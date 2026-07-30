// Anvil desktop — a window onto the dashboard, plus a nudge when an agent is
// waiting on you.
//
// Why an app and not a bookmark: the dashboard sits behind HTTP basic auth, so
// a browser either prompts on every cold start or you save the password into
// the browser's own store. Here the credentials live in one file this app
// owns, and the same credentials drive a background poll of /api/questions —
// so an agent that needs an email address or a login can actually reach you
// while you're doing something else, instead of the question sitting unseen
// until you happen to open the page.

const { app, BrowserWindow, Notification, Tray, Menu, shell, ipcMain } = require("electron");
const fs = require("fs");
const path = require("path");

const CONFIG = path.join(app.getPath("userData"), "config.json");
const POLL_MS = 60000;

let win = null;
let tray = null;
let lastOpenCount = 0;

function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG, "utf8"));
  } catch {
    return null;
  }
}

function writeConfig(cfg) {
  fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2), { mode: 0o600 });
}

function authHeader(cfg) {
  return "Basic " + Buffer.from(`${cfg.user}:${cfg.password}`).toString("base64");
}

// ---------------------------------------------------------------- first run

function showSetup() {
  win = new BrowserWindow({
    width: 460,
    height: 420,
    title: "Anvil — Setup",
    webPreferences: { nodeIntegration: true, contextIsolation: false },
  });
  win.setMenuBarVisibility(false);
  win.loadFile("setup.html");
}

ipcMain.on("save-config", (_e, cfg) => {
  writeConfig(cfg);
  if (win) win.close();
  openDashboard();
});

// -------------------------------------------------------------- main window

function openDashboard() {
  const cfg = readConfig();
  if (!cfg) return showSetup();

  win = new BrowserWindow({
    width: 1280,
    height: 860,
    title: "Anvil",
    backgroundColor: "#ffffff",
    autoHideMenuBar: true,
  });

  // Electron asks us for credentials instead of showing the OS auth dialog.
  win.webContents.on("login", (event, _details, _authInfo, callback) => {
    event.preventDefault();
    callback(cfg.user, cfg.password);
  });

  // Anything that isn't the dashboard opens in the real browser rather than
  // trapping the user in a chrome-less Electron window with no back button.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  win.loadURL(cfg.url).catch(() => {});

  win.webContents.on("did-fail-load", (_e, code, desc) => {
    // Server down or no network — say so plainly instead of a blank window.
    // -3 is an aborted load (normal during redirects), not a failure.
    if (code === -3) return;
    win.loadURL(
      "data:text/html," +
        encodeURIComponent(
          `<body style="font:14px system-ui;padding:40px;color:#333">
           <h2>Can't reach Anvil</h2>
           <p>${cfg.url}</p>
           <p style="color:#888">${desc} (${code})</p>
           <p style="color:#888">The server may be down, or the stack isn't deployed yet.</p>
           <button onclick="location.reload()">Retry</button></body>`
        )
    );
  });

  win.on("closed", () => {
    win = null;
  });
}

// ------------------------------------------------------- question polling

async function pollQuestions() {
  const cfg = readConfig();
  if (!cfg) return;
  // Falls back to `url` for configs written before the local setup (dashboard
  // and API on different ports) needed them apart.
  const api = (cfg.apiUrl || cfg.url).replace(/\/$/, "");
  try {
    const res = await fetch(`${api}/api/questions?status=open`, {
      headers: { Authorization: authHeader(cfg) },
    });
    if (!res.ok) return;
    const open = await res.json();
    const count = Array.isArray(open) ? open.length : 0;

    if (tray) {
      tray.setToolTip(count ? `Anvil — ${count} question(s) waiting` : "Anvil");
    }

    // Only notify on a rise. Re-notifying every minute for the same unanswered
    // question is how a notification becomes something you learn to ignore.
    if (count > lastOpenCount) {
      const newest = open[0];
      new Notification({
        title: count === 1 ? "An agent needs you" : `${count} questions waiting`,
        body: newest ? `${newest.agent}: ${newest.question}` : "Open Anvil to answer.",
      })
        .on("click", () => {
          if (!win) openDashboard();
          else win.show();
        })
        .show();
    }
    lastOpenCount = count;
  } catch {
    // Offline or server down — the window's own error page covers it.
  }
}

// ------------------------------------------------------------------- boot

app.whenReady().then(() => {
  const cfg = readConfig();
  if (cfg) openDashboard();
  else showSetup();

  try {
    tray = new Tray(path.join(process.resourcesPath || __dirname, "icon.png"));
  } catch {
    tray = null; // no icon shipped yet — the app works fine without a tray
  }
  if (tray) {
    tray.setToolTip("Anvil");
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: "Open Anvil", click: () => (win ? win.show() : openDashboard()) },
        { label: "Check now", click: pollQuestions },
        { type: "separator" },
        {
          label: "Reset connection…",
          click: () => {
            try {
              fs.unlinkSync(CONFIG);
            } catch {}
            if (win) win.close();
            showSetup();
          },
        },
        { label: "Quit", click: () => app.quit() },
      ])
    );
  }

  pollQuestions();
  setInterval(pollQuestions, POLL_MS);
});

app.on("window-all-closed", () => {
  // Keep running so notifications still arrive with the window closed. Quit
  // from the tray menu.
  if (!tray) app.quit();
});

app.on("activate", () => {
  if (!win) openDashboard();
});
