from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from zz.enums import AreaType, CardType, Color, Keyword


EffectFn = Callable[[Any, Any, Any], None]
EffectCondition = Callable[[Any, Any, Any], bool]


class EffectTiming(Enum):
    ON_SUMMON = "on_summon"
    ON_PLACE_BASE = "on_place_base"
    ON_CAST_MAGIC = "on_cast_magic"
    ON_ATTACK = "on_attack"
    ON_BLOCK = "on_block"
    ON_DESTROY = "on_destroy"
    ON_DAMAGE_PLAYER = "on_damage_player"
    ON_DAMAGE_FORCE = "on_damage_force"
    ON_CARD_USED = "on_card_used"
    ON_FORCE_DESTROYED = "on_force_destroyed"
    ON_BATTLE_WIN = "on_battle_win"
    ON_ENTER_FIELD = "on_enter_field"
    ON_BLESS = "on_bless"
    ON_DECK_DISCARD = "on_deck_discard"
    ON_MOVE_TO_FIELD = "on_move_to_field"
    MOVE_TO_BASE = "move_to_base"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    CONTINUOUS = "continuous"
    MAIN_ACTIVATED = "main_activated"
    FLASH_ACTIVATED = "flash_activated"


@dataclass
class EffectSpec:
    timing: EffectTiming
    fn: EffectFn
    condition: EffectCondition | None = None
    target_kind: str | None = None
    min_targets: int = 1
    max_targets: int = 1
    optional: bool = False
    template_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    official_effect: str | None = None
    official_timing: str | None = None
    official_condition: str | None = None
    active_areas: tuple[AreaType, ...] | None = None
    pre_target_fn: EffectFn | None = None


def effect_once_per_turn_used(effect: EffectSpec, source: Any) -> bool:
    """Return whether an explicitly marked once-per-turn effect was consumed.

    Card callbacks remain responsible for setting their existing turn marker
    only after the effect really resolves.  The shared trigger/session paths
    use this predicate to avoid presenting a stale choice for a duplicate
    pending trigger.
    """
    flag = effect.params.get("once_per_turn_flag")
    if not flag:
        return False
    scope = effect.params.get("once_per_turn_scope", "source")
    if scope == "source":
        holder = source
    elif scope == "owner":
        holder = getattr(source, "owner", None)
    else:
        raise ValueError(f"unknown once-per-turn scope: {scope!r}")
    flags = getattr(holder, "flags", None)
    return isinstance(flags, set) and str(flag) in flags


TIMING_LABELS = {
    EffectTiming.ON_SUMMON: "召喚時",
    EffectTiming.ON_PLACE_BASE: "配置時",
    EffectTiming.ON_CAST_MAGIC: "メイン/フラッシュ",
    EffectTiming.ON_ATTACK: "アタック時",
    EffectTiming.ON_BLOCK: "ブロック時",
    EffectTiming.ON_DESTROY: "破壊時",
    EffectTiming.ON_DAMAGE_PLAYER: "ダメージ時",
    EffectTiming.ON_DAMAGE_FORCE: "フォースダメージ時",
    EffectTiming.ON_CARD_USED: "カード使用時",
    EffectTiming.ON_FORCE_DESTROYED: "フォース破壊時",
    EffectTiming.ON_BATTLE_WIN: "バトル勝利時",
    EffectTiming.ON_ENTER_FIELD: "フィールドに出る",
    EffectTiming.ON_BLESS: "加護時",
    EffectTiming.ON_DECK_DISCARD: "デッキから破棄された時",
    EffectTiming.ON_MOVE_TO_FIELD: "移動時",
    EffectTiming.MOVE_TO_BASE: "後退時",
    EffectTiming.TURN_START: "自分のターン開始時",
    EffectTiming.TURN_END: "自分のターン終了時",
    EffectTiming.CONTINUOUS: "常時",
    EffectTiming.MAIN_ACTIVATED: "メイン",
    EffectTiming.FLASH_ACTIVATED: "フラッシュ",
}


KEYWORD_LABELS = {
    Keyword.RUSH: "襲撃",
    Keyword.FLYING: "飛来",
    Keyword.REAWAKEN: "再起",
    Keyword.PENETRATE: "貫通",
    Keyword.SNEAKING: "潜入",
    Keyword.DEATH_BLOW: "奪命",
    Keyword.COOPERATION: "連携",
    Keyword.BLESS: "加護",
    Keyword.KAGO: "加護",
    Keyword.COST_REDUCTION: "コスト軽減",
    Keyword.UNBLOCKABLE: "ブロックされない",
}

KEYWORDS_BY_OFFICIAL_LABEL = {
    label: keyword
    for keyword, label in KEYWORD_LABELS.items()
    if label
}


@dataclass(frozen=True)
class EffectTemplate:
    id: str
    label: str
    target_kinds: tuple[str, ...] = ()
    official_effect: str | None = None
    official_effects: tuple[str, ...] = ()


