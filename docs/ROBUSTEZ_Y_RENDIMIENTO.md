# Carga robusta, paralelismo y recuperación

## Ejecución

Desde la raíz del proyecto, usando el entorno `.venv` y los contenedores de
`docker-compose.yml`:

```bash
.venv/bin/python scripts/seeder.py data/dataset.csv --output-dir data/seed --workers 4 --batch-size 500
.venv/bin/python scripts/load_all.py --source-dir data/seed --workers 4 --batch-size 1000
```

El primer comando valida y cifra; el segundo inserta en los seis motores usando
hasta cuatro hilos, con una conexión independiente por banco. También siguen
funcionando `load_postgres.py`, `load_mysql.py`, `load_sqlite.py`, `load_mongo.py`,
`load_redis.py` y `load_neo4j.py`, con la ruta de origen como argumento posicional, y
`--database-url`, `--batch-size` y `--bank-id` como opciones. Ejemplo:

```bash
.venv/bin/python scripts/load_sqlite.py data/seed/bank_03.jsonl --database-url sqlite:///data/bank_03.sqlite
```

`load_all.py --banks 1,3,13` permite seleccionar bancos. Las conexiones se pueden
sobrescribir con `BANK_01_DATABASE_URL`, etc. El script NoSQL antiguo ahora llama
al cargador común y utiliza Neo4j para el banco 13; se retiró `--reset` para no
mezclar poblamiento y borrado de datos.

Para la consolidación oficial, arrancar ASFI con PostgreSQL:

```bash
ASFI_DATABASE_URL=postgresql://asfi_user:asfi_password@127.0.0.1:5434/asfi_db \
ASFI_CRYPTO_WORKERS=4 ASFI_BATCH_SIZE=500 \
.venv/bin/uvicorn main:app --app-dir asfi-service --host 127.0.0.1 --port 8000
```

`bash scripts/run_all_demo.sh` carga los bancos en paralelo, levanta las APIs y
utiliza PostgreSQL para ASFI. Si se arranca ASFI directamente sin configurar la
URL, utiliza `data/asfi.sqlite` como alternativa local explícita en el código.
La tabla `asfi_cuentas` se crea al iniciar el primer barrido.

**Cada dataset distinto debe usar bases bancarias y una consolidación nuevas o
preparadas expresamente para esa evaluación.** La recarga es insert-only: una
referencia existente conserva su contenido y confirmación. No sirve para
reemplazar cuentas de un dataset anterior. `cargadas` cuenta registros enviados
correctamente al motor, incluidos los ya existentes; no significa nuevas filas
insertadas. No se borraron las bases del proyecto durante este trabajo.

## Validación y memoria

- CSV UTF-8, con BOM opcional, siete columnas obligatorias, cabecera sin duplicados.
- Una cuenta por línea física. Campos CSV con saltos de línea no están admitidos:
  se rechazan para recuperar la lectura tras comillas rotas sin absorber las
  siguientes cuentas. Máximo 32 KiB por fila y 1024 caracteres por campo.
- Identificador `Nro` entero positivo BIGINT; se normalizan ceros iniciales y se
  detectan duplicados con una tabla SQLite temporal en disco. Los números de
  cuenta e identificaciones se conservan como texto.
- Banco entre 1 y 14, campos obligatorios no vacíos, sin controles ni errores de
  codificación. Los fallos de cifrado se rechazan por registro.
- Importes con `Decimal`, finitos y compatibles con `DECIMAL(18,4)`. Se aceptan
  negativos porque el enunciado no prohíbe saldos deudores. No se redondean
  silenciosamente importes de entrada con más de cuatro decimales significativos.
- Punto decimal; coma decimal si no hay punto; miles estrictamente agrupados.
  `1.234` significa 1,234 unidades, no 1234. Formatos ambiguos como `1.000,25`
  se rechazan. La coma dentro de un CSV debe estar entre comillas.
- El producto USD × tasa se redondea a cuatro decimales con `ROUND_HALF_EVEN` y
  vuelve a comprobarse el rango. Se conservan las mismas reglas en seeder,
  ASFI y confirmaciones bancarias.
- JSONL se lee por registros limitados a 512 KiB. JSON roto, campos ausentes y
  bancos incorrectos se reportan sin detener los registros siguientes. Los
  errores SQL de datos se aíslan subdividiendo el lote; un fallo de
  infraestructura detiene ese cargador, informa el error y admite recarga.

El CLI del seeder no acumula el dataset: mantiene como máximo dos lotes pendientes
por proceso. El muestreo opcional `--target-distribution official_1pct --seed 42`
utiliza selección reproducible en disco. `load_rows()` se conserva sólo como
utilidad para muestras pequeñas y pruebas; sí devuelve listas en memoria.

