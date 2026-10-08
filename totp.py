# -*- coding: utf-8 -*-
"""TOTP (RFC 6238, SHA-1, 6 dígitos, 30 s) compatible con Microsoft Authenticator. Con anti-reutilización y límite de intentos."""
import base64
import hashlib
import hmac
import json
import os
import struct
import time
from pathlib import Path
from urllib.parse import quote

HOME = Path(__file__).resolve().parent
STATE = HOME / "totp_state.json"
STEP, DIGITS, WINDOW = 30, 6, 1
MAX_FAILS, FAIL_WINDOW, LOCK_S = 5, 600, 3600     # 5 fallos en 10 min -> pausa de 1 h


def new_secret():
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def code_at(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    d = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = d[-1] & 0x0F
    return str((struct.unpack(">I", d[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS).zfill(DIGITS)


def otpauth_uri(secret, account="PC limpio", issuer="Pedro Sanchez"):
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"last": 0, "fails": [], "lock_until": 0}


def verify(secret, code, now=None):
    """(ok, motivo). Un código solo sirve UNA vez (aunque siga en ventana) y 5 fallos seguidos bloquean 1 h."""
    now = time.time() if now is None else now
    st = _load()
    if now < st.get("lock_until", 0):
        return False, f"Bloqueado {int((st['lock_until'] - now) // 60) + 1} min por códigos erróneos."
    code = "".join(c for c in str(code) if c.isdigit())
    if len(code) == DIGITS and secret:
        cur = int(now // STEP)
        for c in range(cur - WINDOW, cur + WINDOW + 1):
            if c > st.get("last", 0) and hmac.compare_digest(code_at(secret, c), code):
                st["last"], st["fails"] = c, []
                STATE.write_text(json.dumps(st), encoding="utf-8")
                return True, ""
    st["fails"] = [t for t in st.get("fails", []) if now - t < FAIL_WINDOW] + [now]
    if len(st["fails"]) >= MAX_FAILS:
        st["lock_until"], st["fails"] = now + LOCK_S, []
    STATE.write_text(json.dumps(st), encoding="utf-8")
    return False, "Código incorrecto."


def diagnose(secret, code, now=None, span=200):
    """Solo para depurar: dice si el código encaja con otro paso de tiempo (desfase) o con ninguno. No lo consume."""
    now = time.time() if now is None else now
    code = "".join(c for c in str(code) if c.isdigit())
    if len(code) != DIGITS:
        return f"el texto recibido tiene {len(code)} dígitos (hacen falta {DIGITS})"
    cur = int(now // STEP)
    for k in range(-span, span + 1):
        if hmac.compare_digest(code_at(secret, cur + k), code):
            return f"coincide con desfase de {k} pasos ({k * STEP} s): reloj del móvil o del PC desajustado" if k else "coincide con el paso actual"
    return "no coincide con ningún paso de +-100 min: secreto distinto (otro QR/cuenta) o código mal tecleado"
