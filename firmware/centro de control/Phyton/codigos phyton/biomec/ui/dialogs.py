"""Ventanas de ayuda: atajos de teclado (F1) y "Acerca de"."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import APP_NAME, APP_VERSION, ORG_NAME
from ..core.updates import RELEASES_PAGE
from ..paths import asset
from .icons import logo_badge
from .widgets import style_titlebar

SHORTCUTS = [
    ("Ctrl+K", "Paleta de comandos: buscar y ejecutar cualquier acción"),
    ("Ctrl+1 … Ctrl+5", "Mostrar / ocultar ventanas: Gemelo digital, Posturas, Gráficas, Entrenamiento, Dispositivo"),
    ("Ctrl+6 / Ctrl+7", "Mostrar / ocultar el Visor EMG y el Analizador EMG"),
    ("Ctrl+J", "Mostrar / ocultar la Consola"),
    ("Ctrl+Shift+K", "Mostrar / ocultar Comandos (catálogo e historial)"),
    ("Ctrl+I", "Asistente IA: abrir y escribir"),
    ("Ctrl+Shift+G", "Nueva gráfica (otra ventana con las señales que elijas)"),
    ("Ctrl+B", "Mostrar / ocultar la barra lateral"),
    ("Alt+1 … Alt+8", "Enviar el gesto 1 … 8"),
    ("Esc", "PARAR: frena todos los motores"),
    ("Ctrl+M", "Control por voz: empezar / dejar de escuchar"),
    ("Ctrl+R", "Empezar / detener la grabación de la sesión"),
    ("Ctrl+O", "Reproducir una sesión grabada"),
    ("Espacio", "Durante una reproducción: pausa / continuar  (← → saltan en la barra de tiempo)"),
    ("F1", "Esta ayuda"),
    ("↑ / ↓", "En la consola: comandos anteriores"),
    ("Tab", "En la consola: autocompletar el comando"),
]


class _Base(QDialog):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.setObjectName("infoDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(26, 22, 26, 20)
        self.lay.setSpacing(12)
        ctx = getattr(parent, "ctx", None)
        if ctx is not None:
            style_titlebar(self, ctx.theme)

    def add_close(self) -> None:
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Cerrar")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        self.lay.addSpacing(6)
        self.lay.addLayout(row)


class ShortcutsDialog(_Base):
    def __init__(self, parent):
        super().__init__(parent, "Atajos de teclado")
        title = QLabel("Atajos de teclado")
        title.setObjectName("pageTitle")
        self.lay.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        for row, (keys, text) in enumerate(SHORTCUTS):
            k = QLabel(keys)
            k.setObjectName("kbd")
            k.setAlignment(Qt.AlignCenter)
            grid.addWidget(k, row, 0, Qt.AlignLeft)
            grid.addWidget(QLabel(text), row, 1)
        self.lay.addLayout(grid)
        note = QLabel("Los atajos de gestos y Esc solo envían comandos si hay una mano conectada (real o simulada).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        self.add_close()


class VoiceHelpDialog(_Base):
    """Las órdenes que entiende el control por voz."""

    GROUPS = [
        ("Parar", "para · ¡para, para! · alto · quieto · detente"),
        ("Mano", "abre la mano · cierra la mano · puño · pinza · señala"),
        ("Gestos", "por su nombre (mano abierta, índice y medio… gancho) · gesto uno … gesto ocho"),
        ("Dedos", "abre / cierra el índice, el medio, el anular · abre / cierra el pulgar"),
        ("Modo", "modo manual · modo demostración"),
        ("App", "gemelo digital · posturas · gráficas · entrenamiento · graba · deja de grabar"),
    ]

    def __init__(self, parent, postures: list[str]):
        super().__init__(parent, "Control por voz")
        self.setFixedWidth(600)
        title = QLabel("Órdenes de voz")
        title.setObjectName("pageTitle")
        self.lay.addWidget(title)
        intro = QLabel("Di la orden sola, con naturalidad. Funciona sin internet. Una orden solo se ejecuta si la "
                       "frase entera es una orden (lo que se dice en una conversación no mueve la mano); "
                       "«para» se acepta siempre.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        self.lay.addWidget(intro)
        groups = list(self.GROUPS)
        if postures:
            groups.insert(4, ("Mis posturas", " · ".join(p.lower() for p in postures)))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        for row, (name, phrases) in enumerate(groups):
            cap = QLabel(name.upper())
            cap.setObjectName("caption")
            grid.addWidget(cap, row, 0, Qt.AlignLeft | Qt.AlignTop)
            text = QLabel(phrases)
            text.setWordWrap(True)
            grid.addWidget(text, row, 1)
        grid.setColumnStretch(1, 1)
        self.lay.addLayout(grid)
        self.add_close()


class AboutDialog(_Base):
    def __init__(self, parent):
        super().__init__(parent, f"Acerca de {APP_NAME}")
        self.setFixedWidth(520)
        head = QHBoxLayout()
        head.setSpacing(14)
        badge = QLabel()
        badge.setFixedSize(56, 56)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #1e3a8a);"
                            "border-radius: 15px;")
        badge.setPixmap(logo_badge(42, "#ffffff", asset("biomec_logo_dark.png")))
        head.addWidget(badge)
        names = QVBoxLayout()
        names.setSpacing(0)
        t = QLabel(f"{ORG_NAME} · {APP_NAME}")
        t.setObjectName("pageTitle")
        v = QLabel(f"Versión {APP_VERSION}  ·  Centro de control de la mano protésica")
        v.setObjectName("muted")
        names.addWidget(t)
        names.addWidget(v)
        head.addLayout(names, 1)
        self.lay.addLayout(head)

        def section(title: str, body: str) -> None:
            cap = QLabel(title.upper())
            cap.setObjectName("caption")
            txt = QLabel(body)
            txt.setWordWrap(True)
            txt.setTextFormat(Qt.RichText)
            txt.setOpenExternalLinks(True)
            self.lay.addWidget(cap)
            self.lay.addWidget(txt)

        section("Proyecto",
                "Proyecto BIOMEC de la Universidad de Málaga: prótesis de mano mioeléctrica de bajo coste. "
                "Esta aplicación controla la mano a través de una ESP32-C6 (USB ↔ ESP-NOW) e incluye un "
                "simulador, un gemelo digital del diseño en SolidWorks, entrenamiento de IA con señales EMG "
                "y un asistente con IA.")
        controller = getattr(parent, "updates", None)
        if controller is not None and controller.installed:
            section("Actualizaciones",
                    "Busca versiones nuevas en GitHub al arrancar y avisa en la cabecera.")
            row = QHBoxLayout()
            auto = QCheckBox("Buscar actualizaciones al arrancar")
            auto.setChecked(controller.auto)
            auto.toggled.connect(lambda on: setattr(controller, "auto", on))
            row.addWidget(auto)
            row.addStretch(1)
            now = QPushButton("Buscar ahora")
            now.clicked.connect(lambda: (self.accept(), parent.check_updates(manual=True)))
            row.addWidget(now)
            self.lay.addLayout(row)
        elif controller is not None:
            section("Actualizaciones",
                    "Esta copia (código o dist) no se actualiza sola; la instalada sí. "
                    f"Instalador: <a href='{RELEASES_PAGE}'>GitHub → Releases</a>.")
        section("Seguridad",
                "El botón <b>Parar</b> es una parada por software: envía PARAR por radio y depende de la "
                "comunicación. <b>No sustituye a una parada de emergencia física</b> ni a cortar la alimentación.")
        section("Referencias de diseño",
                "Interfaz sobria con el color reservado para estados (ISA-101, interfaces de alto rendimiento). "
                "Umbral de latencia según Farrell y Weir, <i>The Optimal Controller Delay for Myoelectric "
                "Prostheses</i>, IEEE TNSRE 15(1):111-118, 2007 (óptimo 100-125 ms para el control completo). "
                "Galería de gestos y editor de posturas inspirados en las apps de prótesis comerciales "
                "(Össur i-Limb, PSYONIC). Pestaña Entrenamiento como las estaciones de calibración de Coapt y "
                "Ottobock Myo Plus: características de Hudgins et al. (IEEE TBME, 1993) y LDA con ventanas "
                "solapadas y voto por mayoría (Englehart y Hudgins, IEEE TBME, 2003). Sesiones grabadas al "
                "estilo de rosbag / Foxglove.")
        section("Software de terceros",
                "Qt for Python / PySide6 (LGPL v3) · pyqtgraph (MIT) · PyOpenGL (BSD) · NumPy (BSD) · "
                "pyserial (BSD) · SDK de Anthropic para el asistente (MIT) · iconos basados en Lucide (ISC).")
        self.add_close()
