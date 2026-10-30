import pytest

from zz.cards import CARD_REGISTRY
from zz.engine import GameOver
from zz.enums import AreaType, Phase, Step
from zz.model import Action, CardInstance
from zz.multiplayer.views import build_player_view
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_lab
from zz.web.session import GameSession


def test_existing_web_choice_payload_remains_compatible() -> None:
    session = GameSession(seed=401, mode="human-vs-ai")
    prompt = session.prompt
    assert prompt is not None and prompt["kind"] == "mulligan"

    state = session.choose(
        prompt["id"],
        "keep",
        {"promptId": prompt["id"], "optionId": "keep"},
    )

    assert state["error"] is None
    assert session.engine.state.players[0].mulligan_done is True


def test_invalid_payload_does_not_clear_active_prompt() -> None:
    session = GameSession(seed=402, mode="human-vs-ai")
    prompt = session.prompt
    assert prompt is not None

    state = session.choose(
        prompt["id"],
        "keep",
        {"promptId": prompt["id"], "optionId": "keep", "unexpected": True},
    )

    assert state["error"]["code"] == "invalid_payload"
    assert session.prompt is not None
    assert session.prompt["id"] == prompt["id"]


def test_lethal_damage_never_exposes_negative_player_or_force_life() -> None:
    session = GameSession(seed=403, mode="debug-card-lab")
    player = session.engine.state.players[0]
    opponent = session.engine.state.players[1]
    force = player.forces[0]
    source = CardInstance(
        CARD_REGISTRY["red_02_02_02_00"],
        opponent,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.FIELD,
    )
    player.life = 1
    force.life = 1

    with pytest.raises(GameOver):
        session.engine._damage_player(player, 3, source=source)
    assert player.life == 0

    spill = session.engine._damage_force(force, 3, source=source)
    assert force.life == 0
    assert spill == 2


