-- =====================================================================
-- LAS 8 CONSULTAS - MOTOR 3: SQLite  (Banco 3 - BNB)
-- =====================================================================
--   sqlite3 data/bank_03.sqlite < 03_sqlite.sql
--   (o:  python -c "import sqlite3;print(sqlite3.connect('data/bank_03.sqlite').execute(open('03_sqlite.sql').read()).fetchall())" )
--
-- Notas de dialecto: SQLite no trae REGEXP, se usa GLOB. Las fechas son
-- texto ISO-8601, por eso la diferencia de tiempo se calcula con julianday().
-- `saldo` (USD) está CIFRADO con Vigenère; `saldo_bs` lo escribe la ASFI.
-- =====================================================================

.mode column
.headers on

-- C1. Inventario y avance de conversión
SELECT
    (SELECT count(*) FROM clientes)                                   AS total_clientes,
    count(*)                                                          AS total_cuentas,
    count(codigo_verificacion)                                        AS convertidas,
    count(*) - count(codigo_verificacion)                             AS pendientes,
    ROUND(100.0 * count(codigo_verificacion) / NULLIF(count(*),0), 2) AS porcentaje_avance
FROM cuentas;


-- C2. Total convertido en este banco (Bs.)
SELECT
    id_banco,
    count(*)                            AS cuentas_convertidas,
    ROUND(SUM(CAST(saldo_bs AS REAL)),4) AS total_bs,
    ROUND(AVG(CAST(saldo_bs AS REAL)),4) AS promedio_bs,
    MIN(CAST(saldo_bs AS REAL))          AS minimo_bs,
    MAX(CAST(saldo_bs AS REAL))          AS maximo_bs
FROM cuentas
WHERE saldo_bs IS NOT NULL
GROUP BY id_banco;


-- C3. Lado banco de la consistencia banco <-> ASFI
SELECT nro AS cuenta_id, id_banco, saldo_bs, tipo_cambio, codigo_verificacion, convertido_at
FROM cuentas
WHERE codigo_verificacion IS NOT NULL
ORDER BY nro
LIMIT 10;


-- C4. Validación del código de verificación (8 hexadecimales)
--     GLOB con 8 clases [0-9A-F] equivale al regex ^[0-9A-F]{8}$.
SELECT
    SUM(codigo_verificacion IS NOT NULL)                                     AS con_codigo,
    SUM(codigo_verificacion IS NOT NULL AND NOT (
        codigo_verificacion GLOB '[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]'
        AND length(codigo_verificacion) = 8))                                AS formato_invalido,
    COUNT(DISTINCT codigo_verificacion)                                      AS codigos_distintos,
    SUM(codigo_verificacion IS NOT NULL) - COUNT(DISTINCT codigo_verificacion) AS duplicados
FROM cuentas;


-- C5. Auditoría del tipo de cambio y prueba del barrido paralelo
SELECT
    tipo_cambio,
    count(*)                AS cuentas_con_esa_tasa,
    MIN(convertido_at)      AS primera_conversion,
    MAX(convertido_at)      AS ultima_conversion,
    ROUND((julianday(MAX(convertido_at)) - julianday(MIN(convertido_at))) * 86400.0, 3) AS ventana_segundos
FROM cuentas
WHERE tipo_cambio IS NOT NULL
GROUP BY tipo_cambio
ORDER BY cuentas_con_esa_tasa DESC;


-- C6. Cuentas no procesadas
SELECT count(*) AS cuentas_sin_convertir FROM cuentas WHERE codigo_verificacion IS NULL;


-- C7. Relación cliente -> cuenta (equivalente SQL de TIENE_CUENTA)
SELECT
    cl.nro                               AS cliente,
    count(c.nro)                         AS cuentas_del_cliente,
    ROUND(SUM(CAST(c.saldo_bs AS REAL)),4) AS total_bs_del_cliente
FROM clientes cl
JOIN cuentas c ON c.cliente_nro = cl.nro
GROUP BY cl.nro
ORDER BY cuentas_del_cliente DESC, cliente
LIMIT 10;


-- C8. Integridad referencial y calidad de datos (todo debe dar 0)
SELECT
    (SELECT count(*) FROM cuentas c
       LEFT JOIN clientes cl ON cl.nro = c.cliente_nro
      WHERE cl.nro IS NULL)                                          AS cuentas_huerfanas,
    (SELECT count(*) FROM cuentas WHERE saldo IS NULL OR saldo = '') AS saldo_cifrado_vacio,
    (SELECT count(*) FROM cuentas
      WHERE codigo_verificacion IS NOT NULL AND saldo_bs IS NULL)    AS confirmadas_sin_saldo_bs;
