"""Paletas y hoja de estilos de la app.

Para cambiar colores solo hay que tocar PALETTES. Los nombres de los objetos
(setObjectName) que se estilan aquí: card, cardTitle, sidebar, brandName,
brandSub, navButton, sectionLabel, pageTitle, pageSubtitle, statusPill,
simBanner, muted, primary, ghost, segmentReal, segmentSim, inset, devicePanel.
"""

from .icons import qss_icon_file

FONT = "'Segoe UI Variable Text', 'Segoe UI', sans-serif"
MONO = "'Cascadia Mono', 'Cascadia Code', Consolas, monospace"

PALETTES = {
    "dark": {
        "bg": "#0b0f17", "sidebar": "#0e131c", "card": "#131a25", "inset": "#0f151f",
        "border": "#212b3a", "border_strong": "#2f3b4f",
        "text": "#e6ebf3", "muted": "#8a96aa", "subtle": "#5f6b80",
        "accent": "#3b82f6", "accent_hover": "#2f73e0", "accent_text": "#8ab4ff",
        "accent_soft": "rgba(59, 130, 246, 0.14)", "hover": "rgba(255, 255, 255, 0.05)",
        "accent_soft_solid": "#17243b",
        "button": "#1a2231", "button_hover": "#212b3d", "segment_on": "#212c3e",
        "ok": "#34d399", "warn": "#fbbf24", "error": "#ef4444", "tx": "#7fb0ff", "danger_hover": "#dc2626",
        "ok_soft": "rgba(52, 211, 153, 0.12)", "error_soft": "rgba(248, 113, 113, 0.10)",
        "sim_bg": "rgba(251, 191, 36, 0.10)", "sim_text": "#fbbf24", "sim_border": "rgba(251, 191, 36, 0.35)",
        "plot_bg": "#0f151f", "plot_axis": "#8a96aa",
        "selection": "rgba(59, 130, 246, 0.35)",
    },
    "light": {
        "bg": "#f3f5f9", "sidebar": "#ffffff", "card": "#ffffff", "inset": "#f7f9fc",
        "border": "#e2e7ef", "border_strong": "#cdd5e1",
        "text": "#0f172a", "muted": "#5b6678", "subtle": "#97a2b3",
        "accent": "#2563eb", "accent_hover": "#1d4fd8", "accent_text": "#1d4ed8",
        "accent_soft": "rgba(37, 99, 235, 0.09)", "hover": "rgba(15, 23, 42, 0.04)",
        "accent_soft_solid": "#e9f0fd",
        "button": "#ffffff", "button_hover": "#f1f4f9", "segment_on": "#ffffff",
        "ok": "#059669", "warn": "#b45309", "error": "#dc2626", "tx": "#2563eb", "danger_hover": "#b91c1c",
        "ok_soft": "rgba(5, 150, 105, 0.10)", "error_soft": "rgba(220, 38, 38, 0.08)",
        "sim_bg": "#fff8e8", "sim_text": "#92400e", "sim_border": "#f3cf7f",
        "plot_bg": "#ffffff", "plot_axis": "#5b6678",
        "selection": "rgba(37, 99, 235, 0.18)",
    },
}

# Colores de las curvas de las gráficas (se reparten en orden).
PLOT_COLORS = ["#3b82f6", "#f97316", "#10b981", "#e11d48", "#a855f7", "#eab308", "#06b6d4", "#84cc16"]