def test_payment_candidates_include_localizable_card_faces() -> None:
    session = GameSession(seed=404, mode="debug-card-lab")
    player = session.engine.state.players[0]
    player.hand.clear()
    player.base.clear()

    played = CardInstance(
        CARD_REGISTRY["red_02_02_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.HAND,
    )
    player.hand.append(played)
    for card_id in ("red_00_01_02_00", "colorless_00_01_02_01"):
        player.base.append(CardInstance(
            CARD_REGISTRY[card_id],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.BASE,
        ))

    meta = session._action_meta(Action(kind="play_card", payload={"iid": played.iid}))

    assert len(meta["paymentCandidates"]) == 2
    for candidate in meta["paymentCandidates"]:
        card = candidate["card"]
        assert card["cardId"] == candidate["cardId"]
        assert card["nameJp"]
        assert card["assetUrl"]


def test_bad_talk_shows_milled_cards_before_trash_target_prompt() -> None:
    session = GameSession(seed=409, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "purple_01_03_02_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    player.deck.clear()
    player.trash.clear()
    for _ in range(3):
        player.deck.append(CardInstance(
            CARD_REGISTRY["red_02_02_02_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.DECK,
        ))

    source = next(card for card in player.hand if card.card.id == "purple_01_03_02_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )

    assert result["prompt"]["kind"] == "effect_target"
    assert result["prompt"]["choiceKind"] == "trash_minion"
    assert len(player.deck) == 0
    assert [card["cardId"] for card in result["prompt"]["options"]] == [
        "red_02_02_02_00",
        "red_02_02_02_00",
        "red_02_02_02_00",
    ]
    assert source.area is AreaType.RESOLVING and source not in player.trash
    assert [
        (event["type"], event.get("fromArea"), event.get("toArea"))
        for event in result["animationEvents"]
    ] == [
        ("zone_move", "hand", "resolving"),
        ("effect", None, None),
        ("zone_move", "deck", "trash"),
        ("zone_move", "deck", "trash"),
        ("zone_move", "deck", "trash"),
    ]
    chosen = result["prompt"]["options"][0]
    result = session.choose(result["prompt"]["id"], chosen["id"])
    assert result["error"] is None and source.area is AreaType.TRASH
    moves = [(event.get("fromArea"), event.get("toArea"))
             for event in result["animationEvents"] if event["type"] == "zone_move"]
    assert moves == [("trash", "hand"), ("resolving", "trash")]


def test_vanjan_payment_metadata_and_default_selection_use_three_mana_value() -> None:
    session = GameSession(seed=405, mode="debug-card-lab")
    player = session.engine.state.players[0]
    player.hand.clear()
    player.base.clear()
    session.engine.state.active_idx = 0
    session.engine.state.phase = Phase.MAIN
    session.engine.state.step = Step.MAIN

    played = CardInstance(
        CARD_REGISTRY["green_05_02_01r_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.HAND,
    )
    player.hand.append(played)
    for card_id in (
        "green_05_02_01r_00",
        "green_00_01_01r_00",
        "colorless_00_01_01r_01",
    ):
        player.base.append(CardInstance(
            CARD_REGISTRY[card_id],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.BASE,
        ))

    session._prompt_main_action()
    option = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == played.iid
    )
    vanjan_candidate = next(
        candidate
        for candidate in option["paymentCandidates"]
        if candidate["cardId"] == "green_05_02_01r_00"
    )

    assert vanjan_candidate["manaValue"] == 3
    assert sum(
        next(candidate for candidate in option["paymentCandidates"] if candidate["iid"] == iid)["manaValue"]
        for iid in option["paymentDefaultIids"]
    ) == 5
    underpaid = session.validate_choice(
        session.prompt["id"],
        option["id"],
        {"paymentBaseIids": option["paymentDefaultIids"][:2]},
    )
    assert underpaid is not None
    assert underpaid["code"] == "illegal_choice"
    assert session.validate_choice(
        session.prompt["id"],
        option["id"],
        {"paymentBaseIids": option["paymentDefaultIids"]},
    ) is None

    result = session.choose(
        session.prompt["id"],
        option["id"],
        {"paymentBaseIids": option["paymentDefaultIids"]},
    )
    assert result["error"] is None
    assert played in player.field


def test_goldweather_session_choice_puts_selected_blue_field_minion_in_base_rested() -> None:
    session = GameSession(seed=406, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "blue_06_02_01r_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    add_debug_card_to_zone(
        session,
        "blue_02_02_01r_00",
        side="P1",
        zone="hand",
        rested=False,
    )
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "blue_06_02_01r_00")

    option = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )
    result = session.choose(
        session.prompt["id"],
        option["id"],
        {"paymentBaseIids": option["paymentDefaultIids"]},
    )
    assert result["prompt"]["kind"] == "effect_target"
    target_option = next(
        option
        for option in result["prompt"]["options"]
        if option.get("cardId") == "blue_02_02_01r_00"
    )

    result = session.choose(result["prompt"]["id"], target_option["id"])

    target = next(card for card in player.base if card.card.id == "blue_02_02_01r_00")
    assert result["error"] is None
    assert target.area is AreaType.BASE
    assert target.rested is True
    assert target not in player.field


def test_goldweather_session_choice_requests_base_replacement_when_base_is_full() -> None:
    session = GameSession(seed=408, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "blue_06_02_01r_00",
        zone="hand",
        compact_board=False,
        player_forces=[],
        opponent_forces=[],
    )
    add_debug_card_to_zone(
        session,
        "blue_02_02_01r_00",
        side="P1",
        zone="hand",
        rested=False,
    )
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "blue_06_02_01r_00")
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )

    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )
    target_option = next(
        option
        for option in result["prompt"]["options"]
        if option.get("cardId") == "blue_02_02_01r_00"
    )
    result = session.choose(result["prompt"]["id"], target_option["id"])

    assert result["prompt"]["choiceKind"] == "ally_base"
    replacement_option = result["prompt"]["options"][0]
    replaced_iid = replacement_option["cardIid"]
    result = session.choose(result["prompt"]["id"], replacement_option["id"])

    target = next(card for card in player.base if card.card.id == "blue_02_02_01r_00")
    assert result["error"] is None
    assert target.area is AreaType.BASE
    assert target.rested is True
    assert all(card.iid != replaced_iid for card in player.base)
    assert any(card.iid == replaced_iid for card in player.trash)


