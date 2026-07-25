from __future__ import annotations

import json

import pytest

from zz.multiplayer.compatibility import (
    compatibility_payload,
    hello_compatibility_payload,
)
from zz.multiplayer.protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    parse_client_hello,
    parse_client_message,
    parse_server_message,
    serialize_client_message,
    serialize_server_message,
    validate_client_envelope,
    validate_server_envelope,
)


def _client(message_type: str, payload: dict | None = None) -> dict:
    if message_type == "HELLO" and payload is None:
        payload = hello_compatibility_payload()
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "client-message-1",
        "type": message_type,
        "payload": payload or {},
    }


def _server(message_type: str, payload: dict | None = None) -> dict:
    if message_type == "WELCOME" and payload is not None:
        payload = {**payload, "compatibility": compatibility_payload()}
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "server-message-1",
        "type": message_type,
        "payload": payload or {},
    }


@pytest.mark.parametrize(
    ("message_type", "payload"),
    [
        ("CREATE_ROOM", {"displayName": "Alice"}),
        ("JOIN_ROOM", {"roomCode": "ABC123", "displayName": "Bob"}),
        ("SELECT_DECK", {"deck": {"CARD_001": 3}, "forces": ["F01", "F02"], "profile": {"codemanId": "codeman-1", "playmatId": "playmat-1"}}),
        ("SET_READY", {"ready": True}),
        (
            "SUBMIT_ACTION",
            {
                "matchId": "match-1",
                "playerId": "player_1",
                "clientActionId": "action-1",
                "expectedRevision": 0,
                "action": {
                    "kind": "CHOOSE_PROMPT_OPTION",
                    "promptId": "prompt-1",
                    "optionId": "option-1",
                    "payload": {},
                },
            },
        ),
        ("REQUEST_SYNC", {"matchId": "match-1"}),
        ("LEAVE_ROOM", {}),
    ],
)
def test_client_gameplay_messages_round_trip(message_type: str, payload: dict) -> None:
    message = _client(message_type, payload)

    encoded = serialize_client_message(message)

    assert parse_client_message(encoded) == message


def test_hello_is_accepted_only_by_the_handshake_parser() -> None:
    message = _client("HELLO")

    assert parse_client_hello(json.dumps(message)) == message
    with pytest.raises(ProtocolError) as gameplay_error:
        validate_client_envelope(message)
    assert gameplay_error.value.code == "INVALID_MESSAGE"
    assert gameplay_error.value.fatal is True


@pytest.mark.parametrize(
    ("message", "code", "fatal"),
    [
        ([], "INVALID_MESSAGE", False),
        ({"protocolVersion": PROTOCOL_VERSION}, "INVALID_MESSAGE", False),
        (
            {
                **_client("LEAVE_ROOM"),
                "unexpected": True,
            },
            "INVALID_MESSAGE",
            False,
        ),
        (
            {
                **_client("LEAVE_ROOM"),
                "protocolVersion": PROTOCOL_VERSION + 1,
            },
            "PROTOCOL_VERSION_MISMATCH",
            True,
        ),
        (_client("NOT_A_MESSAGE"), "UNKNOWN_MESSAGE_TYPE", False),
    ],
)
def test_client_envelope_rejects_invalid_shapes(message, code: str, fatal: bool) -> None:
    with pytest.raises(ProtocolError) as error:
        validate_client_envelope(message)

    assert error.value.code == code
    assert error.value.fatal is fatal


@pytest.mark.parametrize(
    "message",
    [
        _client("JOIN_ROOM", {"roomCode": "abc123"}),
        _client("JOIN_ROOM", {"roomCode": "ABC12"}),
        _client("JOIN_ROOM", {"roomCode": "ABC123", "extra": True}),
        _client("CREATE_ROOM", {"displayName": "x" * 41}),
        _client("SET_READY", {"ready": 1}),
        _client("LEAVE_ROOM", {"roomCode": "ABC123"}),
    ],
)
def test_client_payloads_reject_bad_fields_and_boundaries(message: dict) -> None:
    with pytest.raises(ProtocolError) as error:
        validate_client_envelope(message)

    assert error.value.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    "payload",
    [
        {"deck": {}, "forces": ["F01", "F02"]},
        {"deck": {"": 1}, "forces": ["F01", "F02"]},
        {"deck": {"CARD_001": True}, "forces": ["F01", "F02"]},
        {"deck": {"CARD_001": 0}, "forces": ["F01", "F02"]},
        {"deck": {"CARD_001": 1}, "forces": ["F01"]},
        {"deck": {"CARD_001": 1}, "forces": ["F01", "F02", "F03"]},
    ],
)
def test_select_deck_rejects_invalid_maps_counts_and_force_lengths(payload: dict) -> None:
    with pytest.raises(ProtocolError) as error:
        validate_client_envelope(_client("SELECT_DECK", payload))

    assert error.value.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    "action_patch",
    [
        {"expectedRevision": True},
        {"expectedRevision": -1},
        {"action": {}},
        {"action": {"kind": "SURRENDER", "unknown": 1}},
        {
            "action": {
                "kind": "CHOOSE_PROMPT_OPTION",
                "promptId": "prompt-1",
                "optionId": "option-1",
            }
        },
    ],
)
def test_submit_action_rejects_invalid_basic_shape(action_patch: dict) -> None:
    payload = {
        "matchId": "match-1",
        "playerId": "player_1",
        "clientActionId": "action-1",
        "expectedRevision": 2,
        "action": {"kind": "SURRENDER"},
    }
    payload.update(action_patch)

    with pytest.raises(ProtocolError) as error:
        validate_client_envelope(_client("SUBMIT_ACTION", payload))

    assert error.value.code == "INVALID_MESSAGE"


