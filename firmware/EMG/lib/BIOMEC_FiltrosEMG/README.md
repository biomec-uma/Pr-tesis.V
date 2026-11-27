# Sistema EMG para prótesis: guía completa explicada desde cero

20/11/2026 · Dylan


## Conceptos básicos

Esta sección explica las ideas que se usan en el resto del documento. Si ya las conoces, puedes saltarla; si no, merece la pena leerla con calma, porque todo lo demás se apoya en ella.



### Muestreo y frecuencia de muestreo

**Muestrear** es medir la señal a intervalos regulares. Cada medida es una **muestra**.

La **frecuencia de muestreo** (se escribe *fs*) es cuántas muestras se toman por segundo, y se mide en hercios (Hz) o en *muestras por segundo* (SPS, *samples per second*). En este proyecto, **fs = 500 Hz**: una muestra cada **2 ms**.

Hay una regla fundamental, el **teorema de Nyquist**: con una frecuencia de muestreo *fs* solo se pueden representar correctamente frecuencias por debajo de *fs/2*. Esa mitad se llama **frecuencia de Nyquist**. Con 500 Hz, el límite es **250 Hz**. Por eso ningún filtro del proyecto puede trabajar por encima de 250 Hz.



### Ruido e interferencias

**Ruido** es todo lo que se mide y no es la señal que interesa. Conviene distinguir dos tipos:

- **Ruido de fondo:** aleatorio y repartido por todas las frecuencias. Viene de los propios componentes, de la piel y de los electrodos. No se puede eliminar filtrando, solo reducir con buen hardware.
- **Interferencias:** señales externas con una frecuencia concreta que se cuelan en la medida. Como están en frecuencias fijas, sí se pueden eliminar con filtros.

La interferencia más habitual es la de la **red eléctrica**. En Europa, los enchufes funcionan con corriente alterna de **50 Hz**, y los cables de la casa radian ese campo. El cuerpo actúa como una antena y lo recoge. Además aparecen sus **armónicos**: frecuencias múltiplo de la principal (100, 150, 200 Hz…), que se producen porque los aparatos no consumen la corriente de forma perfectamente senoidal.

### Modo común y medida diferencial

Cada canal EMG usa **dos electrodos** sobre el músculo y el sistema mide la **diferencia** de tensión entre ellos: es una **medida diferencial**. La interferencia de la red llega casi igual a los dos electrodos; a esa parte igual se le llama **tensión de modo común**. Al restar, se cancela. La señal del músculo, en cambio, es distinta en cada electrodo y sobrevive a la resta.

Esta cancelación solo funciona bien si **los dos electrodos hacen igual de buen contacto**. Si uno contacta peor, la interferencia ya no llega igual a ambos y deja de cancelarse. Por eso, cuando un canal tiene más ruido que otro, lo primero es revisar sus electrodos.

### Decibelios (dB)

Los **decibelios** son una forma de expresar cuántas veces es mayor o menor una magnitud usando una escala logarítmica. Para tensiones: −6 dB es aproximadamente la mitad; −20 dB, la décima parte; −40 dB, la centésima. Se usan para describir cuánto atenúa un filtro: «−48 dB a 5 Hz» significa que una señal de 5 Hz sale unas 250 veces más pequeña.

## El hardware


### El ADS1198: el conversor de la señal


**Tensión de referencia (Vref).** Es la tensión con la que el ADC compara la señal para decidir qué número darle. El ADS1198 usa una referencia interna de **2,4 V** (lo fija el registro `CONFIG3 = 0xCC`). Con ella, el rango de entrada es ±Vref / ganancia: con ganancia 12, ±200 mV.

**De cuentas a microvoltios.** Cada cuenta equivale a:

```
                 2 × Vref               2 × 2,4 V
1 cuenta = ───────────────────── = ─────────────── ≈ 6,1 µV
             ganancia × 65 536       12 × 65 536
```

Con ganancia 4 (la que había al principio) cada cuenta valía unos 18,3 µV: tres veces menos resolución.

**Filtro interno del ADS.** Antes de entregar cada número, el ADS1198 aplica un filtro digital propio (llamado *sinc*). Su efecto es un paso bajo con el corte en torno a 0,26 veces la frecuencia de muestreo: a 500 SPS, unos **130 Hz**. Por eso el proyecto no necesita añadir su propio paso bajo.

**DRDY (Data Ready).** Es un pin del ADS que cambia de nivel cada vez que tiene una muestra nueva lista: a 500 SPS, cada 2 ms. El ESP32 vigila ese pin y, cuando cambia, lee la muestra. Es el « reloj » que marca el ritmo de todo el sistema.

**SPI.** Es el bus de comunicación entre el ESP32 y el ADS: cuatro cables (reloj, datos de ida, datos de vuelta y selección de chip) por los que el ESP32 configura el ADS y le lee las muestras. Si una lectura SPI sale mal (por ejemplo, porque coincide con un cambio de la muestra), llega un valor absurdo. En las grabaciones aparecían muestras sueltas como `0, 0` o `1, 4086`: eso son fallos de lectura, no señal.

**El ADS no guarda muestras.** Si el ESP32 tarda más de 2 ms en leer una muestra, la siguiente la sobrescribe y la anterior se pierde. Esto fue la causa de uno de los problemas resueltos (sección «Cómo se encontraron y resolvieron los problemas»).

