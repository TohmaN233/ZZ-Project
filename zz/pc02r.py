from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable

from zz.cards import CARD_REGISTRY, register
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color, Keyword, Step
from zz.model import Card, CardInstance, Context, ForceInstance, Player
from zz.pc01 import DEFAULT_CARD_TSV, _card_from_row, _cost_from_image_id
from zz.pc02 import _remove_target


PC02R_PACK_JP = "PC:02R DIVINE"

# JP quoted extra-game identity (EN face prints "Tidal Wave", a different Basic card).
WAITRESS_EXTRA_GAME_ID = "blue_02_03_01_01"
ELF_SHAMAN_EXTRA_GAME_ID = "green_02_03_01r_00"
CLUB_SKELETON_EXTRA_GAME_ID = "purple_01_03_01_00"
GOBLIN_QUEEN_ID = "colorless_03_02_01_04"
LOYAL_CANINE_ID = "colorless_05_02_02r_00"
REPRINT_SOURCE_IDS = {
    "colorless_03_02_02r_03": "colorless_03_02_01r_02",
    "colorless_04_02_02r_03": "colorless_04_02_01_03",
    "colorless_09_02_02r_00": "colorless_09_02_ex01_00",
    "colorless_010_02_02r_00": "colorless_010_02_01_00",
}

ANJU_FORMS = {
    Color.RED: "red_04_02_02r_01",
    Color.YELLOW: "yellow_04_02_02r_01",
    Color.WHITE: "white_04_02_02r_00",
    Color.GREEN: "green_04_02_02r_01",
    Color.BLUE: "blue_04_02_02r_02",
    Color.PURPLE: "purple_04_02_02r_00",
}
ANJU_OWN_COLOR = {
    "red_04_02_02r_01": Color.RED,
    "yellow_04_02_02r_01": Color.YELLOW,
    "white_04_02_02r_00": Color.WHITE,
    "green_04_02_02r_01": Color.GREEN,
    "blue_04_02_02r_02": Color.BLUE,
    "purple_04_02_02r_00": Color.PURPLE,
    "colorless_04_02_02r_01": None,
}
LEGEND_FORMS = {
    "blue_07_02_02r_00": ("blue_07_02_02r_01", Color.BLUE),
    "green_07_02_02r_00": ("green_07_02_02r_01", Color.GREEN),
    "purple_07_02_02r_00": ("purple_07_02_02r_01", Color.PURPLE),
    "red_07_02_02r_00": ("red_07_02_02r_01", Color.RED),
    "white_07_02_02r_00": ("white_07_02_02r_01", Color.WHITE),
    "yellow_07_02_02r_00": ("yellow_07_02_02r_01", Color.YELLOW),
}

_CROP_STATS: dict[str, tuple[int | None, int, int]] = {
    "blue_00_01_02r_00": (None, 200, 0),
    "blue_00_01_02r_01": (None, 100, 1),
    "blue_02_02_02r_00": (2, 100, 1),
    "blue_03_02_02r_00": (3, 200, 1),
    "blue_04_02_02r_00": (4, 400, 1),
    "blue_04_02_02r_01": (4, 400, 1),
    "blue_04_02_02r_02": (4, 700, 2),
    "blue_05_02_02r_00": (5, 500, 2),
    "blue_06_02_02r_00": (6, 400, 2),
    "blue_06_02_02r_01": (6, 700, 2),
    "blue_07_02_02r_00": (7, 700, 2),
    "blue_07_02_02r_01": (7, 1000, 3),
    "colorless_00_01_02r_00": (None, 200, 1),
    "colorless_00_02_02r_00": (0, 700, 1),
    "colorless_01_02_02r_00": (1, 100, 0),
    "colorless_02_02_02r_00": (2, 400, 0),
    "colorless_02_02_02r_01": (2, 200, 1),
    "colorless_03_02_02r_00": (3, 200, 0),
    "colorless_03_02_02r_01": (3, 300, 1),
    "colorless_03_02_02r_02": (3, 300, 1),
    "colorless_03_02_02r_03": (3, 300, 1),
    "colorless_04_02_02r_00": (4, 400, 2),
    "colorless_04_02_02r_01": (4, 400, 1),
    "colorless_04_02_02r_02": (4, 400, 1),
    "colorless_04_02_02r_03": (4, 600, 1),
    "colorless_05_02_02r_00": (5, 500, 2),
    "colorless_05_02_02r_01": (5, 500, 2),
    "colorless_06_02_02r_00": (6, 500, 2),
    "colorless_06_02_02r_01": (6, 600, 2),
    "colorless_07_02_02r_00": (7, 700, 2),
    "colorless_07_02_02r_01": (7, 400, 2),
    "colorless_08_02_02r_00": (8, 700, 3),
    "colorless_09_02_02r_00": (9, 900, 3),
    "colorless_010_02_02r_00": (10, 1200, 3),
    "green_00_01_02r_00": (None, 100, 0),
    "green_00_01_02r_01": (None, 300, 1),
    "green_02_02_02r_00": (2, 300, 1),
    "green_03_02_02r_00": (3, 200, 1),
    "green_04_02_02r_00": (4, 600, 1),
    "green_04_02_02r_01": (4, 700, 2),
    "green_05_02_02r_00": (5, 500, 2),
    "green_06_02_02r_00": (6, 600, 2),
    "green_06_02_02r_01": (6, 700, 2),
    "green_07_02_02r_00": (7, 700, 2),
    "green_07_02_02r_01": (7, 1300, 3),
    "green_08_02_02r_00": (8, 900, 3),
    "purple_00_01_02r_00": (None, 100, 0),
    "purple_00_01_02r_01": (None, 100, 1),
    "purple_02_02_02r_00": (2, 200, 1),
    "purple_03_02_02r_00": (3, 300, 1),
    "purple_03_02_02r_01": (3, 200, 1),
    "purple_04_02_02r_00": (4, 700, 2),
    "purple_04_02_02r_01": (4, 500, 2),
    "purple_05_02_02r_00": (5, 500, 2),
    "purple_06_02_02r_00": (6, 700, 2),
    "purple_06_02_02r_01": (6, 600, 1),
    "purple_07_02_02r_00": (7, 700, 2),
    "purple_07_02_02r_01": (7, 1000, 2),
    "red_00_01_02r_00": (None, 200, 0),
    "red_00_01_02r_01": (None, 100, 1),
    "red_02_02_02r_00": (2, 200, 1),
    "red_02_02_02r_01": (2, 200, 1),
    "red_04_02_02r_00": (4, 300, 1),
    "red_04_02_02r_01": (4, 700, 2),
    "red_05_02_02r_00": (5, 400, 2),
    "red_06_02_02r_00": (6, 600, 1),
    "red_07_02_02r_00": (7, 700, 2),
    "red_07_02_02r_01": (7, 1000, 2),
    "red_07_02_02r_02": (7, 600, 1),
    "red_08_02_02r_00": (8, 700, 2),
    "white_00_01_02r_00": (None, 100, 0),
    "white_00_01_02r_01": (None, 300, 1),
    "white_02_02_02r_00": (2, 200, 1),
    "white_03_02_02r_00": (3, 200, 1),
    "white_04_02_02r_00": (4, 700, 2),
    "white_04_02_02r_01": (4, 500, 1),
    "white_04_02_02r_02": (4, 400, 2),
    "white_05_02_02r_00": (5, 600, 2),
    "white_06_02_02r_00": (6, 500, 2),
    "white_06_02_02r_01": (6, 600, 1),
    "white_07_02_02r_00": (7, 700, 2),
    "white_07_02_02r_01": (7, 1000, 2),
    "yellow_00_01_02r_00": (None, 100, 0),
    "yellow_00_01_02r_01": (None, 300, 1),
    "yellow_02_02_02r_00": (2, 200, 0),
    "yellow_02_02_02r_01": (2, 300, 1),
    "yellow_03_02_02r_00": (3, 300, 1),
    "yellow_04_02_02r_00": (4, 400, 1),
    "yellow_04_02_02r_01": (4, 700, 2),
    "yellow_04_02_02r_02": (4, 400, 1),
    "yellow_06_02_02r_00": (6, 600, 2),
    "yellow_07_02_02r_00": (7, 700, 2),
    "yellow_07_02_02r_01": (7, 1000, 2),
    "yellow_08_02_02r_00": (8, 800, 2),
}

_FLASH_ONLY = {
    "green_02_03_02r_00",
    "red_02_03_02r_00",
    "white_02_03_02r_00",
    "yellow_01_03_02r_00",
}
_MAIN_AND_FLASH = {
    "blue_04_03_02r_00",
    "green_01_03_02r_00",
    "purple_04_03_02r_00",
    "red_02_03_02r_01",
    "yellow_05_03_02r_00",
}


def _effect(
    timing: EffectTiming,
    fn: Callable[[CardInstance, Any, Context], None],
    *,
    condition: Callable[[CardInstance, Any, Context], bool] | None = None,
    target_kind: str | None = None,
    min_targets: int = 1,
    max_targets: int = 1,
    optional: bool = False,
    params: dict[str, Any] | None = None,
    official_effect: str,
    official_timing: str,
    official_condition: str | None = None,
    active_areas: tuple[AreaType, ...] | None = None,
) -> EffectSpec:
    return EffectSpec(
        timing=timing,
        fn=fn,
        condition=condition,
        target_kind=target_kind,
        min_targets=min_targets,
        max_targets=max_targets,
        optional=optional,
        params=dict(params or {}),
        official_effect=official_effect,
        official_timing=official_timing,
        official_condition=official_condition,
        active_areas=active_areas,
    )


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _opponent(state: Any, player: Player) -> Player:
    return state.players[1 - state.players.index(player)]


