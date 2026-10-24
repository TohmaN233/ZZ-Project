from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_07_02_02c_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _snipe(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]

    def eligible(target: CardInstance) -> bool:
        return (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and target.card.printed_color is Color.COLORLESS
            and not engine.is_protected_from_card_effect(
                target,
                source=source,
                operation="destroy",
            )
        )

    targets = engine._eligible_targets(
        source.owner,
        "enemy_minion",
        filter_fn=eligible,
        source=source,
    )
    if not targets:
        engine._damage_player(opponent, 1, source=source)
        return
    selected = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=eligible,
        source=source,
    )
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one legal Colorless Minion, got {len(selected)}")
    engine.destroy_target(selected[0], source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_snipe,
            condition=_self_summoned,
            target_kind="enemy_minion",
            params={
                "color": Color.COLORLESS,
                "ex02c_switch_races": ["黒の剣士"],
            },
            active_areas=(AreaType.FIELD,),
            official_effect="『狙撃』相手の無色のミニオン1体を破壊する。破壊するミニオンがいない場合、相手のプレイヤーに1ダメージを与える",
            official_timing="召喚時＆スイッチ",
        )
    ]
    return card
