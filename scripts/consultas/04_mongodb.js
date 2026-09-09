// =====================================================================
// LAS 8 CONSULTAS - MOTOR 4: MongoDB
// Bancos 8 Prodem, 9 Solidario, 11 FIE, 12 PYME, 14 Nación Argentina
// =====================================================================
// Ejecutar con:  mongosh mongodb://127.0.0.1:27017 --file 04_mongodb.js
// Cambiar BASE por: bank_prodem | bank_solidario | bank_fie | bank_pyme | bank_argentina
//
// Documento de la colección `cuentas`:
//   { nro, id_banco, identificacion, nombres, apellidos, nro_cuenta,
//     saldo (CIFRADO), saldo_bs, codigo_verificacion, tipo_cambio,
//     convertido_at, estado }
//
// PARA LA DEFENSA: `saldo` está cifrado (Blowfish/Twofish/RSA/ElGamal/ChaCha20
// según el banco), por eso no se puede sumar en Mongo. `saldo_bs` sí, porque
// lo escribe la ASFI al confirmar. Las sumas usan $toDecimal sobre saldo_bs.
// =====================================================================

const BASE = "bank_prodem";          // <- cambiar según el banco a mostrar
const BD = db.getSiblingDB(BASE);
const C  = BD.cuentas;

print("=========== BASE: " + BASE + " ===========");

// ---------------------------------------------------------------------
// C1. INVENTARIO Y AVANCE
// ---------------------------------------------------------------------
print("\n--- C1. Inventario y avance ---");
printjson(C.aggregate([
  { $group: {
      _id: "$id_banco",
      total_cuentas: { $sum: 1 },
      convertidas:   { $sum: { $cond: [{ $ifNull: ["$codigo_verificacion", false] }, 1, 0] } },
      pendientes:    { $sum: { $cond: [{ $ifNull: ["$codigo_verificacion", false] }, 0, 1] } }
  }},
  { $addFields: { porcentaje_avance: {
      $round: [{ $multiply: [100, { $divide: ["$convertidas", "$total_cuentas"] }] }, 2] } } }
]).toArray());


// ---------------------------------------------------------------------
// C2. TOTAL CONVERTIDO EN Bs.
// ---------------------------------------------------------------------
print("\n--- C2. Total convertido (Bs.) ---");
printjson(C.aggregate([
  { $match: { saldo_bs: { $ne: null } } },
  { $group: {
      _id: "$id_banco",
      cuentas_convertidas: { $sum: 1 },
      total_bs:    { $sum: { $toDecimal: "$saldo_bs" } },
      promedio_bs: { $avg: { $toDecimal: "$saldo_bs" } },
      minimo_bs:   { $min: { $toDecimal: "$saldo_bs" } },
      maximo_bs:   { $max: { $toDecimal: "$saldo_bs" } }
  }}
]).toArray());


// ---------------------------------------------------------------------
// C3. LADO BANCO DE LA CONSISTENCIA BANCO <-> ASFI
//     Estos valores deben coincidir con asfi_cuentas de la base central.
// ---------------------------------------------------------------------
print("\n--- C3. Consistencia: muestra para comparar con ASFI ---");
printjson(C.find(
  { codigo_verificacion: { $ne: null } },
  { _id: 0, nro: 1, id_banco: 1, saldo_bs: 1, tipo_cambio: 1, codigo_verificacion: 1, convertido_at: 1 }
).sort({ nro: 1 }).limit(10).toArray());


// ---------------------------------------------------------------------
// C4. VALIDACIÓN DEL CÓDIGO DE VERIFICACIÓN (8 hexadecimales)
//     formato_invalido debe ser 0 y no debe haber duplicados.
// ---------------------------------------------------------------------
print("\n--- C4. Códigos de verificación ---");
print("con_codigo:       " + C.countDocuments({ codigo_verificacion: { $ne: null } }));
print("formato_invalido: " + C.countDocuments({
  codigo_verificacion: { $ne: null, $not: /^[0-9A-F]{8}$/ } }));
print("duplicados:");
printjson(C.aggregate([
  { $match: { codigo_verificacion: { $ne: null } } },
  { $group: { _id: "$codigo_verificacion", veces: { $sum: 1 } } },
  { $match: { veces: { $gt: 1 } } },
  { $limit: 10 }
]).toArray());


// ---------------------------------------------------------------------
// C5. AUDITORÍA DEL TIPO DE CAMBIO Y BARRIDO PARALELO
//     Debe salir UNA sola tasa, con ventana de tiempo corta.
// ---------------------------------------------------------------------
print("\n--- C5. Tipo de cambio aplicado ---");
printjson(C.aggregate([
  { $match: { tipo_cambio: { $ne: null } } },
  { $group: {
      _id: "$tipo_cambio",
      cuentas:  { $sum: 1 },
      primera:  { $min: "$convertido_at" },
      ultima:   { $max: "$convertido_at" }
  }},
  { $sort: { cuentas: -1 } }
]).toArray());


// ---------------------------------------------------------------------
// C6. CUENTAS NO PROCESADAS
// ---------------------------------------------------------------------
print("\n--- C6. Cuentas sin convertir ---");
print("sin_convertir: " + C.countDocuments({ codigo_verificacion: null }));
printjson(C.aggregate([
  { $group: { _id: "$estado", cuentas: { $sum: 1 } } }
]).toArray());


// ---------------------------------------------------------------------
// C7. RELACIÓN CLIENTE -> CUENTA
//     El "cliente" es identificacion (cifrada). Agrupando por ese campo se
//     obtiene el equivalente de (:Cliente)-[:TIENE_CUENTA]->(:Cuenta).
// ---------------------------------------------------------------------
print("\n--- C7. Clientes con más cuentas ---");
printjson(C.aggregate([
  { $group: {
      _id: "$identificacion",
      cuentas_del_cliente: { $sum: 1 },
      total_bs: { $sum: { $toDecimal: { $ifNull: ["$saldo_bs", "0"] } } }
  }},
  { $sort: { cuentas_del_cliente: -1 } },
  { $limit: 10 }
]).toArray());


// ---------------------------------------------------------------------
// C8. RANKING E INTEGRIDAD
// ---------------------------------------------------------------------
print("\n--- C8. Top 10 por saldo convertido ---");
printjson(C.aggregate([
  { $match: { saldo_bs: { $ne: null } } },
  { $addFields: { bs: { $toDecimal: "$saldo_bs" } } },
  { $sort: { bs: -1 } },
  { $limit: 10 },
  { $project: { _id: 0, nro: 1, id_banco: 1, saldo_bs: 1, codigo_verificacion: 1 } }
]).toArray());

print("\n--- C8b. Integridad: nro duplicados (debe estar vacío) ---");
printjson(C.aggregate([
  { $group: { _id: "$nro", veces: { $sum: 1 } } },
  { $match: { veces: { $gt: 1 } } },
  { $limit: 10 }
]).toArray());

print("\n--- C8c. Índices de la colección ---");
printjson(C.getIndexes());
