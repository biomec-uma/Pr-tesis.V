/**
 * @file BIOMEC_EMG_Basic.ino
 * @brief Adquisición básica de señal EMG con ADS119X.
 *
 * Lee continuamente los canales activos del ADS119X y envía los datos
 * por puerto Serie. Ejemplo básico para verificar la adquisición de
 * señal desde electrodos de superficie.
 *
 * Contexto: adquisición de señal EMG para control de mano protésica.
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

ADS119X ads(PIN_DRDY, PIN_RESET, PIN_CS, PIN_SCLK, PIN_MISO, PIN_MOSI);

void setup() {
  Serial.begin(115200);
  
  if (!ads.begin()) {
    Serial.println("ERROR: ADS119X no detectado.");
    while (1);
  }
  
  Serial.println("ADS119X inicializado correctamente.");
  Serial.print("Canales activos: ");
  Serial.println(ads.getNumberOfChannels());

  // Configurar todos los canales: normal, ganancia 4, entrada normal
  ads.setAllChannelSettings(ADS119X_CHnSET_PD_NORMAL, ADS119X_CHnSET_GAIN_4, ADS119X_CHnSET_MUX_NORMAL);

  // Iniciar conversión continua
  ads.sendCommand(ADS119X_CMD_START);
  ads.sendCommand(ADS119X_CMD_RDATAC);
}

void loop() {
  if (ads.isDRDY()) {
    ads.readChannelData();
    
    for (byte ch = 0; ch < ads.getNumberOfChannels(); ch++) {
      Serial.print("CH");
      Serial.print(ch + 1);
      Serial.print(": ");
      Serial.print(ads.getChannelData(ch));
      if (ch < ads.getNumberOfChannels() - 1) Serial.print(" | ");
    }
    Serial.println();
  }
}