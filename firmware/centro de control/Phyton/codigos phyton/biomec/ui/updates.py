"""Actualizaciones en la interfaz: aviso en la cabecera, ventana de novedades y descarga.

    arranque ──(4 s)──► hilo: core.updates.check ──► found ──► botón «Actualizar a X» + aviso
    «Actualizar y reiniciar» ──► hilo: descarga + huella SHA-256 ──► instalador en silencio ──► la app
    se cierra; el instalador espera a que termine, la actualiza y la vuelve a abrir

Solo se busca en la app instalada con el instalador: desde el código o desde dist/ no se actualiza.
"""

import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser

from .. import APP_NAME, APP_VERSION, ORG_NAME
from ..core import updates
from .dialogs import _Base
from .theme import PALETTES


class UpdateController(QObject):
    found = Signal(object)           # core.updates.Release
    up_to_date = Signal()
    failed = Signal(str)
    progress = Signal(int, int)      # bytes descargados, total
    downloaded = Signal(str)         # ruta del instalador ya comprobado
    download_failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.release: updates.Release | None = None
        self.installed = updates.installed_dir() is not None
        self.folder = Path(tempfile.gettempdir()) / APP_NAME / "actualizaciones"
        self._cancel = False
        if self.installed:
            updates.clean_downloads(self.folder, APP_VERSION)  # el instalador de la última actualización ya no hace falta

    @property
    def auto(self) -> bool:
        """Buscar versiones nuevas al arrancar (se puede quitar en «Acerca de»)."""
        return self.settings.value("updates/auto", True, type=bool)

    @auto.setter
    def auto(self, value: bool) -> None:
        self.settings.setValue("updates/auto", bool(value))

    def check(self) -> None:
        def work():
            try:
                release = updates.check(APP_VERSION)
            except updates.UpdateError as error:
                self.failed.emit(str(error))
                return
            except Exception as error:  # noqa: BLE001  (una comprobación nunca debe tumbar la app)
                self.failed.emit(f"Error inesperado: {error}")
                return
            if release is None:
                self.up_to_date.emit()
            else:
                self.release = release
                self.found.emit(release)

        threading.Thread(target=work, name="actualizaciones", daemon=True).start()

    def download(self) -> None:
        release = self.release
        self._cancel = False

        def work():
            try:
                path = updates.download(release, self.folder, lambda d, t: self.progress.emit(d, t),
                                        lambda: self._cancel)
                self.downloaded.emit(str(path))
            except updates.UpdateError as error:
                self.download_failed.emit(str(error))
            except Exception as error:  # noqa: BLE001
                self.download_failed.emit(f"Error inesperado: {error}")

        threading.Thread(target=work, name="descarga-actualizacion", daemon=True).start()

    def cancel(self) -> None:
        self._cancel = True

    def install(self, path: str) -> None:
        updates.launch_installer(Path(path), self.folder.parent / "actualizacion.log")


def _date(iso: str) -> str:
    """'2026-11-12' -> '12/11/2026'."""
    parts = iso.split("-")
    return "/".join(reversed(parts)) if len(parts) == 3 else iso


class UpdateDialog(_Base):
    """Qué trae la versión nueva y el botón para instalarla."""

    def __init__(self, parent, release: updates.Release, real_hand: bool):
        super().__init__(parent, f"Actualizar {APP_NAME}")
        self.setFixedWidth(560)
        theme = getattr(getattr(parent, "ctx", None), "theme", "dark")
        title = QLabel(f"Versión {release.version} disponible")
        title.setObjectName("pageTitle")
        self.lay.addWidget(title)
        meta = [f"Tienes la {APP_VERSION}"]
        if release.published:
            meta.append(f"publicada el {_date(release.published)}")
        if release.size:
            meta.append(f"{release.size / 1e6:.0f} MB")
        sub = QLabel("  ·  ".join(meta))
        sub.setObjectName("muted")
        self.lay.addWidget(sub)

        cap = QLabel("NOVEDADES")
        cap.setObjectName("caption")
        self.lay.addSpacing(4)
        self.lay.addWidget(cap)
        notes = QTextBrowser()
        notes.setObjectName("updateNotes")
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "Esta versión no trae notas.")
        notes.setMinimumHeight(170)
        notes.setMaximumHeight(300)
        self.lay.addWidget(notes)

        how = QLabel("Se descarga de GitHub, se comprueba que llega intacta y se instala sola: la app se cierra "
                     "y vuelve a abrirse en unos segundos. Tus ajustes, posturas, sesiones y modelos se conservan.")
        how.setObjectName("muted")
        how.setWordWrap(True)
        self.lay.addWidget(how)
        if real_hand:
            warn = QLabel("La mano real está conectada: antes de actualizar se enviará PARAR y se desconectará.")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {PALETTES[theme]['warn']}; font-weight: 600;")
            self.lay.addWidget(warn)

        row = QHBoxLayout()
        page = QPushButton("Ver en GitHub")
        page.setCursor(Qt.PointingHandCursor)
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release.page_url)))
        row.addWidget(page)
        row.addStretch(1)
        later = QPushButton("Más tarde")
        later.clicked.connect(self.reject)
        row.addWidget(later)
        go = QPushButton("Actualizar y reiniciar")
        go.setObjectName("primary")
        go.setDefault(True)
        go.clicked.connect(self.accept)
        row.addWidget(go)
        self.lay.addSpacing(6)
        self.lay.addLayout(row)
