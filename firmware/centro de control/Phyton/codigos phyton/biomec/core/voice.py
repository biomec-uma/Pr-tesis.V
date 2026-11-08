"""Control por voz sin internet: reconocimiento con Vosk y una lista cerrada de órdenes.

Vosk funciona en el propio ordenador (gratis, sin conexión, en tiempo real). Con
una gramática cerrada, el reconocedor solo puede "oír" las frases de la tabla
(o [unk] para todo lo demás), así que es muy fiable incluso con el modelo
pequeño y ruido de laboratorio.

Seguridad:
  - Una orden solo se ejecuta si la frase entera es una orden de la tabla y la
    confianza es alta: lo que se dice en una conversación ("vamos a abrir la
    caja") no mueve la mano.
  - "Para" (y "alto", "quieto"…) se acepta siempre, aunque vaya rodeada de
    otras palabras: ante la duda, parar es lo seguro.

El modelo (~40 MB, español) se descarga una vez a %APPDATA%/BIOMEC Control/voz.
"""

from __future__ import annotations

import json
import shutil
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MODEL_NAME = "vosk-model-small-es-0.42"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_MB = 40
MIN_CONF = 0.75          # confianza media mínima de las palabras de una orden
STOP_MIN_CONF = 0.45     # "para" se acepta con menos: parar ante la duda es lo seguro
NUMBERS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"]
STOP_WORDS = {"para", "parar", "alto", "quieto", "detente", "stop"}
STOP_TOKENS = STOP_WORDS | {"la", "mano", "ya"}  # lo que puede acompañar a una parada: "¡para la mano ya!"


@dataclass(frozen=True)
class VoiceAction:
    kind: str     # "command" (se envía a la mano) | "page" (cambia de pestaña) | "app" (grabar…)
    value: str    # "GESTO 6", título de la pestaña o clave de la acción
    label: str    # lo que se le enseña al usuario: "Señalar"

    @property
    def is_stop(self) -> bool:
        return self.kind == "command" and self.value == "PARAR"


