"""Paletas y hoja de estilos. Para cambiar colores solo hay que tocar PALETTES."""

PALETTES = {
    "dark": {
        "bg": "#070b12", "card": "#111a2b", "sidebar": "#0b1220",
        "title": "#f5f8ff", "subtitle": "#83aaff", "section": "#8fb2ff",
        "text": "#e8eefb", "muted": "#a8bad7",
        "widget_bg": "#080f1e", "border": "#2a3b5c",
        "header_bg": "#17243b", "header_text": "#aec6f5",
        "button_bg": "#1a2942", "button_hover": "#243a5d", "button_border": "#314b73", "button_text": "#eaf1ff",
        "primary": "#2463d2", "primary_border": "#3980ff", "primary_hover": "#3477ed",
        "disabled_bg": "#151d2b", "disabled_border": "#222d40", "disabled_text": "#65738b",
        "selection": "#2864d7",
        "ok": "#3ecf8e", "warn": "#f2b84b", "error": "#ff6b6b", "tx": "#7fb0ff",
        "plot_bg": "#080f1e", "plot_axis": "#a8bad7",
    },
    "light": {
        "bg": "#eaf2ff", "card": "#ffffff", "sidebar": "#dde9fc",
        "title": "#0f1d36", "subtitle": "#355faa", "section": "#275bbd",
        "text": "#1c2a3d", "muted": "#40587f",
        "widget_bg": "#f6faff", "border": "#cfe1ff",
        "header_bg": "#edf4ff", "header_text": "#2e5aa6",
        "button_bg": "#edf5ff", "button_hover": "#dfeeff", "button_border": "#bfd6ff", "button_text": "#16345d",
        "primary": "#1f5fd2", "primary_border": "#3477ed", "primary_hover": "#174db3",
        "disabled_bg": "#edf2fb", "disabled_border": "#d5def4", "disabled_text": "#7284a4",
        "selection": "#8fb9ff",
        "ok": "#14905a", "warn": "#a86b00", "error": "#c62828", "tx": "#1f5fd2",
        "plot_bg": "#ffffff", "plot_axis": "#40587f",
    },
}

# Colores de las curvas de las gráficas (se reparten en orden).
PLOT_COLORS = ["#3b82f6", "#f97316", "#10b981", "#e11d48", "#a855f7", "#eab308", "#06b6d4", "#84cc16"]


def stylesheet(theme: str) -> str:
    p = PALETTES[theme]
    return f"""
        QMainWindow, QWidget {{ background: {p['bg']}; color: {p['text']}; font-family: 'Segoe UI'; font-size: 10pt; }}
        QWidget#card {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 12px; }}
        QLabel, QCheckBox, QWidget#transparent {{ background: transparent; }}
        QWidget#sidebar {{ background: {p['sidebar']}; border-right: 1px solid {p['border']}; }}
        QLabel#title {{ color: {p['title']}; font-size: 17pt; font-weight: 700; letter-spacing: 2px; background: transparent; }}
        QLabel#subtitle {{ color: {p['subtitle']}; font-size: 8pt; font-weight: 600; letter-spacing: 2px; background: transparent; }}
        QLabel#section {{ color: {p['section']}; font-weight: 700; letter-spacing: 1px; }}
        QLabel#muted {{ color: {p['muted']}; }}
        QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QTableWidget, QSpinBox {{ background: {p['widget_bg']}; border: 1px solid {p['border']}; border-radius: 7px; padding: 6px; color: {p['text']}; selection-background-color: {p['selection']}; }}
        QHeaderView::section {{ background: {p['header_bg']}; color: {p['header_text']}; border: 0; padding: 7px; font-weight: 600; }}
        QTableWidget {{ gridline-color: {p['border']}; padding: 2px; }}
        QPushButton {{ background: {p['button_bg']}; border: 1px solid {p['button_border']}; border-radius: 7px; padding: 8px 14px; color: {p['button_text']}; font-weight: 600; }}
        QPushButton:hover {{ background: {p['button_hover']}; }}
        QPushButton:disabled {{ color: {p['disabled_text']}; background: {p['disabled_bg']}; border-color: {p['disabled_border']}; }}
        QPushButton#primary {{ background: {p['primary']}; border-color: {p['primary_border']}; color: white; }}
        QPushButton#primary:hover {{ background: {p['primary_hover']}; }}
        QPushButton#primary:disabled {{ color: {p['disabled_text']}; background: {p['disabled_bg']}; border-color: {p['disabled_border']}; }}
        QPushButton#nav {{ text-align: left; padding: 11px 16px; border: 0; border-radius: 8px; background: transparent; font-size: 10.5pt; }}
        QPushButton#nav:hover {{ background: {p['button_hover']}; }}
        QPushButton#nav:checked {{ background: {p['primary']}; color: white; }}
        QStatusBar {{ background: {p['sidebar']}; color: {p['muted']}; }}
        QDockWidget {{ color: {p['section']}; font-weight: 700; }}
        QDockWidget::title {{ background: {p['header_bg']}; padding: 6px; }}
    """
