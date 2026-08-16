from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from zz.multiplayer.compatibility import PROTOCOL_VERSION
from zz.multiplayer.transport import MultiplayerTransport, Unsubscribe


class ClientConnectionState(str, Enum):
    OFFLINE = "OFFLINE"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    IN_ROOM = "IN_ROOM"
    MATCH_STARTING = "MATCH_STARTING"
    IN_MATCH = "IN_MATCH"
    MATCH_FINISHED = "MATCH_FINISHED"
    ERROR = "ERROR"


class MultiplayerClientStore:
    def __init__(self, transport: MultiplayerTransport):
        self.transport = transport
        self.status = ClientConnectionState.OFFLINE
        self.connection_id: str | None = None
        self.player_id: str | None = None
        self.match_id: str | None = None
        self._pending_action: dict[str, Any] | None = None
        self._welcome: dict[str, Any] | None = None
        self._room_state: dict[str, Any] | None = None
        self._gameplay_view: dict[str, Any] | None = None
        self._last_action_result: dict[str, Any] | None = None
        self._last_error: dict[str, Any] | None = None
        self._unsubscribe: Unsubscribe | None = None

    @property
    def welcome(self) -> dict[str, Any] | None:
        return deepcopy(self._welcome)

    @property
    def room_state(self) -> dict[str, Any] | None:
        return deepcopy(self._room_state)

    @property
    def gameplay_view(self) -> dict[str, Any] | None:
        return deepcopy(self._gameplay_view)

    @property
    def last_action_result(self) -> dict[str, Any] | None:
        return deepcopy(self._last_action_result)

    @property
    def last_error(self) -> dict[str, Any] | None:
        return deepcopy(self._last_error)

    @property
    def pending_action(self) -> dict[str, Any] | None:
        return deepcopy(self._pending_action)

    @property
    def pending_action_id(self) -> str | None:
        if self._pending_action is None:
            return None
        return _optional_string(self._pending_action.get("clientActionId"))

    @property
    def can_submit_action(self) -> bool:
        return (
            self.status is ClientConnectionState.IN_MATCH
            and self.pending_action_id is None
            and self._gameplay_view is not None
        )

    def connect(self) -> None:
        if self.status is not ClientConnectionState.OFFLINE:
            raise RuntimeError(f"client cannot connect from {self.status.value}")
        self.status = ClientConnectionState.CONNECTING
        self._unsubscribe = self.transport.on_message(self._handle_message)
        try:
            self.transport.connect()
        except Exception:
            self._remove_listener()
            self.status = ClientConnectionState.ERROR
            raise
        if self.status is ClientConnectionState.CONNECTING:
            self.status = ClientConnectionState.CONNECTED

    def close(self) -> None:
        self.transport.close()
        self._remove_listener()
        self.status = ClientConnectionState.OFFLINE
        self.connection_id = None
        self.player_id = None
        self.match_id = None
        self._pending_action = None
        self._welcome = None
        self._room_state = None
        self._gameplay_view = None
        self._last_action_result = None
        self._last_error = None

    def create_room(self, *, display_name: str = "Host") -> None:
        self._send("CREATE_ROOM", {"displayName": display_name})

    def join_room(self, room_code: str, *, display_name: str = "Guest") -> None:
        if not room_code:
            raise ValueError("room_code must not be empty")
        self._send("JOIN_ROOM", {
            "roomCode": room_code,
            "displayName": display_name,
        })

    def select_deck(
        self,
        deck_recipe: Mapping[str, int],
        force_ids: list[str] | tuple[str, str],
    ) -> None:
        if not isinstance(deck_recipe, Mapping):
            raise TypeError("deck_recipe must be a mapping")
        if not isinstance(force_ids, (list, tuple)):
            raise TypeError("force_ids must be a list or tuple")
        self._send("SELECT_DECK", {
            "deck": deepcopy(dict(deck_recipe)),
            "forces": list(force_ids),
        })

    def set_ready(self, ready: bool) -> None:
        if not isinstance(ready, bool):
            raise TypeError("ready must be a boolean")
        self._send("SET_READY", {"ready": ready})

    def select_opening_choice(self, choice: str) -> None:
        if choice not in {"rock", "paper", "scissors"}:
            raise ValueError("choice must be rock, paper, or scissors")
        self._send("SELECT_OPENING_CHOICE", {"choice": choice})

    def submit_action(
        self,
        action: Mapping[str, Any],
        *,
        client_action_id: str | None = None,
    ) -> str:
        if not isinstance(action, Mapping):
            raise TypeError("action must be a mapping")
        if not self.can_submit_action:
            if self.pending_action_id is not None:
                raise RuntimeError("an action is awaiting acknowledgement")
            raise RuntimeError("client is not ready to submit an action")
        action_id = client_action_id or str(uuid4())
        if not action_id:
            raise ValueError("client_action_id must not be empty")
        revision = self._gameplay_view.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise RuntimeError("canonical gameplay view has no valid revision")
        if not self.match_id or not self.player_id:
            raise RuntimeError("match and player identity are required")
        submitted = {
            "matchId": self.match_id,
            "playerId": self.player_id,
            "clientActionId": action_id,
            "expectedRevision": revision,
            "action": deepcopy(dict(action)),
        }
        self._pending_action = deepcopy(submitted)
        self._send("SUBMIT_ACTION", submitted)
        return action_id

    def surrender(self, *, client_action_id: str | None = None) -> str:
        return self.submit_action(
            {"kind": "SURRENDER"},
            client_action_id=client_action_id,
        )

    def request_sync(self) -> None:
        payload: dict[str, Any] = {}
        if self.match_id is not None:
            payload["matchId"] = self.match_id
        self._send("REQUEST_SYNC", payload)

    def _send(self, message_type: str, payload: Mapping[str, Any]) -> None:
        if self.status in {
            ClientConnectionState.OFFLINE,
            ClientConnectionState.CONNECTING,
            ClientConnectionState.ERROR,
        }:
            raise RuntimeError(f"client cannot send from {self.status.value}")
        self.transport.send({
            "protocolVersion": PROTOCOL_VERSION,
            "messageId": str(uuid4()),
            "type": message_type,
            "payload": deepcopy(dict(payload)),
        })

    def _handle_message(self, message: dict[str, Any]) -> None:
        if not isinstance(message, Mapping):
            raise TypeError("server message must be a mapping")
        message_type = message.get("type")
        if not isinstance(message_type, str) or not message_type:
            raise ValueError("server message type must be a non-empty string")
        payload = message.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("server message payload must be a mapping")
        payload_copy = deepcopy(dict(payload))

        handlers = {
            "WELCOME": self._handle_welcome,
            "HELLO_ACCEPTED": self._handle_welcome,
            "ROOM_STATE": self._handle_room_state,
            "MATCH_STARTED": self._handle_match_started,
            "STATE_SNAPSHOT": self._handle_state_snapshot,
            "ACTION_RESULT": self._handle_action_result,
            "ERROR": self._handle_error,
            "ROOM_CLOSED": self._handle_room_closed,
        }
        handler = handlers.get(message_type)
        if handler is None:
            raise ValueError(f"unsupported server message type {message_type!r}")
        handler(message, payload_copy)

    def _handle_welcome(
        self,
        _message: Mapping[str, Any],
        payload: dict[str, Any],
    ) -> None:
        self._welcome = payload
        self.connection_id = _optional_string(payload.get("connectionId"))
        self.player_id = _optional_string(payload.get("playerId"))
        self.status = ClientConnectionState.CONNECTED

    def _handle_room_state(
        self,
        _message: Mapping[str, Any],
        payload: dict[str, Any],
    ) -> None:
        self._room_state = payload
        self.player_id = _optional_string(payload.get("playerId")) or self.player_id
        phase = str(payload.get("status") or payload.get("phase") or "")
        if phase == "STARTING":
            self.status = ClientConnectionState.MATCH_STARTING
        elif phase == "RUNNING":
            self.status = ClientConnectionState.IN_MATCH
        elif phase == "FINISHED":
            self.status = ClientConnectionState.MATCH_FINISHED
        elif phase == "CLOSED":
            self.status = ClientConnectionState.CONNECTED
        else:
            self.match_id = None
            self._gameplay_view = None
            self._pending_action = None
            self.status = ClientConnectionState.IN_ROOM

    def _handle_match_started(
        self,
        message: Mapping[str, Any],
        payload: dict[str, Any],
    ) -> None:
        self.match_id = _optional_string(
            message.get("matchId", payload.get("matchId"))
        )
        self.player_id = _optional_string(payload.get("playerId")) or self.player_id
        view = payload.get("view")
        if not isinstance(view, Mapping):
            raise ValueError("MATCH_STARTED payload must include a view")
        self._gameplay_view = deepcopy(dict(view))
        self._pending_action = None
        self.status = ClientConnectionState.IN_MATCH

    def _handle_state_snapshot(
        self,
        message: Mapping[str, Any],
        payload: dict[str, Any],
    ) -> None:
        view = payload.get("view")
        if not isinstance(view, Mapping):
            raise ValueError("STATE_SNAPSHOT payload must include a view")
        self._gameplay_view = deepcopy(dict(view))
        self.match_id = (
            _optional_string(message.get("matchId", payload.get("matchId")))
            or self.match_id
        )
        if self._gameplay_view.get("gameOver"):
            self.status = ClientConnectionState.MATCH_FINISHED
        else:
            self.status = ClientConnectionState.IN_MATCH

    def _handle_action_result(
        self,
        _message: Mapping[str, Any],
        payload: dict[str, Any],
    ) -> None:
        self._last_action_result = payload
        action_id = _optional_string(payload.get("clientActionId"))
        if action_id is not None and action_id == self.pending_action_id:
            self._pending_action = None
        view = payload.get("view")
        if isinstance(view, Mapping):
            self._gameplay_view = deepcopy(dict(view))
        result = payload.get("result")
        result_mapping = result if isinstance(result, Mapping) else payload
        events = result_mapping.get("events", [])
        if payload.get("matchFinished") or any(
            isinstance(event, Mapping) and event.get("kind") == "MATCH_ENDED"
            for event in events
        ):
            self.status = ClientConnectionState.MATCH_FINISHED

    def _handle_error(
        self,
        _message: Mapping[str, Any],
        payload: dict[str, Any],
    ) -> None:
        self._last_error = payload
        action_id = _optional_string(payload.get("clientActionId"))
        if action_id is not None and action_id == self.pending_action_id:
            self._pending_action = None
        if payload.get("fatal") is True:
            self.status = ClientConnectionState.ERROR

    def _handle_room_closed(
        self,
        _message: Mapping[str, Any],
        _payload: dict[str, Any],
    ) -> None:
        self._room_state = None
        self._gameplay_view = None
        self._last_action_result = None
        self.match_id = None
        self._pending_action = None
        self.status = ClientConnectionState.CONNECTED

    def _remove_listener(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
