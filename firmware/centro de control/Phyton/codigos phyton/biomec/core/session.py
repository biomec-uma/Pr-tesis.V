"""Grabación y reproducción de sesiones (la idea de rosbag / Foxglove).

Una sesión guarda TODO lo que pasa por la app (comandos enviados, respuestas,
telemetría, EMG y avisos) con su instante, para volver a verla después en la
misma app: el gemelo digital, las gráficas y la consola se mueven igual que
durante la prueba. Sirve para documentar ensayos, enseñar una prueba a quien
no estuvo y reunir datos para la IA.

Formato: JSON Lines (.jsonl), un objeto por línea, legible con cualquier
herramienta (Python, MATLAB jsondecode, un editor de texto…):

    {"formato": "biomec-sesion", "version": 1, "inicio": "2026-11-08T17:02:11", ...}   ← cabecera
    {"t": 0.412, "k": "TX", "x": "GESTO 3"}                                            ← t en s desde el inicio
    {"t": 0.431, "k": "ACK", "x": "GESTO 3 Índice y anular"}
    {"t": 0.480, "k": "DATA", "x": "indice=0 medio=-128 anular=0 pulgar=10 gesto=3"}
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .protocol import Message, MessageKind, make_message

FORMAT = "biomec-sesion"
VERSION = 1


@dataclass
class SessionEvent:
    t: float
    kind: MessageKind
    text: str

    def message(self) -> Message:
        return make_message(self.kind, self.text)


@dataclass
class Session:
    path: Path
    meta: dict
    events: list[SessionEvent]

    @property
    def duration(self) -> float:
        return self.events[-1].t if self.events else 0.0

    def count(self, kind: MessageKind) -> int:
        return sum(e.kind is kind for e in self.events)


class SessionRecorder:
    """Escribe cada mensaje en cuanto llega y vuelca a disco cada segundo (si la app se cierra
    de golpe, se pierde como mucho el último segundo)."""

    def __init__(self, path: str | Path, meta: dict | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w", encoding="utf-8")
        self._t0 = time.monotonic()
        self._flushed = 0.0
        self.count = 0
        header = {"formato": FORMAT, "version": VERSION, "inicio": datetime.now().isoformat(timespec="milliseconds")}
        header.update(meta or {})
        self._fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        self._fh.flush()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    @property
    def is_open(self) -> bool:
        return not self._fh.closed

    def write(self, msg: Message) -> None:
        if self._fh.closed:
            return
        t = self.elapsed
        line = {"t": round(t, 4), "k": msg.kind.value, "x": msg.text}
        self._fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.count += 1
        if t - self._flushed > 1.0:  # a disco al menos una vez por segundo
            self._fh.flush()
            self._flushed = t

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


def load_session(path: str | Path) -> Session:
    """Lee una sesión. Las líneas dañadas se saltan (p. ej. la última si la app se cerró de golpe)."""
    path = Path(path)
    with open(path, encoding="utf-8") as fh:
        first = fh.readline()
        try:
            meta = json.loads(first)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name} no es una sesión de BIOMEC: {error}") from None
        if not isinstance(meta, dict) or meta.get("formato") != FORMAT:
            raise ValueError(f"{path.name} no es una sesión de BIOMEC (falta la cabecera '{FORMAT}').")
        kinds = {k.value: k for k in MessageKind}
        events = []
        for raw in fh:
            try:
                item = json.loads(raw)
                events.append(SessionEvent(float(item["t"]), kinds[item["k"]], str(item["x"])))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
    events.sort(key=lambda e: e.t)
    return Session(path, meta, events)


def default_name(simulated: bool) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"sesion_{stamp}{'_simulacion' if simulated else ''}.jsonl"
