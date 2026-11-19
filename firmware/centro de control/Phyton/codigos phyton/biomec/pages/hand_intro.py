"""Presentación animada de la mano en el gemelo digital: el DIBUJO (OpenGL + Qt).

El guion (qué pasa en cada instante) está en core/hand_intro.py. Aquí se pinta:
  - con el sombreador "biomec_intro": igual que el normal del gemelo, pero solo pinta lo que
    queda por debajo del barrido (Y < u_cut) y da un brillo azul al borde;
  - las líneas "de plano" de cada pieza (sus aristas), que crecen de abajo arriba;
  - una capa encima de la vista 3D con el rótulo de la fase, las etiquetas de las piezas, el
    título y el botón Saltar.
Se salta con un clic en la vista o con el botón (Esc sigue siendo Parar los motores). Al
terminar, el gemelo vuelve a seguir a la mano como siempre.
"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QMatrix4x4, QPainter, QPen, QVector4D
from PySide6.QtWidgets import QPushButton, QWidget

from ..core.hand_intro import CALLOUTS, DURATION, IntroFrame, IntroScript, feature_edges
from ..core.hand_model import DEDOS, frustum
from ..ui.theme import PALETTES

SHADER = "biomec_intro"
PHALANGES = ("Proximal", "Medio", "Distal")

# Mismo sombreado que "biomec_lit" (hand3d.py) + el barrido: v_s es la Y del STL (de la muñeca a
# las puntas). Lo que queda por encima de u_cut no se pinta; justo debajo, brilla.
ShaderProgram(SHADER, [
    VertexShader("""
        uniform mat4 u_mvp;
        uniform mat3 u_normal;
        attribute vec4 a_position;
        attribute vec3 a_normal;
        attribute vec4 a_color;
        varying vec4 v_color;
        varying vec3 v_normal;
        varying float v_s;
        void main() {
            v_normal = normalize(u_normal * a_normal);
            v_color = a_color;
            v_s = a_position.y;
            gl_Position = u_mvp * a_position;
        }
    """),
    FragmentShader("""
        #ifdef GL_ES
        precision mediump float;
        #endif
        uniform float u_cut;
        uniform float u_band;
        uniform float u_glow;
        uniform float u_glow_color[3];
        varying vec4 v_color;
        varying vec3 v_normal;
        varying float v_s;
        void main() {
            if (v_s > u_cut) discard;
            float p = abs(dot(normalize(v_normal), normalize(vec3(0.35, 0.45, 1.0))));
            vec3 rgb = v_color.rgb * (0.38 + 0.72 * p);
            float g = u_glow * (1.0 - smoothstep(0.0, u_band, u_cut - v_s));
            vec3 glow = vec3(u_glow_color[0], u_glow_color[1], u_glow_color[2]);
            gl_FragColor = vec4(min(mix(rgb, glow, g), vec3(1.0)), v_color.a);
        }
    """),
], uniforms={"u_cut": [0.0], "u_band": [14.0], "u_glow": [0.0], "u_glow_color": [0.23, 0.51, 0.96]})


def _rgb(hex_color: str) -> np.ndarray:
    h = hex_color.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def _glow_hex(theme: str) -> str:
    p = PALETTES[theme]
    return p["accent_text"] if theme == "dark" else p["accent"]


class HandIntro(QObject):
    """Reproduce la presentación sobre la vista 3D de una Hand3DPage."""

    finished = Signal()

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.script = IntroScript(page.model)
        self.anchors = [self.script.anchor(c) for c in CALLOUTS]
        self.running = False
        self.t = 0.0
        self._t0 = 0.0
        self._lines: dict[str, tuple] = {}     # pieza -> (GLLinePlotItem, puntos (2M, 3))
        self._shown: dict[str, tuple] = {}
        self.overlay = IntroOverlay(page.view, self)
        self.overlay.hide()
        page.view.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._step)

    # ---------------------------------------------------------------- control
    def start(self, at_startup: bool = False) -> None:
        self.overlay.startup_hint = at_startup   # al abrir la app: cómo quitarla
        if not self.running:
            self._ensure_lines()
            self.running = True
            for item in self.page.items.values():
                item.setShader(SHADER)
            self.overlay.setGeometry(self.page.view.rect())
            self.overlay.show()
            self.overlay.raise_()
        self._t0 = time.monotonic()
        self._apply(0.0)
        self.timer.start()

    def seek(self, t: float) -> None:
        """Salta a un instante y se queda quieta ahí (para capturas y pruebas)."""
        if not self.running:
            self.start()
        self.timer.stop()
        self._t0 = time.monotonic() - t
        self._apply(t)

    def stop(self) -> None:
        if not self.running:
            return
        self.timer.stop()
        self.running = False
        page = self.page
        for name, item in page.items.items():
            item.setShader("biomec_lit")
            item.setTransform(pg.Transform3D())   # las piezas fijas; los dedos los recoloca el gemelo
        for item, _ in self._lines.values():
            item.setVisible(False)
        self._shown.clear()
        self.overlay.hide()
        page._applied = None
        page._colors_applied = None
        page.set_camera("¾")
        self.finished.emit()

    def _step(self) -> None:
        if not self.page.view.isVisible():   # se ha cerrado o tapado la ventana del gemelo
            self.stop()
            return
        t = time.monotonic() - self._t0
        self._apply(min(t, DURATION))
        if t >= DURATION:
            self.stop()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt)
        if obj is self.page.view and event.type() == QEvent.Resize:
            self.overlay.setGeometry(self.page.view.rect())
        return False

    # ---------------------------------------------------------------- dibujo
    def _ensure_lines(self) -> None:
        if self._lines:
            return
        for name, part in self.page.model.parts.items():
            seg = feature_edges(part.triangles)
            if len(seg) < 0.15 * len(part.triangles):   # pieza redondeada (el pulgar): pocos pliegues
                seg = feature_edges(part.triangles, angle_deg=12.0)
            item = gl.GLLinePlotItem(pos=np.zeros((2, 3), np.float32), mode="lines", width=1.3,
                                     antialias=True, color=(0, 0, 0, 0), glOptions="translucent")
            item.setParentItem(self.page.items[name])
            item.setVisible(False)
            self._lines[name] = (item, seg.reshape(-1, 3))

    def _apply(self, t: float) -> None:
        f = self.script.frame(t)
        self.t = t
        page, model = self.page, self.page.model
        theme = page.ctx.theme
        glow = _rgb(_glow_hex(theme))

        poses = model.pose(f.flex, f.thumb)
        for name, item in page.items.items():
            m = f.offsets[name] @ poses.get(name, np.eye(4))
            item.setTransform(pg.Transform3D(*m.astype(np.float32).ravel()))
        for d in DEDOS:   # los dedos que se mueven, en azul (como en el gemelo)
            level = 0.75 * f.moving[d]
            for role in PHALANGES:
                base = _rgb(model.parts[f"{d}/{role}"].color)
                page.items[f"{d}/{role}"].setColor(tuple((1 - level) * base + level * glow) + (1.0,))

        prog = ShaderProgram.names[SHADER]
        prog["u_cut"] = [f.cut]
        prog["u_glow"] = [f.glow]
        prog["u_glow_color"] = [float(c) for c in glow]

        for name, (item, pts) in self._lines.items():
            k = int(round(f.wire[name] * (len(pts) // 2))) if f.visible[name] else 0
            if k == 0 or f.wire_alpha <= 0:
                item.setVisible(False)
                continue
            key = (k, round(f.wire_alpha, 2), theme)
            if self._shown.get(name) != key:
                item.setData(pos=pts[:2 * k], color=tuple(glow) + (0.85 * f.wire_alpha,))
                self._shown[name] = key
            item.setVisible(True)

        az, el, dist = f.camera
        page.view.opts["center"] = pg.Vector(0, 0, 0)
        page.view.setCameraPosition(distance=model.size * dist, elevation=el, azimuth=az)
        self.overlay.frame = f
        self.overlay.update()

    def project(self, part: str, point: np.ndarray) -> QPointF | None:
        """Píxel de la vista donde cae un punto de una pieza (o None si queda detrás de la cámara)."""
        view = self.page.view
        w, h = max(view.width(), 1), max(view.height(), 1)
        left, right, bottom, top, near, far = frustum(view.opts["fov"], view.opts["distance"], w, h)
        proj = QMatrix4x4()
        proj.frustum(left, right, bottom, top, near, far)
        m = proj * view.viewMatrix() * self.page.root_item.transform() * self.page.items[part].transform()
        v = m.map(QVector4D(float(point[0]), float(point[1]), float(point[2]), 1.0))
        if v.w() <= 1e-6:
            return None
        return QPointF((v.x() / v.w() + 1) * 0.5 * w, (1 - v.y() / v.w()) * 0.5 * h)


class IntroOverlay(QWidget):
    """Capa encima de la vista 3D: rótulo de la fase, etiquetas, título, progreso y Saltar."""

    def __init__(self, view, intro: HandIntro):
        super().__init__(view)
        self.intro = intro
        self.frame: IntroFrame | None = None
        self.startup_hint = False
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Clic para saltar la presentación")
        self.skip_btn = QPushButton("Saltar", self)
        self.skip_btn.setObjectName("ghost")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.clicked.connect(intro.stop)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt)
        self.intro.stop()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt)
        self.skip_btn.adjustSize()
        self.skip_btn.move(self.width() - self.skip_btn.width() - 10, 8)   # arriba, a la altura del rótulo

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt)
        f = self.frame
        if f is None:
            return
        pal = PALETTES[self.intro.page.ctx.theme]
        accent = QColor(_glow_hex(self.intro.page.ctx.theme))
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # rótulo de la fase, como en un plano
        mono = QFont("Consolas")
        mono.setPointSizeF(9.0)
        mono.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(mono)
        p.setPen(QPen(accent, 1.4))
        p.drawLine(QPointF(14, 22), QPointF(34, 22))
        p.drawText(QPointF(42, 26), f.phase.upper())

        for index, grow, alpha in f.callouts:
            part, point = self.intro.anchors[index]
            anchor = self.intro.project(part, point)
            if anchor is not None:
                self._callout(p, anchor, CALLOUTS[index], grow, alpha, accent, pal)

        if f.title_alpha > 0:
            self._title(p, w, h, f.title_alpha, pal)

        if self.startup_hint:
            small = QFont(self.font())
            small.setPointSizeF(8.5)
            p.setFont(small)
            p.setPen(QColor(pal["subtle"]))
            hint = "Clic para saltar  ·  Clic derecho en «Mostrar» para que no salga al abrir"
            p.drawText(QPointF(14, h - 14), QFontMetricsF(small).elidedText(hint, Qt.ElideRight, w - 28))

        # progreso de la presentación
        p.setPen(Qt.NoPen)
        track = QColor(pal["border"])
        p.setBrush(track)
        p.drawRect(QRectF(0, h - 3, w, 3))
        p.setBrush(accent)
        p.drawRect(QRectF(0, h - 3, w * f.t / DURATION, 3))
        p.end()

    @staticmethod
    def _with_alpha(color: QColor, alpha: float) -> QColor:
        c = QColor(color)
        c.setAlphaF(max(0.0, min(1.0, color.alphaF() * alpha)))
        return c

    def _callout(self, p: QPainter, anchor: QPointF, c, grow: float, alpha: float, accent: QColor, pal) -> None:
        elbow = anchor + QPointF(c.side * 34, c.dy)
        end = elbow + QPointF(c.side * 56, 0)
        l1 = (elbow - anchor).manhattanLength()
        l2 = (end - elbow).manhattanLength()
        along = grow * (l1 + l2)
        p.setPen(QPen(self._with_alpha(accent, alpha), 1.4))
        if along <= l1:
            p.drawLine(anchor, anchor + (elbow - anchor) * (along / max(l1, 1)))
        else:
            p.drawLine(anchor, elbow)
            p.drawLine(elbow, elbow + (end - elbow) * ((along - l1) / max(l2, 1)))
        p.setPen(Qt.NoPen)
        p.setBrush(self._with_alpha(accent, 0.25 * alpha))
        p.drawEllipse(anchor, 8, 8)
        p.setBrush(self._with_alpha(accent, alpha))
        p.drawEllipse(anchor, 3.5, 3.5)

        text_alpha = alpha * max(0.0, (grow - 0.55) / 0.45)
        if text_alpha <= 0:
            return
        title_font = QFont(self.font())
        title_font.setPointSizeF(10.0)
        title_font.setBold(True)
        sub_font = QFont(self.font())
        sub_font.setPointSizeF(8.8)
        ft, fs = QFontMetricsF(title_font), QFontMetricsF(sub_font)
        bw = max(ft.horizontalAdvance(c.title), fs.horizontalAdvance(c.subtitle)) + 22
        bh = ft.height() + fs.height() + 16
        x = end.x() + 6 if c.side > 0 else end.x() - 6 - bw
        x = min(max(x, 8.0), self.width() - bw - 8)
        y = min(max(end.y() - bh / 2, 36.0), self.height() - bh - 54)
        box = QRectF(x, y, bw, bh)
        p.setPen(QPen(self._with_alpha(QColor(pal["border_strong"]), text_alpha), 1))
        p.setBrush(self._with_alpha(QColor(pal["card"]), 0.94 * text_alpha))
        p.drawRoundedRect(box, 8, 8)
        p.setFont(title_font)
        p.setPen(self._with_alpha(QColor(pal["text"]), text_alpha))
        p.drawText(QPointF(x + 11, y + 8 + ft.ascent()), c.title)
        p.setFont(sub_font)
        p.setPen(self._with_alpha(QColor(pal["muted"]), text_alpha))
        p.drawText(QPointF(x + 11, y + 8 + ft.height() + fs.ascent()), c.subtitle)

    def _title(self, p: QPainter, w: int, h: int, alpha: float, pal) -> None:
        big = QFont(self.font())
        big.setPointSizeF(max(18.0, min(30.0, h / 18)))
        big.setBold(True)
        big.setLetterSpacing(QFont.AbsoluteSpacing, 8)
        sub = QFont(self.font())
        sub.setPointSizeF(10.5)
        fb, fs = QFontMetricsF(big), QFontMetricsF(sub)
        rise = (1 - alpha) * 10
        y = h * 0.80 + rise
        text, subtitle = "BIOMEC", "Prótesis de mano mioeléctrica  ·  Universidad de Málaga"
        p.setFont(big)
        p.setPen(self._with_alpha(QColor(pal["text"]), alpha))
        p.drawText(QPointF((w - fb.horizontalAdvance(text)) / 2, y), text)
        p.setFont(sub)
        p.setPen(self._with_alpha(QColor(pal["muted"]), alpha))
        p.drawText(QPointF((w - fs.horizontalAdvance(subtitle)) / 2, y + fs.height() + 6), subtitle)
