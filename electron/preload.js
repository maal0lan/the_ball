'use strict';
// The ONLY bridge between web pages and Node. Pages never get require().
const { contextBridge, ipcRenderer } = require('electron');
const invoke = (ch, ...a) => ipcRenderer.invoke(ch, ...a);
const on = (ch, cb) => { const h = (_e, ...a) => cb(...a); ipcRenderer.on(ch, h); return () => ipcRenderer.removeListener(ch, h); };

contextBridge.exposeInMainWorld('crystal', {
  settings: {
    schema: () => invoke('settings:schema'),
    all: () => invoke('settings:all'),
    set: patch => invoke('settings:set', patch),
    reset: keys => invoke('settings:reset', keys),
    exportJson: () => invoke('settings:export'),
    importJson: () => invoke('settings:import'),
    onChange: cb => on('settings:changed', cb),
  },
  backend: {
    info: () => invoke('backend:info'),
    api: (method, path, body) => invoke('backend:api', { method, path, body }),
    transcribe: (pcm, language) => invoke('backend:transcribe', pcm, language),
    restart: () => invoke('backend:restart'),
    onState: cb => on('backend:state', cb),
  },
  win: {
    ignoreMouse: ignore => ipcRenderer.send('win:ignore-mouse', ignore),
    dragStart: () => ipcRenderer.send('win:drag-start'),
    dragMove: (dx, dy) => ipcRenderer.send('win:drag-move', dx, dy),
    dragEnd: () => ipcRenderer.send('win:drag-end'),
    contextMenu: () => ipcRenderer.send('win:context-menu'),
    hideBall: () => ipcRenderer.send('win:hide-ball'),
    openSettings: () => invoke('app:open-settings'),
    openConsole: () => invoke('app:open-console'),
    onToggleChat: cb => on('ui:toggle-chat', cb),
    onNewChat: cb => on('ui:new-chat', cb),
    onMute: cb => on('ui:mute', cb),
  },
  capture: {
    info: () => invoke('capture:info'),
    onDisplayChanged: cb => on('capture:display-changed', cb),
  },
  log: {
    history: () => invoke('log:history'),
    push: (level, source, message) => ipcRenderer.send('log:push', level, source, message),
    onEntry: cb => on('log:entry', cb),
    onCleared: cb => on('log:cleared', cb),
    clear: () => invoke('log:clear'),
    openFile: () => invoke('log:open-file'),
    counts: () => invoke('log:counts'),
  },
  app: {
    chooseFolder: () => invoke('dialog:choose-folder'),
    openDataFolder: () => invoke('app:open-data'),
    version: () => invoke('app:version'),
    quit: () => ipcRenderer.send('app:quit'),
  },
});
