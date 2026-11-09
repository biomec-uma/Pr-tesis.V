# Guía de Actualización Inalámbrica (OTA) en ESP32 mediante Punto de Acceso (SoftAP)

Esta guía explica cómo configurar y actualizar el firmware de un microcontrolador ESP32 de forma inalámbrica (*Over-The-Air* u OTA) utilizando la propia placa como punto de acceso Wi-Fi (*SoftAP*). Esto permite subir código directamente desde un portátil sin depender de una red Wi-Fi externa.

---

## 1. Requisitos Previos

* **Entorno de desarrollo:** Tener instalado Visual Studio Code con la extensión **PlatformIO IDE** y un proyecto de PlatformIO ya creado y configurado para tu modelo de placa ESP32.
* **Cable USB de datos:** Necesario únicamente para la primera carga del código base.

---

## 2. Configuración de `platformio.ini`

Para alternar fácilmente entre la carga inicial por cable USB y las futuras actualizaciones inalámbricas, añade o adapta los siguientes dos entornos en el archivo `platformio.ini` en la raíz del proyecto:

```ini
[env]
platform = espressif32
board = fm-devkit # Ajustar dependiendo de qué modelo de placa usamos
framework = arduino

; Entorno 1: Para la primera carga mediante cable USB
[env:usb]
upload_protocol = esptool

; Entorno 2: Para actualizaciones inalámbricas (OTA)
[env:ota]
upload_protocol = espota
upload_port = 192.168.4.1 # La IP default del esp en la red
```

---

## 3. Código Base (`src/main.cpp`)

El siguiente código encapsula la lógica OTA en dos funciones auxiliares (`setupOTA()` y `loopOTA()`) para mantener limpio el programa principal, acompañado de un parpadeo del LED integrado en el pin 2 para verificar visualmente el funcionamiento.

```cpp
#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoOTA.h>

#define LED 2

const char* ap_ssid = "biomec";
const char* ap_password = "12345678"; // IMPORTANTE: Mínimo 8 caracteres

void setupOTA();
void loopOTA();

void setup() {
  setupOTA();

  pinMode(LED, OUTPUT);
}

void loop() {
  loopOTA();

  digitalWrite(LED, HIGH);
  delay(100);
  digitalWrite(LED, LOW);
  delay(100);
}

void setupOTA() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP(ap_ssid, ap_password);

  ArduinoOTA.setHostname("esp32-ota");
  ArduinoOTA.begin();
}

void loopOTA() {
  ArduinoOTA.handle();
}
```

### Cómo funciona el código

* **`setupOTA()`:** Configura la antena Wi-Fi del ESP32 en modo Punto de Acceso (`WIFI_AP`), levanta la red con el nombre `biomec` y contraseña `12345678`, e inicia el servidor de escucha `ArduinoOTA` bajo la dirección IP por defecto **`192.168.4.1`**.
* **`loopOTA()`:** Ejecuta `ArduinoOTA.handle()`, que comprueba en cada iteración de `loop()` si PlatformIO está intentando enviar un nuevo firmware por Wi-Fi.

---

## 4. Procedimiento Paso a Paso

1. **Primera carga por USB (obligatoria una sola vez):**
   * Conecta el ESP32 al ordenador mediante el cable USB.
   * Selecciona el entorno **`env:usb`** en la barra inferior de PlatformIO  y sube el código.
2. **Conexión a la red Wi-Fi del ESP32:**
   * Una vez cargado el firmware (puedes desconectar el USB y alimentar la placa con una fuente externa), abre la configuración de Wi-Fi de tu portátil.
   * Conéctate a la red **`biomec`** con la contraseña **`12345678`**.
   * *Nota:* El sistema operativo indicará que la red "No tiene acceso a Internet". Es normal; mantén la conexión activa.
3. **Subida de nuevas actualizaciones por OTA:**
   * Realiza las modificaciones que necesites en `src/main.cpp` (por ejemplo, cambiar `delay(100)` a `delay(500)` para alterar la velocidad del LED).
   * Cambia el entorno activo en PlatformIO a **`env:ota`**.
   * PlatformIO se conectará automáticamente a `192.168.4.1` y actualizará la placa sin usar cables.

---

## 5. Reglas Críticas para Futuras Modificaciones

> [!WARNING]
> Para no perder la capacidad de actualizar la placa por Wi-Fi en siguientes versiones del código, todo el equipo debe respetar estas tres reglas al programar:

* **Longitud de la contraseña Wi-Fi:** La variable `ap_password` debe tener **estrictamente entre 8 y 63 caracteres**. Si se introduce una contraseña de menos de 8 caracteres, el estándar WPA2 falla de forma silenciosa y el ESP32 no creará la red `biomec`.
* **Mantener siempre `setupOTA()` y `loopOTA()`:** Si alguien sube un firmware nuevo por OTA habiendo borrado la llamada a `setupOTA()` o `loopOTA()`, la actualización se completará, pero el ESP32 dejará de emitir Wi-Fi tras reiniciarse y habrá que volver a conectarlo por cable USB para recuperarlo.
* **Evitar bloqueos largos en `loop()`:** La función `loopOTA()` necesita ejecutarse con frecuencia para responder a PlatformIO. Los `delay(100)` actuales permiten que responda sin problema, pero si se añaden pausas largas (como `delay(5000)` o bucles `while` lentos), la conexión OTA dará error de *timeout*. Para tareas periódicas lentas, es recomendable usar temporizadores no bloqueantes con `millis()`.