@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Crear Visor EMG.exe

echo ============================================
echo   Creando "Visor EMG.exe"
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encuentra Python. Instalalo desde python.org
    echo         y marca "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

if not exist "visor_emg.py" (
    echo [ERROR] No esta visor_emg.py en esta carpeta.
    pause
    exit /b 1
)

echo Instalando / actualizando librerias...
python -m pip install --upgrade pyinstaller pyserial numpy
if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las librerias.
    pause
    exit /b 1
)

set EXTRAS=
if exist "logo.png" (
    set EXTRAS=%EXTRAS% --add-data "logo.png;."
) else (
    echo [AVISO] No hay logo.png: el programa saldra sin logo.
)
if exist "icono.ico" (
    set EXTRAS=%EXTRAS% --add-data "icono.ico;." --icon "icono.ico"
) else (
    echo [AVISO] No hay icono.ico: el .exe tendra el icono por defecto.
)

echo.
echo Compilando (tarda un minuto)...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "Visor EMG" %EXTRAS% visor_emg.py
if errorlevel 1 (
    echo [ERROR] Fallo al crear el ejecutable.
    pause
    exit /b 1
)

rem Limpieza de archivos temporales
rmdir /s /q build 2>nul
del /q "Visor EMG.spec" 2>nul

echo.
echo ============================================
echo   Listo:  dist\Visor EMG.exe
echo ============================================
explorer dist
pause
