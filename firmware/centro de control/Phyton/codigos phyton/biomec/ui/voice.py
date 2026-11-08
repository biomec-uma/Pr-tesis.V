"""Control por voz en la interfaz: micrófono → Vosk (en un hilo) → acciones de la app.

    micrófono (QtMultimedia) ──PCM──► cola ──► hilo: VoiceRecognizer ──► señales Qt ──► ventana
                                                     (core/voice.py)        heard / partial

El reconocimiento es local (sin internet). La ventana decide qué hacer con cada
orden oída (enviar un comando, cambiar de pestaña…) y la enseña en un aviso.
"""

import queue
import threading

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..core.gestures import GESTOS
from ..core.voice import VoiceRecognizer, build_phrases, download_model, interpret, model_dir, model_ready
from ..paths import user_data_dir


def to_int16_mono(data: bytes, sample_format, channels: int) -> bytes:
    """Cualquier formato del micrófono -> PCM 16 bits mono (lo que espera Vosk)."""
    from PySide6.QtMultimedia import QAudioFormat
    if sample_format == QAudioFormat.Int16:
        a = np.frombuffer(data[: len(data) // 2 * 2], np.int16).astype(np.float32)
    elif sample_format == QAudioFormat.Int32:
        a = np.frombuffer(data[: len(data) // 4 * 4], np.int32).astype(np.float32) / 65536
    elif sample_format == QAudioFormat.Float:
        a = np.frombuffer(data[: len(data) // 4 * 4], np.float32) * 32767
    else:  # UInt8
        a = (np.frombuffer(data, np.uint8).astype(np.float32) - 128) * 256
    if channels > 1:
        a = a[: len(a) // channels * channels].reshape(-1, channels).mean(axis=1)
    return np.clip(a, -32768, 32767).astype(np.int16).tobytes()


class VoiceController(QObject):
    listening_changed = Signal(bool)
    ready = Signal()                 # modelo cargado: ya se puede hablar
    partial = Signal(str)            # lo que se va oyendo
    heard = Signal(object)           # core.voice.Heard
    error = Signal(str)
    download_progress = Signal(int, int)
    download_done = Signal(str)      # "" si fue bien; si no, el error

    def __init__(self, ctx, pages: list[str]):
        super().__init__()
        self.ctx = ctx
        self.pages = pages
        self.root = user_data_dir() / "voz"
        self.listening = False
        self.table: dict = {}
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._source = None
        self._io = None
        self._fmt = None
        self._cancel_download = False
        ctx.postures_changed.connect(self._update_grammar)

    # ----------------------------------------------------------- modelo
    @property
    def model_ready(self) -> bool:
        return model_ready(self.root)

    def download(self) -> None:
        """Descarga el modelo en segundo plano (download_progress / download_done)."""
        self._cancel_download = False

        def work():
            try:
                download_model(self.root, lambda d, t: self.download_progress.emit(d, t),
                               lambda: self._cancel_download)
                self.download_done.emit("")
            except Exception as error:  # noqa: BLE001  (red, disco, zip…: se le enseña al usuario)
                self.download_done.emit(str(error))

        threading.Thread(target=work, name="descarga-voz", daemon=True).start()

    def cancel_download(self) -> None:
        self._cancel_download = True

    # ---------------------------------------------------------- escuchar
    def _phrases(self) -> list[str]:
        self.table = build_phrases(GESTOS, self.ctx.postures.items, self.pages)
        return [spoken for spoken, _action in self.table.values()]

    def start(self, use_microphone: bool = True) -> bool:
        if self.listening:
            return True
        if not self.model_ready:
            self.error.emit("Falta el modelo de voz: descárgalo primero.")
            return False
        rate = 16000
        if use_microphone:
            rate = self._open_microphone()
            if not rate:
                return False
        phrases = self._phrases()
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, args=(phrases, rate), name="voz", daemon=True)
        self._thread.start()
        self.listening = True
        self.listening_changed.emit(True)
        return True

    def stop(self) -> None:
        if self._source is not None:
            self._source.stop()
            self._source.deleteLater()
        self._source = self._io = None
        self._queue.put(None)
        if self.listening:
            self.listening = False
            self.listening_changed.emit(False)

    def _open_microphone(self) -> int:
        """Abre el micrófono por defecto. Prueba 16 kHz mono y, si falla, el formato nativo del dispositivo
        (Vosk acepta cualquier frecuencia y aquí se pasa a 16 bits mono). Devuelve la frecuencia o 0."""
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.error.emit("No se ha encontrado ningún micrófono. Conéctalo o revisa la configuración de sonido.")
            return 0
        wanted = QAudioFormat()
        wanted.setSampleRate(16000)
        wanted.setChannelCount(1)
        wanted.setSampleFormat(QAudioFormat.Int16)
        candidates = ([wanted] if device.isFormatSupported(wanted) else []) + [device.preferredFormat()]
        problems = []
        for fmt in candidates:
            source = QAudioSource(device, fmt, self)
            io = source.start()
            # se compara el NOMBRE: en Qt 6.7+ el enum es QtAudio.Error y QAudio.Error es otra clase
            if io is not None and source.error().name == "NoError":
                self._fmt, self._source, self._io = fmt, source, io
                io.readyRead.connect(self._on_audio)
                # sin parámetros: PySide no sabe convertir el QAudio::State de la señal (Qt 6.7+ lo renombró)
                source.stateChanged.connect(lambda: self._on_state())
                return fmt.sampleRate()
            problems.append(f"{fmt.sampleRate()} Hz/{fmt.channelCount()} can.: {source.error().name}")
            source.stop()
            source.deleteLater()
        self.error.emit(f"No se pudo abrir el micrófono «{device.description()}» ({'; '.join(problems)}). "
                        "Comprueba que ninguna otra aplicación lo esté usando y los permisos de micrófono de Windows.")
        return 0

    def _on_state(self) -> None:
        """Errores que llegan después de abrirlo (micrófono desconectado, acceso denegado…)."""
        source = self._source
        if source is not None and source.state().name == "StoppedState" and source.error().name != "NoError":
            self.error.emit(f"El micrófono se ha detenido ({source.error().name}).")

    def _on_audio(self) -> None:
        if self._io is None:
            return
        data = self._io.readAll().data()
        if data:
            self._queue.put(to_int16_mono(data, self._fmt.sampleFormat(), self._fmt.channelCount()))

    def feed(self, pcm: bytes) -> None:
        """Audio PCM 16 bits mono desde otra fuente (pruebas sin micrófono)."""
        self._queue.put(pcm)

    def _update_grammar(self) -> None:
        if self.listening:
            self._queue.put(self._phrases())  # el hilo rehace el reconocedor con las posturas nuevas

    def _worker(self, phrases: list[str], rate: int) -> None:
        try:
            rec = VoiceRecognizer(model_dir(self.root), phrases, rate)
        except Exception as error:  # noqa: BLE001
            self.error.emit(f"No se pudo cargar el modelo de voz: {error}")
            return
        self.ready.emit()
        table = self.table
        while True:
            item = self._queue.get()
            if item is None:
                break
            if isinstance(item, list):
                rec.set_phrases(item)
                table = self.table
                continue
            partial, final = rec.feed(item)
            if partial:
                self.partial.emit(partial)
            if final:
                heard = interpret(final, table)
                if heard is not None:
                    self.heard.emit(heard)
