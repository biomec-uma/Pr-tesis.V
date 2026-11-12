"""Ventana «Analizador EMG»: el analizador de MATLAB del equipo (AnalizadorEMG.mlapp, v1.0) dentro de la app.

┌ [Cargar CSV…] [Analizar] [Guardar…]   muestra.csv · 5000 muestras · 10.0 s            ✓ Analizado ┐
├ Parámetros ──────────────┐ ┌ Gráfica [Señal bruta ▾] ─────────────────────────────────────────────┤
│ Datos del ADC            │ │ canal 0  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿│
│  Vref, ganancia, SPS…    │ │ canal 1  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿│
│ Filtrado (notch, banda)  │ ├ Resultados ──────────────────────────────────────────────────────────┤
│ Detección de contracción │ │ 50 Hz bruta (%) · 50 Hz tras notch (%) · RMS reposo (µV) · Umbral (µV) │
│ Canales del CSV          │ │                                                                       │
└──────────────────────────┘ └───────────────────────────────────────────────────────────────────────┘

El cálculo está en core/emg_analysis.py y da los mismos números que MATLAB (comprobado con los análisis
guardados en el repositorio del equipo). «Guardar» crea <carpeta>/<muestra>/ con figura_1…7.png,
resultados.csv, resumen_muestras.csv, senales.csv y coeficientes_filtros.txt, como guardarAnalisis.m.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, QSettings, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, ORG_NAME
from ..core import emg_analysis as ea
from ..paths import documents_dir
from ..ui.theme import PALETTES, PLOT_COLORS
from .base import BasePage

SETTINGS = "analizador_emg"
VIEWS = ["Señal bruta", "Espectro", "Notch (antes/después)", "Paso banda (antes/después)", "Bruta vs filtrada",
         "Espectrograma", "Envolvente RMS y umbral"]
RESULT_ROWS = [("50 Hz bruta (%)", "p50"), ("50 Hz tras notch (%)", "p50_notch"), ("RMS reposo (µV)", "rest_rms"),
               ("Umbral (µV)", "threshold")]
MAX_CHANNELS = 8
EXPORT_SIZE = (1400, 1000)          # píxeles de cada figura_N.png

# (clave de AnalysisParams, texto, unidad, mínimo, máximo, decimales, paso, ayuda)
PARAM_GROUPS = [
    ("Datos del ADC", [
        ("vref", "Vref", "V", 0.01, 10, 3, 0.1, "Tensión de referencia del ADC: 2.4 V con la referencia interna "
                                                  "del ADS1198 (CONFIG3 PD_REFBUF=1, VREF_4V=0)."),
        ("gain", "Ganancia PGA", "", 1, 24, 0, 1, "Ganancia configurada en el ADS (ADS119X_CHnSET_GAIN_4)."),
        ("sps", "Samples/s", "SPS", 1, 32000, 0, 50, "Muestras por segundo del ADC."),
        ("bits", "Bits", "", 1, 32, 0, 1, "16 bits en el ADS1198."),
    ]),
    ("Filtrado", [
        ("notch_on", "Notch", None, 0, 0, 0, 0, "Quita la red eléctrica con un notch IIR aplicado sin desfase "
                                                 "(filtfilt)."),
        ("f0", "Frecuencia", "Hz", 1, 10000, 1, 1, "Frecuencia de la red: 50 Hz en España."),
        ("q", "Factor de calidad (Q)", "", 0.1, 1000, 1, 1, "Factor de calidad del notch: cuanto mayor, más estrecha "
                                                             "la banda que se elimina."),
        ("band_on", "Pasa banda", None, 0, 0, 0, 0, "Paso banda FIR (ventana de Kaiser, 60 dB) sin desfase, como "
                                                    "bandpass(…, 'ImpulseResponse', 'fir') de MATLAB."),
        ("f_low", "Corte inferior", "Hz", 0.1, 10000, 1, 1, "Frecuencia de corte inferior."),
        ("f_high", "Corte superior", "Hz", 0.1, 10000, 1, 1, "Frecuencia de corte superior. El ADS atenúa por "
                                                              "encima de 0.262·SPS (~131 Hz a 500 SPS)."),
    ]),
    ("Detección de contracción", [
        ("t_rms", "Suavizado RMS", "s", 0.002, 60, 3, 0.05, "Duración de la ventana de la envolvente RMS. Más larga "
                                                            "suaviza más, pero responde más lento."),
        ("k", "Sensibilidad K", "", 0, 100, 2, 0.5, "Umbral = media del reposo + k · desviación típica. Un k menor "
                                                     "detecta más, pero da más falsas activaciones."),
        ("rest_start", "Reposo desde", "s", 0, 100000, 2, 0.5, "Inicio del tramo en reposo (sin contraer)."),
        ("rest_end", "Reposo hasta", "s", 0, 100000, 2, 0.5, "Fin del tramo en reposo."),
        ("t_window", "Ventana espectrograma", "s", 0.01, 100, 3, 0.05,
         "Duración de cada trozo de señal con el que se calcula el espectrograma. Una ventana corta (0.1 s) ve "
         "mejor cuándo empieza y acaba cada contracción, pero distingue peor las frecuencias. Una ventana larga "
         "(0.5 s) hace lo contrario. Recomendado: 0.25 s. Solo afecta a la gráfica del espectrograma."),
    ]),
]

# viridis (CC0) con 9 paradas: no depende de los archivos de mapas de pyqtgraph (el .exe no los lleva)
VIRIDIS = pg.ColorMap(np.linspace(0, 1, 9), [(68, 1, 84), (71, 44, 122), (59, 81, 139), (44, 113, 142),
                                              (33, 144, 141), (39, 173, 129), (92, 200, 99), (170, 220, 50),
                                              (253, 231, 37)])


# =========================================================================== gráficas
def _style_plot(plot: pg.PlotItem, p: dict) -> None:
    plot.showGrid(x=True, y=True, alpha=0.15)
    plot.setMenuEnabled(False)
    plot.hideButtons()
    for axis in ("left", "bottom"):
        ax = plot.getAxis(axis)
        ax.setPen(pg.mkPen(p["border_strong"]))
        ax.setTextPen(pg.mkPen(p["muted"]))
    plot.getAxis("left").setWidth(64)


def _legend(plot: pg.PlotItem, p: dict) -> pg.LegendItem:
    leg = plot.addLegend(offset=(-10, 8))
    leg.setBrush(pg.mkBrush(p["card"] + "d0"))
    leg.setPen(pg.mkPen(p["border"]))
    leg.setLabelTextColor(p["text"])
    return leg


def draw_view(glw: pg.GraphicsLayoutWidget, res: ea.AnalysisResult, view: int, p: dict) -> None:
    """Dibuja una de las 7 vistas (la misma que graficarX.m) con un gráfico por canal."""
    glw.clear()
    glw.setBackground(p["card"])
    sps = res.params.sps
    first = None
    n_ch = len(res.channels)
    title_color = p["text"]
    for i, ch in enumerate(res.channels):
        last = i == n_ch - 1
        plot = glw.addPlot(row=i, col=0)
        _style_plot(plot, p)
        color = PLOT_COLORS[0]
        second = PLOT_COLORS[1]
        label = f"Canal {i}"
        time_view = view in (0, 4, 6)
        if view == 0:
            plot.plot(res.t, ch.v, pen=pg.mkPen(color, width=1))
            if i == 0:
                plot.setTitle("Señal bruta centrada", color=title_color)
            plot.setLabel("left", f"{label} [µV]")
        elif view in (1, 2, 3):
            if view == 1:
                f, db = ea.power_spectrum(ch.v, sps)
                plot.plot(f, db, pen=pg.mkPen(color, width=1))
            else:
                leg = _legend(plot, p)
                a, b = (ch.v, ch.v_notch) if view == 2 else (ch.v_notch, ch.v_band)
                names = ("Original", "Notch") if view == 2 else ("Solo notch", "Notch + paso banda")
                for x, pen_color, name in ((a, color, names[0]), (b, second, names[1])):
                    f, db = ea.power_spectrum(x, sps)
                    item = plot.plot(f, db, pen=pg.mkPen(pen_color, width=1))
                    leg.addItem(item, name)
            plot.setTitle(label, color=title_color)
            plot.setLabel("left", "Potencia [dB]")
            if last:
                plot.setLabel("bottom", "Frecuencia [Hz]")
        elif view == 4:
            leg = _legend(plot, p)
            leg.addItem(plot.plot(res.t, ch.v, pen=pg.mkPen(color, width=1)), "Bruta")
            leg.addItem(plot.plot(res.t, ch.v_band, pen=pg.mkPen(second, width=1)), "Filtrada")
            if i == 0:
                plot.setTitle("Señal bruta vs filtrada", color=title_color)
            plot.setLabel("left", f"{label} [µV]")
        elif view == 5:
            t, f, s = ea.spectrogram(ch.v_band, sps, res.params.t_window)
            img = pg.ImageItem(s.T)
            dt = t[1] - t[0] if len(t) > 1 else res.params.t_window
            df = f[1] - f[0] if len(f) > 1 else 1.0
            img.setRect(QRectF(float(t[0] - dt / 2), float(f[0] - df / 2), float(dt * len(t)), float(df * len(f))))
            hi = float(s.max())
            lo = max(float(np.percentile(s, 1)), hi - 120)
            img.setLevels((lo, hi))
            cmap = VIRIDIS
            img.setColorMap(cmap)
            plot.addItem(img)
            bar = pg.ColorBarItem(values=(lo, hi), colorMap=cmap, interactive=False, width=12,
                                  label="Potencia [dB]")
            bar.setImageItem(img, insert_in=plot)
            bar.getAxis("right").setTextPen(pg.mkPen(p["muted"]))
            plot.setTitle(f"{label} - espectrograma", color=title_color)
            plot.setLabel("left", "Frecuencia [Hz]")
            plot.setXRange(0, res.duration, padding=0)
            plot.setYRange(0, sps / 2, padding=0)
            if last:
                plot.setLabel("bottom", "Tiempo [s]")
        elif view == 6:
            plot.plot(res.t, ch.v_band, pen=pg.mkPen(p["subtle"], width=1))
            plot.plot(res.t, ch.rms, pen=pg.mkPen(color, width=2.4))
            line = pg.InfiniteLine(pos=ch.threshold, angle=0, movable=False,
                                   pen=pg.mkPen(p["error"], width=1.6, style=Qt.DashLine),
                                   label="Umbral", labelOpts={"position": 0.04, "color": p["error"],
                                                              "anchors": [(0, 1), (0, 1)]})
            plot.addItem(line)
            if i == 0:
                plot.setTitle("EMG filtrado y envolvente RMS", color=title_color)
            plot.setLabel("left", f"{label} [µV]")
        if time_view:
            region = pg.LinearRegionItem(values=(res.params.rest_start, min(res.params.rest_end, res.duration)),
                                         movable=False, brush=pg.mkBrush(p["ok"] + "22"),
                                         pen=pg.mkPen(p["ok"] + "88"))
            region.setZValue(-10)
            plot.addItem(region)
            if i == 0:
                text = pg.TextItem("reposo", color=p["ok"], anchor=(0, 0))
                text.setPos(res.params.rest_start, 0)
                plot.addItem(text, ignoreBounds=True)
                plot.sigYRangeChanged.connect(lambda _p, r, ti=text, x=res.params.rest_start: ti.setPos(x, r[1]))
            if last:
                plot.setLabel("bottom", "Tiempo [s]")
        if view != 5:
            for c in plot.listDataItems():
                c.setDownsampling(auto=True, method="peak")
                c.setClipToView(True)
        if time_view or view == 5:
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
        elif view in (1, 2, 3):
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            plot.setXRange(0, sps / 2, padding=0.01)


# =========================================================================== ventana
class EmgAnalyzerPanel(BasePage):
    title = "Analizador EMG"
    subtitle = "Analiza una grabación: red de 50 Hz, filtros, espectros, envolvente RMS y umbral de contracción"
    icon = "chart"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.table: ea.EmgTable | None = None
        self.result: ea.AnalysisResult | None = None
        self.inputs: dict[str, QWidget] = {}
        self._channel_checks: list[tuple[int, QCheckBox]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        scroll = QScrollArea()          # en una ventana baja, barra de desplazamiento en vez de aplastar los controles
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        root.addWidget(self._build_top())
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_params())
        body.addWidget(self._build_plots(), 1)
        root.addLayout(body, 1)

        self._load_params()
        ctx.analyze_emg_file.connect(self.open_file)
        self.on_theme_changed(ctx.theme)
        self._set_state("none")

    # ------------------------------------------------------------------ barra superior
    def _build_top(self) -> QWidget:
        card, lay = self.card()
        row = QHBoxLayout()
        row.setSpacing(8)
        load = self.button("Cargar CSV…", "folder", "", "Elegir una grabación EMG (.csv)")
        load.clicked.connect(self.choose_file)
        row.addWidget(load)
        self.analyze_btn = self.button("Analizar", "play", "primary", "Analizar con los parámetros de la izquierda")
        self.analyze_btn.clicked.connect(self.analyze)
        row.addWidget(self.analyze_btn)
        self.save_btn = self.button("Guardar…", "save", "", "Guardar figuras, resultados, señales y filtros")
        self.save_btn.clicked.connect(self.save)
        row.addWidget(self.save_btn)
        row.addSpacing(10)
        self.file_lbl = QLabel("Ningún archivo")
        self.file_lbl.setObjectName("muted")
        self.file_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.file_lbl, 1)
        self.state_lbl = QLabel()
        row.addWidget(self.state_lbl)
        lay.addLayout(row)
        self.warn_lbl = QLabel()
        self.warn_lbl.setWordWrap(True)
        self.warn_lbl.setVisible(False)
        lay.addWidget(self.warn_lbl)
        return card

    # ------------------------------------------------------------------ parámetros
    def _build_params(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        for title, specs in PARAM_GROUPS:
            card, cl = self.card(title)
            cl.setSpacing(6)
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(6)
            for r, (key, text, unit, lo, hi, dec, step, tip) in enumerate(specs):
                if unit is None:
                    w = QCheckBox(text)
                    w.setToolTip(tip)
                    w.toggled.connect(self._params_changed)
                    grid.addWidget(w, r, 0, 1, 2)
                else:
                    name = QLabel(text)
                    name.setToolTip(tip)
                    w = QDoubleSpinBox()
                    w.setRange(lo, hi)
                    w.setDecimals(dec)
                    w.setSingleStep(step)
                    if unit:
                        w.setSuffix(f" {unit}")
                    w.setToolTip(tip)
                    w.setKeyboardTracking(False)
                    w.valueChanged.connect(self._params_changed)
                    w.setMinimumWidth(92)
                    grid.addWidget(name, r, 0)
                    grid.addWidget(w, r, 1)
                self.inputs[key] = w
            cl.addLayout(grid)
            lay.addWidget(card)
        self.inputs["notch_on"].toggled.connect(self._update_enabled)
        self.inputs["band_on"].toggled.connect(self._update_enabled)

        card, cl = self.card("Canales del CSV")
        self.channels_box = QVBoxLayout()
        self.channels_box.setSpacing(4)
        cl.addLayout(self.channels_box)
        self.rate_hint = QLabel()
        self.rate_hint.setObjectName("muted")
        self.rate_hint.setWordWrap(True)
        self.rate_hint.setVisible(False)
        cl.addWidget(self.rate_hint)
        lay.addWidget(card)
        reset = self.button("Valores por defecto", "rotate", "ghost", "Los mismos que la app de MATLAB")
        reset.clicked.connect(lambda: self.set_params(ea.AnalysisParams()))
        lay.addWidget(reset, 0, Qt.AlignLeft)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(300)
        return scroll

    def params(self) -> ea.AnalysisParams:
        values = {}
        for key, w in self.inputs.items():
            values[key] = w.isChecked() if isinstance(w, QCheckBox) else w.value()
        values["bits"] = int(round(values["bits"]))
        return ea.AnalysisParams.from_dict(values)

    def set_params(self, p: ea.AnalysisParams) -> None:
        for key, value in p.to_dict().items():
            w = self.inputs.get(key)
            if w is None:
                continue
            w.blockSignals(True)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(value))
            else:
                w.setValue(float(value))
            w.blockSignals(False)
        self._update_enabled()
        self._params_changed()

    def _update_enabled(self) -> None:
        notch, band = self.inputs["notch_on"].isChecked(), self.inputs["band_on"].isChecked()
        for key in ("f0", "q"):
            self.inputs[key].setEnabled(notch)
        for key in ("f_low", "f_high"):
            self.inputs[key].setEnabled(band)

    def _params_changed(self, *_args) -> None:
        self.settings.setValue(f"{SETTINGS}/parametros", json.dumps(self.params().to_dict()))
        self._update_file_label()
        if self.result is not None:
            self._set_state("stale")

    def _load_params(self) -> None:
        try:
            data = json.loads(self.settings.value(f"{SETTINGS}/parametros", "") or "{}")
        except (TypeError, ValueError):
            data = {}
        self.set_params(ea.AnalysisParams.from_dict(data))

    # ------------------------------------------------------------------ gráficas y resultados
    def _build_plots(self) -> QWidget:
        self.view_combo = QComboBox()
        self.view_combo.addItems(VIEWS)
        self.view_combo.setCurrentIndex(int(self.settings.value(f"{SETTINGS}/vista", 0)) % len(VIEWS))
        self.view_combo.currentIndexChanged.connect(self._view_changed)
        card, lay = self.card("Gráfica", [self.view_combo])
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setMinimumHeight(240)
        lay.addWidget(self.glw, 1)
        self.empty_lbl = QLabel("Carga una grabación (.csv) del Visor EMG o del logger serie y pulsa Analizar.")
        self.empty_lbl.setObjectName("muted")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        lay.addWidget(self.empty_lbl)
        caption = QLabel("RESULTADOS")
        caption.setObjectName("caption")
        lay.addWidget(caption)
        self.results = QTableWidget(len(RESULT_ROWS), 2)
        self.results.setVerticalHeaderLabels([r[0] for r in RESULT_ROWS])
        self.results.setHorizontalHeaderLabels(["Canal 0", "Canal 1"])
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setSelectionMode(QTableWidget.NoSelection)
        self.results.setFocusPolicy(Qt.NoFocus)
        self.results.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.results)
        self._fit_table()
        return card

    def _fit_table(self) -> None:
        """Alto justo para las 4 filas (sin barra de desplazamiento)."""
        t = self.results
        t.resizeRowsToContents()
        rows = sum(t.rowHeight(r) for r in range(t.rowCount()))
        t.setFixedHeight(rows + t.horizontalHeader().sizeHint().height() + 2 * t.frameWidth() + 2)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_table()

    def _view_changed(self, i: int) -> None:
        self.settings.setValue(f"{SETTINGS}/vista", i)
        self._draw()

    def _draw(self) -> None:
        has = self.result is not None
        self.glw.setVisible(has)
        self.empty_lbl.setVisible(not has)
        if has:
            draw_view(self.glw, self.result, self.view_combo.currentIndex(), PALETTES[self.ctx.theme])

    def _fill_results(self) -> None:
        res = self.result
        chs = res.channels if res is not None else []
        n = max(len(chs), 1)
        self.results.setColumnCount(n)
        headers = []
        for i in range(n):
            headers.append(f"Canal {i}" + (f"  ({chs[i].name})" if i < len(chs) else ""))
        self.results.setHorizontalHeaderLabels(headers)
        for r, (_label, attr) in enumerate(RESULT_ROWS):
            for c in range(n):
                text = f"{getattr(chs[c], attr):.1f}" if c < len(chs) else "—"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.results.setItem(r, c, item)
        self._fit_table()

    # ------------------------------------------------------------------ archivo
    def choose_file(self) -> None:
        start = self.settings.value(f"{SETTINGS}/carpeta_csv", "") or str(documents_dir("Grabaciones EMG"))
        path, _ = QFileDialog.getOpenFileName(self, "Elige la muestra EMG", start, "CSV (*.csv);;Todos (*.*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> bool:
        """Carga un CSV y lo analiza (lo usa también el botón Analizar del Visor EMG)."""
        try:
            table = ea.load_csv(path)
        except (OSError, ea.AnalysisError, UnicodeError) as error:
            QMessageBox.warning(self, "Analizador EMG", f"No se pudo leer {Path(path).name}:\n{error}")
            return False
        if not table.channel_cols:
            QMessageBox.warning(self, "Analizador EMG", f"{Path(path).name} no tiene columnas de canales EMG.")
            return False
        self.table = table
        self.result = None
        self.settings.setValue(f"{SETTINGS}/carpeta_csv", str(Path(path).parent))
        self._build_channel_checks()
        self._update_file_label()
        self._set_state("loaded")
        self._fill_results()
        self._draw()
        self.analyze()
        return True

    def _build_channel_checks(self) -> None:
        while self.channels_box.count():
            item = self.channels_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._channel_checks = []
        t = self.table
        if t is None:
            return
        candidates = [i for i in range(len(t.header)) if i != t.time_col and np.isfinite(t.data[:, i]).mean() > 0.95]
        for i in candidates:
            chk = QCheckBox(t.header[i])
            chk.setChecked(i in t.channel_cols[:MAX_CHANNELS])
            chk.toggled.connect(self._params_changed)
            self.channels_box.addWidget(chk)
            self._channel_checks.append((i, chk))
        if t.time_col is not None:
            note = QLabel(f"Tiempo: {t.header[t.time_col]} (no se analiza)")
            note.setObjectName("muted")
            self.channels_box.addWidget(note)

    def _selected_channels(self) -> list[int]:
        return [i for i, chk in self._channel_checks if chk.isChecked()][:MAX_CHANNELS]

    def _update_file_label(self) -> None:
        t = self.table
        if t is None:
            self.file_lbl.setText("Ningún archivo")
            self.rate_hint.setVisible(False)
            return
        sps = self.inputs["sps"].value()
        self.file_lbl.setText(f"{t.path.name} · {t.rows} muestras · {t.rows / sps:.1f} s")
        self.file_lbl.setToolTip(str(t.path))
        rate = t.estimated_rate()
        off = rate is not None and abs(rate - sps) > 0.05 * sps
        self.rate_hint.setVisible(off)
        if off:
            self.rate_hint.setText(f"La columna de tiempo indica ~{rate:.0f} muestras/s y Samples/s es {sps:g}: "
                                   f"revisa la frecuencia del ADC.")

    def _set_state(self, state: str) -> None:
        p = PALETTES[self.ctx.theme]
        text, color = {
            "none": ("", p["subtle"]),
            "loaded": ("Sin analizar", p["subtle"]),
            "ok": ("✓ Analizado", p["ok"]),
            "stale": ("Parámetros cambiados: pulsa Analizar", p["warn"]),
            "error": ("✗ Error en el análisis", p["error"]),
        }[state]
        self.state_lbl.setText(text)
        self.state_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.save_btn.setEnabled(self.result is not None)
        self.analyze_btn.setEnabled(self.table is not None)

    # ------------------------------------------------------------------ analizar y guardar
    def analyze(self) -> bool:
        if self.table is None:
            QMessageBox.information(self, "Sin datos", "Primero carga un archivo CSV.")
            return False
        cols = self._selected_channels()
        if not cols:
            QMessageBox.information(self, "Analizador EMG", "Marca al menos un canal del CSV.")
            return False
        data = self.table.data[:, cols]
        ok_rows = np.isfinite(data).all(axis=1)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.result = ea.analyze(data[ok_rows], self.params(), [self.table.header[i] for i in cols])
        except ea.AnalysisError as error:
            self.result = None
            QApplication.restoreOverrideCursor()
            self._set_state("error")
            self.warn_lbl.setVisible(False)
            self._fill_results()
            self._draw()
            QMessageBox.warning(self, "Error en el análisis", str(error))
            return False
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        self._set_state("ok")
        warnings = list(self.result.warnings)
        if (~ok_rows).any():
            warnings.append(f"Se han saltado {int((~ok_rows).sum())} filas con celdas vacías o no numéricas.")
        self._show_warnings(warnings)
        self._fill_results()
        self._draw()
        return True

    def _show_warnings(self, warnings: list[str]) -> None:
        p = PALETTES[self.ctx.theme]
        self.warn_lbl.setVisible(bool(warnings))
        self.warn_lbl.setText("⚠  " + "\n\n⚠  ".join(w.replace("\n\n", " ") for w in warnings))
        self.warn_lbl.setStyleSheet(f"color: {p['warn']};")

    def save(self) -> None:
        if self.result is None or self.table is None:
            QMessageBox.information(self, "Nada que guardar", "Primero analiza una muestra.")
            return
        start = (self.settings.value(f"{SETTINGS}/carpeta_resultados", "")
                 or str(documents_dir("Análisis EMG")))
        folder = QFileDialog.getExistingDirectory(self, "Elige dónde guardar los resultados", start)
        if not folder:
            return
        self.settings.setValue(f"{SETTINGS}/carpeta_resultados", folder)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dest = ea.save_analysis(self.result, self.table.path.name, folder)
            self.export_figures(dest)
        except OSError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error al guardar", str(error))
            return
        QApplication.restoreOverrideCursor()
        self.ctx.notify(f"Análisis guardado en {dest}", toast=True)
        box = QMessageBox(QMessageBox.Information, "Análisis guardado", f"Guardado en:\n{dest}", parent=self)
        open_btn = box.addButton("Abrir carpeta", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest)))

    def export_figures(self, dest: Path) -> list[Path]:
        """Las 7 vistas como figura_1…7.png, en el orden del desplegable (el de crearFiguras.m)."""
        w = pg.GraphicsLayoutWidget()
        w.setAttribute(Qt.WA_DontShowOnScreen, True)
        w.resize(*EXPORT_SIZE)
        w.show()
        paths = []
        try:
            palette = PALETTES[self.ctx.theme]       # con el tema de la app (las de MATLAB del equipo son oscuras)
            for k in range(len(VIEWS)):
                draw_view(w, self.result, k, palette)
                w.ci.setContentsMargins(12, 12, 12, 12)
                QApplication.processEvents()
                path = Path(dest) / f"figura_{k + 1}.png"
                if not w.grab().save(str(path)):
                    raise OSError(f"No se pudo guardar {path.name}")
                paths.append(path)
        finally:
            w.close()
            w.deleteLater()
        return paths

    # ------------------------------------------------------------------ tema
    def on_theme_changed(self, theme: str) -> None:
        self.glw.setBackground(PALETTES[theme]["card"])
        self.warn_lbl.setStyleSheet(f"color: {PALETTES[theme]['warn']};")
        if self.result is not None:
            self._draw()
        state = self.state_lbl.text()
        if state:
            key = {"Sin analizar": "loaded", "✓ Analizado": "ok", "✗ Error en el análisis": "error"}.get(
                state, "stale")
            self._set_state(key)