EFFECT_TEMPLATES: dict[str, EffectTemplate] = {
    "draw_cards": EffectTemplate("draw_cards", "Draw cards"),
    "draw_until_hand_size": EffectTemplate("draw_until_hand_size", "Draw until hand size"),
    "discard_hand_draw": EffectTemplate("discard_hand_draw", "Discard hand then draw"),
    "exchange_player_force_life": EffectTemplate(
        "exchange_player_force_life",
        "Exchange player and force life",
        target_kinds=("ally_force",),
    ),
    "increase_movement_right": EffectTemplate("increase_movement_right", "Increase movement right"),
    "stat_modifier": EffectTemplate(
        "stat_modifier",
        "Modify BP/DP",
        target_kinds=("ally_minion", "other_ally_minion", "enemy_minion"),
    ),
    "stat_modifier_all": EffectTemplate(
        "stat_modifier_all",
        "Modify all matching BP/DP",
        target_kinds=("ally_minion", "enemy_minion", "any_minion"),
    ),
    "grant_keyword": EffectTemplate(
        "grant_keyword",
        "Grant keyword",
        target_kinds=("ally_minion",),
        official_effects=tuple(
            label for label in ["襲撃", "飛来", "再起", "貫通", "潜入", "奪命", "連携", "加護"]
        ),
    ),
    "grant_unblockable": EffectTemplate(
        "grant_unblockable",
        "Grant unblockable",
        target_kinds=("ally_minion",),
    ),
    "return_to_hand": EffectTemplate(
        "return_to_hand",
        "Return target to hand",
        target_kinds=("enemy_minion", "enemy_minion_cost_at_most_4", "ally_minion", "any_minion"),
    ),
    "return_self_to_hand": EffectTemplate("return_self_to_hand", "Return self to hand"),
    "return_from_trash_to_hand": EffectTemplate(
        "return_from_trash_to_hand",
        "Return from trash to hand",
        target_kinds=("trash_magic_cost_at_most_4",),
    ),
    "discard_target_draw": EffectTemplate(
        "discard_target_draw",
        "Discard target then draw",
        target_kinds=("hand_base_minion",),
    ),
    "create_tokens": EffectTemplate("create_tokens", "Create tokens"),
    "move_to_base_targets": EffectTemplate(
        "move_to_base_targets",
        "Move targets to base",
        target_kinds=("enemy_minion", "enemy_minion_cost_at_most_4", "enemy_minion_cost_at_least_6"),
    ),
    "rest_targets": EffectTemplate(
        "rest_targets",
        "Rest targets",
        target_kinds=(
            "enemy_minion",
            "enemy_minion_cost_at_most_4",
            "enemy_minion_or_force",
            "any_minion_or_force",
            "enemy_force",
        ),
    ),
    "refresh_targets": EffectTemplate(
        "refresh_targets",
        "Refresh targets",
        target_kinds=("ally_minion", "any_minion", "ally_minion_cost_at_most_4", "ally_base"),
    ),
    "rest_self": EffectTemplate("rest_self", "Rest self"),
    "destroy_targets": EffectTemplate(
        "destroy_targets",
        "Destroy targets",
        target_kinds=("any_minion", "enemy_minion", "enemy_minion_cost_at_most_4"),
    ),
    "heal_targets": EffectTemplate(
        "heal_targets",
        "Heal targets",
        target_kinds=("owner_player", "owner_player_or_force", "owner_player_and_forces", "owner_forces", "ally_force"),
    ),
    "search_deck_to_hand": EffectTemplate(
        "search_deck_to_hand",
        "Search deck to hand",
        target_kinds=("deck_base_minion",),
    ),
    "look_top_to_hand": EffectTemplate(
        "look_top_to_hand",
        "Look top cards to hand",
        target_kinds=("top3_field_minion", "top_field_minion"),
    ),
    "place_base_from_hand": EffectTemplate(
        "place_base_from_hand",
        "Place base from hand",
        target_kinds=("ally_green_base_hand",),
    ),
    "refresh_self": EffectTemplate("refresh_self", "Refresh self"),
    "move_to_base_rested": EffectTemplate("move_to_base_rested", "Move to base rested"),
    "place_colorless_mana": EffectTemplate("place_colorless_mana", "Place colorless mana"),
    "prevent_player_damage": EffectTemplate("prevent_player_damage", "Prevent player damage"),
    "prevent_force_damage": EffectTemplate("prevent_force_damage", "Prevent force damage"),
    "block_life_gain_and_damage_reduction": EffectTemplate(
        "block_life_gain_and_damage_reduction",
        "Block life gain and damage reduction",
    ),
    "place_base_from_deck": EffectTemplate(
        "place_base_from_deck",
        "Place base from deck",
        target_kinds=("deck_base_minion", "deck_base_or_field_minion"),
    ),
    "summon_from_trash": EffectTemplate(
        "summon_from_trash",
        "Summon field minion from trash",
        target_kinds=("trash_field_minion",),
    ),
    "damage_targets": EffectTemplate(
        "damage_targets",
        "Deal damage",
        target_kinds=("opponent_player", "opponent_player_and_forces", "opponent_forces"),
    ),
    "force_block": EffectTemplate("force_block", "Force block", target_kinds=("enemy_minion",)),
}


