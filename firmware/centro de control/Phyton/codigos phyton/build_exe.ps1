# Genera BIOMEC Control.exe en dist\ y crea el acceso directo "BIOMEC Control (desarrollo)" en el
# menú Inicio (y opcionalmente en el escritorio) para probar la versión que estás programando.
# La app para el equipo (instalador + actualizaciones) la genera y publica release.ps1.
#
#   Uso:   powershell -ExecutionPolicy Bypass -File build_exe.ps1 [-Desktop] [-NoShortcut]
#
param([switch]$Desktop, [switch]$NoShortcut)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$dist = Join-Path $PSScriptRoot "dist"

# Si la copia de dist\ está abierta, Windows bloquea sus archivos y el build sale incompleto.
# (La app instalada no molesta: está en otra carpeta.)
$running = @(Get-Process -Name "BIOMEC Control" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($dist, [StringComparison]::OrdinalIgnoreCase) })
# No se cierra sola: puede estar en uso (conectada a la mano, grabando...). Se para y se avisa.
if ($running.Count) {
    throw ("BIOMEC Control está abierta desde dist\ ($($running.Count) ventana(s)). Ciérrala y vuelve a " +
           "ejecutar el script (o usa la app instalada, que está en otra carpeta y no molesta).")
}

$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet -r requirements.txt pyinstaller

# Icono .ico: la misma insignia que usa la app (Qt sabe escribir .ico)
& $py -c "from biomec.ui.icons import save_app_icon; save_app_icon('assets/biomec.ico')"

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name "BIOMEC Control" `
    --icon "assets\biomec.ico" `
    --add-data "assets;assets" `
    --add-data "config;config" `
    --collect-binaries vosk `
    main.py

$exe = Join-Path $dist "BIOMEC Control\BIOMEC Control.exe"
if (-not (Test-Path $exe)) { throw "No se generó el ejecutable" }
$internal = Join-Path $dist "BIOMEC Control\_internal\config\commands.json"
if (-not (Test-Path $internal)) { throw "El build está incompleto (falta _internal). Cierra la app y vuelve a ejecutar el script." }

# Autodiagnóstico: el .exe importa todo lo que necesita (numpy, OpenGL, el SDK de Claude...) y sale
$check = Start-Process -FilePath $exe -ArgumentList "--selftest" -Wait -PassThru
$report = Join-Path $env:TEMP "biomec_selftest.txt"
if (Test-Path $report) { Get-Content $report | ForEach-Object { Write-Host "  $_" } }
if ($check.ExitCode -ne 0) { throw "El autodiagnóstico del .exe ha fallado (ver arriba)." }

if ($NoShortcut) {
    Write-Host "`nListo: $exe"
    exit 0
}

$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = Split-Path $exe
    $lnk.IconLocation = $exe
    $lnk.Save()
    Write-Host "Acceso directo: $path"
}

$folders = @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))
foreach ($folder in $folders) {
    # Antes este script creaba "BIOMEC Control": ese nombre es ahora el de la app instalada.
    $old = Join-Path $folder "BIOMEC Control.lnk"
    if ((Test-Path $old) -and ($shell.CreateShortcut($old).TargetPath -eq $exe)) { Remove-Item $old }
}
New-Shortcut (Join-Path $folders[0] "BIOMEC Control (desarrollo).lnk")
if ($Desktop) { New-Shortcut (Join-Path $folders[1] "BIOMEC Control (desarrollo).lnk") }

Write-Host "`nListo: $exe"
Write-Host "Búscala en el menú Inicio como 'BIOMEC Control (desarrollo)'."
