"""Reproductor de sesiones grabadas (barra superior en modo reproducción).

    [▶]  00:12.4 / 01:45.0  ─────●──|───|──────|─────  [1× ▾]  sesion_….jsonl · 1 234 mensajes  [✕]
                                    marcas: comandos enviados (azul) y errores (rojo)

Los mensajes de la sesión llegan a todas las páginas con ctx.inject(), como si
vinieran de la mano: el gemelo digital, las gráficas y la consola se mueven
igual que durante la prueba. Mientras se reproduce no se pueden enviar
comandos (la conexión con la mano está cerrada).
"""

import bisect
import time
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QToolTip, QWidget

from ..core.protocol import MessageKind
from ..core.session import Session
from .icons import icon
from .theme import PALETTES

SPEEDS = (0.5, 1.0, 2.0, 4.0)
MAX_EVENTS_PER_TICK = 4000  # para que un salto adelante no congele la interfaz


def fmt_time(t: float) -> str:
    m, s = divmod(max(t, 0.0), 60)
    return f"{int(m):02d}:{s:04.1f}"


class SessionPlayer(QObject):
    position_changed = Signal(float)
    state_changed = Signal(str)   # "playing" | "paused" | "closed"

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.session: Session | None = None
        self.speed = 1.0
        self.position = 0.0
        self._times: list[float] = []
        self._idx = 0
        self._anchor = (0.0, 0.0)  # (reloj de pared, posición) al empezar a reproducir
        self._start: datetime | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._tick)

    @property
    def playing(self) -> bool:
        return self._timer.isActive()

    @property
    def duration(self) -> float:
        return self.session.duration if self.session else 0.0

    def load(self, session: Session) -> None:
        self.close()
        self.session = session
        self._times = [e.t for e in session.events]
        self._idx = 0
        self.position = 0.0
        try:
            self._start = datetime.fromisoformat(session.meta.get("inicio", ""))
        except ValueError:
            self._start = None
        self.ctx.set_replaying(True)
        self.ctx.time_scale = self.speed
        self.position_changed.emit(0.0)
        self.state_changed.emit("paused")

    def play(self) -> None:
        if self.session is None:
            return
        if self.position >= self.duration:
            self.seek(0.0)
        self._anchor = (time.monotonic(), self.position)
        self._timer.start()
        self.state_changed.emit("playing")

    def pause(self) -> None:
        if self.session is None:
            return
        self._timer.stop()
        self.state_changed.emit("paused")

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def set_speed(self, speed: float) -> None:
        self.speed = speed
        self.ctx.time_scale = speed
        self._anchor = (time.monotonic(), self.position)

    def seek(self, t: float) -> None:
        """Salta sin reproducir lo intermedio (las gráficas siguen desde el punto nuevo)."""
        if self.session is None:
            return
        self.position = min(max(t, 0.0), self.duration)
        self._idx = bisect.bisect_right(self._times, self.position)
        self._anchor = (time.monotonic(), self.position)
        self.position_changed.emit(self.position)

    def close(self) -> None:
        if self.session is None:
            return
        self._timer.stop()
        self.session = None
        self._times = []
        self.ctx.time_scale = 1.0
        self.ctx.set_replaying(False)
        self.state_changed.emit("closed")

    def _tick(self) -> None:
        wall, pos = self._anchor
        target = min(pos + (time.monotonic() - wall) * self.speed, self.duration)
        events = self.session.events
        sent = 0
        while self._idx < len(events) and events[self._idx].t <= target and sent < MAX_EVENTS_PER_TICK:
            ev = events[self._idx]
            msg = ev.message()
            if self._start is not None:
                msg.timestamp = self._start + timedelta(seconds=ev.t)  # la consola muestra la hora de la grabación
            self.ctx.inject(msg)
            self._idx += 1
            sent += 1
        self.position = target
        self.position_changed.emit(target)
        if self._idx >= len(events) and target >= self.duration:
            self._timer.stop()
            self.state_changed.emit("paused")


