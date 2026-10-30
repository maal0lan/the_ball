'use strict';
const { app, BrowserWindow, Tray, Menu, ipcMain, screen, globalShortcut, dialog, desktopCapturer,
        shell, nativeImage, systemPreferences, session } = require('electron');
const fs = require('fs');
const path = require('path');
const log = require('./logger');
const { SettingsStore } = require('./settings-store');
const { BackendManager } = require('./backend');

const ROOT = app.isPackaged ? process.resourcesPath : path.join(__dirname, '..');
const APP_ROOT = path.join(__dirname, '..');
const PRELOAD = path.join(__dirname, 'preload.js');
const PAD = 28;        // transparent margin around the ball (aura + shadow)
const CHAT_GAP = 6;    // space between ball and dialogue box
const IS_LINUX = process.platform === 'linux';

let store, backend, tray;
let ballWin = null, settingsWin = null, consoleWin = null;
// Resolves once the ball is really visible and hidden from screen capture.
let ballShownResolve;
const ballShown = new Promise(r => { ballShownResolve = r; });
let quitting = false, dragStart = null, lastDisplayId = null, moveTimer = null, captureNotifyTimer = null;
function notifyCaptureChanged() {
  clearTimeout(captureNotifyTimer);
  captureNotifyTimer = setTimeout(() => {
    if (ballWin && !ballWin.isDestroyed()) ballWin.webContents.send('capture:display-changed');
  }, 400);
}

// ---------------------------------------------------------------- launch sequencer
app.whenReady().then(async () => {
  const userData = app.getPath('userData');
  const schema = JSON.parse(fs.readFileSync(path.join(ROOT, 'shared', 'settings-schema.json'), 'utf8'));
  try { store = new SettingsStore(path.join(userData, 'settings.json'), schema); }
  catch (e) { dialog.showErrorBox('Crystal: settings error', e.message); app.quit(); return; }

  log.init(path.join(userData, 'logs'), { minLevel: S('debug.logLevel'), max: S('debug.maxLogEntries'), toFile: S('debug.logToFile') });
  log.onEntry(e => broadcast('log:entry', e));
  log.info('main', `Crystal ${app.getVersion()} · Electron ${process.versions.electron} · ${process.platform} · data: ${userData}`);

  backend = new BackendManager({ root: ROOT, dataDir: userData, settings: store });
  backend.on('state', info => {
    broadcast('backend:state', info);
    if (info.state === 'ready') pushSettingsToBackend();
  });
  setupIpc();
  Menu.setApplicationMenu(null);
  createBall();
  buildTray();
  registerHotkey();
  app.setLoginItemSettings({ openAtLogin: S('behavior.startWithSystem') });
  screen.on('display-metrics-changed', notifyCaptureChanged);
  if (S('debug.showConsoleOnStart')) openSingleton('console');
  backend.start();
  if (process.env.CRYSTAL_SELFTEST) require('./selftest')({ BrowserWindow, ballWin, log, openWindow: openSingleton });
});

// ---------------------------------------------------------------- crash visibility
process.on('uncaughtException', e => log.error('main', `uncaughtException: ${e.stack || e}`));
process.on('unhandledRejection', e => log.error('main', `unhandledRejection: ${e && e.stack || e}`));

if (!app.requestSingleInstanceLock()) { app.quit(); }
app.on('second-instance', () => showBall(true));

// ---------------------------------------------------------------- helpers
const S = k => store.get(k);
function broadcast(channel, ...args) {
  for (const w of [ballWin, settingsWin, consoleWin]) if (w && !w.isDestroyed()) w.webContents.send(channel, ...args);
}
function wireWebContents(win, name) {
  const wc = win.webContents;
  wc.on('console-message', (_e, level, message, line, sourceId) => {
    const lvl = ['debug', 'info', 'warn', 'error'][level] || 'info';
    const where = sourceId ? ` (${path.basename(sourceId)}:${line})` : '';
    log.add(lvl, `ui:${name}`, message + (lvl === 'error' || lvl === 'warn' ? where : ''));
  });
  wc.on('render-process-gone', (_e, d) => log.error(`ui:${name}`, `renderer process gone: ${d.reason} (exit ${d.exitCode})`));
  wc.on('did-fail-load', (_e, code, desc, url) => log.error(`ui:${name}`, `failed to load ${url}: ${desc} (${code})`));
  wc.on('preload-error', (_e, p, err) => log.error(`ui:${name}`, `preload error in ${p}: ${err}`));
  win.on('unresponsive', () => log.warn(`ui:${name}`, 'window is unresponsive'));
  wc.on('before-input-event', (_e, i) => { if (i.type === 'keyDown' && (i.key === 'F12' || (i.control && i.shift && i.key.toLowerCase() === 'i'))) wc.toggleDevTools(); });
}

