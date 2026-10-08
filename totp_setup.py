# -*- coding: utf-8 -*-
"""Crea (o renueva) el secreto TOTP, lo guarda en .env y deja un QR en el Escritorio para Microsoft Authenticator."""
import os
import re
from pathlib import Path

import qrcode

import totp

HOME = Path(__file__).resolve().parent
secret = totp.new_secret()
env = HOME / ".env"
txt = env.read_text(encoding="utf-8") if env.exists() else ""
line = "JARVIS_TOTP_SECRET=" + secret
txt = re.sub(r"(?m)^JARVIS_TOTP_SECRET=.*$", lambda m: line, txt) if "JARVIS_TOTP_SECRET=" in txt else txt.rstrip() + "\n" + line + "\n"
env.write_text(txt, encoding="utf-8")
(HOME / "totp_state.json").unlink(missing_ok=True)
png = Path(os.path.expanduser("~")) / "Desktop" / "QR_Pedro_Sanchez_BORRAR.png"
qrcode.make(totp.otpauth_uri(secret)).save(png)
print("Hecho. Se creó el QR en el Escritorio:", png)
print()
print("1) Microsoft Authenticator -> + -> Otra cuenta (Google, Facebook, etc.) -> Escanear código QR")
print("2) Escanea ese QR desde la pantalla del PC.")
print("3) BORRA el PNG del Escritorio (es la llave del código).")
print("4) Reinicia Jarvis (o dile a Claude que lo haga).")
