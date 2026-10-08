/* Pulso: datos del PC para los prototipos (fase 1). Sin dependencias. Expone window.Pulso.
   - Sondea /api/estado (2,5 s, solo con la pestaña visible) y /api/watchdog (20 s).
   - Normaliza el texto de estado (mismo formato que jarvis.estado()).
   - Detecta pérdida de señal (2 fallos seguidos o >8 s sin respuesta) y vuelta (con reinicio si el uptime retrocede).
   - Gobernador de calidad: mide el frame-time y sube/baja un nivel (0..3) con histéresis.
   Todo texto del servidor se pinta con textContent en las vistas. Nada se guarda en localStorage. */
(function () {
  "use strict";
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const num = s => parseFloat(String(s).replace(",", "."));

  function parseEstado(text) {
    const T = String(text || ""), o = { ok: false }; let m;
    if ((m = T.match(/CPU\s+(\d+(?:[.,]\d+)?)\s*%/i))) { o.cpu = num(m[1]); o.ok = true; }
    if ((m = T.match(/RAM\s+libre\s+(\d+)\s*MB\s+de\s+(\d+)/i))) { o.ramFree = +m[1]; o.ramTot = +m[2]; o.ok = true; }
    const gl = (T.match(/^GPU.*$/im) || [""])[0];
    if ((m = gl.match(/GPU\s+(\d+(?:[.,]\d+)?)\s*°?\s*C/i))) {
      o.gpu = { t: num(m[1]) };
      if ((m = gl.match(/(\d+(?:[.,]\d+)?)\s*W\b/))) o.gpu.w = num(m[1]);
      if ((m = gl.match(/(\d+(?:[.,]\d+)?)\s*%\s*uso/i))) o.gpu.u = num(m[1]);
      if ((m = gl.match(/VRAM\s+(\d+)\s*\/\s*(\d+)\s*MB/i))) { o.gpu.vu = +m[1]; o.gpu.vt = +m[2]; }
      if ((m = gl.match(/\b(P\d{1,2})\b/))) o.gpu.ps = m[1];
    } else if (gl) o.gpuErr = gl.replace(/^GPU:?\s*/i, "");
    if ((m = T.match(/Disco\s+([A-Z]:)\s+libre\s+(\d+(?:[.,]\d+)?)\s*GB/i))) o.disk = { d: m[1], free: num(m[2]) };
    if ((m = T.match(/Encendido desde hace\s+(?:(\d+)\s*(?:days?|d[ií]as?)\s*,?\s*)?(\d+):(\d{2}):(\d{2})/i)))
      o.up = (+(m[1] || 0)) * 86400 + (+m[2]) * 3600 + (+m[3]) * 60 + (+m[4]);
    if ((m = T.match(/Watchdog:\s*([^\n(]+?)\s*(?:\(.*?hace\s+(\d+)\s*s\))?\s*$/im))) o.wd = { ok: /activo/i.test(m[1]), age: m[2] != null ? +m[2] : null };
    return o;
  }

  async function api(path, body, ms) {
    const ac = new AbortController(), to = setTimeout(() => ac.abort(), ms || 7000);
    try {
      const r = await fetch(path, { method: "POST", signal: ac.signal, credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Jarvis": "1" }, body: JSON.stringify(body || {}) });
      if (r.status === 401) throw Object.assign(new Error("sesion"), { auth: true });
      if (!r.ok) throw new Error("http " + r.status);
      return await r.json();
    } finally { clearTimeout(to); }
  }

  const P = {
    d: null, wd: null, lastOk: 0, fails: 0, lost: false, lostAt: 0, hist: [], listeners: {},
    on(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    emit(ev, x) { (this.listeners[ev] || []).forEach(f => { try { f(x); } catch (e) { console.error(e); } }); },
    async tick() {
      clearTimeout(this._t);
      if (document.hidden) return;
      const t0 = performance.now();
      try {
        const j = await api("/api/estado");
        const d = parseEstado(j.text); d.lat = Math.round(performance.now() - t0); d.at = Date.now();
        const prev = this.d;
        if (this.lost) { this.lost = false; this.emit("back", { reboot: prev && d.up != null && prev.up != null && d.up < prev.up, d }); }
        else if (prev && d.up != null && prev.up != null && d.up + 30 < prev.up) this.emit("back", { reboot: true, d });
        this.d = d; this.lastOk = Date.now(); this.fails = 0;
        this.hist.push({ t: d.at, gt: d.gpu ? d.gpu.t : null, gw: d.gpu ? d.gpu.w : null, cpu: d.cpu }); if (this.hist.length > 240) this.hist.shift();
        this.emit("data", d);
      } catch (e) {
        if (e.auth) { this.emit("auth"); return; }
        this.fails++;
        if (!this.lost && (this.fails >= 2 || Date.now() - this.lastOk > 8000)) { this.lost = true; this.lostAt = this.lastOk || Date.now(); this.emit("lost", { since: this.lostAt }); }
      }
      this._t = setTimeout(() => this.tick(), this.lost ? 4000 : 2500);
    },
    async tickWd() {
      clearTimeout(this._w);
      if (!document.hidden && !this.lost) {
        try { this.wd = await api("/api/watchdog"); this.emit("wd", this.wd); } catch (e) { /* silencioso: el estado ya avisa */ }
      }
      this._w = setTimeout(() => this.tickWd(), 20000);
    },
    start() { this.tick(); this.tickWd(); },
    api, parseEstado, clamp
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { P.tick(); } });

  /* Gobernador de calidad: llamar Gov.frame(dt) cada fotograma; avisa con onLevel(n) cuando cambia. */
  const Gov = {
    level: 2, max: 3, ema: 16.7, n: 0, cool: 0, onLevel: null,
    frame(dt) {
      if (dt > 250) return;                         // vuelta de segundo plano: no cuenta
      this.ema += (dt - this.ema) * 0.05; this.n++;
      if (this.n < 45 || --this.cool > 0) return;
      if (this.ema > 21 && this.level > 0) { this.level--; this.cool = 90; this.onLevel && this.onLevel(this.level); }
      else if (this.ema < 14.5 && this.level < this.max) { this.level++; this.cool = 240; this.onLevel && this.onLevel(this.level); }
    }
  };
  window.__gov = () => ({ level: Gov.level, ema: +Gov.ema.toFixed(2) });

  /* Veredicto en lenguaje llano: lo primero que se lee. Nunca inventa: solo usa estado + vigilante. */
  P.veredicto = function (d, wd) {
    if (!d) return "";
    const g = d.gpu || {}; let a;
    if (g.t >= 83) a = "Muy caliente."; else if (g.t >= 70) a = "Caliente y trabajando."; else if (g.u >= 50 || d.cpu >= 60) a = "Trabajando."; else a = "Tranquilo.";
    if (d.wd && !d.wd.ok) return a + " El vigilante está parado.";
    if (wd && wd.hoy && wd.hoy.arranques_hoy != null) { const r = wd.hoy.arranques_hoy - 1;
      return a + (r <= 0 ? " Sin reinicios hoy." : r === 1 ? " Un reinicio hoy." : ` ${r} reinicios hoy.`); }
    return a;
  };
  /* Frase de estado en segmentos [texto, destacado]. Las cifras se destacan por peso, no por color. */
  P.frase = function (d, wd) {
    if (!d) return [];
    const g = d.gpu || {}, out = [];
    const v = P.veredicto(d, null).replace(/ El vigilante.*/, "");
    out.push([v + " "]);
    if (g.t != null) { out.push(["La gráfica está a "]); out.push([Math.round(g.t) + " °C", 1]); }
    if (d.up != null) { const t = new Date(Date.now() - d.up * 1000);
      out.push([g.t != null ? " y no se ha reiniciado desde las " : "Encendido desde las "]);
      out.push([t.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }), 1]); }
    out.push(["."]);
    if (d.wd && !d.wd.ok) out.push([" El vigilante está parado.", 1]);
    else if (wd && wd.hoy) { const r = wd.hoy.arranques_hoy - 1; if (r > 0) { out.push([" Hoy lleva "]); out.push([String(r) + (r === 1 ? " reinicio" : " reinicios"), 1]); out.push(["."]); } }
    return out;
  };
  P.pinta = function (el, segs) { el.textContent = ""; for (const [t, b] of segs) { if (b) { const x = document.createElement("b"); x.textContent = t; el.append(x); } else el.append(t); } };
  P.Gov = Gov;
  P.reduced = matchMedia("(prefers-reduced-motion: reduce)");
  P.fmt = {
    n1: v => (Math.round(v * 10) / 10).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    n0: v => Math.round(v).toLocaleString("es-ES"),
    gb: mb => (mb / 1024).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    up(s) { if (s == null) return "—"; const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
      return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`; },
    hora: t => new Date(t).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
  };
  window.Pulso = P;
})();
