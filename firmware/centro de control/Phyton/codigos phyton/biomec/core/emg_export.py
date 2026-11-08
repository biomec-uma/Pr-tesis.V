"""Exporta un modelo EMG entrenado a una cabecera C (.h) para la ESP32.

Es el paso de "IA embebida": el mismo clasificador que funciona en la app,
pero dentro de la placa, sin PC. La cabecera es autocontenida (solo math.h):
filtros, características de Hudgins, LDA y voto por mayoría, con los mismos
números que core/emg.py.

    #include "biomec_emg_modelo.h"
    BiomecEmg emg;
    int k = emg.muestra(canales);   // cada muestra del ADS1198 (int16 por canal)
    if (k >= 0) { ... BIOMEC_EMG_CLASES[k] ... emg.confianza ... }
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

import numpy as np

from .emg import EmgModel, Preprocessor


def _floats(values, per_line: int = 6, indent: str = "  ") -> str:
    vals = [f"{float(v):.9g}f" for v in np.ravel(values)]
    lines = [", ".join(vals[i:i + per_line]) for i in range(0, len(vals), per_line)]
    return (",\n" + indent).join(lines)


def _c_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def c_identifier(text: str) -> str:
    """'Abrir mano' -> 'ABRIR_MANO' (sin tildes), para usarlo como constante en C."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    ident = re.sub(r"[^A-Za-z0-9]+", "_", plain).strip("_").upper()
    return ident if ident and not ident[0].isdigit() else f"M_{ident}"


def export_c_header(model: EmgModel) -> str:
    pre = Preprocessor(model.fs, 1, model.config.filters)
    sos = [[s.b[0], s.b[1], s.b[2], s.a[1], s.a[2]] for s in pre.stages]
    lda = model.lda
    K, D = lda.W.shape
    acc = f"{model.report.accuracy * 100:.0f} % ({model.report.method})" if model.report else "sin evaluar"
    names = ", ".join(_c_string(c) for c in model.classes)
    enum = "\n".join(f"  BIOMEC_EMG_{c_identifier(c)} = {i}," for i, c in enumerate(model.classes))
    cfg = model.config
    filters = f"paso alto {cfg.filters.highpass_hz:g} Hz (4º orden)" + (
        f" + notch {cfg.filters.notch_hz:g} Hz" if len(sos) > 2 else "")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""#pragma once
// =====================================================================
//  BIOMEC UMA · Modelo EMG para la ESP32 (generado por BIOMEC Control, {stamp})
//
//  Clasificador LDA con características de Hudgins (MAV, WL, ZC, SSC),
//  idéntico al de la app (biomec/core/emg.py).
//  Movimientos ({K}): {", ".join(f"{i} = {c}" for i, c in enumerate(model.classes))}
//  Precisión estimada: {acc}
//  {model.channels} canales a {model.fs} Hz · ventana {cfg.window_ms} ms cada {cfg.step_ms} ms · voto de {cfg.vote}
//  Filtros: {filters}
//
//  Uso:
//    #include "biomec_emg_modelo.h"
//    BiomecEmg emg;                              // estado del clasificador
//    void nuevaMuestra(const int16_t* canales) {{ // una muestra de cada canal (cuentas del ADC)
//      int k = emg.muestra(canales);             // -1 = todavía no hay decisión nueva
//      if (k >= 0) Serial.printf("%s (%.0f %%)\\n", BIOMEC_EMG_CLASES[k], emg.confianza * 100);
//    }}
//  Coste: {K}x{D} multiplicaciones cada {cfg.step_ms} ms. Memoria: {model.window}x{model.channels} floats.
//  ¡Si cambias el número de canales o la frecuencia de muestreo, vuelve a entrenar y exportar!
// =====================================================================
#include <math.h>
#include <stdint.h>
#include <string.h>

#define BIOMEC_EMG_CANALES {model.channels}
#define BIOMEC_EMG_N_CLASES {K}
#define BIOMEC_EMG_FS {model.fs}
#define BIOMEC_EMG_VENTANA {model.window}
#define BIOMEC_EMG_PASO {model.step}
#define BIOMEC_EMG_VOTO {max(cfg.vote, 1)}
#define BIOMEC_EMG_N_CARAC {D}
#define BIOMEC_EMG_N_SOS {len(sos)}

enum BiomecEmgClase {{
{enum}
}};

static const char* const BIOMEC_EMG_CLASES[BIOMEC_EMG_N_CLASES] = {{{names}}};

// Biquads en cascada (forma directa II transpuesta): b0, b1, b2, a1, a2
static const float BIOMEC_EMG_SOS[BIOMEC_EMG_N_SOS][5] = {{
  {",\n  ".join("{" + _floats(s, 5, "") + "}" for s in sos)}
}};

// Umbral de ruido de cada canal para ZC y SSC
static const float BIOMEC_EMG_UMBRAL[BIOMEC_EMG_CANALES] = {{
  {_floats(model.thr)}
}};

// Estandarización de las características: z = (x - media) * escala
static const float BIOMEC_EMG_MEDIA[BIOMEC_EMG_N_CARAC] = {{
  {_floats(lda.mu)}
}};
static const float BIOMEC_EMG_ESCALA[BIOMEC_EMG_N_CARAC] = {{
  {_floats(1.0 / lda.sd)}
}};

