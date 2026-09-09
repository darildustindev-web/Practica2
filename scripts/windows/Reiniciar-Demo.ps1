<#
.SYNOPSIS
    Deja la Práctica 2 como recién instalada y lista para volver a demostrar.

.DESCRIPTION
    Ejecutar esto DESPUÉS de una demostración para poder repetirla desde cero.
    Hace ocho pasos:
      1. Detiene los servicios Python que quedaron corriendo.
      2. Borra los contenedores Y SUS VOLÚMENES (las 14 bases quedan vacías).
      3. Limpia data\seed, el log de auditoría y las bases locales SQLite.
      4. Vuelve a levantar los contenedores.
      5. Espera a que los 10 motores acepten conexiones de verdad.
      6. Vuelve a cifrar el dataset del docente (seeder).
      7. VERIFICA que los saldos descifrados coincidan con el CSV original.
      8. Carga los 14 bancos y crea las tablas Bancos/Cuentas del enunciado.

    Al terminar sólo queda levantar los servicios:
        .\scripts\windows\Levantar-Servicios.ps1

    Funciona igual en Windows PowerShell 5.1 y en PowerShell 7.

.PARAMETER SoloLimpiar
    Sólo borra (pasos 1 a 3). No levanta ni vuelve a cargar nada.

.PARAMETER BorrarLlaves
    Además borra data\keys (RSA del Banco 11 y ECC del Banco 13). Se regeneran
    en el siguiente sembrado. Úsalo sólo si querés partir absolutamente de cero.

.PARAMETER Rapido
    Siembra y carga sólo los bancos 1, 2, 3 y 10 (un motor de cada tipo).
    Útil para ensayar la demostración sin esperar el dataset completo.

.EXAMPLE
    .\scripts\windows\Reiniciar-Demo.ps1
    Reinicio completo: todo queda listo para volver a demostrar.

.EXAMPLE
    .\scripts\windows\Reiniciar-Demo.ps1 -SoloLimpiar
    Deja todo apagado y limpio, sin volver a cargar datos.
#>
[CmdletBinding()]
param(
    [switch]$SoloLimpiar,
    [switch]$BorrarLlaves,
    [switch]$Rapido
)

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Raiz

function Paso([int]$n, [string]$texto) {
    Write-Host ""
    Write-Host ("[{0}/8] {1}" -f $n, $texto) -ForegroundColor Cyan
    Write-Host ("      " + ("-" * 62)) -ForegroundColor DarkGray
}
function Ok([string]$t)    { Write-Host "      OK   $t" -ForegroundColor Green }
function Aviso([string]$t) { Write-Host "      !    $t" -ForegroundColor Yellow }
function Error2([string]$t){ Write-Host "      X    $t" -ForegroundColor Red }

# ---------------------------------------------------------------------
# Ejecuta un programa externo sin que PowerShell trate su salida de error
# como un error fatal.
#
# Por qué hace falta: docker escribe su progreso ("Container ... Stopping")
# por stderr, no por stdout. En Windows PowerShell 5.1, si esa salida pasa
# por un pipe mientras $ErrorActionPreference vale 'Stop', PowerShell la
# convierte en un NativeCommandError TERMINANTE y corta el script a la
# mitad, aunque docker haya funcionado perfecto. Aquí se baja la
# preferencia mientras corre el comando y se restaura después; el código de
# salida real queda en $LASTEXITCODE.
# ---------------------------------------------------------------------
function Invoke-Nativo {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Programa,
        [string[]]$Argumentos = @()
    )
    $previo = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Programa @Argumentos 2>&1 | ForEach-Object { "$_" }
    }
    finally {
        $ErrorActionPreference = $previo
    }
}

# Igual que arriba, pero para el intérprete de Python. La salida se manda a la
# consola con Write-Host (no al pipeline), así lo único que devuelve la función
# es el código de salida.
function Invoke-Python {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string[]]$Argumentos)
    $previo = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Python @Argumentos 2>&1 | ForEach-Object { Write-Host "$_" }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previo
    }
}

