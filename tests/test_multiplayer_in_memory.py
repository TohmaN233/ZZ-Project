from __future__ import annotations

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.actions import CHOOSE_PROMPT_OPTION
from zz.multiplayer.client import ClientConnectionState, MultiplayerClientStore
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.transport import InMemoryTransport


def _clients() -> tuple[MultiplayerServer, MultiplayerClientStore, MultiplayerClientStore]:
    server = MultiplayerServer(
        room_id_factory=lambda: "room-1",
        room_code_factory=lambda: "ABC123",
        match_id_factory=lambda: "match-1",
        seed_factory=lambda: 701,
    )
    first = MultiplayerClientStore(InMemoryTransport(server, "connection-a"))
    second = MultiplayerClientStore(InMemoryTransport(server, "connection-b"))
    first.connect()
    second.connect()
    return server, first, second


def _start_match(
    first: MultiplayerClientStore,
    second: MultiplayerClientStore,
) -> None:
    first.create_room(display_name="Alice")
    assert first.room_state is not None
    second.join_room(first.room_state["roomCode"], display_name="Bob")
    first.select_deck(KANATANA_YELLOW_RECIPE, DECKCODE0_YELLOW_FORCES)
    second.select_deck(DEMETE_GREEN_RECIPE, DECKCODE0_GREEN_FORCES)
    first.set_ready(True)
    second.set_ready(True)


def _prompt_action(client: MultiplayerClientStore) -> dict:
    view = client.gameplay_view
    assert view is not None
    prompt = view.get("prompt")
    assert isinstance(prompt, dict)
    options = prompt["options"]
    if prompt["kind"] == "mulligan":
        option = next(candidate for candidate in options if candidate["id"] == "keep")
    else:
        by_kind = {candidate.get("kind"): candidate for candidate in options}
        option = (
            by_kind.get("end_turn")
            or by_kind.get("skip_mana")
            or by_kind.get("place_colorless_mana")
            or options[0]
        )
    return {
        "kind": CHOOSE_PROMPT_OPTION,
        "promptId": prompt["id"],
        "optionId": option["id"],
        "payload": {},
    }


def test_two_independent_clients_join_ready_act_surrender_and_close() -> None:
    server, first, second = _clients()
    _start_match(first, second)

    assert first.status is ClientConnectionState.IN_MATCH
    assert second.status is ClientConnectionState.IN_MATCH
    assert first.player_id == "player_1"
    assert second.player_id == "player_2"
    assert first.match_id == second.match_id == "match-1"

    first_view = first.gameplay_view
    second_view = second.gameplay_view
    assert first_view is not None and second_view is not None
    assert first_view["stateHash"] == second_view["stateHash"]
    assert first_view["players"]["human"]["hand"] != second_view["players"]["human"]["hand"]
    assert all("iid" not in card for card in first_view["players"]["opponent"]["hand"])
    assert all("iid" not in card for card in second_view["players"]["opponent"]["hand"])
    assert first_view.get("prompt") is not None
    assert second_view.get("prompt") is None

    before_hash = first_view["stateHash"]
    second.submit_action({
        "kind": CHOOSE_PROMPT_OPTION,
        "promptId": first_view["prompt"]["id"],
        "optionId": "keep",
        "payload": {},
    }, client_action_id="wrong-seat")
    assert second.last_action_result["result"]["accepted"] is False
    assert second.last_action_result["result"]["rejection"]["code"] == "NOT_YOUR_TURN"
    assert first.gameplay_view["stateHash"] == before_hash
    assert second.pending_action_id is None
    assert second.status is ClientConnectionState.IN_MATCH

    first.submit_action(_prompt_action(first), client_action_id="keep-a")
    assert first.gameplay_view["revision"] == 1
    assert second.gameplay_view["revision"] == 1
    assert first.gameplay_view.get("prompt") is None
    assert second.gameplay_view.get("prompt") is not None

    second.submit_action(_prompt_action(second), client_action_id="keep-b")
    assert first.gameplay_view["revision"] == 2
    assert second.gameplay_view["revision"] == 2
    assert first.gameplay_view.get("prompt") is None
    assert second.gameplay_view.get("prompt") is not None

    active_sides = [first.gameplay_view["activeSide"]]
    for index in range(8):
        owner = first if first.gameplay_view.get("prompt") is not None else second
        owner.submit_action(_prompt_action(owner), client_action_id=f"turn-{index}")
        active_sides.append(first.gameplay_view["activeSide"])
        if first.gameplay_view["turn"] == 2:
            break
    assert "P2" in active_sides
    assert first.gameplay_view["turn"] == 2
    assert first.gameplay_view["activeSide"] == "P1"
    assert first.gameplay_view.get("prompt") is not None
    assert second.gameplay_view.get("prompt") is None

    first.surrender(client_action_id="surrender-a")
    assert first.status is ClientConnectionState.MATCH_FINISHED
    assert second.status is ClientConnectionState.MATCH_FINISHED
    assert first.gameplay_view["stateHash"] == second.gameplay_view["stateHash"]
    assert first.gameplay_view["gameOver"] is not None
    assert second.gameplay_view["gameOver"] is not None
    assert first.room_state["status"] == "FINISHED"
    assert second.room_state["status"] == "FINISHED"

    server.close_room("ABC123")
    assert first.status is ClientConnectionState.CONNECTED
    assert second.status is ClientConnectionState.CONNECTED
    assert first.room_state is None
    assert second.room_state is None


