from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable

from zz.cards import CARD_REGISTRY, register
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.forces import Force
from zz.model import Card, CardInstance, Context
from zz.pc01 import DEFAULT_CARD_TSV, _card_from_row


EX01_PACK_JP = "EX:01 魔術都市の9戦士"


def _selected_force(source: CardInstance, force_id: str) -> bool:
    return any(instance.force.id == force_id for instance in source.owner.forces)


def twin_free_cost_reduction(player: Any, source: CardInstance, state: Any) -> int:
    if (
        source.card.id == "colorless_05_02_ex01_02"
        and state.active is player
        and source.area is AreaType.HAND
        and _selected_force(source, "force_so")
    ):
        return 2
    return 0


def memoria_free_cost_reduction(player: Any, source: CardInstance, state: Any) -> int:
    if (
        source.card.id == "colorless_08_02_ex01_00"
        and state.active is player
        and source.area is AreaType.HAND
    ):
        return sum(3 for force in player.forces if force.destroyed)
    return 0


def _self_source_with_force(force_id: str) -> Callable[[CardInstance, Any, Context], bool]:
    def condition(source: CardInstance, state: Any, ctx: Context) -> bool:
        return ctx.source is source and _selected_force(source, force_id)

    return condition


def _turn_end_with_force(
        force_id: str,
        *,
        own_turn: bool,
) -> Callable[[CardInstance, Any, Context], bool]:
    def condition(source: CardInstance, state: Any, ctx: Context) -> bool:
        is_own_turn = ctx.controller is source.owner
        return is_own_turn is own_turn and _selected_force(source, force_id)

    return condition


