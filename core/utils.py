import requests
import time
from core.models import Kline
from django.db.models import Min, Max, Sum
from datetime import datetime, timezone
import pandas as pd

BINANCE_BASE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MAPPING = {
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440
}

def get_historical_klines(symbol, interval, limit=1000):
    """
    Récupère l'historique des Klines pour une paire donnée.
    """
    url = f"{BINANCE_BASE_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        return [
            {
                "timestamp": kline[0],  # Timestamp de la bougie
                "open": float(kline[1]),  # Prix d'ouverture
                "high": float(kline[2]),  # Plus haut
                "low": float(kline[3]),  # Plus bas
                "close": float(kline[4]),  # Prix de fermeture
                "volume": float(kline[5])  # Volume échangé
            }
            for kline in data
        ]
    else:
        print(f"Erreur API Binance: {response.status_code} - {response.text}")
        return []

from core.models import Kline
from django.db.models import Min, Max, Sum
from datetime import datetime

INTERVAL_MAPPING = {
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440
}

def aggregate_higher_timeframe_klines(symbol):
    """
    Met à jour dynamiquement les Klines supérieures (3m, 5m, 15m, ...) dès qu'une nouvelle 1m arrive.
    """
    last_kline = Kline.objects.filter(symbole=symbol, intervalle="1m").order_by("-timestamp").first()
    if not last_kline:
        return

    last_timestamp = last_kline.timestamp

    for interval, minute_count in INTERVAL_MAPPING.items():
        aligned_timestamp = last_timestamp - (last_timestamp % (minute_count * 60 * 1000))  # Alignement du timestamp

        klines = Kline.objects.filter(
            symbole=symbol, intervalle="1m",
            timestamp__gte=aligned_timestamp
        ).order_by("timestamp")

        if klines.count() < minute_count:
            continue  # On attend d'avoir assez de bougies

        open_price = klines.first().open_price
        high_price = klines.aggregate(Max("high_price"))["high_price__max"]
        low_price = klines.aggregate(Min("low_price"))["low_price__min"]
        close_price = klines.last().close_price
        volume = klines.aggregate(Sum("volume"))["volume__sum"]

        Kline.objects.update_or_create(
            symbole=symbol, intervalle=interval, timestamp=aligned_timestamp,
            defaults={
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "volume": volume
            }
        )

        print(f"[{datetime.fromtimestamp(aligned_timestamp/1000, tz=timezone.utc)}] {symbol} {interval} Kline générée")
        rsi_value = calculate_rsi(symbol, interval)
        print(f"RSI {interval} pour {symbol} : {rsi_value}")


def calculate_rsi(symbol, interval, period=6):
    """
    Calcule le RSI pour une paire et un intervalle donné.
    """
    klines = Kline.objects.filter(symbole=symbol, intervalle=interval).order_by("-timestamp")[:period + 1]
    
    if len(klines) < period + 1:
        return None  # Pas assez de données

    df = pd.DataFrame(list(klines.values("close_price")))
    df["delta"] = df["close_price"].diff()

    gain = (df["delta"].where(df["delta"] > 0, 0)).rolling(window=period).mean()
    loss = (-df["delta"].where(df["delta"] < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi.iloc[-1], 2)  # Retourne le dernier RSI calculé
