// =====================================================================
//  BIOMEC UMA · ESP32-WROOM de la MANO
//
//  Basado en el código original de la mano (mismos pines, rampas y gestos)
//  y en firmware/bucle_exposiciones (core 3.x, comprobado en la mano real):
//    - PWM de los motores con ledcAttach(), igual que el bucle de exposiciones
//    - el timer hardware se sustituye por millis(), mismo periodo de 3 s
//    - control desde la app BIOMEC Control por ESP-NOW (vía la C6 puente)
//
//  Modos:
//    AUTO    -> la demo de siempre: recorre los 8 gestos (3 s moviendo,
//               3 s parando). Es el modo al encender (ARRANCAR_EN_AUTO).
//    MANUAL  -> la mano obedece comandos (GESTO, DEDO, PULGAR...).
//               Cualquier comando de movimiento pasa a MANUAL.
//
//  Para añadir un comando:  función cmdXxx + 1 línea en COMMANDS[]
//                           + su bloque en config/commands.json (app)
//  Para añadir un gesto:    1 línea en GESTOS[]
//  Para añadir una señal:   función + 1 línea en TELEMETRY[]
//
//  Arduino IDE: placa "ESP32 Dev Module". Librería ESP32Servo >= 3.0
// =====================================================================
#include <ESP32Servo.h>  // Para el servo
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_system.h>
#include <stdarg.h>
#include "biomec_protocol.h"

// MAC de la C6 PUENTE (la imprime al arrancar o con el comando INFO).
// Con broadcast funciona sin configurarla.
uint8_t BRIDGE_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

#define ARRANCAR_EN_AUTO true   // true = al encender hace la demo como antes

// ======================= Hardware (tu código original) ===============
// Control de rampa (arranque/parada suaves)
unsigned long tiempoInicioEstado = 0;      // millis() en el que empezó la fase actual
unsigned long tiempoEnEstado = 0;          // Tiempo transcurrido dentro de la fase actual
const unsigned long duracionRampa = 500;   // Duración de la rampa en ms (0,5s)
unsigned long tiempoFase = 3000;           // Antes: timer de 3 s. Ajustable con TIEMPO <ms>

// VALORES PWM (como en el bucle de exposiciones, comprobado en la mano real).
// En el core 3.x ledcAttach() asigna el canal automáticamente y
// ledcWrite()/ledcRead() trabajan directamente con el PIN.
// No fijar los canales 8-15: en la ESP32 son el grupo de baja velocidad
// y con ellos los motores no se movían.
const int freq = 15000;        // frecuencia
const int resolucion = 8;      // 8 bits -> 0-255

// --- MOTORES DC (Dedo Medio y Anular/Meñique) ---
const int medioA = 25, medioB = 26;
const int anularA = 18, anularB = 17;
const int indiceA = 32, indiceB = 33;

// SERVO
Servo pulgar_S;       // Pulgar (s)
const int pinS = 19;  // Pin para el pulgar
int anguloPulgar = 10;

// En el core 3.x ledcWrite/ledcRead usan el PIN, no el canal.
struct Motor {
  int pinA;
  int pinB;
};

Motor indice = { indiceA, indiceB };
Motor medio  = { medioA,  medioB  };
Motor anular = { anularA, anularB };

// ======================= Gestos ======================================
// Cada gesto define la posición ABSOLUTA de cada dedo. Al ir a un gesto
// solo se mueven los dedos que cambian, igual que hacía el switch
// original al recorrer la secuencia en orden, pero así se puede saltar
// a cualquier gesto desde la app.
enum Pos : uint8_t { ABIERTO, CERRADO, DESCONOCIDO };

struct Gesto {
  const char* nombre;
  Pos indice, medio, anular;
  int pulgar;  // ángulo del servo
};

