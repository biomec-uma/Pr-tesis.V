// =============================================================================
//  FiltrosEMG.cpp  -  Implementación (ver FiltrosEMG.h)
// =============================================================================
#include "BIOMEC_FiltrosEMG.h"
#include <math.h>

static const float PI_F = 3.14159265358979f;

// Q de las dos secciones de un Butterworth de orden 4: 1/(2·cos(π/8)) y 1/(2·cos(3π/8))
static const float Q_BUTTER4_A = 0.54119610f;
static const float Q_BUTTER4_B = 1.30656296f;
// Q de un Butterworth de orden 2: 1/√2
static const float Q_BUTTER2 = 0.70710678f;

// =============================================================================
//  Biquad
// =============================================================================
Biquad::Biquad() { configurarCoeficientes(1.0f, 0.0f, 0.0f, 0.0f, 0.0f); }

void Biquad::configurarCoeficientes(float b0, float b1, float b2, float a1, float a2) {
  b0_ = b0; b1_ = b1; b2_ = b2; a1_ = a1; a2_ = a2;
  reiniciar();
}

void Biquad::reiniciar() { z1_ = 0.0f; z2_ = 0.0f; }

// Notch: mismas fórmulas que scipy.signal.iirnotch
// (con f0 = 50, Q = 35, fs = 500 da exactamente los coeficientes de la app).
bool Biquad::configurarNotch(float f0, float Q, float fs) {
  if (f0 <= 0.0f || f0 >= fs / 2.0f || Q <= 0.0f) return false;
  float w0 = 2.0f * PI_F * f0 / fs;
  float bw = w0 / Q;
  float beta = tanf(bw / 2.0f);
  float g = 1.0f / (1.0f + beta);
  float c = cosf(w0);
  configurarCoeficientes(g, -2.0f * g * c, g, -2.0f * g * c, 2.0f * g - 1.0f);
  return true;
}

// Paso alto y paso bajo: fórmulas del "Audio EQ Cookbook" (R. Bristow-Johnson).
bool Biquad::configurarPasoAlto(float fc, float Q, float fs) {
  if (fc <= 0.0f || fc >= fs / 2.0f || Q <= 0.0f) return false;
  float w0 = 2.0f * PI_F * fc / fs;
  float c = cosf(w0);
  float alpha = sinf(w0) / (2.0f * Q);
  float a0 = 1.0f + alpha;
  configurarCoeficientes(((1.0f + c) / 2.0f) / a0, -(1.0f + c) / a0, ((1.0f + c) / 2.0f) / a0,
                         (-2.0f * c) / a0, (1.0f - alpha) / a0);
  return true;
}

bool Biquad::configurarPasoBajo(float fc, float Q, float fs) {
  if (fc <= 0.0f || fc >= fs / 2.0f || Q <= 0.0f) return false;
  float w0 = 2.0f * PI_F * fc / fs;
  float c = cosf(w0);
  float alpha = sinf(w0) / (2.0f * Q);
  float a0 = 1.0f + alpha;
  configurarCoeficientes(((1.0f - c) / 2.0f) / a0, (1.0f - c) / a0, ((1.0f - c) / 2.0f) / a0,
                         (-2.0f * c) / a0, (1.0f - alpha) / a0);
  return true;
}

// =============================================================================
//  FiltroEMG
// =============================================================================
FiltroEMG::FiltroEMG()
    : fs_(500.0f), nNotch_(0), pasoAltoActivo_(false), pasoBajoActivo_(false),
      primera_(true), offset0_(0.0f) {}

void FiltroEMG::iniciar(float fs) {
  fs_ = fs;
  pasoAltoActivo_ = pasoBajoActivo_ = false;
  nNotch_ = 0;
  primera_ = true;
}

bool FiltroEMG::pasoAlto(float fc) {
  bool ok = pasoAlto_[0].configurarPasoAlto(fc, Q_BUTTER4_A, fs_) &&
            pasoAlto_[1].configurarPasoAlto(fc, Q_BUTTER4_B, fs_);
  pasoAltoActivo_ = ok;
  return ok;
}

bool FiltroEMG::notch(float f0, float Q) {
  // Si ya hay un notch en esa frecuencia, solo se reajusta (por ejemplo, otra Q)
  for (uint8_t i = 0; i < nNotch_; i++) {
    if (fabsf(fNotch_[i] - f0) < 0.01f) return notch_[i].configurarNotch(f0, Q, fs_);
  }
  if (nNotch_ >= MAX_NOTCH) return false;                     // no caben más
  if (!notch_[nNotch_].configurarNotch(f0, Q, fs_)) return false;  // frecuencia no válida
  fNotch_[nNotch_] = f0;
  nNotch_++;
  return true;
}

