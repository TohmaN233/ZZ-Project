from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_06_01_03_02"


def _self_attacked(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _own_minion_mana_moved(source: CardInstance, state: Any, ctx: Context) -> bool:
    moved = ctx.source
    return bool(
        source.area is AreaType.FIELD
        and source in source.owner.field
        and state.active is source.owner
        and ctx.controller is source.owner
        and isinstance(moved, CardInstance)
        and moved is not source
        and moved.owner is source.owner
        and moved.area is AreaType.FIELD
        and moved in source.owner.field
        and moved.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _move_blue_minion_mana_to_field(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} attack effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "ally_minion_base",
        0,
        1,
        filter_fn=lambda target: (
            target.owner is source.owner
            and target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and engine._mana_color_of(target) is Color.BLUE
        ),
        source=source,
    )
    if targets:
        engine.move_base_minion_to_field(source.owner, targets[0], rested=False)


def _grant_stats(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} movement effect requires an Engine")
    engine.modify_stat(source, bp_delta=100, dp_delta=1, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【アタック時】自分のミニオンカードである青マナ1つを、フィールドにアクティブ状態で移動させることができる。\n"
        "【自分のターン】他の自分のミニオンカードであるマナがフィールドに移動するたび、"
        "このミニオンにBP+100/DP+1を付与する。"
    )
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _move_blue_minion_mana_to_field,
                condition=_self_attacked,
                target_kind="ally_minion_base",
                min_targets=0,
                max_targets=1,
                optional=True,
                params={"mana_color": Color.BLUE},
                official_effect="自分のミニオンカードである青マナ1つを、フィールドにアクティブ状態で移動させることができる。",
                official_timing="アタック時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_MOVE_TO_FIELD,
                _grant_stats,
                condition=_own_minion_mana_moved,
                official_effect="他の自分のミニオンカードであるマナがフィールドに移動するたび、このミニオンにBP+100/DP+1を付与する。",
                official_timing="自分のターン",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
