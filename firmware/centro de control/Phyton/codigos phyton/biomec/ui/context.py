"""Contexto compartido: lo único que las páginas necesitan conocer.

Las páginas NO se importan entre sí. Se comunican a través de este objeto:
  - ctx.send_command("DEDO INDICE CERRAR")   valida y envía
  - ctx.message                    señal con cada Message (RX, TX, errores...)
  - ctx.connection_changed         señal (conectado, descripción)
  - ctx.theme_changed              señal (nombre del tema)
  - ctx.prefill_command            pedir a la consola que escriba un comando
  - ctx.catalog_reloaded           se ha vuelto a leer commands.json
  - ctx.latency_measured           (ms, comando): tiempo hasta la respuesta
  - ctx.hand_status_changed        ("offline" | "silent" | "online", Hz de telemetría)
  - ctx.hand_state_changed         gesto activo (0 = ninguno) y modo (AUTO/MANUAL);
                                   ctx.posture = postura personalizada activa ('C A C 90')
  - ctx.postures / postures_changed  posturas personalizadas del usuario
  - ctx.recording_changed          se empieza / termina de grabar una sesión
  - ctx.replay_changed             se empieza / termina de reproducir una sesión
  - ctx.simulated / sim_mode_changed  modo Simulación elegido en el panel Dispositivo
  - ctx.emg_receiver               receptor EMG del equipo por USB (Visor EMG): su señal llega por ctx.message
                                   como la del puente
  - ctx.analyze_emg_file           pedir al Analizador EMG que abra y analice un CSV (lo usa el Visor EMG)

Latencia: se mide desde que la app envía un comando hasta que llega su
respuesta (ACK/ERR de la mano, o BRIDGE para los comandos @ del puente).
Es solo la parte de comunicación del retardo total; como referencia, Farrell
y Weir (2007, IEEE TNSRE 15(1):111-118) sitúan el retardo óptimo del control
completo de una prótesis mioeléctrica en 100-125 ms.
"""

import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.commands import CommandCatalog, CommandError
from ..core.emg_receiver import EmgReceiver
from ..core.gestures import GESTOS
from ..core.postures import PostureStore, spec_from_ack
from ..core.protocol import Message, MessageKind
from ..core.serial_link import SerialLink
from ..core.session import SessionRecorder
from ..core.signals import DEFAULT_CLOSE_TIME_S, SignalCatalog, SignalStore
from ..paths import config_file, user_data_dir

LATENCY_GOOD_MS = 100    # por debajo: verde
LATENCY_LIMIT_MS = 125   # por encima: rojo (entre ambos: ámbar)


def latency_level(ms: float) -> str:
    """Clave de color de la paleta para una latencia: ok / warn / error."""
    return "ok" if ms < LATENCY_GOOD_MS else "warn" if ms <= LATENCY_LIMIT_MS else "error"


def _close_time_s() -> float:
    """Tiempo que tarda un dedo en cerrarse (config/mano3d.json), para estimar el % cerrado sin sensor."""
    try:
        import json
        return float(json.loads(config_file("mano3d.json").read_text(encoding="utf-8")).get("tiempo_cierre_s",
                                                                                              DEFAULT_CLOSE_TIME_S))
    except (OSError, ValueError, TypeError):
        return DEFAULT_CLOSE_TIME_S


