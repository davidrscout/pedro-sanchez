# -*- coding: utf-8 -*-
"""Panel web de JARVIS. Solo escucha en 127.0.0.1; se publica con un túnel de Cloudflare TEMPORAL (solo salida).

Flujo: /web en Telegram -> enlace de un solo uso (60 s) -> página de PIN -> sesión corta con cookie.
Telegram NO es de fiar (cuenta compartida): lo único que protege es el PIN, con bloqueos duros.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path(__file__).resolve().parent
STATE_F = HOME / "webpanel_state.json"
LOCK_F = HOME / "LOCKED"
DEV_F = HOME / "devices.json"       # dispositivos autorizados (hash de su cookie)
ENROLL_F = HOME / "enroll.json"     # ventana de enrolamiento abierta desde el PC
NOWIN = 0x08000000
CLOUDFLARED = shutil.which("cloudflared") or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"

TOKEN_TTL = 60          # s que vale el enlace
NONCE_TTL = 120         # s para teclear el PIN tras abrir el enlace
SESSION_IDLE = 43200     # 12 h sin actividad (uso remoto sin prisa)
SESSION_MAX = 259200     # 3 días máximo absoluto
FAILS_PER_TOKEN = 3
IP_FAIL_LIMIT = 3          # 3 PIN fallidos seguidos desde la MISMA IP -> esa IP queda bloqueada
IP_BLOCK_S = 86400         # 24 h (DESBLOQUEAR.cmd en el PC lo quita antes)
GLOBAL_FAILS_PER_HOUR = 9  # red de seguridad: ataque repartido entre muchas IP -> pausa global de 1 h

VOZ_PREFIJO = ("[Conversación por VOZ con David: contesta en español de España, como en una charla, en 1-3 frases cortas, "
               "sin markdown, sin listas, sin enlaces ni código. Si hace falta más detalle, ofrécelo.]\n")
H = {}      # callables que inyecta jarvis.py
CFG = {}
PORT = 18765
TOKENS = {}     # token -> {"t": creado, "fails": n, "dead": bool}
NONCES = {}     # nonce -> {"token": t, "t": creado}
SESS = {"sid": None, "t0": 0, "last": 0}
JOBS = {}
TUN = {"proc": None, "url": None, "since": 0}
LOCKS = {"tun": threading.Lock(), "state": threading.Lock(), "srv": threading.Lock()}
SERVER = {"httpd": None}
LINK_TIMES = []


def log(msg):
    H.get("log", lambda m: None)(msg)


# ---------------------------------------------------------------- PIN y estado persistente
def make_hash(pin):
    salt = os.urandom(16)
    return salt.hex() + "$" + hashlib.scrypt(pin.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()


def pin_ok(pin):
    return _verify(pin, CFG.get("JARVIS_PIN_HASH", ""))


def load_state():
    try:
        st = json.loads(STATE_F.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    st.setdefault("ips", {})        # ip -> {"fails": n, "blocked_until": ts}
    st.setdefault("recent", [])     # marcas de tiempo de fallos (todas las IPs) para la red de seguridad global
    st.setdefault("pause_until", 0)
    return st


def save_state(s):
    STATE_F.write_text(json.dumps(s), encoding="utf-8")


def lock_status():
    """Bloqueo GLOBAL (solo manual con LOCKED o pausa de seguridad por ataque repartido). None si se puede."""
    if LOCK_F.exists():
        return "Panel BLOQUEADO manualmente. Se desbloquea en el PC con DESBLOQUEAR.cmd."
    st = load_state()
    if time.time() < st.get("pause_until", 0):
        return f"Panel en pausa de seguridad {int((st['pause_until'] - time.time()) // 60) + 1} min (demasiados fallos desde varias IP)."
    return None


def ip_blocked(ip):
    """None si la IP puede intentar; si no, el motivo."""
    rec = load_state()["ips"].get(ip)
    if rec and time.time() < rec.get("blocked_until", 0):
        return f"Tu IP está bloqueada {int((rec['blocked_until'] - time.time()) // 3600) + 1} h por fallos de PIN."
    return None


def register_fail(ip):
    """Cuenta el fallo para ESA IP. A los IP_FAIL_LIMIT fallos seguidos se bloquea esa IP IP_BLOCK_S segundos.
    Devuelve (fallos_de_la_ip, bloqueada_ahora)."""
    with LOCKS["state"]:
        st = load_state()
        now = time.time()
        rec = st["ips"].setdefault(ip, {"fails": 0, "blocked_until": 0})
        rec["fails"] += 1
        blocked = False
        if rec["fails"] >= IP_FAIL_LIMIT:
            rec["blocked_until"] = now + IP_BLOCK_S
            rec["fails"] = 0
            blocked = True
        st["recent"] = [t for t in st["recent"] if now - t < 3600] + [now]
        if len(st["recent"]) >= GLOBAL_FAILS_PER_HOUR:
            st["pause_until"] = now + 3600
            st["recent"] = []
        # limpia IPs viejas
        st["ips"] = {k: v for k, v in st["ips"].items() if v["fails"] or v["blocked_until"] > now}
        save_state(st)
        return rec["fails"], blocked


def register_ok(ip):
    with LOCKS["state"]:
        st = load_state()
        st["ips"].pop(ip, None)
        save_state(st)


# ---------------------------------------------------------------- dispositivos autorizados
# Un IMEI no es accesible desde una web. En su lugar: cada móvil se ENROLA una vez desde el PC (ENROLAR.cmd) y
# recibe una cookie larga y aleatoria. Sin ella, el enlace ni siquiera enseña la página del PIN.
DEV_COOKIE_MAX = 31536000


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _hash(x):
    return hashlib.sha256(x.encode("utf-8")).hexdigest()


def device_cookie_of(handler):
    m = re.search(r"(?:^|;\s*)dev=([A-Za-z0-9_\-]{20,})", handler.headers.get("Cookie", ""))
    return m.group(1) if m else None


def require_device():
    """Autorización por dispositivo (cookie). APAGADA por defecto: con túnel de dirección aleatoria la cookie se pierde en
    cada enlace nuevo, y el código TOTP de Telegram ya impide que nadie más consiga el enlace. Útil si algún día hay
    un dominio fijo (túnel con nombre)."""
    return CFG.get("JARVIS_REQUIRE_DEVICE", "0") == "1"


def device_ok(handler):
    c = device_cookie_of(handler)
    return bool(c) and _hash(c) in _read_json(DEV_F, {})


def _verify(secret, hashstr):
    try:
        salt_hex, hash_hex = (hashstr or "").split("$")
        calc = hashlib.scrypt(str(secret).encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32).hex()
        return hmac.compare_digest(calc, hash_hex)
    except Exception:
        return False


def enroll_open():
    """El alta de móviles nuevos usa un código fijo de 8 dígitos (JARVIS_ENROLL_HASH). Sin él, no se pueden dar de alta."""
    return bool(CFG.get("JARVIS_ENROLL_HASH"))


def enroll_check(code):
    return _verify(code, CFG.get("JARVIS_ENROLL_HASH", ""))


def add_device(label="móvil"):
    tok = secrets.token_urlsafe(32)
    devs = _read_json(DEV_F, {})
    devs[_hash(tok)] = {"label": label, "added": time.strftime("%Y-%m-%d %H:%M:%S")}
    DEV_F.write_text(json.dumps(devs), encoding="utf-8")
    return tok


# ---------------------------------------------------------------- túnel
def tunnel_host():
    u = TUN.get("url") or ""
    return re.sub(r"^https://", "", u)


def stop_tunnel():
    p = TUN.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    TUN.update({"proc": None, "url": None})


def ensure_server():
    with LOCKS["srv"]:
        if SERVER["httpd"]:
            return
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        SERVER["httpd"] = httpd


def ensure_tunnel():
    with LOCKS["tun"]:
        if TUN["proc"] and TUN["proc"].poll() is None and TUN["url"]:
            return TUN["url"]
        stop_tunnel()
        ensure_server()
        p = subprocess.Popen([CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NOWIN,
                             text=True, encoding="utf-8", errors="replace")
        found = threading.Event()

        def reader():
            for line in p.stdout:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m and not TUN["url"]:
                    TUN["url"] = m.group(0)
                    found.set()
        threading.Thread(target=reader, daemon=True).start()
        TUN["proc"], TUN["since"] = p, time.time()
        if not found.wait(40):
            stop_tunnel()
            raise RuntimeError("El túnel de Cloudflare no arrancó a tiempo.")
        time.sleep(2)  # que el DNS del túnel se propague
        return TUN["url"]


def new_link():
    """Devuelve (url, error). Rate limit + bloqueos incluidos."""
    why = lock_status()
    if why:
        return None, why
    now = time.time()
    LINK_TIMES[:] = [t for t in LINK_TIMES if now - t < 3600]
    if LINK_TIMES and now - LINK_TIMES[-1] < 20:
        return None, "Espera unos segundos antes de pedir otro enlace."
    if len(LINK_TIMES) >= 8:
        return None, "Demasiados enlaces en la última hora."
    LINK_TIMES.append(now)
    base = ensure_tunnel()
    for k in [k for k, v in TOKENS.items() if now - v["t"] > TOKEN_TTL * 3]:
        TOKENS.pop(k, None)
    tok = secrets.token_urlsafe(24)
    TOKENS[tok] = {"t": now, "fails": 0, "dead": False}
    log("enlace web generado")
    return f"{base}/t/{tok}", None


def session_valid(handler):
    cookie = handler.headers.get("Cookie", "")
    m = re.search(r"(?:^|;\s*)sid=([A-Za-z0-9_\-]+)", cookie)
    now = time.time()
    if not m or not SESS["sid"] or not hmac.compare_digest(m.group(1), SESS["sid"]):
        return False
    if now - SESS["last"] > SESSION_IDLE or now - SESS["t0"] > SESSION_MAX:
        SESS["sid"] = None
        return False
    SESS["last"] = now
    return True


def janitor():
    idle_since = None
    while True:
        time.sleep(15)
        try:
            now = time.time()
            if SESS["sid"] and (now - SESS["last"] > SESSION_IDLE or now - SESS["t0"] > SESSION_MAX):
                SESS["sid"] = None
            live_tok = any((not v["dead"]) and now - v["t"] < TOKEN_TTL for v in TOKENS.values())
            busy = bool(SESS["sid"]) or live_tok
            if TUN["proc"] and not busy:
                idle_since = idle_since or now
                if now - idle_since > 120:
                    stop_tunnel()
                    log("túnel cerrado por inactividad")
                    idle_since = None
            else:
                idle_since = None
        except Exception:
            pass


# ---------------------------------------------------------------- servidor
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".woff2": "font/woff2", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8", ".glsl": "text/plain; charset=utf-8",
                ".vert": "text/plain; charset=utf-8", ".frag": "text/plain; charset=utf-8", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"}
CSP = ("default-src 'none'; img-src 'self' blob: data:; font-src 'self' data:; media-src 'self' blob: data:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; worker-src 'self' blob:; "
       "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = "J"
    sys_version = ""

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None, cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            for item in (v if isinstance(v, list) else [v]):
                self.send_header(k, item)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8", extra)

    def _host_ok(self):
        host = self.headers.get("Host", "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost", tunnel_host().lower())

    def _ip(self):
        return self.headers.get("Cf-Connecting-Ip", self.client_address[0])

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 20000:
                return {}
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _origin_ok(self):
        o = self.headers.get("Origin")
        return (not o) or o.endswith("://" + tunnel_host()) or o.startswith("http://127.0.0.1")

    # -------------------------------------------------- GET
    def do_GET(self):
        if not self._host_ok():
            return self._send(421, "no")
        path = self.path.split("?")[0]
        if path.startswith("/t/"):
            tok = path[3:]
            t = TOKENS.get(tok)
            if not t or t["dead"] or time.time() - t["t"] > TOKEN_TTL or lock_status() or ip_blocked(self._ip()):
                return self._send(404, "no")
            known = (not require_device()) or device_ok(self)
            if not known and not enroll_open():
                log(f"enlace abierto desde dispositivo NO autorizado ({self._ip()})")
                return self._send(404, "no")
            nonce = secrets.token_urlsafe(18)
            NONCES[nonce] = {"token": tok, "t": time.time()}
            v1 = "v=1" in self.path.partition("?")[2].split("&")
            page = ui("pin_v1.html" if v1 else "pin.html", PIN_HTML).replace("__NONCE__", nonce).replace("__ENROLL__", "0" if known else "1")
            # Red de seguridad: ?v=1 en el enlace = interfaz anterior (cookie ui=v1 hasta que se pida un enlace sin ?v=1)
            ck = "ui=v1; Path=/; SameSite=Lax; Max-Age=86400" if v1 else "ui=; Path=/; SameSite=Lax; Max-Age=0"
            return self._send(200, page, "text/html; charset=utf-8", extra={"Set-Cookie": ck})
        if path.startswith("/s/"):
            return self._static(path[3:])
        if path == "/app":
            if not session_valid(self):
                return self._send(302, "", extra={"Location": "/gone"})
            old_ui = "ui=v1" in self.headers.get("Cookie", "")
            return self._send(200, ui("app_v1.html" if old_ui else "app.html", APP_HTML), "text/html; charset=utf-8")
        if path.startswith("/api/job/"):
            if not session_valid(self):
                return self._json(401, {"error": "sesion"})
            job = JOBS.get(path[len("/api/job/"):])
            return self._json(200, job or {"state": "none"})
        if path == "/gone":
            return self._send(401, "Sesión no válida o caducada. Pide otro enlace con /web.")
        return self._send(404, "no")

    # -------------------------------------------------- POST
    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._send(421, "no")
        path = self.path.split("?")[0]
        if path == "/login":
            return self._login()
        if self.headers.get("X-Jarvis") != "1":
            return self._json(403, {"error": "cabecera"})
        if not session_valid(self):
            return self._json(401, {"error": "sesion"})
        if path == "/logout":
            SESS["sid"] = None
            threading.Thread(target=lambda: (time.sleep(2), stop_tunnel()), daemon=True).start()
            return self._json(200, {"ok": True})
        if path == "/api/stt":
            return self._stt()
        if path.startswith("/api/"):
            return self._api(path[5:], self._body())
        return self._send(404, "no")

    def _login(self):
        d = self._body()
        now = time.time()
        ip = self._ip()
        why = lock_status() or ip_blocked(ip)
        if why:
            return self._json(429, {"error": why})
        n = NONCES.pop(str(d.get("nonce", "")), None)
        t = TOKENS.get(n["token"]) if n else None
        if (not n) or (not t) or t["dead"] or now - n["t"] > NONCE_TTL or now - t["t"] > TOKEN_TTL + NONCE_TTL:
            return self._json(401, {"error": "Enlace caducado. Pide otro con /web."})
        pin = str(d.get("pin", ""))[:32]
        known = (not require_device()) or device_ok(self)
        enrolled_now = False
        if not known:
            enrolled_now = enroll_check(str(d.get("enroll", ""))[:16])
        if (known or enrolled_now) and pin_ok(pin):
            t["dead"] = True
            register_ok(ip)
            SESS.update({"sid": secrets.token_urlsafe(32), "t0": now, "last": now})
            cookies = [f"sid={SESS['sid']}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age={SESSION_MAX}"]
            if enrolled_now:
                cookies.append(f"dev={add_device()}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={DEV_COOKIE_MAX}")
                log(f"DISPOSITIVO NUEVO enrolado desde {ip}")
                H.get("alert", lambda m: None)("Se ha enrolado un dispositivo nuevo en el panel.")
            log(f"login web OK desde {ip}")
            return self._json(200, {"ok": True}, {"Set-Cookie": cookies})
        t["fails"] += 1
        fails, blocked = register_fail(ip)
        log(f"PIN FALLIDO desde {ip} (IP {fails}/{IP_FAIL_LIMIT}, bloqueada={blocked})")
        if blocked:
            t["dead"] = True
            H.get("alert", lambda m: None)(f"IP {ip} BLOQUEADA 24 h por 3 PIN fallidos en el panel.")
            return self._json(429, {"error": "PIN incorrecto 3 veces. Tu IP queda bloqueada 24 h."})
        H.get("alert", lambda m: None)(f"PIN fallido en el panel desde {ip} ({fails}/{IP_FAIL_LIMIT}).")
        if t["fails"] >= FAILS_PER_TOKEN:
            t["dead"] = True
            return self._json(401, {"error": "PIN incorrecto. Enlace anulado; pide otro con /web."})
        left = IP_FAIL_LIMIT - fails
        nn = secrets.token_urlsafe(18)
        NONCES[nn] = {"token": n["token"], "t": time.time()}
        return self._json(401, {"error": f"PIN incorrecto. Te quedan {left}.", "nonce": nn})

    def _stt(self):
        """Audio del móvil (binario, máx. 6 MB ~ 3-4 min) -> texto con Whisper en el PC."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > 6_000_000 or not self.headers.get("Content-Type", "").startswith("audio/"):
            return self._json(400, {"error": "audio no válido"})
        data = self.rfile.read(n)
        try:
            return self._json(200, {"text": H["stt"](data)})
        except Exception as e:
            log(f"stt error {type(e).__name__}: {str(e)[:150]}")
            return self._json(500, {"error": "No pude transcribir el audio."})

    def _static(self, rel):
        """Ficheros públicos de la interfaz (ui/static): js, css, shaders, fuentes, imágenes. Sin secretos, sin listados,
        sin salir de la carpeta."""
        try:
            root = (HOME / "ui" / "static").resolve()
            p = (root / rel).resolve()
            ctype = STATIC_TYPES.get(p.suffix.lower())
            if root not in p.parents or not p.is_file() or not ctype or "\\" in rel or ".." in rel:
                return self._send(404, "no")
            return self._send(200, p.read_bytes(), ctype, cache="public, max-age=60")
        except Exception:
            return self._send(404, "no")

    def _job(self, fn):
        jid = uuid.uuid4().hex[:10]
        JOBS[jid] = {"state": "running"}
        if len(JOBS) > 50:
            JOBS.pop(next(iter(JOBS)), None)

        def work():
            try:
                res = fn()
                JOBS[jid] = {"state": "done", **(res if isinstance(res, dict) else {"text": str(res)})}
            except Exception as e:
                log(f"job error {type(e).__name__}: {str(e)[:150]}")
                JOBS[jid] = {"state": "done", "text": f"Error: {type(e).__name__}"}
        threading.Thread(target=work, daemon=True).start()
        return self._json(200, {"job": jid})

    def _api(self, action, d):
        try:
            if action == "estado":
                return self._json(200, {"text": H["estado"]()})
            if action == "eventos":
                return self._json(200, {"text": H["eventos"]()})
            if action == "captura":
                return self._send(200, H["captura"](), "image/jpeg")
            if action == "tts":
                return self._send(200, H["tts"](str(d.get("texto", "")), str(d.get("voz", "")) or "es-ES-AlvaroNeural"), "audio/mpeg")
            if action == "vivo":      # captura ligera de la pantalla principal para el mando remoto
                return self._send(200, H["vivo"](d.get("w", 1100), d.get("q", 60)), "image/jpeg")
            if action == "raton":
                r = H["raton"](d)
                return self._json(200, r if isinstance(r, dict) else {"text": r})
            if action == "teclas":
                if d.get("texto"):
                    return self._json(200, {"text": H["escribir"](str(d["texto"]))})
                ks = d.get("combo")
                if not isinstance(ks, list) or not ks:
                    return self._json(400, {"error": "falta combo o texto"})
                return self._json(200, {"text": H["combo"](ks)})
            if action == "ventanas":
                return self._json(200, {"ventanas": H["ventanas"]()})
            if action == "ventana":
                return self._json(200, {"text": H["ventana"](d.get("id", 0), str(d.get("accion", "")))})
            if action == "bloquear":
                H["bloquear"]()
                return self._json(200, {"text": "Sesión bloqueada."})
            if action == "pantalla":
                H["pantalla"]()
                return self._json(200, {"text": "Monitor apagado."})
            if action == "ahorro":
                H["ahorro"]()
                return self._json(200, {"text": "Modo ahorro: bloqueado y monitor apagado."})
            if action == "vol" and d.get("a") in ("up", "down", "mute"):
                H["vol"](d["a"])
                return self._json(200, {"text": f"Volumen: {d['a']}"})
            if action == "abrir":
                return self._json(200, {"text": H["abrir"](str(d.get("app", "")))})
            if action in ("apagar", "reiniciar") and d.get("confirm") is True:
                return self._json(200, {"text": H["power"](action)})
            if action == "cancelar":
                return self._json(200, {"text": H["power"]("cancelar")})
            if action == "modelos":
                return self._json(200, {"backends": H["backends"]()})
            if action == "watchdog":
                return self._json(200, H["watchdog"]())
            if action == "serie":
                return self._json(200, H["serie"]())
            if action == "procesos":
                return self._json(200, H["procesos"]())
            if action == "red":
                return self._json(200, {"text": H["red"]()})
            if action == "matar":
                if d.get("confirm") is not True or not str(d.get("pid", "")).isdigit():
                    return self._json(400, {"error": "falta confirmación o pid"})
                return self._json(200, {"text": H["matar"](int(d["pid"]))})
            if action == "parar":
                return self._json(200, {"text": H["parar"]()})
            if action == "nueva":
                return self._json(200, {"text": H["nueva"]()})
            if action == "stats":
                return self._json(200, H["stats"]())
            if action == "memoria":
                return self._json(200, {"items": H["memoria"]()})
            if action == "recordar":
                return self._json(200, {"text": H["recordar"](str(d.get("texto", ""))[:400])})
            if action == "olvidar":
                return self._json(200, {"text": H["olvidar"](str(d.get("id", ""))[:12])})
            if action == "agenda":
                return self._json(200, {"items": H["agenda"]()})
            if action == "agenda_borrar":
                return self._json(200, {"text": H["agenda_borrar"](str(d.get("id", ""))[:12])})
            if action == "agenda_crear":
                return self._json(200, {"text": H["agenda_crear"](str(d.get("cuando", ""))[:20], str(d.get("texto", ""))[:1500],
                                                                 str(d.get("tipo", "aviso")), str(d.get("repetir", "no"))[:12])})
            if action == "launchers":
                return self._json(200, H["launchers"]())
            if action == "lanzar":
                lid = str(d.get("id", ""))[:60]
                where = "pc" if d.get("donde") == "pc" else "movil"
                return self._job(lambda: H["lanzar"](lid, d.get("confirm") is True, where))
            if action in ("preguntar", "hacer", "agy", "chat"):
                prompt = str(d.get("prompt", "")).strip()[:4000]
                if not prompt:
                    return self._json(400, {"error": "vacío"})
                if action == "chat":
                    backend, mode = str(d.get("backend", "claude")), ("do" if d.get("mode") == "do" else "ask")
                else:
                    backend, mode = ("agy", "do") if action == "agy" else ("claude", "do" if action == "hacer" else "ask")
                if d.get("voz") is True:     # conversación hablada: respuesta corta y apta para leer en voz alta
                    prompt = VOZ_PREFIJO + prompt
                if backend not in ("claude", "agy", "local"):
                    return self._json(400, {"error": "cerebro desconocido"})
                if mode == "do" and d.get("confirm") is not True:
                    return self._json(400, {"error": "falta confirmación"})
                return self._job(lambda: {"text": H["brain"](prompt, mode, backend)})
        except Exception as e:
            log(f"api {action} error {type(e).__name__}: {str(e)[:150]}")
            return self._json(500, {"error": type(e).__name__})
        return self._json(404, {"error": "acción desconocida"})


