"""Demostración en vivo de las Consideraciones de Seguridad del enunciado.

Levanta un servicio bancario de prueba con la protección activada y ejecuta
cuatro escenarios delante del docente:

  1. Petición legítima de la ASFI                        -> ACEPTADA
  2. Suplantación (Spoofing): un tercero sin el secreto  -> RECHAZADA
  3. Manipulación en tránsito (MITM): se altera el saldo -> RECHAZADA
  4. Ataque de repetición (Replay): se reenvía la misma
     petición firmada, byte por byte                     -> RECHAZADA

Uso:
    python scripts/demo_seguridad.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# La protección se activa con esta variable. En producción se define fuera.
os.environ.setdefault("ASFI_HMAC_SECRET", "secreto-compartido-asfi-2026")

from fastapi import FastAPI                    # noqa: E402
from fastapi.testclient import TestClient      # noqa: E402
from shared import seguridad                   # noqa: E402


def construir_app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/banco/cuentas/confirmar")
    async def confirmar(payload: dict):
        return {"status": "CONFIRMADA", "recibido": payload}

    activa = seguridad.instalar_middleware(app)
    print(f"Protección HMAC entre nodos: {'ACTIVA' if activa else 'APAGADA'}")
    return app


def titulo(n: int, texto: str) -> None:
    print("\n" + "=" * 70)
    print(f"ESCENARIO {n}: {texto}")
    print("=" * 70)


def main() -> None:
    cliente = TestClient(construir_app())
    ruta = "/api/banco/cuentas/confirmar"
    cuerpo = json.dumps({
        "account_ref": "1001",
        "verification_code": "A1B2C3D4",
        "saldo_bs": "6960.0000",
        "exchange_rate": "6.9600",
    }).encode()

    # ---------------------------------------------------------------
    titulo(1, "Petición legítima firmada por la ASFI")
    cabeceras = seguridad.cabeceras_de_firma("POST", ruta, cuerpo)
    r = cliente.post(ruta, content=cuerpo, headers={**cabeceras, "Content-Type": "application/json"})
    print(f"  HTTP {r.status_code} -> {str(r.json())[:90]}")
    assert r.status_code == 200, "La petición legítima debería aceptarse"
    print("  RESULTADO: ACEPTADA (correcto)")

    # ---------------------------------------------------------------
    titulo(2, "Suplantación de identidad (Spoofing): atacante sin el secreto")
    falsas = dict(cabeceras)
    falsas[seguridad.CABECERA_FIRMA] = "0" * 64
    falsas[seguridad.CABECERA_NONCE] = "nonce-del-atacante"
    r = cliente.post(ruta, content=cuerpo, headers={**falsas, "Content-Type": "application/json"})
    print(f"  HTTP {r.status_code} -> {r.json().get('detail')}")
    assert r.status_code == 401, "El atacante no debería poder confirmar"
    print("  RESULTADO: RECHAZADA (correcto)")

    # ---------------------------------------------------------------
    titulo(3, "Manipulación en tránsito (MITM): se altera el saldo del mensaje")
    cuerpo_alterado = cuerpo.replace(b'"6960.0000"', b'"9999999.0000"')
    cabeceras = seguridad.cabeceras_de_firma("POST", ruta, cuerpo)   # firma del original
    r = cliente.post(ruta, content=cuerpo_alterado,
                     headers={**cabeceras, "Content-Type": "application/json"})
    print(f"  Saldo original : 6960.0000")
    print(f"  Saldo inyectado: 9999999.0000")
    print(f"  HTTP {r.status_code} -> {r.json().get('detail')}")
    assert r.status_code == 401, "La alteración del cuerpo debería detectarse"
    print("  RESULTADO: RECHAZADA (correcto)")

    # ---------------------------------------------------------------
    titulo(4, "Ataque de repetición (Replay): se reenvía la MISMA petición firmada")
    cabeceras = seguridad.cabeceras_de_firma("POST", ruta, cuerpo)
    primera = cliente.post(ruta, content=cuerpo, headers={**cabeceras, "Content-Type": "application/json"})
    print(f"  1er envío  HTTP {primera.status_code} (legítimo)")
    segunda = cliente.post(ruta, content=cuerpo, headers={**cabeceras, "Content-Type": "application/json"})
    print(f"  2do envío  HTTP {segunda.status_code} -> {segunda.json().get('detail')}")
    assert primera.status_code == 200 and segunda.status_code == 401, "El replay debería rechazarse"
    print("  RESULTADO: RECHAZADA (correcto)")

    print("\n" + "=" * 70)
    print("Los 4 escenarios se comportaron como exige el enunciado.")
    print("=" * 70)


if __name__ == "__main__":
    main()
