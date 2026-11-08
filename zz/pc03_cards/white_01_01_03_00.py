from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context, ForceInstance
from zz.pc01 import _card_from_row

CARD_ID = "white_01_01_03_00"
ABILITY_JP = (
    "【相手のターン】\n"
    "自分の種族「エヴォーカー」を持つ、白または無色のマナがある場合、"
    "自分のフォースに与えられるコスト5以下のミニオンからのダメージを1軽減する。"
    "この効果は重複しない。\n"
    "【常時】\n"
    "このミニオンはベースに移動するとき、レスト状態で移動する。"
)
ABILITY_EN = (
    "[On Your Opponent's Turn]\n"
    "If you have White or Neutral Mana belonging to the Evoker class in your base, "
    "damage dealt to your Forces by minions with a cost of 5 or lower is reduced by 1. "
    "This effect cannot stack.\n"
    "[Passive]\n"
    "This minion enters the Rest State when it moves to your base."
)


def _force_damage_reduction(
    source: CardInstance,
    force: ForceInstance,
    damage_source: Any,
    _damage_kind: str,
    state: Any,
) -> int:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Force damage reduction requires an Engine")
    if (
        source.area is not AreaType.FIELD
        or source.owner is not force.owner
        or state.active is source.owner
        or not isinstance(damage_source, CardInstance)
        or damage_source.owner is force.owner
        or damage_source.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or sum(damage_source.card.cost.values()) > 5
    ):
        return 0
    has_evoker_mana = any(
        mana.area is AreaType.BASE
        and mana.card.type is CardType.B_MINION
        and "エヴォーカー" in mana.card.race_jp.split("|")
        and engine._mana_color_of(mana) in (Color.WHITE, Color.COLORLESS)
        for mana in source.owner.base
    )
    return 1 if has_evoker_mana else 0


def _self_moved_to_base(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.BASE


def _rest_after_moving_to_base(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Base movement requires an Engine")
    if source.area is not AreaType.BASE:
        raise RuntimeError(f"{CARD_ID} move-to-Base effect resolved outside Base: {source.area!r}")
    engine.rest_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    # Shared Engine must aggregate matching reductions by maximum; the printed effect cannot stack.
    card.force_damage_reducer = _force_damage_reduction
    card.effects.append(
        EffectSpec(
            EffectTiming.MOVE_TO_BASE,
            _rest_after_moving_to_base,
            condition=_self_moved_to_base,
            official_effect="このミニオンはベースに移動するとき、レスト状態で移動する。",
            official_timing="常時",
            active_areas=(AreaType.BASE,),
        )
    )
    return card
