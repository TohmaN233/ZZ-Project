from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.enums import CardType, Color, Phase, Step
from zz.forces import ALL_FORCES
from zz.model import Action, CardInstance, Player
from zz.card_slot_refs import encode_card_slot_norm
from zz.rl_action_vocab import (
    ACTION_CATEGORY_FEATURES,
    ACTION_KIND_TO_ID,
    ACTION_STATE_FEATURE_NAMES,
    CARD_PROFILE_FEATURE_NAMES,
    DECISION_KIND_TO_ID,
    PAYLOAD_FEATURE_NAMES,
    action_category_tags,
    action_state_numeric_features,
    card_profile_numeric_features,
    decision_kind_for_action,
    normalise_action_kind,
    normalise_decision_kind,
    payload_numeric_features,
)


ACTION_TENSOR_SCHEMA_VERSION = "rl_action_tensor_v1"
CARD_ID_VOCAB_VERSION = "official_card_id_vocab_v1"
DEFAULT_MAX_CARD_TOKENS = 8
FORCE_IDS: tuple[str, ...] = tuple(str(force_id) for force_id in ALL_FORCES)
OFFICIAL_CARD_ID_PREFIXES: tuple[str, ...] = (
    "blue_",
    "colorless_",
    "green_",
    "purple_",
    "red_",
    "white_",
    "yellow_",
)

GLOBAL_FEATURE_NAMES: tuple[str, ...] = (
    "global:turn_norm",
    *(f"global:phase_{phase.value}" for phase in Phase),
    *(f"global:step_{step.value}" for step in Step),
    "global:active_true_first",
    "global:active_true_second",
    "global:self_life_norm",
    "global:opponent_life_norm",
    "global:self_hand_count_norm",
    "global:self_base_count_norm",
    "global:self_field_count_norm",
    "global:self_trash_count_norm",
    "global:self_movement_right_count_norm",
    "global:self_colorless_only_streak_norm",
    "global:opponent_hand_count_norm",
    "global:opponent_base_count_norm",
    "global:opponent_field_count_norm",
    "global:opponent_trash_count_norm",
    "global:self_force_alive_count_norm",
    "global:self_force_broken_count_norm",
    "global:self_force_low_life_count_norm",
    "global:opponent_force_alive_count_norm",
    "global:opponent_force_broken_count_norm",
    "global:opponent_force_low_life_count_norm",
    *(f"global:self_force_alive:{force_id}" for force_id in FORCE_IDS),
    *(f"global:self_force_broken:{force_id}" for force_id in FORCE_IDS),
    *(f"global:self_force_rested:{force_id}" for force_id in FORCE_IDS),
    *(f"global:self_force_low_life:{force_id}" for force_id in FORCE_IDS),
    *(f"global:opponent_force_alive:{force_id}" for force_id in FORCE_IDS),
    *(f"global:opponent_force_broken:{force_id}" for force_id in FORCE_IDS),
    *(f"global:opponent_force_rested:{force_id}" for force_id in FORCE_IDS),
    *(f"global:opponent_force_low_life:{force_id}" for force_id in FORCE_IDS),
)


def _registered_official_card_ids() -> tuple[str, ...]:
    try:
        import zz.decks  # noqa: F401 - populate official card registry
    except Exception as exc:
        raise RuntimeError("failed to import zz.decks while building official card-id vocabulary") from exc
    card_ids = tuple(
        sorted(
            card_id
            for card_id, card in CARD_REGISTRY.items()
            if _is_official_trainable_card_id(card_id, card)
        )
    )
    if not card_ids:
        raise RuntimeError("official trainable card-id vocabulary is empty after importing zz.decks")
    return card_ids


def _schema_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_official_trainable_card_id(card_id: str, card: Any) -> bool:
    if not card_id.startswith(OFFICIAL_CARD_ID_PREFIXES):
        return False
    if bool(getattr(card, "is_token", False)):
        return False
    return getattr(card, "type", None) is not CardType.MANA_TOKEN


REGISTERED_OFFICIAL_CARD_IDS: tuple[str, ...] = _registered_official_card_ids()
CARD_ID_VOCAB_HASH: str = _schema_hash(
    {
        "version": CARD_ID_VOCAB_VERSION,
        "cardIds": REGISTERED_OFFICIAL_CARD_IDS,
    }
)

