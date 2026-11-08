"""Editor de posturas personalizadas (inspirado en el 'Grip Builder' de PSYONIC y
las posturas propias de Össur i-Limb).

    ┌ Nueva postura ─────────────────────────────────────┐
    │  [ pictograma ]   Nombre  [ Pinza fina          ]  │
    │                   Índice  [Abierto][Cerrado][No mover]
    │                   Medio   [Abierto][Cerrado][No mover]
    │                   Anular  [Abierto][Cerrado][No mover]
    │                   Pulgar  ───────●──────  90°      │
    │  Se envía como:  POSTURA C A A 90                  │
    │  [Probar en la mano]            [Cancelar] [Guardar]│
    └────────────────────────────────────────────────────┘
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout,
)

from ..core.gestures import ABIERTO, CERRADO, DESCONOCIDO, Gesto
from ..core.postures import MAX_NAME, matching_gesture, posture_command
from .pictogram import hand_pixmap
from .theme import PALETTES
from .widgets import Segmented, style_titlebar

FINGERS = (("indice", "Índice"), ("medio", "Medio"), ("anular", "Anular"))
STATE_LABELS = ((ABIERTO, "Abierto"), (CERRADO, "Cerrado"), (DESCONOCIDO, "No mover"))


class PostureDialog(QDialog):
    def __init__(self, parent, ctx, posture: Gesto, title: str = "Nueva postura"):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("infoDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(14)
        head = QLabel(title)
        head.setObjectName("pageTitle")
        lay.addWidget(head)

        body = QHBoxLayout()
        body.setSpacing(20)
        self.preview = QLabel()
        self.preview.setFixedSize(132, 132)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setObjectName("inset")
        body.addWidget(self.preview, 0, Qt.AlignTop)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel("Nombre"), 0, 0)
        self.name = QLineEdit(posture.nombre)
        self.name.setMaxLength(MAX_NAME)
        self.name.setPlaceholderText("p. ej. Pinza fina, Llave, Ratón…")
        self.name.textChanged.connect(self._refresh)
        grid.addWidget(self.name, 0, 1)

        self.groups: dict[str, QButtonGroup] = {}
        for row, (key, label) in enumerate(FINGERS, start=1):
            grid.addWidget(QLabel(label), row, 0)
            seg = Segmented([text for _state, text in STATE_LABELS],
                            tooltips=[None, None, "Ese dedo se queda donde esté"])
            for i, (state, _text) in enumerate(STATE_LABELS):
                if getattr(posture, key) == state:
                    seg.set_current(i)
            seg.idClicked.connect(lambda _i: self._refresh())
            self.groups[key] = seg.group
            grid.addWidget(seg, row, 1)

        grid.addWidget(QLabel("Pulgar"), 4, 0)
        thumb = QHBoxLayout()
        self.thumb = QSlider(Qt.Horizontal)
        self.thumb.setRange(0, 180)
        self.thumb.setValue(int(posture.pulgar))
        self.thumb.setToolTip("Ángulo del servo del pulgar: 10° separado, 90° en pinza")
        self.thumb.valueChanged.connect(self._refresh)
        self.thumb_label = QLabel()
        self.thumb_label.setObjectName("value")
        self.thumb_label.setMinimumWidth(42)
        self.thumb_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        thumb.addWidget(self.thumb, 1)
        thumb.addWidget(self.thumb_label)
        grid.addLayout(thumb, 4, 1)
        hint = QLabel("10° separado  ·  90° en pinza")
        hint.setObjectName("muted")
        grid.addWidget(hint, 5, 1)
        body.addLayout(grid, 1)
        lay.addLayout(body)

        self.command_label = QLabel()
        self.command_label.setObjectName("muted")
        self.command_label.setTextFormat(Qt.RichText)
        self.command_label.setWordWrap(True)
        lay.addWidget(self.command_label)

        buttons = QHBoxLayout()
        self.try_btn = QPushButton("Probar en la mano")
        self.try_btn.setToolTip("Envía la postura ahora (sin guardarla) para verla en la mano y en el gemelo digital")
        self.try_btn.clicked.connect(self._try)
        self.try_btn.setEnabled(ctx.connected)
        buttons.addWidget(self.try_btn)
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Guardar")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)
        self._refresh()
        style_titlebar(self, ctx.theme)

    def posture(self) -> Gesto:
        states = {}
        for key, group in self.groups.items():
            i = group.checkedId()
            states[key] = STATE_LABELS[i][0] if i >= 0 else ABIERTO
        return Gesto(self.name.text().strip() or "Postura", states["indice"], states["medio"], states["anular"],
                     self.thumb.value())

    def _refresh(self) -> None:
        p = PALETTES[self.ctx.theme]
        g = self.posture()
        self.preview.setPixmap(hand_pixmap(g, p["muted"], p["accent"], 112))
        self.thumb_label.setText(f"{self.thumb.value()}°")
        same = matching_gesture(g)
        extra = f"  ·  igual que el gesto {same} de fábrica" if same else ""
        self.command_label.setText(f"Se envía como <b><span style='font-family:Consolas'>{posture_command(g)}</span>"
                                   f"</b>{extra}")
        self.save_btn.setEnabled(bool(self.name.text().strip()))

    def _try(self) -> None:
        self.ctx.send_command(posture_command(self.posture()))
