from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable, Iterable

from zz.cards import CARD_REGISTRY, register
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, AttackTargetKind, CardType, Color, Keyword, Step, TriggerTiming
from zz.model import AttackTarget, Card, CardInstance, Context, ForceInstance, Player
from zz.pc01 import DEFAULT_CARD_TSV, _card_from_row


PC02_PACK_JP = "PC:02 CONTRACT"


def _effect(
    timing: EffectTiming,
    fn: Callable[[CardInstance, Any, Context], None],
    *,
    pre_target_fn: Callable[[CardInstance, Any, Context], None] | None = None,
    condition: Callable[[CardInstance, Any, Context], bool] | None = None,
    target_kind: str | None = None,
    min_targets: int = 1,
    max_targets: int = 1,
    optional: bool = False,
    template_id: str | None = None,
    params: dict[str, Any] | None = None,
    official_effect: str,
    official_timing: str,
    official_condition: str | None = None,
    active_areas: tuple[AreaType, ...] | None = None,
) -> EffectSpec:
    return EffectSpec(
        timing=timing,
        fn=fn,
        pre_target_fn=pre_target_fn,
        condition=condition,
        target_kind=target_kind,
        min_targets=min_targets,
        max_targets=max_targets,
        optional=optional,
        template_id=template_id,
        params=dict(params or {}),
        official_effect=official_effect,
        official_timing=official_timing,
        official_condition=official_condition,
        active_areas=active_areas,
    )


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _own_turn(source: CardInstance, state: Any, ctx: Context) -> bool:
    return state.active is source.owner


def _opponent(state: Any, player: Player) -> Player:
    return state.players[1 - state.players.index(player)]


def _card_color(card: Card) -> Color:
    if card.mana_color is not None:
        return card.mana_color
    return next((color for color in card.cost if color is not Color.COLORLESS), Color.COLORLESS)


def _total_cost(card: Card) -> int:
    return sum(card.cost.values())


def _has_race(card: Card, *races: str) -> bool:
    return any(race in card.race_jp for race in races)


def _is_color(card: Card, *colors: Color) -> bool:
    return _card_color(card) in colors


def _other_ally_entered(source: CardInstance, state: Any, ctx: Context) -> bool:
    entered = ctx.source
    return (
        isinstance(entered, CardInstance)
        and entered is not source
        and entered.owner is source.owner
        and entered.area is AreaType.FIELD
    )


_STANDARD_BLESS_COLORS = {
    "red_00_01_02_00": Color.RED,
    "yellow_00_01_02_00": Color.YELLOW,
    "white_00_01_02_00": Color.WHITE,
    "green_00_01_02_00": Color.GREEN,
    "blue_00_01_02_00": Color.BLUE,
    "purple_00_01_02_00": Color.PURPLE,
}

_ADVANCED_BLESS_COLORS = {
    "red_00_01_02_01": Color.RED,
    "yellow_00_01_02_01": Color.YELLOW,
    "white_00_01_02_01": Color.WHITE,
    "green_00_01_02_01": Color.GREEN,
    "blue_00_01_02_01": Color.BLUE,
    "purple_00_01_02_01": Color.PURPLE,
}

_COLORLESS_COST_BLESS_IDS = {"colorless_00_01_02_00", "colorless_00_01_02_02"}
_UNCONDITIONAL_BLESS_IDS = {"colorless_00_01_02_01"}
_BLESS_CONDITION_OVERRIDE_TARGET_IDS = {"green_03_02_02_00"}


def bless_condition_matches(mana: CardInstance, target: CardInstance) -> bool:
    if target.card.id in _BLESS_CONDITION_OVERRIDE_TARGET_IDS:
        return True
    mana_id = mana.card.id
    if mana_id in _STANDARD_BLESS_COLORS:
        return _card_color(target.card) is _STANDARD_BLESS_COLORS[mana_id]
    if mana_id in _ADVANCED_BLESS_COLORS:
        return _card_color(target.card) is _ADVANCED_BLESS_COLORS[mana_id] and _total_cost(target.card) >= 4
    if mana_id in _COLORLESS_COST_BLESS_IDS:
        return _total_cost(target.card) >= 4
    return mana_id in _UNCONDITIONAL_BLESS_IDS


def blessing_keywords(host: CardInstance) -> list[Keyword]:
    keywords: list[Keyword] = []
    for mana in host.blessings:
        if mana.card.id == "purple_00_01_02_01":
            keywords.append(Keyword.DEATH_BLOW)
        elif mana.card.id == "colorless_00_01_02_01":
            keywords.append(Keyword.REAWAKEN)
    return keywords


