from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable

from zz.cards import CARD_REGISTRY, register
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color, Keyword, Step
from zz.model import Card, CardInstance, Context, ForceInstance, Player
from zz.pc01 import DEFAULT_CARD_TSV, _card_from_row


PC01R_PACK_JP = "PC:01R BEYOND"


def _effect(
    timing: EffectTiming,
    fn: Callable[[CardInstance, Any, Context], None],
    *,
    condition: Callable[[CardInstance, Any, Context], bool] | None = None,
    target_kind: str | None = None,
    min_targets: int = 1,
    max_targets: int = 1,
    optional: bool = False,
    params: dict[str, Any] | None = None,
    official_effect: str,
    official_timing: str,
    official_condition: str | None = None,
    active_areas: tuple[AreaType, ...] | None = None,
) -> EffectSpec:
    return EffectSpec(
        timing=timing,
        fn=fn,
        condition=condition,
        target_kind=target_kind,
        min_targets=min_targets,
        max_targets=max_targets,
        optional=optional,
        params=dict(params or {}),
        official_effect=official_effect,
        official_timing=official_timing,
        official_condition=official_condition,
        active_areas=active_areas,
    )


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


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


def _has_demigod(player: Player) -> bool:
    return any(_has_race(ci.card, "デミゴッド") for ci in player.field)


def _is_colored(card: Card) -> bool:
    return _card_color(card) is not Color.COLORLESS


def _demigod_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source.area is AreaType.FIELD and target is source and _has_demigod(source.owner):
        return 200, 1
    return 0, 0


def _rose_keyword_aura(source: CardInstance, target: CardInstance, state: Any) -> list[Keyword]:
    if (
        source.area is AreaType.FIELD
        and state.active is source.owner
        and target.owner is source.owner
        and target.area is AreaType.FIELD
        and _has_race(target.card, "マーフォーク")
    ):
        return [Keyword.SNEAKING]
    return []


# Engine-owned continuous rules call these small, pure hooks. Keeping the card
# predicates here prevents card-set IDs from spreading through the core engine.
def free_cost_delta(player: Player, card: CardInstance, state: Any) -> int:
    delta = 0
    if card.card.type is CardType.MAGIC:
        delta -= sum(
            1
            for source in player.field
            if source.card.id == "blue_02_02_01r_01" and source.area is AreaType.FIELD
        )
        if "turn:pc01r_opponent_magic_plus3" in player.flags:
            delta += 3
    if (
        card.card.id == "colorless_06_02_01r_00"
        and state.active is player
        and card.area is AreaType.HAND
        and _has_demigod(player)
    ):
        delta -= 3
    return delta


def mana_value(mana: CardInstance, card_being_paid_for: CardInstance | None) -> int:
    if (
        mana.card.id == "green_05_02_01r_00"
        and mana.area is AreaType.BASE
        and card_being_paid_for is not None
        and _card_color(card_being_paid_for.card) is Color.GREEN
    ):
        return 3
    return 1


def can_attack_or_move(card: CardInstance) -> bool:
    return "pc01r:locked_until_owner_turn_end" not in card.flags


def can_block(attacker: CardInstance, blocker: CardInstance, state: Any) -> bool:
    if "pc01r:locked_until_owner_turn_end" in blocker.flags:
        return False
    if (
        attacker.card.id == "colorless_05_02_01r_00"
        and state.active is attacker.owner
        and _is_colored(blocker.card)
    ):
        return False
    return True


def can_effect_select(source: CardInstance, target: CardInstance) -> bool:
    if source.card.type is not CardType.MAGIC or source.owner is target.owner:
        return True
    return "turn:pc01r_opponent_magic_immune" not in target.flags


def battle_outcome_override(attacker: CardInstance, blocker: CardInstance) -> tuple[bool, bool] | None:
    attacker_wins = "turn:pc01r_always_wins_battle" in attacker.flags
    blocker_wins = "turn:pc01r_always_wins_battle" in blocker.flags
    if not attacker_wins and not blocker_wins:
        return None
    return attacker_wins, blocker_wins


def battle_win_damage_enabled(player: Player) -> bool:
    return "turn:pc01r_battle_win_damage" in player.flags


def adjust_minion_dp_damage(state: Any, amount: int, source: Any) -> int:
    if not isinstance(source, CardInstance) or source.card.type not in (CardType.B_MINION, CardType.F_MINION):
        return amount
    if _total_cost(source.card) > 3:
        return amount
    reduction = sum(
        1
        for player in state.players
        for card in player.field
        if card.card.id == "colorless_02_02_01r_00" and card.area is AreaType.FIELD
    )
    return max(0, amount - reduction)


def clear_owner_turn_end_locks(player: Player) -> None:
    for zone in (player.field, player.base, player.hand, player.trash, player.removed):
        for card in zone:
            card.flags.discard("pc01r:locked_until_owner_turn_end")


