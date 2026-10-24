from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_05_02_02c_00'


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_double_sword_keywords(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    engine.add_keyword(source, Keyword.RUSH, duration="permanent")
    has_another_minion = any(
        minion is not source
        and minion.card.type in (CardType.F_MINION, CardType.B_MINION)
        for minion in source.owner.field
    )
    if not has_another_minion:
        engine.add_keyword(source, Keyword.REAWAKEN, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # These are granted by the summon effect, not intrinsic keywords printed on
    # the card face. KAGO is permission to receive a Bless, not a mana keyword.
    card.keywords = [
        keyword
        for keyword in card.keywords
        if keyword not in (Keyword.RUSH, Keyword.REAWAKEN, Keyword.KAGO, Keyword.BLESS)
    ]
    card.ignore_bless_conditions = True
    card.max_blessings = 2
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_grant_double_sword_keywords,
            condition=_self_source,
            active_areas=(AreaType.FIELD,),
            official_effect=(
                "このミニオンに［襲撃］を付与し、他に自分のミニオンがいない場合、"
                "このミニオンに［再起］を付与する。"
            ),
            official_timing="召喚時",
        )
    )
    return card
