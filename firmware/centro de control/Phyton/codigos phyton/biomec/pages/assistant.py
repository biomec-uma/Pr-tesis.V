"""Ventana "Asistente IA".

    ✦ Claude · propone, tú ejecutas       ⚙ 🗑
    ┌──────────────────────────────────────────┐
    │            [¿Por qué no responde…?]  tú  │
    │  Claude: La mano no contesta porque…     │
    │  ┌ PROPUESTA ─────────────────────────┐  │
    │  │ 1. POSTURA C A A 90 · espera 3 s   │  │
    │  │ 2. ABRIR                           │  │
    │  │ [▶ Ejecutar]  [Descartar]          │  │
    │  └────────────────────────────────────┘  │
    └──────────────────────────────────────────┘
    [ Pregunta o pide algo…                 ] [Enviar]
    Claude Opus 5.5 · solo se envía lo que tú confirmas

El asistente (core/assistant.py) se ejecuta en un hilo; el texto llega por
señales Qt. NUNCA envía comandos solo: propone, y el usuario pulsa Ejecutar.
Atajo: Ctrl+I.
"""

import threading
import time
from collections import deque

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, ORG_NAME
from ..core.assistant import MODEL, Assistant, AssistantError, Callbacks, Proposal
from ..core.gestures import GESTOS
from ..core.postures import posture_command
from ..core.protocol import MessageKind
from ..core.secrets import protect, unprotect
from ..core.simulator import SIMULATOR_PORT
from ..ui.icons import icon
from ..ui.theme import PALETTES
from ..ui.widgets import ElidedLabel, style_titlebar
from .base import BasePage

MODEL_LABEL = {"claude-opus-5-5": "Claude Opus 5.5"}.get(MODEL, MODEL)
SUGGESTIONS = [
    "¿Por qué no responde la mano?",
    "Haz una pinza con el índice y luego abre la mano",
    "¿Qué indica la latencia de la barra de estado?",
    "¿Cómo entreno la IA con mis señales EMG?",
]
MIN_GAP_MS = 150  # pausa mínima entre comandos de una propuesta


class _Bridge(QObject):
    """Lleva lo que pasa en el hilo del asistente al hilo de la interfaz."""
    text = Signal(str)
    activity = Signal(str)
    proposal = Signal(object)
    done = Signal(str, str)


class _Relay(Callbacks):
    def __init__(self, bridge: _Bridge):
        self.bridge = bridge

    def on_text(self, delta: str) -> None:
        self.bridge.text.emit(delta)

    def on_activity(self, text: str) -> None:
        self.bridge.activity.emit(text)

    def on_proposal(self, proposal: Proposal) -> None:
        self.bridge.proposal.emit(proposal)


