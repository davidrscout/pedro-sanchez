# -*- coding: utf-8 -*-
"""Voz de Pedro: texto -> MP3 con las voces neuronales de Edge (edge-tts, gratis, sin clave). Necesita internet en el PC."""
import asyncio
import re

VOZ = "es-ES-AlvaroNeural"
VOCES_OK = {"es-ES-AlvaroNeural", "es-ES-ElviraNeural", "es-ES-ArnauNeural", "es-MX-JorgeNeural", "es-AR-TomasNeural"}


def limpia(t):
    """Quita markdown y cosas que suenan fatal leídas en voz alta."""
    t = re.sub(r"```.*?```", " (código omitido) ", str(t), flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", " enlace ", t)
    t = re.sub(r"[*_#>|~]+", " ", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()


async def _gen(texto, voz, ritmo):
    import edge_tts
    com = edge_tts.Communicate(texto, voz, rate=ritmo)
    out = bytearray()
    async for ch in com.stream():
        if ch["type"] == "audio":
            out += ch["data"]
    return bytes(out)


def sintetizar(texto, voz=VOZ, ritmo="+8%"):
    texto = limpia(texto)[:1200]
    if not texto:
        raise ValueError("texto vacío")
    if voz not in VOCES_OK:
        voz = VOZ
    if not re.fullmatch(r"[+-]\d{1,2}%", ritmo or ""):
        ritmo = "+0%"
    mp3 = asyncio.run(asyncio.wait_for(_gen(texto, voz, ritmo), 25))
    if not mp3:
        raise RuntimeError("sin audio")
    return mp3