def test_goldweather_full_base_replaces_owner_chosen_card_without_overflow() -> None:
    session = GameSession(seed=410, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "blue_06_02_01r_00",
        zone="hand",
        compact_board=False,
        player_forces=[],
        opponent_forces=[],
    )
    add_debug_card_to_zone(
        session,
        "blue_02_02_01r_00",
        side="P1",
        zone="hand",
        rested=False,
    )
    player = session.engine.state.players[0]
    source = next(card for card in player.hand if card.card.id == "blue_06_02_01r_00")
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )

    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )
    target_option = next(
        option
        for option in result["prompt"]["options"]
        if option.get("cardId") == "blue_02_02_01r_00"
    )
    result = session.choose(result["prompt"]["id"], target_option["id"])

    assert result["prompt"]["choiceKind"] == "ally_base"
    assert result["prompt"]["requiredTargetCount"] == 1
    replacement_option = result["prompt"]["options"][0]
    replaced_iid = replacement_option["cardIid"]
    result = session.choose(result["prompt"]["id"], replacement_option["id"])

    target = next(card for card in player.base if card.card.id == "blue_02_02_01r_00")
    assert result["error"] is None
    assert target.area is AreaType.BASE
    assert target.rested is True
    assert len(player.base) == 10
    assert any(card.iid == replaced_iid for card in player.trash)


def test_book_session_exposes_all_top_four_cards_but_only_reveals_selected_card() -> None:
    session = GameSession(seed=407, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "blue_01_03_01r_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    for card_id in (
        "red_02_02_01r_00",
        "red_02_03_01r_00",
        "blue_02_02_01r_00",
        "green_02_02_01r_00",
    ):
        add_debug_card_to_zone(session, card_id, side="P1", zone="deck")

    player = session.engine.state.players[0]
    source = next(
        card for card in player.hand
        if card.card.id == "blue_01_03_01r_00"
    )
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )
    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )

    assert result["prompt"]["kind"] == "effect_target"
    assert [card["cardId"] for card in result["prompt"]["revealedCards"]] == [
        "red_02_02_01r_00",
        "red_02_03_01r_00",
        "blue_02_02_01r_00",
        "green_02_02_01r_00",
    ]
    target = next(
        option
        for option in result["prompt"]["options"]
        if option.get("cardId") == "red_02_03_01r_00"
    )
    result = session.choose(result["prompt"]["id"], target["id"])

    assert result["error"] is None
    assert source in player.trash
    assert [reveal["card"]["cardId"] for reveal in result["publicReveals"]] == [
        "red_02_03_01r_00",
    ]
    assert result["publicReveals"][0]["reason"] == "deck_search"


def test_revelation_shows_private_top_three_when_no_field_minion_exists() -> None:
    session = GameSession(seed=414, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "yellow_01_03_00_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    player.deck.clear()
    top_cards = [
        CardInstance(
            CARD_REGISTRY["red_00_01_02_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.DECK,
        )
        for _ in range(3)
    ]
    player.deck.extend(top_cards)
    source = next(card for card in player.hand if card.card.id == "yellow_01_03_00_00")
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )

    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )

    prompt = result["prompt"]
    assert prompt["kind"] == "effect_target"
    assert prompt["choiceKind"] == "top3_field_minion"
    assert [card["cardId"] for card in prompt["revealedCards"]] == [
        card.card.id for card in top_cards
    ]
    assert not [option for option in prompt["options"] if option.get("cardIid")]
    finish = next(
        option for option in prompt["options"]
        if option.get("kind") == "effect_target_skip"
    )

    controller_view = build_player_view(
        session,
        player_id="player_1",
        revision=1,
        state_hash="revelation-private-look",
    )
    opponent_view = build_player_view(
        session,
        player_id="player_2",
        revision=1,
        state_hash="revelation-private-look",
    )
    assert len(controller_view["prompt"]["revealedCards"]) == 3
    assert opponent_view["prompt"] is None

    result = session.choose(prompt["id"], finish["id"])

    assert result["error"] is None
    assert source in player.trash
    assert result["publicReveals"] == []
    assert {card.iid for card in player.deck} == {card.iid for card in top_cards}


