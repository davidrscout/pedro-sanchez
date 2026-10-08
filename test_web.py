# -*- coding: utf-8 -*-
"""Pruebas del panel sin túnel: servidor local + token/PIN/dispositivos/sesión + bloqueos por IP."""
import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests

import webpanel as w

tmp = Path(tempfile.mkdtemp())
w.STATE_F, w.LOCK_F, w.DEV_F, w.ENROLL_F, w.PORT = tmp / "st.json", tmp / "LOCKED", tmp / "dev.json", tmp / "enroll.json", 18799
called = []
w.H.update({"log": lambda m: None, "alert": lambda m: called.append(("alert", m)),
            "estado": lambda: "CPU ok", "eventos": lambda: "sin eventos", "captura": lambda: b"\xff\xd8JPEG",
            "bloquear": lambda: called.append("lock"), "pantalla": lambda: None, "ahorro": lambda: None,
            "vol": lambda a: None, "abrir": lambda a: "ok", "power": lambda k: called.append(("power", k)) or "hecho",
            "brain": lambda p, m, b="claude": f"resp[{b}/{m}]:{p}",
            "backends": lambda: [{"id": "claude", "nombre": "Claude", "ok": True, "nota": ""}],
            "watchdog": lambda: {"activo": True, "latido_s": 3, "tarea": "Running", "sesiones": 1, "ultima": None, "hoy": None, "eventos": []},
            "serie": lambda: {"desde": 0, "paso_s": 300, "puntos": [None, {"t": 40.0, "u": 10, "c": 5}], "cortes": [], "muestras": 1},
            "procesos": lambda: {"total": 1, "top": [{"pid": 4, "name": "x.exe", "cpu": 0, "mem_mb": 1, "protegido": False}], "ventanas": []},
            "matar": lambda pid: called.append(("matar", pid)) or "cerrado", "red": lambda: "red ok",
            "launchers": lambda: {"grupos": [{"id": "a", "nombre": "A"}], "items": [{"id": "u1", "grupo": "a", "label": "L", "tipo": "url", "confirmar": False, "url": "https://x"}]},
            "lanzar": lambda i, c, d: {"text": f"lanzado {i} confirm={c} donde={d}"}})
w.CFG["JARVIS_ENROLL_HASH"] = w.make_hash("12345678")
w.CFG["JARVIS_REQUIRE_DEVICE"] = "1"   # las pruebas de dispositivos lo necesitan activo
w.CFG["JARVIS_PIN_HASH"] = w.make_hash("2404")
w.TUN["url"] = "https://fake.trycloudflare.com"
w.ensure_server()
B = "http://127.0.0.1:18799"


def ok(c, msg):
    print(("OK  " if c else "FALLO ") + msg)
    assert c, msg


def mk_token(age=0):
    t = "tok" + os.urandom(4).hex()
    w.TOKENS[t] = {"t": time.time() - age, "fails": 0, "dead": False}
    return t


def page(tok, dev=None, ip=None):
    h = {}
    if dev:
        h["Cookie"] = f"dev={dev}"
    if ip:
        h["Cf-Connecting-Ip"] = ip
    r = requests.get(f"{B}/t/{tok}", headers=h)
    m = re.search(r'let nonce\s*=\s*"([^"]+)"', r.text) if r.status_code == 200 else None   # la UI nueva usa espacios
    return r, (m.group(1) if m else None)


def login(nonce, pin, enroll=None, dev=None, ip=None):
    h = {}
    if dev:
        h["Cookie"] = f"dev={dev}"
    if ip:
        h["Cf-Connecting-Ip"] = ip
    body = {"nonce": nonce, "pin": pin}
    if enroll:
        body["enroll"] = enroll
    return requests.post(f"{B}/login", json=body, headers=h)


def fresh_state():
    w.save_state({"ips": {}, "recent": [], "pause_until": 0})
    w.LOCK_F.unlink(missing_ok=True)


