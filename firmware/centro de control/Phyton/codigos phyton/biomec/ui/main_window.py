"""Ventana principal: un espacio de trabajo por ventanas.

┌ rail ─┐┌─────────────────────────────────────────────────────────────────────────┐
│ ▣ BIO ││ [▣] Ensayo                 [Ventanas ▾]   ● Estado  [⏺][⟲][🎤] │ [Parar] │
│       ││     Gráficas, Gemelo digital, Posturas y Consola                         │
│ VENT. ││ [ franja de simulación / barra de reproducción ]                         │
│ ▸ Gem ││ ┌ Dispositivo ┐ ┌ Gráficas ─────────────────┐ ┌ Gemelo digital ───────┐ │
│ ▸ Pos ││ │             │ │                           │ │                       │ │
│ ▸ Grá ││ ├ Posturas ───┤ │                           │ │                       │ │
│ ▸ Ent ││ │             │ └───────────────────────────┘ └───────────────────────┘ │
│ HERR. ││ │             │ ┌ Consola ────────────────────────────────────────────┐ │
│ ▸ Con ││ │             │ │                                                     │ │
│ ...   ││ └─────────────┘ └─────────────────────────────────────────────────────┘ │
│ ☀ ⌨ ⓘ ││                                                      avisos flotantes ↗ │
└───────┘└─────────────────────────────────────────────────────────────────────────┘

Cada parte (gemelo, posturas, gráficas, entrenamiento, visor y analizador EMG, consola, comandos, asistente,
dispositivo) es una ventana (ui/docks.py): se muestra u oculta desde la barra lateral o el menú Ventanas, se arrastra
por su título para recolocarla, agruparla en pestañas o sacarla flotante. Hay espacios predefinidos
(Demostración, Ensayo, Entrenamiento, Todo) y el último reparto se recuerda al cerrar.
Atajos: Ctrl+1…7 ventanas · Ctrl+B barra lateral · Ctrl+K paleta · Ctrl+R grabar · Ctrl+O reproducir.
"""

import json

from PySide6.QtCore import QByteArray, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_VERSION, ORG_NAME
from ..core.gestures import GESTOS
from ..core.postures import posture_command
from ..core.protocol import MessageKind
from ..core.session import default_name, load_session
from ..paths import asset, documents_dir
from .connection_bar import ConnectionBar
from .context import LATENCY_GOOD_MS, LATENCY_LIMIT_MS, AppContext, latency_level
from .dialogs import AboutDialog, ShortcutsDialog, VoiceHelpDialog
from .docks import Dock, Rail
from .icons import app_icon, icon, logo_badge, pixmap
from .palette import CommandPalette, PaletteAction
from .player import PlayerBar, SessionPlayer, fmt_time
from .theme import PALETTES, stylesheet
from .updates import UpdateController, UpdateDialog
from .voice import VoiceController
from .widgets import ElidedLabel, ToastHost, style_titlebar

HEADER_H = 32  # altura común de los controles de la cabecera
RAIL_AUTO_WIDTH = 1380  # por debajo de este ancho la barra lateral se pliega sola (modo automático)
PRESETS = ("Demostración", "Ensayo", "Entrenamiento", "Todo")
CUSTOM = "Espacio personalizado"

