"""Componentes de interfaz reutilizables (el "sistema de diseño" de la app).

  Segmented     control segmentado: opciones excluyentes dentro de una cápsula (vistas, pestañas, modos)
  Stepper       pasos numerados con su estado: hecho ✓ / actual / pendiente (Entrenamiento)
  ToastHost     avisos flotantes arriba a la derecha (errores y confirmaciones importantes)
  ElidedLabel   texto de una línea que termina en "…" si no cabe
  style_titlebar  barra de título de Windows a juego con el tema (oscura en modo oscuro)
"""

import ctypes
import sys

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QWidget,
)

from .icons import icon, pixmap
from .theme import PALETTES


# ================================================================ segmentado
class Segmented(QWidget):
    """Opciones en una cápsula; la elegida se ve "levantada". exclusive=False: el estado lo pone el código."""

    def __init__(self, labels, exclusive: bool = True, stretch: bool = True, tooltips=None):
        super().__init__()
        self.setObjectName("segmented")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(exclusive)
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if tooltips and i < len(tooltips) and tooltips[i]:
                b.setToolTip(tooltips[i])
            self.group.addButton(b, i)
            lay.addWidget(b, 1 if stretch else 0)
        self.setSizePolicy(QSizePolicy.Preferred if stretch else QSizePolicy.Maximum, QSizePolicy.Fixed)

    @property
    def idClicked(self):
        return self.group.idClicked

    def button(self, i: int) -> QPushButton:
        return self.group.button(i)

    def set_current(self, i: int) -> None:
        b = self.group.button(i)
        if b is not None:
            b.setChecked(True)

    def current(self) -> int:
        return self.group.checkedId()


# ================================================================== pasos
class Stepper(QWidget):
    """① Grabar ── ② Entrenar ── ③ Probar: el actual en azul, los completados con ✓."""
    step_clicked = Signal(int)

    CIRCLE = 22

    def __init__(self, ctx, steps: list[str]):
        super().__init__()
        self.ctx = ctx
        self.steps = steps
        self.current = 0
        self.done: set[int] = set()
        self._hover = -1
        self._rects: list[QRectF] = []
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_current(self, i: int) -> None:
        self.current = i
        self.update()

    def set_done(self, i: int, done: bool) -> None:
        (self.done.add if done else self.done.discard)(i)
        self.update()

    def _layout(self, qp: QPainter) -> list[tuple[QRectF, QRectF, float]]:
        fm = qp.fontMetrics()
        x, out = 2.0, []
        mid = self.height() / 2
        for text in self.steps:
            circle = QRectF(x, mid - self.CIRCLE / 2, self.CIRCLE, self.CIRCLE)
            w = fm.horizontalAdvance(text) + 4
            label = QRectF(x + self.CIRCLE + 8, 0, w, self.height())
            out.append((circle, label, label.right()))
            x = label.right() + 64
        return out

    def paintEvent(self, _event) -> None:
        p = PALETTES[self.ctx.theme]
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        font = qp.font()
        font.setBold(True)
        qp.setFont(font)
        items = self._layout(qp)
        self._rects = [QRectF(c.left() - 4, 0, l.right() - c.left() + 8, self.height()) for c, l, _r in items]
        mid = self.height() / 2
        for i, (circle, label, right) in enumerate(items):
            if i + 1 < len(items):  # conector hasta el siguiente paso
                nxt = items[i + 1][0]
                qp.setPen(QPen(QColor(p["ok"] if i in self.done else p["border_strong"]), 1.5))
                qp.drawLine(QPointF(right + 14, mid), QPointF(nxt.left() - 14, mid))
            current, done = i == self.current, i in self.done
            if current:
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(p["accent"]))
            elif done:
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(p["ok"]))
            else:
                qp.setPen(QPen(QColor(p["border_strong"]), 1.5))
                qp.setBrush(Qt.NoBrush)
            qp.drawEllipse(circle)
            if done and not current:  # marca de hecho
                qp.setPen(QPen(QColor("#ffffff"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                c = circle.center()
                path = QPainterPath(QPointF(c.x() - 4.5, c.y() + 0.2))
                path.lineTo(QPointF(c.x() - 1.2, c.y() + 3.4))
                path.lineTo(QPointF(c.x() + 4.8, c.y() - 3.2))
                qp.setBrush(Qt.NoBrush)
                qp.drawPath(path)
            else:
                qp.setPen(QColor("#ffffff") if current else QColor(p["muted"]))
                qp.drawText(circle, Qt.AlignCenter, str(i + 1))
            color = p["text"] if current else p["accent_text"] if i == self._hover else p["muted"]
            qp.setPen(QColor(color))
            qp.drawText(label, Qt.AlignVCenter | Qt.AlignLeft, self.steps[i])
        qp.end()

    def _hit(self, pos) -> int:
        for i, r in enumerate(self._rects):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, event) -> None:
        hover = self._hit(event.position())
        if hover != self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, _event) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, event) -> None:
        i = self._hit(event.position())
        if i >= 0 and event.button() == Qt.LeftButton:
            self.step_clicked.emit(i)


