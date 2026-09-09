<#
.SYNOPSIS
    Comprueba que esta máquina Windows puede correr la Práctica 2.

.DESCRIPTION
    Ejecutar ANTES de la defensa. Revisa, en orden:
      1. Python 3.11 o superior
      2. Entorno virtual .venv creado
      3. Dependencias instaladas (los 6 drivers de base de datos)
      4. Bloqueo de archivos en Windows (kernel32/LockFileEx)
      5. Que no queden dependencias de Unix (fcntl / resource) en el código
      6. Docker disponible y corriendo
      7. Dataset del docente presente
      8. Puertos libres

    Cada punto dice qué hacer si falla.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$Raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Raiz

$fallos = 0
$avisos = 0

function Titulo([string]$t) {
    Write-Host ""
    Write-Host $t -ForegroundColor Cyan
    Write-Host ("-" * 63) -ForegroundColor DarkGray
}
function Bien([string]$t)  { Write-Host "  [OK]    $t" -ForegroundColor Green }
function Mal ([string]$t, [string]$arreglo) {
    Write-Host "  [FALLO] $t" -ForegroundColor Red
    Write-Host "          -> $arreglo" -ForegroundColor Yellow
    $script:fallos++
}
function Ojo ([string]$t, [string]$nota) {
    Write-Host "  [AVISO] $t" -ForegroundColor Yellow
    Write-Host "          -> $nota" -ForegroundColor DarkYellow
    $script:avisos++
}

Write-Host ""
Write-Host "===============================================================" -ForegroundColor White
Write-Host " VERIFICACION DEL ENTORNO WINDOWS - Practica 2 ASFI/BCB" -ForegroundColor White
Write-Host (" PowerShell {0} ({1})" -f $PSVersionTable.PSVersion, $PSVersionTable.PSEdition) -ForegroundColor DarkGray
Write-Host "===============================================================" -ForegroundColor White

# ---------------------------------------------------------------- 1
Titulo "1. Python"
$PythonSistema = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonSistema) {
    Mal "No se encontro 'python' en el PATH." "Instala Python 3.11+ desde python.org y marca 'Add to PATH'."
} else {
    $version = (& python --version 2>&1) -replace 'Python ',''
    $partes = $version.Split('.')
    if ([int]$partes[0] -ge 3 -and [int]$partes[1] -ge 11) { Bien "Python $version" }
    else { Mal "Python $version es muy antiguo." "El proyecto necesita Python 3.11 o superior." }
}

# ---------------------------------------------------------------- 2
Titulo "2. Entorno virtual"
$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
if (Test-Path $Python) { Bien "Encontrado .venv\Scripts\python.exe" }
else {
    Ojo "No existe .venv" "Crealo con:  python -m venv .venv"
    $Python = 'python'
}

# ---------------------------------------------------------------- 3
Titulo "3. Dependencias de Python"
$modulos = @{
    'fastapi'   = 'API de los servicios'
    'uvicorn'   = 'servidor de los servicios'
    'httpx'     = 'cliente HTTP de la ASFI'
    'psycopg2'  = 'PostgreSQL'
    'pymysql'   = 'MySQL'
    'pymongo'   = 'MongoDB'
    'redis'     = 'Redis'
    'neo4j'     = 'Neo4j'
    'Crypto'    = 'pycryptodome (DES, AES, ChaCha20...)'
    'cryptography' = 'ECC'
}
$faltan = @()
foreach ($modulo in $modulos.Keys) {
    & $Python -c "import $modulo" 2>$null
    if ($LASTEXITCODE -eq 0) { Bien "$modulo  ($($modulos[$modulo]))" }
    else { $faltan += $modulo; Write-Host "  [FALTA] $modulo  ($($modulos[$modulo]))" -ForegroundColor Red }
}
if ($faltan.Count -gt 0) {
    Mal "Faltan $($faltan.Count) modulos." ".venv\Scripts\python.exe -m pip install -r requirements.txt"
}

