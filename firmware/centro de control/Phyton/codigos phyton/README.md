# BIOMEC Control

Centro de control de la mano protésica de BIOMEC UMA.

```
 PC (app Python)  ──USB──  ESP32-C6 PUENTE  ──ESP-NOW──  ESP32-WROOM MANO
                                  ▲
                                  └──ESP-NOW──  placa EMG (ESP32-C3 + ADS1198)
```

## Normas del equipo

- El responsable de esta parte (software de control y firmware) es **Hugo Moreno**.
- **No subáis cambios directamente a `main`.** Para proponer algo: cread una rama,
  haced vuestros cambios y abrid un *pull request*; se revisa y se acepta o no.
- Ideas, dudas o fallos: comentadlos antes con Hugo o abrid un *issue* en GitHub.
- Estado: **todavía no probado con el hardware real** (C6 puente + mano). Mientras
  tanto se puede usar el **simulador** (ver abajo).

## Tareas pendientes

A consultar con el equipo antes de hacerlas:

- [ ] **Recalibrar sin reprogramar**: que la app envíe por radio el modelo recién
  entrenado a la placa y esta lo guarde en su memoria, para recalibrar con un botón
  (como Coapt o Myo Plus) en vez de recompilar y volver a subir el firmware.
- [ ] **Dónde decide el clasificador**: en la ESP32 de la placa EMG (propuesta: decide
  junto al ADS y solo envía la orden a la mano) o en la WROOM de la mano.
- [ ] **Conectar la placa EMG al puente**: en `firmware/EMG/src/main.cpp`, `rxMac` = MAC
  del puente (`AC:EB:E6:00:55:B4`) y `N_CHNLS` igual a `EMG_CANALES` del puente (2).
- [ ] **Gestos de fábrica**: ¿cambiar «Medio extendido» por Puño o Pinza en el firmware,
  o crearlas como posturas desde la app (Mis posturas)?

Cuando haya hardware:

- [ ] Subir el firmware nuevo al puente y a la mano, y probar `@PING`, `@INFO`,
  `ESTADO`, un gesto y una `POSTURA`.

## Primeros pasos (instalar en tu ordenador)

