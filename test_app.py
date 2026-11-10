# -*- coding: utf-8 -*-
"""Entrada directa de la app nativa «Pedro» (iPhone): POST /puente/app firmado -> /a/<token de un uso> -> sesión.
Sin Tailscale ni túnel reales: el puente escucha en 127.0.0.1 y se finge red 100.x donde toca."""
import secrets
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import requests

import webpanel as w

tmp = Path(tempfile.mkdtemp())
w.STATE_F, w.LOCK_F, w.DEV_F, w.ENROLL_F = tmp / "st.json", tmp / "LOCKED", tmp / "dev.json", tmp / "enroll.json"
w.APP_F, w.APP_SECRETO_DESTINO = tmp / "app_pedro.json", tmp / ".secreto_app"
PUERTO_WEB, PUERTO_PUENTE, PUERTO_FUERA = 18811, 18812, 18813
w.PORT = PUERTO_WEB
avisos = []
w.H.update({"log": lambda m: None, "alert": lambda m: avisos.append(m), "estado": lambda: "CPU ok"})
registro = []
w.log = lambda m: registro.append(m)
w.save_state({"ips": {}, "recent": [], "pause_until": 0, "active_link": None})
tuneles = []
def _sin_tunel():
    tuneles.append(1)
    raise RuntimeError("la app NO debe abrir el túnel")
w.ensure_tunnel = _sin_tunel
fallos = 0


def ok(c, txt):
    global fallos
    print(("OK  " if c else "MAL ") + txt)
    fallos += 0 if c else 1


def sirve(port, handler):
    s = ThreadingHTTPServer(("127.0.0.1", port), handler)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()


class PuenteTS(w.Puente):          # como si la petición llegara desde la red de Tailscale
    def _de_tailscale(self):
        return True


sirve(PUERTO_WEB, w.Handler)
sirve(PUERTO_PUENTE, PuenteTS)
sirve(PUERTO_FUERA, w.Puente)      # el real: 127.0.0.1 NO es Tailscale


def pedir(ts=None, firma=None, port=PUERTO_PUENTE, sec=None, nonce=None):
    ts = str(int(time.time())) if ts is None else ts
    nonce = nonce or secrets.token_urlsafe(16)
    firma = firma if firma is not None else w._firma_app(sec or w.app_secreto(), ts, nonce)
    return requests.post(f"http://127.0.0.1:{port}/puente/app", headers={"X-Ts": ts, "X-Nonce": nonce, "X-Firma": firma},
                         data=b"{}", timeout=5)


# ---- sin secreto el endpoint no existe
ok(pedir(firma="x").status_code == 404, "sin app_pedro.json -> 404 (endpoint apagado)")
dest = w.app_secreto_nuevo()
sec = w.app_secreto()
ok(len(sec) == 64 and dest and Path(dest).read_text(encoding="utf-8") == sec, "secreto nuevo de 32 bytes, copiado a la carpeta de la app")
ok(sec != (w.equipos_cfg().get("secreto") or ""), "secreto distinto del de equipos")

# ---- firma buena -> url de un uso -> sesión
r = pedir()
ok(r.status_code == 200 and "/a/" in r.json().get("url", ""), "firma buena -> 200 con url /a/<token>")
ok(r.json()["url"].startswith(f"http://127.0.0.1:{PUERTO_PUENTE}/a/"), "la url es la IP:puerto del propio puente (Tailscale), no el túnel")
ok(not tuneles, "/puente/app NO llama a ensure_tunnel()")
url = r.json()["url"]
s = requests.Session()
r2 = s.get(url, allow_redirects=False, timeout=5)
ok(r2.status_code == 302 and r2.headers.get("Location") == "/app", "GET /a/<token> -> 302 a /app")
ok("sid=" in r2.headers.get("Set-Cookie", "") and "HttpOnly" in r2.headers.get("Set-Cookie", ""), "pone la cookie de sesión sid (HttpOnly)")
ok(avisos and "app Pedro" in avisos[-1] and "127.0.0.1" in avisos[-1], "avisa a Telegram de la entrada desde la app, con la IP de origen")
ok("Secure" not in r2.headers.get("Set-Cookie", ""), "por el puente (HTTP en Tailscale) la cookie sid va sin «Secure»")
sid = r2.cookies.get("sid")
ok(requests.post(f"http://127.0.0.1:{PUERTO_WEB}/api/estado", cookies={"sid": sid}, headers={"X-Jarvis": "1"}, timeout=5).status_code != 401,
   "la sesión vale para la API como tras un PIN correcto")
ok(requests.get(url, allow_redirects=False, timeout=5).status_code == 404, "token usado dos veces -> 404")

