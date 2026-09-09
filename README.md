# 🏦 Práctica 2: Plataforma Distribuida de Conversión Monetaria Interbancaria (ASFI - BCB)

> **Actualización de robustez y rendimiento:** carga por lotes con procesos e hilos,
> confirmaciones recuperables, cotización por lote y consolidación PostgreSQL.
> Consultar [la guía vigente y los benchmarks](docs/ROBUSTEZ_Y_RENDIMIENTO.md)
> para los comandos actuales, la política de carga y sus límites. Los resultados
> históricos y pendientes que aparecen más abajo corresponden a versiones anteriores.


Bienvenido al repositorio oficial del proyecto **Práctica 2 - Sistemas Distribuidos**. Este proyecto simula un entorno real de interoperabilidad financiera distribuida bajo restricciones monetarias en Bolivia, donde la **ASFI** procesa la conversión obligatoria de cuentas bancarias en dólares estadounidenses (USD) a bolivianos (Bs.) utilizando la cotización fluctuante del **Banco Central de Bolivia (BCB)**.

---

## 📐 1. Resumen de la Arquitectura del Sistema

El sistema consta de 3 capas principales de microservicios:

```
                                  +---------------------------------------+
                                  |     Servicio BCB (Tasa de Cambio)     |
                                  | - Cotización USD ➔ Bs. (±0.9999)      |
                                  | - Fluctuación configurable c/ 3 min   |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +-------------------+-------------------+
                                  |     Servicio Central ASFI (Core)     |
                                  | - Barrido Paralelo Asíncrono (14 APIs)|
                                  | - Gestor de Llaves (Key Manager)      |
                                  | - Motor Criptográfico (14 Cifrados)   |
                                  | - Generador de Código Hex 8 dígitos   |
                                  | - Registro de Auditoría (Audit Log)   |
                                  | - BD Central Relacional (PostgreSQL)  |
                                  +---------+-------------------+---------+
                                            |                   |
                     +----------------------+                   +----------------------+
                     | (GET /cuentas/cifradas)                  | (GET /cuentas/cifradas)
                     | (POST /cuentas/confirmar)                | (POST /cuentas/confirmar)
                     v                                          v
      +------------------------------+           +------------------------------+
      |      Bancos Relacionales     |           |     Bancos No-Relacionales    |
      |          (1 al 7)            |           |         (8 al 14)            |
      | - Banco Unión (César)        |           | - Banco Prodem (Blowfish)    |
      | - Banco Mercantil (Atbash)   |           | - Banco Solidario (Twofish)  |
      | - BNB (Vigenère)             |           | - Banco Fortaleza (AES)      |
      | - BCP (Playfair)             |           | - Banco FIE (RSA)            |
      | - Banco BISA (Hill)          |           | - Banco PYME (ElGamal)       |
      | - Banco Ganadero (DES)       |           | - BDP (ECC - Neo4j Grafos)   |
      | - Banco Económico (3DES)     |           | - Banco N. Arg. (ChaCha20)   |
      |                              |           |                              |
      |  (PostgreSQL, MySQL, SQLite) |           | (MongoDB, Redis, Neo4j)      |
      +------------------------------+           +------------------------------+
```

---

## 👥 2. Asignación de Roles y Tareas por Integrante

### 🔵 Integrante 1 (Líder de Proyecto / Núcleo ASFI & Criptografía - Daril)
**Responsabilidades principales:**
1. **Motor Criptográfico Central (`asfi-service/crypto/`):**
   - Implementar/organizar las funciones de descifrado y cifrado para los 14 algoritmos (César, Atbash, Vigenère, Playfair, Hill, DES, 3DES, Blowfish, Twofish, AES, RSA, ElGamal, ECC, ChaCha20).
   - Crear el **Gestor de Llaves ASFI (Key Manager)**.
2. **Servicio Central ASFI & BD Central (`asfi-service/`):**
   - Diseñar la base de datos relacional de consolidación de ASFI (PostgreSQL).
   - Implementar el procesador de conversión USD ➔ Bs y el generador del **Código de Verificación Hexadecimal de 8 caracteres** (`0-9, A-F`).
3. **Barrido Paralelo Asíncrono & Auditoría:**
   - Desarrollar el cliente asíncrono/multihilo (`httpx`/`asyncio`) que ejecute las peticiones en paralelo a las 14 APIs bancarias simultáneamente para evitar sesgos por la fluctuación del dólar.
   - Generar el archivo/tabla de **Log de Auditoría** (Timestamp, Tasa BCB, CuentaId, BancoId, CodigoVerificacion, Estado).

