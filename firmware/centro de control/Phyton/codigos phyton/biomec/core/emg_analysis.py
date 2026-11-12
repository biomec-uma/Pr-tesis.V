"""Analizador EMG: versión en Python (numpy) del analizador en MATLAB del equipo.

Origen: firmware/EMG/tools/analizadorEMG/tercerScript+app del repositorio del equipo
(Analizador EMG v1.0, de Carlos López Jiménez). Mismos pasos, parámetros, avisos y archivos:

  cuentas ──► µV centrados ──► % de red (50 Hz) ──► notch (filtfilt) ──► paso banda FIR ──► envolvente RMS
                                                                         (Kaiser, sin desfase)      │
                                    umbral de contracción = media + k·std de la envolvente en reposo ◄┘

Equivalencias con MATLAB (comprobadas con los análisis guardados en el repositorio, ver tests):
  designNotchPeakIIR    -> notch_design      mismos coeficientes
  filtfilt              -> filtfilt          relleno impar de 3·(n-1) muestras y estado inicial estable
  bandpass(...,'fir')   -> bandpass_design   ventana de Kaiser, 60 dB, pendiente 0.85: con 20-130 Hz a
                           + fir_zero_phase  500 SPS salen los mismos 595 coeficientes
  bandpower             -> bandpower         periodograma con ventana de Hamming
  envelope(x, W, 'rms') -> rms_envelope
  pspectrum             -> power_spectrum / spectrogram  (solo para las gráficas: aspecto parecido, no idéntico)

Solo usa numpy (sin scipy), igual que el resto del núcleo EMG de la app.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import numpy as np

ADS_BANDWIDTH = 0.262      # el filtro sinc del ADS1198 corta (-3 dB) en 0.262·SPS (~131 Hz a 500 SPS)
STEEPNESS = 0.85           # pendiente por defecto de bandpass() en MATLAB
STOP_DB = 60.0             # atenuación por defecto de bandpass() en MATLAB


class AnalysisError(ValueError):
    """Parámetros o datos con los que el análisis no se puede hacer (mensaje para el usuario)."""


@dataclass
class AnalysisParams:
    """Los parámetros de la app de MATLAB (struct p), con sus valores por defecto."""
    sps: float = 500.0          # muestras por segundo del ADC
    vref: float = 2.4           # tensión de referencia del ADC [V]
    gain: float = 4.0           # ganancia del PGA
    bits: int = 16              # resolución del ADC
    notch_on: bool = True
    f0: float = 50.0            # frecuencia de la red [Hz]
    q: float = 35.0             # factor de calidad del notch
    band_on: bool = True
    f_low: float = 20.0         # corte inferior del paso banda [Hz]
    f_high: float = 130.0       # corte superior [Hz]
    t_rms: float = 0.2          # ventana de la envolvente RMS [s]
    rest_start: float = 0.5     # tramo de reposo [s]
    rest_end: float = 2.5
    k: float = 3.0              # umbral = media + k·std del reposo
    t_window: float = 0.25      # ventana del espectrograma [s] (solo la gráfica)

    @property
    def microvolts_per_count(self) -> float:
        return 2 * (self.vref / self.gain) / 2 ** self.bits * 1e6

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AnalysisParams:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})


# ===================================================================== validación
def validate(p: AnalysisParams, n_samples: int) -> list[str]:
    """Como validarParametros.m: lanza AnalysisError si el análisis no se puede hacer y devuelve los avisos
    (el análisis se puede hacer, pero conviene revisarlo)."""
    warnings: list[str] = []
    if p.sps <= 0:
        raise AnalysisError("Samples/s tiene que ser mayor que 0.")
    if p.gain <= 0 or p.vref <= 0:
        raise AnalysisError("La ganancia y Vref tienen que ser mayores que 0.")
    if p.bits <= 0 or int(p.bits) != p.bits:
        raise AnalysisError("Los bits del ADC tienen que ser un número entero mayor que 0.")
    nyq = p.sps / 2
    duration = n_samples / p.sps
    if p.notch_on:
        if p.f0 <= 0 or p.f0 >= nyq:
            raise AnalysisError(f"La frecuencia del notch ({p.f0:g} Hz) tiene que estar entre 0 y {nyq:g} Hz (sps/2).")
        if p.q <= 0:
            raise AnalysisError("El factor de calidad Q tiene que ser mayor que 0.")
    if p.band_on:
        if p.f_low <= 0 or p.f_low >= p.f_high:
            raise AnalysisError(f"El corte inferior ({p.f_low:g} Hz) tiene que ser mayor que 0 y menor que el "
                                f"superior ({p.f_high:g} Hz).")
        if p.f_high >= nyq:
            raise AnalysisError(f"El corte superior ({p.f_high:g} Hz) tiene que ser menor que {nyq:g} Hz (sps/2).")
        real = ADS_BANDWIDTH * p.sps
        if p.f_high > real:
            warnings.append(
                f"El corte superior ({p.f_high:g} Hz) supera el ancho de banda real del ADS a {p.sps:g} SPS "
                f"(~{real:.0f} Hz).\n\nEl ADS lleva un filtro interno que atenúa todo lo que pase de ~{real:.0f} Hz, "
                f"así que entre {real:.0f} y {p.f_high:g} Hz la señal ya llega debilitada y el paso banda no la "
                f"recupera.\n\nPara que el corte sea real, baja el corte superior a {math.floor(real):.0f} Hz o "
                f"menos, o sube los SPS del ADS.")
    if p.t_rms * p.sps < 1 or p.t_rms >= duration:
        raise AnalysisError(f"El suavizado ({p.t_rms:g} s) tiene que durar al menos 1 muestra y menos que la "
                            f"señal ({duration:.1f} s).")
    if p.rest_start < 0 or p.rest_start >= p.rest_end or p.rest_end > duration:
        raise AnalysisError(f'La franja de reposo ({p.rest_start:g} a {p.rest_end:g} s) tiene que estar dentro de la '
                            f'señal (0 a {duration:.1f} s) y "desde" ser menor que "hasta".')
    if p.k < 0:
        raise AnalysisError("La sensibilidad K no puede ser negativa.")
    if p.t_window <= 0 or p.t_window >= duration:
        raise AnalysisError(f"La ventana del espectrograma ({p.t_window:g} s) tiene que ser mayor que 0 y menor que "
                            f"la señal ({duration:.1f} s).")
    return warnings


# ======================================================================== filtros
def notch_design(f0: float, q: float, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Notch IIR de 2º orden (designNotchPeakIIR / iirnotch de MATLAB): ancho de banda f0/Q a -3 dB."""
    w0 = 2 * math.pi * f0 / fs
    gain = 1 / (1 + math.tan(w0 / q / 2))
    b = gain * np.array([1.0, -2 * math.cos(w0), 1.0])
    a = np.array([1.0, -2 * gain * math.cos(w0), 2 * gain - 1])
    return b, a


