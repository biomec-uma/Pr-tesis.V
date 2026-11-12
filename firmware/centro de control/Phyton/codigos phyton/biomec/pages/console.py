"""Consola: ventana con el registro de mensajes y una línea para escribir comandos.

    ☐ Telemetría  ☑ Autodesplazar                      [Limpiar] [Guardar]
    12:01:03.120  TX   GESTO 3
    12:01:03.251  ACK  GESTO 3 Índice y anular
    [ escribir comando: GESTO 3, ABRIR…        ] ☐ Sin validar [Enviar]

Atajo: Ctrl+J muestra u oculta la ventana (lo gestiona la ventana principal). No hace falta leerlo
todo: la telemetría se ve mejor en Gráficas y aquí está oculta salvo que se marque «Telemetría».
"""

import html

from PySide6.QtCore import QEvent, QStringListModel, Qt
from PySide6.QtWidgets import (
    QCheckBox, QCompleter, QFileDialog, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout,
)

from ..core.protocol import MessageKind
from ..ui.theme import PALETTES
from .base import BasePage

# Cómo se muestra cada tipo de mensaje: (etiqueta, clave de color en la paleta)
_STYLE = {
    MessageKind.TX: ("TX", "tx"),
    MessageKind.ACK: ("ACK", "ok"),
    MessageKind.ERROR: ("ERR", "error"),
    MessageKind.BRIDGE: ("PUENTE", "muted"),
    MessageKind.DATA: ("DATA", "subtle"),
    MessageKind.EMG: ("EMG", "subtle"),
    MessageKind.TEXT: ("RX", "text"),
    MessageKind.SYSTEM: ("APP", "warn"),
}
_LABEL_WIDTH = 7


class ConsolePanel(BasePage):
    title = "Consola"
    icon = "terminal"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._history: list[str] = []
        self._history_pos = 0
        self._plain_log: list[str] = []
        self.setMinimumSize(360, 160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # --- opciones
        head = QHBoxLayout()
        head.setSpacing(8)
        self.show_data = QCheckBox("Telemetría")
        self.show_data.setToolTip("Muestra también las líneas DATA (telemetría) y EMG (señales musculares):\n"
                                  "pueden ser decenas por segundo. Se ven mejor en Gráficas.")
        self.autoscroll = QCheckBox("Autodesplazar")
        self.autoscroll.setChecked(True)
        self.clear_btn = self.button("Limpiar", "trash", "ghost", "Borra el monitor (el registro guardable se conserva)")
        self.clear_btn.clicked.connect(self.clear)
        self.save_btn = self.button("Guardar", "download", "ghost", "Guarda todo el registro en un archivo .txt")
        self.save_btn.clicked.connect(self.save_log)
        head.addWidget(self.show_data)
        head.addWidget(self.autoscroll)
        head.addStretch(1)
        head.addWidget(self.clear_btn)
        head.addWidget(self.save_btn)
        layout.addLayout(head)

        # --- registro
        self.view = QPlainTextEdit()
        self.view.setObjectName("log")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(3000)
        self.view.setMinimumHeight(60)
        layout.addWidget(self.view, 1)

        # --- línea de envío
        send_row = QHBoxLayout()
        send_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un comando: GESTO 3, ABRIR, PULGAR 90…   ↑↓ historial · Tab autocompletar")
        self.input.returnPressed.connect(self.send)
        self.input.installEventFilter(self)
        self._completer_model = QStringListModel(ctx.catalog.names())
        completer = QCompleter(self._completer_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.input.setCompleter(completer)
        self.raw_mode = QCheckBox("Sin validar")
        self.raw_mode.setToolTip("Envía el texto tal cual, aunque no esté en el catálogo (para pruebas).")
        self.send_btn = self.button("Enviar", "send", "primary")
        self.send_btn.clicked.connect(self.send)
        send_row.addWidget(self.input, 1)
        send_row.addWidget(self.raw_mode)
        send_row.addWidget(self.send_btn)
        layout.addLayout(send_row)

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

    def focus_input(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

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
        stream = msg.kind in (MessageKind.DATA, MessageKind.EMG)
        if msg.kind is not MessageKind.EMG:  # el EMG (25 líneas/s) se guarda en las sesiones, no en el registro
            self._plain_log.append(f"[{stamp}] {label:<7} {msg.text}")
            if len(self._plain_log) > 20000:
                del self._plain_log[:5000]
        if stream and not self.show_data.isChecked():
            return
        p = PALETTES[self.ctx.theme]
        color = p[color_key]
        pad = "&nbsp;" * (_LABEL_WIDTH - len(label))
        body_color = p["text"] if msg.kind in (MessageKind.TEXT, MessageKind.BRIDGE) else color
        self.view.appendHtml(
            f'<span style="color:{p["subtle"]}">{stamp}</span>&nbsp;&nbsp;'
            f'<b style="color:{color}">{label}</b>{pad}'
            f'<span style="color:{body_color}">{html.escape(msg.text)}</span>'
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


ConsolePage = ConsolePanel  # nombre anterior