def _set_next_red_rush(source: CardInstance, state: Any, ctx: Context) -> None:
    source.owner.flags.add("turn:pc01r_next_red_summon_rush")


def _grant_next_red_rush(source: CardInstance, state: Any, ctx: Context) -> None:
    summoned = ctx.source
    if not isinstance(summoned, CardInstance) or summoned.owner is not source.owner:
        return
    if _card_color(summoned.card) is not Color.RED:
        return
    marker = "turn:pc01r_next_red_summon_rush"
    if marker not in source.owner.flags:
        return
    source.owner.flags.remove(marker)
    state.engine.add_keyword(summoned, Keyword.RUSH)
    summoned.summoning_sickness = False


def _draw_destroyed_enemy_forces(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, sum(force.destroyed for force in _opponent(state, source.owner).forces))


def _buff_penetrate_minion(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: eng.has_keyword(target, Keyword.PENETRATE),
        source=source,
    )
    for target in targets:
        eng.modify_stat(target, bp_delta=100, dp_delta=1, duration="permanent")


def _move_ally_to_base_preserving_rest(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(source.owner, "ally_minion", 0, 1, source=source)
    if not targets:
        return
    target = targets[0]
    if not eng.move_target_to_base_asking_owner(target, rested=target.rested, source=source):
        return


def _mark_must_block(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 0, 1, source=source)
    if targets:
        targets[0].flags.add("turn:must_block")


def _buff_by_token_count(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if targets:
        amount = 100 * sum(card.card.is_token for card in source.owner.field)
        eng.modify_stat(targets[0], bp_delta=amount, duration="permanent")


def _flame_karman_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=100, duration="permanent")


def _attacks_player(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and isinstance(ctx.target, Player) and ctx.target is not source.owner


def _copy_other_non_token(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "any_minion",
        1,
        1,
        filter_fn=lambda target: target is not source and not target.card.is_token,
        source=source,
    )
    if not targets:
        return
    copied = CardInstance(
        card=targets[0].card,
        owner=source.owner,
        iid=state.allocate_iid(),
        area=AreaType.REMOVED,
    )
    eng.add_to_hand(source.owner, copied, from_area=AreaType.REMOVED)


def _increase_opponent_magic_cost(source: CardInstance, state: Any, ctx: Context) -> None:
    _opponent(state, source.owner).flags.add("turn:pc01r_opponent_magic_plus3")


def _refresh_yellow_cost_six(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: _card_color(target.card) is Color.YELLOW and _total_cost(target.card) >= 6,
        source=source,
    )
    for target in targets:
        target.rested = False


def _other_ally_entered(source: CardInstance, state: Any, ctx: Context) -> bool:
    entered = ctx.source
    return (
        isinstance(entered, CardInstance)
        and entered is not source
        and entered.owner is source.owner
        and entered.area is AreaType.FIELD
    )


def _ape_growth(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=100, duration="permanent")


def _lock_enemy_minion(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if targets:
        targets[0].flags.add("pc01r:locked_until_owner_turn_end")


def _return_enemy_to_hand(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        state.engine.return_to_hand(target)


def _refresh_own_color_minion(color: Color) -> Callable[[CardInstance, Any, Context], None]:
    def fn(source: CardInstance, state: Any, ctx: Context) -> None:
        targets = state.engine.select_target(
            source.owner,
            "ally_minion",
            1,
            1,
            filter_fn=lambda target: _card_color(target.card) is color,
            source=source,
        )
        for target in targets:
            target.rested = False

    return fn


def _return_all_minions(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    for player in state.players:
        for target in list(player.field):
            eng.return_to_hand(target)


def _damage_one_enemy_force(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_force", 1, 1, source=source)
    for target in targets:
        state.engine._damage_force(target, 1, source=source)


def _destroy_ally_draw_two(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if not targets:
        return
    target = targets[0]
    eng.destroy_target(target, source)
    if target.area is not AreaType.FIELD:
        eng.draw(source.owner, 2)


def _mill_top_five(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.mill_deck(source.owner, 5, source=source)


def _kiska_is_active_listener(source: CardInstance, state: Any, ctx: Context) -> bool:
    if state.active is not source.owner or source.area is not AreaType.FIELD:
        return False
    leaders = [
        card
        for card in source.owner.field
        if card.card.id == source.card.id and card.area is AreaType.FIELD
    ]
    return bool(leaders) and source.iid == min(card.iid for card in leaders)


def _resolve_first_milled_purple_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    milled = ctx.target if isinstance(ctx.target, list) else []
    for card in milled:
        if _card_color(card.card) is not Color.PURPLE:
            continue
        destroy_effects = [effect for effect in card.card.effects if effect.timing is EffectTiming.ON_DESTROY]
        if not destroy_effects:
            continue
        destroy_ctx = Context(controller=source.owner, source=source, target=card)
        state.engine._resolve_source_effects(card, EffectTiming.ON_DESTROY, destroy_ctx)
        return


def _destroy_rested_bp_400(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "any_minion",
        1,
        1,
        filter_fn=lambda target: target.rested and eng.effective_bp(target) <= 400,
        source=source,
    )
    for target in targets:
        eng.destroy_target(target, source)


def _refresh_green_mana(amount: int) -> Callable[[CardInstance, Any, Context], None]:
    def fn(source: CardInstance, state: Any, ctx: Context) -> None:
        targets = state.engine.select_target(
            source.owner,
            "ally_base",
            amount,
            amount,
            filter_fn=lambda target: state.engine._mana_color_of(target) is Color.GREEN,
            source=source,
        )
        for target in targets:
            target.rested = False

    return fn


def _set_enemy_dp_zero(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        eng.modify_stat(target, dp_delta=-eng.effective_dp(target))


def _scarel_trigger(source: CardInstance, state: Any, ctx: Context) -> bool:
    placed = ctx.source
    if state.step is not Step.MANA or state.active is not source.owner:
        return False
    if not isinstance(placed, CardInstance) or placed.owner is not source.owner:
        return False
    if placed.card.id != "green_00_01_00_00":
        return False
    copies = [card for card in source.owner.field if card.card.id == source.card.id]
    return bool(copies) and source.iid == min(card.iid for card in copies)


def _rest_enemy_and_forces(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        eng.rest_target(target)
    for force in _opponent(state, source.owner).forces:
        if not force.destroyed:
            eng.rest_target(force)


def _rest_enemy_minion_or_force(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion_or_force", 1, 1, source=source)
    for target in targets:
        state.engine.rest_target(target)


def _ward_viper_draw(source: CardInstance, state: Any, ctx: Context) -> None:
    if len(source.owner.hand) <= 4:
        state.engine.draw(source.owner, 1)


def _move_minion_mana_to_field(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(source.owner, "ally_minion_base", 1, 1, source=source)
    if not targets:
        return
    replace_iid = None
    if len(source.owner.field) >= 5:
        replacements = eng.select_target(source.owner, "ally_minion", 1, 1, source=source)
        if not replacements:
            return
        replace_iid = replacements[0].iid
    eng.move_base_minion_to_field(source.owner, targets[0], rested=False, replace_field_iid=replace_iid)


def _howling_voice(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "enemy_minion_bp_at_most_500_or_opponent_player",
        1,
        1,
        source=source,
    )
    if not targets:
        return
    target = targets[0]
    if isinstance(target, Player):
        eng._damage_player(target, 1, source=source)
        return
    if not eng.move_target_to_base_asking_owner(target, rested=True, source=source):
        return


def _put_blue_minion_rested(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "hand_card",
        0,
        1,
        filter_fn=lambda target: target.card.type is CardType.F_MINION and _card_color(target.card) is Color.BLUE,
        source=source,
    )
    if not targets:
        return
    replace_iid = eng.select_base_replacement_iid(source.owner, source)
    if len(source.owner.base) >= 10 and replace_iid is None:
        return
    eng.put_base_minion_from_hand(
        source.owner,
        targets[0],
        rested=True,
        replace_base_iid=replace_iid,
    )


def _protect_one_from_magic(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    for target in targets:
        target.flags.add("turn:pc01r_opponent_magic_immune")


def _refresh_all_on_opponent_turn(source: CardInstance, state: Any, ctx: Context) -> None:
    if state.active is source.owner:
        return
    for target in source.owner.field:
        target.rested = False
    for force in source.owner.forces:
        if not force.destroyed:
            force.rested = False


def _grant_soldier_auto_win(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: _has_race(target.card, "ソルジャー"),
        source=source,
    )
    for target in targets:
        target.flags.add("turn:pc01r_always_wins_battle")


def _dimensional_crack(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in list(source.owner.field):
        state.engine.modify_stat(target, bp_delta=100, duration="permanent")
    source.owner.flags.add("turn:pc01r_battle_win_damage")


def _rest_force_refresh_self(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_force",
        0,
        1,
        filter_fn=lambda force: not force.rested,
        source=source,
    )
    if targets:
        targets[0].rested = True
        source.rested = False


def _protect_all_from_magic(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in source.owner.field:
        target.flags.add("turn:pc01r_opponent_magic_immune")


def _city_resident(source: CardInstance, state: Any, ctx: Context) -> None:
    source.rested = True
    targets = state.engine.select_target(
        source.owner,
        "trash_magic_cost_at_most_4",
        1,
        1,
        filter_fn=lambda target: _total_cost(target.card) <= 3,
        source=source,
    )
    for target in targets:
        state.engine.add_to_hand(source.owner, target, from_area=AreaType.TRASH)


def _porin_draw_condition(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or not source.owner.base:
        return False
    return all(
        card.card.type is CardType.MANA_TOKEN and state.engine._mana_color_of(card) is Color.COLORLESS
        for card in source.owner.base
    )


def _search_cost_two_magic(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "deck_card",
        1,
        1,
        filter_fn=lambda target: target.card.type is CardType.MAGIC and _total_cost(target.card) == 2,
        source=source,
    )
    if targets:
        target = targets[0]
        source.owner.deck.remove(target)
        eng.reveal_card(source.owner, target, "deck_search")
        eng.add_to_hand(source.owner, target, from_area=AreaType.DECK)
    eng.rng.shuffle(source.owner.deck)


def _platona_redraw(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    selected = eng.select_target(
        source.owner,
        "hand_card",
        0,
        len(source.owner.hand),
        source=source,
    )
    discarded: list[CardInstance] = []
    for target in selected:
        if target in source.owner.hand:
            eng.discard_from_hand(source.owner, target)
            discarded.append(target)
    eng.draw(source.owner, len(discarded))
    eng.rng.shuffle(discarded)
    for target in discarded:
        if target in source.owner.trash:
            source.owner.trash.remove(target)
        target.area = AreaType.DECK
        source.owner.deck.append(target)
        eng._record_zone_move(target, AreaType.TRASH, AreaType.DECK)


def _hidden_wolf_growth(source: CardInstance, state: Any, ctx: Context) -> None:
    amount = 100 * len(_opponent(state, source.owner).field)
    state.engine.modify_stat(source, bp_delta=amount, duration="permanent")


def _opponent_magic_used(source: CardInstance, state: Any, ctx: Context) -> bool:
    used = ctx.source
    return (
        isinstance(used, CardInstance)
        and used.owner is not source.owner
        and used.card.type is CardType.MAGIC
    )


def _puma_growth(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=100, dp_delta=1, duration="permanent")


def _put_cost_six_from_hand(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "hand_card",
        1,
        1,
        filter_fn=lambda target: target.card.type is CardType.F_MINION and _total_cost(target.card) <= 6,
        source=source,
    )
    if not targets:
        return
    replace_iid = None
    if len(source.owner.field) >= 5:
        replacements = eng.select_target(source.owner, "ally_minion", 1, 1, source=source)
        if not replacements:
            return
        replace_iid = replacements[0].iid
    eng.put_field_minion_from_hand(source.owner, targets[0], replace_field_iid=replace_iid)


def _gorgon_turn_end(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.controller is not source.owner:
        return
    for player in state.players:
        for target in list(player.field):
            if not _has_race(target.card, "モンスター"):
                state.engine.modify_stat(target, bp_delta=-200, duration="permanent")


def _bald_lord(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    targets = eng.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: eng.effective_bp(target) <= 1200,
        source=source,
    )
    for target in targets:
        eng.destroy_target(target, source)
    for force in source.owner.forces:
        if not force.destroyed:
            eng._damage_force(force, 1, source=source)


def _kirin_damage(source: CardInstance, state: Any, ctx: Context) -> None:
    amount = sum(_has_race(card.card, "ビースト", "ファイブスター") for card in source.owner.field)
    if amount:
        state.engine._damage_player(_opponent(state, source.owner), amount, source=source)


_PC01R_EFFECTS_BY_ID: dict[str, tuple[EffectSpec, ...]] = {
    "red_00_01_01r_00": (
        _effect(EffectTiming.ON_PLACE_BASE, _set_next_red_rush, condition=_self_source, official_effect="次に召喚する赤のミニオンに襲撃", official_timing="配置時", active_areas=(AreaType.BASE,)),
        _effect(EffectTiming.ON_SUMMON, _grant_next_red_rush, official_effect="次の赤ミニオンへ襲撃を付与", official_timing="召喚時", active_areas=(AreaType.BASE,)),
    ),
    "red_01_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _buff_by_token_count, target_kind="ally_minion", params={"token_count_multiplier": 100}, official_effect="ミニオン・トークン1体毎にBP+100を付与", official_timing="メイン/フラッシュ"),),
    "red_02_02_01r_00": (_effect(EffectTiming.ON_ATTACK, _flame_karman_attack, condition=_attacks_player, official_effect="BP+100を付与", official_timing="アタック時", official_condition="プレイヤーにアタック"),),
    "red_02_03_01r_00": (build_effect("grant_keyword", EffectTiming.ON_CAST_MAGIC, target_kind="enemy_minion", keyword=Keyword.CANNOT_BLOCK, min_bp=500, duration="turn", official_effect="ブロックできない", official_timing="メイン/フラッシュ"),),
    "red_03_02_01r_00": (build_effect("create_tokens", EffectTiming.MOVE_TO_BASE, condition=_self_source, amount=1, token_id="s_golem_token", name_jp="S・ゴレイム・トークン", color=Color.RED, cost=1, bp=100, dp=1, race_jp="ゴレイム"),),
    "red_04_02_01r_00": (_effect(EffectTiming.ON_SUMMON, _copy_other_non_token, condition=_self_source, target_kind="any_minion", params={"exclude_source": True, "exclude_tokens": True}, official_effect="同じカード1枚を手札に加える", official_timing="召喚時"),),
    "red_05_03_01r_00": (build_effect("stat_modifier", EffectTiming.ON_CAST_MAGIC, target_kind="enemy_minion", bp_delta=-500, duration="permanent"),),
    "red_07_02_01r_00": (
        build_effect("stat_modifier", EffectTiming.ON_ATTACK, condition=_self_source, target_kind="enemy_minion", bp_delta=-300, duration="turn"),
        build_effect("create_tokens", EffectTiming.MOVE_TO_BASE, condition=_self_source, amount=2, token_id="s_golem_token", name_jp="S・ゴレイム・トークン", color=Color.RED, cost=1, bp=100, dp=1, race_jp="ゴレイム"),
    ),
    "yellow_00_01_01r_00": (build_effect("stat_modifier_all", EffectTiming.ON_PLACE_BASE, condition=_self_source, target_kind="ally_minion", bp_delta=100, duration="turn", applies_to_future=True),),
    "yellow_01_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _increase_opponent_magic_cost, official_effect="相手のマジックのフリーコストを3増やす", official_timing="メイン/フラッシュ"),),
    "yellow_02_02_01r_00": (_effect(EffectTiming.MOVE_TO_BASE, _refresh_yellow_cost_six, condition=_self_source, target_kind="ally_minion", params={"color": Color.YELLOW.name, "min_cost": 6}, official_effect="コスト6以上の黄のミニオンをアクティブ", official_timing="後退時", active_areas=(AreaType.BASE,)),),
    "yellow_03_03_01r_00": (build_effect("stat_modifier", EffectTiming.ON_CAST_MAGIC, target_kind="ally_minion", bp_delta=200, dp_delta=1, duration="permanent"),),
    "yellow_05_02_01r_00": (_effect(EffectTiming.ON_ENTER_FIELD, _ape_growth, condition=_other_ally_entered, official_effect="BP+100を付与", official_timing="他の自分のミニオンがフィールドに出るたび"),),
    "yellow_06_02_01r_00": (_effect(EffectTiming.ON_SUMMON, _lock_enemy_minion, condition=_self_source, target_kind="enemy_minion", official_effect="アタック・ブロック・移動できない", official_timing="召喚時", official_condition="次の相手のターン終了時まで"),),
    "yellow_06_02_01r_01": (
        _effect(EffectTiming.ON_DESTROY, _return_enemy_to_hand, target_kind="enemy_minion", official_effect="手札に戻す", official_timing="破壊時"),
        _effect(EffectTiming.MOVE_TO_BASE, _refresh_own_color_minion(Color.YELLOW), condition=_self_source, target_kind="ally_minion", params={"color": Color.YELLOW.name}, official_effect="黄のミニオンをアクティブ", official_timing="後退時", active_areas=(AreaType.BASE,)),
    ),
    "yellow_07_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _return_all_minions, official_effect="全てのミニオンを持ち主の手札に戻す", official_timing="メイン"),),
    "purple_00_01_01r_00": (_effect(EffectTiming.ON_PLACE_BASE, _draw_destroyed_enemy_forces, condition=_self_source, official_effect="相手の破壊されたフォース1つ毎に1枚引く", official_timing="配置時", active_areas=(AreaType.BASE,)),),
    "purple_02_02_01r_00": (_effect(EffectTiming.ON_DESTROY, _damage_one_enemy_force, target_kind="enemy_force", official_effect="相手のフォースに1ダメージ", official_timing="破壊時"),),
    "purple_03_02_01r_00": (build_effect("stat_modifier", EffectTiming.MOVE_TO_BASE, condition=_self_source, target_kind="enemy_minion", bp_delta=-200, duration="permanent"),),
    "purple_03_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _destroy_ally_draw_two, target_kind="ally_minion", official_effect="自分のミニオンを破壊して2枚引く", official_timing="メイン/フラッシュ"),),
    "purple_04_03_01r_00": (build_effect("destroy_targets", EffectTiming.ON_CAST_MAGIC, target_kind="any_minion", all_targets=True, max_cost=3),),
    "purple_06_02_01r_00": (
        _effect(EffectTiming.ON_SUMMON, _mill_top_five, condition=_self_source, official_effect="デッキを上から5枚破棄", official_timing="召喚時"),
        _effect(EffectTiming.ON_DECK_DISCARD, _resolve_first_milled_purple_destroy, condition=_kiska_is_active_listener, official_effect="最初の紫の破壊時効果を発揮", official_timing="自分のターン", official_condition="デッキからカードが破棄されたとき・重複しない"),
    ),
    "purple_07_02_01r_00": (
        build_effect("create_tokens", EffectTiming.ON_DESTROY, amount=3, token_id="s_aryushinashion_token", name_jp="S・アリュシナシオン・トークン", color=Color.PURPLE, cost=2, bp=200, dp=1, race_jp="スケルトン", keywords=(Keyword.DEATH_BLOW,), optional=True),
        build_effect("stat_modifier", EffectTiming.MOVE_TO_BASE, condition=_self_source, target_kind="enemy_minion", bp_delta=-400, duration="permanent"),
    ),
    "purple_07_03_01r_00": (build_effect("summon_from_trash", EffectTiming.ON_CAST_MAGIC, target_kind="trash_field_minion"),),
    "green_00_01_01r_00": (_effect(EffectTiming.ON_PLACE_BASE, _buff_penetrate_minion, condition=_self_source, target_kind="ally_minion", params={"required_keyword": Keyword.PENETRATE.name}, official_effect="貫通を持つミニオンにBP+100/DP+1を付与", official_timing="配置時", active_areas=(AreaType.BASE,)),),
    "green_01_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _destroy_rested_bp_400, target_kind="any_minion", params={"only_rested": True, "max_bp": 400}, official_effect="レスト状態のBP400以下を破壊", official_timing="メイン"),),
    "green_02_02_01r_00": (_effect(EffectTiming.MOVE_TO_BASE, _refresh_green_mana(1), condition=_self_source, target_kind="ally_base", params={"color": Color.GREEN.name}, official_effect="緑マナ1つをアクティブ", official_timing="後退時", active_areas=(AreaType.BASE,)),),
    "green_02_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _set_enemy_dp_zero, target_kind="enemy_minion", official_effect="DPを0にする", official_timing="フラッシュ"),),
    "green_03_02_01r_00": (build_effect("draw_cards", EffectTiming.ON_PLACE_BASE, condition=_scarel_trigger, amount=1, active_areas=(AreaType.FIELD,)),),
    "green_03_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _rest_enemy_and_forces, target_kind="enemy_minion", official_effect="相手のミニオン1体とフォース全てをレスト", official_timing="メイン/フラッシュ"),),
    "green_05_02_01r_00": (build_effect("move_to_base_rested", EffectTiming.MOVE_TO_BASE, condition=_self_source),),
    "green_07_02_01r_00": (
        _effect(EffectTiming.ON_ATTACK, _rest_enemy_minion_or_force, condition=_self_source, target_kind="enemy_minion_or_force", official_effect="相手のミニオンかフォースをレスト", official_timing="アタック時"),
        _effect(EffectTiming.MOVE_TO_BASE, _refresh_green_mana(2), condition=_self_source, target_kind="ally_base", min_targets=2, max_targets=2, params={"color": Color.GREEN.name}, official_effect="緑マナ2つをアクティブ", official_timing="後退時", active_areas=(AreaType.BASE,)),
    ),
    "blue_00_01_01r_00": (_effect(EffectTiming.ON_PLACE_BASE, _move_ally_to_base_preserving_rest, condition=_self_source, target_kind="ally_minion", min_targets=0, max_targets=1, optional=True, params={"moves_targets_to_base": True}, official_effect="自分のミニオンをベースに移動", official_timing="配置時", active_areas=(AreaType.BASE,)),),
    "blue_01_03_01r_00": (build_effect("look_top_to_hand", EffectTiming.ON_CAST_MAGIC, target_kind="top4_card", top_n=4, card_type=CardType.MAGIC),),
    "blue_02_02_01r_00": (_effect(EffectTiming.MOVE_TO_BASE, _ward_viper_draw, condition=_self_source, official_effect="手札4枚以下なら1枚引く", official_timing="後退時", active_areas=(AreaType.BASE,)),),
    "blue_03_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _move_minion_mana_to_field, target_kind="ally_minion_base", official_effect="ミニオンであるマナをフィールドにアクティブで移動", official_timing="メイン/フラッシュ"),),
    "blue_05_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _howling_voice, target_kind="enemy_minion_bp_at_most_500_or_opponent_player", params={"moves_targets_to_base": True}, official_effect="BP500以下をベースへ移動またはプレイヤーに1ダメージ", official_timing="フラッシュ"),),
    "blue_06_02_01r_00": (_effect(EffectTiming.ON_SUMMON, _put_blue_minion_rested, condition=_self_source, target_kind="hand_card", min_targets=0, max_targets=1, optional=True, params={"card_type": CardType.F_MINION.value, "color": Color.BLUE.name, "exclude_source": True, "puts_targets_on_base": True}, official_effect="青のフィールド・ミニオンをレスト状態で置く", official_timing="召喚時"),),
    "blue_08_02_01r_00": (build_effect("draw_cards", EffectTiming.MOVE_TO_BASE, condition=_self_source, amount=2),),
    "white_00_01_01r_00": (_effect(EffectTiming.ON_PLACE_BASE, _mark_must_block, condition=_self_source, target_kind="enemy_minion", min_targets=0, max_targets=1, optional=True, official_effect="このターン中必ずブロック", official_timing="配置時", active_areas=(AreaType.BASE,)),),
    "white_02_02_01r_00": (_effect(EffectTiming.MOVE_TO_BASE, _protect_one_from_magic, condition=_self_source, target_kind="ally_minion", official_effect="相手のマジックの効果で選択できない", official_timing="後退時", active_areas=(AreaType.BASE,)),),
    "white_02_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _refresh_all_on_opponent_turn, official_effect="自分のミニオンとフォース全てをアクティブ", official_timing="フラッシュ", official_condition="相手のターン"),),
    "white_02_03_01r_01": (_effect(EffectTiming.ON_CAST_MAGIC, _grant_soldier_auto_win, target_kind="ally_minion", params={"race": "ソルジャー"}, official_effect="BPに関係なくバトルに勝利", official_timing="メイン/フラッシュ"),),
    "white_04_02_01r_00": (build_effect("force_block", EffectTiming.ON_ATTACK, condition=_self_source),),
    "white_04_03_01r_00": (_effect(EffectTiming.ON_CAST_MAGIC, _dimensional_crack, official_effect="全ミニオンにBP+100を付与しバトル勝利毎に1ダメージ", official_timing="メイン"),),
    "white_06_02_01r_00": (
        _effect(EffectTiming.ON_ATTACK, _rest_force_refresh_self, condition=_self_source, target_kind="ally_force", min_targets=0, max_targets=1, optional=True, params={"only_active": True}, official_effect="フォースをレストして自身をアクティブ", official_timing="アタック時"),
        _effect(EffectTiming.ON_BLOCK, _rest_force_refresh_self, condition=_self_source, target_kind="ally_force", min_targets=0, max_targets=1, optional=True, params={"only_active": True}, official_effect="フォースをレストして自身をアクティブ", official_timing="ブロック時"),
    ),
    "white_07_02_01r_00": (
        build_effect("rest_targets", EffectTiming.ON_BATTLE_WIN, condition=_self_source, target_kind="enemy_minion"),
        _effect(EffectTiming.MOVE_TO_BASE, _protect_all_from_magic, condition=_self_source, official_effect="全ミニオンを相手のマジックの対象に選べない", official_timing="後退時", active_areas=(AreaType.BASE,)),
    ),
    "colorless_00_01_01r_00": (_effect(EffectTiming.ON_PLACE_BASE, _city_resident, condition=_self_source, target_kind="trash_magic_cost_at_most_4", params={"max_cost": 3}, official_effect="自身をレストしコスト3以下のマジックを回収", official_timing="配置時", active_areas=(AreaType.BASE,)),),
    "colorless_00_01_01r_01": (build_effect("rest_targets", EffectTiming.ON_PLACE_BASE, condition=_self_source, target_kind="enemy_minion_cost_at_most_4"),),
    "colorless_01_02_01r_00": (
        build_effect("draw_cards", EffectTiming.ON_SUMMON, condition=_porin_draw_condition, amount=1, official_condition="ベースにミニオンでない無色マナしかない"),
        build_effect("move_to_base_rested", EffectTiming.MOVE_TO_BASE, condition=_self_source),
    ),
    "colorless_03_02_01r_00": (build_effect("stat_modifier", EffectTiming.ON_SUMMON, condition=_self_source, target_kind="enemy_minion", bp_delta=-200, duration="permanent"),),
    "colorless_03_02_01r_01": (_effect(EffectTiming.ON_SUMMON, _search_cost_two_magic, condition=_self_source, target_kind="deck_card", params={"card_type": CardType.MAGIC.value, "min_cost": 2, "max_cost": 2}, official_effect="コスト2のマジックを公開して手札に加えシャッフル", official_timing="召喚時"),),
    "colorless_03_02_01r_02": (_effect(EffectTiming.ON_SUMMON, _platona_redraw, condition=_self_source, target_kind="hand_card", min_targets=0, max_targets=10, optional=True, params={"exclude_source": True}, official_effect="好きな枚数破棄し同じ枚数引いて破棄札をデッキ下へ", official_timing="召喚時"),),
    "colorless_04_02_01r_00": (_effect(EffectTiming.ON_SUMMON, _hidden_wolf_growth, condition=_self_source, official_effect="相手のミニオン1体毎にBP+100を付与", official_timing="召喚時"),),
    "colorless_05_02_01r_01": (_effect(EffectTiming.ON_CARD_USED, _puma_growth, condition=_opponent_magic_used, official_effect="BP+100/DP+1を付与", official_timing="相手がマジックを使用するたび"),),
    "colorless_06_02_01r_01": (_effect(EffectTiming.MOVE_TO_BASE, _put_cost_six_from_hand, condition=_self_source, target_kind="hand_card", params={"card_type": CardType.F_MINION.value, "max_cost": 6, "puts_targets_on_field": True}, official_effect="本来のコスト6以下を手札から置く", official_timing="後退時", active_areas=(AreaType.BASE,)),),
    "colorless_07_02_01r_01": (_effect(EffectTiming.TURN_END, _gorgon_turn_end, official_effect="モンスターでない全ミニオンにBP-200を付与", official_timing="自分のターン終了時"),),
    "colorless_07_02_01r_02": (_effect(EffectTiming.ON_SUMMON, _bald_lord, condition=_self_source, target_kind="enemy_minion", params={"max_bp": 1200}, official_effect="BP1200以下を破壊し自分の全フォースに1ダメージ", official_timing="召喚時"),),
    "colorless_010_02_01r_00": (_effect(EffectTiming.ON_SUMMON, _kirin_damage, condition=_self_source, official_effect="ビースト/ファイブスター数と同じダメージ", official_timing="召喚時"),),
}


_PC01R_AURAS_BY_ID = {
    "red_05_02_01r_00": _demigod_aura,
    "yellow_04_02_01r_00": _demigod_aura,
    "purple_04_02_01r_00": _demigod_aura,
    "green_06_02_01r_00": _demigod_aura,
    "blue_05_02_01r_00": _demigod_aura,
    "white_03_02_01r_00": _demigod_aura,
}


_PC01R_KEYWORD_AURAS_BY_ID = {
    "blue_08_02_01r_00": _rose_keyword_aura,
}


_ENGINE_RULE_IDS = {
    "blue_02_02_01r_01",
    "green_05_02_01r_00",
    "colorless_02_02_01r_00",
    "colorless_05_02_01r_00",
    "colorless_06_02_01r_00",
    "colorless_07_02_01r_00",
}


_PC01R_COST_OVERRIDES = {
    "red_04_02_01r_00": {Color.RED: 2, Color.COLORLESS: 2},
    "red_05_03_01r_00": {Color.RED: 2, Color.COLORLESS: 3},
    "white_04_02_01r_00": {Color.WHITE: 2, Color.COLORLESS: 2},
    "white_06_02_01r_00": {Color.WHITE: 2, Color.COLORLESS: 4},
}


def _pc01r_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("pack_jp_official") == PC01R_PACK_JP
        ]
    rows.sort(key=lambda row: int(row.get("official_order") or 999999))
    return rows


def _pc01r_card_from_row(row: dict[str, str]) -> Card:
    card = _card_from_row(row)
    if card.id in _PC01R_COST_OVERRIDES:
        card.cost = dict(_PC01R_COST_OVERRIDES[card.id])
    card.effects = list(_PC01R_EFFECTS_BY_ID.get(card.id, ()))
    card.aura = _PC01R_AURAS_BY_ID.get(card.id)
    card.keyword_aura = _PC01R_KEYWORD_AURAS_BY_ID.get(card.id)
    if card.id == "blue_08_02_01r_00":
        card.keywords = [keyword for keyword in card.keywords if keyword is not Keyword.SNEAKING]
    return card


def register_pc01r_cards(path: Path = DEFAULT_CARD_TSV) -> list[str]:
    rows = _pc01r_rows(path)
    registered_ids: list[str] = []
    for row in rows:
        card = _pc01r_card_from_row(row)
        if card.id not in CARD_REGISTRY:
            register(card)
        registered_ids.append(card.id)
    behavior_ids = set(_PC01R_EFFECTS_BY_ID) | set(_PC01R_AURAS_BY_ID) | set(_PC01R_KEYWORD_AURAS_BY_ID) | _ENGINE_RULE_IDS
    missing = set(registered_ids) - behavior_ids
    extra = behavior_ids - set(registered_ids)
    if len(registered_ids) != 70 or missing or extra:
        raise RuntimeError(
            f"PC01R inventory/behavior mismatch: rows={len(registered_ids)} missing={sorted(missing)} extra={sorted(extra)}"
        )
    return registered_ids


PC01R_CARD_IDS = register_pc01r_cards()
