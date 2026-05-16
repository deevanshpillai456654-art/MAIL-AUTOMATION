const { contextBridge, ipcRenderer } = require('electron');

const ALLOWED_CHANNELS = new Set(['runtime:getStatus', 'runtime:openExternal']);
function invoke(channel, ...args) {
  if (!ALLOWED_CHANNELS.has(channel)) throw new Error('Blocked IPC channel');
  return ipcRenderer.invoke(channel, ...args);
}

contextBridge.exposeInMainWorld('AIEmailOrganizerDesktop', Object.freeze({
  getRuntimeStatus: () => invoke('runtime:getStatus'),
  openExternal: url => invoke('runtime:openExternal', String(url || ''))
}));
