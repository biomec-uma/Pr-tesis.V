# Visor EMG

Programa de PC para **ver en tiempo real y grabar en .csv** la señal mioeléctrica del sensor.

```
Sensor (ESP32 + ADS1198) ──ESP-NOW──▶ Receptor (ESP32-C6) ──USB──▶ PC (visor_emg.py)
```

El sensor envía paquetes por radio al receptor, el receptor los reenvía por USB sin modificarlos y el visor los dibuja y los guarda.

---

## 1. Requisitos e instalación

- Python 3 con **tkinter** (viene incluido en el instalador oficial de Python para Windows).
- Dos librerías:

```
pip install pyserial numpy
```

Para ejecutarlo:

```
python visor_emg.py
```

### Crear el .exe

Ejecuta `build_exe.bat` con `logo.png` e `icono.ico` en la misma carpeta que `visor_emg.py`. El .exe resultante no necesita Python instalado. Si cambias el `.py`, vuelve a generar el .exe.

---

## 2. Uso paso a paso

### Conectar

1. Enchufa el **receptor** (C6) al PC por USB.
2. En **Puerto del receptor**, elige su puerto. El programa propone uno automáticamente; pulsa **↻** si acabas de enchufarlo.
3. En **Frecuencia del ADS (Hz)**, pon la frecuencia a la que muestrea el sensor (500 por defecto). Se usa para calcular el tiempo de cada muestra, así que **tiene que coincidir con la del sensor**.
4. Pulsa **Conectar**. Cuando lleguen paquetes aparecerá la señal.

Si el puerto está ocupado, cierra el monitor serie de PlatformIO/Arduino u otro programa que lo esté usando. Si el receptor se desconecta, el visor intenta reconectarse solo cada segundo.

### Ver la señal

- Cada canal se dibuja en su propio carril. El borde derecho (línea naranja) es **«ahora»** y el tiempo corre hacia la izquierda.
- **Ventana (s):** cuántos segundos se ven, de 1 a 30.
- **Pausar gráfica:** congela el dibujo para examinarlo. **No detiene la grabación.**
- **Escala automática:** ajusta la escala vertical de cada canal. Crece al instante y encoge despacio para que no «baile». Desmárcala para congelar la escala actual.
- A la izquierda de cada carril se ven el valor máximo y el mínimo visibles. Si el sensor envía la señal filtrada, llevan la unidad **µV**; si envía cuentas crudas, no llevan unidad.
- Cuando hay más muestras que píxeles, cada columna de píxeles dibuja el mínimo y el máximo de sus muestras. Así no se pierde ningún pico al reducir la gráfica, algo importante en EMG.

### Grabar

1. Elige la **Carpeta** y escribe un **Nombre**. El archivo se llamará `Nombre_AAAAMMDD_HHMMSS.csv`.
2. Opcional: en **Parar a los (s)** pon una duración y la grabación se detendrá sola al llegar a ese tiempo de señal.
3. Elige las **columnas** del CSV (ver más abajo).
4. Pulsa **EMPEZAR A GRABAR** (verde). Para terminar, pulsa **PARAR GRABACIÓN** (rojo).

Al parar, la barra inferior indica el archivo, cuántas muestras y segundos se han guardado y si se perdió algún paquete durante la grabación.

Mientras se graba no se pueden cambiar las columnas. Si el sensor cambia de formato a mitad de grabación (otro número de canales o de muestras por paquete, u otra versión), la grabación se detiene sola, porque el CSV ya tiene otras columnas.

---

## 3. Columnas del CSV

Hay una casilla por cada columna disponible. Marca las que quieras guardar. El recuadro de texto es el nombre que tendrá en la cabecera del CSV, y a la derecha se ve el último valor recibido.

| Columna | Contenido |
|---|---|
| `t_s` | Tiempo de la muestra en segundos, con 4 decimales |
| `seq` | Número de paquete que envía el sensor |
| `idx` | Posición de la muestra dentro de su paquete (0 … batch−1) |
| `ch1`, `ch2`, … | Valor de cada canal |
| `modo` | 0 = cuentas crudas del ADS, 1 = µV filtrados *(solo sensor versión 2)* |
| `sat` | Saturaciones del ADS *(solo versión 2)* |
| `picos` | Picos corregidos por el limpiador del sensor *(solo versión 2)* |
| `perdidas` | Muestras que el sensor no llegó a leer *(solo versión 2)* |
| `recortes` | Muestras filtradas que no cabían en 16 bits *(solo versión 2)* |

Botones de atajo:

- **Solo tiempo + canales:** guarda solo `tiempo, data0, data1…`, el formato de las grabaciones antiguas.
- **Todas (nombres originales):** marca todas las columnas con su nombre original.

La elección se recuerda para la próxima vez.

**Cómo se calcula el tiempo.** Sale de `seq` y de la frecuencia, no del reloj del PC, así que es exacto aunque el USB llegue a trompicones. Un paquete perdido deja un hueco en el tiempo. Si el sensor se reinicia, el tiempo sigue contando donde iba.

**Columnas de diagnóstico** (`sat`, `picos`, `perdidas`, `recortes`). Cada paquete escribe sus eventos en su primera fila (`idx` = 0) y 0 en las demás. Por tanto:

- **la suma de la columna** es el total de eventos de la grabación;
- **las filas con un valor distinto de 0** marcan dónde ocurrió cada uno, útil para descartar tramos al preparar datos de entrenamiento.

