"""Receptor EMG del equipo por USB y grabación de la señal en CSV (lo que hace el «Visor EMG» del equipo).

El receptor es una ESP32-C6 (firmware/maestro del repositorio del equipo, rama de Dylan) que recibe por
ESP-NOW los paquetes del sensor (ESP32-C3 + ADS1198) y los reenvía al PC en marcos binarios:

    AA 55 | tipo (1) | longitud (1) | contenido (longitud bytes) | XOR (1)      todo en little-endian
    XOR = tipo ^ longitud ^ todos los bytes del contenido

    0x01 DATOS   el paquete del sensor tal cual:
                 version u8, nChnls u8, batch u8, seq u32, sendFails u16, data[batch][nChnls] i16
    0x02 ESTADO  diagnóstico de la C6 (1 por segundo):
                 mac[6], recibidos u32, invalidos u32, perdidosCola u32, descartadosUSB u32
    otros        se ignoran (así el protocolo puede crecer sin romper nada)

EmgReceiver convierte cada paquete en un Message EMG, igual que las líneas «EMG …» del puente: así la señal
del receptor llega a todas las ventanas (gráficas, Entrenamiento, sesiones grabadas) sin cambiar nada más.
"""

from __future__ import annotations

import csv
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import serial
from PySide6.QtCore import QObject, Signal

from .protocol import EmgFrame, Message, MessageKind

SYNC = b"\xAA\x55"
TYPE_DATA = 0x01
TYPE_STATUS = 0x02
SENSOR_VERSION = 1
SENSOR_HEADER = struct.Struct("<BBBIH")      # version, nChnls, batch, seq, sendFails = 9 bytes
STATUS = struct.Struct("<6sIIII")            # mac, recibidos, invalidos, perdidosCola, descartadosUSB
MAX_PENDING = 1 << 16                        # bytes sin marco válido que se guardan como mucho


@dataclass
class SensorPacket:
    version: int
    channels: int
    batch: int
    seq: int
    send_fails: int
    samples: np.ndarray        # (batch, canales) int16


@dataclass
class ReceiverStatus:
    mac: str
    received: int
    invalid: int
    queue_full: int
    usb_dropped: int


class FrameParser:
    """Separa los marcos de un flujo de bytes: pueden llegar partidos, juntos o con basura en medio."""

    def __init__(self):
        self._buf = bytearray()
        self.corrupt = 0      # XOR incorrecto o contenido con un formato que no cuadra
        self.unknown = 0      # tipos de marco que esta versión no conoce

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> list[SensorPacket | ReceiverStatus]:
        """Marcos completos que hay en data; lo que no es un marco se descarta."""
        return self.split(data)[0]

    def split(self, data: bytes) -> tuple[list[SensorPacket | ReceiverStatus], bytes]:
        """Como feed, pero devuelve también los bytes que no son de ningún marco: las líneas de texto de la
        mano cuando el puente manda por el mismo USB el EMG (marcos) y las respuestas (texto)."""
        b = self._buf
        b += data
        out: list[SensorPacket | ReceiverStatus] = []
        text = bytearray()
        pos = 0
        while True:
            start = b.find(SYNC, pos)
            if start < 0:                    # sin firma: todo es texto menos un AA final (puede ser medio marco)
                keep = len(b) - 1 if b and b[-1] == SYNC[0] else len(b)
                keep = max(pos, keep)
                text += b[pos:keep]
                pos = keep
                break
            text += b[pos:start]
            if len(b) - start < 5:           # cabecera incompleta
                pos = start
                break
            kind, n = b[start + 2], b[start + 3]
            end = start + 4 + n
            if len(b) <= end:                # marco incompleto
                pos = start
                break
            payload = bytes(b[start + 4:end])
            chk = kind ^ n
            for x in payload:
                chk ^= x
            if chk != b[end]:                # un AA 55 casual dentro de los datos, o basura
                self.corrupt += 1
                text += b[start:start + 1]
                pos = start + 1
                continue
            item = self._decode(kind, payload)
            if item is not None:
                out.append(item)
            pos = end + 1
        del b[:pos]
        if len(b) > MAX_PENDING:
            del b[:-1]
        return out, bytes(text)

    def _decode(self, kind: int, c: bytes):
        if kind == TYPE_DATA:
            if len(c) < SENSOR_HEADER.size:
                self.corrupt += 1
                return None
            version, nch, batch, seq, fails = SENSOR_HEADER.unpack_from(c)
            if version != SENSOR_VERSION or nch == 0 or len(c) != SENSOR_HEADER.size + nch * batch * 2:
                self.corrupt += 1
                return None
            samples = np.frombuffer(c, dtype="<i2", offset=SENSOR_HEADER.size).reshape(batch, nch).copy()
            return SensorPacket(version, nch, batch, seq, fails, samples)
        if kind == TYPE_STATUS:
            if len(c) < STATUS.size:
                self.corrupt += 1
                return None
            mac, rec, inv, queue, usb = STATUS.unpack_from(c)
            return ReceiverStatus(":".join(f"{x:02X}" for x in mac), rec, inv, queue, usb)
        self.unknown += 1
        return None


