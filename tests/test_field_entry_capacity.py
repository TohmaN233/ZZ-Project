import pytest

from zz.cards import CARD_REGISTRY
from zz.effects import EffectTiming
from zz.enums import AreaType, CardType, Color, Step
from zz.model import Card, CardInstance, Context
from zz.web.session import GameSession


def setup_game():
    session = GameSession(seed=91, mode="god")
    session._clear_prompt()
    engine = session.engine
    engine.state.step = Step.MAIN
    engine.state.active_idx = 0
    for player in engine.state.players:
        for zone in (player.field, player.base, player.hand, player.trash, player.deck):
            zone.clear()
    return session, engine, *engine.state.players


def add(engine, owner, card, area=AreaType.FIELD):
    instance = CardInstance(card, owner, iid=engine.state.allocate_iid(), area=area)
    getattr(owner, area.value).append(instance)
    return instance


def filler(engine, owner, name, **kwargs):
    return add(engine, owner, Card(name, name, name, CardType.F_MINION, bp=300, **kwargs))


def choose_cards(session, cards):
    options = {option.get("cardIid"): option["id"] for option in session.prompt["options"]}
    ids = [options[card.iid] for card in cards]
    payload = {"selectedOptionIds": ids} if len(ids) > 1 else None
    result = session.choose(session.prompt["id"], ids[0], payload)
    assert result["error"] is None, result["error"]
    return result


@pytest.mark.parametrize("replace_source", [False, True])
def test_knives_full_field_revives_before_placing_mana(replace_source):
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_04_01_03_00"])
    fillers = [filler(engine, owner, f"field-{i}", cannot_move=i == 0) for i in range(4)]
    fillers[0].card.effect_targetable = lambda *_: False
    target = add(engine, owner, Card("skeleton", "skeleton", "skeleton", CardType.F_MINION,
                                    cost={Color.PURPLE: 6}, bp=300, race_jp="スケルトン"), AreaType.TRASH)
    too_expensive = add(engine, owner, Card("expensive", "expensive", "expensive", CardType.F_MINION,
                                           cost={Color.PURPLE: 7}, bp=300, race_jp="スケルトン"), AreaType.TRASH)
    wrong_race = add(engine, owner, Card("dragon", "dragon", "dragon", CardType.F_MINION,
                                        bp=300, race_jp="ドラゴン"), AreaType.TRASH)
    for _ in range(10):
        engine.place_generated_colorless_mana(owner)

    engine.transform_card(source, CARD_REGISTRY["purple_04_01_03_01"])
    assert session.prompt["choiceKind"] == "trash_field_minion"
    options = {option.get("cardIid") for option in session.prompt["options"]}
    assert target.iid in options and too_expensive.iid not in options and wrong_race.iid not in options
    assert not any(option.get("kind") == "effect_target_skip" for option in session.prompt["options"])
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    assert target in owner.trash and len(owner.field) == 5
    replacement = source if replace_source else fillers[0]
    choose_cards(session, [replacement])
    assert target in owner.field and replacement in owner.trash and len(owner.field) == 5
    assert replacement not in engine.destroy_events
    assert session.prompt["choiceKind"] == "ally_base"
    assert not any(ci.mana_color_override is Color.PURPLE for ci in owner.base)
    choose_cards(session, [owner.base[0]])
    assert len(owner.base) == 10
    assert sum(ci.mana_color_override is Color.PURPLE and ci.rested for ci in owner.base) == 1
    assert session._pending_effect is None