def stylesheet(theme: str) -> str:
    p = PALETTES[theme]
    check = qss_icon_file("check", "#ffffff", 3)
    down = qss_icon_file("chevron_down", p["muted"])
    up = qss_icon_file("chevron_up", p["muted"])
    right = qss_icon_file("chevron_right", p["muted"])
    return f"""
    * {{ font-family: {FONT}; font-size: 10pt; }}
    QWidget {{ color: {p['text']}; }}
    QMainWindow, QDialog {{ background: {p['bg']}; }}
    QScrollArea {{ background: transparent; border: 0; }}
    QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}

    /* ---------- estructura ---------- */
    QWidget#sidebar {{ background: {p['sidebar']}; border-right: 1px solid {p['border']}; }}
    QLabel#brandName {{ font-size: 13pt; font-weight: 700; letter-spacing: 0.5px; }}
    QLabel#brandSub {{ color: {p['muted']}; font-size: 8.5pt; }}
    QLabel#sectionLabel {{ color: {p['subtle']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding: 0 10px; }}
    QPushButton#navButton {{ text-align: left; padding: 9px 12px; border: 0; border-radius: 8px;
        background: transparent; color: {p['muted']}; font-weight: 600; }}
    QPushButton#navButton:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QPushButton#navButton:checked {{ background: {p['accent_soft']}; color: {p['accent_text']}; }}
    QPushButton#toolButton {{ text-align: left; padding: 9px 12px; border: 0; border-radius: 8px;
        background: transparent; color: {p['muted']}; font-weight: 600; }}
    QPushButton#toolButton:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QPushButton#toolButton:checked {{ color: {p['accent_text']}; }}
    QWidget#devicePanel {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 12px; }}

    QLabel#pageTitle {{ font-size: 16pt; font-weight: 700; }}
    QLabel#pageSubtitle {{ color: {p['muted']}; }}
    QLabel#pageBadge {{ background: {p['accent_soft']}; border-radius: 10px; }}
    QLabel#statusPill {{ font-weight: 600; font-size: 9pt; }}
    QWidget#simBanner {{ background: {p['sim_bg']}; border: 1px solid {p['sim_border']}; border-radius: 8px; }}
    QLabel#simText {{ color: {p['sim_text']}; font-weight: 600; font-size: 9pt; }}
    QPushButton#headerIcon {{ background: transparent; border: 1px solid {p['border']}; border-radius: 8px; padding: 0; }}
    QPushButton#headerIcon:hover {{ background: {p['hover']}; border-color: {p['border_strong']}; }}
    QPushButton#headerIcon:disabled {{ border-color: {p['border']}; }}
    QPushButton#headerIcon[active="true"] {{ background: {p['accent_soft']}; border-color: {p['accent']}; }}
    QLabel#voiceCaption {{ color: {p['accent_text']}; font-style: italic; }}
    QFrame#headerSep {{ background: {p['border']}; }}
    QLabel#version {{ color: {p['subtle']}; font-size: 8.5pt; }}

    QWidget#card {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 12px; }}
    QLabel#cardTitle {{ font-size: 10.5pt; font-weight: 700; }}
    QLabel#muted {{ color: {p['muted']}; }}
    QLabel#value {{ color: {p['text']}; font-weight: 600; }}
    QStatusBar {{ background: {p['sidebar']}; color: {p['muted']}; border-top: 1px solid {p['border']}; font-size: 9pt; }}
    QStatusBar QLabel {{ color: {p['muted']}; font-size: 9pt; }}

    /* ---------- botones ---------- */
    QPushButton {{ background: {p['button']}; border: 1px solid {p['border_strong']}; border-radius: 8px;
        padding: 7px 14px; color: {p['text']}; font-weight: 600; }}
    QPushButton:hover {{ background: {p['button_hover']}; }}
    QPushButton:pressed {{ background: {p['border']}; }}
    QPushButton:disabled {{ color: {p['subtle']}; border-color: {p['border']}; background: transparent; }}
    QPushButton#primary {{ background: {p['accent']}; border-color: {p['accent']}; color: white; }}
    QPushButton#primary:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
    QPushButton#primary:disabled {{ background: {p['border']}; border-color: {p['border']}; color: {p['subtle']}; }}
    QPushButton#ghost {{ background: transparent; border-color: transparent; color: {p['muted']}; padding: 7px 10px; }}
    QPushButton#ghost:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QWidget#segmented {{ background: {p['inset']}; border: 1px solid {p['border']}; border-radius: 9px; }}
    QPushButton#segment, QPushButton#segmentReal, QPushButton#segmentSim {{ background: transparent;
        border: 1px solid transparent; border-radius: 7px; padding: 5px 12px; color: {p['muted']}; font-weight: 600; }}
    QPushButton#segment:hover, QPushButton#segmentReal:hover, QPushButton#segmentSim:hover {{ color: {p['text']}; }}
    QPushButton#segment:checked {{ background: {p['segment_on']}; border-color: {p['border_strong']}; color: {p['text']}; }}
    QPushButton#segment:disabled {{ color: {p['subtle']}; }}
    QPushButton#segment:checked:disabled {{ color: {p['muted']}; }}
    QPushButton#segmentReal:checked {{ background: {p['accent_soft']}; border-color: {p['accent']}; color: {p['accent_text']}; }}
    QPushButton#segmentSim:checked {{ background: {p['sim_bg']}; border-color: {p['sim_border']}; color: {p['sim_text']}; }}
    QPushButton#toggleChip {{ background: transparent; border: 1px solid {p['border']}; border-radius: 8px;
        padding: 6px 10px; color: {p['muted']}; font-weight: 600; }}
    QPushButton#toggleChip:hover {{ border-color: {p['border_strong']}; color: {p['text']}; }}
    QPushButton#toggleChip:checked {{ background: {p['accent_soft']}; border-color: {p['accent']}; color: {p['accent_text']}; }}
    QPushButton#toggleChip:disabled {{ color: {p['subtle']}; }}

    /* ---------- entradas ---------- */
    QLineEdit, QComboBox, QSpinBox {{ background: {p['inset']}; border: 1px solid {p['border']}; border-radius: 8px;
        padding: 6px 10px; color: {p['text']}; selection-background-color: {p['selection']}; min-height: 20px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {p['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {p['subtle']}; }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox::down-arrow {{ image: url({down}); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{ background: {p['card']}; border: 1px solid {p['border_strong']}; border-radius: 8px;
        padding: 4px; selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; outline: 0; }}
    QSpinBox::up-button, QSpinBox::down-button {{ border: 0; width: 18px; background: transparent; }}
    QSpinBox::up-arrow {{ image: url({up}); width: 12px; height: 12px; }}
    QSpinBox::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}

    QPlainTextEdit, QTextEdit {{ background: {p['inset']}; border: 1px solid {p['border']}; border-radius: 10px;
        padding: 8px; color: {p['text']}; selection-background-color: {p['selection']}; }}
    QPlainTextEdit#log {{ font-family: {MONO}; font-size: 9.5pt; }}

    QCheckBox {{ spacing: 8px; color: {p['text']}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {p['border_strong']};
        background: {p['inset']}; }}
    QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url({check}); }}

    QSlider::groove:horizontal {{ height: 4px; background: {p['border']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal:disabled {{ background: {p['subtle']}; }}
    QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
        background: white; border: 2px solid {p['accent']}; }}
    QSlider::handle:horizontal:disabled {{ border-color: {p['subtle']}; background: {p['card']}; }}

    QProgressBar {{ background: {p['border']}; border: 0; border-radius: 3px; max-height: 6px; }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 3px; }}

    QPushButton#tabButton {{ background: transparent; border: 1px solid {p['border']}; color: {p['muted']}; padding: 5px 10px; }}
    QPushButton#tabButton:hover {{ background: {p['hover']}; }}
    QPushButton#tabButton:checked {{ background: {p['accent_soft']}; border-color: {p['accent']}; color: {p['accent_text']}; }}
    QDialog#commandPalette {{ background: transparent; }}
    QFrame#palette {{ background: {p['card']}; border: 1px solid {p['border_strong']}; border-radius: 14px; }}
    QLineEdit#paletteInput {{ font-size: 11pt; padding: 10px 12px; border: 0; background: transparent; }}
    QListWidget#paletteList {{ background: transparent; border: 0; border-top: 1px solid {p['border']};
        border-radius: 0; padding: 4px 0; }}
    QDialog#infoDialog {{ background: {p['card']}; }}
    QLabel#kbd {{ background: {p['inset']}; border: 1px solid {p['border_strong']}; border-radius: 5px;
        padding: 2px 7px; font-family: {MONO}; font-size: 9pt; color: {p['text']}; }}
    QLabel#caption {{ color: {p['subtle']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
    QToolButton#gestureCard {{ background: {p['inset']}; border: 1px solid {p['border']}; border-radius: 10px;
        padding: 8px 4px 7px 4px; color: {p['text']}; font-weight: 600; font-size: 9pt; }}
    QToolButton#gestureCard:hover {{ background: {p['hover']}; border-color: {p['border_strong']}; }}
    QToolButton#gestureCard:pressed {{ background: {p['accent_soft']}; }}
    QToolButton#gestureCard[active="true"] {{ background: {p['accent_soft']}; border: 1px solid {p['accent']};
        color: {p['accent_text']}; }}
    QToolButton#gestureCard:disabled {{ color: {p['subtle']}; }}
    QPushButton#chip {{ background: transparent; border: 1px solid {p['border']}; border-radius: 7px;
        padding: 4px 10px; color: {p['muted']}; font-weight: 600; }}
    QPushButton#chip:hover {{ background: {p['hover']}; color: {p['text']}; border-color: {p['border_strong']}; }}
    QPushButton#chip:pressed {{ background: {p['accent_soft']}; }}
    QPushButton#danger {{ background: {p['error']}; border: 1px solid {p['error']}; color: white; padding: 7px 16px; }}
    QPushButton#danger:hover {{ background: {p['danger_hover']}; border-color: {p['danger_hover']}; }}
    QPushButton#danger:disabled {{ background: transparent; border-color: {p['border']}; color: {p['subtle']}; }}
    QWidget#inset, QLabel#inset {{ background: {p['inset']}; border: 1px solid {p['border']}; border-radius: 10px; }}

    QLabel#bigNumber {{ font-size: 24pt; font-weight: 700; }}
    QLabel#promptTitle {{ font-size: 15pt; font-weight: 700; }}
    QLabel#detected {{ font-size: 14pt; font-weight: 700; }}

    /* ---------- avisos flotantes ---------- */
    QFrame#toast {{ background: {p['card']}; border: 1px solid {p['border_strong']}; border-radius: 12px; }}
    QFrame#toast[kind="error"] {{ border-color: {p['error']}; }}
    QFrame#toast[kind="ok"] {{ border-color: {p['ok']}; }}
    QLabel#legend {{ color: {p['muted']}; font-size: 9pt; }}

    /* ---------- asistente IA ---------- */
    QLabel#userBubble {{ background: {p['accent_soft']}; border: 1px solid {p['accent']}; border-radius: 12px;
        padding: 8px 11px; }}
    QLabel#botBubble {{ background: {p['inset']}; border: 1px solid {p['border']}; border-radius: 12px;
        padding: 8px 11px; }}
    QLabel#errorBubble {{ background: {p['error_soft']}; border: 1px solid {p['error']}; border-radius: 12px;
        padding: 8px 11px; color: {p['error']}; }}
    QLabel#thinking {{ color: {p['muted']}; font-style: italic; padding: 2px 4px; }}
    QWidget#proposalCard {{ background: {p['card']}; border: 1px solid {p['border_strong']}; border-radius: 12px; }}
    QLabel#monoText {{ font-family: {MONO}; font-size: 9.5pt; }}

    /* ---------- grabación y reproducción de sesiones ---------- */
    QPushButton#recButton {{ background: transparent; border: 1px solid {p['border']}; color: {p['muted']};
        border-radius: 8px; padding: 0 10px; }}
    QPushButton#recButton:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QPushButton#recButton[recording="true"] {{ background: {p['error_soft']}; border-color: {p['error']};
        color: {p['error']}; }}
    QWidget#playerBar {{ background: {p['accent_soft']}; border: 1px solid {p['accent']}; border-radius: 10px; }}
    QLabel#playerBadge {{ color: {p['accent_text']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
    QPushButton#dashedCard {{ background: transparent; border: 1px dashed {p['border_strong']}; border-radius: 10px;
        color: {p['muted']}; padding: 10px; }}
    QPushButton#dashedCard:hover {{ background: {p['hover']}; color: {p['text']}; }}

    QTreeWidget, QListWidget {{ background: {p['inset']}; border: 1px solid {p['border']}; border-radius: 10px;
        padding: 4px; outline: 0; }}
    QTreeWidget::item, QListWidget::item {{ padding: 5px 6px; border-radius: 6px; }}
    QTreeWidget::item:hover, QListWidget::item:hover {{ background: {p['hover']}; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
    QTreeWidget::branch {{ background: transparent; }}
    QTreeWidget::branch:has-children:closed {{ image: url({right}); }}
    QTreeWidget::branch:has-children:open {{ image: url({down}); }}

    /* ---------- tablas ---------- */
    QTableWidget {{ background: {p['card']}; alternate-background-color: {p['inset']}; border: 1px solid {p['border']};
        border-radius: 10px; gridline-color: transparent; selection-background-color: {p['accent_soft']};
        selection-color: {p['text']}; outline: 0; }}
    QTableWidget::item {{ padding: 4px 10px; border: 0; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: {p['card']}; color: {p['muted']}; border: 0; border-bottom: 1px solid {p['border']};
        padding: 8px 10px; font-weight: 600; font-size: 9pt; }}
    QTableCornerButton::section {{ background: {p['card']}; border: 0; }}

    /* ---------- barras de desplazamiento ---------- */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {p['border_strong']}; border-radius: 3px; min-height: 28px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {p['subtle']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: transparent; }}
    QToolTip {{ background: {p['card']}; color: {p['text']}; border: 1px solid {p['border_strong']};
        border-radius: 6px; padding: 6px 8px; }}
    """
