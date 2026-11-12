"""Gráficas: ventanas de señales en tiempo real (puede haber varias, cada una con sus señales).

    ┌ Gráficas ─────────────────────────────────────────── [Señales…] ☑ Comandos  Ventana 10 s  ⏸ 🗑 ⬇ ┐
    │ Motores · PWM  ┆ GESTO 3 ░░░░░░░░░░░░░ fin                    │ ● Índice · PWM        −255 PWM │
    │                ┆  curvas                                      │ ● Medio · PWM            0 PWM │
    │ Pulgar (°)     ┆                                              │ ● Pulgar                  90 ° │
    │ Estado         ┆                                              │ ● Gesto activo   3 · Índice y… │
    │   00:12   00:14   00:16   00:18   00:20  (mm:ss)              │                  20 muestras/s │
    └──────────────────────────────────────────────────────────────┴────────────────────────────────┘

- Cada grupo del catálogo (config/signals.json) es una magnitud distinta y va en su propia gráfica,
  con el eje de tiempo compartido (mm:ss desde que se empezó a recibir).
- Marcas: cada comando deja una línea discontinua en el instante en que se envía y, si mueve los
  motores, una zona sombreada hasta que terminan de moverse (el fin de la ejecución). Los movimientos
  que inicia la propia mano (modo demo) se marcan en gris.
- Los datos viven en ctx.signals (core/signals.py): todas las ventanas de Gráficas los comparten.
  "Nueva gráfica" (o clic derecho en una señal) abre otra ventana con las señales que se elijan.
"""

import csv
import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.gestures import GESTOS
from ..core.signals import Marker, fmt_clock
from ..ui.theme import PALETTES, PLOT_COLORS
from ..ui.widgets import ElidedLabel
from .base import BasePage

DEFAULT_KEYS = ["indice", "medio", "anular", "pulgar", "gesto"]


def _format_value(key: str, value: float, unit: str, muted: str) -> str:
    """Valor con su unidad; el gesto, con su nombre."""
    if key == "gesto":
        g = int(value)
        return f"{g} · {GESTOS[g - 1].nombre}" if 1 <= g <= len(GESTOS) else "postura propia"
    text = f"{value:.0f}" if abs(value) >= 10 or value == int(value) else f"{value:.2f}"
    return f"{text} <span style='color:{muted}'>{unit}</span>" if unit else text


