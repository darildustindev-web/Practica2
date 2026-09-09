"""Adaptador Redis para el contrato común de los servicios bancarios."""
from __future__ import annotations

import threading
from typing import Any
from urllib.parse import urlparse

from redis import Redis

from common.bank_router import ConfirmationRequest


class RedisStore:
    def __init__(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme != "redis" or not parsed.hostname:
            raise ValueError("DATABASE_URL de Redis debe usar redis://")
        self._redis = Redis(
            host=parsed.hostname,
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/") or 0),
            decode_responses=True,
        )
        self._prefix = f"bank:{parsed.fragment or 'default'}"
        self._lock = threading.Lock()
        self._redis.ping()

    def _key(self, account_ref: str) -> str:
        return f"{self._prefix}:cuenta:{account_ref}"

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        keys = sorted(self._redis.scan_iter(match=f"{self._prefix}:cuenta:*"))
        records = []
        for key in keys[offset:offset + limit]:
            record = self._redis.hgetall(key)
            if record:
                records.append(
                    {
                        "Nro": record["nro"],
                        "Identificacion": record["identificacion"],
                        "Nombres": record["nombres"],
                        "Apellidos": record["apellidos"],
                        "NroCuenta": record["nro_cuenta"],
                        "IdBanco": int(record["id_banco"]),
                        "Saldo": record["saldo"],
                    }
                )
        return records

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        with self._lock:
            key = self._key(request.account_ref)
            if not self._redis.exists(key):
                raise KeyError("Cuenta no encontrada")
            self._redis.hset(
                key,
                mapping={
                    "saldo_bs": request.saldo_bs,
                    "codigo_verificacion": request.verification_code.upper(),
                    "tipo_cambio": request.exchange_rate,
                    "convertido_at": request.converted_at.isoformat(),
                },
            )
        return {
            "account_ref": request.account_ref,
            "verification_code": request.verification_code.upper(),
            "status": "CONFIRMADA",
            "converted_at": request.converted_at,
        }

    def confirm_batch(self, requests: list[ConfirmationRequest]) -> list[dict[str, Any]]:
        if not requests:
            return []
        with self._lock:
            pipe = self._redis.pipeline(transaction=False)
            for r in requests:
                pipe.hset(
                    self._key(r.account_ref),
                    mapping={
                        "saldo_bs": r.saldo_bs,
                        "codigo_verificacion": r.verification_code.upper(),
                        "tipo_cambio": r.exchange_rate,
                        "convertido_at": r.converted_at.isoformat(),
                    }
                )
            pipe.execute()
        return [
            {
                "account_ref": r.account_ref,
                "verification_code": r.verification_code.upper(),
                "status": "CONFIRMADA",
                "converted_at": r.converted_at,
            }
            for r in requests
        ]

    def upsert_account(self, record: dict[str, Any]) -> None:
        self.upsert_accounts_batch([record])

    def upsert_accounts_batch(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        with self._lock:
            pipe = self._redis.pipeline(transaction=False)
            for record in records:
                account = {
                    "nro": str(record["Nro"]),
                    "identificacion": record["Identificacion"],
                    "nombres": record["Nombres"],
                    "apellidos": record["Apellidos"],
                    "nro_cuenta": record["NroCuenta"],
                    "id_banco": str(int(record["IdBanco"])),
                    "saldo": record["Saldo"],
                }
                pipe.hset(self._key(account["nro"]), mapping=account)
            pipe.execute()
