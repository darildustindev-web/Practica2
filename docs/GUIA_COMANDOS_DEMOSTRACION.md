# Guía de demostración en terminal: bancos, ASFI y errores

## Ruta rápida: bases ya cargadas

Si la prueba final ya terminó, **no volver a ejecutar el seeder ni el cargador** para hacer consultas. En la máquina de esta demostración el dataset completo está preparado en `data/seed`.

```bash
cd /home/daril/ProyectosDistribuidos/Practica2
docker compose up -d
.venv/bin/python scripts/run_panel.py
```

Mantener esa terminal abierta. Si el lanzador indica «ya disponible», está reutilizando servicios existentes. En otra terminal:

```bash
cd /home/daril/ProyectosDistribuidos/Practica2
curl -fsS http://127.0.0.1:8200/api/panel/servicios | .venv/bin/python -m json.tool
.venv/bin/python scripts/demo_terminal.py estado
```

Luego seguir los apartados 4–10 para consultar cada motor y comprobar ASFI. El apartado «Preparar desde cero con el dataset del docente» está al final: usarlo únicamente cuando corresponda cargar datos nuevos.

## 1. Preparación y qué demuestra el sistema

Todos los comandos de esta guía se ejecutan desde:

```bash
cd /home/daril/ProyectosDistribuidos/Practica2
```

El flujo es: dataset → validación → cifrado → bases bancarias → lectura y descifrado por ASFI → cotización BCB por lote → confirmación bancaria → comprobación del recibo → consolidación ASFI y auditoría.

El saldo original en USD se conserva. Cada nueva conversión calcula `USD × tasa`, con cuatro decimales, y tiene un código hexadecimal de ocho caracteres. Banco y ASFI deben coincidir en saldo Bs, tasa y código. Un reintento pendiente conserva su operación original; un nuevo barrido recotiza las confirmadas. Los bancos trabajan concurrentemente; el descifrado utiliza procesos y las operaciones bloqueantes utilizan hilos. Los barridos completos no se solapan.

**Las consultas de esta guía son de lectura**, salvo los comandos señalados como inicio de servicios, generación/carga, modificación del intervalo o ejecución de barridos.

## 2. Iniciar y detener

En una terminal, iniciar los contenedores y las APIs:

```bash
docker compose up -d
.venv/bin/python scripts/run_panel.py
```

Dejarla abierta. El nombre del lanzador contiene «panel», pero permite trabajar exclusivamente por terminal. Reutiliza servicios existentes y no carga datos automáticamente.

En otra terminal, comprobar disponibilidad y cantidad de cuentas:

```bash
curl -fsS http://127.0.0.1:8200/api/panel/servicios | .venv/bin/python -m json.tool
docker compose ps
.venv/bin/python scripts/demo_terminal.py estado
```

Para detener las APIs iniciadas por el lanzador: `Ctrl+C` en su terminal. Para pausar las bases conservando los contenedores:

```bash
docker compose stop
```

**No usar `docker compose down` como rutina de demostración:** actualmente las bases SQL de los bancos no tienen volúmenes declarados; eliminar sus contenedores puede perder sus datos. `down -v` también elimina los volúmenes nombrados. ASFI local y Banco 3 se almacenan en archivos del proyecto.

## 3. Mapa de bancos

Los puertos API son `8100 + IdBanco`. Las cantidades son las verificadas con el dataset actual; cambiarán con el dataset del docente.

