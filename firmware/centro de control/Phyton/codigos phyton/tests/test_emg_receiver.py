"""Receptor EMG del equipo (marcos AA 55), marcos mezclados con texto en la conexión principal, estadísticas,
grabación en CSV y las ventanas Visor/Analizador EMG."""

import csv
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path

import numpy as np

from biomec.core.emg_receiver import (
    STATUS, TYPE_DATA, TYPE_STATUS, CsvRecorder, FrameParser, FrameStream, ReceiverStatus, SensorPacket,
    StatusBaseline, StreamStats, build_frame, column_ids, sensor_payload, simple_name,
)
from biomec.core.protocol import MessageKind, make_message


def _packets(n: int, start_seq: int = 0, batch: int = 5, nch: int = 2) -> list[tuple[int, np.ndarray]]:
    rng = np.random.default_rng(0)
    return [(start_seq + i, rng.integers(-2000, 2000, size=(batch, nch)).astype(np.int16)) for i in range(n)]


class FrameParserTests(unittest.TestCase):
    def test_split_frames_garbage_and_status(self):
        pk = _packets(3)
        status = STATUS.pack(bytes([0xAC, 0xEB, 0xE6, 0x2C, 0xD7, 0xDC]), 10, 1, 2, 3)
        blob = (b"\x00\xAA" + build_frame(TYPE_DATA, sensor_payload(*pk[0], send_fails=4)) + b"basura"
                + build_frame(TYPE_STATUS, status) + build_frame(TYPE_DATA, sensor_payload(*pk[1]))
                + build_frame(0x7E, b"nuevo") + build_frame(TYPE_DATA, sensor_payload(*pk[2])))
        parser = FrameParser()
        items = []
        for i in range(0, len(blob), 7):          # llega a trozos
            items += parser.feed(blob[i:i + 7])
        data = [x for x in items if isinstance(x, SensorPacket)]
        self.assertEqual([p.seq for p in data], [0, 1, 2])
        np.testing.assert_array_equal(data[1].samples, pk[1][1])
        self.assertEqual((data[0].version, data[0].channels, data[0].batch, data[0].send_fails), (1, 2, 5, 4))
        st = [x for x in items if isinstance(x, ReceiverStatus)][0]
        self.assertEqual((st.mac, st.received, st.invalid, st.queue_full, st.usb_dropped),
                         ("AC:EB:E6:2C:D7:DC", 10, 1, 2, 3))
        self.assertEqual(parser.unknown, 1)
        self.assertEqual(parser.corrupt, 0)

    def test_bad_checksum_and_version_are_corrupt(self):
        pk = _packets(2)
        good = build_frame(TYPE_DATA, sensor_payload(*pk[0]))
        bad = bytearray(build_frame(TYPE_DATA, sensor_payload(*pk[1])))
        bad[-1] ^= 0xFF
        old = build_frame(TYPE_DATA, sensor_payload(*pk[1], version=2))
        parser = FrameParser()
        items = parser.feed(bytes(bad) + old + good)
        self.assertEqual([p.seq for p in items], [0])
        self.assertGreaterEqual(parser.corrupt, 2)

    def test_sync_bytes_inside_data(self):
        samples = np.array([[0x55AA, 0x55AA]] * 5, dtype=np.uint16).view(np.int16)   # AA 55 dentro de los datos
        items = FrameParser().feed(build_frame(TYPE_DATA, sensor_payload(9, samples)))
        self.assertEqual(len(items), 1)
        np.testing.assert_array_equal(items[0].samples, samples)


class MixedStreamTests(unittest.TestCase):
    """El puente con placa EMG manda por el mismo USB líneas de texto (la mano) y marcos AA 55 (el sensor)."""

    def _stream(self):
        pk = _packets(3)
        status = STATUS.pack(bytes([0xAC, 0xEB, 0xE6, 0x00, 0x55, 0xB4]), 3, 0, 0, 0)
        text = "ACK ABRIR\nDATA m1=-255 m2=0 pulgar=10 gesto=1\nBRIDGE EMG 1 canales=2 sensor=si\n".encode()
        blob = (text[:10] + build_frame(TYPE_DATA, sensor_payload(*pk[0])) + text[10:30]
                + build_frame(TYPE_STATUS, status) + build_frame(TYPE_DATA, sensor_payload(*pk[1]))
                + text[30:] + build_frame(TYPE_DATA, sensor_payload(*pk[2])) + "Mano lista ñ\n".encode())
        return blob, text + "Mano lista ñ\n".encode(), pk

    def test_split_keeps_text_in_order(self):
        blob, text, pk = self._stream()
        for step in (1, 3, 7, 64, len(blob)):           # trozos de cualquier tamaño, incluso byte a byte
            with self.subTest(step=step):
                parser = FrameParser()
                items, got = [], b""
                for i in range(0, len(blob), step):
                    new_items, new_text = parser.split(blob[i:i + step])
                    items += new_items
                    got += new_text
                self.assertEqual(got, text)
                self.assertEqual([p.seq for p in items if isinstance(p, SensorPacket)], [0, 1, 2])
                self.assertEqual(sum(isinstance(p, ReceiverStatus) for p in items), 1)
                self.assertEqual(parser.corrupt, 0)

    def test_text_only_stream_is_untouched(self):
        parser = FrameParser()
        text = "ACK ESTADO modo=MANUAL\nDATA m1=0\n".encode() + "ª é ü\n".encode()   # 0xAA dentro de UTF-8
        self.assertEqual(parser.split(text), ([], text))

    def test_frame_stream_messages(self):
        blob, _text, pk = self._stream()
        stream = FrameStream("conexion")
        messages, _ = stream.split(blob)
        self.assertEqual([m.payload.seq for m in messages], [0, 1, 2])
        frame = messages[0].payload
        self.assertEqual((frame.source, frame.seq_bits), ("conexion", 32))
        np.testing.assert_array_equal(frame.samples, pk[0][1])
        self.assertEqual(stream.status.current.mac, "AC:EB:E6:00:55:B4")
        self.assertEqual((stream.format, stream.frames), ((1, 2, 5), 4))


class FakePort:
    """Puerto serie de mentira: entrega los trozos dados y después avisa al hilo lector de que pare."""

    def __init__(self, chunks, link):
        self.chunks = list(chunks)
        self.link = link
        self.written = b""
        self.port = "COM99"
        self.is_open = True

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, _n):
        if not self.chunks:
            self.link._stop.set()
            return b""
        return self.chunks.pop(0)

    def write(self, data):
        self.written += data

    def close(self):
        self.is_open = False


class SerialLinkMixedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _run(self, chunks):
        from biomec.core.serial_link import SerialLink
        link = SerialLink()
        got = []
        link.message_received.connect(got.append)
        link._serial = FakePort(chunks, link)
        link._read_loop()
        return link, got

    def test_text_and_emg_on_the_same_connection(self):
        blob, _text, pk = MixedStreamTests()._stream()
        link, got = self._run([blob[i:i + 5] for i in range(0, len(blob), 5)])
        kinds = [m.kind for m in got]
        self.assertEqual(kinds.count(MessageKind.EMG), 3)
        self.assertEqual([m.text for m in got if m.kind is MessageKind.ACK], ["ABRIR"])
        self.assertEqual([m.values for m in got if m.kind is MessageKind.DATA],
                         [{"m1": -255.0, "m2": 0.0, "pulgar": 10.0, "gesto": 1.0}])
        self.assertIn("Mano lista ñ", [m.text for m in got if m.kind is MessageKind.TEXT])
        emg = [m.payload for m in got if m.kind is MessageKind.EMG]
        self.assertEqual({(f.source, f.seq_bits) for f in emg}, {("conexion", 32)})
        self.assertTrue(any("Llega EMG del sensor" in m.text for m in got if m.kind is MessageKind.SYSTEM))
        self.assertTrue(link._text_seen)
        link.message_received.disconnect()
        link.deleteLater()

    def test_receiver_without_bridge_is_detected(self):
        status = STATUS.pack(bytes([0xAC, 0xEB, 0xE6, 0x2C, 0xD7, 0xDC]), 0, 0, 0, 0)
        link, got = self._run([build_frame(TYPE_STATUS, status)] * 3)     # el receptor del equipo, sin sensor
        self.assertFalse(link._text_seen)
        port = link._serial
        port.is_open = True
        link._probe_bridge()
        self.assertEqual(port.written, b"@PING\n")         # pregunta sin dejar línea TX en la consola
        self.assertNotIn(MessageKind.TX, [m.kind for m in got])
        link._probe_result()                                # nadie contestó: es solo receptor
        errors = [m.text for m in got if m.kind is MessageKind.ERROR]
        self.assertTrue(errors and "firmware/puente_pc" in errors[-1])
        link.message_received.disconnect()
        link._serial = None
        link.deleteLater()

    def test_bridge_answers_so_no_warning(self):
        status = STATUS.pack(bytes(6), 0, 0, 0, 0)
        link, got = self._run([build_frame(TYPE_STATUS, status), b"BRIDGE PONG\n"])
        link._serial.is_open = True
        link._probe_result()
        self.assertFalse([m for m in got if m.kind is MessageKind.ERROR])
        link.message_received.disconnect()
        link._serial = None
        link.deleteLater()


