# Entrega final — Práctica 2: Plataforma Distribuida de Conversión Monetaria (ASFI / BCB)

**Guía completa para Windows.** Este documento es lo único que necesitás leer para
entender qué pide el enunciado, qué construimos, cómo se corre y cómo se defiende.

Todos los comandos son de **PowerShell en Windows**.
Última revisión: 2026-09-09, verificando el código contra motores de base de datos
reales con el dataset del docente.

---

## Índice

1. [Qué es este sistema, en dos minutos](#1-qué-es-este-sistema-en-dos-minutos)
2. [El tablero: por dónde empezar](#2-el-tablero-por-dónde-empezar)
3. [Lo que hay que arreglar antes de mostrar nada](#3-lo-que-hay-que-arreglar-antes-de-mostrar-nada)
4. [Instalación desde cero](#4-instalación-desde-cero)
5. [Los cinco scripts de Windows](#5-los-cinco-scripts-de-windows)
6. [El comando para reiniciar todo](#6-el-comando-para-reiniciar-todo)
7. [Guion de demostración, paso a paso](#7-guion-de-demostración-paso-a-paso)
8. [La rúbrica, punto por punto](#8-la-rúbrica-punto-por-punto)
9. [Los requerimientos del enunciado](#9-los-requerimientos-del-enunciado)
10. [Mapa de archivos: qué hace cada cosa](#10-mapa-de-archivos-qué-hace-cada-cosa)
11. [Preguntas del docente y cómo responderlas](#11-preguntas-del-docente-y-cómo-responderlas)
12. [Si algo falla en vivo](#12-si-algo-falla-en-vivo)
13. [Qué se probó de verdad](#13-qué-se-probó-de-verdad)

---

## 1. Qué es este sistema, en dos minutos

El Banco Central de Bolivia necesita convertir a bolivianos todas las cuentas en
dólares de 14 bancos. El problema: **cada banco guarda los saldos cifrados con un
algoritmo distinto** (el Banco Unión con César, el FIE con RSA, el BDP con ECC…),
y además cada uno usa un motor de base de datos diferente.

El sistema tiene tres capas:

```
                 ┌────────────────────────────────────┐
                 │  Servicio BCB  (puerto 8001)       │
                 │  Cotización del dólar, cambia      │
                 │  cada 3 min, ±0.9999, 4 decimales  │
                 └──────────────┬─────────────────────┘
                                │ 1. pide la cotización UNA vez
                                ▼
                 ┌────────────────────────────────────┐
                 │  Servicio central ASFI (8000)      │
                 │  · guarda las llaves de los 14     │
                 │  · descifra, convierte, audita     │
                 │  · genera el código hex de 8       │
                 │  · BD consolidada (PostgreSQL)     │
                 └──────────────┬─────────────────────┘
                    2. sale a los 14 bancos EN PARALELO
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  Banco 1 (8101)          Banco 8 (8108)          Banco 13 (8113)
  César · PostgreSQL      Blowfish · MongoDB      ECC · Neo4j (grafo)
        └───────── … los 14, uno por puerto … ──────────┘
                    3. cada banco confirma con el código
```

**La idea central que hay que entender para la defensa:** el saldo en dólares
viaja **cifrado** desde el banco. Sólo la ASFI, que administra las llaves, puede
descifrarlo. Por eso en la base de un banco no se puede sumar el saldo USD, y en
la base de la ASFI sí.

**Por qué el paralelismo importa:** si la ASFI fuera de banco en banco, el dólar
cambiaría a mitad del recorrido y unos clientes se convertirían a 6,96 y otros a
7,10. Por eso captura una sola cotización y sale a los 14 al mismo tiempo.

---

## 2. El tablero: por dónde empezar

```powershell
.\scripts\windows\Abrir-Tablero.ps1
```

Abre **http://127.0.0.1:8090** con:

- **Pestaña Rúbrica** — los 7 ítems con su estado *real*, consultado contra las
  bases de datos en ese momento: cuántas entidades tienen datos, cuántas cuentas
  se convirtieron, si hay descuadres, si la tasa fue una sola. Cada tarjeta dice
  además **cómo demostrar ese punto**.
- **Pestaña Ejecutar** — botones para cada paso: verificar entorno, reiniciar
  todo, levantar los servicios, correr el barrido, las 8 consultas, la demo de
  seguridad, acelerar el dólar. La salida aparece abajo en vivo.
- **Pestaña Requisitos** — los requerimientos técnicos con cómo se cumple cada uno.
- **Pestaña Seguridad** — las seis amenazas del enunciado y su mitigación.

> **Sobre la seguridad del tablero:** ejecuta comandos, así que está acotado a
> propósito. Escucha **sólo en 127.0.0.1**, no hay "ejecutar comando arbitrario"
> (existe una lista blanca fija: el navegador manda un identificador, nunca una
> orden), ningún argumento viene del navegador, y las acciones exigen que la
> petición venga del propio tablero. Probado: una clave inventada devuelve 404 y
> una petición de otro origen devuelve 403.

**No confundir con el otro panel.** El proyecto tiene dos, y hacen cosas
distintas:

| | Para qué sirve |
|---|---|
| `http://127.0.0.1:8090` — **Tablero de Entrega** | Ver si cumplimos la rúbrica y lanzar la demostración |
| `http://127.0.0.1:8000/panel` — **Panel de operación** | Ver el barrido en vivo mientras corre (progreso por banco) |

---

## 3. Lo que hay que arreglar antes de mostrar nada

### 3.1 El proyecto no arrancaba en Windows — ya corregido

`asfi-service\main.py`, `scripts\seeder.py` y `scripts\load_common.py` usaban
`fcntl` y `resource`, que **sólo existen en Linux**. En Windows el servicio ASFI
ni siquiera llegaba a importarse.

Se agregó **`shared\portable.py`**, que hace lo mismo con `LockFileEx` de
kernel32 en Windows y con `fcntl` en Linux, sin instalar nada extra. Comprobalo:

```powershell
.venv\Scripts\python.exe shared\portable.py
# Debe decir: Bloqueo de archivos OK (Windows)
```

### 3.2 Los saldos cargados están inflados — se arregla con un comando

Cuenta `Nro = 9` del Banco Unión:

| Origen | Valor |
|---|---|
| `data\dataset.csv` (dataset del docente) | `301716.8517` |
| Lo que quedó cargado en la base | `3017168517.0000` |

Se verificó sobre 300 cuentas del Banco 1: **283 tienen el saldo mal**. Al número
se le quitó el punto decimal, así que el error es ×10, ×1.000 o ×10.000 según
cuántos decimales tuviera el saldo.

**El código actual ya está corregido**: el seeder de hoy, sobre el mismo CSV,
produce 300/300 saldos correctos. Lo que pasó es que los archivos de
`data\seed-docente1\` se generaron con una versión anterior y nunca se
regeneraron. Si no lo arreglás, el docente va a ver cuentas de tres mil millones
de dólares en un banco boliviano.

**Solución, un solo comando:**

```powershell
.\scripts\windows\Reiniciar-Demo.ps1
```

---

## 4. Instalación desde cero

**Requisitos previos:** Docker Desktop para Windows (abierto, con el motor
corriendo) y Python 3.11 o superior con "Add to PATH" marcado.

```powershell
# 1. Ubicarse en el proyecto
cd C:\Users\rober\Documents\GitHub\Practica2

# 2. Entorno virtual e instalación de dependencias
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configuración
Copy-Item .env.example .env

# 4. Comprobar que la máquina está lista
.\scripts\windows\Verificar-Entorno.ps1

# 5. Construir todo (Docker + sembrado + verificación + carga)
.\scripts\windows\Reiniciar-Demo.ps1

# 6. Levantar los 16 servicios
.\scripts\windows\Levantar-Servicios.ps1

# 7. Abrir el tablero
.\scripts\windows\Abrir-Tablero.ps1
```

### Si PowerShell bloquea los scripts

Windows por defecto no ejecuta scripts. Una sola vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

O sin cambiar nada del sistema, ejecutá cada script así:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Reiniciar-Demo.ps1
```

---

## 5. Los cinco scripts de Windows

Todos en `scripts\windows\`. Ejecutalos **desde la carpeta del proyecto**.

| Script | Qué hace | Cuándo |
|---|---|---|
| `Verificar-Entorno.ps1` | Revisa Python, dependencias, bloqueo de archivos, Docker, dataset y puertos | Antes de la defensa |
| `Reiniciar-Demo.ps1` | Deja todo como recién instalado y listo para volver a demostrar | Antes de empezar y después de cada demo |
| `Levantar-Servicios.ps1` | Arranca el BCB, los 14 bancos y la ASFI | Después de reiniciar |
| `Detener-Servicios.ps1` | Los apaga, sin tocar los datos | Al terminar |
| `Abrir-Tablero.ps1` | Abre el tablero en el navegador | Para conducir la demostración |

**Opciones útiles:**

```powershell
# Ver los logs de cada servicio en su propia ventana
.\scripts\windows\Levantar-Servicios.ps1 -Ventanas

# Levantar sólo algunos bancos (ensayo rápido)
.\scripts\windows\Levantar-Servicios.ps1 -Bancos 1,2,3,10

# Levantar con la firma HMAC entre nodos activada
.\scripts\windows\Levantar-Servicios.ps1 -ConSeguridad

# Apagar también los contenedores, conservando los datos
.\scripts\windows\Detener-Servicios.ps1 -ConDocker
```

---

## 6. El comando para reiniciar todo

Después de una demostración, para poder repetirla desde cero:

```powershell
.\scripts\windows\Reiniciar-Demo.ps1
```

Tarda unos 3–5 minutos y hace ocho pasos:

| Paso | Qué hace |
|---|---|
| 1 | Detiene los 16 servicios Python que quedaron corriendo |
| 2 | `docker compose down -v` — borra los contenedores **y sus volúmenes**: las 14 bases quedan vacías |
| 3 | Limpia `data\seed`, `data\audit.jsonl`, las bases SQLite y la evidencia anterior |
| 4 | `docker compose up -d` — vuelve a levantar los 10 contenedores |
| 5 | Espera a que los 10 motores **acepten conexiones de verdad** (Docker dice "running" mucho antes de que MySQL esté listo) |
| 6 | Vuelve a cifrar el dataset con el seeder |
| 7 | **Verifica que los saldos descifrados coincidan con el CSV.** Si no coinciden, se detiene y no carga nada |
| 8 | Carga los 14 bancos y crea las tablas `Bancos` / `Cuentas` del enunciado |

El paso 7 es la red de seguridad: es exactamente lo que habría evitado el problema
de los saldos inflados.

**Variantes:**

```powershell
# Sólo apagar y limpiar, sin reconstruir
.\scripts\windows\Reiniciar-Demo.ps1 -SoloLimpiar

# Ensayo rápido: sólo bancos 1, 2, 3 y 10 (un motor de cada tipo)
.\scripts\windows\Reiniciar-Demo.ps1 -Rapido

# Partir absolutamente de cero, regenerando también las llaves RSA y ECC
.\scripts\windows\Reiniciar-Demo.ps1 -BorrarLlaves
```

---

## 7. Guion de demostración, paso a paso

> En PowerShell, `curl` es un alias de `Invoke-WebRequest` y **no** acepta los
> parámetros de curl. Usá siempre **`curl.exe`**, que es el curl real de Windows.

Podés hacer todo desde el tablero (pestaña **Ejecutar**) o con estos comandos.

### Paso 1 — Las 14 bases están pobladas · 20 pts · 2 min

**Tablero:** botón «Ejecutar las 8 consultas». **Terminal:**

```powershell
.venv\Scripts\python.exe scripts\consultas\ejecutar_consultas.py
```

La tabla **C1** lista los 14 bancos con su algoritmo, su motor y sus cuentas.

> **Qué decir:** *"seis motores distintos —PostgreSQL, MySQL, SQLite, MongoDB,
> Redis y Neo4j—, cada banco con su propio algoritmo de cifrado."*

### Paso 2 — Los datos están cifrados · 2 min

```powershell
curl.exe -s "http://127.0.0.1:8101/api/banco/cuentas/cifradas?limit=2" | .venv\Scripts\python.exe -m json.tool
curl.exe -s "http://127.0.0.1:8108/api/banco/cuentas/cifradas?limit=2" | .venv\Scripts\python.exe -m json.tool
```

El primero es César (Banco Unión), el segundo Blowfish (Prodem). Se ve que el
cifrado es distinto.

> **Qué decir:** *"ni siquiera un banco puede leer los datos de otro; sólo la
> ASFI, que administra las llaves, descifra."*

### Paso 3 — El barrido paralelo en vivo · 15+15+10 pts · 3 min

**Tablero:** botón «Ejecutar el barrido paralelo». **Terminal:**

```powershell
Measure-Command { curl.exe -X POST http://127.0.0.1:8000/api/asfi/ejecutar-conversion }
```

> **Qué decir:** *"la ASFI pide la cotización al BCB una sola vez, la congela y
> sale a los 14 bancos en paralelo: descifra con la llave de cada uno, convierte,
> genera el código de verificación de 8 hexadecimales y se lo confirma al banco."*

Mientras corre, se puede mostrar el progreso en `http://127.0.0.1:8000/panel`.

### Paso 4 — Probar que fue realmente paralelo · 10 pts · 2 min

Antes del barrido, acelerá la fluctuación para que sea dramático:

```powershell
curl.exe -X PUT "http://127.0.0.1:8001/api/bcb/configurar-intervalo?segundos=3"
```

Después del barrido, la consulta **C5** muestra:

```
Tasa 6.9600  ->  N cuentas, bancos [1..14]
    ventana: 0.750 segundos
=> Cotizaciones distintas en la base: 1 (CORRECTO: una sola)
```

> **Qué decir:** *"el dólar estaba cambiando cada 3 segundos y el barrido igual
> aplicó una sola cotización a los 14 bancos. Si hubiera sido secuencial, acá
> aparecerían dos o más tasas: unos clientes convertidos a 6,96 y otros a 7,10."*

Acordate de restaurarlo después: botón «Restaurar el dólar a 3 minutos».

### Paso 5 — Consistencia banco ↔ ASFI · 2 min

La consulta **C3** compara cuenta por cuenta los dos lados y debe decir
`Diferencias totales: 0 (CONSISTENTE)`.

> **Qué decir:** *"el enunciado pide validar que el saldo del banco coincida con
> el de la ASFI. Se comparan las N cuentas de los dos lados: saldo en bolivianos,
> tasa aplicada y código de verificación. Cero diferencias."*

### Paso 6 — La base de grafos · 20 pts · 3 min

Abrir `http://127.0.0.1:7474` (usuario `neo4j`, contraseña `bdp_password`):

```cypher
MATCH (cl:Cliente)-[:TIENE_CUENTA]->(cu:Cuenta) RETURN cl, cu LIMIT 25;
```

Se ve el grafo dibujado. Después, la consulta que aprovecha el modelo:

```cypher
MATCH (cl:Cliente)-[:TIENE_CUENTA]->(cu:Cuenta)
WITH cl, count(cu) AS n, sum(toFloat(coalesce(cu.saldo_bs,'0'))) AS total
WHERE n > 1
RETURN cl.clienteId, n, round(total,4) ORDER BY n DESC LIMIT 10;
```

> **Qué decir:** *"dos tipos de nodo, Cliente y Cuenta, unidos por TIENE_CUENTA.
> Ir de un cliente a sus cuentas no cuesta una búsqueda por índice como el JOIN
> relacional: se recorre la arista."*

### Paso 7 — El log de auditoría · 10 pts · 2 min

```powershell
Get-Content data\audit.jsonl -Tail 3 | .venv\Scripts\python.exe -m json.tool
```

Cada línea trae `timestamp`, `tipo_cambio`, `cuenta_id`, `banco_id`,
`codigo_verificacion`, `estado` y `barrido_id`.

> **Qué decir:** *"cada transacción queda registrada con la tasa que se le aplicó
> y el momento exacto; el barrido_id permite reconstruir una ejecución completa."*

### Paso 8 — Las mitigaciones de seguridad · 3 min

**Tablero:** botón «Demostrar las mitigaciones». **Terminal:**

```powershell
.venv\Scripts\python.exe scripts\demo_seguridad.py
```

Cuatro escenarios: petición legítima aceptada; suplantación, manipulación en
tránsito y repetición, las tres rechazadas con HTTP 401.

### Paso 9 — Cierre: las 8 consultas · 40 pts · 5 min

```powershell
.venv\Scripts\python.exe scripts\consultas\ejecutar_consultas.py --salida docs\evidencia-consultas.txt
```

Y abrí `scripts\consultas\README.md`, que explica cada consulta con la pregunta
que responde. **Ese README es lo que hay que estudiar para defender "sin IA".**

### Paso 10 — Reiniciar para la próxima vuelta

```powershell
.\scripts\windows\Reiniciar-Demo.ps1
```

---

## 8. La rúbrica, punto por punto

| # | Ítem | Puntos | Estado | Dónde se demuestra |
|---|---|---|---|---|
| 1 | 14 bases de datos pobladas con información base | 20 | ⚠️ Estructura lista, **datos a regenerar** | Consulta C1 · paso 1 |
| 2 | Servicio de transferencia de datos por entidad | 15 | ✅ | Paso 2 |
| 3 | Servicio de recepción y descifrado en la ASFI | 15 | ✅ | Consultas C2/C3/C4 · paso 3 |
| 4 | Log de auditoría de transacciones y tipo de cambio | 10 | ✅ | Paso 7 |
| 5 | 8 consultas a la base de datos y preguntas (sin IA) | 40 | ✅ **agregado en esta revisión** | Paso 9 |
| 6 | Base de datos orientada a grafos (cliente y cuenta) | 20 | ✅ | Paso 6 |
| 7 | Barrido paralelo (optimización de tiempo) | 10 | ✅ | Paso 4 |

El ítem 1 queda en ⚠️ hasta que corras `Reiniciar-Demo.ps1`; el tablero lo pone
en verde solo cuando las 14 entidades tienen datos correctos.

### Las 8 consultas, en una línea cada una

Están en `scripts\consultas\`, una versión por motor, y el README explica cada una.

| | Pregunta que responde | Qué prueba |
|---|---|---|
| **C1** | ¿Cuántos clientes y cuentas hay, y cuántas se convirtieron? | Las 14 bases pobladas |
| **C2** | ¿Cuánto suma en USD y en Bs cada entidad? | El descifrado y la conversión |
| **C3** | ¿El banco y la ASFI guardan lo mismo? | Consistencia (requisito explícito) |
| **C4** | ¿Los códigos son 8 hexadecimales, únicos y están en ambos lados? | Requisito explícito |
| **C5** | ¿Qué cotización se aplicó y se usó una sola? | Auditoría + paralelismo |
| **C6** | ¿Qué cuentas quedaron sin procesar y por qué? | Trazabilidad |
| **C7** | ¿Qué clientes tienen más de una cuenta? | El grafo Neo4j |
| **C8** | ¿La conversión es aritméticamente exacta? | Integridad posconversión |

---

## 9. Los requerimientos del enunciado

### 9.1 Objetivo de la práctica

| Requisito | Estado | Dónde está |
|---|---|---|
| Poblar 14 BD bancarias, cada una con su algoritmo | ✅ | `scripts\seeder.py`, `scripts\load_all.py` |
| Un servicio API por entidad que exponga datos cifrados | ✅ | `banks-services\` (puertos 8101–8114) |
| Gestionar las llaves criptográficas de la ASFI | ✅ | `asfi-service\crypto\key_manager.py`, llaves en `data\keys\` |
| Consultar el tipo de cambio del BCB dinámicamente | ✅ | `bcb-service\main.py` |
| Cotización variable cada 3 minutos, configurable | ✅ | `BCB_UPDATE_INTERVAL=180` y `PUT /api/bcb/configurar-intervalo` |
| Precisión de 4 decimales | ✅ | `shared\money.py` (`Decimal`, `quantize(0.0001)`) |
| Oscilación de ±0.9999 sobre la tasa base | ✅ | rango [5.9601, 7.9599] sobre base 6.9600 |
| Log de auditoría: timestamp, tasa, CuentaId, BancoId | ✅ | `data\audit.jsonl` |
| Registrar saldo original USD y convertido Bs en la ASFI | ✅ | tabla `asfi_cuentas` |
| Código de verificación de 8 caracteres hexadecimales | ✅ | `secrets.token_hex(4).upper()`, validado con regex en el banco |
| Validar consistencia banco ↔ ASFI | ✅ | Consulta C3 |

### 9.2 Requerimientos técnicos

| Requisito | Estado | Detalle |
|---|---|---|
| Mínimo 3 motores relacionales | ✅ | PostgreSQL (1, 4, 6), MySQL (2, 5, 7), SQLite (3) |
| Mínimo 2 motores no relacionales | ✅ | MongoDB (8, 9, 11, 12, 14), Redis (10) |
| Una BD relacional que consolide todo | ✅ | PostgreSQL `asfi_db` |
| Microservicios en C#, Java o Python | ✅ | Python + FastAPI, 16 servicios |
| Cifrado simétrico | ✅ | César, Atbash, Vigenère, Playfair, Hill, DES, 3DES, Blowfish, Twofish, AES, ChaCha20 |
| Cifrado asimétrico | ✅ | RSA (11), ElGamal (12), ECC (13) |
| Comunicación segura entre nodos | ✅ | `shared\seguridad.py` — HMAC-SHA256 + nonce |
| No existe frontend | ⚠️ | Ver nota abajo |

**Sobre el "no existe frontend":** el enunciado quiere decir que no hace falta
construir una interfaz de usuario final. Lo que tiene el proyecto son dos paneles
de operación y entrega. Si lo cuestionan: *"no es un frontend de usuario final,
son consolas de monitoreo del proceso; el sistema funciona completo por
terminal"* — y es cierto, todo el guion de la sección 7 se puede hacer sin ellos.

### 9.3 Consideraciones de seguridad

| Amenaza | Mitigación | Verificado |
|---|---|---|
| Intercepción en tránsito (MITM) | La firma HMAC cubre método, ruta y cuerpo: alterar un byte la invalida | ✅ escenario 3 |
| Ataques de repetición (Replay) | Nonce único por petición + ventana temporal de 120 s | ✅ escenario 4 |
| Suplantación entre nodos (Spoofing) | Secreto compartido: sin él no se puede firmar | ✅ escenario 2 |
| Manipulación del tipo de cambio | La ASFI valida contra el BCB la frescura del timestamp y el rango permitido | ✅ `get_exchange_rate` |
| Desincronización de llaves | Llaves RSA y ECC persistidas en `data\keys\` y creadas antes de lanzar procesos | ✅ `key_manager.py` |
| Alteración de integridad posconversión | Hash SHA-256 del registro de origen + verificación `saldo_bs = saldo_usd × tasa` | ✅ Consulta C8 |

> **Limitación que conviene decir vos mismo antes de que la pregunten:** la firma
> HMAC autentica e integra los mensajes, pero **no cifra el canal**. Para
> confidencialidad en tránsito habría que poner HTTPS/TLS delante, que se
> configura fuera de la aplicación. Decirlo demuestra que entendés la diferencia
> entre integridad y confidencialidad.

### 9.4 Entregables esperados

| Entregable | Archivo |
|---|---|
| Script de poblamiento de datos | `scripts\seeder.py` + `scripts\load_all.py` |
| 5 scripts de creación de BD | `scripts\creacion\01_postgresql.sql` … `05_neo4j.cypher` (+ `06_redis.txt`) |
| Código de encriptación | `asfi-service\crypto\ciphers.py` — los 14 algoritmos |
| Código de fluctuación del dólar | `bcb-service\main.py` |
| Código de transporte hacia la ASFI | `asfi-service\main.py` |
| Script de creación de la BD ASFI | `scripts\creacion\asfi_postgresql.sql` + `asfi_vistas_enunciado.sql` |

**Sobre el esquema de la ASFI:** el enunciado define literalmente
`Bancos(BancoId, Nombre, AlgoritmoEncriptacion)` y `Cuentas(CuentaId, BancoId,
SaldoUSD, SaldoBs, FechaConversion, CodigoVerificacion)`. La tabla física del
servicio se llama `asfi_cuentas` porque además guarda el estado y el payload de
auditoría. Para que el docente encuentre exactamente lo que pidió,
`asfi_vistas_enunciado.sql` crea la tabla real `Bancos` con las 14 entidades y la
vista `Cuentas` con esos nombres. Los dos esquemas conviven sin duplicar datos.

---

## 10. Mapa de archivos: qué hace cada cosa

```
Practica2\
├─ docs\
│  └─ ENTREGA_FINAL.md          ← este documento
├─ scripts\
│  ├─ windows\                  ← los 5 scripts de PowerShell
│  │  ├─ Verificar-Entorno.ps1
│  │  ├─ Reiniciar-Demo.ps1     ← reinicia TODO desde cero
│  │  ├─ Levantar-Servicios.ps1
│  │  ├─ Detener-Servicios.ps1
│  │  └─ Abrir-Tablero.ps1
│  ├─ tablero\                  ← el tablero de entrega
│  │  ├─ servidor.py            ← API + lista blanca de acciones
│  │  └─ tablero.html           ← la interfaz
│  ├─ consultas\                ← LAS 8 CONSULTAS (40 pts)
│  │  ├─ README.md              ← qué responde cada una (estudiar esto)
│  │  ├─ 01_postgresql.sql … 07_asfi.sql
│  │  └─ ejecutar_consultas.py  ← las corre todas y arma la evidencia
│  ├─ creacion\                 ← los 5 scripts de creación de BD
│  ├─ seeder.py                 ← cifra el dataset del docente
│  ├─ load_all.py               ← carga los 14 bancos en paralelo
│  ├─ verificar_saldos.py       ← compara los saldos contra el CSV
│  ├─ esperar_bases.py          ← espera a que los motores acepten conexiones
│  └─ demo_seguridad.py         ← MITM, replay y spoofing en vivo
├─ shared\
│  ├─ money.py                  ← importes exactos con Decimal
│  ├─ portable.py               ← compatibilidad Windows (kernel32)
│  └─ seguridad.py              ← firma HMAC + nonce anti-replay
├─ asfi-service\                ← el núcleo: descifra, convierte, audita
├─ banks-services\              ← los 14 microservicios bancarios
├─ bcb-service\                 ← la cotización del dólar
└─ data\
   ├─ dataset.csv               ← el dataset del docente (no versionado)
   ├─ seed\                     ← el dataset cifrado, uno por banco
   ├─ keys\                     ← llaves RSA y ECC
   └─ audit.jsonl               ← el log de auditoría
```

---

## 11. Preguntas del docente y cómo responderlas

**¿Por qué no podés sumar los saldos en dólares en la base del banco?**
Porque están cifrados con el algoritmo de esa entidad. Sólo la ASFI tiene las
llaves. En la base del banco el único importe legible es el saldo en bolivianos,
porque lo escribe la ASFI al confirmar la transacción.

**¿Cómo garantizás que todos se convirtieron a la misma cotización?**
La ASFI pide la cotización al BCB una vez, valida que no esté vencida y que esté
en el rango permitido, y la aplica a todo el lote. La consulta C5 lo demuestra:
una sola tasa para los 14 bancos, en una ventana de menos de un segundo.

**¿Qué pasa si un banco se cae a mitad del barrido?**
El resto sigue. Ese banco queda con sus cuentas en PENDIENTE y el motivo queda en
`data\audit.jsonl`. Al volver a correr el barrido, la ASFI retoma sólo lo
pendiente: guarda en su base **antes** de confirmarle al banco (patrón outbox),
por eso nunca convierte dos veces ni pierde una conversión.

**¿Qué pasa si llega dos veces la misma confirmación?**
El banco es idempotente: si la cuenta ya fue confirmada con ese código y los
importes coinciden, devuelve el mismo comprobante. Si los importes difieren, la
rechaza con HTTP 409.

**¿Cómo sabés que nadie alteró un saldo después de convertirlo?**
La consulta C8 recalcula `saldo_usd × tipo_cambio` y lo compara con el `saldo_bs`
guardado, para todas las cuentas. Cualquier alteración da descuadre. Además la
ASFI guarda un hash SHA-256 del registro original.

**¿Qué algoritmos asimétricos usaron y por qué?**
RSA en el Banco FIE, ElGamal en el PYME y ECC en el BDP. En los tres, la ASFI
conserva la clave privada y el banco cifra con la pública: el banco protege el
dato y sólo el supervisor puede leerlo.

**¿Por qué el código de verificación es de 8 caracteres hexadecimales?**
Lo pide el enunciado. Se genera con `secrets.token_hex(4)` —4 bytes aleatorios
criptográficamente seguros, o sea 8 caracteres hex— y el banco lo valida con la
expresión regular `^[0-9A-F]{8}$` antes de aceptarlo.

**¿Cuánto tarda con los 12 millones de cuentas reales?**
El dataset entregado es la muestra del 1 % (123.790 cuentas). Medido: cifrado de
las 123.785 en ~27 s y carga de las 14 bases en ~8 s. El barrido escala en
paralelo por banco, con lotes de 500 y descifrado en varios procesos.

**¿Por qué los saldos por banco no siguen la tabla de proporciones del enunciado?**
Porque el CSV entregado no las respeta: la tabla dice Unión 22.472 y Mercantil
19.975, pero el archivo trae ~8.800 por banco de forma pareja. No es una decisión
nuestra. El seeder tiene la opción `--target-distribution official_1pct` por si
piden recortar a las cuotas oficiales.

**¿Por qué "Jose" aparece como "Iose" en el Banco BCP?**
Porque el cifrado Playfair clásico comparte celda para la I y la J: es una
propiedad conocida del algoritmo, no un error de implementación. Conviene decirlo
antes de que lo noten.

---

## 12. Si algo falla en vivo

| Síntoma | Solución |
|---|---|
| `NativeCommandError` y el script se corta en el paso 2 o 4 | **Ya corregido.** Era PowerShell 5.1: `docker` escribe su progreso por stderr y, con un pipe de por medio, 5.1 lo convertía en error fatal. Si volvés a verlo, es que tenés una copia vieja del script |
| «No respondieron los puertos 8101, 8102, …» | Casi siempre las bases están apagadas o vacías. `Levantar-Servicios.ps1` ahora lo avisa antes de arrancar; la solución es `Reiniciar-Demo.ps1` |
| `ModuleNotFoundError: No module named 'fcntl'` | Falta `shared\portable.py` o quedó un archivo sin parchear. Correr `Verificar-Entorno.ps1`, punto 5 |
| El barrido falla con `BrokenProcessPool` | `$env:ASFI_CRYPTO_WORKERS = "0"` y volver a levantar la ASFI (usa hilos en vez de procesos) |
| `curl : No se encuentra ningún parámetro…` | Usá **`curl.exe`**, no `curl` |
| Un servicio no levanta | `.\scripts\windows\Levantar-Servicios.ps1 -Ventanas`: cada servicio abre su ventana y **no se cierra** aunque falle, así se lee el traceback |
| MySQL rechaza conexiones al arrancar | Normal, tarda ~40 s. `Reiniciar-Demo.ps1` ya espera en el paso 5 |
| "No se puede cargar el archivo … .ps1" | `powershell -ExecutionPolicy Bypass -File .\scripts\windows\...` |
| El tablero dice "No se pudo consultar el estado" | Docker no está levantado: `docker compose up -d` |
| El tablero tarda en cargar la rúbrica | Normal si hay motores caídos: espera el timeout de cada uno (máximo ~9 s) |
| Todo quedó raro | `.\scripts\windows\Reiniciar-Demo.ps1` |

**Consejo:** tené la evidencia guardada de antemano
(`docs\evidencia-consultas.txt`) por si en la defensa no levanta algún contenedor.

---

## 13. Qué se probó de verdad

Todo lo siguiente se ejecutó con los datos reales del dataset, contra motores
reales (PostgreSQL, MySQL/MariaDB, SQLite y Redis levantados de verdad):

| Prueba | Resultado |
|---|---|
| Seeder actual sobre `data\dataset.csv` | 300/300 saldos idénticos al CSV ✅ |
| Los datos que estaban cargados | 283/300 saldos inflados ❌ (por eso hay que reiniciar) |
| `verificar_saldos.py` sobre datos buenos | 1.200 verificados, 0 errores ✅ |
| `verificar_saldos.py` sobre los datos malos | detecta 574/600 y muestra el factor ×10.000 ✅ |
| Carga en PostgreSQL / MySQL / SQLite / Redis | 800 cuentas por motor, 0 rechazos ✅ |
| Barrido paralelo (4 bancos, 4 motores) | 3.200 transacciones, 0 errores, 1,13 s ✅ |
| Una sola cotización en todo el barrido | 1 tasa, ventana de 0,75 s ✅ |
| `saldo_bs = saldo_usd × tipo_cambio` | 3.200 evaluadas, 0 descuadres ✅ |
| Consistencia banco ↔ ASFI | 3.200 comparadas, 0 diferencias ✅ |
| Códigos de verificación | 0 con formato inválido, 0 duplicados ✅ |
| Las 8 consultas | ejecutadas en PostgreSQL, MySQL, SQLite, Redis y ASFI ✅ |
| Seguridad: spoofing / MITM / replay | los 3 rechazados con HTTP 401 ✅ |
| Barrido completo tras quitar `fcntl` | 2.400/2.400 confirmadas, 0 errores ✅ |
| Los 6 scripts de PowerShell | sintaxis validada con el parser de PowerShell 7 ✅ |
| Tablero: rúbrica en vivo, acciones y consola | probado end-to-end ✅ |
| Tablero: clave inventada / otro origen / acción de Windows en Linux | 404 / 403 / 400 ✅ |

**Lo único que no se pudo probar:** la rama de Windows de `shared\portable.py` se
ejercitó con la API de kernel32 simulada (las banderas de `LockFileEx` salen
correctas), pero no sobre un Windows real. Por eso el punto 4 de
`Verificar-Entorno.ps1` la prueba en tu máquina antes de la defensa. **Corré eso
primero: si ese punto da OK, el resto anda.**

---

## 14. Reparto del trabajo

| Integrante | Responsabilidad |
|---|---|
| Daril (1) | Núcleo ASFI, motor criptográfico de los 14 algoritmos, gestor de llaves, barrido paralelo y auditoría |
| Robert (2) | Seeder del dataset, bases relacionales y APIs de los bancos 1 al 7, esquema normalizado Clientes/Cuentas |
| Integrante 3 | Servicio BCB, bases NoSQL (MongoDB, Redis), grafo Neo4j del BDP y APIs de los bancos 8 al 14 |

Las 8 consultas, las mitigaciones de seguridad, la compatibilidad con Windows y
el tablero se agregaron en la revisión final y cubren el sistema completo.
