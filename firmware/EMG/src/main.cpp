#include <SPI.h>
#include <BIOMEC_ADS119X.h>
#include <WiFi.h>
#include <esp_now.h>
#define BATCH 20 //Agrupar 20 muestras (1 muestra/2ms ~ 40ms)

#define N_CHNLS 2 //Cambiamos al numero de canales que necesitemos

typedef struct __attribute__((packed)){//__attribute__ es para no meter relleno cuando halla espacios, en este caso no lo haría porque el tamaño es el justo
  uint16_t seq;
  int16_t data[BATCH][N_CHNLS];
} Packet;

uint8_t rxMac[]={0xAC,0xEB,0xE6,0x2C,0xD7,0xDC}; //RECEPTOR C6
Packet pkt;
uint8_t idx=0;
uint16_t seq=0;
volatile uint16_t sendFails=0;

void onSent(const wifi_tx_info_t *info, esp_now_send_status_t s) {
  if (s != ESP_NOW_SEND_SUCCESS) sendFails++;
}
void initEspNow() {
  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) { ESP.restart(); }
  esp_now_register_send_cb(onSent);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, rxMac, 6);
  peer.channel = 0;          // mismo canal que el receptor
  peer.encrypt = false;
  esp_now_add_peer(&peer);
}


// Pins para el ads 
byte dataReady_Pin = 1;
byte reset_pin = 0;
byte cs_pin = 10 ; 
byte clk_pin = 6;
byte miso_pin = 2; 
byte mosi_pin = 7;
byte start_pin = 3;
ADS119X adc(dataReady_Pin,reset_pin , cs_pin, clk_pin, miso_pin, mosi_pin);


//Variables del ADS
bool dataReady = 0;
bool prev_dataReady = 0;
//byte received ; 
//boolean verbosity = 1; 
byte numberOfChannels;
//const byte numChars = 32;
//char receivedChars[numChars];
//char tempChars[numChars];        
//int command [2]; 
//boolean newData = false;
byte state = 1; 
//int elapsed = 0 ;
//long prevMicros = 0 ;
bool flagReset=false;
uint16_t contador_ceros_brutos=0;

void printData() {
  bool todoCero=true;
  for(int ch=0;ch<N_CHNLS;ch++){
    int16_t v=adc.getChannelData(ch);
    pkt.data[idx][ch]=v;//Lo guardo al paquete de envío
    if(v!=0) todoCero=false;
  }
  contador_ceros_brutos = todoCero ? contador_ceros_brutos + 1 : 0;
  if(contador_ceros_brutos > 750) flagReset = true;


  if(++idx==BATCH){//Cuando tenga 20 muestras
    pkt.seq=seq++; //Enumeración de dato para verla en orden
    esp_now_send(rxMac, (uint8_t*)&pkt, sizeof(pkt));
    idx=0;//Vacio contador
  }
}

void setup() {
  
  Serial.begin(115200);  
  // INICIO DE ADS1198------------------------------------------------------------------
  // 0. Necesario poner entradas del ADS a 0 por hardware.-------------
  // Estado seguro de lineas de control antes de adc.begin()
  pinMode(cs_pin, OUTPUT);
  digitalWrite(cs_pin, HIGH);   // Mantener ADS deseleccionado

  pinMode(reset_pin, OUTPUT);
  digitalWrite(reset_pin, LOW); // Mantener ADS en reset al arranque

  pinMode(clk_pin, OUTPUT);
  digitalWrite(clk_pin, LOW);

  pinMode(mosi_pin, OUTPUT);
  digitalWrite(mosi_pin, LOW);

  pinMode(start_pin, OUTPUT);
  digitalWrite(start_pin, LOW);

  // Lineas de entrada al micro (no forzar nivel)
  pinMode(dataReady_Pin, INPUT);
  pinMode(miso_pin, INPUT);
  //Las entradas analógicas del ADC deben estar en LOW de alguna manera
  //--------------------------------------------------------------------
  
  // 1. Retardo inicial para "despertar"--------------------------------
  Serial.println("Esperando estabilización de energía...");
  delay(1000); 
  // 2. Bucle de reintentos
  int intentos = 0;
  int maxIntentos = 7;
  bool conectado = false;
  while (intentos < maxIntentos && !conectado) {
    Serial.printf("Intento de conexión ADS1198: %d de %d...\n", intentos + 1, maxIntentos);
    if (adc.begin()) {
      conectado = true;
      numberOfChannels = adc.getNumberOfChannels();
      Serial.println("¡ADS1198 Conectado con éxito!");
    }else{
      intentos++;
      delay(500); 
    }
  }
  //--------------------------------------------------------------------
  // 3. Si después de los intentos no conecta, resetear ESP32-----------
  if (!conectado) {
    Serial.println("Fallo crítico: No se pudo conectar con el ADS. Reiniciando microcontrolador...");
    delay(2000); 
    ESP.restart(); 
  }
  //--------------------------------------------------------------------

  // Stop continuous conversion, and send commands to configure 
  adc.sendCommand (ADS119X_CMD_SDATAC);
  
  // ========== CAMBIO CRÍTICO 1: GANANCIA REDUCIDA ==========
  // En 4.1 funciona bien, en 4.2 se satura. Usamos la de 4.1
  adc.setAllChannelGain( ADS119X_CHnSET_GAIN_4);  //
  
  adc.setAllChannelMux(ADS119X_CHnSET_MUX_NORMAL); //Este método activa todos los canales
  

    //Desactivo canales que no voy a usar -----------------------------------------------
  for (byte address = ADS119X_ADD_CH3SET; address <= ADS119X_ADD_CH8SET; address++) {
    adc.setChannelSettings(address, ADS119X_CHnSET_PD_NORMAL, ADS119X_CHnSET_GAIN_1, ADS119X_CHnSET_MUX_IN_SHORT);
  }
  for (byte address = ADS119X_ADD_CH3SET; address <= ADS119X_ADD_CH8SET; address++) {
    adc.setChannelSettings(address, ADS119X_CHnSET_PD_POWERDOWN, ADS119X_CHnSET_GAIN_1, ADS119X_CHnSET_MUX_IN_SHORT);
  }
  //--------------------------------------------------------------------

  //--------------------------------------------------------------------
  
  adc.setDataRate(ADS119X_DRATE_500SPS);     
  adc.sendCommand(ADS119X_CMD_START);
  adc.sendCommand(ADS119X_CMD_RDATAC);

  initEspNow();

  Serial.println("\n===== SISTEMA LISTO =====\n");
}

void loop() {

  if (state) { 
    dataReady = adc.isDRDY();
    if (!prev_dataReady && dataReady) {
      //elapsed = micros() - elapsed;
      //elapsed = micros();
      adc.readChannelData();
      printData();  
    }
    prev_dataReady = dataReady;
  }
  if (flagReset){
    delay(100);
    ESP.restart();    
  }
}