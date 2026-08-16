from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from zz.multiplayer.compatibility import (
    PROTOCOL_VERSION,
    hello_compatibility_payload,
)

MAX_MESSAGE_BYTES = 262_144

_MAX_IDENTIFIER_LENGTH = 128
_MAX_DISPLAY_NAME_LENGTH = 40
_MAX_ERROR_MESSAGE_LENGTH = 512
_MAX_DECK_ENTRIES = 100
_MAX_JSON_COLLECTION_ITEMS = 512
_MAX_JSON_STRING_LENGTH = 4_096
_MAX_JSON_DEPTH = 12
_ROOM_CODE_PATTERN = re.compile(r"^[A-Z0-9]{6}$")

_CLIENT_MESSAGE_TYPES = {
    "HELLO",
    "CREATE_ROOM",
    "JOIN_ROOM",
    "RECONNECT",
    "SELECT_DECK",
    "SET_READY",
    "SELECT_OPENING_CHOICE",
    "SUBMIT_ACTION",
    "REQUEST_SYNC",
    "LEAVE_ROOM",
}
_SERVER_MESSAGE_TYPES = {
    "WELCOME",
    "ROOM_STATE",
    "MATCH_STARTED",
    "STATE_SNAPSHOT",
    "ACTION_RESULT",
    "ERROR",
    "ROOM_CLOSED",
}
_ROOM_STATUSES = {
    "CREATED",
    "WAITING_FOR_PLAYERS",
    "READY_CHECK",
    "STARTING",
    "RUNNING",
    "FINISHED",
    "CLOSED",
}


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, fatal: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fatal = fatal

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "fatal": self.fatal,
        }


def validate_client_envelope(
    message: Mapping[str, Any],
    *,
    allow_hello: bool = False,
) -> dict[str, Any]:
    envelope = _validate_envelope(message, server=False)
    message_type = envelope["type"]
    if message_type not in _CLIENT_MESSAGE_TYPES:
        raise ProtocolError(
            "UNKNOWN_MESSAGE_TYPE",
            f"unknown client message type {message_type!r}",
        )
    if message_type == "HELLO" and not allow_hello:
        raise ProtocolError(
            "INVALID_MESSAGE",
            "HELLO is only valid during connection handshake",
            fatal=True,
        )
    _CLIENT_PAYLOAD_VALIDATORS[message_type](envelope["payload"])
    return envelope


def validate_server_envelope(message: Mapping[str, Any]) -> dict[str, Any]:
    envelope = _validate_envelope(message, server=True)
    message_type = envelope["type"]
    if message_type not in _SERVER_MESSAGE_TYPES:
        raise ProtocolError(
            "UNKNOWN_MESSAGE_TYPE",
            f"unknown server message type {message_type!r}",
        )
    _SERVER_PAYLOAD_VALIDATORS[message_type](envelope["payload"])
    return envelope


