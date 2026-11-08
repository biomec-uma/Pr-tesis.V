// =====================================================================
//  BIOMEC UMA · ESP32-C6 PUENTE (conectada al PC por USB)
//
//  - Lo que llega por USB se reenvía a la mano por ESP-NOW.
//  - Lo que llega de la mano por ESP-NOW se imprime por USB.
//  - Las líneas que empiezan por '@' son comandos del propio puente.
//  - Los paquetes binarios de la placa EMG (ADS1198) se reenvían como
//    líneas "EMG ..." si la app lo pide con @EMG 1 (ver sección EMG).
//
//  Arduino IDE: placa "ESP32C6 Dev Module", core esp32 >= 3.0
//  Herramientas -> "USB CDC On Boot: Enabled" (para usar el USB nativo).
// =====================================================================
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "biomec_protocol.h"

// ---------------------------------------------------------------------
// MAC del ESP32 de la MANO. Con FF:FF:... (broadcast) funciona sin
// configurar nada; cuando la sepas (la imprime la mano al arrancar)
// ponla aquí para que solo se hablen entre ellas.
// ---------------------------------------------------------------------
uint8_t HAND_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static QueueHandle_t rxQueue;
static String usbLine;

// ---------------------------------------------------------------------
// EMG: paquetes de la placa del ADS1198 (firmware/EMG/src/main.cpp):
//     struct __attribute__((packed)) { uint16_t seq; int16_t data[BATCH][N_CHNLS]; }
// Para que lleguen aquí, en ese firmware pon en rxMac la MAC de ESTE
// puente (la muestra @INFO). Con @EMG 1 se reenvían a la app como
//     EMG <seq> <canales> s1c1 s1c2 ... s2c1 s2c2 ...
// y la pestaña "Entrenamiento" los usa para entrenar el clasificador.
// ---------------------------------------------------------------------
#define EMG_CANALES 2   // = N_CHNLS del firmware EMG
uint8_t EMG_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};  // FF... = de cualquier placa

bool emgReenviar = false;       // lo activa la app con @EMG 1
uint32_t emgPaquetes = 0, emgPerdidos = 0;
int32_t emgUltimoSeq = -1;

// ======================= Comandos del PUENTE (@...) ==================
// Para añadir uno: escribe la función y añade UNA línea a BRIDGE_COMMANDS.
// (y su entrada en config/commands.json con "target": "puente")

void cmdPing(const BiomecArgs&) {
  Serial.println("BRIDGE PONG");
}

void cmdInfo(const BiomecArgs&) {
  Serial.printf("BRIDGE MAC puente=%s mano=%s canal=%d emg=%d paquetes=%lu perdidos=%lu\n",
                WiFi.macAddress().c_str(), biomecMacToString(HAND_MAC).c_str(),
                BIOMEC_ESPNOW_CHANNEL, emgReenviar ? 1 : 0,
                (unsigned long)emgPaquetes, (unsigned long)emgPerdidos);
}

// @EMG 1 / @EMG 0: reenviar (o no) a la app las muestras de la placa EMG
void cmdEmg(const BiomecArgs& a) {
  if (a.count > 0) emgReenviar = a.toInt(0) != 0;
  Serial.printf("BRIDGE EMG %d canales=%d paquetes=%lu perdidos=%lu\n", emgReenviar ? 1 : 0,
                EMG_CANALES, (unsigned long)emgPaquetes, (unsigned long)emgPerdidos);
}

struct BridgeCommand {
  const char* name;
  void (*handler)(const BiomecArgs&);
};

const BridgeCommand BRIDGE_COMMANDS[] = {
  {"PING", cmdPing},
  {"INFO", cmdInfo},
  {"EMG",  cmdEmg},
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

// ======================= EMG =========================================
// true si el paquete es una línea de texto UTF-8 sin caracteres de control,
// como todas las respuestas de la mano. Los paquetes EMG son binarios.
bool esTexto(const uint8_t* s, int n) {
  for (int i = 0; i < n; i++) {
    uint8_t c = s[i];
    if (c < 0x80) {
      if (c < 0x20 && c != '\t') return false;
      continue;
    }
    int extra = (c >= 0xC2 && c <= 0xDF) ? 1 : (c >= 0xE0 && c <= 0xEF) ? 2 : (c >= 0xF0 && c <= 0xF4) ? 3 : -1;
    if (extra < 0 || i + extra >= n) return false;
    for (int k = 1; k <= extra; k++) if ((s[i + k] & 0xC0) != 0x80) return false;
    i += extra;
  }
  return true;
}

bool esPaqueteEmg(const BiomecPacket& p) {
  if (!isBroadcast(EMG_MAC) && memcmp(p.mac, EMG_MAC, 6) != 0) return false;
  if (p.len < 2 + 2 * EMG_CANALES || (p.len - 2) % (2 * EMG_CANALES) != 0) return false;
  return !esTexto((const uint8_t*)p.text, p.len);
}

void reenviarEmg(const BiomecPacket& p) {
  const uint8_t* b = (const uint8_t*)p.text;
  uint16_t seq = b[0] | (b[1] << 8);  // little-endian, como lo escribe la ESP32
  if (emgUltimoSeq >= 0) {
    uint16_t hueco = (uint16_t)(seq - (uint16_t)emgUltimoSeq - 1);
    if (hueco < 1000) emgPerdidos += hueco;  // si es enorme, la placa EMG se reinició
  }
  emgUltimoSeq = seq;
  emgPaquetes++;
  if (!emgReenviar) return;

  static char out[24 + 7 * (BIOMEC_MAX_MSG / 2)];
  int n = snprintf(out, sizeof(out), "EMG %u %d", seq, EMG_CANALES);
  for (int i = 2; i + 1 < p.len && n < (int)sizeof(out) - 8; i += 2) {
    int16_t v = (int16_t)(b[i] | (b[i + 1] << 8));  // byte a byte: el puntero puede no estar alineado
    n += snprintf(out + n, sizeof(out) - n, " %d", v);
  }
  Serial.write((const uint8_t*)out, n);
  Serial.write('\n');
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

  // 2) mano / placa EMG -> USB
  BiomecPacket p;
  while (xQueueReceive(rxQueue, &p, 0) == pdTRUE) {
    if (esPaqueteEmg(p)) { reenviarEmg(p); continue; }
    if (!isBroadcast(HAND_MAC) && memcmp(p.mac, HAND_MAC, 6) != 0) continue;  // otro dispositivo
    Serial.println(p.text);
  }
}