def _biquad(b, a, x: np.ndarray, z1: float, z2: float) -> np.ndarray:
    """Filtro de 2º orden (forma directa II transpuesta) con estado inicial; bucle escalar (rápido en Python)."""
    b0, b1, b2 = (float(v) for v in b)
    a1, a2 = float(a[1]), float(a[2])
    out = np.empty(len(x))
    for i, xn in enumerate(x.tolist()):
        yn = b0 * xn + z1
        z1 = b1 * xn - a1 * yn + z2
        z2 = b2 * xn - a2 * yn
        out[i] = yn
    return out


def filtfilt(b, a, x: np.ndarray) -> np.ndarray:
    """Filtrado ida y vuelta sin desfase, como filtfilt de MATLAB (para filtros de 2º orden)."""
    b, a = np.asarray(b, float) / a[0], np.asarray(a, float) / a[0]
    if len(b) != 3 or len(a) != 3:
        raise ValueError("filtfilt: solo filtros de 2º orden")
    x = np.asarray(x, float)
    nfact = 3 * (3 - 1)
    if len(x) <= nfact:
        raise AnalysisError("La señal es demasiado corta para el filtro notch.")
    # estado inicial estable ante un escalón (como MATLAB y scipy.signal.lfilter_zi)
    m = np.array([[1 + a[1], -1.0], [a[2], 1.0]])
    zi = np.linalg.solve(m, np.array([b[1] - b[0] * a[1], b[2] - b[0] * a[2]]))
    y = np.concatenate([2 * x[0] - x[nfact:0:-1], x, 2 * x[-1] - x[-2:-nfact - 2:-1]])
    y = _biquad(b, a, y, *(zi * y[0]))[::-1]
    y = _biquad(b, a, y, *(zi * y[0]))[::-1]
    return y[nfact:-nfact]


def kaiser_beta(atten_db: float) -> float:
    if atten_db > 50:
        return 0.1102 * (atten_db - 8.7)
    if atten_db > 21:
        return 0.5842 * (atten_db - 21) ** 0.4 + 0.07886 * (atten_db - 21)
    return 0.0


