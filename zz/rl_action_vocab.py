from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from zz.enums import AttackTargetKind, Color
from zz.forces import ALL_FORCES
from zz.model import Action


ACTION_KIND_VOCAB_VERSION = "rl_action_vocab_v1"

ACTION_KINDS: tuple[str, ...] = (
    "unknown",
    "end_turn",
    "skip_mana",
    "flash_pass",
    "play_to_base",
    "place_colorless_mana",
    "swap_mana_color",
    "move_card",
    "play_card",
    "attack",
    "activate_flash_ability",
    "choose_attack_target",
    "choose_blocker",
    "block",
    "no_block",
    "choose_target",
    "choose_replacement",
    "mulligan_keep",
    "mulligan_replace",
)

ACTION_KIND_TO_ID: dict[str, int] = {kind: idx for idx, kind in enumerate(ACTION_KINDS)}

DECISION_KINDS: tuple[str, ...] = (
    "unknown",
    "mulligan",
    "mana",
    "main",
    "attack_target",
    "blocker",
    "flash",
    "generic_target",
    "replacement",
    "color_swap",
)

DECISION_KIND_TO_ID: dict[str, int] = {kind: idx for idx, kind in enumerate(DECISION_KINDS)}

ACTION_CATEGORY_FEATURES: tuple[str, ...] = (
    "resource_action:play_to_base",
    "resource_action:place_colorless",
    "resource_action:swap_color",
    "resource_action:base_to_field",
    "resource_action:field_to_base",
    "resource_action:replace_base",
    "board_action:play_card",
    "board_action:move_base_to_field",
    "board_action:move_field_to_base",
    "board_action:replace_field",
    "spell_action:flash_response",
    "spell_action:activate_flash_ability",
    "combat_action:attack_declared",
    "combat_action:block",
    "combat_action:no_block",
    "target_action:choose_attack_target",
    "target_action:choose_target",
    "target_action:choose_replacement",
    "terminal_action:end_turn",
    "terminal_action:skip_mana",
    "terminal_action:flash_pass",
)

PAYLOAD_REFERENCE_FIELDS: tuple[str, ...] = (
    "iid",
    "attacker_iid",
    "blocker_iid",
    "target_iid",
    "replace_base_iid",
    "replace_field_iid",
    "base_card_iid",
)

PAYLOAD_COLOR_NAMES: tuple[str, ...] = (
    "colorless",
    "red",
    "yellow",
    "white",
    "green",
    "blue",
    "purple",
)

FORCE_IDS: tuple[str, ...] = tuple(str(force_id) for force_id in ALL_FORCES)

PAYLOAD_FORCE_FEATURE_NAMES: tuple[str, ...] = (
    "payload:target_force_known",
    "payload:target_force_life_norm",
    "payload:target_force_low_life",
    "payload:target_force_broken",
    "payload:target_force_rested",
    *(f"payload:target_force_id:{force_id}" for force_id in FORCE_IDS),
)

PAYLOAD_ATTACK_TARGET_FEATURE_NAMES: tuple[str, ...] = (
    "payload:attack_target_attacker_bp_norm",
    "payload:attack_target_attacker_dp_norm",
    "payload:attack_target_attacker_rested",
    "payload:attack_target_force_life_minus_attacker_dp_norm",
    "payload:attack_target_force_life_lethal",
)

PAYLOAD_FEATURE_NAMES: tuple[str, ...] = (
    *(f"payload:has_{field}" for field in PAYLOAD_REFERENCE_FIELDS),
    "payload:direction_base_to_field",
    "payload:direction_field_to_base",
    "payload:payment_base_count_norm",
    *(f"payload:new_color_{color}" for color in PAYLOAD_COLOR_NAMES),
    "payload:target_kind_player",
    "payload:target_kind_force",
    "payload:target_kind_minion",
    *PAYLOAD_FORCE_FEATURE_NAMES,
    *PAYLOAD_ATTACK_TARGET_FEATURE_NAMES,
    "payload:combat_no_block",
    "payload:combat_block_declared",
    "payload:combat_attacker_bp_norm",
    "payload:combat_attacker_dp_norm",
    "payload:combat_blocker_bp_norm",
    "payload:combat_blocker_dp_norm",
    "payload:combat_bp_delta_norm",
    "payload:combat_blocker_destroyed",
    "payload:combat_attacker_destroyed",
    "payload:combat_trade",
)

