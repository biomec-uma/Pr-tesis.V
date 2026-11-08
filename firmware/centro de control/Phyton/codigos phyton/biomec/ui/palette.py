"""Paleta de comandos (Ctrl+K), al estilo de VS Code o Linear.

Una ventana flotante con un buscador: escribe y pulsa Enter para ejecutar
cualquier acción de la app (gestos, comandos del catálogo, navegación,
conexión, tema…). Si lo escrito es un comando válido completo, por ejemplo
"dedo indice cerrar", la primera opción es enviarlo tal cual.

Las acciones las proporciona la ventana principal (MainWindow.palette_actions),
así que añadir una nueva es añadir un PaletteAction a esa lista.
"""

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QFrame, QLabel, QLineEdit, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QVBoxLayout,
)

from ..core.commands import CommandError
from .icons import icon
from .theme import PALETTES


@dataclass
class PaletteAction:
    title: str
    hint: str = ""            # texto gris a la derecha (categoría, atajo…)
    icon: str = "terminal"
    run: Callable[[], None] = lambda: None
    keywords: str = ""        # palabras extra para la búsqueda
    enabled: bool = True
    data: dict = field(default_factory=dict)


class _Delegate(QStyledItemDelegate):
    def __init__(self, palette_dialog):
        super().__init__(palette_dialog)
        self.dlg = palette_dialog

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 38)

    def paint(self, painter: QPainter, option, index) -> None:
        action: PaletteAction = index.data(Qt.UserRole)
        p = PALETTES[self.dlg.theme]
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(6, 2, -6, -2)
        if option.state & QStyle.State_Selected:
            path = QPainterPath()
            path.addRoundedRect(r, 8, 8)
            painter.fillPath(path, QColor(p["accent_soft_solid"]))
        color = p["text"] if action.enabled else p["subtle"]
        ic = icon(action.icon, p["accent_text"] if option.state & QStyle.State_Selected else p["muted"], 16)
        ic.paint(painter, QRect(r.left() + 10, r.center().y() - 8, 16, 16))
        f = QFont(option.font)
        f.setPointSizeF(10)
        painter.setFont(f)
        painter.setPen(QColor(color))
        text_rect = QRect(r.left() + 36, r.top(), r.width() - 46, r.height())
        hint_w = painter.fontMetrics().horizontalAdvance(action.hint) + 12 if action.hint else 0
        title = painter.fontMetrics().elidedText(action.title, Qt.ElideRight, text_rect.width() - hint_w)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, title)
        if action.hint:
            f.setPointSizeF(9)
            painter.setFont(f)
            painter.setPen(QColor(p["subtle"]))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignRight, action.hint)
        painter.restore()


class CommandPalette(QDialog):
    def __init__(self, window):
        super().__init__(window, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("commandPalette")
        self.window_ = window
        self.ctx = window.ctx
        self.theme = self.ctx.theme
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName("palette")
        outer.addWidget(self.frame)
        lay = QVBoxLayout(self.frame)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.input = QLineEdit()
        self.input.setObjectName("paletteInput")
        self.input.setPlaceholderText("Busca una acción o escribe un comando (p. ej. «gesto 3», «dedo indice cerrar»)…")
        self.input.textChanged.connect(self._filter)
        self.input.returnPressed.connect(self._run_current)
        self.input.installEventFilter(self)
        lay.addWidget(self.input)

        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.setItemDelegate(_Delegate(self))
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda _i: self._run_current())
        lay.addWidget(self.list)

        self.footer = QLabel("↑↓ moverse   ·   Enter ejecutar   ·   Esc cerrar")
        self.footer.setObjectName("muted")
        self.footer.setContentsMargins(8, 0, 8, 2)
        lay.addWidget(self.footer)
        self.actions: list[PaletteAction] = []

    # -------------------------------------------------------------- mostrar
    def open_palette(self, text: str = "") -> None:
        self.theme = self.ctx.theme
        self.actions = self.window_.palette_actions()
        geo = self.window_.geometry()
        self.move(geo.x() + (geo.width() - self.width()) // 2, geo.y() + 96)
        self.input.setText(text)
        self._filter(text)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def _filter(self, text: str) -> None:
        self.list.clear()
        query = text.strip()
        items: list[PaletteAction] = []

        # Comando completo y válido -> enviarlo tal cual
        if query:
            try:
                _cmd, line = self.ctx.catalog.build(query)
                if len(query.split()) > 1 or not _cmd.args:
                    items.append(PaletteAction(f"Enviar  {line}", "Enter", "send",
                                               lambda line=line: self.ctx.send_raw(line), enabled=self.ctx.connected))
            except CommandError:
                pass

        tokens = query.lower().split()
        for a in self.actions:
            hay = f"{a.title} {a.hint} {a.keywords}".lower()
            if all(t in hay for t in tokens):
                items.append(a)
        for a in items[:60]:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, a)
            if not a.enabled:
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
            self.list.addItem(it)
        for row in range(self.list.count()):
            if self.list.item(row).flags() & Qt.ItemIsEnabled:
                self.list.setCurrentRow(row)
                break
        rows = min(max(self.list.count(), 1), 9)
        list_h = rows * 38 + 14
        self.list.setFixedHeight(list_h)
        # Altura calculada a mano: el layout no siempre se ha recalculado todavía en este momento
        inner = self.frame.layout()
        m = inner.contentsMargins()
        height = (m.top() + m.bottom() + 2 * inner.spacing() + self.input.sizeHint().height()
                  + list_h + self.footer.sizeHint().height() + 2)
        self.setFixedHeight(height)

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return
        action: PaletteAction = item.data(Qt.UserRole)
        self.hide()
        action.run()

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                step = 1 if key == Qt.Key_Down else -1
                row = self.list.currentRow()
                for _ in range(self.list.count()):
                    row = (row + step) % max(self.list.count(), 1)
                    if self.list.item(row) and self.list.item(row).flags() & Qt.ItemIsEnabled:
                        self.list.setCurrentRow(row)
                        break
                return True
            if key == Qt.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)