def enroll_device():
    """Enrola un dispositivo de verdad por el flujo web y devuelve su cookie dev."""
    code = w.new_enroll_code()
    tok = mk_token()
    r, n = page(tok)
    assert r.status_code == 200
    r = login(n, "2404", enroll=code)
    assert r.status_code == 200, r.text
    return [c for c in r.headers["Set-Cookie"].split(", ") if c.startswith("dev=")][0].split("=")[1].split(";")[0] if "dev=" in r.headers.get("Set-Cookie", "") else None, r


# ---------------------------------------------------------------- básicos
ok(requests.get(f"{B}/t/inventado").status_code == 404, "token inventado -> 404")
ok(requests.get(f"{B}/t/{mk_token(70)}").status_code == 404, "token de 70 s (caducado) -> 404")
ok(requests.get(f"{B}/app", allow_redirects=False).status_code == 302, "/app sin sesión -> redirige")
ok(requests.get(f"{B}/", headers={"Host": "malo.com"}).status_code == 421, "Host ajeno -> 421")
ok(requests.post(f"{B}/api/estado").status_code in (403, 421), "api sin cabecera/cookie -> rechazada")

# ---------------------------------------------------------------- dispositivos (código de alta FIJO, sin tocar el PC)
fresh_state()
r, n = page(mk_token())
ok(r.status_code == 200 and "__ENROLL__" not in r.text, "dispositivo nuevo: se ve la página (con el paso del código de alta)")
r = login(n, "2404")
ok(r.status_code == 401 and not (w.DEV_F.exists() and json.loads(w.DEV_F.read_text())), "dispositivo nuevo con PIN bueno pero SIN código de alta -> no entra")
n = r.json()["nonce"]
r = login(n, "2404", enroll="00000000")
ok(r.status_code == 401, "código de alta malo + PIN bueno -> 401")
fresh_state()   # (los dos fallos anteriores ya cuentan para el bloqueo por IP; se reinicia para aislar este caso)
r, n = page(mk_token())
r = login(n, "9999", enroll="12345678")
ok(r.status_code == 401 and not (w.DEV_F.exists() and json.loads(w.DEV_F.read_text())), "código bueno + PIN malo -> no se da de alta")
fresh_state()
r, n = page(mk_token())
r = login(n, "2404", enroll="12345678")
ok(r.status_code == 200, "código de alta bueno + PIN bueno -> alta y entra")
sc = r.headers.get("Set-Cookie", "")
ok("dev=" in sc and "sid=" in sc, "devuelve cookie de dispositivo y de sesión")
DEV = sc.split("dev=")[1].split(";")[0]
ok(len(json.loads(w.DEV_F.read_text())) == 1, "dispositivo guardado")
r, n = page(mk_token(), dev=DEV)
ok(r.status_code == 200 and login(n, "2404", dev=DEV).status_code == 200, "dispositivo ya dado de alta: solo PIN")
fresh_state()
r, n = page(mk_token()); r = login(n, "2404", enroll="12345678")
ok(r.status_code == 200 and len(json.loads(w.DEV_F.read_text())) == 2, "el código de alta es reutilizable: segundo móvil dado de alta")
saved = w.CFG.pop("JARVIS_ENROLL_HASH")
ok(page(mk_token())[0].status_code == 404, "sin código de alta configurado, un móvil nuevo no ve nada (404)")
w.CFG["JARVIS_ENROLL_HASH"] = saved
r, n = page(mk_token(), dev="x" * 40)
ok(r.status_code == 200 and "dev" not in r.headers.get("Set-Cookie", ""), "cookie de dispositivo inventada = dispositivo nuevo (necesita código de alta)")