def parse_client_message(
    raw: str | bytes | bytearray,
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> dict[str, Any]:
    return validate_client_envelope(_parse_json(raw, max_bytes=max_bytes))


def parse_client_hello(
    raw: str | bytes | bytearray,
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> dict[str, Any]:
    message = validate_client_envelope(
        _parse_json(raw, max_bytes=max_bytes),
        allow_hello=True,
    )
    if message["type"] != "HELLO":
        raise ProtocolError(
            "INVALID_MESSAGE",
            "the handshake layer accepts only HELLO",
            fatal=True,
        )
    return message


def parse_server_message(
    raw: str | bytes | bytearray,
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> dict[str, Any]:
    return validate_server_envelope(_parse_json(raw, max_bytes=max_bytes))


def serialize_client_message(
    message: Mapping[str, Any],
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> str:
    return _serialize_json(
        validate_client_envelope(message),
        max_bytes=max_bytes,
    )


def serialize_client_hello(
    message: Mapping[str, Any],
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> str:
    message_with_compatibility = deepcopy(dict(message))
    payload = message_with_compatibility.get("payload")
    if isinstance(payload, Mapping):
        message_with_compatibility["payload"] = {
            **hello_compatibility_payload(),
            **dict(payload),
        }
    validated = validate_client_envelope(
        message_with_compatibility,
        allow_hello=True,
    )
    if validated["type"] != "HELLO":
        raise ProtocolError(
            "INVALID_MESSAGE",
            "the handshake layer accepts only HELLO",
            fatal=True,
        )
    return _serialize_json(validated, max_bytes=max_bytes)


def serialize_server_message(
    message: Mapping[str, Any],
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> str:
    return _serialize_json(
        validate_server_envelope(message),
        max_bytes=max_bytes,
    )


def _validate_envelope(
    message: Mapping[str, Any],
    *,
    server: bool,
) -> dict[str, Any]:
    required = {"protocolVersion", "messageId", "type", "payload"}
    optional = {"matchId", "revision"} if server else set()
    envelope = _strict_object(
        message,
        required=required,
        optional=optional,
        label="message",
    )
    version = envelope["protocolVersion"]
    if isinstance(version, bool) or not isinstance(version, int):
        _invalid("protocolVersion must be an integer")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            "PROTOCOL_VERSION_MISMATCH",
            f"protocol version {version} is not supported",
            fatal=True,
        )
    _string(envelope["messageId"], "messageId", max_length=_MAX_IDENTIFIER_LENGTH)
    _string(envelope["type"], "type", max_length=64)
    if not isinstance(envelope["payload"], Mapping):
        _invalid("payload must be an object")
    if "matchId" in envelope:
        _identifier(envelope["matchId"], "matchId")
    if "revision" in envelope:
        _non_negative_int(envelope["revision"], "revision")
    return deepcopy(envelope)


def _validate_hello(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={
            "applicationVersion",
            "rulesVersion",
            "cardDatabaseChecksum",
        },
        label="HELLO payload",
    )
    _string(value["applicationVersion"], "applicationVersion", max_length=64)
    _string(value["rulesVersion"], "rulesVersion", max_length=64)
    checksum = _string(
        value["cardDatabaseChecksum"],
        "cardDatabaseChecksum",
        max_length=71,
    )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
        _invalid("cardDatabaseChecksum must be a SHA-256 checksum")


def _validate_create_room(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        optional={"displayName"},
        label="CREATE_ROOM payload",
    )
    if "displayName" in value:
        _display_name(value["displayName"])


def _validate_join_room(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"roomCode"},
        optional={"displayName"},
        label="JOIN_ROOM payload",
    )
    _room_code(value["roomCode"])
    if "displayName" in value:
        _display_name(value["displayName"])


def _validate_reconnect(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"roomCode", "playerId", "reconnectToken"},
        optional={"lastRevision"},
        label="RECONNECT payload",
    )
    _room_code(value["roomCode"])
    _identifier(value["playerId"], "playerId")
    _identifier(value["reconnectToken"], "reconnectToken")
    if "lastRevision" in value:
        _non_negative_int(value["lastRevision"], "lastRevision")


def _validate_select_deck(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"deck", "forces"},
        optional={"profile"},
        label="SELECT_DECK payload",
    )
    deck = value["deck"]
    if not isinstance(deck, Mapping):
        _invalid("deck must be an object")
    if not deck or len(deck) > _MAX_DECK_ENTRIES:
        _invalid(f"deck must contain 1-{_MAX_DECK_ENTRIES} entries")
    for card_id, count in deck.items():
        _identifier(card_id, "deck card id")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 99:
            _invalid("deck counts must be integers from 1 to 99")
    forces = value["forces"]
    if not isinstance(forces, list) or len(forces) != 2:
        _invalid("forces must be an array containing exactly two ids")
    for force_id in forces:
        _identifier(force_id, "force id")
    if "profile" in value:
        profile = _strict_object(
            value["profile"],
            required=set(),
            optional={"codemanId", "playmatId"},
            label="profile",
        )
        for field in ("codemanId", "playmatId"):
            if profile.get(field) is not None:
                _identifier(profile[field], field)


def _validate_set_ready(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"ready"},
        label="SET_READY payload",
    )
    if not isinstance(value["ready"], bool):
        _invalid("ready must be a boolean")


def _validate_select_opening_choice(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"choice"},
        label="SELECT_OPENING_CHOICE payload",
    )
    if value["choice"] not in {"rock", "paper", "scissors"}:
        _invalid("choice must be rock, paper, or scissors")


