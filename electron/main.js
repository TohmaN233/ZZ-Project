const { app, BrowserWindow, dialog, ipcMain, Menu, net, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const fsSync = require("node:fs");
const fs = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");
const { createAdaptiveWebSocketClass } = require("./adaptive-websocket");
const { LanManager } = require("./lan-manager");
const { MultiplayerDesktopClient } = require("./multiplayer-client");
const {
  checkLatestRelease,
  LATEST_RELEASE_URL,
  PROJECT_WEBSITE_URL,
} = require("./update-checker");

let mainWindow = null;
let serverProcess = null;
let serverUrl = null;
let serverState = "stopped";
let trustedOrigin = null;
const serverLog = [];
let multiplayerRoute = "UNSELECTED";
const AdaptiveWebSocket = createAdaptiveWebSocketClass({
  resolveProxy: (url) => session.defaultSession.resolveProxy(url),
  onRouteSelected: (route) => {
    multiplayerRoute = route.kind.toUpperCase();
    appendLog(`Multiplayer route selected: ${multiplayerRoute}`);
  },
});
const multiplayerClient = new MultiplayerDesktopClient({ WebSocketImpl: AdaptiveWebSocket });
const lanManager = new LanManager();
let multiplayerRecoveryPath = null;
let multiplayerRecoveryWrite = Promise.resolve();
let multiplayerReconnectTimer = null;
const multiplayerReconnectDelayMs = 1000;
let shutdownPrepared = false;
let shutdownPromise = null;
let updateCheckPromise = null;
let updateStatus = { status: "idle", currentVersion: null };

app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

function projectRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, "app");
  return path.resolve(__dirname, "..");
}

function packagedServerPath() {
  if (!app.isPackaged) return null;
  const executable = process.platform === "win32" ? "zz-server.exe" : "zz-server";
  return path.join(process.resourcesPath, "server", executable);
}

function packagedAssetRoot() {
  const configured = process.env.ZZ_ASSET_ROOT;
  if (configured) {
    const configuredCandidates = [
      path.resolve(configured),
      path.resolve(projectRoot(), configured),
      path.resolve(path.dirname(process.execPath), configured),
    ];
    const configuredRoot = configuredCandidates.find(assetRootLooksValid);
    if (configuredRoot) return configuredRoot;
    appendLog(`Ignoring invalid ZZ_ASSET_ROOT: ${configured}`);
  }
  const primary = path.join(path.dirname(process.execPath), "asserts");
  const candidates = [
    primary,
    path.join(primary, "asserts"),
    path.join(process.resourcesPath, "asserts"),
    path.join(projectRoot(), "asserts"),
  ];
  return candidates.find(assetRootLooksValid) || primary;
}

function assetRootLooksValid(candidate) {
  try {
    return ["ZENONZARD_CARDLIST", "audio", "video"].every((name) =>
      fsSync.statSync(path.join(candidate, name)).isDirectory()
    );
  } catch (_error) {
    return false;
  }
}

function packagedDeckRoot() {
  return path.join(path.dirname(process.execPath), "data", "decks");
}

function packagedUserDataRoot() {
  return path.join(app.getPath("userData"), "game-data");
}

function applicationIconPath() {
  return path.join(app.getAppPath(), "electron", "icon-256.png");
}

function openHelpUrl(url, label) {
  shell.openExternal(url).catch((error) => {
    appendLog(`Opening ${label} failed: ${error.message || error}`);
  });
}