# ---------------------------------------------------------------- PIN / sesión desde dispositivo autorizado
fresh_state()
tok = mk_token(); r, n = page(tok, dev=DEV)
r = login(n, "0000", dev=DEV); ok(r.status_code == 401 and r.json().get("nonce"), "PIN malo #1 -> 401 con nonce nuevo")
n = r.json()["nonce"]
r = login(n, "2404", dev=DEV)
ok(r.status_code == 200, "PIN correcto desde dispositivo autorizado -> 200")
sc = r.headers.get("Set-Cookie", "")
ok("HttpOnly" in sc and "Secure" in sc, "cookies HttpOnly+Secure")
sid = [p for p in sc.replace(",", ";").split(";") if p.strip().startswith("sid=")][0].strip()[4:]
ck = {"sid": sid}; hd = {"X-Jarvis": "1"}
ok(w.load_state()["ips"] == {}, "éxito borra los fallos de esa IP")
ok(login(n, "2404", dev=DEV).status_code == 401, "el nonce no se reutiliza")
ok(requests.get(f"{B}/app", cookies=ck).status_code == 200, "/app con sesión -> 200")
ok(requests.post(f"{B}/api/estado", cookies=ck).status_code == 403, "api sin X-Jarvis -> 403 (anti-CSRF)")
ok(requests.post(f"{B}/api/estado", headers=hd).status_code == 401, "api sin cookie -> 401")
ok(requests.post(f"{B}/api/estado", cookies={"sid": "x" * 40}, headers=hd).status_code == 401, "cookie falsa -> 401")
ok(requests.post(f"{B}/api/estado", cookies=ck, headers=hd).json()["text"] == "CPU ok", "api estado con sesión OK")
ok(requests.post(f"{B}/api/captura", cookies=ck, headers=hd).content.startswith(b"\xff\xd8"), "captura devuelve imagen")
requests.post(f"{B}/api/apagar", cookies=ck, headers=hd, json={})
requests.post(f"{B}/api/apagar", cookies=ck, headers=hd, json={"confirm": "true"})
ok(("power", "apagar") not in called, "apagar SIN confirm:true (o con string) NO se ejecuta")
requests.post(f"{B}/api/apagar", cookies=ck, headers=hd, json={"confirm": True})
ok(("power", "apagar") in called, "apagar con confirm:true sí se ejecuta")
ok(requests.post(f"{B}/api/hacer", cookies=ck, headers=hd, json={"prompt": "x"}).status_code == 400, "/hacer sin confirmación -> 400")
r = requests.post(f"{B}/api/preguntar", cookies=ck, headers=hd, json={"prompt": "hola"}); jid = r.json()["job"]; time.sleep(0.5)
ok("resp[claude/ask]:hola" in requests.get(f"{B}/api/job/{jid}", cookies=ck).json()["text"], "pregunta -> trabajo asíncrono con respuesta")
r = requests.post(f"{B}/api/agy", cookies=ck, headers=hd, json={"prompt": "hola", "confirm": True}); jid = r.json()["job"]; time.sleep(0.5)
ok("resp[agy/do]" in requests.get(f"{B}/api/job/{jid}", cookies=ck).json()["text"], "acción antigua agy -> cerebro agy en modo actuar")
ok(requests.post(f"{B}/api/inexistente", cookies=ck, headers=hd).status_code == 404, "acción desconocida -> 404")
ok(requests.post(f"{B}/api/estado", cookies=ck, headers={**hd, "Origin": "https://evil.com"}).status_code == 421, "Origin ajeno -> rechazado")
w.SESS["last"] -= 700
ok(requests.post(f"{B}/api/estado", cookies=ck, headers=hd).status_code == 200, "la sesión ya NO caduca a los 10 min")

