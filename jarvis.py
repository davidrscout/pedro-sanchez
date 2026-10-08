# -*- coding: utf-8 -*-
"""JARVIS (PC limpio de David) - control por Telegram. Solo conexiones de SALIDA, sin puertos abiertos.

Diseño: sin Administrador, sin --dangerously-skip-permissions, sin túnel público.
  - Comandos propios (/estado, /captura, /bloquear...) = funciones fijas, no pasan por el modelo.
  - Texto libre = Claude Code en modo SOLO LECTURA.
  - /hacer <tarea> = Claude Code con herramientas, pero SOLO tras pulsar "Sí" en un botón.
Solo obedece al usuario de Telegram JARVIS_ALLOWED_ID; al resto lo ignora (y apunta su id en el log).
"""
import ctypes
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil
import requests

import agenda
import backends
import launchers
import memoria
import remoto
import voz
import sysinfo
import totp
import webpanel

HOME = Path(__file__).resolve().parent
WORK = HOME / "workspace"
WORK.mkdir(exist_ok=True)
LOG = HOME / "jarvis.log"
STATE = HOME / "jarvis_state.json"
SYSTEM_FILE = HOME / "system_prompt.md"
WATCHDOG_HB = Path(r"C:\Personal\watchdog\logs\heartbeat.txt")
NOWIN = 0x08000000  # CREATE_NO_WINDOW


def log(msg):
    try:
        if LOG.exists() and LOG.stat().st_size > 1_000_000:
            LOG.replace(HOME / "jarvis.log.old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def load_env():
    cfg = {}
    p = HOME / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


CFG = load_env()  # a propósito NO se vuelca a os.environ: el cerebro no debe ver el token
TOKEN = CFG.get("JARVIS_BOT_TOKEN", "")
ALLOWED = int(CFG.get("JARVIS_ALLOWED_ID", "0") or 0)
TG_CONTROL = CFG.get("JARVIS_TELEGRAM_CONTROL", "0") == "1"  # Telegram NO es de fiar (cuenta compartida): apagado por defecto
API = f"https://api.telegram.org/bot{TOKEN}/"
CLAUDE = shutil.which("claude") or r"C:\Users\ADMIN\.local\bin\claude.exe"

# ---------------------------------------------------------------- Telegram
def tg(method, data=None, files=None, timeout=15):
    try:
        r = requests.post(API + method, data=data, files=files, timeout=timeout)
        j = r.json()
        if not j.get("ok"):
            log(f"tg {method} error: {j.get('description')}")
            return None
        return j["result"]
    except Exception as e:  # nunca loguear str(e): contiene la URL con el token
        log(f"tg {method} fallo: {type(e).__name__}")
        return None


def send_text(chat, text, markup=None):
    text = text or "(vacío)"
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    for i, c in enumerate(chunks):
        data = {"chat_id": chat, "text": c}
        if markup and i == len(chunks) - 1:
            data["reply_markup"] = json.dumps(markup)
        tg("sendMessage", data=data)


def send_photo(chat, jpg_bytes, caption=""):
    tg("sendPhoto", data={"chat_id": chat, "caption": caption},
       files={"photo": ("captura.jpg", jpg_bytes, "image/jpeg")}, timeout=60)


# ---------------------------------------------------------------- acciones del PC
def lock_pc():
    ctypes.windll.user32.LockWorkStation()


def monitor_off():
    ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)  # WM_SYSCOMMAND, SC_MONITORPOWER, off


def volume(action):
    keys = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}
    vk = keys[action]
    reps = 5 if action in ("up", "down") else 1
    for _ in range(reps):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


APPS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "steam": "steam://open/main",
    "spotify": "spotify:",
    "discord": "discord:",
}


def open_app(name):
    target = APPS.get(name.lower())
    if not target:
        return "No conozco esa app. Disponibles: " + ", ".join(APPS)
    os.startfile(target)
    return f"Abriendo {name}."


def screenshot_jpg():
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True).convert("RGB")
    if img.width > 2560:
        img.thumbnail((2560, 2560))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def ps(script, timeout=60):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                       timeout=timeout, creationflags=NOWIN)
    return r.stdout.decode("cp850", errors="replace").strip()


