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
        help="Limita la cantidad de registros para una prueba local",
    )
    return parser.parse_args()


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    return {str(key).strip(): (value or "").strip() for key, value in row.items()}


def load_rows(dataset: Path, limit: int | None) -> list[dict[str, str]]:
    with dataset.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Faltan columnas requeridas: {', '.join(sorted(missing))}")

        rows = []
        for row in reader:
            normalized = normalize_row(row)
            if normalized["IdBanco"] not in {str(bank_id) for bank_id in range(1, 15)}:
                raise ValueError(f"IdBanco invalido: {normalized['IdBanco']}")
            rows.append(normalized)
            if limit is not None and len(rows) >= limit:
                break
    return rows


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


def write_bank_files(rows: list[dict[str, str]], output_dir: Path) -> dict[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    strategies = create_bank_strategies()
    files = {}
    counts = {bank_id: 0 for bank_id in range(1, 15)}

    try:
        for bank_id in range(1, 15):
            files[bank_id] = (output_dir / f"bank_{bank_id:02d}.jsonl").open(
                "w", encoding="utf-8"
            )

        for row in rows:
            bank_id = int(row["IdBanco"])
            cipher, key = strategies[bank_id]
            record = encrypt_row(row, cipher, key)
            json.dump(record, files[bank_id], ensure_ascii=False)
            files[bank_id].write("\n")
            counts[bank_id] += 1
    finally:
        for file in files.values():
            file.close()

    return counts


def main() -> None:
    args = parse_args()
    rows = load_rows(args.dataset, args.limit)
    counts = write_bank_files(rows, args.output_dir)
    configured_banks = sum(1 for count in counts.values() if count > 0)
    print(f"Registros procesados: {len(rows)}")
    print(f"Bancos con datos: {configured_banks}/14")
    for bank_id, count in counts.items():
        if count:
            bank = get_bank_key(bank_id)
            print(f"Banco {bank_id} ({bank['type']}): {count} registros")


if __name__ == "__main__":
    main()