# ---------------------------------------------------------------- API nueva
def api(a, body=None): return requests.post(f"{B}/api/{a}", cookies=ck, headers=hd, json=body or {})
ok(api("modelos").json()["backends"][0]["id"] == "claude", "modelos")
ok(api("watchdog").json()["activo"] is True, "watchdog")
ok(api("serie").json()["puntos"][1]["t"] == 40.0, "serie (historial del vigilante)")
ok(api("procesos").json()["top"][0]["pid"] == 4, "procesos")
ok(api("red").json()["text"] == "red ok", "red")
ok(api("matar", {"pid": 4}).status_code == 400 and ("matar", 4) not in called, "matar sin confirmar NO ejecuta")
ok(api("matar", {"pid": "4; rm", "confirm": True}).status_code == 400, "matar con pid no numérico -> 400")
api("matar", {"pid": 4, "confirm": True}); ok(("matar", 4) in called, "matar con confirmación ejecuta")
ok(api("chat", {"backend": "agy", "mode": "do", "prompt": "x"}).status_code == 400, "chat en modo actuar sin confirm -> 400")
ok(api("chat", {"backend": "opencode", "mode": "ask", "prompt": "x"}).status_code == 400, "OpenCode ya no existe como cerebro -> 400")
ok(api("chat", {"backend": "hackeo", "mode": "ask", "prompt": "x"}).status_code == 400, "chat con cerebro desconocido -> 400")
jid = api("chat", {"backend": "agy", "mode": "do", "prompt": "hola", "confirm": True}).json()["job"]; time.sleep(0.5)
ok("resp[agy/do]:hola" in requests.get(f"{B}/api/job/{jid}", cookies=ck).json()["text"], "chat agy actuar con confirm")
jid = api("chat", {"backend": "local", "mode": "ask", "prompt": "q"}).json()["job"]; time.sleep(0.5)
ok("resp[local/ask]" in requests.get(f"{B}/api/job/{jid}", cookies=ck).json()["text"], "chat local solo lectura sin confirm")
ok(api("launchers").json()["items"][0]["id"] == "u1", "launchers")
jid = api("lanzar", {"id": "u1", "donde": "pc"}).json()["job"]; time.sleep(0.4)
ok("donde=pc" in requests.get(f"{B}/api/job/{jid}", cookies=ck).json()["text"], "lanzar -> trabajo con resultado")
import launchers as L
pub = json.dumps(L.lista_publica())
raw = L._cargar()["items"]
ok('"destino"' not in pub and all(it["destino"] not in pub for it in raw if it["tipo"] in ("ssh", "cmd", "app", "carpeta")),
   "la lista pública NO expone los comandos (ssh/cmd) ni rutas internas; solo URLs y prompts de IA")
ok(L.ejecutar("vps_gemsy_reiniciar", confirm=False)["text"] == "Hace falta confirmación." , "lanzador con confirmar:true no corre sin confirmación")
ok(L.ejecutar("no_existe")["text"] == "Lanzador desconocido.", "lanzador inexistente")
w.SESS["last"] -= 50000
ok(requests.post(f"{B}/api/estado", cookies=ck, headers=hd).status_code == 401, "sesión inactiva >12 h caduca")

# ---------------------------------------------------------------- bloqueo por IP (no del panel entero)
fresh_state()
BAD, GOOD = "9.9.9.9", "8.8.8.8"
tok = mk_token(); r, n = page(tok, dev=DEV, ip=BAD)
for i in range(2):
    r = login(n, "0000", dev=DEV, ip=BAD); ok(r.status_code == 401, f"IP mala: fallo #{i+1} -> 401")
    n = r.json()["nonce"]
r = login(n, "0000", dev=DEV, ip=BAD)
ok(r.status_code == 429 and "IP" in r.json()["error"], "IP mala: 3er fallo -> 429, IP bloqueada")
ok(not w.LOCK_F.exists() and w.lock_status() is None, "el panel NO queda bloqueado en general")
ok(page(mk_token(), dev=DEV, ip=BAD)[0].status_code == 404, "la IP bloqueada ya no abre enlaces")
tk = mk_token(); r, n = page(tk, dev=DEV, ip=GOOD)
ok(r.status_code == 200 and login(n, "2404", dev=DEV, ip=GOOD).status_code == 200, "otra IP sigue entrando con normalidad")
al = [c[1] for c in called if isinstance(c, tuple) and c[0] == "alert"]
ok(any("BLOQUEADA" in a and BAD in a for a in al), "aviso de IP bloqueada con su IP")
st = w.load_state(); st["ips"][BAD]["blocked_until"] = time.time() - 1; w.save_state(st)
ok(page(mk_token(), dev=DEV, ip=BAD)[0].status_code == 200, "el bloqueo de IP caduca (24 h) y se levanta")

