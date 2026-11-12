# -*- coding: utf-8 -*-
"""Pruebas de avisos.py y del CLI avisar.py. Todo en una carpeta temporal (JARVIS_AVISOS_DIR): nunca toca avisos.json real
ni manda nada a Telegram."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="avisos_test_"))
os.environ["JARVIS_AVISOS_DIR"] = str(TMP)
HOME = Path(__file__).resolve().parent

import avisos as av  # noqa: E402

fallos = 0


def ok(c, txt):
    global fallos
    print(("OK  " if c else "MAL ") + txt)
    fallos += 0 if c else 1


def limpiar():
    for f in TMP.glob("avisos*"):
        f.unlink()


def cli(args, **kw):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([sys.executable, str(HOME / "avisar.py"), *args], capture_output=True, env=env, timeout=60, **kw)


# ---------------------------------------------------------------- crear / listar
a = av.crear("¿Sigo con el despliegue?", ["Sí", "No"], espera=True, urgente=True, origen="Orquestador Gemsy")
ok(a["estado"] == "pendiente" and a["espera"] and a["urgente"] and a["opciones"] == ["Sí", "No"] and a["origen"] == "Orquestador Gemsy",
   "crear pregunta: pendiente, urgente, con opciones y origen")
ok(len(a["id"]) == 8 and a["notificado"] is False and a["respuesta"] is None and a["via"] is None and a["respondido_en"] is None,
   "crear: id corto, sin notificar, sin respuesta")
ok(set(a) == set(av.PUBLICOS), "el aviso público trae exactamente los campos del contrato")
b = av.crear("Terminé la copia de seguridad")
ok(b["estado"] == "informativo" and not b["espera"] and b["opciones"] == [] and b["origen"] == "Pedro", "crear informativo: sin espera, origen por defecto «Pedro»")
ok([x["id"] for x in av.listar()] == [a["id"]], "listar(solo_pendientes) = solo las preguntas sin responder")
ok({x["id"] for x in av.listar(False)} == {a["id"], b["id"]}, "listar(False) trae también los informativos")
ok(av.listar(False, n=1)[0]["id"] == b["id"], "más reciente primero y n limita")
ok(av.obtener(a["id"])["texto"] == "¿Sigo con el despliegue?" and av.obtener("nada") is None, "obtener por id")
ok(av.crear("x", "Sí|No|Sí| ", espera=True)["opciones"] == ["Sí", "No"], "opciones como texto con | (sin repetidas ni vacías)")
ok(len(av.crear("y", [f"o{i}" for i in range(20)], espera=True)["opciones"]) == av.MAX_OPCIONES, "máximo de opciones")
for malo in ("", "   ", None):
    try:
        av.crear(malo)
        ok(False, f"texto vacío {malo!r} debe fallar")
    except ValueError:
        ok(True, f"texto vacío {malo!r} -> ValueError")
ok(len(av.crear("z" * 5000)["texto"]) == av.MAX_TEXTO, "texto largo recortado")
ok(not (TMP / "avisos.lock").exists(), "el candado no se queda puesto")

# ---------------------------------------------------------------- responder
r = av.responder(a["id"], "  Sí, sigue  ", "app")
ok(r == (True, ""), "responder -> (True, '')")
c = av.obtener(a["id"])
ok(c["estado"] == "respondido" and c["respuesta"] == "Sí, sigue" and c["via"] == "app" and c["respondido_en"], "queda respondido con respuesta, vía y hora")
ok(av.responder(a["id"], "No", "web")[0] is False and av.obtener(a["id"])["respuesta"] == "Sí, sigue" and av.obtener(a["id"])["via"] == "app",
   "DOBLE respuesta rechazada: gana la primera")
ok("ya estaba respondido" in av.responder(a["id"], "No", "telegram")[1], "el motivo de la doble respuesta es claro")
ok(av.responder("noexiste", "x", "app") == (False, "No existe ese aviso."), "id inexistente rechazado")
ok(av.responder(b["id"], "x", "app")[0] is False, "un informativo no admite respuesta")
p = av.crear("pregunta de prueba", espera=True)
ok(av.responder(p["id"], "   ", "app")[0] is False, "respuesta vacía rechazada")
ok(av.responder(p["id"], "x" * 2001, "app")[0] is False and av.obtener(p["id"])["estado"] == "pendiente", "respuesta de más de 2000 caracteres rechazada")
ok(av.responder(p["id"], "x" * 2000, "web")[0] is True, "exactamente 2000 caracteres vale")
try:
    av.responder(av.crear("q", espera=True)["id"], "x", "sms")
    ok(False, "vía desconocida debe fallar")
except ValueError:
    ok(True, "vía desconocida -> ValueError")
ok(all(av.responder(av.crear("v", espera=True)["id"], "ok", v)[0] for v in ("app", "web", "telegram")), "las tres vías valen: app, web, telegram")

# ---------------------------------------------------------------- esperar
limpiar()
q = av.crear("¿Elijo A o B?", ["A", "B"], espera=True)
threading.Timer(1.2, lambda: av.responder(q["id"], "B", "app")).start()
t0 = time.time()
resp = av.esperar(q["id"], 15)
ok(resp == "B" and 0.9 < time.time() - t0 < 4, f"esperar devuelve la respuesta cuando otro hilo responde ({time.time() - t0:.1f} s)")
ok(av.esperar(q["id"], 5) == "B", "esperar sobre un aviso ya respondido devuelve al instante")
q2 = av.crear("¿Nadie contesta?", espera=True)
t0 = time.time()
ok(av.esperar(q2["id"], 2) is None and 1.8 < time.time() - t0 < 4, "esperar con timeout -> None")
ok(av.obtener(q2["id"])["estado"] == "pendiente", "tras el timeout la pregunta sigue pendiente (David aún puede verla)")
ok(av.esperar("noexiste", 5) is None, "esperar un id inexistente -> None sin esperar")
q3 = av.crear("¿Caduca mientras espero?", espera=True)
with av._Candado():
    its = av._leer()
    for i in its:
        if i["id"] == q3["id"]:
            i["t"] -= 30 * 3600
    av._escribir(its)
threading.Timer(0.8, av.caducar_viejos).start()
t0 = time.time()
ok(av.esperar(q3["id"], 10) is None and time.time() - t0 < 5, "si el aviso caduca mientras se espera, esperar termina con None")

# ---------------------------------------------------------------- caducar
limpiar()
viejo = av.crear("vieja", espera=True)
nuevo = av.crear("nueva", espera=True)
info = av.crear("informativa vieja")
resp_v = av.crear("respondida vieja", espera=True)
av.responder(resp_v["id"], "hecho", "app")
with av._Candado():
    its = av._leer()
    for i in its:
        if i["id"] in (viejo["id"], info["id"], resp_v["id"]):
            i["t"] -= 25 * 3600
    av._escribir(its)
ok(av.caducar_viejos(24) == 1, "caducar_viejos(24) caduca solo la pendiente de más de 24 h")
ok(av.obtener(viejo["id"])["estado"] == "caducado" and av.obtener(nuevo["id"])["estado"] == "pendiente"
   and av.obtener(info["id"])["estado"] == "informativo" and av.obtener(resp_v["id"])["estado"] == "respondido",
   "la nueva, la informativa y la respondida no se tocan")
ok("ha caducado" in av.responder(viejo["id"], "tarde", "app")[1], "no se puede responder a un aviso caducado")
ok([x["id"] for x in av.listar()] == [nuevo["id"]], "los caducados salen de «pendientes»")
ok(av.caducar_viejos(24) == 0, "caducar es idempotente")

# ---------------------------------------------------------------- entrega a Telegram (cola)
limpiar()
e1, e2 = av.crear("uno", espera=True), av.crear("dos")
sale = av.sacar_no_notificados()
ok({x["id"] for x in sale} == {e1["id"], e2["id"]} and all("tg_msg" in x for x in sale), "sacar_no_notificados trae los dos")
ok(av.sacar_no_notificados() == [], "y no los vuelve a sacar (nunca se entrega dos veces)")
av.devolver_a_la_cola(e1["id"])
ok([x["id"] for x in av.sacar_no_notificados()] == [e1["id"]], "un envío fallido vuelve a la cola")
for _ in range(6):
    av.devolver_a_la_cola(e1["id"])
    av.sacar_no_notificados()
ok(av.sacar_no_notificados() == [], "tras 5 fallos se da por entregado (no reintenta eternamente)")
av.marcar_mensaje(e1["id"], 777)
ok(av.por_editar() == [], "mientras está pendiente no hay nada que editar en Telegram")
av.responder(e1["id"], "vale", "app")
ok([x["id"] for x in av.por_editar()] == [e1["id"]] and av.por_editar()[0]["tg_msg"] == 777, "respondido con mensaje de Telegram -> por editar")
av.marcar_editado(e1["id"])
ok(av.por_editar() == [], "marcar_editado lo saca de la lista")
ok(av.listar(False, 10) and "tg_msg" not in av.listar(False, 1)[0], "la lista pública no enseña campos internos")

# ---------------------------------------------------------------- límites
limpiar()
for i in range(av.MAX_PENDIENTES):
    av.crear(f"p{i}", espera=True)
try:
    av.crear("una más", espera=True)
    ok(False, "más de 25 preguntas pendientes debe fallar")
except ValueError as ex:
    ok("sin responder" in str(ex), "tope de preguntas pendientes")
limpiar()
for i in range(av.MAX_POR_HORA):
    av.crear(f"i{i}")
try:
    av.crear("flood")
    ok(False, "más de 60 avisos en una hora debe fallar")
except ValueError as ex:
    ok("última hora" in str(ex), "tope de avisos por hora")

# ---------------------------------------------------------------- fichero roto: no se pierde, se aparta
limpiar()
(TMP / "avisos.json").write_text("{esto no es json", encoding="utf-8")
ok(av.listar(False) == [] and list(TMP.glob("avisos.json.corrupto_*")), "JSON roto: se aparta como .corrupto_ y se empieza de cero")
ok(av.crear("tras el roto", espera=True)["estado"] == "pendiente", "y se puede seguir usando")

# ---------------------------------------------------------------- candado entre procesos
limpiar()
SCRIPT = """
import sys, os
sys.path.insert(0, {home!r})
import avisos
n = int(sys.argv[1]); quien = sys.argv[2]
for i in range(n):
    a = avisos.crear(f"{{quien}}-{{i}}", espera=True, origen=quien)
    if i % 2 == 0:
        avisos.responder(a["id"], "r", "app")
