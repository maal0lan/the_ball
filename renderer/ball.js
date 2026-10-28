'use strict';
/* Crystal ball window: WebGL glass refraction of the real desktop, dialogue box, voice playback, backend socket. */

// ============================================================ state & helpers
let S = {};
const $ = id => document.getElementById(id);
const el = { video: $('screenVideo'), glass: $('glass'), hit: $('ballHit'), badge: $('badge'), panel: $('panel'),
  backdrop: $('panelBackdrop'), msgs: $('messages'), notice: $('notice'), confirm: $('confirm'),
  confirmText: $('confirmText'), input: $('input'), form: $('composer'), mic: $('micBtn'), stop: $('stopBtn') };

const hex = h => { const n = parseInt(h.replace('#', ''), 16); return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255]; };
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).slice(0, 12);
window.addEventListener('error', e => console.error(`Uncaught: ${e.message} @ ${e.filename}:${e.lineno}`));
window.addEventListener('unhandledrejection', e => console.error(`Unhandled promise rejection: ${e.reason && (e.reason.stack || e.reason)}`));

const turn = { active: false, msgEl: null, text: '', buffered: '' };
let chatOpen = false, dragging = false, sessionId = null, errorCount = 0, hideTimer = null, pendingConfirm = null;
let speechInput = null, speechListening = false, speechStopping = false;
const sentHistory = []; let sentIdx = -1;

// ============================================================ layout from settings
function applyLayout() {
  const r = document.documentElement.style;
  r.setProperty('--ball', S['appearance.ballSize'] + 'px');
  r.setProperty('--chat-w', S['chat.width'] + 'px');
  r.setProperty('--chat-h', S['chat.height'] + 'px');
  r.setProperty('--font', S['chat.fontFamily']);
  r.setProperty('--fs', S['chat.fontSize'] + 'px');
  r.setProperty('--reply', S['chat.textColor']);
  r.setProperty('--user', S['chat.userColor']);
  r.setProperty('--accent', S['appearance.accentColor']);
  r.setProperty('--dark', S['chat.opacity']);
  r.setProperty('--radius', S['chat.radius'] + 'px');
  el.input.placeholder = S['chat.placeholder'];
  el.mic.hidden = !S['voice.inputEnabled'];
  if (!S['voice.inputEnabled'] && speechListening) stopSpeechInput();
  if (speechInput) speechInput.language = S['voice.inputLanguage'] || 'en-US';
  renderPickers();
  resizeGL();
}

// ============================================================ screen capture (the "see-through" part)
let capture = { has: false, disp: { x: 0, y: 0, width: 1920, height: 1080 }, stream: null };

async function startCapture() {
  stopCapture();
  if (!S['behavior.captureScreen']) { console.info('Desktop refraction is off (Settings → Behavior).'); return; }
  try {
    const info = await crystal.capture.info();
    if (!info.sourceId) throw new Error('no screen source');
    capture.disp = info.display.bounds;
    const maxW = info.maxWidth, maxH = Math.round(maxW * capture.disp.height / capture.disp.width);
    capture.stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { mandatory: {
      chromeMediaSource: 'desktop', chromeMediaSourceId: info.sourceId, maxWidth: maxW, maxHeight: maxH, maxFrameRate: info.fps } } });
    el.video.srcObject = capture.stream;
    await el.video.play();
    capture.has = true;
    console.info(`Screen capture started: display ${info.display.id}, ${el.video.videoWidth}x${el.video.videoHeight}`);
  } catch (e) {
    capture.has = false;
    // Ignore AbortError from stopCapture race; treat as transient and retry on next user action
    if (e.name !== 'AbortError') console.error(`Screen capture failed: ${e.message}. The ball falls back to plain glass. (macOS: grant Screen Recording permission.)`);
  }
}
function stopCapture() {
  capture.has = false;
  if (capture.stream) capture.stream.getTracks().forEach(t => t.stop());
  capture.stream = null; el.video.srcObject = null;
}

// ============================================================ WebGL glass shader
const VERT = `#version 300 es
in vec2 a; out vec2 v_uv;
void main(){ v_uv = vec2(a.x*.5+.5, 1.-(a.y*.5+.5)); gl_Position = vec4(a,0.,1.); }`;