# fallos repartidos entre tokens distintos de la misma IP también cuentan
fresh_state()
for i in range(2):
    tk = mk_token(); r, n = page(tk, dev=DEV, ip=BAD); login(n, "1111", dev=DEV, ip=BAD)
ok(w.ip_blocked(BAD) is None, "2 fallos sueltos aún no bloquean")
tk = mk_token(); r, n = page(tk, dev=DEV, ip=BAD); r = login(n, "1111", dev=DEV, ip=BAD)
ok(r.status_code == 429 and w.ip_blocked(BAD), "el 3º fallo (con otro enlace) bloquea la IP")
fresh_state()
tk = mk_token(); r, n = page(tk, dev=DEV, ip=BAD); login(n, "1111", dev=DEV, ip=BAD)
tk = mk_token(); r, n = page(tk, dev=DEV, ip=BAD)
ok(login(n, "2404", dev=DEV, ip=BAD).status_code == 200 and BAD not in w.load_state()["ips"], "un acierto antes del 3º pone el contador a cero")

# red de seguridad: ataque repartido entre muchas IP
fresh_state()
for i in range(9):
    tk = mk_token(); r, n = page(tk, dev=DEV, ip=f"10.0.0.{i}"); login(n, "1111", dev=DEV, ip=f"10.0.0.{i}")
ok(w.lock_status() and "pausa" in w.lock_status(), "9 fallos desde IP distintas -> pausa global de 1 h")
url, err = w.new_link(); ok(url is None and "pausa" in err, "en pausa global no se generan enlaces")
fresh_state()
w.LOCK_F.write_text("x"); ok("BLOQUEADO" in (w.lock_status() or ""), "LOCKED manual sigue funcionando")
fresh_state()
# ---------------------------------------------------------------- por defecto: SIN dispositivo autorizado
w.CFG["JARVIS_REQUIRE_DEVICE"] = "0"
fresh_state()
r, n = page(mk_token())
ok(r.status_code == 200 and "__ENROLL__" not in r.text, "sin exigir dispositivo, un móvil cualquiera ve la página del PIN (con enlace válido)")
r = login(n, "2404")
ok(r.status_code == 200 and "sid=" in r.headers.get("Set-Cookie", "") and "dev=" not in r.headers.get("Set-Cookie", ""), "entra solo con el PIN, sin código de alta ni cookie de dispositivo")
ok(page("inventado")[0].status_code == 404, "sigue sin entrar sin un enlace válido")
# ---------------------------------------------------------------- ficheros estáticos de la UI (ui/static)
sd = Path(__file__).resolve().parent / "ui" / "static"; sd.mkdir(parents=True, exist_ok=True)
(sd / "_t.js").write_text("console.log(1)"); (sd / "_t.txt").write_text("no"); (sd / "sub").mkdir(exist_ok=True); (sd / "sub" / "_t.glsl").write_text("void main(){}")
r = requests.get(f"{B}/s/_t.js"); ok(r.status_code == 200 and "javascript" in r.headers["Content-Type"], "estático: js servido con su tipo")
ok(requests.get(f"{B}/s/sub/_t.glsl").status_code == 200, "estático: subcarpeta y shader")
ok(requests.get(f"{B}/s/_t.txt").status_code == 404, "estático: extensión no permitida -> 404")
ok(requests.get(f"{B}/s/").status_code == 404 and requests.get(f"{B}/s/sub").status_code == 404, "estático: sin listado de carpetas")
for bad in ("../../.env", "..%2f..%2f.env", "%2e%2e/%2e%2e/.env", r"..\..\.env", "../webpanel.py", "..%5c..%5c.env"):
    ok(requests.get(f"{B}/s/{bad}").status_code == 404, f"estático: intento de salir de la carpeta {bad!r} -> 404")
