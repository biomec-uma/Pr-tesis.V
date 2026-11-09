@echo off
REM Genera SerialLogger.exe a partir de serial_logger_gui.py
REM Uso: pon este archivo en la misma carpeta que serial_logger_gui.py y haz doble clic.
REM Si en esa carpeta hay un logo.png y/o un icono.ico, se meten dentro del .exe.

cd /d "%~dp0"
echo Instalando lo necesario (solo tarda la primera vez)...
python -m pip install --upgrade pyinstaller pyserial
if errorlevel 1 (
    echo.
    echo ERROR: no se encontro Python. Instala Python desde python.org marcando "Add Python to PATH".
    pause
    exit /b 1
)

REM --add-data "origen;destino" mete un archivo dentro del .exe (en Windows se separa con ;)
REM --icon es el icono que se ve en el Explorador de archivos
set EXTRA=
if exist logo.png (
    echo Incluyendo logo.png
    set EXTRA=%EXTRA% --add-data "logo.png;."
)
if exist icono.ico (
    echo Incluyendo icono.ico
    set EXTRA=%EXTRA% --add-data "icono.ico;." --icon "icono.ico"
)

echo.
echo Creando el ejecutable...
python -m PyInstaller --onefile --windowed --clean --noconfirm --name SerialLogger %EXTRA% serial_logger_gui.py
if errorlevel 1 (
    echo.
    echo ERROR al crear el ejecutable. Revisa los mensajes de arriba.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Listo: el ejecutable esta en  dist\SerialLogger.exe
echo  Ese es el unico archivo que tienes que pasar a tus companeros.
echo ============================================================
explorer dist
pause
