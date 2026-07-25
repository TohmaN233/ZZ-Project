from __future__ import annotations

import re
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.decks import is_user_deck_card_id, validate_forces
from zz.engine import BASE_CAP, LIFE_CAP
from zz.enums import AreaType, CardType, Color, Phase, Side, Step
from zz.forces import ALL_FORCES
from zz.model import Card, CardInstance, ForceInstance


DEBUG_MODE = "debug-card-lab"
DEBUG_ZONES = {
    "deck": AreaType.DECK,
    "hand": AreaType.HAND,
    "base": AreaType.BASE,
    "field": AreaType.FIELD,
    "trash": AreaType.TRASH,
    "removed": AreaType.REMOVED,
}

_COOPERATION_COLOR_BY_LABEL = {
    "赤": Color.RED,
    "黄": Color.YELLOW,
    "白": Color.WHITE,
    "緑": Color.GREEN,
    "青": Color.BLUE,
    "紫": Color.PURPLE,
    "無": Color.COLORLESS,
    "無色": Color.COLORLESS,
}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _total_cost(card: Card) -> int:
    return sum(card.cost.values())


def _debug_card_row(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "cardId": card["id"],
        "nameJp": card.get("nameJp", ""),
        "nameEn": card.get("nameEn", ""),
        "type": card.get("type", ""),
        "cardTypeJp": card.get("cardTypeJp", ""),
        "packJp": card.get("packJp", ""),
        "attributeJp": card.get("attributeJp", ""),
        "totalCost": card.get("totalCost", 0),
        "officialCost": card.get("officialCost", ""),
        "bp": card.get("bp"),
        "dp": card.get("dp"),
        "keywords": list(card.get("keywords") or []),
        "effectTagsJp": list(card.get("effectTagsJp") or []),
        "effectTimingJp": list(card.get("effectTimingJp") or []),
        "conditionTagsJp": list(card.get("conditionTagsJp") or []),
        "effectSpecs": list(card.get("effectSpecs") or []),
        "abilityJp": card.get("abilityJp", ""),
        "abilityEn": card.get("abilityEn", ""),
        "assetUrl": card.get("assetUrl", ""),
    }


def _matches_filter(card: dict[str, Any], filters: dict[str, str]) -> bool:
    q = _norm(filters.get("q"))
    if q:
        haystack = " ".join(
            str(value or "")
            for value in [
                card.get("id"),
                card.get("nameJp"),
                card.get("nameEn"),
                card.get("abilityJp"),
                card.get("abilityEn"),
                card.get("packJp"),
                card.get("attributeJp"),
            ]
        ).lower()
        if q not in haystack:
            return False
    pack = _norm(filters.get("pack"))
    if pack and pack not in _norm(card.get("packJp")):
        return False
    color = _norm(filters.get("color"))
    if color and color not in _norm(" ".join([
        str(card.get("attributeJp") or ""),
        str(card.get("attribute") or ""),
        str(card.get("manaColor") or ""),
    ])):
        return False
    card_type = _norm(filters.get("type"))
    if card_type and card_type not in {_norm(card.get("type")), _norm(card.get("cardTypeJp"))}:
        return False
    cost = _norm(filters.get("cost"))
    if cost and cost not in {_norm(card.get("totalCost")), _norm(card.get("officialCost"))}:
        return False
    keyword = _norm(filters.get("keyword"))
    if keyword and keyword not in _norm(" ".join(
        list(card.get("keywords") or []) + list(card.get("effectTagsJp") or [])
    )):
        return False
    timing = _norm(filters.get("timing"))
    if timing:
        timing_values = list(card.get("effectTimingJp") or [])
        timing_values.extend(str(spec.get("timing") or "") for spec in card.get("effectSpecs") or [])
        timing_values.extend(str(spec.get("officialTiming") or "") for spec in card.get("effectSpecs") or [])
        if timing not in _norm(" ".join(timing_values)):
            return False
    return True


