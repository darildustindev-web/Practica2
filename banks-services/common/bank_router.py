"""Contrato HTTP común para los servicios de las entidades financieras."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from shared.money import parse_money
from shared.conversion import newer_conversion

BANK_METADATA = {
    1: {"name": "Banco Unión S.A.", "algorithm": "César"},
    2: {"name": "Banco Mercantil Santa Cruz S.A.", "algorithm": "Atbash"},
    3: {"name": "Banco Nacional de Bolivia S.A.", "algorithm": "Vigenère"},
    4: {"name": "Banco de Crédito de Bolivia S.A.", "algorithm": "Playfair"},
    5: {"name": "Banco BISA S.A.", "algorithm": "Hill"},
    6: {"name": "Banco Ganadero S.A.", "algorithm": "DES"},
    7: {"name": "Banco Económico S.A.", "algorithm": "3DES"},
    8: {"name": "Banco Prodem S.A.", "algorithm": "Blowfish"},
    9: {"name": "Banco Solidario S.A.", "algorithm": "Twofish"},
    10: {"name": "Banco Fortaleza S.A.", "algorithm": "AES"},
    11: {"name": "Banco FIE S.A.", "algorithm": "RSA"},
    12: {"name": "Banco PYME de la Comunidad S.A.", "algorithm": "ElGamal"},
    13: {"name": "Banco de Desarrollo Productivo S.A.M.", "algorithm": "ECC"},
    14: {"name": "Banco de la Nación Argentina", "algorithm": "ChaCha20"},
}


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(validate_default=True)
    revalue: bool = False
    account_ref: str = Field(default="", description="Referencia interna Nro / CuentaId del dataset")
    cuenta_id: str | None = Field(default=None, description="Alias para account_ref")
    verification_code: str = Field(default="", description="Código de verificación hexadecimal de 8 caracteres (0-9, A-F)")
    codigo_verificacion: str | None = Field(default=None, description="Alias para verification_code")
    saldo_bs: str = Field(..., description="Saldo convertido recibido desde ASFI")
    exchange_rate: str = Field(default="6.9600", description="Tipo de cambio aplicado")
    tipo_cambio: str | None = Field(default=None, description="Alias para exchange_rate")
    converted_at: datetime | None = Field(default=None, description="Fecha/hora de conversión")
    fecha_conversion: datetime | None = Field(default=None, description="Alias para converted_at")

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            ref = (
                data.get("account_ref")
                or data.get("cuenta_id")
                or data.get("nro")
                or data.get("CuentaId")
            )
            data["account_ref"] = str(ref).strip() if ref is not None else ""

            code = (
                data.get("verification_code")
                or data.get("codigo_verificacion")
                or data.get("CodigoVerificacion")
            )
            data["verification_code"] = str(code).strip() if code is not None else ""

            rate = (
                data.get("exchange_rate")
                or data.get("tipo_cambio")
                or data.get("TipoCambio")
                or "6.9600"
            )
            data["exchange_rate"] = str(rate).strip()

            conv = (
                data.get("converted_at")
                or data.get("fecha_conversion")
                or data.get("FechaConversion")
            )
            data["converted_at"] = conv if conv is not None else datetime.now(timezone.utc)
        return data

    @field_validator("saldo_bs", "exchange_rate")
    @classmethod
    def validate_money(cls, value, info):
        return format(parse_money(value, rate=info.field_name == 'exchange_rate'), 'f')

    @field_validator("converted_at")
    @classmethod
    def validate_timestamp(cls, value):
        if value is None or value.tzinfo is None:
            raise ValueError('converted_at requiere zona horaria')
        return value.astimezone(timezone.utc)

    @field_validator("verification_code")
    @classmethod
    def validate_verification_code(cls, v: str) -> str:
        code = v.strip().upper()
        if not re.fullmatch(r"^[0-9A-Fa-f]{8}$", code):
            raise ValueError(
                "El código de verificación debe estar compuesto exactamente por 8 caracteres hexadecimales (0-9, A-F)"
            )
        return code

    @field_validator("account_ref")
    @classmethod
    def validate_account_ref(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("account_ref / cuenta_id no puede estar vacío")
        return v.strip()


class BankStore(Protocol):
    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        ...

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        ...


class JsonBankStore:
    """Almacén local para pruebas; luego puede sustituirse por un adaptador de BD."""

    def __init__(self, source: Path, bank_id: int = 1):
        self.source = source
        self._bank_id = bank_id
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
                    accounts[str(record.get("Nro") or record.get("CuentaId"))] = record
        return accounts

    def count_accounts(self) -> int:
        return len(self._accounts)

    def get_account(self, account_ref: str) -> dict[str, Any] | None:
        return self._accounts.get(str(account_ref))

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        records = list(self._accounts.values())[offset : offset + limit]
        formatted = []
        for record in records:
            item = {key: value for key, value in record.items() if not key.startswith("_")}
            nro = str(item.get("Nro") or item.get("CuentaId", ""))
            item["CuentaId"] = nro
            item["BancoId"] = int(item.get("IdBanco") or self._bank_id)
            item["SaldoUSD"] = item.get("Saldo", "")
            item["SaldoBs"] = record.get("_saldo_bs")
            item["Estado"] = "CONFIRMADA" if record.get("_verification_code") else "PENDIENTE"
            item["CodigoVerificacion"] = record.get("_verification_code")
            item["FechaConversion"] = record.get("_converted_at")
            formatted.append(item)
        return formatted

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        with self._lock:
            account = self._accounts.get(request.account_ref)
            if account is None:
                raise KeyError(f"Cuenta '{request.account_ref}' no encontrada")

            existing_code = account.get("_verification_code")
            if existing_code and not newer_conversion(request, existing_code, account.get('_converted_at')):
                if existing_code == request.verification_code.upper():
                    if (parse_money(account['_saldo_bs']) != parse_money(request.saldo_bs) or
                            parse_money(account['_exchange_rate']) != parse_money(request.exchange_rate)):
                        raise ValueError('Reintento con importe o tasa diferentes')
                    return {
                        "account_ref": request.account_ref,
                        "cuenta_id": request.account_ref,
                        "verification_code": request.verification_code.upper(),
                        "codigo_verificacion": request.verification_code.upper(),
                        "saldo_bs": account.get("_saldo_bs", request.saldo_bs),
                        "status": "CONFIRMADA",
                        "estado": "CONFIRMADA",
                        "converted_at": request.converted_at,
                        "reintento": True,
                    }
                else:
                    raise ValueError(
                        f"Operación rechazada: La cuenta '{request.account_ref}' ya fue confirmada previamente "
                        f"con el código '{existing_code}'"
                    )

            account["_verification_code"] = request.verification_code.upper()
            account["_saldo_bs"] = request.saldo_bs
            account["_exchange_rate"] = request.exchange_rate
            account["_converted_at"] = request.converted_at.isoformat() if request.converted_at else ""
            self._persist()
            return {
                "account_ref": request.account_ref,
                "cuenta_id": request.account_ref,
                "verification_code": request.verification_code.upper(),
                "codigo_verificacion": request.verification_code.upper(),
                "saldo_bs": request.saldo_bs,
                "status": "CONFIRMADA",
                "estado": "CONFIRMADA",
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
    meta = BANK_METADATA.get(bank_id, {"name": f"Banco {bank_id}", "algorithm": "Desconocido"})

    def _handle_confirm(request: ConfirmationRequest) -> dict[str, Any]:
        try:
            return store.confirm(request)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ConnectionError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    def _get_accounts_response(offset: int, limit: int, after: str | None = None) -> dict[str, Any]:
        try:
            cuentas = store.encrypted_accounts_after(after, limit) if after is not None and hasattr(store, 'encrypted_accounts_after') else store.encrypted_accounts(offset, limit)
            total = store.count_accounts() if hasattr(store, "count_accounts") else len(cuentas)
            return {
                "banco_id": bank_id,
                "banco_nombre": meta["name"],
                "algoritmo": meta["algorithm"],
                "offset": offset,
                "limit": limit,
                "total": total,
                "cuentas": cuentas,
                "next_cursor": str(cuentas[-1]["Nro"]) if cuentas and hasattr(store, "encrypted_accounts_after") else None,
            }
        except ConnectionError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    # Endpoint estándar: GET /api/banco/cuentas
    @router.get("/cuentas")
    def get_accounts(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        return _get_accounts_response(offset, limit)

    # Alias compatible con ASFI: GET /api/banco/cuentas/cifradas
    @router.get("/cuentas/cifradas")
    def get_encrypted_accounts(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
        after: str | None = Query(default=None, max_length=255),
    ) -> dict[str, Any]:
        return _get_accounts_response(offset, limit, after)

    # Endpoint para consultar una cuenta individual
    @router.get("/cuentas/{account_ref}")
    def get_account_by_id(account_ref: str) -> dict[str, Any]:
        getter = getattr(store, "get_account", None) or getattr(store, "get_account_by_id", None)
        if getter:
            account = getter(account_ref)
            if account:
                formatted_acc = {
                    "Nro": account.get("nro") or account.get("cuentaId") or account.get("Nro") or account_ref,
                    "CuentaId": account.get("cuentaId") or account.get("nro") or account.get("CuentaId") or account_ref,
                    "BancoId": int(account.get("bancoId") or account.get("id_banco") or account.get("BancoId") or bank_id),
                    "IdBanco": int(account.get("id_banco") or account.get("bancoId") or account.get("IdBanco") or bank_id),
                    "Saldo": account.get("saldo") or account.get("saldoUSD") or account.get("Saldo"),
                    "SaldoUSD": account.get("saldoUSD") or account.get("saldo") or account.get("SaldoUSD"),
                    "SaldoBs": account.get("saldoBs") or account.get("saldo_bs") or account.get("SaldoBs"),
                    "Estado": account.get("estado") or account.get("Estado", "PENDIENTE"),
                    "CodigoVerificacion": (
                        account.get("codigoVerificacion")
                        or account.get("codigo_verificacion")
                        or account.get("CodigoVerificacion")
                    ),
                    "FechaConversion": (
                        account.get("fechaConversion")
                        or account.get("convertido_at")
                        or account.get("FechaConversion")
                    ),
                    "TipoCambio": account.get("tipoCambio") or account.get("tipo_cambio") or account.get("TipoCambio"),
                    "NroCuenta": account.get("nroCuenta") or account.get("nro_cuenta") or account.get("NroCuenta"),
                    "Identificacion": (
                        account.get("identificacion")
                        or account.get("clienteId")
                        or account.get("Identificacion")
                    ),
                    "Nombres": account.get("nombres") or account.get("Nombres"),
                    "Apellidos": account.get("apellidos") or account.get("Apellidos"),
                }
                return {
                    "banco_id": bank_id,
                    "banco_nombre": meta["name"],
                    "algoritmo": meta["algorithm"],
                    "cuenta": formatted_acc,
                }
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta '{account_ref}' no encontrada en el banco {bank_id}",
        )

    # Endpoints para consultas de grafos (Neo4j / BDP)
    @router.get("/clientes")
    def get_clients() -> dict[str, Any]:
        if hasattr(store, "get_all_clients"):
            clients = store.get_all_clients()
            return {
                "banco_id": bank_id,
                "banco_nombre": meta["name"],
                "total_clientes": len(clients),
                "clientes": clients,
            }
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Operación no soportada por el motor de almacenamiento")

    @router.get("/clientes/{client_id}/cuentas")
    def get_client_accounts(client_id: str) -> dict[str, Any]:
        if hasattr(store, "get_accounts_by_client"):
            accounts = store.get_accounts_by_client(client_id)
            return {
                "banco_id": bank_id,
                "cliente_id": client_id,
                "total_cuentas": len(accounts),
                "cuentas": accounts,
            }
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Operación no soportada por el motor de almacenamiento")

    @router.get("/cuentas/{account_ref}/cliente")
    def get_account_client(account_ref: str) -> dict[str, Any]:
        if hasattr(store, "get_client_by_account"):
            client = store.get_client_by_account(account_ref)
            if client:
                return {
                    "banco_id": bank_id,
                    "cuenta_id": account_ref,
                    "cliente": client,
                }
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cliente para la cuenta '{account_ref}' no encontrado")
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Operación no soportada por el motor de almacenamiento")

    @router.get("/grafo")
    def get_graph() -> dict[str, Any]:
        if hasattr(store, "get_graph_clients_and_accounts"):
            graph_data = store.get_graph_clients_and_accounts()
            return {
                "banco_id": bank_id,
                "banco_nombre": meta["name"],
                "total_relaciones": len(graph_data),
                "relaciones": graph_data,
            }
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Operación no soportada por el motor de almacenamiento")

    # Endpoint estándar: POST /api/banco/confirmar
    @router.post("/confirmar")
    def confirm_account(request: ConfirmationRequest) -> dict[str, Any]:
        return _handle_confirm(request)

    # Alias compatible con ASFI: POST /api/banco/cuentas/confirmar
    @router.post("/cuentas/confirmar")
    def confirm_account_alias(request: ConfirmationRequest | list[Any]) -> dict[str, Any]:
        if isinstance(request, ConfirmationRequest):
            return _handle_confirm(request)
        if len(request) > 1000:
            raise HTTPException(status_code=413, detail="Máximo 1000 confirmaciones por lote")
        valid, results = [], []
        for item in request:
            try:
                valid.append(ConfirmationRequest.model_validate(item))
            except ValueError as exc:
                results.append(dict(account_ref=str(item.get('account_ref','')) if isinstance(item,dict) else '',status='ERROR',detail=str(exc)))
        if hasattr(store, 'confirm_batch'):
            results.extend(store.confirm_batch(valid))
        else:
            for item in valid:
                try:
                    receipt = store.confirm(item)
                    # Todo reintento debe coincidir también en importe y tasa.
                    amount = receipt.get('saldo_bs', item.saldo_bs)
                    rate = receipt.get('exchange_rate',receipt.get('tipo_cambio',item.exchange_rate))
                    if parse_money(amount) != parse_money(item.saldo_bs) or parse_money(rate) != parse_money(item.exchange_rate):
                        raise ValueError('El recibo previo tiene importe o tasa diferentes')
                    results.append(dict(receipt, account_ref=item.account_ref, status='CONFIRMADA',
                                        verification_code=item.verification_code,saldo_bs=str(amount),exchange_rate=str(rate)))
                except (KeyError, ValueError) as exc:
                    results.append(dict(account_ref=item.account_ref,status='ERROR',detail=str(exc)))
        return {'resultados': results}

    # Endpoint de información / metadatos del banco
    @router.get("/info")
    def get_bank_info() -> dict[str, Any]:
        total = store.count_accounts() if hasattr(store, "count_accounts") else 0
        health = store.health_check() if hasattr(store, "health_check") else {}
        return {
            "banco_id": bank_id,
            "banco_nombre": meta["name"],
            "algoritmo": meta["algorithm"],
            "total_cuentas": total,
            "health": health,
        }

    return router

