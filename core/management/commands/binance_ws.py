from django.core.management.base import BaseCommand
import websocket
import sys
import os
import json
from core.models import Kline
from core.utils import aggregate_higher_timeframe_klines
from datetime import datetime, timezone
import django

# Aller au dossier du projet Django (contenant manage.py)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

# Définir les paramètres Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trade_binance.settings")

django.setup()

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
print("✅ WebSocket Binance en cours de connexion...")



def on_message(ws, message):
    data = json.loads(message)
    kline = data.get("k", {})

    if kline and kline["x"]:  # Vérifier que la bougie est fermée
        symbole = kline["s"]
        timestamp = kline["t"]
        open_price = float(kline["o"])
        high_price = float(kline["h"])
        low_price = float(kline["l"])
        close_price = float(kline["c"])
        volume = float(kline["v"])

        # Sauvegarde en base de données
        kline_obj, created = Kline.objects.update_or_create(
            symbole=symbole, intervalle="1m", timestamp=timestamp,
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

def on_open(ws):
    print("🔄 Connexion au WebSocket Binance établie...")
    symbols = ["btcusdt", "ethusdt", "bnbusdt", "adausdt", "xrpusdt"]  # Paires à écouter
    streams = [f"{symbol}@kline_1m" for symbol in symbols]
    params = {"method": "SUBSCRIBE", "params": streams, "id": 1}
    ws.send(json.dumps(params))
    print(f"✅ Abonnement aux streams : {streams}")

class Command(BaseCommand):
    help = "Lance le WebSocket Binance"

    def handle(self, *args, **kwargs):
        print("🚀 Lancement du WebSocket Binance via `manage.py`...")
        ws = websocket.WebSocketApp(BINANCE_WS_URL, on_message=on_message)
        ws.on_open = on_open
        ws.run_forever()
