# Genera BIOMEC Control.exe y crea su acceso directo en el menú Inicio
# (y opcionalmente en el escritorio), para abrirla como cualquier otra app.
#
#   Uso:   powershell -ExecutionPolicy Bypass -File build_exe.ps1 [-Desktop]
#
param([switch]$Desktop)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Si la app está abierta, Windows bloquea sus archivos y el build sale incompleto.
$running = Get-Process -Name "BIOMEC Control" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "Cerrando BIOMEC Control para poder actualizarla..."
    $running | Stop-Process -Force
    Start-Sleep -Seconds 2
}

$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet -r requirements.txt pyinstaller

# Icono .ico a partir del logo (Qt sabe escribir .ico)
& $py -c "from PySide6.QtGui import QImage; QImage('assets/biomec_logo_dark.png').scaled(256,256).save('assets/biomec.ico')"

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name "BIOMEC Control" `
    --icon "assets\biomec.ico" `
    --add-data "assets;assets" `
    --add-data "config;config" `
    main.py

$exe = Join-Path $PSScriptRoot "dist\BIOMEC Control\BIOMEC Control.exe"
if (-not (Test-Path $exe)) { throw "No se generó el ejecutable" }
$internal = Join-Path $PSScriptRoot "dist\BIOMEC Control\_internal\config\commands.json"
if (-not (Test-Path $internal)) { throw "El build está incompleto (falta _internal). Cierra la app y vuelve a ejecutar el script." }

function New-Shortcut($path) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = Split-Path $exe
    $lnk.IconLocation = $exe
    $lnk.Save()
    Write-Host "Acceso directo: $path"
}

New-Shortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "BIOMEC Control.lnk")
if ($Desktop) { New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "BIOMEC Control.lnk") }

Write-Host "`nListo: $exe"
Write-Host "Búscala en el menú Inicio como 'BIOMEC Control'."
