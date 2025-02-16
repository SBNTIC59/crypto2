import requests
import time
from core.models import Kline, Indicator, Indicator, TradeLog, APIKey, Strategy, Monnaie
from django.db.models import Min, Max, Sum, Avg, Count
from datetime import datetime, timezone
import pandas as pd
import threading
import numpy as np
import operator
import decimal
from django.utils.timezone import now
from django.db import transaction
import talib


sell_conditions_lock = threading.Lock()
OPERATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq
}
INVESTMENT_AMOUNT = decimal.Decimal("100")

loaded_symbols = {}
print(f"✅ [DEBUG] loaded_symbols défini dans utils : {loaded_symbols}")
loaded_symbols_lock = threading.Lock()#


BINANCE_BASE_URL = "https://api.binance.com/api/v3"
BINANCE_KLINES_URL = BINANCE_BASE_URL + "/klines"

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

#def load_historical_klines():
#    """
#    Charge l'historique des Klines pour toutes les paires USDT.
#    """
#    from core.utils import get_historical_klines
#
#    symbols = get_all_usdt_pairs()
#    for symbol in symbols:
#        print(f"🔄 Chargement des Klines pour {symbol}...")
#        get_historical_klines(symbol, "1m")
#
def get_historical_klines(symbol, interval, limit=1000):
    """
    Récupère l'historique des Klines depuis Binance avec gestion des erreurs.
    """
    api_key, secret_key = get_binance_credentials()
    if not api_key or not secret_key:
        print("❌ Impossible de récupérer les Klines : Clés API manquantes.")
        return []

    headers = {"X-MBX-APIKEY": api_key}
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    
    for _ in range(3):  # 🔄 Retry 3 fois en cas d'erreur
        try:
            response = requests.get(BINANCE_KLINES_URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()  # Lève une erreur si le code HTTP est != 200
            return response.json()
        except requests.exceptions.Timeout:
            print(f"⚠️ Timeout Binance pour {symbol} {interval}, tentative de reconnexion...")
            time.sleep(5)
        except requests.exceptions.HTTPError as e:
            print(f"❌ Erreur API Binance ({symbol}, {interval}) : {e}")
            return []
        except Exception as e:
            print(f"⚠️ Erreur inattendue : {e}")
            return []

    print(f"❌ Impossible de récupérer les Klines après 3 tentatives ({symbol}, {interval}).")
    return []

def load_historical_klines():
    """
    Charge l'historique des Klines pour toutes les paires USDT et tous les intervalles nécessaires.
    """
    symbols = get_all_usdt_pairs()
    intervals = ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]

    for symbol in symbols:
        #print(f"🔄 Chargement des Klines pour {symbol}...")
        for interval in intervals:
            klines = get_historical_klines(symbol, interval)
            if klines:
                save_klines_to_db(symbol, interval, klines)
                calculate_indicators(symbol)
                Monnaie.objects.filter(symbole=symbol).update(init=True)

def save_klines_to_db(symbol, interval, klines):
    """
    Enregistre les Klines récupérées en base de données.
    """
    klines_to_insert = [
        Kline(
            symbole=symbol,
            intervalle=interval,
            timestamp=k[0],
            open_price=float(k[1]),
            high_price=float(k[2]),
            low_price=float(k[3]),
            close_price=float(k[4]),
            volume=float(k[5])
        ) for k in klines
    ]

    Kline.objects.bulk_create(klines_to_insert, ignore_conflicts=True)
    #print(f"✅ {len(klines_to_insert)} Klines enregistrées pour {symbol} ({interval})")

def aggregate_higher_timeframe_klines(symbole, kline_1m):
    """
    Met à jour les Klines des intervalles supérieurs (3m, 5m...) à partir de la dernière Kline 1m reçue.
    """
    intervals = {
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }

    timestamp_1m = kline_1m.timestamp
    open_price_1m = kline_1m.open_price
    high_price_1m = kline_1m.high_price
    low_price_1m = kline_1m.low_price
    close_price_1m = kline_1m.close_price
    volume_1m = kline_1m.volume

    for interval, duration in intervals.items():
        # Timestamp group correspondant à cette Kline 1m pour l'intervalle
        timestamp_group = timestamp_1m - (timestamp_1m % (duration * 60 * 1000))

        # Chercher la Kline actuelle sur cet intervalle
        aggregated_kline, created = Kline.objects.get_or_create(
            symbole=symbole,
            intervalle=interval,
            timestamp=timestamp_group,
            defaults={
                'open_price': open_price_1m,
                'high_price': high_price_1m,
                'low_price': low_price_1m,
                'close_price': close_price_1m,
                'volume': volume_1m,
            }
        )

        if not created:
            # Mise à jour de la Kline si elle existait déjà (encore en cours)
            aggregated_kline.high_price = max(aggregated_kline.high_price, high_price_1m)
            aggregated_kline.low_price = min(aggregated_kline.low_price, low_price_1m)
            aggregated_kline.close_price = close_price_1m
            aggregated_kline.volume += volume_1m
            aggregated_kline.save()

        # Détecter la fin de la période pour finaliser proprement
        next_1m_timestamp = timestamp_1m + 60 * 1000
        next_timestamp_group = next_1m_timestamp - (next_1m_timestamp % (duration * 60 * 1000))

        if next_timestamp_group != timestamp_group:
            # On considère que la bougie précédente est clôturée
            calculate_indicators(symbole, interval)