const FRAG = `#version 300 es
precision highp float;
in vec2 v_uv; out vec4 o;
uniform sampler2D u_tex;
uniform float u_hasTex,u_time,u_level,u_listen,u_think,u_speak,u_scale,u_R;
uniform vec2 u_center,u_dispO,u_dispS;
uniform float u_refract,u_zoom,u_ior,u_aber,u_blur,u_frost,u_tintAmt,u_dark,u_sat,u_rim,u_spec,u_caustic,u_grain,u_wobble,u_glow,u_shadow,u_opacity,u_edge;
uniform vec3 u_tint,u_accent;

float hash(vec2 p){ return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453); }

vec3 scr(vec2 off, float blurPx, vec2 seed){
  vec3 acc = vec3(0.);
  const int N = 8;
  float j = hash(seed)*6.2831;
  for(int i=0;i<N;i++){
    float a = float(i)*2.39996 + j;
    float rr = sqrt((float(i)+.5)/float(N))*blurPx;
    vec2 uv = (u_center + off + vec2(cos(a),sin(a))*rr - u_dispO)/u_dispS;
    acc += texture(u_tex, clamp(uv, .001, .999)).rgb;
  }
  return acc/float(N);
}

void main(){
  vec2 p = (v_uv-.5)*2.*u_scale;          // ball radius = 1, y points down
  float r = length(p);
  float t = u_time;
  float act = clamp(u_listen*.6 + u_think + u_speak*(.5+u_level), 0., 1.5);

  if(r > 1.0){                             // aura + soft shadow outside the glass
    float d = r-1.;
    float aura = exp(-d*7.)*(.06+.38*act)*u_glow;
    float sh = u_shadow*.28*exp(-d*6.)*smoothstep(-.6,.5,p.y);
    float fade = 1.-smoothstep(1., u_scale, r);
    o = vec4(u_accent*aura*fade, clamp(aura+sh,0.,1.)*fade); return;
  }

  // liquid motion while thinking / speaking
  vec2 q = p;
  float ang = u_think*.25*(1.-r)*sin(t*1.3);
  q = mat2(cos(ang),-sin(ang),sin(ang),cos(ang))*q;
  float w = u_wobble*(.006 + .02*u_think + .05*u_speak*u_level);
  q += w*vec2(sin(p.y*7.+t*2.3), cos(p.x*7.+t*1.9));
  q *= 1. + sin(r*16.-t*5.)*u_speak*u_level*.03*u_wobble;
  float ql = length(q); if(ql > .999) q *= .999/ql;

  float z = sqrt(1.-dot(q,q));
  vec3 n = normalize(vec3(q,z));
  vec3 I = vec3(0.,0.,-1.);
  float ab = u_aber*.035;
  vec3 dR = refract(I,n,1./(u_ior-ab));
  vec3 dG = refract(I,n,1./u_ior);
  vec3 dB = refract(I,n,1./(u_ior+ab));
  vec2 base = q*u_R/u_zoom;
  float k = u_R*u_refract*1.2;
  float blurPx = u_blur*(1.+u_frost*4.*r*r*r);
  vec2 seed = gl_FragCoord.xy + fract(t);

  vec3 col; float a;
  if(u_hasTex > .5){
    col.r = scr(base + dR.xy/max(.25,-dR.z)*k, blurPx, seed).r;
    col.g = scr(base + dG.xy/max(.25,-dG.z)*k, blurPx, seed).g;
    col.b = scr(base + dB.xy/max(.25,-dB.z)*k, blurPx, seed).b;
    a = 1.;
  } else { col = vec3(.07,.09,.12); a = .14; }

  float lum = dot(col, vec3(.299,.587,.114));
  col = mix(vec3(lum), col, u_sat) * (1.-u_dark);
  col = mix(col, col*u_tint*1.25, u_tintAmt) + u_tint*u_tintAmt*.05;
  col *= 1. - u_edge*pow(r,4.);                                // glass edge is darker: gives highlights something to sit on

  // All lighting is collected separately, then SCREEN-blended so it can brighten
  // but never exceed 1.0 (plain addition is what blew the ball out to white).
  vec3 hl = u_accent*exp(-r*r*5.)*(u_think*(.22+.12*sin(t*3.)) + u_speak*u_level*.35 + u_listen*.05);
  float fres = pow(1.-z, 3.);
  vec3 rimCol = mix(vec3(.82,.93,1.), u_accent, clamp(u_listen*.5+u_speak*.6+u_think*.4,0.,1.));
  float ring = smoothstep(.955,.985,r)*(1.-smoothstep(.985,1.,r));
  hl += rimCol*(fres*.40 + ring*.30)*u_rim;

  vec3 L = normalize(vec3(-.45,-.55,.70));
  vec3 H = normalize(L + vec3(0.,0.,1.));
  float nh = max(dot(n,H),0.);
  float sp = pow(nh,140.)*.9 + pow(nh,10.)*.05;
  hl += vec3(1.)*sp*u_spec;

  vec2 ld = normalize(vec2(.55,.65));
  float cz = pow(max(dot(normalize(q+1e-4),ld),0.),5.)*smoothstep(.55,.93,r)*(1.-smoothstep(.93,1.,r));
  hl += mix(vec3(.6,.85,1.),u_accent,.35)*cz*.35*u_caustic;

  hl = clamp(hl, 0., 1.);
  col = 1. - (1.-clamp(col,0.,1.))*(1.-hl);
  col += (hash(gl_FragCoord.xy+t)-.5)*u_grain;

  if(u_hasTex < .5) a = clamp(.10 + fres*.30 + ring*.22 + sp*u_spec*.5, 0., 1.);
  a *= (1.-smoothstep(.99,1.,r))*u_opacity;
  o = vec4(max(col,0.)*a, a);
}`;

