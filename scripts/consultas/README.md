# Las 8 consultas oficiales — entregable de 40 puntos

Este directorio responde al ítem de la rúbrica **"8 Consultas a la base de datos
y preguntas (Sin IA) — 40 pts"**.

"Sin IA" significa que en la defensa hay que poder explicar cada consulta con
palabras propias. Por eso cada una viene con **la pregunta que responde**, **por
qué está escrita así** y **qué debe salir si el sistema funciona**.

## Archivos

| Archivo | Motor | Bancos |
|---|---|---|
| `01_postgresql.sql` | PostgreSQL | 1 Unión, 4 BCP, 6 Ganadero |
| `02_mysql.sql` | MySQL | 2 Mercantil, 5 BISA, 7 Económico |
| `03_sqlite.sql` | SQLite | 3 BNB |
| `04_mongodb.js` | MongoDB | 8 Prodem, 9 Solidario, 11 FIE, 12 PYME, 14 Nación Argentina |
| `05_neo4j.cypher` | Neo4j (grafo) | 13 BDP |
| `06_redis.txt` | Redis | 10 Fortaleza |
| `07_asfi.sql` | PostgreSQL | Base central de la ASFI |
| `ejecutar_consultas.py` | todos | Ejecuta las 8 sobre los 14 bancos + ASFI y arma la evidencia |

## Forma rápida de mostrarlas

```bash
# Con los servicios levantados y un barrido ya ejecutado:
python scripts/consultas/ejecutar_consultas.py --salida docs/evidencia-consultas.txt
```

Imprime un informe con las 8 consultas resueltas sobre los 14 bancos y la base
central, y guarda la evidencia en un archivo para adjuntar a la entrega.

Para mostrar una consulta escrita a mano en un motor concreto:

```bash
psql -h 127.0.0.1 -p 5433 -U union_user -d bank_union -f scripts/consultas/01_postgresql.sql
mysql -h 127.0.0.1 -P 3306 -u mercantil_user -p bank_mercantil < scripts/consultas/02_mysql.sql
sqlite3 data/bank_03.sqlite < scripts/consultas/03_sqlite.sql
mongosh mongodb://127.0.0.1:27017 --file scripts/consultas/04_mongodb.js
cypher-shell -a bolt://127.0.0.1:7687 -u neo4j -p bdp_password -f scripts/consultas/05_neo4j.cypher
psql -h 127.0.0.1 -p 5434 -U asfi_user -d asfi_db -f scripts/consultas/07_asfi.sql
```

---

## La idea que hay que tener clara antes de empezar

**En la base de un banco, el saldo en USD está CIFRADO.** No se puede sumar,
ordenar ni comparar. Cada banco usa su propio algoritmo (César, Atbash, DES,
RSA, ECC...). Sólo la ASFI, que administra las llaves, puede descifrarlo.

Por eso:

- Las sumas **en USD** salen de la **base central de la ASFI** (`07_asfi.sql`),
  donde el saldo ya está descifrado.
- Las sumas **en Bs.** también salen del banco, porque `saldo_bs` lo escribe la
  ASFI en el banco al confirmar la transacción, junto con el código de
  verificación.

Si el docente pregunta *"¿por qué no sumas el saldo USD en la tabla del banco?"*,
ésa es la respuesta: **está cifrado, y el banco no tiene la llave de la ASFI**.

---

## C1. Inventario y avance por banco

**Pregunta:** ¿Están las 14 bases pobladas y cuántas cuentas ya se convirtieron?

Cuenta clientes, cuentas totales, cuántas tienen código de verificación (es
decir, ya pasaron por la ASFI) y el porcentaje de avance.

**Debe salir:** las 14 entidades con sus cuentas cargadas y, después de un
barrido completo, 100 % de avance.

**Prueba de la rúbrica:** "14 bases de datos pobladas con información base".

## C2. Saldo original en USD y convertido en Bs.

**Pregunta:** ¿Cuánto dinero se convirtió en cada entidad y a cuánto equivale?

Agrupa por banco sobre la base central de la ASFI y suma `saldo_usd` y
`saldo_bs`.

**Debe salir:** un total por banco y el gran total del sistema. Los importes
tienen que ser realistas (cuentas de decenas a cientos de miles de USD). Si
aparecen saldos de miles de millones, los datos están mal sembrados.

**Prueba de la rúbrica:** "Servicio de recepción y descifrado de datos en la
ASFI" y el requisito de registrar saldo original y convertido.

## C3. Consistencia banco ↔ ASFI

**Pregunta:** ¿Lo que quedó guardado en el banco coincide con lo que registró la
ASFI?

Compara, cuenta por cuenta, `saldo_bs`, `tipo_cambio` y `codigo_verificacion` en
ambos lados. No es una consulta SQL única porque son **bases de datos distintas
en motores distintos**: no existe JOIN entre ellas. El runner lee los dos lados y
los cruza en memoria.

**Debe salir:** `Diferencias totales: 0 (CONSISTENTE)`.

