"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");
const { test } = require("node:test");
const { buildSync } = require("esbuild");

const {
  LOCAL_COMPATIBILITY,
  MultiplayerClientState,
  MultiplayerDesktopClient,
} = require("../electron/multiplayer-client");

class FakeWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.sent = [];
    this.closeCalls = 0;
    this.listeners = new Map();
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener);
  }

  send(raw) {
    this.sent.push(raw);
  }

  close() {
    this.closeCalls += 1;
  }

  emit(type, event = {}) {
    for (const listener of [...(this.listeners.get(type) || [])]) listener(event);
  }

  receive(message) {
    this.emit("message", { data: JSON.stringify(message) });
  }

  listenerCount() {
    return [...this.listeners.values()].reduce((total, listeners) => total + listeners.size, 0);
  }
}

function makeClient() {
  FakeWebSocket.instances = [];
  let nextId = 0;
  const client = new MultiplayerDesktopClient({
    WebSocketImpl: FakeWebSocket,
    uuidFactory: () => `id-${++nextId}`,
  });
  return {
    client,
    socket: () => FakeWebSocket.instances[0],
    sockets: () => FakeWebSocket.instances,
  };
}

function serverMessage(type, payload, metadata = {}) {
  const compatiblePayload = type === "WELCOME"
    ? { ...payload, compatibility: LOCAL_COMPATIBILITY }
    : payload;
  return {
    protocolVersion: LOCAL_COMPATIBILITY.protocolVersion,
    messageId: `server-${type}`,
    type,
    payload: compatiblePayload,
    ...metadata,
  };
}

function connectClient(client, socket) {
  client.connect({ url: "ws://127.0.0.1:8766/multiplayer" });
  socket().emit("open");
  socket().receive(serverMessage("WELCOME", { connectionId: "connection-1" }));
}

function enterRoom(client, socket, status = "READY_CHECK") {
  socket().receive(serverMessage("ROOM_STATE", {
    roomId: "room-1",
    roomCode: "ABC123",
    status,
    playerId: "player-1",
  }));
}

function startMatch(client, socket, revision = 4) {
  socket().receive(serverMessage("MATCH_STARTED", {
    matchId: "match-1",
    playerId: "player-1",
    view: { revision, gameOver: false, hand: ["hidden-safe"] },
  }, { matchId: "match-1", revision }));
}

function enterRecoverableRoom(client, socket, reconnectToken = "token-1", status = "READY_CHECK") {
  socket().receive(serverMessage("ROOM_STATE", {
    roomId: "room-1",
    roomCode: "ABC123",
    status,
    playerId: "player-1",
    reconnectToken,
  }));
}

test("connect has explicit states and sends HELLO exactly once after open", () => {
  const { client, socket } = makeClient();
  const states = [];
  client.onEvent((event) => {
    if (event.type === "STATE_CHANGED") states.push(event.snapshot.state);
  });

  client.connect({ url: "ws://example.test/multiplayer" });
  assert.equal(client.state, MultiplayerClientState.CONNECTING);
  assert.equal(socket().sent.length, 0);
  assert.throws(() => client.connect({ url: "ws://example.test/again" }), /cannot connect/);

  socket().emit("open");
  socket().emit("open");
  assert.equal(client.state, MultiplayerClientState.CONNECTED);
  assert.equal(socket().sent.length, 1);
  assert.deepEqual(JSON.parse(socket().sent[0]), {
    protocolVersion: LOCAL_COMPATIBILITY.protocolVersion,
    messageId: "id-1",
    type: "HELLO",
    payload: {
      applicationVersion: LOCAL_COMPATIBILITY.applicationVersion,
      rulesVersion: LOCAL_COMPATIBILITY.rulesVersion,
      cardDatabaseChecksum: LOCAL_COMPATIBILITY.cardDatabaseChecksum,
    },
  });
  assert.deepEqual(states, ["CONNECTING", "CONNECTED"]);
});

