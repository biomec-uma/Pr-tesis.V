"""Asistente con IA (Claude) para la app: preguntas, diagnóstico y órdenes en lenguaje natural.

Seguridad: el asistente NUNCA mueve la mano por su cuenta. Su única forma de
actuar es la herramienta proponer_comandos, que la app enseña como una
tarjeta con un botón «Ejecutar»: solo se envía lo que el usuario confirma.
Para saber qué pasa, leer_estado devuelve una foto del estado de la app
(solo lectura).

API (Claude Opus 5.5): streaming con bucle manual de herramientas, caché del
prompt (sistema + catálogo + conversación) y fallbacks del servidor
("default"): si un clasificador de seguridad rechaza la petición, la API la
reintenta sola con el modelo recomendado.

Este módulo no usa Qt: el panel (ui/assistant_panel.py) lo ejecuta en un hilo
y recibe el texto y las propuestas por callbacks.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Callable

from .commands import CommandCatalog, CommandError
from .gestures import GESTOS

MODEL = "claude-opus-5-5"
EFFORT = "medium"           # Opus 5.5: el pensamiento siempre está activo; el esfuerzo regula cuánto
MAX_TOKENS = 64000          # con streaming no hay riesgo de timeout
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_STEPS = 20
MAX_WAIT_MS = 15000
MAX_JSON_RETRIES = 2
MAX_ROUNDS = 12             # rondas de herramientas por turno (evita bucles)


@dataclass
class Proposal:
    explanation: str
    steps: list[tuple[str, int]] = field(default_factory=list)  # (comando, espera en ms tras él)


class AssistantError(Exception):
    """Error que se le puede enseñar al usuario tal cual (sin clave, sin red, límite de uso...)."""


class Callbacks:
    """El panel sobreescribe estos métodos (se llaman desde el hilo del asistente)."""

    def on_text(self, delta: str) -> None: ...
    def on_activity(self, text: str) -> None: ...
    def on_proposal(self, proposal: Proposal) -> None: ...


TOOLS = [
    {
        "name": "leer_estado",
        "description": (
            "Lee el estado actual de la app y de la mano: conexión (real o simulación), estado de la mano, "
            "modo, gesto o postura activa, última telemetría, latencia, posturas personalizadas, grabación "
            "de sesión y las últimas líneas de la consola. Úsala antes de responder sobre lo que pasa ahora."),
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "proponer_comandos",
        "description": (
            "Propone al usuario una secuencia de comandos para la mano. NO los ejecuta: la app los muestra con "
            "un botón Ejecutar y solo se envían si el usuario lo pulsa. Cada comando debe ser del catálogo "
            "(p. ej. 'GESTO 3', 'POSTURA C A A 90', 'PULGAR 45', 'PARAR'). espera_ms es la pausa tras ese "
            "comando antes de enviar el siguiente: un movimiento de los dedos dura TIEMPO ms (3000 por defecto)."),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "explicacion": {"type": "string", "description": "Una frase: qué hará la secuencia"},
                "pasos": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_STEPS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "comando": {"type": "string", "description": "Comando del catálogo con sus argumentos"},
                            "espera_ms": {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_MS},
                        },
                        "required": ["comando"],
                    },
                },
            },
            "required": ["explicacion", "pasos"],
        },
    },
]

_SYSTEM = """Eres el asistente integrado en BIOMEC Control, la app de escritorio con la que el equipo BIOMEC \
(Universidad de Málaga) controla y prueba el prototipo de una prótesis de mano mioeléctrica de bajo coste. \
Hablas con estudiantes e ingenieros del equipo.

# El sistema
- PC (esta app) → USB → ESP32-C6 «puente» → ESP-NOW (canal 1) → ESP32-WROOM de la mano. Las respuestas \
vuelven por el mismo camino. Los comandos que empiezan por @ los ejecuta el propio puente.
- La mano tiene 3 motores DC (índice, medio y anular+meñique juntos) con rampas de 500 ms; cada movimiento \
dura TIEMPO ms (3000 por defecto). No hay sensores de posición: cada dedo está abierto, cerrado o \
«desconocido» (si se interrumpió). El pulgar es un servo: 10° separado, 90° en pinza.
- Placa EMG: ESP32-C3 + ADS1198 (8 canales; el equipo usa 2) a 500 muestras/s. Sus paquetes llegan a la app \
por el puente cuando se activa @EMG 1.
- Modo simulación: una mano y un «paciente virtual» simulados dentro de la app responden igual que el \
hardware, sin mover nada real.

# Protocolo (líneas de texto)
DATA clave=valor (telemetría: PWM de cada dedo −255…255, + abre / − cierra; pulgar en grados; gesto) · \
ACK (comando ejecutado) · ERR (error) · BRIDGE (mensaje del puente) · EMG (muestras).

# Comandos del catálogo
{catalog}

# Gestos de fábrica
{gestures}

