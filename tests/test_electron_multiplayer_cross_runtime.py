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
def _gateway():
    core = MultiplayerServer(
        room_id_factory=lambda: "electron-room",
        room_code_factory=lambda: "EL1234",
        match_id_factory=lambda: "electron-match",
        seed_factory=lambda: 919,
    )
    gateway = WebSocketMultiplayerGateway(
        core,
        config=WebSocketServerConfig(host="127.0.0.1", port=0),
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
    await waitFor(() => first.state === "IN_MATCH" && second.state === "IN_MATCH", "match start");
    if (first.view.stateHash !== second.view.stateHash) throw new Error("state hash mismatch");
    if (first.view.players.opponent.hand.some((card) => Object.hasOwn(card, "iid"))) throw new Error("first hidden hand leaked");
    if (second.view.players.opponent.hand.some((card) => Object.hasOwn(card, "iid"))) throw new Error("second hidden hand leaked");
    first.surrender({ clientActionId: "electron-surrender" });
    await waitFor(() => first.state === "MATCH_FINISHED" && second.state === "MATCH_FINISHED", "match finish");
    process.stdout.write(JSON.stringify({
      firstHash: first.view.stateHash,
      secondHash: second.view.stateHash,
      firstState: first.state,
      secondState: second.state,
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
    assert result["firstHash"] == result["secondHash"]
    assert result["firstState"] == result["secondState"] == "MATCH_FINISHED"