ACTION_CARD_FEATURE_NAMES: tuple[str, ...] = (
    "action_card:known",
    "action_card:unknown_or_token",
    *(f"action_card_id:{card_id}" for card_id in REGISTERED_OFFICIAL_CARD_IDS),
)

ACTION_FEATURE_NAMES: tuple[str, ...] = (
    *(f"action_kind:{kind}" for kind in ACTION_KIND_TO_ID),
    *(f"decision:{kind}" for kind in DECISION_KIND_TO_ID),
    *ACTION_CATEGORY_FEATURES,
    *PAYLOAD_FEATURE_NAMES,
    *ACTION_STATE_FEATURE_NAMES,
    *CARD_PROFILE_FEATURE_NAMES,
    *ACTION_CARD_FEATURE_NAMES,
    "action_ref:source_card_slot_norm",
    "action_ref:target_card_slot_norm",
)

HISTORY_FEATURE_NAMES: tuple[str, ...] = (
    "history:replay_decision_index_norm",
    "history:recent_action_count_norm",
    *(f"history:previous_action_kind:{kind}" for kind in ACTION_KIND_TO_ID),
    *(f"history:previous_decision:{kind}" for kind in DECISION_KIND_TO_ID),
    *(f"history:recent_decision:{kind}_count_norm" for kind in DECISION_KIND_TO_ID),
)


CARD_ID_FEATURE_NAMES: tuple[str, ...] = tuple(
    f"card_id:{card_id}"
    for card_id in REGISTERED_OFFICIAL_CARD_IDS
)

CARD_FEATURE_NAMES: tuple[str, ...] = (
    "card:present",
    "card:owner_self",
    "card:owner_opponent",
    "card:zone_hand",
    "card:zone_base",
    "card:zone_field",
    "card:zone_trash",
    "card:rested",
    "card:summoning_sickness",
    "card:cost_norm",
    "card:bp_norm",
    "card:dp_norm",
    *(f"card:color_{color.name.lower()}" for color in Color),
    *(f"card:type_{card_type.value}" for card_type in CardType),
    *CARD_ID_FEATURE_NAMES,
    *CARD_PROFILE_FEATURE_NAMES,
)

ACTION_SET_TENSOR_SCHEMA_FINGERPRINT: str = _schema_hash(
    {
        "schemaVersion": ACTION_TENSOR_SCHEMA_VERSION,
        "cardIdVocabVersion": CARD_ID_VOCAB_VERSION,
        "cardIdVocabHash": CARD_ID_VOCAB_HASH,
        "globalFeatureNames": GLOBAL_FEATURE_NAMES,
        "historyFeatureNames": HISTORY_FEATURE_NAMES,
        "actionFeatureNames": ACTION_FEATURE_NAMES,
        "cardFeatureNames": CARD_FEATURE_NAMES,
    }
)


@dataclass(frozen=True)
class ActionSetTensor:
    schemaVersion: str
    schemaFingerprint: str
    cardIdVocabVersion: str
    cardIdVocabHash: str
    cards_: tuple[tuple[float, ...], ...]
    cardFeatureNames: tuple[str, ...]
    history_: tuple[float, ...]
    historyFeatureNames: tuple[str, ...]
    global_: tuple[float, ...]
    globalFeatureNames: tuple[str, ...]
    actions_: tuple[tuple[float, ...], ...]
    actionFeatureNames: tuple[str, ...]
    mask_: tuple[int, ...]
    card_refs: tuple[CardInstance | None, ...]
    action_refs: tuple[Action | None, ...]
    decisionKind: str


