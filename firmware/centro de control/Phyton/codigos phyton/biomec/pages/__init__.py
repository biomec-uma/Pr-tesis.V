"""Registro de páginas de la aplicación.

╔══════════════════════════════════════════════════════════════════════╗
║  Para AÑADIR una pestaña: crea pages/mi_pagina.py con una clase que    ║
║  herede de BasePage, impórtala aquí y añádela a PAGES.                 ║
║  Para QUITARLA: borra su línea de PAGES. Nada más se ve afectado.      ║
╚══════════════════════════════════════════════════════════════════════╝
El orden de la lista es el orden en la barra lateral.
"""

from .commands import CommandsPage
from .console import ConsolePage
from .telemetry import TelemetryPage

PAGES = [
    ConsolePage,
    CommandsPage,
    TelemetryPage,
]