**RLD (Right Leg Drive).** El nombre viene de los electrocardiogramas, donde este electrodo se pone en la pierna derecha. Es un circuito que mide la tensión de modo común de los electrodos (la interferencia que llega igual a todos), la invierte y la devuelve al cuerpo por un electrodo extra. Así reduce activamente la interferencia de la red. Hacerlo funcionar fue lo que permitió pasar de una señal tapada por el ruido de 50 Hz a una señal aprovechable.

### El ESP32: el microcontrolador



El proyecto usa un **ESP32-C3** como emisor y un **ESP32-C6** como receptor, y está previsto pasar el emisor también a C6. Dos características suyas influyen en el diseño:

- **Un solo núcleo.** Con uno solo, todo (leer el ADS, filtrar, la radio) comparte el mismo procesador, turnándose muy rápido. Si una tarea se queda con el procesador demasiado tiempo, las demás esperan.
- **Sin FPU.** La **FPU** (*Floating Point Unit*) es un circuito que hace cálculos con decimales (`float`) directamente. El C3 y el C6 no la tienen, así que esos cálculos se hacen por software, varias veces más lento. Aun así, el filtrado del proyecto ocupa un porcentaje pequeño del procesador; lo que no sería viable es un filtro con cientos de coeficientes.

### ESP-NOW: la radio

**ESP-NOW** es un protocolo de Espressif para que dos ESP32 se manden mensajes cortos directamente, sin router ni red Wi-Fi. Cada mensaje puede tener hasta **250 bytes** en caso de usar C6 se podrían usar otra versión de ESPNOW con mas capacidad. 

El emisor envía **100 paquetes por segundo**, cada uno con 5 muestras de cada canal (10 ms de señal). Después de las pruebas, su potencia de emisión está reducida a **5 dBm**, suficiente para llegar del brazo al receptor en la mesa. El motivo está en la sección de problemas: con más potencia, la propia radio se colaba en la medida.

## Filtros digitales desde cero


### Los tipos de filtro que se usan

| Filtro | Qué deja pasar | Para qué se usa aquí |
| --- | --- | --- |
| **Paso alto** | Solo frecuencias **por encima** de una frecuencia de corte | Quitar lo que hay por debajo de 20 Hz: el desplazamiento lento de la línea base y los artefactos de movimiento |
| **Paso bajo** | Solo frecuencias **por debajo** de la de corte | Quitar lo más rápido. Aquí está desactivado porque ya lo hace el ADS en torno a 130 Hz |
| **Paso banda** | Solo una franja entre dos frecuencias | Es un paso alto y un paso bajo seguidos |
| **Notch** (o de muesca, o rechazo de banda) | Todo **menos** una franja muy estrecha | Eliminar interferencias de frecuencia fija: 50 Hz y sus armónicos |

La **frecuencia de corte** es la frecuencia a partir de la cual el filtro empieza a actuar. Por convenio es el punto en que la señal sale reducida a un 70 % (−3 dB).

### Qué es la Q de un notch

Un notch quita una franja estrecha alrededor de su frecuencia central. El **factor de calidad Q** dice cómo de estrecha es:

```
                          frecuencia central
anchura de la muesca = ────────────────────────
                                 Q
```

Un notch de 50 Hz con Q = 35 quita una franja de unos 1,4 Hz; con Q = 20, de unos 2,5 Hz. Cuanto más estrecha, menos señal EMG útil se pierde, pero si la frecuencia de la red varía un poco (oscila ligeramente alrededor de 50 Hz), una muesca demasiado estrecha deja escapar parte de la interferencia. El proyecto usa Q = 20 en 50 Hz y Q = 35 en los armónicos.

### ¿Cómo funciona un filtro por software?

Un filtro digital calcula cada muestra de salida combinando la muestra actual con algunas anteriores. La forma más usada es la **ecuación en diferencias**:

```
y[n] = b0·x[n] + b1·x[n-1] + b2·x[n-2] − a1·y[n-1] − a2·y[n-2]
```

- `x[n]` es la muestra que acaba de llegar, `x[n-1]` la anterior y `x[n-2]` la de antes.
- `y[n]` es la muestra filtrada que sale, e `y[n-1]`, `y[n-2]`, las que salieron antes.
- `b0, b1, b2, a1, a2` son los **coeficientes**: cinco números fijos que deciden qué tipo de filtro es y dónde corta.

Todos los filtros del código usan esta misma ecuación; un paso alto, un paso bajo y un notch solo se diferencian en sus cinco coeficientes. Un filtro con esta forma se llama **biquad** (filtro de segundo orden). Los coeficientes se calculan con fórmulas conocidas a partir de la frecuencia, la Q y la frecuencia de muestreo. Se calculan una sola vez al arrancar, y después cada muestra solo cuesta cinco multiplicaciones (b0* x, b1* x, b2* x, a1* y, a2* y).

Como el filtro necesita recordar las muestras anteriores, necesita **memoria** (también llamada **estado**). Por eso cada canal tiene su propio filtro, en caso de usar un filtro para varios canales sus valores pasados se mezclarían alterando la salida.

### Orden y Butterworth

El **orden** de un filtro indica cómo de brusco es su corte. Un biquad es de orden 2. Para un corte más brusco se ponen varios en cadena: dos biquads seguidos forman un filtro de orden 4. Cada orden añade unos 6 dB de atenuación por cada vez que la frecuencia se reduce a la mitad.

**Butterworth** es una forma concreta de diseñar el filtro para que, en la zona que deja pasar, la respuesta sea lo más plana posible: no realza ni atenúa ninguna frecuencia útil. El paso alto del proyecto es un Butterworth de orden 4 a 20 Hz, que se comporta así:

