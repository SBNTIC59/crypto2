import json
import traceback
import threading
import time
from websocket import WebSocketApp
from django.core.management.base import BaseCommand
from core.models import Kline, Monnaie
from core.utils import execute_strategies, execute_sell_strategy, aggregate_higher_timeframe_klines, calculate_indicators, load_historical_klines

MAX_STREAMS_PER_WS = 100
active_websockets = []

def start_single_websocket(symbols, ws_id):
    streams = "/".join([f"{s.lower()}@kline_1m" for s in symbols])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    from datetime import datetime, timezone

    def on_message(ws, message):
        try:
            # Initialiser message_count et start_count_time sur l'objet ws
            if not hasattr(ws, 'message_count'):
                ws.message_count = 0
                ws.start_count_time = time.time()

            ws.message_count += 1

            if time.time() - ws.start_count_time > 60:
                print(f"📊 [WebSocket {ws.ws_id}] {ws.message_count} messages reçus en 60s")
                ws.message_count = 0
                ws.start_count_time = time.time()

            start_time = datetime.now(timezone.utc)

            data = json.loads(message)
            kline = data['data']['k']
            symbole = kline['s']
            event_time = data['data']['E'] 
            event_time_dt = datetime.fromtimestamp(event_time / 1000, tz=timezone.utc)
            delay_from_binance = (start_time - event_time_dt).total_seconds()
            monnaie = Monnaie.objects.filter(symbole=symbole, init=True).first()
            if monnaie:
                timestamp = kline['t']
                close_price = float(kline['c'])
                kline_obj, created = Kline.objects.update_or_create(
                    symbole=symbole,
                    intervalle='1m',
                    timestamp=timestamp,
                    defaults={
                        'open_price': float(kline['o']),
                        'high_price': float(kline['h']),
                        'low_price': float(kline['l']),
                        'close_price': close_price,
                        'volume': float(kline['v']),
                    }
                )
                t0 = datetime.now(timezone.utc)
                aggregate_higher_timeframe_klines(symbole, kline_obj)
                t1 = datetime.now(timezone.utc)

                calculate_indicators(symbole)
                t2 = datetime.now(timezone.utc)

                execute_strategies(symbole)
                t3 = datetime.now(timezone.utc)

                execute_sell_strategy(symbole)
                t4 = datetime.now(timezone.utc)

                # Mesurer les durées
                reception_duration = (t0 - start_time).total_seconds()
                aggregation_duration = (t1 - t0).total_seconds()
                indicators_duration = (t2 - t1).total_seconds()
                buy_strategy_duration = (t3 - t2).total_seconds()
                sell_strategy_duration = (t4 - t3).total_seconds()
                total_duration = (t4 - start_time).total_seconds()

                # Retard sur la Kline
                kline_delay = (start_time - datetime.fromtimestamp(event_time / 1000, tz=timezone.utc)).total_seconds()

                print(
                    f"🕒 [{symbole}] Retard Kline : {kline_delay:.2f}s | "
                    f"Réception : {reception_duration:.3f}s | "
                    f"Aggrégation : {aggregation_duration:.3f}s | "
                    f"Indicateurs : {indicators_duration:.3f}s | "
                    f"Achat : {buy_strategy_duration:.3f}s | "
                    f"Vente : {sell_strategy_duration:.3f}s | "
                    f"TOTAL : {total_duration:.3f}s"
                )

                if total_duration > 1.0:
                    print(f"⚠️ [SLOW] Traitement lent pour {symbole} : {total_duration:.3f}s")
                if kline_delay > 2.0:
                    print(f"⚠️ [DELAY] Retard Kline pour {symbole} : {kline_delay:.2f}s")
            else:
                print(f"⚠️ kline ignorée pour {symbole}, attendre l'initialisation")

        except Exception as e:
            print(f"❌ [ERROR] WebSocket {ws.ws_id} : {e}")
            traceback.print_exc()

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
    symbols = list(Kline.objects.values_list("symbole", flat=True).distinct())
    grouped_symbols = [symbols[i:i + MAX_STREAMS_PER_WS] for i in range(0, len(symbols), MAX_STREAMS_PER_WS)]

    for i, symbol_group in enumerate(grouped_symbols):
        ws_thread = threading.Thread(target=start_single_websocket, args=(symbol_group, i + 1))
        ws_thread.start()
        active_websockets.append(ws_thread)
        time.sleep(2)

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        Monnaie.objects.all().update(init=False)
        # Lancer le chargement des klines historiques dans un thread séparé
        historical_thread = threading.Thread(target=load_historical_klines)
        historical_thread.start()
        start_websockets()
