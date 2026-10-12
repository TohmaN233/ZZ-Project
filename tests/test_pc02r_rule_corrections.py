import random

import pytest

from zz.cards import CARD_REGISTRY
from zz.decks import AGUMA_RED_RECIPE  # register all official packs
from zz.engine import Engine, IllegalActionError
from zz.enums import AreaType, AttackTargetKind, CardType, Color, Side, Step
from zz.forces import F_CHIRON
from zz.model import Action, AttackTarget, Card, CardInstance, ForceInstance, GameState, Player


class FirstTarget:
    def choose_target(self, _engine, _kind, _minimum, maximum, eligible):
        return eligible[:maximum]


@pytest.fixture
def game():
    owner, opponent = Player("P1", Side.P1), Player("P2", Side.P2)
    engine = Engine(GameState(players=[owner, opponent], step=Step.MAIN), random.Random(5))
    engine.set_policies(FirstTarget(), FirstTarget())
    return engine, owner, opponent


def put(engine, owner, card, zone="field"):
    if isinstance(card, str):
        card = CARD_REGISTRY[card]
    ci = CardInstance(card=card, owner=owner, iid=engine.state.allocate_iid(), area=AreaType(zone))
    getattr(owner, zone).append(ci)
    return ci


def body(card_id="ordinary", *, token=False, color=Color.RED, bp=500):
    return Card(card_id, card_id, card_id, CardType.F_MINION, is_token=token, bp=bp, printed_color=color)


def test_iron_sprite_aura_requires_attached_bless_and_live_host(game):
    engine, owner, opponent = game
    mana = put(engine, owner, "red_00_01_02r_00", "base")
    host = put(engine, owner, body("host", token=True))
    token = put(engine, owner, body("token", token=True, color=Color.GREEN))
    ordinary = put(engine, owner, body())
    enemy = put(engine, opponent, body("enemy", token=True))
    assert engine.effective_bp(token) == 500  # Base alone grants nothing.
    owner.movement_right_count = 1
    engine.bless(mana, host)
    assert engine.effective_bp(token) == 700
    assert engine.effective_bp(host) == 700  # Printed Bless BP, no self aura.
    assert engine.effective_bp(ordinary) == 500
    assert engine.effective_bp(enemy) == 500
    engine.state.active_idx = 1
    assert engine.effective_bp(token) == 500
    engine.state.active_idx = 0
    assert engine.effective_bp(token) == 700
    engine.return_to_hand(host)
    assert mana.area is AreaType.BASE
    assert engine.effective_bp(token) == 500


def test_bless_aura_stops_on_detach_and_host_destruction(game):
    engine, owner, _ = game
    mana = put(engine, owner, "red_00_01_02r_00", "base")
    host = put(engine, owner, body("host"))
    token = put(engine, owner, body("token", token=True))
    owner.movement_right_count = 2
    engine.bless(mana, host)
    assert engine.effective_bp(token) == 700
    engine._finish_blessing_return(host, mana)
    assert engine.effective_bp(token) == 500
    mana.rested = False
    engine.bless(mana, host)
    assert engine.effective_bp(token) == 700
    engine.destroy_target(host, None)
    assert host in owner.trash
    assert engine.effective_bp(token) == 500


@pytest.mark.parametrize("attack_kind,refreshed", [(AttackTargetKind.PLAYER, True), (AttackTargetKind.FORCE, False)])
def test_volcanic_dragon_blocked_refresh_depends_on_original_target(game, attack_kind, refreshed):
    engine, owner, opponent = game
    attacker = put(engine, owner, "red_05_02_02r_00")
    blocker = put(engine, opponent, body("blocker", bp=100))
    attacker.rested = True
    force = ForceInstance(force=F_CHIRON, owner=opponent, life=3)
    opponent.forces.append(force)
    engine.resolve_attack_after_flash(attacker, AttackTarget(attack_kind, opponent if attack_kind is AttackTargetKind.PLAYER else force), blocker)
    assert attacker.area is AreaType.FIELD
    assert attacker.rested is not refreshed


def test_lava_slime_creates_real_copy_without_summon_recursion(game):
    engine, owner, _ = game
    original = put(engine, owner, "red_06_02_02r_00", "hand")
    engine.summon_from_hand(owner, original)
    assert len(owner.field) == 2
    clone = next(ci for ci in owner.field if ci is not original)
    assert clone.card is original.card
    assert clone.card.id == "red_06_02_02r_00"
    assert not clone.card.is_token
    assert clone.card.effects
    engine.return_to_hand(clone)
    assert clone in owner.hand
    engine.summon_from_hand(owner, clone)
    assert len(owner.field) == 3