| Frecuencia | Lo que sale |
| --- | --- |
| 5 Hz | 250 veces más pequeño (−48 dB) |
| 10 Hz | 16 veces más pequeño (−24 dB) |
| 20 Hz | Al 70 % (−3 dB, la frecuencia de corte) |
| 30 Hz o más | Prácticamente igual que entra |

### IIR frente a FIR

Hay dos grandes familias de filtros digitales:

- **IIR** (*Infinite Impulse Response*): usan también las **salidas** anteriores (los términos con `a1` y `a2`). Con muy pocos coeficientes consiguen cortes bruscos. Son los que usa el código.
- **FIR** (*Finite Impulse Response*): solo usan **entradas** anteriores, pero necesitan muchos coeficientes. Su ventaja es que no deforman la forma de la onda (tienen **fase lineal**).

El analizador de Carlos proponía un paso banda FIR de **595 coeficientes**. Se descartó por dos motivos:

- **Retardo:** un FIR así entrega cada muestra con (595 − 1) / 2 = 297 muestras de retraso, es decir, **0,594 s**. En una prótesis, medio segundo entre que contraes el músculo y la mano responde es demasiado.
- **Cálculo:** 595 multiplicaciones por muestra y canal, en un chip sin FPU.

La cadena IIR del proyecto retrasa la señal solo **unos pocos milisegundos** y cuesta una pequeña fracción del procesador. A cambio deforma un poco la fase de la onda, lo que no importa para detectar contracciones.

### Filtrado causal y por qué importa al entrenar un modelo

Si se entrena un modelo de aprendizaje automático con señales filtradas en el PC de otra forma, el modelo verá en la prótesis una señal distinta de la que aprendió. La regla es: **entrenar con la misma señal que procesará el sensor**. Lo más sencillo es grabar directamente la señal ya filtrada por el ESP32, que es lo que hace el sistema en modo filtrado.

## La cadena de procesado

Cada muestra recorre siempre el mismo camino dentro del emisor, desde que el ADS avisa de que está lista hasta que sale por radio. Todo el recorrido tarda una fracción de los 2 ms que hay entre muestras.

**Cada muestra se limpia y se filtra antes de salir por radio.** Todo ocurre en la tarea de adquisición, cada 2 ms. Las etapas marcadas con ★ son de la librería BIOMEC_FiltrosEMG.

```
    ADS1198        
 Avisa por DRDY 
Leer y convertir
  cuentas a µV
--------------------------
       ▼ ▼ ▼
--------------------------
★ Limpieza de picos
+2 ms de retraso
--------------------------
       ▼ ▼ ▼
--------------------------
★ Paso alto 20 Hz
Butterworth orden 4
--------------------------
       ▼ ▼ ▼
--------------------------
  ★ 4 notch             
50, 100, 150, 200 Hz
--------------------------
       ▼ ▼ ▼
--------------------------
    A int16
Redondeo y recorte
--------------------------
       ▼ ▼ ▼
--------------------------
    Paquete  
5 muestras + contadores
--------------------------
       ▼ ▼ ▼
--------------------------
    ESP-NOW
Cada 10 ms, a 5 dBm
--------------------------
```

El paso bajo existe en la librería, pero está desactivado porque el filtro interno del ADS ya corta en unos 130 Hz. Si se activara, iría justo después de los notch. En modo crudo (`ENVIAR_FILTRADO 0`), la muestra salta de la lectura directamente al paquete, en cuentas y sin procesar.

## El programa del emisor

El emisor es el `main.cpp` que corre en el ESP32 conectado al ADS. Su trabajo, cada 2 ms, es: leer una muestra de cada canal, limpiarla, filtrarla, convertirla a entero y meterla en un paquete. Cada 5 muestras envía el paquete por radio.

### Interrupciones

En el emisor, la interrupción salta cada vez que el pin **DRDY** del ADS indica que hay una muestra nueva:

```cpp
attachInterrupt(digitalPinToInterrupt(dataReady_Pin), dataReadyADS, FALLING);
```

`FALLING` significa que salta cuando el pin pasa de nivel alto a bajo, que es como el ADS avisa.

Como las interrupciones detiene todo el programa para ejecutarse **deben ser cortas**, por eso `dataReadyADS()` no lee el ADS ni filtra nada; solo hace dos cosas:

1. Suma 1 a `contadorDRDY`, para llevar la cuenta de cuántas muestras ha producido el ADS.
2. Despierta a la tarea de adquisición (`vTaskNotifyGiveFromISR`).

La palabra `volatile` delante de `contadorDRDY` le dice al compilador que esa variable puede cambiar «en cualquier momento» (desde la interrupción), para que no haga optimizaciones que asuman que no cambia.
### FreeRTOS y la tarea de adquisición

El ESP32 lleva dentro **FreeRTOS**, un pequeño **sistema operativo de tiempo real**. Permite tener varias **tareas**: funciones que se ejecutan «a la vez». Con un solo núcleo no es literalmente a la vez: el sistema las va turnando muy deprisa. Cada tarea tiene una **prioridad**; cuando dos quieren ejecutarse, gana la de prioridad más alta.

El propio `loop()` de Arduino es una tarea más, de prioridad 1. 
Durante las pruebas se ha descubierto que **se detiene la función `loop()` unos 5 ms cada 2 segundos** para atender al sistema. Como el ADS produce una muestra cada 2 ms y no las guarda, en esa pausa se perdían 1 o 2 muestras.

