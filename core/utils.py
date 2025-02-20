import requests
import time
from core.models import Kline, Indicator, TradeLog, APIKey, Strategy, Monnaie
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
INTERVALS = ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]
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

def set_loaded_symbol(symbole, status):
    global loaded_symbols
    loaded_symbols[symbole] = status


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
        print(f"🔄 Chargement des Klines pour {symbol}...")
        for interval in intervals:
            klines = get_historical_klines(symbol, interval)
            if klines:
                save_klines_to_db(symbol, interval, klines)
                for interval in INTERVALS:
                    calculate_indicators(symbol, interval)
        Monnaie.objects.filter(symbole=symbol).update(init=True)
        set_loaded_symbol(symbol, True)
        print(f"✅ Initialisation terminée pour {symbol}")

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

def calculate_indicators_with_live(symbol, interval, live_close_price):
    """
    Calculer les indicateurs en ajoutant le prix en temps réel à la fin des Klines cloturées.
    """
    from .models import Kline, Monnaie

    monnaie = Monnaie.objects.get(symbole=symbol)

    # Récupère les 13 dernières Klines clôturées
    klines = Kline.objects.filter(symbole=symbol, intervalle=interval).order_by('-timestamp')[:13]

    if len(klines) < 13:
        return  # Pas assez de Klines pour calculer

    closes = [float(k.close_price) for k in klines][::-1]

    # Ajoute la valeur de la Kline non clôturée en cours
    closes.append(live_close_price)

    rsi_value = calculate_rsi(closes)
    stoch_rsi_value = calculate_stoch_rsi(closes)

    # Mise à jour en temps réel dans Monnaie
    setattr(monnaie, f'rsi_{interval}', round(rsi_value, 2))
    setattr(monnaie, f'stoch_rsi_{interval}', round(stoch_rsi_value, 2))

    monnaie.save()


def calculate_stoch_rsi_with_current(symbol, interval, current_price=None, rsi_length=14, stoch_length=14, smooth_k=3):
    klines = list(Kline.objects.filter(symbole=symbol, intervalle=interval).order_by("-timestamp")[:rsi_length + stoch_length + smooth_k])

    if len(klines) < (rsi_length + stoch_length + smooth_k):
        return None

    closes = [float(k.close_price) for k in reversed(klines)]

    # Remplacement de la dernière valeur si current_price est fourni
    if current_price is not None:
        closes[-1] = current_price

    closes = np.array(closes)
    deltas = np.diff(closes)

    gain = np.where(deltas > 0, deltas, 0)
    loss = np.where(deltas < 0, -deltas, 0)

    avg_gain = pd.Series(gain).rolling(window=rsi_length, min_periods=rsi_length).mean()
    avg_loss = pd.Series(loss).rolling(window=rsi_length, min_periods=rsi_length).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.dropna().values

    if len(rsi) < stoch_length:
        return None

    min_rsi = pd.Series(rsi).rolling(window=stoch_length, min_periods=stoch_length).min()
    max_rsi = pd.Series(rsi).rolling(window=stoch_length, min_periods=stoch_length).max()

    stoch_rsi = (rsi - min_rsi) / (max_rsi - min_rsi)
    stoch_rsi_k = stoch_rsi.rolling(window=smooth_k, min_periods=smooth_k).mean() * 100

    if len(stoch_rsi_k.dropna()) == 0:
        return None

    return round(stoch_rsi_k.dropna().iloc[-1], 2)

from django.db.models import Max

