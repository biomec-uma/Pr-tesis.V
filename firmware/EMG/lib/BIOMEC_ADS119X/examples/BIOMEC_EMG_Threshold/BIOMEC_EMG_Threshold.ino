/**
 * @file BIOMEC_EMG_Threshold.ino
 * @brief Detección de contracción muscular por umbral en señal EMG.
 *
 * Lee continuamente el canal 1 del ADS119X y detecta contracciones
 * musculares cuando la señal supera un umbral definido. Envía por
 * puerto Serie el estado de contracción.
 *
 * Contexto: detección de contracción muscular para activación de
 * mano protésica mediante señal EMG de superficie.
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

// Pines
#define PIN_DRDY  4
#define PIN_RESET 5
#define PIN_CS    15
#define PIN_SCLK  18
#define PIN_MISO  19
#define PIN_MOSI  23

// Umbral de detección de contracción (ajustar según señal)
#define EMG_THRESHOLD 1000

ADS119X ads(PIN_DRDY, PIN_RESET, PIN_CS, PIN_SCLK, PIN_MISO, PIN_MOSI);

bool contractionDetected = false;

void setup() {
  Serial.begin(115200);

  if (!ads.begin()) {
    Serial.println("ERROR: ADS119X no detectado.");
    while (1);
  }

  Serial.println("ADS119X inicializado correctamente.");

  // Configurar CH1: normal, ganancia 4, entrada normal
  ads.setChannelSettings(ADS119X_ADD_CH1SET, ADS119X_CHnSET_PD_NORMAL, ADS119X_CHnSET_GAIN_4, ADS119X_CHnSET_MUX_NORMAL);

  // Iniciar conversión continua
  ads.sendCommand(ADS119X_CMD_START);
  ads.sendCommand(ADS119X_CMD_RDATAC);
}

void loop() {
  if (ads.isDRDY()) {
    ads.readChannelData();

    int16_t emg = abs(ads.getChannelData(0)); // CH1

    if (emg > EMG_THRESHOLD && !contractionDetected) {
      contractionDetected = true;
      Serial.println("CONTRACCION DETECTADA");
    } else if (emg <= EMG_THRESHOLD && contractionDetected) {
      contractionDetected = false;
      Serial.println("RELAJACION DETECTADA");
    }

    Serial.print("EMG CH1: ");
    Serial.println(emg);
  }
}