La solución fue sacar el trabajo de `loop()` a una tarea propia, `tareaAdquisicion`, con **prioridad 10**:

```cpp
xTaskCreate(tareaAdquisicion, "adquisicion", 4096, NULL, 10, &tareaADS);
```

Los argumentos son:

`[La función de la tarea; un nombre; la memoria que reserva para ella (4096 bytes de **pila**); un parámetro que no se usa; la prioridad; dónde guardar su identificador].`

La tarea es un bucle infinito que **duerme** hasta que la interrupción la despierta (`ulTaskNotifyTake`). Al despertar, comprueba si se ha saltado alguna muestra, lee el ADS y procesa la muestra. Luego vuelve a dormir. Mientras duerme no gasta procesador, así que el resto del sistema (la radio, `loop()`) puede trabajar. Como tiene más prioridad que `loop()`, las pausas de `loop()` ya no le afectan.

La tarea se crea **antes** de activar la interrupción: si la interrupción saltara antes, intentaría despertar a una tarea que todavía no existe.

### Cómo se detectan las muestras perdidas

La interrupción cuenta las muestras que produce el ADS (`contadorDRDY`) y la tarea cuenta las que lee (`muestrasProcesadas`). Si al leer ve que el ADS ha producido dos o más desde la última vez, es que alguna se sobrescribió sin leerse, y suma la diferencia a `muestrasPerdidas`. Con la tarea de adquisición, este contador se queda en 0.

### procesarMuestra(): qué se hace con cada muestra

1. **Leer** el valor de cada canal del ADS, en cuentas.
2. **Comprobar la saturación:** si el valor está por encima de 32 000 o por debajo de −32 000, el ADS está cerca de su límite; se suma una saturación. Se hace sobre las cuentas porque la saturación depende del rango del ADC, no de la tensión.
3. **Convertir a microvoltios:** `cuentas × UV_POR_CUENTA` (unos 6,1 µV por cuenta con ganancia 12). Así los datos y los umbrales no dependen de la ganancia elegida.
4. **Limpiar picos** con el `LimpiadorPicos` (siguiente apartado).
5. **Filtrar** cada canal con su `FiltroEMG`: paso alto de 20 Hz y notch de 50, 100, 150 y 200 Hz.
6. **Convertir a entero de 16 bits** (`int16`) redondeando, porque el paquete guarda los datos así. Si un valor no cupiera (más de ±32 767 µV), se recorta al máximo y se suma un **recorte**.
7. **Guardar en el paquete.** Cuando el paquete tiene 5 muestras, se le añaden los contadores de diagnóstico y se envía.

Todos los cálculos intermedios se hacen con decimales (`float`) y solo se redondea al final, para no perder precisión entre etapas.

### El limpiador de picos
Durante las grabaciones más duraderas se veían picos aleatorios de forma muy esporadica, que alteraban el resultado del filtrado en el analizador, tras ver que eran picos con valores absurdos y sin relación aparente se decidieron quitar de raíz antes de que pudiera afectar al filtrado de la señal

El `LimpiadorPicos` mira cada muestra junto con la anterior y la siguiente. Si se aleja una cantidad croqueta ;) de la media de sus vecinas, y las vecinas coinciden entre sí, es un pico aislado: se sustituye por esa media. Si un canal tiene un pico se corrige la **trama** entera (todos los canales de ese instante).

¿Cual es esa croqueta cantidad? El umbral se adapta a la actividad de cada canal (`factor × nivel típico + suelo`, con factor 12 y suelo 300 µV). En reposo es bajo; durante una contracción sube solo, para no confundir músculo real con un fallo. Los valores [factor;suelo] han sido calculados a mano, para [12;150], [12;300], [20;150], en la primera se modifican muchos valores, en la segunda hubo un equilibrio y en la tercera se escapaban algunos picos. 
Para poder mirar la muestra siguiente, el limpiador entrega cada muestra con **una muestra de retraso** (2 ms).

### Modo filtrado y modo crudo

Con `#define ENVIAR_FILTRADO 1` el emisor envía los microvoltios filtrados. Con `0` envía las cuentas del ADS sin tocar, igual que el programa original, se puede usar para depurar o para grabar la señal sin procesar. Si se activa el modo de prueba del ADS (`testADS = true`), el emisor pasa a modo crudo por defecto porque el paso alto deformaría las señales de prueba.

### Potencia de la radio

En `initEspNow()`, justo después de arrancar ESP-NOW:

```cpp
esp_wifi_set_max_tx_power(20); //20 = 5 dBm (unidades de 0,25 dBm)
```

La función mide la potencia en unidades de 0,25 dBm, así que 20 equivale a 5 dBm. Por defecto el ESP32 emite a unos 20 dBm. Mirando las graficas la IA veía que había un ruido de 100Hz que se repetía dentro de cada paquete de la misma forma, por eso surgío la idea de que ese ruido la producía la antena emisora ya que se repetía en cada envío. Si algún día empiezan a perderse paquetes porque el receptor está más lejos, se puede subir (por ejemplo, a 34, que son 8,5 dBm).

## La librería de filtros

Una **librería** se llama `BIOMEC_FiltrosEMG` y tiene dos archivos:

- **`BIOMEC_FiltrosEMG.h`** (la **cabecera**): dice *qué* ofrece la librería (qué clases y funciones existen). Es lo que se incluye con `#include`.
- **`BIOMEC_FiltrosEMG.cpp`** (la **implementación**): dice *cómo* lo hace (el código de cada función).

