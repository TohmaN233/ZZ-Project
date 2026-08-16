from __future__ import annotations

import pytest

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.protocol import (
    PROTOCOL_VERSION,
    parse_client_message,
    serialize_client_message,
)
from zz.multiplayer.rooms import Room, RoomError
from zz.multiplayer.service import MultiplayerServer


class StepClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        value = self.value
        self.value += 1.0
        return value


class FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class TimerFactory:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    def __call__(self, delay: float, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer


def _message(message_id: str, message_type: str, payload: dict | None = None) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": message_id,
        "type": message_type,
        "payload": payload or {},
    }


def _send(
    server: MultiplayerServer,
    connection_id: str,
    message_type: str,
    payload: dict | None = None,
) -> None:
    _send.counter += 1
    server.receive(
        connection_id,
        _message(f"client-{_send.counter}", message_type, payload),
    )


_send.counter = 0


def _latest(messages: list[dict], message_type: str) -> dict:
    return next(
        message["payload"]
        for message in reversed(messages)
        if message["type"] == message_type
    )


def _connected_server(
    timer_factory: TimerFactory,
) -> tuple[MultiplayerServer, dict[str, list[dict]]]:
    messages: dict[str, list[dict]] = {"a": [], "b": []}
    server = MultiplayerServer(
        room_id_factory=lambda: "room-1",
        room_code_factory=lambda: "ABC123",
        match_id_factory=lambda: "match-1",
        seed_factory=lambda: 701,
        reconnect_grace_seconds=45,
        reconnect_timer_factory=timer_factory,
    )
    server.connect("a", messages["a"].append)
    server.connect("b", messages["b"].append)
    return server, messages


def _start_match(
    server: MultiplayerServer,
    messages: dict[str, list[dict]],
) -> dict[str, str]:
    _send(server, "a", "CREATE_ROOM", {"displayName": "Alice"})
    _send(server, "b", "JOIN_ROOM", {"roomCode": "ABC123", "displayName": "Bob"})
    tokens = {
        "player_1": _latest(messages["a"], "ROOM_STATE")["reconnectToken"],
        "player_2": _latest(messages["b"], "ROOM_STATE")["reconnectToken"],
    }
    _send(server, "a", "SELECT_DECK", {
        "deck": KANATANA_YELLOW_RECIPE,
        "forces": DECKCODE0_YELLOW_FORCES,
    })
    _send(server, "b", "SELECT_DECK", {
        "deck": DEMETE_GREEN_RECIPE,
        "forces": DECKCODE0_GREEN_FORCES,
    })
    _send(server, "a", "SET_READY", {"ready": True})
    _send(server, "b", "SET_READY", {"ready": True})
    _send(server, "a", "SELECT_OPENING_CHOICE", {"choice": "rock"})
    _send(server, "b", "SELECT_OPENING_CHOICE", {"choice": "scissors"})
    return tokens


def _submit_keep(
    server: MultiplayerServer,
    messages: dict[str, list[dict]],
    connection_id: str = "a",
) -> None:
    started = _latest(messages[connection_id], "MATCH_STARTED")
    prompt = started["view"]["prompt"]
    _send(server, connection_id, "SUBMIT_ACTION", {
        "matchId": "match-1",
        "playerId": "player_1",
        "clientActionId": "keep-player-1",
        "expectedRevision": 0,
        "action": {
            "kind": "CHOOSE_PROMPT_OPTION",
            "promptId": prompt["id"],
            "optionId": "keep",
            "payload": {},
        },
    })


def test_reconnect_protocol_round_trips_room_scoped_credentials() -> None:
    message = {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "reconnect-1",
        "type": "RECONNECT",
        "payload": {
            "roomCode": "ABC123",
            "playerId": "player_1",
            "reconnectToken": "private-reconnect-token",
            "lastRevision": 7,
        },
    }

    assert parse_client_message(serialize_client_message(message)) == message


