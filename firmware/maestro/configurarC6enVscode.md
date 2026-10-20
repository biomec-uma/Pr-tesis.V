# EMG con Waveshare ESP32-C6-Zero

Proyecto PlatformIO para la placa **Waveshare ESP32-C6-Zero**, usando
**Arduino** como framework y la librería local `BIOMEC_ADS119X`.

## Requisitos

- Visual Studio Code.
- Extensión **PlatformIO IDE**.
- Cable USB-C de datos.
- Waveshare ESP32-C6-Zero.
- ADS1198 conectado según la tabla de pines de este documento.

La placa se configura mediante la definición compatible
`esp32-c6-devkitm-1`. El proyecto adapta esa definición a la Waveshare:

- Flash: 8 MB.
- Particiones: `default_8MB.csv`.
- USB CDC activado al arrancar.
- Velocidad de carga: 460800.
- Monitor serie: 115200 baudios.

## Instalación en otro ordenador

1. Instala VS Code.
2. Instala la extensión **PlatformIO IDE**.
3. Clona o copia este repositorio.
4. Abre en VS Code la carpeta raíz del proyecto.
5. Espera a que PlatformIO descargue automáticamente la plataforma,
   framework y herramientas.
6. Selecciona el entorno `esp32-c6-zero` en la barra inferior de PlatformIO.

### Rutas largas de Windows

En el ordenador original se usa una carpeta corta para los paquetes de
PlatformIO:

```text
C:\pio
```

Esto evita el límite histórico de longitud de rutas de Windows. Para usar la
misma configuración en otro ordenador, abre PowerShell y ejecuta:

```powershell
[Environment]::SetEnvironmentVariable(
  'PLATFORMIO_CORE_DIR',
  'C:\pio',
  'User'
)
```

Cierra y vuelve a abrir VS Code después de ejecutar el comando. PlatformIO
creará o reutilizará sus paquetes dentro de `C:\pio`.

Como alternativa, puedes habilitar **Win32 Long Paths** en Windows desde una
consola de administrador:

```powershell
New-ItemProperty `
  -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
  -Name 'LongPathsEnabled' `
  -Value 1 `
  -PropertyType DWORD `
  -Force
```

Después es necesario reiniciar Windows.

## Compilar y cargar

Desde la paleta de comandos de VS Code (`Ctrl+Shift+P`):

1. Ejecuta `PlatformIO: Clean`.
2. Ejecuta `PlatformIO: Build`.
3. Conecta la placa por USB-C.
4. Ejecuta `PlatformIO: Upload`.
5. Ejecuta `PlatformIO: Serial Monitor`.

También puedes usar la terminal de PlatformIO:

```powershell
pio run -e esp32-c6-zero
pio run -e esp32-c6-zero -t upload
pio device monitor -b 115200
```

Si la placa no entra automáticamente en modo de carga:

1. Mantén pulsado **BOOT**.
2. Pulsa y suelta **RESET**.
3. Suelta **BOOT**.
4. Repite `PlatformIO: Upload`.

El programa comienza mostrando información de inicialización en el monitor
serie. La velocidad debe ser **115200**.

## Conexión del ADS1198

Los pines utilizados por `src/main.cpp` son:

| ADS1198 | ESP32-C6-Zero |
| --- | ---: |
| DRDY | GPIO 1 |
| RESET | GPIO 0 |
| CS | GPIO 10 |
| SCLK | GPIO 6 |
| MISO | GPIO 2 |
| MOSI | GPIO 7 |
| START | GPIO 3 |

Además, conecta correctamente la alimentación y las masas comunes entre el
ADS1198 y la placa. El firmware espera detectar el ADS1198 durante el arranque
y reintenta la conexión varias veces si no responde.

## Archivos específicos del ordenador

`platformio.ini` contiene la configuración del proyecto y debe conservarse.
Los paquetes descargados por PlatformIO no forman parte del repositorio.

Los archivos `.vscode/c_cpp_properties.json` y `.vscode/launch.json` pueden
contener rutas absolutas del ordenador donde se generaron. Si esas rutas no
existen en otro equipo:

1. Configura primero `PLATFORMIO_CORE_DIR`.
2. Ejecuta `PlatformIO: Rebuild C/C++ Project Index`.
3. Si es necesario, ejecuta `PlatformIO: Re-Init` o vuelve a abrir el proyecto.

La compilación y la carga dependen principalmente de `platformio.ini`; la
configuración de `.vscode` solo afecta al autocompletado y la depuración.

## ESP Crash Decoder

La extensión **ESP Crash Decoder** es opcional. No es necesaria para compilar,
cargar o ejecutar el firmware. Solo sirve para traducir direcciones de memoria
de un reinicio o fallo a funciones y líneas de código legibles.