def _card_color(card: Card) -> Color:
    if card.mana_color is not None:
        return card.mana_color
    return next((color for color in card.cost if color is not Color.COLORLESS), Color.COLORLESS)


def _total_cost(card: Card) -> int:
    return sum(card.cost.values())


def _has_race(card: Card, *races: str) -> bool:
    return any(race in card.race_jp for race in races)


def _own_blue_dragon(player: Player) -> bool:
    return any(
        _card_color(ci.card) is Color.BLUE and _has_race(ci.card, "ドラゴン")
        for ci in player.field
    )


def _token_card(card_id: str, name_jp: str, cost: int, bp: int, dp: int, *, color: Color = Color.COLORLESS, race_jp: str = "", keywords: list[Keyword] | None = None) -> Card:
    cost_map = {color: cost} if cost else {}
    if color is not Color.COLORLESS and cost > 1:
        cost_map = {color: 1, Color.COLORLESS: cost - 1}
    elif color is Color.COLORLESS and cost:
        cost_map = {Color.COLORLESS: cost}
    return Card(
        id=card_id,
        name_jp=name_jp,
        name_en=name_jp,
        type=CardType.F_MINION,
        cost=cost_map,
        bp=bp,
        dp=dp,
        race_jp=race_jp,
        keywords=list(keywords or []),
        is_token=True,
    )


SLIME_BLOCK_TOKEN = _token_card("slime_block_token", "スライム・ブロック・トークン", 1, 300, 0, race_jp="スライム")
S_GOLEM_TOKEN = _token_card("s_golem_token", "S・ゴレイム・トークン", 1, 100, 1, color=Color.RED, race_jp="ゴレイム")
LAVA_SLIME_COPY = _token_card("red_06_02_02r_00_copy", "ラヴァ・スライム", 6, 600, 1, color=Color.RED, race_jp="モンスター")
BOLT_COPY = _token_card("colorless_07_02_02r_01_copy", "「炎狼」ヴォルト", 7, 400, 2, race_jp="ビースト")


def _add_named_from_outside(card_id: str) -> Callable[[CardInstance, Any, Context], None]:
    def fn(source: CardInstance, state: Any, ctx: Context) -> None:
        card = CARD_REGISTRY[card_id]
        copied = CardInstance(card, source.owner, iid=state.allocate_iid(), area=AreaType.REMOVED)
        state.engine.add_to_hand(source.owner, copied, from_area=AreaType.REMOVED)
    return fn


def _banish_attached_mana(host: CardInstance, mana: CardInstance, engine: Any) -> None:
    if mana in host.blessings:
        host.blessings.remove(mana)
    if mana in host.owner.base:
        host.owner.base.remove(mana)
    mana.area = AreaType.REMOVED
    host.owner.removed.append(mana)
    engine._record_zone_move(mana, AreaType.BLESSING, AreaType.REMOVED)


def _return_attached_mana_to_base(host: CardInstance, mana: CardInstance, engine: Any) -> None:
    if mana in host.blessings:
        host.blessings.remove(mana)
    replace_iid = engine.select_base_replacement_iid(host.owner, host)
    if len(host.owner.base) >= 10 and replace_iid is None:
        _banish_attached_mana(host, mana, engine)
        return
    engine._make_base_space(host.owner, replace_iid)
    mana.area = AreaType.BASE
    mana.rested = True
    host.owner.base.append(mana)
    engine._record_zone_move(mana, AreaType.BLESSING, AreaType.BASE)


def _morph_anju(host: CardInstance, state: Any, mana: CardInstance) -> None:
    color = state.engine._mana_color_of(mana)
    if color is Color.COLORLESS:
        return
    dest_id = ANJU_FORMS.get(color)
    if dest_id is None or dest_id == host.card.id:
        return
    state.engine.morph_in_place(host, CARD_REGISTRY[dest_id])


def _anju_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        return
    color = state.engine._mana_color_of(mana)
    own = ANJU_OWN_COLOR.get(source.card.id)
    if own is None:
        if color is Color.COLORLESS:
            return
        _return_attached_mana_to_base(source, mana, state.engine)
        _morph_anju(source, state, mana)
        return
    if color is Color.COLORLESS or color is own:
        return
    _banish_attached_mana(source, mana, state.engine)
    _morph_anju(source, state, mana)


def _legend_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    dest_id, needed = LEGEND_FORMS[source.card.id]
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        return
    if state.engine._mana_color_of(mana) is not needed:
        return
    _banish_attached_mana(source, mana, state.engine)
    state.engine.morph_in_place(source, CARD_REGISTRY[dest_id])


def _select(engine: Any, owner: Player, kind: str, source: CardInstance, *, min_n: int = 1, max_n: int = 1, filter_fn=None, optional: bool = False):
    return engine.select_target(owner, kind, 0 if optional else min_n, max_n, filter_fn=filter_fn, source=source)


# --- engine hooks -------------------------------------------------------

def adjust_effective_cost(player: Player, card: CardInstance, state: Any, cost: dict[Color, int]) -> dict[Color, int]:
    if card.card.id == "colorless_00_02_02r_00" and card.area is AreaType.HAND:
        life = max(0, player.life)
        return {Color.COLORLESS: life} if life else {}
    opponent = _opponent(state, player)
    if (
        card.card.type is CardType.MAGIC
        and card.area is AreaType.HAND
        and any(source.card.id == "colorless_02_02_02r_00" and source.area is AreaType.FIELD for source in opponent.field)
    ):
        return {color: amount for color, amount in card.card.cost.items() if amount > 0}
    adjusted = dict(cost)
    if card.card.type is CardType.F_MINION and _card_color(card.card) is Color.COLORLESS and card.area is AreaType.HAND:
        keepers = sum(
            source.card.id == "green_02_02_02r_00" and source.area is AreaType.FIELD
            for owner in state.players
            for source in owner.field
        )
        if keepers:
            adjusted[Color.COLORLESS] = adjusted.get(Color.COLORLESS, 0) + keepers
    if card.card.id == "purple_06_02_02r_01" and card.area is AreaType.HAND and state.active is player:
        reduction = sum(ci.card.type is CardType.F_MINION for ci in player.trash)
        adjusted[Color.COLORLESS] = max(0, adjusted.get(Color.COLORLESS, 0) - reduction)
    if card.card.id == "white_06_02_02r_01" and card.area is AreaType.HAND and state.active is player:
        reduction = len(opponent.field)
        adjusted[Color.COLORLESS] = max(0, adjusted.get(Color.COLORLESS, 0) - reduction)
    return {color: amount for color, amount in adjusted.items() if amount > 0}


def can_effect_select(source: CardInstance, target: CardInstance, state: Any) -> bool:
    if target.card.id == "colorless_03_02_02r_02" and target.area is AreaType.TRASH:
        return False
    if source.owner is target.owner:
        return True
    if "turn:pc02r_effect_untargetable" in target.flags:
        return False
    if state.active is target.owner:
        if any(
            ci.card.id == "white_05_02_02r_00" and ci.area is AreaType.FIELD
            for ci in target.owner.field
        ) and _card_color(target.card) is Color.WHITE and _has_race(target.card, "ドラゴン"):
            return False
    return True


def blocks_effect_destroy(ci: CardInstance, source: Any, state: Any) -> bool:
    if not isinstance(source, CardInstance) or source.owner is ci.owner:
        return False
    if not any(card.card.id == "green_05_02_02r_00" and card.area is AreaType.FIELD for card in ci.owner.field):
        return False
    return ci.card.id == "green_05_02_02r_00" or (
        _card_color(ci.card) is Color.GREEN and _has_race(ci.card, "ドラゴン")
    )


def blocks_return_to_hand(ci: CardInstance, state: Any) -> bool:
    return ci.card.id == "green_06_02_02r_00"


def suppress_force_on_destroy(source: Any, fi: ForceInstance, state: Any) -> bool:
    if not isinstance(source, CardInstance):
        return False
    return state.active is source.owner and any(mana.card.id == "purple_00_01_02r_00" for mana in source.blessings)


def adjust_life_damage(state: Any, player: Player, amount: int, source: Any, damage_kind: str) -> int:
    if "pc02r:next_life_zero" in player.flags:
        player.flags.discard("pc02r:next_life_zero")
        return 0
    if (
        damage_kind == "minion_dp"
        and state.active is not player
        and isinstance(source, CardInstance)
        and _total_cost(source.card) <= 5
        and any(ci.card.id == "green_04_02_02r_00" and ci.area is AreaType.FIELD for ci in player.field)
    ):
        return max(0, amount - 1)
    return amount


def adjust_force_damage(state: Any, fi: ForceInstance, amount: int, source: Any) -> int:
    if "pc02r:nicold_force_reduce" in fi.owner.flags:
        return max(0, amount - 1)
    return amount


