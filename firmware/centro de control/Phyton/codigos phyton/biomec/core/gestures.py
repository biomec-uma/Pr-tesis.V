"""Tabla de gestos de la mano (la misma que GESTOS[] en firmware/mano/mano.ino).

La usan el simulador y la galería de gestos de la app. Si se añade o cambia
un gesto en el firmware, hay que reflejarlo aquí (y en el rango de GESTO en
config/commands.json).
"""

from dataclasses import dataclass

ABIERTO, CERRADO, DESCONOCIDO = "abierto", "cerrado", "?"


@dataclass(frozen=True)
class Gesto:
    nombre: str
    indice: str
    medio: str
    anular: str
    pulgar: int  # ángulo del servo

    def dedos(self) -> dict[str, str]:
        return {"indice": self.indice, "medio": self.medio, "anular": self.anular}


# Nombres según la postura o el agarre (terminología de prótesis comerciales).
GESTOS = [
    Gesto("Mano abierta",     ABIERTO, ABIERTO, ABIERTO, 10),
    Gesto("Índice y medio",   ABIERTO, ABIERTO, CERRADO, 10),
    Gesto("Índice y anular",  ABIERTO, CERRADO, ABIERTO, 10),
    Gesto("Medio extendido",  CERRADO, ABIERTO, CERRADO, 10),
    Gesto("Índice extendido", ABIERTO, CERRADO, CERRADO, 10),
    Gesto("Señalar",          ABIERTO, CERRADO, CERRADO, 90),  # índice extendido, pulgar recogido
    Gesto("Mano plana",       ABIERTO, ABIERTO, ABIERTO, 90),  # dedos extendidos, pulgar recogido
    Gesto("Gancho",           CERRADO, CERRADO, CERRADO, 10),  # dedos cerrados, pulgar abierto (asas, bolsas)
]
