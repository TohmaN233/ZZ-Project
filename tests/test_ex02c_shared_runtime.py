from __future__ import annotations

import copy

import pytest

import zz.ex02c  # noqa: F401 - register EX02C cards
from tests.test_public_base_rules import lab as _project_lab
from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.engine import IllegalActionError
from zz.enums import AreaType, CardType, Color, Keyword, Step
from zz.model import Card, CardInstance, Context
from zz.web.debug_tools import add_debug_card_to_zone


def _lab(*args, **kwargs):
    session, owner = _project_lab(*args, **kwargs)
    for player in session.engine.state.players:
        player._test_engine = session.engine
    session.engine.defer_trigger_choice = None
    session.engine.defer_source_effect_choice = None
    return session, owner


def _interactive_lab(*args, **kwargs):
    session, owner = _project_lab(*args, **kwargs)
    for player in session.engine.state.players:
        player._test_engine = session.engine
    return session, owner


def _instance(card: Card, owner, *, area: AreaType, rested: bool = False) -> CardInstance:
    instance = CardInstance(card, owner, iid=owner._test_engine.state.allocate_iid(), area=area, rested=rested)
    getattr(owner, area.value).append(instance)
    return instance


def test_switch_replays_only_field_host_and_sets_switch_source():
    session, owner = _lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    state = engine.state
    host = next(instance for instance in owner.field if instance.card.id == "green_08_02_02c_00")
    transformed = copy.deepcopy(CARD_REGISTRY["green_08_02_02c_01"])
    engine.transform_card(host, transformed)

    opponent = state.players[1]
    target = _instance(Card("switch-target", "target", "target", CardType.F_MINION, bp=100), opponent,
                       area=AreaType.FIELD, rested=True)
    switch_sources = []
    host.card.effects.append(EffectSpec(
        timing=EffectTiming.ON_DESTROY,
        fn=lambda _source, _state, ctx: switch_sources.append(ctx.switch_source),
        params={"ex02c_switch_races": ["黒の剣士"]},
        active_areas=(AreaType.FIELD,),
    ))
    summoned = _instance(CARD_REGISTRY["green_04_02_02c_00"], owner, area=AreaType.FIELD)
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=summoned))
    engine.triggers.resolve_all()

    assert host.area is AreaType.FIELD and host in owner.field
    assert switch_sources == [host]
    assert "skip_refresh:P2" in target.flags

    opponent_summon = _instance(CARD_REGISTRY["green_04_02_02c_00"], opponent, area=AreaType.FIELD)
    engine.triggers.emit(
        EffectTiming.ON_SUMMON,
        Context(controller=opponent, source=opponent_summon),
    )
    engine.triggers.resolve_all()
    assert switch_sources == [host]


def test_stacia_selection_protection_tracks_active_sources_and_current_targets():
    session, owner = _interactive_lab("colorless_05_02_02c_03", zone="field", base_count=4)
    engine = session.engine
    state = engine.state
    stacia = next(card for card in owner.field if card.card.id == "colorless_05_02_02c_03")
    opponent = state.players[1]
    opponent_source = _instance(
        Card("stacia-opponent-source", "opponent source", "", CardType.F_MINION),
        opponent,
        area=AreaType.FIELD,
    )
    swordsman_card = Card(
        "stacia-swordsman", "swordsman", "swordsman", CardType.F_MINION,
        bp=100, race_jp="黒の剣士|ソード",
    )
    swordsman = _instance(swordsman_card, owner, area=AreaType.FIELD)

    session._clear_prompt()
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=stacia))
    engine.triggers.resolve_all()

    assert not engine._opponent_effect_target_protected(stacia)
    assert engine._opponent_effect_target_protected(swordsman)
    state.turn += 1
    assert not engine._opponent_effect_target_protected(swordsman)
    state.turn -= 1
    assert engine._opponent_effect_target_protected(swordsman)

    entered_after_activation = _instance(
        Card("late-stacia-swordsman", "late swordsman", "", CardType.F_MINION,
             bp=100, race_jp="黒の剣士"),
        owner,
        area=AreaType.FIELD,
    )
    base_swordsman = _instance(
        Card("base-stacia-swordsman", "base swordsman", "", CardType.B_MINION,
             race_jp="黒の剣士"),
        owner,
        area=AreaType.BASE,
    )
    assert engine._opponent_effect_target_protected(entered_after_activation)
    assert engine._opponent_effect_target_protected(base_swordsman)

    second_stacia = _instance(stacia.card, owner, area=AreaType.FIELD)
    engine.triggers.emit(
        EffectTiming.ON_SUMMON,
        Context(controller=owner, source=second_stacia),
    )
    engine.triggers.resolve_all()

    assert engine.return_to_hand(stacia, source=opponent_source)
    assert not engine._opponent_effect_target_protected(stacia)
    assert engine._opponent_effect_target_protected(swordsman)
    assert engine.return_to_hand(second_stacia, source=opponent_source)
    assert not engine._opponent_effect_target_protected(swordsman)


