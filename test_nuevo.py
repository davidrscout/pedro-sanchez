# -*- coding: utf-8 -*-
"""Pruebas de memoria.py y agenda.py (en una carpeta temporal; no tocan los ficheros reales)."""
import datetime as dt
import tempfile
from pathlib import Path

import agenda
import memoria

tmp = Path(tempfile.mkdtemp())
memoria.FILE, memoria.PERFIL = tmp / "m.json", tmp / "perfil.md"
agenda.FILE, agenda.BANDEJA, agenda.CANDADO = tmp / "a.json", tmp / "b.json", tmp / "a.lock"


def ok(c, msg):
    print(("OK  " if c else "FALLO ") + msg)
    assert c, msg


# ---------------- memoria
ok("Guardado" in memoria.recordar("A David no le gusta el naranja"), "recordar guarda")
ok("Ya lo sabía" in memoria.recordar("a david NO le gusta el naranja!"), "recordar deduplica (mayúsculas/puntuación)")
ok("No guardo" in memoria.recordar("la contraseña del router es 1234"), "no guarda contraseñas")
ok("No guardo" in memoria.recordar("mi api key es sk-abc"), "no guarda api keys")
ok("Demasiado largo" in memoria.recordar("x" * 500), "rechaza textos largos")
mid = memoria.listar()[0]["id"]
memoria.PERFIL.write_text("Vive en Pattaya.", encoding="utf-8")
b = memoria.bloque_prompt()
ok("Pattaya" in b and "naranja" in b and mid in b, "bloque_prompt lleva perfil + hechos con id")
ok(memoria.olvidar(mid) == "Olvidado." and not memoria.listar(), "olvidar borra")
ok(memoria.olvidar("nope") == "No encuentro ese id.", "olvidar id inexistente")

# ---------------- agenda: parseo
ahora = dt.datetime(2026, 10, 4, 22, 0)
ok(agenda.parse_cuando("+30", ahora) == dt.datetime(2026, 10, 4, 22, 30), "+30 = 30 min")
ok(agenda.parse_cuando("+2h", ahora) == dt.datetime(2026, 10, 5, 0, 0), "+2h")
ok(agenda.parse_cuando("09:00", ahora) == dt.datetime(2026, 10, 5, 9, 0), "HH:MM ya pasada = mañana")
ok(agenda.parse_cuando("23:15", ahora) == dt.datetime(2026, 10, 4, 23, 15), "HH:MM futura = hoy")
ok(agenda.parse_cuando("2026-12-24 20:00", ahora) == dt.datetime(2026, 12, 24, 20, 0), "fecha completa")
try:
    agenda.parse_cuando("mañana", ahora)
    ok(False, "texto libre debería fallar")
except ValueError:
    ok(True, "texto libre no válido -> error claro")

# ---------------- agenda: crear / validar
ok("Programado" in agenda.crear("+1", "beber agua"), "crear aviso")
ok("repetir" in agenda.crear("+1", "x", repetir="cada:2"), "cada:<5 min rechazado")
ok("tipo" in agenda.crear("+1", "x", tipo="borrar_todo"), "tipo inválido rechazado")
ok("ya ha pasado" in agenda.crear("2020-01-01 10:00", "x"), "fecha pasada rechazada")
ok("Programado" in agenda.crear("+1", "informe", tipo="tarea", repetir="diario"), "crear tarea diaria")
ok(len(agenda.listar()) == 2, "hay 2 en la agenda")

# ---------------- agenda: disparo y reprogramación
futuro = dt.datetime.now() + dt.timedelta(minutes=2)
salen = agenda.vencidos(futuro)
ok(len(salen) == 2, "a los 2 min vencen los 2")
quedan = agenda.listar()
ok(len(quedan) == 1 and quedan[0]["repetir"] == "diario", "el aviso único desaparece; la diaria se queda")
sig = dt.datetime.strptime(quedan[0]["cuando"], "%Y-%m-%d %H:%M")
ok(sig > futuro and (sig - futuro) < dt.timedelta(days=1, minutes=1), "la diaria pasa al día siguiente")
ok(agenda.vencidos(futuro) == [], "no se dispara dos veces")
ok(agenda.borrar(quedan[0]["id"]) == "Borrado." and not agenda.listar(), "borrar")

# laborables: un viernes a las 09:00 -> siguiente es lunes
agenda._escribir(agenda.FILE, [{"id": "l1", "cuando": "2026-10-09 09:00", "texto": "t", "tipo": "aviso", "repetir": "laborables", "creado": ""}])
salen = agenda.vencidos(dt.datetime(2026, 10, 9, 9, 1))
ok(len(salen) == 1 and agenda.listar()[0]["cuando"] == "2026-10-12 09:00", "laborables salta el fin de semana")
# PC apagado mucho tiempo: no dispara recordatorios de hace más de 12 h
agenda._escribir(agenda.FILE, [{"id": "v1", "cuando": "2026-10-01 09:00", "texto": "viejo", "tipo": "aviso", "repetir": "no", "creado": ""}])
ok(agenda.vencidos(dt.datetime(2026, 10, 4, 9, 0)) == [] and not agenda.listar(), "lo de hace >12 h se descarta sin avisar")

# ---------------- bandeja
ok("cola" in agenda.encolar("hola"), "encolar")
ok(agenda.sacar_bandeja() == ["hola"] and agenda.sacar_bandeja() == [], "sacar_bandeja vacía tras leer")
print("TODAS LAS PRUEBAS NUEVAS OK")