// ---- TABLA DE GESTOS: añadir / quitar líneas aquí ----
const Gesto GESTOS[] = {
  // Nombres según la postura o el agarre. Deben coincidir con biomec/core/gestures.py (app).
  {"Mano abierta",     ABIERTO, ABIERTO, ABIERTO, 10},  // case 0
  {"Índice y medio",   ABIERTO, ABIERTO, CERRADO, 10},  // case 2  (cerrar anular)
  {"Índice y anular",  ABIERTO, CERRADO, ABIERTO, 10},  // case 4  (abrir anular, cerrar medio)
  {"Medio extendido",  CERRADO, ABIERTO, CERRADO, 10},  // case 6  (cerrar indice + anular, abrir medio)
  {"Índice extendido", ABIERTO, CERRADO, CERRADO, 10},  // case 8  (cerrar medio, abrir indice)
  {"Señalar",          ABIERTO, CERRADO, CERRADO, 90},  // case 10 (pulgar a 90)
  {"Mano plana",       ABIERTO, ABIERTO, ABIERTO, 90},  // case 12 (abrir medio y anular)
  {"Gancho",           CERRADO, CERRADO, CERRADO, 10},  // case 14 (cerrar todo, pulgar a 10)
};
const int N = sizeof(GESTOS) / sizeof(GESTOS[0]);  // Número de posiciones

// ======================= Estado de la mano ===========================
enum Fase : uint8_t { MOVIENDO, PARANDO };
enum Mov  : uint8_t { QUIETO, ABRIENDO, CERRANDO };

Motor* const DEDOS[3]        = { &indice, &medio, &anular };
const char* const NOMBRES[3] = { "INDICE", "MEDIO", "ANULAR" };
Pos  posDedo[3] = { DESCONOCIDO, DESCONOCIDO, DESCONOCIDO };  // dónde está cada dedo
Mov  movDedo[3] = { QUIETO, QUIETO, QUIETO };                 // qué hace en esta fase
Fase fase = PARANDO;
bool modoAuto = ARRANCAR_EN_AUTO;
int  gestoActual = -1;   // -1 = posición personalizada (DEDO / PULGAR sueltos)

bool streaming = false;
unsigned long periodoTelemetria = 50;

// ======================= Funciones de motores (tu código) ============
void cerrarDedo(Motor& motor) {
  // constrain: limita tiempoEnEstado a [0, duracionRampa]
  unsigned long t = constrain(tiempoEnEstado, 0UL, duracionRampa);
  // map: reescala el tiempo de la rampa a un duty de 0 a 255
  int duty = map(t, 0, duracionRampa, 0, 255);
  ledcWrite(motor.pinA, 0);
  ledcWrite(motor.pinB, duty);
}

void abrirDedo(Motor& motor) {
  unsigned long t = constrain(tiempoEnEstado, 0UL, duracionRampa);
  int duty = map(t, 0, duracionRampa, 0, 255);
  ledcWrite(motor.pinA, duty);
  ledcWrite(motor.pinB, 0);
}

void pararDedo(Motor& motor) {
  unsigned long t = constrain(tiempoEnEstado, 0UL, duracionRampa);
  int duty = map(t, 0, duracionRampa, 255, 0);  // Rampa de bajada
  // Si estaba en movimiento reduzco hasta 0; si ya estaba parado no hago nada.
  // min(): si se interrumpió un movimiento a media rampa (duty < 255), frena
  // desde la velocidad que llevaba en vez de dar un acelerón hasta 255.
  int a = ledcRead(motor.pinA), b = ledcRead(motor.pinB);
  if (a > 0) ledcWrite(motor.pinA, min(a, duty));
  if (b > 0) ledcWrite(motor.pinB, min(b, duty));
}

