import requests
import time
from django.db.models import Min, Max, Sum, Avg, Count, Q, F
from datetime import datetime, timezone
import pandas as pd
import threading
import numpy as np
import operator
import decimal
from django.utils.timezone import now
from django.db import transaction
import talib
from django.conf import settings
from collections import deque
import random

regul_max_atteint = False
processing_times = deque(maxlen=100)
is_initializing = True
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

def init_loaded_symbols():
    global loaded_symbols
    loaded_symbols = {symbole: False for symbole in loaded_symbols}



def get_all_usdt_pairs():
    """
    Récupère toutes les paires USDT disponibles sur Binance.
    """
    from .models import Monnaie
    response = requests.get(BINANCE_BASE_URL_liste)
    if response.status_code == 200:
        data = response.json()
        symbols = [s["symbol"] for s in data["symbols"] if s["symbol"].endswith("USDT")]
        print(f"✅ {len(symbols)} paires USDT trouvées.")
        for symbol in symbols:
            monnaie, created = Monnaie.objects.get_or_create(symbole=symbol)
            if created:
                print(f"🆕 [INFO] Monnaie {symbol} ajoutée à la base.")
                
        # Trier les monnaies par performance (gains cumulés et ratio de trades gagnants)
        monnaies_triees = Monnaie.objects.filter(symbole__in=symbols).order_by(
            -F('win_rate'),  # En premier par taux de trades gagnants
            -F('total_profit')  # Ensuite par profit total
            ).values_list('symbole', flat=True)

        return list(monnaies_triees)      
    else:
        print(f"❌ Erreur lors de la récupération des paires Binance: {response.status_code}")
        return []

def get_historical_klines(symbol, interval, limit=None):
    """
    Récupère l'historique des Klines depuis Binance avec gestion des erreurs.
    """
    api_key, secret_key = get_binance_credentials()
    if not api_key or not secret_key:
        print("❌ Impossible de récupérer les Klines : Clés API manquantes.")
        return []

    # Utilise NB_KLINES_HISTORIQUE s'il n'est pas défini en argument
    if limit is None:
        limit = getattr(settings, "NB_KLINES_HISTORIQUE", 100)  # Valeur par défaut si non défini

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

def load_historical_klines(symbols=None):
    """
    Charge l'historique des Klines pour toutes les paires USDT et tous les intervalles nécessaires.
    """
    from core.models import Monnaie
    global is_initializing, regul_max_atteint  # Activation du verrou
    is_initializing = True
    
    if symbols is None:
        symbols = get_all_usdt_pairs()
    else:
        symbols = [symbols]
    
    intervals = ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]

    for symbol in symbols:
        monnaie = Monnaie.objects.filter(symbole=symbol).select_related("strategy").first()
        if not monnaie or not monnaie.strategy:
            print(f"⚠️ [WARNING] {symbol} n'a pas de stratégie assignée, aucun chargement d'historique.")
            continue  # Passe à la monnaie suivante si aucune stratégie n'est définie

        intervals = monnaie.strategy.intervals  # Récupération des intervalles utilisés par la stratégie
        print(f"🔄 Chargement des Klines pour {symbol} (intervalles: {intervals})...")

        if not regul_max_atteint:
            for interval in intervals:
                klines = get_historical_klines(symbol, interval)
                if klines:
                    save_klines_to_db(symbol, interval, klines)
                    #for interval in INTERVALS:
                    #    calculate_indicators(symbol, interval)
            
            set_loaded_symbol(symbol, True)
            Monnaie.objects.filter(symbole=symbol).update(init=True)
        else:
            
            set_loaded_symbol(symbol, False)
            Monnaie.objects.filter(symbole=symbol).update(init=False)
        
        
        print(f"✅ Initialisation terminée pour {symbol}")
    is_initializing = False
    print("🔓 Régulation activée : les nouvelles monnaies peuvent être ajoutées.")    