test("unbundled and bundled clients load the same static compatibility manifest", () => {
  const result = buildSync({
    entryPoints: [path.join(__dirname, "../electron/multiplayer-client.js")],
    bundle: true,
    platform: "node",
    format: "cjs",
    write: false,
  });
  const bundledModule = new Module("bundled-multiplayer-client");
  bundledModule.filename = path.join(__dirname, "bundled-multiplayer-client.cjs");
  bundledModule.paths = Module._nodeModulePaths(__dirname);
  bundledModule._compile(result.outputFiles[0].text, bundledModule.filename);

  assert.deepEqual(bundledModule.exports.LOCAL_COMPATIBILITY, LOCAL_COMPATIBILITY);
});

test("fatal compatibility errors are clear and do not expose server details", () => {
  const { client, socket } = makeClient();
  client.connect({ url: "ws://example.test/multiplayer" });
  socket().emit("open");
  socket().receive(serverMessage("ERROR", {
    code: "INCOMPATIBLE_GAME_VERSION",
    message: "Client game version is incompatible with this server.",
    fatal: true,
  }));

  assert.equal(client.state, MultiplayerClientState.ERROR);
  assert.deepEqual(client.error, {
    code: "INCOMPATIBLE_GAME_VERSION",
    message: "Client game version is incompatible with this server.",
    fatal: true,
  });
  assert.equal(JSON.stringify(client.error).includes("cardDatabaseChecksum"), false);
});

test("standard MessageEvent prototype data is accepted", () => {
  const { client, socket } = makeClient();
  client.connect({ url: "ws://example.test/multiplayer" });
  socket().emit("open");
  const message = serverMessage("WELCOME", { connectionId: "connection-prototype" });
  const event = Object.create({ data: JSON.stringify(message) });

  socket().emit("message", event);

  assert.equal(client.connectionId, "connection-prototype");
  assert.equal(client.state, MultiplayerClientState.CONNECTED);
});

test("connect rejects non-WebSocket URLs without constructing a socket", () => {
  const { client } = makeClient();

  assert.throws(() => client.connect({ url: "https://example.test" }), /ws:\/\/ or wss:\/\//);
  assert.throws(() => client.connect({ url: "not a url" }), /valid ws:\/\/ or wss:\/\/ URL/);
  assert.equal(client.state, MultiplayerClientState.OFFLINE);
  assert.equal(FakeWebSocket.instances.length, 0);
});

test("room commands are state-gated and use only the protocol command set", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);

  client.createRoom({ displayName: "Alice" });
  assert.equal(JSON.parse(socket().sent.at(-1)).type, "CREATE_ROOM");
  enterRoom(client, socket);
  assert.equal(client.state, MultiplayerClientState.IN_ROOM);
  assert.equal(client.playerId, "player-1");
  assert.equal(client.room.roomCode, "ABC123");

  client.selectDeck({
    deck: { CARD_001: 3 },
    forces: ["F01", "F02"],
    profile: { codemanId: "codeman-1", playmatId: "playmat-1" },
  });
  assert.deepEqual(JSON.parse(socket().sent.at(-1)).payload.profile, {
    codemanId: "codeman-1",
    playmatId: "playmat-1",
  });
  client.setReady({ ready: true });
  client.requestSync();
  client.leaveRoom();
  assert.deepEqual(socket().sent.slice(-4).map((raw) => JSON.parse(raw).type), [
    "SELECT_DECK",
    "SET_READY",
    "REQUEST_SYNC",
    "LEAVE_ROOM",
  ]);
  assert.equal(Object.prototype.hasOwnProperty.call(client, "socket"), false);
  assert.throws(() => client.createRoom({ displayName: "Again" }), /not allowed from IN_ROOM/);
});