def _validate_submit_action(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={
            "matchId",
            "playerId",
            "clientActionId",
            "expectedRevision",
            "action",
        },
        label="SUBMIT_ACTION payload",
    )
    _identifier(value["matchId"], "matchId")
    _identifier(value["playerId"], "playerId")
    _identifier(value["clientActionId"], "clientActionId")
    _non_negative_int(value["expectedRevision"], "expectedRevision")
    action = _strict_object(
        value["action"],
        required={"kind"},
        optional={"promptId", "optionId", "payload"},
        label="action",
    )
    kind = _string(action["kind"], "action.kind", max_length=64)
    if "promptId" in action:
        _identifier(action["promptId"], "action.promptId")
    if "optionId" in action:
        _identifier(action["optionId"], "action.optionId")
    if "payload" in action:
        if not isinstance(action["payload"], Mapping):
            _invalid("action.payload must be an object")
        _validate_json_value(action["payload"], "action.payload")
    if kind == "CHOOSE_PROMPT_OPTION":
        missing = {"promptId", "optionId", "payload"} - set(action)
        if missing:
            _invalid(
                "CHOOSE_PROMPT_OPTION requires promptId, optionId and payload"
            )
    elif kind == "SURRENDER" and set(action) != {"kind"}:
        _invalid("SURRENDER accepts no action fields except kind")


def _validate_request_sync(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        optional={"matchId"},
        label="REQUEST_SYNC payload",
    )
    if "matchId" in value:
        _identifier(value["matchId"], "matchId")


def _validate_leave_room(payload: Mapping[str, Any]) -> None:
    _strict_object(payload, label="LEAVE_ROOM payload")


def _validate_welcome(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"connectionId"},
        optional={"playerId", "compatibility"},
        label="WELCOME payload",
    )
    _identifier(value["connectionId"], "connectionId")
    if "playerId" in value:
        _identifier(value["playerId"], "playerId")
    if "compatibility" in value:
        _validate_compatibility(value["compatibility"])


def _validate_compatibility(value: Mapping[str, Any]) -> None:
    compatibility = _strict_object(
        value,
        required={
            "applicationVersion",
            "protocolVersion",
            "rulesVersion",
            "cardDatabaseChecksum",
        },
        label="compatibility",
    )
    _string(compatibility["applicationVersion"], "applicationVersion", max_length=64)
    protocol_version = compatibility["protocolVersion"]
    if isinstance(protocol_version, bool) or not isinstance(protocol_version, int):
        _invalid("compatibility.protocolVersion must be an integer")
    _string(compatibility["rulesVersion"], "rulesVersion", max_length=64)
    checksum = _string(
        compatibility["cardDatabaseChecksum"],
        "cardDatabaseChecksum",
        max_length=71,
    )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
        _invalid("compatibility.cardDatabaseChecksum must be a SHA-256 checksum")


def _validate_room_state(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={
            "roomId",
            "roomCode",
            "status",
            "hostPlayerId",
            "capacity",
            "createdAt",
            "updatedAt",
            "startedAt",
            "finishedAt",
            "closedAt",
            "players",
            "playerId",
        },
        optional={"matchId", "reconnectToken", "openingRound", "lastOpeningResult"},
        label="ROOM_STATE payload",
    )
    _identifier(value["roomId"], "roomId")
    _room_code(value["roomCode"])
    status = _string(value["status"], "status", max_length=32)
    if status not in _ROOM_STATUSES:
        _invalid(f"unknown room status {status!r}")
    _identifier(value["hostPlayerId"], "hostPlayerId")
    capacity = value["capacity"]
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity != 2:
        _invalid("capacity must be 2")
    for field_name in (
        "createdAt",
        "updatedAt",
        "startedAt",
        "finishedAt",
        "closedAt",
    ):
        _optional_number(value[field_name], field_name)
    players = value["players"]
    if not isinstance(players, list) or len(players) > 2:
        _invalid("players must be an array containing at most two players")
    for player in players:
        _validate_room_player(player)
    _identifier(value["playerId"], "playerId")
    if "matchId" in value:
        _identifier(value["matchId"], "matchId")
    if "reconnectToken" in value:
        _identifier(value["reconnectToken"], "reconnectToken")
    if "openingRound" in value:
        opening_round = value["openingRound"]
        if isinstance(opening_round, bool) or not isinstance(opening_round, int) or opening_round < 1:
            _invalid("openingRound must be a positive integer")
    if "lastOpeningResult" in value and value["lastOpeningResult"] is not None:
        _json_object(value["lastOpeningResult"], "lastOpeningResult")


