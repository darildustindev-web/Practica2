from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
import os
import sys
from pathlib import Path
import unittest

# Agregar la raíz del proyecto y bcb-service al sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "bcb-service"))

from fastapi.testclient import TestClient

import main as bcb_module
from main import (
    BASE_EXCHANGE_RATE,
    DECIMAL_PRECISION,
    DEFAULT_UPDATE_INTERVAL,
    MAX_EXCHANGE_RATE,
    MIN_EXCHANGE_RATE,
    VARIATION_LIMIT,
    app,
    generate_next_rate,
    get_env_interval,
    state,
)


class TestBCBService(unittest.TestCase):
    """Suite de pruebas exhaustivas para el microservicio BCB (Fluctuación del Dólar)."""

    def setUp(self):
        # Resetear estado base para cada prueba
        state.current_rate = BASE_EXCHANGE_RATE
        state.interval_seconds = DEFAULT_UPDATE_INTERVAL
        state.update_count = 0

    def test_initial_base_rate(self):
        """Verifica que el tipo de cambio base sea exactamente 6.9600."""
        self.assertEqual(BASE_EXCHANGE_RATE, Decimal("6.9600"))
        self.assertEqual(state.current_rate, Decimal("6.9600"))
        self.assertEqual(f"{state.current_rate:.4f}", "6.9600")

    def test_precision_exactly_4_decimals(self):
        """Comprueba que la cotización maneje exactamente 4 decimales sin residuos flotantes."""
        for _ in range(50):
            rate, delta = generate_next_rate()
            # Convertir a cadena y verificar longitud de parte decimal
            rate_str = f"{rate:.4f}"
            parts = rate_str.split(".")
            self.assertEqual(len(parts), 2)
            self.assertEqual(len(parts[1]), 4)
            # Asegurar que el Decimal coincide con quantize(0.0001)
            self.assertEqual(rate, rate.quantize(DECIMAL_PRECISION))

    def test_fluctuation_bounds_and_limits(self):
        """
        Ejecuta 2,000 simulaciones aleatorias para verificar:
        - Nunca supera los límites: 5.9601 <= cotización <= 7.9599.
        - La variación máxima nunca excede ±0.9999 respecto a 6.9600.
        """
        min_seen = Decimal("999.0")
        max_seen = Decimal("-999.0")

        for _ in range(2000):
            rate, delta = generate_next_rate()
            self.assertGreaterEqual(
                rate,
                MIN_EXCHANGE_RATE,
                f"El tipo de cambio {rate} es menor al límite inferior permitido {MIN_EXCHANGE_RATE}",
            )
            self.assertLessEqual(
                rate,
                MAX_EXCHANGE_RATE,
                f"El tipo de cambio {rate} es mayor al límite superior permitido {MAX_EXCHANGE_RATE}",
            )
            self.assertLessEqual(abs(delta), VARIATION_LIMIT)
            self.assertEqual(rate, (BASE_EXCHANGE_RATE + delta).quantize(DECIMAL_PRECISION))

            if rate < min_seen:
                min_seen = rate
            if rate > max_seen:
                max_seen = rate

        # Verificar que la simulación realmente fluctúa a ambos lados
        self.assertLess(min_seen, BASE_EXCHANGE_RATE)
        self.assertGreater(max_seen, BASE_EXCHANGE_RATE)

    def test_env_interval_parsing_and_fallback(self):
        """Verifica lectura de BCB_UPDATE_INTERVAL y robustez ante valores inválidos."""
        # 1. Caso valor normal válido
        os.environ["BCB_UPDATE_INTERVAL"] = "60"
        self.assertEqual(get_env_interval(), 60)

        # 2. Caso valor ausente (debe devolver default 180s)
        del os.environ["BCB_UPDATE_INTERVAL"]
        self.assertEqual(get_env_interval(), 180)

        # 3. Caso valor inválido no numérico (fallback 180s)
        os.environ["BCB_UPDATE_INTERVAL"] = "invalido"
        self.assertEqual(get_env_interval(), 180)

        # 4. Caso valor menor o igual a cero (fallback 180s)
        os.environ["BCB_UPDATE_INTERVAL"] = "-10"
        self.assertEqual(get_env_interval(), 180)
        os.environ["BCB_UPDATE_INTERVAL"] = "0"
        self.assertEqual(get_env_interval(), 180)

        # Limpiar
        if "BCB_UPDATE_INTERVAL" in os.environ:
            del os.environ["BCB_UPDATE_INTERVAL"]

    def test_endpoint_get_tipo_cambio_structure(self):
        """Verifica la respuesta HTTP del endpoint GET /api/bcb/tipo-cambio."""
        with TestClient(app) as client:
            response = client.get("/api/bcb/tipo-cambio")
            self.assertEqual(response.status_code, 200)
            data = response.json()

            # Campos obligatorios requeridos y compatibles
            self.assertIn("tipo_cambio", data)
            self.assertIn("tipo_cambio_formateado", data)
            self.assertIn("moneda", data)
            self.assertIn("moneda_origen", data)
            self.assertIn("moneda_destino", data)
            self.assertIn("precision_decimales", data)
            self.assertIn("intervalo_actual_segundos", data)
            self.assertIn("timestamp", data)

            self.assertEqual(data["moneda"], "USD")
            self.assertEqual(data["moneda_origen"], "USD")
            self.assertEqual(data["moneda_destino"], "BOB")
            self.assertEqual(data["precision_decimales"], 4)
            self.assertEqual(data["tipo_cambio"], 6.96)
            self.assertEqual(data["tipo_cambio_formateado"], "6.9600")

    def test_endpoint_health(self):
        """Verifica el endpoint GET /health."""
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["service"], "bcb-service")
            self.assertEqual(data["cotizacion_actual"], "6.9600")

    def test_reconfigure_interval_endpoint(self):
        """Verifica el endpoint PUT /api/bcb/configurar-intervalo."""
        with TestClient(app) as client:
            response = client.put("/api/bcb/configurar-intervalo", params={"segundos": 5})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["intervalo_actual_segundos"], 5)
            self.assertEqual(state.interval_seconds, 5)

            # Validar rechazo de valores <= 0
            response_invalid = client.put("/api/bcb/configurar-intervalo", params={"segundos": 0})
            self.assertEqual(response_invalid.status_code, 422)

    def test_automatic_background_update_execution(self):
        """
        Verifica que el proceso en segundo plano actualice automáticamente
        la cotización transcurrido el intervalo, sin requerir llamada forzada.
        """
        os.environ["BCB_UPDATE_INTERVAL"] = "1"  # 1 segundo para prueba rápida
        try:
            with TestClient(app) as client:
                # Al inicio debe ser 6.9600
                res_init = client.get("/api/bcb/tipo-cambio")
                self.assertEqual(res_init.json()["tipo_cambio_formateado"], "6.9600")

                # Esperar 1.3 segundos para que el worker de segundo plano actúe
                import time
                time.sleep(1.3)

                res_updated = client.get("/api/bcb/tipo-cambio")
                data_updated = res_updated.json()
                new_rate_str = data_updated["tipo_cambio_formateado"]

                # Comprobar que se ejecutó al menos una actualización
                self.assertGreaterEqual(state.update_count, 1)
                new_rate = Decimal(new_rate_str)
                self.assertGreaterEqual(new_rate, MIN_EXCHANGE_RATE)
                self.assertLessEqual(new_rate, MAX_EXCHANGE_RATE)
        finally:
            del os.environ["BCB_UPDATE_INTERVAL"]


if __name__ == "__main__":
    unittest.main()
