"""Simulador de la mano y coherencia con el firmware y el catálogo.

Si alguien añade un comando o un gesto en mano.cpp y se olvida del simulador
o de commands.json (o al revés), estas pruebas fallan y dicen qué falta.
"""

import re
import time
import unittest
from pathlib import Path

from biomec.core.commands import CommandCatalog
from biomec.core.emg_sim import PATIENT
from biomec.core.gestures import GESTOS
from biomec.core.protocol import MessageKind, parse_line
from biomec.core.simulator import SimulatedHand, SimulatedSerial
from biomec.paths import config_file

ROOT = Path(__file__).resolve().parent.parent


def firmware(local: str, equipo: str) -> str:
    """Lee el código de un firmware: está en firmware/ junto a la app o, en el repositorio del equipo, en
    firmware/centro de control/maestro/ (el puente en c6/), dos carpetas por encima de la app."""
    for path in (ROOT / "firmware" / local, ROOT.parent.parent / "maestro" / equipo):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"No se encuentra el firmware: ni firmware/{local} ni ../../maestro/{equipo}")


MANO = firmware("mano/src/mano.cpp", "mano/src/mano.cpp")
PUENTE = firmware("puente_pc/src/puente_pc.cpp", "c6/src/puente_pc.cpp")


def table(source: str, name: str) -> list[str]:
    """Nombres de una tabla {"NOMBRE", cmdXxx} del firmware."""
    block = source.split(name, 1)[1].split("};", 1)[0]
    return re.findall(r'\{\s*"([A-Z]+)"\s*,\s*cmd\w+\s*\}', block)


class FirmwareParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = CommandCatalog(config_file("commands.json"))

    def test_hand_commands(self):
        firmware = set(table(MANO, "COMMANDS[] ="))
        simulator = set(SimulatedHand()._commands)
        catalog = {c.name for c in self.cat if c.target == "mano"}
        self.assertEqual(firmware, simulator, "mano.cpp y simulator.py no tienen los mismos comandos")
        self.assertEqual(firmware, catalog, "mano.cpp y commands.json no tienen los mismos comandos")

    def test_bridge_commands(self):
        firmware = set(table(PUENTE, "BRIDGE_COMMANDS[] ="))
        catalog = {c.name for c in self.cat if c.target == "puente"}
        self.assertEqual(firmware, catalog, "puente_pc.cpp y commands.json no tienen los mismos comandos @")

    def test_telemetry_keys(self):
        """Las señales DATA del firmware, del simulador y del catálogo de gráficas coinciden."""
        from biomec.core.signals import SignalCatalog
        block = MANO.split("const TelemetrySignal TELEMETRY[] = {", 1)[1].split("};", 1)[0]
        firmware = set(re.findall(r'\{"(\w+)",\s*t\w+\}', block))
        hand = SimulatedHand()
        hand.streaming = True
        hand._ultima_telemetria = 0
        line = hand.telemetry()[0]
        simulator = {tok.split("=")[0] for tok in line.split()[1:]}
        self.assertEqual(firmware, simulator, "mano.cpp y simulator.py no envían las mismas señales DATA")
        catalog = SignalCatalog(config_file("signals.json"))
        missing = firmware - set(catalog.signals)
        self.assertFalse(missing, f"Señales del firmware sin entrada en config/signals.json: {missing}")

    def test_gesture_names(self):
        block = MANO.split("const Gesto GESTOS[] = {", 1)[1].split("};", 1)[0]
        rows = re.findall(r'\{"([^"]+)",\s*(\w+),\s*(\w+),\s*(\w+),\s*(\d+)\}', block)
        firmware = [(n, a.lower(), b.lower(), c.lower(), int(p)) for n, a, b, c, p in rows]
        app = [(g.nombre, g.indice, g.medio, g.anular, g.pulgar) for g in GESTOS]
        self.assertEqual(firmware, app, "La tabla de gestos de mano.cpp no coincide con core/gestures.py")


class SimulatedHandTest(unittest.TestCase):
    def setUp(self):
        self.hand = SimulatedHand()

    def test_gesto(self):
        self.assertTrue(self.hand.handle("GESTO 9")[0].startswith("ERR"))
        self.assertEqual(self.hand.handle("GESTO 6"), [f"ACK GESTO 6 {GESTOS[5].nombre}"])
        self.assertFalse(self.hand.modo_auto)

    def test_postura(self):
        self.assertEqual(self.hand.handle("POSTURA c a - 90"), ["ACK POSTURA C A - 90"])
        self.assertEqual(self.hand.gesto_actual, -1)
        self.assertEqual(self.hand.angulo_pulgar, 90)
        self.assertEqual(self.hand.mov[2], 0)  # "-" = no se mueve
        # idéntica a un gesto de fábrica: se informa como ese gesto
        self.hand.handle("POSTURA A A A 10")
        self.assertEqual(self.hand.gesto_actual, 0)
        for bad in ("POSTURA X A A 10", "POSTURA A A A 181", "POSTURA A A A", "POSTURA A A A -5"):
            self.assertTrue(self.hand.handle(bad)[0].startswith("ERR"), bad)

    def test_estado_reports_number(self):
        self.hand.handle("GESTO 6")
        reply = self.hand.handle("ESTADO")[0]
        self.assertIn(" gesto=6 ", reply)
        self.assertIn("modo=MANUAL", reply)


class SimulatedSerialTest(unittest.TestCase):
    def _lines(self, port: SimulatedSerial, seconds: float) -> list[str]:
        out, buf, end = [], b"", time.monotonic() + seconds
        while time.monotonic() < end:
            buf += port.read(4096)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                out.append(raw.decode("utf-8").strip())
        return out

    def test_bridge_and_emg(self):
        port = SimulatedSerial(timeout=0.01)
        port.write(b"@PING\n@EMG 1\n")
        lines = self._lines(port, 0.3)
        self.assertIn("BRIDGE PONG", lines)
        emg = [parse_line(l) for l in lines if l.startswith("EMG ")]
        self.assertGreaterEqual(len(emg), 4)  # 25 paquetes/s
        self.assertTrue(all(m.kind is MessageKind.EMG for m in emg))
        self.assertEqual({m.payload.channels for m in emg}, {PATIENT.channels})
        seqs = [m.payload.seq for m in emg]
        self.assertEqual(seqs, list(range(seqs[0], seqs[0] + len(seqs))))  # sin huecos
        port.write(b"@EMG 0\n")
        self._lines(port, 0.05)
        self.assertFalse(any(l.startswith("EMG ") for l in self._lines(port, 0.15)))
        port.close()


if __name__ == "__main__":
    unittest.main()