void ConfiguracionDeMotores() {
  pulgar_S.attach(pinS);
  // pulgar_S.setPeriodHertz(50);       // Frecuencia estándar para servos
  // pulgar_S.attach(pinS, 500, 2400);  // Anchos de pulso seguros (min, max)

  // ledcAttach(pin, frecuencia, resolución): configura el canal y lo asocia al pin
  // (después del servo, en el mismo orden que el bucle de exposiciones)
  ledcAttach(indiceA, freq, resolucion);
  ledcAttach(indiceB, freq, resolucion);
  ledcAttach(medioA,  freq, resolucion);
  ledcAttach(medioB,  freq, resolucion);
  ledcAttach(anularA, freq, resolucion);
  ledcAttach(anularB, freq, resolucion);
}

// Por qué arrancó la placa. Si los motores hacen caer la tensión, la mano se
// reinicia y la app lo muestra en la consola como reinicio=BAJADA_DE_TENSION.
const char* motivoReinicio() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "encendido";
    case ESP_RST_EXT:      return "boton";
    case ESP_RST_SW:       return "software";
    case ESP_RST_BROWNOUT: return "BAJADA_DE_TENSION";
    case ESP_RST_PANIC:    return "FALLO";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:      return "WATCHDOG";
    default:               return "otro";
  }
}

// ======================= Máquina de estados ==========================
void empezarFase(Fase f) {
  fase = f;
  tiempoInicioEstado = millis();
  tiempoEnEstado = 0;
}

// Si se interrumpe un movimiento a medias, ese dedo queda en posición
// desconocida (la próxima orden lo moverá seguro).
void cancelarMovimiento() {
  if (fase != MOVIENDO) return;
  for (int i = 0; i < 3; i++) {
    if (movDedo[i] != QUIETO) posDedo[i] = DESCONOCIDO;
    movDedo[i] = QUIETO;
  }
}

// Mueve solo los dedos cuya posición objetivo es distinta de la actual.
// DESCONOCIDO como objetivo = "no tocar ese dedo".
void moverA(Pos objetivo0, Pos objetivo1, Pos objetivo2) {
  cancelarMovimiento();
  Pos obj[3] = { objetivo0, objetivo1, objetivo2 };
  for (int i = 0; i < 3; i++) {
    if (obj[i] == DESCONOCIDO || obj[i] == posDedo[i]) movDedo[i] = QUIETO;
    else movDedo[i] = (obj[i] == ABIERTO) ? ABRIENDO : CERRANDO;
  }
  empezarFase(MOVIENDO);
}

void irAGesto(int g) {
  gestoActual = g;
  const Gesto& G = GESTOS[g];
  anguloPulgar = G.pulgar;
  pulgar_S.write(anguloPulgar);
  moverA(G.indice, G.medio, G.anular);
}

void actualizarMano() {
  tiempoEnEstado = millis() - tiempoInicioEstado;

  if (fase == MOVIENDO) {
    for (int i = 0; i < 3; i++) {
      if (movDedo[i] == ABRIENDO) abrirDedo(*DEDOS[i]);
      else if (movDedo[i] == CERRANDO) cerrarDedo(*DEDOS[i]);
      else pararDedo(*DEDOS[i]);  // si se interrumpió su movimiento, frena con rampa
    }
    if (tiempoEnEstado >= tiempoFase) {  // fin del movimiento -> parada
      for (int i = 0; i < 3; i++) {
        if (movDedo[i] == ABRIENDO) posDedo[i] = ABIERTO;
        if (movDedo[i] == CERRANDO) posDedo[i] = CERRADO;
        movDedo[i] = QUIETO;
      }
      empezarFase(PARANDO);
    }
  } else {  // PARANDO: STOP engine (el "default" del switch original)
    pararDedo(indice);
    pararDedo(medio);
    pararDedo(anular);
    if (modoAuto && tiempoEnEstado >= tiempoFase) {
      irAGesto((gestoActual + 1) % N);  // siguiente gesto de la demo
    }
  }
}

// ======================= Envío al PC =================================
static QueueHandle_t rxQueue;

