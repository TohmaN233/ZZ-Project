from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_04_02_02r_03"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _is_printed_colorless_minion(target: CardInstance) -> bool:
    return (
        target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and target.card.printed_color is Color.COLORLESS
    )


def _destroy_selected_colorless_minion(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=_is_printed_colorless_minion,
        source=source,
    )
    if not targets:
        # The summon still resolves when no opposing Colorless Minion is on the Field.
        return
    if len(targets) != 1 or not isinstance(targets[0], CardInstance):
        raise RuntimeError("Lightningfall requires one opposing Minion target")
    target = targets[0]
    if target.owner is source.owner or not _is_printed_colorless_minion(target):
        raise RuntimeError("Lightningfall selected a non-opposing or non-colorless Minion")
    if target.area is not AreaType.FIELD:
        raise RuntimeError("Lightningfall target is not on the Field")
    engine.destroy_target(target, source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_destroy_selected_colorless_minion,
            condition=_this_minion_was_summoned,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"color": Color.COLORLESS},
            official_effect="相手の無色のミニオン1体を破壊する",
            official_timing="召喚時",
        )
    ]
    return card
