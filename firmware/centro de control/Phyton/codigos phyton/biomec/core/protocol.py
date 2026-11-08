"""Protocolo de texto entre el PC y la ESP32-C6 puente.

Cada mensaje es UNA línea de texto terminada en '\\n'.

PC -> puente
    COMANDO [args...]     Se reenvía tal cual a la mano por ESP-NOW.
    @COMANDO [args...]    Lo procesa el propio puente (no viaja a la mano).

Puente / mano -> PC (la primera palabra indica el tipo)
    DATA clave=valor ...  Telemetría numérica  -> gráficas
    ACK COMANDO ...       Confirmación de un comando
    ERR texto             Error
    BRIDGE texto          Mensaje informativo del puente
    EMG seq canales v...  Muestras EMG (las reenvía el puente si se activa con @EMG 1):
                          seq = nº de paquete, canales = nº de canales y después las
                          muestras intercaladas: s1c1 s1c2 … s2c1 s2c2 … (cuentas del ADC)
    cualquier otra cosa   Texto libre, se muestra en la consola

Para añadir un tipo nuevo: añade una constante a MessageKind y una
entrada en _PREFIXES. Las páginas que no lo usen simplemente lo ignoran.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import numpy as np


class MessageKind(str, Enum):
    DATA = "DATA"
    ACK = "ACK"
    ERROR = "ERR"
    BRIDGE = "BRIDGE"
    EMG = "EMG"        # muestras de los electrodos (payload = EmgFrame)
    TEXT = "TEXT"      # línea sin prefijo conocido
    TX = "TX"          # comando enviado por nosotros (para el registro)
    SYSTEM = "SYSTEM"  # eventos internos de la app (conexión, avisos...)


_PREFIXES = {
    "DATA": MessageKind.DATA,
    "ACK": MessageKind.ACK,
    "ERR": MessageKind.ERROR,
    "BRIDGE": MessageKind.BRIDGE,
    "EMG": MessageKind.EMG,
}


@dataclass
class EmgFrame:
    """Un paquete de muestras EMG: samples tiene forma (muestras, canales)."""
    seq: int
    samples: np.ndarray

    @property
    def channels(self) -> int:
        return self.samples.shape[1]


@dataclass
class Message:
    kind: MessageKind
    text: str
    values: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    payload: object = None  # datos ya interpretados según el tipo (EMG: EmgFrame)


def parse_line(line: str) -> Message:
    line = line.strip()
    head, _, rest = line.partition(" ")
    kind = _PREFIXES.get(head.upper(), MessageKind.TEXT)
    if kind is MessageKind.TEXT:
        return Message(kind, line)
    return make_message(kind, rest)


def make_message(kind: MessageKind, text: str) -> Message:
    """Reconstruye un Message a partir de su tipo y su texto (sin el prefijo).

    Lo usan parse_line y la reproducción de sesiones grabadas.
    """
    if kind is MessageKind.DATA:
        return Message(kind, text, _parse_values(text))
    if kind is MessageKind.EMG:
        frame = parse_emg(text)
        if frame is None:  # mal formado: se muestra como texto para no perderlo
            return Message(MessageKind.TEXT, f"EMG {text}")
        return Message(kind, text, payload=frame)
    return Message(kind, text)


def parse_emg(payload: str) -> EmgFrame | None:
    """'7 2 10 -3 12 -5' -> EmgFrame(seq=7, samples=[[10, -3], [12, -5]])"""
    parts = payload.split()
    if len(parts) < 3:
        return None
    try:
        seq, channels = int(parts[0]), int(parts[1])
        values = np.array(parts[2:], dtype=np.int32)
    except ValueError:
        return None
    if not 1 <= channels <= 16 or values.size % channels:
        return None
    return EmgFrame(seq, values.reshape(-1, channels))


def format_emg(seq: int, samples: np.ndarray) -> str:
    """Inverso de parse_emg, con el prefijo: lo usan el simulador y las pruebas."""
    samples = np.asarray(samples, dtype=np.int32)
    return f"EMG {seq} {samples.shape[1]} " + " ".join(map(str, samples.ravel().tolist()))


def _parse_values(payload: str) -> dict[str, float]:
    """'pot=512 m1=33.5 t=21' -> {'pot': 512.0, 'm1': 33.5, 't': 21.0}"""
    values = {}
    for token in payload.replace(",", " ").split():
        key, sep, raw = token.partition("=")
        if not sep:
            continue
        try:
            values[key.strip()] = float(raw)
        except ValueError:
            pass  # valor no numérico: se ignora sin romper el resto
    return values