def test_native_destroy_effect_can_resolve_in_trash_but_switch_cannot_replay_it():
    session, owner = _lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    host = next(instance for instance in owner.field if instance.card.id == "green_08_02_02c_00")
    engine.transform_card(host, copy.deepcopy(CARD_REGISTRY["green_08_02_02c_01"]))
    opponent = engine.state.players[1]
    target = _instance(Card("trash-switch-target", "target", "target", CardType.F_MINION, bp=100), opponent,
                       area=AreaType.FIELD, rested=True)
    attacker = _instance(Card("trash-switch-attacker", "attacker", "attacker", CardType.F_MINION, bp=100), opponent,
                         area=AreaType.FIELD)

    engine._destroy(host, source=attacker)
    assert host.area is AreaType.TRASH
    assert "skip_refresh:P2" in target.flags  # Native ON_DESTROY resolved from Trash.
    target.flags.discard("skip_refresh:P2")

    summoned = _instance(CARD_REGISTRY["green_04_02_02c_00"], owner, area=AreaType.FIELD)
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=summoned))
    engine.triggers.resolve_all()
    assert "skip_refresh:P2" not in target.flags


def test_kirito_required_switch_search_rejects_skip_and_empty_target_list():
    session, owner = _interactive_lab("colorless_06_02_cp_00", zone="field", base_count=4)
    add_debug_card_to_zone(session, "colorless_00_01_02c_00", side="P1", zone="deck")
    source_iid = add_debug_card_to_zone(
        session, "colorless_05_02_02c_03", side="P1", zone="hand"
    )["added"]["iid"]
    source = next(card for card in owner.hand if card.iid == source_iid)

    session._clear_prompt()
    session._prompt_main_action()
    play_option_id = next(
        option_id for option_id, action in session._options.items()
        if getattr(action, "kind", None) == "play_card"
        and action.payload.get("iid") == source.iid
    )
    assert session.choose(session.prompt["id"], play_option_id)["error"] is None
    prompt = session.prompt
    assert prompt["kind"] == "effect_target"
    assert prompt["choiceKind"] == "deck_base_minion"
    assert all(option.get("kind") != "effect_target_skip" for option in prompt["options"])

    before = (
        tuple(card.iid for card in owner.hand),
        tuple(card.iid for card in owner.deck),
        tuple(card.iid for card in owner.field),
    )
    rejected_skip = session.choose(prompt["id"], "none")
    target_option = next(option for option in prompt["options"] if option.get("cardIid"))
    rejected_empty = session.choose(
        prompt["id"], target_option["id"], {"selectedOptionIds": []}
    )
    after = (
        tuple(card.iid for card in owner.hand),
        tuple(card.iid for card in owner.deck),
        tuple(card.iid for card in owner.field),
    )
    assert rejected_skip["error"]["code"] == "illegal_choice"
    assert rejected_empty["error"]["code"] == "illegal_choice"
    assert before == after
    assert session.prompt["id"] == prompt["id"]


