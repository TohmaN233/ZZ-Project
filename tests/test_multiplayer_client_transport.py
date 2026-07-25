from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

import pytest

from zz.multiplayer.client import ClientConnectionState, MultiplayerClientStore
from zz.multiplayer.transport import InMemoryTransport
from zz.deckcode0 import DECKCODE0_YELLOW_FORCES, KANATANA_YELLOW_RECIPE


class FakeEndpoint:
    def __init__(self) -> None:
        self.connections: dict[str, Callable[[Mapping[str, Any]], None]] = {}
        self.received: list[tuple[str, dict[str, Any]]] = []
        self.disconnected: list[str] = []

    def connect(
        self,
        connection_id: str,
        emit: Callable[[Mapping[str, Any]], None],
    ) -> None:
        if connection_id in self.connections:
            raise RuntimeError("duplicate connection")
        self.connections[connection_id] = emit
        emit({
            "type": "WELCOME",
            "payload": {
                "connectionId": connection_id,
                "playerId": f"player_{len(self.connections)}",
            },
        })

    def receive(self, connection_id: str, message: Mapping[str, Any]) -> None:
        self.received.append((connection_id, deepcopy(dict(message))))

    def disconnect(self, connection_id: str) -> None:
        self.disconnected.append(connection_id)
        self.connections.pop(connection_id, None)

    def emit(self, connection_id: str, message: Mapping[str, Any]) -> None:
        self.connections[connection_id](message)

    def broadcast(self, message: Mapping[str, Any]) -> None:
        for emit in tuple(self.connections.values()):
            emit(message)


def test_in_memory_transport_lifecycle_and_copy_isolation() -> None:
    endpoint = FakeEndpoint()
    transport = InMemoryTransport(endpoint, "connection-a")
    first_messages: list[dict[str, Any]] = []
    second_messages: list[dict[str, Any]] = []

    unsubscribe_first = transport.on_message(first_messages.append)
    unsubscribe_second = transport.on_message(second_messages.append)
    transport.connect()

    assert transport.connected is True
    assert first_messages[0]["payload"]["connectionId"] == "connection-a"
    with pytest.raises(RuntimeError, match="already connected"):
        transport.connect()

    source = {"type": "ROOM_STATE", "payload": {"players": ["P1"]}}
    endpoint.emit("connection-a", source)
    source["payload"]["players"].append("P2")
    first_messages[-1]["payload"]["players"].append("local-only")
    assert second_messages[-1]["payload"]["players"] == ["P1"]

    unsubscribe_first()
    unsubscribe_first()
    endpoint.emit("connection-a", {"type": "ROOM_STATE", "payload": {}})
    assert len(first_messages) == 2
    assert len(second_messages) == 3
    unsubscribe_second()

    outbound = {"type": "PING", "payload": {"values": [1]}}
    transport.send(outbound)
    outbound["payload"]["values"].append(2)
    assert endpoint.received[-1][1]["payload"]["values"] == [1]

    transport.close()
    transport.close()
    assert endpoint.disconnected == ["connection-a"]
    assert transport.connected is False
    with pytest.raises(RuntimeError, match="not connected"):
        transport.send({"type": "PING"})


def test_two_client_stores_keep_independent_server_owned_state() -> None:
    endpoint = FakeEndpoint()
    first = MultiplayerClientStore(InMemoryTransport(endpoint, "first"))
    second = MultiplayerClientStore(InMemoryTransport(endpoint, "second"))

    first.connect()
    second.connect()
    assert first.status is ClientConnectionState.CONNECTED
    assert second.status is ClientConnectionState.CONNECTED
    assert first.player_id == "player_1"
    assert second.player_id == "player_2"

    shared_room = {
        "type": "ROOM_STATE",
        "payload": {
            "roomCode": "ABCD12",
            "phase": "READY_CHECK",
            "players": [{"playerId": "player_1"}, {"playerId": "player_2"}],
        },
    }
    endpoint.broadcast(shared_room)
    first_room = first.room_state
    assert first_room is not None
    first_room["players"].clear()
    assert len(second.room_state["players"]) == 2
    assert len(first.room_state["players"]) == 2
    assert first.status is ClientConnectionState.IN_ROOM
    assert second.status is ClientConnectionState.IN_ROOM

    first_view = {"revision": 0, "players": {"you": {"hand": ["secret-a"]}}}
    second_view = {"revision": 0, "players": {"you": {"hand": ["secret-b"]}}}
    endpoint.emit("first", {
        "type": "MATCH_STARTED",
        "matchId": "match-1",
        "payload": {"playerId": "player_1", "view": first_view},
    })
    endpoint.emit("second", {
        "type": "MATCH_STARTED",
        "matchId": "match-1",
        "payload": {"playerId": "player_2", "view": second_view},
    })
    first_view["players"]["you"]["hand"].clear()
    assert first.gameplay_view["players"]["you"]["hand"] == ["secret-a"]
    assert second.gameplay_view["players"]["you"]["hand"] == ["secret-b"]
    assert first.status is ClientConnectionState.IN_MATCH
    assert second.status is ClientConnectionState.IN_MATCH


