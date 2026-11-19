"""Filtros de los sensores EMG Gravity (firmware/emg_gravity/lib/EMGFilters, copia corregida de OYMotion).

La librería original tenía una coma de menos en el notch de 50 Hz a 500 Hz: el filtro dejaba de ser un notch
y pasaba a inclinar el espectro (-14 dB a 20 Hz, +5 dB a 150 Hz). Estas pruebas leen los coeficientes del .cpp
y comprueban la respuesta de cada filtro tal y como la calcula el firmware, para que no vuelva a pasar si
alguien sustituye la librería.
"""

import re
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RUTA = "emg_gravity/lib/EMGFilters/EMGFilters.cpp"


def fuente() -> str:
    """Junto a la app (firmware/) o, en el repositorio del equipo, dos carpetas por encima (maestro/)."""
    for path in (ROOT / "firmware" / RUTA, ROOT.parent.parent / "maestro" / RUTA):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"No se encuentra {RUTA}")


def tabla(src: str, nombre: str) -> list[list[float]]:
    """Filas de una tabla 'static const float nombre[a][b] = {{...}, {...}};' (o una fila si es [a])."""
    m = re.search(rf"{nombre}\[[^=]*=\s*(\{{.*?\}});", src, re.S)
    if m is None:
        raise AssertionError(f"No está la tabla {nombre}")
    cuerpo = re.sub(r"//[^\n]*", "", m.group(1))
    filas = re.findall(r"\{([^{}]*)\}", cuerpo)
    out = []
    for fila in filas:
        try:
            out.append([float(x) for x in fila.split(",")])
        except ValueError:
            raise AssertionError(f"{nombre}: '{fila.strip()}' no son números separados por comas "
                                 f"(¿falta una coma?)") from None
    return out


def respuesta(b, a, f, fs):
    z = np.exp(-1j * 2 * np.pi * np.asarray(f, dtype=float) / fs)
    return np.polyval(np.asarray(b)[::-1], z) / np.polyval(np.asarray(a)[::-1], z)


def db(h):
    return 20 * np.log10(np.abs(h))


FS = (500, 1000)          # fila 0 y fila 1 de cada tabla


class EmgFiltersGravity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.src = fuente()
        except FileNotFoundError as error:   # una copia de la app sin ese firmware al lado
            raise unittest.SkipTest(str(error)) from None

    def test_notch_tablas_completas(self):
        """Cada fila del notch tiene sus 6 coeficientes y el 4º del denominador es 1 (el código lo da por hecho)."""
        for red in (50, 60):
            for nombre in (f"ahf_numerator_coef_{red}Hz", f"ahf_denominator_coef_{red}Hz"):
                filas = tabla(self.src, nombre)
                self.assertEqual([len(f) for f in filas], [6, 6], f"{nombre}: ¿falta una coma?")
            for fila in tabla(self.src, f"ahf_denominator_coef_{red}Hz"):
                self.assertEqual((fila[0], fila[3]), (1.0, 1.0))

    def test_notch_quita_la_red_y_deja_el_emg(self):
        f_emg = [20, 30, 80, 100, 120, 150]
        for red in (50, 60):
            num = tabla(self.src, f"ahf_numerator_coef_{red}Hz")
            den = tabla(self.src, f"ahf_denominator_coef_{red}Hz")
            gan = tabla(self.src, f"ahf_output_gain_coef_{red}Hz")[0]
            for k, fs in enumerate(FS):
                b, a, g = num[k], den[k], gan[k]

                def h(f):
                    return g * respuesta(b[0:3], a[0:3], f, fs) * respuesta(b[3:6], a[3:6], f, fs)

                with self.subTest(red=red, fs=fs):
                    self.assertLess(db(h([red]))[0], -15, "no quita la red")
                    self.assertTrue(np.all(np.abs(db(h(f_emg))) < 3), f"deforma el EMG: {np.round(db(h(f_emg)), 1)}")
                    polos = np.abs(np.roots(a[3:6])), np.abs(np.roots(a[0:3]))
                    self.assertTrue(all(np.all(p < 1) for p in polos), "inestable")

    def test_paso_bajo_y_paso_alto(self):
        for nombre, corte in (("lpf", 150), ("hpf", 20)):
            num = tabla(self.src, f"{nombre}_numerator_coef")
            den = tabla(self.src, f"{nombre}_denominator_coef")
            for k, fs in enumerate(FS):
                with self.subTest(filtro=nombre, fs=fs):
                    a3 = db(respuesta(num[k], den[k], [corte], fs))[0]
                    self.assertAlmostEqual(a3, -3, delta=1, msg=f"a {corte} Hz da {a3:.1f} dB")
                    medio = db(respuesta(num[k], den[k], [70], fs))[0]
                    self.assertGreater(medio, -1.5, "atenúa la banda del EMG")


if __name__ == "__main__":
    unittest.main()