def build_frame(kind: int, payload: bytes) -> bytes:
    """Marco AA 55 completo (lo usan las pruebas y el simulador)."""
    chk = kind ^ len(payload)
    for x in payload:
        chk ^= x
    return SYNC + bytes([kind, len(payload)]) + payload + bytes([chk])


def sensor_payload(seq: int, samples: np.ndarray, send_fails: int = 0, version: int = SENSOR_VERSION) -> bytes:
    samples = np.asarray(samples, dtype="<i2")
    batch, nch = samples.shape
    return SENSOR_HEADER.pack(version, nch, batch, seq, send_fails) + samples.tobytes()


class FrameStream:
    """Marcos AA 55 de una conexión USB → Messages EMG, más el estado de la C6 que los manda.

    Hay uno por cada entrada: el puerto del receptor en el Visor EMG (EmgReceiver, source "receptor") y la
    conexión principal de la app (SerialLink, source "conexion"), donde los marcos llegan mezclados con las
    líneas de texto de la mano si el puente tiene el firmware que hace de puente y de receptor a la vez.
    """

    def __init__(self, source: str):
        self.source = source
        self.lock = threading.Lock()
        self.parser = FrameParser()
        self.status = StatusBaseline()
        self.format: tuple[int, int, int] = (0, 0, 0)   # versión, canales, muestras por paquete
        self.frames = 0                                  # marcos válidos (datos o estado) desde reset()

    def reset(self) -> None:
        with self.lock:
            self.parser = FrameParser()
            self.status = StatusBaseline()
            self.format = (0, 0, 0)
            self.frames = 0

    def feed(self, data: bytes) -> list[Message]:
        return self.split(data)[0]

    def split(self, data: bytes) -> tuple[list[Message], bytes]:
        """(Messages EMG de los marcos completos, bytes que no son de ningún marco)."""
        messages: list[Message] = []
        with self.lock:
            items, text = self.parser.split(data)
            for item in items:
                self.frames += 1
                if isinstance(item, ReceiverStatus):
                    self.status.update(item)
                    continue
                self.format = (item.version, item.channels, item.batch)
                frame = EmgFrame(item.seq, item.samples.astype(np.int32), send_fails=item.send_fails,
                                 source=self.source, seq_bits=32)
                line = f"{item.seq} {item.channels} " + " ".join(map(str, item.samples.ravel().tolist()))
                messages.append(Message(MessageKind.EMG, line, payload=frame))
        return messages, text


