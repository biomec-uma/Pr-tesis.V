"""Consola: escribir comandos y ver todo lo que llega del puente y de la mano."""

import html

from PySide6.QtCore import QEvent, QStringListModel, Qt
from PySide6.QtWidgets import (
    QCheckBox, QCompleter, QFileDialog, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..core.protocol import MessageKind
from ..ui.theme import PALETTES
from .base import BasePage

# Cómo se muestra cada tipo de mensaje: (etiqueta, clave de color en la paleta)
_STYLE = {
    MessageKind.TX: ("TX →", "tx"),
    MessageKind.ACK: ("ACK", "ok"),
    MessageKind.ERROR: ("ERR", "error"),
    MessageKind.BRIDGE: ("PUENTE", "muted"),
    MessageKind.DATA: ("DATA", "muted"),
    MessageKind.TEXT: ("RX ←", "text"),
    MessageKind.SYSTEM: ("APP", "warn"),
}


class ConsolePage(BasePage):
    title = "Consola"
    icon = "⌨"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._history: list[str] = []
        self._history_pos = 0
        self._plain_log: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card, layout = self.card("Monitor")

        toolbar = QHBoxLayout()
        self.show_data = QCheckBox("Mostrar telemetría (DATA)")
        self.autoscroll = QCheckBox("Autodesplazar")
        self.autoscroll.setChecked(True)
        clear_btn = QPushButton("Limpiar")
        clear_btn.clicked.connect(self.clear)
        save_btn = QPushButton("Guardar registro…")
        save_btn.clicked.connect(self.save_log)
        toolbar.addWidget(self.show_data)
        toolbar.addWidget(self.autoscroll)
        toolbar.addStretch(1)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(save_btn)
        layout.addLayout(toolbar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(3000)
        self.view.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        layout.addWidget(self.view, 1)

        send_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un comando (p. ej. ABRIR, DEDO 2 50). ↑/↓ = historial, Tab = autocompletar")
        self.input.returnPressed.connect(self.send)
        self.input.installEventFilter(self)
        self._completer_model = QStringListModel(ctx.catalog.names())
        completer = QCompleter(self._completer_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.input.setCompleter(completer)
        self.raw_mode = QCheckBox("Sin validar")
        self.raw_mode.setToolTip("Envía el texto tal cual, aunque no esté en el catálogo (para pruebas).")
        self.send_btn = QPushButton("Enviar")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        send_row.addWidget(self.input, 1)
        send_row.addWidget(self.raw_mode)
        send_row.addWidget(self.send_btn)
        layout.addLayout(send_row)

        root.addWidget(card)
        ctx.prefill_command.connect(self.prefill)
        self.on_connection_changed(ctx.connected, "")

    # ---------------------------------------------------------------- envío
    def send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        ok = self.ctx.send_raw(text) if self.raw_mode.isChecked() else self.ctx.send_command(text)
        if ok:
            if not self._history or self._history[-1] != text:
                self._history.append(text)
            self._history_pos = len(self._history)
            self.input.clear()

    def prefill(self, text: str) -> None:
        self.input.setText(text)
        self.input.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.KeyPress and self._history:
            if event.key() == Qt.Key_Up:
                self._history_pos = max(0, self._history_pos - 1)
                self.input.setText(self._history[self._history_pos])
                return True
            if event.key() == Qt.Key_Down:
                self._history_pos = min(len(self._history), self._history_pos + 1)
                self.input.setText(self._history[self._history_pos] if self._history_pos < len(self._history) else "")
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------- recepción
    def on_message(self, msg) -> None:
        label, color_key = _STYLE.get(msg.kind, ("", "text"))
        stamp = msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
        plain = f"[{stamp}] {label:<7} {msg.text}"
        self._plain_log.append(plain)
        if len(self._plain_log) > 20000:
            del self._plain_log[:5000]
        if msg.kind is MessageKind.DATA and not self.show_data.isChecked():
            return
        color = PALETTES[self.ctx.theme][color_key]
        self.view.appendHtml(
            f'<span style="color:{PALETTES[self.ctx.theme]["muted"]}">[{stamp}]</span> '
            f'<b style="color:{color}">{label}</b> '
            f'<span style="color:{color}">{html.escape(msg.text)}</span>'
        )
        if self.autoscroll.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def on_catalog_reloaded(self) -> None:
        self._completer_model.setStringList(self.ctx.catalog.names())

    def on_connection_changed(self, connected: bool, info: str) -> None:
        self.send_btn.setEnabled(connected)

    def clear(self) -> None:
        self.view.clear()

    def save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Guardar registro", "registro_biomec.txt", "Texto (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self._plain_log))
            self.ctx.notify(f"Registro guardado en {path}")
