from __future__ import annotations

import time
from threading import Barrier, Lock, Thread

from zz.multiplayer.protocol import PROTOCOL_VERSION
from zz.multiplayer.service import MultiplayerServer


def _message(message_id: str, message_type: str, payload: dict | None = None) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": message_id,
        "type": message_type,
        "payload": payload or {},
    }


def _action_message(message_id: str) -> dict:
    return _message(message_id, "SUBMIT_ACTION", {
        "matchId": "match-1",
        "playerId": "player_1",
        "clientActionId": message_id,
        "expectedRevision": 0,
        "action": {"kind": "SURRENDER"},
    })


def _server_with_two_rooms() -> MultiplayerServer:
    room_ids = iter(("room-1", "room-2"))
    room_codes = iter(("ROOM01", "ROOM02"))
    server = MultiplayerServer(
        room_id_factory=lambda: next(room_ids),
        room_code_factory=lambda: next(room_codes),
    )
    for connection_id in ("a1", "a2", "b1", "b2"):
        server.connect(connection_id, lambda _message: None)
    server.receive("a1", _message("create-a", "CREATE_ROOM"))
    server.receive("a2", _message("join-a", "JOIN_ROOM", {"roomCode": "ROOM01"}))
    server.receive("b1", _message("create-b", "CREATE_ROOM"))
    server.receive("b2", _message("join-b", "JOIN_ROOM", {"roomCode": "ROOM02"}))
    return server


def test_same_room_messages_are_processed_sequentially() -> None:
    server = _server_with_two_rooms()
    counter_lock = Lock()
    active = 0
    maximum_active = 0

    def slow_submit(_connection, _payload) -> None:
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with counter_lock:
            active -= 1

    server._submit_action = slow_submit
    first = Thread(target=server.receive, args=("a1", _action_message("a")))
    second = Thread(target=server.receive, args=("a2", _action_message("b")))
    first.start()
    second.start()
    first.join()
    second.join()

    assert maximum_active == 1


def test_different_rooms_can_process_messages_concurrently() -> None:
    server = _server_with_two_rooms()
    entered = Barrier(2)
    completed: list[str] = []

    def synchronized_submit(connection, _payload) -> None:
        entered.wait(timeout=1)
        completed.append(connection.connection_id)

    server._submit_action = synchronized_submit
    first = Thread(target=server.receive, args=("a1", _action_message("a")))
    second = Thread(target=server.receive, args=("b1", _action_message("b")))
    first.start()
    second.start()
    first.join()
    second.join()

    assert sorted(completed) == ["a1", "b1"]
