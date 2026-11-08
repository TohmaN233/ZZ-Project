from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_02_02_03_00"


def _self_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _buff_then_schedule_destroy(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} requires an Engine")
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    for target in targets:
        engine.modify_stat(target, bp_delta=400, dp_delta=1, duration="turn")

        def destroy_at_turn_end(target=target, source=source, engine=engine) -> None:
            if target.area is AreaType.FIELD:
                engine.destroy_target(target, source=source)

        engine.schedule_turn_end_effect(source.owner, destroy_at_turn_end)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _buff_then_schedule_destroy,
            condition=_self_cast,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            official_effect="このターン中、自分のミニオン1体をBP+400/DP+1する。このターン終了時、そのミニオンを破壊する。",
            official_timing="メイン/フラッシュ",
        )
    )
    return card
