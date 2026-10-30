'use strict';
const $ = id => document.getElementById(id);
window.addEventListener('error', e => console.error(`Uncaught: ${e.message} @ ${e.filename}:${e.lineno}`));
window.addEventListener('unhandledrejection', e => console.error(`Unhandled rejection: ${e.reason && (e.reason.stack || e.reason)}`));

let schema, values = {}, defaults = {}, current = 'brain', modelNames = [];
const TOOLS = 'tools';
const WORKSPACES = 'workspaces';

function h(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else if (v !== false && v != null) n.setAttribute(k, v === true ? '' : v); }
  for (const k of kids.flat()) { if (k == null || k === false) continue; n.append(k instanceof Node ? k : document.createTextNode(k)); }
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
  list.append(h('button', { class: current === WORKSPACES ? 'on' : '', onclick: () => { current = WORKSPACES; $('search').value = ''; render(); } }, 'Workspaces'));
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
  if (current === WORKSPACES) return renderWorkspaces(box);
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
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const trustMap = () => { try { const m = JSON.parse(values['agent.trustedSkills'] || '{}'); return m && typeof m === 'object' ? m : {}; } catch { return {}; } };
  const setTrust = async m => { await crystal.settings.set({ 'agent.trustedSkills': JSON.stringify(m) }); values = await crystal.settings.all(); await sleep(500); };  // settings are pushed to the backend asynchronously
  const reloadSkills = async () => { const r = await api('POST', '/api/skills/reload'); showSkills(r.data || {}); };
  const showSkills = d => {
    const files = d.files || [], errs = (d.skills || []).filter(s => s.error), tools = (d.skills || []).filter(s => !s.error);
    const head = h('p', { style: 'white-space:pre-wrap' }, `Skills folder: ${d.dir}\nSkill trust: ${d.trust_mode}` + (d.trust_mode === 'warn' ? '  ⚠ unreviewed skills are loading anyway' : ''));
    const rows = files.map(f => {
      const ok = f.trust === 'builtin' || f.trust === 'trusted';
      const state = f.trust === 'builtin' ? '✓ bundled' : f.trust === 'trusted' ? '✓ trusted by you' : f.trust === 'modified' ? '⚠ CHANGED since trusted' : '⚠ not reviewed';
      const kind = f.kind === 'code' ? 'code (runs with your full privileges)' : 'instructions';
      const pre = h('pre', { style: 'display:none;max-height:240px;overflow:auto;white-space:pre-wrap' });
      const view = h('button', { class: 'b', onclick: async () => {
        if (pre.style.display === 'none') { const r = await api('GET', '/api/skills/source?file=' + encodeURIComponent(f.file)); pre.textContent = r.data && r.data.text != null ? r.data.text + (r.data.truncated ? '\n…(truncated)' : '') : 'Could not read the file.'; pre.style.display = 'block'; } else pre.style.display = 'none'; } }, 'View source');
      const act = ok && f.trust === 'trusted'
        ? h('button', { class: 'b', onclick: async () => { const m = trustMap(); delete m[f.file]; await setTrust(m); await reloadSkills(); } }, 'Revoke trust')
        : !ok ? h('button', { class: 'b pri', onclick: async () => {
            if (!confirm(`Trust ${f.file}?\n\nsha256 ${f.sha256.slice(0, 16)}…\nKind: ${kind}\n\nOnly trust a file you wrote or have read. If the file changes even by one byte, trust is withdrawn automatically.`)) return;
            await setTrust({ ...trustMap(), [f.file]: f.sha256 }); await reloadSkills(); } }, 'Trust this skill') : null;
      return h('div', { class: 'row' }, h('div', { class: 'lab' }, h('b', {}, `${ok ? '' : '⚠ '}${f.file}`),
        h('div', {}, `${state} · ${kind} · ${f.loaded ? 'loaded' : 'NOT loaded'} · sha256 ${f.sha256.slice(0, 12)}`),
        f.warning ? h('div', {}, f.warning) : null, f.provides && f.provides.length ? h('div', {}, 'provides: ' + f.provides.join(', ')) : null, pre),
        view, act);
    });
    const toolList = tools.length ? h('pre', {}, tools.map(s => `${s.active ? '●' : '○'} ${s.name}  [${s.perm}${s.confirm ? ', asks first' : ''}, ${s.source}]${s.active ? '' : '\n      ↳ inactive because: ' + s.reason}`).join('\n')) : null;
    const errList = errs.length ? h('pre', {}, errs.map(s => `✗ ${s.name}: ${s.error}`).join('\n')) : null;
    out.replaceChildren(head, ...rows, ...(toolList ? [toolList] : []), ...(errList ? [errList] : []));
  };
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
    btn('List / reload skills', async () => { const r = await api('POST', '/api/skills/reload'); showSkills(r.data || {}); }),
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