# ================================================================= avisos
class Toast(QWidget):
    """Un aviso: icono + texto + ✕, con sombra. Se va solo (o al pulsar ✕).

    Sin efecto de fundido: Qt no pinta bien dos efectos gráficos anidados (fundido + sombra)
    cuando el aviso se recoloca al apilar otro."""
    finished = Signal(object)

    ICONS = {"error": ("octagon", "error"), "ok": ("check", "ok"), "info": ("info", "accent_text"),
             "voice": ("mic", "accent_text")}

    def __init__(self, parent: QWidget, theme: str, text: str, kind: str, ms: int):
        super().__init__(parent)
        self.text, self.kind = text, kind
        p = PALETTES[theme]
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 18)  # hueco para la sombra
        frame = QFrame()
        frame.setObjectName("toast")
        frame.setProperty("kind", kind)
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 120 if theme == "dark" else 45))
        frame.setGraphicsEffect(shadow)
        outer.addWidget(frame)
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 10, 6, 10)
        row.setSpacing(10)
        name, color = self.ICONS.get(kind, self.ICONS["info"])
        ic = QLabel()
        ic.setPixmap(pixmap(name, p[color], 16))
        ic.setFixedSize(18, 18)
        row.addWidget(ic, 0, Qt.AlignTop)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(250)
        self.label.setMaximumWidth(360)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.label, 1)
        close = QPushButton()
        close.setObjectName("ghost")
        close.setIcon(icon("close", p["muted"], 14))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(24, 24)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignTop)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._ms = ms
        self._closing = False

    def popup(self) -> None:
        self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(self._ms)

    def bump(self) -> None:
        """El mismo aviso otra vez: se queda más tiempo en vez de duplicarse."""
        self._timer.start(self._ms)

    def enterEvent(self, _event) -> None:  # con el ratón encima no se cierra
        self._timer.stop()

    def leaveEvent(self, _event) -> None:
        if not self._closing:
            self._timer.start(2500)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self.hide()
        QTimer.singleShot(0, lambda: self.finished.emit(self))


class ToastHost:
    """Coloca los avisos apilados en la esquina superior derecha de 'anchor'."""

    MAX = 3

    def __init__(self, parent: QWidget, anchor: QWidget, theme_getter, top: int = 64):
        self.parent, self.anchor, self.theme, self.top = parent, anchor, theme_getter, top
        self.toasts: list[Toast] = []

    def show(self, text: str, kind: str = "info") -> None:
        text = text.strip()
        if not text:
            return
        for t in self.toasts:
            if t.text == text and not t._closing:
                t.bump()
                return
        while len(self.toasts) >= self.MAX:
            self.toasts[0].dismiss()
            self._remove(self.toasts[0])
        ms = 7000 if kind == "error" else 4200
        toast = Toast(self.parent, self.theme(), text, kind, ms)
        toast.finished.connect(self._remove)
        self.toasts.append(toast)
        toast.popup()
        self.relayout()

    def _remove(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        toast.hide()
        toast.deleteLater()
        self.relayout()

    def relayout(self) -> None:
        origin = self.anchor.mapTo(self.parent, self.anchor.rect().topRight())
        y = origin.y() + self.top
        for toast in reversed(self.toasts):  # el más reciente arriba
            toast.adjustSize()
            toast.move(origin.x() - toast.width() - 8, y)
            toast.raise_()
            y += toast.height() - 10


# ============================================================ texto recortado
class ElidedLabel(QLabel):
    """Etiqueta de una línea que, si no cabe, termina en "…" en vez de ensanchar la ventana."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(40)
        return hint

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(min(hint.width(), 200))
        return hint

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, text)


# ======================================================= barra de título (Windows)
def _colorref(hex_color: str) -> int:
    c = QColor(hex_color)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def style_titlebar(widget: QWidget, theme: str) -> None:
    """Barra de título oscura en modo oscuro (Windows 10/11) y del color de la barra lateral (Windows 11)."""
    if sys.platform != "win32":
        return
    p = PALETTES[theme]
    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        dwm = ctypes.windll.dwmapi
        for attr, value in ((20, 1 if theme == "dark" else 0),     # DWMWA_USE_IMMERSIVE_DARK_MODE
                            (35, _colorref(p["sidebar"])),         # DWMWA_CAPTION_COLOR (Windows 11)
                            (34, _colorref(p["border"])),          # DWMWA_BORDER_COLOR
                            (36, _colorref(p["text"]))):           # DWMWA_TEXT_COLOR
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, ctypes.c_uint(attr), ctypes.byref(v), ctypes.c_uint(4))
    except (AttributeError, OSError, ValueError):
        pass
