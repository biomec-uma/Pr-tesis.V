# BIOMEC Control

Centro de control de la mano protésica de BIOMEC UMA.

```
 PC (app Python)  ──USB──  ESP32-C6 PUENTE  ──ESP-NOW──  ESP32-WROOM MANO
```

> **En este repositorio (Pr-tesis.V):** la app está en `firmware/centro de control/Phyton/codigos phyton/`
> y el firmware en `firmware/centro de control/maestro/`: `c6/` = puente ESP32-C6 (`puente_pc.ino`)
> y `mano/` = mano ESP32-WROOM (`mano.ino`). Donde este README dice `firmware/puente_pc` o
> `firmware/mano`, se refiere a esas carpetas.

## Normas del equipo

- El responsable de esta parte (software de control y firmware) es **Hugo Moreno**.
- **No subáis cambios directamente a `main`.** Para proponer algo: cread una rama,
  haced vuestros cambios y abrid un *pull request*; se revisa y se acepta o no.
- Ideas, dudas o fallos: comentadlos antes con Hugo o abrid un *issue* en GitHub.
- Estado: **todavía no probado con el hardware real** (C6 puente + mano). Mientras
  tanto se puede usar el **simulador** (ver abajo).

## Primeros pasos (instalar en tu ordenador)

```powershell
git clone https://github.com/biomec-uma/Pr-tesis.V.git
cd Pr-tesis.V
git switch pruebasHugo   # mientras no esté unido a main
cd "firmware/centro de control/Phyton/codigos phyton"
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Ejecutar

```powershell
.\.venv\Scripts\python.exe main.py
```

### Sin hardware: simulador

En el selector de puerto aparece siempre **SIMULADOR · Mano simulada (sin hardware)**.
Al conectarte, la app habla con una mano virtual que reproduce la lógica de
`firmware/mano/mano.ino` (gestos, rampas, AUTO/MANUAL, telemetría) y responde
con los mismos mensajes. Sirve para desarrollar y enseñar la app sin placas.
Está en `biomec/core/simulator.py`: **si cambias el firmware de la mano,
actualiza también el simulador.**

Para instalarla como app de Windows (menú Inicio):

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Desktop
```

## Estructura

```
main.py                  Arranque: crea conexión, catálogo, contexto y ventana
config/commands.json     CATÁLOGO DE COMANDOS (editar aquí, no en el código)
config/mano3d.json       Modelo 3D: piezas, pasadores, flexión máxima, tiempos
assets/                  Logos e icono
biomec/
  core/                  Lógica sin interfaz
    protocol.py            Formato de las líneas (DATA, ACK, ERR, BRIDGE…)
    serial_link.py         Conexión USB en un hilo aparte
    commands.py            Carga y valida comandos del JSON
    simulator.py           Mano + puente simulados (opción SIMULADOR)
    hand_model.py          Carga los STL y resuelve el mecanismo de los dedos
  ui/                    Ventana, tema, barra de conexión, contexto compartido
  pages/                 UNA PESTAÑA POR ARCHIVO
    __init__.py            Lista PAGES: añadir/quitar pestañas aquí
    console.py             Consola de comandos y monitor
    commands.py            Catálogo consultable + historial de envíos
    telemetry.py           Gráficas en tiempo real
    hand3d.py              Mano 3D (modelo de SolidWorks animado)
firmware/
  puente_pc/             C6 conectada al PC (USB <-> ESP-NOW)
  mano/                  ESP32-WROOM de la mano (gestos, comandos y telemetría)
```

## Modelo 3D

La pestaña **Mano 3D** muestra el ensamblaje de SolidWorks (`assets/modelo3d/*.STL`)
moviéndose como la mano. Cada dedo es un mecanismo de barras que se resuelve en
`biomec/core/hand_model.py`; los pasadores están en `config/mano3d.json`.
La posición se estima integrando el PWM de la telemetría (`STREAM 1`), porque la
mano no tiene sensores de posición. Ajustar en `mano3d.json`:
`flexion_max_grados` (cuánto cierra un dedo) y `tiempo_cierre_s` (lo que tarda).

Si cambia el diseño: en SolidWorks, *Guardar como → STL*, Opciones: binario, mm,
✅ "No trasladar al espacio positivo", ❌ "Guardar todos los componentes en un único
archivo"; copiar los STL a `assets/modelo3d` y revisar los pasadores.

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
