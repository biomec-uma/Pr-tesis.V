"""Control por voz: tabla de órdenes e interpretación de lo que reconoce Vosk (sin micrófono ni modelo)."""

import unittest

from biomec.core.gestures import ABIERTO, CERRADO, GESTOS, Gesto
from biomec.core.voice import build_phrases, interpret, normalize


def vosk_result(text: str, conf: float = 1.0) -> dict:
    """Lo que devuelve Vosk con SetWords(True)."""
    return {"text": text, "result": [{"word": w, "conf": conf} for w in text.split()]}


class VoiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = build_phrases(GESTOS, [Gesto("Pinza fina", CERRADO, ABIERTO, ABIERTO, 90)],
                                  ["Gemelo digital", "Gráficas", "Entrenamiento"])

    def action(self, text: str, conf: float = 1.0):
        heard = interpret(vosk_result(text, conf), self.table)
        return heard.action.value if heard and heard.action else None

    def test_normalize(self):
        self.assertEqual(normalize("Índice  y MEDIO."), "indice y medio")
        self.assertEqual(normalize("Señalar"), "senalar")

    def test_commands(self):
        self.assertEqual(self.action("abre la mano"), "ABRIR")
        self.assertEqual(self.action("cierra la mano"), "CERRAR")
        self.assertEqual(self.action("señala"), "GESTO 6")
        self.assertEqual(self.action("gesto tres"), "GESTO 3")
        self.assertEqual(self.action("índice y medio"), "GESTO 2")
        self.assertEqual(self.action("cierra el índice"), "DEDO INDICE CERRAR")
        self.assertEqual(self.action("pinza fina"), "POSTURA C A A 90")    # postura personalizada
        self.assertEqual(self.action("pinza"), "POSTURA C A A 90")
        self.assertEqual(self.action("gráficas"), "Gráficas")              # cambiar de pestaña

    def test_every_gesture_has_a_phrase(self):
        values = {a.value for _spoken, a in self.table.values()}
        for i in range(1, len(GESTOS) + 1):
            self.assertIn(f"GESTO {i}", values)

    def test_conversation_is_ignored(self):
        self.assertIsNone(self.action("gesto para la"))            # "esto es para la prueba"
        self.assertIsNone(self.action("gesto mano plana"))         # palabras sueltas pegadas
        self.assertIsNone(self.action("[unk] abre la mano"))       # la frase no es solo la orden
        self.assertIsNone(self.action("abre la mano", conf=0.5))   # poca confianza
        self.assertIsNone(interpret(vosk_result(""), self.table))
        self.assertIsNone(interpret(vosk_result("[unk] [unk]"), self.table))

    def test_stop_is_easy(self):
        self.assertEqual(self.action("para"), "PARAR")
        self.assertEqual(self.action("para para"), "PARAR")
        self.assertEqual(self.action("alto"), "PARAR")
        self.assertEqual(self.action("[unk] para"), "PARAR")       # entre ruido también
        self.assertEqual(self.action("para", conf=0.5), "PARAR")   # con menos confianza que el resto
        self.assertIsNone(self.action("para", conf=0.2))


if __name__ == "__main__":
    unittest.main()
