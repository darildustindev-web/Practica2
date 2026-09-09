// =====================================================================
// LAS 8 CONSULTAS - MOTOR 6: Neo4j (GRAFO)
// Banco 13 - Banco de Desarrollo Productivo S.A.M. (BDP), cifrado ECC
// =====================================================================
// Ejecutar con:
//   cypher-shell -a bolt://127.0.0.1:7687 -u neo4j -p bdp_password -f 05_neo4j.cypher
//   o pegando cada consulta en Neo4j Browser: http://127.0.0.1:7474
//
// MODELO DEL GRAFO (requisito de 20 pts: "dos nodos cliente y cuenta"):
//
//     (:Cliente {clienteId, identificacion, nombres, apellidos})
//            |
//            | [:TIENE_CUENTA]
//            v
//     (:Cuenta {cuentaId, nro, bancoId, saldo/saldoUSD (CIFRADO con ECC),
//               saldoBs, saldo_bs, estado, codigoVerificacion,
//               codigo_verificacion, tipoCambio, convertido_at, nroCuenta})
//
// PARA LA DEFENSA: aquí no hay tablas ni JOIN. La relación TIENE_CUENTA es
// una arista física del grafo: ir de un cliente a sus cuentas no cuesta una
// búsqueda por índice, se recorre el puntero. Ésa es la ventaja del grafo.
// El saldo USD está cifrado con ECC; sólo la ASFI puede descifrarlo.
// =====================================================================


// ---------------------------------------------------------------------
// C1. INVENTARIO Y AVANCE: nodos, relaciones y cuentas convertidas
// ---------------------------------------------------------------------
MATCH (cl:Cliente)
WITH count(cl) AS clientes
MATCH (cu:Cuenta)
WITH clientes, count(cu) AS cuentas,
     count(cu.codigo_verificacion) AS convertidas
MATCH (:Cliente)-[r:TIENE_CUENTA]->(:Cuenta)
RETURN clientes,
       cuentas,
       count(r)                   AS relaciones_tiene_cuenta,
       convertidas,
       cuentas - convertidas      AS pendientes,
       round(100.0 * convertidas / cuentas, 2) AS porcentaje_avance;


// ---------------------------------------------------------------------
// C2. TOTAL CONVERTIDO EN Bs. EN EL BANCO 13
//     saldo_bs es texto (lo escribe la ASFI), se convierte con toFloat().
// ---------------------------------------------------------------------
MATCH (cu:Cuenta)
WHERE cu.saldo_bs IS NOT NULL
RETURN cu.bancoId                          AS banco_id,
       count(cu)                           AS cuentas_convertidas,
       round(sum(toFloat(cu.saldo_bs)), 4) AS total_bs,
       round(avg(toFloat(cu.saldo_bs)), 4) AS promedio_bs,
       min(toFloat(cu.saldo_bs))           AS minimo_bs,
       max(toFloat(cu.saldo_bs))           AS maximo_bs;


// ---------------------------------------------------------------------
// C3. LADO BANCO DE LA CONSISTENCIA BANCO <-> ASFI
//     Comparar estas filas contra asfi_cuentas WHERE banco_id = 13.
// ---------------------------------------------------------------------
MATCH (cu:Cuenta)
WHERE cu.codigo_verificacion IS NOT NULL
RETURN cu.cuentaId              AS cuenta_id,
       cu.bancoId               AS banco_id,
       cu.saldo_bs              AS saldo_bs,
       cu.tipo_cambio           AS tipo_cambio,
       cu.codigo_verificacion   AS codigo_verificacion,
       cu.convertido_at         AS convertido_at
ORDER BY cu.cuentaId
LIMIT 10;


// ---------------------------------------------------------------------
// C4. VALIDACIÓN DEL CÓDIGO DE VERIFICACIÓN (8 hexadecimales)
//     formato_invalido y duplicados deben ser 0.
// ---------------------------------------------------------------------
MATCH (cu:Cuenta)
WHERE cu.codigo_verificacion IS NOT NULL
WITH collect(cu.codigo_verificacion) AS codigos
RETURN size(codigos)                                          AS con_codigo,
       size([c IN codigos WHERE NOT c =~ '^[0-9A-F]{8}$'])    AS formato_invalido,
       size(apoc.coll.toSet(codigos))                         AS codigos_distintos;
// Si APOC no está instalado, usar esta variante equivalente:
// MATCH (cu:Cuenta) WHERE cu.codigo_verificacion IS NOT NULL
// WITH cu.codigo_verificacion AS c
// RETURN count(c) AS con_codigo,
//        sum(CASE WHEN c =~ '^[0-9A-F]{8}$' THEN 0 ELSE 1 END) AS formato_invalido,
//        count(DISTINCT c) AS codigos_distintos;


// ---------------------------------------------------------------------
// C5. AUDITORÍA DEL TIPO DE CAMBIO Y BARRIDO PARALELO
//     Debe salir UNA sola tasa: la misma que recibieron los otros 13 bancos.
// ---------------------------------------------------------------------
MATCH (cu:Cuenta)
WHERE cu.tipo_cambio IS NOT NULL
RETURN cu.tipo_cambio        AS tipo_cambio,
       count(cu)             AS cuentas_con_esa_tasa,
       min(cu.convertido_at) AS primera_conversion,
       max(cu.convertido_at) AS ultima_conversion
ORDER BY cuentas_con_esa_tasa DESC;


// ---------------------------------------------------------------------
// C6. CUENTAS NO PROCESADAS Y SU ESTADO
// ---------------------------------------------------------------------
MATCH (cu:Cuenta)
RETURN coalesce(cu.estado, 'SIN_ESTADO') AS estado, count(cu) AS cuentas
ORDER BY cuentas DESC;

MATCH (cu:Cuenta)
WHERE cu.codigo_verificacion IS NULL
RETURN count(cu) AS cuentas_sin_convertir;


// ---------------------------------------------------------------------
// C7. *** LA CONSULTA DE GRAFO POR EXCELENCIA (20 pts) ***
//     Clientes con MÁS DE UNA cuenta y su saldo total convertido,
//     recorriendo la relación TIENE_CUENTA.
//     Esto en SQL exigiría un JOIN + GROUP BY; aquí es un recorrido directo.
// ---------------------------------------------------------------------
MATCH (cl:Cliente)-[:TIENE_CUENTA]->(cu:Cuenta)
WITH cl, count(cu) AS cuentas_del_cliente, collect(cu.cuentaId) AS ids,
     sum(toFloat(coalesce(cu.saldo_bs, '0'))) AS total_bs
WHERE cuentas_del_cliente > 1
RETURN cl.clienteId          AS cliente_id,
       cuentas_del_cliente,
       ids                   AS cuentas,
       round(total_bs, 4)    AS total_bs_del_cliente
ORDER BY cuentas_del_cliente DESC, total_bs_del_cliente DESC
LIMIT 10;

// Recorrido inverso: dada una cuenta, ¿quién es su titular?
// (cambiar el valor por una cuentaId real obtenida de C3)
MATCH (cl:Cliente)-[:TIENE_CUENTA]->(cu:Cuenta {cuentaId: '1000'})
RETURN cl.clienteId AS cliente, cu.cuentaId AS cuenta, cu.estado AS estado;


// ---------------------------------------------------------------------
// C8. INTEGRIDAD DEL GRAFO
//     Cuentas sin titular y clientes sin cuentas deben ser 0.
//     Además se listan las restricciones de unicidad activas.
// ---------------------------------------------------------------------
MATCH (cu:Cuenta)
WHERE NOT (:Cliente)-[:TIENE_CUENTA]->(cu)
RETURN count(cu) AS cuentas_sin_titular;

MATCH (cl:Cliente)
WHERE NOT (cl)-[:TIENE_CUENTA]->(:Cuenta)
RETURN count(cl) AS clientes_sin_cuentas;

SHOW CONSTRAINTS;