def test_knives_ai_replaces_field_minion_when_reviving():
    from zz.ai import PassOnlyPolicy

    _, engine, owner, _ = setup_game()
    engine.defer_trigger_choice = None
    engine.defer_source_effect_choice = None
    engine.set_policies(PassOnlyPolicy(), PassOnlyPolicy())
    source = add(engine, owner, CARD_REGISTRY["purple_04_01_03_00"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, Card("skeleton", "skeleton", "skeleton", CardType.F_MINION,
                                    bp=300, race_jp="スケルトン"), AreaType.TRASH)
    engine.transform_card(source, CARD_REGISTRY["purple_04_01_03_01"])
    assert target in owner.field and len(owner.field) == 5
    assert sum(card in owner.trash for card in [source, *fillers]) == 1
    assert sum(ci.mana_color_override is Color.PURPLE for ci in owner.base) == 1


def test_knives_real_bless_action_revives_on_full_field():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_04_01_03_00"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, Card("skeleton", "skeleton", "skeleton", CardType.F_MINION,
                                    bp=300, race_jp="スケルトン"), AreaType.TRASH)
    mana = add(engine, owner, CARD_REGISTRY["purple_00_01_02_00"], AreaType.BASE)
    owner.movement_right_count = 1
    session._prompt_main_action()
    action = next(option for option in session.prompt["options"]
                  if option.get("kind") == "bless" and option.get("mana_iid") == mana.iid
                  and option.get("target_iid") == source.iid)
    result = session.choose(session.prompt["id"], action["id"])
    assert result["error"] is None and source.card.id == "purple_04_01_03_01"
    assert session.prompt["choiceKind"] == "trash_field_minion"
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [fillers[0]])
    assert target in owner.field and fillers[0] in owner.trash and mana in owner.removed
    assert len(owner.field) == 5 and owner.movement_right_count == 0
    assert sum(ci.mana_color_override is Color.PURPLE and ci.rested for ci in owner.base) == 1


def test_knives_no_legal_resurrection_still_places_mana_without_replacement_prompt():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_04_01_03_00"])
    for i in range(4):
        filler(engine, owner, f"field-{i}")
    wrong = add(engine, owner, Card("dragon", "dragon", "dragon", CardType.F_MINION,
                                    bp=300, race_jp="ドラゴン"), AreaType.TRASH)
    engine.transform_card(source, CARD_REGISTRY["purple_04_01_03_01"])
    assert wrong in owner.trash and len(owner.field) == 5
    assert sum(ci.mana_color_override is Color.PURPLE and ci.rested for ci in owner.base) == 1
    assert session.prompt is None or session.prompt.get("kind") != "effect_target"


def test_resurrection_replacement_returns_blessing_when_base_is_full():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_04_01_03_00"])
    host = filler(engine, owner, "host")
    for i in range(3):
        filler(engine, owner, f"field-{i}")
    mana = CardInstance(CARD_REGISTRY["purple_00_01_02_00"], owner,
                        iid=engine.state.allocate_iid(), area=AreaType.BLESSING)
    host.blessings.append(mana)
    target = add(engine, owner, Card("skeleton", "skeleton", "skeleton", CardType.F_MINION,
                                    bp=300, race_jp="スケルトン"), AreaType.TRASH)
    for _ in range(10):
        engine.place_generated_colorless_mana(owner)
    engine.transform_card(source, CARD_REGISTRY["purple_04_01_03_01"])
    choose_cards(session, [target])
    choose_cards(session, [host])
    assert target in owner.field and host in owner.trash and host not in engine.destroy_events
    for _ in range(2):
        prompt = session.prompt
        assert prompt["playerSide"] == "P1"
        if prompt["kind"] == "blessing_base_replacement":
            option = prompt["options"][0]
            assert session.choose(prompt["id"], option["id"])["error"] is None
        else:
            assert prompt["choiceKind"] == "ally_base"
            choose_cards(session, [owner.base[0]])
    assert mana in owner.base and mana.rested and len(owner.base) == 10
    assert sum(ci.mana_color_override is Color.PURPLE for ci in owner.base) == 1
    assert not engine.pending_blessing_returns


def test_resurrection_replacing_token_removes_it_without_destroying_it():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_04_01_03_00"])
    token = filler(engine, owner, "token", is_token=True)
    for i in range(3):
        filler(engine, owner, f"field-{i}")
    target = add(engine, owner, Card("skeleton", "skeleton", "skeleton", CardType.F_MINION,
                                    bp=300, race_jp="スケルトン"), AreaType.TRASH)
    engine.transform_card(source, CARD_REGISTRY["purple_04_01_03_01"])
    choose_cards(session, [target])
    choose_cards(session, [token])
    assert target in owner.field and len(owner.field) == 5
    assert token not in owner.field and token not in owner.trash and token not in owner.removed
    assert token not in engine.destroy_events


