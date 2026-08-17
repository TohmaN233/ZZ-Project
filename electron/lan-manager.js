"use strict";

const childProcess = require("node:child_process");
const dgramModule = require("node:dgram");
const netModule = require("node:net");
const osModule = require("node:os");
const path = require("node:path");

const SERVICE = "zz-multiplayer";
const PROTOCOL_VERSION = 1;
const DEFAULT_HOST_PORT = 32145;
const DEFAULT_DISCOVERY_PORT = 32146;
const BROADCAST_ADDRESS = "255.255.255.255";
const STARTUP_MARKER = "Serving ZZ multiplayer WebSocket at ";
const DISCOVERY_KEYS = Object.freeze([
  "capacity",
  "host",
  "players",
  "port",
  "protocolVersion",
  "roomCode",
  "serverName",
  "service",
]);

class LanManager {
  #spawn;
  #dgram;
  #net;
  #os;
  #clock;
  #timers;
  #discoveryPort;
  #broadcastIntervalMs;
  #readinessTimeoutMs;
  #stopTimeoutMs;
  #maxPacketBytes;
  #maxLogEntries;
  #maxLogChars;
  #process = null;
  #hostConfig = null;
  #state = "stopped";
  #startPromise = null;
  #stopPromise = null;
  #broadcastSockets = [];
  #probeSocket = null;
  #broadcastInterval = null;
  #roomPacket = null;
  #discoveries = new Set();
  #logs = [];
  #lastError = null;

  constructor({
    spawn = childProcess.spawn,
    dgram = dgramModule,
    net = netModule,
    os = osModule,
    clock = () => Date.now(),
    timers = globalThis,
    discoveryPort = DEFAULT_DISCOVERY_PORT,
    broadcastIntervalMs = 1000,
    readinessTimeoutMs = 15000,
    stopTimeoutMs = 3000,
    maxPacketBytes = 1024,
    maxLogEntries = 40,
    maxLogChars = 2000,
  } = {}) {
    if (typeof spawn !== "function") throw new TypeError("spawn must be a function");
    if (!dgram || typeof dgram.createSocket !== "function") throw new TypeError("dgram.createSocket is required");
    if (!net || typeof net.isIP !== "function") {
      throw new TypeError("net.isIP is required");
    }
    if (!os || typeof os.networkInterfaces !== "function") throw new TypeError("os.networkInterfaces is required");
    if (typeof clock !== "function" && (!clock || typeof clock.now !== "function")) {
      throw new TypeError("clock must be a function or expose now()");
    }
    for (const name of ["setTimeout", "clearTimeout", "setInterval", "clearInterval"]) {
      if (!timers || typeof timers[name] !== "function") throw new TypeError(`timers.${name} is required`);
    }
    this.#spawn = spawn;
    this.#dgram = dgram;
    this.#net = net;
    this.#os = os;
    this.#clock = typeof clock === "function" ? clock : () => clock.now();
    this.#timers = timers;
    this.#discoveryPort = requirePort(discoveryPort, "discoveryPort");
    this.#broadcastIntervalMs = requirePositiveInteger(broadcastIntervalMs, "broadcastIntervalMs");
    this.#readinessTimeoutMs = requirePositiveInteger(readinessTimeoutMs, "readinessTimeoutMs");
    this.#stopTimeoutMs = requirePositiveInteger(stopTimeoutMs, "stopTimeoutMs");
    this.#maxPacketBytes = requirePositiveInteger(maxPacketBytes, "maxPacketBytes");
    this.#maxLogEntries = requirePositiveInteger(maxLogEntries, "maxLogEntries");
    this.#maxLogChars = requirePositiveInteger(maxLogChars, "maxLogChars");
  }

