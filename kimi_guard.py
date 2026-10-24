# -*- coding: utf-8 -*-
"""Hook PreToolUse de Kimi: bloquea comandos prohibidos solo en procesos de Pedro."""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RULES = (
    ("rm -rf", re.compile(r"(?<![\w-])rm\s+(?:-[a-z0-9-]+\s+)*-[a-z0-9-]*r[a-z0-9-]*f[a-z0-9-]*(?=\s|$)", re.I)),
    ("rm -r -f", re.compile(r"(?<![\w-])rm\s+-r\s+-f(?=\s|$)", re.I)),
    ("del /s", re.compile(r"(?<![\w-])del(?:\.exe)?\s+/s(?=\s|/|$)", re.I)),
    ("format", re.compile(r"(?<![\w-])format(?:\.(?:exe|com|cmd|bat))?(?=\s|$)", re.I)),
    ("shutdown", re.compile(r"(?<![\w-])shutdown(?:\.exe)?(?=\s|$)", re.I)),
    ("reg delete", re.compile(r"(?<![\w-])reg(?:\.exe)?\s+delete(?=\s|$)", re.I)),
    ("diskpart", re.compile(r"(?<![\w-])diskpart(?:\.exe)?(?=\s|$)", re.I)),
    ("Remove-Item -Recurse", re.compile(r"(?<![\w-])remove-item\b[^;&|\r\n]*-recurse(?=\s|$)", re.I)),
    ("Stop-Computer", re.compile(r"(?<![\w-])stop-computer(?=\s|$)", re.I)),
    ("Restart-Computer", re.compile(r"(?<![\w-])restart-computer(?=\s|$)", re.I)),
)


def guard_reason(payload, env=None):
    env = os.environ if env is None else env
    if env.get("PEDRO_KIMI_GUARD") != "1":
        return None
    cwd = payload.get("cwd") or ""
    try:
        Path(cwd).resolve().relative_to(ROOT)
    except (OSError, ValueError):
        return None
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str):
        return None
    normalized = re.sub(r"\s+", " ", command).strip()
    for name, pattern in RULES:
        if pattern.search(normalized):
            return name
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        return 0
    reason = guard_reason(payload)
    if reason:
        print(f"Pedro ha bloqueado este comando por la regla: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
