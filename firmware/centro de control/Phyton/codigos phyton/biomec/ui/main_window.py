"""Ventana principal.

┌──────────────┬──────────────────────────────────────────────────────────┐
│ ▣ BIOMEC     │ [▣] Título                   ● Estado  [⏺][⟲] │ [Parar] │
│   Centro…    │     Descripción                                           │
│ NAVEGACIÓN   │ [ franja de simulación / barra de reproducción ]          │
│ ▸ Gemelo dig.│ ┌──────────────────────────────┬─────────────┬─────────┐ │
│ ▸ Gráficas   │ │           página             │ Comandos    │Asistente│ │
│ ▸ Entrenam.  │ └──────────────────────────────┴─────────────┴─────────┘ │
│ HERRAMIENTAS │ ┌ Consola (plegable, en todas las pestañas) ────────────┐ │
│ DISPOSITIVO  │ └────────────────────────────────────────────────────────┘ │
│ ☀ ⌨ ⓘ  v0.2  │                                    avisos flotantes ↗    │
└──────────────┴──────────────────────────────────────────────────────────┘
Atajos: Ctrl+1…3 pestañas · Ctrl+J consola · Ctrl+K paleta · Ctrl+R grabar · Ctrl+O reproducir.
"""

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
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
from .icons import app_icon, icon, logo_badge, nav_icon, pixmap
from .palette import CommandPalette, PaletteAction
from .player import PlayerBar, SessionPlayer, fmt_time
from .theme import PALETTES, stylesheet
from .voice import VoiceController
from .widgets import ElidedLabel, ToastHost, style_titlebar

