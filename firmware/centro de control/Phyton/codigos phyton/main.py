"""Punto de entrada de BIOMEC Control.

    python main.py          -> abre la aplicación
    build_exe.ps1           -> genera el .exe y el acceso directo del menú Inicio
"""

import ctypes
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from biomec import APP_NAME, ORG_NAME
from biomec.core.commands import CommandCatalog
from biomec.core.serial_link import SerialLink
from biomec.pages import PAGES
from biomec.paths import asset, config_file
from biomec.ui.context import AppContext
from biomec.ui.main_window import MainWindow


def main() -> int:
    if sys.platform == "win32":
        # Hace que Windows muestre nuestro icono en la barra de tareas (no el de Python).
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BiomecUMA.Control")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(QIcon(str(asset("biomec_logo_dark.png"))))

    link = SerialLink()
    catalog = CommandCatalog(config_file("commands.json"))
    ctx = AppContext(link, catalog)

    window = MainWindow(ctx, PAGES)
    window.show()
    ctx.notify(f"{APP_NAME} iniciada. {len(catalog.names())} comandos cargados.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
