"use strict";

const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { test } = require("node:test");

const {
  LanManager,
  SERVICE,
} = require("../electron/lan-manager");

class FakeChild extends EventEmitter {
  constructor(pid = 7001) {
    super();
    this.pid = pid;
    this.stdout = new EventEmitter();
    this.stderr = new EventEmitter();
    this.killCalls = 0;
  }

  kill() {
    this.killCalls += 1;
    queueMicrotask(() => this.emit("exit", 0, null));
    return true;
  }
}

class FakeUdpSocket extends EventEmitter {
  constructor() {
    super();
    this.bindCalls = [];
    this.sent = [];
    this.broadcast = false;
    this.closeCalls = 0;
  }

  bind(...args) {
    this.bindCalls.push(args);
    const callback = args.find((value) => typeof value === "function");
    if (callback) queueMicrotask(callback);
  }

  setBroadcast(value) {
    this.broadcast = value;
  }

  send(message, port, address, callback) {
    this.sent.push({ message: Buffer.from(message), port, address });
    if (callback) callback(null);
  }

  close() {
    this.closeCalls += 1;
  }
}

class FakeTimers {
  constructor() {
    this.nextId = 1;
    this.timeouts = new Map();
    this.intervals = new Map();
    this.clearedTimeouts = [];
    this.clearedIntervals = [];
  }

  setTimeout(callback) {
    const id = this.nextId++;
    this.timeouts.set(id, callback);
    return id;
  }

  clearTimeout(id) {
    this.clearedTimeouts.push(id);
    this.timeouts.delete(id);
  }

  setInterval(callback) {
    const id = this.nextId++;
    this.intervals.set(id, callback);
    return id;
  }

  clearInterval(id) {
    this.clearedIntervals.push(id);
    this.intervals.delete(id);
  }

  runTimeout(id) {
    const callback = this.timeouts.get(id);
    this.timeouts.delete(id);
    callback?.();
  }

  runAllTimeouts() {
    for (const id of [...this.timeouts.keys()]) this.runTimeout(id);
  }
}

function makeDependencies({ startupMarker = "auto" } = {}) {
  const children = [];
  const spawnCalls = [];
  const spawn = (...args) => {
    spawnCalls.push(args);
    const child = new FakeChild(7000 + children.length);
    children.push(child);
    if (startupMarker === "auto") {
      queueMicrotask(() => child.stdout.emit(
        "data",
        "Serving ZZ multiplayer WebSocket at ws://0.0.0.0:32145/",
      ));
    }
    return child;
  };
  const net = {
    isIP(address) {
      return /^(?:\d{1,3}\.){3}\d{1,3}$/.test(address) ? 4 : 0;
    },
  };
  const udpSockets = [];
  const dgram = {
    createSocket(type) {
      assert.equal(type, "udp4");
      const socket = new FakeUdpSocket();
      udpSockets.push(socket);
      return socket;
    },
  };
  const os = {
    hostname: () => "test-host",
    networkInterfaces: () => ({
      Loopback: [{ address: "127.0.0.1", family: "IPv4", internal: true }],
      Ethernet: [
        { address: "192.168.50.8", family: "IPv4", internal: false },
        { address: "fe80::1", family: "IPv6", internal: false },
      ],
      VPN: [{ address: "10.9.0.3", family: 4, internal: false }],
    }),
  };
  return { children, dgram, net, os, spawn, spawnCalls, udpSockets };
}

async function startReadyHost(manager, options = {}) {
  return manager.startHost({
    projectRoot: "D:\\Games\\ZZ-Project",
    serverName: "Alice LAN",
    ...options,
  });
}

