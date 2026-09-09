-- =====================================================================
-- LAS 8 CONSULTAS - BASE DE DATOS CENTRAL DE LA ASFI (PostgreSQL)
-- Aquí vive la copia consolidada de las 14 entidades financieras.
-- =====================================================================
--   psql -h 127.0.0.1 -p 5434 -U asfi_user -d asfi_db -f 07_asfi.sql
--   (variante SQLite de pruebas: sqlite3 data/asfi.sqlite < 07_asfi.sql,
--    reemplazando los cast ::numeric por CAST(... AS REAL))
--
-- Esquema:
--   asfi_cuentas(banco_id, cuenta_id, saldo_usd, saldo_bs, tipo_cambio,
--                codigo_verificacion, fecha_conversion, estado, payload)
--   asfi_historial(banco_id, cuenta_id, codigo_verificacion, payload)
--   Vistas del enunciado: "Bancos" y "Cuentas" (ver asfi_vistas_enunciado.sql)
--
-- DIFERENCIA CLAVE CON LA BD DE UN BANCO: aquí `saldo_usd` está EN CLARO,
-- porque la ASFI ya lo descifró con las llaves que administra. Por eso las
-- sumas en USD sólo se pueden hacer en esta base.
-- =====================================================================


-- ---------------------------------------------------------------------
-- C1. INVENTARIO CONSOLIDADO: ¿cuántas cuentas recibió la ASFI de cada
--     banco y en qué estado quedaron?
-- ---------------------------------------------------------------------
SELECT
    banco_id,
    count(*)                                          AS cuentas_consolidadas,
    count(*) FILTER (WHERE estado = 'CONFIRMADA')     AS confirmadas,
    count(*) FILTER (WHERE estado = 'PENDIENTE')      AS pendientes,
    count(*) FILTER (WHERE estado NOT IN ('CONFIRMADA','PENDIENTE')) AS otros_estados
FROM asfi_cuentas
GROUP BY banco_id
ORDER BY banco_id;

-- Total general del sistema
SELECT count(*) AS total_cuentas_sistema,
       count(DISTINCT banco_id) AS bancos_con_datos,
       count(*) FILTER (WHERE estado = 'CONFIRMADA') AS total_confirmadas
FROM asfi_cuentas;


-- ---------------------------------------------------------------------
-- C2. SALDO ORIGINAL EN USD Y SALDO CONVERTIDO EN Bs. POR BANCO
--     Es el número central de la práctica: cuánto se convirtió y a cuánto.
--     Requisito: "registrar el saldo original en USD y el saldo convertido en Bs."
-- ---------------------------------------------------------------------
SELECT
    banco_id,
    count(*)                              AS cuentas,
    sum(saldo_usd)                        AS total_usd,
    sum(saldo_bs)                         AS total_bs,
    round(avg(saldo_usd), 4)              AS promedio_usd,
    max(tipo_cambio)                      AS tipo_cambio_aplicado
FROM asfi_cuentas
WHERE estado = 'CONFIRMADA'
GROUP BY banco_id
ORDER BY total_usd DESC;

-- Gran total del sistema financiero
SELECT sum(saldo_usd) AS total_usd_sistema,
       sum(saldo_bs)  AS total_bs_sistema
FROM asfi_cuentas WHERE estado = 'CONFIRMADA';


-- ---------------------------------------------------------------------
-- C3. VERIFICACIÓN ARITMÉTICA DE LA CONVERSIÓN
--     saldo_bs debe ser exactamente saldo_usd * tipo_cambio con 4 decimales.
--     "descuadres" debe ser 0. Es la prueba de que ASFI no alteró importes.
-- ---------------------------------------------------------------------
SELECT
    count(*)                                                                AS total_evaluadas,
    count(*) FILTER (WHERE round(saldo_usd * tipo_cambio, 4) <> saldo_bs)    AS descuadres
FROM asfi_cuentas
WHERE estado = 'CONFIRMADA';

-- Detalle de cualquier descuadre (debe salir vacío)
SELECT banco_id, cuenta_id, saldo_usd, tipo_cambio, saldo_bs,
       round(saldo_usd * tipo_cambio, 4) AS bs_esperado
FROM asfi_cuentas
WHERE estado = 'CONFIRMADA' AND round(saldo_usd * tipo_cambio, 4) <> saldo_bs
LIMIT 10;


