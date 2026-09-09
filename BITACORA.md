# 📋 Bitácora de Proyecto y Registro de Cambios (Changelog) - Práctica 2

**Proyecto:** Plataforma Distribuida de Conversión Monetaria Interbancaria (ASFI - BCB)
**Materia:** Sistemas Distribuidos
**Líder / Desarrollador Principal:** Daril (Integrante 1)
**Equipo:** 3 Integrantes

---

## 👥 1. Organización del Equipo y Distribución de Responsabilidades

| Integrante | Rol Principal | Áreas de Enfoque |
|---|---|---|
| **Daril (Tú)** | **Líder / Núcleo ASFI & Motor Criptográfico** | - Motor criptográfico modular (14 algoritmos, patrón Strategy/Factory)<br>- Gestor de Llaves ASFI (Key Manager)<br>- Orquestador de Barrido Paralelo Asíncrono (concurrencia y multihilo)<br>- Base de Datos Central ASFI (PostgreSQL) y Registro de Auditoría |
| **Integrante 2** | **Infraestructura Bancos Relacionales & Seeder** | - Script de poblamiento del 1% del dataset con cifrado previo<br>- Bases de datos relacionales (PostgreSQL, MySQL, SQLite)<br>- APIs bancarias de los bancos relacionales (1 al 7) |
| **Integrante 3** | **BDs NoSQL, Grafo Neo4j, Servicio BCB & Consultas** | - Microservicio BCB (cotización dinámica del dólar con fluctuación configurable)<br>- Bases de datos NoSQL (MongoDB, Redis)<br>- Base de datos orientada a grafos en Neo4j (Banco 13 - BDP: nodos Cliente y Cuenta)<br>- APIs bancarias (8 al 14) y 8 consultas SQL/NoSQL |

---

## 🎯 2. Contexto Clave y Reglas de Negocio Incorporadas

1. **Estructura del Dataset:**
   - Columnas: `Nro`, `Identificacion`, `Nombres`, `Apellidos`, `NroCuenta`, `IdBanco`, `Saldo`.
   - Se procesará una muestra del **1%** (~120,000 registros).
   - Los datos sensibles deben estar **cifrados en las BDs de los bancos** antes de que ASFI los consuma.

2. **Problema Crítico de Concurrencia y Fluctuación del Dólar:**
   - El BCB puede fluctuar la tasa en intervalos muy cortos (incluso cada segundo en la defensa del docente).
   - El barrido de ASFI **no puede ser secuencial**; debe ser **paralelo/asíncrono** para congelar la tasa y procesar todas las cuentas al mismo tipo de cambio en esa ventana temporal.
   - Generación de un **Código de Verificación Hexadecimal de 8 caracteres** (`0-9, A-F`) para confirmar la transacción y alinear el saldo en el banco con el saldo en ASFI.

3. **Arquitectura Modular Extensible (a prueba de cambios del docente):**
   - El motor criptográfico implementará el patrón **Strategy/Factory**. Si el docente pide cambiar el algoritmo de un banco en plena defensa, se cambiará una línea de configuración sin romper el resto del sistema.

---

## 📝 3. Registro de Cambios (Changelog)

