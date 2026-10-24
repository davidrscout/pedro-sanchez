# -*- coding: utf-8 -*-
"""Pruebas del backend Kimi sin procesos, red ni configuración real."""
import json
import tempfile
from pathlib import Path

import jarvis as j

tmp = Path(tempfile.mkdtemp())
j.HOME = tmp
j.WORK = tmp / "workspace"
j.WORK.mkdir()
j.STATE = tmp / "state.json"
j.TELEMETRIA = tmp / "telemetria.jsonl"
j.LOG = tmp / "jarvis.log"
j.SYSTEM_FILE = tmp / "system.md"
j.SYSTEM_FILE.write_text("Eres Pedro Sánchez.", encoding="utf-8")
j.PROMPT_SESION = tmp / "_prompt.md"
j.CFG = {}
j.memoria.bloque_prompt = lambda: ""
calls = []
fallos = []


class Proceso:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pid = 1000 + len(calls)
        self.returncode = 1 if fallos and fallos.pop(0) else 0
        self.numero = len(calls) + 1
        calls.append(self)

    def communicate(self, timeout=None):
        if self.returncode:
            return b"", b"sesion perdida"
        lineas = [
            {"role": "assistant", "content": "intermedio"},
            {"role": "assistant", "content": "respuesta"},
            {"role": "meta", "type": "session.resume_hint", "session_id": f"session_{self.numero}"},
        ]
        return ("\n".join(json.dumps(x) for x in lineas) + "\n").encode("utf-8"), b""

    def poll(self):
        return self.returncode


j.subprocess.Popen = lambda args, **kwargs: Proceso(args, **kwargs)


def ok(c, msg):
    print(("OK  " if c else "FALLO ") + msg)
    assert c, msg


def args_n(n=-1):
    return calls[n].args


# Primera llamada: perfil Leer real, sin --auto ni flags incompatibles de Claude.
ok(j.run_kimi("hola", "ask") == "respuesta", "Kimi devuelve el último texto del JSONL")
a = args_n()
ok(calls[-1].kwargs["env"].get("PEDRO_KIMI_GUARD") == "1", "el backend activa la guarda solo en sus procesos")
ok("--auto" not in a and "--continue" not in a and "--session" not in a, "primera llamada no reanuda ni usa --auto")
ok("--agent-file" in a and "--output-format" in a and "stream-json" in a, "primera llamada usa agente y JSONL")
ok("--mcp-config" not in a and "--strict-mcp-config" not in a and "--allowedTools" not in a, "no quedan argumentos de Claude")
ok(a[a.index("-p") + 1].endswith("## Mensaje de David\nhola"), "el prompt conserva contexto y mensaje")
agente = Path(a[a.index("--agent-file") + 1]).read_text(encoding="utf-8")
ok("  - Bash\n" not in agente and "  - Edit\n" not in agente and "  - Write\n" not in agente, "Leer no ofrece shell ni escritura")
ok("  - mcp__pedro__*\n" in agente and "${base_prompt}" in agente, "agente Leer incluye solo el MCP de Pedro y el prompt base")
mcp = json.loads((j.WORK / ".kimi-code" / "mcp.json").read_text(encoding="utf-8"))
ok(mcp["mcpServers"]["pedro"]["env"]["PEDRO_MODO"] == "ask", "MCP arranca en modo Leer")
ok(j.load_state()["kimi_session"] == "session_1", "guarda el session_id real")

# Mismo modo: reanuda; otro modo: perfil nuevo. Después vuelve a reanudar.
j.run_kimi("siguiente", "ask")
a = args_n()
ok(a[a.index("--session") + 1] == "session_1" and "--agent-file" not in a, "segunda llamada reanuda la misma sesión")
j.run_kimi("cambia", "do")
a = args_n()
ok("--session" not in a and "pedro-do.md" in a[a.index("--agent-file") + 1], "cambiar a Actuar crea su perfil de sesión")
agente_do = Path(a[a.index("--agent-file") + 1]).read_text(encoding="utf-8")
ok("  - Bash\n" in agente_do and "  - Edit\n" in agente_do, "Actuar sí ofrece shell y edición")
mcp = json.loads((j.WORK / ".kimi-code" / "mcp.json").read_text(encoding="utf-8"))
ok(mcp["mcpServers"]["pedro"]["env"]["PEDRO_MODO"] == "do", "MCP cambia a modo Actuar")
j.run_kimi("otra", "do")
ok(args_n()[args_n().index("--session") + 1] == "session_3", "Actuar también reanuda")

# Tarea efímera: carpeta aislada y estado principal intacto.
antes = j.STATE.read_text(encoding="utf-8")
j.run_kimi("tarea", "ask", efimera=True)
ok("_efimera" in calls[-1].kwargs["cwd"] and "--session" not in args_n(), "tarea efímera usa carpeta y sesión aisladas")
ok(j.STATE.read_text(encoding="utf-8") == antes, "tarea efímera no toca la conversación principal")

# Una sesión que ya no existe se reintenta una vez desde cero.
fallos.append(True)
ok(j.run_kimi("recupera", "do") == "respuesta", "recupera una sesión perdida")
ok("--session" in args_n(-2) and "--agent-file" in args_n(-1), "el fallo de reanudación reintenta con sesión nueva")
ok(j.load_state()["kimi_session"] == f"session_{len(calls)}", "guarda la sesión recuperada")

j.nueva_conversacion()
ok(not j.load_state()["started"] and j.load_state()["kimi_session"] is None, "/nueva reinicia la continuidad")
j.STATE.write_text(json.dumps({"session": "claude-antiguo", "started": True}), encoding="utf-8")
j.run_kimi("migracion", "ask")
ok("--session" not in args_n() and "--agent-file" in args_n(), "el estado antiguo de Claude no se reutiliza")
reg = json.loads(j.TELEMETRIA.read_text(encoding="utf-8").splitlines()[-1])
ok(reg["tok_in"] is None and reg["tok_out"] is None, "tokens sin medida quedan vacíos, no a cero")
print("TODAS LAS PRUEBAS DE KIMI OK")
