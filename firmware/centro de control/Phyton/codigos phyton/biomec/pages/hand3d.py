"""Pestaña 'Mano 3D': el modelo de SolidWorks moviéndose como la mano.

Dos modos:
  - Seguir a la mano: la postura se estima con la telemetría (STREAM 1):
      PWM de cada dedo -> se integra en el tiempo -> flexión 0..1
      (no hay sensor de posición; ver "tiempo_cierre_s" en config/mano3d.json).
      Las respuestas de ESTADO corrigen la estimación (abierto/cerrado).
  - Manual: deslizadores para ver cualquier postura sin hardware.
"""

import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ..core.hand_model import DEDOS, HandModel
from ..core.protocol import MessageKind
from ..paths import ASSETS_DIR, config_file
from ..ui.theme import PALETTES
from .base import BasePage

try:  # el 3D necesita PyOpenGL; si falta, la pestaña lo explica en vez de romper la app
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    from pyqtgraph.opengl.GLGraphicsItem import GLGraphicsItem
    from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader

    # Sombreado propio: luz que sale de la cámara (como una linterna) + luz ambiente.
    # El 'shaded' de pyqtgraph ilumina desde detrás y la mano se ve casi negra.
    ShaderProgram("biomec_lit", [
        VertexShader("""
            uniform mat4 u_mvp;
            uniform mat3 u_normal;
            attribute vec4 a_position;
            attribute vec3 a_normal;
            attribute vec4 a_color;
            varying vec4 v_color;
            varying vec3 v_normal;
            void main() {
                v_normal = normalize(u_normal * a_normal);
                v_color = a_color;
                gl_Position = u_mvp * a_position;
            }
        """),
        FragmentShader("""
            #ifdef GL_ES
            precision mediump float;
            #endif
            varying vec4 v_color;
            varying vec3 v_normal;
            void main() {
                float p = abs(dot(normalize(v_normal), normalize(vec3(0.35, 0.45, 1.0))));
                vec3 rgb = v_color.rgb * (0.38 + 0.72 * p);
                gl_FragColor = vec4(min(rgb, vec3(1.0)), v_color.a);
            }
        """),
    ])
    _GL_ERROR = None
except Exception as error:  # noqa: BLE001
    _GL_ERROR = error


def _rgba(hex_color: str, alpha: float = 1.0) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (alpha,)