  startHost({
    projectRoot,
    python = "python",
    command,
    args,
    port = DEFAULT_HOST_PORT,
    serverName,
  } = {}) {
    const config = {
      projectRoot: requireAbsolutePath(projectRoot, "projectRoot"),
      python: requireNonBlankString(python, "python"),
      command: command ? requireNonBlankString(command, "command") : null,
      args: Array.isArray(args) ? args.map((value) => String(value)) : null,
      port: requirePort(port, "port"),
      serverName: normalizeServerName(serverName, this.#os),
    };
    if (this.#state === "starting" || this.#state === "running") {
      if (!sameHostConfig(config, this.#hostConfig)) {
        throw new Error("LAN host is already active with different settings");
      }
      return this.#startPromise || Promise.resolve(this.getSnapshot());
    }
    if (this.#state === "stopping") throw new Error("LAN host is stopping");

    this.#hostConfig = config;
    this.#state = "starting";
    this.#lastError = null;
    const executable = config.command || config.python;
    const spawnArgs = config.args || [
      "-m",
      "zz.multiplayer.websocket_server",
      "--host",
      "0.0.0.0",
      "--port",
      String(config.port),
    ];
    let child;
    try {
      child = this.#spawn(executable, spawnArgs, {
        cwd: config.projectRoot,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
      assertChildProcess(child);
    } catch (error) {
      this.#state = "stopped";
      this.#hostConfig = null;
      this.#recordError("SPAWN_FAILED", error);
      return Promise.reject(error);
    }

    this.#process = child;
    child.stdout.on("data", (chunk) => this.#appendLog("stdout", chunk));
    child.stderr.on("data", (chunk) => this.#appendLog("stderr", chunk));
    child.once("error", (error) => this.#handleProcessError(child, error));
    child.once("exit", (code, signal) => this.#handleProcessExit(child, code, signal));

    const startPromise = this.#waitForStartupMarker(child)
      .then(() => {
        if (this.#process !== child || this.#state !== "starting") {
          throw new Error("LAN host stopped before becoming ready");
        }
        this.#state = "running";
        this.#startProbeListener();
        return this.getSnapshot();
      })
      .catch((error) => {
        if (this.#process === child) {
          this.#recordError("READINESS_FAILED", error);
          this.#clearBroadcast();
          this.#process = null;
          try {
            child.kill();
          } catch (killError) {
            this.#appendLog("system", `Failed to stop host: ${errorMessage(killError)}`);
          }
        }
        if (this.#state !== "stopping") this.#state = "stopped";
        this.#hostConfig = null;
        throw error;
      })
      .finally(() => {
        if (this.#startPromise === startPromise) this.#startPromise = null;
      });
    this.#startPromise = startPromise;
    return startPromise;
  }

  stopHost() {
    if (this.#stopPromise) return this.#stopPromise;
    this.#clearBroadcast();
    this.#stopProbeListener();
    this.#closeDiscoveries();
    this.#roomPacket = null;
    const child = this.#process;
    this.#process = null;
    this.#hostConfig = null;
    this.#state = "stopping";

    if (!child) {
      this.#state = "stopped";
      return Promise.resolve(this.getSnapshot());
    }

    const stopPromise = new Promise((resolve) => {
      let finished = false;
      let timeout = null;
      const finish = () => {
        if (finished) return;
        finished = true;
        if (timeout !== null) this.#timers.clearTimeout(timeout);
        child.removeListener("exit", finish);
        child.removeListener("close", finish);
        this.#state = "stopped";
        resolve(this.getSnapshot());
      };
      child.once("exit", finish);
      child.once("close", finish);
      timeout = this.#timers.setTimeout(finish, this.#stopTimeoutMs);
      try {
        child.kill();
      } catch (error) {
        this.#appendLog("system", `Failed to stop host: ${errorMessage(error)}`);
        finish();
      }
    }).finally(() => {
      if (this.#stopPromise === stopPromise) this.#stopPromise = null;
    });
    this.#stopPromise = stopPromise;
    return stopPromise;
  }

  updateRoom(room) {
    if (this.#state !== "running" || !this.#hostConfig || !this.#process) {
      throw new Error("LAN host must be running before advertising a room");
    }
    const packet = makeRoomPacket(room, this.#hostConfig, this.#localAddresses());
    const encoded = Buffer.from(JSON.stringify(packet), "utf8");
    if (encoded.length > this.#maxPacketBytes) throw new RangeError("discovery packet is too large");
    this.#roomPacket = packet;
    if (!this.#broadcastSockets.length) {
      this.#startBroadcastSocket();
    } else {
      this.#sendBroadcast();
    }
    return this.getSnapshot();
  }

  clearRoom() {
    this.#roomPacket = null;
    this.#clearBroadcast();
    return this.getSnapshot();
  }

  discover({ timeoutMs = 4000 } = {}) {
    const duration = requirePositiveInteger(timeoutMs, "timeoutMs");
    const rooms = new Map();
    const sockets = [];

    return new Promise((resolve, reject) => {
      const discovery = {
        sockets,
        timeout: null,
        done: false,
        finish: (error) => {
          if (discovery.done) return;
          discovery.done = true;
          if (discovery.timeout !== null) this.#timers.clearTimeout(discovery.timeout);
          this.#discoveries.delete(discovery);
          for (const socket of sockets) closeSocket(socket);
          if (error) {
            reject(error);
            return;
          }
          resolve([...rooms.values()].sort(compareDiscoveredRooms));
        },
      };
      this.#discoveries.add(discovery);
      const onMessage = (message, rinfo) => {
        const room = parseDiscoveryPacket(message, rinfo, this.#net, this.#maxPacketBytes);
        if (!room) return;
        rooms.set(`${room.serverName}:${room.port}:${room.roomCode}`, room);
      };
      const bindAddresses = ["0.0.0.0", ...this.#localAddresses()];
      for (const address of bindAddresses) {
        const socket = this.#dgram.createSocket("udp4");
        assertDatagramSocket(socket);
        sockets.push(socket);
        socket.on("message", onMessage);
        socket.once("error", (error) => {
          if (address === "0.0.0.0") discovery.finish(error);
        });
        try {
          socket.bind({ port: address === "0.0.0.0" ? this.#discoveryPort : 0, address, exclusive: false }, () => {
            try {
              socket.setBroadcast(true);
              const probe = Buffer.from(JSON.stringify({ service: SERVICE, type: "probe" }), "utf8");
              socket.send(probe, this.#discoveryPort, BROADCAST_ADDRESS);
            } catch (_error) {
              // Keep listening for host broadcasts even if a probe cannot be sent.
            }
          });
        } catch (error) {
          if (address === "0.0.0.0") discovery.finish(error);
        }
      }
      discovery.timeout = this.#timers.setTimeout(() => discovery.finish(), duration);
    });
  }

  getManualEndpoints() {
    const port = this.#hostConfig?.port ?? DEFAULT_HOST_PORT;
    const addresses = this.#localAddresses();
    return {
      localUrl: `ws://127.0.0.1:${port}`,
      addresses,
      urls: addresses.map((address) => `ws://${address}:${port}`),
    };
  }

  getSnapshot() {
    return {
      state: this.#state,
      pid: Number.isInteger(this.#process?.pid) ? this.#process.pid : null,
      port: this.#hostConfig?.port ?? null,
      serverName: this.#hostConfig?.serverName ?? null,
      room: this.#roomPacket ? cloneJson(this.#roomPacket) : null,
      manualEndpoints: this.getManualEndpoints(),
      log: this.#logs.map((entry) => ({ ...entry })),
      lastError: this.#lastError ? { ...this.#lastError } : null,
      broadcasting: this.#broadcastSockets.length > 0,
      discovering: this.#discoveries.size,
    };
  }

  #startBroadcastSocket() {
    const bindAddresses = this.#localAddresses();
    const targets = bindAddresses.length ? bindAddresses : ["0.0.0.0"];
    for (const address of targets) {
      const socket = this.#dgram.createSocket("udp4");
      assertDatagramSocket(socket);
      this.#broadcastSockets.push(socket);
      socket.once("error", (error) => {
        if (!this.#broadcastSockets.includes(socket)) return;
        this.#recordError("BROADCAST_ERROR", error);
        this.#clearBroadcast();
      });
      socket.bind({ address, port: 0 }, () => {
        if (!this.#broadcastSockets.includes(socket)) return;
        socket.setBroadcast(true);
        this.#sendBroadcastOn(socket);
      });
    }
    this.#broadcastInterval = this.#timers.setInterval(
      () => this.#sendBroadcast(),
      this.#broadcastIntervalMs,
    );
  }

  #sendBroadcast() {
    for (const socket of this.#broadcastSockets) this.#sendBroadcastOn(socket);
  }

  #sendBroadcastOn(socket) {
    if (!socket || !this.#roomPacket) return;
    const encoded = Buffer.from(JSON.stringify(this.#roomPacket), "utf8");
    socket.send(
      encoded,
      this.#discoveryPort,
      BROADCAST_ADDRESS,
      (error) => {
        if (error) this.#recordError("BROADCAST_SEND_FAILED", error);
      },
    );
  }

  #startProbeListener() {
    if (this.#probeSocket) return;
    const socket = this.#dgram.createSocket("udp4");
    assertDatagramSocket(socket);
    this.#probeSocket = socket;
    socket.on("message", (message, rinfo) => {
      if (!this.#roomPacket || !rinfo || this.#net.isIP(rinfo.address) !== 4) return;
      let value;
      try {
        value = JSON.parse(message.toString("utf8"));
      } catch (_error) {
        return;
      }
      if (!value || value.service !== SERVICE || value.type !== "probe") return;
      const encoded = Buffer.from(JSON.stringify(this.#roomPacket), "utf8");
      socket.send(encoded, rinfo.port, rinfo.address);
    });
    socket.once("error", (error) => {
      if (this.#probeSocket !== socket) return;
      this.#recordError("PROBE_LISTEN_ERROR", error);
      this.#stopProbeListener();
    });
    try {
      socket.bind({ port: this.#discoveryPort, address: "0.0.0.0", exclusive: false });
    } catch (error) {
      this.#recordError("PROBE_LISTEN_ERROR", error);
      this.#stopProbeListener();
    }
  }

  #stopProbeListener() {
    if (!this.#probeSocket) return;
    closeSocket(this.#probeSocket);
    this.#probeSocket = null;
  }

  #clearBroadcast() {
    if (this.#broadcastInterval !== null) {
      this.#timers.clearInterval(this.#broadcastInterval);
      this.#broadcastInterval = null;
    }
    for (const socket of this.#broadcastSockets) closeSocket(socket);
    this.#broadcastSockets = [];
  }

  #closeDiscoveries() {
    for (const discovery of [...this.#discoveries]) discovery.finish();
  }

  #waitForStartupMarker(child) {
    return new Promise((resolve, reject) => {
      let done = false;
      const finish = (error) => {
        if (done) return;
        done = true;
        this.#timers.clearTimeout(timeout);
        child.stdout.removeListener("data", onData);
        child.removeListener("error", onError);
        child.removeListener("exit", onExit);
        error ? reject(error) : resolve();
      };
      const onData = (chunk) => {
        if (String(chunk ?? "").includes(STARTUP_MARKER)) finish();
      };
      const onError = (error) => finish(error);
      const onExit = (code, signal) => finish(new Error(
        `LAN host exited before readiness marker (${code ?? signal ?? "unknown"})`,
      ));
      const timeout = this.#timers.setTimeout(
        () => finish(new Error("Timed out waiting for LAN host readiness marker")),
        this.#readinessTimeoutMs,
      );
      child.stdout.on("data", onData);
      child.once("error", onError);
      child.once("exit", onExit);
    });
  }

  #handleProcessError(child, error) {
    if (this.#process !== child) return;
    this.#recordError("PROCESS_ERROR", error);
    this.#process = null;
    this.#hostConfig = null;
    this.#state = "stopped";
    this.#clearBroadcast();
    this.#stopProbeListener();
  }

  #handleProcessExit(child, code, signal) {
    if (this.#process !== child) return;
    const error = new Error(`LAN host exited before shutdown (${code ?? signal ?? "unknown"})`);
    this.#recordError("PROCESS_EXITED", error);
    this.#process = null;
    this.#hostConfig = null;
    this.#state = "stopped";
    this.#clearBroadcast();
    this.#stopProbeListener();
  }

  #appendLog(stream, chunk) {
    const text = String(chunk ?? "").trim();
    if (!text) return;
    this.#logs.push({
      at: this.#now(),
      stream,
      text: text.slice(0, this.#maxLogChars),
    });
    if (this.#logs.length > this.#maxLogEntries) {
      this.#logs.splice(0, this.#logs.length - this.#maxLogEntries);
    }
  }

  #recordError(code, error) {
    this.#lastError = { code, message: errorMessage(error), at: this.#now() };
    this.#appendLog("system", `${code}: ${this.#lastError.message}`);
  }

  #localAddresses() {
    const addresses = new Set();
    const interfaces = this.#os.networkInterfaces() || {};
    for (const records of Object.values(interfaces)) {
      if (!Array.isArray(records)) continue;
      for (const record of records) {
        if (!record || record.internal === true) continue;
        const family = record.family;
        if (family !== "IPv4" && family !== 4) continue;
        if (typeof record.address !== "string" || this.#net.isIP(record.address) !== 4) continue;
        if (record.address.startsWith("127.")) continue;
        addresses.add(record.address);
      }
    }
    return [...addresses].sort();
  }

  #now() {
    const value = Number(this.#clock());
    return Number.isFinite(value) ? value : Date.now();
  }
}

function makeRoomPacket(room, hostConfig, localAddresses) {
  if (!isPlainObject(room)) throw new TypeError("room must be an object");
  const capacity = requirePositiveInteger(room.capacity, "room.capacity");
  const players = requireNonNegativeInteger(room.players, "room.players");
  if (players > capacity) throw new RangeError("room.players must not exceed room.capacity");
  return {
    service: SERVICE,
    protocolVersion: PROTOCOL_VERSION,
    serverName: hostConfig.serverName,
    host: localAddresses[0] || "",
    port: hostConfig.port,
    roomCode: requireRoomCode(room.roomCode),
    players,
    capacity,
  };
}

function parseDiscoveryPacket(message, rinfo, net, maxPacketBytes) {
  if (!Buffer.isBuffer(message) || message.length === 0 || message.length > maxPacketBytes) return null;
  if (!rinfo || typeof rinfo.address !== "string" || net.isIP(rinfo.address) !== 4) return null;
  let value;
  try {
    value = JSON.parse(message.toString("utf8"));
  } catch (_) {
    return null;
  }
  if (!isPlainObject(value)) return null;
  const keys = Object.keys(value).sort();
  if (keys.length !== DISCOVERY_KEYS.length || keys.some((key, index) => key !== DISCOVERY_KEYS[index])) return null;
  if (value.service !== SERVICE || value.protocolVersion !== PROTOCOL_VERSION) return null;
  if (typeof value.serverName !== "string" || !value.serverName.trim() || value.serverName.length > 80) return null;
  if (typeof value.host !== "string" || value.host.length > 45) return null;
  if (!Number.isInteger(value.port) || value.port < 1 || value.port > 65535) return null;
  if (typeof value.roomCode !== "string" || !/^[A-Z0-9]{6}$/.test(value.roomCode)) return null;
  if (!Number.isInteger(value.capacity) || value.capacity < 1 || value.capacity > 16) return null;
  if (!Number.isInteger(value.players) || value.players < 0 || value.players > value.capacity) return null;
  return {
    service: SERVICE,
    protocolVersion: PROTOCOL_VERSION,
    serverName: value.serverName,
    host: rinfo.address,
    port: value.port,
    roomCode: value.roomCode,
    players: value.players,
    capacity: value.capacity,
  };
}

function normalizeServerName(value, os) {
  if (value === undefined || value === null || value === "") {
    const fallback = typeof os.hostname === "function" ? os.hostname() : "";
    return requireServerName(fallback || "ZZ LAN Server");
  }
  return requireServerName(value);
}

function requireServerName(value) {
  const normalized = requireNonBlankString(value, "serverName").trim();
  if (normalized.length > 80) throw new RangeError("serverName must be at most 80 characters");
  return normalized;
}

function requireRoomCode(value) {
  if (typeof value !== "string" || !/^[A-Z0-9]{6}$/.test(value)) {
    throw new TypeError("room.roomCode must contain exactly six uppercase letters or digits");
  }
  return value;
}

function requireAbsolutePath(value, label) {
  const normalized = requireNonBlankString(value, label);
  if (!path.isAbsolute(normalized)) throw new TypeError(`${label} must be an absolute path`);
  return path.resolve(normalized);
}

function requireNonBlankString(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new TypeError(`${label} must be a non-empty string`);
  return value;
}

function requirePort(value, label) {
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new RangeError(`${label} must be an integer from 1 to 65535`);
  }
  return value;
}

function requirePositiveInteger(value, label) {
  if (!Number.isInteger(value) || value <= 0) throw new RangeError(`${label} must be a positive integer`);
  return value;
}

function requireNonNegativeInteger(value, label) {
  if (!Number.isInteger(value) || value < 0) throw new RangeError(`${label} must be a non-negative integer`);
  return value;
}

function sameHostConfig(left, right) {
  return Boolean(right)
    && left.projectRoot === right.projectRoot
    && left.python === right.python
    && left.command === right.command
    && JSON.stringify(left.args) === JSON.stringify(right.args)
    && left.port === right.port
    && left.serverName === right.serverName;
}

function assertChildProcess(child) {
  if (
    !child
    || typeof child.once !== "function"
    || typeof child.removeListener !== "function"
    || typeof child.kill !== "function"
    || !child.stdout
    || typeof child.stdout.on !== "function"
    || !child.stderr
    || typeof child.stderr.on !== "function"
  ) {
    throw new TypeError("spawn must return a child process with piped stdout and stderr");
  }
}

function assertDatagramSocket(socket) {
  if (
    !socket
    || typeof socket.on !== "function"
    || typeof socket.once !== "function"
    || typeof socket.bind !== "function"
    || typeof socket.send !== "function"
    || typeof socket.close !== "function"
  ) {
    throw new TypeError("dgram.createSocket must return a UDP socket");
  }
}

function closeSocket(socket) {
  try {
    socket.close();
  } catch (error) {
    if (error?.code !== "ERR_SOCKET_DGRAM_NOT_RUNNING") throw error;
  }
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function compareDiscoveredRooms(left, right) {
  return left.serverName.localeCompare(right.serverName)
    || left.host.localeCompare(right.host)
    || left.port - right.port
    || left.roomCode.localeCompare(right.roomCode);
}

module.exports = {
  DEFAULT_DISCOVERY_PORT,
  DEFAULT_HOST_PORT,
  LanManager,
  PROTOCOL_VERSION,
  SERVICE,
};