def save_klines_to_db(symbol, interval, klines):
    """
    Enregistre les Klines récupérées en base de données.
    """
    from core.models import Kline
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
    Agrège les Klines 1m en intervalles supérieurs.
    Utilise des niveaux intermédiaires pour limiter le nombre de calculs directs depuis 1m.
    """
    from core.models import Kline, Monnaie
    import datetime
    monnaie = Monnaie.objects.get(symbole=symbole)

    if not monnaie.strategy:
        print(f"⚠️ [DEBUG] {symbole} ignoré (pas de stratégie définie).")
        return

    required_intervals = set(monnaie.strategy.intervals)

    INTERVAL_MAPPING = {
        "3m": {"base": "1m", "factor": 3},  # 3x 1m
        "5m": {"base": "1m", "factor": 5},  # 5x 1m
        "15m": {"base": "5m", "factor": 3},  # 3x 5m (au lieu de 15x 1m)
        "1h": {"base": "15m", "factor": 4},  # 4x 15m (au lieu de 60x 1m)
    }

    timestamp_1m = kline_1m.timestamp  # Timestamp en ms

    for interval, config in INTERVAL_MAPPING.items():
        if interval in required_intervals:
            base_interval = config["base"]
            factor = config["factor"]

            # Calcul du timestamp aligné pour cet intervalle
            timestamp_group = timestamp_1m - (timestamp_1m % (factor * 60 * 1000))

            # Récupérer les dernières Klines du base_interval pour former cet intervalle
            klines = Kline.objects.filter(
                symbole=symbole, intervalle=base_interval, timestamp__gte=timestamp_group
            ).order_by("timestamp")[:factor]

            if len(klines) == factor:  # Vérifie que toutes les Klines sont disponibles
                open_price = klines[0].open_price
                close_price = list(klines)[-1].close_price if klines.exists() else None
                high_price = max(k.high_price for k in klines)
                low_price = min(k.low_price for k in klines)
                volume = sum(k.volume for k in klines)

                # Vérifier si la Kline existe déjà (évite doublons)
                kline, created = Kline.objects.update_or_create(
                    symbole=symbole,
                    intervalle=interval,
                    timestamp=timestamp_group,
                    defaults={
                        "open_price": open_price,
                        "close_price": close_price,
                        "high_price": high_price,
                        "low_price": low_price,
                        "volume": volume,
                    },
                )

                if created:
                    print(f"✅ [DEBUG] Kline {interval} créée pour {symbole} à {datetime.datetime.fromtimestamp(timestamp_group / 1000)}")
            calculate_indicators(symbole, interval)
        #else:
        #    print(f"⚠️ [DEBUG] Aggrégat de {symbole} ignoré pour l'interval {interval}")



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
    from core.models import Kline
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
    from core.models import Kline, Monnaie
    #monnaie = get_loaded_symbols().get(symbole)
    monnaie = Monnaie.objects.get(symbole=symbole)
    #if not isinstance(monnaie, Monnaie):  # Vérifie que c'est bien un objet Monnaie
    #    print(f"⚠️ [WARNING] {symbole} est invalide ou non chargé correctement.")
    #    return

    if not monnaie:
        print(f"⚠️ [WARNING] {symbole} n'a pas de stratégie assignée, pas de calcul.")
        return
    
    if interval not in monnaie.strategy.intervals:
        #print(f"⚠️ [DEBUG] {symbole} {interval} ignoré (non utilisé par la stratégie).")
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
    if monnaie.strategy.use_rsi:
        rsi_value = calculate_rsi(closes)
    else:
        rsi_value = None
    
    if monnaie.strategy.use_stoch_rsi:
        stoch_rsi_value = calculate_stoch_rsi(closes)
    else:
        stoch_rsi_value = None    
    
    if monnaie.strategy.use_macd:
        macd_value, macd_signal = calculate_macd(closes)
    else:
        macd_value, macd_signal = None, None      
        

    if monnaie.strategy.use_bollinger:
        bollinger_upper, bollinger_middle, bollinger_lower = calculate_bollinger_bands(closes)
    else:
        bollinger_upper, bollinger_middle, bollinger_lower = None, None, None
    
    

    #rsi_value = calculate_rsi(closes)
    #stoch_rsi_value = calculate_stoch_rsi(closes)
    #macd_value, macd_signal = calculate_macd(closes)
    #bollinger_upper, bollinger_middle, bollinger_lower = calculate_bollinger_bands(closes)

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
    
    

    ## Si la Kline est clôturée, on sauvegarde les indicateurs en base
    #if is_closed:
    #    # Prendre le timestamp de la dernière Kline (clôturée)
    #    last_timestamp = klines[-1].timestamp
#
    #    # Met à jour ou crée une nouvelle entrée en base pour les indicateurs clôturés
    #    Indicator.objects.update_or_create(
    #        symbole=symbole,
    #        intervalle=interval,
    #        timestamp=last_timestamp,
    #        defaults=indicateurs
    #    )
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
    from core.models import Kline, Monnaie
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
    print(f"monnaie dans acheter: {monnaie.symbole}")
      
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

    if monnaie.strategy.evaluate_buy(monnaie):
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
    
    if symbole is not None:
        open_trades = TradeLog.objects.filter(status="open", symbole=symbole)
    else:
        open_trades = TradeLog.objects.filter(status="open")

    for trade in open_trades:
        monnaie = trade.symbole
        if monnaie.strategy:
            print(f"indicateur avant evaluation : stoch_rsi_1m :{monnaie.stoch_rsi_1m} | stoch_rsi_3m :{monnaie.stoch_rsi_3m} | stoch_rsi_5m :{monnaie.stoch_rsi_5m}")
            result = monnaie.strategy.evaluate_sell(symbole=monnaie, trade=trade)
            if result:
                print(f"✅ Vente validée pour {trade.symbole} selon la stratégie {monnaie.strategy.name}")
                trade.close_trade(trade.prix_actuel)
                trade.status = "closed"
                trade.save()
                monnaie.update_performance()
                    # 📌 Récupérer les 3 derniers trades de la monnaie
                derniers_trades = TradeLog.objects.filter(
                    symbole=trade.symbole, status="closed"
                    ).order_by("-close_time")[:3]

                # 📌 Vérifier si ce sont **3 trades perdants consécutifs**
                if derniers_trades.count() == 3 and all(t.trade_result < 0 for t in derniers_trades):
                    print(f"❌ [REGULATION] Désactivation de {trade.symbole} (3 pertes d'affilée)")
                    regulator = TradingRegulator.objects.get().first()
                    regulator.desactiver_monnaie(trade.symbole)
                    regulator.ajouter_monnaie()
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
    from core.models import  Monnaie
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
    from core.models import APIKey
    try:
        api_key_obj = APIKey.objects.get(name="Binance")
        return api_key_obj.api_key, api_key_obj.secret_key
    except APIKey.DoesNotExist:
        print("❌ Erreur : Aucune clé API Binance trouvée dans la base !")
        return None, None
    
def update_monnaie_strategy(monnaie, new_strategy):
    """
    Met à jour la stratégie d'une monnaie et ajuste son état en fonction des nouveaux besoins en indicateurs et intervalles.
    """
    old_intervals = set(monnaie.strategy.intervals) if monnaie.strategy else set()
    new_intervals = set(new_strategy.intervals)

    monnaie.strategy = new_strategy

    # Si la nouvelle stratégie demande plus d'intervalles qu'avant, recharger l'historique
    if new_intervals - old_intervals:
        monnaie.init = False  # ⚠️ Nécessite un rechargement de l'historique
        print(f"🔄 [UPDATE] {monnaie.symbole} doit être réinitialisé pour charger les nouveaux intervalles : {new_intervals - old_intervals}")
    
    monnaie.save()

class TradingRegulator:
    
    def __init__(self):
        """Initialisation des seuils et durées de surveillance"""
        from core.models import RegulatorSettings
        self.settings = RegulatorSettings.objects.first()  # Récupération des paramètres stockés
        self.start_time_min = time.time()
        self.start_time_max = time.time()
        self.start_time_critique = time.time()
        self.monnaies_actives = set()

    def verifier_regulation(self):
        """ Vérifie si on doit ajuster le nombre de monnaies actives """
        maintenant = time.time()
    
        # 🔄 Récupération du temps de traitement min et max via `track_processing_time()`
        temps_min, temps_max = track_processing_time()
        nb_monnaies_actives = sum(get_loaded_symbols().values())
        
        print(f"📊 [DEBUG] Vérifier  Régulation : Min: {temps_min:.3f}s | Max: {temps_max:.3f}s | nombre de monnaies actives {nb_monnaies_actives}")
        
        
    
        # 📌 Vérification du SEUIL MIN : Si le temps min reste bas trop longtemps, on ajoute une monnaie
        if (temps_min <= self.settings.seuil_min_traitement) and (temps_max <= self.settings.seuil_max_traitement):
            if maintenant - self.start_time_min >= self.settings.duree_surveillance_min:
                if nb_monnaies_actives < self.settings.nb_monnaies_max:
                    self.ajouter_monnaie()
                    self.start_time_min = maintenant  # 🔄 Reset de la durée de surveillance
    
                  
    
        # 📌 Vérification du SEUIL CRITIQUE : Si le temps max dépasse un seuil critique, on réduit encore plus
        elif temps_max > self.settings.seuil_critique:
            if maintenant - self.start_time_critique >= self.settings.duree_surveillance_critique:
                if nb_monnaies_actives > self.settings.nb_monnaies_min:
                    self.reduire_monnaies(self.settings.reduction_nb_monnaies * 2)
                    self.start_time_critique = maintenant  # 🔄 Reset surveillance
        elif temps_max >= self.settings.seuil_max_traitement:
            if maintenant - self.start_time_max >= self.settings.duree_surveillance_max:
                if nb_monnaies_actives > self.settings.nb_monnaies_min:
                    self.reduire_monnaies(self.settings.reduction_nb_monnaies)
                    self.start_time_max = maintenant  # 🔄 Reset surveillance


    def ajouter_monnaie(self):
        """ Ajoute une nouvelle monnaie à la liste des monnaies actives """
        from core.models import Monnaie
        if is_initializing:
            print("⏳ [DEBUG] Régulation en pause pour l'ajout de monnaie : Initialisation en cours...")
            return  # Bloque l'ajout tant que l'initialisation n'est pas terminée
        
        global regul_max_atteint
        regul_max_atteint= False

        monnaies_disponibles = Monnaie.objects.filter(init=False).exclude(symbole__in=self.monnaies_actives).order_by("-win_rate", "-total_profit").values_list("symbole", flat=True)

        if monnaies_disponibles.exists():
            nouvelle_monnaie = monnaies_disponibles.first()
            load_historical_klines(nouvelle_monnaie)
            nb_monnaies_actives = sum(get_loaded_symbols().values())
            self.monnaies_actives.add(nouvelle_monnaie)
            #print(f"✅ [REGULATION] Nouvelle monnaie activée : {nouvelle_monnaie.symbole} | winrate: {nouvelle_monnaie.win_rate} | totalprofit :  {nouvelle_monnaie.total_profit}")
            temps_min, temps_max = track_processing_time(reinit=True)
            print(f"📊 [DEBUG] Vérifier  création monnaie : Min: {temps_min:.3f}s | Max: {temps_max:.3f}s | nombre de monnaies actives {nb_monnaies_actives}")
            

    def reduire_monnaies(self, nb_a_retirer = None, critique= None,symbole = None):
        """ Réduit le nombre de monnaies actives, en excluant celles ayant des trades en cours. """
        from core.models import Monnaie
        global regul_max_atteint
        regul_max_atteint= True
        # 📌 1. Récupérer les monnaies actives depuis `loaded_symbols`
        
        if critique:
            facteur_critique = 2
        else:
            facteur_critique = 1
        if not nb_a_retirer:
            nb_a_retirer  = self.settings.reduction_nb_monnaies *facteur_critique

        if not symbole:
            monnaies_actives = [symbole for symbole, actif in get_loaded_symbols().items() if actif]
        else:
            monnaies_actives = [symbole]

        if not monnaies_actives:
            print("⚠️ [REGULATION] Aucune monnaie active à désactiver.")
            return

        # 📌 2. Récupérer les monnaies **sans trades en cours**
        monnaies_sans_trades = Monnaie.objects.filter(
                symbole__in=monnaies_actives
            ).exclude(
                trades__status="open"  # ⚠️ Vérifie bien le nom du related_name dans TradeLog
            ).order_by("win_rate", "total_profit").values_list("symbole", flat=True)
          
        
        

        if not monnaies_sans_trades:
            print("⚠️ [REGULATION] Toutes les monnaies actives ont des trades en cours, aucune suppression possible.")
            return

        # 📌 3. Sélection des monnaies à désactiver (max `nb_a_retirer`) par performance
        monnaies_a_retirer = monnaies_sans_trades[:nb_a_retirer]

        print(f"🔍 [DEBUG] Monnaies actives avant réduction: {monnaies_actives}")
        print(f"🔻 [REGULATION] Suppression de {len(monnaies_a_retirer)} monnaies: {monnaies_a_retirer}")

        for symbole in monnaies_a_retirer:
            print(f"chargement liste pour reset: {symbole}")
            monnaie = Monnaie.objects.filter(symbole=symbole).first()
            if monnaie:
                print(f"reset: {symbole}")
                set_loaded_symbol(symbole, False)
                monnaie.init = False
                monnaie.save()
        track_processing_time(reinit=True)
        nb_monnaies_actives = sum(get_loaded_symbols().values())
        print(f"✅ [REGULATION] Nombre de monnaies restantes actives : {nb_monnaies_actives}")
    
processing_times = []

def track_processing_time(temps_traitement  = None, reinit=False):
    """ Stocke et suit le temps de traitement des Klines """
    global processing_times

    if temps_traitement is not None:
        processing_times.append(temps_traitement)
    
    if reinit:
        processing_times.clear()
        return 0,0    
    
    # 🔄 On conserve uniquement les 100 dernières valeurs pour éviter un stockage inutile
    if len(processing_times) > 1000:
        processing_times.pop(0)
    
    if len(processing_times) ==  0:
        return 0,0
    #print(f"📊 [DEBUG] Min: {min(processing_times):.3f}s | Max: {max(processing_times):.3f}s")
    # 📊 Retourne les valeurs min et max actuelles
    return min(processing_times), max(processing_times)
