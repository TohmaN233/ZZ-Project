from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_05_01_03_01"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "place_base_from_deck",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="deck_base_minion",
            min_targets=0,
            max_targets=1,
            optional=True,
            race="エヴォーカー",
            card_type=CardType.B_MINION,
            colors_any=(Color.GREEN, Color.COLORLESS),
            rested=True,
            activate_placed_effect=True,
            official_effect=(
                "自分はデッキの中から種族「エヴォーカー」を持つ緑または無色の"
                "ベース・ミニオンカード1枚を、レスト状態でべースに置くことができる。"
                "その後、自分のデッキをシャッフルし、置かれたマナの【配置時】効果を発揮させる。"
            ),
            official_timing="召喚時",
        )
    )
    return card
