"""Actualizaciones: qué versión publicada se elige, novedades del CHANGELOG y descarga con huella (sin red)."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from biomec.core import updates


def published(tag: str, installer: bool = True, side_sha: bool = False, digest: bool = True,
              draft: bool = False, prerelease: bool = False) -> dict:
    """Una versión tal como la devuelve la API de GitHub Releases."""
    version = tag.removeprefix("control-v")
    name = f"BIOMEC-Control-Setup-{version}.exe"
    assets = []
    if installer:
        asset = {"name": name, "browser_download_url": f"https://example.org/{name}", "size": 1234}
        if digest:
            asset["digest"] = "sha256:" + "AB" * 32
        assets.append(asset)
    if side_sha:
        assets.append({"name": name + ".sha256", "browser_download_url": f"https://example.org/{name}.sha256"})
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "body": "- Novedad\n",
            "html_url": f"https://example.org/{tag}", "published_at": "2026-11-12T10:00:00Z", "assets": assets}


class UpdatesTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("control-v0.3.1"), (0, 3, 1))
        self.assertEqual(updates.parse_version("v1.10.0"), (1, 10, 0))
        self.assertEqual(updates.parse_version("0.2.0"), (0, 2, 0))
        self.assertIsNone(updates.parse_version("firmware-v1"))
        self.assertIsNone(updates.parse_version("0.3"))

    def test_pick_latest(self):
        data = [published("control-v0.3.0"), published("control-v0.3.1"),
                published("control-v0.10.0", draft=True), published("control-v0.9.0", prerelease=True),
                published("v9.9.9"), published("control-v0.4.0", installer=False)]
        r = updates.pick_latest(data, "0.2.0")
        # 0.10 es un borrador, 0.9 una versión de prueba, v9.9.9 no es de la app y 0.4 no tiene instalador
        self.assertEqual(r.version, "0.3.1")
        self.assertEqual(r.tag, "control-v0.3.1")
        self.assertEqual(r.asset_name, "BIOMEC-Control-Setup-0.3.1.exe")
        self.assertEqual(r.sha256, "ab" * 32)
        self.assertEqual(r.published, "2026-11-12")
        self.assertEqual(r.notes, "- Novedad")
        self.assertIsNone(updates.pick_latest(data, "0.3.1"))  # ya tiene la última
        self.assertIsNone(updates.pick_latest(data, "1.0.0"))

    def test_versions_compare_as_numbers(self):
        r = updates.pick_latest([published("control-v0.9.0"), published("control-v0.10.0")], "0.3.0")
        self.assertEqual(r.version, "0.10.0")

    def test_sha256_from_side_file(self):
        r = updates.pick_latest([published("control-v0.3.1", side_sha=True, digest=False)], "0.3.0")
        self.assertIsNone(r.sha256)
        self.assertTrue(r.sha256_url.endswith(".exe.sha256"))

    def test_changelog_section(self):
        text = "# Novedades\n\n## 0.3.1\n\n- Uno\n- Dos\n\n## 0.3.0 · 2026-11-09\n\n- Antes\n"
        self.assertEqual(updates.changelog_section(text, "0.3.1"), "- Uno\n- Dos")
        self.assertEqual(updates.changelog_section(text, "0.3.0"), "- Antes")
        self.assertEqual(updates.changelog_section(text, "0.2.0"), "")

    def test_changelog_has_current_version(self):
        from biomec import APP_VERSION
        root = Path(__file__).resolve().parent.parent
        notes = updates.changelog_section((root / "CHANGELOG.md").read_text(encoding="utf-8"), APP_VERSION)
        self.assertTrue(notes, f"CHANGELOG.md no tiene el apartado '## {APP_VERSION}'")

    def test_download_checks_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "origen.exe")
            src.write_bytes(b"instalador de prueba " * 5000)
            good = hashlib.sha256(src.read_bytes()).hexdigest()

            def release(sha):
                return updates.Release("0.3.1", "control-v0.3.1", "", "", "", "BIOMEC-Control-Setup-0.3.1.exe",
                                       src.as_uri(), src.stat().st_size, sha, None)

            seen = []
            path = updates.download(release(good), Path(tmp, "bien"), lambda done, total: seen.append(done))
            self.assertEqual(path.read_bytes(), src.read_bytes())
            self.assertEqual(seen[-1], src.stat().st_size)

            other = Path(tmp, "mal")
            with self.assertRaises(updates.UpdateError):  # huella distinta: no se da por bueno
                updates.download(release("0" * 64), other)
            self.assertEqual(list(other.iterdir()), [])  # y no deja archivos a medias
            with self.assertRaises(updates.UpdateError):  # sin huella publicada no se instala
                updates.download(release(None), other)
            with self.assertRaises(updates.UpdateError):  # cancelada
                updates.download(release(good), other, cancelled=lambda: True)
            self.assertEqual(list(other.iterdir()), [])

    def test_clean_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            names = ["BIOMEC-Control-Setup-0.2.0.exe", "BIOMEC-Control-Setup-0.3.0.exe",
                     "BIOMEC-Control-Setup-0.3.1.exe", "BIOMEC-Control-Setup-0.4.0.exe.part", "otra-cosa.exe"]
            for name in names:
                (folder / name).write_bytes(b"x")
            updates.clean_downloads(folder, "0.3.0")
            # quedan la versión más nueva (aún no instalada) y lo que no es de la app
            self.assertEqual(sorted(p.name for p in folder.iterdir()),
                             ["BIOMEC-Control-Setup-0.3.1.exe", "otra-cosa.exe"])
            updates.clean_downloads(folder / "no-existe", "0.3.0")  # sin carpeta: no pasa nada

    def test_installer_runs_silently_and_reopens_the_app(self):
        cmd = updates.installer_command(Path("C:/x/setup.exe"), Path("C:/x/log.txt"))
        self.assertEqual(cmd[0], str(Path("C:/x/setup.exe")))
        for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/relanzar=1"):
            self.assertIn(flag, cmd)

    def test_no_updates_when_running_from_source(self):
        self.assertIsNone(updates.installed_dir())

    def test_installer_script_matches(self):
        """El instalador espera al mismo mutex que crea la app y produce el nombre que busca el actualizador."""
        root = Path(__file__).resolve().parent.parent
        iss = (root / "installer" / "biomec_control.iss").read_text(encoding="utf-8-sig")
        self.assertIn(f'#define AppMutex "{updates.APP_MUTEX}"', iss)
        self.assertIn("OutputBaseFilename=" + updates.INSTALLER.format(version="{#AppVersion}").removesuffix(".exe"),
                      iss)
        self.assertIn("{param:relanzar|0}", iss)


if __name__ == "__main__":
    unittest.main()
