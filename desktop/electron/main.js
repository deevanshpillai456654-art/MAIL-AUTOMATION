
const { app, BrowserWindow, ipcMain, shell, crashReporter } = require('electron');
const path = require('path');

const LOCAL_DASHBOARD_URL = process.env.AIO_DASHBOARD_URL || 'http://127.0.0.1:4597/dashboard';
const ALLOWED_APP_ORIGINS = new Set(['http://127.0.0.1:4597', 'http://localhost:4597']);
try { ALLOWED_APP_ORIGINS.add(new URL(LOCAL_DASHBOARD_URL).origin); } catch {}
const ALLOWED_IPC = new Set(['runtime:getStatus', 'runtime:openExternal']);
const ALLOWED_EXTERNAL_PROTOCOLS = new Set(['https:', 'mailto:']);

crashReporter.start({ submitURL: '', uploadToServer: false, compress: true });

function isAllowedAppUrl(value) {
  try {
    const url = new URL(value);
    return ALLOWED_APP_ORIGINS.has(url.origin);
  } catch {
    return false;
  }
}

function isAllowedExternalUrl(value) {
  try {
    const url = new URL(value);
    return ALLOWED_EXTERNAL_PROTOCOLS.has(url.protocol);
  } catch {
    return false;
  }
}

function assertIpc(event, channel) {
  if (!ALLOWED_IPC.has(channel)) throw new Error('Forbidden IPC channel');
  const frameUrl = event.senderFrame && event.senderFrame.url;
  if (!frameUrl || !isAllowedAppUrl(frameUrl)) throw new Error('Forbidden IPC origin');
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 1024,
    minHeight: 720,
    show: false,
    backgroundColor: '#070b14',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      enableRemoteModule: false,
      devTools: process.env.AIO_DESKTOP_DEVTOOLS === '1'
    }
  });

  win.once('ready-to-show', () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedAppUrl(url)) {
      event.preventDefault();
      if (isAllowedExternalUrl(url)) shell.openExternal(url);
    }
  });
  win.webContents.on('before-input-event', (event, input) => {
    if (input.control && input.shift && input.key && input.key.toLowerCase() === 'i' && process.env.AIO_DESKTOP_DEVTOOLS !== '1') {
      event.preventDefault();
    }
  });
  win.webContents.session.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(['notifications'].includes(permission));
  });

  if (!isAllowedAppUrl(LOCAL_DASHBOARD_URL)) throw new Error('Dashboard URL is not allowlisted');
  win.loadURL(LOCAL_DASHBOARD_URL);
  return win;
}

ipcMain.handle('runtime:getStatus', event => {
  assertIpc(event, 'runtime:getStatus');
  return { ok: true, sandboxed: true, contextIsolation: true, nodeIntegration: false, version: app.getVersion() };
});

ipcMain.handle('runtime:openExternal', (event, url) => {
  assertIpc(event, 'runtime:openExternal');
  const target = String(url || '');
  if (!isAllowedExternalUrl(target)) throw new Error('Blocked URL');
  return shell.openExternal(target);
});

app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', event => event.preventDefault());
});
app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
process.on('uncaughtException', error => console.error('Desktop runtime error:', error && error.message));
process.on('unhandledRejection', reason => console.error('Desktop unhandled rejection:', reason && reason.message || reason));
