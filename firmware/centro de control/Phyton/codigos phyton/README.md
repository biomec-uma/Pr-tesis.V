# BIOMEC Control

Centro de control de la mano protésica de BIOMEC UMA.

```
 PC (app Python)  ──USB──  ESP32-C6 PUENTE  ──ESP-NOW──  ESP32-WROOM MANO
        │                         ▲
        │                         └──ESP-NOW──  placa EMG (ESP32-C3 + ADS1198)   (formato antiguo)
        └───────USB──  ESP32-C6 RECEPTOR EMG del equipo  ◄──ESP-NOW──  placa EMG   (Visor EMG)
```

## Normas del equipo

- El responsable de esta parte (software de control y firmware) es **Hugo Moreno**.
- **No subáis cambios directamente a `main`.** Para proponer algo: cread una rama,
  haced vuestros cambios y abrid un *pull request*; se revisa y se acepta o no.
- Ideas, dudas o fallos: comentadlos antes con Hugo o abrid un *issue* en GitHub.
- Estado: **todavía no probado con el hardware real** (C6 puente + mano). Mientras
  tanto se puede usar el **simulador** (ver abajo).

## Instalar la app (para el equipo)

1. Descarga `BIOMEC-Control-Setup-X.Y.Z.exe` de la última versión en
   [GitHub → Releases](https://github.com/biomec-uma/Pr-tesis.V/releases).
2. Ábrelo. Windows avisará de que no reconoce la aplicación (no está firmada): pulsa
   **Más información → Ejecutar de todas formas**. No pide permisos de administrador.
3. Queda en el menú Inicio como **BIOMEC Control** (se desinstala desde Configuración → Aplicaciones).

**Actualizaciones**: al arrancar, la app mira en GitHub si hay una versión nueva y la anuncia en la
cabecera («Actualizar a X»). Con un clic se descarga, se comprueba su huella SHA-256 y se instala sola;
tus ajustes, posturas, sesiones y modelos se conservan. También en **Acerca de → Buscar ahora** o en la
paleta (Ctrl+K). Las novedades de cada versión están en [CHANGELOG.md](CHANGELOG.md).

## Tareas pendientes

A consultar con el equipo antes de hacerlas:

- [ ] **Recalibrar sin reprogramar**: que la app envíe por radio el modelo recién
  entrenado a la placa y esta lo guarde en su memoria, para recalibrar con un botón
  (como Coapt o Myo Plus) en vez de recompilar y volver a subir el firmware.
- [ ] **Dónde decide el clasificador**: en la ESP32 de la placa EMG (propuesta: decide
  junto al ADS y solo envía la orden a la mano) o en la WROOM de la mano.
- [ ] **Qué C6 recibe el EMG**: `puente_pc.cpp` ya hace de puente y de receptor a la vez (con y sin
  placa EMG). El sensor nuevo (rama `Imprimir-seq`) envía a `rxMac` = `AC:EB:E6:2C:D7:DC`, la C6-Zero
  del receptor del equipo. Dos opciones: subir `puente_pc` a esa C6-Zero (el sensor no se toca), o poner
  en `rxMac` la MAC de nuestra DevKitC (`AC:EB:E6:00:55:B4`). Las dos son placas o código de Dylan.
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

Para generar el `.exe` en `dist/` y probarlo como app (acceso «BIOMEC Control (desarrollo)» en el
menú Inicio; al terminar comprueba que el `.exe` lleva todo lo necesario):

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Desktop
```

### Sin hardware: simulador

En la ventana **Dispositivo** (Ctrl+5) se elige **Real / Simulación**:

- **Real**: eliges el puerto COM de la ESP32-C6 y los comandos van por USB al
  puente y de ahí, por ESP-NOW, a la mano.
- **Simulación**: los comandos los contesta una mano virtual dentro de la app que
  reproduce `firmware/mano/src/mano.cpp` (gestos, rampas, AUTO/MANUAL, telemetría) con
  los mismos mensajes, y un **paciente virtual** genera señales EMG. Mientras está
  activa se ve una franja ámbar bajo la cabecera.

Está en `biomec/core/simulator.py` y `biomec/core/emg_sim.py`. **Si cambias el
firmware de la mano, actualiza también el simulador** (las pruebas automáticas
avisan si no coinciden los comandos o los gestos).

## Cómo se usa la app

La app es un **espacio de trabajo por ventanas**: cada parte es una ventana que se muestra u oculta a
gusto, para montar solo lo que hace falta en cada prueba, ensayo o demostración.

| Ventana | Atajo | Qué tiene |
|---|---|---|
| **Gemelo digital** | Ctrl+1 | El modelo de SolidWorks moviéndose como la mano; «Seguir a la mano» y % de cierre estimado. Los dedos con el motor en marcha se ven en azul |
| **Posturas** | Ctrl+2 | Galería de gestos, **Mis posturas** (ver abajo), dedos sueltos, pulgar y modo Manual/Demo |
| **Gráficas** | Ctrl+3 | Señales en tiempo real con marcas de los comandos (ver «Gráficas y señales»). **Nueva gráfica** (Ctrl+Mayús+G) abre otra ventana con las señales que se elijan |
| **Entrenamiento** | Ctrl+4 | Control mioeléctrico con reconocimiento de patrones (ver abajo) |
| **Visor EMG** | Ctrl+6 | Señal de los electrodos en directo, diagnóstico del enlace y grabación en CSV (ver abajo) |
| **Analizador EMG** | Ctrl+7 | El analizador de MATLAB del equipo: red de 50 Hz, filtros, espectros, envolvente y umbral |
| **Dispositivo** | Ctrl+5 | Mano real o simulación, puerto y conexión |
| **Consola** | Ctrl+J | Registro de mensajes y línea para escribir comandos |
| **Comandos** | Ctrl+Mayús+K | Catálogo e historial de comandos |
| **Asistente IA** | Ctrl+I | Preguntas y órdenes en lenguaje natural (ver abajo) |

- **Mostrar u ocultar** una ventana: su botón en la barra lateral, el menú **Ventanas** de la cabecera,
  su atajo o la ✕ de su título.
- **Recolocar**: se arrastra por el título. Soltada sobre otra ventana, se agrupa con ella en
  pestañas; en un borde, se pone al lado. El botón ⧉ del título (o doble clic) la saca **flotante**,
  por ejemplo a otra pantalla, y vuelve a acoplarla.
- **Espacios de trabajo** (menú Ventanas o Ctrl+K): *Demostración* (gemelo grande y posturas),
  *Ensayo* (gráficas, gemelo, posturas y consola a la vez), *Entrenamiento* (Entrenamiento, Visor EMG
  y Analizador EMG en pestañas, gemelo y consola) y *Todo*. El reparto de ventanas se recuerda al cerrar la app.
- **Barra lateral**: el botón « la pliega a solo iconos y Ctrl+B la oculta. En ventanas estrechas
  se pliega sola.
- **Grabar** (Ctrl+R) / **Reproducir** (Ctrl+O) sesiones y **control por voz** (Ctrl+M): arriba a la derecha.
- **Parar** (botón rojo o **Esc**): envía PARAR. Es una parada por software:
  **no sustituye a una parada de emergencia física**. También desactiva el control
  por EMG y corta las secuencias del asistente.
- **Paleta de comandos** (**Ctrl+K**): buscar y ejecutar cualquier acción.
- **Barra de estado**: estado de la mano y **latencia** de los comandos: verde
  < 100 ms, ámbar ≤ 125 ms. Farrell y Weir (2007) sitúan el retardo óptimo del
  control completo de una prótesis mioeléctrica en 100-125 ms.
- **Gestos con el teclado**: Alt+1 … Alt+8. **F1**: todos los atajos.

### Mis posturas (posturas personalizadas)

En la ventana *Posturas → Mis posturas → + Nueva* se diseña una postura
(cada dedo abierto, cerrado o «no mover», y el ángulo del pulgar) con vista previa;
**Probar en la mano** la envía sin guardarla. Clic derecho sobre una tarjeta:
editar, duplicar, ordenar o eliminar. Se envían con el comando
`POSTURA <índice> <medio> <anular> <pulgar>` (p. ej. `POSTURA C A A 90`), que mueve
los tres dedos a la vez, así que **no hace falta tocar el firmware** para añadir
posturas. Se guardan en `%APPDATA%\BIOMEC Control\posturas.json`.

### Gráficas y señales

Las señales que se pueden dibujar están en el catálogo `config/signals.json`. Cada **grupo** es una
magnitud distinta (su unidad) y tiene su propia gráfica, con el eje de tiempo compartido en mm:ss.
En una ventana de Gráficas, **Señales…** elige qué se dibuja. Pueden abrirse tantas ventanas como se
quiera, con una señal cada una o varias juntas.

| Grupo (gráfica) | Unidad | Señales | Origen | Estado |
|---|---|---|---|---|
| Motores | PWM (−255…255; + abre, − cierra) | índice, medio, anular: salida del controlador | mano | disponible |
| Consignas | 1 = cerrar, 0 = abrir | objetivo de cada dedo según el último comando aceptado | app | disponible |
| Pulgar | ° | ángulo del servo y su consigna | mano / app | disponible |
| Posición estimada | % cerrado | integración del PWM en el tiempo (no hay sensor de posición) | app | disponible |
| Estado de la mano | — | gesto activo; fase (1 = moviendo) | mano | disponible; *fase*, con el firmware nuevo |
| Alarmas | 1 = activa | saturación: el motor lleva al máximo más de lo previsto (tiempo de fase + rampa) | app | disponible |
| EMG bruto | cuentas ADC | un canal por electrodo, 500 Hz | placa EMG | disponible (falta conectar la placa al puente) |
| EMG filtrado | cuentas ADC | paso alto 20 Hz + notch 50 Hz, los filtros del entrenamiento | app | disponible |
| Corriente | mA | un motor cada una | mano | **pendiente**: la placa aún no la mide |
| Posición de los motores | mm | un motor cada una | mano | **pendiente**: hace falta un sensor o final de carrera |

Son **siete magnitudes disponibles hoy** más dos previstas, así que como mucho hay nueve gráficas
distintas a la vez. Lo normal en un ensayo son tres: PWM, pulgar y estado. Las señales pendientes ya
salen en el selector, en gris, para que la interfaz no tenga que cambiar cuando la mano las envíe.

**Marcas de comandos.** Cada comando deja una línea discontinua en el instante en que se envía. Si
mueve los motores, la zona se sombrea hasta que terminan de moverse y ahí se dibuja una línea
punteada; la etiqueta dice cuánto tardó (p. ej. «GESTO 3 · 3.5 s»). Los movimientos que inicia la
propia mano en modo demo se marcan en gris. Las consultas (`ESTADO`, `STREAM`…) no se marcan.

**Fase entre la marca y las curvas.** La mano manda su estado cada 50 ms y las curvas se dibujan en
escalón: cada valor se mantiene hasta que llega el siguiente. Así el cambio aparece en la primera
muestra que llega después del comando, entre 10 y 50 ms tras la marca. Antes se unían las muestras con
líneas rectas, y el tramo desde la última muestra anterior al comando hacía parecer que la curva
empezaba a cambiar antes de la marca.

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

El puente funciona **con y sin la placa EMG**: sin ella solo mueve la mano; con ella encendida,
además manda su señal al PC por el mismo USB.

1. En `firmware/EMG/src/main.cpp` (placa EMG), `rxMac` debe ser la MAC de la C6 conectada al PC:
   la del puente (la muestra `@INFO`) o, si se sube `puente_pc` a la C6-Zero del receptor del equipo,
   la que ya trae (`AC:EB:E6:2C:D7:DC`).
2. Nada más: el puente arranca mandando el EMG (`@EMG 0` lo para, `@EMG 1` lo reactiva) y su LED se
   pone azul mientras llega. `@INFO` dice si llega (`sensor=si`), el formato y los paquetes perdidos.

Formatos del sensor que entiende el puente:

- **Nuevo** (rama `Imprimir-seq`): `version, nChnls, batch, seq (u32), sendFails, data`. Va al PC tal
  cual, en marcos binarios `AA 55 | tipo | longitud | contenido | XOR` entre las líneas de texto (los
  mismos que el receptor del equipo, así que también lo lee su `visor_emg.py`). Cada segundo, mientras
  llega EMG, un marco de estado con la MAC de la C6 y sus contadores.
- **Antiguo** (`main`): `seq (u16), data`. Va como línea `EMG <seq> <canales> s1c1 s1c2 …`
  (`EMG_CANALES` del puente = `N_CHNLS` de la placa).

La app separa los marcos del texto en la conexión principal, así que también se puede conectar ahí el
**receptor EMG del equipo** (solo trae EMG: si se le mandan comandos, la app avisa de que esa C6 no habla
con la mano). O conectar el receptor en un segundo USB desde el **Visor EMG**. En todos los casos la señal
llega igual a Entrenamiento, a las Gráficas y a las sesiones grabadas.

El cálculo está en `biomec/core/emg.py` (solo numpy, todo causal).

## Visor EMG y Analizador EMG

Son las dos herramientas EMG del equipo (`firmware/EMG/tools/` en `main`), metidas en la app como
ventanas.

**Visor EMG** (el `visor_emg.py` de Tkinter):

- **Fuente**: el **receptor EMG del equipo** (ESP32-C6 con `firmware/maestro` de la rama
  `Imprimir-seq`) por USB: elige su puerto y pulsa **Conectar** (el de la conexión de la app sale
  marcado «en uso»; la lista se vuelve a buscar al abrirla). Lee los marcos
  `AA 55 | tipo | longitud | contenido | XOR` y se reconecta solo si se desenchufa. También muestra lo
  que llegue por la conexión de la app (el puente con la placa EMG, el receptor conectado ahí o la
  simulación), con los contadores de esa C6.
- **Señal**: un carril por canal con el presente a la derecha, ventana de 1 a 30 s, **Bruta** (cuentas
  del ADC) o **Filtrada** (paso alto 20 Hz + notch 50 Hz, como Entrenamiento), escala automática que
  crece al instante y encoge despacio, y pausa (no detiene la grabación).
- **Diagnóstico**: paquetes/s, recibidos, perdidos (saltos de `seq`), envíos fallidos del sensor,
  reinicios, marcos corruptos y, del receptor, su MAC y sus contadores (inválidos, cola llena,
  descartados por USB) desde que se conecta.
- **Grabación en CSV** con las columnas que se elijan y su nombre en la cabecera: **Todas** (`t_s, seq,
  idx, ch1, ch2…`) o **Solo tiempo + canales** (`tiempo, data0, data1…`, el formato del Analizador). El
  tiempo sale de `seq` y de la frecuencia del ADC, no del reloj del PC: un paquete perdido deja su hueco.
  «Parar a los» corta sola la grabación. Al terminar, **Analizar** la abre en el Analizador.

**Analizador EMG** (la app de MATLAB `AnalizadorEMG.mlapp` v1.0 y `analizarEMG.m`):

- Mismos parámetros (Datos del ADC, Filtrado, Detección de contracción, con sus valores por defecto) y
  mismos avisos y errores (`validarParametros.m`).
- Pasos: cuentas → µV centrados, % de potencia en 50 ± 1 Hz, notch sin desfase (`filtfilt`), paso
  banda FIR sin desfase (como `bandpass(…, 'fir')`), envolvente RMS y umbral = media + k·std del reposo.
- Las 7 gráficas de la app de MATLAB (bruta, espectro, notch antes/después, paso banda antes/después,
  bruta vs filtrada, espectrograma y envolvente con el umbral), un gráfico por canal. Analiza los canales
  que se marquen del CSV (lee los del Visor y del logger serie).
- **Guardar** crea `<carpeta>/<muestra>/` con `figura_1…7.png`, `resultados.csv` (mismas columnas),
  `resumen_muestras.csv` (una fila más cada vez), `senales.csv` y `coeficientes_filtros.txt` (mismo
  formato). En vez de los `.mat` de MATLAB guarda `senales.csv` (t, señal filtrada y envolvente).
- **Da los mismos números que MATLAB**: con la muestra `27.10.2026.enReposoUsandoMotores.csv` del
  repositorio coinciden en 9 cifras o más el % de 50 Hz, el notch, los 595 coeficientes del paso banda,
  la señal filtrada, la envolvente, el RMS de reposo y el umbral (lo comprueban las pruebas).

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
build_exe.ps1            Genera el .exe en dist/ (versión de desarrollo)
release.ps1              Publica una versión: pruebas, .exe, instalador y GitHub Releases
installer/               Instalador de Windows (Inno Setup)
CHANGELOG.md             Novedades de cada versión (las ve el equipo al actualizar)
config/commands.json     CATÁLOGO DE COMANDOS (editar aquí, no en el código)
config/mano3d.json       Modelo 3D: piezas, pasadores, flexión máxima, tiempos
config/signals.json      Señales graficables: grupos (magnitudes) y señales
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
    gestures.py            Tabla de gestos (la misma que GESTOS[] en mano.cpp)
    postures.py            Posturas personalizadas
    session.py             Grabar y leer sesiones (.jsonl)
    assistant.py           Asistente con Claude (herramientas, streaming)
    voice.py               Control por voz: órdenes, reconocimiento (Vosk) y modelo
    updates.py             Actualizaciones: versiones en GitHub, descarga y huella SHA-256
    secrets.py             Guardar la clave de API cifrada (DPAPI)
    hand_model.py          Carga los STL, resuelve el mecanismo de los dedos y el encuadre de la vista 3D
    signals.py             Señales de las gráficas: catálogo, almacén, derivadas y marcas de comandos
    emg_receiver.py        Receptor EMG del equipo por USB (marcos AA 55), estadísticas y grabación en CSV
    emg_analysis.py        Analizador EMG: el analizador de MATLAB del equipo en numpy
  ui/                    Ventana principal, tema, iconos, paleta, diálogos, reproductor, contexto compartido
    main_window.py         Espacio de trabajo: cabecera, ventanas (WINDOWS) y espacios predefinidos
    docks.py               Ventana acoplable/flotante (Dock) y barra lateral plegable (Rail)
  pages/                 EL CONTENIDO DE CADA VENTANA
    hand3d.py              Gemelo digital (vista 3D) y Posturas
    telemetry.py           Gráficas (GraphPanel; una por ventana) y selector de señales
    emg.py                 Entrenamiento (EMG)
    emg_viewer.py          Visor EMG
    emg_analyzer.py        Analizador EMG
    console.py             Consola
    commands.py            Comandos
    assistant.py           Asistente IA
firmware/
  puente_pc/             C6 conectada al PC: puente de la mano y receptor EMG (con y sin placa EMG)
                         (cada firmware es un proyecto de PlatformIO: platformio.ini + src/*.cpp)
  mano/                  ESP32-WROOM de la mano (gestos, posturas, comandos y telemetría)
  bucle_exposiciones/    La mano sola, sin radio: recorre los gestos (exposiciones y prueba de hardware)
tests/                   Pruebas automáticas (tests/data: una muestra EMG del equipo con sus resultados de MATLAB)
```

## Pruebas automáticas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Comprueban el protocolo, el catálogo, el simulador, las posturas, las sesiones, la
IA (filtros, LDA, entrenamiento, tiempo real, exportación a C), el asistente (con
un cliente falso, sin red), el control por voz (qué frases son órdenes y cuáles no), las
actualizaciones, las señales de las gráficas (marcas de inicio y fin de cada comando, consignas,
% cerrado, saturación, EMG), el encuadre de la vista 3D, el receptor EMG (marcos partidos, corruptos, mezclados con el texto de la mano en la conexión principal,
paquetes perdidos, reinicios), la grabación en CSV y que **el Analizador EMG da los mismos números que
MATLAB** con una muestra del equipo. También verifican que **firmware,
simulador, `commands.json` y `signals.json` tienen los mismos comandos, gestos y señales**: si
alguien añade uno en un sitio y se olvida de otro, fallan y dicen qué falta.

## Publicar una versión nueva

1. Sube `APP_VERSION` en `biomec/__init__.py` (p. ej. 0.3.0 → 0.3.1) y escribe sus novedades en
   [CHANGELOG.md](CHANGELOG.md), en un apartado `## 0.3.1`: es lo que verá el equipo al actualizar.
2. Sube el código a GitHub (rama `pruebasHugo`).
3. Ejecuta `release.ps1`:

```powershell
powershell -ExecutionPolicy Bypass -File release.ps1
```

Pasa las pruebas, genera el `.exe` y el instalador con [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`) y lo publica en GitHub Releases con la etiqueta `control-v0.3.1`.
Con [GitHub CLI](https://cli.github.com/) (`gh auth login` una vez) lo publica él solo; sin él, abre la
página de GitHub con la etiqueta y el título puestos para arrastrar el instalador. Con `-SoloInstalador`
genera el instalador sin publicar nada. El instalador está en `installer/biomec_control.iss`: su `AppId`
no se debe cambiar nunca.

## Modelo 3D (Gemelo digital)

La ventana **Gemelo digital** muestra el ensamblaje de SolidWorks (`assets/modelo3d/*.STL`)
moviéndose como la mano. Cada dedo es un mecanismo de barras que se resuelve en
`biomec/core/hand_model.py`; los pasadores están en `config/mano3d.json`.
La posición se estima integrando el PWM de la telemetría (`STREAM 1`), porque la
mano no tiene sensores de posición. Ajustar en `mano3d.json`:
`flexion_max_grados` (cuánto cierra un dedo) y `tiempo_cierre_s` (lo que tarda).

El encuadre de la vista usa un campo de visión **vertical** fijo (`frustum()` en `hand_model.py`):
la escala de la mano depende solo del alto de la ventana. pyqtgraph lo fija en horizontal, y al
abrir o cerrar otras ventanas cambiaba el ancho y la mano se veía a otra escala.

Si cambia el diseño: en SolidWorks, *Guardar como → STL*, Opciones: binario, mm,
✅ "No trasladar al espacio positivo", ❌ "Guardar todos los componentes en un único
archivo"; copiar los STL a `assets/modelo3d` y revisar los pasadores.

## Cómo ampliar

| Quiero…                         | Hago…                                                                 |
|---------------------------------|-----------------------------------------------------------------------|
| Un comando nuevo para la mano   | Bloque en `config/commands.json` + función y línea en `COMMANDS[]` de `mano.cpp` + el mismo comando en `simulator.py` |
| Un comando del puente           | Igual, con `"target": "puente"`, y línea en `BRIDGE_COMMANDS[]`       |
| Una postura nueva               | Desde la app (Mis posturas): no hace falta tocar código               |
| Una señal nueva en las gráficas | Función `tX()` y línea en `TELEMETRY[]` de `mano.cpp` + la misma clave en `simulator.py` + su entrada en `config/signals.json` (nombre, grupo). Sin entrada se dibuja igual, en «Otras señales» |
| Una magnitud nueva (otra gráfica) | Un grupo en `config/signals.json` (título, unidad, rango, eje) |
| Una ventana nueva               | `biomec/pages/mi_ventana.py` (hereda de `BasePage`) + una línea en `WINDOWS` de `ui/main_window.py` |
| Quitar una ventana              | Borrar su línea en `WINDOWS`                                          |

El contenido de una ventana solo necesita sobrescribir los ganchos que use:

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

Líneas de texto acabadas en `\n` (ver `biomec/core/protocol.py` y `firmware/*/biomec_protocol.h`).
La única excepción es el EMG del sensor nuevo, que el puente manda en marcos binarios `AA 55` entre las
líneas (ver «Entrenamiento: control con los músculos»); sin placa EMG, todo es texto.

| Dirección      | Formato                          | Uso                                         |
|----------------|----------------------------------|---------------------------------------------|
| PC → mano      | `COMANDO args`                   | El puente lo reenvía por ESP-NOW            |
| PC → puente    | `@COMANDO args`                  | Lo ejecuta el puente (`@PING`, `@INFO`, `@EMG 1`) |
| → PC           | `DATA clave=valor …`             | Telemetría → gráficas y gemelo              |
| → PC           | `ACK COMANDO …` / `ERR texto`    | Respuesta a un comando                      |
| → PC           | `BRIDGE texto`                   | Mensajes del puente                         |
| → PC           | `EMG seq canales v1 v2 …`        | Muestras EMG del sensor antiguo             |
| → PC           | marco `AA 55 01 …` / `AA 55 02 …` | Paquete del sensor nuevo / estado de la C6 |

## Firmware (PlatformIO)

Cada firmware es un proyecto de PlatformIO (`platformio.ini` + `src/<nombre>.cpp`, y `include/` si
tiene cabeceras), como los del resto del equipo. Para compilar y subir: en VS Code con PlatformIO,
**abrir la carpeta de ese firmware** (la que tiene su `platformio.ini`) y pulsar *Upload*. La placa, el
core (pioarduino 54.03.21 = Arduino 3.x) y las librerías ya vienen en el `platformio.ini`.

- Dónde está: `firmware/puente_pc`, `firmware/mano` y `firmware/bucle_exposiciones` junto a la app
  o, en el repositorio del equipo, `firmware/centro de control/maestro/c6` (puente),
  `…/maestro/mano` y `…/maestro/bucle_exposiciones`. (La carpeta `maestro` en sí es el receptor EMG
  del equipo, otro proyecto.)
- `puente_pc` → ESP32-C6, con *USB CDC On Boot* activado (necesario para el USB nativo). Dos
  entornos: `devkitc` (la DevKitC del puente, por defecto) y `c6zero` (la C6-Zero del receptor del
  equipo, con sus mismos ajustes de placa). Hace de puente de la mano y, si la placa EMG está
  encendida, de receptor EMG.
- `mano` → ESP32-WROOM (*ESP32 Dev Module*) con la librería **ESP32Servo ≥ 3.0**.
  **Hay que volver a subirlo** para tener `POSTURA` y el `ESTADO` nuevo. En la WROOM de la mano hay
  que **mantener pulsado BOOT** al empezar a subir (si no, sale `Wrong boot mode`).
  Al arrancar envía `Mano lista … reinicio=<motivo>`: si sale `BAJADA_DE_TENSION`, los motores
  están tirando de la alimentación de la placa.
  **Alimentación**: con la radio encendida la mano necesita **al menos 1 A a 5 V**. Con 0,59 A la
  placa se reinicia sin parar al encender la radio y ni se mueve ni contesta (el bucle de
  exposiciones, sin radio, sí cabe). Si en la consola de la app aparece `Mano lista …` sin haberla
  encendido, se ha reiniciado: la fuente va justa.
- `bucle_exposiciones` → la mano sola, sin radio ni app: recorre los 8 gestos. Sirve para exponerla
  y para descartar el hardware (comprobado en la mano real). `mano` hace lo mismo en modo AUTO y
  además obedece a la app. Los motores van con `ledcAttach()` en los dos: con canales fijos 8-15
  (grupo de baja velocidad de la ESP32) no se movían.
- Todos con el core esp32 ≥ 3.0 (la API de LEDC/timers del core 2.x ya no existe). Con Arduino IDE
  también se puede: crear un sketch con el nombre del firmware y copiar dentro su `.cpp` y su `.h`.
- `biomec_protocol.h` está duplicado en `puente_pc/include` y `mano/include`: si lo cambias, cópialo
  en ambas.
- Por defecto las placas usan broadcast. Cuando sepas las MAC (las imprimen al arrancar, o con `@INFO`),
  ponlas en `HAND_MAC` y `BRIDGE_MAC` para que solo se hablen entre ellas.
