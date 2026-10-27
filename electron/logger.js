'use strict';
// Central log: ring buffer + file + live feed to the debug console window.
const fs = require('fs');
const path = require('path');

const RANK = { debug: 10, info: 20, warn: 30, error: 40 };

class Logger {
  constructor() {
    this.buffer = [];
    this.max = 5000;
    this.minLevel = 'debug';
    this.listeners = new Set();
    this.counts = { debug: 0, info: 0, warn: 0, error: 0 };
    this.stream = null;
    this.file = null;
    this.nextId = 1;
  }

  init(dir, { minLevel = 'debug', max = 5000, toFile = true } = {}) {
    this.minLevel = minLevel;
    this.max = max;
    if (toFile) {
      fs.mkdirSync(dir, { recursive: true });
      this.file = path.join(dir, `crystal-${new Date().toISOString().slice(0, 10)}.log`);
      this.stream = fs.createWriteStream(this.file, { flags: 'a' });
    }
  }

  configure(opts) {
    if (opts.minLevel) this.minLevel = opts.minLevel;
    if (opts.max) this.max = opts.max;
  }

  onEntry(cb) { this.listeners.add(cb); return () => this.listeners.delete(cb); }

  add(level, source, message) {
    if (!RANK[level]) level = 'info';
    if (RANK[level] < RANK[this.minLevel]) return null;
    const entry = { id: this.nextId++, ts: Date.now(), level, source, message: String(message) };
    this.counts[level]++;
    this.buffer.push(entry);
    if (this.buffer.length > this.max) this.buffer.splice(0, this.buffer.length - this.max);
    if (this.stream) {
      const t = new Date(entry.ts).toISOString();
      this.stream.write(`${t} [${level.toUpperCase()}] ${source}: ${entry.message}\n`);
    }
    const line = `[${level}] ${source}: ${entry.message}`;
    (level === 'error' ? console.error : console.log)(line);
    for (const cb of this.listeners) { try { cb(entry); } catch (_) { /* ignore */ } }
    return entry;
  }

  clear() { this.buffer = []; this.counts = { debug: 0, info: 0, warn: 0, error: 0 }; }
}

const L = new Logger();
for (const lvl of ['debug', 'info', 'warn', 'error']) L[lvl] = (source, msg) => L.add(lvl, source, msg);
module.exports = L;