class StatsTests(unittest.TestCase):
    def test_lost_and_restart(self):
        st = StreamStats()
        self.assertEqual(st.on_packet(10), (0, False))
        self.assertEqual(st.on_packet(11), (0, False))
        self.assertEqual(st.on_packet(14), (2, False))
        self.assertEqual(st.on_packet(0), (0, True))          # el sensor se reinició
        self.assertEqual((st.packets, st.lost, st.restarts), (4, 2, 1))

    def test_16_bit_wrap_is_not_a_restart(self):
        st = StreamStats()
        st.on_packet(65535, 16)
        self.assertEqual(st.on_packet(0, 16), (0, False))
        self.assertEqual(st.on_packet(2, 16), (1, False))

    def test_status_counts_from_connection(self):
        base = StatusBaseline()
        first = base.update(ReceiverStatus("M", 100, 5, 1, 0))
        self.assertEqual((first.received, first.invalid), (0, 0))
        later = base.update(ReceiverStatus("M", 150, 6, 1, 2))
        self.assertEqual((later.received, later.invalid, later.usb_dropped), (50, 1, 2))
        restarted = base.update(ReceiverStatus("M", 3, 0, 0, 0))   # la C6 se reinició: nueva base
        self.assertEqual(restarted.received, 0)


class RecorderTests(unittest.TestCase):
    def test_columns(self):
        self.assertEqual(column_ids(2), ["t_s", "seq", "idx", "ch1", "ch2"])
        self.assertEqual([simple_name(c) for c in column_ids(2)], ["tiempo", "seq", "idx", "data0", "data1"])

    def test_time_from_seq_with_gap_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = CsvRecorder(Path(tmp) / "x.csv", 2, 500.0, [("t_s", "tiempo"), ("ch1", "data0"), ("ch2", "data1")])
            s = np.arange(10).reshape(5, 2)
            rec.write(100, s)
            rec.write(102, s, lost=1)              # un paquete perdido: hueco de 5 muestras
            rec.write(0, s, restart=True)          # reinicio: el tiempo sigue donde iba
            rec.close()
            with open(rec.path, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], ["tiempo", "data0", "data1"])
            t = [float(r[0]) for r in rows[1:]]
            self.assertEqual(t[:5], [0.0, 0.002, 0.004, 0.006, 0.008])
            self.assertAlmostEqual(t[5], 0.020)     # muestras 10-14 (el paquete 101 se perdió)
            self.assertAlmostEqual(t[10], t[9] + 0.002)
            self.assertEqual((rec.rows, rec.lost), (15, 1))
            self.assertEqual(rows[1][1:], ["0", "1"])

    def test_invalid_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                CsvRecorder(Path(tmp) / "a.csv", 2, 500, [])
            with self.assertRaises(ValueError):
                CsvRecorder(Path(tmp) / "b.csv", 2, 500, [("ch1", "x"), ("ch2", "x")])
            with self.assertRaises(ValueError):
                CsvRecorder(Path(tmp) / "c.csv", 2, 500, [("ch3", "x")])


# ============================================================================ ventanas (Qt sin pantalla)

class WindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)      # ajustes en una carpeta temporal, no en los reales
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.tmp.name)
        from biomec.core.commands import CommandCatalog
        from biomec.core.serial_link import SerialLink
        from biomec.paths import config_file
        from biomec.ui.context import AppContext
        cls.ctx = AppContext(SerialLink(), CommandCatalog(config_file("commands.json")),
                             postures_path=Path(cls.tmp.name) / "posturas.json")
        import biomec.pages.emg_analyzer as analyzer_mod
        import biomec.pages.emg_viewer as viewer_mod

        class NoDialogs:          # un diálogo modal colgaría la prueba: si aparece, es un fallo
            @staticmethod
            def warning(*args, **_kw):
                raise AssertionError(f"diálogo inesperado: {args[1:]}")
            information = critical = warning

        cls._saved = (analyzer_mod.QMessageBox, viewer_mod.QMessageBox)
        analyzer_mod.QMessageBox = viewer_mod.QMessageBox = NoDialogs
        cls.widgets = []

    @classmethod
    def tearDownClass(cls):
        # Se destruye todo lo de Qt aquí, con la aplicación viva: dejarlo para el cierre de Python puede
        # acabar en un acceso inválido al salir (las pruebas pasan, pero el proceso devuelve error).
        from PySide6.QtCore import QCoreApplication, QEvent
        import biomec.pages.emg_analyzer as analyzer_mod
        import biomec.pages.emg_viewer as viewer_mod
        analyzer_mod.QMessageBox, viewer_mod.QMessageBox = cls._saved
        cls.ctx.emg_receiver.disconnect_port()
        for w in cls.widgets:
            w.close()
            w.deleteLater()
        cls.widgets.clear()
        cls.ctx.deleteLater()
        cls.ctx = None
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()
        cls.tmp.cleanup()

    def test_receiver_message_reaches_the_app(self):
        got = []
        self.ctx.message.connect(got.append)
        try:
            seq, samples = _packets(1, 70000)[0]
            self.ctx.emg_receiver.feed(build_frame(TYPE_DATA, sensor_payload(seq, samples, send_fails=2)))
        finally:
            self.ctx.message.disconnect(got.append)
        emg = [m for m in got if m.kind is MessageKind.EMG]
        self.assertEqual(len(emg), 1)
        frame = emg[0].payload
        self.assertEqual((frame.seq, frame.source, frame.send_fails), (70000, "receptor", 2))
        replay = make_message(MessageKind.EMG, emg[0].text)          # las sesiones grabadas lo reproducen igual
        np.testing.assert_array_equal(replay.payload.samples, samples)

    def test_viewer_shows_emg_from_the_app_connection(self):
        from biomec.pages.emg_viewer import EmgViewerPanel
        viewer = EmgViewerPanel(self.ctx)
        self.widgets.append(viewer)
        link = self.ctx.link
        status = STATUS.pack(bytes([0xAC, 0xEB, 0xE6, 0x00, 0x55, 0xB4]), 9, 0, 0, 0)
        blob = b"ACK ABRIR\n" + b"".join(build_frame(TYPE_DATA, sensor_payload(seq, s)) for seq, s in _packets(20, 5))
        messages, text = link.frames.split(blob + build_frame(TYPE_STATUS, status))
        self.assertEqual(text, b"ACK ABRIR\n")
        for m in messages:
            self.ctx.message.emit(m)
        self.assertEqual((viewer.source, viewer.channels, viewer.stats.packets, viewer.stats.lost),
                         ("conexion", 2, 20, 0))
        self.assertIs(viewer._frame_stream(), link.frames)
        viewer._update_diag()
        self.assertEqual(viewer.diag["mac"].text(), "AC:EB:E6:00:55:B4")
        link.frames.reset()
        viewer.shutdown()

    def test_viewer_records_and_analyzer_opens(self):
        from biomec.pages.emg_analyzer import EmgAnalyzerPanel
        from biomec.pages.emg_viewer import EmgViewerPanel
        viewer = EmgViewerPanel(self.ctx)
        analyzer = EmgAnalyzerPanel(self.ctx)
        self.widgets += [viewer, analyzer]
        out = Path(self.tmp.name) / "grabaciones"
        viewer.folder_edit.setText(str(out))
        viewer.name_edit.setText("prueba")
        fs = 500
        t = np.arange(3000) / fs
        sig = np.stack([300 * np.sin(2 * np.pi * 50 * t), 200 * np.sin(2 * np.pi * 80 * t)], 1)
        sig[1500:2000] += np.random.default_rng(2).normal(0, 200, (500, 2))
        sig = sig.astype(np.int16)
        frames = [build_frame(TYPE_DATA, sensor_payload(i, sig[k:k + 5])) for i, k in enumerate(range(0, 3000, 5))]
        rec = self.ctx.emg_receiver
        rec.feed(frames[0])
        self.assertEqual((viewer.channels, viewer.source), (2, "receptor"))
        viewer.columns_simple()
        self.assertTrue(viewer.start_recording())
        for f in frames[1:300] + frames[301:]:           # se pierde un paquete
            rec.feed(f)
        self.assertEqual((viewer.stats.lost, viewer.stats.packets), (1, 599))
        path = viewer.stop_recording()
        self.assertTrue(path.exists())
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.readline().strip(), "tiempo,data0,data1")
        viewer._analyze_last()                            # botón Analizar → el analizador abre el CSV
        self.assertIsNotNone(analyzer.result)
        self.assertEqual(len(analyzer.result.channels), 2)
        self.assertGreater(analyzer.result.channels[0].p50, 50)      # el canal 0 es casi todo 50 Hz
        dest = Path(self.tmp.name) / "analisis"
        dest.mkdir()
        figures = analyzer.export_figures(dest)
        self.assertEqual([p.name for p in figures], [f"figura_{k}.png" for k in range(1, 8)])
        self.assertTrue(all(p.stat().st_size > 1000 for p in figures))
        viewer.shutdown()


if __name__ == "__main__":
    unittest.main()