# ---- firma repetida (replay dentro de la ventana)
ts, nn = str(int(time.time())), secrets.token_urlsafe(16)
f = w._firma_app(sec, ts, nn)
ok(pedir().status_code == 200 and pedir().status_code == 200, "dos entradas legítimas en el mismo segundo -> 200 las dos")
ok(pedir(ts, f, nonce=nn).status_code == 200, "firma nueva -> 200")
ok(pedir(ts, f, nonce=nn).status_code == 403, "MISMA petición otra vez (replay) -> 403")
ok(pedir(nonce="corto").status_code == 403, "nonce demasiado corto -> 403")

# ---- token caducado
r = pedir()
tok = r.json()["url"].rsplit("/", 1)[1]
w.APP_TOKENS[tok] -= 61
ok(requests.get(r.json()["url"], allow_redirects=False, timeout=5).status_code == 404, "token de más de 60 s -> 404")
ok(requests.get(f"http://127.0.0.1:{PUERTO_WEB}/a/inventado", allow_redirects=False, timeout=5).status_code == 404, "token inventado -> 404")

# ---- firmas malas
ok(pedir(ts="abc", firma="x").status_code == 403, "X-Ts no numérico -> 403")
ok(requests.post(f"http://127.0.0.1:{PUERTO_PUENTE}/puente/app", timeout=5).status_code == 403, "sin cabeceras -> 403")
ok(pedir().status_code == 200, "hora mal escrita o cabeceras ausentes no cuentan como ataque")
viejo = str(int(time.time()) - 120)
r = pedir(viejo, w._firma_app(sec, viejo, "n" * 16), nonce="n" * 16)
ok(r.status_code == 403 and r.json().get("error") == "caducada" and "ahora" in r.json(), "firma caducada -> 403 «caducada» (con la hora del PC)")
ok(pedir(firma=w._firma(sec, str(int(time.time())))).status_code == 403, "firma con el formato de equipos -> 403")
ok(pedir(firma=w._firma_app(sec, str(int(time.time())), "otro-nonce-distinto")).status_code == 403, "firma de otro nonce -> 403")
ok(pedir(sec="otro-secreto").status_code == 403, "secreto distinto -> 403")
ok(pedir().status_code == 429, "tras 3 firmas malas la IP queda bloqueada -> 429 aunque la firma sea buena")
ok(any("bloqueada" in a for a in avisos), "avisa del bloqueo a Telegram")
w.save_state({"ips": {}, "recent": [], "pause_until": 0, "active_link": None})

# ---- fuera de Tailscale
ok(pedir(port=PUERTO_FUERA).status_code == 404, "IP fuera de Tailscale -> 404 aunque la firma sea buena")

# ---- panel bloqueado
w.LOCK_F.write_text("x")
ok(pedir().status_code == 429, "panel BLOQUEADO (LOCKED) -> 429")
w.LOCK_F.unlink()
r = pedir()
w.LOCK_F.write_text("x")
ok(requests.get(r.json()["url"], allow_redirects=False, timeout=5).status_code == 404, "token válido pero panel bloqueado -> 404")
w.LOCK_F.unlink()

# ---- no toca el enlace de Telegram
w.TOKENS["tg"] = {"t": time.time(), "fails": 0, "dead": False}
pedir()
ok(not w.TOKENS["tg"]["dead"], "pedir entrada desde la app NO anula el enlace de Telegram activo")

