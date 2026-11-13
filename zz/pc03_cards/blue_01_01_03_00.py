from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import CardType, Color
from zz.pc01 import _card_from_row


CARD_ID = "blue_01_01_03_00"


def _has_blue_or_colorless_evoker_mana(source: Any, _state: Any, _ctx: Any) -> bool:
    return any(
        mana.card.type is CardType.B_MINION
        and mana.card.mana_color in (Color.BLUE, Color.COLORLESS)
        and "エヴォーカ" in mana.card.race_jp
        for mana in source.owner.base
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "return_from_trash_to_hand",
                EffectTiming.ON_DESTROY,
                condition=_has_blue_or_colorless_evoker_mana,
                self_destroy_only=True,
                target_kind="trash_magic_cost_at_most_4",
                min_targets=1,
                max_targets=1,
                optional=False,
                color=Color.BLUE,
                card_type=CardType.MAGIC,
                max_cost=4,
                official_effect="自分のトラッシュにあるコスト4以下の青のマジックカード1枚を手札に戻す",
                official_timing="破壊時",
                official_condition="自分の種族「エヴォーカ」を持つ、青または無色のマナがある場合",
            ),
            build_effect(
                "move_to_base_rested",
                EffectTiming.MOVE_TO_BASE,
                official_effect="このミニオンはベースに移動するとき、レスト状態で移動する",
                official_timing="常時",
            ),
        ]
    )
    return card