---

## 4. Panel de diagnóstico

Los valores en naranja indican algo a revisar.

| Fila | Qué significa | Qué hacer si sube |
|---|---|---|
| Canales × muestras | Formato del paquete del sensor | — |
| Paquetes/s | Paquetes por segundo (100 con 500 Hz y 5 muestras/paquete) | Si baja, mira los paquetes perdidos |
| Paquetes recibidos | Total desde que pulsaste Conectar | — |
| Paquetes perdidos | Huecos detectados en `seq` | Acerca el sensor al receptor o revisa interferencias |
| Envíos fallidos (sensor) | Envíos ESP-NOW que el sensor no pudo completar | Igual que los perdidos |
| Reinicios del sensor | Veces que `seq` volvió atrás | Revisa la alimentación del sensor |
| Marcos corruptos | Marcos USB con la comprobación incorrecta o un formato desconocido | Revisa el cable USB; si salen todos, el visor y el sensor no hablan la misma versión |
| Datos del sensor | Cuentas (crudo) o µV filtrado | — |
| Saturaciones (sensor) | Muestras del ADS en el límite de su rango | **Baja la ganancia del ADS** |
| Picos corregidos (sensor) | Fallos de lectura corregidos por el sensor | Alguno suelto es normal; si sube mucho, revisa el SPI |
| Muestras perdidas (sensor) | Muestras que el sensor no llegó a leer | Debería ser siempre 0 |
| Recortes (sensor) | Valores filtrados que no cabían en 16 bits | Debería ser siempre 0 |
| MAC receptor | MAC de la C6 (la que va en `rxMac` del sensor) | — |
| Inválidos (C6) | Paquetes de radio con un tamaño que el receptor no reconoce | Firmware del sensor y del receptor desparejados |
| Cola llena (C6) | Paquetes que el receptor no pudo guardar a tiempo | — |
| Descartados USB (C6) | Paquetes que el receptor no pudo enviar al PC | El PC no estaba leyendo (programa cerrado o colgado) |

Los contadores del sensor y de la C6 cuentan **desde que pulsas Conectar**, no desde que se encendieron los equipos. Con un sensor de firmware antiguo (versión 1), las filas del sensor muestran «—».

---

## 5. Protocolo (para quien modifique el programa)

Todo va en **little-endian**.

### Marco USB (receptor → PC)

```
AA 55 | tipo (1) | longitud (1) | contenido (longitud bytes) | XOR (1)
XOR = tipo ^ longitud ^ cada byte del contenido
```

| Tipo | Contenido |
|---|---|
| `0x01` DATOS | El paquete del sensor tal cual (ver abajo) |
| `0x02` ESTADO | Diagnóstico de la C6, una vez por segundo: `mac[6] recibidos(u32) invalidos(u32) perdidosCola(u32) descartadosUSB(u32)` |

Los tipos desconocidos se ignoran, así que el protocolo se puede ampliar sin romper versiones anteriores.

### Paquete del sensor (contenido de DATOS)

| Bytes | Campo | Tipo |
|---|---|---|
| 0 | `version` (1 o 2) | u8 |
| 1 | `nChnls` | u8 |
| 2 | `batch` (muestras por paquete) | u8 |
| 3–6 | `seq` | u32 |
| 7–8 | `sendFails` | u16 |
| 9 … | `data[batch][nChnls]`: muestra 0 de cada canal, muestra 1 de cada canal, … | i16 |
| *solo versión 2, al final:* | `modo`, `saturaciones`, `picosCorregidos`, `muestrasPerdidas`, `recortes` | u8 + 4 × u16 |

El número de muestras se calcula siempre como `nChnls × batch`, nunca a partir de la longitud. Los contadores de la versión 2 son **acumulados** desde que arrancó el sensor y se envían como u16: el visor resta el valor del paquete anterior con `& 0xFFFF` para que la cuenta salga bien aunque den la vuelta en 65 535.

Para añadir una versión nueva del paquete:

1. Añádela a `COLA_VERSION` con los bytes que lleva tras los datos.
2. Léelos en `Receptor.procesar()`.
3. Si quieres grabarlos, añade sus columnas en `ids_columnas()`.

---

## 6. Organización del código

| Parte | Qué hace |
|---|---|
| Constantes `PROTOCOLO` | Firmas, tipos de marco, formatos `struct` y versiones admitidas |
| `Datos` | Todo lo que comparten el hilo receptor y la ventana: memoria circular de 31 s de señal, contadores y grabación activa. Protegido con un *lock* |
| `Grabacion` | Abre el CSV, escribe solo las columnas elegidas y vuelca a disco cada segundo |
| `Receptor` (hilo) | Lee el USB, separa los marcos por la firma `AA 55`, comprueba el XOR y reparte el contenido. Se reconecta solo si se pierde el puerto |
| `Grafica` | Dibuja los carriles sobre un `Canvas` de tkinter |
| `App` | La ventana: conexión, panel lateral, grabación y refresco unas 25 veces por segundo |

La ventana y el receptor van en hilos separados: aunque la gráfica vaya lenta, no se pierden datos.

La configuración (puerto, frecuencia, ventana, carpeta, nombre y columnas) se guarda en `~/.visor_emg.json` al conectar, al grabar y al cerrar. Si algo se queda raro, borrar ese archivo devuelve el programa a sus valores por defecto.
