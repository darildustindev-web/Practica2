"""Microservicio Banco 13 - Banco de Desarrollo Productivo S.A.M. (BDP)
Algoritmo de cifrado: ECC (Criptografía de Curva Elíptica SECP256R1 con ECDH + HKDF + AES)
Almacenamiento NoSQL: MongoDB (base de datos bank_bdp) y Redis (caché y trazabilidad) / Neo4j
Puerto asignado: 8113
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICES_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from bank_template.main import create_app

storage = os.getenv("BANK_STORAGE", "neo4j")
default_url = "neo4j://neo4j:bdp_password@127.0.0.1:7687" if storage == "neo4j" else "mongodb://127.0.0.1:27017/bank_bdp"
db_url = os.getenv("DATABASE_URL", default_url)

app = create_app(bank_id=13, storage=storage, database_url=db_url)