Los archivos se preparan en un directorio temporal y se publican al completar la
carga. Un bloqueo compartido con los cargadores impide leer durante la publicación.
Un error de cabecera o infraestructura no publica la nueva generación. Si el
proceso se mata precisamente durante el reemplazo de archivos, se debe repetir
el seeder antes de cargar; la publicación de los 14 archivos no es una única
transacción de filesystem.

## Paralelismo y dólar variable

El seeder utiliza procesos para cifrar. ElGamal emplea exponenciación modular
nativa de PyCryptodome, conservando módulo, generador y tamaño de exponente;
su aleatoriedad ahora procede de `secrets`. Los cifrados clásicos conservan
acentos y Unicode; Playfair conserva I y J por separado en su matriz 6×6.

ASFI consulta los bancos concurrentemente con `asyncio`. Descifra sublotes en
procesos (`ASFI_CRYPTO_WORKERS`, hasta cuatro sublotes por banco); persistencia
y escritura de auditoría se realizan en hilos. Con `ASFI_CRYPTO_WORKERS=0` también
el descifrado pasa a hilos, útil para pruebas. No se crea un hilo por cuenta.

Las APIs mantienen `offset/limit` y agregan `after` y `next_cursor`. ASFI utiliza
cursores para evitar recorrer todos los registros anteriores en cada página.
Redis tiene un índice ordenado y lectura por pipeline en lugar de escanear y
ordenar todas las claves repetidamente. Los lotes HTTP tienen máximo 1000 cuentas.

La cotización se consulta **después del descifrado, para cada lote nuevo** y queda
asociada al timestamp de conversión de ese lote. Se verifica rango 5.9601–7.9599,
positividad, cuatro decimales y vigencia del timestamp según el intervalo BCB
(con tolerancia de cinco segundos). Una cotización inválida detiene ese banco
sin convertir con un valor inventado. Los demás bancos terminan su trabajo.

Un reintento conserva la tasa, fecha y código de la operación original; no
recalcula con el dólar nuevo. La granularidad temporal es el lote, no cada cuenta.
Si el docente exige otra granularidad, ésta es la política que debe ajustarse.

## Confirmaciones y recuperación

`POST /api/banco/cuentas/confirmar` acepta un objeto individual o una lista.
Para listas retorna `{"resultados": [...]}` con resultado por cuenta; un elemento
inválido no rechaza los válidos. ASFI comprueba código, saldo y tasa de cada recibo.

La secuencia es:

1. Descifrar y validar el lote; consultar la tasa actual.
2. Consolidar los datos personales descifrados, saldo USD, saldo Bs., tasa,
   timestamps, código y huella del origen en `asfi_cuentas`, estado `PENDIENTE`.
3. Enviar al banco exactamente la operación persistida.
4. Verificar el recibo, marcar `CONFIRMADA` y escribir auditoría del lote.

Las confirmaciones SQL usan transacciones y bloqueo de filas; MongoDB usa
actualizaciones condicionales; Redis usa Lua; Neo4j toma un bloqueo de escritura
antes de comprobar y actualizar la cuenta. Un código igual con saldo o tasa
diferentes es un conflicto. Los reintentos HTTP de fallos transitorios son tres
intentos totales, con espera creciente y el mismo cuerpo.

Si la respuesta se pierde después de la confirmación bancaria, el próximo
barrido reutiliza el pendiente. Las confirmadas se reconocen sin descifrarlas ni
convertirlas otra vez. Una huella de origen distinta exige conciliación. Los
bloqueos de archivo y el advisory lock de PostgreSQL evitan barridos simultáneos
sobre la misma consolidación. Cargar datasets mientras se convierten cuentas no
forma parte del flujo admitido: primero terminar la carga, luego iniciar ASFI.

`asfi_cuentas` es la fuente durable de consolidación; el log JSONL es su registro
por lotes. Si una caída ocurre entre el commit y la escritura del log, se puede
reconstruir el estado consolidado en un archivo nuevo:

```bash
.venv/bin/python scripts/export_asfi_audit.py \
  --database-url postgresql://asfi_user:asfi_password@127.0.0.1:5434/asfi_db \
  --output /tmp/auditoria-reconstruida.jsonl
```

La exportación refleja el estado actual de las cuentas consolidadas; no recupera
un historial de intentos que nunca llegó a persistirse. Los errores de entrada
quedan en los reportes de rechazo y los errores operativos, en el log y la respuesta.

## Resultados medidos en esta máquina

Dataset local: 123.790 filas; 123.785 válidas cifradas y 5 rechazadas.

