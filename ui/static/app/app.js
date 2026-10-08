/* 09/10: nombre del usuario (JARVIS_NOMBRE en .env); vacío = sin nombre */
const CON_NOMBRE = (n => n ? ", " + n : "")((document.documentElement.dataset.nombre || "").trim());
/* Pulso del PC · aplicación (fase 2). Sin dependencias.
   Contratos con el servidor (webpanel.py): POST /api/<acción> con cabecera X-Jarvis: 1; GET /api/job/<id>; POST /logout.
   Todo lo que viene del servidor se pinta con textContent. localStorage solo guarda preferencias no sensibles
   (cerebro, modo, leer en voz alta). Ningún PIN ni token sale de la cookie HttpOnly. */
"use strict";
(() => {
const P = window.Pulso, F = P.fmt, clamp = P.clamp;
const RM = matchMedia("(prefers-reduced-motion: reduce)");
const TOUCH = matchMedia("(pointer: coarse)").matches;
const $ = id => document.getElementById(id);
const PC = "PC limpio";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const NF = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });

/* ---------- DOM: h(tag, attrs, ...hijos). Texto siempre como nodo de texto ---------- */
function h(tag, a, ...kids) {
  const el = document.createElement(tag);
  if (a) for (const k in a) {
    const v = a[k]; if (v == null || v === false) continue;
    if (k === "text") el.textContent = String(v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
/* iconos: constantes propias (nunca datos del servidor) */
const IC = { refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>', copy: '<rect x="8" y="8" width="12" height="12"/><path d="M16 8V4H4v12h4"/>',
  lock: '<rect x="5" y="11" width="14" height="9"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>' };
function ic(n) { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.innerHTML = IC[n]; return s; }
const LS = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, String(v)); } catch (e) { } } };

/* ---------- sesión y API ---------- */
class NetErr extends Error {} class AuthErr extends Error {}
const timers = new Set();                       /* para poder parar todo al cerrar la sesión */
const later = (fn, ms) => { const t = setTimeout(() => { timers.delete(t); fn(); }, ms); timers.add(t); return t; };
const Session = { dead: false,
  end(kind) {
    if (this.dead) return; this.dead = true;
    try { P.tick = P.tickWd = function () {}; clearTimeout(P._t); clearTimeout(P._w); } catch (e) { }
    timers.forEach(clearTimeout); timers.clear(); Pollers.forEach(p => p.stop());
    Mando.cerrar(); Hoja.cerrarTodas(); Conv.parar(); Voz.parar(); desmontar();
    const tt = kind === "cerrada" ? "Sesión cerrada" : "Sesión caducada";
    const tx = kind === "cerrada" ? "Hasta luego" + CON_NOMBRE + ". Para volver, pide otro enlace con /web en Telegram."
      : "Por seguridad la sesión se ha cerrado. Pide otro enlace con /web en Telegram.";
    const box = h("div", { class: "fin", role: "alertdialog", "aria-modal": "true", "aria-labelledby": "finT" }, h("div", null, h("h2", { id: "finT", tabindex: "-1", text: tt }), h("p", { text: tx })));
    ["main", "top"].forEach(id => { const e = id === "main" ? document.querySelector("main") : $(id); e && e.setAttribute("inert", ""); });
    document.body.append(box); box.querySelector("h2").focus();
  } };
async function req(path, opt, ms) {
  if (Session.dead) throw new AuthErr("sesión");
  const ac = new AbortController(), to = setTimeout(() => ac.abort(), ms || 25000);
  let r;
  try { r = await fetch(path, Object.assign({ cache: "no-store", credentials: "same-origin", signal: ac.signal }, opt)); }
  catch (e) { throw new NetErr("Sin conexión con el PC."); }
  finally { clearTimeout(to); }
  if (r.status === 401) { Session.end("caducada"); throw new AuthErr("sesión"); }
  return r;
}
async function api(path, body, raw) {
  const r = await req(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Jarvis": "1" }, body: JSON.stringify(body || {}) });
  if (raw) { if (!r.ok) throw new Error("El PC respondió con un error (" + r.status + ")."); return r; }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j && j.error ? String(j.error) : "El PC respondió con un error (" + r.status + ").");
  return j;
}
async function apiGet(path) {
  const r = await req(path, { method: "GET", headers: { "X-Jarvis": "1" } });
  const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error("Error " + r.status); return j;
}
const errText = e => e instanceof NetErr ? "Sin conexión con el PC. Revisa la red y vuelve a intentarlo." : (e && e.message) || "Algo ha fallado.";
async function pollJob(id, onTick, max) {
  const t0 = Date.now(); let fails = 0;
  for (;;) {
    await sleep(1200); if (Session.dead) throw new AuthErr("sesión");
    onTick && onTick(Date.now() - t0);
    try { const s = await apiGet("/api/job/" + encodeURIComponent(id)); fails = 0;
      if (s.state === "done") return s;
      if (s.state === "none") throw new Error("La tarea se ha perdido (¿se reinició el asistente en el PC?)."); }
    catch (e) { if (e instanceof AuthErr) throw e; if (e instanceof NetErr && ++fails < 6) { await sleep(1000 * 2 ** fails); continue; } throw e; }
    if (max && Date.now() - t0 > max) throw new Error("Sin respuesta tras " + Math.round(max / 1000) + " s; puede que siga ejecutándose en el PC.");
  }
}
/* sondeo con reintento exponencial; se para con la pestaña oculta y al cerrar la sesión */
const Pollers = [];
function poller(fn, every) {
  let t = 0, fails = 0, on = false, busy = false;
  const p = {
    async run() { clearTimeout(t); if (!on || Session.dead) return; if (document.hidden) return;
      if (!busy) { busy = true; try { await fn(); fails = 0; } catch (e) { if (e instanceof AuthErr) return; fails++; } busy = false; }
      if (on && !Session.dead) t = setTimeout(() => p.run(), fails ? Math.min(every * 2 ** fails, 300000) : every); },
    start() { if (on) return; on = true; p.run(); }, stop() { on = false; clearTimeout(t); }, now() { if (on) p.run(); else fn().catch(() => {}); },
    get on() { return on; } };
  Pollers.push(p); return p;
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) Pollers.forEach(p => p.on && p.run()); });

/* ---------- avisos ---------- */
function toast(text, kind, ms) {
  if (Session.dead) return; const box = $("toasts");
  const t = h("div", { class: "toast " + (kind || ""), text }); box.append(t);
  while (box.children.length > 3) box.firstChild.remove();
  requestAnimationFrame(() => t.classList.add("on"));
  setTimeout(() => { t.classList.remove("on"); setTimeout(() => t.remove(), 240); }, ms || 3800);
}
async function copiar(txt) {
  try { await navigator.clipboard.writeText(txt); toast("Copiado.", "ok", 1400); }
  catch (e) { const ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = txt; document.body.append(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (_) { } ta.remove(); toast(ok ? "Copiado." : "No se pudo copiar.", ok ? "ok" : "warn", 1600); }
}

/* ---------- hojas (diálogos desde abajo) con foco atrapado y devuelto ---------- */
const Hoja = { pila: [],
  open({ titulo, texto, cuerpo, acciones, modal = true, clase = "", onClose }) {
    const prev = document.activeElement, id = "hj" + Math.random().toString(36).slice(2, 7);
    const cerrarB = h("button", { class: "ico", type: "button", "aria-label": "Cerrar" }, ic("x"));
    const el = h("div", { class: "hoja " + clase, role: "dialog", "aria-modal": modal ? "true" : null, "aria-labelledby": id },
      h("div", { class: "in" }, h("div", { class: "cab" }, h("h2", { id, tabindex: "-1", text: titulo }), cerrarB),
        texto ? h("p", { text: texto }) : null, cuerpo || null, acciones && acciones.length ? h("div", { class: "pie" }, acciones) : null));
    const velo = modal ? h("div", { class: "velo" }) : null;
    const o = { el, cerrado: false,
      close(v) { if (o.cerrado) return; o.cerrado = true; Hoja.pila.splice(Hoja.pila.indexOf(o), 1);
        el.classList.remove("on"); velo && velo.classList.remove("on"); document.removeEventListener("keydown", kd, true);
        setTimeout(() => { el.remove(); velo && velo.remove(); }, RM.matches ? 0 : 240);
        if (modal) { ["main", "top"].forEach(x => { const e = x === "main" ? document.querySelector("main") : $(x); e && e.removeAttribute("inert"); });  }
        try { prev && prev.focus && prev.focus({ preventScroll: true }); } catch (e) { } onClose && onClose(v); } };
    const kd = e => {
      if (Hoja.pila[Hoja.pila.length - 1] !== o) return;
      if (e.key === "Escape") { e.preventDefault(); o.close(false); }
      if (e.key === "Tab" && modal) { const f = [...el.querySelectorAll("button,[href],textarea,input,[tabindex]:not([tabindex='-1'])")].filter(x => !x.disabled && x.offsetParent);
        if (!f.length) return; const a = f[0], z = f[f.length - 1];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); } else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); } } };
    document.addEventListener("keydown", kd, true);
    cerrarB.addEventListener("click", () => o.close(false));
    if (velo) { velo.addEventListener("click", () => o.close(false)); document.body.append(velo);
      ["main", "top"].forEach(x => { const e = x === "main" ? document.querySelector("main") : $(x); e && e.setAttribute("inert", ""); });  }
    document.body.append(el); Hoja.pila.push(o);
    requestAnimationFrame(() => { el.classList.add("on"); velo && velo.classList.add("on"); (el.querySelector("[data-autofocus]") || el.querySelector("h2")).focus({ preventScroll: true }); });
    return o;
  },
  cerrarTodas() { [...this.pila].forEach(o => o.close(false)); } };

/* ---------- interruptor con TAPA ROJA de seguridad: levantar la tapa y luego accionar ---------- */
function Tapa(accion, onOk) {
  const pal = h("button", { class: "palanca", type: "button", disabled: true, tabindex: "-1", "aria-label": "Accionar: " + accion }, h("i", { "aria-hidden": "true" }), h("span", { text: accion }));
  const cub = h("button", { class: "cubierta", type: "button", "aria-expanded": "false", "data-autofocus": "" }, "Levanta la tapa", h("span", { text: "para poder " + accion.toLowerCase() }));
  const ay = h("p", { class: "ay", text: "Paso 1 de 2: levanta la tapa roja." });
  const el = h("div", { class: "tapa" }, h("div", { class: "caja" }, pal, cub), ay);
  let t = 0, hecho = false;
  const cerrar = () => { if (hecho) return; el.classList.remove("abierta"); cub.setAttribute("aria-expanded", "false"); cub.removeAttribute("aria-hidden"); delete cub.dataset.lcIgnore; pal.disabled = true; pal.tabIndex = -1; cub.tabIndex = 0;
    ay.textContent = "La tapa se ha vuelto a cerrar. Levántala otra vez si quieres seguir."; };
  cub.addEventListener("click", () => {
    el.classList.add("abierta"); cub.setAttribute("aria-expanded", "true"); cub.tabIndex = -1; cub.setAttribute("aria-hidden", "true"); cub.dataset.lcIgnore = ""; pal.disabled = false; pal.tabIndex = 0;
    ay.textContent = "Paso 2 de 2: acciona el interruptor para " + accion.toLowerCase() + ". Se vuelve a cerrar sola en 8 s.";
    try { navigator.vibrate && navigator.vibrate(12); } catch (e) { }
    pal.focus({ preventScroll: true }); clearTimeout(t); t = setTimeout(cerrar, 8000);
  });
  pal.addEventListener("click", () => {
    if (pal.disabled || hecho) return; hecho = true; clearTimeout(t); pal.classList.add("hecha"); pal.disabled = true;
    try { navigator.vibrate && navigator.vibrate([20, 40, 30]); } catch (e) { }
    ay.textContent = "Accionado."; setTimeout(onOk, RM.matches ? 0 : 200);
  });
  el._limpia = () => clearTimeout(t);
  return el;
}
function confirmar({ titulo, texto, detalle, accion, onOk }) {
  let o = null;
  const tapa = Tapa(accion, () => { o && o.close(true); onOk(); });
  o = Hoja.open({ titulo, texto, cuerpo: h("div", null, detalle ? h("div", { class: "det", text: detalle }) : null, tapa),
    acciones: [h("button", { class: "bt", type: "button", onclick: () => o.close(false) }, "No, volver")], onClose: () => tapa._limpia() });
  return o;
}

/* ---------- navegación ---------- */
const VISTAS = ["hablar", "pantalla", "control", "lanzar", "pulso"];
const alMostrar = {}; let vista = "unica";
function ir(v) {
  if (v === "hablar" && Chat && Chat.textarea && document.activeElement === Chat.textarea) v = "conv";
  const el = $("v-" + v); if (!el) return;
  el.scrollIntoView({ behavior: RM.matches ? "auto" : "smooth", block: "start" });
  (alMostrar[v] || []).forEach(f => f());
}
document.addEventListener("click", e => { const b = e.target.closest("[data-ir]"); if (b) ir(b.dataset.ir); });
const on = (v, f) => (alMostrar[v] = alMostrar[v] || []).push(f);