ACTION_STATE_FEATURE_NAMES: tuple[str, ...] = (
    "state_action:end_turn_with_main_alternative",
    "state_action:end_turn_under_opponent_force_pressure",
    "state_action:end_turn_while_behind_on_board",
    "state_action:attack_opponent_force_low_life",
    "state_action:attack_self_life_low",
    "state_action:attack_while_behind_on_board",
    "state_action:place_colorless_under_base_cap",
    "state_action:place_colorless_with_colored_hand_demand",
    "state_action:place_colorless_ignores_missing_colored_hand",
    "state_action:place_colorless_after_colorless_streak",
    "state_action:skip_mana_under_base_cap",
    "state_action:no_block_life_lethal",
    "state_action:no_block_force_exposed",
    "state_action:no_block_pressure_norm",
    "state_action:block_preserves_life_or_force",
    "state_action:blocker_only_available_blocker",
    "state_action:blocker_chump_block",
    "state_action:blocker_loses_last_field_body",
)

_CARD_PROFILE_NUMERIC_FEATURE_NAMES: tuple[str, ...] = (
    "card_profile:known",
    "card_profile:action_references_card",
    "card_profile:cost_norm",
    "card_profile:bp_norm",
    "card_profile:dp_norm",
)


def _card_profile_taxonomy_feature_names() -> tuple[str, ...]:
    from zz.card_profiles import card_taxonomy_vocabulary

    names: list[str] = []
    for namespace, labels in card_taxonomy_vocabulary().items():
        feature_prefix = f"card_profile_{namespace.replace(':', '_')}"
        names.extend(f"{feature_prefix}:{label}" for label in labels)
    return tuple(names)


CARD_PROFILE_FEATURE_NAMES: tuple[str, ...] = (
    *_CARD_PROFILE_NUMERIC_FEATURE_NAMES,
    *_card_profile_taxonomy_feature_names(),
)


def normalise_action_kind(action_or_kind: Action | str | Any) -> str:
    raw_kind = getattr(action_or_kind, "kind", action_or_kind)
    kind = str(raw_kind or "").strip().lower()
    return kind if kind in ACTION_KIND_TO_ID else "unknown"


def action_kind_id(action_or_kind: Action | str | Any) -> int:
    return ACTION_KIND_TO_ID[normalise_action_kind(action_or_kind)]


def normalise_decision_kind(decision_kind: str | None) -> str:
    kind = str(decision_kind or "").strip().lower()
    return kind if kind in DECISION_KIND_TO_ID else "unknown"


def decision_kind_for_action(action: Action, *, context_decision_kind: str | None = None) -> str:
    context = normalise_decision_kind(context_decision_kind)
    if context != "unknown":
        return context

    kind = normalise_action_kind(action)
    if kind in {"mulligan_keep", "mulligan_replace"}:
        return "mulligan"
    if kind in {"play_to_base", "place_colorless_mana", "skip_mana"}:
        return "mana"
    if kind == "swap_mana_color":
        return "color_swap"
    if kind == "choose_attack_target":
        return "attack_target"
    if kind in {"choose_blocker", "block", "no_block"}:
        return "blocker"
    if kind in {"flash_pass", "activate_flash_ability"}:
        return "flash"
    if kind == "choose_target":
        return "generic_target"
    if kind == "choose_replacement":
        return "replacement"
    if kind == "unknown":
        return "unknown"
    return "main"