# Intérprete de Python: preferir el entorno virtual del proyecto.
$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    $Python = 'python'
    Aviso "No se encontro .venv; se usara el Python del sistema."
}

Write-Host ""
Write-Host "===============================================================" -ForegroundColor White
Write-Host " REINICIO DE LA DEMOSTRACION - Practica 2 ASFI/BCB" -ForegroundColor White
Write-Host " Carpeta: $Raiz" -ForegroundColor DarkGray
Write-Host " PowerShell $($PSVersionTable.PSVersion)" -ForegroundColor DarkGray
Write-Host "===============================================================" -ForegroundColor White

# ---------------------------------------------------------------------
Paso 1 "Deteniendo los servicios Python (BCB, 14 bancos y ASFI)"
# ---------------------------------------------------------------------
$archivoPids = Join-Path $Raiz 'data\.servicios.pids'
$detenidos = 0
if (Test-Path $archivoPids) {
    foreach ($linea in Get-Content $archivoPids) {
        $identificador = ($linea -split ',')[0]
        if ($identificador -match '^\d+$') {
            $proceso = Get-Process -Id ([int]$identificador) -ErrorAction SilentlyContinue
            if ($proceso) { Stop-Process -Id $proceso.Id -Force -ErrorAction SilentlyContinue; $detenidos++ }
        }
    }
    Remove-Item $archivoPids -Force -ErrorAction SilentlyContinue
}
# Red de seguridad: cualquier uvicorn de este proyecto que haya quedado suelto.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*uvicorn*' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $detenidos++
    }
Ok "Servicios detenidos: $detenidos"

# ---------------------------------------------------------------------
Paso 2 "Borrando contenedores y volumenes (las bases quedan vacias)"
# ---------------------------------------------------------------------
if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
    Error2 "No se encontro 'docker'. Abri Docker Desktop y volve a intentar."
    exit 1
}
Invoke-Nativo docker @('compose','down','-v') |
    ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Aviso "docker compose down devolvio codigo $LASTEXITCODE (normal si no habia nada levantado)."
}
Ok "Contenedores y volumenes eliminados"

# ---------------------------------------------------------------------
Paso 3 "Limpiando archivos de la corrida anterior"
# ---------------------------------------------------------------------
$aBorrar = @(
    'data\seed',
    'data\audit.jsonl',
    'data\asfi.sqlite', 'data\asfi.sqlite.lock', 'data\asfi.sqlite-wal', 'data\asfi.sqlite-shm',
    'data\bank_03.sqlite', 'data\bank_03.sqlite-journal',
    'data\asfi-conversion.lock',
    'data\.servicios.pids',
    'docs\evidencia-consultas.txt'
)
if ($BorrarLlaves) { $aBorrar += 'data\keys' }

foreach ($elemento in $aBorrar) {
    $ruta = Join-Path $Raiz $elemento
    if (Test-Path $ruta) {
        Remove-Item $ruta -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "      borrado: $elemento" -ForegroundColor DarkGray
    }
}
if ($BorrarLlaves) { Aviso "Se borraron las llaves RSA/ECC: se regeneran al sembrar." }
Ok "Archivos de la corrida anterior eliminados"

if ($SoloLimpiar) {
    Write-Host ""
    Write-Host "Listo: todo apagado y limpio (-SoloLimpiar)." -ForegroundColor Green
    Write-Host "Para reconstruir: .\scripts\windows\Reiniciar-Demo.ps1" -ForegroundColor Gray
    exit 0
}

# ---------------------------------------------------------------------
Paso 4 "Levantando los contenedores de base de datos"
# ---------------------------------------------------------------------
Invoke-Nativo docker @('compose','up','-d') |
    ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Error2 "docker compose up fallo (codigo $LASTEXITCODE). Revisa el detalle de arriba."
    exit 1
}
Ok "Contenedores levantados"