// ---------------------------------------------------------------- ball window
function ballSize() {
  const D = S('appearance.ballSize');
  const stage = D + PAD * 2;
  return { w: Math.max(stage, S('chat.width') + 32), h: stage + CHAT_GAP + S('chat.height') + 16 };
}

function defaultPosition(w) {
  const wa = screen.getPrimaryDisplay().workArea;
  return { x: wa.x + wa.width - w - 60, y: wa.y + 80 };
}

function validPosition(x, y, w, h) {
  return screen.getAllDisplays().some(d => {
    const b = d.workArea; return x + w / 2 > b.x && x + w / 2 < b.x + b.width && y + 40 > b.y && y + 40 < b.y + b.height;
  });
}

function createBall() {
  const { w, h } = ballSize();
  let x = S('behavior.rememberPosition') ? store.getHidden('_x') : undefined;
  let y = S('behavior.rememberPosition') ? store.getHidden('_y') : undefined;
  if (x == null || y == null || !validPosition(x, y, w, h)) ({ x, y } = defaultPosition(w));

  ballWin = new BrowserWindow({
    width: w, height: h, x, y,
    transparent: true, frame: false, hasShadow: false, resizable: false, maximizable: false, minimizable: false,
    fullscreenable: false, backgroundColor: '#00000000', show: false, title: 'Crystal',
    skipTaskbar: !S('behavior.showInTaskbar'), alwaysOnTop: S('behavior.alwaysOnTop'),
    webPreferences: { preload: PRELOAD, contextIsolation: true, nodeIntegration: false, sandbox: true,
                      autoplayPolicy: 'no-user-gesture-required', backgroundThrottling: false },
  });
  wireWebContents(ballWin, 'ball');
  applyBallFlags();
  ballWin.loadFile(path.join(APP_ROOT, 'renderer', 'ball.html'));
  ballWin.once('ready-to-show', () => { if (!S('behavior.startHidden')) ballWin.showInactive(); });
  ballWin.once('show', settleGlass);
  ballWin.on('show', () => { if (ballWin && !ballWin.isDestroyed()) ballWin.setContentProtection(!!S('behavior.excludeFromCapture')); });
  ballWin.on('move', onBallMove);
  ballWin.on('close', e => { if (!quitting) { e.preventDefault(); ballWin.hide(); } });
  if (S('debug.devTools')) ballWin.webContents.openDevTools({ mode: 'detach' });
  lastDisplayId = screen.getDisplayMatching(ballWin.getBounds()).id;
  log.info('main', `ball window created ${w}x${h} at ${x},${y}`);
}

function settleGlass() {
  applyBallFlags();
  setTimeout(() => {
    applyBallFlags();
    ballShownResolve();
    log.info('main', 'glass ready: window visible and hidden from screen capture');
    notifyCaptureChanged();
  }, 500);
}

function resetGlass() {
  log.info('main', 'Reset glass requested');
  applyBallFlags();
  notifyCaptureChanged();
}

function applyBallFlags() {
  if (!ballWin || ballWin.isDestroyed()) return;
  ballWin.setAlwaysOnTop(S('behavior.alwaysOnTop'), 'floating');
  ballWin.setSkipTaskbar(!S('behavior.showInTaskbar'));
  // Excluding the window from screen capture is what lets the ball "see" the desktop behind it
  // without seeing itself. Windows 10 2004+ and macOS support it; Linux does not.
  ballWin.setContentProtection(!!S('behavior.excludeFromCapture'));
  if (!S('behavior.clickThrough') || IS_LINUX) ballWin.setIgnoreMouseEvents(false);
  else ballWin.setIgnoreMouseEvents(true, { forward: true });
  if (IS_LINUX && S('behavior.clickThrough')) log.warn('main', 'Click-through is not supported on Linux; transparent corners will block clicks.');
  if (IS_LINUX && S('behavior.captureScreen')) log.warn('main', 'Linux: window cannot hide itself from capture, so refraction may show the ball itself. Disable "Refract the real desktop" if it looks wrong.');
}

