from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_03_02c_01"


def _weaken_opponent_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if not targets:
        return
    bp_delta = -600 if any(
        "黒の剣士" in ci.card.race_jp.split("|") for ci in source.owner.field
    ) else -300
    engine.modify_stat(targets[0], bp_delta=bp_delta, duration="turn")


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_weaken_opponent_minion,
            condition=_this_magic_was_cast,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            official_effect="このターン中、相手のミニオン1体をBP-300する。自分の種族「黒の剣士」を持つミニオンがいる場合、代わりにBP-600する",
            official_timing="メイン/フラッシュ",
            active_areas=(AreaType.TRASH,),
        )
    ]
    return card
