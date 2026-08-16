from __future__ import annotations

import json
import time
from contextlib import contextmanager
from threading import Thread

import pytest
from websockets.sync.client import connect as websocket_connect

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.client import ClientConnectionState, MultiplayerClientStore
from zz.multiplayer.compatibility import (
    compatibility_payload,
    hello_compatibility_payload,
)
from zz.multiplayer.protocol import (
    PROTOCOL_VERSION,
    parse_server_message,
    serialize_client_hello,
    serialize_client_message,
)
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.transport import WebSocketTransport
from zz.multiplayer.websocket_server import (
    WebSocketMultiplayerGateway,
    WebSocketServerConfig,
)


def _wait_until(predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_gateway_applies_configured_reconnect_grace_to_default_core() -> None:
    gateway = WebSocketMultiplayerGateway(config=WebSocketServerConfig(
        reconnect_grace_seconds=37.5,
    ))

    assert gateway.core.reconnect_grace_seconds == 37.5


@contextmanager
def _running_gateway(core: MultiplayerServer):
    gateway = WebSocketMultiplayerGateway(
        core,
        config=WebSocketServerConfig(
            host="127.0.0.1",
            port=0,
            heartbeat_interval_seconds=0.2,
            heartbeat_timeout_seconds=0.5,
        ),
    )
    with gateway.create_server() as server:
        thread = Thread(target=server.serve_forever, name="zz-test-websocket-server")
        thread.start()
        port = server.socket.getsockname()[1]
        try:
            yield f"ws://127.0.0.1:{port}"
        finally:
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


def test_two_websocket_clients_complete_authoritative_room_flow() -> None:
    core = MultiplayerServer(
        room_id_factory=lambda: "room-ws",
        room_code_factory=lambda: "WS1234",
        match_id_factory=lambda: "match-ws",
        seed_factory=lambda: 811,
    )
    with _running_gateway(core) as url:
        first_transport = WebSocketTransport(url, max_size=65_536)
        second_transport = WebSocketTransport(url, max_size=65_536)
        first = MultiplayerClientStore(first_transport)
        second = MultiplayerClientStore(second_transport)
        try:
            first.connect()
            second.connect()
            _wait_until(lambda: first.welcome is not None and second.welcome is not None)

            first.create_room(display_name="Alice")
            _wait_until(lambda: first.room_state is not None)
            second.join_room("WS1234", display_name="Bob")
            _wait_until(lambda: len(first.room_state["players"]) == 2)
            first.select_deck(KANATANA_YELLOW_RECIPE, DECKCODE0_YELLOW_FORCES)
            second.select_deck(DEMETE_GREEN_RECIPE, DECKCODE0_GREEN_FORCES)
            first.set_ready(True)
            second.set_ready(True)
            _wait_until(lambda: (
                first.status is ClientConnectionState.MATCH_STARTING
                and second.status is ClientConnectionState.MATCH_STARTING
            ))
            first.select_opening_choice("rock")
            second.select_opening_choice("scissors")
            _wait_until(lambda: (
                first.status is ClientConnectionState.IN_MATCH
                and second.status is ClientConnectionState.IN_MATCH
                and first.gameplay_view is not None
                and second.gameplay_view is not None
            ))

            assert first.gameplay_view["stateHash"] == second.gameplay_view["stateHash"]
            assert all(
                "iid" not in card
                for card in first.gameplay_view["players"]["opponent"]["hand"]
            )
            assert all(
                "iid" not in card
                for card in second.gameplay_view["players"]["opponent"]["hand"]
            )

            first.surrender(client_action_id="ws-surrender")
            _wait_until(lambda: (
                first.status is ClientConnectionState.IN_ROOM
                and second.status is ClientConnectionState.IN_ROOM
            ))
            assert first.gameplay_view is None
            assert second.gameplay_view is None
            assert first.room_state["roomCode"] == second.room_state["roomCode"] == "WS1234"

            core.close_room("WS1234")
            _wait_until(lambda: (
                first.status is ClientConnectionState.CONNECTED
                and second.status is ClientConnectionState.CONNECTED
            ))
        finally:
            first.close()
            second.close()


def test_handshake_version_mismatch_and_unknown_message_are_explicit() -> None:
    room_codes = iter(("ER1234",))
    core = MultiplayerServer(room_code_factory=lambda: next(room_codes))
    with _running_gateway(core) as url:
        with websocket_connect(url, proxy=None) as socket:
            socket.send(json.dumps({
                "protocolVersion": 999,
                "messageId": "bad-version",
                "type": "HELLO",
                "payload": {},
            }))
            error = parse_server_message(socket.recv())
            assert error["payload"]["code"] == "PROTOCOL_VERSION_MISMATCH"
            assert error["payload"]["fatal"] is True

        with websocket_connect(url, proxy=None) as socket:
            socket.send(serialize_client_hello({
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": "hello",
                "type": "HELLO",
                "payload": {},
            }))
            welcome = parse_server_message(socket.recv())
            assert welcome["type"] == "WELCOME"
            assert welcome["payload"]["compatibility"] == compatibility_payload()
            socket.send(json.dumps({
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": "unknown",
                "type": "REMOTE_SHELL",
                "payload": {},
            }))
            error = parse_server_message(socket.recv())
            assert error["payload"]["code"] == "UNKNOWN_MESSAGE_TYPE"
            assert error["payload"]["fatal"] is False

            socket.send(serialize_client_message({
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": "create",
                "type": "CREATE_ROOM",
                "payload": {"displayName": "Alice"},
            }))
            room_state = parse_server_message(socket.recv())
            assert room_state["type"] == "ROOM_STATE"
            assert room_state["payload"]["roomCode"] == "ER1234"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("applicationVersion", "9.9.9"),
        ("rulesVersion", "incompatible-rules"),
        ("cardDatabaseChecksum", f"sha256:{'0' * 64}"),
    ],
)
def test_gateway_rejects_game_compatibility_mismatch_before_connect(
    field: str,
    value: str,
) -> None:
    core = MultiplayerServer()
    with _running_gateway(core) as url:
        with websocket_connect(url, proxy=None) as socket:
            payload = {**hello_compatibility_payload(), field: value}
            socket.send(json.dumps({
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": f"mismatch-{field}",
                "type": "HELLO",
                "payload": payload,
            }))
            error = parse_server_message(socket.recv())

            assert error == {
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": error["messageId"],
                "type": "ERROR",
                "payload": {
                    "code": "INCOMPATIBLE_GAME_VERSION",
                    "message": "Client game version is incompatible with this server.",
                    "fatal": True,
                },
            }
            assert core._connections == {}


