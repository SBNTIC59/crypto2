import json
import traceback
import threading
import time
from websocket import WebSocketApp
from django.core.management.base import BaseCommand
from core.models import Kline, Monnaie, RegulatorSettings
from core.utils import init_loaded_symbols, TradingRegulator, track_processing_time, execute_strategies, execute_sell_strategy, aggregate_higher_timeframe_klines, calculate_indicators, load_historical_klines, calculate_indicators_with_live, INTERVALS
import queue
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from django.db import transaction
from django.db.models import Min
from django.conf import settings

regulator = TradingRegulator()

try:
    regulator_settings = RegulatorSettings.objects.first()
    if regulator_settings is None:
        raise ValueError("❌ Aucun paramètre de régulation trouvé en base. Ajoutez-en via Django Admin.")

    MAX_QUEUE = regulator_settings.max_queue
    MAX_STREAM_PER_WS = regulator_settings.max_stream_per_ws
    NB_MESSAGES_FLUSH = regulator_settings.nb_messages_flush
    DUREE_MAX_FLUSH = regulator_settings.duree_max_flush
    

except Exception as e:
    print(f"⚠️ [ERREUR] Impossible de charger les paramètres : {e}")
    MAX_QUEUE = 5  # Valeur par défaut pour éviter un crash
    MAX_STREAM_PER_WS = 5
    NB_MESSAGES_FLUSH = 25
    DUREE_MAX_FLUSH = 5
    


#max_queue = 5
kline_queue = queue.Queue()
executor = ThreadPoolExecutor(max_workers=MAX_QUEUE)
#MAX_STREAMS_PER_WS = 75
active_websockets = []
klines_cloturees = []
monnaies_a_aggreger = set()
lock = threading.Lock()  # 🔒 Protection des accès concurrents
kline_timestamps = {}

def process_kline(item):
    global klines_cloturees, monnaies_a_aggreger
    symbole = item["symbole"]
    kline_data = item["kline"]
    timestamp_reception = item["timestamp_reception"]
    #deb_kline = item["timestamp_production"]
      
    try:
        #print(f"✅ [DEBUG] Process Kline : {symbole} debut de process_kline {kline_data}")

        from core.utils import aggregate_higher_timeframe_klines, calculate_indicators, execute_strategies, execute_sell_strategy, get_loaded_symbols
        from core.models import Kline, Monnaie
        
        if not get_loaded_symbols().get(symbole, False):
            #print(f"✅ [DEBUG] Process Kline : {symbole} | pas initialisé")
            return
        #print(f"✅ [DEBUG] Process Kline : {symbole} | initialisé")

        # Traitement de la Kline
        is_closed = kline_data["x"]
        
        kline = Kline(
            symbole=symbole,
            intervalle="1m",
            timestamp=kline_data["t"],
            open_price=float(kline_data["o"]),
            high_price=float(kline_data["h"]),
            low_price=float(kline_data["l"]),
            close_price=float(kline_data["c"]),
            volume=float(kline_data["v"])
        )
        #print(f"✅ [DEBUG] Process Kline : {symbole} | kline: {kline}")

        # Mise à jour uniquement pour affichage en temps réel
        Monnaie.objects.filter(symbole=symbole).update(
            prix_actuel=float(kline.close_price),
            prix_max=float(kline.high_price),
            prix_min=float(kline.low_price)
        )
        
        if is_closed:
            with lock:  # 🔒 Sécurisation des accès
                klines_cloturees.append(kline)
                monnaies_a_aggreger.add(symbole)
                kline_timestamps[(symbole, kline.intervalle, kline.timestamp)] = timestamp_reception
        else:
            for interval in INTERVALS:
                calculate_indicators(symbole, interval, kline=kline, is_closed=is_closed)
            temps_traitement = time.time() - timestamp_reception
            if temps_traitement >2:
                print(f"🕒 [DEBUG] Traitement {symbole} terminé en {temps_traitement:.3f}s Sans test des strategies")
                min_time, max_time = track_processing_time(temps_traitement)
            else:
                execute_strategies(symbole)
                execute_sell_strategy(symbole)
                temps_traitement = time.time() - timestamp_reception
                min_time, max_time = track_processing_time(temps_traitement)
                #temps_total  = time.time() - (deb_kline / 1000)
                #print(f"🕒 [DEBUG] Traitement {symbole} terminé en {temps_traitement:.3f}s")




        # Si on atteint un certain seuil, on sauvegarde en batch
        if (len(klines_cloturees) >= NB_MESSAGES_FLUSH or (kline_timestamps and time.time() - min(kline_timestamps.values()) > DUREE_MAX_FLUSH)):
            flush_klines()
   
        
        
        
    except Exception as e:
        print(f"❌ [ERROR] Erreur lors du traitement d'une Kline pour {symbole} : {e}")
        print(f"🔍 [DETAILS] Données de la Kline : {kline}")
        print(f"🔍 [TRACEBACK]")
        traceback.print_exc()