def action_category_tags(action: Action) -> tuple[str, ...]:
    kind = normalise_action_kind(action)
    payload = _payload(action)
    tags: list[str] = [f"action_kind:{kind}"]

    if kind == "play_to_base":
        tags.append("resource_action:play_to_base")
    elif kind == "place_colorless_mana":
        tags.append("resource_action:place_colorless")
    elif kind == "swap_mana_color":
        tags.append("resource_action:swap_color")
    elif kind == "move_card":
        direction = str(payload.get("direction") or "").strip().lower()
        if direction == "base_to_field":
            tags.extend(["resource_action:base_to_field", "board_action:move_base_to_field"])
        elif direction == "field_to_base":
            tags.extend(["resource_action:field_to_base", "board_action:move_field_to_base"])
    elif kind == "play_card":
        tags.append("board_action:play_card")
    elif kind == "attack":
        tags.append("combat_action:attack_declared")
    elif kind == "activate_flash_ability":
        tags.extend(["spell_action:activate_flash_ability", "spell_action:flash_response"])
    elif kind == "choose_attack_target":
        tags.append("target_action:choose_attack_target")
    elif kind in {"choose_blocker", "block"}:
        tags.append("combat_action:no_block" if bool(payload.get("block_none")) else "combat_action:block")
    elif kind == "no_block":
        tags.append("combat_action:no_block")
    elif kind == "choose_target":
        tags.append("target_action:choose_target")
    elif kind == "choose_replacement":
        tags.append("target_action:choose_replacement")
    elif kind == "end_turn":
        tags.append("terminal_action:end_turn")
    elif kind == "skip_mana":
        tags.append("terminal_action:skip_mana")
    elif kind == "flash_pass":
        tags.append("terminal_action:flash_pass")

    if payload.get("replace_field_iid") is not None:
        tags.append("board_action:replace_field")
    if payload.get("replace_base_iid") is not None or payload.get("base_card_iid") is not None:
        tags.append("resource_action:replace_base")

    return _dedupe(tags)


def payload_numeric_features(action: Action) -> dict[str, float]:
    payload = _payload(action)
    features = {name: 0.0 for name in PAYLOAD_FEATURE_NAMES}

    for field in PAYLOAD_REFERENCE_FIELDS:
        if payload.get(field) is not None:
            features[f"payload:has_{field}"] = 1.0

    direction = str(payload.get("direction") or "").strip().lower()
    if direction in {"base_to_field", "field_to_base"}:
        features[f"payload:direction_{direction}"] = 1.0

    payment_iids = payload.get("payment_base_iids")
    if isinstance(payment_iids, Iterable) and not isinstance(payment_iids, (str, bytes, dict)):
        features["payload:payment_base_count_norm"] = min(1.0, len(list(payment_iids)) / 10.0)

    color = _normalise_color(payload.get("new_color"))
    if color in PAYLOAD_COLOR_NAMES:
        features[f"payload:new_color_{color}"] = 1.0

    target_kind = _normalise_target_kind(_payload_target_kind(payload))
    if target_kind in {"player", "force", "minion"}:
        features[f"payload:target_kind_{target_kind}"] = 1.0

    features.update(_target_force_payload_features(payload, target_kind))
    features.update(_attack_target_payload_features(action, payload, target_kind))
    features.update(_combat_payload_features(action, payload))
    return features


