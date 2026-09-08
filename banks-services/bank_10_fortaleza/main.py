"""Microservicio Banco 10 - Banco Fortaleza S.A.
Algoritmo de cifrado: AES
Almacenamiento NoSQL: Redis (motor primario en memoria) y MongoDB (base bank_fortaleza)
Puerto asignado: 8110
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICES_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from bank_template.main import create_app

storage = os.getenv("BANK_STORAGE", "redis")
default_url = "redis://127.0.0.1:6379/0#bank10" if storage == "redis" else "mongodb://127.0.0.1:27017/bank_fortaleza"
db_url = os.getenv("DATABASE_URL", default_url)

app = create_app(bank_id=10, storage=storage, database_url=db_url)