// ---------------------------------------------------------------- workspaces UI
async function renderWorkspaces(box) {
  $('title').textContent = 'Workspaces';
  $('desc').textContent = 'Named folders the agent can read/write in. Switching requires confirmation.';
  box.textContent = '';

  const out = h('div', { id: 'wsOut', style: 'white-space:pre-wrap; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin-bottom: 14px; max-width: 880px;' }, 'Loading…');
  const say = t => { out.textContent = t; };
  box.append(out);

  const refresh = async () => {
    say('Loading…');
    const r = await crystal.backend.api('GET', '/api/workspaces');
    if (!r.ok) { say('Failed to load workspaces: ' + (r.data && r.data.error || JSON.stringify(r))); return; }
    const data = r.data || {};
    const list = data.workspaces || [];
    const active = data.active;
    out.textContent = '';

    const activeName = active && active.name;

    // Active indicator
    if (active) {
      box.append(h('div', { style: 'margin-bottom: 10px;' },
        h('b', {}, 'Active: '), h('span', { style: 'color: var(--accent); margin-left: 6px;' }, active.name),
        h('span', { style: 'color: var(--mute); margin-left: 10px; font-size: 12px;' }, '→ ' + active.path)));
    } else {
      box.append(h('div', { style: 'margin-bottom: 10px; color: var(--mute);' },
        h('b', {}, 'Active: '), h('span', { style: 'color: var(--bad);' }, '(no workspace selected)')));
    }

    // List
    const ul = h('div', { style: 'display:flex;flex-direction:column;gap:8px;' });
    if (!list.length) {
      ul.append(h('p', { style: 'color: var(--mute); margin: 8px 0;' }, 'No saved workspaces yet. Add one below.'));
    }
    for (const w of list) {
      const perms = w.permissions || {};
      const permBadge = (p) => {
        const on = !!perms[p];
        return h('span', { style: 'font-size:11px;padding:2px 8px;border-radius:10px;background:' + (on ? 'var(--accent)' : '#263447') + ';color:' + (on ? '#07211d' : 'var(--mute)') + ';' }, p[0].toUpperCase());
      };
      const isActive = w.name === activeName;
      const row = h('div', { style: 'border:1px solid var(--line);border-radius:10px;padding:10px;display:flex;gap:10px;align-items:center;background:' + (isActive ? 'rgba(127,214,201,.12)' : 'transparent') + ';' });
      row.append(
        h('div', { style: 'flex:1;min-width:0;' },
          h('div', { style: 'font-weight:600;' }, w.name),
          h('div', { style: 'color: var(--mute); font-size: 12px; word-break:break-all;' }, w.path)),
        h('div', { style: 'display:flex;gap:6px;' }, permBadge('read'), permBadge('write'), permBadge('delete'), permBadge('exec')),
        h('div', { style: 'display:flex;gap:6px;' },
          h('button', { class: 'b', type: 'button', onclick: async () => {
            const ok = confirm(`Switch to workspace “${w.name}”?\n\n${w.path}\n\nThis changes the folder the agent can access.`);
            if (!ok) return;
            const r = await crystal.backend.api('POST', '/api/workspaces/switch', { name: w.name });
            if (!r.ok) { say('Switch failed: ' + (r.data && r.data.error || JSON.stringify(r))); return; }
            await crystal.settings.set({ 'agent.workspace': r.data.active.path, 'agent.activeWorkspace': w.name });
            await crystal.settings.all(); // refresh values
            say('Switched to “' + w.name + '”.');
            refresh();
          } }, isActive ? 'Active' : 'Switch'),
          h('button', { class: 'b', type: 'button', onclick: async () => {
            const np = prompt('New path for “' + w.name + '”: ', w.path);
            if (np == null) return;
            const r = await crystal.backend.api('POST', '/api/workspaces/' + encodeURIComponent(w.name), { path: np });
            if (!r.ok) { say('Update failed: ' + (r.data && r.data.error || JSON.stringify(r))); return; }
            say('Updated “' + w.name + '”.');
            refresh();
          } }, 'Edit path'),
          h('button', { class: 'b', type: 'button', onclick: async () => {
            const ok = confirm(`Remove workspace “${w.name}”?`);
            if (!ok) return;
            const r = await crystal.backend.api('DELETE', '/api/workspaces/' + encodeURIComponent(w.name));
            if (!r.ok) { say('Remove failed: ' + (r.data && r.data.error || JSON.stringify(r))); return; }
            say('Removed “' + w.name + '”.');
            refresh();
          } }, 'Remove'))
      );
      ul.append(row);
    }
    box.append(ul);

    // Add workspace form
    const addBox = h('div', { style: 'border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:14px;background: var(--panel);' });
    addBox.append(h('b', { style: 'display:block;margin-bottom:8px;' }, 'Add workspace'));
    const nameI = h('input', { type: 'text', placeholder: 'Name (e.g. notes)', style: 'width: min(260px,100%);' });
    const pathI = h('input', { type: 'text', placeholder: 'Folder path', style: 'flex:1;min-width:0;' });
    const browse = h('button', { class: 'b', type: 'button', onclick: async () => {
      const p = await crystal.app.chooseFolder();
      if (p) pathI.value = p;
    } }, 'Browse…');
    const permRow = h('div', { style: 'display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap;' });
    const permInputs = {};
    for (const p of ['read', 'write', 'delete', 'exec']) {
      const cb = h('input', { type: 'checkbox' });
      cb.checked = true;
      permRow.append(h('label', { class: 'sw' }, cb, h('span', {}, p)));
      permInputs[p] = cb;
    }
    permRow.append(h('span', { style: 'color: var(--mute); font-size: 12px; margin-left: 8px;' }, 'permissions (unchecked = restricted)'));
    const addBtn = h('button', { class: 'b pri', type: 'button', onclick: async () => {
      const name = nameI.value.trim();
      const path = pathI.value.trim();
      if (!name || !path) { say('Name and path are required.'); return; }
      const perms = {};
      for (const p of ['read', 'write', 'delete', 'exec']) perms[p] = permInputs[p].checked;
      const r = await crystal.backend.api('POST', '/api/workspaces', { name, path, permissions: perms });
      if (!r.ok) { say('Add failed: ' + (r.data && r.data.error || JSON.stringify(r))); return; }
      say('Added “' + name + '”.');
      nameI.value = ''; pathI.value = '';
      refresh();
    } }, 'Add');
    addBox.append(h('div', { style: 'display:flex;gap:8px;align-items:flex-start;' }, nameI, h('div', { style: 'display:flex;gap:8px;' }, pathI, browse)), permRow, addBtn);
    box.append(addBox);
  };

  await refresh();
}

(async function boot() {
  schema = await crystal.settings.schema(); values = await crystal.settings.all();
  for (const s of schema.sections) for (const f of s.fields) defaults[f.key] = f.default;
  const r = await crystal.backend.api('GET', '/api/models'); modelNames = (r.data && r.data.llm_models) || [];
  crystal.backend.onState(async info => { if (info.state === 'ready') { const m = await crystal.backend.api('GET', '/api/models'); modelNames = (m.data && m.data.llm_models) || []; } });
  $('search').addEventListener('input', render);
  render();
})();