function installApplicationMenu() {
  const template = [];
  if (process.platform === "darwin") {
    template.push({
      label: app.name,
      submenu: [{ role: "about" }, { type: "separator" }, { role: "quit" }],
    });
  }
  template.push(
    { role: "fileMenu" },
    { role: "viewMenu" },
    { role: "windowMenu" },
    {
      role: "help",
      submenu: [
        {
          label: "项目发布页 / Project Page",
          click: () => openHelpUrl(PROJECT_WEBSITE_URL, "project page"),
        },
        {
          label: "最新版本 / Latest Release",
          click: () => openHelpUrl(LATEST_RELEASE_URL, "latest release"),
        },
      ],
    },
  );
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function defaultPort() {
  const raw = Number(process.env.ZZ_WEB_PORT || 0);
  return Number.isInteger(raw) && raw >= 0 && raw <= 65535 ? raw : 0;
}

function normalizePort(value) {
  const raw = Number(value);
  return Number.isInteger(raw) && raw >= 0 && raw <= 65535 ? raw : defaultPort();
}

function appendLog(chunk) {
  const text = String(chunk || "").trim();
  if (!text) return;
  serverLog.push(text);
  if (serverLog.length > 40) serverLog.splice(0, serverLog.length - 40);
  try {
    if (app.isReady()) {
      const logPath = path.join(app.getPath("userData"), "server.log");
      fsSync.mkdirSync(path.dirname(logPath), { recursive: true });
      fsSync.appendFileSync(logPath, `${new Date().toISOString()} ${text}\n`, "utf8");
    }
  } catch (error) {
    console.error(`Failed to persist server log: ${error.message || error}`);
  }
}

function statusSnapshot() {
  return {
    state: serverState,
    url: serverUrl,
    pid: serverProcess ? serverProcess.pid : null,
    log: [...serverLog],
  };
}

async function checkForApplicationUpdate() {
  if (updateStatus.status === "current" || updateStatus.status === "available") return { ...updateStatus };
  if (updateCheckPromise) return updateCheckPromise;
  const currentVersion = app.getVersion();
  updateStatus = { status: "checking", currentVersion };
  updateCheckPromise = checkLatestRelease({
    currentVersion,
    fetchImpl: (url, options) => net.fetch(url, options),
  }).then((result) => {
    updateStatus = result;
    appendLog(result.status === "available"
      ? `Application update available: ${result.currentVersion} -> ${result.latestVersion}`
      : `Application update check complete: ${result.currentVersion} is current`);
    return { ...updateStatus };
  }).catch((error) => {
    const message = error && error.message ? error.message : String(error);
    updateStatus = { status: "error", currentVersion, error: message };
    appendLog(`Application update check failed: ${message}`);
    return { ...updateStatus };
  }).finally(() => {
    updateCheckPromise = null;
  });
  return updateCheckPromise;
}

function multiplayerSnapshot() {
  const snapshot = multiplayerClient.getSnapshot();
  const lan = lanManager.getSnapshot();
  return {
    ...snapshot,
    status: snapshot.state,
    lastError: snapshot.error,
    networkRoute: multiplayerRoute,
    lan: {
      ...lan,
      state: String(lan.state || "stopped").toUpperCase(),
      localUrl: lan.manualEndpoints.localUrl,
      addresses: lan.manualEndpoints.addresses,
      urls: lan.manualEndpoints.urls,
    },
  };
}

function queueMultiplayerRecoveryWrite() {
  if (!multiplayerRecoveryPath) return multiplayerRecoveryWrite;
  const recovery = multiplayerClient.getRecoverySession();
  const targetPath = multiplayerRecoveryPath;
  multiplayerRecoveryWrite = multiplayerRecoveryWrite
    .then(async () => {
      if (recovery === null) {
        await fs.rm(targetPath, { force: true });
        return;
      }
      await fs.mkdir(path.dirname(targetPath), { recursive: true });
      const temporaryPath = `${targetPath}.tmp`;
      await fs.writeFile(temporaryPath, `${JSON.stringify(recovery)}\n`, {
        encoding: "utf8",
        mode: 0o600,
      });
      await fs.rename(temporaryPath, targetPath);
    })
    .catch((error) => {
      appendLog(`Multiplayer recovery write failed: ${error.message || error}`);
    });
  return multiplayerRecoveryWrite;
}

async function restoreMultiplayerRecovery() {
  if (!multiplayerRecoveryPath) return false;
  let raw;
  try {
    raw = await fs.readFile(multiplayerRecoveryPath, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT") return false;
    throw error;
  }
  try {
    multiplayerClient.restoreRecoverySession(JSON.parse(raw));
    return true;
  } catch (error) {
    appendLog(`Multiplayer recovery restore failed: ${error.message || error}`);
    return false;
  }
}

function scheduleMultiplayerReconnect() {
  if (multiplayerClient.state !== "RECONNECTING" || !multiplayerClient.getSnapshot().canReconnect) {
    if (multiplayerReconnectTimer !== null) clearTimeout(multiplayerReconnectTimer);
    multiplayerReconnectTimer = null;
    return;
  }
  if (multiplayerReconnectTimer !== null) return;
  multiplayerReconnectTimer = setTimeout(() => {
    multiplayerReconnectTimer = null;
    if (multiplayerClient.state !== "RECONNECTING") return;
    if (multiplayerClient.getSnapshot().reconnectAttemptActive) return;
    try {
      multiplayerClient.reconnect();
    } catch (error) {
      appendLog(`Multiplayer reconnect attempt failed: ${error.message || error}`);
      scheduleMultiplayerReconnect();
    }
  }, multiplayerReconnectDelayMs);
}

function syncLanAdvertisement() {
  const lan = lanManager.getSnapshot();
  if (lan.state !== "running") return;
  const room = multiplayerClient.room;
  if (room && ["WAITING_FOR_PLAYERS", "READY_CHECK"].includes(room.status)) {
    lanManager.updateRoom({
      roomCode: room.roomCode,
      players: Array.isArray(room.players) ? room.players.length : 0,
      capacity: room.capacity,
    });
  } else {
    lanManager.clearRoom();
  }
}

function broadcastMultiplayerEvent(event) {
  syncLanAdvertisement();
  queueMultiplayerRecoveryWrite();
  scheduleMultiplayerReconnect();
  const payload = {
    ...event,
    snapshot: multiplayerSnapshot(),
  };
  if (!mainWindow || mainWindow.isDestroyed() || !isTrustedUrl(mainWindow.webContents.getURL())) return;
  mainWindow.webContents.send("multiplayer:event", payload);
}

multiplayerClient.onEvent(broadcastMultiplayerEvent);

function rememberTrustedOrigin(url) {
  trustedOrigin = new URL(url).origin;
}

function isTrustedUrl(url) {
  if (!trustedOrigin || !url) return false;
  try {
    return new URL(url).origin === trustedOrigin;
  } catch (_) {
    return false;
  }
}

function isTrustedReplayUrl(url) {
  if (!isTrustedUrl(url)) return false;
  try {
    const parsed = new URL(url);
    return parsed.hash.startsWith("#/replay/");
  } catch (_) {
    return false;
  }
}

function assertTrustedSender(event) {
  const senderUrl = event.senderFrame ? event.senderFrame.url : event.sender.getURL();
  if (!isTrustedUrl(senderUrl)) {
    throw new Error("Untrusted IPC sender.");
  }
}

function waitForHttp(url, timeoutMs = 15000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const poll = () => {
      const request = http.get(url, (response) => {
        response.resume();
        resolve(true);
      });
      request.on("error", (error) => {
        if (Date.now() - startedAt >= timeoutMs) {
          reject(error);
          return;
        }
        setTimeout(poll, 250);
      });
      request.setTimeout(1000, () => {
        request.destroy();
      });
    };
    poll();
  });
}

