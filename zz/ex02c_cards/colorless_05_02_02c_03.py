from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context, GameState
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_05_02_02c_03'
_PROTECTION_FLAG = "turn:ex02c_stacia_black_swordsman_protection"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _apply_black_swordsman_protection(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    source.flags.add(
        f"{_PROTECTION_FLAG}:{state.turn}:{source.owner.side.name}"
    )


def _protection_is_active(source: CardInstance, state: Any) -> bool:
    protection_flag = f"{_PROTECTION_FLAG}:{state.turn}:{source.owner.side.name}"
    return (
        source.area is AreaType.FIELD
        and source in source.owner.field
        and protection_flag in source.flags
    )


def _protect_black_swordsmen_from_selection(
    protector: CardInstance,
    target: CardInstance,
    operation: str,
    state: Any,
) -> bool:
    return (
        operation == "select"
        and target.owner is protector.owner
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and "黒の剣士" in target.card.race_jp.split("|")
        and _protection_is_active(protector, state)
    )


def _sword_turn_aura(
    source: CardInstance,
    target: CardInstance,
    state: GameState,
) -> tuple[int, int]:
    if (
        source.area is AreaType.FIELD
        and target.owner is source.owner
        and target is not source
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and "ソード" in target.card.race_jp.split("|")
        and state.active is source.owner
    ):
        return 100, 1
    return 0, 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.stat_aura = _sword_turn_aura
    card.effect_protection = _protect_black_swordsmen_from_selection
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_apply_black_swordsman_protection,
            condition=_self_source,
            params={"ex02c_switch_races": ["黒の剣士"]},
            active_areas=(AreaType.FIELD,),
            official_effect=(
                "このターン中、このミニオンに「自分の種族「黒の剣士」を持つミニオン全ては、"
                "相手の効果で選択できない。」を与える。"
            ),
            official_timing="召喚時＆スイッチ",
            official_condition="スイッチ：「黒の剣士」",
        )
    )
    return card
