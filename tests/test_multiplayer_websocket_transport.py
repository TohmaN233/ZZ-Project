from __future__ import annotations

from copy import deepcopy
import json
from queue import Queue
import time
from typing import Any

import pytest

from zz.multiplayer.compatibility import hello_compatibility_payload
from zz.multiplayer.client import ClientConnectionState, MultiplayerClientStore
import zz.multiplayer.transport as transport_module
from zz.multiplayer.transport import WebSocketTransport


class FakeClosed(Exception):
    pass


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.received: Queue[str | bytes | BaseException] = Queue()
        self.close_calls = 0
        self.closed = False
        self.send_error: BaseException | None = None

    def send(self, message: str) -> None:
        if self.send_error is not None:
            raise self.send_error
        if self.closed:
            raise FakeClosed("socket is closed")
        self.sent.append(message)

    def recv(self) -> str | bytes:
        value = self.received.get(timeout=1)
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.close_calls += 1
        if self.closed:
            return
        self.closed = True
        self.received.put(FakeClosed("socket is closed"))

    def emit(self, message: dict[str, Any], *, as_bytes: bool = False) -> None:
        encoded = json.dumps(message, ensure_ascii=False)
        self.received.put(encoded.encode("utf-8") if as_bytes else encoded)

    def fail(self, error: BaseException) -> None:
        self.received.put(error)


class FakeConnector:
    def __init__(self, *results: FakeSocket | BaseException) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeSocket:
        self.calls.append((url, deepcopy(kwargs)))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def wait_until(predicate: Any, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_connect_sends_one_hello_and_serializes_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket()
    connector = FakeConnector(socket)
    monkeypatch.setattr(transport_module, "websocket_connect", connector)
    transport = WebSocketTransport(
        "ws://127.0.0.1:32145/multiplayer",
        max_size=4096,
        open_timeout=3,
        ping_interval=7,
        ping_timeout=5,
        close_timeout=2,
    )

    transport.connect()

    assert transport.connected is True
    assert len(socket.sent) == 1
    hello = json.loads(socket.sent[0])
    assert hello["protocolVersion"] == 1
    assert hello["type"] == "HELLO"
    assert hello["messageId"]
    assert hello["payload"] == hello_compatibility_payload()
    assert connector.calls == [("ws://127.0.0.1:32145/multiplayer", {
        "max_size": 4096,
        "open_timeout": 3,
        "ping_interval": 7,
        "ping_timeout": 5,
        "close_timeout": 2,
    })]
    with pytest.raises(RuntimeError, match="already connected"):
        transport.connect()
    assert len(socket.sent) == 1

    outbound = {"type": "PING", "payload": {"label": "中文", "values": [1]}}
    transport.send(outbound)
    outbound["payload"]["values"].append(2)
    assert json.loads(socket.sent[-1]) == {
        "type": "PING",
        "payload": {"label": "中文", "values": [1]},
    }

    transport.close()
    transport.close()
    assert transport.connected is False
    assert transport._receiver_thread is None
    assert socket.close_calls >= 1


def test_receiver_dispatches_isolated_copies_and_disconnect_can_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_socket = FakeSocket()
    second_socket = FakeSocket()
    connector = FakeConnector(first_socket, second_socket)
    monkeypatch.setattr(transport_module, "websocket_connect", connector)
    transport = WebSocketTransport("ws://server/multiplayer", close_timeout=0.1)
    first_messages: list[dict[str, Any]] = []
    second_messages: list[dict[str, Any]] = []

    def mutate_first(message: dict[str, Any]) -> None:
        first_messages.append(message)
        message["payload"]["players"].append("local-only")

    transport.on_message(mutate_first)
    transport.on_message(second_messages.append)
    transport.connect()
    first_socket.emit(
        {"type": "ROOM_STATE", "payload": {"players": ["P1"]}},
        as_bytes=True,
    )
    wait_until(lambda: len(second_messages) == 1)
    assert first_messages[0]["payload"]["players"] == ["P1", "local-only"]
    assert second_messages[0]["payload"]["players"] == ["P1"]

    first_socket.fail(FakeClosed("network lost"))
    wait_until(lambda: not transport.connected)
    assert isinstance(transport.last_error, FakeClosed)

    transport.connect()
    assert transport.connected is True
    assert len(first_socket.sent) == 1
    assert len(second_socket.sent) == 1
    assert json.loads(second_socket.sent[0])["type"] == "HELLO"
    transport.close()


def test_connect_failure_resets_state_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket()
    connector = FakeConnector(OSError("connection refused"), socket)
    monkeypatch.setattr(transport_module, "websocket_connect", connector)
    transport = WebSocketTransport("ws://server/multiplayer", close_timeout=0.1)

    with pytest.raises(OSError, match="connection refused"):
        transport.connect()
    assert transport.connected is False
    assert isinstance(transport.last_error, OSError)

    transport.connect()
    assert transport.connected is True
    assert len(socket.sent) == 1
    transport.close()


def test_send_failure_closes_connection_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_socket = FakeSocket()
    second_socket = FakeSocket()
    connector = FakeConnector(first_socket, second_socket)
    monkeypatch.setattr(transport_module, "websocket_connect", connector)
    transport = WebSocketTransport("ws://server/multiplayer", close_timeout=0.1)
    transport.connect()
    first_socket.send_error = OSError("write failed")

    with pytest.raises(OSError, match="write failed"):
        transport.send({"type": "PING", "payload": {}})
    assert transport.connected is False
    assert isinstance(transport.last_error, OSError)
    assert transport._receiver_thread is None

    transport.connect()
    assert transport.connected is True
    assert json.loads(second_socket.sent[0])["type"] == "HELLO"
    transport.close()


def test_client_keeps_full_pending_metadata_until_matching_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket()
    monkeypatch.setattr(
        transport_module,
        "websocket_connect",
        FakeConnector(socket),
    )
    store = MultiplayerClientStore(
        WebSocketTransport("ws://server/multiplayer", close_timeout=0.1)
    )
    store.connect()
    socket.emit({
        "type": "HELLO_ACCEPTED",
        "payload": {"connectionId": "connection-1", "playerId": "player-1"},
    })
    socket.emit({
        "type": "MATCH_STARTED",
        "matchId": "match-1",
        "payload": {
            "playerId": "player-1",
            "view": {"revision": 8, "players": {"you": {"life": 10}}},
        },
    })
    wait_until(lambda: store.status is ClientConnectionState.IN_MATCH)
    canonical_before = store.gameplay_view

    store.submit_action(
        {"kind": "CHOOSE_PROMPT_OPTION", "optionId": "keep"},
        client_action_id="action-1",
    )
    assert store.pending_action == {
        "matchId": "match-1",
        "playerId": "player-1",
        "clientActionId": "action-1",
        "expectedRevision": 8,
        "action": {"kind": "CHOOSE_PROMPT_OPTION", "optionId": "keep"},
    }
    assert store.gameplay_view == canonical_before
    assert store.can_submit_action is False

    socket.emit({
        "type": "ACTION_RESULT",
        "payload": {"clientActionId": "another-action", "result": {"accepted": True}},
    })
    wait_until(lambda: store.last_action_result is not None)
    assert store.pending_action_id == "action-1"
    assert store.gameplay_view == canonical_before

    socket.emit({
        "type": "ACTION_RESULT",
        "payload": {"clientActionId": "action-1", "result": {"accepted": True}},
    })
    wait_until(lambda: store.pending_action is None)
    assert store.gameplay_view == canonical_before
    assert store.can_submit_action is True
    store.close()
