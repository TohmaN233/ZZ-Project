from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from zz.enums import Color


COUNTERFACTUAL_TRANSITION_SCHEMA_VERSION = "counterfactual_transition_v1"
COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION = "counterfactual_transition_pair_v1"

TARGET_COMPONENT_KEYS = (
    "terminalValue",
    "survivalValue",
    "pressureValue",
    "planValue",
    "tempoValue",
    "resourceValue",
)

FORBIDDEN_FEATURE_PREFIXES = (
    "opponent_kind:",
    "opponentDifficulty:",
    "difficulty:",
    "chosen_by_policy",
    "policy_chosen",
    "playerDeckId:",
    "opponentDeckId:",
    "own_deck_id:",
    "enemy_deck_id:",
    "deck_id:",
    "opponent_deck_id:",
    "hard_row_id:",
    "m014:",
)


def transition_value_from_targets(targets: dict[str, Any]) -> float:
    value = sum(float(targets.get(key, 0.0) or 0.0) for key in TARGET_COMPONENT_KEYS)
    value -= float(targets.get("timeoutPenalty", 0.0) or 0.0)
    return float(value)


def validate_transition_row(row: dict[str, Any]) -> None:
    if row.get("schemaVersion") != COUNTERFACTUAL_TRANSITION_SCHEMA_VERSION:
        raise ValueError(f"unsupported schemaVersion: {row.get('schemaVersion')!r}")
    for key in ("rowId", "beforeStateFeatures", "actions"):
        if key not in row:
            raise ValueError(f"missing required transition row key: {key}")
    if not isinstance(row["beforeStateFeatures"], dict):
        raise ValueError("beforeStateFeatures must be a dict")
    if not isinstance(row["actions"], list) or not row["actions"]:
        raise ValueError("actions must be a non-empty list")
    _reject_forbidden_features(row["beforeStateFeatures"])
    for action in row["actions"]:
        for key in ("actionId", "actionKind", "actionFeatures", "afterStateFeatures", "rolloutSummary", "targets"):
            if key not in action:
                raise ValueError(f"missing required action key: {key}")
        for feature_map_key in ("actionFeatures", "afterStateFeatures", "rolloutSummary"):
            if isinstance(action.get(feature_map_key), dict):
                _reject_forbidden_features(action[feature_map_key])
        targets = action["targets"]
        computed = transition_value_from_targets(targets)
        if "transitionValue" in targets and abs(float(targets["transitionValue"]) - computed) > 1e-6:
            raise ValueError("transitionValue does not match component sum")


def _reject_forbidden_features(features: dict[str, Any]) -> None:
    for key in features:
        if any(str(key).startswith(prefix) for prefix in FORBIDDEN_FEATURE_PREFIXES):
            raise ValueError(f"forbidden feature: {key}")


def _without_forbidden_features(features: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in features.items()
        if not any(str(key).startswith(prefix) for prefix in FORBIDDEN_FEATURE_PREFIXES)
    }


def _transition_observed_opponent_feature(key: str) -> bool:
    payload_key = str(key)
    for prefix in ("before:", "action:", "after:", "rollout:"):
        if payload_key.startswith(prefix):
            payload_key = payload_key[len(prefix):]
            break
    return (
        payload_key.startswith("opponent_observed_")
        or "observed_opponent" in payload_key
        or "observed_aggression" in payload_key
    )


def _transition_row_action_kind(row: dict[str, Any]) -> str | None:
    for key, value in row.items():
        key_text = str(key)
        if key_text.startswith("action:action:") and _positive_feature_value(value) > 0.0:
            return key_text[len("action:action:"):]
    return None


def _transition_play_card_scoped_feature_inactive(row: dict[str, Any], key: str) -> bool:
    key_text = str(key)
    if not key_text.startswith("action:play_card_"):
        return False
    return _transition_row_action_kind(row) not in {"play_card", "activate_flash_ability"}


def _transition_action_context_feature(key: str) -> bool:
    key_text = str(key)
    if not key_text.startswith("action:"):
        return False
    payload_key = key_text[len("action:"):]
    if payload_key in {"learner_is_first_player", "learner_is_second_player"}:
        return False
    if payload_key.startswith((
        "own_deck_archetype:",
        "own_deck_combo_route:",
        "own_deck_semantic_combo_route:",
        "own_deck_plan:",
        "own_deck_semantic_plan:",
        "own_force_id:",
        "own_force_combo:",
        "enemy_force_id:",
        "enemy_force_combo:",
    )):
        return False
    if payload_key.startswith(("own_deck_", "enemy_deck_")):
        return True
    return payload_key.startswith((
        "own_",
        "enemy_",
        "opponent_observed_",
        "can_swap_mana_color",
    ))


_TRANSITION_SCHEMA_COLOR_VALUES = {color.name.lower() for color in Color}


def _transition_schema_color_enum_feature(key: str) -> bool:
    payload_key = str(key)
    for prefix in ("before:", "action:", "after:", "rollout:"):
        if payload_key.startswith(prefix):
            payload_key = payload_key[len(prefix):]
            break
    if ":" not in payload_key:
        return False
    feature_name, color_value = payload_key.rsplit(":", 1)
    if color_value.strip().lower() not in _TRANSITION_SCHEMA_COLOR_VALUES:
        return False
    return (
        feature_name.endswith("_cost_color")
        or feature_name.endswith("_mana_color")
        or feature_name.endswith("_color")
    )


