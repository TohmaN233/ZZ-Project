import json

from zz.multiplayer.match import AuthoritativeMatch, InitialMatchSpec
from zz.web.serialize import serialize_card


def test_player_views_hide_opponent_private_information() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="hidden-info", seed=101))

    player_1 = match.get_view_for("player_1")
    player_2 = match.get_view_for("player_2")

    assert player_1["prompt"]["kind"] == "mulligan"
    assert player_2["prompt"]["kind"] == "mulligan"
    assert player_1["prompt"]["id"] != player_2["prompt"]["id"]
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
    first_prompt = match.get_view_for("player_1")["prompt"]
    second_prompt = match.get_view_for("player_2")["prompt"]
    assert first_prompt["options"]
    assert second_prompt["options"]
    assert first_prompt["id"] != second_prompt["id"]
    assert first_prompt["playerSide"] == "P1"
    assert second_prompt["playerSide"] == "P2"


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
        "area": "hand",
        "rested": False,
    }]


def _collect_url_fields(value, acc=None):
    acc = [] if acc is None else acc
    if isinstance(value, dict):
        for key, item in value.items():
            if "url" in key.lower():
                acc.append((key, item))
            _collect_url_fields(item, acc)
    elif isinstance(value, list):
        for item in value:
            _collect_url_fields(item, acc)
    return acc


def test_player_views_keep_asset_ids_and_omit_image_urls() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="local-assets", seed=104))
    view = match.get_view_for("player_1")
    human_card = view["players"]["human"]["hand"][0]
    assert human_card["assetId"]
    assert "assetUrl" not in human_card
    assert "assetUrlEn" not in human_card
    url_fields = _collect_url_fields(view)
    assert url_fields == []
    assert all(
        not (isinstance(item, str) and item.startswith(("http://", "https://")))
        for item in _walk_strings(view)
    )


def _walk_strings(value):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
