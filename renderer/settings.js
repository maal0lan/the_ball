'use strict';
const $ = id => document.getElementById(id);
window.addEventListener('error', e => console.error(`Uncaught: ${e.message} @ ${e.filename}:${e.lineno}`));
window.addEventListener('unhandledrejection', e => console.error(`Unhandled rejection: ${e.reason && (e.reason.stack || e.reason)}`));

let schema, values = {}, defaults = {}, current = 'brain', modelNames = [];
const TOOLS = 'tools';

function h(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else if (v !== false && v != null) n.setAttribute(k, v === true ? '' : v); }
  for (const k of kids.flat()) n.append(k instanceof Node ? k : document.createTextNode(k));
  return n;
}
const timers = {};
function commit(key, value, immediate) {
  values[key] = value;
  clearTimeout(timers[key]);
  const go = () => crystal.settings.set({ [key]: value });
  immediate ? go() : (timers[key] = setTimeout(go, 140));
}

function control(f, onChange) {
  const v = values[f.key];
  switch (f.type) {
    case 'bool': { const i = h('input', { type: 'checkbox' }); i.checked = !!v; i.onchange = () => onChange(i.checked, true); return [h('label', { class: 'sw' }, i, h('span'))]; }
    case 'number': {
      const num = h('input', { type: 'number', min: f.min, max: f.max, step: f.step, value: v });
      num.onchange = () => { const n = parseFloat(num.value); onChange(n, true); if (rng) rng.value = n; };
      if (!f.slider) return [num, f.unit || ''];
      const out = h('span', { class: 'val' }, `${v}${f.unit ? ' ' + f.unit : ''}`);
      var rng = h('input', { type: 'range', min: f.min, max: f.max, step: f.step, value: v });
      rng.oninput = () => { const n = parseFloat(rng.value); out.textContent = `${n}${f.unit ? ' ' + f.unit : ''}`; num.value = n; onChange(n, false); };
      return [rng, out, num];
    }
    case 'select': { const s = h('select', {}, f.options.map(o => h('option', { value: o }, o))); s.value = v; s.onchange = () => onChange(s.value, true); return [s]; }
    case 'color': { const c = h('input', { type: 'color', value: v }); c.oninput = () => { t.value = c.value; onChange(c.value, false); }; var t = h('input', { type: 'text', value: v, style: 'width:110px' }); t.onchange = () => { c.value = t.value; onChange(t.value, true); }; return [c, t]; }
    case 'textarea': { const a = h('textarea', {}); a.value = v; a.oninput = () => onChange(a.value, false); return [a]; }
    case 'folder': {
      const t = h('input', { type: 'text', value: v, placeholder: 'No folder chosen' }); t.onchange = () => onChange(t.value, true);
      const b = h('button', { class: 'b', type: 'button', onclick: async () => { const p = await crystal.app.chooseFolder(); if (p) { t.value = p; onChange(p, true); } } }, 'Browse…');
      return [t, b];
    }
    case 'model': {
      const id = 'dl-' + f.key.replace(/\W/g, '');
      const t = h('input', { type: 'text', value: v, list: id }); t.onchange = () => onChange(t.value.trim(), true);
      return [t, h('datalist', { id }, modelNames.map(m => h('option', { value: m })))];
    }
    case 'hotkey': {
      const t = h('input', { type: 'text', value: v, placeholder: 'Press a key combination…' });
      t.onkeydown = e => {
        e.preventDefault();
        if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return;
        const parts = []; if (e.ctrlKey || e.metaKey) parts.push('CommandOrControl'); if (e.altKey) parts.push('Alt'); if (e.shiftKey) parts.push('Shift');
        let k = e.key === ' ' ? 'Space' : e.key.length === 1 ? e.key.toUpperCase() : e.key.replace('Arrow', '');
        parts.push(k); t.value = parts.join('+'); onChange(t.value, true);
      };
      return [t, h('span', { class: 'restart' }, 'click the box and press the keys')];
    }
    case 'providers': return [providerEditor(v, onChange)];
    case 'password': { const t = h('input', { type: 'password', value: v }); t.onchange = () => onChange(t.value, true); return [t]; }
    default: { const t = h('input', { type: 'text', value: v }); t.onchange = () => onChange(t.value, true); return [t]; }
  }
}

