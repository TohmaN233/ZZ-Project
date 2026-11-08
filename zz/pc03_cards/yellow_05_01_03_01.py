from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_05_01_03_01"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _self_attacked(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _buff_self_and_other(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} attack effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "other_ally_minion",
        1,
        1,
        source=source,
        filter_fn=lambda target: target is not source and target.card.type is CardType.F_MINION,
    )
    engine.modify_stat(source, bp_delta=200, duration="turn")
    for target in targets:
        engine.modify_stat(target, bp_delta=200, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.CONTINUOUS,
                lambda source, state, ctx: None,
                params={"pc03_summon_suppression": True},
                official_effect="このミニオンがフィールドにいる間、黄以外の全てのミニオンの召喚時効果を無効にする。",
                official_timing="召喚時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _buff_self_and_other,
                condition=_self_attacked,
                target_kind="other_ally_minion",
                min_targets=1,
                max_targets=1,
                official_effect="このミニオンと自分の他のミニオン1体にBP+200を付与する。",
                official_timing="アタック時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
