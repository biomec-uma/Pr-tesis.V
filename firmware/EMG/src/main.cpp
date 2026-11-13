#include <SPI.h>
#include <BIOMEC_ADS119X.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#define CANAL_ESPNOW 1
#define BATCH 5 //Agrupar 5 muestras (1 muestra/2ms ~ 10ms)
#define N_CHNLS 2 //Cambiamos al numero de canales que necesitemos
#define DNI 1 //Version del paquete

//=================NO CAMBIAR EL ORDEN DE LOS CAMPOS DEL STRUCT=================
//Estructura de mi paquete
typedef struct __attribute__((packed)){//__attribute__ es para no meter relleno cuando halla espacios, por seguiridad pero no haría falta
  uint8_t version; //Formato (nos puede ayudar en el futuro)
  uint8_t nChnls; //Nº de canales
  uint8_t batch; //Nº de muestras por paquete
  uint32_t seq; //El numero de paquete
  uint16_t sendFails;//Nº de envios fallidos
  int16_t data[BATCH][N_CHNLS];
} Packet;
//Restricción en envios (tamaño y dirección)
static_assert(sizeof(Packet) <= 250, "El paquete excede la capacidad, reducir BATCH o N_CHNLS");//No compila si el tamaño excede
uint8_t rxMac[]={0xAC,0xEB,0xE6,0x2C,0xD7,0xDC}; //Defino el MAC RECEPTOR C6 como rxMac
//Creación de paquete e iniciación de variables
Packet pkt;
uint8_t idx=0;//contador dentro de pkt
uint32_t seq=0;//nºde paquete
volatile uint16_t sendFails=0;//Los envios fallidos
void initPaquete(){
  pkt.version=DNI;
  pkt.nChnls=N_CHNLS; 
  pkt.batch=BATCH;
}
//=================================================

//Contador de envios fallidos
void onSent(const wifi_tx_info_t *info, esp_now_send_status_t s) {
  if (s != ESP_NOW_SEND_SUCCESS) sendFails++;
}
//Inicialización de ESP-NOW [se mete rxMAC y canal de radio]
void initEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  esp_wifi_set_channel(CANAL_ESPNOW,WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) { ESP.restart(); }
  esp_now_register_send_cb(onSent);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, rxMac, 6);
  peer.channel = CANAL_ESPNOW;          
  peer.encrypt = false;
  if(esp_now_add_peer(&peer)!=ESP_OK){ESP.restart();}
}

//=================Variables del ADS===============
//Pins para el ads 
byte dataReady_Pin = 1;
byte reset_pin = 0;
byte cs_pin = 10 ; 
byte clk_pin = 6;
byte miso_pin = 2; 
byte mosi_pin = 7;
byte start_pin = 3;
ADS119X adc(dataReady_Pin,reset_pin , cs_pin, clk_pin, miso_pin, mosi_pin);
//Variables del ADS para utilidades
volatile bool dataReady = false;
//Variables del ADS para hacer test
bool testADS = false;
const byte testModeRuidoInterno = 0x00;
const byte testModeSignalCuadrada = 0x01;
const byte testModeSignalDC = 0x02;
//Variables del ADS para configuracion
const byte N_CHNLS_TOTALES = 0x08;
const byte adsGanancia = ADS119X_CHnSET_GAIN_4;
const byte adsSPS = ADS119X_DRATE_500SPS;

//Preconfiguraciones para registros
//Pre-conf registro CONFIG3 para RLD 0xCC = 1100 1100
//Activa unicamente la referencia interna y ref interna del AO RLD

byte preconfRLDConfig3 = 0xCC;
//Pre-conf registro RLD_SENSP y RLD_SENSN 
//El circuito RLD escucha el ruido de los electrodos de los canales CH1 y CH2

byte preconfSENSPCH1yCH2 = 0x03;
byte preconfSENSNCH1yCH2 = 0x03;

//=================================================


//Recojo el valor del ADS en un canal y lo guardo en el paquete para enviar
void printData() {
  int cadaXmuestras = 1;//Por si quisiera imprimir con saltos (1= cada muestra, 2 = cada 2 muestras, etc)
  for(int ch=0;ch<N_CHNLS;ch++){
    int16_t v=adc.getChannelData(ch);
    pkt.data[idx][ch]=v;//Guarda el valor del canal ch en la fila idx del paquete
  }
  if(++idx==BATCH){//Incremento el contador y comparo con el maximo de muestras por paquete
    pkt.seq=seq++; //Registramos el nº del paquete
    pkt.sendFails=sendFails; //Registramos el nº de envios fallidos
    esp_now_send(rxMac, (uint8_t*)&pkt, sizeof(pkt));
    idx=0;//Vacio contador
  }
}