/* =============================== PULSO =============================== */
document.documentElement.classList.add("js");
let D = null, calorV = 0, titActual = "", rebootHasta = 0;
/* titulares: cada palabra sube desde una máscara (se reutiliza en los h1 de las pestañas y en las respuestas de Pedro) */
function palabras(el, texto, d0) {
  el.textContent = ""; let i = 0;
  for (const w of String(texto).split(/\s+/)) { if (!w) continue;
    const m = document.createElement("span"), t = document.createElement("span"); m.className = "w"; t.textContent = w;
    if (/\d/.test(w)) t.className = "d"; t.style.setProperty("--i", Math.min(i++, 16)); if (d0) t.style.setProperty("--d", d0 + "ms");
    m.append(t); el.append(m, " "); }
}
function animaH1(sec) { const x = sec && sec.querySelector(".gigante"); if (!x) return; if (!x.dataset.t) x.dataset.t = x.textContent; palabras(x, x.dataset.t); }
function titularDe(d) {
  if (P.lost) return "Sin señal.";
  if (Date.now() < rebootHasta) return "Ha vuelto.";
  const g = (d && d.gpu) || {};
  if (g.t >= 82) return "Está ardiendo.";
  if (g.t >= 70) return "Caliente y a tope.";
  if (g.u >= 50 || d.cpu >= 70) return "Trabajando a tope.";
  if (g.u >= 15 || d.cpu >= 35) return "Trabajando.";
  return "Todo en orden" + CON_NOMBRE + ".";
}
function pintaTitular(d) { const t = titularDe(d); if (t === titActual) return; const primera = !titActual; titActual = t; palabras($("titular"), t, primera ? 500 : 0); }
function atmosfera(t) {
  calorV = t == null ? 0 : clamp((t - 30) / 50, 0, 1);
  document.documentElement.style.setProperty("--calor", calorV.toFixed(3));
  document.body.classList.toggle("caliente", t != null && t >= 70 && t < 82); document.body.classList.toggle("ardiendo", t != null && t >= 82);
}
/* el número cuenta hasta el valor real (desde 0 la primera vez) */
let nShown = null, nAnim = 0;
function muestraNum(v) {
  const el = $("sv"); if (v == null) { el.textContent = "—"; nShown = null; return; }
  const to = Math.round(v), from = nShown == null ? 0 : nShown; if (to === from && nShown != null) { el.textContent = String(to); return; }
  cancelAnimationFrame(nAnim); if (RM.matches) { el.textContent = String(to); nShown = to; return; }
  const t0 = performance.now(), dur = nShown == null ? 1700 : 800, ret = nShown == null ? 700 : 0;
  const st = t => { const p = clamp((t - t0 - ret) / dur, 0, 1), e = 1 - Math.pow(1 - p, 4); const cur = Math.round(from + (to - from) * e);
    el.textContent = String(p <= 0 && nShown == null ? 0 : cur); if (p > 0) nShown = cur; if (p < 1) nAnim = requestAnimationFrame(st); else nShown = to; };
  nAnim = requestAnimationFrame(st);
}
function pintaHechos(d) {
  const g = d.gpu || {}, box = $("hechos"); box.textContent = "";
  const add = (k, v) => box.append(h("span", null, k + " ", h("b", { text: v })));
  if (g.u != null) add("Carga", F.n0(g.u) + " %"); if (g.w != null) add("Consumo", F.n0(g.w) + " W"); if (d.up != null) add("Encendido hace", F.up(d.up));
}
const barra = (id, f) => $(id).style.setProperty("--fx", clamp(f || 0, 0, 1).toFixed(3));
function conUnidad(id, v, sub) { const e = $(id); e.textContent = v; if (sub) e.append(h("small", { text: sub })); }
function pintaPulso(d) {
  const g = d.gpu || {};
  muestraNum(g.t != null ? g.t : null); $("sn").textContent = g.t != null ? "grados" : "";
  atmosfera(g.t != null ? g.t : null); pintaTitular(d); pintaHechos(d);
  conUnidad("r-gu", g.u != null ? F.n0(g.u) + " %" : "—"); barra("h-gu", (g.u || 0) / 100);
  conUnidad("r-gw", g.w != null ? F.n0(g.w) + " W" : "—"); barra("h-gw", (g.w || 0) / 180);
  conUnidad("r-vr", g.vt ? F.gb(g.vu) : "—", g.vt ? "de " + F.n0(g.vt / 1024) + " GB" : ""); barra("h-vr", g.vt ? g.vu / g.vt : 0);
  conUnidad("r-cpu", d.cpu != null ? F.n0(d.cpu) + " %" : "—"); barra("h-cpu", (d.cpu || 0) / 100);
  conUnidad("r-ram", d.ramFree != null ? F.gb(d.ramFree) : "—", d.ramTot ? "de " + F.n0(d.ramTot / 1024) + " GB" : ""); barra("h-ram", d.ramTot ? 1 - d.ramFree / d.ramTot : 0);
  conUnidad("r-dk", d.disk ? F.n0(d.disk.free) : "—", d.disk ? "GB libres" : ""); barra("h-dk", d.disk ? clamp(1 - d.disk.free / 500, 0, 1) : 0);
  P.pinta($("frase"), P.frase(d, P.wd));
  pintaLatido();
  const l = $("lat"); l.classList.remove("beat"); void l.offsetWidth; l.classList.add("beat");
}
function pintaLatido() {
  const d = D, w = P.wd, t = $("latT"); t.textContent = "";
  t.append(h("b", { text: d && d.wd ? (d.wd.ok ? "Vigilante activo, latido hace " + (d.wd.age != null ? d.wd.age : "?") + " s." : "Vigilante PARADO.") : "Vigilante sin datos." }));
  if (w && w.hoy && w.hoy.gpu_temp_max != null) t.append(" Máximo de hoy: " + F.n0(w.hoy.gpu_temp_max) + " °C.");
}
function aviso(txt, ms) { const a = $("aviso"); a.textContent = txt; a.classList.add("on"); clearTimeout(a._t); a._t = later(() => a.classList.remove("on"), ms || 7000); }

/* brasas: partículas que suben, más rápido cuanto más calor. Se para fuera de Pulso, con la pestaña oculta o con movimiento reducido */
const Polvo = (() => {
  const cv = $("polvo"), cx = cv.getContext("2d"); let W = 0, H = 0, dpr = 1, raf = 0, run = false, ps = [], last = 0;
  const cuantas = () => (innerWidth < 700 ? 44 : 84);
  function medir() { dpr = Math.min(2, devicePixelRatio || 1); const r = cv.getBoundingClientRect(); W = r.width; H = r.height; cv.width = Math.max(1, W * dpr); cv.height = Math.max(1, H * dpr); }
  const nueva = azar => ({ x: Math.random() * W, y: azar ? Math.random() * H : H + 12, r: .5 + Math.random() * 1.7, v: 7 + Math.random() * 15, dx: (Math.random() - .5) * 8, a: .25 + Math.random() * .6, f: Math.random() * 6.28 });
  function frame(t) {
    if (!run) return; raf = requestAnimationFrame(frame);
    const dt = Math.min(.05, (t - last) / 1000); last = t;
    cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, W, H); cx.globalCompositeOperation = "lighter";
    const sin = document.body.classList.contains("sin"), k = sin ? 0 : .5 + calorV * 2.4;
    for (const p of ps) {
      p.y -= p.v * k * dt; p.x += p.dx * dt + Math.sin(t / 1600 + p.f) * .18;
      if (p.y < -12) Object.assign(p, nueva(false));
      const al = p.a * (.55 + .45 * Math.sin(t / 700 + p.f)) * (sin ? .25 : 1);
      cx.fillStyle = "rgba(" + Math.round(150 + 90 * calorV) + "," + Math.round(195 + 40 * calorV) + ",255," + al.toFixed(3) + ")";
      cx.beginPath(); cx.arc(p.x, p.y, p.r, 0, 6.2832); cx.fill();
    }
  }
  return {
    start() { if (run || RM.matches || document.hidden || Session.dead) return; medir(); ps = Array.from({ length: cuantas() }, () => nueva(true)); run = true; last = performance.now(); raf = requestAnimationFrame(frame); },
    stop() { run = false; cancelAnimationFrame(raf); cx.clearRect(0, 0, cv.width, cv.height); },
    medir } })();
let heroVisible = false;
function montar() { if (heroVisible) Polvo.start(); }
if ("IntersectionObserver" in window) new IntersectionObserver(es => { heroVisible = es[0].isIntersecting; heroVisible ? montar() : Polvo.stop(); }).observe($("hero"));
function desmontar() { Polvo.stop(); }
addEventListener("resize", () => { if (heroVisible) { Polvo.stop(); Polvo.start(); } });
document.addEventListener("visibilitychange", () => { document.hidden ? Polvo.stop() : montar(); });
/* paralaje: la foto se queda atrás y el titular se va antes que el resto al bajar */
let rafScroll = 0;
addEventListener("scroll", () => { if (vista !== "pulso" || rafScroll || RM.matches) return;
  rafScroll = requestAnimationFrame(() => { rafScroll = 0; const y = scrollY, hh = innerHeight;
    $("hero").querySelector(".fondo").style.transform = "translate3d(0," + (y * .24).toFixed(1) + "px,0)";
    const tx = $("hero").querySelector(".texto"); tx.style.transform = "translate3d(0," + (-y * .1).toFixed(1) + "px,0)"; tx.style.opacity = clamp(1 - y / (hh * .62), 0, 1).toFixed(3); }); }, { passive: true });
/* aparición al hacer scroll */
const io = "IntersectionObserver" in window ? new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: .12, rootMargin: "0px 0px -6% 0px" }) : null;
document.querySelectorAll(".rev").forEach((e, i) => { e.style.setProperty("--rd", (i % 3) * 90 + "ms"); io ? io.observe(e) : e.classList.add("in"); });

/* ---------- Sismograma: las últimas 24 h (POST /api/serie). Una barra por tramo de 5 min, coloreada con la rampa de brasa ---------- */
const RAMPA = [[0, [18, 22, 46]], [.2, [36, 58, 140]], [.45, [91, 168, 255]], [.65, [167, 139, 250]], [.85, [255, 128, 200]], [1, [255, 255, 255]]];
function colorTemp(t) {
  const x = clamp((t - 20) / 65, 0, 1); let i = 1; while (i < RAMPA.length - 1 && RAMPA[i][0] < x) i++;
  const [x0, a] = RAMPA[i - 1], [x1, b] = RAMPA[i], k = (x - x0) / (x1 - x0);
  return "rgb(" + a.map((v, j) => Math.round(v + (b[j] - v) * k)).join(",") + ")";
}
let SM = null;
function sNS(tag, a) { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const k in a) e.setAttribute(k, String(a[k])); return e; }
function lecturaSismo(i) {
  const p = SM.puntos[i], hh = F.hora((SM.desde + i * SM.paso_s) * 1000);
  return p ? hh + ": gráfica a " + NF.format(p.t) + " °C, al " + p.u + " % de carga; procesador al " + p.c + " %." : hh + ": sin datos (el PC estaba apagado o sin respuesta).";
}
function pintaSismo(s) {
  SM = s; const svg = $("sm-svg"); svg.textContent = "";
  const pts = s.puntos || [], n = pts.length; if (!n || !s.muestras) { $("sismo").hidden = true; return; }
  $("sismo").hidden = false;
  svg.setAttribute("viewBox", "0 0 " + n + " 60");
  let max = null, maxI = -1, hueco = 0;
  pts.forEach((p, i) => {
    if (!p) { hueco++; svg.append(sNS("rect", { class: "hu", x: i, y: 57, width: 1, height: 3 })); return; }
    const hgt = Math.max(2, clamp((p.t - 20) / 65, 0, 1) * 56);
    svg.append(sNS("rect", { class: "b", x: i, y: 60 - hgt, width: 1.02, height: hgt, fill: colorTemp(p.t) }));
    if (max == null || p.t > max) { max = p.t; maxI = i; }
  });
  let reinicios = 0;
  (s.cortes || []).forEach(c => { if (c.tipo !== "reinicio") return; const x = (c.ts - s.desde) / s.paso_s; if (x < 0 || x > n) return; reinicios++;
    svg.append(sNS("line", { class: "rb", x1: x, x2: x, y1: 0, y2: 60 })); });
  const sel = sNS("line", { class: "sel", x1: -5, x2: -5, y1: 0, y2: 60 }); svg.append(sel);
  const base = (max != null ? "Máximo " + NF.format(max) + " °C a las " + F.hora((s.desde + maxI * s.paso_s) * 1000) + ". " : "") +
    (reinicios ? reinicios + (reinicios === 1 ? " reinicio" : " reinicios") + " (línea blanca). " : "Sin reinicios. ") +
    (hueco ? "Unas " + NF.format(Math.round(hueco * s.paso_s / 360) / 10) + " h sin datos." : "");
  const lg = $("sm-lg"); lg.textContent = base; $("sm-sr").textContent = base;
  $("sm-a0").textContent = F.hora(s.desde * 1000); $("sm-a1").textContent = F.hora((s.desde + n * s.paso_s / 2) * 1000);
  const mueve = e => { const r = svg.getBoundingClientRect(); const i = clamp(Math.floor((e.clientX - r.left) / r.width * n), 0, n - 1);
    sel.setAttribute("x1", i + .5); sel.setAttribute("x2", i + .5); lg.textContent = lecturaSismo(i); };
  svg.onpointermove = mueve; svg.onpointerdown = mueve;
  svg.onpointerleave = () => { sel.setAttribute("x1", -5); sel.setAttribute("x2", -5); lg.textContent = base; };
}
const pollSismo = poller(async () => { pintaSismo(await api("/api/serie")); }, 300000); pollSismo._vista = "pulso";