def normalize(text: str) -> str:
    """'Índice  y MEDIO' -> 'indice y medio' (sin tildes ni mayúsculas, espacios simples)."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(plain.replace(",", " ").replace(".", " ").split())


def build_phrases(gestures, postures=(), pages=()) -> dict[str, tuple[str, VoiceAction]]:
    """Tabla de órdenes: frase normalizada -> (frase tal cual se dice, acción)."""
    table: dict[str, tuple[str, VoiceAction]] = {}

    def add(phrases, action: VoiceAction) -> None:
        for p in phrases:
            table.setdefault(normalize(p), (p.lower(), action))

    add(["para", "parar", "alto", "quieto", "detente", "stop", "para la mano"], VoiceAction("command", "PARAR", "Parar"))
    add(["abre la mano", "abrir la mano", "abre", "abrir", "abre la mano entera"],
        VoiceAction("command", "ABRIR", "Abrir la mano"))
    add(["cierra la mano", "cerrar la mano", "cierra", "cerrar", "cierra el puño", "puño"],
        VoiceAction("command", "CERRAR", "Cerrar la mano"))
    for i, g in enumerate(gestures, start=1):
        action = VoiceAction("command", f"GESTO {i}", g.nombre)
        add([g.nombre, f"gesto {NUMBERS[i]}" if i < len(NUMBERS) else g.nombre], action)
    señalar = next((i for i, g in enumerate(gestures, start=1) if normalize(g.nombre) == "senalar"), None)
    if señalar:
        add(["señala", "señalar", "apunta"], VoiceAction("command", f"GESTO {señalar}", "Señalar"))
    custom = {normalize(p.nombre): p for p in postures}
    from .postures import posture_command  # evita una importación circular al cargar el módulo
    for p in postures:
        add([p.nombre, f"postura {p.nombre}"], VoiceAction("command", posture_command(p), p.nombre))
    if "pinza" not in custom:
        add(["pinza", "haz una pinza", "haz la pinza"], VoiceAction("command", "POSTURA C A A 90", "Pinza"))
    for dedo, nombre in (("INDICE", "índice"), ("MEDIO", "medio"), ("ANULAR", "anular")):
        add([f"abre el {nombre}"], VoiceAction("command", f"DEDO {dedo} ABRIR", f"Abrir el {nombre}"))
        add([f"cierra el {nombre}"], VoiceAction("command", f"DEDO {dedo} CERRAR", f"Cerrar el {nombre}"))
    add(["abre el pulgar", "separa el pulgar", "pulgar abierto"], VoiceAction("command", "PULGAR 10", "Separar el pulgar"))
    add(["cierra el pulgar", "pulgar en pinza", "pulgar cerrado"], VoiceAction("command", "PULGAR 90", "Pulgar en pinza"))
    add(["modo demostración", "demostración", "modo automático"], VoiceAction("command", "AUTO", "Modo demo"))
    add(["modo manual"], VoiceAction("command", "MANUAL", "Modo manual"))
    for title in pages:
        add([title, f"ve a {title}", f"abre {title}"], VoiceAction("page", title, f"Ir a {title}"))
    add(["graba", "empieza a grabar", "grabar sesión"], VoiceAction("app", "grabar", "Grabar la sesión"))
    add(["deja de grabar", "para de grabar", "detén la grabación"], VoiceAction("app", "detener", "Detener la grabación"))
    return table


@dataclass
class Heard:
    text: str                       # lo que reconoció Vosk ("abre la mano", "[unk] para [unk]")
    action: VoiceAction | None      # la orden, si se acepta
    confidence: float
    reason: str = ""                # por qué no se acepta (para mostrarlo)


def interpret(result: dict, table: dict[str, tuple[str, VoiceAction]]) -> Heard | None:
    """Decide si un resultado final de Vosk es una orden. None si no se oyó nada útil."""
    text = result.get("text", "").strip()
    tokens = text.split()
    clean = [t for t in tokens if t != "[unk]"]
    if not clean:
        return None
    words = [w for w in result.get("result", []) if w.get("word") != "[unk]"]
    conf = sum(w.get("conf", 1.0) for w in words) / len(words) if words else 1.0
    entry = table.get(normalize(" ".join(clean)))
    if entry is None:
        # "¡para, para!" o "alto, para": varias palabras de parada seguidas también paran la mano.
        # Una frase normal que contiene "para" ("esto es para la prueba") no.
        norm = [normalize(t) for t in clean]
        if any(n in STOP_WORDS for n in norm) and all(n in STOP_TOKENS for n in norm):
            stop = next(a for _s, a in table.values() if a.is_stop)
            return Heard(text, stop, conf) if conf >= STOP_MIN_CONF else Heard(text, None, conf, "confianza baja")
        return Heard(text, None, conf, "no es una orden")
    action = entry[1]
    if action.is_stop:
        return Heard(text, action, conf) if conf >= STOP_MIN_CONF else Heard(text, None, conf, "confianza baja")
    if len(clean) != len(tokens):
        return Heard(text, None, conf, "frase incompleta")
    if conf < MIN_CONF:
        return Heard(text, None, conf, "confianza baja")
    return Heard(text, action, conf)


class VoiceRecognizer:
    """Vosk con la gramática de órdenes. feed() recibe audio PCM 16 bits mono."""

    def __init__(self, model_path: str | Path, phrases: list[str], sample_rate: int = 16000):
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        self._KaldiRecognizer = KaldiRecognizer
        self.model = Model(str(model_path))
        self.sample_rate = sample_rate
        self.grammar: list[str] = []
        self.set_phrases(phrases)

    def known(self, phrase: str) -> bool:
        return all(self.model.vosk_model_find_word(w) != -1 for w in phrase.split())

    def set_phrases(self, phrases: list[str]) -> None:
        """Solo entran las frases cuyas palabras conoce el modelo (las demás no se podrían reconocer)."""
        self.grammar = sorted({p for p in phrases if self.known(p)})
        self.rec = self._KaldiRecognizer(self.model, self.sample_rate,
                                         json.dumps(self.grammar + ["[unk]"], ensure_ascii=False))
        self.rec.SetWords(True)

    def feed(self, pcm: bytes) -> tuple[str, dict | None]:
        """(texto parcial, resultado final o None)."""
        if self.rec.AcceptWaveform(pcm):
            return "", json.loads(self.rec.Result())
        return json.loads(self.rec.PartialResult()).get("partial", ""), None

    def flush(self) -> dict:
        return json.loads(self.rec.FinalResult())


# ============================================================ modelo de voz
def model_dir(root: Path) -> Path:
    return root / MODEL_NAME


def model_ready(root: Path) -> bool:
    d = model_dir(root)
    return (d / "am").is_dir() and (d / "conf").is_dir()


def download_model(root: Path, progress: Callable[[int, int], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> Path:
    """Descarga y descomprime el modelo (una sola vez). progress(bytes, total)."""
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{MODEL_NAME}.zip.part"
    req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "BIOMEC-Control"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            if cancelled and cancelled():
                raise InterruptedError("Descarga cancelada")
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    target = model_dir(root)
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(tmp) as zf:
        for member in zf.namelist():  # nada fuera de la carpeta de destino
            if not (root / member).resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Ruta no válida en el zip: {member}")
        zf.extractall(root)
    tmp.unlink()
    if not model_ready(root):
        raise ValueError("El modelo descargado no tiene el formato esperado")
    return target
