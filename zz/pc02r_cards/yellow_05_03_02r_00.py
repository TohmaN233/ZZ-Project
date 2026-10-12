from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.pc02 import _replacement_iid


CARD_ID = "yellow_05_03_02r_00"


def _self_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _put_field_minion_from_zone(
    engine: Any,
    player: Any,
    card: CardInstance,
    from_area: AreaType,
    source: CardInstance,
) -> None:
    if card.card.type is not CardType.F_MINION:
        raise RuntimeError(f"{CARD_ID} selected non-Field Minion {card.card.id} from deck")
    if from_area is not AreaType.DECK or card not in player.deck:
        raise RuntimeError(f"{CARD_ID} selected card is no longer in its owner's deck")
    engine._make_field_space(player, _replacement_iid(engine, player, source))
    player.deck.remove(card)
    card.area = AreaType.FIELD
    card.rested = False
    card.summoning_sickness = True
    player.field.append(card)
    engine._record_zone_move(card, from_area, AreaType.FIELD)
    engine._emit_enter_field(player, card)
    engine.triggers.resolve_all()


def _search_and_put_yellow_cost_four(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    owner = source.owner
    eligible = [
        target
        for target in owner.deck
        if target.card.type is CardType.F_MINION
        and target.card.printed_color is Color.YELLOW
        and sum(target.card.cost.values()) == 4
    ]
    selected = []
    if eligible:
        selected = engine.select_target(
            owner,
            "deck_card",
            1,
            1,
            filter_fn=lambda target: (
                target.card.type is CardType.F_MINION
                and target.card.printed_color is Color.YELLOW
                and sum(target.card.cost.values()) == 4
            ),
            source=source,
        )
    if len(selected) > 1:
        raise RuntimeError(f"{CARD_ID} selected multiple deck cards: {[card.iid for card in selected]}")
    if selected:
        chosen = selected[0]
        _put_field_minion_from_zone(engine, owner, chosen, AreaType.DECK, source)
    engine.rng.shuffle(owner.deck)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # The printed face says Main / Flash; OCR confused the Main delimiter.
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_search_and_put_yellow_cost_four,
            condition=_self_cast,
            target_kind="deck_minion",
            min_targets=1,
            max_targets=1,
            params={
                "puts_targets_on_field": True,
                "min_cost": 4,
                "max_cost": 4,
                "color": Color.YELLOW,
                "card_type": CardType.F_MINION,
            },
            official_effect="デッキからコスト4の黄のField Minion1体を出し、その後デッキをシャッフルする",
            official_timing="メイン/フラッシュ",
        )
    ]
    return card