def test_action_pending_until_matching_ack_and_snapshots_are_canonical() -> None:
    endpoint = FakeEndpoint()
    store = MultiplayerClientStore(InMemoryTransport(endpoint, "first"))
    store.connect()
    endpoint.emit("first", {
        "type": "MATCH_STARTED",
        "matchId": "match-1",
        "payload": {
            "playerId": "player_1",
            "view": {"revision": 4, "players": {"you": {"life": 10}}},
        },
    })

    original_view = store.gameplay_view
    action_id = store.submit_action(
        {"kind": "CHOOSE_PROMPT_OPTION", "optionId": "keep"},
        client_action_id="action-1",
    )
    assert action_id == "action-1"
    assert store.pending_action_id == "action-1"
    assert store.can_submit_action is False
    assert store.gameplay_view == original_view
    with pytest.raises(RuntimeError, match="awaiting acknowledgement"):
        store.surrender(client_action_id="action-2")

    _, submitted = endpoint.received[-1]
    assert submitted["protocolVersion"] == 1
    assert submitted["messageId"]
    assert submitted["type"] == "SUBMIT_ACTION"
    assert submitted["payload"] == {
        "matchId": "match-1",
        "playerId": "player_1",
        "clientActionId": "action-1",
        "expectedRevision": 4,
        "action": {"kind": "CHOOSE_PROMPT_OPTION", "optionId": "keep"},
    }

    endpoint.emit("first", {
        "type": "ACTION_RESULT",
        "payload": {"clientActionId": "another-action", "result": {"accepted": True}},
    })
    assert store.pending_action_id == "action-1"
    endpoint.emit("first", {
        "type": "ACTION_RESULT",
        "payload": {
            "clientActionId": "action-1",
            "result": {"accepted": True, "revision": 5},
        },
    })
    assert store.pending_action_id is None
    assert store.can_submit_action is True
    assert store.gameplay_view == original_view

    endpoint.emit("first", {
        "type": "STATE_SNAPSHOT",
        "matchId": "match-1",
        "payload": {"view": {"revision": 5, "players": {"you": {"life": 9}}}},
    })
    assert store.gameplay_view["revision"] == 5
    assert store.gameplay_view["players"]["you"]["life"] == 9

    surrender_id = store.surrender(client_action_id="surrender-1")
    assert surrender_id == "surrender-1"
    assert endpoint.received[-1][1]["payload"]["action"] == {"kind": "SURRENDER"}
    endpoint.emit("first", {
        "type": "ACTION_RESULT",
        "payload": {
            "clientActionId": "surrender-1",
            "result": {"events": [{"kind": "MATCH_ENDED"}]},
        },
    })
    assert store.pending_action_id is None
    assert store.status is ClientConnectionState.MATCH_FINISHED


def test_helpers_error_room_close_and_listener_cleanup() -> None:
    endpoint = FakeEndpoint()
    store = MultiplayerClientStore(InMemoryTransport(endpoint, "first"))
    store.connect()

    store.create_room()
    store.join_room("ROOM42")
    store.select_deck(KANATANA_YELLOW_RECIPE, DECKCODE0_YELLOW_FORCES)
    store.set_ready(True)
    store.request_sync()
    assert [message["type"] for _, message in endpoint.received] == [
        "CREATE_ROOM",
        "JOIN_ROOM",
        "SELECT_DECK",
        "SET_READY",
        "REQUEST_SYNC",
    ]

    endpoint.emit("first", {
        "type": "ERROR",
        "payload": {"code": "ROOM_NOT_FOUND", "message": "missing", "fatal": True},
    })
    assert store.status is ClientConnectionState.ERROR
    assert store.last_error["code"] == "ROOM_NOT_FOUND"
    with pytest.raises(RuntimeError, match="cannot send from ERROR"):
        store.create_room()

    endpoint.emit("first", {"type": "ROOM_CLOSED", "payload": {}})
    assert store.status is ClientConnectionState.CONNECTED
    assert store.room_state is None
    assert store.gameplay_view is None

    store.close()
    store.close()
    assert store.status is ClientConnectionState.OFFLINE
    assert endpoint.disconnected == ["first"]

    messages_before = deepcopy(store.welcome)
    assert messages_before is None
