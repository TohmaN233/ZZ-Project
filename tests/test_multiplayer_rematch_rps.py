from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.client import ClientConnectionState, MultiplayerClientStore
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.transport import InMemoryTransport


def _ready_room() -> tuple[MultiplayerServer, MultiplayerClientStore, MultiplayerClientStore]:
    match_ids = iter(("match-1", "match-2"))
    server = MultiplayerServer(
        room_id_factory=lambda: "room-1",
        room_code_factory=lambda: "ABC123",
        match_id_factory=lambda: next(match_ids),
        seed_factory=lambda: 701,
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
    return server, first, second


def test_rps_choices_stay_hidden_until_both_submit_and_winner_starts() -> None:
    _server, first, second = _ready_room()

    assert first.status is ClientConnectionState.MATCH_STARTING
    first.select_opening_choice("rock")
    assert first.room_state["players"][0]["openingChoiceSubmitted"] is True
    assert second.room_state["players"][0]["openingChoiceSubmitted"] is True
    assert "rock" not in repr(first.room_state).lower()

    second.select_opening_choice("scissors")

    assert first.status is ClientConnectionState.IN_MATCH
    assert second.status is ClientConnectionState.IN_MATCH
    assert first.gameplay_view["players"]["human"]["isFirstPlayer"] is True
    assert first.gameplay_view["animationEvents"] == [{
        "type": "rock_paper_scissors",
        "choices": {"P1": "rock", "P2": "scissors"},
        "winnerSide": "P1",
    }]


def test_rps_tie_resets_choices_for_another_round() -> None:
    _server, first, second = _ready_room()

    first.select_opening_choice("paper")
    second.select_opening_choice("paper")

    assert first.status is ClientConnectionState.MATCH_STARTING
    assert first.room_state["openingRound"] == 2
    assert all(not player["openingChoiceSubmitted"] for player in first.room_state["players"])
    assert first.room_state["lastOpeningResult"] == {
        "result": "tie",
        "choices": {"player_1": "paper", "player_2": "paper"},
    }


def test_finished_match_returns_same_seats_to_ready_check_for_rematch() -> None:
    _server, first, second = _ready_room()
    first.select_opening_choice("rock")
    second.select_opening_choice("scissors")
    first.surrender(client_action_id="surrender-1")

    assert first.status is ClientConnectionState.IN_ROOM
    assert second.status is ClientConnectionState.IN_ROOM
    assert first.room_state["roomCode"] == second.room_state["roomCode"] == "ABC123"
    assert [player["displayName"] for player in first.room_state["players"]] == ["Alice", "Bob"]
    assert all(player["deckSelected"] for player in first.room_state["players"])
    assert all(not player["ready"] for player in first.room_state["players"])
    assert first.match_id is None and second.match_id is None
    assert first.gameplay_view is None and second.gameplay_view is None

    first.set_ready(True)
    second.set_ready(True)
    first.select_opening_choice("scissors")
    second.select_opening_choice("rock")

    assert first.match_id == second.match_id == "match-2"
    assert second.gameplay_view["players"]["human"]["isFirstPlayer"] is True