def action_state_numeric_features(
    action: Action,
    *,
    global_features: dict[str, float] | None = None,
    action_set_actions: Iterable[Action] | None = None,
) -> dict[str, float]:
    features = {name: 0.0 for name in ACTION_STATE_FEATURE_NAMES}
    kind = normalise_action_kind(action)
    state = global_features or {}
    if kind == "end_turn":
        alternatives = list(action_set_actions or [])
        has_main_alternative = any(
            normalise_action_kind(candidate) not in {"end_turn", "flash_pass", "skip_mana"}
            for candidate in alternatives
        )
        features["state_action:end_turn_with_main_alternative"] = 1.0 if has_main_alternative else 0.0
        opponent_force_pressure = _feature_value(state, "global:opponent_force_low_life_count_norm") > 0.0
        features["state_action:end_turn_under_opponent_force_pressure"] = 1.0 if opponent_force_pressure else 0.0
        behind_on_board = _feature_value(state, "global:self_field_count_norm") < _feature_value(
            state,
            "global:opponent_field_count_norm",
        )
        features["state_action:end_turn_while_behind_on_board"] = 1.0 if behind_on_board else 0.0
        return features

    if kind == "attack":
        opponent_force_pressure = _feature_value(state, "global:opponent_force_low_life_count_norm") > 0.0
        features["state_action:attack_opponent_force_low_life"] = 1.0 if opponent_force_pressure else 0.0
        low_self_life = 0.0 < _feature_value(state, "global:self_life_norm") <= 0.3
        features["state_action:attack_self_life_low"] = 1.0 if low_self_life else 0.0
        behind_on_board = _feature_value(state, "global:self_field_count_norm") < _feature_value(
            state,
            "global:opponent_field_count_norm",
        )
        features["state_action:attack_while_behind_on_board"] = 1.0 if behind_on_board else 0.0
        return features

    if kind not in {"choose_blocker", "block", "no_block"}:
        return features

    payload_features = payload_numeric_features(action)
    no_block = payload_features.get("payload:combat_no_block", 0.0) > 0.0
    block_declared = payload_features.get("payload:combat_block_declared", 0.0) > 0.0
    attacker_dp_norm = float(payload_features.get("payload:combat_attacker_dp_norm", 0.0))
    self_life_norm = _feature_value(state, "global:self_life_norm")
    force_exposed = (
        _feature_value(state, "global:self_force_alive_count_norm") > 0.0
        and _feature_value(state, "global:self_force_low_life_count_norm") > 0.0
    )
    pressure_is_lethal = attacker_dp_norm > 0.0 and self_life_norm > 0.0 and attacker_dp_norm >= self_life_norm

    if no_block:
        features["state_action:no_block_pressure_norm"] = max(0.0, min(1.0, attacker_dp_norm))
        features["state_action:no_block_life_lethal"] = 1.0 if pressure_is_lethal else 0.0
        features["state_action:no_block_force_exposed"] = 1.0 if force_exposed else 0.0
        return features

    if block_declared:
        features["state_action:block_preserves_life_or_force"] = 1.0 if pressure_is_lethal or force_exposed else 0.0
        block_options = _block_option_count(action_set_actions)
        only_blocker = block_options == 1
        features["state_action:blocker_only_available_blocker"] = 1.0 if only_blocker else 0.0
        chump_block = (
            payload_features.get("payload:combat_blocker_destroyed", 0.0) > 0.0
            and payload_features.get("payload:combat_attacker_destroyed", 0.0) <= 0.0
        )
        features["state_action:blocker_chump_block"] = 1.0 if chump_block else 0.0
        low_field = _feature_value(state, "global:self_field_count_norm") <= 0.1
        features["state_action:blocker_loses_last_field_body"] = 1.0 if chump_block and (only_blocker or low_field) else 0.0
    return features


def card_profile_numeric_features(action: Action) -> dict[str, float]:
    features = {name: 0.0 for name in CARD_PROFILE_FEATURE_NAMES}
    card_id = _referenced_card_id(_payload(action))
    if not card_id:
        return features

    features["card_profile:action_references_card"] = 1.0
    profile = _cached_card_profile(card_id)
    if profile is None:
        return features

    features["card_profile:known"] = 1.0
    features["card_profile:cost_norm"] = _bounded_norm(float(profile.identity.cost_total), 10.0)
    features["card_profile:bp_norm"] = _bounded_norm(float(profile.identity.bp), 1000.0)
    features["card_profile:dp_norm"] = _bounded_norm(float(profile.identity.dp), 10.0)
    for tag in _card_profile_tags(profile):
        feature_name = _card_profile_feature_name_from_tag(tag)
        if feature_name in features:
            features[feature_name] = 1.0
    return features


@lru_cache(maxsize=512)
def _cached_card_profile(card_id: str):
    _ensure_card_registry_loaded()
    from zz.card_profiles import build_card_profile
    from zz.cards import CARD_REGISTRY

    card = CARD_REGISTRY.get(card_id)
    if card is None:
        return None
    return build_card_profile(card)


def _ensure_card_registry_loaded() -> None:
    import zz.basic  # noqa: F401 - register Basic cards for taxonomy features.
    import zz.pc01  # noqa: F401 - register PC:01 cards for taxonomy features.


def _card_profile_tags(profile: Any) -> tuple[str, ...]:
    from zz.card_profiles import card_profile_tags

    return card_profile_tags(profile)


