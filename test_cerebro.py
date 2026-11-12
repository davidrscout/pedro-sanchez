# -*- coding: utf-8 -*-
"""Pruebas del cerebro Claude (predeterminado) sin procesos reales: coste cero, permisos, sesiones y elección manual."""
import json
import os
import tempfile
from pathlib import Path

import jarvis as j

tmp = Path(tempfile.mkdtemp())
j.HOME = tmp
j.WORK = tmp / "workspace"
j.WORK.mkdir()
j.STATE = tmp / "state.json"
j.STATE_KIMI = tmp / "state_kimi.json"
j.TELEMETRIA = tmp / "telemetria.jsonl"
j.LOG = tmp / "jarvis.log"
j.SYSTEM_FILE = tmp / "system.md"
j.SYSTEM_FILE.write_text("Eres Pedro Sánchez.", encoding="utf-8")
j.PROMPT_SESION = tmp / "_prompt.md"
j.CFG = {}
j.memoria.bloque_prompt = lambda: ""
calls, fallos = [], []
os.environ["ANTHROPIC_API_KEY"] = "sk-de-pago-NO"
os.environ["ANTHROPIC_BASE_URL"] = "https://proveedor-de-pago"


class Proceso:
    def __init__(self, args, **kw):
        self.args, self.kw, self.pid = args, kw, 2000 + len(calls)
        self.returncode = 1 if fallos and fallos.pop(0) else 0
        calls.append(self)

    def communicate(self, data=None, timeout=None):
        self.stdin = data
        if self.returncode:
            return b"", b"No conversation found"
        return json.dumps({"result": "hola David", "is_error": False, "num_turns": 2,
                           "usage": {"input_tokens": 5, "output_tokens": 7}}).encode(), b""

    def poll(self):
        return self.returncode


j.subprocess.Popen = lambda args, **kw: Proceso(args, **kw)


def ok(c, msg):
    print(("OK  " if c else "FALLO ") + msg)
    assert c, msg


a = lambda n=-1: calls[n].args
ok(j.brain_sync("hola", "ask") == "hola David", "el cerebro por defecto es Claude")
ok(a()[0] == j.CLAUDE and "-p" in a(), "lanza el CLI de Claude en modo -p")
env = calls[-1].kw["env"]
ok("ANTHROPIC_API_KEY" not in env and "ANTHROPIC_BASE_URL" not in env, "coste cero: sin claves ni proveedores de pago en el entorno")
ok("--strict-mcp-config" in a() and "--mcp-config" in a(), "solo el MCP de Pedro")
ok(json.loads(Path(a()[a().index("--mcp-config") + 1]).read_text())["mcpServers"]["pedro"]["env"]["PEDRO_MODO"] == "ask", "MCP en modo leer")
ok("--allowedTools" in a() and "--dangerously-skip-permissions" not in a(), "modo leer: herramientas acotadas, sin saltar permisos")
ok("Bash" in a()[a().index("--disallowedTools") + 1], "modo leer: Bash prohibido")
ok("--session-id" in a(), "primera vez: sesión nueva")
ok(calls[-1].stdin == "hola".encode(), "el mensaje va por stdin")
ok(j.load_state()["started"] and j.load_state()["engine"] == "claude", "guarda la conversación de Claude")
j.brain_sync("sigue", "do")
ok("--resume" in a() and "--dangerously-skip-permissions" in a(), "modo actuar: continúa la conversación y sin pedir permisos")
ok(".env" in a()[a().index("--disallowedTools") + 1], "modo actuar: .env sigue protegido")
fallos.append(True)
ok(j.brain_sync("recupera", "ask") == "hola David" and "--session-id" in a(), "sesión perdida: empieza otra")
ses = j.load_state()["session"]
ok(j.run_claude("tarea", "ask", efimera=True) == "hola David" and j.load_state()["session"] == ses, "tarea programada efímera no toca la conversación")
j.STATE.write_text(json.dumps({"session": "x", "started": True, "engine": "kimi", "kimi_session": "s"}), encoding="utf-8")
j.brain_sync("migra", "ask")
ok("--session-id" in a() and j.load_state()["engine"] == "claude", "un estado viejo de Kimi no se reutiliza con Claude")
j.CFG = {"JARVIS_MODELO": "sonnet"}
j.brain_sync("m", "ask")
ok(a()[a().index("--model") + 1] == "sonnet", "JARVIS_MODELO se respeta")
j.brain_sync("m", "ask", "claude", "haiku")
ok(a()[a().index("--model") + 1] == "haiku" and a().count("--model") == 1, "llamada de voz: modelo=haiku manda sobre JARVIS_MODELO (un solo --model)")
j.brain_sync("m", "ask", "claude")
ok(a()[a().index("--model") + 1] == "sonnet", "sin modelo de voz sigue valiendo JARVIS_MODELO (comportamiento de siempre)")
j.brain_sync("m", "ask", "claude", "haiku; calc")
ok(a()[a().index("--model") + 1] == "sonnet", "un nombre de modelo raro no se pasa al CLI")
j.CFG = {}
j.brain_sync("m", "ask", "claude")
ok("--model" not in a(), "sin JARVIS_MODELO ni modelo de voz: no hay --model")
j.brain_sync("m", "ask", "claude", "sonnet")
ok(a()[a().index("--model") + 1] == "sonnet" and "ANTHROPIC_API_KEY" not in calls[-1].kw["env"], "con modelo de voz sigue sin claves de pago (coste cero)")
n = len(calls)
ok(j.brain_sync("x", "ask", "inventado") == "Cerebro desconocido." and len(calls) == n, "cerebro desconocido: no cae a otro (nada automático)")
tel = [json.loads(l) for l in j.TELEMETRIA.read_text(encoding="utf-8").splitlines()]
ok(tel[0]["cerebro"] == "claude" and tel[0]["tok_out"] == 7, "telemetría de Claude con tokens")
ok("kimi" in [b["id"] for b in j.backends.estado()] and j.backends.estado()[0]["id"] == "claude", "Kimi queda como opción; Claude el primero")
print("TODAS LAS PRUEBAS DE CLAUDE OK")