"""Modelo 3D de la mano: carga los STL y calcula la posición de cada pieza.

Sin interfaz (solo numpy), para poder probarlo por separado.

Cada dedo es un mecanismo de barras (ver config/mano3d.json):
    - La falange proximal gira sobre el pasador A de la palma.
    - La biela Base-Medio (B-D) obliga a la falange media a girar con ella.
    - La biela Proximal-Distal (F-G) obliga a la distal a cerrarse también.
Dada la flexión (0 = abierto, 1 = cerrado) se resuelven los dos cuadriláteros
articulados y se obtiene la matriz 4x4 de cada pieza.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DEDOS = ("indice", "medio", "anular")
_STEPS = 400  # resolución de la tabla de posiciones de cada dedo


# ---------------------------------------------------------------- STL
def load_stl(path: Path) -> np.ndarray:
    """Devuelve los triángulos como array (N, 3, 3) en mm. Admite STL binario y ASCII."""
    data = path.read_bytes()
    n = int.from_bytes(data[80:84], "little") if len(data) >= 84 else 0
    if len(data) == 84 + 50 * n:
        rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        return np.frombuffer(data, dtype=rec, count=n, offset=84)["v"].astype(np.float32)
    verts = [list(map(float, line.split()[1:4]))
             for line in data.decode("ascii", "ignore").splitlines() if line.strip().startswith("vertex")]
    return np.asarray(verts, dtype=np.float32).reshape(-1, 3, 3)


# ---------------------------------------------------------- geometría 2D
# Los dedos se mueven en el plano (y, z): giros alrededor del eje X.
def _rot2(v: np.ndarray, a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([v[0] * c - v[1] * s, v[0] * s + v[1] * c])


def _angle(v: np.ndarray) -> float:
    return float(np.arctan2(v[1], v[0]))


def _circle_intersection(c0, r0, c1, r1, prev):
    """Punto a distancia r0 de c0 y r1 de c1; de las dos soluciones, la más cercana a prev."""
    d = float(np.linalg.norm(c1 - c0))
    if d == 0 or d > r0 + r1 or d < abs(r0 - r1):
        return None
    a = (r0 ** 2 - r1 ** 2 + d ** 2) / (2 * d)
    h = np.sqrt(max(r0 ** 2 - a ** 2, 0.0))
    m = c0 + a * (c1 - c0) / d
    perp = np.array([-(c1 - c0)[1], (c1 - c0)[0]]) / d
    s1, s2 = m + h * perp, m - h * perp
    return s1 if np.linalg.norm(s1 - prev) <= np.linalg.norm(s2 - prev) else s2


def rotation_x(pivot_yz, angle: float, new_pivot_yz=None) -> np.ndarray:
    """Matriz 4x4: gira `angle` rad alrededor del eje X que pasa por pivot y lo lleva a new_pivot."""
    py, pz = pivot_yz
    ny, nz = new_pivot_yz if new_pivot_yz is not None else pivot_yz
    c, s = np.cos(angle), np.sin(angle)
    m = np.eye(4)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    m[1, 3] = ny - (c * py - s * pz)
    m[2, 3] = nz - (s * py + c * pz)
    return m


def rotation_y(pivot_xz, angle: float) -> np.ndarray:
    """Matriz 4x4: gira `angle` rad alrededor de un eje paralelo a Y que pasa por (x, z)."""
    px, pz = pivot_xz
    c, s = np.cos(angle), np.sin(angle)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    m[0, 3] = px - (c * px + s * pz)
    m[2, 3] = pz - (-s * px + c * pz)
    return m


# --------------------------------------------------------- un dedo
class FingerLinkage:
    """Resuelve el mecanismo de un dedo y guarda una tabla flexión -> matrices."""

    PARTS = ("Proximal", "Medio", "Distal", "Base-Medio", "Proximal-Distal")

    def __init__(self, pivots: dict, max_flex_deg: float):
        P = {k: np.asarray(v, dtype=float) for k, v in pivots.items()}
        L_bd, L_cd = np.linalg.norm(P["D"] - P["B"]), np.linalg.norm(P["D"] - P["C"])
        L_fg, L_eg = np.linalg.norm(P["G"] - P["F"]), np.linalg.norm(P["G"] - P["E"])
        self.table: list[dict[str, np.ndarray]] = []
        D_prev, G_prev = P["D"], P["G"]
        for theta in np.linspace(0.0, -np.radians(max_flex_deg), _STEPS + 1):  # flexión = giro negativo
            C = P["A"] + _rot2(P["C"] - P["A"], theta)
            F = P["A"] + _rot2(P["F"] - P["A"], theta)
            D = _circle_intersection(P["B"], L_bd, C, L_cd, D_prev)
            if D is None:
                break
            a_med = _angle(D - C) - _angle(P["D"] - P["C"])
            E = C + _rot2(P["E"] - P["C"], a_med)
            G = _circle_intersection(F, L_fg, E, L_eg, G_prev)
            if G is None:
                break
            a_dis = _angle(G - E) - _angle(P["G"] - P["E"])
            D_prev, G_prev = D, G
            self.table.append({
                "Proximal": rotation_x(P["A"], theta),
                "Medio": rotation_x(P["C"], a_med, C),
                "Distal": rotation_x(P["E"], a_dis, E),
                "Base-Medio": rotation_x(P["B"], _angle(D - P["B"]) - _angle(P["D"] - P["B"])),
                "Proximal-Distal": rotation_x(P["F"], _angle(G - F) - _angle(P["G"] - P["F"]), F),
            })
        if len(self.table) < 2:
            raise ValueError("El mecanismo del dedo no tiene solución: revisa los pasadores en mano3d.json")

    def transforms(self, flex: float) -> dict[str, np.ndarray]:
        i = int(round(min(max(flex, 0.0), 1.0) * (len(self.table) - 1)))
        return self.table[i]


# ---------------------------------------------------------- la mano
@dataclass
class Part:
    name: str          # p. ej. "indice/Proximal", "palma", "pulgar"
    triangles: np.ndarray
    color: str


@dataclass
class HandModel:
    parts: dict[str, Part] = field(default_factory=dict)
    fingers: dict[str, FingerLinkage] = field(default_factory=dict)
    thumb_axis: str = "x"
    thumb_point: tuple = (0.0, 0.0)
    thumb_reference: float = 10.0
    thumb_sign: int = 1
    thumb_ratio: float = 1.0
    thumb_speed: float = 300.0
    close_time_s: float = 1.5
    center: np.ndarray = field(default_factory=lambda: np.zeros(3))
    size: float = 200.0

    @classmethod
    def load(cls, config_path: Path, assets_dir: Path) -> "HandModel":
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        folder = assets_dir / cfg.get("carpeta", "modelo3d")
        files = sorted(folder.glob("*.[sS][tT][lL]"))

        def find(*needles: str) -> Path:
            for f in files:
                if all(n.lower() in f.name.lower() for n in needles):
                    return f
            raise FileNotFoundError(f"No encuentro el STL que contiene {needles} en {folder}")

        m = cls()
        for fixed in cfg["piezas_fijas"]:
            name = Path(fixed["archivo"]).stem.replace("mano - ", "")
            m.parts[name] = Part(name, load_stl(folder / fixed["archivo"]), fixed["color"])

        for dedo, info in cfg["dedos"].items():
            m.fingers[dedo] = FingerLinkage(info["pasadores"], cfg["flexion_max_grados"])
            for role, spec in cfg["piezas_dedo"].items():
                # Ojo: "ProximalV1-1" también aparece dentro de "Base-...": se busca con el espacio delante.
                path = find(info["ensamblaje"] + " " + spec["archivo"])
                m.parts[f"{dedo}/{role}"] = Part(f"{dedo}/{role}", load_stl(path), spec["color"])

        th = cfg["pulgar"]
        m.parts["pulgar"] = Part("pulgar", load_stl(folder / th["archivo"]), th["color"])
        m.thumb_axis = th.get("eje", "x").lower()
        m.thumb_point = tuple(th["eje_punto"])
        m.thumb_reference = float(th["angulo_modelo"])
        m.thumb_sign = int(th["signo"])
        m.thumb_ratio = float(th.get("relacion", 1.0))
        m.thumb_speed = float(th.get("velocidad_grados_s", 300))
        m.close_time_s = float(cfg.get("tiempo_cierre_s", 1.5))

        allv = np.concatenate([p.triangles.reshape(-1, 3) for p in m.parts.values()])
        lo, hi = allv.min(0), allv.max(0)
        m.center, m.size = (lo + hi) / 2, float(np.max(hi - lo))
        return m

    def pose(self, flex: dict[str, float], thumb_angle: float) -> dict[str, np.ndarray]:
        """Matriz 4x4 de cada pieza móvil para una postura dada."""
        out = {}
        for dedo, linkage in self.fingers.items():
            for role, mat in linkage.transforms(flex.get(dedo, 0.0)).items():
                out[f"{dedo}/{role}"] = mat
        angle = np.radians((thumb_angle - self.thumb_reference) * self.thumb_ratio * self.thumb_sign)
        rotate = rotation_x if self.thumb_axis == "x" else rotation_y
        out["pulgar"] = rotate(self.thumb_point, angle)
        return out