def gpu_line():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,utilization.gpu,memory.used,memory.total,pstate",
             "--format=csv,noheader,nounits"], capture_output=True, timeout=10, creationflags=NOWIN)
        t, p, u, mu, mt, ps_ = [x.strip() for x in r.stdout.decode(errors="replace").split(",")]
        return f"GPU {t} °C, {float(p):.0f} W, {u} % uso, VRAM {mu}/{mt} MB, {ps_}"
    except Exception:
        return "GPU: nvidia-smi no responde (¡ojo, posible GPU caída!)"


def estado():
    up = datetime.timedelta(seconds=int(time.time() - psutil.boot_time()))
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    hb = ""
    if WATCHDOG_HB.exists():
        age = int(time.time() - WATCHDOG_HB.stat().st_mtime)
        hb = f"\nWatchdog: {'activo' if age < 120 else 'PARADO'} (último latido hace {age} s)"
    return (f"CPU {psutil.cpu_percent(interval=0.5):.0f} % | RAM libre {vm.available // 2**20} MB de {vm.total // 2**20}\n"
            f"{gpu_line()}\nDisco C: libre {disk.free // 2**30} GB\nEncendido desde hace {up}{hb}")


def eventos():
    out = ps(r"""
$s=(Get-Date).AddHours(-24)
Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$s} -EA SilentlyContinue |
 Where-Object { $_.Id -in 41,6008,1001 -or ($_.ProviderName -match 'WHEA|nvlddmkm' -and $_.Level -le 3) } |
 Sort-Object TimeCreated | Select-Object -Last 15 |
 ForEach-Object { '{0:dd/MM HH:mm} id{1} {2}' -f $_.TimeCreated,$_.Id,$_.ProviderName }
""")
    return "Eventos graves últimas 24 h:\n" + out if out else "Sin eventos graves en las últimas 24 h (Kernel-Power 41, BSOD, WHEA, nvlddmkm)."


def reinicio_inesperado():
    start = datetime.datetime.fromtimestamp(psutil.boot_time()) - datetime.timedelta(seconds=60)
    n = ps(f"(Get-WinEvent -FilterHashtable @{{LogName='System';Id=41,6008;StartTime=[datetime]'{start:%Y-%m-%d %H:%M:%S}'}}"
           " -EA SilentlyContinue | Measure-Object).Count")
    return n.isdigit() and int(n) > 0


# ---------------------------------------------------------------- cerebro (Claude Code)
BRAIN_LOCK = threading.Lock()
BRAIN = {"proc": None, "parado": False}
ASK_TOOLS = "Read,Glob,Grep,WebSearch,WebFetch,mcp__pedro"
ASK_DENY = "Bash,PowerShell,Edit,Write,NotebookEdit,Read(//c/Dev/Jarvis/.env)"
DO_TOOLS = "Read,Glob,Grep,Edit,Write,Bash,PowerShell,WebSearch,WebFetch,mcp__pedro"
DO_DENY = ("Read(//c/Dev/Jarvis/.env),Edit(//c/Dev/Jarvis/.env),Bash(rm -rf:*),Bash(del /s:*),Bash(format:*),Bash(shutdown:*),Bash(reg delete:*),Bash(diskpart:*),"
           "PowerShell(Remove-Item -Recurse:*),PowerShell(Stop-Computer:*),PowerShell(Restart-Computer:*)")
PROMPT_SESION = HOME / "_prompt_sesion.md"
TELEMETRIA = HOME / "telemetria.jsonl"
PYW = Path(sys.executable).with_name("pythonw.exe")
HERRAMIENTAS = """
## Tus herramientas propias (servidor «pedro»)
- Para saber cómo está el PC usa estado_pc, eventos_graves, procesos, ventanas_abiertas, red, vigilante: NO lo supongas.
- ver_pantalla te enseña la pantalla: úsala cuando David pregunte qué hay abierto o en pantalla, o para comprobar algo visual.
- Memoria: cuando David te cuente algo DURADERO (preferencias, datos de proyectos, decisiones, gente) guárdalo con recordar,
  sin pedir permiso y sin anunciarlo con pompa. Si un hecho guardado queda obsoleto: olvidar + recordar el nuevo.
- Agenda: «recuérdame…», «avísame a las…», «cada mañana dime…» -> programar (aviso o tarea). agenda_listar / agenda_borrar.
- avisar_telegram solo si David lo pide o al terminar algo largo que te encargó.
- En modo actuar tienes además clic, rueda, escribir_texto, atajo, ventana, lanzar y cerrar_proceso: mira la pantalla
  antes y después de cada acción; si algo es destructivo o ambiguo, pregunta antes.
"""


