"""Señales graficables: el catálogo (config/signals.json) y el almacén que las guarda en tiempo real.

    mensajes (DATA, ACK, EMG, TX) ──► SignalStore ──► cualquier número de ventanas de Gráficas
                                        │  series por clave (tiempo, valor)
                                        │  señales derivadas: consignas, % cerrado estimado, saturación, EMG filtrado
                                        └  marcas: comandos (inicio y fin de la ejecución) y movimientos de la demo

Solo numpy y la biblioteca estándar: se prueba sin interfaz (tests/test_signals.py).
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .gestures import CERRADO, GESTOS
from .protocol import MessageKind

MAX_POINTS = 20000        # por señal (40 s de EMG a 500 Hz; horas de telemetría)
MAX_MARKERS = 80
MOTOR_KEYS = ("indice", "medio", "anular")
MOVE_COMMANDS = {"GESTO", "ABRIR", "CERRAR", "DEDO", "POSTURA"}   # mueven los motores: tienen inicio y fin
NO_MARKER = {"STREAM", "PERIODO", "ESTADO", "GESTOS"}            # consultas y ajustes: no se marcan (ruido)
NO_MOTION_S = 0.6         # si en este tiempo ningún motor arranca, el comando no movió nada ("ya estaba")
OWN_MOVE_GAP_S = 1.0      # un cambio de gesto sin comando reciente es un movimiento de la propia mano (demo)
SATURATED_PWM = 250
DEFAULT_PHASE_S = 3.0     # tiempoFase del firmware (TIEMPO / ESTADO lo actualizan)
RAMP_S = 0.5
DEFAULT_CLOSE_TIME_S = 1.5
EMG_FS = 500


# ================================================================== catálogo
@dataclass(frozen=True)
class SignalGroup:
    id: str
    title: str
    unit: str = ""
    range: tuple[float, float] | None = None
    axis: str = ""               # etiqueta corta del eje vertical

    @property
    def axis_label(self) -> str:
        return self.axis or self.title


@dataclass(frozen=True)
class SignalDef:
    key: str
    name: str
    group: str
    source: str = "mano"
    status: str = "disponible"   # "disponible" | "pendiente" (prevista: la mano aún no la envía)
    note: str = ""
    short: str = ""              # nombre corto para la leyenda

    @property
    def available(self) -> bool:
        return self.status != "pendiente"

    @property
    def short_name(self) -> str:
        return self.short or self.name


class SignalCatalog:
    """Qué señales existen, cómo se llaman y en qué gráfica (grupo = unidad) van."""

    def __init__(self, path: str | Path | None = None):
        self.groups: dict[str, SignalGroup] = {}
        self.signals: dict[str, SignalDef] = {}
        if path is not None:
            self.load(Path(path))
        if "otros" not in self.groups:
            self.groups["otros"] = SignalGroup("otros", "Otras señales")

    def load(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        for g in data.get("grupos", []):
            rng = g.get("rango")
            self.groups[g["id"]] = SignalGroup(g["id"], g.get("titulo", g["id"]), g.get("unidad", ""),
                                               (float(rng[0]), float(rng[1])) if rng else None, g.get("eje", ""))
        for s in data.get("senales", []):
            n = int(s.get("canales", 0))
            name, short = s.get("nombre", s["clave"]), s.get("corto", "")
            variants = [(s["clave"].format(n=i), name.format(n=i), short.format(n=i)) for i in range(1, n + 1)] \
                if n else [(s["clave"], name, short)]
            for key, name_i, short_i in variants:
                self.signals[key] = SignalDef(key, name_i, s.get("grupo", "otros"), s.get("origen", "mano"),
                                              s.get("estado", "disponible"), s.get("nota", ""), short_i)

    def define(self, key: str) -> SignalDef:
        """La definición de una clave; una clave desconocida se registra sobre la marcha en 'otros'."""
        sd = self.signals.get(key)
        if sd is None:
            sd = SignalDef(key, key, "otros", "mano")
            self.signals[key] = sd
        return sd

    def group_of(self, key: str) -> SignalGroup:
        return self.groups.get(self.define(key).group) or self.groups["otros"]

    def by_group(self, keys) -> list[tuple[SignalGroup, list[str]]]:
        """Las claves agrupadas por gráfica, en el orden del catálogo."""
        order = list(self.groups)
        buckets: dict[str, list[str]] = {}
        for key in keys:
            buckets.setdefault(self.group_of(key).id, []).append(key)
        return [(self.groups[g], buckets[g]) for g in order if g in buckets]


# ===================================================================== datos
class Series:
    __slots__ = ("key", "t", "y")

    def __init__(self, key: str):
        self.key = key
        self.t: deque[float] = deque(maxlen=MAX_POINTS)
        self.y: deque[float] = deque(maxlen=MAX_POINTS)

    def append(self, t: float, y: float) -> None:
        self.t.append(t)
        self.y.append(y)

    @property
    def last(self) -> float | None:
        return self.y[-1] if self.y else None

    def window(self, start: float) -> tuple[np.ndarray, np.ndarray]:
        """Los puntos desde 'start' (la deque se vuelca una vez por redibujado)."""
        t = np.fromiter(self.t, float, len(self.t))
        y = np.fromiter(self.y, float, len(self.y))
        i = int(np.searchsorted(t, start))
        return t[i:], y[i:]


@dataclass
class Marker:
    t0: float
    text: str
    kind: str = "cmd"              # "cmd": comando enviado · "hand": movimiento iniciado por la propia mano (demo)
    t1: float | None = None        # fin de la ejecución (cuando los motores vuelven a 0)
    open: bool = False             # todavía ejecutándose: la zona sombreada crece hasta el último dato

    @property
    def label(self) -> str:
        return self.text.lstrip("@")


class SignalStore:
    """Guarda todo lo graficable con un reloj común (segundos desde que se creó o se borró)."""

    def __init__(self, catalog: SignalCatalog, clock: Callable[[], float] = time.monotonic,
                 close_time_s: float = DEFAULT_CLOSE_TIME_S, time_scale: Callable[[], float] = lambda: 1.0):
        self.catalog = catalog
        self._clock = clock
        self._time_scale = time_scale
        self.close_time_s = close_time_s
        self.series: dict[str, Series] = {}
        self.markers: deque[Marker] = deque()
        self.phase_s = DEFAULT_PHASE_S
        self.emg_fs = EMG_FS
        self.emg_channels = 0
        self.t0 = clock()
        self._reset_state()

    def _reset_state(self) -> None:
        self._open: Marker | None = None
        self._open_activity = False
        self._last_move_tx = -1e9
        self._last_gesture: float | None = None
        self._setpoints: dict[str, float] = {f"consigna_{d}": 0.0 for d in MOTOR_KEYS}
        self._setpoints["consigna_pulgar"] = 10.0
        self._flex = {d: 0.0 for d in MOTOR_KEYS}
        self._last_data_t: float | None = None
        self._sat_since: dict[str, float | None] = {d: None for d in MOTOR_KEYS}
        self._emg_pre = None
        self._emg_t = None

    # ------------------------------------------------------------- reloj
    def now(self) -> float:
        return self._clock() - self.t0

    def latest(self) -> float:
        """Instante del último dato o marca (el borde derecho de las gráficas)."""
        t = max((s.t[-1] for s in self.series.values() if s.t), default=0.0)
        if self.markers:
            t = max(t, self.markers[-1].t0)
        return t

    def clear(self) -> None:
        self.series.clear()
        self.markers.clear()
        self.t0 = self._clock()
        self.emg_channels = 0
        self._reset_state()

    def get(self, key: str) -> Series:
        s = self.series.get(key)
        if s is None:
            self.catalog.define(key)
            s = self.series[key] = Series(key)
        return s

    def keys_with_data(self) -> list[str]:
        return [k for k, s in self.series.items() if s.t]

    # ---------------------------------------------------------- mensajes
    def on_message(self, msg) -> None:
        kind = msg.kind
        if kind is MessageKind.DATA:
            if msg.values:
                self._on_data(msg.values)
        elif kind is MessageKind.TX:
            self._on_tx(msg.text)
        elif kind is MessageKind.ACK:
            self._on_ack(msg.text)
        elif kind is MessageKind.EMG and msg.payload is not None:
            self._on_emg(msg.payload.samples)

    # ---- comandos: marcas con inicio y fin
    def _on_tx(self, text: str) -> None:
        t = self.now()
        name = text.split()[0].upper() if text.split() else ""
        if name in NO_MARKER or name.startswith("@") or not name:
            return
        if name in MOVE_COMMANDS:
            self._close_open(t)
            m = Marker(t, text, "cmd", open=True)
            self._open, self._open_activity = m, False
            self._last_move_tx = t
            self._add_marker(m)
        elif name == "PARAR":
            self._close_open(t)
            self._add_marker(Marker(t, text, "cmd"))
        else:
            self._add_marker(Marker(t, text, "cmd"))

    def _close_open(self, t: float | None) -> None:
        m, self._open = self._open, None
        if m is None:
            return
        m.open = False
        m.t1 = t if (self._open_activity and t is not None and t > m.t0) else None

    def _add_marker(self, m: Marker) -> None:
        self.markers.append(m)
        while len(self.markers) > MAX_MARKERS:
            old = self.markers.popleft()
            if old is self._open:
                self._open = None

    # ---- telemetría de la mano
    def _on_data(self, values: dict[str, float]) -> None:
        t = self.now()
        for key, value in values.items():
            self.get(key).append(t, value)
        motors = [values[d] for d in MOTOR_KEYS if d in values]
        active = any(abs(v) > 0 for v in motors)

        # fin de la ejecución de un comando: los motores arrancaron y han vuelto a 0
        m = self._open
        if m is not None:
            if active:
                self._open_activity = True
            elif self._open_activity:
                self._close_open(t)
            elif t - m.t0 > NO_MOTION_S:   # no movió nada (la mano ya estaba así)
                self._close_open(None)

        # movimientos que inicia la propia mano (modo demo): cambia el gesto sin comando reciente
        g = values.get("gesto")
        if g is not None:
            if self._last_gesture is not None and g != self._last_gesture and t - self._last_move_tx > OWN_MOVE_GAP_S:
                n = int(g)
                name = GESTOS[n - 1].nombre if 1 <= n <= len(GESTOS) else "postura propia"
                self._add_marker(Marker(t, f"demo · {name}", "hand"))
            self._last_gesture = g

        # derivadas: consignas, % cerrado estimado y saturación (se muestrean al ritmo de la telemetría)
        for key, value in self._setpoints.items():
            self.get(key).append(t, value)
        if motors:
            dt = 0.0 if self._last_data_t is None else min((t - self._last_data_t) * self._time_scale(), 0.25)
            self._last_data_t = t
            limit = self.phase_s + RAMP_S
            for d in MOTOR_KEYS:
                if d not in values:
                    continue
                pwm = values[d]
                self._flex[d] = min(max(self._flex[d] - pwm / 255 * dt / self.close_time_s, 0.0), 1.0)
                self.get(f"flex_{d}").append(t, self._flex[d] * 100)
                if abs(pwm) >= SATURATED_PWM:
                    since = self._sat_since[d]
                    self._sat_since[d] = t if since is None else since
                    self.get(f"sat_{d}").append(t, 1.0 if t - self._sat_since[d] > limit else 0.0)
                else:
                    self._sat_since[d] = None
                    self.get(f"sat_{d}").append(t, 0.0)

    # ---- respuestas: consignas y parámetros de la mano
    def _on_ack(self, text: str) -> None:
        parts = text.split()
        if not parts:
            return
        head, args = parts[0].upper(), parts[1:]
        sp = self._setpoints
        if head in ("GESTO", "ABRIR", "CERRAR"):
            try:
                n = int(args[0]) if head == "GESTO" else (1 if head == "ABRIR" else len(GESTOS))
                G = GESTOS[n - 1]
            except (IndexError, ValueError):
                return
            for d, pos in zip(MOTOR_KEYS, (G.indice, G.medio, G.anular)):
                sp[f"consigna_{d}"] = 1.0 if pos == CERRADO else 0.0
            sp["consigna_pulgar"] = float(G.pulgar)
        elif head == "DEDO" and len(args) >= 2 and args[0].lower() in MOTOR_KEYS:
            if "(ya" in text:
                self._close_open(None)
            sp[f"consigna_{args[0].lower()}"] = 1.0 if args[1].upper() == "CERRAR" else 0.0
        elif head == "POSTURA" and len(args) >= 4:
            for d, letter in zip(MOTOR_KEYS, args[:3]):
                if letter.upper() in ("A", "C"):
                    sp[f"consigna_{d}"] = 1.0 if letter.upper() == "C" else 0.0
            try:
                sp["consigna_pulgar"] = float(args[3])
            except ValueError:
                pass
        elif head == "PULGAR" and args:
            try:
                sp["consigna_pulgar"] = float(args[0])
            except ValueError:
                pass
        elif head == "TIEMPO" and args:
            try:
                self.phase_s = int(args[0]) / 1000
            except ValueError:
                pass
        elif head == "ESTADO":
            fields = dict(tok.split("=", 1) for tok in args if "=" in tok)
            try:
                self.phase_s = int(fields.get("tiempo", self.phase_s * 1000)) / 1000
            except ValueError:
                pass
            if fields.get("fase") == "parado":  # la mano dice dónde está cada dedo: se corrige la estimación
                for d in MOTOR_KEYS:
                    if fields.get(d) == "abierto":
                        self._flex[d] = 0.0
                    elif fields.get(d) == "cerrado":
                        self._flex[d] = 1.0

    # ---- EMG: bruto y filtrado, canal a canal
    def _on_emg(self, samples: np.ndarray) -> None:
        n, channels = samples.shape
        if channels != self.emg_channels or self._emg_pre is None:
            from .emg import Preprocessor  # importación tardía: numpy pesado solo si llega EMG
            self.emg_channels = channels
            self._emg_pre = Preprocessor(self.emg_fs, channels)
            self._emg_t = None
        t_end = self.now()
        # cada muestra con su instante: la última ahora, las anteriores separadas 1/fs
        start = t_end - (n - 1) / self.emg_fs
        if self._emg_t is not None and 0 < start - self._emg_t < 0.5 / self.emg_fs * n:
            start = self._emg_t + 1 / self.emg_fs  # continuidad entre paquetes
        times = start + np.arange(n) / self.emg_fs
        self._emg_t = float(times[-1])
        filtered = self._emg_pre.process(samples)
        for c in range(channels):
            raw, flt = self.get(f"emg{c + 1}"), self.get(f"emg{c + 1}_f")
            raw.t.extend(times.tolist())
            raw.y.extend(samples[:, c].astype(float).tolist())
            flt.t.extend(times.tolist())
            flt.y.extend(filtered[:, c].tolist())


# ================================================================= tiempo
def fmt_clock(t: float, decimals: int = 0) -> str:
    """Segundos -> 'mm:ss' (o 'h:mm:ss'); con decimales para ventanas cortas: '01:02.5'."""
    t = max(t, 0.0)
    h, rest = divmod(t, 3600)
    m, s = divmod(rest, 60)
    sec = f"{s:0{3 + decimals}.{decimals}f}" if decimals else f"{int(s):02d}"
    return f"{int(h)}:{int(m):02d}:{sec}" if h >= 1 else f"{int(m):02d}:{sec}"
