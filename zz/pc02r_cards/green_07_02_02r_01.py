from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_07_02_02r_01"


def _this_rory_was_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_rory_attacks(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _banish_all_neutral_minions(_source: CardInstance, state: Any, _ctx: Context) -> None:
    from zz.pc02 import _remove_target

    engine = state.engine
    for player in state.players:
        for target in list(player.field):
            if (
                target.card.type in (CardType.F_MINION, CardType.B_MINION)
                and engine._card_color(target.card) is Color.COLORLESS
            ):
                _remove_target(engine, target, _source)


def _rest_selected_enemy_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if not engine._eligible_targets(source.owner, "enemy_minion", source=source):
        return
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} attack trigger selected {len(targets)} targets")
    for target in targets:
        engine.rest_target(target)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.RUSH not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.RUSH]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_banish_all_neutral_minions,
            condition=_this_rory_was_transformed,
            active_areas=(AreaType.FIELD,),
            official_effect="変形時、無色のミニオン全てを除外する",
            official_timing="変形時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_rest_selected_enemy_minion,
            condition=_this_rory_attacks,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            active_areas=(AreaType.FIELD,),
            official_effect="アタック時、相手のミニオン1体をレストする",
            official_timing="アタック時",
        ),
    ]
    return card