def mcp_config(mode):
    """Config MCP con SOLO el servidor de Pedro (--strict-mcp-config: ningún otro MCP del usuario entra aquí)."""
    f = HOME / f"_mcp_{mode}.json"
    exe = str(PYW if PYW.exists() else Path(sys.executable))
    cfg = {"mcpServers": {"pedro": {"command": exe, "args": [str(HOME / "pedro_mcp.py")], "env": {"PEDRO_MODO": mode}}}}
    txt = json.dumps(cfg, indent=1)
    if not f.exists() or f.read_text(encoding="utf-8") != txt:
        f.write_text(txt, encoding="utf-8")
    return f


def prompt_sesion():
    """Prompt de sistema de cada llamada: el fijo + herramientas + fecha/hora + memoria a largo plazo."""
    base = SYSTEM_FILE.read_text(encoding="utf-8") if SYSTEM_FILE.exists() else ""
    ahora = datetime.datetime.now()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    partes = [base, HERRAMIENTAS, f"Ahora es {dias[ahora.weekday()]} {ahora:%d/%m/%Y %H:%M} (hora del PC).", memoria.bloque_prompt()]
    PROMPT_SESION.write_text("\n\n".join(p for p in partes if p), encoding="utf-8")
    return PROMPT_SESION


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"session": str(uuid.uuid4()), "started": False}


def save_state(s):
    STATE.write_text(json.dumps(s), encoding="utf-8")


def nueva_conversacion():
    save_state({"session": str(uuid.uuid4()), "started": False})
    return "Conversación nueva: Pedro empieza de cero (lo que recuerda a largo plazo se conserva)."


def parar_cerebro():
    p = BRAIN.get("proc")
    if not p or p.poll() is not None:
        return "Pedro no estaba haciendo nada."
    BRAIN["parado"] = True
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=NOWIN)
    log("cerebro parado a mano")
    return "Parado."


def _telemetria(mode, j, segs):
    try:
        u = j.get("usage") or {}
        reg = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "modo": mode, "s": round(segs, 1),
               "turnos": j.get("num_turns"), "error": bool(j.get("is_error")),
               "tok_in": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0),
               "tok_out": u.get("output_tokens")}
        with open(TELEMETRIA, "a", encoding="utf-8") as f:
            f.write(json.dumps(reg) + "\n")
    except Exception:
        pass


def stats(dias=7):
    """Resumen de uso del cerebro (telemetria.jsonl) + tamaño de memoria y agenda."""
    ahora = datetime.datetime.now()
    lim, hoy = (ahora - datetime.timedelta(days=dias)).strftime("%Y-%m-%d"), ahora.strftime("%Y-%m-%d")
    regs = []
    try:
        for line in TELEMETRIA.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["t"] >= lim:
                regs.append(r)
    except Exception:
        pass

    def suma(rs):
        return {"llamadas": len(rs),
                "segundos_medio": round(sum(r["s"] for r in rs) / len(rs), 1) if rs else 0,
                "errores": sum(1 for r in rs if r.get("error"))}
    return {"hoy": suma([r for r in regs if r["t"].startswith(hoy)]), "semana": suma(regs),
            "memoria": len(memoria.listar()), "agenda": len(agenda.listar())}


def _matar_arbol(p):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=NOWIN)


# Coste CERO (decisión de David 04/10): Claude Code va SIEMPRE con la suscripción de claude.ai. Si alguna vez aparece una
# clave de API o un proveedor de pago en el entorno, se quita antes de lanzar el cerebro para que nunca facture por uso.
PAGO_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY")


def env_sin_pago():
    return {k: v for k, v in os.environ.items() if k.upper() not in PAGO_ENV}


