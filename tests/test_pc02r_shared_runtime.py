from __future__ import annotations

import csv
import random
from functools import lru_cache

from zz.ai import PassOnlyPolicy
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.engine import FIELD_CAP, Engine
from zz.enums import AreaType, CardType, Color, Keyword, Side, Step
from zz.forces import Force
from zz.model import Action, Card, CardInstance, Context, ForceInstance, GameState, Player
from zz.pc01 import DEFAULT_CARD_TSV, _card_from_row
from zz.pc02 import _densai_summon, bless_condition_matches
from zz.pc02r_cards.blue_04_03_02r_00 import build_card as build_blue_multi_target
from zz.pc02r_cards.colorless_02_02_02r_01 import build_card as build_opponent_token_summoner
from zz.pc02r_cards.red_00_01_02r_00 import build_card as build_base_token_aura
from zz.web.session import GameSession


@lru_cache(maxsize=None)
def _row(card_id: str) -> dict[str, str]:
    with DEFAULT_CARD_TSV.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("image_id") == card_id:
                return row
    raise AssertionError(f"missing source row for {card_id}")


def _instance(
        owner: Player,
        card_id: str,
        *,
        card_type: CardType = CardType.F_MINION,
        color: Color = Color.COLORLESS,
        area: AreaType = AreaType.FIELD,
        bp: int = 100,
        is_token: bool = False,
        race_jp: str = "",
        card: Card | None = None,
) -> CardInstance:
    template = card or Card(
        id=card_id,
        name_jp=card_id,
        name_en=card_id,
        type=card_type,
        printed_color=color,
        bp=bp,
        is_token=is_token,
        race_jp=race_jp,
    )
    return CardInstance(card=template, owner=owner, area=area)


class _FirstTargetPolicy:
    def choose_target(self, _engine, _kind, _min_n, max_n, eligible):
        return eligible[:max_n]


def test_effect_tags_register_kago_and_pc02r_boosts_use_same_color_without_cost_floor() -> None:
    tagged = _card_from_row(_row("yellow_00_01_02r_00"))
    assert Keyword.KAGO in tagged.keywords

    cases = (
        ("purple_00_01_02r_00", Color.PURPLE),
        ("green_00_01_02r_00", Color.GREEN),
        ("white_00_01_02r_00", Color.WHITE),
    )
    for card_id, color in cases:
        mana = _instance(
            Player(name="P1", side=Side.P1),
            card_id,
            card_type=CardType.B_MINION,
            color=color,
            area=AreaType.BASE,
            card=_card_from_row(_row(card_id)),
        )
        matching_target = _instance(mana.owner, f"{card_id}-target", color=color)
        wrong_color_target = _instance(mana.owner, f"{card_id}-wrong", color=Color.RED)

        assert Keyword.KAGO in mana.card.keywords
        assert bless_condition_matches(mana, matching_target)
        assert not bless_condition_matches(mana, wrong_color_target)

    owner = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    engine = Engine(GameState(players=[owner, opponent]), rng=random.Random(901))
    engine.state.step = Step.MAIN
    mana = CardInstance(
        card=_card_from_row(_row("white_00_01_02r_00")),
        owner=owner,
        area=AreaType.BASE,
    )
    white_target = _instance(owner, "white_target", color=Color.WHITE)
    owner.base.append(mana)
    owner.field.append(white_target)
    owner.movement_right_count = 1
    assert engine.can_bless(mana, white_target)
    white_target.card.printed_color = Color.RED
    assert not engine.can_bless(mana, white_target)


