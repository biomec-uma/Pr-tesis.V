"""Panel "Dispositivo" (barra lateral): elegir mano real o simulación, y conectar.

    ┌ Dispositivo ───────────────┐
    │ ● Desconectado             │
    │ [ Mano real ][ Simulación ]│
    │ [ COM7 — …           ▾] ⟳  │   (solo en modo real)
    │ [ 115200             ▾]    │
    │ [        Conectar        ] │
    └────────────────────────────┘

- Mano real: los comandos van por USB a la ESP32-C6 puente y de ahí a la mano.
- Simulación: los contesta una mano virtual dentro de la app (core/simulator.py).
Cambiar de modo estando conectado desconecta primero, para que nunca haya
dudas de a dónde van los comandos.
"""

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import APP_NAME, ORG_NAME
from ..core.serial_link import SIMULATOR_PORT, SerialLink, available_ports
from .icons import icon, nav_icon
from .theme import PALETTES

BAUD_RATES = ["115200", "230400", "460800", "921600"]


class ConnectionBar(QWidget):
    mode_changed = Signal(bool)  # True = simulación

    def __init__(self, link: SerialLink, ctx):
        super().__init__()
        self.link = link
        self.ctx = ctx
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.setObjectName("devicePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)  # sin esto, una subclase de QWidget no pinta su fondo/borde
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(8)

        # --- Estado
        head = QHBoxLayout()
        head.setSpacing(6)
        self.led = QLabel("●")
        self.state = QLabel("Desconectado")
        self.state.setObjectName("value")
        head.addWidget(self.led)
        head.addWidget(self.state, 1)
        col.addLayout(head)
        self.hand_label = QLabel()
        self.hand_label.setObjectName("muted")
        self.hand_label.setContentsMargins(18, 0, 0, 0)
        col.addWidget(self.hand_label)
        ctx.hand_status_changed.connect(lambda *_: self._refresh_look())

        # --- Selector de modo
        seg_box = QWidget()  # control segmentado: las dos opciones dentro de una cápsula
        seg_box.setObjectName("segmented")
        seg_box.setAttribute(Qt.WA_StyledBackground, True)
        seg = QHBoxLayout(seg_box)
        seg.setContentsMargins(3, 3, 3, 3)
        seg.setSpacing(2)
        self.real_btn = QPushButton("Real")
        self.real_btn.setObjectName("segmentReal")
        self.real_btn.setToolTip("Los comandos van por USB a la ESP32-C6 y de ahí a la mano")
        self.sim_btn = QPushButton("Simulación")
        self.sim_btn.setObjectName("segmentSim")
        self.sim_btn.setToolTip("Los comandos los contesta una mano virtual: no se mueve nada real")
        self.mode_group = QButtonGroup(self)
        for i, btn in enumerate((self.real_btn, self.sim_btn)):
            btn.setCheckable(True)
            btn.setIconSize(QSize(15, 15))
            self.mode_group.addButton(btn, i)
            seg.addWidget(btn, 1)
        self.mode_group.idClicked.connect(lambda i: self.set_simulated(i == 1))
        col.addWidget(seg_box)

        # --- Puerto (solo en modo real)
        self.real_box = QWidget()
        real = QVBoxLayout(self.real_box)
        real.setContentsMargins(0, 0, 0, 2)
        real.setSpacing(6)
        port_row = QHBoxLayout()
        port_row.setSpacing(4)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumContentsLength(10)
        self.port_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.port_combo.setToolTip("Puerto COM de la ESP32-C6 puente")
        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.setToolTip("Buscar puertos COM")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_btn)
        real.addLayout(port_row)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUD_RATES)
        self.baud_combo.setToolTip("Velocidad del puerto serie (baudios)")
        real.addWidget(self.baud_combo)
        col.addWidget(self.real_box)

        self.sim_label = QLabel("La mano virtual responde dentro de la app.")
        self.sim_label.setObjectName("muted")
        self.sim_label.setWordWrap(True)
        col.addWidget(self.sim_label)

        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self.toggle)
        col.addWidget(self.connect_btn)

        link.connection_changed.connect(self._on_connection_changed)
        ctx.theme_changed.connect(lambda _t: self._refresh_look())
        self.simulated = self.settings.value("simulated", False, type=bool)
        (self.sim_btn if self.simulated else self.real_btn).setChecked(True)
        self._apply_mode()
        self._on_connection_changed(False, "")

    # ------------------------------------------------------------------ modo
    def set_simulated(self, simulated: bool) -> None:
        if simulated == self.simulated:
            return
        if self.link.is_connected:
            self.link.disconnect()
        self.simulated = simulated
        self.settings.setValue("simulated", simulated)
        self._apply_mode()
        self.ctx.notify("Modo SIMULACIÓN: los comandos no llegan a la mano real." if simulated
                        else "Modo MANO REAL: los comandos irán por USB a la ESP32-C6.")

    def _apply_mode(self) -> None:
        self.real_box.setVisible(not self.simulated)
        self.sim_label.setVisible(self.simulated)
        self.refresh_ports()
        self._on_connection_changed(self.link.is_connected, "")
        self.mode_changed.emit(self.simulated)

    # ------------------------------------------------------------- conexión
    def refresh_ports(self) -> None:
        previous = self.port_combo.currentData()
        self.port_combo.clear()
        ports = available_ports()
        for device, description in ports:
            self.port_combo.addItem(f"{device} · {description}", device)
            self.port_combo.setItemData(self.port_combo.count() - 1, f"{device} — {description}", 3)  # tooltip
        if not ports:
            self.port_combo.addItem("Sin puertos COM", None)
        index = self.port_combo.findData(previous)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        self.connect_btn.setEnabled(self.link.is_connected or self.simulated or bool(ports))

    def toggle(self) -> None:
        if self.link.is_connected:
            self.link.disconnect()
        elif self.simulated:
            self.link.connect(SIMULATOR_PORT, 115200)
        elif self.port_combo.currentData():
            self.link.connect(self.port_combo.currentData(), int(self.baud_combo.currentText()))

    def _on_connection_changed(self, connected: bool, info: str) -> None:
        if connected and self.simulated:
            self.state.setText("Simulación en marcha")
        elif connected:
            self.state.setText(f"Conectado · {self.link.port_name}")
        else:
            self.state.setText("Desconectado")
        self.connect_btn.setText("Desconectar" if connected else "Conectar")
        # Conectar es la acción principal (azul); conectado, Desconectar pasa a botón secundario
        kind = "" if connected else "primary"
        if self.connect_btn.objectName() != kind:
            self.connect_btn.setObjectName(kind)
            self.connect_btn.style().unpolish(self.connect_btn)
            self.connect_btn.style().polish(self.connect_btn)
        for widget in (self.port_combo, self.refresh_btn, self.baud_combo):
            widget.setEnabled(not connected)
        if not connected:
            self.refresh_ports()
        self._refresh_look()

    def _refresh_look(self) -> None:
        p = PALETTES[self.ctx.theme]
        connected = self.link.is_connected
        self.led.setStyleSheet(f"color: {p['ok'] if connected else p['subtle']}; font-size: 11pt;")
        self.real_btn.setIcon(nav_icon("plug", p["muted"], p["accent_text"], 15))
        self.sim_btn.setIcon(nav_icon("flask", p["muted"], p["sim_text"], 15))
        self.refresh_btn.setIcon(icon("refresh", p["muted"], 15))
        self.connect_btn.setIcon(icon("power", p["muted"] if connected else "#ffffff", 15))
        # Segunda línea: la mano (el puente puede estar conectado y la mano apagada)
        status = self.ctx.hand_status
        if status == "online":
            color, text = p["ok"], "Mano: en línea"
        elif status == "silent":
            color, text = p["warn"], "Mano: sin respuesta"
        else:
            color, text = p["subtle"], "Mano: —"
        self.hand_label.setText(f'<span style="color:{color}">●</span>&nbsp; {text}')
        self.hand_label.setVisible(connected)