def _ring_trigger(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and _selected_force(source, "force_rin")


def _buff_self_for_turn(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=300)


def _vixon_trigger(source: CardInstance, state: Any, ctx: Context) -> bool:
    eng = state.engine
    return (
        ctx.controller is not source.owner
        and _selected_force(source, "force_kai")
        and not eng.player_was_damaged_this_turn(source.owner)
    )


def _grant_vixon_bp(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=200, duration="permanent")


def _put_low_cost_minion_from_hand(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    chosen = eng.select_target(
        source.owner,
        "hand_field_minion_cost_at_most_2",
        0,
        1,
        source=source,
    )
    if not chosen:
        return
    replace_iid = None
    if len(source.owner.field) >= 5:
        replacements = eng.select_target(source.owner, "ally_minion", 1, 1, source=source)
        if not replacements:
            return
        replace_iid = replacements[0].iid
    eng.put_field_minion_from_hand(
        source.owner,
        chosen[0],
        replace_field_iid=replace_iid,
    )


def _riza_trigger(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        state.active is not source.owner
        and ctx.controller is source.owner
        and _selected_force(source, "force_so2")
    )


def _refresh_self(source: CardInstance, state: Any, ctx: Context) -> None:
    source.rested = False


def _heal_owner(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.heal(source.owner, 1)


def _karen_force_destroyed(source: CardInstance, state: Any, ctx: Context) -> bool:
    return getattr(ctx, "target", None) is not None


def _grant_selected_force_ability(source: CardInstance, state: Any, ctx: Context) -> None:
    chosen = state.engine.select_target(source.owner, "force_catalog", 1, 1, source=source)
    if not chosen:
        return
    force = chosen[0]
    if not isinstance(force, Force):
        raise TypeError("force_catalog must return a Force")
    state.engine.grant_force_ability(source, force.id)


def _revenge_dragon_trigger(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and state.engine.destroyed_forces_count(source.owner) > 0


def _destroy_for_each_destroyed_force(source: CardInstance, state: Any, ctx: Context) -> None:
    eng = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    count = min(eng.destroyed_forces_count(source.owner), len(opponent.field))
    if count <= 0:
        return
    targets = eng.select_target(source.owner, "enemy_minion", count, count, source=source)
    for target in targets:
        eng.destroy_target(target, source)


def _effect(
        timing: EffectTiming,
        fn: Callable[[CardInstance, Any, Context], None],
        *,
        condition: Callable[[CardInstance, Any, Context], bool] | None = None,
        target_kind: str | None = None,
        min_targets: int = 1,
        max_targets: int = 1,
        optional: bool = False,
        official_effect: str,
        official_timing: str,
        official_condition: str | None = None,
        params: dict[str, Any] | None = None,
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


_EX01_EFFECTS_BY_ID: dict[str, tuple[EffectSpec, ...]] = {
    "colorless_02_02_ex01_00": (
        build_effect(
            "refresh_self",
            EffectTiming.MOVE_TO_BASE,
            condition=_self_source_with_force("force_sho"),
            official_condition="翔のフォース選択時",
            active_areas=(AreaType.BASE,),
        ),
        build_effect(
            "refresh_self",
            EffectTiming.ON_MOVE_TO_FIELD,
            condition=_self_source_with_force("force_sho"),
            official_condition="翔のフォース選択時",
        ),
    ),
    "colorless_03_02_ex01_00": (
        build_effect(
            "look_top_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source_with_force("force_chi"),
            target_kind="top2_card",
            top_n=2,
            official_effect="公開して手札に加える",
            official_condition="知のフォース選択時",
        ),
    ),
    "colorless_03_02_ex01_01": (
        _effect(
            EffectTiming.ON_ATTACK,
            _buff_self_for_turn,
            condition=_ring_trigger,
            official_effect="BP+300",
            official_timing="アタック時",
            official_condition="輪のフォース選択時",
        ),
        _effect(
            EffectTiming.ON_BLOCK,
            _buff_self_for_turn,
            condition=_ring_trigger,
            official_effect="BP+300",
            official_timing="ブロック時",
            official_condition="輪のフォース選択時",
        ),
    ),
    "colorless_04_02_ex01_00": (
        _effect(
            EffectTiming.TURN_END,
            _grant_vixon_bp,
            condition=_vixon_trigger,
            official_effect="BP+200を付与",
            official_timing="相手のターン終了時",
            official_condition="凱のフォース選択時・プレイヤーダメージなし",
        ),
    ),
    "colorless_04_02_ex01_01": (
        _effect(
            EffectTiming.ON_SUMMON,
            _put_low_cost_minion_from_hand,
            condition=_self_source_with_force("force_e"),
            target_kind="hand_field_minion_cost_at_most_2",
            min_targets=0,
            max_targets=1,
            optional=True,
            official_effect="手札からフィールド・ミニオンを出す",
            official_timing="召喚時",
            official_condition="悪のフォース選択時・本来のコスト2以下",
            params={"puts_targets_on_field": True},
        ),
    ),
    "colorless_04_02_ex01_02": (
        build_effect(
            "place_colorless_mana",
            EffectTiming.ON_SUMMON,
            condition=_self_source_with_force("force_kon"),
            rested=True,
            official_condition="混のフォース選択時",
        ),
    ),
    "colorless_05_02_ex01_00": (
        build_effect(
            "draw_cards",
            EffectTiming.TURN_END,
            condition=_turn_end_with_force("force_sei", own_turn=True),
            amount=1,
            official_condition="聖のフォース選択時",
        ),
    ),
    "colorless_05_02_ex01_01": (
        _effect(
            EffectTiming.ON_CARD_USED,
            _refresh_self,
            condition=_riza_trigger,
            official_effect="アクティブにする",
            official_timing="相手のターン・カード使用時",
            official_condition="甦のフォース選択時",
        ),
    ),
    "colorless_07_02_ex01_00": (
        _effect(
            EffectTiming.ON_ATTACK,
            _heal_owner,
            condition=lambda source, state, ctx: ctx.source is source,
            official_effect="プレイヤーを1回復",
            official_timing="アタック時",
        ),
        _effect(
            EffectTiming.ON_FORCE_DESTROYED,
            _refresh_self,
            condition=_karen_force_destroyed,
            official_effect="アクティブにする",
            official_timing="フォース破壊時",
        ),
    ),
    "colorless_08_02_ex01_00": (
        _effect(
            EffectTiming.ON_SUMMON,
            _grant_selected_force_ability,
            condition=lambda source, state, ctx: ctx.source is source,
            target_kind="force_catalog",
            official_effect="フォースの固有能力を付与",
            official_timing="召喚時",
        ),
    ),
    "colorless_09_02_ex01_00": (
        _effect(
            EffectTiming.ON_SUMMON,
            _destroy_for_each_destroyed_force,
            condition=_revenge_dragon_trigger,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=2,
            official_effect="破壊",
            official_timing="召喚時",
            official_condition="自分の破壊されたフォース数",
            params={"exact_target_count_from_own_destroyed_forces": True},
        ),
    ),
}


def _ex01_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("pack_jp_official") == EX01_PACK_JP
        ]
    rows.sort(key=lambda row: int(row.get("official_order") or 999999))
    return rows


def _ex01_card_from_row(row: dict[str, str]) -> Card:
    card = _card_from_row(row)
    card.effects = list(_EX01_EFFECTS_BY_ID.get(card.id, ()))
    return card


def register_ex01_cards(path: Path = DEFAULT_CARD_TSV) -> list[str]:
    registered_ids: list[str] = []
    for row in _ex01_rows(path):
        card = _ex01_card_from_row(row)
        if card.id not in CARD_REGISTRY:
            register(card)
        registered_ids.append(card.id)
    expected = set(_EX01_EFFECTS_BY_ID) | {"colorless_05_02_ex01_02"}
    if set(registered_ids) != expected:
        raise RuntimeError(
            f"EX01 inventory/effect mapping mismatch: registered={sorted(registered_ids)}, expected={sorted(expected)}"
        )
    return registered_ids


EX01_CARD_IDS = register_ex01_cards()