// Uso tipo printf: reply("ACK GESTO %d", g);
void reply(const char* fmt, ...) {
  char buf[BIOMEC_MAX_MSG + 1];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  if (n < 0) return;
  n = min(n, BIOMEC_MAX_MSG);
  esp_now_send(BRIDGE_MAC, (const uint8_t*)buf, n);
  Serial.println(buf);  // eco local para depurar con la mano conectada al PC
}

// ======================= Comandos ====================================
// La app ya valida los argumentos, pero se vuelve a comprobar aquí:
// la seguridad de la mano no debe depender del PC.

int indiceDedo(const String& nombre) {
  for (int i = 0; i < 3; i++) if (nombre.equalsIgnoreCase(NOMBRES[i])) return i;
  return -1;
}

void cmdGesto(const BiomecArgs& a) {
  long g = a.toInt(0);
  if (g < 1 || g > N) { reply("ERR GESTO debe estar entre 1 y %d", N); return; }
  modoAuto = false;
  irAGesto(g - 1);
  reply("ACK GESTO %ld %s", g, GESTOS[g - 1].nombre);
}

void cmdAbrir(const BiomecArgs&) {
  modoAuto = false;
  irAGesto(0);
  reply("ACK ABRIR");
}

void cmdCerrar(const BiomecArgs&) {
  modoAuto = false;
  irAGesto(N - 1);
  reply("ACK CERRAR");
}

void cmdDedo(const BiomecArgs& a) {
  int d = indiceDedo(a.count > 0 ? a.v[0] : "");
  String acc = a.count > 1 ? a.v[1] : "";
  acc.toUpperCase();
  if (d < 0 || (acc != "ABRIR" && acc != "CERRAR")) {
    reply("ERR Uso: DEDO <INDICE|MEDIO|ANULAR> <ABRIR|CERRAR>");
    return;
  }
  modoAuto = false;
  gestoActual = -1;
  Pos obj[3] = { DESCONOCIDO, DESCONOCIDO, DESCONOCIDO };  // los demás no se tocan
  obj[d] = (acc == "ABRIR") ? ABIERTO : CERRADO;
  if (obj[d] == posDedo[d] && fase == PARANDO) {
    reply("ACK DEDO %s %s (ya estaba)", NOMBRES[d], acc.c_str());
    return;
  }
  // Si otros dedos se estaban moviendo, frenan con rampa y quedan como
  // "posición desconocida"; solo se mueve el dedo pedido.
  moverA(obj[0], obj[1], obj[2]);
  reply("ACK DEDO %s %s", NOMBRES[d], acc.c_str());
}

void cmdPulgar(const BiomecArgs& a) {
  long ang = a.toInt(0, -1);
  if (ang < 0 || ang > 180) { reply("ERR PULGAR debe estar entre 0 y 180"); return; }
  modoAuto = false;
  gestoActual = -1;
  anguloPulgar = ang;
  pulgar_S.write(anguloPulgar);
  reply("ACK PULGAR %ld", ang);
}

// "A" -> ABIERTO, "C" -> CERRADO, "-" -> DESCONOCIDO (= no mover ese dedo)
bool letraPos(String s, Pos& p) {
  s.toUpperCase();
  if (s == "A") { p = ABIERTO; return true; }
  if (s == "C") { p = CERRADO; return true; }
  if (s == "-") { p = DESCONOCIDO; return true; }
  return false;
}

char letra(Pos p) { return p == ABIERTO ? 'A' : p == CERRADO ? 'C' : '-'; }

