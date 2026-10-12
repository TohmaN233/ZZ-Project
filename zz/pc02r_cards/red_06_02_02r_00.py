from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_06_02_02r_00"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)

    def _create_lava_slime(source: CardInstance, state: Any, _ctx: Context) -> None:
        # Putting the named card into play is not summoning it: retain its
        # identity and effects without firing ON_SUMMON recursively.
        state.engine.create_field_minions(source.owner, [card], source=source)

    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_create_lava_slime,
            condition=_this_minion_was_summoned,
            template_id="create_field_minions",
            params={"amount": 1, "generated_card_id": CARD_ID},
            official_effect="ラヴァ・スライム1体を出す",
            official_timing="召喚時",
        )
    ]
    return card
