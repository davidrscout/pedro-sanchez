# -*- coding: utf-8 -*-
"""Lanzadores del panel (launchers.json). El navegador solo manda un id: los comandos viven aquí, no en la web."""
import json
import os
import subprocess
from pathlib import Path

HOME = Path(__file__).resolve().parent
FILE = HOME / "launchers.json"
NOWIN = 0x08000000
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PERFIL = "Profile 1"      # el perfil de Chrome de David con sus sesiones iniciadas


def _cargar():
    return json.loads(FILE.read_text(encoding="utf-8"))


def lista_publica():
    """Lo que ve el navegador: sin comandos ni rutas internas (solo la URL de los enlaces)."""
    d = _cargar()
    items = []
    for it in d["items"]:
        pub = {k: it[k] for k in ("id", "grupo", "label", "tipo", "desc", "backend", "modo") if k in it}
        pub["confirmar"] = bool(it.get("confirmar"))
        if it["tipo"] == "url":
            pub["url"] = it["destino"]
        if it["tipo"] == "ia":
            pub["prompt"] = it["destino"]
        items.append(pub)
    return {"grupos": d["grupos"], "items": items}


def _buscar(i):
    for it in _cargar()["items"]:
        if it["id"] == i:
            return it
    return None


def _truncar(t, n=8000):
    t = (t or "").strip()
    return t if len(t) <= n else t[:n] + "\n… (recortado)"


def ejecutar(i, confirm=False, donde="pc"):
    """Devuelve dict {text, url?}. Los 'ia' no se ejecutan aquí: la web rellena el chat."""
    it = _buscar(i)
    if not it:
        return {"text": "Lanzador desconocido."}
    if it.get("confirmar") and confirm is not True:
        return {"text": "Hace falta confirmación."}
    t, dest = it["tipo"], os.path.expandvars(it["destino"])
    if t == "url":
        if donde == "pc":
            subprocess.Popen([CHROME, f"--profile-directory={PERFIL}", dest], creationflags=NOWIN)
            return {"text": f"Abierto en el PC: {it['label']}", "url": dest}
        return {"text": "Abriendo en este móvil.", "url": dest}
    if t in ("app", "carpeta"):
        os.startfile(dest)
        return {"text": f"Abierto: {it['label']}"}
    if t == "cmd":
        r = subprocess.run(["powershell", "-NoProfile", "-Command", dest], capture_output=True, timeout=90, creationflags=NOWIN)
        return {"text": _truncar(r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")) or "(sin salida)"}
    if t == "ssh":
        vps = _cargar()["vps"]
        r = subprocess.run(["ssh", "-i", vps["clave"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
                            "-o", "StrictHostKeyChecking=accept-new", vps["host"], dest],
                           capture_output=True, timeout=90, creationflags=NOWIN)
        out = r.stdout.decode("utf-8", errors="replace") + r.stderr.decode("utf-8", errors="replace")
        return {"text": _truncar(out) or "(sin salida)"}
    return {"text": "Tipo no soportado."}
