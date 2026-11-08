# -*- coding: utf-8 -*-
"""Prueba del puente entre equipos sin Tailscale: el «otro equipo» escucha en 127.0.0.1 y se finge red 100.x."""
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import webpanel as w

fallos = 0


def ok(cond, txt):
    global fallos
    print(("OK  " if cond else "MAL ") + txt)
    fallos += 0 if cond else 1


SECRETO = "secreto-de-prueba"
w.equipos_cfg = lambda: {"yo": "Casa", "secreto": SECRETO, "equipos": [{"nombre": "Oficina", "ip": "127.0.0.1"}, {"nombre": "Apagado", "ip": "127.0.0.2"}]}
w.Puente._de_tailscale = lambda self: True
pedidos = []
w.new_link = lambda pre=False: (pedidos.append(pre), ("https://x.trycloudflare.com/t/abc", None))[1]
w.PORT = 18799
srv = ThreadingHTTPServer(("127.0.0.1", w.PORT), w.Puente)
threading.Thread(target=srv.serve_forever, daemon=True).start()

l = w.equipos_lista()
ok(l["yo"] == "Casa", "lista: nombre propio")
ok(l["equipos"][0] == {"nombre": "Oficina", "online": True}, "lista: Oficina en línea")
ok(l["equipos"][1]["online"] is False, "lista: equipo apagado sale apagado")

url, err = w.puente_pedir("Oficina")
ok(url == "https://x.trycloudflare.com/t/abc" and pedidos == [True], "saltar: devuelve el enlace del otro, marcado pre=True")
url, err = w.puente_pedir("Nadie")
ok(url is None and "configurado" in err, "saltar: equipo desconocido -> error claro")


def post(headers):
    rq = urllib.request.Request(f"http://127.0.0.1:{w.PORT}/puente/enlace", data=b"{}", method="POST", headers=headers)
    try:
        return urllib.request.urlopen(rq, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


ts = str(int(time.time()))
ok(post({"X-Ts": ts, "X-Firma": "mala"}) == 403, "firma mala -> 403")
viejo = str(int(time.time()) - 300)
ok(post({"X-Ts": viejo, "X-Firma": w._firma(SECRETO, viejo)}) == 403, "firma caducada (5 min) -> 403")
ok(post({"X-Ts": ts, "X-Firma": w._firma("otro", ts)}) == 403, "secreto distinto -> 403")
ok(post({}) == 403, "sin firma -> 403")
try:
    urllib.request.urlopen(f"http://127.0.0.1:{w.PORT}/api/estado", timeout=5)
    ok(False, "el puente no expone la API")
except urllib.error.HTTPError as e:
    ok(e.code == 404, "el puente NO expone la API del panel (404)")
ok(len(pedidos) == 1, "ninguna petición rechazada generó enlace")
print("TODAS LAS PRUEBAS DEL PUENTE OK" if not fallos else f"{fallos} FALLOS")
