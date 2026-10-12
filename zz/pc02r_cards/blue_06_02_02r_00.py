from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType
from zz.model import CardInstance, Context, Player
from zz.pc01 import _card_from_row


CARD_ID = "blue_06_02_02r_00"


def _this_minion_damaged_opponent_life(source: CardInstance, state: Any, ctx: Context) -> bool:
    if state.active is not source.owner:
        return False
    opponent = state.players[1 - state.players.index(source.owner)]
    return (
        ctx.source is source
        and ctx.target is opponent
        and any(ci.card.type in (CardType.B_MINION, CardType.F_MINION) for ci in source.owner.base)
    )


def _move_minion_mana_to_field(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    owner = source.owner
    targets = engine.select_target(owner, "ally_minion_base", 1, 1, source=source)
    if not targets:
        return
    replace_iid = None
    if len(owner.field) >= 5:
        replacements = engine.select_target(owner, "ally_minion", 1, 1, source=source)
        if not replacements:
            return
        replace_iid = replacements[0].iid
    engine.move_base_minion_to_field(owner, targets[0], rested=False, replace_field_iid=replace_iid)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_DAMAGE_PLAYER,
            fn=_move_minion_mana_to_field,
            condition=_this_minion_damaged_opponent_life,
            target_kind="ally_minion_base",
            official_effect="相手プレイヤーにダメージを与えるたび、自分のミニオンマナ1つをアクティブでフィールドへ移動する",
            official_timing="自分のターン中のダメージ時",
        )
    ]
    return card