### [2026-09-06] - Inicialización y Planificación
- **Documentación:** Creación de esta bitácora (`CHANGELOG.md` / `BITACORA.md`) con las reglas de negocio, roles y prioridades.
- **Análisis de Requisitos:** Verificación del enunciado oficial, especificaciones del dataset y arquitectura en `README.md`.
- **Estructura Base:** Configuración preliminar de `docker-compose.yml`, `requirements.txt`, `asfi-service` y `bcb-service`.
- **BCB:** Intervalo de fluctuación configurable mediante `PUT /api/bcb/configurar-intervalo`.
- **Seeder:** Creación de `scripts/seeder.py` para leer CSV, cifrar campos sensibles y generar un JSONL por banco.
- **Hill:** Implementación con aritmética pura de Python para evitar dependencia adicional de `numpy`.
- **APIs bancarias:** Creación de `banks-services/common/bank_router.py` con endpoints paginados para cuentas cifradas y confirmaciones protegidas por bloqueo.
- **Plantilla bancaria:** Creación de `banks-services/bank_template/main.py`, parametrizable con `BANK_ID` y `BANK_DATA_FILE`.
- **ASFI:** Implementación del barrido asíncrono en `asfi-service/main.py`; captura una tasa única del BCB, consulta los bancos concurrentemente, confirma transacciones y escribe la auditoría en JSONL.
- **Claves compartidas:** Persistencia local de las claves RSA y ECC en `data/keys/` para que el seeder, los servicios bancarios y ASFI puedan cifrar y descifrar entre procesos.
- **Servicio bancario:** Validación de `BANK_ID`, resolución estable de rutas de datos y endpoint `/health`.
- **Playfair:** Conservación del separador decimal y eliminación del relleno criptográfico al descifrar saldos.
- **Prueba integrada:** Verificación exitosa del flujo completo con 14 servicios bancarios: 14 transacciones, 14 confirmadas, 0 errores y una única cotización BCB.
- **PostgreSQL real:** Banco 1 carga registros cifrados desde JSONL, los entrega mediante su API y persiste las confirmaciones en PostgreSQL.
- **MySQL real:** Banco 2 incorpora el adaptador `MySQLStore` y el cargador `scripts/load_mysql.py`; se validaron carga, lectura y persistencia de confirmaciones.
- **SQLite real:** Banco 3 incorpora el adaptador `SQLiteStore` y el cargador `scripts/load_sqlite.py`; se validaron carga, lectura y persistencia de confirmaciones.
- **Barrido multi-motor:** Prueba integrada exitosa con PostgreSQL (Banco 1), MySQL (Banco 2) y SQLite (Banco 3): 32 transacciones, 32 confirmadas, 0 errores y una única tasa BCB aplicada.
- **MongoDB real:** Banco 8 incorpora el adaptador `MongoStore` y el cargador `scripts/load_mongo.py`; se validaron carga, lectura y persistencia de confirmaciones.
- **Banco 4:** Se agregó un contenedor PostgreSQL aislado (`bank4-bcp-db`, puerto externo 5435) para reutilizar `PostgreSQLStore` sin mezclar datos con Banco 1. Falta levantar el contenedor y validar desde el entorno del equipo.
- **Banco 5:** Se agregó un contenedor MySQL aislado (`bank5-bisa-db`, puerto externo 3307) para reutilizar `MySQLStore` con el cifrado Hill.
- **Bancos 6 y 7:** Se agregaron bases aisladas PostgreSQL (`5436`) y MySQL (`3308`), reutilizando sus adaptadores.
- **MongoDB restante:** Los bancos 9, 10, 11, 12 y 14 pueden cargarse en bases MongoDB separadas mediante `MongoStore`.
- **Neo4j:** Banco 13 incorpora `Neo4jStore` y `load_neo4j.py`, creando nodos `Cliente`, `Cuenta` y relación `TIENE_CUENTA`.
- **Redis:** Banco 10 incorpora `RedisStore` y `load_redis.py`; se agregó el contenedor `bank10-fortaleza-redis` para completar el segundo motor NoSQL requerido.
- **Validación NoSQL/grafo:** Redis y Neo4j fueron cargados con 10 registros cada uno; ambos entregaron cuentas cifradas y persistieron confirmaciones correctamente.
- **Flujo final:** Se agregó `scripts/run_all_demo.sh` para cargar los 14 bancos, levantar sus APIs y ejecutar un barrido ASFI completo con una única cotización.
- **Hill:** Se corrigió el retiro del relleno `X` agregado por Hill en saldos de longitud impar; los 9 errores observados en la primera prueba completa correspondían únicamente al Banco 5.

### [2026-09-08] - Tarea 2: Bases de Datos NoSQL (MongoDB & Redis) y APIs Bancos 8 al 14
- **Persistencia Docker:**
  - Configuración de volúmenes persistentes con nombre `banks_mongo_data` y `bank10_redis_data` en `docker-compose.yml`.
  - Verificación operativa de los contenedores `banks-nosql-db` (mongo:6.0, puerto 27017) y `bank10-fortaleza-redis` (redis:7-alpine, puerto 6379).
- **Adaptador MongoDB (`MongoStore`):**
  - Aislamiento lógico por base de datos independiente (`bank_prodem`, `bank_solidario`, `bank_fortaleza`, `bank_fie`, `bank_pyme`, `bank_bdp`, `bank_argentina`).
  - Creación automática de índices en MongoDB: índice único para `nro`, índice para `id_banco`, e índice para `codigo_verificacion`.
  - Integración opcional de caché y tracking transaccional en Redis (`bank:{id}:*`) con fallback transparente ante desconexión.
  - Validación estricta del código de verificación (hexadecimal de exactamente 8 caracteres).
  - Soporte de reintento idempotente (200 OK con mismo código) y protección anti-replay / alteración (409 Conflict si se intenta reconfirmar con código diferente).
- **Adaptador Redis (`RedisStore`):**
  - Estandarización de namespaces aislados por banco: `bank:{bank_id}:cuenta:{account_ref}`, `bank:{bank_id}:cuentas:index` y `bank:{bank_id}:tx:{account_ref}`.
  - Validación y actualización de esquema completo: `CuentaId`, `BancoId`, `SaldoUSD`, `SaldoBs`, `Estado`, `CodigoVerificacion`, `FechaConversion`.
  - Validación estricta de 8 caracteres hex, idempotencia y anti-replay (409 Conflict).