def calculate_indicators(symbole, interval=None):
    intervals = [interval] if interval else ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]

    for interval in intervals:
        klines = Kline.objects.filter(symbole=symbole, intervalle=interval).order_by("-timestamp")[:50]

        if len(klines) < 26:
            continue

        closes = np.array([float(k.close_price) for k in reversed(klines)])
        highs = np.array([float(k.high_price) for k in reversed(klines)])
        lows = np.array([float(k.low_price) for k in reversed(klines)])

        macd, macd_signal, _ = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        rsi = talib.RSI(closes, timeperiod=14)
        fastk, fastd = talib.STOCHRSI(closes, timeperiod=14, fastk_period=3, fastd_period=3, fastd_matype=0)
        upper, middle, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)

        last_kline = klines[0]
        Indicator.objects.update_or_create(
            symbole=symbole,
            intervalle=interval,
            timestamp=last_kline.timestamp,
            defaults={
                'macd': macd[-1],
                'macd_signal': macd_signal[-1],
                'rsi': rsi[-1],
                'stoch_rsi': fastk[-1],
                'bollinger_upper': upper[-1],
                'bollinger_middle': middle[-1],
                'bollinger_lower': lower[-1],
            }
        )

import pandas as pd
import numpy as np

def calculate_stoch_rsi(symbol, interval, rsi_length=14, stoch_length=14, smooth_k=3):
    # Récupération des Klines (assurez-vous d'avoir les bons champs dans votre modèle)
    klines = Kline.objects.filter(symbole=symbol, intervalle=interval).order_by("-timestamp")[:rsi_length + stoch_length + smooth_k]

    if len(klines) < rsi_length + stoch_length + smooth_k:
        return None  # Pas assez de données

    df = pd.DataFrame(list(klines.values("close_price")))
    df["delta"] = df["close_price"].diff()

    # Calcul du RSI (14 périodes)
    gain = df["delta"].where(df["delta"] > 0, 0).rolling(window=rsi_length).mean()
    loss = -df["delta"].where(df["delta"] < 0, 0).rolling(window=rsi_length).mean()

    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # Calcul du Stoch RSI brut (%K avant lissage)
    min_rsi = df["rsi"].rolling(window=stoch_length).min()
    max_rsi = df["rsi"].rolling(window=stoch_length).max()

    df["stoch_rsi"] = (df["rsi"] - min_rsi) / (max_rsi - min_rsi)
    df["stoch_rsi"] = df["stoch_rsi"].fillna(0)  # Remplacer les NaN par 0 si division par zéro

    # Lissage du %K (SMA sur 3 périodes)
    df["%K"] = df["stoch_rsi"].rolling(window=smooth_k).mean() * 100  # Convertir en %

    # Dernière valeur du %K
    stoch_rsi_k = round(df["%K"].iloc[-1], 2)

    return stoch_rsi_k

def calculate_rsi(symbol, interval, period=6):
    klines = Kline.objects.filter(symbole=symbol, intervalle=interval).order_by("-timestamp")[:period + 1]
    
    if len(klines) < period + 1:
        return None  # Pas assez de données

    df = pd.DataFrame(list(klines.values("close_price")))
    df["delta"] = df["close_price"].diff()

    # Utilisation de l'EMA au lieu de la SMA
    gain = (df["delta"].where(df["delta"] > 0, 0)).ewm(span=period, adjust=False).mean()
    loss = (-df["delta"].where(df["delta"] < 0, 0)).ewm(span=period, adjust=False).mean()

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