const gl = { ctx: null, prog: null, tex: null, u: {}, ok: false, newFrame: false };

function initGL() {
  const c = el.glass.getContext('webgl2', { premultipliedAlpha: true, alpha: true, antialias: false });
  if (!c) { console.error('WebGL2 is unavailable; using CSS fallback glass.'); el.glass.classList.add('no-gl'); return; }
  const sh = (type, src) => { const s = c.createShader(type); c.shaderSource(s, src); c.compileShader(s);
    if (!c.getShaderParameter(s, c.COMPILE_STATUS)) throw new Error('Shader compile error: ' + c.getShaderInfoLog(s)); return s; };
  try {
    const p = c.createProgram();
    c.attachShader(p, sh(c.VERTEX_SHADER, VERT)); c.attachShader(p, sh(c.FRAGMENT_SHADER, FRAG)); c.linkProgram(p);
    if (!c.getProgramParameter(p, c.LINK_STATUS)) throw new Error('Shader link error: ' + c.getProgramInfoLog(p));
    c.useProgram(p);
    const buf = c.createBuffer(); c.bindBuffer(c.ARRAY_BUFFER, buf);
    c.bufferData(c.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), c.STATIC_DRAW);
    const loc = c.getAttribLocation(p, 'a'); c.enableVertexAttribArray(loc); c.vertexAttribPointer(loc, 2, c.FLOAT, false, 0, 0);
    const n = c.getProgramParameter(p, c.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const name = c.getActiveUniform(p, i).name; gl.u[name] = c.getUniformLocation(p, name); }
    gl.tex = c.createTexture(); c.bindTexture(c.TEXTURE_2D, gl.tex);
    c.texParameteri(c.TEXTURE_2D, c.TEXTURE_MIN_FILTER, c.LINEAR); c.texParameteri(c.TEXTURE_2D, c.TEXTURE_MAG_FILTER, c.LINEAR);
    c.texParameteri(c.TEXTURE_2D, c.TEXTURE_WRAP_S, c.CLAMP_TO_EDGE); c.texParameteri(c.TEXTURE_2D, c.TEXTURE_WRAP_T, c.CLAMP_TO_EDGE);
    c.texImage2D(c.TEXTURE_2D, 0, c.RGBA, 1, 1, 0, c.RGBA, c.UNSIGNED_BYTE, new Uint8Array([0,0,0,255]));
    c.enable(c.BLEND); c.blendFunc(c.ONE, c.ONE_MINUS_SRC_ALPHA);
    gl.ctx = c; gl.prog = p; gl.ok = true;
    console.info('WebGL2 glass shader ready.');
  } catch (e) { console.error(e.message); el.glass.classList.add('no-gl'); }
}

function resizeGL() {
  if (!gl.ok) return;
  const dpr = window.devicePixelRatio || 1;
  const css = S['appearance.ballSize'] + 56;
  el.glass.width = Math.round(css * dpr); el.glass.height = Math.round(css * dpr);
  gl.ctx.viewport(0, 0, el.glass.width, el.glass.height);
}

