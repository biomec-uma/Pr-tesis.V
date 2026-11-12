"""Catálogo de señales y almacén para las gráficas: marcas de comandos (inicio/fin), movimientos de la demo,
señales derivadas y eje de tiempo. Sin interfaz."""

import unittest

import numpy as np

from biomec.core.gestures import GESTOS
from biomec.core.protocol import Message, MessageKind, make_message
from biomec.core.signals import SignalCatalog, SignalStore, fmt_clock
from biomec.paths import config_file


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def data(**values) -> Message:
    return make_message(MessageKind.DATA, " ".join(f"{k}={v}" for k, v in values.items()))


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.cat = SignalCatalog(config_file("signals.json"))

    def test_groups_and_templates(self):
        self.assertEqual(self.cat.group_of("indice").unit, "PWM")
        self.assertEqual(self.cat.group_of("pulgar").id, "angulo")
        self.assertIn("emg1", self.cat.signals)           # plantilla emg{n} con 8 canales
        self.assertIn("emg8_f", self.cat.signals)
        self.assertEqual(self.cat.signals["emg3"].name, "EMG canal 3 · bruto")
        self.assertFalse(self.cat.signals["i_indice"].available)   # pendiente
        self.assertTrue(self.cat.signals["indice"].available)

    def test_unknown_key_goes_to_otros(self):
        sd = self.cat.define("temperatura")
        self.assertEqual(sd.group, "otros")
        groups = self.cat.by_group(["pulgar", "indice", "temperatura", "medio"])
        self.assertEqual([g.id for g, _k in groups], ["pwm", "angulo", "otros"])  # orden del catálogo
        self.assertEqual(groups[0][1], ["indice", "medio"])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = SignalStore(SignalCatalog(config_file("signals.json")), clock=self.clock)

    def tick(self, dt: float, **values):
        self.clock.t += dt
        self.store.on_message(data(**values))

    def test_command_marker_opens_and_closes_when_motors_stop(self):
        self.tick(0.05, indice=0, medio=0, anular=0, pulgar=10, gesto=1)
        self.store.on_message(Message(MessageKind.TX, "GESTO 3"))
        m = self.store.markers[-1]
        self.assertTrue(m.open)
        self.assertEqual(m.t0, self.store.now())
        self.tick(0.05, indice=0, medio=-25, anular=0, pulgar=10, gesto=3)   # arranca el motor
        self.assertTrue(m.open)
        for _ in range(10):
            self.tick(0.05, indice=0, medio=-255, anular=0, pulgar=10, gesto=3)
        self.tick(0.05, indice=0, medio=0, anular=0, pulgar=10, gesto=3)     # vuelve a 0: fin
        self.assertFalse(m.open)
        self.assertAlmostEqual(m.t1, self.store.now())
        self.assertGreater(m.t1, m.t0)

    def test_command_without_motion_has_no_region(self):
        self.tick(0.05, indice=0, medio=0, anular=0, gesto=1)
        self.store.on_message(Message(MessageKind.TX, "GESTO 1"))
        m = self.store.markers[-1]
        for _ in range(20):
            self.tick(0.05, indice=0, medio=0, anular=0, gesto=1)
        self.assertFalse(m.open)
        self.assertIsNone(m.t1)

    def test_demo_movement_is_marked_as_hand(self):
        self.tick(0.05, indice=0, gesto=2)
        self.tick(3.0, indice=25, gesto=3)   # cambia el gesto sin ningún comando: la demo
        kinds = [(m.kind, m.text) for m in self.store.markers]
        self.assertEqual(kinds, [("hand", f"demo · {GESTOS[2].nombre}")])
        # con un comando reciente no se marca como demo
        self.store.on_message(Message(MessageKind.TX, "GESTO 5"))
        self.tick(0.1, indice=25, gesto=5)
        self.assertEqual(self.store.markers[-1].kind, "cmd")

    def test_setpoints_follow_acks(self):
        self.store.on_message(Message(MessageKind.ACK, "GESTO 8 Gancho"))   # todo cerrado, pulgar 10
        self.tick(0.05, indice=0, medio=0, anular=0)
        self.assertEqual([self.store.series[f"consigna_{d}"].last for d in ("indice", "medio", "anular")], [1, 1, 1])
        self.store.on_message(Message(MessageKind.ACK, "DEDO INDICE ABRIR"))
        self.store.on_message(Message(MessageKind.ACK, "PULGAR 90"))
        self.tick(0.05, indice=0, medio=0, anular=0)
        self.assertEqual(self.store.series["consigna_indice"].last, 0)
        self.assertEqual(self.store.series["consigna_pulgar"].last, 90)
        self.store.on_message(Message(MessageKind.ACK, "POSTURA C - A 45"))
        self.tick(0.05, indice=0, medio=0, anular=0)
        self.assertEqual([self.store.series[f"consigna_{d}"].last for d in ("indice", "medio", "anular")], [1, 1, 0])
        self.assertEqual(self.store.series["consigna_pulgar"].last, 45)

    def test_flex_estimate_and_saturation(self):
        self.store.on_message(Message(MessageKind.ACK, "TIEMPO 1000"))
        self.assertEqual(self.store.phase_s, 1.0)
        self.tick(0.05, indice=0, medio=0, anular=0)
        for _ in range(28):                    # 1,35 s cerrando a tope: aún dentro de tiempo de fase + rampa (1,5 s)
            self.tick(0.05, indice=-255, medio=0, anular=0)
        self.assertEqual(self.store.series["sat_indice"].last, 0.0)
        for _ in range(4):                     # 1,55 s: más de lo previsto -> alarma
            self.tick(0.05, indice=-255, medio=0, anular=0)
        self.assertEqual(self.store.series["sat_indice"].last, 1.0)
        flex = self.store.series["flex_indice"].last
        self.assertGreater(flex, 90)           # ≈ 1,6 s / tiempo de cierre 1,5 s -> 100 %
        self.tick(0.05, indice=0, medio=0, anular=0)
        self.assertEqual(self.store.series["sat_indice"].last, 0.0)
        self.store.on_message(Message(MessageKind.ACK, "ESTADO modo=MANUAL fase=parado gesto=1 indice=abierto "
                                                       "medio=abierto anular=abierto pulgar=10 tiempo=3000"))
        self.tick(0.05, indice=0, medio=0, anular=0)
        self.assertEqual(self.store.series["flex_indice"].last, 0.0)
        self.assertEqual(self.store.phase_s, 3.0)

    def test_emg_channels(self):
        samples = np.tile(np.array([[100, -100]]), (20, 1))
        self.clock.t += 0.04
        self.store.on_message(make_message(MessageKind.EMG, "7 2 " + " ".join(map(str, samples.ravel()))))
        self.assertEqual(self.store.emg_channels, 2)
        raw, flt = self.store.series["emg1"], self.store.series["emg2_f"]
        self.assertEqual(len(raw.t), 20)
        self.assertAlmostEqual(raw.t[-1] - raw.t[0], 19 / 500)
        self.assertEqual(raw.y[-1], 100)
        self.assertEqual(len(flt.y), 20)

    def test_clear_resets_clock(self):
        self.tick(5.0, indice=0)
        self.assertGreater(self.store.latest(), 4.9)
        self.store.clear()
        self.assertEqual(self.store.latest(), 0.0)
        self.assertEqual(self.store.now(), 0.0)
        self.assertEqual(self.store.keys_with_data(), [])


class ClockFormatTest(unittest.TestCase):
    def test_fmt_clock(self):
        self.assertEqual(fmt_clock(0), "00:00")
        self.assertEqual(fmt_clock(65), "01:05")
        self.assertEqual(fmt_clock(3312), "55:12")
        self.assertEqual(fmt_clock(3725), "1:02:05")
        self.assertEqual(fmt_clock(62.5, 1), "01:02.5")


if __name__ == "__main__":
    unittest.main()