---

### 🟢 Integrante 2 (Infraestructura Bancos Relacionales & Seeder)
**Responsabilidades principales:**
1. **Generador y Poblamiento de Datos (`scripts/seeder.py`):**
   - Crear el script que genera y puebla la muestra del 1% (~120,000 cuentas en total entre los 14 bancos).
   - Asegurar que cada cuenta sea guardada en su correspondiente BD bancaria con sus datos sensibles previamente cifrados.
2. **Motores de BD Relacionales (Bancos 1 al 7):**
   - Configurar los motores relacionales (mínimo 3 distintas tecnologías: **PostgreSQL**, **MySQL**, **MariaDB/SQLite**).
   - Mapear las bases de datos para los Bancos 1 al 7:
     1. Banco Unión S.A. (César)
     2. Banco Mercantil Santa Cruz S.A. (Atbash)
     3. Banco Nacional de Bolivia (BNB) (Vigenère)
     4. Banco de Crédito de Bolivia (BCP) (Playfair)
     5. Banco BISA S.A. (Hill)
     6. Banco Ganadero S.A. (DES)
     7. Banco Económico S.A. (3DES)
3. **APIs Bancarias (Bancos 1 al 7):**
   - Exponer endpoints para la entrega de datos cifrados y la recepción/actualización del código de verificación de 8 dígitos hexadecimales.

---

### 🔴 Integrante 3 (BDs NoSQL, Grafo Neo4j, Servicio BCB & Reportes)
**Responsabilidades principales:**
1. **Servicio BCB (Fluctuación del Dólar) (`bcb-service/`):**
   - Desarrollar el microservicio mock del BCB que fluctúe la cotización del dólar cada **3 minutos (configurable)** en **±0.9999** con **4 decimales** de precisión.
2. **BDs No-Relacionales y Base de Datos de Grafos (Bancos 8 al 14):**
   - Configurar motores NoSQL (ej. **MongoDB**, **Redis**).
   - **Requisito Crítico (20 pts):** Implementar **1 Base de Datos orientada a Grafos en Neo4j** para uno de los bancos (ej. BDP) con nodos `Cliente` y `Cuenta` y relación `TIENE_CUENTA`.
   - Mapear las BDs de los Bancos 8 al 14:
     8. Banco Prodem S.A. (Blowfish)
     9. Banco Solidario S.A. (Twofish)
     10. Banco Fortaleza S.A. (AES)
     11. Banco FIE S.A. (RSA)
     12. Banco PYME de la Comunidad S.A. (ElGamal)
     13. Banco de Desarrollo Productivo S.A.M. (ECC - Neo4j)
     14. Banco de la Nación Argentina (ChaCha20)
3. **APIs Bancarias (Bancos 8 al 14) & Consultas (40 pts):**
   - Exponer endpoints para bancos 8 al 14.
   - Escribir los **8 scripts de consulta SQL/NoSQL** requeridos por la guía de la práctica para verificación de saldo y auditoría sin uso de IA durante la defensa.

---

## 📊 3. Mapeo Oficial de Entidades Financieras y Algoritmos

| ID | Banco | Nro. Cuentas (100%) | Nro. Cuentas (1% Muestra) | Algoritmo de Cifrado | Motor de Base de Datos Recomendado |
|---|---|---|---|---|---|
| 1 | Banco Unión S.A. | 2,247,210 | 22,472 | Cifrado César | PostgreSQL |
| 2 | Banco Mercantil Santa Cruz S.A. | 1,997,520 | 19,975 | Cifrado Atbash | MySQL |
| 3 | Banco Nacional de Bolivia (BNB) | 1,498,140 | 14,981 | Cifrado Vigenère | MariaDB / SQLite |
| 4 | Banco de Crédito de Bolivia (BCP) | 1,398,264 | 13,983 | Cifrado Playfair | PostgreSQL |
| 5 | Banco BISA S.A. | 1,048,698 | 10,487 | Cifrado Hill | MySQL |
| 6 | Banco Ganadero S.A. | 948,822 | 9,488 | Cifrado DES | PostgreSQL |
| 7 | Banco Económico S.A. | 848,946 | 8,489 | Cifrado 3DES | MySQL |
| 8 | Banco Prodem S.A. | 749,070 | 7,491 | Blowfish | MongoDB |
| 9 | Banco Solidario S.A. | 549,318 | 5,493 | Twofish | MongoDB |
| 10 | Banco Fortaleza S.A. | 349,566 | 3,496 | AES | Redis / MongoDB |
| 11 | Banco FIE S.A. | 399,504 | 3,995 | RSA | MongoDB |
| 12 | Banco PYME de la Comunidad S.A. | 224,721 | 2,247 | ElGamal | SQLite / MongoDB |
| 13 | Banco de Desarrollo Productivo S.A.M. | 99,876 | 999 | ECC | **Neo4j (BD de Grafos)** |
| 14 | Banco de la Nación Argentina | 19,975 | 200 | ChaCha20 | MongoDB |

