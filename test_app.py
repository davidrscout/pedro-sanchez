# -*- coding: utf-8 -*-
"""Entrada directa de la app nativa «Pedro» (iPhone): POST /puente/app firmado -> /a/<token de un uso> -> sesión.
Sin Tailscale ni túnel reales: el puente escucha en 127.0.0.1 y se finge red 100.x donde toca."""
import base64
import os
import secrets
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import requests

import webpanel as w

tmp = Path(tempfile.mkdtemp())
os.environ["JARVIS_AVISOS_DIR"] = str(tmp)     # los avisos de estas pruebas no tocan el avisos.json real
import avisos as av  # noqa: E402
w.STATE_F, w.LOCK_F, w.DEV_F, w.ENROLL_F = tmp / "st.json", tmp / "LOCKED", tmp / "dev.json", tmp / "enroll.json"
w.APP_F, w.APP_SECRETO_DESTINO = tmp / "app_pedro.json", tmp / ".secreto_app"
PUERTO_WEB, PUERTO_PUENTE, PUERTO_FUERA = 18811, 18812, 18813
w.PORT = PUERTO_WEB
avisos = []
w.H.update({"log": lambda m: None, "alert": lambda m: avisos.append(m), "estado": lambda: "CPU ok",
           "vivo": lambda w_, q_: b"\xff\xd8JPEG", "raton": lambda d: {"ok": True}})
registro = []
w.log = lambda m: registro.append(m)
w.save_state({"ips": {}, "recent": [], "pause_until": 0, "active_link": None})
tuneles = []
def _sin_tunel():
    tuneles.append(1)
    raise RuntimeError("la app NO debe abrir el túnel")
w.ensure_tunnel = _sin_tunel
fallos = 0


def espera_aviso(n_antes, seg=1.0):
    """El aviso de /a/ sale en un hilo: espera (hasta 1 s) a que llegue."""
    t0 = time.time()
    while len(avisos) <= n_antes and time.time() - t0 < seg:
        time.sleep(0.02)
    return avisos[-1] if len(avisos) > n_antes else None


def espera_log(pred, seg=1.0):
    """El log del puente se escribe DESPUÉS de enviar la respuesta: espera (hasta 1 s) a que aparezca la línea."""
    t0 = time.time()
    while not pred() and time.time() - t0 < seg:
        time.sleep(0.02)
    return pred()


def post_reintento(*a, **k):
    """Windows resetea la conexión si el servidor contesta 401 sin leer el cuerpo: un reintento, no un fallo."""
    try:
        return requests.post(*a, **k)
    except requests.exceptions.ConnectionError:
        return requests.post(*a, **k)


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
n_avisos = len(avisos)
r2 = s.get(url, allow_redirects=False, timeout=5)
ok(r2.status_code == 302 and r2.headers.get("Location") == "/app", "GET /a/<token> -> 302 a /app")
ok("sid=" in r2.headers.get("Set-Cookie", "") and "HttpOnly" in r2.headers.get("Set-Cookie", ""), "pone la cookie de sesión sid (HttpOnly)")
ok(espera_aviso(n_avisos) == "Entrada de prueba desde este PC (127.0.0.1).", "entrada desde la IP del propio PC (la del puente) -> aviso «de prueba»")
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
ok(espera_log(lambda: any(m.startswith("app: POST /api/estado 200 ") and m.rstrip().endswith("(127.0.0.1)") for m in registro)), "log por llamada: acción, código, ms e IP")
import re as _re
ok(espera_log(lambda: any(m.startswith("app: GET /a/… 302") for m in registro)) and not any(_re.search(r"/a/[A-Za-z0-9_-]{20,}", m) for m in registro),
   "el log no guarda tokens")
# IP falsa en Cf-Connecting-Ip: el puente la ignora
url = pedir().json()["url"]
with w.LOCKS["state"]:
    st = w.load_state(); st["ips"]["127.0.0.1"] = {"fails": 0, "blocked_until": time.time() + 600}; w.save_state(st)
ok(requests.get(url, headers={"Cf-Connecting-Ip": "8.8.8.8"}, allow_redirects=False, timeout=5).status_code == 404,
   "puente: Cf-Connecting-Ip falsa no salta el bloqueo de IP")