function resizeBall() {
  if (!ballWin || ballWin.isDestroyed()) return;
  const { w, h } = ballSize();
  const b = ballWin.getBounds();
  if (b.width === w && b.height === h) return;
  ballWin.setBounds({ x: b.x + Math.round((b.width - w) / 2), y: b.y, width: w, height: h });
}

function showBall(focus) {
  if (!ballWin) return;
  ballWin.show();
  if (focus) ballWin.focus();
}

function toggleChatFromHotkey() {
  if (!ballWin) return;
  if (!ballWin.isVisible()) ballWin.show();
  ballWin.focus();
  ballWin.webContents.send('ui:toggle-chat');
}

function onBallMove() {
  clearTimeout(moveTimer);
  moveTimer = setTimeout(() => {
    if (!ballWin || ballWin.isDestroyed()) return;
    const b = ballWin.getBounds();
    store.setHidden('_x', b.x); store.setHidden('_y', b.y);
    const d = screen.getDisplayMatching(b);
    if (d.id !== lastDisplayId) { lastDisplayId = d.id; log.info('main', `ball moved to display ${d.id}`); notifyCaptureChanged(); }
  }, 250);
}

// ---------------------------------------------------------------- other windows
function openSingleton(kind) {
  const cfg = {
    settings: { file: 'settings.html', title: 'Crystal — Settings', w: 1020, h: 740 },
    console: { file: 'console.html', title: 'Crystal — Debug console', w: 1000, h: 520 },
  }[kind];
  const existing = kind === 'settings' ? settingsWin : consoleWin;
  if (existing && !existing.isDestroyed()) { existing.show(); existing.focus(); return existing; }
  const win = new BrowserWindow({
    width: cfg.w, height: cfg.h, minWidth: 640, minHeight: 400, title: cfg.title, backgroundColor: '#0c1117',
    autoHideMenuBar: true, icon: path.join(APP_ROOT, 'assets', 'icon.png'),
    webPreferences: { preload: PRELOAD, contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.setMenuBarVisibility(false);
  wireWebContents(win, kind);
  win.loadFile(path.join(APP_ROOT, 'renderer', cfg.file));
  win.on('closed', () => { if (kind === 'settings') settingsWin = null; else consoleWin = null; });
  if (kind === 'settings') settingsWin = win; else consoleWin = win;
  return win;
}

// ---------------------------------------------------------------- tray
function buildTray() {
  const img = nativeImage.createFromPath(path.join(APP_ROOT, 'assets', 'tray.png'));
  tray = new Tray(img);
  tray.setToolTip('Crystal');
  const rebuild = () => tray.setContextMenu(Menu.buildFromTemplate(trayTemplate()));
  rebuild();
  tray.on('click', () => { ballWin && (ballWin.isVisible() ? ballWin.hide() : showBall(true)); });
  return rebuild;
}
function trayTemplate() {
  return [
    { label: 'Show / hide ball', click: () => (ballWin.isVisible() ? ballWin.hide() : showBall(true)) },
    { label: 'Toggle dialogue box', click: toggleChatFromHotkey },
    { label: 'New chat', click: () => ballWin && ballWin.webContents.send('ui:new-chat') },
    { label: 'Mute / unmute voice', click: () => ballWin && ballWin.webContents.send('ui:mute') },
    { type: 'separator' },
    { label: 'Settings…', click: () => openSingleton('settings') },
    { label: 'Debug console', click: () => openSingleton('console') },
    { label: 'Reset glass (fixes a white ball)', click: resetGlass },
    { label: 'Restart backend', click: () => backend.restart() },
    { type: 'separator' },
    { label: 'Quit Crystal', click: () => { quitting = true; app.quit(); } },
  ];
}

// ---------------------------------------------------------------- settings application
let hotkeyOk = false;
function registerHotkey() {
  globalShortcut.unregisterAll();
  const acc = S('behavior.hotkey');
  if (!acc) return;
  try {
    hotkeyOk = globalShortcut.register(acc, toggleChatFromHotkey);
    if (!hotkeyOk) log.error('main', `Could not register hotkey "${acc}" (already used by another app?). Change it in Settings → Behavior.`);
    else log.info('main', `hotkey registered: ${acc}`);
  } catch (e) { log.error('main', `Invalid hotkey "${acc}": ${e.message}`); }
}

let pushTimer = null;
function pushSettingsToBackend() {
  if (!backend || backend.state !== 'ready') return;   // the 'ready' event pushes everything anyway
  clearTimeout(pushTimer);
  pushTimer = setTimeout(async () => {
    const r = await backend.request('POST', '/api/settings', store.all());
    if (!r.ok) log.warn('main', `pushing settings to backend failed: ${JSON.stringify(r.data)}`);
  }, 150);
}

function applySettings(changed) {
  const any = prefix => changed.some(k => k.startsWith(prefix));
  log.debug('main', `settings changed: ${changed.join(', ')}`);
  log.configure({ minLevel: S('debug.logLevel'), max: S('debug.maxLogEntries') });
  if (any('appearance.ballSize') || any('chat.width') || any('chat.height')) resizeBall();
  if (any('behavior.')) applyBallFlags();
  if (changed.includes('behavior.hotkey')) registerHotkey();
  if (changed.includes('behavior.startWithSystem')) app.setLoginItemSettings({ openAtLogin: S('behavior.startWithSystem') });
  if (any('backend.') || any('voice.hfToken')) {
    const needs = changed.filter(k => (store.fields.get(k) || {}).apply === 'backend-restart');
    if (needs.length) log.warn('main', `Changed ${needs.join(', ')} — use tray → Restart backend (or Settings → Tools) to apply.`);
  }
  pushSettingsToBackend();
  broadcast('settings:changed', store.all(), changed);
}

// ---------------------------------------------------------------- IPC
let ipcReady = false;
function setupIpc() {
  if (ipcReady) return;
  ipcReady = true;
  session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) => {
  if (permission !== 'media') return callback(false);
  const fromBall = ballWin && !ballWin.isDestroyed() && wc === ballWin.webContents;
  const wantsAudio = (details.mediaTypes || []).includes('audio');
  // audio = mic (only if voice input is on); anything else = the glass screen capture
  callback(!!fromBall && (!wantsAudio || !!S('voice.inputEnabled')));
});
  ipcMain.handle('settings:schema', () => store.schema);
  ipcMain.handle('settings:all', () => store.all());
  ipcMain.handle('settings:set', (_e, patch) => { const c = store.set(patch); if (c.length) applySettings(c); return c; });
  ipcMain.handle('settings:reset', (_e, keys) => { const c = store.reset(keys); if (c.length) applySettings(c); return c; });
  ipcMain.handle('settings:export', async () => {
    const r = await dialog.showSaveDialog(settingsWin, { defaultPath: 'crystal-settings.json', filters: [{ name: 'JSON', extensions: ['json'] }] });
    if (r.canceled) return null;
    fs.writeFileSync(r.filePath, JSON.stringify(store.all(), null, 2)); return r.filePath;
  });
  ipcMain.handle('settings:import', async () => {
    const r = await dialog.showOpenDialog(settingsWin, { properties: ['openFile'], filters: [{ name: 'JSON', extensions: ['json'] }] });
    if (r.canceled) return null;
    const c = store.set(JSON.parse(fs.readFileSync(r.filePaths[0], 'utf8'))); if (c.length) applySettings(c); return c;
  });

  ipcMain.handle('backend:info', () => backend.info());
  ipcMain.handle('backend:api', (_e, { method, path: p, body }) => backend.request(method, p, body));
  ipcMain.handle('backend:transcribe', (_e, pcm, language) => {
    if (!S('voice.inputEnabled') || !(Buffer.isBuffer(pcm) || pcm instanceof Uint8Array || pcm instanceof ArrayBuffer) || pcm.byteLength > 480_000) {
      throw new Error('Voice input is disabled or the audio clip is invalid.');
    }
    return backend.transcribe(Buffer.from(pcm), String(language || 'en-US'));
  });
  ipcMain.handle('backend:restart', () => backend.restart());

  ipcMain.on('win:ignore-mouse', (_e, ignore) => {
    if (!ballWin || ballWin.isDestroyed() || IS_LINUX || !S('behavior.clickThrough')) return;
    ballWin.setIgnoreMouseEvents(!!ignore, { forward: true });
  });
  ipcMain.on('win:drag-start', () => { dragStart = ballWin.getBounds(); });
  ipcMain.on('win:drag-move', (_e, dx, dy) => {
    if (!dragStart) return;
    ballWin.setBounds({ x: Math.round(dragStart.x + dx), y: Math.round(dragStart.y + dy), width: dragStart.width, height: dragStart.height });
  });
  ipcMain.on('win:drag-end', () => { dragStart = null; onBallMove(); });
  ipcMain.on('win:hide-ball', () => ballWin.hide());
  ipcMain.on('win:context-menu', () => Menu.buildFromTemplate(trayTemplate()).popup({ window: ballWin }));
  ipcMain.handle('app:open-settings', () => { openSingleton('settings'); });
  ipcMain.handle('app:open-console', () => { openSingleton('console'); });

  ipcMain.handle('capture:info', async () => {
    await Promise.race([ballShown, new Promise(r => setTimeout(r, 5000))]);
    const b = ballWin.getBounds();
    const disp = screen.getDisplayMatching(b);
    lastDisplayId = disp.id;
    if (process.platform === 'darwin') {
      const st = systemPreferences.getMediaAccessStatus('screen');
      if (st !== 'granted') log.error('main', `macOS screen-recording permission is "${st}". Grant it in System Settings → Privacy & Security → Screen Recording, then restart.`);
    }
    let sources = [];
    try { sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 1, height: 1 } }); }
    catch (e) { log.error('main', `desktopCapturer failed: ${e.message}`); }
    const idx = screen.getAllDisplays().findIndex(d => d.id === disp.id);
    const src = sources.find(s => s.display_id === String(disp.id)) || sources[idx] || sources[0];
    if (!src) log.error('main', 'No screen source available for capture.');
    return {
      sourceId: src ? src.id : null,
      display: { id: disp.id, bounds: disp.bounds, scaleFactor: disp.scaleFactor },
      maxWidth: S('behavior.captureMaxWidth'), fps: S('behavior.captureFps'),
    };
  });

  ipcMain.handle('log:history', () => ({ entries: log.buffer, counts: log.counts, file: log.file }));
  ipcMain.handle('log:counts', () => log.counts);
  ipcMain.handle('log:clear', () => { log.clear(); broadcast('log:cleared'); });
  ipcMain.handle('log:open-file', () => log.file && shell.showItemInFolder(log.file));
  ipcMain.on('log:push', (_e, level, source, message) => log.add(level, source, message));

  ipcMain.handle('dialog:choose-folder', async () => {
    const r = await dialog.showOpenDialog(settingsWin || ballWin, { properties: ['openDirectory', 'createDirectory'] });
    return r.canceled ? null : r.filePaths[0];
  });
  ipcMain.handle('app:open-data', () => shell.openPath(app.getPath('userData')));
  ipcMain.handle('app:version', () => ({ app: app.getVersion(), electron: process.versions.electron, chrome: process.versions.chrome, platform: process.platform }));
  ipcMain.on('app:quit', () => { quitting = true; app.quit(); });
}

