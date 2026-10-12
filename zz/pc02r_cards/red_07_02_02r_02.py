from __future__ import annotations

from copy import copy
from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_07_02_02r_02"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_granted_minion_at_own_turn_end(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.destroy_target(source, source)


def _own_turn_ends(source: CardInstance, state: Any, _ctx: Context) -> bool:
    return state.active is source.owner


def _put_red_dragon_from_hand(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    eligible = lambda candidate: (
        candidate.card.type is CardType.F_MINION
        and candidate.card.printed_color is Color.RED
        and "ドラゴン" in candidate.card.race_jp
    )
    targets = engine.select_target(
        source.owner,
        "hand_field_minion",
        0,
        1,
        filter_fn=eligible,
        source=source,
    )
    if not targets:
        return
    target = targets[0]
    if target.owner is not source.owner or target.area is not AreaType.HAND or not eligible(target):
        raise RuntimeError("Shaina selected a card outside the Red Field Dragon hand zone")

    engine.summon_from_hand(source.owner, target)

    # Clone the card definition so the granted abilities belong to this instance only.
    granted_card = copy(target.card)
    granted_card.cost = dict(granted_card.cost)
    granted_card.keywords = list(granted_card.keywords)
    granted_card.effects = list(granted_card.effects)
    granted_card.triggers = list(granted_card.triggers)
    granted_card.ability_jp = (
        granted_card.ability_jp
        + "\n【常時】このミニオンは移動できない。"
        + "\n【自分のターン終了時】このミニオンを破壊する。"
    )
    granted_card.ability_en = (
        granted_card.ability_en
        + "\n[Passive] This minion cannot move."
        + "\n[At the End of Your Turn] Destroy this minion."
    )
    granted_card.effects.append(
        EffectSpec(
            timing=EffectTiming.TURN_END,
            fn=_destroy_granted_minion_at_own_turn_end,
            condition=_own_turn_ends,
            active_areas=(AreaType.FIELD,),
            official_effect="自分のターン終了時にこのミニオンを破壊する",
            official_timing="自分のターン終了時",
        )
    )
    target.card = granted_card
    target.flags.add("cannot_move")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_put_red_dragon_from_hand,
            condition=_this_minion_was_summoned,
            target_kind="hand_card",
            min_targets=0,
            max_targets=1,
            optional=True,
            params={
                "card_type": CardType.F_MINION.value,
                "color": Color.RED.name,
                "race": "ドラゴン",
            },
            official_effect="手札の赤いドラゴン族Field Minion1枚を場に出し、移動不可と自分のターン終了時破壊を付与する",
            official_timing="召喚時",
        )
    ]
    return card
