"""Punto de entrada de BIOMEC Control.

    python main.py              -> abre la aplicación
    python main.py --selftest   -> comprueba que no falta nada (lo usa build_exe.ps1 con el .exe)
    build_exe.ps1               -> genera el .exe y el acceso directo del menú Inicio
"""

import ctypes
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from biomec import APP_NAME, APP_VERSION, ORG_NAME
from biomec.core.commands import CommandCatalog
from biomec.core.serial_link import SerialLink
from biomec.pages import PAGES
from biomec.paths import config_file
from biomec.ui.context import AppContext
from biomec.ui.icons import app_icon, app_icon_pixmap
from biomec.ui.main_window import MainWindow


def splash_pixmap() -> QPixmap:
    """Pantalla de arranque: icono, nombre y versión sobre fondo oscuro redondeado."""
    w, h, ratio = 460, 250, 2
    pm = QPixmap(w * ratio, h * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 18, 18)
    p.fillPath(path, QColor("#0e131c"))
    p.setPen(QColor("#2f3b4f"))
    p.drawPath(path)
    p.drawPixmap(QRectF(36, 46, 76, 76), app_icon_pixmap(152), QRectF(0, 0, 152, 152))
    p.setPen(QColor("#e6ebf3"))
    p.setFont(QFont("Segoe UI", 20, QFont.Bold))
    p.drawText(QRectF(132, 50, 300, 40), Qt.AlignLeft | Qt.AlignVCenter, ORG_NAME)
    p.setPen(QColor("#8a96aa"))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(QRectF(132, 88, 300, 28), Qt.AlignLeft | Qt.AlignVCenter, "Centro de control")
    p.setPen(QColor("#5f6b80"))
    p.setFont(QFont("Segoe UI", 9))
    p.drawText(QRectF(36, 196, 300, 24), Qt.AlignLeft | Qt.AlignVCenter, f"Versión {APP_VERSION}  ·  Universidad de Málaga")
    p.end()
    return pm


def selftest() -> int:
    """Importa todo lo que la app necesita y deja el resultado en %TEMP%/biomec_selftest.txt."""
    import importlib
    import tempfile
    from pathlib import Path

    lines, ok = [], True
    modules = ("numpy", "serial", "pyqtgraph", "pyqtgraph.opengl", "OpenGL.GL", "anthropic", "vosk",
               "PySide6.QtMultimedia", "biomec.core.emg", "biomec.core.assistant", "biomec.core.voice", "biomec.pages")
    for name in modules:
        try:
            importlib.import_module(name)
            lines.append(f"OK   {name}")
        except Exception as error:  # noqa: BLE001
            ok = False
            lines.append(f"FALLA {name}: {error!r}")
    try:
        import anthropic
        anthropic.Anthropic(api_key="prueba")
        lines.append("OK   cliente de Claude")
    except Exception as error:  # noqa: BLE001
        ok = False
        lines.append(f"FALLA cliente de Claude: {error!r}")
    try:
        CommandCatalog(config_file("commands.json"))
        lines.append("OK   config/commands.json")
    except Exception as error:  # noqa: BLE001
        ok = False
        lines.append(f"FALLA config/commands.json: {error!r}")
    Path(tempfile.gettempdir(), "biomec_selftest.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def micro_test() -> int:
    """Abre el micrófono 1 s con el mismo código que el control por voz y anota qué pasa en
    %TEMP%/biomec_micro.txt. Solo cuenta bytes: el audio no se guarda ni se escucha."""
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QTimer
    from PySide6.QtMultimedia import QMediaDevices

    from biomec.ui.voice import VoiceController

    app = QApplication(sys.argv)
    lines = []
    device = QMediaDevices.defaultAudioInput()
    lines.append(f"dispositivo: {'ninguno' if device.isNull() else device.description()}")
    if not device.isNull():
        pref = device.preferredFormat()
        lines.append(f"formato preferido: {pref.sampleRate()} Hz, {pref.channelCount()} canales, "
                     f"{pref.sampleFormat().name}")
    ctx = AppContext(SerialLink(), CommandCatalog(config_file("commands.json")))
    voice = VoiceController(ctx, [])
    voice.error.connect(lambda text: lines.append("ERROR: " + text))
    rate = voice._open_microphone()
    lines.append(f"micrófono abierto a {rate} Hz" if rate else "el micrófono NO se abrió")
    result = {"bytes": 0}

    def finish() -> None:
        result["bytes"] = sum(len(chunk) for chunk in list(voice._queue.queue) if isinstance(chunk, bytes))
        lines.append(f"audio recibido en 1 s: {result['bytes']} bytes")
        voice.stop()
        app.quit()

    QTimer.singleShot(1000 if rate else 0, finish)
    app.exec()
    Path(tempfile.gettempdir(), "biomec_micro.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if result["bytes"] > 0 else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--diagnostico-micro" in sys.argv:
        return micro_test()
    if sys.platform == "win32":
        # Hace que Windows muestre nuestro icono en la barra de tareas (no el de Python).
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BiomecUMA.Control")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(app_icon())

    splash = QSplashScreen(splash_pixmap())
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.show()
    splash.showMessage("Cargando el gemelo digital…   ", Qt.AlignBottom | Qt.AlignRight, QColor("#8a96aa"))
    app.processEvents()

    link = SerialLink()
    catalog = CommandCatalog(config_file("commands.json"))
    ctx = AppContext(link, catalog)

    window = MainWindow(ctx, PAGES)
    window.show()
    splash.finish(window)
    ctx.notify(f"{APP_NAME} iniciada. {len(catalog.names())} comandos cargados.  Pulsa Ctrl+K para la paleta de comandos.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