# La app
- Gemelo digital: modelo 3D que imita a la mano. Pestaña Control (seguir a la mano, % de cierre) y Postura \
(galería de gestos, «Mis posturas» personalizadas que se envían con POSTURA, dedos sueltos, pulgar, modo).
- Gráficas: telemetría en tiempo real con marcas de cada comando enviado.
- Entrenamiento: graba EMG guiado por movimientos, entrena un clasificador (características de Hudgins + \
LDA) y puede mover la mano con los músculos. Exporta el modelo a C para la ESP32.
- Grabar (Ctrl+R) y Reproducir (Ctrl+O) sesiones; consola (Ctrl+J); paleta de comandos (Ctrl+K).
- Parar (Esc) envía PARAR: es una parada por software que depende de la radio, no una parada de emergencia física.
- Latencia: tiempo entre enviar un comando y recibir su respuesta. Verde < 100 ms, ámbar ≤ 125 ms. \
Farrell y Weir (2007) sitúan el retardo óptimo del control completo en 100-125 ms.

# Problemas frecuentes
- «Write timeout» o desconexión al enviar: la C6 se programó sin «USB CDC On Boot: Enabled».
- «ERR Comando desconocido en la mano: @PING»: el puente tiene un firmware antiguo o se programó en la C6 el \
firmware de la mano; hay que subir firmware/puente_pc.
- «Mano: sin respuesta» con el puente conectado: la mano está apagada, usa otro canal ESP-NOW, la MAC \
configurada (HAND_MAC / BRIDGE_MAC) no es la correcta o la mano no tiene el firmware nuevo.
- Sin señal EMG: en firmware/EMG/src/main.cpp, rxMac debe ser la MAC del puente (la da @INFO); falta @EMG 1; \
o EMG_CANALES del puente no coincide con N_CHNLS de la placa.
- Poca precisión de la IA: incluir Reposo, grabar 2 o más repeticiones, movimientos más distintos entre sí, \
más canales del ADS1198.

