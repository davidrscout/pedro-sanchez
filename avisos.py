# -*- coding: utf-8 -*-
"""Avisos y preguntas a David con respuesta (fase 1 de «Jarvis te avisa y puedes llamarle»).

Cualquier agente (Pedro por MCP, o una sesión de Claude Code/T3 por la línea de comandos con avisar.py) deja aquí un aviso:
- informativo (espera=False): solo se entrega por Telegram («🔔 origen: texto»).
- pregunta (espera=True): David la ve en la app Pedro (pestaña Hablar), la responde, y el agente que SIGUE ESPERANDO recibe la
  respuesta con esperar(). Opcionalmente (JARVIS_TG_RESPUESTAS=1) también por botones de Telegram.

Mismo patrón que agenda.py: JSON `avisos.json` en la carpeta del proyecto + candado entre procesos (avisos.lock), porque lo
tocan Jarvis, el servidor MCP de Pedro y los CLI de otros agentes. Sin dependencias. El token de Telegram nunca pasa por aquí:
quien entrega los avisos es jarvis.py.

Para pruebas: la variable de entorno JARVIS_AVISOS_DIR cambia la carpeta donde viven avisos.json y avisos.lock.
Estados: pendiente | respondido | caducado | informativo. Vías de respuesta: app | web | telegram."""
import datetime as dt
import json
import os
import re
import time
import uuid
from pathlib import Path

HOME = Path(__file__).resolve().parent
ESTADOS = ("pendiente", "respondido", "caducado", "informativo")
VIAS = ("app", "web", "telegram")
MAX_TEXTO = 2000
MAX_RESPUESTA = 2000
MAX_OPCIONES = 8
MAX_OPCION = 80
MAX_ORIGEN = 40
MAX_GUARDADOS = 300        # al pasarse, se descartan los más viejos que ya no están pendientes
MAX_PENDIENTES = 25        # un agente descontrolado no llena el móvil de preguntas
MAX_POR_HORA = 60          # ni el Telegram de David de avisos
PUBLICOS = ("id", "texto", "opciones", "espera", "urgente", "origen", "creado", "estado", "respuesta", "via",
            "respondido_en", "notificado")


def _dir():
    return Path(os.environ.get("JARVIS_AVISOS_DIR") or HOME)


def _fichero():
    return _dir() / "avisos.json"


def _lock():
    return _dir() / "avisos.lock"