def _fir_bandpass(order: int, fc1: float, fc2: float, fs: float, beta: float) -> np.ndarray:
    """fir1(order, [fc1 fc2]/(fs/2), kaiser(order+1, beta)): ganancia 1 en el centro de la banda."""
    n = np.arange(order + 1) - order / 2
    ideal = 2 * fc2 / fs * np.sinc(2 * fc2 / fs * n) - 2 * fc1 / fs * np.sinc(2 * fc1 / fs * n)
    h = ideal * np.kaiser(order + 1, beta)
    centre = (fc1 + fc2) / 2
    return h / abs(np.sum(h * np.exp(-2j * np.pi * centre / fs * np.arange(order + 1))))


def _stopband_db(h: np.ndarray, fs: float, stop1: float, stop2: float) -> float:
    nfft = max(8192, 1 << int(math.ceil(math.log2(len(h)))))
    mag = np.abs(np.fft.rfft(h, nfft))
    f = np.fft.rfftfreq(nfft, 1 / fs)
    stop = (f <= stop1 + 1e-9) | (f >= stop2 - 1e-9)
    return float(-20 * np.log10(max(mag[stop].max(), 1e-300)))


def bandpass_design(f_low: float, f_high: float, fs: float, steepness: float = STEEPNESS,
                    stop_db: float = STOP_DB) -> np.ndarray:
    """Coeficientes del FIR de bandpass(x, [f_low f_high], fs, 'ImpulseResponse', 'fir') de MATLAB.

    Transición = (0.99 − 0.98·pendiente)·min(f_low, fs/2 − f_high) a cada lado (filtro simétrico), cortes en el
    centro de cada transición, ventana de Kaiser para 60 dB y el orden par más bajo (desde la estimación de
    Kaiser) cuya banda eliminada llega a 60 dB."""
    width = (0.99 - 0.98 * steepness) * min(f_low, fs / 2 - f_high)
    if width <= 0:
        raise AnalysisError("Los cortes del paso banda tienen que estar entre 0 y sps/2.")
    beta = kaiser_beta(stop_db)
    order = math.ceil((stop_db - 7.95) / (2.285 * 2 * math.pi * width / fs))
    order += order % 2
    fc1, fc2 = f_low - width / 2, f_high + width / 2
    for _ in range(64):
        h = _fir_bandpass(order, fc1, fc2, fs, beta)
        if round(_stopband_db(h, fs, f_low - width, f_high + width), 1) >= stop_db:
            break
        order += 2
    return h


