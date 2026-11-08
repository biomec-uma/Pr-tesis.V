"""Posturas personalizadas y grabación de sesiones."""

import json
import tempfile
import unittest
from pathlib import Path

from biomec.core.gestures import ABIERTO, CERRADO, DESCONOCIDO, Gesto
from biomec.core.postures import PostureStore, matching_gesture, posture_command, spec_from_ack
from biomec.core.protocol import Message, MessageKind, parse_line
from biomec.core.session import SessionRecorder, load_session


class PostureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "posturas.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        store = PostureStore(self.path)
        store.add(Gesto("Pinza fina", CERRADO, ABIERTO, ABIERTO, 90))
        store.add(Gesto("Solo pulgar", DESCONOCIDO, DESCONOCIDO, DESCONOCIDO, 45))
        again = PostureStore(self.path)
        self.assertEqual(again.items, store.items)
        self.assertEqual(posture_command(again.items[0]), "POSTURA C A A 90")
        self.assertEqual(posture_command(again.items[1]), "POSTURA - - - 45")
        self.assertEqual(again.find_spec("C A A 90"), 0)
        self.assertEqual(again.find_spec("C C C 90"), -1)

    def test_unique_names_and_move(self):
        store = PostureStore(self.path)
        store.add(Gesto("Llave", CERRADO, CERRADO, CERRADO, 60))
        self.assertEqual(store.unique_name("Llave"), "Llave 2")
        self.assertEqual(store.unique_name("Llave", skip=0), "Llave")
        store.add(Gesto("Otra", ABIERTO, ABIERTO, ABIERTO, 10))
        store.move(1, -1)
        self.assertEqual([g.nombre for g in PostureStore(self.path).items], ["Otra", "Llave"])

    def test_damaged_file(self):
        self.path.write_text("{no es json", encoding="utf-8")
        store = PostureStore(self.path)
        self.assertEqual(store.items, [])
        self.assertTrue(store.error)

    def test_sanitizes_values(self):
        data = {"posturas": [{"nombre": "X", "indice": "raro", "medio": "cerrado", "anular": "?", "pulgar": 999}]}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        g = PostureStore(self.path).items[0]
        self.assertEqual((g.indice, g.medio, g.anular, g.pulgar), (ABIERTO, CERRADO, DESCONOCIDO, 180))

    def test_helpers(self):
        self.assertEqual(spec_from_ack("POSTURA c a - 90"), "C A - 90")
        self.assertIsNone(spec_from_ack("GESTO 3 algo"))
        self.assertEqual(matching_gesture(Gesto("x", ABIERTO, ABIERTO, ABIERTO, 10)), 1)
        self.assertEqual(matching_gesture(Gesto("x", CERRADO, ABIERTO, ABIERTO, 90)), 0)


class SessionTest(unittest.TestCase):
    def test_record_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            rec = SessionRecorder(path, {"simulacion": True})
            for line in ("DATA indice=-200 gesto=3", "ACK GESTO 3 Índice y anular", "EMG 1 2 5 -5 6 -6"):
                rec.write(parse_line(line))
            rec.write(Message(MessageKind.TX, "GESTO 3"))
            rec.close()
            with open(path, "a", encoding="utf-8") as fh:
                fh.write('{"t": 9.9, "k": "DATA", "x": "a=1"')  # línea cortada (cierre brusco)
            s = load_session(path)
        self.assertTrue(s.meta["simulacion"])
        self.assertEqual([e.kind for e in s.events],
                         [MessageKind.DATA, MessageKind.ACK, MessageKind.EMG, MessageKind.TX])
        msgs = [e.message() for e in s.events]
        self.assertEqual(msgs[0].values["indice"], -200.0)
        self.assertEqual(msgs[1].text, "ACK GESTO 3 Índice y anular"[4:])
        self.assertEqual(msgs[2].payload.samples.tolist(), [[5, -5], [6, -6]])
        self.assertEqual(s.count(MessageKind.TX), 1)
        self.assertGreaterEqual(s.duration, 0.0)

    def test_not_a_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.jsonl"
            path.write_text('{"otra": "cosa"}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_session(path)


if __name__ == "__main__":
    unittest.main()