def test_invalid_resurrection_cannot_eject_a_field_minion():
    from zz.engine import IllegalActionError

    _, engine, owner, opponent = setup_game()
    field = [filler(engine, owner, f"field-{i}") for i in range(5)]
    foreign = add(engine, opponent, Card("foreign", "foreign", "foreign", CardType.F_MINION,
                                        bp=300), AreaType.TRASH)
    with pytest.raises(IllegalActionError, match="not in trash"):
        engine.summon_from_trash(owner, foreign, replace_field_iid=field[0].iid)
    assert owner.field == field and foreign in opponent.trash


def test_debug_control_both_allows_second_player_to_choose_target_and_replacement():
    from zz.web.debug_tools import set_debug_control

    session, engine, _, owner = setup_game()
    session.mode = "debug-card-lab"
    session._configure_mode_controls()
    set_debug_control(session, True)
    session._clear_prompt()
    engine.state.active_idx = 1
    source = add(engine, owner, CARD_REGISTRY["purple_04_01_03_00"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, Card("skeleton", "skeleton", "skeleton", CardType.F_MINION,
                                    bp=300, race_jp="スケルトン"), AreaType.TRASH)
    engine.transform_card(source, CARD_REGISTRY["purple_04_01_03_01"])
    assert session.prompt["playerSide"] == "P2"
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion" and session.prompt["playerSide"] == "P2"
    choose_cards(session, [fillers[0]])
    assert target in owner.field and fillers[0] in owner.trash and len(owner.field) == 5
    set_debug_control(session, False)
    assert engine.policy_for(owner) is not session.human_policy


def test_pc01_resurrection_template_asks_for_field_replacement():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_06_02_01_00"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, Card("revive", "revive", "revive", CardType.F_MINION,
                                    bp=300, cost={Color.PURPLE: 3}), AreaType.TRASH)
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    assert session.prompt["choiceKind"] == "trash_field_minion"
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [fillers[0]])
    assert target in owner.field and fillers[0] in owner.trash and len(owner.field) == 5


def test_pc01_special_trash_card_uses_one_field_replacement_when_revived_directly():
    from zz.effects import build_effect

    session, engine, owner, _ = setup_game()
    effect = build_effect("summon_from_trash", EffectTiming.ON_SUMMON, target_kind="trash_field_minion")
    source = filler(engine, owner, "source", effects=[effect])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, CARD_REGISTRY["purple_04_02_01_00"], AreaType.TRASH)
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    assert session.prompt["requiredTargetCount"] == 1
    choose_cards(session, [fillers[0]])
    assert target in owner.field and fillers[0] in owner.trash and len(owner.field) == 5


def test_returning_grave_rover_to_hand_requires_field_replacement():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_05_02_00_00"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, CARD_REGISTRY["purple_04_02_01_00"], AreaType.TRASH)
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [fillers[0]])
    assert target in owner.field and target not in owner.hand
    assert fillers[0] in owner.trash and len(owner.field) == 5


def test_petit_diable_return_from_trash_replaces_field_minion():
    session, engine, owner, _ = setup_game()
    field = [filler(engine, owner, f"field-{i}") for i in range(5)]
    target = add(engine, owner, CARD_REGISTRY["purple_05_01_03_01"], AreaType.TRASH)
    engine.add_to_hand(owner, target, from_area=AreaType.TRASH)
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [field[0]])
    assert target in owner.field and target not in owner.hand
    assert field[0] in owner.trash and len(owner.field) == 5