w.save_state({"ips": {}, "recent": [], "pause_until": 0, "active_link": None})
ok(requests.post(f"{P}/logout", headers=HJ, json={}, timeout=5).status_code == 200, "puente: POST /logout -> 200")
ok(post_reintento(f"{P}/api/estado", headers=HJ, json={}, timeout=5).status_code == 401, "tras /logout la sesión ya no vale")
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

# ---------------------------------------------------------------- 10/11: aviso fuera del camino crítico
n_avisos = len(avisos)
lento_alerta = w.H["alert"]
w.H["alert"] = lambda m: (time.sleep(3), avisos.append(m))
url = pedir().json()["url"]
t0 = time.time()
r = requests.get(url, allow_redirects=False, timeout=10)
ok(r.status_code == 302 and time.time() - t0 < 0.5, "/a/ responde sin esperar a Telegram (aviso que tarda 3 s)")
w.H["alert"] = lento_alerta
tok = pedir().json()["url"].rsplit("/", 1)[1]
n_avisos = len(avisos)
requests.get(f"http://127.0.0.1:{PUERTO_WEB}/a/{tok}", headers={"Cf-Connecting-Ip": "100.90.1.2"}, allow_redirects=False, timeout=5)
ok(espera_aviso(n_avisos) == "Entrada desde la app Pedro (iPhone) desde 100.90.1.2.", "IP que no es la del PC -> aviso normal con la IP")

# ---------------------------------------------------------------- 10/11: llamadas frecuentes del mando en el log
registro.clear()
url = pedir().json()["url"]
sid = requests.get(url, allow_redirects=False, timeout=5).cookies.get("sid")
HJ = {"Cookie": f"sid={sid}", "X-Jarvis": "1"}
ok(all(requests.post(f"{P}/api/vivo", headers=HJ, json={}, timeout=5).status_code == 200 for _ in range(3)), "puente: /api/vivo -> 200")
ok(all(requests.post(f"{P}/api/raton", headers=HJ, json={"a": "mover"}, timeout=5).status_code == 200 for _ in range(3)), "puente: /api/raton -> 200")
ok(not any("/api/vivo" in m or "/api/raton" in m for m in registro), "log: /api/vivo y /api/raton con 2xx y rápidos NO se registran")
requests.post(f"{P}/api/vivo", headers={"X-Jarvis": "1"}, json={}, timeout=5)
ok(espera_log(lambda: any(m.startswith("app: POST /api/vivo 401") for m in registro)), "log: /api/vivo con error SÍ se registra")
rapido = w.H["raton"]
w.H["raton"] = lambda d: (time.sleep(1.6), {"ok": True})[1]
requests.post(f"{P}/api/raton", headers=HJ, json={}, timeout=5)
w.H["raton"] = rapido
ok(espera_log(lambda: any(m.startswith("app: POST /api/raton 200") for m in registro)), "log: /api/raton lento (>1500 ms) SÍ se registra")
requests.post(f"{P}/api/estado", headers=HJ, json={}, timeout=5)
ok(espera_log(lambda: any(m.startswith("app: POST /api/estado 200") for m in registro)), "log: las demás llamadas se siguen registrando siempre")

# ---------------------------------------------------------------- 12/11: avisos con respuesta y llamada por voz (Puente, con sesión)
w.save_state({"ips": {}, "recent": [], "pause_until": 0, "active_link": None})
w.APP_TIMES.clear()
sid = requests.get(pedir().json()["url"], allow_redirects=False, timeout=5).cookies.get("sid")
CK = {"Cookie": f"sid={sid}"}
HJ = dict(CK, **{"X-Jarvis": "1"})
F = f"http://127.0.0.1:{PUERTO_FUERA}"
W = f"http://127.0.0.1:{PUERTO_WEB}"
for ruta in ("/api/avisos", "/api/avisos/responder", "/api/llamada/turno"):
    ok(requests.post(f"{P}{ruta}", headers={"X-Jarvis": "1"}, json={}, timeout=5).status_code == 401, f"puente: {ruta} sin sesión -> 401")
    ok(requests.post(f"{P}{ruta}", headers=CK, json={}, timeout=5).status_code == 403, f"puente: {ruta} sin X-Jarvis -> 403")
    ok(requests.post(f"{F}{ruta}", headers=HJ, json={}, timeout=5).status_code == 404, f"fuera de Tailscale: {ruta} -> 404")

