"use strict";

const { randomUUID } = require("node:crypto");
const compatibility = require("../zz/multiplayer/compatibility.json");

const LOCAL_COMPATIBILITY = Object.freeze({ ...compatibility });
const PROTOCOL_VERSION = LOCAL_COMPATIBILITY.protocolVersion;

const MultiplayerClientState = Object.freeze({
  OFFLINE: "OFFLINE",
  CONNECTING: "CONNECTING",
  CONNECTED: "CONNECTED",
  IN_ROOM: "IN_ROOM",
  MATCH_STARTING: "MATCH_STARTING",
  IN_MATCH: "IN_MATCH",
  RECONNECTING: "RECONNECTING",
  MATCH_FINISHED: "MATCH_FINISHED",
  ERROR: "ERROR",
});

const ALLOWED_TRANSITIONS = Object.freeze({
  OFFLINE: new Set(["CONNECTING", "RECONNECTING"]),
  CONNECTING: new Set(["CONNECTED", "OFFLINE", "ERROR"]),
  CONNECTED: new Set(["IN_ROOM", "MATCH_STARTING", "IN_MATCH", "RECONNECTING", "OFFLINE", "ERROR"]),
  IN_ROOM: new Set(["CONNECTED", "MATCH_STARTING", "IN_MATCH", "RECONNECTING", "OFFLINE", "ERROR"]),
  MATCH_STARTING: new Set(["CONNECTED", "IN_MATCH", "MATCH_FINISHED", "RECONNECTING", "OFFLINE", "ERROR"]),
  IN_MATCH: new Set(["CONNECTED", "MATCH_FINISHED", "RECONNECTING", "OFFLINE", "ERROR"]),
  RECONNECTING: new Set(["CONNECTED", "IN_ROOM", "MATCH_STARTING", "IN_MATCH", "MATCH_FINISHED", "OFFLINE", "ERROR"]),
  MATCH_FINISHED: new Set(["CONNECTED", "IN_ROOM", "MATCH_STARTING", "RECONNECTING", "OFFLINE", "ERROR"]),
  ERROR: new Set(["OFFLINE", "RECONNECTING"]),
});

const ROOM_COMMAND_STATES = new Set([
  MultiplayerClientState.IN_ROOM,
  MultiplayerClientState.MATCH_STARTING,
  MultiplayerClientState.IN_MATCH,
  MultiplayerClientState.MATCH_FINISHED,
]);

const MAX_RECONNECT_FAILURES = 5;
const RECONNECT_TIMEOUT_MS = 10000;

const SERVER_MESSAGE_TYPES = new Set([
  "WELCOME",
  "ROOM_STATE",
  "MATCH_STARTED",
  "STATE_SNAPSHOT",
  "LOG_HISTORY",
  "ACTION_RESULT",
  "ERROR",
  "ROOM_CLOSED",
]);

class MultiplayerDesktopClient {
  #WebSocketImpl;
  #uuidFactory;
  #socket = null;
  #socketListeners = null;
  #helloSent = false;
  #listeners = new Set();
  #room = null;
  #view = null;
  #logHistoryPage = null;
  #error = null;
  #pendingAction = null;
  #recovery = null;
  #pendingActionNeedsReplay = false;
  #reconnectFailures = 0;
  #reconnectTimer = null;
  #recoveryPersistenceAckSupported = false;
  #confirmedRecoveryToken = null;

  constructor({ WebSocketImpl = globalThis.WebSocket, uuidFactory = randomUUID } = {}) {
    if (typeof WebSocketImpl !== "function") {
      throw new TypeError("WebSocketImpl must be a constructor");
    }
    if (typeof uuidFactory !== "function") {
      throw new TypeError("uuidFactory must be a function");
    }
    this.#WebSocketImpl = WebSocketImpl;
    this.#uuidFactory = uuidFactory;
    this.state = MultiplayerClientState.OFFLINE;
    this.url = null;
    this.connectionId = null;
    this.playerId = null;
    this.matchId = null;
  }