bool FiltroEMG::pasoBajo(float fc) {
  bool ok = pasoBajo_.configurarPasoBajo(fc, Q_BUTTER2, fs_);
  pasoBajoActivo_ = ok;
  return ok;
}

bool FiltroEMG::pasaBanda(float fBaja, float fAlta) {
  if (fBaja >= fAlta) return false;
  return pasoAlto(fBaja) && pasoBajo(fAlta);
}

void FiltroEMG::quitarPasoAlto() { pasoAltoActivo_ = false; }
void FiltroEMG::quitarNotch() { nNotch_ = 0; }
void FiltroEMG::quitarPasoBajo() { pasoBajoActivo_ = false; }

void FiltroEMG::reiniciar() {
  pasoAlto_[0].reiniciar();
  pasoAlto_[1].reiniciar();
  for (uint8_t i = 0; i < MAX_NOTCH; i++) notch_[i].reiniciar();
  pasoBajo_.reiniciar();
  primera_ = true;
}

float FiltroEMG::procesar(float x) {
  // La primera muestra se toma como offset y se resta siempre. El paso alto
  // quitaría ese offset igualmente, pero partiendo de cero daría un salto enorme
  // al arrancar (respuesta al escalón). Restarlo evita ese transitorio.
  if (primera_) { offset0_ = x; primera_ = false; }
  float y = x - offset0_;
  if (pasoAltoActivo_) {
    y = pasoAlto_[0].procesar(y);
    y = pasoAlto_[1].procesar(y);
  }
  for (uint8_t i = 0; i < nNotch_; i++) y = notch_[i].procesar(y);
  if (pasoBajoActivo_) y = pasoBajo_.procesar(y);
  return y;
}

// =============================================================================
//  LimpiadorPicos
// =============================================================================
static const float ALFA_NIVEL = 0.01f;          // velocidad de adaptación (~100 muestras)
static const uint32_t TRAMAS_APRENDIZAJE = 250; // 0,5 s a 500 Hz sin corregir

LimpiadorPicos::LimpiadorPicos(uint8_t nCanales, float factor, float suelo)
    : n_(nCanales > MAX_CANALES ? MAX_CANALES : nCanales), factor_(factor), suelo_(suelo) {
  reiniciar();
}

void LimpiadorPicos::reiniciar() {
  for (uint8_t c = 0; c < MAX_CANALES; c++) {
    prev2_[c] = prev1_[c] = nivel_[c] = 0.0f;
  }
  tramas_ = 0;
  corregidas_ = 0;
}

bool LimpiadorPicos::procesar(const float* entrada, float* salida) {
  // Las dos primeras tramas solo se guardan: aún no hay vecinas para comparar.
  if (tramas_ < 2) {
    for (uint8_t c = 0; c < n_; c++) {
      prev2_[c] = prev1_[c];
      prev1_[c] = entrada[c];
    }
    tramas_++;
    return false;
  }

  // ¿La trama anterior (prev1) es un pico? Se compara con la media de sus vecinas,
  // y solo cuenta si las dos vecinas coinciden entre sí (si la vecina siguiente es
  // la que está mal, no se marca esta: se marcará en la siguiente llamada).
  bool esPico = false;
  float desvio[MAX_CANALES];
  for (uint8_t c = 0; c < n_; c++) {
    float media = 0.5f * (prev2_[c] + entrada[c]);
    desvio[c] = fabsf(prev1_[c] - media);
    float umbral = factor_ * nivel_[c] + suelo_;
    bool vecinasCoinciden = fabsf(entrada[c] - prev2_[c]) < umbral;
    if (tramas_ > TRAMAS_APRENDIZAJE && desvio[c] > umbral && vecinasCoinciden) esPico = true;
  }

  for (uint8_t c = 0; c < n_; c++) {
    if (esPico) prev1_[c] = 0.5f * (prev2_[c] + entrada[c]);  // sustituye la trama entera
    salida[c] = prev1_[c];

    // Actualiza el nivel típico del canal. Se limita al umbral para que un pico
    // no lo dispare, pero sin congelarlo (si la señal crece de verdad, el nivel la sigue).
    float umbral = factor_ * nivel_[c] + suelo_;
    float d = desvio[c] < umbral ? desvio[c] : umbral;
    nivel_[c] += ALFA_NIVEL * (d - nivel_[c]);

    prev2_[c] = prev1_[c];
    prev1_[c] = entrada[c];
  }
  if (esPico) corregidas_++;
  tramas_++;
  return true;
}