| ID | Banco | Motor | Base / archivo | API | Cuentas actuales |
|---:|---|---|---|---:|---:|
| 1 | Unión | PostgreSQL | `bank_union` | 8101 | 8721 |
| 2 | Mercantil Santa Cruz | MySQL | `bank_mercantil` | 8102 | 8830 |
| 3 | Nacional de Bolivia | SQLite | `data/bank_03.sqlite` | 8103 | 8767 |
| 4 | Crédito de Bolivia | PostgreSQL | `bank_bcp` | 8104 | 8885 |
| 5 | BISA | MySQL | `bank_bisa` | 8105 | 8785 |
| 6 | Ganadero | PostgreSQL | `bank_ganadero` | 8106 | 8793 |
| 7 | Económico | MySQL | `bank_economico` | 8107 | 8872 |
| 8 | Prodem | MongoDB | `bank_prodem` | 8108 | 8877 |
| 9 | Solidario | MongoDB | `bank_solidario` | 8109 | 8817 |
| 10 | Fortaleza | Redis | `DB 0; prefijo bank:10` | 8110 | 8779 |
| 11 | FIE | MongoDB | `bank_fie` | 8111 | 8910 |
| 12 | PYME de la Comunidad | MongoDB | `bank_pyme` | 8112 | 8982 |
| 13 | Desarrollo Productivo | Neo4j | `neo4j` | 8113 | 8902 |
| 14 | Nación Argentina | MongoDB | `bank_argentina` | 8114 | 8865 |

Total actual: **123.785 cuentas**. El valor «Leídas» de un barrido es lo que recorrió esa ejecución, no una consulta independiente del inventario.

## 4. Consultar cualquier banco por API

Ejemplo para Unión; cambiar `BANCO` por cualquier ID del 1 al 14:

```bash
BANCO=1
PUERTO=$((8100 + BANCO))
curl -fsS "http://127.0.0.1:$PUERTO/api/banco/info" | .venv/bin/python -m json.tool
curl -fsS "http://127.0.0.1:$PUERTO/api/banco/cuentas/cifradas?offset=0&limit=5" | .venv/bin/python -m json.tool
```

La respuesta incluye `total` y una página de `cuentas`. `Saldo`, nombres y otros campos originales están cifrados: es lo esperado. `Nro` es la referencia interna que se utiliza para verificar; **no confundirla con NroCuenta**, que puede estar cifrado.

Obtener automáticamente una referencia real y consultar su resultado:

```bash
CUENTA=$(curl -fsS "http://127.0.0.1:$PUERTO/api/banco/cuentas/cifradas?limit=1" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["cuentas"][0]["Nro"])')
echo "Banco $BANCO, referencia $CUENTA"
curl -fsS "http://127.0.0.1:$PUERTO/api/banco/cuentas/$CUENTA" | .venv/bin/python -m json.tool
```

Si el banco está vacío, el comando que selecciona la primera cuenta no aplica: consultar primero `total`. Después de convertir, revisar `SaldoBs`, `TipoCambio`, `CodigoVerificacion` y `FechaConversion`. El campo `Estado` del adaptador no es por sí solo la prueba de consistencia; usar el verificador del apartado 10.

## 5. PostgreSQL: bancos 1, 4 y 6

Entrar al banco elegido:

Banco 1:

```bash
docker exec -it bank1-union-db psql -U union_user -d bank_union
```

Banco 4:

```bash
docker exec -it bank4-bcp-db psql -U bcp_user -d bank_bcp
```

Banco 6:

```bash
docker exec -it bank6-ganadero-db psql -U ganadero_user -d bank_ganadero
```

Dentro de `psql`:

```sql
\dt
\d cuentas
SELECT COUNT(*) AS total FROM cuentas;
SELECT nro, id_banco, saldo_bs, tipo_cambio, codigo_verificacion, convertido_at
FROM cuentas ORDER BY nro LIMIT 5;
SELECT nro, saldo AS saldo_usd_cifrado, saldo_bs, tipo_cambio, codigo_verificacion
FROM cuentas WHERE nro = 'REFERENCIA';
SELECT c.nro, cl.identificacion, cl.nombres, cl.apellidos, c.nro_cuenta
FROM cuentas c JOIN clientes cl ON cl.nro = c.cliente_nro
ORDER BY c.nro LIMIT 5;
\q
```

Sustituir `REFERENCIA` por el `Nro` obtenido de la API. Los datos del cliente permanecen cifrados en el banco.

## 6. MySQL: bancos 2, 5 y 7

Estos usuarios y contraseñas corresponden al Docker Compose de desarrollo del proyecto. Introducir la contraseña cuando la solicite `-p`.

Banco 2; contraseña local: `mercantil_password`.

```bash
docker exec -it bank2-mercantil-db mysql -u mercantil_user -p bank_mercantil
```

