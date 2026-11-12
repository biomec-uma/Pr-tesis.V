"""Encuadre de la vista 3D: la escala de la mano depende solo del alto de la vista."""

import unittest

from biomec.core.hand_model import frustum


class FrustumTest(unittest.TestCase):
    def test_vertical_extent_does_not_depend_on_width(self):
        narrow = frustum(60, 300, 400, 500)
        wide = frustum(60, 300, 1000, 500)
        self.assertEqual(narrow[2:4], wide[2:4])          # bottom y top iguales: misma escala vertical
        self.assertAlmostEqual(wide[1] / narrow[1], 1000 / 400)   # el ancho visible crece con la ventana

    def test_height_changes_scale(self):
        short = frustum(60, 300, 800, 300)
        tall = frustum(60, 300, 800, 600)
        self.assertEqual(short[3], tall[3])               # mismo campo de visión vertical…
        self.assertAlmostEqual(short[1] / tall[1], 2.0)   # …y el ancho visible se reparte según la proporción

    def test_near_far(self):
        left, right, bottom, top, near, far = frustum(60, 300, 800, 600)
        self.assertAlmostEqual(near, 0.3)
        self.assertAlmostEqual(far, 300000)
        self.assertLess(left, 0)
        self.assertLess(bottom, 0)


if __name__ == "__main__":
    unittest.main()
