-- =====================================================================
-- LAS 8 CONSULTAS - MOTOR 1: PostgreSQL  (Bancos 1 Unión, 4 BCP, 6 Ganadero)
-- Práctica 2 - Plataforma Distribuida de Conversión Monetaria ASFI/BCB
-- =====================================================================
-- Ejecutar contra la base del banco que se quiera mostrar:
--   psql -h 127.0.0.1 -p 5433 -U union_user     -d bank_union     -f 01_postgresql.sql
--   psql -h 127.0.0.1 -p 5435 -U bcp_user       -d bank_bcp       -f 01_postgresql.sql
--   psql -h 127.0.0.1 -p 5436 -U ganadero_user  -d bank_ganadero  -f 01_postgresql.sql
--
-- Esquema de un banco:
--   clientes(nro, identificacion, nombres, apellidos)          <- datos CIFRADOS
--   cuentas (nro, cliente_nro, nro_cuenta, id_banco, saldo,    <- saldo CIFRADO
--            saldo_bs, codigo_verificacion, tipo_cambio, convertido_at)
--
-- IMPORTANTE PARA LA DEFENSA: en la base del banco, `saldo` (USD) está
-- CIFRADO con el algoritmo de esa entidad, por eso NO se puede sumar ni
-- ordenar aquí. Sólo la ASFI, que administra las llaves, lo descifra. Lo
-- que sí es texto plano en el banco es `saldo_bs`, porque lo escribe la
-- ASFI al confirmar la transacción junto con el código de verificación.
-- =====================================================================


-- ---------------------------------------------------------------------
-- C1. INVENTARIO Y AVANCE: ¿cuántos clientes y cuentas hay, y cuántas
--     cuentas ya fueron convertidas por la ASFI?
--     (Evidencia de: "14 bases de datos pobladas con información base")
-- ---------------------------------------------------------------------
SELECT
    (SELECT count(*) FROM clientes)                                   AS total_clientes,
    count(*)                                                          AS total_cuentas,
    count(codigo_verificacion)                                        AS convertidas,
    count(*) - count(codigo_verificacion)                             AS pendientes,
    round(100.0 * count(codigo_verificacion) / NULLIF(count(*), 0), 2) AS porcentaje_avance
FROM cuentas;


-- ---------------------------------------------------------------------
-- C2. TOTAL CONVERTIDO EN ESTE BANCO (en Bs.)
--     El saldo USD no aparece aquí porque está cifrado; el total en Bs.
--     sí, porque lo escribió la ASFI. Debe coincidir con la consulta C2
--     de 07_asfi_postgresql.sql para este mismo banco_id.
-- ---------------------------------------------------------------------
SELECT
    id_banco,
    count(*)                                        AS cuentas_convertidas,
    sum(CAST(saldo_bs AS DECIMAL(18,4)))            AS total_bs,
    round(avg(CAST(saldo_bs AS DECIMAL(18,4))), 4)  AS promedio_bs,
    min(CAST(saldo_bs AS DECIMAL(18,4)))            AS minimo_bs,
    max(CAST(saldo_bs AS DECIMAL(18,4)))            AS maximo_bs
FROM cuentas
WHERE saldo_bs IS NOT NULL
GROUP BY id_banco;


-- ---------------------------------------------------------------------
-- C3. LADO BANCO DE LA CONSISTENCIA BANCO <-> ASFI
--     Devuelve el detalle que la ASFI debe tener idéntico. La comparación
--     entre ambas bases la ejecuta ejecutar_consultas.py (son dos motores
--     distintos, no hay JOIN posible entre bases separadas).
-- ---------------------------------------------------------------------
SELECT nro AS cuenta_id, id_banco, saldo_bs, tipo_cambio, codigo_verificacion, convertido_at
FROM cuentas
WHERE codigo_verificacion IS NOT NULL
ORDER BY nro
LIMIT 10;


