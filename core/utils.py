import requests
import time
from core.models import Kline, Indicator, Indicator, SymbolStrategy, TradeLog
from django.db.models import Min, Max, Sum, Avg, Count
from datetime import datetime, timezone
import pandas as pd
import threading
import numpy as np
import operator

OPERATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq
}

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

def get_historical_klines(symbol, interval, limit=5000):
    global loaded_symbols

    print(f"🔄 Chargement de l'historique ({limit} Klines) pour {symbol}...")

    all_klines = []
    last_timestamp = None

    while len(all_klines) < limit:
        request_limit = min(1000, limit - len(all_klines))  # Ne pas dépasser `limit`
        url = f"{BINANCE_BASE_URL}?symbol={symbol}&interval={interval}&limit={request_limit}"
        
        if last_timestamp:
            url += f"&endTime={last_timestamp}"  # Charger des Klines plus anciennes

        response = requests.get(url)
        if response.status_code != 200:
            print(f"❌ Erreur API Binance : {response.status_code} - {response.text}")
            break

        data = response.json()
        if not data:
            break  # Plus de données disponibles

        all_klines.extend(data)
        last_timestamp = data[0][0]  # Mettre à jour `endTime` pour la prochaine requête

    print(f"✅ Total {len(all_klines)} Klines récupérées pour {symbol}")

    # Enregistrer toutes les Klines en base
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
        ) for k in all_klines
    ]

    Kline.objects.bulk_create(klines_to_insert, ignore_conflicts=True)
    loaded_symbols[symbol] = True
    
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

def parse_condition(condition):
    """
    Transforme une condition sous forme de string ("<5") en une fonction et une valeur.
    """
    for op in OPERATORS:
        if condition.startswith(op):
            value = float(condition[len(op):])
            return OPERATORS[op], value
    return None, None

def check_strategy_conditions(symbole, interval, conditions):
    """
    Vérifie si une liste de conditions est remplie pour une monnaie donnée, 
    même si elles concernent plusieurs intervalles.
    """
    # Récupération initiale des indicateurs pour l'intervalle en cours
    latest_indicator = Indicator.objects.filter(symbole=symbole, intervalle=interval).order_by("-timestamp").first()
    
    if not latest_indicator:
        return False  # Pas assez de données pour l'intervalle actuel

    for indicator_key, condition in conditions.items():
        # Extraire l'indicateur et l'intervalle depuis la clé (ex: "stoch_rsi_3m")
        parts = indicator_key.split("_")
        if len(parts) < 2:
            continue  # Format incorrect

        indicator_name = "_".join(parts[:-1])  # ex: "stoch_rsi"
        interval_check = parts[-1]  # ex: "3m"

        # ✅ Si l'intervalle demandé n'est pas celui en cours, charger l'indicateur correct
        if interval_check != interval:
            latest_indicator = Indicator.objects.filter(symbole=symbole, intervalle=interval_check).order_by("-timestamp").first()

            if not latest_indicator:
                print(f"❌ Impossible de récupérer l'indicateur '{indicator_name}' sur {interval_check} pour {symbole}.")
                return False  # On arrête si on ne trouve pas les données sur l'autre intervalle

        # Récupérer la valeur de l'indicateur
        indicator_value = getattr(latest_indicator, indicator_name, None)

        if indicator_value is None:
            print(f"❌ L'indicateur '{indicator_name}' n'est pas encore calculé sur {interval_check} pour {symbole}.")
            return False  # L'indicateur n'existe pas encore

        # Vérifier la condition
        op_func, threshold = parse_condition(condition)
        if not op_func or not op_func(indicator_value, threshold):
            print(f"❌ Condition échouée pour {indicator_name} sur {interval_check} ({indicator_value} {condition}) pour {symbole}.")
            return False  # Une condition n'est pas remplie

    return True  # ✅ Toutes les conditions sont remplies

def execute_strategies(symbole):
    """
    Vérifie toutes les stratégies actives et exécute les achats ou ventes si les conditions sont remplies.
    """
    try:
        symbol_strategy = SymbolStrategy.objects.get(symbole=symbole, active=True)
    except SymbolStrategy.DoesNotExist:
        return  # Aucune stratégie active pour cette monnaie
    
    strategy = symbol_strategy.strategy
    last_price = symbol_strategy.close_price

    if last_price is None:
        print(f"❌ Aucun prix connu pour {symbole}, achat/vente impossible.")
        return

    # ✅ Vérifier les conditions d'achat
    if not symbol_strategy.entry_price:
        if check_strategy_conditions(symbole, "1m", strategy.buy_conditions):
            entry_price = last_price
            investment_amount = symbol_strategy.investment_amount
            quantity = investment_amount / entry_price  # Quantité achetée

            # ✅ Enregistrer l'achat
            symbol_strategy.entry_price = entry_price
            symbol_strategy.max_price = entry_price
            symbol_strategy.save()

            # ✅ Ajouter l'achat dans le journal des trades
            TradeLog.objects.create(
                symbole=symbole,
                strategy=strategy,
                entry_price=entry_price,
                investment_amount=investment_amount,
                quantity=quantity
            )

            print(f"✅ Achat simulé de {quantity:.4f} {symbole} à {entry_price} USDT (Investissement: {investment_amount} USDT)")
            return  # On ne vérifie pas la vente immédiatement après un achat

    # ✅ Vérifier les conditions de vente
    max_price = max(symbol_strategy.max_price, last_price)
    symbol_strategy.max_price = max_price
    symbol_strategy.save()

    sell_conditions = {
        "sell_1": last_price <= symbol_strategy.entry_price * 0.999,
        "sell_2": last_price >= symbol_strategy.entry_price * 1.01 and (max_price / symbol_strategy.entry_price) * 0.9 >= last_price / symbol_strategy.entry_price
    }

    if any(sell_conditions.values()):
        print(f"🚀 Vente déclenchée pour {symbole} à {last_price}")

        # ✅ Fermer le trade et enregistrer la vente
        trade = TradeLog.objects.filter(symbole=symbole, status="open").first()
        if trade:
            trade.close_trade(last_price)

        symbol_strategy.active = False  # Désactiver la stratégie après la vente
        symbol_strategy.save()

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