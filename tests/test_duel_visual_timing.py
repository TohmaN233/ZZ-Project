from zz.cards import CARD_REGISTRY
from zz.engine import FIELD_CAP
from zz.enums import AreaType, Step
from zz.model import CardInstance
from zz.web.debug_tools import setup_debug_lab
from zz.web.session import GameSession


def _append_card(session, player, card_id, area):
    card = CardInstance(
        CARD_REGISTRY[card_id],
        player,
        iid=session.engine.state.allocate_iid(),
        area=area,
    )
    if area is AreaType.FIELD:
        player.field.append(card)
    elif area is AreaType.BASE:
        player.base.append(card)
    elif area is AreaType.DECK:
        player.deck.append(card)
    else:
        raise AssertionError(area)
    return card


def _choose_play(session, card_id, **required):
    source = next(card for card in session.engine.state.players[0].hand if card.card.id == card_id)
    play = next(
        option
        for option in session.prompt["options"]
        if option.get("iid") == source.iid and all(option.get(key) == value for key, value in required.items())
    )
    payload = {}
    if play.get("paymentDefaultIids") is not None:
        payload["paymentBaseIids"] = play["paymentDefaultIids"]
    return session.choose(session.prompt["id"], play["id"], payload or None), play


def test_fain_callias_force_option_keeps_prompt_id_and_heals() -> None:
    session = GameSession(seed=501, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "colorless_04_02_01_05",
        zone="hand",
        compact_board=True,
        player_forces=["force_sei", "force_li"],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    player.life = 8
    player.forces[0].life = 8

    result, _play = _choose_play(session, "colorless_04_02_01_05")
    assert result["error"] is None
    prompt = result["prompt"]
    assert prompt["kind"] == "effect_target"
    option_ids = [option["id"] for option in prompt["options"]]
    assert option_ids == list(session._options)
    assert all(option_id.startswith("e") for option_id in option_ids)
    assert "force_sei" not in option_ids

    force_option = next(option for option in prompt["options"] if option.get("targetKind") == "force")
    healed = session.choose(prompt["id"], force_option["id"])
    assert healed["error"] is None
    assert player.forces[0].life == 9
    assert healed["prompt"] is None or healed["prompt"]["kind"] != "effect_target"


def test_full_field_summon_destroys_ejected_card_before_new_card_enters() -> None:
    session = GameSession(seed=502, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "white_01_02_01_00",
        zone="hand",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    ejected = None
    while len(player.field) < FIELD_CAP:
        ejected = _append_card(session, player, "red_02_02_02_00", AreaType.FIELD)
    session._prompt_main_action()

    result, play = _choose_play(session, "white_01_02_01_00", replace_field_iid=ejected.iid)
    assert result["error"] is None
    events = [
        (event["type"], event.get("fromArea"), event.get("toArea"), (event.get("card") or {}).get("iid"))
        for event in result["animationEvents"]
    ]
    destroy_at = next(index for index, event in enumerate(events) if event[0] == "destroy" and event[3] == ejected.iid)
    enter_at = next(
        index
        for index, event in enumerate(events)
        if event[0] == "zone_move" and event[1] == "hand" and event[2] == "field"
    )
    assert destroy_at < enter_at
    assert ejected in player.trash
    assert ejected not in player.field
    assert len(player.field) == FIELD_CAP


def test_movement_right_records_base_and_field_zone_moves() -> None:
    session = GameSession(seed=503, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "white_01_02_01_00",
        zone="base",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player = session.engine.state.players[0]
    moving = next(card for card in player.base if card.card.id == "white_01_02_01_00")
    move = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "move_card"
        and option.get("direction") == "base_to_field"
        and option.get("iid") == moving.iid
    )
    result = session.choose(session.prompt["id"], move["id"])
    assert result["error"] is None
    assert any(
        event["type"] == "zone_move"
        and event.get("fromArea") == "base"
        and event.get("toArea") == "field"
        and event["card"]["iid"] == moving.iid
        for event in result["animationEvents"]
    )
    assert moving in player.field

    session.engine.state.step = Step.MAIN
    player.movement_right_count = 1
    session._prompt_main_action()
    back = next(
        option
        for option in session.prompt["options"]
        if option.get("kind") == "move_card"
        and option.get("direction") == "field_to_base"
        and option.get("iid") == moving.iid
    )
    returned = session.choose(session.prompt["id"], back["id"])
    assert returned["error"] is None
    assert any(
        event["type"] == "zone_move"
        and event.get("fromArea") == "field"
        and event.get("toArea") == "base"
        and event["card"]["iid"] == moving.iid
        for event in returned["animationEvents"]
    )


def test_turn_end_heal_animates_before_opponent_draw() -> None:
    session = GameSession(seed=504, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "green_08_02_01_00",
        zone="field",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player, opponent = session.engine.state.players
    player.life = 8
    while sum(1 for card in player.base if session.engine._mana_color_of(card).name == "GREEN") < 4:
        _append_card(session, player, "green_00_01_01_00", AreaType.BASE)
    for side in (player, opponent):
        if not side.deck:
            _append_card(session, side, "red_02_02_02_00", AreaType.DECK)
    session.engine.state.step = Step.MAIN
    session._prompt_main_action()
    end_turn = next(option for option in session.prompt["options"] if option.get("kind") == "end_turn")
    result = session.choose(session.prompt["id"], end_turn["id"])
    assert result["error"] is None
    types = [event["type"] for event in result["animationEvents"]]
    heal_at = types.index("heal")
    advance_at = next(index for index, event_type in enumerate(types) if event_type in {"turn_begin", "draw"})
    assert heal_at < advance_at
    assert player.life == 9



def test_turn_end_base_refresh_animates_before_opponent_draw() -> None:
    session = GameSession(seed=505, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "green_00_01_01_00",
        zone="base",
        compact_board=True,
        player_forces=[],
        opponent_forces=[],
    )
    player, opponent = session.engine.state.players
    mana = next(card for card in player.base if card.card.id == "green_00_01_01_00")
    mana.rested = True
    for side in (player, opponent):
        if not side.deck:
            _append_card(session, side, "red_02_02_02_00", AreaType.DECK)
    session.engine.state.step = Step.MAIN
    session._prompt_main_action()
    end_turn = next(option for option in session.prompt["options"] if option.get("kind") == "end_turn")
    result = session.choose(session.prompt["id"], end_turn["id"])
    assert result["error"] is None
    assert mana.rested is False
    events = result["animationEvents"]
    refresh_at = next(index for index, event in enumerate(events) if event["type"] == "refresh")
    advance_at = next(index for index, event in enumerate(events) if event["type"] in {"turn_begin", "draw"})
    assert refresh_at < advance_at
    assert events[refresh_at].get("phase") != "refresh"
    assert any(card["iid"] == mana.iid for card in events[refresh_at]["cards"])
    phase_at = next(
        (
            index
            for index, event in enumerate(events)
            if event["type"] == "phase" and event.get("phase") == "refresh"
        ),
        None,
    )
    assert phase_at is not None
    assert phase_at > advance_at



def test_triggered_effect_text_includes_selected_language_variants() -> None:
    session = GameSession(seed=506, mode="debug-card-lab")
    setup_debug_lab(
        session,
        "colorless_04_02_01_05",
        zone="field",
        compact_board=True,
        player_forces=["force_sei", "force_li"],
        opponent_forces=[],
    )
    card = next(item for item in session.engine.state.players[0].field if item.card.id == "colorless_04_02_01_05")
    effect = card.card.effects[0]
    fields = session._effect_text_fields(card, effect)
    assert "召唤" in fields["effectTextZh"]
    assert "召喚" in fields["effectTextJp"]
    assert "Summon" in fields["effectTextEn"] or "summon" in fields["effectTextEn"].lower()
    assert fields["effectTextJp"] != fields["effectTextZh"]