Banco 5; contraseña local: `bisa_password`.

```bash
docker exec -it bank5-bisa-db mysql -u bisa_user -p bank_bisa
```

Banco 7; contraseña local: `economico_password`.

```bash
docker exec -it bank7-economico-db mysql -u economico_user -p bank_economico
```

Dentro de MySQL:

```sql
SHOW TABLES;
DESCRIBE cuentas;
SELECT COUNT(*) AS total FROM cuentas;
SELECT nro, id_banco, saldo_bs, tipo_cambio, codigo_verificacion, convertido_at
FROM cuentas ORDER BY nro LIMIT 5;
SELECT nro, saldo_bs, tipo_cambio, codigo_verificacion
FROM cuentas WHERE nro = 'REFERENCIA';
SELECT c.nro, cl.identificacion, cl.nombres, cl.apellidos, c.nro_cuenta
FROM cuentas c JOIN clientes cl ON cl.nro = c.cliente_nro
ORDER BY c.nro LIMIT 5;
exit
```

## 7. SQLite: Banco 3

No depende de un contenedor. Este comando usa Python incluido en el entorno y abre el archivo en modo de solo lectura:

```bash
.venv/bin/python - <<'PYCODE'
import sqlite3
with sqlite3.connect('file:data/bank_03.sqlite?mode=ro', uri=True) as db:
    print('TABLAS:', db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
    print('TOTAL:', db.execute('SELECT count(*) FROM cuentas').fetchone()[0])
    for row in db.execute('SELECT nro,saldo_bs,tipo_cambio,codigo_verificacion,convertido_at FROM cuentas ORDER BY nro LIMIT 5'):
        print(row)
PYCODE
```

Si tienes instalada la consola `sqlite3`:

```bash
sqlite3 -readonly -header -column data/bank_03.sqlite
```

Dentro de esa consola:

```sql
.tables
.schema cuentas
SELECT nro, saldo_bs, tipo_cambio, codigo_verificacion FROM cuentas LIMIT 5;
.quit
```

## 8. MongoDB: bancos 8, 9, 11, 12 y 14

```bash
docker exec -it banks-nosql-db mongosh
```

Dentro de `mongosh`, seleccionar **una** base según el banco:

```javascript
// Banco 8
use bank_prodem
// Banco 9
use bank_solidario
// Banco 11
use bank_fie
// Banco 12
use bank_pyme
// Banco 14
use bank_argentina
```

Cada `use` cambia la selección; no ejecutar todos si quieres consultar solo Prodem. Luego:

```javascript
show collections
db.cuentas.countDocuments({})
db.cuentas.find({}, {_id:0,nro:1,id_banco:1,saldo_bs:1,tipo_cambio:1,codigo_verificacion:1,convertido_at:1}).sort({nro:1}).limit(5)
db.cuentas.findOne({nro:"REFERENCIA"}, {_id:0})
exit
```

## 9. Redis y Neo4j

### Redis: Banco 10

```bash
docker exec -it bank10-fortaleza-redis redis-cli
```

Dentro de Redis:

```text
SELECT 0
ZCARD bank:10:index
ZRANGE bank:10:index 0 4
HGETALL bank:10:cuenta:REFERENCIA
HGETALL bank:10:tx:REFERENCIA
QUIT
```

`ZRANGE` devuelve referencias reales. Sustituir `REFERENCIA` con una de ellas. El hash `cuenta` conserva datos originales y resultados; el hash `tx` muestra la confirmación vigente. Usar `ZCARD` para contar cuentas, no `DBSIZE`, que cuenta todas las claves.

### Neo4j: Banco 13

```bash
docker exec -it bank13-bdp-neo4j cypher-shell -u neo4j
```

Contraseña local predeterminada: `bdp_password` (si se configuró `NEO4J_AUTH`, usar la correspondiente).

```cypher
MATCH (c:Cuenta) RETURN count(c) AS total;
MATCH (c:Cuenta)
RETURN c.cuentaId AS referencia, c.saldo_bs AS saldo_bs,
       c.tipo_cambio AS tasa, c.codigo_verificacion AS codigo
ORDER BY referencia LIMIT 5;
MATCH (c:Cuenta {cuentaId:'REFERENCIA'}) RETURN properties(c);
MATCH (cl:Cliente)-[r]->(cu:Cuenta)
RETURN cl, type(r), cu LIMIT 5;
:exit
```

