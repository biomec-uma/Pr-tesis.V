#!/usr/bin/env python3
"""
Serial Logger (versión con ventana, tema oscuro)

Graba en .csv todo lo que un microcontrolador (ESP32, Arduino...) envía por el
puerto serie. Cada línea recibida es una fila; los valores se separan solos por
tabulador, coma, punto y coma o espacios.

Uso: elegir puerto y velocidad -> Conectar -> (nombre opcional) -> Empezar / Parar.

Requisito para ejecutar el .py:  pip install pyserial
Para crear el .exe: ejecutar build_exe.bat (logo.png e icono.ico en la misma carpeta)
"""

import collections
import csv
import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Falta la librería pyserial. Instálala con:  pip install pyserial")
    sys.exit(1)

APP_NOMBRE = "Serial Logger"
APP_SUBTITULO = "Grabación de datos por puerto serie"
CONFIG = os.path.join(os.path.expanduser("~"), ".serial_logger.json")
VELOCIDADES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
MAX_LINEAS_MONITOR = 500

# ============================================================================ COLORES
# Para cambiar el aspecto, basta con tocar estos valores ("#RRGGBB").
FONDO = "#1E1F22"            # fondo de la ventana
FONDO_CABECERA = "#151618"   # barra superior con el logo
FONDO_CAMPO = "#2B2D31"      # cajas de texto, desplegables, botones pequeños
FONDO_MONITOR = "#141517"    # cuadro de "Datos recibidos"
BORDE = "#3A3D43"
TEXTO = "#E4E6EB"            # texto normal
TEXTO_SUAVE = "#9AA0A8"      # textos secundarios
TEXTO_MONITOR = "#B8E0F5"    # texto de los datos recibidos
ACENTO = "#7CC8F2"           # títulos de sección y casillas marcadas

BOTON_GRABAR = "#7CC8F2"         # azul claro: "Empezar a grabar"
BOTON_GRABAR_PULSADO = "#5AB4E6"
BOTON_PARAR = "#FF9F43"          # naranja: "Parar"
BOTON_PARAR_PULSADO = "#F08A24"
BOTON_TEXTO = "#10202B"          # texto oscuro: se lee mejor sobre colores claros
BOTON_APAGADO = "#33363C"        # botón grande antes de conectar
BOTON_APAGADO_TEXTO = "#7A808A"

FUENTE = "Segoe UI"
LOGO = "logo.png"     # logo de la barra superior (PNG, junto al .py; se mete dentro del .exe)
ICONO = "icono.ico"   # icono de la ventana y del .exe


# ============================================================================ lógica (sin interfaz)

