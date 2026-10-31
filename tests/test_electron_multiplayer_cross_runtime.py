from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.websocket_server import WebSocketMultiplayerGateway, WebSocketServerConfig


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _gateway(core=None, *, max_message_bytes=262_144):
    core = core or MultiplayerServer(
        room_id_factory=lambda: "electron-room",
        room_code_factory=lambda: "EL1234",
        match_id_factory=lambda: "electron-match",
        seed_factory=lambda: 919,
    )
    gateway = WebSocketMultiplayerGateway(
        core,
        config=WebSocketServerConfig(host="127.0.0.1", port=0, max_message_bytes=max_message_bytes),
    )
    with gateway.create_server() as server:
        thread = Thread(target=server.serve_forever, name="electron-cross-runtime-server")
        thread.start()
        try:
            yield f"ws://127.0.0.1:{server.socket.getsockname()[1]}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_node_desktop_clients_complete_real_python_websocket_match() -> None:
    payload = {
        "first": {"deck": KANATANA_YELLOW_RECIPE, "forces": DECKCODE0_YELLOW_FORCES},
        "second": {"deck": DEMETE_GREEN_RECIPE, "forces": DECKCODE0_GREEN_FORCES},
    }
    script = r"""
const { MultiplayerDesktopClient } = require(process.env.ZZ_CLIENT_MODULE);
const decks = JSON.parse(process.env.ZZ_TEST_DECKS);
const waitFor = async (predicate, label) => {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`timeout: ${label}`);
};
(async () => {
  const first = new MultiplayerDesktopClient();
  const second = new MultiplayerDesktopClient();
  try {
    first.connect({ url: process.env.ZZ_TEST_URL });
    second.connect({ url: process.env.ZZ_TEST_URL });
    await waitFor(() => (
      (first.state === "CONNECTED" && second.state === "CONNECTED")
      || first.state === "ERROR"
      || second.state === "ERROR"
    ), "connect");
    if (first.state === "ERROR" || second.state === "ERROR") {
      throw new Error(`connect failed: ${JSON.stringify({ first: first.error, second: second.error })}`);
    }
    first.createRoom({ displayName: "Alice" });
    await waitFor(() => first.room && first.room.roomCode === "EL1234", "create room");
    second.joinRoom({ roomCode: "EL1234", displayName: "Bob" });
    await waitFor(() => first.room && first.room.players.length === 2, "join room");
    first.selectDeck(decks.first);
    second.selectDeck(decks.second);
    first.setReady({ ready: true });
    second.setReady({ ready: true });
    await waitFor(() => first.state === "MATCH_STARTING" && second.state === "MATCH_STARTING", "opening choice");
    first.selectOpeningChoice({ choice: "rock" });
    second.selectOpeningChoice({ choice: "scissors" });
    await waitFor(() => first.state === "IN_MATCH" && second.state === "IN_MATCH", "match start");
    if (first.view.stateHash !== second.view.stateHash) throw new Error("state hash mismatch");
    if (first.view.players.opponent.hand.some((card) => Object.hasOwn(card, "iid"))) throw new Error("first hidden hand leaked");
    if (second.view.players.opponent.hand.some((card) => Object.hasOwn(card, "iid"))) throw new Error("second hidden hand leaked");
    first.surrender({ clientActionId: "electron-surrender" });
    await waitFor(() => (
      first.state === "MATCH_FINISHED" && second.state === "MATCH_FINISHED"
      && first.room?.status === "READY_CHECK" && second.room?.status === "READY_CHECK"
    ), "match finish and room reset");
    process.stdout.write(JSON.stringify({
      firstState: first.state,
      secondState: second.state,
      roomCode: first.room.roomCode,
      roomStatus: first.room.status,
      winner: first.view.gameOver && first.view.gameOver.winner,
    }));
  } finally {
    first.disconnect();
    second.disconnect();
  }
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
"""
    env = {
        **os.environ,
        "ZZ_CLIENT_MODULE": str(ROOT / "electron" / "multiplayer-client.js"),
        "ZZ_TEST_DECKS": json.dumps(payload),
    }
    with _gateway() as url:
        env["ZZ_TEST_URL"] = url
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )

    result = json.loads(completed.stdout)
    assert result["firstState"] == result["secondState"] == "MATCH_FINISHED"
    assert result["roomCode"] == "EL1234"
    assert result["roomStatus"] == "READY_CHECK"
    assert result["winner"] == "Bob"