def build_debug_queue(catalog_cards: list[dict[str, Any]], filters: dict[str, str] | None = None) -> dict[str, Any]:
    filters = {key: str(value) for key, value in (filters or {}).items() if value not in (None, "")}
    queue = [
        _debug_card_row(card)
        for card in catalog_cards
        if _matches_filter(card, filters)
    ]
    return {
        "mode": DEBUG_MODE,
        "queue": queue,
        "filters": filters,
        "index": 0,
        "total": len(queue),
    }


def _area_can_be_rested(area: AreaType) -> bool:
    return area in (AreaType.FIELD, AreaType.BASE)


def _new_instance(card_id: str, owner, area: AreaType, *, rested: bool = False) -> CardInstance:
    ci = CardInstance(
        card=CARD_REGISTRY[card_id],
        owner=owner,
        area=area,
        rested=rested and _area_can_be_rested(area),
    )
    ci.summoning_sickness = False
    return ci


def _base_card_for_color(color: Color) -> str:
    candidates = [
        card for card in CARD_REGISTRY.values()
        if is_user_deck_card_id(card.id)
        and card.type is CardType.B_MINION
        and card.mana_color is color
    ]
    if candidates:
        return sorted(candidates, key=lambda card: card.id)[0].id
    fallback = [
        card for card in CARD_REGISTRY.values()
        if is_user_deck_card_id(card.id) and card.type is CardType.B_MINION
    ]
    return sorted(fallback, key=lambda card: card.id)[0].id


def _field_card_for_cost(cost: int) -> str:
    candidates = [
        card for card in CARD_REGISTRY.values()
        if is_user_deck_card_id(card.id)
        and card.type is CardType.F_MINION
        and _total_cost(card) == cost
    ]
    if not candidates:
        raise ValueError(f"no field minion with cost {cost}")
    return sorted(candidates, key=lambda card: card.id)[0].id


def _first_card(card_type: CardType, *, exclude: str | None = None) -> str:
    candidates = [
        card for card in CARD_REGISTRY.values()
        if is_user_deck_card_id(card.id)
        and card.type is card_type
        and card.id != exclude
    ]
    if not candidates:
        raise ValueError(f"no card for {card_type.value}")
    return sorted(candidates, key=lambda card: (_total_cost(card), card.id))[0].id


def _mana_token(owner, area: AreaType = AreaType.BASE) -> CardInstance:
    token_card = Card(
        id="mana_token",
        name_jp="無色マナ",
        name_en="Colorless Mana",
        type=CardType.MANA_TOKEN,
        mana_color=Color.COLORLESS,
    )
    ci = CardInstance(card=token_card, owner=owner, area=area)
    ci.summoning_sickness = False
    return ci


def _debug_mana_color_of(ci: CardInstance) -> Color:
    if ci.mana_color_override is not None:
        return ci.mana_color_override
    if ci.card.type is CardType.MANA_TOKEN:
        return Color.COLORLESS
    if ci.card.mana_color is not None:
        return ci.card.mana_color
    for color in ci.card.cost:
        if color is not Color.COLORLESS:
            return color
    return Color.COLORLESS


def _cooperation_colors(card: Card) -> list[Color]:
    colors: list[Color] = []
    for match in re.finditer(r"[［\[]\s*連携\s*[：:]\s*([^］\]\s]+)\s*[］\]]", card.ability_jp or ""):
        color = _COOPERATION_COLOR_BY_LABEL.get(match.group(1).strip())
        if color is not None and color not in colors:
            colors.append(color)
    return colors


def _mark_debug_cooperation_ready(player, card: Card) -> None:
    base_colors = {_debug_mana_color_of(ci) for ci in player.base}
    for color in _cooperation_colors(card):
        if color in base_colors:
            player.flags.add(f"turn:placed_mana:{color.name}")


def _player_for_side(session, side: str):
    target_side = Side[str(side or "").upper()]
    return next(player for player in session.engine.state.players if player.side is target_side)


