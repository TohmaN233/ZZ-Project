from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_04_03_02r_00"


def _this_magic(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_magic_with_blue_dragon(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and _has_blue_dragon(source)


def _this_magic_without_blue_dragon(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and not _has_blue_dragon(source)


def _has_blue_dragon(source: CardInstance) -> bool:
    return any(
        ci.card.type in (CardType.B_MINION, CardType.F_MINION)
        and ci.card.printed_color is Color.BLUE
        and "ドラゴン" in ci.card.race_jp
        for ci in source.owner.field
    )


def _target_limit(source: CardInstance) -> int:
    return 2 if _has_blue_dragon(source) else 1


def _destroy_neutral_targets(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        _target_limit(source),
        filter_fn=lambda target: (
            target.card.type in (CardType.B_MINION, CardType.F_MINION)
            and target.card.printed_color is Color.COLORLESS
        ),
        source=source,
    )
    for target in targets:
        engine.destroy_target(target, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_destroy_neutral_targets,
            condition=_this_magic_without_blue_dragon,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"color": Color.COLORLESS.name},
            official_effect="相手の無色ミニオン1体を破壊する",
            official_timing="メイン/フラッシュ",
        ),
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_destroy_neutral_targets,
            condition=_this_magic_with_blue_dragon,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=2,
            params={"color": Color.COLORLESS.name, "allow_variable_targets": True},
            official_effect="相手の無色ミニオン1体を破壊する。青のドラゴンがいれば最大2体",
            official_timing="メイン/フラッシュ",
        ),
        build_effect(
            "move_to_base_targets",
            EffectTiming.ON_CAST_MAGIC,
            condition=_this_magic_without_blue_dragon,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            official_effect="相手のミニオン1体をレスト状態でベースへ移動する",
            official_timing="メイン/フラッシュ",
        ),
        build_effect(
            "move_to_base_targets",
            EffectTiming.ON_CAST_MAGIC,
            condition=_this_magic_with_blue_dragon,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=2,
            allow_variable_targets=True,
            official_effect="相手のミニオン1体をレスト状態でベースへ移動する。青のドラゴンがいれば最大2体",
            official_timing="メイン/フラッシュ",
        ),
    ]
    return card