# --- avisos
ok(requests.post(f"{P}/api/avisos", headers=HJ, json={}, timeout=5).json() == {"avisos": []}, "puente: /api/avisos sin nada -> {avisos: []}")
preg = av.crear("¿Sigo con el despliegue?", ["Sí", "No"], espera=True, urgente=True, origen="Orquestador Gemsy")
info = av.crear("Copia terminada", origen="Pedro")
r = requests.post(f"{P}/api/avisos", headers=HJ, json={}, timeout=5)
lista = r.json()["avisos"]
ok(r.status_code == 200 and [x["id"] for x in lista] == [preg["id"]], "puente: /api/avisos devuelve solo las pendientes")
ok(set(lista[0]) == set(av.PUBLICOS) and lista[0]["opciones"] == ["Sí", "No"] and lista[0]["urgente"] and lista[0]["origen"] == "Orquestador Gemsy"
   and lista[0]["estado"] == "pendiente" and lista[0]["respuesta"] is None, "el aviso trae todos los campos del contrato")
ok({x["id"] for x in requests.post(f"{P}/api/avisos", headers=HJ, json={"todos": True}, timeout=5).json()["avisos"]} == {preg["id"], info["id"]},
   "todos:true trae también los informativos")
ok({x["id"] for x in requests.post(f"{P}/api/avisos", headers=HJ, json={"todos": "si"}, timeout=5).json()["avisos"]} == {preg["id"]},
   "solo todos:true (booleano) amplía la lista")
rp = lambda i, resp, base=P: requests.post(f"{base}/api/avisos/responder", headers=HJ, json={"id": i, "respuesta": resp}, timeout=5)
ok(rp("noexiste", "x").status_code == 400, "responder a un id que no existe -> 400")
ok(rp(preg["id"], "").status_code == 400 and rp(preg["id"], "x" * 2001).status_code == 400, "respuesta vacía o de más de 2000 caracteres -> 400")
ok(requests.post(f"{P}/api/avisos/responder", headers=HJ, json={"id": preg["id"]}, timeout=5).status_code == 400, "sin campo respuesta -> 400")
ok(requests.post(f"{P}/api/avisos/responder", headers=HJ, json={"id": preg["id"], "respuesta": 5}, timeout=5).status_code == 400, "respuesta que no es texto -> 400")
ok(av.obtener(preg["id"])["estado"] == "pendiente", "los rechazos no tocan el aviso")
r = rp(preg["id"], "Sí, sigue")
ok(r.status_code == 200 and r.json() == {"ok": True}, "responder -> 200 {ok: true}")
x = av.obtener(preg["id"])
ok(x["estado"] == "respondido" and x["respuesta"] == "Sí, sigue" and x["via"] == "app" and x["respondido_en"], "queda respondido con via «app» (entró por el Puente)")
r = rp(preg["id"], "No")
ok(r.status_code == 400 and "respondido" in r.json()["error"] and av.obtener(preg["id"])["respuesta"] == "Sí, sigue", "doble respuesta -> 400 y gana la primera")
ok(rp(info["id"], "x").status_code == 400, "un informativo no admite respuesta -> 400")
ok(requests.post(f"{P}/api/avisos", headers=HJ, json={}, timeout=5).json() == {"avisos": []}, "respondido: ya no sale en pendientes")
preg2 = av.crear("¿A o B?", ["A", "B"], espera=True)
r = rp(preg2["id"], "B", W)
ok(r.status_code == 200 and av.obtener(preg2["id"])["via"] == "web", "por el túnel la respuesta queda con via «web»")
ok(any(m.startswith("aviso ") and "respondido desde app" in m for m in registro) and not any("Sí, sigue" in m for m in registro),
   "el log dice quién respondió, no qué respondió")
ok(espera_log(lambda: any(m.startswith("app: POST /api/avisos/responder 400") for m in registro)), "el log del puente registra las llamadas a los avisos")

# --- llamada por voz
llam = {"stt": [], "brain": [], "tts": []}
audio = b"\x1aE\xdf\xa3" * 300