def _area_for_zone(zone: str) -> AreaType:
    try:
        return DEBUG_ZONES[str(zone or "").strip().lower()]
    except KeyError as exc:
        raise ValueError(f"unknown debug zone: {zone}") from exc


def _zone_for_area(player, area: AreaType) -> list[CardInstance]:
    if area is AreaType.DECK:
        return player.deck
    if area is AreaType.HAND:
        return player.hand
    if area is AreaType.BASE:
        return player.base
    if area is AreaType.FIELD:
        return player.field
    if area is AreaType.TRASH:
        return player.trash
    if area is AreaType.REMOVED:
        return player.removed
    raise ValueError(f"unsupported debug area: {area.value}")


def _remove_from_all_zones(ci: CardInstance) -> None:
    owner = ci.owner
    for zone in (owner.deck, owner.hand, owner.base, owner.field, owner.trash, owner.removed):
        if ci in zone:
            zone.remove(ci)


def _validate_card_area(ci: CardInstance, area: AreaType) -> None:
    if area in (AreaType.FIELD, AreaType.BASE) and ci.card.type not in (
        CardType.F_MINION,
        CardType.B_MINION,
        CardType.MANA_TOKEN,
    ):
        raise ValueError(f"{ci.card.name_jp} cannot be placed in {area.value}")


def _debug_refresh_session(session) -> None:
    session._refresh_visual_snapshot()
    if session._attack is None and session._pending_effect is None:
        session._clear_prompt()
        session._prompt_main_action()


def _find_card_instance(session, iid: int) -> CardInstance:
    for player in session.engine.state.players:
        for zone in (player.deck, player.hand, player.base, player.field, player.trash, player.removed):
            for ci in zone:
                if ci.iid == iid:
                    return ci
    raise ValueError(f"unknown card iid: {iid}")


def add_debug_card_to_zone(
    session,
    card_id: str,
    *,
    side: str,
    zone: str,
    rested: bool = False,
) -> dict[str, Any]:
    player = _player_for_side(session, side)
    area = _area_for_zone(zone)
    if card_id == "mana_token":
        ci = _mana_token(player, area)
    else:
        if card_id not in CARD_REGISTRY or not is_user_deck_card_id(card_id):
            raise ValueError(f"unknown debug card id: {card_id}")
        ci = _new_instance(card_id, player, area, rested=rested)
    _validate_card_area(ci, area)
    ci.rested = bool(rested) and _area_can_be_rested(area)
    ci.area = area
    _zone_for_area(player, area).append(ci)
    if area is AreaType.FIELD:
        ci.summoning_sickness = False
    _mark_debug_cooperation_ready(player, ci.card)
    _debug_refresh_session(session)
    return {
        "added": {
            "iid": ci.iid,
            "cardId": ci.card.id,
            "side": player.side.name,
            "zone": area.value,
            "rested": ci.rested,
        }
    }


def move_debug_card(session, iid: int, *, zone: str, rested: bool | None = None) -> dict[str, Any]:
    ci = _find_card_instance(session, int(iid))
    area = _area_for_zone(zone)
    _validate_card_area(ci, area)
    _remove_from_all_zones(ci)
    ci.area = area
    if rested is not None:
        ci.rested = bool(rested) and _area_can_be_rested(area)
    elif not _area_can_be_rested(area):
        ci.rested = False
    if area is AreaType.FIELD:
        ci.summoning_sickness = False
    _zone_for_area(ci.owner, area).append(ci)
    _mark_debug_cooperation_ready(ci.owner, ci.card)
    _debug_refresh_session(session)
    return {
        "moved": {
            "iid": ci.iid,
            "cardId": ci.card.id,
            "side": ci.owner.side.name,
            "zone": area.value,
            "rested": ci.rested,
        }
    }


def set_debug_card_state(session, iid: int, *, rested: bool | None = None) -> dict[str, Any]:
    ci = _find_card_instance(session, int(iid))
    if rested is not None:
        ci.rested = bool(rested) and _area_can_be_rested(ci.area)
    _debug_refresh_session(session)
    return {
        "card": {
            "iid": ci.iid,
            "cardId": ci.card.id,
            "side": ci.owner.side.name,
            "zone": ci.area.value,
            "rested": ci.rested,
        }
    }


