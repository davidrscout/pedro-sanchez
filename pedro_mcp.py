# -*- coding: utf-8 -*-
"""Herramientas propias de Pedro como servidor MCP (stdio). Lo arranca Claude Code con --mcp-config (ver jarvis.py).
Idea de adewaskar/jarvis (createSdkMcpServer) y OpenJarvis (tools/ + mcp/).

PEDRO_MODO=ask -> solo herramientas de lectura + memoria + agenda + aviso a Telegram (no tocan el PC).
PEDRO_MODO=do  -> además ratón, teclado, ventanas, lanzadores y cerrar procesos.
El token de Telegram NO pasa por aquí: los avisos van a la bandeja (agenda.py) y los manda jarvis.py."""
import io
import json
import os
import sys
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME))
os.chdir(HOME)

from mcp.server.mcpserver import MCPServer, Image  # noqa: E402

import agenda  # noqa: E402
import launchers  # noqa: E402
import memoria  # noqa: E402
import remoto  # noqa: E402
import sysinfo  # noqa: E402

MODO = os.environ.get("PEDRO_MODO", "ask")
VISION_ANCHO = 1280
mcp = MCPServer("pedro")


def _jarvis():
    import jarvis   # perezoso: solo para estado()/eventos()
    return jarvis


# ------------------------------------------------------------------ lectura (siempre)
@mcp.tool()
def estado_pc() -> str:
    """CPU, RAM, GPU (temperatura, consumo, VRAM), disco C:, tiempo encendido y watchdog del PC de David."""
    return _jarvis().estado()


@mcp.tool()
def eventos_graves() -> str:
    """Cuelgues, BSOD, WHEA y errores del driver de NVIDIA de las últimas 24 h (visor de eventos de Windows)."""
    return _jarvis().eventos()


@mcp.tool()
def procesos(n: int = 20) -> str:
    """Los n procesos que más memoria usan (pid, nombre, CPU %, MB) y las ventanas con título."""
    d = sysinfo.procesos(max(1, min(int(n), 60)))
    filas = [f"{p['pid']:>6} {p['name'][:28]:<28} cpu {p['cpu']:>5}% {p['mem_mb']:>6} MB" + (" [protegido]" if p["protegido"] else "")
             for p in d["top"]]
    return f"{d['total']} procesos. Top por memoria:\n" + "\n".join(filas)


@mcp.tool()
def ventanas_abiertas() -> str:
    """Ventanas visibles ahora mismo (id, título, si está activa o minimizada)."""
    vs = remoto.ventanas()
    return "\n".join(f"{v['id']}: {v['titulo']}" + (" [ACTIVA]" if v["activa"] else "") + (" [min]" if v["min"] else "")
                     for v in vs) or "(ninguna)"


@mcp.tool()
def ver_pantalla() -> Image:
    """Captura la pantalla principal y te la devuelve como imagen para que la VEAS. La imagen mide 1280 px de ancho;
    si luego quieres hacer clic, pasa a la herramienta clic las coordenadas EN PÍXELES DE ESTA IMAGEN.
    Si la sesión está bloqueada saldrá negra."""
    return Image(data=remoto.captura(VISION_ANCHO, 70), format="jpeg")


@mcp.tool()
def red() -> str:
    """Estado de la red: adaptadores, IP, VPN (Mullvad), latencia."""
    return sysinfo.red()


@mcp.tool()
def vigilante() -> str:
    """Estado del watchdog de cuelgues del PC (latido, sesiones, eventos recientes)."""
    return json.dumps(sysinfo.watchdog(), ensure_ascii=False, default=str)[:4000]


@mcp.tool()
def lanzadores() -> str:
    """Lista de lanzadores configurados (apps, webs, comandos del VPS...). Con modo actuar puedes ejecutarlos por id."""
    d = launchers.lista_publica()
    return "\n".join(f"{i['id']} [{i['grupo']}/{i['tipo']}] {i['label']}" + (" (pide confirmación)" if i["confirmar"] else "")
                     for i in d["items"])


# ------------------------------------------------------------------ memoria y agenda (siempre)
@mcp.tool()
def recordar(hecho: str, tema: str = "general") -> str:
    """Guarda un hecho DURADERO sobre David o sus cosas para futuras conversaciones (preferencias, datos de proyectos,
    decisiones). Una frase autosuficiente. Nunca claves, contraseñas, PIN ni tokens."""
    return memoria.recordar(hecho, tema)