test("opening choice is allowed only while the match is starting", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRoom(client, socket, "STARTING");

  client.selectOpeningChoice({ choice: "rock" });

  assert.deepEqual(JSON.parse(socket().sent.at(-1)), {
    protocolVersion: LOCAL_COMPATIBILITY.protocolVersion,
    messageId: "id-2",
    type: "SELECT_OPENING_CHOICE",
    payload: { choice: "rock" },
  });
  assert.throws(() => client.selectOpeningChoice({ choice: "fire" }), /rock, paper, or scissors/);
});

test("ready-check after a finished match keeps the result until the player returns", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRoom(client, socket);
  startMatch(client, socket, 2);
  socket().receive(serverMessage("STATE_SNAPSHOT", {
    matchId: "match-1",
    view: { revision: 3, gameOver: true },
  }, { matchId: "match-1", revision: 3 }));

  enterRoom(client, socket, "READY_CHECK");

  assert.equal(client.state, MultiplayerClientState.MATCH_FINISHED);
  assert.equal(client.room.roomCode, "ABC123");
  assert.deepEqual(client.view, { revision: 3, gameOver: true });

  client.dismissMatchResult();
  assert.equal(client.state, MultiplayerClientState.IN_ROOM);
  assert.equal(client.view, null);
});

test("room start, match start and finish drive the explicit state machine", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRoom(client, socket, "STARTING");
  assert.equal(client.state, MultiplayerClientState.MATCH_STARTING);

  startMatch(client, socket, 2);
  assert.equal(client.state, MultiplayerClientState.IN_MATCH);
  socket().receive(serverMessage("STATE_SNAPSHOT", {
    matchId: "match-1",
    view: { revision: 3, gameOver: true, winner: "player-1" },
  }, { matchId: "match-1", revision: 3 }));
  assert.equal(client.state, MultiplayerClientState.MATCH_FINISHED);
  assert.equal(client.view.winner, "player-1");
});

test("submitAction uses cached identity and revision and blocks until matching ACK", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRoom(client, socket);
  startMatch(client, socket, 8);

  const actionId = client.submitAction({
    clientActionId: "action-1",
    action: {
      kind: "CHOOSE_PROMPT_OPTION",
      promptId: "prompt-1",
      optionId: "option-1",
      payload: {},
    },
  });
  assert.equal(actionId, "action-1");
  assert.equal(client.canSubmitAction, false);
  assert.deepEqual(JSON.parse(socket().sent.at(-1)).payload, {
    matchId: "match-1",
    playerId: "player-1",
    clientActionId: "action-1",
    expectedRevision: 8,
    action: {
      kind: "CHOOSE_PROMPT_OPTION",
      promptId: "prompt-1",
      optionId: "option-1",
      payload: {},
    },
  });
  assert.throws(() => client.surrender(), /awaiting acknowledgement/);

  socket().receive(serverMessage("ACTION_RESULT", {
    clientActionId: "another-action",
    result: { accepted: true },
    view: { revision: 9, gameOver: false },
  }));
  assert.equal(client.pendingAction.clientActionId, "action-1");
  socket().receive(serverMessage("ACTION_RESULT", {
    clientActionId: "action-1",
    result: { accepted: true },
    view: { revision: 10, gameOver: false },
  }));
  assert.equal(client.pendingAction, null);
  assert.equal(client.canSubmitAction, true);
  assert.equal(client.view.revision, 10);
});

test("only canonical server messages replace the gameplay view", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRoom(client, socket);
  startMatch(client, socket, 4);
  const canonical = client.view;

  socket().receive(serverMessage("ROOM_STATE", {
    roomId: "room-1",
    roomCode: "ABC123",
    status: "RUNNING",
    playerId: "player-1",
    view: { revision: 999 },
  }));
  socket().receive(serverMessage("ERROR", {
    code: "STALE_REVISION",
    message: "sync required",
    fatal: false,
    view: { revision: 1000 },
  }));
  assert.deepEqual(client.view, canonical);
  assert.equal(client.error.code, "STALE_REVISION");

  const snapshot = client.getSnapshot();
  snapshot.room.roomCode = "MUTATE";
  snapshot.view.revision = -1;
  snapshot.error.code = "MUTATE";
  assert.equal(client.room.roomCode, "ABC123");
  assert.equal(client.view.revision, 4);
  assert.equal(client.error.code, "STALE_REVISION");
});