---

## 📂 4. Estructura de Directorios del Proyecto

```text
Practica2/
├── README.md                              # Este documento
├── 01 - Practica 2 Algoritmos...md        # Especificaciones del docente
├── docker-compose.yml                     # Orquestador de contenedores (BDs y servicios)
├── bcb-service/                           # Microservicio BCB (Tipo de Cambio)
│   ├── main.py                            # FastAPI app
│   └── requirements.txt
├── asfi-service/                          # Servicio Central ASFI
│   ├── main.py                            # FastAPI app y Orquestador de Barrido
│   ├── crypto/                            # Módulo central de algoritmos de cifrado/descifrado
│   │   ├── ciphers.py                     # César, Atbash, Vigenère, Playfair, Hill, AES, RSA, etc.
│   │   └── key_manager.py                 # Gestión de llaves ASFI
│   ├── database.py                        # Conexión BD ASFI
│   ├── audit_logger.py                    # Generador de Logs de auditoría
│   └── requirements.txt
├── banks-services/                        # APIs de las 14 Entidades Financieras
│   ├── common/                            # Código común para las APIs bancarias
│   │   └── bank_router.py                 # Endpoints genéricos GET /cuentas y POST /confirmar
│   ├── bank_01_union/                     # Microservicio Banco Unión
│   ├── bank_02_mercantil/
│   ├── ...
│   └── bank_14_nacion_argentina/
├── scripts/                               # Scripts de apoyo y utilidad
│   ├── seeder.py                          # Script de poblamiento del 1% (~120,000 cuentas)
│   └── queries.sql                        # Consultas de verificación
└── docs/                                  # Documentación adicional
```

---

## 🤖 5. Guía para Consultar a la IA durante el Desarrollo

Para que todos los integrantes puedan usar asistentes de IA de forma consistente y sin romper el código de los demás, **sigan este formato al hacer preguntas**:

### 💡 Ejemplo de Prompt para pedir ayuda a la IA:
> *"Estoy trabajando en la **Práctica 2 de Sistemas Distribuidos (ASFI/BCB)**. Mi rol es el **[Rol: Integrante 1 / 2 / 3]**. Revisa el archivo `README.md` del repositorio para entender la estructura. Necesito implementar la clase/función `[Nombre de la función/API]` siguiendo el patrón establecido en `[Ruta del archivo]`..."*

---

## 🛠️ 6. Cómo Levantar el Proyecto Localmente

### Prerrequisitos
- Docker y Docker Compose instalados.
- Python 3.11+ instalado.

### Preparar el entorno Python en Linux

Si `.venv/bin/python` no tiene `pip` o aparece `No module named ensurepip`, instala los paquetes del sistema una sola vez:

```bash
sudo apt update
sudo apt install python3-venv python3-pip
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

En VS Code selecciona `.venv/bin/python` como intérprete de Python.

### Pasos
1. **Clonar el repositorio y entrar al proyecto:**
   ```bash
   git clone <URL_DEL_REPOSITO>
   cd Practica2
   ```

2. **Levantar la infraestructura con Docker Compose:**
   ```bash
   sudo docker compose up -d
   ```

3. **Poblar las bases de datos con la muestra del 1%:**
   ```bash
   .venv/bin/python scripts/seeder.py data/dataset.csv --output-dir data/seed
   ```
   El dataset oficial (`data/dataset.csv`, no versionado en git) ya está en
   esta carpeta del proyecto. Filas inválidas se listan en
   `data/seed/rejected_rows.csv` en vez de abortar el proceso; la consola
   muestra cuántos registros se cargaron por banco frente a la cuota oficial
   del 1% (ver BITACORA.md sobre por qué normalmente no van a coincidir).

4. **Levantar el BCB:**
   ```bash
   cd bcb-service
   ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
   ```

5. **Levantar una API bancaria de prueba, en otra terminal:**
   ```bash
   .venv/bin/python scripts/load_postgres.py data/seed/bank_01.jsonl \
     --database-url "postgresql://union_user:union_password@127.0.0.1:5433/bank_union"
   BANK_ID=1 BANK_STORAGE=postgres \
   DATABASE_URL="postgresql://union_user:union_password@127.0.0.1:5433/bank_union" \
   .venv/bin/uvicorn bank_template.main:app --app-dir banks-services --host 0.0.0.0 --port 8101
   ```

6. **Levantar ASFI, en otra terminal:**
   ```bash
   cd asfi-service
   BCB_URL=http://localhost:8001/api/bcb/tipo-cambio BANK_URL_1=http://localhost:8101/api/banco ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
   ```

7. **Probar el Barrido Paralelo de la ASFI:**
   ```bash
   curl -X POST http://localhost:8000/api/asfi/ejecutar-conversion
   ```

Banco 2 puede usar MySQL con el mismo contrato:

```bash
.venv/bin/python scripts/load_mysql.py data/seed/bank_02.jsonl \
  --database-url "mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil"

