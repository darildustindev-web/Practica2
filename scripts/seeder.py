"""Genera registros cifrados por banco a partir del dataset de la practica.

Uso:
    python3 scripts/seeder.py dataset.csv --output-dir data/seed

El resultado es un JSONL por banco. La insercion en cada motor de BD se mantiene
separada para que el seeder no dependa de PostgreSQL, MySQL, MongoDB o Neo4j.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRYPTO_ROOT = PROJECT_ROOT / "asfi-service"
sys.path.insert(0, str(CRYPTO_ROOT))

from crypto.ciphers import ECCCipher
from crypto.key_manager import CipherFactory, get_bank_key


REQUIRED_COLUMNS = {
    "Nro",
    "Identificacion",
    "Nombres",
    "Apellidos",
    "NroCuenta",
    "IdBanco",
    "Saldo",
}
SENSITIVE_COLUMNS = ("Identificacion", "Nombres", "Apellidos", "NroCuenta", "Saldo")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cifra el dataset y lo separa por banco.")
    parser.add_argument("dataset", type=Path, help="Ruta al dataset en formato CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("data/seed"))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita la cantidad total de registros válidos procesados",
    )
    parser.add_argument(
        "--limit-per-bank",
        type=int,
        default=None,
        help="Limita la cantidad de registros por banco (ej. 1000)",
    )
    return parser.parse_args()


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    return {str(key).strip(): (value or "").strip() for key, value in row.items()}


def create_bank_strategies() -> dict[int, tuple[Any, Any]]:
    strategies = {}
    for bank_id in range(1, 15):
        cipher, key = CipherFactory.get_cipher_for_bank(bank_id)
        if isinstance(cipher, ECCCipher):
            key = key.public_key()
        strategies[bank_id] = (cipher, key)
    return strategies


def encrypt_row(row: dict[str, str], cipher: Any, key: Any) -> dict[str, Any]:
    encrypted = dict(row)
    for column in SENSITIVE_COLUMNS:
        encrypted[column] = cipher.encrypt(row[column], key)
    encrypted["IdBanco"] = int(row["IdBanco"])
    return encrypted


def process_dataset(
    dataset: Path,
    output_dir: Path,
    limit: int | None = None,
    limit_per_bank: int | None = None,
) -> tuple[int, int, dict[int, int]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    strategies = create_bank_strategies()
    files = {}
    counts = {bank_id: 0 for bank_id in range(1, 15)}
    total_valid = 0
    total_skipped = 0

    try:
        for bank_id in range(1, 15):
            files[bank_id] = (output_dir / f"bank_{bank_id:02d}.jsonl").open(
                "w", encoding="utf-8"
            )

        with dataset.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            columns = set(reader.fieldnames or [])
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise ValueError(f"Faltan columnas requeridas: {', '.join(sorted(missing))}")

            for row_idx, raw_row in enumerate(reader, start=2):
                row = normalize_row(raw_row)
                bank_str = row.get("IdBanco", "")
                if bank_str not in {str(b) for b in range(1, 15)}:
                    total_skipped += 1
                    print(f"⚠️ [Fila {row_idx}] Descartada por IdBanco inválido: '{bank_str}' (Nro: {row.get('Nro')})")
                    continue

                bank_id = int(bank_str)
                if limit_per_bank is not None and counts[bank_id] >= limit_per_bank:
                    # Si todos los bancos llegaron al límite, terminar
                    if all(c >= limit_per_bank for c in counts.values()):
                        break
                    continue

                cipher, key = strategies[bank_id]
                try:
                    record = encrypt_row(row, cipher, key)
                    json.dump(record, files[bank_id], ensure_ascii=False)
                    files[bank_id].write("\n")
                    counts[bank_id] += 1
                    total_valid += 1
                except Exception as err:
                    total_skipped += 1
                    print(f"⚠️ [Fila {row_idx}] Error al cifrar banco {bank_id}: {err}")
                    continue

                if limit is not None and total_valid >= limit:
                    break
    finally:
        for f in files.values():
            f.close()

    return total_valid, total_skipped, counts


def main() -> None:
    args = parse_args()
    total_valid, total_skipped, counts = process_dataset(
        args.dataset,
        args.output_dir,
        limit=args.limit,
        limit_per_bank=args.limit_per_bank,
    )
    configured_banks = sum(1 for count in counts.values() if count > 0)
    print(f"\n==========================================")
    print(f"Registros válidos cifrados: {total_valid}")
    print(f"Registros descartados/anomalías: {total_skipped}")
    print(f"Bancos con datos: {configured_banks}/14")
    print(f"==========================================")
    for bank_id, count in counts.items():
        if count:
            bank = get_bank_key(bank_id)
            print(f"Banco {bank_id:02d} ({bank['type']}): {count} registros")


if __name__ == "__main__":
    main()
