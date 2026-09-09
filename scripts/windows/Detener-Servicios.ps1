<#
.SYNOPSIS
    Detiene el BCB, los 14 bancos y la ASFI, sin tocar las bases de datos.

.DESCRIPTION
    Usa los PID guardados por Levantar-Servicios.ps1 en data\.servicios.pids y,
    como red de seguridad, cierra cualquier uvicorn de este proyecto que haya
    quedado suelto.

    Los contenedores de Docker y los datos NO se tocan: para reiniciar todo
    desde cero usar Reiniciar-Demo.ps1.

.PARAMETER ConDocker
    Además detiene los contenedores (docker compose stop), conservando los datos.
#>
[CmdletBinding()]
param([switch]$ConDocker)

$ErrorActionPreference = 'Continue'
$Raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Raiz

$archivoPids = Join-Path $Raiz 'data\.servicios.pids'
$detenidos = 0

Write-Host ""
Write-Host "Deteniendo servicios..." -ForegroundColor Cyan

if (Test-Path $archivoPids) {
    foreach ($linea in Get-Content $archivoPids) {
        $partes = $linea -split ','
        $identificador = $partes[0]
        $etiqueta = if ($partes.Count -ge 3) { $partes[2] } else { 'servicio' }
        if ($identificador -match '^\d+$') {
            $proceso = Get-Process -Id ([int]$identificador) -ErrorAction SilentlyContinue
            if ($proceso) {
                Stop-Process -Id $proceso.Id -Force -ErrorAction SilentlyContinue
                Write-Host ("  detenido  {0,-34} PID {1}" -f $etiqueta, $identificador) -ForegroundColor Gray
                $detenidos++
            }
        }
    }
    Remove-Item $archivoPids -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "  (no hay data\.servicios.pids; se buscaran procesos sueltos)" -ForegroundColor DarkGray
}

# Red de seguridad: uvicorn de este proyecto que no esté en el archivo de PID.
$sueltos = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*uvicorn*' }
foreach ($p in $sueltos) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host ("  detenido  {0,-34} PID {1}" -f 'uvicorn suelto', $p.ProcessId) -ForegroundColor DarkYellow
    $detenidos++
}

if ($ConDocker) {
    Write-Host ""
    Write-Host "Deteniendo contenedores (los datos se conservan)..." -ForegroundColor Cyan
    # docker escribe su progreso por stderr; con ErrorActionPreference en 'Stop'
    # y un pipe de por medio, PowerShell 5.1 lo convertiria en error fatal.
    # Aqui la preferencia ya es 'Continue' (arriba), pero se deja explicito.
    $previo = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        docker compose stop 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    } finally {
        $ErrorActionPreference = $previo
    }
}

Write-Host ""
Write-Host "Servicios detenidos: $detenidos" -ForegroundColor Green
if (-not $ConDocker) {
    Write-Host "Las bases de datos siguen levantadas con sus datos." -ForegroundColor Gray
    Write-Host "Para borrar todo y empezar de cero: .\scripts\windows\Reiniciar-Demo.ps1" -ForegroundColor Gray
}
Write-Host ""
