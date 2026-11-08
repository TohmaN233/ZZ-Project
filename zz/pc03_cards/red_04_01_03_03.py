from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, AttackTargetKind, CardType, Color, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_04_01_03_03"
DWARF_RACE = "ドワーフ"


def _self_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _self_transformed_with_enemy(source: CardInstance, state: Any, ctx: Context) -> bool:
    if not _self_transformed(source, state, ctx):
        return False
    opponent = state.players[1 - state.players.index(source.owner)]
    return any(
        target.area is AreaType.FIELD
        and target.owner is opponent
        and target.card.type is CardType.F_MINION
        for target in opponent.field
    )


def _mark_enemy_unblockable_and_place_red_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transformation effect requires an Engine")
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if targets:
        engine.add_keyword(targets[0], Keyword.CANNOT_BLOCK, duration="turn")



def _is_first_active_copy(source: CardInstance) -> bool:
    return source is next(
        (ci for ci in source.owner.field if ci.card.id == CARD_ID),
        None,
    )


def _dwarf_attacked_player(source: CardInstance, state: Any, ctx: Context) -> bool:
    attacker = ctx.source
    attack_target = ctx.attack_target
    opponent = state.players[1 - state.players.index(source.owner)]
    attacked_opponent = (
        attack_target.kind is AttackTargetKind.PLAYER and attack_target.ref is opponent
        if attack_target is not None
        else ctx.target is opponent
    )
    if (
        source.area is not AreaType.FIELD
        or source.owner is not ctx.controller
        or state.active is not source.owner
        or not _is_first_active_copy(source)
        or not isinstance(attacker, CardInstance)
        or attacker.area is not AreaType.FIELD
        or attacker.owner is not source.owner
        or attacker.card.type is not CardType.F_MINION
        or DWARF_RACE not in attacker.card.race_jp.split("|")
        or not attacked_opponent
    ):
        return False
    return True


def _draw_for_dwarf_player_attack(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} attack effect requires an Engine")
    engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_TRANSFORM,
                _mark_enemy_unblockable_and_place_red_mana,
                condition=_self_transformed_with_enemy,
                target_kind="enemy_minion",
                min_targets=1,
                max_targets=1,
                official_effect=(
                    "相手のミニオン1体を選択する。このターン中、そのミニオンはブロックできない。"
                    "赤マナ1つをレスト状態でベースに置く。"
                ),
                official_timing="変形時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _draw_for_dwarf_player_attack,
                condition=_dwarf_attacked_player,
                official_effect="自分の種族「ドワーフ」を持つミニオンがプレイヤーにアタックするたび、自分はカードを1枚引く。この効果は重複しない。",
                official_timing="アタック時",
                official_condition="自分のターンに、自分の種族「ドワーフ」を持つミニオンがプレイヤーにアタックしたとき",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    card.effects.append(build_effect(
        "place_colorless_mana", EffectTiming.ON_TRANSFORM,
        condition=_self_transformed, rested=True, mana_color=Color.RED,
        official_effect="赤マナ1つをレスト状態でベースに置く。",
        official_timing="変形時", active_areas=(AreaType.FIELD,),
    ))
    return card