def test_large_reconnect_recovers_logs_and_missed_private_replay_frames(tmp_path: Path) -> None:
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _send, _start_match, _submit_keep
    from zz.enums import AreaType

    core, messages = _connected_server(TimerFactory())
    tokens = _start_match(core, messages)
    match = core.match_for_room("ABC123")
    initial = match.get_view_for("player_1")
    _submit_keep(core, messages, "a")
    core.disconnect("a")
    prompt = match.get_view_for("player_2")["prompt"]
    _send(core, "b", "SUBMIT_ACTION", {
        "matchId": match.match_id, "playerId": "player_2", "clientActionId": "keep-player-2",
        "expectedRevision": match.revision, "action": {"kind": "CHOOSE_PROMPT_OPTION",
            "promptId": prompt["id"], "optionId": "keep", "payload": {}},
    })
    assert match.revision == 2
    for _ in range(95):
        match.session._log_event("private diagnostic text", {"type": "optional_effect", "actorSide": "P1", "used": True})
    latest = match.session._codeman_trace_events[-1]["eventIndex"]
    card = match.session.engine.state.players[0].hand[0]
    match.session._animation_events.clear()
    for _ in range(400):
        match.session._queue_zone_move_animation_event(card, AreaType.HAND, AreaType.TRASH)
    match._animation_events = tuple(match.session._animation_events)
    match.session._animation_events.clear()
    (tmp_path / "initial.json").write_text(json.dumps(initial, ensure_ascii=False), encoding="utf-8")
    script = r"""
const fs = require("node:fs");
const assert = require("node:assert/strict");
const { MultiplayerDesktopClient } = require(process.env.ZZ_CLIENT_MODULE);
const { MultiplayerReplayArchive, MultiplayerReplayRecorder } = require(process.env.ZZ_REPLAY_MODULE);
const waitFor = async (predicate, label) => {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  throw new Error(`timeout: ${label}`);
};
(async () => {
  const client = new MultiplayerDesktopClient();
  const archive = new MultiplayerReplayArchive(process.env.ZZ_REPLAY_ROOT);
  const identity = { serverUrl: process.env.ZZ_TEST_URL, matchId: "match-1", playerId: "player_1" };
  const initial = JSON.parse(fs.readFileSync(process.env.ZZ_INITIAL_VIEW, "utf8"));
  const saved = await archive.recordView({ ...identity, view: initial });
  const errors = [];
  const recorder = new MultiplayerReplayRecorder({ archive, client, onError: error => errors.push(error.message) });
  client.onEvent(event => recorder.handleEvent(event));
  try {
    client.restoreRecoverySession({ url: identity.serverUrl, roomCode: "ABC123", playerId: identity.playerId,
      reconnectToken: process.env.ZZ_TEST_TOKEN, matchId: identity.matchId, pendingAction: null });
    client.reconnect();
    await waitFor(() => client.state === "IN_MATCH" || errors.length > 0, "large reconnect");
    assert.deepEqual(errors, []);
    assert.equal(client.view.revision, 2);
    assert.equal(client.view.animationEvents.length, 400);
    await waitFor(async () => {
      const [summary] = await archive.list();
      return summary && summary.missingLogEvents === 0 && summary.missingRevisions === 0 && summary.frameCount === 3;
    }, "replay recovery");
    const replay = await archive.read(saved.id);
    assert.equal(replay.trace.logEvents.length, Number(process.env.ZZ_LATEST_EVENT) + 1,
      JSON.stringify({ metadata: replay.metadata, latest: replay.trace.stateSnapshots.map(frame => frame.state.logHistory) }));
    assert.deepEqual(replay.trace.stateSnapshots.map(frame => frame.state.revision), [0, 1, 2]);
    assert.ok(replay.trace.stateSnapshots.every(frame => frame.state.players.opponent.hand.every(card => card.faceDown && !card.cardId)));
    const file = fs.readFileSync(`${process.env.ZZ_REPLAY_ROOT}/${saved.id}.jsonl`, "utf8");
    assert.equal(file.includes(process.env.ZZ_TEST_TOKEN), false);
    assert.equal(file.includes("private diagnostic text"), false);
    assert.deepEqual(errors, []);
    process.stdout.write(JSON.stringify({ frames: replay.metadata.frameCount, events: replay.metadata.eventCount }));
  } finally {
    client.disconnect();
    await recorder.flush();
  }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
"""
    env = {**os.environ, "ZZ_CLIENT_MODULE": str(ROOT / "electron" / "multiplayer-client.js"),
           "ZZ_REPLAY_MODULE": str(ROOT / "electron" / "multiplayer-replay.js"),
           "ZZ_REPLAY_ROOT": str(tmp_path / "replays"), "ZZ_INITIAL_VIEW": str(tmp_path / "initial.json"),
           "ZZ_TEST_TOKEN": tokens["player_1"], "ZZ_LATEST_EVENT": str(latest)}
    with _gateway(core) as url:
        env["ZZ_TEST_URL"] = url
        completed = subprocess.run(["node", "-e", script], cwd=ROOT, env=env, capture_output=True,
                                   text=True, timeout=25, check=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"frames": 3, "events": latest + 1}