def _validate_room_player(player: Mapping[str, Any]) -> None:
    value = _strict_object(
        player,
        required={
            "playerId",
            "displayName",
            "isHost",
            "joinedAt",
            "deckSelected",
            "ready",
        },
        optional={"connected", "disconnectedAt", "openingChoiceSubmitted"},
        label="room player",
    )
    _identifier(value["playerId"], "playerId")
    _display_name(value["displayName"])
    for field_name in ("isHost", "deckSelected", "ready"):
        if not isinstance(value[field_name], bool):
            _invalid(f"{field_name} must be a boolean")
    _optional_number(value["joinedAt"], "joinedAt", allow_none=False)
    if "connected" in value and not isinstance(value["connected"], bool):
        _invalid("connected must be a boolean")
    if "disconnectedAt" in value:
        _optional_number(value["disconnectedAt"], "disconnectedAt")
    if "openingChoiceSubmitted" in value and not isinstance(value["openingChoiceSubmitted"], bool):
        _invalid("openingChoiceSubmitted must be a boolean")


def _validate_match_started(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"matchId", "playerId", "view"},
        label="MATCH_STARTED payload",
    )
    _identifier(value["matchId"], "matchId")
    _identifier(value["playerId"], "playerId")
    _json_object(value["view"], "view")


def _validate_state_snapshot(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"matchId", "view"},
        optional={"playerId", "connectionStatus"},
        label="STATE_SNAPSHOT payload",
    )
    _identifier(value["matchId"], "matchId")
    _json_object(value["view"], "view")
    if "playerId" in value:
        _identifier(value["playerId"], "playerId")
    if "connectionStatus" in value:
        _validate_connection_status(value["connectionStatus"])


def _validate_connection_status(value: Any) -> None:
    statuses = _strict_object(
        value,
        required={"player_1", "player_2"},
        label="connectionStatus",
    )
    for player_id, status in statuses.items():
        item = _strict_object(
            status,
            required={"connected", "disconnectedAt"},
            label=f"connectionStatus.{player_id}",
        )
        if not isinstance(item["connected"], bool):
            _invalid(f"connectionStatus.{player_id}.connected must be a boolean")
        _optional_number(
            item["disconnectedAt"],
            f"connectionStatus.{player_id}.disconnectedAt",
        )


def _validate_action_result(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"clientActionId", "result", "view"},
        optional={"matchFinished"},
        label="ACTION_RESULT payload",
    )
    _identifier(value["clientActionId"], "clientActionId")
    _json_object(value["result"], "result")
    _json_object(value["view"], "view")
    if "matchFinished" in value and not isinstance(value["matchFinished"], bool):
        _invalid("matchFinished must be a boolean")


def _validate_error(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"code", "message", "fatal"},
        optional={"clientActionId"},
        label="ERROR payload",
    )
    _string(value["code"], "code", max_length=64)
    _string(
        value["message"],
        "message",
        min_length=0,
        max_length=_MAX_ERROR_MESSAGE_LENGTH,
    )
    if not isinstance(value["fatal"], bool):
        _invalid("fatal must be a boolean")
    if "clientActionId" in value:
        _identifier(value["clientActionId"], "clientActionId")


def _validate_room_closed(payload: Mapping[str, Any]) -> None:
    value = _strict_object(
        payload,
        required={"roomId", "roomCode"},
        label="ROOM_CLOSED payload",
    )
    _identifier(value["roomId"], "roomId")
    _room_code(value["roomCode"])


_CLIENT_PAYLOAD_VALIDATORS: dict[str, Callable[[Mapping[str, Any]], None]] = {
    "HELLO": _validate_hello,
    "CREATE_ROOM": _validate_create_room,
    "JOIN_ROOM": _validate_join_room,
    "RECONNECT": _validate_reconnect,
    "SELECT_DECK": _validate_select_deck,
    "SET_READY": _validate_set_ready,
    "SELECT_OPENING_CHOICE": _validate_select_opening_choice,
    "SUBMIT_ACTION": _validate_submit_action,
    "REQUEST_SYNC": _validate_request_sync,
    "LEAVE_ROOM": _validate_leave_room,
}
_SERVER_PAYLOAD_VALIDATORS: dict[str, Callable[[Mapping[str, Any]], None]] = {
    "WELCOME": _validate_welcome,
    "ROOM_STATE": _validate_room_state,
    "MATCH_STARTED": _validate_match_started,
    "STATE_SNAPSHOT": _validate_state_snapshot,
    "ACTION_RESULT": _validate_action_result,
    "ERROR": _validate_error,
    "ROOM_CLOSED": _validate_room_closed,
}


