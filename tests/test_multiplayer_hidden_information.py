import json

from zz.multiplayer.match import AuthoritativeMatch, InitialMatchSpec


def test_player_views_hide_opponent_private_information() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="hidden-info", seed=101))

    player_1 = match.get_view_for("player_1")
    player_2 = match.get_view_for("player_2")

    assert player_1["prompt"] is not None
    assert player_2["prompt"] is None
    assert player_1["players"]["human"]["side"] == "P1"
    assert player_2["players"]["human"]["side"] == "P2"

    for player_id, view in (("player_1", player_1), ("player_2", player_2)):
        opponent = view["players"]["opponent"]
        assert "deck" not in opponent
        opponent_id = "player_2" if player_id == "player_1" else "player_1"
        opponent_state = match.get_view_for(opponent_id)["players"]["human"]
        assert opponent["deckCount"] == opponent_state["deckCount"]
        assert opponent["handCount"] == opponent_state["handCount"]
        for card in opponent["hand"]:
            assert card["faceDown"] is True
            assert "iid" not in card
            assert "cardId" not in card
            assert "nameJp" not in card
            assert "abilityJp" not in card
        assert "seed" not in view
        assert "rngState" not in view

    json.dumps(match.canonical_state(), sort_keys=True)


def test_only_prompt_owner_receives_private_prompt_options() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="prompt-owner", seed=102))

    owner = match.prompt_owner_id()
    assert owner == "player_1"
    assert match.get_view_for(owner)["prompt"]["options"]
    assert match.get_view_for("player_2")["prompt"] is None