def effect_template_catalog() -> dict[str, dict[str, Any]]:
    return {
        template_id: {
            "id": template.id,
            "label": template.label,
            "targetKinds": list(template.target_kinds),
            "officialEffect": template.official_effect,
            "officialEffects": list(template.official_effects),
        }
        for template_id, template in EFFECT_TEMPLATES.items()
    }


def build_effect(
    template_id: str,
    timing: EffectTiming,
    *,
    condition: EffectCondition | None = None,
    target_kind: str | None = None,
    min_targets: int = 1,
    max_targets: int = 1,
    optional: bool = False,
    official_effect: str | None = None,
    official_timing: str | None = None,
    official_condition: str | None = None,
    active_areas: tuple[AreaType, ...] | None = None,
    **params: Any,
) -> EffectSpec:
    if template_id not in EFFECT_TEMPLATES:
        raise ValueError(f"unknown effect template: {template_id}")
    template = EFFECT_TEMPLATES[template_id]
    if template_id == "force_block" and not params.get("choose_target") and target_kind is None:
        resolved_target_kind = None
    else:
        resolved_target_kind = target_kind or (template.target_kinds[0] if template.target_kinds else None)
    official_effect_label = official_effect or template.official_effect
    builder = _EFFECT_BUILDERS[template_id]
    fn = builder(
        target_kind=resolved_target_kind,
        min_targets=min_targets,
        max_targets=max_targets,
        optional=optional,
        **params,
    )
    stored_params = {
        key: _param_value(value)
        for key, value in params.items()
    }
    if template_id == "stat_modifier_all":
        stored_params["all_targets"] = True
    if active_areas is None and timing in (EffectTiming.ON_PLACE_BASE, EffectTiming.MOVE_TO_BASE):
        active_areas = (AreaType.BASE,)
    return EffectSpec(
        timing=timing,
        fn=fn,
        condition=condition,
        target_kind=resolved_target_kind,
        min_targets=min_targets,
        max_targets=max_targets,
        optional=optional,
        template_id=template_id,
        params=stored_params,
        official_effect=official_effect_label,
        official_timing=official_timing or TIMING_LABELS.get(timing),
        official_condition=official_condition,
        active_areas=active_areas,
    )


def _param_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (list, tuple)):
        return [_param_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _param_value(item) for key, item in value.items()}
    return value