def run_claude(prompt, mode, efimera=False):
    """efimera=True: conversación aparte que no toca la de David (tareas programadas)."""
    st = {"session": str(uuid.uuid4()), "started": False} if efimera else load_state()
    for attempt in (1, 2):
        flag = ["--resume", st["session"]] if st["started"] else ["--session-id", st["session"]]
        args = [CLAUDE, "-p", "--output-format", "json", "--append-system-prompt-file", str(prompt_sesion()),
                "--mcp-config", str(mcp_config(mode)), "--strict-mcp-config"] + flag
        if CFG.get("JARVIS_MODELO"):          # p. ej. sonnet / opus / haiku; vacío = el de por defecto de Claude Code
            args += ["--model", CFG["JARVIS_MODELO"]]
        if mode == "ask":
            args += ["--allowedTools", ASK_TOOLS, "--disallowedTools", ASK_DENY]
        else:
            # /hacer: SIN preguntar permisos (decisión de David 03/10). Se mantienen solo las negativas explícitas
            # de DO_DENY (proteger .env y órdenes que destruyen el sistema).
            args += ["--dangerously-skip-permissions", "--disallowedTools", DO_DENY]
        t0 = time.time()
        BRAIN["parado"] = False
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=str(WORK), creationflags=NOWIN, env=env_sin_pago())
        BRAIN["proc"] = p
        try:
            raw_out, raw_err = p.communicate(prompt.encode("utf-8"), timeout=900)
        except subprocess.TimeoutExpired:
            _matar_arbol(p)
            p.communicate()
            return "Se me acabó el tiempo (15 min). La tarea se ha cancelado."
        finally:
            BRAIN["proc"] = None
        if BRAIN["parado"]:
            return "Vale, paro."
        out = raw_out.decode("utf-8", errors="replace").strip()
        err = raw_err.decode("utf-8", errors="replace").strip()
        try:
            j = json.loads(out)
        except Exception:
            j = None
        if isinstance(j, dict):
            _telemetria(mode, j, time.time() - t0)
        else:
            j = None
        if p.returncode == 0 and j is not None and not j.get("is_error"):
            if not efimera:
                st["started"] = True
                save_state(st)
            return (j.get("result") or "").strip()
        if attempt == 1 and st["started"]:  # sesión perdida: empezar otra
            st = {"session": str(uuid.uuid4()), "started": False}
            continue
        detalle = (j or {}).get("result") or err or out
        log(f"claude rc={p.returncode} err={str(detalle)[:300]}")
        return f"El cerebro falló (código {p.returncode}). {str(detalle)[:300]}"
    return "El cerebro no respondió."


def brain_sync(prompt, mode, backend="claude"):
    """Un solo cerebro a la vez. mode: 'ask' (solo lectura/plan) o 'do' (SIN pedir permisos).
    backend: claude | agy | local."""
    if mode not in ("ask", "do"):
        mode = "ask"
    if not BRAIN_LOCK.acquire(blocking=False):
        return "Sigo con la tarea anterior, espera a que termine."
    try:
        if backend == "claude":
            return run_claude(prompt, mode) or "(sin respuesta)"
        if backend == "agy":
            return backends.run_agy(prompt, mode)
        if backend == "local":
            return backends.run_local(prompt, mode)
        return "Cerebro desconocido."
    finally:
        BRAIN_LOCK.release()


def ahorro():
    lock_pc()
    time.sleep(1)
    monitor_off()


def power(kind):
    if kind == "apagar":
        subprocess.run(["shutdown", "/s", "/t", "15"], creationflags=NOWIN)
        return "Apagado COMPLETO en 15 s (Cancelar lo anula)."
    if kind == "reiniciar":
        subprocess.run(["shutdown", "/r", "/t", "15"], creationflags=NOWIN)
        return "Reiniciando en 15 s (Cancelar lo anula)."
    subprocess.run(["shutdown", "/a"], creationflags=NOWIN)
    return "Apagado/reinicio cancelado (si había alguno)."


# ---------------------------------------------------------------- enlace web (Telegram solo reparte el enlace)
PENDING_DEL = HOME / "pending_delete.json"


def _pd_load():
    try:
        return json.loads(PENDING_DEL.read_text(encoding="utf-8"))
    except Exception:
        return []


def _pd_save(items):
    PENDING_DEL.write_text(json.dumps(items), encoding="utf-8")


def schedule_delete(chat, msg_id, secs):
    items = _pd_load()
    items.append([chat, msg_id])
    _pd_save(items)

    def go():
        time.sleep(secs)
        tg("deleteMessage", data={"chat_id": chat, "message_id": msg_id})
        _pd_save([i for i in _pd_load() if i != [chat, msg_id]])
    threading.Thread(target=go, daemon=True).start()


def purge_pending_deletes():
    for chat, mid in _pd_load():
        tg("deleteMessage", data={"chat_id": chat, "message_id": mid})
    _pd_save([])


