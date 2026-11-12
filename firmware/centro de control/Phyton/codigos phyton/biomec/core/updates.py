"""Actualizaciones de la app: versiones publicadas en GitHub Releases.

    Hugo:   release.ps1 ──► GitHub Releases (etiqueta control-vX.Y.Z + instalador + .sha256)
    equipo: la app instalada pregunta a GitHub al arrancar ──► avisa ──► descarga el instalador,
            comprueba su huella SHA-256 y lo ejecuta en silencio ──► la app se cierra y se reabre

El repositorio del equipo es público: no hace falta ninguna clave ni para consultar ni para
descargar. Se usa la API pública de GitHub (60 consultas por hora y por IP: de sobra).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = "biomec-uma/Pr-tesis.V"
TAG_PREFIX = "control-v"           # el repositorio tiene más cosas: solo cuentan las etiquetas de la app
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
INSTALLER = "BIOMEC-Control-Setup-{version}.exe"
APP_MUTEX = "BiomecControlApp"     # el instalador espera a que la app lo suelte (installer/biomec_control.iss)
USER_AGENT = "BIOMEC-Control"


class UpdateError(Exception):
    """Fallo que se le enseña al usuario tal cual."""


def parse_version(text: str) -> tuple[int, int, int] | None:
    """'control-v0.3.1', 'v0.3.1' o '0.3.1' -> (0, 3, 1); None si no es una versión."""
    m = re.fullmatch(r"(?:control-)?v?(\d+)\.(\d+)\.(\d+)", text.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


@dataclass(frozen=True)
class Release:
    version: str            # "0.3.1"
    tag: str                # "control-v0.3.1"
    notes: str              # novedades en markdown (el apartado de CHANGELOG.md)
    page_url: str           # la versión en GitHub
    published: str          # "2026-11-12"
    asset_name: str         # "BIOMEC-Control-Setup-0.3.1.exe"
    asset_url: str
    size: int               # bytes
    sha256: str | None      # huella que calcula GitHub ("digest"); si falta, se usa el .sha256 publicado
    sha256_url: str | None


def pick_latest(releases: list[dict], current: str) -> Release | None:
    """La versión publicada más nueva que la actual, sin borradores ni versiones de prueba."""
    now = parse_version(current) or (0, 0, 0)
    best: tuple[tuple[int, int, int], Release] | None = None
    for r in releases:
        tag = r.get("tag_name") or ""
        if r.get("draft") or r.get("prerelease") or not tag.startswith(TAG_PREFIX):
            continue
        version = parse_version(tag)
        if version is None or version <= now or (best is not None and version <= best[0]):
            continue
        text = ".".join(map(str, version))
        assets = {a.get("name"): a for a in r.get("assets") or []}
        setup = assets.get(INSTALLER.format(version=text))
        if setup is None or not setup.get("browser_download_url"):
            continue  # publicada sin instalador (o todavía subiéndose)
        digest = setup.get("digest") or ""
        side = assets.get(setup["name"] + ".sha256")
        best = (version, Release(
            version=text, tag=tag, notes=(r.get("body") or "").strip(),
            page_url=r.get("html_url") or RELEASES_PAGE, published=(r.get("published_at") or "")[:10],
            asset_name=setup["name"], asset_url=setup["browser_download_url"], size=int(setup.get("size") or 0),
            sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
            sha256_url=side.get("browser_download_url") if side else None))
    return best[1] if best else None


def _open(url: str, timeout: float, accept: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_releases(timeout: float = 10) -> list[dict]:
    """Las versiones publicadas en GitHub (BIOMEC_UPDATES_URL cambia la dirección, para probar en local)."""
    url = os.environ.get("BIOMEC_UPDATES_URL") or RELEASES_URL
    try:
        with _open(url, timeout, "application/vnd.github+json") as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            raise UpdateError("GitHub ha limitado las consultas: vuelve a probar dentro de un rato.") from error
        raise UpdateError(f"GitHub ha respondido con un error ({error.code}).") from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise UpdateError("No se ha podido conectar con GitHub. ¿Hay conexión a internet?") from error
    if not isinstance(data, list):
        raise UpdateError("GitHub ha devuelto una respuesta inesperada.")
    return data


def check(current: str, timeout: float = 10) -> Release | None:
    """La versión nueva que hay publicada, o None si ya se tiene la última."""
    return pick_latest(fetch_releases(timeout), current)


def _published_sha256(release: Release, timeout: float) -> str | None:
    """La huella del archivo .sha256 que release.ps1 publica junto al instalador."""
    if not release.sha256_url:
        return None
    try:
        with _open(release.sha256_url, timeout, "application/octet-stream") as resp:
            text = resp.read(4096).decode("ascii", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise UpdateError(f"No se ha podido leer la huella del instalador: {error}") from error
    m = re.match(r"\s*([0-9a-fA-F]{64})\b", text)
    return m[1].lower() if m else None


def download(release: Release, folder: Path, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None, timeout: float = 30) -> Path:
    """Descarga el instalador y comprueba su huella SHA-256 antes de darlo por bueno."""
    expected = release.sha256 or _published_sha256(release, timeout)
    if not expected:
        raise UpdateError("La versión publicada no trae su huella SHA-256: por seguridad no se instala.")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / release.asset_name
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    done = 0
    try:
        with _open(release.asset_url, timeout, "application/octet-stream") as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0) or release.size
            while True:
                if cancelled and cancelled():
                    raise UpdateError("Descarga cancelada.")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        part.unlink(missing_ok=True)
        raise UpdateError(f"La descarga ha fallado: {error}") from error
    if digest.hexdigest() != expected.lower():
        part.unlink(missing_ok=True)
        raise UpdateError("El archivo descargado no coincide con la huella publicada: no se instala.")
    part.replace(target)
    return target


# ============================================================ instalar
def installed_dir() -> Path | None:
    """Carpeta de la app si se instaló con el instalador (tiene el desinstalador al lado).
    None al ejecutar desde el código o desde dist/: ahí no se actualiza sola."""
    if not getattr(sys, "frozen", False):
        return None
    folder = Path(sys.executable).resolve().parent
    return folder if any(folder.glob("unins*.exe")) else None


def installer_command(installer: Path, log: Path) -> list[str]:
    """Instalación silenciosa: el instalador espera a que se cierre la app, la actualiza y la reabre."""
    return [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/relanzar=1", f"/LOG={log}"]


def clean_downloads(folder: Path, current: str) -> None:
    """Borra los instaladores ya usados (de esta versión o anteriores) y las descargas a medias,
    para que no se acumulen ~75 MB por actualización en la carpeta temporal."""
    if not folder.is_dir():
        return
    now = parse_version(current) or (0, 0, 0)
    for f in folder.iterdir():
        m = re.fullmatch(r"BIOMEC-Control-Setup-(\d+\.\d+\.\d+)\.exe(\.part)?", f.name)
        if m and (m[2] or (parse_version(m[1]) or now) <= now):
            try:
                f.unlink()
            except OSError:
                pass  # en uso o sin permiso: ya se borrará la próxima vez


def launch_installer(installer: Path, log: Path) -> None:
    """Lanza el instalador por su cuenta (sigue vivo cuando la app se cierra)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen(installer_command(installer, log), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ============================================================ novedades
def changelog_section(text: str, version: str) -> str:
    """El apartado '## <versión>' de CHANGELOG.md, sin el título: las novedades de esa versión."""
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            words = line[3:].split()
            inside = bool(words) and words[0] == version
            continue
        if inside:
            lines.append(line)
    return "\n".join(lines).strip()


if __name__ == "__main__":
    # release.ps1:  python -m biomec.core.updates notas <versión> <archivo de salida>
    if len(sys.argv) == 4 and sys.argv[1] == "notas":
        root = Path(__file__).resolve().parents[2]
        notes = changelog_section((root / "CHANGELOG.md").read_text(encoding="utf-8"), sys.argv[2])
        Path(sys.argv[3]).write_text(notes + "\n", encoding="utf-8")
        sys.exit(0 if notes else 1)
    print("uso: python -m biomec.core.updates notas <versión> <archivo>")
    sys.exit(2)