# Cómo trabajas
- Responde en español, breve y al grano: unas pocas frases o una lista corta.
- Para mover la mano usa SIEMPRE proponer_comandos; nunca digas que algo se ha ejecutado salvo que una nota de \
la app lo confirme. Con la mano real, propón secuencias cortas y recuerda que Parar (Esc) está disponible.
- Usa leer_estado cuando la respuesta dependa de lo que está pasando ahora (conexión, errores, latencia...).
- Si algo no se puede hacer con el catálogo (por ejemplo, no hay control de velocidad ni posiciones \
intermedias de los dedos), dilo y propone la alternativa más cercana.
- Si no sabes algo del hardware, dilo y sugiere cómo comprobarlo."""


def build_system_prompt(catalog: CommandCatalog) -> str:
    lines = []
    for cmd in catalog:
        where = "puente, se envía con @" if cmd.target == "puente" else "mano"
        lines.append(f"- {cmd.usage} ({where}): {cmd.description}")
    gestures = "\n".join(f"{i}. {g.nombre}: índice {g.indice}, medio {g.medio}, anular {g.anular}, pulgar {g.pulgar}°"
                         for i, g in enumerate(GESTOS, start=1))
    return _SYSTEM.format(catalog="\n".join(lines), gestures=gestures)


def validate_proposal(args, catalog: CommandCatalog) -> tuple[Proposal | None, str]:
    """(propuesta, "") si es correcta; (None, motivo) si no. La salida del modelo no es de fiar: se comprueba todo."""
    if not isinstance(args, dict):
        return None, "La entrada debe ser un objeto con 'explicacion' y 'pasos'."
    explanation, steps = args.get("explicacion"), args.get("pasos")
    if not isinstance(explanation, str) or not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        return None, f"Hacen falta 'explicacion' (texto) y 'pasos' (lista de 1 a {MAX_STEPS} pasos)."
    out, problems = [], []
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or not isinstance(step.get("comando"), str):
            problems.append(f"Paso {i}: falta 'comando' (texto).")
            continue
        wait = step.get("espera_ms", 0)
        if isinstance(wait, bool) or not isinstance(wait, int) or not 0 <= wait <= MAX_WAIT_MS:
            problems.append(f"Paso {i}: 'espera_ms' debe ser un entero entre 0 y {MAX_WAIT_MS}.")
            continue
        try:
            cmd, _line = catalog.build(step["comando"])
        except CommandError as error:
            problems.append(f"Paso {i} ({step['comando']!r}): {error}")
            continue
        args_text = step["comando"].split()[1:]
        out.append((" ".join([cmd.name, *args_text]), wait))
    if problems:
        return None, "Comandos no válidos:\n" + "\n".join(problems)
    return Proposal(explanation.strip(), out), ""


class Assistant:
    def __init__(self, catalog: CommandCatalog, state_provider: Callable[[], dict], api_key: str | None = None):
        self.catalog = catalog
        self.state_provider = state_provider
        self.system = build_system_prompt(catalog)
        self.messages: list[dict] = []    # historial: solo se añade (y se deshace un turno entero si falla)
        self._api_key = api_key
        self._client = None
        self.cancel = threading.Event()

    def set_api_key(self, key: str | None) -> None:
        self._api_key = key or None
        self._client = None

    def refresh_catalog(self) -> None:
        self.system = build_system_prompt(self.catalog)

    def reset(self) -> None:
        self.messages = []

    def _get_client(self):
        import anthropic  # perezoso: la app arranca aunque falte el paquete
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self._api_key) if self._api_key else anthropic.Anthropic()
        return self._client

    # ------------------------------------------------------------ un turno
    def run_turn(self, text: str, cb: Callbacks) -> str:
        """Ejecuta un turno completo. Devuelve "ok", "cancelled" o "refusal"; lanza AssistantError."""
        try:
            import anthropic
        except ImportError:
            raise AssistantError("Falta el paquete de Claude. Instálalo con: pip install anthropic") from None

        self.cancel.clear()
        start = len(self.messages)
        self.messages.append({"role": "user", "content": text})
        try:
            status = self._loop(cb)
        except anthropic.AuthenticationError:
            status, error = "error", "La clave de API no es válida. Revísala en ⚙ (ajustes del asistente)."
        except anthropic.PermissionDeniedError:
            status, error = "error", "La clave de API no tiene permiso para usar este modelo."
        except anthropic.RateLimitError:
            status, error = "error", "Se ha alcanzado el límite de uso de la API. Espera un poco y vuelve a intentarlo."
        except anthropic.BadRequestError as e:
            status, error = "error", f"La API rechazó la petición: {e.message}"
        except anthropic.APIStatusError as e:
            status, error = "error", (f"El servicio de Claude no está disponible ahora (error {e.status_code}). "
                                      "Inténtalo en unos minutos." if e.status_code >= 500
                                      else f"Error de la API ({e.status_code}): {e.message}")
        except anthropic.APIConnectionError:
            status, error = "error", "No hay conexión con la API de Claude. ¿Hay internet?"
        except TypeError as e:  # el SDK no encuentra ninguna credencial
            if "authentication" not in str(e).lower():
                raise
            status, error = "error", ("Falta la clave de API de Claude. Añádela en ⚙ o define la variable de "
                                      "entorno ANTHROPIC_API_KEY.")
        except AssistantError as e:
            status, error = "error", str(e)
        else:
            error = ""
        if status != "ok":
            # se deshace el turno entero: el historial sigue siendo válido (y el siguiente turno, coherente)
            del self.messages[start:]
        if error:
            raise AssistantError(error)
        return status

    def _loop(self, cb: Callbacks) -> str:
        client = self._get_client()
        json_retries = 0
        for _round in range(MAX_ROUNDS):
            try:
                with client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=self.system,
                    tools=TOOLS,
                    messages=self.messages,
                    output_config={"effort": EFFORT},
                    cache_control={"type": "ephemeral"},   # caché automática del prefijo (sistema + historial)
                    betas=[FALLBACK_BETA],
                    fallbacks="default",                   # si se rechaza, la API reintenta con otro modelo
                ) as stream:
                    for event in stream:
                        if self.cancel.is_set():
                            return "cancelled"
                        if event.type == "text":
                            cb.on_text(event.text)
                        elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                            name = event.content_block.name
                            cb.on_activity("Consultando el estado de la app…" if name == "leer_estado"
                                           else "Preparando una propuesta de comandos…")
                    response = stream.get_final_message()
                json_retries = 0
            except ValueError:
                # JSON de una herramienta que el SDK no pudo leer: no hay tool_use_id al que responder,
                # se repite la petición (con límite). Los errores de la API no son ValueError.
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    raise AssistantError("La respuesta llegó dañada varias veces. Inténtalo de nuevo.") from None
                continue

            if response.stop_reason == "pause_turn":
                self.messages.append({"role": "assistant", "content": response.content})
                continue
            if response.stop_reason == "refusal":
                return "refusal"
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "max_tokens" and tool_uses:
                raise AssistantError("La respuesta se cortó antes de terminar. Prueba con una petición más corta.")
            self.messages.append({"role": "assistant", "content": response.content})
            if not tool_uses:
                return "ok"
            results = [self._run_tool(block, cb) for block in tool_uses]
            self.messages.append({"role": "user", "content": results})  # todos los resultados en un mensaje
        raise AssistantError("El asistente encadenó demasiados pasos sin terminar. Reformula la petición.")

    def _run_tool(self, block, cb: Callbacks) -> dict:
        args = block.input
        if block.name == "leer_estado":
            if not isinstance(args, dict):
                return self._error(block, {"INVALID_JSON": json.dumps(args, ensure_ascii=False)})
            state = self.state_provider()
            return {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(state, ensure_ascii=False)}
        if block.name == "proponer_comandos":
            proposal, problem = validate_proposal(args, self.catalog)
            if proposal is None:
                return self._error(block, problem)
            cb.on_proposal(proposal)
            return {"type": "tool_result", "tool_use_id": block.id,
                    "content": ("Propuesta mostrada al usuario con un botón Ejecutar. Todavía NO se ha ejecutado: "
                                "solo se enviará si el usuario la confirma. No digas que la mano ya se ha movido.")}
        return self._error(block, f"Herramienta desconocida: {block.name}")

    @staticmethod
    def _error(block, content) -> dict:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": text}