  get room() {
    return cloneJson(this.#room);
  }

  get view() {
    return cloneJson(this.#view);
  }

  get error() {
    return cloneJson(this.#error);
  }

  get pendingAction() {
    return cloneJson(this.#pendingAction);
  }

  get canSubmitAction() {
    return (
      this.state === MultiplayerClientState.IN_MATCH
      && this.#pendingAction === null
      && this.#view !== null
      && Number.isInteger(this.#view.revision)
      && this.#view.revision >= 0
    );
  }

  getSnapshot() {
    return {
      state: this.state,
      url: this.url,
      connectionId: this.connectionId,
      playerId: this.playerId,
      matchId: this.matchId,
      room: cloneJson(this.#room),
      view: cloneJson(this.#view),
      logHistoryPage: this.#logHistoryPage?.matchId === this.matchId ? cloneJson(this.#logHistoryPage) : null,
      error: cloneJson(this.#error),
      pendingAction: cloneJson(this.#pendingAction),
      canSubmitAction: this.canSubmitAction,
      canReconnect: this.#recovery !== null,
      recoveryRoomCode: this.#recovery?.roomCode || null,
      canRetryReconnect: this.#recovery !== null && this.#socket === null
        && [MultiplayerClientState.OFFLINE, MultiplayerClientState.ERROR].includes(this.state),
      reconnectAttemptActive: this.state === MultiplayerClientState.RECONNECTING && this.#socket !== null,
      reconnectFailures: this.#reconnectFailures,
      reconnectMaxAttempts: MAX_RECONNECT_FAILURES,
    };
  }

  getRecoverySession() {
    return cloneJson(this.#recovery);
  }

  acknowledgeRecoveryPersisted(session) {
    if (!this.#recoveryPersistenceAckSupported || this.#socket === null || this.#recovery === null) return false;
    if (!session || ["url", "roomCode", "playerId", "reconnectToken"].some((key) => session[key] !== this.#recovery[key])) return false;
    if (this.#confirmedRecoveryToken === session.reconnectToken) return false;
    const socket = this.#socket;
    try {
      this.#sendCommand("CONFIRM_RECONNECT", { reconnectToken: session.reconnectToken });
      this.#confirmedRecoveryToken = session.reconnectToken;
    } catch (error) {
      this.#failConnection(socket, "RECOVERY_CONFIRM_FAILED", error);
      throw error;
    }
    return true;
  }

  restoreRecoverySession(session) {
    if (this.state !== MultiplayerClientState.OFFLINE || this.#socket !== null) {
      throw new Error("recovery session can only be restored while offline");
    }
    const recovery = validateRecoverySession(session);
    this.#recovery = recovery;
    this.url = recovery.url;
    this.playerId = recovery.playerId;
    this.matchId = recovery.matchId;
    this.#pendingAction = cloneJson(recovery.pendingAction);
    return this.getSnapshot();
  }

  onEvent(listener) {
    if (typeof listener !== "function") {
      throw new TypeError("listener must be a function");
    }
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }

  connect({ url } = {}) {
    if (this.state !== MultiplayerClientState.OFFLINE || this.#socket !== null) {
      throw new Error(`client cannot connect from ${this.state}`);
    }
    const normalizedUrl = validateWebSocketUrl(url);
    this.#clearRecovery();
    this.url = normalizedUrl;
    this.#error = null;
    this.#helloSent = false;
    this.#setState(MultiplayerClientState.CONNECTING);

    let socket;
    try {
      socket = new this.#WebSocketImpl(normalizedUrl);
      this.#assertSocket(socket);
      this.#socket = socket;
      this.#attachSocketListeners(socket);
    } catch (error) {
      this.#socket = null;
      this.#socketListeners = null;
      this.#recordError("CONNECT_FAILED", error);
      this.#setState(MultiplayerClientState.ERROR);
      throw error;
    }
    return this.getSnapshot();
  }

  reconnect() {
    if (this.#recovery === null) throw new Error("no reconnect session is available");
    if (this.#socket !== null) throw new Error("reconnect socket is already active");
    if (![MultiplayerClientState.OFFLINE, MultiplayerClientState.RECONNECTING, MultiplayerClientState.ERROR].includes(this.state)) {
      throw new Error(`client cannot reconnect from ${this.state}`);
    }
    if (this.state !== MultiplayerClientState.RECONNECTING) this.#reconnectFailures = 0;
    this.url = this.#recovery.url;
    this.#error = null;
    this.#helloSent = false;
    this.#recoveryPersistenceAckSupported = false;
    this.#confirmedRecoveryToken = null;
    this.#pendingActionNeedsReplay = this.#pendingAction !== null;
    this.#setState(MultiplayerClientState.RECONNECTING);
    let socket;
    try {
      socket = new this.#WebSocketImpl(this.url);
      this.#assertSocket(socket);
      this.#socket = socket;
      this.#attachSocketListeners(socket);
      this.#reconnectTimer = setTimeout(() => {
        if (socket === this.#socket) {
          this.#failConnection(socket, "RECONNECT_TIMEOUT", new Error("Reconnect handshake timed out"));
        }
      }, RECONNECT_TIMEOUT_MS);
      this.#reconnectTimer.unref?.();
    } catch (error) {
      this.#socket = null;
      this.#socketListeners = null;
      this.#recordError("RECONNECT_FAILED", error);
      this.#registerReconnectFailure();
      throw error;
    }
    return this.getSnapshot();
  }

  disconnect({ preserveRecovery = false } = {}) {
    if (this.state === MultiplayerClientState.OFFLINE && this.#socket === null && this.#recovery === null) {
      return this.getSnapshot();
    }
    this.#clearReconnectTimer();
    const socket = this.#socket;
    this.#detachSocketListeners(socket);
    this.#socket = null;
    this.#helloSent = false;
    this.#recoveryPersistenceAckSupported = false;
    this.#confirmedRecoveryToken = null;
    if (socket !== null) {
      socket.close();
    }
    this.url = preserveRecovery && this.#recovery ? this.#recovery.url : null;
    this.connectionId = null;
    this.playerId = preserveRecovery && this.#recovery ? this.#recovery.playerId : null;
    this.matchId = preserveRecovery && this.#recovery ? this.#recovery.matchId : null;
    this.#room = null;
    this.#view = null;
    this.#logHistoryPage = null;
    this.#error = null;
    this.#pendingAction = preserveRecovery && this.#recovery
      ? cloneJson(this.#recovery.pendingAction)
      : null;
    this.#pendingActionNeedsReplay = false;
    this.#reconnectFailures = 0;
    if (!preserveRecovery) this.#clearRecovery();
    this.#setState(MultiplayerClientState.OFFLINE);
    this.#emitEvent("DISCONNECTED");
    return this.getSnapshot();
  }

  suspend() {
    return this.disconnect({ preserveRecovery: true });
  }

  createRoom({ displayName } = {}) {
    this.#requireState("CREATE_ROOM", new Set([MultiplayerClientState.CONNECTED]));
    const payload = {};
    if (displayName !== undefined) payload.displayName = requireNonBlankString(displayName, "displayName");
    this.#sendCommand("CREATE_ROOM", payload);
  }

  joinRoom({ roomCode, displayName } = {}) {
    this.#requireState("JOIN_ROOM", new Set([MultiplayerClientState.CONNECTED]));
    if (typeof roomCode !== "string" || !/^[A-Z0-9]{6}$/.test(roomCode)) {
      throw new TypeError("roomCode must contain exactly six uppercase letters or digits");
    }
    const payload = { roomCode };
    if (displayName !== undefined) payload.displayName = requireNonBlankString(displayName, "displayName");
    this.#sendCommand("JOIN_ROOM", payload);
  }

  selectDeck({ deck, forces, profile } = {}) {
    this.#requireState("SELECT_DECK", new Set([MultiplayerClientState.IN_ROOM]));
    if (!isPlainObject(deck) || Object.keys(deck).length === 0) {
      throw new TypeError("deck must be a non-empty object");
    }
    for (const [cardId, count] of Object.entries(deck)) {
      if (!cardId || !Number.isInteger(count) || count < 1 || count > 99) {
        throw new TypeError("deck entries must have a card id and an integer count from 1 to 99");
      }
    }
    if (!Array.isArray(forces) || forces.length !== 2 || forces.some((id) => typeof id !== "string" || !id)) {
      throw new TypeError("forces must contain exactly two non-empty ids");
    }
    this.#sendCommand("SELECT_DECK", {
      deck: cloneJson(deck),
      forces: [...forces],
      ...(profile ? { profile: cloneJson(profile) } : {}),
    });
  }

  setReady({ ready } = {}) {
    this.#requireState("SET_READY", new Set([MultiplayerClientState.IN_ROOM]));
    if (typeof ready !== "boolean") throw new TypeError("ready must be a boolean");
    this.#sendCommand("SET_READY", { ready });
  }

  selectOpeningChoice({ choice } = {}) {
    this.#requireState("SELECT_OPENING_CHOICE", new Set([MultiplayerClientState.MATCH_STARTING]));
    if (!["rock", "paper", "scissors"].includes(choice)) {
      throw new TypeError("choice must be rock, paper, or scissors");
    }
    this.#sendCommand("SELECT_OPENING_CHOICE", { choice });
  }

  submitAction({ action, clientActionId } = {}) {
    if (!isPlainObject(action)) throw new TypeError("action must be an object");
    if (!this.canSubmitAction) {
      if (this.#pendingAction !== null) throw new Error("an action is awaiting acknowledgement");
      throw new Error("client is not ready to submit an action");
    }
    if (!this.matchId || !this.playerId) {
      throw new Error("match and player identity are required");
    }
    const actionId = clientActionId === undefined
      ? this.#newId("clientActionId")
      : requireNonBlankString(clientActionId, "clientActionId");
    const submission = {
      matchId: this.matchId,
      playerId: this.playerId,
      clientActionId: actionId,
      expectedRevision: this.#view.revision,
      action: cloneJson(action),
    };
    this.#pendingAction = cloneJson(submission);
    this.#syncRecoverySession();
    try {
      this.#sendCommand("SUBMIT_ACTION", submission);
    } catch (error) {
      this.#pendingAction = null;
      this.#syncRecoverySession();
      throw error;
    }
    return actionId;
  }

  surrender({ clientActionId } = {}) {
    return this.submitAction({ action: { kind: "SURRENDER" }, clientActionId });
  }

  requestSync() {
    this.#requireState("REQUEST_SYNC", ROOM_COMMAND_STATES);
    const payload = this.matchId ? { matchId: this.matchId } : {};
    this.#sendCommand("REQUEST_SYNC", payload);
  }

  requestLogHistory({ matchId, beforeEventIndex } = {}) {
    this.#requireState("REQUEST_LOG_HISTORY", ROOM_COMMAND_STATES);
    if (!this.#view || this.#view.logHistory?.canPage !== true) throw new Error("server does not support log history paging");
    if (matchId !== this.matchId) throw new Error("log history matchId must match the current match");
    if (!Number.isSafeInteger(beforeEventIndex) || beforeEventIndex < 0) throw new TypeError("beforeEventIndex must be a non-negative integer");
    this.#sendCommand("REQUEST_LOG_HISTORY", { matchId, beforeEventIndex });
  }

  dismissMatchResult() {
    if (this.#view && this.#view.gameOver) {
      this.#view = null;
      this.#logHistoryPage = null;
      this.#pendingAction = null;
      this.#pendingActionNeedsReplay = false;
    }
    if (this.#room && !["STARTING", "RUNNING", "FINISHED"].includes(this.#room.status)) {
      this.#applyRoomStatus(this.#room.status);
    }
    return this.getSnapshot();
  }

  leaveRoom() {
    this.#requireState("LEAVE_ROOM", ROOM_COMMAND_STATES);
    this.#sendCommand("LEAVE_ROOM", {});
    this.#clearRecovery();
    this.#emitEvent("LEAVE_REQUESTED");
  }

  #assertSocket(socket) {
    if (
      socket === null
      || typeof socket !== "object"
      || typeof socket.addEventListener !== "function"
      || typeof socket.removeEventListener !== "function"
      || typeof socket.send !== "function"
      || typeof socket.close !== "function"
    ) {
      throw new TypeError("WebSocketImpl must provide the standard WebSocket event API");
    }
  }

  #attachSocketListeners(socket) {
    const listeners = {
      open: () => this.#handleOpen(socket),
      message: (event) => this.#handleMessage(socket, event),
      error: (event) => this.#handleSocketError(socket, event),
      close: (event) => this.#handleUnexpectedClose(socket, event),
    };
    this.#socketListeners = listeners;
    for (const [type, listener] of Object.entries(listeners)) {
      socket.addEventListener(type, listener);
    }
  }

  #detachSocketListeners(socket) {
    if (socket === null || this.#socketListeners === null) return;
    for (const [type, listener] of Object.entries(this.#socketListeners)) {
      socket.removeEventListener(type, listener);
    }
    this.#socketListeners = null;
  }

  #handleOpen(socket) {
    if (
      socket !== this.#socket
      || ![MultiplayerClientState.CONNECTING, MultiplayerClientState.RECONNECTING].includes(this.state)
    ) return;
    try {
      if (!this.#helloSent) {
        this.#helloSent = true;
        this.#sendEnvelope("HELLO", helloCompatibilityPayload());
      }
      if (this.state === MultiplayerClientState.CONNECTING) {
        this.#setState(MultiplayerClientState.CONNECTED);
      }
    } catch (error) {
      this.#failConnection(socket, "HELLO_FAILED", error);
    }
  }

  #handleMessage(socket, event) {
    if (socket !== this.#socket) return;
    try {
      const raw = event && typeof event === "object" && "data" in event ? event.data : event;
      const text = Buffer.isBuffer(raw) ? raw.toString("utf8") : raw;
      if (typeof text !== "string") throw new TypeError("server message must be UTF-8 text");
      const message = JSON.parse(text);
      this.#applyServerMessage(message);
      const publicMessage = cloneJson(message);
      if (publicMessage.type === "ROOM_STATE" && isPlainObject(publicMessage.payload)) {
        delete publicMessage.payload.reconnectToken;
      }
      this.#emitEvent(message.type, { message: publicMessage });
    } catch (error) {
      this.#failConnection(socket, error?.code || "INVALID_SERVER_MESSAGE", error);
    }
  }

  #handleSocketError(socket, event) {
    if (socket !== this.#socket) return;
    const error = event instanceof Error
      ? event
      : (event && event.error instanceof Error ? event.error : new Error("WebSocket error"));
    this.#failConnection(socket, "SOCKET_ERROR", error);
  }

  #handleUnexpectedClose(socket, event) {
    if (socket !== this.#socket) return;
    const code = event && Number.isInteger(event.code) ? event.code : null;
    const reason = event && typeof event.reason === "string" ? event.reason : "";
    this.#clearReconnectTimer();
    this.#detachSocketListeners(socket);
    this.#socket = null;
    this.#helloSent = false;
    const error = new Error(reason || "WebSocket closed unexpectedly");
    if (this.#recovery !== null) {
      this.#recordError("RECONNECT_REQUIRED", error, { closeCode: code });
      if (this.state !== MultiplayerClientState.RECONNECTING) {
        this.#setState(MultiplayerClientState.RECONNECTING);
      } else {
        this.#registerReconnectFailure();
      }
      return;
    }
    this.#recordError("UNEXPECTED_CLOSE", error, { closeCode: code });
    this.#setState(MultiplayerClientState.ERROR);
  }

  #failConnection(socket, code, error) {
    this.#clearReconnectTimer();
    this.#detachSocketListeners(socket);
    if (this.#socket === socket) this.#socket = null;
    this.#helloSent = false;
    try {
      socket.close();
    } finally {
      if (code === "INCOMPATIBLE_GAME_VERSION") {
        this.#clearRoomSession();
        this.#recordError(code, error);
        this.#setState(MultiplayerClientState.ERROR);
      } else if (this.#recovery !== null) {
        this.#recordError("RECONNECT_REQUIRED", error, { causeCode: code });
        if (this.state !== MultiplayerClientState.RECONNECTING) {
          this.#setState(MultiplayerClientState.RECONNECTING);
        } else {
          this.#registerReconnectFailure();
        }
      } else {
        this.#recordError(code, error);
        this.#setState(MultiplayerClientState.ERROR);
      }
    }
  }

  #applyServerMessage(message) {
    if (!isPlainObject(message)) throw new TypeError("server message must be an object");
    if (message.protocolVersion !== PROTOCOL_VERSION) throw new Error("unsupported protocol version");
    requireNonBlankString(message.messageId, "messageId");
    if (!SERVER_MESSAGE_TYPES.has(message.type)) throw new Error(`unsupported server message type ${String(message.type)}`);
    if (!isPlainObject(message.payload)) throw new TypeError("server message payload must be an object");
    const payload = cloneJson(message.payload);

    switch (message.type) {
      case "WELCOME":
        requireCompatibleServer(payload.compatibility);
        if (payload.recoveryPersistenceAck !== undefined && typeof payload.recoveryPersistenceAck !== "boolean") {
          throw new TypeError("recoveryPersistenceAck must be a boolean");
        }
        this.#recoveryPersistenceAckSupported = payload.recoveryPersistenceAck === true;
        this.connectionId = optionalString(payload.connectionId);
        this.playerId = optionalString(payload.playerId) || this.playerId;
        if (this.state === MultiplayerClientState.RECONNECTING && this.#recovery !== null) {
          this.#sendCommand("RECONNECT", {
            roomCode: this.#recovery.roomCode,
            playerId: this.#recovery.playerId,
            reconnectToken: this.#recovery.reconnectToken,
          });
        }
        break;
      case "ROOM_STATE":
        {
          const reconnectToken = optionalString(payload.reconnectToken);
          delete payload.reconnectToken;
          this.#room = payload;
          this.playerId = optionalString(payload.playerId) || this.playerId;
          if (["STARTING", "RUNNING", "FINISHED"].includes(payload.status)) {
            this.matchId = optionalString(payload.matchId) || this.matchId;
          } else if (payload.status === "READY_CHECK" && this.#view && this.#view.gameOver) {
            // Keep the finished view until the player dismisses the result screen.
          } else {
            this.matchId = null;
            this.#view = null;
            this.#logHistoryPage = null;
            this.#pendingAction = null;
            this.#pendingActionNeedsReplay = false;
          }
          if (reconnectToken) this.#setRecoveryToken(reconnectToken);
          // A running match isn't restored until its private canonical view arrives.
          if (this.state !== MultiplayerClientState.RECONNECTING || payload.status !== "RUNNING") {
            this.#completeReconnect();
            this.#applyRoomStatus(payload.status);
          }
          this.#syncRecoverySession();
        }
        break;
      case "MATCH_STARTED":
        this.matchId = optionalString(payload.matchId) || optionalString(message.matchId);
        this.playerId = optionalString(payload.playerId) || this.playerId;
        this.#view = requirePlainObjectClone(payload.view, "MATCH_STARTED view");
        this.#logHistoryPage = null;
        this.#completeReconnect();
        this.#pendingAction = null;
        this.#pendingActionNeedsReplay = false;
        this.#syncRecoverySession();
        this.#setState(MultiplayerClientState.IN_MATCH);
        break;
      case "STATE_SNAPSHOT":
        this.matchId = optionalString(payload.matchId) || optionalString(message.matchId) || this.matchId;
        this.playerId = optionalString(payload.playerId) || this.playerId;
        this.#view = requirePlainObjectClone(payload.view, "STATE_SNAPSHOT view");
        this.#completeReconnect();
        this.#setState(this.#view.gameOver ? MultiplayerClientState.MATCH_FINISHED : MultiplayerClientState.IN_MATCH);
        this.#syncRecoverySession();
        if (this.#pendingActionNeedsReplay && this.#pendingAction !== null && !this.#view.gameOver) {
          this.#pendingActionNeedsReplay = false;
          this.#sendCommand("SUBMIT_ACTION", this.#pendingAction);
        }
        break;
      case "ACTION_RESULT":
        this.#applyActionResult(payload);
        break;
      case "LOG_HISTORY": {
        if (payload.matchId !== this.matchId) break;
        if (!Number.isSafeInteger(payload.beforeEventIndex) || payload.beforeEventIndex < 0
            || !Array.isArray(payload.events) || payload.events.length > 80) {
          throw new TypeError("invalid log history page");
        }
        let previous = -1;
        for (const event of payload.events) {
          if (!isPlainObject(event) || !Number.isSafeInteger(event.eventIndex)
              || event.eventIndex <= previous || event.eventIndex >= payload.beforeEventIndex) {
            throw new TypeError("invalid log history eventIndex order");
          }
          previous = event.eventIndex;
        }
        const first = payload.events[0]?.eventIndex ?? null;
        const last = payload.events.at(-1)?.eventIndex ?? null;
        if ((payload.events.length > 0 ? last !== payload.beforeEventIndex - 1 : payload.beforeEventIndex !== 0)
            || payload.firstEventIndex !== first || payload.lastEventIndex !== last
            || payload.hasEarlierEvents !== (first !== null && first > 0)) {
          throw new TypeError("invalid log history window");
        }
        this.#logHistoryPage = payload;
        break;
      }
      case "ERROR":
        this.#error = payload;
        if (optionalString(payload.clientActionId) === this.#pendingAction?.clientActionId) {
          this.#pendingAction = null;
          this.#syncRecoverySession();
        }
        if (this.state === MultiplayerClientState.RECONNECTING) {
          this.#clearReconnectTimer();
          const retryable = ["DUPLICATE_CONNECTION", "SEAT_ALREADY_CONNECTED", "RATE_LIMITED"].includes(payload.code);
          const socket = this.#socket;
          this.#detachSocketListeners(socket);
          this.#socket = null;
          this.#helloSent = false;
          if (socket !== null) socket.close();
          if (retryable) {
            this.#recordError(payload.code, new Error(payload.message || payload.code));
            this.#registerReconnectFailure();
          } else {
            this.#clearRecovery();
            this.#room = null;
            this.#view = null;
            this.#logHistoryPage = null;
            this.connectionId = null;
            this.playerId = null;
            this.matchId = null;
            this.#pendingAction = null;
            this.#pendingActionNeedsReplay = false;
            this.#reconnectFailures = 0;
            this.#setState(MultiplayerClientState.OFFLINE);
          }
          break;
        }
        if (payload.fatal === true) {
          const socket = this.#socket;
          this.#detachSocketListeners(socket);
          this.#socket = null;
          this.#helloSent = false;
          if (socket !== null) socket.close();
          this.#setState(MultiplayerClientState.ERROR);
        }
        break;
      case "ROOM_CLOSED":
        this.#clearRoomSession();
        this.#setState(MultiplayerClientState.CONNECTED);
        break;
      default:
        throw new Error(`unsupported server message type ${message.type}`);
    }
  }

  #applyRoomStatus(status) {
    if (status === "STARTING" || status === "RUNNING") {
      if (this.state !== MultiplayerClientState.IN_MATCH) this.#setState(MultiplayerClientState.MATCH_STARTING);
      return;
    }
    if (status === "FINISHED") {
      this.#setState(MultiplayerClientState.MATCH_FINISHED);
      return;
    }
    if (status === "READY_CHECK" && this.#view && this.#view.gameOver) {
      this.#setState(MultiplayerClientState.MATCH_FINISHED);
      return;
    }
    if (status === "CLOSED") {
      this.#clearRoomSession();
      this.#setState(MultiplayerClientState.CONNECTED);
      return;
    }
    this.#setState(MultiplayerClientState.IN_ROOM);
  }

  #applyActionResult(payload) {
    const actionId = optionalString(payload.clientActionId);
    if (actionId && actionId === this.#pendingAction?.clientActionId) this.#pendingAction = null;
    this.#view = requirePlainObjectClone(payload.view, "ACTION_RESULT view");
    this.#syncRecoverySession();
    if (payload.matchFinished === true || this.#view.gameOver === true) {
      this.#setState(MultiplayerClientState.MATCH_FINISHED);
    } else {
      this.#setState(MultiplayerClientState.IN_MATCH);
    }
  }

  #clearRoomSession() {
    this.#room = null;
    this.#view = null;
    this.#logHistoryPage = null;
    this.#pendingAction = null;
    this.#pendingActionNeedsReplay = false;
    this.matchId = null;
    this.playerId = null;
    this.#clearRecovery();
  }

  #setRecoveryToken(reconnectToken) {
    if (!this.#room || !this.url || !this.playerId) {
      throw new Error("reconnect token arrived before room identity");
    }
    this.#recovery = {
      url: this.url,
      roomCode: requireRoomCode(this.#room.roomCode),
      playerId: this.playerId,
      matchId: this.matchId,
      reconnectToken: requireNonBlankString(reconnectToken, "reconnectToken"),
      pendingAction: cloneJson(this.#pendingAction),
    };
  }

  #syncRecoverySession() {
    if (this.#recovery === null) return;
    this.#recovery = {
      ...this.#recovery,
      url: this.url || this.#recovery.url,
      playerId: this.playerId || this.#recovery.playerId,
      matchId: this.matchId,
      pendingAction: cloneJson(this.#pendingAction),
    };
  }

  #clearRecovery() {
    this.#clearReconnectTimer();
    this.#recovery = null;
    this.#logHistoryPage = null;
    this.#pendingActionNeedsReplay = false;
  }

  #requireState(command, allowedStates) {
    if (!allowedStates.has(this.state)) throw new Error(`${command} is not allowed from ${this.state}`);
  }

  #sendCommand(type, payload) {
    this.#sendEnvelope(type, payload);
  }

  #sendEnvelope(type, payload) {
    const socket = this.#socket;
    if (socket === null) throw new Error("WebSocket is not connected");
    const envelope = {
      protocolVersion: PROTOCOL_VERSION,
      messageId: this.#newId("messageId"),
      type,
      payload: cloneJson(payload),
    };
    socket.send(JSON.stringify(envelope));
  }

  #newId(label) {
    return requireNonBlankString(this.#uuidFactory(), label);
  }

  #registerReconnectFailure() {
    this.#reconnectFailures += 1;
    this.#emitEvent("RECONNECT_FAILED");
    if (this.#reconnectFailures >= MAX_RECONNECT_FAILURES) {
      this.#recordError("RECONNECT_EXHAUSTED", new Error("reconnect failed repeatedly"));
      this.#setState(MultiplayerClientState.ERROR);
    }
  }

  #clearReconnectTimer() {
    if (this.#reconnectTimer !== null) clearTimeout(this.#reconnectTimer);
    this.#reconnectTimer = null;
  }

  #completeReconnect() {
    this.#clearReconnectTimer();
    this.#reconnectFailures = 0;
    this.#error = null;
  }

  #setState(nextState) {
    if (nextState === this.state) return;
    const allowed = ALLOWED_TRANSITIONS[this.state];
    if (!allowed || !allowed.has(nextState)) {
      throw new Error(`invalid multiplayer client transition ${this.state} -> ${nextState}`);
    }
    this.state = nextState;
    this.#emitEvent("STATE_CHANGED");
  }

  #recordError(code, error, extra = {}) {
    this.#error = {
      code,
      message: error instanceof Error ? error.message : String(error),
      ...extra,
    };
  }

  #emitEvent(type, detail = {}) {
    const event = { type, ...cloneJson(detail), snapshot: this.getSnapshot() };
    for (const listener of [...this.#listeners]) listener(cloneJson(event));
  }
}

