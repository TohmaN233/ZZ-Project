import json

import pytest

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.rooms import Room, RoomError, RoomStatus


class StepClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        current = self.value
        self.value += 1.0
        return current


def _room(clock: StepClock | None = None) -> Room:
    return Room(
        room_id="room-1",
        room_code="ABC123",
        host_connection_id="connection-host",
        host_name="Host",
        clock=clock or StepClock(),
    )


def _join_and_select(room: Room) -> None:
    room.select_loadout(
        "connection-host",
        KANATANA_YELLOW_RECIPE,
        DECKCODE0_YELLOW_FORCES,
    )
    room.join("connection-guest", display_name="Guest")
    room.select_loadout(
        "connection-guest",
        DEMETE_GREEN_RECIPE,
        DECKCODE0_GREEN_FORCES,
    )


def test_two_player_room_follows_the_complete_lifecycle() -> None:
    clock = StepClock()
    room = _room(clock)

    assert room.status is RoomStatus.WAITING_FOR_PLAYERS
    assert room.host.player_id == "player_1"
    assert room.host.connection_id == "connection-host"
    assert room.created_at == 1000.0

    room.select_loadout(
        "connection-host",
        KANATANA_YELLOW_RECIPE,
        DECKCODE0_YELLOW_FORCES,
        {"codemanId": "codeman-1", "playmatId": "playmat-1"},
    )
    assert room.host.profile == {"codemanId": "codeman-1", "playmatId": "playmat-1"}

    _join_and_select(room)
    assert room.status is RoomStatus.READY_CHECK
    assert [player.player_id for player in room.players] == ["player_1", "player_2"]

    room.ready("connection-host")
    room.ready("connection-guest")
    ready_timestamp = room.updated_at
    room.ready("connection-guest")
    assert room.updated_at == ready_timestamp

    room.start()
    assert room.status is RoomStatus.STARTING
    room.mark_running()
    assert room.status is RoomStatus.RUNNING
    assert room.started_at is not None
    room.finish()
    assert room.status is RoomStatus.FINISHED
    assert room.finished_at is not None
    room.close()
    assert room.status is RoomStatus.CLOSED
    assert room.closed_at is not None


def test_join_rejects_duplicate_connection_ownership_and_a_third_player() -> None:
    room = _room()

    with pytest.raises(RoomError) as duplicate:
        room.join("connection-host")
    assert duplicate.value.code == "CONNECTION_ALREADY_OWNED"
    assert duplicate.value.to_dict() == {
        "code": "CONNECTION_ALREADY_OWNED",
        "message": "connection already owns a room seat",
    }

    room.join("connection-guest")
    with pytest.raises(RoomError) as full:
        room.join("connection-third")
    assert full.value.code == "ROOM_FULL"


def test_loadout_validation_and_start_preconditions_use_domain_errors() -> None:
    room = _room()
    room.join("connection-guest")

    with pytest.raises(RoomError) as invalid_deck:
        room.select_loadout(
            "connection-host",
            {"yellow_00_01_00_00": 1},
            DECKCODE0_YELLOW_FORCES,
        )
    assert invalid_deck.value.code == "INVALID_DECK"

    with pytest.raises(RoomError) as invalid_forces:
        room.select_loadout(
            "connection-host",
            KANATANA_YELLOW_RECIPE,
            [DECKCODE0_YELLOW_FORCES[0], DECKCODE0_YELLOW_FORCES[0]],
        )
    assert invalid_forces.value.code == "INVALID_FORCES"

    with pytest.raises(RoomError) as not_selected:
        room.ready("connection-host")
    assert not_selected.value.code == "LOADOUT_REQUIRED"

    _select_both(room)
    room.ready("connection-host")
    with pytest.raises(RoomError) as not_ready:
        room.start()
    assert not_ready.value.code == "PLAYERS_NOT_READY"

    room.ready("connection-guest")
    room.start()
    with pytest.raises(RoomError) as already_started:
        room.select_loadout(
            "connection-host",
            KANATANA_YELLOW_RECIPE,
            DECKCODE0_YELLOW_FORCES,
        )
    assert already_started.value.code == "INVALID_ROOM_STATUS"


def _select_both(room: Room) -> None:
    room.select_loadout(
        "connection-host",
        KANATANA_YELLOW_RECIPE,
        DECKCODE0_YELLOW_FORCES,
    )
    room.select_loadout(
        "connection-guest",
        DEMETE_GREEN_RECIPE,
        DECKCODE0_GREEN_FORCES,
    )


def test_public_room_state_is_json_serializable_without_deck_contents() -> None:
    room = _room()
    _join_and_select(room)
    room.ready("connection-host")

    public_state = room.to_public_dict()
    encoded = json.dumps(public_state, sort_keys=True)

    assert public_state["roomId"] == "room-1"
    assert public_state["roomCode"] == "ABC123"
    assert public_state["hostPlayerId"] == "player_1"
    assert public_state["status"] == "READY_CHECK"
    assert public_state["players"][0]["deckSelected"] is True
    assert public_state["players"][1]["deckSelected"] is True
    assert public_state["players"][0]["ready"] is True
    assert all("deck" not in player for player in public_state["players"])
    assert not any(card_id in encoded for card_id in KANATANA_YELLOW_RECIPE)
    assert not any(card_id in encoded for card_id in DEMETE_GREEN_RECIPE)


def test_room_rejects_illegal_forward_skips_and_reverse_transitions() -> None:
    room = _room()

    with pytest.raises(RoomError) as early_start:
        room.start()
    assert early_start.value.code == "INVALID_ROOM_STATUS"

    _join_and_select(room)
    room.ready("connection-host")
    room.ready("connection-guest")
    room.start()

    with pytest.raises(RoomError) as early_finish:
        room.finish()
    assert early_finish.value.code == "INVALID_ROOM_STATUS"

    room.mark_running()
    room.finish()
    with pytest.raises(RoomError) as reverse:
        room.mark_running()
    assert reverse.value.code == "INVALID_ROOM_STATUS"


def test_waiting_room_can_close_and_close_is_idempotent() -> None:
    room = _room()

    room.close()
    closed_at = room.closed_at
    room.close()

    assert room.status is RoomStatus.CLOSED
    assert room.closed_at == closed_at
    with pytest.raises(RoomError) as join_closed:
        room.join("connection-guest")
    assert join_closed.value.code == "INVALID_ROOM_STATUS"
