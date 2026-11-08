from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_09_01_03_00"
ONCE_PER_TURN_FLAG = "turn:pc03_schwarz_tiger_effect_used"
ABILITY_JP = (
    "【召喚時】\n"
    "相手のプレイヤーに、相手のプレイヤーのライフの半分"
    "（端数切り上げ）に等しいダメージを与える。"
    "自分の「「粉砕」シュヴァルツティーガー」の効果はターンに1回だけ発揮する。"
)
ABILITY_EN = (
    "[When Summoned]\n"
    "Deal damage to your opponent's Life equal to half of their Life "
    "(round up to the nearest whole number). "
    "The effect of Schwarz Tiger - The Pulverizer can only be activated once per turn."
)


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _damage_half_opponent_life(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} damage effect requires an Engine")
    source.owner.flags.add(ONCE_PER_TURN_FLAG)
    opponent = state.players[1 - state.players.index(source.owner)]
    amount = (opponent.life + 1) // 2
    engine._damage_player(opponent, amount, source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _damage_half_opponent_life,
            condition=_self_summoned,
            params={
                "once_per_turn_flag": ONCE_PER_TURN_FLAG,
                "once_per_turn_scope": "owner",
            },
            official_effect=(
                "相手のプレイヤーに、相手のプレイヤーのライフの半分"
                "（端数切り上げ）に等しいダメージを与える。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
