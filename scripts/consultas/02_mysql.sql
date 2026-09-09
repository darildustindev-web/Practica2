-- =====================================================================
-- LAS 8 CONSULTAS - MOTOR 2: MySQL  (Bancos 2 Mercantil, 5 BISA, 7 Económico)
-- =====================================================================
--   mysql -h 127.0.0.1 -P 3306 -u mercantil_user -p bank_mercantil < 02_mysql.sql
--   mysql -h 127.0.0.1 -P 3307 -u bisa_user      -p bank_bisa      < 02_mysql.sql
--   mysql -h 127.0.0.1 -P 3308 -u economico_user -p bank_economico < 02_mysql.sql
--
-- Mismo esquema lógico que PostgreSQL: clientes + cuentas.
-- Recordar: `saldo` (USD) está CIFRADO; `saldo_bs` lo escribe la ASFI.
-- =====================================================================


-- C1. Inventario y avance de conversión
SELECT
    (SELECT count(*) FROM clientes)                                        AS total_clientes,
    count(*)                                                               AS total_cuentas,
    count(codigo_verificacion)                                             AS convertidas,
    count(*) - count(codigo_verificacion)                                  AS pendientes,
    ROUND(100.0 * count(codigo_verificacion) / NULLIF(count(*),0), 2)      AS porcentaje_avance
FROM cuentas;


-- C2. Total convertido en este banco (Bs.)
SELECT
    id_banco,
    count(*)                                       AS cuentas_convertidas,
    SUM(CAST(saldo_bs AS DECIMAL(18,4)))           AS total_bs,
    ROUND(AVG(CAST(saldo_bs AS DECIMAL(18,4))), 4) AS promedio_bs,
    MIN(CAST(saldo_bs AS DECIMAL(18,4)))           AS minimo_bs,
    MAX(CAST(saldo_bs AS DECIMAL(18,4)))           AS maximo_bs
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
--     formato_invalido y duplicados deben ser 0.
SELECT
    SUM(codigo_verificacion IS NOT NULL)                                        AS con_codigo,
    SUM(codigo_verificacion IS NOT NULL
        AND codigo_verificacion NOT REGEXP '^[0-9A-F]{8}$')                     AS formato_invalido,
    COUNT(DISTINCT codigo_verificacion)                                         AS codigos_distintos,
    SUM(codigo_verificacion IS NOT NULL) - COUNT(DISTINCT codigo_verificacion)  AS duplicados
FROM cuentas;


-- C5. Auditoría del tipo de cambio y prueba del barrido paralelo
--     Debe salir UNA sola tasa y una ventana de tiempo corta.
SELECT
    tipo_cambio,
    count(*)                                                           AS cuentas_con_esa_tasa,
    MIN(convertido_at)                                                 AS primera_conversion,
    MAX(convertido_at)                                                 AS ultima_conversion,
    ROUND(TIMESTAMPDIFF(MICROSECOND, MIN(convertido_at), MAX(convertido_at))/1000000, 3) AS ventana_segundos
FROM cuentas
WHERE tipo_cambio IS NOT NULL
GROUP BY tipo_cambio
ORDER BY cuentas_con_esa_tasa DESC;


-- C6. Cuentas no procesadas
SELECT count(*) AS cuentas_sin_convertir FROM cuentas WHERE codigo_verificacion IS NULL;

SELECT nro AS cuenta_id, id_banco, convertido_at
FROM cuentas
WHERE codigo_verificacion IS NULL
ORDER BY nro
LIMIT 10;


-- C7. Relación cliente -> cuenta (equivalente SQL de TIENE_CUENTA)
SELECT
    cl.nro                                  AS cliente,
    count(c.nro)                            AS cuentas_del_cliente,
    SUM(CAST(c.saldo_bs AS DECIMAL(18,4)))  AS total_bs_del_cliente
FROM clientes cl
JOIN cuentas c ON c.cliente_nro = cl.nro
GROUP BY cl.nro
ORDER BY cuentas_del_cliente DESC, cliente
LIMIT 10;


-- C8. Integridad referencial y calidad de datos (todo debe dar 0)
SELECT
    (SELECT count(*) FROM cuentas c
       LEFT JOIN clientes cl ON cl.nro = c.cliente_nro
      WHERE cl.nro IS NULL)                                             AS cuentas_huerfanas,
    (SELECT count(*) FROM cuentas WHERE saldo IS NULL OR saldo = '')    AS saldo_cifrado_vacio,
    (SELECT count(*) FROM cuentas
      WHERE codigo_verificacion IS NOT NULL AND saldo_bs IS NULL)       AS confirmadas_sin_saldo_bs;