def test_granted_bless_aura_is_reflected_in_serialized_field_token_stats_for_its_turn() -> None:
    session = GameSession(seed=901, mode="god")
    owner, opponent = session.engine.state.players
    session._clear_prompt()
    aura_source = _instance(
        owner,
        "red_00_01_02r_00",
        card_type=CardType.B_MINION,
        color=Color.RED,
        area=AreaType.BASE,
        card=build_base_token_aura(_row("red_00_01_02r_00")),
    )
    token = _instance(
        owner,
        "test_red_token",
        color=Color.RED,
        is_token=True,
        area=AreaType.FIELD,
    )
    owner.base.append(aura_source)
    owner.field.append(token)
    host = _instance(owner, "iron_sprite_host", color=Color.RED)
    owner.field.append(host)
    session.engine.state.step = Step.MAIN
    owner.movement_right_count = 1
    session.engine.bless(aura_source, host)

    session.engine.state.active_idx = session.engine.state.players.index(owner)
    active_state = session.state_dto()
    active_token = next(card for card in active_state["players"]["human"]["field"] if card["cardId"] == token.card.id)
    active_bp = active_token["effectiveBp"]

    session.engine.state.active_idx = session.engine.state.players.index(opponent)
    opponent_turn_state = session.state_dto()
    inactive_token = next(
        card for card in opponent_turn_state["players"]["human"]["field"]
        if card["cardId"] == token.card.id
    )
    assert active_bp - inactive_token["effectiveBp"] == 200


def test_purple_echo_suppresses_only_its_minion_dp_force_destroy_callback() -> None:
    def resolve(damage_kind: str, *, echo: bool, owner_turn: bool = True) -> list[str]:
        owner = Player(name="P1", side=Side.P1, is_first_player=True)
        opponent = Player(name="P2", side=Side.P2)
        state = GameState(players=[owner, opponent])
        engine = Engine(state, rng=random.Random(902))
        events: list[str] = []
        source = _instance(owner, "damage_source")
        source.card.effects.append(
            EffectSpec(
                timing=EffectTiming.ON_DAMAGE_FORCE,
                fn=lambda _source, _state, _ctx: events.append("damage_trigger"),
            )
        )
        owner.field.append(source)
        if echo:
            echo_card = _card_from_row(_row("purple_00_01_02r_00"))
            source.blessings.append(
                CardInstance(card=echo_card, owner=owner, area=AreaType.BLESSING)
            )
        force = Force(
            id="test_force",
            name_jp="test force",
            initial_life=1,
            on_destroy=lambda _force, _state, _ctx: events.append("force_destroy"),
        )
        force_instance = ForceInstance(force=force, owner=opponent, life=1)
        opponent.forces.append(force_instance)
        if not owner_turn:
            state.active_idx = state.players.index(opponent)

        engine._damage_force(force_instance, 1, source, damage_kind=damage_kind)
        assert force_instance.destroyed
        return events

    assert resolve("minion_dp", echo=True) == ["damage_trigger"]
    assert resolve("effect", echo=True) == ["force_destroy", "damage_trigger"]
    assert resolve("minion_dp", echo=True, owner_turn=False) == ["force_destroy", "damage_trigger"]
    assert resolve("minion_dp", echo=False) == ["force_destroy", "damage_trigger"]


def test_nested_trigger_waits_for_existing_target_prompt_then_resumes_callback() -> None:
    session = GameSession(seed=903, mode="god")
    owner, opponent = session.engine.state.players
    session._clear_prompt()
    selected: list[CardInstance] = []
    source = _instance(owner, "queued_trigger_source")
    target = _instance(opponent, "queued_trigger_target")

    effect = EffectSpec(
        timing=EffectTiming.ON_DAMAGE_FORCE,
        fn=lambda instance, state, _ctx: selected.extend(
            state.engine.select_target(instance.owner, "enemy_minion", 1, 1, source=instance)
        ),
        target_kind="enemy_minion",
    )
    source.card.effects.append(effect)
    owner.field.append(source)
    opponent.field.append(target)

    session._set_prompt("effect_target", "finish current selection", [])
    session.engine.triggers.emit(
        EffectTiming.ON_DAMAGE_FORCE,
        Context(controller=owner, source=source),
    )
    session.engine.triggers.resolve_all()

    assert selected == []
    assert session.engine.triggers.has_pending(instance=source, trigger=effect)

    session._clear_prompt()
    session.engine.triggers.resolve_all()
    assert session.prompt is not None and session.prompt["kind"] == "effect_target"
    target_option = next(
        option for option in session.prompt["options"]
        if str(option.get("cardIid")) == str(target.iid)
    )
    result = session.choose(session.prompt["id"], target_option["id"])

    assert result["error"] is None
    assert selected == [target]


