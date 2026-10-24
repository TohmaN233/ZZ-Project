from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_06_02_cp_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _search_item_base_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    owner = source.owner

    def is_item_base_minion(target: CardInstance) -> bool:
        return (
            target.card.type is CardType.B_MINION
            and "アイテム" in target.card.race_jp.split("|")
        )

    eligible = engine._eligible_targets(
        owner,
        "deck_base_minion",
        filter_fn=is_item_base_minion,
        source=source,
    )
    if not eligible:
        engine.rng.shuffle(owner.deck)
        return
    selected = engine.select_target(
        owner,
        "deck_base_minion",
        1,
        1,
        filter_fn=is_item_base_minion,
        source=source,
    )
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one legal Item Base Minion, got {len(selected)}")
    card = selected[0]
    owner.deck.remove(card)
    engine.reveal_card(owner, card, "deck_search")
    engine.add_to_hand(owner, card, from_area=AreaType.DECK)
    engine.rng.shuffle(owner.deck)


def _attacked_player(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and any(ctx.target is player for player in state.players)


def _destroy_enemy_minion_at_most_300(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine

    def eligible(target: CardInstance) -> bool:
        return (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and engine.effective_bp(target) <= 300
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
        raise RuntimeError(f"{CARD_ID} expected one legal attacking target, got {len(selected)}")
    engine.destroy_target(selected[0], source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_search_item_base_minion,
            condition=_self_summoned,
            target_kind="deck_base_minion",
            min_targets=1,
            max_targets=1,
            optional=False,
            params={
                "card_type": CardType.B_MINION,
                "races_any": ["アイテム"],
                "ex02c_switch_races": ["閃光"],
            },
            active_areas=(AreaType.FIELD,),
            official_effect="自分はデッキの中から種族「アイテム」を持つベース・ミニオンカード1枚を公開して手札に加える。その後、自分のデッキをシャッフルする",
            official_timing="召喚時＆スイッチ",
        ),
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_destroy_enemy_minion_at_most_300,
            condition=_attacked_player,
            target_kind="enemy_minion",
            params={"max_bp": 300, "protection_operation": "destroy"},
            active_areas=(AreaType.FIELD,),
            official_effect="プレイヤーにアタックした場合、相手のBP300以下のミニオン1体を破壊する",
            official_timing="アタック時",
        ),
    ]
    return card