def _strict_object(
    value: Any,
    *,
    required: set[str] | None = None,
    optional: set[str] | None = None,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(f"{label} must be an object")
    result = dict(value)
    required_fields = required or set()
    allowed_fields = required_fields | (optional or set())
    missing = sorted(required_fields - set(result))
    if missing:
        _invalid(f"{label} is missing fields: {', '.join(missing)}")
    unknown = sorted(set(result) - allowed_fields)
    if unknown:
        _invalid(f"{label} has unknown fields: {', '.join(unknown)}")
    return result


def _display_name(value: Any) -> str:
    result = _string(
        value,
        "displayName",
        max_length=_MAX_DISPLAY_NAME_LENGTH,
    )
    if not result.strip():
        _invalid("displayName must not be blank")
    return result


def _identifier(value: Any, field_name: str) -> str:
    return _string(value, field_name, max_length=_MAX_IDENTIFIER_LENGTH)


def _room_code(value: Any) -> str:
    result = _string(value, "roomCode", max_length=6)
    if _ROOM_CODE_PATTERN.fullmatch(result) is None:
        _invalid("roomCode must contain exactly six uppercase letters or digits")
    return result


def _string(
    value: Any,
    field_name: str,
    *,
    min_length: int = 1,
    max_length: int,
) -> str:
    if not isinstance(value, str) or not min_length <= len(value) <= max_length:
        _invalid(
            f"{field_name} must be a string with {min_length}-{max_length} characters"
        )
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _invalid(f"{field_name} must be a non-negative integer")
    return value


def _optional_number(
    value: Any,
    field_name: str,
    *,
    allow_none: bool = True,
) -> None:
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(f"{field_name} must be a number")
    if not math.isfinite(float(value)):
        _invalid(f"{field_name} must be finite")


def _json_object(value: Any, field_name: str) -> None:
    if not isinstance(value, Mapping):
        _invalid(f"{field_name} must be an object")
    _validate_json_value(value, field_name)


def _validate_json_value(value: Any, field_name: str, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        _invalid(f"{field_name} exceeds maximum nesting depth")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if len(value) > _MAX_JSON_STRING_LENGTH:
            _invalid(f"{field_name} contains an oversized string")
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _invalid(f"{field_name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        if len(value) > _MAX_JSON_COLLECTION_ITEMS:
            _invalid(f"{field_name} contains too many object fields")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > _MAX_IDENTIFIER_LENGTH:
                _invalid(f"{field_name} contains an invalid object key")
            _validate_json_value(item, f"{field_name}.{key}", depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > _MAX_JSON_COLLECTION_ITEMS:
            _invalid(f"{field_name} contains an oversized array")
        for index, item in enumerate(value):
            _validate_json_value(item, f"{field_name}[{index}]", depth=depth + 1)
        return
    _invalid(f"{field_name} contains a non-JSON value")


def _parse_json(
    raw: str | bytes | bytearray,
    *,
    max_bytes: int,
) -> dict[str, Any]:
    limit = _message_size_limit(max_bytes)
    if isinstance(raw, str):
        try:
            encoded = raw.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ProtocolError("INVALID_MESSAGE", "message is not valid UTF-8") from exc
        text = raw
    elif isinstance(raw, (bytes, bytearray)):
        encoded = bytes(raw)
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("INVALID_MESSAGE", "message is not valid UTF-8") from exc
    else:
        raise ProtocolError("INVALID_MESSAGE", "message must be text or UTF-8 bytes")
    _check_message_size(len(encoded), limit)
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ProtocolError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("INVALID_MESSAGE", "message is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError("INVALID_MESSAGE", "message must be a JSON object")
    return parsed


def _serialize_json(message: Mapping[str, Any], *, max_bytes: int) -> str:
    limit = _message_size_limit(max_bytes)
    try:
        encoded = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProtocolError("INVALID_MESSAGE", "message is not JSON serializable") from exc
    try:
        size = len(encoded.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ProtocolError("INVALID_MESSAGE", "message is not valid UTF-8") from exc
    _check_message_size(size, limit)
    return encoded


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolError("INVALID_MESSAGE", f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ProtocolError("INVALID_MESSAGE", f"non-finite JSON number {value!r}")


def _message_size_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return value


def _check_message_size(size: int, limit: int) -> None:
    if size > limit:
        raise ProtocolError(
            "MESSAGE_TOO_LARGE",
            f"message size {size} exceeds {limit} bytes",
            fatal=True,
        )


def _invalid(message: str) -> None:
    raise ProtocolError("INVALID_MESSAGE", message)