function pythonArgs(port) {
  const assetRoot = app.isPackaged ? packagedAssetRoot() : null;
  if (assetRoot && app.isPackaged) {
    appendLog(`Packaged asset root: ${assetRoot}${assetRootLooksValid(assetRoot) ? "" : " (expected folders not found)"}`);
  }
  const args = app.isPackaged
    ? ["--host", "127.0.0.1", "--port", String(port), "--asset-root", assetRoot,
      "--user-data-root", packagedUserDataRoot(), "--bundled-deck-root", packagedDeckRoot()]
    : ["-m", "zz.web.server", "--host", "127.0.0.1", "--port", String(port)];
  if (!app.isPackaged && process.env.ZZ_ASSET_ROOT) args.push("--asset-root", process.env.ZZ_ASSET_ROOT);
  return args;
}

async function startServer(options = {}) {
  if (serverProcess && serverState !== "stopped") {
    return statusSnapshot();
  }
  const port = normalizePort(options.port);
  serverState = "starting";
  const serverCommand = packagedServerPath() || process.env.ZZ_PYTHON || "python";
  serverProcess = spawn(serverCommand, pythonArgs(port), {
    cwd: projectRoot(),
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });

  serverProcess.stdout.on("data", (chunk) => {
    const text = chunk.toString("utf8");
    appendLog(text);
    const match = text.match(/https?:\/\/127\.0\.0\.1:\d+\//);
    if (match) {
      serverUrl = match[0];
    }
  });
  serverProcess.stderr.on("data", appendLog);
  serverProcess.on("exit", (code, signal) => {
    appendLog(`Python server exited: ${code ?? signal}`);
    serverProcess = null;
    if (serverState !== "stopping") {
      serverState = "stopped";
    }
  });

  const readinessUrl = new Promise((resolve, reject) => {
    const startedAt = Date.now();
    const readUrl = () => {
      if (serverUrl) {
        resolve(serverUrl);
        return;
      }
      if (Date.now() - startedAt > 15000) {
        reject(new Error("Timed out waiting for Python server URL."));
        return;
      }
      setTimeout(readUrl, 100);
    };
    readUrl();
  });
  serverUrl = await readinessUrl;
  await waitForHttp(serverUrl, 15000);
  serverState = "running";
  return statusSnapshot();
}

function waitForProcessExit(child, timeoutMs = 5000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve(true);
    };
    child.once("exit", finish);
    child.once("close", finish);
    setTimeout(() => {
      if (!done) child.kill();
      finish();
    }, timeoutMs);
  });
}