def test_room_reconnect_rebinds_the_seat_and_rotates_private_credentials() -> None:
    tokens = iter(("host-token", "guest-token", "rotated-host-token"))
    room = Room(
        room_id="room-1",
        room_code="ABC123",
        host_connection_id="connection-old",
        clock=StepClock(),
        reconnect_token_factory=lambda: next(tokens),
    )
    room.join("connection-guest")
    host = room.host

    assert host.connected is True
    assert host.disconnected_at is None
    assert "reconnectToken" not in room.to_public_dict()
    assert all("reconnectToken" not in player for player in room.to_public_dict()["players"])

    assert room.mark_disconnected("connection-old") is host
    assert host.connected is False
    assert host.disconnected_at is not None

    rebound = room.reconnect(
        player_id="player_1",
        reconnect_token="host-token",
        connection_id="connection-new",
    )
    assert rebound is host
    assert host.connection_id == "connection-new"
    assert host.connected is True
    assert host.disconnected_at is None
    assert host.reconnect_token == "rotated-host-token"

    with pytest.raises(RoomError) as stale:
        room.reconnect(
            player_id="player_1",
            reconnect_token="host-token",
            connection_id="connection-third",
        )
    assert stale.value.code == "INVALID_RECONNECT_TOKEN"

    room.close()
    assert all(player.reconnect_token is None for player in room.players)


def test_service_disconnect_reconnect_is_private_rotating_and_timer_backed() -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    _send(server, "a", "CREATE_ROOM", {"displayName": "Alice"})
    _send(server, "b", "JOIN_ROOM", {"roomCode": "ABC123", "displayName": "Bob"})

    host_state = _latest(messages["a"], "ROOM_STATE")
    guest_state = _latest(messages["b"], "ROOM_STATE")
    host_token = host_state["reconnectToken"]
    guest_token = guest_state["reconnectToken"]
    assert host_token != guest_token
    assert guest_token not in repr(messages["a"])
    assert host_token not in repr(messages["b"])

    server.disconnect("a")
    assert len(timer_factory.timers) == 1
    assert timer_factory.timers[0].delay == 45
    disconnected = _latest(messages["b"], "ROOM_STATE")
    host_public = next(
        player for player in disconnected["players"] if player["playerId"] == "player_1"
    )
    assert host_public["connected"] is False
    assert host_public["disconnectedAt"] is not None

    messages["new-a"] = []
    server.connect("new-a", messages["new-a"].append)
    _send(server, "new-a", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_1",
        "reconnectToken": host_token,
        "lastRevision": 0,
    })

    restored_room = _latest(messages["new-a"], "ROOM_STATE")
    assert restored_room["playerId"] == "player_1"
    assert restored_room["reconnectToken"] != host_token
    assert timer_factory.timers[0].cancelled is True
    assert all(player["connected"] for player in restored_room["players"])
    rotated_token = restored_room["reconnectToken"]
    assert rotated_token not in repr(messages["b"])

    messages["stale"] = []
    server.connect("stale", messages["stale"].append)
    _send(server, "stale", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_1",
        "reconnectToken": host_token,
    })
    assert _latest(messages["stale"], "ERROR")["code"] == "INVALID_RECONNECT_TOKEN"

    messages["duplicate"] = []
    server.connect("duplicate", messages["duplicate"].append)
    _send(server, "duplicate", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_1",
        "reconnectToken": rotated_token,
    })
    assert _latest(messages["duplicate"], "ERROR")["code"] == "DUPLICATE_CONNECTION"


@pytest.mark.parametrize("disconnected_connection", ["a", "b"])
def test_disconnect_during_own_or_opponent_turn_restores_authoritative_state(
    disconnected_connection: str,
) -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    tokens = _start_match(server, messages)
    player_id = "player_1" if disconnected_connection == "a" else "player_2"
    match = server.match_for_room("ABC123")
    assert match is not None
    revision_before = match.revision
    state_hash_before = match.state_hash()

    server.disconnect(disconnected_connection)
    assert match.revision == revision_before
    assert match.state_hash() == state_hash_before

    replacement = f"new-{disconnected_connection}"
    messages[replacement] = []
    server.connect(replacement, messages[replacement].append)
    _send(server, replacement, "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": player_id,
        "reconnectToken": tokens[player_id],
        "lastRevision": revision_before,
    })
    snapshot = _latest(messages[replacement], "STATE_SNAPSHOT")
    assert snapshot["playerId"] == player_id
    assert snapshot["view"]["revision"] == revision_before
    assert snapshot["view"]["stateHash"] == state_hash_before
    assert snapshot["connectionStatus"] == {
        "player_1": {"connected": True, "disconnectedAt": None},
        "player_2": {"connected": True, "disconnectedAt": None},
    }


