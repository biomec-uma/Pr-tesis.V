"""Presentación animada de la mano en el gemelo digital: el GUION (sin Qt ni OpenGL).

Como las entradas de las webs de producto: la mano aparece dibujada en líneas, como un plano;
las piezas llegan y se montan una a una; un barrido con el borde brillante la vuelve sólida;
salen etiquetas con sus partes y termina moviendo los dedos con su mecanismo real.

Este módulo solo dice QUÉ pasa en cada instante t (segundos): dónde está cada pieza, hasta
dónde llegan las líneas y el sólido, la cámara, las etiquetas y la postura. El dibujo lo hace
pages/hand_intro.py. Así se puede probar sin tarjeta gráfica (tests/test_hand_intro.py).

Coordenadas: las de los STL del ensamblaje (mm). Los dedos crecen hacia +Y, así que el
barrido va de la muñeca (Y mínima) a las puntas de los dedos (Y máxima).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .hand_model import DEDOS, HandModel

DURATION = 13.6                  # s
FINAL_CAMERA = (55.0, 15.0, 1.25)  # azimut, elevación, distancia/tamaño = la vista "¾" del gemelo
GLOW_BAND = 14.0                 # mm de borde brillante en el barrido
THUMB_OPEN = 10.0

# Cámara: (t, azimut, elevación, distancia/tamaño). Entre puntos, con aceleración suave.
CAMERA_KEYS = [
    (0.0, 18.0, 30.0, 1.55),
    (3.0, 38.0, 20.0, 1.36),
    (5.2, 64.0, 12.0, 1.32),
    (9.6, 84.0, 8.0, 1.22),     # para los gestos, casi de frente a la palma
    (12.4, 66.0, 13.0, 1.24),
    (DURATION, *FINAL_CAMERA),
]

# Rótulo de cada fase (arriba a la izquierda): (desde t, texto)
PHASES = [
    (0.0, "01 · Diseño"),
    (1.0, "02 · Ensamblaje"),
    (3.1, "03 · Sólido"),
    (5.2, "04 · Componentes"),
    (9.7, "05 · Movimiento"),
]

# Tiempos de cada etapa
PALM_WIRE = (0.15, 1.5)          # se dibujan las líneas de la palma
COVER_FLIGHT = (0.7, 1.5)        # la tapa de cables llega por detrás
FINGER_START, FINGER_STEP = 1.0, 0.3   # cada dedo empieza 0,3 s después del anterior
PIECE_STEP, FLIGHT = 0.08, 0.8         # y dentro del dedo, cada pieza 0,08 s después
THUMB_FLIGHT = (2.15, 3.05)
SOLID = (3.1, 4.9)               # barrido sólido de la muñeca a las puntas
GLOW_OFF = (4.9, 5.4)
WIRE_FADE = (4.7, 5.8)
CALLOUT_TIMES = (5.4, 6.3, 7.2, 8.1)
CALLOUT_GROW = 0.35
CALLOUT_FADE = (9.5, 9.95)
TITLE = (11.6, 12.0, 13.0, 13.5)  # aparece, se queda, se va

# Gestos del final: (inicio, fin, flexión índice/medio/anular, pulgar)
GESTURES = [
    (9.8, 10.6, (1.0, 1.0, 1.0), 90.0),   # puño
    (10.8, 11.5, (0.0, 0.0, 0.0), THUMB_OPEN),
    (11.7, 12.3, (0.0, 1.0, 1.0), 90.0),  # señalar
    (12.5, 13.1, (0.0, 0.0, 0.0), THUMB_OPEN),
]

ORDER_IN_FINGER = ("Proximal", "Base-Medio", "Medio", "Proximal-Distal", "Distal")
FINGER_OFFSET = np.array([0.0, 85.0, 28.0])     # mm: los dedos llegan desde más allá de las puntas
COVER_OFFSET = np.array([0.0, -10.0, -60.0])
THUMB_OFFSET = np.array([-70.0, -25.0, 35.0])
THUMB_SWING = 70.0                               # grados de más con los que llega el pulgar


@dataclass(frozen=True)
class Callout:
    title: str
    subtitle: str
    part: str          # pieza a la que apunta: su nombre o el principio ("Palma" = "PalmaV2-4")
    side: int          # -1 etiqueta a la izquierda, +1 a la derecha
    dy: int            # desplazamiento vertical de la etiqueta (px)
    y_top: float = 0.0  # >0: usa solo los vértices de los últimos y_top mm (p. ej. la base de los dedos)


CALLOUTS = [
    Callout("Mecanismo de barras", "Un motor cierra las tres falanges", "indice/Base-Medio", 1, -70),
    Callout("3 motores DC", "Índice, medio y anular + meñique", "Palma", -1, -40, y_top=30.0),
    Callout("Servo del pulgar", "10° separado · 90° en pinza", "pulgar", 1, 30),
    Callout("Cables a la ESP32", "Recibe las órdenes por radio (ESP-NOW)", "Tapa cables", -1, 55),
]


# ------------------------------------------------------------------ ayudas
def clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def progress(t: float, start: float, end: float) -> float:
    return clamp01((t - start) / (end - start)) if end > start else float(t >= end)


def ease_out(x: float) -> float:
    return 1.0 - (1.0 - clamp01(x)) ** 3


def ease_in_out(x: float) -> float:
    x = clamp01(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def translation(v) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = v
    return m


def feature_edges(triangles: np.ndarray, angle_deg: float = 32.0, decimals: int = 3) -> np.ndarray:
    """Aristas "de plano" de una malla: bordes abiertos y pliegues de más de angle_deg entre caras.

    Las diagonales de las caras planas no salen (en un cubo: 12 aristas, no 18). Los STL no
    comparten vértices, así que primero se sueldan los iguales (redondeando a 10^-decimals mm).
    Devuelve los segmentos (M, 2, 3), ordenados de abajo arriba en Y (para dibujarlos crecer).
    """
    tri = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    if len(tri) == 0:
        return np.zeros((0, 2, 3), np.float32)
    keys = np.round(tri.reshape(-1, 3), decimals)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    ids = inv.reshape(-1, 3)
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normal, axis=1)
    good = length > 1e-12
    normal = normal / np.where(good, length, 1.0)[:, None]

    edges = np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]])
    face = np.tile(np.arange(len(tri)), 3)
    edges.sort(axis=1)
    valid = np.tile(good, 3) & (edges[:, 0] != edges[:, 1])
    edges, face = edges[valid], face[valid]
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges, face = edges[order], face[order]

    first = np.r_[True, np.any(edges[1:] != edges[:-1], axis=1)]
    starts = np.flatnonzero(first)
    counts = np.diff(np.r_[starts, len(edges)])
    keep = counts != 2                                  # bordes y aristas raras: siempre
    pair = np.flatnonzero(counts == 2)
    cos = np.einsum("ij,ij->i", normal[face[starts[pair]]], normal[face[starts[pair] + 1]])
    keep[pair] = cos < np.cos(np.radians(angle_deg))
    seg = uniq[edges[starts[keep]]]
    seg = seg[np.argsort(seg[:, :, 1].min(axis=1), kind="stable")]
    return seg.astype(np.float32)


# ------------------------------------------------------------------ fotograma
@dataclass
class IntroFrame:
    t: float
    offsets: dict[str, np.ndarray] = field(default_factory=dict)   # matriz extra de cada pieza (vuelo)
    visible: dict[str, bool] = field(default_factory=dict)         # la pieza ya ha empezado a llegar
    wire: dict[str, float] = field(default_factory=dict)           # fracción de sus líneas dibujadas
    wire_alpha: float = 1.0
    cut: float = 0.0          # mm: por debajo de esta Y la mano ya es sólida
    glow: float = 0.0         # intensidad del borde brillante
    camera: tuple = FINAL_CAMERA
    flex: dict[str, float] = field(default_factory=dict)
    thumb: float = THUMB_OPEN
    moving: dict[str, float] = field(default_factory=dict)         # 0..1: dedos que se mueven (en azul)
    callouts: list[tuple[int, float, float]] = field(default_factory=list)  # (índice, crecimiento, opacidad)
    title_alpha: float = 0.0
    phase: str = ""
    done: bool = False


class IntroScript:
    """Guion de la presentación para un modelo concreto (sus piezas y su altura)."""

    def __init__(self, model: HandModel):
        self.model = model
        ys = np.concatenate([p.triangles[:, :, 1].ravel() for p in model.parts.values()])
        self.y_min, self.y_max = float(ys.min()), float(ys.max())
        self.flight: dict[str, tuple[float, float, np.ndarray]] = {}  # pieza -> (inicio, fin, desplazamiento)
        for i, dedo in enumerate(DEDOS):
            for k, role in enumerate(ORDER_IN_FINGER):
                name = f"{dedo}/{role}"
                if name in model.parts:
                    start = FINGER_START + i * FINGER_STEP + k * PIECE_STEP
                    self.flight[name] = (start, start + FLIGHT, FINGER_OFFSET)
        for name in model.parts:
            if name.lower().startswith("tapa"):
                self.flight[name] = (*COVER_FLIGHT, COVER_OFFSET)
        if "pulgar" in model.parts:
            self.flight["pulgar"] = (*THUMB_FLIGHT, THUMB_OFFSET)

    # ---- partes del guion
    @staticmethod
    def camera(t: float) -> tuple[float, float, float]:
        for (t0, *a), (t1, *b) in zip(CAMERA_KEYS, CAMERA_KEYS[1:]):
            if t <= t1:
                k = ease_in_out(progress(t, t0, t1))
                return tuple(float(x + (y - x) * k) for x, y in zip(a, b))
        return FINAL_CAMERA

    @staticmethod
    def pose(t: float) -> tuple[dict[str, float], float, dict[str, float]]:
        """Postura de los dedos, del pulgar y cuánto se mueve cada dedo (para pintarlo en azul)."""
        flex, thumb = [0.0, 0.0, 0.0], THUMB_OPEN
        moving = [0.0, 0.0, 0.0]
        for start, end, target, target_thumb in GESTURES:
            if t < start:
                break
            k = ease_in_out(progress(t, start, end))
            active = start <= t < end
            for i in range(3):
                if active and abs(target[i] - flex[i]) > 1e-6:
                    moving[i] = 1.0
                flex[i] = flex[i] + (target[i] - flex[i]) * k
            thumb = thumb + (target_thumb - thumb) * k
        return dict(zip(DEDOS, flex)), thumb, dict(zip(DEDOS, moving))

    def frame(self, t: float) -> IntroFrame:
        t = min(max(t, 0.0), DURATION)
        f = IntroFrame(t=t)
        f.done = t >= DURATION
        for name in self.model.parts:
            if name in self.flight:
                start, end, offset = self.flight[name]
                k = progress(t, start, end)
                f.visible[name] = t >= start
                f.wire[name] = k
                rest = 1.0 - ease_out(k)
                m = translation(offset * rest)
                if name == "pulgar" and rest > 0:      # además llega girando sobre su eje
                    m = m @ self.model.pose({}, THUMB_OPEN + THUMB_SWING * rest)["pulgar"]
                    m = m @ np.linalg.inv(self.model.pose({}, THUMB_OPEN)["pulgar"])
                f.offsets[name] = m
            else:                                       # la palma: ya está, se dibuja
                f.visible[name] = True
                f.wire[name] = progress(t, *PALM_WIRE)
                f.offsets[name] = np.eye(4)
        f.wire_alpha = 1.0 - progress(t, *WIRE_FADE)
        k = ease_in_out(progress(t, *SOLID))
        f.cut = (self.y_min - 2.0) + (self.y_max + GLOW_BAND + 2.0 - (self.y_min - 2.0)) * k
        f.glow = 0.0 if t < SOLID[0] else 1.0 - progress(t, *GLOW_OFF)
        f.camera = self.camera(t)
        f.flex, f.thumb, f.moving = self.pose(t)
        for i, start in enumerate(CALLOUT_TIMES):
            if t >= start:
                alpha = 1.0 - progress(t, *CALLOUT_FADE)
                if alpha > 0:
                    f.callouts.append((i, ease_out(progress(t, start, start + CALLOUT_GROW)), alpha))
        a, b, c, d = TITLE
        f.title_alpha = progress(t, a, b) * (1.0 - progress(t, c, d))
        f.phase = next(text for start, text in reversed(PHASES) if t >= start)
        return f

    def part_name(self, prefix: str) -> str:
        """Nombre de la pieza: exacto o la primera que empieza así ("Palma" -> "PalmaV2-4")."""
        if prefix in self.model.parts:
            return prefix
        for name in self.model.parts:
            if name.lower().startswith(prefix.lower()):
                return name
        raise KeyError(f"No hay ninguna pieza que empiece por {prefix!r}")

    def anchor(self, callout: Callout) -> tuple[str, np.ndarray]:
        """Pieza y punto 3D (coordenadas del STL) al que apunta una etiqueta."""
        name = self.part_name(callout.part)
        v = self.model.parts[name].triangles.reshape(-1, 3)
        if callout.y_top > 0:
            v = v[v[:, 1] >= v[:, 1].max() - callout.y_top]
        return name, v.mean(axis=0)


__all__ = ["CALLOUTS", "DURATION", "FINAL_CAMERA", "Callout", "IntroFrame", "IntroScript", "feature_edges"]
