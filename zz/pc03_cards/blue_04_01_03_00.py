from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_04_01_03_00"
REWARD_CARD_IDS = (
    "blue_02_03_00_00",
    "blue_03_03_00_01",
    "blue_03_03_00_00",
)


def _has_own_arcana(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return (
        ctx.source is source
        and source.area is AreaType.FIELD
        and any(
            minion.area is AreaType.FIELD
            and "アルカナ" in minion.card.race_jp.split("|")
            for minion in source.owner.field
        )
    )


def _add_named_magic_from_outside(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(source.owner, "outside_card", 1, 1, source=source)
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one named Magic card, got {len(targets)}")
    engine.add_card_from_outside_to_hand(source.owner, targets[0].id)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _add_named_magic_from_outside,
            condition=_has_own_arcana,
            target_kind="outside_card",
            params={"outside_card_ids": list(REWARD_CARD_IDS)},
            official_effect=(
                "自分の種族「アルカナ」を持つミニオンがいる場合、"
                "「コントロールカレント」「タイダルウェイブ」「ユリーカのワルツ」のうち"
                "カード1枚を手札に加える。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