class StreamStats:
    """Paquetes recibidos, perdidos (saltos de seq) y reinicios del sensor (seq vuelve atrás)."""

    MAX_GAP = 10_000      # un salto mayor (o hacia atrás) es un reinicio del sensor, no paquetes perdidos

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.packets = 0
        self.lost = 0
        self.restarts = 0
        self.last_seq: int | None = None
        self.send_fails: int | None = None

    def on_packet(self, seq: int, seq_bits: int = 32, send_fails: int | None = None) -> tuple[int, bool]:
        """Cuenta un paquete. Devuelve (paquetes perdidos justo antes de este, ¿el sensor se reinició?)."""
        lost, restart = 0, False
        if self.last_seq is not None:
            gap = (seq - self.last_seq) % (1 << seq_bits)
            if gap == 0 or gap > self.MAX_GAP:
                restart = True
                self.restarts += 1
            elif gap > 1:
                lost = gap - 1
                self.lost += lost
        self.last_seq = seq
        self.packets += 1
        if send_fails is not None:
            self.send_fails = send_fails
        return lost, restart

    @property
    def lost_pct(self) -> float:
        total = self.packets + self.lost
        return 100 * self.lost / total if total else 0.0


class StatusBaseline:
    """Los contadores de la C6 cuentan desde que se encendió; se muestran desde que se conecta la app."""

    def __init__(self):
        self.base: ReceiverStatus | None = None
        self.current: ReceiverStatus | None = None
        self.time = 0.0

    def update(self, st: ReceiverStatus, now: float | None = None) -> ReceiverStatus:
        fields_ = ("received", "invalid", "queue_full", "usb_dropped")
        if self.base is None or any(getattr(st, f) < getattr(self.base, f) for f in fields_):
            self.base = st            # primera vez, o la C6 se reinició
        self.current = ReceiverStatus(st.mac, *(getattr(st, f) - getattr(self.base, f) for f in fields_))
        self.time = time.monotonic() if now is None else now
        return self.current


# ======================================================================== grabación en CSV
def column_ids(channels: int) -> list[str]:
    """Columnas disponibles: tiempo, nº de paquete, posición dentro del paquete y un chN por canal."""
    return ["t_s", "seq", "idx"] + [f"ch{i + 1}" for i in range(channels)]


def simple_name(cid: str) -> str:
    """Nombres del formato «tiempo, data0, data1…» (el que lee el Analizador EMG del equipo)."""
    if cid == "t_s":
        return "tiempo"
    if cid.startswith("ch") and cid[2:].isdigit():
        return f"data{int(cid[2:]) - 1}"
    return cid


class CsvRecorder:
    """Graba en CSV solo las columnas elegidas. El tiempo sale de seq y de la frecuencia del ADC, no del reloj
    del PC: los paquetes perdidos dejan su hueco y, si el sensor se reinicia, el tiempo sigue donde iba.

    columns: lista de (id, nombre en la cabecera), con id de column_ids()."""

    def __init__(self, path: str | Path, channels: int, fs: float, columns: list[tuple[str, str]]):
        available = column_ids(channels)
        if not columns:
            raise ValueError("Marca al menos una columna para guardar.")
        unknown = [cid for cid, _ in columns if cid not in available]
        if unknown:
            raise ValueError(f"Columnas desconocidas: {', '.join(unknown)}")
        names = [name.strip() or cid for cid, name in columns]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError("Hay columnas con el mismo nombre: " + ", ".join(repeated))
        self.path = Path(path)
        self.channels, self.fs = channels, fs
        self.names = names
        self._idx = [available.index(cid) for cid, _ in columns]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(names)
        self.rows = 0
        self.lost = 0
        self.last_t = 0.0
        self._t_offset = 0.0
        self._pos: int | None = None
        self._started = time.monotonic()
        self._flushed = self._started

    def write(self, seq: int, samples: np.ndarray, lost: int = 0, restart: bool = False) -> None:
        n = len(samples)
        if self._pos is None:
            self._pos = 0
        elif restart:                      # el sensor empezó de 0: seguimos la cuenta donde íbamos
            self._t_offset = self.last_t + 1 / self.fs
            self._pos = 0
        elif lost:                         # hueco de los paquetes perdidos (del mismo tamaño que este)
            self._pos += lost * n
            self.lost += lost
        rows = []
        t = self.last_t
        for i, row in enumerate(np.asarray(samples).tolist()):
            t = self._t_offset + (self._pos + i) / self.fs
            full = [f"{t:.4f}", seq, i] + row
            rows.append([full[j] for j in self._idx])
        self._w.writerows(rows)
        self._pos += n
        self.last_t = t
        self.rows += n
        now = time.monotonic()
        if now - self._flushed >= 1:
            self._f.flush()
            self._flushed = now

    @property
    def seconds(self) -> float:
        """Segundos de señal grabados."""
        return self.rows / self.fs

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def close(self) -> None:
        if not self._f.closed:
            self._f.flush()
            self._f.close()


