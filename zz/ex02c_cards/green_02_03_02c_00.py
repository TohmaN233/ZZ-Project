from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_02_03_02c_00"


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _boost_and_set_dp_to_zero(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "any_minion", 1, 1, source=source)
    if not targets:
        return
    engine.modify_stat(targets[0], bp_delta=300, dp_set=0, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【メイン】／【フラッシュ】このターン中、ミニオン1体をBP+300して、DPを0にする。"
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_boost_and_set_dp_to_zero,
            condition=_this_magic_was_cast,
            target_kind="any_minion",
            min_targets=1,
            max_targets=1,
            official_effect="このターン中、ミニオン1体をBP+300して、DPを0にする。",
            official_timing="メイン／フラッシュ",
            active_areas=(AreaType.TRASH,),
        )
    )
    return card