# ventanas: clave, título, icono, tamaño mínimo, atajo
WINDOWS = [   # (clave, título, icono, (ancho mínimo, —), atajo): el alto mínimo lo decide el contenido
    ("gemelo", "Gemelo digital", "hand", (270, 0), "Ctrl+1"),
    ("posturas", "Posturas", "grid", (270, 0), "Ctrl+2"),
    ("graficas", "Gráficas", "activity", (420, 0), "Ctrl+3"),
    ("entrenamiento", "Entrenamiento", "brain", (480, 0), "Ctrl+4"),
    ("visor_emg", "Visor EMG", "waveform", (520, 0), "Ctrl+6"),
    ("analizador_emg", "Analizador EMG", "chart", (560, 0), "Ctrl+7"),
    ("consola", "Consola", "terminal", (360, 0), "Ctrl+J"),
    ("comandos", "Comandos", "list", (300, 0), "Ctrl+Mayús+K"),
    ("asistente", "Asistente IA", "sparkles", (320, 0), "Ctrl+I"),
    ("dispositivo", "Dispositivo", "plug", (230, 0), "Ctrl+5"),
]
TOOLS = {"consola", "comandos", "asistente", "dispositivo"}
VOICE_WINDOWS = ("Gemelo digital", "Posturas", "Gráficas", "Entrenamiento")


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, *_ignored, **_kw):
        super().__init__()
        from ..pages import (AssistantPanel, CommandsPanel, ConsolePanel, EmgAnalyzerPanel, EmgPage, EmgViewerPanel,
                             GraphPanel, Hand3DPage)
        self.ctx = ctx
        self.settings = QSettings(ORG_NAME, APP_NAME)
        ctx.theme = self.settings.value("theme", "dark")
        self._preset = self.settings.value("workspace/preset", "Ensayo")
        self._rail_mode = self.settings.value("sidebar/mode", "auto")  # auto | expanded | collapsed | hidden
        self._graph_n = 1
        self._applying = False  # mientras se reparte un espacio predefinido no cuenta como "personalizado"

        self.setWindowTitle(f"{ORG_NAME} · {APP_NAME}")
        self.setWindowIcon(app_icon())
        self.resize(1360, 860)
        self.setMinimumSize(980, 640)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ================= barra lateral =================
        self.rail = Rail(ctx)
        self.rail.clicked.connect(self.toggle_dock)
        self.rail.new_graph.connect(self.new_graph)
        self.rail.collapse_toggled.connect(self._toggle_rail_width)
        self.rail.theme_btn.clicked.connect(self.toggle_theme)
        self.rail.help_btn.clicked.connect(self.show_shortcuts)
        self.rail.about_btn.clicked.connect(self.show_about)
        outer.addWidget(self.rail)

        # ================= zona principal =================
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(22, 16, 22, 14)
        main_layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(0)
        self.page_badge = QLabel()
        self.page_badge.setObjectName("pageBadge")
        self.page_badge.setFixedSize(40, 40)
        self.page_badge.setAlignment(Qt.AlignCenter)
        header.addWidget(self.page_badge, 0, Qt.AlignVCenter)
        header.addSpacing(14)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = ElidedLabel()  # en ventanas estrechas se recorta con "…" (texto completo en el tooltip)
        self.page_subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles, 1)
        header.addSpacing(12)
        self.windows_btn = QPushButton("  Ventanas")
        self.windows_btn.setObjectName("headerMenu")
        self.windows_btn.setFixedHeight(HEADER_H)
        self.windows_btn.setIconSize(QSize(15, 15))
        self.windows_btn.setCursor(Qt.PointingHandCursor)
        self.windows_btn.setToolTip("Mostrar u ocultar ventanas, abrir otra gráfica y elegir un espacio de trabajo")
        self.windows_menu = QMenu(self)
        self.windows_menu.aboutToShow.connect(self._fill_windows_menu)
        self.windows_btn.setMenu(self.windows_menu)
        header.addWidget(self.windows_btn, 0, Qt.AlignVCenter)
        header.addSpacing(16)
        self.voice_caption = ElidedLabel()  # lo que se va oyendo (solo mientras escucha)
        self.voice_caption.setObjectName("voiceCaption")
        self.voice_caption.setMaximumWidth(240)
        self.voice_caption.hide()
        header.addWidget(self.voice_caption, 0, Qt.AlignVCenter)
        header.addSpacing(10)
        # «Actualizar a X»: solo aparece cuando hay una versión nueva publicada
        self.update_btn = QPushButton()
        self.update_btn.setObjectName("updateButton")
        self.update_btn.setIconSize(QSize(15, 15))
        self.update_btn.setFixedHeight(HEADER_H)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self.show_update)
        self.update_box = QWidget()  # botón + su separación: al ocultarlo no deja hueco
        update_row = QHBoxLayout(self.update_box)
        update_row.setContentsMargins(0, 0, 10, 0)
        update_row.addWidget(self.update_btn)
        self.update_box.hide()
        header.addWidget(self.update_box, 0, Qt.AlignVCenter)
        self.status_pill = QPushButton()
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setFixedHeight(HEADER_H)
        self.status_pill.setCursor(Qt.PointingHandCursor)
        self.status_pill.setToolTip("Estado de la conexión. Clic: ventana Dispositivo (Ctrl+5)")
        self.status_pill.clicked.connect(lambda: self.show_dock("dispositivo"))
        header.addWidget(self.status_pill, 0, Qt.AlignVCenter)
        header.addSpacing(10)
        self.rec_btn = QPushButton()
        self.rec_btn.setObjectName("recButton")
        self.rec_btn.setIconSize(QSize(13, 13))
        self.rec_btn.setFixedHeight(HEADER_H)
        self.rec_btn.setCursor(Qt.PointingHandCursor)
        self.rec_btn.clicked.connect(self.toggle_recording)
        header.addWidget(self.rec_btn, 0, Qt.AlignVCenter)
        header.addSpacing(6)
        self.replay_btn = QPushButton()
        self.replay_btn.setObjectName("headerIcon")
        self.replay_btn.setIconSize(QSize(16, 16))
        self.replay_btn.setFixedSize(HEADER_H + 2, HEADER_H)
        self.replay_btn.setCursor(Qt.PointingHandCursor)
        self.replay_btn.setToolTip("Reproducir una sesión grabada: el gemelo, las gráficas y la consola\n"
                                   "se mueven como durante la prueba  (Ctrl+O)")
        self.replay_btn.clicked.connect(lambda: self.open_session())
        header.addWidget(self.replay_btn, 0, Qt.AlignVCenter)
        header.addSpacing(6)
        self.voice_btn = QPushButton()
        self.voice_btn.setObjectName("headerIcon")
        self.voice_btn.setIconSize(QSize(16, 16))
        self.voice_btn.setFixedSize(HEADER_H + 2, HEADER_H)
        self.voice_btn.setCursor(Qt.PointingHandCursor)
        self.voice_btn.setProperty("active", False)
        self.voice_btn.clicked.connect(self.toggle_voice)
        self.voice_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.voice_btn.customContextMenuRequested.connect(lambda _p: self.show_voice_help())
        header.addWidget(self.voice_btn, 0, Qt.AlignVCenter)
        header.addSpacing(14)
        sep = QFrame()
        sep.setObjectName("headerSep")
        sep.setFixedSize(1, 22)
        header.addWidget(sep, 0, Qt.AlignVCenter)
        header.addSpacing(14)
        self.stop_btn = QPushButton("  Parar")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setIconSize(QSize(16, 16))
        self.stop_btn.setFixedHeight(HEADER_H + 2)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setToolTip("PARAR: frena todos los motores (Esc).\n"
                                 "Es una parada por software: no sustituye a una parada de emergencia física.")
        self.stop_btn.clicked.connect(self.emergency_stop)
        header.addWidget(self.stop_btn, 0, Qt.AlignVCenter)
        main_layout.addLayout(header)

        # franja de simulación: fina, con icono, siempre visible en modo simulación
        self.sim_banner = QWidget()
        self.sim_banner.setObjectName("simBanner")
        self.sim_banner.setAttribute(Qt.WA_StyledBackground, True)
        sim_row = QHBoxLayout(self.sim_banner)
        sim_row.setContentsMargins(12, 6, 12, 6)
        sim_row.setSpacing(8)
        self.sim_icon = QLabel()
        sim_row.addWidget(self.sim_icon)
        sim_text = QLabel("Simulación · los comandos van a una mano virtual; la mano real no se mueve")
        sim_text.setObjectName("simText")
        sim_row.addWidget(sim_text, 1)
        main_layout.addWidget(self.sim_banner)
        self.player = SessionPlayer(ctx)
        self.player_bar = PlayerBar(ctx, self.player)
        self.player_bar.setVisible(False)
        main_layout.addWidget(self.player_bar)

        # ================= espacio de trabajo (ventanas) =================
        self.workspace = QMainWindow()
        self.workspace.setObjectName("workspace")
        self.workspace.setDockNestingEnabled(True)
        self.workspace.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks |
                                      QMainWindow.AllowTabbedDocks | QMainWindow.GroupedDragging)
        self.workspace.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        self.workspace.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.workspace.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        placeholder = QWidget()  # sin widget central: las ventanas ocupan todo el espacio
        placeholder.setMaximumSize(0, 0)
        self.workspace.setCentralWidget(placeholder)
        main_layout.addWidget(self.workspace, 1)
        outer.addWidget(main, 1)
        self.setCentralWidget(central)

        # --- contenido de las ventanas
        self.twin = Hand3DPage(ctx)
        self.console = ConsolePanel(ctx)
        self.commands = CommandsPanel(ctx)
        self.assistant = AssistantPanel(ctx)
        self.emg = EmgPage(ctx)
        self.emg_viewer = EmgViewerPanel(ctx)
        self.emg_analyzer = EmgAnalyzerPanel(ctx)
        self.connection_bar = ConnectionBar(ctx.link, ctx)
        self.connection_bar.setObjectName("transparent")  # la ventana ya es la tarjeta
        self.graph_panels: dict[str, GraphPanel] = {}
        self.docks: dict[str, Dock] = {}
        widgets = {
            "gemelo": self.twin.twin_widget, "posturas": self.twin.posture_widget,
            "entrenamiento": self.emg, "visor_emg": self.emg_viewer, "analizador_emg": self.emg_analyzer,
            "consola": self.console, "comandos": self.commands, "asistente": self.assistant,
            "dispositivo": self.connection_bar,
        }
        self.rail.add_section("Ventanas")
        for key, title, icon_name, min_size, shortcut in WINDOWS:
            if key == "graficas":
                self._add_graph("graficas", None, "Gráficas", min_size)
            else:
                self._add_dock(key, title, icon_name, widgets[key], min_size,
                               plain=key in ("entrenamiento", "visor_emg", "analizador_emg"), top=key == "dispositivo")
            if key == "entrenamiento":
                self.rail.add_section("EMG")
            elif key == "consola":
                self.rail.add_section("Herramientas")
            self.rail.add_entry(key, title, icon_name, tool=key in TOOLS, shortcut=shortcut)
            if key == "graficas":
                self.rail.add_new_graph()
            seq = shortcut.replace("Mayús", "Shift")
            QShortcut(QKeySequence(seq), self, activated=lambda k=key: self.toggle_dock(k, focus=True))
        self.docks["gemelo"].visibilityChanged.connect(lambda v: v and self.twin.on_shown())

        ctx.prefill_command.connect(lambda _t: self.show_dock("consola"))
        ctx.analyze_emg_file.connect(lambda _path: self.show_dock("analizador_emg"))
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.toggle_rail)
        QShortcut(QKeySequence("Ctrl+Shift+G"), self, activated=self.new_graph)
        self.palette = CommandPalette(self)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.palette.open_palette)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.palette.open_palette)
        QShortcut(QKeySequence("Esc"), self, activated=self.emergency_stop)
        QShortcut(QKeySequence("F1"), self, activated=self.show_shortcuts)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.toggle_recording)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=lambda: self.open_session())
        self.space_shortcut = QShortcut(QKeySequence("Space"), self, activated=self.player.toggle)
        self.space_shortcut.setEnabled(False)  # solo mientras se reproduce una sesión
        for n in range(1, len(GESTOS) + 1):
            QShortcut(QKeySequence(f"Alt+{n}"), self, activated=lambda n=n: self.send_gesture(n))
        self.toasts = ToastHost(central, self.workspace, lambda: self.ctx.theme, top=6)
        ctx.toast.connect(self.toasts.show)

        # control por voz (sin internet)
        self.voice = VoiceController(ctx, list(VOICE_WINDOWS))
        self.voice.listening_changed.connect(lambda _l: self._update_voice_button())
        self.voice.ready.connect(self._on_voice_ready)
        self.voice.partial.connect(lambda text: self.voice_caption.setText(f"«{text}…»"))
        self.voice.heard.connect(self._on_voice_heard)
        self.voice.error.connect(self._on_voice_error)
        self._voice_real_ok = False
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_voice)

        # actualizaciones (GitHub Releases): solo en la app instalada con el instalador
        self.updates = UpdateController()
        self.updates.found.connect(self._on_update_found)
        self.updates.up_to_date.connect(self._on_up_to_date)
        self.updates.failed.connect(self._on_update_failed)
        self._manual_update_check = False
        if self.updates.installed and self.updates.auto:
            QTimer.singleShot(4000, lambda: self.check_updates(manual=False))

        self.hand_status_lbl = QLabel()
        self.latency_lbl = QLabel()
        for w in (self.hand_status_lbl, self.latency_lbl):
            w.setContentsMargins(10, 0, 10, 0)
            self.statusBar().addPermanentWidget(w)
        self.latency_lbl.setToolTip(
            "Tiempo entre enviar un comando y recibir su respuesta (ida y vuelta por USB y ESP-NOW).\n"
            f"Verde < {LATENCY_GOOD_MS} ms · ámbar ≤ {LATENCY_LIMIT_MS} ms · rojo por encima.\n"
            "Referencia: Farrell y Weir (2007) sitúan el retardo óptimo del control completo\n"
            "de una prótesis mioeléctrica en 100-125 ms; la comunicación es solo una parte.")
        ctx.hand_status_changed.connect(lambda *_: self._update_device_status())
        ctx.latency_measured.connect(lambda *_: self._update_device_status())

        self.connection_bar.mode_changed.connect(self._on_mode_changed)
        ctx.link.connection_changed.connect(lambda *_: self._update_status_pill())
        ctx.link.connection_changed.connect(lambda connected, _i: connected and self.player.close())
        self.player.state_changed.connect(self._on_player_state)
        ctx.recording_changed.connect(lambda _r: self._update_rec_button())
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(500)
        self._rec_timer.timeout.connect(self._update_rec_button)
        ctx.message.connect(self._status_from_message)
        ctx.theme_changed.connect(lambda _t: self.apply_theme())
        self.apply_theme()
        self._on_mode_changed(self.connection_bar.simulated)
        self._restore_workspace()
        self._apply_rail_mode()
        self.statusBar().showMessage("Listo.  Ctrl+K: paleta de comandos · F1: atajos de teclado")

    # ================================================================ ventanas
    def _add_dock(self, key: str, title: str, icon_name: str, widget: QWidget, min_size, plain: bool = False,
                  top: bool = False) -> Dock:
        dock = Dock(key, title, icon_name, widget, self.ctx, min_size, plain=plain, top=top)
        self.workspace.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.hide()
        self.docks[key] = dock
        dock.toggleViewAction().toggled.connect(lambda on, k=key: self._on_dock_toggled(k, on))
        # lo que hace el usuario con la ventana (menú, cerrar, mover, sacar) convierte el espacio en personalizado
        dock.toggleViewAction().triggered.connect(lambda _c: self._mark_custom())
        dock.closed.connect(lambda _k: self._mark_custom())
        dock.dockLocationChanged.connect(lambda _a: self._mark_custom())
        dock.topLevelChanged.connect(lambda _f: self._mark_custom())
        return dock

    def _mark_custom(self) -> None:
        if not self._applying and self._preset != CUSTOM:
            self._set_preset(CUSTOM)

    def _add_graph(self, key: str, keys, name: str, min_size=(440, 240)) -> Dock:
        from ..pages import GraphPanel
        panel = GraphPanel(self.ctx, keys, name)
        panel.open_in_new.connect(lambda ks: self.new_graph(ks))
        panel.keys_changed.connect(self._save_graphs)
        self.graph_panels[key] = panel
        dock = self._add_dock(key, name, "activity", panel, min_size)
        if key != "graficas":
            dock.closed.connect(self._remove_graph)
        return dock

    def _remove_graph(self, key: str) -> None:
        dock = self.docks.pop(key, None)
        panel = self.graph_panels.pop(key, None)
        if dock is None:
            return
        self.workspace.removeDockWidget(dock)
        dock.deleteLater()
        if panel is not None:
            panel.timer.stop()
        self._save_graphs()
        self._update_header()

    def new_graph(self, keys=None) -> None:
        """Otra ventana de Gráficas, flotante, con las señales elegidas (o pedidas en un diálogo)."""
        from ..pages.telemetry import SignalPicker
        if not keys:
            dialog = SignalPicker(self, self.ctx, [], "Señales de la gráfica nueva")
            if dialog.exec() != QDialog.Accepted or not dialog.keys():
                return
            keys = dialog.keys()
        self._graph_n += 1
        key, name = f"grafica{self._graph_n}", f"Gráfica {self._graph_n}"
        dock = self._add_graph(key, list(keys), name)
        dock.setFloating(True)
        dock.resize(640, 360)
        anchor = self.workspace.mapToGlobal(self.workspace.rect().center())
        dock.move(anchor.x() - 320 + 24 * (self._graph_n % 5), anchor.y() - 180 + 24 * (self._graph_n % 5))
        dock.show()
        dock.raise_()
        self._save_graphs()
        self._mark_custom()
        self._update_header()

    def _on_dock_toggled(self, key: str, visible: bool) -> None:
        self.rail.set_checked(key, visible)
        self._update_header()

    def show_dock(self, key: str, focus: bool = False) -> None:
        dock = self.docks.get(key)
        if dock is None:
            return
        dock.show()
        dock.raise_()
        if dock.isFloating():
            dock.activateWindow()
        if focus:
            self._focus_dock(key)

    def toggle_dock(self, key: str, focus: bool = False) -> None:
        dock = self.docks.get(key)
        if dock is None:
            return
        if dock.isHidden() or dock.behind_tab():
            self.show_dock(key, focus)
            self._mark_custom()
        else:
            dock.close()

    def show_dock_by_title(self, title: str) -> None:
        for key, dock in self.docks.items():
            if dock.windowTitle() == title:
                self.show_dock(key)
                return

    def _focus_dock(self, key: str) -> None:
        if key == "consola":
            self.console.focus_input()
        elif key == "comandos":
            self.commands.focus_search()
        elif key == "asistente":
            self.assistant.focus_input()

    def _visible_titles(self) -> list[str]:
        return [d.windowTitle() for d in self.docks.values() if not d.isHidden()]

    def _update_header(self) -> None:
        titles = self._visible_titles()
        self.page_title.setText(self._preset)
        text = (", ".join(titles[:-1]) + " y " + titles[-1]) if len(titles) > 1 else (titles[0] if titles else
                                                                                       "Sin ventanas: ábrelas desde la barra lateral o el menú Ventanas")
        self.page_subtitle.setText(text)
        self.page_subtitle.setToolTip("\n".join(titles))

    def _fill_windows_menu(self) -> None:
        menu = self.windows_menu
        menu.clear()
        for key, dock in self.docks.items():
            action = dock.toggleViewAction()
            action.setText(dock.windowTitle())
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction("Nueva gráfica…  (Ctrl+Mayús+G)", lambda: self.new_graph())
        menu.addSeparator()
        spaces = menu.addMenu("Espacio de trabajo")
        for name in PRESETS:
            act = spaces.addAction(name, lambda n=name: self.apply_preset(n))
            act.setCheckable(True)
            act.setChecked(name == self._preset)
        menu.addAction("Barra lateral: mostrar / ocultar  (Ctrl+B)", self.toggle_rail)

    # ------------------------------------------------------------ espacios
    def apply_preset(self, name: str) -> None:
        """Reparte las ventanas según un espacio predefinido.

        Las gráficas extra («Nueva gráfica») no se tocan si están flotando; si estaban acopladas se ocultan
        (se recuperan desde el menú Ventanas)."""
        ws = self.workspace
        D = {k: d for k, d in self.docks.items() if k in dict.fromkeys(w[0] for w in WINDOWS)}
        self._applying = True
        for key, dock in self.docks.items():
            if key not in D and not dock.isFloating():
                dock.hide()
        for d in D.values():
            d.setFloating(False)
            ws.removeDockWidget(d)
        L, R, H, V = Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea, Qt.Horizontal, Qt.Vertical
        # Todo va en dos columnas: la izquierda (Dispositivo arriba + otra ventana) y la derecha, con divisiones
        # anidadas (la consola va dentro de la columna derecha, no en el área inferior: así se puede dar altura).
        show: list[str]
        tall = ws.height() or 700
        dev_h = D["dispositivo"].sizeHint().height()
        if name == "Demostración":
            ws.addDockWidget(L, D["dispositivo"])
            ws.addDockWidget(L, D["posturas"])
            ws.addDockWidget(R, D["gemelo"])
            show = ["dispositivo", "posturas", "gemelo"]
            widths = ([D["posturas"], D["gemelo"]], [340, 900])
            heights = ([D["dispositivo"], D["posturas"]], [dev_h, tall])
        elif name == "Entrenamiento":
            ws.addDockWidget(L, D["dispositivo"])
            ws.addDockWidget(L, D["gemelo"])
            ws.addDockWidget(R, D["entrenamiento"])
            ws.splitDockWidget(D["entrenamiento"], D["consola"], V)
            ws.tabifyDockWidget(D["entrenamiento"], D["visor_emg"])       # las herramientas EMG, en pestañas
            ws.tabifyDockWidget(D["visor_emg"], D["analizador_emg"])
            show = ["dispositivo", "gemelo", "entrenamiento", "consola", "visor_emg", "analizador_emg"]
            widths = ([D["gemelo"], D["entrenamiento"]], [360, 900])
            heights = ([D["dispositivo"], D["gemelo"], D["entrenamiento"], D["consola"]], [dev_h, tall, tall, 170])
        elif name == "Todo":
            ws.addDockWidget(L, D["dispositivo"])
            ws.addDockWidget(L, D["posturas"])
            ws.addDockWidget(R, D["graficas"])
            ws.splitDockWidget(D["graficas"], D["gemelo"], H)        # primero las columnas…
            ws.splitDockWidget(D["graficas"], D["consola"], V)       # …y la consola solo bajo Gráficas
            ws.splitDockWidget(D["gemelo"], D["comandos"], V)
            ws.tabifyDockWidget(D["comandos"], D["asistente"])
            ws.tabifyDockWidget(D["graficas"], D["entrenamiento"])  # las dos grandes, en pestañas
            show = ["dispositivo", "posturas", "graficas", "gemelo", "comandos", "asistente", "consola", "entrenamiento"]
            widths = ([D["posturas"], D["graficas"], D["gemelo"]], [250, 620, 420])
            heights = ([D["dispositivo"], D["posturas"], D["graficas"], D["consola"]], [dev_h, tall, tall, 200])
        else:  # Ensayo
            name = "Ensayo"
            ws.addDockWidget(L, D["dispositivo"])
            ws.addDockWidget(L, D["posturas"])
            ws.addDockWidget(R, D["graficas"])
            ws.splitDockWidget(D["graficas"], D["consola"], V)
            ws.splitDockWidget(D["graficas"], D["gemelo"], H)
            show = ["dispositivo", "posturas", "graficas", "gemelo", "consola"]
            widths = ([D["posturas"], D["graficas"], D["gemelo"]], [250, 580, 480])
            heights = ([D["dispositivo"], D["posturas"], D["graficas"], D["consola"]], [dev_h, tall, tall, 180])
        self._preset = name
        for key in D:   # las que no se ven siguen en el reparto (ocultas) para poder abrirlas después
            if key not in show:
                ws.addDockWidget(R, D[key])
                D[key].hide()
        for key in show:
            D[key].show()
        if name == "Todo":
            D["graficas"].raise_()
            D["comandos"].raise_()
        elif name == "Entrenamiento":
            D["entrenamiento"].raise_()
        self._pending_sizes = (widths, heights)
        self._size_docks()
        QTimer.singleShot(0, self._size_docks)
        self._applying = False
        self._set_preset(name)
        self._update_header()

    def _size_docks(self) -> None:
        sizes = getattr(self, "_pending_sizes", None)
        if not sizes:
            return
        widths, heights = sizes
        if widths:
            self.workspace.resizeDocks(widths[0], widths[1], Qt.Horizontal)
        if heights:
            self.workspace.resizeDocks(heights[0], heights[1], Qt.Vertical)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._size_docks)  # el reparto de tamaños necesita la ventana ya en pantalla

    def _set_preset(self, name: str) -> None:
        self._preset = name
        self.settings.setValue("workspace/preset", name)
        self._update_header()

    def _restore_workspace(self) -> None:
        """El reparto de la última vez (incluidas las gráficas extra); si no hay o falla, el espacio Ensayo."""
        try:
            extra = json.loads(self.settings.value("workspace/graphs", "[]"))
        except (TypeError, ValueError):
            extra = []
        for cfg in extra:
            key = cfg.get("clave", "")
            if key.startswith("grafica") and key not in self.docks:
                n = int(key[7:]) if key[7:].isdigit() else self._graph_n + 1
                self._graph_n = max(self._graph_n, n)
                self._add_graph(key, cfg.get("claves") or None, cfg.get("nombre", f"Gráfica {n}"))
                self.graph_panels[key].apply_config(cfg)
        main_cfg = self.settings.value("workspace/main_graph", "")
        if main_cfg:
            try:
                self.graph_panels["graficas"].apply_config(json.loads(main_cfg))
            except (TypeError, ValueError):
                pass
        state = self.settings.value("workspace/state")
        ok = False
        self._applying = True
        if isinstance(state, QByteArray) and not state.isEmpty():
            ok = self.workspace.restoreState(state)
        self._applying = False
        if not ok or not self._visible_titles():
            self.apply_preset(self._preset if self._preset in PRESETS else "Ensayo")
        else:
            for key, dock in self.docks.items():
                self.rail.set_checked(key, not dock.isHidden())
            self._update_header()

    def _save_graphs(self) -> None:
        extra = [dict(self.graph_panels[k].config(), clave=k) for k in self.graph_panels if k != "graficas"]
        self.settings.setValue("workspace/graphs", json.dumps(extra, ensure_ascii=False))
        self.settings.setValue("workspace/main_graph", json.dumps(self.graph_panels["graficas"].config(),
                                                                   ensure_ascii=False))

    def _save_workspace(self) -> None:
        self.settings.setValue("workspace/state", self.workspace.saveState())
        self.settings.setValue("workspace/preset", self._preset)
        self._save_graphs()

    # --------------------------------------------------------- barra lateral
    def _apply_rail_mode(self) -> None:
        mode = self._rail_mode
        self.rail.setVisible(mode != "hidden")
        if mode == "auto":
            self.rail.set_expanded(self.width() >= RAIL_AUTO_WIDTH)
        elif mode in ("expanded", "collapsed"):
            self.rail.set_expanded(mode == "expanded")
        self.settings.setValue("sidebar/mode", mode)

    def _toggle_rail_width(self) -> None:
        self._rail_mode = "collapsed" if self.rail.expanded else "expanded"
        self._apply_rail_mode()

    def toggle_rail(self) -> None:
        self._rail_mode = "auto" if self._rail_mode == "hidden" else "hidden"
        self._apply_rail_mode()

    # ----------------------------------------------------------------- tema
    def toggle_theme(self) -> None:
        self.ctx.set_theme("light" if self.ctx.theme == "dark" else "dark")
        self.settings.setValue("theme", self.ctx.theme)

    def apply_theme(self) -> None:
        theme = self.ctx.theme
        p = PALETTES[theme]
        self._apply_qt_palette(p)
        self.setStyleSheet(stylesheet(theme))
        self.rail.badge.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['accent']}, stop:1 #1e3a8a);"
            "border-radius: 10px;")
        self.rail.badge.setPixmap(logo_badge(27, "#ffffff", asset("biomec_logo_dark.png")))
        self.rail.apply_theme(theme)
        style_titlebar(self, theme)
        self.sim_icon.setPixmap(pixmap("flask", p["sim_text"], 15))
        self.page_badge.setPixmap(pixmap("layout", p["accent_text"], 20))
        self.windows_btn.setIcon(icon("layout", p["muted"], 15))
        self.stop_btn.setIcon(icon("octagon", "#ffffff", 16))
        self.replay_btn.setIcon(icon("history", p["muted"], 16))
        self.update_btn.setIcon(icon("download", p["accent_text"], 15))
        self._update_voice_button()
        self._update_rec_button()
        self._update_status_pill()

    @staticmethod
    def _apply_qt_palette(p: dict) -> None:
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication

        pal = QPalette()
        roles = {
            QPalette.Window: p["bg"], QPalette.WindowText: p["text"], QPalette.Base: p["inset"],
            QPalette.AlternateBase: p["card"], QPalette.Text: p["text"], QPalette.Button: p["card"],
            QPalette.ButtonText: p["text"], QPalette.Highlight: p["accent"], QPalette.HighlightedText: "#ffffff",
            QPalette.ToolTipBase: p["card"], QPalette.ToolTipText: p["text"], QPalette.PlaceholderText: p["subtle"],
        }
        for role, color in roles.items():
            pal.setColor(role, QColor(color))
        QApplication.instance().setPalette(pal)

    # ---------------------------------------------------------- estado
    def _on_mode_changed(self, simulated: bool) -> None:
        self.ctx.set_simulated(simulated)
        self.sim_banner.setVisible(simulated and not self.ctx.replaying)
        suffix = "  —  SIMULACIÓN" if simulated else ""
        self.setWindowTitle(f"{ORG_NAME} · {APP_NAME}{suffix}")
        self._update_status_pill()

    def _update_status_pill(self) -> None:
        p = PALETTES[self.ctx.theme]
        link, sim = self.ctx.link, self.connection_bar.simulated
        if self.ctx.replaying:
            text, fg, bg = "●  Reproducción", p["accent_text"], p["accent_soft"]
        elif link.is_connected and sim:
            text, fg, bg = "●  Simulación", p["sim_text"], p["sim_bg"]
        elif link.is_connected:
            text, fg, bg = f"●  Conectado · {link.port_name}", p["ok"], p["ok_soft"]
        else:
            text, fg, bg = "●  Desconectado", p["muted"], p["hover"]
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(f"QPushButton {{ color: {fg}; background: {bg}; border: 0; "
                                       f"border-radius: {HEADER_H // 2}px; padding: 0 14px; font-weight: 600; "
                                       "font-size: 9pt; }}")
        self.stop_btn.setEnabled(link.is_connected)
        self._update_device_status()

    def _update_device_status(self) -> None:
        """Barra de estado: estado de la mano (además del puente) y latencia de los comandos."""
        if not hasattr(self, "latency_lbl"):
            return
        p = PALETTES[self.ctx.theme]
        status, rate = self.ctx.hand_status, self.ctx.data_rate
        who = "Sesión grabada" if self.ctx.replaying else "Mano simulada" if self.connection_bar.simulated else "Mano"
        if status == "online":
            color, text = p["ok"], f"{who}: en línea" + (f" · {rate:.0f} Hz" if rate else "")
        elif status == "silent":
            color, text = p["warn"], f"{who}: sin respuesta"
        else:
            color, text = p["subtle"], f"{who}: —"
        self.hand_status_lbl.setText(f'<span style="color:{color}">●</span>&nbsp; {text}')
        self.hand_status_lbl.setToolTip(
            "En línea: llegan datos de la mano (telemetría o respuestas).\n"
            "Sin respuesta: el puente está conectado pero la mano no contesta "
            "(¿está encendida? ¿mismo canal ESP-NOW?)." if status != "offline" else "No hay conexión.")
        if self.ctx.latencies:
            last, avg = self.ctx.latencies[-1], self.ctx.avg_latency
            color = p[latency_level(last)]
            self.latency_lbl.setText(f'Latencia <span style="color:{color}"><b>{last:.0f} ms</b></span>'
                                     f'&nbsp;·&nbsp;media {avg:.0f} ms')
        else:
            self.latency_lbl.setText(f'<span style="color:{p["subtle"]}">Latencia —</span>')

    # ------------------------------------------------- sesiones grabadas
    def toggle_recording(self) -> None:
        if self.ctx.recording:
            self.ctx.stop_recording()
            return
        if self.ctx.replaying:
            self.ctx.notify("No se puede grabar mientras se reproduce una sesión.", error=True)
            return
        sim = self.connection_bar.simulated
        meta = {"app": APP_NAME, "version": APP_VERSION, "simulacion": sim, "puerto": self.ctx.link.port_name}
        self.ctx.start_recording(documents_dir("Sesiones") / default_name(sim), meta)

    def _update_rec_button(self) -> None:
        p = PALETTES[self.ctx.theme]
        recording = self.ctx.recording
        if recording:
            self.rec_btn.setText(f"  REC {fmt_time(self.ctx.recorder.elapsed)[:-2]}")
            self.rec_btn.setIcon(icon("stop", p["error"], 13))
            self.rec_btn.setToolTip(f"Grabando en {self.ctx.recorder.path}\nPulsa para detener  (Ctrl+R)")
            self.rec_btn.setMinimumWidth(0)
            self.rec_btn.setMaximumWidth(220)
            if not self._rec_timer.isActive():
                self._rec_timer.start()
        else:
            self.rec_btn.setText("")
            self.rec_btn.setIcon(icon("record", p["error"], 13))
            self.rec_btn.setFixedWidth(HEADER_H + 2)
            self.rec_btn.setToolTip("Grabar la sesión: guarda comandos, respuestas, telemetría y EMG con su instante\n"
                                    "para volver a verla después en la app  (Ctrl+R)")
            self._rec_timer.stop()
        if self.rec_btn.property("recording") != recording:
            self.rec_btn.setProperty("recording", recording)
            self.rec_btn.style().unpolish(self.rec_btn)
            self.rec_btn.style().polish(self.rec_btn)

    def open_session(self, path: str | None = None) -> None:
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Reproducir una sesión grabada", str(documents_dir("Sesiones")),
                                                  "Sesiones BIOMEC (*.jsonl);;Todos los archivos (*)")
            if not path:
                return
        try:
            session = load_session(path)
        except (OSError, ValueError, UnicodeDecodeError) as error:
            QMessageBox.warning(self, "No se pudo abrir la sesión", str(error))
            return
        if not session.events:
            QMessageBox.information(self, "Sesión vacía", f"{session.path.name} no contiene mensajes.")
            return
        if self.ctx.connected:
            answer = QMessageBox.question(
                self, "Reproducir sesión",
                "Para reproducir una sesión se desconecta la mano: mientras dure no se pueden enviar comandos.\n\n"
                "¿Continuar?")
            if answer != QMessageBox.Yes:
                return
            self.ctx.link.disconnect()
        if self.ctx.recording:
            self.ctx.stop_recording()
        self.player.load(session)
        self.player_bar.show_session(session)
        self.player.play()
        self.ctx.notify(f"Reproduciendo {session.path.name} ({fmt_time(session.duration)}). "
                        "Espacio: pausa · clic en la barra de tiempo: saltar.")

    def open_sessions_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(documents_dir("Sesiones"))))

    def _on_player_state(self, state: str) -> None:
        replaying = state != "closed"
        self.space_shortcut.setEnabled(replaying)
        self.sim_banner.setVisible(self.connection_bar.simulated and not replaying)
        self.rec_btn.setEnabled(not replaying)
        self._update_status_pill()
        if state == "closed":
            self.ctx.notify("Reproducción cerrada.")

    # ---------------------------------------------------------- control por voz
    def toggle_voice(self) -> None:
        if self.voice.listening:
            self.voice.stop()
            return
        if not self.voice.model_ready:
            answer = QMessageBox.question(
                self, "Control por voz",
                "El control por voz funciona sin internet, pero la primera vez hay que descargar el modelo de "
                "reconocimiento en español (40 MB, una sola vez).\n\n¿Descargarlo ahora?")
            if answer == QMessageBox.Yes:
                self._download_voice_model()
            return
        if self.ctx.connected and not self.connection_bar.simulated and not self._voice_real_ok:
            answer = QMessageBox.warning(
                self, "Control por voz",
                "La mano REAL obedecerá las órdenes de voz.\n\nDi «para» o pulsa Esc para detenerla. ¿Activar?",
                QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self._voice_real_ok = True
        self.voice.start()

    def _download_voice_model(self) -> None:
        from PySide6.QtWidgets import QProgressDialog
        dialog = QProgressDialog("Descargando el modelo de voz en español…", "Cancelar", 0, 100, self)
        dialog.setWindowTitle("Control por voz")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setValue(0)
        dialog.canceled.connect(self.voice.cancel_download)

        def progress(done: int, total: int) -> None:
            if total:
                dialog.setValue(int(done * 100 / total))
                dialog.setLabelText(f"Descargando el modelo de voz en español…  {done / 1e6:.0f} / {total / 1e6:.0f} MB")

        def finished(error: str) -> None:
            self.voice.download_progress.disconnect(progress)
            self.voice.download_done.disconnect(finished)
            dialog.close()
            if error:
                if "cancelada" not in error:
                    self.ctx.notify(f"No se pudo descargar el modelo de voz: {error}", error=True)
                return
            self.ctx.notify("Modelo de voz listo.", toast=True)
            self.toggle_voice()

        self.voice.download_progress.connect(progress)
        self.voice.download_done.connect(finished)
        self.voice.download()

    def _update_voice_button(self) -> None:
        if not hasattr(self, "voice"):
            return
        p = PALETTES[self.ctx.theme]
        on = self.voice.listening
        self.voice_btn.setIcon(icon("mic", p["accent_text"] if on else p["muted"], 16))
        self.voice_btn.setToolTip("Escuchando órdenes de voz: clic para dejar de escuchar  (Ctrl+M)" if on else
                                  "Control por voz: di «abre la mano», «pinza», «para»…  (Ctrl+M)\n"
                                  "Clic derecho: lista de órdenes")
        self.voice_caption.setVisible(on)
        if not on:
            self.voice_caption.setText("")
        else:
            self.voice_caption.setText("escuchando…")
        if self.voice_btn.property("active") != on:
            self.voice_btn.setProperty("active", on)
            self.voice_btn.style().unpolish(self.voice_btn)
            self.voice_btn.style().polish(self.voice_btn)

    def _on_voice_heard(self, heard) -> None:
        action = heard.action
        if action is None:
            self.voice_caption.setText(f"«{heard.text}» ✕")
            self.statusBar().showMessage(f"Voz: «{heard.text}» — {heard.reason}", 4000)
            return
        self.voice_caption.setText(f"«{heard.text}»")
        if action.is_stop:
            self.emergency_stop()
        elif action.kind == "command":
            if not self.ctx.connected:
                self.ctx.notify(f"«{heard.text}»: conecta primero la mano o la simulación.", error=True)
                return
            if not self.ctx.send_command(action.value):
                return
        elif action.kind == "page":
            self.show_dock_by_title(action.value)
        elif action.kind == "app":
            if (action.value == "grabar") != self.ctx.recording:
                self.toggle_recording()
        self.toasts.show(f"«{heard.text}»  →  {action.label}", "voice")

    def _on_voice_ready(self) -> None:
        if not getattr(self, "_voice_intro_shown", False):  # la explicación, solo la primera vez
            self._voice_intro_shown = True
            self.toasts.show("Te escucho: di una orden, p. ej. «abre la mano» o «pinza». «Para» detiene la mano. "
                             "Clic derecho en el micrófono: todas las órdenes.", "voice")

    def _on_voice_error(self, text: str) -> None:
        self.voice.stop()
        self.ctx.notify(f"Control por voz: {text}", error=True)

    def show_voice_help(self) -> None:
        VoiceHelpDialog(self, [p.nombre for p in self.ctx.postures.items]).exec()

    # ---------------------------------------------------------- acciones
    def emergency_stop(self) -> None:
        if not self.ctx.connected:
            self.ctx.notify("PARAR: no hay ninguna mano conectada.", error=True)
            return
        self.ctx.send_command("PARAR")

    def send_gesture(self, n: int) -> None:
        if not self.ctx.connected:
            self.ctx.notify(f"Gesto {n}: conecta primero la mano o la simulación.", error=True)
            return
        self.ctx.send_command(f"GESTO {n}")

    def show_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def palette_actions(self) -> list[PaletteAction]:
        """Todo lo que se puede hacer desde la paleta de comandos (Ctrl+K)."""
        ctx, bar = self.ctx, self.connection_bar
        on = ctx.connected
        acts: list[PaletteAction] = []
        acts.append(PaletteAction("Parar motores", "Esc", "octagon", self.emergency_stop, "stop parada emergencia", on))
        for i, g in enumerate(GESTOS, start=1):
            acts.append(PaletteAction(f"Gesto {i} · {g.nombre}", f"Alt+{i}", "hand",
                                      lambda n=i: self.send_gesture(n), "gesto agarre", on))
        for g in ctx.postures.items:
            acts.append(PaletteAction(f"Postura · {g.nombre}", posture_command(g), "hand",
                                      lambda c=posture_command(g): ctx.send_command(c), "postura personalizada", on))
        acts.append(PaletteAction("Nueva postura personalizada…", "Editor de posturas", "plus",
                                  lambda: (self.show_dock("posturas"), self.twin.new_posture()),
                                  "crear postura agarre editor"))
        for key, dock in self.docks.items():
            hidden = dock.isHidden()
            acts.append(PaletteAction(f"{'Mostrar' if hidden else 'Ocultar'} ventana · {dock.windowTitle()}",
                                      "Ventana", dock.icon_name, lambda k=key: self.toggle_dock(k, focus=True),
                                      "ventana abrir cerrar mostrar ocultar"))
        acts.append(PaletteAction("Nueva gráfica…", "Ctrl+Mayús+G", "activity", lambda: self.new_graph(),
                                  "grafica ventana señales nueva"))
        for name in PRESETS:
            acts.append(PaletteAction(f"Espacio de trabajo · {name}", "Ventanas", "layout",
                                      lambda n=name: self.apply_preset(n), "espacio reparto ventanas preset"))
        acts.append(PaletteAction("Barra lateral: mostrar / ocultar", "Ctrl+B", "sidebar", self.toggle_rail,
                                  "barra lateral menu plegar"))
        acts += [
            PaletteAction("Detener grabación" if ctx.recording else "Grabar sesión", "Ctrl+R", "record",
                          self.toggle_recording, "grabar sesion rec registro", not ctx.replaying),
            PaletteAction("Reproducir una sesión grabada…", "Ctrl+O", "history", lambda: self.open_session(),
                          "reproducir sesion grabacion abrir"),
            PaletteAction("Abrir la carpeta de sesiones", "Documentos", "folder", self.open_sessions_folder,
                          "carpeta sesiones grabaciones"),
            PaletteAction("Dejar de escuchar órdenes de voz" if self.voice.listening else "Control por voz",
                          "Ctrl+M", "mic", self.toggle_voice, "voz microfono hablar escuchar"),
            PaletteAction("Órdenes de voz disponibles", "Ayuda", "mic", self.show_voice_help, "voz lista ordenes"),
        ]
        if ctx.replaying:
            acts.append(PaletteAction("Cerrar la reproducción", "Sesión", "close", self.player.close, "salir"))
        acts += [
            PaletteAction("Desconectar" if on else "Conectar", "Dispositivo", "power", bar.toggle,
                          "conexion puerto usb"),
            PaletteAction("Cambiar a mano real" if bar.simulated else "Cambiar a simulación", "Dispositivo",
                          "plug" if bar.simulated else "flask", lambda: bar.set_simulated(not bar.simulated),
                          "modo simulador real"),
            PaletteAction("Activar telemetría", "STREAM 1", "zap", lambda: ctx.send_command("STREAM 1"),
                          "datos graficas", on),
            PaletteAction("Desactivar telemetría", "STREAM 0", "zap", lambda: ctx.send_command("STREAM 0"),
                          "datos graficas", on),
            PaletteAction("Sincronizar estado de la mano", "ESTADO", "refresh", lambda: ctx.send_command("ESTADO"),
                          "estado", on),
            PaletteAction("Modo demo (recorrer gestos)", "AUTO", "play", lambda: ctx.send_command("AUTO"),
                          "auto exposicion bucle demostracion", on),
            PaletteAction("Modo manual", "MANUAL", "pause", lambda: ctx.send_command("MANUAL"), "manual", on),
        ]
        if self.twin.model is not None:
            from ..pages.hand3d import CAMERAS
            for name in CAMERAS:
                acts.append(PaletteAction(f"Vista 3D: {name}", "Gemelo digital", "camera",
                                          lambda n=name: (self.show_dock("gemelo"), self.twin.set_camera(n)),
                                          "camara"))
        quick = {"PARAR", "AUTO", "MANUAL", "ESTADO", "GESTO"}
        for cmd in ctx.catalog:
            if cmd.name in quick:
                continue
            if cmd.args:
                acts.append(PaletteAction(cmd.usage, f"{cmd.category} · escribir", "terminal",
                                          lambda c=cmd: ctx.prefill_command.emit(c.name + " "), cmd.description))
            else:
                acts.append(PaletteAction(cmd.name, f"{cmd.category} · enviar", "send",
                                          lambda c=cmd: ctx.send_command(c.name), cmd.description, on))
        acts += [
            PaletteAction("Preguntar al asistente IA", "Ctrl+I", "sparkles",
                          lambda: self.show_dock("asistente", focus=True), "ia claude chat ayuda asistente"),
            PaletteAction("Cambiar a tema " + ("claro" if ctx.theme == "dark" else "oscuro"), "Apariencia",
                          "sun" if ctx.theme == "dark" else "moon", self.toggle_theme, "tema color"),
            PaletteAction("Atajos de teclado", "F1", "keyboard", self.show_shortcuts, "ayuda"),
            PaletteAction(f"Acerca de {APP_NAME}", f"v{APP_VERSION}", "info", self.show_about, "version licencias"),
            PaletteAction("Buscar actualizaciones", f"v{APP_VERSION}", "download", lambda: self.check_updates(True),
                          "actualizar version nueva descargar instalar"),
        ]
        return acts

    # ------------------------------------------------------ actualizaciones
    def check_updates(self, manual: bool = True) -> None:
        if not self.updates.installed:
            if manual:
                QMessageBox.information(
                    self, "Actualizaciones",
                    "Esta copia no se instaló con el instalador (se ejecuta desde el código o desde dist), así que "
                    "no se actualiza sola.\n\nEl instalador de la última versión está en GitHub → Releases.")
            return
        self._manual_update_check = manual
        if manual:
            self.statusBar().showMessage("Buscando actualizaciones en GitHub…", 5000)
        self.updates.check()

    def _on_update_found(self, release) -> None:
        self.update_btn.setText(f"  Actualizar a {release.version}")
        self.update_btn.setToolTip(f"Hay una versión nueva de {APP_NAME} ({release.version}; tienes la {APP_VERSION}).\n"
                                   "Pulsa para ver las novedades e instalarla.")
        self.update_box.show()
        if self._manual_update_check:
            self.show_update()
        else:
            self.toasts.show(f"Hay una versión nueva de {APP_NAME}: la {release.version}. "
                             "Pulsa «Actualizar» arriba para ver las novedades.", "info")
        self._manual_update_check = False

    def _on_up_to_date(self) -> None:
        if self._manual_update_check:
            self.toasts.show(f"Tienes la última versión ({APP_VERSION}).", "ok")
        self._manual_update_check = False

    def _on_update_failed(self, text: str) -> None:
        if self._manual_update_check:
            self.ctx.notify(f"Actualizaciones: {text}", error=True)
        else:  # al arrancar sin internet no se molesta con avisos
            self.statusBar().showMessage(f"No se pudo buscar actualizaciones: {text}", 8000)
        self._manual_update_check = False

    def show_update(self) -> None:
        release = self.updates.release
        if release is None:
            return
        real_hand = self.ctx.connected and not self.ctx.simulated
        if UpdateDialog(self, release, real_hand).exec() == QDialog.Accepted:
            self._download_update(release)

    def _download_update(self, release) -> None:
        from PySide6.QtWidgets import QProgressDialog
        label = f"Descargando la versión {release.version}…"
        dialog = QProgressDialog(label, "Cancelar", 0, 100, self)
        dialog.setWindowTitle("Actualizar")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        style_titlebar(dialog, self.ctx.theme)
        dialog.canceled.connect(self.updates.cancel)

        def progress(done: int, total: int) -> None:
            if total:
                dialog.setValue(int(done * 100 / total))
                dialog.setLabelText(f"{label}  {done / 1e6:.0f} / {total / 1e6:.0f} MB")

        def finished(path: str = "", error: str = "") -> None:
            self.updates.progress.disconnect(progress)
            self.updates.downloaded.disconnect(ok)
            self.updates.download_failed.disconnect(failed)
            dialog.close()
            if error:
                if "cancelada" not in error:
                    self.ctx.notify(f"No se pudo actualizar: {error}", error=True)
                return
            self._install_update(path)

        def ok(path: str) -> None:
            finished(path=path)

        def failed(error: str) -> None:
            finished(error=error)

        self.updates.progress.connect(progress)
        self.updates.downloaded.connect(ok)
        self.updates.download_failed.connect(failed)
        self.updates.download()

    def _install_update(self, path: str) -> None:
        if self.ctx.connected and not self.ctx.simulated:
            self.ctx.send_command("PARAR")  # que la mano no siga moviéndose mientras no hay app que la controle
        try:
            self.updates.install(path)
        except OSError as error:
            self.ctx.notify(f"No se pudo abrir el instalador: {error}", error=True)
            return
        self.close()  # el instalador espera a que la app termine de cerrarse, la actualiza y la reabre

    # --------------------------------------------------------------- eventos
    def _status_from_message(self, msg) -> None:
        if msg.kind in (MessageKind.SYSTEM, MessageKind.ERROR, MessageKind.ACK):
            self.statusBar().showMessage(f"{msg.kind.value}  ·  {msg.text}", 8000)
        if msg.kind is MessageKind.ERROR:  # los errores no deben pasar desapercibidos
            self.toasts.show(msg.text, "error")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.relayout()
        if getattr(self, "_rail_mode", "") == "auto":
            self.rail.set_expanded(self.width() >= RAIL_AUTO_WIDTH)

    def closeEvent(self, event) -> None:
        self.voice.stop()
        self.emg_viewer.shutdown()            # cierra el CSV que se esté grabando
        self.ctx.emg_receiver.disconnect_port()
        if self.ctx.recording:
            self.ctx.stop_recording()
        self.player.close()
        self.settings.setValue("geometry", self.saveGeometry())
        self._save_workspace()
        self.ctx.link.disconnect()
        for dock in self.docks.values():  # las ventanas flotantes son ventanas aparte: se cierran con la app
            if dock.isFloating():
                dock.hide()
        event.accept()
