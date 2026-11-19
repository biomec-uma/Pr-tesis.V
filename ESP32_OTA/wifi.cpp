#include <Arduino.h> 
#include <WiFi.h> // 
#include <Update.h> //Biblioteca para descargar y actualizar el binario del maestro (el C6)

const char* ssid = "TU_NOMBRE_DE_RED";
const char* password = "TU_CONTRASEÑA";

void setup(){

      Serial.begin(115200);
      Update.begin();
      delay(10);

      Serial.println();
      Serial.print("Conectando a: ");
      Serial.println(ssid);

      WiFi.begin(ssid, password);
      
      while(WiFi.status() != WL_CONNECTED){
             delay(500);
             Serial.print(".");
      }

      Serial.println("");
      Serial.println("¡Wi-Fi Conectado!");
      Serial.print("Dirección IP: ");
      Serial.println(WiFi.localIP());

}

void loop(){

   Update.write();

     


   //Código a ejecutarse cíclicamente


   Update.end();
    
}