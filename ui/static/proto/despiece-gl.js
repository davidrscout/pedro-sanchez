/* Despiece: motor WebGL2 mínimo escrito a mano (sin librerías) para el prototipo B.
   Cajas con luz de dos colores (ciruela arriba-derecha, petróleo abajo-izquierda, como el fondo de David),
   aristas mecanizadas antialias, aletas, ventiladores procedurales con desenfoque de movimiento,
   brasa de calor y cable de alimentación con pulsos. Expone window.Despiece = {create(canvas) -> scene|null}. */
(function () {
  "use strict";
  /* ---------------- matrices (column-major, como GL) ---------------- */
  const M = {
    id() { return [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]; },
    mul(a, b) { const o = new Array(16); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; } return o; },
    persp(fov, asp, n, f) { const t = 1 / Math.tan(fov / 2); return [t / asp,0,0,0, 0,t,0,0, 0,0,(f + n) / (n - f),-1, 0,0,2 * f * n / (n - f),0]; },
    look(e, c, u) { const z = norm(sub(e, c)), x = norm(cross(u, z)), y = cross(z, x);
      return [x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0, -dot(x,e),-dot(y,e),-dot(z,e),1]; },
    T(x, y, z) { return [1,0,0,0, 0,1,0,0, 0,0,1,0, x,y,z,1]; },
    S(x, y, z) { return [x,0,0,0, 0,y,0,0, 0,0,z,0, 0,0,0,1]; },
    RX(a) { const c = Math.cos(a), s = Math.sin(a); return [1,0,0,0, 0,c,s,0, 0,-s,c,0, 0,0,0,1]; },
    RY(a) { const c = Math.cos(a), s = Math.sin(a); return [c,0,-s,0, 0,1,0,0, s,0,c,0, 0,0,0,1]; },
    RZ(a) { const c = Math.cos(a), s = Math.sin(a); return [c,s,0,0, -s,c,0,0, 0,0,1,0, 0,0,0,1]; },
    xf(m, p) { const x = p[0], y = p[1], z = p[2];
      return [m[0]*x + m[4]*y + m[8]*z + m[12], m[1]*x + m[5]*y + m[9]*z + m[13], m[2]*x + m[6]*y + m[10]*z + m[14], m[3]*x + m[7]*y + m[11]*z + m[15]]; }
  };
  const sub = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]], dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
  const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0]/l, a[1]/l, a[2]/l]; };
  const lerp = (a, b, t) => a + (b - a) * t;

  /* ---------------- shaders ---------------- */
  const LIGHT = `
  const vec3 KEY=vec3(.66,.43,.80); const vec3 FILL=vec3(.20,.50,.58);
  vec3 light(vec3 N,vec3 V,vec3 base,float dim){
    vec3 L1=normalize(vec3(.55,.75,.45)),L2=normalize(vec3(-.75,-.35,.45));
    float d1=max(dot(N,L1),0.),d2=max(dot(N,L2),0.)*.8+.12*max(-N.y,0.);
    vec3 H=normalize(L1+V);float sp=pow(max(dot(N,H),0.),38.)*.55;
    float fr=pow(1.-max(dot(N,V),0.),3.);
    vec3 c=base*(.05+KEY*d1*1.25+FILL*d2*1.1)+KEY*sp+mix(FILL,KEY,.5+.5*N.y)*fr*.45;
    return c*dim;}
  vec3 ember(float h){return mix(mix(vec3(.45,.06,.03),vec3(1.,.42,.12),smoothstep(0.,.6,h)),vec3(1.,.86,.55),smoothstep(.6,1.,h));}`;
  const BOX_VS = `#version 300 es
  layout(location=0) in vec3 aP; layout(location=1) in vec3 aN;
  uniform mat4 uVP,uM; uniform vec3 uSize;
  out vec3 vL,vN,vW;
  void main(){ vL=aP; vec4 w=uM*vec4(aP,1.); vW=w.xyz; vN=normalize(mat3(uM)*aN); gl_Position=uVP*w; }`;
  const BOX_FS = `#version 300 es
  precision highp float;
  in vec3 vL,vN,vW; out vec4 o;
  uniform vec3 uSize,uCol,uEye,uHot; uniform float uEdge,uKind,uHeat,uDim,uAlpha,uT,uEmit; uniform vec3 uEmitCol;
  ${LIGHT}
  void main(){
    vec3 N=normalize(vN),V=normalize(uEye-vW);
    vec3 an=abs(normalize(vL*0.+ (abs(vL.x)>abs(vL.y)&&abs(vL.x)>abs(vL.z)? vec3(1,0,0): abs(vL.y)>abs(vL.z)? vec3(0,1,0):vec3(0,0,1))));
    vec3 q=vL*uSize, h=uSize*.5;
    vec3 dd=h-abs(q); float e=1e3;
    if(an.x<.5) e=min(e,dd.x); if(an.y<.5) e=min(e,dd.y); if(an.z<.5) e=min(e,dd.z);
    float edge=1.-smoothstep(0.,fwidth(e)*1.6,e);
    vec3 base=uCol;
    if(uKind>.5&&uKind<1.5&&an.y<.5){ float f=abs(fract(q.y*14.)-.5); base*=.55+.75*smoothstep(.12,.32,f); }   /* aletas */
    if(uKind>1.5&&uKind<2.5&&an.z>.5){ float tr=step(.92,fract(q.x*7.+floor(q.y*5.)*.37))*step(.5,fract(sin(floor(q.y*18.)*12.9898)*43758.5));
      tr+=step(.95,fract(q.y*9.))*step(.6,fract(sin(floor(q.x*11.)*78.233)*43758.5)); base+=vec3(.06,.04,.025)*tr; }      /* pistas de cobre */
    vec3 c=light(N,V,base,uDim);
    c+=edge*uEdge*mix(vec3(.55,.5,.62),KEY,.35)*(.35+.65*uDim);
    float hd=length(q-uHot*uSize); float glow=uHeat*exp(-hd*hd*2.2);
    c+=ember(uHeat)*glow*1.3*uDim + ember(uHeat)*uHeat*.08*uDim;
    c+=uEmitCol*uEmit;
    if(uKind>2.5){ if(edge<.02) discard; o=vec4(c,uAlpha*edge); return; }      /* solo aristas (caja fantasma) */
    o=vec4(c,uAlpha);
  }`;
  const FAN_VS = `#version 300 es
  layout(location=0) in vec2 aP; uniform mat4 uVP,uM; out vec2 vU; out vec3 vW;
  void main(){ vU=aP; vec4 w=uM*vec4(aP,0.,1.); vW=w.xyz; gl_Position=uVP*w; }`;
  const FAN_FS = `#version 300 es
  precision highp float; in vec2 vU; in vec3 vW; out vec4 o;
  uniform float uRot,uBlur,uDim,uHeat; uniform vec3 uEye,uNrm;
  ${LIGHT}
  float blade(float a,float r){ float k=fract((a+r*1.1)*9./6.2831853); return smoothstep(.5-uBlur-.12,.5-uBlur,k)*(1.-smoothstep(.85,.85+uBlur+.03,k)); }
  void main(){
    float r=length(vU); if(r>1.) discard;
    float a=atan(vU.y,vU.x)-uRot;
    vec3 N=normalize(uNrm),V=normalize(uEye-vW);
    float b=r>.27&&r<.9?blade(a,r):0.;
    float ring=smoothstep(.9,.93,r);
    float hub=1.-smoothstep(.25,.27,r);
    vec3 base=vec3(.05,.055,.07)+vec3(.09,.09,.11)*b*(1.-uBlur*1.2)+vec3(.04)*uBlur*step(.27,r)*step(r,.9);
    vec3 c=light(N,V,base,uDim);
    c+=ring*vec3(.22,.2,.26)*uDim; c+=hub*vec3(.08,.07,.1)*uDim;
    c+=ember(uHeat)*uHeat*.18*(1.-r)*uDim;
    o=vec4(c,1.);
  }`;
  const CAB_VS = `#version 300 es
  layout(location=0) in vec3 aP; layout(location=1) in float aS; uniform mat4 uVP; out float vS;
  void main(){ vS=aS; gl_Position=uVP*vec4(aP,1.); }`;
  const CAB_FS = `#version 300 es
  precision highp float; in float vS; out vec4 o; uniform float uT,uW,uDim;
  ${LIGHT}
  void main(){ float p=smoothstep(.8,1.,fract(vS*7.-uT*(.35+uW*2.4)));
    vec3 c=vec3(.07,.07,.09)*uDim + ember(.55+uW*.45)*p*(.25+uW)*uDim;
    o=vec4(c,1.); }`;

  function cube() {
    const P = [], N = [];
    const f = (n, u, v) => { const c = [n[0]*.5, n[1]*.5, n[2]*.5];
      const q = (a, b) => [c[0]+u[0]*a+v[0]*b, c[1]+u[1]*a+v[1]*b, c[2]+u[2]*a+v[2]*b];
      for (const p of [q(-.5,-.5), q(.5,-.5), q(.5,.5), q(-.5,-.5), q(.5,.5), q(-.5,.5)]) { P.push(...p); N.push(...n); } };
    f([1,0,0],[0,0,-1],[0,1,0]); f([-1,0,0],[0,0,1],[0,1,0]); f([0,1,0],[1,0,0],[0,0,-1]);
    f([0,-1,0],[1,0,0],[0,0,1]); f([0,0,1],[1,0,0],[0,1,0]); f([0,0,-1],[-1,0,0],[0,1,0]);
    return { P: new Float32Array(P), N: new Float32Array(N) };
  }

  function create(canvas) {
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: "low-power" });
    if (!gl) return null;
    const prog = (vs, fs) => { const mk = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o);
        if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o)); return o; };
      const p = gl.createProgram(); gl.attachShader(p, mk(gl.VERTEX_SHADER, vs)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
      const u = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
      for (let i = 0; i < n; i++) { const a = gl.getActiveUniform(p, i); u[a.name] = gl.getUniformLocation(p, a.name); }
      return { p, u }; };
    let PB, PF, PC;
    try { PB = prog(BOX_VS, BOX_FS); PF = prog(FAN_VS, FAN_FS); PC = prog(CAB_VS, CAB_FS); }
    catch (e) { console.error(e); return null; }
    const c = cube();
    const vaoBox = gl.createVertexArray(); gl.bindVertexArray(vaoBox);
    const bp = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, bp); gl.bufferData(gl.ARRAY_BUFFER, c.P, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    const bn = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, bn); gl.bufferData(gl.ARRAY_BUFFER, c.N, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
    const vaoFan = gl.createVertexArray(); gl.bindVertexArray(vaoFan);
    const fb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, fb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, 1,1, -1,-1, 1,1, -1,1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const SEG = 48;
    const vaoCab = gl.createVertexArray(); gl.bindVertexArray(vaoCab);
    const cb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, cb); gl.bufferData(gl.ARRAY_BUFFER, (SEG + 1) * 2 * 4 * 4, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 16, 12);
    gl.bindVertexArray(null);
    const cabData = new Float32Array((SEG + 1) * 2 * 4);

    /* ---------------- la máquina ----------------
       A = montado, B = despiezado. rot en grados. hot = foco de calor en coordenadas locales (-.5..5). */
    const D2R = Math.PI / 180;
    const parts = [
      { id: "board", size: [3.0, 3.6, .06], A: [0, 0, 0], B: [0, .05, -.5], col: [.045, .05, .06], kind: 2, edge: .5, d: 0 },
      { id: "cpu", size: [.95, 1.05, .85], A: [-.35, .8, .5], B: [-.65, 1.35, 2.1], col: [.16, .16, .19], kind: 1, edge: .9, d: .05, hot: [0, 0, -.5] },
      { id: "ram0", size: [.07, 1.25, .3], A: [.55, .75, .2], B: [.85, .95, 1.25], col: [.09, .09, .11], edge: .8, d: .15 },
      { id: "ram1", size: [.07, 1.25, .3], A: [.69, .75, .2], B: [1.1, .95, 1.45], col: [.09, .09, .11], edge: .8, d: .19 },
      { id: "ram2", size: [.07, 1.25, .3], A: [.83, .75, .2], B: [1.35, .95, 1.65], col: [.09, .09, .11], edge: .8, d: .23 },
      { id: "ram3", size: [.07, 1.25, .3], A: [.97, .75, .2], B: [1.6, .95, 1.85], col: [.09, .09, .11], edge: .8, d: .27 },
      { id: "nvme", size: [.75, .22, .04], A: [-.25, -.05, .06], B: [-1.25, -.1, 1.5], col: [.08, .08, .1], edge: .9, d: .2 },
      { id: "gpu", size: [2.6, .45, 1.15], A: [.15, -.62, .65], B: [.3, -1.05, 2.9], rA: [0, 0, 0], rB: [-90, 0, 0], col: [.07, .07, .085], edge: 1, d: .1, hot: [0, -.5, 0] },
      { id: "psu", size: [1.5, .85, 1.3], A: [-.55, -2.35, .65], B: [-.85, -2.95, 2.2], rA: [0, 0, 0], rB: [0, 18, 0], col: [.06, .06, .075], edge: .9, d: .32, hot: [0, 0, .5] },
      { id: "case", size: [3.5, 5.3, 2.5], A: [0, -.55, .95], B: [0, -.6, -.4], col: [.2, .2, .25], kind: 3, edge: 1, d: 0, alphaA: .14, alphaB: .02 },
      { id: "led", size: [.08, .08, .08], A: [1.62, 2.0, 2.1], B: [1.62, 2.0, 2.1], col: [.02, .02, .02], edge: 0, d: 0 },
    ];
    const byId = Object.fromEntries(parts.map(p => [p.id, p]));
    const S = { explode: 0, t: 0, fanRot: 0, fanSpd: 0, dim: 0, heatGpu: 0, heatCpu: 0, heatPsu: 0, watts: 0, led: 0, ledCol: [.3, .9, .6],
      yaw: -30, pitch: 11, dist: 13.2, target: [.2, -.85, 1.25], fov: 30 };
    const ease = x => { x = Math.min(1, Math.max(0, x)); return 1 - Math.pow(1 - x, 3); };
    const easeBack = x => { x = Math.min(1, Math.max(0, x)); const c = 1.35; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };

    function model(p) {
      const k = p.id === "case" ? ease(S.explode) : easeBack((S.explode - p.d) / .62);
      const pos = [0, 1, 2].map(i => lerp(p.A[i], p.B[i], k));
      let m = M.T(...pos);
      if (p.rA) { const r = [0, 1, 2].map(i => lerp(p.rA[i], p.rB[i], ease((S.explode - p.d) / .7)) * D2R);
        m = M.mul(m, M.mul(M.RY(r[1]), M.mul(M.RX(r[0]), M.RZ(r[2])))); }
      return m;
    }
    let VP = M.id(), eye = [0, 0, 10], W = 1, H = 1;
    function camera() {
      const y = S.yaw * D2R, x = S.pitch * D2R;
      eye = [S.target[0] + S.dist * Math.cos(x) * Math.sin(y), S.target[1] + S.dist * Math.sin(x), S.target[2] + S.dist * Math.cos(x) * Math.cos(y)];
      VP = M.mul(M.persp(S.fov * D2R, W / H, .5, 40), M.look(eye, S.target, [0, 1, 0]));
    }
    function project(p) { const v = M.xf(VP, p); return [(v[0] / v[3] * .5 + .5) * canvas.clientWidth, (1 - (v[1] / v[3] * .5 + .5)) * canvas.clientHeight, v[3]]; }
    function anchor(id) {
      const A = { gpu: ["gpu", [0, -.5, -.05]], cpu: ["cpu", [.2, .5, .5]], ram: ["ram3", [0, .5, .3]], nvme: ["nvme", [-.5, 0, .5]], psu: ["psu", [-.3, .2, .5]] }[id];
      return project(M.xf(model(byId[A[0]]), A[1]));
    }
    function resize(w, h, scale) {
      W = Math.max(1, Math.round(w * scale)); H = Math.max(1, Math.round(h * scale));
      canvas.width = W; canvas.height = H; gl.viewport(0, 0, W, H);
    }
    function cable(mg, mp) {
      const a = M.xf(mp, [.38, .5, .25]), b = M.xf(mg, [1.15, 0, .5]);
      const c1 = [a[0] + .1, a[1] + 1.4, a[2] + .6], c2 = [b[0] + .9, b[1] - .2, b[2] + .4];
      const pts = [];
      for (let i = 0; i <= SEG; i++) { const t = i / SEG, u = 1 - t;
        pts.push([0, 1, 2].map(k => u*u*u*a[k] + 3*u*u*t*c1[k] + 3*u*t*t*c2[k] + t*t*t*b[k])); }
      for (let i = 0; i <= SEG; i++) {
        const p = pts[i], q = pts[Math.min(SEG, i + 1)], r = pts[Math.max(0, i - 1)];
        const tg = norm(sub(q, r)), vd = norm(sub(eye, p)), sd = norm(cross(tg, vd)), w = .035;
        cabData.set([p[0] + sd[0]*w, p[1] + sd[1]*w, p[2] + sd[2]*w, i / SEG, p[0] - sd[0]*w, p[1] - sd[1]*w, p[2] - sd[2]*w, i / SEG], i * 8);
      }
    }
    function drawBox(p, mm, alpha) {
      const u = PB.u;
      gl.uniformMatrix4fv(u.uM, false, M.mul(mm, M.S(...p.size)));
      gl.uniform3fv(u.uSize, p.size); gl.uniform3fv(u.uCol, p.col); gl.uniform1f(u.uEdge, p.edge); gl.uniform1f(u.uKind, p.kind || 0);
      const heat = p.id === "gpu" ? S.heatGpu : p.id === "cpu" ? S.heatCpu : p.id === "psu" ? S.heatPsu : 0;
      gl.uniform1f(u.uHeat, heat); gl.uniform3fv(u.uHot, p.hot || [0, 0, 0]);
      gl.uniform1f(u.uAlpha, alpha);
      if (p.id === "led") { gl.uniform3fv(u.uEmitCol, S.ledCol); gl.uniform1f(u.uEmit, S.led); }
      else { gl.uniform1f(u.uEmit, 0); }
      gl.drawArrays(gl.TRIANGLES, 0, 36);
    }
    function render() {
      camera();
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE); gl.disable(gl.BLEND);
      gl.useProgram(PB.p); gl.bindVertexArray(vaoBox);
      gl.uniformMatrix4fv(PB.u.uVP, false, VP); gl.uniform3fv(PB.u.uEye, eye); gl.uniform1f(PB.u.uDim, S.dim); gl.uniform1f(PB.u.uT, S.t);
      const mods = {};
      for (const p of parts) { mods[p.id] = model(p); if (p.kind !== 3) drawBox(p, mods[p.id], 1); }
      /* ventiladores de la gráfica */
      gl.useProgram(PF.p); gl.bindVertexArray(vaoFan);
      gl.uniformMatrix4fv(PF.u.uVP, false, VP); gl.uniform3fv(PF.u.uEye, eye); gl.uniform1f(PF.u.uDim, S.dim);
      gl.uniform1f(PF.u.uBlur, Math.min(.42, S.fanSpd * .028)); gl.uniform1f(PF.u.uHeat, S.heatGpu);
      gl.disable(gl.CULL_FACE);
      for (const [fx, dir] of [[-.62, 1], [.62, -1]]) {
        const mm = M.mul(mods.gpu, M.mul(M.T(fx, -.232, 0), M.mul(M.RX(Math.PI / 2), M.S(.47, .47, 1))));
        gl.uniformMatrix4fv(PF.u.uM, false, mm);
        const n = M.xf(mods.gpu, [0, -1, 0]), o = M.xf(mods.gpu, [0, 0, 0]);
        gl.uniform3fv(PF.u.uNrm, sub(n, o)); gl.uniform1f(PF.u.uRot, S.fanRot * dir);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      }
      /* cable de alimentación */
      cable(mods.gpu, mods.psu);
      gl.useProgram(PC.p); gl.bindVertexArray(vaoCab);
      gl.bindBuffer(gl.ARRAY_BUFFER, cb); gl.bufferSubData(gl.ARRAY_BUFFER, 0, cabData);
      gl.uniformMatrix4fv(PC.u.uVP, false, VP); gl.uniform1f(PC.u.uT, S.t); gl.uniform1f(PC.u.uW, S.watts); gl.uniform1f(PC.u.uDim, S.dim);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, (SEG + 1) * 2);
      /* caja fantasma (solo aristas, transparente) */
      gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
      gl.useProgram(PB.p); gl.bindVertexArray(vaoBox);
      const cs = byId.case; drawBox(cs, mods.case, lerp(cs.alphaA, cs.alphaB, ease(S.explode)) * (.4 + .6 * S.dim));
      gl.depthMask(true);
      gl.bindVertexArray(null);
    }
    return { S, render, resize, anchor, gl, lost: () => gl.isContextLost() };
  }
  window.Despiece = { create };
})();
