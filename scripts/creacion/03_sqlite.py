"""Creación manual de SQLite Banco 3. No ejecutar contra otra base."""
import argparse
import sqlite3
from pathlib import Path
SCHEMA = 'CREATE TABLE IF NOT EXISTS clientes (\n    nro TEXT PRIMARY KEY,\n    identificacion TEXT NOT NULL,\n    nombres TEXT NOT NULL,\n    apellidos TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS cuentas (\n    nro TEXT PRIMARY KEY,\n    cliente_nro TEXT NOT NULL REFERENCES clientes(nro),\n    nro_cuenta TEXT NOT NULL,\n    id_banco INTEGER NOT NULL,\n    saldo TEXT NOT NULL,\n    saldo_bs TEXT,\n    codigo_verificacion TEXT,\n    tipo_cambio TEXT,\n    convertido_at TEXT\n);\n'
if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--archivo',type=Path,required=True);a=p.parse_args()
    a.archivo.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(a.archivo) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(SCHEMA)