## 10. ASFI: dónde está la copia y cómo compararla

**Con el lanzador utilizado en esta demostración, ASFI usa `data/asfi.sqlite` por defecto.** La existencia del contenedor `asfi-db` no significa que esa ejecución esté usando PostgreSQL. `ASFI_DATABASE_URL` permite cambiar la conexión; el script antiguo `run_all_demo.sh` tiene otros valores y puertos. No mezclar ambas configuraciones durante la exposición.

Consultar la consolidación local:

```bash
.venv/bin/python - <<'PYCODE'
import sqlite3, json
with sqlite3.connect('file:data/asfi.sqlite?mode=ro', uri=True) as db:
    print('CONSOLIDACIÓN POR BANCO Y ESTADO')
    for row in db.execute('SELECT banco_id,estado,count(*) FROM asfi_cuentas GROUP BY banco_id,estado ORDER BY banco_id'):
        print(row)
    print('CINCO CUENTAS')
    for row in db.execute('SELECT banco_id,cuenta_id,saldo_usd,saldo_bs,tipo_cambio,codigo_verificacion,estado FROM asfi_cuentas ORDER BY banco_id,cuenta_id LIMIT 5'):
        print(row)
    print('VERSIONES HISTÓRICAS:',db.execute('SELECT count(*) FROM asfi_historial').fetchone()[0])
    row=db.execute('SELECT payload FROM asfi_cuentas ORDER BY banco_id,cuenta_id LIMIT 1').fetchone()
    if row:
        print('COPIA CONSOLIDADA DE UNA CUENTA:')
        print(json.dumps(json.loads(row[0]),ensure_ascii=False,indent=2))
PYCODE
```

`asfi_cuentas` guarda una fila vigente por banco y referencia, con saldo USD, Bs, tasa, código y estado. El JSON `payload` contiene `datos` con los campos descifrados del cliente/cuenta. `asfi_historial` guarda versiones anteriores al recotizar las confirmadas. Es una consolidación lógica; no es una clonación literal de las tablas de seis motores diferentes.

ASFI puede conservar referencias de pruebas anteriores si se mezclan datasets; la carga incremental no las elimina. La prueba final documentada se hizo desde bases nuevas y compara todas las referencias, no solo el total global. Ver `RESULTADO_PRUEBA_FINAL.md` para los resultados medidos.

Comparación directa y recomendada para la exposición, usando las variables del apartado 4:

```bash
.venv/bin/python scripts/demo_terminal.py verificar "$BANCO" "$CUENTA"
```

Debe mostrar **COINCIDE**, los valores de ASFI y del banco y estas verificaciones verdaderas: `saldo`, `tasa`, `codigo`, `calculo`, `confirmada`. El código se compara junto con banco y cuenta: no debe presentarse como un identificador global infaliblemente único, pues ocho caracteres tienen un espacio finito.

También se puede consultar por HTTP:

```bash
curl -fsS "http://127.0.0.1:8200/api/panel/verificar?banco=$BANCO&cuenta=$CUENTA" | .venv/bin/python -m json.tool
```

Si ASFI fue configurada explícitamente para el PostgreSQL del Compose:

```bash
docker exec -it asfi-db psql -U asfi_user -d asfi_db
```

Dentro de `psql`:

```sql
\dt
SELECT banco_id, estado, count(*) FROM asfi_cuentas GROUP BY banco_id, estado ORDER BY banco_id;
SELECT banco_id, cuenta_id, saldo_usd, saldo_bs, tipo_cambio, codigo_verificacion, estado FROM asfi_cuentas LIMIT 5;
SELECT payload::json->'datos' FROM asfi_cuentas LIMIT 1;
SELECT count(*) FROM asfi_historial;
\q
```

Si no existen esas tablas, puede ser una base que esta ejecución no utiliza; no crearlas manualmente para hacer que la consulta funcione.

## 11. Demostrar el dólar variable y medir tiempos