# ======================================================================== conexión USB
def open_port(port: str) -> serial.Serial:
    """Como el Visor EMG: sin tocar DTR/RTS (no reinicia la C6) y vaciando lo que hubiera pendiente."""
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = 115200          # con USB nativo da igual, pero hay que poner alguno
    ser.timeout = 0.05
    ser.dtr = False
    ser.rts = False
    ser.open()
    ser.reset_input_buffer()
    return ser


def port_error_text(port: str, error: Exception) -> str:
    text = str(error)
    if any(k in text.lower() for k in ("denegado", "denied", "permissionerror", "acceso")):
        return (f"El puerto {port} está ocupado. Cierra el monitor serie de PlatformIO / Arduino, el Visor EMG "
                f"del equipo u otro programa que lo esté usando.")
    return f"No se pudo abrir {port}: {text}"


class EmgReceiver(QObject):
    """Conexión con el receptor EMG del equipo. Lee en un hilo aparte y se reconecta solo si se desenchufa."""

    message_received = Signal(object)        # Message EMG (payload EmgFrame), como las líneas EMG del puente
    connection_changed = Signal(bool, str)   # conectado, puerto
    notice = Signal(str, str)                # ("ok" | "warn" | "error", texto)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stream = FrameStream("receptor")
        self.online = False                              # puerto abierto ahora mismo (False mientras reintenta)
        self._port = ""
        self._serial: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def connected(self) -> bool:
        return self._thread is not None

    @property
    def port(self) -> str:
        return self._port

    # atajos al FrameStream (los usan el Visor EMG y las pruebas)
    @property
    def lock(self) -> threading.Lock:
        return self.stream.lock

    @property
    def parser(self) -> FrameParser:
        return self.stream.parser

    @property
    def status(self) -> StatusBaseline:
        return self.stream.status

    @property
    def format(self) -> tuple[int, int, int]:
        return self.stream.format

    def connect_port(self, port: str) -> bool:
        self.disconnect_port()
        try:
            ser = open_port(port)
        except (serial.SerialException, OSError, ValueError) as error:
            self.notice.emit("error", port_error_text(port, error))
            return False
        self.stream.reset()
        self._port, self._serial, self.online = port, ser, True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="emg-receptor", daemon=True)
        self._thread.start()
        self.connection_changed.emit(True, port)
        return True

    def disconnect_port(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)
        self._thread = None
        self._close_serial()
        self.online = False
        port, self._port = self._port, ""
        self.connection_changed.emit(False, port)

    def _close_serial(self) -> None:
        ser, self._serial = self._serial, None
        if ser is not None:
            try:
                ser.close()
            except (serial.SerialException, OSError):
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._serial is None:
                    self._serial = open_port(self._port)
                    with self.stream.lock:
                        self.stream.parser.reset()
                    self.online = True
                    self.notice.emit("ok", f"Receptor EMG: reconectado a {self._port}.")
                chunk = self._serial.read(max(1, self._serial.in_waiting))
            except (serial.SerialException, OSError, AttributeError, TypeError, ValueError):
                if self._serial is not None:
                    self.notice.emit("warn", f"Receptor EMG: {self._port} desconectado, reintentando…")
                self._close_serial()
                self.online = False
                self._stop.wait(1.0)
                continue
            if chunk:
                self.feed(chunk)
        self._close_serial()

    def feed(self, data: bytes) -> None:
        """Procesa bytes recibidos (el hilo lector, o las pruebas sin puerto)."""
        for message in self.stream.feed(data):
            self.message_received.emit(message)