// per-frame smoothed animation state
const anim = { think: 0, speak: 0, listen: 0, level: 0, t: 0 };

function renderGL(dt) {
  const c = gl.ctx, u = gl.u;
  const target = {
    think: turn.active && !speaker.busy ? 1 : 0,
    speak: speaker.busy ? 1 : 0,
    listen: chatOpen && document.activeElement === el.input && !turn.active && !speaker.busy ? 1 : 0 };
  for (const k of ['think', 'speak', 'listen']) anim[k] += (target[k] - anim[k]) * Math.min(1, dt * 6);
  anim.level += (speaker.level() - anim.level) * Math.min(1, dt * 14);
  anim.t += dt * S['appearance.animSpeed'];

  const useTex = capture.has && el.video.readyState >= 2 && el.video.videoWidth > 0;
  if (useTex && gl.newFrame) {
    c.bindTexture(c.TEXTURE_2D, gl.tex);
    c.texImage2D(c.TEXTURE_2D, 0, c.RGBA, c.RGBA, c.UNSIGNED_BYTE, el.video);
    gl.newFrame = false;
  }
  const rect = el.glass.getBoundingClientRect();
  const D = S['appearance.ballSize'];
  const f = (n, v) => c.uniform1f(u[n], v);
  f('u_hasTex', useTex ? 1 : 0); f('u_time', anim.t); f('u_level', anim.level);
  f('u_listen', anim.listen); f('u_think', anim.think); f('u_speak', anim.speak);
  f('u_scale', (D + 56) / D); f('u_R', D / 2);
  c.uniform2f(u.u_center, window.screenX + rect.left + rect.width / 2, window.screenY + rect.top + rect.height / 2);
  c.uniform2f(u.u_dispO, capture.disp.x, capture.disp.y); c.uniform2f(u.u_dispS, capture.disp.width, capture.disp.height);
  f('u_refract', S['appearance.refraction']); f('u_zoom', S['appearance.zoom']); f('u_ior', S['appearance.ior']);
  f('u_aber', S['appearance.aberration']); f('u_blur', S['appearance.blur']); f('u_frost', S['appearance.frost']);
  f('u_tintAmt', S['appearance.tintAmount']); f('u_dark', S['appearance.darken']); f('u_sat', S['appearance.saturation']);
  f('u_rim', S['appearance.rim']); f('u_spec', S['appearance.specular']); f('u_caustic', S['appearance.caustic']);
  f('u_grain', S['appearance.grain']); f('u_wobble', S['appearance.wobble']); f('u_glow', S['appearance.glow']);
  f('u_shadow', S['appearance.shadow']); f('u_edge', S['appearance.edgeDarkening']); f('u_opacity', S['appearance.opacity']);
  c.uniform3fv(u.u_tint, hex(S['appearance.tintColor'])); c.uniform3fv(u.u_accent, hex(S['appearance.accentColor']));
  c.uniform1i(u.u_tex, 0);
  c.clearColor(0, 0, 0, 0); c.clear(c.COLOR_BUFFER_BIT);
  c.drawArrays(c.TRIANGLE_STRIP, 0, 4);
}

// frosted background for the dialogue box, drawn from the same screen capture
let lastBackdrop = 0;
function drawBackdrop(now) {
  if (now - lastBackdrop < 90 || el.panel.hidden || !capture.has || el.video.videoWidth === 0) return;
  lastBackdrop = now;
  const r = el.panel.getBoundingClientRect(), ov = 24;
  const cw = Math.max(2, Math.round((r.width + ov * 2) / 2)), ch = Math.max(2, Math.round((r.height + ov * 2) / 2));
  if (el.backdrop.width !== cw) el.backdrop.width = cw;
  if (el.backdrop.height !== ch) el.backdrop.height = ch;
  const k = el.video.videoWidth / capture.disp.width;
  const sx = (window.screenX + r.left - ov - capture.disp.x) * k, sy = (window.screenY + r.top - ov - capture.disp.y) * k;
  const g = el.backdrop.getContext('2d');
  g.filter = `blur(${S['chat.blur'] / 2}px) saturate(1.25)`;
  g.drawImage(el.video, sx, sy, (r.width + ov * 2) * k, (r.height + ov * 2) * k, 0, 0, cw, ch);
}

