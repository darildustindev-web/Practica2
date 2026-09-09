<#
.SYNOPSIS
    Abre el Tablero de Entrega en el navegador.

.DESCRIPTION
    Levanta el tablero en http://127.0.0.1:8090 y abre el navegador.

    El tablero muestra los 7 ítems de la rúbrica con su estado REAL (consultado
    contra las bases de datos) y permite ejecutar cada paso de la demostración
    con un botón: verificar entorno, reiniciar todo, levantar servicios, correr
    el barrido, las 8 consultas y la demo de seguridad.

    Escucha sólo en 127.0.0.1: no es accesible desde la red.
    Para cerrarlo, Ctrl+C en esta ventana.

.PARAMETER Puerto
    Puerto donde escuchar. Por defecto 8090.

.PARAMETER SinNavegador
    No abrir el navegador automáticamente.

.EXAMPLE
    .\scripts\windows\Abrir-Tablero.ps1
#>
[CmdletBinding()]
param(
    [int]$Puerto = 8090,
    [switch]$SinNavegador
)

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Raiz

$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Write-Host "No se encontro .venv; se usara el Python del sistema." -ForegroundColor Yellow
    $Python = 'python'
}

$servidor = Join-Path $Raiz 'scripts\tablero\servidor.py'
if (-not (Test-Path $servidor)) {
    Write-Host "No se encontro scripts\tablero\servidor.py" -ForegroundColor Red
    exit 1
}

# Si ya hay algo escuchando en ese puerto, sólo abrimos el navegador.
$enUso = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
         Where-Object { $_.Port -eq $Puerto }
if ($enUso) {
    Write-Host "Ya hay algo escuchando en el puerto $Puerto." -ForegroundColor Yellow
    Write-Host "Si es el tablero, se abrira en el navegador." -ForegroundColor Gray
    if (-not $SinNavegador) { Start-Process "http://127.0.0.1:$Puerto" }
    exit 0
}

Write-Host ""
Write-Host "===============================================================" -ForegroundColor White
Write-Host " TABLERO DE ENTREGA - Practica 2 ASFI/BCB" -ForegroundColor White
Write-Host "===============================================================" -ForegroundColor White
Write-Host ""
Write-Host "  Direccion:  http://127.0.0.1:$Puerto" -ForegroundColor Yellow
Write-Host "  Para cerrarlo: Ctrl+C en esta ventana" -ForegroundColor Gray
Write-Host ""

if (-not $SinNavegador) {
    # Se abre en segundo plano: el servidor tarda un instante en aceptar conexiones.
    Start-Job -ScriptBlock {
        param($p)
        Start-Sleep -Seconds 3
        Start-Process "http://127.0.0.1:$p"
    } -ArgumentList $Puerto | Out-Null
}

& $Python $servidor --puerto $Puerto
