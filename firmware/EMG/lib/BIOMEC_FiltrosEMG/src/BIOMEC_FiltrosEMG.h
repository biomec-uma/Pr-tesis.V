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
//  Peine (comb notch IIR): quita f0 y todos sus armónicos (2·f0, 3·f0...) con
//  un solo filtro y ~4 operaciones por muestra.
//    y[n] = k·(x[n] - x[n-N]) + R·y[n-N],   N = fs/f0,   k = (1+R)/2
//  Implementado con un solo buffer: w[n] = x[n] + R·w[n-N];  y[n] = k·(w[n] - w[n-N])
//  - fs/f0 debe ser entero (500/50 = 10, 1000/50 = 20).
//  - R (0..1) hace de Q: más cerca de 1 = muescas más estrechas pero más lentas
//    en asentarse. 0,9 -> muesca de 50 Hz de ~1,7 Hz de ancho, asienta en ~0,6 s.
//  - También pone una muesca en 0 Hz (no sustituye al paso alto).
// -----------------------------------------------------------------------------
class Peine {
public:
  static const uint8_t MAX_RETARDO = 40;  // N máximo (p. ej. 2000 SPS / 50 Hz)

  Peine();

  // Devuelve false si fs/f0 no es entero, N no cabe o R no está entre 0 y 1.
  bool configurar(float f0, float R, float fs);
  void reiniciar();

  inline float procesar(float x) {
    float wViejo = w_[pos_];          // w[n-N]
    float w = x + R_ * wViejo;        // w[n]
    w_[pos_] = w;                     // se guarda en el hueco que se acaba de leer
    if (++pos_ >= N_) pos_ = 0;
    return k_ * (w - wViejo);
  }

private:
  float w_[MAX_RETARDO];  // últimos N valores de w (buffer circular)
  uint8_t N_, pos_;
  float R_, k_;
};

// -----------------------------------------------------------------------------
//  FiltroEMG: cadena de filtros para UN canal.
//  Orden fijo de procesado: paso alto -> notch -> paso bajo.
//  Cada etapa se activa al configurarla y se puede desactivar.
// -----------------------------------------------------------------------------
class FiltroEMG {
public:
  static const uint8_t MAX_NOTCH = 4;
  FiltroEMG();

  void iniciar(float fs);                // fs = frecuencia de muestreo (Hz)

  bool pasoAlto(float fc);               // Butterworth orden 4 (2 biquads)
  bool notch(float f0, float Q = 35.0f); // notch de 2º orden
  bool peine(float f0 = 50.0f, float R = 0.9f);  // quita f0 y todos sus armónicos (alternativa a varios notch)
  bool pasoBajo(float fc);               // Butterworth orden 2 (1 biquad)
  bool pasaBanda(float fBaja, float fAlta);  // = pasoAlto(fBaja) + pasoBajo(fAlta)

  void quitarPasoAlto();
  void quitarNotch();
  void quitarPeine();
  void quitarPasoBajo();
  bool envolvente(float fc = 5.0f);      // activa la envolvente: |señal| + paso bajo de fc Hz
  void quitarEnvolvente();
  float envolventeActual() const { return env_; }  // envolvente de la última muestra procesada

  void reiniciar();                      // vacía la memoria de todas las etapas
  float procesar(float x);               // filtra UNA muestra

private:
  float fs_;
  Biquad pasoAlto_[2];
  Biquad notch_[MAX_NOTCH];
  float fNotch_[MAX_NOTCH]; 
  uint8_t nNotch_;
  Peine peine_;
  bool peineActivo_;
  Biquad pasoBajo_;
  bool pasoAltoActivo_, pasoBajoActivo_;
  Biquad envolvente_;        // paso bajo de la envolvente
  bool envolventeActiva_;
  float env_;                // último valor de la envolvente
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
