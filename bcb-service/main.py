from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import logging
import os
import random
from typing import Any

from fastapi import FastAPI, HTTPException, Query

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bcb-service")

# Constantes del Tipo de Cambio Oficial
BASE_EXCHANGE_RATE = Decimal("6.9600")
VARIATION_LIMIT = Decimal("0.9999")
MIN_EXCHANGE_RATE = Decimal("5.9601")
MAX_EXCHANGE_RATE = Decimal("7.9599")
DECIMAL_PRECISION = Decimal("0.0001")
DEFAULT_UPDATE_INTERVAL = 180  # 3 minutos por defecto en segundos


def get_env_interval() -> int:
    """Obtiene y valida la variable de entorno BCB_UPDATE_INTERVAL."""
    raw_value = os.getenv("BCB_UPDATE_INTERVAL", str(DEFAULT_UPDATE_INTERVAL)).strip()
    try:
        val = int(raw_value)
        if val <= 0:
            logger.warning(
                f"BCB_UPDATE_INTERVAL inválido ({raw_value}): debe ser un entero >= 1. "
                f"Se utilizará el valor por defecto de {DEFAULT_UPDATE_INTERVAL} segundos."
            )
            return DEFAULT_UPDATE_INTERVAL
        return val
    except ValueError:
        logger.warning(
            f"BCB_UPDATE_INTERVAL inválido ('{raw_value}'): debe ser un número entero. "
            f"Se utilizará el valor por defecto de {DEFAULT_UPDATE_INTERVAL} segundos."
        )
        return DEFAULT_UPDATE_INTERVAL


def generate_next_rate() -> tuple[Decimal, Decimal]:
    """
    Genera una nueva cotización aleatoria simulada.
    Oscila como máximo ±0.9999 respecto a la tasa base (6.9600).
    Garantiza que el valor se mantenga estrictamente en [5.9601, 7.9599]
    y con exactamente 4 decimales de precisión.
    Retorna (nueva_cotizacion, variacion_aplicada).
    """
    delta_int = random.randint(-9999, 9999)
    delta = (Decimal(delta_int) / Decimal(10000)).quantize(DECIMAL_PRECISION)
    new_rate = (BASE_EXCHANGE_RATE + delta).quantize(DECIMAL_PRECISION)

    # Clamping de seguridad para garantizar que nunca exceda los límites
    if new_rate < MIN_EXCHANGE_RATE:
        new_rate = MIN_EXCHANGE_RATE
    elif new_rate > MAX_EXCHANGE_RATE:
        new_rate = MAX_EXCHANGE_RATE

    return new_rate, delta


class ExchangeRateState:
    """Contenedor de estado con control de concurrencia para el microservicio BCB."""

    def __init__(self, initial_rate: Decimal, interval_seconds: int):
        self.current_rate: Decimal = initial_rate
        self.base_rate: Decimal = initial_rate
        self.interval_seconds: int = interval_seconds
        self.last_update_time: datetime = datetime.now(timezone.utc)
        self.lock: asyncio.Lock | None = None
        self.interval_changed: asyncio.Event | None = None
        self.worker_task: asyncio.Task | None = None
        self.update_count: int = 0

    @property
    def active_lock(self) -> asyncio.Lock:
        if self.lock is None:
            self.lock = asyncio.Lock()
        return self.lock

    @property
    def active_event(self) -> asyncio.Event:
        if self.interval_changed is None:
            self.interval_changed = asyncio.Event()
        return self.interval_changed


# Inicialización del estado global
state = ExchangeRateState(BASE_EXCHANGE_RATE, get_env_interval())


