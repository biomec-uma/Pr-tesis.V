"""Clase base del contenido de las ventanas (gemelo, gráficas, entrenamiento, consola…)."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..ui.context import AppContext
from ..ui.icons import ICONS, icon
from ..ui.theme import PALETTES


class BasePage(QWidget):
    #: Texto del botón en la barra lateral y título de la cabecera.
    title = "Página"
    #: Frase bajo el título en la cabecera.
    subtitle = ""
    #: Nombre del icono (ver ui/icons.py: ICONS).
    icon = "info"

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._icon_buttons: list[tuple[QPushButton, str, str]] = []
        ctx.message.connect(self.on_message)
        ctx.connection_changed.connect(self.on_connection_changed)
        ctx.theme_changed.connect(self.on_theme_changed)
        ctx.theme_changed.connect(lambda _t: self._paint_icons())
        ctx.catalog_reloaded.connect(self.on_catalog_reloaded)

    # Ganchos opcionales: cada página sobreescribe solo los que necesita.
    def on_message(self, msg) -> None: ...
    def on_connection_changed(self, connected: bool, info: str) -> None: ...
    def on_theme_changed(self, theme: str) -> None: ...
    def on_catalog_reloaded(self) -> None: ...
    def on_shown(self) -> None: ...

    # ------------------------------------------------------ maquetación
    @staticmethod
    def card(title: str | None = None, actions: list[QWidget] | None = None) -> tuple[QWidget, QVBoxLayout]:
        """Tarjeta con título opcional y, a su derecha, botones/controles opcionales."""
        widget = QWidget()
        widget.setObjectName("card")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        if title or actions:
            head = QHBoxLayout()
            head.setSpacing(8)
            if title:
                label = QLabel(title)
                label.setObjectName("cardTitle")
                head.addWidget(label)
            head.addStretch(1)
            for w in actions or []:
                head.addWidget(w)
            layout.addLayout(head)
        return widget, layout

    def button(self, text: str, icon_name: str | None = None, kind: str = "", tooltip: str = "",
               icon_color: str = "muted") -> QPushButton:
        """Botón con icono que se recolorea al cambiar de tema. kind: "" | "primary" | "ghost"."""
        btn = QPushButton(("  " + text) if (text and icon_name) else text)
        if kind:
            btn.setObjectName(kind)
        if tooltip:
            btn.setToolTip(tooltip)
        if icon_name and icon_name in ICONS:
            btn.setIconSize(QSize(16, 16))
            color = "white" if kind == "primary" else icon_color
            self._icon_buttons.append((btn, icon_name, color))
            self._paint_icons()
        return btn

    def _paint_icons(self) -> None:
        p = PALETTES[self.ctx.theme]
        for btn, name, color in self._icon_buttons:
            btn.setIcon(icon(name, "#ffffff" if color == "white" else p.get(color, color)))
