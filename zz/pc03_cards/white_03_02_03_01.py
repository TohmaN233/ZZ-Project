from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_03_02_03_01"
ATTACK_EFFECT = build_effect(
    "force_block",
    EffectTiming.ON_ATTACK,
    target_kind="enemy_minion",
    choose_target=True,
    only_active=True,
    official_effect="相手のアクティブ状態のミニオン1体を選択する。このターン中、そのミニオンは必ずブロックする。",
    official_timing="アタック時",
)


def _self_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_forced_block_attack_ability(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} temporary attack grant requires an Engine")
    apply_grant = getattr(engine, "apply_pc03_temporary_attack_grant", None)
    if apply_grant is None:
        raise RuntimeError(f"{CARD_ID} requires Engine.apply_pc03_temporary_attack_grant")
    apply_grant(
        source=source,
        context=ctx,
        target_color=None,
        target_types=(CardType.F_MINION, CardType.B_MINION),
        effect=ATTACK_EFFECT,
        duration="turn",
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【メイン】このターン中、自分のミニオン全てに「【アタック時】相手のアクティブ状態のミニオン1体を選択する。"
        "このターン中、そのミニオンは必ずブロックする」を与える。"
    )
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _grant_forced_block_attack_ability,
            condition=_self_cast,
            params={
                "temporary_attack_grant": {
                    "color": None,
                    "target_types": [CardType.F_MINION.name, CardType.B_MINION.name],
                    "duration": "turn",
                    "ability_timing": EffectTiming.ON_ATTACK.value,
                    "ability_target_kind": "enemy_minion",
                    "ability_only_active": True,
                    "ability_forces_block": True,
                }
            },
            official_effect=card.ability_jp.replace("【メイン】", "").strip(),
            official_timing="メイン",
            active_areas=(AreaType.RESOLVING,),
        )
    )
    return card
