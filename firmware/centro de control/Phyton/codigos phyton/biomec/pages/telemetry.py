"""Gráficas en tiempo real de la telemetría (líneas 'DATA clave=valor ...').

Dos gráficas con el eje de tiempo sincronizado:
  - Motores: PWM de cada dedo (−255…+255; + abre, − cierra), escala fija.
  - Otras señales: pulgar (°), gesto y cualquier valor nuevo que envíe la mano.
Cada comando enviado deja una marca vertical con su nombre (como las
anotaciones de Grafana), para ver qué provocó cada movimiento.

No hay que configurar nada: cada clave nueva que llegue crea su propia curva.
Para que una señal nueva vaya a la gráfica de motores, añádela a MOTOR_KEYS.
"""

import bisect
import csv
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QSpinBox, QWidget

from ..core.protocol import MessageKind
from ..ui.theme import PALETTES, PLOT_COLORS
from .base import BasePage

MAX_POINTS = 20000      # por señal
MAX_MARKERS = 60
MOTOR_KEYS = {"indice", "medio", "anular"}


def _format_value(key: str, value: float, muted: str) -> str:
    """Valor con su unidad: PWM de los motores, grados del pulgar y nombre del gesto."""
    from ..core.gestures import GESTOS
    if key in MOTOR_KEYS:
        return f"{value:.0f} <span style='color:{muted}'>PWM</span>"
    if key == "pulgar":
        return f"{value:.0f}°"
    if key == "gesto":
        g = int(value)
        return f"{g} · {GESTOS[g - 1].nombre}" if 1 <= g <= len(GESTOS) else "personalizado"
    return f"{value:.4g}"


class Series:
    def __init__(self, key: str, color: str):
        self.key = key
        self.color = color
        self.t: deque[float] = deque(maxlen=MAX_POINTS)
        self.y: deque[float] = deque(maxlen=MAX_POINTS)
        self.curve = None
        self.plot = None
        self.checkbox: QCheckBox | None = None
        self.value_label: QLabel | None = None


