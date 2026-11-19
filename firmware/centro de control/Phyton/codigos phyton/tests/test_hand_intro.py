"""Presentación animada del gemelo (core/hand_intro.py): el guion, sin tarjeta gráfica."""

import unittest

import numpy as np

from biomec.core.hand_intro import (
    CALLOUTS, DURATION, FINAL_CAMERA, GESTURES, IntroScript, feature_edges,
)
from biomec.core.hand_model import DEDOS, HandModel
from biomec.paths import ASSETS_DIR, config_file


def cubo() -> np.ndarray:
    """Cubo de 1 mm hecho con 12 triángulos (2 por cara), sin vértices compartidos, como un STL."""
    v = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
    caras = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tri = []
    for a, b, c, d in caras:
        tri += [(v[a], v[b], v[c]), (v[a], v[c], v[d])]
    return np.array(tri)


class AristasTest(unittest.TestCase):
    def test_cubo(self):
        seg = feature_edges(cubo())
        self.assertEqual(len(seg), 12)                       # las diagonales de las caras no salen
        ys = seg[:, :, 1].min(axis=1)
        self.assertTrue(np.all(np.diff(ys) >= 0))            # de abajo arriba, para dibujarlas crecer

    def test_vacio(self):
        self.assertEqual(feature_edges(np.zeros((0, 3, 3))).shape, (0, 2, 3))


class GuionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = HandModel.load(config_file("mano3d.json"), ASSETS_DIR)
        cls.script = IntroScript(cls.model)

    def test_empieza_en_lineas(self):
        f = self.script.frame(0.0)
        self.assertLess(f.cut, self.script.y_min)            # nada sólido todavía
        self.assertEqual(f.phase, "01 · Diseño")
        for d in DEDOS:
            self.assertFalse(f.visible[f"{d}/Proximal"])     # los dedos aún no han llegado
            self.assertFalse(np.allclose(f.offsets[f"{d}/Proximal"], np.eye(4)))

    def test_termina_como_el_gemelo(self):
        """Al final todo queda como la vista normal: así el gemelo sigue sin saltos."""
        from biomec.pages.hand3d import CAMERAS
        f = self.script.frame(DURATION)
        self.assertTrue(f.done)
        for name, m in f.offsets.items():
            self.assertTrue(np.allclose(m, np.eye(4)), name)
        self.assertGreater(f.cut, self.script.y_max)
        self.assertEqual((f.wire_alpha, f.glow, f.title_alpha, f.callouts), (0.0, 0.0, 0.0, []))
        self.assertEqual(f.flex, {d: 0.0 for d in DEDOS})
        self.assertEqual(f.thumb, 10.0)
        self.assertEqual(f.camera, FINAL_CAMERA)
        self.assertEqual(FINAL_CAMERA[:2], CAMERAS["¾"])

    def test_barrido_avanza(self):
        cortes = [self.script.frame(t).cut for t in np.linspace(0, DURATION, 200)]
        self.assertTrue(np.all(np.diff(cortes) >= 0))

    def test_etiquetas(self):
        vistas = []
        for t in np.linspace(0, DURATION, 400):
            for i, _grow, _alpha in self.script.frame(t).callouts:
                if i not in vistas:
                    vistas.append(i)
        self.assertEqual(vistas, list(range(len(CALLOUTS))))   # todas, en orden
        for c in CALLOUTS:
            part, punto = self.script.anchor(c)
            self.assertIn(part, self.model.parts)
            self.assertEqual(punto.shape, (3,))

    def test_gestos(self):
        inicio, fin, flexion, pulgar = GESTURES[0]               # el puño
        f = self.script.frame(fin)
        self.assertEqual([round(f.flex[d], 3) for d in DEDOS], list(flexion))
        self.assertEqual(round(f.thumb), pulgar)
        mitad = self.script.frame((inicio + fin) / 2)
        self.assertTrue(all(mitad.moving[d] == 1.0 for d in DEDOS))   # en azul mientras se mueven

    def test_dibujo_importa(self):
        """El módulo que pinta se puede importar (registra su sombreador) sin abrir ninguna ventana."""
        import biomec.pages.hand_intro as dibujo
        self.assertEqual(dibujo.SHADER, "biomec_intro")


if __name__ == "__main__":
    unittest.main()
