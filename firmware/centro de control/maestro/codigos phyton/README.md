# BIOMEC Control

Centro de control de la mano protésica de BIOMEC UMA.

```
 PC (app Python)  ──USB──  ESP32-C6 PUENTE  ──ESP-NOW──  ESP32-WROOM MANO
```

## Ejecutar

```powershell
.\.venv\Scripts\python.exe main.py
```

Para instalarla como app de Windows (menú Inicio):

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Desktop
```

## Estructura

```
main.py                  Arranque: crea conexión, catálogo, contexto y ventana
config/commands.json     CATÁLOGO DE COMANDOS (editar aquí, no en el código)
assets/                  Logos e icono
biomec/
  core/                  Lógica sin interfaz
    protocol.py            Formato de las líneas (DATA, ACK, ERR, BRIDGE…)
    serial_link.py         Conexión USB en un hilo aparte
    commands.py            Carga y valida comandos del JSON
  ui/                    Ventana, tema, barra de conexión, contexto compartido
  pages/                 UNA PESTAÑA POR ARCHIVO
    __init__.py            Lista PAGES: añadir/quitar pestañas aquí
    console.py             Consola de comandos y monitor
    commands.py            Catálogo consultable + historial de envíos
    telemetry.py           Gráficas en tiempo real
firmware/
  puente_pc/             C6 conectada al PC (USB <-> ESP-NOW)
  mano/                  ESP32-WROOM de la mano (gestos, comandos y telemetría)
```

## Cómo ampliar

| Quiero…                         | Hago…                                                                 |
|---------------------------------|-----------------------------------------------------------------------|
| Un comando nuevo para la mano   | Bloque en `config/commands.json` + función y línea en `COMMANDS[]` de `mano.ino` |
| Un comando del puente           | Igual, con `"target": "puente"`, y línea en `BRIDGE_COMMANDS[]`       |
| Una señal nueva en las gráficas | Función `leerX()` y línea en `TELEMETRY[]` de `mano.ino`. La app la dibuja sola |
| Una pestaña nueva               | `biomec/pages/mi_pagina.py` (hereda de `BasePage`) + añadirla a `PAGES` |
| Quitar una pestaña              | Borrar su línea en `PAGES`                                            |

Una página nueva solo necesita sobrescribir los ganchos que use:

```python
from .base import BasePage

class MiPagina(BasePage):
    title = "Mi página"
    icon = "★"

    def __init__(self, ctx):
        super().__init__(ctx)
        # construir widgets…

    def on_message(self, msg):          # cada línea recibida/enviada
        if msg.kind.value == "DATA":
            print(msg.values)           # {'pot': 512.0, ...}
```

Para enviar desde cualquier página: `self.ctx.send_command("DEDO 2 50")`.

## Protocolo

Todo son líneas de texto acabadas en `\n` (ver `biomec/core/protocol.py` y `firmware/*/biomec_protocol.h`).

| Dirección      | Formato                        | Uso                                 |
|----------------|--------------------------------|-------------------------------------|
| PC → mano      | `COMANDO args`                 | El puente lo reenvía por ESP-NOW    |
| PC → puente    | `@COMANDO args`                | Lo ejecuta el puente                |
| → PC           | `DATA clave=valor …`           | Telemetría → gráficas               |
| → PC           | `ACK COMANDO …` / `ERR texto`  | Respuesta a un comando              |
| → PC           | `BRIDGE texto`                 | Mensajes del puente                 |

## Firmware (Arduino IDE)

- `puente_pc` → placa **ESP32C6 Dev Module**, con **Herramientas → USB CDC On Boot: Enabled**.
- `mano` → placa **ESP32 Dev Module** (ESP32-WROOM). Necesita la librería **ESP32Servo ≥ 3.0**.
- Ambos con el core esp32 ≥ 3.0 (la API de LEDC/timers del core 2.x ya no existe).
- `biomec_protocol.h` está duplicado en las dos carpetas: si lo cambias, cópialo en ambas.
- Por defecto las placas usan broadcast. Cuando sepas las MAC (las imprimen al arrancar, o con el comando `INFO`), ponlas en `HAND_MAC` y `BRIDGE_MAC` para que solo se hablen entre ellas.
