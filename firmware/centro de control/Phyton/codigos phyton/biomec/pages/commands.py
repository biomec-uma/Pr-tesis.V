"""Catálogo de comandos: consulta, búsqueda e historial de lo enviado."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from ..core.protocol import MessageKind
from .base import BasePage

_COLUMNS = ["Comando", "Uso", "Destino", "Categoría", "Descripción"]


class CommandsPage(BasePage):
    title = "Comandos"
    icon = "☰"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Vertical)

        # --- Catálogo
        card, layout = self.card("Catálogo de comandos")
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nombre, categoría o descripción…")
        self.search.textChanged.connect(self.populate)
        reload_btn = QPushButton("Recargar")
        reload_btn.setToolTip("Vuelve a leer config/commands.json")
        reload_btn.clicked.connect(self.reload)
        open_btn = QPushButton("Editar JSON")
        open_btn.clicked.connect(lambda: os.startfile(self.ctx.catalog.path))
        top.addWidget(self.search, 1)
        top.addWidget(reload_btn)
        top.addWidget(open_btn)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(True)
        self.table.doubleClicked.connect(self.use_selected)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.hint = QLabel("Doble clic en un comando para llevarlo a la consola.")
        self.hint.setObjectName("muted")
        self.use_btn = QPushButton("Usar en consola")
        self.use_btn.clicked.connect(self.use_selected)
        self.send_btn = QPushButton("Enviar ahora")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send_selected)
        actions.addWidget(self.hint, 1)
        actions.addWidget(self.use_btn)
        actions.addWidget(self.send_btn)
        layout.addLayout(actions)
        splitter.addWidget(card)

        # --- Historial
        hcard, hlayout = self.card("Historial de comandos enviados")
        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["Hora", "Línea enviada", "Respuesta"])
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.horizontalHeader().setStretchLastSection(True)
        self.history.setColumnWidth(1, 260)
        hlayout.addWidget(self.history, 1)
        splitter.addWidget(hcard)
        splitter.setSizes([520, 220])

        root.addWidget(splitter)
        self.populate()

    # -------------------------------------------------------------- catálogo
    def reload(self) -> None:
        self.ctx.reload_catalog()

    def on_catalog_reloaded(self) -> None:
        self.populate()

    def populate(self, *_):
        needle = self.search.text().strip().lower()
        rows = [
            c for c in self.ctx.catalog
            if not needle or needle in f"{c.name} {c.category} {c.description}".lower()
        ]
        self.table.setRowCount(len(rows))
        for r, cmd in enumerate(rows):
            for col, value in enumerate([cmd.name, cmd.usage, cmd.target, cmd.category, cmd.description]):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, cmd.name)
                self.table.setItem(r, col, item)
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self._update_buttons()

    def _selected(self):
        items = self.table.selectedItems()
        return self.ctx.catalog.get(items[0].data(Qt.UserRole)) if items else None

    def _update_buttons(self):
        cmd = self._selected()
        self.use_btn.setEnabled(cmd is not None)
        self.send_btn.setEnabled(cmd is not None and not cmd.args and self.ctx.connected)

    def use_selected(self, *_):
        cmd = self._selected()
        if cmd:
            self.ctx.prefill_command.emit(cmd.name + (" " if cmd.args else ""))
            self.window().show_page("Consola")

    def send_selected(self):
        cmd = self._selected()
        if cmd:
            self.ctx.send_command(cmd.name)

    # ------------------------------------------------------------- historial
    def on_message(self, msg) -> None:
        if msg.kind is MessageKind.TX:
            row = self.history.rowCount()
            self.history.insertRow(row)
            self.history.setItem(row, 0, QTableWidgetItem(msg.timestamp.strftime("%H:%M:%S")))
            self.history.setItem(row, 1, QTableWidgetItem(msg.text))
            self.history.setItem(row, 2, QTableWidgetItem("…"))
            self.history.scrollToBottom()
        elif msg.kind in (MessageKind.ACK, MessageKind.ERROR) and self.history.rowCount():
            last = self.history.item(self.history.rowCount() - 1, 2)
            if last and last.text() == "…":
                last.setText(f"{msg.kind.value} {msg.text}")

    def on_connection_changed(self, connected, info):
        self._update_buttons()

    def on_shown(self):
        self._update_buttons()