def encode_action_set(
    engine: Any,
    player: Player,
    actions: list[Action] | tuple[Action, ...],
    *,
    max_actions: int,
    max_cards: int = DEFAULT_MAX_CARD_TOKENS,
    decision_kind: str | None = None,
    history_context: Any | None = None,
) -> ActionSetTensor:
    if max_actions <= 0:
        raise ValueError("max_actions must be positive")
    if max_cards <= 0:
        raise ValueError("max_cards must be positive")

    action_list = list(actions)
    state = getattr(engine, "state", None)
    decision_kind_value = _resolve_decision_kind(state, action_list, decision_kind)
    global_map = _global_feature_map(state, player)
    history_map = dict(zip(HISTORY_FEATURE_NAMES, history_feature_row(history_context), strict=False))
    card_refs, card_slot_by_iid, card_id_by_iid = _card_tokens_for_state(
        state,
        player,
        max_cards=max_cards,
        actions=action_list,
    )
    card_rows = tuple(_card_feature_row(card, player) for card in card_refs)
    rows: list[tuple[float, ...]] = []
    refs: list[Action | None] = []
    mask: list[int] = []

    for idx in range(max_actions):
        if idx < len(action_list):
            action = action_list[idx]
            action_map = _action_feature_map(
                action,
                context_decision_kind=decision_kind_value,
                global_features=global_map,
                action_set_actions=action_list,
                player=player,
                card_slot_by_iid=card_slot_by_iid,
                card_id_by_iid=card_id_by_iid,
                max_cards=max_cards,
            )
            rows.append(tuple(action_map[name] for name in ACTION_FEATURE_NAMES))
            refs.append(action)
            mask.append(1)
        else:
            rows.append(tuple(0.0 for _ in ACTION_FEATURE_NAMES))
            refs.append(None)
            mask.append(0)

    return ActionSetTensor(
        schemaVersion=ACTION_TENSOR_SCHEMA_VERSION,
        schemaFingerprint=ACTION_SET_TENSOR_SCHEMA_FINGERPRINT,
        cardIdVocabVersion=CARD_ID_VOCAB_VERSION,
        cardIdVocabHash=CARD_ID_VOCAB_HASH,
        cards_=card_rows,
        cardFeatureNames=CARD_FEATURE_NAMES,
        history_=tuple(history_map[name] for name in HISTORY_FEATURE_NAMES),
        historyFeatureNames=HISTORY_FEATURE_NAMES,
        global_=tuple(global_map[name] for name in GLOBAL_FEATURE_NAMES),
        globalFeatureNames=GLOBAL_FEATURE_NAMES,
        actions_=tuple(rows),
        actionFeatureNames=ACTION_FEATURE_NAMES,
        mask_=tuple(mask),
        card_refs=tuple(card_refs),
        action_refs=tuple(refs),
        decisionKind=decision_kind_value,
    )


def _global_feature_map(state: Any, player: Player) -> dict[str, float]:
    features = {name: 0.0 for name in GLOBAL_FEATURE_NAMES}
    phase = getattr(state, "phase", None)
    step = getattr(state, "step", None)
    opponent = _opponent_for(state, player)

    features["global:turn_norm"] = _norm(getattr(state, "turn", 0), 20.0)
    phase_value = getattr(phase, "value", str(phase).lower() if phase is not None else "")
    step_value = getattr(step, "value", str(step).lower() if step is not None else "")
    if f"global:phase_{phase_value}" in features:
        features[f"global:phase_{phase_value}"] = 1.0
    if f"global:step_{step_value}" in features:
        features[f"global:step_{step_value}"] = 1.0

    is_first = bool(getattr(player, "is_first_player", False))
    features["global:active_true_first"] = 1.0 if is_first else 0.0
    features["global:active_true_second"] = 0.0 if is_first else 1.0

    _add_player_counts(features, "self", player)
    _add_player_counts(features, "opponent", opponent)
    _add_force_counts(features, "self", player)
    _add_force_counts(features, "opponent", opponent)
    return features


def _action_feature_map(
    action: Action,
    *,
    context_decision_kind: str | None = None,
    global_features: dict[str, float] | None = None,
    action_set_actions: list[Action] | tuple[Action, ...] | None = None,
    player: Player | None = None,
    card_slot_by_iid: dict[int, int] | None = None,
    card_id_by_iid: dict[int, str] | None = None,
    max_cards: int = DEFAULT_MAX_CARD_TOKENS,
) -> dict[str, float]:
    features = {name: 0.0 for name in ACTION_FEATURE_NAMES}
    kind = normalise_action_kind(action)
    features[f"action_kind:{kind}"] = 1.0
    decision_kind = decision_kind_for_action(action, context_decision_kind=context_decision_kind)
    features[f"decision:{decision_kind}"] = 1.0

    for tag in action_category_tags(action):
        if tag in features:
            features[tag] = 1.0

    for name, value in payload_numeric_features(action).items():
        if name in features:
            features[name] = float(value)
    for name, value in action_state_numeric_features(
        action,
        global_features=global_features,
        action_set_actions=action_set_actions,
    ).items():
        if name in features:
            features[name] = float(value)
    for name, value in _tensor_state_action_features(action, player=player, global_features=global_features).items():
        if name in features:
            features[name] = float(value)
    for name, value in card_profile_numeric_features(action).items():
        if name in features:
            features[name] = float(value)
    for name, value in _action_card_identity_features(action, card_id_by_iid or {}).items():
        if name in features:
            features[name] = float(value)
    features.update(_action_card_ref_features(action, card_slot_by_iid or {}, max_cards=max_cards))

    return features