def on_turn_end_flags(state: Any, active: Player) -> None:
    if "pc02r:nicold_force_reduce" in active.flags:
        active.flags.add("pc02r:nicold_seen_own_end")
    opponent = _opponent(state, active)
    if "pc02r:nicold_seen_own_end" in opponent.flags:
        opponent.flags.discard("pc02r:nicold_force_reduce")
        opponent.flags.discard("pc02r:nicold_seen_own_end")
    for ci in list(active.field):
        if "pc02r:lock_until_own_end" in ci.flags:
            ci.flags.discard("pc02r:lock_until_own_end")
            ci.flags.discard("pc02r:cannot_attack")
            ci.flags.discard("pc02r:cannot_block")
            ci.flags.discard("pc02r:cannot_move")
        if "pc02r:destroy_at_owner_turn_end" in ci.flags:
            state.engine.destroy_target(ci, ci)


def on_player_attack_blocked(engine: Any, attacker: CardInstance, blocker: CardInstance) -> None:
    if attacker.card.id == "red_05_02_02r_00" and engine.state.active is attacker.owner:
        attacker.rested = False


# --- card callbacks -----------------------------------------------------

def _cortney_place(source: CardInstance, state: Any, ctx: Context) -> None:
    if len(source.owner.base) >= 4:
        state.engine.draw(source.owner, 1)


def _cogito(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    engine.draw(source.owner, 1)
    if source.owner.movement_right_count <= 0:
        return
    source.owner.movement_right_count -= 1
    replace_iid = engine.select_base_replacement_iid(source.owner, source)
    if len(source.owner.base) >= 10 and replace_iid is None:
        return
    mana = engine.place_generated_colorless_mana(source.owner, replace_iid)
    mana.rested = True


def _explorer_keyword(source: CardInstance, target: CardInstance, state: Any) -> list[Keyword]:
    if source is target and source.blessings:
        return [Keyword.SNEAKING]
    return []


def _brighton_retreat(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_minion", source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=-100, dp_delta=-1, duration="permanent")


def _oceans_magic(source: CardInstance, state: Any, ctx: Context) -> None:
    used = ctx.source
    if not isinstance(used, CardInstance) or used.card.type is not CardType.MAGIC or used.owner is not source.owner:
        return
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: _total_cost(target.card) <= 5,
    )
    for target in targets:
        state.engine.move_target_to_base_asking_owner(target, rested=True, source=source)


def _wizardry(source: CardInstance, state: Any, ctx: Context) -> None:
    extra = 1 if _own_blue_dragon(source.owner) else 0
    count = 1 + extra
    colorless = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        min_n=count,
        max_n=count,
        filter_fn=lambda target: _card_color(target.card) is Color.COLORLESS,
    )
    for target in colorless:
        state.engine.destroy_target(target, source)
    moved = _select(state.engine, source.owner, "enemy_minion", source, min_n=count, max_n=count)
    for target in moved:
        state.engine.move_target_to_base_asking_owner(target, rested=True, source=source)


def _selene_listen(source: CardInstance, state: Any, ctx: Context) -> bool:
    return _self_source(source, state, ctx) and _own_blue_dragon(source.owner)


def _selene_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    if not _own_blue_dragon(source.owner):
        return
    build_effect(
        "search_deck_to_hand",
        EffectTiming.ON_SUMMON,
        target_kind="deck_card",
        card_type=CardType.MAGIC,
        official_effect="マジック1枚を公開して手札に加える",
        official_timing="召喚時",
    ).fn(source, state, ctx)


