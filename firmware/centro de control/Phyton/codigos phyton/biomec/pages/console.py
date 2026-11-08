"""Consola (panel inferior, visible en todas las pestañas).

Plegada:    [▸] Consola   última respuesta…                 [ escribir comando ] [Enviar]
Desplegada: cabecera con opciones + registro completo + línea para escribir.
Atajo: Ctrl+J pliega/despliega (lo gestiona la ventana principal).
"""

import html

from PySide6.QtCore import QEvent, QSettings, QSize, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QCompleter, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, ORG_NAME
from ..core.protocol import MessageKind
from ..ui.icons import icon
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
    expanded_changed = Signal(bool)

    def __init__(self, ctx):
        super().__init__(ctx)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self._history: list[str] = []
        self._history_pos = 0
        self._plain_log: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName("card")
        root.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # --- cabecera
        head = QHBoxLayout()
        head.setSpacing(8)
        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("ghost")
        self.toggle_btn.setIconSize(QSize(16, 16))
        self.toggle_btn.setToolTip("Desplegar / plegar la consola (Ctrl+J)")
        self.toggle_btn.clicked.connect(lambda: self.set_expanded(not self.expanded))
        title = QLabel("Consola")
        title.setObjectName("cardTitle")
        self.last_line = QLabel()
        self.last_line.setObjectName("muted")
        self.last_line.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # no empuja al resto
        self.show_data = QCheckBox("Telemetría")
        self.show_data.setToolTip("Muestra también las líneas DATA (telemetría) y EMG (señales musculares):\n"
                                  "pueden ser decenas por segundo")
        self.autoscroll = QCheckBox("Autodesplazar")
        self.autoscroll.setChecked(True)
        self.clear_btn = self.button("Limpiar", "trash", "ghost", "Borra el monitor (el registro guardable se conserva)")
        self.clear_btn.clicked.connect(self.clear)
        self.save_btn = self.button("Guardar", "download", "ghost", "Guarda todo el registro en un archivo .txt")
        self.save_btn.clicked.connect(self.save_log)
        head.addWidget(self.toggle_btn)
        head.addWidget(title)
        head.addSpacing(6)
        head.addWidget(self.last_line, 3)
        head.addStretch(1)
        self._expanded_only = [self.show_data, self.autoscroll, self.clear_btn, self.save_btn]
        for w in self._expanded_only:
            head.addWidget(w)
        layout.addLayout(head)

        # --- registro
        self.view = QPlainTextEdit()
        self.view.setObjectName("log")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(3000)
        self.view.setMinimumHeight(80)
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
        self.expanded = self.settings.value("console_expanded", True, type=bool)
        self.set_expanded(self.expanded, save=False)

    # -------------------------------------------------------- plegar
    def set_expanded(self, expanded: bool, save: bool = True) -> None:
        self.expanded = expanded
        self.view.setVisible(expanded)
        for w in self._expanded_only:
            w.setVisible(expanded)
        self.last_line.setVisible(not expanded)
        self._paint_toggle()
        if save:
            self.settings.setValue("console_expanded", expanded)
        self.expanded_changed.emit(expanded)

    def _paint_toggle(self) -> None:
        self.toggle_btn.setIcon(icon("chevron_down" if self.expanded else "chevron_up",
                                     PALETTES[self.ctx.theme]["muted"], 16))

    def on_theme_changed(self, theme: str) -> None:
        self._paint_toggle()

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
        if not stream:  # resumen visible con la consola plegada
            self.last_line.setText(f"{label}  {msg.text}")
            self.last_line.setStyleSheet(f"color: {color if msg.kind is not MessageKind.TEXT else p['muted']};")
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