def _draw_cards(*, amount: int = 1, scope: str = "owner", **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is not None:
            if scope == "both":
                for player in state.players:
                    eng.draw(player, amount)
            else:
                eng.draw(ci.owner, amount)
    return fn


def _draw_until_hand_size(*, hand_size: int, **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        missing = max(0, hand_size - len(ci.owner.hand))
        if missing:
            eng.draw(ci.owner, missing)
    return fn


def _discard_hand_draw(*, amount: int, scope: str = "owner", **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        players = list(state.players) if scope == "both" else [ci.owner]
        for player in players:
            discarded = list(player.hand)
            player.hand.clear()
            for card in discarded:
                card.area = AreaType.TRASH
                player.trash.append(card)
            eng.draw(player, amount)
    return fn


def _exchange_player_force_life(
    *,
    target_kind: str | None,
    player_scope: str = "opponent",
    max_targets: int = 1,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        targets = eng.select_target(ci.owner, target_kind, max_targets, max_targets)
        if not targets:
            return
        force = targets[0]
        player = ci.owner
        if player_scope == "opponent":
            player = state.players[1 - state.players.index(ci.owner)]
        player.life, force.life = force.life, player.life
    return fn


def _increase_movement_right(*, amount: int = 1, **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is not None and hasattr(eng, "grant_movement_right"):
            eng.grant_movement_right(ci.owner, amount)
            return
        ci.owner.movement_right_count += amount
        ci.owner.movement_right_total += amount
    return fn


def _stat_modifier(
    *,
    target_kind: str | None,
    min_targets: int = 1,
    max_targets: int = 1,
    bp_delta: int = 0,
    dp_delta: int = 0,
    keyword: Keyword | str | None = None,
    exclude_self: bool = False,
    duration: str = "turn",
    max_cost: int | None = None,
    min_cost: int | None = None,
    max_bp: int | None = None,
    min_bp: int | None = None,
    max_dp: int | None = None,
    min_dp: int | None = None,
    color: Color | str | None = None,
    race: str | None = None,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        selection_kind = "ally_minion" if target_kind == "other_ally_minion" else target_kind
        should_exclude_self = exclude_self or target_kind == "other_ally_minion"
        matcher = _target_filter(
            eng,
            max_cost=max_cost,
            min_cost=min_cost,
            max_bp=max_bp,
            min_bp=min_bp,
            max_dp=max_dp,
            min_dp=min_dp,
            color=color,
            race=race,
        )
        filter_fn = lambda target: (not should_exclude_self or target is not ci) and matcher(target)
        targets = eng.select_target(ci.owner, selection_kind, min_targets, max_targets, filter_fn=filter_fn, source=ci)
        for target in targets[:max_targets]:
            eng.modify_stat(target, bp_delta=bp_delta, dp_delta=dp_delta, duration=duration)
            if keyword is not None:
                eng.add_keyword(target, _keyword_from_value(keyword))
    return fn


def _stat_modifier_all(
    *,
    target_kind: str | None,
    bp_delta: int = 0,
    dp_delta: int = 0,
    keyword: Keyword | str | None = None,
    max_cost: int | None = None,
    min_cost: int | None = None,
    max_bp: int | None = None,
    max_dp: int | None = None,
    color: Color | str | None = None,
    duration: str = "turn",
    applies_to_future: bool = False,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        if applies_to_future and duration == "turn" and hasattr(eng, "add_turn_stat_modifier"):
            eng.add_turn_stat_modifier(
                ci.owner,
                target_kind=target_kind,
                bp_delta=bp_delta,
                dp_delta=dp_delta,
                max_cost=max_cost,
                min_cost=min_cost,
                max_bp=max_bp,
                max_dp=max_dp,
                color=color,
                source=ci,
            )
            return
        for target in _matching_targets(
            state,
            ci.owner,
            target_kind,
            max_cost=max_cost,
            min_cost=min_cost,
            max_bp=max_bp,
            max_dp=max_dp,
            color=color,
        ):
            eng.modify_stat(target, bp_delta=bp_delta, dp_delta=dp_delta, duration=duration)
            if keyword is not None:
                eng.add_keyword(target, _keyword_from_value(keyword))
    return fn


def _grant_keyword(
    *,
    target_kind: str | None,
    max_targets: int = 1,
    keyword: Keyword | str,
    **params: Any,
) -> EffectFn:
    return _stat_modifier(
        target_kind=target_kind,
        max_targets=max_targets,
        keyword=keyword,
        **params,
    )


def _grant_unblockable(
    *,
    target_kind: str | None,
    max_targets: int = 1,
    return_if_race: str | None = None,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        targets = eng.select_target(ci.owner, target_kind, max_targets, max_targets, source=ci)
        for target in targets[:max_targets]:
            eng.add_keyword(target, Keyword.UNBLOCKABLE)
            target.flags.add("turn:unblockable")
            if return_if_race and return_if_race in target.card.race_jp:
                if ci in ci.owner.trash:
                    ci.owner.trash.remove(ci)
                if ci not in ci.owner.hand:
                    eng.add_to_hand(ci.owner, ci, from_area=AreaType.TRASH)
    return fn


def _return_to_hand(
    *,
    target_kind: str | None,
    max_targets: int = 1,
    max_bp: int | None = None,
    max_cost: int | None = None,
    min_cost: int | None = None,
    max_dp: int | None = None,
    color: Color | str | None = None,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        filter_fn = None
        if any(value is not None for value in (max_bp, max_cost, min_cost, max_dp, color)):
            filter_fn = _target_filter(
                eng,
                max_bp=max_bp,
                max_cost=max_cost,
                min_cost=min_cost,
                max_dp=max_dp,
                color=color,
            )
        targets = eng.select_target(ci.owner, target_kind, max_targets, max_targets, filter_fn=filter_fn, source=ci)
        for target in targets[:max_targets]:
            eng.return_to_hand(target)
    return fn


def _return_self_to_hand(**_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is not None:
            eng.return_to_hand(ci)
    return fn


def _return_from_trash_to_hand(
    *,
    target_kind: str | None,
    max_targets: int = 1,
    optional: bool = False,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        targets = eng.select_target(ci.owner, target_kind, 0 if optional else 1, max_targets, source=ci)
        for target in targets[:max_targets]:
            if target not in ci.owner.trash:
                continue
            eng.add_to_hand(ci.owner, target, from_area=AreaType.TRASH)
    return fn


def _discard_target_draw(
    *,
    target_kind: str | None,
    amount: int = 1,
    max_targets: int = 1,
    optional: bool = False,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        targets = eng.select_target(ci.owner, target_kind, 0 if optional else 1, max_targets, source=ci)
        if not targets:
            return
        for target in targets[:max_targets]:
            if target not in ci.owner.hand:
                continue
            ci.owner.hand.remove(target)
            target.area = AreaType.TRASH
            ci.owner.trash.append(target)
        eng.draw(ci.owner, amount)
    return fn


def _create_tokens(
    *,
    amount: int,
    token_id: str,
    name_jp: str,
    color: Color | str = Color.COLORLESS,
    cost: int = 0,
    bp: int = 0,
    dp: int = 0,
    rested: bool = False,
    optional: bool = False,
    race_jp: str = "",
    keywords: tuple[Keyword | str, ...] | list[Keyword | str] | None = None,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        from zz.model import Card

        eng = getattr(state, "engine", None)
        if eng is None:
            return
        token_color = _color_from_value(color) or Color.COLORLESS
        token_cost = {token_color: cost} if cost else {}
        token_card = Card(
            id=token_id,
            name_jp=name_jp,
            name_en=name_jp,
            type=CardType.F_MINION,
            cost=token_cost,
            bp=bp,
            dp=dp,
            race_jp=race_jp,
            keywords=[_keyword_from_value(keyword) for keyword in (keywords or ())],
        )
        selected_amount = getattr(ctx, "_create_tokens_count", None)
        if selected_amount is None:
            selected_amount = amount
        selected_amount = max(0, min(amount, int(selected_amount)))
        eng.create_tokens(
            ci.owner,
            [token_card] * amount,
            source=ci,
            rested=rested,
            optional=optional,
            count=selected_amount,
        )
    return fn


def _move_to_base_targets(
    *,
    target_kind: str | None,
    min_targets: int = 1,
    max_targets: int = 1,
    max_cost: int | None = None,
    min_cost: int | None = None,
    rested: bool = True,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        filter_fn = None
        if max_cost is not None or min_cost is not None:
            filter_fn = _target_filter(eng, max_cost=max_cost, min_cost=min_cost)
        targets = eng.select_target(ci.owner, target_kind, min_targets, max_targets, filter_fn=filter_fn, source=ci)
        for target in targets[:max_targets]:
            if not eng.move_target_to_base_asking_owner(target, rested=rested, source=ci):
                return
    return fn


def _rest_targets(
    *,
    target_kind: str | None,
    min_targets: int = 1,
    max_targets: int = 1,
    max_cost: int | None = None,
    all_targets: bool = False,
    lock_until_next_refresh_on_own_turn: bool = False,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        if all_targets:
            targets = _matching_targets(state, ci.owner, target_kind, max_cost=max_cost)
            for target in targets:
                eng.rest_target(target)
                if lock_until_next_refresh_on_own_turn and getattr(state, "active", None) is ci.owner:
                    eng.prevent_next_refresh(target)
            return
        filter_fn = None
        if max_cost is not None:
            filter_fn = lambda target: sum(target.card.cost.values()) <= max_cost
        bonus = 1 if _owner_has_card(ci.owner, "green_04_02_01_01") else 0
        required = min_targets + bonus
        limit = max_targets + bonus
        targets = eng.select_target(ci.owner, target_kind, required, limit, filter_fn=filter_fn, source=ci)
        for target in targets[:limit]:
            eng.rest_target(target)
            if lock_until_next_refresh_on_own_turn and getattr(state, "active", None) is ci.owner:
                eng.prevent_next_refresh(target)
    return fn


def _refresh_targets(
    *,
    target_kind: str | None,
    min_targets: int = 1,
    max_targets: int = 1,
    max_cost: int | None = None,
    optional: bool = False,
    only_rested: bool = False,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        filter_fn = None
        if max_cost is not None:
            filter_fn = lambda target: sum(target.card.cost.values()) <= max_cost
        if only_rested:
            previous_filter = filter_fn

            def filter_fn(target: Any) -> bool:
                return bool(getattr(target, "rested", False)) and (
                    previous_filter is None or previous_filter(target)
                )
        required = 0 if optional else min_targets
        targets = eng.select_target(ci.owner, target_kind, required, max_targets, filter_fn=filter_fn, source=ci)
        for target in targets[:max_targets]:
            if hasattr(target, "rested"):
                target.rested = False
    return fn


def _rest_self(**_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        ci.rested = True
    return fn


def _destroy_targets(
    *,
    target_kind: str | None,
    max_targets: int = 1,
    all_targets: bool = False,
    max_cost: int | None = None,
    min_cost: int | None = None,
    max_bp: int | None = None,
    max_dp: int | None = None,
    color: Color | str | None = None,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        if all_targets:
            targets = _matching_targets(
                state,
                ci.owner,
                target_kind,
                max_cost=max_cost,
                min_cost=min_cost,
                max_bp=max_bp,
                max_dp=max_dp,
                color=color,
            )
        else:
            filter_fn = _target_filter(eng, max_cost=max_cost, min_cost=min_cost, max_bp=max_bp, max_dp=max_dp, color=color)
            targets = eng.select_target(ci.owner, target_kind, max_targets, max_targets, filter_fn=filter_fn, source=ci)
        for target in list(targets[:max_targets] if not all_targets else targets):
            eng.destroy_target(target, source=ci)
    return fn


def _heal_targets(
    *,
    target_kind: str | None,
    amount: int = 1,
    max_targets: int = 1,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        if target_kind == "owner_player":
            eng.heal_target(ci.owner, amount)
            return
        if target_kind == "owner_player_or_force":
            targets = eng.select_target(ci.owner, target_kind, max_targets, max_targets, source=ci)
            for target in targets[:max_targets]:
                eng.heal_target(target, amount)
            return
        if target_kind == "owner_forces":
            for force in ci.owner.forces:
                if not force.destroyed:
                    eng.heal_target(force, amount)
            return
        if target_kind == "owner_player_and_forces":
            eng.heal_target(ci.owner, amount)
            for force in ci.owner.forces:
                if not force.destroyed:
                    eng.heal_target(force, amount)
            return
        targets = eng.select_target(ci.owner, target_kind, max_targets, max_targets, source=ci)
        for target in targets[:max_targets]:
            eng.heal_target(target, amount)
    return fn


def _search_deck_to_hand(
    *,
    target_kind: str | None,
    optional: bool = False,
    card_id: str | None = None,
    card_ids: tuple[str, ...] | list[str] | None = None,
    exclude_card_id: str | None = None,
    race: str | None = None,
    card_type: CardType | str | None = None,
    color: Color | str | None = None,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        owner = ci.owner
        if eng is not None and target_kind is not None:
            filter_fn = _target_filter(
                eng,
                card_id=card_id,
                card_ids=card_ids,
                exclude_card_id=exclude_card_id,
                race=race,
                card_type=card_type,
                color=color,
            )
            chosen = eng.select_target(owner, target_kind, 1, 1, filter_fn=filter_fn, source=ci)
            candidate = chosen[0] if chosen else None
        else:
            candidate = next((card for card in owner.deck if card.card.type is CardType.B_MINION), None)
        if candidate is None:
            if eng is not None:
                eng.rng.shuffle(owner.deck)
            return
        owner.deck.remove(candidate)
        if eng is not None:
            eng.reveal_card(owner, candidate, "deck_search")
            eng.add_to_hand(owner, candidate, from_area=AreaType.DECK)
        else:
            candidate.area = AreaType.HAND
            owner.hand.append(candidate)
        if eng is not None:
            eng.rng.shuffle(owner.deck)
    return fn


def _look_top_to_hand(
    *,
    target_kind: str | None,
    top_n: int,
    min_targets: int = 1,
    max_targets: int = 1,
    optional: bool = False,
    card_id: str | None = None,
    card_ids: tuple[str, ...] | list[str] | None = None,
    exclude_card_id: str | None = None,
    race: str | None = None,
    card_type: CardType | str | None = None,
    color: Color | str | None = None,
    max_cost: int | None = None,
    min_cost: int | None = None,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        owner = ci.owner
        if eng is None or target_kind is None:
            return
        seen = list(owner.deck[:top_n])
        filter_fn = _target_filter(
            eng,
            card_id=card_id,
            card_ids=card_ids,
            exclude_card_id=exclude_card_id,
            race=race,
            card_type=card_type,
            color=color,
            max_cost=max_cost,
            min_cost=min_cost,
        )
        chosen = eng.select_target(
            owner,
            target_kind,
            0 if optional else min_targets,
            max_targets,
            filter_fn=filter_fn,
            source=ci,
        )
        chosen_ids = {card.iid for card in chosen}
        for card in chosen:
            if card not in owner.deck:
                continue
            owner.deck.remove(card)
            eng.reveal_card(owner, card, "deck_search")
            eng.add_to_hand(owner, card, from_area=AreaType.DECK)
        rest = [card for card in seen if card.iid not in chosen_ids and card in owner.deck]
        for card in rest:
            owner.deck.remove(card)
        eng.rng.shuffle(rest)
        owner.deck.extend(rest)
    return fn


def _place_base_from_hand(
    *,
    target_kind: str | None,
    color: Color | str | None = None,
    rested: bool = True,
    optional: bool = True,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        owner = ci.owner
        if eng is not None and target_kind is not None:
            chosen = eng.select_target(owner, target_kind, 0 if optional else 1, 1, source=ci)
            candidate = chosen[0] if chosen else None
        else:
            wanted_color = _color_from_value(color)
            candidate = next(
                (
                    card for card in owner.hand
                    if card.card.type is CardType.B_MINION
                    and (wanted_color is None or card.card.mana_color is wanted_color)
                ),
                None,
            )
        if candidate is None:
            return
        replace_iid = None
        if eng is not None:
            replace_iid = eng.select_base_replacement_iid(owner, ci)
            if len(owner.base) >= 10 and replace_iid is None:
                return
            if replace_iid is not None:
                eng._make_base_space(owner, replace_iid)
        elif len(owner.base) >= 10:
            return
        owner.hand.remove(candidate)
        candidate.area = AreaType.BASE
        candidate.rested = rested
        owner.base.append(candidate)
    return fn


def _place_colorless_mana(*, rested: bool = False, **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is not None:
            replace_iid = eng.select_base_replacement_iid(ci.owner, ci)
            if len(ci.owner.base) >= 10 and replace_iid is None:
                return
            token = eng.place_generated_colorless_mana(ci.owner, replace_base_iid=replace_iid)
            token.rested = rested
    return fn


def _prevent_player_damage(*, amount: int = 1, **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is not None:
            eng.prevent_player_damage(ci.owner, amount)
    return fn


def _prevent_force_damage(*, amount: int = 1, **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is not None:
            eng.prevent_force_damage(ci.owner, amount)
    return fn


def _block_life_gain_and_damage_reduction(*, player_scope: str = "opponent", **_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        player = ci.owner
        if player_scope == "opponent":
            player = state.players[1 - state.players.index(ci.owner)]
        eng.block_life_gain_and_damage_reduction(player)
    return fn


def _place_base_from_deck(
    *,
    target_kind: str | None,
    card_id: str | None = None,
    min_targets: int = 1,
    max_targets: int = 1,
    rested: bool = True,
    optional: bool = True,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        filter_fn = _target_filter(eng, card_id=card_id)
        chosen = eng.select_target(
            ci.owner,
            target_kind,
            0 if optional else min_targets,
            max_targets,
            filter_fn=filter_fn,
            source=ci,
        )
        if not chosen:
            eng.rng.shuffle(ci.owner.deck)
            return
        for candidate in chosen[:max_targets]:
            if candidate not in ci.owner.deck:
                continue
            replace_iid = eng.select_base_replacement_iid(ci.owner, ci)
            if len(ci.owner.base) >= 10 and replace_iid is None:
                eng.rng.shuffle(ci.owner.deck)
                return
            eng.place_from_deck_to_base(ci.owner, candidate, rested=rested, replace_base_iid=replace_iid)
        eng.rng.shuffle(ci.owner.deck)
    return fn


def _summon_from_trash(
    *,
    target_kind: str | None,
    max_cost: int | None = None,
    min_cost: int | None = None,
    color: Color | str | None = None,
    exclude_card_id: str | None = None,
    optional: bool = False,
    rested: bool = False,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None or target_kind is None:
            return
        filter_fn = _target_filter(
            eng,
            max_cost=max_cost,
            min_cost=min_cost,
            color=color,
            exclude_card_id=exclude_card_id,
            card_type=CardType.F_MINION,
        )
        targets = eng.select_target(ci.owner, target_kind, 0 if optional else 1, 1, filter_fn=filter_fn, source=ci)
        if not targets:
            return
        replace_iid = None
        if len(ci.owner.field) >= 5:
            replacements = eng.select_target(ci.owner, "ally_minion", 1, 1, source=ci)
            if not replacements:
                return
            replace_iid = replacements[0].iid
        eng.summon_from_trash(ci.owner, targets[0], rested=rested, replace_field_iid=replace_iid)
    return fn


def _damage_targets(
    *,
    target_kind: str | None,
    amount: int = 1,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if eng is None:
            return
        opponent = state.players[1 - state.players.index(ci.owner)]
        if target_kind == "opponent_player_and_forces":
            eng._damage_player(opponent, amount, source=ci)
            for force in list(opponent.forces):
                if not force.destroyed:
                    eng._damage_force(force, amount, source=ci)
        elif target_kind == "opponent_player":
            eng._damage_player(opponent, amount, source=ci)
        elif target_kind == "opponent_forces":
            for force in list(opponent.forces):
                if not force.destroyed:
                    eng._damage_force(force, amount, source=ci)
    return fn


def _force_block(
    *,
    target_kind: str | None = None,
    choose_target: bool = False,
    **_: Any,
) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        eng = getattr(state, "engine", None)
        if choose_target and eng is not None and target_kind is not None:
            targets = eng.select_target(ci.owner, target_kind, 0, 1, source=ci)
            if not targets:
                return
            target = targets[0]
            target.rested = False
            ci.flags.add(f"force_block_iid:{target.iid}")
            return
        ci.flags.add("must_be_blocked")
    return fn


def _refresh_self(**_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        ci.rested = False
    return fn


def _move_to_base_rested(**_: Any) -> EffectFn:
    def fn(ci: Any, state: Any, ctx: Any) -> None:
        if ctx.source is ci and ci.area is AreaType.BASE:
            ci.rested = True
    return fn


def _keyword_from_value(value: Keyword | str) -> Keyword:
    if isinstance(value, Keyword):
        return value
    if value in Keyword.__members__:
        return Keyword[value]
    if value in KEYWORDS_BY_OFFICIAL_LABEL:
        return KEYWORDS_BY_OFFICIAL_LABEL[value]
    raise ValueError(f"unknown keyword: {value}")


def _color_from_value(value: Color | str | None) -> Color | None:
    if value is None:
        return None
    if isinstance(value, Color):
        return value
    return Color[value]


def _target_filter(
    eng: Any,
    *,
    max_cost: int | None = None,
    min_cost: int | None = None,
    max_bp: int | None = None,
    min_bp: int | None = None,
    max_dp: int | None = None,
    min_dp: int | None = None,
    color: Color | str | None = None,
    card_id: str | None = None,
    card_ids: tuple[str, ...] | list[str] | None = None,
    exclude_card_id: str | None = None,
    race: str | None = None,
    card_type: CardType | str | None = None,
):
    wanted_color = _color_from_value(color)
    wanted_type = _card_type_from_value(card_type)
    wanted_card_ids = set(card_ids or ())

    def matches(target: Any) -> bool:
        card = getattr(target, "card", None)
        if card is None:
            return False
        if card_id is not None and card.id != card_id:
            return False
        if wanted_card_ids and card.id not in wanted_card_ids:
            return False
        if exclude_card_id is not None and card.id == exclude_card_id:
            return False
        if wanted_type is not None and card.type is not wanted_type:
            return False
        if race is not None and race not in card.race_jp:
            return False
        total_cost = sum(card.cost.values())
        if max_cost is not None and total_cost > max_cost:
            return False
        if min_cost is not None and total_cost < min_cost:
            return False
        if max_bp is not None and eng.effective_bp(target) > max_bp:
            return False
        if min_bp is not None and eng.effective_bp(target) < min_bp:
            return False
        if max_dp is not None and eng.effective_dp(target) > max_dp:
            return False
        if min_dp is not None and eng.effective_dp(target) < min_dp:
            return False
        if wanted_color is not None and _card_color(card) is not wanted_color:
            return False
        return True

    return matches


def _matching_targets(
    state: Any,
    owner: Any,
    target_kind: str,
    **filters: Any,
) -> list[Any]:
    eng = getattr(state, "engine", None)
    if eng is None:
        return []
    opponent = state.players[1 - state.players.index(owner)]
    if target_kind == "enemy_minion":
        pool = list(opponent.field)
    elif target_kind == "ally_minion":
        pool = list(owner.field)
    elif target_kind == "any_minion":
        pool = [ci for player in state.players for ci in player.field]
    else:
        pool = eng.select_target(owner, target_kind, 0, 99)
    matcher = _target_filter(eng, **filters)
    return [target for target in pool if matcher(target)]


def _owner_has_card(owner: Any, card_id: str) -> bool:
    return any(ci.card.id == card_id and ci.area is AreaType.FIELD for ci in owner.field)


def _card_color(card: Any) -> Color | None:
    if getattr(card, "mana_color", None) is not None:
        return card.mana_color
    for color in getattr(card, "cost", {}):
        if color is not Color.COLORLESS:
            return color
    return Color.COLORLESS


def _card_type_from_value(value: CardType | str | None) -> CardType | None:
    if value is None:
        return None
    if isinstance(value, CardType):
        return value
    return CardType[value] if value in CardType.__members__ else CardType(value)


_EFFECT_BUILDERS: dict[str, Callable[..., EffectFn]] = {
    "draw_cards": _draw_cards,
    "draw_until_hand_size": _draw_until_hand_size,
    "discard_hand_draw": _discard_hand_draw,
    "exchange_player_force_life": _exchange_player_force_life,
    "increase_movement_right": _increase_movement_right,
    "stat_modifier": _stat_modifier,
    "stat_modifier_all": _stat_modifier_all,
    "grant_keyword": _grant_keyword,
    "grant_unblockable": _grant_unblockable,
    "return_to_hand": _return_to_hand,
    "return_self_to_hand": _return_self_to_hand,
    "return_from_trash_to_hand": _return_from_trash_to_hand,
    "discard_target_draw": _discard_target_draw,
    "create_tokens": _create_tokens,
    "move_to_base_targets": _move_to_base_targets,
    "rest_targets": _rest_targets,
    "refresh_targets": _refresh_targets,
    "rest_self": _rest_self,
    "destroy_targets": _destroy_targets,
    "heal_targets": _heal_targets,
    "search_deck_to_hand": _search_deck_to_hand,
    "look_top_to_hand": _look_top_to_hand,
    "place_base_from_hand": _place_base_from_hand,
    "refresh_self": _refresh_self,
    "move_to_base_rested": _move_to_base_rested,
    "place_colorless_mana": _place_colorless_mana,
    "prevent_player_damage": _prevent_player_damage,
    "prevent_force_damage": _prevent_force_damage,
    "block_life_gain_and_damage_reduction": _block_life_gain_and_damage_reduction,
    "place_base_from_deck": _place_base_from_deck,
    "summon_from_trash": _summon_from_trash,
    "damage_targets": _damage_targets,
    "force_block": _force_block,
}


_TIMING_TEXT_PATTERNS = [
    ("メイン/フラッシュ", re.compile(r"【メイン】\s*/\s*【フラッシュ】")),
    ("召喚時", re.compile(r"【召喚時】")),
    ("アタック時", re.compile(r"【アタック時】")),
    ("常時", re.compile(r"【常時】")),
    ("フラッシュ", re.compile(r"【フラッシュ】")),
    ("メイン", re.compile(r"【メイン】")),
    ("配置時", re.compile(r"【配置時】")),
    ("後退時", re.compile(r"【後退時】")),
    ("破壊時", re.compile(r"【破壊時】")),
    ("自分のターン終了時", re.compile(r"【自分のターン終了時】")),
    ("相手のターン", re.compile(r"【相手のターン】")),
    ("自分のターン", re.compile(r"【自分のターン】")),
]

_CONDITION_TEXT_PATTERNS = [
    ("デッキ", re.compile(r"《デッキ》")),
    ("ベース", re.compile(r"《ベース》")),
    ("トラッシュ", re.compile(r"《トラッシュ》")),
    ("付与能力", re.compile(r"《付与能力》")),
]


def _append_unique(out: list[str], value: str | None) -> None:
    if value and value not in out:
        out.append(value)


def official_effect_tags_for_card(card: Any) -> list[str]:
    labels: list[str] = []
    for keyword in getattr(card, "keywords", []):
        _append_unique(labels, KEYWORD_LABELS.get(keyword))
    for effect in getattr(card, "effects", []):
        _append_unique(labels, effect.official_effect)
    return labels


def official_timing_tags_for_card(card: Any) -> list[str]:
    labels: list[str] = []
    for effect in getattr(card, "effects", []):
        _append_unique(labels, effect.official_timing or TIMING_LABELS.get(effect.timing))
    text = getattr(card, "ability_jp", "") or ""
    for label, pattern in _TIMING_TEXT_PATTERNS:
        if pattern.search(text):
            _append_unique(labels, label)
    return labels


def official_condition_tags_for_card(card: Any) -> list[str]:
    labels: list[str] = []
    for effect in getattr(card, "effects", []):
        _append_unique(labels, effect.official_condition)
    text = getattr(card, "ability_jp", "") or ""
    for label, pattern in _CONDITION_TEXT_PATTERNS:
        if pattern.search(text):
            _append_unique(labels, label)
    return labels