BANK_ID=2 BANK_STORAGE=mysql \
DATABASE_URL="mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil" \
.venv/bin/uvicorn bank_template.main:app --app-dir banks-services --port 8102
```

Banco 3 puede usar SQLite sin agregar otro contenedor:

```bash
.venv/bin/python scripts/load_sqlite.py data/seed/bank_03.jsonl \
  --database-url "sqlite:///data/bank_03.sqlite"

BANK_ID=3 BANK_STORAGE=sqlite \
DATABASE_URL="sqlite:///data/bank_03.sqlite" \
.venv/bin/uvicorn bank_template.main:app --app-dir banks-services --port 8103
```

Banco 8 puede usar MongoDB:

```bash
.venv/bin/python scripts/load_mongo.py data/seed/bank_08.jsonl \
  --database-url "mongodb://127.0.0.1:27017/bank_prodem"

BANK_ID=8 BANK_STORAGE=mongo \
DATABASE_URL="mongodb://127.0.0.1:27017/bank_prodem" \
.venv/bin/uvicorn bank_template.main:app --app-dir banks-services --port 8108
```

Los bancos 9, 10, 11, 12 y 14 reutilizan MongoDB en bases separadas:

```bash
for spec in \
  "9 bank_solidario" "10 bank_fortaleza" "11 bank_fie" \
  "12 bank_pyme" "14 bank_argentina"; do
  set -- $spec
  .venv/bin/python scripts/load_mongo.py "data/seed/bank_$(printf '%02d' "$1").jsonl" \
    --database-url "mongodb://127.0.0.1:27017/$2"
done
```

Banco 13 usa Neo4j y crea `Cliente`, `Cuenta` y `TIENE_CUENTA`:

```bash
.venv/bin/python scripts/load_neo4j.py data/seed/bank_13.jsonl \
  --database-url "neo4j://neo4j:bdp_password@127.0.0.1:7687"
```

Banco 10 usa Redis como segundo motor NoSQL:

```bash
sudo docker compose up -d bank10-fortaleza-redis

.venv/bin/python scripts/load_redis.py data/seed/bank_10.jsonl \
  --database-url "redis://127.0.0.1:6379/0#bank10"

BANK_ID=10 BANK_STORAGE=redis \
DATABASE_URL="redis://127.0.0.1:6379/0#bank10" \
.venv/bin/uvicorn bank_template.main:app --app-dir banks-services --port 8110
```

Banco 4 usa PostgreSQL en una base aislada:

```bash
sudo docker compose up -d bank4-bcp-db

.venv/bin/python scripts/load_postgres.py data/seed/bank_04.jsonl \
  --database-url "postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp"

BANK_ID=4 BANK_STORAGE=postgres \
DATABASE_URL="postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp" \
.venv/bin/uvicorn bank_template.main:app --app-dir banks-services --port 8104
```

Banco 5 usa MySQL en una base aislada:

```bash
sudo docker compose up -d bank5-bisa-db

.venv/bin/python scripts/load_mysql.py data/seed/bank_05.jsonl \
  --database-url "mysql://bisa_user:bisa_password@127.0.0.1:3307/bank_bisa"

BANK_ID=5 BANK_STORAGE=mysql \
DATABASE_URL="mysql://bisa_user:bisa_password@127.0.0.1:3307/bank_bisa" \
.venv/bin/uvicorn bank_template.main:app --app-dir banks-services --port 8105
```

Los bancos 6 y 7 usan bases aisladas:

```bash
sudo docker compose up -d bank6-ganadero-db bank7-economico-db

