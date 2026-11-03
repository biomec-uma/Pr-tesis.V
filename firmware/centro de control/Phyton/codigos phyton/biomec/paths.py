"""Rutas de recursos, válidas tanto en desarrollo como en el .exe (PyInstaller)."""

import os
import sys
from pathlib import Path

from . import APP_NAME

if getattr(sys, "frozen", False):
    # Dentro del ejecutable, PyInstaller descomprime los datos en _MEIPASS.
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = BASE_DIR / "assets"
CONFIG_DIR = BASE_DIR / "config"


def asset(name: str) -> Path:
    return ASSETS_DIR / name


def config_file(name: str) -> Path:
    return CONFIG_DIR / name


def user_data_dir() -> Path:
    """Carpeta para registros y ajustes del usuario (%APPDATA%/BIOMEC Control)."""
    root = Path(os.environ.get("APPDATA", Path.home()))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path
