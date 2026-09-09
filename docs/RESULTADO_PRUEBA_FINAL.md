# Resultado de la prueba final con dataset grande

Fecha: 2026-09-09T20:43:41.149245+00:00. Se ejecutó contra los 14 servicios HTTP y los seis motores reales del Docker Compose, con ASFI en SQLite. BCB cambió cada segundo. Bases bancarias y ASFI se iniciaron sin registros previos. La carpeta versionada `data/seed-docente1` se conservó y NO se utilizó; los archivos usados fueron generados en `data/seed` desde `data/dataset.csv`.

| Etapa | Resultado | Tiempo |
|---|---|---:|
| Validación y cifrado | 123,790 filas leídas; 123,785 válidas; 5 rechazadas | 32.99 s |
| Carga paralela | 14 bancos; cero rechazos de carga | 11.85 s |
| Barrido 1 | 123,785 confirmadas; 0 errores | 66.11 s |
| Comparación completa 1 | 123,785 cuentas coinciden | 4.73 s |
| Barrido 2 | 123,785 confirmadas; 0 errores | 67.80 s |
| Comparación completa 2 | 123,785 cuentas coinciden | 4.41 s |

## Recotización

- 123,785 códigos cambiaron y 123,785 tasas cambiaron.
- 123,783 saldos Bs cambiaron; 2 cuentas tienen USD cero y mantienen Bs cero, como corresponde.
- ASFI conservó 123,785 versiones anteriores.
- No hubo referencias faltantes ni adicionales respecto al dataset, ni discrepancias en saldo, tasa, código, fórmula o estado confirmado, en ninguna de las dos comparaciones.

## Auditoría y Twofish

Se comprobaron 2 inicios y 2 finales de barrido. Eventos sin fecha o identificador: 0. Los 17,634 eventos de cuenta del banco 9 (dos rondas) identificaron Twofish TF1 real.

## Pruebas adicionales

20 pruebas y 50 subpruebas de cifrado, auditoría, pipeline, panel y compatibilidad de esquema pasaron. Dos pruebas adicionales verificaron que el nuevo comparador detecta discrepancias y cuentas faltantes. No se ejecutaron los scripts de creación entregables de `scripts/creacion`.

## Reproducir consultas con estas bases cargadas

```bash
.venv/bin/python scripts/verificar_consolidacion.py --source-dir data/seed
```

Ver [GUIA_COMANDOS_DEMOSTRACION.md](GUIA_COMANDOS_DEMOSTRACION.md) para iniciar, consultar cada base y demostrar Neo4j/ASFI. Las bases y servicios se dejaron disponibles al finalizar esta prueba. Los tiempos son mediciones de esta máquina, no garantías para otro hardware o dataset.

Los logs detallados locales están en `data/evidencias`. El informe agregado versionable está en [prueba-final-resultados.json](prueba-final-resultados.json); no contiene datos personales ni saldos individuales.
