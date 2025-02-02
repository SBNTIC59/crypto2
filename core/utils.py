import requests
import time
from core.models import Kline, Indicator
from django.db.models import Min, Max, Sum
from datetime import datetime, timezone
import pandas as pd
import threading
import numpy as np

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
    
def aggregate_higher_timeframe_klines(symbole):
    print(f"🔄 [DEBUG] Agrégation des Klines supérieures pour {symbole}...")

    intervals = {"3m": 3, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}

    for interval, factor in intervals.items():
        print(f"  ➡️ Agrégation pour {interval} (nécessite {factor} bougies 1m)")

        # Récupérer la dernière bougie 1m en base
        last_kline_1m = Kline.objects.filter(symbole=symbole, intervalle="1m").order_by("-timestamp").first()
        if not last_kline_1m:
            print(f"⚠️ Aucune bougie 1m disponible pour {symbole}, impossible d'agréger {interval}")
            continue

        last_timestamp = last_kline_1m.timestamp

        # Trouver le timestamp de début du nouvel intervalle
        aligned_timestamp = last_timestamp - (last_timestamp % (factor * 60 * 1000))

        # Récupérer toutes les bougies 1m qui appartiennent à cet intervalle
        klines_1m = list(Kline.objects.filter(
            symbole=symbole,
            intervalle="1m",
            timestamp__gte=aligned_timestamp
        ).order_by("timestamp"))

        print(f"  🔍 {len(klines_1m)} bougies 1m trouvées pour {interval}")

        if len(klines_1m) < factor:
            print(f"⚠️ Pas assez de bougies 1m alignées pour générer {interval} ({len(klines_1m)} trouvées)")
            continue

        open_price = klines_1m[0].open_price
        close_price = klines_1m[-1].close_price
        high_price = max(k.high_price for k in klines_1m)
        low_price = min(k.low_price for k in klines_1m)
        volume = sum(k.volume for k in klines_1m)

        # Insérer ou mettre à jour la Kline agrégée
        kline, created = Kline.objects.update_or_create(
            symbole=symbole,
            intervalle=interval,
            timestamp=aligned_timestamp,
            defaults={
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "volume": volume,
            }
        )

        if created:
            print(f"✅ Nouvelle Kline {interval} créée pour {symbole} à {aligned_timestamp}")
        else:
            print(f"♻️ Kline {interval} mise à jour pour {symbole} à {aligned_timestamp}")

def calculate_indicators(symbol, interval):
    """
    Calcule le MACD, RSI et les bandes de Bollinger pour un symbole donné et un intervalle.
    """
    print(f"📊 Début du calcul des indicateurs pour {symbol} ({interval})")
    klines = list(Kline.objects.filter(symbole=symbol, intervalle=interval).order_by("timestamp").values())

    if len(klines) < 50:  # Assurez-vous d'avoir assez de données
        return None

    df = pd.DataFrame(klines)
    df["close_price"] = df["close_price"].astype(float)

    # ✅ Calcul du MACD
    short_ema = df["close_price"].ewm(span=12, adjust=False).mean()
    long_ema = df["close_price"].ewm(span=26, adjust=False).mean()
    df["macd"] = short_ema - long_ema
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    # ✅ Calcul du RSI
    delta = df["close_price"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # ✅ Calcul du StochRSI
    min_rsi = df["rsi"].rolling(window=14).min()
    max_rsi = df["rsi"].rolling(window=14).max()
    df["stoch_rsi"] = (df["rsi"] - min_rsi) / (max_rsi - min_rsi)

    # ✅ Calcul des Bollinger Bands
    df["bollinger_middle"] = df["close_price"].rolling(window=20).mean()  # ✅ Ajout de la bande médiane
    rolling_std = df["close_price"].rolling(window=20).std()
    df["bollinger_upper"] = df["bollinger_middle"] + (rolling_std * 2)
    df["bollinger_lower"] = df["bollinger_middle"] - (rolling_std * 2)    

    latest = df.iloc[-1]  # On prend la dernière ligne
    print(f"📌 Derniers indicateurs pour {symbol} ({interval}):")
    print(f"  MACD: {latest['macd']:.2f}, MACD Signal: {latest['macd_signal']:.2f}")
    print(f"  RSI: {latest['rsi']:.2f}")
    print(f"  Bollinger: {latest['bollinger_lower']:.2f} - {latest['bollinger_upper']:.2f}")

    # ✅ Enregistrement en base
    Indicator.objects.update_or_create(
        symbole=symbol,
        intervalle=interval,
        timestamp=int(latest["timestamp"]),
        defaults={
            "macd": latest["macd"],
            "macd_signal": latest["macd_signal"],
            "rsi": latest["rsi"],
            "stoch_rsi": latest["stoch_rsi"],
            "bollinger_upper": latest["bollinger_upper"],
            "bollinger_middle": latest["bollinger_middle"],
            "bollinger_lower": latest["bollinger_lower"],
        }
    )

    return latest

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