@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Creando Serial Logger.exe ===

python --version >nul 2>&1
if errorlevel 1 (
    echo No se encuentra Python. Instalalo desde python.org marcando "Add Python to PATH".
    pause
    exit /b 1
)

echo Instalando dependencias...
python -m pip install --upgrade pyserial pyinstaller
if errorlevel 1 goto error

set EXTRA=
if exist icono.ico set EXTRA=%EXTRA% --icon icono.ico --add-data "icono.ico;."
if exist logo.png  set EXTRA=%EXTRA% --add-data "logo.png;."
if not exist logo.png echo Aviso: no hay logo.png, el .exe saldra sin logo en la cabecera.

python -m PyInstaller --noconfirm --clean --onefile --windowed --name "Serial Logger" %EXTRA% serial_logger_gui.py
if errorlevel 1 goto error

echo.
echo Listo: dist\Serial Logger.exe
explorer dist
pause
exit /b 0

:error
echo.
echo Algo ha fallado. Revisa los mensajes de arriba.
pause
exit /b 1