class TelemetryPage(BasePage):
    title = "Gráficas"
    subtitle = "Telemetría en tiempo real: cada valor que envía la mano se dibuja automáticamente"
    icon = "activity"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._series: dict[str, Series] = {}
        self._markers: deque[tuple[float, list]] = deque()
        self._t0 = time.monotonic()
        self._paused = False
        self._dirty = False

        ctx.replay_changed.connect(lambda _r: self.clear())

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # --- Gráficas
        window_label = QLabel("Ventana")
        window_label.setObjectName("muted")
        self.window_s = QSpinBox()
        self.window_s.setRange(1, 600)
        self.window_s.setValue(10)
        self.window_s.setSuffix(" s")
        self.window_s.setFixedWidth(84)
        self.window_s.setToolTip("Segundos que se muestran en la gráfica")
        self.markers_chk = QCheckBox("Comandos")
        self.markers_chk.setChecked(True)
        self.markers_chk.setToolTip("Marca en la gráfica el momento en que se envía cada comando")
        self.markers_chk.toggled.connect(self._toggle_markers)
        self.pause_btn = self.button("", "pause", "ghost", "Pausar: congela la gráfica (los datos se siguen guardando)")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._toggle_pause)
        clear_btn = self.button("", "trash", "ghost", "Borrar todas las curvas")
        clear_btn.clicked.connect(self.clear)
        export_btn = self.button("", "download", "ghost", "Exportar los datos a un archivo CSV")
        export_btn.clicked.connect(self.export_csv)
        plot_card, plot_layout = self.card(
            "Señales", [self.markers_chk, window_label, self.window_s, self.pause_btn, clear_btn, export_btn])

        pg.setConfigOptions(antialias=True)
        self.glw = pg.GraphicsLayoutWidget()
        self.p_motors = self.glw.addPlot(row=0, col=0)
        self.p_other = self.glw.addPlot(row=1, col=0)
        self.glw.ci.layout.setRowStretchFactor(0, 3)
        self.glw.ci.layout.setRowStretchFactor(1, 2)
        self.glw.ci.setSpacing(10)
        self.p_other.setXLink(self.p_motors)
        for plot, label in ((self.p_motors, "Motores · PWM"), (self.p_other, "Pulgar (°) · gesto")):
            plot.showGrid(x=True, y=True, alpha=0.12)
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.setLabel("left", label)
            plot.getAxis("left").setWidth(62)
            # sin leyenda dentro de la gráfica (tapaba las curvas): hace de leyenda el panel "Valores actuales"
        self.p_motors.getAxis("bottom").setStyle(showValues=False)
        self.p_other.setLabel("bottom", "tiempo", units="s")
        self.p_motors.setYRange(-280, 280, padding=0)
        self.p_motors.setMouseEnabled(x=False, y=False)
        self.p_other.setMouseEnabled(x=False, y=True)
        self.zero_line = pg.InfiniteLine(pos=0, angle=0, movable=False)
        self.p_motors.addItem(self.zero_line, ignoreBounds=True)
        plot_layout.addWidget(self.glw, 1)
        root.addWidget(plot_card, 1)

        # --- Panel de valores
        side_card, side_layout = self.card("Valores actuales")
        side_card.setFixedWidth(250)
        self.signals_box = QWidget()
        self.signals_grid = QGridLayout(self.signals_box)
        self.signals_grid.setContentsMargins(0, 0, 0, 0)
        self.signals_grid.setColumnStretch(0, 1)
        side_layout.addWidget(self.signals_box)
        self.empty_hint = QLabel("Aún no llegan datos.\n\nLa telemetría se activa sola al conectar;\n"
                                 "si la desactivaste, actívala aquí.")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        side_layout.addWidget(self.empty_hint)
        self.stream_btn = self.button("Activar telemetría", "zap", "primary", "Envía STREAM 1")
        self.stream_btn.clicked.connect(lambda: self.ctx.send_command("STREAM 1"))
        side_layout.addWidget(self.stream_btn)
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
        self.on_connection_changed(ctx.connected, "")

    # ------------------------------------------------------------ recepción
    def on_message(self, msg) -> None:
        if msg.kind is MessageKind.TX:
            self._add_marker(msg.text)
            return
        if msg.kind is not MessageKind.DATA or not msg.values:
            return
        now = time.monotonic() - self._t0
        for key, value in msg.values.items():
            series = self._series.get(key) or self._add_series(key)
            series.t.append(now)
            series.y.append(value)
        self._samples_since += 1
        self._dirty = True

    def on_connection_changed(self, connected: bool, info: str) -> None:
        self.stream_btn.setEnabled(connected)

    def _add_series(self, key: str) -> Series:
        color = PLOT_COLORS[len(self._series) % len(PLOT_COLORS)]
        s = Series(key, color)
        s.plot = self.p_motors if key in MOTOR_KEYS else self.p_other
        s.curve = s.plot.plot(name=key, pen=pg.mkPen(color, width=2))
        self.on_theme_changed(self.ctx.theme)  # la etiqueta nueva de la leyenda, con el color del tema
        row = len(self._series)
        s.checkbox = QCheckBox(key)
        s.checkbox.setChecked(True)
        s.checkbox.setStyleSheet(f"color: {color}; font-weight: 600;")
        s.checkbox.toggled.connect(s.curve.setVisible)
        s.value_label = QLabel("—")
        s.value_label.setObjectName("value")
        s.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.value_label.setMinimumWidth(70)  # que quepan valores como "-255" o "1.234e+03"
        s.value_label.setTextFormat(Qt.RichText)
        self.signals_grid.addWidget(s.checkbox, row, 0)
        self.signals_grid.addWidget(s.value_label, row, 1)
        self.empty_hint.hide()
        self.stream_btn.hide()
        self._series[key] = s
        return s

    # ------------------------------------------------------------- marcas
    def _add_marker(self, text: str) -> None:
        t = time.monotonic() - self._t0
        p = PALETTES[self.ctx.theme]
        pen = pg.mkPen(p["tx"], width=1, style=Qt.DashLine)
        # Si el comando anterior fue hace muy poco, solo se dibuja la línea (las etiquetas se pisarían)
        crowded = bool(self._markers) and t - self._markers[-1][0] < 0.8
        label = None if crowded else text.lstrip("@")
        top = pg.InfiniteLine(pos=t, angle=90, movable=False, pen=pen, label=label,
                              labelOpts={"position": 0.96, "color": p["tx"], "anchors": [(0, 0), (0, 0)],
                                         "fill": pg.mkBrush(p["card"])})
        top.setToolTip(text)
        bottom = pg.InfiniteLine(pos=t, angle=90, movable=False, pen=pen)
        for plot, line in ((self.p_motors, top), (self.p_other, bottom)):
            line.setVisible(self.markers_chk.isChecked())
            plot.addItem(line, ignoreBounds=True)
        self._markers.append((t, [top, bottom]))
        while len(self._markers) > MAX_MARKERS:
            _t, lines = self._markers.popleft()
            self.p_motors.removeItem(lines[0])
            self.p_other.removeItem(lines[1])
        self._dirty = True

    def _toggle_markers(self, visible: bool) -> None:
        for _t, lines in self._markers:
            for line in lines:
                line.setVisible(visible)

    # -------------------------------------------------------------- dibujo
    def _redraw(self) -> None:
        muted = PALETTES[self.ctx.theme]["muted"]
        elapsed = time.monotonic() - self._rate_clock
        if elapsed >= 1.0:
            self.rate_label.setText(f"{self._samples_since / elapsed:.0f} muestras/s")
            self._samples_since = 0
            self._rate_clock = time.monotonic()
        if self._paused or not self._dirty or not self.isVisible():
            return
        self._dirty = False
        latest = max((s.t[-1] for s in self._series.values() if s.t), default=0.0)
        if self._markers:
            latest = max(latest, self._markers[-1][0])
        start = latest - self.window_s.value()
        for s in self._series.values():
            if not s.t:
                continue
            # Solo se dibuja lo que cabe en la ventana: rápido aunque haya muchos datos.
            t, y = list(s.t), list(s.y)
            i = bisect.bisect_left(t, start)
            s.curve.setData(t[i:], y[i:])
            s.value_label.setText(_format_value(s.key, s.y[-1], muted))
        self.p_motors.setXRange(max(0.0, start), max(latest, self.window_s.value()), padding=0)

    def _toggle_pause(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.setToolTip("Reanudar la gráfica" if paused else "Pausar: congela la gráfica (los datos se siguen guardando)")
        self._icon_buttons = [(b, ("play" if paused else "pause") if b is self.pause_btn else n, c)
                              for b, n, c in self._icon_buttons]
        self._paint_icons()
        self._dirty = True

    def clear(self) -> None:
        for s in self._series.values():
            s.plot.removeItem(s.curve)
            s.checkbox.deleteLater()
            s.value_label.deleteLater()
        self._series.clear()
        for _t, lines in self._markers:
            self.p_motors.removeItem(lines[0])
            self.p_other.removeItem(lines[1])
        self._markers.clear()
        for plot in (self.p_motors, self.p_other):
            plot.legend.clear()
        self._t0 = time.monotonic()
        self.empty_hint.show()
        self.stream_btn.show()

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
            for t, lines in self._markers:  # los comandos también, para poder analizarlos
                writer.writerow(["comando", f"{t:.4f}", lines[0].toolTip()])
        self.ctx.notify(f"Telemetría exportada a {path}")

    def on_theme_changed(self, theme: str) -> None:
        p = PALETTES[theme]
        self.glw.setBackground(p["card"])  # la gráfica se funde con su tarjeta
        self.zero_line.setPen(pg.mkPen(p["border_strong"], width=1))
        for plot in (self.p_motors, self.p_other):
            for axis in ("left", "bottom"):
                ax = plot.getAxis(axis)
                ax.setPen(pg.mkPen(p["border_strong"]))
                ax.setTextPen(pg.mkPen(p["muted"]))
            legend = plot.legend
            if legend is not None:
                fill = pg.mkColor(p["card"])
                fill.setAlpha(200)
                legend.setBrush(pg.mkBrush(fill))
                legend.setPen(pg.mkPen(p["border"]))
                legend.setLabelTextColor(p["text"])
                for _sample, label in legend.items:  # pyqtgraph solo aplica el color al volver a escribir el texto
                    label.setText(label.text, color=p["text"])
        pen = pg.mkPen(p["tx"], width=1, style=Qt.DashLine)
        for _t, lines in self._markers:
            for line in lines:
                line.setPen(pen)
            label = getattr(lines[0], "label", None)  # las marcas "amontonadas" no tienen etiqueta
            if label is not None:
                label.setColor(p["tx"])
                label.fill = pg.mkBrush(p["card"])
