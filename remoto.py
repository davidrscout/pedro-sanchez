# -*- coding: utf-8 -*-
"""Control remoto del PC desde el panel web: captura ligera, ratón, teclado y ventanas. Solo ctypes + Pillow.
Las coordenadas llegan NORMALIZADAS (0..1) sobre la pantalla principal, así el móvil no necesita saber la resolución."""
import ctypes
import io
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # coordenadas físicas, iguales a las de la captura
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

ULONG_PTR = ctypes.c_size_t
MOUSEEVENTF = {"move": 0x0001, "ld": 0x0002, "lu": 0x0004, "rd": 0x0008, "ru": 0x0010, "md": 0x0020, "mu": 0x0040, "wheel": 0x0800}
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def pantalla_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)      # pantalla principal


# ---------------------------------------------------------------- captura (pantalla principal, ligera)
def captura(ancho=1100, calidad=60):
    from PIL import ImageGrab
    ancho = max(320, min(int(ancho), 2400))
    calidad = max(25, min(int(calidad), 90))
    w, h = pantalla_size()
    img = ImageGrab.grab(bbox=(0, 0, w, h)).convert("RGB")
    if img.width > ancho:
        img = img.resize((ancho, max(1, round(img.height * ancho / img.width))))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=calidad)
    return buf.getvalue()


# ---------------------------------------------------------------- ratón
def _abs(nx, ny):
    w, h = pantalla_size()
    x = int(max(0.0, min(1.0, float(nx))) * (w - 1))
    y = int(max(0.0, min(1.0, float(ny))) * (h - 1))
    return x, y


def _boton(b):
    return ("ld", "lu") if b == "izq" else ("rd", "ru") if b == "der" else ("md", "mu")


def _mouse(flag, data=0):
    _send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, data & 0xFFFFFFFF, MOUSEEVENTF[flag], 0, 0))))


def raton(d):
    """d: {accion: mover|clic|doble|abrir|arrastrar_ini|arrastrar_fin|rueda, x, y, boton, delta}"""
    a = str(d.get("accion", ""))
    if a == "pos":                       # dónde está el cursor ahora (para pintar la flecha del modo ratón)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        w, h = pantalla_size()
        return {"x": max(0.0, min(1.0, pt.x / max(1, w - 1))), "y": max(0.0, min(1.0, pt.y / max(1, h - 1)))}
    if a in ("mover", "clic", "doble", "arrastrar_ini", "arrastrar_fin") and "x" in d:
        x, y = _abs(d.get("x", 0), d.get("y", 0))
        user32.SetCursorPos(x, y)
    b = str(d.get("boton", "izq"))
    if b not in ("izq", "der", "medio"):
        b = "izq"
    dn, up = _boton(b)
    if a == "mover":
        return "ok"
    if a == "clic":
        _mouse(dn); _mouse(up)
    elif a == "doble":
        for _ in range(2):
            _mouse(dn); _mouse(up); time.sleep(0.04)
    elif a == "arrastrar_ini":
        _mouse(dn)
    elif a == "arrastrar_fin":
        _mouse(up)
    elif a != "rueda":
        raise ValueError("acción de ratón desconocida")
    if a == "rueda":
        delta = max(-1200, min(1200, int(d.get("delta", 0))))
        _mouse("wheel", delta)
    return "ok"


# ---------------------------------------------------------------- teclado
VK = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "retroceso": 0x08, "borrar": 0x2E, "espacio": 0x20,
      "izq": 0x25, "arriba": 0x26, "der": 0x27, "abajo": 0x28, "inicio": 0x24, "fin": 0x23, "repag": 0x21, "avpag": 0x22,
      "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "impr": 0x2C, "menu": 0x5D,
      "mute": 0xAD, "vol-": 0xAE, "vol+": 0xAF, "pausa": 0xB3, "sig": 0xB0, "ant": 0xB1}
for i in range(1, 13):
    VK[f"f{i}"] = 0x6F + i
BLOQUEADO = {("ctrl", "alt", "borrar")}    # Ctrl+Alt+Supr no se puede (ni se debe) inyectar


def _vk(vk, up=False):
    _send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0))))


def escribir(texto):
    """Teclea texto Unicode literal (acentos, ñ, emojis...)."""
    texto = str(texto)[:400]
    ev = []
    raw = texto.encode("utf-16-le")
    for i in range(0, len(raw), 2):
        code = raw[i] | (raw[i + 1] << 8)
        ev.append(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0))))
        ev.append(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))))
    for i in range(0, len(ev), 60):
        _send(*ev[i:i + 60])
        time.sleep(0.01)
    return "ok"


def combo(teclas):
    """teclas: lista como ['ctrl','shift','esc'] o ['a']. Pulsa en orden y suelta en orden inverso."""
    ks = [str(t).lower() for t in teclas][:5]
    if tuple(ks) in BLOQUEADO or not ks:
        raise ValueError("combinación no permitida")
    codes = []
    for k in ks:
        if k in VK:
            codes.append(VK[k])
        elif len(k) == 1:
            r = user32.VkKeyScanW(ord(k)) & 0xFF
            if r == 0xFF:
                raise ValueError("tecla desconocida: " + k)
            codes.append(r)
        else:
            raise ValueError("tecla desconocida: " + k)
    for c in codes:
        _vk(c)
    for c in reversed(codes):
        _vk(c, up=True)
    return "ok"


# ---------------------------------------------------------------- ventanas
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
SW = {"min": 6, "max": 3, "restaurar": 9}
IGNORAR = {"Program Manager", "Windows Input Experience", "Microsoft Text Input Application", "Configuración"}


def ventanas():
    res = []
    fg = user32.GetForegroundWindow()

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):    # GW_OWNER
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            t = buf.value
            ex = user32.GetWindowLongW(hwnd, -20)
            if t in IGNORAR or (ex & 0x80):                                       # WS_EX_TOOLWINDOW
                return True
            cloaked = wintypes.DWORD(0)
            try:
                ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)   # DWMWA_CLOAKED
            except Exception:
                pass
            if cloaked.value:
                return True
            res.append({"id": int(hwnd), "titulo": t[:120], "activa": int(hwnd) == int(fg or 0), "min": bool(user32.IsIconic(hwnd))})
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return res


def ventana(hwnd, accion):
    hwnd = int(hwnd)
    if hwnd not in {v["id"] for v in ventanas()}:
        raise ValueError("esa ventana ya no existe")
    if accion == "foco":
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        _vk(VK["alt"]); _vk(VK["alt"], up=True)                                   # truco: permite SetForegroundWindow
        user32.SetForegroundWindow(hwnd)
    elif accion == "cerrar":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)                                    # WM_CLOSE: la app puede pedir guardar
    elif accion in SW:
        user32.ShowWindow(hwnd, SW[accion])
    else:
        raise ValueError("acción de ventana desconocida")
    return "ok"
