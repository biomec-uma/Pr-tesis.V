// =====================================================================
//  BIOMEC UMA · ESP32-C6 PUENTE (conectada al PC por USB)
//
//  - Lo que llega por USB se reenvía a la mano por ESP-NOW.
//  - Lo que llega de la mano por ESP-NOW se imprime por USB.
//  - Las líneas que empiezan por '@' son comandos del propio puente.
//
//  Arduino IDE: placa "ESP32C6 Dev Module", core esp32 >= 3.0
//  Herramientas -> "USB CDC On Boot: Enabled" (para usar el USB nativo).
// =====================================================================
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "biomec_protocol.h"

// ---------------------------------------------------------------------
// MAC de la C6 de la MANO. Con FF:FF:... (broadcast) funciona sin
// configurar nada; cuando la sepas (la imprime la mano al arrancar)
// ponla aquí para que solo se hablen entre ellas.
// ---------------------------------------------------------------------
uint8_t HAND_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static QueueHandle_t rxQueue;
static String usbLine;

// ======================= Comandos del PUENTE (@...) ==================
// Para añadir uno: escribe la función y añade UNA línea a BRIDGE_COMMANDS.
// (y su entrada en config/commands.json con "target": "puente")

void cmdPing(const BiomecArgs&) {
  Serial.println("BRIDGE PONG");
}

void cmdInfo(const BiomecArgs&) {
  Serial.printf("BRIDGE MAC puente=%s mano=%s canal=%d\n",
                WiFi.macAddress().c_str(), biomecMacToString(HAND_MAC).c_str(),
                BIOMEC_ESPNOW_CHANNEL);
}

struct BridgeCommand {
  const char* name;
  void (*handler)(const BiomecArgs&);
};

const BridgeCommand BRIDGE_COMMANDS[] = {
  {"PING", cmdPing},
  {"INFO", cmdInfo},
};

// =====================================================================

void onEspNowRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  // Se ejecuta en la tarea WiFi: solo copiar y salir.
  BiomecPacket p;
  memcpy(p.mac, info->src_addr, 6);
  p.len = min(len, BIOMEC_MAX_MSG);
  memcpy(p.text, data, p.len);
  p.text[p.len] = '\0';
  xQueueSend(rxQueue, &p, 0);
}

bool isBroadcast(const uint8_t* mac) {
  for (int i = 0; i < 6; i++) if (mac[i] != 0xFF) return false;
  return true;
}

void handleBridgeCommand(const String& line) {
  BiomecArgs args = BiomecArgs::parse(line.substring(1));  // sin la '@'
  for (const auto& c : BRIDGE_COMMANDS) {
    if (args.name == c.name) {
      c.handler(args);
      return;
    }
  }
  Serial.printf("ERR Comando de puente desconocido: %s\n", args.name.c_str());
}

void forwardToHand(const String& line) {
  if (line.length() > BIOMEC_MAX_MSG) {
    Serial.println("ERR Comando demasiado largo para ESP-NOW");
    return;
  }
  esp_err_t r = esp_now_send(HAND_MAC, (const uint8_t*)line.c_str(), line.length());
  if (r != ESP_OK) {
    Serial.printf("ERR ESP-NOW no pudo enviar (%s)\n", esp_err_to_name(r));
  }
}

void handleUsbLine(String line) {
  line.trim();
  if (line.length() == 0) return;
  if (line[0] == '@') handleBridgeCommand(line);
  else forwardToHand(line);
}

void setup() {
  Serial.begin(BIOMEC_SERIAL_BAUD);
  rxQueue = xQueueCreate(BIOMEC_QUEUE_LEN, sizeof(BiomecPacket));

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(BIOMEC_ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ERR No se pudo iniciar ESP-NOW");
    return;
  }
  esp_now_register_recv_cb(onEspNowRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, HAND_MAC, 6);
  peer.channel = BIOMEC_ESPNOW_CHANNEL;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("ERR No se pudo registrar la mano como peer");
  }

  Serial.printf("BRIDGE Puente listo. MAC=%s\n", WiFi.macAddress().c_str());
}

void loop() {
  // 1) USB -> mano
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handleUsbLine(usbLine); usbLine = ""; }
    else if (c != '\r' && usbLine.length() < 512) usbLine += c;
  }

  // 2) mano -> USB
  BiomecPacket p;
  while (xQueueReceive(rxQueue, &p, 0) == pdTRUE) {
    if (!isBroadcast(HAND_MAC) && memcmp(p.mac, HAND_MAC, 6) != 0) continue;  // otro dispositivo
    Serial.println(p.text);
  }
}