def fir_zero_phase(h: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Como bandpass() de MATLAB con FIR: añade N/2 ceros, filtra y quita las N/2 primeras muestras."""
    x = np.asarray(x, float)
    d = (len(h) - 1) // 2
    n = len(x) + len(h) - 1
    if len(x) * len(h) > 4_000_000:          # señales largas: convolución por FFT (mismo resultado)
        nfft = 1 << int(math.ceil(math.log2(n)))
        full = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[:n]
    else:
        full = np.convolve(x, h)
    return full[d:d + len(x)]


# ===================================================================== medidas
def bandpower(x: np.ndarray, fs: float, f1: float, f2: float) -> float:
    """Potencia entre f1 y f2 (bandpower de MATLAB: periodograma con ventana de Hamming)."""
    x = np.asarray(x, float)
    n = len(x)
    w = np.hamming(n)
    spec = np.abs(np.fft.rfft(x * w)) ** 2 / (fs * np.sum(w ** 2))
    if n % 2 == 0:
        spec[1:-1] *= 2
    else:
        spec[1:] *= 2
    f = np.arange(len(spec)) * fs / n
    lo = np.flatnonzero(f <= f1)
    hi = np.flatnonzero(f >= f2)
    i1 = lo[-1] if len(lo) else 0
    i2 = hi[0] if len(hi) else len(f) - 1
    return float(np.sum(spec[i1:i2 + 1]) * fs / n)


def rms_envelope(x: np.ndarray, window: int) -> np.ndarray:
    """Envolvente RMS (envelope(x, W, 'rms') de MATLAB): media de la señal + RMS de la señal sin su media en
    una ventana de W muestras ((W-1)//2 antes y W//2 después); en los extremos la ventana se acorta."""
    x = np.asarray(x, float)
    mean = x.mean()
    sq = (x - mean) ** 2
    n = len(x)
    before, after = (window - 1) // 2, window // 2
    c = np.concatenate([[0.0], np.cumsum(sq)])
    i = np.arange(n)
    lo = np.clip(i - before, 0, n)
    hi = np.clip(i + after + 1, 0, n)
    return mean + np.sqrt(np.maximum((c[hi] - c[lo]) / (hi - lo), 0.0))


def power_spectrum(x: np.ndarray, fs: float, segment: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Espectro de potencia en dB para las gráficas, con un aspecto parecido al de pspectrum: media de tramos
    de ~4 s (a 500 Hz) solapados a la mitad con ventana de Hann, en unidades de potencia (una senoidal de
    amplitud A da A²/2). Solo se usa para dibujar: los números del análisis salen de bandpower()."""
    x = np.asarray(x, float)
    n = len(x)
    seg = min(n, segment)
    hop = max(1, seg // 2)
    w = np.hanning(seg) if seg > 2 else np.ones(seg)
    starts = range(0, n - seg + 1, hop)
    acc = np.zeros(seg // 2 + 1)
    count = 0
    for s0 in starts:
        part = x[s0:s0 + seg]
        acc += np.abs(np.fft.rfft((part - part.mean()) * w)) ** 2
        count += 1
    p = acc / max(count, 1) / np.sum(w) ** 2
    p[1:] *= 2
    f = np.fft.rfftfreq(seg, 1 / fs)
    return f, 10 * np.log10(p + 1e-30)


def spectrogram(x: np.ndarray, fs: float, t_window: float, overlap: float = 0.75):
    """Espectrograma en dB (como pspectrum(..., 'spectrogram', 'TimeResolution', t, 'OverlapPercent', 75)).

    Devuelve (tiempos del centro de cada ventana, frecuencias, matriz [frecuencia, tiempo])."""
    x = np.asarray(x, float)
    seg = max(4, int(round(t_window * fs)))
    hop = max(1, int(round(seg * (1 - overlap))))
    if len(x) < seg:
        seg = len(x)
    starts = np.arange(0, len(x) - seg + 1, hop)
    w = np.kaiser(seg, 20.0)
    nfft = max(256, 1 << int(math.ceil(math.log2(seg))))
    frames = np.stack([x[s:s + seg] * w for s in starts])
    p = np.abs(np.fft.rfft(frames, nfft, axis=1)) ** 2 / np.sum(w) ** 2
    p[:, 1:] *= 2
    f = np.fft.rfftfreq(nfft, 1 / fs)
    t = (starts + seg / 2) / fs
    return t, f, 10 * np.log10(p.T + 1e-30)


# ===================================================================== análisis
@dataclass
class ChannelResult:
    name: str                 # nombre de la columna del CSV
    v: np.ndarray             # µV centrados
    v_notch: np.ndarray
    v_band: np.ndarray
    rms: np.ndarray
    p50: float                # % de la potencia en f0 ± 1 Hz (bruta)
    p50_notch: float          # ídem tras el notch
    rest_rms: float           # media de la envolvente en reposo [µV]
    threshold: float          # umbral de contracción [µV]


@dataclass
class AnalysisResult:
    params: AnalysisParams
    t: np.ndarray
    channels: list[ChannelResult]
    b_notch: np.ndarray
    a_notch: np.ndarray
    h_band: np.ndarray | None
    window: int               # muestras de la ventana RMS
    rest: np.ndarray          # máscara del tramo de reposo
    warnings: list[str] = field(default_factory=list)

    @property
    def n_samples(self) -> int:
        return len(self.t)

    @property
    def duration(self) -> float:
        return self.n_samples / self.params.sps


def _p50(v: np.ndarray, p: AnalysisParams) -> float:
    total = bandpower(v, p.sps, 1, p.sps / 2 - 1)
    return 100 * bandpower(v, p.sps, p.f0 - 1, p.f0 + 1) / total if total > 0 else 0.0


def analyze(data: np.ndarray, p: AnalysisParams, names: list[str] | None = None) -> AnalysisResult:
    """data: (muestras, canales) en cuentas del ADC. Hace lo mismo que analizarEMG.m, canal a canal."""
    data = np.asarray(data, float)
    if data.ndim == 1:
        data = data[:, None]
    n, k = data.shape
    if n < 2:
        raise AnalysisError("El archivo no tiene muestras.")
    names = names or [f"canal {i}" for i in range(k)]
    warnings = validate(p, n)
    t = np.arange(n) / p.sps
    if p.notch_on:
        b_notch, a_notch = notch_design(p.f0, p.q, p.sps)
    else:
        b_notch, a_notch = np.array([1.0]), np.array([1.0])
    h_band = None
    if p.band_on:
        h_band = bandpass_design(p.f_low, p.f_high, p.sps)
        if n < 2 * (len(h_band) - 1):
            raise AnalysisError(
                f"No se puede aplicar el paso banda {p.f_low:g}-{p.f_high:g} Hz a esta señal: con un corte tan cerca "
                f"de 0 Hz o de {p.sps / 2:g} Hz (sps/2) el filtro necesitaría más muestras de las que tiene la señal "
                f"({len(h_band)} coeficientes para {n} muestras). Aleja los cortes de los extremos.")
    window = round(p.t_rms * p.sps)
    rest = (t >= p.rest_start) & (t < p.rest_end)
    if not rest.any():
        raise AnalysisError("La franja de reposo no contiene ninguna muestra.")
    channels = []
    for i in range(k):
        v = (data[:, i] - data[:, i].mean()) * p.microvolts_per_count
        v_notch = filtfilt(b_notch, a_notch, v) if p.notch_on else v
        v_band = fir_zero_phase(h_band, v_notch) if h_band is not None else v_notch
        rms = rms_envelope(v_band, window)
        rest_rms = float(rms[rest].mean())
        std = float(rms[rest].std(ddof=1)) if rest.sum() > 1 else 0.0
        channels.append(ChannelResult(names[i], v, v_notch, v_band, rms, _p50(v, p), _p50(v_notch, p),
                                      rest_rms, rest_rms + p.k * std))
    return AnalysisResult(p, t, channels, b_notch, a_notch, h_band, window, rest, warnings)


# ===================================================================== CSV
TIME_NAMES = re.compile(r"^(t|t_s|tiempo|time|program time.*|timestamp|ms|t_ms)$", re.I)
META_NAMES = re.compile(r"^(seq|idx|n|index|muestra|paquete)$", re.I)


@dataclass
class EmgTable:
    path: Path
    header: list[str]
    data: np.ndarray          # (filas, columnas) numéricas (NaN si una celda no es número)
    time_col: int | None      # columna de tiempo detectada
    channel_cols: list[int]   # columnas que parecen canales EMG

    def column(self, i: int) -> np.ndarray:
        return self.data[:, i]

    @property
    def rows(self) -> int:
        return len(self.data)

    def estimated_rate(self) -> float | None:
        """Frecuencia de muestreo que sugiere la columna de tiempo (None si no hay o no es fiable)."""
        if self.time_col is None or self.rows < 10:
            return None
        t = self.data[:, self.time_col]
        t = t[np.isfinite(t)]
        if len(t) < 10 or t[-1] <= t[0]:
            return None
        rate = (len(t) - 1) / (t[-1] - t[0])
        return float(rate) if np.isfinite(rate) else None


def load_csv(path: str | Path) -> EmgTable:
    """Lee un CSV de EMG del equipo: el del visor («t_s, seq, idx, ch1…» o «tiempo, data0, data1»), el del
    logger serie («Program Time [s], data 0, data 1») u otro con cabecera. Detecta el tiempo y los canales."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if not rows:
        raise AnalysisError("El archivo está vacío.")

    def number(s: str) -> float:
        s = s.strip()
        if delimiter != "," and "," in s and "." not in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return math.nan

    first_numeric = all(math.isfinite(number(c)) for c in rows[0] if c.strip())
    header = [f"col{i + 1}" for i in range(len(rows[0]))] if first_numeric else [c.strip() for c in rows[0]]
    body = rows if first_numeric else rows[1:]
    width = len(header)
    data = np.full((len(body), width), math.nan)
    for r, row in enumerate(body):
        for c in range(min(width, len(row))):
            data[r, c] = number(row[c])
    keep = np.isfinite(data).any(axis=1)
    data = data[keep]
    if not len(data):
        raise AnalysisError("El archivo no tiene filas con números.")
    time_col = next((i for i, h in enumerate(header) if TIME_NAMES.match(h.strip())
                     or "tiempo" in h.lower() or "time" in h.lower()), None)
    numeric = [i for i in range(width) if np.isfinite(data[:, i]).mean() > 0.95]
    channels = [i for i in numeric if i != time_col and not META_NAMES.match(header[i].strip())]
    if time_col is None and first_numeric and len(numeric) >= 3:      # sin cabecera: 1ª columna = tiempo (MATLAB)
        time_col, channels = numeric[0], numeric[1:]
    return EmgTable(path, header, data, time_col, channels)


# ===================================================================== guardar
def _fmt(v) -> str:
    """Números como writetable de MATLAB (15 cifras significativas; lógicos como 1/0)."""
    if isinstance(v, (bool, np.bool_)):
        return "1" if v else "0"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return str(int(f)) if f.is_integer() and abs(f) < 1e15 else f"{f:.15g}"
    return str(v)


def results_row(result: AnalysisResult, sample: str) -> tuple[list[str], list]:
    """Cabecera y fila de resultados.csv (las mismas columnas que guardarAnalisis.m, para cualquier nº de canales)."""
    p = result.params
    chs = result.channels
    head = ["muestra", "nMuestras", "duracion_s"]
    row: list = [sample, result.n_samples, result.n_samples / p.sps]
    for key, attr in (("p50_ch{}", "p50"), ("p50notch_ch{}", "p50_notch"), ("rmsReposo_ch{}_uV", "rest_rms"),
                      ("umbral_ch{}_uV", "threshold")):
        for i, ch in enumerate(chs):
            head.append(key.format(i))
            row.append(getattr(ch, attr))
    head += ["sps", "notchOn", "f0_Hz", "Q", "bandaOn", "fBaja_Hz", "fAlta_Hz", "tRMS_s", "tReposoIni_s",
             "tReposoFin_s", "kUmbral"]
    row += [p.sps, bool(p.notch_on), p.f0, p.q, bool(p.band_on), p.f_low, p.f_high, p.t_rms, p.rest_start,
            p.rest_end, p.k]
    return head, row


def _num_list(values) -> str:
    """Lista de coeficientes como num2str(x, '%.10g') de MATLAB: todos con el mismo ancho, separados por comas."""
    texts = [f"{float(v):.10g}" for v in values]
    width = max(len(t) for t in texts)
    return ", ".join(t.rjust(width) for t in texts)


def coefficients_text(result: AnalysisResult) -> str:
    """Contenido de coeficientes_filtros.txt (mismo formato que guardarFiltros.m)."""
    p = result.params
    lines = [f"fs = {p.sps:g} Hz", ""]
    if p.notch_on:
        lines += [f"Notch {p.f0:g} Hz, Q = {p.q:g}", f"b = [{_num_list(result.b_notch)}]",
                  f"a = [{_num_list(result.a_notch)}]", ""]
    else:
        lines += ["Notch desactivado", ""]
    if result.h_band is None:
        lines.append("Paso banda desactivado")
    else:
        lines += [f"Paso banda {p.f_low:g}-{p.f_high:g} Hz ({len(result.h_band)} coeficientes)",
                  _num_list(result.h_band)]
    return "\n".join(lines) + "\n"


def sample_folder(dest_root: str | Path, sample_file: str) -> Path:
    return Path(dest_root) / Path(sample_file).stem


def save_analysis(result: AnalysisResult, sample_file: str, dest_root: str | Path) -> Path:
    """Guarda como guardarAnalisis.m (salvo las figuras, que guarda la ventana) en <dest_root>/<muestra>/:
    resultados.csv (se sobrescribe), resumen_muestras.csv (una fila más cada vez), senales.csv (t, señal
    filtrada y envolvente de cada canal) y coeficientes_filtros.txt."""
    dest = sample_folder(dest_root, sample_file)
    dest.mkdir(parents=True, exist_ok=True)
    head, row = results_row(result, Path(sample_file).name)
    line_head, line_row = ",".join(head), ",".join(_fmt(v) for v in row)
    (dest / "resultados.csv").write_text(f"{line_head}\n{line_row}\n", encoding="utf-8")
    summary = dest / "resumen_muestras.csv"
    new = not summary.exists() or summary.stat().st_size == 0
    with summary.open("a", encoding="utf-8", newline="") as f:
        if new:
            f.write(line_head + "\n")
        f.write(line_row + "\n")
    cols = [result.t] + [c.v_band for c in result.channels] + [c.rms for c in result.channels]
    names = ["t"] + [f"v{i}fBanda" for i in range(len(result.channels))] + [f"rms{i}" for i in
                                                                             range(len(result.channels))]
    table = np.column_stack(cols)
    with (dest / "senales.csv").open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(names) + "\n")
        for r in table:
            f.write(",".join(f"{v:.10g}" for v in r) + "\n")
    (dest / "coeficientes_filtros.txt").write_text(coefficients_text(result), encoding="utf-8")
    return dest
