"""Simulador de la C6 puente + la mano, para trabajar sin hardware.

Se comporta como un puerto serie (read / write / in_waiting / close), así que
SerialLink lo usa exactamente igual que un COM real: la app no nota la
diferencia. En el selector de puerto aparece como "SIMULADOR".

La lógica es una copia de firmware/mano/mano.ino (gestos, rampas, fases,
modo AUTO/MANUAL) y responde con los mismos textos. ¡Si cambias el firmware
de la mano, actualiza también este archivo para que sigan coincidiendo!

También imita la placa EMG: con @EMG 1 envía líneas "EMG ..." generadas por
el paciente virtual (core/emg_sim.py), igual que haría el puente real.
"""

import threading
import time

from .emg_sim import PATIENT
from .gestures import ABIERTO, CERRADO, DESCONOCIDO, GESTOS
from .protocol import format_emg

SIMULATOR_PORT = "SIMULADOR"

# ---------------------------------------------------------------- constantes
# (mismos valores que mano.ino)
DURACION_RAMPA = 500      # ms
TIEMPO_FASE = 3000        # ms (antes: timer de 3 s)
ARRANCAR_EN_AUTO = True

QUIETO, ABRIENDO, CERRANDO = 0, 1, -1
MOVIENDO, PARANDO = "moviendo", "parado"

DEDOS = ["INDICE", "MEDIO", "ANULAR"]
N = len(GESTOS)
LETRAS = {"A": ABIERTO, "C": CERRADO, "-": DESCONOCIDO}

# EMG simulado (lo que reenviaría el puente desde la placa del ADS1198)
EMG_FS = 500        # muestras/s
EMG_BATCH = 20      # muestras por paquete, como BATCH en firmware/EMG


