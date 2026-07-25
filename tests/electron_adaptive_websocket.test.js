"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");

const { createAdaptiveWebSocketClass } = require("../electron/adaptive-websocket");

class FakeSocket {
  static instances = [];

  constructor(url, options = {}) {
    this.url = url;
    this.options = options;
    this.listeners = new Map();
    this.sent = [];
    this.closeCalls = 0;
    FakeSocket.instances.push(this);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener);
  }

  emit(type, event = {}) {
    for (const listener of [...(this.listeners.get(type) || [])]) listener(event);
  }

  send(value) {
    this.sent.push(value);
  }

  close() {
    this.closeCalls += 1;
  }
}

async function settleStartup() {
  await Promise.resolve();
  await Promise.resolve();
}

function makeAdaptive({ proxyResult = "PROXY 127.0.0.1:3067; DIRECT" } = {}) {
  FakeSocket.instances = [];
  const selected = [];
  let resolveCalls = 0;
  const AdaptiveWebSocket = createAdaptiveWebSocketClass({
    WebSocketImpl: FakeSocket,
    resolveProxy: async () => {
      resolveCalls += 1;
      return proxyResult;
    },
    proxyAgentFactory: (proxyUrl) => ({ proxyUrl }),
    attemptTimeoutMs: 5000,
    onRouteSelected: (route) => selected.push(route),
  });
  return { AdaptiveWebSocket, selected, resolveCalls: () => resolveCalls };
}

test("public WSS races direct and system proxy and keeps the fastest handshake", async () => {
  const { AdaptiveWebSocket, selected } = makeAdaptive();
  const socket = new AdaptiveWebSocket("wss://zz.example/multiplayer");
  let opened = 0;
  socket.addEventListener("open", () => { opened += 1; });
  await settleStartup();

  assert.equal(FakeSocket.instances.length, 2);
  const direct = FakeSocket.instances.find((item) => !item.options.agent);
  const proxy = FakeSocket.instances.find((item) => item.options.agent);
  assert.equal(proxy.options.agent.proxyUrl, "http://127.0.0.1:3067");

  proxy.emit("open");
  direct.emit("open");
  socket.send("HELLO");

  assert.equal(opened, 1);
  assert.equal(direct.closeCalls, 1);
  assert.deepEqual(proxy.sent, ["HELLO"]);
  assert.deepEqual(selected, [{ kind: "proxy", proxy: "http://127.0.0.1:3067" }]);
});

test("direct remains eligible even when the system proxy is configured", async () => {
  const { AdaptiveWebSocket, selected } = makeAdaptive();
  const socket = new AdaptiveWebSocket("wss://zz.example/multiplayer");
  await settleStartup();
  const direct = FakeSocket.instances.find((item) => !item.options.agent);
  const proxy = FakeSocket.instances.find((item) => item.options.agent);

  direct.emit("open");

  assert.equal(proxy.closeCalls, 1);
  assert.deepEqual(selected, [{ kind: "direct", proxy: null }]);
  socket.close();
  assert.equal(direct.closeCalls, 1);
  assert.equal(proxy.closeCalls, 1);
});

test("LAN ws connections stay direct and do not query the system proxy", async () => {
  const { AdaptiveWebSocket, resolveCalls, selected } = makeAdaptive();
  const socket = new AdaptiveWebSocket("ws://192.168.1.10:32145");
  await settleStartup();

  assert.equal(resolveCalls(), 0);
  assert.equal(FakeSocket.instances.length, 1);
  FakeSocket.instances[0].emit("open");
  assert.deepEqual(selected, [{ kind: "direct", proxy: null }]);
  socket.close();
});

test("all route failures are surfaced together instead of hiding the cause", async () => {
  const { AdaptiveWebSocket } = makeAdaptive();
  const socket = new AdaptiveWebSocket("wss://zz.example/multiplayer");
  let failure = null;
  socket.addEventListener("error", (event) => { failure = event.error; });
  await settleStartup();
  const direct = FakeSocket.instances.find((item) => !item.options.agent);
  const proxy = FakeSocket.instances.find((item) => item.options.agent);

  direct.emit("error", { error: new Error("direct reset") });
  proxy.emit("error", { error: new Error("proxy refused") });

  assert.ok(failure instanceof Error);
  assert.match(failure.message, /direct: direct reset/);
  assert.match(failure.message, /proxy: proxy refused/);
});
