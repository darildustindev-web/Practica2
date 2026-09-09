from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from crypto.key_manager import CipherFactory

app = FastAPI(title="Servicio Central ASFI", version="1.0.0")
BCB_URL = os.getenv("BCB_URL", "http://localhost:8001/api/bcb/tipo-cambio")
AUDIT_FILE = Path(os.getenv("ASFI_AUDIT_FILE", "data/audit.jsonl"))


def bank_urls() -> dict[int, str]:
    configured_ids = os.getenv("ACTIVE_BANK_IDS", "1,2,3,4,5,6,7,8,9,10,11,12,13,14")
    bank_ids = [int(value.strip()) for value in configured_ids.split(",") if value.strip()]
    invalid_ids = [bank_id for bank_id in bank_ids if bank_id not in range(1, 15)]
    if invalid_ids:
        raise ValueError(f"ACTIVE_BANK_IDS inválido: {invalid_ids}")
    return {
        bank_id: os.getenv(
            f"BANK_URL_{bank_id}",
            f"http://localhost:{8100 + bank_id}/api/banco",
        )
        for bank_id in bank_ids
    }


def generate_verification_code() -> str:
    """Genera un código de verificación de 8 caracteres hexadecimales (0-9, A-F)."""
    return secrets.token_hex(4).upper()


def parse_money(value: object) -> Decimal:
    """Parsea decimales, notación científica y separadores de miles."""
    text = str(value).strip().replace(" ", "")
    if not text:
        raise ValueError("Saldo vacío")

    if text.count(".") > 1 and "e" not in text.lower():
        text = text.replace(".", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text:
        text = text.replace(",", "")

    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        raise ValueError(f"Formato de saldo no válido: {value}")
    return Decimal(text)


async def get_exchange_rate(client: httpx.AsyncClient) -> Decimal:
    response = await client.get(BCB_URL)
    response.raise_for_status()
    return Decimal(str(response.json()["tipo_cambio"]))


async def process_bank(
    client: httpx.AsyncClient,
    bank_id: int,
    base_url: str,
    exchange_rate: Decimal,
) -> list[dict[str, object]]:
    cipher, key = CipherFactory.get_cipher_for_bank(bank_id)
    results = []
    offset = 0
    limit = 1000

    while True:
        response = await client.get(
            f"{base_url}/cuentas/cifradas",
            params={"offset": offset, "limit": limit},
        )
        response.raise_for_status()
        accounts = response.json().get("cuentas", [])
        if not accounts:
            break

        confirmations_payload = []
        parsed_accounts = []

        for account in accounts:
            converted_at = datetime.now(timezone.utc)
            verification_code = generate_verification_code()
            try:
                saldo_usd = parse_money(cipher.decrypt(account["Saldo"], key))
                saldo_bs = (saldo_usd * exchange_rate).quantize(Decimal("0.0001"))
                confirmations_payload.append(
                    {
                        "account_ref": str(account["Nro"]),
                        "verification_code": verification_code,
                        "saldo_bs": format(saldo_bs, "f"),
                        "exchange_rate": format(exchange_rate, "f"),
                        "converted_at": converted_at.isoformat(),
                    }
                )
                parsed_accounts.append(
                    {
                        "timestamp": converted_at.isoformat(),
                        "tipo_cambio": format(exchange_rate, "f"),
                        "cuenta_id": str(account.get("Nro", "")),
                        "banco_id": bank_id,
                        "codigo_verificacion": verification_code,
                        "saldo_usd": format(saldo_usd, "f"),
                        "saldo_bs": format(saldo_bs, "f"),
                        "estado": "CONFIRMADA",
                    }
                )
            except (InvalidOperation, KeyError, ValueError) as error:
                parsed_accounts.append(
                    {
                        "timestamp": converted_at.isoformat(),
                        "tipo_cambio": format(exchange_rate, "f"),
                        "cuenta_id": str(account.get("Nro", "")),
                        "banco_id": bank_id,
                        "codigo_verificacion": verification_code,
                        "saldo_usd": None,
                        "saldo_bs": None,
                        "estado": f"ERROR: {error}",
                    }
                )

        if confirmations_payload:
            try:
                conf_response = await client.post(
                    f"{base_url}/cuentas/confirmar",
                    json=confirmations_payload,
                )
                conf_response.raise_for_status()
            except httpx.HTTPError as error:
                for item in parsed_accounts:
                    if item["estado"] == "CONFIRMADA":
                        item["estado"] = f"ERROR_CONFIRMACION: {error}"

        results.extend(parsed_accounts)

        if len(accounts) < limit:
            break
        offset += len(accounts)

    return results


async def execute_conversion() -> list[dict[str, object]]:
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        exchange_rate = await get_exchange_rate(client)
        jobs = [
            process_bank(client, bank_id, url, exchange_rate)
            for bank_id, url in bank_urls().items()
        ]
        bank_results = await asyncio.gather(*jobs, return_exceptions=True)

    results = []
    for bank_id, bank_result in zip(bank_urls(), bank_results):
        if isinstance(bank_result, Exception):
            results.append({"banco_id": bank_id, "estado": f"ERROR: {bank_result}"})
        else:
            results.extend(bank_result)

    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_FILE.open("a", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, ensure_ascii=False) + "\n")
    return results

@app.get("/")
def read_root():
    return {"message": "Servicio Central ASFI Operativo"}

@app.post("/api/asfi/ejecutar-conversion")
async def ejecutar_barrido_conversion():
    """
    Realiza el barrido paralelo asíncrono consultando el tipo de cambio del BCB
    y consumiendo las APIs de los 14 bancos de forma simultánea.
    """
    try:
        results = await execute_conversion()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar el BCB: {error}") from error
    return {
        "status": "PROCESADO",
        "mensaje": "Barrido paralelo completado",
        "transacciones": len(results),
        "confirmadas": sum(result.get("estado") == "CONFIRMADA" for result in results),
        "errores": sum(str(result.get("estado", "")).startswith("ERROR") for result in results),
    }