def _tensor_state_action_features(
    action: Action,
    *,
    player: Player | None,
    global_features: dict[str, float] | None = None,
) -> dict[str, float]:
    features: dict[str, float] = {}
    kind = normalise_action_kind(action)
    base_count = _safe_len(getattr(player, "base", [])) if player is not None else 0
    under_base_cap = base_count < 10
    if kind == "skip_mana":
        features["state_action:skip_mana_under_base_cap"] = 1.0 if under_base_cap else 0.0
        return features
    if kind != "place_colorless_mana":
        return features

    features["state_action:place_colorless_under_base_cap"] = 1.0 if under_base_cap else 0.0
    if float((global_features or {}).get("global:self_colorless_only_streak_norm", 0.0) or 0.0) > 0.0:
        features["state_action:place_colorless_after_colorless_streak"] = 1.0
    if player is None:
        return features

    hand_demand = _colored_hand_cost_demand(player)
    if hand_demand:
        features["state_action:place_colorless_with_colored_hand_demand"] = 1.0
    ready_base_colors = _ready_base_color_counts(player)
    missing_color = any(int(amount) > int(ready_base_colors.get(color, 0)) for color, amount in hand_demand.items())
    if missing_color:
        features["state_action:place_colorless_ignores_missing_colored_hand"] = 1.0
    return features


def _history_feature_map(history_context: Any | None) -> dict[str, float]:
    features = {name: 0.0 for name in HISTORY_FEATURE_NAMES}
    if not isinstance(history_context, dict):
        return features

    cursor = history_context.get("replayCursor")
    if isinstance(cursor, dict):
        decision_index = cursor.get("actionSetDecisionIndex", cursor.get("decisionIndex"))
    else:
        decision_index = history_context.get("actionSetDecisionIndex", history_context.get("decisionIndex"))
    features["history:replay_decision_index_norm"] = _norm(decision_index, 64.0)

    recent_actions = _history_recent_actions(history_context)
    features["history:recent_action_count_norm"] = _norm(len(recent_actions), 8.0)
    if not recent_actions:
        return features

    previous = recent_actions[-1]
    previous_kind = normalise_action_kind(previous.get("kind") if isinstance(previous, dict) else previous)
    previous_decision = normalise_decision_kind(
        str(previous.get("decisionKind")) if isinstance(previous, dict) and previous.get("decisionKind") is not None else None
    )
    features[f"history:previous_action_kind:{previous_kind}"] = 1.0
    features[f"history:previous_decision:{previous_decision}"] = 1.0

    decision_counts: dict[str, int] = {}
    for item in recent_actions[-8:]:
        decision = normalise_decision_kind(
            str(item.get("decisionKind")) if isinstance(item, dict) and item.get("decisionKind") is not None else None
        )
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
    for decision, count in decision_counts.items():
        feature_name = f"history:recent_decision:{decision}_count_norm"
        if feature_name in features:
            features[feature_name] = _norm(count, 8.0)
    return features


def history_feature_row(history_context: Any | None) -> tuple[float, ...]:
    features = _history_feature_map(history_context)
    return tuple(features[name] for name in HISTORY_FEATURE_NAMES)


def _history_recent_actions(history_context: dict[str, Any]) -> list[Any]:
    for key in ("recentActions", "recentActionHistory", "actionHistory"):
        value = history_context.get(key)
        if isinstance(value, list | tuple):
            return list(value)
    previous = history_context.get("previousAction")
    if previous is not None:
        return [previous]
    return []


