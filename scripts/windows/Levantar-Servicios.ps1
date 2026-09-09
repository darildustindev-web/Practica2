<#
.SYNOPSIS
    Levanta el BCB, los 14 servicios bancarios y la ASFI en Windows.

.DESCRIPTION
    Arranca 16 procesos de uvicorn, uno por servicio, y guarda sus PID en
    data\.servicios.pids para poder detenerlos después con Detener-Servicios.ps1.

    Puertos:
        8001        Servicio BCB (cotización del dólar)
        8101..8114  Los 14 bancos
        8000        Servicio central ASFI (y panel en /panel)

.PARAMETER Ventanas
    Abre cada servicio en su propia ventana de PowerShell. Sirve para mostrar
    los logs en vivo durante la defensa. Por defecto corren minimizados.

.PARAMETER Bancos
    Lista de bancos a levantar. Por defecto los 14.

.PARAMETER ConSeguridad
    Activa la firma HMAC entre nodos (ASFI y bancos comparten el secreto).
    Sin este parámetro el sistema funciona igual que siempre.

.PARAMETER SinChequeo
    Salta la comprobación previa de que los motores de base de datos estén
    escuchando. Sólo para casos raros: sin bases, los bancos no arrancan.

.EXAMPLE
    .\scripts\windows\Levantar-Servicios.ps1

.EXAMPLE
    .\scripts\windows\Levantar-Servicios.ps1 -Bancos 1,2,3,10 -Ventanas
#>
[CmdletBinding()]
param(
    [switch]$Ventanas,
    [int[]]$Bancos = @(1,2,3,4,5,6,7,8,9,10,11,12,13,14),
    [switch]$ConSeguridad,
    [switch]$SinChequeo
)

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Raiz

$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }

# Motor y cadena de conexión de cada banco (deben coincidir con docker-compose.yml)
$Config = @{
    1  = @{ storage='postgres'; url='postgresql://union_user:union_password@127.0.0.1:5433/bank_union';           nombre='Union (Cesar)' }
    2  = @{ storage='mysql';    url='mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil';    nombre='Mercantil (Atbash)' }
    3  = @{ storage='sqlite';   url=('sqlite:///' + (Join-Path $Raiz 'data\bank_03.sqlite'));                     nombre='BNB (Vigenere)' }
    4  = @{ storage='postgres'; url='postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp';                 nombre='BCP (Playfair)' }
    5  = @{ storage='mysql';    url='mysql://bisa_user:bisa_password@127.0.0.1:3307/bank_bisa';                   nombre='BISA (Hill)' }
    6  = @{ storage='postgres'; url='postgresql://ganadero_user:ganadero_password@127.0.0.1:5436/bank_ganadero';  nombre='Ganadero (DES)' }
    7  = @{ storage='mysql';    url='mysql://economico_user:economico_password@127.0.0.1:3308/bank_economico';    nombre='Economico (3DES)' }
    8  = @{ storage='mongo';    url='mongodb://127.0.0.1:27017/bank_prodem';                                      nombre='Prodem (Blowfish)' }
    9  = @{ storage='mongo';    url='mongodb://127.0.0.1:27017/bank_solidario';                                   nombre='Solidario (Twofish)' }
    10 = @{ storage='redis';    url='redis://127.0.0.1:6379/0#bank10';                                            nombre='Fortaleza (AES)' }
    11 = @{ storage='mongo';    url='mongodb://127.0.0.1:27017/bank_fie';                                         nombre='FIE (RSA)' }
    12 = @{ storage='mongo';    url='mongodb://127.0.0.1:27017/bank_pyme';                                        nombre='PYME (ElGamal)' }
    13 = @{ storage='neo4j';    url='neo4j://neo4j:bdp_password@127.0.0.1:7687';                                  nombre='BDP (ECC) - GRAFO' }
    14 = @{ storage='mongo';    url='mongodb://127.0.0.1:27017/bank_argentina';                                   nombre='Nacion Argentina (ChaCha20)' }
}

$Secreto = if ($ConSeguridad) { 'secreto-compartido-asfi-2026' } else { $null }
$archivoPids = Join-Path $Raiz 'data\.servicios.pids'
New-Item -ItemType Directory -Force -Path (Join-Path $Raiz 'data') | Out-Null
$registro = @()