-- ---------------------------------------------------------------------
-- C4. VALIDACIÓN DEL CÓDIGO DE VERIFICACIÓN (8 caracteres hexadecimales)
--     Requisito del enunciado: 8 caracteres alfanuméricos en formato
--     hexadecimal (0-9, A-F). "formato_invalido" y "duplicados" deben ser 0.
-- ---------------------------------------------------------------------
SELECT
    count(*) FILTER (WHERE codigo_verificacion IS NOT NULL)                          AS con_codigo,
    count(*) FILTER (WHERE codigo_verificacion !~ '^[0-9A-F]{8}$')                    AS formato_invalido,
    count(DISTINCT codigo_verificacion)                                              AS codigos_distintos,
    count(*) FILTER (WHERE codigo_verificacion IS NOT NULL)
        - count(DISTINCT codigo_verificacion)                                        AS duplicados
FROM cuentas;


-- ---------------------------------------------------------------------
-- C5. AUDITORÍA DEL TIPO DE CAMBIO Y PRUEBA DEL BARRIDO PARALELO
--     Si el barrido fue paralelo y congeló una sola cotización, debe salir
--     UNA sola fila (una sola tasa) y una ventana de tiempo corta.
--     (Evidencia de: "Log de auditoría" y "Barrido paralelo")
-- ---------------------------------------------------------------------
SELECT
    tipo_cambio,
    count(*)                                                                AS cuentas_con_esa_tasa,
    min(convertido_at)                                                      AS primera_conversion,
    max(convertido_at)                                                      AS ultima_conversion,
    round(EXTRACT(EPOCH FROM (max(convertido_at) - min(convertido_at)))::numeric, 3) AS ventana_segundos
FROM cuentas
WHERE tipo_cambio IS NOT NULL
GROUP BY tipo_cambio
ORDER BY cuentas_con_esa_tasa DESC;


-- ---------------------------------------------------------------------
-- C6. CUENTAS NO PROCESADAS
--     Toda cuenta sin código de verificación no fue convertida. El motivo
--     puntual se lee en data/audit.jsonl (consulta C6 del runner).
-- ---------------------------------------------------------------------
SELECT count(*) AS cuentas_sin_convertir
FROM cuentas
WHERE codigo_verificacion IS NULL;

SELECT nro AS cuenta_id, id_banco, convertido_at
FROM cuentas
WHERE codigo_verificacion IS NULL
ORDER BY nro
LIMIT 10;


-- ---------------------------------------------------------------------
-- C7. RELACIÓN CLIENTE -> CUENTA EN MODELO RELACIONAL
--     Es el equivalente en SQL de la relación (:Cliente)-[:TIENE_CUENTA]->(:Cuenta)
--     que el Banco 13 resuelve en Neo4j (ver 05_neo4j.cypher).
-- ---------------------------------------------------------------------
SELECT
    cl.nro            AS cliente,
    count(c.nro)      AS cuentas_del_cliente,
    sum(CAST(c.saldo_bs AS DECIMAL(18,4))) AS total_bs_del_cliente
FROM clientes cl
JOIN cuentas c ON c.cliente_nro = cl.nro
GROUP BY cl.nro
HAVING count(c.nro) >= 1
ORDER BY count(c.nro) DESC, cliente
LIMIT 10;


-- ---------------------------------------------------------------------
-- C8. INTEGRIDAD REFERENCIAL Y CALIDAD DE DATOS
--     Con la clave foránea activa esto debe devolver 0 filas siempre.
--     Sirve como prueba de regresión si alguien carga datos sin el loader.
-- ---------------------------------------------------------------------
SELECT
    (SELECT count(*) FROM cuentas c
      LEFT JOIN clientes cl ON cl.nro = c.cliente_nro
      WHERE cl.nro IS NULL)                                        AS cuentas_huerfanas,
    (SELECT count(*) FROM cuentas WHERE saldo IS NULL OR saldo = '') AS saldo_cifrado_vacio,
    (SELECT count(*) FROM cuentas
      WHERE codigo_verificacion IS NOT NULL AND saldo_bs IS NULL)  AS confirmadas_sin_saldo_bs;