def f_stt(b):
    llam["stt"].append(len(b))
    return "  qué hora es  "


def f_brain(p, m, b="claude", modelo=None):
    llam["brain"].append((p, m, b, modelo))
    return "Son las tres."


def f_tts(t, v):
    llam["tts"].append((t, v))
    return b"ID3-FALSO-MP3"


w.H.update({"stt": f_stt, "brain": f_brain, "tts": f_tts})


def turno(qs="", cab=None, cuerpo=audio, tipo="audio/webm", base=P):
    return requests.post(f"{base}/api/llamada/turno{qs}", headers=dict(HJ, **{"Content-Type": tipo}, **(cab or {})), data=cuerpo, timeout=5)


def espera_job(r, base=P):
    assert r.status_code == 200 and r.json().get("job"), (r.status_code, r.text)
    for _ in range(200):
        j = requests.get(f"{base}/api/job/{r.json()['job']}", headers=HJ, timeout=5).json()
        if j.get("state") == "done":
            return j
        time.sleep(0.03)
    return {}


registro.clear()
r = turno()
ok(r.status_code == 200 and list(r.json()) == ["job"], "puente: audio -> 200 con {job}")
j = espera_job(r)
ok(j["oido"] == "qué hora es" and j["texto"] == "Son las tres." and base64.b64decode(j["audio_b64"]) == b"ID3-FALSO-MP3", "resultado: oido (transcrito y sin espacios), texto y audio_b64 (mp3 de voz.py)")
ok(set(j["ms"]) == {"stt", "cerebro", "tts"} and all(isinstance(v, int) and v >= 0 for v in j["ms"].values()) and "error" not in j, "ms con stt/cerebro/tts y sin error")
ok(llam["stt"][-1] == len(audio), "el audio entero llega al reconocedor")
p, m, b, mod = llam["brain"][-1]
ok(p == w.VOZ_PREFIJO + "qué hora es" and m == "ask" and b == "claude" and mod is None, "cerebro: prefijo de voz + lo oído, modo ask, claude y sin modelo especial por defecto")
ok(llam["tts"][-1] == ("Son las tres.", "es-ES-AlvaroNeural"), "voz por defecto es-ES-AlvaroNeural")
ok(espera_log(lambda: any(m.startswith("llamada: claude/ask") and "stt=" in m and "cerebro=" in m and "tts=" in m and "total=" in m for m in registro)), "el log mide cada fase: stt, cerebro, tts y total")
ok(not any("qué hora" in m or "Son las tres" in m for m in registro), "el log de la llamada no guarda lo hablado")
n_stt = len(llam["stt"])
j = espera_job(turno(cuerpo=b'{"texto": "  hola Pedro  "}', tipo="application/json"))
ok(j["oido"] == "hola Pedro" and j["texto"] == "Son las tres." and j["ms"]["stt"] == 0 and len(llam["stt"]) == n_stt and llam["brain"][-1][0] == w.VOZ_PREFIJO + "hola Pedro",
   "JSON {texto}: no pasa por el reconocedor (stt = 0 ms)")
j = espera_job(turno("?cerebro=kimi&voz=es-ES-ElviraNeural"))
ok(llam["brain"][-1][2] == "kimi" and llam["tts"][-1][1] == "es-ES-ElviraNeural", "query: cerebro=kimi y voz")
j = espera_job(turno(cab={"X-Cerebro": "local", "X-Voz": "es-MX-JorgeNeural"}))
ok(llam["brain"][-1][2] == "local" and llam["tts"][-1][1] == "es-MX-JorgeNeural", "cabeceras X-Cerebro y X-Voz valen igual")
j = espera_job(turno(cuerpo=b'{"texto": "ey", "cerebro": "agy"}', tipo="application/json"))
ok(llam["brain"][-1][2] == "agy", "cerebro también puede ir en el JSON")
j = espera_job(turno("?cerebro=local", cab={"X-Cerebro": "kimi"}))
ok(llam["brain"][-1][2] == "local", "la query manda sobre la cabecera")
ok(turno("?cerebro=gpt").status_code == 400 and turno("?cerebro=auto").status_code == 400, "cerebro desconocido (o «auto») -> 400: nunca automático")
n_b = len(llam["brain"])
ok(turno("?modo=do").status_code == 400 and turno("?modo=do&confirm=false").status_code == 400 and turno("?modo=raro").status_code == 400, "modo do sin confirm=true (o modo raro) -> 400")
ok(len(llam["brain"]) == n_b, "los 400 no llegan al cerebro")
j = espera_job(turno("?modo=do&confirm=true"))
ok(llam["brain"][-1][1] == "do", "modo=do con confirm=true -> cerebro en modo do")
j = espera_job(turno("?modo=do", cab={"X-Confirm": "true"}))
ok(llam["brain"][-1][1] == "do", "confirm por cabecera X-Confirm")
ok(turno(tipo="text/plain").status_code == 400 and turno(cuerpo=b"", tipo="audio/webm").status_code == 400 and turno(cuerpo=b"no json", tipo="application/json").status_code == 400
   and turno(cuerpo=b'{"texto": "  "}', tipo="application/json").status_code == 400 and turno(cuerpo=b"[1]", tipo="application/json").status_code == 400,
   "tipo no válido, cuerpo vacío, JSON roto, texto vacío o JSON que no es objeto -> 400")