function terminateProcessTree(child) {
  if (!child || !child.pid) return;
  if (process.platform !== "win32") {
    child.kill();
    return;
  }
  const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
    windowsHide: true,
    stdio: "ignore",
  });
  killer.once("error", (error) => {
    appendLog(`Failed to terminate server process tree: ${error.message || error}`);
    try {
      child.kill();
    } catch (killError) {
      appendLog(`Fallback server termination failed: ${killError.message || killError}`);
    }
  });
  killer.once("exit", (code, signal) => {
    if (code !== 0 && code !== 128) {
      appendLog(`taskkill exited with ${code ?? signal}`);
    }
  });
}

async function stopServer() {
  if (!serverProcess) {
    serverState = "stopped";
    return statusSnapshot();
  }
  serverState = "stopping";
  const processToStop = serverProcess;
  terminateProcessTree(processToStop);
  await waitForProcessExit(processToStop);
  if (serverProcess === processToStop) {
    serverProcess = null;
  }
  serverState = "stopped";
  serverUrl = null;
  return statusSnapshot();
}

function createReplayWindow(url) {
  if (!isTrustedReplayUrl(url)) {
    throw new Error("Untrusted replay URL.");
  }
  const replayWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: "#05090c",
    icon: applicationIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  replayWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (!isTrustedUrl(targetUrl)) {
      event.preventDefault();
    }
  });
  replayWindow.webContents.setWindowOpenHandler(({ url: targetUrl }) => (
    isTrustedUrl(targetUrl) ? { action: "allow" } : { action: "deny" }
  ));
  replayWindow.loadURL(url);
  return replayWindow;
}

async function createWindow() {
  const status = await startServer();
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 980,
    minHeight: 680,
    icon: applicationIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  rememberTrustedOrigin(serverUrl);
  mainWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (!isTrustedUrl(targetUrl)) {
      event.preventDefault();
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => (
    isTrustedUrl(url) ? { action: "allow" } : { action: "deny" }
  ));
  await mainWindow.loadURL(serverUrl);
  mainWindow.on("closed", () => {
    mainWindow = null;
    if (!shutdownPrepared) app.quit();
  });
  return status;
}