function providerEditor(json, onChange) {
  let list; try { list = JSON.parse(json || '[]'); if (!Array.isArray(list)) list = []; } catch { list = []; }
  const box = h('div', { class: 'prov' });
  const save = imm => onChange(JSON.stringify(list), imm);
  const inp = (p, key, ph, type = 'text', sub) => {
    const i = h('input', { type, placeholder: ph, value: (sub ? (p[sub] || {})[key] : p[key]) || '' });
    i.onchange = () => { if (sub) { p[sub] = p[sub] || {}; p[sub][key] = i.value.trim(); } else p[key] = i.value.trim(); save(true); };
    return i;
  };
  const draw = () => {
    box.textContent = '';
    for (const p of list) {
      const out = h('small', { class: 'restart' }, '');
      const on = h('input', { type: 'checkbox' }); on.checked = p.enabled !== false; on.onchange = () => { p.enabled = on.checked; save(true); };
      box.append(h('div', { class: 'provcard' },
        h('div', { class: 'ctl' }, h('label', { class: 'sw' }, on, h('span')), inp(p, 'name', 'Name (e.g. OpenRouter)'),
          h('button', { class: 'b', type: 'button', onclick: () => { if (confirm(`Delete provider “${p.name || p.id}”?`)) { list = list.filter(x => x !== p); save(true); draw(); } } }, 'Delete')),
        h('div', { class: 'ctl' }, inp(p, 'baseUrl', 'API link, e.g. https://openrouter.ai/api/v1'), inp(p, 'apiKey', 'API key', 'password')),
        h('div', { class: 'ctl' }, inp(p, 'fast', 'Low model', 'text', 'models'), inp(p, 'mid', 'Medium model', 'text', 'models'), inp(p, 'heavy', 'High model', 'text', 'models')),
        h('div', { class: 'ctl' }, h('button', { class: 'b', type: 'button', onclick: async () => {
          out.textContent = 'Testing…'; const r = await crystal.backend.api('POST', '/api/test/provider', { id: p.id, tier: 'fast' }); const d = r.data || {};
          out.textContent = d.ok ? `OK (${d.model}): ${d.reply}` : `Failed: ${d.error || JSON.stringify(r)}`;
        } }, 'Test low model'), out)));
    }
    box.append(h('button', { class: 'b pri', type: 'button', onclick: () => {
      list.push({ id: 'p' + Date.now().toString(36), name: 'New provider', baseUrl: '', apiKey: '', enabled: true, models: { fast: '', mid: '', heavy: '' } }); save(true); draw();
    } }, '+ Add provider'),
    h('div', { class: 'restart' }, 'Any OpenAI-compatible endpoint works (OpenRouter, Groq, Together, OpenAI, LM Studio, …). Keys are stored in plain text in settings.json.'));
  };
  draw(); return box;
}

function fieldRow(f) {
  const rst = h('button', { class: 'rst', type: 'button', title: 'Reset to default', hidden: values[f.key] === f.default }, 'Reset');
  const upd = () => { rst.hidden = values[f.key] === f.default; };
  const ctl = control(f, (val, imm) => { commit(f.key, val, imm); upd(); });
  rst.onclick = async () => { await crystal.settings.reset([f.key]); values[f.key] = f.default; render(); };
  const note = f.apply === 'backend-restart' ? h('div', { class: 'restart' }, 'Needs a backend restart (Tools tab)') : f.apply === 'app-restart' ? h('div', { class: 'restart' }, 'Needs an app restart') : '';
  return h('div', { class: 'row' },
    h('div', { class: 'lab' }, h('b', {}, f.label), h('small', {}, f.help || ''), h('code', {}, f.key)),
    h('div', {}, h('div', { class: 'ctl' }, ctl, rst), note));
}

function nav() {
  const list = $('navList'); list.textContent = '';
  for (const s of schema.sections) list.append(h('button', { class: s.id === current ? 'on' : '', onclick: () => { current = s.id; $('search').value = ''; render(); } }, s.title));
  list.append(h('button', { class: current === TOOLS ? 'on' : '', onclick: () => { current = TOOLS; $('search').value = ''; render(); } }, 'Tools & diagnostics'));
}

function render() {
  nav();
  const box = $('fields'); box.textContent = '';
  const q = $('search').value.trim().toLowerCase();
  if (q) {
    $('title').textContent = `Results for “${q}”`; $('desc').textContent = '';
    for (const s of schema.sections) for (const f of s.fields)
      if ((f.label + ' ' + f.key + ' ' + (f.help || '')).toLowerCase().includes(q)) box.append(fieldRow(f));
    if (!box.children.length) box.append(h('p', {}, 'Nothing matches that search.'));
    return;
  }
  if (current === TOOLS) return renderTools(box);
  const s = schema.sections.find(x => x.id === current);
  $('title').textContent = s.title; $('desc').textContent = s.description;
  for (const f of s.fields) box.append(fieldRow(f));
  box.append(h('div', { class: 'row' }, h('div', { class: 'lab' }, h('b', {}, 'Reset this page')), h('button', { class: 'b', onclick: async () => {
    if (confirm(`Reset every setting on “${s.title}” to its default?`)) { await crystal.settings.reset(s.fields.map(f => f.key)); values = await crystal.settings.all(); render(); } } }, 'Reset to defaults')));
}