def _tiger_damage(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.source is not source or not isinstance(ctx.target, Player) or ctx.target is source.owner:
        return
    if state.active is not source.owner:
        return
    selected = _select(
        state.engine,
        source.owner,
        "ally_minion_base",
        source,
        filter_fn=lambda target: target.card.type in (CardType.B_MINION, CardType.F_MINION) and not target.card.is_token,
    )
    for target in selected:
        replace_iid = None
        if len(source.owner.field) >= 5:
            replacements = _select(state.engine, source.owner, "ally_minion", source)
            if not replacements:
                return
            replace_iid = replacements[0].iid
        state.engine.move_base_minion_to_field(source.owner, target, rested=False, replace_field_iid=replace_iid)


def _sundra_magic(source: CardInstance, state: Any, ctx: Context) -> None:
    used = ctx.source
    if not isinstance(used, CardInstance) or used.owner is not source.owner or used.card.type is not CardType.MAGIC:
        return
    if _total_cost(used.card) < 4:
        return
    opponent = _opponent(state, source.owner)
    for force in opponent.forces:
        if not force.destroyed:
            state.engine._damage_force(force, 1, source)


def _orka_king_transform(source: CardInstance, state: Any, ctx: Context) -> None:
    for ci in source.owner.field:
        if _card_color(ci.card) is Color.BLUE:
            state.engine.add_keyword(ci, Keyword.SNEAKING)


def _orka_king_damage(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.source is not source or state.active is not source.owner:
        return
    for mana in source.owner.base:
        if state.engine._mana_color_of(mana) is Color.BLUE:
            mana.rested = False


def _fiora_place(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.create_tokens(source.owner, [SLIME_BLOCK_TOKEN], source=source)


def _mappirat_search(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(
        state.engine,
        source.owner,
        "deck_base_minion",
        source,
        optional=True,
        min_n=0,
        filter_fn=lambda target: (
            target.card.type is CardType.B_MINION
            and target.card.dp == 0
            and _card_color(target.card) is not Color.COLORLESS
            and _has_race(target.card, "ニンフ")
        ),
    )
    if not selected:
        state.engine.rng.shuffle(source.owner.deck)
        return
    card = selected[0]
    source.owner.deck.remove(card)
    state.engine.reveal_card(source.owner, card, "deck_search")
    state.engine.add_to_hand(source.owner, card, from_area=AreaType.DECK)
    state.engine.rng.shuffle(source.owner.deck)


def _mappirat_to_base(source: CardInstance, state: Any, ctx: Context) -> None:
    source.rested = True


def _stray_block(source: CardInstance, state: Any, ctx: Context) -> None:
    source.rested = False


def _disaster_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    opponent = _opponent(state, source.owner)
    token = _token_card(
        "slime_block_token",
        "スライム・ブロック・トークン",
        1,
        300,
        0,
        race_jp="スライム",
        keywords=[Keyword.CANNOT_BLOCK],
    )
    state.engine.create_tokens(opponent, [token], source=source)


def _mimic_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: _total_cost(target.card) <= 3,
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _rocket_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    if not any(ci.card.id == LOYAL_CANINE_ID for ci in source.owner.field):
        return
    state.engine.draw(source.owner, 1)


def _suzaku_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    source.owner.flags.add("pc02r:next_life_zero")
    if source in source.owner.trash:
        source.owner.trash.remove(source)
        source.area = AreaType.REMOVED
        source.owner.removed.append(source)
        state.engine._record_zone_move(source, AreaType.TRASH, AreaType.REMOVED)


def _platorna_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    hand = list(source.owner.hand)
    selected = _select(state.engine, source.owner, "hand_card", source, min_n=0, max_n=max(len(hand), 1))
    for card in selected:
        if card in source.owner.hand:
            source.owner.hand.remove(card)
    state.engine.rng.shuffle(selected)
    for card in selected:
        card.area = AreaType.DECK
        source.owner.deck.append(card)
    if selected:
        state.engine.draw(source.owner, len(selected))


def _dragonfly_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    opponent = _opponent(state, source.owner)
    for target in list(opponent.field):
        if _total_cost(target.card) <= 1:
            state.engine.destroy_target(target, source)


def _lightningfall_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: _card_color(target.card) is Color.COLORLESS,
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _canine_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source.area is not AreaType.FIELD or target.owner is not source.owner or target is source:
        return 0, 0
    if _has_race(target.card, "ビースト"):
        return 200, 0
    return 0, 0


def _goblin_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source.area is not AreaType.FIELD or state.active is not source.owner:
        return 0, 0
    if not any(ci.card.id == GOBLIN_QUEEN_ID for ci in source.owner.field):
        return 0, 0
    if target.owner is source.owner and _has_race(target.card, "ゴブリン"):
        return 100, 1
    return 0, 0


def _ruby_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: bool(target.blessings),
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _white_bat_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    if not any(ci.blessings for ci in source.owner.field):
        return
    opponent = _opponent(state, source.owner)
    state.engine._damage_player(opponent, 1, source)
    state.engine.heal_target(source.owner, 1)


def _prime_eagle_listen(source: CardInstance, state: Any, ctx: Context) -> bool:
    return state.active is not source.owner and ctx.target is source.owner and isinstance(ctx.source, CardInstance)


def _anttiger_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(state.engine, source.owner, "ally_base", source)
    for mana in selected:
        mana.rested = False


def _anttiger_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    source.flags.add("pc02r:anttiger_boosted")


def _anttiger_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    if "pc02r:anttiger_boosted" not in source.flags:
        return
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: state.engine.effective_bp(target) <= 400,
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _bolt_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    opponent = _opponent(state, source.owner)
    needed = max(0, len(opponent.field) - len(source.owner.field))
    if needed:
        state.engine.create_tokens(source.owner, [BOLT_COPY] * needed, source=source)


def _serpent_keyword(source: CardInstance, target: CardInstance, state: Any) -> list[Keyword]:
    if source.area is AreaType.FIELD and target.owner is source.owner and target is not source and _has_race(target.card, "モンスター"):
        return [Keyword.DEATH_BLOW]
    return []


def _vengeful_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    n = state.engine.destroyed_forces_count(source.owner)
    if n <= 0:
        return
    available = list(_opponent(state, source.owner).field)
    count = min(n, len(available))
    if count <= 0:
        return
    targets = _select(state.engine, source.owner, "enemy_minion", source, min_n=count, max_n=count)
    for target in targets:
        state.engine.destroy_target(target, source)


def _alabaster_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    opponent = _opponent(state, source.owner)
    remaining = sum(not force.destroyed for force in opponent.forces)
    state.engine._damage_player(opponent, max(0, 3 - remaining), source)


def _kascade_place(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: _total_cost(target.card) >= 5,
    )
    for target in targets:
        target.rested = True


def _minor_aid(source: CardInstance, state: Any, ctx: Context) -> None:
    amount = 3 if len(_opponent(state, source.owner).field) >= 4 else 1
    state.engine.heal_target(source.owner, amount)


def _sloth_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_force", source)
    for force in targets:
        force.rested = True


def _beast_stampede(source: CardInstance, state: Any, ctx: Context) -> None:
    for ci in source.owner.field:
        if _card_color(ci.card) is Color.GREEN:
            state.engine.modify_stat(ci, bp_delta=300, duration="turn")


def _gaia_turn_end(source: CardInstance, state: Any, ctx: Context) -> None:
    if state.active is source.owner:
        state.engine.heal_target(source.owner, 1)


def _envine_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_minion", source)
    for target in targets:
        target.flags.add("pc02r:cannot_attack_player")


def _rory_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    replace_iid = state.engine.select_base_replacement_iid(source.owner, source)
    if len(source.owner.base) >= 10 and replace_iid is None:
        return
    mana = state.engine.place_generated_colorless_mana(source.owner, replace_iid)
    mana.mana_color_override = Color.GREEN


def _rory_transform(source: CardInstance, state: Any, ctx: Context) -> None:
    for player in state.players:
        for ci in list(player.field):
            if _card_color(ci.card) is Color.COLORLESS:
                _remove_target(state.engine, ci, source)


def _rory_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_minion", source)
    for target in targets:
        target.rested = True


def _misty_place(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(
        state.engine,
        source.owner,
        "trash_field_minion",
        source,
        filter_fn=lambda target: _total_cost(target.card) == 7,
    )
    for card in selected:
        state.engine.add_to_hand(source.owner, card, from_area=AreaType.TRASH)


def _dodec_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    x = state.engine.destroyed_forces_count(_opponent(state, source.owner))
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: state.engine.effective_dp(target) <= x,
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _miscreant_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    source.flags.add("pc02r:miscreant_boosted")


def _miscreant_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    if "pc02r:miscreant_boosted" not in source.flags:
        return
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: _total_cost(target.card) <= 6,
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _ritual(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_force", source)
    for force in targets:
        state.engine._damage_force(force, 1, source)
    state.engine.heal_target(source.owner, 1)


def _darkness_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.mill_deck(source.owner, 1, source=source)
    state.engine.mill_deck(_opponent(state, source.owner), 1, source=source)


def _dorothy_turn_end(source: CardInstance, state: Any, ctx: Context) -> None:
    if state.active is not source.owner:
        return
    if "turn:pc02r_dorothy_entered" in source.owner.flags:
        return
    if not any(
        _card_color(ci.card) is Color.PURPLE and _has_race(ci.card, "ドラゴン")
        for ci in source.owner.field
    ):
        return
    if source not in source.owner.trash:
        return
    replace_iid = None
    if len(source.owner.field) >= 5:
        replacements = _select(state.engine, source.owner, "ally_minion", source)
        if not replacements:
            return
        replace_iid = replacements[0].iid
    source.owner.flags.add("turn:pc02r_dorothy_entered")
    state.engine.summon_from_trash(source.owner, source, replace_field_iid=replace_iid)


def _confusion(source: CardInstance, state: Any, ctx: Context) -> None:
    chosen = _select(state.engine, source.owner, "ally_minion", source)
    if not chosen:
        return
    cost = _total_cost(chosen[0].card)
    state.engine.destroy_target(chosen[0], source)
    opponent = _opponent(state, source.owner)
    for ci in list(opponent.field):
        if _total_cost(ci.card) == cost:
            state.engine.destroy_target(ci, source)


def _onick_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.mill_deck(source.owner, 3, source=source)
    state.engine.draw(source.owner, 1)


def _christall_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    for player in state.players:
        for ci in player.field:
            if not (_has_race(ci.card, "ドラゴン") or _has_race(ci.card, "ヒューマノイド")):
                state.engine.modify_stat(ci, bp_delta=-200, duration="permanent")


def _rekindled_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_force", source)
    for force in targets:
        state.engine._damage_force(force, 2, source)


def _rekindled_transform(source: CardInstance, state: Any, ctx: Context) -> None:
    for player in state.players:
        for ci in list(player.field):
            if ci is source:
                continue
            if _has_race(ci.card, "ドラゴン"):
                state.engine.destroy_target(ci, source)


def _rekindled_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    n = state.engine.destroyed_forces_count(_opponent(state, source.owner))
    if n <= 0:
        return
    selected = _select(
        state.engine,
        source.owner,
        "trash_field_minion",
        source,
        min_n=n,
        max_n=n,
        filter_fn=lambda target: _total_cost(target.card) <= 3,
    )
    for card in selected:
        replace_iid = None
        if len(source.owner.field) >= 5:
            replacements = _select(state.engine, source.owner, "ally_minion", source)
            if not replacements:
                return
            replace_iid = replacements[0].iid
        state.engine.summon_from_trash(source.owner, card, replace_field_iid=replace_iid)


def _rubia_place(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: state.engine.effective_bp(target) <= 400,
    )
    for target in targets:
        state.engine.add_keyword(target, Keyword.CANNOT_BLOCK)


def _rock_imp_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.block_life_gain_and_damage_reduction(_opponent(state, source.owner))


def _ruler_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(state.engine, source.owner, "ally_colorless_mana_token", source, min_n=0, max_n=1)
    if not selected:
        return
    state.engine._eject_base_card(source.owner, selected[0])
    state.engine.create_tokens(source.owner, [S_GOLEM_TOKEN], source=source)


def _golem_call(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "ally_minion", source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=300, duration="turn")
        if _has_race(target.card, "ゴレイム"):
            state.engine.create_tokens(source.owner, [S_GOLEM_TOKEN], source=source)


def _fire_rain(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: state.engine.effective_bp(target) < target.card.bp,
    )
    for target in targets:
        state.engine.destroy_target(target, source)


def _dwarf_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_minion", source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=-200, duration="turn")


def _flames_blocked(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.target is source and state.active is source.owner


def _flames_block_damage(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine._damage_player(_opponent(state, source.owner), 1, source)


def _lava_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.create_tokens(source.owner, [LAVA_SLIME_COPY], source=source)


def _zaura_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "enemy_minion", source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=-500, duration="turn")


def _zaura_transform(source: CardInstance, state: Any, ctx: Context) -> None:
    for ci in _opponent(state, source.owner).field:
        state.engine.modify_stat(ci, bp_delta=-300, duration="turn")


def _zaura_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    if isinstance(ctx.target, Player) and ctx.target is not source.owner:
        state.engine.draw(source.owner, 1)


def _shaina_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(
        state.engine,
        source.owner,
        "hand_card",
        source,
        optional=True,
        min_n=0,
        filter_fn=lambda target: (
            target.card.type is CardType.F_MINION
            and _card_color(target.card) is Color.RED
            and _has_race(target.card, "ドラゴン")
        ),
    )
    for card in selected:
        replace_iid = None
        if len(source.owner.field) >= 5:
            replacements = _select(state.engine, source.owner, "ally_minion", source)
            if not replacements:
                return
            replace_iid = replacements[0].iid
        state.engine.put_field_minion_from_hand(source.owner, card, replace_field_iid=replace_iid)
        card.flags.add("pc02r:cannot_move")
        card.flags.add("pc02r:destroy_at_owner_turn_end")


def _flair_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    for ci in _opponent(state, source.owner).field:
        state.engine.modify_stat(ci, bp_delta=-200, duration="permanent")


def _flair_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    if state.active is not source.owner:
        return
    if source in source.owner.trash:
        state.engine.add_to_hand(source.owner, source, from_area=AreaType.TRASH)


def _nicold_place(source: CardInstance, state: Any, ctx: Context) -> None:
    source.owner.flags.add("pc02r:nicold_force_reduce")
    source.owner.flags.discard("pc02r:nicold_seen_own_end")


def _sky_squid_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    for force in source.owner.forces:
        if not force.destroyed:
            state.engine.heal_target(force, 1)
            force.rested = False


def _metal_wall(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "ally_minion", source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=300, duration="turn")
        target.flags.add("turn:pc02r_effect_untargetable")


def _parvell_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "ally_minion",
        source,
        filter_fn=lambda target: _has_race(target.card, "アンドロイド", "ウイング"),
    )
    for target in targets:
        state.engine.modify_stat(target, bp_delta=200, duration="permanent")


def _artillery_win(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.source is not source or not isinstance(ctx.target, CardInstance):
        return
    _remove_target(state.engine, ctx.target, source)


def _schuz_listen(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        state.active is not source.owner
        and isinstance(ctx.target, ForceInstance)
        and ctx.target.owner is source.owner
        and isinstance(ctx.source, CardInstance)
    )


def _halo_damage(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.source is source:
        state.engine.modify_stat(source, bp_delta=200, duration="permanent")


def _assembly(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, 3)
    n = state.engine.destroyed_forces_count(source.owner)
    if n <= 0:
        return
    required = min(n, len(source.owner.hand))
    selected = _select(
        state.engine,
        source.owner,
        "hand_card",
        source,
        min_n=required,
        max_n=required,
    )
    for card in selected:
        state.engine.discard_from_hand(source.owner, card)


def _aizalf_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    n = sum(not force.destroyed for force in source.owner.forces)
    if n:
        state.engine.modify_stat(source, bp_delta=100 * n, duration="permanent")


def _aizalf_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: not target.rested,
    )
    for target in targets:
        target.flags.add("turn:must_block")


def _griphone_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, 2)
    selected = _select(state.engine, source.owner, "hand_card", source, min_n=min(2, len(source.owner.hand)), max_n=2)
    for card in selected:
        state.engine.discard_from_hand(source.owner, card)


def _griphone_transform(source: CardInstance, state: Any, ctx: Context) -> None:
    for ci in source.owner.field:
        state.engine.modify_stat(ci, bp_delta=100, duration="permanent")
        state.engine.add_keyword(ci, Keyword.REAWAKEN)


def _griphone_win(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.source is source and state.active is source.owner and isinstance(ctx.target, CardInstance):
        source.rested = False


def _gus_place(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "ally_minion", source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=200, duration="permanent")


def _build_up(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "ally_minion", source)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=200, duration="turn")
        target.flags.add("pc02r:build_up")


def _build_up_win(source: CardInstance, state: Any, ctx: Context) -> None:
    winner = ctx.source
    if not isinstance(winner, CardInstance) or "pc02r:build_up" not in winner.flags:
        return
    if source in source.owner.trash:
        state.engine.add_to_hand(source.owner, source, from_area=AreaType.TRASH)


def _swallow_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "other_ally_minion",
        source,
    )
    for target in targets:
        state.engine.modify_stat(target, bp_delta=200, duration="turn")


def _karapace_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "ally_minion",
        source,
        filter_fn=lambda target: _card_color(target.card) is Color.YELLOW,
    )
    for target in targets:
        target.flags.add("turn:pc02r_dragon_block_only")


def _thunder_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source is not target or source.area is not AreaType.FIELD:
        return 0, 0
    summoned = getattr(state, "summoned_this_turn", ())
    if any(ci is not source and getattr(ci, "owner", None) is source.owner for ci in summoned):
        return 200, 1
    return 0, 0


def _lucia_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(
        state.engine,
        source.owner,
        "ally_minion",
        source,
        filter_fn=lambda target: _card_color(target.card) is Color.YELLOW and _has_race(target.card, "ドラゴン"),
    )
    for target in selected:
        bp, dp = target.card.bp, target.card.dp
        state.engine.return_to_hand(target)
        state.engine.modify_stat(source, bp_delta=bp - source.card.bp, dp_delta=dp - source.card.dp, duration="permanent")


def _assault_dive(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(
        state.engine,
        source.owner,
        "deck_minion",
        source,
        filter_fn=lambda target: (
            target.card.type is CardType.F_MINION
            and _card_color(target.card) is Color.YELLOW
            and _total_cost(target.card) == 4
        ),
    )
    for card in selected:
        replace_iid = None
        if len(source.owner.field) >= 5:
            replacements = _select(state.engine, source.owner, "ally_minion", source)
            if not replacements:
                state.engine.rng.shuffle(source.owner.deck)
                return
            replace_iid = replacements[0].iid
        state.engine.summon_from_deck(source.owner, card, replace_field_iid=replace_iid)
    state.engine.rng.shuffle(source.owner.deck)


def _skye_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    opponent = _opponent(state, source.owner)
    for ci in list(opponent.field):
        if _total_cost(ci.card) <= 3:
            state.engine.return_to_hand(ci)


def _hardin_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    selected = _select(
        state.engine,
        source.owner,
        "hand_card",
        source,
        filter_fn=lambda target: target.card.type is CardType.F_MINION and _total_cost(target.card) <= 4,
    )
    for card in selected:
        replace_iid = None
        if len(source.owner.field) >= 5:
            replacements = _select(state.engine, source.owner, "ally_minion", source)
            if not replacements:
                return
            replace_iid = replacements[0].iid
        state.engine.put_field_minion_from_hand(source.owner, card, replace_field_iid=replace_iid)


def _hardin_transform(source: CardInstance, state: Any, ctx: Context) -> None:
    for ci in source.owner.field:
        if ci is not source:
            state.engine.modify_stat(ci, bp_delta=200, dp_delta=1, duration="turn")


def _hardin_attack(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(
        state.engine,
        source.owner,
        "enemy_minion",
        source,
        filter_fn=lambda target: _total_cost(target.card) <= 6,
    )
    for target in targets:
        target.flags.add("pc02r:cannot_attack")
        target.flags.add("pc02r:cannot_block")
        target.flags.add("pc02r:cannot_move")
        target.flags.add("pc02r:lock_until_own_end")


def _dual_eagle_summon(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = _select(state.engine, source.owner, "ally_minion", source, min_n=2, max_n=2)
    for target in targets:
        state.engine.modify_stat(target, bp_delta=300, duration="turn")


def _refresh_self(source: CardInstance, state: Any, ctx: Context) -> None:
    source.rested = False


def _used_own_magic(source: CardInstance, state: Any, ctx: Context) -> bool:
    used = ctx.source
    return isinstance(used, CardInstance) and used.card.type is CardType.MAGIC and used.owner is source.owner


def _damaged_by_self(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _movement_plus(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.grant_movement_right(source.owner, 1)


def _draw_one(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def _draw_three(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, 3)


def _plakanna_destroy(source: CardInstance, state: Any, ctx: Context) -> None:
    state.engine.draw(source.owner, 3)


# --- tables -------------------------------------------------------------

_PC02R_KEYWORDS: dict[str, list[Keyword]] = {
    "blue_00_01_02r_00": [Keyword.KAGO],
    "blue_00_01_02r_01": [Keyword.KAGO],
    "blue_07_02_02r_01": [Keyword.RUSH],
    "colorless_00_01_02r_00": [Keyword.KAGO],
    "colorless_04_02_02r_02": [Keyword.REAWAKEN],
    "colorless_08_02_02r_00": [Keyword.DEATH_BLOW],
    "colorless_010_02_02r_00": [Keyword.RUSH],
    "green_00_01_02r_00": [Keyword.KAGO],
    "green_00_01_02r_01": [Keyword.KAGO],
    "green_06_02_02r_00": [Keyword.PENETRATE],
    "green_07_02_02r_01": [Keyword.RUSH],
    "green_08_02_02r_00": [Keyword.PENETRATE],
    "purple_00_01_02r_00": [Keyword.KAGO],
    "purple_00_01_02r_01": [Keyword.KAGO],
    "purple_04_02_02r_01": [Keyword.CANNOT_BLOCK],
    "purple_06_02_02r_01": [Keyword.DEATH_BLOW],
    "purple_07_02_02r_01": [Keyword.RUSH],
    "red_00_01_02r_00": [Keyword.KAGO],
    "red_00_01_02r_01": [Keyword.KAGO],
    "red_07_02_02r_01": [Keyword.RUSH],
    "white_00_01_02r_00": [Keyword.KAGO],
    "white_00_01_02r_01": [Keyword.KAGO],
    "white_07_02_02r_01": [Keyword.RUSH, Keyword.REAWAKEN],
    "yellow_00_01_02r_00": [Keyword.KAGO],
    "yellow_00_01_02r_01": [Keyword.KAGO],
    "yellow_02_02_02r_00": [Keyword.FLYING],
    "yellow_07_02_02r_01": [Keyword.RUSH],
    "yellow_08_02_02r_00": [Keyword.FLYING],
}

_PC02R_AURAS: dict[str, Callable] = {
    "colorless_05_02_02r_00": _canine_aura,
    "colorless_04_02_02r_02": _goblin_aura,
    "yellow_04_02_02r_01": _thunder_aura,
}

_PC02R_KEYWORD_AURAS: dict[str, Callable] = {
    "blue_02_02_02r_00": _explorer_keyword,
    "colorless_08_02_02r_00": _serpent_keyword,
}

_PC02R_EFFECTS: dict[str, tuple[EffectSpec, ...]] = {
    "blue_00_01_02r_01": (
        _effect(EffectTiming.ON_PLACE_BASE, _cortney_place, condition=_self_source, official_effect="マナ4つ以上なら1枚引く", official_timing="配置時", active_areas=(AreaType.BASE,)),
    ),
    "blue_01_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _cogito, official_effect="1枚引き移動権を消費して無色マナを置く", official_timing="メイン"),
    ),
    "blue_03_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _add_named_from_outside(WAITRESS_EXTRA_GAME_ID), condition=_self_source, official_effect="ヴァイオレントストリームをゲーム外から加える", official_timing="召喚時"),
    ),
    "blue_04_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _movement_plus, condition=_self_source, official_effect="移動権+1", official_timing="召喚時"),
    ),
    "blue_04_02_02r_01": (
        _effect(EffectTiming.MOVE_TO_BASE, _brighton_retreat, condition=_self_source, target_kind="enemy_minion", official_effect="相手1体にBP-100/DP-1", official_timing="後退時", active_areas=(AreaType.BASE,)),
    ),
    "blue_04_02_02r_02": (
        _effect(EffectTiming.ON_CARD_USED, _oceans_magic, condition=_used_own_magic, target_kind="enemy_minion", params={"max_cost": 5, "moves_targets_to_base": True}, official_effect="コスト5以下をベースへ", official_timing="常時"),
        _effect(EffectTiming.ON_BLESS, _anju_bless, condition=_self_source, official_effect="他色なら除外して大変身", official_timing="加護時"),
    ),
    "blue_04_03_02r_00": (
        _effect(
            EffectTiming.ON_CAST_MAGIC,
            _wizardry,
            target_kind="enemy_minion",
            params={
                "color": "COLORLESS",
                "extra_targets_if_own_color_race": {"color": "BLUE", "race": "ドラゴン"},
                "followup_target_kind": "enemy_minion",
                "followup_max_targets": 1,
                "followup_exclude_first_targets": True,
                "moves_targets_to_base": True,
            },
            official_effect="無色破壊後ベースへ移動",
            official_timing="メイン/フラッシュ",
        ),
    ),
    "blue_05_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _selene_summon, condition=_selene_listen, optional=True, target_kind="deck_card", params={"card_type": "MAGIC"}, official_effect="マジックを検索できる", official_timing="召喚時"),
    ),
    "blue_06_02_02r_00": (
        _effect(EffectTiming.ON_DAMAGE_PLAYER, _tiger_damage, condition=_damaged_by_self, target_kind="ally_minion_base", params={"exclude_tokens": True}, official_effect="ベースのミニオンをフィールドへ", official_timing="自分のターン"),
    ),
    "blue_06_02_02r_01": (
        _effect(EffectTiming.ON_CARD_USED, _sundra_magic, condition=_used_own_magic, official_effect="コスト4以上のマジックでフォース1ダメージ", official_timing="常時"),
    ),
    "blue_07_02_02r_00": (
        build_effect("look_top_to_hand", EffectTiming.ON_SUMMON, condition=_self_source, target_kind="top3_card", top_n=3, official_effect="上3枚から1枚公開して手札", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _legend_bless, condition=_self_source, official_effect="青加護なら変形", official_timing="加護時"),
    ),
    "blue_07_02_02r_01": (
        _effect(EffectTiming.ON_TRANSFORM, _orka_king_transform, condition=_self_source, official_effect="青ミニオンに潜入", official_timing="変形時"),
        _effect(EffectTiming.ON_DAMAGE_PLAYER, _orka_king_damage, condition=_damaged_by_self, official_effect="青マナをアクティブ", official_timing="アタック時"),
        _effect(EffectTiming.ON_DAMAGE_FORCE, _orka_king_damage, condition=_damaged_by_self, official_effect="青マナをアクティブ", official_timing="アタック時"),
    ),
    "colorless_00_01_02r_00": (
        _effect(EffectTiming.ON_PLACE_BASE, _fiora_place, condition=_self_source, official_effect="スライム・ブロック・トークンを出す", official_timing="配置時", active_areas=(AreaType.BASE,)),
    ),
    "colorless_01_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _mappirat_search, condition=_self_source, optional=True, target_kind="deck_base_minion", params={"race": "ニンフ", "max_dp": 0, "exclude_color": "COLORLESS"}, official_effect="DP0有色ニンフを検索できる", official_timing="召喚時"),
        _effect(EffectTiming.MOVE_TO_BASE, _mappirat_to_base, condition=_self_source, official_effect="ベースへレストで移動", official_timing="常時", active_areas=(AreaType.BASE,)),
    ),
    "colorless_02_02_02r_00": (
        _effect(EffectTiming.ON_BLOCK, _stray_block, condition=_self_source, official_effect="ブロック時アクティブ", official_timing="ブロック時"),
    ),
    "colorless_02_02_02r_01": (
        _effect(EffectTiming.ON_SUMMON, _disaster_summon, condition=_self_source, official_effect="相手にブロック不可スライム", official_timing="召喚時"),
    ),
    "colorless_03_02_02r_00": (
        _effect(EffectTiming.ON_DESTROY, _mimic_destroy, target_kind="enemy_minion", params={"max_cost": 3}, official_effect="コスト3以下を破壊", official_timing="破壊時"),
    ),
    "colorless_03_02_02r_01": (
        _effect(EffectTiming.ON_ATTACK, _rocket_attack, condition=_self_source, official_effect="ロイヤルドッグがいれば1枚引く", official_timing="アタック時"),
    ),
    "colorless_03_02_02r_02": (
        _effect(EffectTiming.ON_DESTROY, _suzaku_destroy, official_effect="次のライフダメージ0にして除外", official_timing="破壊時"),
    ),
    "colorless_03_02_02r_03": (
        _effect(EffectTiming.ON_SUMMON, _platorna_summon, condition=_self_source, target_kind="hand_card", min_targets=0, max_targets=10, optional=True, official_effect="任意枚破棄して同数引き下に戻す", official_timing="召喚時"),
    ),
    "colorless_04_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _dragonfly_summon, condition=_self_source, official_effect="コスト1以下を全て破壊", official_timing="召喚時"),
    ),
    "colorless_04_02_02r_01": (
        _effect(EffectTiming.ON_SUMMON, _draw_one, condition=_self_source, official_effect="1枚引く", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _anju_bless, condition=_self_source, official_effect="有色ならマナをベースへ戻し大変身", official_timing="加護時"),
    ),
    "colorless_04_02_02r_03": (
        _effect(EffectTiming.ON_SUMMON, _lightningfall_summon, condition=_self_source, target_kind="enemy_minion", params={"color": "COLORLESS"}, official_effect="無色1体破壊", official_timing="召喚時"),
    ),
    "colorless_05_02_02r_01": (
        _effect(EffectTiming.ON_SUMMON, _ruby_summon, condition=_self_source, target_kind="enemy_minion", params={"requires_blessing": True}, official_effect="加護された1体を破壊", official_timing="召喚時"),
    ),
    "colorless_06_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _white_bat_summon, condition=_self_source, official_effect="加護がいればライフ1ダメージ1回復", official_timing="召喚時"),
    ),
    "colorless_06_02_02r_01": (
        _effect(EffectTiming.ON_ATTACK, _refresh_self, condition=_prime_eagle_listen, official_effect="ライフが攻撃されたらアクティブ", official_timing="相手のターン"),
    ),
    "colorless_07_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _anttiger_summon, condition=_self_source, target_kind="ally_base", official_effect="マナ1つをアクティブ", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _anttiger_bless, condition=_self_source, official_effect="アタック時BP400以下破壊を付与", official_timing="加護時"),
        _effect(EffectTiming.ON_ATTACK, _anttiger_attack, condition=_self_source, target_kind="enemy_minion", params={"max_bp": 400}, official_effect="BP400以下を破壊", official_timing="アタック時"),
    ),
    "colorless_07_02_02r_01": (
        _effect(EffectTiming.ON_SUMMON, _bolt_summon, condition=_self_source, official_effect="相手と同数になるまでコピー", official_timing="召喚時"),
    ),
    "colorless_09_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _vengeful_summon, condition=_self_source, target_kind="enemy_minion", params={"exact_target_count_from_own_destroyed_forces": True}, official_effect="破壊フォース数だけ相手を破壊", official_timing="召喚時"),
    ),
    "colorless_010_02_02r_00": (
        _effect(EffectTiming.ON_ATTACK, _alabaster_attack, condition=_self_source, official_effect="ライフ3ダメージ、フォース毎に-1", official_timing="アタック時"),
    ),
    "green_00_01_02r_01": (
        _effect(EffectTiming.ON_PLACE_BASE, _kascade_place, condition=_self_source, target_kind="enemy_minion", params={"min_cost": 5}, official_effect="コスト5以上をレスト", official_timing="配置時", active_areas=(AreaType.BASE,)),
    ),
    "green_01_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _minor_aid, official_effect="1回復、相手4体以上なら3", official_timing="メイン/フラッシュ"),
    ),
    "green_02_02_02r_00": (
        _effect(EffectTiming.ON_DESTROY, _sloth_destroy, target_kind="enemy_force", official_effect="相手フォースをレスト", official_timing="破壊時"),
    ),
    "green_02_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _beast_stampede, official_effect="緑ミニオンBP+300", official_timing="フラッシュ"),
    ),
    "green_03_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _add_named_from_outside(ELF_SHAMAN_EXTRA_GAME_ID), condition=_self_source, official_effect="トーンダウンをゲーム外から加える", official_timing="召喚時"),
    ),
    "green_04_02_02r_01": (
        _effect(EffectTiming.TURN_END, _gaia_turn_end, official_effect="1回復", official_timing="自分のターン終了時"),
        _effect(EffectTiming.ON_BLESS, _anju_bless, condition=_self_source, official_effect="他色なら除外して大変身", official_timing="加護時"),
    ),
    "green_06_02_02r_01": (
        _effect(EffectTiming.ON_SUMMON, _envine_summon, condition=_self_source, target_kind="enemy_minion", official_effect="プレイヤー攻撃不可を付与", official_timing="召喚時"),
    ),
    "green_07_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _rory_summon, condition=_self_source, official_effect="緑マナをベースに置く", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _legend_bless, condition=_self_source, official_effect="緑加護なら変形", official_timing="加護時"),
    ),
    "green_07_02_02r_01": (
        _effect(EffectTiming.ON_TRANSFORM, _rory_transform, condition=_self_source, official_effect="無色を全て除外", official_timing="変形時"),
        _effect(EffectTiming.ON_ATTACK, _rory_attack, condition=_self_source, target_kind="enemy_minion", official_effect="相手1体レスト", official_timing="アタック時"),
    ),
    "green_08_02_02r_00": (
        _effect(EffectTiming.ON_DESTROY, _plakanna_destroy, official_effect="3枚引く", official_timing="破壊時"),
    ),
    "purple_00_01_02r_01": (
        _effect(EffectTiming.ON_PLACE_BASE, _misty_place, condition=_self_source, target_kind="trash_field_minion", params={"min_cost": 7, "max_cost": 7}, official_effect="コスト7フィールドを手札に戻す", official_timing="配置時", active_areas=(AreaType.BASE,)),
    ),
    "purple_02_02_02r_00": (
        _effect(EffectTiming.ON_DESTROY, _dodec_destroy, target_kind="enemy_minion", params={"max_dp_from_opponent_destroyed_forces": True}, official_effect="DPが破壊フォース以下を破壊", official_timing="破壊時"),
    ),
    "purple_03_02_02r_00": (
        _effect(EffectTiming.ON_BLESS, _miscreant_bless, condition=_self_source, official_effect="破壊時コスト6以下破壊を付与", official_timing="加護時"),
        _effect(EffectTiming.ON_DESTROY, _miscreant_destroy, target_kind="enemy_minion", params={"max_cost": 6}, official_effect="コスト6以下を破壊", official_timing="破壊時"),
    ),
    "purple_03_02_02r_01": (
        _effect(EffectTiming.ON_SUMMON, _add_named_from_outside(CLUB_SKELETON_EXTRA_GAME_ID), condition=_self_source, official_effect="マッドピッドをゲーム外から加える", official_timing="召喚時"),
    ),
    "purple_03_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _ritual, target_kind="enemy_force", official_effect="フォース1ダメージと1回復", official_timing="メイン"),
    ),
    "purple_04_02_02r_00": (
        _effect(EffectTiming.ON_ATTACK, _darkness_attack, condition=_self_source, official_effect="互いのデッキ上1枚破棄", official_timing="アタック時"),
        _effect(EffectTiming.ON_BLESS, _anju_bless, condition=_self_source, official_effect="他色なら除外して大変身", official_timing="加護時"),
    ),
    "purple_04_02_02r_01": (
        _effect(EffectTiming.TURN_END, _dorothy_turn_end, official_effect="紫ドラゴンがいればフィールドへ", official_timing="自分のターン終了時", active_areas=(AreaType.TRASH,), params={"once_per_turn_flag": "turn:pc02r_dorothy_entered", "once_per_turn_scope": "owner"}),
    ),
    "purple_04_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _confusion, target_kind="ally_minion", official_effect="自分1体破壊し同コストを破壊", official_timing="メイン/フラッシュ"),
    ),
    "purple_05_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _onick_summon, condition=_self_source, official_effect="上3枚破棄して1枚引く", official_timing="召喚時"),
    ),
    "purple_06_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _christall_summon, condition=_self_source, official_effect="ドラゴン/ヒューマノイド以外BP-200", official_timing="召喚時"),
    ),
    "purple_07_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _rekindled_summon, condition=_self_source, target_kind="enemy_force", official_effect="フォースに2ダメージ", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _legend_bless, condition=_self_source, official_effect="紫加護なら変形", official_timing="加護時"),
    ),
    "purple_07_02_02r_01": (
        _effect(EffectTiming.ON_TRANSFORM, _rekindled_transform, condition=_self_source, official_effect="他のドラゴンを破壊", official_timing="変形時"),
        _effect(EffectTiming.ON_ATTACK, _rekindled_attack, condition=_self_source, target_kind="trash_field_minion", min_targets=0, max_targets=10, params={"max_cost": 3, "exact_target_count_from_opponent_destroyed_forces": True, "puts_targets_on_field": True}, official_effect="コスト3以下をX体出す", official_timing="アタック時"),
    ),
    "red_00_01_02r_01": (
        _effect(EffectTiming.ON_PLACE_BASE, _rubia_place, condition=_self_source, target_kind="enemy_minion", params={"max_bp": 400}, official_effect="BP400以下はブロック不可", official_timing="配置時", active_areas=(AreaType.BASE,)),
    ),
    "red_02_02_02r_00": (
        _effect(EffectTiming.ON_BLESS, _rock_imp_bless, condition=_self_source, official_effect="相手の軽減と回復を封じる", official_timing="加護時"),
    ),
    "red_02_02_02r_01": (
        _effect(EffectTiming.ON_SUMMON, _ruler_summon, condition=_self_source, optional=True, target_kind="ally_colorless_mana_token", min_targets=0, max_targets=1, official_effect="無色マナを破壊してSゴレイム", official_timing="召喚時"),
    ),
    "red_02_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _golem_call, target_kind="ally_minion", official_effect="BP+300、ゴレイムならトークン", official_timing="フラッシュ"),
    ),
    "red_02_03_02r_01": (
        _effect(EffectTiming.ON_CAST_MAGIC, _fire_rain, target_kind="enemy_minion", params={"bp_below_printed": True}, official_effect="本来より低いBPを破壊", official_timing="メイン/フラッシュ"),
    ),
    "red_04_02_02r_00": (
        _effect(EffectTiming.ON_ATTACK, _dwarf_attack, condition=_self_source, target_kind="enemy_minion", official_effect="BP-200", official_timing="アタック時"),
    ),
    "red_04_02_02r_01": (
        _effect(EffectTiming.ON_BLOCK, _flames_block_damage, condition=_flames_blocked, official_effect="ブロックされたらライフ1ダメージ", official_timing="自分のターン"),
        _effect(EffectTiming.ON_BLESS, _anju_bless, condition=_self_source, official_effect="他色なら除外して大変身", official_timing="加護時"),
    ),
    "red_06_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _lava_summon, condition=_self_source, official_effect="ラヴァ・スライムをもう1体出す", official_timing="召喚時"),
    ),
    "red_07_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _zaura_summon, condition=_self_source, target_kind="enemy_minion", official_effect="BP-500", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _legend_bless, condition=_self_source, official_effect="赤加護なら変形", official_timing="加護時"),
    ),
    "red_07_02_02r_01": (
        _effect(EffectTiming.ON_TRANSFORM, _zaura_transform, condition=_self_source, official_effect="相手全てBP-300", official_timing="変形時"),
        _effect(EffectTiming.ON_ATTACK, _zaura_attack, condition=_self_source, official_effect="プレイヤー攻撃なら1枚引く", official_timing="アタック時"),
    ),
    "red_07_02_02r_02": (
        _effect(EffectTiming.ON_SUMMON, _shaina_summon, condition=_self_source, optional=True, target_kind="hand_card", params={"card_type": "F_MINION", "color": "RED", "race": "ドラゴン"}, official_effect="手札の赤ドラゴンを出せる", official_timing="召喚時"),
    ),
    "red_08_02_02r_00": (
        _effect(EffectTiming.ON_ATTACK, _flair_attack, condition=_self_source, official_effect="相手全てBP-200", official_timing="アタック時"),
        _effect(EffectTiming.ON_DESTROY, _flair_destroy, official_effect="自分のターンなら手札に戻す", official_timing="破壊時"),
    ),
    "white_00_01_02r_01": (
        _effect(EffectTiming.ON_PLACE_BASE, _nicold_place, condition=_self_source, official_effect="フォースダメージ1軽減", official_timing="配置時", active_areas=(AreaType.BASE,)),
    ),
    "white_02_02_02r_00": (
        _effect(EffectTiming.ON_BLESS, _sky_squid_bless, condition=_self_source, official_effect="フォース全て1回復してアクティブ", official_timing="加護時"),
    ),
    "white_02_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _metal_wall, target_kind="ally_minion", official_effect="BP+300し効果対象にならない", official_timing="フラッシュ"),
    ),
    "white_03_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _parvell_summon, condition=_self_source, target_kind="ally_minion", params={"races": ["アンドロイド", "ウイング"]}, official_effect="アンドロイド/ウイングにBP+200", official_timing="召喚時"),
    ),
    "white_04_02_02r_00": (
        _effect(EffectTiming.ON_BATTLE_WIN, _artillery_win, official_effect="バトルした相手を除外", official_timing="常時"),
        _effect(EffectTiming.ON_BLESS, _anju_bless, condition=_self_source, official_effect="他色なら除外して大変身", official_timing="加護時"),
    ),
    "white_04_02_02r_01": (
        _effect(EffectTiming.ON_ATTACK, _refresh_self, condition=_schuz_listen, official_effect="フォースが攻撃されたらアクティブ", official_timing="相手のターン"),
    ),
    "white_04_02_02r_02": (
        _effect(EffectTiming.ON_DAMAGE_PLAYER, _halo_damage, condition=_damaged_by_self, official_effect="ダメージ時BP+200", official_timing="アタック時"),
        _effect(EffectTiming.ON_DAMAGE_FORCE, _halo_damage, condition=_damaged_by_self, official_effect="ダメージ時BP+200", official_timing="アタック時"),
    ),
    "white_05_03_02r_00": (
        _effect(
            EffectTiming.ON_CAST_MAGIC,
            _assembly,
            target_kind="hand_card",
            params={
                "post_draw_discard_hand": True,
                "draw_amount": 3,
                "exact_target_count_from_own_destroyed_forces": True,
            },
            official_effect="3枚引き破壊フォース数破棄",
            official_timing="メイン",
        ),
    ),
    "white_06_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _aizalf_summon, condition=_self_source, official_effect="フォース毎にBP+100", official_timing="召喚時"),
        _effect(EffectTiming.ON_ATTACK, _aizalf_attack, condition=_self_source, target_kind="enemy_minion", params={"only_active": True}, official_effect="アクティブ1体は必ずブロック", official_timing="アタック時"),
    ),
    "white_07_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _griphone_summon, condition=_self_source, target_kind="hand_card", min_targets=2, max_targets=2, official_effect="2枚引き2枚破棄", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _legend_bless, condition=_self_source, official_effect="白加護なら変形", official_timing="加護時"),
    ),
    "white_07_02_02r_01": (
        _effect(EffectTiming.ON_TRANSFORM, _griphone_transform, condition=_self_source, official_effect="BP+100と再起", official_timing="変形時"),
        _effect(EffectTiming.ON_BATTLE_WIN, _griphone_win, official_effect="バトル勝利でアクティブ", official_timing="自分のターン"),
    ),
    "yellow_00_01_02r_01": (
        _effect(EffectTiming.ON_PLACE_BASE, _gus_place, condition=_self_source, target_kind="ally_minion", official_effect="BP+200", official_timing="配置時", active_areas=(AreaType.BASE,)),
    ),
    "yellow_01_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _build_up, target_kind="ally_minion", official_effect="バトル中BP+200、勝利なら回収", official_timing="フラッシュ"),
        _effect(EffectTiming.ON_BATTLE_WIN, _build_up_win, official_effect="勝利したミニオンがいれば手札に戻る", official_timing="フラッシュ", active_areas=(AreaType.TRASH,)),
    ),
    "yellow_02_02_02r_01": (
        build_effect("look_top_to_hand", EffectTiming.ON_BLESS, condition=_self_source, target_kind="top3_field_minion", top_n=3, official_effect="上3枚からフィールド・ミニオン1枚", official_timing="加護時"),
    ),
    "yellow_03_02_02r_00": (
        _effect(EffectTiming.ON_ATTACK, _swallow_attack, condition=_self_source, target_kind="other_ally_minion", official_effect="他の1体BP+200", official_timing="アタック時"),
    ),
    "yellow_04_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _karapace_summon, condition=_self_source, target_kind="ally_minion", params={"color": "YELLOW"}, official_effect="黄1体はドラゴン/ドラゴニュート以外にブロックされない", official_timing="召喚時"),
    ),
    "yellow_04_02_02r_01": (
        _effect(EffectTiming.ON_BLESS, _anju_bless, condition=_self_source, official_effect="他色なら除外して大変身", official_timing="加護時"),
    ),
    "yellow_04_02_02r_02": (
        _effect(EffectTiming.ON_SUMMON, _lucia_summon, condition=_self_source, target_kind="ally_minion", params={"color": "YELLOW", "race": "ドラゴン"}, official_effect="黄ドラゴンを手札に戻しBP/DPを得る", official_timing="召喚時"),
    ),
    "yellow_05_03_02r_00": (
        _effect(EffectTiming.ON_CAST_MAGIC, _assault_dive, target_kind="deck_minion", params={"card_type": "F_MINION", "color": "YELLOW", "min_cost": 4, "max_cost": 4}, official_effect="コスト4の黄フィールドを出す", official_timing="メイン/フラッシュ"),
    ),
    "yellow_06_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _skye_summon, condition=_self_source, official_effect="コスト3以下を手札に戻す", official_timing="召喚時"),
    ),
    "yellow_07_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _hardin_summon, condition=_self_source, target_kind="hand_card", params={"card_type": "F_MINION", "max_cost": 4}, official_effect="コスト4以下を手札から出す", official_timing="召喚時"),
        _effect(EffectTiming.ON_BLESS, _legend_bless, condition=_self_source, official_effect="黄加護なら変形", official_timing="加護時"),
    ),
    "yellow_07_02_02r_01": (
        _effect(EffectTiming.ON_TRANSFORM, _hardin_transform, condition=_self_source, official_effect="他の味方BP+200/DP+1", official_timing="変形時"),
        _effect(EffectTiming.ON_ATTACK, _hardin_attack, condition=_self_source, target_kind="enemy_minion", params={"max_cost": 6}, official_effect="コスト6以下は攻撃/ブロック/移動不可", official_timing="アタック時"),
    ),
    "yellow_08_02_02r_00": (
        _effect(EffectTiming.ON_SUMMON, _dual_eagle_summon, condition=_self_source, target_kind="ally_minion", min_targets=2, max_targets=2, official_effect="2体BP+300", official_timing="召喚時"),
    ),
}