class AppContext(QObject):
    message = Signal(object)
    connection_changed = Signal(bool, str)
    theme_changed = Signal(str)
    prefill_command = Signal(str)
    catalog_reloaded = Signal()
    latency_measured = Signal(float, str)
    hand_status_changed = Signal(str, float)
    hand_state_changed = Signal(int, str)
    postures_changed = Signal()
    recording_changed = Signal(bool)
    sim_mode_changed = Signal(bool)
    toast = Signal(str, str)  # aviso flotante: (texto, "ok" | "info")
    replay_changed = Signal(bool)
    analyze_emg_file = Signal(str)

    def __init__(self, link: SerialLink, catalog: CommandCatalog, theme: str = "dark",
                 postures_path: str | Path | None = None):
        super().__init__()
        self.link = link
        self.catalog = catalog
        self.theme = theme
        self.auto_telemetry = True  # al conectar se envía STREAM 1 (el gemelo y las gráficas la necesitan)
        self.postures = PostureStore(postures_path or user_data_dir() / "posturas.json")
        self.recorder: SessionRecorder | None = None
        self.replaying = False
        self.simulated = False  # modo elegido en el panel Dispositivo (lo fija la ventana)
        self.time_scale = 1.0  # velocidad de la reproducción (el gemelo integra el tiempo de la grabación)
        # Señales graficables (compartidas por todas las ventanas de Gráficas)
        self.signals = SignalStore(SignalCatalog(config_file("signals.json")), close_time_s=_close_time_s(),
                                   time_scale=lambda: self.time_scale)

        self.latencies: deque[float] = deque(maxlen=30)
        self._pending: deque[tuple[float, str]] = deque()
        self._data_times: deque[float] = deque(maxlen=400)
        self._last_hand = 0.0
        self.hand_status, self.data_rate = "offline", 0.0
        self.gesture, self.mode, self.posture = 0, "", ""

        link.message_received.connect(self._track)
        link.message_received.connect(self.message)
        link.connection_changed.connect(self._on_connection)
        link.connection_changed.connect(self.connection_changed)
        # receptor EMG del equipo (segundo puerto USB): su señal entra por el mismo camino que la del puente
        self.emg_receiver = EmgReceiver(self)
        self.emg_receiver.message_received.connect(self.message)
        self.emg_receiver.notice.connect(self._receiver_notice)
        self.message.connect(self._record)
        self.message.connect(self.signals.on_message)
        self.replay_changed.connect(lambda _r: self.signals.clear())  # el tiempo de las gráficas empieza de cero

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._update_hand_status)
        self._status_timer.start()

    # ------------------------------------------------------------- envío
    @property
    def connected(self) -> bool:
        return self.link.is_connected

    def send_command(self, text: str) -> bool:
        if self._blocked():
            return False
        try:
            _cmd, line = self.catalog.build(text)
        except CommandError as error:
            self.notify(str(error), error=True)
            return False
        return self.link.send_line(line)

    def send_raw(self, line: str) -> bool:
        """Envía sin validar contra el catálogo (modo avanzado / pruebas)."""
        if self._blocked():
            return False
        return self.link.send_line(line)

    def _blocked(self) -> bool:
        if self.replaying:
            self.notify("Se está reproduciendo una sesión grabada: ciérrala para enviar comandos.", error=True)
            return True
        return False

    def reload_catalog(self) -> None:
        try:
            self.catalog.reload()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.notify(f"Error leyendo {self.catalog.path.name}: {error}", error=True)
            return
        self.catalog_reloaded.emit()
        self.notify(f"Catálogo recargado: {len(self.catalog.names())} comandos.")

    def notify(self, text: str, error: bool = False, toast: bool = False) -> None:
        """Mensaje para el usuario: va a la consola y la barra de estado. Los errores salen además como
        aviso flotante; toast=True hace lo mismo con una confirmación importante (sesión guardada…)."""
        self.message.emit(Message(MessageKind.ERROR if error else MessageKind.SYSTEM, text))
        if toast and not error:
            self.toast.emit(text, "ok")

    def _receiver_notice(self, kind: str, text: str) -> None:
        """Avisos del receptor EMG (llegan desde su hilo; Qt los entrega aquí, en el de la interfaz)."""
        self.notify(text, error=kind == "error")

    def set_simulated(self, simulated: bool) -> None:
        if simulated != self.simulated:
            self.simulated = simulated
            self.sim_mode_changed.emit(simulated)

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.theme_changed.emit(theme)

    @property
    def avg_latency(self) -> float | None:
        return sum(self.latencies) / len(self.latencies) if self.latencies else None

    # ------------------------------------------------------ grabar sesiones
    @property
    def recording(self) -> bool:
        return self.recorder is not None

    def start_recording(self, path: str | Path, meta: dict | None = None) -> bool:
        if self.recorder is not None:
            return False
        try:
            self.recorder = SessionRecorder(path, meta)
        except OSError as error:
            self.notify(f"No se pudo crear la grabación: {error}", error=True)
            return False
        self.recording_changed.emit(True)
        self.notify(f"Grabando la sesión en {Path(path).name}…")
        return True

    def stop_recording(self) -> SessionRecorder | None:
        rec, self.recorder = self.recorder, None
        if rec is None:
            return None
        rec.close()
        self.recording_changed.emit(False)
        self.notify(f"Sesión guardada: {rec.path.name}  ({rec.count} mensajes, {rec.elapsed:.0f} s)", toast=True)
        return rec

    def _record(self, msg: Message) -> None:
        if self.recorder is not None and not self.replaying:
            self.recorder.write(msg)

    # ------------------------------------------------- reproducir sesiones
    def set_replaying(self, replaying: bool) -> None:
        if replaying == self.replaying:
            return
        self.replaying = replaying
        self._pending.clear()
        self._data_times.clear()
        self._last_hand = 0.0
        self._set_hand_state(0, "", "")
        self.replay_changed.emit(replaying)
        self._update_hand_status()

    def inject(self, msg: Message) -> None:
        """Mensaje de una sesión grabada: llega a todas las páginas como si viniera de la mano."""
        self._track(msg)
        self.message.emit(msg)

    # ------------------------------------------------- seguimiento de mensajes
    def _on_connection(self, connected: bool, _info: str) -> None:
        self._pending.clear()
        self._data_times.clear()
        self._last_hand = 0.0
        if connected and self.auto_telemetry:
            QTimer.singleShot(400, lambda: self.connected and self.send_command("STREAM 1"))
        if not connected:
            self._set_hand_state(0, "", "")
        self._update_hand_status()

    def _track(self, msg: Message) -> None:
        now = time.monotonic()
        kind = msg.kind
        if kind is MessageKind.TX:
            if not self.replaying:  # en una reproducción no se mide la latencia: sería la del pasado
                while self._pending and now - self._pending[0][0] > 3.0:  # sin respuesta: se descarta
                    self._pending.popleft()
                self._pending.append((now, msg.text))
            return

        is_bridge_reply = kind is MessageKind.BRIDGE and self._pending and self._pending[0][1].startswith("@")
        is_hand_reply = kind in (MessageKind.ACK, MessageKind.ERROR) and self._pending \
            and not self._pending[0][1].startswith("@")
        if is_bridge_reply or is_hand_reply:
            sent_at, text = self._pending.popleft()
            ms = (now - sent_at) * 1000
            self.latencies.append(ms)
            self.latency_measured.emit(ms, text)

        if kind in (MessageKind.DATA, MessageKind.ACK, MessageKind.TEXT) or is_hand_reply:
            self._last_hand = now
        if kind is MessageKind.DATA:
            self._data_times.append(now)
            if "gesto" in msg.values:
                gesture = int(msg.values["gesto"])
                self._set_hand_state(gesture, self.mode, self.posture if gesture == 0 else "")
        elif kind is MessageKind.ACK:
            self._state_from_ack(msg.text)

    def _state_from_ack(self, text: str) -> None:
        head, _, rest = text.partition(" ")
        head = head.upper()
        gesture, mode, posture = self.gesture, self.mode, self.posture
        if head == "GESTO":
            try:
                gesture = int(rest.split()[0])
            except (IndexError, ValueError):
                pass
            mode, posture = "MANUAL", ""
        elif head == "ABRIR":
            gesture, mode, posture = 1, "MANUAL", ""
        elif head == "CERRAR":
            gesture, mode, posture = len(GESTOS), "MANUAL", ""
        elif head == "POSTURA":
            spec = spec_from_ack(text) or ""
            # la mano informa como gesto de fábrica si la postura coincide con uno
            gesture, mode, posture = 0, "MANUAL", spec
        elif head in ("DEDO", "PULGAR"):
            gesture, mode, posture = 0, "MANUAL", ""
        elif head in ("PARAR", "MANUAL"):
            mode = "MANUAL"
        elif head == "AUTO":
            mode, posture = "AUTO", ""
        elif head == "ESTADO":
            fields = dict(tok.split("=", 1) for tok in rest.split() if "=" in tok)
            mode = fields.get("modo", mode)
            raw = fields.get("gesto", "0")
            if raw.isdigit():
                gesture = int(raw)
            else:  # firmware antiguo: enviaba el nombre
                names = [g.nombre for g in GESTOS]
                gesture = names.index(raw) + 1 if raw in names else 0
            if gesture:
                posture = ""
        self._set_hand_state(gesture, mode, posture)

    def _set_hand_state(self, gesture: int, mode: str, posture: str = "") -> None:
        if (gesture, mode, posture) != (self.gesture, self.mode, self.posture):
            self.gesture, self.mode, self.posture = gesture, mode, posture
            self.hand_state_changed.emit(gesture, mode)

    def _update_hand_status(self) -> None:
        now = time.monotonic()
        rate = float(sum(1 for t in self._data_times if now - t <= 1.0))
        if not (self.connected or self.replaying):
            status = "offline"
        elif self._last_hand and now - self._last_hand < (1.5 if rate else 5.0):
            status = "online"
        else:
            status = "silent"
        if (status, round(rate)) != (self.hand_status, round(self.data_rate)):
            self.hand_status, self.data_rate = status, rate
            self.hand_status_changed.emit(status, rate)