test("surrender is a submitted action and ROOM_CLOSED clears session caches", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRoom(client, socket);
  startMatch(client, socket, 1);

  client.surrender({ clientActionId: "surrender-1" });
  const submission = JSON.parse(socket().sent.at(-1));
  assert.equal(submission.type, "SUBMIT_ACTION");
  assert.deepEqual(submission.payload.action, { kind: "SURRENDER" });

  socket().receive(serverMessage("ROOM_CLOSED", { roomId: "room-1", roomCode: "ABC123" }));
  assert.equal(client.state, MultiplayerClientState.CONNECTED);
  assert.equal(client.room, null);
  assert.equal(client.view, null);
  assert.equal(client.matchId, null);
  assert.equal(client.pendingAction, null);
});

test("a second room and match never reuse the closed match state", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRoom(client, socket);
  startMatch(client, socket, 7);
  client.surrender({ clientActionId: "old-surrender" });

  socket().receive(serverMessage("ROOM_CLOSED", { roomId: "room-1", roomCode: "ABC123" }));
  client.createRoom({ displayName: "Alice" });
  assert.equal(JSON.parse(socket().sent.at(-1)).type, "CREATE_ROOM");
  socket().receive(serverMessage("ROOM_STATE", {
    roomId: "room-2",
    roomCode: "DEF456",
    status: "READY_CHECK",
    playerId: "player-1",
  }));
  socket().receive(serverMessage("MATCH_STARTED", {
    matchId: "match-2",
    playerId: "player-1",
    view: { revision: 0, gameOver: false, hand: ["new-match"] },
  }, { matchId: "match-2", revision: 0 }));

  assert.equal(client.matchId, "match-2");
  assert.deepEqual(client.view, { revision: 0, gameOver: false, hand: ["new-match"] });
  assert.equal(client.pendingAction, null);
  assert.equal(client.room.roomId, "room-2");
  assert.equal(client.getRecoverySession(), null);
});

test("unexpected close enters ERROR while explicit disconnect is idempotent and removes listeners", () => {
  const first = makeClient();
  connectClient(first.client, first.socket);
  first.socket().emit("close", { code: 1006, reason: "network lost" });
  assert.equal(first.client.state, MultiplayerClientState.ERROR);
  assert.equal(first.client.error.code, "UNEXPECTED_CLOSE");
  assert.equal(first.client.error.code === "RECONNECTING", false);
  assert.equal(first.socket().listenerCount(), 0);

  const second = makeClient();
  connectClient(second.client, second.socket);
  const events = [];
  const unsubscribe = second.client.onEvent((event) => events.push(event));
  unsubscribe();
  second.client.disconnect();
  second.client.disconnect();
  assert.equal(second.client.state, MultiplayerClientState.OFFLINE);
  assert.equal(second.socket().closeCalls, 1);
  assert.equal(second.socket().listenerCount(), 0);
  assert.deepEqual(events, []);
});

test("socket ErrorEvent preserves the underlying network failure", () => {
  const { client, socket } = makeClient();
  client.connect({ url: "wss://example.test/multiplayer" });

  socket().emit("error", { error: new Error("read ECONNRESET") });

  assert.equal(client.state, MultiplayerClientState.ERROR);
  assert.deepEqual(client.error, {
    code: "SOCKET_ERROR",
    message: "read ECONNRESET",
  });
});