def send_web_link(chat, user_msg_id, code=""):
    if user_msg_id:
        tg("deleteMessage", data={"chat_id": chat, "message_id": user_msg_id})   # borra tu /web (lleva el código)
    secret = CFG.get("JARVIS_TOTP_SECRET", "")
    if not secret:
        send_text(chat, "No hay código de Authenticator configurado en el PC.")
        return
    good, why = totp.verify(secret, code)
    if not good:
        log("/web con código TOTP incorrecto o bloqueado: " + totp.diagnose(secret, code))
        tg_note = tg("sendMessage", data={"chat_id": chat, "text": (why + " Manda solo el código de 6 dígitos de tu Authenticator.")})
        if tg_note:
            schedule_delete(chat, tg_note["message_id"], 30)
        return
    why = webpanel.lock_status()
    if why:
        send_text(chat, why)
        return
    first = tg("sendMessage", data={"chat_id": chat, "text": "⏳ Preparando enlace seguro…"})
    mid = first["message_id"] if first else None
    try:
        url, err = webpanel.new_link()
    except Exception as e:
        log(f"enlace web falló: {type(e).__name__}: {str(e)[:150]}")
        url, err = None, "No pude abrir el túnel de Cloudflare."
    if err:
        if mid:
            tg("editMessageText", data={"chat_id": chat, "message_id": mid, "text": err})
            schedule_delete(chat, mid, 60)
        else:
            send_text(chat, err)
        return
    texto = "🔐 Enlace de un solo uso (60 s):\n" + url
    body = {"chat_id": chat, "message_id": mid, "text": texto,
            "link_preview_options": json.dumps({"is_disabled": True})}
    if mid and tg("editMessageText", data=body):
        schedule_delete(chat, mid, 60)
    else:
        sent = tg("sendMessage", data={"chat_id": chat, "text": texto,
                                       "link_preview_options": json.dumps({"is_disabled": True}),
                                       "protect_content": True})
        if sent:
            schedule_delete(chat, sent["message_id"], 60)


def brain_async(chat, prompt, mode):
    def work():
        if not BRAIN_LOCK.acquire(blocking=False):
            send_text(chat, "Sigo con la tarea anterior, espera a que termine.")
            return
        try:
            send_text(chat, "Pensando..." if mode == "ask" else "Ejecutando...")
            send_text(chat, run_claude(prompt, mode) or "(sin respuesta)")
        except Exception as e:
            log(f"brain error {type(e).__name__}")
            send_text(chat, "Error interno en el cerebro.")
        finally:
            BRAIN_LOCK.release()
    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------- agenda + bandeja + vigilante proactivo (un hilo)
ALERTAS = {}            # tipo -> última vez que se avisó
ALERTA_CADA = 3 * 3600  # no repetir la misma alerta en 3 h
ARRANQUE = time.time()  # 07/10/2026: al encender, el latido del watchdog es el de antes de apagar -> falso aviso
GPU_FALLOS = [0]        # 07/10/2026: un tirón (p. ej. el PC sin memoria) no es una GPU caída: 2 fallos seguidos


def _alerta(tipo, texto):
    now = time.time()
    if now - ALERTAS.get(tipo, 0) < ALERTA_CADA:
        return
    ALERTAS[tipo] = now
    log(f"alerta {tipo}: {texto}")
    send_text(ALLOWED, "⚠️ " + texto)


def _gpu_temp():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, timeout=10, creationflags=NOWIN)
        return float(r.stdout.decode(errors="replace").split()[0])
    except Exception:
        return None


def vigilar():
    """Comprobaciones baratas cada minuto. Umbrales en .env: JARVIS_ALERTA_GPU_C (85), JARVIS_ALERTA_DISCO_GB (10)."""
    lim_gpu = float(CFG.get("JARVIS_ALERTA_GPU_C", "85"))
    lim_disco = float(CFG.get("JARVIS_ALERTA_DISCO_GB", "10"))
    t = _gpu_temp()
    GPU_FALLOS[0] = GPU_FALLOS[0] + 1 if t is None else 0
    if t is None:
        if shutil.which("nvidia-smi") and GPU_FALLOS[0] >= 2:
            _alerta("gpu_caida", "nvidia-smi no responde: posible GPU/driver caído. Mira /eventos en el panel.")
    elif t >= lim_gpu:
        _alerta("gpu_temp", f"GPU a {t:.0f} °C (umbral {lim_gpu:.0f} °C).")
    libre = psutil.disk_usage("C:\\").free / 2 ** 30
    if libre < lim_disco:
        _alerta("disco", f"Disco C: casi lleno: quedan {libre:.1f} GB.")
    if (time.time() - ARRANQUE > 600 and WATCHDOG_HB.exists()
            and time.time() - WATCHDOG_HB.stat().st_mtime > 600):
        _alerta("watchdog", "El watchdog de cuelgues lleva más de 10 min sin latir.")


