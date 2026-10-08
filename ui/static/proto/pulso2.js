/* pulso2.js: sustituto directo de pulso.js. window.Pulso conserva EXACTAMENTE la misma superficie
   (copia literal de pulso.js) y suma un único miembro nuevo: Pulso.Termo (motor térmico de la fase 2). */
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

/* ==========================================================================================
   Pulso.Termo: motor térmico (fase 2). WebGL2 (o WebGL1) escrito a mano, sin librerías.
   - La anatomía del PC (ventilador, disipador con aletas, RAM con chips, bomba de la CPU, fuente,
     cables trenzados, rejillas) se HORNEA una vez por tamaño en 2 texturas de "bases de calor"
     (8 canales: desfase estructural, tarjeta, núcleo, CPU, RAM, fuente, VRAM, penacho).
   - Cada fotograma es UN pase: 2 lecturas de bases + 2 de ruido + 1–3 de paleta, ventiladores
     procedurales con desenfoque de movimiento analítico, convección, grano, aberración y viñeta.
   - El mapa de calor se consulta en JS con el MISMO modelo (bases leídas del GPU una vez).
   - Rango automático como una cámara real (AGC): lo = ambiente − 3; hi = máx(48, GPU + 6).
   Uso: const T = Pulso.Termo.mount(canvas, {auto:true}); T.heatAt(x,y); T.parts(); T.range().
   ========================================================================================== */
