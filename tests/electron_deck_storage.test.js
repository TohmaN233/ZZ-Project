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

test("packaged server reads writable game-root decks and immutable bundled defaults", () => {
  const context = vm.createContext({
    path: path.win32,
    process: { execPath: "D:\\Games\\ZZ\\ZZ-Project.exe", resourcesPath: "D:\\Games\\ZZ\\resources", env: {} },
    app: { isPackaged: true, getPath: () => "C:\\Users\\Player\\AppData\\Roaming\\zenonzard-clone" },
    startupAssetRoot: null,
    packagedAssetRoot: () => "D:\\Games\\ZZ\\asserts",
    assetRootLooksValid: () => true,
    appendLog() {},
  });
  vm.runInContext(["packagedDeckRoot", "packagedBundledDeckRoot", "packagedUserDataRoot", "pythonArgs"]
    .map(functionSource).join("\n"), context);
  const args = Array.from(context.pythonArgs(12345));
  assert.equal(args[args.indexOf("--deck-root") + 1], "D:\\Games\\ZZ\\data\\decks");
  assert.equal(args[args.indexOf("--bundled-deck-root") + 1], "D:\\Games\\ZZ\\resources\\default-decks");
  assert.equal(args[args.indexOf("--user-data-root") + 1], "C:\\Users\\Player\\AppData\\Roaming\\zenonzard-clone\\game-data");
  context.app.isPackaged = false;
  assert.equal(Array.from(context.pythonArgs(12345)).includes("--deck-root"), false);
});

test("server startup surfaces a deck-directory permission error without waiting for timeout", async () => {
  const process = Object.assign(new EventEmitter(), { stdout: new EventEmitter(), stderr: new EventEmitter() });
  const logs = [];
  const calls = [];
  const context = vm.createContext({
    serverProcess: null, serverState: "stopped", serverUrl: null,
    normalizePort: () => 0, packagedServerPath: () => "zz-server.exe",
    pythonArgs: () => [], projectRoot: () => "D:\\Games\\ZZ", path: path.win32,
    app: { getPath: () => "C:\\Player\\AppData\\zenonzard-clone" },
    process: { env: {} }, spawn: (...args) => { calls.push(args); return process; },
    appendLog: value => logs.push(String(value)),
    setTimeout, Date, waitForHttp: async () => {}, statusSnapshot: () => ({}),
  });
  vm.runInContext(functionSource("startServer"), context);
  const started = Date.now();
  const result = context.startServer();
  assert.equal(calls[0][2].env.PYTHONIOENCODING, "utf-8");
  process.stderr.emit("data", Buffer.from("PermissionError: D:\\Games\\ZZ\\data\\decks\\a.json"));
  process.emit("exit", 1, null);
  process.emit("close", 1, null);
  await assert.rejects(result, /PermissionError: D:\\Games\\ZZ\\data\\decks\\a\.json/);
  assert.ok(Date.now() - started < 2000, "startup failure should not wait for the 15 second timeout");
  assert.ok(logs.some(line => line.includes("PermissionError")));
});

test("server process launch errors reach the user", async () => {
  const child = Object.assign(new EventEmitter(), { stdout: new EventEmitter(), stderr: new EventEmitter() });
  const context = vm.createContext({
    serverProcess: null, serverState: "stopped", serverUrl: null,
    normalizePort: () => 0, packagedServerPath: () => "zz-server.exe",
    pythonArgs: () => [], projectRoot: () => "D:\\Games\\ZZ", path: path.win32,
    app: { getPath: () => "C:\\Player\\AppData\\zenonzard-clone" },
    process: { env: {} }, spawn: () => child, appendLog() {},
    setTimeout, Date, waitForHttp: async () => {}, statusSnapshot: () => ({}),
  });
  vm.runInContext(functionSource("startServer"), context);
  const result = context.startServer();
  child.emit("error", new Error("ENOENT missing server"));
  await assert.rejects(result, /Unable to start Python server: ENOENT missing server/);
});
