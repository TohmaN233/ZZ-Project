from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.client import ClientConnectionState, MultiplayerClientStore
from zz.multiplayer.protocol import PROTOCOL_VERSION
from zz.multiplayer.transport import WebSocketTransport


def _wait_until(
    predicate: Callable[[], bool],
    clients: tuple[MultiplayerClientStore, MultiplayerClientStore],
    *,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for client in clients:
            if client.status is ClientConnectionState.ERROR:
                raise RuntimeError(f"multiplayer client failed: {client.last_error}")
        if predicate():
            return
        time.sleep(0.02)
    raise TimeoutError("external multiplayer smoke timed out")


def run_external_smoke(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    first_transport = WebSocketTransport(url, max_size=65_536)
    second_transport = WebSocketTransport(url, max_size=65_536)
    first = MultiplayerClientStore(first_transport)
    second = MultiplayerClientStore(second_transport)
    clients = (first, second)
    try:
        first.connect()
        second.connect()
        _wait_until(
            lambda: first.welcome is not None and second.welcome is not None,
            clients,
            timeout=timeout,
        )

        first.create_room(display_name="External Smoke Host")
        _wait_until(lambda: first.room_state is not None, clients, timeout=timeout)
        room_code = str(first.room_state["roomCode"])
        second.join_room(room_code, display_name="External Smoke Guest")
        _wait_until(
            lambda: first.room_state is not None
            and len(first.room_state["players"]) == 2,
            clients,
            timeout=timeout,
        )
        first.select_deck(KANATANA_YELLOW_RECIPE, DECKCODE0_YELLOW_FORCES)
        second.select_deck(DEMETE_GREEN_RECIPE, DECKCODE0_GREEN_FORCES)
        first.set_ready(True)
        second.set_ready(True)
        _wait_until(
            lambda: first.status is ClientConnectionState.MATCH_STARTING
            and second.status is ClientConnectionState.MATCH_STARTING,
            clients,
            timeout=timeout,
        )
        first.select_opening_choice("rock")
        second.select_opening_choice("scissors")
        _wait_until(
            lambda: first.status is ClientConnectionState.IN_MATCH
            and second.status is ClientConnectionState.IN_MATCH
            and first.gameplay_view is not None
            and second.gameplay_view is not None,
            clients,
            timeout=timeout,
        )

        initial_hash = str(first.gameplay_view["stateHash"])
        player_ids = [first.player_id, second.player_id]
        if initial_hash != second.gameplay_view["stateHash"]:
            raise AssertionError("clients disagree on the initial state hash")
        for client in clients:
            opponent_hand = client.gameplay_view["players"]["opponent"]["hand"]
            if any("iid" in card for card in opponent_hand):
                raise AssertionError("opponent hidden hand identity leaked")

        first.surrender(client_action_id=f"external-smoke-{uuid4()}")
        _wait_until(
            lambda: first.status is ClientConnectionState.IN_ROOM
            and second.status is ClientConnectionState.IN_ROOM,
            clients,
            timeout=timeout,
        )
        final_hash = str(first.last_action_result["result"]["stateHash"])
        if first.room_state["roomCode"] != room_code or second.room_state["roomCode"] != room_code:
            raise AssertionError("clients did not return to the same room")

        first_transport.send({
            "protocolVersion": PROTOCOL_VERSION,
            "messageId": str(uuid4()),
            "type": "LEAVE_ROOM",
            "payload": {},
        })
        _wait_until(
            lambda: first.status is ClientConnectionState.CONNECTED
            and second.status is ClientConnectionState.CONNECTED,
            clients,
            timeout=timeout,
        )
        return {
            "url": url,
            "roomCode": room_code,
            "playerIds": player_ids,
            "initialStateHash": initial_hash,
            "finalStateHash": final_hash,
            "hiddenInformationLeaks": 0,
            "roomClosed": True,
        }
    finally:
        first.close()
        second.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a two-client smoke against a deployed ZZ WebSocket server"
    )
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    print(json.dumps(run_external_smoke(args.url, timeout=args.timeout), sort_keys=True))


if __name__ == "__main__":
    main()
