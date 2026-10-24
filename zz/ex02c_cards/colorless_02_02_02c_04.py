from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_02_02_02c_04"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    search = build_effect(
        "search_deck_to_hand",
        EffectTiming.ON_SUMMON,
        condition=_self_source,
        target_kind="deck_base_minion",
        optional=True,
        race="アイテム",
        card_type=CardType.B_MINION,
        active_areas=(AreaType.FIELD,),
        official_effect=(
            "自分はデッキの中から種族「アイテム」を持つベース・ミニオンカード1枚を"
            "公開して手札に加えることができる。その後、自分のデッキをシャッフルする。"
        ),
        official_timing="召喚時＆スイッチ",
    )
    search.params["ex02c_switch_races"] = ["黒の剣士"]
    card.effects.append(search)
    return card
