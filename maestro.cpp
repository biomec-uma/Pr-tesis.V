#include <WiFi.h>
#include <WebServer.h>
#include <LittleFS.h>

const char* ssid = "Red_ESP32_C6";
const char* password = "FIRMWARE_OTA_PASS";

WebServer server(80);

void handleOTA() {
  if (LittleFS.exists("/wroom_fw.bin")) {
    File file = LittleFS.open("/wroom_fw.bin", "r");
    // Envía el archivo binario con el tipo de contenido correcto para OTA
    server.streamFile(file, "application/octet-stream");
    file.close();
    Serial.println("Firmware enviado con éxito al WROOM.");
  } else {
    server.send(404, "text/plain", "Archivo firmware binario no encontrado.");
  }
}

void setup() {
  Serial.begin(115200);
  
  if(!LittleFS.begin(true)){
    Serial.println("Error al montar LittleFS");
    return;
  }

  // Configura el ESP32-C6 como Punto de Acceso Wi-Fi
  WiFi.softAP(ssid, password);
  Serial.print("Servidor listo. IP del C6: ");
  Serial.println(WiFi.softAPIP());

  // Ruta a la que llamará el WROOM para descargar su código
  server.on("/update", HTTP_GET, handleOTA);
  server.begin();
}

void loop() {
  server.handleClient();
  delay(2);
}