def calculate_bollinger_bands(symbole, interval, period=20, std_dev=2):
    """
    Calcule les bandes de Bollinger pour un symbole et un intervalle donné.

    Args:
        symbole (str): Le symbole de la monnaie.
        interval (str): L'intervalle de temps.
        period (int): La période des Bollinger Bands.
        std_dev (float): Le coefficient d'écart-type.

    Returns:
        tuple: (bollinger_middle, bollinger_upper, bollinger_lower)
    """
    klines = Kline.objects.filter(symbole=symbole, intervalle=interval).order_by("-timestamp")[:period]
    
    if len(klines) < period:
        print(f"⚠️ Pas assez de Klines pour calculer les Bollinger Bands ({symbole}, {interval})")
        return None, None, None  # 🔥 Retourne 3 valeurs par sécurité

    closing_prices = np.array([float(k.close_price) for k in klines[::-1]])  # Inverser pour ordre croissant

    middle_band = np.mean(closing_prices)
    std_dev_value = np.std(closing_prices)

    upper_band = middle_band + (std_dev * std_dev_value)
    lower_band = middle_band - (std_dev * std_dev_value)

    return middle_band, upper_band, lower_band  # 🔥 Toujours retourner 3 valeurs

import operator

def get_trade_statistics():
    """
    Renvoie les statistiques globales des trades et par monnaie.
    """
    stats = {}

    # 🔹 Global
    stats["total_trades"] = TradeLog.objects.count()
    stats["open_trades"] = TradeLog.objects.filter(status="open").count()
    stats["closed_trades"] = TradeLog.objects.filter(status="closed").count()

    # 🔹 Statistiques des gains/pertes
    closed_trades = TradeLog.objects.filter(status="closed")
    stats["win_trades"] = closed_trades.filter(trade_result__gt=0).count()
    stats["lose_trades"] = closed_trades.filter(trade_result__lt=0).count()
    stats["min_gain"] = closed_trades.aggregate(Min("trade_result"))["trade_result__min"]
    stats["max_gain"] = closed_trades.aggregate(Max("trade_result"))["trade_result__max"]
    stats["avg_gain"] = closed_trades.aggregate(Avg("trade_result"))["trade_result__avg"]
    stats["cumulative_gain"] = closed_trades.aggregate(Sum("trade_result"))["trade_result__sum"]

    # 🔹 Durée des trades
    stats["min_duration"] = closed_trades.aggregate(Min("duration"))["duration__min"]
    stats["max_duration"] = closed_trades.aggregate(Max("duration"))["duration__max"]
    stats["avg_duration"] = closed_trades.aggregate(Avg("duration"))["duration__avg"]

    # 🔹 Statistiques par monnaie
    symbols = TradeLog.objects.values_list("symbole", flat=True).distinct()
    stats["per_symbol"] = {}

    for symbol in symbols:
        trades = TradeLog.objects.filter(symbole=symbol, status="closed")
        stats["per_symbol"][symbol] = {
            "total": trades.count(),
            "win": trades.filter(trade_result__gt=0).count(),
            "lose": trades.filter(trade_result__lt=0).count(),
            "avg_gain": trades.aggregate(Avg("trade_result"))["trade_result__avg"],
            "max_gain": trades.aggregate(Max("trade_result"))["trade_result__max"],
            "min_gain": trades.aggregate(Min("trade_result"))["trade_result__min"],
            "cumulative_gain": trades.aggregate(Sum("trade_result"))["trade_result__sum"],
        }

    return stats

from core.models import TradeLog

MONTANT_INVESTISSEMENT_FIXE = 100.0  # Ajuste selon ton besoin

def acheter(symbole):
    """
    Exécute un achat seulement si aucune position ouverte n'existe déjà pour cette monnaie.
    """
    existing_trade = TradeLog.objects.filter(symbole=symbole, status="open").exists()
    if existing_trade:
        print(f"⚠️ Achat ignoré pour {symbole}, un trade est déjà en cours.")
        return

    # 🔍 Récupérer le dernier prix de la monnaie
    last_kline = Kline.objects.filter(symbole=symbole, intervalle="1m").order_by("-timestamp").first()
    if not last_kline or not last_kline.close_price:
        print(f"⚠️ Pas de prix disponible pour {symbole}, achat annulé.")
        return

    last_price = last_kline.close_price

    # 🔄 Déterminer le montant à investir
    montant_investissement = MONTANT_INVESTISSEMENT_FIXE  # Peut être dynamique

    # ✅ Calcul de la quantité à acheter
    if last_price > 0:
        quantity = montant_investissement / last_price
    else:
        print(f"⚠️ Impossible de calculer la quantité pour {symbole}, prix invalide.")
        return

    # 🔍 Récupérer la stratégie actuelle de la monnaie
    monnaie = Monnaie.objects.filter(symbole=symbole).first()
    strategy = monnaie.strategy if monnaie else None

    # 🔥 Enregistrement du trade
    trade = TradeLog.objects.create(
        symbole=symbole,
        prix_achat=last_price,
        prix_actuel = last_price,
        prix_max =last_price,
        quantity=quantity,
        investment_amount=montant_investissement,
        status="open",
        strategy=monnaie.strategy if monnaie else None  # 🔄 Nouvelle relation directe
    )

    print(f"🚀 Achat exécuté pour {symbole} à {last_price:.4f} USDT, Quantité: {quantity:.4f}, Investissement: {montant_investissement:.2f} USDT")