def test_parser_rejects_invalid_json_and_oversize_before_decoding() -> None:
    with pytest.raises(ProtocolError) as invalid:
        parse_client_message("{not-json")
    assert invalid.value.code == "INVALID_MESSAGE"

    oversized = " " * (MAX_MESSAGE_BYTES + 1)
    with pytest.raises(ProtocolError) as too_large:
        parse_client_message(oversized)
    assert too_large.value.code == "MESSAGE_TOO_LARGE"
    assert too_large.value.fatal is True


def test_serializer_uses_utf8_byte_size_limit() -> None:
    message = _client("CREATE_ROOM", {"displayName": "中"})

    with pytest.raises(ProtocolError) as too_large:
        serialize_client_message(message, max_bytes=50)

    assert too_large.value.code == "MESSAGE_TOO_LARGE"


def test_parser_rejects_duplicate_json_keys_and_non_finite_numbers() -> None:
    duplicate = (
        '{"protocolVersion":1,"messageId":"a","messageId":"b",'
        '"type":"LEAVE_ROOM","payload":{}}'
    )
    with pytest.raises(ProtocolError) as duplicate_error:
        parse_client_message(duplicate)
    assert duplicate_error.value.code == "INVALID_MESSAGE"

    non_finite = json.dumps(_client("SET_READY", {"ready": True})).replace(
        '"ready": true', '"ready": NaN'
    )
    with pytest.raises(ProtocolError) as number_error:
        parse_client_message(non_finite)
    assert number_error.value.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    ("message_type", "payload"),
    [
        ("WELCOME", {"connectionId": "connection-1"}),
        (
            "ROOM_STATE",
            {
                "roomId": "room-1",
                "roomCode": "ABC123",
                "status": "READY_CHECK",
                "hostPlayerId": "player_1",
                "capacity": 2,
                "createdAt": 1.0,
                "updatedAt": 2.0,
                "startedAt": None,
                "finishedAt": None,
                "closedAt": None,
                "players": [],
                "playerId": "player_1",
            },
        ),
        (
            "MATCH_STARTED",
            {"matchId": "match-1", "playerId": "player_1", "view": {"revision": 0}},
        ),
        ("STATE_SNAPSHOT", {"matchId": "match-1", "view": {"revision": 1}}),
        (
            "ACTION_RESULT",
            {"clientActionId": "action-1", "result": {"accepted": True}, "view": {}},
        ),
        ("ERROR", {"code": "INVALID_MESSAGE", "message": "bad", "fatal": False}),
        ("ROOM_CLOSED", {"roomId": "room-1", "roomCode": "ABC123"}),
    ],
)
def test_server_messages_round_trip(message_type: str, payload: dict) -> None:
    message = _server(message_type, payload)

    encoded = serialize_server_message(message)

    assert parse_server_message(encoded) == message


def test_server_envelope_rejects_unknown_type_payload_and_metadata() -> None:
    with pytest.raises(ProtocolError) as unknown:
        validate_server_envelope(_server("NOPE"))
    assert unknown.value.code == "UNKNOWN_MESSAGE_TYPE"

    with pytest.raises(ProtocolError) as payload:
        validate_server_envelope(_server("ERROR", {
            "code": "INVALID_MESSAGE",
            "message": "bad",
            "fatal": False,
            "extra": True,
        }))
    assert payload.value.code == "INVALID_MESSAGE"

    bad_revision = {**_server("WELCOME", {"connectionId": "connection-1"}), "revision": True}
    with pytest.raises(ProtocolError) as revision:
        validate_server_envelope(bad_revision)
    assert revision.value.code == "INVALID_MESSAGE"