if ('requestVideoFrameCallback' in HTMLVideoElement.prototype) {
  const tick = () => { gl.newFrame = true; el.video.requestVideoFrameCallback(tick); };
  el.video.addEventListener('playing', () => el.video.requestVideoFrameCallback(tick));
} else setInterval(() => { gl.newFrame = true; }, 33);

let lastFrame = performance.now(), lastRender = 0;
function frame(now) {
  requestAnimationFrame(frame);
  const busy = turn.active || speaker.busy || dragging || chatOpen;
  const fps = busy ? S['appearance.activeFps'] : S['appearance.idleFps'];
  if (now - lastRender < 1000 / fps - 2) return;
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now; lastRender = now;
  if (gl.ok) renderGL(dt);
  drawBackdrop(now);
}

// ============================================================ voice playback
class Speaker {
  constructor() { this.ctx = null; this.queue = []; this.playing = false; this.pending = 0; this.sys = 0;
    this.chain = Promise.resolve(); this.muted = false; this.src = null; this.onIdle = null; }
  ensure() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.gain = this.ctx.createGain(); this.analyser = this.ctx.createAnalyser(); this.analyser.fftSize = 512;
      this.buf = new Uint8Array(this.analyser.fftSize);
      this.gain.connect(this.analyser); this.analyser.connect(this.ctx.destination);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
    this.gain.gain.value = this.muted ? 0 : S['voice.volume'];
  }
  get busy() { return this.playing || this.queue.length > 0 || this.pending > 0 || this.sys > 0; }
  level() {
    if (this.sys > 0) return 0.35 + 0.25 * Math.sin(performance.now() / 90);
    if (!this.playing || !this.analyser) return 0;
    this.analyser.getByteTimeDomainData(this.buf);
    let s = 0; for (const v of this.buf) { const x = (v - 128) / 128; s += x * x; }
    return Math.min(1, Math.sqrt(s / this.buf.length) * 3.2);
  }
  enqueueWav(b64) {
    this.ensure(); this.pending++;
    this.chain = this.chain.then(async () => {
      try {
        const bin = atob(b64), u8 = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
        this.queue.push(await this.ctx.decodeAudioData(u8.buffer));
      } catch (e) { console.error('Audio decode failed: ' + e.message); }
      this.pending--; this.pump();
    });
  }
  pump() {
    if (this.playing) return;
    const buf = this.queue.shift();
    if (!buf) { if (!this.busy && this.onIdle) this.onIdle(); return; }
    this.playing = true;
    const s = this.ctx.createBufferSource(); s.buffer = buf; s.connect(this.gain);
    s.onended = () => { this.playing = false; this.pump(); };
    this.src = s; s.start();
  }
  enqueueText(text) {
    if (!('speechSynthesis' in window)) { console.error('System speech is not available in this build.'); return; }
    const u = new SpeechSynthesisUtterance(text);
    u.rate = S['voice.speed']; u.volume = this.muted ? 0 : S['voice.volume'];
    const want = S['voice.systemVoice'];
    if (want) { const v = speechSynthesis.getVoices().find(v => v.name === want); if (v) u.voice = v; }
    this.sys++;
    const done = () => { this.sys--; if (!this.busy && this.onIdle) this.onIdle(); };
    u.onend = done; u.onerror = done;
    speechSynthesis.speak(u);
  }
  stop() {
    this.queue = []; this.pending = 0; this.chain = Promise.resolve();
    if (this.src) { try { this.src.onended = null; this.src.stop(); } catch (_) {} }
    this.playing = false; this.sys = 0;
    if ('speechSynthesis' in window) speechSynthesis.cancel();
  }
}
const speaker = new Speaker();
speaker.onIdle = () => scheduleAutoHide();

// ============================================================ dialogue box
function scrollDown() { el.msgs.scrollTop = el.msgs.scrollHeight; }
function addMsg(kind, text, meta) {
  const d = document.createElement('div'); d.className = 'msg ' + kind; d.appendChild(document.createTextNode(text));
  if (meta) { const m = document.createElement('span'); m.className = 'meta'; m.textContent = meta; d.appendChild(m); }
  el.msgs.appendChild(d);
  while (el.msgs.children.length > S['chat.maxMessages']) el.msgs.firstChild.remove();
  scrollDown(); return d;
}
function setNotice(text, bad) { el.notice.hidden = !text; el.notice.textContent = text || ''; el.notice.classList.toggle('bad', !!bad); }

