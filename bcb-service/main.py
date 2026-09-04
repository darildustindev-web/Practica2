from fastapi import FastAPI
import random
import time

app = FastAPI(title="Servicio BCB - Cotización del Dólar", version="1.0.0")

# Cotización Base Oficial
BASE_EXCHANGE_RATE = 6.9600
VARIATION_LIMIT = 0.9999
UPDATE_INTERVAL_SECONDS = 180  # 3 minutos (configurable)

# Estado global simple para prueba
last_update_time = time.time()
current_rate = BASE_EXCHANGE_RATE

def get_updated_rate():
    global last_update_time, current_rate
    now = time.time()
    if now - last_update_time >= UPDATE_INTERVAL_SECONDS:
        variation = round(random.uniform(-VARIATION_LIMIT, VARIATION_LIMIT), 4)
        current_rate = round(BASE_EXCHANGE_RATE + variation, 4)
        last_update_time = now
    return current_rate

@app.get("/api/bcb/tipo-cambio")
def obtener_tipo_cambio():
    rate = get_updated_rate()
    return {
        "moneda_origen": "USD",
        "moneda_destino": "BOB",
        "tipo_cambio": rate,
        "precision_decimales": 4,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
