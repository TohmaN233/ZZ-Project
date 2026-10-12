from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.pc02 import _replacement_iid


CARD_ID = "yellow_07_02_02r_00"
_TRANSFORMED_CARD_ID = "yellow_07_02_02r_01"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _yellow_blessed_this_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        ctx.source is source
        and isinstance(ctx.target, CardInstance)
        and state.engine._mana_color_of(ctx.target) is Color.YELLOW
    )


def _put_field_minion_from_hand(
    engine: Any,
    player: Any,
    card: CardInstance,
    source: CardInstance,
) -> None:
    if card not in player.hand or card.area is not AreaType.HAND:
        raise RuntimeError(f"{CARD_ID} selected a card that is no longer in its owner's hand")
    if card.card.type is not CardType.F_MINION:
        raise RuntimeError(f"{CARD_ID} selected non-Field Minion {card.card.id} from hand")
    engine._make_field_space(player, _replacement_iid(engine, player, source))
    player.hand.remove(card)
    card.area = AreaType.FIELD
    card.rested = False
    card.summoning_sickness = True
    player.field.append(card)
    engine._record_zone_move(card, AreaType.HAND, AreaType.FIELD)
    engine._emit_enter_field(player, card)
    engine.triggers.resolve_all()


def _put_low_cost_field_minion_from_hand(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    eligible = [
        candidate
        for candidate in source.owner.hand
        if candidate.card.type is CardType.F_MINION
        and sum(candidate.card.cost.values()) <= 4
    ]
    if not eligible:
        return
    selected = engine.select_target(
        source.owner,
        "hand_card",
        0,
        1,
        filter_fn=lambda candidate: (
            candidate.card.type is CardType.F_MINION
            and sum(candidate.card.cost.values()) <= 4
        ),
        source=source,
    )
    if not selected:
        return
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one Field Minion costing at most 4, received {len(selected)}")
    _put_field_minion_from_hand(engine, source.owner, selected[0], source)


def _transform_with_yellow_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires its attached Yellow Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")
    if state.engine._mana_color_of(mana) is not Color.YELLOW:
        raise RuntimeError(f"{CARD_ID} transformation received a non-Yellow Bless")
    try:
        transformed = copy(CARD_REGISTRY[_TRANSFORMED_CARD_ID])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} transformed face is not registered: {_TRANSFORMED_CARD_ID}") from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)

    engine = state.engine
    source.blessings.remove(mana)
    engine._reset_card_zone_state(mana)
    mana.area = AreaType.REMOVED
    mana.owner.removed.append(mana)
    engine._record_zone_move(mana, AreaType.BLESSING, AreaType.REMOVED)
    engine.transform_card(source, transformed, target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.can_bless_while_rested = False
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_put_low_cost_field_minion_from_hand,
            condition=_self_summoned,
            target_kind="hand_card",
            min_targets=0,
            max_targets=1,
            optional=True,
            params={"puts_targets_on_field": True, "card_type": CardType.F_MINION, "max_cost": 4},
            official_effect="手札から本来のコスト4以下のField Minion1体を出す",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_with_yellow_bless,
            condition=_yellow_blessed_this_source,
            active_areas=(AreaType.FIELD,),
            official_effect="黄のBless Manaを除外して「天空猛虎」センシュウに変形する",
            official_timing="加護時",
        ),
    ]
    return card