def flush_klines():
    """ Enregistre les Klines clôturées et exécute aggregate en batch tout en mesurant le temps de traitement le plus long """
    global klines_cloturees, monnaies_a_aggreger, kline_timestamps

    if not klines_cloturees:
        print("⚠️ [DEBUG] Aucun flush : Aucune Kline à sauvegarder.")
        return

    print(f"📌 [DEBUG] Début du flush de {len(klines_cloturees)} Klines...")
    if not lock.acquire(timeout=2):  # ⏳ Timeout de 2s pour éviter un blocage total
        print("⛔ [DEBUG] Impossible d'acquérir le lock, un autre thread le bloque")
              
        return  # 🔄 On abandonne cette tentative de flush
    
    try:
        #print("tratement dant flush klines ;)")
        klines_a_sauvegarder = klines_cloturees[:]  # Copie sécurisée
        monnaies_a_traiter = monnaies_a_aggreger.copy()
        kline_timestamps_a_traiter  = kline_timestamps.copy()
       # Réinitialisation avant la transaction
        klines_cloturees.clear()
        monnaies_a_aggreger.clear()
        kline_timestamps.clear()

        #print(f"📌 [DEBUG] fin du with lock {len(klines_cloturees)} Klines...")
        max_processing_time = 0  # ⏳ Initialisation du max
        worst_case_kline = None  # 🔍 Stockage de la pire Kline
        min_time= 0

        with transaction.atomic():  # 🔄 Garantit l'intégrité des données
            # Charger les Klines existantes pour éviter le problème de clé primaire manquante
            existing_klines = { (k.symbole, k.intervalle, k.timestamp): k.id 
                for k in Kline.objects.filter(
                    symbole__in=[k.symbole for k in klines_a_sauvegarder],
                    intervalle__in=[k.intervalle for k in klines_a_sauvegarder],
                    timestamp__in=[k.timestamp for k in klines_a_sauvegarder]
                )
            }

            nouvelles_klines = []
            mises_a_jour = []

            for kline in klines_a_sauvegarder:
                key = (kline.symbole, kline.intervalle, kline.timestamp)
                kline_time = kline_timestamps_a_traiter.get(key, time.time())
                min_time = min(kline_time, min_time) if min_time else kline_time

                if key in existing_klines:
                    # 🔥 On récupère l'ID de l'objet existant avant mise à jour
                    kline.id = existing_klines[key]
                    mises_a_jour.append(kline)
                else:
                    nouvelles_klines.append(kline)

            if nouvelles_klines:
                #print("📌 [DEBUG] Sauvegarde des Klines en base (Create)...")

                Kline.objects.bulk_create(nouvelles_klines)

            if mises_a_jour:
                #print("📌 [DEBUG] Sauvegarde des Klines en base (update)...")

                Kline.objects.bulk_update(
                    mises_a_jour, ["close_price", "high_price", "low_price", "volume"]
                )

            for symbole in monnaies_a_traiter:
                last_kline_1m = Kline.objects.filter(symbole=symbole, intervalle="1m").order_by("-timestamp").first()
                if last_kline_1m:
                    #print(f"📌 [DEBUG] Agrégation des Klines pour {symbole}...")
                    aggregate_higher_timeframe_klines(symbole, last_kline_1m)
                    #print(f"✅ [DEBUG] Agrégation terminée pour {symbole}.")
                    if (time.time()-min_time) < 2 :
                        execute_strategies(symbole)
                        execute_sell_strategy(symbole)
                    #else:
                    #    print(f"🕒 [DEBUG] Traitement {symbole} Sans test des strategies dans flush")
                else:
                    print(f"⚠️ [DEBUG] Aucune Kline 1m trouvée pour {symbole}, agrégation annulée.")
        if min_time==0:
            max_processing_time = 0
        else:    
            max_processing_time = time.time()  -  min_time
        print(f"⚠️ [DEBUG] Temps de traitement MAX : {max_processing_time:.3f}s")

        #print(f"✅ [DEBUG] {len(nouvelles_klines)} nouvelles Klines ajoutées, {len(mises_a_jour)} mises à jour.")
    finally:
        if lock.locked():  # ✅ Vérification avant libération du lock
            lock.release()
            print("🔓 [DEBUG] Lock relâché après flush.")