//=================INTERRUPCIONES==========================
//Interrupcion ADS. DataReady (cada vez que recibo un valor )
void IRAM_ATTR dataReadyADS(){
  dataReady = true;
}

//=========================================================

/*Esta funcion prepara el ADS respetando orden y tiempos especificados en el datasheet.
Deber ser siempre la primera en iniciarse. 
Tras llamar a esta funcion debe llamarse posteriormente a configurarADS()
*/
void prepararADS(){
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
  //Serial.println("Esperando estabilización de energía...");
  delay(1000); 
  // 2. En caso de no conectar lo reintenta 7 veces más en caso contrario se reinicia
  int intentos = 0;
  int maxIntentos = 7;
  bool conectado = false;
  while (intentos < maxIntentos && !conectado) {
    //Serial.printf("Intento de conexión ADS1198: %d de %d...\n", intentos + 1, maxIntentos);
    if (adc.begin()) {
      conectado = true;
      //Serial.println("¡ADS1198 Conectado con éxito!");
    }else{
      intentos++;
      delay(500); 
    }
  }
  //--------------------------------------------------------------------
  // 3. Si después de los intentos no conecta, resetear ESP32-----------
  if (!conectado) {
    //Serial.println("Fallo crítico: No se pudo conectar con el ADS. Reiniciando microcontrolador...");
    delay(1000); 
    ESP.restart(); 
  }  
}

/*Esta funcion debe ejecutarse siempre despues de prepararADS()*/
void configurarADS(){
  
  // Stop continuous conversion, and send commands to configure (un poco de ingles por si te parecia aburrido)
  adc.sendCommand (ADS119X_CMD_SDATAC);
  
  // ========== CAMBIO CRÍTICO 1: GANANCIA REDUCIDA ==========
  adc.setAllChannelGain(adsGanancia);
  adc.setAllChannelMux(ADS119X_CHnSET_MUX_NORMAL); //Este método activa todos los canales

  for (byte address=ADS119X_ADD_CH1SET+N_CHNLS; address<ADS119X_ADD_CH1SET+N_CHNLS_TOTALES; address++){
    adc.setChannelSettings(address, ADS119X_CHnSET_PD_NORMAL, ADS119X_CHnSET_GAIN_1, ADS119X_CHnSET_MUX_IN_SHORT);    
    adc.setChannelSettings(address, ADS119X_CHnSET_PD_POWERDOWN, ADS119X_CHnSET_GAIN_1, ADS119X_CHnSET_MUX_IN_SHORT);
  }
  //--------------------------------------------------------------------
  adc.setDataRate(adsSPS);
  adc.sendCommand(ADS119X_CMD_START);
  adc.sendCommand(ADS119X_CMD_RDATAC);  

}

/*Esta funcion decide si los datos que imprime printData() son muestras EMG o señales de prueba.
testear: Define si se hace el test o no
modo: Define que tipo de test quiere hacerse
Si testear = false la funcion no hace nada*/
void testearADS(bool testear, byte modo){
  if (testear){
    switch (modo){
      case testModeRuidoInterno:
      adc.testNoise();
      break;
      
      case testModeSignalCuadrada:
      adc.testSignal();
      break;

      case testModeSignalDC:
      adc.testSignalDC();
      break;
    }
  }
}


void configurarRLD(){

  adc.sendCommand(ADS119X_CMD_SDATAC); //Primero siempre detener la lectura
  adc.WREG(ADS119X_ADD_CONFIG3,preconfRLDConfig3);
  adc.WREG(ADS119X_ADD_RLD_SENSP,preconfSENSPCH1yCH2);
  adc.WREG(ADS119X_ADD_RLD_SENSN,preconfSENSNCH1yCH2);
  adc.sendCommand(ADS119X_CMD_START); //Siempre continuar conversiones
  adc.sendCommand(ADS119X_CMD_RDATAC); //Siempre leer conversiones

}


void setup() {
  prepararADS();
  configurarADS();
  configurarRLD();
  testearADS(testADS,testModeSignalCuadrada);
  initPaquete();
  initEspNow();
  attachInterrupt(digitalPinToInterrupt(dataReady_Pin),dataReadyADS,FALLING);
  Serial.begin(115200);
  Serial.println("\n===== SISTEMA LISTO =====\n");
}

void loop() {
  if(dataReady){
    dataReady = false; //Cambio estado provocado por la interrupcion
    adc.readChannelData();
    printData();    
  }
}