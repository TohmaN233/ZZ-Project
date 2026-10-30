"use strict";

// Invoked by the real Python gateway test. Recovery credentials arrive only on
// stdin and stay out of process arguments, stdout, renderer events and logs.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { readFileSync } = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const WebSocket = require("ws");
const { MultiplayerDesktopClient } = require("../electron/multiplayer-client");

async function run() {
  const recovery = JSON.parse(readFileSync(0, "utf8"));
  let drops = 3;
  const lostCandidates = [];
  class LossyWebSocket extends WebSocket {
    addEventListener(type, listener, options) {
      if (type !== "message") return super.addEventListener(type, listener, options);
      const wrapped = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "ROOM_STATE" && drops > 0) {
          drops -= 1;
          lostCandidates.push(message.payload.reconnectToken);
          this.terminate();
          return;
        }
        // terminate() can leave an already buffered snapshot in the same tick.
        if (this.readyState === WebSocket.OPEN) listener(event);
      };
      this.messageListener = { listener, wrapped };
      return super.addEventListener(type, wrapped, options);
    }
    removeEventListener(type, listener, options) {
      const wrapped = type === "message" && this.messageListener?.listener === listener
        ? this.messageListener.wrapped : listener;
      return super.removeEventListener(type, wrapped, options);
    }
  }
  const client = new MultiplayerDesktopClient({ WebSocketImpl: LossyWebSocket });
  const publicEvents = [];
  client.onEvent((event) => publicEvents.push(event));
  const wait = (target, predicate) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => { unsubscribe(); reject(new Error("expected recovery event timed out")); }, 3000);
    const unsubscribe = target.onEvent((event) => {
      if (predicate(event)) { clearTimeout(timer); unsubscribe(); resolve(event); }
    });
  });
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "zz-reconnect-test-"));
  const filename = path.join(directory, "recovery.json");
  let replacement;
  let stale;
  try {
    client.restoreRecoverySession(recovery);
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      const failed = wait(client, (event) => event.type === "RECONNECT_FAILED");
      client.reconnect();
      await failed;
      assert.equal(client.getSnapshot().reconnectFailures, attempt);
      assert.equal(client.getRecoverySession().reconnectToken, recovery.reconnectToken);
    }
    assert.equal(new Set(lostCandidates).size, 1);
    let ready = wait(client, (event) => event.snapshot.state === "IN_MATCH");
    client.reconnect();
    await ready;
    assert.equal(client.matchId, recovery.matchId);
    assert.equal(client.playerId, recovery.playerId);
    assert.equal(client.getRecoverySession().reconnectToken, lostCandidates[0]);
    const recoveredRevision = client.view.revision;

    const source = readFileSync(path.join(__dirname, "../electron/main.js"), "utf8");
    const writeSource = source.slice(source.indexOf("function queueMultiplayerRecoveryWrite()"), source.indexOf("async function restoreMultiplayerRecovery()"));
    const queueWrite = new Function("multiplayerClient", "fs", "path", "multiplayerRecoveryPath", "appendLog", `
      let multiplayerRecoveryWrite = Promise.resolve();
      ${writeSource}
      return queueMultiplayerRecoveryWrite;
    `)(client, fs, path, filename, (line) => { throw new Error(line); });
    await queueWrite();
    const persisted = JSON.parse(await fs.readFile(filename, "utf8"));
    assert.equal(persisted.reconnectToken, lostCandidates[0]);
    // REQUEST_SYNC is an ordering barrier: the server has processed the durable
    // confirmation before we simulate an application crash/process replacement.
    ready = wait(client, (event) => event.type === "STATE_SNAPSHOT");
    client.requestSync();
    await ready;
    client.suspend();

    stale = new MultiplayerDesktopClient({ WebSocketImpl: WebSocket });
    stale.restoreRecoverySession(recovery);
    ready = wait(stale, (event) => event.type === "ERROR");
    stale.reconnect();
    await ready;
    assert.equal(stale.getSnapshot().canReconnect, false);
    assert.equal(stale.error.code, "INVALID_RECONNECT_TOKEN");

    replacement = new MultiplayerDesktopClient({ WebSocketImpl: WebSocket });
    replacement.restoreRecoverySession(persisted);
    ready = wait(replacement, (event) => event.snapshot.state === "IN_MATCH");
    replacement.reconnect();
    await ready;
    assert.equal(replacement.matchId, recovery.matchId);
    assert.equal(replacement.playerId, recovery.playerId);
    assert.equal(replacement.view.revision, recoveredRevision);
    const publicText = JSON.stringify(publicEvents);
    for (const token of [recovery.reconnectToken, ...lostCandidates]) assert.equal(publicText.includes(token), false);
    process.stdout.write(JSON.stringify({ recovered: true, droppedResponses: 3, durableConfirmation: true }));
  } finally {
    client.disconnect();
    stale?.disconnect();
    replacement?.disconnect();
    await fs.rm(filename, { force: true });
    await fs.rm(`${filename}.tmp`, { force: true });
    await fs.rmdir(directory);
  }
}

run().catch((error) => {
  // Assertion diagnostics can include credentials; emit only the fixed error
  // classification and source location for the parent test's failure report.
  process.stderr.write(`${error.code || error.name}: gateway recovery harness failed\n`);
  process.exitCode = 1;
});
