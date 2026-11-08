"""Protocolo de texto y catálogo de comandos."""

import unittest

import numpy as np

from biomec.core.commands import CommandCatalog, CommandError
from biomec.core.protocol import MessageKind, format_emg, parse_emg, parse_line
from biomec.paths import config_file


class ProtocolTest(unittest.TestCase):
    def test_data_values(self):
        msg = parse_line("DATA indice=-128 medio=0 pulgar=90 gesto=6\r\n")
        self.assertIs(msg.kind, MessageKind.DATA)
        self.assertEqual(msg.values, {"indice": -128.0, "medio": 0.0, "pulgar": 90.0, "gesto": 6.0})

    def test_kinds(self):
        self.assertIs(parse_line("ACK GESTO 3 Índice y anular").kind, MessageKind.ACK)
        self.assertEqual(parse_line("ACK GESTO 3 Índice y anular").text, "GESTO 3 Índice y anular")
        self.assertIs(parse_line("ERR algo").kind, MessageKind.ERROR)
        self.assertIs(parse_line("BRIDGE PONG").kind, MessageKind.BRIDGE)
        self.assertIs(parse_line("Mano lista. MAC=AA").kind, MessageKind.TEXT)

    def test_bad_values_are_ignored(self):
        self.assertEqual(parse_line("DATA a=1 b=x c").values, {"a": 1.0})

    def test_emg(self):
        msg = parse_line("EMG 7 2 10 -3 12 -5 0 1")
        self.assertIs(msg.kind, MessageKind.EMG)
        self.assertEqual(msg.payload.seq, 7)
        self.assertEqual(msg.payload.channels, 2)
        np.testing.assert_array_equal(msg.payload.samples, [[10, -3], [12, -5], [0, 1]])

    def test_emg_malformed_is_text(self):
        self.assertIs(parse_line("EMG 7 2 1 2 3").kind, MessageKind.TEXT)   # 3 valores para 2 canales
        self.assertIs(parse_line("EMG hola").kind, MessageKind.TEXT)
        self.assertIsNone(parse_emg("1 0 5"))

    def test_emg_roundtrip(self):
        samples = np.array([[1, -2, 3], [4, 5, -6]])
        frame = parse_line(format_emg(65535, samples)).payload
        self.assertEqual(frame.seq, 65535)
        np.testing.assert_array_equal(frame.samples, samples)


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = CommandCatalog(config_file("commands.json"))

    def test_build(self):
        self.assertEqual(self.cat.build("gesto 3")[1], "GESTO 3")
        self.assertEqual(self.cat.build("dedo indice cerrar")[1], "DEDO INDICE CERRAR")
        self.assertEqual(self.cat.build("ping")[1], "@PING")
        self.assertEqual(self.cat.build("@INFO")[1], "@INFO")
        self.assertEqual(self.cat.build("emg 1")[1], "@EMG 1")

    def test_postura(self):
        self.assertEqual(self.cat.build("postura c a - 90")[1], "POSTURA C A - 90")
        for bad in ("POSTURA X A A 90", "POSTURA C A A 200", "POSTURA C A A", "POSTURA C A A noventa"):
            with self.assertRaises(CommandError, msg=bad):
                self.cat.build(bad)

    def test_validation(self):
        for bad in ("GESTO 0", "GESTO 9", "GESTO", "PULGAR -1", "NOEXISTE", ""):
            with self.assertRaises(CommandError, msg=bad):
                self.cat.build(bad)


if __name__ == "__main__":
    unittest.main()
