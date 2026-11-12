"""Ventana «Visor EMG»: la señal de los electrodos en directo, el diagnóstico del enlace y la grabación en CSV.

Es el Visor EMG del equipo (firmware/EMG/tools/Visor EMG/visor_emg.py, en Tkinter) dentro de la app:

┌ Fuente ─────────────────────────────────────────────────────────────────────────┐
│ Receptor USB [COM8 – … ▾] [↻] [Conectar]   ADC [500 Hz]          ● COM8 · recibiendo │
└───────────────────────────────────────────────────────────────────────────────────┘
┌ Señal ─────────── [5 s ▾] [Bruta|Filtrada] [Escala auto] [Pausa] ┐ ┌ Diagnóstico ───┐
│ CH1 ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿│ │ Paquetes/s 100 │
│ CH2 ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿│ │ Perdidos 0 …   │
└───────────────────────────────────────────────────────────────────┘ └────────────────┘
┌ Grabación ───────────────────────────────────────────────────────────────────────┐
│ Carpeta [Documentos\\BIOMEC Control\\Grabaciones EMG] [📁] [Abrir]  Nombre [emg]  Parar a los [—] │
│ Columnas: tiempo, data0, data1                                  [Columnas ▾]        │
│ [●  EMPEZAR A GRABAR]                                                                │
│ Guardado: emg_20261111_131500.csv — 5000 muestras (10.0 s) — sin pérdidas  [Analizar] │
└───────────────────────────────────────────────────────────────────────────────────┘

La señal puede venir del receptor EMG del equipo por USB (core/emg_receiver.py) o de la conexión de la app
(líneas EMG del puente con @EMG 1, o la simulación): las dos llegan como Message EMG por ctx.message.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections import deque
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .. import APP_NAME, ORG_NAME
from ..core.emg import Preprocessor
from ..core.emg_receiver import CsvRecorder, StreamStats, column_ids, simple_name
from ..core.protocol import MessageKind
from ..core.serial_link import available_ports
from ..paths import documents_dir
from ..ui.theme import PALETTES, PLOT_COLORS
from ..ui.widgets import Segmented
from .base import BasePage

BUFFER_S = 31                       # segundos de señal en memoria para la gráfica
WINDOWS_S = (1, 2, 5, 10, 20, 30)   # opciones de la ventana de tiempo
SOURCE_SILENCE_S = 1.0              # si dos fuentes mandan EMG a la vez, se sigue la primera
NO_DATA_S = 1.0                     # sin paquetes durante este tiempo = "sin datos"
STATUS_FRESH_S = 3.0                # el estado de la C6 llega cada segundo
SETTINGS = "visor_emg"


def clean_name(name: str) -> str:
    name = re.sub(r"[^\w\-]", "", name.strip().replace(" ", "_"))
    return name or "emg"


class PortCombo(QComboBox):
    """Lista de puertos que se vuelve a buscar cada vez que se abre (la C6 se enchufa con la app abierta)."""

    def __init__(self, before_popup):
        super().__init__()
        self._before_popup = before_popup

    def showPopup(self) -> None:
        self._before_popup()
        super().showPopup()


class LaneAxis(pg.AxisItem):
    """Eje de tiempo con el presente a la derecha: «ahora», «-1 s», «-2 s»…"""

    def tickStrings(self, values, scale, spacing):
        return ["ahora" if abs(v) < 1e-9 else f"{v:g} s" for v in values]


class EmgViewerPanel(BasePage):
    title = "Visor EMG"
    subtitle = "Señal de los electrodos en directo, diagnóstico del enlace y grabación en CSV"
    icon = "waveform"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.receiver = ctx.emg_receiver
        self.stats = StreamStats()
        self.fs = 500.0
        self.channels = 0
        self.batch = 0
        self.source = ""
        self.recorder: CsvRecorder | None = None
        self.paused = False
        self.auto_scale = True
        self.filtered = False
        self._buf = np.zeros((0, 0))
        self._fbuf = np.zeros((0, 0))
        self._written = 0
        self._pre: Preprocessor | None = None
        self._last_frame = 0.0
        self._last_seq: int | None = None
        self._hist: deque[tuple[float, int]] = deque()
        self._pps = 0.0
        self._scales: list[list[float] | None] = []
        self._dirty = False
        self._ticks = 0
        self._rec_note = ""          # último aviso de la grabación («Guardado: …»), se queda a la vista
        self._last_saved: Path | None = None
        self._col_widgets: dict[str, tuple[QCheckBox, QLineEdit, QLabel]] = {}
        self._cfg_cols = self._load_json("columnas", {})
        self._simple_mode = self.settings.value(f"{SETTINGS}/modo_simple", "true") in ("true", True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        scroll = QScrollArea()          # en una ventana baja, barra de desplazamiento en vez de aplastar los controles
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        root.addWidget(self._build_source_card())
        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addWidget(self._build_signal_card(), 1)
        middle.addWidget(self._build_diag_card())
        root.addLayout(middle, 1)
        root.addWidget(self._build_record_card())

        self.receiver.connection_changed.connect(lambda *_: self._update_source())
        ctx.replay_changed.connect(lambda _r: self._reset_stream("", 0))
        self._timer = QTimer(self)
        self._timer.setInterval(40)            # ~25 imágenes por segundo, como el visor del equipo
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.refresh_ports(self.settings.value(f"{SETTINGS}/puerto", ""))
        self._build_columns()
        self._update_source()
        self.on_theme_changed(ctx.theme)

    # ================================================================ fuente
    def _build_source_card(self) -> QWidget:
        self.source_lbl = QLabel()
        self.source_lbl.setObjectName("muted")
        card, lay = self.card("Fuente", [self.source_lbl])
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel("Receptor USB")
        lbl.setToolTip("ESP32-C6 del equipo que recibe el sensor por ESP-NOW y lo manda al PC (marcos AA 55)")
        row.addWidget(lbl)
        self.port_combo = PortCombo(lambda: self.refresh_ports(self._selected_port()))
        self.port_combo.setMinimumWidth(140)
        self.port_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self.port_combo, 1)
        self.refresh_btn = self.button("", "refresh", "ghost", "Volver a buscar puertos")
        self.refresh_btn.clicked.connect(lambda: self.refresh_ports(self._selected_port()))
        row.addWidget(self.refresh_btn)
        self.connect_btn = self.button("Conectar", "plug", "primary",
                                       "Abre el puerto del receptor EMG del equipo (no el del puente de la mano)")
        self.connect_btn.clicked.connect(self.toggle_receiver)
        row.addWidget(self.connect_btn)
        row.addSpacing(10)
        fs_lbl = QLabel("ADC")
        fs_lbl.setToolTip("Muestras por segundo del ADS1198 (ADS119X_DRATE_500SPS en el firmware del sensor).\n"
                          "Da el tiempo de cada muestra en la gráfica y en el CSV.")
        row.addWidget(fs_lbl)
        self.fs_spin = QSpinBox()
        self.fs_spin.setRange(50, 8000)
        self.fs_spin.setSuffix(" Hz")
        self.fs_spin.setValue(int(float(self.settings.value(f"{SETTINGS}/fs", 500))))
        self.fs_spin.setToolTip(fs_lbl.toolTip())
        self.fs_spin.valueChanged.connect(self._fs_changed)
        self.fs = float(self.fs_spin.value())
        row.addWidget(self.fs_spin)
        lay.addLayout(row)
        self.source_hint = QLabel(
            "Conecta aquí el receptor EMG del equipo, o usa la conexión de la app: el puente (con o sin placa "
            "EMG) o el propio receptor conectados allí también traen la señal, igual que la simulación. "
            "Lo que llegue por cualquiera de las dos se ve aquí.")
        self.source_hint.setObjectName("muted")
        self.source_hint.setWordWrap(True)
        lay.addWidget(self.source_hint)
        return card

    def _selected_port(self) -> str:
        return self.port_combo.currentData() or ""

    def refresh_ports(self, preferred: str = "") -> None:
        ports = sorted(available_ports())
        app_port = self.ctx.link.port_name if self.ctx.connected else ""
        self.port_combo.clear()
        for dev, desc in ports:
            text = f"{dev} – {desc}" + ("   (en uso: conexión de la app)" if dev == app_port else "")
            self.port_combo.addItem(text, dev)
        if not ports:
            self.port_combo.addItem("No hay puertos: conecta el receptor y pulsa ↻", "")
            return
        devices = [d for d, _ in ports]
        if preferred in devices:
            choice = preferred
        else:
            free = [d for d in devices if d != app_port]
            choice = free[0] if free else devices[0]
        self.port_combo.setCurrentIndex(devices.index(choice))

    def toggle_receiver(self) -> None:
        if self.receiver.connected:
            self.receiver.disconnect_port()
            return
        port = self._selected_port()
        if not port:                       # se enchufó después de abrir la app: se busca otra vez
            self.refresh_ports()
            port = self._selected_port()
        if not port:
            self.ctx.notify("Visor EMG: no hay ningún puerto. Enchufa el receptor por USB y vuelve a pulsar "
                            "Conectar.", error=True)
            return
        if self.ctx.connected and port == self.ctx.link.port_name:
            self.ctx.notify(f"{port} ya está abierto en la conexión de la app: el EMG que mande ya llega a esta "
                            f"ventana, no hace falta conectarlo aquí.")
            return
        self.settings.setValue(f"{SETTINGS}/puerto", port)
        if self.receiver.connect_port(port):
            self.ctx.notify(f"Receptor EMG conectado en {port}.")

    def _update_source(self) -> None:
        on = self.receiver.connected
        self.connect_btn.setText("  Desconectar" if on else "  Conectar")
        self.connect_btn.setObjectName("ghost" if on else "primary")
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
        self.port_combo.setEnabled(not on)
        self.refresh_btn.setEnabled(not on)

    def _fs_changed(self, value: int) -> None:
        if self.recorder is not None:          # el tiempo del CSV depende de la frecuencia: no se cambia grabando
            self.fs_spin.blockSignals(True)
            self.fs_spin.setValue(int(self.fs))
            self.fs_spin.blockSignals(False)
            self.ctx.notify("Para la grabación antes de cambiar la frecuencia del ADC.", error=True)
            return
        self.fs = float(value)
        self.settings.setValue(f"{SETTINGS}/fs", value)
        self._reset_stream(self.source, self.channels)

    # ================================================================ señal
    def _build_signal_card(self) -> QWidget:
        self.window_combo = QComboBox()
        for s in WINDOWS_S:
            self.window_combo.addItem(f"{s} s", s)
        saved = int(float(self.settings.value(f"{SETTINGS}/ventana", 5)))
        self.window_combo.setCurrentIndex(WINDOWS_S.index(saved) if saved in WINDOWS_S else 2)
        self.window_combo.setToolTip("Segundos de señal en la gráfica (el borde derecho es «ahora»)")
        self.window_combo.currentIndexChanged.connect(self._window_changed)
        self.mode_seg = Segmented(["Bruta", "Filtrada"], stretch=False, tooltips=[
            "Cuentas del ADC tal cual llegan",
            "Paso alto 20 Hz + notch 50 Hz, causal (lo mismo que ve Entrenamiento)"])
        self.mode_seg.set_current(0)
        self.mode_seg.idClicked.connect(self._mode_changed)
        self.auto_chk = QCheckBox("Escala auto")
        self.auto_chk.setChecked(True)
        self.auto_chk.setToolTip("Crece al instante y encoge despacio, para que la señal no «baile».\n"
                                 "Desactivada, la escala se queda fija donde está.")
        self.auto_chk.toggled.connect(self._auto_changed)
        self.pause_btn = self.button("", "pause", "ghost", "Congela la gráfica (no detiene la grabación)")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._pause_changed)
        card, lay = self.card("Señal", [self.window_combo, self.mode_seg, self.auto_chk, self.pause_btn])
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setMinimumHeight(160)
        self.glw.ci.layout.setSpacing(2)
        lay.addWidget(self.glw, 1)
        self.wait_lbl = QLabel("Esperando datos del sensor…")
        self.wait_lbl.setObjectName("muted")
        self.wait_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.wait_lbl)
        self.plots: list[pg.PlotItem] = []
        self.curves: list = []
        return card

    def _window_s(self) -> float:
        return float(self.window_combo.currentData() or 5)

    def _window_changed(self, _i: int) -> None:
        self.settings.setValue(f"{SETTINGS}/ventana", int(self._window_s()))
        for plot in self.plots:
            plot.setXRange(-self._window_s(), 0, padding=0)
        self._dirty = True

    def _mode_changed(self, i: int) -> None:
        self.filtered = i == 1
        self._scales = [None] * self.channels
        self._dirty = True

    def _auto_changed(self, on: bool) -> None:
        self.auto_scale = on
        for plot in self.plots:
            plot.setMouseEnabled(x=False, y=not on)
        self._dirty = True

    def _pause_changed(self, on: bool) -> None:
        self.paused = on
        self.pause_btn.setToolTip("Reanudar la gráfica" if on else "Congela la gráfica (no detiene la grabación)")
        self._dirty = True

    def _build_plots(self) -> None:
        self.glw.clear()
        self.plots, self.curves = [], []
        p = PALETTES[self.ctx.theme]
        first = None
        for ch in range(self.channels):
            last = ch == self.channels - 1
            plot = self.glw.addPlot(row=ch, col=0, axisItems={"bottom": LaneAxis(orientation="bottom")})
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.setMouseEnabled(x=False, y=not self.auto_scale)
            plot.showGrid(x=True, y=False, alpha=0.12)
            plot.setXRange(-self._window_s(), 0, padding=0)
            color = PLOT_COLORS[ch % len(PLOT_COLORS)]
            plot.setLabel("left", f"<b>CH{ch + 1}</b>", color=color)
            plot.getAxis("left").setWidth(62)
            if not last:
                plot.getAxis("bottom").setStyle(showValues=False)
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            now = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=pg.mkPen(p["accent"], width=2))
            plot.addItem(now, ignoreBounds=True)
            curve = plot.plot(pen=pg.mkPen(color, width=1))
            curve.setDownsampling(auto=True, method="peak")    # máximos y mínimos de cada píxel: no se pierden picos
            curve.setClipToView(True)
            self.plots.append(plot)
            self.curves.append(curve)
        self._scales = [None] * self.channels
        self.on_theme_changed(self.ctx.theme)

    # ================================================================ diagnóstico
    def _build_diag_card(self) -> QWidget:
        card, lay = self.card("Diagnóstico")
        card.setFixedWidth(292)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.diag: dict[str, QLabel] = {}
        rows = [("formato", "Canales × muestras", "Canales del sensor y muestras por paquete"),
                ("pps", "Paquetes/s", "Paquetes que llegan por segundo (100/s con 5 muestras a 500 Hz)"),
                ("paquetes", "Paquetes recibidos", ""),
                ("perdidos", "Paquetes perdidos", "Saltos en el número de paquete (seq)"),
                ("fails", "Envíos fallidos (sensor)", "Envíos ESP-NOW que el sensor no pudo entregar"),
                ("reinicios", "Reinicios del sensor", "Veces que el número de paquete volvió a empezar"),
                ("corruptos", "Marcos corruptos", "Marcos USB con la comprobación (XOR) mal o un formato raro"),
                (None, None, None),
                ("mac", "MAC receptor", "La que debe ir en rxMac del firmware del sensor"),
                ("c6_inv", "Inválidos (C6)", "Paquetes ESP-NOW con un tamaño que no cuadra"),
                ("c6_cola", "Cola llena (C6)", "Paquetes que llegaron con la cola de la C6 llena"),
                ("c6_usb", "Descartados USB (C6)", "Marcos que la C6 no pudo mandar al PC (nadie leyendo)")]
        for i, (key, text, tip) in enumerate(rows):
            if key is None:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setObjectName("headerSep")
                grid.addWidget(sep, i, 0, 1, 2)
                continue
            name = QLabel(text)
            name.setObjectName("muted")
            if tip:
                name.setToolTip(tip)
            value = QLabel("—")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(name, i, 0)
            grid.addWidget(value, i, 1)
            self.diag[key] = value
        lay.addLayout(grid)
        lay.addStretch(1)
        return card

    def _frame_stream(self):
        """Los marcos AA 55 de dónde sale la señal: el puerto de esta ventana o la conexión de la app."""
        if self.receiver.connected or self.source == "receptor":
            return self.receiver.stream
        if self.source == "conexion" or (self.ctx.connected and self.ctx.link.frames.frames):
            return self.ctx.link.frames
        return None

    def _set_diag(self, key: str, text: str, alert: bool = False, strong: bool = False) -> None:
        p = PALETTES[self.ctx.theme]
        label = self.diag[key]
        label.setText(text)
        color = p["warn"] if alert else (p["accent_text"] if strong else p["text"])
        label.setStyleSheet(f"color: {color}; font-weight: {700 if alert or strong else 400};")

    def _update_diag(self) -> None:
        st = self.stats
        live = self.channels > 0
        self._set_diag("formato", f"{self.channels} × {self.batch}" if live else "—")
        self._set_diag("pps", f"{self._pps:.1f}" if st.packets else "—", strong=True)
        self._set_diag("paquetes", f"{st.packets}")
        self._set_diag("perdidos", f"{st.lost} ({st.lost_pct:.2f} %)" if st.lost else "0", st.lost > 0)
        self._set_diag("fails", "—" if st.send_fails is None else f"{st.send_fails}", bool(st.send_fails))
        self._set_diag("reinicios", f"{st.restarts}", st.restarts > 0)
        stream = self._frame_stream()
        if stream is not None:
            with stream.lock:
                corrupt, status, status_t = stream.parser.corrupt, stream.status.current, stream.status.time
            self._set_diag("corruptos", f"{corrupt}", corrupt > 0)
        else:
            status, status_t = None, 0.0
            self._set_diag("corruptos", "—")
        if status is not None and time.monotonic() - status_t < STATUS_FRESH_S:
            self._set_diag("mac", status.mac)
            self._set_diag("c6_inv", f"{status.invalid}", status.invalid > 0)
            self._set_diag("c6_cola", f"{status.queue_full}", status.queue_full > 0)
            self._set_diag("c6_usb", f"{status.usb_dropped}", status.usb_dropped > 0)
        else:
            for key in ("mac", "c6_inv", "c6_cola", "c6_usb"):
                self._set_diag(key, "—")

    # ================================================================ grabación
    def _build_record_card(self) -> QWidget:
        card, lay = self.card("Grabación")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Carpeta"), 0, 0)
        self.folder_edit = QLineEdit(self.settings.value(f"{SETTINGS}/carpeta", "")
                                     or str(documents_dir("Grabaciones EMG", create=False)))
        self.folder_edit.setMinimumWidth(140)
        grid.addWidget(self.folder_edit, 0, 1, 1, 3)
        pick = self.button("", "folder", "ghost", "Elegir la carpeta")
        pick.clicked.connect(self._pick_folder)
        grid.addWidget(pick, 0, 4)
        open_btn = self.button("Abrir", None, "ghost", "Abrir la carpeta en el explorador")
        open_btn.clicked.connect(self._open_folder)
        grid.addWidget(open_btn, 0, 5)
        grid.addWidget(QLabel("Nombre"), 1, 0)
        self.name_edit = QLineEdit(self.settings.value(f"{SETTINGS}/nombre", "emg"))
        self.name_edit.setToolTip("El archivo se llamará <nombre>_<fecha>_<hora>.csv")
        grid.addWidget(self.name_edit, 1, 1)
        stop_lbl = QLabel("Parar a los")
        grid.addWidget(stop_lbl, 1, 2, Qt.AlignRight)
        self.limit_spin = QDoubleSpinBox()
        self.limit_spin.setRange(0, 36000)
        self.limit_spin.setDecimals(1)
        self.limit_spin.setSuffix(" s")
        self.limit_spin.setSpecialValueText("sin límite")
        self.limit_spin.setToolTip("Segundos de señal tras los que la grabación se para sola (0 = sin límite)")
        self.limit_spin.setValue(float(self.settings.value(f"{SETTINGS}/limite", 0)))
        grid.addWidget(self.limit_spin, 1, 3, 1, 3)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        cols_row = QHBoxLayout()
        cols_row.setSpacing(8)
        cap = QLabel("Columnas del CSV:")
        cols_row.addWidget(cap)
        self.cols_summary = QLabel()
        self.cols_summary.setObjectName("muted")
        cols_row.addWidget(self.cols_summary, 1)
        self.cols_btn = self.button("Columnas", "chevron_down", "ghost",
                                    "Elegir qué columnas se guardan y con qué nombre")
        self.cols_btn.setCheckable(True)
        self.cols_btn.toggled.connect(self._toggle_columns)
        cols_row.addWidget(self.cols_btn)
        lay.addLayout(cols_row)

        self.cols_box = QWidget()
        box = QVBoxLayout(self.cols_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        presets = QHBoxLayout()
        hint = QLabel("Marca las que quieres guardar · el recuadro es el nombre en la cabecera · a la derecha, el "
                      "último valor recibido")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        presets.addWidget(hint, 1)
        self.simple_btn = QPushButton("Solo tiempo + canales")
        self.simple_btn.setToolTip("tiempo, data0, data1…: el formato que lee el Analizador EMG")
        self.simple_btn.clicked.connect(self.columns_simple)
        presets.addWidget(self.simple_btn)
        self.all_btn = QPushButton("Todas (nombres originales)")
        self.all_btn.setToolTip("t_s, seq, idx, ch1, ch2…")
        self.all_btn.clicked.connect(self.columns_all)
        presets.addWidget(self.all_btn)
        box.addLayout(presets)
        self.cols_grid = QGridLayout()
        self.cols_grid.setHorizontalSpacing(14)
        self.cols_grid.setVerticalSpacing(4)
        box.addLayout(self.cols_grid)
        self.cols_box.setVisible(False)
        lay.addWidget(self.cols_box)

        self.rec_btn = QPushButton("●   EMPEZAR A GRABAR")
        self.rec_btn.setObjectName("primary")
        self.rec_btn.setMinimumHeight(40)
        self.rec_btn.setCursor(Qt.PointingHandCursor)
        self.rec_btn.clicked.connect(self.toggle_recording)
        lay.addWidget(self.rec_btn)
        status_row = QHBoxLayout()
        self.rec_status = QLabel()
        self.rec_status.setObjectName("muted")
        self.rec_status.setWordWrap(True)
        status_row.addWidget(self.rec_status, 1)
        self.analyze_btn = self.button("Analizar", "chart", "", "Abrir esta grabación en el Analizador EMG")
        self.analyze_btn.clicked.connect(self._analyze_last)
        self.analyze_btn.setVisible(False)
        status_row.addWidget(self.analyze_btn)
        lay.addLayout(status_row)
        return card

    def _toggle_columns(self, on: bool) -> None:
        self.cols_box.setVisible(on)
        for i, (btn, name, color) in enumerate(self._icon_buttons):   # flecha arriba / abajo
            if btn is self.cols_btn:
                self._icon_buttons[i] = (btn, "chevron_up" if on else "chevron_down", color)
        self._paint_icons()

    def _build_columns(self) -> None:
        """Una casilla por columna disponible (cambia con el número de canales)."""
        while self.cols_grid.count():
            item = self.cols_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._col_widgets.clear()
        ids = column_ids(self.channels)
        per_row = 3
        for i, cid in enumerate(ids):
            saved = self._cfg_cols.get(cid, {})
            name = saved.get("nombre") or (simple_name(cid) if self._simple_mode else cid)
            on = saved.get("on", not (self._simple_mode and cid in ("seq", "idx")))
            chk = QCheckBox(cid)
            chk.setChecked(bool(on))
            chk.setMinimumWidth(52)
            edit = QLineEdit(name)
            edit.setMaximumWidth(110)
            value = QLabel("—")
            value.setObjectName("muted")
            value.setMinimumWidth(56)
            chk.toggled.connect(self._columns_changed)
            edit.textChanged.connect(self._columns_changed)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(chk)
            cell.addWidget(edit)
            cell.addWidget(value)
            holder = QWidget()
            holder.setLayout(cell)
            self.cols_grid.addWidget(holder, i // per_row, i % per_row)
            self._col_widgets[cid] = (chk, edit, value)
        if self.channels == 0:
            note = QLabel("(los canales aparecerán al llegar datos del sensor)")
            note.setObjectName("muted")
            self.cols_grid.addWidget(note, 1, 1, 1, 2)
        self._lock_columns(self.recorder is not None)
        self._columns_changed()

    def _columns_changed(self) -> None:
        cols = self.selected_columns()
        self.cols_summary.setText(", ".join(n for _c, n in cols) if cols else "ninguna (marca alguna)")
        for cid, (chk, edit, _v) in self._col_widgets.items():
            self._cfg_cols[cid] = {"on": chk.isChecked(), "nombre": edit.text()}

    def selected_columns(self) -> list[tuple[str, str]]:
        return [(cid, edit.text().strip() or cid) for cid, (chk, edit, _v) in self._col_widgets.items()
                if chk.isChecked()]

    def columns_simple(self) -> None:
        """Formato del Analizador EMG: tiempo, data0, data1…"""
        self._simple_mode = True
        for cid, (chk, edit, _v) in self._col_widgets.items():
            chk.setChecked(cid not in ("seq", "idx"))
            edit.setText(simple_name(cid))

    def columns_all(self) -> None:
        self._simple_mode = False
        for cid, (chk, edit, _v) in self._col_widgets.items():
            chk.setChecked(True)
            edit.setText(cid)

    def _lock_columns(self, lock: bool) -> None:
        for chk, edit, _v in self._col_widgets.values():
            chk.setEnabled(not lock)
            edit.setEnabled(not lock)
        self.simple_btn.setEnabled(not lock)
        self.all_btn.setEnabled(not lock)
        self.fs_spin.setEnabled(not lock)

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de las grabaciones EMG", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def _open_folder(self) -> None:
        folder = Path(self.folder_edit.text().strip() or ".")
        if not folder.is_dir():
            self.ctx.notify("La carpeta todavía no existe: se creará al grabar.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def toggle_recording(self) -> None:
        if self.recorder is not None:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> bool:
        if self.channels == 0:
            QMessageBox.information(self, "Visor EMG", "Todavía no llegan datos del sensor. Espera a ver la señal.")
            return False
        folder = Path(self.folder_edit.text().strip() or documents_dir("Grabaciones EMG", create=False))
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = folder / f"{clean_name(self.name_edit.text())}_{stamp}.csv"
        try:
            self.recorder = CsvRecorder(path, self.channels, self.fs, self.selected_columns())
        except ValueError as error:
            QMessageBox.warning(self, "Visor EMG", str(error))
            return False
        except OSError as error:
            QMessageBox.critical(self, "Visor EMG", f"No se pudo crear el archivo:\n{error}")
            return False
        self._save_settings()
        self._lock_columns(True)
        self.analyze_btn.setVisible(False)
        self._update_rec_button()
        return True

    def stop_recording(self, reason: str = "") -> Path | None:
        rec, self.recorder = self.recorder, None
        if rec is None:
            return None
        rec.close()
        self._lock_columns(False)
        self._update_rec_button()
        lost = (f" — ⚠ {rec.lost} paquete{'s' if rec.lost != 1 else ''} perdido{'s' if rec.lost != 1 else ''}"
                if rec.lost else " — sin pérdidas")
        self._rec_note = (f"{reason}Guardado: {rec.path.name} — {rec.rows} muestras "
                          f"({rec.seconds:.1f} s de señal){lost}")
        self.rec_status.setText(self._rec_note)
        self.rec_status.setToolTip(str(rec.path))
        self._last_saved = rec.path
        self.analyze_btn.setVisible(True)
        self.ctx.notify(f"Grabación EMG guardada: {rec.path}", toast=True)
        return rec.path

    def _update_rec_button(self) -> None:
        recording = self.recorder is not None
        self.rec_btn.setText("■   PARAR GRABACIÓN" if recording else "●   EMPEZAR A GRABAR")
        self.rec_btn.setObjectName("danger" if recording else "primary")
        self.rec_btn.style().unpolish(self.rec_btn)
        self.rec_btn.style().polish(self.rec_btn)
        self.rec_btn.setEnabled(recording or self.channels > 0)

    def _analyze_last(self) -> None:
        if self._last_saved is not None:
            self.ctx.analyze_emg_file.emit(str(self._last_saved))

    # ================================================================ datos
    def _reset_stream(self, source: str, channels: int) -> None:
        if self.recorder is not None and channels != self.recorder.channels:
            self.stop_recording("El sensor cambió de formato: grabación detenida. ")
        self.source = source
        self.channels = channels
        n = int(BUFFER_S * self.fs)
        self._buf = np.zeros((n, max(channels, 1)))
        self._fbuf = np.zeros((n, max(channels, 1)))
        self._written = 0
        self._pre = Preprocessor(self.fs, channels) if channels else None
        self.stats.reset()
        self._hist.clear()
        self._pps = 0.0
        self._last_seq = None
        self._build_plots()
        self._build_columns()
        self._update_rec_button()
        self._dirty = True

    def on_message(self, msg) -> None:
        if msg.kind is not MessageKind.EMG or msg.payload is None:
            return
        frame = msg.payload
        samples = np.asarray(frame.samples)
        if samples.ndim != 2 or not len(samples):
            return
        now = time.monotonic()
        source = getattr(frame, "source", "puente")
        if source != self.source and self.source and now - self._last_frame < SOURCE_SILENCE_S:
            return                              # otra fuente mandando a la vez: se sigue la primera
        if source != self.source or samples.shape[1] != self.channels:
            self._reset_stream(source, samples.shape[1])
        lost, restart = self.stats.on_packet(int(frame.seq), getattr(frame, "seq_bits", 16),
                                             getattr(frame, "send_fails", None))
        self.batch = len(samples)
        self._last_frame = now
        self._last_seq = int(frame.seq)
        self._append(samples)
        if self.recorder is not None:
            try:
                self.recorder.write(int(frame.seq), samples, lost, restart)
            except (OSError, ValueError) as error:
                self.recorder.close()
                self.recorder = None
                self._rec_note = f"Error al escribir el archivo: {error}" 
                self._lock_columns(False)
                self._update_rec_button()
                self.ctx.notify(f"Visor EMG: error al escribir el archivo ({error}). Grabación detenida.",
                                error=True)
            else:
                limit = self.limit_spin.value()
                if limit > 0 and self.recorder.seconds >= limit:
                    self.stop_recording()
        self._dirty = True

    def _append(self, samples: np.ndarray) -> None:
        x = samples.astype(float)
        f = self._pre.process(x) if self._pre is not None else x
        size = len(self._buf)
        n = len(x)
        if n >= size:
            x, f, n = x[-size:], f[-size:], size
        p = self._written % size
        end = p + n
        if end <= size:
            self._buf[p:end] = x
            self._fbuf[p:end] = f
        else:
            k = size - p
            self._buf[p:], self._buf[:n - k] = x[:k], x[k:]
            self._fbuf[p:], self._fbuf[:n - k] = f[:k], f[k:]
        self._written += n

    def window_data(self, n: int, filtered: bool = False) -> np.ndarray:
        """Las últimas n muestras (o menos si aún no hay tantas), en orden."""
        buf = self._fbuf if filtered else self._buf
        size = len(buf)
        n = min(n, self._written, size)
        if n <= 0 or self.channels == 0:
            return np.zeros((0, max(self.channels, 1)))
        end = self._written % size
        start = end - n
        if start >= 0:
            return buf[start:end].copy()
        return np.concatenate((buf[start:], buf[:end]))

    # ================================================================ refresco
    def _tick(self) -> None:
        now = time.monotonic()
        self._hist.append((now, self.stats.packets))
        while self._hist and now - self._hist[0][0] > 2:
            self._hist.popleft()
        if len(self._hist) > 1 and now - self._hist[0][0] > 0.5:
            self._pps = (self._hist[-1][1] - self._hist[0][1]) / (now - self._hist[0][0])
        alive = self.channels > 0 and now - self._last_frame < NO_DATA_S
        self._update_status(alive, now)
        if not self.isVisible():
            return
        self.wait_lbl.setVisible(self.channels == 0)
        self.glw.setVisible(self.channels > 0)
        self._ticks += 1
        if self._ticks % 6 == 0:                         # el panel, 4 veces por segundo
            self._update_diag()
            self._update_column_values()
        if self.paused or not self._dirty or self.channels == 0:
            return
        self._dirty = False
        self._draw()

    def _draw(self) -> None:
        win = self._window_s()
        data = self.window_data(int(win * self.fs), self.filtered)
        n = len(data)
        if not n:
            for c in self.curves:
                c.setData([], [])
            return
        t = (np.arange(n) - n) / self.fs + 1 / self.fs
        for ch, (plot, curve) in enumerate(zip(self.plots, self.curves)):
            v = data[:, ch]
            curve.setData(t, v)
            if not self.auto_scale:
                continue
            lo, hi = float(v.min()), float(v.max())
            centre, half = (hi + lo) / 2, max((hi - lo) / 2 * 1.1, 5.0)
            s = self._scales[ch] if ch < len(self._scales) else None
            if s is None:
                s = [centre, half]
            else:                               # crece al instante, encoge despacio (no «baila»)
                s[0] += (centre - s[0]) * 0.1
                s[1] = half if half > s[1] else s[1] + (half - s[1]) * 0.03
            if ch < len(self._scales):
                self._scales[ch] = s
            plot.setYRange(s[0] - s[1], s[0] + s[1], padding=0)

    def _update_status(self, alive: bool, now: float) -> None:
        p = PALETTES[self.ctx.theme]
        rec = self.receiver
        if rec.connected:
            where = rec.port if rec.online else f"{rec.port} (reconectando…)"
            origin = f"Receptor USB {where}"
        elif self.source == "receptor":
            origin = "Receptor USB"
        elif self.source == "conexion":
            port = self.ctx.link.port_name if self.ctx.connected else ""
            origin = f"Conexión de la app {port}".rstrip()
        elif self.source:
            origin = "Conexión de la app (puente o simulación)"
        else:
            origin = ""
        if alive:
            dot, text = p["ok"], f"{origin} · recibiendo"
        elif rec.connected or self.ctx.connected:
            dot = p["warn"]
            text = ("Sin datos: ¿está encendido el sensor?" if self.stats.packets else
                    f"{origin or 'Conectado'} · esperando paquetes del sensor…")
        else:
            dot, text = p["subtle"], "Desconectado"
        self.source_lbl.setText(f'<span style="color:{dot}">●</span>&nbsp; {text}')
        self.source_hint.setVisible(not rec.connected and not alive)
        recorder = self.recorder
        if recorder is not None:
            self.rec_status.setText(f"● GRABANDO {recorder.path.name} — {recorder.rows} muestras — "
                                    f"{recorder.seconds:.1f} s de señal")
            self.rec_status.setToolTip(str(recorder.path))
        elif self._rec_note:
            self.rec_status.setText(self._rec_note)
        else:
            self.rec_status.setText("Llega señal: pulsa EMPEZAR A GRABAR." if alive else
                                    "Se puede grabar en cuanto llegue señal del sensor.")

    def _update_column_values(self) -> None:
        if self.channels == 0 or self._written == 0:
            values = {}
        else:
            last = self._buf[(self._written - 1) % len(self._buf)]
            t = self.recorder.last_t if self.recorder is not None and self.recorder.rows else self._written / self.fs
            values = {"t_s": f"{t:.3f}", "seq": str(self._last_seq), "idx": f"0…{max(self.batch - 1, 0)}"}
            values.update({f"ch{i + 1}": f"{int(v)}" for i, v in enumerate(last[:self.channels])})
        for cid, (_chk, _edit, label) in self._col_widgets.items():
            label.setText(values.get(cid, "—"))

    # ================================================================ tema y ajustes
    def on_theme_changed(self, theme: str) -> None:
        p = PALETTES[theme]
        self.glw.setBackground(p["card"])
        for plot in self.plots:
            for axis in ("left", "bottom"):
                ax = plot.getAxis(axis)
                ax.setPen(pg.mkPen(p["border_strong"]))
                ax.setTextPen(pg.mkPen(p["muted"]))
        self._update_diag()

    def _load_json(self, key: str, default):
        try:
            return json.loads(self.settings.value(f"{SETTINGS}/{key}", "") or "null") or default
        except (TypeError, ValueError):
            return default

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue(f"{SETTINGS}/carpeta", self.folder_edit.text())
        s.setValue(f"{SETTINGS}/nombre", self.name_edit.text())
        s.setValue(f"{SETTINGS}/limite", self.limit_spin.value())
        s.setValue(f"{SETTINGS}/modo_simple", "true" if self._simple_mode else "false")
        s.setValue(f"{SETTINGS}/columnas", json.dumps(self._cfg_cols, ensure_ascii=False))

    def shutdown(self) -> None:
        """Al cerrar la app: se cierra el archivo que se esté grabando y se guardan los ajustes."""
        if self.recorder is not None:
            self.stop_recording()
        self._save_settings()