HEADER_H = 32  # altura común de los controles de la cabecera


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, page_classes, console_cls=None, commands_cls=None, assistant_cls=None):
        super().__init__()
        if console_cls is None or commands_cls is None or assistant_cls is None:
            from ..pages import ASSISTANT_PANEL, COMMANDS_PANEL, CONSOLE_PANEL
            console_cls = console_cls or CONSOLE_PANEL
            commands_cls = commands_cls or COMMANDS_PANEL
            assistant_cls = assistant_cls or ASSISTANT_PANEL
        self.ctx = ctx
        self.settings = QSettings(ORG_NAME, APP_NAME)
        ctx.theme = self.settings.value("theme", "dark")

        self.setWindowTitle(f"{ORG_NAME} · {APP_NAME}")
        self.setWindowIcon(app_icon())
        self.resize(1320, 840)
        self.setMinimumSize(1040, 720)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ================= barra lateral =================
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(262)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 14)
        side.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.badge = QLabel()
        self.badge.setFixedSize(40, 40)
        self.badge.setAlignment(Qt.AlignCenter)
        brand.addWidget(self.badge)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = QLabel("BIOMEC UMA")
        name.setObjectName("brandName")
        sub = QLabel("Centro de control")
        sub.setObjectName("brandSub")
        names.addWidget(name)
        names.addWidget(sub)
        brand.addLayout(names, 1)
        side.addLayout(brand)
        side.addSpacing(22)

        nav_label = QLabel("NAVEGACIÓN")
        nav_label.setObjectName("sectionLabel")
        side.addWidget(nav_label)
        side.addSpacing(4)

        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.pages = {}
        self.nav_buttons = []
        for index, page_cls in enumerate(page_classes):
            page = page_cls(ctx)
            self.stack.addWidget(page)
            self.pages[page.title] = page
            button = QPushButton(f"  {page.title}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setIconSize(QSize(18, 18))
            if index < 9:
                button.setToolTip(f"{page.title}  (Ctrl+{index + 1})")
            self.nav_group.addButton(button, index)
            self.nav_buttons.append((button, page))
            side.addWidget(button)
        self.nav_group.idClicked.connect(self._go_to)

        side.addSpacing(16)
        tools_label = QLabel("HERRAMIENTAS")
        tools_label.setObjectName("sectionLabel")
        side.addWidget(tools_label)
        side.addSpacing(4)
        self.console = console_cls(ctx)
        self.commands = commands_cls(ctx)
        self.assistant = assistant_cls(ctx)
        self.console_btn = self._tool_button("Consola", "Desplegar / plegar la consola  (Ctrl+J)")
        self.commands_btn = self._tool_button("Comandos", "Mostrar / ocultar el catálogo de comandos  (Ctrl+K)")
        self.assistant_btn = self._tool_button("Asistente IA", "Pregunta o pide cosas en lenguaje natural  (Ctrl+I)")
        self.console_btn.clicked.connect(lambda: self.console.set_expanded(not self.console.expanded))
        self.commands_btn.clicked.connect(lambda checked: self.set_commands_visible(checked))
        self.assistant_btn.clicked.connect(lambda checked: self.set_assistant_visible(checked))
        side.addWidget(self.console_btn)
        side.addWidget(self.commands_btn)
        side.addWidget(self.assistant_btn)

        side.addStretch(1)
        dev_label = QLabel("DISPOSITIVO")
        dev_label.setObjectName("sectionLabel")
        side.addWidget(dev_label)
        side.addSpacing(4)
        self.connection_bar = ConnectionBar(ctx.link, ctx)
        side.addWidget(self.connection_bar)
        side.addSpacing(10)

        footer = QHBoxLayout()
        footer.setSpacing(2)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("ghost")
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.help_btn = QPushButton()
        self.help_btn.setObjectName("ghost")
        self.help_btn.setToolTip("Atajos de teclado (F1)")
        self.help_btn.clicked.connect(self.show_shortcuts)
        self.about_btn = QPushButton()
        self.about_btn.setObjectName("ghost")
        self.about_btn.setToolTip(f"Acerca de {APP_NAME} · v{APP_VERSION}")
        self.about_btn.clicked.connect(self.show_about)
        footer.addWidget(self.theme_btn)
        footer.addWidget(self.help_btn)
        footer.addWidget(self.about_btn)
        footer.addStretch(1)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("version")
        version.setToolTip(f"{APP_NAME} {APP_VERSION}")
        footer.addWidget(version)
        footer.addSpacing(6)
        side.addLayout(footer)
        outer.addWidget(sidebar)

        # ================= zona principal =================
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(28, 22, 28, 22)
        main_layout.setSpacing(14)

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
        header.addSpacing(16)
        self.voice_caption = ElidedLabel()  # lo que se va oyendo (solo mientras escucha)
        self.voice_caption.setObjectName("voiceCaption")
        self.voice_caption.setMaximumWidth(240)
        self.voice_caption.hide()
        header.addWidget(self.voice_caption, 0, Qt.AlignVCenter)
        header.addSpacing(10)
        self.status_pill = QLabel()
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setFixedHeight(HEADER_H)
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

        # página + panel de comandos (derecha) / consola (abajo)
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.setHandleWidth(14)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.addWidget(self.stack)
        self.hsplit.addWidget(self.commands)
        self.hsplit.addWidget(self.assistant)
        self.hsplit.setStretchFactor(0, 1)
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.setHandleWidth(14)
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(self.console)
        self.vsplit.setStretchFactor(0, 1)
        main_layout.addWidget(self.vsplit, 1)
        outer.addWidget(main, 1)

        self.commands.close_requested.connect(lambda: self.set_commands_visible(False))
        self.assistant.close_requested.connect(lambda: self.set_assistant_visible(False))
        self.console.expanded_changed.connect(self._on_console_expanded)
        ctx.prefill_command.connect(lambda _t: None if self.console.expanded else self.console.set_expanded(True))
        QShortcut(QKeySequence("Ctrl+J"), self, activated=lambda: self.console.set_expanded(not self.console.expanded))
        QShortcut(QKeySequence("Ctrl+Shift+K"), self, activated=self._toggle_commands_shortcut)
        self.palette = CommandPalette(self)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.palette.open_palette)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.palette.open_palette)
        QShortcut(QKeySequence("Esc"), self, activated=self.emergency_stop)
        QShortcut(QKeySequence("F1"), self, activated=self.show_shortcuts)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.toggle_recording)
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self._toggle_assistant_shortcut)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=lambda: self.open_session())
        self.space_shortcut = QShortcut(QKeySequence("Space"), self, activated=self.player.toggle)
        self.space_shortcut.setEnabled(False)  # solo mientras se reproduce una sesión
        for n in range(1, len(GESTOS) + 1):
            QShortcut(QKeySequence(f"Alt+{n}"), self, activated=lambda n=n: self.send_gesture(n))
        for i in range(min(self.stack.count(), 9)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self._go_to(i))
        self.setCentralWidget(central)
        self.toasts = ToastHost(central, main, lambda: self.ctx.theme, top=78)
        ctx.toast.connect(self.toasts.show)

        # control por voz (sin internet)
        self.voice = VoiceController(ctx, [page.title for _b, page in self.nav_buttons])
        self.voice.listening_changed.connect(lambda _l: self._update_voice_button())
        self.voice.ready.connect(self._on_voice_ready)
        self.voice.partial.connect(lambda text: self.voice_caption.setText(f"«{text}…»"))
        self.voice.heard.connect(self._on_voice_heard)
        self.voice.error.connect(self._on_voice_error)
        self._voice_real_ok = False
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_voice)

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
        self._go_to(int(self.settings.value("last_page", 0)) if self.stack.count() else 0)
        self.set_commands_visible(self.settings.value("commands_visible", False, type=bool))
        self.set_assistant_visible(self.settings.value("assistant_visible", False, type=bool))
        self._on_console_expanded(self.console.expanded)
        self.statusBar().showMessage("Listo.  Ctrl+K: paleta de comandos · F1: atajos de teclado")

    # ------------------------------------------------------- herramientas
    def _tool_button(self, text: str, tooltip: str) -> QPushButton:
        b = QPushButton(f"  {text}")
        b.setObjectName("toolButton")  # activa = texto en color (no parece una página seleccionada)
        b.setCheckable(True)
        b.setToolTip(tooltip)
        b.setIconSize(QSize(18, 18))
        return b

    def set_commands_visible(self, visible: bool) -> None:
        self.commands.setVisible(visible)
        self.commands_btn.setChecked(visible)
        self.settings.setValue("commands_visible", visible)
        self._layout_drawers()

    def set_assistant_visible(self, visible: bool) -> None:
        self.assistant.setVisible(visible)
        self.assistant_btn.setChecked(visible)
        self.settings.setValue("assistant_visible", visible)
        self._layout_drawers()

    def _layout_drawers(self) -> None:
        """Reparte el ancho entre la página y los paneles desplegables visibles (Comandos, Asistente)."""
        total = max(self.hsplit.width(), 900)
        commands = 380 if self.commands.isVisibleTo(self) else 0
        assistant = 420 if self.assistant.isVisibleTo(self) else 0
        self.hsplit.setSizes([max(total - commands - assistant, 320), commands, assistant])

    def _toggle_assistant_shortcut(self) -> None:
        if self.assistant.isVisible() and self.assistant.input.hasFocus():
            self.set_assistant_visible(False)
        else:
            self.set_assistant_visible(True)
            self.assistant.focus_input()

    def _toggle_commands_shortcut(self) -> None:
        if self.commands.isVisible() and self.commands.search.hasFocus():
            self.set_commands_visible(False)
        else:
            self.set_commands_visible(True)
            self.commands.focus_search()

    def _on_console_expanded(self, expanded: bool) -> None:
        self.console_btn.setChecked(expanded)
        handle = self.vsplit.handle(1)
        if expanded:
            self.console.setMaximumHeight(16777215)
            handle.setEnabled(True)
            height = int(self.settings.value("console_height", 260))
            QTimer.singleShot(0, lambda: self.vsplit.setSizes([max(self.vsplit.height() - height, 200), height]))
        else:
            if self.vsplit.sizes()[1] > 120:
                self.settings.setValue("console_height", self.vsplit.sizes()[1])
            self.console.setMaximumHeight(self.console.sizeHint().height())
            handle.setEnabled(False)
            # el divisor no reparte solo el espacio que deja la consola al plegarse: se le da a la página
            QTimer.singleShot(0, self._fit_collapsed_console)

    def _fit_collapsed_console(self) -> None:
        if not self.console.expanded:
            h = self.console.sizeHint().height()
            self.vsplit.setSizes([max(self.vsplit.height() - h, 200), h])

    # ------------------------------------------------------------ navegación
    def _go_to(self, index: int) -> None:
        if not 0 <= index < self.stack.count():
            index = 0
        self.stack.setCurrentIndex(index)
        self.nav_group.button(index).setChecked(True)
        page = self.stack.currentWidget()
        self.page_badge.setPixmap(pixmap(page.icon, PALETTES[self.ctx.theme]["accent_text"], 20))
        self.page_title.setText(page.title)
        self.page_subtitle.setText(page.subtitle)
        self.page_subtitle.setToolTip(page.subtitle)
        page.on_shown()
        self.settings.setValue("last_page", index)

    def show_page(self, title: str) -> None:
        page = self.pages.get(title)
        if page is not None:
            self._go_to(self.stack.indexOf(page))

    # ----------------------------------------------------------------- tema
    def toggle_theme(self) -> None:
        self.ctx.set_theme("light" if self.ctx.theme == "dark" else "dark")
        self.settings.setValue("theme", self.ctx.theme)

    def apply_theme(self) -> None:
        theme = self.ctx.theme
        p = PALETTES[theme]
        self._apply_qt_palette(p)
        self.setStyleSheet(stylesheet(theme))
        self.badge.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['accent']}, stop:1 #1e3a8a);"
            "border-radius: 11px;")
        self.badge.setPixmap(logo_badge(30, "#ffffff", asset("biomec_logo_dark.png")))
        style_titlebar(self, theme)
        self.sim_icon.setPixmap(pixmap("flask", p["sim_text"], 15))
        page = self.stack.currentWidget()
        if page is not None:
            self.page_badge.setPixmap(pixmap(page.icon, p["accent_text"], 20))
        for button, page in self.nav_buttons:
            button.setIcon(nav_icon(page.icon, p["muted"], p["accent_text"]))
        self.console_btn.setIcon(nav_icon("terminal", p["muted"], p["accent_text"]))
        self.commands_btn.setIcon(nav_icon("list", p["muted"], p["accent_text"]))
        self.assistant_btn.setIcon(nav_icon("sparkles", p["muted"], p["accent_text"]))
        dark = theme == "dark"
        self.theme_btn.setToolTip("Cambiar a modo claro" if dark else "Cambiar a modo oscuro")
        self.theme_btn.setIcon(icon("sun" if dark else "moon", p["muted"], 16))
        self.help_btn.setIcon(icon("keyboard", p["muted"], 16))
        self.about_btn.setIcon(icon("info", p["muted"], 16))
        self.stop_btn.setIcon(icon("octagon", "#ffffff", 16))
        self.replay_btn.setIcon(icon("history", p["muted"], 16))
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
        self.status_pill.setStyleSheet(f"color: {fg}; background: {bg}; border-radius: {HEADER_H // 2}px; "
                                       "padding: 0 14px;")
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
            self.show_page(action.value)
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
        twin_page = self.pages.get("Gemelo digital")
        if twin_page is not None and hasattr(twin_page, "new_posture"):
            acts.append(PaletteAction("Nueva postura personalizada…", "Editor de posturas", "plus",
                                      lambda: (self.show_page("Gemelo digital"), twin_page.new_posture()),
                                      "crear postura agarre editor"))
        for index, (button, page) in enumerate(self.nav_buttons):
            acts.append(PaletteAction(f"Ir a {page.title}", "Pestaña", page.icon, lambda i=index: self._go_to(i)))
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
            PaletteAction("Modo demo (recorrer gestos)", "AUTO", "play", lambda: ctx.send_command("AUTO"), "auto", on),
            PaletteAction("Modo manual", "MANUAL", "pause", lambda: ctx.send_command("MANUAL"), "manual", on),
        ]
        twin = self.pages.get("Gemelo digital")
        if twin is not None and hasattr(twin, "set_camera"):
            from ..pages.hand3d import CAMERAS
            for name in CAMERAS:
                acts.append(PaletteAction(f"Vista 3D: {name}", "Gemelo digital", "camera",
                                          lambda n=name: (self.show_page("Gemelo digital"), twin.set_camera(n)),
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
            PaletteAction("Mostrar / ocultar consola", "Ctrl+J", "terminal",
                          lambda: self.console.set_expanded(not self.console.expanded)),
            PaletteAction("Mostrar / ocultar panel Comandos", "Ctrl+Shift+K", "list",
                          lambda: self.set_commands_visible(not self.commands.isVisible())),
            PaletteAction("Preguntar al asistente IA", "Ctrl+I", "sparkles",
                          lambda: (self.set_assistant_visible(True), self.assistant.focus_input()),
                          "ia claude chat ayuda asistente"),
            PaletteAction("Cambiar a tema " + ("claro" if ctx.theme == "dark" else "oscuro"), "Apariencia",
                          "sun" if ctx.theme == "dark" else "moon", self.toggle_theme, "tema color"),
            PaletteAction("Atajos de teclado", "F1", "keyboard", self.show_shortcuts, "ayuda"),
            PaletteAction(f"Acerca de {APP_NAME}", f"v{APP_VERSION}", "info", self.show_about, "version licencias"),
        ]
        return acts

    def _status_from_message(self, msg) -> None:
        if msg.kind in (MessageKind.SYSTEM, MessageKind.ERROR, MessageKind.ACK):
            self.statusBar().showMessage(f"{msg.kind.value}  ·  {msg.text}", 8000)
        if msg.kind is MessageKind.ERROR:  # los errores no deben pasar desapercibidos
            self.toasts.show(msg.text, "error")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.relayout()

    def closeEvent(self, event) -> None:
        self.voice.stop()
        if self.ctx.recording:
            self.ctx.stop_recording()
        self.player.close()
        self.settings.setValue("geometry", self.saveGeometry())
        if self.console.expanded and self.vsplit.sizes()[1] > 120:
            self.settings.setValue("console_height", self.vsplit.sizes()[1])
        self.ctx.link.disconnect()
        event.accept()