def _disparar_tarea(it):
    def go():
        if not BRAIN_LOCK.acquire(timeout=900):
            send_text(ALLOWED, f"⏰ No pude hacer la tarea programada (Pedro seguía ocupado): {it['texto'][:200]}")
            return
        try:
            pr = ("[Tarea programada por David; contesta para leer en el móvil, breve y al grano. Usa tus herramientas "
                  "para comprobar datos reales.]\n" + it["texto"])
            res = run_claude(pr, "ask", efimera=True)
            send_text(ALLOWED, f"⏰ {it['texto'][:80]}\n\n{res}")
        except Exception as e:
            log(f"tarea programada error {type(e).__name__}")
        finally:
            BRAIN_LOCK.release()
    threading.Thread(target=go, daemon=True).start()


def servicio():
    n = 0
    while True:
        try:
            for it in agenda.vencidos():
                tarde = f" (con {it['retraso_min']} min de retraso; el PC estaba ocupado o apagado)" if it.get("retraso_min", 0) > 3 else ""
                if it["tipo"] == "tarea":
                    _disparar_tarea(it)
                else:
                    send_text(ALLOWED, f"⏰ Recordatorio{tarde}: {it['texto']}")
            for txt in agenda.sacar_bandeja():
                send_text(ALLOWED, "Pedro: " + txt)
            if n % 3 == 0 and CFG.get("JARVIS_ALERTAS", "1") == "1":
                vigilar()
        except Exception as e:
            log(f"servicio error {type(e).__name__}: {str(e)[:150]}")
        n += 1
        time.sleep(20)


# ---------------------------------------------------------------- confirmaciones
PENDING = {}  # id -> (timestamp, kind, payload)


def ask_confirm(chat, kind, payload, question):
    now = time.time()
    for k in [k for k, v in PENDING.items() if now - v[0] > 300]:
        PENDING.pop(k, None)
    pid = uuid.uuid4().hex[:8]
    PENDING[pid] = (now, kind, payload)
    send_text(chat, question, {"inline_keyboard": [[
        {"text": "✅ Sí", "callback_data": f"ok:{pid}"}, {"text": "❌ No", "callback_data": f"no:{pid}"}]]})


def handle_callback(cb):
    uid = (cb.get("from") or {}).get("id")
    chat = ((cb.get("message") or {}).get("chat") or {}).get("id")
    if uid != ALLOWED:
        log(f"callback de usuario NO autorizado id={uid}")
        return
    tg("answerCallbackQuery", data={"callback_query_id": cb.get("id")})
    if not TG_CONTROL:
        return
    verdict, _, pid = (cb.get("data") or "").partition(":")
    item = PENDING.pop(pid, None)
    if not item or time.time() - item[0] > 300:
        send_text(chat, "Esa confirmación ya caducó. Vuelve a pedirlo.")
        return
    if verdict != "ok":
        send_text(chat, "Cancelado.")
        return
    _, kind, payload = item
    if kind == "hacer":
        brain_async(chat, payload, "do")
    elif kind == "apagar":
        subprocess.run(["shutdown", "/s", "/t", "15"], creationflags=NOWIN)
        send_text(chat, "Apagado COMPLETO en 15 s. (/cancelar para anularlo)")
    elif kind == "reiniciar":
        subprocess.run(["shutdown", "/r", "/t", "15"], creationflags=NOWIN)
        send_text(chat, "Reiniciando en 15 s. (/cancelar para anularlo)")


AYUDA = """PEDRO SÁNCHEZ - PC limpio
/estado - CPU, RAM, GPU, disco, watchdog
/eventos - cuelgues/BSOD/errores de GPU de las últimas 24 h
/captura - foto de la pantalla
/bloquear - bloquea la sesión
/pantalla - apaga el monitor
/ahorro - bloquea + apaga monitor (el PC sigue encendido y escuchando)
/vol up|down|mute
/abrir chrome|steam|spotify|discord
/hacer <tarea> - Claude Code con herramientas (pide confirmación)
/parar - corta lo que esté haciendo Pedro · /nueva - conversación desde cero
/memoria · /olvidar <id> · /agenda · /stats
/apagar - apagado completo (confirmación) · /reiniciar · /cancelar
Texto libre: pregunta en modo solo lectura."""


