import calendar
import configparser
import datetime
import json
import os
import requests
import sys

from time import sleep
import RPi.GPIO as GPIO
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

# Faz a leitura do arquivo de configuração
def carregar_config(nome_arq='config'):
  config = configparser.RawConfigParser()
  esse_dir = os.path.abspath(os.path.dirname(__file__))
  config.read(esse_dir + '/' + nome_arq)
  if config.has_section('Configuracao_Irrigacao'):
      return {nome:val for (nome, val) in config.items('Configuracao_Irrigacao')}
  else:
      print('Não foi possível ler o arquivo %s com a seção Configuracao_Irrigacao' % nome_arq)
      print('Certifique-se que o arquivo chamado config está localizado no diretório' %s % esse_dir)
      raise Exception('Não foi possível encontrar o arquivo config')


# Pede o histórico metereológico da API do Open Weather
def get_clima_hist(config, timestamp_dt):
    API_URL = 'https://api.openweathermap.org/data/2.5/onecall/timemachine?lat={lat}&lon={lon}&dt={day}&appid={key}'
    hist_clima = requests.get(API_URL.format(key=config['api_key'],
                                       day=timestamp_dt,
                                       lat=config['lat'],
                                       lon=config['lon']))
    weather_data = json.loads(hist_clima.content.decode('utf-8'))
    chuva_por_hora = {x.get('dt'): x.get('rain').get('1h') for x in weather_data.get('hourly') if x.get('rain') and x.get('dt') >= timestamp_dt}
    return chuva_por_hora

def get_clima(config, timestamp_dt):
    API_URL = 'https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={lon}&dt={day}&appid={key}'
    clima_hoje = requests.get(API_URL.format(key=config['api_key'],
                                       day=timestamp_dt,
                                       lat=config['lat'],
                                       lon=config['lon']))
    weather_data = json.loads(clima_hoje.content.decode('utf-8'))
    curr_rain = {}  
    curr = weather_data.get('current')

    if curr:
      rain = curr.get('rain', 0)
      if rain:
        curr_rain = {timestamp_dt: rain.get('1h', 0)}

    chuva_por_hora = {x.get('dt'): x.get('rain').get('1h') for x in weather_data.get('hourly') if x.get('rain') and x.get('dt') < timestamp_dt}
    chuva_por_hora.update(curr_rain)
    return chuva_por_hora

# Define a pluviosidade das ultimas 24hr usando a API do Open Weather
def get_ind_pluv_no_intervalo(config, time_win_hr=24):
    # Obtém data UTC de ontem e converte para Unix timestamp
    ontem_timestamp = calendar.timegm((
      datetime.datetime.utcnow() - \
      datetime.timedelta(hours=time_win_hr)).utctimetuple())
    # Obtém data UTC de hoje e converte para Unix timestamp
    hoje_timestamp = calendar.timegm(
      datetime.datetime.utcnow().utctimetuple())

    
    # Obtém valores de hoje e ontem
    try:
        chuva_por_hora_ontem = get_clima_hist(config, ontem_timestamp)
    except Exception as ex: 
        print(ex)
        return None
    try:
        chuva_por_hora_hoje = get_clima(config, hoje_timestamp)
    except Exception as ex:
        print(ex)
        return None
   
    try: 
        total = 0   
        chuva_por_hora_ontem.update(chuva_por_hora_hoje)
        total += sum(chuva_por_hora_ontem.values())
    except Exception as ex:
        pass
    return total

# Inicia a irrigação
def irrigacao(config):
  pin = int(config['gpio_starter'])
  led = int(config['gpio_led1'])
  runtime = float(config['runtime_min'])
  with open(config['log'],'a') as log:
    try:
      GPIO.setup((pin, led), GPIO.OUT)
      log.write('%s: Iniciando irrigação\n' % datetime.datetime.now())
      GPIO.output((pin,led), GPIO.HIGH)
      sleep(runtime * 60) 
      log.write('%s: Parando irrigação\n' % datetime.datetime.now())
      GPIO.output((pin,led), GPIO.LOW)
    except Exception as ex:
      log.write('%s: Um erro ocorreu: %s \n' % (datetime.datetime.now(), ex.message))  
      GPIO.output((pin,led), GPIO.LOW)

# Método principal
#   1.  Lê o arquivo de configuração
#   2.  Checa o índice pluviométrico das ultimas 24hrs
#   3.  Inicia a irrigação caso o índice esteja abaixo do limite
def main(): 
  # Carrega o arquivo de configuração
  config = carregar_config()
    
  with open(config['log'],'a') as log:
    # Obtém precipitação das últimas 24hrs
    ind_pluv = get_ind_pluv_no_intervalo(config)
    if ind_pluv is None:
      log.write('%s: Erro ao adquirir índice pluviométrico, definindo índice como 0.0 mm\n' % datetime.datetime.now())
      ind_pluv = 0.0
    else:
      log.write('%s: Índice pluviométrico: %f in\n' % (datetime.datetime.now(), ind_pluv))
    
  # Se isso for menor do que o limite inicia a irrigação
  if ind_pluv <= float(config['rain_threshold_mm']):
    irrigacao(config)

# Testa o acesso à API
def test_api():
  config = carregar_config()
  total = get_ind_pluv_no_intervalo(config)

  if total is None:
    print("API está funcionando, porém não foi possível obter pluviosidade. Verifique se o tipo de API correto está sendo utilizado ")
    return
    
  print("API está funcionando, pluviosidade das últimas 24 horas=%f" % (total))  
    
# Inicia irrigação sem checar índice pluviométrico
def force_run():
  config = carregar_config()
  irrigacao(config)
  
# Seta todos os GPIO pins como GPIO.LOW. Deve ser executado quando o raspberry pi boota
def reset():
    config = carregar_config()
    pin = int(config['gpio_starter'])
    led = int(config['gpio_led1'])
    GPIO.setup((pin, led), GPIO.OUT)
    GPIO.output((pin,led), GPIO.LOW)      
    
if __name__ == "__main__":
  if len(sys.argv) == 1:
    # Modo padrão
    main()
  elif len(sys.argv) == 2 and sys.argv[1] == 'test':
    # Testa a conexão com a API
    # Necessário executar como root para que funcione
    test_api()
  elif len(sys.argv) == 2 and sys.argv[1] == 'force':
    # Inicia irrigação independete do valor de ind_pluv
    force_run()
  elif len(sys.argv) == 2 and sys.argv[1] == 'reset':
    # Seta pin e leds GPIOS como GPIO.LOW
    reset()
  else:
    print("Comando desconhecido", sys.argv)
        
        
    
    
    
    