def _referenced_card_id(payload: dict[str, Any]) -> str | None:
    for field in ("card_id", "base_card_id", "target_card_id", "source_card_id"):
        card_id = _clean_card_id(payload.get(field))
        if card_id:
            return card_id
    for field in ("card", "attacker", "blocker", "target", "source", "replacement"):
        nested = payload.get(field)
        if isinstance(nested, dict):
            for nested_field in ("card_id", "cardId", "id", "base_card_id"):
                card_id = _clean_card_id(nested.get(nested_field))
                if card_id:
                    return card_id
    signature_card_id = _find_card_id(payload.get("signature"))
    if signature_card_id:
        return signature_card_id
    return None


def _clean_card_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find_card_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for field in ("card_id", "cardId", "base_card_id", "target_card_id", "source_card_id"):
            card_id = _clean_card_id(value.get(field))
            if card_id:
                return card_id
        for nested in value.values():
            card_id = _find_card_id(nested)
            if card_id:
                return card_id
    elif isinstance(value, list):
        for nested in value:
            card_id = _find_card_id(nested)
            if card_id:
                return card_id
    return None


def _card_profile_feature_name_from_tag(tag: str) -> str:
    parts = str(tag).split(":")
    if len(parts) == 2:
        namespace, label = parts
    elif len(parts) == 3 and parts[0] == "identity":
        namespace, label = f"{parts[0]}_{parts[1]}", parts[2]
    else:
        return ""
    return f"card_profile_{namespace}:{label}"


def _payload_target_kind(payload: dict[str, Any]) -> Any:
    for field in ("target_kind", "attack_target_kind", "targetKind", "attackTargetKind"):
        value = payload.get(field)
        if value is not None:
            return value
    for field in ("target", "attack_target", "attackTarget", "ref"):
        value = payload.get(field)
        kind = _target_kind_from_value(value)
        if kind is not None:
            return kind
    signature_kind = _target_kind_from_value(payload.get("signature"))
    return signature_kind


def _target_kind_from_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, AttackTargetKind)):
        return value
    if isinstance(value, dict):
        for field in ("target_kind", "attack_target_kind", "targetKind", "attackTargetKind", "kind"):
            nested = value.get(field)
            if nested is not None:
                return nested
        for field in ("target", "attack_target", "attackTarget", "ref"):
            nested_kind = _target_kind_from_value(value.get(field))
            if nested_kind is not None:
                return nested_kind
        return None
    return getattr(value, "kind", None)


def _target_force_payload_features(payload: dict[str, Any], target_kind: str) -> dict[str, float]:
    features = {name: 0.0 for name in PAYLOAD_FORCE_FEATURE_NAMES}
    force_id = _referenced_force_id(payload)
    references_force = target_kind == "force" or force_id is not None
    if not references_force:
        return features

    features["payload:target_force_known"] = 1.0
    if force_id:
        feature_name = f"payload:target_force_id:{force_id}"
        if feature_name in features:
            features[feature_name] = 1.0

    life = _target_force_float(payload, ("force_life", "target_force_life", "targetForceLife", "life"))
    if life is not None:
        features["payload:target_force_life_norm"] = _bounded_norm(life, 10.0)
        features["payload:target_force_low_life"] = 1.0 if life <= 1.0 else 0.0
    if _target_force_bool(payload, ("destroyed", "force_destroyed", "target_force_destroyed")) is True:
        features["payload:target_force_broken"] = 1.0
    if _target_force_bool(payload, ("rested", "force_rested", "target_force_rested")) is True:
        features["payload:target_force_rested"] = 1.0
    return features


def _referenced_force_id(payload: dict[str, Any]) -> str | None:
    for field in ("force_id", "forceId", "target_force_id", "targetForceId"):
        force_id = _clean_force_id(payload.get(field))
        if force_id:
            return force_id
    for field in ("force", "target", "attack_target", "attackTarget", "ref", "signature"):
        force_id = _find_force_id(payload.get(field))
        if force_id:
            return force_id
    return None