def handle_update(u):
    if "callback_query" in u:
        return handle_callback(u["callback_query"])
    m = u.get("message") or {}
    uid = (m.get("from") or {}).get("id")
    chat = (m.get("chat") or {}).get("id")
    if uid != ALLOWED:
        log(f"mensaje de usuario NO autorizado id={uid}")
        return
    text = (m.get("text") or "").strip()
    if (text.split() or [""])[0].lower().split("@")[0] in ("/encender", "/on", "/wake"):   # con el PC apagado lo atiende el router (router/wol_tg.sh)
        send_text(chat, "✅ El PC ya está encendido.")
        return
    if (text.split() or [""])[0].lower().split("@")[0] == "/web":
        parts = text.split(maxsplit=1)
        code = parts[1] if len(parts) > 1 else ""
        threading.Thread(target=send_web_link, args=(chat, m.get("message_id"), code), daemon=True).start()
        return
    if re.fullmatch(r"\d{3}\s?\d{3}", text):   # solo el código de 6 dígitos = petición del enlace (sin "/web")
        threading.Thread(target=send_web_link, args=(chat, m.get("message_id"), text.replace(" ", "")), daemon=True).start()
        return
    if not TG_CONTROL:
        send_text(chat, "Control por Telegram desactivado. Manda el código de tu Authenticator (6 dígitos).")
        return
    if not text:
        send_text(chat, "De momento solo entiendo texto.")
        return
    cmd, _, arg = text.partition(" ")
    cmd, arg = cmd.lower().split("@")[0], arg.strip()
    try:
        if cmd in ("/start", "/ayuda", "/help"):
            send_text(chat, AYUDA)
        elif cmd == "/estado":
            send_text(chat, estado())
        elif cmd == "/eventos":
            send_text(chat, eventos())
        elif cmd == "/captura":
            send_photo(chat, screenshot_jpg(), "Pantalla ahora (si está bloqueada saldrá negra)")
        elif cmd == "/bloquear":
            lock_pc()
            send_text(chat, "Sesión bloqueada.")
        elif cmd == "/pantalla":
            monitor_off()
            send_text(chat, "Monitor apagado.")
        elif cmd == "/ahorro":
            lock_pc()
            time.sleep(1)
            monitor_off()
            send_text(chat, "Modo ahorro: sesión bloqueada y monitor apagado. El PC sigue encendido y escuchando.")
        elif cmd == "/vol" and arg in ("up", "down", "mute"):
            volume(arg)
            send_text(chat, f"Volumen: {arg}.")
        elif cmd == "/abrir" and arg:
            send_text(chat, open_app(arg))
        elif cmd == "/hacer" and arg:
            ask_confirm(chat, "hacer", arg, f"¿Ejecuto esto con herramientas (puede editar archivos y lanzar comandos)?\n\n{arg}")
        elif cmd == "/apagar":
            ask_confirm(chat, "apagar", None, "¿Apago el PC por completo? Después no podré despertarlo desde aquí.")
        elif cmd == "/reiniciar":
            ask_confirm(chat, "reiniciar", None, "¿Reinicio el PC?")
        elif cmd == "/parar":
            send_text(chat, parar_cerebro())
        elif cmd == "/nueva":
            send_text(chat, nueva_conversacion())
        elif cmd == "/memoria":
            its = memoria.listar()
            send_text(chat, "\n".join(f"{i['id']}: {i['texto']}" for i in its) or "No recuerdo nada todavía.")
        elif cmd == "/olvidar" and arg:
            send_text(chat, memoria.olvidar(arg))
        elif cmd == "/agenda":
            its = agenda.listar()
            send_text(chat, "\n".join(f"{i['id']}: {i['cuando']} [{i['tipo']}, {i['repetir']}] {i['texto']}" for i in its) or "Agenda vacía.")
        elif cmd == "/stats":
            send_text(chat, json.dumps(stats(), ensure_ascii=False, indent=1))
        elif cmd == "/cancelar":
            subprocess.run(["shutdown", "/a"], creationflags=NOWIN)
            send_text(chat, "Apagado/reinicio cancelado (si había alguno en marcha).")
        elif cmd.startswith("/"):
            send_text(chat, "Comando no reconocido. /ayuda")
        else:
            brain_async(chat, text, "ask")
    except Exception as e:
        log(f"error en {cmd}: {type(e).__name__}: {str(e)[:200]}")
        send_text(chat, f"Falló {cmd}: {type(e).__name__}")