def _firely_blocked(host: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.target is host and isinstance(ctx.source, CardInstance)


def _firely_debuff(host: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(ctx.source, bp_delta=-200, duration="permanent")


def _sunlight_growth(host: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(host, bp_delta=200, duration="turn")


def _chronora_win(host: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is host and isinstance(ctx.target, CardInstance) and _total_cost(ctx.target.card) <= 3


def _refresh_host(host: CardInstance, state: Any, ctx: Context) -> None:
    host.rested = False


def _griefi_attack(host: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(host.owner, "enemy_force", 1, 1, source=host)
    for target in targets:
        target.rested = True


def _bleuvert_attack(host: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.grant_movement_right(host.owner, 1)


_BLESSING_GRANTED_EFFECTS: dict[str, tuple[EffectSpec, ...]] = {
    "red_00_01_02_01": (
        _effect(EffectTiming.ON_BLOCK, _firely_debuff, condition=_firely_blocked, official_effect="ブロックしたミニオンにBP-200を付与", official_timing="アタック時/ブロック時"),
    ),
    "yellow_00_01_02_01": (
        _effect(EffectTiming.ON_ENTER_FIELD, _sunlight_growth, condition=_other_ally_entered, official_effect="他の自分のミニオンが出るたびBP+200", official_timing="常時"),
    ),
    "white_00_01_02_01": (
        _effect(EffectTiming.ON_BATTLE_WIN, _refresh_host, condition=_chronora_win, official_effect="コスト3以下とのバトル勝利時にアクティブ", official_timing="常時"),
    ),
    "green_00_01_02_01": (
        _effect(EffectTiming.ON_ATTACK, _griefi_attack, condition=_self_source, target_kind="enemy_force", official_effect="相手のフォース1つをレスト", official_timing="アタック時"),
    ),
    "blue_00_01_02_01": (
        _effect(EffectTiming.ON_ATTACK, _bleuvert_attack, condition=_self_source, official_effect="移動権を1増やす", official_timing="アタック時"),
    ),
}


def blessing_effects(host: CardInstance, timing: EffectTiming, ctx: Context) -> Iterable[EffectSpec]:
    for mana in host.blessings:
        for effect in _BLESSING_GRANTED_EFFECTS.get(mana.card.id, ()):
            if effect.timing is timing:
                yield effect


def _replacement_iid(engine: Any, player: Player, source: CardInstance) -> int | None:
    if len(player.field) < 5:
        return None
    selected = engine.select_target(player, "ally_minion", 1, 1, source=source)
    return selected[0].iid if selected else None


def _base_replacement_iid(engine: Any, player: Player, source: CardInstance) -> int | None:
    if len(player.base) < 10:
        return None
    selected = engine.select_target(player, "ally_base", 1, 1, source=source)
    return selected[0].iid if selected else None


def _create_tokens(source: CardInstance, state: Any, specs: list[Card]) -> None:
    state.engine.create_tokens(source.owner, specs, source=source)


def _token_card(card_id: str, name_jp: str, cost: int, bp: int, dp: int, *, ability_jp: str = "") -> Card:
    return Card(
        id=card_id,
        name_jp=name_jp,
        name_en=name_jp,
        type=CardType.F_MINION,
        cost={Color.COLORLESS: cost},
        bp=bp,
        dp=dp,
        race_jp="ドラゴン",
        ability_jp=ability_jp,
        is_token=True,
    )


DRAGON_TOKEN = _token_card("colorless_04_04_00_00", "ドラゴン・トークン", 4, 500, 2)
FIRE_DRAGON_TOKEN = _token_card("colorless_01_04_00_01", "ドラゴン「火」・トークン", 1, 300, 0, ability_jp="【常時】このミニオンはフォースにアタックできない。")
WATER_DRAGON_TOKEN = _token_card("colorless_03_04_00_00", "ドラゴン「水」・トークン", 3, 400, 1, ability_jp="【常時】このミニオンはフォースにアタックできない。")
WIND_DRAGON_TOKEN = _token_card("colorless_04_04_00_01", "ドラゴン「風」・トークン", 4, 500, 2, ability_jp="【常時】このミニオンはフォースにアタックできない。")
THUNDER_DRAGON_TOKEN = _token_card("colorless_05_04_00_00", "ドラゴン「雷」・トークン", 5, 700, 2, ability_jp="【常時】このミニオンはフォースにアタックできない。")


def _destroy_colorless_mana(source: CardInstance, state: Any, *, draw: bool = False) -> bool:
    engine = state.engine
    selected = engine.select_target(
        source.owner,
        "ally_colorless_mana_token",
        0,
        1,
        source=source,
    )
    if not selected:
        return False
    mana = selected[0]
    engine._eject_base_card(source.owner, mana)
    if draw:
        engine.draw(source.owner, 1)
    return True


def _digger_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    _destroy_colorless_mana(source, state, draw=True)


def _gran_rex_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    _destroy_colorless_mana(source, state)


def _fire_lizard_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source is not target or state.active is not source.owner:
        return 0, 0
    copies = sum(card.card.id == source.card.id for card in source.owner.field)
    return max(0, copies - 1) * 300, 0


def _jane_keyword_aura(source: CardInstance, target: CardInstance, state: Any) -> list[Keyword]:
    if (
        state.active is source.owner
        and target.owner is source.owner
        and _is_color(target.card, Color.RED, Color.COLORLESS)
        and _has_race(target.card, "ドラゴン")
    ):
        return [Keyword.RUSH]
    return []


def _shape_shift(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    selected = engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: _card_color(target.card) is Color.RED and _total_cost(target.card) <= 3,
        source=source,
    )
    if not selected:
        return
    replacement = _replacement_iid(engine, source.owner, source)
    if len(source.owner.field) >= 5 and replacement is None:
        return
    original = selected[0]
    copy = CardInstance(
        card=original.card,
        owner=source.owner,
        iid=state.allocate_iid(),
        area=AreaType.FIELD,
        summoning_sickness=True,
    )
    engine._make_field_space(source.owner, replacement)
    source.owner.field.append(copy)
    engine._emit_enter_field(source.owner, copy)


def _breaching(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        amount = -600 if _has_race(target.card, "ドラゴン") else -300
        state.engine.modify_stat(target, bp_delta=amount, duration="permanent")


def _margus_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    if not _destroy_colorless_mana(source, state):
        return
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        state.engine.add_keyword(target, Keyword.CANNOT_BLOCK)


def _fossil(source: CardInstance, state: Any, ctx: Context) -> None:
    if not _destroy_colorless_mana(source, state):
        return
    engine = state.engine
    top = list(source.owner.deck[:3])
    selected = engine.select_target(
        source.owner,
        "top3_field_minion",
        1,
        1,
        filter_fn=lambda target: _has_race(target.card, "ドラゴン") and _is_color(target.card, Color.RED, Color.COLORLESS),
        source=source,
    )
    chosen = selected[0] if selected else None
    for card in top:
        if card in source.owner.deck:
            source.owner.deck.remove(card)
    if chosen is not None:
        replacement = _replacement_iid(engine, source.owner, source)
        if len(source.owner.field) < 5 or replacement is not None:
            engine._make_field_space(source.owner, replacement)
            chosen.area = AreaType.FIELD
            chosen.summoning_sickness = True
            source.owner.field.append(chosen)
            engine._record_zone_move(chosen, AreaType.DECK, AreaType.FIELD)
            engine._emit_enter_field(source.owner, chosen)
        else:
            chosen = None
    rest = [card for card in top if card is not chosen]
    engine.rng.shuffle(rest)
    for card in rest:
        card.area = AreaType.DECK
        source.owner.deck.append(card)


def _magma_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: state.engine.effective_bp(target) <= 500,
        source=source,
    )
    if not targets:
        return
    target = targets[0]
    state.engine.destroy_target(target, source)
    if target.area is not AreaType.FIELD:
        _create_tokens(source, state, [DRAGON_TOKEN])


def _otter_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=100, duration="permanent")


def _air_raid(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    amount = -400 if state.summoned_this_turn and any(ci.owner is source.owner for ci in state.summoned_this_turn) else -200
    for target in targets:
        state.engine.modify_stat(target, bp_delta=amount, duration="permanent")


def _tornado_blow(source: CardInstance, state: Any, ctx: Context) -> None:
    source.owner.flags.add("turn:pc02_return_damager")


def _celica_search(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    selected = engine.select_target(
        source.owner,
        "deck_card",
        0,
        1,
        filter_fn=lambda target: target.card.type is CardType.F_MINION and _has_race(target.card, "ドラゴン") and (_card_color(target.card) is Color.YELLOW or _total_cost(target.card) >= 9),
        source=source,
    )
    for target in selected:
        source.owner.deck.remove(target)
        engine.reveal_card(source.owner, target, "deck_search")
        engine.add_to_hand(source.owner, target, from_area=AreaType.DECK)
    engine.rng.shuffle(source.owner.deck)


def _kungfu_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=200, duration="turn")
        state.engine.add_keyword(target, Keyword.REAWAKEN)


def _milky_return(source: CardInstance, state: Any, ctx: Context) -> None:
    if not getattr(ctx, "blessed_return_to_hand", False) or source not in source.owner.trash:
        return
    state.engine.add_to_hand(source.owner, source, from_area=AreaType.TRASH)


def _ryudou_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: target is not source,
        source=source,
    )
    for target in targets:
        target.flags.add("turn:pc02_always_wins_battle")


def _densai_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        target.owner.field.remove(target)
        state.engine._return_blessings_to_base(target)
        state.engine._reset_card_zone_state(target)
        target.area = AreaType.DECK
        target.owner.deck.insert(0, target)
        state.engine._record_zone_move(target, AreaType.FIELD, AreaType.DECK)


def _eisen_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source is not target:
        return 0, 0
    destroyed = sum(force.destroyed for force in source.owner.forces)
    return destroyed * 200, destroyed


def _ra7_force_attacked(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        state.active is not source.owner
        and isinstance(ctx.source, CardInstance)
        and isinstance(ctx.target, ForceInstance)
        and ctx.target.owner is source.owner
    )


def _ra7_growth(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=100, duration="permanent")


def _matilda_win(source: CardInstance, state: Any, ctx: Context) -> bool:
    winner = ctx.source
    return (
        state.active is source.owner
        and isinstance(winner, CardInstance)
        and winner.owner is source.owner
        and _has_race(winner.card, "ドラゴン")
        and _is_color(winner.card, Color.WHITE, Color.COLORLESS)
    )


def _matilda_damage(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine._damage_player(_opponent(state, source.owner), 1, source=source)


def _moving_shield(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    forces = [force for force in source.owner.forces if not force.destroyed]
    if not forces:
        engine.draw(source.owner, 1)
        return
    selected = engine.select_target(source.owner, "ally_force", 1, 1, source=source)
    if selected:
        engine._pc02_attack_target_override = AttackTarget(AttackTargetKind.FORCE, selected[0])


def _apostel_win(source: CardInstance, state: Any, ctx: Context) -> bool:
    winner = ctx.source
    return isinstance(winner, CardInstance) and winner.owner is source.owner and _card_color(winner.card) is Color.WHITE


def _apostel_growth(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=100, dp_delta=1, duration="permanent")


def _option_parts(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in source.owner.field:
        if _card_color(target.card) is Color.WHITE:
            state.engine.modify_stat(target, bp_delta=200, duration="permanent")


def _ivan_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    source.flags.add("must_be_blocked")


def _kanonen_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        target.rested = False
        target.flags.add("turn:must_block")


def _kanonen_win(source: CardInstance, state: Any, ctx: Context) -> bool:
    return state.active is source.owner and ctx.source is source


def _remove_target(engine: Any, target: CardInstance) -> None:
    if target.area is not AreaType.FIELD:
        return
    target.owner.field.remove(target)
    engine._return_blessings_to_base(target)
    engine._reset_card_zone_state(target)
    target.area = AreaType.REMOVED
    target.owner.removed.append(target)
    engine._record_zone_move(target, AreaType.FIELD, AreaType.REMOVED)


def _remove_enemy(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        _remove_target(state.engine, target)


def _anima(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    selected = engine.select_target(
        source.owner,
        "deck_base_minion",
        1,
        1,
        filter_fn=lambda target: target.card.mana_color is Color.GREEN and _has_race(target.card, "ニンフ"),
        source=source,
    )
    if selected:
        target = selected[0]
        replace_iid = _base_replacement_iid(engine, source.owner, source)
        if len(source.owner.base) < 10 or replace_iid is not None:
            engine._make_base_space(source.owner, replace_iid)
            source.owner.deck.remove(target)
            target.area = AreaType.BASE
            target.rested = True
            source.owner.base.append(target)
            engine._record_zone_move(target, AreaType.DECK, AreaType.BASE)
            engine.triggers.emit(EffectTiming.ON_PLACE_BASE, Context(controller=source.owner, source=target))
            engine.triggers.resolve_all()
    engine.rng.shuffle(source.owner.deck)


def _papilio_nymph_placed(source: CardInstance, state: Any, ctx: Context) -> bool:
    placed = ctx.source
    return isinstance(placed, CardInstance) and placed.owner is source.owner and _has_race(placed.card, "ニンフ")


def _papilio_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: target.rested,
        source=source,
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _bayagan_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.add_keyword(source, Keyword.RUSH)
    state.engine.add_keyword(source, Keyword.REAWAKEN)


def _sylvie_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    for mana in source.owner.base:
        if _has_race(mana.card, "ニンフ"):
            mana.rested = False


def _blessed_ally_attack(source: CardInstance, state: Any, ctx: Context) -> bool:
    attacker = ctx.source
    return (
        state.active is source.owner
        and isinstance(attacker, CardInstance)
        and attacker.owner is source.owner
        and bool(attacker.blessings)
    )


def _rest_enemy(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        target.rested = True


def _rest_all_enemy(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in _opponent(state, source.owner).field:
        target.rested = True


def _hatoto_enemy_enter(source: CardInstance, state: Any, ctx: Context) -> bool:
    entered = ctx.source
    return state.active is not source.owner and isinstance(entered, CardInstance) and entered.owner is not source.owner


def _hatoto_rest(source: CardInstance, state: Any, ctx: Context) -> None:
    if isinstance(ctx.source, CardInstance):
        ctx.source.rested = True


def _apprentice_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    if not source.owner.deck:
        return
    target = source.owner.deck[0]
    selected = state.engine.select_target(source.owner, "top1_card", 0, 1, source=source)
    if not selected:
        source.owner.deck.remove(target)
        source.owner.deck.append(target)


def _sophia_dragon_enter(source: CardInstance, state: Any, ctx: Context) -> bool:
    entered = ctx.source
    return (
        state.active is source.owner
        and isinstance(entered, CardInstance)
        and entered.owner is source.owner
        and _has_race(entered.card, "ドラゴン")
        and _is_color(entered.card, Color.BLUE, Color.COLORLESS)
    )


def _blackscale_retreat(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: _total_cost(target.card) <= 5,
        source=source,
    )
    for target in targets:
        replace_iid = _base_replacement_iid(engine, target.owner, source)
        if len(target.owner.base) < 10 or replace_iid is not None:
            engine.move_target_to_base(target, rested=True, replace_base_iid=replace_iid)


def _giulio_move(source: CardInstance, state: Any, ctx: Context) -> bool:
    moved = ctx.source
    return isinstance(moved, CardInstance) and moved is not source and moved.owner is source.owner and _card_color(moved.card) is Color.BLUE


def _giulio_refresh(source: CardInstance, state: Any, ctx: Context) -> None:
    if isinstance(ctx.source, CardInstance):
        ctx.source.rested = False


def _rainbow_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def _david_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    top = list(source.owner.deck[:3])
    selected = engine.select_target(
        source.owner,
        "top3_magic",
        0,
        3,
        source=source,
    )
    selected_iids = {card.iid for card in selected}
    for card in top:
        source.owner.deck.remove(card)
    rest: list[CardInstance] = []
    for card in top:
        if card.iid in selected_iids:
            engine.reveal_card(source.owner, card, "top_magic")
            engine.add_to_hand(source.owner, card, from_area=AreaType.DECK)
        else:
            rest.append(card)
    engine.rng.shuffle(rest)
    for card in rest:
        card.area = AreaType.DECK
        source.owner.deck.append(card)


def _guerrerofon_free_magic(source: CardInstance, state: Any, ctx: Context) -> None:
    source.owner.flags.add("turn:pc02_next_blue_magic_free")


def _maelshtrom(source: CardInstance, state: Any, ctx: Context) -> None:
    _create_tokens(source, state, [FIRE_DRAGON_TOKEN, WATER_DRAGON_TOKEN, WIND_DRAGON_TOKEN, THUNDER_DRAGON_TOKEN])


def _murmur_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: _card_color(target.card) is Color.PURPLE,
        source=source,
    )
    for target in targets:
        state.engine.modify_stat(target, bp_delta=100, duration="permanent")


def _bad_talk_mill(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.mill_deck(source.owner, 3, source=source)


def _bad_talk(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "trash_minion",
        1,
        1,
        filter_fn=lambda target: _total_cost(target.card) <= 3,
        source=source,
    )
    for target in targets:
        state.engine.add_to_hand(source.owner, target, from_area=AreaType.TRASH)


def _richard_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    source.owner.flags.add("turn:pc02_draw_enemy_destroy")


def _ante_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: target is not source,
        source=source,
    )
    if not targets:
        return
    target = targets[0]
    state.engine.destroy_target(target, source)
    if target.area is not AreaType.FIELD:
        state.engine.modify_stat(source, bp_delta=200, dp_delta=1, duration="permanent")


def _doomed_road(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if not targets:
        return
    state.engine.modify_stat(targets[0], bp_delta=-200, duration="permanent")
    for target in source.owner.field:
        if _card_color(target.card) is Color.PURPLE:
            state.engine.modify_stat(target, bp_delta=100, duration="permanent")


def _francesca_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "trash_field_minion",
        0,
        1,
        filter_fn=lambda target: _has_race(target.card, "ドラゴン") and _is_color(target.card, Color.PURPLE, Color.COLORLESS),
        source=source,
    )
    for target in targets:
        state.engine.add_to_hand(source.owner, target, from_area=AreaType.TRASH)


def _gustave_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    amount = 100 * sum(card.card.type is CardType.F_MINION for player in state.players for card in player.trash)
    state.engine.modify_stat(source, bp_delta=amount, duration="permanent")


def _demons_terror(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in _opponent(state, source.owner).field:
        target.flags.add("turn:pc02_cannot_attack")


def _skullbone_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if not targets:
        return
    target = targets[0]
    amount = _total_cost(target.card)
    state.engine.destroy_target(target, source)
    if target.area is not AreaType.FIELD:
        state.engine.mill_deck(source.owner, amount, source=source)


def _cryska_place(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    top = list(source.owner.deck[:4])
    selected = engine.select_target(
        source.owner,
        "top4_card",
        1,
        1,
        filter_fn=lambda target: target.card.type is CardType.F_MINION and _has_race(target.card, "ドラゴン"),
        source=source,
    )
    chosen = selected[0] if selected else None
    for card in top:
        source.owner.deck.remove(card)
    if chosen is not None:
        engine.reveal_card(source.owner, chosen, "deck_search")
        engine.add_to_hand(source.owner, chosen, from_area=AreaType.DECK)
    rest = [card for card in top if card is not chosen]
    engine.rng.shuffle(rest)
    for card in rest:
        card.area = AreaType.DECK
        source.owner.deck.append(card)


def _scarlet_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    if any(card.blessings for card in source.owner.field) or any(
        Keyword.KAGO in mana.card.keywords or Keyword.BLESS in mana.card.keywords
        for mana in source.owner.base
    ):
        state.engine.draw(source.owner, 1)


def _dragon_priest_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    _create_tokens(source, state, [DRAGON_TOKEN])


def _gray_blob_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in list(_opponent(state, source.owner).field):
        if target.card.is_token:
            state.engine.destroy_target(target, source)


def _obsidian_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if target is not source and target.owner is source.owner and _has_race(target.card, "ドラゴン"):
        return 200, 0
    return 0, 0


def _steel_damage(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and state.active is source.owner and getattr(ctx, "damage_amount", 0) > 0


def _steel_heal(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.heal(source.owner, int(getattr(ctx, "damage_amount", 0)))


def _monoeye_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: has_destroy_effect(target.card),
        source=source,
    )
    for target in targets:
        _remove_target(state.engine, target)


def _hero_error(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in list(_opponent(state, source.owner).field):
        if _total_cost(target.card) >= 8:
            state.engine.destroy_target(target, source)


def _gilly_heal(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "owner_player_or_force", 1, 1, source=source)
    for target in targets:
        state.engine.heal_target(target, 1)


def _storm_rest(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: state.engine.effective_bp(target) <= 400,
        source=source,
    )
    for target in targets:
        target.rested = True


def _hagen_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=300, duration="turn")


def _hagen_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    marker = "turn:pc02_hagen_refresh"
    if marker in source.flags:
        return
    source.flags.add(marker)
    source.rested = False


def _hydra_end(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.controller is source.owner:
        _create_tokens(source, state, [DRAGON_TOKEN])


def _regenerate_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    marker = "turn:pc02_regenerate_used"
    if marker in source.owner.flags:
        return
    source.owner.flags.add(marker)
    for mana in source.owner.base:
        if state.engine._mana_color_of(mana) is not Color.COLORLESS:
            mana.rested = False


def _draw_one(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def _sonic_wave(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=-200, dp_delta=-1, duration="permanent")


def _power_of_sun(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=400, dp_delta=2, duration="turn")


def _forest_guard(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: target.rested,
        source=source,
    )
    for target in targets:
        state.engine.modify_stat(target, bp_delta=-500, duration="permanent")


def _tupa_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, dp_delta=1, duration="permanent")


def _merfolk_march(source: CardInstance, state: Any, ctx: Context) -> None:
    if any(_card_color(card.card) is Color.BLUE for card in source.owner.field):
        state.engine.grant_movement_right(source.owner, 1)


def _all_white_buff(source: CardInstance, state: Any, ctx: Context) -> None:
    _option_parts(source, state, ctx)


def has_destroy_effect(card: Card) -> bool:
    return any(effect.timing is EffectTiming.ON_DESTROY for effect in card.effects) or any(
        trigger.when is TriggerTiming.ON_DESTROY for trigger in card.triggers
    )


_PC02_EFFECTS_BY_ID: dict[str, tuple[EffectSpec, ...]] = {
    "red_01_02_02_00": (_effect(EffectTiming.ON_SUMMON, _digger_summon, condition=_self_source, target_kind="ally_colorless_mana_token", min_targets=0, max_targets=1, optional=True, official_effect="無色の非ミニオンマナを破壊して1枚引く", official_timing="召喚時"),),
    "red_03_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _shape_shift, target_kind="ally_minion", params={"color": "RED", "max_cost": 3}, official_effect="コスト3以下の赤のミニオンを複製して出す", official_timing="メイン"),),
    "red_03_03_02_01": (_effect(EffectTiming.ON_CAST_MAGIC, _breaching, target_kind="enemy_minion", official_effect="BP-300、ドラゴンならBP-600", official_timing="メイン/フラッシュ"),),
    "red_04_02_02_00": (_effect(EffectTiming.ON_SUMMON, _gran_rex_summon, condition=_self_source, target_kind="ally_colorless_mana_token", official_effect="無色の非ミニオンマナを破壊", official_timing="召喚時"),),
    "red_05_02_02_00": (
        build_effect(
            "create_tokens",
            EffectTiming.ON_BLESS,
            condition=_self_source,
            amount=1,
            token_id="s_golem_token",
            name_jp="S・ゴレイム・トークン",
            color=Color.RED,
            cost=1,
            bp=100,
            dp=1,
            race_jp="ゴレイム",
            official_effect="S・ゴレイム・トークンを出す",
            official_timing="加護時",
        ),
    ),
    "red_06_02_02_01": (_effect(EffectTiming.ON_SUMMON, _margus_summon, condition=_self_source, target_kind="ally_colorless_mana_token", official_effect="無色マナを破壊し相手1体をブロック不可", official_timing="召喚時"),),
    "red_08_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _fossil, target_kind="ally_colorless_mana_token", official_effect="無色マナを破壊し上3枚から赤/無色ドラゴンを出す", official_timing="メイン"),),
    "red_09_02_02_00": (_effect(EffectTiming.ON_ATTACK, _magma_attack, condition=_self_source, target_kind="enemy_minion", template_id="create_tokens", params={"max_bp": 500, "amount": 1}, official_effect="BP500以下を破壊してドラゴン・トークンを出す", official_timing="アタック時"),),
    "yellow_01_02_02_00": (_effect(EffectTiming.ON_SUMMON, _otter_summon, condition=_self_source, target_kind="ally_minion", official_effect="自分のミニオンにBP+100", official_timing="召喚時"),),
    "yellow_02_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _air_raid, target_kind="enemy_minion", official_effect="BP-200、召喚済みならBP-400", official_timing="フラッシュ"),),
    "yellow_03_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _tornado_blow, official_effect="ダメージを与えたミニオンを手札に戻す能力をプレイヤーに付与", official_timing="フラッシュ"),),
    "yellow_04_02_02_00": (_effect(EffectTiming.ON_SUMMON, _celica_search, condition=_self_source, target_kind="pc02_celica_dragon", min_targets=0, max_targets=1, optional=True, official_effect="黄またはコスト9以上のドラゴンを検索", official_timing="召喚時"),),
    "yellow_04_02_02_02": (_effect(EffectTiming.ON_SUMMON, _kungfu_summon, condition=_self_source, target_kind="ally_minion", official_effect="BP+200と再起を付与", official_timing="召喚時"),),
    "yellow_05_02_02_00": (_effect(EffectTiming.ON_DESTROY, _milky_return, official_effect="加護されていたなら手札に戻す", official_timing="破壊時"),),
    "yellow_06_02_02_00": (_effect(EffectTiming.ON_SUMMON, _ryudou_summon, condition=_self_source, target_kind="other_ally_minion", official_effect="他の自分のミニオンにバトル必勝を付与", official_timing="召喚時"),),
    "yellow_06_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _power_of_sun, target_kind="ally_minion", official_effect="BP+400/DP+2", official_timing="メイン/フラッシュ"),),
    "yellow_09_02_02_00": (_effect(EffectTiming.ON_SUMMON, _densai_summon, condition=_self_source, target_kind="enemy_minion", official_effect="相手のミニオンをデッキ上に戻す", official_timing="召喚時"),),
    "white_03_02_02_00": (_effect(EffectTiming.ON_ATTACK, _ra7_growth, condition=_ra7_force_attacked, official_effect="自分のフォースが攻撃されるたびBP+100", official_timing="相手のターン"),),
    "white_03_02_02_01": (_effect(EffectTiming.ON_BATTLE_WIN, _matilda_damage, condition=_matilda_win, official_effect="白/無色ドラゴンのバトル勝利時に相手プレイヤーへ1ダメージ", official_timing="自分のターン"),),
    "white_03_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _moving_shield, target_kind="ally_force", official_effect="攻撃対象を変更、フォースが無ければ1枚引く", official_timing="フラッシュ"),),
    "white_04_02_02_00": (_effect(EffectTiming.ON_BATTLE_WIN, _apostel_growth, condition=_apostel_win, official_effect="白のミニオンのバトル勝利時BP+100/DP+1", official_timing="常時"),),
    "white_04_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _all_white_buff, official_effect="自分の白のミニオン全てにBP+200", official_timing="メイン"),),
    "white_05_02_02_00": (_effect(EffectTiming.ON_BLESS, _ivan_bless, condition=_self_source, official_effect="相手は必ずブロックする", official_timing="加護時"),),
    "white_06_02_02_00": (
        _effect(EffectTiming.ON_SUMMON, _kanonen_summon, condition=_self_source, target_kind="enemy_minion", official_effect="相手1体をアクティブにして必ずブロック", official_timing="召喚時"),
        _effect(EffectTiming.ON_BATTLE_WIN, _draw_one, condition=_kanonen_win, official_effect="バトル勝利時1枚引く", official_timing="自分のターン"),
    ),
    "white_06_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _remove_enemy, target_kind="enemy_minion", official_effect="相手のミニオン1体を除外", official_timing="フラッシュ"),),
    "green_01_02_02_00": (_effect(EffectTiming.ON_BLESS, _tupa_bless, condition=_self_source, official_effect="DP+1を付与", official_timing="加護時"),),
    "green_02_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _anima, target_kind="deck_base_minion", params={"color": "GREEN", "race": "ニンフ"}, official_effect="緑のニンフBミニオンをデッキからベースにレストで置く", official_timing="メイン"),),
    "green_03_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _forest_guard, target_kind="enemy_minion", params={"only_rested": True}, official_effect="レスト状態の相手にBP-500", official_timing="メイン/フラッシュ"),),
    "green_04_02_02_00": (_effect(EffectTiming.ON_PLACE_BASE, _papilio_destroy, condition=_papilio_nymph_placed, target_kind="enemy_minion", params={"only_rested": True}, official_effect="ニンフのマナ配置時にレスト状態の相手を破壊", official_timing="常時"),),
    "green_05_02_02_00": (_effect(EffectTiming.ON_BLESS, _bayagan_bless, condition=_self_source, official_effect="このターン襲撃と再起を付与", official_timing="加護時"),),
    "green_06_02_02_00": (
        _effect(EffectTiming.ON_SUMMON, _sylvie_summon, condition=_self_source, official_effect="自分のニンフマナ全てをアクティブ", official_timing="召喚時"),
        _effect(EffectTiming.ON_ATTACK, _rest_enemy, condition=_blessed_ally_attack, target_kind="enemy_minion", official_effect="加護された自分のミニオンの攻撃時に相手1体をレスト", official_timing="自分のターン"),
    ),
    "green_08_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _rest_all_enemy, official_effect="相手のミニオン全てをレスト", official_timing="メイン"),),
    "green_09_02_02_00": (_effect(EffectTiming.ON_ENTER_FIELD, _hatoto_rest, condition=_hatoto_enemy_enter, official_effect="相手のミニオンはレストで出る", official_timing="相手のターン"),),
    "blue_00_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _merfolk_march, official_effect="青のミニオンがいれば移動権+1", official_timing="メイン"),),
    "blue_01_02_02_00": (_effect(EffectTiming.ON_SUMMON, _apprentice_summon, condition=_self_source, target_kind="top1_card", min_targets=0, max_targets=1, params={"deck_reorder": "top_or_bottom"}, official_effect="自分のデッキ上1枚を見て上か下へ", official_timing="召喚時"),),
    "blue_03_02_02_00": (_effect(EffectTiming.ON_ENTER_FIELD, _draw_one, condition=_sophia_dragon_enter, official_effect="青/無色ドラゴンが出るたび1枚引く", official_timing="自分のターン"),),
    "blue_03_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _sonic_wave, target_kind="enemy_minion", official_effect="BP-200と本来のDP-1", official_timing="メイン/フラッシュ"),),
    "blue_04_02_02_00": (_effect(EffectTiming.MOVE_TO_BASE, _blackscale_retreat, condition=_self_source, target_kind="enemy_minion", params={"max_cost": 5, "moves_targets_to_base": True}, official_effect="コスト5以下をレストでベースへ移動", official_timing="後退時", active_areas=(AreaType.BASE,)),),
    "blue_05_02_02_00": (
        _effect(EffectTiming.ON_MOVE_TO_FIELD, _giulio_refresh, condition=_giulio_move, official_effect="移動した青のミニオン/マナを移動先でアクティブ", official_timing="常時"),
        _effect(EffectTiming.MOVE_TO_BASE, _giulio_refresh, condition=_giulio_move, official_effect="移動した青のミニオン/マナを移動先でアクティブ", official_timing="常時"),
    ),
    "blue_05_02_02_01": (_effect(EffectTiming.ON_BLESS, _rainbow_bless, condition=_self_source, official_effect="1枚引く", official_timing="加護時"),),
    "blue_06_02_02_00": (_effect(EffectTiming.ON_SUMMON, _david_summon, condition=_self_source, target_kind="top3_magic", min_targets=0, max_targets=3, params={"allow_variable_targets": True, "top_n": 3, "card_type": "MAGIC"}, official_effect="自分のデッキを上から3枚見て、その中のマジックカード全てを公開して手札に加える。残りをランダムにデッキの下に戻す。", official_timing="召喚時"),),
    "blue_09_02_02_00": (
        _effect(EffectTiming.ON_SUMMON, _guerrerofon_free_magic, condition=_self_source, official_effect="次の青のマジックをコスト0", official_timing="召喚時"),
        _effect(EffectTiming.TURN_START, _guerrerofon_free_magic, condition=_own_turn, official_effect="次の青のマジックをコスト0", official_timing="自分のターン開始時"),
    ),
    "blue_010_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _maelshtrom, template_id="create_tokens", params={"amount": 4}, official_effect="火・水・風・雷のドラゴン・トークンを各1体出す", official_timing="メイン"),),
    "purple_01_02_02_00": (_effect(EffectTiming.ON_DESTROY, _murmur_destroy, target_kind="ally_minion", params={"color": "PURPLE"}, official_effect="自分の紫のミニオンにBP+100", official_timing="破壊時"),),
    "purple_01_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _bad_talk, pre_target_fn=_bad_talk_mill, target_kind="trash_minion", params={"max_cost": 3}, official_effect="上3枚を破棄しコスト3以下のミニオンを回収", official_timing="メイン"),),
    "purple_02_02_02_00": (_effect(EffectTiming.ON_BLESS, _richard_bless, condition=_self_source, official_effect="敵ミニオン破壊時に1枚引く能力をプレイヤーへ付与", official_timing="加護時"),),
    "purple_03_02_02_00": (_effect(EffectTiming.ON_SUMMON, _ante_summon, condition=_self_source, target_kind="other_ally_minion", official_effect="他の自分のミニオンを破壊してBP+200/DP+1", official_timing="召喚時"),),
    "purple_03_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _doomed_road, target_kind="enemy_minion", official_effect="相手にBP-200、自分の紫全てにBP+100", official_timing="メイン/フラッシュ"),),
    "purple_04_02_02_00": (_effect(EffectTiming.ON_SUMMON, _francesca_summon, condition=_self_source, target_kind="pc02_francesca_dragon", min_targets=0, max_targets=1, optional=True, official_effect="紫/無色ドラゴンをトラッシュから回収", official_timing="召喚時"),),
    "purple_06_02_02_00": (_effect(EffectTiming.ON_SUMMON, _gustave_summon, condition=_self_source, official_effect="両トラッシュのFミニオン1枚毎にBP+100", official_timing="召喚時"),),
    "purple_06_03_02_00": (_effect(EffectTiming.ON_CAST_MAGIC, _demons_terror, official_effect="相手のミニオン全てをこのターン攻撃不可", official_timing="フラッシュ"),),
    "purple_09_02_02_00": (_effect(EffectTiming.ON_SUMMON, _skullbone_summon, condition=_self_source, target_kind="enemy_minion", official_effect="相手1体を破壊しそのコスト分デッキ破棄", official_timing="召喚時"),),
    "colorless_00_01_02_02": (_effect(EffectTiming.ON_PLACE_BASE, _cryska_place, condition=_self_source, target_kind="top4_card", params={"card_type": "F_MINION", "race": "ドラゴン"}, official_effect="上4枚からドラゴンFミニオンを手札へ", official_timing="配置時", active_areas=(AreaType.BASE,)),),
    "colorless_02_02_02_00": (_effect(EffectTiming.ON_SUMMON, _scarlet_summon, condition=_self_source, official_effect="加護済みミニオンか加護マナがあれば1枚引く", official_timing="召喚時"),),
    "colorless_03_02_02_00": (_effect(EffectTiming.ON_DESTROY, _dragon_priest_destroy, template_id="create_tokens", params={"amount": 1}, official_effect="ドラゴン・トークンを出す", official_timing="破壊時"),),
    "colorless_03_02_02_01": (_effect(EffectTiming.ON_DESTROY, _gray_blob_destroy, official_effect="相手のミニオン・トークンを全て破壊", official_timing="破壊時"),),
    "colorless_04_02_02_02": (
        _effect(EffectTiming.ON_DAMAGE_PLAYER, _steel_heal, condition=_steel_damage, official_effect="与えたダメージ分プレイヤーを回復", official_timing="アタック時"),
        _effect(EffectTiming.ON_DAMAGE_FORCE, _steel_heal, condition=_steel_damage, official_effect="与えたダメージ分プレイヤーを回復", official_timing="アタック時"),
    ),
    "colorless_05_02_02_01": (_effect(EffectTiming.ON_SUMMON, _monoeye_summon, condition=_self_source, target_kind="pc02_destroy_effect_minion", official_effect="破壊時を持つ相手1体を除外", official_timing="召喚時"),),
    "colorless_05_02_02_03": (_effect(EffectTiming.ON_SUMMON, _hero_error, condition=_self_source, official_effect="相手のコスト8以上を全て破壊", official_timing="召喚時"),),
    "colorless_06_02_02_00": (_effect(EffectTiming.ON_SUMMON, _gilly_heal, condition=_self_source, target_kind="owner_player_or_force", official_effect="自分のプレイヤーかフォースを1回復", official_timing="召喚時"),),
    "colorless_06_02_02_01": (_effect(EffectTiming.ON_SUMMON, _storm_rest, condition=_self_source, target_kind="enemy_minion", params={"max_bp": 400}, official_effect="BP400以下の相手1体をレスト", official_timing="召喚時"),),
    "colorless_07_02_02_01": (
        _effect(EffectTiming.ON_SUMMON, _hagen_summon, condition=_self_source, official_effect="このターンBP+300", official_timing="召喚時"),
        _effect(EffectTiming.ON_ATTACK, _hagen_attack, condition=_self_source, params={"once_per_turn_flag": "turn:pc02_hagen_refresh"}, official_effect="ターンに1回アクティブ", official_timing="アタック時"),
    ),
    "colorless_08_02_02_00": (_effect(EffectTiming.TURN_END, _hydra_end, template_id="create_tokens", params={"amount": 1}, official_effect="ドラゴン・トークンを出す", official_timing="自分のターン終了時"),),
    "colorless_010_02_02_00": (_effect(EffectTiming.ON_SUMMON, _regenerate_summon, condition=_self_source, params={"once_per_turn_flag": "turn:pc02_regenerate_used", "once_per_turn_scope": "owner"}, official_effect="有色マナ全てをアクティブ（同名ターン1回）", official_timing="召喚時"),),
}


_PC02_AURAS_BY_ID = {
    "red_02_02_02_00": _fire_lizard_aura,
    "white_01_02_02_00": _eisen_aura,
    "colorless_04_02_02_00": _obsidian_aura,
}


_PC02_KEYWORD_AURAS_BY_ID = {
    "red_03_02_02_00": _jane_keyword_aura,
}


_PC02_ENGINE_RULE_IDS = {
    *_STANDARD_BLESS_COLORS,
    *_ADVANCED_BLESS_COLORS,
    *_COLORLESS_COST_BLESS_IDS,
    *_UNCONDITIONAL_BLESS_IDS,
    "yellow_04_02_02_01",
    "yellow_06_02_02_00",
    "white_04_02_02_00",
    "white_09_02_02_00",
    "green_03_02_02_00",
    "green_03_02_02_01",
    "green_08_03_02_00",
    "green_09_02_02_00",
    "blue_05_02_02_00",
    "blue_09_02_02_00",
    "purple_05_02_02_01",
    "purple_06_03_02_00",
    "purple_09_02_02_00",
    "colorless_02_02_02_01",
    "colorless_03_02_02_02",
    "colorless_04_02_02_01",
    "colorless_04_02_02_03",
    "colorless_06_02_02_02",
}


_PC02_VANILLA_IDS = {
    "red_06_02_02_00",
    "yellow_03_02_02_00",
    "white_04_02_02_01",
    "green_08_02_02_00",
    "blue_02_02_02_00",
    "purple_05_02_02_00",
    "colorless_07_02_02_00",
}

_PC02_KEYWORD_ONLY_IDS = {"colorless_05_02_02_00"}


_DRAGON_LORD_IDS = {
    "red_09_02_02_00",
    "yellow_09_02_02_00",
    "white_09_02_02_00",
    "green_09_02_02_00",
    "blue_09_02_02_00",
    "purple_09_02_02_00",
}


def mana_value(mana: CardInstance, card_being_paid_for: CardInstance | None, default: int) -> int:
    if (
        mana.card.id == "green_03_02_02_01"
        and mana.area is AreaType.BASE
        and card_being_paid_for is not None
        and card_being_paid_for.card.type is CardType.F_MINION
        and _has_race(card_being_paid_for.card, "ドラゴン")
        and _is_color(card_being_paid_for.card, Color.GREEN, Color.COLORLESS)
    ):
        return 2
    return default


def adjust_effective_cost(
    player: Player,
    card: CardInstance,
    state: Any,
    cost: dict[Color, int],
) -> dict[Color, int]:
    if (
        card.card.id == "green_08_03_02_00"
        and any(_card_color(ci.card) is Color.GREEN and _total_cost(ci.card) >= 7 for ci in player.field)
    ):
        adjusted = dict(cost)
        adjusted.pop(Color.COLORLESS, None)
        return adjusted
    if (
        card.card.type is CardType.MAGIC
        and _card_color(card.card) is Color.BLUE
        and "turn:pc02_next_blue_magic_free" in player.flags
    ):
        return {}
    adjusted = dict(cost)
    if card.card.type is CardType.F_MINION and _has_race(card.card, "デミゴッド"):
        increase = 2 * sum(
            source.card.id == "colorless_02_02_02_01"
            for owner in state.players
            for source in owner.field
        )
        if increase:
            adjusted[Color.COLORLESS] = adjusted.get(Color.COLORLESS, 0) + increase
    if card.card.type in (CardType.B_MINION, CardType.F_MINION) and _has_race(card.card, "ドラゴン"):
        reduction = sum(source.card.id == "colorless_03_02_02_02" for source in player.field)
        adjusted[Color.COLORLESS] = max(0, adjusted.get(Color.COLORLESS, 0) - reduction)
    return {color: amount for color, amount in adjusted.items() if amount > 0}


def consume_cost_override(player: Player, card: CardInstance) -> None:
    if card.card.type is CardType.MAGIC and _card_color(card.card) is Color.BLUE:
        player.flags.discard("turn:pc02_next_blue_magic_free")


def can_use_card(player: Player, card: CardInstance, state: Any) -> bool:
    if card.card.id != "purple_06_03_02_00":
        return True
    return any(_has_race(source.card, "デーモン") for source in player.field)


def can_attack(card: CardInstance) -> bool:
    return "turn:pc02_cannot_attack" not in card.flags


def can_attack_force(attacker: CardInstance) -> bool:
    return attacker.card.id not in {
        FIRE_DRAGON_TOKEN.id,
        WATER_DRAGON_TOKEN.id,
        WIND_DRAGON_TOKEN.id,
        THUNDER_DRAGON_TOKEN.id,
    }


def can_block(attacker: CardInstance, blocker: CardInstance, state: Any) -> bool:
    if attacker.card.id in _DRAGON_LORD_IDS and state.active is attacker.owner:
        return _has_race(blocker.card, "ドラゴン", "ドラゴニュート")
    return True


def can_effect_select(source: CardInstance, target: CardInstance, state: Any) -> bool:
    if source.owner is target.owner:
        return True
    if target.card.id == "white_04_02_02_00" and state.active is not target.owner:
        return False
    if target.card.id == "colorless_06_02_02_02":
        others = [card for card in target.owner.field if card is not target]
        return bool(others)
    return True


def can_effect_select_non_card(source: CardInstance, target: Any, state: Any) -> bool:
    if not isinstance(target, ForceInstance) or source.owner is target.owner or state.active is target.owner:
        return True
    return not any(card.card.id == "colorless_04_02_02_01" for card in target.owner.field)


def battle_outcome_override(
    attacker: CardInstance,
    blocker: CardInstance,
    state: Any,
) -> tuple[bool, bool] | None:
    attacker_wins = attacker.card.id == "yellow_06_02_02_00" or "turn:pc02_always_wins_battle" in attacker.flags
    blocker_wins = "turn:pc02_always_wins_battle" in blocker.flags
    if not attacker_wins and not blocker_wins:
        return None
    return attacker_wins, blocker_wins


def death_blow_active(source: CardInstance, active: Player, state: Any) -> bool:
    if source.owner is active:
        return True
    return any(card.card.id == "purple_05_02_02_01" for card in source.owner.field)


def on_targets_selected(player: Player, source: CardInstance | None, selected: Iterable[Any]) -> None:
    if source is None or source.owner is not player:
        return
    for target in selected:
        if not isinstance(target, CardInstance) or target.card.id != "yellow_04_02_02_01" or not target.rested:
            continue
        marker = "turn:pc02_chohi_refresh"
        if marker not in target.flags:
            target.flags.add(marker)
            target.rested = False


def _place_red_mana_rested(engine: Any, player: Player, source: CardInstance) -> None:
    replace_iid = _base_replacement_iid(engine, player, source)
    if len(player.base) >= 10 and replace_iid is None:
        return
    mana = engine.place_generated_colorless_mana(player, replace_base_iid=replace_iid)
    mana.mana_color_override = Color.RED
    mana.rested = True


def on_base_mana_removed(engine: Any, player: Player, mana: CardInstance, *, reason: str) -> None:
    if reason == "replacement" or engine.state.active is not player:
        return
    leaders = [card for card in player.field if card.card.id == "red_06_02_02_01"]
    if leaders:
        _place_red_mana_rested(engine, player, min(leaders, key=lambda card: card.iid))


def on_mana_moved_to_base(player: Player, mana: CardInstance) -> None:
    if _card_color(mana.card) is Color.BLUE and any(card.card.id == "blue_05_02_02_00" for card in player.field):
        mana.rested = False


def on_damage_resolved(engine: Any, source: Any, target: Any, amount: int) -> None:
    if amount <= 0 or not isinstance(source, CardInstance):
        return
    target_owner = target if isinstance(target, Player) else target.owner
    if "turn:pc02_return_damager" in target_owner.flags and source.owner is not target_owner:
        engine.return_to_hand(source)
    if source.card.id == "white_09_02_02_00" and source.owner is engine.state.active:
        opponent = _opponent(engine.state, source.owner)
        if opponent.field:
            minimum = min(_total_cost(card.card) for card in opponent.field)
            for card in list(opponent.field):
                if _total_cost(card.card) == minimum:
                    _remove_target(engine, card)


def on_minion_destroyed(engine: Any, destroyed: CardInstance) -> None:
    for player in engine.state.players:
        if destroyed.owner is not player and "turn:pc02_draw_enemy_destroy" in player.flags:
            engine.draw(player, 1)


def clear_turn_state(state: Any) -> None:
    for player in state.players:
        player.flags = {flag for flag in player.flags if not flag.startswith("turn:pc02_")}


def _pc02_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("pack_jp_official") == PC02_PACK_JP
        ]
    rows.sort(key=lambda row: int(row.get("official_order") or 999999))
    return rows


def _pc02_card_from_row(row: dict[str, str]) -> Card:
    card = _card_from_row(row)
    bless_ids = (
        set(_STANDARD_BLESS_COLORS)
        | set(_ADVANCED_BLESS_COLORS)
        | _COLORLESS_COST_BLESS_IDS
        | _UNCONDITIONAL_BLESS_IDS
    )
    if card.id in bless_ids and Keyword.KAGO not in card.keywords:
        card.keywords.append(Keyword.KAGO)
    card.effects = list(card.effects) + list(_PC02_EFFECTS_BY_ID.get(card.id, ()))
    card.aura = _PC02_AURAS_BY_ID.get(card.id, card.aura)
    card.keyword_aura = _PC02_KEYWORD_AURAS_BY_ID.get(card.id, card.keyword_aura)
    return card


def register_pc02_cards(path: Path = DEFAULT_CARD_TSV) -> list[str]:
    rows = _pc02_rows(path)
    registered_ids: list[str] = []
    for row in rows:
        card = _pc02_card_from_row(row)
        if card.id not in CARD_REGISTRY:
            register(card)
        registered_ids.append(card.id)
    behavior_ids = (
        set(_PC02_EFFECTS_BY_ID)
        | set(_PC02_AURAS_BY_ID)
        | set(_PC02_KEYWORD_AURAS_BY_ID)
        | _PC02_ENGINE_RULE_IDS
        | _PC02_VANILLA_IDS
        | _PC02_KEYWORD_ONLY_IDS
    )
    missing = set(registered_ids) - behavior_ids
    extra = behavior_ids - set(registered_ids)
    if len(registered_ids) != 100 or len(set(registered_ids)) != 100 or missing or extra:
        raise RuntimeError(
            f"PC02 inventory/behavior mismatch: rows={len(registered_ids)} unique={len(set(registered_ids))} "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    return registered_ids


PC02_CARD_IDS = register_pc02_cards()