Modificar el intervalo de BCB y consultar la tasa:

```bash
.venv/bin/python scripts/demo_terminal.py intervalo 1
curl -fsS http://127.0.0.1:8001/api/bcb/tipo-cambio | .venv/bin/python -m json.tool
```

Ejecutar un barrido **actualiza saldos Bs, tasas, códigos e historial**:

```bash
.venv/bin/python scripts/demo_terminal.py ejecutar
```

Verificar la cuenta elegida y anotar tasa, saldo Bs y código. Ejecutar otro barrido y verificar la misma referencia:

```bash
.venv/bin/python scripts/demo_terminal.py verificar "$BANCO" "$CUENTA"
.venv/bin/python scripts/demo_terminal.py ejecutar
.venv/bin/python scripts/demo_terminal.py verificar "$BANCO" "$CUENTA"
```

Alternativa para medir dos consecutivos y guardar su salida:

```bash
mkdir -p data/evidencias
set -o pipefail
.venv/bin/python scripts/demo_terminal.py ejecutar --barridos 2 | tee "data/evidencias/barridos-$(date +%Y%m%d-%H%M%S).log"
```

El tiempo total es de pared; no sumar los tiempos de todos los bancos, porque trabajan concurrentemente. La tasa se consulta por lote: diferentes cuentas pueden tener tasas distintas dentro de un mismo barrido. Que BCB cambie cada segundo no significa que 123.785 cuentas se actualicen todas en un segundo. Los pendientes conservan su cotización hasta recuperarse; el barrido siguiente los recotiza.

## 12. ¿Existen logs? Sí, en varias etapas

| Archivo | Qué permite demostrar | Identificación / causa |
|---|---|---|
| `data/seed/rejected_rows.csv` | Filas rechazadas antes del cifrado | `linea`, `Nro`, `IdBanco`, `motivo` |
| `data/seed/bank_XX.load-rejected.jsonl` | Rechazos de la carga de cada archivo | `linea`, `motivo`; banco indicado por el archivo |
| `data/seed/metrics.json` | Lecturas, cifradas, rechazadas, tiempos, workers y distribución | Resumen de generación |
| `data/seed/load-metrics.json` | Resultados por banco de la última invocación de carga | No necesariamente incluye los 14 si se cargó un subconjunto |
| `data/audit.jsonl` | Confirmaciones, pendientes y errores durante el barrido | Banco, referencia, estado y `detail` cuando hay fallo |
| `data/service-logs/bank_XX.log` | Salida y errores de cada API bancaria | Solicitudes HTTP y posibles trazas del servidor |
| `data/service-logs/asfi.log` / `bcb.log` | Salida de los servicios centrales | Conexiones, arranque y errores del proceso |

Los archivos de servicio se generan cuando `run_panel.py` inicia ese proceso; si reutiliza uno iniciado de otra forma, su salida puede estar en la terminal original.

Ver los rechazos reales del dataset actual:

```bash
cat data/seed/rejected_rows.csv
cat data/seed/metrics.json
cat data/seed/load-metrics.json
```

Ver fallos de carga de un banco; un archivo vacío significa que esa carga no registró rechazos:

```bash
cat data/seed/bank_04.load-rejected.jsonl
```

Ver errores acumulados del barrido o filtrar bancos:

```bash
.venv/bin/python scripts/demo_terminal.py errores
.venv/bin/python scripts/demo_terminal.py errores --bancos 1 2 6 7
```

**Son históricos:** un error anterior permanece en auditoría aunque la cuenta se haya recuperado después. Para el resultado del último barrido del servidor, usar:

```bash
.venv/bin/python scripts/demo_terminal.py estado
```

Ver actividad en vivo (`Ctrl+C` detiene la visualización):

```bash
tail -n 10 -f data/audit.jsonl
tail -n 30 -f data/service-logs/asfi.log
```

Ejecutar cada `tail` en una terminal distinta si se necesitan ambos simultáneamente.

Filtrar todos los eventos de una cuenta sin cargar el archivo completo en memoria:

```bash
BANCO=1
# CUENTA debe contener una referencia válida, obtenida antes de la API.
.venv/bin/python - "$BANCO" "$CUENTA" <<'PYCODE'
import sys,json
bank=int(sys.argv[1]);ref=sys.argv[2]
with open('data/audit.jsonl') as source:
    for line in source:
        try:r=json.loads(line)
        except ValueError:continue
        if r.get('banco_id')==bank and str(r.get('cuenta_id'))==ref:
            print(json.dumps(r,ensure_ascii=False))
PYCODE
```

## 13. ¿Se explica por qué un dato no se procesó?

Sí, según la etapa:

- CSV: motivo como saldo inválido, referencia duplicada, banco fuera de rango, columnas incorrectas o fila demasiado grande. La fila se excluye antes de cifrar/cargar; las válidas continúan.
- Carga: el archivo de rechazos informa línea y motivo. Los errores de datos aislables no descartan el resto del lote. Un fallo de infraestructura detiene esa carga, en lugar de etiquetar todas las filas como datos inválidos.
- Descifrado: auditoría registra `ERROR` y `detail`, por ejemplo formato de cifrado no reconocido. No se confirma una conversión de esa fila.
- Consistencia: si los datos descifrados difieren de la copia ASFI, se registra que requiere conciliación. Un cambio del texto cifrado con contenido equivalente ya no se rechaza por sí solo.
- Confirmación: una discrepancia o falta de respuesta queda `PENDIENTE`, con causa disponible en `detail`. **Pendiente no significa necesariamente que el banco no actualizó:** pudo perderse la respuesta. El reintento conserva el código para recuperarla.
- Fallo del banco: un evento `ERROR_BANCO` identifica la entidad y el punto de paginación afectado; no siempre identifica una fila individual porque el problema puede ser de conexión.

### Límites que conviene explicar honestamente

Hay auditoría funcional y reportes de rechazo, pero no se puede certificar cumplimiento de todos los requisitos de logs del docente sin el apartado exacto del enunciado. Actualmente:

- Los errores recuperables HTTP guardan en algunos casos la clase del fallo, no toda la respuesta remota. Para más detalle, revisar la salida del servicio.
- Los rechazos de BD por datos pueden mostrar `DataError`/`IntegrityError` sin indicar la columna exacta.
- Los nuevos eventos incluyen `audit_timestamp` y `barrido_id`; los antiguos conservan su formato original. El JSONL es acumulativo y no tiene rotación automática.
- Los reportes de generación/carga se reemplazan al repetir esas operaciones en la misma carpeta. Guardar evidencias antes si se quiere conservarlas.
- El log omite `datos` personales completos; están en la consolidación ASFI. La auditoría no contiene cada detalle del dataset rechazado, sino su referencia/línea y motivo.

## 14. Guardar evidencia para entregar

Después de una demostración, usar un directorio nuevo:

```bash
EVIDENCIA="data/evidencias/demo-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EVIDENCIA"
cp data/seed/rejected_rows.csv data/seed/metrics.json data/seed/load-metrics.json "$EVIDENCIA/"
.venv/bin/python scripts/demo_terminal.py estado > "$EVIDENCIA/ultimo-barrido.txt"
.venv/bin/python scripts/demo_terminal.py verificar "$BANCO" "$CUENTA" > "$EVIDENCIA/comparacion.txt"
.venv/bin/python scripts/export_asfi_audit.py --output "$EVIDENCIA/consolidacion-actual.jsonl"
```

El exportador toma el estado vigente de ASFI; **no es una exportación de todo el historial de barridos**. Usa la conexión predeterminada o `--database-url` si ASFI se configuró para otro motor. No admite sobrescribir un archivo existente. Si se necesita conservar el log histórico completo:

```bash
cp data/audit.jsonl "$EVIDENCIA/audit-historico.jsonl"
```

## 15. Preparación de otro dataset (no necesaria para repetir la demostración actual)

Generar en una carpeta nueva evita reemplazar los archivos de preparación existentes:

```bash
.venv/bin/python scripts/seeder.py RUTA_AL_DATASET.csv --output-dir data/seed-nuevo --workers 4
cat data/seed-nuevo/rejected_rows.csv
cat data/seed-nuevo/metrics.json
.venv/bin/python scripts/demo_terminal.py validar-cifrados --directorio data/seed-nuevo --bancos 1 2 3 4 5 6 7 8 9 10 11 12 13 14
```

Solo después de preparar las bases de la práctica para ese dataset, cargar:

```bash
.venv/bin/python scripts/load_all.py --source-dir data/seed-nuevo --workers 4
```

La carga es incremental: preserva las referencias ya existentes, **no reemplaza un dataset diferente con las mismas referencias**. Para la presentación con bases vacías se debe preparar un entorno coherente para bancos y ASFI; no eliminar únicamente la copia ASFI dejando conversiones antiguas en bancos, ni mezclar saldos de dos datasets. Esta guía no ejecuta ningún borrado.

## 16. Orden sugerido para exponer

1. Mostrar las 14 APIs disponibles y su cantidad de cuentas.
2. Abrir una base de cada motor y mostrar cinco registros, resaltando los campos cifrados.
3. Mostrar el reporte de filas rechazadas y explicar un motivo real.
4. Cambiar BCB a un segundo y ejecutar un barrido.
5. Explicar leídas, confirmadas, errores y tiempos de ejecución paralela.
6. Elegir una cuenta y mostrar su saldo Bs, tasa y código directamente en su base.
7. Mostrar la misma referencia en ASFI y ejecutar `verificar`: debe indicar `COINCIDE`.
8. Repetir el barrido y verificar nuevamente la misma cuenta para demostrar recotización.
9. Mostrar auditoría y guardar las evidencias.


## 17. Preparar desde cero con el dataset del docente

Este procedimiento presupone bases de bancos y ASFI vacías de la misma práctica. No incluye comandos de borrado: no mezclar una nueva fuente con cuentas antiguas de igual `Nro`.

1. Guardar el CSV como `data/dataset-docente.csv`. La cabecera esperada es `Nro,Identificacion,Nombres,Apellidos,NroCuenta,IdBanco,Saldo`. Saldo corresponde a USD e IdBanco va de 1 a 14. Si cambia la estructura, adaptar el mapeo antes de cargar.
2. Preparar archivos y revisar los rechazos:

```bash
.venv/bin/python scripts/seeder.py data/dataset-docente.csv --output-dir data/seed-docente --workers 4
cat data/seed-docente/metrics.json
cat data/seed-docente/rejected_rows.csv
```

3. Iniciar bases y esperar a que acepten conexiones. Luego cargar:

```bash
docker compose up -d
docker compose ps
.venv/bin/python scripts/load_all.py --source-dir data/seed-docente --workers 4
cat data/seed-docente/load-metrics.json
```

Un contenedor «Up» puede seguir inicializando su base. Si la carga reporta conexión rechazada, esperar y reintentar; las inserciones son incrementales. No continuar a la demostración si algún banco que debería tener datos quedó sin cargar.

4. Iniciar APIs con `scripts/run_panel.py`, mantener la terminal abierta y consultar `/api/panel/servicios` en otra terminal.
5. Modificar BCB a un segundo, ejecutar un barrido, verificar una cuenta y ejecutar el segundo barrido. Los comandos están en el apartado 11.
6. Consultar todas las cuentas con el verificador del siguiente apartado, usando `--source-dir data/seed-docente`.

## 18. Verificación completa: todas las cuentas, seis motores

El siguiente comando **solo lee** las bases y escribe el informe si se especifica `--output`. Ejecutarlo cuando no haya barridos ni cargas en curso, para que los valores no cambien durante la comparación.

Para el dataset grande preparado en la prueba final:

```bash
.venv/bin/python scripts/verificar_consolidacion.py --source-dir data/seed --output data/evidencias/verificacion-manual.json
```

Para el dataset del docente:

```bash
.venv/bin/python scripts/verificar_consolidacion.py --source-dir data/seed-docente --output data/evidencias/verificacion-docente.json
```

Comprueba referencias presentes/faltantes/adicionales, importe Bs, tasa, código hexadecimal, fórmula USD × tasa y estado confirmado en ASFI. Muestra resultados por banco y finaliza con COINCIDE si no detecta diferencias. No reemplaza las verificaciones de descifrado realizadas durante el barrido.