// POSTURA <indice> <medio> <anular> <pulgar>   p. ej. POSTURA C A C 90
// Mueve todos los dedos A LA VEZ (con DEDO uno a uno, cada orden cancelaría
// el movimiento de la anterior). La usan las posturas personalizadas de la app.
void cmdPostura(const BiomecArgs& a) {
  Pos obj[3];
  long ang = a.toInt(3, -1);
  bool ok = a.count == 4 && a.v[3].length() > 0 && isDigit(a.v[3][0]) && ang >= 0 && ang <= 180;
  for (int i = 0; i < 3 && ok; i++) ok = letraPos(a.v[i], obj[i]);
  if (!ok) {
    reply("ERR Uso: POSTURA <A|C|-> <A|C|-> <A|C|-> <0-180>  (indice medio anular pulgar)");
    return;
  }
  modoAuto = false;
  gestoActual = -1;
  for (int g = 0; g < N; g++) {  // si coincide con un gesto de la tabla, se informa como ese gesto
    const Gesto& G = GESTOS[g];
    if (G.indice == obj[0] && G.medio == obj[1] && G.anular == obj[2] && G.pulgar == ang) gestoActual = g;
  }
  anguloPulgar = ang;
  pulgar_S.write(anguloPulgar);
  moverA(obj[0], obj[1], obj[2]);
  reply("ACK POSTURA %c %c %c %ld", letra(obj[0]), letra(obj[1]), letra(obj[2]), ang);
}

void cmdParar(const BiomecArgs&) {
  modoAuto = false;
  cancelarMovimiento();
  empezarFase(PARANDO);
  reply("ACK PARAR");
}

void cmdAuto(const BiomecArgs&) {
  modoAuto = true;
  if (fase == PARANDO) tiempoInicioEstado = millis() - tiempoFase;  // arranca ya
  reply("ACK AUTO");
}

void cmdManual(const BiomecArgs&) {
  modoAuto = false;
  reply("ACK MANUAL");
}

void cmdTiempo(const BiomecArgs& a) {
  long ms = a.toInt(0);
  if (ms < 500 || ms > 10000) { reply("ERR TIEMPO debe estar entre 500 y 10000 ms"); return; }
  tiempoFase = ms;
  reply("ACK TIEMPO %ld", ms);
}

void cmdStream(const BiomecArgs& a) {
  streaming = a.toInt(0) != 0;
  reply("ACK STREAM %d", streaming ? 1 : 0);
}

void cmdPeriodo(const BiomecArgs& a) {
  long ms = a.toInt(0);
  if (ms < 10 || ms > 5000) { reply("ERR PERIODO debe estar entre 10 y 5000 ms"); return; }
  periodoTelemetria = ms;
  reply("ACK PERIODO %ld", ms);
}

const char* textoPos(Pos p) { return p == ABIERTO ? "abierto" : p == CERRADO ? "cerrado" : "?"; }

void cmdEstado(const BiomecArgs&) {
  // gesto = número (1..N, 0 = posición personalizada): los nombres llevan espacios y romperían el formato clave=valor
  reply("ACK ESTADO modo=%s fase=%s gesto=%d indice=%s medio=%s anular=%s pulgar=%d tiempo=%lu",
        modoAuto ? "AUTO" : "MANUAL", fase == MOVIENDO ? "moviendo" : "parado",
        gestoActual + 1,
        textoPos(posDedo[0]), textoPos(posDedo[1]), textoPos(posDedo[2]),
        anguloPulgar, tiempoFase);
}

void cmdGestos(const BiomecArgs&) {
  for (int i = 0; i < N; i++) reply("GESTO %d = %s", i + 1, GESTOS[i].nombre);
}

struct HandCommand {
  const char* name;
  void (*handler)(const BiomecArgs&);
};

// ---- TABLA DE COMANDOS: añadir / quitar líneas aquí ----
const HandCommand COMMANDS[] = {
  {"GESTO",   cmdGesto},
  {"ABRIR",   cmdAbrir},
  {"CERRAR",  cmdCerrar},
  {"DEDO",    cmdDedo},
  {"PULGAR",  cmdPulgar},
  {"POSTURA", cmdPostura},
  {"PARAR",   cmdParar},
  {"AUTO",    cmdAuto},
  {"MANUAL",  cmdManual},
  {"TIEMPO",  cmdTiempo},
  {"STREAM",  cmdStream},
  {"PERIODO", cmdPeriodo},
  {"ESTADO",  cmdEstado},
  {"GESTOS",  cmdGestos},
};

