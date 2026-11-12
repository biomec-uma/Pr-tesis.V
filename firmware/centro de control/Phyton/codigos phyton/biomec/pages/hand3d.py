"""Gemelo digital: dos ventanas que comparten el mismo estado estimado de la mano.

  Ventana "Gemelo digital"                        Ventana "Posturas"
  ┌ [¾][Palma][Dorso][Lateral]   ● Motor en marcha ┐  ┌ Gestos (galería)              ┐
  │                                                 │  │ Mis posturas  [+ Nueva]       │
  │        modelo 3D (dedos con motor activo        │  │ Dedos: abrir / cerrar         │
  │        resaltados en azul)                      │  │ Pulgar: deslizador            │
  │                                                 │  │ Modo: Manual / Demo           │
  │ ☑ Seguir a la mano  índice 0 %  medio 0 % …     │  └───────────────────────────────┘
  └─────────────────────────────────────────────────┘

Postura del 3D:
  - Seguir a la mano: se estima con la telemetría (STREAM 1):
      PWM de cada dedo -> se integra en el tiempo -> flexión 0..1
      (no hay sensor de posición; ver "tiempo_cierre_s" en config/mano3d.json).
      Las respuestas de ESTADO corrigen la estimación (abierto/cerrado).
  - Manual (Seguir desactivado): deslizadores para ver cualquier postura sin hardware.

La vista 3D encuadra por el ALTO (core/hand_model.frustum): al abrir o cerrar otras ventanas
cambia el ancho y la mano no cambia de escala.
"""

import time
from math import radians, tan

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QMatrix4x4
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from ..core.gestures import ABIERTO, CERRADO, GESTOS, Gesto
from ..core.hand_model import DEDOS, HandModel, frustum
from ..core.postures import posture_command, posture_spec
from ..core.protocol import MessageKind
from ..paths import ASSETS_DIR, config_file
from ..ui.icons import pixmap
from ..ui.pictogram import hand_pixmap
from ..ui.theme import PALETTES
from ..ui.widgets import ElidedLabel, Segmented
from .base import BasePage

try:  # el 3D necesita PyOpenGL; si falta, la ventana lo explica en vez de romper la app
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

    class HandGLView(gl.GLViewWidget):
        """Vista 3D cuyo encuadre depende solo del alto (ver core/hand_model.frustum)."""

        def projectionMatrix(self, region, viewport):
            x0, y0, w, h = viewport
            left, right, bottom, top, near, far = frustum(self.opts["fov"], self.opts["distance"], w, h)
            # la región pintada puede ser parte del viewport (pyqtgraph lo usa para capturas por trozos)
            l_ = right * ((region[0] - x0) * (2.0 / w) - 1)
            r_ = right * ((region[0] + region[2] - x0) * (2.0 / w) - 1)
            b_ = top * ((region[1] - y0) * (2.0 / h) - 1)
            t_ = top * ((region[1] + region[3] - y0) * (2.0 / h) - 1)
            tr = QMatrix4x4()
            tr.frustum(l_, r_, b_, t_, near, far)
            return tr

        def pixelSize(self, pos):
            """Tamaño de un píxel en unidades del modelo (lo usa el desplazamiento con el ratón)."""
            cam = self.cameraPosition()
            if isinstance(pos, np.ndarray):
                cam = np.array(cam).reshape((1,) * (pos.ndim - 1) + (3,))
                dist = ((pos - cam) ** 2).sum(axis=-1) ** 0.5
            else:
                dist = (pos - cam).length()
            return dist * 2.0 * tan(0.5 * radians(self.opts["fov"])) / max(self.height(), 1)

    _GL_ERROR = None
except Exception as error:  # noqa: BLE001
    _GL_ERROR = error

# Vistas de cámara: nombre -> (azimut, elevación). La cara palmar mira hacia +Y de la vista.
CAMERAS = {"¾": (55, 15), "Palma": (90, 4), "Dorso": (270, 4), "Lateral": (180, 6)}
HIGHLIGHT = "#3b82f6"  # dedos con el motor activo
FINGER_PHALANGES = ("Proximal", "Medio", "Distal")