def recurso(nombre):
    """Ruta de un archivo (logo, icono) tanto al ejecutar el .py como dentro del .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nombre)


def es_numero(s):
    return bool(NUM_RE.match(s))


def separar(linea):
    for s in ("\t", ",", ";"):
        if s in linea:
            return [c.strip() for c in linea.split(s)]
    return linea.split()


def limpiar_nombre(nombre):
    nombre = nombre.strip().replace(" ", "_")
    nombre = re.sub(r"[^\w\-]", "", nombre)
    return nombre or "grabacion"


def abrir_puerto(puerto, baudios):
    ser = serial.Serial()
    ser.port = puerto
    ser.baudrate = baudios
    ser.timeout = 0.1
    ser.dtr = False  # no reiniciar / no dejar en modo boot a los ESP32 al abrir
    ser.rts = False
    ser.open()
    ser.reset_input_buffer()
    return ser


class Grabacion:
    """Un archivo .csv abierto. procesar() se llama desde el hilo lector."""

    def __init__(self, ruta, solo_numeros=False, excel=False, tiempo=True, cabecera=""):
        self.ruta = ruta
        self.solo_numeros = solo_numeros
        self.excel = excel
        self.tiempo = tiempo
        self.cabecera = [c.strip() for c in cabecera.split(",") if c.strip()]
        self.f = open(ruta, "w", newline="", encoding="utf-8-sig")
        self.writer = csv.writer(self.f, delimiter=";" if excel else ",")
        self.cabecera_escrita = False
        self.t0 = time.time()
        self.ultimo_flush = self.t0
        self.guardadas = 0
        self.ignoradas = 0

    def procesar(self, linea):
        campos = separar(linea)
        if self.solo_numeros and not all(es_numero(c) for c in campos):
            self.ignoradas += 1
            return
        ahora = time.time()
        if self.excel:
            campos = [c.replace(".", ",") if es_numero(c) else c for c in campos]
        if not self.cabecera_escrita:
            nombres = self.cabecera or [f"col{i + 1}" for i in range(len(campos))]
            if self.tiempo:
                nombres = ["fecha_hora", "t_s"] + nombres
            self.writer.writerow(nombres)
            self.cabecera_escrita = True
        if self.tiempo:
            t_rel = f"{ahora - self.t0:.3f}"
            if self.excel:
                t_rel = t_rel.replace(".", ",")
            campos = [dt.datetime.now().isoformat(timespec="milliseconds"), t_rel] + campos
        self.writer.writerow(campos)
        self.guardadas += 1
        if ahora - self.ultimo_flush >= 1:
            self.f.flush()
            self.ultimo_flush = ahora

    def duracion(self):
        return time.time() - self.t0

    def cerrar(self):
        self.f.flush()
        self.f.close()


class Lector(threading.Thread):
    """Lee el puerto continuamente. Si hay una grabación activa, le pasa cada línea."""

    def __init__(self, ser, puerto, baudios):
        super().__init__(daemon=True)
        self.ser = ser
        self.puerto = puerto
        self.baudios = baudios
        self.parar_evento = threading.Event()
        self.lock = threading.Lock()
        self.grab = None
        self.monitor = collections.deque(maxlen=MAX_LINEAS_MONITOR)
        self.eventos = queue.Queue()
        self.total = 0

    def empezar_grabacion(self, grab):
        with self.lock:
            self.grab = grab

    def parar_grabacion(self):
        with self.lock:
            g, self.grab = self.grab, None
        if g:
            g.cerrar()
        return g

    def run(self):
        while not self.parar_evento.is_set():
            try:
                if self.ser is None:
                    self.ser = abrir_puerto(self.puerto, self.baudios)
                    self.eventos.put(("ok", f"Reconectado a {self.puerto}"))
                raw = self.ser.readline()
            except (serial.SerialException, OSError):
                if self.ser is not None:
                    self.eventos.put(("aviso", f"{self.puerto} desconectado, reintentando..."))
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                self.ser = None
                time.sleep(1)
                continue
            if not raw:
                continue
            linea = raw.decode("utf-8", errors="replace").strip()
            if not linea:
                continue
            self.total += 1
            self.monitor.append(linea)
            with self.lock:
                if self.grab is not None:
                    try:
                        self.grab.procesar(linea)
                    except Exception as e:
                        self.eventos.put(("error", f"Error al escribir el archivo: {e}"))
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass

    def detener(self):
        self.parar_evento.set()


# ============================================================================ ventana

class App:
    def __init__(self, root):
        self.root = root
        self.lector = None
        self.puertos = {}
        self.ultimo_total = 0
        self.ultimo_t = time.time()
        self.lps = 0.0
        cfg = self.cargar_config()

        root.title(APP_NOMBRE)
        root.minsize(640, 600)
        root.configure(bg=FONDO)
        self.aplicar_tema_oscuro()
        self.poner_icono()
        pad = {"padx": 6, "pady": 4}

        # --- Cabecera con logo
        cab = tk.Frame(root, bg=FONDO_CABECERA)
        cab.pack(fill="x")
        self.logo_img = None  # se guarda en self: si no, Python borra la imagen y sale en blanco
        if os.path.exists(recurso(LOGO)):
            try:
                self.logo_img = tk.PhotoImage(file=recurso(LOGO))
                tk.Label(cab, image=self.logo_img, bg=FONDO_CABECERA).pack(side="left", padx=(14, 10), pady=10)
            except tk.TclError:
                self.logo_img = None
        txt_cab = tk.Frame(cab, bg=FONDO_CABECERA)
        txt_cab.pack(side="left", padx=(0 if self.logo_img else 14, 0), pady=10)
        tk.Label(txt_cab, text=APP_NOMBRE, bg=FONDO_CABECERA, fg=TEXTO,
                 font=(FUENTE, 15, "bold")).pack(anchor="w")
        tk.Label(txt_cab, text=APP_SUBTITULO, bg=FONDO_CABECERA, fg=TEXTO_SUAVE,
                 font=(FUENTE, 9)).pack(anchor="w")

        # --- Conexión
        fc = ttk.LabelFrame(root, text="1. Conexión")
        fc.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(fc, text="Puerto:").grid(row=0, column=0, sticky="w", **pad)
        self.cb_puerto = ttk.Combobox(fc, state="readonly", width=28)
        self.cb_puerto.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(fc, text="↻", width=3, command=self.refrescar_puertos).grid(row=0, column=2, **pad)
        ttk.Label(fc, text="Velocidad:").grid(row=0, column=3, sticky="w", **pad)
        self.cb_baud = ttk.Combobox(fc, values=VELOCIDADES, width=9)
        self.cb_baud.set(cfg.get("baudios", "115200"))
        self.cb_baud.grid(row=0, column=4, **pad)
        self.btn_conectar = ttk.Button(fc, text="Conectar", command=self.conectar)
        self.btn_conectar.grid(row=0, column=5, **pad)
        fc.columnconfigure(1, weight=1)

        # --- Grabación
        fg = ttk.LabelFrame(root, text="2. Grabación")
        fg.pack(fill="x", padx=10, pady=4)
        ttk.Label(fg, text="Carpeta:").grid(row=0, column=0, sticky="w", **pad)
        self.var_carpeta = tk.StringVar(value=cfg.get("carpeta", os.path.join(os.path.expanduser("~"), "Documents")))
        ttk.Entry(fg, textvariable=self.var_carpeta).grid(row=0, column=1, columnspan=3, sticky="ew", **pad)
        ttk.Button(fg, text="Elegir…", command=self.elegir_carpeta).grid(row=0, column=4, **pad)
        ttk.Button(fg, text="Abrir", command=self.abrir_carpeta).grid(row=0, column=5, **pad)

        ttk.Label(fg, text="Nombre:").grid(row=1, column=0, sticky="w", **pad)
        self.var_nombre = tk.StringVar(value=cfg.get("nombre", ""))
        ttk.Entry(fg, textvariable=self.var_nombre).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Label(fg, text="Parar a los (s):").grid(row=1, column=2, sticky="e", **pad)
        self.var_duracion = tk.StringVar(value="")
        ttk.Entry(fg, textvariable=self.var_duracion, width=7).grid(row=1, column=3, sticky="w", **pad)

        ttk.Label(fg, text="Columnas:").grid(row=2, column=0, sticky="w", **pad)
        self.var_cabecera = tk.StringVar(value=cfg.get("cabecera", ""))
        ttk.Entry(fg, textvariable=self.var_cabecera).grid(row=2, column=1, columnspan=3, sticky="ew", **pad)
        ttk.Label(fg, text="ej: seq,idx,ch1", style="Suave.TLabel").grid(
            row=2, column=4, columnspan=2, sticky="w", **pad)

        fo = ttk.Frame(fg)
        fo.grid(row=3, column=0, columnspan=6, sticky="w", **pad)
        self.var_solo_num = tk.BooleanVar(value=cfg.get("solo_numeros", True))
        self.var_tiempo = tk.BooleanVar(value=cfg.get("tiempo", True))
        self.var_excel = tk.BooleanVar(value=cfg.get("excel", False))
        ttk.Checkbutton(fo, text="Solo líneas numéricas", variable=self.var_solo_num).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(fo, text="Añadir hora y tiempo", variable=self.var_tiempo).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(fo, text="Formato Excel (; y coma decimal)", variable=self.var_excel).pack(side="left")
        fg.columnconfigure(1, weight=1)

        # --- Botón grande + estado
        fb = ttk.Frame(root)
        fb.pack(fill="x", padx=10, pady=6)
        self.btn_grabar = tk.Button(fb, font=(FUENTE, 12, "bold"), relief="flat", bd=0, height=2,
                                    cursor="hand2", command=self.alternar_grabacion)
        self.btn_grabar.pack(fill="x")
        self.boton_estado("apagado")
        self.var_estado = tk.StringVar(value="Desconectado. Elige el puerto y pulsa Conectar.")
        ttk.Label(root, textvariable=self.var_estado, anchor="w", style="Suave.TLabel").pack(fill="x", padx=12)

        # --- Monitor
        fm = ttk.LabelFrame(root, text="Datos recibidos")
        fm.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        barra = ttk.Frame(fm)
        barra.pack(fill="x")
        self.var_monitor = tk.BooleanVar(value=True)
        ttk.Checkbutton(barra, text="Mostrar datos", variable=self.var_monitor).pack(side="left", padx=4)
        ttk.Button(barra, text="Limpiar", command=lambda: self.txt.delete("1.0", "end")).pack(side="right", padx=4)
        self.txt = tk.Text(fm, height=12, font=("Consolas", 9), wrap="none",
                           bg=FONDO_MONITOR, fg=TEXTO_MONITOR, insertbackground=TEXTO,
                           selectbackground="#2F5D7C", relief="flat", highlightthickness=1,
                           highlightbackground=BORDE, highlightcolor=BORDE, padx=6, pady=4)
        sb = ttk.Scrollbar(fm, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=(4, 4))
        self.txt.pack(fill="both", expand=True, padx=(4, 0), pady=4)

        self.refrescar_puertos(cfg.get("puerto"))
        root.protocol("WM_DELETE_WINDOW", self.al_cerrar)
        root.after(100, self.tick)

    # ----------------------------------------------------------------- aspecto
    def aplicar_tema_oscuro(self):
        # La lista desplegable de los Combobox no es ttk: se colorea con option_add
        self.root.option_add("*TCombobox*Listbox.background", FONDO_CAMPO)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXTO)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#2F5D7C")
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXTO)

        st = ttk.Style()
        st.theme_use("clam")  # el tema de Windows ignora los colores; 'clam' los respeta
        st.configure(".", background=FONDO, foreground=TEXTO, bordercolor=BORDE,
                     lightcolor=FONDO, darkcolor=FONDO, troughcolor=FONDO, font=(FUENTE, 9))
        st.configure("TFrame", background=FONDO)
        st.configure("TLabel", background=FONDO, foreground=TEXTO)
        st.configure("Suave.TLabel", background=FONDO, foreground=TEXTO_SUAVE)
        st.configure("TLabelframe", background=FONDO, bordercolor=BORDE)
        st.configure("TLabelframe.Label", background=FONDO, foreground=ACENTO, font=(FUENTE, 10, "bold"))

        st.configure("TCheckbutton", background=FONDO, foreground=TEXTO, indicatorbackground=FONDO_CAMPO,
                     indicatorforeground=FONDO, indicatormargin=(0, 0, 6, 0))
        st.map("TCheckbutton", background=[("active", FONDO)],
               indicatorbackground=[("selected", ACENTO), ("active", BORDE)])

        st.configure("TEntry", fieldbackground=FONDO_CAMPO, foreground=TEXTO, insertcolor=TEXTO,
                     bordercolor=BORDE, lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO, padding=3)
        st.map("TEntry", bordercolor=[("focus", ACENTO)], lightcolor=[("focus", ACENTO)])

        st.configure("TCombobox", fieldbackground=FONDO_CAMPO, background=FONDO_CAMPO, foreground=TEXTO,
                     arrowcolor=TEXTO, bordercolor=BORDE, lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO,
                     selectbackground=FONDO_CAMPO, selectforeground=TEXTO, padding=3)
        st.map("TCombobox",
               fieldbackground=[("readonly", FONDO_CAMPO), ("disabled", FONDO)],
               foreground=[("disabled", TEXTO_SUAVE)],
               background=[("active", BORDE)],
               arrowcolor=[("disabled", TEXTO_SUAVE)])

        st.configure("TButton", background=FONDO_CAMPO, foreground=TEXTO, bordercolor=BORDE,
                     lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO, padding=(10, 3), focuscolor=FONDO_CAMPO)
        st.map("TButton", background=[("pressed", FONDO), ("active", BORDE)])

        st.configure("Vertical.TScrollbar", background=FONDO_CAMPO, troughcolor=FONDO_MONITOR,
                     bordercolor=FONDO_MONITOR, arrowcolor=TEXTO_SUAVE,
                     lightcolor=FONDO_CAMPO, darkcolor=FONDO_CAMPO)
        st.map("Vertical.TScrollbar", background=[("active", BORDE)])

    def boton_estado(self, estado):
        """Colores del botón grande: 'apagado' (sin conectar), 'listo' o 'grabando'."""
        if estado == "apagado":
            self.btn_grabar.config(text="●  EMPEZAR A GRABAR", state="disabled", bg=BOTON_APAGADO,
                                   disabledforeground=BOTON_APAGADO_TEXTO, cursor="arrow")
        elif estado == "listo":
            self.btn_grabar.config(text="●  EMPEZAR A GRABAR", state="normal", bg=BOTON_GRABAR,
                                   fg=BOTON_TEXTO, activebackground=BOTON_GRABAR_PULSADO,
                                   activeforeground=BOTON_TEXTO, cursor="hand2")
        else:
            self.btn_grabar.config(text="■  PARAR", state="normal", bg=BOTON_PARAR,
                                   fg=BOTON_TEXTO, activebackground=BOTON_PARAR_PULSADO,
                                   activeforeground=BOTON_TEXTO, cursor="hand2")

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
        cfg = {
            "puerto": self.puertos.get(self.cb_puerto.get(), ""),
            "baudios": self.cb_baud.get(),
            "carpeta": self.var_carpeta.get(),
            "nombre": self.var_nombre.get(),
            "cabecera": self.var_cabecera.get(),
            "solo_numeros": self.var_solo_num.get(),
            "tiempo": self.var_tiempo.get(),
            "excel": self.var_excel.get(),
        }
        try:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    # ----------------------------------------------------------------- puertos
    def refrescar_puertos(self, preferido=None):
        lista = sorted(list_ports.comports(), key=lambda p: p.device)
        self.puertos = {f"{p.device} – {p.description}": p.device for p in lista}
        textos = list(self.puertos)
        self.cb_puerto["values"] = textos
        if not textos:
            self.cb_puerto.set("")
            self.var_estado.set("No se encuentra ningún puerto. Conecta la placa y pulsa ↻.")
            return
        elegido = None
        for t, dev in self.puertos.items():
            if dev == preferido:
                elegido = t
        if elegido is None:  # preferir placas USB (los puertos Bluetooth no tienen VID)
            usb = [f"{p.device} – {p.description}" for p in lista if p.vid is not None]
            elegido = usb[0] if usb else textos[0]
        self.cb_puerto.set(elegido)

    def conectar(self):
        if self.lector:
            self.desconectar()
            return
        dev = self.puertos.get(self.cb_puerto.get())
        if not dev:
            messagebox.showwarning(APP_NOMBRE, "Elige un puerto.")
            return
        try:
            baud = int(self.cb_baud.get())
        except ValueError:
            messagebox.showwarning(APP_NOMBRE, "La velocidad debe ser un número (ej. 115200).")
            return
        try:
            ser = abrir_puerto(dev, baud)
        except serial.SerialException as e:
            txt = str(e).lower()
            if "denegado" in txt or "denied" in txt or "permissionerror" in txt:
                messagebox.showerror(APP_NOMBRE, f"El puerto {dev} está ocupado.\n\nCierra el monitor serie "
                                     "de PlatformIO / Arduino u otro programa que lo esté usando.")
            else:
                messagebox.showerror(APP_NOMBRE, f"No se pudo abrir {dev}:\n{e}")
            return
        self.lector = Lector(ser, dev, baud)
        self.lector.start()
        self.ultimo_total, self.ultimo_t = 0, time.time()
        self.btn_conectar.config(text="Desconectar")
        self.cb_puerto.config(state="disabled")
        self.cb_baud.config(state="disabled")
        self.boton_estado("listo")
        self.guardar_config()

    def desconectar(self):
        if self.lector and self.lector.grab:
            self.parar()
        if self.lector:
            self.lector.detener()
            self.lector = None
        self.btn_conectar.config(text="Conectar")
        self.cb_puerto.config(state="readonly")
        self.cb_baud.config(state="normal")
        self.boton_estado("apagado")
        self.var_estado.set("Desconectado.")

    # ----------------------------------------------------------------- grabación
    def alternar_grabacion(self):
        if self.lector and self.lector.grab:
            self.parar()
        else:
            self.empezar()

    def empezar(self):
        carpeta = self.var_carpeta.get().strip() or "."
        try:
            os.makedirs(carpeta, exist_ok=True)
            marca = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta = os.path.join(carpeta, f"{limpiar_nombre(self.var_nombre.get())}_{marca}.csv")
            grab = Grabacion(ruta, self.var_solo_num.get(), self.var_excel.get(),
                             self.var_tiempo.get(), self.var_cabecera.get())
        except Exception as e:
            messagebox.showerror(APP_NOMBRE, f"No se pudo crear el archivo:\n{e}")
            return
        self.lector.empezar_grabacion(grab)
        self.boton_estado("grabando")
        self.guardar_config()

    def parar(self):
        g = self.lector.parar_grabacion()
        self.boton_estado("listo")
        if g:
            d = g.duracion()
            extra = f", {g.ignoradas} de texto descartadas" if g.ignoradas else ""
            msg = f"Guardado: {os.path.basename(g.ruta)} — {g.guardadas} filas en {d:.1f} s{extra}"
            self.var_estado.set(msg)
            self.escribir_monitor([f"--- {msg} ---"])
            if g.guardadas == 0:
                messagebox.showwarning(APP_NOMBRE, "La grabación está vacía: no llegó ninguna línea válida.\n"
                                       "Revisa la velocidad o desmarca 'Solo líneas numéricas'.")

    # ----------------------------------------------------------------- refresco periódico
    def escribir_monitor(self, lineas):
        self.txt.insert("end", "\n".join(lineas) + "\n")
        exceso = int(self.txt.index("end-1c").split(".")[0]) - MAX_LINEAS_MONITOR
        if exceso > 0:
            self.txt.delete("1.0", f"{exceso + 1}.0")
        self.txt.see("end")

    def tick(self):
        lec = self.lector
        if lec:
            while not lec.eventos.empty():
                tipo, msg = lec.eventos.get()
                self.escribir_monitor([f"[{msg}]"])
                if tipo == "error":
                    messagebox.showerror(APP_NOMBRE, msg)
            nuevas = []
            while lec.monitor:
                nuevas.append(lec.monitor.popleft())
            if nuevas and self.var_monitor.get():
                self.escribir_monitor(nuevas[-200:])
            ahora = time.time()
            if ahora - self.ultimo_t >= 1:
                self.lps = (lec.total - self.ultimo_total) / (ahora - self.ultimo_t)
                self.ultimo_total, self.ultimo_t = lec.total, ahora
            g = lec.grab
            if g:
                d = g.duracion()
                self.var_estado.set(f"● GRABANDO {os.path.basename(g.ruta)} — {g.guardadas} filas — "
                                    f"{d:.1f} s — {self.lps:.0f} líneas/s")
                try:
                    lim = float(self.var_duracion.get().replace(",", "."))
                except ValueError:
                    lim = 0
                if lim > 0 and d >= lim:
                    self.parar()
            elif not self.var_estado.get().startswith("Guardado"):
                if lec.total == 0:
                    self.var_estado.set(f"Conectado a {lec.puerto}, esperando datos… "
                                        "(si no llega nada, revisa la velocidad o pulsa RESET en la placa)")
                else:
                    self.var_estado.set(f"Conectado a {lec.puerto} — recibiendo {self.lps:.0f} líneas/s. "
                                        "Pulsa EMPEZAR para grabar.")
        self.root.after(100, self.tick)

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
        if self.lector and self.lector.grab:
            if not messagebox.askyesno(APP_NOMBRE, "Hay una grabación en curso. ¿Pararla y salir?"):
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
        for atributo in (20, 19):  # 20 = Windows 11 / Win10 recientes, 19 = Win10 antiguos
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(valor),
                                                          ctypes.sizeof(valor)) == 0:
                break
    except Exception:
        pass


def main():
    if sys.platform.startswith("win"):
        try:  # texto nítido en pantallas con escalado
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