// ======================= Telemetría ==================================
// PWM con signo: positivo = abriendo, negativo = cerrando (0-255).
float pwmDedo(const Motor& m) { return (float)ledcRead(m.pinA) - (float)ledcRead(m.pinB); }
float tIndice() { return pwmDedo(indice); }
float tMedio()  { return pwmDedo(medio); }
float tAnular() { return pwmDedo(anular); }
float tPulgar() { return anguloPulgar; }
float tGesto()  { return gestoActual + 1; }  // 0 = personalizado
float tFase()   { return fase == MOVIENDO ? 1 : 0; }  // 1 mientras los motores ejecutan un movimiento

struct TelemetrySignal {
  const char* key;  // nombre que verá la app (sin espacios ni '=')
  float (*read)();
};

// ---- TABLA DE SEÑALES: añadir / quitar líneas aquí ----
const TelemetrySignal TELEMETRY[] = {
  {"indice", tIndice},
  {"medio",  tMedio},
  {"anular", tAnular},
  {"pulgar", tPulgar},
  {"gesto",  tGesto},
  {"fase",   tFase},
};

void sendTelemetry() {
  char buf[BIOMEC_MAX_MSG + 1];
  int n = snprintf(buf, sizeof(buf), "DATA");
  for (const auto& s : TELEMETRY) {
    if (n >= BIOMEC_MAX_MSG) break;
    n += snprintf(buf + n, sizeof(buf) - n, " %s=%.0f", s.key, s.read());
  }
  n = min(n, BIOMEC_MAX_MSG);
  esp_now_send(BRIDGE_MAC, (const uint8_t*)buf, n);
}

// ======================= ESP-NOW =====================================
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

void dispatch(const String& line) {
  BiomecArgs args = BiomecArgs::parse(line);
  if (args.name.length() == 0) return;
  for (const auto& c : COMMANDS) {
    if (args.name == c.name) {
      c.handler(args);
      return;
    }
  }
  reply("ERR Comando desconocido en la mano: %s", args.name.c_str());
}

void iniciarEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(BIOMEC_ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ERR No se pudo iniciar ESP-NOW");
    return;
  }
  esp_now_register_recv_cb(onEspNowRecv);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BRIDGE_MAC, 6);
  peer.channel = BIOMEC_ESPNOW_CHANNEL;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
}

// ======================= setup / loop ================================
// Comandos también por el USB de la propia mano (útil para probar sin puente).
static String usbLine;

void setup() {
  Serial.begin(BIOMEC_SERIAL_BAUD);
  rxQueue = xQueueCreate(BIOMEC_QUEUE_LEN, sizeof(BiomecPacket));

  ConfiguracionDeMotores();  // La configuración de los motores y servo
  iniciarEspNow();

  irAGesto(0);  // Empieza abriendo la mano (como antes, Estado = 0)
  reply("Mano lista. MAC=%s modo=%s reinicio=%s", WiFi.macAddress().c_str(),  // por radio y por USB
        modoAuto ? "AUTO" : "MANUAL", motivoReinicio());
}

void loop() {
  // 1) Comandos recibidos por ESP-NOW
  BiomecPacket p;
  while (xQueueReceive(rxQueue, &p, 0) == pdTRUE) {
    if (!isBroadcast(BRIDGE_MAC) && memcmp(p.mac, BRIDGE_MAC, 6) != 0) continue;  // no es el puente
    dispatch(String(p.text));
  }

  // 2) Comandos por USB (monitor serie del Arduino IDE)
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { dispatch(usbLine); usbLine = ""; }
    else if (c != '\r' && usbLine.length() < 200) usbLine += c;
  }

  // 3) Motores
  actualizarMano();

  // 4) Telemetría
  static unsigned long ultimo = 0;
  if (streaming && millis() - ultimo >= periodoTelemetria) {
    ultimo = millis();
    sendTelemetry();
  }
}
