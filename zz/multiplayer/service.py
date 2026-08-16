from __future__ import annotations

import math
import secrets
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock, Timer
from typing import Any

from zz.multiplayer.actions import SURRENDER, ActionRejection, ActionResult, SubmittedAction
from zz.multiplayer.match import (
    AuthoritativeMatch,
    InitialMatchSpec,
    first_player_id_for_roll,
    opening_roll_for_seed,
)
from zz.multiplayer.observability import null_event_sink
from zz.multiplayer.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    validate_client_envelope,
    validate_server_envelope,
)
from zz.multiplayer.rooms import Room, RoomError, RoomStatus


@dataclass
class _Connection:
    connection_id: str
    emit: Callable[[dict[str, Any]], None]
    room_id: str | None = None
    rate_tokens: float = 0.0
    rate_updated_at: float = 0.0


class MultiplayerServer:
    """Process-local authoritative server used by all multiplayer transports.

    Reconnect credentials and matches intentionally aren't persisted across a
    server process loss. Durable recovery is outside this runtime's scope.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        room_id_factory: Callable[[], str] | None = None,
        room_code_factory: Callable[[], str] | None = None,
        match_id_factory: Callable[[], str] | None = None,
        seed_factory: Callable[[], int] | None = None,
        reconnect_token_factory: Callable[[], str] | None = None,
        reconnect_grace_seconds: float = 90.0,
        reconnect_timer_factory: Callable[[float, Callable[[], None]], Any] | None = None,
        max_rooms: int | None = None,
        room_idle_timeout_seconds: float | None = None,
        room_idle_timer_factory: Callable[[float, Callable[[], None]], Any] | None = None,
        rate_limit_messages_per_second: int | None = None,
        rate_limit_burst: int | None = None,
        rate_clock: Callable[[], float] = time.monotonic,
        event_sink: Callable[..., None] | None = None,
        asset_root: str | None = None,
    ) -> None:
        if (
            isinstance(reconnect_grace_seconds, bool)
            or not isinstance(reconnect_grace_seconds, (int, float))
            or not math.isfinite(float(reconnect_grace_seconds))
            or reconnect_grace_seconds <= 0
        ):
            raise ValueError("reconnect_grace_seconds must be a positive finite number")
        if (
            max_rooms is not None
            and (
                isinstance(max_rooms, bool)
                or not isinstance(max_rooms, int)
                or max_rooms <= 0
            )
        ):
            raise ValueError("max_rooms must be a positive integer or None")
        if room_idle_timeout_seconds is not None and (
            isinstance(room_idle_timeout_seconds, bool)
            or not isinstance(room_idle_timeout_seconds, (int, float))
            or not math.isfinite(float(room_idle_timeout_seconds))
            or room_idle_timeout_seconds <= 0
        ):
            raise ValueError(
                "room_idle_timeout_seconds must be a positive finite number or None"
            )
        if room_idle_timer_factory is not None and room_idle_timeout_seconds is None:
            raise ValueError(
                "room_idle_timer_factory requires room_idle_timeout_seconds"
            )
        if rate_limit_messages_per_second is not None and (
            isinstance(rate_limit_messages_per_second, bool)
            or not isinstance(rate_limit_messages_per_second, int)
            or rate_limit_messages_per_second <= 0
        ):
            raise ValueError("rate_limit_messages_per_second must be a positive integer or None")
        if rate_limit_burst is not None and (
            isinstance(rate_limit_burst, bool)
            or not isinstance(rate_limit_burst, int)
            or rate_limit_burst <= 0
        ):
            raise ValueError("rate_limit_burst must be a positive integer or None")
        if rate_limit_messages_per_second is None and rate_limit_burst is not None:
            raise ValueError("rate_limit_burst requires rate_limit_messages_per_second")
        if not callable(rate_clock):
            raise TypeError("rate_clock must be callable")
        if event_sink is not None and not callable(event_sink):
            raise TypeError("event_sink must be callable or None")
        self._clock = clock
        self._room_id_factory = room_id_factory or (lambda: secrets.token_hex(8))
        self._room_code_factory = room_code_factory or self._random_room_code
        self._match_id_factory = match_id_factory or (lambda: secrets.token_hex(12))
        self._seed_factory = seed_factory or (lambda: secrets.randbits(63))
        self._reconnect_token_factory = reconnect_token_factory
        self.reconnect_grace_seconds = float(reconnect_grace_seconds)
        self._reconnect_timer_factory = (
            reconnect_timer_factory or self._default_reconnect_timer
        )
        self.max_rooms = max_rooms
        self.room_idle_timeout_seconds = (
            float(room_idle_timeout_seconds)
            if room_idle_timeout_seconds is not None
            else None
        )
        self._room_idle_timer_factory = (
            room_idle_timer_factory or self._default_reconnect_timer
        )
        self.rate_limit_messages_per_second = rate_limit_messages_per_second
        self.rate_limit_burst = (
            rate_limit_burst
            if rate_limit_burst is not None
            else (
                rate_limit_messages_per_second * 2
                if rate_limit_messages_per_second is not None
                else None
            )
        )
        self._rate_clock = rate_clock
        self._event_sink = event_sink or null_event_sink
        self._asset_root = asset_root
        self._connections: dict[str, _Connection] = {}
        self._rooms: dict[str, Room] = {}
        self._room_ids_by_code: dict[str, str] = {}
        self._matches: dict[str, AuthoritativeMatch] = {}
        self._registry_lock = RLock()
        self._room_locks: dict[str, RLock] = {}
        self._disconnect_timers: dict[tuple[str, str], Any] = {}
        self._room_idle_timers: dict[str, Any] = {}
        self._next_server_message_id = 1

    def connect(
        self,
        connection_id: str,
        emit: Callable[[dict[str, Any]], None],
    ) -> None:
        if not connection_id or not callable(emit):
            raise ValueError("connection_id and emit are required")
        now = self._rate_now() if self.rate_limit_messages_per_second is not None else 0.0
        with self._registry_lock:
            if connection_id in self._connections:
                raise RuntimeError("connection is already registered")
            self._connections[connection_id] = _Connection(
                connection_id,
                emit,
                rate_tokens=float(self.rate_limit_burst or 0),
                rate_updated_at=now,
            )
        self._emit(connection_id, "WELCOME", {"connectionId": connection_id})
        self._observe("connection_opened", connectionId=connection_id)

    def disconnect(self, connection_id: str) -> None:
        with self._registry_lock:
            connection = self._connections.pop(connection_id, None)
            room = (
                self._rooms.get(connection.room_id)
                if connection is not None and connection.room_id is not None
                else None
            )
            room_lock = (
                self._room_locks.get(connection.room_id)
                if connection is not None and connection.room_id is not None
                else None
            )
        if connection is None or room is None or room_lock is None:
            if connection is not None:
                self._observe("connection_closed", connectionId=connection_id)
            return
        with room_lock:
            player = room.mark_disconnected(connection_id)
            self._broadcast_room(room)
            self._cancel_room_idle_timer(room.room_id)
            self._schedule_disconnect_timeout(room, player.player_id)
            self._observe(
                "player_disconnected",
                connectionId=connection_id,
                playerId=player.player_id,
                roomId=room.room_id,
                matchId=self._match_id_for_room(room),
            )
        self._observe("connection_closed", connectionId=connection_id)

    def receive(self, connection_id: str, message: Mapping[str, Any]) -> None:
        with self._registry_lock:
            connection = self._connections.get(connection_id)
            rate_allowed = connection is not None and self._consume_rate_token(connection)
        if connection is None:
            raise RuntimeError("connection is not registered")
        if not rate_allowed:
            self._error(
                connection_id,
                "RATE_LIMITED",
                "connection message rate limit exceeded",
            )
            self._observe(
                "message_rate_limited",
                level="WARNING",
                connectionId=connection_id,
                errorCode="RATE_LIMITED",
            )
            return
        raw_message_type = message.get("type") if isinstance(message, Mapping) else None
        message_type_for_log = (
            raw_message_type
            if isinstance(raw_message_type, str) and len(raw_message_type) <= 64
            else None
        )
        try:
            message_type, payload = self._validate_message(message)
            mutation_lock = self._lock_for_message(connection, message_type, payload)
            with mutation_lock:
                self._dispatch(connection, message_type, payload)
        except RoomError as exc:
            self._error(connection_id, exc.code, exc.message)
            self._observe(
                "message_rejected",
                level="WARNING",
                connectionId=connection_id,
                messageType=message_type_for_log,
                errorCode=exc.code,
            )
        except ProtocolError as exc:
            self._error(connection_id, exc.code, exc.message, fatal=exc.fatal)
            self._observe(
                "message_rejected",
                level="WARNING",
                connectionId=connection_id,
                messageType=message_type_for_log,
                errorCode=exc.code,
            )
        except (TypeError, ValueError) as exc:
            self._error(connection_id, "INVALID_MESSAGE", str(exc))
            self._observe(
                "message_rejected",
                level="WARNING",
                connectionId=connection_id,
                messageType=message_type_for_log,
                errorCode="INVALID_MESSAGE",
            )

    def close_room(self, room_code: str) -> None:
        with self._registry_lock:
            room_id = self._room_ids_by_code.get(room_code)
            room = self._rooms.get(room_id) if room_id is not None else None
            room_lock = self._room_locks.get(room_id) if room_id is not None else None
        if room is None:
            raise RoomError("ROOM_NOT_FOUND", "room code does not exist")
        if room_lock is None:
            raise RuntimeError("registered room has no mutation lock")
        with room_lock:
            if room.status is RoomStatus.RUNNING:
                raise RoomError("INVALID_ROOM_STATUS", "running room must finish before close")
            if room.status is RoomStatus.CLOSED:
                return
            self._close_room_locked(room)

    def room_for_code(self, room_code: str) -> Room:
        return self._room_by_code(room_code)

    def match_for_room(self, room_code: str) -> AuthoritativeMatch | None:
        room = self._room_by_code(room_code)
        return self._matches.get(room.room_id)

    def _dispatch(
        self,
        connection: _Connection,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        handlers = {
            "CREATE_ROOM": self._create_room,
            "JOIN_ROOM": self._join_room,
            "RECONNECT": self._reconnect,
            "SELECT_DECK": self._select_deck,
            "SET_READY": self._set_ready,
            "SUBMIT_ACTION": self._submit_action,
            "REQUEST_SYNC": self._request_sync,
            "LEAVE_ROOM": self._leave_room,
        }
        handlers[message_type](connection, payload)

    def _create_room(self, connection: _Connection, payload: dict[str, Any]) -> None:
        self._require_no_room(connection)
        if self.max_rooms is not None and self._active_room_count() >= self.max_rooms:
            raise RoomError("SERVER_CAPACITY", "server room capacity has been reached")
        room_id = self._unique_value(self._room_id_factory, self._rooms)
        room_code = self._unique_value(self._room_code_factory, self._room_ids_by_code)
        room = Room(
            room_id=room_id,
            room_code=room_code,
            host_connection_id=connection.connection_id,
            host_name=self._display_name(payload, "Host"),
            clock=self._clock,
            reconnect_token_factory=self._reconnect_token_factory,
        )
        self._rooms[room_id] = room
        self._room_ids_by_code[room_code] = room_id
        self._room_locks[room_id] = RLock()
        connection.room_id = room_id
        self._reset_room_idle_timer(room)
        self._broadcast_room(room)
        self._observe(
            "room_created",
            connectionId=connection.connection_id,
            playerId=room.host_player_id,
            roomId=room.room_id,
        )

    def _join_room(self, connection: _Connection, payload: dict[str, Any]) -> None:
        self._require_no_room(connection)
        room_code = payload.get("roomCode")
        if not isinstance(room_code, str) or not room_code:
            raise ValueError("roomCode must be a non-empty string")
        room = self._room_by_code(room_code)
        room.join(
            connection.connection_id,
            display_name=self._display_name(payload, "Guest"),
        )
        self._cancel_room_idle_timer(room.room_id)
        connection.room_id = room.room_id
        self._broadcast_room(room)
        player = room.player_for_connection(connection.connection_id)
        self._observe(
            "player_joined",
            connectionId=connection.connection_id,
            playerId=player.player_id,
            roomId=room.room_id,
        )

    def _reconnect(self, connection: _Connection, payload: dict[str, Any]) -> None:
        self._require_no_room(connection)
        room = self._room_by_code(str(payload["roomCode"]))
        player = room.reconnect(
            player_id=str(payload["playerId"]),
            reconnect_token=str(payload["reconnectToken"]),
            connection_id=connection.connection_id,
        )
        connection.room_id = room.room_id
        self._cancel_disconnect_timer(room.room_id, player.player_id)
        if room.status is RoomStatus.WAITING_FOR_PLAYERS:
            self._reset_room_idle_timer(room)
        self._broadcast_room(room)
        match = self._matches.get(room.room_id)
        if match is not None:
            self._emit(
                connection.connection_id,
                "STATE_SNAPSHOT",
                self._snapshot_payload(room, match, player.player_id),
                match_id=match.match_id,
            )
        self._observe(
            "player_reconnected",
            connectionId=connection.connection_id,
            playerId=player.player_id,
            roomId=room.room_id,
            matchId=match.match_id if match is not None else None,
            revision=match.revision if match is not None else None,
        )

    def _select_deck(self, connection: _Connection, payload: dict[str, Any]) -> None:
        room = self._room_for_connection(connection)
        deck = payload.get("deck")
        forces = payload.get("forces")
        if not isinstance(deck, Mapping):
            raise ValueError("deck must be an object")
        if not isinstance(forces, list):
            raise ValueError("forces must be an array")
        room.select_loadout(connection.connection_id, deck, forces, payload.get("profile"))
        if room.status is RoomStatus.WAITING_FOR_PLAYERS:
            self._reset_room_idle_timer(room)
        self._broadcast_room(room)

    def _set_ready(self, connection: _Connection, payload: dict[str, Any]) -> None:
        room = self._room_for_connection(connection)
        ready = payload.get("ready")
        if not isinstance(ready, bool):
            raise ValueError("ready must be a boolean")
        room.set_ready(connection.connection_id, ready)
        self._broadcast_room(room)
        if len(room.players) == Room.CAPACITY and all(player.ready for player in room.players):
            self._start_match(room)

    def _start_match(self, room: Room) -> None:
        self._cancel_room_idle_timer(room.room_id)
        room.start()
        player_1, player_2 = room.players
        if (
            player_1.deck_recipe is None
            or player_1.force_ids is None
            or player_2.deck_recipe is None
            or player_2.force_ids is None
        ):
            raise RuntimeError("ready room lost a validated loadout")
        seed = self._seed_factory()
        opening_roll = opening_roll_for_seed(seed)
        match = AuthoritativeMatch(InitialMatchSpec(
            match_id=self._match_id_factory(),
            seed=seed,
            first_player_id=first_player_id_for_roll(opening_roll),
            player_1_deck=player_1.deck_recipe,
            player_1_forces=player_1.force_ids,
            player_2_deck=player_2.deck_recipe,
            player_2_forces=player_2.force_ids,
            player_1_profile=player_1.profile,
            player_2_profile=player_2.profile,
            player_1_name=player_1.display_name,
            player_2_name=player_2.display_name,
            opening_roll=opening_roll,
        ), asset_root=self._asset_root)
        self._matches[room.room_id] = match
        room.mark_running()
        self._broadcast_room(room)
        for player in room.players:
            self._emit(player.connection_id, "MATCH_STARTED", {
                "matchId": match.match_id,
                "playerId": player.player_id,
                "view": match.get_view_for(player.player_id),
            }, match_id=match.match_id)
        self._observe(
            "match_started",
            roomId=room.room_id,
            matchId=match.match_id,
            revision=match.revision,
        )

    def _submit_action(self, connection: _Connection, payload: dict[str, Any]) -> None:
        room = self._room_for_connection(connection)
        if room.status is not RoomStatus.RUNNING:
            raise RoomError("MATCH_NOT_RUNNING", "room has no running match")
        match = self._matches.get(room.room_id)
        if match is None:
            raise RuntimeError("running room has no authoritative match")
        submitted = SubmittedAction.from_dict(payload)
        player = room.player_for_connection(connection.connection_id)
        if submitted.player_id != player.player_id or submitted.match_id != match.match_id:
            result = ActionResult(
                accepted=False,
                revision=match.revision,
                state_hash=match.state_hash(),
                rejection=ActionRejection(
                    code="PLAYER_NOT_IN_MATCH",
                    message="connection cannot control the submitted player or match",
                ),
            )
        else:
            result = match.submit_action(submitted)
        result_payload = {
            "clientActionId": submitted.client_action_id,
            "result": result.to_dict(),
            "view": match.get_view_for(player.player_id),
        }
        self._emit(
            connection.connection_id,
            "ACTION_RESULT",
            result_payload,
            match_id=match.match_id,
        )
        if not result.accepted:
            self._observe(
                "action_rejected",
                level="WARNING",
                connectionId=connection.connection_id,
                playerId=player.player_id,
                roomId=room.room_id,
                matchId=match.match_id,
                revision=result.revision,
                messageType="SUBMIT_ACTION",
                errorCode=(
                    result.rejection.code
                    if result.rejection is not None
                    else "ACTION_REJECTED"
                ),
            )
            return
        self._observe(
            "action_accepted",
            connectionId=connection.connection_id,
            playerId=player.player_id,
            roomId=room.room_id,
            matchId=match.match_id,
            revision=result.revision,
            messageType="SUBMIT_ACTION",
        )
        self._broadcast_snapshots(room, match)
        if match.session._game_over is not None:
            room.finish()
            self._broadcast_room(room)
            self._observe(
                "match_ended",
                roomId=room.room_id,
                matchId=match.match_id,
                revision=match.revision,
            )

    def _request_sync(self, connection: _Connection, _payload: dict[str, Any]) -> None:
        room = self._room_for_connection(connection)
        match = self._matches.get(room.room_id)
        if match is None:
            if room.status is RoomStatus.WAITING_FOR_PLAYERS:
                self._reset_room_idle_timer(room)
            self._emit(connection.connection_id, "ROOM_STATE", self._room_payload(room, connection))
            return
        player = room.player_for_connection(connection.connection_id)
        self._emit(connection.connection_id, "STATE_SNAPSHOT", {
            **self._snapshot_payload(room, match, player.player_id),
        }, match_id=match.match_id)

    def _leave_room(self, connection: _Connection, _payload: dict[str, Any]) -> None:
        room = self._room_for_connection(connection)
        if room.status is RoomStatus.RUNNING:
            raise RoomError("MATCH_RUNNING", "surrender before leaving a running match")
        self.close_room(room.room_code)

    def _broadcast_snapshots(self, room: Room, match: AuthoritativeMatch) -> None:
        for player in room.players:
            self._emit(
                player.connection_id,
                "STATE_SNAPSHOT",
                self._snapshot_payload(room, match, player.player_id),
                match_id=match.match_id,
            )

    def _broadcast_room(self, room: Room) -> None:
        for player in room.players:
            with self._registry_lock:
                connection = self._connections.get(player.connection_id)
            if connection is not None:
                self._emit(
                    player.connection_id,
                    "ROOM_STATE",
                    self._room_payload(room, connection),
                )

    def _room_payload(self, room: Room, connection: _Connection) -> dict[str, Any]:
        payload = room.to_public_dict()
        player = room.player_for_connection(connection.connection_id)
        payload["playerId"] = player.player_id
        if player.reconnect_token is None:
            raise RuntimeError("connected room player has no reconnect token")
        payload["reconnectToken"] = player.reconnect_token
        match = self._matches.get(room.room_id)
        if match is not None:
            payload["matchId"] = match.match_id
        return payload

    @staticmethod
    def _snapshot_payload(
        room: Room,
        match: AuthoritativeMatch,
        player_id: str,
    ) -> dict[str, Any]:
        return {
            "matchId": match.match_id,
            "playerId": player_id,
            "view": match.get_view_for(player_id),
            "connectionStatus": {
                player.player_id: {
                    "connected": player.connected,
                    "disconnectedAt": player.disconnected_at,
                }
                for player in room.players
            },
        }

    def _emit(
        self,
        connection_id: str,
        message_type: str,
        payload: Mapping[str, Any],
        *,
        match_id: str | None = None,
    ) -> None:
        with self._registry_lock:
            connection = self._connections.get(connection_id)
            message_id = f"server-{self._next_server_message_id}"
            self._next_server_message_id += 1
        if connection is None:
            return
        message: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "messageId": message_id,
            "type": message_type,
            "payload": deepcopy(dict(payload)),
        }
        if match_id is not None:
            message["matchId"] = match_id
        connection.emit(validate_server_envelope(message))

    def _error(
        self,
        connection_id: str,
        code: str,
        message: str,
        *,
        fatal: bool = False,
    ) -> None:
        self._emit(connection_id, "ERROR", {
            "code": code,
            "message": message,
            "fatal": fatal,
        })

    def _validate_message(self, message: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        envelope = validate_client_envelope(message)
        return str(envelope["type"]), deepcopy(dict(envelope["payload"]))

    def _room_for_connection(self, connection: _Connection) -> Room:
        if connection.room_id is None:
            raise RoomError("PLAYER_NOT_IN_ROOM", "connection is not in a room")
        room = self._rooms.get(connection.room_id)
        if room is None:
            raise RoomError("ROOM_NOT_FOUND", "room does not exist")
        return room

    def _lock_for_message(
        self,
        connection: _Connection,
        message_type: str,
        payload: Mapping[str, Any],
    ) -> RLock:
        if message_type == "CREATE_ROOM":
            return self._registry_lock
        if message_type in {"JOIN_ROOM", "RECONNECT"}:
            room_code = payload.get("roomCode")
            if not isinstance(room_code, str):
                return self._registry_lock
            with self._registry_lock:
                room_id = self._room_ids_by_code.get(room_code)
                return self._room_locks.get(room_id, self._registry_lock)
        with self._registry_lock:
            if connection.room_id is None:
                return self._registry_lock
            return self._room_locks.get(connection.room_id, self._registry_lock)

    def _room_by_code(self, room_code: str) -> Room:
        room_id = self._room_ids_by_code.get(room_code)
        room = self._rooms.get(room_id) if room_id is not None else None
        if room is None or room.status is RoomStatus.CLOSED:
            raise RoomError("ROOM_NOT_FOUND", "room code does not exist")
        return room

    def _active_room_count(self) -> int:
        return sum(room.status is not RoomStatus.CLOSED for room in self._rooms.values())

    def _consume_rate_token(self, connection: _Connection) -> bool:
        if self.rate_limit_messages_per_second is None:
            return True
        if self.rate_limit_burst is None:
            raise RuntimeError("configured message rate limit has no burst capacity")
        now = self._rate_now()
        elapsed = max(0.0, now - connection.rate_updated_at)
        connection.rate_updated_at = now
        connection.rate_tokens = min(
            float(self.rate_limit_burst),
            connection.rate_tokens + elapsed * self.rate_limit_messages_per_second,
        )
        if connection.rate_tokens < 1.0:
            return False
        connection.rate_tokens -= 1.0
        return True

    def _rate_now(self) -> float:
        value = self._rate_clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise RuntimeError("rate clock must return a finite number")
        return float(value)

    def _observe(self, event: str, *, level: str = "INFO", **fields: Any) -> None:
        self._event_sink(event, level=level, **fields)

    def _match_id_for_room(self, room: Room) -> str | None:
        match = self._matches.get(room.room_id)
        return match.match_id if match is not None else None

    @staticmethod
    def _require_no_room(connection: _Connection) -> None:
        if connection.room_id is not None:
            raise RoomError("CONNECTION_ALREADY_OWNED", "connection already owns a room seat")

    @staticmethod
    def _display_name(payload: Mapping[str, Any], fallback: str) -> str:
        value = payload.get("displayName", fallback)
        if not isinstance(value, str) or not value.strip() or len(value) > 40:
            raise ValueError("displayName must contain 1-40 characters")
        return value.strip()

    @staticmethod
    def _unique_value(factory: Callable[[], str], existing: Mapping[str, Any]) -> str:
        for _ in range(32):
            value = factory()
            if isinstance(value, str) and value and value not in existing:
                return value
        raise RuntimeError("identifier factory did not produce a unique value")

    @staticmethod
    def _random_room_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(6))

    @staticmethod
    def _default_reconnect_timer(
        delay: float,
        callback: Callable[[], None],
    ) -> Timer:
        timer = Timer(delay, callback)
        timer.daemon = True
        return timer

    def _schedule_disconnect_timeout(self, room: Room, player_id: str) -> None:
        player = room.player_for_id(player_id)
        if player.connected or player.disconnected_at is None:
            return
        key = (room.room_id, player_id)
        disconnected_at = player.disconnected_at
        with self._registry_lock:
            if key in self._disconnect_timers:
                return
        holder: list[Any] = []

        def expire() -> None:
            self._handle_disconnect_timeout(
                room.room_id,
                player_id,
                disconnected_at,
                holder[0],
            )

        timer = self._reconnect_timer_factory(self.reconnect_grace_seconds, expire)
        holder.append(timer)
        with self._registry_lock:
            if key in self._disconnect_timers:
                return
            self._disconnect_timers[key] = timer
        try:
            timer.start()
        except Exception:
            with self._registry_lock:
                if self._disconnect_timers.get(key) is timer:
                    self._disconnect_timers.pop(key, None)
            raise

    def _cancel_disconnect_timer(self, room_id: str, player_id: str) -> None:
        with self._registry_lock:
            timer = self._disconnect_timers.pop((room_id, player_id), None)
        if timer is not None:
            timer.cancel()

    def _cancel_room_timers(self, room_id: str) -> None:
        self._cancel_room_idle_timer(room_id)
        with self._registry_lock:
            timers = [
                self._disconnect_timers.pop(key)
                for key in tuple(self._disconnect_timers)
                if key[0] == room_id
            ]
        for timer in timers:
            timer.cancel()

    def _reset_room_idle_timer(self, room: Room) -> None:
        if self.room_idle_timeout_seconds is None:
            return
        if room.status is not RoomStatus.WAITING_FOR_PLAYERS:
            self._cancel_room_idle_timer(room.room_id)
            return
        with self._registry_lock:
            if any(key[0] == room.room_id for key in self._disconnect_timers):
                self._cancel_room_idle_timer(room.room_id)
                return
            previous = self._room_idle_timers.pop(room.room_id, None)
        if previous is not None:
            previous.cancel()
        holder: list[Any] = []

        def expire() -> None:
            self._handle_room_idle_timeout(room.room_id, holder[0])

        timer = self._room_idle_timer_factory(self.room_idle_timeout_seconds, expire)
        holder.append(timer)
        with self._registry_lock:
            self._room_idle_timers[room.room_id] = timer
        try:
            timer.start()
        except Exception:
            with self._registry_lock:
                if self._room_idle_timers.get(room.room_id) is timer:
                    self._room_idle_timers.pop(room.room_id, None)
            raise

    def _cancel_room_idle_timer(self, room_id: str) -> None:
        with self._registry_lock:
            timer = self._room_idle_timers.pop(room_id, None)
        if timer is not None:
            timer.cancel()

    def _handle_room_idle_timeout(self, room_id: str, timer: Any) -> None:
        with self._registry_lock:
            if self._room_idle_timers.get(room_id) is not timer:
                return
            self._room_idle_timers.pop(room_id, None)
            room = self._rooms.get(room_id)
            room_lock = self._room_locks.get(room_id)
        if room is None or room_lock is None:
            return
        with room_lock:
            if room.status is RoomStatus.WAITING_FOR_PLAYERS:
                self._close_room_locked(room)

    def _handle_disconnect_timeout(
        self,
        room_id: str,
        player_id: str,
        disconnected_at: float | None,
        timer: Any,
    ) -> None:
        key = (room_id, player_id)
        with self._registry_lock:
            if self._disconnect_timers.get(key) is not timer:
                return
            self._disconnect_timers.pop(key, None)
            room = self._rooms.get(room_id)
            room_lock = self._room_locks.get(room_id)
        if room is None or room_lock is None:
            return
        with room_lock:
            player = room.player_for_id(player_id)
            if (
                player.connected
                or player.disconnected_at != disconnected_at
                or room.status is RoomStatus.CLOSED
            ):
                return
            if room.status is RoomStatus.RUNNING:
                self._forfeit_disconnected_player(room, player_id, disconnected_at)
            else:
                room.expire_reconnect(player_id)
                if room.status in {
                    RoomStatus.CREATED,
                    RoomStatus.WAITING_FOR_PLAYERS,
                    RoomStatus.READY_CHECK,
                    RoomStatus.STARTING,
                }:
                    self._close_room_locked(room)
                elif all(
                    not candidate.connected and candidate.reconnect_token is None
                    for candidate in room.players
                ):
                    self._close_room_locked(room)
                else:
                    self._broadcast_room(room)

    def _forfeit_disconnected_player(
        self,
        room: Room,
        player_id: str,
        disconnected_at: float | None,
    ) -> None:
        match = self._matches.get(room.room_id)
        if match is None:
            raise RuntimeError("running room has no authoritative match")
        submitted = SubmittedAction(
            match_id=match.match_id,
            player_id=player_id,
            client_action_id=f"timeout-forfeit-{player_id}-{disconnected_at}",
            expected_revision=match.revision,
            action={"kind": SURRENDER},
        )
        result = match.submit_action(submitted)
        if not result.accepted:
            raise RuntimeError(f"disconnect timeout forfeit was rejected: {result.rejection}")
        room.expire_reconnect(player_id)
        self._broadcast_snapshots(room, match)
        room.finish()
        self._broadcast_room(room)
        self._observe(
            "match_ended",
            level="WARNING",
            playerId=player_id,
            roomId=room.room_id,
            matchId=match.match_id,
            revision=match.revision,
            errorCode="RECONNECT_TIMEOUT",
        )

    def _close_room_locked(self, room: Room) -> None:
        room.close()
        self._cancel_room_timers(room.room_id)
        for player in room.players:
            with self._registry_lock:
                connection = self._connections.get(player.connection_id)
                if connection is not None:
                    connection.room_id = None
            if connection is not None:
                self._emit(player.connection_id, "ROOM_CLOSED", {
                    "roomId": room.room_id,
                    "roomCode": room.room_code,
                })
        self._observe(
            "room_closed",
            roomId=room.room_id,
            matchId=self._match_id_for_room(room),
        )