def test_researcher_activation_lock_survives_turn_start_and_clears_after_reawaken():
    session, owner = _lab("colorless_03_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    state = engine.state
    opponent = state.players[1]
    researcher = next(instance for instance in owner.field if instance.card.id == "colorless_03_02_02c_00")
    reawakening_minion = _instance(
        Card("reawakening-minion", "reawakening", "reawakening", CardType.F_MINION,
             bp=100, keywords=[Keyword.REAWAKEN]),
        opponent,
        area=AreaType.FIELD,
        rested=True,
    )
    _instance(Card("opponent-turn-draw", "draw", "draw", CardType.B_MINION), opponent,
              area=AreaType.DECK)
    _instance(Card("owner-turn-draw", "draw", "draw", CardType.B_MINION), owner,
              area=AreaType.DECK)
    destroyer = _instance(
        Card("researcher-destroyer", "destroyer", "destroyer", CardType.F_MINION, bp=100),
        opponent,
        area=AreaType.FIELD,
    )
    state.turn = 2

    engine._destroy(researcher, source=destroyer)

    lock_flag = "turn:zz03c_minions_cannot_activate:2:P2"
    assert researcher.area is AreaType.TRASH
    assert lock_flag in opponent.flags
    state.active_idx = 1
    engine.begin_turn()
    assert lock_flag in opponent.flags
    assert reawakening_minion.rested

    engine.end_turn()
    assert reawakening_minion.rested
    assert lock_flag not in opponent.flags


def test_on_rest_batches_only_minions_that_became_rested_during_callback():
    session, owner = _lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    opponent = engine.state.players[1]
    batches = []
    listener = _instance(Card(
        "rest-listener", "listener", "listener", CardType.F_MINION, bp=100,
        effects=[EffectSpec(
            EffectTiming.ON_REST,
            lambda _source, _state, ctx: batches.append(tuple(ctx.target)),
            active_areas=(AreaType.FIELD,),
        )],
    ), owner, area=AreaType.FIELD)
    first = _instance(Card("rest-first", "first", "first", CardType.F_MINION, bp=100), opponent,
                      area=AreaType.FIELD)
    already_rested = _instance(Card("rest-existing", "existing", "existing", CardType.F_MINION, bp=100), opponent,
                               area=AreaType.FIELD, rested=True)
    second = _instance(Card("rest-second", "second", "second", CardType.B_MINION, bp=100), opponent,
                       area=AreaType.BASE)

    def rest_batch(_source, state, _ctx):
        state.engine.rest_target(first)
        state.engine.rest_target(first)
        state.engine.rest_target(already_rested)
        state.engine.rest_target(second)

    engine._run_effect_callback(rest_batch, listener, engine.state, Context(controller=owner, source=listener))

    assert batches == [(first, second)]


def test_return_to_hand_emits_event_and_sets_opponent_turn_flag_until_turn_end():
    session, owner = _lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    opponent = engine.state.players[1]
    returned = _instance(Card("return-target", "target", "target", CardType.F_MINION, bp=100), opponent,
                         area=AreaType.FIELD)
    observations = []
    host = _instance(Card(
        "return-listener", "listener", "listener", CardType.F_MINION, bp=100,
        effects=[EffectSpec(
            EffectTiming.ON_RETURN_TO_HAND,
            lambda _source, _state, ctx: observations.append((ctx.target, ctx.target.area)),
            active_areas=(AreaType.FIELD,),
        )],
    ), owner, area=AreaType.FIELD)

    assert engine.return_to_hand(returned, source=host)
    assert observations == [(returned, AreaType.HAND)]
    assert "turn:ex02c_opponent_minion_returned_to_hand" in owner.flags
    engine._fire_turn_end_hooks()
    assert "turn:ex02c_opponent_minion_returned_to_hand" not in owner.flags


def test_bless_callbacks_maximum_and_cost_mapping_are_validated():
    session, owner = _lab("red_02_03_02c_00", zone="hand", base_count=4)
    engine = session.engine
    magic = next(instance for instance in owner.hand if instance.card.id == "red_02_03_02c_00")
    magic.card = copy.deepcopy(magic.card)
    swordsman = _instance(Card("swordsman", "swordsman", "swordsman", CardType.F_MINION,
                               race_jp="黒の剣士"), owner, area=AreaType.FIELD)
    assert engine.effective_cost(owner, magic) == {}
    magic.card.cost_aura = lambda _source, _target, _state: {"RED": 1}
    with pytest.raises(TypeError, match="non-Color key"):
        engine.effective_cost(owner, magic)
    del swordsman

    mana = owner.base[0]
    mana.card = Card(
        "test-bless-mana", "mana", "mana", CardType.B_MINION,
        keywords=[Keyword.BLESS],
        bless_condition=lambda _mana, target, _state: target.card.bp == 500,
    )
    target_card = Card("test-bless-target", "target", "target", CardType.F_MINION, bp=500)
    target_card.max_blessings = 2
    target = _instance(target_card, owner, area=AreaType.FIELD)
    old_blessing = CardInstance(Card("old-blessing", "old", "old", CardType.B_MINION), owner,
                                area=AreaType.BLESSING)
    target.blessings.append(old_blessing)
    assert engine.can_bless(mana, target)
    target.card.bp = 400
    assert not engine.can_bless(mana, target)
    target.card.bp = 500
    target.blessings.append(old_blessing)
    assert not engine.can_bless(mana, target)


@pytest.mark.parametrize(
    ("mana_id", "cost", "race", "allowed"),
    [
        ("colorless_00_01_02c_00", 4, "黒の剣士|ソード", True),
        ("colorless_00_01_02c_00", 4, "ソード", False),
        ("green_00_01_02c_01", 4, "ソード", True),
        ("green_00_01_02c_01", 3, "ソード", False),
        ("green_00_01_02c_02", 4, "ソード", True),
        ("green_00_01_02c_02", 4, "黒の剣士", False),
        ("red_00_01_02c_02", 4, "ソード", True),
        ("red_00_01_02c_02", 4, "黒の剣士", False),
    ],
)
def test_ex02c_bless_conditions_use_their_race_and_cost_limits(mana_id, cost, race, allowed):
    session, owner = _lab(mana_id, zone="base", base_count=4)
    mana = next(instance for instance in owner.base if instance.card.id == mana_id)
    target = _instance(
        Card(
            f"target-{mana_id}-{cost}-{race}", "target", "target", CardType.F_MINION,
            cost={Color.GREEN: cost}, race_jp=race,
        ),
        owner,
        area=AreaType.FIELD,
    )

    assert session.engine.can_bless(mana, target) is allowed


def test_battle_destruction_carries_participants_and_honors_battle_protection():
    session, owner = _lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    opponent = engine.state.players[1]
    participants = []
    target_card = Card(
        "battle-protected", "target", "target", CardType.F_MINION, bp=100,
        effect_protection=lambda protector, target, operation, state: (
            protector is target and operation == "battle" and state.active is target.owner
        ),
        effects=[EffectSpec(
            EffectTiming.ON_DESTROY,
            lambda _source, _state, ctx: participants.append(ctx.battle_participants),
            condition=lambda source, _state, ctx: ctx.target is source,
            active_areas=(AreaType.TRASH,),
        )],
    )
    target = _instance(target_card, owner, area=AreaType.FIELD)
    attacker = _instance(Card("battle-attacker", "attacker", "attacker", CardType.F_MINION, bp=100), opponent,
                         area=AreaType.FIELD)

    engine._destroy(target, source=attacker, operation="battle", battle_participants=(attacker, target))
    assert target in owner.field and not participants
    target.card.effect_protection = None
    engine._destroy(target, source=attacker, operation="battle", battle_participants=(attacker, target))
    assert target in owner.trash
    assert participants == [(attacker, target)]
    assert Context(controller=owner).battle_participants is None


def test_action_restrictions_remove_attack_block_and_move_eligibility():
    session, owner = _lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    opponent = engine.state.players[1]
    restriction = lambda _source, target, action, _state: (
        target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and target.card.bp <= 1000
        and action in {"attack", "block", "move"}
    )
    _instance(Card("admin", "admin", "admin", CardType.F_MINION, action_restriction=restriction),
              opponent, area=AreaType.FIELD)
    attacker = _instance(Card("low-attacker", "attacker", "attacker", CardType.F_MINION, bp=500),
                         owner, area=AreaType.FIELD)
    blocker = _instance(Card("low-blocker", "blocker", "blocker", CardType.F_MINION, bp=500),
                        opponent, area=AreaType.FIELD)
    engine.state.turn = 2
    engine.state.present_at_turn_start.add(attacker.iid)

    assert engine._action_restricted(attacker, "attack")
    assert not engine.can_attack(attacker)
    assert blocker not in engine.legal_blockers(attacker)
    assert engine._movement_locked(attacker)
    from zz.web.serialize import serialize_card

    public_card = serialize_card(engine, attacker, session.asset_index)
    assert public_card["actionRestrictions"] == ["attack", "block", "move"]


def test_dp_set_zero_and_blessing_mana_banishment_have_explicit_boundaries():
    session, owner = _lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    minion = _instance(
        Card("dp-set-base", "base", "base", CardType.B_MINION, dp=3),
        owner,
        area=AreaType.BASE,
    )
    engine.modify_stat(minion, dp_set=0, duration="turn")
    assert engine.effective_dp(minion) == 0
    with pytest.raises(ValueError, match="non-negative integer"):
        engine.modify_stat(minion, dp_set=-1)
    with pytest.raises(ValueError, match="non-negative integer"):
        engine.modify_stat(minion, dp_set=True)

    host = _instance(
        Card("bless-host", "host", "host", CardType.F_MINION, max_blessings=2),
        owner,
        area=AreaType.FIELD,
    )
    mana = CardInstance(
        Card("attached-bless", "mana", "mana", CardType.B_MINION),
        owner,
        iid=engine.state.allocate_iid(),
        area=AreaType.BLESSING,
    )
    host.blessings.append(mana)
    engine.banish_blessing_mana(host, mana, source=host)
    assert mana.area is AreaType.REMOVED
    assert mana in owner.removed and mana not in host.blessings
    assert engine.zone_move_events[-1] == {
        "card": mana,
        "from": AreaType.BLESSING,
        "to": AreaType.REMOVED,
    }

    unattached = CardInstance(
        Card("unattached-bless", "mana", "mana", CardType.B_MINION),
        owner,
        iid=engine.state.allocate_iid(),
        area=AreaType.BLESSING,
    )
    with pytest.raises(IllegalActionError, match="not attached"):
        engine.banish_blessing_mana(host, unattached, source=host)


def test_base_minion_from_hand_can_enter_base_without_on_place_base_trigger():
    session, owner = _lab("green_03_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    placement_events = []
    listener = _instance(
        Card(
            "placement-listener",
            "listener",
            "listener",
            CardType.F_MINION,
            effects=[EffectSpec(
                EffectTiming.ON_PLACE_BASE,
                lambda _source, _state, ctx: placement_events.append(ctx.source),
                active_areas=(AreaType.FIELD,),
            )],
        ),
        owner,
        area=AreaType.FIELD,
    )
    hand_minion = _instance(
        Card("hand-base-minion", "item", "item", CardType.B_MINION, race_jp="アイテム"),
        owner,
        area=AreaType.HAND,
    )
    deck_minion = _instance(
        Card("deck-base-minion", "deck", "deck", CardType.B_MINION, race_jp="アイテム"),
        owner,
        area=AreaType.DECK,
    )

    engine.put_base_minion_from_hand(owner, hand_minion)
    assert hand_minion.area is AreaType.BASE and hand_minion in owner.base
    assert engine.zone_move_events[-1] == {
        "card": hand_minion,
        "from": AreaType.HAND,
        "to": AreaType.BASE,
    }
    assert not placement_events
    assert listener in owner.field

    engine.place_from_deck_to_base(owner, deck_minion)
    assert deck_minion.area is AreaType.BASE and deck_minion in owner.base
    assert engine.zone_move_events[-1] == {
        "card": deck_minion,
        "from": AreaType.DECK,
        "to": AreaType.BASE,
    }


def test_red_kirito_grants_rested_bless_for_its_turn_only():
    session, owner = _lab("red_07_02_02c_02", zone="field", base_count=4)
    engine = session.engine
    engine.state.step = Step.MAIN
    engine.state.players[0].movement_right_count = 1
    kirito = next(card for card in owner.field if card.card.id == "red_07_02_02c_02")
    mana = owner.base[0]
    mana.card = Card("rested-bless", "mana", "mana", CardType.B_MINION, keywords=[Keyword.BLESS])
    mana.rested = True
    host = _instance(
        Card(
            "rested-bless-host",
            "host",
            "host",
            CardType.F_MINION,
            bp=100,
            dp=1,
            max_blessings=2,
            can_bless_while_rested=True,
            ignore_bless_conditions=True,
        ),
        owner,
        area=AreaType.FIELD,
    )
    assert not engine.can_bless(mana, host)

    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=kirito))
    engine.triggers.resolve_all()
    assert "turn:pc02_ex02c_allow_rested_bless" in owner.flags
    assert engine.can_bless(mana, host)
    engine._fire_turn_end_hooks()
    assert "turn:pc02_ex02c_allow_rested_bless" not in owner.flags
    assert not engine.can_bless(mana, host)