- **Enrutador y Plantilla Bancaria (`bank_router.py` y `bank_template/main.py`):**
  - Compatibilidad dual de rutas: `/cuentas`, `/confirmar`, `/cuentas/{ref}` y las rutas compatibles con ASFI (`/api/banco/cuentas/cifradas`, `/api/banco/cuentas/confirmar`, `/api/banco/cuentas/{ref}`).
  - Pydantic model `ConfirmationRequest` con soporte para aliases en español e inglés y validación regex `^[0-9A-Fa-f]{8}$`.
  - Patrón Factory `create_app(...)` para evitar colisiones de caché singleton entre microservicios bancarios.
  - Verificación de salud `/health` con ping real a MongoDB y Redis.
- **Microservicios Bancarios Individuales (Bancos 8 al 14):**
  - Banco 8: Banco Prodem S.A. -> Blowfish (puerto 8108)
  - Banco 9: Banco Solidario S.A. -> Twofish (puerto 8109)
  - Banco 10: Banco Fortaleza S.A. -> AES (puerto 8110, Redis primario)
  - Banco 11: Banco FIE S.A. -> RSA (puerto 8111)
  - Banco 12: Banco PYME de la Comunidad S.A. -> ElGamal (puerto 8112)
  - Banco 13: Banco de Desarrollo Productivo S.A.M. -> ECC (puerto 8113)
  - Banco 14: Banco de la Nación Argentina -> ChaCha20 (puerto 8114)
  - Cada uno con su propio paquete y punto de entrada `main.py` (`banks-services/bank_08_prodem` a `bank_14_nacion_argentina`).
- **Poblamiento NoSQL (`scripts/load_nosql_banks.py`):**
  - Script automatizado que carga las cuentas cifradas desde `data/seed/bank_XX.jsonl` a las bases MongoDB y sincroniza con Redis.
- **Suite de Pruebas Automatizadas (`tests/test_nosql_banks_8_14.py`):**
  - 9 pruebas automatizadas pasando exitosamente (cifrado/descifrado de los 7 algoritmos, aislamiento NoSQL, índices MongoDB, namespaces Redis, endpoints `/cuentas` con paginación, consulta por ID, validaciones de código de 8 hex, ciclo de confirmación, idempotencia, anti-replay, y barrido simulado ASFI de 35 cuentas).
- **Pruebas de Regresión:**
  - Verificación de `tests/test_bcb_service.py` con 8/8 pruebas exitosas sin alterar el microservicio BCB.

### [2026-09-08] - Tarea 3: BD Orientada a Grafos Neo4j (Banco BDP - Exclusivo 20 pts)
- **Infraestructura Docker y Persistencia:**
  - Configuración de volúmenes persistentes con nombre `bank13_neo4j_data` y `bank13_neo4j_logs` para el contenedor `bank13-bdp-neo4j` (imagen `neo4j:5.11`, puertos 7687 Bolt y 7474 HTTP) en `docker-compose.yml`.
  - Configuración de variables de entorno y credenciales seguras en `.env.example` (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `BANK_13_STORAGE=neo4j`, `BANK_13_DATABASE_URL`).
- **Modelo de Grafos en Neo4j:**
  - Creación del modelo conceptual `(:Cliente)-[:TIENE_CUENTA]->(:Cuenta)`.
  - Propiedades del nodo `(:Cliente)`: `clienteId`, `identificacion`, `nombres`, `apellidos`.
  - Propiedades del nodo `(:Cuenta)`: `cuentaId`, `nro`, `bancoId` (13), `id_banco`, `saldoUSD`, `saldo`, `saldoBs`, `saldo_bs`, `estado`, `codigoVerificacion`, `codigo_verificacion`, `fechaConversion`, `convertido_at`, `tipoCambio`, `nroCuenta`, `nro_cuenta`.
- **Restricciones e Índices (Neo4j 5.x):**
  - Creación automática de restricción de unicidad para `Cliente.clienteId` (`cliente_id_unique`).
  - Creación automática de restricción de unicidad para `Cuenta.cuentaId` (`cuenta_id_unique`).
  - Creación de índices en `Cuenta.bancoId` y `Cuenta.codigoVerificacion`.
- **Cifrado Asimétrico ECC:**
  - Protección de datos sensibles (`Saldo`, `Identificacion`, `Nombres`, `Apellidos`, `NroCuenta`) cifrados con ECC (Curva Elíptica SECP256R1 con ECDH + HKDF SHA-256 + AES-128-CTR).
  - Verificación de carga y aislamiento de claves privadas (`data/keys/bank_13_ecc.pem`).
- **Adaptador de Persistencia (`Neo4jStore` en `banks-services/common/neo4j_store.py`):**
  - Implementación completa de las 8 consultas Cypher parametrizadas requeridas:
    - A. `get_all_clients`: todos los clientes ordenados por `clienteId`.
    - B. `get_all_accounts`: todas las cuentas con paginación `offset` y `limit`.
    - C. `get_accounts_by_client`: cuentas asociadas a un `clienteId`.
    - D. `get_account_by_id`: búsqueda de cuenta por `cuentaId` o `nro`.
    - E. `get_client_by_account`: cliente propietario de una cuenta.
    - F. `get_graph_clients_and_accounts`: clientes y cuentas vinculados por `TIENE_CUENTA`.
    - G. `get_pending_accounts`: cuentas en estado `PENDIENTE` para conversión.
    - H. `confirm`: confirmación de conversión con validación de 8 caracteres hex, idempotencia y anti-replay (409 Conflict).
  - Métodos auxiliares: `count_clients()`, `count_accounts()`, `count_relationships()`, `health_check()`, `close()`.
- **Integración con API del Banco BDP:**
  - Microservicio `banks-services/bank_13_bdp/main.py` configurado por defecto con `storage="neo4j"` en el puerto `8113`.
  - Exposición de endpoints REST compatibles con ASFI y rutas específicas de grafo en `bank_router.py` y `bank_template/main.py`:
    - `GET /cuentas`, `GET /cuentas/{account_ref}`, `POST /confirmar`, `GET /health`, `GET /info`.
    - `GET /clientes`, `GET /clientes/{client_id}/cuentas`, `GET /cuentas/{account_ref}/cliente`, `GET /grafo`.
- **Poblamiento e Idempotencia (`scripts/load_neo4j.py`):**
  - Actualización del script con cláusulas `MERGE` (`ON CREATE` / `ON MATCH`) que evitan nodos o relaciones duplicadas ante múltiples ejecuciones consecutivas.
- **Suite de Pruebas Automatizadas (`tests/test_bdp_neo4j.py`):**
  - 6 pruebas integrales (restricciones e índices, modelo de grafos e idempotencia, cifrado/descifrado ECC, 8 consultas Cypher A a H, validaciones de API REST y ciclo de confirmación, y barrido simulado ASFI de 5 cuentas con 0 errores).
- **Pruebas de Regresión:**
  - `tests/test_bcb_service.py` (Tarea 1): 8/8 pruebas exitosas.
  - `tests/test_nosql_banks_8_14.py` (Tarea 2): 9/9 pruebas exitosas.

### Estado de cierre de esta etapa


La arquitectura distribuida está integrada en modo demostración. Se validó el
flujo con los 14 bancos, 142 transacciones, 142 confirmaciones y 0 errores.
La prueba utiliza 10 registros por banco y conserva dos registros históricos de
prueba en Banco 1, por eso el total no es exactamente 140.

#### Distribución implementada

- Relacionales: PostgreSQL (1, 4, 6), MySQL (2, 5, 7) y SQLite (3).
- No relacionales: MongoDB (8, 9, 11, 12, 14) y Redis (10).
- Grafo: Neo4j (13), con `Cliente`, `Cuenta` y `TIENE_CUENTA`.

#### Pendientes de integración del equipo

1. ✅ Hecho (Integrante 2): seeder reescrito para no abortar ante filas
   inválidas (columna vacía, IdBanco fuera de rango, Saldo no numérico,
   Nro duplicado); ahora se descartan y se listan en
   `data/seed/rejected_rows.csv` con el motivo. Ver "Actualización de
   Integrante 2" más abajo para el hallazgo sobre la distribución real del
   dataset oficial frente a la tabla del enunciado.
2. ✅ Hecho (Integrante 2): esquemas de PostgreSQL, MySQL y SQLite para los
   bancos 1–7 normalizados en dos tablas (`clientes`, `cuentas`) con FK,
   verificados con datos reales cifrados/descifrados. De paso se encontraron
   y corrigieron dos bugs de cifrado (Playfair y Hill) que corrompían Saldo,
   Nombres y Apellidos; ver detalle abajo.
3. Integrante 3 debe validar MongoDB, Redis y Neo4j para los bancos 8–14,
   incluyendo consultas de defensa y evidencia de `TIENE_CUENTA`. Aviso de
   Integrante 2: al probar el seeder con el dataset oficial completo, el
   cifrado ElGamal (Banco 12) resultó extremadamente lento a escala real
   (miles de registros) porque genera un exponente aleatorio de 2048 bits en
   cada cifrado; el barrido de los 14 bancos no terminó en más de 2 minutos
   por esta causa. Conviene revisar esa implementación (por ejemplo, cifrar
   con una clave de sesión simétrica y envolverla una sola vez con ElGamal)
   antes de sembrar los bancos 8–14 con datos reales.
4. El equipo debe implementar la tabla central de ASFI en `asfi-db` y guardar
   cada saldo original, saldo convertido, tasa, timestamp, banco, cuenta y
   código de verificación.
