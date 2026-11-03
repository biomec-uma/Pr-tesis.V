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
    cualquier otra cosa   Texto libre, se muestra en la consola

Para añadir un tipo nuevo: añade una constante a MessageKind y una
entrada en _PREFIXES. Las páginas que no lo usen simplemente lo ignoran.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageKind(str, Enum):
    DATA = "DATA"
    ACK = "ACK"
    ERROR = "ERR"
    BRIDGE = "BRIDGE"
    TEXT = "TEXT"      # línea sin prefijo conocido
    TX = "TX"          # comando enviado por nosotros (para el registro)
    SYSTEM = "SYSTEM"  # eventos internos de la app (conexión, avisos...)


_PREFIXES = {
    "DATA": MessageKind.DATA,
    "ACK": MessageKind.ACK,
    "ERR": MessageKind.ERROR,
    "BRIDGE": MessageKind.BRIDGE,
}


@dataclass
class Message:
    kind: MessageKind
    text: str
    values: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


def parse_line(line: str) -> Message:
    line = line.strip()
    head, _, rest = line.partition(" ")
    kind = _PREFIXES.get(head.upper(), MessageKind.TEXT)

    if kind is MessageKind.TEXT:
        return Message(kind, line)
    if kind is MessageKind.DATA:
        return Message(kind, rest, _parse_values(rest))
    return Message(kind, rest)


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
