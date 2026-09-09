"""Ejecuta las 8 consultas oficiales sobre los 14 bancos y la BD central de ASFI.

Uso:
    python scripts/consultas/ejecutar_consultas.py
    python scripts/consultas/ejecutar_consultas.py --salida docs/evidencia-consultas.txt
    python scripts/consultas/ejecutar_consultas.py --bancos 1,2,3,13

Lee la configuración de las variables de entorno (.env) igual que el resto del
proyecto. Los motores que no estén levantados se reportan como NO DISPONIBLE en
lugar de abortar, para que la demostración pueda continuar.

La consulta C3 (consistencia banco <-> ASFI) es la única que no puede escribirse
en SQL puro: compara dos bases distintas, así que se resuelve leyendo ambos lados
y cruzándolos en memoria.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BANCOS = {
    1:  ("Banco Unión S.A.",                    "César",    "postgres", "POSTGRES_UNION"),
    2:  ("Banco Mercantil Santa Cruz S.A.",     "Atbash",   "mysql",    "MYSQL_MERCANTIL"),
    3:  ("Banco Nacional de Bolivia S.A.",      "Vigenère", "sqlite",   "SQLITE_BNB"),
    4:  ("Banco de Crédito de Bolivia S.A.",    "Playfair", "postgres", "POSTGRES_BCP"),
    5:  ("Banco BISA S.A.",                     "Hill",     "mysql",    "MYSQL_BISA"),
    6:  ("Banco Ganadero S.A.",                 "DES",      "postgres", "POSTGRES_GANADERO"),
    7:  ("Banco Económico S.A.",                "3DES",     "mysql",    "MYSQL_ECONOMICO"),
    8:  ("Banco Prodem S.A.",                   "Blowfish", "mongo",    "MONGO_PRODEM"),
    9:  ("Banco Solidario S.A.",                "Twofish",  "mongo",    "MONGO_SOLIDARIO"),
    10: ("Banco Fortaleza S.A.",                "AES",      "redis",    "REDIS_FORTALEZA"),
    11: ("Banco FIE S.A.",                      "RSA",      "mongo",    "MONGO_FIE"),
    12: ("Banco PYME de la Comunidad S.A.",     "ElGamal",  "mongo",    "MONGO_PYME"),
    13: ("Banco de Desarrollo Productivo S.A.M.", "ECC",    "neo4j",    "NEO4J_BDP"),
    14: ("Banco de la Nación Argentina",        "ChaCha20", "mongo",    "MONGO_ARGENTINA"),
}

URLS_POR_DEFECTO = {
    1:  "postgresql://union_user:union_password@127.0.0.1:5433/bank_union",
    2:  "mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil",
    3:  "sqlite:///" + str(ROOT / "data" / "bank_03.sqlite"),
    4:  "postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp",
    5:  "mysql://bisa_user:bisa_password@127.0.0.1:3307/bank_bisa",
    6:  "postgresql://ganadero_user:ganadero_password@127.0.0.1:5436/bank_ganadero",
    7:  "mysql://economico_user:economico_password@127.0.0.1:3308/bank_economico",
    8:  "mongodb://127.0.0.1:27017/bank_prodem",
    9:  "mongodb://127.0.0.1:27017/bank_solidario",
    10: "redis://127.0.0.1:6379/0#bank10",
    11: "mongodb://127.0.0.1:27017/bank_fie",
    12: "mongodb://127.0.0.1:27017/bank_pyme",
    13: "neo4j://neo4j:bdp_password@127.0.0.1:7687",
    14: "mongodb://127.0.0.1:27017/bank_argentina",
}

HEX8 = __import__("re").compile(r"^[0-9A-F]{8}$")


def url_banco(bank: int) -> str:
    return os.getenv(f"BANK_{bank:02d}_DATABASE_URL") or URLS_POR_DEFECTO[bank]


def url_asfi() -> str:
    return os.getenv("ASFI_DATABASE_URL", "sqlite:///" + str(ROOT / "data" / "asfi.sqlite"))


def dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


# =====================================================================
# Lectura de un banco: devuelve la lista de cuentas ya convertidas
# =====================================================================
def leer_banco(bank: int) -> dict:
    """Devuelve {'total', 'convertidas', 'filas': [...], 'clientes'} o lanza excepción."""
    motor = BANCOS[bank][2]
    url = url_banco(bank)
    if motor == "postgres":
        import psycopg2
        con = psycopg2.connect(url, connect_timeout=8)
        cur = con.cursor()
        cur.execute("SELECT count(*), count(codigo_verificacion) FROM cuentas")
        total, conv = cur.fetchone()
        cur.execute("SELECT count(*) FROM clientes")
        clientes = cur.fetchone()[0]
        cur.execute("SELECT nro, saldo_bs, tipo_cambio, codigo_verificacion, convertido_at "
                    "FROM cuentas WHERE codigo_verificacion IS NOT NULL")
        filas = [dict(zip(("cuenta_id", "saldo_bs", "tipo_cambio", "codigo", "fecha"), r)) for r in cur.fetchall()]
        con.close()
    elif motor == "mysql":
        import pymysql
        cred, base = url[len("mysql://"):].split("/", 1)
        userpass, hostport = cred.rsplit("@", 1)
        user, pwd = userpass.split(":", 1)
        host, _, port = hostport.partition(":")
        con = pymysql.connect(host=host, port=int(port or 3306), user=user, password=pwd,
                              database=base, connect_timeout=8)
        cur = con.cursor()
        cur.execute("SELECT count(*), count(codigo_verificacion) FROM cuentas")
        total, conv = cur.fetchone()
        cur.execute("SELECT count(*) FROM clientes")
        clientes = cur.fetchone()[0]
        cur.execute("SELECT nro, saldo_bs, tipo_cambio, codigo_verificacion, convertido_at "
                    "FROM cuentas WHERE codigo_verificacion IS NOT NULL")
        filas = [dict(zip(("cuenta_id", "saldo_bs", "tipo_cambio", "codigo", "fecha"), r)) for r in cur.fetchall()]
        con.close()
    elif motor == "sqlite":
        import sqlite3
        con = sqlite3.connect(url[len("sqlite:///"):])
        total, conv = con.execute("SELECT count(*), count(codigo_verificacion) FROM cuentas").fetchone()
        clientes = con.execute("SELECT count(*) FROM clientes").fetchone()[0]
        filas = [dict(zip(("cuenta_id", "saldo_bs", "tipo_cambio", "codigo", "fecha"), r))
                 for r in con.execute("SELECT nro, saldo_bs, tipo_cambio, codigo_verificacion, convertido_at "
                                      "FROM cuentas WHERE codigo_verificacion IS NOT NULL")]
        con.close()
    elif motor == "mongo":
        from pymongo import MongoClient
        base = url.rsplit("/", 1)[1]
        cli = MongoClient(url, serverSelectionTimeoutMS=8000)
        col = cli[base]["cuentas"]
        total = col.count_documents({})
        conv = col.count_documents({"codigo_verificacion": {"$ne": None}})
        clientes = len(col.distinct("identificacion"))
        filas = [dict(cuenta_id=d["nro"], saldo_bs=d.get("saldo_bs"), tipo_cambio=d.get("tipo_cambio"),
                      codigo=d.get("codigo_verificacion"), fecha=d.get("convertido_at"))
                 for d in col.find({"codigo_verificacion": {"$ne": None}},
                                   {"_id": 0, "nro": 1, "saldo_bs": 1, "tipo_cambio": 1,
                                    "codigo_verificacion": 1, "convertido_at": 1})]
        cli.close()
    elif motor == "redis":
        import redis as redis_lib
        from urllib.parse import urlparse
        p = urlparse(url)
        frag = (p.fragment or "").strip()
        prefijo = f"bank:{frag.removeprefix('bank')}" if frag else f"bank:{bank}"
        r = redis_lib.Redis(host=p.hostname or "127.0.0.1", port=p.port or 6379,
                            db=int((p.path or "/0").lstrip("/") or 0), decode_responses=True,
                            socket_connect_timeout=8)
        refs = r.zrange(f"{prefijo}:index", 0, -1)
        total = len(refs)
        filas, ident = [], set()
        pipe = r.pipeline()
        for ref in refs:
            pipe.hgetall(f"{prefijo}:cuenta:{ref}")
        for h in pipe.execute():
            if not h:
                continue
            ident.add(h.get("identificacion", ""))
            if h.get("codigo_verificacion"):
                filas.append(dict(cuenta_id=h.get("nro"), saldo_bs=h.get("saldo_bs"),
                                  tipo_cambio=h.get("tipo_cambio"), codigo=h.get("codigo_verificacion"),
                                  fecha=h.get("convertido_at")))
        conv = len(filas)
        clientes = len(ident)
    elif motor == "neo4j":
        from neo4j import GraphDatabase
        from urllib.parse import urlparse
        p = urlparse(url)
        drv = GraphDatabase.driver(f"bolt://{p.hostname}:{p.port or 7687}",
                                   auth=(p.username or "neo4j", p.password or ""))
        with drv.session() as s:
            total = s.run("MATCH (cu:Cuenta) RETURN count(cu) AS n").single()["n"]
            clientes = s.run("MATCH (cl:Cliente) RETURN count(cl) AS n").single()["n"]
            filas = [dict(cuenta_id=r["cuenta_id"], saldo_bs=r["saldo_bs"], tipo_cambio=r["tipo_cambio"],
                          codigo=r["codigo"], fecha=r["fecha"])
                     for r in s.run("MATCH (cu:Cuenta) WHERE cu.codigo_verificacion IS NOT NULL "
                                    "RETURN cu.cuentaId AS cuenta_id, cu.saldo_bs AS saldo_bs, "
                                    "cu.tipo_cambio AS tipo_cambio, cu.codigo_verificacion AS codigo, "
                                    "cu.convertido_at AS fecha")]
            conv = len(filas)
        drv.close()
    else:
        raise ValueError(f"Motor desconocido: {motor}")
    return dict(total=total, convertidas=conv, clientes=clientes, filas=filas)


# =====================================================================
# Lectura de la base central de ASFI
# =====================================================================
def leer_asfi() -> dict:
    url = url_asfi()
    if url.startswith(("postgresql://", "postgres://")):
        import psycopg2
        con = psycopg2.connect(url, connect_timeout=8)
        cur = con.cursor()
        cur.execute("SELECT banco_id, cuenta_id, saldo_usd, saldo_bs, tipo_cambio, "
                    "codigo_verificacion, fecha_conversion, estado FROM asfi_cuentas")
        filas = cur.fetchall()
        cur.execute("SELECT count(*) FROM asfi_historial")
        historial = cur.fetchone()[0]
        con.close()
    else:
        import sqlite3
        con = sqlite3.connect(url[len("sqlite:///"):])
        filas = con.execute("SELECT banco_id, cuenta_id, saldo_usd, saldo_bs, tipo_cambio, "
                            "codigo_verificacion, fecha_conversion, estado FROM asfi_cuentas").fetchall()
        historial = con.execute("SELECT count(*) FROM asfi_historial").fetchone()[0]
        con.close()
    campos = ("banco_id", "cuenta_id", "saldo_usd", "saldo_bs", "tipo_cambio",
              "codigo", "fecha", "estado")
    return dict(filas=[dict(zip(campos, f)) for f in filas], historial=historial)


# =====================================================================
# Informe
# =====================================================================
def informe(bancos_pedidos, salida=None):
    out = []
    def p(texto=""):
        print(texto)
        out.append(texto)

    p("=" * 78)
    p("LAS 8 CONSULTAS OFICIALES - Práctica 2 ASFI/BCB")
    p("Generado: " + datetime.now(timezone.utc).isoformat())
    p("=" * 78)

    # ---------- ASFI ----------
    try:
        asfi = leer_asfi()
        asfi_ok = True
    except Exception as exc:
        p(f"\n[!] BD central ASFI NO DISPONIBLE ({type(exc).__name__}: {exc})")
        p("    Levanta asfi-db y ejecuta un barrido antes de correr las consultas.")
        asfi = dict(filas=[], historial=0)
        asfi_ok = False

    asfi_por_banco = {}
    for f in asfi["filas"]:
        asfi_por_banco.setdefault(int(f["banco_id"]), {})[str(f["cuenta_id"])] = f

    # ---------- C1 ----------
    p("\n" + "-" * 78)
    p("C1. INVENTARIO Y AVANCE POR BANCO  (¿están las 14 bases pobladas?)")
    p("-" * 78)
    p(f"{'ID':>3} {'Banco':<38} {'Cifrado':<9} {'Motor':<9} {'Cuentas':>8} {'Conv.':>7} {'%':>6}")
    datos_banco = {}
    total_cuentas = total_conv = 0
    for b in bancos_pedidos:
        nombre, algo, motor, _ = BANCOS[b]
        try:
            d = leer_banco(b)
            datos_banco[b] = d
            pct = 100.0 * d["convertidas"] / d["total"] if d["total"] else 0.0
            total_cuentas += d["total"]; total_conv += d["convertidas"]
            p(f"{b:>3} {nombre[:38]:<38} {algo:<9} {motor:<9} {d['total']:>8} {d['convertidas']:>7} {pct:>5.1f}%")
        except Exception as exc:
            p(f"{b:>3} {nombre[:38]:<38} {algo:<9} {motor:<9} {'NO DISPONIBLE':>22}  ({type(exc).__name__})")
    p(f"{'':>3} {'TOTAL':<38} {'':<9} {'':<9} {total_cuentas:>8} {total_conv:>7}")

    # ---------- C2 ----------
    p("\n" + "-" * 78)
    p("C2. SALDO ORIGINAL EN USD Y CONVERTIDO EN Bs. (BD central de ASFI)")
    p("-" * 78)
    if asfi_ok and asfi["filas"]:
        p(f"{'ID':>3} {'Banco':<38} {'Cuentas':>8} {'Total USD':>18} {'Total Bs.':>20}")
        gran_usd = gran_bs = Decimal(0)
        for b in sorted(asfi_por_banco):
            filas = [f for f in asfi_por_banco[b].values() if f["estado"] == "CONFIRMADA"]
            usd = sum((dec(f["saldo_usd"]) for f in filas), Decimal(0))
            bs = sum((dec(f["saldo_bs"]) for f in filas), Decimal(0))
            gran_usd += usd; gran_bs += bs
            p(f"{b:>3} {BANCOS[b][0][:38]:<38} {len(filas):>8} {usd:>18,.4f} {bs:>20,.4f}")
        p(f"{'':>3} {'TOTAL DEL SISTEMA':<38} {'':>8} {gran_usd:>18,.4f} {gran_bs:>20,.4f}")
    else:
        p("  (sin datos en ASFI)")

    # ---------- C3 ----------
    p("\n" + "-" * 78)
    p("C3. CONSISTENCIA BANCO <-> ASFI  (requisito explícito del enunciado)")
    p("    Compara saldo_bs, tipo_cambio y código de verificación en ambos lados.")
    p("-" * 78)
    p(f"{'ID':>3} {'Banco':<32} {'Comparadas':>11} {'Coinciden':>10} {'Difieren':>9} {'Sólo banco':>11}")
    total_dif = 0
    for b in sorted(datos_banco):
        lado_banco = {str(f["cuenta_id"]): f for f in datos_banco[b]["filas"]}
        lado_asfi = asfi_por_banco.get(b, {})
        coinciden = difieren = solo_banco = 0
        ejemplos = []
        for ref, fb in lado_banco.items():
            fa = lado_asfi.get(ref)
            if fa is None:
                solo_banco += 1
                continue
            if (dec(fb["saldo_bs"]) == dec(fa["saldo_bs"])
                    and dec(fb["tipo_cambio"]) == dec(fa["tipo_cambio"])
                    and str(fb["codigo"]).upper() == str(fa["codigo"]).upper()):
                coinciden += 1
            else:
                difieren += 1
                if len(ejemplos) < 3:
                    ejemplos.append((ref, fb["saldo_bs"], fa["saldo_bs"], fb["codigo"], fa["codigo"]))
        total_dif += difieren
        p(f"{b:>3} {BANCOS[b][0][:32]:<32} {len(lado_banco):>11} {coinciden:>10} {difieren:>9} {solo_banco:>11}")
        for e in ejemplos:
            p(f"      cuenta {e[0]}: banco bs={e[1]} cod={e[3]} | asfi bs={e[2]} cod={e[4]}")
    p(f"  => Diferencias totales: {total_dif}  ({'CONSISTENTE' if total_dif == 0 else 'REVISAR'})")

    # ---------- C4 ----------
    p("\n" + "-" * 78)
    p("C4. CÓDIGOS DE VERIFICACIÓN: 8 hexadecimales, únicos y presentes en ambos lados")
    p("-" * 78)
    p(f"{'ID':>3} {'Banco':<32} {'Con código':>11} {'Formato mal':>12} {'Duplicados':>11}")
    malos = dups = 0
    for b in sorted(datos_banco):
        codigos = [str(f["codigo"]).upper() for f in datos_banco[b]["filas"] if f["codigo"]]
        invalidos = sum(1 for c in codigos if not HEX8.match(c))
        duplicados = len(codigos) - len(set(codigos))
        malos += invalidos; dups += duplicados
        p(f"{b:>3} {BANCOS[b][0][:32]:<32} {len(codigos):>11} {invalidos:>12} {duplicados:>11}")
    codigos_asfi = [str(f["codigo"]).upper() for f in asfi["filas"] if f["codigo"]]
    inv_asfi = sum(1 for c in codigos_asfi if not HEX8.match(c))
    p(f"{'':>3} {'BD central ASFI':<32} {len(codigos_asfi):>11} {inv_asfi:>12} "
      f"{len(codigos_asfi) - len(set(codigos_asfi)):>11}")
    p(f"  => Formato inválido total: {malos + inv_asfi}   Duplicados: {dups}")

    # ---------- C5 ----------
    p("\n" + "-" * 78)
    p("C5. AUDITORÍA DEL TIPO DE CAMBIO Y PRUEBA DEL BARRIDO PARALELO")
    p("    Una sola cotización para todos los bancos = nadie se benefició ni perjudicó.")
    p("-" * 78)
    tasas = {}
    for f in asfi["filas"]:
        tasas.setdefault(str(dec(f["tipo_cambio"])), []).append(f)
    for tasa, filas in sorted(tasas.items(), key=lambda x: -len(x[1])):
        fechas = sorted(str(f["fecha"]) for f in filas if f["fecha"])
        bancos = sorted({int(f["banco_id"]) for f in filas})
        p(f"  Tasa {tasa}  ->  {len(filas)} cuentas, bancos {bancos}")
        if fechas:
            p(f"      primera: {fechas[0]}")
            p(f"      última : {fechas[-1]}")
            try:
                d0 = datetime.fromisoformat(fechas[0]); d1 = datetime.fromisoformat(fechas[-1])
                p(f"      ventana: {(d1 - d0).total_seconds():.3f} segundos")
            except Exception:
                pass
    p(f"  => Cotizaciones distintas en la base: {len(tasas)} "
      f"({'CORRECTO: una sola' if len(tasas) == 1 else 'revisar: hubo más de un barrido o recotización'})")

    # ---------- C6 ----------
    p("\n" + "-" * 78)
    p("C6. CUENTAS NO PROCESADAS Y SU MOTIVO")
    p("-" * 78)
    pendientes = [f for f in asfi["filas"] if f["estado"] != "CONFIRMADA"]
    p(f"  Cuentas no confirmadas en ASFI: {len(pendientes)}")
    for f in pendientes[:10]:
        p(f"      banco {f['banco_id']} cuenta {f['cuenta_id']}: estado={f['estado']}")
    audit = ROOT / os.getenv("ASFI_AUDIT_FILE", "data/audit.jsonl")
    if audit.exists():
        motivos = {}
        eventos = 0
        with audit.open(encoding="utf-8") as fh:
            for linea in fh:
                try:
                    r = json.loads(linea)
                except Exception:
                    continue
                eventos += 1
                if r.get("detail"):
                    motivos[r["detail"][:70]] = motivos.get(r["detail"][:70], 0) + 1
        p(f"  Log de auditoría {audit.name}: {eventos} eventos registrados")
        for motivo, veces in sorted(motivos.items(), key=lambda x: -x[1])[:8]:
            p(f"      {veces:>5}x  {motivo}")
    else:
        p(f"  (no se encontró el log de auditoría en {audit})")

    # ---------- C7 ----------
    p("\n" + "-" * 78)
    p("C7. RELACIÓN CLIENTE -> CUENTA (grafo Neo4j y su equivalente en el resto)")
    p("-" * 78)
    for b in sorted(datos_banco):
        d = datos_banco[b]
        motor = BANCOS[b][2]
        marca = "  <-- GRAFO (:Cliente)-[:TIENE_CUENTA]->(:Cuenta)" if motor == "neo4j" else ""
        cuentas_por_cliente = (d["total"] / d["clientes"]) if d["clientes"] else 0
        p(f"{b:>3} {BANCOS[b][0][:34]:<34} clientes={d['clientes']:>6} cuentas={d['total']:>6} "
          f"prom={cuentas_por_cliente:.2f}{marca}")

    # ---------- C8 ----------
    p("\n" + "-" * 78)
    p("C8. RANKING DEL SISTEMA E INTEGRIDAD DE LOS IMPORTES")
    p("-" * 78)
    confirmadas = [f for f in asfi["filas"] if f["estado"] == "CONFIRMADA"]
    descuadres = [f for f in confirmadas
                  if (dec(f["saldo_usd"]) * dec(f["tipo_cambio"])).quantize(Decimal("0.0001")) != dec(f["saldo_bs"])]
    p(f"  Cuentas confirmadas evaluadas: {len(confirmadas)}")
    p(f"  Descuadres saldo_bs != saldo_usd * tipo_cambio: {len(descuadres)} "
      f"({'CORRECTO' if not descuadres else 'REVISAR'})")
    for f in descuadres[:5]:
        p(f"      banco {f['banco_id']} cuenta {f['cuenta_id']}: "
          f"{f['saldo_usd']} x {f['tipo_cambio']} != {f['saldo_bs']}")
    p("  Top 10 cuentas por saldo en USD:")
    for f in sorted(confirmadas, key=lambda x: -dec(x["saldo_usd"]))[:10]:
        p(f"      banco {f['banco_id']:>2} cuenta {str(f['cuenta_id']):>10} "
          f"USD {dec(f['saldo_usd']):>14,.4f}  Bs {dec(f['saldo_bs']):>16,.4f}  cod {f['codigo']}")
    tramos = {"a) < 1.000": 0, "b) 1.000-10.000": 0, "c) 10.000-100.000": 0,
              "d) 100.000-500.000": 0, "e) >= 500.000": 0}
    for f in confirmadas:
        v = dec(f["saldo_usd"])
        clave = ("a) < 1.000" if v < 1000 else "b) 1.000-10.000" if v < 10000
                 else "c) 10.000-100.000" if v < 100000
                 else "d) 100.000-500.000" if v < 500000 else "e) >= 500.000")
        tramos[clave] += 1
    p("  Distribución por tramo de saldo USD:")
    for k in sorted(tramos):
        p(f"      {k:<22} {tramos[k]:>8} cuentas")
    p(f"  Versiones archivadas en asfi_historial (reconversiones): {asfi['historial']}")

    p("\n" + "=" * 78)
    p("FIN DEL INFORME")
    p("=" * 78)

    if salida:
        Path(salida).parent.mkdir(parents=True, exist_ok=True)
        Path(salida).write_text("\n".join(out), encoding="utf-8")
        print(f"\n[Evidencia guardada en {salida}]")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bancos", default="1,2,3,4,5,6,7,8,9,10,11,12,13,14",
                    help="Lista de bancos a consultar, separados por coma")
    ap.add_argument("--salida", help="Archivo donde guardar la evidencia")
    args = ap.parse_args()
    bancos = [int(x) for x in args.bancos.split(",") if x.strip()]
    if any(b not in BANCOS for b in bancos):
        ap.error("Los bancos deben estar entre 1 y 14")
    informe(bancos, args.salida)


if __name__ == "__main__":
    main()