def execute_strategies(symbole):
    """
    Vérifie la stratégie d'achat pour une monnaie spécifique lors de la réception d'une Kline.
    """
    from core.models import Monnaie

    monnaie = Monnaie.objects.filter(symbole=symbole).first()

    if not monnaie:
        print(f"❌ Monnaie {symbole} introuvable.")
        return

    if not monnaie.strategy:
        print(f"⚠️ Aucune stratégie définie pour {monnaie.symbole}, pas d'achat.")
        return

    if monnaie.strategy.evaluate_buy(monnaie.symbole):
        print(f"✅ Achat validé pour {monnaie.symbole} selon la stratégie {monnaie.strategy.name}")
        # Ta logique d'achat ici, par exemple :
        acheter(monnaie.symbole)
    else:
        print(f"❌ Achat non validé pour {monnaie.symbole}")

def execute_sell_strategy(symbole=None):
    """
    Vérifie les stratégies de vente et clôture les trades si nécessaire.
    Si symbole est fourni, n'évalue que les trades de cette monnaie.
    """
    from core.models import TradeLog, Monnaie
    update_trade_prices(symbole)

    if symbole:
        open_trades = TradeLog.objects.filter(status="open", symbole=symbole)
    else:
        open_trades = TradeLog.objects.filter(status="open")

    for trade in open_trades:
        monnaie = Monnaie.objects.get(symbole=trade.symbole)
        if monnaie.strategy:
            result = monnaie.strategy.evaluate_sell(trade.symbole, trade)
            if result:
                print(f"✅ Vente validée pour {trade.symbole} selon la stratégie {monnaie.strategy.name}")
                trade.close_trade(trade.prix_actuel)
                trade.status = "closed"
                trade.save()
            else:
                print(f"❌ Vente non validée pour {trade.symbole}")

def get_latest_price(symbole):
    """
    Récupère le dernier prix connu de la monnaie à partir des Klines en base.
    """
    from core.models import Kline

    dernier_kline = Kline.objects.filter(symbole=symbole, intervalle="1m").order_by("-timestamp").first()
    
    if dernier_kline:
        return decimal.Decimal(dernier_kline.close_price)
    
    return None  # Aucun prix trouvé

def update_trade_prices(symbole=None):
    """
    Met à jour le prix actuel et le prix max pour les trades ouverts.
    - Si un symbole est fourni, ne met à jour que ce symbole.
    - Sinon, met à jour tous les trades ouverts.
    """
    trades = TradeLog.objects.filter(status="open")
    if symbole:
        trades = trades.filter(symbole=symbole)

    for trade in trades:
        last_kline = Kline.objects.filter(symbole=trade.symbole, intervalle="1m").order_by("-timestamp").first()

        if last_kline:
            prix_actuel = last_kline.close_price

            if prix_actuel != trade.prix_actuel or prix_actuel > (trade.prix_max or 0) :
                print(f"🔄 Mise à jour prix pour {trade.symbole} : Prix actuel {prix_actuel}, Prix max {max(prix_actuel, trade.prix_max or 0)}")
                trade.prix_actuel = prix_actuel
                trade.prix_max = max(prix_actuel, trade.prix_max  or 0)
                trade.save()
        else:
            print(f"⚠️ Pas de Kline trouvée pour {trade.symbole}, prix non mis à jour.")

def get_binance_credentials():
    """
    Récupère les clés API Binance depuis la base de données.
    """
    try:
        api_key_obj = APIKey.objects.get(name="Binance")
        return api_key_obj.api_key, api_key_obj.secret_key
    except APIKey.DoesNotExist:
        print("❌ Erreur : Aucune clé API Binance trouvée dans la base !")
        return None, None
    



















