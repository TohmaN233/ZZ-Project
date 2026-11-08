from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_03_02_03_00"


ATTACK_EFFECT = build_effect(
    "move_to_base_targets",
    EffectTiming.ON_ATTACK,
    target_kind="enemy_minion",
    rested=True,
    official_effect="相手のミニオン1体をレスト状態でベースに移動させる。",
    official_timing="アタック時",
)


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_attack_effect(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} temporary attack grant requires an Engine")
    apply_grant = getattr(engine, "apply_pc03_temporary_attack_grant", None)
    if apply_grant is None:
        raise RuntimeError(
            f"{CARD_ID} requires Engine.apply_pc03_temporary_attack_grant for its temporary attack ability"
        )
    apply_grant(
        source=source,
        context=ctx,
        target_color=Color.BLUE,
        target_types=(CardType.F_MINION, CardType.B_MINION),
        effect=ATTACK_EFFECT,
        duration="turn",
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _grant_attack_effect,
            condition=_self_source,
            params={
                "temporary_attack_grant": {
                    "color": Color.BLUE.name,
                    "target_types": [CardType.F_MINION.name, CardType.B_MINION.name],
                    "duration": "turn",
                    "ability_timing": EffectTiming.ON_ATTACK.value,
                    "ability_target_kind": "enemy_minion",
                }
            },
            official_effect=(
                "このターン中、自分の青のミニオン全てに「アタック時："
                "相手のミニオン1体をレスト状態でベースに移動させる。」を与える。"
            ),
            official_timing="メイン",
            active_areas=(AreaType.RESOLVING,),
        )
    )
    return card
