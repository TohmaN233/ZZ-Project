from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from zz.decks import validate_forces, validate_user_deck_recipe


class RoomStatus(str, Enum):
    CREATED = "CREATED"
    WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
    READY_CHECK = "READY_CHECK"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    CLOSED = "CLOSED"


class RoomError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class RoomPlayer:
    player_id: str
    connection_id: str
    display_name: str
    is_host: bool
    joined_at: float
    reconnect_token: str | None = field(default=None, repr=False)
    connected: bool = True
    disconnected_at: float | None = None
    deck_recipe: dict[str, int] | None = field(default=None, repr=False)
    force_ids: tuple[str, str] | None = field(default=None, repr=False)
    profile: dict[str, str | None] = field(default_factory=dict, repr=False)
    ready: bool = False

    @property
    def deck_selected(self) -> bool:
        return self.deck_recipe is not None and self.force_ids is not None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "displayName": self.display_name,
            "isHost": self.is_host,
            "joinedAt": self.joined_at,
            "connected": self.connected,
            "disconnectedAt": self.disconnected_at,
            "deckSelected": self.deck_selected,
            "ready": self.ready,
        }


class Room:
    CAPACITY = 2
    _NEXT_STATUS = {
        RoomStatus.CREATED: RoomStatus.WAITING_FOR_PLAYERS,
        RoomStatus.WAITING_FOR_PLAYERS: RoomStatus.READY_CHECK,
        RoomStatus.READY_CHECK: RoomStatus.STARTING,
        RoomStatus.STARTING: RoomStatus.RUNNING,
        RoomStatus.RUNNING: RoomStatus.FINISHED,
        RoomStatus.FINISHED: RoomStatus.CLOSED,
    }

    def __init__(
        self,
        *,
        room_id: str,
        room_code: str,
        host_connection_id: str,
        host_name: str = "Host",
        clock: Callable[[], float] = time.time,
        reconnect_token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._require_identifier(room_id, "room_id")
        self._require_identifier(room_code, "room_code")
        self._require_identifier(host_connection_id, "host_connection_id")
        self.room_id = room_id
        self.room_code = room_code
        self.host_player_id = "player_1"
        self._clock = clock
        self._reconnect_token_factory = reconnect_token_factory or (
            lambda: secrets.token_urlsafe(32)
        )
        self.status = RoomStatus.CREATED
        self.created_at = self._now()
        self.updated_at = self.created_at
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.closed_at: float | None = None
        self._players: list[RoomPlayer] = []
        self._players.append(RoomPlayer(
            player_id=self.host_player_id,
            connection_id=host_connection_id,
            display_name=self._require_display_name(host_name or "Host"),
            is_host=True,
            joined_at=self.created_at,
            reconnect_token=self._new_reconnect_token(),
        ))
        self._transition(RoomStatus.WAITING_FOR_PLAYERS)

    @property
    def players(self) -> tuple[RoomPlayer, ...]:
        return tuple(self._players)

    @property
    def host(self) -> RoomPlayer:
        return self._players[0]

    def join(self, connection_id: str, *, display_name: str = "Guest") -> RoomPlayer:
        self._require_identifier(connection_id, "connection_id")
        if any(player.connection_id == connection_id for player in self._players):
            raise RoomError(
                "CONNECTION_ALREADY_OWNED",
                "connection already owns a room seat",
            )
        if len(self._players) >= self.CAPACITY:
            raise RoomError("ROOM_FULL", "room already has two players")
        self._require_status(RoomStatus.WAITING_FOR_PLAYERS)
        player = RoomPlayer(
            player_id="player_2",
            connection_id=connection_id,
            display_name=self._require_display_name(display_name or "Guest"),
            is_host=False,
            joined_at=self._now(),
            reconnect_token=self._new_reconnect_token(),
        )
        self._players.append(player)
        self._transition(RoomStatus.READY_CHECK)
        return player

    def select_loadout(
        self,
        connection_id: str,
        deck_recipe: Mapping[str, int],
        force_ids: Sequence[str],
        profile: Mapping[str, str | None] | None = None,
    ) -> RoomPlayer:
        if self.status not in {
            RoomStatus.WAITING_FOR_PLAYERS,
            RoomStatus.READY_CHECK,
        }:
            self._raise_invalid_status("select a loadout")
        player = self.player_for_connection(connection_id)
        if player.ready:
            raise RoomError("PLAYER_ALREADY_READY", "ready player cannot change loadout")
        if not isinstance(deck_recipe, Mapping):
            raise RoomError("INVALID_DECK", "deck recipe must be an object")
        try:
            validated_deck = dict(deck_recipe)
            validate_user_deck_recipe(validated_deck)
        except (TypeError, ValueError) as exc:
            raise RoomError("INVALID_DECK", str(exc)) from exc
        if isinstance(force_ids, (str, bytes)) or not isinstance(force_ids, Sequence):
            raise RoomError("INVALID_FORCES", "forces must be an array")
        try:
            validated_forces = list(force_ids)
            validate_forces(validated_forces)
        except (TypeError, ValueError) as exc:
            raise RoomError("INVALID_FORCES", str(exc)) from exc
        player.deck_recipe = validated_deck
        player.force_ids = (validated_forces[0], validated_forces[1])
        player.profile = {
            "codemanId": (profile or {}).get("codemanId"),
            "playmatId": (profile or {}).get("playmatId"),
        }
        self._touch()
        return player

    def ready(self, connection_id: str) -> RoomPlayer:
        return self.set_ready(connection_id, True)

    def set_ready(self, connection_id: str, ready: bool) -> RoomPlayer:
        self._require_status(RoomStatus.READY_CHECK)
        if not isinstance(ready, bool):
            raise RoomError("INVALID_READY", "ready must be a boolean")
        player = self.player_for_connection(connection_id)
        if ready and not player.deck_selected:
            raise RoomError("LOADOUT_REQUIRED", "select a legal deck and two Forces first")
        if player.ready is ready:
            return player
        player.ready = ready
        self._touch()
        return player

    def start(self) -> None:
        self._require_status(RoomStatus.READY_CHECK)
        if len(self._players) != self.CAPACITY or not all(
            player.deck_selected for player in self._players
        ):
            raise RoomError("LOADOUT_REQUIRED", "both players need legal loadouts")
        if not all(player.ready for player in self._players):
            raise RoomError("PLAYERS_NOT_READY", "both players must be ready")
        self._transition(RoomStatus.STARTING)
        self.started_at = self.updated_at

    def mark_running(self) -> None:
        self._transition(RoomStatus.RUNNING)

    def finish(self) -> None:
        self._transition(RoomStatus.FINISHED)
        self.finished_at = self.updated_at

    def mark_disconnected(self, connection_id: str) -> RoomPlayer:
        player = self.player_for_connection(connection_id)
        if not player.connected:
            return player
        player.connected = False
        player.disconnected_at = self._now()
        self._touch()
        return player

    def reconnect(
        self,
        *,
        player_id: str,
        reconnect_token: str,
        connection_id: str,
    ) -> RoomPlayer:
        self._require_identifier(connection_id, "connection_id")
        if self.status is RoomStatus.CLOSED:
            self._raise_invalid_status("reconnect")
        player = self.player_for_id(player_id)
        current_token = player.reconnect_token
        if (
            not isinstance(reconnect_token, str)
            or current_token is None
            or not secrets.compare_digest(current_token, reconnect_token)
        ):
            raise RoomError(
                "INVALID_RECONNECT_TOKEN",
                "reconnect credentials are invalid",
            )
        if player.connected:
            raise RoomError(
                "DUPLICATE_CONNECTION",
                "player seat already has an active connection",
            )
        if any(
            candidate.connection_id == connection_id
            for candidate in self._players
            if candidate is not player
        ):
            raise RoomError(
                "CONNECTION_ALREADY_OWNED",
                "connection already owns a room seat",
            )
        player.connection_id = connection_id
        player.reconnect_token = self._new_reconnect_token(exclude=current_token)
        player.connected = True
        player.disconnected_at = None
        self._touch()
        return player

    def expire_reconnect(self, player_id: str) -> RoomPlayer:
        player = self.player_for_id(player_id)
        if player.reconnect_token is not None:
            player.reconnect_token = None
            self._touch()
        return player

    def close(self) -> None:
        if self.status is RoomStatus.CLOSED:
            return
        if self.status in {RoomStatus.STARTING, RoomStatus.RUNNING}:
            self._raise_invalid_status("close an active room")
        for player in self._players:
            player.reconnect_token = None
        self.status = RoomStatus.CLOSED
        self._touch()
        self.closed_at = self.updated_at

    def player_for_connection(self, connection_id: str) -> RoomPlayer:
        player = next(
            (
                candidate
                for candidate in self._players
                if candidate.connection_id == connection_id
            ),
            None,
        )
        if player is None:
            raise RoomError("PLAYER_NOT_IN_ROOM", "connection does not own a room seat")
        return player

    def player_for_id(self, player_id: str) -> RoomPlayer:
        player = next(
            (
                candidate
                for candidate in self._players
                if candidate.player_id == player_id
            ),
            None,
        )
        if player is None:
            raise RoomError("PLAYER_NOT_IN_ROOM", "player does not own a room seat")
        return player

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "roomId": self.room_id,
            "roomCode": self.room_code,
            "status": self.status.value,
            "hostPlayerId": self.host_player_id,
            "capacity": self.CAPACITY,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "closedAt": self.closed_at,
            "players": [player.to_public_dict() for player in self._players],
        }

    def _transition(self, target: RoomStatus) -> None:
        if self._NEXT_STATUS.get(self.status) is not target:
            self._raise_invalid_status(f"transition to {target.value}")
        self.status = target
        self._touch()

    def _require_status(self, expected: RoomStatus) -> None:
        if self.status is not expected:
            self._raise_invalid_status(f"perform operation requiring {expected.value}")

    def _raise_invalid_status(self, operation: str) -> None:
        raise RoomError(
            "INVALID_ROOM_STATUS",
            f"cannot {operation} while room is {self.status.value}",
        )

    def _touch(self) -> None:
        self.updated_at = self._now()

    def _now(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("room clock must return a number")
        return float(value)

    def _new_reconnect_token(self, *, exclude: str | None = None) -> str:
        existing = {
            player.reconnect_token
            for player in self._players
            if player.reconnect_token is not None
        }
        if exclude is not None:
            existing.add(exclude)
        for _ in range(32):
            token = self._reconnect_token_factory()
            if (
                isinstance(token, str)
                and 1 <= len(token) <= 128
                and token not in existing
            ):
                return token
        raise RuntimeError("reconnect token factory did not produce a unique token")

    @staticmethod
    def _require_identifier(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value:
            raise RoomError("INVALID_ROOM", f"{field_name} must be a non-empty string")

    @staticmethod
    def _require_display_name(value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 40:
            raise RoomError(
                "INVALID_PLAYER_NAME",
                "displayName must contain 1-40 characters",
            )
        return value.strip()