Usa las conexiones locales predeterminadas del cargador. Si se configuraron otras, conservar `BANK_XX_DATABASE_URL` y `ASFI_DATABASE_URL`, o pasar `--asfi-url`. El informe no incluye nombres ni saldos individuales; contiene contadores y huellas de códigos. Para mostrar una cuenta concreta usar `demo_terminal.py verificar`.

## 19. Entrar y mostrar la base de grafos con más detalle

Neo4j corresponde al Banco 13. Su contenedor es `bank13-bdp-neo4j`.

```bash
docker exec -it bank13-bdp-neo4j cypher-shell -u neo4j
```

Ingresar la contraseña local `bdp_password`, salvo que se haya cambiado `NEO4J_AUTH`.

Dentro de la consola, ejecutar cada consulta completa, con punto y coma:

```cypher
MATCH (c:Cliente) RETURN count(c) AS clientes;
MATCH (c:Cuenta) RETURN count(c) AS cuentas;
MATCH ()-[r]->() RETURN type(r) AS relacion, count(*) AS cantidad;
MATCH (cl:Cliente)-[r]->(cu:Cuenta)
RETURN cl.clienteId AS cliente, type(r) AS relacion,
       cu.cuentaId AS cuenta, cu.saldo_bs AS bolivianos,
       cu.tipo_cambio AS tasa, cu.codigo_verificacion AS codigo
LIMIT 5;
```

Escoger una de las referencias `cuenta` devueltas y sustituir REFERENCIA:

```cypher
MATCH (cu:Cuenta {cuentaId:'REFERENCIA'}) RETURN properties(cu);
MATCH (cl:Cliente)-[r]->(cu:Cuenta {cuentaId:'REFERENCIA'}) RETURN cl,r,cu;
:exit
```

En la terminal del sistema, comprobar la misma cuenta contra ASFI:

```bash
.venv/bin/python scripts/demo_terminal.py verificar 13 REFERENCIA
```

Opcionalmente, abrir `http://127.0.0.1:7474` en el navegador, conectar a `bolt://127.0.0.1:7687` con las mismas credenciales y ejecutar `MATCH (cl:Cliente)-[r]->(cu:Cuenta) RETURN cl,r,cu LIMIT 20;`. La vista Graph permite mostrar nodos y relaciones; la consola de terminal muestra sus resultados en tabla.

## 20. Guion hablado y evidencia que mostrar

| Paso | Comando o sección | Qué explicar |
|---|---|---|
| 1 | `docker compose ps` y `/api/panel/servicios` | Hay seis motores y 14 servicios bancarios; cada uno tiene su cantidad de cuentas. |
| 2 | Consultas de los apartados 5–9 | Los datos originales están cifrados y cada motor tiene su modelo. En Neo4j hay clientes y cuentas relacionados. |
| 3 | `rejected_rows.csv` y `metrics.json` | Un dato inválido se registra con motivo y no derriba el procesamiento de los válidos. |
| 4 | `demo_terminal.py intervalo 1` | La cotización cambia cada segundo; ASFI toma una tasa por lote. |
| 5 | `demo_terminal.py ejecutar` | Los bancos trabajan concurrentemente; mostrar tiempos y contadores. |
| 6 | Consulta de una cuenta y `demo_terminal.py verificar` | Banco y ASFI coinciden en saldo Bs, tasa y código; mostrar también la fórmula. |
| 7 | Segundo barrido y misma referencia | Se conserva USD; se genera una nueva operación y se aplica una cotización disponible. |
| 8 | `verificar_consolidacion.py` | La comprobación alcanza todas las cuentas, no únicamente una muestra. |
| 9 | `tail -n 10 data/audit.jsonl` | Cada barrido nuevo tiene ID y cada evento fecha UTC; los errores conservan su causa disponible. |

No mostrar toda la tabla de 123.785 filas en pantalla: usar COUNT, LIMIT y una referencia concreta. No confundir «banco con cero filas» con fallo si el dataset nuevo no asigna cuentas a ese banco.