def _rgb(hex_color: str) -> np.ndarray:
    h = hex_color.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def _rgba(hex_color: str, alpha: float = 1.0) -> tuple:
    return tuple(_rgb(hex_color)) + (alpha,)


def _caption(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("caption")
    return label


class Hand3DPage(BasePage):
    """Controlador del gemelo: crea la ventana 3D (twin_widget) y la de posturas (posture_widget)."""

    title = "Gemelo digital"
    subtitle = "Réplica virtual de la mano: se mueve a la vez que la mano real o la simulada"
    icon = "hand"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.flex = {d: 0.0 for d in DEDOS}
        self.pwm = {d: 0.0 for d in DEDOS}
        self.thumb_target = 10.0
        self.thumb_now = 10.0
        self._last_data = None
        self._last_tick = time.monotonic()
        self._applied = None
        self._colors_applied = None
        self._thumb_user_until = 0.0
        self.model = None
        self.view = None
        self.items = {}

        self.twin_widget = self._build_twin()
        self.posture_widget = self._build_posture_widget()

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        ctx.hand_state_changed.connect(self._on_hand_state)
        ctx.replay_changed.connect(self._on_replay)
        self.on_theme_changed(ctx.theme)
        self.on_connection_changed(ctx.connected, "")

    # ============================================================ ventana 3D
    def _build_twin(self) -> QWidget:
        box = QWidget()
        box.setObjectName("transparent")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        cam_seg = Segmented(list(CAMERAS), stretch=False, tooltips=[f"Vista {name}" for name in CAMERAS])
        self.cam_group = cam_seg.group
        self.cam_group.idClicked.connect(lambda i: self.set_camera(list(CAMERAS)[i]))
        top.addWidget(cam_seg)
        top.addStretch(1)
        layout.addLayout(top)

        problem = None
        if _GL_ERROR is not None:
            problem = f"No se puede mostrar el 3D: falta PyOpenGL ({_GL_ERROR}).\nInstala con: pip install PyOpenGL"
        else:
            try:
                self.model = HandModel.load(config_file("mano3d.json"), ASSETS_DIR)
            except Exception as error:  # noqa: BLE001
                problem = f"No se pudo cargar el modelo 3D:\n{error}"
        if problem:
            msg = QLabel(problem)
            msg.setWordWrap(True)
            msg.setAlignment(Qt.AlignCenter)
            layout.addWidget(msg, 1)
            self._build_follow_bar(layout)
            return box

        self.view = HandGLView()
        self.view.setMinimumSize(220, 150)
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
        self.set_camera("¾")
        layout.addWidget(self.view, 1)
        self.view.setToolTip("Arrastrar: girar  ·  rueda: acercar  ·  botón central: desplazar")
        legend = QHBoxLayout()  # leyenda: qué significa el azul + la postura estimada
        legend.setSpacing(6)
        dot = QLabel()
        dot.setPixmap(pixmap("record", HIGHLIGHT, 12))
        legend.addWidget(dot)
        moving = QLabel("Motor en marcha")
        moving.setObjectName("legend")
        legend.addWidget(moving)
        legend.addSpacing(10)
        self.pose_label = ElidedLabel("")  # "Índice 0 % · Medio 100 % · Anular 0 % · Pulgar 10°"
        self.pose_label.setObjectName("legend")
        self.pose_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pose_label.setToolTip("% de cierre estimado de cada dedo y ángulo del pulgar")
        legend.addWidget(self.pose_label, 1)
        layout.addLayout(legend)
        self._build_follow_bar(layout)
        return box

    def _build_follow_bar(self, layout: QVBoxLayout) -> None:
        """Pie de la ventana 3D: seguir a la mano, % de cierre de cada dedo y, si se desactiva, deslizadores."""
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.follow = QCheckBox("Seguir a la mano")
        self.follow.setToolTip("Activado: el 3D imita a la mano (real o simulada) usando su telemetría.\n"
                               "Desactivado: mueve tú los deslizadores para ver cualquier postura.")
        self.follow.setChecked(True)
        self.follow.toggled.connect(self._on_follow_toggled)
        bar.addWidget(self.follow)
        bar.addStretch(1)
        if not hasattr(self, "pose_label"):  # sin 3D (falta OpenGL) la leyenda no existe
            self.pose_label = ElidedLabel("")
            self.pose_label.setObjectName("legend")
            bar.addWidget(self.pose_label, 1)
        sync_btn = self.button("", "refresh", "ghost", "Sincronizar: envía ESTADO y la mano dice qué dedos están "
                                                        "abiertos o cerrados")
        sync_btn.clicked.connect(lambda: self.ctx.send_command("ESTADO"))
        bar.addWidget(sync_btn)
        # solo mientras no llega telemetría (al conectar se activa sola)
        self.stream_btn = self.button("Telemetría", "zap", "primary",
                                      "Envía STREAM 1: la mano manda su estado ~20 veces/s y el 3D se mueve")
        self.stream_btn.clicked.connect(lambda: self.ctx.send_command("STREAM 1"))
        bar.addWidget(self.stream_btn)
        self.ctx.hand_status_changed.connect(lambda *_: self._update_stream_button())
        layout.addLayout(bar)

        # deslizadores manuales (solo con "Seguir a la mano" desactivado)
        self.manual_box = QWidget()
        self.manual_box.setObjectName("transparent")
        grid = QGridLayout(self.manual_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        self.sliders = {}
        rows = [(d, d.capitalize(), 100) for d in DEDOS] + [("pulgar", "Pulgar", 180)]
        for i, (key, label, maximum) in enumerate(rows):
            name = QLabel(label)
            name.setObjectName("muted")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, maximum)
            if key == "pulgar":
                slider.valueChanged.connect(self._slider_thumb)
            else:
                slider.valueChanged.connect(lambda v, d=key: self._slider_flex(d, v))
            grid.addWidget(name, i // 2, (i % 2) * 2)
            grid.addWidget(slider, i // 2, (i % 2) * 2 + 1)
            self.sliders[key] = slider
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.thumb_slider = self.sliders.pop("pulgar")
        self.thumb_slider.setValue(10)
        note = QLabel("Sin sensor de posición: el % cerrado se estima integrando el PWM (config/mano3d.json).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        grid.addWidget(note, 2, 0, 1, 4)
        self.manual_box.hide()
        layout.addWidget(self.manual_box)
        self._on_follow_toggled(True)

    def set_camera(self, name: str) -> None:
        if self.model is None:
            return
        azimuth, elevation = CAMERAS[name]
        self.view.setCameraPosition(distance=self.model.size * 1.25, elevation=elevation, azimuth=azimuth)
        self.view.opts["center"] = pg.Vector(0, 0, 0)
        self.cam_group.button(list(CAMERAS).index(name)).setChecked(True)

    def reset_camera(self) -> None:
        self.set_camera("¾")

    # ===================================================== ventana Posturas
    def _build_posture_widget(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumSize(240, 200)
        body = QWidget()
        body.setObjectName("transparent")
        cl = QVBoxLayout(body)
        cl.setContentsMargins(0, 2, 6, 4)
        cl.setSpacing(8)
        self._online_widgets: list[QWidget] = []  # se desactivan sin conexión

        self.offline_hint = QLabel("Conecta la mano real o la simulación (ventana Dispositivo) para controlarla.")
        self.offline_hint.setObjectName("muted")
        self.offline_hint.setWordWrap(True)
        cl.addWidget(self.offline_hint)

        # --- galería de gestos de fábrica
        cl.addWidget(_caption("Gestos"))
        gestures = QWidget()
        grid = QGridLayout(gestures)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.gesture_cards: list[QToolButton] = []
        for i, gesto in enumerate(GESTOS, start=1):
            b = self._card_button(gesto.nombre, f"GESTO {i} · {gesto.nombre}\nAtajo: Alt+{i}")
            b.clicked.connect(lambda _c=False, n=i: self.ctx.send_command(f"GESTO {n}"))
            grid.addWidget(b, (i - 1) // 2, (i - 1) % 2)
            self.gesture_cards.append(b)
        cl.addWidget(gestures)
        self._online_widgets.append(gestures)

        # --- posturas personalizadas (se pueden crear y editar sin conexión)
        cl.addSpacing(4)
        mine_head = QHBoxLayout()
        mine_head.addWidget(_caption("Mis posturas"))
        mine_head.addStretch(1)
        new_btn = QPushButton("+ Nueva")
        new_btn.setObjectName("chip")
        new_btn.setToolTip("Diseña una postura propia (p. ej. una pinza) partiendo de la postura actual de la mano")
        new_btn.clicked.connect(self.new_posture)
        mine_head.addWidget(new_btn)
        cl.addLayout(mine_head)
        self.posture_box = QWidget()
        self.posture_grid = QGridLayout(self.posture_box)
        self.posture_grid.setContentsMargins(0, 0, 0, 0)
        self.posture_grid.setSpacing(8)
        cl.addWidget(self.posture_box)
        self.posture_hint = QLabel("Crea posturas propias sin tocar el firmware: la app las envía con el comando "
                                   "POSTURA. Clic derecho sobre una para editarla.")
        self.posture_hint.setObjectName("muted")
        self.posture_hint.setWordWrap(True)
        cl.addWidget(self.posture_hint)
        self.posture_cards: list[QToolButton] = []

        # --- dedos sueltos
        cl.addSpacing(4)
        cl.addWidget(_caption("Dedos"))
        fingers_box = QWidget()
        fingers = QGridLayout(fingers_box)
        fingers.setContentsMargins(0, 0, 0, 0)
        fingers.setHorizontalSpacing(6)
        fingers.setVerticalSpacing(6)
        for row, dedo in enumerate(DEDOS):
            fingers.addWidget(QLabel(dedo.capitalize()), row, 0)
            for col_i, accion in enumerate(("Abrir", "Cerrar")):
                b = QPushButton(accion)
                b.setObjectName("chip")
                b.setToolTip(f"DEDO {dedo.upper()} {accion.upper()}")
                b.clicked.connect(lambda _c=False, d=dedo, a=accion: self.ctx.send_command(f"DEDO {d} {a}"))
                fingers.addWidget(b, row, 1 + col_i)
        fingers.setColumnStretch(0, 1)
        cl.addWidget(fingers_box)
        self._online_widgets.append(fingers_box)

        # --- pulgar
        cl.addSpacing(4)
        thumb_head = QHBoxLayout()
        thumb_head.addWidget(_caption("Pulgar"))
        thumb_head.addStretch(1)
        self.thumb_value = QLabel("10°")
        self.thumb_value.setObjectName("value")
        thumb_head.addWidget(self.thumb_value)
        cl.addLayout(thumb_head)
        self.thumb_ctrl = QSlider(Qt.Horizontal)
        self.thumb_ctrl.setRange(0, 180)
        self.thumb_ctrl.setValue(10)
        self.thumb_ctrl.setToolTip("Ángulo del servo del pulgar (10° abierto, 90° pinza). Se envía al soltar.")
        self._thumb_send = QTimer(self)
        self._thumb_send.setSingleShot(True)
        self._thumb_send.setInterval(250)
        self._thumb_send.timeout.connect(self._send_thumb)
        self.thumb_ctrl.valueChanged.connect(self._on_thumb_ctrl)
        self.thumb_ctrl.sliderReleased.connect(self._send_thumb)
        cl.addWidget(self.thumb_ctrl)
        self._online_widgets.append(self.thumb_ctrl)

        # --- modo
        cl.addSpacing(4)
        cl.addWidget(_caption("Modo"))
        # el botón marcado es el modo REAL de la mano (llega con el ACK), no el último pulsado
        modes_box = Segmented(("Manual", "Demo"), exclusive=False,
                              tooltips=("La mano solo obedece comandos",
                                        "Bucle de exposiciones: recorre los 8 gestos automáticamente (modo AUTO)"))
        self.mode_group = modes_box.group
        self.mode_buttons = {"MANUAL": modes_box.button(0), "AUTO": modes_box.button(1)}
        for key, b in self.mode_buttons.items():
            b.clicked.connect(lambda _c=False, k=key: self._set_mode(k))
        cl.addWidget(modes_box)
        self._online_widgets.append(modes_box)

        cl.addStretch(1)
        scroll.setWidget(body)
        # QScrollArea obliga al contenido a pintar su fondo con la paleta: se desactiva para que sea transparente
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        self.ctx.postures_changed.connect(self._rebuild_postures)
        self._rebuild_postures()
        return scroll

    @staticmethod
    def _card_button(text: str, tooltip: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("gestureCard")
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(46, 46))
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.setMinimumSize(100, 84)
        b.setToolTip(tooltip)
        b.setProperty("active", False)
        return b

    # ------------------------------------------------ posturas personalizadas
    def _rebuild_postures(self) -> None:
        for card in self.posture_cards:
            self.posture_grid.removeWidget(card)
            card.deleteLater()
        self.posture_cards = []
        p = PALETTES[self.ctx.theme]
        for i, g in enumerate(self.ctx.postures.items):
            b = self._card_button(g.nombre, f"{posture_command(g)}\nClic derecho: editar, duplicar o eliminar")
            b.setIcon(self._gesture_icon(g, p))
            b.clicked.connect(lambda _c=False, n=i: self.send_posture(n))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, n=i, w=b: self._posture_menu(n, w.mapToGlobal(pos)))
            self.posture_grid.addWidget(b, i // 2, i % 2)
            self.posture_cards.append(b)
        self.posture_box.setVisible(bool(self.posture_cards))
        self.posture_hint.setVisible(not self.posture_cards)
        self._on_hand_state(self.ctx.gesture, self.ctx.mode)

    def send_posture(self, index: int) -> None:
        g = self.ctx.postures.items[index]
        if not self.ctx.connected:
            self.ctx.notify(f"Postura «{g.nombre}»: conecta primero la mano o la simulación.", error=True)
            return
        self.ctx.send_command(posture_command(g))

    def _current_pose(self) -> Gesto:
        """La postura que tiene ahora la mano (estimada por el gemelo), para partir de ella."""
        states = [CERRADO if self.flex[d] >= 0.5 else ABIERTO for d in DEDOS]
        return Gesto(self.ctx.postures.unique_name("Mi postura"), *states, int(round(self.thumb_target)))

    def new_posture(self) -> None:
        from ..ui.posture_dialog import PostureDialog
        dialog = PostureDialog(self.posture_widget.window(), self.ctx, self._current_pose(), "Nueva postura")
        if dialog.exec():
            g = dialog.posture()
            g = Gesto(self.ctx.postures.unique_name(g.nombre), g.indice, g.medio, g.anular, g.pulgar)
            self._store(lambda: self.ctx.postures.add(g), f"Postura «{g.nombre}» guardada.")

    def edit_posture(self, index: int) -> None:
        from ..ui.posture_dialog import PostureDialog
        dialog = PostureDialog(self.posture_widget.window(), self.ctx, self.ctx.postures.items[index], "Editar postura")
        if dialog.exec():
            g = dialog.posture()
            g = Gesto(self.ctx.postures.unique_name(g.nombre, skip=index), g.indice, g.medio, g.anular, g.pulgar)
            self._store(lambda: self.ctx.postures.replace(index, g), f"Postura «{g.nombre}» actualizada.")

    def _posture_menu(self, index: int, pos) -> None:
        from PySide6.QtWidgets import QMenu, QMessageBox
        store = self.ctx.postures
        g = store.items[index]
        menu = QMenu(self.posture_widget)
        menu.addAction("Enviar a la mano", lambda: self.send_posture(index)).setEnabled(self.ctx.connected)
        menu.addSeparator()
        menu.addAction("Editar…", lambda: self.edit_posture(index))
        menu.addAction("Duplicar", lambda: self._store(
            lambda: store.add(Gesto(store.unique_name(g.nombre), g.indice, g.medio, g.anular, g.pulgar)),
            f"Postura «{g.nombre}» duplicada."))
        left = menu.addAction("Mover antes", lambda: self._store(lambda: store.move(index, -1)))
        left.setEnabled(index > 0)
        right = menu.addAction("Mover después", lambda: self._store(lambda: store.move(index, 1)))
        right.setEnabled(index < len(store.items) - 1)
        menu.addSeparator()

        def delete():
            answer = QMessageBox.question(self.posture_widget.window(), "Eliminar postura",
                                          f"¿Eliminar la postura «{g.nombre}»?")
            if answer == QMessageBox.Yes:
                self._store(lambda: store.remove(index), f"Postura «{g.nombre}» eliminada.")
        menu.addAction("Eliminar", delete)
        menu.exec(pos)

    def _store(self, change, done: str = "") -> None:
        try:
            change()
        except OSError as error:
            self.ctx.notify(f"No se pudieron guardar las posturas: {error}", error=True)
            return
        self.ctx.postures_changed.emit()
        if done:
            self.ctx.notify(done, toast=True)

    # ====================================================== entradas
    def _on_follow_toggled(self, following: bool) -> None:
        self.manual_box.setVisible(not following)
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

    def _on_thumb_ctrl(self, value: int) -> None:
        self.thumb_value.setText(f"{value}°")
        self._thumb_user_until = time.monotonic() + 1.5
        if not self.thumb_ctrl.isSliderDown():  # teclado / rueda: se envía tras una pausa
            self._thumb_send.start()

    def _send_thumb(self) -> None:
        self._thumb_send.stop()
        self._thumb_user_until = time.monotonic() + 1.0
        self.ctx.send_command(f"PULGAR {self.thumb_ctrl.value()}")

    def _set_mode(self, mode: str) -> None:
        self.ctx.send_command(mode)
        self._on_hand_state(self.ctx.gesture, self.ctx.mode)  # el botón refleja el modo real (llega con el ACK)

    def _on_hand_state(self, gesture: int, mode: str) -> None:
        posture = self.ctx.posture if gesture == 0 else ""
        cards = [(card, i == gesture) for i, card in enumerate(self.gesture_cards, start=1)]
        cards += [(card, bool(posture) and posture_spec(g) == posture)
                  for card, g in zip(self.posture_cards, self.ctx.postures.items)]
        for card, active in cards:
            if card.property("active") != active:
                card.setProperty("active", active)
                card.style().unpolish(card)
                card.style().polish(card)
        for key, b in self.mode_buttons.items():
            b.setChecked(key == mode)

    def on_message(self, msg) -> None:
        if msg.kind is MessageKind.DATA:
            for d in DEDOS:
                if d in msg.values:
                    self.pwm[d] = msg.values[d]
        if not self.follow.isChecked():
            return
        if msg.kind is MessageKind.DATA:
            now = time.monotonic()
            scale = getattr(self.ctx, "time_scale", 1.0)  # reproducción de sesiones a 2x, 4x...
            dt = 0.0 if self._last_data is None else min((now - self._last_data) * scale, 0.25)
            self._last_data = now
            close_time = self.model.close_time_s if self.model is not None else 1.5
            for d in DEDOS:
                if d in msg.values:  # PWM con signo: + abre, − cierra
                    delta = -msg.values[d] / 255 * dt / close_time
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

    def _update_stream_button(self) -> None:
        self.stream_btn.setVisible(self.ctx.connected and not self.ctx.replaying and self.ctx.data_rate == 0)

    def on_connection_changed(self, connected: bool, info: str) -> None:
        self.stream_btn.setEnabled(connected)
        self._update_stream_button()
        for w in self._online_widgets:
            w.setEnabled(connected)
        self.offline_hint.setText("Reproduciendo una sesión grabada: los controles se activan al cerrarla."
                                  if self.ctx.replaying else
                                  "Conecta la mano real o la simulación (ventana Dispositivo) para controlarla.")
        self.offline_hint.setVisible(not connected)
        self._last_data = None
        if not connected:
            self.pwm = {d: 0.0 for d in DEDOS}

    def _on_replay(self, _replaying: bool) -> None:
        """Al empezar o terminar una reproducción, el gemelo parte de la mano abierta."""
        self.flex = {d: 0.0 for d in DEDOS}
        self.pwm = {d: 0.0 for d in DEDOS}
        self._last_data = None
        self.on_connection_changed(self.ctx.connected, "")

    # ======================================================== dibujo
    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last_tick = now - self._last_tick, now
        speed = self.model.thumb_speed if self.model is not None else 300.0
        step = speed * dt  # el servo no es instantáneo
        self.thumb_now += float(np.clip(self.thumb_target - self.thumb_now, -step, step))

        following = self.follow.isChecked()
        parts = []
        for d in DEDOS:
            pct = round(self.flex[d] * 100)
            parts.append(f"{d.capitalize()} {pct} %")
            if following:  # el deslizador muestra la estimación, sin disparar cambios
                self.sliders[d].blockSignals(True)
                self.sliders[d].setValue(pct)
                self.sliders[d].blockSignals(False)
        parts.append(f"Pulgar {self.thumb_now:.0f}°")
        text = "  ·  ".join(parts)
        if text != self.pose_label.text():
            self.pose_label.setText(text)
        if following:
            self.thumb_slider.blockSignals(True)
            self.thumb_slider.setValue(round(self.thumb_now))
            self.thumb_slider.blockSignals(False)
        if now > self._thumb_user_until and not self.thumb_ctrl.isSliderDown():
            self.thumb_ctrl.blockSignals(True)  # el control refleja el ángulo real del pulgar
            self.thumb_ctrl.setValue(round(self.thumb_target))
            self.thumb_ctrl.blockSignals(False)
            self.thumb_value.setText(f"{round(self.thumb_target)}°")

        if self.model is None or not self.view.isVisible():
            return
        self._apply_colors()
        state = (tuple(round(self.flex[d], 3) for d in DEDOS), round(self.thumb_now, 1))
        if state == self._applied:
            return
        self._applied = state
        for name, mat in self.model.pose(self.flex, self.thumb_now).items():
            self.items[name].setTransform(pg.Transform3D(*mat.astype(np.float32).ravel()))

    def _apply_colors(self) -> None:
        """Resalta en azul los dedos cuyo motor recibe potencia (y el pulgar mientras se mueve)."""
        levels = {d: round(min(abs(self.pwm[d]) / 255, 1.0), 1) for d in DEDOS}
        levels["pulgar"] = 1.0 if abs(self.thumb_target - self.thumb_now) > 0.5 else 0.0
        key = tuple(sorted(levels.items()))
        if key == self._colors_applied:
            return
        self._colors_applied = key
        hi = _rgb(HIGHLIGHT)
        for d in DEDOS:
            for role in FINGER_PHALANGES:
                part = self.model.parts[f"{d}/{role}"]
                mix = (1 - 0.75 * levels[d]) * _rgb(part.color) + 0.75 * levels[d] * hi
                self.items[f"{d}/{role}"].setColor(tuple(mix) + (1.0,))
        part = self.model.parts["pulgar"]
        mix = (1 - 0.6 * levels["pulgar"]) * _rgb(part.color) + 0.6 * levels["pulgar"] * hi
        self.items["pulgar"].setColor(tuple(mix) + (1.0,))

    def on_theme_changed(self, theme: str) -> None:
        p = PALETTES[theme]
        if self.view is not None:
            self.view.setBackgroundColor(p["inset"])
        for i, card in enumerate(self.gesture_cards):
            card.setIcon(self._gesture_icon(GESTOS[i], p))
        for card, g in zip(self.posture_cards, self.ctx.postures.items):
            card.setIcon(self._gesture_icon(g, p))

    @staticmethod
    def _gesture_icon(gesto, p):
        from PySide6.QtGui import QIcon
        ic = QIcon()
        ic.addPixmap(hand_pixmap(gesto, p["muted"], p["accent"], 46), QIcon.Normal)
        ic.addPixmap(hand_pixmap(gesto, p["border_strong"], p["subtle"], 46), QIcon.Disabled)
        return ic

    def on_shown(self) -> None:
        self._applied = None
        self._colors_applied = None