def test_rekindled_revives_two_with_two_distinct_field_replacements():
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_07_02_02r_01"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    targets = [add(engine, owner, Card(f"revive-{i}", "revive", "revive", CardType.F_MINION,
                                      bp=300, cost={Color.PURPLE: 3}), AreaType.TRASH)
               for i in range(2)]
    for force in opponent.forces:
        force.destroyed = True
    engine._resolve_source_effects(source, EffectTiming.ON_ATTACK, Context(controller=owner, source=source))
    assert session.prompt["choiceKind"] == "trash_field_minion"
    choose_cards(session, targets)
    assert session.prompt["choiceKind"] == "ally_minion"
    assert session.prompt["requiredTargetCount"] == 2
    choose_cards(session, fillers[:2])
    assert all(target in owner.field for target in targets)
    assert all(card in owner.trash and card not in engine.destroy_events for card in fillers[:2])
    assert len(owner.field) == 5 and session._pending_effect is None


def test_dorothy_turn_end_self_resurrection_can_replace_field_minion():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_04_02_02r_01"], AreaType.TRASH)
    dragon = filler(engine, owner, "purple_dragon", race_jp="ドラゴン")
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    engine.end_turn()
    assert session.prompt["choiceKind"] == "ally_minion"
    assert source in owner.trash and engine.state.active is owner
    choose_cards(session, [fillers[0]])
    assert source in owner.field and fillers[0] in owner.trash and dragon in owner.field
    assert len(owner.field) == 5 and engine.state.active is not owner


@pytest.mark.parametrize("card_id", ["colorless_06_02_02c_00", "colorless_06_02_EX02_00"])
@pytest.mark.parametrize("use_effect", [False, True])
def test_ex02_self_resurrection_on_full_field_respects_choice(card_id, use_effect):
    session, engine, owner, opponent = setup_game()
    owner.life = 5
    source = add(engine, owner, CARD_REGISTRY[card_id], AreaType.TRASH)
    fillers = [filler(engine, owner, f"field-{i}") for i in range(5)]
    enemy = filler(engine, opponent, "enemy")
    ctx = Context(controller=owner, source=enemy, target=source, battle_participants=(source, enemy))
    engine._resolve_source_effects(source, EffectTiming.ON_DESTROY, ctx)
    assert session.prompt["kind"] == "optional_effect"
    option = "yes" if use_effect else "no"
    assert session.choose(session.prompt["id"], option)["error"] is None
    if use_effect:
        assert session.prompt["choiceKind"] == "ally_minion"
        assert owner.life == 5 and source in owner.trash
        choose_cards(session, [fillers[0]])
        assert source in owner.field and fillers[0] in owner.trash and owner.life == 4
    else:
        assert source in owner.trash and all(card in owner.field for card in fillers)
        assert owner.life == 5
    assert len(owner.field) == 5


def test_priest_copy_from_enemy_trash_asks_for_field_replacement():
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["purple_06_01_03_00"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, opponent, Card("copy-me", "copy-me", "copy-me", CardType.F_MINION,
                                       bp=300), AreaType.TRASH)
    engine.destroy_target(source, None)
    assert session.prompt["choiceKind"] == "enemy_trash_field_minion"
    filler(engine, owner, "another-entry")
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [fillers[0]])
    assert target in opponent.trash and fillers[0] in owner.trash
    assert any(ci.card.id == target.card.id and not ci.card.is_token for ci in owner.field)
    assert len(owner.field) == 5


def test_shaina_puts_selected_hand_dragon_on_full_field():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_07_02_02r_02"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, Card("dragon", "dragon", "dragon", CardType.F_MINION,
                                    bp=300, printed_color=Color.RED, race_jp="ドラゴン"), AreaType.HAND)
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    assert session.prompt["choiceKind"] == "hand_card"
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [fillers[0]])
    assert target in owner.field and fillers[0] in owner.trash
    assert "cannot_move" in target.flags and len(owner.field) == 5


