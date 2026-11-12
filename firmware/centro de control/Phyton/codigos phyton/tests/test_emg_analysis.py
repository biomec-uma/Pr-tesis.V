"""Analizador EMG (core/emg_analysis.py): mismos números que el analizador en MATLAB del equipo.

Las referencias salen del repositorio del equipo (rama main): firmware/EMG/data/raw/27.10.2026.enReposoUsandoMotores.csv
(copiado en tests/data/emg_equipo_reposo_motores.csv) y su análisis guardado por MATLAB en
firmware/EMG/data/processed/OutputAnalisis/27.10.2026.enReposoUsandoMotores/ (resultados.csv y
coeficientes_filtros.txt), más el diseño 20-240 Hz de OutputAnalisis/20.10.2026.antebrazoluegobicep.
"""

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from biomec.core import emg_analysis as ea

DATA = Path(__file__).parent / "data" / "emg_equipo_reposo_motores.csv"

# resultados.csv de MATLAB para esa muestra (parámetros por defecto: 500 SPS, notch 50 Hz Q 35, 20-130 Hz,
# RMS 0.2 s, reposo 0.5-2.5 s, k 3)
MATLAB = {
    "p50": (66.6417772918071, 93.1631118707423),
    "p50_notch": (1.20072319764949, 6.58156339619607),
    "rest_rms": (3.49839750321083, 6.0562100314697),
    "threshold": (6.65320367331876, 16.6197234895605),
}


class FilterDesignTests(unittest.TestCase):
    def test_notch_like_designNotchPeakIIR(self):
        b, a = ea.notch_design(50, 35, 500)
        np.testing.assert_allclose(b, [0.9911036356, -1.603639369, 0.9911036356], atol=2e-10)
        np.testing.assert_allclose(a, [1, -1.603639369, 0.9822072713], atol=2e-10)

    def test_bandpass_20_130_same_coefficients_as_matlab(self):
        h = ea.bandpass_design(20, 130, 500)
        self.assertEqual(len(h), 595)
        np.testing.assert_allclose(h[:4], [2.497156307e-05, -2.48006046e-06, -1.725118574e-18, 4.154360228e-05],
                                   atol=1e-12)
        self.assertAlmostEqual(h[297], 0.4525549863, places=9)
        self.assertAlmostEqual(h[298], 0.2441531155, places=9)

    def test_bandpass_20_240_same_coefficients_as_matlab(self):
        h = ea.bandpass_design(20, 240, 500)
        self.assertEqual(len(h), 1157)
        np.testing.assert_allclose(h[:4], [-1.730632923e-06, -1.889954348e-05, -1.051975025e-06, -1.404445593e-05],
                                   atol=1e-12)
        self.assertAlmostEqual(h[578], 0.8862975381, places=9)
        self.assertAlmostEqual(h[579], -0.03933809642, places=9)

    def test_filtfilt_has_no_phase_shift(self):
        fs = 500
        t = np.arange(5000) / fs
        x = np.sin(2 * np.pi * 10 * t) + np.sin(2 * np.pi * 50 * t)
        b, a = ea.notch_design(50, 35, fs)
        y = ea.filtfilt(b, a, x)
        clean = np.sin(2 * np.pi * 10 * t)
        self.assertLess(np.abs(y - clean)[500:-500].max(), 0.02)   # quita los 50 Hz sin desplazar los 10 Hz

    def test_fir_zero_phase_keeps_band(self):
        fs = 500
        t = np.arange(5000) / fs
        x = np.sin(2 * np.pi * 75 * t)
        y = ea.fir_zero_phase(ea.bandpass_design(20, 130, fs), x)
        np.testing.assert_allclose(y[600:-600], x[600:-600], atol=2e-3)


class MatlabEquivalenceTests(unittest.TestCase):
    def test_team_sample_gives_matlab_results(self):
        table = ea.load_csv(DATA)
        self.assertEqual(table.header, ["Program Time [s]", "data 0", "data 1"])
        self.assertEqual(table.time_col, 0)
        self.assertEqual(table.channel_cols, [1, 2])
        res = ea.analyze(table.data[:, table.channel_cols], ea.AnalysisParams())
        self.assertEqual(res.n_samples, 5000)
        self.assertEqual(res.warnings, [])
        for attr, ref in MATLAB.items():
            for ch, value in zip(res.channels, ref):
                self.assertAlmostEqual(getattr(ch, attr) / value, 1.0, places=9, msg=attr)

    def test_coefficients_file_like_guardarFiltros(self):
        table = ea.load_csv(DATA)
        res = ea.analyze(table.data[:, table.channel_cols], ea.AnalysisParams())
        lines = ea.coefficients_text(res).splitlines()
        self.assertEqual(lines[:7], [
            "fs = 500 Hz", "", "Notch 50 Hz, Q = 35", "b = [0.9911036356, -1.603639369, 0.9911036356]",
            "a = [           1, -1.603639369, 0.9822072713]", "", "Paso banda 20-130 Hz (595 coeficientes)"])
        self.assertEqual(len(lines[7].split(",")), 595)


