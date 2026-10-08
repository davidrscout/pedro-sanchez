# -*- coding: utf-8 -*-
"""Información y control del PC para el panel: procesos, watchdog, red. Solo funciones; sin estado."""
import csv
import datetime
import re
import subprocess
import time
from pathlib import Path

import psutil

NOWIN = 0x08000000
WD = Path(r"C:\Personal\watchdog")
# Procesos que NUNCA se matan desde el panel (sistema, y los del propio asistente)
PROTEGIDOS = {"system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
              "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe", "memory compression",
              "cloudflared.exe", "mullvad-daemon.exe", "nvidia app.exe"}


def _ps(script, timeout=30):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=timeout,
                       creationflags=NOWIN)
    return r.stdout.decode("cp850", errors="replace").strip()


def _es_de_jarvis(p):
    try:
        cmd = " ".join(p.cmdline()).lower()
    except Exception:
        return False
    return "jarvis.py" in cmd or "webpanel.py" in cmd


def procesos(n=25):
    """Top por memoria (con CPU medida en 0,4 s) + ventanas abiertas."""
    procs = list(psutil.process_iter(["pid", "name", "memory_info", "username", "create_time"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(0.4)
    filas = []
    for p in procs:
        try:
            mem = p.info["memory_info"].rss / 2 ** 20 if p.info["memory_info"] else 0
            filas.append({"pid": p.info["pid"], "name": p.info["name"], "cpu": round(p.cpu_percent(None) / (psutil.cpu_count() or 1), 1),
                          "mem_mb": round(mem), "protegido": (p.info["name"] or "").lower() in PROTEGIDOS or _es_de_jarvis(p)})
        except Exception:
            continue
    filas.sort(key=lambda f: f["mem_mb"], reverse=True)
    out = _ps("Get-Process | Where-Object { $_.MainWindowTitle } | ForEach-Object { '{0}|{1}|{2}' -f $_.Id,$_.ProcessName,$_.MainWindowTitle }")
    ventanas = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].isdigit():
            ventanas.append({"pid": int(parts[0]), "name": parts[1], "title": parts[2][:90]})
    return {"total": len(filas), "top": filas[:n], "ventanas": ventanas}


def matar(pid):
    """Cierra un proceso por PID. Devuelve texto. Respeta PROTEGIDOS y no se mata a sí mismo."""
    try:
        p = psutil.Process(int(pid))
        nombre = p.name()
        if nombre.lower() in PROTEGIDOS or _es_de_jarvis(p) or p.pid in (0, 4):
            return f"{nombre} está protegido; no lo cierro."
        hijos = len(p.children(recursive=True))
        p.terminate()
        try:
            p.wait(5)
        except psutil.TimeoutExpired:
            p.kill()
        return f"{nombre} (PID {pid}) cerrado" + (f" con {hijos} hijos" if hijos else "") + "."
    except psutil.NoSuchProcess:
        return "Ese proceso ya no existe."
    except Exception as e:
        return f"No pude cerrarlo: {type(e).__name__}"


def _csv_hoy():
    hoy = datetime.date.today().strftime("%Y%m%d")
    return WD / "logs" / f"telemetria_{hoy}.csv"


def watchdog():
    """Estado del watchdog de la GPU/PC: latido, última muestra, resumen del día, eventos."""
    res = {"activo": False, "latido_s": None, "tarea": None, "ultima": None, "hoy": None, "eventos": [], "sesiones": 0}
    hb = WD / "logs" / "heartbeat.txt"
    if hb.exists():
        res["latido_s"] = int(time.time() - hb.stat().st_mtime)
        res["activo"] = res["latido_s"] < 120
    t = _ps("(Get-ScheduledTask -TaskName WatchdogPC -EA SilentlyContinue).State")
    res["tarea"] = t or ("activo (tarea de sistema, no visible sin administrador)" if res["activo"] else "no encontrada")
    f = _csv_hoy()
    if f.exists():
        try:
            with open(f, encoding="utf-8", errors="replace", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except Exception:
            rows = []
        if rows:
            def num(r, k):
                try:
                    return float(r.get(k, "") or 0)
                except ValueError:
                    return 0.0
            ult = rows[-1]
            res["ultima"] = {k: ult.get(k) for k in ("ts", "cpu_pct", "gpu_temp_c", "gpu_util_pct", "gpu_pwr_w", "gpu_vram_mb",
                                                     "gpu_pstate", "ram_libre_mb", "juego")}
            ups = [num(r, "uptime_s") for r in rows]
            reinicios = sum(1 for a, b in zip(ups, ups[1:]) if b < a)
            res["sesiones"] = reinicios + 1
            res["hoy"] = {"muestras": len(rows), "gpu_temp_max": max(num(r, "gpu_temp_c") for r in rows),
                          "gpu_w_max": max(num(r, "gpu_pwr_w") for r in rows), "gpu_util_max": max(num(r, "gpu_util_pct") for r in rows),
                          "cpu_max": max(num(r, "cpu_pct") for r in rows), "ram_libre_min_mb": min(num(r, "ram_libre_mb") for r in rows),
                          "arranques_hoy": reinicios + 1}
    ev = WD / "logs" / "eventos.log"
    if ev.exists():
        try:
            lines = ev.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
            res["eventos"] = [re.sub(r"\s+", " ", l)[:200] for l in lines]
        except Exception:
            pass
    return res


def serie(horas=24, paso_min=5):
    """Historial del vigilante para el sismograma: la última ventana de `horas`, resumida en tramos de `paso_min` minutos
    (temperatura máx. de la gráfica, carga máx. de la gráfica, CPU media), y los cortes: reinicios (el uptime baja) y huecos
    sin muestras (el PC apagado o colgado)."""
    ahora = datetime.datetime.now()
    desde = ahora - datetime.timedelta(hours=horas)
    muestras = []
    for dias in (1, 0):
        dia = (ahora - datetime.timedelta(days=dias)).strftime("%Y%m%d")
        f = WD / "logs" / f"telemetria_{dia}.csv"
        if not f.exists():
            continue
        try:
            with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        ts = datetime.datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
                    except (KeyError, ValueError):
                        continue
                    if ts < desde:
                        continue

                    def num(k):
                        try:
                            return float(r.get(k, "") or 0)
                        except ValueError:
                            return 0.0
                    muestras.append((ts, num("uptime_s"), num("gpu_temp_c"), num("gpu_util_pct"), num("cpu_pct")))
        except OSError:
            continue
    muestras.sort(key=lambda m: m[0])
    paso = paso_min * 60
    t0 = desde.timestamp()
    n = int(horas * 3600 // paso)
    tramos = [None] * n
    for ts, _up, temp, util, cpu in muestras:
        i = int((ts.timestamp() - t0) // paso)
        if 0 <= i < n:
            b = tramos[i] or {"t": 0.0, "u": 0.0, "c": 0.0, "k": 0}
            b["t"], b["u"] = max(b["t"], temp), max(b["u"], util)
            b["c"] += cpu
            b["k"] += 1
            tramos[i] = b
    puntos = [None if b is None else {"t": round(b["t"], 1), "u": round(b["u"]), "c": round(b["c"] / b["k"])} for b in tramos]
    cortes = []
    for a, b in zip(muestras, muestras[1:]):
        if b[1] < a[1]:
            cortes.append({"ts": b[0].timestamp(), "tipo": "reinicio"})
        elif (b[0] - a[0]).total_seconds() > 180:
            cortes.append({"ts": a[0].timestamp(), "hasta": b[0].timestamp(), "tipo": "hueco"})
    return {"desde": t0, "paso_s": paso, "puntos": puntos, "cortes": cortes[-40:], "muestras": len(muestras)}


def red():
    """Resumen de red: adaptador activo, wifi, latencias y estado de Mullvad."""
    out = []
    ad = _ps("Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object { '{0} ({1}) {2}' -f $_.Name,$_.InterfaceDescription,$_.LinkSpeed }")
    out.append("Adaptadores activos:\n" + (ad or "ninguno"))
    wifi = _ps("netsh wlan show interfaces | Select-String 'SSID|Señal|Banda|Canal' | ForEach-Object { $_.Line.Trim() }")
    if wifi:
        out.append("Wi-Fi:\n" + wifi)
    gw = _ps("(Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Sort-Object RouteMetric | Select-Object -First 1).NextHop")
    lat = _ps(f"foreach($h in '{gw or '192.168.50.1'}','1.1.1.1'){{ $r=Test-Connection $h -Count 2 -EA SilentlyContinue; if($r){{ '{{0}}: {{1}} ms' -f $h,[math]::Round(($r|Measure-Object ResponseTime -Average).Average) }} else {{ '{{0}}: sin respuesta' -f $h }} }}")
    out.append("Latencia:\n" + lat)
    mv = _ps("$m=(Get-Command mullvad -EA SilentlyContinue).Source; if(!$m){$m='C:\\Program Files\\Mullvad VPN\\resources\\mullvad.exe'}; if(Test-Path $m){ & $m status 2>&1 | Select-Object -First 3 } else { 'Mullvad no encontrado' }")
    out.append("Mullvad:\n" + mv)
    return "\n\n".join(out)
