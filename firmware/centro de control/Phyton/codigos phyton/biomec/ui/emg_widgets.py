"""Widgets dibujados a mano para la pestaña Entrenamiento.

  LevelBars        activación de cada canal (como el medidor de las apps de calibración)
  ProbBars         probabilidad de cada movimiento; el elegido, resaltado
  ConfusionMatrix  qué movimientos se confunden con cuáles (filas = real, columnas = predicho)
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import PALETTES


def _color(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


class LevelBars(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.levels: list[float] = []
        self.setMinimumSize(96, 120)
        self.setToolTip("Activación de cada canal (amplitud media de los últimos 100 ms)")

    def set_levels(self, levels: list[float]) -> None:
        self.levels = levels
        self.update()

    def paintEvent(self, _event) -> None:
        p = PALETTES[self.ctx.theme]
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        n = max(len(self.levels), 1)
        w, h = self.width(), self.height()
        gap = 8
        bw = min(26.0, (w - gap * (n + 1)) / n)
        total = n * bw + (n - 1) * gap
        x = (w - total) / 2
        top, bottom = 18, h - 20
        font = qp.font()
        font.setPointSizeF(8)
        qp.setFont(font)
        if not self.levels:
            qp.setPen(QColor(p["subtle"]))
            qp.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "sin señal")
            qp.end()
            return
        for i, level in enumerate(self.levels):
            level = min(max(level, 0.0), 1.0)
            track = QRectF(x, top, bw, bottom - top)
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(p["border"]))
            qp.drawRoundedRect(track, 5, 5)
            fill_h = track.height() * level
            qp.setBrush(QColor(p["accent"]))
            qp.drawRoundedRect(QRectF(x, bottom - fill_h, bw, fill_h), 5, 5)
            qp.setPen(QColor(p["muted"]))
            qp.drawText(QRectF(x - 6, bottom + 3, bw + 12, 16), Qt.AlignHCenter | Qt.AlignTop, f"C{i + 1}")
            qp.setPen(QColor(p["text"]))
            qp.drawText(QRectF(x - 8, 0, bw + 16, 16), Qt.AlignHCenter | Qt.AlignBottom, f"{level * 100:.0f}")
            x += bw + gap
        qp.end()


class ProbBars(QWidget):
    ROW = 26

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.classes: list[str] = []
        self.probs: list[float] = []
        self.winner = -1
        self.threshold = 0.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_classes(self, classes: list[str]) -> None:
        self.classes = list(classes)
        self.probs = [0.0] * len(classes)
        self.winner = -1
        self.setFixedHeight(max(len(classes), 1) * self.ROW + 4)
        self.update()

    def set_data(self, probs, winner: int, threshold: float) -> None:
        self.probs = [float(v) for v in probs]
        self.winner = winner
        self.threshold = threshold
        self.update()

    def paintEvent(self, _event) -> None:
        p = PALETTES[self.ctx.theme]
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        name_w, pct_w = min(130, int(w * 0.38)), 44
        bar_x, bar_w = name_w + 8, max(w - name_w - pct_w - 16, 20)
        for i, (name, prob) in enumerate(zip(self.classes, self.probs)):
            y = 2 + i * self.ROW
            win = i == self.winner
            qp.setPen(QColor(p["text"] if win else p["muted"]))
            font = qp.font()
            font.setBold(win)
            qp.setFont(font)
            qp.drawText(QRectF(0, y, name_w, self.ROW - 4), Qt.AlignVCenter | Qt.AlignLeft,
                        qp.fontMetrics().elidedText(name, Qt.ElideRight, name_w))
            track = QRectF(bar_x, y + 7, bar_w, self.ROW - 18)
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(p["border"]))
            qp.drawRoundedRect(track, 4, 4)
            qp.setBrush(QColor(p["accent"]) if win else _color(p["muted"], 0.55))
            qp.drawRoundedRect(QRectF(bar_x, y + 7, bar_w * min(max(prob, 0), 1), self.ROW - 18), 4, 4)
            qp.setPen(QColor(p["text"] if win else p["muted"]))
            qp.drawText(QRectF(bar_x + bar_w + 6, y, pct_w, self.ROW - 4), Qt.AlignVCenter | Qt.AlignRight,
                        f"{prob * 100:.0f} %")
        if self.threshold > 0 and self.classes:  # línea de la confianza mínima
            x = bar_x + bar_w * self.threshold
            qp.setPen(QPen(QColor(p["warn"]), 1, Qt.DashLine))
            qp.drawLine(int(x), 2, int(x), 2 + len(self.classes) * self.ROW - 6)
        qp.end()


class ConfusionMatrix(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.classes: list[str] = []
        self.matrix = None
        self.setMinimumHeight(120)
        self.setToolTip("Filas: el movimiento que hiciste · columnas: lo que detectó el modelo.\n"
                        "La diagonal son los aciertos; lo demás, confusiones (en % de cada fila).")

    def set_report(self, classes, matrix) -> None:
        self.classes = list(classes)
        self.matrix = matrix
        self.update()

    def paintEvent(self, _event) -> None:
        p = PALETTES[self.ctx.theme]
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        if self.matrix is None or not self.classes:
            qp.setPen(QColor(p["subtle"]))
            qp.drawText(self.rect(), Qt.AlignCenter, "Entrena un modelo para ver la matriz de confusión")
            qp.end()
            return
        k = len(self.classes)
        font = qp.font()
        font.setPointSizeF(8.5)
        qp.setFont(font)
        fm = qp.fontMetrics()
        label_w = min(max(fm.horizontalAdvance(f"{i + 1}  {c}") for i, c in enumerate(self.classes)) + 10, 150)
        head_h = 18
        cell = max(min((self.width() - label_w) / k, (self.height() - head_h) / k, 54), 16)
        x0, y0 = label_w, head_h
        qp.setPen(QColor(p["muted"]))
        for j in range(k):  # cabecera: número de la clase predicha
            qp.drawText(QRectF(x0 + j * cell, 0, cell, head_h), Qt.AlignCenter, str(j + 1))
        rows = self.matrix.sum(axis=1)
        for i, name in enumerate(self.classes):
            qp.setPen(QColor(p["muted"]))
            qp.drawText(QRectF(0, y0 + i * cell, label_w - 6, cell), Qt.AlignVCenter | Qt.AlignRight,
                        fm.elidedText(f"{i + 1}  {name}", Qt.ElideRight, label_w - 6))
            for j in range(k):
                frac = float(self.matrix[i, j] / rows[i]) if rows[i] else 0.0
                rect = QRectF(x0 + j * cell + 1.5, y0 + i * cell + 1.5, cell - 3, cell - 3)
                base = p["ok"] if i == j else p["error"]
                qp.setPen(Qt.NoPen)
                qp.setBrush(_color(base, 0.08 + 0.75 * frac) if frac > 0 else QColor(p["inset"]))
                qp.drawRoundedRect(rect, 4, 4)
                if frac > 0:
                    qp.setPen(QColor("#ffffff") if frac > 0.55 else QColor(p["text"]))
                    small = qp.font()
                    small.setBold(i == j)
                    qp.setFont(small)
                    qp.drawText(rect, Qt.AlignCenter, f"{frac * 100:.0f}")
                    qp.setFont(font)
        qp.end()