5. El equipo debe preparar las 8 consultas exigidas por la guía, probarlas con
   datos cargados y documentar el resultado esperado.
6. Antes de entregar, el equipo debe ejecutar el flujo desde cero, revisar que
   `errores` sea 0 y limpiar datos históricos para que el conteo sea explicable.

#### Regla de integración

Los compañeros deben usar `banks-services/common/` y no crear endpoints
alternativos por banco. Para agregar o cambiar un motor, se implementa un
adaptador con `encrypted_accounts()` y `confirm()`, se conecta mediante
`BANK_STORAGE` y se conserva el contrato HTTP existente.

---

## 🟢 3.1 Actualización de Integrante 2 (bancos relacionales, 2026-09-08)

**Hallazgo sobre el dataset oficial:** el CSV entregado por el docente
(`data/dataset.csv`, 123,790 filas) NO reparte las cuentas según la
proporción de la tabla del enunciado (Unión 22,472, Mercantil 19,975, etc.).
En la práctica trae ~8,700–8,900 filas por banco de forma casi pareja para
los 14 bancos. Para los bancos 1–7 esto significa menos filas de las que
pide la tabla oficial (por ejemplo Banco Unión: 8,721 disponibles contra
22,472 esperadas). El seeder ya no asume la distribución del enunciado: usa
todas las filas válidas tal como vienen etiquetadas por `IdBanco` y en la
consola imprime una comparación banco por banco contra la cifra oficial para
que el equipo decida si hay que pedir el dataset completo al docente. Quien
quiera forzar el recorte a las cuotas oficiales (nunca inventa filas, solo
recorta) puede correr `--target-distribution official_1pct`.

**Bugs de cifrado corregidos en `asfi-service/crypto/ciphers.py`:**

- *Playfair (Banco 4, BCP):* la reconstrucción del texto original contaba
  posiciones entre el flujo cifrado (con relleno `X` intercalado) y el texto
  plano. Con dígitos repetidos en el Saldo el conteo se desalineaba: por
  ejemplo `"324443.5414"` volvía como `"3244.435414"` (el punto decimal
  quedaba corrido). También se perdían las mayúsculas/minúsculas de Nombres
  y Apellidos. Se reescribió para guardar de forma explícita una plantilla
  (posición de cada separador no alfanumérico), una máscara de mayúsculas y
  las posiciones exactas de relleno, de modo que el descifrado reconstruye
  el original exactamente. La fusión clásica I/J de Playfair se mantiene
  (es una propiedad conocida del algoritmo, no un defecto).
- *Hill (Banco 5, BISA):* la versión original hacía
  `.upper().replace(" ", "")` y descartaba cualquier carácter fuera de
  A-Z/0-9/'.', por lo que un nombre como `"Jorge Diego"` perdía el espacio
  para siempre (`"JORGEDIEGO"`) y un NroCuenta en notación científica con
  `+` (`"3.96E+15"`) perdía el signo. Ahora esos caracteres se preservan de
  forma literal y el caso original se restaura al descifrar.
- Verificación: round-trip exacto (cifrar → descifrar → comparar contra el
  CSV original) sobre las 61,653 filas reales de los bancos 1–7 (308,265
  campos), con 0 discrepancias reales (las únicas diferencias en Playfair
  son la fusión I/J, inherente al algoritmo).

**Esquema de bases de datos (bancos 1–7):** se separaron `clientes`
(identificación, nombres, apellidos) y `cuentas` (cuenta, saldo, código de
verificación, etc.) con clave foránea `cliente_nro`, como pedía la tarjeta
de Trello ("Tablas en bancos: Clientes, Cuentas"). El contrato HTTP/JSON de
`encrypted_accounts()`/`confirm()` no cambió (se arma con un JOIN), así que
ASFI y el resto del equipo no necesitan tocar nada. Probado con datos reales
cifrados contra PostgreSQL, MySQL/MariaDB y SQLite (motores reales, no
mocks): carga, lectura cifrada, descifrado exacto y confirmación con
actualización de saldo, todo verificado.

**Nota de plataforma:** al ejecutar el seeder y los servicios bancarios
desde este entorno de escritorio con la carpeta del proyecto en una unidad
de red montada, SQLite dio `disk I/O error` al crear el archivo dentro de
`data/`. Es una limitación de ese punto de montaje (SQLite necesita bloqueo
de archivos que la unidad de red no soporta bien), no un error del código:
en una terminal normal de Windows/WSL sobre disco local funciona sin
problema, como ya se validó en un entorno Linux con PostgreSQL, MySQL y
SQLite reales.