# ---------------------------------------------------------------- páginas
def ui(name, fallback):
    """La interfaz vive en ui/<name> (editable sin tocar el servidor); si falta, se usa la embebida."""
    try:
        return (HOME / 'ui' / name).read_text(encoding='utf-8')
    except Exception:
        return fallback


BASE_CSS = """
:root{color-scheme:dark;--bg:#05080d;--card:#0c141d;--line:#17324a;--cy:#38e1ff;--tx:#d6e8f5;--mu:#7fa0b8;--rd:#ff5a6a;--gr:#4cf0a6}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.4 system-ui,Segoe UI,sans-serif}
body{padding:16px;max-width:760px;margin:0 auto}h1{font-size:15px;letter-spacing:.35em;color:var(--cy);margin:6px 0 14px;font-weight:600}
button{background:var(--card);color:var(--tx);border:1px solid var(--line);border-radius:10px;padding:12px;font:inherit;cursor:pointer}
button:active{border-color:var(--cy)}input,textarea{width:100%;background:#08111a;color:var(--tx);border:1px solid var(--line);border-radius:10px;padding:12px;font:inherit}
"""

PIN_HTML = """<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS</title><style>""" + BASE_CSS + """
.box{margin-top:18vh;text-align:center}#pin{font-size:34px;text-align:center;letter-spacing:.5em;max-width:260px;margin:14px auto}
#msg{min-height:22px;color:var(--rd);margin-top:10px}</style>
<div class="box"><h1>J.A.R.V.I.S.</h1><div style="color:var(--mu)">PIN</div>
<input id="pin" type="password" inputmode="numeric" autocomplete="off" maxlength="12" autofocus>
<button id="go" style="padding:12px 34px">Entrar</button><div id="msg"></div></div>
<script>
let nonce="__NONCE__";const $=i=>document.getElementById(i);
async function go(){const r=await fetch("/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({nonce:nonce,pin:$("pin").value})});
const j=await r.json().catch(()=>({}));if(r.ok){location.replace("/app");return}
$("msg").textContent=j.error||"Error";if(j.nonce)nonce=j.nonce;$("pin").value="";if(!j.nonce)$("go").disabled=true}
$("go").onclick=go;$("pin").addEventListener("keydown",e=>{if(e.key==="Enter")go()});
</script></html>"""

