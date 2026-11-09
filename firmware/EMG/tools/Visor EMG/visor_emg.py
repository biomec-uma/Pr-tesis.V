#!/usr/bin/env python3
"""
Visor EMG

Recibe por USB los paquetes que el receptor (ESP32-C6) reenvía desde el sensor (ESP32-C3),
dibuja la señal en tiempo real y la graba en .csv (con las columnas que elijas).

Formato de cada marco que llega por USB (todo en little-endian):
    AA 55 | tipo (1) | longitud (1) | contenido (longitud bytes) | XOR (1)
    XOR = tipo ^ longitud ^ todos los bytes del contenido

Tipos conocidos (los demás se ignoran, para poder ampliar el protocolo sin romper nada):
    0x01 DATOS  -> el paquete del sensor tal cual:
                   version(u8) nChnls(u8) batch(u8) seq(u32) sendFails(u16) data[batch][nChnls](i16)
    0x02 ESTADO -> diagnóstico de la C6:
                   mac[6] recibidos(u32) invalidos(u32) perdidosCola(u32) descartadosUSB(u32)

Requisitos para ejecutar el .py:  pip install pyserial numpy
Para crear el .exe: build_exe.bat (con logo.png e icono.ico en la misma carpeta)
"""

import csv
import datetime as dt
import json
import os
import re
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import numpy as np
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Faltan librerías. Instálalas con:  pip install pyserial numpy")
    sys.exit(1)

APP_NOMBRE = "Visor EMG"
APP_SUBTITULO = "Sensor mioeléctrico · ESP-NOW"
CONFIG = os.path.join(os.path.expanduser("~"), ".visor_emg.json")

# ============================================================================ PROTOCOLO
SYNC = b"\xAA\x55"
TIPO_DATOS = 0x01
TIPO_ESTADO = 0x02
VERSION_SOPORTADA = 1
CAB_SENSOR = struct.Struct("<BBBIH")             # version, nChnls, batch, seq, sendFails = 9 bytes
CAB_ESTADO = struct.Struct("<6sIIII")            # mac, recibidos, invalidos, perdidosCola, descartadosUSB
SEGUNDOS_BUFFER = 31                             # cuánta señal se guarda en memoria para la gráfica
VENTANAS = ["1", "2", "5", "10", "20", "30"]     # opciones de ventana de tiempo (s)

# ============================================================================ COLORES
FONDO = "#1E1F22"
FONDO_CABECERA = "#151618"
FONDO_CAMPO = "#2B2D31"
FONDO_GRAFICA = "#141517"
REJILLA = "#262930"
BORDE = "#3A3D43"
TEXTO = "#E4E6EB"
TEXTO_SUAVE = "#9AA0A8"
NARANJA = "#FF773D"             # color del logo: títulos, detalles, casillas
NARANJA_OSCURO = "#D95F28"
NARANJA_TENUE = "#5C3424"       # naranja apagado para bordes sutiles

BOTON_GRABAR = "#22C3A6"        # verde azulado: "Empezar a grabar"
BOTON_GRABAR_PULSADO = "#1AA58C"
BOTON_GRABAR_TEXTO = "#0B1F1B"
BOTON_PARAR = "#E5484D"         # rojo: grabando / parar
BOTON_PARAR_PULSADO = "#C93B40"
BOTON_PARAR_TEXTO = "#FFFFFF"
BOTON_APAGADO = "#33363C"
BOTON_APAGADO_TEXTO = "#7A808A"

# Colores de los canales en la gráfica (se repiten si hay más de 8)
COLORES_CANAL = ["#FF773D", "#5BC0EB", "#9BE564", "#C792EA", "#FDE74C", "#F78FB3", "#7FDBCA", "#B0BEC5"]

FUENTE = "Segoe UI"
LOGO = "logo.png"
ICONO = "icono.ico"


# ============================================================================ utilidades

def recurso(nombre):
    """Ruta de un archivo (logo, icono) tanto al ejecutar el .py como dentro del .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nombre)


def limpiar_nombre(nombre):
    nombre = re.sub(r"[^\w\-]", "", nombre.strip().replace(" ", "_"))
    return nombre or "emg"


def abrir_puerto(puerto):
    ser = serial.Serial()
    ser.port = puerto
    ser.baudrate = 115200          # con USB nativo da igual, pero hay que poner alguno
    ser.timeout = 0.05
    ser.dtr = False
    ser.rts = False
    ser.open()
    ser.reset_input_buffer()
    return ser


# ============================================================================ datos compartidos

class Datos:
    """Todo lo que el hilo receptor escribe y la ventana lee. Protegido con un lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.fs = 500.0
        self.reiniciar_formato(0, 0, 0)
        # contadores de la sesión
        self.paquetes = 0           # paquetes de datos correctos
        self.perdidos = 0           # detectados por saltos en seq
        self.reinicios = 0          # seq volvió atrás (el sensor se reinició)
        self.corruptos = 0          # marcos con XOR incorrecto o formato raro
        self.desconocidos = 0       # tipos de marco que este programa no conoce
        self.send_fails = None      # último valor que manda el sensor
        self.estado_c6 = None       # último marco de estado (contadores desde que se conectó)
        self.base_c6 = None         # contadores de la C6 en el momento de conectar
        self.ultimo_seq = None
        self.grab = None

    def reiniciar_formato(self, version, nch, batch):
        self.version, self.nch, self.batch = version, nch, batch
        n = int(SEGUNDOS_BUFFER * self.fs)
        self.buf = np.zeros((n, max(nch, 1)), dtype=np.int16)   # memoria circular de la señal
        self.escrito = 0                                       # muestras escritas en total
        self.ultimo_seq = None

    def ventana(self, n):
        """Devuelve las últimas n muestras (o menos si aún no hay tantas), en orden."""
        with self.lock:
            tam = len(self.buf)
            n = min(n, self.escrito, tam)
            if n == 0 or self.nch == 0:
                return np.zeros((0, max(self.nch, 1)), dtype=np.int16)
            fin = self.escrito % tam
            ini = fin - n
            if ini >= 0:
                return self.buf[ini:fin].copy()
            return np.concatenate((self.buf[ini:], self.buf[:fin]))


