#include <Arduino.h>
#include <SPI.h>
#include <BIOMEC_ADS119X.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <BIOMEC_FiltrosEMG.h>
#define CANAL_ESPNOW 1
#define BATCH 5 //Agrupar 5 muestras (1 muestra/2ms ~ 10ms)
#define N_CHNLS 2 //Cambiamos al numero de canales que necesitemos

//=================CONFIGURACION DEL FILTRADO=================
#define ENVIAR_FILTRADO 1 //1 = envia la señal filtrada en µV | 0 = envia las cuentas crudas del ADS (como antes)
#define DNI 2 //Version del FORMATO del paquete (2 = con modo y diagnostico al final)
#define MODO_CRUDO 0 //Campo modo: data[] son cuentas del ADS sin procesar
#define MODO_FILTRADO 1 //Campo modo: data[] son microvoltios filtrados
#define MODO_ENVOLVENTE 2 //Campo modo: data[] es la envolvente en µV
#define ENVIAR_ENVOLVENTE 1 //1 = envia la envolvente en vez de la señal filtrada (prueba) | 0 = señal filtrada
const float FS_HZ = 500.0f; //Frecuencia de muestreo. DEBE coincidir con adsSPS
const float GANANCIA_NUM = 12.0f; //Ganancia en numero. DEBE coincidir con adsGanancia
const float VREF_V = 2.4f; //Referencia interna del ADS (CONFIG3 = 0xCC -> 2,4 V)
const float UV_POR_CUENTA = (2.0f * VREF_V / GANANCIA_NUM) / 65536.0f * 1e6f; //µV que vale 1 cuenta

const float FC_PASO_ALTO = 20.0f; //Hz. Quita offset y artefactos de movimiento
const float F_NOTCH[] = {50.0f, 100.0f, 150.0f, 200.0f}; //Hz. Red electrica y sus armonicos
const float Q_NOTCH[] = {20.0f, 35.0f, 35.0f, 35.0f}; //Anchura de cada muesca (mas alto = mas estrecha)
const int N_NOTCH = sizeof(F_NOTCH) / sizeof(F_NOTCH[0]); //Cuantos hay (maximo FiltroEMG::MAX_NOTCH)
const float FC_PASO_BAJO = 0.0f; //Hz. 0 = desactivado (el ADS ya corta en ~130 Hz a 500 SPS)
const float FC_ENVOLVENTE = 5.0f; //Hz. Paso bajo de la envolvente (5 Hz: ~48 ms de retardo). 0 = desactivada

const int16_t UMBRAL_SATURACION = 32000; //Cuentas. Por encima se considera que el ADS satura
//=============================================================

//=================NO CAMBIAR EL ORDEN DE LOS CAMPOS DEL STRUCT=================
//Estructura de mi paquete
typedef struct __attribute__((packed)){//__attribute__ es para no meter relleno cuando halla espacios, por seguiridad pero no haría falta
  uint8_t version; //Formato (nos puede ayudar en el futuro)
  uint8_t nChnls; //Nº de canales
  uint8_t batch; //Nº de muestras por paquete
  uint32_t seq; //El numero de paquete
  uint16_t sendFails;//Nº de envios fallidos
  int16_t data[BATCH][N_CHNLS];
  //Campos nuevos (version 2)
  uint8_t modo; //MODO_CRUDO o MODO_FILTRADO
  uint16_t saturaciones; //Contadores ACUMULADOS (como sendFails): el receptor resta
  uint16_t picosCorregidos; //el valor del paquete anterior para saber cuantos hubo.
  uint16_t muestrasPerdidas; //Al ser uint16 dan la vuelta en 65535 y la resta
  uint16_t recortes; //sin signo lo resuelve sola.
} Packet;
//Restricción en envios (tamaño y dirección)
static_assert(sizeof(Packet) <= 250, "El paquete excede la capacidad, reducir BATCH o N_CHNLS");//No compila si el tamaño excede
uint8_t rxMac[]={0xAC,0xEB,0xE6,0x2C,0xD7,0xDC}; //Defino el MAC RECEPTOR C6 como rxMac
//Creación de paquete e iniciación de variables
Packet pkt;
uint8_t idx=0;//contador dentro de pkt
uint32_t seq=0;//nºde paquete
volatile uint16_t sendFails=0;//Los envios fallidos
//=================================================

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
volatile uint32_t contadorDRDY=0;
uint32_t muestrasProcesadas=0;
TaskHandle_t tareaADS = NULL; //Tarea que lee el ADS (la despierta la interrupcion)
//Variables del ADS para hacer test
bool testADS = false;
const byte testModeRuidoInterno = 0x00;
const byte testModeSignalCuadrada = 0x01;
const byte testModeSignalDC = 0x02;
//Variables del ADS para configuracion
const byte N_CHNLS_TOTALES = 0x08;
const byte adsGanancia = ADS119X_CHnSET_GAIN_12;
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

//=================Filtros y estadisticas==========
FiltroEMG filtros[N_CHNLS]; //Un filtro (con su propia memoria) por canal
LimpiadorPicos limpiador(N_CHNLS); //Revisa todos los canales a la vez
bool enviarFiltrado = ENVIAR_FILTRADO; //En modo test se desactiva (ver setup)

uint32_t saturaciones = 0; //Muestras del ADS cerca del limite de ±32767
uint32_t recortesSalida = 0; //Muestras filtradas que no cabian en int16
uint32_t muestrasPerdidas = 0; //Muestras que llegaron sin que loop() pudiera leerlas
//=================================================