def test_green_08_prompt_requires_one_enemy_target_per_own_green_minion():
    session, owner = _interactive_lab("green_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    source = next(card for card in owner.field if card.card.id == "green_08_02_02c_00")
    opponent = engine.state.players[1]
    allies = [
        _instance(
            Card(
                f"green-ally-{index}", "green", "green", CardType.F_MINION,
                bp=100, dp=1, printed_color=Color.GREEN,
            ),
            owner,
            area=AreaType.FIELD,
        )
        for index in range(2)
    ]
    enemies = [
        _instance(Card(f"green-target-{index}", "target", "target", CardType.F_MINION, bp=100, dp=1),
                  opponent, area=AreaType.FIELD)
        for index in range(4)
    ]
    session._clear_prompt()
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    engine.triggers.resolve_all()

    assert session.prompt is not None and session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "enemy_minion"
    assert session.prompt["requiredTargetCount"] == 3  # Source plus the two added Green Minions.
    assert session.prompt["minimumTargetCount"] == session.prompt["maximumTargetCount"] == 3
    option_ids = [option["id"] for option in session.prompt["options"][:3]]
    result = session.choose(session.prompt["id"], option_ids[0], {"selectedOptionIds": option_ids})
    assert result["error"] is None
    assert sum(target.rested for target in enemies) == 3
    assert all(not ally.rested for ally in allies)


def test_titania_draws_before_hand_choice_and_requires_black_swordsman_to_attack():
    session, owner = _interactive_lab("colorless_03_02_02c_03", zone="field", base_count=4)
    engine = session.engine
    source = next(card for card in owner.field if card.card.id == "colorless_03_02_02c_03")
    for index in range(3):
        _instance(
            Card(f"titania-draw-{index}", "draw", "draw", CardType.B_MINION),
            owner,
            area=AreaType.DECK,
        )
    engine.state.step = Step.MAIN
    engine.state.turn = 2
    source.rested = False
    source.summoning_sickness = False
    engine.state.present_at_turn_start.add(source.iid)
    assert not engine.can_attack(source)
    swordsman = _instance(
        Card("black-swordsman", "swordsman", "swordsman", CardType.F_MINION, bp=100, dp=1, race_jp="黒の剣士"),
        owner,
        area=AreaType.FIELD,
    )
    assert engine.can_attack(source)

    before_hand_count = len(owner.hand)
    assert owner.deck
    session._clear_prompt()
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    engine.triggers.resolve_all()
    assert len(owner.hand) == before_hand_count + 1
    drawn = owner.hand[-1]
    assert session.prompt is not None and session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "hand_card"
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == drawn.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    assert drawn in owner.deck and owner.deck[-1] is drawn
    assert any(
        event.get("type") == "zone_move"
        and event.get("fromArea") == AreaType.HAND.value
        and event.get("toArea") == AreaType.DECK.value
        and event.get("card", {}).get("iid") == drawn.iid
        for event in result["animationEvents"]
    )
    assert swordsman in owner.field


def test_conditional_high_cost_callback_prompts_for_custom_buff_target():
    session, owner = _interactive_lab("colorless_08_02_02c_01", zone="field", base_count=4)
    engine = session.engine
    source = next(card for card in owner.field if card.card.id == "colorless_08_02_02c_01")
    target = _instance(
        Card("buff-target", "target", "target", CardType.F_MINION, bp=100, dp=1, race_jp="黒の剣士"),
        owner,
        area=AreaType.FIELD,
    )
    session._clear_prompt()
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    engine.triggers.resolve_all()

    assert session.prompt is not None and session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "ally_minion"
    assert len(session.prompt["options"]) == 1
    result = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    assert result["error"] is None
    assert target.permanent_bp_mod == 300
    assert target.permanent_dp_mod == 1


@pytest.mark.parametrize(
    ("card_id", "target_card", "expected_area"),
    [
        ("colorless_07_02_02c_00", "colorless_07-target", AreaType.TRASH),
        ("colorless_06_02_cp_00", "colorless_06-target", AreaType.HAND),
    ],
)
def test_high_cost_custom_effects_prompt_for_their_declared_target(card_id, target_card, expected_area):
    session, owner = _interactive_lab(card_id, zone="field", base_count=4)
    engine = session.engine
    source = next(card for card in owner.field if card.card.id == card_id)
    if card_id == "colorless_07_02_02c_00":
        target = _instance(
            Card(target_card, "target", "target", CardType.F_MINION, bp=100, dp=1,
                 printed_color=Color.COLORLESS),
            engine.state.players[1],
            area=AreaType.FIELD,
        )
    else:
        target = _instance(
            Card(target_card, "item", "item", CardType.B_MINION, race_jp="アイテム"),
            owner,
            area=AreaType.DECK,
        )

    session._clear_prompt()
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    engine.triggers.resolve_all()
    assert session.prompt is not None and session.prompt["kind"] == "effect_target"
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    assert target.area is expected_area
    if expected_area is AreaType.HAND:
        assert target in owner.hand and target not in owner.deck
    else:
        assert target in engine.state.players[1].trash


def test_sword_golem_turn_end_prompt_includes_confirmed_equivalent_card():
    session, owner = _interactive_lab("colorless_08_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    engine.state.turn = 2
    source = next(card for card in owner.field if card.card.id == "colorless_08_02_02c_00")
    destroyer = _instance(
        Card("sword-golem-destroyer", "destroyer", "destroyer", CardType.F_MINION, bp=100, dp=1),
        engine.state.players[1],
        area=AreaType.FIELD,
    )
    alternate = _instance(
        Card("colorless_08_02_EX02_00", "ヒュージ・スタチュー", "", CardType.F_MINION, bp=800, dp=3),
        owner,
        area=AreaType.TRASH,
    )
    engine._destroy(source, source=destroyer)
    assert source.area is AreaType.TRASH

    session._clear_prompt()
    engine.triggers.emit(EffectTiming.TURN_END, Context(controller=owner))
    engine.triggers.resolve_all()
    assert session.prompt is not None and session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "trash_minion"
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == alternate.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    assert alternate in owner.hand and alternate not in owner.trash
    assert source.area is AreaType.TRASH and source in owner.trash


def test_sachi_granted_bp_bonus_survives_turn_end():
    session, owner = _lab("red_02_02_02c_00", zone="field", base_count=4)
    engine = session.engine
    sachi = next(card for card in owner.field if card.card.id == "red_02_02_02c_00")
    swordsman = _instance(
        Card("sachi-target", "swordsman", "swordsman", CardType.F_MINION, bp=100, dp=1, race_jp="黒の剣士"),
        owner,
        area=AreaType.FIELD,
    )
    attacker = _instance(
        Card("sachi-destroyer", "attacker", "attacker", CardType.F_MINION, bp=100),
        engine.state.players[1],
        area=AreaType.FIELD,
    )
    session.human_policy.queue_targets([swordsman])
    engine._destroy(sachi, source=attacker)
    assert sachi.area is AreaType.TRASH
    assert swordsman.permanent_bp_mod == 200
    engine._fire_turn_end_hooks()
    assert swordsman.permanent_bp_mod == 200
    assert engine.effective_bp(swordsman) == 300