P.on("data", d => { D = d; document.body.classList.remove("sin"); $("sinsenal").hidden = true; pintaPulso(d); });
P.on("wd", w => { if (D) P.pinta($("frase"), P.frase(D, w)); pintaLatido(); pintaVig(w); });
P.on("lost", ({ since }) => {
  document.body.classList.add("sin"); $("sinsenal").hidden = false; atmosfera(null); pintaTitular(D || {});
  $("ult").textContent = "Última lectura a las " + F.hora(since) + ".";
  $("latT").textContent = "Sin latido desde las " + F.hora(since) + ".";
});
P.on("back", ({ reboot }) => {
  if (reboot) { rebootHasta = Date.now() + 9000; later(() => D && pintaTitular(D), 9200);
    const n = P.wd && P.wd.hoy ? P.wd.hoy.arranques_hoy + 1 : null; aviso("El PC se ha reiniciado." + (n ? " Van " + n + " arranques hoy." : ""), 9000); }
  P.tickWd();
});
P.on("auth", () => Session.end("caducada"));
setInterval(() => { if (document.hidden || Session.dead) return; const el = $("fresco");
  if (P.lost) el.textContent = "sin respuesta";
  else if (P.lastOk) { const s = Math.round((Date.now() - P.lastOk) / 1000); el.textContent = s < 2 ? "lectura ahora" : "lectura hace " + s + " s"; } }, 1000);

/* =============================== HABLAR =============================== */
const Chat = (() => {
  let cerebros = [], cerebro = LS.get("jv_brain", "claude"), modo = LS.get("jv_mode", "ask") === "do" ? "do" : "ask", cargado = false;
  const box = $("cerebros"), ta = $("ta"), env = $("enviar"), log = $("log"), vacio = $("vacio"), comp = $("comp");
  const HINT = { ask: "Leer: solo mira y planifica; no toca nada del PC.", do: "Actuar: hace cambios en el PC sin pedir permisos. Antes te pediré levantar la tapa roja." };
  const nombre = id => { const b = cerebros.find(x => x.id === id); return b ? String(b.nombre || id).replace(/\s*\(.*\)\s*$/, "") : id; };
  function pintaCerebros() {
    box.textContent = "";
    for (const b of cerebros) {
      const ok = b.ok !== false, nm = String(b.nombre || b.id).replace(/\s*\(.*\)\s*$/, "");
      const el = h("button", { type: "button", role: "radio", "data-id": String(b.id), "aria-checked": String(b.id === cerebro), tabindex: b.id === cerebro ? "0" : "-1", disabled: !ok },
        h("b", { text: nm }), h("span", { text: ok ? String(b.nota || "") : "no disponible" + (b.nota ? ": " + b.nota : "") }));
      el.addEventListener("click", () => elegir(b.id));
      el.addEventListener("keydown", e => { if (!/Arrow(Left|Right)/.test(e.key)) return; e.preventDefault();
        const oks = cerebros.filter(x => x.ok !== false); let i = oks.findIndex(x => x.id === cerebro);
        i = (i + (e.key === "ArrowRight" ? 1 : -1) + oks.length) % oks.length; elegir(oks[i].id); box.querySelector('[data-id="' + oks[i].id + '"]').focus(); });
      box.append(el);
    }
  }
  function elegir(id, quieto) {
    const b = cerebros.find(x => x.id === id); if (!b || b.ok === false) return false;
    cerebro = id; LS.set("jv_brain", id);
    box.querySelectorAll("button").forEach(x => { const s = x.dataset.id === id; x.setAttribute("aria-checked", String(s)); x.tabIndex = s ? 0 : -1; });
    if (!quieto && id === "local") toast("La primera respuesta de la IA local puede tardar 30-120 s mientras se carga en la gráfica.", "", 4200);
    return true;
  }
  function setModo(m) {
    modo = m; LS.set("jv_mode", m);
    $("modos").querySelectorAll("button").forEach(b => { const s = b.dataset.modo === m; b.setAttribute("aria-checked", String(s)); b.tabIndex = s ? 0 : -1; });
    $("mhint").textContent = HINT[m]; $("mhint").classList.toggle("hz", m === "do"); comp.classList.toggle("hz", m === "do");
    ta.placeholder = m === "do" ? "¿Qué quieres que haga en el PC?" : "Dile algo a Pedro";
  }
  $("modos").querySelectorAll("button").forEach(b => {
    b.addEventListener("click", () => setModo(b.dataset.modo));
    b.addEventListener("keydown", e => { if (!/Arrow/.test(e.key)) return; e.preventDefault(); const n = modo === "ask" ? "do" : "ask"; setModo(n); $("modos").querySelector('[data-modo="' + n + '"]').focus(); });
  });
  setModo(modo);
  async function cargar() {
    box.textContent = ""; for (let i = 0; i < 3; i++) box.append(h("button", { type: "button", disabled: true, "aria-label": "Cargando" }, h("b", { text: "…" }), h("span", { text: "consultando" })));
    try { const j = await api("/api/modelos"); cerebros = (Array.isArray(j.backends) ? j.backends : []).filter(b => b && b.id); }
    catch (e) { if (e instanceof AuthErr) return; cerebros = []; toast("No se pudo consultar quién está disponible: " + errText(e), "warn"); }
    if (!cerebros.length) cerebros = [{ id: "claude", nombre: "Claude Code", ok: true, nota: "Lista no disponible; uso el predeterminado." }];
    if (!cerebros.some(b => b.id === cerebro && b.ok !== false)) { const f = cerebros.find(b => b.ok !== false); cerebro = f ? f.id : cerebro; }
    pintaCerebros(); cargado = true;
  }
  on("hablar", () => { if (!cargado) cargar(); });
  const crece = () => { ta.style.height = "auto"; ta.style.height = Math.min(150, ta.scrollHeight) + "px"; ta.style.overflowY = ta.scrollHeight > 150 ? "auto" : "hidden"; env.disabled = !ta.value.trim(); };
  ta.addEventListener("input", crece);
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !TOUCH) { e.preventDefault(); comp.requestSubmit(); } });
  comp.addEventListener("submit", e => { e.preventDefault(); const p = ta.value.trim(); if (p) enviar(p); });
  vacio.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { setModo("ask"); enviar(b.textContent); }));
  function enviar(p) {
    if (!cargado) { toast("Un momento: consultando quién está disponible.", "", 2000); return; }
    const b = cerebros.find(x => x.id === cerebro); if (!b || b.ok === false) { toast("Elige quién contesta.", "warn"); return; }
    if (modo === "do") {
      confirmar({ titulo: "¿Actuar en el PC?", texto: "Actuará sin pedir permisos: puede crear, cambiar, borrar y ejecutar en el " + PC + ". Contesta " + nombre(cerebro) + ".",
        detalle: p, accion: "Actuar", onOk: () => correr(p, cerebro, "do") });
      return;
    }
    correr(p, cerebro, "ask");
  }
  async function correr(p, bk, md, op) {
    const voz = !!(op && op.voz);
    ta.value = ""; crece(); vacio.remove();
    log.append(h("div", { class: "m yo" }, h("p", { class: "quien", text: "Tú, a " + nombre(bk) + (md === "do" ? ", para actuar" : ", para leer") }), h("p", { class: "txt", text: p })));
    const tt = h("span", { text: md === "do" ? "Pedro está trabajando…" : "Pedro está pensando…" }), seg = h("span", { class: "num", text: " 0 s" });
    const lento = h("span", { class: "lento", hidden: true, text: "La primera vez puede tardar 30-120 s." });
    const parar = h("button", { class: "bt", type: "button", onclick: async () => { parar.disabled = true; try { const r = await api("/api/parar"); toast(r.text || "Parado.", "ok", 1800); } catch (e) { if (!(e instanceof AuthErr)) toast(errText(e), "err"); } } }, "Parar");
    const pens = h("div", { class: "pensando" }, h("span", null, tt, seg), h("div", { class: "calor", "aria-hidden": "true" }), lento, parar);
    const m = h("div", { class: "m pedro", "aria-busy": "true" }, h("p", { class: "quien", text: "Pedro con " + nombre(bk) }), pens);
    log.append(m); m.scrollIntoView({ block: "nearest", behavior: RM.matches ? "auto" : "smooth" });
    const t0 = Date.now(); let text = "", err = false;
    try {
      const body = { backend: bk, mode: md, prompt: p }; if (md === "do") body.confirm = true; if (voz) body.voz = true;
      const j = await api("/api/chat", body); if (!j.job) throw new Error(j.error || "El PC no devolvió una tarea.");
      const s = await pollJob(j.job, ms => { seg.textContent = " " + Math.round(ms / 1000) + " s";
        if (bk === "local" && ms > 6000 && lento.hidden) { tt.textContent = "Cargando la IA local en la GPU…"; lento.hidden = false; } });
      text = String(s.text || "(sin respuesta)");
      if (/^Error: /.test(text)) err = true;
    } catch (e) { if (e instanceof AuthErr) return { ok: false, text: "" }; err = true; text = errText(e); }
    pens.remove(); m.removeAttribute("aria-busy"); if (err) m.classList.add("err");
    const out = h("div", { class: "res" }); m.append(out);
    revela(out, text, err); later(() => m.scrollIntoView({ block: "nearest", behavior: RM.matches ? "auto" : "smooth" }), 160);
    const pie = h("div", { class: "pie" }, h("span", { class: "num", text: Math.round((Date.now() - t0) / 1000) + " s" }));
    if (!err) pie.append(h("button", { class: "bt", type: "button", onclick: () => copiar(text) }, ic("copy"), "Copiar"));
    m.append(pie);
    if (!err && !voz) Voz.decir(text);
    return { ok: !err, text };
  }
  async function hablar(p) {
    if (!cargado) await cargar();
    const b = cerebros.find(x => x.id === cerebro);
    if (!b || b.ok === false) { toast("Elige quién contesta.", "warn"); return { ok: false, text: "No hay nadie disponible para contestar." }; }
    return correr(p, cerebro, "ask", { voz: true });
  }
  /* respuesta tipográfica: la primera frase corta es el titular (sube palabra a palabra); el resto, texto normal */
  function revela(el, text, err) {
    const t = String(text).trim(), m = !err && t.match(/^([^\n]{3,72}?[.!?:])(?=\s|$)/), cuerpo = h("p", { class: "txt cuerpo" });
    if (m) { const tit = h("p", { class: "tit", "data-lc-ignore": "" }); palabras(tit, m[1].replace(/:$/, "."), 0); el.append(tit); cuerpo.textContent = t.slice(m[1].length).trim(); if (cuerpo.textContent) el.append(cuerpo); }
    else { cuerpo.textContent = t; el.append(cuerpo); }
  }
  function preparar({ prompt, backend, modo: md }) {
    ir("conv");
    const go = () => {
      if (backend && !elegir(String(backend), true) && cerebros.some(b => b.id === backend)) toast(nombre(backend) + " no está disponible; elige otro.", "warn");
      const mm = String(md || "").toLowerCase(); if (mm === "do" || mm === "actuar") setModo("do"); else if (mm === "ask" || mm === "leer") setModo("ask");
      $("txt-op").open = true; ta.value = prompt || ""; crece(); ta.focus({ preventScroll: true }); comp.scrollIntoView({ block: "end" });
      toast("Tarea preparada: revísala y pulsa Enviar.", "", 3200);
    };
    cargado ? go() : cargar().then(go);
  }
  return { preparar, hablar, cargar, textarea: ta, crece, get modo() { return modo; } };
})();