def test_invalid_room_third_player_and_private_loadouts() -> None:
    server, first, second = _clients()
    missing = MultiplayerClientStore(InMemoryTransport(server, "connection-missing"))
    missing.connect()
    missing.join_room("NOPE00")
    assert missing.last_error["code"] == "ROOM_NOT_FOUND"
    assert missing.status is ClientConnectionState.CONNECTED

    first.create_room()
    second.join_room("ABC123")
    third = MultiplayerClientStore(InMemoryTransport(server, "connection-c"))
    third.connect()
    third.join_room("ABC123")
    assert third.last_error["code"] == "ROOM_FULL"
    assert third.status is ClientConnectionState.CONNECTED

    first.select_deck(KANATANA_YELLOW_RECIPE, DECKCODE0_YELLOW_FORCES)
    second.select_deck(DEMETE_GREEN_RECIPE, DECKCODE0_GREEN_FORCES)
    encoded_room = repr(first.room_state)
    assert not any(card_id in encoded_room for card_id in KANATANA_YELLOW_RECIPE)
    assert not any(card_id in encoded_room for card_id in DEMETE_GREEN_RECIPE)


def test_online_match_preserves_cosmetics_names_and_seeded_opening_roll() -> None:
    server = MultiplayerServer(
        room_id_factory=lambda: "room-parity",
        room_code_factory=lambda: "PAR123",
        match_id_factory=lambda: "match-parity",
        seed_factory=lambda: 701,
    )
    first = MultiplayerClientStore(InMemoryTransport(server, "connection-host"))
    second = MultiplayerClientStore(InMemoryTransport(server, "connection-guest"))
    first.connect()
    second.connect()
    first.create_room(display_name="Alice")
    second.join_room("PAR123", display_name="Bob")
    first._send("SELECT_DECK", {
        "deck": dict(KANATANA_YELLOW_RECIPE),
        "forces": list(DECKCODE0_YELLOW_FORCES),
        "profile": {
            "codemanId": "codeman_01_ash_claude",
            "playmatId": "playmat_illust_767258",
        },
    })
    second._send("SELECT_DECK", {
        "deck": dict(DEMETE_GREEN_RECIPE),
        "forces": list(DECKCODE0_GREEN_FORCES),
        "profile": {
            "codemanId": "codeman_02_eilietta_lash",
            "playmatId": "playmat_illust_767258",
        },
    })
    first.set_ready(True)
    second.set_ready(True)

    first_view = first.gameplay_view
    second_view = second.gameplay_view
    assert first_view is not None and second_view is not None
    assert first_view["players"]["human"]["name"] == "Alice"
    assert first_view["players"]["opponent"]["name"] == "Bob"
    assert second_view["players"]["human"]["name"] == "Bob"
    assert first_view["players"]["human"]["profile"]["codemanId"] == "codeman_01_ash_claude"
    assert first_view["players"]["human"]["profile"]["playmatId"] == "playmat_illust_767258"
    assert second_view["players"]["human"]["profile"]["codemanId"] == "codeman_02_eilietta_lash"
    assert first_view["players"]["human"]["isFirstPlayer"] is False
    assert first_view["players"]["opponent"]["isFirstPlayer"] is True
    assert first_view["activeSide"] == second_view["activeSide"] == "P2"
    assert first_view["animationEvents"] == second_view["animationEvents"] == [{
        "type": "dice_roll",
        "value": 6,
        "firstSeat": "right",
    }]
