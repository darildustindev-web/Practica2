"""Espera a que los 10 contenedores de base de datos acepten conexiones.

Docker informa "running" apenas arranca el proceso, pero PostgreSQL y sobre todo
MySQL tardan varios segundos más en aceptar conexiones. Este script comprueba la
conexión de verdad con el driver de cada motor, que es la única señal fiable.

Uso:
    python scripts/esperar_bases.py                  # espera hasta 180 s
    python scripts/esperar_bases.py --timeout 300
    python scripts/esperar_bases.py --motores postgres,mysql
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DESTINOS = [
    ("PostgreSQL ASFI",      "postgres", "postgresql://asfi_user:asfi_password@127.0.0.1:5434/asfi_db"),
    ("PostgreSQL Unión",     "postgres", "postgresql://union_user:union_password@127.0.0.1:5433/bank_union"),
    ("PostgreSQL BCP",       "postgres", "postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp"),
    ("PostgreSQL Ganadero",  "postgres", "postgresql://ganadero_user:ganadero_password@127.0.0.1:5436/bank_ganadero"),
    ("MySQL Mercantil",      "mysql",    "mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil"),
    ("MySQL BISA",           "mysql",    "mysql://bisa_user:bisa_password@127.0.0.1:3307/bank_bisa"),
    ("MySQL Económico",      "mysql",    "mysql://economico_user:economico_password@127.0.0.1:3308/bank_economico"),
    ("MongoDB",              "mongo",    "mongodb://127.0.0.1:27017"),
    ("Redis",                "redis",    "redis://127.0.0.1:6379/0"),
    ("Neo4j",                "neo4j",    "neo4j://neo4j:bdp_password@127.0.0.1:7687"),
]


def probar(motor: str, url: str) -> None:
    """Lanza una excepción si el motor todavía no acepta conexiones."""
    if motor == "postgres":
        import psycopg2
        psycopg2.connect(url, connect_timeout=3).close()
    elif motor == "mysql":
        import pymysql
        credenciales, base = url[len("mysql://"):].split("/", 1)
        usuario_clave, servidor = credenciales.rsplit("@", 1)
        usuario, clave = usuario_clave.split(":", 1)
        host, _, puerto = servidor.partition(":")
        pymysql.connect(host=host, port=int(puerto or 3306), user=usuario,
                        password=clave, database=base, connect_timeout=3).close()
    elif motor == "mongo":
        from pymongo import MongoClient
        cliente = MongoClient(url, serverSelectionTimeoutMS=3000)
        cliente.admin.command("ping")
        cliente.close()
    elif motor == "redis":
        import redis
        redis.Redis.from_url(url, socket_connect_timeout=3).ping()
    elif motor == "neo4j":
        from neo4j import GraphDatabase
        from urllib.parse import urlparse
        p = urlparse(url)
        driver = GraphDatabase.driver(f"bolt://{p.hostname}:{p.port or 7687}",
                                      auth=(p.username or "neo4j", p.password or ""))
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
    else:
        raise ValueError(f"Motor desconocido: {motor}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=180, help="Segundos máximos de espera")
    ap.add_argument("--motores", default="", help="Filtrar por motor: postgres,mysql,mongo,redis,neo4j")
    args = ap.parse_args()

    filtro = {m.strip() for m in args.motores.split(",") if m.strip()}
    destinos = [d for d in DESTINOS if not filtro or d[1] in filtro]

    print(f"Esperando {len(destinos)} bases de datos (máximo {args.timeout} s)...")
    limite = time.time() + args.timeout
    pendientes = list(destinos)
    listas: list[str] = []

    while pendientes and time.time() < limite:
        siguen = []
        for nombre, motor, url in pendientes:
            try:
                probar(motor, url)
                listas.append(nombre)
                print(f"  [OK]       {nombre}")
            except Exception:
                siguen.append((nombre, motor, url))
        pendientes = siguen
        if pendientes:
            time.sleep(3)

    print()
    if pendientes:
        print(f"NO respondieron {len(pendientes)} de {len(destinos)}:")
        for nombre, _, url in pendientes:
            print(f"  [FALLO]    {nombre}  ->  {url}")
        print()
        print("Revisa que Docker Desktop esté corriendo y que 'docker compose ps'")
        print("muestre los contenedores como 'running'.")
        return 1

    print(f"Las {len(listas)} bases de datos están listas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