(function () {
  "use strict";
  const P = window.Pulso, clamp = P.clamp, RM = P.reduced;
  const SW = 400, SH = 500;                          /* espacio de escena (unidades) */
  const RAMPA = [[0, "#0b0716"], [.22, "#3a1646"], [.48, "#a21c6b"], [.74, "#ff7a1a"], [1, "#fff3d6"]];
  const PARTS = [                                    /* rectángulos en escena; c = punto de medida */
    {id: "gpu", name: "Gráfica",    x: 20,  y: 300, w: 336, h: 104, c: [188, 358]},
    {id: "cpu", name: "Procesador", x: 174, y: 130, w: 80,  h: 80,  c: [214, 170]},
    {id: "ram", name: "Memoria",    x: 282, y: 116, w: 52,  h: 150, c: [308, 190]},
    {id: "nvme",name: "Disco",      x: 144, y: 238, w: 92,  h: 16,  c: [190, 246]},
    {id: "psu", name: "Fuente",     x: 22,  y: 435, w: 164, h: 56,  c: [104, 463]}];
  /* ventiladores: x, y, radio, aspas (3 de la gráfica + trasero de la caja) */
  const FANS = [[90, 358, 43, 9], [188, 358, 43, 9], [286, 358, 43, 9], [66, 175, 46, 7]];
  const LEVELS = [.5, .65, .8, 1];                  /* escala de resolución interna × DPR (máx. 2) */

  /* ---------------------------------------------------------------- GLSL */
  const VS1 = "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}";
  const VS2 = "#version 300 es\nin vec2 a;void main(){gl_Position=vec4(a,0.,1.);}";
  const COMMON = `
float hs(vec2 p){p=fract(p*vec2(.1031,.1030));p+=dot(p,p.yx+33.33);return fract((p.x+p.y)*p.x);}
float bx(vec2 p,vec2 c,vec2 e,float r){vec2 d=abs(p-c)-e+r;return length(max(d,0.))+min(max(d.x,d.y),0.)-r;}
float gs(float d,float s){d=max(d,0.);return exp(-d*d/(s*s));}
float st(float v,float w){return .5+.5*cos(6.2832*v/w);}
`;
  /* Horneado de la anatomía (una vez por tamaño). Desfases en °C sobre el ambiente; bases 0..1. */
  const BAKE = `uniform vec2 BR;uniform float PS;
vec4 A;vec4 B;
float vn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hs(i),hs(i+vec2(1.,0.)),f.x),mix(hs(i+vec2(0.,1.)),hs(i+vec2(1.,1.)),f.x),f.y);}
float fl(float d){return clamp(.5-d/.9,0.,1.);}
void L(float m,vec4 a,vec4 b){A=mix(A,a,m);B=mix(B,b,m);}
vec2 sg(vec2 p,vec2 a,vec2 b){vec2 pa=p-a,ba=b-a;float h=clamp(dot(pa,ba)/dot(ba,ba),0.,1.);return vec2(length(pa-ba*h),h*length(ba));}
vec2 cb(vec2 p,vec2 a,vec2 b,vec2 c){vec2 s=sg(p,a,b),t=sg(p,b,c);t.y+=length(b-a);return s.x<t.x?s:t;}
void tb(vec2 dl,float r,float o,vec4 ha,vec4 hb){float k=dl.x/r;
 float br=st(dl.y+dl.x*1.4,3.2)*st(dl.y-dl.x*1.4,3.2);
 L(fl(dl.x-r),vec4(o+1.1*br-1.8*k*k,ha.yzw*(1.-.35*k*k)),hb);}
void main(){
 vec2 p=vec2(gl_FragCoord.x,BR.y-gl_FragCoord.y)/BR*vec2(400.,500.);
 float n=vn(p*.07),m,fn,r;
 A=vec4(-1.4+.7*n+.3*vn(p*vec2(.015,.35)),0.,0.,0.);B=vec4(0.);
 L(fl(p.x-18.)*.8,vec4(-.7+.5*st(p.y,5.),0.,0.,0.),B);
 for(int i=0;i<6;i++){float y=304.+float(i)*17.;L(fl(bx(p,vec2(10.,y),vec2(7.,6.),1.)),vec4(.2+.7*st(p.x,2.5),.24,0.,0.),vec4(0.));}
 {float d=bx(p,vec2(66.,175.),vec2(52.),6.);L(fl(d),vec4(.4-1.*smoothstep(-5.,0.,d),0.,0.,0.),vec4(0.));
  vec2 g=p/vec2(5.,4.33);g.x+=mod(floor(g.y),2.)*.5;vec2 gf=(fract(g)-.5)*vec2(5.,4.33);
  L(fl(length(p-vec2(66.,175.))-45.),vec4(-.6-2.2*fl(length(gf)-1.6),0.,0.,0.),vec4(0.));
  for(int i=0;i<4;i++){vec2 c=vec2(66.,175.)+vec2(i<2?-46.:46.,mod(float(i),2.)<.5?-46.:46.);L(fl(length(p-c)-2.6),vec4(-2.,0.,0.,0.),vec4(0.));}}
 float hl=st(p.x+mod(floor(p.y/4.),2.)*2.,4.)*st(p.y,4.);
 L(fl(p.y-13.),vec4(-.9+1.8*hl*hl,0.,0.,.14*hl),vec4(0.));
 for(int i=0;i<2;i++){L(fl(bx(p,vec2(372.,84.+float(i)*86.),vec2(8.,28.),7.)),vec4(-2.4,0.,0.,0.),vec4(0.));}
 m=fl(bx(p,vec2(238.,176.),vec2(118.,129.),4.));
 float h=hs(floor(p/9.));vec2 f=fract(p/9.)*9.;
 float cp=step(.76,h)*fl(bx(f,vec2(4.5),vec2(1.4+h*1.6,.9+h*.5),.4));
 float tr=pow(st(p.x*.7+p.y*.7,7.),10.)*.6+pow(st(p.x-p.y*.3,11.),14.)*.5;
 L(m,vec4(.6+.7*tr+3.2*cp+.5*n+1.3*vn(p*.018),0.,0.,.24*gs(bx(p,vec2(214.,170.),vec2(46.),12.),30.)),vec4(.16*gs(bx(p,vec2(308.,190.),vec2(28.,76.),2.),14.),0.,0.,0.));
 for(int i=0;i<3;i++)for(int j=0;j<2;j++){vec2 c=vec2(128.+float(i)*104.,56.+float(j)*228.);L(fl(length(p-c)-3.2)*.9,vec4(-1.9,0.,0.,0.),vec4(0.));}
 m=fl(bx(p,vec2(245.,32.),vec2(136.,15.),2.));fn=st(p.x,2.4);
 L(m,vec4(.2+1.3*fn,0.,0.,.26+.14*fn),vec4(0.));
 L(fl(bx(p,vec2(114.,32.),vec2(6.,17.),2.)),vec4(.9,0.,0.,.34),vec4(0.));
 L(fl(bx(p,vec2(376.,32.),vec2(6.,17.),2.)),vec4(.9,0.,0.,.34),vec4(0.));
 for(int i=0;i<8;i++){L(fl(bx(p,vec2(164.+float(i)*13.5,127.),vec2(4.,2.6),.5)),vec4(1.8,0.,0.,.8),vec4(0.));L(fl(bx(p,vec2(158.,138.+float(i)*11.5),vec2(2.6,4.),.5)),vec4(1.8,0.,0.,.8),vec4(0.));}
 m=fl(bx(p,vec2(212.,113.),vec2(58.,8.),2.));fn=st(p.x,3.2);
 L(m,vec4(.7+1.9*fn,0.,0.,.48+.26*fn),vec4(0.));
 m=fl(bx(p,vec2(146.,176.),vec2(7.,50.),2.));fn=st(p.y,3.2);
 L(m,vec4(.7+1.9*fn,0.,0.,.48+.26*fn),vec4(0.));
 r=length(p-vec2(214.,170.));
 L(fl(r-40.),vec4(1.3-1.9*smoothstep(31.,40.,r),0.,0.,.5),vec4(0.));
 A.w+=.42*gs(abs(r-34.)-2.,2.5)*fl(r-40.);
 L(fl(r-23.),vec4(-1.1+.4*st(r,5.),0.,0.,.27),vec4(0.));
 L(fl(abs(r-12.)-.8),vec4(-2.1,0.,0.,.2),vec4(0.));
 tb(cb(p,vec2(195.,135.),vec2(178.,96.),vec2(150.,46.)),4.6,.5,vec4(0.,0.,0.,.42),vec4(0.));
 tb(cb(p,vec2(209.,130.),vec2(203.,92.),vec2(180.,46.)),4.6,.5,vec4(0.,0.,0.,.42),vec4(0.));
 for(int i=0;i<4;i++){float x=287.+float(i)*13.;
  float dr=bx(p,vec2(x,190.),vec2(4.3,73.),1.);L(fl(dr),vec4(.6+.3*st(p.y,3.)-1.2*smoothstep(-2.5,0.,dr),0.,0.,0.),vec4(.5,0.,0.,0.));
  for(int j=0;j<8;j++){L(fl(bx(p,vec2(x,129.+float(j)*17.5),vec2(3.,6.2),.8)),vec4(1.,0.,0.,0.),vec4(1.,0.,0.,0.));}
  L(fl(bx(p,vec2(x,114.),vec2(4.6,3.),.5)),vec4(.2,0.,0.,0.),vec4(.15,0.,0.,0.));
  L(fl(bx(p,vec2(x,266.),vec2(4.6,3.),.5)),vec4(.2,0.,0.,0.),vec4(.15,0.,0.,0.));}
 L(fl(bx(p,vec2(190.,246.),vec2(46.,8.),2.)),vec4(2.+1.1*st(p.x,4.),0.,0.,.06),vec4(0.));
 L(fl(bx(p,vec2(268.,284.),vec2(26.,12.),3.)),vec4(4.+1.2*st(p.x+p.y,5.),0.,0.,.08),vec4(0.));
 L(fl(bx(p,vec2(346.,200.),vec2(5.5,36.),1.)),vec4(.8+.7*st(p.y,4.),0.,0.,0.),vec4(0.,.18,0.,0.));
 for(int k=0;k<6;k++){float y=172.+float(k)*11.5,x=389.-float(k)*5.;
  tb(cb(p,vec2(351.,y),vec2(x,y+4.),vec2(x,430.)),2.4,.3,vec4(0.),vec4(0.,.22,0.,0.));}
 for(int k=0;k<3;k++){float x=329.+float(k)*5.;tb(cb(p,vec2(x,292.),vec2(x+3.,284.),vec2(362.,282.+float(k)*3.)),2.3,.3,vec4(0.,.1,0.,0.),vec4(0.,.3,0.,0.));}
 vec2 dc=vec2(188.,358.);
 float hc=gs(bx(p,vec2(188.,352.),vec2(168.,52.),6.),24.);
 A.y=max(A.y,.4*hc);
 m=fl(bx(p,vec2(188.,352.),vec2(168.,52.),5.));
 float dk=bx(p,vec2(188.,352.),vec2(168.,52.),5.);vec4 ca=vec4(.6-1.6*smoothstep(-7.,0.,dk),.4,0.,0.);
 float g1=abs(p.x-139.-(p.y-358.)*.35),g2=abs(p.x-237.+(p.y-358.)*.35);
 ca.x-=1.2*(gs(g1,1.4)+gs(g2,1.4)+gs(abs(p.y-397.),1.2));
 fn=st(p.x,2.3);
 ca=mix(ca,vec4(.3+1.1*fn,.6+.4*fn,0.,0.),fl(bx(p,vec2(188.,306.),vec2(166.,6.),1.)));
 L(m,ca,vec4(0.));
 for(int i=0;i<3;i++){fn=st(p.x,2.2);L(fl(length(p-vec2(90.+float(i)*98.,358.))-43.),vec4(.2+1.*fn,.7+.3*fn,0.,0.),vec4(0.));}
 vec2 q=p-dc;
 float co=exp(-dot(q,q)/450.);
 co=max(co,.74*exp(-q.x*q.x/2600.-(p.y-306.)*(p.y-306.)/72.));
 A.z=max(co,.5*exp(-dot(q,q)/7000.))*m;
 for(int k=0;k<8;k++){float an=float(k)*.7854+.39;vec2 c=dc+31.*vec2(cos(an),sin(an));B.z=max(B.z,.6*fl(bx(p,c,vec2(4.),1.))+.35*gs(length(p-c)-4.,6.));}
 B.z*=m;
 L(fl(bx(p,vec2(334.,296.),vec2(10.,4.5),1.)),vec4(.6,.3,0.,0.),vec4(0.,.3,0.,0.));
 L(fl(bx(p,vec2(15.,352.),vec2(5.,56.),1.)),vec4(.1+.6*st(p.y,6.),.32,0.,0.),vec4(0.));
 L(fl(418.-p.y),vec4(.2+.5*n,.5*hc,0.,0.),vec4(0.,.1,0.,0.));
 L(fl(abs(p.y-421.)-3.),vec4(1.,.6*hc,0.,0.),vec4(0.,.08,0.,0.));
 vec2 hp=p/vec2(6.5,5.63);hp.x+=mod(floor(hp.y),2.)*.5;vec2 hf=(fract(hp)-.5)*vec2(6.5,5.63);
 float ho=fl(length(hf)-2.1),ps=gs(bx(p,vec2(104.,468.),vec2(58.,22.),4.),16.);
 L(fl(bx(p,vec2(104.,463.),vec2(82.,28.),3.)),vec4(.1+.7*ho,0.,0.,0.),vec4(0.,mix(.2,.35+.65*ps,ho),0.,0.));
 L(fl(bx(p,vec2(376.,426.),vec2(17.,5.),4.)),vec4(-2.,0.,0.,0.),vec4(0.));
 L(fl(bx(p,vec2(290.,462.),vec2(46.,12.),2.))*.6,vec4(1.2,0.,0.,0.),vec4(0.,.18,0.,0.));
 float ed=min(min(p.x,400.-p.x),min(p.y,500.-p.y));
 A.x-=1.6*(1.-smoothstep(0.,26.,ed));
 A.x+=1.5*smoothstep(430.,0.,p.y);
 B.w=clamp(smoothstep(300.,230.,p.y)*smoothstep(20.,140.,p.y)*exp(-(p.x-196.)*(p.x-196.)/22500.)+.5*smoothstep(130.,60.,p.y)*smoothstep(8.,40.,p.y)*exp(-(p.x-230.)*(p.x-230.)/16900.),0.,1.);
 FC=PS<.5?vec4(clamp((A.x+4.)/16.,0.,1.),clamp(A.yzw,0.,1.)):clamp(B,0.,1.);
}`;
  /* Difusión del calor (horneado): gaussiana separable a 100×125 y mezcla con la base nítida. */
  const BLUR = `uniform sampler2D S;uniform vec2 BR,DR;
void main(){vec2 uv=gl_FragCoord.xy/BR;vec4 c=TX(S,uv)*.227;
 c+=(TX(S,uv+DR*1.385)+TX(S,uv-DR*1.385))*.3162;c+=(TX(S,uv+DR*3.231)+TX(S,uv-DR*3.231))*.0703;FC=c;}`;
  const COMB = `uniform sampler2D S,Bl;uniform vec2 BR;uniform float PS;
void main(){vec2 uv=gl_FragCoord.xy/BR;vec4 s=TX(S,uv),b=TX(Bl,uv);
 FC=PS<.5?vec4(mix(s.x,b.x,.4),min(vec3(1.),s.yzw+.7*b.yzw)):vec4(min(vec3(1.),s.xyz+.7*b.xyz),b.w);}`;
  /* Pase único por fotograma. */
  const MAIN = `uniform vec2 R;uniform vec4 FT;uniform sampler2D T0,T1,TN,TL;uniform float TI;
uniform vec4 V0,V1,V2,FX,FA,FB;uniform vec3 LU;
float I(float u,float d){return floor(u)*d+min(fract(u),d);}
float fan(vec2 p,vec2 c,float Rf,float nb,float an,float bl,float Tm,float amb,float k){
 vec2 d=p-c;float r=length(d);if(r>Rf+3.)return Tm;float rr=r/Rf;
 if(r<Rf){
  if(rr<.3){Tm=mix(amb+1.,Tm,.9)-.9*gs(abs(rr-.21)*Rf,.8);}
  else{float u=nb*(atan(d.y,d.x)-an)/6.2832+.55*rr,du=.6-.22*rr;
   float w=nb*bl/6.2832+nb*k/(6.2832*r)+.001;
   float cv=(I(u+w*.5,du)-I(u-w*.5,du))/w;
   Tm=mix(Tm,mix(amb+1.3,Tm,.38),cv*.94);}}
 float ri=smoothstep(Rf-1.5,Rf,r)*smoothstep(Rf+3.,Rf+1.5,r);
 return mix(Tm,amb+1.5+.25*(Tm-amb),ri);}
vec3 lut(float x){return TX(TL,vec2(clamp(x,0.,1.)*.996+.002,.5)).rgb;}
void main(){
 vec2 px=vec2(gl_FragCoord.x,R.y-gl_FragCoord.y);
 vec2 p=(px-FT.yz)*FT.x;float k=FT.x;
 if(LU.z>0.){vec2 d=p-LU.xy;if(length(d)<LU.z){p=LU.xy+d*.5;k*=.5;}}
 float amb=V0.x,U=V1.z;
 float pm=smoothstep(300.,230.,p.y)*smoothstep(20.,140.,p.y)*exp(-(p.x-196.)*(p.x-196.)/22500.);
 vec2 q=p*vec2(.0075,.0055)+vec2(0.,TI*(.04+.2*U));
 vec4 n1=TX(TN,q+.25*TX(TN,q*.5+vec2(TI*.01,0.)).ba),n2=TX(TN,q*1.7+vec2(.31,TI*.09));
 float nn=n1.r*.75+n2.g*.25;
 vec2 w=(vec2(n1.b,n2.a)-.5)*(.7+2.*U)*(.25+pm);
 vec2 uv=(p+w)/vec2(400.,500.);uv.y=1.-uv.y;
 vec4 a=TX(T0,uv),b=TX(T1,uv);
 float ins=step(0.,uv.x)*step(uv.x,1.)*step(0.,uv.y)*step(uv.y,1.);
 a=mix(vec4(.15+.05*n1.r,0.,0.,0.),a,ins);b*=ins;
 float core=pow(max(a.z,1e-4),V1.w);
 float Tm=amb+a.x*16.-4.+V0.y*max(FT.w*a.y,core)+V0.z*a.w+V0.w*b.x+V1.x*b.y+V0.y*.12*V1.y*b.z;
 Tm+=b.w*smoothstep(.45,.95,nn)*(V0.y*.1+.7)*(.3+U);
 Tm=fan(p,vec2(90.,358.),43.,9.,FA.x,FB.x,Tm,amb,k);
 Tm=fan(p,vec2(188.,358.),43.,9.,FA.y,FB.y,Tm,amb,k);
 Tm=fan(p,vec2(286.,358.),43.,9.,FA.z,FB.z,Tm,amb,k);
 Tm=fan(p,vec2(66.,175.),46.,7.,FA.w,FB.w,Tm,amb,k);
 Tm=mix(amb-5.,Tm,FX.w);Tm=mix(Tm,amb-2.+.4*(Tm-amb),FX.x);
 float x=(Tm-V2.x)/(V2.y-V2.x)+V2.w;
 x+=(hs(floor(px/1.6)+V2.z)-.5)*.024+(hs(vec2(floor(px.x/1.6),7.))-.5)*.008;
 x=mix(x,.33,FX.z);
 vec3 col=lut(x);
#ifdef DV
 float ca=length(vec2(dFdx(x),dFdy(x)));vec2 cu=px/R-.5;
 ca*=(1.+2.5*dot(cu,cu))*1.3*smoothstep(.45,.8,x);
 col.r=lut(x+ca).r;col.b=lut(x-ca).b;
#endif
 vec2 u2=px/R;col*=mix(.5,1.,smoothstep(1.2,.3,length((u2-vec2(.5,.47))*vec2(1.,.85))));
 col*=1.-.3*FX.x;
 FC=vec4(mix(col,vec3(1.,.97,.9),FX.y),1.);
}`;

  /* ---------------------------------------------------------------- utilidades */
  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  function lutBytes() {
    const o = new Uint8Array(256 * 4), S = RAMPA.map(([t, h]) => [t, hex(h)]);
    for (let i = 0; i < 256; i++) {
      const x = i / 255; let j = 0; while (j < S.length - 2 && x > S[j + 1][0]) j++;
      const [t0, c0] = S[j], [t1, c1] = S[j + 1], f = clamp((x - t0) / (t1 - t0), 0, 1);
      for (let c = 0; c < 3; c++) o[i * 4 + c] = Math.round(c0[c] + (c1[c] - c0[c]) * f);
      o[i * 4 + 3] = 255;
    }
    return o;
  }
  function noiseBytes() {                          /* 64×64 ruido suave y periódico (4 canales independientes) */
    const N = 64, r = new Float32Array(N * N * 4), o = new Uint8Array(N * N * 4);
    let s = 1234567; const rnd = () => ((s = (Math.imul(s, 1103515245) + 12345) >>> 0) / 4294967296);
    for (let i = 0; i < r.length; i++) r[i] = rnd();
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) for (let c = 0; c < 4; c++) {
      let a = 0; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) a += r[(((y + dy + N) % N) * N + ((x + dx + N) % N)) * 4 + c];
      o[(y * N + x) * 4 + c] = Math.round(clamp((a / 9 - .5) * 2.6 + .5, 0, 1) * 255);
    }
    return o;
  }
  /* Bases de calor: {w,h,a,b} con a/b Float32 0..1 (fila 0 = arriba de la escena). Muestreo bilineal. */
  function samp(Q, x, y, out) {
    const fx = clamp(x / SW * Q.w - .5, 0, Q.w - 1), fy = clamp(y / SH * Q.h - .5, 0, Q.h - 1);
    const x0 = fx | 0, y0 = fy | 0, x1 = Math.min(x0 + 1, Q.w - 1), y1 = Math.min(y0 + 1, Q.h - 1), u = fx - x0, v = fy - y0;
    for (let c = 0; c < 8; c++) {
      const A = c < 4 ? Q.a : Q.b, k = c & 3, g = (i, j) => A[(j * Q.w + i) * 4 + k];
      out[c] = (g(x0, y0) * (1 - u) + g(x1, y0) * u) * (1 - v) + (g(x0, y1) * (1 - u) + g(x1, y1) * u) * v;
    }
    return out;
  }
  /* EL modelo (idéntico al del shader, sin ruido ni aspas): °C en un punto a partir de sus 8 bases. */
  function model(s, S) {
    const core = Math.pow(Math.max(s[2], 1e-4), S.bre);
    let T = S.amb + s[0] * 16 - 4 + S.dG * Math.max(S.hf * s[1], core) + S.dC * s[3] + S.dR * s[4] + S.dP * s[5] + S.dG * .12 * S.vr * s[6];
    T = S.amb - 5 + (T - S.amb + 5) * S.dev;
    return T + (S.amb - 2 + .4 * (T - S.amb) - T) * S.cold;
  }
  /* Horneado en JS (respaldo sin WebGL): la misma anatomía, simplificada, a baja resolución. */
  function bakeJS(w, h) {
    const a = new Float32Array(w * h * 4), b = new Float32Array(w * h * 4);
    const bx = (x, y, cx, cy, ex, ey, r) => { const dx = Math.abs(x - cx) - ex + r, dy = Math.abs(y - cy) - ey + r;
      return Math.hypot(Math.max(dx, 0), Math.max(dy, 0)) + Math.min(Math.max(dx, dy), 0) - r; };
    const fl = d => clamp(.5 - d / 2.5, 0, 1), st = (v, k) => .5 + .5 * Math.cos(6.2832 * v / k), gs = (d, s) => { d = Math.max(d, 0); return Math.exp(-d * d / (s * s)); };
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      const x = (i + .5) / w * SW, y = (j + .5) / h * SH, A = [-1.2, 0, 0, 0], B = [0, 0, 0, 0];
      const L = (m, va, vb) => { for (let c = 0; c < 4; c++) { A[c] += (va[c] - A[c]) * m; B[c] += (vb[c] - B[c]) * m; } };
      L(fl(bx(x, y, 238, 176, 118, 129, 4)), [1.1, 0, 0, .24 * gs(bx(x, y, 214, 170, 46, 46, 12), 30)], [0, 0, 0, 0]);
      L(fl(bx(x, y, 245, 32, 136, 15, 2)), [.8, 0, 0, .3], [0, 0, 0, 0]);
      L(fl(bx(x, y, 212, 113, 58, 8, 2)), [1.5, 0, 0, .6], [0, 0, 0, 0]);
      L(fl(bx(x, y, 146, 176, 7, 50, 2)), [1.5, 0, 0, .6], [0, 0, 0, 0]);
      const r = Math.hypot(x - 214, y - 170);
      L(fl(r - 40), [.4, 0, 0, .5 + .42 * gs(Math.abs(r - 34) - 2, 3)], [0, 0, 0, 0]); L(fl(r - 23), [-1.1, 0, 0, .27], [0, 0, 0, 0]);
      for (let k = 0; k < 4; k++) { const sx = 287 + k * 13; L(fl(bx(x, y, sx, 190, 4.3, 73, 1)), [.8, 0, 0, 0], [.5 + .5 * st(y - 129, 17.5), 0, 0, 0]); }
      L(fl(bx(x, y, 190, 246, 46, 8, 2)), [2.4, 0, 0, .06], [0, 0, 0, 0]);
      L(fl(bx(x, y, 268, 284, 26, 12, 3)), [3.2, 0, 0, 0], [0, 0, 0, 0]);
      for (let k = 0; k < 6; k++) { const cx = 389 - k * 5; if (y > 172 + k * 11.5) L(fl(Math.abs(x - cx) - 2.4), [.6, 0, 0, 0], [0, .22, 0, 0]); }
      const hc = gs(bx(x, y, 188, 352, 168, 52, 6), 24); A[1] = Math.max(A[1], .4 * hc);
      const m = fl(bx(x, y, 188, 352, 168, 52, 5));
      L(m, y < 312 ? [.3 + 1.1 * st(x, 2.3), .8, 0, 0] : [.6, .42, 0, 0], [0, 0, 0, 0]);
      for (let k = 0; k < 3; k++) L(fl(Math.hypot(x - 90 - k * 98, y - 358) - 43), [.7, .85, 0, 0], [0, 0, 0, 0]);
      const qx = x - 188, qy = y - 358;
      A[2] = Math.max(Math.exp(-(qx * qx + qy * qy) / 450), .74 * Math.exp(-qx * qx / 2600 - (y - 306) * (y - 306) / 72), .42 * Math.exp(-(qx * qx + qy * qy) / 5000)) * m;
      B[2] = m * gs(Math.abs(Math.hypot(qx, qy) - 31) - 3, 4);
      L(fl(418 - y), [.3, .5 * hc, 0, 0], [0, .1, 0, 0]);
      L(fl(bx(x, y, 104, 463, 82, 28, 3)), [.4, 0, 0, 0], [0, .3 + .6 * gs(bx(x, y, 104, 468, 58, 22, 4), 16), 0, 0]);
      const e = Math.min(x, SW - x, y, SH - y); A[0] -= 1.6 * (1 - clamp(e / 26, 0, 1));
      const o = (j * w + i) * 4;
      a[o] = clamp((A[0] + 4) / 16, 0, 1); for (let c = 1; c < 4; c++) a[o + c] = clamp(A[c], 0, 1);
      for (let c = 0; c < 4; c++) b[o + c] = clamp(B[c], 0, 1);
    }
    return {w, h, a, b};
  }

  /* ---------------------------------------------------------------- motor */
  function mount(cv, opts) {
    opts = Object.assign({auto: true, span: "auto", gov: true, medir: false, calidad: null, anclaY: .5}, opts || {});
    const AMB = opts.ambiente || 27;
    const V = {gpu: AMB, cpu: AMB, ram: AMB, psu: AMB, vram: 0, util: 0, wn: 0, cold: 1, flash: 0, nuc: 1, dev: 0, hi: 50, lo: AMB - 3};
    const TGT = {gpu: AMB, cpu: AMB, ram: AMB, psu: AMB, vram: 0, util: 0, wn: 0, cold: 0};
    const fan = {a: [0, 1.1, 2.3, .4], v: [0, 0, 0, .3], on: false};
    let D = null, est = "reposo", fit = {s: 1, ox: 0, oy: 0}, cssW = 1, cssH = 1, dpr = 1, level = -1;
    let gl = null, v2 = false, prog = null, U = {}, tex = {}, Q = null, ctx2 = null, img = null, Qjs = null;
    let raf = 0, running = false, dead = false, last = 0, tSec = 0, acc = 0, t0 = performance.now(), nucAt = t0 + 150000 + Math.random() * 60000, nucEnd = 0;
    let lupa = null, lastRange = "", seed = 0, cost = 0, costMax = 0;
    const inst = {onRange: null};

    /* ---- WebGL ---- */
    function compile(type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.error("Termo:", gl.getShaderInfoLog(s)); return null; } return s; }
    function program(fs) {
      let hdr;
      if (v2) hdr = "#version 300 es\nprecision highp float;\nout vec4 oc;\n#define FC oc\n#define TX texture\n#define DV 1\n";
      else { const hi = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT).precision > 0, dv = !!gl.getExtension("OES_standard_derivatives");
        hdr = (dv ? "#extension GL_OES_standard_derivatives : enable\n#define DV 1\n" : "") + `precision ${hi ? "highp" : "mediump"} float;\n#define FC gl_FragColor\n#define TX texture2D\n`; }
      const vs = compile(gl.VERTEX_SHADER, v2 ? VS2 : VS1), f = compile(gl.FRAGMENT_SHADER, hdr + COMMON + fs);
      if (!vs || !f) return null;
      const p = gl.createProgram(); gl.attachShader(p, vs); gl.attachShader(p, f); gl.bindAttribLocation(p, 0, "a"); gl.linkProgram(p);
      return gl.getProgramParameter(p, gl.LINK_STATUS) ? p : null;
    }
    function mkTex(w, h, data, lin, rep) {
      const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
      const f = lin ? gl.LINEAR : gl.NEAREST, wr = rep ? gl.REPEAT : gl.CLAMP_TO_EDGE;
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, f); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, f);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wr); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wr);
      return t;
    }
    function initGL() {
      const o = {antialias: false, alpha: false, depth: false, stencil: false, premultipliedAlpha: false, powerPreference: "low-power", preserveDrawingBuffer: false};
      if (!gl) { gl = opts.gl1 ? null : cv.getContext("webgl2", o); v2 = !!gl; if (!gl) gl = cv.getContext("webgl", o); }
      if (!gl) return false;
      prog = program(MAIN); tex.bakeP = program(BAKE); tex.blurP = program(BLUR); tex.combP = program(COMB);
      if (!prog || !tex.bakeP || !tex.blurP || !tex.combP) return false;
      const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      gl.useProgram(prog);
      for (const k of ["R", "FT", "T0", "T1", "TN", "TL", "TI", "V0", "V1", "V2", "FX", "FA", "FB", "LU"]) U[k] = gl.getUniformLocation(prog, k);
      tex.n = mkTex(64, 64, noiseBytes(), true, true); tex.l = mkTex(256, 1, lutBytes(), true, false);
      gl.uniform1i(U.T0, 0); gl.uniform1i(U.T1, 1); gl.uniform1i(U.TN, 2); gl.uniform1i(U.TL, 3);
      tex.bw = 0; return true;
    }
    /* hornea las 2 bases a w×h (nítida → difusión a 100×125 → mezcla); con read=true devuelve sus píxeles */
    function bake(w, h, read) {
      const fb = gl.createFramebuffer(), out = [], px = read ? new Uint8Array(w * h * 4) : null, BW = 100, BH = 125;
      const uni = (pr, n) => gl.getUniformLocation(pr, n);
      const into = (t, ww, hh) => { gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0); gl.viewport(0, 0, ww, hh); };
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      const tA = mkTex(BW, BH, null, true, false), tB = mkTex(BW, BH, null, true, false);
      for (let pass = 0; pass < 2; pass++) {
        const sh = mkTex(w, h, null, true, false), fin = mkTex(w, h, null, true, false);
        gl.useProgram(tex.bakeP); gl.uniform2f(uni(tex.bakeP, "BR"), w, h); gl.uniform1f(uni(tex.bakeP, "PS"), pass);
        into(sh, w, h); gl.drawArrays(gl.TRIANGLES, 0, 3);
        gl.useProgram(tex.blurP); gl.uniform2f(uni(tex.blurP, "BR"), BW, BH); gl.uniform1i(uni(tex.blurP, "S"), 0); gl.activeTexture(gl.TEXTURE0);
        let src = sh;
        for (let it = 0; it < 4; it++) {                    /* H, V, H, V */
          const dst = it % 2 ? tB : tA; gl.bindTexture(gl.TEXTURE_2D, src); into(dst, BW, BH);
          gl.uniform2f(uni(tex.blurP, "DR"), it % 2 ? 0 : 1 / BW, it % 2 ? 1 / BH : 0); gl.drawArrays(gl.TRIANGLES, 0, 3); src = dst;
          if (it === 1) src = tB;
        }
        gl.useProgram(tex.combP); gl.uniform2f(uni(tex.combP, "BR"), w, h); gl.uniform1f(uni(tex.combP, "PS"), pass);
        gl.uniform1i(uni(tex.combP, "S"), 0); gl.uniform1i(uni(tex.combP, "Bl"), 1);
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, sh); gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, tB);
        into(fin, w, h); gl.drawArrays(gl.TRIANGLES, 0, 3);
        gl.deleteTexture(sh);
        if (read) { gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
          const f = new Float32Array(w * h * 4);
          for (let jj = 0; jj < h; jj++) for (let ii = 0; ii < w * 4; ii++) f[(h - 1 - jj) * w * 4 + ii] = px[jj * w * 4 + ii] / 255;
          out.push(f); gl.deleteTexture(fin); } else out.push(fin);
      }
      gl.deleteTexture(tA); gl.deleteTexture(tB);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.deleteFramebuffer(fb); gl.useProgram(prog);
      return out;
    }
    const useGL = initGL();
    if (!useGL) {
      if (gl) { const c2 = cv.cloneNode(false); cv.replaceWith(c2); cv = c2; }   /* WebGL sin shader válido: lienzo 2D nuevo */
      gl = null; ctx2 = cv.getContext("2d"); Qjs = bakeJS(100, 125); Q = Qjs; }

    /* ---- tamaño y encaje ---- */
    function lvl() { return opts.calidad != null ? opts.calidad : opts.gov ? P.Gov.level : 2; }
    function layout() {
      if (dead) return;
      const r = cv.getBoundingClientRect(); if (!r.width || !r.height) return;
      cssW = r.width; cssH = r.height; dpr = Math.min(2, window.devicePixelRatio || 1);
      const s = Math.min(cssW / SW, cssH / SH);
      fit = {s, ox: (cssW - SW * s) / 2, oy: (cssH - SH * s) * opts.anclaY};
      level = lvl();
      if (gl) {
        const k = dpr * LEVELS[level];
        cv.width = Math.max(1, Math.round(cssW * k)); cv.height = Math.max(1, Math.round(cssH * k));
        const bw = Math.round(SW * clamp(s * dpr, 1, 2));          /* bases a ~1 texel por píxel físico */
        if (bw !== tex.bw) {
          if (tex.b0) { gl.deleteTexture(tex.b0); gl.deleteTexture(tex.b1); }
          [tex.b0, tex.b1] = bake(bw, Math.round(bw * SH / SW)); tex.bw = bw;
          if (!Q) { const [a, b] = bake(200, 250, true); Q = {w: 200, h: 250, a, b}; }
        }
        gl.viewport(0, 0, cv.width, cv.height);
      } else { cv.width = Math.max(1, Math.round(cssW / 2.6)); cv.height = Math.max(1, Math.round(cssH / 2.6)); img = ctx2.createImageData(cv.width, cv.height); }
      draw();
    }

    /* ---- datos → objetivos (inercia térmica en el bucle) ---- */
    function set(d) {
      if (!d) return; D = d; const g = d.gpu || {};
      TGT.gpu = g.t != null ? g.t : AMB + 4; TGT.util = clamp((g.u || 0) / 100, 0, 1);
      TGT.vram = g.vt ? clamp(g.vu / g.vt, 0, 1) : 0; TGT.wn = clamp((g.w || 0) / 180, 0, 1.2);
      TGT.cpu = AMB + 4 + (d.cpu || 0) * .3;                                    /* estimación visual: no hay sensor de CPU */
      TGT.ram = AMB + 4 + (d.ramTot ? (1 - d.ramFree / d.ramTot) * 14 : 0);
      TGT.psu = AMB + 3 + (g.w || 0) * .09; TGT.cold = 0;
      if (est !== "reinicio") est = TGT.gpu >= 83 ? "muy caliente" : (TGT.gpu >= 70 || TGT.util >= .5 || (d.cpu || 0) >= 60) ? "trabajando" : "reposo";
      if (RM.matches) draw();
    }
    function lost() { TGT.cold = 1; for (const k of ["gpu", "cpu", "ram", "psu"]) TGT[k] = AMB; TGT.util = TGT.wn = TGT.vram = 0; est = "sin respuesta"; }
    function back(reboot) {
      if (reboot) { est = "reinicio"; for (const k of ["gpu", "cpu", "ram", "psu"]) V[k] = AMB + 1; V.cold = .55; setTimeout(() => { if (est === "reinicio") est = "reposo"; }, 9000); }
      if (!RM.matches) V.flash = 1;
      TGT.cold = 0;
    }
    if (opts.auto) {
      P.on("data", d => { if (!dead) { set(d); if (est === "sin respuesta") est = "reposo"; } });
      P.on("lost", () => { if (!dead) lost(); });
      P.on("back", x => { if (!dead) back(x && x.reboot); });
      if (P.d) set(P.d);
    }

    /* ---- simulación por fotograma ---- */
    function step(dt) {
      const k = Math.min(1, dt), ease = 1 - Math.pow(.25, k);
      for (const key of ["gpu", "cpu", "ram", "psu", "vram", "util", "wn"]) V[key] += (TGT[key] - V[key]) * ease;
      V.cold += (TGT.cold - V.cold) * (1 - Math.pow(TGT.cold > V.cold ? .72 : .3, k));   /* sin señal: ~8 s hasta casi negro */
      V.flash *= Math.pow(.015, k);
      const hiT = opts.span === "fijo" ? 95 : Math.max(50, Math.max(V.gpu, V.cpu, V.ram, V.psu) + 6);
      V.hi += (hiT - V.hi) * (1 - Math.pow(.3, k)); V.lo = opts.span === "fijo" ? 22 : AMB - 3;
      const now = performance.now(), rm = RM.matches;
      V.dev = rm ? 1 : clamp((now - t0 - 260) / 1300, 0, 1);
      if (!rm && now > nucAt) { nucEnd = now + 140; nucAt = now + 150000 + Math.random() * 60000; }
      V.nuc = rm ? 0 : now - t0 < 260 ? 1 : now < nucEnd ? .85 : 0;
      /* ventiladores: la gráfica para en reposo (modo 0 rpm, con histéresis) y arranca con calor o carga */
      if (!fan.on && (V.gpu > 52 || V.util > .35)) fan.on = true; else if (fan.on && V.gpu < 46 && V.util < .15) fan.on = false;
      const live = 1 - V.cold, gT = fan.on ? (.5 + 2.6 * clamp((V.gpu - 45) / 40, 0, 1) + .8 * V.util) * live : 0;
      const rT = (.32 + .9 * clamp((V.gpu - 35) / 50, 0, 1) + .5 * clamp((V.cpu - AMB - 6) / 50, 0, 1)) * live;
      for (let i = 0; i < 4; i++) { const tg = i < 3 ? gT * (1 - .06 * i) : rT, up = tg > fan.v[i];
        fan.v[i] += (tg - fan.v[i]) * (1 - Math.pow(up ? .3 : .55, k));
        if (!rm) fan.a[i] = (fan.a[i] + fan.v[i] * 6.2832 * dt) % 6.2832; }
      if (!rm) { tSec += dt; seed = (seed + 17.31) % 997; }
      const r = range(), key = r.lo + "/" + r.hi;
      if (key !== lastRange) { lastRange = key; inst.onRange && inst.onRange(r); }
    }
    function S() {                                   /* entradas del modelo, compartidas por shader y JS */
      const rm = RM.matches, br = rm ? .01 : .07, rate = .9 + 1.6 * V.wn;
      return {amb: AMB, dG: V.gpu - AMB, dC: V.cpu - AMB, dR: V.ram - AMB, dP: V.psu - AMB, vr: V.vram,
        hf: .7 + .16 * clamp((V.gpu - 50) / 35, 0, 1), bre: (1.35 - .55 * clamp(V.wn, 0, 1)) * (1 + br * Math.sin((rm ? performance.now() / 1000 : tSec) * rate)), cold: V.cold, dev: V.dev};
    }
    function draw() {
      if (dead || (!gl && !ctx2)) return;
      const c0 = performance.now(), s = S();
      if (gl) {
        const kx = 1 / (fit.s * cv.width / cssW), sc = cv.width / cssW;
        gl.uniform2f(U.R, cv.width, cv.height); gl.uniform4f(U.FT, kx, fit.ox * sc, fit.oy * sc, s.hf);
        gl.uniform1f(U.TI, tSec);
        gl.uniform4f(U.V0, AMB, s.dG, s.dC, s.dR); gl.uniform4f(U.V1, s.dP, s.vr, V.util, s.bre);
        gl.uniform4f(U.V2, V.lo, V.hi, seed, RM.matches ? 0 : .004 * Math.sin(tSec * 7.3) * Math.sin(tSec * 2.9));
        gl.uniform4f(U.FX, V.cold, V.flash, V.nuc, V.dev);
        gl.uniform4f(U.FA, ...fan.a);
        const ex = RM.matches ? 0 : 1 / 30;                  /* exposición del sensor: desenfoque de movimiento */
        gl.uniform4f(U.FB, ...fan.v.map(v => Math.min(6.3, v * 6.2832 * ex)));
        gl.uniform3f(U.LU, lupa ? lupa[0] : 0, lupa ? lupa[1] : 0, lupa ? lupa[2] : 0);
        const tx = [tex.b0, tex.b1, tex.n, tex.l];
        for (let i = 0; i < 4; i++) { gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_2D, tx[i]); }
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      } else draw2D(s);
      const c = performance.now() - c0; cost = cost ? cost * .9 + c * .1 : c; costMax = Math.max(costMax, c);
      if (opts.medir) { window.__cost = cost; window.__costMax = costMax; }
    }
    /* respaldo Canvas 2D: mismo modelo y misma rampa, a resolución de sensor */
    const LUT2 = lutBytes(), sm = new Float32Array(8);
    function draw2D(s) {
      const w = cv.width, h = cv.height, d = img.data, k = cssW / w, span = V.hi - V.lo;
      for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
        const x = ((i + .5) * k - fit.ox) / fit.s, y = ((j + .5) * k - fit.oy) / fit.s;
        let T;
        if (x < 0 || y < 0 || x > SW || y > SH) T = AMB - 1.8; else T = model(samp(Q, x, y, sm), s);
        for (let f = 0; f < 4; f++) { const F = FANS[f], dx = x - F[0], dy = y - F[1], r = Math.hypot(dx, dy);
          if (r < F[2] && r > F[2] * .3) { const u = F[3] * (Math.atan2(dy, dx) - fan.a[f]) / 6.2832 + .55 * r / F[2];
            if (u - Math.floor(u) < .6 - .22 * r / F[2]) T = T + (AMB + .6 - T) * .58; } }
        let v = clamp((T - V.lo) / span, 0, 1); v = v + (.33 - v) * V.nuc;
        const o = (j * w + i) * 4, l = Math.round(clamp(v, 0, 1) * 255) * 4, vg = 1 - .45 * V.cold;
        for (let c = 0; c < 3; c++) d[o + c] = (LUT2[l + c] * vg) + (255 - LUT2[l + c] * vg) * V.flash;
        d[o + 3] = 255;
      }
      ctx2.putImageData(img, 0, 0);
    }

    /* ---- bucle ---- */
    function frame(now) {
      if (!running || dead) return;
      raf = requestAnimationFrame(frame);
      const dt = Math.min(.25, (now - last) / 1000); last = now;
      if (opts.gov && gl && dt < .25) P.Gov.frame(dt * 1000);
      if (gl && lvl() !== level) layout();
      acc += dt;
      /* nivel 0 o respaldo 2D: 30 Hz; movimiento reducido: 8 Hz (solo respiración mínima) */
      const minDt = RM.matches ? .125 : (!gl ? .1 : level === 0 ? .032 : 0);
      if (acc < minDt) return;
      step(acc); acc = 0; draw();
    }
    function start() { if (running || dead) return; running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
    function stop() { running = false; cancelAnimationFrame(raf); }
    const onVis = () => document.hidden ? stop() : start();
    document.addEventListener("visibilitychange", onVis);
    const onLost = e => { e.preventDefault(); stop(); }, onRest = () => { tex = {}; Q = null; if (initGL()) { layout(); start(); } };
    cv.addEventListener("webglcontextlost", onLost); cv.addEventListener("webglcontextrestored", onRest);
    const ro = new ResizeObserver(() => layout()); ro.observe(cv);

    /* ---- API pública ---- */
    function toScene(x, y) { return [(x - fit.ox) / fit.s, (y - fit.oy) / fit.s]; }
    function range() { return {lo: Math.round(V.lo), hi: Math.round(V.hi)}; }
    function heatAt(x, y) {
      const [sx, sy] = toScene(x, y);
      let parte = null, bd = 1e9;
      for (const p of PARTS) { const dx = Math.max(p.x - sx, 0, sx - p.x - p.w), dy = Math.max(p.y - sy, 0, sy - p.y - p.h), dd = dx * dx + dy * dy;
        if (dd < bd && dd < 400) { bd = dd; parte = p.id; } }
      if (!Q) return {t: null, parte, medido: false};
      const t = sx < 0 || sy < 0 || sx > SW || sy > SH ? AMB - 1.8 : model(samp(Q, sx, sy, new Float32Array(8)), S());
      const medido = Math.hypot(sx - 188, sy - 358) < 18 && D && D.gpu && D.gpu.t != null;
      return {t: medido ? D.gpu.t : Math.round(t * 10) / 10, parte, medido: !!medido};   /* sobre el chip manda el sensor */
    }
    Object.assign(inst, {
      set, lost, back, heatAt, range, layout,
      estado: () => est,
      mapa: t => clamp((t - V.lo) / (V.hi - V.lo), 0, 1),               /* posición 0..1 de t en la escala visible */
      parts: () => PARTS.map(p => ({id: p.id, name: p.name, x: fit.ox + p.x * fit.s, y: fit.oy + p.y * fit.s, w: p.w * fit.s, h: p.h * fit.s,
        cx: fit.ox + p.c[0] * fit.s, cy: fit.oy + p.c[1] * fit.s})),
      lupa(x, y) { if (x == null) lupa = null; else { const [sx, sy] = toScene(x, y); lupa = [sx, sy, 34]; } if (RM.matches) draw(); },
      calidad(n) { opts.calidad = n == null ? null : clamp(n | 0, 0, 3); layout(); },
      canvas: () => cv,
      info: () => ({motor: gl ? (v2 ? "webgl2" : "webgl1") : "canvas2d", nivel: level, escala: gl ? LEVELS[level] * dpr : 1 / 2.6,
        px: [cv.width, cv.height], bases: tex.bw ? [tex.bw, Math.round(tex.bw * SH / SW)] : [100, 125], cpuMs: +cost.toFixed(3), cpuMaxMs: +costMax.toFixed(2),
        ventiladores: fan.v.map(v => +v.toFixed(2)), rango: range(), estado: est}),
      /* banco sintético: n fotogramas forzando su fin con readPixels (en SwiftShader ≈ coste de raster) */
      bench(n) { if (!gl) return null; const b = new Uint8Array(4); draw(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, b);
        const a = performance.now(); for (let i = 0; i < (n || 30); i++) { draw(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, b); }
        return +((performance.now() - a) / (n || 30)).toFixed(2); },
      destroy() { dead = true; stop(); ro.disconnect(); document.removeEventListener("visibilitychange", onVis);
        cv.removeEventListener("webglcontextlost", onLost); cv.removeEventListener("webglcontextrestored", onRest);
        if (gl) { const e = gl.getExtension("WEBGL_lose_context"); e && e.loseContext(); } }
    });
    layout(); if (!document.hidden) start();
    return inst;
  }

  P.Termo = {
    mount, PARTS: PARTS.map(p => Object.assign({}, p)), RAMPA,
    css: (dir) => `linear-gradient(${dir || "to top"},${RAMPA.map(([t, c]) => c + " " + (t * 100) + "%").join(",")})`
  };
})();