// LDA: g_k = W_k · z + b_k ; gana la mayor
static const float BIOMEC_EMG_W[BIOMEC_EMG_N_CLASES][BIOMEC_EMG_N_CARAC] = {{
  {",\n  ".join("{" + _floats(row, 8, "   ") + "}" for row in lda.W)}
}};
static const float BIOMEC_EMG_B[BIOMEC_EMG_N_CLASES] = {{
  {_floats(lda.b)}
}};

struct BiomecEmg {{
  float z1[BIOMEC_EMG_N_SOS][BIOMEC_EMG_CANALES];
  float z2[BIOMEC_EMG_N_SOS][BIOMEC_EMG_CANALES];
  float dc[BIOMEC_EMG_CANALES];
  float ventana[BIOMEC_EMG_VENTANA][BIOMEC_EMG_CANALES];  // circular, ya filtrada
  uint32_t n;                                              // muestras recibidas
  int votos[BIOMEC_EMG_VOTO];
  int nVotos;
  float prob[BIOMEC_EMG_N_CLASES];                         // probabilidades de la última ventana
  float confianza;                                         // probabilidad del movimiento elegido

  BiomecEmg() {{ reiniciar(); }}

  void reiniciar() {{
    memset(this, 0, sizeof(*this));
  }}

  // Una muestra de cada canal. Devuelve el movimiento decidido (0..N_CLASES-1)
  // cada BIOMEC_EMG_PASO muestras, o -1 entre medias.
  int muestra(const int16_t* x) {{
    int pos = n % BIOMEC_EMG_VENTANA;
    for (int c = 0; c < BIOMEC_EMG_CANALES; c++) {{
      if (n == 0) dc[c] = x[c];  // se resta el offset inicial para que el filtro no arranque con un escalón
      float v = (float)x[c] - dc[c];
      for (int s = 0; s < BIOMEC_EMG_N_SOS; s++) {{
        const float* k = BIOMEC_EMG_SOS[s];
        float y = k[0] * v + z1[s][c];
        z1[s][c] = k[1] * v - k[3] * y + z2[s][c];
        z2[s][c] = k[2] * v - k[4] * y;
        v = y;
      }}
      ventana[pos][c] = v;
    }}
    n++;
    if (n % BIOMEC_EMG_PASO != 0 || n < BIOMEC_EMG_VENTANA) return -1;
    return clasificar();
  }}

  int clasificar() {{
    const int N = BIOMEC_EMG_VENTANA;
    const int inicio = n % N;  // muestra más antigua de la ventana
    float f[BIOMEC_EMG_N_CARAC];
    for (int c = 0; c < BIOMEC_EMG_CANALES; c++) {{
      const float thr = BIOMEC_EMG_UMBRAL[c];
      float prev = ventana[inicio][c];
      float mav = fabsf(prev), wl = 0, dPrev = 0;
      int zc = 0, ssc = 0;
      for (int i = 1; i < N; i++) {{
        float x = ventana[(inicio + i) % N][c];
        float d = x - prev, ad = fabsf(d);
        mav += fabsf(x);
        wl += ad;
        if (prev * x < 0 && ad >= thr) zc++;
        if (i >= 2 && dPrev * -d > 0 && (fabsf(dPrev) >= thr || ad >= thr)) ssc++;  // pico o valle en x[i-1]
        dPrev = d;
        prev = x;
      }}
      f[4 * c + 0] = logf(mav / N + 1e-3f);
      f[4 * c + 1] = logf(wl / N + 1e-3f);
      f[4 * c + 2] = (float)zc / N;
      f[4 * c + 3] = (float)ssc / N;
    }}
    float g[BIOMEC_EMG_N_CLASES], gmax = -1e30f;
    int k = 0;
    for (int j = 0; j < BIOMEC_EMG_N_CLASES; j++) {{
      float s = BIOMEC_EMG_B[j];
      for (int i = 0; i < BIOMEC_EMG_N_CARAC; i++)
        s += BIOMEC_EMG_W[j][i] * (f[i] - BIOMEC_EMG_MEDIA[i]) * BIOMEC_EMG_ESCALA[i];
      g[j] = s;
      if (s > gmax) {{ gmax = s; k = j; }}
    }}
    float suma = 0;
    for (int j = 0; j < BIOMEC_EMG_N_CLASES; j++) {{ prob[j] = expf(g[j] - gmax); suma += prob[j]; }}
    for (int j = 0; j < BIOMEC_EMG_N_CLASES; j++) prob[j] /= suma;
    // voto por mayoría de las últimas decisiones (empate: la más reciente)
    if (nVotos < BIOMEC_EMG_VOTO) votos[nVotos++] = k;
    else {{
      memmove(votos, votos + 1, sizeof(int) * (BIOMEC_EMG_VOTO - 1));
      votos[BIOMEC_EMG_VOTO - 1] = k;
    }}
    int mejor = k, mejorN = 0;
    for (int a = nVotos - 1; a >= 0; a--) {{
      int cuenta = 0;
      for (int b = 0; b < nVotos; b++) cuenta += votos[b] == votos[a];
      if (cuenta > mejorN) {{ mejorN = cuenta; mejor = votos[a]; }}
    }}
    confianza = prob[mejor];
    return mejor;
  }}
}};
"""
