from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_03_01_03_01"


def _is_colored_base_minion(target: CardInstance, owner: Any) -> bool:
    return (
        target.owner is owner
        and target.area is AreaType.BASE
        and target.card.type is CardType.B_MINION
        and target.card.printed_color is not None
        and target.card.printed_color is not Color.COLORLESS
    )


def _has_colored_base_minion(source: CardInstance, state: Any, ctx: Context) -> bool:
    if source.area is not AreaType.FIELD or ctx.source is not source:
        return False
    return any(_is_colored_base_minion(mana, source.owner) for mana in source.owner.base)


def _copy_colored_base_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} copy effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "ally_base",
        1,
        1,
        filter_fn=lambda target: _is_colored_base_minion(target, source.owner),
        source=source,
    )
    if not targets:
        raise RuntimeError(f"{CARD_ID} resolved without a legal colored Base Minion target")
    engine.add_card_from_outside_to_hand(source.owner, targets[0].card.id)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _copy_colored_base_minion,
            condition=_has_colored_base_minion,
            target_kind="ally_base",
            min_targets=1,
            max_targets=1,
            params={
                "card_type": CardType.B_MINION,
                "exclude_color": Color.COLORLESS,
            },
            official_effect="自分の有色のベース・ミニオンカードであるマナ1つと同じカード1枚を手札に加える。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card