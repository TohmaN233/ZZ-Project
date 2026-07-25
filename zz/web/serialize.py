from __future__ import annotations

from typing import Any

from zz.engine import LIFE_CAP
from zz.enums import Color
from zz.model import CardInstance, ForceInstance, Player
from zz.web.assets import AssetIndex
from zz.web.localization import card_translation, force_translation


def _area_value(obj) -> str:
    return getattr(obj, "value", str(obj))


def _keyword_names(engine, ci: CardInstance) -> list[str]:
    effective_keywords = getattr(engine, "effective_keywords", None)
    if effective_keywords is None:
        return [kw.name for kw in ci.keywords]
    return [kw.name for kw in effective_keywords(ci)]


def _cost_dict(ci: CardInstance) -> dict[str, int]:
    return {color.name: amount for color, amount in ci.card.cost.items()}


def _first(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _current_mana_color(engine, ci: CardInstance) -> str:
    mana_color_of = getattr(engine, "_mana_color_of", None)
    if mana_color_of is not None:
        return mana_color_of(ci).name
    if ci.mana_color_override is not None:
        return ci.mana_color_override.name
    if ci.card.mana_color is not None:
        return ci.card.mana_color.name
    for color in ci.card.cost:
        if color is not Color.COLORLESS:
            return color.name
    return Color.COLORLESS.name


def serialize_card(engine, ci: CardInstance, asset_index: AssetIndex,
                   face_down: bool = False) -> dict[str, Any]:
    if face_down:
        return {
            "iid": ci.iid,
            "ownerSide": ci.owner.side.name,
            "faceDown": True,
            "assetId": "card_back",
            "assetUrl": asset_index.asset_url("card_back"),
            "area": _area_value(ci.area),
            "rested": ci.rested,
        }
    asset_id = ci.card.id
    translation = card_translation(asset_id)
    effective_bp = engine.effective_bp(ci)
    effective_dp = engine.effective_dp(ci)
    active_effects = getattr(engine, "card_active_effects", lambda card: [])(ci)
    return {
        "iid": ci.iid,
        "cardId": ci.card.id,
        "ownerSide": ci.owner.side.name,
        "nameJp": ci.card.name_jp,
        "nameEn": ci.card.name_en,
        "nameZh": _first(translation.get("name_zh")),
        "abilityJp": ci.card.ability_jp,
        "abilityEn": ci.card.ability_en,
        "abilityZh": _first(translation.get("ability_zh")),
        "type": ci.card.type.value,
        "cost": _cost_dict(ci),
        "manaColor": _current_mana_color(engine, ci),
        "bp": ci.card.bp,
        "dp": ci.card.dp,
        "effectiveBp": effective_bp,
        "effectiveDp": effective_dp,
        "bpModifier": effective_bp - ci.card.bp,
        "dpModifier": effective_dp - ci.card.dp,
        "turnBpModifier": ci.bp_mod,
        "turnDpModifier": ci.dp_mod,
        "permanentBpModifier": ci.permanent_bp_mod,
        "permanentDpModifier": ci.permanent_dp_mod,
        "activeEffects": active_effects,
        "rested": ci.rested,
        "area": _area_value(ci.area),
        "keywords": _keyword_names(engine, ci),
        "faceDown": False,
        "assetId": asset_id,
        "assetUrl": asset_index.asset_url(asset_id),
        "assetUrlEn": asset_index.asset_url_en(asset_id),
    }


def serialize_force(engine, fi: ForceInstance, asset_index: AssetIndex) -> dict[str, Any]:
    translation = force_translation(fi.force.id)
    return {
        "id": fi.force.id,
        "ownerSide": fi.owner.side.name,
        "nameJp": fi.force.name_jp,
        "nameZh": _first(translation.get("name_zh")),
        "nameEn": _first(translation.get("name_en")),
        "abilityJp": getattr(fi.force, "ability_jp", ""),
        "abilityEn": getattr(fi.force, "ability_en", ""),
        "abilityZh": _first(translation.get("ability_zh")),
        "life": fi.life,
        "initialLife": fi.force.initial_life,
        "maxLife": LIFE_CAP,
        "destroyed": fi.destroyed,
        "rested": fi.rested,
        "assetId": fi.force.id,
        "assetUrl": asset_index.asset_url(fi.force.id),
        "activeEffects": getattr(engine, "force_active_effects", lambda force: [])(fi),
    }


def _base_summary(engine, player: Player) -> dict[str, Any]:
    colors: dict[str, int] = {}
    ready = 0
    for ci in player.base:
        color = engine._mana_color_of(ci).name
        colors[color] = colors.get(color, 0) + 1
        if not ci.rested:
            ready += 1
    return {
        "total": len(player.base),
        "ready": ready,
        "colors": colors,
    }


def _deck_visual_tier(count: int) -> str:
    if count <= 0:
        return "empty"
    if count <= 10:
        return "low"
    if count <= 30:
        return "mid"
    return "many"


def serialize_player(engine, player: Player, asset_index: AssetIndex,
                     hide_hand: bool) -> dict[str, Any]:
    active_effects = getattr(engine, "player_active_effects", lambda item: [])(player)
    return {
        "name": player.name,
        "side": player.side.name,
        "isFirstPlayer": player.is_first_player,
        "profile": getattr(player, "profile", {
            "codemanId": None,
            "codeman": None,
            "playmatId": None,
            "playmatUrl": None,
        }),
        "life": player.life,
        "maxLife": LIFE_CAP,
        "deckCount": len(player.deck),
        "deckVisualTier": _deck_visual_tier(len(player.deck)),
        "handCount": len(player.hand),
        "trashCount": len(player.trash),
        "removedCount": len(player.removed),
        "movementRightCount": player.movement_right_count,
        "movementRightTotal": max(player.movement_right_total, player.movement_right_count),
        "colorlessOnlyStreak": player.colorless_only_streak,
        "activeEffects": active_effects,
        "hand": [
            serialize_card(engine, ci, asset_index, face_down=hide_hand)
            for ci in player.hand
        ],
        "field": [
            serialize_card(engine, ci, asset_index)
            for ci in player.field
        ],
        "base": [
            serialize_card(engine, ci, asset_index)
            for ci in player.base
        ],
        "trash": [
            serialize_card(engine, ci, asset_index)
            for ci in player.trash
        ],
        "baseSummary": _base_summary(engine, player),
        "forces": [serialize_force(engine, fi, asset_index) for fi in player.forces],
    }


def serialize_state(engine, human: Player | None, asset_index: AssetIndex,
                    prompt: dict | None, log: list[str] | None = None,
                    log_events: list[dict[str, Any]] | None = None,
                    mode: str = "human-vs-ai",
                    error: dict | None = None,
                    game_over: dict | None = None,
                    reveal_all_hands: bool = False,
                    animation_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    players = engine.state.players
    if human is None:
        bottom = players[0]
        top = players[1]
        hide_top_hand = False
    else:
        bottom = human
        top = players[1 - players.index(human)]
        hide_top_hand = not reveal_all_hands
    return {
        "mode": mode,
        "turn": engine.state.turn,
        "phase": engine.state.phase.value,
        "step": engine.state.step.value,
        "activeSide": engine.state.active.side.name,
        "humanSide": None if human is None else human.side.name,
        "gameOver": game_over,
        "error": error,
        "prompt": prompt,
        "log": list(log or []),
        "logEvents": list(log_events or []),
        "animationEvents": list(animation_events or []),
        "players": {
            "human": serialize_player(engine, bottom, asset_index, hide_hand=False),
            "opponent": serialize_player(engine, top, asset_index, hide_hand=hide_top_hand),
        },
    }
