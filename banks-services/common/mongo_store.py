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

    def upsert_account(self, record: dict[str, Any]) -> None:
        document = {
            "nro": str(record["Nro"]),
            "identificacion": record["Identificacion"],
            "nombres": record["Nombres"],
            "apellidos": record["Apellidos"],
            "nro_cuenta": record["NroCuenta"],
            "id_banco": int(record["IdBanco"]),
            "saldo": record["Saldo"],
        }
        with self._lock:
            self._collection.replace_one({"nro": document["nro"]}, document, upsert=True)

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