### Clases y objetos

Una **clase** es como una plantilla que agrupa datos y las funciones que trabajan con ellos. 

Un **objeto** es un ejemplar concreto creado a partir de esa plantilla, con sus propios datos. 

Por ejemplo, `FiltroEMG` es la clase, y `filtros[0]` y `filtros[1]` son dos objetos, uno por canal, cada uno con su propia memoria.

Las funciones de una clase se llaman **métodos** y se usan con un punto: `filtros[0].notch(50)`.

### Las tres clases

| Clase | Qué es | Quién la usa |
| --- | --- | --- |
| `Biquad` | Un filtro de segundo orden: los 5 coeficientes, las 2 variables de memoria y la ecuación en diferencias | Las usa `FiltroEMG` por dentro |
| `FiltroEMG` | La cadena completa de filtros de **un** canal: paso alto, hasta 4 notch y paso bajo | El `main.cpp`, un objeto por canal |
| `LimpiadorPicos` | El detector y corrector de tramas corruptas, para **todos** los canales a la vez | El `main.cpp`, un solo objeto |

### Cómo se usa FiltroEMG

```cpp
#include <BIOMEC_FiltrosEMG.h>

FiltroEMG filtro;              // crea el objeto (sin configurar)

void setup() {
  filtro.iniciar(500);         // frecuencia de muestreo en Hz
  filtro.pasoAlto(20);         // paso alto de 20 Hz
  filtro.notch(50, 20);        // notch de 50 Hz con Q = 20
  filtro.notch(100);           // notch de 100 Hz (Q = 35 si no se indica)
}

// por cada muestra nueva, en microvoltios:
float limpia = filtro.procesar(muestra);
```

Otro ejemplo "mas personalizado"
```cpp
#include <BIOMEC_FiltrosEMG.h>

FiltroEMG filtro;              // crea el objeto (sin configurar)

void setup() {
  // Canal 1: solo un notch de 50 Hz
  filtros[0].iniciar(500);
  filtros[0].notch(50, 20);

  // Canal 2: solo un paso alto de 20 Hz
  filtros[1].iniciar(500);
  filtros[1].pasoAlto(20);
}

// por cada muestra nueva, en microvoltios:
float limpia = filtros[ch].procesar(...)
```

| Método | Qué hace |
| --- | --- |
| `iniciar(fs)` | Fija la frecuencia de muestreo y deja todas las etapas desactivadas. Se llama primero |
| `pasoAlto(fc)` | Activa un paso alto Butterworth de orden 4 (dos biquads) con corte en `fc` |
| `notch(f0, Q)` | Añade un notch en `f0`. Caben hasta 4. Si ya había uno en esa frecuencia, solo cambia su Q |
| `pasoBajo(fc)` | Activa un paso bajo Butterworth de orden 2 con corte en `fc` |
| `pasaBanda(fBaja, fAlta)` | Atajo: `pasoAlto(fBaja)` + `pasoBajo(fAlta)` |
| `quitarPasoAlto()`, `quitarNotch()`, `quitarPasoBajo()` | Desactivan esa etapa. `quitarNotch()` quita todos los notch |
| `reiniciar()` | Borra la memoria de todos los filtros, por ejemplo tras cambiar la configuración |
| `procesar(x)` | Filtra **una** muestra y devuelve el resultado. Se llama una vez por muestra, siempre en orden |

Los métodos de configuración devuelven `true` si todo fue bien y `false` si la frecuencia no es válida (tiene que estar entre 0 y fs/2) o si ya no caben más notch.

Dentro de `procesar()` el orden es siempre: paso alto → notch (todos, uno detrás de otro) → paso bajo. El paso alto va primero para que el resto trabaje con una señal centrada en cero.

**El truco del arranque.** Al recibir la primera muestra, `FiltroEMG` la guarda y la resta de todas las siguientes. Sin ese truco, el paso alto vería pasar de golpe de 0 al valor de la señal (que puede tener un offset de miles de µV) y daría un salto enorme al arrancar. Con él, el arranque es suave.

### Cómo se usa LimpiadorPicos

```cpp
LimpiadorPicos limpiador(2);           // 2 canales, umbrales por defecto

float entrada[2], salida[2];
// ... rellenar entrada con la trama nueva ...
if (limpiador.procesar(entrada, salida)) {
  // salida contiene la trama ANTERIOR, ya revisada
}
```

`procesar()` devuelve `false` en las dos primeras llamadas, porque todavía no hay vecinas con las que comparar. `tramasCorregidas()` devuelve cuántas tramas ha corregido desde que arrancó. Admite hasta 8 canales, los del ADS1198.

### Configuración actual en el emisor

| Parámetro | Valor | Dónde se cambia en `main.cpp` |
| --- | --- | --- |
| Frecuencia de muestreo | 500 Hz | `FS_HZ` (debe coincidir con `adsSPS`) |
| Paso alto | 20 Hz | `FC_PASO_ALTO` |
| Notch | 50 Hz (Q 20), 100, 150 y 200 Hz (Q 35) | Listas `F_NOTCH` y `Q_NOTCH` |
| Paso bajo | Desactivado | `FC_PASO_BAJO` (0 = desactivado) |
| Limpiador | Factor 12, suelo 300 µV | Al crear `limpiador` |

## El paquete de datos y el protocolo