//Función para inicializar las ctes del paquete
void initPaquete(){
  pkt.version=DNI;
  pkt.modo= !enviarFiltrado ? MODO_CRUDO : (ENVIAR_ENVOLVENTE ? MODO_ENVOLVENTE : MODO_FILTRADO);
  pkt.nChnls=N_CHNLS; 
  pkt.batch=BATCH;
}
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
  esp_wifi_set_max_tx_power(20); //20 = 5 dBm (unidades de 0,25 dBm; por defecto ~20 dBm)
  esp_now_register_send_cb(onSent);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, rxMac, 6);
  peer.channel = CANAL_ESPNOW;          
  peer.encrypt = false;
  if(esp_now_add_peer(&peer)!=ESP_OK){ESP.restart();}
}

//Configura la cadena de filtros de todos los canales con los valores de arriba
void configurarFiltros(){
  for(int ch=0;ch<N_CHNLS;ch++){
    filtros[ch].iniciar(FS_HZ);
    filtros[ch].pasoAlto(FC_PASO_ALTO);
    for(int k=0;k<N_NOTCH;k++) filtros[ch].notch(F_NOTCH[k], Q_NOTCH[k]);
    if (FC_PASO_BAJO > 0.0f) filtros[ch].pasoBajo(FC_PASO_BAJO);
    if (FC_ENVOLVENTE > 0.0f) filtros[ch].envolvente(FC_ENVOLVENTE);
  }
}

//Convierte un float a int16 redondeando y sin desbordar
int16_t aInt16(float v){
  if (v > 32767.0f){ recortesSalida++; return 32767; }
  if (v < -32768.0f){ recortesSalida++; return -32768; }
  return (int16_t)lroundf(v);
}

//Mete una fila (una muestra de todos los canales) en el paquete y lo envia al llenarse
void guardarEnPaquete(const int16_t *fila){
  for(int ch=0;ch<N_CHNLS;ch++){
    pkt.data[idx][ch]=fila[ch];//Guarda el valor del canal ch en la fila idx del paquete
  }
  if(++idx==BATCH){//Incremento el contador y comparo con el maximo de muestras por paquete
    pkt.seq=seq++; //Registramos el nº del paquete
    pkt.sendFails=sendFails; //Registramos el nº de envios fallidos
    pkt.saturaciones=(uint16_t)saturaciones; //Diagnostico del sensor (se queda con los 16 bits bajos)
    pkt.picosCorregidos=(uint16_t)limpiador.tramasCorregidas();
    pkt.muestrasPerdidas=(uint16_t)muestrasPerdidas;
    pkt.recortes=(uint16_t)recortesSalida;
    esp_now_send(rxMac, (uint8_t*)&pkt, sizeof(pkt));
    idx=0;//Vacio contador
  }
}

//Recojo el valor del ADS en cada canal, lo limpio, lo filtro y lo guardo en el paquete
void procesarMuestra() {
  int16_t crudo[N_CHNLS];
  float entrada[N_CHNLS];
  float limpia[N_CHNLS];
  int16_t fila[N_CHNLS];

  for(int ch=0;ch<N_CHNLS;ch++){
    crudo[ch]=adc.getChannelData(ch);
    if (crudo[ch] >= UMBRAL_SATURACION || crudo[ch] <= -UMBRAL_SATURACION) saturaciones++;
    entrada[ch]=crudo[ch]*UV_POR_CUENTA; //Cuentas -> microvoltios
  }

  if(!enviarFiltrado){ //Modo crudo: igual que el codigo original
    guardarEnPaquete(crudo);
    return;
  }

  if(!limpiador.procesar(entrada, limpia)) return; //Las 2 primeras muestras no tienen salida

  for(int ch=0;ch<N_CHNLS;ch++){
    float y=filtros[ch].procesar(limpia[ch]); //Señal filtrada (y calcula la envolvente)
    fila[ch]=aInt16(ENVIAR_ENVOLVENTE ? filtros[ch].envolventeActual() : y);
  }
  guardarEnPaquete(fila);
}


//=================INTERRUPCIONES==========================
//Interrupcion ADS. DataReady (cada vez que recibo un valor )
void IRAM_ATTR dataReadyADS(){
  contadorDRDY++;
  BaseType_t despertar = pdFALSE;
  vTaskNotifyGiveFromISR(tareaADS, &despertar); //Avisa a la tarea de adquisicion
  portYIELD_FROM_ISR(despertar); //Si tiene mas prioridad que lo que se ejecutaba, pasa a ella ya
}

//=================TAREA DE ADQUISICION====================
//Lee y procesa cada muestra. Tiene mas prioridad que loop(), asi que las pausas
//de loop() (el nucleo Arduino la para ~5 ms cada 2 s) ya no hacen perder muestras.
void tareaAdquisicion(void *param){
  for(;;){
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY); //Duerme hasta que la interrupcion avisa
    uint32_t llegadas = contadorDRDY; //Copia del contador de la interrupcion
    if (llegadas - muestrasProcesadas > 1) muestrasPerdidas += llegadas - muestrasProcesadas - 1;
    muestrasProcesadas = llegadas;
    adc.readChannelData();
    procesarMuestra();
  }
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
  
  // ========== CAMBIO CRÍTICO 1 ==========
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

/*Esta funcion decide si los datos son muestras EMG o señales de prueba.
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
  //Condicion para no filtrar las señales test
  if (testADS) enviarFiltrado = false;
  //
  configurarFiltros();
  initPaquete();
  initEspNow();
  xTaskCreate(tareaAdquisicion, "adquisicion", 4096, NULL, 10, &tareaADS); //Antes de activar la interrupcion
  attachInterrupt(digitalPinToInterrupt(dataReady_Pin),dataReadyADS,FALLING);
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000)); //Todo el trabajo lo hace tareaAdquisicion; loop() solo espera
}