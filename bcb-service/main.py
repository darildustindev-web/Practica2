from fastapi import FastAPI, Query
import random
import time

app = FastAPI(title="Servicio BCB - Cotización del Dólar", version="1.0.0")

# Cotización Base Oficial
BASE_EXCHANGE_RATE = 6.9600
VARIATION_LIMIT = 0.9999
DEFAULT_UPDATE_INTERVAL = 180  # 3 minutos por defecto

# Estado global
last_update_time = time.time()
current_rate = BASE_EXCHANGE_RATE
update_interval_seconds = DEFAULT_UPDATE_INTERVAL

@app.put("/api/bcb/configurar-intervalo")
def configurar_intervalo(segundos: int = Query(..., description="Nuevo intervalo de actualización en segundos (ej. 1 para pruebas extremas)")):
    global update_interval_seconds
    update_interval_seconds = segundos
    return {"mensaje": f"Intervalo de fluctuación actualizado a {segundos} segundos."}

def get_updated_rate():
    global last_update_time, current_rate, update_interval_seconds
    now = time.time()
    if now - last_update_time >= update_interval_seconds:
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
        "intervalo_actual_segundos": update_interval_seconds,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
