"""Pictogramas de la mano para la galería de gestos.

Se dibujan a partir de la definición de cada gesto (core/gestures.py), así que
un gesto nuevo tiene su icono sin diseñar nada. La mano tiene tres dedos
(índice, medio y anular+meñique) y el pulgar, igual que la prótesis.

    abierto: dedo largo          cerrado: dedo corto plegado (con su "uña" hacia la palma)
    "no mover" (posturas personalizadas): dedo largo semitransparente
    pulgar < 50°: separado        pulgar ≥ 50°: en pinza hacia el índice
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from ..core.gestures import CERRADO, DESCONOCIDO, Gesto


def _capsule(painter: QPainter, x: float, y_base: float, length: float, width: float) -> None:
    """Dedo vertical con la base en y_base que crece hacia arriba."""
    painter.drawRoundedRect(QRectF(x - width / 2, y_base - length, width, length + width / 2), width / 2, width / 2)


def hand_pixmap(gesto: Gesto, fill: str, accent: str, size: int = 64) -> QPixmap:
    """Pictograma de un gesto. fill = color de la mano; accent = color de los dedos cerrados."""
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size * ratio / 64, size * ratio / 64)  # se dibuja en una rejilla de 64x64

    hand = QColor(fill)
    closed = QColor(accent)
    p.setPen(Qt.NoPen)

    # --- palma
    p.setBrush(hand)
    palm = QPainterPath()
    palm.addRoundedRect(QRectF(19, 29, 30, 28), 8, 8)
    p.drawPath(palm)

    # --- dedos (índice junto al pulgar, a la izquierda)
    xs = {"indice": 24.5, "medio": 34, "anular": 43.5}
    lengths = {"indice": 22, "medio": 25, "anular": 20}
    for dedo, x in xs.items():
        if gesto.dedos()[dedo] == CERRADO:
            p.setBrush(closed)
            _capsule(p, x, 31, 6, 8.2)          # dedo plegado: corto
            p.setBrush(hand.darker(125))
            p.drawEllipse(QPointF(x, 33.5), 2.4, 2.4)  # punta plegada sobre la palma
        elif gesto.dedos()[dedo] == DESCONOCIDO:
            ghost = QColor(hand)
            ghost.setAlphaF(0.35)
            p.setBrush(ghost)
            _capsule(p, x, 31, lengths[dedo], 8.2)
        else:
            p.setBrush(hand)
            _capsule(p, x, 31, lengths[dedo], 8.2)

    # --- pulgar
    p.save()
    pinza = gesto.pulgar >= 50
    p.translate(21, 47)
    p.rotate(28 if pinza else -38)               # en pinza apunta hacia el índice
    p.setBrush(closed if pinza else hand)
    _capsule(p, 0, 0, 13 if pinza else 16, 8.2)
    p.restore()

    # --- contorno suave de la muñeca
    p.setPen(QPen(hand.darker(140), 1.2))
    p.drawLine(QPointF(26, 59.5), QPointF(42, 59.5))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm
