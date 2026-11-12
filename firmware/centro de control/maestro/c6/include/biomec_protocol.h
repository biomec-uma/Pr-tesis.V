// =====================================================================
//  BIOMEC UMA · Protocolo común PC <-> Puente <-> Mano
//  ¡Este archivo debe ser IDÉNTICO en puente_pc/include y mano/include!
// =====================================================================
//
//  PC  --USB serie-->  C6 PUENTE  --ESP-NOW-->  C6 MANO
//  PC  <--USB serie--  C6 PUENTE  <--ESP-NOW--  C6 MANO
//
//  Todo son líneas de texto (sin '\n' dentro del paquete ESP-NOW).
//
//  PC -> puente:
//     "COMANDO args"   se reenvía tal cual a la mano
//     "@COMANDO args"  lo ejecuta el propio puente
//
//  Puente/mano -> PC (primera palabra = tipo, lo interpreta la app):
//     "DATA clave=valor clave=valor"   telemetría -> gráficas
//     "ACK COMANDO ..."                comando ejecutado
//     "ERR texto"                      error
//     "BRIDGE texto"                   mensaje del puente
//
//  Excepción: la señal de la placa EMG (si está encendida) va del puente
//  al PC en marcos binarios "AA 55 tipo longitud contenido XOR", entre
//  las líneas de texto (ver puente_pc.cpp). Sin placa EMG, todo es texto.
// =====================================================================
#pragma once
#include <Arduino.h>

#define BIOMEC_SERIAL_BAUD    115200
#define BIOMEC_ESPNOW_CHANNEL 1     // Ambas placas deben usar el mismo canal
#define BIOMEC_MAX_MSG        240   // ESP-NOW admite hasta 250 bytes por paquete
#define BIOMEC_QUEUE_LEN      16

// Paquete recibido por ESP-NOW, copiado desde el callback a una cola
// para procesarlo con calma en loop() (nunca dentro del callback).
struct BiomecPacket {
  uint8_t mac[6];
  uint8_t len;
  char    text[BIOMEC_MAX_MSG + 1];
};

// Argumentos de un comando ya troceados: "DEDO 2 50" -> name="DEDO", v={"2","50"}
struct BiomecArgs {
  static const int MAX = 8;
  String name;
  String v[MAX];
  int    count = 0;

  long  toInt(int i, long def = 0) const    { return i < count ? v[i].toInt()   : def; }
  float toFloat(int i, float def = 0) const { return i < count ? v[i].toFloat() : def; }

  static BiomecArgs parse(const String& line) {
    BiomecArgs a;
    int start = 0;
    String s = line;
    s.trim();
    bool first = true;
    while (start < (int)s.length()) {
      int sp = s.indexOf(' ', start);
      if (sp < 0) sp = s.length();
      String tok = s.substring(start, sp);
      start = sp + 1;
      if (tok.length() == 0) continue;
      if (first) { a.name = tok; a.name.toUpperCase(); first = false; }
      else if (a.count < MAX) { a.v[a.count++] = tok; }
    }
    return a;
  }
};

inline String biomecMacToString(const uint8_t* mac) {
  char buf[18];
  snprintf(buf, sizeof(buf), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  return String(buf);
}