function openChat() {
  chatOpen = true; el.panel.hidden = false; clearTimeout(hideTimer); el.input.focus(); scrollDown();
}
function closeChat() { if (speechListening) stopSpeechInput(false); chatOpen = false; el.panel.hidden = true; el.input.blur(); crystal.win.ignoreMouse(true); }
function toggleChat() { chatOpen ? closeChat() : openChat(); }
function scheduleAutoHide() {
  clearTimeout(hideTimer);
  const s = S['chat.autoHideSeconds'];
  if (s > 0 && chatOpen && !turn.active && !speaker.busy) hideTimer = setTimeout(closeChat, s * 1000);
}

function sendChat(text) {
  text = text.trim(); if (!text) return;
  sentHistory.push(text); sentIdx = sentHistory.length;
  if (S['voice.interruptOnSend']) speaker.stop();
  speaker.ensure();                                   // user gesture: unlock audio
  if (S['chat.showUserMessages']) addMsg('user', text);
  if (!ws || ws.readyState !== 1) { addMsg('error', 'Not connected to the brain yet. Open the Debug console to see why.'); return; }
  turn.active = true; turn.msgEl = null; turn.text = ''; turn.buffered = '';
  ws.send(JSON.stringify({ type: 'chat', text, session_id: sessionId }));
  el.stop.hidden = false;
}

// ---- provider + effort chips (glass UI). Selection is stored in settings so the backend sees it live.
function renderPickers() {
let list = []; try { list = JSON.parse(S['llm.providers'] || '[]'); } catch {}
const provs = [{ id: 'ollama', name: 'Ollama' }, ...list.filter(p => p && p.enabled !== false && p.baseUrl)];
const cur = provs.some(p => p.id === S['llm.provider']) ? S['llm.provider'] : 'ollama';
const mk = (box, items, active, onPick) => { box.textContent = ''; for (const [id, label] of items) {
  const b = document.createElement('button'); b.type = 'button'; b.className = 'chip' + (id === active ? ' on' : ''); b.textContent = label;
  b.onclick = () => onPick(id); box.append(b); } };
mk($('provChips'), provs.map(p => [p.id, p.name]), cur, id => crystal.settings.set({ 'llm.provider': id }));
mk($('effortChips'), [['auto', 'Auto'], ['fast', 'Low'], ['mid', 'Medium'], ['heavy', 'High']], S['llm.mode'], id => crystal.settings.set({ 'llm.mode': id }));
$('provChips').hidden = provs.length < 2;
}

el.form.addEventListener('submit', e => {
  e.preventDefault();
  if (speechListening) { stopSpeechInput(true); return; }
  if (speechStopping) return;
  const t = el.input.value; el.input.value = ''; sendChat(t);
});
el.mic.addEventListener('click', toggleSpeechRecognition);
el.stop.addEventListener('click', stopEverything);
function stopEverything() { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'stop' })); speaker.stop(); turn.active = false; el.stop.hidden = true; }
function setListening(on, stopping = false) {
  speechListening = on;
  speechStopping = stopping;
  el.mic.classList.toggle('listening', on);
  el.mic.classList.toggle('processing', stopping);
  el.mic.querySelector('svg path').setAttribute('d', on
    ? 'M6 6h12v12H6z'
    : 'M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.93V21h2v-3.07A7 7 0 0 0 19 11Z');
  el.mic.setAttribute('aria-label', on ? 'Stop voice input' : stopping ? 'Transcribing voice input' : 'Start voice input');
  el.mic.title = on ? 'Stop voice input' : stopping ? 'Transcribing voice input…' : 'Start voice input';
  el.mic.disabled = stopping;
}
async function toggleSpeechRecognition() {
  if (speechListening) { stopSpeechInput(true); return; }
  if (speechStopping || !S['voice.inputEnabled']) return;
  if (turn.active || speaker.busy) { addMsg('tool', 'Voice input is unavailable while Crystal is responding.'); return; }
  if (!speechInput) speechInput = new LocalSpeechInput(text => {
    el.input.value = [el.input.value.trim(), text].filter(Boolean).join(' ');
    el.input.dispatchEvent(new Event('input', { bubbles: true }));
    el.input.focus();
    setListening(false);
  }, error => { setListening(false); addMsg('error', `Local speech transcription failed: ${error.message}`); },
  () => setListening(false, true));
  speechInput.language = S['voice.inputLanguage'] || 'en-US';
  try {
    await speechInput.start();
    setListening(true);
  } catch (error) {
    setListening(false);
    addMsg('error', `Could not access the microphone: ${error.message}`);
  }
}
function stopSpeechInput(transcribe = false) {
  if (!speechInput || !speechListening || speechStopping) return;
  setListening(false, true);
  speechInput.stop(transcribe).finally(() => setListening(false));
}
el.input.addEventListener('keydown', e => {
  if (e.key === 'Escape') { e.preventDefault(); if (turn.active || speaker.busy) stopEverything(); else if (S['behavior.escClosesChat']) closeChat(); }
  else if (e.key === 'ArrowUp' && sentHistory.length) { e.preventDefault(); sentIdx = Math.max(0, sentIdx - 1); el.input.value = sentHistory[sentIdx] || ''; }
  else if (e.key === 'ArrowDown' && sentHistory.length) { e.preventDefault(); sentIdx = Math.min(sentHistory.length, sentIdx + 1); el.input.value = sentHistory[sentIdx] || ''; }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && chatOpen && document.activeElement !== el.input) closeChat(); });
