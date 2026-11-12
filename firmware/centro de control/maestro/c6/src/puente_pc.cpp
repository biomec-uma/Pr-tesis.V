// =====================================================================
//  BIOMEC UMA · ESP32-C6 PUENTE (conectada al PC por USB)
//
//  Funciona CON y SIN la placa EMG (ESP32-C3 + ADS1198):
//  - Lo que llega por USB se reenvía a la mano por ESP-NOW.
//  - Lo que llega de la mano por ESP-NOW se imprime por USB.
//  - Las líneas que empiezan por '@' son comandos del propio puente.
//  - Si la placa EMG está encendida y envía a ESTA C6, su señal llega al
//    PC (ver sección EMG). Sin placa EMG, el puente solo mueve la mano y
//    por el USB solo salen líneas de texto.
//
//  Así una sola C6 hace de puente de la mano y de receptor EMG: sirve la
//  DevKitC del puente o la Waveshare C6-Zero del receptor del equipo
//  (las dos tienen el LED RGB en el GPIO 8).
//
//  PlatformIO: abre en VS Code la carpeta de este firmware (la que tiene
//  el platformio.ini). Entorno "devkitc" = DevKitC del puente, "c6zero" =
//  C6-Zero del receptor del equipo. Ya trae "USB CDC On Boot" activado,
//  necesario para el USB nativo.
// =====================================================================
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <stdarg.h>
#include "biomec_protocol.h"

// ---------------------------------------------------------------------
// MAC del ESP32 de la MANO. Con FF:FF:... (broadcast) funciona sin
// configurar nada; cuando la sepas (la imprime la mano al arrancar)
// ponla aquí para que solo se hablen entre ellas.
// ---------------------------------------------------------------------
uint8_t HAND_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// ---------------------------------------------------------------------
// EMG. La placa del ADS1198 manda sus paquetes por ESP-NOW a la MAC que
// tenga en rxMac (firmware/EMG/src/main.cpp): tiene que ser la de ESTA
// C6 (la muestra @INFO). Se entienden los dos formatos del equipo:
//
//  · Nuevo (rama Imprimir-seq):
//        version=1, nChnls, batch, seq u32, sendFails u16, int16 data[batch][nChnls]
//    Se reenvía al PC tal cual, en el mismo marco binario que el receptor
//    del equipo (firmware/maestro de esa rama):
//        AA 55 | tipo | longitud | contenido | XOR(tipo ^ longitud ^ contenido)
//        tipo 0x01 = paquete del sensor
//        tipo 0x02 = estado de esta C6 (1 por segundo mientras llega EMG)
//    Lo entienden la app (en la conexión principal o en el Visor EMG) y el
//    visor_emg.py del equipo.
//
//  · Antiguo (main): uint16 seq + int16 data[..][EMG_CANALES]. Se reenvía
//    como línea de texto "EMG <seq> <canales> s1c1 s1c2 s2c1 s2c2 ...".
//
//  @EMG 0 deja de mandar el EMG al PC (consola de texto limpia) y @EMG 1
//  lo vuelve a activar. Arranca activado.
// ---------------------------------------------------------------------
#define EMG_CANALES 2   // canales del formato antiguo (= N_CHNLS de esa placa)
uint8_t EMG_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};  // FF... = de cualquier placa

#define SYNC1           0xAA
#define SYNC2           0x55
#define MARCO_DATOS     0x01
#define MARCO_ESTADO    0x02
#define CABECERA_SENSOR 9      // version + nChnls + batch + seq(4) + sendFails(2)
#define VERSION_SENSOR  1
#define RADIO_MAX       250    // tamaño máximo de un paquete ESP-NOW
#define RADIO_COLA      24
#define EMG_ACTIVO_MS   3000   // sin paquetes durante este tiempo = no hay placa EMG

// Paquete recibido por ESP-NOW, copiado desde el callback a una cola para
// procesarlo con calma en loop() (nunca dentro del callback).
struct PaqueteRadio {
  uint8_t mac[6];
  uint8_t len;
  uint8_t datos[RADIO_MAX + 1];   // +1: sitio para el '\n' de las líneas de texto
};

