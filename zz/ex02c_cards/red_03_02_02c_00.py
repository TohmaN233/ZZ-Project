from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_03_02_02c_00"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _chain_item_mana(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and any(
        mana.area is AreaType.BASE and "アイテム" in mana.card.race_jp
        for mana in source.owner.base
    )


def _sword_team_aura(
    source: CardInstance,
    target: CardInstance,
    state: Any,
) -> tuple[int, int]:
    if (
        state.active is source.owner
        and target.owner is source.owner
        and target.area is AreaType.FIELD
        and target is not source
        and "ソード" in target.card.race_jp
    ):
        return 100, 0
    return 0, 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.aura = _sword_team_aura
    card.effects = list(card.effects) + [
        build_effect(
            "draw_cards",
            EffectTiming.ON_SUMMON,
            condition=lambda source, state, ctx: (
                _this_minion_was_summoned(source, state, ctx)
                and _chain_item_mana(source, state, ctx)
            ),
            amount=1,
            official_effect="カードを1枚引く",
            official_timing="召喚時",
            official_condition="連携：「アイテム」",
        )
    ]
    return card
