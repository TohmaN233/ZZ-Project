from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.pc01 import _card_from_row


CARD_ID = "red_02_03_02r_01"


def _fire_rain(source, state, ctx) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: engine.effective_bp(target) < target.card.bp,
        source=source,
    )
    if targets:
        engine.destroy_target(targets[0], source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_fire_rain,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"bp_below_original": True},
            official_effect="本来よりBPが低い相手のミニオン1体を破壊する",
            official_timing="メイン/フラッシュ",
        )
    )
    return card