**Prueba:** requisito explícito del enunciado — *"Validar la consistencia entre
el saldo actualizado en el banco y el saldo registrado en la ASFI"*.

## C4. Validación de los códigos de verificación

**Pregunta:** ¿Todos los códigos son de 8 caracteres hexadecimales, únicos, y
están en los dos lados?

Valida el formato con una expresión regular `^[0-9A-F]{8}$` y busca duplicados.

**Debe salir:** `formato_invalido = 0` y `duplicados = 0`.

**Prueba:** requisito explícito — *"código de verificación compuesto por 8
caracteres alfanuméricos en formato hexadecimal (0–9, A–F)"*.

## C5. Auditoría del tipo de cambio y prueba del barrido paralelo

**Pregunta:** ¿Qué cotización se aplicó, cuándo, y se usó la misma para todos?

Agrupa por `tipo_cambio` y muestra la ventana de tiempo entre la primera y la
última conversión.

**Debe salir:** **una sola tasa** para los 14 bancos y una ventana de pocos
segundos.

**Por qué importa (dilo así en la defensa):** el enunciado pide que el proceso
sea paralelo *"para que la fluctuación del dólar no afecte a algunos y beneficie
a otros"*. Esta consulta es la prueba: si el barrido hubiera sido secuencial y
lento, el BCB habría cambiado la cotización a mitad de camino y aquí aparecerían
dos o más tasas distintas. Aparece una sola.

**Prueba de la rúbrica:** "Log de auditoría de transacciones y tipo de cambio" y
"Barrido paralelo (optimización de tiempo)".

## C6. Cuentas no procesadas y su motivo

**Pregunta:** ¿Quedó alguna cuenta sin convertir? ¿Por qué?

Lista las cuentas sin código de verificación y agrupa los motivos registrados en
`data/audit.jsonl`.

**Debe salir:** 0 pendientes tras un barrido correcto. Si hay pendientes, el log
dice exactamente por qué (banco caído, dato inválido, timeout), y eso también es
una respuesta válida: el sistema no las pierde en silencio.

**Prueba:** trazabilidad y no repudio.

## C7. Relación cliente → cuenta (la consulta de grafo)

**Pregunta:** ¿Qué clientes tienen más de una cuenta y cuánto suman?

En Neo4j (Banco 13) se recorre la relación `(:Cliente)-[:TIENE_CUENTA]->(:Cuenta)`.
En los motores relacionales el equivalente es un JOIN entre `clientes` y
`cuentas`; en MongoDB, agrupar por `identificacion`.

**Debe salir:** los clientes con varias cuentas y su saldo total.

**Por qué importa (dilo así):** en el grafo, ir de un cliente a sus cuentas no
requiere buscar en un índice, se recorre la arista directamente. Ésa es la
ventaja del modelo de grafos frente al JOIN relacional.

**Prueba de la rúbrica:** "Una base de datos orientada a grafos de las 14 (dos
nodos cliente y cuenta) — 20 pts".

## C8. Ranking del sistema e integridad de los importes

**Pregunta:** ¿La conversión es aritméticamente correcta y los montos son
razonables?

Verifica que `saldo_bs = saldo_usd × tipo_cambio` con 4 decimales para **todas**
las cuentas, muestra el top 10 y la distribución por tramos.

**Debe salir:** `Descuadres: 0 (CORRECTO)`.

**Por qué importa:** demuestra que la ASFI no alteró ningún importe durante la
conversión. Es la respuesta directa a la consideración de seguridad *"alteración
de la integridad de los datos posconversión"*.

---

## Preguntas que probablemente haga el docente

**¿Por qué la ASFI puede sumar el saldo en USD y el banco no?**
Porque la ASFI descifra con la llave que administra. En el banco el campo `saldo`
es texto cifrado con el algoritmo de esa entidad.

**¿Cómo sé que nadie modificó un saldo después de la conversión?**
Consulta C8: recalcula `saldo_usd × tipo_cambio` y lo compara con `saldo_bs`
guardado. Cualquier alteración da descuadre. Además la ASFI guarda un hash del
registro de origen (`origen_hash`) y compara al reprocesar.

**¿Qué pasa si el mismo código de verificación llega dos veces?**
El banco lo detecta: si la cuenta ya fue confirmada con ese código y los importes
coinciden, responde el mismo comprobante (operación idempotente); si los importes
difieren, rechaza con conflicto. Consulta C4 comprueba que no haya duplicados.

**¿Y si el dólar cambia a mitad del barrido?**
La ASFI captura la cotización una vez, valida contra el BCB que no esté vencida
(compara el timestamp con el intervalo declarado) y la aplica a todo el lote.
Consulta C5 lo demuestra: una sola tasa.

**¿Dónde está la copia de cada banco en la ASFI?**
En la tabla `asfi_cuentas` de `asfi_db`, y expuesta con los nombres exactos del
enunciado en la vista `Cuentas` junto con la tabla `Bancos`
(ver `scripts/creacion/asfi_vistas_enunciado.sql`).