$('allowBtn').addEventListener('click', () => answerConfirm(true));
$('denyBtn').addEventListener('click', () => answerConfirm(false));
function answerConfirm(allow) {
  if (!pendingConfirm) return;
  ws.send(JSON.stringify({ type: 'confirm_response', id: pendingConfirm, allow }));
  pendingConfirm = null; el.confirm.hidden = true;
}

// ============================================================ backend socket
let ws = null, wsPort = 0, reconnectTimer = null, connecting = false;
async function connectWs() {
  if (connecting) return;
  connecting = true;
  try { await connectWsInner(); } finally { connecting = false; }
}
async function connectWsInner() {
  clearTimeout(reconnectTimer);
  const cur = await crystal.backend.info();
  if (ws && wsPort === cur.port && ws.readyState <= 1) return;   // already connected/connecting
  if (ws) { ws.onclose = null; try { ws.close(); } catch (_) {} ws = null; }
  const info = await crystal.backend.info();
  if (info.state !== 'ready') { setNotice(`Brain is ${info.state}… open the Debug console for details.`, info.state === 'crashed'); return; }
  wsPort = info.port;
  ws = new WebSocket(`ws://127.0.0.1:${info.port}/ws?token=${info.token}`);
  ws.onopen = () => { setNotice(''); console.info('Connected to backend.'); initSession(); };
  ws.onerror = () => console.error('WebSocket error talking to the backend.');
  ws.onclose = () => { setNotice('Brain disconnected — reconnecting…', true); reconnectTimer = setTimeout(connectWs, 1500); };
  ws.onmessage = ev => { try { onServer(JSON.parse(ev.data)); } catch (e) { console.error('Bad server message: ' + e.message); } };
}
crystal.backend.onState(info => { if (info.state === 'ready') connectWs(); else setNotice(`Brain is ${info.state}… open the Debug console.`, info.state === 'crashed'); });

function ensureAssistantMsg() { if (!turn.msgEl) turn.msgEl = addMsg('assistant', ''); return turn.msgEl; }

function onServer(m) {
  switch (m.type) {
    case 'turn_start': if (speechListening) stopSpeechInput(); console.info(`Using ${m.tier} model: ${m.model}`); break;
    case 'token':
      turn.text += m.text;
      if (S['chat.streamText']) { ensureAssistantMsg().firstChild.nodeValue = turn.text; scrollDown(); }
      break;
    case 'tool_call':
      turn.msgEl = null; turn.text = '';
      if (S['agent.showToolActivity']) addMsg('tool', m.description);
      break;
    case 'tool_result': if (!m.ok) addMsg('tool', 'That did not work.'); break;
    case 'confirm': pendingConfirm = m.id; el.confirmText.textContent = m.description + '?'; el.confirm.hidden = false; openChat(); break;
    case 'audio': if (speechListening) stopSpeechInput(); speaker.enqueueWav(m.wav); break;
    case 'speak': if (speechListening) stopSpeechInput(); speaker.ensure(); speaker.enqueueText(m.text); break;
    case 'speech_done': if (!speaker.busy) scheduleAutoHide(); break;
    case 'info': addMsg('tool', m.message); break;
    case 'error': console.error(`[${m.where}] ${m.message}`); addMsg('error', m.message); break;
    case 'stopped': turn.active = false; el.stop.hidden = true; break;
    case 'done': {
      if (!S['chat.streamText'] && m.text) { ensureAssistantMsg().firstChild.nodeValue = m.text; }
      if (turn.msgEl && S['debug.chatTimings'] && m.seconds) {
        const meta = document.createElement('span'); meta.className = 'meta'; meta.textContent = `${m.model} · ${m.seconds}s`; turn.msgEl.appendChild(meta);
      }
      turn.active = false; el.stop.hidden = true; scrollDown(); scheduleAutoHide(); break;
    }
    default: break;
  }
}