test("recoverable close reconnects with a private rotated token and canonical snapshot", () => {
  const { client, socket, sockets } = makeClient();
  const publicEvents = [];
  client.onEvent((event) => publicEvents.push(event));
  connectClient(client, socket);
  enterRecoverableRoom(client, socket);
  startMatch(client, socket, 5);

  assert.equal(client.getSnapshot().canReconnect, true);
  assert.equal(client.room.reconnectToken, undefined);
  assert.equal(JSON.stringify(client.getSnapshot()).includes("token-1"), false);
  assert.equal(JSON.stringify(publicEvents).includes("token-1"), false);
  assert.equal(client.getRecoverySession().reconnectToken, "token-1");

  socket().emit("close", { code: 1006, reason: "temporary outage" });
  assert.equal(client.state, MultiplayerClientState.RECONNECTING);
  client.reconnect();
  assert.equal(client.getSnapshot().reconnectAttemptActive, true);
  const reconnectSocket = sockets()[1];
  reconnectSocket.emit("open");
  assert.equal(JSON.parse(reconnectSocket.sent[0]).type, "HELLO");
  reconnectSocket.receive(serverMessage("WELCOME", { connectionId: "connection-2" }));
  assert.deepEqual(JSON.parse(reconnectSocket.sent.at(-1)), {
    protocolVersion: LOCAL_COMPATIBILITY.protocolVersion,
    messageId: "id-3",
    type: "RECONNECT",
    payload: { roomCode: "ABC123", playerId: "player-1", reconnectToken: "token-1" },
  });
  reconnectSocket.receive(serverMessage("ROOM_STATE", {
    roomId: "room-1",
    roomCode: "ABC123",
    status: "RUNNING",
    playerId: "player-1",
    matchId: "match-1",
    reconnectToken: "token-2",
  }));
  reconnectSocket.receive(serverMessage("STATE_SNAPSHOT", {
    matchId: "match-1",
    playerId: "player-1",
    connections: { self: true, opponent: true },
    view: { revision: 7, gameOver: false },
  }, { matchId: "match-1", revision: 7 }));

  assert.equal(client.state, MultiplayerClientState.IN_MATCH);
  assert.equal(client.view.revision, 7);
  assert.equal(client.getRecoverySession().reconnectToken, "token-2");
  assert.equal(JSON.stringify(client.getSnapshot()).includes("token-2"), false);
});

test("pending action is replayed with the same id and expected revision after reconnect", () => {
  const { client, socket, sockets } = makeClient();
  connectClient(client, socket);
  enterRecoverableRoom(client, socket);
  startMatch(client, socket, 8);
  client.submitAction({
    clientActionId: "action-pending",
    action: { kind: "SURRENDER" },
  });
  const originalSubmission = JSON.parse(socket().sent.at(-1));

  socket().emit("close", { code: 1006 });
  client.reconnect();
  const reconnectSocket = sockets()[1];
  reconnectSocket.emit("open");
  reconnectSocket.receive(serverMessage("WELCOME", { connectionId: "connection-2" }));
  reconnectSocket.receive(serverMessage("ROOM_STATE", {
    roomId: "room-1",
    roomCode: "ABC123",
    status: "RUNNING",
    playerId: "player-1",
    matchId: "match-1",
    reconnectToken: "token-2",
  }));
  reconnectSocket.receive(serverMessage("STATE_SNAPSHOT", {
    matchId: "match-1",
    playerId: "player-1",
    connections: { self: true, opponent: true },
    view: { revision: 9, gameOver: false },
  }));

  const replayed = JSON.parse(reconnectSocket.sent.at(-1));
  assert.equal(replayed.type, "SUBMIT_ACTION");
  assert.deepEqual(replayed.payload, originalSubmission.payload);
  reconnectSocket.receive(serverMessage("ACTION_RESULT", {
    clientActionId: "action-pending",
    result: { accepted: true },
    view: { revision: 9, gameOver: true },
    matchFinished: true,
  }));
  assert.equal(client.pendingAction, null);
  assert.equal(client.getRecoverySession().pendingAction, null);
  assert.equal(client.state, MultiplayerClientState.MATCH_FINISHED);
});

