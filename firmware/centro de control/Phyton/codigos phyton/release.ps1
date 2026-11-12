# Publica una versión nueva de BIOMEC Control para el equipo.
#
#   Antes:  1) sube APP_VERSION en biomec/__init__.py (p. ej. 0.3.0 -> 0.3.1)
#           2) escribe sus novedades en CHANGELOG.md, en un apartado "## 0.3.1"
#           3) sube el código a GitHub (rama pruebasHugo)
#   Uso:    powershell -ExecutionPolicy Bypass -File release.ps1                  (genera y publica)
#           powershell -ExecutionPolicy Bypass -File release.ps1 -SoloInstalador  (solo el instalador)
#
# Pasa las pruebas, genera el .exe, crea el instalador con Inno Setup y lo publica en GitHub Releases
# con la etiqueta control-vX.Y.Z. Las apps instaladas lo ven al arrancar y se actualizan con un clic.
param([switch]$SoloInstalador)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Repo = "biomec-uma/Pr-tesis.V"
$Rama = "pruebasHugo"
$AppPath = "firmware/centro de control/Phyton/codigos phyton"   # carpeta de la app en el repositorio del equipo
$py = ".\.venv\Scripts\python.exe"

$version = (& $py -c "import biomec; print(biomec.APP_VERSION)").Trim()
$tag = "control-v$version"
Write-Host "BIOMEC Control $version  ($tag)" -ForegroundColor Cyan

# Novedades de esta versión: el apartado de CHANGELOG.md
$notes = Join-Path $env:TEMP "biomec_novedades_$version.md"
& $py -m biomec.core.updates notas $version $notes
if ($LASTEXITCODE -ne 0) { throw "CHANGELOG.md no tiene un apartado '## $version': escribe las novedades antes de publicar." }

# 1. Pruebas automáticas
& $py -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallan: no se publica." }

# 2. El .exe (sin accesos directos: los crea el instalador)
& powershell -NoProfile -ExecutionPolicy Bypass -File build_exe.ps1 -NoShortcut
if ($LASTEXITCODE -ne 0) { throw "No se pudo generar el .exe." }

# 3. El instalador (Inno Setup 6) y su huella SHA-256
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Falta Inno Setup 6. Instálalo con:  winget install JRSoftware.InnoSetup" }
& $iscc /Qp "/DAppVersion=$version" "installer\biomec_control.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup no pudo crear el instalador." }
$setup = Join-Path $PSScriptRoot "dist\BIOMEC-Control-Setup-$version.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$setup.sha256", "$hash  BIOMEC-Control-Setup-$version.exe`n")
Write-Host ("Instalador: {0}  ({1:N0} MB)" -f $setup, ((Get-Item $setup).Length / 1MB))
if ($SoloInstalador) { exit 0 }

# 4. La etiqueta se crea sobre la rama de GitHub: el código de esta versión tiene que estar subido
$raw = "https://raw.githubusercontent.com/$Repo/$Rama/" + ($AppPath -replace " ", "%20") + "/biomec/__init__.py"
$remote = (Invoke-WebRequest -UseBasicParsing $raw).Content
if ($remote -notmatch ('APP_VERSION = "' + [regex]::Escape($version) + '"')) {
    throw "La rama $Rama de GitHub no tiene la versión $version. Sube el código antes de publicar (si acabas de subirlo, espera un par de minutos)."
}

# 5. Publicar en GitHub Releases
if (Get-Command gh -ErrorAction SilentlyContinue) {
    gh release create $tag $setup "$setup.sha256" --repo $Repo --target $Rama --title "BIOMEC Control $version" --notes-file $notes
    if ($LASTEXITCODE -ne 0) { throw "GitHub CLI no pudo publicar (¿ya existe la versión $version? ¿has hecho 'gh auth login'?)." }
    Write-Host "Publicada: https://github.com/$Repo/releases/tag/$tag" -ForegroundColor Green
} else {
    # Sin GitHub CLI: se abre la página de nueva versión con la etiqueta y el título puestos
    $title = [uri]::EscapeDataString("BIOMEC Control $version")
    Start-Process "https://github.com/$Repo/releases/new?tag=$tag&target=$Rama&title=$title"
    Start-Process explorer.exe "/select,`"$setup`""
    Get-Content $notes -Encoding UTF8 | Set-Clipboard
    Write-Host "En la página que se ha abierto: arrastra el instalador y su .sha256 (carpeta dist),"
    Write-Host "pega las novedades (ya están copiadas) y pulsa 'Publish release'."
}