def _card_tokens_for_state(
    state: Any,
    player: Player,
    *,
    max_cards: int,
    actions: list[Action] | tuple[Action, ...] | None = None,
) -> tuple[list[CardInstance | None], dict[int, int], dict[int, str]]:
    opponent = _opponent_for(state, player)
    ordered: list[CardInstance] = []
    for owner in (player, opponent):
        for zone_name in ("hand", "base", "field", "trash"):
            for card in getattr(owner, zone_name, []) or []:
                if isinstance(card, CardInstance):
                    ordered.append(card)
    by_iid = {int(card.iid): card for card in ordered}
    synthetic_by_iid = _synthetic_action_card_tokens(
        actions or (),
        known_iids=set(by_iid),
        player=player,
        opponent=opponent,
    )
    by_iid.update(synthetic_by_iid)
    referenced_cards: list[CardInstance] = []
    seen_iids: set[int] = set()
    for iid in _action_referenced_iids(actions or ()):
        card = by_iid.get(iid)
        if card is None or iid in seen_iids:
            continue
        referenced_cards.append(card)
        seen_iids.add(iid)
    prioritized = referenced_cards + [
        card
        for card in ordered
        if int(card.iid) not in seen_iids
    ]
    refs: list[CardInstance | None] = list(prioritized[:max_cards])
    refs.extend([None] * (max_cards - len(refs)))
    slot_by_iid = {int(card.iid): index for index, card in enumerate(refs) if isinstance(card, CardInstance)}
    card_id_by_iid = {
        int(card.iid): str(getattr(getattr(card, "card", None), "id", "") or "")
        for card in [*ordered, *synthetic_by_iid.values()]
        if isinstance(card, CardInstance)
    }
    return refs, slot_by_iid, card_id_by_iid


def _synthetic_action_card_tokens(
    actions: list[Action] | tuple[Action, ...],
    *,
    known_iids: set[int],
    player: Player,
    opponent: Player | None,
) -> dict[int, CardInstance]:
    out: dict[int, CardInstance] = {}
    for action in actions:
        payload = getattr(action, "payload", None)
        data = payload if isinstance(payload, dict) else {}
        for iid in _action_source_target_iids(action):
            if iid is None or iid in known_iids or iid in out:
                continue
            card_id = _clean_card_id(data.get("card_id") or data.get("cardId"))
            if not card_id:
                card_id = _nested_card_id_for_iid(data, iid)
            card = CARD_REGISTRY.get(str(card_id or ""))
            if card is None:
                continue
            owner = _payload_owner_player(data.get("owner"), player=player, opponent=opponent)
            instance = CardInstance(card=card, iid=int(iid), owner=owner)
            if "rested" in data:
                instance.rested = bool(data.get("rested"))
            _apply_payload_effective_stats(instance, data)
            out[int(iid)] = instance
    return out


def _nested_card_id_for_iid(payload: dict[str, Any], iid: int) -> str | None:
    for value in payload.values():
        if not isinstance(value, dict):
            continue
        if _payload_iid(value) != int(iid):
            continue
        card_id = _clean_nested_card_id(value)
        if card_id:
            return card_id
    return None


def _payload_owner_player(owner_value: Any, *, player: Player, opponent: Player | None) -> Player:
    label = _normalise_player_label(owner_value)
    if label and _player_label_matches(player, label):
        return player
    if opponent is not None and label and _player_label_matches(opponent, label):
        return opponent
    return player


def _normalise_player_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("SIDE."):
        text = text.split(".", 1)[1]
    return text


def _player_label_matches(player: Player, label: str) -> bool:
    side = getattr(player, "side", None)
    candidates = {
        str(getattr(player, "name", "") or "").strip().upper(),
        str(getattr(side, "name", "") or "").strip().upper(),
        str(getattr(side, "value", "") or "").strip().upper(),
    }
    return str(label or "").strip().upper() in candidates


def _apply_payload_effective_stats(instance: CardInstance, payload: dict[str, Any]) -> None:
    for attr, mod_attr in (("bp", "permanent_bp_mod"), ("dp", "permanent_dp_mod")):
        if attr not in payload:
            continue
        try:
            value = int(payload.get(attr) or 0)
        except (TypeError, ValueError):
            continue
        base = int(getattr(getattr(instance, "card", None), attr, 0) or 0)
        setattr(instance, mod_attr, int(value) - base)