def ids_columnas(nch):
    """Columnas disponibles: t_s, seq, idx y un chN por canal."""
    return ["t_s", "seq", "idx"] + [f"ch{i + 1}" for i in range(nch)]


class Grabacion:
    """Graba en un .csv solo las columnas elegidas, en el orden en que llegan.
    columnas: lista de (id, nombre en el csv), con id en t_s, seq, idx, ch1, ch2…
    """

    def __init__(self, ruta, nch, batch, fs, columnas):
        self.ruta = ruta
        self.nch, self.batch, self.fs = nch, batch, fs
        todas = ids_columnas(nch)
        self.indices = [todas.index(cid) for cid, _ in columnas]   # posición de cada una en la fila completa
        self.f = open(ruta, "w", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        self.w.writerow([nombre for _, nombre in columnas])
        self.t_ini = time.time()
        self.seq_base = None
        self.t_offset = 0.0
        self.ultimo_t = 0.0
        self.filas = 0
        self.ultimo_flush = time.time()

    def escribir(self, seq, muestras, reinicio):
        """muestras: array (batch, nch). El tiempo sale de seq e idx, no del reloj del PC."""
        if self.seq_base is None:
            self.seq_base = seq
        elif reinicio:  # el sensor empezó de 0: seguimos la cuenta donde íbamos
            self.t_offset = self.ultimo_t + 1.0 / self.fs
            self.seq_base = seq
        base = (seq - self.seq_base) * self.batch
        filas = []
        for idx in range(self.batch):
            t = self.t_offset + (base + idx) / self.fs
            completa = [f"{t:.4f}", seq, idx] + muestras[idx].tolist()
            filas.append([completa[i] for i in self.indices])
        self.ultimo_t = t
        self.w.writerows(filas)
        self.filas += self.batch
        if time.time() - self.ultimo_flush >= 1:
            self.f.flush()
            self.ultimo_flush = time.time()

    def nombres(self):
        return os.path.basename(self.ruta)

    def duracion(self):
        return time.time() - self.t_ini

    def cerrar(self):
        self.f.flush()
        self.f.close()


# ============================================================================ hilo receptor

class Receptor(threading.Thread):
    """Lee bytes del USB, separa los marcos, los comprueba y reparte su contenido."""

    def __init__(self, ser, puerto, datos):
        super().__init__(daemon=True)
        self.ser, self.puerto, self.d = ser, puerto, datos
        self.parar_evento = threading.Event()
        self.avisos = []           # mensajes para la ventana
        self.avisos_lock = threading.Lock()
        self.pendiente = bytearray()

    def avisar(self, tipo, msg):
        with self.avisos_lock:
            self.avisos.append((tipo, msg))

    def run(self):
        while not self.parar_evento.is_set():
            try:
                if self.ser is None:
                    self.ser = abrir_puerto(self.puerto)
                    self.avisar("ok", f"Reconectado a {self.puerto}")
                trozo = self.ser.read(max(1, self.ser.in_waiting))
            except (serial.SerialException, OSError):
                if self.ser is not None:
                    self.avisar("aviso", f"{self.puerto} desconectado, reintentando…")
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                self.ser = None
                self.pendiente.clear()
                time.sleep(1)
                continue
            if trozo:
                self.pendiente += trozo
                self.separar_marcos()
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass

    def separar_marcos(self):
        b = self.pendiente
        pos = 0
        while True:
            ini = b.find(SYNC, pos)
            if ini < 0:                              # no hay firma: guardamos solo el último byte
                pos = max(pos, len(b) - 1)           # (podría ser el AA de una firma a medias)
                break
            if len(b) - ini < 5:                     # cabecera incompleta: esperar más bytes
                pos = ini
                break
            tipo, n = b[ini + 2], b[ini + 3]
            fin = ini + 4 + n
            if len(b) <= fin:                        # marco incompleto: esperar más bytes
                pos = ini
                break
            contenido = bytes(b[ini + 4:fin])
            chk = tipo ^ n
            for x in contenido:
                chk ^= x
            if chk != b[fin]:                        # no cuadra: era un AA 55 casual o hay basura
                with self.d.lock:
                    self.d.corruptos += 1
                pos = ini + 1                        # seguir buscando una byte más allá
                continue
            self.procesar(tipo, contenido)
            pos = fin + 1
        del b[:pos]

    def procesar(self, tipo, c):
        d = self.d
        if tipo == TIPO_DATOS:
            if len(c) < CAB_SENSOR.size:
                with d.lock:
                    d.corruptos += 1
                return
            version, nch, batch, seq, send_fails = CAB_SENSOR.unpack_from(c)
            if version != VERSION_SOPORTADA or len(c) != CAB_SENSOR.size + nch * batch * 2 or nch == 0:
                with d.lock:
                    d.corruptos += 1
                return
            muestras = np.frombuffer(c, dtype="<i2", offset=CAB_SENSOR.size).reshape(batch, nch)
            with d.lock:
                if (version, nch, batch) != (d.version, d.nch, d.batch):
                    cambio = d.nch != 0
                    d.reiniciar_formato(version, nch, batch)
                    if d.grab is not None:              # el CSV ya tiene otras columnas
                        d.grab.cerrar()
                        d.grab = None
                        self.avisar("formato", "El sensor cambió de formato: grabación detenida.")
                    if cambio:
                        self.avisar("info", f"Nuevo formato: {nch} canales, {batch} muestras/paquete")
                reinicio = False
                if d.ultimo_seq is not None:
                    salto = seq - d.ultimo_seq
                    if salto > 1:
                        d.perdidos += salto - 1
                    elif salto <= 0:
                        d.reinicios += 1
                        reinicio = True
                d.ultimo_seq = seq
                d.paquetes += 1
                d.send_fails = send_fails
                tam = len(d.buf)
                p = d.escrito % tam
                if p + batch <= tam:
                    d.buf[p:p + batch] = muestras
                else:
                    k = tam - p
                    d.buf[p:] = muestras[:k]
                    d.buf[:batch - k] = muestras[k:]
                d.escrito += batch
                if d.grab is not None:
                    try:
                        d.grab.escribir(seq, muestras, reinicio)
                    except Exception as e:
                        d.grab = None
                        self.avisar("error", f"Error al escribir el archivo: {e}")
        elif tipo == TIPO_ESTADO:
            if len(c) >= CAB_ESTADO.size:
                mac, rec, inv, cola, usb = CAB_ESTADO.unpack_from(c)
                with d.lock:
                    actual = {"recibidos": rec, "invalidos": inv, "cola": cola, "usb": usb}
                    # Los contadores de la C6 cuentan desde que se encendió (incluido el tiempo
                    # en que nadie leía el USB). Guardamos los del primer estado tras conectar
                    # y mostramos la diferencia: así cuentan solo desde que pulsas Conectar.
                    if d.base_c6 is None or any(actual[k] < d.base_c6[k] for k in actual):
                        d.base_c6 = actual          # primera vez, o la C6 se reinició
                    d.estado_c6 = {k: actual[k] - d.base_c6[k] for k in actual}
                    d.estado_c6.update(mac=":".join(f"{x:02X}" for x in mac), t=time.time())
        else:
            with d.lock:
                d.desconocidos += 1   # tipo nuevo que este programa aún no conoce: se ignora

    def detener(self):
        self.parar_evento.set()


# ============================================================================ gráfica

class Grafica:
    """Dibuja los canales en carriles apilados sobre un Canvas de tkinter."""

    MARGEN_IZQ, MARGEN_DER, MARGEN_SUP, MARGEN_INF = 64, 12, 8, 24

    def __init__(self, padre):
        self.c = tk.Canvas(padre, bg=FONDO_GRAFICA, highlightthickness=1, highlightbackground=NARANJA_TENUE)
        self.lineas = []
        self.escalas = []      # (centro, mitad del rango) de cada canal, suavizadas
        self.nch = 0
        self.auto = True       # False = escala congelada en sus valores actuales

    def preparar(self, nch):
        self.c.delete("senal")
        self.lineas = [self.c.create_line(0, 0, 0, 0, fill=COLORES_CANAL[i % len(COLORES_CANAL)],
                                          width=1, tags="senal") for i in range(nch)]
        self.escalas = [None] * nch
        self.nch = nch

    def dibujar(self, datos, ventana_s, fs, mensaje=None):
        c = self.c
        W, H = c.winfo_width(), c.winfo_height()
        c.delete("fijo")
        if W < 100 or H < 60:
            return
        x0, x1 = self.MARGEN_IZQ, W - self.MARGEN_DER
        y0, y1 = self.MARGEN_SUP, H - self.MARGEN_INF
        ancho = x1 - x0

        # --- rejilla de tiempo (el borde derecho es "ahora")
        paso = next(p for p in (0.1, 0.2, 0.5, 1, 2, 5, 10) if ventana_s / p <= 10)
        k = 0
        while k * paso <= ventana_s + 1e-9:
            x = x1 - (k * paso) / ventana_s * ancho
            c.create_line(x, y0, x, y1, fill=REJILLA, tags="fijo")
            if k == 0:   # el "ahora" en naranja
                c.create_text(x, y1 + 4, text="ahora", anchor="ne", fill=NARANJA,
                              font=(FUENTE, 8, "bold"), tags="fijo")
            else:
                c.create_text(x, y1 + 4, text=f"-{k * paso:g} s", anchor="n",
                              fill=TEXTO_SUAVE, font=(FUENTE, 8), tags="fijo")
            k += 1

        if mensaje or self.nch == 0 or len(datos) == 0:
            c.create_text(W / 2, H / 2, text=mensaje or "Esperando datos del sensor…",
                          fill=TEXTO_SUAVE, font=(FUENTE, 11), tags="fijo")
            for ln in self.lineas:
                c.coords(ln, 0, 0, 0, 0)
            return

        n_vent = max(1, int(ventana_s * fs))
        n = len(datos)
        alto = (y1 - y0) / self.nch
        # Si hay más muestras que píxeles, cada columna de píxeles muestra el mínimo y el
        # máximo de sus muestras: así no se "pierden" picos al reducir (importante en EMG).
        cols = max(2, int(ancho * n / n_vent))
        if n > 2 * cols:
            bordes = np.linspace(0, n, cols + 1).astype(int)[:-1]
            mins = np.minimum.reduceat(datos, bordes, axis=0)
            maxs = np.maximum.reduceat(datos, bordes, axis=0)
            pos = bordes + (n / cols) / 2
            xs = np.repeat(pos, 2)
            vals = np.empty((2 * len(bordes), self.nch))
            vals[0::2], vals[1::2] = mins, maxs
        else:
            xs = np.arange(n, dtype=float)
            vals = datos.astype(float)
        xs = x1 - (n - xs) / n_vent * ancho

        for ch in range(self.nch):
            top = y0 + ch * alto
            bot = top + alto
            v = vals[:, ch]
            lo, hi = float(v.min()), float(v.max())
            centro, mitad = (hi + lo) / 2, max((hi - lo) / 2 * 1.1, 5)
            # Escala automática suave: crece al instante, encoge despacio (no "baila").
            # Si está desactivada, se usa la última escala calculada sin tocarla.
            if self.escalas[ch] is None:
                self.escalas[ch] = [centro, mitad]
            elif self.auto:
                e = self.escalas[ch]
                e[0] += (centro - e[0]) * 0.1
                e[1] = mitad if mitad > e[1] else e[1] + (mitad - e[1]) * 0.03
            centro, mitad = self.escalas[ch]
            ys = (top + alto / 2) - (v - centro) / mitad * (alto / 2 - 4)
            pts = np.column_stack((xs, ys)).ravel().tolist()
            if len(pts) < 4:
                pts += pts
            c.coords(self.lineas[ch], *pts)

            color = COLORES_CANAL[ch % len(COLORES_CANAL)]
            if ch > 0:
                c.create_line(x0, top, x1, top, fill=BORDE, tags="fijo")
            c.create_line(x0, top + alto / 2, x1, top + alto / 2, fill=REJILLA, dash=(2, 4), tags="fijo")
            # Margen izquierdo de cada carril: máximo arriba, nombre del canal en el centro
            # (junto a una marca de su color) y mínimo abajo. Así nunca se solapan.
            c.create_text(x0 - 6, top + 4, text=f"{centro + mitad:.0f}", anchor="ne",
                          fill=TEXTO_SUAVE, font=(FUENTE, 7), tags="fijo")
            c.create_rectangle(6, top + alto / 2 - 7, 9, top + alto / 2 + 7, fill=color, outline="", tags="fijo")
            c.create_text(14, top + alto / 2, text=f"CH{ch + 1}", anchor="w", fill=color,
                          font=(FUENTE, 9, "bold"), tags="fijo")
            c.create_text(x0 - 6, bot - 4, text=f"{centro - mitad:.0f}", anchor="se",
                          fill=TEXTO_SUAVE, font=(FUENTE, 7), tags="fijo")
        c.create_line(x0, y0, x0, y1, fill=BORDE, tags="fijo")
        c.create_line(x1, y0, x1, y1, fill=NARANJA, width=2, tags="fijo")   # línea naranja del "ahora"
        c.tag_raise("senal")


# ============================================================================ ventana

class App:
    def __init__(self, root):
        self.root = root
        self.d = Datos()
        self.receptor = None
        self.puertos = {}
        self.pausa = False
        self.hist = []          # (instante, paquetes) para calcular paquetes/s
        self.pps = 0.0
        self.ultimo_panel = 0
        cfg = self.cargar_config()

        root.title(APP_NOMBRE)
        root.geometry("1120x790")
        root.minsize(860, 600)
        root.configure(bg=FONDO)
        self.aplicar_tema()
        self.poner_icono()
        pad = {"padx": 6, "pady": 4}

        # --- Cabecera
        cab = tk.Frame(root, bg=FONDO_CABECERA)
        cab.pack(fill="x")
        self.logo_img = None
        if os.path.exists(recurso(LOGO)):
            try:
                self.logo_img = tk.PhotoImage(file=recurso(LOGO))
                tk.Label(cab, image=self.logo_img, bg=FONDO_CABECERA).pack(side="left", padx=(14, 10), pady=10)
            except tk.TclError:
                self.logo_img = None
        tc = tk.Frame(cab, bg=FONDO_CABECERA)
        tc.pack(side="left", padx=(0 if self.logo_img else 14, 0), pady=10)
        tk.Label(tc, text=APP_NOMBRE, bg=FONDO_CABECERA, fg=TEXTO, font=(FUENTE, 15, "bold")).pack(anchor="w")
        tk.Label(tc, text=APP_SUBTITULO, bg=FONDO_CABECERA, fg=TEXTO_SUAVE, font=(FUENTE, 9)).pack(anchor="w")
        self.var_conexion = tk.StringVar(value="●  Desconectado")
        self.lbl_conexion = tk.Label(cab, textvariable=self.var_conexion, bg=FONDO_CABECERA,
                                     fg=TEXTO_SUAVE, font=(FUENTE, 10, "bold"))
        self.lbl_conexion.pack(side="right", padx=16)
        tk.Frame(root, bg=NARANJA, height=2).pack(fill="x")   # línea naranja bajo la cabecera

        # --- Conexión
        fc = ttk.LabelFrame(root, text="Conexión")
        fc.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(fc, text="Puerto del receptor:").grid(row=0, column=0, sticky="w", **pad)
        self.cb_puerto = ttk.Combobox(fc, state="readonly", width=34)
        self.cb_puerto.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(fc, text="↻", width=3, command=self.refrescar_puertos).grid(row=0, column=2, **pad)
        self.btn_conectar = ttk.Button(fc, text="Conectar", style="Acento.TButton", command=self.conectar)
        self.btn_conectar.grid(row=0, column=3, **pad)
        ttk.Label(fc, text="Frecuencia del ADS (Hz):").grid(row=0, column=4, sticky="e", padx=(18, 6), pady=4)
        self.var_fs = tk.StringVar(value=cfg.get("fs", "500"))
        self.ent_fs = ttk.Entry(fc, textvariable=self.var_fs, width=7)
        self.ent_fs.grid(row=0, column=5, sticky="w", **pad)
        fc.columnconfigure(1, weight=1)

        # --- Centro: gráfica + panel lateral
        centro = ttk.Frame(root)
        centro.pack(fill="both", expand=True, padx=10, pady=4)

        lateral = ttk.Frame(centro, width=300)
        lateral.pack(side="right", fill="y", padx=(10, 0))
        lateral.pack_propagate(False)

        fgraf = ttk.LabelFrame(centro, text="Señal")
        fgraf.pack(side="left", fill="both", expand=True)
        self.grafica = Grafica(fgraf)
        self.grafica.c.pack(fill="both", expand=True, padx=6, pady=6)

        # Panel: controles de la gráfica
        fv = ttk.LabelFrame(lateral, text="Gráfica")
        fv.pack(fill="x")
        ttk.Label(fv, text="Ventana (s):").grid(row=0, column=0, sticky="w", **pad)
        self.cb_ventana = ttk.Combobox(fv, values=VENTANAS, width=6)
        self.cb_ventana.set(cfg.get("ventana", "5"))
        self.cb_ventana.grid(row=0, column=1, sticky="w", **pad)
        self.btn_pausa = ttk.Button(fv, text="Pausar gráfica", style="Acento.TButton", command=self.alternar_pausa)
        self.btn_pausa.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(fv, text="Pausar no detiene la grabación.", style="Suave.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))
        self.var_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(fv, text="Escala automática", variable=self.var_auto,
                        command=lambda: setattr(self.grafica, "auto", self.var_auto.get())).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 6))

        # Panel: diagnóstico
        fd = ttk.LabelFrame(lateral, text="Diagnóstico")
        fd.pack(fill="x", pady=(8, 0))
        self.diag = {}
        filas = [("formato", "Canales × muestras"), ("pps", "Paquetes/s"), ("paquetes", "Paquetes recibidos"),
                 ("perdidos", "Paquetes perdidos"), ("fails", "Envíos fallidos (sensor)"),
                 ("reinicios", "Reinicios del sensor"), ("corruptos", "Marcos corruptos"),
                 ("sep", None),
                 ("mac", "MAC receptor"), ("c6_inv", "Inválidos (C6)"), ("c6_cola", "Cola llena (C6)"),
                 ("c6_usb", "Descartados USB (C6)")]
        for i, (clave, texto) in enumerate(filas):
            if texto is None:
                tk.Frame(fd, bg=NARANJA_TENUE, height=1).grid(row=i, column=0, columnspan=2, sticky="ew",
                                                             padx=6, pady=5)
                continue
            ttk.Label(fd, text=texto, style="Suave.TLabel").grid(row=i, column=0, sticky="w", padx=6, pady=1)
            v = tk.StringVar(value="—")
            lbl = ttk.Label(fd, textvariable=v)
            lbl.grid(row=i, column=1, sticky="e", padx=6, pady=1)
            self.diag[clave] = (v, lbl)
        fd.columnconfigure(1, weight=1)

        # --- Grabación
        fg = ttk.LabelFrame(root, text="Grabación")
        fg.pack(fill="x", padx=10, pady=4)
        ttk.Label(fg, text="Carpeta:").grid(row=0, column=0, sticky="w", **pad)
        self.var_carpeta = tk.StringVar(value=cfg.get("carpeta", os.path.join(os.path.expanduser("~"), "Documents")))
        ttk.Entry(fg, textvariable=self.var_carpeta).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(fg, text="Elegir…", command=self.elegir_carpeta).grid(row=0, column=2, **pad)
        ttk.Button(fg, text="Abrir", command=self.abrir_carpeta).grid(row=0, column=3, **pad)
        ttk.Label(fg, text="Nombre:").grid(row=0, column=4, sticky="w", padx=(16, 6), pady=4)
        self.var_nombre = tk.StringVar(value=cfg.get("nombre", ""))
        ttk.Entry(fg, textvariable=self.var_nombre, width=22).grid(row=0, column=5, sticky="ew", **pad)
        ttk.Label(fg, text="Parar a los (s):").grid(row=0, column=6, sticky="w", padx=(16, 6), pady=4)
        self.var_duracion = tk.StringVar(value="")
        ttk.Entry(fg, textvariable=self.var_duracion, width=6).grid(row=0, column=7, sticky="w", **pad)
        # Columnas del .csv: se ven todas las que llegan (con su último valor), se marcan
        # las que se quieren guardar y se les puede cambiar el nombre de la cabecera.
        fcol = ttk.Frame(fg)
        fcol.grid(row=1, column=0, columnspan=8, sticky="ew", pady=(2, 4))
        cab_col = ttk.Frame(fcol)
        cab_col.pack(fill="x")
        ttk.Label(cab_col, text="Columnas del .csv:").pack(side="left", padx=6)
        ttk.Label(cab_col, text="marca las que quieres guardar · el recuadro es el nombre en la cabecera · "
                  "a la derecha, el último valor recibido", style="Suave.TLabel").pack(side="left")
        self.btn_col_simple = ttk.Button(cab_col, text="Solo tiempo + canales", command=self.columnas_simple)
        self.btn_col_simple.pack(side="right", padx=6)
        self.btn_col_todas = ttk.Button(cab_col, text="Todas (nombres originales)", command=self.columnas_todas)
        self.btn_col_todas.pack(side="right")
        self.fcols = ttk.Frame(fcol)
        self.fcols.pack(fill="x", pady=(2, 0))
        self.cfg_cols = cfg.get("columnas", {})     # elección guardada de la última vez
        self.modo_simple = cfg.get("columnas_modo_simple", False)
        self.cols = {}                              # id -> {"on", "nombre", "valor"} (variables tk)
        self.col_widgets = []
        self.estado_boton = "apagado"
        self.construir_columnas(0)
        fg.columnconfigure(1, weight=1)

        fb = ttk.Frame(root)
        fb.pack(fill="x", padx=10, pady=(4, 2))
        self.btn_grabar = tk.Button(fb, font=(FUENTE, 12, "bold"), relief="flat", bd=0, height=2,
                                    command=self.alternar_grabacion)
        self.btn_grabar.pack(fill="x")
        self.boton_estado("apagado")
        self.var_estado = tk.StringVar(value="Elige el puerto del receptor y pulsa Conectar.")
        ttk.Label(root, textvariable=self.var_estado, style="Suave.TLabel", anchor="w").pack(fill="x", padx=12, pady=(0, 6))
        tk.Frame(root, bg=NARANJA, height=2).pack(fill="x", side="bottom")   # línea naranja al pie

        self.refrescar_puertos(cfg.get("puerto"))
        root.protocol("WM_DELETE_WINDOW", self.al_cerrar)
        root.after(100, self.tick)

    # ----------------------------------------------------------------- aspecto
    def aplicar_tema(self):
        r = self.root
        r.option_add("*TCombobox*Listbox.background", FONDO_CAMPO)
        r.option_add("*TCombobox*Listbox.foreground", TEXTO)
        r.option_add("*TCombobox*Listbox.selectBackground", NARANJA_OSCURO)
        r.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        st = ttk.Style()
        st.theme_use("clam")
        st.configure(".", background=FONDO, foreground=TEXTO, bordercolor=BORDE, lightcolor=FONDO,
                     darkcolor=FONDO, troughcolor=FONDO, font=(FUENTE, 9))
        st.configure("TFrame", background=FONDO)
        st.configure("TLabel", background=FONDO, foreground=TEXTO)
        st.configure("Suave.TLabel", background=FONDO, foreground=TEXTO_SUAVE)
        st.configure("Alerta.TLabel", background=FONDO, foreground=NARANJA, font=(FUENTE, 9, "bold"))
        st.configure("Destacado.TLabel", background=FONDO, foreground=NARANJA, font=(FUENTE, 11, "bold"))
        st.configure("TLabelframe", background=FONDO, bordercolor=BORDE)
        st.configure("TLabelframe.Label", background=FONDO, foreground=NARANJA, font=(FUENTE, 10, "bold"))
        st.configure("TSeparator", background=BORDE)
        st.configure("TEntry", fieldbackground=FONDO_CAMPO, foreground=TEXTO, insertcolor=TEXTO,
                     bordercolor=BORDE, lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO, padding=3)
        st.map("TEntry", bordercolor=[("focus", NARANJA)], lightcolor=[("focus", NARANJA)],
               fieldbackground=[("disabled", FONDO)], foreground=[("disabled", TEXTO_SUAVE)])
        st.configure("TCombobox", fieldbackground=FONDO_CAMPO, background=FONDO_CAMPO, foreground=TEXTO,
                     arrowcolor=NARANJA, bordercolor=BORDE, lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO,
                     selectbackground=FONDO_CAMPO, selectforeground=TEXTO, padding=3)
        st.map("TCombobox", fieldbackground=[("readonly", FONDO_CAMPO), ("disabled", FONDO)],
               foreground=[("disabled", TEXTO_SUAVE)], background=[("active", BORDE)],
               arrowcolor=[("disabled", TEXTO_SUAVE)], bordercolor=[("focus", NARANJA)])
        st.configure("TButton", background=FONDO_CAMPO, foreground=TEXTO, bordercolor=BORDE,
                     lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO, padding=(10, 3), focuscolor=FONDO_CAMPO)
        st.map("TButton", background=[("pressed", FONDO), ("active", BORDE)])
        # Botón "Conectar" con borde naranja
        st.configure("Acento.TButton", background=FONDO_CAMPO, foreground=NARANJA, bordercolor=NARANJA,
                     lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO, font=(FUENTE, 9, "bold"))
        st.map("Acento.TButton", background=[("pressed", FONDO), ("active", BORDE)])

    def boton_estado(self, estado):
        self.estado_boton = estado
        self.bloquear_columnas(estado == "grabando")
        b = self.btn_grabar
        if estado == "apagado":
            b.config(text="●  EMPEZAR A GRABAR", state="disabled", bg=BOTON_APAGADO,
                     disabledforeground=BOTON_APAGADO_TEXTO, cursor="arrow")
        elif estado == "listo":
            b.config(text="●  EMPEZAR A GRABAR", state="normal", bg=BOTON_GRABAR, fg=BOTON_GRABAR_TEXTO,
                     activebackground=BOTON_GRABAR_PULSADO, activeforeground=BOTON_GRABAR_TEXTO, cursor="hand2")
        else:
            b.config(text="■  PARAR GRABACIÓN", state="normal", bg=BOTON_PARAR, fg=BOTON_PARAR_TEXTO,
                     activebackground=BOTON_PARAR_PULSADO, activeforeground=BOTON_PARAR_TEXTO, cursor="hand2")

    def poner_icono(self):
        try:
            if sys.platform.startswith("win") and os.path.exists(recurso(ICONO)):
                self.root.iconbitmap(recurso(ICONO))
            elif os.path.exists(recurso(LOGO)):
                self.icono_img = tk.PhotoImage(file=recurso(LOGO))
                self.root.iconphoto(True, self.icono_img)
        except tk.TclError:
            pass

    # ----------------------------------------------------------------- configuración guardada
    def cargar_config(self):
        try:
            with open(CONFIG, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def guardar_config(self):
        cfg = {"puerto": self.puertos.get(self.cb_puerto.get(), ""), "fs": self.var_fs.get(),
               "ventana": self.cb_ventana.get(), "carpeta": self.var_carpeta.get(),
               "nombre": self.var_nombre.get(), "columnas_modo_simple": self.modo_simple,
               "columnas": {**self.cfg_cols,
                            **{cid: {"on": v["on"].get(), "nombre": v["nombre"].get()}
                               for cid, v in self.cols.items()}}}
        try:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    # ----------------------------------------------------------------- conexión
    def refrescar_puertos(self, preferido=None):
        lista = sorted(list_ports.comports(), key=lambda p: p.device)
        self.puertos = {f"{p.device} – {p.description}": p.device for p in lista}
        textos = list(self.puertos)
        self.cb_puerto["values"] = textos
        if not textos:
            self.cb_puerto.set("")
            self.var_estado.set("No se encuentra ningún puerto. Conecta el receptor y pulsa ↻.")
            return
        elegido = next((t for t, dev in self.puertos.items() if dev == preferido), None)
        if elegido is None:
            usb = [f"{p.device} – {p.description}" for p in lista if p.vid is not None]
            elegido = usb[0] if usb else textos[0]
        self.cb_puerto.set(elegido)

    def conectar(self):
        if self.receptor:
            self.desconectar()
            return
        dev = self.puertos.get(self.cb_puerto.get())
        if not dev:
            messagebox.showwarning(APP_NOMBRE, "Elige el puerto del receptor.")
            return
        try:
            fs = float(self.var_fs.get().replace(",", "."))
            assert fs > 0
        except (ValueError, AssertionError):
            messagebox.showwarning(APP_NOMBRE, "La frecuencia debe ser un número positivo (ej. 500).")
            return
        try:
            ser = abrir_puerto(dev)
        except serial.SerialException as e:
            t = str(e).lower()
            if "denegado" in t or "denied" in t or "permissionerror" in t:
                messagebox.showerror(APP_NOMBRE, f"El puerto {dev} está ocupado.\n\nCierra el monitor serie "
                                     "de PlatformIO / Arduino u otro programa que lo esté usando.")
            else:
                messagebox.showerror(APP_NOMBRE, f"No se pudo abrir {dev}:\n{e}")
            return
        self.d = Datos()
        self.d.fs = fs
        self.d.reiniciar_formato(0, 0, 0)
        self.grafica.preparar(0)
        self.hist.clear()
        self.receptor = Receptor(ser, dev, self.d)
        self.receptor.start()
        self.btn_conectar.config(text="Desconectar")
        self.cb_puerto.config(state="disabled")
        self.ent_fs.config(state="disabled")
        self.boton_estado("listo")
        self.var_conexion.set(f"●  {dev}")
        self.lbl_conexion.config(fg=NARANJA)
        self.guardar_config()

    def desconectar(self):
        if self.d.grab:
            self.parar()
        if self.receptor:
            self.receptor.detener()
            self.receptor = None
        self.btn_conectar.config(text="Conectar")
        self.cb_puerto.config(state="readonly")
        self.ent_fs.config(state="normal")
        self.boton_estado("apagado")
        self.var_conexion.set("●  Desconectado")
        self.lbl_conexion.config(fg=TEXTO_SUAVE)
        self.var_estado.set("Desconectado.")

    # ----------------------------------------------------------------- grabación
    def alternar_grabacion(self):
        if self.d.grab:
            self.parar()
        else:
            self.empezar()

    def empezar(self):
        with self.d.lock:
            nch, batch, fs = self.d.nch, self.d.batch, self.d.fs
        if nch == 0:
            messagebox.showinfo(APP_NOMBRE, "Todavía no llegan datos del sensor. Espera a ver la señal.")
            return
        columnas = []
        for cid in ids_columnas(nch):
            v = self.cols.get(cid)
            if v and v["on"].get():
                columnas.append((cid, v["nombre"].get().strip() or cid))
        if not columnas:
            messagebox.showwarning(APP_NOMBRE, "Marca al menos una columna para guardar.")
            return
        nombres = [n for _, n in columnas]
        repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
        if repetidos:
            messagebox.showwarning(APP_NOMBRE, "Hay columnas con el mismo nombre: " + ", ".join(repetidos))
            return
        carpeta = self.var_carpeta.get().strip() or "."
        try:
            os.makedirs(carpeta, exist_ok=True)
            marca = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta = os.path.join(carpeta, f"{limpiar_nombre(self.var_nombre.get())}_{marca}.csv")
            grab = Grabacion(ruta, nch, batch, fs, columnas)
        except Exception as e:
            messagebox.showerror(APP_NOMBRE, f"No se pudo crear el archivo:\n{e}")
            return
        with self.d.lock:
            self.grab_perdidos_ini = self.d.perdidos
            self.d.grab = grab
        self.boton_estado("grabando")
        self.guardar_config()

    def parar(self):
        with self.d.lock:
            g, self.d.grab = self.d.grab, None
            perdidos = self.d.perdidos - getattr(self, "grab_perdidos_ini", self.d.perdidos)
        if g is None:
            return
        g.cerrar()
        self.boton_estado("listo" if self.receptor else "apagado")
        extra = (f" — ⚠ {perdidos} paquete{'s' if perdidos > 1 else ''} perdido{'s' if perdidos > 1 else ''}"
                 if perdidos else " — sin pérdidas")
        self.var_estado.set(f"Guardado: {g.nombres()} — {g.filas} muestras "
                            f"({g.filas / g.fs:.1f} s de señal){extra}")

    # ----------------------------------------------------------------- refresco periódico
    def alternar_pausa(self):
        self.pausa = not self.pausa
        self.btn_pausa.config(text="Reanudar gráfica" if self.pausa else "Pausar gráfica")

    def tick(self):
        d = self.d
        rec = self.receptor
        if rec:
            with rec.avisos_lock:
                avisos, rec.avisos = rec.avisos, []
            for tipo, msg in avisos:
                self.var_estado.set(msg)
                if tipo == "aviso":
                    self.var_conexion.set("●  Reconectando…")
                    self.lbl_conexion.config(fg=TEXTO_SUAVE)
                elif tipo == "ok":
                    self.var_conexion.set(f"●  {rec.puerto}")
                    self.lbl_conexion.config(fg=NARANJA)
                if tipo in ("error", "formato"):
                    self.boton_estado("listo")
                    messagebox.showwarning(APP_NOMBRE, msg)

            with d.lock:
                nch, batch, fs = d.nch, d.batch, d.fs
                paquetes = d.paquetes
                grab = d.grab
            if nch != self.grafica.nch:
                self.grafica.preparar(nch)
                self.construir_columnas(nch)

            ahora = time.time()
            self.hist.append((ahora, paquetes))
            while self.hist and ahora - self.hist[0][0] > 2:
                self.hist.pop(0)
            if ahora - self.hist[0][0] > 0.5:
                self.pps = (paquetes - self.hist[0][1]) / (ahora - self.hist[0][0])

            try:
                ventana = min(SEGUNDOS_BUFFER - 1, max(0.2, float(self.cb_ventana.get().replace(",", "."))))
            except ValueError:
                ventana = 5.0
            if not self.pausa:
                sin_datos = paquetes > 0 and self.pps == 0 and len(self.hist) > 1 and ahora - self.hist[0][0] > 1
                datos = d.ventana(int(ventana * fs))
                self.grafica.dibujar(datos, ventana, fs,
                                     "Sin datos: ¿está encendido el sensor?" if sin_datos else None)

            if grab:
                dur = grab.duracion()
                self.var_estado.set(f"● GRABANDO {grab.nombres()} — {grab.filas} muestras — "
                                    f"{dur:.1f} s")
                try:
                    lim = float(self.var_duracion.get().replace(",", "."))
                except ValueError:
                    lim = 0
                if lim > 0 and grab.filas / grab.fs >= lim:
                    self.parar()
            elif paquetes and not self.var_estado.get().startswith(("Guardado", "El sensor", "Error")):
                self.var_estado.set("Recibiendo señal. Pulsa EMPEZAR para grabar.")
            elif not paquetes and not self.var_estado.get().startswith(("Reconectado", "COM", "/dev")):
                self.var_estado.set("Conectado. Esperando paquetes del sensor… (¿está encendido?)")

            if ahora - self.ultimo_panel > 0.25:
                self.ultimo_panel = ahora
                self.actualizar_panel()
        else:
            self.grafica.dibujar(np.zeros((0, 1)), 5, 500, "Desconectado")
        self.root.after(40, self.tick)   # ~25 imágenes por segundo

    def poner(self, clave, texto, alerta=False, estilo=None):
        v, lbl = self.diag[clave]
        v.set(texto)
        lbl.configure(style=estilo or ("Alerta.TLabel" if alerta else "TLabel"))

    def actualizar_panel(self):
        d = self.d
        with d.lock:
            nch, batch, version = d.nch, d.batch, d.version
            paquetes, perdidos, reinicios = d.paquetes, d.perdidos, d.reinicios
            corruptos, fails, est = d.corruptos, d.send_fails, d.estado_c6
        self.poner("formato", f"{nch} × {batch}" if nch else "—")
        self.poner("pps", f"{self.pps:.1f}" if paquetes else "—", estilo="Destacado.TLabel")
        self.poner("paquetes", f"{paquetes}")
        total = paquetes + perdidos
        self.poner("perdidos", f"{perdidos} ({100 * perdidos / total:.2f} %)" if total else "0", perdidos > 0)
        self.poner("fails", "—" if fails is None else f"{fails}", bool(fails))
        self.poner("reinicios", f"{reinicios}", reinicios > 0)
        self.poner("corruptos", f"{corruptos}", corruptos > 0)
        self.actualizar_valores_columnas()
        if est and time.time() - est["t"] < 3:
            self.poner("mac", est["mac"])
            self.poner("c6_inv", f"{est['invalidos']}", est["invalidos"] > 0)
            self.poner("c6_cola", f"{est['cola']}", est["cola"] > 0)
            self.poner("c6_usb", f"{est['usb']}", est["usb"] > 0)
        else:
            for k in ("mac", "c6_inv", "c6_cola", "c6_usb"):
                self.poner(k, "—")

    # ----------------------------------------------------------------- columnas del csv
    COLUMNAS_POR_FILA = 5

    def construir_columnas(self, nch):
        """(Re)dibuja una casilla por columna disponible. Se llama al cambiar el número de canales."""
        for w in self.fcols.winfo_children():
            w.destroy()
        self.col_widgets = []
        ids = ids_columnas(nch)
        for i, cid in enumerate(ids):
            if cid not in self.cols:
                guardada = self.cfg_cols.get(cid, {})
                nombre = guardada.get("nombre")
                if nombre is None:
                    nombre = self.nombre_simple(cid) if self.modo_simple else cid
                on = guardada.get("on", not (self.modo_simple and cid in ("seq", "idx")))
                self.cols[cid] = {"on": tk.BooleanVar(value=on), "nombre": tk.StringVar(value=nombre),
                                  "valor": tk.StringVar(value="—")}
            v = self.cols[cid]
            celda = ttk.Frame(self.fcols)
            celda.grid(row=i // self.COLUMNAS_POR_FILA, column=i % self.COLUMNAS_POR_FILA,
                       sticky="w", padx=6, pady=2)
            chk = ttk.Checkbutton(celda, text=cid, variable=v["on"], width=5)
            chk.pack(side="left")
            ent = ttk.Entry(celda, textvariable=v["nombre"], width=10)
            ent.pack(side="left", padx=(2, 6))
            ttk.Label(celda, textvariable=v["valor"], style="Suave.TLabel", width=9).pack(side="left")
            self.col_widgets += [chk, ent]
        if nch == 0:
            ttk.Label(self.fcols, text="(los canales aparecerán al llegar datos del sensor)",
                      style="Suave.TLabel").grid(row=0, column=3, columnspan=2, sticky="w", padx=6)
        self.bloquear_columnas(self.estado_boton == "grabando")

    def bloquear_columnas(self, bloquear):
        """Mientras se graba no se pueden cambiar las columnas."""
        estado = ["disabled"] if bloquear else ["!disabled"]
        for w in self.col_widgets + [self.btn_col_todas, self.btn_col_simple]:
            w.state(estado)

    @staticmethod
    def nombre_simple(cid):
        if cid == "t_s":
            return "tiempo"
        if cid.startswith("ch"):
            return f"data{int(cid[2:]) - 1}"
        return cid

    def columnas_todas(self):
        self.modo_simple = False
        for cid, v in self.cols.items():
            v["on"].set(True)
            v["nombre"].set(cid)

    def columnas_simple(self):
        """Formato del otro programa: tiempo, data0, data1…"""
        self.modo_simple = True
        for cid, v in self.cols.items():
            v["on"].set(cid not in ("seq", "idx"))
            v["nombre"].set(self.nombre_simple(cid))

    def actualizar_valores_columnas(self):
        """Muestra junto a cada columna el último valor recibido."""
        d = self.d
        with d.lock:
            nch, batch, fs, escrito = d.nch, d.batch, d.fs, d.escrito
            ultimo = d.buf[(escrito - 1) % len(d.buf)].tolist() if escrito and nch else None
            seq = d.ultimo_seq
            t_grab = d.grab.ultimo_t if d.grab is not None and d.grab.filas else None
        if ultimo is None:
            valores = {}
        else:
            t = t_grab if t_grab is not None else escrito / fs
            valores = {"t_s": f"{t:.3f}", "seq": seq, "idx": f"0…{batch - 1}"}
            valores.update({f"ch{i + 1}": x for i, x in enumerate(ultimo)})
        for cid, v in self.cols.items():
            v["valor"].set(str(valores.get(cid, "—")))

    # ----------------------------------------------------------------- otros
    def elegir_carpeta(self):
        c = filedialog.askdirectory(initialdir=self.var_carpeta.get() or os.path.expanduser("~"))
        if c:
            self.var_carpeta.set(c)

    def abrir_carpeta(self):
        c = self.var_carpeta.get()
        if not os.path.isdir(c):
            messagebox.showinfo(APP_NOMBRE, "La carpeta todavía no existe. Se creará al grabar.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(c)
            elif sys.platform == "darwin":
                os.system(f'open "{c}"')
            else:
                os.system(f'xdg-open "{c}"')
        except Exception:
            pass

    def al_cerrar(self):
        if self.d.grab and not messagebox.askyesno(APP_NOMBRE, "Hay una grabación en curso. ¿Pararla y salir?"):
            return
        self.desconectar()
        self.guardar_config()
        self.root.destroy()


def barra_titulo_oscura(root):
    """En Windows 10/11, pide al sistema que pinte oscura la barra de título."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        valor = ctypes.c_int(1)
        for atributo in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(valor),
                                                          ctypes.sizeof(valor)) == 0:
                break
    except Exception:
        pass


def main():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    barra_titulo_oscura(root)
    root.mainloop()


if __name__ == "__main__":
    main()
