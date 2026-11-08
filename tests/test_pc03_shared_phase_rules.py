import pytest

from zz.effects import EffectSpec, EffectTiming, effect_target_filter
from zz.engine import IllegalActionError
from zz.enums import AreaType, CardType, Color, Step
from zz.model import Action, Card, CardInstance
from zz.web.session import GameSession


def test_declared_multiple_colors_and_types_filter_prompt():
    session = GameSession(seed=18, mode="god")
    engine = session.engine
    owner = engine.state.players[0]
    owner.deck.clear()
    source = CardInstance(Card("src", "src", "src", CardType.F_MINION), owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    def item(name, kind, color):
        card = Card(name, name, name, kind, printed_color=color, race_jp="エヴォーカー")
        ci = CardInstance(card, owner, iid=engine.state.allocate_iid(), area=AreaType.DECK)
        owner.deck.append(ci)
        return ci
    good = item("green", CardType.B_MINION, Color.GREEN)
    item("red", CardType.B_MINION, Color.RED)
    item("magic", CardType.MAGIC, Color.GREEN)
    effect = EffectSpec(EffectTiming.ON_SUMMON, lambda *_: None, target_kind="deck_card", params={"colors_any": [Color.GREEN, Color.COLORLESS], "card_types": [CardType.B_MINION, CardType.F_MINION]})
    session._prompt_effect_target(owner, "deck_card", None, 1, effect=effect, source_ci=source)
    assert [o["cardIid"] for o in session.prompt["options"] if o.get("cardIid")] == [good.iid]
    matcher = effect_target_filter(engine, effect, source=source)
    assert [ci for ci in owner.deck if matcher(ci)] == [good]


def test_flash_condition_and_battle_lock_are_checked_before_payment():
    session = GameSession(seed=19, mode="god")
    engine = session.engine
    owner = engine.state.active
    engine.state.step = Step.MAIN
    spell = Card("conditional", "conditional", "conditional", CardType.MAGIC, cost={})
    spell.main_timing_ok = True
    spell.flash_timing_ok = True
    spell.flash_timing_condition = lambda player, state, source: bool(player.field)
    ci = CardInstance(spell, owner, iid=engine.state.allocate_iid(), area=AreaType.HAND)
    owner.hand[:] = [ci]
    owner.field.clear()
    action = Action("play_card", {"iid": ci.iid})
    assert action not in engine.legal_flash_actions(owner)
    with pytest.raises(IllegalActionError):
        engine.apply_flash_action(owner, action)
    assert ci in owner.hand
    owner.field.append(CardInstance(Card("body", "body", "body", CardType.F_MINION), owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD))
    assert action in engine.legal_flash_actions(owner)
    owner.flags.add("battle:cannot_activate_magic")
    assert action not in engine.legal_flash_actions(owner)
    assert action not in engine.legal_actions()
    with pytest.raises(IllegalActionError):
        engine.apply_flash_action(owner, action)
    with pytest.raises(IllegalActionError):
        engine.play_card(ci)
    assert ci in owner.hand


def test_direct_refresh_obeys_field_restriction():
    session = GameSession(seed=20, mode="god")
    engine = session.engine
    owner = engine.state.players[0]
    restrictor = Card("lock", "lock", "lock", CardType.F_MINION)
    restrictor.action_restriction = lambda source, target, action, state: action == "refresh" and target.area is AreaType.BASE
    source = CardInstance(restrictor, owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    mana = CardInstance(Card("mana", "mana", "mana", CardType.B_MINION), owner, iid=engine.state.allocate_iid(), area=AreaType.BASE, rested=True)
    owner.field.append(source)
    owner.base.append(mana)
    assert not engine.refresh_target(mana)
    assert mana.rested
    owner.field.remove(source)
    assert engine.refresh_target(mana)
    assert not mana.rested


def test_base_destroy_and_deck_discard_lifecycle():
    session = GameSession(seed=21, mode="god")
    engine = session.engine
    owner = engine.state.players[0]
    owner.deck.clear()
    mana = CardInstance(Card("spell-mana", "mana", "mana", CardType.MAGIC), owner, iid=engine.state.allocate_iid(), area=AreaType.BASE)
    owner.base.append(mana)
    engine.destroy_target(mana, None)
    assert mana in owner.trash and mana not in owner.base
    token = engine.place_generated_colorless_mana(owner)
    engine.destroy_target(token, None)
    assert token not in owner.base and token not in owner.trash and token not in owner.removed
    source = CardInstance(Card("source", "source", "source", CardType.F_MINION), owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(source)
    cards = [CardInstance(Card(str(n), str(n), str(n), CardType.F_MINION, cost={Color.COLORLESS: n}), owner, iid=engine.state.allocate_iid(), area=AreaType.DECK) for n in (2, 6, 4)]
    owner.deck.extend(cards)
    discarded = engine.discard_deck_matching(owner, source=source, predicate=lambda ci: sum(ci.card.cost.values()) <= 5, shuffle=True)
    assert discarded == [cards[0], cards[2]]
    assert owner.deck == [cards[1]]
    assert all(ci in owner.trash for ci in discarded)


def test_pc03_declared_continuous_effects_follow_source_and_turn():
    from zz.cards import CARD_REGISTRY
    from zz.enums import Keyword
    session = GameSession(seed=22, mode="god")
    engine = session.engine
    owner, opponent = engine.state.players
    owner.field.clear()
    opponent.field.clear()
    protect = CardInstance(CARD_REGISTRY["blue_02_01_03_00"], owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(protect)
    target_card = Card("target", "target", "target", CardType.F_MINION, cost={Color.COLORLESS: 3}, cost_aura=lambda *_: -2)
    target = CardInstance(target_card, opponent, iid=engine.state.allocate_iid(), area=AreaType.HAND)
    opponent.hand.append(target)
    assert engine.effective_cost(opponent, target) == {Color.COLORLESS: 3}
    owner.field.remove(protect)
    assert sum(engine.effective_cost(opponent, target).values()) == 1
    aura = CardInstance(CARD_REGISTRY["blue_02_01_03_02"], owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(aura)
    ally = CardInstance(Card("sea", "sea", "sea", CardType.F_MINION, race_jp="シーワーム"), owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(ally)
    engine.state.active_idx = 0
    assert engine.has_keyword(ally, Keyword.UNBLOCKABLE)
    engine.state.active_idx = 1
    assert not engine.has_keyword(ally, Keyword.UNBLOCKABLE)
    engine.state.active_idx = 0
    owner.field.remove(aura)
    assert not engine.has_keyword(ally, Keyword.UNBLOCKABLE)


def _transform_setup(source_id, count=10):
    from zz.cards import CARD_REGISTRY
    session = GameSession(seed=23, mode="god")
    engine = session.engine
    owner = engine.state.players[0]
    session.prompt = None
    owner.base.clear()
    owner.field.clear()
    owner.trash.clear()
    source = CardInstance(CARD_REGISTRY[source_id], owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(source)
    for _ in range(count):
        engine.place_generated_colorless_mana(owner)
    return session, engine, owner, source


def _choose_first(session):
    prompt = session.prompt
    result = session.choose(prompt["id"], prompt["options"][0]["id"])
    assert result["error"] is None


@pytest.mark.parametrize("initial,choices", [(9, 1), (10, 2)])
def test_green_two_mana_each_waits_for_capacity_choice(initial, choices):
    from zz.cards import CARD_REGISTRY
    session, engine, owner, source = _transform_setup("green_04_01_03_00", initial)
    engine.transform_card(source, CARD_REGISTRY["green_04_01_03_01"])
    for index in range(choices):
        assert session.prompt["choiceKind"] == "ally_base"
        assert session.prompt["playerSide"] == "P1"
        assert len(owner.base) == 10
        assert sum(ci.mana_color_override is Color.GREEN for ci in owner.base) == (1 if initial == 9 else index)
        _choose_first(session)
    assert len(owner.base) == 10
    assert sum(ci.mana_color_override is Color.GREEN for ci in owner.base) == 2


def test_purple_target_then_owner_replacement_then_mana():
    from zz.cards import CARD_REGISTRY
    session, engine, owner, source = _transform_setup("purple_04_01_03_00")
    skeleton = CardInstance(Card("skeleton", "skeleton", "skeleton", CardType.F_MINION, race_jp="スケルトン", cost={Color.COLORLESS: 3}), owner, iid=engine.state.allocate_iid(), area=AreaType.TRASH)
    owner.trash.append(skeleton)
    engine.transform_card(source, CARD_REGISTRY["purple_04_01_03_01"])
    assert session.prompt["choiceKind"] == "trash_field_minion"
    assert skeleton in owner.trash and len(owner.base) == 10
    _choose_first(session)
    assert skeleton in owner.field and session.prompt["choiceKind"] == "ally_base"
    assert len(owner.base) == 10 and not any(ci.mana_color_override is Color.PURPLE for ci in owner.base)
    _choose_first(session)
    assert len(owner.base) == 10 and sum(ci.mana_color_override is Color.PURPLE for ci in owner.base) == 1


@pytest.mark.parametrize("source_id,target_id,color", [
    ("blue_03_01_03_00", "blue_03_01_03_01", Color.BLUE),
    ("white_04_01_03_02", "white_04_01_03_03", Color.WHITE),
    ("yellow_03_01_03_02", "yellow_03_01_03_03", Color.YELLOW),
    ("red_04_01_03_02", "red_04_01_03_03", Color.RED),
])
def test_other_transforms_wait_for_owner_mana_replacement(source_id, target_id, color):
    from zz.cards import CARD_REGISTRY
    session, engine, owner, source = _transform_setup(source_id)
    opponent = engine.state.players[1]
    opponent.field.clear()
    if color is Color.RED:
        target = CardInstance(Card("enemy", "enemy", "enemy", CardType.F_MINION), opponent, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
        opponent.field.append(target)
    engine.transform_card(source, CARD_REGISTRY[target_id])
    if color is Color.RED:
        assert session.prompt["choiceKind"] == "enemy_minion"
        _choose_first(session)
    assert session.prompt["choiceKind"] == "ally_base"
    assert session.prompt["playerSide"] == "P1"
    assert len(owner.base) == 10 and not any(ci.mana_color_override is color for ci in owner.base)
    _choose_first(session)
    assert len(owner.base) == 10 and sum(ci.mana_color_override is color for ci in owner.base) == 1


def test_player_opponent_trash_and_token_candidates_use_declared_contract():
    session = GameSession(seed=24, mode="god")
    engine = session.engine
    owner, opponent = engine.state.players
    owner.field.clear()
    opponent.trash.clear()
    source = CardInstance(Card("source2", "source2", "source2", CardType.F_MINION), owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    token = CardInstance(Card("token2", "token2", "token2", CardType.F_MINION, is_token=True), owner, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.extend([source, token])
    effect = EffectSpec(EffectTiming.ON_SUMMON, lambda *_: None, target_kind="ally_minion", params={"requires_token": True})
    session._prompt_effect_target(owner, "ally_minion", None, 1, effect=effect, source_ci=source)
    assert [o["cardIid"] for o in session.prompt["options"] if o.get("cardIid")] == [token.iid]
    session._prompt_effect_target(owner, "any_player", None, 1, source_ci=source)
    assert [o["ownerSide"] for o in session.prompt["options"]] == ["P1", "P2"]
    assert engine._eligible_targets(owner, "any_player") == [owner, opponent]
    good = CardInstance(Card("good", "good", "good", CardType.F_MINION), opponent, iid=engine.state.allocate_iid(), area=AreaType.TRASH)
    excluded = CardInstance(Card("excluded", "excluded", "excluded", CardType.F_MINION), opponent, iid=engine.state.allocate_iid(), area=AreaType.TRASH)
    opponent.trash.extend([good, excluded])
    effect = EffectSpec(EffectTiming.ON_DESTROY, lambda *_: None, target_kind="enemy_trash_field_minion", params={"exclude_card_id": "excluded"})
    session._prompt_effect_target(owner, "enemy_trash_field_minion", None, 1, effect=effect, source_ci=source)
    assert [o["cardIid"] for o in session.prompt["options"] if o.get("cardIid")] == [good.iid]


def test_force_lock_survives_clone_and_blocks_refresh():
    import copy
    session = GameSession(seed=25, mode="god")
    engine = session.engine
    force = engine.state.players[1].forces[0]
    engine.rest_target(force)
    engine.prevent_activation_until_next_standby_end(force)
    assert not engine.refresh_target(force)
    cloned = copy.deepcopy(engine.state)
    assert cloned.players[1].forces[0].flags == force.flags
    assert force.rested


def test_mixed_force_target_keeps_force_but_filters_expensive_minion():
    session = GameSession(seed=26, mode="god")
    engine = session.engine
    owner, opponent = engine.state.players
    opponent.field.clear()
    cheap = CardInstance(Card("cheap", "cheap", "cheap", CardType.F_MINION, cost={Color.COLORLESS: 3}), opponent, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    expensive = CardInstance(Card("expensive", "expensive", "expensive", CardType.F_MINION, cost={Color.COLORLESS: 4}), opponent, iid=engine.state.allocate_iid(), area=AreaType.FIELD)
    opponent.field.extend([cheap, expensive])
    effect = EffectSpec(EffectTiming.ON_SUMMON, lambda *_: None, target_kind="enemy_minion_or_force", params={"max_cost": 3})
    session._prompt_effect_target(owner, "enemy_minion_or_force", None, 1, effect=effect)
    opts = session.prompt["options"]
    assert any(o.get("cardIid") == cheap.iid for o in opts)
    assert not any(o.get("cardIid") == expensive.iid for o in opts)
    assert sum(o.get("targetKind") == "force" for o in opts) == len([f for f in opponent.forces if not f.destroyed])


def test_deck_banish_preserves_owner_and_rejects_wrong_zone():
    session = GameSession(seed=27, mode="god")
    engine = session.engine
    owner, opponent = engine.state.players
    opponent.deck.clear()
    source = CardInstance(Card("spell2", "spell2", "spell2", CardType.MAGIC), owner, iid=engine.state.allocate_iid(), area=AreaType.RESOLVING)
    card = CardInstance(Card("deck2", "deck2", "deck2", CardType.F_MINION), opponent, iid=engine.state.allocate_iid(), area=AreaType.DECK)
    opponent.deck.append(card)
    assert engine.banish_from_deck(opponent, [card], source=source, effect_controller=owner) == [card]
    assert card.owner is opponent and card in opponent.removed and card not in opponent.deck
    assert any(e.get("card") is card and e.get("from") is AreaType.DECK and e.get("to") is AreaType.REMOVED for e in engine.zone_move_events)
    with pytest.raises(IllegalActionError):
        engine.banish_from_deck(opponent, [card], source=source, effect_controller=owner)