def _action_referenced_iids(actions: list[Action] | tuple[Action, ...]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for action in actions:
        source_iid, target_iid = _action_source_target_iids(action)
        for iid in (source_iid, target_iid):
            if iid is None or iid in seen:
                continue
            out.append(iid)
            seen.add(iid)
    return out


def _payload_iid(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("iid")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _card_feature_row(card: CardInstance | None, perspective: Player) -> tuple[float, ...]:
    features = {name: 0.0 for name in CARD_FEATURE_NAMES}
    if card is None:
        return tuple(features[name] for name in CARD_FEATURE_NAMES)

    template = getattr(card, "card", None)
    features["card:present"] = 1.0
    if getattr(card, "owner", None) is perspective:
        features["card:owner_self"] = 1.0
    else:
        features["card:owner_opponent"] = 1.0

    zone_name = _zone_name_for_card(card)
    zone_feature = f"card:zone_{zone_name}"
    if zone_feature in features:
        features[zone_feature] = 1.0
    features["card:rested"] = 1.0 if bool(getattr(card, "rested", False)) else 0.0
    features["card:summoning_sickness"] = 1.0 if bool(getattr(card, "summoning_sickness", False)) else 0.0

    features["card:cost_norm"] = _norm(sum((getattr(template, "cost", {}) or {}).values()), 10.0)
    features["card:bp_norm"] = _norm(getattr(card, "bp", getattr(template, "bp", 0)), 1000.0)
    features["card:dp_norm"] = _norm(getattr(card, "dp", getattr(template, "dp", 0)), 10.0)

    color = getattr(template, "mana_color", None) or _first_cost_color(template)
    if isinstance(color, Color):
        feature_name = f"card:color_{color.name.lower()}"
    else:
        feature_name = ""
    if feature_name in features:
        features[feature_name] = 1.0

    card_type = getattr(template, "type", None)
    type_value = getattr(card_type, "value", None)
    if isinstance(type_value, str) and f"card:type_{type_value}" in features:
        features[f"card:type_{type_value}"] = 1.0

    card_id = str(getattr(template, "id", "") or "")
    card_id_feature = f"card_id:{card_id}"
    if card_id_feature in features:
        features[card_id_feature] = 1.0

    features.update(_card_profile_features_from_card(template))
    return tuple(features[name] for name in CARD_FEATURE_NAMES)


def _zone_name_for_card(card: CardInstance) -> str:
    owner = getattr(card, "owner", None)
    for zone_name in ("hand", "base", "field", "trash"):
        if card in (getattr(owner, zone_name, []) or []):
            return zone_name
    return ""


def _first_cost_color(card: Any) -> Color | None:
    cost = getattr(card, "cost", None) or {}
    for color in cost:
        if isinstance(color, Color):
            return color
    return None


def _colored_hand_cost_demand(player: Any) -> dict[Color, int]:
    demand: dict[Color, int] = {}
    for instance in getattr(player, "hand", []) or []:
        card = getattr(instance, "card", instance)
        cost = getattr(card, "cost", None) or {}
        if not isinstance(cost, dict):
            continue
        for color, amount in cost.items():
            if not isinstance(color, Color) or color is Color.COLORLESS:
                continue
            try:
                count = int(amount)
            except (TypeError, ValueError):
                count = 0
            if count > 0:
                demand[color] = demand.get(color, 0) + count
    return demand


def _ready_base_color_counts(player: Any) -> dict[Color, int]:
    counts: dict[Color, int] = {}
    for instance in getattr(player, "base", []) or []:
        if bool(getattr(instance, "rested", False)):
            continue
        card = getattr(instance, "card", instance)
        color = getattr(card, "mana_color", None) or _first_cost_color(card)
        if not isinstance(color, Color) or color is Color.COLORLESS:
            continue
        counts[color] = counts.get(color, 0) + 1
    return counts


def _card_profile_features_from_card(card: Any) -> dict[str, float]:
    features = {name: 0.0 for name in CARD_PROFILE_FEATURE_NAMES}
    if card is None:
        return features
    try:
        from zz.card_profiles import build_card_profile, card_profile_tags
    except Exception:
        return features
    try:
        profile = build_card_profile(card)
    except Exception:
        return features
    features["card_profile:known"] = 1.0
    features["card_profile:action_references_card"] = 1.0
    identity = getattr(profile, "identity", None)
    features["card_profile:cost_norm"] = _norm(float(getattr(identity, "cost_total", 0) or 0), 10.0)
    features["card_profile:bp_norm"] = _norm(float(getattr(identity, "bp", 0) or 0), 1000.0)
    features["card_profile:dp_norm"] = _norm(float(getattr(identity, "dp", 0) or 0), 10.0)
    for tag in card_profile_tags(profile):
        feature_name = _card_profile_feature_name_from_tag(tag)
        if feature_name in features:
            features[feature_name] = 1.0
    return features


def _action_card_identity_features(action: Action, card_id_by_iid: dict[int, str]) -> dict[str, float]:
    features = {name: 0.0 for name in ACTION_CARD_FEATURE_NAMES}
    card_id = _action_referenced_card_id(action, card_id_by_iid)
    if not card_id:
        return features
    features["action_card:known"] = 1.0
    feature_name = f"action_card_id:{card_id}"
    if feature_name in features:
        features[feature_name] = 1.0
    else:
        features["action_card:unknown_or_token"] = 1.0
    return features


def _action_referenced_card_id(action: Action, card_id_by_iid: dict[int, str]) -> str | None:
    payload = getattr(action, "payload", None)
    data = payload if isinstance(payload, dict) else {}
    for field in ("card_id", "base_card_id", "source_card_id", "target_card_id"):
        card_id = _clean_card_id(data.get(field))
        if card_id:
            return card_id
    for field in ("card", "source_card", "target_card", "attacker", "blocker", "target"):
        card_id = _clean_nested_card_id(data.get(field))
        if card_id:
            return card_id
    for field in (
        "iid",
        "source_iid",
        "source_card_iid",
        "attacker_iid",
        "blocker_iid",
        "target_iid",
        "target_card_iid",
        "replace_field_iid",
        "replace_base_iid",
        "base_card_iid",
    ):
        card_id = _card_id_from_iid_payload(data.get(field), card_id_by_iid)
        if card_id:
            return card_id
    return None


def _card_id_from_iid_payload(value: Any, card_id_by_iid: dict[int, str]) -> str | None:
    nested = _clean_nested_card_id(value)
    if nested:
        return nested
    try:
        iid = int(value)
    except (TypeError, ValueError):
        return None
    return card_id_by_iid.get(iid)


def _clean_nested_card_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for field in ("cardId", "card_id", "base_card_id", "target_card_id", "source_card_id", "id"):
            card_id = _clean_card_id(value.get(field))
            if card_id:
                return card_id
    return None


def _clean_card_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text else None


def _card_profile_feature_name_from_tag(tag: str) -> str:
    parts = str(tag).split(":")
    if len(parts) == 2:
        namespace, label = parts
    elif len(parts) == 3 and parts[0] == "identity":
        namespace, label = f"{parts[0]}_{parts[1]}", parts[2]
    else:
        return ""
    return f"card_profile_{namespace}:{label}"


def _action_card_ref_features(action: Action, card_slot_by_iid: dict[int, int], *, max_cards: int) -> dict[str, float]:
    source_iid, target_iid = _action_source_target_iids(action)
    return {
        "action_ref:source_card_slot_norm": _slot_norm(card_slot_by_iid.get(source_iid), max_cards),
        "action_ref:target_card_slot_norm": _slot_norm(card_slot_by_iid.get(target_iid), max_cards),
    }


def _action_source_target_iids(action: Action) -> tuple[int | None, int | None]:
    kind = normalise_action_kind(action)
    payload = getattr(action, "payload", None)

    if kind == "choose_target":
        return (
            _first_payload_iid(payload, ("source_iid", "source_card_iid", "source")),
            _first_payload_iid(payload, ("target_iid", "target_card_iid", "target", "iid")),
        )
    if kind == "choose_attack_target":
        return (
            _first_payload_iid(payload, ("attacker_iid", "attacker", "source_iid", "source_card_iid", "source")),
            _first_payload_iid(payload, ("target_iid", "target_card_iid", "target", "iid")),
        )
    if kind in {"choose_blocker", "block"}:
        return (
            _first_payload_iid(payload, ("blocker_iid", "blocker", "iid", "source_iid", "source_card_iid")),
            _first_payload_iid(payload, ("attacker_iid", "attacker", "target_iid", "target_card_iid", "target")),
        )
    if kind == "no_block":
        return (
            None,
            _first_payload_iid(payload, ("attacker_iid", "attacker", "target_iid", "target_card_iid", "target")),
        )
    if kind == "attack":
        return (
            _first_payload_iid(payload, ("attacker_iid", "attacker", "iid", "source_iid", "source_card_iid")),
            _first_payload_iid(payload, ("target_iid", "target_card_iid", "target")),
        )

    return (
        _first_payload_iid(payload, ("iid", "source_iid", "source_card_iid", "attacker_iid", "blocker_iid", "attacker", "blocker")),
        _first_payload_iid(payload, ("target_iid", "target_card_iid", "target", "replace_field_iid", "replace_base_iid", "base_card_iid")),
    )


def _first_payload_iid(payload: Any, fields: tuple[str, ...]) -> int | None:
    data = payload if isinstance(payload, dict) else {}
    for field in fields:
        value = data.get(field)
        if value is None:
            continue
        if isinstance(value, dict):
            value = value.get("iid")
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _slot_norm(slot: int | None, max_cards: int) -> float:
    return encode_card_slot_norm(slot, max_cards=max_cards)


def _resolve_decision_kind(state: Any, actions: list[Action], decision_kind: str | None) -> str:
    explicit = normalise_decision_kind(decision_kind)
    inferred = {decision_kind_for_action(action) for action in actions}
    if explicit != "unknown":
        if explicit == "main" and len(inferred) == 1:
            inferred_kind = next(iter(inferred))
            if inferred_kind not in {"unknown", "main"}:
                return inferred_kind
        return explicit

    step = getattr(state, "step", None)
    if step is Step.MANA or getattr(step, "value", None) == "mana":
        return "mana"
    if step is Step.FLASH or getattr(step, "value", None) == "flash":
        return "flash"
    if step is Step.MAIN or getattr(step, "value", None) == "main":
        return "main"

    if len(inferred) == 1:
        return next(iter(inferred))
    return "unknown"


def _opponent_for(state: Any, player: Player) -> Any:
    players = list(getattr(state, "players", []) or [])
    for candidate in players:
        if candidate is not player:
            return candidate
    return None


def _add_player_counts(features: dict[str, float], prefix: str, player: Any) -> None:
    features[f"global:{prefix}_life_norm"] = _norm(getattr(player, "life", 0), 10.0)
    features[f"global:{prefix}_hand_count_norm"] = _norm(_safe_len(getattr(player, "hand", [])), 20.0)
    features[f"global:{prefix}_base_count_norm"] = _norm(_safe_len(getattr(player, "base", [])), 10.0)
    features[f"global:{prefix}_field_count_norm"] = _norm(_safe_len(getattr(player, "field", [])), 10.0)
    features[f"global:{prefix}_trash_count_norm"] = _norm(_safe_len(getattr(player, "trash", [])), 30.0)
    if prefix == "self":
        features["global:self_movement_right_count_norm"] = _norm(
            getattr(player, "movement_right_count", 0),
            5.0,
        )
        features["global:self_colorless_only_streak_norm"] = _norm(
            getattr(player, "colorless_only_streak", 0),
            5.0,
        )


def _add_force_counts(features: dict[str, float], prefix: str, player: Any) -> None:
    forces = list(getattr(player, "forces", []) or [])
    alive = 0
    broken = 0
    low_life = 0
    for force in forces:
        force_id = _force_id_for_instance(force)
        if bool(getattr(force, "destroyed", False)):
            broken += 1
            if force_id:
                feature_name = f"global:{prefix}_force_broken:{force_id}"
                if feature_name in features:
                    features[feature_name] = 1.0
            if bool(getattr(force, "rested", False)) and force_id:
                feature_name = f"global:{prefix}_force_rested:{force_id}"
                if feature_name in features:
                    features[feature_name] = 1.0
            continue
        alive += 1
        if force_id:
            feature_name = f"global:{prefix}_force_alive:{force_id}"
            if feature_name in features:
                features[feature_name] = 1.0
            if bool(getattr(force, "rested", False)):
                rested_feature = f"global:{prefix}_force_rested:{force_id}"
                if rested_feature in features:
                    features[rested_feature] = 1.0
        if int(getattr(force, "life", 0) or 0) <= 1:
            low_life += 1
            if force_id:
                feature_name = f"global:{prefix}_force_low_life:{force_id}"
                if feature_name in features:
                    features[feature_name] = 1.0

    features[f"global:{prefix}_force_alive_count_norm"] = _norm(alive, 3.0)
    features[f"global:{prefix}_force_broken_count_norm"] = _norm(broken, 3.0)
    features[f"global:{prefix}_force_low_life_count_norm"] = _norm(low_life, 3.0)


def _force_id_for_instance(force_instance: Any) -> str | None:
    force = getattr(force_instance, "force", None)
    for value in (
        getattr(force, "id", None),
        getattr(force_instance, "force_id", None),
        getattr(force_instance, "id", None),
    ):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except TypeError:
        return 0


def _norm(value: Any, cap: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if cap <= 0.0:
        return 0.0
    return max(0.0, min(1.0, number / cap))
