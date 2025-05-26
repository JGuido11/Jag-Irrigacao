import os
import sys
import json
import requests
import configparser
import datetime
import RPi.GPIO as GPIO

from time import sleep
from calendar import timegm
from datetime import timezone, datetime, timedelta

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

def carregar_config(nome_arq='config'):
    """Lê e retorna as configurações do arquivo de configuração."""
    config = configparser.RawConfigParser(allow_no_value=False)
    esse_dir = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(esse_dir, nome_arq)
    if not os.path.exists(config_path):
        print(f'Arquivo de configuração {nome_arq} não encontrado.')
        print(f'Certifique-se que o arquivo chamado config está localizado no diretório {esse_dir}')
        raise FileNotFoundError(f'Arquivo de configuração {nome_arq} não encontrado.')
    config.read(config_path, encoding='utf-8')
    if config.has_section('Configuracao_Irrigacao'):
        return {nome: val for (nome, val) in config.items('Configuracao_Irrigacao')}
    else:
        print(f'Não foi possível ler o arquivo {nome_arq} com a seção Configuracao_Irrigacao')
        print(f'Certifique-se que o arquivo chamado config está localizado no diretório {esse_dir}')
        raise Exception('Não foi possível encontrar o arquivo config')

def get_clima_hist(config, timestamp_dt):
    """Obtém histórico meteorológico da API do Open Weather."""
    API_URL = (
        'https://api.openweathermap.org/data/2.5/onecall/timemachine'
        '?lat={lat}&lon={lon}&dt={day}&appid={key}'
    )
    resp = requests.get(API_URL.format(
        key=config['api_key'],
        day=timestamp_dt,
        lat=config['lat'],
        lon=config['lon']
    ))
    weather_data = resp.json()
    return {
        x.get('dt'): x.get('rain', {}).get('1h', 0)
        for x in weather_data.get('hourly', [])
        if x.get('rain') and x.get('dt') >= timestamp_dt
    }

def get_clima(config, timestamp_dt):
    """Obtém clima atual da API do Open Weather."""
    API_URL = (
        'https://api.openweathermap.org/data/2.5/onecall'
        '?lat={lat}&lon={lon}&dt={day}&appid={key}'
    )
    resp = requests.get(API_URL.format(
        key=config['api_key'],
        day=timestamp_dt,
        lat=config['lat'],
        lon=config['lon']
    ))
    weather_data = resp.json()
    curr_rain = {}
    curr = weather_data.get('current')
    if curr and curr.get('rain'):
        curr_rain = {timestamp_dt: curr['rain'].get('1h', 0)}
    chuva_por_hora = {
        x.get('dt'): x.get('rain', {}).get('1h', 0)
        for x in weather_data.get('hourly', [])
        if x.get('rain') and x.get('dt') < timestamp_dt
    }
    chuva_por_hora.update(curr_rain)
    return chuva_por_hora

def get_ind_pluv_no_intervalo(config, time_win_hr=24):
    """Calcula a pluviosidade das últimas 24 horas."""
    ontem_timestamp = timegm(
        (timezone() - timedelta(hours=time_win_hr)).utctimetuple()
    )
    hoje_timestamp = timegm(datetime.now(timezone.utc).utctimetuple())
    try:
        chuva_por_hora_ontem = get_clima_hist(config, ontem_timestamp)
    except Exception as ex:
        print(f"Erro ao obter clima histórico: {ex}")
        return None
    try:
        chuva_por_hora_hoje = get_clima(config, hoje_timestamp)
    except Exception as ex:
        print(f"Erro ao obter clima atual: {ex}")
        return None
    try:
        chuva_por_hora_ontem.update(chuva_por_hora_hoje)
        total = sum(chuva_por_hora_ontem.values())
    except Exception as ex:
        print(f"Erro ao calcular total de chuva: {ex}")
        return None
    return total

def irrigacao(config):
    """Ativa a irrigação."""
    pin = int(config['gpio_starter'])
    led = int(config['gpio_led1'])
    runtime = float(config['runtime_min'])
    with open(config['log'], 'a') as log:
        try:
            GPIO.setup((pin, led), GPIO.OUT)
            log.write(f'{datetime.now().strftime('%Y-%m-%d %H:%M')}: Iniciando irrigação\n')
            GPIO.output((pin, led), GPIO.HIGH)
            sleep(runtime * 60)
            log.write(f'{datetime.now().strftime('%Y-%m-%d %H:%M')}: Parando irrigação\n')
            GPIO.output((pin, led), GPIO.LOW)
        except Exception as ex:
            log.write(f'{datetime.now().strftime('%Y-%m-%d %H:%M')}: Um erro ocorreu: {ex}\n')
            GPIO.output((pin, led), GPIO.LOW)

def main():
    """Fluxo principal do programa."""
    config = carregar_config()
    with open(config['log'], 'a') as log:
        ind_pluv = get_ind_pluv_no_intervalo(config)
        if ind_pluv is None:
            log.write(f'{datetime.now().strftime('%Y-%m-%d %H:%M')}: Erro ao adquirir índice pluviométrico, definindo índice como 0.0 mm\n')
            ind_pluv = 0.0
        else:
            log.write(f'{datetime.now().strftime('%Y-%m-%d %H:%M')}: Índice pluviométrico: {ind_pluv:.2f} mm\n')
    if ind_pluv <= float(config['rain_threshold_mm']):
        irrigacao(config)

def test_api():
    """Testa o acesso à API."""
    config = carregar_config()
    total = get_ind_pluv_no_intervalo(config)
    if total is None:
        print("API está funcionando, porém não foi possível obter pluviosidade. Verifique se o tipo de API correto está sendo utilizado.")
    else:
        print(f"API está funcionando, pluviosidade das últimas 24 horas={total:.2f}")

def force_run():
    """Força a irrigação sem checar índice pluviométrico."""
    config = carregar_config()
    irrigacao(config)

def reset():
    """Reseta todos os GPIO pins para LOW."""
    config = carregar_config()
    pin = int(config['gpio_starter'])
    led = int(config['gpio_led1'])
    GPIO.setup((pin, led), GPIO.OUT)
    GPIO.output((pin, led), GPIO.LOW)

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        main()
    elif args[0] == 'test':
        test_api()
    elif args[0] == 'force':
        force_run()
    elif args[0] == 'reset':
        reset()
    else:
        print("Comando desconhecido", sys.argv)