Un **protocolo** es un acuerdo sobre cómo se ordenan los datos que se envían, para que quien los recibe sepa interpretarlos. Si el emisor y el receptor no están de acuerdo, el receptor lee basura. Por eso, cuando se cambia el formato del paquete, hay que actualizar los tres programas: emisor, receptor y visor.

### La estructura del paquete

En el código, el paquete es un `struct` (una agrupación de variables) llamado `Packet`. Lleva `__attribute__((packed))` para que el compilador no meta bytes de relleno entre campos: así el paquete ocupa exactamente lo que suman sus campos y el receptor puede leerlo byte a byte. 

El comentario «NO CAMBIAR EL ORDEN DE LOS CAMPOS» es literal: si se cambia, el receptor lo leerá mal.

Con 2 canales y 5 muestras por paquete, el paquete ocupa **38 bytes**:

| Bytes | Campo | Tipo | Qué contiene |
| --- | --- | --- | --- |
| 0 | `version` | `uint8_t` | Versión del formato del paquete: 2 |
| 1 | `nChnls` | `uint8_t` | Número de canales: 2 |
| 2 | `batch` | `uint8_t` | Muestras por paquete: 5 |
| 3–6 | `seq` | `uint32_t` | Número de paquete. Sube de 1 en 1; vuelve a 0 si el sensor se reinicia |
| 7–8 | `sendFails` | `uint16_t` | Envíos de radio fallidos, según el propio emisor |
| 9–28 | `data[5][2]` | `int16_t` × 10 | Las muestras en µV: muestra 0 del canal 1, muestra 0 del canal 2, muestra 1 del canal 1… |
| 29 | `modo` | `uint8_t` | 0 = cuentas crudas, 1 = µV filtrados |
| 30–31 | `saturaciones` | `uint16_t` | Muestras del ADS cerca del límite |
| 32–33 | `picosCorregidos` | `uint16_t` | Tramas corregidas por el limpiador |
| 34–35 | `muestrasPerdidas` | `uint16_t` | Muestras que el ADS sobrescribió sin que se leyeran |
| 36–37 | `recortes` | `uint16_t` | Valores filtrados que no cabían en `int16` |

Los campos 29–37 se añadieron en la **versión 2** del paquete de envio. Se pusieron al final para no mover ninguno de los anteriores. El receptor sigue aceptando paquetes de la versión 1 de los paquetes que enviaba ADS->Master (29 bytes, sin esos campos).

El tamaño máximo de un mensaje ESP-NOW es 250 bytes. El código lo comprueba al compilar con `static_assert`: si se suben demasiado los canales o las muestras por paquete, el programa no compila y avisa.

### ¿Por qué 5 muestras por paquete?

Enviar cada muestra por separado serían 500 envíos por segundo, demasiados para la radio. 

Agrupar demasiadas retrasa la señal, por ejemplo con `BATCH` = 50, cada paquete tardaría 100 ms en llenarse. 

Con 5 se envían **100 paquetes por segundo** y el retraso por agrupar es de 10 ms, un buen equilibrio para una prótesis.

### Contadores acumulados

Los contadores de diagnóstico (y `sendFails`) no dicen cuántos eventos hubo en ese paquete, sino cuántos ha habido **desde que arrancó el sensor**. Para saber cuántos hubo entre dos paquetes, el receptor resta el valor del anterior.

La ventaja es que perder un paquete no hace perder información: el siguiente trae el total actualizado. Como son de 16 bits, al pasar de 65 535 vuelven a 0; la resta sin signo (con `& 0xFFFF` en el visor) sigue dando el número correcto aunque eso ocurra.

### El marco USB (receptor → PC)

El receptor envía cada paquete al PC por USB envuelto en un **marco**, para que el PC sepa dónde empieza y acaba cada uno dentro del flujo continuo de bytes:

| Parte | Bytes | Qué es |
| --- | --- | --- |
| Firma | `AA 55` | Dos bytes fijos que marcan el inicio de un marco |
| Tipo | 1 | `01` = paquete del sensor, `02` = estado del receptor |
| Longitud | 1 | Cuántos bytes de contenido vienen |
| Contenido | Variable | El paquete del sensor tal cual, o el estado del receptor |
| Comprobación | 1 | XOR del tipo, la longitud y todos los bytes del contenido |

El **XOR** es una operación entre bits que sirve como prueba sencilla de integridad: el PC la recalcula y, si no coincide, descarta el marco como corrupto. Esto evita que un `AA 55` que aparezca por casualidad dentro de los datos se confunda con el inicio de un marco.

## El receptor

### El receptor (ESP32-C6)

El receptor es un ESP32-C6 conectado al PC por USB. Hace de puente: recibe los paquetes por radio y los pasa al PC sin modificarlos. No filtra ni interpreta la señal.

**Cómo recibe.** Cuando llega un mensaje ESP-NOW, el sistema llama automáticamente a la función `onDataReceived` (es un **callback**: una función que se registra para que otro código la llame cuando ocurre algo). Esa función comprueba que el paquete tiene sentido:

1. Que su longitud esté entre 9 y 250 bytes.
2. Que su versión sea conocida (1 o 2).
3. Que su longitud coincida exactamente con lo que debería medir según su versión, sus canales y sus muestras: [ 9 + canales × muestras × 2 + (más 9 bytes si es la versión 2) ].

**Si algo falla, lo cuenta como inválidoy lo descarta.** 

