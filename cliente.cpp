#include <WiFi.h>
#include <HTTPClient.h>
#include <Update.h>

const char* ssid = "Red_ESP32_C6";
const char* password = "FIRMWARE_OTA_PASS";

// IP por defecto del Punto de Acceso del C6 y la ruta asignada
const String ota_url = "http://192.168.4"; 

void ejecutarOTA() {
  WiFiClient client;
  HTTPClient http;

  Serial.println("Conectando al servidor C6 para verificar actualizaciones...");
  http.begin(client, ota_url);
  
  int httpCode = http.GET();
  if (httpCode == HTTP_CODE_OK) {
    int contentLength = http.getSize();
    bool canBegin = Update.begin(contentLength);

    if (canBegin) {
      Serial.println("Descargando e instalando nuevo firmware...");
      size_t written = Update.writeStream(http.getStream());

      if (written == contentLength) {
        Serial.println("Escritura completada con éxito.");
      } else {
        Serial.printf("Error: Solo se escribieron %d de %d bytes\n", written, contentLength);
      }

      if (Update.end()) {
        Serial.println("¡OTA exitosa! Reiniciando dispositivo...");
        if (Update.isFinished()) {
          ESP.restart();
        }
      } else {
        Serial.printf("Error en Update.end(): %s\n", Update.errorString());
      }
    } else {
      Serial.println("No hay suficiente espacio en memoria para realizar la OTA.");
    }
  } else {
    Serial.printf("Error al conectar con el servidor HTTP. Código: %d\n", httpCode);
  }
  http.end();
}

void setup(){
    
  Serial.begin(115200);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConectado a la red del C6.");

  // Ejecuta la rutina de actualización (puedes condicionarlo a un botón)
  ejecutarOTA();
}

void loop() {
  // Código de tu aplicación habitual para el WROOM
}
