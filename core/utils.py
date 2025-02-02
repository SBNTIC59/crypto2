import requests
import time
from core.models import Kline
from django.db.models import Min, Max, Sum
from datetime import datetime, timezone
import pandas as pd
import threading

loaded_symbols = {}
print(f"✅ [DEBUG] loaded_symbols défini dans utils : {loaded_symbols}")
loaded_symbols_lock = threading.Lock()#

BINANCE_BASE_URL = "https://api.binance.com/api/v3"
BINANCE_BASE_URL_klines = BINANCE_BASE_URL + "/klines"
BINANCE_BASE_URL_liste  =  BINANCE_BASE_URL +"/exchangeInfo"

INTERVAL_MAPPING = {
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440
}

def get_loaded_symbols():
    global loaded_symbols
    return loaded_symbols

def get_all_usdt_pairs():
    """
    Récupère toutes les paires USDT disponibles sur Binance.
    """
    response = requests.get(BINANCE_BASE_URL_liste)
    if response.status_code == 200:
        data = response.json()
        symbols = [s["symbol"] for s in data["symbols"] if s["symbol"].endswith("USDT")]
        print(f"✅ {len(symbols)} paires USDT trouvées.")
        return symbols
    else:
        print(f"❌ Erreur lors de la récupération des paires Binance: {response.status_code}")
        return []

def load_historical_klines():
    """
    Charge l'historique des Klines pour toutes les paires USDT.
    """
    from core.utils import get_historical_klines

    symbols = get_all_usdt_pairs()
    for symbol in symbols:
        print(f"🔄 Chargement des Klines pour {symbol}...")
        get_historical_klines(symbol, "1m")

def get_historical_klines(symbol, interval, limit=1000):
    """
    Récupère l'historique des Klines pour une paire donnée.
    """
    global loaded_symbols
    klines_to_insert = [] 
    url = f"{BINANCE_BASE_URL_klines}?symbol={symbol}&interval={interval}&limit={limit}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        for kline in data:
            klines_to_insert.append(Kline(
                symbole=symbol,
                intervalle=interval,
                timestamp=kline[0],
                open_price =float(kline[1]),
                high_price= float(kline[2]),
                low_price= float(kline[3]),
                close_price= float(kline[4]),
                volume= float(kline[5])
                
            ))
        if klines_to_insert:  # 🔥 Vérifier qu'on n'insère pas une liste vide
            Kline.objects.bulk_create(klines_to_insert, ignore_conflicts=True)
            print(f"✅ {interval} chargé pour {symbol} (total: {len(klines_to_insert)} Klines)")


        # ✅ Activer le témoin APRÈS le dernier intervalle
        with loaded_symbols_lock:
            loaded_symbols[symbol] = True
        #print(f"loaded symbol aprés activation d'une monnaie{loaded_symbols}")
        print(f"🚀 {symbol} est maintenant actif !")

    else:
        print(f"❌ Erreur API Binance ({interval}) : {response.status_code} - {response.text}")        
    


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

def calculate_macd(symbol, interval, short_window=12, long_window=26, signal_window=9):
    """
    Calcule le MACD pour une paire et un intervalle donné.
    """
    from core.models import Kline

    klines = Kline.objects.filter(symbole=symbol, intervalle=interval).order_by("timestamp")
    
    if len(klines) < long_window:
        return None  # Pas assez de données

    df = pd.DataFrame(list(klines.values("timestamp", "close_price")))
    
    df["EMA_12"] = df["close_price"].ewm(span=short_window, adjust=False).mean()
    df["EMA_26"] = df["close_price"].ewm(span=long_window, adjust=False).mean()
    df["MACD"] = df["EMA_12"] - df["EMA_26"]
    df["Signal_Line"] = df["MACD"].ewm(span=signal_window, adjust=False).mean()

    return df.iloc[-1]["MACD"], df.iloc[-1]["Signal_Line"]

def calculate_bollinger_bands(symbol, interval, window=20):
    """
    Calcule les bandes de Bollinger pour une paire et un intervalle donné.
    """
    from core.models import Kline

    klines = Kline.objects.filter(symbole=symbol, intervalle=interval).order_by("timestamp")

    if len(klines) < window:
        return None  # Pas assez de données

    df = pd.DataFrame(list(klines.values("timestamp", "close_price")))
    
    df["SMA"] = df["close_price"].rolling(window=window).mean()
    df["STD"] = df["close_price"].rolling(window=window).std()
    
    df["Upper_Band"] = df["SMA"] + (df["STD"] * 2)
    df["Lower_Band"] = df["SMA"] - (df["STD"] * 2)

    return df.iloc[-1]["Upper_Band"], df.iloc[-1]["Lower_Band"]