/* ---------- voz: oído (dictado del navegador) + habla (voz neuronal del PC; la del navegador, de reserva) ---------- */
const Voz = (() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition, sw = $("tts"), mic = $("mic");
  let leer = LS.get("jv_tts", "0") === "1", audio = null, token = 0, cortar = null;
  const SILENCIO = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
  sw.setAttribute("aria-checked", String(leer));
  sw.addEventListener("click", () => { leer = !leer; sw.setAttribute("aria-checked", String(leer)); LS.set("jv_tts", leer ? "1" : "0"); if (!leer) callar(); });

  /* Safari/iOS solo deja reproducir audio si el primer play() nace de un gesto: se "desbloquea" en el primer toque */
  function desbloquear() { actx(); try { if (!audio) audio = new Audio(); if (audio.dataset.ok) return; audio.dataset.ok = "1"; audio.src = SILENCIO; audio.play().catch(() => { delete audio.dataset.ok; }); } catch (e) { } }
  document.addEventListener("pointerdown", desbloquear, { once: true, passive: true });

  /* ---- oído del PC: graba aquí, Whisper transcribe en el PC (gratis y privado). Respaldo cuando el navegador no
     deja dictar (Safari con el Dictado apagado, navegadores sin SpeechRecognition) ---- */
  const LOCAL_OK = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  let usarLocal = !SR, micStream = null, micSuelta = 0;
  const MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find(m => { try { return MediaRecorder.isTypeSupported(m); } catch (e) { return false; } }) || "";
  async function abreMic() {
    clearTimeout(micSuelta);
    if (micStream && micStream.getAudioTracks().some(t => t.readyState === "live")) return micStream;
    micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    return micStream;
  }
  /* un solo AudioContext, despertado en un toque (Safari no deja medir el micro sin gesto) */
  let AC = null;
  function actx() { try { if (!AC) { const K = window.AudioContext || window.webkitAudioContext; if (!K) return null; AC = new K(); } if (AC.state === "suspended") AC.resume().catch(() => { }); } catch (e) { return null; } return AC; }
  function sueltaMic() { clearTimeout(micSuelta); micSuelta = setTimeout(() => { try { micStream && micStream.getTracks().forEach(t => t.stop()); } catch (e) { } micStream = null; }, 45000); }
  async function transcribe(blob) {
    const r = await req("/api/stt", { method: "POST", headers: { "Content-Type": (blob.type || "audio/webm").split(";")[0], "X-Jarvis": "1" }, body: blob }, 60000);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "No pude transcribir.");
    return String(j.text || "").trim();
  }
  function oirLocal({ continuo, alParcial, alFin, alError }) {
    if (!LOCAL_OK) return null;
    let rec = null, src = null, raf = 0, parado = false, abortado = false, trozos = [], t0 = Date.now(), habla = 0, calla = 0;
    const cierra = () => { cancelAnimationFrame(raf); try { src && src.disconnect(); } catch (e) { } sueltaMic(); };
    const para = () => { if (parado) return; parado = true; try { rec && rec.state !== "inactive" ? rec.stop() : cierra(); } catch (e) { cierra(); } };
    (async () => {
      let st;
      try { st = await abreMic(); } catch (e) { const er = e && e.name === "NotAllowedError" ? "not-allowed" : "audio-capture"; alError && alError(er); alFin && alFin("", er); return; }
      if (parado) { sueltaMic(); alFin && alFin("", abortado ? "aborted" : ""); return; }
      try { rec = MIME ? new MediaRecorder(st, { mimeType: MIME }) : new MediaRecorder(st); } catch (e) { alError && alError("audio-capture"); alFin && alFin("", "audio-capture"); return; }
      rec.ondataavailable = e => { if (e.data && e.data.size) trozos.push(e.data); };
      rec.onstop = async () => {
        cierra(); if (abortado) { alFin && alFin("", "aborted"); return; }
        const blob = new Blob(trozos, { type: rec.mimeType || MIME || "audio/webm" });
        if (!continuo && !habla) { alError && alError("no-speech"); alFin && alFin("", "no-speech"); return; }
        if (blob.size < 1500) { alFin && alFin("", "no-speech"); return; }
        alParcial && alParcial("…");
        try { const t = await transcribe(blob); alFin && alFin(t, t ? "" : "no-speech"); }
        catch (e) { if (e instanceof AuthErr) return; alError && alError("network"); alFin && alFin("", "network"); }
      };
      rec.start(250);
      /* detector de voz por energía: en modo turno, corta tras ~1,3 s de silencio después de hablar */
      if (!continuo) {
        try {
          const ctx = actx(); if (!ctx || ctx.state !== "running") throw new Error("audio dormido");
          const an = ctx.createAnalyser(); an.fftSize = 1024; src = ctx.createMediaStreamSource(st); src.connect(an); const buf = new Float32Array(an.fftSize); let ruido = 0.01;
          const mide = () => {
            if (parado) return; an.getFloatTimeDomainData(buf); let e = 0; for (const v of buf) e += v * v; e = Math.sqrt(e / buf.length);
            const ahora = Date.now();
            if (ahora - t0 < 400) ruido = Math.max(ruido, e * 1.3);
            if (e > Math.max(0.02, ruido * 2.2)) { habla = habla || ahora; calla = 0; } else if (habla && !calla) calla = ahora;
            if (habla && calla && ahora - calla > 1300) return para();
            if (!habla && ahora - t0 > 8000) return para();
            if (ahora - t0 > 30000) return para();
            raf = requestAnimationFrame(mide);
          };
          raf = requestAnimationFrame(mide);
        } catch (e) { habla = Date.now(); later(para, 7000); }      /* sin medidor: graba 7 s y transcribe */
      } else habla = Date.now();
    })();
    return { stop() { para(); }, abort() { abortado = true; para(); } };
  }

  function oir(op) {
    if (usarLocal || !SR) return oirLocal(op);
    const { continuo, alParcial, alFinal, alFin, alError } = op;
    const r = new SR(); r.lang = "es-ES"; r.interimResults = true; r.continuous = !!continuo; r.maxAlternatives = 1;
    let fin = "", ult = "", err = "";
    r.onresult = e => { let parc = ""; for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; if (e.results[i].isFinal) fin += t + " "; else parc += t; }
      ult = (fin + parc).trim(); alParcial && alParcial(ult); };
    r.onerror = e => { err = e.error || "error"; if (LOCAL_OK && /service-not-allowed|language-not-supported/.test(err)) { usarLocal = true; err = "usa-pc"; } alError && alError(err); };
    r.onend = () => alFin && alFin((fin.trim() || ult), err);
    try { r.start(); } catch (e) { alError && alError("start"); return null; }
    return { stop() { try { r.stop(); } catch (e) { } }, abort() { try { r.abort(); } catch (e) { } } };
  }

  /* frases agrupadas en trozos de hasta ~240 caracteres: el primero suena enseguida y el siguiente se va pidiendo mientras tanto */
  function trozos(t) {
    const fr = String(t).replace(/\s+/g, " ").trim().match(/[^.!?…]+[.!?…]*\s*/g) || [String(t)];
    const out = []; let cur = "";
    for (const f of fr) { if (cur && (cur + f).length > 240) { out.push(cur.trim()); cur = f; } else cur += f; }
    if (cur.trim()) out.push(cur.trim());
    return out.slice(0, 8);
  }
  const pide = txt => api("/api/tts", { texto: txt }, true).then(r => r.blob()).then(b => (/^audio\//.test(b.type) ? URL.createObjectURL(b) : null)).catch(() => null);
  const libera = u => { if (u) setTimeout(() => URL.revokeObjectURL(u), 1500); };
  function reproduce(url) {
    return new Promise(res => {
      if (!audio) audio = new Audio();
      const a = audio; let hecho = false;
      const fin = () => { if (hecho) return; hecho = true; a.onended = a.onerror = null; if (cortar === fin) cortar = null; libera(url); res(); };
      cortar = fin; a.onended = fin; a.onerror = fin; a.src = url;
      a.play().catch(() => fin());
    });
  }
  function conElNavegador(txt, mi) {
    return new Promise(res => {
      if (!window.speechSynthesis || mi !== token) return res();
      const u = new SpeechSynthesisUtterance(txt.replace(/[*_`#>]/g, "")); u.lang = "es-ES";
      const v = speechSynthesis.getVoices().find(x => /^es[-_]ES/i.test(x.lang)) || speechSynthesis.getVoices().find(x => /^es/i.test(x.lang)); if (v) u.voice = v;
      let hecho = false; const fin = () => { if (hecho) return; hecho = true; if (cortar === fin) cortar = null; res(); };
      cortar = fin; u.onend = fin; u.onerror = fin; speechSynthesis.cancel(); speechSynthesis.speak(u);
    });
  }
  /* devuelve una promesa que se cumple cuando Pedro termina de hablar (o le cortan) */
  async function decir(texto, forzar) {
    if (!forzar && !leer) return;
    callar(); const mi = token;
    const ch = trozos(texto); if (!ch.length) return;
    let sig = pide(ch[0]);
    for (let i = 0; i < ch.length; i++) {
      const url = await sig; if (mi !== token) { libera(url); return; }
      sig = i + 1 < ch.length ? pide(ch[i + 1]) : null;
      if (!url) { await conElNavegador(ch.slice(i).join(" "), mi); return; }
      await reproduce(url); if (mi !== token) return;
    }
  }
  function callar() {
    token++; const c = cortar; cortar = null; if (c) c();
    try { audio && audio.pause(); } catch (e) { } try { window.speechSynthesis && speechSynthesis.cancel(); } catch (e) { }
  }

  /* dictado dentro del formulario de texto */
  let dic = null;
  if (!SR && !LOCAL_OK) mic.hidden = true;
  mic.addEventListener("click", () => {
    if (dic) { dic.stop(); return; }
    mic.setAttribute("aria-pressed", "true");
    dic = oir({ alParcial: t => { if (t === "…") { Chat.textarea.placeholder = "Transcribiendo en el PC…"; return; } Chat.textarea.value = t; Chat.crece(); },
      alError: er => { const m = { "not-allowed": "Permiso de micrófono denegado.", "service-not-allowed": "El dictado no está disponible en este navegador.", "no-speech": "No te he oído. Prueba otra vez.", "audio-capture": "No encuentro el micrófono.", network: "El dictado necesita conexión a internet." }[er]; if (m) toast(m, "warn"); },
      alFin: (t, er) => { dic = null; mic.setAttribute("aria-pressed", "false"); Chat.textarea.placeholder = "Dile algo a Pedro"; if (t) { Chat.textarea.value = t; Chat.crece(); }
        else if (er === "usa-pc") toast("El dictado de este navegador no está disponible: uso el del PC. Vuelve a tocar el micrófono.", "", 4200); } });
    if (!dic) mic.setAttribute("aria-pressed", "false");
  });
  return { soportaOir: !!SR || LOCAL_OK, get enPC() { return usarLocal || !SR; }, oir, decir, callar, desbloquear, parar() { callar(); try { dic && dic.abort(); } catch (e) { } } };
})();

/* ---------- conversación por voz con Pedro: orbe (manos libres) + «mantén para hablar» ---------- */
const Conv = (() => {
  const orbe = $("orbe"), est = $("vz-estado"), oigo = $("vz-oigo"), manos = $("manos"), pulsar = $("pulsar"), nota = $("vz-nota");
  let estado = "reposo", libres = LS.get("jv_manos", "1") === "1", activo = false, ctl = null, gen = 0, mudos = 0;
  const T = { reposo: "Toca y habla con Pedro", escuchando: "Te escucho…", pensando: "Pedro está pensando…", hablando: "Pedro habla · toca para cortarle" };
  const set = (e, txt) => { estado = e; orbe.dataset.estado = e; orbe.setAttribute("aria-pressed", String(e !== "reposo")); est.textContent = txt || T[e]; };
  const avisa = t => { nota.hidden = !t; nota.textContent = t || ""; };
  manos.setAttribute("aria-checked", String(libres));
  manos.addEventListener("click", () => { libres = !libres; LS.set("jv_manos", libres ? "1" : "0"); manos.setAttribute("aria-checked", String(libres));
    if (!libres) activo = false; });
  if (!Voz.soportaOir) {
    orbe.disabled = true; pulsar.disabled = true; est.textContent = "Este navegador no deja usar el micrófono para dictar.";
    avisa("En Android usa Chrome; en iPhone, Safari con el dictado activado (Ajustes > General > Teclado > Dictado). Mientras tanto puedes escribir a Pedro más abajo y él te contesta con voz si activas el interruptor.");
  }
  const ERR = { "not-allowed": "Permiso de micrófono denegado. Actívalo en los ajustes del navegador.", "service-not-allowed": "El dictado no está disponible en este navegador.",
    "audio-capture": "No encuentro el micrófono.", network: "El dictado necesita internet en el móvil." };

  function escuchar(modo) {
    const g = ++gen; oigo.textContent = ""; avisa(""); set("escuchando");
    let errUlt = "";
    ctl = Voz.oir({ continuo: modo === "mantener",
      alParcial: t => { if (g !== gen) return; if (t === "…") est.textContent = "Transcribiendo en el PC…"; else oigo.textContent = t; },
      alError: er => { errUlt = er; },
      alFin: t => {
        if (g !== gen) return; ctl = null;
        if (t) { mudos = 0; enviar(t, g); return; }
        if (errUlt === "usa-pc") { escuchar(modo); return; }                    /* el navegador no deja: repite con el oído del PC */
        if (ERR[errUlt]) { activo = false; set("reposo"); avisa(ERR[errUlt]); return; }
        if (activo && libres && ++mudos < 3) { escuchar("turno"); return; }       /* silencio: sigue escuchando un par de veces */
        activo = false; mudos = 0; set("reposo", "No te he oído. Toca para seguir."); } });
    if (!ctl) { activo = false; set("reposo"); avisa("No se pudo iniciar el micrófono."); }
  }
  async function enviar(t, g) {
    set("pensando"); oigo.textContent = "“" + t + "”";
    const r = await Chat.hablar(t);
    if (g !== gen) return;
    if (!r.ok) { activo = false; set("reposo", r.text || "Algo ha fallado."); return; }
    set("hablando"); await Voz.decir(r.text, true);
    if (g !== gen) return;
    if (libres && activo) escuchar("turno"); else { activo = false; set("reposo"); }
  }
  orbe.addEventListener("click", () => {
    Voz.desbloquear();
    if (estado === "reposo") { activo = libres; mudos = 0; escuchar("turno"); }
    else if (estado === "escuchando") { gen++; try { ctl && ctl.abort(); } catch (e) { } ctl = null; activo = false; set("reposo"); }
    else if (estado === "pensando") { gen++; activo = false; set("reposo", "Cancelado. Pedro terminará y verás su respuesta abajo."); }
    else if (estado === "hablando") { Voz.callar(); gen++; if (libres) { activo = true; mudos = 0; escuchar("turno"); } else { activo = false; set("reposo"); } }
  });
  /* mantener pulsado: habla mientras lo tienes apretado y se envía al soltar */
  let pulsando = false;
  const suelta = () => { if (!pulsando) return; pulsando = false; pulsar.classList.remove("on"); try { ctl && ctl.stop(); } catch (e) { } };
  pulsar.addEventListener("pointerdown", e => {
    e.preventDefault(); Voz.desbloquear(); if (estado === "pensando") return;
    pulsando = true; pulsar.classList.add("on"); try { pulsar.setPointerCapture(e.pointerId); } catch (_) { }
    Voz.callar(); try { ctl && ctl.abort(); } catch (_) { } activo = false; escuchar("mantener");
    try { navigator.vibrate && navigator.vibrate(10); } catch (_) { } });
  ["pointerup", "pointercancel", "lostpointercapture"].forEach(ev => pulsar.addEventListener(ev, suelta));
  pulsar.addEventListener("contextmenu", e => e.preventDefault());
  pulsar.addEventListener("keydown", e => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); if (!pulsando) { pulsando = true; pulsar.classList.add("on"); Voz.callar(); activo = false; escuchar("mantener"); } } });
  pulsar.addEventListener("keyup", e => { if (e.key === " " || e.key === "Enter") suelta(); });
  return { parar() { gen++; activo = false; try { ctl && ctl.abort(); } catch (e) { } ctl = null; Voz.callar(); set("reposo"); } };
})();

/* =============================== CONTROL =============================== */
const fmtN = (v, u) => v == null || v === "" || isNaN(+v) ? "—" : NF.format(+v) + (u || "");
function pintaVig(d) {
  const box = $("vig"); if (!d) return; box.textContent = "";
  const lat = d.latido_s == null ? null : +d.latido_s, ok = !!d.activo && (lat == null || lat <= 120);
  const hoy = d.hoy || null, u = d.ultima || null;
  if (hoy && +hoy.arranques_hoy > 1) box.append(h("p", { class: "alerta", text: "El PC se ha reiniciado hoy: " + hoy.arranques_hoy + " arranques. Revisa los eventos." }));
  box.append(h("div", { class: "sema" }, h("span", { class: "luz" + (ok ? "" : " mal"), "aria-hidden": "true" }),
    h("div", null, h("b", { text: ok ? "Vigilando." : "Parado." }), " ", lat == null ? "Sin latido." : "Último latido hace " + lat + " s.",
      d.tarea ? h("div", { class: "nota", text: "Tarea programada: " + String(d.tarea) }) : null)));
  if (u) box.append(h("p", { class: "nota", text: "Última muestra" + (u.ts ? " (" + String(u.ts).slice(11, 16) + ")" : "") + ": gráfica " + fmtN(u.gpu_temp_c, " °C") + ", " + fmtN(u.gpu_pwr_w, " W") + ", " + fmtN(u.gpu_util_pct, " %") + " de uso; procesador " + fmtN(u.cpu_pct, " %") + "." + (u.juego ? " Jugando a " + String(u.juego) + "." : "") }));
  if (hoy) {
    const c = (k, v) => h("div", null, h("dt", { text: k }), h("dd", { class: "num", text: v }));
    box.append(h("dl", { class: "dia" }, c("Temperatura máx.", fmtN(hoy.gpu_temp_max, " °C")), c("Consumo máx.", fmtN(hoy.gpu_w_max, " W")), c("Gráfica máx.", fmtN(hoy.gpu_util_max, " %")),
      c("Procesador máx.", fmtN(hoy.cpu_max, " %")), c("Memoria libre mín.", hoy.ram_libre_min_mb == null ? "—" : NF.format(hoy.ram_libre_min_mb / 1024) + " GB"), c("Arranques hoy", fmtN(hoy.arranques_hoy))));
  }
  const ev = Array.isArray(d.eventos) ? d.eventos : [];
  box.append(h("p", { class: "nota", text: ev.length ? "Registro del vigilante (lo más reciente arriba):" : "Sin eventos en el registro del vigilante." }));
  if (ev.length) box.append(h("ul", { class: "lista" }, ev.slice(-12).reverse().map(t => h("li", { text: String(t) }))));
}
$("vig-rf").addEventListener("click", async () => { const b = $("vig-rf"); b.disabled = true;
  try { P.wd = await api("/api/watchdog"); P.emit("wd", P.wd); } catch (e) { if (!(e instanceof AuthErr)) toast("Vigilante: " + errText(e), "err"); } b.disabled = false; });
on("control", () => { if (P.wd) pintaVig(P.wd); else $("vig-rf").click(); });

/* energía (tapa roja) */
let cuenta = 0;
function pendiente(tipo, txt) {
  clearInterval(cuenta); const box = $("pend"); box.textContent = "";
  let s = +((String(txt).match(/(\d+)\s*s\b/) || [])[1] || 15);
  const c = h("span", { class: "cnt num", text: String(s) });
  const cb = h("button", { class: "bt fuerte", type: "button", onclick: cancelar }, "Cancelar");
  box.append(h("div", { class: "pend", role: "alert" }, c, h("span", { text: (tipo === "apagar" ? "Apagando" : "Reiniciando") + " el " + PC + ". " + String(txt) }), cb)); cb.focus();
  cuenta = setInterval(() => { s--; c.textContent = String(Math.max(0, s)); if (s <= 0) clearInterval(cuenta); }, 1000);
}
async function cancelar() {
  try { const j = await api("/api/cancelar"); clearInterval(cuenta); $("pend").textContent = ""; toast(j.text || "Cancelado.", "ok"); }
  catch (e) { if (!(e instanceof AuthErr)) toast(errText(e), "err"); }
}
$("cancelar").addEventListener("click", cancelar);
const ENE = {
  apagar: { t: "¿Apagar el " + PC + "?", x: "Apagado completo en 15 s. Podrás cancelarlo durante esos segundos; después solo se enciende por Wake-on-LAN.", a: "Apagar" },
  reiniciar: { t: "¿Reiniciar el " + PC + "?", x: "Se reiniciará en 15 s. El asistente tardará un par de minutos en volver.", a: "Reiniciar" },
  bloquear: { t: "¿Bloquear el " + PC + "?", x: "Bloquea la sesión de Windows. Para desbloquearlo hará falta estar delante del PC.", a: "Bloquear" } };
document.querySelectorAll("[data-energia]").forEach(b => b.addEventListener("click", () => {
  const k = b.dataset.energia, p = ENE[k];
  confirmar({ titulo: p.t, texto: p.x, accion: p.a, onOk: async () => {
    try { if (k === "bloquear") { const j = await api("/api/bloquear"); toast(j.text || "Bloqueado.", "ok"); return; }
      const j = await api("/api/" + k, { confirm: true }); pendiente(k, j.text || ""); }
    catch (e) { if (!(e instanceof AuthErr)) toast(errText(e), "err"); } } });
}));
document.querySelectorAll("[data-vol]").forEach(b => b.addEventListener("click", async () => {
  const a = b.dataset.vol; b.disabled = true;
  try { await api("/api/vol", { a }); toast(a === "up" ? "Volumen subido." : a === "down" ? "Volumen bajado." : "Silencio conmutado.", "ok", 1600); }
  catch (e) { if (!(e instanceof AuthErr)) toast(errText(e), "err"); }
  b.disabled = false;
}));

/* procesos */
const Proc = (() => {
  let D2 = { total: 0, top: [], ventanas: [] }, tab = "top", ok = false;
  const list = $("procs"), q = $("pro-q");
  const setTab = t => { tab = t; $("t-top").setAttribute("aria-selected", String(t === "top")); $("t-win").setAttribute("aria-selected", String(t === "win")); pinta(); };
  $("t-top").addEventListener("click", () => setTab("top")); $("t-win").addEventListener("click", () => setTab("win"));
  q.addEventListener("input", () => pinta());
  const prot = pid => { const p = D2.top.find(x => x.pid === pid); return p ? !!p.protegido : false; };
  function accion(pid, nombre, protegido) {
    if (protegido) return h("span", { class: "candado", role: "img", "aria-label": nombre + " está protegido: no se cierra desde aquí", title: "Protegido" }, ic("lock"));
    return h("button", { class: "bt", type: "button", "aria-label": "Cerrar " + nombre + " (PID " + pid + ")", onclick: () => confirmar({
      titulo: "¿Cerrar " + nombre + "?", texto: "PID " + pid + ". Se forzará el cierre y se perderá lo que no esté guardado.", accion: "Cerrar",
      onOk: async () => { try { const j = await api("/api/matar", { pid, confirm: true }); toast(j.text || "Cerrado.", "ok"); } catch (e) { if (!(e instanceof AuthErr)) toast(errText(e), "err"); } poll.now(); } }) }, "Cerrar");
  }
  function pinta() {
    list.textContent = ""; const t = q.value.trim().toLowerCase();
    if (!ok) return;
    if (tab === "top") {
      const rows = D2.top.filter(p => String(p.name || "").toLowerCase().includes(t)).sort((a, b) => (+b.mem_mb || 0) - (+a.mem_mb || 0));
      const mx = Math.max(1, ...D2.top.map(p => +p.mem_mb || 0));
      if (!rows.length) { list.append(h("li", { class: "vacia", text: t ? "Ningún proceso coincide." : "Sin datos." })); return; }
      for (const p of rows) { const mem = +p.mem_mb || 0;
        list.append(h("li", null, h("div", { style: "min-width:0" }, h("div", { class: "n", text: String(p.name || "?") }),
          h("div", { class: "m2 num", text: "PID " + p.pid + ", " + (mem >= 1024 ? NF.format(mem / 1024) + " GB" : Math.round(mem) + " MB") + ", " + NF.format(+p.cpu || 0) + " % de CPU" }),
          h("div", { class: "hb", "aria-hidden": "true", style: "--f:" + (100 * mem / mx).toFixed(1) + "%" }, h("i"))),
          accion(p.pid, String(p.name || "proceso"), !!p.protegido))); }
    } else {
      const rows = D2.ventanas.filter(w => (String(w.title || "") + " " + String(w.name || "")).toLowerCase().includes(t));
      if (!rows.length) { list.append(h("li", { class: "vacia", text: t ? "Ninguna ventana coincide." : "No hay ventanas abiertas." })); return; }
      for (const w of rows) list.append(h("li", null, h("div", { style: "min-width:0" }, h("div", { class: "n", text: String(w.title || "(sin título)") }), h("div", { class: "m2", text: String(w.name || "") + ", PID " + w.pid })),
        accion(w.pid, String(w.name || w.title || "ventana"), prot(w.pid))));
    }
  }
  async function cargar() {
    if (!ok) { list.textContent = ""; list.append(h("li", null, h("div", { class: "skl", style: "width:100%" })), h("li", null, h("div", { class: "skl", style: "width:100%" }))); }
    try { const j = await api("/api/procesos");
      D2 = { total: +j.total || 0, top: Array.isArray(j.top) ? j.top : [], ventanas: Array.isArray(j.ventanas) ? j.ventanas : [] }; ok = true;
      $("n-top").textContent = String(D2.total || D2.top.length); $("n-win").textContent = String(D2.ventanas.length); pinta(); }
    catch (e) { if (e instanceof AuthErr) throw e;
      if (!ok) { list.textContent = ""; list.append(h("li", { class: "vacia err" }, h("span", { text: errText(e) + " Se reintentará solo." }))); } else toast("Procesos: " + errText(e), "warn");
      throw e; }
  }
  const poll = poller(cargar, 60000); poll._vista = "control";
  $("pro-rf").addEventListener("click", () => poll.now());
  return poll;
})();

/* eventos graves */
const EVK = { "41": ["Reinicio inesperado", "Kernel-Power: el PC se apagó sin cerrar bien"], "6008": ["Apagado inesperado", "El sistema no se cerró correctamente"], "1001": ["Pantallazo azul", "BugCheck registrado"] };
async function cargaEventos() {
  const box = $("ev"); if (!box.childNodes.length) box.append(h("div", { class: "skl" }));
  try { const j = await api("/api/eventos"); const t = String(j.text || ""); box.textContent = "";
    const items = t.split(/\r?\n/).map(s => s.trim()).filter(l => /^\d{2}\/\d{2}\s+\d{2}:\d{2}/.test(l));
    if (!items.length) { box.append(h("p", { class: "vacia", text: /sin eventos/i.test(t) ? "Todo en calma: sin eventos graves en 24 h." : (t || "Sin datos.") })); return; }
    box.append(h("ul", { class: "lista ev" }, items.reverse().map(l => {
      const m = l.match(/^(\d{2}\/\d{2}\s+\d{2}:\d{2})\s+id(\d+)\s+(.*)$/), tm = m ? m[1] : l.slice(0, 11), id = m ? m[2] : "", pr = m ? m[3] : l.slice(11);
      let k = EVK[id]; if (!k && /WHEA/i.test(pr)) k = ["Error de hardware (WHEA)", "PCIe, CPU o RAM: revisa la gráfica y su enlace"];
      if (!k && /nvlddmkm/i.test(pr)) k = ["Fallo del driver de NVIDIA", "nvlddmkm dejó de responder"];
      k = k || ["Evento " + id, ""];
      return h("li", null, h("span", { class: "t num", text: tm }), h("b", { text: k[0] }), h("span", { class: "d", text: (k[1] ? k[1] + ". " : "") + pr + (id ? " (id " + id + ")" : "") }));
    })));
  } catch (e) { if (e instanceof AuthErr) throw e; box.textContent = ""; box.append(h("p", { class: "vacia err", text: errText(e) + " Se reintentará solo." })); throw e; }
}
const pollEv = poller(cargaEventos, 300000); pollEv._vista = "control";
$("ev-rf").addEventListener("click", () => pollEv.now());
let textoRed = "";
async function cargaRed() {
  const pre = $("red"), b = $("red-rf"); b.disabled = true;
  try { const j = await api("/api/red"); textoRed = String(j.text || "(vacío)"); pre.textContent = textoRed; }
  catch (e) { if (!(e instanceof AuthErr)) pre.textContent = errText(e); }
  b.disabled = false;
}
$("red-rf").addEventListener("click", cargaRed); $("red-cp").addEventListener("click", () => copiar(textoRed || $("red").textContent));
let redHecha = false; on("control", () => { if (!redHecha) { redHecha = true; cargaRed(); } });

/* memoria y agenda de Pedro */
async function cargaPedro() {
  const ag = $("ped-ag"), mem = $("ped-mem"), b = $("ped-rf"); b.disabled = true;
  const fila = (txt, sub, onBorrar) => h("div", { class: "fila-acc" }, h("div", { class: "q" }, h("b", { text: txt }), h("span", { text: sub })),
    h("button", { class: "bt", type: "button", onclick: onBorrar }, "Borrar"));
  const borra = (ruta, id, txt) => () => confirmar({ titulo: "¿Borrar?", texto: "Se borra para siempre.", detalle: txt, accion: "Borrar",
    onOk: async () => { try { const j = await api(ruta, { id }); toast(j.text || "Borrado.", "ok", 1600); } catch (e) { if (!(e instanceof AuthErr)) toast(errText(e), "err"); } cargaPedro(); } });
  try {
    const [a, m, s] = await Promise.all([api("/api/agenda"), api("/api/memoria"), api("/api/stats")]);
    ag.textContent = ""; mem.textContent = "";
    const ai = Array.isArray(a.items) ? a.items : [], mi = Array.isArray(m.items) ? m.items : [];
    if (!ai.length) ag.append(h("p", { class: "vacia", text: "Nada programado." }));
    for (const it of ai) ag.append(fila(String(it.texto || ""), String(it.cuando) + " · " + (it.tipo === "tarea" ? "tarea" : "aviso") + (it.repetir !== "no" ? " · " + it.repetir : ""), borra("/api/agenda_borrar", it.id, it.texto)));
    if (!mi.length) mem.append(h("p", { class: "vacia", text: "Todavía no recuerda nada." }));
    for (const it of mi.slice().reverse()) mem.append(fila(String(it.texto || ""), String(it.t || "") + (it.tema ? " · " + it.tema : ""), borra("/api/olvidar", it.id, it.texto)));
    if (s && s.hoy) $("ped-uso").textContent = "Hoy: " + s.hoy.llamadas + " consultas a Pedro (" + s.hoy.segundos_medio + " s de media). Últimos 7 días: " + s.semana.llamadas + ". Para añadir, díselo hablando: «recuerda que…», «avísame a las…».";
  } catch (e) { if (!(e instanceof AuthErr)) { ag.textContent = ""; ag.append(h("p", { class: "vacia err", text: errText(e) })); } }
  b.disabled = false;
}
$("ped-rf").addEventListener("click", cargaPedro);
on("control", cargaPedro);
$("c-nueva").addEventListener("click", () => confirmar({ titulo: "¿Conversación nueva?", texto: "Pedro olvida el hilo de esta charla (no lo que recuerda a largo plazo).", detalle: "", accion: "Empezar de cero",
  onOk: async () => { try { const j = await api("/api/nueva"); toast(j.text || "Hecho.", "ok", 2400); } catch (e) { if (!(e instanceof AuthErr)) toast(errText(e), "err"); } } }));

/* =============================== LANZAR =============================== */
const Lanz = (() => {
  let L = { grupos: [], items: [] }, ok = false, tok = 0, hoja = null;
  const box = $("lz"), q = $("lz-q");
  const QUE = { url: "abre aquí", app: "en el PC", carpeta: "en el PC", cmd: "comprobación", ssh: "en el VPS", ia: "prepara el chat" };
  const seguro = u => /^https?:\/\//i.test(String(u || ""));
  function pinta() {
    box.textContent = ""; const t = q.value.trim().toLowerCase();
    const items = t ? L.items.filter(i => (String(i.label) + " " + (i.desc || "")).toLowerCase().includes(t)) : L.items;
    if (!items.length) { box.append(h("p", { class: "vacia", text: t ? "Nada coincide con «" + q.value.trim() + "»." : "No hay lanzadores." })); return; }
    for (const g of L.grupos) {
      const del = items.filter(i => i.grupo === g.id); if (!del.length) continue;
      const hid = "lg-" + g.id;
      box.append(h("section", { class: "grupo", "aria-labelledby": hid }, h("h2", { id: hid }, String(g.nombre), h("span", { class: "num", text: String(del.length) })),
        h("ul", { class: "lanz" }, del.map(it => {
          const go = h("button", { class: "go", type: "button" }, h("b", { text: String(it.label) }), it.desc ? h("span", { class: "d", text: String(it.desc) }) : null,
            h("span", { class: "ti", text: (it.confirmar ? "pide confirmación" : QUE[it.tipo] || String(it.tipo || "")) }));
          go.addEventListener("click", () => actuar(it));
          const li = h("li", null, go);
          if (it.tipo === "url") li.append(h("button", { class: "enpc", type: "button", "aria-label": "Abrir " + it.label + " en el PC", onclick: () => correr(it, { donde: "pc" }) }, "En el PC"));
          else li.append(h("span"));
          return li;
        }))));
    }
  }
  function actuar(it) {
    if (it.tipo === "url") { if (!seguro(it.url)) { toast("Enlace no válido.", "warn"); return; } window.open(it.url, "_blank", "noopener"); return; }
    if (it.tipo === "ia") { Chat.preparar({ prompt: String(it.prompt || ""), backend: it.backend, modo: it.modo }); return; }
    if (it.confirmar) { confirmar({ titulo: "¿Ejecutar «" + it.label + "»?", texto: "Se ejecutará en el " + PC + (it.desc ? ": " + it.desc : "."), accion: "Ejecutar", onOk: () => correr(it, { confirm: true }) }); return; }
    correr(it, {});
  }
  async function correr(it, extra) {
    const mi = ++tok; let texto = "";
    const est = h("span", { class: "nota", text: "Ejecutando…" }), pre = h("pre", { class: "salida", text: "…" });
    const cp = h("button", { class: "bt", type: "button", onclick: () => copiar(texto) }, ic("copy"), "Copiar"), abrir = h("button", { class: "bt", type: "button", hidden: true }, "Abrir");
    if (hoja) hoja.close();
    hoja = Hoja.open({ titulo: String(it.label) + (extra.donde === "pc" ? " en el PC" : ""), modal: false, clase: "res", cuerpo: h("div", null, est, pre), acciones: [abrir, cp], onClose: () => { if (tok === mi) tok++; } });
    const t0 = Date.now();
    try { const j = await api("/api/lanzar", Object.assign({ id: it.id }, extra)); if (!j.job) throw new Error(j.error || "El PC no devolvió una tarea.");
      const s = await pollJob(j.job, ms => { if (tok === mi) est.textContent = "Ejecutando… " + Math.round(ms / 1000) + " s"; }, 180000);
      if (tok !== mi) return; texto = String(s.text || "(sin salida)"); pre.textContent = texto; est.textContent = "Hecho en " + Math.round((Date.now() - t0) / 1000) + " s.";
      if (seguro(s.url) && extra.donde !== "pc") { abrir.hidden = false; abrir.onclick = () => window.open(s.url, "_blank", "noopener"); } }
    catch (e) { if (e instanceof AuthErr || tok !== mi) return; texto = errText(e); pre.textContent = texto; est.textContent = "Error."; }
  }
  async function cargar() {
    try { const j = await api("/api/launchers"); L = { grupos: Array.isArray(j.grupos) ? j.grupos : [], items: Array.isArray(j.items) ? j.items : [] }; ok = true; pinta(); }
    catch (e) { if (e instanceof AuthErr) return; box.textContent = "";
      box.append(h("p", { class: "vacia err", text: errText(e) }), h("button", { class: "bt", type: "button", onclick: cargar }, ic("refresh"), "Reintentar")); }
  }
  q.addEventListener("input", () => ok && pinta());
  on("lanzar", () => { if (!ok) cargar(); });
  return { cerrar: () => hoja && hoja.close() };
})();
on("pulso", () => Lanz.cerrar()); on("hablar", () => Lanz.cerrar()); on("control", () => Lanz.cerrar());

/* =============================== VENTANAS (lista con acciones; se usa en Control y en el mando) =============================== */
const Vent = (() => {
  async function lista() { const j = await api("/api/ventanas"); return Array.isArray(j.ventanas) ? j.ventanas : []; }
  async function accion(w, a, alFin) {
    try { await api("/api/ventana", { id: w.id, accion: a }); alFin && alFin(a); }
    catch (e) { if (e instanceof AuthErr) return; toast("No se pudo: " + errText(e), "warn", 2800); }
  }
  function pinta(ul, vs, alFin) {
    ul.textContent = "";
    if (!vs.length) { ul.append(h("li", { class: "vac", text: "No veo ventanas abiertas." })); return; }
    for (const w of vs) {
      const cerrar = h("button", { class: "bt", type: "button" }, "Cerrar");
      let armado = 0;
      cerrar.addEventListener("click", () => {
        if (!armado) { armado = 1; cerrar.textContent = "¿Seguro?"; cerrar.classList.add("peligro"); setTimeout(() => { armado = 0; cerrar.textContent = "Cerrar"; cerrar.classList.remove("peligro"); }, 3000); return; }
        accion(w, "cerrar", alFin); });
      ul.append(h("li", { class: w.activa ? "act" : "" },
        h("button", { class: "w-t", type: "button", onclick: () => accion(w, "foco", alFin) }, h("b", { text: w.titulo || "(sin título)" }), h("span", { text: w.activa ? "al frente" : w.min ? "minimizada · toca para traerla" : "toca para traerla al frente" })),
        h("div", { class: "w-a" }, h("button", { class: "bt", type: "button", onclick: () => accion(w, w.min ? "restaurar" : "min", alFin) }, w.min ? "Restaurar" : "Minimizar"),
          h("button", { class: "bt", type: "button", onclick: () => accion(w, "max", alFin) }, "Maximizar"), cerrar)));
    }
  }
  return { lista, pinta };
})();
const wins = $("wins");
async function cargaVentanas() { pinta_(await Vent.lista()); }
const pinta_ = vs => Vent.pinta(wins, vs, () => later(() => pollWin.now(), 400));
const pollWin = poller(cargaVentanas, 10000); pollWin._vista = "control";
$("win-rf").addEventListener("click", () => pollWin.now());

/* =============== PANTALLA: MANDO REMOTO v2 =============== */
/* Modo RATÓN (por defecto): el móvil es un touchpad. La flecha se mueve arrastrando el dedo en cualquier parte
   (no se tapa lo que se quiere pulsar); toque = clic donde está la flecha, dos toques = doble clic, dos dedos = clic
   derecho, mantener y arrastrar = arrastrar. Con zoom, la vista sigue a la flecha. Modo TÁCTIL: toque directo.
   La geometría sale del tamaño REAL del lienzo (ResizeObserver), no de cálculos con innerHeight: así no se solapa nada
   aunque Safari esconda sus barras o salga el teclado. */
const Mando = (() => {
  const mando = $("mando"), lz = $("m-lienzo"), img = $("m-img"), cur = $("m-cursor"), carg = $("m-carg"), hora = $("m-hora"),
    toque = $("m-toque"), kb = $("m-kb"), teclas = $("m-teclas"), rueda = $("m-rueda"), bTec = $("m-teclado"), bModo = $("m-modo");
  const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  let url = null, busy = false, t = 0, pausa = false, full = false, fallos = 0, urgente = false, enVista = false;
  let ar = 16 / 9, z = 1, modo = LS.get("jv_mando", "raton") === "tactil" ? "tactil" : "raton", der = false;
  let cx = .5, cy = .5, S = 1, tx = 0, ty = 0;
  const iw = 1000; let ih = iw / ar;
  const mods = new Set();
  const activa = () => (full || enVista) && !document.hidden && !pausa && !Session.dead;
  const vibra = ms => { try { navigator.vibrate && navigator.vibrate(ms); } catch (e) { } };

  /* ---- imagen en directo ---- */
  const programa = ms => { clearTimeout(t); if (activa()) t = setTimeout(cuadro, ms); };
  function kick() { if (!activa()) return; if (busy) urgente = true; else programa(100); }
  async function cuadro() {
    if (busy || !activa()) return; busy = true;
    try {
      const alta = full && z > 1.6;
      const r = await api("/api/vivo", { w: alta ? 2000 : full ? 1280 : 900, q: alta ? 70 : full ? 60 : 52 }, true), bl = await r.blob();
      if (!/^image\//.test(bl.type)) throw new Error("Respuesta no válida del PC.");
      const viejo = url; url = URL.createObjectURL(bl); img.src = url; if (viejo) setTimeout(() => URL.revokeObjectURL(viejo), 1500);
      carg.hidden = true; fallos = 0; hora.textContent = "en directo · " + new Date().toLocaleTimeString("es-ES");
    } catch (e) {
      if (e instanceof AuthErr) { busy = false; return; }
      fallos++; carg.hidden = false; carg.textContent = "Sin imagen del PC: " + errText(e); hora.textContent = "sin señal";
    }
    busy = false; const u = urgente; urgente = false;
    programa(fallos ? Math.min(1000 * 2 ** fallos, 15000) : u ? 100 : full ? 380 : 1500);
  }
  img.addEventListener("load", () => { if (img.naturalWidth) { const n = img.naturalWidth / img.naturalHeight; if (Math.abs(n - ar) > .01) { ar = n; ih = iw / ar; if (!full) lz.style.aspectRatio = String(ar); } pinta(); } });
  if ("IntersectionObserver" in window) new IntersectionObserver(es => { enVista = es[0].isIntersecting; if (enVista) kick(); else if (!full) clearTimeout(t); }).observe(lz);
  else enVista = true;
  lz.style.aspectRatio = String(ar);

  /* ---- geometría: encajar la imagen en el lienzo y, con zoom, seguir a la flecha ---- */
  function pinta() {
    const W = lz.clientWidth, Hh = lz.clientHeight; if (!W || !Hh) return;
    S = Math.min(W / iw, Hh / ih) * z;
    const dw = iw * S, dh = ih * S;
    tx = dw <= W ? (W - dw) / 2 : Math.min(0, Math.max(W - dw, W / 2 - cx * dw));
    ty = dh <= Hh ? (Hh - dh) / 2 : Math.min(0, Math.max(Hh - dh, Hh / 2 - cy * dh));
    img.style.width = dw + "px"; img.style.height = dh + "px"; img.style.transform = "translate(" + tx + "px," + ty + "px)";
    cur.style.transform = "translate(" + (tx + cx * dw) + "px," + (ty + cy * dh) + "px)";
    cur.hidden = !full || modo !== "raton";
  }
  if (window.ResizeObserver) new ResizeObserver(pinta).observe(lz);
  addEventListener("resize", pinta);
  const aNorm = (px, py) => { const r = lz.getBoundingClientRect(), u = (px - r.left - tx) / (iw * S), v = (py - r.top - ty) / (ih * S);
    return (u < 0 || u > 1 || v < 0 || v > 1) ? null : { x: u, y: v }; };
  const ponCursor = p => { cx = p.x; cy = p.y; pinta(); };
  function ponZoom(n) { z = clamp(n, 1, 5); pinta(); kick(); $("m-zmenos").disabled = z <= 1; }

  /* ---- órdenes al PC, en orden y sin amontonar movimientos ---- */
  const cola = []; let enviando = false;
  function empuja(ruta, cuerpo, fusionable) {
    const u = cola[cola.length - 1];
    if (u && u.ruta === ruta) {
      if (fusionable && u.fus) { u.cuerpo = cuerpo; return; }
      if (cuerpo.texto && u.cuerpo.texto) { u.cuerpo.texto += cuerpo.texto; return; }
    }
    cola.push({ ruta, cuerpo, fus: !!fusionable }); if (!enviando) bombea();
  }
  async function bombea() {
    enviando = true;
    while (cola.length) { const o = cola.shift();
      try { await api(o.ruta, o.cuerpo); }
      catch (e) { if (e instanceof AuthErr) { cola.length = 0; break; } toast("El PC no ha aceptado la orden: " + errText(e), "warn", 2600); } }
    enviando = false; kick();
  }
  const raton = (accion, p, extra) => empuja("/api/raton", Object.assign({ accion, x: p.x, y: p.y }, extra || {}), accion === "mover");
  function marcaEn(p, cls) {
    toque.className = "m-toque"; void toque.offsetWidth;
    toque.style.left = (tx + p.x * iw * S) + "px"; toque.style.top = (ty + p.y * ih * S) + "px"; toque.className = "m-toque on " + (cls || "");
  }
  function pulsaDer(v) { der = v; $("m-der").setAttribute("aria-pressed", String(v)); }

  /* ---- gestos sobre la imagen (solo a pantalla completa; en la página, un toque abre el mando) ---- */
  const ptrs = new Map(); let g = null, tapPend = null, ultTap = 0;
  lz.addEventListener("click", () => { if (!full) ampliar(true); });
  lz.addEventListener("keydown", e => { if (!full && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); ampliar(true); } });
  lz.addEventListener("pointerdown", e => {
    if (!full) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault(); try { lz.setPointerCapture(e.pointerId); } catch (_) { }
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (ptrs.size === 1) {
      const now = performance.now();
      g = { n: 1, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, t0: now, lt: now, movido: false, arrastra: false, hecho: false };
      g.timer = setTimeout(() => {
        if (!g || g.n !== 1 || g.movido) return;
        if (modo === "raton") { g.arrastra = true; raton("arrastrar_ini", { x: cx, y: cy }, { boton: "izq" }); cur.classList.add("arr"); vibra(20); }
        else { g.hecho = true; const p = aNorm(g.x0, g.y0); if (p) { ponCursor(p); raton("clic", p, { boton: "der" }); marcaEn(p, "der"); vibra(25); } }
      }, 450);
    } else if (ptrs.size === 2) {
      if (g && g.timer) clearTimeout(g.timer);
      if (g && g.arrastra) { raton("arrastrar_fin", { x: cx, y: cy }); cur.classList.remove("arr"); }
      const a = [...ptrs.values()], mx = (a[0].x + a[1].x) / 2, my = (a[0].y + a[1].y) / 2;
      g = { n: 2, d0: Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y) || 1, z0: z, mx0: mx, my0: my, mx, my, modo: null, acc: 0, t0: performance.now(), tap: false };
    }
  });
  lz.addEventListener("pointermove", e => {
    if (!full || !g) return; const p0 = ptrs.get(e.pointerId); if (!p0) return;
    p0.x = e.clientX; p0.y = e.clientY;
    if (g.n === 1) {
      const dx = e.clientX - g.x, dy = e.clientY - g.y, now = performance.now(), dt = Math.max(8, now - g.lt);
      g.x = e.clientX; g.y = e.clientY; g.lt = now;
      if (!g.movido && Math.hypot(g.x - g.x0, g.y - g.y0) > 6) {
        g.movido = true; if (!g.arrastra) clearTimeout(g.timer);
        if (modo === "tactil") { const p = aNorm(g.x0, g.y0); if (p) { ponCursor(p); raton("arrastrar_ini", p, { boton: "izq" }); g.arrastra = true; } }
        return;
      }
      if (!g.movido) return;
      if (modo === "raton") {
        const v = Math.hypot(dx, dy) / dt, k = 1.1 * (1 + Math.min(2.2, Math.max(0, v - .25) * 1.6));   /* aceleración: lento = preciso */
        cx = clamp(cx + dx * k / (iw * S), 0, 1); cy = clamp(cy + dy * k / (ih * S), 0, 1); pinta();
        raton("mover", { x: cx, y: cy });
      } else if (g.arrastra) { const p = aNorm(g.x, g.y); if (p) { ponCursor(p); raton("mover", p); } }
    } else if (g.n === 2 && ptrs.size >= 2) {
      const a = [...ptrs.values()], d = Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y), mx = (a[0].x + a[1].x) / 2, my = (a[0].y + a[1].y) / 2;
      if (!g.modo) { if (Math.abs(d / g.d0 - 1) > .15) g.modo = "zoom"; else if (Math.hypot(mx - g.mx0, my - g.my0) > 12) g.modo = "rueda"; }
      if (g.modo === "zoom") ponZoom(g.z0 * d / g.d0);
      else if (g.modo === "rueda") { g.acc += my - g.my; if (Math.abs(g.acc) >= 16) { raton("rueda", { x: cx, y: cy }, { delta: Math.round(g.acc * 4) }); g.acc = 0; } }
      g.mx = mx; g.my = my;
    }
  });
  function suelta(e) {
    const habia = ptrs.delete(e.pointerId); if (!habia || !g) return;
    if (g.n === 1) {
      clearTimeout(g.timer);
      if (g.arrastra) { raton("arrastrar_fin", modo === "raton" ? { x: cx, y: cy } : (aNorm(g.x, g.y) || { x: cx, y: cy })); cur.classList.remove("arr"); }
      else if (e.type !== "pointercancel" && !g.movido && !g.hecho && performance.now() - g.t0 < 450) toqueCorto(g.x0, g.y0);
      g = null;
    } else if (g.n === 2) {
      if (!g.modo && !g.tap && performance.now() - g.t0 < 400 && e.type !== "pointercancel") { g.tap = true; raton("clic", { x: cx, y: cy }, { boton: "der" }); marcaEn({ x: cx, y: cy }, "der"); vibra(25); }
      if (!ptrs.size) g = null;
    }
  }
  lz.addEventListener("pointerup", suelta); lz.addEventListener("pointercancel", suelta);
  /* un toque = clic (se esperan 230 ms por si llega el segundo toque del doble clic) */
  function toqueCorto(px, py) {
    let p;
    if (modo === "tactil") { p = aNorm(px, py); if (!p) return; ponCursor(p); } else p = { x: cx, y: cy };
    if (der) { pulsaDer(false); raton("clic", p, { boton: "der" }); marcaEn(p, "der"); vibra(25); return; }
    const ahora = performance.now();
    if (tapPend && ahora - ultTap < 320) { clearTimeout(tapPend); tapPend = null; raton("doble", p); marcaEn(p, "doble"); vibra([10, 40, 10]); return; }
    ultTap = ahora; marcaEn(p);
    tapPend = setTimeout(() => { tapPend = null; raton("clic", p); vibra(8); }, 230);
  }
  lz.addEventListener("contextmenu", e => { e.preventDefault(); if (!full) return; const p = modo === "raton" ? { x: cx, y: cy } : aNorm(e.clientX, e.clientY); if (p) { raton("clic", p, { boton: "der" }); marcaEn(p, "der"); } });
  lz.addEventListener("wheel", e => { if (!full) return; e.preventDefault(); raton("rueda", { x: cx, y: cy }, { delta: Math.round(-e.deltaY * 3) }); }, { passive: false });
  /* Safari: que el pellizco no amplíe la página entera ni el dedo la desplace mientras se usa el mando */
  ["gesturestart", "gesturechange"].forEach(ev => document.addEventListener(ev, e => { if (full) e.preventDefault(); }));
  mando.addEventListener("touchmove", e => { if (full && !e.target.closest(".m-barra,.m-teclas")) e.preventDefault(); }, { passive: false });

  /* ---- barra de desplazamiento propia (arrastrar arriba/abajo = rueda donde está la flecha) ---- */
  let rd = null;
  rueda.addEventListener("pointerdown", e => { e.preventDefault(); try { rueda.setPointerCapture(e.pointerId); } catch (_) { } rd = { y: e.clientY, acc: 0 }; rueda.classList.add("on"); });
  rueda.addEventListener("pointermove", e => { if (!rd) return; rd.acc += e.clientY - rd.y; rd.y = e.clientY;
    if (Math.abs(rd.acc) >= 12) { raton("rueda", { x: cx, y: cy }, { delta: Math.round(rd.acc * 5) }); rd.acc = 0; } });
  ["pointerup", "pointercancel", "lostpointercapture"].forEach(ev => rueda.addEventListener(ev, () => { rd = null; rueda.classList.remove("on"); }));
  rueda.addEventListener("keydown", e => { const d = { ArrowUp: 120, ArrowDown: -120, PageUp: 600, PageDown: -600 }[e.key]; if (d) { e.preventDefault(); raton("rueda", { x: cx, y: cy }, { delta: d }); } });

  /* ---- teclado del móvil: lo sacas y lo escondes tú con el botón «Teclado» (nada automático) ---- */
  const abierto = () => !teclas.hidden;
  function limpiaMods() { mods.clear(); teclas.querySelectorAll("[data-mod]").forEach(b => b.setAttribute("aria-pressed", "false")); }
  function tecla(k) { empuja("/api/teclas", { combo: [...mods, k] }); limpiaMods(); }
  function escribe(txt) {
    if (!txt) return;
    if (mods.size && txt.length === 1) { empuja("/api/teclas", { combo: [...mods, txt.toLowerCase()] }); limpiaMods(); return; }
    empuja("/api/teclas", { texto: txt });
  }
  kb.addEventListener("beforeinput", e => {
    const it = e.inputType;
    if (it === "insertText" && !e.isComposing) { e.preventDefault(); escribe(e.data || ""); }
    else if (it === "insertLineBreak" || it === "insertParagraph") { e.preventDefault(); tecla("enter"); }
    else if (it === "deleteContentBackward" && !e.isComposing) { e.preventDefault(); tecla("retroceso"); }
    else if (it === "deleteContentForward") { e.preventDefault(); tecla("borrar"); }
    else if (it === "insertFromPaste") { e.preventDefault(); const tx_ = e.dataTransfer && e.dataTransfer.getData("text"); if (tx_) escribe(tx_); }
  });
  kb.addEventListener("compositionend", e => { if (e.data) escribe(e.data); kb.value = ""; });
  kb.addEventListener("input", e => { if (!e.isComposing) kb.value = ""; });
  kb.addEventListener("keydown", e => { const m = { ArrowLeft: "izq", ArrowRight: "der", ArrowUp: "arriba", ArrowDown: "abajo", Escape: "esc", Tab: "tab", Delete: "borrar" }[e.key]; if (m) { e.preventDefault(); tecla(m); } });
  function teclado(v) {
    bTec.setAttribute("aria-pressed", String(v)); bTec.textContent = v ? "Ocultar teclado" : "Teclado"; teclas.hidden = !v;
    if (v) { kb.tabIndex = 0; kb.focus({ preventScroll: true }); } else { kb.blur(); kb.tabIndex = -1; limpiaMods(); }
  }
  /* el foco se queda en el captador al pulsar los botones (si no, el iPhone cerraría el teclado) */
  [bTec, teclas].forEach(el => el.addEventListener("mousedown", e => e.preventDefault()));
  bTec.addEventListener("click", () => teclado(!abierto()));
  /* si lo cierras con el «OK» del iPhone o tocando fuera, el botón se entera */
  kb.addEventListener("blur", () => later(() => { if (abierto() && document.activeElement !== kb) teclado(false); }, 300));
  teclas.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.k) { tecla(b.dataset.k); kb.focus({ preventScroll: true }); }
    else if (b.dataset.mod) { const k = b.dataset.mod, on_ = !mods.has(k); on_ ? mods.add(k) : mods.delete(k); b.setAttribute("aria-pressed", String(on_)); kb.focus({ preventScroll: true }); }
  });
  /* el mando ocupa justo lo que se ve (Safari cambia el alto visible al mostrar barras o teclado) */
  function ajustaAlto() {
    const vv = window.visualViewport;
    if (full && vv) { mando.style.height = vv.height + "px"; mando.style.top = vv.offsetTop + "px"; }
    else { mando.style.height = ""; mando.style.top = ""; }
    pinta();
  }
  if (window.visualViewport) { visualViewport.addEventListener("resize", ajustaAlto); visualViewport.addEventListener("scroll", ajustaAlto); }

  /* ---- atajos y ventanas ---- */
  const ATAJOS = [["Copiar", ["ctrl", "c"]], ["Pegar", ["ctrl", "v"]], ["Cortar", ["ctrl", "x"]], ["Deshacer", ["ctrl", "z"]], ["Rehacer", ["ctrl", "y"]], ["Seleccionar todo", ["ctrl", "a"]],
    ["Guardar", ["ctrl", "s"]], ["Buscar", ["ctrl", "f"]], ["Cambiar de ventana", ["alt", "tab"]], ["Escritorio", ["win", "d"]], ["Administrador de tareas", ["ctrl", "shift", "esc"]],
    ["Pestaña nueva", ["ctrl", "t"]], ["Cerrar pestaña", ["ctrl", "w"]], ["Recargar", ["f5"]], ["Pantalla completa", ["f11"]], ["Explorador", ["win", "e"]], ["Ejecutar", ["win", "r"]],
    ["Captura", ["win", "shift", "s"]], ["Cerrar ventana", ["alt", "f4"]], ["Menú inicio", ["win"]]];
  $("m-atajos").addEventListener("click", () => {
    let o = null; const grid = h("div", { class: "atajos" });
    for (const [n, k] of ATAJOS) grid.append(h("button", { class: "bt", type: "button", onclick: () => { empuja("/api/teclas", { combo: k }); o.close(true); } }, h("span", { text: n }), h("small", { class: "num", text: k.map(x => ({ ctrl: "Ctrl", alt: "Alt", shift: "Mayús", win: "Win", esc: "Esc", tab: "Tab" }[x] || x.toUpperCase())).join("+") })));
    o = Hoja.open({ titulo: "Atajos de teclado", texto: "Se envían al PC tal cual.", cuerpo: grid, onClose: () => kick() });
  });
  $("m-vent").addEventListener("click", () => {
    const ul = h("ul", { class: "wins" }); let o = null;
    const carga = async () => { try { Vent.pinta(ul, await Vent.lista(), a => { if (a === "foco" && o) o.close(true); else later(carga, 400); }); } catch (e) { if (!(e instanceof AuthErr)) ul.replaceChildren(h("li", { class: "vac", text: errText(e) })); } };
    ul.append(h("li", { class: "vac", text: "Buscando ventanas…" }));
    o = Hoja.open({ titulo: "Ventanas", texto: "Toca una para traerla al frente.", cuerpo: ul, onClose: () => kick() }); carga();
  });

  /* ---- barra ---- */
  function pintaModo() { bModo.textContent = modo === "raton" ? "Modo ratón" : "Modo táctil";
    $("m-ay2").textContent = modo === "raton" ? "Arrastra para mover la flecha · toca = clic · dos toques = doble clic · dos dedos = clic derecho · mantén y arrastra = arrastrar"
      : "Toca donde quieras clicar · dos toques = doble clic · mantén = clic derecho · arrastra = arrastrar"; pinta(); }
  bModo.addEventListener("click", () => { modo = modo === "raton" ? "tactil" : "raton"; LS.set("jv_mando", modo); pintaModo(); toast(modo === "raton" ? "Modo ratón: el móvil es un touchpad." : "Modo táctil: tocas directamente donde quieres clicar.", "", 2400); });
  $("m-der").addEventListener("click", () => pulsaDer(!der));
  $("m-zmas").addEventListener("click", () => ponZoom(z * 1.6));
  $("m-zmenos").addEventListener("click", () => ponZoom(z / 1.6));
  $("m-pausa").addEventListener("click", () => { pausa = !pausa; $("m-pausa").setAttribute("aria-pressed", String(pausa)); $("m-pausa").textContent = pausa ? "Seguir" : "Pausa"; if (pausa) { clearTimeout(t); hora.textContent = "en pausa"; } else kick(); });
  function ampliar(v) {
    full = v; mando.classList.toggle("full", v); document.body.classList.toggle("m-full", v);
    $("m-full").textContent = v ? "Salir" : "Abrir mando"; lz.style.aspectRatio = v ? "" : String(ar);
    if (v) {
      api("/api/raton", { accion: "pos" }).then(r => { if (r && typeof r.x === "number") { cx = r.x; cy = r.y; pinta(); } }).catch(() => { });
      try { if (!IOS && mando.requestFullscreen && !document.fullscreenElement) mando.requestFullscreen().then(() => { try { screen.orientation && screen.orientation.lock && screen.orientation.lock("landscape").catch(() => { }); } catch (_) { } }).catch(() => { }); } catch (e) { }
      if (innerHeight > innerWidth) toast("Gira el móvil en horizontal para verlo más grande.", "", 3200);
    } else {
      z = 1; teclado(false); pulsaDer(false);
      try { if (document.fullscreenElement) document.exitFullscreen().catch(() => { }); } catch (e) { }
    }
    ajustaAlto(); later(ajustaAlto, 120); later(ajustaAlto, 500); kick(); programa(0);
  }
  $("m-full").addEventListener("click", () => ampliar(!full));
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && full && !IOS) later(ajustaAlto, 100); });
  addEventListener("keydown", e => { if (e.key === "Escape" && full && !Hoja.pila.length && document.activeElement !== kb) ampliar(false); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); else clearTimeout(t); });
  pintaModo(); ponZoom(1);

  return {
    vista() { },
    cerrar() { clearTimeout(t); cola.length = 0; if (full) ampliar(false); if (url) { URL.revokeObjectURL(url); url = null; } }
  };
})();

/* =============================== equipo y salida =============================== */
$("equipo").addEventListener("click", () => {
  Hoja.open({ titulo: "Equipos", texto: "Por ahora el panel controla un solo PC. Los demás llegarán pronto.",
    cuerpo: h("ul", { class: "equipos" },
      h("li", null, h("span", null, h("b", { text: PC })), h("span", { class: "ya", text: "este" })),
      h("li", { "aria-disabled": "true" }, h("span", { text: "PC sucio" }), h("span", { class: "pronto", text: "pronto" })),
      h("li", { "aria-disabled": "true" }, h("span", { text: "Añadir equipo" }), h("span", { class: "pronto", text: "pronto" }))) });
});
$("salir").addEventListener("click", async () => {
  const b = $("salir"); b.disabled = true;
  try { await api("/logout"); } catch (e) { if (e instanceof AuthErr) return; }
  Session.end("cerrada");
});


/* =============== cielo estrellado (tema Espacio): estrellas tenues que parpadean y derivan muy despacio =============== */
(() => {
  const cv = document.createElement("canvas"); cv.id = "cielo"; cv.setAttribute("aria-hidden", "true"); document.body.prepend(cv);
  const g = cv.getContext("2d"); if (!g) return;
  let W = 0, Hh = 0, D = 1, E = [], raf = 0, last = 0;
  function medir() { D = Math.min(1.5, devicePixelRatio || 1); W = innerWidth; Hh = innerHeight; cv.width = W * D | 0; cv.height = Hh * D | 0; g.setTransform(D, 0, 0, D, 0, 0);
    const n = Math.round(W * Hh * .00016); E = [];
    for (let i = 0; i < n; i++) { const t = Math.random(); E.push({ x: Math.random() * W, y: Math.random() * Hh, r: Math.random() * .9 + .3, b: Math.random() * .5 + .4, ph: Math.random() * 6.28, sp: Math.random() * 1.2 + .4,
      c: t < .08 ? "167,139,250" : t < .2 ? "158,203,255" : "255,255,255" }); }
    pinta(0); }
  function pinta(t) { g.clearRect(0, 0, W, Hh);
    for (const s of E) { const a = RM.matches ? s.b * .7 : s.b * (.62 + .38 * Math.sin(t * .0011 * s.sp + s.ph)); s.y -= RM.matches ? 0 : .006 * s.sp; if (s.y < -2) s.y = Hh + 2;
      g.fillStyle = "rgba(" + s.c + "," + a.toFixed(3) + ")"; g.beginPath(); g.arc(s.x, s.y, s.r, 0, 6.283); g.fill(); } }
  function bucle(t) { if (document.hidden) { raf = 0; return; } if (t - last > 33) { pinta(t); last = t; } raf = requestAnimationFrame(bucle); }
  let rz = 0; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(medir, 200); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !raf && !RM.matches) raf = requestAnimationFrame(bucle); });
  medir(); if (!RM.matches) raf = requestAnimationFrame(bucle);
})();

/* arranque */
addEventListener("keydown", e => { if (e.key === "/" && !/TEXTAREA|INPUT/.test((document.activeElement || {}).tagName || "") && !Hoja.pila.length) { e.preventDefault(); ir("conv"); Chat.textarea.focus(); } });
P.start(); pollSismo.start(); Chat.cargar();
["control", "lanzar"].forEach(v => (alMostrar[v] || []).forEach(f => { try { f(); } catch (e) { } }));
Pollers.forEach(p => p._vista && p.start());
})();
