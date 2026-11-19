"""C6 del móvil (firmware/puente_movil): página, firmware y simulador coherentes con la app.

Si alguien cambia un gesto o un comando y se olvida de la página del móvil
(o edita la página y no regenera pagina_web.h), estas pruebas dicen qué falta.
"""

import http.client
import importlib.util
import json
import re
import threading
import unittest
from pathlib import Path

from biomec.core.commands import CommandCatalog, CommandError
from biomec.core.gestures import GESTOS
from biomec.paths import config_file

ROOT = Path(__file__).resolve().parent.parent


def carpeta_movil() -> Path | None:
    """firmware/puente_movil junto a la app o, en el repositorio del equipo, maestro/movil."""
    for path in (ROOT / "firmware" / "puente_movil", ROOT.parent.parent / "maestro" / "movil"):
        if (path / "platformio.ini").is_file():
            return path
    return None


MOVIL = carpeta_movil()
SIN_MOVIL = "No está el firmware de la C6 del móvil (firmware/puente_movil) junto a esta copia de la app"
PAGINA = (MOVIL / "web" / "index.html").read_text(encoding="utf-8") if MOVIL else ""
FIRMWARE = (MOVIL / "src" / "puente_movil.cpp").read_text(encoding="utf-8") if MOVIL else ""


