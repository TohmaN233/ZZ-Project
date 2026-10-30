from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_00_01_02c_00"


def _black_swordsman(mana: CardInstance, target: CardInstance, _state: Any) -> bool:
    return "黒の剣士" in target.card.race_jp.split("|")


def _host_is_attacking_with_ten_mana(source: CardInstance, _state: Any, ctx: Context) -> bool:
    host = ctx.source
    if (
        source.area is not AreaType.BLESSING
        or not isinstance(host, CardInstance)
        or host.area is not AreaType.FIELD
        or host.owner is not source.owner
        or source not in host.blessings
    ):
        return False
    attached_mana_count = sum(len(minion.blessings) for minion in source.owner.field)
    return len(source.owner.base) + attached_mana_count >= 10


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords.append(Keyword.KAGO)
    card.bless_condition = _black_swordsman
    card.effects.append(
        build_effect(
            "destroy_targets",
            EffectTiming.ON_ATTACK,
            condition=_host_is_attacking_with_ten_mana,
            target_kind="enemy_minion",
            max_targets=1,
            active_areas=(AreaType.BLESSING,),
            granted_by_blessing=True,
            official_effect=(
                "自分のマナが10以上ある場合、相手のミニオン1体を破壊する。"
            ),
            official_timing="アタック時",
            official_condition="自分のマナが10以上ある場合",
        )
    )
    return card
