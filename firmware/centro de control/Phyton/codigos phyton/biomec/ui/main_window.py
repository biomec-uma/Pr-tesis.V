"""Ventana principal: barra lateral + barra de conexión + páginas."""

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_VERSION, ORG_NAME
from ..core.protocol import MessageKind
from ..paths import asset
from .connection_bar import ConnectionBar
from .context import AppContext
from .theme import stylesheet


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, page_classes):
        super().__init__()
        self.ctx = ctx
        self.settings = QSettings(ORG_NAME, APP_NAME)
        ctx.theme = self.settings.value("theme", "dark")

        self.setWindowTitle(f"{ORG_NAME} · {APP_NAME}")
        self.resize(1280, 800)
        self.setMinimumSize(980, 640)

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Barra lateral
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 14)
        side.setSpacing(6)
        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setStyleSheet("background: transparent;")
        side.addWidget(self.logo)
        title = QLabel("BIOMEC UMA")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("CENTRO DE CONTROL")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        side.addWidget(title)
        side.addWidget(subtitle)
        side.addSpacing(18)

        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.pages = {}
        for index, page_cls in enumerate(page_classes):
            page = page_cls(ctx)
            self.stack.addWidget(page)
            self.pages[page.title] = page
            button = QPushButton(f"  {page.icon}   {page.title}")
            button.setObjectName("nav")
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            side.addWidget(button)
        self.nav_group.idClicked.connect(self._go_to)

        side.addStretch(1)
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self.toggle_theme)
        side.addWidget(self.theme_btn)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignCenter)
        side.addWidget(version)
        outer.addWidget(sidebar)

        # --- Zona principal
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(14)
        self.connection_bar = ConnectionBar(ctx.link, ctx)
        main_layout.addWidget(self.connection_bar)
        main_layout.addWidget(self.stack, 1)
        outer.addWidget(main, 1)
        self.setCentralWidget(central)

        ctx.message.connect(self._status_from_message)
        ctx.theme_changed.connect(lambda _t: self.apply_theme())
        self.apply_theme()
        self._go_to(int(self.settings.value("last_page", 0)) if self.stack.count() else 0)
        self.statusBar().showMessage("Listo. Conecta la ESP32-C6 puente por USB.")

    # ------------------------------------------------------------ navegación
    def _go_to(self, index: int) -> None:
        if not 0 <= index < self.stack.count():
            index = 0
        self.stack.setCurrentIndex(index)
        self.nav_group.button(index).setChecked(True)
        self.stack.currentWidget().on_shown()
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
        logo_path = asset(f"biomec_logo_{theme}.png")
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            self.logo.setPixmap(pixmap.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.setWindowIcon(QIcon(str(logo_path)))
        self.theme_btn.setText("☀  Modo claro" if theme == "dark" else "☾  Modo oscuro")
        self.setStyleSheet(stylesheet(theme))

    # --------------------------------------------------------------- estado
    def _status_from_message(self, msg) -> None:
        if msg.kind in (MessageKind.SYSTEM, MessageKind.ERROR, MessageKind.ACK):
            self.statusBar().showMessage(f"{msg.kind.value}: {msg.text}", 8000)

    def closeEvent(self, event) -> None:
        self.ctx.link.disconnect()
        event.accept()