def _numeric_prefixed(prefix: str, features: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in features.items():
        if isinstance(value, bool):
            out[f"{prefix}:{key}"] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            out[f"{prefix}:{key}"] = float(value)
    return out


_CONTEXT_ACTION_INTERACTION_CONTEXT_PREFIXES = (
    "own_deck_plan:",
    "own_deck_semantic_plan:",
    "own_deck_combo_route:",
    "own_deck_semantic_combo_route:",
    "own_deck_archetype:",
    "own_deck_semantic_archetype:",
    "own_force:",
    "enemy_force:",
)

_CONTEXT_ACTION_INTERACTION_ACTION_PREFIXES = (
    "action:",
    "semantic_action_",
    "play_to_base_",
    "place_colorless_mana_",
    "play_card_profile_role:",
    "play_card_profile_target:",
    "play_card_profile_phase:",
    "play_card_profile_zone:",
    "play_card_profile_risk:",
    "play_card_semantic_role:",
    "play_card_semantic_target:",
    "play_card_semantic_phase:",
    "play_card_semantic_zone:",
    "play_card_effect:",
    "play_card_force_life_exchange",
    "play_card_adds_blocker",
    "replace_field_",
    "move_card_profile_role:",
    "move_card_profile_zone:",
    "move_card_profile_risk:",
    "move_card_semantic_role:",
    "move_field_to_base",
    "move_base_to_field",
    "attack_",
    "target_force_id:",
    "target_effect:",
    "blocker_profile_role:",
    "blocker_death_payoff",
    "blocker_has_on_destroy",
    "positive_",
    "negative_",
)


def _positive_feature_value(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _clamp_interaction_value(value: float) -> float:
    if value <= 0.0:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _context_action_interaction_contexts(before_features: dict[str, Any]) -> dict[str, float]:
    contexts: dict[str, float] = {}
    for key, value in before_features.items():
        numeric = _positive_feature_value(value)
        if numeric <= 0.0:
            continue
        if any(str(key).startswith(prefix) for prefix in _CONTEXT_ACTION_INTERACTION_CONTEXT_PREFIXES):
            contexts[str(key)] = _clamp_interaction_value(numeric)

    own_forces_alive = before_features.get("own_forces_alive")
    if isinstance(own_forces_alive, (int, float, bool)):
        own_alive_value = _positive_feature_value(own_forces_alive)
        if own_alive_value > 0.0:
            contexts["force_state:own_alive"] = _clamp_interaction_value(own_alive_value)
        else:
            contexts["force_state:own_broken"] = 1.0

    enemy_forces_alive = before_features.get("enemy_forces_alive")
    if isinstance(enemy_forces_alive, (int, float, bool)):
        enemy_alive_value = _positive_feature_value(enemy_forces_alive)
        if enemy_alive_value > 0.0:
            contexts["force_state:enemy_alive"] = _clamp_interaction_value(enemy_alive_value)
        else:
            contexts["force_state:enemy_broken"] = 1.0

    own_force_life = _positive_feature_value(before_features.get("own_force_life_total"))
    own_lowest_force_life = _positive_feature_value(before_features.get("own_lowest_force_life"))
    if (0.0 < own_force_life <= 0.25) or (0.0 < own_lowest_force_life <= 0.20):
        contexts["force_state:own_low_life"] = 1.0

    enemy_force_life = _positive_feature_value(before_features.get("enemy_force_life_total"))
    enemy_lowest_force_life = _positive_feature_value(before_features.get("enemy_lowest_force_life"))
    if (0.0 < enemy_force_life <= 0.25) or (0.0 < enemy_lowest_force_life <= 0.20):
        contexts["force_state:enemy_low_life"] = 1.0

    colored_hand_demand = sum(
        _positive_feature_value(value)
        for key, value in before_features.items()
        if str(key).startswith("own_hand_demand_color:")
        and not str(key).endswith(":colorless")
    )
    if colored_hand_demand > 0.0:
        contexts["mana_state:colored_hand_demand"] = _clamp_interaction_value(colored_hand_demand)

    if _positive_feature_value(before_features.get("own_no_ready_colored_mana_for_hand")) > 0.0:
        contexts["mana_state:no_ready_colored_hand_mana"] = 1.0
    if _positive_feature_value(before_features.get("own_ready_color_matches_hand_demand")) > 0.0:
        contexts["mana_state:ready_color_matches_hand_demand"] = _clamp_interaction_value(
            _positive_feature_value(before_features.get("own_ready_color_matches_hand_demand"))
        )
    if _positive_feature_value(before_features.get("place_colorless_mana_supports_chimera_color_fix")) > 0.0:
        contexts["mana_state:chimera_colorless_support"] = 1.0

    if _positive_feature_value(before_features.get("enemy_pressure_high_player_risk")) > 0.0:
        contexts["pressure_state:enemy_high_player_risk"] = 1.0
    if _positive_feature_value(before_features.get("enemy_pressure_near_player_lethal")) > 0.0:
        contexts["pressure_state:enemy_near_player_lethal"] = 1.0
    enemy_dp_pressure = _positive_feature_value(before_features.get("enemy_field_dp_pressure"))
    if enemy_dp_pressure > 0.0:
        contexts["pressure_state:enemy_field_dp_pressure"] = _clamp_interaction_value(enemy_dp_pressure)

    return contexts


def _context_action_interaction_actions(action_features: dict[str, Any]) -> dict[str, float]:
    actions: dict[str, float] = {}
    for key, value in action_features.items():
        numeric = _positive_feature_value(value)
        if numeric <= 0.0:
            continue
        if any(str(key).startswith(prefix) for prefix in _CONTEXT_ACTION_INTERACTION_ACTION_PREFIXES):
            actions[str(key)] = _clamp_interaction_value(numeric)
    return actions


def _context_action_interaction_features(
    *,
    before_features: dict[str, Any],
    action_features: dict[str, Any],
) -> dict[str, float]:
    contexts = _context_action_interaction_contexts(before_features)
    actions = _context_action_interaction_actions(action_features)
    interactions: dict[str, float] = {}
    for context_key, context_value in sorted(contexts.items()):
        for action_key, action_value in sorted(actions.items()):
            value = float(context_value) * float(action_value)
            if value > 0.0:
                interactions[f"interaction:ctx:{context_key}|act:{action_key}"] = value
    return interactions


def action_transition_feature_row(
    *,
    before_features: dict[str, Any],
    action: dict[str, Any],
    include_rollout_features: bool = True,
) -> dict[str, float]:
    features: dict[str, float] = {}
    clean_before_features = _without_forbidden_features(before_features)
    clean_action_features = _without_forbidden_features(dict(action.get("actionFeatures") or {}))
    clean_after_features = _without_forbidden_features(dict(action.get("afterStateFeatures") or {}))
    features.update(_numeric_prefixed("before", clean_before_features))
    features.update(_numeric_prefixed("action", clean_action_features))
    features.update(_numeric_prefixed("after", clean_after_features))
    features.update(_context_action_interaction_features(
        before_features=clean_before_features,
        action_features=clean_action_features,
    ))
    if include_rollout_features:
        features.update(_numeric_prefixed("rollout", dict(action.get("rolloutSummary") or {})))
    return features


def runtime_action_transition_feature_row(
    *,
    extractor: Any,
    before_engine: Any,
    before_player: Any,
    action: Any,
    after_engine: Any,
    after_player: Any,
    horizon_actions: int,
    horizon_turns: int,
    clone_after_engine: bool = True,
    include_rollout_features: bool = True,
) -> dict[str, float]:
    before_features = _without_forbidden_features(extractor.features_for_state(before_engine, before_player))
    action_features = _without_forbidden_features(
        _extract_transition_action_features(extractor, before_engine, before_player, action)
    )
    before_snapshot = _life_resource_snapshot(before_engine, before_player)
    player_index = _player_index(after_engine, after_player)
    rollout_engine = _clone_engine(after_engine) if clone_after_engine and include_rollout_features else after_engine
    rollout_player = _player_at(rollout_engine, player_index)
    terminal_winner = None
    timeout = False
    rollout_actions = 0
    if include_rollout_features and int(horizon_actions) > 0:
        try:
            rollout_actions, timeout = _roll_forward(rollout_engine, horizon_actions)
        except Exception as exc:
            terminal_winner = getattr(exc, "winner", None)
            rollout_actions = 0
    if include_rollout_features:
        rollout_player = _player_at(rollout_engine, player_index) or rollout_player
        after_features = _without_forbidden_features(extractor.features_for_state(rollout_engine, rollout_player))
        rollout_summary = _rollout_summary(
            before=before_snapshot,
            after=_life_resource_snapshot(rollout_engine, rollout_player),
            horizon_actions=rollout_actions,
            horizon_turns=horizon_turns,
            terminal_winner=terminal_winner,
            timeout=timeout,
        )
    else:
        after_features = _without_forbidden_features(extractor.features_for_state(after_engine, after_player))
        rollout_summary = {}
    return action_transition_feature_row(
        before_features=before_features,
        action={
            "actionFeatures": action_features,
            "afterStateFeatures": after_features,
            "rolloutSummary": rollout_summary,
        },
        include_rollout_features=include_rollout_features,
    )


def _extract_transition_action_features(extractor: Any, engine: Any, player: Any, action: Any) -> dict[str, Any]:
    action_only = getattr(extractor, "action_features", None)
    if callable(action_only):
        return dict(action_only(engine, player, action) or {})
    return dict(extractor.features_for_action(engine, player, action) or {})


def write_jsonl_rows(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            fh.write("\n")


def read_jsonl_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


AICE_MANA_BOUNDARY_ACTION_KINDS = ("place_colorless_mana", "play_to_base")
AICE_SYNTHETIC_COLORLESS_SKIP_ACTION_KINDS = ("place_colorless_mana", "skip_mana")
AICE_COMBO_PLAN_REQUIRED_LABELS = (
    "base_growth_progress",
    "chimera_colorless_fix",
    "draw_search_setup",
    "stabilize_survival_setup",
    "token_board_setup",
    "combo_piece_preservation",
    "hold_defense_until_combo_setup",
    "combo_execution",
)
AICE_COMBO_PLAN_TARGET_SHAPING_DELTAS: dict[str, dict[str, float]] = {
    "base_growth_progress": {"resourceValue": 0.8},
    "chimera_colorless_fix": {"resourceValue": 1.0},
    "chimera_colorless_partial_fix_with_unfixable_debt": {"resourceValue": 0.25},
    "draw_search_setup": {"planValue": 0.8},
    "stabilize_survival_setup": {"survivalValue": 1.0},
    "token_board_setup": {"tempoValue": 0.7},
    "hold_defense_until_combo_setup": {"survivalValue": 0.8, "planValue": 0.2},
    "combo_piece_preservation": {"planValue": 0.7},
    "combo_execution": {"pressureValue": 1.0, "planValue": 0.8},
    "opponent_resource_risk": {"survivalValue": -0.25, "planValue": -1.0},
    "combo_piece_risk": {"planValue": -1.25},
}

IMMEDIATE_PAYOFF_TARGET_SHAPING_DELTAS: dict[str, dict[str, float]] = {
    "positive_kill_enemy_minion": {"tempoValue": 1.0},
    "positive_face_damage": {"pressureValue": 1.0},
    "positive_force_break": {"pressureValue": 1.0},
    "positive_board_protection": {"survivalValue": 0.8, "tempoValue": 0.3},
    "positive_on_destroy_blocker": {"survivalValue": 0.8, "tempoValue": 0.6, "planValue": 0.4},
    "positive_self_destroy_death_payoff": {"tempoValue": 0.8, "planValue": 0.8},
    "positive_reanimate_from_trash": {"tempoValue": 0.8, "planValue": 0.8},
    "positive_revival_setup": {"planValue": 0.8},
    "negative_no_effect_resource_spend": {"resourceValue": -1.0, "tempoValue": -0.25},
    "negative_exposes_lethal_or_bad_trade": {"survivalValue": -1.5, "tempoValue": -0.5},
}

IMMEDIATE_PAYOFF_POSITIVE_LABELS = (
    "positive_face_damage",
    "positive_force_break",
    "positive_kill_enemy_minion",
    "positive_board_protection",
    "positive_on_destroy_blocker",
    "positive_self_destroy_death_payoff",
    "positive_reanimate_from_trash",
    "positive_revival_setup",
)

IMMEDIATE_PAYOFF_NEGATIVE_LABELS = (
    "negative_exposes_lethal_or_bad_trade",
    "negative_no_effect_resource_spend",
)

IMMEDIATE_PAYOFF_SAFETY_NEGATIVE_FEATURES = (
    "attack_exposes_lethal_next_turn",
    "attack_force_break_unreliable_under_enemy_pressure",
    "attack_while_low_life_no_forces",
    "attack_without_forces_under_enemy_pressure",
    "attack_spends_force_life_exchange_combo_wall",
    "attack_suicide_into_larger_blocker_without_pressure",
    "attack_loses_to_larger_blocker_without_pressure",
    "attack_low_dp_into_larger_blocker",
    "attack_zero_dp_without_attack_payoff",
    "move_field_to_base_exposes_lethal_pressure",
    "move_field_to_base_removes_last_blocker_under_enemy_pressure",
    "block_none_allows_lethal_player_damage",
    "block_none_allows_turn_lethal_player_damage",
)


def extract_aice_mana_boundary_rows(
    rows: Iterable[dict[str, Any]],
    *,
    require_aice: bool = True,
    action_kinds: Iterable[str] = AICE_MANA_BOUNDARY_ACTION_KINDS,
) -> list[dict[str, Any]]:
    """Return decision-local rows for AICE colorless-vs-colored-base mana choices."""
    required_kinds = {str(kind) for kind in action_kinds}
    boundary_rows: list[dict[str, Any]] = []
    for row in rows:
        validate_transition_row(row)
        player_deck_id = str(row.get("playerDeckId") or "").strip().lower()
        if require_aice and "aice" not in player_deck_id:
            continue
        actions = [
            copy.deepcopy(action)
            for action in list(row.get("actions") or [])
            if str(action.get("actionKind") or "") in required_kinds
        ]
        present_kinds = {str(action.get("actionKind") or "") for action in actions}
        if not required_kinds.issubset(present_kinds):
            continue
        boundary = copy.deepcopy(row)
        boundary["rowId"] = f"{row['rowId']}:mana_boundary"
        boundary["actions"] = actions
        tags = {
            *{str(tag) for tag in list(row.get("stateTags") or [])},
            *_aice_mana_boundary_feature_tags(list(row.get("actions") or [])),
        }
        tags.add("mana_boundary")
        if "aice" in player_deck_id:
            tags.add("aice_mana_boundary")
        tags.update(_aice_mana_boundary_feature_tags(actions))
        boundary["stateTags"] = sorted(tags)
        validate_transition_row(boundary)
        boundary_rows.append(boundary)
    return boundary_rows


def extract_aice_synthetic_colorless_skip_boundary_rows(
    rows: Iterable[dict[str, Any]],
    *,
    require_aice: bool = True,
    required_difficulties: Iterable[str] = ("normal",),
    required_firstnesses: Iterable[str] = ("second",),
) -> list[dict[str, Any]]:
    """Return diagnostic AICE colorless-vs-skip rows for trace states without a play-to-base alternative."""
    difficulty_filter = {
        str(difficulty).strip().lower()
        for difficulty in required_difficulties
        if str(difficulty).strip()
    }
    firstness_filter = {
        str(firstness).strip().lower()
        for firstness in required_firstnesses
        if str(firstness).strip().lower() in {"first", "second"}
    }
    synthetic_rows: list[dict[str, Any]] = []
    for row in rows:
        validate_transition_row(row)
        player_deck_id = str(row.get("playerDeckId") or "").strip().lower()
        if require_aice and "aice" not in player_deck_id:
            continue
        difficulty = str(row.get("opponentKind") or "").strip().lower()
        if difficulty_filter and difficulty not in difficulty_filter:
            continue
        firstness = _row_firstness(row)
        if firstness_filter and firstness not in firstness_filter:
            continue

        all_actions = list(row.get("actions") or [])
        if any(str(action.get("actionKind") or "") == "play_to_base" for action in all_actions):
            continue
        actions = [
            copy.deepcopy(action)
            for action in all_actions
            if str(action.get("actionKind") or "") in AICE_SYNTHETIC_COLORLESS_SKIP_ACTION_KINDS
        ]
        present_kinds = {str(action.get("actionKind") or "") for action in actions}
        if not set(AICE_SYNTHETIC_COLORLESS_SKIP_ACTION_KINDS).issubset(present_kinds):
            continue
        colorless_action_ids = {
            str(action.get("actionId") or "")
            for action in actions
            if str(action.get("actionKind") or "") == "place_colorless_mana"
        }
        chosen_action_ids = {
            str(row.get("humanChosenActionId") or ""),
            str(row.get("battleChosenActionId") or ""),
        }
        if not any(action_id and action_id in colorless_action_ids for action_id in chosen_action_ids):
            continue

        boundary = copy.deepcopy(row)
        boundary["rowId"] = f"{row['rowId']}:synthetic_colorless_skip_boundary"
        boundary["actions"] = actions
        boundary["syntheticCounterfactual"] = True
        boundary["syntheticCounterfactualKind"] = "aice_colorless_vs_skip_mana_boundary"
        boundary["syntheticSourceRowId"] = str(row.get("rowId") or "")
        boundary["syntheticSourceActionKinds"] = sorted(present_kinds)
        tags = {
            *{str(tag) for tag in list(row.get("stateTags") or [])},
            *_aice_mana_boundary_feature_tags(all_actions),
        }
        tags.update({
            "mana_boundary",
            "aice_synthetic_mana_boundary",
            "aice_synthetic_colorless_vs_skip_boundary",
            "diagnostic_only",
            "synthetic_counterfactual",
        })
        if "aice" in player_deck_id:
            tags.add("aice_mana_boundary")
        tags.update(_aice_mana_boundary_feature_tags(actions))
        boundary["stateTags"] = sorted(tags)
        validate_transition_row(boundary)
        synthetic_rows.append(boundary)
    return synthetic_rows


def _aice_mana_boundary_feature_tags(actions: list[dict[str, Any]]) -> set[str]:
    tags: set[str] = set()
    for action in actions:
        features = dict(action.get("actionFeatures") or {})
        if float(features.get("place_colorless_mana_supports_chimera_color_fix", 0.0) or 0.0) > 0.0:
            tags.add("mana_boundary_chimera_colorless_support")
        if (
            float(features.get("place_colorless_mana_ignores_missing_hand_color", 0.0) or 0.0) > 0.0
            or float(features.get("play_to_base_restores_missing_unfixable_hand_color", 0.0) or 0.0) > 0.0
        ):
            tags.add("mana_boundary_unfixable_color_debt")
        if float(features.get("play_to_base_matches_only_chimera_fixable_hand_color", 0.0) or 0.0) > 0.0:
            tags.add("mana_boundary_only_chimera_fixable_color")
        if float(features.get("play_to_base_spends_chimera_fixable_field_minion", 0.0) or 0.0) > 0.0:
            tags.add("mana_boundary_spends_chimera_fixable_field_minion")
    return tags


def aice_mana_boundary_coverage_report(
    rows: Iterable[dict[str, Any]],
    *,
    required_difficulties: Iterable[str] = ("easy", "normal", "deep"),
    required_sides: Iterable[str] = ("P1", "P2"),
    required_firstnesses: Iterable[str] = ("first", "second"),
    min_rows_per_difficulty_side: int = 2,
    min_unfixable_rows_per_difficulty_side: int = 1,
    min_chimera_support_rows_per_difficulty_side: int = 1,
) -> dict[str, Any]:
    boundary_rows = list(rows)
    difficulties = [str(item).strip().lower() for item in required_difficulties if str(item).strip()]
    sides = [str(item).strip().upper() for item in required_sides if str(item).strip()]
    firstnesses = [
        str(item).strip().lower()
        for item in required_firstnesses
        if str(item).strip().lower() in {"first", "second"}
    ]
    required_side_keys = [f"{difficulty}|{side}" for difficulty in difficulties for side in sides]
    required_firstness_keys = [f"{difficulty}|{firstness}" for difficulty in difficulties for firstness in firstnesses]
    min_rows = max(0, int(min_rows_per_difficulty_side))
    min_unfixable = max(0, int(min_unfixable_rows_per_difficulty_side))
    min_chimera_support = max(0, int(min_chimera_support_rows_per_difficulty_side))
    counts_by_side: dict[str, int] = {}
    unfixable_counts_by_side: dict[str, int] = {}
    chimera_support_counts_by_side: dict[str, int] = {}
    only_chimera_counts_by_side: dict[str, int] = {}
    counts_by_firstness: dict[str, int] = {}
    unfixable_counts_by_firstness: dict[str, int] = {}
    chimera_support_counts_by_firstness: dict[str, int] = {}
    only_chimera_counts_by_firstness: dict[str, int] = {}
    unknown_firstness_rows: list[str] = []
    for row in boundary_rows:
        difficulty = str(row.get("opponentKind") or "").strip().lower()
        side = str(row.get("modelSide") or "").strip().upper()
        if not difficulty or not side:
            continue
        side_key = f"{difficulty}|{side}"
        counts_by_side[side_key] = counts_by_side.get(side_key, 0) + 1
        firstness = _row_firstness(row)
        firstness_key = f"{difficulty}|{firstness}" if firstness in {"first", "second"} else ""
        if firstness_key:
            counts_by_firstness[firstness_key] = counts_by_firstness.get(firstness_key, 0) + 1
        else:
            unknown_firstness_rows.append(str(row.get("rowId") or ""))
        tags = {
            *{str(tag) for tag in list(row.get("stateTags") or [])},
            *_aice_mana_boundary_feature_tags(list(row.get("actions") or [])),
        }
        if "mana_boundary_unfixable_color_debt" in tags:
            unfixable_counts_by_side[side_key] = unfixable_counts_by_side.get(side_key, 0) + 1
            if firstness_key:
                unfixable_counts_by_firstness[firstness_key] = unfixable_counts_by_firstness.get(firstness_key, 0) + 1
        if "mana_boundary_chimera_colorless_support" in tags:
            chimera_support_counts_by_side[side_key] = chimera_support_counts_by_side.get(side_key, 0) + 1
            if firstness_key:
                chimera_support_counts_by_firstness[firstness_key] = (
                    chimera_support_counts_by_firstness.get(firstness_key, 0) + 1
                )
        if "mana_boundary_only_chimera_fixable_color" in tags:
            only_chimera_counts_by_side[side_key] = only_chimera_counts_by_side.get(side_key, 0) + 1
            if firstness_key:
                only_chimera_counts_by_firstness[firstness_key] = (
                    only_chimera_counts_by_firstness.get(firstness_key, 0) + 1
                )
    missing_difficulty_sides = [
        key for key in required_side_keys if counts_by_side.get(key, 0) < min_rows
    ]
    missing_unfixable_sides = [
        key for key in required_side_keys if unfixable_counts_by_side.get(key, 0) < min_unfixable
    ]
    missing_chimera_support_sides = [
        key for key in required_side_keys if chimera_support_counts_by_side.get(key, 0) < min_chimera_support
    ]
    missing_difficulty_firstness = [
        key for key in required_firstness_keys if counts_by_firstness.get(key, 0) < min_rows
    ]
    missing_unfixable_firstness = [
        key for key in required_firstness_keys if unfixable_counts_by_firstness.get(key, 0) < min_unfixable
    ]
    missing_chimera_support_firstness = [
        key for key in required_firstness_keys if chimera_support_counts_by_firstness.get(key, 0) < min_chimera_support
    ]
    recommended_plan: list[dict[str, Any]] = []
    for key in missing_difficulty_firstness:
        difficulty, firstness = key.split("|", 1)
        recommended_plan.append({
            "reason": "missing_boundary_difficulty_firstness",
            "difficulty": difficulty,
            "playerFirstness": firstness,
            "currentBoundaryRows": int(counts_by_firstness.get(key, 0)),
            "targetBoundaryRows": int(min_rows),
        })
    missing_difficulty_firstness_set = set(missing_difficulty_firstness)
    for key in missing_unfixable_firstness:
        if key in missing_difficulty_firstness_set:
            continue
        difficulty, firstness = key.split("|", 1)
        recommended_plan.append({
            "reason": "missing_unfixable_color_debt_boundary_firstness",
            "difficulty": difficulty,
            "playerFirstness": firstness,
            "currentUnfixableColorDebtRows": int(unfixable_counts_by_firstness.get(key, 0)),
            "targetUnfixableColorDebtRows": int(min_unfixable),
        })
    for key in missing_chimera_support_firstness:
        if key in missing_difficulty_firstness_set:
            continue
        difficulty, firstness = key.split("|", 1)
        recommended_plan.append({
            "reason": "missing_chimera_colorless_support_boundary_firstness",
            "difficulty": difficulty,
            "playerFirstness": firstness,
            "currentChimeraColorlessSupportRows": int(chimera_support_counts_by_firstness.get(key, 0)),
            "targetChimeraColorlessSupportRows": int(min_chimera_support),
        })
    passed = (
        not missing_difficulty_firstness
        and not missing_unfixable_firstness
        and not missing_chimera_support_firstness
        and not unknown_firstness_rows
    )
    failure_reasons: list[str] = []
    if missing_difficulty_firstness:
        failure_reasons.append("missing_boundary_difficulty_firstness")
    if missing_unfixable_firstness:
        failure_reasons.append("missing_unfixable_color_debt_boundary_firstness")
    if missing_chimera_support_firstness:
        failure_reasons.append("missing_chimera_colorless_support_boundary_firstness")
    if unknown_firstness_rows:
        failure_reasons.append("unknown_boundary_firstness")
    return {
        "kind": "aice_mana_boundary_coverage",
        "boundaryRowCount": len(boundary_rows),
        "requiredDifficulties": difficulties,
        "requiredSides": sides,
        "requiredFirstnesses": firstnesses,
        "minRowsPerDifficultySide": min_rows,
        "minUnfixableRowsPerDifficultySide": min_unfixable,
        "minChimeraSupportRowsPerDifficultySide": min_chimera_support,
        "countsByDifficultySide": dict(sorted(counts_by_side.items())),
        "unfixableColorDebtCountsByDifficultySide": dict(sorted(unfixable_counts_by_side.items())),
        "chimeraColorlessSupportCountsByDifficultySide": dict(sorted(chimera_support_counts_by_side.items())),
        "onlyChimeraFixableCountsByDifficultySide": dict(sorted(only_chimera_counts_by_side.items())),
        "countsByDifficultyFirstness": dict(sorted(counts_by_firstness.items())),
        "unfixableColorDebtCountsByDifficultyFirstness": dict(sorted(unfixable_counts_by_firstness.items())),
        "chimeraColorlessSupportCountsByDifficultyFirstness": dict(sorted(chimera_support_counts_by_firstness.items())),
        "onlyChimeraFixableCountsByDifficultyFirstness": dict(sorted(only_chimera_counts_by_firstness.items())),
        "missingDifficultySides": missing_difficulty_sides,
        "missingUnfixableColorDebtDifficultySides": missing_unfixable_sides,
        "missingChimeraColorlessSupportDifficultySides": missing_chimera_support_sides,
        "missingDifficultyFirstness": missing_difficulty_firstness,
        "missingUnfixableColorDebtDifficultyFirstness": missing_unfixable_firstness,
        "missingChimeraColorlessSupportDifficultyFirstness": missing_chimera_support_firstness,
        "unknownFirstnessRowIds": [row_id for row_id in unknown_firstness_rows if row_id],
        "recommendedCollectionPlan": recommended_plan,
        "failureReasons": failure_reasons,
        "passedCoverageGate": passed,
    }


def _row_firstness(row: dict[str, Any]) -> str:
    raw_firstness = (
        row.get("tracePlayerFirstness")
        or row.get("playerFirstness")
        or row.get("player_firstness")
        or row.get("learnerFirstness")
    )
    firstness = str(raw_firstness or "").strip().lower()
    if firstness in {"first", "second"}:
        return firstness
    features = dict(row.get("beforeStateFeatures") or {})
    try:
        if float(features.get("learner_is_first_player", 0.0) or 0.0) > 0.5:
            return "first"
        if float(features.get("learner_is_second_player", 0.0) or 0.0) > 0.5:
            return "second"
    except (TypeError, ValueError):
        return "unknown"
    return "unknown"


def immediate_payoff_action_labels(row: dict[str, Any], action: dict[str, Any]) -> list[str]:
    """Return action-level immediate payoff labels from features, rollout deltas, and targets."""
    features = dict(action.get("actionFeatures") or {})
    targets = dict(action.get("targets") or {})
    summary = dict(action.get("rolloutSummary") or {})
    action_kind = str(action.get("actionKind") or "")

    def positive_feature(key: str) -> bool:
        try:
            return float(features.get(key, 0.0) or 0.0) > 0.0
        except (TypeError, ValueError):
            return False

    def numeric(source: dict[str, Any], key: str) -> float:
        try:
            return float(source.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    labels: set[str] = set()
    enemy_life_delta = numeric(summary, "enemyLifeDelta")
    enemy_force_life_delta = numeric(summary, "enemyForceLifeDelta")
    enemy_field_delta = numeric(summary, "enemyFieldDelta")
    enemy_ready_dp_delta = numeric(summary, "enemyReadyDpDelta")
    pressure_value = numeric(targets, "pressureValue")
    positive_pressure = pressure_value > 0.0
    rollout_pressure_action = action_kind in {"attack", "play_card", "activate_flash_ability"}
    rollout_board_combat_action = action_kind in {
        "attack",
        "blocker",
        "play_card",
        "activate_flash_ability",
    }
    base_to_field_pressure_plan_asset = (
        action_kind == "move_card"
        and positive_feature("move_base_to_field")
        and positive_feature("move_base_to_field_protects_minion")
        and positive_feature("move_base_to_field_value")
        and positive_feature("move_base_to_field_mana_color:colorless")
        and not positive_feature("move_base_to_field_colored_mana")
        and (
            positive_feature("own_deck_plan:pressure")
            or positive_feature("own_deck_archetype:force_break")
            or positive_feature("enemy_pressure_high_player_risk")
            or positive_feature("enemy_pressure_near_player_lethal")
        )
    )
    fragile_base_to_field_no_payoff = (
        action_kind == "move_card"
        and positive_feature("move_base_to_field")
        and any(positive_feature(key) for key in (
            "move_card_profile_zone:usually_should_not_attack",
            "move_card_semantic_zone:usually_should_not_attack",
            "move_card_profile_risk:zero_dp_attacker",
            "move_card_semantic_risk:zero_dp_attacker",
            "move_card_profile_risk:low_bp_attacker",
            "move_card_semantic_risk:low_bp_attacker",
        ))
        and not any(positive_feature(key) for key in (
            "move_base_to_field_can_block",
            "move_base_to_field_under_observed_aggression_defense_need",
            "move_base_to_field_immediate_attack_payoff",
        ))
        and not base_to_field_pressure_plan_asset
        and not (
            positive_feature("move_base_to_field_can_attack_player")
            and not any(positive_feature(key) for key in (
                "move_card_profile_zone:usually_should_not_attack",
                "move_card_semantic_zone:usually_should_not_attack",
                "move_card_profile_risk:zero_dp_attacker",
                "move_card_semantic_risk:zero_dp_attacker",
            ))
        )
    )
    base_to_field_defense_need = (
        positive_feature("move_base_to_field_under_observed_aggression_defense_need")
        or positive_feature("enemy_pressure_high_player_risk")
        or positive_feature("enemy_pressure_near_player_lethal")
        or numeric(features, "enemy_field_dp_pressure") >= 0.5
    )
    base_to_field_has_direct_payoff = (
        positive_feature("move_base_to_field_immediate_attack_payoff")
        or base_to_field_pressure_plan_asset
        or (
            positive_feature("move_base_to_field_can_block")
            and base_to_field_defense_need
        )
    )
    productive_base_to_field_protection = (
        action_kind == "move_card"
        and positive_feature("move_base_to_field")
        and positive_feature("move_base_to_field_protects_minion")
        and positive_feature("move_base_to_field_value")
        and base_to_field_has_direct_payoff
        and not fragile_base_to_field_no_payoff
    )

    if (
        (rollout_pressure_action and enemy_life_delta < -1e-6)
        or positive_feature("attack_has_lethal_player_target")
    ):
        labels.add("positive_face_damage")
    direct_force_life_effect = any(
        positive_feature(key)
        for key in (
            "play_card_effect:exchange_player_force_life",
            "play_card_exchange_player_force_life",
            "play_card_force_life_exchange_sets_enemy_low_life",
        )
    )
    rollout_force_break_action = action_kind in {"play_card", "activate_flash_ability"} and direct_force_life_effect
    if (
        (rollout_force_break_action and enemy_force_life_delta < -1e-6)
        or (
            positive_feature("attack_can_destroy_force")
            and (
                not positive_feature("attack_force_break_unreliable_under_enemy_pressure")
                or enemy_force_life_delta < -1e-6
            )
        )
        or positive_feature("target_lethal_force")
    ):
        labels.add("positive_force_break")
    if rollout_board_combat_action and (
        enemy_field_delta < -1e-6
        or (enemy_ready_dp_delta < -1e-6 and enemy_field_delta <= 1e-6)
    ):
        labels.add("positive_kill_enemy_minion")
    if positive_feature("positive_on_destroy_blocker"):
        labels.add("positive_on_destroy_blocker")
    if positive_feature("positive_self_destroy_death_payoff"):
        labels.add("positive_self_destroy_death_payoff")
    if positive_feature("positive_reanimate_from_trash"):
        labels.add("positive_reanimate_from_trash")
    revival_base_to_field_setup = (
        action_kind == "move_card"
        and positive_feature("move_base_to_field_own_revival_candidate")
        and max(
            numeric(targets, "transitionValue"),
            numeric(targets, "planValue"),
            numeric(targets, "tempoValue"),
            numeric(targets, "pressureValue"),
            numeric(targets, "survivalValue"),
        )
        > 1e-6
    )
    if revival_base_to_field_setup:
        labels.add("positive_revival_setup")
    protected_death_payoff_field_to_base = (
        action_kind == "move_card"
        and positive_feature("move_field_to_base")
        and positive_feature("move_field_to_base_protects_high_value_attacker")
        and not positive_feature("move_field_to_base_exposes_lethal_pressure")
        and (
            positive_feature("move_card_profile_role:death_payoff")
            or positive_feature("move_card_semantic_role:death_payoff")
        )
        and any(positive_feature(key) for key in (
            "move_field_to_base_builds_mana",
            "move_field_to_base_under_curve",
            "move_field_to_base_future_play",
            "move_field_to_base_enables_playable_hand_card",
            "move_field_to_base_matches_hand_color",
            "move_field_to_base_restores_missing_hand_color",
            "move_field_to_base_resource_engine",
        ))
    )
    protective_board_action = (
        (
            productive_base_to_field_protection
        )
        or (
            action_kind == "play_card"
            and positive_feature("positive_add_blocker_under_pressure")
        )
        or protected_death_payoff_field_to_base
    )
    if protective_board_action:
        labels.add("positive_board_protection")

    if (
        any(positive_feature(key) for key in IMMEDIATE_PAYOFF_SAFETY_NEGATIVE_FEATURES)
        and not protected_death_payoff_field_to_base
    ):
        labels.add("negative_exposes_lethal_or_bad_trade")

    spends_resource = action_kind in {
        "play_card",
        "activate_flash_ability",
        "move_card",
        "swap_mana_color",
        "place_colorless_mana",
    }
    feature_marked_no_effect_spend = positive_feature("negative_no_effect_resource_spend")
    explicit_no_effect = fragile_base_to_field_no_payoff or any(
        positive_feature(key) for key in (
            "play_card_target_effect_no_eligible_targets",
            "play_card_beneficial_no_own_target",
            "play_card_summon_from_trash_no_own_target",
            "play_card_beneficial_only_enemy_target",
            "play_card_harmful_no_enemy_target",
            "play_card_harmful_target_only_own",
            "move_base_to_field_low_impact_mana_minion",
            "move_base_to_field_spends_ready_mana",
            "move_base_to_field_with_playable_hand",
            "move_base_to_field_colored_mana",
            "swap_mana_delays_base_growth",
            "place_colorless_mana_ignores_missing_hand_color",
        )
    )
    optional_zero_target_development = any(positive_feature(key) for key in (
        "play_card_effect:place_base_from_hand",
        "play_card_place_base_from_hand_support",
        "play_card_base_development_support",
        "play_card_base_search_support",
        "play_card_force_life_exchange_search_support",
        "play_card_force_life_exchange_search_for_deck_piece",
    ))
    if (
        feature_marked_no_effect_spend
        and not any(label.startswith("positive_") for label in labels)
    ):
        labels.add("negative_no_effect_resource_spend")
    if (
        spends_resource
        and explicit_no_effect
        and not optional_zero_target_development
        and not protective_board_action
        and not any(label.startswith("positive_") for label in labels)
    ):
        labels.add("negative_no_effect_resource_spend")
    if spends_resource and not any(label.startswith("positive_") for label in labels):
        positive_components = (
            numeric(targets, "terminalValue"),
            numeric(targets, "survivalValue"),
            numeric(targets, "pressureValue"),
            numeric(targets, "planValue"),
            numeric(targets, "tempoValue"),
            numeric(targets, "resourceValue"),
        )
        no_positive_target = max(positive_components) <= 1e-6 and not positive_pressure
        if (
            explicit_no_effect
            and not optional_zero_target_development
            and not protective_board_action
        ) or no_positive_target:
            labels.add("negative_no_effect_resource_spend")

    return sorted(labels)


def _action_feature_positive(action: dict[str, Any], key: str) -> bool:
    try:
        return float(dict(action.get("actionFeatures") or {}).get(key, 0.0) or 0.0) > 0.0
    except (TypeError, ValueError):
        return False


def immediate_payoff_positive_labels(row: dict[str, Any], action: dict[str, Any]) -> list[str]:
    labels = set(immediate_payoff_action_labels(row, action))
    return sorted(label for label in labels if label in IMMEDIATE_PAYOFF_POSITIVE_LABELS)


def immediate_payoff_negative_labels(row: dict[str, Any], action: dict[str, Any]) -> list[str]:
    labels = set(immediate_payoff_action_labels(row, action))
    return sorted(label for label in labels if label in IMMEDIATE_PAYOFF_NEGATIVE_LABELS)


def immediate_payoff_action_has_safety_negative(row: dict[str, Any], action: dict[str, Any]) -> bool:
    labels = set(immediate_payoff_action_labels(row, action))
    if "negative_exposes_lethal_or_bad_trade" in labels:
        return True
    return any(_action_feature_positive(action, key) for key in IMMEDIATE_PAYOFF_SAFETY_NEGATIVE_FEATURES)


def immediate_payoff_action_has_nonnegative_payoff(row: dict[str, Any], action: dict[str, Any]) -> bool:
    if immediate_payoff_action_has_safety_negative(row, action):
        return False
    if "negative_no_effect_resource_spend" in immediate_payoff_action_labels(row, action):
        return False
    if immediate_payoff_positive_labels(row, action):
        return True
    if (
        _action_feature_positive(action, "attack_can_destroy_force")
        and not _action_feature_positive(action, "attack_force_break_unreliable_under_enemy_pressure")
    ):
        return True
    return any(_action_feature_positive(action, key) for key in (
        "attack_has_lethal_player_target",
        "attack_has_attack_payoff",
        "move_base_to_field_immediate_attack_payoff",
        "place_colorless_mana_supports_chimera_color_fix",
        "swap_mana_fallback_unsticks_hand",
        "swap_mana_enables_playable_hand_card",
        "play_card_rest_lockdown_enemy_ready_targets",
    ))


def immediate_payoff_safety_conflict_regression(
    row: dict[str, Any],
    baseline_action: dict[str, Any],
    selected_action: dict[str, Any],
) -> bool:
    """Return true when a safety-negative selected action overrides a positive safe baseline."""
    if str(baseline_action.get("actionId")) == str(selected_action.get("actionId")):
        return False
    if _action_feature_positive(selected_action, "attack_has_lethal_player_target"):
        return False
    if not immediate_payoff_action_has_safety_negative(row, selected_action):
        return False
    if immediate_payoff_action_has_safety_negative(row, baseline_action):
        return False
    return immediate_payoff_action_has_nonnegative_payoff(row, baseline_action)


def immediate_payoff_lost_positive_labels(
    row: dict[str, Any],
    baseline_action: dict[str, Any],
    selected_action: dict[str, Any],
) -> list[str]:
    baseline_labels = set(immediate_payoff_positive_labels(row, baseline_action))
    selected_labels = set(immediate_payoff_positive_labels(row, selected_action))
    return sorted(baseline_labels - selected_labels)


def _action_set_choice_regression_reasons(
    row: dict[str, Any],
    baseline_action: dict[str, Any],
    selected_action: dict[str, Any],
    *,
    value_tolerance: float,
) -> tuple[list[str], list[str], float]:
    if str(baseline_action.get("actionId")) == str(selected_action.get("actionId")):
        return [], [], 0.0
    old_negative = bool(immediate_payoff_negative_labels(row, baseline_action))
    new_negative = bool(immediate_payoff_negative_labels(row, selected_action))
    introduced_negative = bool(new_negative and not old_negative)
    safety_conflict = immediate_payoff_safety_conflict_regression(row, baseline_action, selected_action)
    lost_positive_labels = immediate_payoff_lost_positive_labels(row, baseline_action, selected_action)
    target_delta = _transition_action_value(selected_action) - _transition_action_value(baseline_action)
    target_regressed = target_delta < -float(value_tolerance)
    reasons: list[str] = []
    if introduced_negative:
        reasons.append("introduced_negative_action")
    if safety_conflict:
        reasons.append("safety_conflict_regression")
    if lost_positive_labels:
        reasons.append("lost_positive_action")
    if target_regressed:
        reasons.append("target_value_regression")
    return reasons, lost_positive_labels, float(target_delta)


def _baseline_constrained_action_set_top1_index(
    row: dict[str, Any],
    actions: list[dict[str, Any]],
    scores: list[float],
    *,
    baseline_index: int,
    value_tolerance: float,
) -> tuple[int, list[str]]:
    ranked_indexes = sorted(
        range(len(actions)),
        key=lambda index: (float(scores[index]), -index),
        reverse=True,
    )
    raw_top_index = ranked_indexes[0] if ranked_indexes else int(baseline_index)
    baseline_action = actions[int(baseline_index)]
    raw_top_reasons: list[str] = []
    for index in ranked_indexes:
        reasons, _lost_positive, _target_delta = _action_set_choice_regression_reasons(
            row,
            baseline_action,
            actions[index],
            value_tolerance=float(value_tolerance),
        )
        if int(index) == int(raw_top_index):
            raw_top_reasons = reasons
        if not reasons:
            return int(index), raw_top_reasons
    return int(baseline_index), raw_top_reasons


def immediate_payoff_label_report(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarise transition rows by immediate payoff labels."""
    materialized_rows = list(rows)
    label_counts: Counter[str] = Counter()
    chosen_label_counts: Counter[str] = Counter()
    action_kind_counts_by_label: dict[str, Counter[str]] = {}
    counts_by_label_difficulty_side: dict[str, Counter[str]] = {}
    unlabeled_resource_spend_action_count = 0
    action_count = 0
    chosen_action_count = 0
    for row in materialized_rows:
        validate_transition_row(row)
        difficulty = str(row.get("opponentKind") or "unknown")
        side = str(row.get("modelSide") or "unknown")
        difficulty_side = f"{difficulty}|{side}"
        chosen_ids = {
            str(value)
            for value in (
                row.get("humanChosenActionId"),
                row.get("battleChosenActionId"),
            )
            if value is not None
        }
        for action in list(row.get("actions") or []):
            action_count += 1
            action_kind = str(action.get("actionKind") or "")
            labels = immediate_payoff_action_labels(row, action)
            if action_kind in {
                "play_card",
                "activate_flash_ability",
                "move_card",
                "swap_mana_color",
                "place_colorless_mana",
            } and not labels:
                unlabeled_resource_spend_action_count += 1
            if str(action.get("actionId")) in chosen_ids:
                chosen_action_count += 1
            for label in labels:
                label_counts[label] += 1
                action_kind_counts_by_label.setdefault(label, Counter())[action_kind] += 1
                counts_by_label_difficulty_side.setdefault(label, Counter())[difficulty_side] += 1
                if str(action.get("actionId")) in chosen_ids:
                    chosen_label_counts[label] += 1
    required_labels = sorted(IMMEDIATE_PAYOFF_TARGET_SHAPING_DELTAS)
    missing_labels = [label for label in required_labels if label_counts.get(label, 0) <= 0]
    return {
        "kind": "immediate_payoff_label_report",
        "rowCount": len(materialized_rows),
        "actionCount": int(action_count),
        "chosenActionCount": int(chosen_action_count),
        "labelCounts": dict(sorted(label_counts.items())),
        "chosenLabelCounts": dict(sorted(chosen_label_counts.items())),
        "actionKindCountsByLabel": {
            label: dict(sorted(counter.items()))
            for label, counter in sorted(action_kind_counts_by_label.items())
        },
        "countsByLabelDifficultySide": {
            label: dict(sorted(counter.items()))
            for label, counter in sorted(counts_by_label_difficulty_side.items())
        },
        "unlabeledResourceSpendActionCount": int(unlabeled_resource_spend_action_count),
        "requiredLabels": required_labels,
        "missingRequiredLabels": missing_labels,
        "passedRequiredLabelPresence": not missing_labels,
    }


def apply_immediate_payoff_target_shaping(
    rows: Iterable[dict[str, Any]],
    *,
    label_component_deltas: dict[str, dict[str, float]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shape transition targets from immediate payoff labels."""
    deltas_by_label = {
        str(label): {
            str(component): float(delta)
            for component, delta in dict(component_deltas).items()
            if str(component) in TARGET_COMPONENT_KEYS and float(delta) != 0.0
        }
        for label, component_deltas in dict(
            label_component_deltas or IMMEDIATE_PAYOFF_TARGET_SHAPING_DELTAS
        ).items()
    }
    shaped_rows: list[dict[str, Any]] = []
    label_counts: Counter[str] = Counter()
    component_delta_sums: Counter[str] = Counter()
    row_count = 0
    shaped_row_count = 0
    shaped_action_count = 0
    action_count = 0
    for row in rows:
        validate_transition_row(row)
        row_count += 1
        shaped = copy.deepcopy(row)
        row_tags = {str(tag) for tag in list(shaped.get("stateTags") or [])}
        row_was_shaped = False
        for action in list(shaped.get("actions") or []):
            action_count += 1
            labels = [
                label
                for label in immediate_payoff_action_labels(shaped, action)
                if label in deltas_by_label and deltas_by_label[label]
            ]
            if not labels:
                continue
            targets = dict(action.get("targets") or {})
            action_component_deltas: Counter[str] = Counter()
            for label in labels:
                label_counts[label] += 1
                for component, delta in deltas_by_label[label].items():
                    targets[component] = float(targets.get(component, 0.0) or 0.0) + float(delta)
                    action_component_deltas[component] += float(delta)
                    component_delta_sums[component] += float(delta)
            targets["immediatePayoffTargetShaping"] = {
                "labels": sorted(labels),
                "componentDeltas": dict(sorted(action_component_deltas.items())),
            }
            targets["transitionValue"] = transition_value_from_targets(targets)
            action["targets"] = targets
            shaped_action_count += 1
            row_was_shaped = True
        if row_was_shaped:
            row_tags.add("immediate_payoff_target_shaping")
            shaped["stateTags"] = sorted(row_tags)
            shaped_row_count += 1
        validate_transition_row(shaped)
        shaped_rows.append(shaped)
    return shaped_rows, {
        "kind": "immediate_payoff_target_shaping",
        "rowCount": int(row_count),
        "actionCount": int(action_count),
        "shapedRowCount": int(shaped_row_count),
        "shapedActionCount": int(shaped_action_count),
        "labelComponentDeltas": {
            label: dict(sorted(component_deltas.items()))
            for label, component_deltas in sorted(deltas_by_label.items())
        },
        "labelCounts": dict(sorted(label_counts.items())),
        "componentDeltaSums": dict(sorted(component_delta_sums.items())),
    }


def aice_combo_plan_action_labels(row: dict[str, Any], action: dict[str, Any]) -> list[str]:
    """Return action-level AICE combo-plan labels inferred from existing features."""
    features = dict(action.get("actionFeatures") or {})
    action_kind = str(action.get("actionKind") or "")
    is_play_action = action_kind in {"play_card", "activate_flash_ability"}
    is_move_action = action_kind == "move_card"
    is_play_to_base_action = action_kind == "play_to_base"

    def positive(key: str) -> bool:
        try:
            return float(features.get(key, 0.0) or 0.0) > 0.0
        except (TypeError, ValueError):
            return False

    def any_positive(keys: Iterable[str]) -> bool:
        return any(positive(key) for key in keys)

    targets = dict(action.get("targets") or {})

    def target_value(key: str) -> float:
        try:
            return float(targets.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    labels: set[str] = set()
    if (
        (
            is_play_action
            and any_positive((
                "semantic_action_plan:base_growth",
                "semantic_action_resource:base_development",
                "play_card_base_development_support",
                "play_card_early_base_development_support",
                "play_card_place_base_from_hand_support",
                "play_card_effect:move_to_base_rested",
                "play_card_effect:place_base_from_hand",
            ))
        )
        or (
            is_move_action
            and any_positive((
                "move_field_to_base_builds_mana",
                "move_field_to_base_under_curve",
            ))
        )
        or (
            is_play_to_base_action
            and any_positive((
                "play_to_base_restores_missing_hand_color",
                "play_to_base_restores_missing_unfixable_hand_color",
                "play_card_profile_zone:good_mana_card",
                "play_card_semantic_zone:good_mana_card",
            ))
        )
    ):
        labels.add("base_growth_progress")
    if positive("place_colorless_mana_supports_chimera_color_fix"):
        if positive("place_colorless_mana_ignores_missing_hand_color"):
            labels.add("chimera_colorless_partial_fix_with_unfixable_debt")
        else:
            labels.add("chimera_colorless_fix")
    if (
        is_play_action
        and any_positive((
            "play_card_base_search_support",
            "play_card_effect:search_deck_to_hand",
            "play_card_effect:look_top_to_hand",
            "play_card_effect:draw_cards_self_only",
            "play_card_effect:draw_cards_both_players",
            "play_card_force_life_exchange_search_support",
            "play_card_force_life_exchange_search_for_deck_piece",
            "play_card_profile_role:draw",
            "play_card_semantic_role:draw",
        ))
    ) or (
        is_move_action
        and positive("move_card_effect:search_deck_to_hand")
    ):
        labels.add("draw_search_setup")
    if is_play_action and positive("play_card_effect:heal_targets"):
        labels.add("stabilize_survival_setup")
    if is_play_action and positive("play_card_effect:create_tokens"):
        labels.add("token_board_setup")
    if (
        is_play_action
        and any_positive((
            "play_card_force_life_exchange_search_for_deck_piece",
            "play_card_force_life_exchange_search_support",
            "play_card_effect:search_deck_to_hand",
        ))
    ) or (
        is_move_action
        and positive("move_card_effect:search_deck_to_hand")
    ):
        labels.add("combo_piece_preservation")
    if is_play_action and any_positive((
        "play_card_effect:exchange_player_force_life",
        "play_card_exchange_player_force_life",
        "play_card_force_life_exchange_sets_enemy_low_life",
        "play_card_force_life_exchange_has_followup_damage",
        "play_card_force_life_exchange_search_for_deck_piece",
    )):
        labels.add("combo_execution")
    if is_play_action and any_positive((
        "play_card_risk:gives_opponent_card",
        "play_card_effect:draw_cards_both_players",
    )):
        labels.add("opponent_resource_risk")
    if (
        any_positive((
            "end_turn_under_observed_aggression_defense_need",
            "play_minion_under_observed_aggression_defense_need",
            "move_base_to_field_under_observed_aggression_defense_need",
            "move_base_to_field_can_block",
            "play_card_defensive_reactive_on_enemy_turn",
            "play_card_defensive_reactive_attack_payoff",
        ))
        or (
            action_kind == "end_turn"
            and any_positive(("own_deck_plan:hold_defense", "own_deck_semantic_plan:hold_defense"))
            and positive("enemy_field_dp_pressure")
            and positive("own_ready_field_dp_total")
        )
        or (
            action_kind == "end_turn"
            and any_positive(("own_deck_plan:hold_defense", "own_deck_semantic_plan:hold_defense"))
            and target_value("observedFutureValue") > 0.0
            and (
                target_value("terminalValue") > 0.0
                or target_value("transitionValue") >= 0.0
            )
        )
    ):
        labels.add("hold_defense_until_combo_setup")
    if any_positive((
        "semantic_action_risk:breaks_life_exchange_plan",
        "move_field_to_base_spends_force_life_exchange_wall",
        "attack_spends_force_life_exchange_combo_wall",
        "move_base_to_field_delays_force_life_exchange",
    )):
        labels.add("combo_piece_risk")
    return sorted(labels)


def aice_combo_plan_label_report(
    rows: Iterable[dict[str, Any]],
    *,
    require_aice: bool = True,
) -> dict[str, Any]:
    """Summarise AICE trace transition rows by explicit combo-plan action labels."""
    materialized_rows = list(rows)
    label_counts: Counter[str] = Counter()
    chosen_label_counts: Counter[str] = Counter()
    action_kind_counts: Counter[str] = Counter()
    chosen_action_kind_counts: Counter[str] = Counter()
    counts_by_label_difficulty_firstness: dict[str, Counter[str]] = {}
    action_kind_counts_by_label: dict[str, Counter[str]] = {}
    row_counts_by_difficulty_firstness: Counter[str] = Counter()
    unlabeled_action_count = 0
    unlabeled_human_chosen_action_count = 0
    aice_row_count = 0
    action_count = 0
    human_chosen_action_count = 0

    for row in materialized_rows:
        validate_transition_row(row)
        player_deck_id = str(row.get("playerDeckId") or "").strip().lower()
        if require_aice and "aice" not in player_deck_id:
            continue
        aice_row_count += 1
        difficulty = str(row.get("opponentKind") or "unknown").strip().lower() or "unknown"
        firstness = _row_firstness(row)
        difficulty_firstness = f"{difficulty}|{firstness}"
        row_counts_by_difficulty_firstness[difficulty_firstness] += 1
        human_chosen_action_id = str(row.get("humanChosenActionId") or "")
        for action in list(row.get("actions") or []):
            action_count += 1
            action_kind = str(action.get("actionKind") or "unknown")
            action_kind_counts[action_kind] += 1
            labels = aice_combo_plan_action_labels(row, action)
            is_human_chosen = bool(human_chosen_action_id and str(action.get("actionId") or "") == human_chosen_action_id)
            if is_human_chosen:
                human_chosen_action_count += 1
                chosen_action_kind_counts[action_kind] += 1
            if not labels:
                unlabeled_action_count += 1
                if is_human_chosen:
                    unlabeled_human_chosen_action_count += 1
                continue
            for label in labels:
                label_counts[label] += 1
                counts_by_label_difficulty_firstness.setdefault(label, Counter())[difficulty_firstness] += 1
                action_kind_counts_by_label.setdefault(label, Counter())[action_kind] += 1
                if is_human_chosen:
                    chosen_label_counts[label] += 1

    missing_required = [
        label for label in AICE_COMBO_PLAN_REQUIRED_LABELS
        if int(label_counts.get(label, 0)) <= 0
    ]
    return {
        "kind": "aice_combo_plan_label_report",
        "rowCount": len(materialized_rows),
        "aiceRowCount": int(aice_row_count),
        "actionCount": int(action_count),
        "humanChosenActionCount": int(human_chosen_action_count),
        "labelCounts": dict(sorted(label_counts.items())),
        "humanChosenLabelCounts": dict(sorted(chosen_label_counts.items())),
        "actionKindCounts": dict(sorted(action_kind_counts.items())),
        "humanChosenActionKindCounts": dict(sorted(chosen_action_kind_counts.items())),
        "rowCountsByDifficultyFirstness": dict(sorted(row_counts_by_difficulty_firstness.items())),
        "countsByLabelDifficultyFirstness": {
            label: dict(sorted(counter.items()))
            for label, counter in sorted(counts_by_label_difficulty_firstness.items())
        },
        "actionKindCountsByLabel": {
            label: dict(sorted(counter.items()))
            for label, counter in sorted(action_kind_counts_by_label.items())
        },
        "unlabeledActionCount": int(unlabeled_action_count),
        "unlabeledHumanChosenActionCount": int(unlabeled_human_chosen_action_count),
        "requiredLabels": list(AICE_COMBO_PLAN_REQUIRED_LABELS),
        "missingRequiredLabels": missing_required,
        "passedLabelPresenceGate": not missing_required,
        "notes": [
            "This report labels existing trace transition rows only; it does not train or promote an evaluator.",
            "Label presence is not sufficient for promotion. G2 still requires held-out baseline comparison and mistake reports."
        ],
    }


def apply_aice_combo_plan_target_shaping(
    rows: Iterable[dict[str, Any]],
    *,
    require_aice: bool = True,
    winning_traces_only: bool = True,
    label_component_deltas: dict[str, dict[str, float]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shape AICE transition targets from explicit combo-plan action labels."""
    deltas_by_label = {
        str(label): {
            str(component): float(delta)
            for component, delta in dict(component_deltas).items()
            if str(component) in TARGET_COMPONENT_KEYS and float(delta) != 0.0
        }
        for label, component_deltas in dict(
            label_component_deltas or AICE_COMBO_PLAN_TARGET_SHAPING_DELTAS
        ).items()
    }
    shaped_rows: list[dict[str, Any]] = []
    label_counts: Counter[str] = Counter()
    component_delta_sums: Counter[str] = Counter()
    row_count = 0
    action_count = 0
    shaped_row_count = 0
    shaped_action_count = 0
    skipped_non_aice = 0
    skipped_non_winning = 0
    for row in rows:
        validate_transition_row(row)
        row_count += 1
        shaped = copy.deepcopy(row)
        player_deck_id = str(shaped.get("playerDeckId") or "").strip().lower()
        if require_aice and "aice" not in player_deck_id:
            skipped_non_aice += 1
            shaped_rows.append(shaped)
            continue
        row_tags = {str(tag) for tag in list(shaped.get("stateTags") or [])}
        if winning_traces_only and "player_win_trace" not in row_tags:
            skipped_non_winning += 1
            shaped_rows.append(shaped)
            continue
        row_was_shaped = False
        for action in list(shaped.get("actions") or []):
            action_count += 1
            labels = [
                label
                for label in aice_combo_plan_action_labels(shaped, action)
                if label in deltas_by_label and deltas_by_label[label]
            ]
            if not labels:
                continue
            targets = dict(action.get("targets") or {})
            action_component_deltas: Counter[str] = Counter()
            for label in labels:
                label_counts[label] += 1
                for component, delta in deltas_by_label[label].items():
                    targets[component] = float(targets.get(component, 0.0) or 0.0) + float(delta)
                    action_component_deltas[component] += float(delta)
                    component_delta_sums[component] += float(delta)
            targets["aiceComboPlanTargetShaping"] = {
                "labels": sorted(labels),
                "componentDeltas": dict(sorted(action_component_deltas.items())),
            }
            targets["transitionValue"] = transition_value_from_targets(targets)
            action["targets"] = targets
            shaped_action_count += 1
            row_was_shaped = True
        if row_was_shaped:
            row_tags.add("aice_combo_plan_target_shaping")
            shaped["stateTags"] = sorted(row_tags)
            shaped_row_count += 1
        validate_transition_row(shaped)
        shaped_rows.append(shaped)
    return shaped_rows, {
        "kind": "aice_combo_plan_target_shaping",
        "rowCount": int(row_count),
        "actionCount": int(action_count),
        "shapedRowCount": int(shaped_row_count),
        "shapedActionCount": int(shaped_action_count),
        "skippedNonAiceRowCount": int(skipped_non_aice),
        "skippedNonWinningTraceRowCount": int(skipped_non_winning),
        "requireAice": bool(require_aice),
        "winningTracesOnly": bool(winning_traces_only),
        "labelComponentDeltas": {
            label: dict(sorted(component_deltas.items()))
            for label, component_deltas in sorted(deltas_by_label.items())
        },
        "labelCounts": dict(sorted(label_counts.items())),
        "componentDeltaSums": dict(sorted(component_delta_sums.items())),
    }


def derive_pairwise_rows(
    rows: Iterable[dict[str, Any]],
    *,
    min_value_gap: float = 0.75,
    include_rollout_features: bool = True,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for row in rows:
        validate_transition_row(row)
        actions = list(row.get("actions") or [])
        scored = [
            (float(action["targets"]["transitionValue"]), action)
            for action in actions
            if isinstance(action.get("targets"), dict) and "transitionValue" in action["targets"]
        ]
        for good_value, good_action in scored:
            for bad_value, bad_action in scored:
                value_gap = good_value - bad_value
                if value_gap < float(min_value_gap):
                    continue
                pairs.append({
                    "schemaVersion": COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION,
                    "featureMode": "with_rollout" if include_rollout_features else "predictive_no_rollout",
                    "rowId": f"ctpair:{row['rowId']}:{good_action['actionId']}:{bad_action['actionId']}",
                    "parentRowId": row["rowId"],
                    "goodActionId": good_action["actionId"],
                    "badActionId": bad_action["actionId"],
                    "valueGap": float(value_gap),
                    "reasonTags": _pair_reason_tags(good_action, bad_action),
                    "sliceTags": _slice_tags_for_row(row),
                    "goodFeatures": action_transition_feature_row(
                        before_features=dict(row.get("beforeStateFeatures") or {}),
                        action=good_action,
                        include_rollout_features=include_rollout_features,
                    ),
                    "badFeatures": action_transition_feature_row(
                        before_features=dict(row.get("beforeStateFeatures") or {}),
                        action=bad_action,
                        include_rollout_features=include_rollout_features,
                    ),
                })
    return pairs


def derive_chosen_action_delta_pairwise_rows(
    rows: Iterable[dict[str, Any]],
    *,
    min_value_gap: float = 0.75,
    include_rollout_features: bool = True,
    preserve_human_win_choices: bool = False,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for row in rows:
        validate_transition_row(row)
        row_tags = {str(tag) for tag in list(row.get("stateTags") or [])}
        human_chosen_action_id = str(row.get("humanChosenActionId") or "")
        chosen_action_id = str(row.get("battleChosenActionId") or human_chosen_action_id or "")
        if not chosen_action_id:
            continue
        preserve_row_choice = (
            bool(preserve_human_win_choices)
            and "player_win_trace" in row_tags
            and bool(human_chosen_action_id)
            and chosen_action_id == human_chosen_action_id
        )
        actions = [
            action
            for action in list(row.get("actions") or [])
            if isinstance(action.get("targets"), dict) and "transitionValue" in action["targets"]
        ]
        chosen_action = next(
            (action for action in actions if str(action.get("actionId")) == chosen_action_id),
            None,
        )
        if chosen_action is None:
            continue
        chosen_value = float(chosen_action["targets"]["transitionValue"])
        for action in actions:
            if action is chosen_action:
                continue
            action_value = float(action["targets"]["transitionValue"])
            value_gap = action_value - chosen_value
            if preserve_row_choice and abs(value_gap) >= float(min_value_gap):
                good_action = chosen_action
                bad_action = action
                value_gap = abs(value_gap)
                direction_tag = (
                    "preserves_player_win_human_choice_over_target_law"
                    if action_value > chosen_value
                    else "protects_against_worse_than_chosen"
                )
            elif value_gap >= float(min_value_gap):
                good_action = action
                bad_action = chosen_action
                direction_tag = "improves_over_chosen"
            elif -value_gap >= float(min_value_gap):
                good_action = chosen_action
                bad_action = action
                value_gap = -value_gap
                direction_tag = "protects_against_worse_than_chosen"
            else:
                continue
            pairs.append({
                "schemaVersion": COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION,
                "featureMode": "with_rollout" if include_rollout_features else "predictive_no_rollout",
                "rowId": f"ctchosenpair:{row['rowId']}:{good_action['actionId']}:{bad_action['actionId']}",
                "parentRowId": row["rowId"],
                "goodActionId": good_action["actionId"],
                "badActionId": bad_action["actionId"],
                "chosenActionId": chosen_action_id,
                "valueGap": float(value_gap),
                "reasonTags": sorted(set([
                    "chosen_action_delta",
                    direction_tag,
                    *_pair_reason_tags(good_action, bad_action),
                ])),
                "sliceTags": _slice_tags_for_row(row),
                "goodFeatures": action_transition_feature_row(
                    before_features=dict(row.get("beforeStateFeatures") or {}),
                    action=good_action,
                    include_rollout_features=include_rollout_features,
                ),
                "badFeatures": action_transition_feature_row(
                    before_features=dict(row.get("beforeStateFeatures") or {}),
                    action=bad_action,
                    include_rollout_features=include_rollout_features,
                ),
            })
    return pairs


def derive_human_chosen_preference_pairwise_rows(
    rows: Iterable[dict[str, Any]],
    *,
    include_rollout_features: bool = True,
    winning_traces_only: bool = True,
    preference_value_gap: float = 1.0,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for row in rows:
        validate_transition_row(row)
        row_tags = {str(tag) for tag in list(row.get("stateTags") or [])}
        if winning_traces_only and "player_win_trace" not in row_tags:
            continue
        chosen_action_id = str(row.get("humanChosenActionId") or row.get("battleChosenActionId") or "")
        if not chosen_action_id:
            continue
        actions = list(row.get("actions") or [])
        chosen_action = next(
            (action for action in actions if str(action.get("actionId")) == chosen_action_id),
            None,
        )
        if chosen_action is None:
            continue
        for action in actions:
            if action is chosen_action:
                continue
            reason_tags = ["human_observed_win_choice"]
            reason_tags.extend(_pair_reason_tags(chosen_action, action))
            pairs.append({
                "schemaVersion": COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION,
                "featureMode": "with_rollout" if include_rollout_features else "predictive_no_rollout",
                "rowId": f"cthuman:{row['rowId']}:{chosen_action['actionId']}:{action['actionId']}",
                "parentRowId": row["rowId"],
                "goodActionId": chosen_action["actionId"],
                "badActionId": action["actionId"],
                "valueGap": float(preference_value_gap),
                "reasonTags": sorted(set(reason_tags)),
                "sliceTags": _slice_tags_for_row(row),
                "goodFeatures": action_transition_feature_row(
                    before_features=dict(row.get("beforeStateFeatures") or {}),
                    action=chosen_action,
                    include_rollout_features=include_rollout_features,
                ),
                "badFeatures": action_transition_feature_row(
                    before_features=dict(row.get("beforeStateFeatures") or {}),
                    action=action,
                    include_rollout_features=include_rollout_features,
                ),
            })
    return pairs


def apply_human_chosen_target_bonus(
    rows: Iterable[dict[str, Any]],
    *,
    bonus: float,
    component: str = "planValue",
    winning_traces_only: bool = True,
    min_current_value_gap: float = 0.0,
    floor_to_best: bool = False,
    floor_margin: float = 0.05,
) -> list[dict[str, Any]]:
    shaped_rows: list[dict[str, Any]] = []
    bonus_value = float(bonus)
    min_gap = max(0.0, float(min_current_value_gap))
    floor_enabled = bool(floor_to_best)
    floor_margin_value = max(0.0, float(floor_margin))
    for row in rows:
        validate_transition_row(row)
        shaped = copy.deepcopy(row)
        if bonus_value <= 0.0 and not floor_enabled:
            shaped_rows.append(shaped)
            continue
        tags = {str(tag) for tag in list(shaped.get("stateTags") or [])}
        if winning_traces_only and "player_win_trace" not in tags:
            shaped_rows.append(shaped)
            continue
        chosen_action_id = str(shaped.get("humanChosenActionId") or shaped.get("battleChosenActionId") or "")
        if not chosen_action_id:
            shaped_rows.append(shaped)
            continue
        actions = list(shaped.get("actions") or [])
        chosen_action = next(
            (action for action in actions if str(action.get("actionId")) == chosen_action_id),
            None,
        )
        if chosen_action is None:
            shaped_rows.append(shaped)
            continue
        if min_gap > 0.0:
            chosen_value = float(dict(chosen_action.get("targets") or {}).get("transitionValue", 0.0) or 0.0)
            best_value = max(
                (
                    float(dict(action.get("targets") or {}).get("transitionValue", 0.0) or 0.0)
                    for action in actions
                ),
                default=chosen_value,
            )
            if best_value - chosen_value < min_gap:
                shaped_rows.append(shaped)
                continue
        targets = dict(chosen_action.get("targets") or {})
        target_component = str(component or "planValue")
        if target_component not in TARGET_COMPONENT_KEYS:
            target_component = "planValue"
        changed = False
        if bonus_value > 0.0:
            targets[target_component] = float(targets.get(target_component, 0.0) or 0.0) + bonus_value
            targets["humanChosenBonus"] = float(targets.get("humanChosenBonus", 0.0) or 0.0) + bonus_value
            changed = True
        if floor_enabled:
            current_value = transition_value_from_targets(targets)
            best_other_value = max(
                (
                    float(dict(action.get("targets") or {}).get("transitionValue", 0.0) or 0.0)
                    for action in actions
                    if action is not chosen_action
                ),
                default=current_value,
            )
            desired_value = best_other_value + floor_margin_value
            if desired_value > current_value:
                floor_delta = desired_value - current_value
                targets[target_component] = float(targets.get(target_component, 0.0) or 0.0) + floor_delta
                targets["humanChosenTargetFloor"] = (
                    float(targets.get("humanChosenTargetFloor", 0.0) or 0.0) + floor_delta
                )
                changed = True
        targets["transitionValue"] = transition_value_from_targets(targets)
        chosen_action["targets"] = targets
        if changed:
            tags.add("human_chosen_target_bonus")
            if floor_enabled:
                tags.add("human_chosen_target_floor")
            shaped["stateTags"] = sorted(tags)
        validate_transition_row(shaped)
        shaped_rows.append(shaped)
    return shaped_rows


def _pair_reason_tags(good_action: dict[str, Any], bad_action: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    good_targets = dict(good_action.get("targets") or {})
    bad_targets = dict(bad_action.get("targets") or {})
    if float(good_targets.get("survivalValue", 0.0)) > float(bad_targets.get("survivalValue", 0.0)):
        tags.append("survives_enemy_reply")
    if float(good_targets.get("pressureValue", 0.0)) > float(bad_targets.get("pressureValue", 0.0)):
        tags.append("advances_pressure")
    if float(good_targets.get("planValue", 0.0)) > float(bad_targets.get("planValue", 0.0)):
        tags.append("advances_plan")
    if float(good_targets.get("resourceValue", 0.0)) > float(bad_targets.get("resourceValue", 0.0)):
        tags.append("improves_resources")
    return tags


def _slice_tags_for_row(row: dict[str, Any]) -> list[str]:
    tags = [str(tag) for tag in row.get("stateTags") or []]
    firstness = _row_firstness(row)
    if firstness == "first":
        tags.append("First")
    elif firstness == "second":
        tags.append("Second")
    if str(row.get("playerDeckId", "")).lower() == "aice":
        tags.append("AICE")
    opponent_kind = str(row.get("opponentKind", "")).strip().lower()
    if opponent_kind:
        tags.append(opponent_kind.capitalize())
    opponent_profile = row.get("opponentBehaviorProfile") or {}
    if float(opponent_profile.get("attackRate", 0.0) or 0.0) >= 0.5:
        tags.append("observed_pressure")
    return sorted(set(tags))


def pairwise_accuracy(
    pairs: Iterable[dict[str, Any]],
    score_many: Any,
) -> float:
    pair_list = list(pairs)
    if not pair_list:
        return 0.0
    good_scores = list(score_many([dict(pair["goodFeatures"]) for pair in pair_list]))
    bad_scores = list(score_many([dict(pair["badFeatures"]) for pair in pair_list]))
    correct = sum(1 for good, bad in zip(good_scores, bad_scores, strict=True) if float(good) > float(bad))
    return correct / len(pair_list)


def offline_gate_report(
    *,
    train_pairs: list[dict[str, Any]],
    holdout_pairs: list[dict[str, Any]],
    score_many: Any,
    required_slices: Iterable[str] = ("Second", "AICE", "enemy_ready_pressure", "Normal"),
) -> dict[str, Any]:
    slice_accuracy: dict[str, float] = {}
    for tag in required_slices:
        slice_pairs = [pair for pair in holdout_pairs if tag in set(pair.get("sliceTags") or [])]
        slice_accuracy[str(tag)] = pairwise_accuracy(slice_pairs, score_many) if slice_pairs else 0.0
    train_accuracy = pairwise_accuracy(train_pairs, score_many)
    holdout_accuracy = pairwise_accuracy(holdout_pairs, score_many)
    passed = (
        train_accuracy >= 0.68
        and holdout_accuracy >= 0.60
        and all(value >= 0.55 for value in slice_accuracy.values())
    )
    return {
        "kind": "counterfactual_transition_offline_gate",
        "trainPairCount": len(train_pairs),
        "holdoutPairCount": len(holdout_pairs),
        "trainPairwiseAccuracy": train_accuracy,
        "holdoutPairwiseAccuracy": holdout_accuracy,
        "slicePairwiseAccuracy": slice_accuracy,
        "passedOfflineGate": passed,
    }


class TransitionLinearRanker:
    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        bias: float = 0.0,
        seed: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.weights = dict(weights or {})
        self.bias = float(bias)
        self.seed = int(seed)
        self.metadata = {
            "kind": "counterfactual_transition_evaluator",
            "schemaVersion": COUNTERFACTUAL_TRANSITION_SCHEMA_VERSION,
            "trainingSeed": self.seed,
            "featureVersion": "transition_flat_features_v1",
            "labelVersion": "transition_outcome_v1",
            "gateStatus": "unpromoted",
        }
        if metadata:
            self.metadata.update(metadata)

    def score_transition(self, row: dict[str, float]) -> float:
        filtered_row = self._drop_runtime_filtered_features(row)
        if self._should_abstain_for_feature_novelty(filtered_row):
            return 0.0
        return float(self.bias + sum(self.weights.get(key, 0.0) * float(value) for key, value in filtered_row.items()))

    def score_many(self, rows: list[dict[str, float]]) -> list[float]:
        return [self.score_transition(row) for row in rows]

    def _should_abstain_for_feature_novelty(self, row: dict[str, float]) -> bool:
        return bool(self.feature_novelty_report(row).get("abstained", False))

    def feature_novelty_report(self, row: dict[str, float]) -> dict[str, Any]:
        row = self._drop_runtime_filtered_features(row)
        if "knownFeatureKeys" not in self.metadata or "maxUnknownNonzeroFeatureRatio" not in self.metadata:
            return {
                "enabled": False,
                "nonzeroFeatureCount": 0,
                "unknownNonzeroFeatureCount": 0,
                "unknownNonzeroFeatureRatio": 0.0,
                "unknownFeatureKeys": [],
                "abstained": False,
            }
        known = {str(key) for key in self.metadata.get("knownFeatureKeys") or []}
        nonzero_keys = [
            str(key)
            for key, value in row.items()
            if isinstance(value, (int, float)) and abs(float(value)) > 1e-12
        ]
        if not nonzero_keys:
            return {
                "enabled": True,
                "nonzeroFeatureCount": 0,
                "unknownNonzeroFeatureCount": 0,
                "unknownNonzeroFeatureRatio": 0.0,
                "unknownFeatureKeys": [],
                "abstained": False,
            }
        unknown = [
            key
            for key in nonzero_keys
            if key not in known and not _transition_schema_color_enum_feature(key)
        ]
        unknown_ratio = len(unknown) / max(1, len(nonzero_keys))
        return {
            "enabled": True,
            "nonzeroFeatureCount": len(nonzero_keys),
            "unknownNonzeroFeatureCount": len(unknown),
            "unknownNonzeroFeatureRatio": unknown_ratio,
            "unknownFeatureKeys": sorted(unknown),
            "abstained": unknown_ratio > float(self.metadata.get("maxUnknownNonzeroFeatureRatio", 1.0)),
        }

    def _drop_runtime_filtered_features(self, row: dict[str, float]) -> dict[str, float]:
        substrings = [
            str(value)
            for value in self.metadata.get("droppedFeatureSubstrings", []) or []
            if str(value)
        ]
        drop_observed_opponent = not bool(self.metadata.get("usesObservedOpponentFeatures", False))
        drop_after_state = self.metadata.get("usesAfterStateFeatures") is False
        drop_before_state = self.metadata.get("usesBeforeStateFeatures") is False
        return {
            str(key): value
            for key, value in row.items()
            if not any(substring in str(key) for substring in substrings)
            and not (drop_after_state and str(key).startswith("after:"))
            and not (
                drop_before_state
                and str(key).startswith("before:")
                and str(key) not in {"before:learner_is_first_player", "before:learner_is_second_player"}
            )
            and not (drop_before_state and _transition_action_context_feature(str(key)))
            and not (drop_before_state and str(key).startswith("interaction:ctx:"))
            and not _transition_play_card_scoped_feature_inactive(row, str(key))
            and not (
                drop_observed_opponent
                and _transition_observed_opponent_feature(str(key))
            )
        }

    def fit_pairwise(
        self,
        pairs: list[dict[str, Any]],
        *,
        epochs: int = 5,
        learning_rate: float = 0.05,
        margin: float = 0.5,
    ) -> dict[str, Any]:
        clean_pairs = [
            (dict(pair["goodFeatures"]), dict(pair["badFeatures"]))
            for pair in pairs
            if isinstance(pair, dict) and pair.get("goodFeatures") and pair.get("badFeatures")
        ]
        losses: list[float] = []
        for _ in range(max(1, int(epochs))):
            loss_total = 0.0
            for good, bad in clean_pairs:
                good_score = self.score_transition(good)
                bad_score = self.score_transition(bad)
                loss = max(0.0, float(margin) - (good_score - bad_score))
                if loss <= 0.0:
                    continue
                loss_total += loss
                delta = _feature_delta(good, bad)
                for key, value in delta.items():
                    self.weights[key] = self.weights.get(key, 0.0) + float(learning_rate) * float(value)
            losses.append(loss_total / max(1, len(clean_pairs)))
        return {
            "kind": "transition_linear_ranker_training",
            "pairCount": len(clean_pairs),
            "epochs": max(1, int(epochs)),
            "learningRate": float(learning_rate),
            "margin": float(margin),
            "loss": losses[-1] if losses else 0.0,
        }

    def save(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({
                "metadata": self.metadata,
                "weights": self.weights,
                "bias": self.bias,
            }, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "TransitionLinearRanker":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = dict(payload.get("metadata") or {})
        if str(metadata.get("modelKind") or "") == "gated_linear_ranker":
            return TransitionGatedLinearRanker.load(path)
        if str(metadata.get("modelKind") or "") == "pressure_aware_action_set_perceptron":
            return TransitionPressureAwareActionSetPerceptron.load(path)
        return cls(
            weights={str(key): float(value) for key, value in dict(payload.get("weights") or {}).items()},
            bias=float(payload.get("bias", 0.0) or 0.0),
            seed=int(metadata.get("trainingSeed", 0) or 0),
            metadata=metadata,
        )


def transition_defensive_pressure_from_feature_row(row: dict[str, Any]) -> bool:
    return bool(
        float(row.get("before:enemy_pressure_high_player_risk", 0.0) or 0.0) > 0.0
        or float(row.get("before:enemy_pressure_near_player_lethal", 0.0) or 0.0) > 0.0
        or float(row.get("rollout:lethalRiskAfter", 0.0) or 0.0) > 0.0
    )


class TransitionGatedLinearRanker(TransitionLinearRanker):
    def __init__(
        self,
        *,
        survival_weights: dict[str, float] | None = None,
        race_weights: dict[str, float] | None = None,
        survival_bias: float = 0.0,
        race_bias: float = 0.0,
        seed: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            weights={},
            bias=0.0,
            seed=seed,
            metadata={
                "modelKind": "gated_linear_ranker",
                "gateMode": "v4_defensive_pressure",
                **dict(metadata or {}),
            },
        )
        self.survival_weights = {str(key): float(value) for key, value in dict(survival_weights or {}).items()}
        self.race_weights = {str(key): float(value) for key, value in dict(race_weights or {}).items()}
        self.survival_bias = float(survival_bias)
        self.race_bias = float(race_bias)

    def selected_head(self, row: dict[str, Any]) -> str:
        filtered_row = self._drop_runtime_filtered_features(row)
        return "survival" if transition_defensive_pressure_from_feature_row(filtered_row) else "race"

    def score_transition(self, row: dict[str, float]) -> float:
        filtered_row = self._drop_runtime_filtered_features(row)
        if self._should_abstain_for_feature_novelty(filtered_row):
            return 0.0
        return self._score_with_head(filtered_row, self.selected_head(filtered_row))

    def score_many(self, rows: list[dict[str, float]]) -> list[float]:
        return [self.score_transition(row) for row in rows]

    def _score_with_head(self, row: dict[str, Any], head: str) -> float:
        weights, bias = self._head_parameters(head)
        return float(bias + sum(weights.get(str(key), 0.0) * float(value) for key, value in row.items()))

    def _head_parameters(self, head: str) -> tuple[dict[str, float], float]:
        if str(head) == "survival":
            return self.survival_weights, self.survival_bias
        if str(head) == "race":
            return self.race_weights, self.race_bias
        raise ValueError(f"unknown transition evaluator head: {head!r}")

    def fit_component_heads(
        self,
        rows: list[dict[str, Any]],
        *,
        epochs: int = 5,
        learning_rate: float = 0.05,
        margin: float = 0.5,
        min_component_gap: float = 0.75,
        include_rollout_features: bool = True,
    ) -> dict[str, Any]:
        head_pairs = self._component_head_pairs(
            rows,
            min_component_gap=min_component_gap,
            include_rollout_features=include_rollout_features,
        )
        losses_by_epoch: list[dict[str, float]] = []
        for _ in range(max(1, int(epochs))):
            epoch_losses: dict[str, float] = {}
            for head in ("survival", "race"):
                pairs = head_pairs[head]
                weights, _bias = self._head_parameters(head)
                loss_total = 0.0
                for good, bad in pairs:
                    good_score = self._score_with_head(good, head)
                    bad_score = self._score_with_head(bad, head)
                    loss = max(0.0, float(margin) - (good_score - bad_score))
                    if loss <= 0.0:
                        continue
                    loss_total += loss
                    delta = _feature_delta(good, bad)
                    for key, value in delta.items():
                        weights[key] = weights.get(key, 0.0) + float(learning_rate) * float(value)
                epoch_losses[head] = loss_total / max(1, len(pairs))
            losses_by_epoch.append(epoch_losses)
        final_losses = losses_by_epoch[-1] if losses_by_epoch else {"survival": 0.0, "race": 0.0}
        return {
            "kind": "transition_gated_linear_ranker_training",
            "rowCount": len(rows),
            "headPairCounts": {head: len(head_pairs[head]) for head in ("survival", "race")},
            "epochs": max(1, int(epochs)),
            "learningRate": float(learning_rate),
            "margin": float(margin),
            "minComponentGap": float(min_component_gap),
            "lossByHead": final_losses,
        }

    def fit_action_sets(
        self,
        rows: list[dict[str, Any]],
        *,
        epochs: int = 3,
        learning_rate: float = 0.05,
        margin: float = 0.5,
        include_rollout_features: bool = True,
        value_tolerance: float = 1e-6,
    ) -> dict[str, Any]:
        action_sets = transition_action_set_training_samples(
            rows,
            include_rollout_features=include_rollout_features,
        )
        mistake_counts: list[int] = []
        updated_head_counts = {"survival": 0, "race": 0}
        for _ in range(max(1, int(epochs))):
            mistakes = 0
            for feature_rows, targets in action_sets:
                if len(feature_rows) < 2:
                    continue
                scores = self.score_many(feature_rows)
                predicted_index = max(range(len(scores)), key=lambda index: (scores[index], -index))
                best_value = max(targets)
                best_index = max(range(len(targets)), key=lambda index: (targets[index], -index))
                rival_indexes = [
                    index
                    for index, target in enumerate(targets)
                    if index != best_index and target < best_value - float(value_tolerance)
                ]
                rival_index = (
                    max(rival_indexes, key=lambda index: (scores[index], -index))
                    if rival_indexes
                    else predicted_index
                )
                if (
                    targets[predicted_index] >= best_value - float(value_tolerance)
                    and float(scores[best_index]) - float(scores[rival_index]) >= float(margin)
                ):
                    continue
                self._apply_action_set_update(
                    best_features=feature_rows[best_index],
                    rival_features=feature_rows[rival_index],
                    learning_rate=learning_rate,
                    updated_head_counts=updated_head_counts,
                )
                mistakes += 1
            mistake_counts.append(mistakes)
        return {
            "kind": "transition_gated_action_set_finetuning",
            "actionSetRowCount": len(action_sets),
            "epochs": max(1, int(epochs)),
            "learningRate": float(learning_rate),
            "margin": float(margin),
            "valueTolerance": float(value_tolerance),
            "mistakes": mistake_counts[-1] if mistake_counts else 0,
            "mistakesByEpoch": mistake_counts,
            "updatedHeadCounts": updated_head_counts,
            "trainingTop1Accuracy": action_set_top1_accuracy(
                action_sets,
                self.score_many,
                value_tolerance=value_tolerance,
            ),
        }

    def _apply_action_set_update(
        self,
        *,
        best_features: dict[str, float],
        rival_features: dict[str, float],
        learning_rate: float,
        updated_head_counts: dict[str, int],
    ) -> None:
        best_head = self.selected_head(best_features)
        rival_head = self.selected_head(rival_features)
        if best_head == rival_head:
            weights, _bias = self._head_parameters(best_head)
            delta = _feature_delta(best_features, rival_features)
            for key, value in delta.items():
                weights[key] = weights.get(key, 0.0) + float(learning_rate) * float(value)
            updated_head_counts[best_head] += 1
            return
        best_weights, _best_bias = self._head_parameters(best_head)
        rival_weights, _rival_bias = self._head_parameters(rival_head)
        for key, value in best_features.items():
            best_weights[str(key)] = best_weights.get(str(key), 0.0) + float(learning_rate) * float(value)
        for key, value in rival_features.items():
            rival_weights[str(key)] = rival_weights.get(str(key), 0.0) - float(learning_rate) * float(value)
        updated_head_counts[best_head] += 1
        updated_head_counts[rival_head] += 1

    def _component_head_pairs(
        self,
        rows: list[dict[str, Any]],
        *,
        min_component_gap: float,
        include_rollout_features: bool,
    ) -> dict[str, list[tuple[dict[str, float], dict[str, float]]]]:
        head_pairs: dict[str, list[tuple[dict[str, float], dict[str, float]]]] = {
            "survival": [],
            "race": [],
        }
        for row in rows:
            validate_transition_row(row)
            before_features = dict(row.get("beforeStateFeatures") or {})
            samples: list[tuple[dict[str, float], dict[str, Any]]] = []
            for action in list(row.get("actions") or []):
                targets = dict(action.get("targets") or {})
                if "transitionValue" not in targets:
                    continue
                samples.append((
                    action_transition_feature_row(
                        before_features=before_features,
                        action=action,
                        include_rollout_features=include_rollout_features,
                    ),
                    targets,
                ))
            for head in ("survival", "race"):
                for good_features, good_targets in samples:
                    for bad_features, bad_targets in samples:
                        value_gap = (
                            self._target_component_value(good_targets, head)
                            - self._target_component_value(bad_targets, head)
                        )
                        if value_gap >= float(min_component_gap):
                            head_pairs[head].append((good_features, bad_features))
        return head_pairs

    def _target_component_value(self, targets: dict[str, Any], head: str) -> float:
        terminal = float(targets.get("terminalValue", 0.0) or 0.0)
        timeout = float(targets.get("timeoutPenalty", 0.0) or 0.0)
        if str(head) == "survival":
            return terminal + float(targets.get("survivalValue", 0.0) or 0.0) - timeout
        if str(head) == "race":
            return (
                terminal
                + float(targets.get("pressureValue", 0.0) or 0.0)
                + float(targets.get("planValue", 0.0) or 0.0)
                + float(targets.get("tempoValue", 0.0) or 0.0)
                + float(targets.get("resourceValue", 0.0) or 0.0)
                - timeout
            )
        raise ValueError(f"unknown transition evaluator head: {head!r}")

    def save(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({
                "metadata": self.metadata,
                "survivalWeights": self.survival_weights,
                "raceWeights": self.race_weights,
                "survivalBias": self.survival_bias,
                "raceBias": self.race_bias,
            }, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "TransitionGatedLinearRanker":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = dict(payload.get("metadata") or {})
        return cls(
            survival_weights={
                str(key): float(value)
                for key, value in dict(payload.get("survivalWeights") or {}).items()
            },
            race_weights={
                str(key): float(value)
                for key, value in dict(payload.get("raceWeights") or {}).items()
            },
            survival_bias=float(payload.get("survivalBias", 0.0) or 0.0),
            race_bias=float(payload.get("raceBias", 0.0) or 0.0),
            seed=int(metadata.get("trainingSeed", 0) or 0),
            metadata=metadata,
        )


class TransitionLinearOutcomeRegressor(TransitionLinearRanker):
    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        bias: float = 0.0,
        seed: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            weights=weights,
            bias=bias,
            seed=seed,
            metadata={
                "modelKind": "linear_outcome_regressor",
                **dict(metadata or {}),
            },
        )

    def fit_outcomes(
        self,
        rows: list[dict[str, Any]],
        *,
        epochs: int = 8,
        learning_rate: float = 0.01,
        include_rollout_features: bool = True,
    ) -> dict[str, Any]:
        samples = transition_outcome_training_samples(
            rows,
            include_rollout_features=include_rollout_features,
        )
        losses: list[float] = []
        for _ in range(max(1, int(epochs))):
            squared_error = 0.0
            for features, target in samples:
                prediction = self.score_transition(features)
                error = float(target) - prediction
                squared_error += error * error
                scale = max(1.0, sum(float(value) * float(value) for value in features.values()))
                step = float(learning_rate) * error / scale
                self.bias += step
                for key, value in features.items():
                    self.weights[key] = self.weights.get(key, 0.0) + step * float(value)
            losses.append(squared_error / max(1, len(samples)))
        return {
            "kind": "transition_linear_outcome_regressor_training",
            "sampleCount": len(samples),
            "epochs": max(1, int(epochs)),
            "learningRate": float(learning_rate),
            "loss": losses[-1] if losses else 0.0,
        }

    @classmethod
    def load(cls, path: str | Path) -> "TransitionLinearOutcomeRegressor":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = dict(payload.get("metadata") or {})
        return cls(
            weights={str(key): float(value) for key, value in dict(payload.get("weights") or {}).items()},
            bias=float(payload.get("bias", 0.0) or 0.0),
            seed=int(metadata.get("trainingSeed", 0) or 0),
            metadata=metadata,
        )


def transition_outcome_training_samples(
    rows: Iterable[dict[str, Any]],
    *,
    include_rollout_features: bool = True,
) -> list[tuple[dict[str, float], float]]:
    samples: list[tuple[dict[str, float], float]] = []
    for row in rows:
        validate_transition_row(row)
        before_features = dict(row.get("beforeStateFeatures") or {})
        for action in list(row.get("actions") or []):
            targets = dict(action.get("targets") or {})
            if "transitionValue" not in targets:
                continue
            samples.append((
                action_transition_feature_row(
                    before_features=before_features,
                    action=action,
                    include_rollout_features=include_rollout_features,
                ),
                float(targets["transitionValue"]),
            ))
    return samples


class TransitionActionSetPerceptron(TransitionLinearRanker):
    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        bias: float = 0.0,
        seed: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            weights=weights,
            bias=bias,
            seed=seed,
            metadata={
                "modelKind": "action_set_perceptron",
                **dict(metadata or {}),
            },
        )

    def fit_action_sets(
        self,
        rows: list[dict[str, Any]],
        *,
        epochs: int = 5,
        learning_rate: float = 1.0,
        margin: float = 1.0,
        include_rollout_features: bool = True,
        value_tolerance: float = 1e-6,
    ) -> dict[str, Any]:
        action_sets = transition_action_set_training_samples(
            rows,
            include_rollout_features=include_rollout_features,
        )
        mistake_counts: list[int] = []
        for _ in range(max(1, int(epochs))):
            mistakes = 0
            for feature_rows, targets in action_sets:
                if len(feature_rows) < 2:
                    continue
                scores = self.score_many(feature_rows)
                predicted_index = max(range(len(scores)), key=lambda index: (scores[index], -index))
                best_value = max(targets)
                best_index = max(range(len(targets)), key=lambda index: (targets[index], -index))
                rival_indexes = [
                    index
                    for index, target in enumerate(targets)
                    if index != best_index and target < best_value - float(value_tolerance)
                ]
                rival_index = (
                    max(rival_indexes, key=lambda index: (scores[index], -index))
                    if rival_indexes
                    else predicted_index
                )
                if (
                    targets[predicted_index] >= best_value - float(value_tolerance)
                    and float(scores[best_index]) - float(scores[rival_index]) >= float(margin)
                ):
                    continue
                delta = _feature_delta(feature_rows[best_index], feature_rows[rival_index])
                for key, value in delta.items():
                    self.weights[key] = self.weights.get(key, 0.0) + float(learning_rate) * float(value)
                mistakes += 1
            mistake_counts.append(mistakes)
        return {
            "kind": "transition_action_set_perceptron_training",
            "actionSetRowCount": len(action_sets),
            "epochs": max(1, int(epochs)),
            "learningRate": float(learning_rate),
            "margin": float(margin),
            "mistakes": mistake_counts[-1] if mistake_counts else 0,
            "trainingTop1Accuracy": action_set_top1_accuracy(
                action_sets,
                self.score_many,
                value_tolerance=value_tolerance,
            ),
        }

    @classmethod
    def load(cls, path: str | Path) -> "TransitionActionSetPerceptron":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = dict(payload.get("metadata") or {})
        return cls(
            weights={str(key): float(value) for key, value in dict(payload.get("weights") or {}).items()},
            bias=float(payload.get("bias", 0.0) or 0.0),
            seed=int(metadata.get("trainingSeed", 0) or 0),
            metadata=metadata,
        )


class TransitionPressureAwareActionSetPerceptron(TransitionLinearRanker):
    def __init__(
        self,
        *,
        default_weights: dict[str, float] | None = None,
        pressure_weights: dict[str, float] | None = None,
        default_bias: float = 0.0,
        pressure_bias: float = 0.0,
        seed: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            weights={},
            bias=0.0,
            seed=seed,
            metadata={
                "modelKind": "pressure_aware_action_set_perceptron",
                "gateMode": "v1_pressure_context",
                **dict(metadata or {}),
            },
        )
        self.default_weights = {str(key): float(value) for key, value in dict(default_weights or {}).items()}
        self.pressure_weights = {str(key): float(value) for key, value in dict(pressure_weights or {}).items()}
        self.default_bias = float(default_bias)
        self.pressure_bias = float(pressure_bias)

    def _selected_head_from_filtered_row(self, filtered_row: dict[str, Any]) -> str:
        return "pressure" if transition_defensive_pressure_from_feature_row(filtered_row) else "default"

    def selected_head(self, row: dict[str, Any]) -> str:
        filtered_row = self._drop_runtime_filtered_features(row)
        return self._selected_head_from_filtered_row(filtered_row)

    def score_transition(self, row: dict[str, float]) -> float:
        filtered_row = self._drop_runtime_filtered_features(row)
        if self._should_abstain_for_feature_novelty(filtered_row):
            return 0.0
        return self._score_with_head(
            filtered_row,
            self._selected_head_from_filtered_row(filtered_row),
        )

    def score_many(self, rows: list[dict[str, float]]) -> list[float]:
        return [self.score_transition(row) for row in rows]

    def _score_with_head(self, row: dict[str, Any], head: str) -> float:
        weights, bias = self._head_parameters(head)
        return float(bias + sum(weights.get(str(key), 0.0) * float(value) for key, value in row.items()))

    def _head_parameters(self, head: str) -> tuple[dict[str, float], float]:
        if str(head) == "pressure":
            return self.pressure_weights, self.pressure_bias
        if str(head) == "default":
            return self.default_weights, self.default_bias
        raise ValueError(f"unknown transition evaluator head: {head!r}")

    def fit_pairwise(
        self,
        pairs: list[dict[str, Any]],
        *,
        epochs: int = 5,
        learning_rate: float = 0.05,
        margin: float = 0.5,
    ) -> dict[str, Any]:
        clean_pairs = []
        for pair in pairs:
            if not isinstance(pair, dict) or not pair.get("goodFeatures") or not pair.get("badFeatures"):
                continue
            filtered_good = self._drop_runtime_filtered_features(dict(pair["goodFeatures"]))
            filtered_bad = self._drop_runtime_filtered_features(dict(pair["badFeatures"]))
            clean_pairs.append((
                filtered_good,
                filtered_bad,
                self._selected_head_from_filtered_row(filtered_good),
                self._selected_head_from_filtered_row(filtered_bad),
            ))
        losses: list[float] = []
        mistake_counts: list[int] = []
        updated_head_counts = {"default": 0, "pressure": 0}
        for _ in range(max(1, int(epochs))):
            loss_total = 0.0
            mistakes = 0
            for filtered_good, filtered_bad, good_head, bad_head in clean_pairs:
                good_score = self._score_with_head(filtered_good, good_head)
                bad_score = self._score_with_head(filtered_bad, bad_head)
                loss = max(0.0, float(margin) - (good_score - bad_score))
                if loss <= 0.0:
                    continue
                loss_total += loss
                mistakes += 1
                if good_head == bad_head:
                    weights, _bias = self._head_parameters(good_head)
                    delta = _feature_delta(filtered_good, filtered_bad)
                    for key, value in delta.items():
                        weights[key] = weights.get(key, 0.0) + float(learning_rate) * float(value)
                    updated_head_counts[good_head] += 1
                else:
                    good_weights, _good_bias = self._head_parameters(good_head)
                    bad_weights, _bad_bias = self._head_parameters(bad_head)
                    for key, value in filtered_good.items():
                        good_weights[key] = (
                            good_weights.get(key, 0.0) + float(learning_rate) * float(value)
                        )
                    for key, value in filtered_bad.items():
                        bad_weights[key] = (
                            bad_weights.get(key, 0.0) - float(learning_rate) * float(value)
                        )
                    updated_head_counts[good_head] += 1
                    updated_head_counts[bad_head] += 1
            losses.append(loss_total / max(1, len(clean_pairs)))
            mistake_counts.append(mistakes)
        return {
            "kind": "transition_pressure_aware_pairwise_training",
            "pairCount": len(clean_pairs),
            "epochs": max(1, int(epochs)),
            "learningRate": float(learning_rate),
            "margin": float(margin),
            "loss": losses[-1] if losses else 0.0,
            "mistakes": mistake_counts[-1] if mistake_counts else 0,
            "mistakesByEpoch": mistake_counts,
            "updatedHeadCounts": updated_head_counts,
        }

    def fit_action_sets(
        self,
        rows: list[dict[str, Any]],
        *,
        epochs: int = 5,
        learning_rate: float = 1.0,
        margin: float = 1.0,
        include_rollout_features: bool = True,
        value_tolerance: float = 1e-6,
    ) -> dict[str, Any]:
        raw_action_sets = transition_action_set_training_samples(
            rows,
            include_rollout_features=include_rollout_features,
        )
        action_sets = []
        for feature_rows, targets in raw_action_sets:
            filtered_feature_rows = [
                self._drop_runtime_filtered_features(row)
                for row in feature_rows
            ]
            heads = [
                self._selected_head_from_filtered_row(row)
                for row in filtered_feature_rows
            ]
            action_sets.append((filtered_feature_rows, targets, heads))
        mistake_counts: list[int] = []
        updated_head_counts = {"default": 0, "pressure": 0}
        for _ in range(max(1, int(epochs))):
            mistakes = 0
            for filtered_feature_rows, targets, heads in action_sets:
                if len(filtered_feature_rows) < 2:
                    continue
                scores = [
                    self._score_with_head(row, heads[index])
                    for index, row in enumerate(filtered_feature_rows)
                ]
                predicted_index = max(range(len(scores)), key=lambda index: (scores[index], -index))
                best_value = max(targets)
                best_index = max(range(len(targets)), key=lambda index: (targets[index], -index))
                rival_indexes = [
                    index
                    for index, target in enumerate(targets)
                    if index != best_index and target < best_value - float(value_tolerance)
                ]
                rival_index = (
                    max(rival_indexes, key=lambda index: (scores[index], -index))
                    if rival_indexes
                    else predicted_index
                )
                if (
                    targets[predicted_index] >= best_value - float(value_tolerance)
                    and float(scores[best_index]) - float(scores[rival_index]) >= float(margin)
                ):
                    continue
                good_head = heads[best_index]
                bad_head = heads[rival_index]
                good_row = filtered_feature_rows[best_index]
                bad_row = filtered_feature_rows[rival_index]
                if good_head == bad_head:
                    weights, _bias = self._head_parameters(good_head)
                    delta = _feature_delta(good_row, bad_row)
                    for key, value in delta.items():
                        weights[key] = weights.get(key, 0.0) + float(learning_rate) * float(value)
                    updated_head_counts[good_head] += 1
                else:
                    good_weights, _good_bias = self._head_parameters(good_head)
                    bad_weights, _bad_bias = self._head_parameters(bad_head)
                    for key, value in good_row.items():
                        good_weights[key] = (
                            good_weights.get(key, 0.0) + float(learning_rate) * float(value)
                        )
                    for key, value in bad_row.items():
                        bad_weights[key] = (
                            bad_weights.get(key, 0.0) - float(learning_rate) * float(value)
                        )
                    updated_head_counts[good_head] += 1
                    updated_head_counts[bad_head] += 1
                mistakes += 1
            mistake_counts.append(mistakes)
        return {
            "kind": "transition_pressure_aware_action_set_training",
            "actionSetRowCount": len(action_sets),
            "epochs": max(1, int(epochs)),
            "learningRate": float(learning_rate),
            "margin": float(margin),
            "valueTolerance": float(value_tolerance),
            "mistakes": mistake_counts[-1] if mistake_counts else 0,
            "mistakesByEpoch": mistake_counts,
            "updatedHeadCounts": updated_head_counts,
            "trainingTop1Accuracy": self._cached_action_set_top1_accuracy(
                action_sets,
                value_tolerance=value_tolerance,
            ),
        }

    def _cached_action_set_top1_accuracy(
        self,
        action_sets: Iterable[tuple[list[dict[str, float]], list[float], list[str]]],
        *,
        value_tolerance: float = 1e-6,
    ) -> float:
        action_set_list = list(action_sets)
        if not action_set_list:
            return 0.0
        correct = 0
        for feature_rows, targets, heads in action_set_list:
            scores = [
                (
                    0.0
                    if self._should_abstain_for_feature_novelty(row)
                    else self._score_with_head(row, heads[index])
                )
                for index, row in enumerate(feature_rows)
            ]
            predicted_index = max(range(len(scores)), key=lambda index: (scores[index], -index))
            if targets[predicted_index] >= max(targets) - float(value_tolerance):
                correct += 1
        return correct / len(action_set_list)

    def save(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({
                "metadata": self.metadata,
                "defaultWeights": self.default_weights,
                "pressureWeights": self.pressure_weights,
                "defaultBias": self.default_bias,
                "pressureBias": self.pressure_bias,
            }, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "TransitionPressureAwareActionSetPerceptron":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = dict(payload.get("metadata") or {})
        return cls(
            default_weights={
                str(key): float(value)
                for key, value in dict(payload.get("defaultWeights") or {}).items()
            },
            pressure_weights={
                str(key): float(value)
                for key, value in dict(payload.get("pressureWeights") or {}).items()
            },
            default_bias=float(payload.get("defaultBias", 0.0) or 0.0),
            pressure_bias=float(payload.get("pressureBias", 0.0) or 0.0),
            seed=int(metadata.get("trainingSeed", 0) or 0),
            metadata=metadata,
        )


def transition_action_set_training_samples(
    rows: Iterable[dict[str, Any]],
    *,
    include_rollout_features: bool = True,
) -> list[tuple[list[dict[str, float]], list[float]]]:
    action_sets: list[tuple[list[dict[str, float]], list[float]]] = []
    for row in rows:
        validate_transition_row(row)
        before_features = dict(row.get("beforeStateFeatures") or {})
        feature_rows: list[dict[str, float]] = []
        targets: list[float] = []
        for action in list(row.get("actions") or []):
            action_targets = dict(action.get("targets") or {})
            if "transitionValue" not in action_targets:
                continue
            feature_rows.append(action_transition_feature_row(
                before_features=before_features,
                action=action,
                include_rollout_features=include_rollout_features,
            ))
            targets.append(float(action_targets["transitionValue"]))
        if len(feature_rows) >= 2:
            action_sets.append((feature_rows, targets))
    return action_sets


def action_set_top1_accuracy(
    action_sets: Iterable[tuple[list[dict[str, float]], list[float]]],
    score_many: Any,
    *,
    value_tolerance: float = 1e-6,
) -> float:
    action_set_list = list(action_sets)
    if not action_set_list:
        return 0.0
    correct = 0
    for feature_rows, targets in action_set_list:
        scores = list(score_many(feature_rows))
        predicted_index = max(range(len(scores)), key=lambda index: (scores[index], -index))
        if targets[predicted_index] >= max(targets) - float(value_tolerance):
            correct += 1
    return correct / len(action_set_list)


def _transition_action_value(action: dict[str, Any]) -> float:
    targets = dict(action.get("targets") or {})
    if "transitionValue" in targets:
        try:
            return float(targets.get("transitionValue", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return transition_value_from_targets(targets)


def _runtime_digest_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _runtime_digest_training_features_from_tags(tags: Iterable[Any]) -> dict[str, float]:
    features: dict[str, float] = {}
    for raw_tag in tags:
        tag = str(raw_tag).strip()
        if not tag or tag.upper() in {"P1", "P2"}:
            continue
        if any(tag.startswith(prefix) for prefix in FORBIDDEN_FEATURE_PREFIXES):
            continue
        features[tag] = 1.0
    return features


def _runtime_digest_examples(digest: Any) -> list[dict[str, Any]]:
    if isinstance(digest, dict):
        examples = digest.get("examples")
        if isinstance(examples, list):
            return [dict(item) for item in examples if isinstance(item, dict)]
        audits = digest.get("changedChoiceAudits")
        if isinstance(audits, list):
            return [dict(item) for item in audits if isinstance(item, dict)]
        return []
    if isinstance(digest, list):
        return [dict(item) for item in digest if isinstance(item, dict)]
    return []


def _runtime_digest_slice_tags(example: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    difficulty = str(example.get("difficulty") or example.get("opponentKind") or "").strip().lower()
    if difficulty:
        tags.append(difficulty.capitalize())
    firstness = str(
        example.get("tracePlayerFirstness")
        or example.get("firstness")
        or example.get("modelFirstness")
        or ""
    ).strip().lower()
    if firstness == "first":
        tags.append("First")
    elif firstness == "second":
        tags.append("Second")
    kind_pair = str(example.get("kindPair") or "").strip()
    if kind_pair:
        tags.append(f"kindPair:{kind_pair}")
    for flag in example.get("flags") or []:
        flag_text = str(flag).strip()
        if flag_text:
            tags.append(flag_text)
    return tags


def derive_runtime_regression_digest_pairwise_rows(
    digest: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build direct hard pairs from runtime choice flips that regressed battle outcomes.

    These pairs use only action/deck/plan tags as trainable features. Diagnostic fields
    such as seat labels and score reversals stay in metadata/reason tags so they cannot
    become non-runtime crutches for the evaluator.
    """
    pairs: list[dict[str, Any]] = []
    examples = _runtime_digest_examples(digest)
    reason_counts: Counter[str] = Counter()
    kind_pair_counts: Counter[str] = Counter()
    skipped_reasons: Counter[str] = Counter()
    for index, example in enumerate(examples):
        baseline_label = str(example.get("baselineLabel") or "").strip()
        selected_label = str(example.get("selectedLabel") or "").strip()
        if not baseline_label or not selected_label:
            skipped_reasons["missing_action_label"] += 1
            continue
        score_delta_without = _runtime_digest_float(example.get("scoreDeltaWithoutTransition"))
        score_delta_with = _runtime_digest_float(example.get("scoreDeltaWithTransition"))
        if not (score_delta_without < 0.0 and score_delta_with > 0.0):
            skipped_reasons["not_negative_margin_flip"] += 1
            continue
        baseline_features = _runtime_digest_training_features_from_tags(example.get("baselineTags") or [])
        selected_features = _runtime_digest_training_features_from_tags(example.get("selectedTags") or [])
        if not baseline_features or not selected_features:
            skipped_reasons["missing_trainable_tags"] += 1
            continue
        flags = [
            str(flag).strip()
            for flag in example.get("flags") or []
            if str(flag).strip()
        ]
        reasons = sorted(set([
            "runtime_regression_negative_margin_flip",
            "transition_score_reversed_negative_raw_margin",
            *flags,
        ]))
        for reason in reasons:
            reason_counts[reason] += 1
        kind_pair = str(example.get("kindPair") or f"{baseline_label}->{selected_label}").strip()
        if kind_pair:
            kind_pair_counts[kind_pair] += 1
        seed = example.get("seed", index)
        row_id = f"ctruntimepair:{seed}:{index}:{baseline_label}:{selected_label}"
        pairs.append({
            "schemaVersion": COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION,
            "featureMode": "digest_action_tags_no_rollout",
            "rowId": row_id,
            "parentRowId": f"runtime-regression-digest:{seed}:{index}",
            "goodActionId": baseline_label,
            "badActionId": selected_label,
            "baselineActionId": baseline_label,
            "modelSelectedActionId": selected_label,
            "kindPair": kind_pair,
            "playerDeckId": str(example.get("playerDeckId") or ""),
            "difficulty": str(example.get("difficulty") or ""),
            "scoreDeltaWithoutTransition": float(score_delta_without),
            "scoreDeltaWithTransition": float(score_delta_with),
            "baselineTransitionEvaluator": _runtime_digest_float(
                example.get("baselineTransitionEvaluator")
            ),
            "selectedTransitionEvaluator": _runtime_digest_float(
                example.get("selectedTransitionEvaluator")
            ),
            "valueGap": float(max(abs(score_delta_without), 1e-6)),
            "reasonTags": reasons,
            "sliceTags": _runtime_digest_slice_tags(example),
            "goodFeatures": baseline_features,
            "badFeatures": selected_features,
        })
    return pairs, {
        "kind": "runtime_regression_digest_pairwise_rows",
        "exampleCount": int(len(examples)),
        "pairCount": int(len(pairs)),
        "skippedCount": int(sum(skipped_reasons.values())),
        "skippedReasons": dict(sorted(skipped_reasons.items())),
        "reasonCounts": dict(sorted(reason_counts.items())),
        "kindPairCounts": dict(sorted(kind_pair_counts.items())),
        "featureMode": "digest_action_tags_no_rollout",
    }


def _mcts_high_audit_reports_rows(reports: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report in reports:
        if isinstance(report, dict):
            for row in report.get("rows") or []:
                if isinstance(row, dict):
                    rows.append(dict(row))
        elif isinstance(report, list):
            for row in report:
                if isinstance(row, dict):
                    rows.append(dict(row))
    return rows


def _mcts_high_audit_action_summary_features(action_summary: dict[str, Any]) -> dict[str, float]:
    features = {
        key: value
        for key, value in _runtime_digest_training_features_from_tags(action_summary.get("tags") or []).items()
        if not (key.startswith("enemy_pressure_") or key.startswith("enemy_field_"))
    }
    action_kind = str(action_summary.get("actionKind") or "").strip()
    if action_kind:
        features[f"action:{action_kind}"] = 1.0
    return features


def _mcts_high_audit_before_features(
    baseline_summary: dict[str, Any],
    selected_summary: dict[str, Any],
) -> dict[str, float]:
    before: dict[str, float] = {}
    for action_summary in (baseline_summary, selected_summary):
        for raw_tag in action_summary.get("tags") or []:
            tag = str(raw_tag).strip()
            if tag.startswith("enemy_pressure_") or tag.startswith("enemy_field_"):
                before[tag] = 1.0
    return before


def _mcts_high_audit_action_signature(action_summary: dict[str, Any]) -> str:
    payload = action_summary.get("actionPayload")
    try:
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except TypeError:
        payload_text = str(payload)
    return "|".join([
        str(action_summary.get("label") or ""),
        str(action_summary.get("actionKind") or ""),
        payload_text,
    ])


def _mcts_high_audit_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _mcts_high_audit_allowed_key(
    *,
    player_deck_id: Any,
    seat_label: Any,
    opponent_deck_id: Any,
    choice_audit_index: Any,
    kind_pair: Any,
) -> str:
    return "|".join([
        str(player_deck_id or "").strip(),
        str(seat_label or "").strip(),
        str(opponent_deck_id or "").strip(),
        str(choice_audit_index or "").strip(),
        str(kind_pair or "").strip(),
    ])


def mcts_high_audit_allowed_keys_from_quality_report(report: dict[str, Any]) -> set[str]:
    """Return changed audit keys explicitly listed by the paired-regression quality report."""
    allowed: set[str] = set()
    high_audit_findings = dict(report.get("highAuditFindings") or {})
    for row in high_audit_findings.get("rows") or []:
        if not isinstance(row, dict):
            continue
        row_key = dict(row.get("rowKey") or {})
        player_deck_id = row_key.get("playerDeckId")
        seat_label = row_key.get("seatLabel")
        opponent_deck_id = row_key.get("opponentDeckId")
        for audit in row.get("changedAudits") or []:
            if not isinstance(audit, dict):
                continue
            allowed.add(_mcts_high_audit_allowed_key(
                player_deck_id=player_deck_id,
                seat_label=seat_label,
                opponent_deck_id=opponent_deck_id,
                choice_audit_index=audit.get("choiceAuditIndex"),
                kind_pair=audit.get("kindPair"),
            ))
    return allowed


def _mcts_high_audit_target_component(action_kind: str, kind_pair: str = "") -> str:
    action_text = str(action_kind or "").strip().lower()
    context_text = f"{action_text} {kind_pair}".lower()
    if action_text in {"place_colorless_mana", "play_to_base", "move_card", "skip_mana"}:
        return "resourceValue"
    if action_text in {"attack", "attack_force", "attack_player"}:
        return "pressureValue"
    if action_text in {"block", "block_none", "end_turn"}:
        return "survivalValue"
    if "mana" in context_text or "resource" in context_text or "move_field_to_base" in context_text:
        return "resourceValue"
    if "attack" in context_text or "face" in context_text or "force_break" in context_text:
        return "pressureValue"
    if "block" in context_text or "lethal" in context_text or "survival" in context_text:
        return "survivalValue"
    if action_text == "play_card":
        return "tempoValue"
    return "planValue"


def _mcts_high_audit_targets(
    value: float,
    *,
    reason: str,
    action_kind: str = "",
    kind_pair: str = "",
) -> dict[str, float | str]:
    component = _mcts_high_audit_target_component(action_kind, kind_pair)
    targets: dict[str, float | str] = {key: 0.0 for key in TARGET_COMPONENT_KEYS}
    targets[component] = float(value)
    targets["transitionValue"] = transition_value_from_targets(targets)
    targets["mctsHighAuditTargetReason"] = str(reason)
    targets["mctsHighAuditTargetComponent"] = str(component)
    return targets


def _mcts_high_audit_transition_action(
    *,
    action_id: str,
    action_summary: dict[str, Any],
    target_value: float,
    target_reason: str,
    kind_pair: str = "",
) -> dict[str, Any]:
    action_kind = str(action_summary.get("actionKind") or "")
    return {
        "actionId": str(action_id),
        "actionKind": action_kind,
        "actionLabel": str(action_summary.get("label") or f"action:{action_kind}"),
        "actionPayload": copy.deepcopy(action_summary.get("actionPayload") or {}),
        "actionFeatures": _mcts_high_audit_action_summary_features(action_summary),
        "afterStateFeatures": {},
        "rolloutSummary": {},
        "targets": _mcts_high_audit_targets(
            float(target_value),
            reason=target_reason,
            action_kind=action_kind,
            kind_pair=kind_pair,
        ),
        "sourceScore": _mcts_high_audit_float(action_summary.get("score")),
        "sourceScoreWithoutTransition": _mcts_high_audit_float(action_summary.get("scoreWithoutTransition")),
        "sourceScoreWithoutTransitionAndBoundedMcts": _mcts_high_audit_float(
            action_summary.get("scoreWithoutTransitionAndBoundedMcts")
        ),
    }


def _mcts_high_audit_state_tags(
    row: dict[str, Any],
    audit: dict[str, Any],
    baseline_summary: dict[str, Any],
    selected_summary: dict[str, Any],
) -> list[str]:
    tags: set[str] = {"mcts_high_audit_regression"}
    opponent_kind = str(row.get("opponentKind") or "").strip().lower()
    if opponent_kind:
        tags.add(opponent_kind.capitalize())
    if str(row.get("modelDeckId") or "").strip().lower() == "aice":
        tags.add("AICE")
    kind_pair = str(audit.get("kindPair") or "").strip()
    if kind_pair:
        tags.add(f"kindPair:{kind_pair}")
    raw_delta = _mcts_high_audit_float(audit.get("scoreDeltaWithoutTransitionAndBoundedMcts"))
    final_delta = _mcts_high_audit_float(audit.get("scoreDeltaWithTransition"))
    if raw_delta < 0.0:
        tags.add("mcts_selected_lower_raw_than_baseline")
    if final_delta < 0.0:
        tags.add("mcts_selected_lower_final_than_baseline")
    for action_summary in (baseline_summary, selected_summary):
        for raw_tag in action_summary.get("tags") or []:
            tag = str(raw_tag).strip()
            if tag.startswith("enemy_pressure_") or tag.startswith("enemy_field_"):
                tags.add(tag)
            if tag == "enemy_pressure_near_player_lethal":
                tags.add("enemy_ready_pressure")
    return sorted(tag for tag in tags if tag.upper() not in {"P1", "P2"})


def _mcts_high_audit_firstness(row: dict[str, Any], audit: dict[str, Any]) -> str:
    for source in (audit, row):
        raw = (
            source.get("learnerFirstness")
            or source.get("tracePlayerFirstness")
            or source.get("playerFirstness")
            or source.get("player_firstness")
        )
        firstness = str(raw or "").strip().lower()
        if firstness in {"first", "second"}:
            return firstness
        features = dict(source.get("beforeStateFeatures") or {})
        try:
            is_first = float(features.get("learner_is_first_player", 0.0) or 0.0) > 0.5
            is_second = float(features.get("learner_is_second_player", 0.0) or 0.0) > 0.5
        except (TypeError, ValueError):
            continue
        if is_first and not is_second:
            return "first"
        if is_second and not is_first:
            return "second"
    return "unknown"


def _merge_target_shaping_summary(summary: dict[str, Any], report: dict[str, Any]) -> None:
    for key in (
        "rowCount",
        "actionCount",
        "shapedRowCount",
        "shapedActionCount",
        "skippedNonAiceRowCount",
        "skippedNonWinningTraceRowCount",
        "adjustedActionCount",
    ):
        if key in report:
            summary[key] = int(summary.get(key, 0) or 0) + int(report.get(key, 0) or 0)
    label_counts = summary.setdefault("labelCounts", Counter())
    for label, count in dict(report.get("labelCounts") or {}).items():
        label_counts[str(label)] += int(count)
    component_sums = summary.setdefault("componentDeltaSums", Counter())
    for component, delta in dict(report.get("componentDeltaSums") or {}).items():
        component_sums[str(component)] += float(delta)


def _target_shaping_summary_for_report(summary: dict[str, Any]) -> dict[str, Any]:
    out = {
        str(key): int(value)
        for key, value in summary.items()
        if key not in {"labelCounts", "componentDeltaSums"} and isinstance(value, (bool, int, float))
    }
    out["labelCounts"] = dict(sorted(Counter(summary.get("labelCounts") or {}).items()))
    out["componentDeltaSums"] = dict(sorted(Counter(summary.get("componentDeltaSums") or {}).items()))
    return out


def _enforce_mcts_high_audit_outcome_preservation(
    row: dict[str, Any],
    *,
    minimum_gap: float,
) -> dict[str, Any]:
    actions = list(row.get("actions") or [])
    if len(actions) < 2:
        return {"kind": "mcts_high_audit_outcome_preservation", "adjustedActionCount": 0}
    baseline_action = actions[0]
    baseline_value = transition_value_from_targets(dict(baseline_action.get("targets") or {}))
    max_nonbaseline_value = float(baseline_value) - float(max(minimum_gap, 1e-6))
    adjusted_count = 0
    component_delta_sums: Counter[str] = Counter()
    kind_pair = str(row.get("kindPair") or "")
    for action in actions[1:]:
        targets = dict(action.get("targets") or {})
        action_value = transition_value_from_targets(targets)
        if action_value <= max_nonbaseline_value:
            continue
        delta = float(max_nonbaseline_value - action_value)
        component = _mcts_high_audit_target_component(str(action.get("actionKind") or ""), kind_pair)
        targets[component] = float(targets.get(component, 0.0) or 0.0) + delta
        targets["mctsHighAuditOutcomePreservation"] = {
            "preferredActionId": str(baseline_action.get("actionId") or ""),
            "minimumGap": float(minimum_gap),
            "appliedDelta": float(delta),
            "component": component,
        }
        targets["transitionValue"] = transition_value_from_targets(targets)
        action["targets"] = targets
        component_delta_sums[component] += delta
        adjusted_count += 1
    if adjusted_count:
        tags = {str(tag) for tag in list(row.get("stateTags") or [])}
        tags.add("mcts_high_audit_outcome_preservation")
        row["stateTags"] = sorted(tags)
    return {
        "kind": "mcts_high_audit_outcome_preservation",
        "adjustedActionCount": int(adjusted_count),
        "componentDeltaSums": dict(sorted(component_delta_sums.items())),
    }


def derive_mcts_high_audit_counterfactual_rows(
    reports: Iterable[Any],
    *,
    allowed_audit_keys: set[str] | None = None,
    include_transition_changes: bool = False,
    include_top_choices: bool = False,
    min_abs_value_gap: float = 1.0,
    require_known_firstness: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Build transition rows and hard pairs from MCTS-primary high-audit root flips.

    The baseline action is treated as the good counterfactual action because the
    source rows are paired runtime regressions. Seat labels remain report
    metadata and are deliberately not emitted as trainable features or slice tags.
    """
    transition_rows: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    source_rows = _mcts_high_audit_reports_rows(reports)
    skipped_reasons: Counter[str] = Counter()
    kind_pair_counts: Counter[str] = Counter()
    target_component_counts: Counter[str] = Counter()
    chosen_target_component_counts: Counter[str] = Counter()
    selected_lower_raw = 0
    selected_lower_final = 0
    changed_by_mcts = 0
    changed_by_transition = 0
    omitted_top_choice_count = 0
    counts_by_firstness: Counter[str] = Counter()
    immediate_shaping_summary: dict[str, Any] = {}
    aice_combo_shaping_summary: dict[str, Any] = {}
    outcome_preservation_summary: dict[str, Any] = {}
    for row_index, source_row in enumerate(source_rows):
        audits = list(source_row.get("modelChoiceDecisionAudits") or [])
        for audit_index, audit in enumerate(audits):
            if not isinstance(audit, dict):
                continue
            changed_mcts = bool(audit.get("changedByBoundedMcts"))
            changed_transition = bool(audit.get("changedByTransition"))
            if not changed_mcts and not (include_transition_changes and changed_transition):
                continue
            baseline_summary = dict(audit.get("baselineAction") or {})
            selected_summary = dict(audit.get("selectedAction") or {})
            if not baseline_summary or not selected_summary:
                skipped_reasons["missing_baseline_or_selected_action"] += 1
                continue
            choice_index = audit.get("choiceAuditIndex", audit_index)
            baseline_kind = str(baseline_summary.get("actionKind") or "baseline")
            selected_kind = str(selected_summary.get("actionKind") or "selected")
            baseline_action_id = f"baseline:{choice_index}:{baseline_kind}"
            selected_action_id = f"selected:{choice_index}:{selected_kind}"
            raw_delta = _mcts_high_audit_float(audit.get("scoreDeltaWithoutTransitionAndBoundedMcts"))
            final_delta = _mcts_high_audit_float(audit.get("scoreDeltaWithTransition"))
            value_gap = max(abs(raw_delta), abs(min(final_delta, 0.0)), float(min_abs_value_gap))
            kind_pair = str(audit.get("kindPair") or f"{baseline_kind}->{selected_kind}").strip()
            allowlist_key = _mcts_high_audit_allowed_key(
                player_deck_id=source_row.get("modelDeckId"),
                seat_label=source_row.get("modelSide"),
                opponent_deck_id=source_row.get("opponentDeckId"),
                choice_audit_index=choice_index,
                kind_pair=kind_pair,
            )
            if allowed_audit_keys is not None and allowlist_key not in allowed_audit_keys:
                skipped_reasons["not_in_paired_regression_allowlist"] += 1
                continue
            reason_tags = sorted(set([
                "mcts_high_audit_baseline_counterfactual",
                "mcts_root_replacement_regression",
                f"kindPair:{kind_pair}",
                "selected_lower_raw_than_baseline" if raw_delta < 0.0 else "",
                "selected_lower_final_than_baseline" if final_delta < 0.0 else "",
            ]) - {""})
            actions = [
                _mcts_high_audit_transition_action(
                    action_id=baseline_action_id,
                    action_summary=baseline_summary,
                    target_value=value_gap,
                    target_reason="baseline_action_counterfactual_good",
                    kind_pair=kind_pair,
                ),
                _mcts_high_audit_transition_action(
                    action_id=selected_action_id,
                    action_summary=selected_summary,
                    target_value=0.0,
                    target_reason="mcts_selected_regressed_action",
                    kind_pair=kind_pair,
                ),
            ]
            seen_signatures = {
                _mcts_high_audit_action_signature(baseline_summary),
                _mcts_high_audit_action_signature(selected_summary),
            }
            for top_index, top_summary_raw in enumerate(audit.get("topChoices") or []):
                if not isinstance(top_summary_raw, dict):
                    continue
                top_summary = dict(top_summary_raw)
                signature = _mcts_high_audit_action_signature(top_summary)
                if signature in seen_signatures:
                    continue
                if not include_top_choices:
                    omitted_top_choice_count += 1
                    continue
                seen_signatures.add(signature)
                top_kind = str(top_summary.get("actionKind") or "top")
                actions.append(_mcts_high_audit_transition_action(
                    action_id=f"top:{choice_index}:{top_index}:{top_kind}",
                    action_summary=top_summary,
                    target_value=0.0,
                    target_reason="mcts_high_audit_context_candidate",
                    kind_pair=kind_pair,
                ))

            row_id = (
                f"ctmcts:{source_row.get('seed', row_index)}:"
                f"{source_row.get('modelDeckId', 'deck')}:{source_row.get('opponentDeckId', 'opponent')}:"
                f"{choice_index}"
            )
            before_features = _mcts_high_audit_before_features(baseline_summary, selected_summary)
            firstness = _mcts_high_audit_firstness(source_row, audit)
            if require_known_firstness and firstness not in {"first", "second"}:
                skipped_reasons["unknown_firstness"] += 1
                continue
            if firstness == "first":
                before_features["learner_is_first_player"] = 1.0
                before_features["learner_is_second_player"] = 0.0
            elif firstness == "second":
                before_features["learner_is_first_player"] = 0.0
                before_features["learner_is_second_player"] = 1.0
            transition_row = {
                "schemaVersion": COUNTERFACTUAL_TRANSITION_SCHEMA_VERSION,
                "rowId": str(row_id),
                "seed": source_row.get("seed"),
                "source": "mcts_high_audit_regression",
                "playerDeckId": str(source_row.get("modelDeckId") or ""),
                "opponentDeckId": str(source_row.get("opponentDeckId") or ""),
                "opponentKind": str(source_row.get("opponentKind") or ""),
                "seatLabel": str(source_row.get("modelSide") or ""),
                "learnerFirstness": firstness,
                "beforeStateFeatures": before_features,
                "stateTags": _mcts_high_audit_state_tags(
                    source_row,
                    audit,
                    baseline_summary,
                    selected_summary,
                ),
                "battleChosenActionId": baseline_action_id,
                "modelSelectedActionId": selected_action_id,
                "sourceChoiceAuditIndex": audit.get("sourceChoiceAuditIndex"),
                "choiceAuditIndex": choice_index,
                "kindPair": kind_pair,
                "scoreDeltaWithTransition": float(final_delta),
                "scoreDeltaWithoutTransition": _mcts_high_audit_float(audit.get("scoreDeltaWithoutTransition")),
                "scoreDeltaWithoutTransitionAndBoundedMcts": float(raw_delta),
                "changedByBoundedMcts": bool(changed_mcts),
                "changedByTransition": bool(changed_transition),
                "actions": actions,
            }
            shaped_rows, immediate_report = apply_immediate_payoff_target_shaping([transition_row])
            _merge_target_shaping_summary(immediate_shaping_summary, immediate_report)
            shaped_rows, aice_report = apply_aice_combo_plan_target_shaping(
                shaped_rows,
                require_aice=True,
                winning_traces_only=False,
            )
            _merge_target_shaping_summary(aice_combo_shaping_summary, aice_report)
            transition_row = shaped_rows[0]
            outcome_report = _enforce_mcts_high_audit_outcome_preservation(
                transition_row,
                minimum_gap=float(value_gap),
            )
            _merge_target_shaping_summary(outcome_preservation_summary, outcome_report)
            validate_transition_row(transition_row)
            transition_rows.append(transition_row)
            actions = list(transition_row.get("actions") or [])
            for action in actions:
                component = str(dict(action.get("targets") or {}).get("mctsHighAuditTargetComponent") or "")
                if component:
                    target_component_counts[component] += 1
            chosen_component = str(dict(actions[0].get("targets") or {}).get("mctsHighAuditTargetComponent") or "")
            if chosen_component:
                chosen_target_component_counts[chosen_component] += 1
            good_value = transition_value_from_targets(dict(actions[0].get("targets") or {}))
            bad_value = transition_value_from_targets(dict(actions[1].get("targets") or {}))
            pair_value_gap = max(float(value_gap), float(good_value - bad_value), float(min_abs_value_gap))
            pair = {
                "schemaVersion": COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION,
                "featureMode": "mcts_high_audit_action_tags_no_rollout",
                "rowId": f"ctmctspair:{row_id}:{baseline_action_id}:{selected_action_id}",
                "parentRowId": str(row_id),
                "goodActionId": baseline_action_id,
                "badActionId": selected_action_id,
                "baselineActionId": baseline_action_id,
                "modelSelectedActionId": selected_action_id,
                "kindPair": kind_pair,
                "valueGap": float(pair_value_gap),
                "scoreDeltaWithTransition": float(final_delta),
                "scoreDeltaWithoutTransitionAndBoundedMcts": float(raw_delta),
                "reasonTags": reason_tags,
                "sliceTags": _slice_tags_for_row(transition_row),
                "goodFeatures": action_transition_feature_row(
                    before_features=before_features,
                    action=actions[0],
                    include_rollout_features=False,
                ),
                "badFeatures": action_transition_feature_row(
                    before_features=before_features,
                    action=actions[1],
                    include_rollout_features=False,
                ),
            }
            pairs.append(pair)
            kind_pair_counts[kind_pair] += 1
            if raw_delta < 0.0:
                selected_lower_raw += 1
            if final_delta < 0.0:
                selected_lower_final += 1
            if changed_mcts:
                changed_by_mcts += 1
            if changed_transition:
                changed_by_transition += 1
            if firstness in {"first", "second"}:
                counts_by_firstness["First" if firstness == "first" else "Second"] += 1
            else:
                counts_by_firstness["unknown"] += 1
    return transition_rows, pairs, {
        "kind": "mcts_high_audit_counterfactual_dataset",
        "sourceReportRowCount": int(len(source_rows)),
        "rowCount": int(len(transition_rows)),
        "pairCount": int(len(pairs)),
        "skippedCount": int(sum(skipped_reasons.values())),
        "skippedReasons": dict(sorted(skipped_reasons.items())),
        "kindPairCounts": dict(sorted(kind_pair_counts.items())),
        "selectedLowerRawThanBaselineCount": int(selected_lower_raw),
        "selectedLowerFinalThanBaselineCount": int(selected_lower_final),
        "changedByBoundedMctsCount": int(changed_by_mcts),
        "changedByTransitionCount": int(changed_by_transition),
        "omittedUnlabeledTopChoiceCount": int(omitted_top_choice_count),
        "countsByFirstness": dict(sorted(counts_by_firstness.items())),
        "targetComponentCounts": dict(sorted(target_component_counts.items())),
        "chosenTargetComponentCounts": dict(sorted(chosen_target_component_counts.items())),
        "featureMode": "mcts_high_audit_action_tags_no_rollout",
        "immediatePayoffTargetShaping": _target_shaping_summary_for_report(immediate_shaping_summary),
        "aiceComboPlanTargetShaping": _target_shaping_summary_for_report(aice_combo_shaping_summary),
        "mctsHighAuditOutcomePreservation": _target_shaping_summary_for_report(outcome_preservation_summary),
        "allowedAuditKeyCount": None if allowed_audit_keys is None else int(len(allowed_audit_keys)),
        "includeTransitionChanges": bool(include_transition_changes),
        "includeTopChoices": bool(include_top_choices),
        "requireKnownFirstness": bool(require_known_firstness),
        "status": (
            "ready_for_reviewed_training_input"
            if transition_rows and not counts_by_firstness.get("unknown", 0)
            else "diagnostic_or_blocked"
        ),
    }


def derive_action_set_choice_audit_regression_pairwise_rows(
    rows: Iterable[dict[str, Any]],
    *,
    score_many: Any,
    include_rollout_features: bool = True,
    value_tolerance: float = 1e-6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return hard pairs that teach against model top1 flips that fail exact-root audit gates."""
    pairs: list[dict[str, Any]] = []
    row_count = 0
    evaluated_rows = 0
    skipped_rows = 0
    reason_counts: Counter[str] = Counter()
    skipped_reasons: Counter[str] = Counter()
    for row in rows:
        validate_transition_row(row)
        row_count += 1
        chosen_action_id = str(row.get("battleChosenActionId") or row.get("humanChosenActionId") or "")
        if not chosen_action_id:
            skipped_rows += 1
            skipped_reasons["missing_chosen_action_id"] += 1
            continue
        actions = [
            action
            for action in list(row.get("actions") or [])
            if "transitionValue" in dict(action.get("targets") or {})
        ]
        if len(actions) < 2:
            skipped_rows += 1
            skipped_reasons["fewer_than_two_scored_actions"] += 1
            continue
        old_index = next(
            (index for index, action in enumerate(actions) if str(action.get("actionId")) == chosen_action_id),
            None,
        )
        if old_index is None:
            skipped_rows += 1
            skipped_reasons["chosen_action_missing_from_action_set"] += 1
            continue
        before_features = dict(row.get("beforeStateFeatures") or {})
        feature_rows = [
            action_transition_feature_row(
                before_features=before_features,
                action=action,
                include_rollout_features=include_rollout_features,
            )
            for action in actions
        ]
        scores = list(score_many(feature_rows))
        if len(scores) != len(actions):
            raise ValueError("score_many returned a score count that does not match the action set")
        new_index = max(range(len(scores)), key=lambda index: (float(scores[index]), -index))
        if int(new_index) == int(old_index):
            evaluated_rows += 1
            continue
        old_action = actions[old_index]
        new_action = actions[new_index]
        old_negative = bool(immediate_payoff_negative_labels(row, old_action))
        new_negative = bool(immediate_payoff_negative_labels(row, new_action))
        introduced_negative = bool(new_negative and not old_negative)
        safety_conflict = immediate_payoff_safety_conflict_regression(row, old_action, new_action)
        lost_positive_labels = immediate_payoff_lost_positive_labels(row, old_action, new_action)
        target_delta = _transition_action_value(new_action) - _transition_action_value(old_action)
        target_regressed = target_delta < -float(value_tolerance)
        reasons: list[str] = []
        if introduced_negative:
            reasons.append("introduced_negative_action")
        if safety_conflict:
            reasons.append("safety_conflict_regression")
        if lost_positive_labels:
            reasons.append("lost_positive_action")
        if target_regressed:
            reasons.append("target_value_regression")
        evaluated_rows += 1
        if not reasons:
            continue
        for reason in reasons:
            reason_counts[reason] += 1
        reason_tags = sorted(set([
            "hard_action_set_choice_audit_regression",
            *reasons,
            *_pair_reason_tags(old_action, new_action),
        ]))
        pairs.append({
            "schemaVersion": COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION,
            "featureMode": "with_rollout" if include_rollout_features else "predictive_no_rollout",
            "rowId": f"ctauditpair:{row['rowId']}:{old_action['actionId']}:{new_action['actionId']}",
            "parentRowId": row["rowId"],
            "goodActionId": old_action["actionId"],
            "badActionId": new_action["actionId"],
            "chosenActionId": chosen_action_id,
            "modelSelectedActionId": new_action["actionId"],
            "valueGap": float(max(abs(target_delta), float(value_tolerance), 1e-6)),
            "targetDelta": float(target_delta),
            "oldEvaluatorScore": float(scores[old_index]),
            "newEvaluatorScore": float(scores[new_index]),
            "reasonTags": reason_tags,
            "lostPositiveLabels": lost_positive_labels,
            "sliceTags": _slice_tags_for_row(row),
            "goodFeatures": feature_rows[old_index],
            "badFeatures": feature_rows[new_index],
        })
    return pairs, {
        "kind": "action_set_choice_audit_regression_pairwise_rows",
        "rowCount": int(row_count),
        "evaluatedRows": int(evaluated_rows),
        "skippedRows": int(skipped_rows),
        "skippedReasons": dict(sorted(skipped_reasons.items())),
        "pairCount": len(pairs),
        "reasonCounts": dict(sorted(reason_counts.items())),
        "includeRolloutFeatures": bool(include_rollout_features),
        "valueTolerance": float(value_tolerance),
    }


def derive_baseline_constrained_action_set_pairwise_rows(
    rows: Iterable[dict[str, Any]],
    *,
    include_rollout_features: bool = True,
    value_tolerance: float = 1e-6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build hard pairs for every action made ineligible by the baseline constraint contract."""
    pairs: list[dict[str, Any]] = []
    row_count = 0
    evaluated_rows = 0
    skipped_rows = 0
    rows_with_ineligible_actions = 0
    ineligible_action_count = 0
    reason_counts: Counter[str] = Counter()
    skipped_reasons: Counter[str] = Counter()
    for row in rows:
        validate_transition_row(row)
        row_count += 1
        chosen_action_id = str(row.get("battleChosenActionId") or row.get("humanChosenActionId") or "")
        if not chosen_action_id:
            skipped_rows += 1
            skipped_reasons["missing_chosen_action_id"] += 1
            continue
        actions = [
            action
            for action in list(row.get("actions") or [])
            if "transitionValue" in dict(action.get("targets") or {})
        ]
        if len(actions) < 2:
            skipped_rows += 1
            skipped_reasons["fewer_than_two_scored_actions"] += 1
            continue
        baseline_index = next(
            (index for index, action in enumerate(actions) if str(action.get("actionId")) == chosen_action_id),
            None,
        )
        if baseline_index is None:
            skipped_rows += 1
            skipped_reasons["chosen_action_missing_from_action_set"] += 1
            continue

        baseline_action = actions[baseline_index]
        eligible_indexes: list[int] = []
        ineligible: list[tuple[int, list[str], list[str], float]] = []
        for index, action in enumerate(actions):
            reasons, lost_positive_labels, target_delta = _action_set_choice_regression_reasons(
                row,
                baseline_action,
                action,
                value_tolerance=float(value_tolerance),
            )
            if reasons:
                ineligible.append((index, reasons, lost_positive_labels, target_delta))
            else:
                eligible_indexes.append(index)
        if not eligible_indexes:
            skipped_rows += 1
            skipped_reasons["no_eligible_action"] += 1
            continue

        evaluated_rows += 1
        if not ineligible:
            continue
        rows_with_ineligible_actions += 1
        ineligible_action_count += len(ineligible)
        good_index = max(
            eligible_indexes,
            key=lambda index: (_transition_action_value(actions[index]), -index),
        )
        good_action = actions[good_index]
        before_features = dict(row.get("beforeStateFeatures") or {})
        good_features = action_transition_feature_row(
            before_features=before_features,
            action=good_action,
            include_rollout_features=include_rollout_features,
        )
        good_value = _transition_action_value(good_action)
        for bad_index, reasons, lost_positive_labels, _baseline_target_delta in ineligible:
            bad_action = actions[bad_index]
            for reason in reasons:
                reason_counts[reason] += 1
            bad_features = action_transition_feature_row(
                before_features=before_features,
                action=bad_action,
                include_rollout_features=include_rollout_features,
            )
            target_delta = _transition_action_value(bad_action) - good_value
            reason_tags = sorted(set([
                "baseline_constrained_action_set",
                *reasons,
                *_pair_reason_tags(good_action, bad_action),
            ]))
            pairs.append({
                "schemaVersion": COUNTERFACTUAL_TRANSITION_PAIR_SCHEMA_VERSION,
                "featureMode": "with_rollout" if include_rollout_features else "predictive_no_rollout",
                "rowId": f"ctconstraintpair:{row['rowId']}:{good_action['actionId']}:{bad_action['actionId']}",
                "parentRowId": row["rowId"],
                "goodActionId": good_action["actionId"],
                "badActionId": bad_action["actionId"],
                "chosenActionId": chosen_action_id,
                "baselineActionId": baseline_action["actionId"],
                "valueGap": float(max(abs(target_delta), float(value_tolerance), 1e-6)),
                "targetDelta": float(target_delta),
                "baselineTargetDelta": float(_baseline_target_delta),
                "reasonTags": reason_tags,
                "lostPositiveLabels": lost_positive_labels,
                "sliceTags": _slice_tags_for_row(row),
                "goodFeatures": good_features,
                "badFeatures": bad_features,
            })
    return pairs, {
        "kind": "baseline_constrained_action_set_pairwise_rows",
        "rowCount": int(row_count),
        "evaluatedRows": int(evaluated_rows),
        "skippedRows": int(skipped_rows),
        "skippedReasons": dict(sorted(skipped_reasons.items())),
        "rowsWithIneligibleActions": int(rows_with_ineligible_actions),
        "ineligibleActionCount": int(ineligible_action_count),
        "pairCount": len(pairs),
        "reasonCounts": dict(sorted(reason_counts.items())),
        "includeRolloutFeatures": bool(include_rollout_features),
        "valueTolerance": float(value_tolerance),
    }


def action_set_choice_audit_report(
    *,
    rows: Iterable[dict[str, Any]],
    score_many: Any,
    include_rollout_features: bool = True,
    value_tolerance: float = 1e-6,
    require_full_coverage: bool = True,
    max_samples: int = 40,
    selection_mode: str = "raw_score",
) -> dict[str, Any]:
    """Compare model top1 choices against exact-root baseline choices with payoff hard gates."""
    if str(selection_mode) not in {"raw_score", "baseline_constrained"}:
        raise ValueError(f"unsupported action-set choice audit selection_mode: {selection_mode!r}")
    materialized_rows = list(rows)
    evaluated_rows = 0
    skipped_rows = 0
    choice_change_count = 0
    ineligible_top_score_rows = 0
    old_negative_rows = 0
    new_negative_rows = 0
    fixed_negative_rows = 0
    introduced_negative_rows = 0
    safety_conflict_regression_rows = 0
    lost_positive_rows = 0
    target_regressed_rows = 0
    target_improved_rows = 0
    aice_rows = 0
    aice_choice_change_count = 0
    changed_samples: list[dict[str, Any]] = []
    regression_samples: list[dict[str, Any]] = []
    counts_by_difficulty_firstness: Counter[str] = Counter()
    skipped_reasons: Counter[str] = Counter()
    ineligible_top_score_reasons: Counter[str] = Counter()

    for row in materialized_rows:
        validate_transition_row(row)
        chosen_action_id = str(row.get("battleChosenActionId") or row.get("humanChosenActionId") or "")
        if not chosen_action_id:
            skipped_rows += 1
            skipped_reasons["missing_chosen_action_id"] += 1
            continue
        actions = [
            action
            for action in list(row.get("actions") or [])
            if "transitionValue" in dict(action.get("targets") or {})
        ]
        if len(actions) < 2:
            skipped_rows += 1
            skipped_reasons["fewer_than_two_scored_actions"] += 1
            continue
        old_index = next(
            (index for index, action in enumerate(actions) if str(action.get("actionId")) == chosen_action_id),
            None,
        )
        if old_index is None:
            skipped_rows += 1
            skipped_reasons["chosen_action_missing_from_action_set"] += 1
            continue
        before_features = dict(row.get("beforeStateFeatures") or {})
        feature_rows = [
            action_transition_feature_row(
                before_features=before_features,
                action=action,
                include_rollout_features=include_rollout_features,
            )
            for action in actions
        ]
        scores = list(score_many(feature_rows))
        if len(scores) != len(actions):
            raise ValueError("score_many returned a score count that does not match the action set")
        raw_top_index = max(range(len(scores)), key=lambda index: (float(scores[index]), -index))
        if str(selection_mode) == "baseline_constrained":
            new_index, blocked_top_reasons = _baseline_constrained_action_set_top1_index(
                row,
                actions,
                scores,
                baseline_index=old_index,
                value_tolerance=float(value_tolerance),
            )
            if int(new_index) != int(raw_top_index) and blocked_top_reasons:
                ineligible_top_score_rows += 1
                for reason in blocked_top_reasons:
                    ineligible_top_score_reasons[reason] += 1
        else:
            new_index = raw_top_index
            blocked_top_reasons = []
        old_action = actions[old_index]
        new_action = actions[new_index]
        raw_top_action = actions[raw_top_index]
        old_labels = immediate_payoff_action_labels(row, old_action)
        new_labels = immediate_payoff_action_labels(row, new_action)
        old_negative = bool(immediate_payoff_negative_labels(row, old_action))
        new_negative = bool(immediate_payoff_negative_labels(row, new_action))
        fixed_negative = bool(old_negative and not new_negative)
        introduced_negative = bool(new_negative and not old_negative)
        safety_conflict = immediate_payoff_safety_conflict_regression(row, old_action, new_action)
        lost_positive_labels = immediate_payoff_lost_positive_labels(row, old_action, new_action)
        old_value = _transition_action_value(old_action)
        new_value = _transition_action_value(new_action)
        target_delta = float(new_value - old_value)
        target_regressed = target_delta < -float(value_tolerance)
        target_improved = target_delta > float(value_tolerance)
        changed = int(new_index) != int(old_index)
        firstness = _row_firstness(row)
        firstness_label = firstness.capitalize() if firstness in {"first", "second"} else "Unknown"
        difficulty = str(row.get("opponentKind") or "unknown").strip().lower() or "unknown"
        counts_by_difficulty_firstness[f"{difficulty}|{firstness_label}"] += 1
        is_aice = str(row.get("playerDeckId") or "").strip().lower() == "aice"

        evaluated_rows += 1
        if is_aice:
            aice_rows += 1
        if old_negative:
            old_negative_rows += 1
        if new_negative:
            new_negative_rows += 1
        if fixed_negative:
            fixed_negative_rows += 1
        if introduced_negative:
            introduced_negative_rows += 1
        if safety_conflict:
            safety_conflict_regression_rows += 1
        if lost_positive_labels:
            lost_positive_rows += 1
        if target_regressed:
            target_regressed_rows += 1
        if target_improved:
            target_improved_rows += 1
        if changed:
            choice_change_count += 1
            if is_aice:
                aice_choice_change_count += 1

        sample = {
            "rowId": str(row.get("rowId") or ""),
            "battleCaseId": str(row.get("battleCaseId") or row.get("sourceBattleCaseId") or ""),
            "battleChoiceAuditSourceIndex": row.get("battleChoiceAuditSourceIndex"),
            "playerDeckId": str(row.get("playerDeckId") or ""),
            "opponentKind": str(row.get("opponentKind") or ""),
            "firstness": firstness_label,
            "changed": bool(changed),
            "oldActionId": str(old_action.get("actionId") or ""),
            "newActionId": str(new_action.get("actionId") or ""),
            "rawTopScoreActionId": str(raw_top_action.get("actionId") or ""),
            "topScoreBlocked": bool(int(new_index) != int(raw_top_index) and blocked_top_reasons),
            "topScoreBlockedReasons": list(blocked_top_reasons),
            "oldActionKind": str(old_action.get("actionKind") or ""),
            "newActionKind": str(new_action.get("actionKind") or ""),
            "oldEvaluatorScore": float(scores[old_index]),
            "newEvaluatorScore": float(scores[new_index]),
            "rawTopEvaluatorScore": float(scores[raw_top_index]),
            "scoreMargin": float(scores[new_index] - scores[old_index]),
            "oldLabels": old_labels,
            "newLabels": new_labels,
            "oldTransitionValue": old_value,
            "newTransitionValue": new_value,
            "targetDelta": target_delta,
            "fixedNegative": fixed_negative,
            "introducedNegative": introduced_negative,
            "safetyConflictRegression": safety_conflict,
            "lostPositive": bool(lost_positive_labels),
            "lostPositiveLabels": lost_positive_labels,
            "targetRegressed": target_regressed,
            "stateTags": [str(tag) for tag in list(row.get("stateTags") or [])],
        }
        if changed and len(changed_samples) < int(max_samples):
            changed_samples.append(sample)
        if (
            introduced_negative
            or safety_conflict
            or lost_positive_labels
            or target_regressed
        ) and len(regression_samples) < int(max_samples):
            regression_samples.append(sample)

    failure_reasons: list[str] = []
    if introduced_negative_rows:
        failure_reasons.append("introduced_negative_action")
    if safety_conflict_regression_rows:
        failure_reasons.append("safety_conflict_regression")
    if lost_positive_rows:
        failure_reasons.append("lost_positive_action")
    if target_regressed_rows:
        failure_reasons.append("target_value_regression")
    soft_skipped_rows = int(skipped_reasons.get("fewer_than_two_scored_actions", 0))
    hard_skipped_rows = max(0, int(skipped_rows) - soft_skipped_rows)
    if require_full_coverage and hard_skipped_rows:
        failure_reasons.append("skipped_rows")
    passed = bool(evaluated_rows > 0 and not failure_reasons)
    return {
        "kind": "counterfactual_transition_action_set_choice_audit",
        "selectionMode": str(selection_mode),
        "rowCount": len(materialized_rows),
        "evaluatedRows": int(evaluated_rows),
        "skippedRows": int(skipped_rows),
        "hardSkippedRows": int(hard_skipped_rows),
        "softSkippedRows": int(soft_skipped_rows),
        "skippedReasons": dict(sorted(skipped_reasons.items())),
        "choiceChangeCount": int(choice_change_count),
        "ineligibleTopScoreRows": int(ineligible_top_score_rows),
        "ineligibleTopScoreReasons": dict(sorted(ineligible_top_score_reasons.items())),
        "oldNegativeRows": int(old_negative_rows),
        "newNegativeRows": int(new_negative_rows),
        "fixedNegativeRows": int(fixed_negative_rows),
        "introducedNegativeRows": int(introduced_negative_rows),
        "safetyConflictRegressionRows": int(safety_conflict_regression_rows),
        "lostPositiveRows": int(lost_positive_rows),
        "targetRegressedRows": int(target_regressed_rows),
        "targetImprovedRows": int(target_improved_rows),
        "aiceRows": int(aice_rows),
        "aiceChoiceChangeCount": int(aice_choice_change_count),
        "countsByDifficultyFirstness": dict(sorted(counts_by_difficulty_firstness.items())),
        "failureReasons": failure_reasons,
        "passedDiagnosticAudit": passed,
        "includeRolloutFeatures": bool(include_rollout_features),
        "requireFullCoverage": bool(require_full_coverage),
        "valueTolerance": float(value_tolerance),
        "changedSamples": changed_samples,
        "regressionSamples": regression_samples,
    }


def action_set_offline_gate_report(
    *,
    train_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    score_many: Any,
    include_rollout_features: bool,
    required_slices: Iterable[str] = ("Second", "AICE", "enemy_ready_pressure", "Normal"),
    min_train_accuracy: float = 0.68,
    min_holdout_accuracy: float = 0.60,
    min_slice_accuracy: float = 0.55,
    min_slice_count: int = 0,
    value_tolerance: float = 1e-6,
) -> dict[str, Any]:
    train_action_sets = transition_action_set_training_samples(
        train_rows,
        include_rollout_features=include_rollout_features,
    )
    holdout_action_sets = transition_action_set_training_samples(
        holdout_rows,
        include_rollout_features=include_rollout_features,
    )
    slice_accuracy: dict[str, float] = {}
    slice_counts: dict[str, int] = {}
    for tag in required_slices:
        slice_rows = [row for row in holdout_rows if str(tag) in set(_slice_tags_for_row(row))]
        slice_sets = transition_action_set_training_samples(
            slice_rows,
            include_rollout_features=include_rollout_features,
        )
        slice_counts[str(tag)] = len(slice_sets)
        slice_accuracy[str(tag)] = (
            action_set_top1_accuracy(slice_sets, score_many, value_tolerance=value_tolerance)
            if slice_sets
            else 0.0
        )
    train_accuracy = action_set_top1_accuracy(
        train_action_sets,
        score_many,
        value_tolerance=value_tolerance,
    )
    holdout_accuracy = action_set_top1_accuracy(
        holdout_action_sets,
        score_many,
        value_tolerance=value_tolerance,
    )
    passed = (
        train_accuracy >= float(min_train_accuracy)
        and holdout_accuracy >= float(min_holdout_accuracy)
        and all(value >= float(min_slice_accuracy) for value in slice_accuracy.values())
        and all(count >= max(0, int(min_slice_count)) for count in slice_counts.values())
    )
    return {
        "kind": "counterfactual_transition_action_set_offline_gate",
        "trainActionSetRowCount": len(train_action_sets),
        "holdoutActionSetRowCount": len(holdout_action_sets),
        "trainActionSetTop1Accuracy": train_accuracy,
        "holdoutActionSetTop1Accuracy": holdout_accuracy,
        "sliceActionSetTop1Accuracy": slice_accuracy,
        "sliceActionSetCounts": slice_counts,
        "sliceMinimumCount": max(0, int(min_slice_count)),
        "valueTolerance": float(value_tolerance),
        "passedActionSetGate": passed,
    }


def _feature_delta(good: dict[str, Any], bad: dict[str, Any]) -> dict[str, float]:
    keys = set(good) | set(bad)
    return {
        key: float(good.get(key, 0.0) or 0.0) - float(bad.get(key, 0.0) or 0.0)
        for key in keys
    }


class CounterfactualTransitionCollector:
    def __init__(
        self,
        *,
        extractor: Any,
        horizon_actions: int = 32,
        horizon_turns: int = 2,
        max_actions_per_state: int = 32,
    ) -> None:
        self.extractor = extractor
        self.horizon_actions = max(1, int(horizon_actions))
        self.horizon_turns = max(1, int(horizon_turns))
        self.max_actions_per_state = max(1, int(max_actions_per_state))

    def collect_state_row(
        self,
        engine: Any,
        *,
        seed: int,
        source: str,
        player_deck_id: str,
        opponent_deck_id: str,
        model_side: str,
        state_index: int,
        opponent_kind: str = "unknown",
        force_include_actions: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        active = getattr(engine.state, "active", None)
        player_index = _player_index(engine, active)
        before_features = _without_forbidden_features(self.extractor.features_for_state(engine, active))
        before_snapshot = _life_resource_snapshot(engine, active)
        actions = []
        selected_actions = list(engine.legal_actions())[: self.max_actions_per_state]
        seen_action_ids = {_action_id(action) for action in selected_actions}
        for forced_action in list(force_include_actions or []):
            forced_action_id = _action_id(forced_action)
            if forced_action_id not in seen_action_ids:
                selected_actions.append(forced_action)
                seen_action_ids.add(forced_action_id)
        for action in selected_actions:
            action_features = _without_forbidden_features(
                _extract_transition_action_features(self.extractor, engine, active, action)
            )
            clone = _clone_engine(engine)
            clone_player = _player_at(clone, player_index)
            terminal_winner = None
            timeout = False
            try:
                clone.apply(copy.deepcopy(action))
                immediate_player = _player_at(clone, player_index) or clone_player
                after_features = _without_forbidden_features(self.extractor.features_for_state(clone, immediate_player))
                rollout_actions, timeout = _roll_forward(clone, self.horizon_actions)
            except Exception as exc:
                terminal_winner = getattr(exc, "winner", None)
                rollout_actions = 0
                after_features = _without_forbidden_features(self.extractor.features_for_state(clone, clone_player))
            clone_player = _player_at(clone, player_index) or clone_player
            rollout_summary = _rollout_summary(
                before=before_snapshot,
                after=_life_resource_snapshot(clone, clone_player),
                horizon_actions=rollout_actions,
                horizon_turns=self.horizon_turns,
                terminal_winner=terminal_winner,
                timeout=timeout,
            )
            targets = _targets_from_rollout_summary(
                rollout_summary,
                model_player=clone_player,
                action_kind=str(getattr(action, "kind", "")),
                before_state_features=before_features,
                action_features=action_features,
            )
            actions.append({
                "actionId": _action_id(action),
                "actionKind": str(getattr(action, "kind", "unknown")),
                "actionPayload": dict(getattr(action, "payload", {}) or {}),
                "actionFeatures": action_features,
                "afterStateFeatures": after_features,
                "rolloutSummary": rollout_summary,
                "targets": targets,
            })
        row = {
            "schemaVersion": COUNTERFACTUAL_TRANSITION_SCHEMA_VERSION,
            "rowId": f"ctv1:{seed}:{source}:{model_side}:{getattr(engine.state, 'turn', 0)}:{state_index}",
            "seed": int(seed),
            "source": str(source),
            "playerDeckId": str(player_deck_id),
            "opponentDeckId": str(opponent_deck_id),
            "opponentKind": str(opponent_kind),
            "modelSide": str(model_side),
            "turn": int(getattr(engine.state, "turn", 0) or 0),
            "phase": str(getattr(engine.state, "phase", "unknown")),
            "activeSide": str(getattr(active, "name", model_side)),
            "opponentBehaviorProfile": _observed_behavior_profile(engine, active),
            "stateTags": _state_tags(before_features),
            "beforeStateFeatures": before_features,
            "actions": actions,
        }
        validate_transition_row(row)
        return row


def _clone_engine(engine: Any) -> Any:
    clone = copy.deepcopy(engine)
    if hasattr(clone, "state") and hasattr(clone.state, "engine"):
        clone.state.engine = clone
    if hasattr(clone, "rebind_passive_modifiers"):
        clone.rebind_passive_modifiers()
    return clone


def _player_index(engine: Any, player: Any) -> int:
    try:
        return list(getattr(engine.state, "players", [])).index(player)
    except Exception:
        return 0


def _player_at(engine: Any, index: int) -> Any:
    players = list(getattr(getattr(engine, "state", None), "players", []) or [])
    if 0 <= index < len(players):
        return players[index]
    return getattr(getattr(engine, "state", None), "active", None)


def _roll_forward(engine: Any, action_budget: int) -> tuple[int, bool]:
    actions_taken = 0
    budget = max(0, int(action_budget))
    for _ in range(budget):
        active = getattr(engine.state, "active", None)
        policy = engine.policy_for(active) if hasattr(engine, "policy_for") else None
        if policy is None or not hasattr(policy, "choose"):
            break
        action = _choose_rollout_action_without_transition_recursion(policy, engine)
        engine.apply(copy.deepcopy(action))
        actions_taken += 1
    return actions_taken, False


def _choose_rollout_action_without_transition_recursion(policy: Any, engine: Any) -> Any:
    if not hasattr(policy, "transition_evaluator_weight"):
        return policy.choose(engine)
    previous_weight = getattr(policy, "transition_evaluator_weight")
    try:
        policy.transition_evaluator_weight = 0.0
        return policy.choose(engine)
    finally:
        policy.transition_evaluator_weight = previous_weight


def _life_resource_snapshot(engine: Any, player: Any) -> dict[str, float]:
    players = list(getattr(getattr(engine, "state", None), "players", []) or [])
    opponent = next((candidate for candidate in players if candidate is not player), None)
    ready_base_color_counts = _ready_base_color_counts(player)
    hand_color_demand = _hand_color_demand_counts(player)
    ready_colored_base_count = sum(
        count for color, count in ready_base_color_counts.items() if color != _color_key(Color.COLORLESS)
    )
    colored_hand_demand = sum(hand_color_demand.values())
    return {
        "ownLife": float(getattr(player, "life", 0) or 0),
        "enemyLife": float(getattr(opponent, "life", 0) or 0),
        "ownForceLife": _force_life(player),
        "enemyForceLife": _force_life(opponent),
        "ownHand": float(len(getattr(player, "hand", []) or [])),
        "ownBase": float(len(getattr(player, "base", []) or [])),
        "ownField": float(len(getattr(player, "field", []) or [])),
        "enemyField": float(len(getattr(opponent, "field", []) or [])),
        "ownColoredBase": _colored_base_count(player),
        "ownReadyColoredBase": float(ready_colored_base_count),
        "ownReadyDemandMatch": _ready_demand_match_count(ready_base_color_counts, hand_color_demand),
        "ownColoredHandDemand": float(colored_hand_demand),
        "ownNoReadyColoredDemand": 1.0 if colored_hand_demand > 0 and ready_colored_base_count <= 0 else 0.0,
        "ownReadyDp": _ready_dp(player),
        "enemyReadyDp": _ready_dp(opponent),
    }


def _force_life(player: Any) -> float:
    if player is None:
        return 0.0
    return float(sum(
        float(getattr(force, "life", 0) or 0)
        for force in getattr(player, "forces", []) or []
        if not getattr(force, "destroyed", False)
    ))


def _ready_dp(player: Any) -> float:
    if player is None:
        return 0.0
    return float(sum(
        float(getattr(item, "dp", getattr(getattr(item, "card", None), "dp", 0)) or 0)
        for item in getattr(player, "field", []) or []
        if not getattr(item, "rested", False)
    ))


def _colored_base_count(player: Any) -> float:
    if player is None:
        return 0.0
    return float(sum(
        1
        for item in getattr(player, "base", []) or []
        if _card_mana_color(item) is not Color.COLORLESS
    ))


def _ready_base_color_counts(player: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if player is None:
        return counts
    for item in getattr(player, "base", []) or []:
        if getattr(item, "rested", False):
            continue
        key = _color_key(_card_mana_color(item))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _hand_color_demand_counts(player: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if player is None:
        return counts
    for item in getattr(player, "hand", []) or []:
        card = getattr(item, "card", item)
        for color, amount in dict(getattr(card, "cost", {}) or {}).items():
            resolved = _coerce_color(color)
            if resolved is None or resolved is Color.COLORLESS or int(amount or 0) <= 0:
                continue
            key = _color_key(resolved)
            counts[key] = counts.get(key, 0) + int(amount or 0)
    return counts


def _ready_demand_match_count(ready_counts: dict[str, int], demand_counts: dict[str, int]) -> float:
    return float(sum(
        min(int(ready_counts.get(color, 0)), int(demand_counts.get(color, 0)))
        for color in demand_counts
        if color != _color_key(Color.COLORLESS)
    ))


def _card_mana_color(item: Any) -> Color:
    override = getattr(item, "mana_color_override", None)
    if override is not None:
        resolved_override = _coerce_color(override)
        if resolved_override is not None:
            return resolved_override
    card = getattr(item, "card", item)
    mana_color = getattr(card, "mana_color", None)
    resolved = _coerce_color(mana_color)
    if resolved is not None:
        return resolved
    for color, amount in dict(getattr(card, "cost", {}) or {}).items():
        resolved_cost = _coerce_color(color)
        if resolved_cost is not None and resolved_cost is not Color.COLORLESS and int(amount or 0) > 0:
            return resolved_cost
    return Color.COLORLESS


def _coerce_color(value: Any) -> Color | None:
    if isinstance(value, Color):
        return value
    if value is None:
        return None
    try:
        return Color(value)
    except Exception:
        pass
    try:
        return Color[str(value).upper()]
    except Exception:
        return None


def _color_key(color: Color) -> str:
    return str(getattr(color, "name", color)).lower()


def _rollout_summary(
    *,
    before: dict[str, float],
    after: dict[str, float],
    horizon_actions: int,
    horizon_turns: int,
    terminal_winner: Any,
    timeout: bool,
) -> dict[str, Any]:
    return {
        "horizonActions": int(horizon_actions),
        "horizonTurns": int(horizon_turns),
        "winner": getattr(terminal_winner, "name", None) if terminal_winner is not None else None,
        "terminal": terminal_winner is not None,
        "ownLifeDelta": after["ownLife"] - before["ownLife"],
        "ownForceLifeDelta": after["ownForceLife"] - before["ownForceLife"],
        "enemyLifeDelta": after["enemyLife"] - before["enemyLife"],
        "enemyForceLifeDelta": after["enemyForceLife"] - before["enemyForceLife"],
        "handDelta": after["ownHand"] - before["ownHand"],
        "baseDelta": after["ownBase"] - before["ownBase"],
        "ownFieldDelta": after["ownField"] - before["ownField"],
        "enemyFieldDelta": after["enemyField"] - before["enemyField"],
        "coloredBaseDelta": after["ownColoredBase"] - before["ownColoredBase"],
        "readyColoredBaseDelta": after["ownReadyColoredBase"] - before["ownReadyColoredBase"],
        "readyDemandMatchDelta": after["ownReadyDemandMatch"] - before["ownReadyDemandMatch"],
        "coloredHandDemandDelta": after["ownColoredHandDemand"] - before["ownColoredHandDemand"],
        "noReadyColoredDemandAfter": after["ownNoReadyColoredDemand"],
        "ownReadyBlockerDpDelta": after["ownReadyDp"] - before["ownReadyDp"],
        "enemyReadyDpDelta": after["enemyReadyDp"] - before["enemyReadyDp"],
        "lethalRiskAfter": 1.0 if after["ownLife"] <= max(0.0, after["enemyReadyDp"]) else 0.0,
        "timeout": bool(timeout),
    }


def _targets_from_rollout_summary(
    summary: dict[str, Any],
    *,
    model_player: Any,
    action_kind: str = "",
    before_state_features: dict[str, float] | None = None,
    action_features: dict[str, float] | None = None,
) -> dict[str, float]:
    winner = summary.get("winner")
    model_name = getattr(model_player, "name", None)
    terminal_value = 100.0 if winner and winner == model_name else (-100.0 if winner else 0.0)
    before_features = dict(before_state_features or {})
    defensive_pressure = (
        float(summary.get("lethalRiskAfter", 0.0) or 0.0) > 0.0
        or float(before_features.get("enemy_pressure_high_player_risk", 0.0) or 0.0) > 0.0
        or float(before_features.get("enemy_pressure_near_player_lethal", 0.0) or 0.0) > 0.0
    )
    ready_blocker_value = float(summary.get("ownReadyBlockerDpDelta", 0.0) or 0.0) if defensive_pressure else 0.0
    survival_value = (
        float(summary.get("ownLifeDelta", 0.0) or 0.0)
        + 0.5 * float(summary.get("ownForceLifeDelta", 0.0) or 0.0)
        + ready_blocker_value
        - 4.0 * float(summary.get("lethalRiskAfter", 0.0) or 0.0)
    )
    pressure_value = (
        -float(summary.get("enemyLifeDelta", 0.0) or 0.0)
        - float(summary.get("enemyForceLifeDelta", 0.0) or 0.0)
    )
    plan_value = (
        1.5 * float(summary.get("coloredBaseDelta", 0.0) or 0.0)
        + float(summary.get("readyDemandMatchDelta", 0.0) or 0.0)
        + 0.5 * float(summary.get("readyColoredBaseDelta", 0.0) or 0.0)
        - 1.5 * float(summary.get("noReadyColoredDemandAfter", 0.0) or 0.0)
    )
    features = dict(action_features or {})
    full_chimera_colorless_fix = (
        str(action_kind) == "place_colorless_mana"
        and float(features.get("place_colorless_mana_supports_chimera_color_fix", 0.0) or 0.0) > 0.0
        and float(features.get("place_colorless_mana_ignores_missing_hand_color", 0.0) or 0.0) <= 0.0
    )
    if full_chimera_colorless_fix:
        plan_value = max(0.0, plan_value)
    if str(action_kind) == "skip_mana":
        before_base_count = float(before_features.get("own_base_count", 1.0) or 0.0)
        if before_base_count <= 0.05:
            plan_value -= 8.0
        if float(before_features.get("own_no_ready_colored_mana_for_hand", 0.0) or 0.0) > 0.0:
            plan_value -= 2.0
    enemy_field_delta = float(summary.get("enemyFieldDelta", 0.0) or 0.0)
    tempo_value = (
        -float(summary.get("enemyReadyDpDelta", 0.0) or 0.0)
        + max(0.0, -enemy_field_delta)
    )
    resource_value = (
        float(summary.get("baseDelta", 0.0) or 0.0)
        + 0.1 * float(summary.get("handDelta", 0.0) or 0.0)
        + 0.5 * float(summary.get("coloredBaseDelta", 0.0) or 0.0)
    )
    timeout_penalty = 10.0 if summary.get("timeout") else 0.0
    targets = {
        "terminalValue": terminal_value,
        "survivalValue": survival_value,
        "pressureValue": pressure_value,
        "planValue": plan_value,
        "tempoValue": tempo_value,
        "resourceValue": resource_value,
        "timeoutPenalty": timeout_penalty,
    }
    targets["transitionValue"] = transition_value_from_targets(targets)
    return targets


def _observed_behavior_profile(engine: Any, player: Any) -> dict[str, float]:
    profiles = getattr(engine, "observed_action_profile_by_player_side", {}) or {}
    if not isinstance(profiles, dict):
        return {"attackRate": 0.0, "facePressureRate": 0.0, "baseGrowthRate": 0.0}
    side = _side_name(player)
    profile = profiles.get(side, {}) or {}
    if not isinstance(profile, dict):
        return {"attackRate": 0.0, "facePressureRate": 0.0, "baseGrowthRate": 0.0}
    action_count = float(profile.get("opponent_action_count", 0.0) or 0.0)
    attack_count = float(profile.get("opponent_attack_count", 0.0) or 0.0)
    face_count = float(profile.get("opponent_attack_player_count", 0.0) or 0.0)
    base_growth_count = (
        float(profile.get("opponent_move_field_to_base_count", 0.0) or 0.0)
        + float(profile.get("opponent_play_to_base_count", 0.0) or 0.0)
    )
    return {
        "attackRate": attack_count / max(1.0, action_count),
        "facePressureRate": face_count / max(1.0, attack_count),
        "baseGrowthRate": base_growth_count / max(1.0, action_count),
    }


def _side_name(player: Any) -> str:
    side = getattr(player, "side", None)
    if side is not None:
        return str(getattr(side, "name", side)).upper()
    return str(getattr(player, "name", ""))


def _state_tags(features: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    if float(features.get("enemy_pressure_high_player_risk", 0.0) or 0.0) > 0.0:
        tags.append("enemy_ready_pressure")
    if float(features.get("own_force_life_total", 1.0) or 1.0) <= 0.25:
        tags.append("low_force_life")
    return tags


def _action_id(action: Any) -> str:
    payload = dict(getattr(action, "payload", {}) or {})
    parts = [str(getattr(action, "kind", "unknown"))]
    for key in sorted(payload):
        parts.append(f"{key}={payload[key]}")
    return ":".join(parts)
