# -*- coding: utf-8 -*-
"""Avisar a David o preguntarle algo y esperar su respuesta, desde CUALQUIER agente o script (Claude Code, T3, Codex...).
No necesita que Jarvis esté escuchando: escribe en avisos.json y Jarvis lo entrega por Telegram; David responde en la app Pedro.

  python C:\\Dev\\Jarvis\\avisar.py "Terminé el despliegue"                       # informativo: lo entrega y termina
  python C:\\Dev\\Jarvis\\avisar.py --pregunta "¿Sigo?" --opciones "Sí|No" --esperar 900 --origen "Orquestador X"
  python C:\\Dev\\Jarvis\\avisar.py --consultar 3fa9c1d2                           # ¿ya respondió a aquella pregunta?

Salida: con --pregunta/--consultar, la RESPUESTA (solo ella) por stdout. Código de salida: 0 respondido (o aviso informativo
registrado), 2 sin respuesta en el tiempo dado (la pregunta sigue pendiente; el id sale por stderr), 1 error de uso."""
import argparse
import sys

import avisos


def _salida_utf8():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None):
    _salida_utf8()
    ap = argparse.ArgumentParser(description="Avisa a David o le pregunta algo y espera la respuesta.")
    ap.add_argument("texto", nargs="?", help="aviso informativo (sin esperar respuesta)")
    ap.add_argument("--pregunta", help="pregunta: se queda esperando la respuesta de David")
    ap.add_argument("--opciones", default="", help="opciones separadas por | (vacío = respuesta libre)")
    ap.add_argument("--esperar", type=int, default=None, help="segundos máximos de espera (por defecto 600 con --pregunta, 0 con --consultar)")
    ap.add_argument("--origen", default="Agente", help="quién pregunta, p. ej. «Orquestador Gemsy»")
    ap.add_argument("--urgente", action="store_true", help="marcar como urgente")
    ap.add_argument("--consultar", metavar="ID", help="ver si ya hay respuesta a una pregunta anterior (espera --esperar s si se da)")
    a = ap.parse_args(argv)
    try:
        if a.consultar:
            if a.texto or a.pregunta:
                ap.error("--consultar no se combina con un texto")
            av = avisos.obtener(a.consultar)
            if av is None:
                print("No existe ese aviso.", file=sys.stderr)
                return 1
            r = avisos.esperar(a.consultar, a.esperar or 0)
            if r is None:
                print(f"Sin respuesta todavía (estado: {av['estado']}).", file=sys.stderr)
                return 2
            print(r)
            return 0
        if bool(a.texto) == bool(a.pregunta):
            ap.error("da un texto informativo O --pregunta (una de las dos)")
        opciones = [o for o in a.opciones.split("|")] if a.opciones else []
        if a.pregunta:
            espera = 600 if a.esperar is None else max(1, a.esperar)
            av = avisos.crear(a.pregunta, opciones, espera=True, urgente=a.urgente, origen=a.origen)
            r = avisos.esperar(av["id"], espera)
            if r is None:
                print(f"Sin respuesta en {espera} s (id {av['id']}; sigue pendiente: avisar.py --consultar {av['id']}).",
                      file=sys.stderr)
                return 2
            print(r)
            return 0
        av = avisos.crear(a.texto, None, espera=False, urgente=a.urgente, origen=a.origen)
        print(f"Aviso registrado (id {av['id']}); Jarvis lo entrega por Telegram.")
        return 0
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except TimeoutError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
