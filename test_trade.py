import requests
import datetime

url = "http://127.0.0.1:8000/api/entrada"
payload = {
    "bot_id": "Bot_TEST",
    "action": "LONG",
    "symbol": "BTCUSDT",
    "price": 68000.0,
    "tp_price": 70000.0,
    "sl_price": 66000.0,
    "timeframe": "1h",
    "bar_close_time": datetime.datetime.now().isoformat()
}

print("Enviando trade de prueba...")
response = requests.post(url, json=payload)
print("Respuesta:", response.json())