def test_apprentice_reveals_own_deck_top_and_allows_bottom_choice() -> None:
    session = GameSession(seed=410, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "blue_01_02_02_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    player.deck.clear()
    top_card = CardInstance(
        CARD_REGISTRY["red_02_02_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.DECK,
    )
    following_card = CardInstance(
        CARD_REGISTRY["blue_02_02_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.DECK,
    )
    player.deck.extend([top_card, following_card])
    source = next(card for card in player.hand if card.card.id == "blue_01_02_02_00")
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )

    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )

    assert result["prompt"]["choiceKind"] == "deck_top_or_bottom"
    assert result["prompt"]["playerSide"] == "P1"
    assert result["prompt"]["revealedCards"][0]["cardId"] == top_card.card.id
    bottom = next(option for option in result["prompt"]["options"] if option.get("reorderPosition") == "bottom")
    result = session.choose(result["prompt"]["id"], bottom["id"])

    assert result["error"] is None
    assert player.deck[-1] is top_card
    assert player.deck[0] is following_card
    assert result["publicReveals"] == []


def test_david_private_top_three_shows_controller_window_and_selects_magic_subset() -> None:
    session = GameSession(seed=412, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "blue_06_02_02_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    player.deck.clear()
    top_cards = [
        CardInstance(
            CARD_REGISTRY[card_id],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.DECK,
        )
        for card_id in (
            "red_03_03_02_01",
            "red_02_02_02_00",
            "blue_00_03_02_00",
        )
    ]
    player.deck.extend(top_cards)
    source = next(card for card in player.hand if card.card.id == "blue_06_02_02_00")

    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )
    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )

    prompt = result["prompt"]
    assert prompt["kind"] == "effect_target"
    assert prompt["choiceKind"] == "top3_magic"
    assert prompt["playerSide"] == "P1"
    assert [card["cardId"] for card in prompt["revealedCards"]] == [
        card.card.id for card in top_cards
    ]
    magic_options = [
        option for option in prompt["options"] if option.get("cardIid")
    ]
    assert {option["cardId"] for option in magic_options} == {
        "red_03_03_02_01",
        "blue_00_03_02_00",
    }
    assert prompt["minimumTargetCount"] == 0
    assert prompt["maximumTargetCount"] == 2
    assert prompt["allowVariableTargetCount"] is True

    selected = next(
        option for option in magic_options if option["cardId"] == "red_03_03_02_01"
    )
    result = session.choose(
        prompt["id"],
        selected["id"],
        {"selectedOptionIds": [selected["id"]]},
    )

    assert result["error"] is None
    assert top_cards[0] in player.hand
    assert top_cards[1] in player.deck
    assert top_cards[2] in player.deck
    assert top_cards[2] not in player.hand
    assert [reveal["card"]["cardId"] for reveal in result["publicReveals"]] == [
        "red_03_03_02_01"
    ]
    assert result["publicReveals"][0]["reason"] == "top_magic"