# modelo de voz (JARVIS_MODELO_VOZ): solo Claude, solo en la llamada
w.CFG["JARVIS_MODELO_VOZ"] = "haiku"
espera_job(turno())
ok(llam["brain"][-1][3] == "haiku", "JARVIS_MODELO_VOZ=haiku -> las llamadas de Claude usan haiku")
espera_job(turno("?cerebro=kimi"))
ok(llam["brain"][-1][3] is None and llam["brain"][-1][2] == "kimi", "...pero Kimi no recibe ese modelo")
del w.CFG["JARVIS_MODELO_VOZ"]
espera_job(turno())
ok(llam["brain"][-1][3] is None, "sin JARVIS_MODELO_VOZ -> el de siempre")
# fallos de cada fase
ok(espera_job(turno())["audio_b64"] is not None, "(control) todo bien antes de romper cosas")
w.H["stt"] = lambda b: ""
nb = len(llam["brain"])
j = espera_job(turno())
ok(j["error"] == "sin_voz" and j["oido"] == "" and "repetirlo" in j["texto"] and j["audio_b64"] and len(llam["brain"]) == nb, "audio sin voz: pide repetir (con voz) sin molestar al cerebro")
w.H["stt"] = lambda b: (_ for _ in ()).throw(RuntimeError("boom con datos privados"))
j = espera_job(turno())
ok(j["error"] == "stt" and j["texto"] == "No pude transcribir el audio." and j["audio_b64"] is None and "ms" in j, "stt roto: error «stt», sin tumbar nada")
w.H["stt"] = f_stt
w.H["brain"] = lambda p, m, b="claude", modelo=None: (_ for _ in ()).throw(RuntimeError("cerebro caído"))
j = espera_job(turno())
ok(j["error"] == "cerebro" and j["oido"] == "qué hora es" and j["audio_b64"], "cerebro roto: error «cerebro», conserva lo oído y lo dice en voz")
w.H["brain"] = f_brain
w.H["tts"] = lambda t, v: (_ for _ in ()).throw(RuntimeError("sin internet"))
j = espera_job(turno())
ok(j["texto"] == "Son las tres." and j["audio_b64"] is None and "error" not in j, "tts roto: la respuesta en texto llega igualmente (audio_b64 null)")
w.H["tts"] = f_tts
# por el túnel (mismo Handler) también existe, con la misma sesión
r = requests.post(f"{W}/api/llamada/turno", headers=HJ | {"Content-Type": "audio/webm"}, data=audio, timeout=5)
ok(r.status_code == 200 and espera_job(r, W)["texto"] == "Son las tres.", "por el túnel: /api/llamada/turno también funciona")
ok(requests.post(f"{W}/api/avisos", headers=HJ, json={}, timeout=5).status_code == 200, "por el túnel: /api/avisos también funciona")
ok(espera_log(lambda: any(m.startswith("app: POST /api/llamada/turno 200") for m in registro)), "el log del puente registra cada turno")

print("TODAS LAS PRUEBAS DE LA APP OK" if not fallos else f"{fallos} FALLOS")
raise SystemExit(1 if fallos else 0)