class ValidationTests(unittest.TestCase):
    def test_warning_above_ads_bandwidth(self):
        warnings = ea.validate(ea.AnalysisParams(f_high=240), 5000)
        self.assertEqual(len(warnings), 1)
        self.assertIn("131 Hz", warnings[0])

    def test_errors(self):
        for bad in (dict(f_high=250), dict(f_low=150), dict(rest_end=20), dict(rest_start=3, rest_end=2),
                    dict(t_rms=0.001), dict(f0=300), dict(k=-1), dict(t_window=11), dict(sps=0)):
            with self.subTest(bad=bad), self.assertRaises(ea.AnalysisError):
                ea.validate(ea.AnalysisParams(**bad), 5000)

    def test_disabled_filters(self):
        x = np.random.default_rng(1).normal(size=(3000, 1)) * 50
        res = ea.analyze(x, ea.AnalysisParams(notch_on=False, band_on=False))
        self.assertIsNone(res.h_band)
        np.testing.assert_allclose(res.channels[0].v_band, res.channels[0].v)
        self.assertIn("Notch desactivado", ea.coefficients_text(res))
        self.assertIn("Paso banda desactivado", ea.coefficients_text(res))


class CsvTests(unittest.TestCase):
    def _write(self, folder: Path, name: str, text: str) -> Path:
        path = folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_formats_of_the_team(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            full = ea.load_csv(self._write(tmp, "a.csv", "t_s,seq,idx,ch1,ch2\n0.0000,7,0,10,-3\n0.0020,7,1,12,-5\n"))
            self.assertEqual((full.time_col, full.channel_cols), (0, [3, 4]))
            simple = ea.load_csv(self._write(tmp, "b.csv", "tiempo,data0,data1\n0.0,1,2\n0.002,3,4\n"))
            self.assertEqual((simple.time_col, simple.channel_cols), (0, [1, 2]))
            semi = ea.load_csv(self._write(tmp, "c.csv", "tiempo;data0\n0,0;5\n0,002;6\n0,004;7\n"))
            self.assertEqual(semi.channel_cols, [1])
            np.testing.assert_allclose(semi.data[:, 1], [5, 6, 7])
            raw = ea.load_csv(self._write(tmp, "d.csv", "0.0,1,2\n0.002,3,4\n0.004,5,6\n"))
            self.assertEqual((raw.time_col, raw.channel_cols), (0, [1, 2]))

    def test_estimated_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.csv"
            t = np.arange(1000) / 250
            path.write_text("tiempo,data0\n" + "\n".join(f"{v:.4f},1" for v in t), encoding="utf-8")
            self.assertAlmostEqual(ea.load_csv(path).estimated_rate(), 250, delta=1)

    def test_save_analysis_like_guardarAnalisis(self):
        table = ea.load_csv(DATA)
        res = ea.analyze(table.data[:, table.channel_cols], ea.AnalysisParams())
        with tempfile.TemporaryDirectory() as tmp:
            dest = ea.save_analysis(res, "27.10.2026.enReposoUsandoMotores.csv", tmp)
            ea.save_analysis(res, "27.10.2026.enReposoUsandoMotores.csv", tmp)     # el resumen crece
            self.assertEqual(dest.name, "27.10.2026.enReposoUsandoMotores")
            names = {p.name for p in dest.iterdir()}
            self.assertEqual(names, {"resultados.csv", "resumen_muestras.csv", "senales.csv",
                                     "coeficientes_filtros.txt"})
            with (dest / "resultados.csv").open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], [
                "muestra", "nMuestras", "duracion_s", "p50_ch0", "p50_ch1", "p50notch_ch0", "p50notch_ch1",
                "rmsReposo_ch0_uV", "rmsReposo_ch1_uV", "umbral_ch0_uV", "umbral_ch1_uV", "sps", "notchOn", "f0_Hz",
                "Q", "bandaOn", "fBaja_Hz", "fAlta_Hz", "tRMS_s", "tReposoIni_s", "tReposoFin_s", "kUmbral"])
            self.assertEqual(rows[1][:3], ["27.10.2026.enReposoUsandoMotores.csv", "5000", "10"])
            self.assertEqual(rows[1][11:], ["500", "1", "50", "35", "1", "20", "130", "0.2", "0.5", "2.5", "3"])
            self.assertAlmostEqual(float(rows[1][3]), MATLAB["p50"][0], places=9)
            summary = (dest / "resumen_muestras.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(summary), 3)      # cabecera + 2 análisis
            signals = (dest / "senales.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(signals[0], "t,v0fBanda,v1fBanda,rms0,rms1")
            self.assertEqual(len(signals), 5001)


if __name__ == "__main__":
    unittest.main()