def cargar(nombre: str, archivo: Path):
    spec = importlib.util.spec_from_file_location(nombre, archivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def comandos_pagina() -> list[str]:
    return re.findall(r'data-cmd="([^"]+)"', PAGINA)


def permitidos() -> set[str]:
    bloque = FIRMWARE.split("PERMITIDOS[] =", 1)[1].split("};", 1)[0]
    return set(re.findall(r'"([A-Z]+)"', bloque))


@unittest.skipIf(MOVIL is None, SIN_MOVIL)
class PaginaMovilTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = CommandCatalog(config_file("commands.json"))

    def test_cabecera_al_dia(self):
        """include/pagina_web.h es la copia exacta de web/index.html."""
        incrustar = cargar("incrustar_web", MOVIL / "incrustar_web.py")
        cabecera = (MOVIL / "include" / "pagina_web.h").read_text(encoding="utf-8")
        self.assertEqual(incrustar.generar(PAGINA), cabecera,
                         "pagina_web.h no coincide con web/index.html: ejecuta python incrustar_web.py "
                         "en firmware/puente_movil (o compila con PlatformIO, que lo hace solo)")

    def test_comandos_de_la_pagina(self):
        """Cada botón manda un comando de la mano que existe en el catálogo y que la C6 deja pasar."""
        comandos = comandos_pagina() + ["PULGAR 0", "PULGAR 180"]   # extremos del deslizador del pulgar
        self.assertGreater(len(comandos), 15)
        for linea in comandos:
            with self.subTest(linea=linea):
                try:
                    cmd, _ = self.cat.build(linea)
                except CommandError as error:
                    self.fail(f"{linea!r} no es válido según commands.json: {error}")
                self.assertEqual(cmd.target, "mano")
                self.assertIn(cmd.name, permitidos(), f"La C6 del móvil rechazaría {linea!r}")

    def test_permitidos_existen(self):
        mano = {c.name for c in self.cat if c.target == "mano"}
        self.assertLessEqual(permitidos(), mano, "PERMITIDOS[] tiene comandos que la mano no conoce")
        self.assertNotIn("STREAM", permitidos())   # cambiaría la telemetría de la app del PC

    def test_gestos(self):
        """Los 8 botones de gesto tienen los nombres y el orden de la app y la mano."""
        botones = re.findall(r'data-cmd="GESTO (\d+)"><b>\1</b><span class="nombre">([^<]+)</span>', PAGINA)
        self.assertEqual([int(n) for n, _ in botones], list(range(1, len(GESTOS) + 1)))
        self.assertEqual([nombre for _, nombre in botones], [g.nombre for g in GESTOS])

    def test_vista_previa_gestos(self):
        """La mano de mentira de la vista previa pone cada dedo y el pulgar como la mano real."""
        bloque = PAGINA.split("var VISTA_GESTOS = [", 1)[1].split("];", 1)[0]
        filas = re.findall(r'\["(\w+)", "(\w+)", "(\w+)", (\d+)\]', bloque)
        self.assertEqual([(i, m, a, int(p)) for i, m, a, p in filas],
                         [(g.indice, g.medio, g.anular, g.pulgar) for g in GESTOS])

    def test_sin_recursos_externos(self):
        """La red de la C6 no tiene internet: nada de CDN, fuentes ni imágenes de fuera."""
        externos = [u for u in re.findall(r'https?://[^\s"\'<)]+', PAGINA) if not u.startswith("http://192.168.4.1")]
        self.assertEqual(externos, [])
        self.assertNotRegex(PAGINA, r'<(link|script|img)[^>]+(href|src)=')

    def test_protocolo_identico(self):
        puente = ROOT / "firmware" / "puente_pc" / "include" / "biomec_protocol.h"
        if not puente.is_file():
            self.skipTest("puente_pc no está en firmware/ (repositorio del equipo)")
        self.assertEqual((MOVIL / "include" / "biomec_protocol.h").read_bytes(), puente.read_bytes(),
                         "biomec_protocol.h tiene que ser idéntico en todos los firmware")


@unittest.skipIf(MOVIL is None, SIN_MOVIL)
class SimuladorMovilTest(unittest.TestCase):
    """simular_movil.py responde como la C6 (lo que usa la página)."""

    @classmethod
    def setUpClass(cls):
        sim = cargar("simular_movil", MOVIL / "simular_movil.py")
        cls.c6 = sim.C6Simulada()
        cls.parar = threading.Event()
        sim.arrancar_mano(cls.c6, cls.parar)
        cls.servidor = sim.crear_servidor(cls.c6, "127.0.0.1", 0)
        cls.puerto = cls.servidor.server_address[1]
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.parar.set()
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def pedir(self, metodo: str, ruta: str, cuerpo: str | None = None):
        con = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        cabeceras = {"Content-Type": "application/x-www-form-urlencoded"} if cuerpo is not None else {}
        con.request(metodo, ruta, body=cuerpo, headers=cabeceras)
        r = con.getresponse()
        datos = r.read()
        con.close()
        return r, datos

    def orden(self, linea: str):
        from urllib.parse import quote
        r, datos = self.pedir("POST", "/cmd", "c=" + quote(linea))
        return r.status, json.loads(datos)

    def test_pagina(self):
        r, datos = self.pedir("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn("Mano BIOMEC", datos.decode("utf-8"))

    def test_gesto_y_estado(self):
        self.assertEqual(self.orden("gesto 3"), (200, {"ok": True}))   # en minúsculas también vale
        self.c6.ultimo_estado_pedido = 0                                # que /estado pregunte ya
        r, datos = self.pedir("GET", "/estado")
        d = json.loads(datos)
        self.assertTrue(d["mano"])
        self.assertEqual((d["estado"]["modo"], d["estado"]["gesto"]), ("MANUAL", 3))
        textos = [linea["t"] for linea in d["registro"]]
        self.assertIn("→ GESTO 3", textos)
        self.assertIn("ACK GESTO 3 Índice y anular", textos)
        self.assertEqual(d["reinicio"]["motivo"], "encendido")

    def test_rechaza_lo_que_no_es_de_mover(self):
        for linea, motivo in (("@INFO", "Carácter no permitido"), ("STREAM 1", "no se puede usar STREAM"),
                              ("", "Orden vacía"), ("GESTO 1; PARAR", "Carácter no permitido")):
            with self.subTest(linea=linea):
                codigo, d = self.orden(linea)
                self.assertEqual(codigo, 400)
                self.assertIn(motivo, d["error"])

    def test_portal_cautivo(self):
        r, _ = self.pedir("GET", "/hotspot-detect.html")
        self.assertEqual(r.status, 302)


if __name__ == "__main__":
    unittest.main()