def test_generated_real_card_uses_shared_full_field_replacement_and_trash(game):
    engine, owner, _ = game
    replaced = put(engine, owner, body("replace"))
    for index in range(3):
        put(engine, owner, body(f"existing{index}"))
    original = put(engine, owner, "red_06_02_02r_00", "hand")
    engine.summon_from_hand(owner, original)
    assert len(owner.field) == 5
    assert replaced in owner.trash
    clone = next(ci for ci in owner.field if ci.card.id == original.card.id and ci is not original)
    engine.destroy_target(clone, None)
    assert clone in owner.trash
    assert not CARD_REGISTRY[original.card.id].is_token


def test_fireball_total_cost_and_color_requirements_are_separate(game):
    engine, owner, opponent = game
    spell = put(engine, owner, "red_02_03_02r_01", "hand")
    enemy = put(engine, opponent, body("enemy", bp=500))
    enemy.bp_mod = -100
    red = put(engine, owner, Card("red-mana", "red", "red", CardType.B_MINION, mana_color=Color.RED), "base")
    assert spell.card.cost == {Color.RED: 1, Color.COLORLESS: 1}
    assert not engine._can_pay(owner, engine.effective_cost(owner, spell), spell)
    with pytest.raises(IllegalActionError, match="cannot pay"):
        engine.play_card(spell)
    blue = put(engine, owner, Card("blue-mana", "blue", "blue", CardType.B_MINION, mana_color=Color.BLUE), "base")
    assert engine._can_pay(owner, engine.effective_cost(owner, spell), spell)
    engine.play_card(spell, payment_base_iids=[red.iid, blue.iid])
    assert red.rested and blue.rested
    assert enemy in opponent.trash


def test_chiron_reduces_only_free_cost_and_stops_when_destroyed(game):
    engine, owner, _ = game
    spell = put(engine, owner, "red_02_03_02r_01", "hand")
    put(engine, owner, Card("red-mana", "red", "red", CardType.B_MINION, mana_color=Color.RED), "base")
    force = ForceInstance(force=F_CHIRON, owner=owner, life=3)
    owner.forces.append(force)
    engine.rebind_passive_modifiers()
    assert engine.effective_cost(owner, spell) == {Color.RED: 1}
    assert engine._can_pay(owner, engine.effective_cost(owner, spell), spell)
    force.destroyed = True
    assert engine.effective_cost(owner, spell) == {Color.RED: 1, Color.COLORLESS: 1}
    assert not engine._can_pay(owner, engine.effective_cost(owner, spell), spell)


@pytest.mark.parametrize("flash", [False, True])
def test_magic_can_be_cast_without_eligible_targets_and_still_pays(game, flash):
    engine, owner, opponent = game
    spell = put(engine, owner, "red_02_03_02r_01", "hand")
    enemy = put(engine, opponent, body("healthy", bp=500))
    mana = [put(engine, owner, Card(f"red-{i}", "red", "red", CardType.B_MINION, mana_color=Color.RED), "base") for i in range(2)]
    actions = engine.legal_flash_actions(owner) if flash else engine.legal_actions()
    assert any(a.kind == "play_card" and a.payload.get("iid") == spell.iid for a in actions)
    if flash:
        engine.apply_flash_action(owner, Action("play_card", {"iid": spell.iid}))
    else:
        engine.play_card(spell)
    assert spell in owner.trash and spell not in owner.hand
    assert all(ci.rested for ci in mana)
    assert enemy in opponent.field and enemy not in opponent.trash


@pytest.mark.parametrize("zone", ["hand", "deck", "base", "field", "trash", "removed"])
def test_debug_cannot_create_transformed_cards_in_any_zone(zone):
    from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_lab
    from zz.web.session import GameSession
    session = GameSession(seed=5, mode="god")
    card_id = "red_07_02_02r_01"
    with pytest.raises(ValueError, match="transformation-only"):
        add_debug_card_to_zone(session, card_id, side="P1", zone=zone)
    with pytest.raises(ValueError, match="transformation-only"):
        setup_debug_lab(session, card_id, zone=zone)


def test_legitimately_transformed_card_can_return_to_hand_and_be_played(game):
    engine, owner, opponent = game
    host = put(engine, owner, "red_07_02_02r_00")
    mana = put(engine, owner, "red_00_01_02_00", "base")
    enemy = put(engine, opponent, body("enemy", bp=1000))
    owner.movement_right_count = 1
    engine.bless(mana, host)
    assert host.card.id == "red_07_02_02r_01"
    assert not host.card.deck_buildable
    assert engine.return_to_hand(host)
    assert host in owner.hand and host.card.id == "red_07_02_02r_01"
    for i in range(7):
        put(engine, owner, Card(f"red-{i}", "red", "red", CardType.B_MINION, mana_color=Color.RED), "base")
    bp_before = engine.effective_bp(enemy)
    engine.play_card(host)
    assert host in owner.field and host.card.id == "red_07_02_02r_01"
    assert engine.effective_bp(enemy) == bp_before  # Summoning is not transforming again.
