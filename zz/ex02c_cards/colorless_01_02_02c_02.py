from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_01_02_02c_02"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "place_base_from_deck",
                EffectTiming.ON_DESTROY,
                condition=_this_minion_was_destroyed,
                target_kind="deck_base_minion",
                min_targets=1,
                max_targets=1,
                optional=False,
                race="アイテム",
                color=Color.GREEN,
                card_type=CardType.B_MINION,
                rested=True,
                active_areas=(AreaType.TRASH,),
                official_effect=(
                    "自分はデッキの中から種族「アイテム」を持つ緑のベース・ミニオンカード1枚を"
                    "レスト状態でベースに置く。その後、自分のデッキをシャッフルする。"
                ),
                official_timing="破壊時",
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
