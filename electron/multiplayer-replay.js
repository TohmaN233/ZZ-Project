"use strict";

const { createHash } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { isDeepStrictEqual } = require("node:util");

function replayId({ serverUrl, matchId, playerId }) {
  for (const value of [serverUrl, matchId, playerId]) {
    if (typeof value !== "string" || !value) throw new TypeError("replay identity fields must be non-empty strings");
  }
  const url = new URL(serverUrl);
  if (!["ws:", "wss:"].includes(url.protocol)) throw new TypeError("replay server URL must use ws or wss");
  return createHash("sha256").update(JSON.stringify([url.toString(), matchId, playerId])).digest("hex");
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function requireEvent(event) {
  if (!event || typeof event !== "object" || Array.isArray(event)
      || !Number.isSafeInteger(event.eventIndex) || event.eventIndex < 0 || event.eventIndex === Number.MAX_SAFE_INTEGER) {
    throw new TypeError("replay event requires a non-negative eventIndex");
  }
}

function applyRecord(session, record) {
  if (record.kind === "event") {
    requireEvent(record.event);
    const previous = session.events.get(record.event.eventIndex);
    if (previous && !isDeepStrictEqual(previous, record.event)) {
      throw new Error(`conflicting replay event ${record.event.eventIndex}`);
    }
    session.events.set(record.event.eventIndex, record.event);
  } else if (record.kind === "frame") {
    const view = record.view;
    if (!view || !Number.isSafeInteger(view.revision) || view.revision < 0 || !view.players) {
      throw new TypeError("invalid replay frame");
    }
    const previous = session.frames.get(view.revision);
    if (previous && previous.stateHash !== view.stateHash) {
      throw new Error(`conflicting replay frame ${view.revision}`);
    }
    session.frames.set(view.revision, view);
  } else {
    throw new Error(`unsupported replay record ${String(record.kind)}`);
  }
}

function inspectSession(session) {
  const frames = [...session.frames.values()].sort((a, b) => a.revision - b.revision);
  const events = [...session.events.values()].sort((a, b) => a.eventIndex - b.eventIndex);
  let latest = -1;
  for (const frame of frames) {
    const index = frame.logHistory?.latestEventIndex;
    if (index !== null && index !== undefined) {
      if (!Number.isSafeInteger(index) || index < 0 || index === Number.MAX_SAFE_INTEGER) {
        throw new Error("invalid latest replay event index");
      }
      latest = Math.max(latest, index);
    }
  }
  for (const event of events) latest = Math.max(latest, event.eventIndex);
  const missingLogEvents = latest + 1 - events.length;
  let newestMissing = latest;
  for (let index = events.length - 1; index >= 0 && newestMissing >= 0; index -= 1) {
    if (events[index].eventIndex === newestMissing) newestMissing -= 1;
    else if (events[index].eventIndex < newestMissing) break;
  }
  const beforeEventIndex = newestMissing >= 0 ? newestMissing + 1 : null;
  let previousRevision = -1;
  let missingRevisions = 0;
  let missingRevision = null;
  for (const frame of frames) {
    missingRevisions += Math.max(0, frame.revision - previousRevision - 1);
    if (missingRevision === null && frame.revision > previousRevision + 1) missingRevision = previousRevision + 1;
    previousRevision = frame.revision;
  }
  const finished = Boolean(frames.at(-1)?.gameOver);
  return {
    frames, events, beforeEventIndex, missingRevision,
    metadata: {
      ...session.header,
      finished,
      complete: finished && missingLogEvents === 0 && missingRevisions === 0,
      missingLogEvents,
      missingRevisions,
      frameCount: frames.length,
      eventCount: events.length,
    },
  };
}

class MultiplayerReplayArchive {
  #root;
  #sessions = new Map();
  #queue = Promise.resolve();

  constructor(root) {
    if (typeof root !== "string" || !root) throw new TypeError("replay root must be a non-empty path");
    this.#root = path.resolve(root);
  }

  #enqueue(operation) {
    const result = this.#queue.then(operation);
    // The caller receives the failure; later operations must still be able to retry.
    this.#queue = result.then(() => undefined, () => undefined);
    return result;
  }

  #file(id) {
    if (typeof id !== "string" || !/^[a-f0-9]{64}$/.test(id)) throw new TypeError("invalid replay id");
    return path.join(this.#root, `${id}.jsonl`);
  }

  async #load(id) {
    const raw = await fs.readFile(this.#file(id), "utf8");
    if (!raw.endsWith("\n")) throw new Error(`replay ${id} ends with an incomplete record`);
    const lines = raw.slice(0, -1).split("\n");
    const header = JSON.parse(lines.shift());
    if (!header || header.kind !== "header" || header.schema !== 1 || header.id !== id) {
      throw new Error(`replay ${id} has an invalid header`);
    }
    const session = { header, frames: new Map(), events: new Map() };
    for (const line of lines) applyRecord(session, JSON.parse(line));
    return session;
  }

  async #session(identity) {
    const id = replayId(identity);
    if (this.#sessions.has(id)) {
      const existing = this.#sessions.get(id);
      this.#sessions.delete(id);
      this.#sessions.set(id, existing);
      return existing;
    }
    await fs.mkdir(this.#root, { recursive: true });
    let session;
    try {
      session = await this.#load(id);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      const header = { kind: "header", schema: 1, id, matchId: identity.matchId,
        playerId: identity.playerId, createdAt: new Date().toISOString() };
      await fs.writeFile(this.#file(id), `${JSON.stringify(header)}\n`, { flag: "wx", mode: 0o600, flush: true });
      session = { header, frames: new Map(), events: new Map() };
    }
    this.#sessions.set(id, session);
    // Durable recordings stay on disk; do not retain every past match in RAM.
    if (this.#sessions.size > 3) this.#sessions.delete(this.#sessions.keys().next().value);
    return session;
  }

  async #append(session, records) {
    if (!records.length) return;
    // Validate the entire batch before writing. Never include socket credentials.
    const next = { header: session.header, frames: new Map(session.frames), events: new Map(session.events) };
    for (const record of records) applyRecord(next, record);
    await fs.appendFile(this.#file(session.header.id), records.map((row) => `${JSON.stringify(row)}\n`).join(""),
      { encoding: "utf8", mode: 0o600, flush: true });
    session.frames = next.frames;
    session.events = next.events;
  }

  recordView({ serverUrl, matchId, playerId, view }) {
    const identity = { serverUrl, matchId, playerId };
    return this.#enqueue(async () => {
      const session = await this.#session(identity);
      const frame = clone(view);
      if (!Array.isArray(frame.logEvents)) throw new TypeError("replay view requires logEvents");
      const events = frame.logEvents;
      frame.logEvents = [];
      frame.log = [];
      const records = events.filter((event) => {
        requireEvent(event);
        const existing = session.events.get(event.eventIndex);
        if (existing && !isDeepStrictEqual(existing, event)) throw new Error(`conflicting replay event ${event.eventIndex}`);
        return !existing;
      }).map((event) => ({ kind: "event", event }));
      const previous = session.frames.get(frame.revision);
      if (previous && previous.stateHash !== frame.stateHash) throw new Error(`conflicting replay frame ${frame.revision}`);
      if (!previous) records.push({ kind: "frame", view: frame });
      await this.#append(session, records);
      const { beforeEventIndex, missingRevision } = inspectSession(session);
      return { id: session.header.id, beforeEventIndex, missingRevision };
    });
  }

  recordPage({ serverUrl, matchId, playerId, beforeEventIndex, events }) {
    const identity = { serverUrl, matchId, playerId };
    return this.#enqueue(async () => {
      const session = await this.#session(identity);
      if (!Number.isSafeInteger(beforeEventIndex) || beforeEventIndex < 0 || !Array.isArray(events)
          || (beforeEventIndex === 0 ? events.length !== 0 : events.length === 0)) {
        throw new TypeError("invalid replay log page");
      }
      const copied = clone(events);
      let previous = -1;
      for (const event of copied) {
        requireEvent(event);
        if (event.eventIndex <= previous || event.eventIndex >= beforeEventIndex) throw new Error("invalid replay page order");
        previous = event.eventIndex;
      }
      if (previous !== beforeEventIndex - 1) throw new Error("replay page does not reach requested cursor");
      const newEvents = copied.filter((event) => {
        const existing = session.events.get(event.eventIndex);
        if (existing && !isDeepStrictEqual(existing, event)) throw new Error(`conflicting replay event ${event.eventIndex}`);
        return !existing;
      });
      await this.#append(session, newEvents.map((event) => ({ kind: "event", event })));
      const { beforeEventIndex: missingCursor, missingRevision } = inspectSession(session);
      return { id: session.header.id, beforeEventIndex: missingCursor, missingRevision };
    });
  }

  list() {
    return this.#enqueue(async () => {
      let names;
      try { names = await fs.readdir(this.#root); } catch (error) {
        if (error.code === "ENOENT") return [];
        throw error;
      }
      const metadata = [];
      for (const name of names.filter((item) => /^[a-f0-9]{64}\.jsonl$/.test(item))) {
        const id = name.slice(0, -6);
        const session = this.#sessions.get(id) || await this.#load(id);
        metadata.push(inspectSession(session).metadata);
      }
      return metadata.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    });
  }

  read(id) {
    return this.#enqueue(async () => {
      const session = this.#sessions.get(id) || await this.#load(id);
      const { metadata, frames, events } = inspectSession(session);
      const logEvents = events.map((event) => {
        let snapshotIndex = frames.findIndex((frame) => (frame.logHistory?.latestEventIndex ?? -1) >= event.eventIndex);
        if (snapshotIndex < 0) snapshotIndex = Math.max(0, frames.length - 1);
        return { ...event, snapshotIndex };
      });
      const stateSnapshots = frames.map((frame, index) => ({
        index,
        state: { ...frame, logEvents: events.filter((event) => event.eventIndex <= (frame.logHistory?.latestEventIndex ?? -1)).slice(-20) },
        animationEvents: frame.animationEvents || [],
      }));
      return clone({ metadata, trace: { logEvents, stateSnapshots } });
    });
  }

  flush() { return this.#queue; }
}