**Nuevo:** `scripts/queries_bancos_1_7.sql` con consultas de verificación
(conteo por banco, confirmadas vs. pendientes, integridad del código hex,
huérfanos Cliente/Cuenta, última tasa aplicada) para apoyar la auditoría de
los bancos relacionales. No reemplaza las 8 consultas oficiales del
enunciado (esas cubren los 14 bancos y son responsabilidad del equipo).

## 🔍 3.2 Revisión final contra la rúbrica (2026-09-09)

Revisión del proyecto ya mergeado, verificando el código contra motores reales
(PostgreSQL, MySQL/MariaDB, SQLite y Redis levantados de verdad con el dataset
del docente). Detalle completo en `docs/ENTREGA_FINAL.md`.

### 🔴 Bug crítico encontrado: saldos inflados en los datos cargados

Los archivos de `data/seed-docente1/` (y por lo tanto las 14 bases cargadas el
2026-09-09 a las 11:44) tienen los saldos multiplicados por hasta 10.000: se les
quitó el punto decimal. Ejemplo, cuenta Nro 9 del Banco Unión: el CSV dice
`301716.8517` y en la base quedó `3017168517.0000`. Verificado sobre 300 cuentas
del Banco 1: 283 incorrectas.

**El código actual ya está corregido**: se ejecutó `scripts/seeder.py` de hoy
sobre el mismo `data/dataset.csv` (MD5 idéntico al original) y produjo 300/300
saldos correctos. El problema es sólo que el seed nunca se regeneró después de
arreglar `shared/money.py`.

**Acción pendiente del equipo:** volver a correr el seeder y recargar las 14
bases antes de la entrega (paso 3 de `docs/ENTREGA_FINAL.md`).

### ❌ Faltaba el entregable de 40 puntos

La rúbrica pide "8 Consultas a la base de datos y preguntas (Sin IA) — 40 pts" y
no existía. Se agregó `scripts/consultas/` con una versión por motor
(PostgreSQL, MySQL, SQLite, MongoDB, Neo4j, Redis y la base central de ASFI),
un runner `ejecutar_consultas.py` que las ejecuta sobre los 14 bancos y genera
evidencia, y un README que explica cada consulta con la pregunta que responde
(para poder defenderlas sin IA).

Las 8 consultas cubren: inventario y avance, saldo USD/Bs consolidado,
consistencia banco↔ASFI, validación de los códigos hexadecimales, auditoría del
tipo de cambio y prueba del barrido paralelo, cuentas no procesadas, relación
cliente→cuenta (grafo) e integridad aritmética de la conversión.

### ➕ Esquema `Bancos` / `Cuentas` del enunciado

El enunciado define literalmente esas dos tablas; el servicio escribe en
`asfi_cuentas`. Se agregó `scripts/creacion/asfi_vistas_enunciado.sql`, que crea
la tabla real `Bancos` con las 14 entidades y la vista `Cuentas` con los nombres
y tipos exactos del enunciado, sin duplicar datos ni tocar el servicio.

### ➕ Comunicación segura entre nodos

Era un requerimiento técnico explícito ("comunicación segura entre nodos") junto
con las consideraciones de seguridad de MITM, replay y spoofing, y no estaba
implementado: cualquier proceso podía llamar a `POST /cuentas/confirmar`.

Se agregó `shared/seguridad.py`: firma HMAC-SHA256 sobre método + ruta + cuerpo,
nonce único por petición y ventana temporal de 120 s. Se conectó en
`bank_template/main.py` (middleware) y en `asfi-service/main.py` (firma de las
peticiones salientes), **protegido por la variable `ASFI_HMAC_SECRET`**: sin ella
el sistema se comporta exactamente igual que antes. Verificado corriendo el
barrido en los dos modos con idéntico resultado (2400/2400, 0 errores).

`scripts/demo_seguridad.py` demuestra los cuatro escenarios en vivo: petición
legítima aceptada; spoofing, MITM y replay rechazados con HTTP 401.

### ✅ Lo que se verificó y funciona

- Barrido paralelo con 4 bancos en 4 motores distintos: 3.200 transacciones,
  3.200 confirmadas, 0 errores, 1,13 s.
- Una sola cotización del BCB para todo el barrido (ventana de 0,75 s).
- `saldo_bs = saldo_usd × tipo_cambio` exacto en las 3.200 cuentas, 0 descuadres.
- Consistencia banco↔ASFI: 3.200 comparadas, 0 diferencias.
- 3.200 códigos de verificación, 0 con formato inválido, 0 duplicados.

### ⚠️ Notas operativas

- Si el barrido falla con `BrokenProcessPool`, usar `ASFI_CRYPTO_WORKERS=0`
  (descifrado en hilos). Ocurrió al probar en un entorno con pocos recursos.
- `bank_template/main.py` importa los seis adaptadores de forma incondicional,
  así que un banco no arranca si falta algún driver aunque no lo use. No es
  bloqueante (están todos en `requirements.txt`), pero conviene saberlo.

