"""Pestaña 'Entrenamiento': control mioeléctrico por reconocimiento de patrones.

Es la "estación de calibración" que usan las prótesis comerciales (Coapt Gen2,
Ottobock Myo Plus), en tres pasos:

  1 Grabar    la app guía al usuario ("abre la mano… relaja…") y graba unos
              segundos de EMG de cada movimiento, con varias repeticiones.
  2 Entrenar  características de Hudgins + LDA; la precisión se estima con
              repeticiones que el modelo no ha visto (validación cruzada).
  3 Probar    el modelo clasifica en tiempo real y, si se activa, mueve la mano:
              cada movimiento se asocia a un gesto, una postura o PARAR.

┌ Señales musculares (EMG) ──────────────────────── ● 500 Hz · 2 canales  [Recibir EMG] ┐
│ gráfica de los últimos 5 s (filtrada)                                   │ C1 C2 barras │
└─────────────────────────────────────────────────────────────────────────────────────────┘
┌ [1 · Grabar] [2 · Entrenar] [3 · Probar y controlar] ─────────────┐ ┌ Paciente virtual ┐
│ contenido del paso                                                  │ │ (solo simulación)│
└─────────────────────────────────────────────────────────────────────┘ └──────────────────┘

Sin electrodos: en modo simulación, el "paciente virtual" (core/emg_sim.py)
genera el EMG. El cálculo está en core/emg.py (solo numpy) y se puede llevar a
la ESP32 con "Exportar a ESP32" (core/emg_export.py).
"""

import json
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, ORG_NAME
from ..core.emg import DEFAULT_FS, REST, EmgDataset, EmgModel, Preprocessor, RealtimeDecoder, TrainConfig, train_model
from ..core.emg_export import export_c_header
from ..core.emg_sim import CHANNEL_OPTIONS, MOVEMENTS, PATIENT
from ..core.gestures import ABIERTO, CERRADO, GESTOS, Gesto
from ..core.postures import posture_command
from ..core.protocol import MessageKind
from ..core.simulator import SIMULATOR_PORT
from ..paths import documents_dir, user_data_dir
from ..ui.emg_widgets import ConfusionMatrix, LevelBars, ProbBars
from ..ui.pictogram import hand_pixmap
from ..ui.theme import PALETTES, PLOT_COLORS
from ..ui.widgets import Stepper
from .base import BasePage

DISPLAY_S = 5            # segundos de señal en la gráfica
DEFAULT_SELECTED = [REST, "Abrir mano", "Cerrar mano"]
REACTION_S = 0.3         # el paciente virtual tarda en reaccionar a la indicación, como una persona
SIGNAL_TIMEOUT_S = 1.5   # sin paquetes EMG durante este tiempo = sin señal
DISPLAY_FLOOR = 40.0     # escala mínima de la gráfica y de las barras (cuentas): el reposo se ve pequeño

PROMPTS = {
    REST: ("Relaja la mano", "Deja el antebrazo suelto, sin hacer fuerza"),
    "Abrir mano": ("Abre la mano", "Extiende los dedos con fuerza y mantén"),
    "Cerrar mano": ("Cierra el puño", "Aprieta con fuerza moderada y mantén"),
    "Pinza": ("Haz una pinza", "Junta el pulgar y el índice y mantén"),
    "Señalar": ("Señala", "Estira el índice y cierra el resto"),
    "Co-contracción": ("Contrae todo", "Tensa a la vez los músculos de arriba y de abajo del antebrazo"),
}
POSES = {
    REST: Gesto(REST, ABIERTO, ABIERTO, ABIERTO, 10),
    "Abrir mano": GESTOS[0],
    "Cerrar mano": GESTOS[-1],
    "Pinza": Gesto("Pinza", CERRADO, ABIERTO, ABIERTO, 90),
    "Señalar": GESTOS[5],
    "Co-contracción": Gesto("Co-contracción", CERRADO, CERRADO, CERRADO, 90),
}
DEFAULT_ACTIONS = {REST: "", "Abrir mano": "GESTO 1", "Cerrar mano": f"GESTO {len(GESTOS)}",
                   "Pinza": "POSTURA C A A 90", "Señalar": "GESTO 6", "Co-contracción": ""}


@dataclass
class Phase:
    kind: str        # "prep" (descanso + aviso del siguiente) | "record"
    movement: str
    rep: int
    seconds: float


