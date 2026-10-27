'use strict';
const $ = id => document.getElementById(id);
const RANK = { debug: 10, info: 20, warn: 30, error: 40 };
let entries = [], paused = false, queued = [], sources = new Set(), logFile = null;
const view = $('log');

const on = { debug: true, info: true, warn: true, error: true };
function visible(e) { return on[e.level] && (!$('src').value || e.source === $('src').value) && (!$('q').value || (e.source + ' ' + e.message).toLowerCase().includes($('q').value.toLowerCase())); }
function row(e) {
  const d = document.createElement('div'); d.className = 'ln ' + e.level; d.dataset.id = e.id;
  const t = new Date(e.ts), pad = n => String(n).padStart(2, '0');
  for (const [cls, txt] of [['ts', `${pad(t.getHours())}:${pad(t.getMinutes())}:${pad(t.getSeconds())}.${String(t.getMilliseconds()).padStart(3, '0')}`], ['lv', e.level.toUpperCase()], ['src', e.source], ['msg', e.message]]) {
    const s = document.createElement('span'); s.className = cls; s.textContent = txt; d.appendChild(s);
  }
  return d;
}
function addSource(s) { if (!sources.has(s)) { sources.add(s); const o = document.createElement('option'); o.value = o.textContent = s; $('src').appendChild(o); } }
function atBottom() { return view.scrollHeight - view.scrollTop - view.clientHeight < 40; }
function push(e) {
  entries.push(e); addSource(e.source); bump(e);
  if (!visible(e)) return;
  const stick = atBottom(); view.appendChild(row(e));
  if (view.children.length > 8000) view.firstChild.remove();
  if (stick) view.scrollTop = view.scrollHeight;
}
function rebuild() { view.textContent = ''; const f = document.createDocumentFragment(); for (const e of entries) if (visible(e)) f.appendChild(row(e)); view.appendChild(f); view.scrollTop = view.scrollHeight; }
let cnt = { debug: 0, info: 0, warn: 0, error: 0 };
function counts() { cnt = { debug: 0, info: 0, warn: 0, error: 0 }; for (const e of entries) cnt[e.level]++; for (const l in cnt) $('c-' + l).textContent = cnt[l]; }
function bump(e) { cnt[e.level]++; $('c-' + e.level).textContent = cnt[e.level]; }

document.querySelectorAll('[data-lv]').forEach(c => c.onchange = () => { on[c.dataset.lv] = c.checked; rebuild(); });
$('src').onchange = rebuild; $('q').oninput = rebuild;
$('errOnly').onclick = () => { const only = !$('errOnly').classList.contains('on'); $('errOnly').classList.toggle('on', only);
  document.querySelectorAll('[data-lv]').forEach(c => { c.checked = only ? c.dataset.lv === 'error' : true; on[c.dataset.lv] = c.checked; }); rebuild(); };
$('pause').onclick = () => { paused = !paused; $('pause').classList.toggle('on', paused); $('pause').textContent = paused ? 'Resume' : 'Pause'; if (!paused) { queued.forEach(push); queued = []; } };
$('clear').onclick = () => crystal.log.clear();
$('open').onclick = () => crystal.log.openFile();
$('copy').onclick = async () => { const t = entries.filter(visible).map(e => `${new Date(e.ts).toISOString()} [${e.level.toUpperCase()}] ${e.source}: ${e.message}`).join('\n'); await navigator.clipboard.writeText(t); $('copy').textContent = 'Copied!'; setTimeout(() => $('copy').textContent = 'Copy visible', 1200); };

function pill(info) { $('pill').textContent = `backend: ${info.state}${info.port ? ' :' + info.port : ''}`; $('pill').className = info.state; }
crystal.backend.onState(pill);
crystal.log.onEntry(e => paused ? queued.push(e) : push(e));
crystal.log.onCleared(() => { entries = []; queued = []; view.textContent = ''; counts(); });
window.addEventListener('error', e => console.error(`Uncaught in console window: ${e.message}`));

(async () => { const h = await crystal.log.history(); entries = []; h.entries.forEach(e => { entries.push(e); addSource(e.source); }); logFile = h.file; counts(); rebuild(); pill(await crystal.backend.info()); })();
