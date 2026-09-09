"""Microservicio Banco 14 - Banco de la Nación Argentina
Algoritmo de cifrado: ChaCha20
Almacenamiento NoSQL: MongoDB (base de datos bank_argentina) y Redis (caché y trazabilidad)
Puerto asignado: 8114
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICES_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from bank_template.main import create_app

db_url = os.getenv("DATABASE_URL", "mongodb://127.0.0.1:27017/bank_argentina")
storage = os.getenv("BANK_STORAGE", "mongo")

app = create_app(bank_id=14, storage=storage, database_url=db_url)