def _ahora():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Candado:
    """Exclusión entre procesos con un fichero creado en exclusiva (igual que agenda.py)."""
    def __enter__(self):
        t0 = time.time()
        self.p = _lock()
        while True:
            try:
                self.fd = os.open(str(self.p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.p.stat().st_mtime > 10:     # candado huérfano de un proceso muerto
                        self.p.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() - t0 > 8:
                    raise TimeoutError("avisos ocupado")
                time.sleep(0.03)
            except PermissionError:                                    # Windows: se está borrando justo ahora
                if time.time() - t0 > 8:
                    raise TimeoutError("avisos ocupado")
                time.sleep(0.03)

    def __exit__(self, *a):
        os.close(self.fd)
        for _ in range(40):
            try:
                self.p.unlink(missing_ok=True)
                return
            except PermissionError:
                time.sleep(0.02)


def _leer():
    """Lista de avisos. Un fallo transitorio de lectura (Windows no deja leer mientras se sustituye el fichero) se reintenta;
    un JSON roto se aparta como avisos.json.corrupto_<hora> (no se borra) y se empieza de cero."""
    p = _fichero()
    for i in range(30):
        try:
            txt = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            time.sleep(0.02)
            continue
        try:
            d = json.loads(txt)
            return d if isinstance(d, list) else []
        except ValueError:
            try:
                os.replace(p, p.with_name("avisos.json.corrupto_" + time.strftime("%Y%m%d_%H%M%S")))
            except OSError:
                pass
            return []
    raise OSError("no pude leer avisos.json")


def _escribir(items):
    p = _fichero()
    tmp = p.with_name(f"avisos.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(60):               # Windows: replace falla si alguien tiene el destino abierto en ese instante
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.02)
    os.replace(tmp, p)


def _limpio(s, n):
    return re.sub(r"[ \t]+", " ", str(s or "").replace("\r", "")).strip()[:n]


def publico(a):
    """El aviso tal como se enseña a la app (sin campos internos como el id del mensaje de Telegram)."""
    return {k: a.get(k) for k in PUBLICOS}


def crear(texto, opciones=None, espera=False, urgente=False, origen="Pedro"):
    """Deja un aviso. espera=True = pregunta (queda pendiente hasta que David responda). Devuelve el aviso (dict público).
    ValueError si algo no vale (texto vacío, demasiados pendientes...)."""
    texto = _limpio(texto, MAX_TEXTO)
    if not texto:
        raise ValueError("Falta el texto.")
    if opciones is None:
        opciones = []
    if isinstance(opciones, str):
        opciones = [o for o in opciones.split("|")]
    opts = []
    for o in list(opciones)[:MAX_OPCIONES]:
        o = _limpio(o, MAX_OPCION)
        if o and o not in opts:
            opts.append(o)
    origen = _limpio(origen, MAX_ORIGEN) or "Pedro"
    espera = bool(espera)
    ahora = time.time()
    with _Candado():
        items = _leer()
        if espera and sum(1 for i in items if i.get("estado") == "pendiente") >= MAX_PENDIENTES:
            raise ValueError(f"Hay ya {MAX_PENDIENTES} preguntas sin responder; no se admiten más.")
        if sum(1 for i in items if ahora - i.get("t", 0) < 3600) >= MAX_POR_HORA:
            raise ValueError("Demasiados avisos en la última hora.")
        a = {"id": uuid.uuid4().hex[:8], "texto": texto, "opciones": opts, "espera": espera, "urgente": bool(urgente),
             "origen": origen, "creado": _ahora(), "t": ahora, "estado": "pendiente" if espera else "informativo",
             "respuesta": None, "via": None, "respondido_en": None, "notificado": False,
             "tg_msg": None, "tg_editado": False, "tg_intentos": 0}
        items.append(a)
        if len(items) > MAX_GUARDADOS:
            sobran = len(items) - MAX_GUARDADOS
            fuera = [i["id"] for i in items if i.get("estado") != "pendiente"][:sobran]
            items = [i for i in items if i["id"] not in fuera]
        _escribir(items)
    return publico(a)


def obtener(ident):
    """El aviso con ese id (dict público) o None."""
    for a in _leer():
        if a.get("id") == str(ident):
            return publico(a)
    return None


def listar(solo_pendientes=True, n=50):
    """Más recientes primero. solo_pendientes=True: solo los que esperan respuesta."""
    its = _leer()
    if solo_pendientes:
        its = [a for a in its if a.get("estado") == "pendiente"]
    # el reloj de Windows tiene ~15 ms de resolución: a igual hora manda el orden de inserción (el fichero va en orden de creación)
    orden = sorted(enumerate(its), key=lambda p: (p[1].get("t", 0), p[0]), reverse=True)
    return [publico(a) for _, a in orden[:max(0, int(n))]]


def responder(ident, respuesta, via="app"):
    """David responde. Devuelve (True, "") o (False, motivo): no existe, ya respondido, caducado, no pedía respuesta,
    respuesta vacía o de más de 2000 caracteres. La primera respuesta gana; las siguientes se rechazan."""
    if via not in VIAS:
        raise ValueError("via debe ser app, web o telegram.")
    respuesta = _limpio(respuesta, 10 ** 6)
    if not respuesta:
        return False, "La respuesta está vacía."
    if len(respuesta) > MAX_RESPUESTA:
        return False, f"La respuesta es demasiado larga (máximo {MAX_RESPUESTA} caracteres)."
    with _Candado():
        items = _leer()
        for a in items:
            if a.get("id") != str(ident):
                continue
            est = a.get("estado")
            if est == "respondido":
                return False, "Ese aviso ya estaba respondido."
            if est == "caducado":
                return False, "Ese aviso ha caducado."
            if est != "pendiente":
                return False, "Ese aviso no esperaba respuesta."
            a.update({"estado": "respondido", "respuesta": respuesta, "via": via, "respondido_en": _ahora()})
            _escribir(items)
            return True, ""
    return False, "No existe ese aviso."


def esperar(ident, timeout_s=600, cada=1.0):
    """Bloquea hasta que el aviso tenga respuesta (la devuelve) o pasen timeout_s segundos (None). Sondea el fichero cada
    ~1 s, así funciona entre procesos distintos. Si el aviso no existe o caduca mientras tanto, devuelve None."""
    fin = time.time() + max(0, float(timeout_s))
    while True:
        try:
            a = obtener(ident)
        except OSError:
            a = {"estado": "pendiente"}                  # fallo transitorio de lectura: se vuelve a intentar
        if a is None or a.get("estado") == "caducado":
            return None
        if a.get("estado") == "respondido":
            return a.get("respuesta")
        resto = fin - time.time()
        if resto <= 0:
            return None
        time.sleep(min(cada, resto))


def caducar_viejos(horas=24):
    """Las preguntas sin responder de más de `horas` pasan a «caducado». Devuelve cuántas."""
    limite = time.time() - float(horas) * 3600
    n = 0
    with _Candado():
        items = _leer()
        for a in items:
            if a.get("estado") == "pendiente" and a.get("t", 0) < limite:
                a["estado"] = "caducado"
                n += 1
        if n:
            _escribir(items)
    return n


# ---------------------------------------------------------------- entrega por Telegram (la hace jarvis.py)
def sacar_no_notificados():
    """Avisos aún no entregados a Telegram (los marca como notificados ya, para que dos hilos no los manden dos veces).
    Si el envío falla, jarvis.py llama a devolver_a_la_cola(id). Los caducados no se entregan."""
    with _Candado():
        items = _leer()
        salen = [a for a in items if not a.get("notificado") and a.get("estado") != "caducado"]
        if salen:
            for a in salen:
                a["notificado"] = True
            _escribir(items)
    return [dict(a) for a in salen]


def devolver_a_la_cola(ident, max_intentos=5):
    """El envío a Telegram falló: se reintentará en el siguiente ciclo (hasta max_intentos veces; luego se da por entregado)."""
    with _Candado():
        items = _leer()
        for a in items:
            if a.get("id") == str(ident):
                a["tg_intentos"] = int(a.get("tg_intentos", 0)) + 1
                if a["tg_intentos"] < max_intentos:
                    a["notificado"] = False
                _escribir(items)
                return


def marcar_mensaje(ident, message_id):
    """Guarda el id del mensaje de Telegram en el que se entregó (para editarlo cuando se responda)."""
    with _Candado():
        items = _leer()
        for a in items:
            if a.get("id") == str(ident):
                a["tg_msg"] = message_id
                _escribir(items)
                return


def por_editar():
    """Avisos con mensaje en Telegram que ya se han respondido o caducado y cuyo mensaje aún no se ha puesto al día."""
    return [dict(a) for a in _leer()
            if a.get("tg_msg") and not a.get("tg_editado") and a.get("estado") in ("respondido", "caducado")]


def marcar_editado(ident):
    with _Candado():
        items = _leer()
        for a in items:
            if a.get("id") == str(ident):
                a["tg_editado"] = True
                _escribir(items)
                return
