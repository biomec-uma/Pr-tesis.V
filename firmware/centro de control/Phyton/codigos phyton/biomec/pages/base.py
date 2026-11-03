"""Clase base de todas las páginas (pestañas de la barra lateral)."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..ui.context import AppContext


class BasePage(QWidget):
    #: Texto del botón en la barra lateral.
    title = "Página"
    #: Carácter/emoji que aparece delante del título.
    icon = "•"

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        ctx.message.connect(self.on_message)
        ctx.connection_changed.connect(self.on_connection_changed)
        ctx.theme_changed.connect(self.on_theme_changed)
        ctx.catalog_reloaded.connect(self.on_catalog_reloaded)

    # Ganchos opcionales: cada página sobreescribe solo los que necesita.
    def on_message(self, msg) -> None: ...
    def on_connection_changed(self, connected: bool, info: str) -> None: ...
    def on_theme_changed(self, theme: str) -> None: ...
    def on_catalog_reloaded(self) -> None: ...
    def on_shown(self) -> None: ...

    # Utilidades de maquetación
    @staticmethod
    def card(title: str | None = None) -> tuple[QWidget, QVBoxLayout]:
        widget = QWidget()
        widget.setObjectName("card")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        if title:
            label = QLabel(title.upper())
            label.setObjectName("section")
            layout.addWidget(label)
        return widget, layout
