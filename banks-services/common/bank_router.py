"""Contrato HTTP comun para los servicios de las entidades financieras."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class ConfirmationRequest(BaseModel):
    account_ref: str = Field(min_length=1, description="Referencia interna Nro del dataset")
    verification_code: str = Field(pattern=r"^[0-9A-Fa-f]{8}$")
    saldo_bs: str = Field(min_length=1, description="Saldo convertido recibido desde ASFI")
    exchange_rate: str = Field(min_length=1)
    converted_at: datetime


class BankStore(Protocol):
    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        ...

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        ...


class JsonBankStore:
    """Almacen local para pruebas; luego puede sustituirse por un adaptador de BD."""

    def __init__(self, source: Path):
        self.source = source
        self._lock = threading.Lock()
        self._accounts = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.source.exists():
            return {}
        accounts = {}
        with self.source.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    record = json.loads(line)
                    accounts[str(record["Nro"])] = record
        return accounts

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        records = list(self._accounts.values())[offset:offset + limit]
        return [
            {key: value for key, value in record.items() if not key.startswith("_")}
            for record in records
        ]

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        with self._lock:
            account = self._accounts.get(request.account_ref)
            if account is None:
                raise KeyError("Cuenta no encontrada")

            account["_verification_code"] = request.verification_code.upper()
            account["_saldo_bs"] = request.saldo_bs
            account["_exchange_rate"] = request.exchange_rate
            account["_converted_at"] = request.converted_at.isoformat()
            self._persist()
            return {
                "account_ref": request.account_ref,
                "verification_code": request.verification_code.upper(),
                "status": "CONFIRMADA",
                "converted_at": request.converted_at,
            }

    def _persist(self) -> None:
        with self.source.open("w", encoding="utf-8") as file:
            for record in self._accounts.values():
                json.dump(record, file, ensure_ascii=False)
                file.write("\n")


def create_bank_router(store: BankStore, bank_id: int) -> APIRouter:
    """Crea los endpoints estandarizados para una entidad bancaria."""
    router = APIRouter(prefix="/api/banco", tags=[f"Banco {bank_id}"])

    @router.get("/cuentas/cifradas")
    def get_encrypted_accounts(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        return {
            "banco_id": bank_id,
            "offset": offset,
            "limit": limit,
            "cuentas": store.encrypted_accounts(offset, limit),
        }

    @router.post("/cuentas/confirmar")
    def confirm_account(request: ConfirmationRequest) -> dict[str, Any]:
        try:
            return store.confirm(request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return router
