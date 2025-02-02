import websocket
import json

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"

def on_message(ws, message):
    print(f"📩 Message reçu : {message[:200]}...")

def on_open(ws):
    print("✅ WebSocket connecté à Binance !")

def on_close(ws, close_status_code, close_msg):
    print(f"❌ WebSocket fermé ! Code: {close_status_code}, Message: {close_msg}")

ws = websocket.WebSocketApp(BINANCE_WS_URL, on_message=on_message, on_close=on_close)
ws.run_forever()