"""
env = dict(os.environ, PYTHONUTF8="1")
procs = [subprocess.Popen([sys.executable, "-c", SCRIPT.format(home=str(HOME)), "15", q], env=env, stderr=subprocess.PIPE) for q in ("P1", "P2", "P3")]
errs = [p.communicate(timeout=120)[1].decode("utf-8", "replace") for p in procs]
ok(all(p.returncode == 0 for p in procs), "tres procesos escribiendo a la vez terminan sin error " + "".join(errs)[:200])
todos = json.loads((TMP / "avisos.json").read_text(encoding="utf-8"))
ok(len(todos) == 45 and len({x["id"] for x in todos}) == 45, f"no se pierde ni se duplica ningún aviso entre procesos ({len(todos)}/45)")
ok(sum(1 for x in todos if x["estado"] == "respondido") == 24, "las 24 respuestas concurrentes también quedan")
ok(not (TMP / "avisos.lock").exists() and not list(TMP.glob("avisos.*.tmp")), "sin candado ni temporales sueltos")
# candado huérfano de un proceso muerto: se recupera
(TMP / "avisos.lock").write_text("x")
old = time.time() - 60
os.utime(TMP / "avisos.lock", (old, old))
ok(av.crear("tras candado huérfano", espera=True)["estado"] == "pendiente", "un candado huérfano (>10 s) se recupera solo")

# ---------------------------------------------------------------- CLI avisar.py
limpiar()
r = cli(["Copia terminada", "--origen", "Orquestador Prueba"])
ok(r.returncode == 0 and b"Aviso registrado" in r.stdout, "CLI informativo -> código 0")
v = av.listar(False)
ok(len(v) == 1 and v[0]["estado"] == "informativo" and v[0]["origen"] == "Orquestador Prueba" and v[0]["texto"] == "Copia terminada", "CLI informativo deja un aviso informativo con su origen")


def contesta(texto, resp, seg=40):
    """Hilo que espera a que aparezca la pregunta y la responde."""
    def go():
        t0 = time.time()
        while time.time() - t0 < seg:
            for x in av.listar():
                if x["texto"] == texto:
                    time.sleep(0.5)
                    av.responder(x["id"], resp, "app")
                    return
            time.sleep(0.2)
    th = threading.Thread(target=go, daemon=True)
    th.start()
    return th


contesta("¿Sigo?", "Sí")
r = cli(["--pregunta", "¿Sigo?", "--opciones", "Sí|No", "--esperar", "30", "--origen", "Orquestador X", "--urgente"])
ok(r.returncode == 0 and r.stdout.decode("utf-8").strip() == "Sí", f"CLI pregunta respondida -> código 0 y la respuesta SOLA por stdout ({r.stdout!r})")
x = [i for i in av.listar(False) if i["texto"] == "¿Sigo?"][0]
ok(x["opciones"] == ["Sí", "No"] and x["urgente"] and x["origen"] == "Orquestador X" and x["estado"] == "respondido", "CLI: opciones, urgente y origen llegan al aviso")
t0 = time.time()
r = cli(["--pregunta", "¿Hay alguien?", "--esperar", "2"])
ok(r.returncode == 2 and r.stdout == b"" and 1.8 < time.time() - t0 < 12, f"CLI sin respuesta -> código 2 y stdout vacío ({time.time() - t0:.1f} s)")
idp = [i for i in av.listar() if i["texto"] == "¿Hay alguien?"][0]["id"]
ok(idp.encode() in r.stderr, "CLI sin respuesta: el id sale por stderr para consultar luego")
r = cli(["--consultar", idp])
ok(r.returncode == 2, "CLI --consultar sin respuesta todavía -> 2")
av.responder(idp, "tarde pero a tiempo", "web")
r = cli(["--consultar", idp])
ok(r.returncode == 0 and r.stdout.decode("utf-8").strip() == "tarde pero a tiempo", "CLI --consultar con respuesta -> 0 y la respuesta")
ok(cli(["--consultar", "noexiste"]).returncode == 1, "CLI --consultar de un id inexistente -> 1")
ok(cli([]).returncode == 2 or cli([]).returncode == 1, "CLI sin argumentos -> error de uso")
ok(cli(["a", "--pregunta", "b"]).returncode != 0, "CLI: texto y --pregunta a la vez -> error de uso")
ok(cli(["   "]).returncode != 0, "CLI: texto vacío -> error")

# ---------------------------------------------------------------- herramientas MCP de Pedro (ask y do)
LISTA = ("import asyncio, sys; sys.path.insert(0, %r); import pedro_mcp as m; "
         "print(','.join(sorted(t.name for t in asyncio.run(m.mcp.list_tools()) if 'david' in t.name)))") % str(HOME)
for modo in ("ask", "do"):
    r = subprocess.run([sys.executable, "-c", LISTA], capture_output=True, timeout=120, env=dict(env, PEDRO_MODO=modo))
    ok(r.stdout.decode().strip() == "avisar_a_david,preguntar_a_david", f"modo {modo}: están avisar_a_david y preguntar_a_david " + r.stderr.decode()[-150:])
limpiar()
import asyncio  # noqa: E402
import pedro_mcp  # noqa: E402
r = asyncio.run(pedro_mcp.mcp.call_tool("avisar_a_david", {"texto": "listo el informe", "urgente": True}))
x = av.listar(False)[0]
ok(not r.is_error and x["texto"] == "listo el informe" and x["urgente"] and x["origen"] == "Pedro" and x["estado"] == "informativo",
   "avisar_a_david (vía servidor MCP): informativo, urgente, origen «Pedro»")
threading.Timer(1.5, lambda: av.responder(av.listar()[0]["id"], "A", "app")).start()
t0 = time.time()
r = asyncio.run(pedro_mcp.mcp.call_tool("preguntar_a_david", {"pregunta": "¿A o B?", "opciones": ["A", "B"], "esperar_s": 30}))
ok(r.structured_content["result"] == "A" and time.time() - t0 < 10, "preguntar_a_david: bloquea hasta la respuesta y la devuelve")
t0 = time.time()
r = asyncio.run(pedro_mcp.mcp.call_tool("preguntar_a_david", {"pregunta": "¿hola?", "esperar_s": 1}))
t = r.structured_content["result"]
ok(t.startswith("Sin respuesta en 5 s") and 4.5 < time.time() - t0 < 12, f"preguntar_a_david sin respuesta: texto claro «Sin respuesta…» (mínimo 5 s) -> {t[:60]}")
ok(asyncio.run(pedro_mcp.preguntar_a_david("  ", [], 5)) == "Falta el texto.", "preguntar_a_david con pregunta vacía: mensaje claro, no revienta")

print("TODAS LAS PRUEBAS DE AVISOS OK" if not fallos else f"{fallos} FALLOS")
raise SystemExit(1 if fallos else 0)
