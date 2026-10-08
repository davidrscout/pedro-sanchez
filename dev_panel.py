# -*- coding: utf-8 -*-
"""Servidor de DESARROLLO del panel: datos falsos, sin túnel, sin tocar el PC. Para diseñar la interfaz.
   python dev_panel.py   -> imprime un enlace http://127.0.0.1:18777/t/... (PIN 2404, alta 12345678, vale 24 h). Recarga ui\*.html al vuelo."""
import os, secrets, tempfile, threading, time, io
from pathlib import Path
import webpanel as w

w.STATE_F, w.LOCK_F, w.PORT = Path(tempfile.mkdtemp()) / "st.json", Path(tempfile.mkdtemp()) / "LOCKED", 18777
w.TOKEN_TTL, w.NONCE_TTL, w.SESSION_IDLE, w.SESSION_MAX = 86400, 86400, 86400, 86400
state = {"cpu": 12}

def estado():
    state["cpu"] = (state["cpu"] * 7 + int.from_bytes(os.urandom(1), "big") % 60) // 8
    return (f"CPU {state['cpu']} % | RAM libre 20372 MB de 32022\nGPU 38 °C, 15 W, 1 % uso, VRAM 1245/16311 MB, P3\n"
            "Disco C: libre 29 GB\nEncendido desde hace 1:30:54\nWatchdog: activo (último latido hace 0 s)")

def captura():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1280, 720), (8, 12, 22)); d = ImageDraw.Draw(im)
    for i in range(0, 1280, 64): d.line([(i, 0), (i, 720)], fill=(20, 32, 52))
    d.rectangle([120, 90, 1160, 630], outline=(56, 189, 248), width=3); d.text((140, 110), "CAPTURA DE PRUEBA", fill=(56, 189, 248))
    b = io.BytesIO(); im.save(b, "JPEG"); return b.getvalue()

def brain(p, mode):
    time.sleep(2.5); return f"[{mode}] Respuesta de prueba a: {p}\n\nEsto simula el cerebro. Línea 2 de ejemplo para ver el formato del texto."

w.H.update({"log": print, "alert": print, "estado": estado, "eventos": lambda: "Eventos graves últimas 24 h:\n02/10 11:58 id17 WHEA-Logger (EJEMPLO)",
            "captura": captura, "bloquear": lambda: None, "pantalla": lambda: None, "ahorro": lambda: None, "vol": lambda a: None,
            "abrir": lambda a: f"Abriendo {a}.", "power": lambda k: f"(simulado) {k}", "brain": brain})
w.CFG["JARVIS_PIN_HASH"] = w.make_hash("2404")
w.CFG["JARVIS_ENROLL_HASH"] = w.make_hash("12345678")   # código de alta de PRUEBA
w.TUN["url"] = "http://127.0.0.1:18777"
w.ensure_server()
tok = secrets.token_urlsafe(12); w.TOKENS[tok] = {"t": time.time(), "fails": 0, "dead": False}
print(f"\nENLACE DEV (PIN 2404): http://127.0.0.1:18777/t/{tok}\nCtrl+C para salir\n", flush=True)
try:
    while True: time.sleep(3600)
except KeyboardInterrupt:
    pass
