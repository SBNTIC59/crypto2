import requests
import time
from core.models import Kline, Indicator, Indicator, SymbolStrategy, TradeLog
from django.db.models import Min, Max, Sum, Avg, Count
from datetime import datetime, timezone
import pandas as pd
import threading
import numpy as np
import operator
import decimal
from django.utils.timezone import now


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
    Analyse une condition sous forme de chaîne et retourne l'opérateur et la valeur.
    """
    print(f"🔎 Analyse de la condition : {condition}")  # Debugging

    for op in OPERATORS.keys():
        if condition.startswith(op):
            try:
                valeur_numerique = float(condition[len(op):])  # Convertir en float après l'opérateur
                print(f"✅ Opérateur détecté : {op}, Valeur : {valeur_numerique}")  # Debugging
                return OPERATORS[op], valeur_numerique
            except ValueError:
                print(f"⚠️ Erreur de conversion dans parse_condition() : {condition}")
                return None, None

    print(f"❌ Aucune correspondance trouvée pour : {condition}")
    return None, None

def check_strategy_conditions(symbole, interval, conditions):
    """
    Vérifie si une liste de conditions est remplie pour une monnaie donnée.
    """
    from core.models import Indicator  

    latest_indicator = Indicator.objects.filter(symbole=symbole, intervalle=interval).order_by("-timestamp").first()

    if not latest_indicator:
        print(f"⚠️ Aucune donnée d'indicateur pour {symbole} {interval}, impossible de tester la stratégie.")
        return False

    print(f"🔍 Test de la stratégie pour {symbole} sur {interval}...")

    # Vérifier si `conditions` est un bloc `AND` ou `OR`
    if isinstance(conditions, dict) and "type" in conditions and "rules" in conditions:
        condition_type = conditions["type"]
        rules = conditions["rules"]

        if not isinstance(rules, list):
            print(f"⚠️ Erreur : `rules` doit être une liste mais a reçu {type(rules)} -> {rules}")
            return False  

        print(f"🔗 Bloc {condition_type} détecté...")

        if condition_type == "AND":
            if not all(check_strategy_conditions(symbole, interval, rule) for rule in rules):
                print(f"❌ Échec d'un test AND, stratégie non validée.")
                return False

        elif condition_type == "OR":
            if any(check_strategy_conditions(symbole, interval, rule) for rule in rules):
                print(f"✅ Succès d'un test OR, stratégie validée.")
                return True

        return False  # Si aucune condition valide n'est trouvée

    # Vérifier si `conditions` est une liste de conditions individuelles
    if isinstance(conditions, dict) and "conditions" in conditions:
        conditions = conditions["conditions"]

    if not isinstance(conditions, list):
        print(f"⚠️ `conditions` doit être une liste, reçu : {conditions}")
        return False  

    # 🔥 Correction : Vérifier que nous traitons bien des conditions individuelles
    for condition in conditions:
        if not isinstance(condition, dict):
            print(f"⚠️ Condition ignorée (pas un dictionnaire) : {condition}")
            continue  

        # **🔥 Vérification supplémentaire : éviter de traiter des blocs `AND` et `OR` comme des conditions**
        if "type" in condition and "rules" in condition:
            print(f"⚠️ Ignoré : bloc {condition['type']} trouvé dans une boucle de conditions simples")
            continue  

        required_keys = ["metric", "operator", "value"]
        missing_keys = [key for key in required_keys if key not in condition]

        if missing_keys:
            print(f"⚠️ Condition incomplète, clés manquantes : {missing_keys} dans {condition}")
            continue  

        metric = condition["metric"]
        interval_check = condition.get("interval", interval)  
        operator_str = condition["operator"]
        value = condition["value"]

        if interval_check != interval:
            print(f"❌ Condition ignorée ({metric} {interval_check}), attendu {interval}")
            continue

        # Récupérer la valeur de l'indicateur
        indicator_value = getattr(latest_indicator, metric, None)

        if indicator_value is None:
            print(f"⚠️ L'indicateur {metric} n'existe pas encore pour {symbole}")
            return False

        # Vérifier la condition
        op_func, threshold = parse_condition(f"{operator_str}{value}")

        if not op_func:
            print(f"⚠️ Condition mal formée lors de l'analyse de l'opérateur : {condition}")
            return False

        print(f"🔹 Test {metric} = {indicator_value} {operator_str} {value} ?")
        if not op_func(indicator_value, threshold):
            print(f"❌ Condition non remplie : {metric} = {indicator_value}, attendu {operator_str} {value}")
            return False  

    print(f"✅ Toutes les conditions sont remplies pour {symbole} sur {interval} !")
    return True  


def execute_strategies(symbole):
    """
    Vérifie les stratégies d'achat pour un symbole donné.
    """
    from core.models import SymbolStrategy

    strategy_obj = SymbolStrategy.objects.filter(symbole=symbole).first()

    if not strategy_obj:
        print(f"⚠️ Aucune stratégie trouvée pour {symbole}")
        return

    strategy = strategy_obj.strategy
    if not strategy:
        print(f"⚠️ Pas de stratégie définie pour {symbole}")
        return
    
    conditions_achat = strategy.buy_conditions  

    if not conditions_achat:
        print(f"⚠️ Aucune condition d'achat définie pour {symbole}")
        return

    print(f"🔎 Test d'achat pour {symbole}")

    if check_strategy_conditions(symbole, "1m", conditions_achat):
        print(f"✅ Achat validé pour {symbole} !")
        acheter(symbole)  
    else:
        print(f"❌ Achat non validé pour {symbole}.")

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

def acheter(symbole):
    """
    Simule l'achat d'une monnaie en enregistrant un trade dans la base de données.
    """
    # 🔍 Récupérer le dernier prix connu de la monnaie
    prix_achat = get_latest_price(symbole)
    
    if prix_achat is None:
        print(f"❌ Impossible d'acheter {symbole} : prix non disponible !")
        return
    
    # 🏦 Calculer la quantité achetée
    quantite = INVESTMENT_AMOUNT / prix_achat

    # 📌 Enregistrer le trade dans la base
    trade = TradeLog.objects.create(
        symbole=symbole,
        prix_achat=prix_achat,
        prix_max=prix_achat,  # Initialisation du prix max
        status="open",
        entry_time=now(),  # Date d'achat
        investment_amount=INVESTMENT_AMOUNT,
        quantity=quantite,
        strategy_json={"buy_conditions": "Exemple"}  # Tu peux mettre ici la vraie stratégie
    )

    print(f"🚀 Achat exécuté : {trade.symbole} | Prix: {trade.prix_achat} USDT | Quantité: {trade.quantity} | ID: {trade.id}")

def get_latest_price(symbole):
    """
    Récupère le dernier prix connu de la monnaie à partir des Klines en base.
    """
    from core.models import Kline

    dernier_kline = Kline.objects.filter(symbole=symbole, intervalle="1m").order_by("-timestamp").first()
    
    if dernier_kline:
        return decimal.Decimal(dernier_kline.close_price)
    
    return None  # Aucun prix trouvé

def evaluate_expression(value, trade):
    """
    Évalue une expression en remplaçant les variables par les valeurs du trade.
    Ex: "prix_achat * 0.999" devient "100 * 0.999"
    """
    variables = {
        "prix_achat": trade.prix_achat,
        "prix_actuel": trade.prix_actuel or trade.prix_achat,  # Valeur actuelle ou prix d'achat
        "prix_max": trade.prix_max or trade.prix_achat  # Valeur max atteinte
    }
    
    try:
        return eval(value, {}, variables)  # Sécurité : on n'expose que les variables permises
    except Exception as e:
        print(f"⚠️ Erreur lors de l'évaluation de l'expression {value}: {e}")
        return None

def check_sell_conditions(trade, conditions):
    """
    Vérifie si les conditions de vente sont remplies en gérant les `ET` et `OU`.
    """
    if not conditions:
        return False  # Pas de condition définie
    
    for condition in conditions.get("conditions", []):
        if "type" in condition and "rules" in condition:
            if condition["type"] == "AND":
                if not all(check_sell_conditions(trade, {"conditions": [rule]}) for rule in condition["rules"]):
                    return False  # Un seul `False` invalide tout le bloc AND
            elif condition["type"] == "OR":
                if any(check_sell_conditions(trade, {"conditions": [rule]}) for rule in condition["rules"]):
                    return True  # Un seul `True` suffit à valider un bloc OR
            continue  # Passer aux autres conditions

        metric = condition["metric"]
        operator_str = condition["operator"]
        value_expr = condition["value"]

        if metric not in ["prix_actuel", "prix_achat", "prix_max"]:
            print(f"⚠️ Métier inconnu : {metric}")
            continue

        # Récupérer les valeurs réelles
        metric_value = evaluate_expression(metric, trade)
        condition_value = evaluate_expression(value_expr, trade)

        if metric_value is None or condition_value is None:
            continue  # Impossible de comparer

        op_func = OPERATORS.get(operator_str)
        if not op_func:
            print(f"⚠️ Opérateur inconnu : {operator_str}")
            continue
        
        # Vérification de la condition
        if op_func(metric_value, condition_value):
            return True
    
    return False

def execute_sell_strategy():
    """
    Vérifie les stratégies de vente et clôture les trades si nécessaire.
    """
    from core.models import TradeLog
    from core.utils import update_trade_prices, check_strategy_conditions

    # 🔄 Mise à jour des prix avant de vendre
    update_trade_prices()

    open_trades = TradeLog.objects.filter(status="open")

    for trade in open_trades:
        strategy = trade.strategy_json  # Récupère la stratégie du trade

        if not strategy or "sell_conditions" not in strategy:
            print(f"⚠️ Aucune condition de vente définie pour {trade.symbole}")
            continue

        conditions_vente = strategy["sell_conditions"]

        print(f"🔎 Test de vente pour {trade.symbole} | Prix actuel: {trade.prix_actuel} | Prix achat: {trade.prix_achat} | Prix max: {trade.prix_max}")
        print(f"🧐 Conditions de vente trouvées : {conditions_vente}")

        if check_strategy_conditions(trade.symbole, "1m", conditions_vente):
            print(f"✅ Vente validée pour {trade.symbole} | Prix actuel: {trade.prix_actuel}")
            trade.close_trade(trade.prix_actuel)  # Ferme le trade immédiatement
            trade.status = "closed"  # 🔥 Empêche la revente du même trade
            trade.save()
        else:
            print(f"❌ Vente non validée pour {trade.symbole} | Prix actuel: {trade.prix_actuel}")


def update_trade_prices():
    """
    Met à jour les prix actuels des trades ouverts en utilisant les Klines les plus récentes.
    """
    open_trades = TradeLog.objects.filter(status="open")

    for trade in open_trades:
        latest_kline = Kline.objects.filter(symbole=trade.symbole, intervalle="1m").order_by("-timestamp").first()

        if latest_kline:
            trade.prix_actuel = latest_kline.close_price
            if trade.prix_max is None or trade.prix_actuel > trade.prix_max:
                trade.prix_max = trade.prix_actuel  # Mise à jour du prix max atteint
            trade.save()
            print(f"🔄 Prix mis à jour : {trade.symbole} | Prix actuel: {trade.prix_actuel} | Prix max: {trade.prix_max}")
        else:
            print(f"⚠️ Aucune Kline récente trouvée pour {trade.symbole}, prix non mis à jour.")