"""Barra superior de conexión USB con la ESP32-C6 puente."""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from ..core.serial_link import SerialLink, available_ports
from .theme import PALETTES

BAUD_RATES = ["115200", "230400", "460800", "921600"]


class ConnectionBar(QWidget):
    def __init__(self, link: SerialLink, ctx):
        super().__init__()
        self.link = link
        self.ctx = ctx
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(10)

        self.led = QLabel("●")
        self.state = QLabel("Desconectado")
        self.state.setMinimumWidth(170)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(280)
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setToolTip("Buscar puertos COM")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUD_RATES)
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self.toggle)

        row.addWidget(self.led)
        row.addWidget(self.state)
        row.addStretch(1)
        row.addWidget(QLabel("Puerto"))
        row.addWidget(self.port_combo)
        row.addWidget(self.refresh_btn)
        row.addWidget(QLabel("Baudios"))
        row.addWidget(self.baud_combo)
        row.addWidget(self.connect_btn)

        link.connection_changed.connect(self._on_connection_changed)
        ctx.theme_changed.connect(lambda _t: self._on_connection_changed(link.is_connected, ""))
        self.refresh_ports()
        self._on_connection_changed(False, "")

    def refresh_ports(self) -> None:
        previous = self.port_combo.currentData()
        self.port_combo.clear()
        ports = available_ports()
        for device, description in ports:
            self.port_combo.addItem(f"{device} — {description}", device)
        if not ports:
            self.port_combo.addItem("No se detectan puertos COM", None)
        index = self.port_combo.findData(previous)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        self.connect_btn.setEnabled(self.link.is_connected or bool(ports))

    def toggle(self) -> None:
        if self.link.is_connected:
            self.link.disconnect()
            return
        port = self.port_combo.currentData()
        if port:
            self.link.connect(port, int(self.baud_combo.currentText()))

    def _on_connection_changed(self, connected: bool, info: str) -> None:
        palette = PALETTES[self.ctx.theme]
        self.led.setStyleSheet(f"color: {palette['ok' if connected else 'error']}; font-size: 14pt;")
        self.state.setText(f"Conectado · {info}" if connected and info else
                           "Conectado" if connected else "Desconectado")
        self.connect_btn.setText("Desconectar" if connected else "Conectar")
        for widget in (self.port_combo, self.refresh_btn, self.baud_combo):
            widget.setEnabled(not connected)
        if not connected:
            self.refresh_ports()
