"""Guardar secretos (la clave de API del asistente) cifrados para el usuario de Windows.

Usa DPAPI (CryptProtectData), lo mismo que usan los navegadores para las
contraseñas: el texto cifrado solo lo puede descifrar el mismo usuario de
Windows en el mismo equipo. Fuera de Windows (pruebas) se guarda en base64
marcado como "plain:", sin cifrar.
"""

import base64
import ctypes
import sys

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _api():
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    blob_p = ctypes.POINTER(_Blob)
    for fn in (crypt32.CryptProtectData, crypt32.CryptUnprotectData):
        fn.restype = ctypes.c_int
    crypt32.CryptProtectData.argtypes = [blob_p, ctypes.c_wchar_p, blob_p, ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_uint32, blob_p]
    crypt32.CryptUnprotectData.argtypes = [blob_p, ctypes.c_void_p, blob_p, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_uint32, blob_p]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _run(protect: bool, data: bytes) -> bytes:
    crypt32, kernel32 = _api()
    buf = (ctypes.c_ubyte * max(len(data), 1)).from_buffer_copy(data or b"\0")
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = _Blob()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), "BIOMEC Control", None, None, None,
                                      CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None,
                                        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise OSError(f"DPAPI falló (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def protect(text: str) -> str:
    data = text.encode("utf-8")
    if sys.platform != "win32":
        return "plain:" + base64.b64encode(data).decode()
    return "dpapi:" + base64.b64encode(_run(True, data)).decode()


def unprotect(token: str) -> str:
    kind, _, payload = token.partition(":")
    raw = base64.b64decode(payload)
    if kind == "plain":
        return raw.decode("utf-8")
    if kind == "dpapi" and sys.platform == "win32":
        return _run(False, raw).decode("utf-8")
    raise ValueError("Formato de secreto desconocido")
