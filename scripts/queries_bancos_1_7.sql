-- Consultas de verificación para los bancos relacionales (1-7)
-- Integrante 2 - Infraestructura Bancos Relacionales & Seeder
--
-- Estas consultas apoyan la trazabilidad y la auditoría de los bancos 1 al 7
-- (Unión, Mercantil, BNB, BCP, BISA, Ganadero, Económico). No sustituyen las
-- 8 consultas SQL/NoSQL oficiales que pide el enunciado (esas cubren los 14
-- bancos y son responsabilidad conjunta del equipo); son un complemento para
-- validar rápidamente el trabajo de esta parte del sistema.
--
-- Sintaxis: válidas en PostgreSQL y MySQL/MariaDB tal cual. Para SQLite,
-- reemplazar NOW()/CURRENT_TIMESTAMP según corresponda (SQLite acepta
-- CURRENT_TIMESTAMP igual) y quitar ILIKE si se usa (no aparece aquí).

-- 1. Conteo de cuentas cargadas por banco (ejecutar en cada base; cada banco
--    vive en su propio motor/BD, no hay una tabla compartida entre bancos).
SELECT COUNT(*) AS total_cuentas FROM cuentas;

-- 2. Cuántas cuentas ya fueron confirmadas por ASFI vs. cuántas siguen
--    pendientes de conversión (saldo_bs se llena recién al confirmar).
SELECT
    SUM(CASE WHEN saldo_bs IS NOT NULL THEN 1 ELSE 0 END) AS confirmadas,
    SUM(CASE WHEN saldo_bs IS NULL THEN 1 ELSE 0 END) AS pendientes
FROM cuentas;

-- 3. Integridad del código de verificación: debe ser NULL (aún no
--    confirmada) u ocho caracteres hexadecimales en mayúscula. Cualquier
--    fila que aparezca aquí es un problema de integridad a investigar.
SELECT nro, codigo_verificacion
FROM cuentas
WHERE codigo_verificacion IS NOT NULL
  AND codigo_verificacion !~ '^[0-9A-F]{8}$';  -- MySQL: usar REGEXP en vez de !~

-- 4. Clientes con más de una cuenta en este banco (hoy el seeder genera una
--    cuenta por fila del dataset; esta consulta confirma esa relación 1:1 o
--    detecta si el dataset llega a tener duplicados de cliente).
SELECT cliente_nro, COUNT(*) AS cuentas
FROM cuentas
GROUP BY cliente_nro
HAVING COUNT(*) > 1;

-- 5. Muestra legible (aún cifrada) uniendo Clientes y Cuentas, la forma en
--    que el equipo puede confirmar visualmente que el JOIN funciona.
SELECT cl.nro, cl.identificacion, cl.nombres, cl.apellidos,
       c.nro_cuenta, c.id_banco, c.saldo, c.saldo_bs, c.codigo_verificacion
FROM clientes cl
JOIN cuentas c ON c.cliente_nro = cl.nro
ORDER BY cl.nro
LIMIT 20;

-- 6. Cuentas sin cliente asociado o clientes sin cuenta: con la FK activa
--    (SQLite requiere `PRAGMA foreign_keys = ON`, ya configurado en
--    sqlite_store.py) esto siempre debería devolver 0 filas; sirve como
--    chequeo de regresión si alguien carga datos sin pasar por el seeder.
SELECT c.nro AS cuenta_huerfana
FROM cuentas c
LEFT JOIN clientes cl ON cl.nro = c.cliente_nro
WHERE cl.nro IS NULL;

-- 7. Última tasa de cambio aplicada y cuándo se hizo, útil para verificar
--    en la defensa que todas las cuentas de este banco se convirtieron con
--    una única tasa BCB durante el barrido paralelo de ASFI.
SELECT DISTINCT tipo_cambio, MIN(convertido_at) AS primera, MAX(convertido_at) AS ultima
FROM cuentas
WHERE tipo_cambio IS NOT NULL
GROUP BY tipo_cambio;

-- 8. Top 10 saldos en Bs. ya convertidos (requiere que ASFI haya confirmado
--    transacciones); útil para validar manualmente un par de conversiones
--    contra el tipo de cambio reportado por el BCB en ese momento.
SELECT nro, saldo_bs, tipo_cambio, convertido_at
FROM cuentas
WHERE saldo_bs IS NOT NULL
ORDER BY CAST(saldo_bs AS DECIMAL(18,4)) DESC
LIMIT 10;
