"""Iconos de línea (SVG) que se colorean según el tema.

Trazos basados en Lucide (https://lucide.dev, licencia ISC).
Uso:  icon("terminal", "#8b98ad")  ·  nav_icon("terminal", normal, activo)
Para añadir uno: copia su <path d="..."> de lucide.dev en ICONS.
"""

from pathlib import Path
import tempfile

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICONS = {
    "terminal": '<path d="M4 17l6-6-6-6"/><path d="M12 19h8"/>',
    "list": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "hand": '<path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2"/><path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v2"/>'
            '<path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"/>'
            '<path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
    "plug": '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
    "flask": '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/>'
             '<path d="M8.5 2h7"/><path d="M7 16h10"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/>'
           '<path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
               '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "play": '<path d="M6 3l14 9-14 9V3z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "pencil": '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    "rotate": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "zap": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "power": '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/>',
    "corner": '<path d="m9 14 5 5 5-5"/><path d="M4 4v7a4 4 0 0 0 4 4h11"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "octagon": '<path d="m15 9-6 6"/><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688'
               'A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414'
               'l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"/><path d="m9 9 6 6"/>',
    "keyboard": '<path d="M10 8h.01"/><path d="M12 12h.01"/><path d="M14 8h.01"/><path d="M16 12h.01"/>'
                '<path d="M18 8h.01"/><path d="M6 8h.01"/><path d="M7 16h10"/><path d="M8 12h.01"/>'
                '<rect width="20" height="16" x="2" y="4" rx="2"/>',
    "command": '<path d="M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"/>',
    "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
              '<circle cx="12" cy="13" r="3"/>',
    "close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "chevron_up": '<path d="m18 15-6-6-6 6"/>',
    "chevron_right": '<path d="m9 18 6-6-6-6"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "record": '<circle cx="12" cy="12" r="6.5" fill="currentColor" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "folder": '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5'
              'a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "save": '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
            '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    "download": '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
    "cpu": '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/>'
           '<path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/>'
           '<path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "brain": '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>'
             '<path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>'
             '<path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M17.599 6.5a3 3 0 0 0 .399-1.375"/>'
             '<path d="M6.003 5.125A3 3 0 0 0 6.401 6.5"/><path d="M3.477 10.896a4 4 0 0 1 .585-.396"/>'
             '<path d="M19.938 10.5a4 4 0 0 1 .585.396"/><path d="M6 18a4 4 0 0 1-1.967-.516"/>'
             '<path d="M19.967 17.484A4 4 0 0 1 18 18"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5'
                'l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063'
                'a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/>'
                '<path d="M4 17v2"/><path d="M5 18H3"/>',
    "key": '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/>'
           '<circle cx="7.5" cy="15.5" r="5.5"/>',
    "bot": '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/>'
           '<path d="M15 13v2"/><path d="M9 13v2"/>',
    "user": '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
    "mic": '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/>'
           '<path d="M12 19v3"/>',
    # EMG: visor (señal en carriles) y analizador (gráfica de barras)
    "waveform": '<path d="M2 13a2 2 0 0 0 2-2V7a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0V4a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0v-4'
                'a2 2 0 0 1 2-2"/>',
    "chart": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    # espacio de trabajo (ventanas)
    "layout": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>',
    "float": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
             '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "dock": '<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="m14 10 7-7"/><path d="m3 21 7-7"/>',
    "grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/>'
            '<rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "sidebar": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "chevron_left": '<path d="m15 18-6-6 6-6"/>',
    "chevrons_left": '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
    "chevrons_right": '<path d="m6 17 5-5-5-5"/><path d="m13 17 5-5-5-5"/>',
}


def _svg(name: str, color: str, stroke: float = 2.0) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'color="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>').encode()


def pixmap(name: str, color: str, size: int = 18, stroke: float = 2.0) -> QPixmap:
    ratio = 2  # se dibuja al doble para pantallas de alta densidad
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(_svg(name, color, stroke))).render(painter, QRectF(0, 0, size * ratio, size * ratio))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))


def nav_icon(name: str, normal: str, active: str, size: int = 18) -> QIcon:
    """Icono para botones que se pueden marcar: un color normal y otro cuando están activos."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, normal, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, active, size), QIcon.Active, QIcon.On)
    return ic


def qss_icon_file(name: str, color: str, stroke: float = 2.5) -> str:
    """Escribe el SVG en una carpeta temporal y devuelve su ruta para usarla en la hoja de estilos (url(...))."""
    folder = Path(tempfile.gettempdir()) / "biomec_icons"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}_{color.lstrip('#')}.svg"
    if not path.exists():
        path.write_bytes(_svg(name, color, stroke))
    return path.as_posix()


def logo_badge(size: int, glyph_color: str, logo_path: Path) -> QPixmap:
    """El dibujo blanco del logo (sin su fondo negro/azul) coloreado con glyph_color."""
    import numpy as np

    ratio = 2
    src = QImage(str(logo_path)).scaled(size * ratio, size * ratio, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    src = src.convertToFormat(QImage.Format_ARGB32)
    w, h = src.width(), src.height()
    arr = np.frombuffer(src.constBits(), dtype=np.uint8).reshape(h, src.bytesPerLine() // 4, 4)[:, :w]
    lum = arr[..., :3].max(axis=2).astype(np.float32)
    bg = float(np.median(np.concatenate([lum[0], lum[-1], lum[:, 0], lum[:, -1]])))
    alpha = np.clip((lum - bg) / max(255.0 - bg, 1.0), 0, 1)
    c = glyph_color.lstrip("#")
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., 2], out[..., 1], out[..., 0] = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)  # BGRA
    out[..., 3] = (alpha * 255).astype(np.uint8)
    img = QImage(out.tobytes(), w, h, w * 4, QImage.Format_ARGB32).copy()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(ratio)
    return pm


def app_icon_pixmap(size: int = 256) -> QPixmap:
    """Icono de la app: insignia azul redondeada con el dibujo del logo en blanco."""
    from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainterPath

    from ..paths import asset

    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#1e3a8a"))
    path = QPainterPath()
    m = size * 0.04
    path.addRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.22, size * 0.22)
    p.fillPath(path, QBrush(grad))
    glyph = logo_badge(max(int(size * 0.9), 8), "#ffffff", asset("biomec_logo_dark.png"))
    gw = glyph.width() / glyph.devicePixelRatio()
    gh = glyph.height() / glyph.devicePixelRatio()
    p.drawPixmap(QRectF((size - gw) / 2, (size - gh) / 2, gw, gh), glyph, QRectF(glyph.rect()))
    p.end()
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(app_icon_pixmap(s))
    return ic


def save_app_icon(path: str) -> None:
    """Guarda el icono (.ico/.png) para el ejecutable. Uso: python -c "...save_app_icon('assets/biomec.ico')"."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    app_icon_pixmap(256).toImage().save(path)
