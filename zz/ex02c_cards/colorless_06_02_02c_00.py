from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.engine import FIELD_CAP
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_06_02_02c_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_card_destroyed_in_minion_battle(
    source: CardInstance,
    _state: Any,
    ctx: Context,
) -> bool:
    if not hasattr(ctx, "battle_participants"):
        raise RuntimeError("battle destruction context is missing battle_participants")
    participants = ctx.battle_participants
    if participants is None:
        return False
    if not isinstance(participants, tuple) or len(participants) != 2:
        raise RuntimeError(f"{CARD_ID} received malformed battle_participants: {participants!r}")
    return (
        ctx.target is source
        and source.area is AreaType.TRASH
        and source in participants
        and isinstance(ctx.source, CardInstance)
        and ctx.source in participants
        and ctx.source is not source
        and ctx.source.owner is not source.owner
        and ctx.source.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _heal_owner(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.heal(source.owner, 1)


def _pay_life_and_return(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    owner = source.owner
    engine._damage_player(owner, 1, source=source)
    replacement_iid = None
    if len(owner.field) >= FIELD_CAP:
        eligible = engine._eligible_targets(owner, "ally_minion", source=source)
        if not eligible:
            raise RuntimeError(f"{CARD_ID} cannot replace a full Field without an eligible Minion")
        replacements = engine.select_target(owner, "ally_minion", 1, 1, source=source)
        if len(replacements) != 1:
            raise RuntimeError(f"{CARD_ID} expected one Field replacement, got {len(replacements)}")
        replacement_iid = replacements[0].iid
    engine.summon_from_trash(owner, source, replace_field_iid=replacement_iid)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_heal_owner,
            condition=_self_summoned,
            params={"ex02c_switch_races": ["黒の剣士"]},
            active_areas=(AreaType.FIELD,),
            official_effect="自分のプレイヤーを1回復する",
            official_timing="召喚時＆スイッチ",
        ),
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_pay_life_and_return,
            condition=_this_card_destroyed_in_minion_battle,
            optional=True,
            template_id="summon_from_trash",
            params={"field_entry_count": 1},
            active_areas=(AreaType.TRASH,),
            official_effect="ミニオンとのバトルで破壊された場合、自分のプレイヤーに1ダメージを与えることができる。そうした場合、このカードをフィールドに出す",
            official_timing="破壊時",
        ),
    ]
    return card