| Prueba | Resultado |
|---|---:|
| Seeder, 4 procesos, antes de acelerar ElGamal | 88,44 s |
| Seeder, 4 procesos, ElGamal nativo | 27,82 s; 4.449,82 filas/s |
| Carga de 123.785 cuentas en 14 SQLite temporales | 2,46 s |
| Conversión completa con 14 APIs ASGI, 4 procesos y cursores | 38,94 s; 123.785 confirmaciones; 0 errores |
| Segundo barrido sobre las mismas cuentas | 10,10 s; 123.785 reconocidas; 0 conversiones nuevas |

Son mediciones separadas en esta máquina, no garantías para otra infraestructura.
El benchmark integral usa SQLite y transporte ASGI dentro del proceso: **no mide
latencia HTTP de red ni rendimiento combinado de los seis motores Docker**.
Se verificaron separadamente lotes, reintentos, conflictos y cursores con
PostgreSQL, MySQL, MongoDB, Redis y Neo4j reales en espacios de prueba aislados.
No se ha medido un dataset de 12 millones de registros.

Los reportes de referencia están en `docs/benchmark-resultados.json`.
Para repetir el benchmark sin tocar los bancos del proyecto:

```bash
.venv/bin/python scripts/benchmark_conversion.py \
  --source-dir data/seed --workers 4 --output /tmp/benchmark.json
```

La carga genera `metrics.json`, `rejected_rows.csv`,
`bank_XX.load-rejected.jsonl` y `load-metrics.json`. ASFI responde con tiempos,
conteos, errores y rendimiento por banco. La memoria principal máxima se mide
con `ru_maxrss` en el seeder; no suma la memoria de todos los procesos hijos.

## Pruebas

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/unit

# Motores Docker disponibles; crea y limpia únicamente datos propios de prueba.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 RUN_DB_TESTS=1 .venv/bin/python -m pytest -q \
  tests/unit tests/test_bcb_service.py \
  tests/test_nosql_banks_8_14.py::TestCryptoAlgorithms
```

La segunda selección pasó 24 pruebas y 50 subpruebas. No se ejecutó la suite
histórica completa: algunas pruebas de Neo4j borran el grafo existente y usan
conteos fijos de una muestra anterior. Las nuevas pruebas de integración usan
esquemas PostgreSQL, una base MySQL, una base MongoDB, un prefijo Redis y cuentas
Neo4j propios; su limpieza no borra los datos bancarios del proyecto.

## Panel de presentación local

Con los contenedores de bases de datos activos, inicia las APIs y el panel sin
cargar ni borrar cuentas:

```bash
.venv/bin/python scripts/run_panel.py
```

Abre `http://127.0.0.1:8200/panel`. El comando reutiliza servicios que ya responden;
Ctrl+C detiene solamente los procesos que inició. Los detalles de arranque se
escriben en `data/service-logs/`. Si BCB y el panel ya están activos, puede usarse
`--banks-only` para completar el arranque de los bancos.

El panel consulta primero las APIs y sus bases: el botón de barrido se habilita
cuando los bancos configurados y BCB están disponibles. Los 14 errores
`ConnectError` observados inicialmente correspondían a APIs bancarias apagadas,
no a 14 cuentas inválidas. El endpoint original de ASFI mantiene la posibilidad
de ejecutar un barrido parcial para pruebas de fallos de bancos.

El panel permite cambiar el intervalo BCB, observar cotizaciones reales, seguir
las etapas y conteos del barrido y comparar cuentas de ASFI directamente con el
banco. La telemetría en vivo corresponde al proceso ASFI actual (usar un worker
Uvicorn para la demostración); se reinicia al reiniciar el servicio. La opción
«Consultar consolidación» lee las cuentas persistentes.

Los bancos SQL adaptan de forma aditiva el esquema antiguo de cuentas con datos
de cliente embebidos: crean y relacionan `clientes`, conservan los campos
anteriores y no borran los saldos ni los códigos de confirmación.


## Recotización y recuperación

El botón del panel y POST /api/asfi/ejecutar-conversion inician un nuevo barrido: las cuentas confirmadas se recalculan desde el USD original, con cotización BCB por lote y código hexadecimal nuevo. ASFI archiva la versión anterior en asfi_historial antes de preparar la siguiente, dentro de la misma transacción. Las pendientes conservan su operación hasta recuperar la confirmación; el siguiente barrido las recotiza. No se eliminan clientes ni datos cifrados.

Los bancos aceptan una recotización explícita sólo si su fecha es posterior y su código distinto; los reintentos con el código vigente deben coincidir en saldo y tasa. Una operación antigua no puede sobrescribir una más reciente. ASFI verifica el recibo de cada cuenta. El panel permite consultar directamente al banco para comprobar importe, tasa y código contra ASFI.

El modo automático del panel requiere mantener la pestaña abierta. Espera a terminar cada barrido, agrupa los cambios de cotización ocurridos durante éste y comienza el siguiente con cotizaciones actuales por lote. No promete procesar todo el dataset cada segundo; no solapa barridos y se detiene ante errores.