def calculate_indicators(symbole, interval, kline=None, is_closed=False):
    """
    Calcule les indicateurs techniques pour une monnaie sur un intervalle donné,
    en temps réel si la Kline n'est pas clôturée.
    """
    monnaie = get_loaded_symbols().get(symbole)
    if not monnaie:
        return

    # Récupération des 14 dernières Klines (ou plus selon tes besoins pour MACD et Bollinger)
    klines_qs = Kline.objects.filter(symbole=symbole, intervalle=interval).order_by('-timestamp')[:100]
    klines = list(klines_qs)

    # Ajout de la Kline en cours si fournie (pour le calcul temps réel)
    if kline:
        klines.append(kline)
    
    
    
    
    
    
    

    # Inversion dans le bon sens chronologique
    klines.reverse()

    # Vérification pour éviter les calculs inutiles
    if len(klines) < 14:
        return

    closes = [k.close_price for k in klines]

    # Calcul des indicateurs
    rsi_value = calculate_rsi(closes)
    stoch_rsi_value = calculate_stoch_rsi(closes)
    macd_value, macd_signal = calculate_macd(closes)
    bollinger_upper, bollinger_middle, bollinger_lower = calculate_bollinger_bands(closes)

    indicateurs = {
        'rsi': rsi_value,
        'stoch_rsi': stoch_rsi_value,
        'macd': macd_value,
        'macd_signal': macd_signal,
        'bollinger_upper': bollinger_upper,
        'bollinger_middle': bollinger_middle,
        'bollinger_lower': bollinger_lower
    }
    
    # Mise à jour des indicateurs en mémoire sur l'objet Monnaie
    monnaie = Monnaie.objects.get(symbole=symbole)
    setattr(monnaie, f"rsi_{interval}", rsi_value)
    setattr(monnaie, f"stoch_rsi_{interval}", stoch_rsi_value)
    setattr(monnaie, f"macd_{interval}", macd_value)
    setattr(monnaie, f"macd_signal_{interval}", macd_signal)
    setattr(monnaie, f"bollinger_middle_{interval}", bollinger_middle)
    setattr(monnaie, f"bollinger_upper_{interval}", bollinger_upper)
    setattr(monnaie, f"bollinger_lower_{interval}", bollinger_lower)

    monnaie.save()
    
    

    # Si la Kline est clôturée, on sauvegarde les indicateurs en base
    if is_closed:
        # Prendre le timestamp de la dernière Kline (clôturée)
        last_timestamp = klines[-1].timestamp

        # Met à jour ou crée une nouvelle entrée en base pour les indicateurs clôturés
        Indicator.objects.update_or_create(
            symbole=symbole,
            intervalle=interval,
            timestamp=last_timestamp,
            defaults=indicateurs
        )
import pandas as pd
import numpy as np

def calculate_stoch_rsi(closes, rsi_length=14, stoch_length=14, smooth_k=3):
    

    if len(closes) < (rsi_length + stoch_length + smooth_k):
        return None

    # Préparation des données
    deltas = np.diff(closes)

    gain = np.where(deltas > 0, deltas, 0)
    loss = np.where(deltas < 0, -deltas, 0)

    avg_gain = pd.Series(gain).rolling(window=rsi_length, min_periods=rsi_length).mean()
    avg_loss = pd.Series(loss).rolling(window=rsi_length, min_periods=rsi_length).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.dropna().values

    if len(rsi) < stoch_length:
        return None

    min_rsi = pd.Series(rsi).rolling(window=stoch_length, min_periods=stoch_length).min()
    max_rsi = pd.Series(rsi).rolling(window=stoch_length, min_periods=stoch_length).max()

    stoch_rsi = (rsi - min_rsi) / (max_rsi - min_rsi)
    stoch_rsi_k = stoch_rsi.rolling(window=smooth_k, min_periods=smooth_k).mean() * 100

    if len(stoch_rsi_k.dropna()) == 0:
        return None

    return round(stoch_rsi_k.dropna().iloc[-1], 2)

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(closes, short_period=12, long_period=26, signal_period=9):
    if len(closes) < long_period:
        return None, None

    short_ema = pd.Series(closes).ewm(span=short_period, adjust=False).mean()
    long_ema = pd.Series(closes).ewm(span=long_period, adjust=False).mean()
    macd = short_ema - long_ema
    signal = macd.ewm(span=signal_period, adjust=False).mean()

    return macd.iloc[-1], signal.iloc[-1]

