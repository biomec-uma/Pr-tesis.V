#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoOTA.h>

#define LED 2

const char* ap_ssid = "biomec";
const char* ap_password = "12345678";

void setupOTA();
void loopOTA();

void setup() {
  setupOTA();

  pinMode(LED, OUTPUT);
}

void loop() {
  loopOTA();

  digitalWrite(LED, HIGH);
  delay(100);
  digitalWrite(LED, LOW);
  delay(100);
}

void setupOTA() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP(ap_ssid, ap_password);

  ArduinoOTA.setHostname("esp32-ota");
  ArduinoOTA.begin();
}

void loopOTA() {
  ArduinoOTA.handle();
}