def test_play_target_count_uses_the_effect_spec_matching_current_blue_dragon_condition() -> None:
    session = GameSession(seed=904, mode="god")
    owner = session.engine.state.players[0]
    card = build_blue_multi_target(_row("blue_04_03_02r_00"))
    source = CardInstance(
        card=card,
        owner=owner,
        iid=max(instance.iid for instance in owner.hand) + 1000,
        area=AreaType.HAND,
    )
    owner.hand.append(source)
    action = Action(kind="play_card", payload={"iid": source.iid})

    assert session._target_count_for_action(action, owner) == 1

    dragon = _instance(
        owner,
        "blue_dragon",
        color=Color.BLUE,
        race_jp="ドラゴン",
    )
    owner.field.append(dragon)
    assert session._target_count_for_action(action, owner) == 2


def test_densai_uses_protected_return_to_deck_path() -> None:
    owner = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    engine = Engine(GameState(players=[owner, opponent]), rng=random.Random(905))
    engine.set_policies(_FirstTargetPolicy(), _FirstTargetPolicy())
    source = _instance(owner, "densai_source")
    protected = _instance(opponent, "protected_target")
    protector = _instance(opponent, "protector")
    protector.card.effect_protection = (
        lambda _protector, target, operation, _state:
        target is protected and operation == "return_to_deck"
    )
    owner.field.append(source)
    opponent.field.extend([protected, protector])

    _densai_summon(source, engine.state, Context(controller=owner, source=source))

    assert protected in opponent.field
    assert protected not in opponent.deck

    protector.card.effect_protection = None
    _densai_summon(source, engine.state, Context(controller=owner, source=source))
    assert opponent.deck[0] is protected


def test_opponent_token_replacement_uses_receivers_capacity_and_policy() -> None:
    session = GameSession(seed=906, mode="debug-card-lab")
    owner, opponent = session.engine.state.players
    session._clear_prompt()
    session.debug_control_both = True
    assert isinstance(session.engine.policy_for(opponent), PassOnlyPolicy)
    source_card = build_opponent_token_summoner(_row("colorless_02_02_02r_01"))
    source = _instance(owner, source_card.id, card=source_card)
    owner.field.append(source)
    opponent.field.extend(
        _instance(opponent, f"receiver_minion_{index}")
        for index in range(FIELD_CAP)
    )
    selected_replacement = opponent.field[3]

    session.engine.triggers.emit(
        EffectTiming.ON_SUMMON,
        Context(controller=owner, source=source),
    )
    session.engine.triggers.resolve_all()

    assert session.prompt is not None
    assert session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "ally_minion"
    assert session.prompt["playerSide"] == opponent.side.name
    replacement_option = next(
        option for option in session.prompt["options"]
        if str(option.get("cardIid")) == str(selected_replacement.iid)
    )
    result = session.choose(session.prompt["id"], replacement_option["id"])

    assert result["error"] is None
    assert selected_replacement not in opponent.field
    assert len(opponent.field) == FIELD_CAP
    assert any(card.card.id == "slime_block_token" for card in opponent.field)


def test_shared_create_tokens_template_uses_declared_token_recipient() -> None:
    owner = Player(name="P1", side=Side.P1, is_first_player=True)
    opponent = Player(name="P2", side=Side.P2)
    engine = Engine(GameState(players=[owner, opponent]), rng=random.Random(907))
    source = _instance(owner, "token_source")
    owner.field.append(source)
    effect = build_effect(
        "create_tokens",
        EffectTiming.ON_SUMMON,
        amount=1,
        token_id="recipient_token",
        name_jp="recipient token",
        color=Color.RED,
        cost=0,
        bp=100,
        dp=1,
        token_recipient="opponent",
    )

    effect.fn(source, engine.state, Context(controller=owner, source=source))

    assert owner.field == [source]
    assert [card.card.id for card in opponent.field] == ["recipient_token"]
