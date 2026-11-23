/* The desktop shell.
 *
 * The app is already a local HTTP server plus a static frontend, which is
 * exactly the shape Electron wraps well: this file starts the server, waits
 * for it, and points a window at it. No application logic lives here, and
 * nothing in web/ knows it is running inside a window.
 *
 * Four things it exists to get right:
 *
 *   - A free port, asked for at launch. A fixed one collides with the uvicorn
 *     the developer already has on 8321, and the collision looks like the app
 *     opening somebody else's data.
 *   - Node without installing Node. pi-models.mjs needs a Node runtime, and
 *     Electron is one; AHA_NODE plus ELECTRON_RUN_AS_NODE hands the child our
 *     own binary, so that prerequisite disappears.
 *   - The server dying with the window. An orphaned uvicorn holding the port
 *     and a job thread is the standard way this goes wrong.
 *   - Saying why, when it fails. A window that never loads tells the user
 *     nothing; the server's own stderr tells them everything.
 */
const { app, BrowserWindow, Menu, dialog, shell } = require('electron');
const { spawn } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
const fs = require('node:fs');

const ROOT = path.join(__dirname, '..');
const BOOT_TIMEOUT_MS = 30_000;

let server = null;
let window_ = null;

/** A port the OS says is free right now. */
function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.on('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

/** The interpreter that has the dependencies. A packaged build ships its own. */
function python() {
  const candidates = [
    process.env.AHA_PYTHON,
    path.join(process.resourcesPath || '', 'python', 'bin', 'python3'),
    path.join(ROOT, '.venv', 'bin', 'python3'),
    path.join(ROOT, '..', 'ahafrog-xhs-yuqihang', '.venv', 'bin', 'python3'),
  ].filter(Boolean);
  return candidates.find((p) => fs.existsSync(p)) || 'python3';
}

/** Where the user's papers, .env and credentials go.
 *
 *  Packaged: the platform's application-data directory. It cannot be the app
 *  bundle — that is read-only, and on macOS writing inside a signed bundle
 *  invalidates the signature, so the first saved setting would break the app's
 *  own code signature.
 *
 *  From a checkout: the checkout, so a developer's existing data/ and .env are
 *  the ones they see. */
function stateDir() {
  return app.isPackaged ? app.getPath('userData') : ROOT;
}

function startServer(port) {
  const bundledBin = path.join(process.resourcesPath || '', 'bin');
  const state = stateDir();
  const env = {
    ...process.env,
    PORT: String(port),
    AHA_STATE_DIR: state,
    PI_CREDENTIAL_FILE: path.join(state, '.runtime', 'credentials.json'),
    // Electron is a Node runtime. Handing the child our own binary is what
    // removes "install Node" from the user's list.
    AHA_NODE: process.execPath,
    ELECTRON_RUN_AS_NODE: '1',
    ...(fs.existsSync(bundledBin) ? { AHA_BIN_DIR: bundledBin } : {}),
  };
  const child = spawn(python(), ['-m', 'uvicorn', 'app.main:app',
                                 '--host', '127.0.0.1', '--port', String(port)],
                      { cwd: ROOT, env });
  child.stdout.on('data', (b) => process.stdout.write(`[server] ${b}`));
  child.stderr.on('data', (b) => process.stderr.write(`[server] ${b}`));
  return child;
}

/** Resolves once /api/ping answers. That endpoint is open even when the access
 *  password is set, which is the reason it exists. */
async function waitForServer(port, deadline) {
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/ping`);
      if (response.ok) return true;
    } catch {
      /* not listening yet */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    show: false,
    // A normal title bar. 'hiddenInset' looks better but draws the traffic
    // lights over the sidebar's own brand mark at the top left, and moving that
    // out of the way means the web page has to know it is in a window.
    backgroundColor: '#ffffff',
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  // The page is ours, but any link it carries to somewhere else belongs in the
  // user's own browser, not in a window with no address bar to check.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  return win;
}

/** A packaged app hides the user's files somewhere they would never guess, so
 *  there has to be a way to open that folder. The Edit roles are not optional:
 *  replacing the default menu without them takes away Cmd+C and Cmd+V. */
function buildMenu() {
  const openData = {
    label: '打开数据文件夹 · Open data folder',
    click: () => shell.openPath(path.join(stateDir(), 'data')),
  };
  const template = [
    ...(process.platform === 'darwin'
      ? [{ label: app.name, submenu: [{ role: 'about' }, { type: 'separator' }, openData,
                                      { type: 'separator' }, { role: 'quit' }] }]
      : [{ label: 'File', submenu: [openData, { type: 'separator' }, { role: 'quit' }] }]),
    { label: 'Edit',
      submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' },
                { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: 'View',
      submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' },
                { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
                { type: 'separator' }, { role: 'togglefullscreen' }] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function boot() {
  buildMenu();
  const port = await freePort();
  server = startServer(port);

  let died = null;
  server.on('exit', (code) => {
    const quitting = app.isQuitting === true;
    if (!quitting) died = code;
  });

  window_ = createWindow();
  await window_.loadURL(
    'data:text/html;charset=utf-8,' +
      encodeURIComponent(`<body style="margin:0;display:grid;place-items:center;height:100vh;
        font:14px ui-sans-serif,system-ui;color:#71717a;background:#fff">正在启动… · starting</body>`),
  );
  window_.show();

  const up = await waitForServer(port, Date.now() + BOOT_TIMEOUT_MS);
  if (!up) {
    dialog.showErrorBox(
      '启动失败 · could not start',
      died !== null
        ? `服务进程退出，代码 ${died}。\nThe server exited with code ${died}. See the terminal for its output.`
        : `服务在 ${BOOT_TIMEOUT_MS / 1000} 秒内没有就绪。\nThe server did not come up in time.`,
    );
    app.quit();
    return;
  }
  await window_.loadURL(`http://127.0.0.1:${port}/`);
  console.log(`[shell] window loaded http://127.0.0.1:${port}/`);

  // Smoke check: start, render, save a PNG of the window, quit. Booting a server
  // proves nothing about whether the shell actually painted the app.
  //   AHA_DESKTOP_SMOKE=/tmp/shot.png npm run desktop
  const shot = process.env.AHA_DESKTOP_SMOKE;
  if (shot) {
    await new Promise((r) => setTimeout(r, 2500));
    fs.writeFileSync(shot, (await window_.webContents.capturePage()).toPNG());
    console.log(`[shell] smoke shot -> ${shot}`);
    app.quit();
  }
}

app.whenReady().then(boot);

app.on('before-quit', () => {
  app.isQuitting = true;
  if (server && server.exitCode === null) server.kill('SIGTERM');
});

app.on('window-all-closed', () => app.quit());

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) boot();
});
