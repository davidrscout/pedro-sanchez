# -*- coding: utf-8 -*-
"""Recordatorios y tareas programadas (idea de OpenJarvis scheduler/), sin dependencias.
- tipo 'aviso': a su hora Jarvis manda el texto por Telegram.
- tipo 'tarea': a su hora Pedro ejecuta el texto como pregunta (solo lectura) y manda la respuesta.
- repetir: 'no' | 'diario' | 'laborables' | 'semanal' | 'cada:<minutos>'.
También guarda la BANDEJA: mensajes que el servidor de herramientas pide mandar a David (Jarvis los envía; así el token
de Telegram nunca sale de jarvis.py)."""
import datetime as dt
import json
import os
import re
import time
import uuid
from pathlib import Path

HOME = Path(__file__).resolve().parent
FILE = HOME / "agenda.json"
BANDEJA = HOME / "bandeja.json"
CANDADO = HOME / "agenda.lock"
REPETIR = re.compile(r"^(no|diario|laborables|semanal|cada:\d{1,5})$")
MAX = 100


class _Candado:
    """Exclusión entre procesos (Jarvis y el servidor MCP) con un fichero creado en exclusiva."""
    def __enter__(self):
        t0 = time.time()
        while True:
            try:
                self.fd = os.open(str(CANDADO), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - CANDADO.stat().st_mtime > 10:   # candado huérfano
                        CANDADO.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() - t0 > 5:
                    raise TimeoutError("agenda ocupada")
                time.sleep(0.05)

    def __exit__(self, *a):
        os.close(self.fd)
        CANDADO.unlink(missing_ok=True)


def _leer(p):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _escribir(p, items):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def parse_cuando(s, ahora=None):
    """Acepta 'YYYY-MM-DD HH:MM', 'HH:MM' (hoy o mañana si ya pasó) o '+N' minutos / '+Nh'."""
    ahora = ahora or dt.datetime.now()
    s = str(s or "").strip().replace("T", " ")
    m = re.fullmatch(r"\+(\d{1,5})\s*(m|min|h)?", s)
    if m:
        n = int(m.group(1))
        return ahora + (dt.timedelta(hours=n) if m.group(2) == "h" else dt.timedelta(minutes=n))
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        c = ahora.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return c if c > ahora else c + dt.timedelta(days=1)
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    raise ValueError("Hora no válida: usa 'YYYY-MM-DD HH:MM', 'HH:MM' o '+30' (minutos).")


def crear(cuando, texto, tipo="aviso", repetir="no"):
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()[:1500]
    if not texto:
        return "Falta el texto."
    if tipo not in ("aviso", "tarea"):
        return "tipo debe ser 'aviso' o 'tarea'."
    repetir = str(repetir or "no").strip().lower()
    if not REPETIR.match(repetir) or (repetir.startswith("cada:") and int(repetir[5:]) < 5):
        return "repetir: no | diario | laborables | semanal | cada:<minutos> (mínimo 5)."
    try:
        c = parse_cuando(cuando)
    except ValueError as e:
        return str(e)
    if c < dt.datetime.now() - dt.timedelta(minutes=1):
        return "Esa hora ya ha pasado."
    with _Candado():
        items = _leer(FILE)
        if len(items) >= MAX:
            return f"Agenda llena ({MAX}). Borra alguno."
        it = {"id": uuid.uuid4().hex[:6], "cuando": c.strftime("%Y-%m-%d %H:%M"), "texto": texto, "tipo": tipo,
              "repetir": repetir, "creado": time.strftime("%Y-%m-%d %H:%M")}
        items.append(it)
        _escribir(FILE, items)
    return f"Programado {tipo} para {it['cuando']} (repetir: {repetir}, id {it['id']})."


def listar():
    return sorted(_leer(FILE), key=lambda i: i["cuando"])


def borrar(ident):
    with _Candado():
        items = _leer(FILE)
        quedan = [i for i in items if i["id"] != str(ident)]
        if len(quedan) == len(items):
            return "No encuentro ese id."
        _escribir(FILE, quedan)
    return "Borrado."


def _siguiente(it, ahora):
    c = dt.datetime.strptime(it["cuando"], "%Y-%m-%d %H:%M")
    r = it["repetir"]
    paso = {"diario": dt.timedelta(days=1), "laborables": dt.timedelta(days=1), "semanal": dt.timedelta(days=7)}.get(r)
    if r.startswith("cada:"):
        paso = dt.timedelta(minutes=int(r[5:]))
    if not paso:
        return None
    while c <= ahora or (r == "laborables" and c.weekday() >= 5):
        c += paso
    return c


def vencidos(ahora=None):
    """Saca los que tocan (y reprograma los repetitivos). Devuelve la lista de los que hay que disparar."""
    ahora = ahora or dt.datetime.now()
    salen, quedan = [], []
    with _Candado():
        for it in _leer(FILE):
            try:
                c = dt.datetime.strptime(it["cuando"], "%Y-%m-%d %H:%M")
            except Exception:
                continue
            if c > ahora:
                quedan.append(it)
                continue
            if not (it["repetir"] == "laborables" and c.weekday() >= 5):
                if ahora - c < dt.timedelta(hours=12):   # si el PC estuvo apagado mucho rato, no dispara cosas viejas
                    salen.append(dict(it, retraso_min=int((ahora - c).total_seconds() // 60)))
            sig = _siguiente(it, ahora)
            if sig:
                quedan.append(dict(it, cuando=sig.strftime("%Y-%m-%d %H:%M")))
        _escribir(FILE, quedan)
    return salen


# ---------------------------------------------------------------- bandeja hacia Telegram
def encolar(texto):
    texto = str(texto or "").strip()[:3500]
    if not texto:
        return "Mensaje vacío."
    with _Candado():
        items = _leer(BANDEJA)
        if len(items) >= 20:
            return "Bandeja llena; espera a que se envíen."
        items.append({"t": time.time(), "texto": texto})
        _escribir(BANDEJA, items)
    return "Mensaje en cola para Telegram (sale en menos de 1 min)."


def sacar_bandeja():
    with _Candado():
        items = _leer(BANDEJA)
        if items:
            _escribir(BANDEJA, [])
    return [i["texto"] for i in items]
