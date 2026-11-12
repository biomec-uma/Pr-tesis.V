// =====================================================================
//  BIOMEC UMA · Bucle para exposiciones (ESP32-WROOM de la mano)
//
//  Sin radio ni app: al encender recorre los 8 gestos (3 s moviendo y
//  3 s parando), como el código original pero con el core esp32 3.x.
//  Comprobado en la mano real (09/11/2026).
//
//  - Para exponer la mano sin ordenador.
//  - Para descartar el hardware: si con firmware/mano no se mueve y con
//    este sí, el problema está en el firmware.
//  firmware/mano hace lo mismo en modo AUTO (al encender) y además
//  obedece a la app.  Arduino IDE: "ESP32 Dev Module", ESP32Servo >= 3.0
// =====================================================================
#include <ESP32Servo.h> //Para el servo
#define N 8 // Número de posiciones
hw_timer_t*timer=NULL;
volatile int Estado;
const int top=N*2;//Si son 8 posiciones ~ 16 pasos

// 1 posicion = activacion + parada = 2 estados
// Activaciones del motor en el numero par y parada de motor como impar de la serie

// 1º Abrir todos
// 2º Paz (cerrar anular)
// 3º jeje (+ cerrar indice)
// 4º Rock (abrir anular + indice y cerrar medio)
// 5º Gesto Austriaco (+abrir medio y cerrar pulgar)
// 6º Nº1 (cerrar anular + medio)
// 7º PiumPium (+ abrir pulgar)
// 8º "Heterobasico" (cerrar indice)

// Control de rampa (arranque/parada suaves)
int estadoAnterior = -1;              // Para detectar cuándo cambia Estado
unsigned long tiempoInicioEstado = 0; // millis() en el que empezó el estado actual
unsigned long tiempoEnEstado = 0;     // Tiempo transcurrido dentro del estado actual
const unsigned long duracionRampa = 500; // Duración de la rampa en ms (0,5s)

// VALORES PWM
// En el core ESP32 3.x ledcAttach() asigna el canal automáticamente
// y ledcWrite()/ledcRead() trabajan directamente con el PIN
const int freq = 15000;   // frecuencia
const int resolucion = 8; // 8 bits -> valores entre 0-255

// --- MOTORES DC (Dedo Medio y Anular/Meñique) ---
const int medioA = 25, medioB = 26;
const int anularA = 18, anularB = 17;
const int indiceA = 32, indiceB = 33;

//DECLARO SERVO Y OBJETO MOTOR
Servo pulgar_S;       // Pulgar (s)
const int pinS = 19;  // Pin para el pulgar

struct Motor {
  int pinA;
  int pinB;
};

Motor indice = { indiceA, indiceB };
Motor medio  = { medioA,  medioB  };
Motor anular = { anularA, anularB };

void IRAM_ATTR CambioDeEstado() {
  if (Estado<top-1){
    Estado++;
  }else if (Estado==top-1){
    Estado=0;
  }
}

void ConfiguracionDeMotores(){
  pulgar_S.attach(pinS);

  // ledcAttach(pin, frecuencia, resolución): configura el canal y lo asocia al pin
  ledcAttach(indiceA, freq, resolucion);
  ledcAttach(indiceB, freq, resolucion);
  ledcAttach(medioA,  freq, resolucion);
  ledcAttach(medioB,  freq, resolucion);
  ledcAttach(anularA, freq, resolucion);
  ledcAttach(anularB, freq, resolucion);
}

// Funciones para los motores DC
void cerrarDedo(Motor &motor) {
  // constrain limita tiempoEnEstado entre 0 y duracionRampa
  // map reescala ese tiempo a un duty entre 0 y 255 (rampa de subida)
  unsigned long t=constrain(tiempoEnEstado,0UL, duracionRampa);
  int duty=map(t,0,duracionRampa,0,255);

  ledcWrite(motor.pinA, 0);
  ledcWrite(motor.pinB, duty);
}

void abrirDedo(Motor &motor) {
  unsigned long t=constrain(tiempoEnEstado,0UL,duracionRampa);
  int duty=map(t,0,duracionRampa,0,255);

  ledcWrite(motor.pinA, duty);
  ledcWrite(motor.pinB, 0);
}

void pararDedo(Motor &motor){
  unsigned long t=constrain(tiempoEnEstado,0UL,duracionRampa);
  int duty=map(t,0,duracionRampa,255,0);//Rampa de bajada
  // Si previamente estaba en movimiento reduzco la velocidad hasta 0; si ya estaba parado no hago nada
  if(ledcRead(motor.pinA)>0) {
    ledcWrite(motor.pinA,duty);
  }
  if(ledcRead(motor.pinB)>0) {
    ledcWrite(motor.pinB,duty);
  }
}


void setup() {
  Serial.begin(115200);

  ConfiguracionDeMotores();//La configuración de los motores y servo
  Estado=0;//Inicializo la variable estado para que empieze abriendo la mano

  // Core 3.x: timerBegin recibe la frecuencia directamente (1 MHz -> 1 tick = 1 microsegundo)
  timer = timerBegin(1000000);
  timerAttachInterrupt(timer, &CambioDeEstado);
  // 3.000.000 us = 3 segundos, autoreload activado, 0 = reload infinito
  // timerAlarm ya habilita el timer (sustituye a timerAlarmWrite + timerAlarmEnable)
  timerAlarm(timer, 3000000, true, 0);
}

void loop(){
  if(Estado!=estadoAnterior){//Si cambio de estado reinicio el cronometro
    tiempoInicioEstado=millis();
    estadoAnterior=Estado;
  }
  tiempoEnEstado=millis()-tiempoInicioEstado; //El tiempo que lleva en un estado del switch
  switch (Estado){
    case 0: //Abrir todos
      pulgar_S.write(10);
      abrirDedo(indice);
      abrirDedo(medio);
      abrirDedo(anular);
      break;
    case 2: //Paz (cerrar anular)
      cerrarDedo(anular);
      break;
    case 4: //Rock (abrir anular y cerrar medio)
      cerrarDedo(medio);
      abrirDedo(anular);
      break;
    case 6: //jeje (cerrar indice + anular y abrir medio)
      cerrarDedo(anular);
      cerrarDedo(indice);
      abrirDedo(medio);
      break;
    case 8: //PiumPium
      cerrarDedo(medio);
      abrirDedo(indice);
      break;
    case 10: //Adan
      pulgar_S.write(90);//Se podría poner 180 grados
      break;
    case 12: //Gesto Austriaco
      abrirDedo(medio);
      abrirDedo(anular);
      break;
    case 14: //"Heterobasico" (cerrar indice)
      pulgar_S.write(10);
      cerrarDedo(indice);
      cerrarDedo(medio);
      cerrarDedo(anular);
      break;

    default: //STOP engine
      pararDedo(indice);
      pararDedo(medio);
      pararDedo(anular);
      break;
  }
}