function Iniciar-Servicio {
    param([string]$Etiqueta, [string]$AppDir, [string]$App, [int]$Puerto, [hashtable]$Entorno)

    $anteriores = @{}
    foreach ($clave in $Entorno.Keys) {
        $anteriores[$clave] = [Environment]::GetEnvironmentVariable($clave)
        [Environment]::SetEnvironmentVariable($clave, $Entorno[$clave])
    }
    try {
        if ($Ventanas) {
            # Cada servicio en su propia ventana, que NO se cierra si el servicio
            # muere: así queda el traceback a la vista. Es el modo de diagnóstico.
            $orden = "& '$Python' -m uvicorn $App --app-dir '$AppDir' --host 127.0.0.1 --port $Puerto"
            $proceso = Start-Process -FilePath 'powershell.exe' `
                                     -ArgumentList @('-NoExit','-NoProfile','-Command', $orden) `
                                     -WorkingDirectory $Raiz -WindowStyle Normal -PassThru
        }
        else {
            $argumentos = @('-m','uvicorn',$App,'--app-dir',$AppDir,'--host','127.0.0.1','--port',$Puerto)
            $proceso = Start-Process -FilePath $Python -ArgumentList $argumentos `
                                     -WorkingDirectory $Raiz -WindowStyle Minimized -PassThru
        }
        Write-Host ("  {0,-40} puerto {1}   PID {2}" -f $Etiqueta, $Puerto, $proceso.Id) -ForegroundColor Gray
        return "$($proceso.Id),$Puerto,$Etiqueta"
    }
    finally {
        foreach ($clave in $anteriores.Keys) {
            [Environment]::SetEnvironmentVariable($clave, $anteriores[$clave])
        }
    }
}

Write-Host ""
Write-Host "===============================================================" -ForegroundColor White
Write-Host " LEVANTANDO SERVICIOS - Practica 2 ASFI/BCB" -ForegroundColor White
Write-Host "===============================================================" -ForegroundColor White
if ($ConSeguridad) { Write-Host " Firma HMAC entre nodos: ACTIVADA" -ForegroundColor Yellow }
Write-Host ""

# --- 0. Comprobacion previa: los motores tienen que estar escuchando ---
# Sin esto, los bancos arrancan, no pueden conectarse a su base y mueren en
# silencio: el sintoma es "no respondieron los puertos 8101, 8102, ..." y no
# dice por que. Este chequeo lo dice antes de arrancar nada.
function Test-Puerto {
    param([int]$Puerto)
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $intento = $cliente.BeginConnect('127.0.0.1', $Puerto, $null, $null)
        if (-not $intento.AsyncWaitHandle.WaitOne(700)) { return $false }
        $cliente.EndConnect($intento)
        return $true
    } catch { return $false }
    finally { $cliente.Close() }
}

if (-not $SinChequeo) {
    # Puerto de base que necesita cada banco (el 3 usa SQLite: archivo local).
    $PuertoDeBanco = @{
        1=5433; 2=3306; 4=5435; 5=3307; 6=5436; 7=3308
        8=27017; 9=27017; 10=6379; 11=27017; 12=27017; 13=7687; 14=27017
    }
    $necesarios = [System.Collections.Generic.SortedSet[int]]::new()
    [void]$necesarios.Add(5434)   # PostgreSQL de la ASFI: siempre hace falta
    foreach ($b in $Bancos) { if ($PuertoDeBanco.ContainsKey($b)) { [void]$necesarios.Add($PuertoDeBanco[$b]) } }

    $caidos = @($necesarios | Where-Object { -not (Test-Puerto $_) })
    if ($caidos.Count -gt 0) {
        Write-Host "  Las bases de datos no estan escuchando: $($caidos -join ', ')" -ForegroundColor Red
        Write-Host ""
        Write-Host "  Los bancos no pueden arrancar sin su base. Antes de levantar" -ForegroundColor Yellow
        Write-Host "  los servicios hay que reconstruir el entorno:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "      .\scripts\windows\Reiniciar-Demo.ps1" -ForegroundColor White
        Write-Host ""
        Write-Host "  (si los contenedores ya estan cargados y solo estan apagados," -ForegroundColor Gray
        Write-Host "   alcanza con:  docker compose up -d )" -ForegroundColor Gray
        Write-Host ""
        exit 1
    }
    Write-Host ("  Bases de datos escuchando: {0}" -f ($necesarios -join ', ')) -ForegroundColor DarkGray
    Write-Host ""
}

# --- 1. BCB -----------------------------------------------------------
Write-Host "Servicio BCB (cotizacion del dolar)" -ForegroundColor Cyan
$entornoBcb = @{ 'BCB_UPDATE_INTERVAL' = '180' }
$registro += Iniciar-Servicio -Etiqueta 'BCB' -AppDir (Join-Path $Raiz 'bcb-service') `
                              -App 'main:app' -Puerto 8001 -Entorno $entornoBcb

# --- 2. Bancos --------------------------------------------------------
Write-Host ""
Write-Host "Servicios bancarios" -ForegroundColor Cyan
foreach ($banco in $Bancos) {
    if (-not $Config.ContainsKey($banco)) { continue }
    $c = $Config[$banco]
    $entorno = @{
        'BANK_ID'      = "$banco"
        'BANK_STORAGE' = $c.storage
        'DATABASE_URL' = $c.url
    }
    if ($Secreto) { $entorno['ASFI_HMAC_SECRET'] = $Secreto }
    $etiqueta = "Banco $banco - $($c.nombre)"
    $registro += Iniciar-Servicio -Etiqueta $etiqueta -AppDir (Join-Path $Raiz 'banks-services') `
                                  -App 'bank_template.main:app' -Puerto (8100 + $banco) -Entorno $entorno
}

# --- 3. ASFI ----------------------------------------------------------
Write-Host ""
Write-Host "Servicio central ASFI" -ForegroundColor Cyan
$entornoAsfi = @{
    'BCB_URL'            = 'http://127.0.0.1:8001/api/bcb/tipo-cambio'
    'ACTIVE_BANK_IDS'    = ($Bancos -join ',')
    'ASFI_DATABASE_URL'  = 'postgresql://asfi_user:asfi_password@127.0.0.1:5434/asfi_db'
    'ASFI_AUDIT_FILE'    = (Join-Path $Raiz 'data\audit.jsonl')
    'ASFI_BATCH_SIZE'    = '500'
    'ASFI_CRYPTO_WORKERS'= '2'
}
foreach ($banco in $Bancos) { $entornoAsfi["BANK_URL_$banco"] = "http://127.0.0.1:$(8100 + $banco)/api/banco" }
if ($Secreto) { $entornoAsfi['ASFI_HMAC_SECRET'] = $Secreto }
$registro += Iniciar-Servicio -Etiqueta 'ASFI (central)' -AppDir (Join-Path $Raiz 'asfi-service') `
                              -App 'main:app' -Puerto 8000 -Entorno $entornoAsfi

$registro | Set-Content -Path $archivoPids -Encoding UTF8

# --- 4. Comprobar salud ----------------------------------------------
Write-Host ""
Write-Host "Esperando a que respondan (hasta 60 s)..." -ForegroundColor Cyan
$puertos = @(8001) + ($Bancos | ForEach-Object { 8100 + $_ }) + @(8000)
$limite = (Get-Date).AddSeconds(60)
$pendientes = [System.Collections.ArrayList]@($puertos)

while ($pendientes.Count -gt 0 -and (Get-Date) -lt $limite) {
    foreach ($puerto in @($pendientes)) {
        try {
            $ruta = if ($puerto -eq 8000) { '/' } else { '/health' }
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$puerto$ruta" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $pendientes.Remove($puerto) }
        } catch { }
    }
    if ($pendientes.Count -gt 0) { Start-Sleep -Seconds 2 }
}

Write-Host ""
if ($pendientes.Count -eq 0) {
    Write-Host "===============================================================" -ForegroundColor Green
    Write-Host " LOS $($puertos.Count) SERVICIOS ESTAN ARRIBA" -ForegroundColor Green
    Write-Host "===============================================================" -ForegroundColor Green
} else {
    Write-Host "No respondieron los puertos: $($pendientes -join ', ')" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Causa mas probable, en orden:" -ForegroundColor White
    Write-Host "  1. Las bases estan vacias (nunca se completo Reiniciar-Demo.ps1)." -ForegroundColor Gray
    Write-Host "     -> .\scripts\windows\Reiniciar-Demo.ps1" -ForegroundColor Gray
    Write-Host "  2. Falta alguna dependencia de Python." -ForegroundColor Gray
    Write-Host "     -> .venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Gray
    Write-Host "  3. Otra cosa: hay que ver el error real de cada servicio." -ForegroundColor Gray
    Write-Host "     -> .\scripts\windows\Detener-Servicios.ps1" -ForegroundColor Gray
    Write-Host "     -> .\scripts\windows\Levantar-Servicios.ps1 -Ventanas" -ForegroundColor Gray
    Write-Host "        (cada servicio abre su propia ventana con el traceback)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host " Ejecutar el barrido de conversion:" -ForegroundColor White
Write-Host "   curl.exe -X POST http://127.0.0.1:8000/api/asfi/ejecutar-conversion" -ForegroundColor Yellow
Write-Host ""
Write-Host " Panel de monitoreo:  http://127.0.0.1:8000/panel" -ForegroundColor White
Write-Host " Neo4j (grafo):       http://127.0.0.1:7474" -ForegroundColor White
Write-Host ""
Write-Host " Para detener todo:   .\scripts\windows\Detener-Servicios.ps1" -ForegroundColor White
Write-Host ""