// Contenido del marco de estado (mismo orden que el receptor del equipo)
struct __attribute__((packed)) EstadoEmg {
  uint8_t  mac[6];           // MAC de esta C6 (la que va en rxMac del sensor)
  uint32_t recibidos;        // paquetes EMG válidos
  uint32_t invalidos;        // paquetes binarios que no son de ningún formato conocido
  uint32_t perdidosCola;     // llegaron con la cola llena
  uint32_t descartadosUSB;   // no cabían en el USB (el PC no estaba leyendo)
};

static QueueHandle_t rxQueue;
static String usbLine;
uint8_t miMac[6];

bool emgReenviar = true;                 // @EMG 1 / @EMG 0
uint32_t emgPaquetes = 0, emgPerdidos = 0, emgInvalidos = 0, descartadosUSB = 0;
volatile uint32_t perdidosCola = 0;      // lo escribe el callback de ESP-NOW
uint32_t emgUltimoSeq = 0;
bool emgHaySeq = false;
uint32_t emgUltimoMs = 0;
uint8_t emgFormato = 0;                  // 0 ninguno todavía, 1 nuevo, 2 antiguo
uint8_t emgCanales = 0, emgLote = 0;

// ======================= Salida por USB ==============================
// Todo se escribe desde loop() y entero o nada: si el PC no está leyendo,
// mejor descartar que bloquear la radio o partir un marco por la mitad.
bool usbEnviar(const uint8_t* buf, size_t n) {
  if (Serial.availableForWrite() < (int)n) { descartadosUSB++; return false; }
  Serial.write(buf, n);
  return true;
}

// Una línea de texto al PC, con formato tipo printf: say("BRIDGE %s", x)
void say(const char* fmt, ...) {
  char buf[320];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  if (n > (int)sizeof(buf) - 2) n = sizeof(buf) - 2;
  buf[n++] = '\n';
  usbEnviar((const uint8_t*)buf, n);
}

void enviarMarco(uint8_t tipo, const uint8_t* contenido, uint8_t n) {
  uint8_t marco[5 + RADIO_MAX];
  marco[0] = SYNC1;
  marco[1] = SYNC2;
  marco[2] = tipo;
  marco[3] = n;
  memcpy(&marco[4], contenido, n);
  uint8_t x = tipo ^ n;
  for (int i = 0; i < n; i++) x ^= contenido[i];
  marco[4 + n] = x;
  usbEnviar(marco, 5 + n);
}

bool emgActivo() {
  return emgPaquetes > 0 && millis() - emgUltimoMs < EMG_ACTIVO_MS;
}

void enviarEstado() {
  EstadoEmg e;
  memcpy(e.mac, miMac, 6);
  e.recibidos = emgPaquetes;
  e.invalidos = emgInvalidos;
  e.perdidosCola = perdidosCola;
  e.descartadosUSB = descartadosUSB;
  enviarMarco(MARCO_ESTADO, (const uint8_t*)&e, sizeof(e));
}

// LED: azul mientras llega EMG, blanco tenue si no (solo mano).
// Azul y blanco se ven igual aunque el LED sea RGB o GRB.
void actualizarLed() {
#ifdef RGB_BUILTIN
  static int8_t pintado = -1;
  int8_t ahora = (emgPaquetes > 0 && millis() - emgUltimoMs < 500) ? 1 : 0;
  if (ahora == pintado) return;
  pintado = ahora;
  if (ahora) rgbLedWrite(RGB_BUILTIN, 0, 0, 40);
  else       rgbLedWrite(RGB_BUILTIN, 6, 6, 6);
#endif
}

// ======================= Comandos del PUENTE (@...) ==================
// Para añadir uno: escribe la función y añade UNA línea a BRIDGE_COMMANDS.
// (y su entrada en config/commands.json con "target": "puente")

const char* nombreFormato() {
  return emgFormato == 1 ? "nuevo" : emgFormato == 2 ? "antiguo" : "ninguno";
}

void cmdPing(const BiomecArgs&) {
  say("BRIDGE PONG");
}

