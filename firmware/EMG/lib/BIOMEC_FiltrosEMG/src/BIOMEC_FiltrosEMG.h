// =============================================================================
//  FiltrosEMG.h  -  Filtrado digital en tiempo real para señales EMG (ESP32)
// -----------------------------------------------------------------------------
//  Tres piezas:
//    - Biquad:          filtro IIR de 2º orden (la pieza base de todo).
//    - FiltroEMG:       cadena de filtros de UN canal (paso alto, notch, paso bajo).
//    - LimpiadorPicos:  quita muestras sueltas corruptas (fallos de lectura SPI)
//                       mirando todos los canales a la vez.
//  No depende de Arduino: solo usa <stdint.h> y <math.h>.
//  Trabaja en float (en ESP32-C3/C6 sin FPU se emula, pero el coste es pequeño).
// =============================================================================
#ifndef BIOMEC_FILTROS_EMG_H
#define BIOMEC_FILTROS_EMG_H

#include <stdint.h>

// -----------------------------------------------------------------------------
//  Biquad: y[n] = b0·x[n] + b1·x[n-1] + b2·x[n-2] - a1·y[n-1] - a2·y[n-2]
//  Implementado en "Direct Form II Transposed" (solo 2 variables de estado).
// -----------------------------------------------------------------------------
class Biquad {
public:
  Biquad();

  // Calculan los coeficientes. Devuelven false si la frecuencia no es válida
  // (debe estar entre 0 y fs/2) y en ese caso no cambian nada.
  bool configurarNotch(float f0, float Q, float fs);     // elimina f0
  bool configurarPasoAlto(float fc, float Q, float fs);  // deja pasar > fc
  bool configurarPasoBajo(float fc, float Q, float fs);  // deja pasar < fc

  // Por si quieres meter a mano coeficientes de otra herramienta (a0 = 1).
  void configurarCoeficientes(float b0, float b1, float b2, float a1, float a2);

  void reiniciar();  // pone a 0 la memoria del filtro

  // Filtra UNA muestra. Se llama una vez por muestra, siempre en orden.
  inline float procesar(float x) {
    float y = b0_ * x + z1_;
    z1_ = b1_ * x - a1_ * y + z2_;
    z2_ = b2_ * x - a2_ * y;
    return y;
  }

private:
  float b0_, b1_, b2_, a1_, a2_;  // coeficientes
  float z1_, z2_;                 // estado (memoria)
};

// -----------------------------------------------------------------------------
//  FiltroEMG: cadena de filtros para UN canal.
//  Orden fijo de procesado: paso alto -> notch -> paso bajo.
//  Cada etapa se activa al configurarla y se puede desactivar.
// -----------------------------------------------------------------------------
class FiltroEMG {
public:
  FiltroEMG();

  void iniciar(float fs);                // fs = frecuencia de muestreo (Hz)

  bool pasoAlto(float fc);               // Butterworth orden 4 (2 biquads)
  bool notch(float f0, float Q = 35.0f); // notch de 2º orden
  bool pasoBajo(float fc);               // Butterworth orden 2 (1 biquad)
  bool pasaBanda(float fBaja, float fAlta);  // = pasoAlto(fBaja) + pasoBajo(fAlta)

  void quitarPasoAlto();
  void quitarNotch();
  void quitarPasoBajo();

  void reiniciar();                      // vacía la memoria de todas las etapas
  float procesar(float x);               // filtra UNA muestra

private:
  float fs_;
  Biquad pasoAlto_[2];
  Biquad notch_;
  Biquad pasoBajo_;
  bool pasoAltoActivo_, notchActivo_, pasoBajoActivo_;
  bool primera_;      // true hasta recibir la primera muestra
  float offset0_;     // valor de la primera muestra (evita el salto inicial)
};

// -----------------------------------------------------------------------------
//  LimpiadorPicos: detecta TRAMAS (todos los canales de un instante) corruptas.
//  Una muestra es sospechosa si se aleja mucho de la media de su anterior y su
//  siguiente (segunda diferencia). El umbral se adapta a la actividad de cada
//  canal: umbral = factor · nivelTipico + suelo.
//  Si cualquier canal es sospechoso, se sustituye la trama entera por la media
//  de sus vecinas (el fallo afecta a todos los canales a la vez).
//  Coste: la salida sale con 1 muestra de retraso (2 ms a 500 Hz).
// -----------------------------------------------------------------------------
class LimpiadorPicos {
public:
  static const uint8_t MAX_CANALES = 8;

  // factor y suelo en las MISMAS unidades que la señal de entrada (aquí µV).
  // Valores por defecto ajustados con las grabaciones del 18/11/2026.
  LimpiadorPicos(uint8_t nCanales, float factor = 12.0f, float suelo = 300.0f);

  // entrada: trama nueva. salida: trama anterior ya revisada.
  // Devuelve false mientras no hay salida válida (las 2 primeras tramas).
  bool procesar(const float* entrada, float* salida);

  uint32_t tramasCorregidas() const { return corregidas_; }
  void reiniciar();

private:
  uint8_t n_;
  float factor_, suelo_;
  float prev2_[MAX_CANALES], prev1_[MAX_CANALES], nivel_[MAX_CANALES];
  uint32_t tramas_;
  uint32_t corregidas_;
};

#endif  // BIOMEC_FILTROS_EMG_H