class MultiplayerReplayRecorder {
  #archive;
  #client;
  #onError;
  #pending = null;
  #timer = null;

  constructor({ archive, client, onError }) {
    this.#archive = archive;
    this.#client = client;
    this.#onError = onError;
  }

  handleEvent(event) {
    const snapshot = event.snapshot || {};
    if (event.type === "STATE_CHANGED" && ["RECONNECTING", "OFFLINE", "ERROR"].includes(snapshot.state)) {
      this.#clearRequest();
    }
    const message = event.message;
    if (message?.type === "ERROR" && this.#pending && message.payload?.code === "RATE_LIMITED") {
      // A generic rate-limit error cannot be correlated to a particular command.
      // Keep the request pending so a valid in-flight reply is still accepted.
      this.#onError(new Error("server rate limit during replay recovery; reconnect to retry if the replay is incomplete"));
    }
    if (message?.type === "ERROR" && this.#pending
        && ["MATCH_NOT_FOUND", "REPLAY_FRAME_NOT_FOUND", "LOG_EVENT_TOO_LARGE"].includes(message.payload?.code)) {
      this.#clearRequest();
      this.#onError(new Error(`replay recovery failed: ${message.payload.code}: ${message.payload.message}`));
      return;
    }
    if (!message || !["MATCH_STARTED", "STATE_SNAPSHOT", "ACTION_RESULT", "LOG_HISTORY", "REPLAY_FRAME"].includes(message.type)) return;
    const payload = message.payload || {};
    const identity = {
      serverUrl: snapshot.url,
      matchId: payload.matchId || message.matchId || snapshot.matchId,
      playerId: payload.playerId || snapshot.playerId,
    };
    if (!identity.serverUrl || !identity.matchId || !identity.playerId) {
      this.#onError(new Error("replay event is missing its match identity"));
      return;
    }
    if (identity.matchId !== snapshot.matchId) {
      this.#onError(new Error("replay event does not match the current match"));
      return;
    }
    if (this.#pending && this.#pending.matchId !== identity.matchId) this.#clearRequest();
    let operation;
    if (message.type === "LOG_HISTORY") {
      if (this.#pending?.kind === "log" && this.#pending.matchId === identity.matchId
          && this.#pending.beforeEventIndex === payload.beforeEventIndex) this.#pending = null;
      operation = this.#archive.recordPage({ ...identity, beforeEventIndex: payload.beforeEventIndex, events: payload.events });
    } else {
      if (message.type === "REPLAY_FRAME" && this.#pending?.kind === "frame"
          && this.#pending.matchId === identity.matchId && this.#pending.revision === payload.view?.revision) this.#pending = null;
      operation = this.#archive.recordView({ ...identity, view: payload.view });
    }
    operation.then((result) => this.#scheduleHistory(identity, result)).catch(this.#onError);
  }

  #clearRequest() {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
    this.#pending = null;
  }

  #scheduleHistory(identity, { beforeEventIndex, missingRevision }) {
    if ((beforeEventIndex === null && missingRevision === null) || this.#pending || this.#timer !== null) return;
    this.#timer = setTimeout(() => {
      this.#timer = null;
      const snapshot = this.#client.getSnapshot();
      if (snapshot.matchId !== identity.matchId || snapshot.playerId !== identity.playerId
          || !["IN_MATCH", "MATCH_FINISHED"].includes(snapshot.state)) return;
      try {
        if (beforeEventIndex !== null && snapshot.view?.logHistory?.canPage === true) {
          this.#pending = { kind: "log", matchId: identity.matchId, beforeEventIndex };
          this.#client.requestLogHistory({ matchId: identity.matchId, beforeEventIndex });
        } else if (missingRevision !== null && snapshot.replayFramesSupported) {
          this.#pending = { kind: "frame", matchId: identity.matchId, revision: missingRevision };
          this.#client.requestReplayFrame({ matchId: identity.matchId, revision: missingRevision });
        }
      } catch (error) {
        this.#pending = null;
        this.#onError(error);
      }
    }, 120);
  }

  flush() { return this.#archive.flush(); }
}

module.exports = { MultiplayerReplayArchive, MultiplayerReplayRecorder };