# ---------------------------------------------------------------------
Paso 5 "Esperando a que los 10 motores acepten conexiones"
# ---------------------------------------------------------------------
$codigo = Invoke-Python @((Join-Path $Raiz 'scripts\esperar_bases.py'), '--timeout', '240')
if ($codigo -ne 0) { Error2 "Alguna base no respondio a tiempo."; exit 1 }
Ok "Todos los motores responden"

# ---------------------------------------------------------------------
Paso 6 "Cifrando el dataset del docente (seeder)"
# ---------------------------------------------------------------------
$dataset = Join-Path $Raiz 'data\dataset.csv'
if (-not (Test-Path $dataset)) {
    Error2 "No se encontro data\dataset.csv. Copia ahi el dataset del docente."
    exit 1
}
$codigo = Invoke-Python @(
    (Join-Path $Raiz 'scripts\seeder.py'),
    $dataset,
    '--output-dir', (Join-Path $Raiz 'data\seed'),
    '--workers', '4'
)
if ($codigo -ne 0) { Error2 "El seeder fallo."; exit 1 }
Ok "Dataset cifrado en data\seed"

# ---------------------------------------------------------------------
Paso 7 "Verificando que los saldos coincidan con el CSV original"
# ---------------------------------------------------------------------
$codigo = Invoke-Python @((Join-Path $Raiz 'scripts\verificar_saldos.py'))
if ($codigo -ne 0) {
    Error2 "Los saldos NO coinciden con el dataset. No se cargaran las bases."
    Error2 "Revisa shared\money.py antes de continuar."
    exit 1
}
Ok "Saldos verificados contra data\dataset.csv"

# ---------------------------------------------------------------------
Paso 8 "Cargando los 14 bancos y creando las tablas del enunciado"
# ---------------------------------------------------------------------
$bancos = if ($Rapido) { '1,2,3,10' } else { '1,2,3,4,5,6,7,8,9,10,11,12,13,14' }
if ($Rapido) { Aviso "Modo rapido: solo bancos $bancos" }

$codigo = Invoke-Python @(
    (Join-Path $Raiz 'scripts\load_all.py'),
    '--source-dir', (Join-Path $Raiz 'data\seed'),
    '--banks', $bancos
)
if ($codigo -ne 0) { Error2 "La carga de alguna base fallo (ver el detalle arriba)."; exit 1 }
Ok "Bases cargadas"

# Tablas Bancos / Cuentas con los nombres exactos del enunciado.
$scriptVistas = Join-Path $Raiz 'scripts\creacion\asfi_vistas_enunciado.sql'
if (Test-Path $scriptVistas) {
    # Se copia el archivo al contenedor en vez de mandarlo por un pipe: PowerShell
    # puede alterar la codificacion y el script tiene acentos (Union, Economico...).
    Invoke-Nativo docker @('cp', $scriptVistas, 'asfi-db:/tmp/asfi_vistas.sql') | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Invoke-Nativo docker @(
            'exec','asfi-db','psql','-U','asfi_user','-d','asfi_db',
            '-v','ON_ERROR_STOP=1','-f','/tmp/asfi_vistas.sql'
        ) | Select-Object -Last 4 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -eq 0) { Ok "Tablas Bancos y vista Cuentas creadas en asfi_db" }
        else { Aviso "No se pudieron crear las tablas del enunciado (revisa asfi-db)." }
    } else {
        Aviso "No se pudo copiar el script al contenedor asfi-db."
    }
}

# ---------------------------------------------------------------------
Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host " TODO REINICIADO Y LISTO PARA VOLVER A DEMOSTRAR" -ForegroundColor Green
Write-Host "===============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Siguiente paso:" -ForegroundColor White
Write-Host "   .\scripts\windows\Levantar-Servicios.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host " Y despues, para ejecutar el barrido:" -ForegroundColor White
Write-Host "   curl.exe -X POST http://127.0.0.1:8000/api/asfi/ejecutar-conversion" -ForegroundColor Yellow
Write-Host ""