class _HoldingReconnectTimer:
    def __init__(self, _delay: float, _callback) -> None:
        self.cancelled = False

    def start(self) -> None:
        return None

    def cancel(self) -> None:
        self.cancelled = True


def test_websocket_disconnect_reconnect_restores_private_snapshot() -> None:
    core = MultiplayerServer(
        room_id_factory=lambda: "room-reconnect-ws",
        room_code_factory=lambda: "RC1234",
        match_id_factory=lambda: "match-reconnect-ws",
        seed_factory=lambda: 911,
        reconnect_grace_seconds=60,
        reconnect_timer_factory=_HoldingReconnectTimer,
    )
    with _running_gateway(core) as url:
        first_transport = WebSocketTransport(url, max_size=65_536)
        second_transport = WebSocketTransport(url, max_size=65_536)
        first = MultiplayerClientStore(first_transport)
        second = MultiplayerClientStore(second_transport)
        try:
            first.connect()
            second.connect()
            _wait_until(lambda: first.welcome is not None and second.welcome is not None)
            first.create_room(display_name="Alice")
            _wait_until(lambda: first.room_state is not None)
            second.join_room("RC1234", display_name="Bob")
            _wait_until(lambda: len(first.room_state["players"]) == 2)
            first.select_deck(KANATANA_YELLOW_RECIPE, DECKCODE0_YELLOW_FORCES)
            second.select_deck(DEMETE_GREEN_RECIPE, DECKCODE0_GREEN_FORCES)
            first.set_ready(True)
            second.set_ready(True)
            _wait_until(lambda: (
                first.status is ClientConnectionState.MATCH_STARTING
                and second.status is ClientConnectionState.MATCH_STARTING
            ))
            first.select_opening_choice("rock")
            second.select_opening_choice("scissors")
            _wait_until(lambda: (
                first.status is ClientConnectionState.IN_MATCH
                and second.status is ClientConnectionState.IN_MATCH
                and first.gameplay_view is not None
                and second.gameplay_view is not None
            ))

            original_token = first.room_state["reconnectToken"]
            original_revision = first.gameplay_view["revision"]
            first_transport.close()
            _wait_until(lambda: core.room_for_code("RC1234").host.connected is False)

            with websocket_connect(url, proxy=None) as recovered:
                recovered.send(serialize_client_hello({
                    "protocolVersion": PROTOCOL_VERSION,
                    "messageId": "reconnect-hello",
                    "type": "HELLO",
                    "payload": {},
                }))
                assert parse_server_message(recovered.recv())["type"] == "WELCOME"
                recovered.send(serialize_client_message({
                    "protocolVersion": PROTOCOL_VERSION,
                    "messageId": "reconnect-seat",
                    "type": "RECONNECT",
                    "payload": {
                        "roomCode": "RC1234",
                        "playerId": "player_1",
                        "reconnectToken": original_token,
                        "lastRevision": max(0, original_revision - 1),
                    },
                }))
                room_state = parse_server_message(recovered.recv())
                snapshot = parse_server_message(recovered.recv())

                assert room_state["type"] == "ROOM_STATE"
                assert room_state["payload"]["playerId"] == "player_1"
                assert room_state["payload"]["reconnectToken"] != original_token
                assert snapshot["type"] == "STATE_SNAPSHOT"
                assert snapshot["payload"]["playerId"] == "player_1"
                assert snapshot["payload"]["view"]["revision"] == original_revision
                assert snapshot["payload"]["connectionStatus"] == {
                    "player_1": {"connected": True, "disconnectedAt": None},
                    "player_2": {"connected": True, "disconnectedAt": None},
                }
                assert all(
                    "iid" not in card
                    for card in snapshot["payload"]["view"]["players"]["opponent"]["hand"]
                )
                assert original_token not in repr(second.room_state)
        finally:
            first.close()
            second.close()