_ENGINE_RULE_IDS = {
    "colorless_00_02_02r_00",
    "colorless_02_02_02r_00",
    "green_02_02_02r_00",
    "green_04_02_02r_00",
    "green_05_02_02r_00",
    "green_06_02_02r_00",
    "purple_06_02_02r_01",
    "white_05_02_02r_00",
    "white_06_02_02r_01",
    "yellow_02_02_02r_00",
    "red_05_02_02r_00",
}


def _printed_cost(card: Card) -> dict[Color, int]:
    if card.type is CardType.B_MINION or card.id == "colorless_00_02_02r_00":
        return {}
    total = _cost_from_image_id(card.id)
    stats = _CROP_STATS.get(card.id)
    if stats and stats[0] is not None:
        total = stats[0]
    if total <= 0:
        return {}
    color = _card_color(card) if card.cost else Color.COLORLESS
    if card.id.startswith("colorless_") or color is Color.COLORLESS:
        return {Color.COLORLESS: total}
    colored = 1
    leftover = total - colored
    cost = {color: colored}
    if leftover:
        cost[Color.COLORLESS] = leftover
    return cost


def _pc02r_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("pack_jp_official") == PC02R_PACK_JP and "_02r_" in (row.get("image_id") or "")
        ]
    rows.sort(key=lambda row: int(row.get("official_order") or 999999))
    return rows


