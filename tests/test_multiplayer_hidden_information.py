import json

from zz.multiplayer.match import AuthoritativeMatch, InitialMatchSpec
from zz.web.serialize import serialize_card


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


def test_opponent_draw_animation_uses_only_the_local_card_back() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="hidden-draw", seed=103))
    player_1 = match.session.engine.state.players[0]
    secret = serialize_card(
        match.session.engine,
        player_1.hand[0],
        match.session.asset_index,
    )
    match._animation_events = ({
        "type": "draw",
        "side": "P1",
        "count": 1,
        "cards": [secret],
    },)

    owner_event = match.get_view_for("player_1")["animationEvents"][0]
    opponent_event = match.get_view_for("player_2")["animationEvents"][0]
    assert owner_event["cards"][0]["cardId"] == secret["cardId"]
    assert opponent_event["cards"] == [{
        "ownerSide": "P1",
        "faceDown": True,
        "assetId": "card_back",
        "assetUrl": match.session.asset_index.asset_url("card_back"),
        "area": "hand",
        "rested": False,
    }]