@mcp.tool()
def olvidar(id: str) -> str:
    """Borra de la memoria el hecho con ese id (los ids salen en tu prompt de sistema)."""
    return memoria.olvidar(id)


@mcp.tool()
def programar(cuando: str, texto: str, tipo: str = "aviso", repetir: str = "no") -> str:
    """Programa un recordatorio o una tarea.
    cuando: 'YYYY-MM-DD HH:MM', 'HH:MM' (próxima vez que llegue esa hora) o '+30' (minutos) / '+2h'.
    tipo: 'aviso' (manda el texto a David por Telegram) o 'tarea' (a esa hora Pedro ejecuta el texto como pregunta de
    solo lectura y manda la respuesta; p. ej. 'resumen del estado del PC y eventos de la noche').
    repetir: no | diario | laborables | semanal | cada:<minutos>."""
    return agenda.crear(cuando, texto, tipo, repetir)


@mcp.tool()
def agenda_listar() -> str:
    """Recordatorios y tareas programadas pendientes."""
    its = agenda.listar()
    return "\n".join(f"{i['id']}: {i['cuando']} [{i['tipo']}, {i['repetir']}] {i['texto'][:120]}" for i in its) or "(agenda vacía)"


@mcp.tool()
def agenda_borrar(id: str) -> str:
    """Borra un recordatorio o tarea por id."""
    return agenda.borrar(id)


@mcp.tool()
def avisar_telegram(texto: str) -> str:
    """Manda un mensaje a David por Telegram (p. ej. cuando acabe algo largo). Úsalo con moderación."""
    return agenda.encolar(texto)


# ------------------------------------------------------------------ actuar (solo modo do)
if MODO == "do":
    def _px(x, y):
        w, h = remoto.pantalla_size()
        alto = round(h * VISION_ANCHO / w)
        return max(0.0, min(1.0, float(x) / (VISION_ANCHO - 1))), max(0.0, min(1.0, float(y) / max(1, alto - 1)))

    @mcp.tool()
    def clic(x: float, y: float, boton: str = "izq", doble: bool = False) -> str:
        """Clic en (x, y) EN PÍXELES de la última imagen de ver_pantalla (1280 de ancho). boton: izq|der|medio.
        Después vuelve a llamar a ver_pantalla para comprobar el resultado."""
        nx, ny = _px(x, y)
        remoto.raton({"accion": "doble" if doble else "clic", "x": nx, "y": ny, "boton": boton})
        time.sleep(0.4)
        return "ok"

    @mcp.tool()
    def rueda(pasos: int) -> str:
        """Gira la rueda del ratón donde esté la flecha: positivo = arriba, negativo = abajo (1 paso = 1 muesca)."""
        remoto.raton({"accion": "rueda", "delta": max(-10, min(10, int(pasos))) * 120})
        return "ok"

    @mcp.tool()
    def escribir_texto(texto: str) -> str:
        """Teclea el texto en la ventana con foco (como si lo escribiera David)."""
        return remoto.escribir(texto[:4000])

    @mcp.tool()
    def atajo(teclas: list[str]) -> str:
        """Pulsa una combinación: p. ej. ['ctrl','c'], ['alt','tab'], ['win','d'], ['enter']. Nombres válidos: enter esc tab
        retroceso borrar espacio izq arriba der abajo inicio fin repag avpag ctrl alt shift win f1..f12 o una letra."""
        return remoto.combo(teclas)

    @mcp.tool()
    def ventana(id: int, accion: str) -> str:
        """Actúa sobre una ventana de ventanas_abiertas: foco | min | max | restaurar | cerrar (cerrar = como la X)."""
        return remoto.ventana(id, accion)

    @mcp.tool()
    def lanzar(id: str) -> str:
        """Ejecuta un lanzador por id (ver lanzadores). Las webs se abren en el Chrome del PC."""
        return launchers.ejecutar(id, True, "pc").get("text", "")

    @mcp.tool()
    def cerrar_proceso(pid: int) -> str:
        """Cierra un proceso por pid (no deja cerrar los del sistema ni los de Pedro)."""
        return sysinfo.matar(int(pid))


if __name__ == "__main__":
    mcp.run()