def test_invalid_reconnect_token_keeps_the_seat_reserved_and_timer_active() -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    _send(server, "a", "CREATE_ROOM")
    server.disconnect("a")

    messages["replacement"] = []
    server.connect("replacement", messages["replacement"].append)
    _send(server, "replacement", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_1",
        "reconnectToken": "not-the-issued-token",
    })

    assert _latest(messages["replacement"], "ERROR")["code"] == "INVALID_RECONNECT_TOKEN"
    assert timer_factory.timers[0].cancelled is False
    assert server.room_for_code("ABC123").host.connected is False


def test_reconnect_with_stale_revision_receives_current_snapshot() -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    tokens = _start_match(server, messages)
    _submit_keep(server, messages)
    match = server.match_for_room("ABC123")
    assert match is not None and match.revision == 1

    server.disconnect("b")
    messages["new-b"] = []
    server.connect("new-b", messages["new-b"].append)
    _send(server, "new-b", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_2",
        "reconnectToken": tokens["player_2"],
        "lastRevision": 0,
    })

    snapshot = _latest(messages["new-b"], "STATE_SNAPSHOT")
    assert snapshot["view"]["revision"] == 1
    assert snapshot["view"]["stateHash"] == match.state_hash()
    assert snapshot["view"]["prompt"] is not None


def test_finished_match_can_reconnect_to_the_same_ready_room() -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    tokens = _start_match(server, messages)
    server.disconnect("b")
    _send(server, "a", "SUBMIT_ACTION", {
        "matchId": "match-1",
        "playerId": "player_1",
        "clientActionId": "surrender-player-1",
        "expectedRevision": 0,
        "action": {"kind": "SURRENDER"},
    })
    assert server.room_for_code("ABC123").status.value == "READY_CHECK"

    messages["new-b"] = []
    server.connect("new-b", messages["new-b"].append)
    _send(server, "new-b", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_2",
        "reconnectToken": tokens["player_2"],
    })

    assert _latest(messages["new-b"], "ROOM_STATE")["status"] == "READY_CHECK"
    assert not any(message["type"] == "STATE_SNAPSHOT" for message in messages["new-b"])


def test_disconnect_timeout_forfeits_and_expires_that_seat() -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    tokens = _start_match(server, messages)
    room = server.room_for_code("ABC123")
    server.disconnect("a")

    timer_factory.timers[0].fire()

    assert room.status.value == "CLOSED"
    assert room.host.reconnect_token is None
    assert _latest(messages["b"], "STATE_SNAPSHOT")["view"]["gameOver"] is not None
    assert _latest(messages["b"], "ROOM_CLOSED")["roomCode"] == "ABC123"

    messages["late"] = []
    server.connect("late", messages["late"].append)
    _send(server, "late", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_1",
        "reconnectToken": tokens["player_1"],
    })
    assert _latest(messages["late"], "ERROR")["code"] == "ROOM_NOT_FOUND"


def test_both_disconnect_use_one_timer_per_seat_and_close_after_both_expire() -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    _start_match(server, messages)
    room = server.room_for_code("ABC123")
    match = server.match_for_room("ABC123")
    assert match is not None

    server.disconnect("a")
    server.disconnect("a")
    server.disconnect("b")
    assert len(timer_factory.timers) == 2
    assert all(timer.started for timer in timer_factory.timers)

    timer_factory.timers[0].fire()
    assert room.status.value == "CLOSED"
    assert match.revision == 1
    timer_factory.timers[1].fire()
    assert room.status.value == "CLOSED"
    assert all(player.reconnect_token is None for player in room.players)

    with pytest.raises(RoomError) as closed:
        server.room_for_code("ABC123")
    assert closed.value.code == "ROOM_NOT_FOUND"


def test_room_close_cancels_disconnect_timer_and_invalidates_token() -> None:
    timer_factory = TimerFactory()
    server, messages = _connected_server(timer_factory)
    _send(server, "a", "CREATE_ROOM")
    token = _latest(messages["a"], "ROOM_STATE")["reconnectToken"]
    server.disconnect("a")
    server.close_room("ABC123")
    assert timer_factory.timers[0].cancelled is True

    messages["late"] = []
    server.connect("late", messages["late"].append)
    _send(server, "late", "RECONNECT", {
        "roomCode": "ABC123",
        "playerId": "player_1",
        "reconnectToken": token,
    })
    assert _latest(messages["late"], "ERROR")["code"] == "ROOM_NOT_FOUND"
