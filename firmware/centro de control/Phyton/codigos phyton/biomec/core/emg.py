"""Señales EMG e IA para la mano: filtrado, características y clasificador.

Es el mismo esquema que usan las prótesis comerciales con reconocimiento de
patrones (Coapt Gen2, Ottobock Myo Plus):

  muestras ──► filtros causales ──► ventanas ──► características ──► LDA ──► voto ──► movimiento
  (ADS1198)    paso alto 20 Hz      150 ms cada   de Hudgins por       lineal    mayoría de
               + notch 50 Hz        50 ms         canal: MAV, WL,                las últimas 3
                                                  ZC y SSC

Solo usa numpy y todo es causal (cada decisión usa únicamente muestras
pasadas), así que el mismo cálculo se puede llevar tal cual a la ESP32
(export_c_header): el LDA es una multiplicación de matrices.

Referencias:
  Hudgins, Parker y Scott (1993), IEEE TBME 40(1):82-94 — características MAV, WL, ZC, SSC.
  Englehart y Hudgins (2003), IEEE TBME 50(7):848-854 — ventanas solapadas, LDA y voto por mayoría.
  Farrell y Weir (2007), IEEE TNSRE 15(1):111-118 — retardo óptimo del controlador 100-125 ms.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

DEFAULT_FS = 500            # el firmware EMG del equipo usa ADS119X_DRATE_500SPS
REST = "Reposo"             # nombre de la clase de reposo (no mueve la mano)
FEATURES = ("MAV", "WL", "ZC", "SSC")
MODEL_FORMAT = "biomec-modelo-emg"


# ====================================================================== filtros
def _rbj(kind: str, f: float, fs: float, q: float) -> tuple[np.ndarray, np.ndarray]:
    """Coeficientes (b, a) de un biquad según el 'Audio EQ Cookbook' de R. Bristow-Johnson."""
    w0 = 2 * math.pi * f / fs
    cos, alpha = math.cos(w0), math.sin(w0) / (2 * q)
    a = [1 + alpha, -2 * cos, 1 - alpha]
    if kind == "highpass":
        b = [(1 + cos) / 2, -(1 + cos), (1 + cos) / 2]
    elif kind == "lowpass":
        b = [(1 - cos) / 2, 1 - cos, (1 - cos) / 2]
    elif kind == "notch":
        b = [1, -2 * cos, 1]
    elif kind == "bandpass":  # ganancia 0 dB en f
        b = [alpha, 0, -alpha]
    else:
        raise ValueError(kind)
    b, a = np.array(b, float), np.array(a, float)
    return b / a[0], a / a[0]


class Biquad:
    """Filtro IIR de 2º orden con estado (forma directa II transpuesta), para varios canales a la vez."""

    def __init__(self, b, a, channels: int):
        self.b, self.a = np.asarray(b, float), np.asarray(a, float)
        self.reset(channels)

    @classmethod
    def design(cls, kind: str, f: float, fs: float, q: float, channels: int) -> Biquad:
        return cls(*_rbj(kind, f, fs, q), channels)

    def reset(self, channels: int) -> None:
        self.z1 = np.zeros(channels)
        self.z2 = np.zeros(channels)

    def process(self, x: np.ndarray) -> np.ndarray:
        b0, b1, b2 = self.b
        a1, a2 = self.a[1], self.a[2]
        z1, z2 = self.z1, self.z2
        y = np.empty(x.shape, float)
        for n in range(x.shape[0]):
            xn = x[n]
            yn = b0 * xn + z1
            z1 = b1 * xn - a1 * yn + z2
            z2 = b2 * xn - a2 * yn
            y[n] = yn
        self.z1, self.z2 = z1, z2
        return y


@dataclass
class FilterConfig:
    highpass_hz: float = 20.0   # quita el offset de continua y los artefactos de movimiento
    notch_hz: float = 50.0      # red eléctrica en España (0 = sin notch)
    notch_q: float = 30.0


class Preprocessor:
    """Filtrado causal en tiempo real: paso alto Butterworth de 4º orden + notch.

    Es la versión causal del análisis del equipo en MATLAB (analizarEMG.m usa
    filtfilt, que necesita la señal entera y no sirve en tiempo real).
    """

    def __init__(self, fs: float, channels: int, cfg: FilterConfig | None = None):
        cfg = cfg or FilterConfig()
        self.channels = channels
        # Butterworth de 4º orden = dos biquads con Q 0.5412 y 1.3066
        self.stages = [Biquad.design("highpass", cfg.highpass_hz, fs, q, channels) for q in (0.5412, 1.3066)]
        if 0 < cfg.notch_hz < fs / 2:
            self.stages.append(Biquad.design("notch", cfg.notch_hz, fs, cfg.notch_q, channels))
        self._dc: np.ndarray | None = None

    def process(self, block: np.ndarray) -> np.ndarray:
        x = np.asarray(block, float)
        if self._dc is None:  # se resta el offset inicial para que el filtro no arranque con un escalón
            self._dc = x.mean(axis=0)
        x = x - self._dc
        for stage in self.stages:
            x = stage.process(x)
        return x


# ============================================================ características
def hudgins_features(win: np.ndarray, thr: np.ndarray) -> np.ndarray:
    """Ventana (muestras, canales) ya filtrada -> [MAV, WL, ZC, SSC] de cada canal.

    MAV y WL miden la amplitud (se usa su logaritmo, más gaussiano y mejor
    para el LDA); ZC y SSC, la frecuencia. thr es el umbral de ruido por canal.
    """
    n = win.shape[0]
    a = np.abs(win)
    d = np.diff(win, axis=0)
    ad = np.abs(d)
    mav = a.mean(axis=0)
    wl = ad.sum(axis=0) / n
    zc = np.count_nonzero((win[:-1] * win[1:] < 0) & (ad >= thr), axis=0) / n
    d1, d2 = d[:-1], -d[1:]           # (x_i − x_{i−1}) y (x_i − x_{i+1})
    ssc = np.count_nonzero((d1 * d2 > 0) & ((ad[:-1] >= thr) | (ad[1:] >= thr)), axis=0) / n
    return np.stack([np.log(mav + 1e-3), np.log(wl + 1e-3), zc, ssc], axis=1).ravel()


def window_features(sig: np.ndarray, win: int, step: int, thr: np.ndarray) -> np.ndarray:
    """Características de todas las ventanas de una señal filtrada: (n_ventanas, 4·canales)."""
    starts = range(0, sig.shape[0] - win + 1, step)
    if not len(starts):
        return np.empty((0, 4 * sig.shape[1]))
    return np.array([hudgins_features(sig[s:s + win], thr) for s in starts])


def feature_names(channels: int) -> list[str]:
    return [f"{f}{c + 1}" for c in range(channels) for f in FEATURES]


# ================================================================ clasificador
class LDA:
    """Análisis discriminante lineal con covarianza común y regularización (shrinkage).

    Cada clase k tiene una función lineal  g_k(x) = w_k·z + b_k  (z = x estandarizado);
    gana la mayor. Con priors iguales, softmax(g) son las probabilidades a posteriori.
    """

    def __init__(self, shrinkage: float = 0.05):
        self.shrinkage = shrinkage
        self.mu = self.sd = self.W = self.b = None

    def fit(self, X: np.ndarray, y: np.ndarray, n_classes: int) -> LDA:
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0)
        self.sd[self.sd < 1e-9] = 1.0
        Z = (X - self.mu) / self.sd
        d = Z.shape[1]
        means = np.zeros((n_classes, d))
        S = np.zeros((d, d))
        for k in range(n_classes):
            Zk = Z[y == k]
            if len(Zk) == 0:
                raise ValueError(f"La clase {k} no tiene ventanas para entrenar")
            means[k] = Zk.mean(axis=0)
            C = Zk - means[k]
            S += C.T @ C
        S /= max(len(Z) - n_classes, 1)
        S = (1 - self.shrinkage) * S + self.shrinkage * np.trace(S) / d * np.eye(d)
        self.W = means @ np.linalg.pinv(S)
        self.b = -0.5 * np.sum(self.W * means, axis=1)
        return self

    def decision(self, X: np.ndarray) -> np.ndarray:
        return ((X - self.mu) / self.sd) @ self.W.T + self.b

    def proba(self, X: np.ndarray) -> np.ndarray:
        s = self.decision(X)
        s = s - s.max(axis=-1, keepdims=True)
        e = np.exp(s)
        return e / e.sum(axis=-1, keepdims=True)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self.decision(X), axis=-1)

    def to_dict(self) -> dict:
        return {"shrinkage": self.shrinkage, "mu": self.mu.tolist(), "sd": self.sd.tolist(),
                "W": self.W.tolist(), "b": self.b.tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> LDA:
        lda = cls(d.get("shrinkage", 0.05))
        lda.mu, lda.sd = np.array(d["mu"]), np.array(d["sd"])
        lda.W, lda.b = np.array(d["W"]), np.array(d["b"])
        return lda


# ===================================================================== datos
@dataclass
class Recording:
    label: str
    rep: int
    samples: np.ndarray  # (muestras, canales), cuentas del ADC tal cual llegan


class EmgDataset:
    """Grabaciones etiquetadas. Se guardan en CSV (se abre en Excel, MATLAB o Python)."""

    def __init__(self, fs: int = DEFAULT_FS, channels: int = 0):
        self.fs = fs
        self.channels = channels
        self.recordings: list[Recording] = []

    def add(self, label: str, samples: np.ndarray) -> Recording:
        samples = np.asarray(samples)
        if self.channels and samples.shape[1] != self.channels:
            raise ValueError(f"Las grabaciones anteriores tienen {self.channels} canales y esta {samples.shape[1]}")
        self.channels = samples.shape[1]
        rec = Recording(label, 1 + sum(r.label == label for r in self.recordings), samples)
        self.recordings.append(rec)
        return rec

    def labels(self) -> list[str]:
        """Movimientos en el orden en que se grabaron (Reposo siempre el primero)."""
        seen = list(dict.fromkeys(r.label for r in self.recordings))
        return sorted(seen, key=lambda l: (l != REST, seen.index(l)))

    def summary(self) -> dict[str, tuple[int, float]]:
        out = {}
        for label in self.labels():
            recs = [r for r in self.recordings if r.label == label]
            out[label] = (len(recs), sum(len(r.samples) for r in recs) / self.fs)
        return out

    def remove(self, label: str) -> None:
        self.recordings = [r for r in self.recordings if r.label != label]
        if not self.recordings:
            self.channels = 0

    def clear(self) -> None:
        self.recordings.clear()
        self.channels = 0

    def __len__(self) -> int:
        return len(self.recordings)

    def save_csv(self, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            fh.write(f"# BIOMEC dataset EMG · fs={self.fs} Hz · {self.channels} canales · cuentas del ADC\n")
            w.writerow(["movimiento", "repeticion", "muestra"] + [f"canal{c + 1}" for c in range(self.channels)])
            for rec in self.recordings:
                for i, row in enumerate(rec.samples.tolist()):
                    w.writerow([rec.label, rec.rep, i] + row)

    @classmethod
    def load_csv(cls, path: str | Path) -> EmgDataset:
        fs, rows = DEFAULT_FS, []
        with open(path, newline="", encoding="utf-8") as fh:
            first = fh.readline()
            if first.startswith("#") and "fs=" in first:
                fs = int(first.split("fs=")[1].split()[0])
            elif not first.startswith("#"):
                fh.seek(0)
            reader = csv.reader(fh)
            header = next(reader)
            if header[:3] != ["movimiento", "repeticion", "muestra"]:
                raise ValueError("No es un dataset EMG de BIOMEC (faltan las columnas movimiento, repeticion, muestra)")
            rows = list(reader)
        ds = cls(fs)
        current, buf = None, []
        for row in rows + [None]:
            key = None if row is None else (row[0], row[1])
            if key != current and buf:
                ds.add(current[0], np.array(buf, dtype=np.int32))
                buf = []
            if row is not None:
                current = key
                buf.append([int(float(v)) for v in row[3:]])
        return ds


# =============================================================== entrenamiento
@dataclass
class TrainConfig:
    window_ms: int = 150        # 150-250 ms: compromiso entre precisión y retardo
    step_ms: int = 50           # una decisión cada 50 ms
    vote: int = 3               # voto por mayoría de las últimas N decisiones
    skip_start_ms: int = 600    # se descarta el inicio de cada grabación (tiempo de reacción)
    skip_end_ms: int = 200      # y el final (el usuario se anticipa a relajar)
    shrinkage: float = 0.05
    filters: FilterConfig = field(default_factory=FilterConfig)


@dataclass
class TrainReport:
    classes: list[str]
    confusion: np.ndarray            # filas = movimiento real, columnas = predicho (nº de ventanas)
    windows: list[int]               # ventanas de entrenamiento por clase
    method: str

    @property
    def accuracy(self) -> float:
        total = self.confusion.sum()
        return float(np.trace(self.confusion) / total) if total else 0.0

    def recall(self) -> list[float]:
        rows = self.confusion.sum(axis=1)
        return [float(self.confusion[i, i] / rows[i]) if rows[i] else 0.0 for i in range(len(self.classes))]

    def worst_pair(self) -> tuple[str, str, float] | None:
        """El par de movimientos que más se confunden: (real, predicho, fracción)."""
        best = None
        for i in range(len(self.classes)):
            row = self.confusion[i].sum()
            for j in range(len(self.classes)):
                if i != j and row:
                    frac = self.confusion[i, j] / row
                    if best is None or frac > best[2]:
                        best = (self.classes[i], self.classes[j], float(frac))
        return best


@dataclass
class EmgModel:
    classes: list[str]
    fs: int
    channels: int
    config: TrainConfig
    thr: np.ndarray                 # umbral de ruido por canal (para ZC y SSC)
    lda: LDA
    rest_mav: np.ndarray            # MAV en reposo y en contracción fuerte (para la intensidad)
    max_mav: np.ndarray
    report: TrainReport | None = None

    @property
    def window(self) -> int:
        return max(int(round(self.config.window_ms * self.fs / 1000)), 8)

    @property
    def step(self) -> int:
        return max(int(round(self.config.step_ms * self.fs / 1000)), 1)

    @property
    def delay_ms(self) -> float:
        """Retardo aproximado del controlador: media ventana + las decisiones que necesita el voto."""
        return self.config.window_ms / 2 + (math.ceil(self.config.vote / 2) - 1) * self.config.step_ms

    def to_dict(self) -> dict:
        d = {
            "formato": MODEL_FORMAT, "version": 1, "clases": self.classes, "fs": self.fs,
            "canales": self.channels, "config": asdict(self.config), "umbral": self.thr.tolist(),
            "lda": self.lda.to_dict(), "mav_reposo": self.rest_mav.tolist(), "mav_max": self.max_mav.tolist(),
        }
        if self.report is not None:
            d["informe"] = {"confusion": self.report.confusion.tolist(), "ventanas": self.report.windows,
                            "metodo": self.report.method}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> EmgModel:
        if d.get("formato") != MODEL_FORMAT:
            raise ValueError("No es un modelo EMG de BIOMEC")
        cfg = dict(d["config"])
        cfg["filters"] = FilterConfig(**cfg.get("filters", {}))
        model = cls(d["clases"], int(d["fs"]), int(d["canales"]), TrainConfig(**cfg), np.array(d["umbral"]),
                    LDA.from_dict(d["lda"]), np.array(d["mav_reposo"]), np.array(d["mav_max"]))
        if "informe" in d:
            rep = d["informe"]
            model.report = TrainReport(model.classes, np.array(rep["confusion"]), rep["ventanas"], rep["metodo"])
        return model

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> EmgModel:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _segments(dataset: EmgDataset, cfg: TrainConfig) -> tuple[list[tuple[str, int, np.ndarray]], np.ndarray]:
    """Filtra cada grabación y devuelve sus tramos útiles y el umbral de ruido por canal."""
    fs, ch = dataset.fs, dataset.channels
    warm = int(0.2 * fs)  # el filtro necesita unos ms para asentarse
    a, b = int(cfg.skip_start_ms * fs / 1000), int(cfg.skip_end_ms * fs / 1000)
    segs = []
    for rec in dataset.recordings:
        pre = Preprocessor(fs, ch, cfg.filters)
        sig = pre.process(rec.samples)
        start = max(a, warm)
        end = len(sig) - b
        if end - start > 0:
            segs.append((rec.label, rec.rep, sig[start:end]))
    rest = [s for label, _, s in segs if label == REST]
    if rest:
        thr = np.concatenate(rest).std(axis=0)
    else:
        thr = 0.1 * np.median([s.std(axis=0) for _, _, s in segs], axis=0) if segs else np.ones(ch)
    return segs, np.maximum(thr, 1e-6)


def train_model(dataset: EmgDataset, cfg: TrainConfig | None = None) -> EmgModel:
    """Entrena el clasificador y estima su precisión con datos que no ha visto."""
    cfg = cfg or TrainConfig()
    classes = dataset.labels()
    if len(classes) < 2:
        raise ValueError("Graba al menos dos movimientos (por ejemplo Reposo y Abrir mano).")
    fs = dataset.fs
    win = max(int(round(cfg.window_ms * fs / 1000)), 8)
    step = max(int(round(cfg.step_ms * fs / 1000)), 1)
    segs, thr = _segments(dataset, cfg)
    feats = [(classes.index(label), rep, window_features(sig, win, step, thr)) for label, rep, sig in segs]
    counts = [sum(len(F) for k, _, F in feats if k == i) for i in range(len(classes))]
    missing = [classes[i] for i, c in enumerate(counts) if c == 0]
    if missing:
        raise ValueError(f"Grabaciones demasiado cortas para: {', '.join(missing)}. "
                         f"Cada una debe durar más de {(cfg.skip_start_ms + cfg.skip_end_ms + cfg.window_ms) / 1000:.1f} s.")

    def stack(items):
        X = np.vstack([F for _, _, F in items if len(F)])
        y = np.concatenate([np.full(len(F), k) for k, _, F in items if len(F)])
        return X, y

    K = len(classes)
    confusion = np.zeros((K, K), dtype=int)
    reps = {k: {rep for kk, rep, F in feats if kk == k and len(F)} for k in range(K)}
    if all(len(r) >= 2 for r in reps.values()):
        method = "validación cruzada dejando fuera una repetición de cada movimiento"
        for r in sorted(set().union(*reps.values())):
            train = [f for f in feats if f[1] != r]
            test = [f for f in feats if f[1] == r and len(f[2])]
            if not test or any(not any(f[0] == k and len(f[2]) for f in train) for k in range(K)):
                continue
            Xtr, ytr = stack(train)
            lda = LDA(cfg.shrinkage).fit(Xtr, ytr, K)
            Xte, yte = stack(test)
            for t, p in zip(yte, lda.predict(Xte)):
                confusion[t, p] += 1
    else:
        method = "70 % de cada grabación para entrenar y el 30 % final para evaluar (graba 2+ repeticiones para una estimación más fiable)"
        gap = max(win // step, 1)  # ventanas solapadas: se deja un hueco para no evaluar con datos casi iguales
        train, test = [], []
        for k, rep, F in feats:
            cut = int(len(F) * 0.7)
            train.append((k, rep, F[:cut]))
            test.append((k, rep, F[cut + gap:]))
        if all(any(k == i and len(F) for k, _, F in train) for i in range(K)) and any(len(F) for *_, F in test):
            Xtr, ytr = stack(train)
            lda = LDA(cfg.shrinkage).fit(Xtr, ytr, K)
            Xte, yte = stack(test)
            for t, p in zip(yte, lda.predict(Xte)):
                confusion[t, p] += 1

    X, y = stack(feats)
    lda = LDA(cfg.shrinkage).fit(X, y, K)
    mav = np.exp(X[:, 0::4])  # MAV de cada canal en cada ventana
    rest_mav = np.percentile(mav[y == 0], 50, axis=0) if classes[0] == REST else np.percentile(mav, 5, axis=0)
    max_mav = np.maximum(np.percentile(mav, 95, axis=0), rest_mav + 1e-3)
    report = TrainReport(classes, confusion, counts, method)
    return EmgModel(classes, fs, dataset.channels, cfg, thr, lda, rest_mav, max_mav, report)


# ================================================================ tiempo real
@dataclass
class Decision:
    label: str
    index: int
    prob: float            # probabilidad del movimiento elegido en la última ventana
    probs: np.ndarray      # probabilidades de todos los movimientos (última ventana)
    intensity: float       # 0 = reposo … 1 = contracción fuerte
    raw_index: int         # predicción de la última ventana, antes del voto


class RealtimeDecoder:
    """Recibe bloques de muestras y emite una decisión cada 'step' muestras."""

    def __init__(self, model: EmgModel, vote: int | None = None):
        self.model = model
        self.pre = Preprocessor(model.fs, model.channels, model.config.filters)
        self.win, self.step = model.window, model.step
        self._buf = np.zeros((0, model.channels))
        self._new = 0
        self.history: deque[int] = deque(maxlen=max(vote or model.config.vote, 1))

    def push(self, samples: np.ndarray) -> list[Decision]:
        if samples.shape[1] != self.model.channels:
            raise ValueError(f"El modelo es de {self.model.channels} canales y llegan {samples.shape[1]}")
        y = self.pre.process(samples)
        self._buf = np.vstack([self._buf, y])
        self._new += len(y)
        out = []
        while self._new >= self.step:
            end = len(self._buf) - (self._new - self.step)
            self._new -= self.step
            if end >= self.win:
                out.append(self._classify(self._buf[end - self.win:end]))
        self._buf = self._buf[-(self.win + self._new):]
        return out

    def _classify(self, win: np.ndarray) -> Decision:
        m = self.model
        f = hudgins_features(win, m.thr)
        probs = m.lda.proba(f[None])[0]
        k = int(np.argmax(probs))
        self.history.append(k)
        counts = Counter(self.history)
        top = max(counts.values())
        winner = next(c for c in reversed(self.history) if counts[c] == top)  # empate: el más reciente
        mav = np.exp(f[0::4])
        intensity = float(np.clip(((mav - m.rest_mav) / (m.max_mav - m.rest_mav)).max(), 0, 1))
        return Decision(m.classes[winner], winner, float(probs[winner]), probs, intensity, k)
