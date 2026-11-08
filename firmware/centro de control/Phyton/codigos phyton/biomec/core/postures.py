"""Posturas personalizadas: el usuario las diseña en la app (editor de posturas).

Se guardan en %APPDATA%/BIOMEC Control/posturas.json y se envían con el
comando POSTURA, que mueve los tres dedos a la vez. Añadir una postura nueva
no requiere tocar el firmware ni recompilar nada.

    {"posturas": [{"nombre": "Pinza fina", "indice": "cerrado", "medio": "abierto",
                   "anular": "abierto", "pulgar": 90}, ...]}
"""

from __future__ import annotations

import json
from pathlib import Path

from .gestures import ABIERTO, CERRADO, DESCONOCIDO, GESTOS, Gesto

LETTER = {ABIERTO: "A", CERRADO: "C", DESCONOCIDO: "-"}
FROM_LETTER = {v: k for k, v in LETTER.items()}
STATES = (ABIERTO, CERRADO, DESCONOCIDO)
MAX_NAME = 28


def posture_spec(g: Gesto) -> str:
    """'C A C 90': lo mismo que devuelve la mano en 'ACK POSTURA C A C 90'."""
    return f"{LETTER[g.indice]} {LETTER[g.medio]} {LETTER[g.anular]} {int(g.pulgar)}"


def posture_command(g: Gesto) -> str:
    return f"POSTURA {posture_spec(g)}"


def spec_from_ack(text: str) -> str | None:
    """'POSTURA C A C 90' (texto de un ACK) -> 'C A C 90'."""
    parts = text.split()
    if len(parts) == 5 and parts[0].upper() == "POSTURA":
        return " ".join(p.upper() for p in parts[1:])
    return None


def matching_gesture(g: Gesto) -> int:
    """Número (1..N) del gesto de fábrica idéntico a la postura, o 0."""
    for i, G in enumerate(GESTOS, start=1):
        if (G.indice, G.medio, G.anular, G.pulgar) == (g.indice, g.medio, g.anular, g.pulgar):
            return i
    return 0


class PostureStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.items: list[Gesto] = []
        self.error = ""
        self.load()

    def load(self) -> None:
        self.items, self.error = [], ""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("posturas", []):
                states = [item.get(k, ABIERTO) for k in ("indice", "medio", "anular")]
                states = [s if s in STATES else ABIERTO for s in states]
                pulgar = int(min(max(int(item.get("pulgar", 10)), 0), 180))
                name = str(item.get("nombre", "Postura")).strip()[:MAX_NAME] or "Postura"
                self.items.append(Gesto(name, *states, pulgar))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            self.error = f"No se pudieron leer las posturas ({self.path.name}): {error}"

    def save(self) -> None:
        data = {"posturas": [{"nombre": g.nombre, "indice": g.indice, "medio": g.medio, "anular": g.anular,
                              "pulgar": g.pulgar} for g in self.items]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def unique_name(self, base: str, skip: int = -1) -> str:
        names = {g.nombre for i, g in enumerate(self.items) if i != skip}
        if base not in names:
            return base
        n = 2
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    def add(self, g: Gesto) -> None:
        self.items.append(g)
        self.save()

    def replace(self, index: int, g: Gesto) -> None:
        self.items[index] = g
        self.save()

    def remove(self, index: int) -> None:
        del self.items[index]
        self.save()

    def move(self, index: int, delta: int) -> None:
        j = index + delta
        if 0 <= j < len(self.items):
            self.items[index], self.items[j] = self.items[j], self.items[index]
            self.save()

    def find_spec(self, spec: str) -> int:
        """Índice de la primera postura con esa especificación ('C A C 90'), o -1."""
        for i, g in enumerate(self.items):
            if posture_spec(g) == spec:
                return i
        return -1
