# -*- coding: utf-8 -*-
"""Memoria a largo plazo de Pedro (idea de OpenJarvis memory/ + USER.md): hechos sueltos en memoria.json y un perfil
fijo en perfil.md. Ambos se inyectan en el prompt de cada conversación. Nunca se guardan claves ni contraseñas."""
import json
import os
import re
import time
import uuid
from pathlib import Path

HOME = Path(__file__).resolve().parent
FILE = HOME / "memoria.json"
PERFIL = HOME / "perfil.md"
MAX_HECHOS = 200
MAX_LARGO = 400
SECRETO = re.compile(r"(contrase|password|passwd|token|api[_ -]?key|secret|clave privada|\bpin\b|sk-[a-z0-9]|ghp_)", re.I)


def _norm(t):
    return re.sub(r"[^a-z0-9áéíóúñü ]", "", re.sub(r"\s+", " ", str(t).lower())).strip()


def _leer():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _escribir(items):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE)


def listar():
    return _leer()


def recordar(texto, tema="general"):
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    if not texto:
        return "Nada que recordar."
    if len(texto) > MAX_LARGO:
        return f"Demasiado largo (máx. {MAX_LARGO} caracteres): resúmelo."
    if SECRETO.search(texto):
        return "No guardo claves, contraseñas, PIN ni tokens."
    items = _leer()
    n = _norm(texto)
    for it in items:
        if _norm(it["texto"]) == n:
            return f"Ya lo sabía (id {it['id']})."
    it = {"id": uuid.uuid4().hex[:6], "texto": texto, "tema": str(tema or "general")[:30], "t": time.strftime("%Y-%m-%d %H:%M")}
    items.append(it)
    _escribir(items[-MAX_HECHOS:])
    return f"Guardado (id {it['id']})."


def olvidar(ident):
    items = _leer()
    quedan = [i for i in items if i["id"] != str(ident)]
    if len(quedan) == len(items):
        return "No encuentro ese id."
    _escribir(quedan)
    return "Olvidado."


def perfil():
    try:
        return PERFIL.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def bloque_prompt():
    """Texto que se añade al prompt de sistema de cada conversación."""
    partes = []
    p = perfil()
    if p:
        partes.append("## Perfil de David (fijo)\n" + p[:4000])
    items = _leer()
    if items:
        partes.append("## Lo que recuerdas de conversaciones anteriores (id: hecho)\n" +
                      "\n".join(f"- {i['id']}: {i['texto']}" for i in items[-120:]))
    return "\n\n".join(partes)