async def fluctuation_worker(current_state: ExchangeRateState) -> None:
    """
    Tarea en segundo plano que actualiza la cotización periódicamente
    sin bloquear las peticiones HTTP concurrentes.
    """
    logger.info(
        f"Worker de fluctuación automática en segundo plano iniciado. "
        f"Intervalo actual: {current_state.interval_seconds}s."
    )
    while True:
        try:
            # Espera no bloqueante durante el intervalo configurado
            # Si el intervalo es reconfigurado dinámicamente, se despierta de inmediato
            try:
                await asyncio.wait_for(
                    current_state.active_event.wait(),
                    timeout=current_state.interval_seconds,
                )
                current_state.active_event.clear()
                # Intervalo cambiado, reiniciar ciclo con nuevo tiempo
                continue
            except asyncio.TimeoutError:
                # Transcurrió el intervalo programado normalmente
                pass

            new_rate, delta = generate_next_rate()
            async with current_state.active_lock:
                old_rate = current_state.current_rate
                current_state.current_rate = new_rate
                current_state.last_update_time = datetime.now(timezone.utc)
                current_state.update_count += 1
                active_interval = current_state.interval_seconds

            sign = "+" if delta >= 0 else ""
            logger.info(
                f"[BCB] Cotización actualizada #{current_state.update_count}: "
                f"anterior={old_rate:.4f}, variación={sign}{delta:.4f}, "
                f"nueva={new_rate:.4f} BOB/USD (intervalo: {active_interval}s)"
            )
        except asyncio.CancelledError:
            logger.info("Worker de fluctuación en segundo plano detenido por apagado del servicio.")
            break
        except Exception as exc:
            logger.error(f"Error inesperado en ciclo de fluctuación: {exc}", exc_info=True)
            # Breve pausa para evitar ciclos rápidos en caso de excepción imprevista
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestor de ciclo de vida del microservicio BCB."""
    # Configuración al iniciar
    state.interval_seconds = get_env_interval()
    state.current_rate = BASE_EXCHANGE_RATE
    state.last_update_time = datetime.now(timezone.utc)
    state.update_count = 0
    state.lock = asyncio.Lock()
    state.interval_changed = asyncio.Event()

    logger.info("=" * 65)
    logger.info("Iniciando Servicio BCB - Cotización Oficial del Dólar")
    logger.info(f"Cotización base inicial: {BASE_EXCHANGE_RATE:.4f} BOB/USD")
    logger.info(f"Rango de fluctuación permitido: [{MIN_EXCHANGE_RATE:.4f}, {MAX_EXCHANGE_RATE:.4f}]")
    logger.info(f"Variación máxima permitida: ±{VARIATION_LIMIT:.4f}")
    logger.info(f"Intervalo de actualización configurado: {state.interval_seconds} segundos")
    logger.info("=" * 65)

    # Iniciar worker en segundo plano
    state.worker_task = asyncio.create_task(fluctuation_worker(state))

    try:
        yield
    finally:
        # Detener worker al apagar el servicio
        if state.worker_task and not state.worker_task.done():
            state.worker_task.cancel()
            try:
                await state.worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Servicio BCB finalizado limpiamente.")


app = FastAPI(
    title="Servicio BCB - Cotización del Dólar",
    version="1.1.0",
    description="Microservicio de simulación de cotización oficial y referencial del Banco Central de Bolivia (BCB)",
    lifespan=lifespan,
)


@app.get("/api/bcb/tipo-cambio")
async def obtener_tipo_cambio() -> dict[str, Any]:
    """
    Retorna la cotización oficial vigente del dólar estadounidense (USD -> BOB).
    El valor es mantenido y actualizado en segundo plano por el worker de fluctuación.
    """
    async with state.active_lock:
        rate = state.current_rate
        interval = state.interval_seconds
        timestamp = state.last_update_time.isoformat()

    return {
        "tipo_cambio": float(rate),
        "tipo_cambio_formateado": f"{rate:.4f}",
        "moneda": "USD",
        "moneda_origen": "USD",
        "moneda_destino": "BOB",
        "precision_decimales": 4,
        "intervalo_actual_segundos": interval,
        "timestamp": timestamp,
    }


@app.put("/api/bcb/configurar-intervalo")
async def configurar_intervalo(
    segundos: int = Query(
        ...,
        ge=1,
        description="Nuevo intervalo de actualización en segundos (ej. 5 para pruebas, 180 por defecto)",
    )
) -> dict[str, Any]:
    """
    Permite reconfigurar dinámicamente el intervalo de fluctuación durante pruebas y defensas.
    """
    async with state.active_lock:
        state.interval_seconds = segundos
    state.active_event.set()
    logger.info(f"[BCB] Intervalo de fluctuación reconfigurado dinámicamente a {segundos} segundos.")
    return {
        "mensaje": f"Intervalo de fluctuación actualizado a {segundos} segundos.",
        "intervalo_actual_segundos": segundos,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    """Endpoint de comprobación de salud del microservicio."""
    return {
        "status": "ok",
        "service": "bcb-service",
        "cotizacion_actual": f"{state.current_rate:.4f}",
        "intervalo_segundos": state.interval_seconds,
        "actualizaciones_realizadas": state.update_count,
    }


@app.get("/")
def read_root() -> dict[str, Any]:
    """Información general y endpoints disponibles del servicio BCB."""
    return {
        "service": "bcb-service",
        "version": "1.1.0",
        "descripcion": "Microservicio BCB - Cotización Oficial del Dólar",
        "endpoints": {
            "tipo_cambio": "GET /api/bcb/tipo-cambio",
            "configurar_intervalo": "PUT /api/bcb/configurar-intervalo",
            "health": "GET /health",
        },
    }
