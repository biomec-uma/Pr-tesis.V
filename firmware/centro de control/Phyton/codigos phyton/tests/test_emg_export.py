"""El modelo exportado a C (.h) decide igual que el clasificador de la app.

No hay compilador de C en el PC de pruebas, así que se leen los números del
.h y se ejecuta el MISMO algoritmo que el código C, traducido línea a línea.
(Que el .h compila para la ESP32 se comprueba aparte con arduino-cli.)
"""

import math
import re
import unittest

import numpy as np

from biomec.core.emg import REST, RealtimeDecoder, train_model
from biomec.core.emg_export import c_identifier, export_c_header
from biomec.core.emg_sim import VirtualPatient
from tests.test_emg import guided_recording


def parse_header(text: str) -> dict:
    out = {k: int(v) for k, v in re.findall(r"#define (BIOMEC_EMG_\w+) (\d+)", text)}
    for name, body in re.findall(r"static const float (BIOMEC_EMG_\w+)\[[^=]*=\s*\{(.*?)\};", text, re.S):
        out[name] = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?(?=f)", body)]
    out["CLASES"] = re.findall(r'"([^"]*)"', re.search(r"BIOMEC_EMG_CLASES\[[^=]*=\s*\{(.*?)\};", text).group(1))
    return out


class CEmulation:
    """Traducción literal de struct BiomecEmg (biomec_emg_modelo.h)."""

    def __init__(self, h: dict):
        self.h = h
        C, S, N = h["BIOMEC_EMG_CANALES"], h["BIOMEC_EMG_N_SOS"], h["BIOMEC_EMG_VENTANA"]
        self.sos = np.array(h["BIOMEC_EMG_SOS"]).reshape(S, 5)
        self.z1, self.z2 = np.zeros((S, C)), np.zeros((S, C))
        self.dc = np.zeros(C)
        self.ventana = np.zeros((N, C))
        self.n = 0
        self.votos: list[int] = []
        self.confianza = 0.0

    def muestra(self, x) -> int:
        h = self.h
        N, P = h["BIOMEC_EMG_VENTANA"], h["BIOMEC_EMG_PASO"]
        pos = self.n % N
        for c in range(h["BIOMEC_EMG_CANALES"]):
            if self.n == 0:
                self.dc[c] = x[c]
            v = float(x[c]) - self.dc[c]
            for s, k in enumerate(self.sos):
                y = k[0] * v + self.z1[s, c]
                self.z1[s, c] = k[1] * v - k[3] * y + self.z2[s, c]
                self.z2[s, c] = k[2] * v - k[4] * y
                v = y
            self.ventana[pos, c] = v
        self.n += 1
        if self.n % P != 0 or self.n < N:
            return -1
        return self.clasificar()

    def clasificar(self) -> int:
        h = self.h
        N, C, K = h["BIOMEC_EMG_VENTANA"], h["BIOMEC_EMG_CANALES"], h["BIOMEC_EMG_N_CLASES"]
        inicio = self.n % N
        f = []
        for c in range(C):
            thr = h["BIOMEC_EMG_UMBRAL"][c]
            prev = self.ventana[inicio, c]
            mav, wl, d_prev, zc, ssc = abs(prev), 0.0, 0.0, 0, 0
            for i in range(1, N):
                x = self.ventana[(inicio + i) % N, c]
                d = x - prev
                ad = abs(d)
                mav += abs(x)
                wl += ad
                if prev * x < 0 and ad >= thr:
                    zc += 1
                if i >= 2 and d_prev * -d > 0 and (abs(d_prev) >= thr or ad >= thr):
                    ssc += 1
                d_prev, prev = d, x
            f += [math.log(mav / N + 1e-3), math.log(wl / N + 1e-3), zc / N, ssc / N]
        W = np.array(h["BIOMEC_EMG_W"]).reshape(K, -1)
        z = (np.array(f) - h["BIOMEC_EMG_MEDIA"]) * h["BIOMEC_EMG_ESCALA"]
        g = W @ z + h["BIOMEC_EMG_B"]
        k = int(np.argmax(g))
        prob = np.exp(g - g.max())
        prob /= prob.sum()
        self.votos = (self.votos + [k])[-h["BIOMEC_EMG_VOTO"]:]
        mejor, mejor_n = k, 0
        for a in reversed(self.votos):
            cuenta = self.votos.count(a)
            if cuenta > mejor_n:
                mejor, mejor_n = a, cuenta
        self.confianza = float(prob[mejor])
        return mejor


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patient = VirtualPatient(channels=4, seed=11)
        moves = [REST, "Abrir mano", "Cerrar mano", "Pinza"]
        cls.model = train_model(guided_recording(cls.patient, moves))
        cls.header = export_c_header(cls.model)
        cls.h = parse_header(cls.header)

    def test_constants(self):
        h, m = self.h, self.model
        self.assertEqual(h["CLASES"], m.classes)
        self.assertEqual(h["BIOMEC_EMG_CANALES"], 4)
        self.assertEqual(h["BIOMEC_EMG_N_CARAC"], 16)
        self.assertEqual(h["BIOMEC_EMG_VENTANA"], m.window)
        self.assertEqual(len(h["BIOMEC_EMG_W"]), 4 * 16)
        np.testing.assert_allclose(h["BIOMEC_EMG_ESCALA"], 1 / m.lda.sd, rtol=1e-6)
        self.assertIn("BIOMEC_EMG_ABRIR_MANO = 1,", self.header)
        # en C, cada valor de un array va separado por una coma (también al cambiar de línea)
        for body in re.findall(r"static const float BIOMEC_EMG_\w+\[[^=]*=\s*\{(.*?)\};", self.header, re.S):
            numbers = len(re.findall(r"\d(?:[eE][-+]?\d+)?f", body))
            self.assertEqual(body.count(",") + 1, numbers, body[:60])

    def test_same_decisions_as_app(self):
        seq = [(REST, 1.0), ("Abrir mano", 1.5), (REST, 1.0), ("Cerrar mano", 1.5), ("Pinza", 1.5), (REST, 1.0)]
        signal = []
        for move, secs in seq:
            self.patient.set_movement(move)
            signal.append(self.patient.generate(int(secs * 500)))
        x = np.vstack(signal)
        app = RealtimeDecoder(self.model)
        c = CEmulation(self.h)
        ours, theirs = [], []
        for i in range(0, len(x), 20):  # bloques de 20 muestras, como llegan del puente
            ours += [d.index for d in app.push(x[i:i + 20])]
        for row in x:
            k = c.muestra(row)
            if k >= 0:
                theirs.append(k)
        self.assertEqual(len(ours), len(theirs))
        skip = 10  # el arranque de los filtros difiere un poco (offset inicial distinto)
        agree = np.mean(np.array(ours[skip:]) == np.array(theirs[skip:]))
        self.assertGreater(agree, 0.97)

    def test_identifiers(self):
        self.assertEqual(c_identifier("Señalar"), "SENALAR")
        self.assertEqual(c_identifier("Co-contracción"), "CO_CONTRACCION")
        self.assertEqual(c_identifier("3 dedos"), "M_3_DEDOS")


if __name__ == "__main__":
    unittest.main()