def _find_force_id(value: Any, *, depth: int = 0) -> str | None:
    if value is None or depth > 5:
        return None
    if isinstance(value, dict):
        for field in ("force_id", "forceId", "target_force_id", "targetForceId"):
            force_id = _clean_force_id(value.get(field))
            if force_id:
                return force_id
        force_value = value.get("force")
        if force_value is not None:
            force_id = _find_force_id(force_value, depth=depth + 1)
            if force_id:
                return force_id
        force_id = _clean_force_id(value.get("id"), require_known=True)
        if force_id:
            return force_id
        for field in ("target", "attack_target", "attackTarget", "ref", "signature"):
            force_id = _find_force_id(value.get(field), depth=depth + 1)
            if force_id:
                return force_id
        for nested in value.values():
            force_id = _find_force_id(nested, depth=depth + 1)
            if force_id:
                return force_id
    elif isinstance(value, list):
        for nested in value:
            force_id = _find_force_id(nested, depth=depth + 1)
            if force_id:
                return force_id
    else:
        for attr in ("force_id", "forceId", "target_force_id", "targetForceId"):
            force_id = _clean_force_id(getattr(value, attr, None))
            if force_id:
                return force_id
        force_value = getattr(value, "force", None)
        if force_value is not None:
            force_id = _find_force_id(force_value, depth=depth + 1)
            if force_id:
                return force_id
        force_id = _clean_force_id(getattr(value, "id", None), require_known=True)
        if force_id:
            return force_id
        for attr in ("ref", "target"):
            force_id = _find_force_id(getattr(value, attr, None), depth=depth + 1)
            if force_id:
                return force_id
    return None


def _clean_force_id(value: Any, *, require_known: bool = False) -> str | None:
    if value is None:
        return None
    text = str(getattr(value, "value", value)).strip()
    if not text:
        return None
    if text in FORCE_IDS:
        return text
    lowered = text.lower()
    if lowered in FORCE_IDS:
        return lowered
    if require_known:
        return None
    return text if lowered.startswith("force_") else None


def _target_force_float(payload: dict[str, Any], field_names: tuple[str, ...]) -> float | None:
    value = _target_force_value(payload, field_names)
    return _optional_float(value)


def _target_force_bool(payload: dict[str, Any], field_names: tuple[str, ...]) -> bool | None:
    value = _target_force_value(payload, field_names)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None


def _target_force_value(payload: dict[str, Any], field_names: tuple[str, ...]) -> Any:
    for field in field_names:
        if field in payload:
            return payload[field]
    for field in ("force", "target", "attack_target", "attackTarget", "ref"):
        value = _find_force_attr(payload.get(field), field_names)
        if value is not None:
            return value
    return None


def _attack_target_payload_features(action: Action, payload: dict[str, Any], target_kind: str) -> dict[str, float]:
    features = {name: 0.0 for name in PAYLOAD_ATTACK_TARGET_FEATURE_NAMES}
    if normalise_action_kind(action) != "choose_attack_target":
        return features

    attacker = payload.get("attacker")
    attacker_payload = attacker if isinstance(attacker, dict) else {}
    attacker_bp = _optional_float(
        attacker_payload.get("bp")
        if "bp" in attacker_payload
        else payload.get("attacker_bp", payload.get("attackerBp"))
    )
    attacker_dp = _optional_float(
        attacker_payload.get("dp")
        if "dp" in attacker_payload
        else payload.get("attacker_dp", payload.get("attackerDp"))
    )
    if attacker_bp is not None:
        features["payload:attack_target_attacker_bp_norm"] = _bounded_norm(attacker_bp, 1000.0)
    if attacker_dp is not None:
        features["payload:attack_target_attacker_dp_norm"] = _bounded_norm(attacker_dp, 10.0)

    rested = attacker_payload.get("rested", payload.get("attacker_rested", payload.get("attackerRested")))
    if rested is not None:
        features["payload:attack_target_attacker_rested"] = 1.0 if _truthy(rested) else 0.0

    force_life = _target_force_float(payload, ("force_life", "target_force_life", "targetForceLife", "life"))
    if target_kind == "force" and force_life is not None and attacker_dp is not None:
        features["payload:attack_target_force_life_minus_attacker_dp_norm"] = _signed_bounded_norm(
            force_life - attacker_dp,
            10.0,
        )
        features["payload:attack_target_force_life_lethal"] = 1.0 if attacker_dp >= force_life else 0.0
    return features