# ---------------------------------------------------------------- 10/11: panel servido por el puente (sin túnel)
w.save_state({"ips": {}, "recent": [], "pause_until": 0, "active_link": None})
P = f"http://127.0.0.1:{PUERTO_PUENTE}"
url = pedir().json()["url"]
r = requests.get(url, allow_redirects=False, timeout=5)
sid = r.cookies.get("sid")
ok(r.status_code == 302 and sid, "puente: GET /a/<token> -> 302 con sid")
CK = {"Cookie": f"sid={sid}"}                       # la app la manda a mano en la cabecera Cookie
ok(requests.get(f"{P}/app", headers=CK, timeout=5).status_code == 200, "puente: GET /app con la cookie a mano -> 200")
ok(requests.get(f"{P}/app", allow_redirects=False, timeout=5).status_code == 302, "puente: GET /app sin sesión -> 302 a /gone")
ok(requests.get(f"{P}/gone", timeout=5).status_code == 401, "puente: /gone -> 401")
ok(requests.get(f"{P}/s/app/app.css", timeout=5).status_code == 200, "puente: estáticos /s/ -> 200")
HJ = dict(CK, **{"X-Jarvis": "1"})
r = requests.post(f"{P}/api/estado", headers=HJ, json={}, timeout=5)
ok(r.status_code == 200, "puente: POST /api/estado con sesión -> 200")
ok(requests.post(f"{P}/api/estado", headers={"X-Jarvis": "1"}, json={}, timeout=5).status_code == 401, "puente: POST /api/* sin sesión -> 401")
ok(requests.post(f"{P}/api/estado", headers=CK, json={}, timeout=5).status_code == 403, "puente: POST /api/* sin X-Jarvis -> 403")
w.JOBS["j1"] = {"state": "done", "text": "hola"}
ok(requests.get(f"{P}/api/job/j1", headers=CK, timeout=5).json().get("text") == "hola", "puente: GET /api/job/<id> con sesión")
ok(requests.get(f"{P}/api/job/j1", timeout=5).status_code == 401, "puente: GET /api/job sin sesión -> 401")
ok(requests.post(f"{P}/api/stt", headers=HJ, data=b"", timeout=5).status_code != 404, "puente: POST /api/stt existe")
ok(requests.post(f"{P}/api/estado", headers=dict(HJ, Origin="https://malo.com"), json={}, timeout=5).status_code == 421, "puente: Origin ajeno -> 421")
ok(requests.post(f"{P}/api/estado", headers=dict(HJ, Origin=P), json={}, timeout=5).status_code == 200, "puente: Origin propio (http://IP:puerto) -> 200")
ok(requests.post(f"{P}/api/estado", headers=dict(HJ, Host="x.trycloudflare.com"), json={}, timeout=5).status_code == 421, "puente: Host ajeno -> 421")
ok(requests.get(f"{P}/t/loquesea", timeout=5).status_code == 404, "puente: /t/ (flujo web) NO existe -> 404")
ok(requests.post(f"{P}/login", json={}, timeout=5).status_code == 404, "puente: /login (PIN) NO existe -> 404")
ok(requests.get(f"{P}/api/estado", timeout=5).status_code == 404, "puente: ruta no listada -> 404")
ok(any(m.startswith("app: POST /api/estado 200 ") and m.rstrip().endswith("(127.0.0.1)") for m in registro), "log por llamada: acción, código, ms e IP")
import re as _re
ok(any(m.startswith("app: GET /a/… 302") for m in registro) and not any(_re.search(r"/a/[A-Za-z0-9_-]{20,}", m) for m in registro),
   "el log no guarda tokens")
# IP falsa en Cf-Connecting-Ip: el puente la ignora
url = pedir().json()["url"]
with w.LOCKS["state"]:
    st = w.load_state(); st["ips"]["127.0.0.1"] = {"fails": 0, "blocked_until": time.time() + 600}; w.save_state(st)
ok(requests.get(url, headers={"Cf-Connecting-Ip": "8.8.8.8"}, allow_redirects=False, timeout=5).status_code == 404,
   "puente: Cf-Connecting-Ip falsa no salta el bloqueo de IP")
w.save_state({"ips": {}, "recent": [], "pause_until": 0, "active_link": None})
ok(requests.post(f"{P}/logout", headers=HJ, json={}, timeout=5).status_code == 200, "puente: POST /logout -> 200")
ok(requests.post(f"{P}/api/estado", headers=HJ, json={}, timeout=5).status_code == 401, "tras /logout la sesión ya no vale")
# fuera de Tailscale: todo 404
F = f"http://127.0.0.1:{PUERTO_FUERA}"
url = pedir().json()["url"].replace(str(PUERTO_PUENTE), str(PUERTO_FUERA))
ok(requests.get(url, allow_redirects=False, timeout=5).status_code == 404, "fuera de Tailscale: GET /a/<token válido> -> 404")
ok(requests.get(f"{F}/app", headers=CK, timeout=5).status_code == 404, "fuera de Tailscale: GET /app -> 404")
ok(requests.get(f"{F}/s/app/app.css", timeout=5).status_code == 404, "fuera de Tailscale: /s/ -> 404")
ok(requests.post(f"{F}/api/estado", headers=HJ, json={}, timeout=5).status_code == 404, "fuera de Tailscale: POST /api/* -> 404")
ok(requests.post(f"{F}/api/stt", headers=HJ, data=b"", timeout=5).status_code == 404, "fuera de Tailscale: POST /api/stt -> 404")
ok(requests.get(f"{F}/api/job/j1", headers=CK, timeout=5).status_code == 404, "fuera de Tailscale: GET /api/job -> 404")
ok(requests.post(f"{F}/logout", headers=HJ, json={}, timeout=5).status_code == 404, "fuera de Tailscale: POST /logout -> 404")
ok(requests.get(f"{F}/ping", timeout=5).status_code == 404, "fuera de Tailscale: /ping -> 404")
# el camino del túnel sigue: un token también entra por el servidor del túnel (con cookie Secure)
tok = pedir().json()["url"].rsplit("/", 1)[1]
r = requests.get(f"http://127.0.0.1:{PUERTO_WEB}/a/{tok}", allow_redirects=False, timeout=5)
ok(r.status_code == 302 and "Secure" in r.headers.get("Set-Cookie", ""), "túnel: /a/ sigue funcionando y su cookie lleva «Secure»")
ok(not tuneles, "ninguna llamada de la app abrió el túnel")

print("TODAS LAS PRUEBAS DE LA APP OK" if not fallos else f"{fallos} FALLOS")
raise SystemExit(1 if fallos else 0)
