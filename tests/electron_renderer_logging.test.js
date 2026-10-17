const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../electron/main.js"), "utf8");
function functionSource(name) {
  const start = source.search(new RegExp(`^(?:async )?function ${name}\\(`, "m"));
  assert.notEqual(start, -1, name);
  const rest = source.slice(start);
  const end = rest.slice(1).search(/\n(?:async )?function \w+\(/);
  return end < 0 ? rest : rest.slice(0, end + 1);
}

function harness(snapshot) {
  const logs = [];
  class FakeWindow extends EventEmitter {
    constructor() {
      super();
      this.webContents = Object.assign(new EventEmitter(), { setWindowOpenHandler() {} });
    }
    async loadURL(url) { this.loadedUrl = url; }
  }
  const context = vm.createContext({
    appendLog: value => logs.push(value),
    multiplayerClient: { getSnapshot: () => snapshot },
    BrowserWindow: FakeWindow,
    startServer: async () => ({ state: "running" }),
    applicationIconPath: () => "icon.png",
    rememberTrustedOrigin() {},
    isTrustedUrl: () => true,
    serverUrl: "http://127.0.0.1:1234/",
    mainWindow: null,
    shutdownPrepared: true,
    app: { quit() { throw new Error("test must not quit the application"); } },
    path,
    __dirname: path.join(__dirname, "../electron"),
  });
  vm.runInContext(functionSource("logRendererConsoleError") + "\n" + functionSource("createWindow"), context);
  return { context, logs };
}

const errorDetails = {
  level: "error",
  message: "Uncaught Error: Visual zone transition duplicated card undefined entering P1:hand.",
  sourceId: "http://127.0.0.1:1234/static/app.js?private=source-query#fragment",
  lineNumber: 1441,
};

test("renderer errors persist allowlisted multiplayer context without recovery credentials or cards", () => {
  const { context, logs } = harness({
    state: "IN_MATCH", room: { roomCode: "ABC123", reconnectToken: "room-secret" },
    matchId: "test-match", playerId: "player_2",
    view: { revision: 7, players: { human: { hand: ["private-card"] } } },
    pendingAction: { clientActionId: "test-action", action: { payload: "private-action" } },
    reconnectToken: "recovery-secret",
  });
  context.logRendererConsoleError(errorDetails);
  assert.equal(logs.length, 1);
  assert.ok(logs[0].startsWith("[Frontend error] "));
  assert.deepEqual(JSON.parse(logs[0].slice("[Frontend error] ".length)), {
    code: "VISUAL_CARD_DUPLICATE", source: "app.js", line: 1441,
    status: "IN_MATCH", roomCode: "ABC123", matchId: "test-match", playerId: "player_2",
    revision: 7, pendingActionId: "test-action",
  });
  assert.doesNotMatch(logs[0], /room-secret|private-card|private-action|recovery-secret|source-query|fragment/);
});

test("untrusted error text and source names cannot persist credentials or private hand data", () => {
  const { context, logs } = harness({ state: "IN_MATCH", room: null, view: null, pendingAction: null });
  context.logRendererConsoleError({
    ...errorDetails,
    message: 'Uncaught Error: reconnectToken=recovery-secret hand=[private-card]',
    sourceId: 'https://secret-user:secret-pass@example.invalid/private-card?token=recovery-secret',
  });
  const entry = JSON.parse(logs[0].slice("[Frontend error] ".length));
  assert.equal(entry.code, "RENDERER_ERROR");
  assert.equal(entry.source, "renderer");
  assert.doesNotMatch(logs[0], /recovery-secret|private-card|secret-user|secret-pass/);
});

test("ordinary console output does not fill the diagnostic log", () => {
  const { context, logs } = harness({ state: "OFFLINE" });
  for (const level of ["info", "warning", "debug"]) context.logRendererConsoleError({ ...errorDetails, level });
  assert.deepEqual(logs, []);
});

test("renderer errors before entering a room remain observable", () => {
  const { context, logs } = harness({ state: "CONNECTED", room: null, view: null, pendingAction: null });
  context.logRendererConsoleError(errorDetails);
  const entry = JSON.parse(logs[0].slice("[Frontend error] ".length));
  assert.equal(entry.status, "CONNECTED");
  assert.equal(entry.roomCode, null);
  assert.equal(entry.revision, null);
});

test("the game window subscribes to the Electron error event before gameplay", async () => {
  const { context, logs } = harness({ state: "IN_MATCH", view: { revision: 1 }, room: null });
  await context.createWindow();
  assert.equal(context.mainWindow.loadedUrl, context.serverUrl);
  context.mainWindow.webContents.emit("console-message", errorDetails);
  assert.equal(logs.length, 1);
});
