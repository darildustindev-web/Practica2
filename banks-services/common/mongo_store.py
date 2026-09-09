"""Adaptador MongoDB para el contrato común de los servicios bancarios."""
from __future__ import annotations

import threading
from typing import Any

from pymongo import MongoClient

from common.bank_router import ConfirmationRequest


class MongoStore:
    def __init__(self, url: str):
        prefix = "mongodb://"
        if not url.startswith(prefix):
            raise ValueError("DATABASE_URL de MongoDB debe comenzar con mongodb://")
        self._client = MongoClient(url, serverSelectionTimeoutMS=5000)
        database_name = url.rstrip("/").rsplit("/", 1)[-1]
        if not database_name or ":" in database_name:
            raise ValueError("DATABASE_URL de MongoDB debe incluir el nombre de la base")
        self._collection = self._client[database_name]["cuentas"]
        self._lock = threading.Lock()
        self._collection.create_index("nro", unique=True)

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        projection = {"_id": 0}
        cursor = self._collection.find({}, projection).sort("nro", 1).skip(offset).limit(limit)
        return [self._to_api_record(record) for record in cursor]

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        with self._lock:
            result = self._collection.update_one(
                {"nro": request.account_ref},
                {
                    "$set": {
                        "saldo_bs": request.saldo_bs,
                        "codigo_verificacion": request.verification_code.upper(),
                        "tipo_cambio": request.exchange_rate,
                        "convertido_at": request.converted_at.isoformat(),
                    }
                },
            )
            if result.matched_count != 1:
                raise KeyError("Cuenta no encontrada")
        return {
            "account_ref": request.account_ref,
            "verification_code": request.verification_code.upper(),
            "status": "CONFIRMADA",
            "converted_at": request.converted_at,
        }

    def confirm_batch(self, requests: list[ConfirmationRequest]) -> list[dict[str, Any]]:
        if not requests:
            return []
        from pymongo import UpdateOne
        operations = [
            UpdateOne(
                {"nro": r.account_ref},
                {
                    "$set": {
                        "saldo_bs": r.saldo_bs,
                        "codigo_verificacion": r.verification_code.upper(),
                        "tipo_cambio": r.exchange_rate,
                        "convertido_at": r.converted_at.isoformat(),
                    }
                }
            )
            for r in requests
        ]
        with self._lock:
            self._collection.bulk_write(operations, ordered=False)
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
        from pymongo import ReplaceOne
        operations = [
            ReplaceOne(
                {"nro": str(r["Nro"])},
                {
                    "nro": str(r["Nro"]),
                    "identificacion": r["Identificacion"],
                    "nombres": r["Nombres"],
                    "apellidos": r["Apellidos"],
                    "nro_cuenta": r["NroCuenta"],
                    "id_banco": int(r["IdBanco"]),
                    "saldo": r["Saldo"],
                },
                upsert=True,
            )
            for r in records
        ]
        with self._lock:
            self._collection.bulk_write(operations, ordered=False)

    @staticmethod
    def _to_api_record(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "Nro": record["nro"],
            "Identificacion": record["identificacion"],
            "Nombres": record["nombres"],
            "Apellidos": record["apellidos"],
            "NroCuenta": record["nro_cuenta"],
            "IdBanco": record["id_banco"],
            "Saldo": record["saldo"],
        }
