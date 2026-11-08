"""Gráficas en tiempo real de la telemetría (líneas 'DATA clave=valor ...').

No hay que configurar nada: cada clave nueva que llegue crea su propia
curva automáticamente. Si la mano empieza a enviar 'DATA fsr1=...' aparece sola.
"""

import bisect
import csv
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.protocol import MessageKind
from ..ui.theme import PALETTES, PLOT_COLORS
from .base import BasePage

MAX_POINTS = 20000  # por señal


class Series:
    def __init__(self, key: str, color: str):
        self.key = key
        self.color = color
        self.t: deque[float] = deque(maxlen=MAX_POINTS)
        self.y: deque[float] = deque(maxlen=MAX_POINTS)
        self.curve = None
        self.checkbox: QCheckBox | None = None
        self.value_label: QLabel | None = None


class TelemetryPage(BasePage):
    title = "Gráficas"
    icon = "📈"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._series: dict[str, Series] = {}
        self._t0 = time.monotonic()
        self._paused = False
        self._dirty = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # --- Gráfica
        plot_card, plot_layout = self.card("Telemetría en tiempo real")
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Ventana (s):"))
        self.window_s = QSpinBox()
        self.window_s.setRange(1, 600)
        self.window_s.setValue(10)
        toolbar.addWidget(self.window_s)
        self.pause_btn = QPushButton("Pausar")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._toggle_pause)
        clear_btn = QPushButton("Borrar")
        clear_btn.clicked.connect(self.clear)
        export_btn = QPushButton("Exportar CSV…")
        export_btn.clicked.connect(self.export_csv)
        toolbar.addStretch(1)
        toolbar.addWidget(self.pause_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(export_btn)
        plot_layout.addLayout(toolbar)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "tiempo", units="s")
        self.plot.addLegend(offset=(10, 10))
        plot_layout.addWidget(self.plot, 1)
        root.addWidget(plot_card, 1)

        # --- Panel de señales
        side_card, side_layout = self.card("Señales")
        side_card.setFixedWidth(230)
        self.signals_box = QWidget()
        self.signals_box.setObjectName("transparent")
        self.signals_grid = QGridLayout(self.signals_box)
        self.signals_grid.setContentsMargins(0, 0, 0, 0)
        self.signals_grid.setColumnStretch(0, 1)
        side_layout.addWidget(self.signals_box)
        self.empty_hint = QLabel("Esperando líneas\n'DATA clave=valor'…\n\nPrueba el comando\nSTREAM 1")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        side_layout.addWidget(self.empty_hint)
        side_layout.addStretch(1)
        self.rate_label = QLabel("0 muestras/s")
        self.rate_label.setObjectName("muted")
        side_layout.addWidget(self.rate_label)
        root.addWidget(side_card)

        self._samples_since = 0
        self._rate_clock = time.monotonic()

        # Redibujar a ~30 FPS, independiente de la velocidad de llegada de datos.
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._redraw)
        self.timer.start()
        self.on_theme_changed(ctx.theme)

    # ------------------------------------------------------------ recepción
    def on_message(self, msg) -> None:
        if msg.kind is not MessageKind.DATA or not msg.values:
            return
        now = time.monotonic() - self._t0
        for key, value in msg.values.items():
            series = self._series.get(key) or self._add_series(key)
            series.t.append(now)
            series.y.append(value)
        self._samples_since += 1
        self._dirty = True

    def _add_series(self, key: str) -> Series:
        color = PLOT_COLORS[len(self._series) % len(PLOT_COLORS)]
        s = Series(key, color)
        s.curve = self.plot.plot(name=key, pen=pg.mkPen(color, width=2))
        row = len(self._series)
        s.checkbox = QCheckBox(key)
        s.checkbox.setChecked(True)
        s.checkbox.setStyleSheet(f"color: {color}; font-weight: 600;")
        s.checkbox.toggled.connect(s.curve.setVisible)
        s.value_label = QLabel("—")
        s.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.value_label.setMinimumWidth(70)  # que quepan valores como "-255" o "1.234e+03"
        self.signals_grid.addWidget(s.checkbox, row, 0)
        self.signals_grid.addWidget(s.value_label, row, 1)
        self.empty_hint.hide()
        self._series[key] = s
        return s

    # -------------------------------------------------------------- dibujo
    def _redraw(self) -> None:
        elapsed = time.monotonic() - self._rate_clock
        if elapsed >= 1.0:
            self.rate_label.setText(f"{self._samples_since / elapsed:.0f} muestras/s")
            self._samples_since = 0
            self._rate_clock = time.monotonic()
        if self._paused or not self._dirty or not self.isVisible():
            return
        self._dirty = False
        latest = max((s.t[-1] for s in self._series.values() if s.t), default=0.0)
        start = latest - self.window_s.value()
        for s in self._series.values():
            if not s.t:
                continue
            # Solo se dibuja lo que cabe en la ventana: rápido aunque haya muchos datos.
            t, y = list(s.t), list(s.y)
            i = bisect.bisect_left(t, start)
            s.curve.setData(t[i:], y[i:])
            s.value_label.setText(f"{s.y[-1]:.4g}")
        self.plot.setXRange(max(0.0, start), max(latest, self.window_s.value()), padding=0)

    def _toggle_pause(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.setText("Reanudar" if paused else "Pausar")
        self._dirty = True

    def clear(self) -> None:
        for s in self._series.values():
            self.plot.removeItem(s.curve)
            s.checkbox.deleteLater()
            s.value_label.deleteLater()
        self._series.clear()
        self.plot.plotItem.legend.clear()
        self._t0 = time.monotonic()
        self.empty_hint.show()

    def export_csv(self) -> None:
        if not self._series:
            self.ctx.notify("No hay datos de telemetría que exportar.", error=True)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar telemetría", "telemetria.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["señal", "tiempo_s", "valor"])
            for s in self._series.values():
                writer.writerows((s.key, f"{t:.4f}", v) for t, v in zip(s.t, s.y))
        self.ctx.notify(f"Telemetría exportada a {path}")

    def on_theme_changed(self, theme: str) -> None:
        p = PALETTES[theme]
        self.plot.setBackground(p["plot_bg"])
        for axis in ("left", "bottom"):
            ax = self.plot.getAxis(axis)
            ax.setPen(p["plot_axis"])
            ax.setTextPen(p["plot_axis"])
