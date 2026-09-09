"""Genera registros cifrados por banco a partir del dataset de la practica.

Uso:
    python3 scripts/seeder.py dataset.csv --output-dir data/seed

El resultado es un JSONL por banco (bank_01.jsonl ... bank_14.jsonl) con los
campos sensibles ya cifrados con el algoritmo asignado a cada entidad
financiera. La insercion en cada motor de BD se mantiene separada (ver
scripts/load_*.py) para que el seeder no dependa de PostgreSQL, MySQL,
MongoDB o Neo4j.

Robustez (Integrante 2):
    - Las filas invalidas (columna faltante, IdBanco fuera de rango, Saldo no
      numerico, Nro duplicado) NO abortan el proceso: se descartan y se
      reportan en <output-dir>/rejected_rows.csv junto con el motivo.
    - Se compara el conteo real de cada banco contra la distribucion oficial
      del 1% publicada en el enunciado (docx) y se advierte si no coincide,
      sin inventar ni descartar filas reales por defecto.
    - Con --target-distribution official_1pct se puede recortar (nunca
      inventar) cada banco hasta su cuota oficial, de forma reproducible via
      --seed, para cuando el equipo decida usar exactamente esos totales.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass, field
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
VALID_BANK_IDS = {str(bank_id) for bank_id in range(1, 15)}

# Distribucion oficial de la muestra del 1% segun el enunciado
# ("01 - Practica 2 Algoritmos de Encriptacion", tabla de entidades financieras).
OFFICIAL_1PCT_DISTRIBUTION: dict[int, int] = {
    1: 22472,
    2: 19975,
    3: 14981,
    4: 13983,
    5: 10487,
    6: 9488,
    7: 8489,
    8: 7491,
    9: 5493,
    10: 3496,
    11: 3995,
    12: 2247,
    13: 999,
    14: 200,
}


@dataclass
class LoadResult:
    valid_rows: list[dict[str, str]] = field(default_factory=list)
    rejected_rows: list[dict[str, str]] = field(default_factory=list)
    total_read: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cifra el dataset y lo separa por banco.")
    parser.add_argument("dataset", type=Path, help="Ruta al dataset en formato CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("data/seed"))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita la cantidad de registros leidos, para una prueba local",
    )
    parser.add_argument(
        "--target-distribution",
        choices=["none", "official_1pct"],
        default="none",
        help=(
            "none (por defecto): usa todas las filas validas tal como vienen "
            "etiquetadas por IdBanco. official_1pct: recorta cada banco (nunca "
            "inventa filas) hasta la cuota oficial del 1%% del enunciado."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Semilla para el muestreo reproducible con --target-distribution",
    )
    return parser.parse_args()


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {str(key).strip(): (value or "").strip() for key, value in row.items()}
    if "Saldo" in normalized:
        normalized["Saldo"] = normalize_saldo(normalized["Saldo"])
    return normalized


def normalize_saldo(value: str) -> str:
    """Normaliza saldos con puntos de miles sin alterar los decimales."""
    saldo = str(value).strip().replace(" ", "")
    parts = saldo.split(".")
    if len(parts) > 2 and parts[0].isdigit() and all(len(part) == 3 and part.isdigit() for part in parts[1:]):
        return "".join(parts)
    return saldo


def parse_saldo(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_rows(dataset: Path, limit: int | None) -> LoadResult:
    """Lee el CSV y separa filas validas de invalidas sin abortar el proceso."""
    result = LoadResult()
    seen_nro: set[str] = set()

    with dataset.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Faltan columnas requeridas: {', '.join(sorted(missing))}")

        for raw_row in reader:
            if limit is not None and result.total_read >= limit:
                break
            result.total_read += 1
            row = normalize_row(raw_row)

            reason = validate_row(row, seen_nro)
            if reason:
                rejected = dict(row)
                rejected["_motivo_rechazo"] = reason
                result.rejected_rows.append(rejected)
                continue

            seen_nro.add(row["Nro"])
            result.valid_rows.append(row)

    return result


def validate_row(row: dict[str, str], seen_nro: set[str]) -> str | None:
    """Devuelve el motivo de rechazo, o None si la fila es valida."""
    nro = row.get("Nro", "")
    if not nro:
        return "Nro vacio"
    if nro in seen_nro:
        return "Nro duplicado"

    for column in ("Identificacion", "Nombres", "Apellidos", "NroCuenta"):
        if not row.get(column):
            return f"campo obligatorio vacio: {column}"

    id_banco = row.get("IdBanco", "")
    if id_banco not in VALID_BANK_IDS:
        return f"IdBanco invalido: {id_banco!r}"

    saldo = row.get("Saldo", "")
    if not saldo or parse_saldo(saldo) is None:
        return f"Saldo no numerico: {saldo!r}"

    return None


def apply_target_distribution(
    rows_by_bank: dict[int, list[dict[str, str]]],
    mode: str,
    seed: int,
) -> tuple[dict[int, list[dict[str, str]]], dict[int, int]]:
    """Recorta (nunca agranda) cada banco hasta su cuota objetivo.

    Devuelve las filas resultantes y un diccionario con el faltante
    (cuota - disponibles) por banco cuando el pool no alcanza la cuota.
    """
    if mode == "none":
        return rows_by_bank, {}

    rng = random.Random(seed)
    trimmed: dict[int, list[dict[str, str]]] = {}
    shortfall: dict[int, int] = {}
    for bank_id, rows in rows_by_bank.items():
        target = OFFICIAL_1PCT_DISTRIBUTION.get(bank_id)
        if target is None or len(rows) <= target:
            trimmed[bank_id] = rows
            if target is not None and len(rows) < target:
                shortfall[bank_id] = target - len(rows)
        else:
            trimmed[bank_id] = rng.sample(rows, target)
    return trimmed, shortfall


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


def group_by_bank(rows: list[dict[str, str]]) -> dict[int, list[dict[str, str]]]:
    grouped: dict[int, list[dict[str, str]]] = {bank_id: [] for bank_id in range(1, 15)}
    for row in rows:
        grouped[int(row["IdBanco"])].append(row)
    return grouped


def write_bank_files(
    rows_by_bank: dict[int, list[dict[str, str]]], output_dir: Path
) -> dict[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    strategies = create_bank_strategies()
    counts = {}

    for bank_id in range(1, 15):
        rows = rows_by_bank.get(bank_id, [])
        cipher, key = strategies[bank_id]
        path = output_dir / f"bank_{bank_id:02d}.jsonl"
        with path.open("w", encoding="utf-8") as file:
            for row in rows:
                record = encrypt_row(row, cipher, key)
                json.dump(record, file, ensure_ascii=False)
                file.write("\n")
        counts[bank_id] = len(rows)

    return counts


def write_rejected_report(rejected_rows: list[dict[str, str]], output_dir: Path) -> Path | None:
    if not rejected_rows:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "rejected_rows.csv"
    fieldnames = sorted({key for row in rejected_rows for key in row.keys()})
    # Aseguramos que el motivo salga siempre al final para facilitar la lectura.
    if "_motivo_rechazo" in fieldnames:
        fieldnames.remove("_motivo_rechazo")
        fieldnames.append("_motivo_rechazo")
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rejected_rows)
    return path


def main() -> None:
    args = parse_args()
    result = load_rows(args.dataset, args.limit)
    rows_by_bank = group_by_bank(result.valid_rows)

    rows_by_bank, shortfall = apply_target_distribution(
        rows_by_bank, args.target_distribution, args.seed
    )

    counts = write_bank_files(rows_by_bank, args.output_dir)
    rejected_path = write_rejected_report(result.rejected_rows, args.output_dir)

    print(f"Filas leidas: {result.total_read}")
    print(f"Filas validas: {len(result.valid_rows)}")
    print(f"Filas rechazadas: {len(result.rejected_rows)}"
          + (f" (detalle en {rejected_path})" if rejected_path else ""))
    print(f"Modo de distribucion: {args.target_distribution}")
    print()
    print(f"{'Banco':<4} {'Nombre':<38} {'Cifrado':<10} {'Cargados':>9} {'Oficial 1%':>11} {'Diff':>7}")
    for bank_id in range(1, 15):
        bank = get_bank_key(bank_id)
        loaded = counts.get(bank_id, 0)
        official = OFFICIAL_1PCT_DISTRIBUTION.get(bank_id, 0)
        diff = loaded - official
        flag = "  <-- faltan filas" if bank_id in shortfall else ""
        print(
            f"{bank_id:<4} {bank['name']:<38} {bank['type']:<10} "
            f"{loaded:>9} {official:>11} {diff:>7}{flag}"
        )

    if any(bank_id <= 7 for bank_id, count in counts.items() if count == 0):
        print(
            "\nAdvertencia: al menos un banco relacional (1-7) quedo sin "
            "registros. Revisa el dataset de origen."
        )


if __name__ == "__main__":
    main()
