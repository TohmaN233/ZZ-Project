"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const { MultiplayerReplayArchive, MultiplayerReplayRecorder } = require("../electron/multiplayer-replay");

test("online replay persists deduplicated views and complete paged logs across restart", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "zz-replay-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  let store = new MultiplayerReplayArchive(root);
  const identity = { serverUrl: "wss://example.test/multiplayer", matchId: "match-1", playerId: "player_1" };
  const view = (revision, first, last) => ({
    revision, stateHash: `hash-${revision}`, gameOver: revision === 2 ? { winner: "P1" } : null,
    humanSide: "P1", players: { human: { hand: [{ cardId: "own" }] }, opponent: { hand: [{ faceDown: true }] } },
    animationEvents: [{ type: "phase", phase: "main" }],
    logHistory: { canPage: true, latestEventIndex: last },
    logEvents: Array.from({ length: last - first + 1 }, (_, i) => ({ eventIndex: first + i, type: "action" })),
  });
  const first = await store.recordView({ ...identity, view: view(0, 0, 1) });
  await store.recordView({ ...identity, view: view(1, 4, 5) });
  const gap = await store.recordView({ ...identity, view: view(1, 4, 5) });
  assert.equal(gap.beforeEventIndex, 4);
  store = new MultiplayerReplayArchive(root);
  const filled = await store.recordPage({ ...identity, beforeEventIndex: 4,
    events: [{ eventIndex: 2, type: "action" }, { eventIndex: 3, type: "action" }] });
  assert.equal(filled.beforeEventIndex, null);
  await store.recordView({ ...identity, view: view(2, 4, 5) });
  const replay = await store.read(first.id);
  assert.equal(replay.metadata.complete, true);
  assert.equal(replay.metadata.missingLogEvents, 0);
  assert.equal(replay.metadata.missingRevisions, 0);
  assert.deepEqual(replay.trace.logEvents.map((row) => row.eventIndex), [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(replay.trace.stateSnapshots.map((frame) => frame.state.revision), [0, 1, 2]);
  assert.equal(replay.trace.stateSnapshots[0].state.players.opponent.hand[0].cardId, undefined);
  assert.equal((await store.list())[0].id, first.id);
  await assert.rejects(() => store.read("../not-a-replay"), /invalid replay id/);
});

test("online replay reports missed frames and failed writes instead of calling an incomplete recording complete", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "zz-replay-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const store = new MultiplayerReplayArchive(root);
  const identity = { serverUrl: "ws://example.test", matchId: "match-2", playerId: "player_2" };
  const saved = await store.recordView({ ...identity, view: {
    revision: 3, stateHash: "h", gameOver: { winner: "P2" }, animationEvents: [],
    players: { human: {}, opponent: {} }, logEvents: [{ eventIndex: 4, type: "action" }],
    logHistory: { canPage: true, latestEventIndex: 4 },
  } });
  assert.equal(saved.beforeEventIndex, 4);
  const replay = await store.read(saved.id);
  assert.equal(replay.metadata.complete, false);
  assert.equal(replay.metadata.missingLogEvents, 4);
  assert.equal(replay.metadata.missingRevisions, 3);
  const notDirectory = path.join(root, "file");
  await fs.writeFile(notDirectory, "not a folder");
  const broken = new MultiplayerReplayArchive(notDirectory);
  await assert.rejects(() => broken.recordView({ ...identity, view: { revision: 0, players: {}, logEvents: [] } }));
});

test("reconnect backfills missing log pages and preserves an in-flight request after a generic rate limit", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "zz-replay-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const archive = new MultiplayerReplayArchive(root);
  const requests = [];
  const errors = [];
  const view = { revision: 3, stateHash: "h", players: { human: {}, opponent: {} }, animationEvents: [],
    logEvents: [{ eventIndex: 4, type: "action" }], logHistory: { latestEventIndex: 4, canPage: true } };
  const snapshot = { url: "ws://example.test", matchId: "match-3", playerId: "player_1", state: "IN_MATCH", view };
  const client = { getSnapshot: () => snapshot, requestLogHistory: (request) => requests.push(request) };
  const recorder = new MultiplayerReplayRecorder({ archive, client, onError: (error) => errors.push(error) });
  recorder.handleEvent({ type: "STATE_SNAPSHOT", snapshot,
    message: { type: "STATE_SNAPSHOT", payload: { matchId: snapshot.matchId, view } } });
  recorder.handleEvent({ type: "STATE_SNAPSHOT", snapshot,
    message: { type: "STATE_SNAPSHOT", payload: { matchId: snapshot.matchId, view } } });
  await new Promise((resolve) => setTimeout(resolve, 200));
  assert.deepEqual(requests, [{ matchId: "match-3", beforeEventIndex: 4 }]);
  recorder.handleEvent({ type: "ERROR", snapshot,
    message: { type: "ERROR", payload: { code: "RATE_LIMITED", message: "rate limit" } } });
  const events = Array.from({ length: 4 }, (_, eventIndex) => ({ eventIndex, type: "action" }));
  recorder.handleEvent({ type: "LOG_HISTORY", snapshot,
    message: { type: "LOG_HISTORY", payload: { matchId: snapshot.matchId, beforeEventIndex: 4, events } } });
  await recorder.flush();
  await new Promise((resolve) => setTimeout(resolve, 150));
  assert.equal(requests.length, 1);
  assert.equal(errors.length, 1);
  assert.match(errors[0].message, /rate limit during replay recovery/);
  assert.equal((await archive.list())[0].missingLogEvents, 0);
});

test("reconnect fetches missed player-view frames and completes the replay", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "zz-replay-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const archive = new MultiplayerReplayArchive(root);
  const requests = [];
  const errors = [];
  const frame = (revision) => ({ revision, stateHash: `h-${revision}`, gameOver: revision === 2 ? { winner: "P1" } : null,
    players: { human: {}, opponent: { hand: [{ faceDown: true }] } }, animationEvents: [], logEvents: [],
    logHistory: { latestEventIndex: null, canPage: true } });
  const snapshot = { url: "ws://example.test", matchId: "match-4", playerId: "player_1",
    state: "MATCH_FINISHED", view: frame(2), replayFramesSupported: true };
  const client = { getSnapshot: () => snapshot, requestReplayFrame: (request) => requests.push(request) };
  const recorder = new MultiplayerReplayRecorder({ archive, client, onError: (error) => errors.push(error) });
  recorder.handleEvent({ type: "STATE_SNAPSHOT", snapshot,
    message: { type: "STATE_SNAPSHOT", payload: { matchId: snapshot.matchId, view: snapshot.view } } });
  for (const revision of [0, 1]) {
    await new Promise((resolve) => setTimeout(resolve, 160));
    assert.deepEqual(requests.at(-1), { matchId: snapshot.matchId, revision });
    recorder.handleEvent({ type: "REPLAY_FRAME", snapshot,
      message: { type: "REPLAY_FRAME", payload: { matchId: snapshot.matchId, view: frame(revision) } } });
    await recorder.flush();
  }
  await new Promise((resolve) => setTimeout(resolve, 150));
  const [summary] = await archive.list();
  assert.equal(summary.complete, true);
  assert.equal(requests.length, 2);
  assert.deepEqual(errors, []);
});
