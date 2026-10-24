from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_03_03_02c_00"


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _rest_or_destroy_target(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if not targets:
        return
    target = targets[0]
    if engine._card_color(target.card) is Color.COLORLESS:
        engine.destroy_target(target, source=source)
    else:
        engine.rest_target(target)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_rest_or_destroy_target,
            condition=_this_magic_was_cast,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            official_effect=(
                "相手のミニオン1体を選択する。そのミニオンが有色の場合、レストする。"
                "そのミニオンが無色の場合、破壊する。"
            ),
            official_timing="メイン／フラッシュ",
            active_areas=(AreaType.TRASH,),
        )
    )
    return card
