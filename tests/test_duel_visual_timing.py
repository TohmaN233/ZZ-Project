from zz.cards import CARD_REGISTRY
from zz.engine import FIELD_CAP
from zz.enums import AreaType, Color, Step
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


def _mutual_battle_events(*, override_color=None):
    session = GameSession(seed=831, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_02_02_00_01", zone="field", compact_board=True,
                    player_forces=[], opponent_forces=[])
    session.debug_control_both = True
    player, opponent = session.engine.state.players
    attacker = player.field[0]
    attacker.summoning_sickness = False
    blocker = _append_card(session, opponent, "colorless_02_02_01_02", AreaType.FIELD)
    blocker.mana_color_override = override_color
    session.engine.state.present_at_turn_start = {attacker.iid, blocker.iid}
    session._prompt_main_action()
    attack = next(option for option in session.prompt["options"]
                  if option.get("attacker_iid") == attacker.iid)
    result = session.choose(session.prompt["id"], attack["id"])
    events = list(result["animationEvents"])
    for kind in ("attack_target", "flash_action", "flash_action", "blocker"):
        assert result["error"] is None
        assert session.prompt["kind"] == kind
        option = next(option for option in session.prompt["options"] if (
            option.get("kind") == "player" if kind == "attack_target" else
            option.get("kind") == "flash_pass" if kind == "flash_action" else
            option.get("cardIid") == blocker.iid))
        result = session.choose(session.prompt["id"], option["id"])
        events.extend(result["animationEvents"])
    assert result["error"] is None
    assert attacker.area is blocker.area is AreaType.TRASH
    return events, attacker, blocker


def test_mutual_battle_destruction_keeps_opposing_source():
    events, attacker, blocker = _mutual_battle_events()
    deaths = {event["card"]["iid"]: event for event in events if event["type"] == "destroy"}
    assert len(deaths) == 2
    for victim, source, color in ((blocker, attacker, "YELLOW"), (attacker, blocker, "COLORLESS")):
        event = deaths[victim.iid]
        assert event.get("cause") == "battle", event
        assert event["sourceCard"]["iid"] == source.iid
        assert event["sourceCard"]["manaColor"] == color
        assert event["sourceCard"]["area"] == "field"
    assert not any(event["type"] == "effect" for event in events), "vanilla battle must not invent an ability"
    assert not any(event["type"] == "damage" for event in events), "blocked mutual destruction does not hit life"


def test_unblocked_attack_emits_one_actual_damage_event_after_declaration():
    session = GameSession(seed=991, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_02_02_00_01", zone="field", compact_board=True,
                    player_forces=[], opponent_forces=[])
    session.debug_control_both = True
    attacker = session.engine.state.players[0].field[0]
    attacker.summoning_sickness = False
    attacker.rested = False
    session.engine.state.present_at_turn_start = {attacker.iid}
    session._prompt_main_action()
    attack = next(option for option in session.prompt["options"] if option.get("attacker_iid") == attacker.iid)
    result = session.choose(session.prompt["id"], attack["id"])
    events = list(result["animationEvents"])
    target = next(option for option in session.prompt["options"] if option.get("kind") == "player")
    result = session.choose(session.prompt["id"], target["id"])
    events.extend(result["animationEvents"])
    while session.prompt["kind"] == "flash_action":
        option = next(option for option in session.prompt["options"] if option.get("kind") == "flash_pass")
        result = session.choose(session.prompt["id"], option["id"])
        assert result["error"] is None
        events.extend(result["animationEvents"])
    assert [event["type"] for event in events].count("attack") == 1
    hits = [event for event in events if event["type"] == "damage"]
    assert len(hits) == 1 and hits[0]["amount"] == 1
    assert events.index(hits[0]) > next(i for i, event in enumerate(events) if event["type"] == "attack")


def test_mutual_battle_source_color_is_frozen_before_either_card_leaves():
    events, attacker, blocker = _mutual_battle_events(override_color=Color.BLUE)
    assert blocker.mana_color_override is None, "zone cleanup must still run"
    death = next(event for event in events if event["type"] == "destroy" and event["card"]["iid"] == attacker.iid)
    assert death["sourceCard"]["manaColor"] == "BLUE"


def test_removal_events_distinguish_effect_self_and_rule_causes():
    session = GameSession(seed=832, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_02_02_00_01", zone="field", compact_board=True,
                    player_forces=[], opponent_forces=[])
    player, opponent = session.engine.state.players
    source = player.field[0]
    victim = _append_card(session, opponent, "colorless_02_02_01_02", AreaType.FIELD)
    session.engine.visual_events.clear()
    session.engine._destroy(victim, source=source)
    effect_death = next(event for event in session.engine.visual_events if event["type"] == "destroy")
    assert effect_death.get("cause") == "effect"
    assert effect_death["sourceCard"]["iid"] == source.iid
    for cause in ("replacement", "rule", "self"):
        card = _append_card(session, player, "yellow_02_02_00_01", AreaType.FIELD)
        session.engine.visual_events.clear()
        if cause == "replacement":
            session.engine._eject_field_card(player, card)
        else:
            session.engine._destroy(card, source=card if cause == "self" else None)
        raw = next(event for event in session.engine.visual_events if event["type"] == "destroy")
        event = session._animation_event_from_engine_visual_event(raw)
        assert event.get("cause") == cause
        assert (event.get("sourceCard") or {}).get("iid") == (card.iid if cause == "self" else None)


def test_destruction_attribution_never_discloses_a_private_source():
    session = GameSession(seed=833, mode="debug-card-lab")
    setup_debug_lab(session, "yellow_02_02_00_01", zone="field", compact_board=True,
                    player_forces=[], opponent_forces=[])
    player, opponent = session.engine.state.players
    for area in (AreaType.HAND, AreaType.DECK):
        source = CardInstance(CARD_REGISTRY["yellow_02_02_00_01"], opponent,
                              iid=session.engine.state.allocate_iid(), area=area)
        victim = _append_card(session, player, "colorless_02_02_01_02", AreaType.FIELD)
        session.engine.visual_events.clear()
        session.engine._destroy(victim, source=source)
        raw = next(event for event in session.engine.visual_events if event["type"] == "destroy")
        event = session._animation_event_from_engine_visual_event(raw)
        assert event["sourceCard"] == {"ownerSide": "P2", "area": area.value, "faceDown": True}


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
    assert not any(event["type"] == "effect" or event.get("summonFx") for event in result["animationEvents"])

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
    assert not any(event["type"] == "effect" or event.get("summonFx") for event in returned["animationEvents"])


def test_retreat_with_a_real_ability_still_activates_once():
    session = GameSession(seed=834, mode="debug-card-lab")
    setup_debug_lab(session, "blue_08_02_01r_00", zone="field", compact_board=True,
                    player_forces=[], opponent_forces=[])
    card = session.engine.state.players[0].field[0]
    move = next(option for option in session.prompt["options"]
                if option.get("kind") == "move_card" and option.get("iid") == card.iid
                and option.get("direction") == "field_to_base")
    result = session.choose(session.prompt["id"], move["id"])
    assert result["error"] is None
    assert [event["type"] for event in result["animationEvents"]] == ["zone_move", "effect"]
    assert result["animationEvents"][1]["card"]["iid"] == card.iid
    assert not any(event.get("summonFx") for event in result["animationEvents"])


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