def _caption(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("caption")
    return label


def _muted(text: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(wrap)
    return label


class EmgPage(BasePage):
    title = "Entrenamiento"
    subtitle = ("Reconocimiento de patrones EMG: graba tus movimientos, entrena el clasificador "
                "y controla la mano con los músculos")
    icon = "brain"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.fs = DEFAULT_FS
        self.channels = 0
        self.dataset = EmgDataset(self.fs)
        self.model: EmgModel | None = None
        self.decoder: RealtimeDecoder | None = None
        self.receiving = False
        self.lost = 0
        self._last_seq: int | None = None
        self._last_frame = 0.0
        self._arrivals: deque[tuple[float, int]] = deque(maxlen=100)
        self._display_pre: Preprocessor | None = None
        self._disp = np.zeros((0, 0))
        self._peak = np.zeros(0)
        self._dirty = False
        self._plan: list[Phase] = []
        self._phase_i = -1
        self._phase_t0 = 0.0
        self._rec_buf: list[np.ndarray] = []
        self._own_tx = False
        self._control_last = ""
        self._control_time = 0.0
        self._stable_label, self._stable_n = "", 0
        self.actions: dict[str, str] = dict(DEFAULT_ACTIONS)
        try:
            self.actions.update(json.loads(self.settings.value("emg_actions", "{}")))
        except (TypeError, ValueError):
            pass
        self._ai_dir = user_data_dir() / "ia"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._build_signal_card(), 3)
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        bottom.addWidget(self._build_steps_card(), 1)
        self.patient_card = self._build_patient_card()
        bottom.addWidget(self.patient_card)
        root.addLayout(bottom, 7)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(50)
        self._ui_timer.timeout.connect(self._refresh)
        self._ui_timer.start()
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(50)
        self._rec_timer.timeout.connect(self._rec_tick)

        ctx.postures_changed.connect(self._rebuild_mapping)
        ctx.replay_changed.connect(lambda _r: self._update_enabled())
        ctx.sim_mode_changed.connect(lambda _s: self._update_enabled())
        self._load_autosave()
        self.on_theme_changed(ctx.theme)
        self._update_enabled()

    # ================================================================ señales
    def _build_signal_card(self) -> QWidget:
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("muted")
        self.receive_btn = self.button("Recibir EMG", "zap", "", "Pide al puente que reenvíe las señales EMG (@EMG 1)")
        self.receive_btn.setCheckable(True)
        self.receive_btn.clicked.connect(lambda checked: self.set_receiving(checked))
        card, lay = self.card("Señales musculares (EMG)", [self.status_lbl, self.receive_btn])
        self.plot_box = QWidget()
        row = QHBoxLayout(self.plot_box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=True, y=False, alpha=0.12)
        self.plot.setXRange(-DISPLAY_S, 0, padding=0)
        self.plot.setLabel("bottom", "tiempo", units="s")
        self.plot.getAxis("left").setWidth(34)
        self.plot.setMinimumHeight(110)
        self.curves: list = []
        row.addWidget(self.plot, 1)
        self.levels = LevelBars(self.ctx)
        self.levels.setFixedWidth(128)
        row.addWidget(self.levels)
        lay.addWidget(self.plot_box, 1)
        self.signal_hint = _muted(
            "Sin señal EMG. Conecta la simulación (paciente virtual) o la mano real y pulsa «Recibir EMG». "
            "Con hardware, la placa del ADS1198 debe enviar al puente: en firmware/EMG/src/main.cpp, "
            "rxMac = MAC del puente (la muestra @INFO).")
        lay.addWidget(self.signal_hint)
        return card

    def set_receiving(self, on: bool) -> None:
        """Activa o desactiva el reenvío de EMG en el puente (real o simulado)."""
        if not self.ctx.connected:
            self.receive_btn.setChecked(False)
            if on:
                self.ctx.notify("EMG: conecta primero la simulación o la mano real.", error=True)
            return
        self.ctx.send_command(f"EMG {1 if on else 0}")
        self.receiving = on
        self.receive_btn.setChecked(on)

    def _reset_stream(self, channels: int) -> None:
        self.channels = channels
        self._display_pre = Preprocessor(self.fs, channels)
        self._disp = np.zeros((0, channels))
        self._peak = np.full(channels, DISPLAY_FLOOR)
        self._scale = np.full(channels, DISPLAY_FLOOR)
        for c in self.curves:
            self.plot.removeItem(c)
        self.curves = [self.plot.plot(pen=pg.mkPen(PLOT_COLORS[i % len(PLOT_COLORS)], width=1.2))
                       for i in range(channels)]
        ticks = [[(channels - 1 - i, f"C{i + 1}") for i in range(channels)]]
        self.plot.getAxis("left").setTicks(ticks)
        self.plot.setYRange(-0.6, channels - 0.4, padding=0)
        self._check_model_channels()

    def on_message(self, msg) -> None:
        kind = msg.kind
        if kind is MessageKind.TX:
            if msg.text == "PARAR" and self.control_chk.isChecked() and not self._own_tx:
                self.control_chk.setChecked(False)
                self.ctx.notify("Control por EMG desactivado: se pulsó Parar.")
            return
        if kind is MessageKind.BRIDGE and msg.text.startswith("EMG "):
            self.receiving = msg.text.split()[1] == "1"
            self.receive_btn.setChecked(self.receiving)
            return
        if kind is not MessageKind.EMG or msg.payload is None:
            return
        frame = msg.payload
        samples = frame.samples
        if samples.shape[1] != self.channels:
            self._reset_stream(samples.shape[1])
        if self._last_seq is not None:
            gap = (frame.seq - self._last_seq - 1) & 0xFFFF
            if 0 < gap < 1000:
                self.lost += gap
        self._last_seq = frame.seq
        now = time.monotonic()
        self._last_frame = now
        self._arrivals.append((now, len(samples)))
        filtered = self._display_pre.process(samples)
        self._disp = np.vstack([self._disp, filtered])[-self.fs * DISPLAY_S:]
        self._dirty = True
        phase = self._phase
        if phase is not None and phase.kind == "record":
            self._rec_buf.append(samples.copy())
        if self.decoder is not None:
            try:
                decisions = self.decoder.push(samples)
            except ValueError as error:
                self.decoder = None
                self.ctx.notify(f"IA: {error}. Vuelve a entrenar con los canales actuales.", error=True)
                return
            for d in decisions:
                self._on_decision(d)

    def _refresh(self) -> None:
        """Redibuja a 20 Hz (la gráfica, los niveles y el estado de la señal)."""
        now = time.monotonic()
        alive = now - self._last_frame < SIGNAL_TIMEOUT_S
        rate = 0.0
        recent = [(t, n) for t, n in self._arrivals if now - t <= 1.0]
        if len(recent) >= 2:
            rate = sum(n for _t, n in recent[1:]) / max(recent[-1][0] - recent[0][0], 1e-3)
        p = PALETTES[self.ctx.theme]
        if alive:
            lost = f" · {self.lost} perdidos" if self.lost else ""
            # se muestra la frecuencia nominal si la medida cuadra (los paquetes llegan a ráfagas)
            ok_rate = abs(rate - self.fs) <= 0.1 * self.fs
            shown = f"{self.fs} Hz" if ok_rate else f'<span style="color:{p["warn"]}">{rate:.0f} Hz</span>'
            self.status_lbl.setText(f'<span style="color:{p["ok"]}">●</span>&nbsp; {shown} · '
                                    f'{self.channels} canales{lost}')
        else:
            self.status_lbl.setText(f'<span style="color:{p["subtle"]}">●</span>&nbsp; sin señal')
        waiting = not alive and not len(self._disp)  # hasta que llega señal, solo el aviso (ocupa menos)
        self.signal_hint.setVisible(waiting)
        self.plot_box.setVisible(not waiting)
        if not (self._dirty and self.isVisible()) or not len(self._disp):
            return
        self._dirty = False
        d = self._disp
        n = len(d)
        t = (np.arange(n) - (n - 1)) / self.fs
        # escala con memoria: tras una contracción fuerte, el reposo se ve pequeño (no ocupa toda la banda)
        peak = np.percentile(np.abs(d[-self.fs:]), 99, axis=0)
        self._scale = np.maximum(np.maximum(self._scale * 0.995, peak), DISPLAY_FLOOR)
        for i, curve in enumerate(self.curves):
            curve.setData(t, d[:, i] / self._scale[i] * 0.42 + (self.channels - 1 - i))
        mav = np.abs(d[-50:]).mean(axis=0)
        if self.model is not None and self.model.channels == self.channels:
            m = self.model
            levels = np.clip((mav - m.rest_mav) / (m.max_mav - m.rest_mav), 0, 1)
        else:
            self._peak = np.maximum(np.maximum(self._peak * 0.995, mav), DISPLAY_FLOOR)
            levels = mav / self._peak
        self.levels.set_levels([float(v) for v in levels])

    # ================================================================== pasos
    def _build_steps_card(self) -> QWidget:
        card, lay = self.card()
        self.stepper = Stepper(self.ctx, ["Grabar", "Entrenar", "Probar y controlar"])
        self.stepper.setToolTip("Los pasos completados se marcan con ✓")
        self.stepper.step_clicked.connect(self.set_step)
        lay.addWidget(self.stepper)
        self.step_stack = QStackedWidget()
        lay.addWidget(self.step_stack, 1)
        for tab in (self._build_record_tab(), self._build_train_tab(), self._build_test_tab()):
            self.step_stack.addWidget(self._scroll(tab))
        step = int(self.settings.value("emg_step", 0))
        self.set_step(step if step in (0, 1, 2) else 0)
        return card

    @staticmethod
    def _scroll(content: QWidget) -> QScrollArea:
        """Cada paso en su zona desplazable: con la ventana pequeña o la consola abierta no se aplasta."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(content)
        content.setAutoFillBackground(False)
        area.viewport().setAutoFillBackground(False)
        return area

    def set_step(self, i: int) -> None:
        self.stepper.set_current(i)
        self.step_stack.setCurrentIndex(i)
        self.settings.setValue("emg_step", i)

    # ---------------------------------------------------------- 1 · Grabar
    def _build_record_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(_caption("Movimientos a grabar"))
        head.addStretch(1)
        lay.addLayout(head)
        self.moves_box = QWidget()
        self.moves_grid = QGridLayout(self.moves_box)
        self.moves_grid.setContentsMargins(0, 0, 0, 0)
        self.moves_grid.setSpacing(6)
        lay.addWidget(self.moves_box)
        saved = self.settings.value("emg_moves", "")
        try:
            selected = json.loads(saved) if saved else list(DEFAULT_SELECTED)
        except ValueError:
            selected = list(DEFAULT_SELECTED)
        custom = [m for m in selected if m not in MOVEMENTS]
        self.move_buttons: dict[str, QPushButton] = {}
        for name in list(MOVEMENTS) + custom:
            self._add_move_button(name, name in selected)
        self.add_move_btn = QPushButton("+ Otro")
        self.add_move_btn.setObjectName("chip")
        self.add_move_btn.setToolTip("Añadir un movimiento con otro nombre (p. ej. Rotar muñeca)")
        self.add_move_btn.clicked.connect(self._ask_custom_move)
        self._layout_moves()

        opts = QHBoxLayout()
        opts.setSpacing(8)
        self.reps = self._spin(1, 10, int(self.settings.value("emg_reps", 3)), "", "Repeticiones de cada movimiento")
        self.dur = self._spin(2, 10, int(self.settings.value("emg_dur", 3)), " s", "Duración de cada contracción")
        self.rest_s = self._spin(1, 10, int(self.settings.value("emg_rest", 2)), " s", "Descanso entre contracciones")
        for label, w in (("Repeticiones", self.reps), ("Contracción", self.dur), ("Descanso", self.rest_s)):
            opts.addWidget(_muted(label, False))
            opts.addWidget(w)
            opts.addSpacing(6)
        opts.addStretch(1)
        lay.addLayout(opts)
        start = QHBoxLayout()  # en su propia línea: así cabe aunque la ventana sea estrecha
        self.rec_btn = self.button("Empezar grabación guiada", "play", "primary",
                                   "La app te irá indicando qué movimiento hacer y cuándo descansar")
        self.rec_btn.clicked.connect(self.toggle_guided)
        start.addWidget(self.rec_btn)
        start.addStretch(1)
        lay.addLayout(start)

        # --- indicación grande
        self.prompt = QWidget()
        self.prompt.setObjectName("inset")
        self.prompt.setAttribute(Qt.WA_StyledBackground, True)
        pr = QHBoxLayout(self.prompt)
        pr.setContentsMargins(16, 12, 16, 12)
        pr.setSpacing(16)
        self.prompt_pic = QLabel()
        self.prompt_pic.setFixedSize(76, 76)
        self.prompt_pic.setAlignment(Qt.AlignCenter)
        pr.addWidget(self.prompt_pic)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        self.prompt_title = QLabel("Preparado para grabar")
        self.prompt_title.setObjectName("promptTitle")
        self.prompt_sub = _muted("Elige los movimientos y pulsa «Empezar grabación guiada». Incluye siempre Reposo: "
                                 "es lo que la mano interpreta como «no hacer nada».")
        self.prompt_bar = QProgressBar()
        self.prompt_bar.setTextVisible(False)
        self.prompt_bar.setRange(0, 1000)
        self.prompt_bar.setValue(0)
        texts.addWidget(self.prompt_title)
        texts.addWidget(self.prompt_sub)
        texts.addWidget(self.prompt_bar)
        pr.addLayout(texts, 1)
        self.prompt_step = QLabel()
        self.prompt_step.setObjectName("value")
        pr.addWidget(self.prompt_step, 0, Qt.AlignTop)
        lay.addWidget(self.prompt)

        data = QHBoxLayout()
        data.setSpacing(8)
        self.data_lbl = _muted()
        data.addWidget(self.data_lbl, 1)
        save = self.button("", "save", "ghost", "Guardar los datos grabados en CSV (Excel, MATLAB, Python)")
        save.clicked.connect(self.save_dataset)
        load = self.button("", "upload", "ghost", "Cargar datos grabados (CSV)")
        load.clicked.connect(self.load_dataset)
        clear = self.button("", "trash", "ghost", "Borrar los datos grabados")
        clear.clicked.connect(self.clear_dataset)
        for w in (save, load, clear):
            data.addWidget(w)
        lay.addLayout(data)
        lay.addStretch(1)
        return page

    def _spin(self, lo: int, hi: int, value: int, suffix: str, tip: str) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(min(max(value, lo), hi))
        s.setSuffix(suffix)
        s.setToolTip(tip)
        s.setFixedWidth(72)
        return s

    def _add_move_button(self, name: str, checked: bool) -> None:
        b = QPushButton(name)
        b.setObjectName("toggleChip")
        b.setCursor(Qt.PointingHandCursor)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setToolTip(PROMPTS.get(name, (name, "Movimiento propio"))[1])
        if name == REST:
            b.setToolTip("Necesario: es el estado «no hacer nada»")
        b.toggled.connect(lambda _c: self._save_moves())
        self.move_buttons[name] = b

    def _layout_moves(self) -> None:
        widgets = list(self.move_buttons.values()) + [self.add_move_btn]
        for i, w in enumerate(widgets):
            self.moves_grid.addWidget(w, i // 4, i % 4)

    def _ask_custom_move(self) -> None:
        name, ok = QInputDialog.getText(self.window(), "Nuevo movimiento", "Nombre del movimiento:")
        name = name.strip()[:24]
        if ok and name and name not in self.move_buttons:
            self._add_move_button(name, True)
            self._layout_moves()
            self._save_moves()

    def _save_moves(self) -> None:
        self.settings.setValue("emg_moves", json.dumps(self.selected_moves(), ensure_ascii=False))

    def selected_moves(self) -> list[str]:
        moves = [n for n, b in self.move_buttons.items() if b.isChecked()]
        return sorted(moves, key=lambda m: m != REST)

    # --- grabación guiada
    @property
    def _phase(self) -> Phase | None:
        return self._plan[self._phase_i] if 0 <= self._phase_i < len(self._plan) else None

    def toggle_guided(self) -> None:
        if self._phase is not None:
            self._stop_guided("Grabación cancelada. Lo ya grabado se conserva.")
            return
        moves = self.selected_moves()
        if len(moves) < 2:
            self.ctx.notify("Elige al menos dos movimientos (por ejemplo Reposo y Abrir mano).", error=True)
            return
        if REST not in moves:
            answer = QMessageBox.question(self.window(), "Sin Reposo",
                                          "No has elegido Reposo. Sin él, la IA siempre detectará algún movimiento "
                                          "aunque no hagas nada. ¿Grabar igualmente?")
            if answer != QMessageBox.Yes:
                return
        if not self.ctx.connected:
            self.ctx.notify("Para grabar hace falta señal EMG: conecta la simulación o la mano real.", error=True)
            return
        if self.dataset.channels and self.channels and self.dataset.channels != self.channels:
            answer = QMessageBox.question(self.window(), "Canales distintos",
                                          f"Los datos grabados tienen {self.dataset.channels} canales y ahora llegan "
                                          f"{self.channels}. ¿Borrar los datos anteriores y empezar de nuevo?")
            if answer != QMessageBox.Yes:
                return
            self.dataset.clear()
        if not self.receiving:
            self.set_receiving(True)
        for key, w in (("emg_reps", self.reps), ("emg_dur", self.dur), ("emg_rest", self.rest_s)):
            self.settings.setValue(key, w.value())
        plan = []
        for rep in range(1, self.reps.value() + 1):
            for m in moves:
                plan.append(Phase("prep", m, rep, 3.0 if not plan else float(self.rest_s.value())))
                plan.append(Phase("record", m, rep, float(self.dur.value())))
        self._plan = plan
        self._start_phase(0)
        self._rec_timer.start()
        self.rec_btn.setText("  Cancelar grabación")
        self._paint_icons_rec(True)
        self._update_enabled()

    def _start_phase(self, i: int) -> None:
        self._phase_i = i
        self._phase_t0 = time.monotonic()
        self._rec_buf = []
        phase = self._phase
        if phase is None:
            return
        p = PALETTES[self.ctx.theme]
        title, sub = PROMPTS.get(phase.movement, (phase.movement, "Haz el movimiento y mantén"))
        pose = POSES.get(phase.movement, POSES[REST])
        total_rec = sum(ph.kind == "record" for ph in self._plan)
        done = sum(ph.kind == "record" for ph in self._plan[:i])
        self.prompt_step.setText(f"{done + (phase.kind == 'record')}/{total_rec}  ·  rep. {phase.rep}")
        if phase.kind == "prep":
            self.prompt_title.setText("Relaja…")
            self.prompt_sub.setText(f"Siguiente: {title.lower()}. {sub}.")
            self.prompt_pic.setPixmap(hand_pixmap(pose, p["subtle"], p["border_strong"], 68))
            self._patient_follow(REST)
        else:
            self.prompt_title.setText(f"¡Ahora! {title}")
            self.prompt_sub.setText(sub)
            self.prompt_pic.setPixmap(hand_pixmap(pose, p["muted"], p["accent"], 68))
            QTimer.singleShot(int(REACTION_S * 1000), lambda m=phase.movement, i=i: (
                self._phase_i == i and self._patient_follow(m)))

    def _rec_tick(self) -> None:
        phase = self._phase
        if phase is None:
            return
        elapsed = time.monotonic() - self._phase_t0
        self.prompt_bar.setValue(int(min(elapsed / phase.seconds, 1.0) * 1000))
        if phase.kind == "record" and elapsed > 1.0 and time.monotonic() - self._last_frame > SIGNAL_TIMEOUT_S:
            self._stop_guided("Grabación detenida: no llega señal EMG.", error=True)
            return
        if elapsed < phase.seconds:
            return
        if phase.kind == "record":
            if self._rec_buf:
                try:
                    self.dataset.add(phase.movement, np.vstack(self._rec_buf))
                except ValueError as error:
                    self._stop_guided(f"No se pudo guardar la grabación: {error}", error=True)
                    return
            self._update_data_label()
        if self._phase_i + 1 < len(self._plan):
            self._start_phase(self._phase_i + 1)
        else:
            self._stop_guided(f"Grabación completa: {len(self.dataset)} grabaciones. Siguiente paso: 2 · Entrenar.")
            self.set_step(1)

    def _stop_guided(self, text: str, error: bool = False) -> None:
        self._rec_timer.stop()
        self._plan, self._phase_i = [], -1
        self._rec_buf = []
        self._patient_follow(REST)
        self.rec_btn.setText("  Empezar grabación guiada")
        self._paint_icons_rec(False)
        self.prompt_title.setText("Grabación terminada" if not error else "Grabación detenida")
        self.prompt_sub.setText(text)
        self.prompt_step.setText("")
        self.prompt_bar.setValue(0)
        p = PALETTES[self.ctx.theme]
        self.prompt_pic.setPixmap(hand_pixmap(POSES[REST], p["muted"], p["accent"], 68))
        self.ctx.notify(text, error=error, toast=True)
        self._autosave_dataset()
        self._update_enabled()

    def _paint_icons_rec(self, recording: bool) -> None:
        for i, (btn, name, color) in enumerate(self._icon_buttons):
            if btn is self.rec_btn:
                self._icon_buttons[i] = (btn, "stop" if recording else "play", color)
        self._paint_icons()

    def _update_data_label(self) -> None:
        self.stepper.set_done(0, len(self.dataset.labels()) >= 2)
        summary = self.dataset.summary()
        if not summary:
            self.data_lbl.setText("Sin datos grabados.")
            return
        parts = [f"{label} {reps}× ({secs:.0f} s)" for label, (reps, secs) in summary.items()]
        self.data_lbl.setText(f"Datos ({self.dataset.channels} canales): " + " · ".join(parts))

    # --- datos
    def save_dataset(self) -> None:
        if not len(self.dataset):
            self.ctx.notify("No hay datos grabados que guardar.", error=True)
            return
        name = f"emg_datos_{time.strftime('%Y-%m-%d_%H-%M')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar datos EMG", str(documents_dir("IA") / name), "CSV (*.csv)")
        if path:
            self.dataset.save_csv(path)
            self.ctx.notify(f"Datos EMG guardados en {path}", toast=True)

    def load_dataset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cargar datos EMG", str(documents_dir("IA")), "CSV (*.csv)")
        if not path:
            return
        try:
            self.dataset = EmgDataset.load_csv(path)
        except (OSError, ValueError, IndexError) as error:
            QMessageBox.warning(self, "No se pudieron cargar los datos", str(error))
            return
        self.fs = self.dataset.fs
        self._update_data_label()
        self._autosave_dataset()
        self.ctx.notify(f"Datos EMG cargados: {len(self.dataset)} grabaciones.", toast=True)

    def clear_dataset(self) -> None:
        if not len(self.dataset):
            return
        answer = QMessageBox.question(self.window(), "Borrar datos", "¿Borrar todas las grabaciones EMG?")
        if answer == QMessageBox.Yes:
            self.dataset.clear()
            self._update_data_label()
            self._autosave_dataset()

    # --------------------------------------------------------- 2 · Entrenar
    def _build_train_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        opts = QHBoxLayout()
        opts.setSpacing(8)
        self.win_combo = QComboBox()
        for ms in (100, 150, 200, 250):
            self.win_combo.addItem(f"{ms} ms", ms)
        self.win_combo.setCurrentIndex(max(self.win_combo.findData(int(self.settings.value("emg_win", 150))), 0))
        self.win_combo.setToolTip("Duración de cada ventana de análisis: más larga = más precisa pero más lenta")
        self.vote_combo = QComboBox()
        for v in (1, 3, 5):
            self.vote_combo.addItem(str(v), v)
        self.vote_combo.setCurrentIndex(max(self.vote_combo.findData(int(self.settings.value("emg_vote", 3))), 0))
        self.vote_combo.setToolTip("Voto por mayoría de las últimas N decisiones: evita saltos sueltos")
        for label, w in (("Ventana", self.win_combo), ("Voto", self.vote_combo)):
            opts.addWidget(_muted(label, False))
            opts.addWidget(w)
            opts.addSpacing(6)
        opts.addWidget(_muted("Decisión cada 50 ms", False))
        opts.addStretch(1)
        self.train_btn = self.button("Entrenar modelo", "brain", "primary",
                                     "Características de Hudgins + LDA, con validación cruzada por repeticiones")
        self.train_btn.clicked.connect(self.train)
        opts.addWidget(self.train_btn)
        lay.addLayout(opts)

        body = QHBoxLayout()
        body.setSpacing(14)
        score = QWidget()
        score.setObjectName("inset")
        score.setAttribute(Qt.WA_StyledBackground, True)
        score.setFixedWidth(232)
        sl = QVBoxLayout(score)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(2)
        sl.addWidget(_caption("Precisión estimada"))
        self.acc_lbl = QLabel("—")
        self.acc_lbl.setObjectName("bigNumber")
        sl.addWidget(self.acc_lbl)
        self.acc_sub = _muted("con datos que el modelo no ha visto")
        sl.addWidget(self.acc_sub)
        sl.addSpacing(8)
        sl.addWidget(_caption("Retardo del controlador"))
        self.delay_lbl = QLabel("—")
        self.delay_lbl.setTextFormat(Qt.RichText)
        sl.addWidget(self.delay_lbl)
        sl.addStretch(1)
        body.addWidget(score)
        self.confusion = ConfusionMatrix(self.ctx)
        self.confusion.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(self.confusion, 1)
        lay.addLayout(body, 1)
        self.tip_lbl = _muted()
        lay.addWidget(self.tip_lbl)

        files = QHBoxLayout()
        files.setSpacing(8)
        self.model_lbl = _muted("Sin modelo.", False)
        files.addWidget(self.model_lbl, 1)
        save = self.button("Guardar", "save", "", "Guardar el modelo (.json)")
        save.clicked.connect(self.save_model)
        load = self.button("Cargar", "upload", "", "Cargar un modelo guardado")
        load.clicked.connect(self.load_model)
        self.export_btn = self.button("Exportar a ESP32", "cpu", "",
                                      "Genera biomec_emg_modelo.h: el mismo clasificador en C para la placa")
        self.export_btn.clicked.connect(self.export_model)
        self._model_buttons = [save, self.export_btn]
        for w in (save, load, self.export_btn):
            files.addWidget(w)
        lay.addLayout(files)
        return page

    def train(self) -> None:
        if len(self.dataset.labels()) < 2:
            self.ctx.notify("Graba antes al menos dos movimientos (paso 1).", error=True)
            self.set_step(0)
            return
        self.settings.setValue("emg_win", self.win_combo.currentData())
        self.settings.setValue("emg_vote", self.vote_combo.currentData())
        cfg = TrainConfig(window_ms=self.win_combo.currentData(), vote=self.vote_combo.currentData())
        self.setCursor(Qt.WaitCursor)
        try:
            model = train_model(self.dataset, cfg)
        except (ValueError, np.linalg.LinAlgError) as error:
            QMessageBox.warning(self, "No se pudo entrenar", str(error))
            return
        finally:
            self.unsetCursor()
        self._set_model(model)
        self._autosave_model()
        acc = model.report.accuracy * 100
        self.ctx.notify(f"Modelo entrenado: {len(model.classes)} movimientos, precisión estimada {acc:.0f} %.",
                        toast=True)

    def _set_model(self, model: EmgModel | None) -> None:
        self.model = model
        self.decoder = None
        p = PALETTES[self.ctx.theme]
        if model is None:
            self.acc_lbl.setText("—")
            self.delay_lbl.setText("—")
            self.model_lbl.setText("Sin modelo.")
            self.confusion.set_report([], None)
            self.tip_lbl.setText("")
        else:
            rep = model.report
            if rep is not None and rep.confusion.sum():
                acc = rep.accuracy
                color = p["ok"] if acc >= 0.9 else p["warn"] if acc >= 0.75 else p["error"]
                self.acc_lbl.setText(f"{acc * 100:.0f} %")
                self.acc_lbl.setStyleSheet(f"color: {color};")
                self.acc_sub.setText("validación cruzada por repeticiones" if "repetición" in rep.method
                                     else "70 % entrenar / 30 % evaluar")
                self.acc_sub.setToolTip(rep.method)
                self.confusion.set_report(rep.classes, rep.confusion)
                self.tip_lbl.setText(self._advice(model))
            else:
                self.acc_lbl.setText("?")
                self.acc_lbl.setStyleSheet("")
                self.confusion.set_report(model.classes, None)
            delay = model.delay_ms
            # Farrell y Weir (2007): el retardo óptimo del controlador está en 100-125 ms
            level = "ok" if delay <= 125 else "warn" if delay <= 175 else "error"
            self.delay_lbl.setText(f'<span style="color:{p[level]}"><b>≈ {delay:.0f} ms</b></span>'
                                   f'<br><span style="color:{p["muted"]}">óptimo ≤ 125 ms (Farrell y Weir, 2007)</span>')
            self.delay_lbl.setWordWrap(True)
            self.model_lbl.setText(f"Modelo: {len(model.classes)} movimientos · {model.channels} canales · "
                                   f"ventana {model.config.window_ms} ms · voto {model.config.vote}")
            self._check_model_channels()
        self.stepper.set_done(1, model is not None)
        for b in self._model_buttons:
            b.setEnabled(model is not None)
        self.probs.set_classes(model.classes if model else [])
        self.action_lbl.setText("Activa «Mover la mano con el EMG» para que cada movimiento envíe su comando."
                                if model else "Entrena o carga un modelo (paso 2) para probarlo.")
        self._rebuild_mapping()
        self._update_enabled()

    @staticmethod
    def _advice(model: EmgModel) -> str:
        rep = model.report
        worst = rep.worst_pair()
        acc = rep.accuracy
        tips = []
        if worst and worst[2] >= 0.1:
            tips.append(f"«{worst[0]}» se confunde con «{worst[1]}» ({worst[2] * 100:.0f} % de las veces): "
                        "haz esos movimientos más distintos, quita uno, o usa más canales del ADS1198 "
                        f"(ahora {model.channels} de 8).")
        if acc < 0.9 and "repetición" not in rep.method:
            tips.append("Graba 2 o más repeticiones para una estimación más fiable.")
        if not tips:
            tips.append("Buen modelo. Pruébalo en el paso 3 antes de mover la mano real con él.")
        return "  ".join(tips)

    def _check_model_channels(self) -> None:
        """El decodificador solo funciona si el modelo y la señal tienen los mismos canales."""
        m = self.model
        if m is not None and self.channels and m.channels == self.channels:
            if self.decoder is None:
                self.decoder = RealtimeDecoder(m)
        else:
            self.decoder = None

    def save_model(self) -> None:
        if self.model is None:
            return
        name = f"modelo_emg_{time.strftime('%Y-%m-%d_%H-%M')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar modelo", str(documents_dir("IA") / name),
                                              "Modelo EMG (*.json)")
        if path:
            self.model.save(path)
            self.ctx.notify(f"Modelo guardado en {path}", toast=True)

    def load_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cargar modelo", str(documents_dir("IA")), "Modelo EMG (*.json)")
        if not path:
            return
        try:
            model = EmgModel.load(path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(self, "No se pudo cargar el modelo", str(error))
            return
        self._set_model(model)
        self._autosave_model()
        self.ctx.notify(f"Modelo cargado: {', '.join(model.classes)}", toast=True)

    def export_model(self) -> None:
        if self.model is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar el modelo para la ESP32",
                                              str(documents_dir("IA") / "biomec_emg_modelo.h"), "Cabecera C (*.h)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(export_c_header(self.model))
        self.ctx.notify(f"Modelo exportado a {path}. Inclúyelo en el firmware con #include \"biomec_emg_modelo.h\".",
                        toast=True)

    # ----------------------------------------------- 3 · Probar y controlar
    def _build_test_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(14)
        det = QWidget()
        det.setObjectName("inset")
        det.setAttribute(Qt.WA_StyledBackground, True)
        det.setFixedWidth(230)
        det.setMinimumHeight(150)
        dl = QVBoxLayout(det)
        dl.setContentsMargins(14, 12, 14, 12)
        dl.setSpacing(4)
        dl.addWidget(_caption("Movimiento detectado"))
        row = QHBoxLayout()
        self.det_pic = QLabel()
        self.det_pic.setFixedSize(60, 60)
        row.addWidget(self.det_pic)
        col = QVBoxLayout()
        self.det_lbl = QLabel("—")
        self.det_lbl.setObjectName("detected")
        self.det_conf = _muted("", False)
        col.addWidget(self.det_lbl)
        col.addWidget(self.det_conf)
        row.addLayout(col, 1)
        dl.addLayout(row)
        dl.addSpacing(4)
        dl.addWidget(_caption("Intensidad"))
        self.intensity = QProgressBar()
        self.intensity.setTextVisible(False)
        self.intensity.setRange(0, 100)
        dl.addWidget(self.intensity)
        dl.addStretch(1)
        top.addWidget(det)
        probs_box = QVBoxLayout()
        probs_box.addWidget(_caption("Probabilidad de cada movimiento"))
        self.probs = ProbBars(self.ctx)
        probs_box.addWidget(self.probs)
        probs_box.addStretch(1)
        top.addLayout(probs_box, 1)
        lay.addLayout(top)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.control_chk = QCheckBox("Mover la mano con el EMG")
        self.control_chk.setToolTip("Cada movimiento detectado envía su comando (ver tabla). Esc o Parar lo desactiva.")
        self.control_chk.toggled.connect(self._on_control_toggled)
        ctrl.addWidget(self.control_chk)
        ctrl.addStretch(1)
        ctrl.addWidget(_muted("Confianza mínima", False))
        self.min_conf = self._spin(40, 99, int(self.settings.value("emg_conf", 70)), " %",
                                   "Por debajo de esta probabilidad no se envía nada")
        self.min_conf.valueChanged.connect(lambda v: self.settings.setValue("emg_conf", v))
        ctrl.addWidget(self.min_conf)
        ctrl.addWidget(_muted("Estable", False))
        self.stable = self._spin(1, 10, int(self.settings.value("emg_stable", 2)), "",
                                 "Decisiones seguidas iguales antes de mover la mano (cada una son 50 ms)")
        self.stable.valueChanged.connect(lambda v: self.settings.setValue("emg_stable", v))
        ctrl.addWidget(self.stable)
        lay.addLayout(ctrl)

        lay.addWidget(_caption("Qué hace la mano con cada movimiento"))
        self.map_box = QWidget()
        self.map_grid = QGridLayout(self.map_box)
        self.map_grid.setContentsMargins(0, 0, 0, 0)
        self.map_grid.setHorizontalSpacing(10)
        self.map_grid.setVerticalSpacing(6)
        lay.addWidget(self.map_box)
        self.action_lbl = _muted()
        lay.addWidget(self.action_lbl)
        lay.addStretch(1)
        self.map_combos: dict[str, QComboBox] = {}
        return page

    def _action_options(self) -> list[tuple[str, str]]:
        opts = [("— Nada (la mano se queda como está)", ""), ("PARAR · frenar los motores", "PARAR")]
        opts += [(f"Gesto {i} · {g.nombre}", f"GESTO {i}") for i, g in enumerate(GESTOS, start=1)]
        opts += [(f"Postura · {g.nombre}", posture_command(g)) for g in self.ctx.postures.items]
        known = {cmd for _l, cmd in opts}
        if "POSTURA C A A 90" not in known:
            opts.append(("Pinza (POSTURA C A A 90)", "POSTURA C A A 90"))
        return opts

    def _rebuild_mapping(self) -> None:
        for combo in self.map_combos.values():
            combo.deleteLater()
        while self.map_grid.count():
            item = self.map_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.map_combos = {}
        if self.model is None:
            return
        opts = self._action_options()
        cols = 2 if len(self.model.classes) > 3 else 1
        for i, cls in enumerate(self.model.classes):
            label = QLabel(cls)
            combo = QComboBox()
            for text, cmd in opts:
                combo.addItem(text, cmd)
            current = self.actions.get(cls, "")
            idx = combo.findData(current)
            if idx < 0 and current:
                combo.addItem(current, current)
                idx = combo.count() - 1
            combo.setCurrentIndex(max(idx, 0))
            combo.currentIndexChanged.connect(lambda _i, c=cls, w=combo: self._set_action(c, w.currentData()))
            r, c = divmod(i, cols)
            self.map_grid.addWidget(label, r, c * 2)
            self.map_grid.addWidget(combo, r, c * 2 + 1)
            self.map_combos[cls] = combo
        for c in range(cols):
            self.map_grid.setColumnStretch(c * 2 + 1, 1)

    def _set_action(self, cls: str, cmd: str) -> None:
        self.actions[cls] = cmd
        self.settings.setValue("emg_actions", json.dumps(self.actions, ensure_ascii=False))
        self._control_last = ""

    def _on_control_toggled(self, on: bool) -> None:
        self._control_last = ""
        self._stable_label, self._stable_n = "", 0
        if not on:
            return
        if self.model is None or not self.ctx.connected or self.ctx.replaying:
            self.control_chk.setChecked(False)
            self.ctx.notify("Para mover la mano con el EMG hace falta un modelo entrenado y la mano conectada.",
                            error=True)
            return
        if self.ctx.link.port_name != SIMULATOR_PORT:
            answer = QMessageBox.warning(
                self.window(), "Control por EMG",
                "La mano REAL se moverá sola según lo que detecte la IA.\n\n"
                "Prueba antes el modelo sin activar esta opción y ten a mano Parar (Esc), que también "
                "desactiva el control por EMG. ¿Activar?", QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                self.control_chk.setChecked(False)
                return
        if not self.receiving:
            self.set_receiving(True)
        self.ctx.notify("Control por EMG activado: la mano obedece a los movimientos detectados.")

    def _on_decision(self, d) -> None:
        threshold = self.min_conf.value() / 100
        if self.step_stack.currentIndex() == 2 and self.isVisible():
            p = PALETTES[self.ctx.theme]
            confident = d.prob >= threshold
            self.det_lbl.setText(d.label)
            self.det_lbl.setStyleSheet(f"color: {p['text'] if confident else p['muted']};")
            self.det_conf.setText(f"confianza {d.prob * 100:.0f} %" + ("" if confident else " (baja)"))
            pose = POSES.get(d.label, POSES[REST])
            self.det_pic.setPixmap(hand_pixmap(pose, p["muted"], p["accent"], 56))
            self.intensity.setValue(int(d.intensity * 100))
            self.probs.set_data(d.probs, d.index, threshold)
        if self.control_chk.isChecked():
            self._control(d, threshold)

    def _control(self, d, threshold: float) -> None:
        if not self.ctx.connected or self.ctx.replaying:
            self.control_chk.setChecked(False)
            return
        if d.prob < threshold:
            self._stable_label, self._stable_n = "", 0
            return
        if d.label == self._stable_label:
            self._stable_n += 1
        else:
            self._stable_label, self._stable_n = d.label, 1
        if self._stable_n < self.stable.value():
            return
        cmd = self.actions.get(d.label, "")
        now = time.monotonic()
        if not cmd or cmd == self._control_last or now - self._control_time < 0.3:
            return
        self._own_tx = True
        try:
            ok = self.ctx.send_command(cmd)
        finally:
            self._own_tx = False
        if ok:
            self._control_last, self._control_time = cmd, now
            self.action_lbl.setText(f"Último: {d.label} → {cmd}  ({d.prob * 100:.0f} %)")

    # ====================================================== paciente virtual
    def _build_patient_card(self) -> QWidget:
        card, outer = self.card("Paciente virtual")
        card.setFixedWidth(272)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)
        outer.addWidget(self._scroll(body), 1)
        lay.addWidget(_muted("Simula los músculos del antebrazo para probar sin electrodos."))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.patient_group = QButtonGroup(self)
        self.patient_buttons: dict[str, QPushButton] = {}
        for i, name in enumerate(MOVEMENTS):
            b = QPushButton(name)
            b.setObjectName("toggleChip")
            b.setFixedHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setCheckable(True)
            b.setChecked(name == REST)
            self.patient_group.addButton(b, i)
            self.patient_buttons[name] = b
            grid.addWidget(b, i // 2, i % 2)
        self.patient_group.idClicked.connect(lambda i: PATIENT.set_movement(list(MOVEMENTS)[i]))
        lay.addLayout(grid)
        head = QHBoxLayout()
        head.addWidget(_caption("Intensidad"))
        head.addStretch(1)
        self.level_lbl = QLabel()
        self.level_lbl.setObjectName("value")
        head.addWidget(self.level_lbl)
        lay.addLayout(head)
        self.level = QSlider(Qt.Horizontal)
        self.level.setRange(20, 100)
        self.level.setValue(int(PATIENT.level * 100))
        self.level.valueChanged.connect(self._on_level)
        lay.addWidget(self.level)
        self._on_level(self.level.value())
        ch = QHBoxLayout()
        ch.addWidget(_caption("Canales"))
        ch.addStretch(1)
        self.ch_combo = QComboBox()
        for n in CHANNEL_OPTIONS:
            self.ch_combo.addItem(f"{n} canales", n)
        self.ch_combo.setCurrentIndex(max(self.ch_combo.findData(PATIENT.channels), 0))
        self.ch_combo.setToolTip("El equipo usa ahora 2 de los 8 canales del ADS1198.\n"
                                 "Con más canales se distinguen más movimientos.")
        self.ch_combo.currentIndexChanged.connect(lambda _i: setattr(PATIENT, "channels", self.ch_combo.currentData()))
        ch.addWidget(self.ch_combo)
        lay.addLayout(ch)
        self.follow_chk = QCheckBox("Sigue las indicaciones al grabar")
        self.follow_chk.setChecked(True)
        self.follow_chk.setToolTip("Durante la grabación guiada, el paciente virtual hace el movimiento que se pide")
        lay.addWidget(self.follow_chk)
        lay.addStretch(1)
        return card

    def _on_level(self, v: int) -> None:
        PATIENT.level = v / 100
        self.level_lbl.setText(f"{v} %")

    def _patient_follow(self, movement: str) -> bool:
        if self._simulated() and self.follow_chk.isChecked():
            PATIENT.set_movement(movement)
            for name, b in self.patient_buttons.items():
                b.setChecked(name == movement)
        return True

    def _simulated(self) -> bool:
        return bool(getattr(self.ctx, "simulated", False)) or self.ctx.link.port_name == SIMULATOR_PORT

    # ================================================================ estado
    def _update_enabled(self) -> None:
        connected = self.ctx.connected
        guided = self._phase is not None
        self.receive_btn.setEnabled(connected)
        self.rec_btn.setEnabled(guided or (connected and not self.ctx.replaying))
        self.train_btn.setEnabled(not guided)
        self.control_chk.setEnabled(self.model is not None and connected and not self.ctx.replaying)
        self.patient_card.setVisible(self._simulated())

    def on_connection_changed(self, connected: bool, info: str) -> None:
        if not connected:
            self.receiving = False
            self.receive_btn.setChecked(False)
            if self._phase is not None:
                self._stop_guided("Grabación detenida: se ha desconectado.", error=True)
            self.control_chk.setChecked(False)
        self._last_seq = None
        self._update_enabled()

    def on_shown(self) -> None:
        self._dirty = True
        self._update_enabled()

    def on_theme_changed(self, theme: str) -> None:
        p = PALETTES[theme]
        self.plot.setBackground(p["card"])
        for axis in ("left", "bottom"):
            ax = self.plot.getAxis(axis)
            ax.setPen(pg.mkPen(p["border_strong"]))
            ax.setTextPen(pg.mkPen(p["muted"]))
        self.prompt_pic.setPixmap(hand_pixmap(POSES[REST], p["muted"], p["accent"], 68))
        self.det_pic.setPixmap(hand_pixmap(POSES[REST], p["border_strong"], p["subtle"], 56))
        for w in (self.levels, self.probs, self.confusion, self.stepper):
            w.update()
        if self.model is not None:
            self._set_model(self.model)

    # ============================================================ autoguardado
    def _autosave_dataset(self) -> None:
        try:
            self._ai_dir.mkdir(parents=True, exist_ok=True)
            path = self._ai_dir / "datos_actuales.csv"
            if len(self.dataset):
                self.dataset.save_csv(path)
            elif path.exists():
                path.unlink()
        except OSError:
            pass

    def _autosave_model(self) -> None:
        if self.model is None:
            return
        try:
            self._ai_dir.mkdir(parents=True, exist_ok=True)
            self.model.save(self._ai_dir / "modelo_actual.json")
        except OSError:
            pass

    def _load_autosave(self) -> None:
        """Al abrir la app se recuperan los últimos datos y el último modelo."""
        try:
            data = self._ai_dir / "datos_actuales.csv"
            if data.exists():
                self.dataset = EmgDataset.load_csv(data)
                self.fs = self.dataset.fs
            model = self._ai_dir / "modelo_actual.json"
            if model.exists():
                self._set_model(EmgModel.load(model))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
        self._update_data_label()
        if self.model is None:
            self._set_model(None)
