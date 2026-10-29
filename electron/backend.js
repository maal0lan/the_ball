'use strict';
// Starts, watches and talks to the Python backend.
const { spawn, spawnSync } = require('child_process');
const { EventEmitter } = require('events');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const path = require('path');
const log = require('./logger');

const LOG_RE = /^\d\d:\d\d:\d\d \[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\] /;

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

class BackendManager extends EventEmitter {
  constructor({ root, dataDir, settings }) {
    super();
    this.root = root;
    this.dataDir = dataDir;
    this.settings = settings;
    this.proc = null;
    this.port = 0;
    this.token = '';
    this.state = 'stopped'; // stopped | starting | ready | crashed
    this.stopping = false;
    this.restartTimer = null;
  }

  info() { return { state: this.state, port: this.port, token: this.token }; }
  setState(s, detail) { this.state = s; log.info('backend', `state -> ${s}${detail ? ' (' + detail + ')' : ''}`); this.emit('state', this.info()); }

  findPython() {
    const custom = this.settings.get('backend.pythonPath');
    if (custom) return { cmd: custom, args: [] };
    const win = process.platform === 'win32';
    const venv = path.join(this.root, 'backend', '.venv', win ? 'Scripts' : 'bin', win ? 'python.exe' : 'python');
    if (fs.existsSync(venv)) return { cmd: venv, args: [] };
    const cands = win ? [['py', ['-3']], ['python', []]] : [['python3', []], ['python', []]];
    for (const [cmd, pre] of cands) {
      const r = spawnSync(cmd, [...pre, '--version'], { encoding: 'utf8' });
      if (r.status === 0) { log.warn('backend', `No backend/.venv found; using system ${cmd}. Run scripts/setup first for a clean install.`); return { cmd, args: pre }; }
    }
    return null;
  }

  async start() {
    if (this.proc) return;
    this.stopping = false;
    const py = this.findPython();
    if (!py) {
      log.error('backend', 'Python 3.11+ was not found. Install it, then run scripts/setup.ps1 (Windows) or scripts/setup.sh.');
      this.setState('crashed', 'python missing');
      return;
    }
    this.port = Number(this.settings.get('backend.port')) || await freePort();
    this.token = crypto.randomBytes(16).toString('hex');
    const dataDir = this.settings.get('backend.dataDir') || this.dataDir;
    const env = {
      ...process.env,
      CRYSTAL_TOKEN: this.token,
      CRYSTAL_SCHEMA: path.join(this.root, 'shared', 'settings-schema.json'),
      CRYSTAL_DATA_DIR: dataDir,
      CRYSTAL_LOG_LEVEL: 'DEBUG',
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    };
    const hf = this.settings.get('voice.hfToken');
    if (hf) env.HF_TOKEN = hf;
    const args = [...py.args, path.join(this.root, 'backend', 'server.py'), '--port', String(this.port), '--data-dir', dataDir];
    log.info('backend', `spawn: ${py.cmd} ${args.join(' ')}`);
    this.setState('starting');
    const p = spawn(py.cmd, args, { cwd: path.join(this.root, 'backend'), env, windowsHide: true });
    this.proc = p;

    let lastLevel = 'info';
    const feed = (stream, isErr) => {
      let buf = '';
      stream.setEncoding('utf8');
      stream.on('data', chunk => {
        buf += chunk;
        const lines = buf.split(/\r?\n/); buf = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const m = LOG_RE.exec(line);
          if (m) { lastLevel = { WARNING: 'warn', CRITICAL: 'error' }[m[1]] || m[1].toLowerCase(); log.add(lastLevel, 'backend', line.slice(m[0].length)); }
          else log.add(isErr ? 'error' : lastLevel, isErr ? 'backend:stderr' : 'backend', line);
        }
      });
    };
    feed(p.stdout, false); feed(p.stderr, true);
    p.on('error', e => log.error('backend', `Failed to launch Python: ${e.message}`));
    p.on('exit', (code, sig) => {
      this.proc = null;
      if (this.stopping) { this.setState('stopped'); return; }
      log.error('backend', `Backend exited unexpectedly (code=${code} signal=${sig}). Scroll up for the Python error.`);
      this.setState('crashed', `exit ${code}`);
      if (this.settings.get('backend.autoRestart')) {
        const d = Number(this.settings.get('backend.restartDelay')) * 1000;
        log.info('backend', `restarting in ${d / 1000}s`);
        this.restartTimer = setTimeout(() => this.start(), d);
      }
    });

    const deadline = Date.now() + Number(this.settings.get('backend.startTimeout')) * 1000;
    while (Date.now() < deadline && this.proc === p) {
      try {
        const r = await fetch(`http://127.0.0.1:${this.port}/health`);
        if (r.ok) { this.setState('ready'); return; }
      } catch (_) { /* not up yet */ }
      await new Promise(r => setTimeout(r, 400));
    }
    if (this.proc === p && this.state === 'starting') {
      log.error('backend', 'Backend did not become healthy before the startup timeout. Missing Python packages? Run scripts/setup.');
      this.setState('crashed', 'timeout');
    }
  }

  async stop() {
    this.stopping = true;
    clearTimeout(this.restartTimer);
    const p = this.proc;
    if (!p) return;
    if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(p.pid), '/T', '/F']);
    else p.kill('SIGTERM');
    await new Promise(r => { const t = setTimeout(r, 2000); p.once('exit', () => { clearTimeout(t); r(); }); });
    this.proc = null;
  }

  async restart() { await this.stop(); this.stopping = false; return this.start(); }

  async transcribe(pcm, language) {
    if (this.state !== 'ready') throw new Error(`Backend is ${this.state}`);
    const response = await fetch(`http://127.0.0.1:${this.port}/api/stt`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/octet-stream', 'X-Speech-Language': language },
      body: Uint8Array.from(pcm),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Speech transcription failed (${response.status})`);
    return data.text || '';
  }

  async request(method, apiPath, body) {
    if (this.state !== 'ready') return { ok: false, status: 0, data: { error: `Backend is ${this.state}` } };
    try {
      const r = await fetch(`http://127.0.0.1:${this.port}${apiPath}`, {
        method,
        headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let data = null; try { data = await r.json(); } catch (_) { /* no body */ }
      return { ok: r.ok, status: r.status, data };
    } catch (e) {
      log.error('backend', `request ${method} ${apiPath} failed: ${e.message}`);
      return { ok: false, status: 0, data: { error: e.message } };
    }
  }
}

module.exports = { BackendManager };