En el repositorio del equipo ([biomec-uma/Pr-tesis.V](https://github.com/biomec-uma/Pr-tesis.V),
rama `pruebasHugo`) la app está en `firmware/centro de control/Phyton/codigos phyton`.

```powershell
git clone <url-del-repositorio>
cd <carpeta>
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Para instalarla como app de Windows (menú Inicio; al terminar comprueba que el
`.exe` lleva todo lo necesario):

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Desktop
```

### Sin hardware: simulador

En el panel **Dispositivo** (abajo a la izquierda) se elige **Real / Simulación**:

- **Real**: eliges el puerto COM de la ESP32-C6 y los comandos van por USB al
  puente y de ahí, por ESP-NOW, a la mano.
- **Simulación**: los comandos los contesta una mano virtual dentro de la app que
  reproduce `firmware/mano/mano.ino` (gestos, rampas, AUTO/MANUAL, telemetría) con
  los mismos mensajes, y un **paciente virtual** genera señales EMG. Mientras está
  activa se ve una franja ámbar en todas las pestañas.

Está en `biomec/core/simulator.py` y `biomec/core/emg_sim.py`. **Si cambias el
firmware de la mano, actualiza también el simulador** (las pruebas automáticas
avisan si no coinciden los comandos o los gestos).

## Cómo se usa la app

- **Gemelo digital** — el modelo de SolidWorks moviéndose como la mano.
  - *Control*: seguir a la mano y % de cierre de cada dedo (o moverlos a mano).
  - *Postura*: galería de gestos, **Mis posturas** (ver abajo), dedos sueltos,
    pulgar y modo Manual/Demo. Los dedos con el motor en marcha se ven en azul.
- **Gráficas** — motores (PWM) y pulgar/gesto, con una marca por cada comando enviado.
- **Entrenamiento** — control mioeléctrico con reconocimiento de patrones (ver abajo).
- **Herramientas** (en todas las pestañas): **Consola** (Ctrl+J), **Comandos**
  (catálogo + historial, Ctrl+Shift+K) y **Asistente IA** (Ctrl+I).
- **Grabar** (Ctrl+R) / **Reproducir** (Ctrl+O) sesiones y **control por voz** (Ctrl+M) — arriba a la derecha.
- **Parar** (botón rojo o **Esc**): envía PARAR. Es una parada por software:
  **no sustituye a una parada de emergencia física**. También desactiva el control
  por EMG y corta las secuencias del asistente.
- **Paleta de comandos** (**Ctrl+K**): buscar y ejecutar cualquier acción.
- **Barra de estado**: estado de la mano y **latencia** de los comandos: verde
  < 100 ms, ámbar ≤ 125 ms. Farrell y Weir (2007) sitúan el retardo óptimo del
  control completo de una prótesis mioeléctrica en 100-125 ms.
- **Gestos con el teclado**: Alt+1 … Alt+8. **F1**: todos los atajos.

### Mis posturas (posturas personalizadas)

En *Gemelo digital → Postura → Mis posturas → + Nueva* se diseña una postura
(cada dedo abierto, cerrado o «no mover», y el ángulo del pulgar) con vista previa;
**Probar en la mano** la envía sin guardarla. Clic derecho sobre una tarjeta:
editar, duplicar, ordenar o eliminar. Se envían con el comando
`POSTURA <índice> <medio> <anular> <pulgar>` (p. ej. `POSTURA C A A 90`), que mueve
los tres dedos a la vez, así que **no hace falta tocar el firmware** para añadir
posturas. Se guardan en `%APPDATA%\BIOMEC Control\posturas.json`.

### Sesiones grabadas

**Grabar** guarda todo lo que pasa por la app (comandos, respuestas, telemetría,
EMG) con su instante en `Documentos\BIOMEC Control\Sesiones\*.jsonl`.
**Reproducir** la vuelve a pasar por la app: el gemelo, las gráficas y la consola
se mueven como durante la prueba, con barra de tiempo (marcas azules = comandos,
rojas = errores), pausa (Espacio), saltos (clic, ← →) y velocidad 0,5×-4×.
Mientras se reproduce no se pueden enviar comandos. El formato es JSON Lines, legible
desde Python o MATLAB (`jsondecode` línea a línea).

## Entrenamiento: control con los músculos (EMG)

Es la «estación de calibración» de las prótesis con reconocimiento de patrones
(Coapt Gen2, Ottobock Myo Plus), en tres pasos:

1. **Grabar**: eliges los movimientos (incluye siempre *Reposo*) y la app te guía:
   «relaja… ¡ahora! abre la mano…», con varias repeticiones.
2. **Entrenar**: características de Hudgins (MAV, WL, ZC, SSC) en ventanas de
   150 ms cada 50 ms + clasificador **LDA**. La precisión se estima con
   repeticiones que el modelo no ha visto; la matriz de confusión dice qué
   movimientos se confunden y el panel da consejos.
3. **Probar y controlar**: movimiento detectado en tiempo real con su probabilidad
   e intensidad. Con **Mover la mano con el EMG**, cada movimiento envía el comando
   que elijas (gesto, postura o PARAR), con confianza mínima y estabilidad
   configurables.

Los datos se guardan en CSV (`movimiento, repeticion, muestra, canal1…`) y el modelo
en JSON. **Exportar a ESP32** genera `biomec_emg_modelo.h`: el mismo clasificador en
C para que la placa decida sin PC (comprobado: compila para ESP32 y ESP32-C6 y da
las mismas decisiones que la app).

**Sin electrodos**: en Simulación aparece el **paciente virtual** (8 electrodos
simulados alrededor del antebrazo). Con 2 canales se distinguen bien 3-4
movimientos; con 4 u 8, más. Es lo que pasará con el ADS1198: ahora usamos 2 de sus
8 canales.

**Con el hardware real**:

1. En `firmware/EMG/src/main.cpp` (placa EMG), poner en `rxMac` la MAC del
   **puente** (la muestra `@INFO`).
2. En `firmware/puente_pc/puente_pc.ino`, `EMG_CANALES` = `N_CHNLS` de la placa EMG.
3. En la app, **Recibir EMG** (envía `@EMG 1`). El puente reenvía cada paquete como
   `EMG <seq> <canales> s1c1 s1c2 …` y cuenta los paquetes perdidos (`@INFO`).

El cálculo está en `biomec/core/emg.py` (solo numpy, todo causal).

## Control por voz

Botón del **micrófono** en la cabecera (o **Ctrl+M**): la mano obedece órdenes habladas.
Funciona **sin internet y gratis**: el reconocimiento ([Vosk](https://alphacephei.com/vosk/))
se hace en el propio ordenador. La primera vez la app descarga el modelo en español
(40 MB) a `%APPDATA%\BIOMEC Control\voz`.

| Para… | Di… |
|---|---|
| Parar | «para», «¡para, para!», «alto», «quieto» |
| Abrir / cerrar | «abre la mano», «cierra la mano», «puño» |
| Gestos | su nombre («señala», «mano plana», «gancho»…) o «gesto uno» … «gesto ocho» |
| Posturas | «pinza» o el nombre de una de *Mis posturas* |
| Dedos | «abre / cierra el índice / el medio / el anular», «abre / cierra el pulgar» |
| Modo y app | «modo manual», «modo demostración», «gráficas», «entrenamiento», «graba», «deja de grabar» |

Clic derecho en el micrófono: la lista completa. Seguridad: solo se ejecuta una orden si
**la frase entera** es una orden (lo que se dice en una conversación no mueve la mano) y con
confianza alta; «para» se acepta siempre. Con la mano real pide confirmación al activarlo, y
Parar/Esc siguen funcionando. Está en `biomec/core/voice.py` y `biomec/ui/voice.py`.

## Asistente IA (Claude)

Panel **Asistente IA** (Ctrl+I): preguntas sobre la mano, la app o un error («¿por
qué no responde la mano?») y órdenes en lenguaje natural («haz una pinza y luego
abre la mano»).

- **Nunca mueve la mano solo**: propone los comandos en una tarjeta y solo se
  envían si pulsas **Ejecutar** (Parar/Esc interrumpe la secuencia).
- Puede leer el estado de la app (conexión, telemetría, latencia, últimas líneas de
  la consola) para diagnosticar.
- Usa **Claude Opus 5.5** con streaming, caché del prompt y reintento automático
  en el servidor si un filtro de seguridad rechaza la petición (`fallbacks: "default"`).
- Necesita una **clave de API** de [console.anthropic.com](https://console.anthropic.com/settings/keys):
  se pone en el icono de la llave del panel (se guarda cifrada con DPAPI, solo para
  tu usuario de Windows) o en la variable de entorno `ANTHROPIC_API_KEY`.
- **Privacidad y coste**: se envían a Anthropic tus mensajes y una foto del estado
  de la app; cada pregunta consume tokens que se facturan a la cuenta de la clave.

## Estructura

```
main.py                  Arranque (y --selftest para comprobar el .exe)
config/commands.json     CATÁLOGO DE COMANDOS (editar aquí, no en el código)
config/mano3d.json       Modelo 3D: piezas, pasadores, flexión máxima, tiempos
assets/                  Logos, icono y STL del modelo 3D
biomec/
  core/                  Lógica sin interfaz (se puede probar sin ventana)
    protocol.py            Formato de las líneas (DATA, ACK, ERR, BRIDGE, EMG…)
    serial_link.py         Conexión USB en un hilo aparte
    commands.py            Carga y valida comandos del JSON
    simulator.py           Mano + puente simulados (opción Simulación)
    emg_sim.py             Paciente virtual: señales EMG simuladas
    emg.py                 IA: filtros, características de Hudgins, LDA, tiempo real
    emg_export.py          Exporta el modelo a C para la ESP32
    gestures.py            Tabla de gestos (la misma que GESTOS[] en mano.ino)
    postures.py            Posturas personalizadas
    session.py             Grabar y leer sesiones (.jsonl)
    assistant.py           Asistente con Claude (herramientas, streaming)
    voice.py               Control por voz: órdenes, reconocimiento (Vosk) y modelo
    secrets.py             Guardar la clave de API cifrada (DPAPI)
    hand_model.py          Carga los STL y resuelve el mecanismo de los dedos
  ui/                    Ventana, tema, iconos, paleta, diálogos, reproductor, contexto compartido
  pages/                 UNA PESTAÑA O PANEL POR ARCHIVO
    __init__.py            PAGES (pestañas) y paneles: añadir/quitar aquí
    hand3d.py              Gemelo digital
    telemetry.py           Gráficas
    emg.py                 Entrenamiento (EMG)
    console.py             Panel Consola (abajo)
    commands.py            Panel Comandos (derecha)
    assistant.py           Panel Asistente IA (derecha)
firmware/
  puente_pc/             C6 conectada al PC (USB <-> ESP-NOW, y reenvío de EMG)
  mano/                  ESP32-WROOM de la mano (gestos, posturas, comandos y telemetría)
tests/                   Pruebas automáticas
```

## Pruebas automáticas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Comprueban el protocolo, el catálogo, el simulador, las posturas, las sesiones, la
IA (filtros, LDA, entrenamiento, tiempo real, exportación a C), el asistente (con
un cliente falso, sin red) y el control por voz (qué frases son órdenes y cuáles no). También verifican que **firmware, simulador y
`commands.json` tienen los mismos comandos y gestos**: si alguien añade uno en un
sitio y se olvida de otro, fallan y dicen qué falta.

## Modelo 3D (Gemelo digital)

La pestaña **Gemelo digital** muestra el ensamblaje de SolidWorks (`assets/modelo3d/*.STL`)
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
| Un comando nuevo para la mano   | Bloque en `config/commands.json` + función y línea en `COMMANDS[]` de `mano.ino` + el mismo comando en `simulator.py` |
| Un comando del puente           | Igual, con `"target": "puente"`, y línea en `BRIDGE_COMMANDS[]`       |
| Una postura nueva               | Desde la app (Mis posturas): no hace falta tocar código               |
| Una señal nueva en las gráficas | Función `leerX()` y línea en `TELEMETRY[]` de `mano.ino`. La app la dibuja sola |
| Una pestaña nueva               | `biomec/pages/mi_pagina.py` (hereda de `BasePage`) + añadirla a `PAGES` |
| Quitar una pestaña              | Borrar su línea en `PAGES`                                            |

Una página nueva solo necesita sobrescribir los ganchos que use:

```python
from .base import BasePage

class MiPagina(BasePage):
    title = "Mi página"
    icon = "activity"          # nombre de un icono de ui/icons.py

    def __init__(self, ctx):
        super().__init__(ctx)
        # construir widgets…

    def on_message(self, msg):          # cada línea recibida/enviada
        if msg.kind.value == "DATA":
            print(msg.values)           # {'indice': -128.0, ...}
```

Para enviar desde cualquier página: `self.ctx.send_command("GESTO 3")`.

## Protocolo

Todo son líneas de texto acabadas en `\n` (ver `biomec/core/protocol.py` y `firmware/*/biomec_protocol.h`).

| Dirección      | Formato                          | Uso                                         |
|----------------|----------------------------------|---------------------------------------------|
| PC → mano      | `COMANDO args`                   | El puente lo reenvía por ESP-NOW            |
| PC → puente    | `@COMANDO args`                  | Lo ejecuta el puente (`@PING`, `@INFO`, `@EMG 1`) |
| → PC           | `DATA clave=valor …`             | Telemetría → gráficas y gemelo              |
| → PC           | `ACK COMANDO …` / `ERR texto`    | Respuesta a un comando                      |
| → PC           | `BRIDGE texto`                   | Mensajes del puente                         |
| → PC           | `EMG seq canales v1 v2 …`        | Muestras EMG (si se activó con `@EMG 1`)    |

## Firmware (Arduino IDE)

- Dónde está: `firmware/puente_pc` y `firmware/mano` junto a la app o, en el repositorio del
  equipo, `firmware/centro de control/maestro/c6` (puente) y `firmware/centro de control/maestro/mano`.
- `puente_pc` → placa **ESP32C6 Dev Module**, con **Herramientas → USB CDC On Boot: Enabled**.
  (También se compila desde el proyecto de PlatformIO «centro de control».)
- `mano` → placa **ESP32 Dev Module** (ESP32-WROOM). Necesita la librería **ESP32Servo ≥ 3.0**.
  **Hay que volver a subirlo** para tener `POSTURA` y el `ESTADO` nuevo.
- Ambos con el core esp32 ≥ 3.0 (la API de LEDC/timers del core 2.x ya no existe).
- `biomec_protocol.h` está duplicado en las dos carpetas: si lo cambias, cópialo en ambas.
- Por defecto las placas usan broadcast. Cuando sepas las MAC (las imprimen al arrancar, o con `@INFO`),
  ponlas en `HAND_MAC` y `BRIDGE_MAC` para que solo se hablen entre ellas.
