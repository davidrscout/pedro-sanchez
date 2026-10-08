# -*- coding: utf-8 -*-
"""Oído de Pedro en el PC: audio del móvil -> texto con faster-whisper (local, gratis, sin internet ni Apple/Google).
Lo usa el panel cuando el navegador no deja dictar (p. ej. Safari con el Dictado apagado).
GPU si se puede (float16); si CUDA falla, CPU int8. El modelo se carga al primer uso y se suelta tras 10 min sin uso."""
import io
import threading
import time

MODELO = "medium"         # ya descargado; acierta más que small en español (≈3 s por frase en CPU)
LIBERAR_TRAS = 600
_M = {"modelo": None, "ult": 0, "disp": ""}
_LOCK = threading.Lock()


def _cargar():
    from faster_whisper import WhisperModel
    try:
        import numpy as np
        m = WhisperModel(MODELO, device="cuda", compute_type="float16")
        list(m.transcribe(np.zeros(16000, dtype=np.float32), language="es")[0])   # prueba real: falta cuBLAS 12 = falla aquí
        _M["disp"] = "gpu"
    except Exception:
        m = WhisperModel(MODELO, device="cpu", compute_type="int8")
        _M["disp"] = "cpu"
    return m


def _vigia():
    while True:
        time.sleep(60)
        with _LOCK:
            if _M["modelo"] is not None and time.time() - _M["ult"] > LIBERAR_TRAS:
                _M["modelo"] = None     # libera VRAM/RAM


threading.Thread(target=_vigia, daemon=True).start()


def decodificar(audio_bytes):
    """Cualquier formato del navegador -> numpy float32 mono 16 kHz (PyAV directo: el decode_audio de faster-whisper
    1.2.1 no es compatible con PyAV 19)."""
    import av
    import numpy as np
    partes = []
    with av.open(io.BytesIO(audio_bytes)) as c:
        rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in c.decode(audio=0):
            for f in rs.resample(frame):
                partes.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None):
            partes.append(f.to_ndarray().reshape(-1))
    if not partes:
        return None
    return (np.concatenate(partes).astype(np.float32) / 32768.0)


def transcribir(audio_bytes):
    """Devuelve el texto (str). audio_bytes: webm/ogg/mp4/m4a/wav tal como lo graba el navegador."""
    if not audio_bytes or len(audio_bytes) < 800:
        return ""
    onda = decodificar(audio_bytes)
    if onda is None or len(onda) < 16000 * 0.3:
        return ""
    with _LOCK:
        if _M["modelo"] is None:
            _M["modelo"] = _cargar()
        _M["ult"] = time.time()
        segs, _info = _M["modelo"].transcribe(onda, language="es", beam_size=1, vad_filter=True,
                                              condition_on_previous_text=False)
        texto = " ".join(s.text.strip() for s in segs).strip()
        _M["ult"] = time.time()
    return texto
