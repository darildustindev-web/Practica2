// Ejecutar manualmente con mongosh. La colección materializa cada base.
for (const name of ['bank_prodem','bank_solidario','bank_fie','bank_pyme','bank_argentina']) {
  const bank = db.getSiblingDB(name);
  if (!bank.getCollectionNames().includes('cuentas')) bank.createCollection('cuentas');
  bank.cuentas.createIndex({nro:1}, {unique:true});
  bank.cuentas.createIndex({id_banco:1});
  bank.cuentas.createIndex({codigo_verificacion:1});
}