## 🪟 3.3 Windows nativo, reinicio de la demostración y tablero (2026-09-09)

Segunda pasada de la revisión final. El objetivo fue que el proyecto se corra
**enteramente en Windows**, que la demostración se pueda **repetir desde cero**
las veces que haga falta, y que haya **una sola pantalla** desde donde ver el
estado real de la rúbrica y lanzar cada paso.

### 🔴 Bug crítico: el proyecto no arrancaba en Windows

`asfi-service/main.py` y `scripts/seeder.py` importaban `fcntl` y `resource`,
que **no existen en Windows**. El servicio ASFI no levantaba y el seeder moría
en el import. Todo el pipeline estaba efectivamente roto fuera de Linux.

**Solución:** `shared/portable.py`, una capa fina que resuelve las dos cosas en
los dos sistemas operativos:

- **Bloqueo de archivos**: en Windows usa `LockFileEx` / `UnlockFileEx` de
  `kernel32` vía `ctypes` (exclusivo `0x2`, no bloqueante `0x1`); en Unix usa
  `fcntl.flock`. Misma API para quien la llama: `bloquear(archivo, EXCLUSIVO)`
  y `bloquear(archivo, COMPARTIDO, bloqueante=False)`.
- **Memoria máxima del proceso**: en Windows por `GetProcessMemoryInfo`, en
  Unix por `resource.getrusage`. El seeder reporta
  `metrics.memoria_principal_max_mib` igual en ambos.
- **`autoprueba()`**: se ejerce sola y la usa `Verificar-Entorno.ps1`.

Archivos parchados: `asfi-service/main.py`, `scripts/seeder.py`,
`scripts/load_common.py`, `scripts/benchmark_conversion.py` (este último
escribía en `/tmp/…`, ruta que no existe en Windows; ahora escribe en
`docs\benchmark-conversion.json`).

Se verificó que el pipeline completo sigue dando **2400/2400 con 0 errores**
después del cambio, y que la rama de Windows manda los flags correctos a
`LockFileEx`.

### ➕ Scripts de PowerShell (`scripts\windows\`)

| Script | Para qué |
|---|---|
| `Verificar-Entorno.ps1` | 8 chequeos previos: Python, Docker, motores, imports Unix, `portable.autoprueba()`, puertos, dataset, dependencias |
| `Reiniciar-Demo.ps1` | **Deja todo como recién instalado.** 8 pasos: detener servicios → `docker compose down -v` → limpiar `data\seed` y SQLite → levantar contenedores → esperar motores → sembrar → **verificar saldos** → cargar 14 bancos + tablas del enunciado |
| `Levantar-Servicios.ps1` | Levanta BCB + 14 bancos + ASFI y guarda los PID en `data\.servicios.pids` |
| `Detener-Servicios.ps1` | Los baja usando ese archivo, con red de seguridad por línea de comandos |
| `Abrir-Tablero.ps1` | Abre el tablero de entrega en el navegador |

`Reiniciar-Demo.ps1` tiene tres modos: normal, `-SoloLimpiar` (apaga y borra sin
reconstruir) y `-Rapido` (siembra y carga sólo los bancos 1, 2, 3 y 10 — un
motor de cada tipo — para ensayar sin esperar el dataset completo).

El paso 7 es un **candado**: si `verificar_saldos.py` encuentra que un saldo
descifrado no coincide con `data\dataset.csv`, el script se detiene y **no
carga las bases**. Así el bug de los saldos inflados no puede volver a entrar
sin que nos enteremos.

### ➕ Tablero de entrega (`scripts\tablero\`)

`servidor.py` + `tablero.html`: un FastAPI en `http://127.0.0.1:8090` con cuatro
pestañas.

- **Rúbrica** — los 7 ítems con su estado **consultado en vivo contra las bases**
  (no una lista escrita a mano): cuántos bancos tienen datos, cuántas cuentas,
  cuántas convertidas, si el tipo de cambio fue único, si hay descuadres
  aritméticos, si los códigos de verificación son válidos y únicos, si el grafo
  de Neo4j está poblado. Cada ítem trae su puntaje y cómo demostrarlo.
- **Ejecutar** — un botón por cada paso de la demostración (verificar entorno,
  reiniciar, levantar servicios, barrido, 8 consultas, demo de seguridad,
  acelerar/restaurar el BCB) con la salida en vivo en una consola.
- **Requisitos** — los requerimientos del enunciado con su estado.
- **Seguridad** — las cuatro amenazas y su mitigación.

**Decisiones de seguridad del tablero** (ejecuta comandos, así que se acotó a
propósito):

- Escucha **sólo en `127.0.0.1`**: no es accesible desde la red.
- **Lista blanca fija** de acciones (`ACCIONES`). No existe forma de mandarle un
  comando arbitrario: el navegador manda una clave, no una línea de comandos.
