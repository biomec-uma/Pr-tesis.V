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

uint8_t rxMac[]={0xAC,0xEB,0xE6,0x00,0x55,0xB4}; //RECEPTOR C6
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
bool dataReady = false;
bool flagReset=false;
uint16_t contador_ceros_brutos=0;
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
/*Pre-conf registro CONFIG3 para RLD 0xCC = 1100 1100
Activa unicamente la referencia interna y ref interna del AO RLD
*/
byte preconfRLDConfig3 = 0xCC;
/*Pre-conf registro RLD_SENSP y RLD_SENSN 
El circuito RLD escucha el ruido de los electrodos de los canales CH1 y CH2
*/
byte preconfSENSPCH1yCH2 = 0x03;
byte preconfSENSNCH1yCH2 = 0x03;
//=================================================

/*
Para cada x muestras se toma la fila idx del momento e itera las columnas.
Como resultado obtenemos una fila ix con todas sus columnas cada x muestras
*/
void serialPrintPaquetes (uint8_t filaVariable, int cadaXmuestras){

  static int cnt = 0;
  cnt++;

  if (cnt == cadaXmuestras){
    for(int i=0; i<N_CHNLS; i++){

      if(i>0){
        Serial.print('\t'); 
      } 
      Serial.print(pkt.data[filaVariable][i]);
    }
    
    Serial.println();
    cnt = 0;

  }

}

void printData() {
  bool todoCero=true;
  int cadaXmuestras = 5;
  
  for(int ch=0;ch<N_CHNLS;ch++){
    int16_t v=adc.getChannelData(ch);
    pkt.data[idx][ch]=v;//Lo guardo al paquete de envío
    if(v!=0) {
      todoCero=false;
    }
  }
  
  serialPrintPaquetes(idx, cadaXmuestras);

  if(++idx==BATCH){//Cuando tenga 20 muestras pero siempre incrementa antes de evaluar
    pkt.seq=seq++; //Enumeración de dato para verla en orden
    esp_now_send(rxMac, (uint8_t*)&pkt, sizeof(pkt));
    idx=0;//Vacio contador
  }

  if (todoCero == true) {//Comprueba que no se haya quedado atrancado el ADS
    contador_ceros_brutos = contador_ceros_brutos + 1;
  } else {
    contador_ceros_brutos = 0;
  }
  if(contador_ceros_brutos > 750) flagReset = true; //Solo se reciben 0 => restart ESP

}

//=================INTERRUPCIONES==========================

//Interrupcion ADS. DataReady
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

}

/*Esta funcion debe ejecutarse siempre despues de prepararADS()*/
void configurarADS(){
  
  // Stop continuous conversion, and send commands to configure 
  adc.sendCommand (ADS119X_CMD_SDATAC);
  
  // ========== CAMBIO CRÍTICO 1: GANANCIA REDUCIDA ==========
  // En 4.1 funciona bien, en 4.2 se satura. Usamos la de 4.1
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

/*Esta funcion usa adc.getRegister(address) para obtener el estado de un registro
La entrada es una direccion de un registro determinado.
Imprime el registro en Hexadecimal
*/
void imprimirRegistros(){
  int cnt = 1;

  //Imprime Registro CHTSET
  for(byte address = ADS119X_ADD_CH1SET;address<=ADS119X_ADD_CH8SET; address++){
    Serial.print("CH");Serial.print(cnt);Serial.print("SET:");
    Serial.println(adc.getRegister(address),HEX);
    cnt++;
  }

  cnt = 1;
  //Imprime Registro CONFIG1-3
  for(byte address = ADS119X_ADD_CONFIG1;address<=ADS119X_ADD_CONFIG3; address++){
    Serial.print("CONFIG");Serial.print(cnt);Serial.print(":");
    Serial.println(adc.getRegister(address),HEX);
    cnt++;
  }

  //Imprime Registro CONFIG 4
  Serial.print("CONFIG");Serial.print(cnt);Serial.print(":");
  Serial.println(adc.getRegister(ADS119X_ADD_CONFIG4),HEX);

  //Imprime Registro RLD SENSP y SENSN
  Serial.print("RLD SENSP");Serial.print(":");
  Serial.println(adc.getRegister(ADS119X_ADD_RLD_SENSP),HEX);
  Serial.print("RLD SENSN");Serial.print(":");
  Serial.println(adc.getRegister(ADS119X_ADD_RLD_SENSN),HEX);

  //Imprime Registro LOFF SENSP y SENSN
  Serial.print("LOFF SENSP");Serial.print(":");
  Serial.println(adc.getRegister(ADS119X_ADD_LOFF_SENSP),HEX);
  Serial.print("LOFF SENSN");Serial.print(":");
  Serial.println(adc.getRegister(ADS119X_ADD_LOFF_SENSN),HEX);

  //Imprime Registro de estado LOFF STATP y STATN
  Serial.print("LOFF STATP");Serial.print(":");
  Serial.println(adc.getRegister(ADS119X_ADD_LOFF_STATP),HEX);
  Serial.print("LOFF STATN");Serial.print(":");
  Serial.println(adc.getRegister(ADS119X_ADD_LOFF_STATN),HEX);
}

/*Esta funcion configura activa el amplificador RLD, activa la referencia interna y
establece los canales usados como escucha para tomar el ruido y devolverlo por referencia
*/
void configurarRLD(){

  adc.sendCommand(ADS119X_CMD_SDATAC); //Primero siempre detener la lectura
  adc.WREG(ADS119X_ADD_CONFIG3,preconfRLDConfig3);
  adc.WREG(ADS119X_ADD_RLD_SENSP,preconfSENSPCH1yCH2);
  adc.WREG(ADS119X_ADD_RLD_SENSN,preconfSENSNCH1yCH2);
  adc.sendCommand(ADS119X_CMD_START); //Siempre continuar conversiones
  adc.sendCommand(ADS119X_CMD_RDATAC); //Siempre leer conversiones

}

void setup() {
  
  Serial.begin(115200);
  prepararADS();
  configurarADS();
  configurarRLD();
  testearADS(testADS,testModeSignalCuadrada); //Si testADS = true no se obtienen muestras EMG
  initEspNow();
  attachInterrupt(digitalPinToInterrupt(dataReady_Pin),dataReadyADS,FALLING);
  Serial.println("===== SISTEMA LISTO =====");
  Serial.print("==========Registros============");
  imprimirRegistros();

}

void loop() {

  if(dataReady){

    dataReady = false; //Cambio estado provocado por la interrupcion
    adc.readChannelData();
    printData();    

  }

  if (flagReset){
    delay(100);
    ESP.restart();    
  }

}