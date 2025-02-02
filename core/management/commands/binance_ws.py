from django.core.management.base import BaseCommand
import websocket
import sys
import os
import json
from core.models import Kline
from core.utils import aggregate_higher_timeframe_klines, loaded_symbols, loaded_symbols_lock, calculate_indicators

from datetime import datetime, timezone
import django
from threading import Thread
import threading

#loaded_symbols = {}  # Dictionnaire pour savoir quelles monnaies sont prêtes
#loaded_symbols_lock = threading.Lock()

# Aller au dossier du projet Django (contenant manage.py)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

# Définir les paramètres Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trade_binance.settings")

django.setup()

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
print("✅ WebSocket Binance en cours de connexion...")



def on_message(ws, message):
    #print(f"📩 Message reçu brut : {message[:200]}...")  # Afficher un extrait du message
    #global loaded_symbols
    global loaded_symbols_lock
    data = json.loads(message)
    kline = data.get("k", {})
    #print(f"kline = {kline}")
    symbole = kline["s"]
    #print(f"Symbole{symbole}")
    #if 'loaded_symbols' not in globals():
    #    print("❌ [ERREUR] loaded_symbols n'existe pas dans les variables globales !")
    #    return
    
    #try:
    #    print(f"📜 loaded_symbols AVANT vérification et sans verrou dans on_message: {loaded_symbols}")
    #except Exception as e:
    #    print(f"❌ [ERREUR] Impossible d'afficher loaded_symbols : {e}")
    with loaded_symbols_lock:
        #print(f"📜 loaded_symbols AVANT vérification et avec verrou dans on_message: {loaded_symbols}")
        if symbole not in loaded_symbols or not loaded_symbols[symbole]:
            print(f"⏳ {symbole} ignoré (historique non chargé)...")
            return
    print(f"apres le test de passage en tps reel de la monnaie {symbole}")
    symbole = kline["s"]
    timestamp = kline["t"]
    open_price = float(kline["o"])
    high_price = float(kline["h"])
    low_price = float(kline["l"])
    close_price = float(kline["c"])
    volume = float(kline["v"])
    # Sauvegarde en base de données
    kline_instance, created = Kline.objects.update_or_create(
        symbole=symbole,
        intervalle="1m",
        timestamp=timestamp,
        defaults={
            "open_price": open_price,
            "high_price": high_price,
            "low_price": low_price,
            "close_price": close_price,
            "volume": volume
        }
        )       
        
        

    print(f"[{datetime.fromtimestamp(timestamp/1000, tz=timezone.utc)}] {symbole} 1m - O:{open_price} H:{high_price} L:{low_price} C:{close_price}")
    # Mettre à jour les Klines supérieures dès la réception de la bougie 1m
    aggregate_higher_timeframe_klines(symbole)
    for interval in ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]:
       result = calculate_indicators(symbole, interval)
       if result:
            print(f"📊 {symbole} {interval} - MACD: {result['macd']:.2f}, RSI: {result['rsi']:.2f}, Bollinger: [{result['bollinger_lower']:.2f}, {result['bollinger_upper']:.2f}]")

def on_close(ws, close_status_code, close_msg):
    print(f"❌ WebSocket fermé ! Code: {close_status_code}, Message: {close_msg}")

def on_open(ws):
    print("✅ Connexion WebSocket Binance établie...")

    # Récupérer toutes les paires en USDT enregistrées en base
    from core.models import Kline
    symbols = list(Kline.objects.values_list("symbole", flat=True).distinct())

    if not symbols:
        print("❌ Aucune monnaie trouvée en base. Veuillez initialiser l'historique.")
        return

    print(f"🔍 Nombre total de monnaies en base (message de def_open) : {len(symbols)}")

    streams = [f"{symbol.lower()}@kline_1m" for symbol in symbols]

    # Respecter la limite de Binance (50 flux par WebSocket, 5 WebSockets max)
    max_per_ws = 50
    if len(streams) > max_per_ws:
        print(f"⚠️ Trop de monnaies ({len(streams)}) ! Seuls les {max_per_ws} premiers seront pris.")
        streams = streams[:max_per_ws]  # Coupe à 50 flux max

    params = {"method": "SUBSCRIBE", "params": streams, "id": 1}
    print(f"🛰️ Envoi des abonnements WebSocket : {params}")  # 🔥 LOG CRUCIAL

    
    ws.send(json.dumps(params))
    print(f"✅ Abonnement aux streams : {streams}")

class Command(BaseCommand):
    help = "Lance le WebSocket Binance"

    def handle(self, *args, **kwargs):
        print("🚀 Lancement du WebSocket Binance via `manage.py`...")
        
        # Lancer le WebSocket en arrière-plan
        ws = websocket.WebSocketApp(
            BINANCE_WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_close=on_close
        )
        Thread(target=ws.run_forever).start()

        # Lancer l'historique des Klines en parallèle
        from core.utils import load_historical_klines
        Thread(target=load_historical_klines).start()