- **Sin `shell=True`** y **sin argumentos que vengan del navegador**.
- **Chequeo de mismo origen** en los POST (403 si no).
- Una acción a la vez.

Probado: clave inventada → 404, otro origen → 403, acción de Windows en Linux →
400, y la ejecución real transmite la salida y propaga el código de salida.

La lectura del estado se hace en paralelo (`ThreadPoolExecutor`, 15 hilos), así
que la rúbrica carga en ~9 s incluso con motores caídos, en vez de sumar el
timeout de cada uno.

### ➕ `docs\ENTREGA_FINAL.md`

Documento único de entrega, reescrito: qué pide el enunciado, qué construimos,
instalación desde cero en Windows, el comando de reinicio, un guion de
demostración de 10 pasos con qué decir en cada uno, la tabla de la rúbrica
(130 pts) con cómo se demuestra cada ítem, el mapa de archivos, 10 preguntas
probables con su respuesta, y una tabla de qué se probó de verdad y qué no.

### ⚙️ Correcciones menores de esta pasada

- `asfi_vistas_enunciado.sql` fallaba en una base recién creada
  (`relation "asfi_cuentas" does not exist`). Ahora incluye el DDL idempotente
  de las tablas base; probado en base vacía y en base cargada.
- `Verificar-Entorno.ps1` daba OK falso al buscar imports de Unix (los patrones
  con `\` no coincidían). Se reemplazó por `Get-ChildItem -Recurse -Filter *.py`;
  se comprobó inyectando un `import fcntl` a propósito, y lo detecta.
- `Get-NetTCPConnection` no está en todas las instalaciones: se reemplazó por
  `[System.Net.NetworkInformation.IPGlobalProperties]`.
- El SQL del enunciado se pasa al contenedor con `docker cp` en vez de por un
  pipe: PowerShell podía alterar la codificación y el script tiene acentos.
- `04_mongodb.js` tenía `const db = db.getSiblingDB(...)` (la variable se
  sombreaba a sí misma). Renombrada a `BD`.

## 🚀 4. Ruta de Trabajo Recomendada (Roadmap de Inicio)

Para arrancar el desarrollo de forma ordenada y sin bloqueos entre integrantes:

### **Paso 1 (Tu rol - Inmediato): Motor Criptográfico Modular y Gestor de Llaves (`asfi-service/crypto/`)**
> **¿Por qué empezar aquí?** Porque el Integrante 2 necesita los métodos de cifrado para crear el script de poblamiento (`seeder.py`), y tú los necesitas en ASFI para el descifrado durante el barrido.
- Implementar la interfaz base común `BaseCipher` (`encrypt`, `decrypt`).
- Completar los 14 algoritmos (César, Atbash, Vigenère, Playfair, Hill, DES, 3DES, Blowfish, Twofish, AES, RSA, ElGamal, ECC, ChaCha20).
- Diseñar el `KeyManager` y la fábrica de algoritmos `CipherFactory`.

### **Paso 2: Microservicio BCB (`bcb-service/`) y Docker Compose**
- Asegurar que el servicio del BCB exponga el endpoint de tipo de cambio y permita configurar el tiempo de fluctuación (ej. cada 1s, 3s, 180s).
- Levantar los contenedores de base de datos base (Postgres, MySQL, Mongo, Neo4j) en `docker-compose.yml`.

### **Paso 3: Script de Poblamiento (`scripts/seeder.py`)**
- Leer el archivo CSV/Excel del dataset (muestra del 1%).
- Cifrar los registros usando `asfi-service/crypto/` e insertarlos en las 14 bases de datos.

### **Paso 4: APIs Bancarias (`banks-services/`)**
- Crear la plantilla genérica de API bancaria con endpoints:
  - `GET /api/banco/cuentas/cifradas`
  - `POST /api/banco/cuentas/confirmar` (recibe el código hexadecimal de 8 caracteres y actualiza el estado/saldo).

### **Paso 5: Orquestador de Barrido Paralelo en ASFI (`asfi-service/`)**
- Implementar la llamada concurrente asíncrona (`asyncio` + `httpx`) hacia las 14 APIs bancarias.
- Descifrado de cuentas, conversión USD ➔ Bs con la tasa capturada del BCB, generación del código hex de 8 caracteres y persistencia en la BD central de ASFI + Log de auditoría.

### Prueba de una API bancaria
Desde `banks-services/`, después de instalar `requirements.txt`:

```bash
BANK_ID=1 BANK_DATA_FILE=../data/seed/bank_01.jsonl uvicorn bank_template.main:app --port 8101
```

Endpoints disponibles:

- `GET /api/banco/cuentas/cifradas?offset=0&limit=100`
- `POST /api/banco/cuentas/confirmar`
