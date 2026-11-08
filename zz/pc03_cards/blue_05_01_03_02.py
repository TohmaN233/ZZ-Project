from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_05_01_03_02"


def _own_attack(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _own_magic_used(source: CardInstance, _state: Any, ctx: Context) -> bool:
    used = ctx.source
    return (
        source.area is AreaType.FIELD
        and isinstance(used, CardInstance)
        and used.owner is source.owner
        and used.card.type is CardType.MAGIC
        and sum(used.card.cost.values()) >= 3
    )


def _refresh_after_magic(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Magic trigger requires an Engine")
    engine.refresh_target(source)


def _reduce_hand_magic_free_cost(source: CardInstance, target: CardInstance, state: Any) -> int:
    if (
        source.area is not AreaType.FIELD
        or target.area is not AreaType.HAND
        or target.card.type is not CardType.MAGIC
        or source.owner is not target.owner
    ):
        return 0
    merfolk_count = sum(
        minion.area is AreaType.FIELD
        and minion.card.type in (CardType.F_MINION, CardType.B_MINION)
        and "マーフォーク" in minion.card.race_jp.split("|")
        for minion in source.owner.field
    )
    return -merfolk_count


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【アタック時】\n相手のコスト5以下のミニオン1体をレスト状態でベースに移動させる。\n"
        "【常時】\n自分が本来のコストが3以上のマジックを使用するたび、このミニオンをアクティブにする。\n"
        "【常時】\n自分の手札にあるマジックカードのフリーコストを、"
        "自分の種族「マーフォーク」を持つミニオン1体毎に1減らす。"
    )
    card.ability_en = (
        "[When Attacking] Move one of your opponent's minions with a cost of 5 or lower into their base in the Rest State.\n"
        "[Passive] Whenever you use a Magic card with an original cost of 3 or higher, this minion enters the Active State.\n"
        "[Passive] Reduce the Free Cost of each Magic card in your hand by 1 for each of your Minions belonging to the Merfolk class."
    )
    card.cost_aura = _reduce_hand_magic_free_cost
    card.effects.extend(
        [
            build_effect(
                "move_to_base_targets",
                EffectTiming.ON_ATTACK,
                target_kind="enemy_minion",
                max_cost=5,
                rested=True,
                condition=_own_attack,
                official_effect="相手のコスト5以下のミニオン1体をレスト状態でベースに移動させる。",
                official_timing="アタック時",
            ),
            EffectSpec(
                EffectTiming.ON_CARD_USED,
                _refresh_after_magic,
                condition=_own_magic_used,
                official_effect="自分が本来のコストが3以上のマジックを使用するたび、このミニオンをアクティブにする。",
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