def process_kline_from_queue():
    print("✅ [DEBUG] Démarrage d'un thread de traitement de la queue")
    while True:
        try:
            item = kline_queue.get()
            #print(f"📥 [DEBUG] Traitement de la Kline en queue pour {item['symbole']}")
            if item is None:
                break  # Arrêter proprement si nécessaire
            process_kline(item)
        except Exception as e:
            print(f"❌ [ERROR] Erreur lors du traitement de la Kline depuis la queue : {e}")


def start_single_websocket(symbols, ws_id):
    streams = "/".join([f"{s.lower()}@kline_1m" for s in symbols])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"
    print(f"🌐 [WS {ws_id}] Connexion à {url}")

    from datetime import datetime, timezone
    def on_message(ws, message):
        try:
            data = json.loads(message)
            if "data" in data and "e" in data["data"] and data["data"]["e"] == "kline":
                kline_data = data["data"]["k"]
                #timesstamp_production = data["data"]["E"]
                symbole = kline_data["s"]
                kline = {
                    "symbole": symbole,
                    "kline": kline_data,
                    #"timesstamp_production" : timesstamp_production,
                    "timestamp_reception": time.time()  # Pour les logs de latence
                }
                kline_queue.put(kline)
                #print(f"🕒 [DEBUG] Kline reçue mise en queue pour {symbole}")
        except Exception as e:
            print(f"❌ [ERROR] Erreur lors de la réception d'un message : {e}")
  
    

    #def on_message(ws, message):
    #    try:
    #        # Initialiser message_count et start_count_time sur l'objet ws
    #        if not hasattr(ws, 'message_count'):
    #            ws.message_count = 0
    #            ws.start_count_time = time.time()
#
    #        ws.message_count += 1
#
    #        if time.time() - ws.start_count_time > 60:
    #            print(f"📊 [WebSocket {ws.ws_id}] {ws.message_count} messages reçus en 60s")
    #            ws.message_count = 0
    #            ws.start_count_time = time.time()
#
    #        start_time = datetime.now(timezone.utc)
#
    #        data = json.loads(message)
    #        kline = data['data']['k']
    #        symbole = kline['s']
    #        event_time = data['data']['E'] 
    #        event_time_dt = datetime.fromtimestamp(event_time / 1000, tz=timezone.utc)
    #        delay_from_binance = (start_time - event_time_dt).total_seconds()
    #        monnaie = Monnaie.objects.filter(symbole=symbole, init=True).first()
    #        if monnaie:
    #            timestamp = kline['t']
    #            close_price = float(kline['c'])
    #            kline_obj, created = Kline.objects.update_or_create(
    #                symbole=symbole,
    #                intervalle='1m',
    #                timestamp=timestamp,
    #                defaults={
    #                    'open_price': float(kline['o']),
    #                    'high_price': float(kline['h']),
    #                    'low_price': float(kline['l']),
    #                    'close_price': close_price,
    #                    'volume': float(kline['v']),
    #                }
    #            )
    #            t0 = datetime.now(timezone.utc)
    #            aggregate_higher_timeframe_klines(symbole, kline_obj)
    #            t1 = datetime.now(timezone.utc)