class Timeline(QWidget):
    """Barra de tiempo con marcas de los comandos (TX) y errores; clic o arrastre para saltar."""
    seek_requested = Signal(float)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.duration = 1.0
        self.position = 0.0
        self.marks: list[tuple[float, str, str]] = []  # (t, clave de color, texto)
        self.setMinimumHeight(26)
        self.setMinimumWidth(160)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("")

    def set_session(self, session: Session | None) -> None:
        self.marks = []
        if session is not None:
            self.duration = max(session.duration, 0.001)
            for e in session.events:
                if e.kind is MessageKind.TX:
                    self.marks.append((e.t, "tx", e.text))
                elif e.kind is MessageKind.ERROR:
                    self.marks.append((e.t, "error", e.text))
        self.position = 0.0
        self.update()

    def set_position(self, t: float) -> None:
        self.position = t
        self.update()

    def _x(self, t: float) -> float:
        return 8 + (self.width() - 16) * min(max(t / self.duration, 0.0), 1.0)

    def _t(self, x: float) -> float:
        return min(max((x - 8) / max(self.width() - 16, 1), 0.0), 1.0) * self.duration

    def paintEvent(self, _event) -> None:
        p = PALETTES[self.ctx.theme]
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        mid = self.height() / 2
        x0, x1 = self._x(0), self._x(self.duration)
        xp = self._x(self.position)
        qp.setPen(Qt.NoPen)
        qp.setBrush(QColor(p["border"]))
        qp.drawRoundedRect(QRectF(x0, mid - 2, x1 - x0, 4), 2, 2)
        qp.setBrush(QColor(p["accent"]))
        qp.drawRoundedRect(QRectF(x0, mid - 2, xp - x0, 4), 2, 2)
        for t, key, _text in self.marks:  # marcas encima de la pista
            qp.setPen(QPen(QColor(p[key]), 1.5))
            x = self._x(t)
            qp.drawLine(QPointF(x, mid - 9), QPointF(x, mid - 4))
        qp.setPen(QPen(QColor(p["accent"]), 2))
        qp.setBrush(QColor("#ffffff"))
        qp.drawEllipse(QPointF(xp, mid), 6, 6)
        qp.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.seek_requested.emit(self._t(event.position().x()))

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if event.buttons() & Qt.LeftButton:
            self.seek_requested.emit(self._t(x))
            return
        t = self._t(x)
        near = [m for m in self.marks if abs(self._x(m[0]) - x) <= 4]
        text = fmt_time(t) + ("\n" + "\n".join(f"{'TX' if k == 'tx' else 'ERR'}  {s}" for _t, k, s in near[:4])
                              if near else "")
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def keyPressEvent(self, event) -> None:
        step = 5.0 if event.modifiers() & Qt.ShiftModifier else 1.0
        if event.key() == Qt.Key_Left:
            self.seek_requested.emit(self.position - step)
        elif event.key() == Qt.Key_Right:
            self.seek_requested.emit(self.position + step)
        else:
            super().keyPressEvent(event)


class PlayerBar(QWidget):
    """Barra de reproducción: se muestra en lugar del aviso de simulación mientras hay una sesión abierta."""

    def __init__(self, ctx, player: SessionPlayer):
        super().__init__()
        self.ctx = ctx
        self.player = player
        self.setObjectName("playerBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)
        self.badge = QLabel("REPRODUCCIÓN")
        self.badge.setObjectName("playerBadge")
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("ghost")
        self.play_btn.setIconSize(QSize(16, 16))
        self.play_btn.setToolTip("Reproducir / pausar (Espacio)")
        self.play_btn.clicked.connect(player.toggle)
        self.time_lbl = QLabel()
        self.time_lbl.setObjectName("value")
        self.timeline = Timeline(ctx)
        self.timeline.seek_requested.connect(player.seek)
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setCurrentIndex(SPEEDS.index(1.0))
        self.speed.setToolTip("Velocidad de reproducción")
        self.speed.currentIndexChanged.connect(lambda i: player.set_speed(SPEEDS[i]))
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("ghost")
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.setToolTip("Cerrar la sesión y volver al modo normal")
        self.close_btn.clicked.connect(player.close)
        for w in (self.badge, self.play_btn, self.time_lbl):
            row.addWidget(w)
        row.addWidget(self.timeline, 1)
        row.addWidget(self.speed)
        row.addWidget(self.info)
        row.addWidget(self.close_btn)
        player.position_changed.connect(self._on_position)
        player.state_changed.connect(self._on_state)
        ctx.theme_changed.connect(lambda _t: self._paint())
        self._paint()

    def show_session(self, session: Session) -> None:
        self.timeline.set_session(session)
        n = len(session.events)
        tx = session.count(MessageKind.TX)
        self.info.setText(f"{session.path.name}  ·  {n:,} mensajes · {tx} comandos".replace(",", " "))
        self.info.setToolTip(f"{session.path}\nInicio: {session.meta.get('inicio', '?')}\n"
                             f"Modo: {'simulación' if session.meta.get('simulacion') else 'mano real'}"
                             f"{' · ' + session.meta['puerto'] if session.meta.get('puerto') else ''}")
        self._on_position(0.0)
        self._on_state("paused")

    def _on_position(self, t: float) -> None:
        self.timeline.set_position(t)
        self.time_lbl.setText(f"{fmt_time(t)} / {fmt_time(self.player.duration)}")

    def _on_state(self, state: str) -> None:
        self._paint()
        self.setVisible(state != "closed")

    def _paint(self) -> None:
        p = PALETTES[self.ctx.theme]
        self.play_btn.setIcon(icon("pause" if self.player.playing else "play", p["text"], 16))
        self.close_btn.setIcon(icon("close", p["muted"], 16))
        self.timeline.update()
