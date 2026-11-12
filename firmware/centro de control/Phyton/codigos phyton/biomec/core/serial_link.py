"""Conexión USB-serie con la ESP32-C6 puente.

La lectura se hace en un hilo aparte para que la interfaz nunca se congele,
aunque la mano envíe telemetría a mucha frecuencia. Todo lo que pasa se
comunica con señales Qt, así que la interfaz no necesita saber nada de pyserial.

Por el mismo USB pueden llegar líneas de texto (la mano y el puente) y marcos
binarios AA 55 con la señal de la placa EMG (si está encendida). Los marcos se
separan antes de partir el texto en líneas, así que da igual conectar aquí el
puente (con o sin placa EMG) o el receptor EMG del equipo.
"""

import threading

import serial
from serial.tools import list_ports
from PySide6.QtCore import QObject, QTimer, Signal

from .emg_receiver import FrameStream
from .protocol import Message, MessageKind, parse_line
from .simulator import SIMULATOR_PORT, SimulatedSerial

PING_WAIT_MS = 2500     # tras un comando, cuánto se espera alguna línea de texto antes de preguntar al puente


def available_ports() -> list[tuple[str, str]]:
    """Puertos COM reales: [(dispositivo, descripción), ...] p. ej. [('COM7', 'Dispositivo serie USB')].

    El simulador no es un puerto: se elige con el selector "Simulación" de la barra
    de conexión, que conecta a SIMULATOR_PORT.
    """
    return [(p.device, p.description) for p in list_ports.comports()]


class SerialLink(QObject):
    message_received = Signal(object)      # Message
    connection_changed = Signal(bool, str)  # conectado, descripción
    _lost = Signal()                        # interno: el hilo avisa al hilo principal

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._lost.connect(self.disconnect)  # se ejecuta en el hilo principal
        self.frames = FrameStream("conexion")   # EMG en marcos AA 55 que llegue por esta conexión
        self._text_seen = False                 # ha llegado alguna línea de texto desde que se conectó
        self._emg_announced = False
        self._probe = 0                         # 0 nada, 1 esperando a que conteste algo, 2 ya avisado
        self._ping_timer = self._single_shot(PING_WAIT_MS, self._probe_bridge)
        self._answer_timer = self._single_shot(1200, self._probe_result)

    def _single_shot(self, ms: int, slot) -> QTimer:
        timer = QTimer(self)        # hijo de la conexión: se destruye con ella aunque esté pendiente
        timer.setSingleShot(True)
        timer.setInterval(ms)
        timer.timeout.connect(slot)
        return timer

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def port_name(self) -> str:
        return self._serial.port if self._serial else ""

    # ------------------------------------------------------------- conexión
    def connect(self, port: str, baudrate: int) -> None:
        self.disconnect()
        try:
            if port == SIMULATOR_PORT:
                self._serial = SimulatedSerial(timeout=0.05)
            else:
                self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=0.05, write_timeout=1)
        except (serial.SerialException, OSError) as error:
            self._serial = None
            self._system(f"No se pudo abrir {port}: {error}", error=True)
            self.connection_changed.emit(False, "")
            return

        self.frames.reset()
        self._text_seen = False
        self._emg_announced = False
        self._probe = 0
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, name="serial-rx", daemon=True)
        self._thread.start()
        self._system(f"Conectado a {port} ({baudrate} baudios).")
        self.connection_changed.emit(True, f"{port} · {baudrate}")

    def disconnect(self) -> None:
        if self._serial is None:
            return
        self._ping_timer.stop()
        self._answer_timer.stop()
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        port = self._serial.port
        try:
            self._serial.close()
        except (serial.SerialException, OSError):
            pass
        self._serial = None
        self._thread = None
        self._system(f"Desconectado de {port}.")
        self.connection_changed.emit(False, "")

    # ---------------------------------------------------------------- envío
    def send_line(self, line: str) -> bool:
        if not self.is_connected:
            self._system("No hay conexión: conecta primero con la ESP32 puente.", error=True)
            return False
        try:
            with self._write_lock:
                self._serial.write((line.strip() + "\n").encode("utf-8"))
        except (serial.SerialException, OSError) as error:
            self._system(f"Error al enviar: {error}", error=True)
            self.disconnect()
            return False
        self.message_received.emit(Message(MessageKind.TX, line.strip()))
        if not self._text_seen and self._probe == 0:
            self._probe = 1
            self._ping_timer.start()
        return True

    # ------------------------------------------------- ¿puente o solo receptor?
    # El receptor EMG del equipo (firmware/maestro) manda marcos AA 55 pero no lee el USB: los comandos no
    # llegan a la mano. Si tras un comando solo hay marcos y ni una línea de texto, se pregunta @PING sin
    # dejar rastro; el puente contesta «BRIDGE PONG» aunque la mano esté apagada, el receptor no.
    def _probe_bridge(self) -> None:
        if self._text_seen or not self.is_connected or self.frames.frames == 0:
            self._probe = 0
            return
        try:
            with self._write_lock:
                self._serial.write(b"@PING\n")
        except (serial.SerialException, OSError, AttributeError):
            self._probe = 0
            return
        self._answer_timer.start()

    def _probe_result(self) -> None:
        if self._text_seen or not self.is_connected:
            self._probe = 0
            return
        self._probe = 2
        self._system(f"{self.port_name} manda EMG del sensor pero no contesta a los comandos: es una C6 con el "
                     f"firmware del receptor del equipo, que no habla con la mano. Para mover la mano con esta "
                     f"misma C6, súbele el firmware del puente: firmware/puente_pc (en el repositorio del "
                     f"equipo, maestro/c6), entorno c6zero si es la C6-Zero del receptor. Hace de puente y de "
                     f"receptor a la vez.", error=True)

    # -------------------------------------------------------------- lectura
    def _read_loop(self) -> None:
        buffer = b""
        while not self._stop.is_set():
            try:
                chunk = self._serial.read(self._serial.in_waiting or 1)
            except (serial.SerialException, OSError, AttributeError, TypeError) as error:
                if not self._stop.is_set():
                    self._system(f"Conexión perdida: {error}", error=True)
                    self._lost.emit()
                return
            if not chunk:
                continue
            emg, text = self.frames.split(chunk)
            if emg and not self._emg_announced:
                self._emg_announced = True
                self._system(f"Llega EMG del sensor por {self.port_name}: se ve en el Visor EMG (Ctrl+6), "
                             f"Entrenamiento y Gráficas.")
            for message in emg:
                self.message_received.emit(message)
            if not text:
                continue
            buffer += text
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self._text_seen = True
                    self.message_received.emit(parse_line(line))
            if len(buffer) > 4096:  # línea sin fin: se vuelca para no crecer sin límite
                self.message_received.emit(parse_line(buffer.decode("utf-8", errors="replace")))
                buffer = b""

    def _system(self, text: str, error: bool = False) -> None:
        kind = MessageKind.ERROR if error else MessageKind.SYSTEM
        self.message_received.emit(Message(kind, text))
