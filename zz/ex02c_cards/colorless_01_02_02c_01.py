from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_01_02_02c_01"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "search_deck_to_hand",
                EffectTiming.MOVE_TO_BASE,
                condition=_self_source,
                target_kind="deck_base_minion",
                optional=True,
                race="ウイング",
                color=Color.YELLOW,
                card_type=CardType.B_MINION,
                active_areas=(AreaType.BASE,),
                official_effect=(
                    "自分はデッキの中から種族「ウイング」を持つ黄のベース・ミニオンカード1枚を"
                    "公開して手札に加えることができる。その後、自分のデッキをシャッフルする。"
                ),
                official_timing="後退時",
            ),
            build_effect(
                "move_to_base_rested",
                EffectTiming.MOVE_TO_BASE,
                condition=_self_source,
                active_areas=(AreaType.BASE,),
                official_effect="このミニオンはベースに移動するとき、レスト状態で移動する。",
                official_timing="常時",
            ),
        ]
    )
    return card
