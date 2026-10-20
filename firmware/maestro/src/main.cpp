#include <WiFi.h>
#include <esp_now.h>

#define BATCH 20 //Agrupar 20 muestras (1 muestra/2ms ~ 40ms)
#define N_CHNLS 2 //Cambiamos al numero de canales que necesitemos

typedef struct __attribute__((packed)){//__attribute__ es para no meter relleno cuando halla espacios, en este caso no lo haría porque el tamaño es el justo
  uint16_t seq;
  int16_t data[BATCH][N_CHNLS];
} packet;

packet receivedPacket;

//Variables globales
volatile bool newPacket = false;
volatile uint16_t packetCount = 0;
volatile uint16_t invalidPackets = 0;

void onDataReceived(const esp_now_recv_info_t *info, const uint8_t *incomingData, int len){

  if (len != sizeof(packet)){
    invalidPackets++;
  }else{
    memcpy(&receivedPacket, incomingData, sizeof(packet));
    packetCount++;
    newPacket = true;
  }
}

void imprimirMAC(){
  Serial.print("MAC del receptor: ");
  Serial.println(WiFi.macAddress());
}

void comprobarEspNow(){
  if(esp_now_init() != ESP_OK){
    Serial.println("Error inicializando ESP-NOW");
    ESP.restart();
  }
}

void llamarTrasRecibirPaquete(esp_now_recv_cb_t funcion){
  esp_now_register_recv_cb(funcion);
}

void initEspNow(){

  WiFi.mode(WIFI_STA);
  imprimirMAC();
  comprobarEspNow();
  llamarTrasRecibirPaquete(onDataReceived);
  Serial.println("Receptor ESP-NOW listo");

}

void imprimePaquete(packet paquete){

  for(int i=0; i<BATCH; i++){

    for(int j=0; j<N_CHNLS; j++){
      if(j>0){
        Serial.print('\t'); 
      }
      Serial.print(paquete.data[i][j]);
    }
    Serial.println();
  }
}

void setup(){
  Serial.begin(115200);
  delay(1000); //espera a que ESP y puerto serie se inicialicen
  initEspNow();
}

void loop(){
  int cadaXmuestras = 0;
  static int fila = 0;
  static int columna = 0;

  if(newPacket){ //Recibimos y lo procesamos
    noInterrupts(); //Desabilita interrupciones
    packet packetToProcess = receivedPacket;
    newPacket = false;
    interrupts(); //Recibido, reactivar interrupciones
    imprimePaquete(packetToProcess);
  }  

}