class Hand3DPage(BasePage):
    title = "Mano 3D"
    icon = "✋"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.flex = {d: 0.0 for d in DEDOS}
        self.thumb_target = 10.0
        self.thumb_now = 10.0
        self._last_data = None
        self._last_tick = time.monotonic()
        self._applied = None
        self.model = None
        self.items = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        view_card, view_layout = self.card("Mano 3D")
        problem = self._build_view(view_layout)
        root.addWidget(view_card, 1)
        root.addWidget(self._build_side_panel())

        if problem:
            msg = QLabel(problem)
            msg.setWordWrap(True)
            msg.setAlignment(Qt.AlignCenter)
            view_layout.addWidget(msg, 1)
            return

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.on_theme_changed(ctx.theme)

    # ------------------------------------------------------------ montaje
    def _build_view(self, layout) -> str | None:
        if _GL_ERROR is not None:
            return f"No se puede mostrar el 3D: falta PyOpenGL ({_GL_ERROR}).\nInstala con: pip install PyOpenGL"
        try:
            self.model = HandModel.load(config_file("mano3d.json"), ASSETS_DIR)
        except Exception as error:  # noqa: BLE001
            return f"No se pudo cargar el modelo 3D:\n{error}"

        self.view = gl.GLViewWidget()
        self.view.setMinimumSize(300, 300)
        # Raíz: centra el modelo y pone su eje Y (a lo largo de los dedos) hacia arriba.
        self.root_item = GLGraphicsItem()
        tr = pg.Transform3D()
        tr.rotate(90, 1, 0, 0)
        c = self.model.center
        tr.translate(-c[0], -c[1], -c[2])
        self.root_item.setTransform(tr)
        self.view.addItem(self.root_item)
        for name, part in self.model.parts.items():
            item = gl.GLMeshItem(
                meshdata=gl.MeshData(vertexes=part.triangles),
                smooth=False, shader="biomec_lit", color=_rgba(part.color), glOptions="opaque",
            )
            item.setParentItem(self.root_item)
            self.items[name] = item
        self.reset_camera()
        layout.addWidget(self.view, 1)
        hint = QLabel("Arrastra para girar · rueda para zoom · botón central para desplazar")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        return None

    def _build_side_panel(self) -> QWidget:
        card, layout = self.card("Postura")
        card.setFixedWidth(270)

        self.follow = QCheckBox("Seguir a la mano (telemetría)")
        self.follow.setChecked(True)
        self.follow.toggled.connect(self._on_follow_toggled)
        layout.addWidget(self.follow)

        grid = QGridLayout()
        self.bars, self.sliders = {}, {}
        for row, dedo in enumerate(DEDOS):
            grid.addWidget(QLabel(dedo.capitalize()), row * 2, 0)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFormat("%p% cerrado")
            grid.addWidget(bar, row * 2, 1)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.valueChanged.connect(lambda v, d=dedo: self._slider_flex(d, v))
            grid.addWidget(slider, row * 2 + 1, 1)
            self.bars[dedo], self.sliders[dedo] = bar, slider
        grid.addWidget(QLabel("Pulgar"), 6, 0)
        self.thumb_label = QLabel("10°")
        grid.addWidget(self.thumb_label, 6, 1)
        self.thumb_slider = QSlider(Qt.Horizontal)
        self.thumb_slider.setRange(0, 180)
        self.thumb_slider.setValue(10)
        self.thumb_slider.valueChanged.connect(self._slider_thumb)
        grid.addWidget(self.thumb_slider, 7, 1)
        layout.addLayout(grid)

        self.stream_btn = QPushButton("Activar telemetría")
        self.stream_btn.setObjectName("primary")
        self.stream_btn.setToolTip("Envía STREAM 1 para que la mano mande su estado y el 3D se mueva")
        self.stream_btn.clicked.connect(lambda: self.ctx.send_command("STREAM 1"))
        sync_btn = QPushButton("Sincronizar (ESTADO)")
        sync_btn.setToolTip("Pregunta a la mano qué dedos están abiertos o cerrados")
        sync_btn.clicked.connect(lambda: self.ctx.send_command("ESTADO"))
        cam_btn = QPushButton("Vista inicial")
        cam_btn.clicked.connect(self.reset_camera)
        layout.addWidget(self.stream_btn)
        layout.addWidget(sync_btn)
        layout.addWidget(cam_btn)

        note = QLabel("La posición de los dedos se estima a partir del PWM de los motores: "
                      "no hay sensor de posición. Ajustes en config/mano3d.json.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self._on_follow_toggled(True)
        return card

    def reset_camera(self) -> None:
        if self.model is not None:
            self.view.setCameraPosition(distance=self.model.size * 1.35, elevation=15, azimuth=55)
            self.view.opts["center"] = pg.Vector(0, 0, 0)

    # -------------------------------------------------------- modos/entrada
    def _on_follow_toggled(self, following: bool) -> None:
        for s in [*self.sliders.values(), self.thumb_slider]:
            s.setEnabled(not following)
        if not following:  # los deslizadores parten de la postura actual
            for d, s in self.sliders.items():
                s.setValue(round(self.flex[d] * 100))
            self.thumb_slider.setValue(round(self.thumb_target))

    def _slider_flex(self, dedo: str, value: int) -> None:
        if not self.follow.isChecked():
            self.flex[dedo] = value / 100

    def _slider_thumb(self, value: int) -> None:
        if not self.follow.isChecked():
            self.thumb_target = float(value)

    def on_message(self, msg) -> None:
        if self.model is None or not self.follow.isChecked():
            return
        if msg.kind is MessageKind.DATA:
            now = time.monotonic()
            dt = 0.0 if self._last_data is None else min(now - self._last_data, 0.25)
            self._last_data = now
            for d in DEDOS:
                if d in msg.values:  # PWM con signo: + abre, − cierra
                    delta = -msg.values[d] / 255 * dt / self.model.close_time_s
                    self.flex[d] = min(max(self.flex[d] + delta, 0.0), 1.0)
            if "pulgar" in msg.values:
                self.thumb_target = msg.values["pulgar"]
        elif msg.kind is MessageKind.ACK and msg.text.startswith("ESTADO"):
            fields = dict(tok.split("=", 1) for tok in msg.text.split() if "=" in tok)
            if fields.get("fase") == "parado":
                for d in DEDOS:
                    if fields.get(d) == "abierto":
                        self.flex[d] = 0.0
                    elif fields.get(d) == "cerrado":
                        self.flex[d] = 1.0
            try:
                self.thumb_target = float(fields.get("pulgar", self.thumb_target))
            except ValueError:
                pass

    def on_connection_changed(self, connected: bool, info: str) -> None:
        self.stream_btn.setEnabled(connected)
        self._last_data = None

    # ------------------------------------------------------------ dibujo
    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last_tick = now - self._last_tick, now
        step = self.model.thumb_speed * dt  # el servo no es instantáneo
        self.thumb_now += float(np.clip(self.thumb_target - self.thumb_now, -step, step))

        for d in DEDOS:
            self.bars[d].setValue(round(self.flex[d] * 100))
        self.thumb_label.setText(f"{self.thumb_now:.0f}°")

        state = (tuple(round(self.flex[d], 3) for d in DEDOS), round(self.thumb_now, 1))
        if state == self._applied or not self.isVisible():
            return
        self._applied = state
        for name, mat in self.model.pose(self.flex, self.thumb_now).items():
            self.items[name].setTransform(pg.Transform3D(*mat.astype(np.float32).ravel()))

    def on_theme_changed(self, theme: str) -> None:
        if self.model is not None:
            self.view.setBackgroundColor(PALETTES[theme]["plot_bg"])

    def on_shown(self) -> None:
        self._applied = None