def set_debug_control(session, control_both: bool) -> dict[str, Any]:
    session.debug_control_both = bool(control_both)
    session._clear_prompt()
    session._prompt_main_action()
    return {"controlBoth": session.debug_control_both}


def set_debug_life(session, *, side: str, life: int, force_index: int | None = None) -> dict[str, Any]:
    player = _player_for_side(session, side)
    value = max(0, min(LIFE_CAP, int(life)))
    if force_index is None:
        player.life = value
        target = {"side": player.side.name, "life": player.life}
    else:
        fi = player.forces[int(force_index)]
        fi.life = value
        target = {"side": player.side.name, "forceIndex": int(force_index), "life": fi.life}
    _debug_refresh_session(session)
    return {"life": target}


def setup_debug_fixed_board(
    session,
    *,
    active_side: str = "P1",
    control_both: bool = True,
) -> dict[str, Any]:
    state = session.engine.state
    active_player = _player_for_side(session, active_side)
    state.active_idx = state.players.index(active_player)
    state.turn = max(2, state.turn)
    state.phase = Phase.MAIN
    state.step = Step.MAIN
    state.summoned_this_turn.clear()
    session.debug_control_both = bool(control_both)
    session._attack = None
    session._pending_effect = None
    session._game_over = None
    session.prompt = None
    session._options = {}

    base_colors = [Color.RED, Color.YELLOW, Color.WHITE, Color.GREEN, Color.BLUE, Color.PURPLE]
    for player in state.players:
        player.field.clear()
        player.base.clear()
        player.mulligan_done = True
        player.movement_right_count = 1
        player.movement_right_total = 1
        player.colorless_only_streak = 0
        player.flags.clear()
        player.base.extend(_new_instance(_base_card_for_color(color), player, AreaType.BASE) for color in base_colors)
        player.base.extend(_mana_token(player) for _ in range(BASE_CAP - len(player.base)))

    opponent = state.players[1 - state.players.index(active_player)]
    opponent_costs = [1, 3, 5, 7, 9]
    opponent.field = [_new_instance(_field_card_for_cost(cost), opponent, AreaType.FIELD) for cost in opponent_costs]
    state.present_at_turn_start = {
        ci.iid
        for player in state.players
        for ci in player.field + player.base
    }
    _debug_refresh_session(session)
    return {
        "fixture": {
            "activeSide": active_player.side.name,
            "opponentSide": opponent.side.name,
            "opponentFieldCosts": opponent_costs,
            "playerBaseCount": len(active_player.base),
            "opponentBaseCount": len(opponent.base),
        },
        "controlBoth": session.debug_control_both,
    }


def _payable_base_ids(selected: Card, owner) -> list[str]:
    ids: list[str] = []
    for color, amount in selected.cost.items():
        if color is Color.COLORLESS:
            continue
        ids.extend([_base_card_for_color(color)] * amount)
    while len(ids) < BASE_CAP:
        ids.append(_base_card_for_color(selected.mana_color or Color.COLORLESS))
    return ids[:BASE_CAP]


def _install_forces_fresh(session, player, force_ids: list[str]) -> None:
    validate_forces(force_ids)
    old_force_iids = {id(fi) for fi in player.forces}
    player.forces = [
        ForceInstance(force=ALL_FORCES[force_id], owner=player, life=ALL_FORCES[force_id].initial_life)
        for force_id in force_ids
    ]
    engine = session.engine
    engine._passive_modifiers = [
        (kind, fn)
        for kind, fn in engine._passive_modifiers
        if getattr(fn, "_force_iid", None) not in old_force_iids
    ]
    for fi in player.forces:
        if fi.force.passive is not None:
            fi.force.passive(fi, engine)


