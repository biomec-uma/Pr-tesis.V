"""Procesado EMG e IA (filtros, características, LDA, entrenamiento y tiempo real)."""

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from biomec.core.emg import (
    LDA, REST, Biquad, EmgDataset, EmgModel, Preprocessor, RealtimeDecoder, hudgins_features, train_model,
)
from biomec.core.emg_sim import VirtualPatient

FS = 500


def guided_recording(patient: VirtualPatient, moves, reps=2, secs=2.5) -> EmgDataset:
    """Como la grabación guiada de la app: reposo, indicación, ~0.3 s de reacción y el movimiento."""
    ds = EmgDataset(FS)
    for _ in range(reps):
        for m in moves:
            patient.set_movement(REST)
            patient.generate(FS)
            pre = patient.generate(int(0.3 * FS))
            patient.set_movement(m)
            ds.add(m, np.vstack([pre, patient.generate(int((secs - 0.3) * FS))]))
    return ds


class FilterTest(unittest.TestCase):
    def test_highpass_removes_offset(self):
        x = np.full((2000, 2), -478.0) + np.random.default_rng(0).normal(0, 1, (2000, 2))
        y = Preprocessor(FS, 2).process(x)
        self.assertLess(abs(y[500:].mean()), 0.5)

    def test_notch_removes_50hz(self):
        t = np.arange(4000) / FS
        x = (np.sin(2 * math.pi * 50 * t) * 100)[:, None]
        y = Biquad.design("notch", 50, FS, 30, 1).process(x)
        self.assertLess(np.abs(y[2000:]).max(), 5.0)

    def test_blocks_equal_whole(self):
        """Filtrar en bloques de 20 muestras (como llegan) da lo mismo que filtrar todo de golpe."""
        x = np.random.default_rng(1).normal(0, 50, (400, 3))
        pre = Preprocessor(FS, 3)
        pre._dc = x[:20].mean(axis=0)  # el offset inicial se toma del primer bloque
        whole = pre.process(x)
        pre2 = Preprocessor(FS, 3)
        parts = np.vstack([pre2.process(x[i:i + 20]) for i in range(0, 400, 20)])
        np.testing.assert_allclose(whole, parts, atol=1e-9)


class FeatureTest(unittest.TestCase):
    def test_hudgins(self):
        win = np.array([[1.0], [-1.0]] * 50)  # cambia de signo en cada muestra
        f = hudgins_features(win, np.array([0.5]))
        mav, wl, zc, ssc = f
        self.assertAlmostEqual(math.exp(mav), 1.0, places=2)
        self.assertAlmostEqual(zc, 99 / 100)
        self.assertAlmostEqual(ssc, 98 / 100)
        quiet = hudgins_features(win * 0.1, np.array([0.5]))
        self.assertEqual(quiet[2], 0.0)  # por debajo del umbral de ruido no cuenta


class LdaTest(unittest.TestCase):
    def test_two_blobs(self):
        rng = np.random.default_rng(2)
        X = np.vstack([rng.normal(0, 1, (200, 4)), rng.normal(3, 1, (200, 4))])
        y = np.repeat([0, 1], 200)
        lda = LDA().fit(X, y, 2)
        self.assertGreater((lda.predict(X) == y).mean(), 0.97)
        p = lda.proba(X[:3])
        np.testing.assert_allclose(p.sum(axis=1), 1.0)
        again = LDA.from_dict(lda.to_dict())
        np.testing.assert_allclose(again.decision(X), lda.decision(X))


class TrainingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patient = VirtualPatient(channels=2, seed=7)
        cls.ds = guided_recording(cls.patient, [REST, "Abrir mano", "Cerrar mano"])
        cls.model = train_model(cls.ds)

    def test_accuracy(self):
        rep = self.model.report
        self.assertEqual(rep.classes, [REST, "Abrir mano", "Cerrar mano"])
        self.assertIn("repetición", rep.method)
        self.assertGreater(rep.accuracy, 0.9)

    def test_needs_two_classes(self):
        ds = EmgDataset(FS)
        ds.add(REST, np.zeros((1000, 2), dtype=int))
        with self.assertRaises(ValueError):
            train_model(ds)

    def test_realtime(self):
        dec = RealtimeDecoder(self.model)
        self.patient.set_movement(REST)
        for _ in range(25):
            dec.push(self.patient.generate(20))
        self.patient.set_movement("Abrir mano")
        decisions = []
        for _ in range(50):  # 2 s en bloques de 20 muestras
            decisions += dec.push(self.patient.generate(20))
        self.assertEqual(len(decisions), 2 * 1000 // self.model.config.step_ms)
        late = decisions[10:]
        self.assertGreater(sum(d.label == "Abrir mano" for d in late) / len(late), 0.9)
        self.assertGreater(np.mean([d.intensity for d in late]), 0.3)
        with self.assertRaises(ValueError):
            dec.push(np.zeros((20, 3)))

    def test_model_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            self.model.save(path)
            again = EmgModel.load(path)
        x = self.patient.generate(400)
        a = [d.label for d in RealtimeDecoder(self.model).push(x)]
        b = [d.label for d in RealtimeDecoder(again).push(x)]
        self.assertEqual(a, b)
        self.assertAlmostEqual(again.report.accuracy, self.model.report.accuracy)

    def test_dataset_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.csv"
            self.ds.save_csv(path)
            again = EmgDataset.load_csv(path)
        self.assertEqual(again.summary(), self.ds.summary())
        for a, b in zip(self.ds.recordings, again.recordings):
            np.testing.assert_array_equal(a.samples, b.samples)


if __name__ == "__main__":
    unittest.main()