**La cola.** El callback se ejecuta en el contexto de la radio y debe terminar rápido, así que no envía nada por USB. Mete el paquete en una **cola** de FreeRTOS: una lista de espera con sitio para 16 paquetes, donde un lado mete y el otro saca. El `loop()` del receptor saca los paquetes de la cola y los envía al PC. Si la cola se llena, el paquete se cuenta como **perdido en cola**.

**Envío sin bloqueo.** Si el PC no está leyendo (el visor está cerrado), el receptor no espera: descarta el paquete y lo cuenta como **descartado USB**. Así nunca se queda colgado.

**Estado.** Una vez por segundo envía al PC un marco de estado con su dirección MAC y sus contadores (recibidos, inválidos, perdidos en cola, descartados USB).

**LED.** 

El LED del receptor indica cómo va todo:

| Color | Significado |
| --- | --- |
| Rojo | No llegan paquetes del sensor (lleva más de 0,5 s sin recibir) |
| Azul | Recibiendo con normalidad |
| Amarillo | Recibiendo, pero el sensor ha saturado en el último segundo: hay que bajar la ganancia |

## El Visor EMG (programa del PC)

El visor es un programa en Python, `visor_emg.py`, que se puede convertir en un `.exe` para Windows. Lee los marcos del USB, dibuja la señal en tiempo real y la graba en archivos CSV. El **CSV** (*comma-separated values*) es un archivo de texto con una fila por muestra y los valores separados por comas, que se abre con Excel o cualquier herramienta de análisis.

**Uso básico indicado en el README junto al programa**


**Cómo calcula el tiempo.** El tiempo de cada muestra no sale del reloj del PC, sino del número de paquete (`seq`) y la posición de la muestra dentro del paquete (`idx`). Así es exacto aunque el USB entregue los datos a trompicones.

**Columnas del CSV:**

| Columna | Qué contiene |
| --- | --- |
| `t_s` | Tiempo en segundos |
| `seq`, `idx` | Número de paquete y posición dentro de él |
| `ch1`, `ch2` | Valor de cada canal (en µV en modo filtrado) |
| `modo` | 0 = cuentas, 1 = µV filtrados |
| `sat`, `picos`, `perdidas`, `recortes` | Eventos de diagnóstico de ese paquete: se escriben en su primera fila y 0 en las demás, así que sumar la columna da el total de la grabación |

***Panel de diagnóstico*** 

Muestra todos los contadores desde que se pulsó Conectar. Los importantes:


**Paquetes/s** (Unos 100)--> — 

**Paquetes perdidos** --> Problema de radio: algo tapa la antena o el receptor está lejos 

**Reinicios del sensor** --> El emisor se ha reiniciado (alimentación, botón de reset) 

**Saturaciones (sensor)** --> Bajar la ganancia del ADS 

**Muestras perdidas (sensor)** --> El emisor no da abasto a leer el ADS 

**Recortes (sensor)** --> Valores filtrados fuera de rango 

**Inválidos (C6)** --> Emisor y receptor no usan el mismo formato de paquete 

**Descartados USB (C6)** --> El PC no lee a tiempo 

Para poner el panel a cero no hace falta reiniciar el sensor: basta con pulsar Desconectar y Conectar en el visor. Los detalles completos del visor están en su `README.md`.


### Estructura de carpetas

```
proyecto-emisor/
├── platformio.ini
├── src/
│   └── main.cpp                  ← el programa
└── lib/
    └── BIOMEC_FiltrosEMG/
        ├── BIOMEC_FiltrosEMG.h   ← la cabecera de la librería
        └── BIOMEC_FiltrosEMG.cpp ← la implementación
```

### Posible fallo a tener en cuenta--> #include de Arduino.h

En un `.cpp` hay que escribir `#include <Arduino.h>`. A veces funciona sin escribirla porque otra librería (como `WiFi.h`) la incluye por dentro, pero es mejor ponerla explícitamente en los `main.cpp`por si acaso, uno nunca sabe jeje. La librería de filtros, en cambio, no la necesita, porque no usa nada de Arduino.


## Cómo se encontraron y resolvieron los problemas

Se hicieron varias grabaciones seguidas el 18 y especialmente el 19 donde se hacía un formato de grabaciones de 30 segundos [10 reposo + 10 contracciones + 10 reposo]. 

El resultado al final de las pruebas y las correcciones fueron dos canales con unos 3 µV de ruido en reposo frente a los 29 µV en el canal 2 antes de aplicar filtros.

**El ruido en reposo del canal 2 bajó de 29 a 2,6 µV.** 

| Cambio | Canal 1 (µV) | Canal 2 (µV) |
| --- | --- | --- |
| Sin apantallar | 3,1 | 29,2 |
| Apantallado | 3,1 | 13,4 |
| + radio a 5 dBm | 3,2 | 7,0 |
| + 4 notch | 2,9 | 2,6 |



### Antes: la señal original

En las primeras grabaciones la señal estaba dominada por los 50 Hz ensuciando mucho la señal. 

Hacer funcionar el RLD del ADS la redujo drásticamente pero esas grabaciones también mostraban muestras sueltas imposibles (`0, 0` o `1, 4086`), en principio por fallos de lectura SPI, que ahora corrige el limpiador de picos.

### Problema 1: un canal con mucho más ruido que el otro

**Síntoma:** En reposo, el canal 1 tenía 3 µV y el canal 2, 29 µV.

**Diagnóstico:** El espectro del canal 2 mostraba picos en 50, 100, 150 y 200 Hz y más ruido de fondo. Eso indica que su cable captaba interferencias.