test("construction has no side effects and startHost explicitly binds the authoritative server", async () => {
  const deps = makeDependencies();
  const manager = new LanManager(deps);

  assert.equal(deps.spawnCalls.length, 0);
  assert.equal(deps.udpSockets.length, 0);
  const snapshot = await startReadyHost(manager, { python: "py", port: 32222 });

  assert.equal(deps.spawnCalls.length, 1);
  assert.deepEqual(deps.spawnCalls[0], [
    "py",
    ["-m", "zz.multiplayer.websocket_server", "--host", "0.0.0.0", "--port", "32222"],
    {
      cwd: "D:\\Games\\ZZ-Project",
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  ]);
  assert.equal(snapshot.state, "running");
  assert.equal(snapshot.pid, 7000);
  assert.equal(snapshot.manualEndpoints.localUrl, "ws://127.0.0.1:32222");
  assert.deepEqual(snapshot.manualEndpoints.addresses, ["10.9.0.3", "192.168.50.8"]);
  assert.deepEqual(snapshot.manualEndpoints.urls, [
    "ws://10.9.0.3:32222",
    "ws://192.168.50.8:32222",
  ]);
});

test("same start is idempotent, conflicting start is rejected, and logs stay bounded", async () => {
  const deps = makeDependencies();
  let now = 100;
  const manager = new LanManager({ ...deps, clock: () => now++, maxLogEntries: 3, maxLogChars: 8 });
  await startReadyHost(manager);
  await startReadyHost(manager);
  assert.equal(deps.spawnCalls.length, 1);
  assert.throws(
    () => manager.startHost({
      projectRoot: "D:\\Games\\ZZ-Project",
      serverName: "Alice LAN",
      port: 33333,
    }),
    /already active with different settings/,
  );

  for (const line of ["first", "second", "third", "fourth-long-value"]) {
    deps.children[0].stdout.emit("data", line);
  }
  assert.deepEqual(manager.getSnapshot().log.map((entry) => entry.text), ["second", "third", "fourth-l"]);
});

test("room broadcasts use an exact privacy-safe schema and update without opening another socket", async () => {
  const deps = makeDependencies();
  const timers = new FakeTimers();
  const manager = new LanManager({ ...deps, timers });
  await startReadyHost(manager);

  manager.updateRoom({
    roomCode: "ABC123",
    players: 1,
    capacity: 2,
    deck: { SECRET: 3 },
    reconnectToken: "secret-token",
    view: { hand: ["secret-card"] },
  });
  await Promise.resolve();
  const socket = deps.udpSockets[0];
  assert.equal(socket.broadcast, true);
  assert.equal(socket.bindCalls.length, 1);
  assert.equal(socket.sent.length >= 1, true);
  const packet = JSON.parse(socket.sent.at(-1).message.toString("utf8"));
  assert.deepEqual(Object.keys(packet), [
    "service",
    "protocolVersion",
    "serverName",
    "host",
    "port",
    "roomCode",
    "players",
    "capacity",
  ]);
  assert.deepEqual(packet, {
    service: SERVICE,
    protocolVersion: 1,
    serverName: "Alice LAN",
    host: "10.9.0.3",
    port: 32145,
    roomCode: "ABC123",
    players: 1,
    capacity: 2,
  });
  assert.equal(JSON.stringify(packet).includes("secret"), false);
  assert.equal(socket.sent.at(-1).port, 32146);
  assert.equal(socket.sent.at(-1).address, "255.255.255.255");

  manager.updateRoom({ roomCode: "ABC123", players: 2, capacity: 2 });
  assert.equal(deps.udpSockets.length, 1);
  assert.equal(JSON.parse(socket.sent.at(-1).message).players, 2);
  assert.equal(timers.intervals.size, 1);

  const cleared = manager.clearRoom();
  assert.equal(cleared.room, null);
  assert.equal(cleared.broadcasting, false);
  assert.equal(socket.closeCalls, 1);
  assert.equal(timers.intervals.size, 0);
});

test("discover validates size and exact schema, deduplicates, and trusts only rinfo.address", async () => {
  const deps = makeDependencies();
  const timers = new FakeTimers();
  const manager = new LanManager({ ...deps, timers, maxPacketBytes: 512 });
  const discovery = manager.discover({ timeoutMs: 500 });
  const socket = deps.udpSockets[0];
  assert.deepEqual(socket.bindCalls[0][0], { port: 32146, address: "0.0.0.0", exclusive: false });

  const valid = {
    service: SERVICE,
    protocolVersion: 1,
    serverName: "Remote LAN",
    host: "6.6.6.6",
    port: 32145,
    roomCode: "ZZ1234",
    players: 1,
    capacity: 2,
  };
  socket.emit("message", Buffer.from(JSON.stringify(valid)), { address: "192.168.50.99" });
  socket.emit("message", Buffer.from(JSON.stringify({ ...valid, players: 2 })), { address: "192.168.50.99" });
  socket.emit("message", Buffer.from(JSON.stringify({ ...valid, players: 2 })), { address: "192.168.50.88" });
  socket.emit("message", Buffer.from(JSON.stringify({ ...valid, deck: { SECRET: 3 } })), { address: "192.168.50.98" });
  socket.emit("message", Buffer.from("not-json"), { address: "192.168.50.97" });
  socket.emit("message", Buffer.alloc(513, 65), { address: "192.168.50.96" });
  socket.emit("message", Buffer.from(JSON.stringify({ ...valid, players: 3 })), { address: "192.168.50.95" });
  socket.emit("message", Buffer.from(JSON.stringify(valid)), { address: "not-an-ip" });

  timers.runAllTimeouts();
  const rooms = await discovery;
  assert.deepEqual(rooms, [{
    service: SERVICE,
    protocolVersion: 1,
    serverName: "Remote LAN",
    host: "192.168.50.88",
    port: 32145,
    roomCode: "ZZ1234",
    players: 2,
    capacity: 2,
  }]);
  assert.equal(socket.closeCalls, 1);
  assert.equal(manager.getSnapshot().discovering, 0);
});

test("stopHost closes broadcasts and discoveries, kills once, and is idempotent", async () => {
  const deps = makeDependencies();
  const timers = new FakeTimers();
  const manager = new LanManager({ ...deps, timers });
  await startReadyHost(manager);
  manager.updateRoom({ roomCode: "ABC123", players: 1, capacity: 2 });
  await Promise.resolve();
  const broadcastSocket = deps.udpSockets[0];
  const discoveryPromise = manager.discover({ timeoutMs: 1000 });
  const discoverySocket = deps.udpSockets[1];

  const stopped = await manager.stopHost();
  assert.equal(stopped.state, "stopped");
  assert.equal(stopped.pid, null);
  assert.equal(stopped.broadcasting, false);
  assert.equal(stopped.discovering, 0);
  assert.equal(deps.children[0].killCalls, 1);
  assert.equal(broadcastSocket.closeCalls, 1);
  assert.equal(discoverySocket.closeCalls, 1);
  assert.equal(timers.intervals.size, 0);
  assert.deepEqual(await discoveryPromise, []);

  const again = await manager.stopHost();
  assert.equal(again.state, "stopped");
  assert.equal(deps.children[0].killCalls, 1);
  const raw = JSON.stringify(again);
  assert.equal(raw.includes("_handle"), false);
  assert.equal(raw.includes("socket"), false);
  assert.equal(raw.includes("process"), false);
});

test("process error and early exit reject readiness and remove runtime resources", async () => {
  const first = makeDependencies({ startupMarker: "manual" });
  const timers = new FakeTimers();
  const manager = new LanManager({ ...first, timers });
  const starting = startReadyHost(manager);
  await Promise.resolve();
  first.children[0].emit("error", new Error("spawned process failed"));
  await assert.rejects(starting, /spawned process failed/);
  assert.equal(manager.getSnapshot().state, "stopped");
  assert.equal(manager.getSnapshot().pid, null);
  assert.equal(timers.timeouts.size, 0);

  const second = makeDependencies({ startupMarker: "manual" });
  const manager2 = new LanManager({ ...second, timers: new FakeTimers() });
  const starting2 = startReadyHost(manager2);
  await Promise.resolve();
  second.children[0].emit("exit", 7, null);
  await assert.rejects(starting2, /exited before readiness marker/);
  assert.equal(manager2.getSnapshot().state, "stopped");
});

test("unexpected host exit stops an active room broadcast", async () => {
  const deps = makeDependencies();
  const timers = new FakeTimers();
  const manager = new LanManager({ ...deps, timers });
  await startReadyHost(manager);
  manager.updateRoom({ roomCode: "ABC123", players: 1, capacity: 2 });
  await Promise.resolve();
  const socket = deps.udpSockets[0];

  deps.children[0].emit("exit", 9, null);

  const snapshot = manager.getSnapshot();
  assert.equal(snapshot.state, "stopped");
  assert.equal(snapshot.pid, null);
  assert.equal(snapshot.broadcasting, false);
  assert.equal(socket.closeCalls, 1);
  assert.equal(timers.intervals.size, 0);
});

test("readiness waits for the spawned server marker before marking the host running", async () => {
  const deps = makeDependencies({ startupMarker: "manual" });
  const timers = new FakeTimers();
  const manager = new LanManager({ ...deps, timers, readinessTimeoutMs: 1000 });
  const starting = startReadyHost(manager);
  await Promise.resolve();
  assert.equal(manager.getSnapshot().state, "starting");
  assert.equal(timers.timeouts.size, 1);

  deps.children[0].stdout.emit(
    "data",
    "Serving ZZ multiplayer WebSocket at ws://0.0.0.0:32145/",
  );
  const snapshot = await starting;
  assert.equal(snapshot.state, "running");
  assert.equal(timers.timeouts.size, 0);
});
