#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Adafruit_NeoPixel.h>
// ----- Marco que se envía al PC por USB -----
#define CANAL_ESPNOW  1 
// ----- Marco que se envía al PC por USB -----
#define SYNC1 0xAA          // firma de inicio de cada marco
#define SYNC2 0x55
#define TIPO_DATOS  0x01    // marco con un paquete del sensor
#define TIPO_ESTADO 0x02    // marco con el diagnóstico de la C6

// ----- Paquete que llega del sensor -----
#define CABECERA_SENSOR 9   // version(1) + nChnls(1) + batch(1) + seq(4) + sendFails(2)=9 equivale a 1 fila sin valores EMG
#define MAX_ESPNOW 250      // 250bytes/paquete equivale a tamaño maximoenviable por ESPNOW

// Hacemos un struct con el paquete tal cual llega y cuantos bytes validos tiene 
typedef struct {
  uint8_t len;
  uint8_t datos[MAX_ESPNOW];
} Recibido;

// Otro struct con atributos sobre el diagnostico de los paquetes
typedef struct __attribute__((packed)) {
  uint8_t  mac[6];          // MAC de esta C6 (la que va en rxMac del sensor)
  uint32_t recibidos;       // paquetes válidos recibidos
  uint32_t invalidos;       // paquetes con tamaño incorrecto
  uint32_t perdidosCola;    // llegaron pero la cola estaba llena
  uint32_t descartadosUSB;  // no se pudieron mandar al PC (nadie leyendo)
} Estado; //6+4*4=22bytes

//=================Variables globales=================
QueueHandle_t cola;   // el "buzón" donde el callback mete y el loop lo vacía
uint8_t miMac[6];

//Las variables propias del struct de diagnostico son volatile porque los esvribe el callback
volatile uint32_t recibidos = 0;
volatile uint32_t invalidos = 0;
volatile uint32_t perdidosCola = 0;
uint32_t descartadosUSB = 0;   // solo lo toca el loop() no hace falta volatile
uint32_t ultimoPaqueteMs = 0;

//Variables LED C6
#define LED_PIN 8
#define NUM_LEDS 1
Adafruit_NeoPixel led(NUM_LEDS, LED_PIN, NEO_RGB + NEO_KHZ800);

void initLED(){
  led.begin();
  led.setBrightness(150);
  led.clear();
  led.show();
}

void onDataReceived(const esp_now_recv_info_t *info, const uint8_t *data, int len){
  // data[version(1), nChnls(1), batch(1), seq(4), sendFails(2), data[nChnls*batch*2] 

  // Filtro para descartar paquetes con otro formato
  if (len < CABECERA_SENSOR || len > MAX_ESPNOW){ invalidos++; return; }
  //Registro el nº de canales y nº de muestras por paquete para 2ºcomprobación
  uint8_t nChnls = data[1];  uint8_t batch  = data[2];
  //Filtro para descartar paquetes corruptos a pesar de tener bien el formato
  if (len != CABECERA_SENSOR + nChnls * batch * 2){ invalidos++; return; }

  // Creo un paquete ajustado al recibido por ESPNOW 
  Recibido r;
  r.len = len;
  memcpy(r.datos, data, len);
  if (xQueueSend(cola, &r, 0) == pdTRUE) recibidos++;//El 0 significa "no te bloquees si está lleno", se cuenta y se sigue
  else perdidosCola++;//Si la cola estaba llena se cuenta como perdido
}

//Con lo realizado en las funciones de antes (registrar problemas) inicio el protocolo
void initEspNow(){
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  esp_wifi_set_channel(CANAL_ESPNOW, WIFI_SECOND_CHAN_NONE);
  if(esp_now_init()!=ESP_OK) ESP.restart();
  esp_now_register_recv_cb(onDataReceived);
}

void enviarMarco(uint8_t tipo, const uint8_t *payload, uint8_t len){
  uint8_t marco[4 + MAX_ESPNOW + 1];
  marco[0] = SYNC1;
  marco[1] = SYNC2;
  marco[2] = tipo;
  marco[3] = len;
  memcpy(&marco[4], payload, len);

  // Comprobación: XOR de tipo, longitud y todos los bytes del contenido
  uint8_t chk = tipo ^ len;
  for (int i = 0; i < len; i++) chk ^= payload[i];
  marco[4 + len] = chk;

  int total = 5 + len;
  // Si el PC no está leyendo, el buffer USB se llena: mejor descartar que bloquear
  if (Serial.availableForWrite() < total){ descartadosUSB++; return; }
  Serial.write(marco, total);
}

void enviarEstado(){
  Estado e;
  memcpy(e.mac, miMac, 6);
  e.recibidos      = recibidos;
  e.invalidos      = invalidos;
  e.perdidosCola   = perdidosCola;
  e.descartadosUSB = descartadosUSB;
  enviarMarco(TIPO_ESTADO, (uint8_t*)&e, sizeof(e));
}

void actualizarLED(){
  static int8_t pintado = -1;   // -1: todavía no se ha pintado nada
  int8_t recibiendo = (millis() - ultimoPaqueteMs < 500) ? 1 : 0;
  if (recibiendo == pintado) return;   // solo se toca el LED si cambia el estado
  pintado = recibiendo;
  led.setPixelColor(0, recibiendo ? led.Color(0, 0, 255) : led.Color(255, 0, 0));
  led.show();
}

void setup(){

  Serial.setTxBufferSize(2048);
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // no bloquear nunca al enviar por USB
  initLED();

  cola=xQueueCreate(16, sizeof(Recibido));  // cola de 16 paquetes
  initEspNow();
  WiFi.macAddress(miMac);
}

void loop(){
 Recibido r;
  if (xQueueReceive(cola, &r, pdMS_TO_TICKS(5)) == pdTRUE){
    enviarMarco(TIPO_DATOS, r.datos, r.len);
    ultimoPaqueteMs = millis();
  }
  static uint32_t ultimoEstado=0;
  if (millis() - ultimoEstado > 1000){
    ultimoEstado = millis();
    enviarEstado();
  }

  actualizarLED();
}