def test_skipping_optional_hand_entry_does_not_require_field_replacement():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_07_02_02r_02"])
    fillers = [filler(engine, owner, f"field-{i}") for i in range(4)]
    target = add(engine, owner, Card("dragon", "dragon", "dragon", CardType.F_MINION,
                                    bp=300, printed_color=Color.RED, race_jp="ドラゴン"), AreaType.HAND)
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    skip = next(option for option in session.prompt["options"] if option.get("kind") == "effect_target_skip")
    assert session.choose(session.prompt["id"], skip["id"])["error"] is None
    assert target in owner.hand and all(card in owner.field for card in [source, *fillers])
    assert session.prompt is None or session.prompt.get("choiceKind") != "ally_minion"


def test_shape_shift_can_replace_the_minion_being_copied_on_a_full_field():
    session, engine, owner, _ = setup_game()
    original = filler(engine, owner, "red-original", printed_color=Color.RED,
                      cost={Color.RED: 2}, race_jp="ドラゴン")
    for i in range(4):
        filler(engine, owner, f"field-{i}")
    spell = add(engine, owner, CARD_REGISTRY["red_03_03_02_00"], AreaType.HAND)
    for _ in range(3):
        engine.place_generated_colorless_mana(owner, mana_color=Color.RED)
    session._prompt_main_action()
    play = next(option for option in session.prompt["options"]
                if option.get("kind") == "play_card" and option.get("iid") == spell.iid)
    assert session.choose(session.prompt["id"], play["id"])["error"] is None
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [original])
    assert session.prompt["choiceKind"] == "ally_minion"
    choose_cards(session, [original])
    copies = [ci for ci in owner.field if ci.card.id == original.card.id]
    assert original in owner.trash and len(copies) == 1 and copies[0] is not original
    assert spell in owner.trash and len(owner.field) == 5


def test_fossil_counts_only_the_deck_card_for_field_replacement():
    session, engine, owner, _ = setup_game()
    fillers = [filler(engine, owner, f"field-{i}") for i in range(5)]
    spell = add(engine, owner, CARD_REGISTRY["red_08_03_02_00"], AreaType.HAND)
    target = add(engine, owner, Card("dragon", "dragon", "dragon", CardType.F_MINION,
                                    bp=300, printed_color=Color.RED, race_jp="ドラゴン"), AreaType.DECK)
    for _ in range(8):
        engine.place_generated_colorless_mana(owner, mana_color=Color.RED)
    mana = engine.place_generated_colorless_mana(owner)
    session._prompt_main_action()
    play = next(option for option in session.prompt["options"]
                if option.get("kind") == "play_card" and option.get("iid") == spell.iid)
    assert session.choose(session.prompt["id"], play["id"])["error"] is None
    assert session.prompt["choiceKind"] == "ally_colorless_mana_token"
    choose_cards(session, [mana])
    assert session.prompt["choiceKind"] == "pc02_fossil_dragon"
    choose_cards(session, [target])
    assert session.prompt["choiceKind"] == "ally_minion"
    assert session.prompt["requiredTargetCount"] == 1
    choose_cards(session, [fillers[0]])
    assert target in owner.field and fillers[0] in owner.trash and len(owner.field) == 5
    assert mana not in owner.base and spell in owner.trash


def test_registered_field_entry_callbacks_declare_capacity_choices():
    import inspect

    setup_game()
    entry_methods = (
        ".summon_from_trash(", ".summon_from_deck(", ".summon_from_hand(",
        ".put_field_minion_from_hand(", ".create_field_minions(",
        "_put_field_minion_from_zone(", "_put_field_minion_from_hand(",
    )
    checked = []
    missing = []
    for card in CARD_REGISTRY.values():
        for effect in card.effects:
            source = inspect.getsource(effect.fn)
            if not any(method in source for method in entry_methods):
                continue
            checked.append(card.id)
            declared = (
                effect.template_id in {"summon_from_trash", "create_field_minions"}
                or effect.params.get("puts_targets_on_field")
                or effect.params.get("source_enters_field")
            )
            if not declared:
                missing.append(card.id)
    assert len(checked) >= 10
    assert not missing, f"field entry effects missing capacity declarations: {missing}"
