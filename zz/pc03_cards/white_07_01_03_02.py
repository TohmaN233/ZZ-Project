from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_07_01_03_02"
ABILITY_JP = (
    "【召喚時】\n"
    "最もライフが多い自分のフォースのライフ1毎に、相手のミニオン全てにBP-100を付与する。\n"
    "【常時】\n"
    "自分の種族「アンドロイド」を持つミニオンがいる場合、このミニオンは相手の効果で選択できない。\n"
    "【自分のターン】\n"
    "自分の種族「アンドロイド」を持つミニオン全てはBPに関係なくバトルに勝利する。"
)
ABILITY_EN = (
    "[When Summoned]\n"
    "For every point your Force with the highest point value has, deal -100BP to all your opponent's minions.\n"
    "[Passive]\n"
    "If you have a minion belonging to the Android class on your field, this minion cannot be selected as a target for your opponent's effects.\n"
    "[On Your Turn]\n"
    "Your minions belonging to the Android class will win in battle against other minions regardless of BP."
)


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _reduce_opponent_minions_by_highest_force_life(
    source: CardInstance, state: Any, _ctx: Context
) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    living_force_lives = [
        force.life for force in source.owner.forces if not force.destroyed
    ]
    if not living_force_lives:
        raise RuntimeError(f"{CARD_ID} summon effect requires a living Force")
    amount = max(living_force_lives) * 100
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in list(opponent.field):
        if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
            continue
        engine.modify_stat(target, bp_delta=-amount, duration="turn")


def _has_android_minion(player: Any) -> bool:
    return any(
        minion.card.type in (CardType.F_MINION, CardType.B_MINION)
        and "アンドロイド" in minion.card.race_jp.split("|")
        for minion in player.field
    )


def _metallic_steed_targetable(
    target: CardInstance, effect_source: CardInstance | None, _state: Any
) -> bool:
    if effect_source is None or effect_source.owner is target.owner:
        return True
    return not _has_android_minion(target.owner)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    card.effect_targetable = _metallic_steed_targetable
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _reduce_opponent_minions_by_highest_force_life,
            condition=_self_summoned,
            official_effect=(
                "最もライフが多い自分のフォースのライフ1毎に、"
                "相手のミニオン全てにBP-100を付与する。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    card.pc03_android_battle_win = True
    return card
