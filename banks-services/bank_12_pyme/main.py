"""Microservicio Banco 12 - Banco PYME de la Comunidad S.A.
Algoritmo de cifrado: ElGamal
Almacenamiento NoSQL: MongoDB (base de datos bank_pyme) y Redis (caché y trazabilidad)
Puerto asignado: 8112
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICES_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from bank_template.main import create_app

db_url = os.getenv("DATABASE_URL", "mongodb://127.0.0.1:27017/bank_pyme")
storage = os.getenv("BANK_STORAGE", "mongo")

app = create_app(bank_id=12, storage=storage, database_url=db_url)