def main():
    if not TOKEN or not ALLOWED:
        log("Falta JARVIS_BOT_TOKEN o JARVIS_ALLOWED_ID en .env")
        print("Falta JARVIS_BOT_TOKEN o JARVIS_ALLOWED_ID en .env")
        return 1
    me = tg("getMe")
    espera = 5
    for _ in range(40):   # tras un reinicio la red tarda en subir: reintenta ~35 min antes de rendirse
        if me:
            break
        log("getMe falló: sin red o token inválido, reintento")
        time.sleep(espera)
        espera = min(espera * 2, 60)
        me = tg("getMe")
    if not me:
        log("getMe falló: token inválido o sin red")
        print("getMe falló: token inválido o sin red")
        return 1
    log(f"Jarvis arrancado como @{me.get('username')}")
    purge_pending_deletes()
    backends.init(CFG, WORK, log)
    webpanel.init({"log": log, "alert": lambda m: send_text(ALLOWED, m), "estado": estado, "eventos": eventos,
                   "captura": screenshot_jpg, "bloquear": lock_pc, "pantalla": monitor_off, "ahorro": ahorro,
                   "vol": volume, "abrir": open_app, "power": power, "brain": brain_sync,
                   "backends": backends.estado, "procesos": sysinfo.procesos, "matar": sysinfo.matar,
                   "watchdog": sysinfo.watchdog, "serie": sysinfo.serie, "red": sysinfo.red, "launchers": launchers.lista_publica,
                   "lanzar": launchers.ejecutar,
                   "tts": lambda t, v: voz.sintetizar(t, v), "vivo": remoto.captura, "raton": remoto.raton, "escribir": remoto.escribir, "combo": remoto.combo,
                   "ventanas": remoto.ventanas, "ventana": remoto.ventana,
                   "stt": lambda b: __import__("stt").transcribir(b), "parar": parar_cerebro, "nueva": nueva_conversacion, "stats": stats,
                   "memoria": memoria.listar, "olvidar": memoria.olvidar, "recordar": memoria.recordar,
                   "agenda": agenda.listar, "agenda_borrar": agenda.borrar, "agenda_crear": agenda.crear}, CFG)
    threading.Thread(target=servicio, daemon=True).start()
    old = tg("getUpdates", data={"offset": -1, "timeout": 0}) or []   # descarta órdenes viejas
    offset = old[-1]["update_id"] + 1 if old else 0
    try:
        aviso = "Pedro Sánchez en línea."
        if reinicio_inesperado():
            aviso = "⚠️ Pedro Sánchez en línea. El PC se REINICIÓ DE FORMA INESPERADA (Kernel-Power 41 / apagado incorrecto). /eventos"
        send_text(ALLOWED, aviso)
    except Exception:
        pass
    backoff = 1
    while True:
        res = tg("getUpdates", data={"offset": offset, "timeout": 30}, timeout=45)
        if res is None:
            time.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)
            continue
        backoff = 1
        for u in res:
            offset = u["update_id"] + 1
            try:
                handle_update(u)
            except Exception as e:
                log(f"update error {type(e).__name__}")


def selftest():
    sent = []
    globals()["send_text"] = lambda c, t, m=None: sent.append(("txt", c, t))
    globals()["send_photo"] = lambda c, b, cap="": sent.append(("foto", c, len(b)))
    print("estado:\n" + estado())
    print("\neventos:\n" + eventos())
    print("\ncaptura bytes:", len(screenshot_jpg()))
    print("reinicio_inesperado:", reinicio_inesperado())
    globals()["ALLOWED"] = 111
    globals()["TG_CONTROL"] = True
    handle_update({"message": {"from": {"id": 999}, "chat": {"id": 999}, "text": "/estado"}})
    assert not sent, "¡un usuario no autorizado obtuvo respuesta!"
    handle_update({"message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/estado"}})
    handle_update({"message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/hacer crear un archivo"}})
    handle_update({"message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/loquesea"}})
    print("\nrespuestas simuladas:", [(k, str(v)[:40]) for k, _, v in sent])
    print("PENDING tras /hacer:", len(PENDING), "(debe ser 1)")
    print("SELFTEST OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main() or 0)
