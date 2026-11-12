# Novedades de BIOMEC Control

Cada apartado es lo que ve el equipo en la ventana «Actualizar» de la app y en GitHub → Releases.
Para publicar una versión: sube `APP_VERSION`, añade aquí su apartado y ejecuta `release.ps1`.

## 0.6.0

- **El puente funciona con y sin la placa EMG** (ADS1198). Sin ella, solo mueve la mano, como siempre.
  Con ella encendida, además manda su señal al PC con el formato nuevo del sensor (el de la rama
  `Imprimir-seq`), en los mismos marcos `AA 55` que el receptor del equipo: **una sola C6 y un solo USB**
  para la mano y el EMG. Sirve igual en la DevKitC del puente que en la C6-Zero del receptor del equipo.
  El LED se pone azul mientras llega EMG. `@EMG 0` deja de mandarlo y `@INFO` dice si llega (`sensor=si`).
  Sigue entendiendo el formato antiguo del sensor (`main`).
- **La conexión de la app entiende el EMG del sensor**: separa los marcos `AA 55` de las líneas de texto
  de la mano. Da igual conectar ahí el puente o el receptor del equipo: la señal llega al Visor EMG, a
  Entrenamiento, a las Gráficas y a las sesiones, y el Visor enseña los contadores de la C6.
- Si la C6 conectada manda EMG pero no contesta a los comandos (tiene el firmware del receptor del equipo,
  que no habla con la mano), la app lo detecta y explica qué firmware subirle.
- **Firmware en `.cpp`**: el puente, la mano y el bucle de exposiciones son ahora proyectos de
  PlatformIO (`platformio.ini` + `src/*.cpp`), como el resto del equipo. Se abre la carpeta y se sube.
- Visor EMG: la lista de puertos se vuelve a buscar al abrirla y al pulsar Conectar (antes, una C6
  enchufada con la app abierta no aparecía hasta pulsar ↻).

## 0.5.0

- **Visor EMG** (Ctrl+6): el visor del equipo dentro de la app. Se conecta por USB al **receptor EMG del
  equipo** (o usa lo que llegue por el puente o la simulación) y enseña la señal en carriles por canal,
  bruta o filtrada, con escala automática y pausa. Diagnóstico del enlace: paquetes/s, perdidos, envíos
  fallidos, reinicios, marcos corruptos y los contadores del receptor. **Graba en CSV** con las columnas
  que elijas («Solo tiempo + canales» = formato del Analizador) y, al terminar, la abre en el Analizador.
- La señal del receptor EMG llega también a **Entrenamiento**, a las **Gráficas** y a las **sesiones
  grabadas**, como la del puente.
- **Analizador EMG** (Ctrl+7): el analizador de MATLAB del equipo (Carlos) en la app, sin MATLAB. Mismos
  parámetros, avisos, 7 gráficas y tabla de resultados; **Guardar** crea la carpeta de la muestra con las
  figuras, `resultados.csv`, `resumen_muestras.csv`, `senales.csv` y `coeficientes_filtros.txt`. Da los
  mismos números que MATLAB (comprobado con una muestra del repositorio).
- Barra lateral: nueva sección **EMG** (Entrenamiento, Visor y Analizador) y «Nueva gráfica» junto a
  Gráficas. El espacio *Entrenamiento* trae el Visor y el Analizador en pestañas.

## 0.4.0

- **Espacio de trabajo por ventanas**: cada parte (gemelo digital, posturas, gráficas, entrenamiento,
  consola, comandos, asistente y dispositivo) es una ventana que se muestra, oculta, recoloca, agrupa en
  pestañas o saca flotante a otra pantalla. Ya se pueden ver a la vez las gráficas, el 3D y las posturas.
  Espacios predefinidos (Demostración, Ensayo, Entrenamiento, Todo) en el menú **Ventanas**; el reparto
  se recuerda al cerrar.
- **Barra lateral plegable** (solo iconos) y ocultable (Ctrl+B); se pliega sola en ventanas estrechas.
- **Gráficas a medida**: tantas ventanas de gráficas como se quiera (**Nueva gráfica**), cada una con sus
  señales elegidas de un catálogo por magnitudes: PWM de los motores, consignas, pulgar, % cerrado
  estimado, estado, alarmas de saturación y EMG bruto y filtrado (`config/signals.json`). El eje de
  tiempo va en mm:ss.
- **Marcas de los comandos con inicio y fin**: línea discontinua al enviar el comando, zona sombreada y
  línea punteada cuando los motores terminan de moverse; la etiqueta dice cuánto tardó («GESTO 3 · 3.5 s»).
  Los movimientos que inicia la propia mano en modo demo se marcan en gris.
- **Curvas en fase con las marcas**: se dibujan en escalón (cada valor hasta la muestra siguiente). Antes,
  la línea recta desde la última muestra anterior al comando hacía parecer que la mano se movía antes.
- **Gemelo digital**: la escala de la mano ya no cambia al abrir o cerrar otras ventanas (el encuadre
  depende solo del alto de la vista).
- **Firmware de la mano**: nueva señal `fase` en la telemetría (1 mientras se mueve); hay que volver a
  subirlo para tenerla (la app funciona igual sin ella).

## 0.3.0

- **Instalador y actualizaciones automáticas**: la app se instala como cualquier programa de Windows y,
  al arrancar, avisa cuando hay una versión nueva. Se actualiza con un clic, sin perder tus ajustes ni tus datos.
- **Control por voz sin internet**: «abre la mano», «pinza», «para»… (botón del micrófono o Ctrl+M).
  Con clic derecho en el micrófono ves todas las órdenes.
- **Interfaz renovada**: cabecera más clara, avisos flotantes, controles segmentados y barra de título oscura.
- La pestaña «Entrenamiento IA» pasa a llamarse **Entrenamiento**.

## 0.2.0

- **Entrenamiento**: control con los músculos (EMG). Graba unos segundos de cada movimiento, entrena el
  modelo y pruébalo en tiempo real; después se exporta a C para la ESP32.
- **Asistente IA** (Claude): preguntas sobre la mano o la app y órdenes en lenguaje natural (necesita clave de API).
- **Mis posturas**: crea y guarda posturas propias desde el gemelo digital.
- **Sesiones**: graba una prueba (comandos, respuestas, telemetría y EMG) y vuelve a verla después.

## 0.1.0

- Primera versión: conexión con la mano por USB a través del puente ESP32-C6, catálogo de comandos,
  gráficas de telemetría, gemelo digital 3D, galería de gestos, paleta de comandos (Ctrl+K) y simulador
  para trabajar sin hardware.