#
    #            calculate_indicators(symbole)
    #            t2 = datetime.now(timezone.utc)
#
    #            execute_strategies(symbole)
    #            t3 = datetime.now(timezone.utc)
#
    #            execute_sell_strategy(symbole)
    #            t4 = datetime.now(timezone.utc)
#
    #            # Mesurer les durées
    #            reception_duration = (t0 - start_time).total_seconds()
    #            aggregation_duration = (t1 - t0).total_seconds()
    #            indicators_duration = (t2 - t1).total_seconds()
    #            buy_strategy_duration = (t3 - t2).total_seconds()
    #            sell_strategy_duration = (t4 - t3).total_seconds()
    #            total_duration = (t4 - start_time).total_seconds()
#
    #            # Retard sur la Kline
    #            kline_delay = (start_time - datetime.fromtimestamp(event_time / 1000, tz=timezone.utc)).total_seconds()
#
    #            print(
    #                f"🕒 [{symbole}] Retard Kline : {kline_delay:.2f}s | "
    #                f"Réception : {reception_duration:.3f}s | "
    #                f"Aggrégation : {aggregation_duration:.3f}s | "
    #                f"Indicateurs : {indicators_duration:.3f}s | "
    #                f"Achat : {buy_strategy_duration:.3f}s | "
    #                f"Vente : {sell_strategy_duration:.3f}s | "
    #                f"TOTAL : {total_duration:.3f}s"
    #            )
#
    #        #    if total_duration > 1.0:
    #        #        print(f"⚠️ [SLOW] Traitement lent pour {symbole} : {total_duration:.3f}s")
    #        #    if kline_delay > 2.0:
    #        #        print(f"⚠️ [DELAY] Retard Kline pour {symbole} : {kline_delay:.2f}s")
    #        #else:
    #        #    print(f"⚠️ kline ignorée pour {symbole}, attendre l'initialisation")
#
    #    except Exception as e:
    #        print(f"❌ [ERROR] WebSocket {ws.ws_id} : {e}")
    #        traceback.print_exc()
#
    def on_error(ws, error):
        print(f"❌ [ERROR] WebSocket {ws.ws_id} : {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"🔴 WebSocket {ws.ws_id} fermé. Reconnexion dans 10 secondes...")
        time.sleep(10)
        start_single_websocket(symbols, ws_id)

    def on_open(ws):
        ws.ws_id = ws_id
        ws.message_count = 0
        ws.start_count_time = time.time()
        print(f"🟢 WebSocket {ws.ws_id} connecté pour {', '.join(symbols)}")

    ws = WebSocketApp(url, on_message=on_message, on_error=on_error, on_close=on_close)
    ws.on_open = on_open
    ws.run_forever()

def start_websockets():
    
    symbols = list(Monnaie.objects.values_list("symbole", flat=True))
    grouped_symbols = [symbols[i:i + MAX_STREAM_PER_WS] for i in range(0, len(symbols), MAX_STREAM_PER_WS)]
    grouped_symbols = grouped_symbols[:5]
    threading.Thread(target=periodic_regulation, daemon=True).start()

    for i, symbol_group in enumerate(grouped_symbols):
        print(f"🟢 Démarrage WebSocket Thread {i + 1} pour {symbol_group}")
        ws_thread = threading.Thread(target=start_single_websocket, args=(symbol_group, i + 1))
        ws_thread.start()
        active_websockets.append(ws_thread)
        time.sleep(2)

def periodic_regulation():
    """ Exécute la régulation toutes les 30 secondes indépendamment du reste. """
    while True:
        time.sleep(5)  # ⏳ Intervalle de régulation
        regulator.verifier_regulation()

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        Monnaie.objects.all().update(init=False)
        init_loaded_symbols() 
        # Lancer le chargement des klines historiques dans un thread séparé
        historical_thread = threading.Thread(target=load_historical_klines)
        historical_thread.start()
        for _ in range(MAX_QUEUE):  # Autant que le max_workers
            executor.submit(process_kline_from_queue)

        start_websockets()
