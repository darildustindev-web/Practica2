"""Tablero de Entrega: ve el estado de la rúbrica y ejecuta la demostración.

Complementa al panel de operación de la ASFI (`/panel`, que muestra el barrido en
vivo). Este tablero responde otra pregunta: **¿cumplimos cada punto de la rúbrica
y cómo lo demuestro?** Muestra los 7 ítems con su estado real, consultado contra
las bases de datos, y permite lanzar cada paso de la demostración con un botón.

Arranque:
    python scripts\\tablero\\servidor.py
    (o bien:  .\\scripts\\windows\\Abrir-Tablero.ps1 )

Luego abrir  http://127.0.0.1:8090

SEGURIDAD
---------
El tablero ejecuta comandos, así que está deliberadamente acotado:

  * Escucha SÓLO en 127.0.0.1. No es accesible desde la red.
  * No existe "ejecutar comando arbitrario": hay una LISTA BLANCA fija de
    acciones (ACCIONES). El navegador manda un identificador, nunca una orden.
  * Ningún argumento viene del navegador: los argv están escritos en este
    archivo. No se usa shell=True en ningún caso.
  * Las acciones que escriben (reiniciar, levantar) exigen que la petición venga
    del propio tablero (comprobación de mismo origen), igual que hace
    asfi-service/dashboard.py.
  * Sólo puede correr una acción a la vez.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts" / "consultas")]

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

ES_WINDOWS = os.name == "nt"
PYTHON = str(ROOT / ".venv" / ("Scripts/python.exe" if ES_WINDOWS else "bin/python"))
if not Path(PYTHON).exists():
    PYTHON = sys.executable


# =====================================================================
# LISTA BLANCA DE ACCIONES  (el navegador sólo manda la clave)
# =====================================================================
def _ps1(nombre: str, *extra: str) -> list[str]:
    ruta = str(ROOT / "scripts" / "windows" / nombre)
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ruta, *extra]


ACCIONES: dict[str, dict] = {
    "verificar_entorno": {
        "titulo": "Verificar entorno",
        "detalle": "Python, dependencias, bloqueo de archivos, Docker, dataset y puertos.",
        "grupo": "preparacion",
        "solo_windows": True,
        "comando": _ps1("Verificar-Entorno.ps1"),
    },
    "reiniciar_demo": {
        "titulo": "Reiniciar todo desde cero",
        "detalle": "Borra bases y datos, vuelve a cifrar, verifica saldos y carga los 14 bancos.",
        "grupo": "preparacion",
        "solo_windows": True,
        "confirmar": "Esto BORRA las 14 bases de datos y las vuelve a cargar. ¿Continuar?",
        "comando": _ps1("Reiniciar-Demo.ps1"),
    },
    "levantar_servicios": {
        "titulo": "Levantar los 16 servicios",
        "detalle": "BCB, los 14 bancos y la ASFI.",
        "grupo": "preparacion",
        "solo_windows": True,
        "comando": _ps1("Levantar-Servicios.ps1"),
    },
    "detener_servicios": {
        "titulo": "Detener servicios",
        "detalle": "Apaga los 16 servicios. No toca las bases de datos.",
        "grupo": "preparacion",
        "solo_windows": True,
        "comando": _ps1("Detener-Servicios.ps1"),
    },
    "verificar_saldos": {
        "titulo": "Verificar saldos contra el CSV",
        "detalle": "Descifra y compara con data/dataset.csv. Detecta datos mal sembrados.",
        "grupo": "demostracion",
        "comando": [PYTHON, str(ROOT / "scripts" / "verificar_saldos.py")],
    },
    "barrido": {
        "titulo": "Ejecutar el barrido paralelo",
        "detalle": "Dispara la conversión de las 14 entidades en paralelo.",
        "grupo": "demostracion",
        "comando": [PYTHON, "-c",
                    "import httpx,json,time;"
                    "t=time.perf_counter();"
                    "r=httpx.post('http://127.0.0.1:8000/api/asfi/ejecutar-conversion',timeout=600);"
                    "d=r.json();"
                    "print(json.dumps({k:v for k,v in d.items() if k!='bancos'},indent=2,ensure_ascii=False));"
                    "[print(f\"  banco {b['banco_id']:>2}: leidas={b['leidas']} confirmadas={b['confirmadas']} errores={b['errores']}\") for b in d.get('bancos',[])];"
                    "print(f'\\nTiempo total medido desde el cliente: {time.perf_counter()-t:.2f} s')"],
    },
    "consultas": {
        "titulo": "Ejecutar las 8 consultas (40 pts)",
        "detalle": "Corre las 8 sobre los 14 bancos y ASFI, y guarda docs/evidencia-consultas.txt.",
        "grupo": "demostracion",
        "comando": [PYTHON, str(ROOT / "scripts" / "consultas" / "ejecutar_consultas.py"),
                    "--salida", str(ROOT / "docs" / "evidencia-consultas.txt")],
    },
    "demo_seguridad": {
        "titulo": "Demostrar las mitigaciones de seguridad",
        "detalle": "Spoofing, MITM y replay: los tres deben ser rechazados.",
        "grupo": "demostracion",
        "comando": [PYTHON, str(ROOT / "scripts" / "demo_seguridad.py")],
    },
    "acelerar_bcb": {
        "titulo": "Acelerar el dólar a 3 segundos",
        "detalle": "Hace visible que el barrido congela una sola cotización.",
        "grupo": "demostracion",
        "comando": [PYTHON, "-c",
                    "import httpx;"
                    "r=httpx.put('http://127.0.0.1:8001/api/bcb/configurar-intervalo',params={'segundos':3},timeout=10);"
                    "print(r.status_code, r.text)"],
    },
    "restaurar_bcb": {
        "titulo": "Restaurar el dólar a 3 minutos",
        "detalle": "Vuelve al intervalo de 180 s que pide el enunciado.",
        "grupo": "demostracion",
        "comando": [PYTHON, "-c",
                    "import httpx;"
                    "r=httpx.put('http://127.0.0.1:8001/api/bcb/configurar-intervalo',params={'segundos':180},timeout=10);"
                    "print(r.status_code, r.text)"],
    },
}


# =====================================================================
# Ejecución de una acción, con salida en vivo
# =====================================================================
class Ejecutor:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proceso: subprocess.Popen | None = None
        self.accion: str | None = None
        self.lineas: deque[str] = deque(maxlen=4000)
        self.inicio: str | None = None
        self.fin: str | None = None
        self.codigo: int | None = None
        self.secuencia = 0

    @property
    def corriendo(self) -> bool:
        return self.proceso is not None and self.proceso.poll() is None

    def _emitir(self, texto: str) -> None:
        self.lineas.append(texto)
        self.secuencia += 1

    def lanzar(self, clave: str) -> None:
        accion = ACCIONES[clave]
        with self.lock:
            if self.corriendo:
                raise HTTPException(409, f"Ya se está ejecutando '{self.accion}'. Esperá a que termine.")
            if accion.get("solo_windows") and not ES_WINDOWS:
                raise HTTPException(400, "Esta acción usa PowerShell y sólo corre en Windows.")
            self.lineas.clear()
            self.accion = clave
            self.inicio = datetime.now(timezone.utc).isoformat()
            self.fin = None
            self.codigo = None
            self._emitir(f"$ {' '.join(accion['comando'][:3])} ...")
            self._emitir("")
            entorno = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            try:
                self.proceso = subprocess.Popen(
                    accion["comando"], cwd=str(ROOT), env=entorno,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1)
            except OSError as exc:
                self._emitir(f"[error] No se pudo iniciar: {exc}")
                self.fin = datetime.now(timezone.utc).isoformat()
                self.codigo = -1
                raise HTTPException(500, f"No se pudo iniciar la acción: {exc}") from exc
            threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self) -> None:
        proceso = self.proceso
        if proceso is None or proceso.stdout is None:
            return
        for linea in proceso.stdout:
            self._emitir(linea.rstrip("\n"))
        proceso.wait()
        self.codigo = proceso.returncode
        self.fin = datetime.now(timezone.utc).isoformat()
        self._emitir("")
        self._emitir(f"[fin] Código de salida: {self.codigo}")

    def detener(self) -> bool:
        with self.lock:
            if not self.corriendo or self.proceso is None:
                return False
            self.proceso.terminate()
            self._emitir("[detenido por el usuario]")
            return True

    def estado(self) -> dict:
        return {
            "accion": self.accion,
            "corriendo": self.corriendo,
            "inicio": self.inicio,
            "fin": self.fin,
            "codigo": self.codigo,
            "secuencia": self.secuencia,
            "lineas": list(self.lineas),
        }


ejecutor = Ejecutor()


# =====================================================================
# Estado real de la rúbrica: se consulta contra las bases de datos
# =====================================================================
def _leer_sistema() -> dict:
    """Lee los 14 bancos y la base central. Nunca lanza: informa lo que pudo."""
    resultado = {"bancos": {}, "asfi": None, "error_asfi": None}
    try:
        from ejecutar_consultas import leer_banco, leer_asfi, BANCOS
    except Exception as exc:
        resultado["error_asfi"] = f"No se pudo importar el runner de consultas: {exc}"
        return resultado

    # En paralelo: si un motor está caído, su espera no bloquea a los demás.
    # En serie, 10 bancos apagados sumaban más de un minuto de timeouts.
    from concurrent.futures import ThreadPoolExecutor

    def _uno(banco):
        try:
            return banco, leer_banco(banco)
        except Exception as exc:
            return banco, {"error": f"{type(exc).__name__}"}

    with ThreadPoolExecutor(max_workers=15) as pool:
        futuro_asfi = pool.submit(leer_asfi)
        for banco, datos in pool.map(_uno, BANCOS):
            resultado["bancos"][banco] = datos
        try:
            resultado["asfi"] = futuro_asfi.result()
        except Exception as exc:
            resultado["error_asfi"] = f"{type(exc).__name__}: {exc}"
    return resultado


def _decimal(valor) -> float:
    try:
        return float(valor)
    except Exception:
        return 0.0


def evaluar_rubrica() -> dict:
    from ejecutar_consultas import BANCOS

    sistema = _leer_sistema()
    bancos = sistema["bancos"]
    asfi = sistema["asfi"] or {"filas": [], "historial": 0}
    filas_asfi = asfi.get("filas", [])

    con_datos = [b for b, d in bancos.items() if not d.get("error") and d.get("total", 0) > 0]
    inalcanzables = [b for b, d in bancos.items() if d.get("error")]
    total_cuentas = sum(d.get("total", 0) for d in bancos.values() if not d.get("error"))
    total_convertidas = sum(d.get("convertidas", 0) for d in bancos.values() if not d.get("error"))

    confirmadas = [f for f in filas_asfi if f.get("estado") == "CONFIRMADA"]
    tasas = {str(f.get("tipo_cambio")) for f in filas_asfi if f.get("tipo_cambio") is not None}

    # Ventana temporal del barrido (prueba del paralelismo)
    ventana = None
    fechas = sorted(str(f["fecha"]) for f in filas_asfi if f.get("fecha"))
    if len(fechas) >= 2:
        try:
            inicio = datetime.fromisoformat(fechas[0])
            final = datetime.fromisoformat(fechas[-1])
            ventana = round((final - inicio).total_seconds(), 3)
        except Exception:
            ventana = None

    # Descuadres aritméticos
    descuadres = 0
    for fila in confirmadas:
        esperado = round(_decimal(fila["saldo_usd"]) * _decimal(fila["tipo_cambio"]), 4)
        if abs(esperado - _decimal(fila["saldo_bs"])) > 0.0001:
            descuadres += 1

    # Consistencia banco <-> ASFI
    por_banco_asfi: dict[int, dict] = {}
    for fila in filas_asfi:
        por_banco_asfi.setdefault(int(fila["banco_id"]), {})[str(fila["cuenta_id"])] = fila
    comparadas = coinciden = 0
    for banco, datos in bancos.items():
        if datos.get("error"):
            continue
        lado_asfi = por_banco_asfi.get(banco, {})
        for fila in datos.get("filas", []):
            central = lado_asfi.get(str(fila["cuenta_id"]))
            if central is None:
                continue
            comparadas += 1
            if (abs(_decimal(fila["saldo_bs"]) - _decimal(central["saldo_bs"])) < 0.0001
                    and str(fila["codigo"]).upper() == str(central["codigo"]).upper()):
                coinciden += 1

    # Códigos de verificación
    import re
    hex8 = re.compile(r"^[0-9A-F]{8}$")
    codigos = [str(f["codigo"]).upper() for f in filas_asfi if f.get("codigo")]
    codigos_malos = sum(1 for c in codigos if not hex8.match(c))

    # Log de auditoría
    ruta_audit = ROOT / "data" / "audit.jsonl"
    eventos = 0
    if ruta_audit.exists():
        try:
            with ruta_audit.open(encoding="utf-8") as fh:
                eventos = sum(1 for linea in fh if linea.strip())
        except OSError:
            eventos = 0

    # Las 8 consultas
    dir_consultas = ROOT / "scripts" / "consultas"
    archivos_consultas = sorted(p.name for p in dir_consultas.glob("*")
                                if p.suffix in {".sql", ".js", ".cypher", ".txt", ".py"}) if dir_consultas.exists() else []
    evidencia = ROOT / "docs" / "evidencia-consultas.txt"

    # Grafo (banco 13)
    grafo = bancos.get(13, {})

    def item(clave, titulo, puntos, estado, resumen, detalles, como):
        return dict(clave=clave, titulo=titulo, puntos=puntos, estado=estado,
                    resumen=resumen, detalles=detalles, como_demostrar=como)

    items = []

    # --- 1. 14 bases pobladas (20) ---
    if len(con_datos) == 14:
        estado, resumen = "ok", f"Las 14 entidades tienen datos ({total_cuentas:,} cuentas)".replace(",", ".")
    elif con_datos:
        estado, resumen = "aviso", f"Sólo {len(con_datos)} de 14 entidades tienen datos"
    else:
        estado, resumen = "falla", "Ninguna base tiene datos cargados"
    items.append(item(
        "bases", "14 bases de datos pobladas con información base", 20, estado, resumen,
        [f"Cuentas cargadas en total: {total_cuentas:,}".replace(",", "."),
         f"Entidades con datos: {len(con_datos)} de 14",
         f"Motores en uso: PostgreSQL, MySQL, SQLite, MongoDB, Redis y Neo4j",
         (f"Sin responder: bancos {', '.join(map(str, inalcanzables))}" if inalcanzables
          else "Todas las bases respondieron")],
        "Botón «Ejecutar las 8 consultas»: la tabla C1 lista los 14 bancos con su motor y algoritmo."))

    # --- 2. Servicio de transferencia por entidad (15) ---
    responden = 14 - len(inalcanzables)
    estado = "ok" if responden == 14 else ("aviso" if responden else "falla")
    items.append(item(
        "transferencia", "Servicio de transferencia de datos por entidad financiera", 15, estado,
        f"{responden} de 14 entidades exponen sus datos cifrados",
        ["Cada banco corre su propio microservicio (puertos 8101 a 8114)",
         "Contrato: GET /api/banco/cuentas/cifradas y POST /api/banco/cuentas/confirmar",
         "El saldo viaja cifrado con el algoritmo propio de cada entidad"],
        "curl.exe -s \"http://127.0.0.1:8101/api/banco/cuentas/cifradas?limit=2\""))

    # --- 3. Recepción y descifrado en la ASFI (15) ---
    if sistema["error_asfi"]:
        estado, resumen = "falla", "No se pudo leer la base central de la ASFI"
    elif confirmadas:
        estado, resumen = "ok", f"{len(confirmadas):,} cuentas descifradas y consolidadas".replace(",", ".")
    else:
        estado, resumen = "aviso", "La base central está vacía: falta ejecutar un barrido"
    total_usd = sum(_decimal(f["saldo_usd"]) for f in confirmadas)
    total_bs = sum(_decimal(f["saldo_bs"]) for f in confirmadas)
    items.append(item(
        "asfi", "Servicio de recepción y descifrado de datos en la ASFI", 15, estado, resumen,
        [f"Saldo original consolidado: USD {total_usd:,.2f}".replace(",", "@").replace(".", ",").replace("@", "."),
         f"Saldo convertido: Bs. {total_bs:,.2f}".replace(",", "@").replace(".", ",").replace("@", "."),
         f"Consistencia banco↔ASFI: {coinciden:,} de {comparadas:,} coinciden".replace(",", "."),
         f"Códigos hexadecimales inválidos: {codigos_malos}"],
        "Botón «Ejecutar las 8 consultas»: las tablas C2, C3 y C4."))

    # --- 4. Log de auditoría (10) ---
    estado = "ok" if eventos > 0 else "aviso"
    items.append(item(
        "auditoria", "Log de auditoría de transacciones y tipo de cambio", 10, estado,
        (f"{eventos:,} eventos registrados".replace(",", ".") if eventos
         else "Todavía no hay eventos: falta ejecutar un barrido"),
        ["Archivo: data/audit.jsonl",
         "Cada línea trae timestamp, tipo de cambio, cuenta, banco y código de verificación",
         "El campo barrido_id permite reconstruir una ejecución completa"],
        "Get-Content data\\audit.jsonl -Tail 3 | python -m json.tool"))

    # --- 5. Las 8 consultas (40) ---
    if len(archivos_consultas) >= 8 and evidencia.exists():
        estado, resumen = "ok", "Las 8 consultas están escritas y con evidencia generada"
    elif len(archivos_consultas) >= 8:
        estado, resumen = "aviso", "Las 8 consultas están escritas; falta generar la evidencia"
    else:
        estado, resumen = "falla", "Faltan archivos de consultas"
    items.append(item(
        "consultas", "8 consultas a la base de datos y preguntas (sin IA)", 40, estado, resumen,
        [f"Archivos en scripts/consultas: {len(archivos_consultas)}",
         "Una versión por motor: PostgreSQL, MySQL, SQLite, MongoDB, Neo4j, Redis y ASFI",
         ("Evidencia: docs/evidencia-consultas.txt" if evidencia.exists()
          else "Evidencia: todavía no generada"),
         "scripts/consultas/README.md explica cada consulta para defenderla sin IA"],
        "Botón «Ejecutar las 8 consultas» y después leer scripts/consultas/README.md."))

    # --- 6. Base de grafos (20) ---
    if grafo.get("error"):
        estado, resumen = "falla", "Neo4j no responde"
    elif grafo.get("total", 0) > 0:
        estado = "ok"
        resumen = f"{grafo['total']:,} cuentas y {grafo.get('clientes', 0):,} clientes en el grafo".replace(",", ".")
    else:
        estado, resumen = "aviso", "Neo4j responde pero no tiene nodos cargados"
    items.append(item(
        "grafo", "Base de datos orientada a grafos (nodos cliente y cuenta)", 20, estado, resumen,
        ["Banco 13 (BDP), cifrado ECC, motor Neo4j",
         "Modelo: (:Cliente)-[:TIENE_CUENTA]->(:Cuenta)",
         f"Clientes: {grafo.get('clientes', 0):,}".replace(",", "."),
         f"Cuentas: {grafo.get('total', 0):,}".replace(",", ".")],
        "Abrir http://127.0.0.1:7474 y correr: MATCH (cl:Cliente)-[:TIENE_CUENTA]->(cu:Cuenta) RETURN cl,cu LIMIT 25"))

    # --- 7. Barrido paralelo (10) ---
    if not filas_asfi:
        estado, resumen = "aviso", "Todavía no se ejecutó un barrido"
    elif len(tasas) == 1:
        estado = "ok"
        resumen = f"Una sola cotización para todo el barrido" + (f" ({ventana} s)" if ventana is not None else "")
    else:
        estado, resumen = "aviso", f"Hay {len(tasas)} cotizaciones distintas (¿varios barridos?)"
    items.append(item(
        "paralelo", "Barrido paralelo (optimización de tiempo)", 10, estado, resumen,
        [f"Cotizaciones distintas en la base: {len(tasas)}",
         (f"Ventana entre la primera y la última conversión: {ventana} s"
          if ventana is not None else "Ventana: sin datos"),
         f"Descuadres saldo_bs ≠ saldo_usd × tasa: {descuadres}",
         "Si el barrido fuera secuencial aparecerían dos o más tasas"],
        "Botón «Acelerar el dólar a 3 segundos», después «Ejecutar el barrido»: la tasa sigue siendo una sola."))

    obtenidos = sum(i["puntos"] for i in items if i["estado"] == "ok")
    parciales = sum(i["puntos"] for i in items if i["estado"] == "aviso")
    return {
        "generado": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "puntos_totales": sum(i["puntos"] for i in items),
        "puntos_ok": obtenidos,
        "puntos_parciales": parciales,
        "total_cuentas": total_cuentas,
        "total_convertidas": total_convertidas,
        "bancos_con_datos": len(con_datos),
        "bancos_sin_responder": inalcanzables,
    }


def evaluar_requisitos() -> list[dict]:
    """Requisitos técnicos del enunciado, con lo que se puede comprobar en vivo."""
    tiene = lambda ruta: (ROOT / ruta).exists()
    return [
        {"texto": "Al menos 3 motores relacionales", "estado": "ok",
         "nota": "PostgreSQL (bancos 1, 4, 6), MySQL (2, 5, 7) y SQLite (3)"},
        {"texto": "Al menos 2 motores no relacionales", "estado": "ok",
         "nota": "MongoDB (8, 9, 11, 12, 14) y Redis (10)"},
        {"texto": "Una base relacional que consolide todo", "estado": "ok",
         "nota": "PostgreSQL asfi_db, tabla asfi_cuentas + vista Cuentas del enunciado"},
        {"texto": "Microservicios en C#, Java o Python", "estado": "ok",
         "nota": "Python con FastAPI: 16 servicios"},
        {"texto": "Algoritmos de cifrado simétrico", "estado": "ok",
         "nota": "César, Atbash, Vigenère, Playfair, Hill, DES, 3DES, Blowfish, Twofish, AES, ChaCha20"},
        {"texto": "Algoritmos de cifrado asimétrico", "estado": "ok",
         "nota": "RSA (banco 11), ElGamal (12) y ECC (13)"},
        {"texto": "Comunicación segura entre nodos", "estado": "ok" if tiene("shared/seguridad.py") else "falla",
         "nota": "Firma HMAC-SHA256 + nonce anti-replay (shared/seguridad.py)"},
        {"texto": "Cotización variable cada 3 minutos, configurable", "estado": "ok",
         "nota": "BCB_UPDATE_INTERVAL=180 y PUT /api/bcb/configurar-intervalo"},
        {"texto": "Precisión de 4 decimales, oscilación ±0.9999", "estado": "ok",
         "nota": "Decimal con quantize(0.0001); rango [5.9601, 7.9599]"},
        {"texto": "Código de verificación de 8 caracteres hexadecimales", "estado": "ok",
         "nota": "secrets.token_hex(4).upper(), validado con regex en el banco"},
        {"texto": "Corre en Windows", "estado": "ok" if tiene("shared/portable.py") else "falla",
         "nota": "shared/portable.py reemplaza fcntl/resource por LockFileEx"},
        {"texto": "No existe frontend de usuario final", "estado": "aviso",
         "nota": "Hay paneles de operación y entrega; el sistema funciona completo por terminal"},
    ]


def evaluar_amenazas() -> list[dict]:
    return [
        {"amenaza": "Intercepción en tránsito (MITM)",
         "mitigacion": "La firma HMAC cubre método, ruta y cuerpo: alterar un byte la invalida"},
        {"amenaza": "Ataques de repetición (Replay)",
         "mitigacion": "Nonce único por petición y ventana temporal de 120 segundos"},
        {"amenaza": "Suplantación entre nodos (Spoofing)",
         "mitigacion": "Secreto compartido: sin él no se puede firmar la petición"},
        {"amenaza": "Manipulación del tipo de cambio",
         "mitigacion": "La ASFI valida contra el BCB la frescura del timestamp y el rango permitido"},
        {"amenaza": "Desincronización de llaves",
         "mitigacion": "Llaves RSA y ECC persistidas en data/keys y creadas antes de lanzar procesos"},
        {"amenaza": "Alteración de la integridad posconversión",
         "mitigacion": "Hash SHA-256 del registro de origen y verificación saldo_bs = saldo_usd × tasa"},
    ]


# =====================================================================
# Aplicación
# =====================================================================
app = FastAPI(title="Tablero de Entrega - Práctica 2", docs_url=None, redoc_url=None)
AQUI = Path(__file__).parent


def mismo_origen(request: Request) -> None:
    origen = request.headers.get("origin")
    if origen and origen.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "La acción debe iniciarse desde el propio tablero")


@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(AQUI / "tablero.html")


@app.get("/api/rubrica")
async def rubrica():
    return await asyncio.to_thread(evaluar_rubrica)


@app.get("/api/requisitos")
def requisitos():
    return {"requisitos": evaluar_requisitos(), "amenazas": evaluar_amenazas()}


@app.get("/api/acciones")
def acciones():
    return {"acciones": [
        {"clave": clave, "titulo": a["titulo"], "detalle": a["detalle"], "grupo": a["grupo"],
         "confirmar": a.get("confirmar"), "disponible": ES_WINDOWS or not a.get("solo_windows")}
        for clave, a in ACCIONES.items()]}


@app.post("/api/acciones/{clave}")
def lanzar(clave: str, request: Request):
    mismo_origen(request)
    if clave not in ACCIONES:
        raise HTTPException(404, "Acción desconocida")
    ejecutor.lanzar(clave)
    return {"estado": "INICIADA", "accion": clave}


@app.post("/api/detener")
def detener(request: Request):
    mismo_origen(request)
    return {"detenido": ejecutor.detener()}


@app.get("/api/salida")
def salida():
    return ejecutor.estado()


@app.get("/api/entorno")
def entorno():
    return {
        "sistema": platform.system(),
        "python": sys.version.split()[0],
        "raiz": str(ROOT),
        "windows": ES_WINDOWS,
        "dataset": (ROOT / "data" / "dataset.csv").exists(),
        "seed": (ROOT / "data" / "seed").exists(),
        "evidencia": (ROOT / "docs" / "evidencia-consultas.txt").exists(),
    }


def main() -> None:
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--puerto", type=int, default=8090)
    args = ap.parse_args()
    print()
    print("=" * 63)
    print(" TABLERO DE ENTREGA - Práctica 2 ASFI/BCB")
    print("=" * 63)
    print(f"  Abrí en el navegador:  http://127.0.0.1:{args.puerto}")
    print("  Para cerrarlo: Ctrl+C en esta ventana")
    print("=" * 63)
    print()
    # host fijo en 127.0.0.1: el tablero ejecuta comandos, no debe salir a la red.
    uvicorn.run(app, host="127.0.0.1", port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