async function initSession() {
  if (sessionId) return;
  try {
    let id = S['history.resumeLast'] ? localStorage.getItem('crystal.session') : null;
    if (S['history.resumeLast'] && !id) { const r = await crystal.backend.api('GET', '/api/history'); id = r.data && r.data.latest; }
    sessionId = id || uuid(); localStorage.setItem('crystal.session', sessionId);
    if (id) {
      const r = await crystal.backend.api('GET', `/api/history/${id}?limit=6`);
      for (const msg of (r.data && r.data.messages) || []) if (msg.role === 'assistant' || S['chat.showUserMessages']) addMsg(msg.role, msg.content);
    }
  } catch (e) { console.error('Could not restore chat history: ' + e.message); sessionId = uuid(); }
}
function newChat() { sessionId = uuid(); localStorage.setItem('crystal.session', sessionId); el.msgs.textContent = ''; stopEverything(); openChat(); }

// ============================================================ mouse: drag, click, click-through
let drag = null;
const interactive = on => { if (!dragging) crystal.win.ignoreMouse(!on); };
for (const n of [el.hit, el.panel, el.badge]) {
  n.addEventListener('mouseenter', () => interactive(true));
  n.addEventListener('mouseleave', () => interactive(false));
}
el.hit.addEventListener('pointerdown', e => {
  if (e.button !== 0) return;
  el.hit.setPointerCapture(e.pointerId);
  drag = { sx: e.screenX, sy: e.screenY, moved: false }; crystal.win.dragStart();
});
el.hit.addEventListener('pointermove', e => {
  if (!drag) return;
  const dx = e.screenX - drag.sx, dy = e.screenY - drag.sy;
  if (!drag.moved && Math.hypot(dx, dy) > 4) { drag.moved = true; dragging = true; }
  if (drag.moved) crystal.win.dragMove(dx, dy);
});
el.hit.addEventListener('pointerup', () => {
  if (!drag) return;
  crystal.win.dragEnd(); const moved = drag.moved; drag = null; dragging = false;
  if (!moved) toggleChat();
});
for (const n of [el.hit, el.panel]) n.addEventListener('contextmenu', e => { e.preventDefault(); crystal.win.contextMenu(); });
el.badge.addEventListener('click', () => { errorCount = 0; el.badge.hidden = true; crystal.win.openConsole(); });

// ============================================================ boot
crystal.settings.onChange((all, changed) => {
  S = all; applyLayout();
  if (changed.some(k => k.startsWith('behavior.capture'))) startCapture();
  if (speaker.gain) speaker.gain.gain.value = speaker.muted ? 0 : S['voice.volume'];
});
crystal.win.onToggleChat(toggleChat);
crystal.win.onNewChat(newChat);
crystal.win.onMute(() => { speaker.muted = !speaker.muted; if (speaker.gain) speaker.gain.gain.value = speaker.muted ? 0 : S['voice.volume']; if (speaker.muted) speechSynthesis.cancel(); addMsg('tool', speaker.muted ? 'Voice muted.' : 'Voice unmuted.'); });
crystal.capture.onDisplayChanged(() => { if (!S['appearance.ballSize']) return; console.info('Display changed; restarting capture.'); startCapture(); });
crystal.log.onEntry(e => { if (e.level === 'error' && S['debug.errorBadge']) { errorCount++; el.badge.hidden = false; el.badge.title = `${errorCount} error(s) — click to open the debug console`; } });

(async function boot() {
  S = await crystal.settings.all();
  applyLayout(); initGL(); applyLayout();
  const counts = await crystal.log.counts(); if (counts.error && S['debug.errorBadge']) { errorCount = counts.error; el.badge.hidden = false; }
  requestAnimationFrame(frame);
  startCapture();
  connectWs();
  if (S['behavior.openChatOnStart']) openChat();
})();