// ---------------------------------------------------------------- lifecycle
app.whenReady().then(async () => {
  const userData = app.getPath('userData');
  const schema = JSON.parse(fs.readFileSync(path.join(ROOT, 'shared', 'settings-schema.json'), 'utf8'));
  try { store = new SettingsStore(path.join(userData, 'settings.json'), schema); }
  catch (e) { dialog.showErrorBox('Crystal: settings error', e.message); app.quit(); return; }

  log.init(path.join(userData, 'logs'), { minLevel: S('debug.logLevel'), max: S('debug.maxLogEntries'), toFile: S('debug.logToFile') });
  log.onEntry(e => broadcast('log:entry', e));
  log.info('main', `Crystal ${app.getVersion()} · Electron ${process.versions.electron} · ${process.platform} · data: ${userData}`);

  backend = new BackendManager({ root: ROOT, dataDir: userData, settings: store });
  backend.on('state', info => {
    broadcast('backend:state', info);
    if (info.state === 'ready') pushSettingsToBackend();
  });

  setupIpc();
  Menu.setApplicationMenu(null);
  createBall();
  buildTray();
  registerHotkey();
  app.setLoginItemSettings({ openAtLogin: S('behavior.startWithSystem') });
  screen.on('display-metrics-changed', () => ballWin && ballWin.webContents.send('capture:display-changed'));
  if (S('debug.showConsoleOnStart')) openSingleton('console');
  backend.start();
  if (process.env.CRYSTAL_SELFTEST) require('./selftest')({ BrowserWindow, ballWin, log, openWindow: openSingleton });
});

app.on('window-all-closed', e => { if (!quitting) e.preventDefault(); });
app.on('before-quit', () => { quitting = true; });
app.on('will-quit', async e => {
  globalShortcut.unregisterAll();
  if (backend && backend.proc) { e.preventDefault(); const b = backend; backend = null; await b.stop(); app.exit(0); }
});