# ---------------------------------------------------------------- 4
Titulo "4. Bloqueo de archivos en Windows (kernel32)"
& $Python (Join-Path $Raiz 'shared\portable.py')
if ($LASTEXITCODE -eq 0) { Bien "El bloqueo compartido y exclusivo funciona" }
else { Mal "El bloqueo de archivos fallo." "Revisa shared\portable.py; sin esto el seeder y la ASFI no arrancan." }

# ---------------------------------------------------------------- 5
Titulo "5. Dependencias de Unix en el codigo"
$archivosPy = Get-ChildItem -Path $Raiz -Filter *.py -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike '*__pycache__*' -and
                   $_.FullName -notlike '*\.venv\*' -and
                   $_.Name -ne 'portable.py' }
$unix = $archivosPy | Select-String -Pattern 'import fcntl|import resource' -ErrorAction SilentlyContinue
if ($unix) {
    foreach ($u in $unix) { Write-Host "  $($u.Path):$($u.LineNumber)" -ForegroundColor Red }
    Mal "Quedan imports que solo existen en Linux." "Deben usar shared\portable.py"
} else {
    Bien "No quedan imports de fcntl ni resource fuera de portable.py"
}

# ---------------------------------------------------------------- 6
Titulo "6. Docker"
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Bien "Docker responde"
        $activos = (docker compose ps --status running --format '{{.Name}}' 2>$null | Measure-Object -Line).Lines
        if ($activos -ge 10) { Bien "Contenedores corriendo: $activos" }
        elseif ($activos -gt 0) { Ojo "Solo $activos contenedores corriendo (se esperan 10)" "docker compose up -d" }
        else { Ojo "No hay contenedores corriendo" "docker compose up -d" }
    } else {
        Mal "Docker esta instalado pero no responde." "Abri Docker Desktop y espera a que diga 'Engine running'."
    }
} else {
    Mal "No se encontro 'docker'." "Instala Docker Desktop para Windows."
}

# ---------------------------------------------------------------- 7
Titulo "7. Dataset del docente"
$dataset = Join-Path $Raiz 'data\dataset.csv'
if (Test-Path $dataset) {
    $filas = (Get-Content $dataset -ReadCount 0).Count - 1
    $mb = [math]::Round((Get-Item $dataset).Length / 1MB, 2)
    Bien "data\dataset.csv presente ($filas filas, $mb MB)"
} else {
    Mal "No se encontro data\dataset.csv" "Copia ahi el CSV que entrego el docente."
}

# ---------------------------------------------------------------- 8
Titulo "8. Puertos"
$puertos = @{ 8000='ASFI'; 8001='BCB'; 5433='PG Union'; 5434='PG ASFI'; 3306='MySQL Mercantil'; 27017='MongoDB'; 6379='Redis'; 7687='Neo4j' }
foreach ($puerto in ($puertos.Keys | Sort-Object)) {
    $escuchando = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    $ocupado = $escuchando | Where-Object { $_.Port -eq $puerto }
    if ($ocupado) { Write-Host "  [uso]   $puerto  $($puertos[$puerto])  (ya hay algo escuchando)" -ForegroundColor DarkGray }
    else { Write-Host "  [libre] $puerto  $($puertos[$puerto])" -ForegroundColor DarkGray }
}
Write-Host "  (que un puerto de base este 'en uso' es normal si Docker ya esta levantado)" -ForegroundColor DarkGray

# ---------------------------------------------------------------- resumen
Write-Host ""
Write-Host "===============================================================" -ForegroundColor White
if ($fallos -eq 0) {
    Write-Host " ENTORNO LISTO  (avisos: $avisos)" -ForegroundColor Green
    Write-Host "===============================================================" -ForegroundColor White
    Write-Host ""
    Write-Host " Siguiente paso:  .\scripts\windows\Reiniciar-Demo.ps1" -ForegroundColor Yellow
} else {
    Write-Host " HAY $fallos PROBLEMA(S) QUE RESOLVER" -ForegroundColor Red
    Write-Host "===============================================================" -ForegroundColor White
}
Write-Host ""
exit $fallos