.venv/bin/python scripts/load_postgres.py data/seed/bank_06.jsonl \
  --database-url "postgresql://ganadero_user:ganadero_password@127.0.0.1:5436/bank_ganadero"
.venv/bin/python scripts/load_mysql.py data/seed/bank_07.jsonl \
  --database-url "mysql://economico_user:economico_password@127.0.0.1:3308/bank_economico"
```

### Demostración integrada

Con los contenedores Docker activos y los datos de `data/seed` generados, se
pueden cargar y levantar los bancos 1, 2, 3, 4 y 8 junto con BCB y ASFI:

```bash
bash scripts/run_demo.sh
```

El script ejecuta un barrido único con `ACTIVE_BANK_IDS=1,2,3,4,8` como
demostración parcial.

### Demostración de los 14 bancos

Después de levantar todos los servicios Docker, el flujo completo se ejecuta con:

```bash
bash scripts/run_all_demo.sh
```

Este script carga los 14 archivos de `data/seed`, levanta las 14 APIs, consulta
BCB una sola vez y ejecuta ASFI con `ACTIVE_BANK_IDS=1,2,...,14`.

---
*Desarrollado para la materia de Sistemas Distribuidos - Práctica 2.*

## Estado actual del proyecto

La demostración integrada está funcionando con una muestra local de 10 registros
por banco. La última ejecución procesó 14 bancos, 142 transacciones, 142
confirmaciones y 0 errores. Las dos transacciones adicionales provienen de
registros de prueba conservados previamente en Banco 1.

### Motores y distribución

| Motor | Bancos |
|---|---|
| PostgreSQL | 1, 4 y 6 |
| MySQL | 2, 5 y 7 |
| SQLite | 3 |
| MongoDB | 8, 9, 11, 12 y 14 |
| Redis | 10 |
| Neo4j | 13 |

Neo4j debe contener `Cliente`, `Cuenta` y `TIENE_CUENTA`. Todos los servicios
bancarios exponen el mismo contrato:

```text
GET  /api/banco/cuentas/cifradas?offset=0&limit=100
POST /api/banco/cuentas/confirmar
GET  /health
```

### Integración para compañeros

Antes de cambiar código, cada integrante debe:

1. Crear su rama de trabajo.
2. Mantener el contrato HTTP anterior.
3. Usar el adaptador de su motor y no modificar ASFI para un banco concreto.
4. Probar carga, lectura cifrada y confirmación.
5. Documentar comandos, variables de entorno y consultas.
6. Ejecutar `bash scripts/run_all_demo.sh` antes de integrar cambios.

### Tareas pendientes para la entrega final

- Implementar la persistencia de consolidación de ASFI en `asfi-db` (PostgreSQL);
  actualmente la auditoría principal se escribe en `data/audit.jsonl`.
- ✅ Bancos 1–7: el seeder ya procesa el dataset oficial (`data/dataset.csv`,
  123,790 filas reales) en vez de la muestra local de 10 registros, con
  validación de filas inválidas. Pendiente para el equipo: el dataset
  entregado no reparte las cuentas según la tabla de proporciones del
  enunciado (trae ~8,700–8,900 filas por banco de forma pareja en vez de la
  distribución 22,472/19,975/.../200); confirmar con el docente si hay que
  usar el dataset completo de 12M o si esta muestra pareja es la oficial.
  Ver BITACORA.md, sección "Actualización de Integrante 2".
- Bancos 8–14: aplica lo mismo (procesar el dataset oficial), pero antes hay
  que revisar el rendimiento del cifrado ElGamal (Banco 12): con miles de
  registros reales tardó más de 2 minutos en un cifrado de prueba por el
  exponente aleatorio de 2048 bits en cada operación.
- Limpiar o recrear las bases de demostración para obtener conteos reproducibles.
- Preparar las 8 consultas SQL/NoSQL solicitadas para la defensa y guardarlas en
  una carpeta `queries/` con datos de ejemplo.
- Validar en Neo4j las consultas de clientes, cuentas y relaciones.
- Añadir pruebas automatizadas permanentes para los 14 cifrados, adaptadores,
  códigos hexadecimales y consistencia de una sola tasa BCB.
- Revisar credenciales y rutas para que sean variables de entorno o archivos
  locales, nunca secretos versionados.
- Ejecutar una prueba final desde un entorno limpio y registrar el resultado.

### Entrega esperada de cada integrante

Cada contribución debe incluir:

```text
Código funcional
Comando de ejecución
Prueba de lectura cifrada
Prueba de confirmación
Consulta o evidencia de la base
Actualización de BITACORA.md
```