ok(requests.get(f"{B}/s/_t.js", headers={"Host": "malo.com"}).status_code == 421, "estático: Host ajeno -> 421")
for f in (sd / "_t.js", sd / "_t.txt", sd / "sub" / "_t.glsl"): f.unlink()
(sd / "sub").rmdir()
# ---------------------------------------------------------------- red de seguridad ?v=1 (interfaz anterior)
uidir = Path(__file__).resolve().parent / "ui"
orig = {n: ((uidir / n).read_bytes() if (uidir / n).exists() else None) for n in ("pin_v1.html", "app_v1.html")}
(uidir / "pin_v1.html").write_text("<html>PIN-ANTIGUO let nonce=\"__NONCE__\"")
(uidir / "app_v1.html").write_text("<html>APP-ANTIGUA")
fresh_state(); w.CFG["JARVIS_REQUIRE_DEVICE"] = "0"
r = requests.get(f"{B}/t/{mk_token()}?v=1")
ok(r.status_code == 200 and "ui=v1" in r.headers.get("Set-Cookie", "") and "PIN-ANTIGUO" in r.text, "?v=1 sirve la página de PIN antigua y fija la cookie ui=v1")
r2 = requests.get(f"{B}/app", cookies={"sid": w.SESS["sid"] or "x" * 40, "ui": "v1"})
tk = mk_token(); r, n = page(tk); r = login(n, "2404"); sid2 = r.headers["Set-Cookie"].split("sid=")[1].split(";")[0]
ok("APP-ANTIGUA" in requests.get(f"{B}/app", cookies={"sid": sid2, "ui": "v1"}).text, "con cookie ui=v1, /app sirve la interfaz antigua")
ok("APP-ANTIGUA" not in requests.get(f"{B}/app", cookies={"sid": sid2}).text, "sin esa cookie, /app sirve la nueva")
r = requests.get(f"{B}/t/{mk_token()}")
ok("ui=;" in r.headers.get("Set-Cookie", "") and "Max-Age=0" in r.headers.get("Set-Cookie", ""), "un enlace SIN ?v=1 borra la cookie ui")
for n_, content in orig.items():
    if content is None: (uidir / n_).unlink()
    else: (uidir / n_).write_bytes(content)
# ---------------- dictado en el PC (/api/stt)
w.H["stt"] = lambda b: f"oido {len(b)} bytes"
w.SESS.update({"sid": "s" * 43, "t0": time.time(), "last": time.time()})
ck = {"sid": "s" * 43}
r = requests.post(f"{B}/api/stt", cookies=ck, headers={**hd, "Content-Type": "audio/webm"}, data=b"x" * 2000)
ok(r.status_code == 200 and r.json()["text"] == "oido 2000 bytes", "stt: audio llega al PC y vuelve el texto")
r = requests.post(f"{B}/api/stt", cookies=ck, headers={**hd, "Content-Type": "application/json"}, data=b"{}")
ok(r.status_code == 400, "stt: rechaza lo que no es audio")
r = requests.post(f"{B}/api/stt", headers={**hd, "Content-Type": "audio/webm"}, data=b"x" * 2000)
ok(r.status_code == 401, "stt: sin sesión -> 401")
r = requests.post(f"{B}/api/stt", cookies=ck, headers={**hd, "Content-Type": "audio/webm"}, data=b"")
ok(r.status_code == 400, "stt: cuerpo vacío -> 400")
print("TODAS LAS PRUEBAS DEL PANEL OK")
