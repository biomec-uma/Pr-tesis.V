"""Las partes de la aplicación. Cada una es una VENTANA del espacio de trabajo (ui/docks.py), que se
muestra, oculta, acopla o saca flotante a gusto del usuario (ui/main_window.py las crea y reparte).

╔══════════════════════════════════════════════════════════════════════╗
║  Hand3DPage      Gemelo digital (vista 3D) + Posturas (galería y     ║
║                  controles): dos ventanas con el mismo estado        ║
║  GraphPanel      Gráficas: tantas ventanas como se quiera, cada una  ║
║                  con sus señales (config/signals.json)               ║
║  EmgPage         Entrenamiento (EMG)                                 ║
║  EmgViewerPanel  Visor EMG: señal en directo, diagnóstico, CSV       ║
║  EmgAnalyzerPanel Analizador EMG (el de MATLAB del equipo)           ║
║  ConsolePanel    Consola · CommandsPanel  Comandos ·                 ║
║  AssistantPanel  Asistente IA                                        ║
╚══════════════════════════════════════════════════════════════════════╝
Para añadir una ventana: crea la clase (hereda de BasePage), impórtala aquí y añade su línea en
WINDOWS de ui/main_window.py.
"""

from .assistant import AssistantPanel
from .commands import CommandsPanel
from .console import ConsolePanel
from .emg import EmgPage
from .emg_analyzer import EmgAnalyzerPanel
from .emg_viewer import EmgViewerPanel
from .hand3d import Hand3DPage
from .telemetry import GraphPanel, TelemetryPage

PAGES = [Hand3DPage, GraphPanel, EmgPage]   # compatibilidad con código anterior

CONSOLE_PANEL = ConsolePanel
COMMANDS_PANEL = CommandsPanel
ASSISTANT_PANEL = AssistantPanel

__all__ = ["AssistantPanel", "CommandsPanel", "ConsolePanel", "EmgAnalyzerPanel", "EmgPage", "EmgViewerPanel",
           "GraphPanel", "Hand3DPage", "TelemetryPage", "PAGES"]