void cmdInfo(const BiomecArgs&) {
  say("BRIDGE MAC puente=%s mano=%s canal=%d emg=%d sensor=%s formato=%s canales=%u lote=%u "
      "paquetes=%lu perdidos=%lu invalidos=%lu cola=%lu usb=%lu",
      WiFi.macAddress().c_str(), biomecMacToString(HAND_MAC).c_str(), BIOMEC_ESPNOW_CHANNEL,
      emgReenviar ? 1 : 0, emgActivo() ? "si" : "no", nombreFormato(), emgCanales, emgLote,
      (unsigned long)emgPaquetes, (unsigned long)emgPerdidos, (unsigned long)emgInvalidos,
      (unsigned long)perdidosCola, (unsigned long)descartadosUSB);
}

// @EMG 1 / @EMG 0: mandar (o no) a la app la señal de la placa EMG
void cmdEmg(const BiomecArgs& a) {
  if (a.count > 0) emgReenviar = a.toInt(0) != 0;
  say("BRIDGE EMG %d canales=%u sensor=%s formato=%s paquetes=%lu perdidos=%lu", emgReenviar ? 1 : 0,
      emgCanales ? emgCanales : EMG_CANALES, emgActivo() ? "si" : "no", nombreFormato(),
      (unsigned long)emgPaquetes, (unsigned long)emgPerdidos);
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
  PaqueteRadio p;
  memcpy(p.mac, info->src_addr, 6);
  p.len = (uint8_t)min(len, RADIO_MAX);
  memcpy(p.datos, data, p.len);
  if (xQueueSend(rxQueue, &p, 0) != pdTRUE) perdidosCola = perdidosCola + 1;  // (++ de volatile está obsoleto)
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

bool dePlacaEmg(const PaqueteRadio& p) {
  return isBroadcast(EMG_MAC) || memcmp(p.mac, EMG_MAC, 6) == 0;
}

// Formato nuevo: empieza por la versión (1) y la longitud cuadra con
// canales x muestras (siempre es impar: 9 + un número par).
bool esEmgNuevo(const PaqueteRadio& p) {
  if (p.len < CABECERA_SENSOR || p.datos[0] != VERSION_SENSOR) return false;
  uint8_t nch = p.datos[1], lote = p.datos[2];
  return nch >= 1 && lote >= 1 && p.len == CABECERA_SENSOR + nch * lote * 2;
}

// Formato antiguo: uint16 seq + muestras de EMG_CANALES canales (longitud par)
bool esEmgAntiguo(const PaqueteRadio& p) {
  if (p.len < 2 + 2 * EMG_CANALES || (p.len - 2) % (2 * EMG_CANALES) != 0) return false;
  return !esTexto(p.datos, p.len);
}

// Cuenta el paquete y los perdidos (saltos del número de paquete)
void contarEmg(uint32_t seq, uint8_t formato, uint8_t canales, uint8_t lote) {
  if (emgHaySeq && formato == emgFormato) {
    uint32_t hueco = seq - emgUltimoSeq - 1;
    if (formato == 2) hueco &= 0xFFFF;              // el formato antiguo cuenta con 16 bits
    if (hueco < 1000) emgPerdidos += hueco;         // si es enorme, la placa EMG se reinició
  }
  emgUltimoSeq = seq;
  emgHaySeq = true;
  emgFormato = formato;
  emgCanales = canales;
  emgLote = lote;
  emgPaquetes++;
  emgUltimoMs = millis();
}

void reenviarEmgNuevo(const PaqueteRadio& p) {
  const uint8_t* b = p.datos;
  uint32_t seq = b[3] | (b[4] << 8) | ((uint32_t)b[5] << 16) | ((uint32_t)b[6] << 24);
  contarEmg(seq, 1, b[1], b[2]);
  if (emgReenviar) enviarMarco(MARCO_DATOS, b, p.len);
}

void reenviarEmgAntiguo(const PaqueteRadio& p) {
  const uint8_t* b = p.datos;
  uint16_t seq = b[0] | (b[1] << 8);  // little-endian, como lo escribe la ESP32
  contarEmg(seq, 2, EMG_CANALES, (p.len - 2) / (2 * EMG_CANALES));
  if (!emgReenviar) return;

  static char out[24 + 7 * (RADIO_MAX / 2)];
  int n = snprintf(out, sizeof(out), "EMG %u %d", seq, EMG_CANALES);
  for (int i = 2; i + 1 < p.len && n < (int)sizeof(out) - 8; i += 2) {
    int16_t v = (int16_t)(b[i] | (b[i + 1] << 8));  // byte a byte: el puntero puede no estar alineado
    n += snprintf(out + n, sizeof(out) - n, " %d", v);
  }
  out[n++] = '\n';
  usbEnviar((const uint8_t*)out, n);
}

// ======================= Mano ========================================

void handleBridgeCommand(const String& line) {
  BiomecArgs args = BiomecArgs::parse(line.substring(1));  // sin la '@'
  for (const auto& c : BRIDGE_COMMANDS) {
    if (args.name == c.name) {
      c.handler(args);
      return;
    }
  }
  say("ERR Comando de puente desconocido: %s", args.name.c_str());
}

void forwardToHand(const String& line) {
  if (line.length() > BIOMEC_MAX_MSG) {
    say("ERR Comando demasiado largo para ESP-NOW");
    return;
  }
  esp_err_t r = esp_now_send(HAND_MAC, (const uint8_t*)line.c_str(), line.length());
  if (r != ESP_OK) {
    say("ERR ESP-NOW no pudo enviar (%s)", esp_err_to_name(r));
  }
}

void handleUsbLine(String line) {
  line.trim();
  if (line.length() == 0) return;
  if (line[0] == '@') handleBridgeCommand(line);
  else forwardToHand(line);
}

void setup() {
#if ARDUINO_USB_MODE && ARDUINO_USB_CDC_ON_BOOT
  Serial.setTxBufferSize(2048);   // antes de begin(): sitio para varios marcos EMG
#endif
  Serial.begin(BIOMEC_SERIAL_BAUD);
#if ARDUINO_USB_MODE && ARDUINO_USB_CDC_ON_BOOT
  Serial.setTxTimeoutMs(0);       // nunca bloquear al escribir: si el PC no lee, se descarta
#endif
  rxQueue = xQueueCreate(RADIO_COLA, sizeof(PaqueteRadio));

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  WiFi.setSleep(false);           // radio siempre despierta: se pierden menos paquetes
  esp_wifi_set_channel(BIOMEC_ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  WiFi.macAddress(miMac);
  actualizarLed();

  if (esp_now_init() != ESP_OK) {
    say("ERR No se pudo iniciar ESP-NOW");
    return;
  }
  esp_now_register_recv_cb(onEspNowRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, HAND_MAC, 6);
  peer.channel = BIOMEC_ESPNOW_CHANNEL;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    say("ERR No se pudo registrar la mano como peer");
  }

  say("BRIDGE Puente listo. MAC=%s (con o sin placa EMG)", WiFi.macAddress().c_str());
}

void loop() {
  // 1) USB -> mano
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handleUsbLine(usbLine); usbLine = ""; }
    else if (c != '\r' && usbLine.length() < 512) usbLine += c;
  }

  // 2) mano / placa EMG -> USB
  PaqueteRadio p;
  while (xQueueReceive(rxQueue, &p, 0) == pdTRUE) {
    if (dePlacaEmg(p) && esEmgNuevo(p))   { reenviarEmgNuevo(p);   continue; }
    if (dePlacaEmg(p) && esEmgAntiguo(p)) { reenviarEmgAntiguo(p); continue; }
    if (!esTexto(p.datos, p.len)) { emgInvalidos++; continue; }   // binario que no es de nadie conocido
    if (!isBroadcast(HAND_MAC) && memcmp(p.mac, HAND_MAC, 6) != 0) continue;  // otro dispositivo
    p.datos[p.len] = '\n';
    usbEnviar(p.datos, p.len + 1);
  }

  // 3) estado de la C6 (1/s) mientras llega EMG: MAC y contadores para el visor
  static uint32_t ultimoEstado = 0;
  if (emgReenviar && emgActivo() && millis() - ultimoEstado >= 1000) {
    ultimoEstado = millis();
    enviarEstado();
  }

  actualizarLed();
}