**Solución:** Apantallar (entrelazar) los cables del canal 2 que despues de soldarlos debido a que la soldadura anterior se partió. El ruido bajó a 13 µV.

### Problema 2: muestras perdidas cada 2 segundos

**Síntoma:** El contador de muestras perdidas subía 1 o 2 cada 2,00 s exactos, hubiera contracción o no.

**Diagnóstico:** Un periodo tan exacto no puede ser carga de trabajo, que varía; tiene que ser algo programado. El núcleo de Arduino pausa `loop()` unos 5 ms cada 2 s para atender al sistema. Como entonces la lectura del ADS estaba en `loop()` y el ADS sobrescribe sus muestras cada 2 ms, en cada pausa se perdían 1 o 2.

Este problema existía de antes, pero no se veía. Lo destapó el contador de "muestras perdidas" añadido para el diagnóstico.

**Solución:** Mover la lectura a una tarea de FreeRTOS con más prioridad que `loop()`, que despierta la interrupción, bajando a 0 las muestras perdidas.

### Problema 3: la radio del emisor se colaba en la medida

**Síntoma:** En una de las grabaciones el ruido del canal 2 subió a 58 µV, casi todo en 100 Hz. 

**Diagnóstico:** Ampliando el espectrograma en la duración equivalente a un paquete se veía que las subidas de 100Hz dibujaban la misma gráfica. De ser la red o los electrodos los 100Hz estarían cerca del 0.

El emisor envía un paquete cada 5 muestras, es decir, 100 veces por segundo. Cada envío provoca un pico de consumo y de radiofrecuencia que deja una huella en la medida. Esa huella se repite al ritmo de los paquetes: 100 Hz (y 200 Hz). Esto explica también por qué apantallar los cables había ayudado.

**Solución:** bajar la potencia de emisión de unos 20 dBm a 5 dBm. La huella de 100 Hz pasó de 72,7 a 6,0 µV y el canal 2 bajó a 7 µV, sin perder ningún paquete. La solución de raíz es de hardware: alejar la antena y desacoplar mejor la alimentación del ADS.

### Problema 4: los armónicos de la red que quedaban

**Síntoma:** quedaban 7 µV en el canal 2, sobre todo en 150 Hz (tercer armónico de la red) y un resto de 50 Hz que el notch estrecho no quitaba del todo.

**Solución:** ampliar la librería para admitir hasta 4 notch, añadir los de 100, 150 y 200 Hz y ensanchar el de 50 Hz (Q de 35 a 20). Antes de cargarlo, se simuló sobre la grabación de las 19:35 compilando la librería en un PC: predecía 2,9 µV. La grabación real dio 2,6 µV. Lo que queda ya es ruido de fondo sin ningún pico: el límite propio de electrodos, piel y ADS, que no se puede eliminar filtrando.

### Modo de estudio que se hizo en este proceso

Casi todos los problemas se resolvieron con el mismo procedimiento:

1. Medir con una grabación controlada: reposo, contracciones y reposo, sin tocar nada.
2. Mirar el **espectro**.
3. Buscar **regularidades**.
4. Cambiar **una sola cosa** y repetir la grabación.

Los contadores de diagnóstico que viajan en cada paquete fueron clave: sin ellos, las muestras perdidas habrían seguido sin verse.

## Puesta en marcha y comprobaciones

### Orden para cargar los programas

El orden importa:

1. **Receptor primero:** Acepta paquetes antiguos y nuevos, así que se puede cargar sin romper nada. Con el emisor antiguo encendido, el LED debe seguir azul.
2. **Recomendable:** Visor nuevo en el PC para ver las graficas con los parametros de diagnostico durante el funcionamiento.
3. **Emisor** al final.


### Antes de compilar el emisor

- [ ] `GANANCIA_NUM` y `adsGanancia` dicen la misma ganancia (las dos 12, 8…). Si no coinciden, todos los microvoltios salen mal escalados.
- [ ] `FS_HZ` coincide con `adsSPS` (500).
- [ ] La tarea se crea con `xTaskCreate` **antes** de `attachInterrupt`.
- [ ] El `#include` de la librería coincide con el nombre de su carpeta y archivos.


### Si algo falla

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| LED del receptor en rojo, sin señal | El emisor no envía, o la MAC del receptor (`rxMac`) no es la buena | Comprobar alimentación del emisor y que `rxMac` coincide con la MAC que muestra el visor |
| «Inválidos (C6)» sube y no hay señal | Emisor y receptor con distinto formato de paquete | Cargar la misma versión en los dos |
| «Marcos corruptos» en el visor | Visor antiguo, o cable USB defectuoso | Usar el visor nuevo y otro cable |
| LED amarillo o «Saturaciones» sube | La señal supera el rango del ADS | Bajar la ganancia a 8 en las dos líneas |
| «Paquetes perdidos» sube | Algo tapa la radio, o el receptor está lejos | Alejar metal y manos de la antena; si hace falta, subir la potencia (34 = 8,5 dBm) |
| «Muestras perdidas (sensor)» sube | El emisor no lee el ADS a tiempo | Comprobar que la lectura está en la tarea de adquisición y no en `loop()` |
| Ruido de reposo alto en un canal | Mal contacto de un electrodo, o cable que capta interferencias | Limpiar la piel, revisar los dos electrodos del par, apantallar el cable |
| Ruido con pico en 100 Hz de fase fija | La radio del emisor se cuela en la medida | Bajar potencia de radio, alejar la antena del ADS y de los cables |