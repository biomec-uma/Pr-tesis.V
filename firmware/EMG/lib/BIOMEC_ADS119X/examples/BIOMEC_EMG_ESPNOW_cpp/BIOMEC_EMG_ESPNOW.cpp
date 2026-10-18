/**
 * @file BIOMEC_EMG_ESPNOW.ino
 * @brief Envío de datos EMG mediante ESP-NOW a otro ESP32.
 *
 * Lee continuamente los canales activos del ADS119X y envía los datos
 * por ESP-NOW a un ESP32 receptor encargado del control de la mano
 * protésica. La dirección MAC del receptor debe configurarse antes de
 * compilar.
 *
 * Contexto: transmisión inalámbrica de señal EMG para control remoto
 * de mano protésica.
 *
 * Conexiones ESP32 (por defecto):
 *  - DRDY : GPIO 4
 *  - RESET: GPIO 5
 *  - CS   : GPIO 15
 *  - SCLK : GPIO 18
 *  - MISO : GPIO 19
 *  - MOSI : GPIO 23
 */

#include "BIOMEC_ADS119X.h"
#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>

// Pines
#define PIN_DRDY  4
#define PIN_RESET 5
#define PIN_CS    15
#define PIN_SCLK  18
#define PIN_MISO  19
#define PIN_MOSI  23

// MAC del ESP32 receptor (modificar según dispositivo)
uint8_t receiverMAC[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Estructura de datos a enviar
typedef struct {
  int16_t channel[8];
  uint8_t numChannels;
} EMGPacket;

EMGPacket packet;

ADS119X ads(PIN_DRDY, PIN_RESET, PIN_CS, PIN_SCLK, PIN_MISO, PIN_MOSI);

void onDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  if (status != ESP_NOW_SEND_SUCCESS) {
    Serial.println("ERROR: fallo en el envío ESP-NOW.");
  }
}

void setup() {
  Serial.begin(115200);

  // Inicializar WiFi en modo estación para ESP-NOW
  WiFi.mode(WIFI_STA);

  // Inicializar ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("ERROR: fallo al inicializar ESP-NOW.");
    while (1);
  }
  esp_now_register_send_cb(onDataSent);

  // Registrar receptor
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverMAC, 6);
  peerInfo.channel = 0;
  peerInfo.encrypt = false;
  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("ERROR: fallo al registrar receptor ESP-NOW.");
    while (1);
  }

  // Inicializar ADS119X
  if (!ads.begin()) {
    Serial.println("ERROR: ADS119X no detectado.");
    while (1);
  }

  Serial.println("ADS119X inicializado correctamente.");
  packet.numChannels = ads.getNumberOfChannels();

  // Configurar todos los canales: normal, ganancia 4, entrada normal
  ads.setAllChannelSettings(ADS119X_CHnSET_PD_NORMAL, ADS119X_CHnSET_GAIN_4, ADS119X_CHnSET_MUX_NORMAL);

  // Iniciar conversión continua
  ads.sendCommand(ADS119X_CMD_START);
  ads.sendCommand(ADS119X_CMD_RDATAC);
}

void loop() {
  if (ads.isDRDY()) {
    ads.readChannelData();

    for (byte ch = 0; ch < packet.numChannels; ch++) {
      packet.channel[ch] = ads.getChannelData(ch);
    }

    esp_now_send(receiverMAC, (uint8_t *)&packet, sizeof(packet));
  }
}