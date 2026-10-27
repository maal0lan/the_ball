'use strict';
// Flat key/value settings persisted to settings.json, validated against shared/settings-schema.json.
const fs = require('fs');
const path = require('path');

class SettingsStore {
  constructor(file, schema) {
    this.file = file;
    this.schema = schema;
    this.fields = new Map();
    for (const s of schema.sections) for (const f of s.fields) this.fields.set(f.key, f);
    this.values = {};
    this.hidden = {}; // keys starting with "_" (window position etc.), not in the schema
    this.load();
  }

  defaults() { const o = {}; for (const [k, f] of this.fields) o[k] = f.default; return o; }

  load() {
    let saved = {};
    try { saved = JSON.parse(fs.readFileSync(this.file, 'utf8')); } catch (e) {
      if (e.code !== 'ENOENT') throw new Error(`settings.json is corrupt (${e.message}). Fix or delete ${this.file}`);
    }
    this.values = this.defaults();
    for (const [k, v] of Object.entries(saved)) {
      if (k.startsWith('_')) this.hidden[k] = v;
      else if (this.fields.has(k)) this.values[k] = this.coerce(this.fields.get(k), v);
    }
  }

  coerce(f, v) {
    switch (f.type) {
      case 'bool': return !!v;
      case 'number': {
        let n = Number(v); if (!Number.isFinite(n)) n = f.default;
        if (f.min != null) n = Math.max(f.min, n);
        if (f.max != null) n = Math.min(f.max, n);
        return n;
      }
      case 'select': return f.options.includes(v) ? v : f.default;
      default: return v == null ? '' : String(v);
    }
  }

  all() { return { ...this.values }; }
  get(k) { return this.values[k]; }
  getHidden(k) { return this.hidden[k]; }
  setHidden(k, v) { this.hidden[k] = v; this.save(); }

  /** Apply a patch; returns the list of keys whose value actually changed. */
  set(patch) {
    const changed = [];
    for (const [k, v] of Object.entries(patch)) {
      const f = this.fields.get(k);
      if (!f) continue;
      const nv = this.coerce(f, v);
      if (this.values[k] !== nv) { this.values[k] = nv; changed.push(k); }
    }
    if (changed.length) this.save();
    return changed;
  }

  reset(keys) {
    const d = this.defaults();
    return this.set(Object.fromEntries((keys && keys.length ? keys : [...this.fields.keys()]).map(k => [k, d[k]])));
  }

  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = this.file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify({ ...this.values, ...this.hidden }, null, 2));
    fs.renameSync(tmp, this.file);
  }
}

module.exports = { SettingsStore };