APP_HTML = """<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS</title><style>""" + BASE_CSS + """
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
#log{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;min-height:120px;max-height:42vh;overflow:auto;white-space:pre-wrap;font:14px/1.45 ui-monospace,Consolas,monospace}
img{max-width:100%;border-radius:10px;margin-top:8px;border:1px solid var(--line)}
.row{display:flex;gap:8px;margin-top:10px}.row button{flex:none}.danger{border-color:#5a2230;color:var(--rd)}
.mu{color:var(--mu);font-size:13px}.on{border-color:var(--gr);color:var(--gr)}
</style>
<h1>J.A.R.V.I.S.</h1>
<div class="grid">
<button data-a="estado">Estado</button><button data-a="eventos">Eventos</button><button data-a="captura">Captura</button>
<button data-a="bloquear">Bloquear</button><button data-a="pantalla">Pantalla off</button><button data-a="ahorro">Ahorro</button>
<button data-v="down">Vol −</button><button data-v="up">Vol +</button><button data-v="mute">Mute</button>
<button data-app="chrome">Chrome</button><button data-app="steam">Steam</button><button data-app="spotify">Spotify</button>
</div>
<div id="log">Listo.</div><div id="shot"></div>
<div class="row"><textarea id="q" rows="2" placeholder="Pregunta (solo lectura)…"></textarea></div>
<div class="row"><button id="ask" style="flex:1">Preguntar</button><button id="agy">agy</button><button id="mic">🎙</button><button id="tts" title="Voz de respuesta">🔈</button></div>
<div class="row"><button id="do" style="flex:1" class="danger">/hacer (con herramientas)</button></div>
<div class="row"><button class="danger" id="off">Apagar</button><button class="danger" id="rb">Reiniciar</button><button id="cx">Cancelar</button><button id="out" style="margin-left:auto">Salir</button></div>
<p class="mu">La sesión caduca sola a los 10 min sin uso.</p>
<script>
const $=i=>document.getElementById(i),log=t=>{$("log").textContent=t};let speak=false;
async function api(a,b){const r=await fetch("/api/"+a,{method:"POST",headers:{"Content-Type":"application/json","X-Jarvis":"1"},body:JSON.stringify(b||{})});
if(r.status===401){log("Sesión caducada. Pide otro enlace con /web.");throw 0}return r}
async function act(a,b){log("…");const r=await api(a,b);if(a==="captura"){const u=URL.createObjectURL(await r.blob());$("shot").innerHTML='<img src="'+u+'">';log("Captura.");return}
const j=await r.json();log(j.text||j.error||"ok");if(j.job)poll(j.job)}
async function poll(id){log("Pensando…");for(;;){await new Promise(r=>setTimeout(r,1500));const r=await fetch("/api/job/"+id);if(r.status===401){log("Sesión caducada.");return}
const j=await r.json();if(j.state==="done"){log(j.text||"(sin respuesta)");if(speak&&window.speechSynthesis){const u=new SpeechSynthesisUtterance((j.text||"").slice(0,600));u.lang="es-ES";speechSynthesis.speak(u)}return}}}
document.querySelectorAll("[data-a]").forEach(b=>b.onclick=()=>act(b.dataset.a));
document.querySelectorAll("[data-v]").forEach(b=>b.onclick=()=>act("vol",{a:b.dataset.v}));
document.querySelectorAll("[data-app]").forEach(b=>b.onclick=()=>act("abrir",{app:b.dataset.app}));
$("ask").onclick=()=>{const p=$("q").value.trim();if(p)act("preguntar",{prompt:p})};
$("agy").onclick=()=>{const p=$("q").value.trim();if(p&&confirm("¿Antigravity actúa con herramientas?\\n\\n"+p))act("agy",{prompt:p,confirm:true})};
$("do").onclick=()=>{const p=$("q").value.trim();if(p&&confirm("¿Ejecuto con herramientas?\\n\\n"+p))act("hacer",{prompt:p,confirm:true})};
$("off").onclick=()=>{if(confirm("¿Apagar el PC por completo? No podrás despertarlo desde aquí."))act("apagar",{confirm:true})};
$("rb").onclick=()=>{if(confirm("¿Reiniciar el PC?"))act("reiniciar",{confirm:true})};
$("cx").onclick=()=>act("cancelar");
$("tts").onclick=()=>{speak=!speak;$("tts").classList.toggle("on",speak)};
$("out").onclick=async()=>{try{await api("../logout")}catch(e){}document.body.innerHTML="<p>Sesión cerrada.</p>"};
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
if(SR){const rec=new SR();rec.lang="es-ES";rec.onresult=e=>{$("q").value=e.results[0][0].transcript;$("ask").click()};
$("mic").onclick=()=>{try{rec.start();log("Escuchando…")}catch(e){}}}else{$("mic").style.display="none"}
</script></html>"""