test("recovery session survives a client process replacement without entering public snapshots", () => {
  const first = makeClient();
  connectClient(first.client, first.socket);
  enterRecoverableRoom(first.client, first.socket, "persisted-token");
  startMatch(first.client, first.socket, 3);
  const recovery = first.client.getRecoverySession();
  first.client.suspend();

  const second = makeClient();
  second.client.restoreRecoverySession(recovery);
  assert.equal(second.client.state, MultiplayerClientState.OFFLINE);
  assert.equal(second.client.getSnapshot().canReconnect, true);
  assert.equal(JSON.stringify(second.client.getSnapshot()).includes("persisted-token"), false);
  second.client.reconnect();
  second.socket().emit("open");
  second.socket().receive(serverMessage("WELCOME", { connectionId: "connection-reopened" }));
  const reconnect = JSON.parse(second.socket().sent.at(-1));
  assert.equal(reconnect.type, "RECONNECT");
  assert.equal(reconnect.payload.reconnectToken, "persisted-token");
});

test("duplicate seat is retryable while an invalid reconnect token clears recovery", () => {
  const retryable = makeClient();
  retryable.client.restoreRecoverySession({
    url: "ws://example.test/multiplayer",
    roomCode: "ABC123",
    playerId: "player-1",
    matchId: "match-1",
    reconnectToken: "token-retry",
    pendingAction: null,
  });
  retryable.client.reconnect();
  retryable.socket().emit("open");
  retryable.socket().receive(serverMessage("WELCOME", { connectionId: "connection-new" }));
  retryable.socket().receive(serverMessage("ERROR", {
    code: "DUPLICATE_CONNECTION",
    message: "old connection is still closing",
    fatal: false,
  }));
  assert.equal(retryable.client.state, MultiplayerClientState.RECONNECTING);
  assert.equal(retryable.client.getSnapshot().canReconnect, true);
  assert.equal(retryable.socket().closeCalls, 1);

  const invalid = makeClient();
  invalid.client.restoreRecoverySession({
    url: "ws://example.test/multiplayer",
    roomCode: "ABC123",
    playerId: "player-1",
    matchId: null,
    reconnectToken: "bad-token",
    pendingAction: null,
  });
  invalid.client.reconnect();
  invalid.socket().emit("open");
  invalid.socket().receive(serverMessage("WELCOME", { connectionId: "connection-invalid" }));
  invalid.socket().receive(serverMessage("ERROR", {
    code: "INVALID_RECONNECT_TOKEN",
    message: "token rejected",
    fatal: false,
  }));
  assert.equal(invalid.client.state, MultiplayerClientState.OFFLINE);
  assert.equal(invalid.client.getSnapshot().canReconnect, false);
  assert.equal(invalid.client.getRecoverySession(), null);
  assert.equal(invalid.client.error, null);
});

test("socket error during a recoverable match starts reconnect instead of dropping the room", () => {
  const { client, socket } = makeClient();
  connectClient(client, socket);
  enterRecoverableRoom(client, socket);
  startMatch(client, socket, 5);

  socket().emit("error", { error: new Error("read ECONNRESET") });

  assert.equal(client.state, MultiplayerClientState.RECONNECTING);
  assert.equal(client.getSnapshot().canReconnect, true);
  assert.equal(client.room.roomCode, "ABC123");
  assert.equal(client.view.revision, 5);
  assert.equal(client.error.code, "RECONNECT_REQUIRED");
});

test("five failed reconnect attempts give up after a recoverable drop", () => {
  const { client, socket, sockets } = makeClient();
  connectClient(client, socket);
  enterRecoverableRoom(client, socket);
  startMatch(client, socket, 5);
  socket().emit("error", { error: new Error("read ECONNRESET") });
  assert.equal(client.state, MultiplayerClientState.RECONNECTING);

  for (let attempt = 0; attempt < 5; attempt += 1) {
    client.reconnect();
    sockets()[attempt + 1].emit("close", { code: 1006, reason: "still down" });
  }

  assert.equal(client.state, MultiplayerClientState.ERROR);
  assert.equal(client.error.code, "RECONNECT_EXHAUSTED");
  assert.equal(client.getSnapshot().reconnectFailures, 5);
});