def setup_debug_lab(
    session,
    card_id: str,
    *,
    zone: str = "hand",
    player_forces: list[str] | None = None,
    opponent_forces: list[str] | None = None,
) -> dict[str, Any]:
    if card_id not in CARD_REGISTRY or not is_user_deck_card_id(card_id):
        raise ValueError(f"unknown debug card id: {card_id}")
    selected = CARD_REGISTRY[card_id]
    state = session.engine.state
    p1, p2 = state.players
    state.turn = 2
    state.active_idx = 0
    state.phase = Phase.MANA if selected.type is CardType.B_MINION else Phase.MAIN
    state.step = Step.MANA if selected.type is CardType.B_MINION else Step.MAIN
    state.summoned_this_turn.clear()
    session._attack = None
    session._pending_effect = None
    session._game_over = None
    session.prompt = None
    session._options = {}
    session._log = [f"Debug lab loaded {selected.name_jp}"]
    session._public_reveals.clear()
    session._animation_events.clear()

    for player in (p1, p2):
        player.hand.clear()
        player.field.clear()
        player.base.clear()
        player.trash.clear()
        player.removed.clear()
        player.deck.clear()
        player.life = 10
        player.mulligan_done = True
        player.movement_right_count = 1
        player.movement_right_total = 1
        player.colorless_only_streak = 0
        player.flags.clear()

    test_card = _new_instance(card_id, p1, AreaType.HAND)
    if zone == "base":
        test_card.area = AreaType.BASE
        p1.base.append(test_card)
    elif zone == "field":
        test_card.area = AreaType.FIELD
        p1.field.append(test_card)
    else:
        p1.hand.append(test_card)

    p1.base.extend(_new_instance(card_id, p1, AreaType.BASE) for card_id in _payable_base_ids(selected, p1))
    _mark_debug_cooperation_ready(p1, selected)
    p1.field.extend([
        _new_instance(_first_card(CardType.F_MINION, exclude=selected.id), p1, AreaType.FIELD),
        _new_instance(_field_card_for_cost(3), p1, AreaType.FIELD),
    ])
    p1.trash.append(_new_instance(_first_card(CardType.MAGIC), p1, AreaType.TRASH))
    p1.deck.extend([
        _new_instance(_first_card(CardType.F_MINION, exclude=selected.id), p1, AreaType.DECK),
        _new_instance(_first_card(CardType.B_MINION), p1, AreaType.DECK),
    ])

    opponent_costs = [1, 3, 5, 7, 9]
    p2.field = [_new_instance(_field_card_for_cost(cost), p2, AreaType.FIELD) for cost in opponent_costs]
    p2.base = [
        _new_instance(_base_card_for_color(color), p2, AreaType.BASE)
        for color in [Color.RED, Color.YELLOW, Color.WHITE, Color.GREEN, Color.BLUE]
    ]
    p2.base.extend(_mana_token(p2) for _ in range(BASE_CAP - len(p2.base)))
    p2.deck.extend([
        _new_instance(_first_card(CardType.F_MINION), p2, AreaType.DECK),
        _new_instance(_first_card(CardType.B_MINION), p2, AreaType.DECK),
    ])

    _install_forces_fresh(session, p1, player_forces or ["force_e", "force_so2"])
    _install_forces_fresh(session, p2, opponent_forces or ["force_kon", "force_rin"])
    p1.life = 10
    p2.life = 10
    state.present_at_turn_start = {ci.iid for player in state.players for ci in player.field + player.base}
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    return {
        "selectedCardId": card_id,
        "playPath": "choose_prompt",
        "fixture": {
            "playerBaseCount": len(p1.base),
            "opponentFieldCosts": opponent_costs,
            "opponentBaseCount": len(p2.base),
        },
    }


def replace_debug_forces(session, side: str, force_ids: list[str]) -> dict[str, Any]:
    validate_forces(force_ids)
    target_side = Side[side]
    player = next(player for player in session.engine.state.players if player.side is target_side)
    _install_forces_fresh(session, player, force_ids)
    player.life = 10
    _debug_refresh_session(session)
    return {"side": side, "forceIds": list(force_ids)}
