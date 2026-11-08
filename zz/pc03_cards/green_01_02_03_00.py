from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_01_02_03_00"


def _boost_by_green_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} BP effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        source=source,
    )
    if not targets:
        return
    green_mana_count = sum(
        1
        for mana in source.owner.base
        if engine._mana_color_of(mana) is Color.GREEN
    )
    engine.modify_stat(
        targets[0],
        bp_delta=100 * green_mana_count,
        duration="turn",
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _boost_by_green_mana,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            official_effect="このターン中、自分のミニオン1体を、自分の緑マナ1つ毎にBP+100する。",
            official_timing="メイン/フラッシュ",
        )
    )
    return card