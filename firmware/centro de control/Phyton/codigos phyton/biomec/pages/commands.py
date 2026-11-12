"""Ventana Comandos: catálogo e historial.

    [ Catálogo ][ Historial ]        ⟳ ✎
    🔍 buscar…
    ▾ Gestos
        GESTO
        ABRIR …
    ▸ Dedos
    ┌ ficha del comando seleccionado ┐
    │ GESTO <numero>                 │
    │ descripción, argumentos…       │
    │ [Insertar en consola] [Enviar] │
    └────────────────────────────────┘
Atajo: Ctrl+Mayús+K muestra la ventana con el buscador listo.
"""

import os

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.protocol import MessageKind
from ..ui.context import latency_level
from ..ui.icons import icon
from ..ui.theme import MONO, PALETTES
from ..ui.widgets import Segmented
from .base import BasePage


def _mono(size: float = 9.5, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies([x.strip(" '") for x in MONO.split(",")])
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


class CommandsPanel(BasePage):
    title = "Comandos"
    icon = "list"
    close_requested = Signal()

    def __init__(self, ctx):
        super().__init__(ctx)
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # --- pestañas Catálogo / Historial + acciones del catálogo
        head = QHBoxLayout()
        head.setSpacing(2)
        tabs = Segmented(("Catálogo", "Historial"))
        self.tab_group = tabs.group
        self.stack = QStackedWidget()
        self.tab_group.button(0).setChecked(True)
        self.tab_group.idClicked.connect(self.stack.setCurrentIndex)
        head.addWidget(tabs, 1)
        head.addSpacing(4)
        reload_btn = self.button("", "refresh", "ghost", "Recargar config/commands.json")
        reload_btn.clicked.connect(self.ctx.reload_catalog)
        edit_btn = self.button("", "pencil", "ghost", "Editar config/commands.json (añadir o cambiar comandos)")
        edit_btn.clicked.connect(lambda: os.startfile(self.ctx.catalog.path))
        for b in (reload_btn, edit_btn):
            head.addWidget(b)
        layout.addLayout(head)
        layout.addWidget(self.stack, 1)

        # --- Catálogo
        catalog = QWidget()
        cl = QVBoxLayout(catalog)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar comando…")
        self.search.setClearButtonEnabled(True)
        self._search_action = self.search.addAction(icon("search", "#888888"), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self.populate)
        self.search.returnPressed.connect(self._insert_first_match)
        cl.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.tree.setIconSize(QSize(14, 14))
        self.tree.setMinimumHeight(130)
        self.tree.currentItemChanged.connect(lambda *_: self._show_details())
        self.tree.itemDoubleClicked.connect(lambda item, _c: self.insert_selected())
        cl.addWidget(self.tree, 1)

        # ficha del comando
        self.details = QWidget()
        self.details.setObjectName("inset")
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.setSpacing(4)
        self.d_usage = QLabel()
        self.d_usage.setFont(_mono(9.5, True))
        self.d_usage.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.d_usage.setWordWrap(True)
        self.d_meta = QLabel()
        self.d_meta.setObjectName("muted")
        self.d_desc = QLabel()
        self.d_desc.setWordWrap(True)
        self.d_args = QLabel()
        self.d_args.setObjectName("muted")
        self.d_args.setWordWrap(True)
        btns = QHBoxLayout()
        self.insert_btn = self.button("Insertar en consola", "corner", "", "Lo escribe en la consola para completarlo y enviarlo")
        self.insert_btn.clicked.connect(self.insert_selected)
        self.send_btn = self.button("Enviar", "send", "primary", "Solo para comandos sin argumentos")
        self.send_btn.clicked.connect(self.send_selected)
        btns.addWidget(self.insert_btn, 1)
        btns.addWidget(self.send_btn)
        for w in (self.d_usage, self.d_meta, self.d_desc, self.d_args):
            dl.addWidget(w)
        dl.addLayout(btns)
        cl.addWidget(self.details)
        self.empty = QLabel("Selecciona un comando para ver cómo se usa.\nDoble clic para insertarlo en la consola.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        cl.addWidget(self.empty)
        self.stack.addWidget(catalog)

        # --- Historial
        hist = QWidget()
        hl = QVBoxLayout(hist)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        self.history = QListWidget()
        self.history.setFocusPolicy(Qt.NoFocus)
        self.history.setWordWrap(True)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history.itemDoubleClicked.connect(
            lambda item: self.ctx.prefill_command.emit(item.data(Qt.UserRole) or ""))
        hl.addWidget(self.history, 1)
        hrow = QHBoxLayout()
        hint = QLabel("Doble clic para repetir un comando")
        hint.setObjectName("muted")
        clear = self.button("Vaciar", "trash", "ghost")
        clear.clicked.connect(self.history.clear)
        hrow.addWidget(hint, 1)
        hrow.addWidget(clear)
        hl.addLayout(hrow)
        self.stack.addWidget(hist)

        self._pending: QListWidgetItem | None = None
        self._last_latency: float | None = None
        ctx.latency_measured.connect(lambda ms, _cmd: setattr(self, "_last_latency", ms))
        self.populate()
        self.on_theme_changed(ctx.theme)

    # -------------------------------------------------------------- catálogo
    def populate(self, *_):
        needle = self.search.text().strip().lower()
        selected = self._selected()
        self.tree.clear()
        cats: dict[str, QTreeWidgetItem] = {}
        bold = QFont()
        bold.setBold(True)
        for cmd in self.ctx.catalog:
            if needle and needle not in f"{cmd.name} {cmd.category} {cmd.description}".lower():
                continue
            parent = cats.get(cmd.category)
            if parent is None:
                parent = QTreeWidgetItem([cmd.category])
                parent.setFont(0, bold)
                parent.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(parent)
                cats[cmd.category] = parent
            item = QTreeWidgetItem([cmd.name])
            item.setData(0, Qt.UserRole, cmd.name)
            item.setFont(0, _mono(9.5))
            item.setToolTip(0, cmd.description)
            parent.addChild(item)
            if selected and cmd.name == selected.name:
                self.tree.setCurrentItem(item)
        self.tree.expandAll()
        self._show_details()

    def _selected(self):
        item = self.tree.currentItem() if hasattr(self, "tree") else None
        name = item.data(0, Qt.UserRole) if item else None
        return self.ctx.catalog.get(name) if name else None

    def _show_details(self) -> None:
        cmd = self._selected()
        self.details.setVisible(cmd is not None)
        self.empty.setVisible(cmd is None)
        if cmd is None:
            return
        self.d_usage.setText(cmd.usage)
        self.d_meta.setText(f"{cmd.category}  ·  se envía a la {'C6 puente' if cmd.target == 'puente' else 'mano'}")
        self.d_desc.setText(cmd.description)
        args = []
        for a in cmd.args:
            if a.choices:
                args.append(f"• {a.name}: {' | '.join(a.choices)}")
            elif a.type in ("int", "float"):
                rng = f" de {a.min:g} a {a.max:g}" if a.min is not None and a.max is not None else ""
                args.append(f"• {a.name}: {'entero' if a.type == 'int' else 'número'}{rng}")
            else:
                args.append(f"• {a.name}: texto")
        self.d_args.setText("\n".join(args))
        self.d_args.setVisible(bool(args))
        self.send_btn.setEnabled(not cmd.args and self.ctx.connected)
        self.send_btn.setToolTip("Enviar ahora" if not cmd.args else "Este comando necesita argumentos: insértalo en la consola")
        QTimer.singleShot(0, self._fit_details)

    def _fit_details(self) -> None:
        """Reserva para la ficha la altura que piden sus textos de varias líneas con el ancho actual."""
        lay = self.details.layout()
        width = self.details.width() or self.width()
        if lay.hasHeightForWidth() and width > 0:
            self.details.setMinimumHeight(lay.totalHeightForWidth(width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.details.isVisible():
            QTimer.singleShot(0, self._fit_details)

    def insert_selected(self) -> None:
        cmd = self._selected()
        if cmd:
            self.ctx.prefill_command.emit(cmd.name + (" " if cmd.args else ""))

    def _insert_first_match(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            if cat.childCount():
                self.tree.setCurrentItem(cat.child(0))
                self.insert_selected()
                return

    def send_selected(self) -> None:
        cmd = self._selected()
        if cmd:
            self.ctx.send_command(cmd.name)

    def focus_search(self) -> None:
        self.tab_group.button(0).setChecked(True)
        self.stack.setCurrentIndex(0)
        self.search.setFocus()
        self.search.selectAll()

    # ------------------------------------------------------------- historial
    def on_message(self, msg) -> None:
        p = PALETTES[self.ctx.theme]
        if msg.kind is MessageKind.TX:
            item = QListWidgetItem(f"{msg.timestamp:%H:%M:%S}   {msg.text}\n      esperando respuesta…")
            item.setData(Qt.UserRole, msg.text.lstrip("@"))
            item.setForeground(QColor(p["muted"]))
            self.history.addItem(item)
            self.history.scrollToBottom()
            self._pending = item
        elif msg.kind in (MessageKind.ACK, MessageKind.ERROR) and self._pending is not None:
            ok = msg.kind is MessageKind.ACK
            sent = self._pending.data(Qt.UserRole)
            ms = f"   ·  {self._last_latency:.0f} ms" if self._last_latency is not None else ""
            self._pending.setText(f"{msg.timestamp:%H:%M:%S}   {sent}{ms}\n      {'✓' if ok else '✕'}  {msg.text}")
            self._pending.setForeground(QColor(p["ok"] if ok else p["error"]))
            if self._last_latency is not None:
                level = latency_level(self._last_latency)
                self._pending.setToolTip(f"Respuesta en {self._last_latency:.1f} ms"
                                         + ("" if level == "ok" else " — por encima de 100 ms"))
            self._pending = None
            self._last_latency = None

    def on_catalog_reloaded(self) -> None:
        self.populate()

    def on_connection_changed(self, connected, info):
        self._show_details()

    def on_theme_changed(self, theme: str) -> None:
        self._search_action.setIcon(icon("search", PALETTES[theme]["subtle"], 16))


CommandsPage = CommandsPanel  # nombre anterior