-- ---------------------------------------------------------------------
-- C4. VALIDACIÓN DE LOS CÓDIGOS DE VERIFICACIÓN EN LA ASFI
--     8 caracteres hexadecimales, sin duplicados dentro del mismo banco.
-- ---------------------------------------------------------------------
SELECT
    count(*)                                                         AS con_codigo,
    count(*) FILTER (WHERE codigo_verificacion !~ '^[0-9A-F]{8}$')    AS formato_invalido,
    count(DISTINCT codigo_verificacion)                              AS codigos_distintos
FROM asfi_cuentas;

-- Códigos repetidos dentro de un mismo banco (debe salir vacío)
SELECT banco_id, codigo_verificacion, count(*) AS veces
FROM asfi_cuentas
GROUP BY banco_id, codigo_verificacion
HAVING count(*) > 1
LIMIT 10;


-- ---------------------------------------------------------------------
-- C5. AUDITORÍA DEL TIPO DE CAMBIO Y PRUEBA DEL BARRIDO PARALELO
--     Si el barrido congeló una sola cotización del BCB, aquí debe salir
--     UNA sola tasa para todos los bancos, con una ventana corta.
--     Ésta es la consulta que demuestra el requisito de paralelismo:
--     "que la fluctuación del dólar no afecte a algunos y beneficie a otros".
-- ---------------------------------------------------------------------
SELECT
    tipo_cambio,
    count(*)                        AS cuentas,
    count(DISTINCT banco_id)        AS bancos_afectados,
    min(fecha_conversion)           AS primera,
    max(fecha_conversion)           AS ultima
FROM asfi_cuentas
GROUP BY tipo_cambio
ORDER BY cuentas DESC;

-- ¿Algún banco recibió una tasa distinta a la de los demás?
-- (si el resultado es 1, todos los bancos usaron la misma cotización)
SELECT count(DISTINCT tipo_cambio) AS tasas_distintas_en_el_barrido FROM asfi_cuentas;


-- ---------------------------------------------------------------------
-- C6. CUENTAS NO CONFIRMADAS Y SU MOTIVO
--     El motivo textual viaja dentro de `payload` (campo "detail").
-- ---------------------------------------------------------------------
SELECT banco_id, estado, count(*) AS cuentas
FROM asfi_cuentas
WHERE estado <> 'CONFIRMADA'
GROUP BY banco_id, estado
ORDER BY banco_id;

SELECT banco_id, cuenta_id, estado,
       substring(payload from '"detail": "([^"]*)"') AS motivo
FROM asfi_cuentas
WHERE estado <> 'CONFIRMADA'
LIMIT 10;


-- ---------------------------------------------------------------------
-- C7. RECONVERSIONES (HISTORIAL)
--     Cada vez que se vuelve a convertir una cuenta ya confirmada, la
--     versión anterior se archiva en asfi_historial. Prueba de trazabilidad
--     y no repudio: ninguna conversión previa se pierde ni se sobrescribe.
-- ---------------------------------------------------------------------
SELECT banco_id, count(*) AS versiones_archivadas
FROM asfi_historial
GROUP BY banco_id
ORDER BY banco_id;

-- Cuentas con más de una conversión histórica
SELECT banco_id, cuenta_id, count(*) AS veces_reconvertida
FROM asfi_historial
GROUP BY banco_id, cuenta_id
HAVING count(*) >= 1
ORDER BY veces_reconvertida DESC
LIMIT 10;


-- ---------------------------------------------------------------------
-- C8. RANKING Y DISTRIBUCIÓN DE SALDOS
--     Top 10 cuentas del sistema y reparto por tramos. Sirve para mostrar
--     que los importes son razonables (control de calidad del dato).
-- ---------------------------------------------------------------------
SELECT banco_id, cuenta_id, saldo_usd, saldo_bs, codigo_verificacion
FROM asfi_cuentas
WHERE estado = 'CONFIRMADA'
ORDER BY saldo_usd DESC
LIMIT 10;

SELECT
    CASE
        WHEN saldo_usd <  1000    THEN 'a) menos de 1.000'
        WHEN saldo_usd <  10000   THEN 'b) 1.000 a 10.000'
        WHEN saldo_usd <  100000  THEN 'c) 10.000 a 100.000'
        WHEN saldo_usd <  500000  THEN 'd) 100.000 a 500.000'
        ELSE                           'e) 500.000 o más'
    END                     AS tramo_usd,
    count(*)                AS cuentas,
    round(sum(saldo_usd),4) AS total_usd
FROM asfi_cuentas
WHERE estado = 'CONFIRMADA'
GROUP BY 1
ORDER BY 1;
