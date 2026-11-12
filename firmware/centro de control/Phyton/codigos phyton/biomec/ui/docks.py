"""Espacio de trabajo por ventanas: cada parte de la app es una ventana acoplable (QDockWidget).

    ┌ rail ┐ ┌ cabecera ───────────────────────────────────────────────┐
    │ ▣    │ │ ┌ Gráficas ─────────────┐ ┌ Gemelo digital ──────────┐ │
    │ ▸ G  │ │ │                       │ │                          │ │
    │ ▸ P  │ │ └───────────────────────┘ └──────────────────────────┘ │
    │ ▸ Gr │ │ ┌ Consola ──────────────────────────────────────────┐ │
    │ ...  │ │ └───────────────────────────────────────────────────┘ │
    └──────┘ └─────────────────────────────────────────────────────────┘

  Dock       una ventana: barra de título propia (icono, nombre, flotar, cerrar) + cuerpo con el widget.
             Se arrastra por la barra para moverla, agruparla en pestañas con otra o sacarla flotante
             (doble clic en el título también la saca o la vuelve a acoplar).
  Rail       barra lateral con un botón por ventana (marcado = visible). Expandida (icono + nombre)
             o plegada (solo iconos); se pliega sola en ventanas estrechas.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import APP_VERSION
from .icons import icon, nav_icon, pixmap
from .theme import PALETTES

RAIL_WIDE = 224
RAIL_NARROW = 58


# ================================================================== ventana
class DockTitle(QWidget):
    """Barra de título de una ventana: icono · nombre · [flotar / acoplar] [cerrar]."""

    def __init__(self, dock: "Dock", ctx, title: str, icon_name: str):
        super().__init__()
        self.dock, self.ctx, self.icon_name = dock, ctx, icon_name
        self.setObjectName("dockTitle")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.OpenHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 7, 8, 7)
        row.setSpacing(8)
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(16, 16)
        row.addWidget(self.icon_lbl)
        self.text = QLabel(title)
        self.text.setObjectName("dockTitleText")
        row.addWidget(self.text, 1)
        self.float_btn = QPushButton()
        self.float_btn.setObjectName("dockBtn")
        self.float_btn.setFixedSize(24, 24)
        self.float_btn.setIconSize(QSize(14, 14))
        self.float_btn.setCursor(Qt.PointingHandCursor)
        self.float_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("dockBtn")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setIconSize(QSize(14, 14))
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("Cerrar la ventana (se vuelve a abrir desde la barra lateral o con Ventanas)")
        self.close_btn.clicked.connect(dock.close)
        row.addWidget(self.float_btn)
        row.addWidget(self.close_btn)
        self.paint(ctx.theme)

    def paint(self, theme: str) -> None:
        p = PALETTES[theme]
        self.icon_lbl.setPixmap(pixmap(self.icon_name, p["accent_text"], 16))
        floating = self.dock.isFloating()
        self.float_btn.setIcon(icon("dock" if floating else "float", p["muted"], 14))
        self.float_btn.setToolTip("Volver a acoplar la ventana" if floating else
                                  "Sacar la ventana (flotante, se puede mover a otra pantalla)")
        self.close_btn.setIcon(icon("close", p["muted"], 14))

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.dock.setFloating(not self.dock.isFloating())
            event.accept()


class Dock(QDockWidget):
    """Una ventana del espacio de trabajo. plain=True: el contenido trae sus propias tarjetas (Entrenamiento)."""

    closed = Signal(str)   # la ventana se ha cerrado (clave)

    def __init__(self, key: str, title: str, icon_name: str, widget: QWidget, ctx, min_size=(280, 200),
                 plain: bool = False, top: bool = False):
        super().__init__(title)
        self.key, self.icon_name, self.ctx = key, icon_name, ctx
        self.setObjectName(f"dock_{key}")
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.body = QFrame()
        self.body.setObjectName("dockBodyPlain" if plain else "dockBody")
        self.body.setAttribute(Qt.WA_StyledBackground, True)
        # Solo el ancho mínimo es fijo: el alto mínimo lo pone el contenido (una altura fija menor
        # que la que necesita haría que Qt aplastase sus controles unos encima de otros).
        self.body.setMinimumWidth(min_size[0])
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(*((0, 8, 0, 0) if plain else (14, 10, 14, 12)))
        lay.addWidget(widget)
        if top:   # contenido de altura fija arriba (Dispositivo): el resto queda vacío en vez de estirarlo
            lay.addStretch(1)
        self.setWidget(self.body)
        self.title_bar = DockTitle(self, ctx, title, icon_name)
        self.setTitleBarWidget(self.title_bar)
        self.topLevelChanged.connect(lambda _f: self.title_bar.paint(self.ctx.theme))
        ctx.theme_changed.connect(self.title_bar.paint)

    @property
    def title(self) -> str:
        return self.windowTitle()

    def behind_tab(self) -> bool:
        """Abierta pero tapada por otra ventana con la que está agrupada en pestañas."""
        return not self.isHidden() and not self.isFloating() and self.visibleRegion().isEmpty()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        self.closed.emit(self.key)


# ============================================================== barra lateral
class Rail(QWidget):
    """Barra lateral: un botón por ventana. Expandida (nombres) o plegada (solo iconos)."""

    clicked = Signal(str)          # clave de la ventana
    new_graph = Signal()
    collapse_toggled = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.expanded = True
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.buttons: dict[str, tuple[QPushButton, str, str]] = {}   # key -> (botón, título, icono)
        self.sections: list[QLabel] = []

        side = QVBoxLayout(self)
        side.setContentsMargins(10, 14, 10, 12)
        side.setSpacing(3)

        self.brand = QGridLayout()
        self.brand.setSpacing(6)
        self.badge = QLabel()
        self.badge.setFixedSize(36, 36)
        self.badge.setAlignment(Qt.AlignCenter)
        self.names = QWidget()
        names = QVBoxLayout(self.names)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        self.brand_name = QLabel("BIOMEC UMA")
        self.brand_name.setObjectName("brandName")
        self.brand_sub = QLabel("Centro de control")
        self.brand_sub.setObjectName("brandSub")
        names.addWidget(self.brand_name)
        names.addWidget(self.brand_sub)
        self.collapse_btn = QPushButton()
        self.collapse_btn.setObjectName("ghost")
        self.collapse_btn.setFixedSize(26, 26)
        self.collapse_btn.setIconSize(QSize(14, 14))
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.clicked.connect(self.collapse_toggled.emit)
        side.addLayout(self.brand)
        self._layout_brand()
        side.addSpacing(14)
        self.body = QVBoxLayout()
        self.body.setSpacing(3)
        side.addLayout(self.body)
        side.addStretch(1)

        self.footer = QGridLayout()
        self.footer.setSpacing(2)
        self.theme_btn = QPushButton()
        self.help_btn = QPushButton()
        self.about_btn = QPushButton()
        for b in (self.theme_btn, self.help_btn, self.about_btn):
            b.setObjectName("ghost")
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(34, 30)
            b.setCursor(Qt.PointingHandCursor)
        self.help_btn.setToolTip("Atajos de teclado (F1)")
        self.about_btn.setToolTip(f"Acerca de BIOMEC Control · v{APP_VERSION}")
        self.version = QLabel(f"v{APP_VERSION}")
        self.version.setObjectName("version")
        self.version.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        side.addLayout(self.footer)
        self._layout_footer()

    # ----------------------------------------------------------- entradas
    def add_section(self, text: str) -> None:
        label = QLabel(text.upper())
        label.setObjectName("sectionLabel")
        self.sections.append(label)
        if self.body.count():
            self.body.addSpacing(12)
        self.body.addWidget(label)
        self.body.addSpacing(2)

    def add_entry(self, key: str, title: str, icon_name: str, tool: bool = False, shortcut: str = "") -> QPushButton:
        b = QPushButton()
        b.setObjectName("toolButton" if tool else "navButton")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setIconSize(QSize(18, 18))
        b.setToolTip(f"{title}  ({shortcut})" if shortcut else title)
        b.clicked.connect(lambda _c=False, k=key: self.clicked.emit(k))
        self.buttons[key] = (b, title, icon_name)
        self.body.addWidget(b)
        self._apply_mode(b, title)
        return b

    def add_new_graph(self) -> None:
        b = QPushButton()
        b.setObjectName("toolButton")
        b.setCursor(Qt.PointingHandCursor)
        b.setIconSize(QSize(18, 18))
        b.setToolTip("Nueva gráfica: otra ventana con las señales que elijas  (Ctrl+Mayús+G)")
        b.clicked.connect(self.new_graph.emit)
        self.buttons["_nueva"] = (b, "Nueva gráfica", "plus")
        self.body.addWidget(b)
        self._apply_mode(b, "Nueva gráfica")

    def set_checked(self, key: str, on: bool) -> None:
        entry = self.buttons.get(key)
        if entry is not None and entry[0].isChecked() != on:
            entry[0].setChecked(on)

    # ----------------------------------------------------------------- modo
    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self.setFixedWidth(RAIL_WIDE if expanded else RAIL_NARROW)
        for label in self.sections:
            label.setVisible(expanded)
        for key, (b, title, _ic) in self.buttons.items():
            self._apply_mode(b, title)
        self.collapse_btn.setToolTip("Plegar la barra lateral (solo iconos)" if expanded else "Expandir la barra lateral")
        self._layout_brand()
        self._layout_footer()
        self.apply_theme(self.ctx.theme)

    def _layout_brand(self) -> None:
        """Expandida: logo · nombre · chevrón. Plegada: logo y, debajo, el chevrón."""
        while self.brand.count():
            item = self.brand.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.names.setVisible(self.expanded)
        if self.expanded:
            self.brand.addWidget(self.badge, 0, 0)
            self.brand.addWidget(self.names, 0, 1)
            self.brand.addWidget(self.collapse_btn, 0, 2, Qt.AlignTop)
            self.brand.setColumnStretch(1, 1)
        else:
            self.brand.setColumnStretch(1, 0)
            self.brand.addWidget(self.badge, 0, 0, Qt.AlignHCenter)
            self.brand.addWidget(self.collapse_btn, 1, 0, Qt.AlignHCenter)
        for w in (self.badge, self.names, self.collapse_btn):
            w.setParent(self)
            w.setVisible(w is not self.names or self.expanded)

    def _apply_mode(self, b: QPushButton, title: str) -> None:
        b.setText(f"  {title}" if self.expanded else "")
        if b.property("compact") != (not self.expanded):
            b.setProperty("compact", not self.expanded)
            b.style().unpolish(b)
            b.style().polish(b)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _layout_footer(self) -> None:
        while self.footer.count():
            item = self.footer.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        if self.expanded:
            for i, b in enumerate((self.theme_btn, self.help_btn, self.about_btn)):
                self.footer.addWidget(b, 0, i)
            self.footer.setColumnStretch(3, 1)
            self.footer.addWidget(self.version, 0, 4)
            self.version.show()
        else:
            self.footer.setColumnStretch(3, 0)
            for i, b in enumerate((self.theme_btn, self.help_btn, self.about_btn)):
                self.footer.addWidget(b, i, 0, Qt.AlignHCenter)
            self.version.hide()
        for b in (self.theme_btn, self.help_btn, self.about_btn):
            b.setParent(self)
            b.show()

    # ---------------------------------------------------------------- tema
    def apply_theme(self, theme: str) -> None:
        p = PALETTES[theme]
        for key, (b, _title, icon_name) in self.buttons.items():
            b.setIcon(nav_icon(icon_name, p["muted"], p["accent_text"]))
        dark = theme == "dark"
        self.theme_btn.setToolTip("Cambiar a modo claro" if dark else "Cambiar a modo oscuro")
        self.theme_btn.setIcon(icon("sun" if dark else "moon", p["muted"], 16))
        self.help_btn.setIcon(icon("keyboard", p["muted"], 16))
        self.about_btn.setIcon(icon("info", p["muted"], 16))
        self.collapse_btn.setIcon(icon("chevrons_left" if self.expanded else "chevrons_right", p["subtle"], 14))