function registerIpc() {
  ipcMain.handle("server:start", async (_event, options) => {
    assertTrustedSender(_event);
    return startServer(options || {});
  });
  ipcMain.handle("server:stop", async (_event) => {
    assertTrustedSender(_event);
    return stopServer();
  });
  ipcMain.handle("server:status", async (_event) => {
    assertTrustedSender(_event);
    return statusSnapshot();
  });
  ipcMain.handle("dialog:openFolder", async (_event) => {
    assertTrustedSender(_event);
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"] });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("shell:openPath", async (_event, targetPath) => {
    assertTrustedSender(_event);
    if (typeof targetPath !== "string" || !targetPath || !path.isAbsolute(targetPath) || targetPath.includes("\0")) {
      return { ok: false, error: "invalid_path" };
    }
    const error = await shell.openPath(targetPath);
    return { ok: !error, error: error || null };
  });
  ipcMain.handle("replay:openWindow", async (_event, payload) => {
    assertTrustedSender(_event);
    const url = payload && typeof payload.url === "string" ? payload.url : "";
    createReplayWindow(url);
    return { ok: true };
  });
  ipcMain.handle("assets:selectRoot", async (_event) => {
    assertTrustedSender(_event);
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"], title: "Select asset root" });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("decks:selectRoot", async (_event) => {
    assertTrustedSender(_event);
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"], title: "Select deck root" });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("app:getVersion", async (_event) => {
    assertTrustedSender(_event);
    return app.getVersion();
  });
  ipcMain.handle("app:checkForUpdates", async (_event) => {
    assertTrustedSender(_event);
    return checkForApplicationUpdate();
  });
  ipcMain.handle("app:openReleasePage", async (_event) => {
    assertTrustedSender(_event);
    await shell.openExternal(LATEST_RELEASE_URL);
    return { ok: true };
  });
  ipcMain.handle("app:quit", async (_event) => {
    assertTrustedSender(_event);
    app.quit();
    return { ok: true };
  });
  ipcMain.handle("multiplayer:status", async (_event) => {
    assertTrustedSender(_event);
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:connect", async (_event, config) => {
    assertTrustedSender(_event);
    multiplayerRoute = "CHECKING";
    multiplayerClient.connect(config || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:disconnect", async (_event) => {
    assertTrustedSender(_event);
    multiplayerClient.disconnect();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:reconnect", async (_event) => {
    assertTrustedSender(_event);
    multiplayerRoute = "CHECKING";
    multiplayerClient.reconnect();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:createRoom", async (_event, payload) => {
    assertTrustedSender(_event);
    multiplayerClient.createRoom(payload || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:joinRoom", async (_event, payload) => {
    assertTrustedSender(_event);
    multiplayerClient.joinRoom(payload || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:selectDeck", async (_event, payload) => {
    assertTrustedSender(_event);
    multiplayerClient.selectDeck(payload || {});
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:setReady", async (_event, ready) => {
    assertTrustedSender(_event);
    multiplayerClient.setReady({ ready });
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:selectOpeningChoice", async (_event, choice) => {
    assertTrustedSender(_event);
    multiplayerClient.selectOpeningChoice({ choice });
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:submitAction", async (_event, action) => {
    assertTrustedSender(_event);
    const clientActionId = multiplayerClient.submitAction({ action });
    await queueMultiplayerRecoveryWrite();
    return { ...multiplayerSnapshot(), clientActionId };
  });
  ipcMain.handle("multiplayer:surrender", async (_event) => {
    assertTrustedSender(_event);
    const clientActionId = multiplayerClient.surrender();
    await queueMultiplayerRecoveryWrite();
    return { ...multiplayerSnapshot(), clientActionId };
  });
  ipcMain.handle("multiplayer:requestSync", async (_event) => {
    assertTrustedSender(_event);
    multiplayerClient.requestSync();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:leaveRoom", async (_event) => {
    assertTrustedSender(_event);
    multiplayerClient.leaveRoom();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:dismissMatchResult", async (_event) => {
    assertTrustedSender(_event);
    multiplayerClient.dismissMatchResult();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:lanStatus", async (_event) => {
    assertTrustedSender(_event);
    return multiplayerSnapshot().lan;
  });
  ipcMain.handle("multiplayer:startLanHost", async (_event, options) => {
    assertTrustedSender(_event);
    const port = (options && options.port) || 32145;
    const packaged = packagedServerPath();
    await lanManager.startHost({
      projectRoot: projectRoot(),
      python: process.env.ZZ_PYTHON || "python",
      command: packaged || process.env.ZZ_PYTHON || "python",
      args: packaged
        ? ["--multiplayer", "--host", "0.0.0.0", "--port", String(port)]
        : ["-m", "zz.multiplayer.websocket_server", "--host", "0.0.0.0", "--port", String(port)],
      port,
      serverName: options && options.serverName,
    });
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:stopLanHost", async (_event) => {
    assertTrustedSender(_event);
    await lanManager.stopHost();
    return multiplayerSnapshot();
  });
  ipcMain.handle("multiplayer:discoverLan", async (_event, options) => {
    assertTrustedSender(_event);
    return lanManager.discover(options || {});
  });
}

app.whenReady().then(async () => {
  installApplicationMenu();
  if (process.platform === "darwin" && app.dock) app.dock.setIcon(applicationIconPath());
  multiplayerRecoveryPath = path.join(app.getPath("userData"), "multiplayer-recovery.json");
  const shouldReconnect = await restoreMultiplayerRecovery();
  registerIpc();
  await createWindow();
  if (shouldReconnect) {
    try {
      multiplayerClient.reconnect();
    } catch (error) {
      appendLog(`Initial multiplayer reconnect failed: ${error.message || error}`);
      scheduleMultiplayerReconnect();
    }
  }
  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});

app.on("before-quit", (event) => {
  if (shutdownPrepared) return;
  event.preventDefault();
  if (shutdownPromise !== null) return;
  if (multiplayerReconnectTimer !== null) clearTimeout(multiplayerReconnectTimer);
  multiplayerReconnectTimer = null;
  if (multiplayerClient.getSnapshot().canReconnect) multiplayerClient.suspend();
  else multiplayerClient.disconnect();
  shutdownPromise = Promise.allSettled([
    queueMultiplayerRecoveryWrite(),
    lanManager.stopHost(),
    stopServer(),
  ]).finally(() => {
    shutdownPrepared = true;
    app.quit();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
