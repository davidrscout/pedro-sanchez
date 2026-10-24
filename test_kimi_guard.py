# -*- coding: utf-8 -*-
"""Pruebas de la guarda PreToolUse de Kimi, sin llamar al CLI ni ejecutar comandos."""
import kimi_guard as g

ENV = {"PEDRO_KIMI_GUARD": "1"}


def payload(command, cwd=None):
    return {"cwd": cwd or str(g.ROOT / "workspace"), "tool_input": {"command": command}}


def ok(c, msg):
    print(("OK  " if c else "FALLO ") + msg)
    assert c, msg


prohibidos = [
    "rm -rf /tmp/prueba", "RM   -RF   /tmp/prueba", "rm -r -f /tmp/prueba",
    "del /s /q prueba", "DEL.EXE /S prueba", "format c:", "shutdown /s /t 0",
    "reg delete HKCU\\Software\\Prueba /f", "REG.EXE DELETE HKCU\\Prueba /f", "diskpart",
    "Remove-Item -Recurse prueba", "Remove-Item -Path prueba -Recurse",
    "Stop-Computer", "powershell -Command Restart-Computer",
]
for comando in prohibidos:
    ok(g.guard_reason(payload(comando), ENV) is not None, "bloquea: " + comando)

permitidos = ["echo hola", "python --version", "git status", "Format-Table", "echo formato", "Get-ChildItem"]
for comando in permitidos:
    ok(g.guard_reason(payload(comando), ENV) is None, "permite: " + comando)

ok(g.guard_reason(payload("rm -rf /tmp/x"), {}) is None, "sin marca de Pedro no bloquea")
ok(g.guard_reason(payload("rm -rf /tmp/x", "C:/"), ENV) is None, "fuera de Jarvis no bloquea")
ok(g.guard_reason({"cwd": str(g.ROOT / "workspace"), "tool_input": {}}, ENV) is None, "payload sin comando permite")
print("TODAS LAS PRUEBAS DE LA GUARDA OK")