def test_david_private_top_three_still_shows_window_when_no_magic_is_available() -> None:
    session = GameSession(seed=413, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "blue_06_02_02_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    player.deck.clear()
    top_cards = [
        CardInstance(
            CARD_REGISTRY["red_02_02_02_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.DECK,
        )
        for _ in range(3)
    ]
    player.deck.extend(top_cards)
    source = next(card for card in player.hand if card.card.id == "blue_06_02_02_00")
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )

    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )

    prompt = result["prompt"]
    assert prompt["choiceKind"] == "top3_magic"
    assert len(prompt["revealedCards"]) == 3
    assert not [option for option in prompt["options"] if option.get("cardIid")]
    skip = next(option for option in prompt["options"] if option.get("kind") == "effect_target_skip")
    result = session.choose(prompt["id"], skip["id"])

    assert result["error"] is None
    assert len(player.deck) == 3
    assert result["publicReveals"] == []


def test_warhammer_bless_prompts_field_replacement_and_creates_token() -> None:
    session = GameSession(seed=408, mode="debug-card-lab")
    player = session.engine.state.players[0]
    player.field.clear()
    player.base.clear()
    player.trash.clear()
    host = CardInstance(
        CARD_REGISTRY["red_05_02_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.FIELD,
    )
    fillers = [
        CardInstance(
            CARD_REGISTRY["red_02_02_02_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.FIELD,
        )
        for _ in range(4)
    ]
    mana = CardInstance(
        CARD_REGISTRY["red_00_01_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.BASE,
    )
    player.field[:] = [host, *fillers]
    player.base[:] = [mana]
    player.movement_right_count = 1
    session.engine.state.active_idx = 0
    session.engine.state.step = Step.MAIN

    action = Action(
        kind="bless",
        payload={"mana_iid": mana.iid, "target_iid": host.iid},
    )
    session._perform_action(action, actor=player)

    assert session.prompt is not None
    assert session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "ally_minion"
    replacement = next(
        option for option in session.prompt["options"]
        if option.get("cardIid") == fillers[0].iid
    )
    result = session.choose(session.prompt["id"], replacement["id"])

    assert result["error"] is None
    assert len(player.field) == 5
    assert sum(card.card.id == "s_golem_token" for card in player.field) == 1
    assert fillers[0] in player.trash


def test_maelstrom_prompts_replacements_and_creates_all_tokens_on_full_field() -> None:
    session = GameSession(seed=411, mode="debug-card-lab")
    player = session.engine.state.players[0]
    player.hand.clear()
    player.field.clear()
    player.base.clear()
    player.trash.clear()
    source = CardInstance(
        CARD_REGISTRY["blue_010_03_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.HAND,
    )
    fillers = [
        CardInstance(
            CARD_REGISTRY["red_02_02_02_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.FIELD,
        )
        for _ in range(5)
    ]
    payment = [
        CardInstance(
            CARD_REGISTRY["blue_00_01_00_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.BASE,
        )
        for _ in range(10)
    ]
    player.hand.append(source)
    player.field[:] = fillers
    player.base[:] = payment
    session.engine.state.active_idx = 0
    session.engine.state.step = Step.MAIN

    session._prompt_main_action()
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "play_card" and option.get("iid") == source.iid
    )
    result = session.choose(
        session.prompt["id"],
        play["id"],
        {"paymentBaseIids": play["paymentDefaultIids"]},
    )

    assert result["prompt"] is not None
    assert result["prompt"]["kind"] == "effect_target"
    assert result["prompt"]["choiceKind"] == "ally_minion"
    assert result["prompt"]["requiredTargetCount"] == 4
    replacement_ids = [option["id"] for option in result["prompt"]["options"][:4]]
    result = session.choose(
        result["prompt"]["id"],
        replacement_ids[0],
        {"selectedOptionIds": replacement_ids},
    )

    assert result["error"] is None
    assert source in player.trash
    assert len(player.field) == 5
    assert [card.card.id for card in player.field].count("colorless_01_04_00_01") == 1
    assert [card.card.id for card in player.field].count("colorless_03_04_00_00") == 1
    assert [card.card.id for card in player.field].count("colorless_04_04_00_01") == 1
    assert [card.card.id for card in player.field].count("colorless_05_04_00_00") == 1
    assert all(card in player.trash for card in fillers[:4])


def test_allysinashion_destroy_chooses_token_count_before_field_replacement() -> None:
    session = GameSession(seed=412, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "purple_07_02_01r_00",
        zone="field",
        player_forces=["force_e", "force_so2"],
        opponent_forces=["force_kon", "force_rin"],
    )
    player = session.engine.state.players[0]
    player.field.extend(
        CardInstance(
            CARD_REGISTRY["red_02_02_02_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.FIELD,
        )
        for _ in range(2)
    )
    replacement = player.field[1]
    source = next(card for card in player.field if card.card.id == "purple_07_02_01r_00")

    session._clear_prompt()
    session.engine.destroy_target(source, None)

    assert session.prompt is not None
    assert session.prompt["kind"] == "optional_effect"
    assert [option["id"] for option in session.prompt["options"]] == [
        "count_0",
        "count_1",
        "count_2",
        "count_3",
    ]

    result = session.choose(session.prompt["id"], "count_2")
    assert result["prompt"] is not None
    assert result["prompt"]["kind"] == "effect_target"
    assert result["prompt"]["choiceKind"] == "ally_minion"
    assert result["prompt"]["requiredTargetCount"] == 1
    assert result["prompt"]["minimumTargetCount"] == 1
    assert result["prompt"]["maximumTargetCount"] == 1
    assert not any(option.get("kind") == "effect_target_skip" for option in result["prompt"]["options"])
    replacement_option = next(
        option for option in result["prompt"]["options"]
        if option.get("cardIid") == replacement.iid
    )

    result = session.choose(result["prompt"]["id"], replacement_option["id"])

    assert result["error"] is None
    assert len(player.field) == 5
    assert sum(card.card.id == "s_aryushinashion_token" for card in player.field) == 2
    assert replacement in player.trash


def test_return_to_hand_detaches_bless_before_full_base_replacement_prompt() -> None:
    session = GameSession(seed=409, mode="debug-card-lab")
    player = session.engine.state.players[0]
    player.hand.clear()
    player.field.clear()
    player.base.clear()
    player.trash.clear()
    host = CardInstance(
        CARD_REGISTRY["red_04_02_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.FIELD,
    )
    mana = CardInstance(
        CARD_REGISTRY["red_00_01_02_00"],
        player,
        iid=session.engine.state.allocate_iid(),
        area=AreaType.BASE,
    )
    player.field.append(host)
    player.base.append(mana)
    player.movement_right_count = 1
    session.engine.state.active_idx = 0
    session.engine.state.step = Step.MAIN

    session.engine.bless(mana, host)
    player.base.extend(
        CardInstance(
            CARD_REGISTRY["colorless_00_01_01_00"],
            player,
            iid=session.engine.state.allocate_iid(),
            area=AreaType.BASE,
        )
        for _ in range(10 - len(player.base))
    )

    session.engine.return_to_hand(host)
    assert host in player.hand
    assert host.blessings == []
    assert session.engine.pending_blessing_returns == [(host, mana)]

    session._advance_after_user_choice(limit=20)
    assert session.prompt is not None
    assert session.prompt["kind"] == "blessing_base_replacement"
    serialized_host = next(
        card
        for card in session.state_dto()["players"]["human"]["hand"]
        if card["iid"] == host.iid
    )
    assert serialized_host["blessings"] == []
    replacement_option = session.prompt["options"][0]
    assert replacement_option["kind"] == "base_replacement"
    assert replacement_option["iid"] == mana.iid
    replaced_iid = replacement_option["replace_base_iid"]
    result = session.choose(session.prompt["id"], replacement_option["id"])

    assert result["error"] is None
    assert host in player.hand
    assert host.blessings == []
    assert len(player.base) == 10
    assert mana in player.base
    assert mana.area is AreaType.BASE
    assert mana.rested is True
    assert session.engine.pending_blessing_returns == []
    assert all(card.iid != replaced_iid for card in player.base)
    assert any(card.iid == replaced_iid for card in player.trash)
