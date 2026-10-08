# -*- coding: utf-8 -*-
"""Cerebros alternativos de Pedro Sánchez: agy (Antigravity), OpenCode+Qwen local y chat directo con la IA local.
Claude Code vive en jarvis.py. Todos los modos: 'ask' = solo lectura/plan; 'do' = SIN pedir permisos (decisión de David)."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

NOWIN = 0x08000000
LLM = Path(r"C:\Personal\llm")
SERVER_EXE = LLM / "bin" / "llama-server.exe"
OPENCODE = LLM / "opencode" / "opencode.exe"
OPENCODE_CFG = LLM / "opencode" / "opencode.json"
DEFAULT_MODEL = LLM / "models" / "Huihui-Qwen3.8-27B-abliterated-UD-IQ4_XS.gguf"
PORT = 8090
AGY = shutil.which("agy") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe")
CLAUDE = shutil.which("claude") or r"C:\Users\ADMIN\.local\bin\claude.exe"

CFG = {}
WORK = Path(".")
log = print
_LLAMA = {"proc": None}
LLAMA_LOCK = threading.Lock()
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def init(cfg, work, logfn):
    global WORK, log
    CFG.update(cfg)
    WORK = Path(work)
    log = logfn


def _limpio(b):
    return ANSI.sub("", b.decode("utf-8", errors="replace")).strip()


# ---------------------------------------------------------------- IA local (llama.cpp)
def local_model():
    p = CFG.get("JARVIS_LOCAL_MODEL", "")
    return Path(p) if p else DEFAULT_MODEL


def llama_up():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_llama():
    """Arranca llama-server si no está. Devuelve True si lo arrancó ESTA llamada (para apagarlo luego)."""
    if llama_up():
        return False
    if not SERVER_EXE.exists() or not local_model().exists():
        raise RuntimeError("Falta llama-server o el modelo local.")
    ctx = CFG.get("JARVIS_LOCAL_CTX", "65536")
    ngl = CFG.get("JARVIS_LOCAL_NGL", "62")
    args = [str(SERVER_EXE), "-m", str(local_model()), "-c", ctx, "-ngl", ngl, "--fit", "off", "-fa", "on",
            "-ctk", "q4_0", "-ctv", "q4_0", "-np", "1", "--jinja", "--cache-ram", "0", "--ctx-checkpoints", "2",
            "--host", "127.0.0.1", "--port", str(PORT), "--alias", "qwen", "--reasoning-budget", "6000",
            "--reasoning-budget-message", "Ya he pensado suficiente, respondo ahora."]
    log("arrancando llama-server (IA local)")
    _LLAMA["proc"] = subprocess.Popen(args, creationflags=NOWIN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < 240:
        if llama_up():
            return True
        if _LLAMA["proc"].poll() is not None:
            raise RuntimeError("llama-server se cerró al arrancar (¿poca VRAM?).")
        time.sleep(2)
    stop_llama()
    raise RuntimeError("llama-server no arrancó en 4 min.")


def stop_llama():
    p = _LLAMA.get("proc")
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
    _LLAMA["proc"] = None
    log("llama-server parado (GPU liberada)")


def _con_llama(fn):
    """Ejecuta fn con el servidor local arriba y lo apaga después si lo arrancamos nosotros (salvo KEEP=1)."""
    with LLAMA_LOCK:
        arranco = ensure_llama()
        try:
            return fn()
        finally:
            if arranco and CFG.get("JARVIS_LOCAL_KEEP", "0") != "1":
                stop_llama()


def run_local(prompt, mode="ask"):
    """Chat directo con el modelo local (sin herramientas)."""
    def go():
        body = json.dumps({"model": "qwen", "max_tokens": 2048,
                           "messages": [{"role": "system", "content": "Eres Pedro Sánchez, asistente de David. Castellano de España, directo y breve."},
                                        {"role": "user", "content": prompt}]}).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            j = json.loads(r.read().decode("utf-8"))
        return (j["choices"][0]["message"].get("content") or "(sin respuesta)").strip()
    try:
        return _con_llama(go)
    except Exception as e:
        return f"IA local: {type(e).__name__}: {str(e)[:200]}"


def run_opencode(prompt, mode="ask"):
    """OpenCode con el modelo local. ask = agente 'plan' (solo lectura); do = --auto (sin pedir permisos)."""
    if not OPENCODE.exists():
        return "OpenCode no está instalado."

    def go():
        args = [str(OPENCODE), "run", "--dir", str(WORK), "-m", "llamacpp/qwen"]
        args += ["--auto"] if mode == "do" else ["--agent", "plan"]
        args.append(prompt)
        env = dict(os.environ, OPENCODE_CONFIG=str(OPENCODE_CFG))
        r = subprocess.run(args, capture_output=True, cwd=str(WORK), timeout=1800, creationflags=NOWIN, env=env,
                           stdin=subprocess.DEVNULL)
        out, err = _limpio(r.stdout), _limpio(r.stderr)
        if r.returncode != 0 and not out:
            log(f"opencode rc={r.returncode} err={err[:300]}")
            return f"OpenCode falló (código {r.returncode}). {err[:200]}"
        return out or "(OpenCode sin respuesta)"
    try:
        return _con_llama(go)
    except subprocess.TimeoutExpired:
        return "OpenCode: se acabó el tiempo (30 min)."
    except Exception as e:
        return f"OpenCode: {type(e).__name__}: {str(e)[:200]}"


# ---------------------------------------------------------------- agy (Antigravity CLI)
def run_agy(prompt, mode="ask"):
    if not Path(AGY).exists():
        return "agy no está instalado."
    # 09/10: en 'ask' (plan) agy sin consola auto-deniega cualquier comando y devolvía stdout vacío
    # («(agy sin respuesta)»). Se pide JSON para saber si fue por eso y avisar claro. Ni --sandbox ni
    # reglas con comodín sirven de modo «solo lectura» en Windows (probado: borra igual), así que
    # leer el PC con agy exige el modo actuar.
    args = [AGY, "-p", prompt] + (["--dangerously-skip-permissions"] if mode == "do"
                                  else ["--mode", "plan", "--output-format", "json"])
    try:
        r = subprocess.run(args, capture_output=True, cwd=str(WORK), timeout=900, creationflags=NOWIN,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "agy: se acabó el tiempo (15 min)."
    out, err = _limpio(r.stdout), _limpio(r.stderr)
    if r.returncode != 0 and not out:
        log(f"agy rc={r.returncode} err={err[:300]}")
        return f"agy falló (código {r.returncode}). ¿Sesión iniciada con 'agy'? {err[:200]}"
    if mode != "do":
        try:
            j = json.loads(out)
        except ValueError:
            return out or "(agy sin respuesta)"
        resp = str(j.get("response") or "").strip()
        if resp:
            return resp
        if j.get("denied_actions"):
            log(f"agy ask sin respuesta: denegado {j.get('denied_actions')}")
            return ("Antigravity en modo «leer» no puede ejecutar nada en el PC sin pedir permiso, y desde aquí "
                    "no puede pedirlo. Para que mire ficheros o el sistema, usa el modo «actuar» o elige Claude.")
        return f"(agy sin respuesta: {j.get('status') or 'desconocido'})"
    return out or "(agy sin respuesta)"


# ---------------------------------------------------------------- catálogo
def estado():
    modelo = local_model()
    local_ok = SERVER_EXE.exists() and modelo.exists()
    return [
        {"id": "claude", "nombre": "Claude Code", "ok": Path(CLAUDE).exists(), "nota": "Lectura / completo"},
        {"id": "agy", "nombre": "Antigravity (agy)", "ok": Path(AGY).exists(), "nota": "Plan / completo"},
        {"id": "local", "nombre": "IA local (chat)", "ok": local_ok, "nota": "Opcional; usa la GPU"},
    ]
