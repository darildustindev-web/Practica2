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

1. Integrante 2 debe revisar los cargadores y adaptar el seeder para la muestra
   oficial del 1%, incluyendo validación de filas inválidas sin perder el
   procesamiento de las filas correctas.
2. Integrante 2 debe verificar los esquemas y consultas de PostgreSQL, MySQL y
   SQLite para los bancos 1–7.
3. Integrante 3 debe validar MongoDB, Redis y Neo4j para los bancos 8–14,
   incluyendo consultas de defensa y evidencia de `TIENE_CUENTA`.
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