class _Input(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ProposalCard(QWidget):
    """Tarjeta con los comandos propuestos. Solo se ejecutan si el usuario pulsa Ejecutar."""

    def __init__(self, panel: "AssistantPanel", proposal: Proposal):
        super().__init__()
        self.panel = panel
        self.proposal = proposal
        self.setObjectName("proposalCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        cap = QLabel("PROPUESTA")
        cap.setObjectName("caption")
        lay.addWidget(cap)
        text = QLabel(proposal.explanation)
        text.setWordWrap(True)
        lay.addWidget(text)
        steps = []
        for i, (cmd, wait) in enumerate(proposal.steps, start=1):
            pause = f"  ·  espera {wait / 1000:g} s" if wait else ""
            steps.append(f"{i}. <b>{cmd}</b><span style='color:{PALETTES[panel.ctx.theme]['muted']}'>{pause}</span>")
        self.steps_lbl = QLabel("<br>".join(steps))
        self.steps_lbl.setObjectName("monoText")
        self.steps_lbl.setTextFormat(Qt.RichText)
        self.steps_lbl.setWordWrap(True)
        lay.addWidget(self.steps_lbl)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.run_btn = QPushButton("  Ejecutar")
        self.run_btn.setObjectName("primary")
        self.run_btn.setIcon(icon("play", "#ffffff", 14))
        self.run_btn.setToolTip("Envía estos comandos a la mano, en orden (Parar / Esc interrumpe)")
        self.run_btn.clicked.connect(lambda: panel.execute(self))
        self.skip_btn = QPushButton("Descartar")
        self.skip_btn.setObjectName("ghost")
        self.skip_btn.clicked.connect(lambda: panel.dismiss(self))
        row.addWidget(self.run_btn)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.status)

    def finish(self, text: str, color_key: str = "muted") -> None:
        self.run_btn.hide()
        self.skip_btn.hide()
        self.set_status(text, color_key)

    def set_status(self, text: str, color_key: str = "muted") -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {PALETTES[self.panel.ctx.theme][color_key]};")
        self.status.show()


class KeyDialog(QDialog):
    def __init__(self, parent, current_source: str):
        super().__init__(parent)
        self.setObjectName("infoDialog")
        self.setWindowTitle("Asistente IA · clave de API")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.cleared = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        title = QLabel("Clave de API de Claude")
        title.setObjectName("pageTitle")
        lay.addWidget(title)
        source = QLabel(current_source)
        source.setObjectName("muted")
        source.setWordWrap(True)
        lay.addWidget(source)
        row = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-ant-…   (déjalo vacío para no cambiarla)")
        show = QPushButton("Mostrar")
        show.setCheckable(True)
        show.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        row.addWidget(self.key, 1)
        row.addWidget(show)
        lay.addLayout(row)
        info = QLabel(
            "Consíguela en <a href='https://console.anthropic.com/settings/keys'>console.anthropic.com</a> "
            "(API Keys). Se guarda <b>cifrada para tu usuario de Windows</b> (DPAPI) y solo se usa para hablar con "
            "la API de Claude. Si no guardas ninguna, se usa la variable de entorno ANTHROPIC_API_KEY.<br><br>"
            "<b>Privacidad y coste:</b> a Anthropic se envían tus mensajes y una foto del estado de la app "
            "(conexión, telemetría y últimas líneas de la consola). Cada pregunta consume tokens de la API, "
            "que se facturan a la cuenta de la clave.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        info.setOpenExternalLinks(True)
        lay.addWidget(info)
        buttons = QHBoxLayout()
        clear = QPushButton("Borrar la clave guardada")
        clear.setObjectName("ghost")
        clear.clicked.connect(self._clear)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Guardar")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)
        ctx = getattr(parent, "ctx", None)
        if ctx is not None:
            style_titlebar(self, ctx.theme)

    def _clear(self) -> None:
        self.cleared = True
        self.key.clear()
        self.accept()


class AssistantPanel(BasePage):
    title = "Asistente IA"
    icon = "sparkles"
    close_requested = Signal()

    def __init__(self, ctx):
        super().__init__(ctx)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.setMinimumWidth(360)
        self.assistant = Assistant(ctx.catalog, self._state_for_assistant, self._saved_key())
        self.bridge = _Bridge()
        self.bridge.text.connect(self._on_text)
        self.bridge.activity.connect(self._on_activity)
        self.bridge.proposal.connect(self._on_proposal)
        self.bridge.done.connect(self._on_done)
        self._worker: threading.Thread | None = None
        self._snapshot: dict = {}
        self._console: deque[str] = deque(maxlen=20)
        self._telemetry: dict[str, float] = {}
        self._notes: list[str] = []
        self._bubble: QLabel | None = None
        self._bubble_text = ""
        self._thinking: QLabel | None = None
        self._dots = 0
        self._last_input = ""
        self._exec: dict | None = None  # propuesta en ejecución

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(2)
        self.title_icon = QLabel()
        head.addWidget(self.title_icon)
        model_lbl = QLabel(" Claude · propone, tú ejecutas")
        model_lbl.setObjectName("muted")
        head.addWidget(model_lbl)
        head.addStretch(1)
        key_btn = self.button("", "key", "ghost", "Clave de API de Claude y privacidad")
        key_btn.clicked.connect(self.edit_key)
        new_btn = self.button("", "trash", "ghost", "Nueva conversación (borra el historial)")
        new_btn.clicked.connect(self.new_conversation)
        for b in (key_btn, new_btn):
            head.addWidget(b)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.chat = QVBoxLayout(body)
        self.chat.setContentsMargins(0, 0, 6, 0)
        self.chat.setSpacing(10)
        self.chat.addStretch(1)
        self.scroll.setWidget(body)
        body.setAutoFillBackground(False)
        self.scroll.viewport().setAutoFillBackground(False)
        lay.addWidget(self.scroll, 1)
        self._welcome()

        self.input = _Input()
        self.input.setPlaceholderText("Pregunta o pide algo…  (Enter envía · Mayús+Enter: nueva línea)")
        self.input.setFixedHeight(64)
        self.input.submitted.connect(self.send)
        lay.addWidget(self.input)
        row = QHBoxLayout()
        self.footer = ElidedLabel(f"{MODEL_LABEL} · tú confirmas cada comando")
        self.footer.setObjectName("muted")
        self.footer.setToolTip("Nada se envía a la mano sin que pulses Ejecutar")
        row.addWidget(self.footer, 1)
        self.send_btn = self.button("Enviar", "send", "primary")
        self.send_btn.clicked.connect(self._send_or_stop)
        row.addWidget(self.send_btn)
        lay.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._snap_timer = QTimer(self)
        self._snap_timer.setInterval(500)
        self._snap_timer.timeout.connect(self._update_snapshot)
        self._snap_timer.start()
        ctx.catalog_reloaded.connect(self.assistant.refresh_catalog)
        self.on_theme_changed(ctx.theme)
        self._update_snapshot()

    # ------------------------------------------------------------ clave
    def _saved_key(self) -> str | None:
        token = self.settings.value("assistant_key", "")
        if not token:
            return None
        try:
            return unprotect(token)
        except (OSError, ValueError):
            return None

    def _key_source(self) -> str:
        import os
        if self._saved_key():
            return "Ahora se usa la clave guardada en la app."
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "Ahora se usa la variable de entorno ANTHROPIC_API_KEY."
        return "Todavía no hay ninguna clave configurada."

    def edit_key(self) -> None:
        dialog = KeyDialog(self.window(), self._key_source())
        if not dialog.exec():
            return
        if dialog.cleared:
            self.settings.remove("assistant_key")
            self.assistant.set_api_key(None)
            self.ctx.notify("Asistente IA: clave borrada.")
            return
        key = dialog.key.text().strip()
        if key:
            try:
                self.settings.setValue("assistant_key", protect(key))
            except OSError as error:
                self.ctx.notify(f"No se pudo guardar la clave: {error}", error=True)
                return
            self.assistant.set_api_key(key)
            self.ctx.notify("Asistente IA: clave guardada (cifrada para tu usuario de Windows).", toast=True)

    # ------------------------------------------------------------ conversación
    def _welcome(self) -> None:
        self.welcome = QWidget()
        wl = QVBoxLayout(self.welcome)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(8)
        hello = QLabel("Pregúntame por la mano, la app o un error, o pídeme que la mueva: te propondré los "
                       "comandos y tú decides si se ejecutan.")
        hello.setObjectName("muted")
        hello.setWordWrap(True)
        wl.addWidget(hello)
        for text in SUGGESTIONS:
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setStyleSheet("text-align: left;")
            b.clicked.connect(lambda _c=False, t=text: self.ask(t))
            wl.addWidget(b)
        self.chat.insertWidget(self.chat.count() - 1, self.welcome)

    def new_conversation(self) -> None:
        if self.busy:
            return
        self.assistant.reset()
        self._notes.clear()
        while self.chat.count() > 1:
            item = self.chat.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._bubble = None
        self._thinking = None
        self._welcome()

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def focus_input(self) -> None:
        self.input.setFocus()

    def ask(self, text: str) -> None:
        self.input.setPlainText(text)
        self.send()

    def _send_or_stop(self) -> None:
        if self.busy:
            self.assistant.cancel.set()
        else:
            self.send()

    def send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or self.busy:
            return
        self._last_input = text
        self.input.clear()
        if self.welcome is not None:
            self.welcome.deleteLater()
            self.welcome = None
        self._add_label(text, "userBubble", Qt.AlignRight)
        payload = text
        if self._notes:  # lo que pasó desde el último mensaje (propuestas ejecutadas o descartadas)
            payload = "[Nota de la app: " + " ".join(self._notes) + "]\n\n" + text
            self._notes.clear()
        self._bubble = None
        self._show_thinking("Pensando")
        self._set_busy(True)
        self._update_snapshot()
        relay = _Relay(self.bridge)

        def work():
            try:
                status = self.assistant.run_turn(payload, relay)
                self.bridge.done.emit(status, "")
            except AssistantError as error:
                self.bridge.done.emit("error", str(error))
            except Exception as error:  # noqa: BLE001  (que un fallo inesperado no deje el panel bloqueado)
                self.bridge.done.emit("error", f"Error inesperado del asistente: {error}")

        self._worker = threading.Thread(target=work, name="asistente-ia", daemon=True)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.send_btn.setText("  Detener" if busy else "  Enviar")
        for i, (btn, name, color) in enumerate(self._icon_buttons):
            if btn is self.send_btn:
                self._icon_buttons[i] = (btn, "stop" if busy else "send", color)
        self._paint_icons()

    # --- lo que llega del hilo del asistente
    def _on_text(self, delta: str) -> None:
        self._hide_thinking()
        if self._bubble is None:
            self._bubble = self._add_label("", "botBubble", Qt.AlignLeft, markdown=True)
            self._bubble_text = ""
        self._bubble_text += delta
        self._dirty = True

    def _on_activity(self, text: str) -> None:
        self._flush()
        self._bubble = None
        self._show_thinking(text.rstrip("…"))

    def _on_proposal(self, proposal: Proposal) -> None:
        self._flush()
        self._hide_thinking()
        self._bubble = None
        card = ProposalCard(self, proposal)
        self._insert(card)
        self._show_thinking("Pensando")

    def _on_done(self, status: str, error: str) -> None:
        self._flush()
        self._hide_thinking()
        self._bubble = None
        self._set_busy(False)
        if status == "cancelled":
            self._add_label("Respuesta detenida.", "muted", Qt.AlignLeft)
        elif status == "refusal":
            self._add_label("Claude no puede ayudar con esa petición. Prueba a formularla de otra manera.",
                            "errorBubble", Qt.AlignLeft)
        elif status == "error":
            self._add_label(error, "errorBubble", Qt.AlignLeft)
            if not self.input.toPlainText().strip():
                self.input.setPlainText(self._last_input)  # para reintentar con un clic
        self.input.setFocus()

    # --- dibujo
    def _insert(self, widget: QWidget, align=None) -> None:
        if align is None:
            self.chat.insertWidget(self.chat.count() - 1, widget)
        else:
            self.chat.insertWidget(self.chat.count() - 1, widget, 0, align)
        QTimer.singleShot(0, self._scroll_to_end)

    def _add_label(self, text: str, name: str, align, markdown: bool = False) -> QLabel:
        label = QLabel()
        label.setObjectName(name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        label.setOpenExternalLinks(True)
        label.setTextFormat(Qt.MarkdownText if markdown else Qt.PlainText)
        label.setText(text)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        if name == "userBubble":  # a la derecha y sin ocupar todo el ancho, como en cualquier chat
            label.setMaximumWidth(int(self.width() * 0.85) if self.width() > 200 else 320)
            self._insert(label, Qt.AlignRight)
        else:
            self._insert(label)
        return label

    def _show_thinking(self, text: str) -> None:
        self._hide_thinking()
        self._thinking_text = text
        self._thinking = QLabel(text + "…")
        self._thinking.setObjectName("thinking")
        self._insert(self._thinking)

    def _hide_thinking(self) -> None:
        if self._thinking is not None:
            self._thinking.deleteLater()
            self._thinking = None

    _dirty = False

    def _flush(self) -> None:
        if self._dirty and self._bubble is not None:
            self._bubble.setText(self._bubble_text)
            self._dirty = False
            QTimer.singleShot(0, self._scroll_to_end)

    def _tick(self) -> None:
        self._flush()
        if self._thinking is not None:
            self._dots = (self._dots + 1) % 12
            self._thinking.setText(self._thinking_text + "." * (1 + self._dots // 4))

    def _scroll_to_end(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------- ejecutar propuestas
    def dismiss(self, card: ProposalCard) -> None:
        card.finish("Descartada.")
        self._notes.append(f"El usuario descartó la propuesta «{card.proposal.explanation}».")

    def execute(self, card: ProposalCard) -> None:
        if self._exec is not None:
            self.ctx.notify("Espera a que termine la propuesta que se está ejecutando.", error=True)
            return
        if not self.ctx.connected:
            card.set_status("Conecta primero la mano o la simulación.", "error")
            return
        card.run_btn.setEnabled(False)
        card.skip_btn.setEnabled(False)
        self._exec = {"card": card, "i": 0, "log": []}
        self._next_step()

    def _next_step(self) -> None:
        ex = self._exec
        if ex is None:
            return
        card, steps = ex["card"], ex["card"].proposal.steps
        if ex["i"] >= len(steps):
            QTimer.singleShot(400, lambda: self._finish_exec(True, ""))  # deja llegar el último ACK
            return
        cmd, wait = steps[ex["i"]]
        card.set_status(f"Ejecutando {ex['i'] + 1}/{len(steps)}: {cmd}")
        ex["own"] = True
        ok = self.ctx.send_command(cmd)
        ex["own"] = False
        if not ok:
            self._finish_exec(False, f"no se pudo enviar {cmd}")
            return
        ex["i"] += 1
        QTimer.singleShot(max(wait, MIN_GAP_MS), self._next_step)

    def _finish_exec(self, ok: bool, why: str) -> None:
        ex, self._exec = self._exec, None
        if ex is None:
            return
        card = ex["card"]
        replies = "; ".join(ex["log"][-8:]) or "sin respuestas registradas"
        if ok:
            card.finish("Ejecutada ✓", "ok")
            self._notes.append(f"El usuario ejecutó la propuesta «{card.proposal.explanation}». "
                               f"Respuestas de la mano: {replies}.")
        else:
            done = ex["i"]
            card.finish(f"Interrumpida: {why} (pasos enviados: {done}).", "error")
            self._notes.append(f"La propuesta «{card.proposal.explanation}» se interrumpió ({why}) tras "
                               f"{done} pasos. Respuestas: {replies}.")

    # ------------------------------------------------ estado para el asistente
    def on_message(self, msg) -> None:
        kind = msg.kind
        if kind is MessageKind.DATA:
            self._telemetry = dict(msg.values)
            return
        if kind is MessageKind.EMG:
            return
        label = {"ERR": "ERR", "TX": "TX", "ACK": "ACK", "BRIDGE": "PUENTE", "TEXT": "RX", "SYSTEM": "APP"}
        self._console.append(f"{msg.timestamp.strftime('%H:%M:%S')} {label.get(kind.value, kind.value)} {msg.text}")
        ex = self._exec
        if ex is not None:
            if kind in (MessageKind.ACK, MessageKind.ERROR):
                ex["log"].append(f"{kind.value} {msg.text}")
            elif kind is MessageKind.TX and msg.text == "PARAR" and not ex.get("own"):
                self._finish_exec(False, "se pulsó Parar")

    def on_connection_changed(self, connected: bool, info: str) -> None:
        if not connected and self._exec is not None:
            self._finish_exec(False, "se desconectó la mano")

    def _update_snapshot(self) -> None:
        """Foto del estado (en el hilo de la interfaz); el hilo del asistente solo lee la última."""
        ctx = self.ctx
        if ctx.replaying:
            conn = "reproduciendo una sesión grabada (no se pueden enviar comandos)"
        elif ctx.connected:
            conn = "simulación" if ctx.link.port_name == SIMULATOR_PORT else f"mano real por {ctx.link.port_name}"
        else:
            conn = "desconectado"
        g = ctx.gesture
        active = f"{g} · {GESTOS[g - 1].nombre}" if 1 <= g <= len(GESTOS) else "ninguno (posición personalizada)"
        posture = None
        if ctx.posture:
            i = ctx.postures.find_spec(ctx.posture)
            posture = f"{ctx.posture}" + (f" ({ctx.postures.items[i].nombre})" if i >= 0 else "")
        self._snapshot = {
            "hora": time.strftime("%H:%M:%S"),
            "conexion": conn,
            "modo_elegido": "simulación" if ctx.simulated else "mano real",
            "estado_mano": {"online": "en línea", "silent": "sin respuesta", "offline": "sin conexión"}.get(
                ctx.hand_status, ctx.hand_status),
            "telemetria_hz": round(ctx.data_rate),
            "modo_mano": ctx.mode or "desconocido",
            "gesto_activo": active,
            "postura_personalizada_activa": posture,
            "ultima_telemetria": self._telemetry,
            "latencia_ms": ({"ultima": round(ctx.latencies[-1]), "media": round(ctx.avg_latency)}
                            if ctx.latencies else None),
            "posturas_personalizadas": [{"nombre": p.nombre, "comando": posture_command(p)}
                                        for p in ctx.postures.items],
            "grabando_sesion": ctx.recording,
            "ultimas_lineas_consola": list(self._console),
        }

    def _state_for_assistant(self) -> dict:
        return dict(self._snapshot)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_warmed", False):  # la 1.ª importación del SDK tarda ~1 s: se adelanta en segundo plano
            self._warmed = True
            threading.Thread(target=self._warm_up, name="importar-anthropic", daemon=True).start()

    @staticmethod
    def _warm_up() -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            pass

    # ------------------------------------------------------------ tema
    def on_theme_changed(self, theme: str) -> None:
        p = PALETTES[theme]
        self.title_icon.setPixmap(icon("sparkles", p["accent_text"], 16).pixmap(16, 16))
