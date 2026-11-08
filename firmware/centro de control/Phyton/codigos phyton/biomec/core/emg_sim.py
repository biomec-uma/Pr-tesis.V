"""Paciente virtual: señales EMG realistas para probar la IA sin electrodos.

Modelo: 8 electrodos repartidos alrededor del antebrazo (0 = cara dorsal,
extensores; 4 = cara palmar, flexores). Cada movimiento activa un patrón de
músculos distinto. La señal de cada canal es ruido de banda 20-150 Hz cuya
amplitud sigue esa activación (así es el EMG de superficie), más el ruido de
fondo, el zumbido de 50 Hz de la red y el offset de continua del ADS1198.

Con 2 canales (los que usa ahora el equipo) se distinguen bien 3-4
movimientos; Pinza/Cerrar y Señalar/Co-contracción se confunden a propósito,
como pasaría en la realidad: con 4 u 8 canales dejan de confundirse.

La app controla al paciente con PATIENT (lo usa el simulador del puente).
"""

import math
import zlib

import numpy as np

from .emg import Biquad

# Activación (0-1) de cada uno de los 8 electrodos en cada movimiento.
MOVEMENTS = {
    "Reposo":         [0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03],
    "Abrir mano":     [1.00, 0.80, 0.35, 0.10, 0.12, 0.10, 0.30, 0.75],
    "Cerrar mano":    [0.15, 0.20, 0.50, 0.90, 1.00, 0.85, 0.40, 0.20],
    "Pinza":          [0.30, 0.15, 0.20, 0.75, 0.70, 0.25, 0.10, 0.20],
    "Señalar":        [0.55, 0.85, 0.30, 0.15, 0.50, 0.60, 0.20, 0.15],
    "Co-contracción": [0.85, 0.70, 0.60, 0.70, 0.90, 0.70, 0.60, 0.70],
}
# Qué electrodos se usan según el número de canales.
ELECTRODES = {1: [0], 2: [0, 4], 3: [0, 3, 5], 4: [0, 2, 4, 6], 6: [0, 1, 3, 4, 5, 7], 8: list(range(8))}
CHANNEL_OPTIONS = (2, 4, 8)


def pattern(name: str) -> np.ndarray:
    """Patrón de activación de un movimiento. Los que inventa el usuario ("Rotar muñeca")
    reciben uno propio, siempre el mismo para el mismo nombre."""
    if name in MOVEMENTS:
        return np.array(MOVEMENTS[name])
    rng = np.random.default_rng(zlib.crc32(name.encode("utf-8")))
    return rng.uniform(0.1, 1.0, 8)

AMPLITUDE = 220.0     # cuentas del ADC con activación 1 (≈ 4 mV con ganancia 4)
NOISE_FLOOR = 2.5     # ruido de fondo (cuentas)
HUM = 6.0             # 50 Hz de la red (cuentas)
TAU_S = 0.06          # dinámica de activación del músculo


class VirtualPatient:
    def __init__(self, channels: int = 2, fs: int = 500, seed: int | None = None):
        self.fs = fs
        self.movement = "Reposo"
        self.level = 0.8                     # intensidad de la contracción (0-1)
        self._rng = np.random.default_rng(seed)
        self._act = np.full(8, MOVEMENTS["Reposo"][0])
        self._gain = np.ones(8)
        self._offset = self._rng.uniform(-500, 300, 8)
        self._phase = self._rng.uniform(0, 2 * math.pi, 8)
        self._tremor = self._rng.uniform(0, 2 * math.pi, 8)
        self._n = 0
        self._bp = [Biquad.design("bandpass", 85, fs, 0.6, 8), Biquad.design("highpass", 20, fs, 0.7071, 8)]
        self._norm = 1.0
        self._norm = 1.0 / max(float(self._colored(4000).std()), 1e-9)  # ruido coloreado con σ = 1 (y filtros asentados)
        self.channels = channels

    @property
    def channels(self) -> int:
        return len(self._electrodes)

    @channels.setter
    def channels(self, n: int) -> None:
        self._electrodes = ELECTRODES.get(n, ELECTRODES[2])

    def set_movement(self, name: str, level: float | None = None) -> None:
        if name != self.movement:
            # cada contracción sale un poco distinta: ganancia global y de cada músculo
            self._gain = self._rng.uniform(0.75, 1.25, 8) * self._rng.uniform(0.6, 1.15)
        self.movement = name
        if level is not None:
            self.level = float(np.clip(level, 0, 1))

    def _colored(self, n: int) -> np.ndarray:
        x = self._rng.standard_normal((n, 8))
        for f in self._bp:
            x = f.process(x)
        return x * self._norm

    def generate(self, n: int) -> np.ndarray:
        """Siguiente bloque de n muestras: (n, canales) en cuentas del ADC (int)."""
        base = np.array(MOVEMENTS["Reposo"])
        if self.movement == "Reposo":
            target = base
        else:
            target = np.maximum(pattern(self.movement) * self._gain * self.level, base)
        # activación con dinámica de 1er orden (exacta para un objetivo constante en el bloque)
        decay = math.exp(-1.0 / (self.fs * TAU_S))
        k = decay ** np.arange(1, n + 1)[:, None]
        act = target + (self._act - target) * k
        self._act = act[-1]
        t = (self._n + np.arange(n))[:, None] / self.fs
        self._n += n
        tremor = 1 + 0.15 * np.sin(2 * math.pi * 0.7 * t + self._tremor)  # la fuerza nunca es constante
        sig = (act * tremor * AMPLITUDE * self._colored(n)
               + NOISE_FLOOR * self._rng.standard_normal((n, 8))
               + HUM * np.sin(2 * math.pi * 50 * t + self._phase)
               + self._offset)
        return np.clip(np.round(sig[:, self._electrodes]), -32768, 32767).astype(np.int32)


PATIENT = VirtualPatient()
