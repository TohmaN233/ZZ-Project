const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { EventEmitter } = require("node:events");
const { ensureStartupAssets } = require("../electron/asset-setup");
const source = require("../electron/asset-source.json");

async function fixture(t, choices) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "zz-asset-consent-test-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const destination = path.join(root, "asserts");
  const dialogs = [], windows = [], handlers = new Map();
  class FakeWindow extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.destroyed = false; this.messages = [];
      this.webContents = new EventEmitter();
      this.webContents.setWindowOpenHandler = () => {};
      this.webContents.send = (channel, event) => this.messages.push({ channel, event });
      windows.push(this);
    }
    async loadFile(file) { this.file = file; }
    setProgressBar(value) { this.percent = value; }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; this.emit("close"); }
  }
  return { destination, source, BrowserWindow: FakeWindow,
    dialog: { async showMessageBox(options) { dialogs.push(options); return { response: choices.shift() }; } },
    ipcMain: { handle: (channel, fn) => handlers.set(channel, fn), removeHandler: channel => handlers.delete(channel) },
    dialogs, windows, handlers,
  };
}

test("refusing download never contacts the network or creates an installation window", async t => {
  const context = await fixture(t, [1]);
  const result = await ensureStartupAssets({ ...context, fetchImpl: () => { throw Error("network accessed"); },
    installImpl: () => { throw Error("download started without consent"); } });
  assert.equal(result, null); assert.equal(context.windows.length, 0);
  assert.match(context.dialogs[0].detail, /asserts\.7z/);
  assert.match(context.dialogs[0].detail, /1\.43 GiB/);
  assert.match(context.dialogs[0].detail, /1\.53 GB/);
  assert.match(context.dialogs[0].detail, /3\.2 GB/);
  assert.ok(context.dialogs[0].detail.includes(context.destination));
});

test("complete assets bypass consent and installation", async t => {
  const context = await fixture(t, []);
  for (const directory of ["ZENONZARD_CARDLIST", "audio", "video"]) await fs.mkdir(path.join(context.destination, directory), { recursive: true });
  assert.equal(await ensureStartupAssets({ ...context, installImpl: () => { throw Error("unexpected install"); } }), context.destination);
  assert.equal(context.dialogs.length, 0);
});

test("accepted installation streams progress to the isolated window and cleans IPC", async t => {
  const context = await fixture(t, [0]);
  const result = await ensureStartupAssets({ ...context, installImpl: async ({ onProgress }) => {
    assert.equal(context.dialogs.length, 1);
    assert.throws(() => context.handlers.get("assets:cancel")({ sender: {} }), /Untrusted/);
    onProgress({ stage: "download", percent: 40, receivedBytes: 12, totalBytes: source.sizeBytes });
    onProgress({ stage: "complete", percent: 100 });
  } });
  assert.equal(result, context.destination);
  const window = context.windows[0];
  assert.equal(window.options.webPreferences.nodeIntegration, false);
  assert.equal(window.options.webPreferences.contextIsolation, true);
  assert.equal(window.messages[0].event.destination, context.destination);
  assert.equal(window.messages.at(-1).event.stage, "complete");
  assert.equal(window.destroyed, true); assert.equal(context.handlers.size, 0);
});

test("cancel from the setup window aborts installation without retrying", async t => {
  const context = await fixture(t, [0]);
  const result = await ensureStartupAssets({ ...context, installImpl: async ({ signal }) => {
    const pending = new Promise((resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("cancel", "AbortError")), { once: true }));
    context.handlers.get("assets:cancel")({ sender: context.windows[0].webContents });
    await pending;
  } });
  assert.equal(result, null); assert.equal(context.dialogs.length, 1);
  assert.equal(context.handlers.size, 0);
});

test("installation failure remains visible and retry is an explicit user choice", async t => {
  const context = await fixture(t, [0, 0]);
  let attempts = 0;
  const result = await ensureStartupAssets({ ...context, installImpl: async () => {
    attempts += 1;
    if (attempts === 1) throw Object.assign(Error("cannot write assets"), { code: "EACCES" });
  } });
  assert.equal(result, context.destination); assert.equal(attempts, 2);
  assert.equal(context.dialogs[1].type, "error");
  assert.match(context.dialogs[1].detail, /cannot write assets/);
  assert.match(context.dialogs[1].detail, /写入权限/);
  assert.equal(context.windows.every(w => w.destroyed), true);
});

test("application quit can close the pending native consent dialog without starting download", async t => {
  const context = await fixture(t, []);
  const controller = new AbortController();
  const pending = ensureStartupAssets({ ...context, signal: controller.signal,
    dialog: { showMessageBox: options => new Promise(resolve => {
      assert.equal(options.signal, controller.signal);
      options.signal.addEventListener("abort", () => resolve({ response: options.cancelId }), { once: true });
    }) }, installImpl: () => { throw Error("download started during shutdown"); },
  });
  controller.abort();
  assert.equal(await pending, null); assert.equal(context.windows.length, 0);
});