function renderTools(box) {
  $('title').textContent = 'Tools & diagnostics'; $('desc').textContent = 'Test each part of the pipeline and see exactly what fails.';
  const out = h('div', { id: 'toolsOut' }, 'Results appear here.');
  const say = t => { out.textContent = t; };
  const btn = (label, fn, pri) => h('button', { class: 'b' + (pri ? ' pri' : ''), onclick: async () => { say(`${label}…`); try { await fn(); } catch (e) { say(`${label} crashed: ${e.message}`); console.error(e.stack || e.message); } } }, label);
  const api = (m, p, b) => crystal.backend.api(m, p, b);
  const actions = h('div', { class: 'actions' },
    btn('Backend status', async () => { const r = await api('GET', '/api/status'); say(JSON.stringify(r.data, null, 2)); }, true),
    btn('Test the three brains', async () => { const r = await api('POST', '/api/test/llm', {}); say(JSON.stringify(r.data, null, 2)); }),
    btn('Test voice', async () => {
      const r = await api('POST', '/api/test/tts', {}); const d = r.data;
      if (!d || !d.ok) return say('Voice failed: ' + (d && d.error || JSON.stringify(r)));
      say(`Voice OK (${d.engine}${d.seconds ? ', ' + d.seconds + 's' : ''}).`);
      if (d.wav) new Audio('data:audio/wav;base64,' + d.wav).play(); else if (d.engine === 'system') speechSynthesis.speak(new SpeechSynthesisUtterance('Crystal voice check.'));
    }),
    btn('Check workspace folder', async () => { const r = await api('POST', '/api/test/workspace'); say(JSON.stringify(r.data, null, 2)); }),
    btn('List / reload skills', async () => { const r = await api('POST', '/api/skills/reload'); const d = r.data || {}; say(`Skills folder: ${d.dir}\n\n` + (d.skills || []).map(s => s.error ? `✗ ${s.name}: ${s.error}` : `${s.active ? '●' : '○'} ${s.name}  [${s.perm}${s.confirm ? ', asks first' : ''}, ${s.source}]${s.active ? '' : '\n      ↳ inactive because: ' + s.reason}`).join('\n')); }),
    btn('Refresh model list', async () => { const r = await api('GET', '/api/models'); modelNames = (r.data && r.data.llm_models) || []; say(modelNames.length ? 'Installed Ollama models:\n' + modelNames.join('\n') : 'No models found. Is Ollama running?'); }),
    btn('Restart backend', async () => { await crystal.backend.restart(); say('Backend restarted. Watch the Debug console.'); }),
    btn('Open debug console', () => crystal.win.openConsole()),
    btn('Open data folder', () => crystal.app.openDataFolder()),
    btn('Export settings…', async () => { const p = await crystal.settings.exportJson(); say(p ? 'Saved to ' + p : 'Cancelled.'); }),
    btn('Import settings…', async () => { const c = await crystal.settings.importJson(); values = await crystal.settings.all(); render(); say(c ? `Imported ${c.length} changed settings.` : 'Cancelled.'); }),
    btn('Reset ALL settings', async () => { if (confirm('Reset every setting to default?')) { await crystal.settings.reset(); values = await crystal.settings.all(); render(); } }),
  );
  box.append(actions, out);
  crystal.app.version().then(v => out.textContent = `Crystal ${v.app} · Electron ${v.electron} · Chromium ${v.chrome} · ${v.platform}`);
}

(async function boot() {
  schema = await crystal.settings.schema(); values = await crystal.settings.all();
  for (const s of schema.sections) for (const f of s.fields) defaults[f.key] = f.default;
  const r = await crystal.backend.api('GET', '/api/models'); modelNames = (r.data && r.data.llm_models) || [];
  crystal.backend.onState(async info => { if (info.state === 'ready') { const m = await crystal.backend.api('GET', '/api/models'); modelNames = (m.data && m.data.llm_models) || []; } });
  $('search').addEventListener('input', render);
  render();
})();