def calculate_bollinger_bands(closes, period=20, num_std=2):
    if len(closes) < period:
        return None, None, None

    series = pd.Series(closes)
    rolling_mean = series.rolling(window=period).mean()
    rolling_std = series.rolling(window=period).std()

    upper_band = rolling_mean.iloc[-1] + (rolling_std.iloc[-1] * num_std)
    lower_band = rolling_mean.iloc[-1] - (rolling_std.iloc[-1] * num_std)
    middle_band = rolling_mean.iloc[-1]

    return upper_band, middle_band, lower_band

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
    symbols = TradeLog.objects.values_list("symbole__symbole", flat=True).distinct()
    stats["per_symbol"] = {}

    for symbol in symbols:
        trades = TradeLog.objects.filter(symbole__symbole=symbol, status="closed")
        stats["per_symbol"][symbol] = {
            "total": trades.count(),
            "win": trades.filter(trade_result__gt=0).count(),
            "lose": trades.filter(trade_result__lt=0).count(),
            "avg_gain": trades.aggregate(Avg("trade_result"))["trade_result__avg"],
            "max_gain": trades.aggregate(Max("trade_result"))["trade_result__max"],
            "min_gain": trades.aggregate(Min("trade_result"))["trade_result__min"],
            "cumulative_gain": trades.aggregate(Sum("trade_result"))["trade_result__sum"],
        }
    stats["per_symbol"] = dict(
        sorted(
            stats["per_symbol"].items(),
            key=lambda item: item[1]["cumulative_gain"] or 0,
            reverse=True
        )
    )
    return stats

from core.models import TradeLog

MONTANT_INVESTISSEMENT_FIXE = 100.0  # Ajuste selon ton besoin

def acheter(symbole):
    """
    Exécute un achat seulement si aucune position ouverte n'existe déjà pour cette monnaie.
    """
    existing_trade = TradeLog.objects.filter(symbole__symbole=symbole, status="open").exists()
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
        symbole=monnaie,
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

    
    #else:
    #    print(f"❌ Achat non validé pour {monnaie.symbole}")

def execute_sell_strategy(symbole=None):
    """
    Vérifie les stratégies de vente et clôture les trades si nécessaire.
    Si symbole est fourni, n'évalue que les trades de cette monnaie.
    """
    from core.models import TradeLog, Monnaie
    
    update_trade_prices(symbole)
    
    if symbole:
        open_trades = TradeLog.objects.filter(status="open", symbole__symbole=symbole)
    else:
        open_trades = TradeLog.objects.filter(status="open")

    for trade in open_trades:
        monnaie = Monnaie.objects.get(symbole=trade.symbole)
        if monnaie.strategy:
            result = monnaie.strategy.evaluate_sell(monnaie, trade)
            if result:
                print(f"✅ Vente validée pour {trade.symbole} selon la stratégie {monnaie.strategy.name}")
                trade.close_trade(trade.prix_actuel)
                trade.status = "closed"
                trade.save()
            #else:
            #    print(f"❌ Vente non validée pour {trade.symbole}")
    

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
        
        try:
            monnaie_obj = Monnaie.objects.get(symbole=symbole)
            trades = trades.filter(symbole=monnaie_obj)
            
        except Monnaie.DoesNotExist:
            print(f"⚠️ Monnaie {symbole} non trouvée. Pas de mise à jour des trades.")
            return
    
    for trade in trades:
        
        monnaie = trade.symbole  # Symbole est une FK vers Monnaie
        
        # Utilise le prix_actuel de Monnaie au lieu de la dernière Kline
        prix_actuel = monnaie.prix_actuel

        if prix_actuel is not None:
            
            if prix_actuel != trade.prix_actuel or prix_actuel > (trade.prix_max or 0):
                
                #print(f"🔄 Mise à jour prix pour {trade.symbole.symbole} : Prix actuel {prix_actuel}, Prix max {max(prix_actuel, trade.prix_max or 0)}")
                trade.prix_actuel = prix_actuel
                trade.prix_max = max(prix_actuel, trade.prix_max or 0)
                
                trade.save()
                
        else:
            print(f"⚠️ Prix actuel non défini pour {monnaie.symbole}, prix non mis à jour.")
    


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
    



