def _pc02r_card_from_row(row: dict[str, str]) -> Card:
    card = _card_from_row(row)
    stats = _CROP_STATS.get(card.id)
    if stats is not None:
        _cost_total, bp, dp = stats
        card.bp = bp
        card.dp = dp
    card.cost = _printed_cost(card)
    card.effects = list(_PC02R_EFFECTS.get(card.id, ()))
    card.aura = _PC02R_AURAS.get(card.id)
    card.keyword_aura = _PC02R_KEYWORD_AURAS.get(card.id)
    card.keywords = list(_PC02R_KEYWORDS.get(card.id, ()))
    source_id = REPRINT_SOURCE_IDS.get(card.id)
    if source_id and source_id in CARD_REGISTRY:
        source = CARD_REGISTRY[source_id]
        if not card.ability_jp:
            card.ability_jp = source.ability_jp
        if not card.ability_en:
            card.ability_en = source.ability_en
        if not card.name_en:
            card.name_en = source.name_en
    if card.type is CardType.MAGIC:
        if card.id in _FLASH_ONLY:
            card.main_timing_ok = False
            card.flash_timing_ok = True
        elif card.id in _MAIN_AND_FLASH:
            card.main_timing_ok = True
            card.flash_timing_ok = True
        else:
            card.main_timing_ok = True
            card.flash_timing_ok = False
    return card


def register_pc02r_cards(path: Path = DEFAULT_CARD_TSV) -> list[str]:
    rows = _pc02r_rows(path)
    registered_ids: list[str] = []
    for row in rows:
        card = _pc02r_card_from_row(row)
        if card.id not in CARD_REGISTRY:
            register(card)
        registered_ids.append(card.id)
    behavior_ids = set(_PC02R_EFFECTS) | set(_PC02R_AURAS) | set(_PC02R_KEYWORD_AURAS) | set(_PC02R_KEYWORDS) | _ENGINE_RULE_IDS
    missing = set(registered_ids) - behavior_ids
    extra = behavior_ids - set(registered_ids)
    if len(registered_ids) != 106 or missing or extra:
        raise RuntimeError(
            f"PC02R inventory/behavior mismatch: rows={len(registered_ids)} missing={sorted(missing)} extra={sorted(extra)}"
        )
    return registered_ids


PC02R_CARD_IDS = register_pc02r_cards()