def test_real_64k_gateway_restores_complete_desktop_history_and_isolates_the_next_match() -> None:
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _start_match

    core, messages = _connected_server(TimerFactory())
    match_ids = iter(("match-1", "match-2"))
    core._match_id_factory = lambda: next(match_ids)
    tokens = _start_match(core, messages)
    match = core.match_for_room("ABC123")
    owner = match.session.engine.state.players[0]
    match.session._log_event("private-log-text", {"type": "effect_target", "actorSide": "P1",
                                                "targets": [match.session._effect_target_log_payload(owner.hand[0])]})
    for index in range(104):
        match.session._log_event("diagnostics", {"type": "reveal", "actorSide": "P1", "reason": "公開" * 2000})
    core.disconnect("a")
    core.disconnect("b")
    script = r"""
const assert = require("node:assert/strict");
const { MultiplayerDesktopClient } = require(process.env.ZZ_CLIENT_MODULE);
const tokens = JSON.parse(process.env.ZZ_TEST_TOKENS);
const waitFor = async (predicate, label) => {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error(`timeout: ${label}`);
};
(async () => {
  const clients = [new MultiplayerDesktopClient(), new MultiplayerDesktopClient()];
  const [first, second] = clients;
  try {
    for (const [index, client] of clients.entries()) {
      const playerId = `player_${index + 1}`;
      client.restoreRecoverySession({ url: process.env.ZZ_TEST_URL, roomCode: "ABC123", playerId,
        reconnectToken: tokens[playerId], matchId: "match-1", pendingAction: null });
      client.reconnect();
    }
    await waitFor(() => clients.every(client => client.state === "IN_MATCH"), "both reconnect snapshots");
    const board = first.view;
    const all = new Map();
    let before = first.view.logHistory.latestEventIndex + 1;
    while (before > 0) {
      first.requestLogHistory({ matchId: "match-1", beforeEventIndex: before });
      await waitFor(() => first.getSnapshot().logHistoryPage?.beforeEventIndex === before, `page ${before}`);
      const page = first.getSnapshot().logHistoryPage;
      assert.ok(page.events.length > 0);
      for (const event of page.events) all.set(event.eventIndex, event);
      assert.ok(page.firstEventIndex < before);
      before = page.firstEventIndex;
    }
    assert.deepEqual([...all.keys()].sort((a, b) => a - b), Array.from({ length: 105 }, (_, i) => i));
    assert.deepEqual(first.view, board);
    assert.ok(all.get(0).targets[0].cardId);
    second.requestLogHistory({ matchId: "match-1", beforeEventIndex: 1 });
    await waitFor(() => second.getSnapshot().logHistoryPage?.beforeEventIndex === 1, "private opponent history");
    assert.equal(second.getSnapshot().logHistoryPage.events[0].targets[0].faceDown, true);
    assert.equal(second.getSnapshot().logHistoryPage.events[0].targets[0].cardId, undefined);
    assert.equal(JSON.stringify(first.getSnapshot().logHistoryPage).includes("private-log-text"), false);
    first.surrender({ clientActionId: "history-finish" });
    await waitFor(() => clients.every(client => client.state === "MATCH_FINISHED" && client.room?.status === "READY_CHECK"), "finish");
    first.requestLogHistory({ matchId: "match-1", beforeEventIndex: 1 });
    await waitFor(() => first.getSnapshot().logHistoryPage?.beforeEventIndex === 1, "finished history");
    assert.ok(first.getSnapshot().logHistoryPage.events[0].targets[0].cardId);
    for (const client of clients) client.dismissMatchResult();
    first.setReady({ ready: true });
    second.setReady({ ready: true });
    await waitFor(() => clients.every(client => client.state === "MATCH_STARTING"), "ready rematch");
    first.selectOpeningChoice({ choice: "rock" });
    second.selectOpeningChoice({ choice: "scissors" });
    await waitFor(() => clients.every(client => client.matchId === "match-2" && client.state === "IN_MATCH"), "next match");
    assert.equal(first.getSnapshot().logHistoryPage, null);
    assert.equal(second.getSnapshot().logHistoryPage, null);
    assert.throws(() => first.requestLogHistory({ matchId: "match-1", beforeEventIndex: 1 }), /current match/);
    process.stdout.write(JSON.stringify({ recovered: all.size, matchId: first.matchId, private: true }));
  } finally {
    for (const client of clients) client.disconnect();
  }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
"""
    env = {**os.environ, "ZZ_CLIENT_MODULE": str(ROOT / "electron" / "multiplayer-client.js"),
           "ZZ_TEST_TOKENS": json.dumps(tokens)}
    with _gateway(core, max_message_bytes=65_536) as url:
        env["ZZ_TEST_URL"] = url
        completed = subprocess.run(["node", "-e", script], cwd=ROOT, env=env, capture_output=True,
                                   text=True, timeout=25, check=True)
    result = json.loads(completed.stdout)
    assert result == {"recovered": 105, "matchId": "match-2", "private": True}
    assert core._finished_match_logs == {}
