"""Contexto compartido: lo único que las páginas necesitan conocer.

Las páginas NO se importan entre sí. Se comunican a través de este objeto:
  - ctx.send_command("DEDO 2 50")    valida y envía
  - ctx.message                      señal con cada Message (RX, TX, errores...)
  - ctx.connection_changed           señal (conectado, descripción)
  - ctx.theme_changed                señal (nombre del tema)
  - ctx.prefill_command              pedir a la consola que escriba un comando
  - ctx.catalog_reloaded             se ha vuelto a leer commands.json
"""

from PySide6.QtCore import QObject, Signal

from ..core.commands import CommandCatalog, CommandError
from ..core.protocol import Message, MessageKind
from ..core.serial_link import SerialLink


class AppContext(QObject):
    message = Signal(object)
    connection_changed = Signal(bool, str)
    theme_changed = Signal(str)
    prefill_command = Signal(str)
    catalog_reloaded = Signal()

    def __init__(self, link: SerialLink, catalog: CommandCatalog, theme: str = "dark"):
        super().__init__()
        self.link = link
        self.catalog = catalog
        self.theme = theme
        link.message_received.connect(self.message)
        link.connection_changed.connect(self.connection_changed)

    @property
    def connected(self) -> bool:
        return self.link.is_connected

    def send_command(self, text: str) -> bool:
        try:
            _cmd, line = self.catalog.build(text)
        except CommandError as error:
            self.notify(str(error), error=True)
            return False
        return self.link.send_line(line)

    def send_raw(self, line: str) -> bool:
        """Envía sin validar contra el catálogo (modo avanzado / pruebas)."""
        return self.link.send_line(line)

    def reload_catalog(self) -> None:
        try:
            self.catalog.reload()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.notify(f"Error leyendo {self.catalog.path.name}: {error}", error=True)
            return
        self.catalog_reloaded.emit()
        self.notify(f"Catálogo recargado: {len(self.catalog.names())} comandos.")

    def notify(self, text: str, error: bool = False) -> None:
        self.message.emit(Message(MessageKind.ERROR if error else MessageKind.SYSTEM, text))

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.theme_changed.emit(theme)
