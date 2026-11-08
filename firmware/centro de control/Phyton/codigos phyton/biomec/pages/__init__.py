"""Registro de páginas y paneles de la aplicación.

╔══════════════════════════════════════════════════════════════════════╗
║  PÁGINAS (barra lateral, una visible cada vez):                        ║
║    crea pages/mi_pagina.py con una clase que herede de BasePage,       ║
║    impórtala aquí y añádela a PAGES. Para quitarla, borra su línea.    ║
║  PANELES (visibles en todas las páginas):                              ║
║    CONSOLE_PANEL abajo; COMMANDS_PANEL y ASSISTANT_PANEL a la derecha  ║
║    (desplegables).                                                     ║
╚══════════════════════════════════════════════════════════════════════╝
El orden de PAGES es el orden en la barra lateral; la primera es la de inicio.
"""

from .assistant import AssistantPanel
from .commands import CommandsPanel
from .console import ConsolePanel
from .emg import EmgPage
from .hand3d import Hand3DPage
from .telemetry import TelemetryPage

PAGES = [
    Hand3DPage,
    TelemetryPage,
    EmgPage,
]

CONSOLE_PANEL = ConsolePanel
COMMANDS_PANEL = CommandsPanel
ASSISTANT_PANEL = AssistantPanel