class TimeAxis(pg.AxisItem):
    """Eje de tiempo en mm:ss (en vez de segundos con prefijos como 'ks')."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        decimals = 1 if spacing < 1 else 0
        return [fmt_clock(v, decimals) for v in values]


# ============================================================ selector
class SignalPicker(QDialog):
    """Qué señales dibujar: todas las del catálogo, por grupos (las pendientes, en gris)."""

    def __init__(self, parent, ctx, selected: list[str], title: str = "Señales de la gráfica"):
        super().__init__(parent)
        self.setObjectName("infoDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        from ..ui.widgets import style_titlebar
        style_titlebar(self, ctx.theme)
        self.ctx = ctx
        store, catalog = ctx.signals, ctx.signals.catalog
        with_data = set(store.keys_with_data())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        head = QLabel(title)
        head.setObjectName("pageTitle")
        lay.addWidget(head)
        hint = QLabel("Cada grupo es una magnitud distinta y va en su propia gráfica, con el tiempo sincronizado. "
                      "Las señales en gris están previstas pero la mano aún no las envía.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(360)
        body = QWidget()
        body.setObjectName("transparent")
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        self.boxes: dict[str, QCheckBox] = {}
        row = 0
        keys = list(catalog.signals) + [k for k in with_data if k not in catalog.signals]
        for group, group_keys in catalog.by_group(keys):
            cap = QLabel(group.title.upper() + (f"  ·  {group.unit}" if group.unit else ""))
            cap.setObjectName("caption")
            grid.addWidget(cap, row, 0, 1, 2)
            row += 1
            for i, key in enumerate(group_keys):
                sd = catalog.define(key)
                box = QCheckBox(sd.name + ("  (pendiente)" if not sd.available else ""))
                box.setChecked(key in selected)
                box.setEnabled(sd.available)
                tip = [f"Clave: {key}", f"Origen: {sd.source}"]
                if sd.note:
                    tip.append(sd.note)
                if sd.available and key not in with_data:
                    tip.append("Todavía no han llegado datos de esta señal.")
                box.setToolTip("\n".join(tip))
                grid.addWidget(box, row + i // 2, i % 2)
                self.boxes[key] = box
            row += (len(group_keys) + 1) // 2
        grid.setRowStretch(row, 1)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        lay.addWidget(scroll, 1)

        quick = QHBoxLayout()
        arriving = QPushButton("Las que están llegando")
        arriving.setToolTip("Marca solo las señales de las que ya hay datos")
        arriving.clicked.connect(lambda: self._set(with_data))
        none = QPushButton("Ninguna")
        none.clicked.connect(lambda: self._set(set()))
        quick.addWidget(arriving)
        quick.addWidget(none)
        quick.addStretch(1)
        lay.addLayout(quick)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Aplicar")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _set(self, keys) -> None:
        for key, box in self.boxes.items():
            if box.isEnabled():
                box.setChecked(key in keys)

    def keys(self) -> list[str]:
        return [k for k, b in self.boxes.items() if b.isChecked()]


# ============================================================== gráfica
class GraphPanel(BasePage):
    title = "Gráficas"
    subtitle = "Señales en tiempo real; cada comando deja una marca con su inicio y su fin"
    icon = "activity"
    keys_changed = Signal()                 # para guardar la configuración de la ventana
    open_in_new = Signal(list)              # abrir otra ventana con estas señales

    def __init__(self, ctx, keys: list[str] | None = None, name: str = "Gráficas"):
        super().__init__(ctx)
        self.store = ctx.signals
        self.name = name
        self.keys = list(keys or DEFAULT_KEYS)
        self._paused = False
        self.plots: dict[str, pg.PlotItem] = {}
        self.curves: dict[str, pg.PlotDataItem] = {}
        self.rows: dict[str, tuple[QCheckBox, QLabel]] = {}
        self._marker_items: dict[int, dict] = {}
        self._last_rate = -1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # --- barra de herramientas de la ventana
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.pick_btn = self.button("Señales…", "list", "", "Elegir qué señales se dibujan en esta ventana")
        self.pick_btn.clicked.connect(self.pick_signals)
        bar.addWidget(self.pick_btn)
        bar.addStretch(1)
        self.markers_chk = QCheckBox("Marcas")
        self.markers_chk.setChecked(True)
        self.markers_chk.setToolTip("Marca cada comando: línea al enviarlo y zona sombreada hasta que la mano\n"
                                    "termina de ejecutarlo. En gris, los movimientos que inicia la propia mano (demo).")
        self.markers_chk.toggled.connect(self._toggle_markers)
        bar.addWidget(self.markers_chk)
        bar.addSpacing(6)
        self.window_s = QSpinBox()
        self.window_s.setRange(1, 600)
        self.window_s.setValue(10)
        self.window_s.setSuffix(" s")
        self.window_s.setFixedWidth(78)
        self.window_s.setToolTip("Ventana de tiempo: segundos que se muestran")
        bar.addWidget(self.window_s)
        self.pause_btn = self.button("", "pause", "ghost", "Pausar: congela la gráfica (los datos se siguen guardando)")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._toggle_pause)
        clear_btn = self.button("", "trash", "ghost", "Borrar los datos (de todas las ventanas de Gráficas)")
        clear_btn.clicked.connect(self.clear)
        export_btn = self.button("", "download", "ghost", "Exportar las señales de esta ventana a CSV")
        export_btn.clicked.connect(self.export_csv)
        for b in (self.pause_btn, clear_btn, export_btn):
            bar.addWidget(b)
        root.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(12)
        pg.setConfigOptions(antialias=True)
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setMinimumSize(260, 180)
        body.addWidget(self.glw, 1)

        # --- columna de valores (hace de leyenda)
        side = QWidget()
        side.setFixedWidth(190)
        self.side = QVBoxLayout(side)
        self.side.setContentsMargins(0, 0, 0, 0)
        self.side.setSpacing(6)
        self.values_box = QWidget()
        self.values_grid = QGridLayout(self.values_box)
        self.values_grid.setContentsMargins(0, 0, 0, 0)
        self.values_grid.setHorizontalSpacing(6)
        self.values_grid.setVerticalSpacing(4)
        self.values_grid.setColumnStretch(0, 1)
        self.side.addWidget(self.values_box)
        self.empty_hint = QLabel("Aún no llegan datos.\n\nLa telemetría se activa sola al conectar; "
                                 "si la desactivaste, actívala aquí.")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setWordWrap(True)
        self.side.addWidget(self.empty_hint)
        self.stream_btn = self.button("Activar telemetría", "zap", "primary", "Envía STREAM 1")
        self.stream_btn.clicked.connect(lambda: self.ctx.send_command("STREAM 1"))
        self.side.addWidget(self.stream_btn)
        self.side.addStretch(1)
        self.rate_label = QLabel("")
        self.rate_label.setObjectName("muted")
        self.side.addWidget(self.rate_label)
        body.addWidget(side)
        root.addLayout(body, 1)

        self._build_plots()
        self.timer = QTimer(self)
        self.timer.setInterval(33)   # ~30 FPS, independiente del ritmo de llegada de datos
        self.timer.timeout.connect(self._redraw)
        self.timer.start()
        self.on_theme_changed(ctx.theme)
        self.on_connection_changed(ctx.connected, "")

    # ------------------------------------------------------------ señales
    def set_keys(self, keys: list[str]) -> None:
        self.keys = [k for k in dict.fromkeys(keys)]   # sin repetidos, mismo orden
        self._build_plots()
        self.on_theme_changed(self.ctx.theme)
        self.keys_changed.emit()

    def pick_signals(self) -> None:
        dialog = SignalPicker(self.window(), self.ctx, self.keys)
        if dialog.exec() == QDialog.Accepted:
            self.set_keys(dialog.keys())

    def _build_plots(self) -> None:
        catalog = self.store.catalog
        self.glw.clear()
        self.plots.clear()
        self.curves.clear()
        for key, (box, label) in self.rows.items():
            box.deleteLater()
            label.deleteLater()
        self.rows.clear()
        self._marker_items.clear()

        colors = {key: PLOT_COLORS[i % len(PLOT_COLORS)] for i, key in enumerate(self.keys)}
        groups = catalog.by_group(self.keys)
        first = None
        for row, (group, keys) in enumerate(groups):
            last = row == len(groups) - 1
            plot = self.glw.addPlot(row=row, col=0, axisItems={"bottom": TimeAxis(orientation="bottom")})
            plot.showGrid(x=True, y=True, alpha=0.12)
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.setLabel("left", group.axis_label)
            plot.getAxis("left").setWidth(58)
            plot.setMouseEnabled(x=False, y=group.range is None)
            if group.range:
                plot.setYRange(group.range[0], group.range[1], padding=0)
                if group.range[0] < 0 < group.range[1]:
                    zero = pg.InfiniteLine(pos=0, angle=0, movable=False)
                    zero.setZValue(-5)
                    plot.addItem(zero, ignoreBounds=True)
                    plot._biomec_zero = zero
            else:
                plot.enableAutoRange(axis="y")
            if last:
                plot.setLabel("bottom", "tiempo (mm:ss)")
            else:
                plot.getAxis("bottom").setStyle(showValues=False)
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            self.glw.ci.layout.setRowStretchFactor(row, 3 if group.id in ("pwm", "emg_bruto", "emg_filtrado") else 2)
            self.plots[group.id] = plot
            emg = group.id in ("emg_bruto", "emg_filtrado")
            for key in keys:
                # En escalón: cada valor se mantiene hasta que llega el siguiente (la telemetría llega cada
                # 50 ms). Con líneas rectas entre muestras, el tramo desde la última muestra anterior a un
                # comando salía inclinado y la curva parecía cambiar ANTES de la marca del comando.
                # El EMG (500 Hz) se dibuja con líneas: sus muestras están muy juntas.
                # stepMode "right": el escalón de cada muestra se extiende hacia la derecha (hasta la siguiente)
                curve = plot.plot(pen=pg.mkPen(colors[key], width=1.2 if emg else 2),
                                  stepMode=None if emg else "right")
                curve.setDownsampling(auto=True, method="peak")
                curve.setClipToView(True)
                self.curves[key] = curve
        self.glw.ci.setSpacing(8)
        if not groups:
            plot = self.glw.addPlot(row=0, col=0, axisItems={"bottom": TimeAxis(orientation="bottom")})
            plot.setLabel("bottom", "tiempo (mm:ss)")
            plot.setLabel("left", "Elige señales con «Señales…»")
            plot.hideButtons()
            self.plots["_vacio"] = plot

        for i, key in enumerate(self.keys):
            sd = catalog.define(key)
            box = QCheckBox()
            box.setChecked(True)
            box.setToolTip(f"{sd.name}\nClave: {key}" + (f"\n{sd.note}" if sd.note else ""))
            box.setStyleSheet(f"color: {colors[key]}; font-weight: 600;")
            name = ElidedLabel(sd.short_name)
            name.setToolTip(box.toolTip())
            name.setStyleSheet(f"color: {colors[key]}; font-weight: 600;")
            name.setContextMenuPolicy(Qt.CustomContextMenu)
            name.customContextMenuRequested.connect(lambda pos, k=key, w=name: self._row_menu(k, w.mapToGlobal(pos)))
            value = QLabel("—")
            value.setObjectName("value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setTextFormat(Qt.RichText)
            value.setMinimumWidth(64)
            box.toggled.connect(lambda on, k=key: self.curves[k].setVisible(on) if k in self.curves else None)
            cell = QHBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(4)
            holder = QWidget()
            holder.setLayout(cell)
            cell.addWidget(box)
            cell.addWidget(name, 1)
            self.values_grid.addWidget(holder, i, 0)
            self.values_grid.addWidget(value, i, 1)
            self.rows[key] = (holder, value)
        self._update_empty_state()

    def _row_menu(self, key: str, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Abrir en una ventana nueva", lambda: self.open_in_new.emit([key]))
        menu.addAction("Quitar de esta gráfica", lambda: self.set_keys([k for k in self.keys if k != key]))
        menu.exec(pos)

    # ------------------------------------------------------------ marcas
    def _marker_pen(self, m: Marker, p: dict) -> pg.QtGui.QPen:
        if m.kind == "hand":
            return pg.mkPen(p["subtle"], width=1, style=Qt.DotLine)
        return pg.mkPen(p["tx"], width=1, style=Qt.DashLine)

    def _ensure_marker(self, m: Marker, prev: Marker | None, p: dict) -> dict:
        items = self._marker_items.get(id(m))
        if items is not None:
            return items
        label = m.label
        color = p["subtle"] if m.kind == "hand" else p["tx"]
        pen = self._marker_pen(m, p)
        lines, regions = [], []
        for i, plot in enumerate(self.plots.values()):
            line = pg.InfiniteLine(pos=m.t0, angle=90, movable=False, pen=pen,
                                   label=label if i == 0 else None,
                                   labelOpts={"position": 0.94, "color": color, "anchors": [(0, 0), (0, 0)],
                                              "fill": pg.mkBrush(p["card"])})
            line.setToolTip(m.text)
            line.setZValue(5)
            line.setVisible(self.markers_chk.isChecked())
            plot.addItem(line, ignoreBounds=True)
            lines.append(line)
        items = {"marker": m, "lines": lines, "ends": [], "regions": regions, "closed": False}
        self._marker_items[id(m)] = items
        return items

    def _add_end_lines(self, items: dict, p: dict) -> None:
        """Fin de la ejecución: línea punteada cuando los motores terminan de moverse y la duración en la etiqueta."""
        m = items["marker"]
        pen = pg.mkPen(p["tx"], width=1, style=Qt.DotLine)
        for plot in self.plots.values():
            line = pg.InfiniteLine(pos=m.t1, angle=90, movable=False, pen=pen)
            line.setToolTip(f"Fin de {m.text}: {m.t1 - m.t0:.2f} s después de enviarlo")
            line.setZValue(5)
            line.setVisible(self.markers_chk.isChecked())
            plot.addItem(line, ignoreBounds=True)
            items["ends"].append(line)
        label = getattr(items["lines"][0], "label", None) if items["lines"] else None
        if label is not None:
            label.setFormat(f"{m.label} · {m.t1 - m.t0:.1f} s")
        for line in items["lines"]:
            line.setToolTip(f"{m.text}\nEnviado en {m.t0:.2f} s · terminado {m.t1 - m.t0:.2f} s después")

    def _region_brush(self, p: dict):
        color = pg.mkColor(p["tx"])
        color.setAlpha(26)
        return pg.mkBrush(color)

    def _sync_markers(self, latest: float) -> None:
        p = PALETTES[self.ctx.theme]
        alive = set()
        prev = None
        first_plot = next(iter(self.plots.values()), None)
        px_per_s = (first_plot.getViewBox().width() if first_plot is not None else 400) / max(self.window_s.value(), 1)
        last_label_t = -1e9
        for m in self.store.markers:
            alive.add(id(m))
            items = self._ensure_marker(m, prev, p)
            prev = m
            # etiquetas: solo si no se pisan con la anterior a la escala actual (las líneas se dibujan siempre)
            label = getattr(items["lines"][0], "label", None) if items["lines"] else None
            if label is not None:
                show = (m.t0 - last_label_t) * px_per_s >= 64
                if show:
                    last_label_t = m.t0
                if label.isVisible() != show:
                    label.setVisible(show)
            if m.kind != "cmd" or items["closed"]:
                continue
            end = latest if m.open else m.t1
            if end is not None and end > m.t0:
                if not items["regions"]:
                    for plot in self.plots.values():
                        region = pg.LinearRegionItem([m.t0, end], movable=False, brush=self._region_brush(p),
                                                     pen=pg.mkPen(None))
                        region.setZValue(-10)
                        region.setVisible(self.markers_chk.isChecked())
                        plot.addItem(region, ignoreBounds=True)
                        items["regions"].append(region)
                else:
                    for region in items["regions"]:
                        region.setRegion([m.t0, end])
            elif not m.open and items["regions"]:   # no movió nada: fuera la zona
                for plot, region in zip(self.plots.values(), items["regions"]):
                    plot.removeItem(region)
                items["regions"] = []
            if not m.open:
                items["closed"] = True
                if m.t1 is not None:
                    self._add_end_lines(items, p)
        for mid in [mid for mid in self._marker_items if mid not in alive]:   # marcas antiguas descartadas
            self._remove_marker_items(self._marker_items.pop(mid))

    def _remove_marker_items(self, items: dict) -> None:
        for kind in ("lines", "ends", "regions"):
            for plot, item in zip(self.plots.values(), items[kind]):
                plot.removeItem(item)

    def _toggle_markers(self, visible: bool) -> None:
        for items in self._marker_items.values():
            for item in items["lines"] + items["ends"] + items["regions"]:
                item.setVisible(visible)

    # -------------------------------------------------------------- dibujo
    def _update_empty_state(self) -> None:
        has_data = any(self.store.series.get(k) and self.store.series[k].t for k in self.keys)
        self.empty_hint.setVisible(not has_data)
        self.stream_btn.setVisible(not has_data)
        self.values_box.setVisible(bool(self.keys))

    def _redraw(self) -> None:
        rate = self.ctx.data_rate
        if rate != self._last_rate:
            self._last_rate = rate
            self.rate_label.setText(f"{rate:.0f} muestras/s" if rate else "")
        if self._paused or not self.isVisible():
            return
        p = PALETTES[self.ctx.theme]
        latest = self.store.latest()
        window = self.window_s.value()
        start = latest - window
        for key, curve in self.curves.items():
            series = self.store.series.get(key)
            if series is None or not series.t:
                if curve.xData is not None and len(curve.xData):   # datos borrados (Borrar, reproducción…)
                    curve.setData([], [])
                    self.rows[key][1].setText("—")
                continue
            t, y = series.window(start)
            curve.setData(t, y)
            unit = self.store.catalog.group_of(key).unit if key != "gesto" else ""
            self.rows[key][1].setText(_format_value(key, series.y[-1], unit, p["muted"]))
        self._sync_markers(latest)
        for plot in self.plots.values():
            axis = plot.getAxis("left")
            tall_enough = plot.getViewBox().height() >= 90   # en gráficas bajas la etiqueta no cabe (se pisaría)
            if getattr(axis, "_biomec_label_on", None) != tall_enough:
                axis._biomec_label_on = tall_enough
                axis.showLabel(tall_enough)
        for plot in self.plots.values():
            plot.setXRange(max(0.0, start), max(latest, float(window)), padding=0)
            break  # los demás van enlazados
        if self.empty_hint.isVisible():
            self._update_empty_state()

    def _toggle_pause(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.setToolTip("Reanudar" if paused else "Pausar: congela la gráfica (los datos se siguen guardando)")
        self._icon_buttons = [(b, ("play" if paused else "pause") if b is self.pause_btn else n, c)
                              for b, n, c in self._icon_buttons]
        self._paint_icons()

    def clear(self) -> None:
        self.store.clear()
        for items in self._marker_items.values():
            self._remove_marker_items(items)
        self._marker_items.clear()
        for curve in self.curves.values():
            curve.setData([], [])
        for _holder, value in self.rows.values():
            value.setText("—")
        self._update_empty_state()

    def on_connection_changed(self, connected: bool, info: str) -> None:
        self.stream_btn.setEnabled(connected)

    def export_csv(self) -> None:
        keys = [k for k in self.keys if self.store.series.get(k) and self.store.series[k].t]
        if not keys:
            self.ctx.notify("No hay datos que exportar en esta ventana.", error=True)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar señales", "telemetria.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["señal", "tiempo_s", "valor"])
            for key in keys:
                s = self.store.series[key]
                writer.writerows((key, f"{t:.4f}", f"{v:g}") for t, v in zip(s.t, s.y))
            writer.writerow(["marca", "inicio_s", "fin_s", "tipo", "texto"])
            for m in self.store.markers:
                writer.writerow(["marca", f"{m.t0:.4f}", f"{m.t1:.4f}" if m.t1 is not None else "",
                                 "comando" if m.kind == "cmd" else "mano", m.text])
        self.ctx.notify(f"Señales exportadas a {path}")

    def on_theme_changed(self, theme: str) -> None:
        p = PALETTES[theme]
        self.glw.setBackground(p["card"])
        for plot in self.plots.values():
            for axis in ("left", "bottom"):
                ax = plot.getAxis(axis)
                ax.setPen(pg.mkPen(p["border_strong"]))
                ax.setTextPen(pg.mkPen(p["muted"]))
            zero = getattr(plot, "_biomec_zero", None)
            if zero is not None:
                zero.setPen(pg.mkPen(p["border_strong"], width=1))
        for items in self._marker_items.values():
            m = items["marker"]
            pen = self._marker_pen(m, p)
            for line in items["lines"]:
                line.setPen(pen)
                label = getattr(line, "label", None)
                if label is not None:
                    label.setColor(p["subtle"] if m.kind == "hand" else p["tx"])
                    label.fill = pg.mkBrush(p["card"])
            for line in items["ends"]:
                line.setPen(pg.mkPen(p["tx"], width=1, style=Qt.DotLine))
            for region in items["regions"]:
                region.setBrush(self._region_brush(p))

    # --------------------------------------------------------- configuración
    def config(self) -> dict:
        return {"nombre": self.name, "claves": list(self.keys), "ventana": self.window_s.value()}

    def apply_config(self, cfg: dict) -> None:
        self.name = cfg.get("nombre", self.name)
        self.window_s.setValue(int(cfg.get("ventana", 10)))
        keys = cfg.get("claves")
        if keys:
            self.set_keys(list(keys))


TelemetryPage = GraphPanel  # nombre anterior