def _map(x, in_min, in_max, out_min, out_max) -> int:
    """map() de Arduino (aritmética entera)."""
    return int((x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min)


class SimulatedHand:
    """Estado y comandos de la mano. Mismo comportamiento que mano.ino."""

    def __init__(self):
        self.pos = [DESCONOCIDO] * 3      # dónde está cada dedo
        self.mov = [QUIETO] * 3           # qué hace en esta fase
        self.pwm = [0] * 3                # con signo: + abre, − cierra (0-255)
        self.fase = PARANDO
        self.modo_auto = ARRANCAR_EN_AUTO
        self.gesto_actual = -1
        self.angulo_pulgar = 10
        self.tiempo_fase = TIEMPO_FASE
        self.streaming = False
        self.periodo_telemetria = 50
        self._inicio = self._now()
        self._t = 0
        self._ultima_telemetria = 0

        self._commands = {
            "GESTO": self.cmd_gesto, "ABRIR": self.cmd_abrir, "CERRAR": self.cmd_cerrar,
            "DEDO": self.cmd_dedo, "PULGAR": self.cmd_pulgar, "PARAR": self.cmd_parar,
            "AUTO": self.cmd_auto, "MANUAL": self.cmd_manual, "TIEMPO": self.cmd_tiempo,
            "STREAM": self.cmd_stream, "PERIODO": self.cmd_periodo, "ESTADO": self.cmd_estado,
            "GESTOS": self.cmd_gestos, "POSTURA": self.cmd_postura,
        }
        self.ir_a_gesto(0)  # empieza abriendo la mano, como el firmware

    @staticmethod
    def _now() -> int:
        return int(time.monotonic() * 1000)

    # ------------------------------------------------------ máquina de estados
    def _empezar_fase(self, fase: str) -> None:
        self.fase = fase
        self._inicio = self._now()
        self._t = 0

    def _cancelar_movimiento(self) -> None:
        if self.fase != MOVIENDO:
            return
        for i in range(3):
            if self.mov[i] != QUIETO:
                self.pos[i] = DESCONOCIDO
            self.mov[i] = QUIETO

    def mover_a(self, objetivos: list[str]) -> None:
        self._cancelar_movimiento()
        for i, obj in enumerate(objetivos):
            if obj == DESCONOCIDO or obj == self.pos[i]:
                self.mov[i] = QUIETO
            else:
                self.mov[i] = ABRIENDO if obj == ABIERTO else CERRANDO
        self._empezar_fase(MOVIENDO)

    def ir_a_gesto(self, g: int) -> None:
        self.gesto_actual = g
        G = GESTOS[g]
        self.angulo_pulgar = G.pulgar
        self.mover_a([G.indice, G.medio, G.anular])

    def _parar_dedo(self, i: int) -> None:
        # Igual que pararDedo(): si el motor estaba activo, rampa 255 -> 0,
        # sin subir nunca por encima de la velocidad que ya llevaba.
        if self.pwm[i] != 0:
            duty = min(abs(self.pwm[i]), _map(min(self._t, DURACION_RAMPA), 0, DURACION_RAMPA, 255, 0))
            self.pwm[i] = duty if self.pwm[i] > 0 else -duty

    def update(self) -> None:
        self._t = self._now() - self._inicio
        if self.fase == MOVIENDO:
            duty = _map(min(self._t, DURACION_RAMPA), 0, DURACION_RAMPA, 0, 255)
            for i in range(3):
                if self.mov[i] == QUIETO:
                    self._parar_dedo(i)
                else:
                    self.pwm[i] = duty * self.mov[i]
            if self._t >= self.tiempo_fase:
                for i in range(3):
                    if self.mov[i] == ABRIENDO:
                        self.pos[i] = ABIERTO
                    elif self.mov[i] == CERRANDO:
                        self.pos[i] = CERRADO
                    self.mov[i] = QUIETO
                self._empezar_fase(PARANDO)
        else:
            for i in range(3):
                self._parar_dedo(i)
            if self.modo_auto and self._t >= self.tiempo_fase:
                self.ir_a_gesto((self.gesto_actual + 1) % N)

    def telemetry(self) -> list[str]:
        now = self._now()
        if not self.streaming or now - self._ultima_telemetria < self.periodo_telemetria:
            return []
        self._ultima_telemetria = now
        i, m, a = self.pwm
        return [f"DATA indice={i} medio={m} anular={a} pulgar={self.angulo_pulgar} gesto={self.gesto_actual + 1}"]

    # --------------------------------------------------------------- comandos
    def handle(self, line: str) -> list[str]:
        parts = line.split()
        if not parts:
            return []
        name, args = parts[0].upper(), parts[1:]
        handler = self._commands.get(name)
        if handler is None:
            return [f"ERR Comando desconocido en la mano: {name}"]
        return handler(args)

    @staticmethod
    def _int(args, i, default=0) -> int:
        try:
            return int(args[i])
        except (IndexError, ValueError):
            return default

    def cmd_gesto(self, args):
        g = self._int(args, 0)
        if not 1 <= g <= N:
            return [f"ERR GESTO debe estar entre 1 y {N}"]
        self.modo_auto = False
        self.ir_a_gesto(g - 1)
        return [f"ACK GESTO {g} {GESTOS[g - 1].nombre}"]

    def cmd_abrir(self, _):
        self.modo_auto = False
        self.ir_a_gesto(0)
        return ["ACK ABRIR"]

    def cmd_cerrar(self, _):
        self.modo_auto = False
        self.ir_a_gesto(N - 1)
        return ["ACK CERRAR"]

    def cmd_dedo(self, args):
        nombre = args[0].upper() if args else ""
        accion = args[1].upper() if len(args) > 1 else ""
        if nombre not in DEDOS or accion not in ("ABRIR", "CERRAR"):
            return ["ERR Uso: DEDO <INDICE|MEDIO|ANULAR> <ABRIR|CERRAR>"]
        d = DEDOS.index(nombre)
        self.modo_auto = False
        self.gesto_actual = -1
        obj = [DESCONOCIDO] * 3
        obj[d] = ABIERTO if accion == "ABRIR" else CERRADO
        if obj[d] == self.pos[d] and self.fase == PARANDO:
            return [f"ACK DEDO {nombre} {accion} (ya estaba)"]
        self.mover_a(obj)
        return [f"ACK DEDO {nombre} {accion}"]

    def cmd_pulgar(self, args):
        ang = self._int(args, 0, -1)
        if not 0 <= ang <= 180:
            return ["ERR PULGAR debe estar entre 0 y 180"]
        self.modo_auto = False
        self.gesto_actual = -1
        self.angulo_pulgar = ang
        return [f"ACK PULGAR {ang}"]

    def cmd_postura(self, args):
        # Igual que cmdPostura() de mano.ino
        ang = self._int(args, 3, -1) if len(args) == 4 and args[3][:1].isdigit() else -1
        objs = [LETRAS.get(a.upper()) for a in args[:3]]
        if len(args) != 4 or None in objs or not 0 <= ang <= 180:
            return ["ERR Uso: POSTURA <A|C|-> <A|C|-> <A|C|-> <0-180>  (indice medio anular pulgar)"]
        self.modo_auto = False
        self.gesto_actual = -1
        for g, G in enumerate(GESTOS):  # si coincide con un gesto de la tabla, se informa como ese gesto
            if [G.indice, G.medio, G.anular] == objs and G.pulgar == ang:
                self.gesto_actual = g
        self.angulo_pulgar = ang
        self.mover_a(objs)
        letras = " ".join({ABIERTO: "A", CERRADO: "C"}.get(o, "-") for o in objs)
        return [f"ACK POSTURA {letras} {ang}"]

    def cmd_parar(self, _):
        self.modo_auto = False
        self._cancelar_movimiento()
        self._empezar_fase(PARANDO)
        return ["ACK PARAR"]

    def cmd_auto(self, _):
        self.modo_auto = True
        if self.fase == PARANDO:
            self._inicio = self._now() - self.tiempo_fase  # arranca ya
        return ["ACK AUTO"]

    def cmd_manual(self, _):
        self.modo_auto = False
        return ["ACK MANUAL"]

    def cmd_tiempo(self, args):
        ms = self._int(args, 0)
        if not 500 <= ms <= 10000:
            return ["ERR TIEMPO debe estar entre 500 y 10000 ms"]
        self.tiempo_fase = ms
        return [f"ACK TIEMPO {ms}"]

    def cmd_stream(self, args):
        self.streaming = self._int(args, 0) != 0
        return [f"ACK STREAM {int(self.streaming)}"]

    def cmd_periodo(self, args):
        ms = self._int(args, 0)
        if not 10 <= ms <= 5000:
            return ["ERR PERIODO debe estar entre 10 y 5000 ms"]
        self.periodo_telemetria = ms
        return [f"ACK PERIODO {ms}"]

    def cmd_estado(self, _):
        # gesto = número (0 = personalizado), igual que mano.ino
        return [
            f"ACK ESTADO modo={'AUTO' if self.modo_auto else 'MANUAL'} fase={self.fase} gesto={self.gesto_actual + 1} "
            f"indice={self.pos[0]} medio={self.pos[1]} anular={self.pos[2]} "
            f"pulgar={self.angulo_pulgar} tiempo={self.tiempo_fase}"
        ]

    def cmd_gestos(self, _):
        return [f"GESTO {i + 1} = {g.nombre}" for i, g in enumerate(GESTOS)]


class SimulatedSerial:
    """Imita la parte de serial.Serial que usa SerialLink."""

    BRIDGE_MAC = "SI:MU:LA:DO:R0:00"

    def __init__(self, timeout: float = 0.05):
        self.port = SIMULATOR_PORT
        self.timeout = timeout
        self.is_open = True
        self.hand = SimulatedHand()
        self.emg_on = False
        self._emg_seq = 0
        self._emg_next = 0.0
        self._out = bytearray()
        self._in = b""
        self._lock = threading.Lock()
        self._emit("BRIDGE Puente listo. MAC=" + self.BRIDGE_MAC + " (SIMULADO)")
        self._emit(f"Mano lista. MAC=SI:MU:LA:DO:R0:01 modo={'AUTO' if self.hand.modo_auto else 'MANUAL'} (SIMULADA)")

    # ----------------------------------------------------- API tipo pyserial
    @property
    def in_waiting(self) -> int:
        with self._lock:
            self._step()
            return len(self._out)

    def read(self, size: int = 1) -> bytes:
        deadline = time.monotonic() + self.timeout
        while self.is_open:
            with self._lock:
                self._step()
                if self._out:
                    chunk = bytes(self._out[:size])
                    del self._out[:size]
                    return chunk
            if time.monotonic() >= deadline:
                return b""
            time.sleep(0.005)
        return b""

    def write(self, data: bytes) -> int:
        with self._lock:
            self._in += data
            while b"\n" in self._in:
                raw, self._in = self._in.split(b"\n", 1)
                self._handle_line(raw.decode("utf-8", errors="replace").strip())
        return len(data)

    def close(self) -> None:
        self.is_open = False

    # ------------------------------------------------------------- interno
    def _emit(self, line: str) -> None:
        self._out += (line + "\r\n").encode("utf-8")

    def _step(self) -> None:
        self.hand.update()
        for line in self.hand.telemetry():
            self._emit(line)
        if self.emg_on:
            now = time.monotonic()
            if now - self._emg_next > 0.5:  # la app estuvo parada: no se recupera el atraso de golpe
                self._emg_next = now
            while now >= self._emg_next:
                self._emit(format_emg(self._emg_seq & 0xFFFF, PATIENT.generate(EMG_BATCH)))
                self._emg_seq += 1
                self._emg_next += EMG_BATCH / EMG_FS

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("@"):  # comandos del puente
            name = line[1:].split()[0].upper() if line[1:].split() else ""
            args = line[1:].split()[1:]
            if name == "PING":
                self._emit("BRIDGE PONG")
            elif name == "INFO":
                self._emit(f"BRIDGE MAC puente={self.BRIDGE_MAC} mano=FF:FF:FF:FF:FF:FF canal=1 "
                           f"emg={int(self.emg_on)} paquetes={self._emg_seq} perdidos=0 (SIMULADO)")
            elif name == "EMG":
                if args and args[0] in ("0", "1"):
                    self.emg_on = args[0] == "1"
                    self._emg_next = time.monotonic()
                self._emit(f"BRIDGE EMG {int(self.emg_on)} canales={PATIENT.channels} fs={EMG_FS} (SIMULADO)")
            else:
                self._emit(f"ERR Comando de puente desconocido: {name}")
            return
        self.hand.update()
        for reply in self.hand.handle(line):
            self._emit(reply)