function validateWebSocketUrl(value) {
  if (typeof value !== "string" || !value) throw new TypeError("url must be a non-empty string");
  let parsed;
  try {
    parsed = new URL(value);
  } catch (error) {
    throw new TypeError("url must be a valid ws:// or wss:// URL", { cause: error });
  }
  if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
    throw new TypeError("url must use ws:// or wss://");
  }
  return parsed.toString();
}

function helloCompatibilityPayload() {
  return {
    applicationVersion: LOCAL_COMPATIBILITY.applicationVersion,
    rulesVersion: LOCAL_COMPATIBILITY.rulesVersion,
    cardDatabaseChecksum: LOCAL_COMPATIBILITY.cardDatabaseChecksum,
  };
}

function requireCompatibleServer(value) {
  const expectedKeys = Object.keys(LOCAL_COMPATIBILITY).sort();
  if (
    !isPlainObject(value)
    || JSON.stringify(Object.keys(value).sort()) !== JSON.stringify(expectedKeys)
    || expectedKeys.some((key) => value[key] !== LOCAL_COMPATIBILITY[key])
  ) {
    const error = new Error("Server game version is incompatible with this client.");
    error.code = "INCOMPATIBLE_GAME_VERSION";
    throw error;
  }
}

function validateRecoverySession(value) {
  if (!isPlainObject(value)) throw new TypeError("recovery session must be an object");
  const required = new Set([
    "matchId",
    "pendingAction",
    "playerId",
    "reconnectToken",
    "roomCode",
    "url",
  ]);
  const keys = Object.keys(value);
  if (keys.length !== required.size || keys.some((key) => !required.has(key))) {
    throw new TypeError("recovery session has invalid fields");
  }
  const matchId = value.matchId === null ? null : requireNonBlankString(value.matchId, "matchId");
  const pendingAction = value.pendingAction === null
    ? null
    : requirePlainObjectClone(value.pendingAction, "pendingAction");
  return {
    url: validateWebSocketUrl(value.url),
    roomCode: requireRoomCode(value.roomCode),
    playerId: requireNonBlankString(value.playerId, "playerId"),
    matchId,
    reconnectToken: requireNonBlankString(value.reconnectToken, "reconnectToken"),
    pendingAction,
  };
}

function cloneJson(value) {
  if (value === null || value === undefined) return value;
  return JSON.parse(JSON.stringify(value));
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function requirePlainObjectClone(value, label) {
  if (!isPlainObject(value)) throw new TypeError(`${label} must be an object`);
  return cloneJson(value);
}

function requireNonBlankString(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new TypeError(`${label} must be a non-empty string`);
  return value;
}

function requireRoomCode(value) {
  if (typeof value !== "string" || !/^[A-Z0-9]{6}$/.test(value)) {
    throw new TypeError("roomCode must contain exactly six uppercase letters or digits");
  }
  return value;
}

function optionalString(value) {
  return typeof value === "string" && value ? value : null;
}

module.exports = {
  LOCAL_COMPATIBILITY,
  MultiplayerClientState,
  MultiplayerDesktopClient,
  PROTOCOL_VERSION,
};
