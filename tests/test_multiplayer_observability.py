from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pytest

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.client import MultiplayerClientStore
from zz.multiplayer.observability import StructuredEventSink
from zz.multiplayer.protocol import PROTOCOL_VERSION
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.transport import InMemoryTransport


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_structured_event_sink_emits_only_allowlisted_metadata() -> None:
    logger = logging.getLogger("zz.multiplayer.test.observability")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _ListHandler()
    logger.addHandler(handler)
    sink = StructuredEventSink(
        logger,
        now=lambda: datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
    )

    sink(
        "action_accepted",
        connectionId="connection-1",
        playerId="player_1",
        roomId="room-1",
        matchId="match-1",
        revision=7,
        messageType="SUBMIT_ACTION",
    )

    assert len(handler.messages) == 1
    assert json.loads(handler.messages[0]) == {
        "timestamp": "2026-07-10T12:00:00+00:00",
        "level": "INFO",
        "event": "action_accepted",
        "connectionId": "connection-1",
        "playerId": "player_1",
        "roomId": "room-1",
        "matchId": "match-1",
        "revision": 7,
        "messageType": "SUBMIT_ACTION",
    }


@pytest.mark.parametrize(
    "forbidden",
    ["reconnectToken", "hand", "deck", "snapshot", "displayName", "action"],
)
def test_structured_event_sink_rejects_private_or_unbounded_fields(forbidden: str) -> None:
    sink = StructuredEventSink(logging.getLogger("zz.multiplayer.test.rejection"))

    with pytest.raises(ValueError, match="forbidden fields"):
        sink("unsafe", **{forbidden: "must-not-log"})


def test_structured_event_sink_rejects_unbounded_event_and_field_values() -> None:
    sink = StructuredEventSink(logging.getLogger("zz.multiplayer.test.bounds"))

    with pytest.raises(ValueError, match="1-64"):
        sink("x" * 65)
    with pytest.raises(ValueError, match="exceeds 128"):
        sink("message_rejected", errorCode="x" * 129)


def test_server_emits_required_lifecycle_events_without_private_state() -> None:
    logger = logging.getLogger("zz.multiplayer.test.lifecycle")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _ListHandler()
    logger.addHandler(handler)

    server = MultiplayerServer(
        room_id_factory=lambda: "room-1",
        room_code_factory=lambda: "ABC123",
        match_id_factory=lambda: "match-1",
        seed_factory=lambda: 701,
        event_sink=StructuredEventSink(logger),
    )
    first = MultiplayerClientStore(InMemoryTransport(server, "connection-a"))
    second = MultiplayerClientStore(InMemoryTransport(server, "connection-b"))
    first.connect()
    second.connect()
    first.create_room(display_name="Alice")
    second.join_room("ABC123", display_name="Bob")
    first.select_deck(KANATANA_YELLOW_RECIPE, DECKCODE0_YELLOW_FORCES)
    second.select_deck(DEMETE_GREEN_RECIPE, DECKCODE0_GREEN_FORCES)
    first.set_ready(True)
    second.set_ready(True)
    first.select_opening_choice("rock")
    second.select_opening_choice("scissors")

    assert first.gameplay_view is not None
    prompt = first.gameplay_view["prompt"]
    second.submit_action({
        "kind": "CHOOSE_PROMPT_OPTION",
        "promptId": prompt["id"],
        "optionId": "keep",
        "payload": {},
    }, client_action_id="wrong-seat")
    assert second.room_state is not None
    reconnect_token = second.room_state["reconnectToken"]
    second.close()
    recovered_messages: list[dict] = []
    server.connect("connection-b-recovered", recovered_messages.append)
    server.receive("connection-b-recovered", {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "reconnect",
        "type": "RECONNECT",
        "payload": {
            "roomCode": "ABC123",
            "playerId": "player_2",
            "reconnectToken": reconnect_token,
            "lastRevision": 0,
        },
    })
    first.surrender(client_action_id="surrender")
    server.close_room("ABC123")
    first.close()
    server.disconnect("connection-b-recovered")

    records = [json.loads(message) for message in handler.messages]
    names = [record["event"] for record in records]
    assert {
        "connection_opened",
        "connection_closed",
        "room_created",
        "player_joined",
        "match_started",
        "action_accepted",
        "action_rejected",
        "player_disconnected",
        "player_reconnected",
        "match_ended",
        "room_closed",
    } <= set(names)
    serialized = json.dumps(records, sort_keys=True)
    assert "reconnectToken" not in serialized
    assert "private-reconnect" not in serialized
    assert "hand" not in serialized
    assert "deck" not in serialized
    assert "Alice" not in serialized
    assert "Bob" not in serialized


def test_per_connection_token_bucket_limits_before_dispatch_and_refills() -> None:
    now = [10.0]
    messages: list[dict] = []
    events: list[tuple[str, dict]] = []
    server = MultiplayerServer(
        room_id_factory=lambda: "room-1",
        room_code_factory=lambda: "ABC123",
        rate_limit_messages_per_second=2,
        rate_limit_burst=2,
        rate_clock=lambda: now[0],
        event_sink=lambda event, **fields: events.append((event, fields)),
    )
    transport = InMemoryTransport(server, "connection-a")
    transport.on_message(messages.append)
    transport.connect()

    transport.send({
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "create",
        "type": "CREATE_ROOM",
        "payload": {},
    })
    transport.send({
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "sync-1",
        "type": "REQUEST_SYNC",
        "payload": {},
    })
    before = len(messages)
    transport.send({
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "sync-limited",
        "type": "REQUEST_SYNC",
        "payload": {},
    })

    assert len(messages) == before + 1
    assert messages[-1]["type"] == "ERROR"
    assert messages[-1]["payload"] == {
        "code": "RATE_LIMITED",
        "message": "connection message rate limit exceeded",
        "fatal": False,
    }
    assert events[-1] == (
        "message_rate_limited",
        {
            "level": "WARNING",
            "connectionId": "connection-a",
            "errorCode": "RATE_LIMITED",
        },
    )

    now[0] += 0.5
    transport.send({
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "sync-refilled",
        "type": "REQUEST_SYNC",
        "payload": {},
    })
    assert messages[-1]["type"] == "ROOM_STATE"