def init(host_funcs, cfg):
    global PORT
    H.update(host_funcs)
    CFG.update(cfg)
    PORT = int(cfg.get("JARVIS_WEB_PORT", "18765"))
    threading.Thread(target=janitor, daemon=True).start()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "altacode":
        code = f"{secrets.randbelow(10 ** 8):08d}"
        h = "JARVIS_ENROLL_HASH=" + make_hash(code)
        envp = HOME / ".env"
        txt = envp.read_text(encoding="utf-8") if envp.exists() else ""
        if "JARVIS_ENROLL_HASH=" in txt:
            txt = re.sub(r"(?m)^JARVIS_ENROLL_HASH=.*$", lambda m: h, txt)
        else:
            txt = txt.rstrip() + chr(10) + h + chr(10)
        envp.write_text(txt, encoding="utf-8")
        print("CODIGO DE ALTA DE DISPOSITIVOS NUEVOS (8 digitos): " + code)
        print("Guardalo en tu gestor de contrasenas. No se vuelve a mostrar. Reinicia Jarvis para aplicarlo.")
    elif cmd == "devices":
        devs = _read_json(DEV_F, {})
        for hh, v in devs.items():
            print(hh[:10], v.get("label"), v.get("added"))
        print("(ninguno)" if not devs else "")
    elif cmd == "revoke":
        DEV_F.unlink(missing_ok=True)
        print("Todos los dispositivos revocados. Hay que volver a darlos de alta con el codigo.")
    else:
        print("uso: python webpanel.py altacode | devices | revoke")