def _find_force_attr(value: Any, field_names: tuple[str, ...], *, depth: int = 0) -> Any:
    if value is None or depth > 5:
        return None
    if isinstance(value, dict):
        for field in field_names:
            if field in value:
                return value[field]
        for field in ("force", "target", "attack_target", "attackTarget", "ref"):
            found = _find_force_attr(value.get(field), field_names, depth=depth + 1)
            if found is not None:
                return found
    else:
        for field in field_names:
            if hasattr(value, field):
                return getattr(value, field)
        for field in ("force", "target", "ref"):
            found = _find_force_attr(getattr(value, field, None), field_names, depth=depth + 1)
            if found is not None:
                return found
    return None


def _combat_payload_features(action: Action, payload: dict[str, Any]) -> dict[str, float]:
    features = {name: 0.0 for name in PAYLOAD_FEATURE_NAMES if name.startswith("payload:combat_")}
    kind = normalise_action_kind(action)
    if kind not in {"choose_blocker", "block", "no_block"}:
        return features

    attacker = payload.get("attacker")
    attacker_payload = attacker if isinstance(attacker, dict) else {}
    attacker_bp = _optional_float(attacker_payload.get("bp"))
    attacker_dp = _optional_float(attacker_payload.get("dp"))
    blocker_bp = _optional_float(payload.get("bp"))
    blocker_dp = _optional_float(payload.get("dp"))
    no_block = kind == "no_block" or bool(payload.get("block_none"))

    features["payload:combat_no_block"] = 1.0 if no_block else 0.0
    features["payload:combat_block_declared"] = 0.0 if no_block else 1.0
    if attacker_bp is not None:
        features["payload:combat_attacker_bp_norm"] = _bounded_norm(attacker_bp, 1000.0)
    if attacker_dp is not None:
        features["payload:combat_attacker_dp_norm"] = _bounded_norm(attacker_dp, 10.0)
    if blocker_bp is not None:
        features["payload:combat_blocker_bp_norm"] = _bounded_norm(blocker_bp, 1000.0)
    if blocker_dp is not None:
        features["payload:combat_blocker_dp_norm"] = _bounded_norm(blocker_dp, 10.0)
    if attacker_bp is not None and blocker_bp is not None:
        features["payload:combat_bp_delta_norm"] = _signed_bounded_norm(blocker_bp - attacker_bp, 1000.0)
        blocker_destroyed = attacker_bp >= blocker_bp
        attacker_destroyed = blocker_bp >= attacker_bp
        features["payload:combat_blocker_destroyed"] = 1.0 if blocker_destroyed else 0.0
        features["payload:combat_attacker_destroyed"] = 1.0 if attacker_destroyed else 0.0
        features["payload:combat_trade"] = 1.0 if blocker_destroyed and attacker_destroyed else 0.0
    return features


def _block_option_count(actions: Iterable[Action] | None) -> int:
    if actions is None:
        return 0
    count = 0
    for action in actions:
        kind = normalise_action_kind(action)
        payload = _payload(action)
        if kind in {"choose_blocker", "block"} and not bool(payload.get("block_none")):
            count += 1
    return count


def _feature_value(features: dict[str, float], name: str) -> float:
    try:
        return float(features.get(name, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _payload(action: Action) -> dict[str, Any]:
    payload = getattr(action, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)


def _normalise_color(value: Any) -> str:
    if isinstance(value, Color):
        return value.name.lower()
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip().lower()
        if text.startswith("color."):
            text = text.split(".", 1)[1]
        for color in Color:
            if text == color.name.lower() or text == str(color.value).lower():
                return color.name.lower()
        return text
    try:
        return Color(value).name.lower()
    except (ValueError, TypeError):
        return ""


def _normalise_target_kind(value: Any) -> str:
    if isinstance(value, AttackTargetKind):
        return value.value
    if value is None:
        return ""
    text = str(getattr(value, "value", value)).strip().lower()
    if text.startswith("attacktargetkind."):
        text = text.rsplit(".", 1)[-1]
    if text in {"player", "force", "minion"}:
        return text
    if text in {kind.name.lower() for kind in AttackTargetKind}:
        return AttackTargetKind[text.upper()].value
    return text


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _bounded_norm(value: float, cap: float) -> float:
    if cap <= 0.0:
        return 0.0
    return max(0.0, min(1.0, float(value) / float(cap)))


def _signed_bounded_norm(value: float, cap: float) -> float:
    if cap <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, float(value) / float(cap)))
