from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
import traceback
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from zz.ai import RandomLegalPolicy
from zz.engine import BASE_CAP, GameOver
from zz.enums import AreaType, AttackTargetKind, CardType, Color, Keyword, TriggerTiming
from zz.effects import EffectTiming
from zz.greedy_ai import GreedyLegalPolicy
from zz.model import Action
from zz.current_policy_runtime import (
    action_identities_from_row,
    actor_logits_from_runtime_scores,
    select_current_policy_top,
)
from zz.rl_action_vocab import decision_kind_for_action
from zz.runtime_aux_compose import clamp_runtime_aux_residual, runtime_aux_max_correction_for_scorer
from zz.sim import play_one_game
from zz.turn_planner import choose_plan_from_candidates, generate_candidate_plans_from_action_choices


MODEL_KIND = "linear_q"
MODEL_VERSION = 1
DEEP_LOOKAHEAD_WEIGHT = 4.0
DEEP_MAX_LOOKAHEAD_ACTIONS = 24
DEEP_LOOKAHEAD_DEPTH = 2
DEEP_LOOKAHEAD_BRANCH_WIDTH = 4
DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY = True
DEEP_HUMANLIKE_PRIOR_WEIGHT = 0.0
OBSERVED_OPPONENT_FEATURE_VERSION = "opponent_action_profile_v1"
OBSERVED_OPPONENT_MODEL_FEATURE_FLAG = "observedOpponentModelFeatures"
PUBLIC_DEEP_V2_PLANNER_ARCHITECTURE = "public_deep_v2_planner"
PUBLIC_DEEP_V2_STATE_VALUE_HEAD_VERSION = "deep_v2_multitask_heads_v1"
PUBLIC_DEEP_V2_RERANK_HEAD_VERSION = "public_deep_v2_rerank_head_v1"
PUBLIC_DEEP_V2_RERANK_RUNTIME_GUARD_VERSION = "public_deep_v2_rerank_runtime_guard_v1"
PUBLIC_DEEP_V2_RERANK_MAX_RUNTIME_WEIGHT = 0.2
PUBLIC_DEEP_V2_SEMANTIC_BRIDGE_VERSION = "public_deep_v2_semantic_bridge_v1"
PUBLIC_DEEP_V2_UNDERSTANDING_RUNTIME_VERSION = "public_deep_v2_understanding_runtime_v1"
PUBLIC_DEEP_V2_UNDERSTANDING_MAX_RUNTIME_WEIGHT = 0.5

DEFAULT_BATTLE_MODEL_CANDIDATES = [
    Path("data/ai_training/deep_p2_specialist_v1_latest/best_greedy.pt"),
    Path("data/ai_training/deep_weak_chimera_distilled_wide_v1/latest.pt"),
    Path("data/ai_training/quality_tactical_latest/best_league.json"),
    Path("data/ai_training/quality_checkpoint_pool_latest/best_league.json"),
    Path("data/ai_models/rl_linear_latest.json"),
]

GREEDY_PRIOR_WEIGHTS = {
    "action:play_to_base": 1.2,
    "action:play_card": 1.0,
    "action:attack": 0.9,
    "action:move_card": 0.75,
    "action:activate_flash_ability": 0.65,
    "action:place_colorless_mana": 0.4,
    "action:swap_mana_color": 0.35,
    "action:skip_mana": -0.2,
    "action:flash_pass": -0.25,
    "action:end_turn": -0.5,
    "is_attack": 0.45,
    "is_board_action": 0.25,
    "is_mana_action": 0.1,
    "is_end_or_pass": -0.15,
    "target_player": 1.0,
    "target_force": 0.3,
    "target_minion": 0.1,
    "target_lethal_player": 3.0,
    "target_lethal_force": 1.0,
    "attack_has_player_target": 0.35,
    "attack_has_lethal_player_target": 2.0,
    "attack_can_destroy_force": 0.8,
    "attack_with_reawaken_self_refresh": 0.6,
    "attack_nonlethal_with_low_base": -1.25,
    "attack_while_low_life_no_forces": -3.0,
    "attack_without_forces_under_enemy_pressure": -4.0,
    "attack_exposes_lethal_next_turn": -8.0,
    "attack_low_dp_into_larger_blocker": -2.0,
    "attack_loses_to_larger_blocker_without_pressure": -4.0,
    "attack_suicide_into_larger_blocker_without_pressure": -5.0,
    "target_life": -0.2,
    "decision:blocker": 0.15,
    "block:none": -0.2,
    "play_card_is_minion": 0.2,
    "play_card_is_magic": 0.05,
    "play_card_has_effect": 0.1,
    "play_card_cost": -0.05,
    "move_base_to_field": 0.3,
    "move_field_to_base": 0.25,
    "move_field_to_base_builds_mana": 0.45,
    "move_field_to_base_under_curve": 0.75,
    "move_field_to_base_future_play": 0.55,
    "move_field_to_base_matches_hand_color": 0.45,
    "move_field_to_base_restores_missing_hand_color": 1.0,
    "move_field_to_base_protects_high_value_attacker": 1.1,
    "move_field_to_base_under_enemy_pressure": -2.0,
    "move_field_to_base_exposes_lethal_pressure": -7.0,
    "move_field_to_base_spends_force_life_exchange_wall": -3.0,
    "move_base_to_field_spends_ready_mana": -0.15,
    "move_base_to_field_with_playable_hand": -0.5,
    "move_base_to_field_can_attack_player": 0.35,
    "move_base_to_field_colored_mana": -0.8,
    "move_base_to_field_only_ready_color_for_hand": -2.5,
    "move_base_to_field_cannot_block": -0.9,
    "move_base_to_field_low_impact_mana_minion": -2.0,
    "move_base_to_field_delays_force_life_exchange": -4.0,
    "own_ready_color_matches_hand_demand": 0.45,
    "own_no_ready_colored_mana_for_hand": -0.85,
    "own_playable_non_base_hand_count": 0.25,
    "own_field_to_base_candidate_count": 0.15,
    "swap_mana_to_hand_demand": 0.05,
    "swap_mana_to_missing_hand_color": 0.1,
    "swap_mana_enables_playable_hand_card": 0.2,
    "swap_mana_fallback_unsticks_hand": 1.0,
    "swap_mana_delays_base_growth": -1.0,
    "play_card_target_effect_no_eligible_targets": -4.0,
    "play_card_beneficial_no_own_target": -4.0,
    "play_card_beneficial_only_enemy_target": -5.0,
    "play_card_harmful_target_only_own": -4.0,
    "play_card_harmful_no_enemy_target": -2.0,
    "play_card_harmful_enemy_target_available": 0.25,
    "play_card_defensive_reactive_on_own_turn": -8.0,
    "play_card_defensive_reactive_on_enemy_turn": 0.8,
    "play_card_defensive_reactive_attack_payoff": 0.5,
    "play_card_exchange_player_force_life": 0.8,
    "play_card_force_life_exchange_sets_enemy_low_life": 3.0,
    "play_card_force_life_exchange_has_followup_damage": 4.0,
    "attack_spends_force_life_exchange_combo_wall": -4.0,
    "block_none_loses_force_life_exchange_resource": -4.0,
    "blocker_preserves_force_life_exchange_resource": 2.0,
}

HARMFUL_TARGET_EFFECT_TEMPLATES = {
    "destroy_targets",
    "force_block",
    "move_to_base_targets",
    "rest_targets",
    "return_to_hand",
}

BENEFICIAL_TARGET_EFFECT_TEMPLATES = {
    "grant_keyword",
    "grant_unblockable",
    "heal_targets",
    "refresh_targets",
}

DEFENSIVE_REACTIVE_EFFECT_TEMPLATES = {
    "prevent_player_damage",
    "prevent_force_damage",
}

MIXED_TARGET_KINDS = {
    "any_minion",
    "any_minion_or_force",
}


def humanlike_action_prior(features: dict[str, float]) -> float:
    score = 0.0
    turn = float(features.get("turn_normalized", 0.0)) * 30.0
    base_count = float(features.get("own_base_count", 0.0)) * 10.0
    under_curve = bool(float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0)
    early_low_base = turn <= 7.0 and base_count < 6.0
    if float(features.get("move_field_to_base", 0.0)) > 0.0:
        score += 0.75
        if under_curve or early_low_base:
            score += 0.9
        if float(features.get("move_field_to_base_future_play", 0.0)) > 0.0:
            score += 0.65
        if float(features.get("move_field_to_base_matches_hand_color", 0.0)) > 0.0:
            score += 0.55
        if float(features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0:
            score += 1.45
        if (
            float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0
            and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
        ):
            score += 1.1
    if float(features.get("move_base_to_field", 0.0)) > 0.0:
        if early_low_base:
            score -= 1.0
        if float(features.get("move_base_to_field_spends_ready_mana", 0.0)) > 0.0:
            score -= 0.75
        if float(features.get("move_base_to_field_with_playable_hand", 0.0)) > 0.0:
            score -= 0.8
        if float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0:
            score -= 0.9
        if float(features.get("move_base_to_field_only_ready_color_for_hand", 0.0)) > 0.0:
            score -= 2.4
        if float(features.get("move_base_to_field_cannot_block", 0.0)) > 0.0:
            score -= 0.8
        if float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0:
            score -= 2.0
        if float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0:
            score -= 0.65
    if float(features.get("attack_nonlethal_with_low_base", 0.0)) > 0.0:
        score -= 0.9
    if (
        float(features.get("action:end_turn", 0.0)) > 0.0
        and float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0
    ):
        score -= 0.7
    return score


def target_selection_prior(features: dict[str, float]) -> float:
    if features.get("decision:attack_target", 0.0):
        score = 0.0
        if float(features.get("target_player_damage_prevented_by_force_kai", 0.0)) > 0.0:
            score -= 18.0
        if float(features.get("target_low_enemy_life_pressure_player", 0.0)) > 0.0:
            score += 12.0
        if float(features.get("target_force_id:force_kai", 0.0)) > 0.0:
            score += 4.0
        return score
    if not features.get("decision:generic_target", 0.0):
        return 0.0
    if float(features.get("target_force_life_exchange_search_payoff", 0.0)) > 0.0:
        score = 12.0
        score += float(features.get("target_force_life_exchange_search_delta", 0.0)) * 18.0
        if float(features.get("target_force_life_exchange_search_near_cast", 0.0)) > 0.0:
            score += 4.0
        return score
    if float(features.get("target_effect:exchange_player_force_life", 0.0)) > 0.0:
        score = 0.0
        if float(features.get("target_own", 0.0)) > 0.0 and float(features.get("target_is_force", 0.0)) > 0.0:
            target_life = float(features.get("target_life", 0.0))
            score += (1.0 - target_life) * 8.0
            score += float(features.get("target_force_life_exchange_delta", 0.0)) * 18.0
            if float(features.get("target_force_life_exchange_combo_payoff", 0.0)) > 0.0:
                score += 8.0
            if float(features.get("target_force_life_exchange_followup_damage", 0.0)) > 0.0:
                score += 4.0
        return score
    if float(features.get("target_kind:ally_base", 0.0)) > 0.0:
        score = 0.0
        score -= float(features.get("target_base_value", 0.0)) * 14.0
        if float(features.get("target_base_mana_token", 0.0)) > 0.0:
            score += 6.0
        if float(features.get("target_base_only_ready_color_for_hand", 0.0)) > 0.0:
            score -= 8.0
        if float(features.get("target_base_protects_minion", 0.0)) > 0.0:
            score -= 3.0
        return score
    if float(features.get("target_kind:deck_base_minion", 0.0)) > 0.0:
        score = 0.0
        if float(features.get("target_base_minion", 0.0)) > 0.0:
            score += 2.0
        if float(features.get("target_matches_hand_color", 0.0)) > 0.0:
            score += 5.0
        if float(features.get("target_restores_missing_hand_color", 0.0)) > 0.0:
            score += 6.0
        return score
    if float(features.get("target_search_to_hand", 0.0)) > 0.0:
        score = float(features.get("target_search_value", 0.0)) * 12.0
        if float(features.get("target_search_combo_piece", 0.0)) > 0.0:
            score += 6.0
        if float(features.get("target_search_high_dp", 0.0)) > 0.0:
            score += 2.0
        return score
    is_harmful = float(features.get("target_effect_harmful", 0.0)) > 0.0
    is_beneficial = float(features.get("target_effect_beneficial", 0.0)) > 0.0
    is_defensive_reactive = float(features.get("target_effect_defensive_reactive", 0.0)) > 0.0
    is_enemy = float(features.get("target_enemy", 0.0)) > 0.0
    is_own = float(features.get("target_own", 0.0)) > 0.0
    is_ready = float(features.get("target_ready", 0.0)) > 0.0
    threat = (
        float(features.get("target_dp", 0.0)) * 1.2
        + float(features.get("target_bp", 0.0)) * 0.8
        + float(features.get("target_cost", 0.0)) * 0.5
    )
    score = 0.0
    if is_harmful:
        if is_own:
            score -= 12.0
        if is_enemy:
            score += 7.0 + threat
            if is_ready:
                score += 2.0
    elif is_enemy:
        score += threat
        if is_ready:
            score += 0.5
    elif is_beneficial and is_own:
        score += 1.0 + threat * 0.35
        if is_defensive_reactive and not is_ready:
            score += 5.0
    return score


def action_choices_after_preinference(choices: list[tuple[Any, dict[str, float]]]) -> list[tuple[Any, dict[str, float]]]:
    if _block_none_allows_lethal_with_available_blocker(choices):
        choices = [
            choice
            for choice in choices
            if float(choice[1].get("block_none_allows_lethal_player_damage", 0.0)) <= 0.0
        ]
    if _block_none_allows_turn_lethal_with_available_blocker(choices):
        choices = [
            choice
            for choice in choices
            if float(choice[1].get("block_none_allows_turn_lethal_player_damage", 0.0)) <= 0.0
        ]
    if _block_none_loses_force_exchange_resource_with_available_blocker(choices):
        choices = [
            choice
            for choice in choices
            if float(choice[1].get("block_none_loses_force_life_exchange_resource", 0.0)) <= 0.0
        ]
    if _force_life_exchange_play_available(choices):
        choices = [
            choice
            for choice in choices
            if _is_force_life_exchange_combo_play(choice[1])
            or float(choice[1].get("attack_has_lethal_player_target", 0.0)) > 0.0
        ]
    if _hold_defense_removal_available(choices):
        filtered_choices = [
            choice
            for choice in choices
            if not _is_low_pressure_nonlethal_face_attack_over_removal(choice[1])
        ]
        if filtered_choices:
            choices = filtered_choices
    safe_choices = [
        choice
        for choice in choices
        if not _action_choice_is_tactically_forbidden(choice[1])
    ]
    return safe_choices or choices


def target_choices_after_preinference(
        choices: list[tuple[Any, dict[str, float]]],
        *,
        min_n: int,
) -> list[tuple[Any, dict[str, float]]]:
    if not choices:
        return choices
    if any(float(features.get("target_effect_harmful", 0.0)) > 0.0 for _, features in choices):
        enemy_choices = [
            choice
            for choice in choices
            if float(choice[1].get("target_enemy", 0.0)) > 0.0
        ]
        if enemy_choices:
            return enemy_choices
        if min_n <= 0:
            return []
    if any(float(features.get("target_effect_beneficial", 0.0)) > 0.0 for _, features in choices):
        own_choices = [
            choice
            for choice in choices
            if float(choice[1].get("target_own", 0.0)) > 0.0
        ]
        if own_choices:
            return own_choices
        if min_n <= 0:
            return []
    return choices


def target_selection_player_for_context(engine: Any) -> Any:
    context = getattr(engine, "_target_selection_context", None)
    if isinstance(context, dict):
        source = context.get("source")
        owner = getattr(source, "owner", None)
        if owner is not None:
            return owner
    return getattr(getattr(engine, "state", None), "active", None)


def _block_none_allows_lethal_with_available_blocker(choices: list[tuple[Any, dict[str, float]]]) -> bool:
    has_lethal_no_block = any(
        float(features.get("block_none_allows_lethal_player_damage", 0.0)) > 0.0
        for _choice, features in choices
    )
    has_blocker = any(
        float(features.get("decision:blocker", 0.0)) > 0.0
        for _choice, features in choices
    )
    return has_lethal_no_block and has_blocker


def _block_none_allows_turn_lethal_with_available_blocker(choices: list[tuple[Any, dict[str, float]]]) -> bool:
    has_turn_lethal_no_block = any(
        float(features.get("block_none_allows_turn_lethal_player_damage", 0.0)) > 0.0
        for _choice, features in choices
    )
    has_preventing_blocker = any(
        float(features.get("blocker_prevents_turn_lethal_player_damage", 0.0)) > 0.0
        for _choice, features in choices
    )
    return has_turn_lethal_no_block and has_preventing_blocker


def _block_none_loses_force_exchange_resource_with_available_blocker(choices: list[tuple[Any, dict[str, float]]]) -> bool:
    loses_resource = any(
        float(features.get("block_none_loses_force_life_exchange_resource", 0.0)) > 0.0
        for _choice, features in choices
    )
    has_resource_blocker = any(
        float(features.get("blocker_preserves_force_life_exchange_resource", 0.0)) > 0.0
        for _choice, features in choices
    )
    return loses_resource and has_resource_blocker


def _force_life_exchange_play_available(choices: list[tuple[Any, dict[str, float]]]) -> bool:
    return any(_is_force_life_exchange_combo_play(features) for _choice, features in choices)


def _is_force_life_exchange_combo_play(features: dict[str, float]) -> bool:
    return (
        float(features.get("action:play_card", 0.0)) > 0.0
        and float(features.get("play_card_force_life_exchange_sets_enemy_low_life", 0.0)) > 0.0
    )


def _hold_defense_removal_available(choices: list[tuple[Any, dict[str, float]]]) -> bool:
    for _choice, features in choices:
        if not (
            float(features.get("action:play_card", 0.0)) > 0.0
            or float(features.get("action:activate_flash_ability", 0.0)) > 0.0
        ):
            continue
        if not _remove_threat_plan_under_pressure(features):
            continue
        if (
            float(features.get("positive_kill_enemy_minion", 0.0)) > 0.0
            or float(features.get("play_card_beneficial_remove_threat", 0.0)) > 0.0
        ):
            return True
    return False


def _remove_threat_plan_under_pressure(features: dict[str, float]) -> bool:
    has_plan = (
        float(features.get("own_deck_plan:remove_threat", 0.0)) > 0.0
        or float(features.get("own_deck_plan:hold_defense", 0.0)) > 0.0
        or float(features.get("own_deck_semantic_plan:remove_threat", 0.0)) > 0.0
        or float(features.get("own_deck_semantic_plan:hold_defense", 0.0)) > 0.0
    )
    under_pressure = (
        float(features.get("enemy_field_dp_pressure", 0.0)) > 0.0
        or float(features.get("enemy_pressure_high_player_risk", 0.0)) > 0.0
        or float(features.get("enemy_pressure_near_player_lethal", 0.0)) > 0.0
    )
    return bool(has_plan and under_pressure)


def _is_low_pressure_nonlethal_face_attack_over_removal(features: dict[str, float]) -> bool:
    if float(features.get("action:attack", 0.0)) <= 0.0:
        return False
    if not _remove_threat_plan_under_pressure(features):
        return False
    if float(features.get("positive_face_damage", 0.0)) <= 0.0:
        return False
    if (
        float(features.get("attack_has_lethal_player_target", 0.0)) > 0.0
        or _attack_has_reliable_force_break(features)
        or float(features.get("attack_low_enemy_life_pressure", 0.0)) > 0.0
        or float(features.get("positive_kill_enemy_minion", 0.0)) > 0.0
        or float(features.get("attack_has_attack_payoff", 0.0)) > 0.0
    ):
        return False
    return True


def _attack_has_reliable_force_break(features: dict[str, float]) -> bool:
    return (
        float(features.get("attack_can_destroy_force", 0.0)) > 0.0
        and float(features.get("attack_force_break_unreliable_under_enemy_pressure", 0.0)) <= 0.0
    )


def _attack_has_immediate_payoff(features: dict[str, float]) -> bool:
    return (
        float(features.get("attack_has_lethal_player_target", 0.0)) > 0.0
        or _attack_has_reliable_force_break(features)
        or float(features.get("attack_low_enemy_life_pressure", 0.0)) > 0.0
        or float(features.get("positive_face_damage", 0.0)) > 0.0
        or float(features.get("attack_has_attack_payoff", 0.0)) > 0.0
    )


def _attack_has_defense_exempt_payoff(features: dict[str, float]) -> bool:
    return (
        float(features.get("attack_has_lethal_player_target", 0.0)) > 0.0
        or _attack_has_reliable_force_break(features)
        or float(features.get("attack_low_enemy_life_pressure", 0.0)) > 0.0
        or float(features.get("attack_has_attack_payoff", 0.0)) > 0.0
    )


def _attack_refreshes_defense_after_attack(features: dict[str, float]) -> bool:
    return (
        float(features.get("attack_with_turn_end_minion_refresh", 0.0)) > 0.0
        or float(features.get("attack_with_reawaken_self_refresh", 0.0)) > 0.0
    )


def _move_field_to_base_last_blocker_exempt(features: dict[str, float]) -> bool:
    protects_death_payoff_resource = (
        float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0
        and (
            float(features.get("move_card_profile_role:death_payoff", 0.0)) > 0.0
            or float(features.get("move_card_semantic_role:death_payoff", 0.0)) > 0.0
        )
        and (
            float(features.get("own_deck_plan:protect_combo_piece", 0.0)) > 0.0
            or float(features.get("own_deck_semantic_plan:protect_combo_piece", 0.0)) > 0.0
            or float(features.get("own_deck_combo_route:trash_recursion", 0.0)) > 0.0
            or float(features.get("own_deck_semantic_combo_route:trash_recursion", 0.0)) > 0.0
        )
        and (
            float(features.get("move_field_to_base_enables_playable_hand_card", 0.0)) > 0.0
            or float(features.get("move_field_to_base_future_play", 0.0)) > 0.0
            or float(features.get("move_field_to_base_matches_hand_color", 0.0)) > 0.0
        )
        and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
    )
    if protects_death_payoff_resource:
        return True
    repairs_missing_color = (
        float(features.get("semantic_action_resource:repair_missing_color", 0.0)) > 0.0
        or float(features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0
    )
    enables_play_now = float(features.get("move_field_to_base_enables_playable_hand_card", 0.0)) > 0.0
    high_player_pressure = (
        float(features.get("enemy_pressure_high_player_risk", 0.0)) > 0.0
        or float(features.get("enemy_pressure_near_player_lethal", 0.0)) > 0.0
        or float(features.get("move_field_to_base_under_observed_aggression_defense_need", 0.0)) > 0.0
    )
    hold_defense_pressure = (
        (
            float(features.get("own_deck_plan:hold_defense", 0.0)) > 0.0
            or float(features.get("own_deck_semantic_plan:hold_defense", 0.0)) > 0.0
        )
        and (
            float(features.get("enemy_field_dp_pressure", 0.0)) > 0.0
            or float(features.get("enemy_pressure_high_player_risk", 0.0)) > 0.0
            or float(features.get("enemy_pressure_near_player_lethal", 0.0)) > 0.0
        )
    )
    if hold_defense_pressure or high_player_pressure:
        return (
            repairs_missing_color
            and enables_play_now
            and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
        )
    if float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0:
        return True
    turn = float(features.get("turn_normalized", 0.0)) * 30.0
    base_count = float(features.get("own_base_count", 0.0)) * 10.0
    return (
        turn <= 3.0
        and base_count < 3.0
        and float(features.get("own_forces_alive", 0.0)) > 0.0
        and float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0
        and float(features.get("move_field_to_base_future_play", 0.0)) > 0.0
        and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
    )


def _action_choice_is_tactically_forbidden(features: dict[str, float]) -> bool:
    if (
        features.get("decision:blocker", 0.0)
        and float(features.get("blocker_wastes_on_zero_dp_attacker", 0.0)) > 0.0
    ):
        return True
    if (
        features.get("decision:blocker", 0.0)
        and float(features.get("blocker_loses_to_attacker", 0.0)) > 0.0
        and float(features.get("blocker_prevents_lethal_player_damage", 0.0)) <= 0.0
        and float(features.get("blocker_prevents_turn_lethal_player_damage", 0.0)) <= 0.0
        and float(features.get("own_forces_alive", 1.0)) <= 0.0
        and float(features.get("enemy_field_dp_pressure", 0.0)) > 0.0
    ):
        return True
    if features.get("action:attack", 0.0):
        exposes_lethal = float(features.get("attack_exposes_lethal_next_turn", 0.0)) > 0.0
        low_life_no_forces = float(features.get("attack_while_low_life_no_forces", 0.0)) > 0.0
        has_player_lethal = float(features.get("attack_has_lethal_player_target", 0.0)) > 0.0
        has_attack_payoff = _attack_has_immediate_payoff(features)
        has_defense_exempt_payoff = _attack_has_defense_exempt_payoff(features)
        refreshes_defense = _attack_refreshes_defense_after_attack(features)
        if exposes_lethal and not has_player_lethal:
            return True
        if low_life_no_forces and not has_player_lethal:
            return True
        if (
            float(features.get("attack_without_forces_under_enemy_pressure", 0.0)) > 0.0
            and not has_player_lethal
        ):
            return True
        if (
            float(features.get("attack_spends_force_life_exchange_combo_wall", 0.0)) > 0.0
            and not has_player_lethal
        ):
            return True
        if (
            float(features.get("own_deck_semantic_plan:hold_defense", 0.0)) > 0.0
            and float(features.get("attack_removes_last_blocker_under_enemy_pressure", 0.0)) > 0.0
            and not has_defense_exempt_payoff
            and not refreshes_defense
        ):
            return True
        if (
            (
                float(features.get("enemy_pressure_high_player_risk", 0.0)) > 0.0
                or float(features.get("enemy_pressure_near_player_lethal", 0.0)) > 0.0
            )
            and (
                float(features.get("attack_larger_ready_blocker_count", 0.0)) > 0.0
                or float(features.get("attack_larger_blocker_bp_gap", 0.0)) > 0.0
                or float(features.get("attack_low_dp_into_larger_blocker", 0.0)) > 0.0
            )
            and not has_attack_payoff
        ):
            return True
        if (
            float(features.get("attack_zero_dp_without_attack_payoff", 0.0)) > 0.0
            and not has_attack_payoff
        ):
            return True
        if (
            (
                float(features.get("attack_suicide_into_larger_blocker_without_pressure", 0.0)) > 0.0
                or float(features.get("attack_loses_to_larger_blocker_without_pressure", 0.0)) > 0.0
            )
            and not has_attack_payoff
        ):
            return True
        return False
    if float(features.get("move_field_to_base_spends_force_life_exchange_wall", 0.0)) > 0.0:
        exposes_low_force_resource = (
            float(features.get("own_force_life_exchange_low_force_resource", 0.0)) > 0.0
            and float(features.get("enemy_field_dp_pressure", 0.0)) > 0.0
        )
        if exposes_low_force_resource:
            color_repair_protects_attacker = (
                float(features.get("move_field_to_base_builds_mana", 0.0)) > 0.0
                and float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0
                and float(features.get("move_field_to_base_future_play", 0.0)) > 0.0
                and float(features.get("move_field_to_base_matches_hand_color", 0.0)) > 0.0
                and float(features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0
                and float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0
                and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
                and float(features.get("enemy_field_dp_pressure", 0.0)) <= 0.2
                and float(features.get("own_forces_alive", 0.0)) > 0.0
                and float(features.get("own_base_count", 1.0)) <= 0.5
            )
            if (
                float(features.get("move_field_to_base_resource_engine", 0.0)) <= 0.0
                and not color_repair_protects_attacker
            ):
                return True
        early_curve_resource_setup = (
            float(features.get("move_field_to_base_builds_mana", 0.0)) > 0.0
            and float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0
            and float(features.get("move_field_to_base_future_play", 0.0)) > 0.0
            and float(features.get("own_forces_alive", 0.0)) > 0.0
            and float(features.get("own_base_count", 1.0)) <= 0.5
            and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
        )
        if early_curve_resource_setup:
            return False
        near_exchange_turn = (
            float(features.get("own_hand_has_force_life_exchange", 0.0)) > 0.0
            and float(features.get("own_base_count", 0.0)) >= 0.8
        )
        if not near_exchange_turn:
            return True
    if (
        float(features.get("move_field_to_base_under_enemy_pressure", 0.0)) > 0.0
        and float(features.get("own_forces_alive", 1.0)) <= 0.0
        and float(features.get("enemy_field_dp_pressure", 0.0)) > 0.0
    ):
        return True
    if (
        float(features.get("move_field_to_base_removes_last_blocker_under_enemy_pressure", 0.0)) > 0.0
        and not _move_field_to_base_last_blocker_exempt(features)
    ):
        return True
    if (
        float(features.get("move_base_to_field_delays_force_life_exchange", 0.0)) > 0.0
        and float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) <= 0.0
    ):
        return True
    if (
        float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0
        and float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) <= 0.0
    ):
        return True
    if (
        float(features.get("move_base_to_field_under_observed_aggression_no_blocker", 0.0)) > 0.0
        and float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) <= 0.0
    ):
        return True
    if (
        float(features.get("move_base_to_field_attack_payoff_contested_by_larger_blocker", 0.0)) > 0.0
        and float(features.get("move_base_to_field_under_observed_aggression_defense_need", 0.0)) <= 0.0
        and (
            float(features.get("move_base_to_field_spends_ready_mana", 0.0)) > 0.0
            or float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0
            or float(features.get("move_base_to_field_with_playable_hand", 0.0)) > 0.0
        )
    ):
        return True
    if (
        float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0
        and float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0
        and float(features.get("move_base_to_field_can_block", 0.0)) <= 0.0
        and float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) <= 0.0
        and float(features.get("move_base_to_field_under_observed_aggression_defense_need", 0.0)) <= 0.0
    ):
        return True
    if not (features.get("action:play_card", 0.0) or features.get("action:activate_flash_ability", 0.0)):
        return False
    forbidden_keys = (
        "play_card_target_effect_no_eligible_targets",
        "play_card_harmful_target_only_own",
        "play_card_harmful_no_enemy_target",
        "play_card_beneficial_no_own_target",
        "play_card_beneficial_only_enemy_target",
        "play_card_defensive_reactive_on_own_turn",
    )
    return any(float(features.get(key, 0.0)) > 0.0 for key in forbidden_keys)


def tactical_action_prior(features: dict[str, float]) -> float:
    score = 0.0
    stuck_for_color = float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0
    has_field_to_base_candidate = float(features.get("own_field_to_base_candidate_count", 0.0)) > 0.0
    turn = float(features.get("turn_normalized", 0.0)) * 30.0
    base_count = float(features.get("own_base_count", 0.0)) * 10.0
    if (
        features.get("action:skip_mana", 0.0)
        and (
            float(features.get("negative_skip_mana_under_base_cap", 0.0)) > 0.0
            or float(features.get("skip_mana_under_base_cap", 0.0)) > 0.0
        )
    ):
        score -= 5.0
    if features.get("action:move_card", 0.0):
        if float(features.get("move_field_to_base", 0.0)) > 0.0:
            score += 0.5
            if float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0:
                score += 0.9
            if float(features.get("move_field_to_base_future_play", 0.0)) > 0.0:
                score += 0.7
            if float(features.get("move_field_to_base_matches_hand_color", 0.0)) > 0.0:
                score += 0.6
            if float(features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0:
                score += 2.6
            elif stuck_for_color:
                score += 0.8
            if (
                float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0
                and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
            ):
                score += 2.3
            if (
                turn <= 5.0
                and base_count < 5.0
                and float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0
                and float(features.get("move_field_to_base_future_play", 0.0)) > 0.0
                and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
            ):
                score += 2.5
            if float(features.get("move_field_to_base_under_enemy_pressure", 0.0)) > 0.0:
                score -= 3.0
            if (
                float(features.get("move_field_to_base_removes_last_blocker_under_enemy_pressure", 0.0)) > 0.0
                and not _move_field_to_base_last_blocker_exempt(features)
            ):
                score -= 8.0
            if float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) > 0.0:
                score -= 10.0
            if float(features.get("move_field_to_base_spends_force_life_exchange_wall", 0.0)) > 0.0:
                score -= 7.0
        elif float(features.get("move_base_to_field", 0.0)) > 0.0:
            if stuck_for_color:
                score -= 1.2
            if float(features.get("move_base_to_field_spends_ready_mana", 0.0)) > 0.0:
                score -= 0.8
            if float(features.get("move_base_to_field_with_playable_hand", 0.0)) > 0.0:
                score -= 0.8
            if float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0:
                score -= 1.0
            if float(features.get("move_base_to_field_only_ready_color_for_hand", 0.0)) > 0.0:
                score -= 3.0
            if float(features.get("move_base_to_field_cannot_block", 0.0)) > 0.0:
                score -= 1.0
            if float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0:
                score -= 2.8
            if float(features.get("move_base_to_field_delays_force_life_exchange", 0.0)) > 0.0:
                score -= 10.0
            if float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) > 0.0:
                score += 8.0
    if features.get("action:end_turn", 0.0) and stuck_for_color and has_field_to_base_candidate:
        score -= 1.2
        if features.get("action:skip_mana", 0.0) and stuck_for_color and float(features.get("can_swap_mana_color", 0.0)) > 0.0:
            score -= 0.8
    if float(features.get("replace_base_value", 0.0)) > 0.0:
        score -= float(features.get("replace_base_value", 0.0)) * 14.0
        if float(features.get("replace_base_mana_token", 0.0)) > 0.0:
            score += 6.0
        if float(features.get("replace_base_only_ready_color_for_hand", 0.0)) > 0.0:
            score -= 8.0
        if float(features.get("replace_base_protects_minion", 0.0)) > 0.0:
            score -= 3.0
    if float(features.get("replace_field_value", 0.0)) > 0.0:
        score -= float(features.get("replace_field_value", 0.0)) * 8.0
        if float(features.get("replace_field_token", 0.0)) > 0.0:
            score += 4.0
        if float(features.get("replace_field_blocker_under_pressure", 0.0)) > 0.0:
            score -= 3.0
        if float(features.get("replace_field_own_revival_candidate", 0.0)) > 0.0:
            score += 1.5
    if features.get("action:swap_mana_color", 0.0):
        score -= 0.4
        if float(features.get("swap_mana_to_hand_demand", 0.0)) > 0.0:
            score += 0.4
        if float(features.get("swap_mana_to_missing_hand_color", 0.0)) > 0.0:
            score += 0.8
        if float(features.get("swap_mana_enables_playable_hand_card", 0.0)) > 0.0:
            score += 1.5
        if stuck_for_color and float(features.get("swap_mana_fallback_unsticks_hand", 0.0)) > 0.0:
            score += 3.2
        if float(features.get("own_playable_non_base_hand_count", 0.0)) > 0.0:
            score -= 1.0
        if float(features.get("swap_mana_delays_base_growth", 0.0)) > 0.0:
            score -= 5.0
        if (
            float(features.get("swap_mana_enables_playable_hand_card", 0.0)) <= 0.0
            and float(features.get("swap_mana_fallback_unsticks_hand", 0.0)) <= 0.0
        ):
            score -= 1.4
    if features.get("action:place_colorless_mana", 0.0):
        ignores_missing_color = float(features.get("place_colorless_mana_ignores_missing_hand_color", 0.0)) > 0.0
        if (
            float(features.get("place_colorless_mana_supports_chimera_color_fix", 0.0)) > 0.0
            and not ignores_missing_color
        ):
            score += 3.2
        if ignores_missing_color:
            score -= 2.4
        if float(features.get("negative_no_effect_resource_spend", 0.0)) > 0.0:
            score -= 2.0
    if features.get("action:play_card", 0.0) or features.get("action:activate_flash_ability", 0.0):
        if float(features.get("play_card_target_effect_no_eligible_targets", 0.0)) > 0.0:
            score -= 50.0
        if float(features.get("play_card_beneficial_no_own_target", 0.0)) > 0.0:
            score -= 35.0
        if float(features.get("play_card_beneficial_only_enemy_target", 0.0)) > 0.0:
            score -= 35.0
        if float(features.get("play_card_harmful_target_only_own", 0.0)) > 0.0:
            score -= 50.0
        elif float(features.get("play_card_harmful_no_enemy_target", 0.0)) > 0.0:
            score -= 8.0
        if float(features.get("play_card_harmful_enemy_target_available", 0.0)) > 0.0:
            score += 0.35
        if float(features.get("play_card_with_turn_end_mana_refresh", 0.0)) > 0.0:
            score += 0.6
        if float(features.get("play_card_defensive_reactive_on_enemy_turn", 0.0)) > 0.0:
            score += 1.2
        if float(features.get("play_card_defensive_reactive_attack_payoff", 0.0)) > 0.0:
            score += 0.8
        if float(features.get("play_card_rest_lockdown_on_own_turn", 0.0)) > 0.0:
            score += 4.5
            score += float(features.get("play_card_rest_lockdown_enemy_lockable_targets", 0.0)) * 2.0
            score += float(features.get("play_card_rest_lockdown_enemy_ready_targets", 0.0)) * 3.0
        if float(features.get("play_card_defensive_reactive_on_own_turn", 0.0)) > 0.0:
            score -= 20.0
        if float(features.get("play_card_exchange_player_force_life", 0.0)) > 0.0:
            score += 0.8
        if float(features.get("play_card_force_life_exchange_sets_enemy_low_life", 0.0)) > 0.0:
            score += 6.0
        if float(features.get("play_card_force_life_exchange_has_followup_damage", 0.0)) > 0.0:
            score += 8.0
        if float(features.get("play_card_force_life_exchange_search_support", 0.0)) > 0.0:
            score += 6.0
        if float(features.get("play_card_force_life_exchange_search_for_deck_piece", 0.0)) > 0.0:
            score += 2.0
        if float(features.get("play_card_force_life_exchange_search_near_cast", 0.0)) > 0.0:
            score += 4.0
        if float(features.get("play_card_base_development_support", 0.0)) > 0.0:
            score += 3.0
        if float(features.get("play_card_base_search_support", 0.0)) > 0.0:
            score += 2.0
        if float(features.get("play_card_place_base_from_hand_support", 0.0)) > 0.0:
            score += 2.5
        if float(features.get("play_card_early_base_development_support", 0.0)) > 0.0:
            score += 2.0
    if features.get("action:attack", 0.0):
        if float(features.get("attack_exposes_lethal_next_turn", 0.0)) > 0.0:
            score -= 16.0
        elif float(features.get("attack_while_low_life_no_forces", 0.0)) > 0.0:
            score -= 6.0
        elif float(features.get("attack_without_forces_under_enemy_pressure", 0.0)) > 0.0:
            score -= 8.0
        if float(features.get("attack_nonlethal_with_low_base", 0.0)) > 0.0:
            score -= 1.5
            if stuck_for_color or has_field_to_base_candidate:
                score -= 0.8
        if float(features.get("attack_zero_dp_without_attack_payoff", 0.0)) > 0.0:
            score -= 20.0
        if float(features.get("attack_suicide_into_larger_blocker_without_pressure", 0.0)) > 0.0:
            score -= 24.0
        elif float(features.get("attack_loses_to_larger_blocker_without_pressure", 0.0)) > 0.0:
            score -= 14.0
        elif float(features.get("attack_low_dp_into_larger_blocker", 0.0)) > 0.0:
            score -= 6.0
        if float(features.get("attack_spends_force_life_exchange_combo_wall", 0.0)) > 0.0:
            score -= 10.0
        if float(features.get("attack_low_enemy_life_pressure", 0.0)) > 0.0:
            score += 12.0
        if (
            float(features.get("opponent_observed_aggressive_pressure", 0.0)) > 0.0
            and float(features.get("own_player_life", 1.0)) <= 0.4
            and float(features.get("own_forces_alive", 1.0)) <= 0.0
            and float(features.get("attack_has_lethal_player_target", 0.0)) <= 0.0
            and not _attack_has_reliable_force_break(features)
        ):
            score -= 5.0
        if float(features.get("attack_under_observed_aggression_defense_need", 0.0)) > 0.0:
            score -= 8.0
        if float(features.get("attack_with_turn_end_minion_refresh", 0.0)) > 0.0:
            score += 0.8
    if float(features.get("play_minion_under_observed_aggression_defense_need", 0.0)) > 0.0:
        score += 2.5
    if (
        float(features.get("move_base_to_field_under_observed_aggression_defense_need", 0.0)) > 0.0
        and float(features.get("move_base_to_field_can_block", 0.0)) > 0.0
    ):
        score += 2.5
    if float(features.get("move_base_to_field_under_observed_aggression_no_blocker", 0.0)) > 0.0:
        score -= 4.0
    if float(features.get("end_turn_under_observed_aggression_defense_need", 0.0)) > 0.0:
        score += 1.0
    if float(features.get("move_field_to_base_under_observed_aggression_defense_need", 0.0)) > 0.0:
        score -= 4.0
    if features.get("decision:blocker", 0.0):
        value = (
            float(features.get("blocker_cost", 0.0))
            + float(features.get("blocker_bp", 0.0))
            + float(features.get("blocker_dp", 0.0))
        )
        if float(features.get("blocker_preserves_force_life_exchange_resource", 0.0)) > 0.0:
            score += 12.0
            if float(features.get("blocker_loses_to_attacker", 0.0)) > 0.0:
                score -= value * 2.0
        if float(features.get("blocker_prevents_force_life_exchange_setup_damage", 0.0)) > 0.0:
            score -= 30.0
        death_payoff_blocker = (
            float(features.get("blocker_has_on_destroy_effect", 0.0)) > 0.0
            or float(features.get("blocker_profile_role:death_payoff", 0.0)) > 0.0
            or float(features.get("blocker_semantic_role:death_payoff", 0.0)) > 0.0
        )
        if (
            death_payoff_blocker
            and float(features.get("blocker_death_payoff_would_trigger", 0.0)) > 0.0
            and float(features.get("blocker_wastes_on_zero_dp_attacker", 0.0)) <= 0.0
        ):
            score += 4.0
        if float(features.get("blocker_cleanly_beats_attacker", 0.0)) > 0.0:
            score += 20.0
        elif float(features.get("blocker_trades_with_attacker", 0.0)) > 0.0:
            score += 7.0 - value
        elif float(features.get("blocker_prevents_lethal_player_damage", 0.0)) > 0.0:
            score += 8.0 - value * 15.0
        elif float(features.get("blocker_prevents_turn_lethal_player_damage", 0.0)) > 0.0:
            score += 10.0 - value * 6.0
        elif float(features.get("blocker_loses_to_attacker", 0.0)) > 0.0:
            score -= value * 5.0
    if features.get("block:none", 0.0) and float(features.get("block_none_allows_lethal_player_damage", 0.0)) > 0.0:
        score -= 12.0
    if features.get("block:none", 0.0) and float(features.get("block_none_allows_turn_lethal_player_damage", 0.0)) > 0.0:
        score -= 14.0
    if features.get("block:none", 0.0) and float(features.get("block_none_loses_force_life_exchange_resource", 0.0)) > 0.0:
        score -= 24.0
    if features.get("block:none", 0.0) and float(features.get("block_none_lowers_force_life_exchange_resource", 0.0)) > 0.0:
        score += 30.0
    if (
        float(features.get("attack_has_lethal_player_target", 0.0)) <= 0.0
        and float(features.get("negative_exposes_lethal_or_bad_trade", 0.0)) > 0.0
    ):
        score -= 8.0
    return score


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except TypeError:
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _card_cost(card: Any) -> int:
    return int(sum(getattr(card, "cost", {}).values()))


def _feature_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", str(value)).strip("_").lower() or "unknown"


def _feature_key(prefix: str, value: str) -> str:
    return f"{prefix}:{_feature_token(value)}"


def _camel_case(value: str) -> str:
    parts = str(value).split("_")
    if not parts:
        return str(value)
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _interaction_feature_key(left: str, right: str) -> str:
    return f"interaction:{_feature_token(left)}__{_feature_token(right)}"


def model_uses_observed_opponent_features(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    return metadata.get("observedOpponentFeatureVersion") == OBSERVED_OPPONENT_FEATURE_VERSION


def model_scores_observed_opponent_features(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    return bool(metadata.get(OBSERVED_OPPONENT_MODEL_FEATURE_FLAG))


def model_uses_public_deep_v2_planner(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    return metadata.get("policyArchitecture") == PUBLIC_DEEP_V2_PLANNER_ARCHITECTURE


def model_uses_public_deep_v2_semantic_bridge(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    return metadata.get("publicDeepV2SemanticBridgeVersion") == PUBLIC_DEEP_V2_SEMANTIC_BRIDGE_VERSION


def model_public_deep_v2_planner_prior_weight(model: Any) -> float:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return 0.0
    return _safe_float(metadata.get("publicDeepV2PlannerPriorWeight"))


def model_public_deep_v2_plan_head_rerank_weight(model: Any) -> float:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return 0.0
    if metadata.get("publicDeepV2PlanHeadRerankEnabled") is not True:
        return 0.0
    return max(0.0, _safe_float(metadata.get("publicDeepV2PlanHeadRerankWeight")))


def model_public_deep_v2_rerank_head_weight(model: Any) -> float:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return 0.0
    if metadata.get("publicDeepV2RerankHeadVersion") != PUBLIC_DEEP_V2_RERANK_HEAD_VERSION:
        return 0.0
    if metadata.get("publicDeepV2RerankHeadRuntimeEnabled") is not True:
        return 0.0
    if metadata.get("publicDeepV2RerankRuntimeGuardVersion") != PUBLIC_DEEP_V2_RERANK_RUNTIME_GUARD_VERSION:
        return 0.0
    if metadata.get("publicDeepV2RerankHeadKeyDecisionsOnly") is not True:
        return 0.0
    if metadata.get("publicDeepV2RerankAntiAggroGuard") is not True:
        return 0.0
    max_weight = _safe_float(metadata.get("publicDeepV2RerankMaxWeight"))
    if max_weight <= 0.0:
        max_weight = PUBLIC_DEEP_V2_RERANK_MAX_RUNTIME_WEIGHT
    max_weight = min(max_weight, PUBLIC_DEEP_V2_RERANK_MAX_RUNTIME_WEIGHT)
    weight = max(0.0, _safe_float(metadata.get("publicDeepV2RerankHeadWeight")))
    if weight > max_weight:
        return 0.0
    return weight


def model_public_deep_v2_rerank_head_key_decisions_only(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    return metadata.get("publicDeepV2RerankHeadKeyDecisionsOnly") is True


def model_public_deep_v2_rerank_anti_aggro_guard(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    return metadata.get("publicDeepV2RerankAntiAggroGuard") is True


def model_public_deep_v2_understanding_runtime_weight(model: Any) -> float:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return 0.0
    if metadata.get("publicDeepV2UnderstandingRuntimeVersion") != PUBLIC_DEEP_V2_UNDERSTANDING_RUNTIME_VERSION:
        return 0.0
    weight = max(0.0, _safe_float(metadata.get("publicDeepV2UnderstandingRuntimeWeight")))
    return min(weight, PUBLIC_DEEP_V2_UNDERSTANDING_MAX_RUNTIME_WEIGHT)


def model_uses_state_value_head(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    return (
        metadata.get("stateValueHeadVersion") == PUBLIC_DEEP_V2_STATE_VALUE_HEAD_VERSION
        and metadata.get("stateValueLeafRuntimeEnabled") is True
    )


def model_state_value_leaf_runtime_focus(model: Any) -> str:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return "all"
    focus = str(metadata.get("stateValueLeafRuntimeFocus") or "all").strip().lower()
    return focus if focus in {"all", "anti_aggro"} else "all"


def _state_value_leaf_context_allowed(features: dict[str, float], *, focus: str) -> bool:
    if focus != "anti_aggro":
        return True
    pressure_keys = (
        "opponent_observed_aggressive_pressure",
        "enemy_pressure_high_player_risk",
        "enemy_pressure_near_player_lethal",
    )
    if any(float(features.get(key, 0.0)) > 0.0 for key in pressure_keys):
        return True
    return (
        float(features.get("enemy_field_dp_pressure", 0.0)) >= 0.3
        and float(features.get("own_player_life", 1.0)) <= 0.5
    )


def _is_rejected_public_deep_v2_candidate(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    if metadata.get("publicDeepV2GatePassed") is True:
        return False
    if metadata.get("publicDeepV2Candidate") is True:
        return True
    if metadata.get("policyArchitecture") == PUBLIC_DEEP_V2_PLANNER_ARCHITECTURE:
        return True
    if metadata.get("deepV2ArchitectureVersion") == "public_deep_v2_shared_heads_v1":
        return True
    return False


def _public_deep_v2_auxiliary_scoring_features(features: dict[str, float]) -> dict[str, float]:
    return {
        key: value
        for key, value in features.items()
        if not (
            key.startswith("planner_label:")
            or key.startswith("planner_reason:")
            or key.startswith("planner_risk:")
            or key == "public_deep_v2_planner_selected"
        )
    }


def _public_deep_v2_rerank_key_decision(features: dict[str, float]) -> bool:
    key_flags = (
        "attack_exposes_lethal_next_turn",
        "attack_while_low_life_no_forces",
        "attack_has_lethal_player_target",
        "attack_can_destroy_force",
        "attack_zero_dp_without_attack_payoff",
        "attack_suicide_into_larger_blocker_without_pressure",
        "attack_without_forces_under_enemy_pressure",
        "play_card_target_effect",
        "play_card_defensive_reactive_effect",
        "block_none_allows_lethal_player_damage",
        "block_none_allows_turn_lethal_player_damage",
        "block_none_loses_force_life_exchange_resource",
        "decision:blocker",
        "move_field_to_base_exposes_lethal_pressure",
        "move_field_to_base_removes_last_blocker_under_enemy_pressure",
        "move_base_to_field_under_observed_aggression_no_blocker",
        "move_base_to_field_under_observed_aggression_defense_need",
        "move_base_to_field_attack_payoff_contested_by_larger_blocker",
        "move_base_to_field_low_impact_mana_minion",
        "move_base_to_field_delays_force_life_exchange",
        "move_field_to_base_spends_force_life_exchange_wall",
        "move_field_to_base_restores_missing_hand_color",
        "play_to_base_restores_missing_hand_color",
        "play_to_base_restores_missing_unfixable_hand_color",
        "play_to_base_matches_unfixable_hand_color",
        "play_card_move_to_base_restores_missing_hand_color",
        "play_card_move_to_base_restores_missing_unfixable_hand_color",
        "play_card_move_to_base_matches_unfixable_hand_color",
        "place_colorless_mana_ignores_missing_hand_color",
    )
    if any(_safe_float(features.get(key)) > 0.0 for key in key_flags):
        return True
    return any(
        _safe_float(value) > 0.0 and (key.startswith("play_card_harmful_") or key.startswith("play_card_beneficial_"))
        for key, value in features.items()
    )


def _public_deep_v2_rerank_anti_aggro_risk(features: dict[str, float]) -> bool:
    risk_flags = (
        "attack_while_low_life_no_forces",
        "attack_without_forces_under_enemy_pressure",
        "attack_exposes_lethal_next_turn",
        "attack_suicide_into_larger_blocker_without_pressure",
        "move_field_to_base_under_enemy_pressure",
        "move_field_to_base_exposes_lethal_pressure",
        "move_field_to_base_removes_last_blocker_under_enemy_pressure",
        "move_base_to_field_under_observed_aggression_no_blocker",
        "move_base_to_field_attack_payoff_contested_by_larger_blocker",
        "move_base_to_field_low_impact_mana_minion",
    )
    return any(_safe_float(features.get(key)) > 0.0 for key in risk_flags)


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def model_scoring_features(
    features: dict[str, float],
    *,
    include_observed_opponent_features: bool = False,
    include_public_deep_v2_planner_features: bool = False,
    include_public_deep_v2_semantic_bridge_features: bool = False,
) -> dict[str, float]:
    return {
        key: value
        for key, value in features.items()
        if (include_observed_opponent_features or not _observed_opponent_prior_only_feature(key))
        and (
            include_public_deep_v2_semantic_bridge_features
            or not _public_deep_v2_semantic_bridge_feature(key)
        )
        and (
            include_public_deep_v2_planner_features
            or not _public_deep_v2_planner_only_feature(key)
        )
    }


def _observed_opponent_prior_only_feature(key: str) -> bool:
    return (
        key.startswith("opponent_observed_")
        or "observed_aggression" in key
        or "observed_opponent" in key
    )


def _public_deep_v2_planner_only_feature(key: str) -> bool:
    if key.startswith("public_deep_v2_planner"):
        return True
    if key.startswith((
        "planner_intent:",
        "planner_deck_id:",
        "planner_label:",
        "planner_state:",
        "planner_reason:",
        "planner_risk:",
    )):
        return True
    if key.startswith("own_deck_") and (
        "_profile_version:" in key
        or key.startswith((
            "own_deck_id:",
            "own_deck_tag:",
            "own_deck_combo_route:",
            "own_deck_archetype:",
            "own_deck_archetype_score:",
            "own_deck_plan:",
        ))
    ):
        return True
    return "_profile_" in key


def _public_deep_v2_semantic_bridge_feature(key: str) -> bool:
    return "_semantic_" in key or key.startswith("semantic_")


def apply_public_deep_v2_planner_to_action_choices(
    choices: list[tuple[Any, dict[str, float]]],
) -> list[tuple[Any, dict[str, float]]]:
    state_tags = _public_deep_v2_state_tags(choices)
    if not _public_deep_v2_planner_should_activate(state_tags):
        return choices

    actions = [action for action, _ in choices]
    try:
        trace = choose_plan_from_candidates(
            generate_candidate_plans_from_action_choices(
                choices,
                state_tags=state_tags,
                deck_plan_tags=_public_deep_v2_deck_plan_tags(choices),
            ),
            state_tags=state_tags,
        )
    except (ValueError, AttributeError):
        return choices

    enriched: list[tuple[Any, dict[str, float]]] = []
    for action, features in choices:
        row = dict(features)
        row["public_deep_v2_planner"] = 1.0
        for tag in state_tags:
            row[_feature_key("planner_state", tag)] = 1.0
        if _public_deep_v2_action_matches_trace(action, trace.first_action):
            row["public_deep_v2_planner_selected"] = 1.0
            row[_feature_key("planner_intent", trace.chosen_intent.value)] = 1.0
            for reason in trace.chosen_plan.get("reasonTags") or []:
                row[_feature_key("planner_reason", str(reason))] = 1.0
            for risk in trace.chosen_plan.get("riskTags") or []:
                row[_feature_key("planner_risk", str(risk))] = 1.0
        enriched.append((action, row))
    return enriched


def apply_concrete_plan_prior_to_action_choices(
    choices: list[tuple[Any, dict[str, float]]],
) -> list[tuple[Any, dict[str, float]]]:
    state_tags = _public_deep_v2_state_tags(choices)
    if not _public_deep_v2_planner_should_activate(state_tags):
        return choices

    try:
        trace = choose_plan_from_candidates(
            generate_candidate_plans_from_action_choices(
                choices,
                state_tags=state_tags,
                deck_plan_tags=_public_deep_v2_deck_plan_tags(choices),
            ),
            state_tags=state_tags,
        )
    except (ValueError, AttributeError):
        return choices

    chosen_score = _safe_float((trace.chosen_plan or {}).get("score"))
    rejected_scores = [
        _safe_float(plan.get("score"))
        for plan in (trace.rejected_plans or [])
        if isinstance(plan, dict)
    ]
    score_margin = max(0.0, chosen_score - max(rejected_scores, default=chosen_score))
    enriched: list[tuple[Any, dict[str, float]]] = []
    for action, features in choices:
        row = dict(features)
        row["concrete_plan_prior"] = 1.0
        if _public_deep_v2_action_matches_trace(action, trace.first_action):
            row["concrete_plan_prior_selected"] = 1.0
            row["concrete_plan_score_margin"] = score_margin
            row[_feature_key("concrete_plan_intent", trace.chosen_intent.value)] = 1.0
            for reason in (trace.chosen_plan or {}).get("reasonTags") or []:
                row[_feature_key("concrete_plan_reason", str(reason))] = 1.0
            for risk in (trace.chosen_plan or {}).get("riskTags") or []:
                row[_feature_key("concrete_plan_risk", str(risk))] = 1.0
        enriched.append((action, row))
    return enriched


def public_deep_v2_planner_prior(features: dict[str, float]) -> float:
    if _safe_float(features.get("public_deep_v2_planner_selected")) <= 0.0:
        return 0.0
    if (
        _safe_float(features.get("planner_intent:hold_defense")) > 0.0
        and _safe_float(features.get("planner_state:enemy_dp_pressure")) > 0.0
        and _safe_float(features.get("planner_state:own_low_life")) > 0.0
        and (
            _safe_float(features.get("planner_state:last_blocker")) > 0.0
            or _safe_float(features.get("planner_state:observed_aggressive_pressure")) > 0.0
        )
    ):
        return 1.25
    if (
        _safe_float(features.get("planner_intent:grow_base")) > 0.0
        and _safe_float(features.get("planner_state:early_game")) > 0.0
        and _safe_float(features.get("planner_state:resource_sensitive_deck")) > 0.0
        and _safe_float(features.get("planner_state:safe_field_to_base")) > 0.0
        and (
            _safe_float(features.get("move_field_to_base_under_curve")) > 0.0
            or _safe_float(features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
        )
    ):
        return 1.0
    return 0.0


def concrete_plan_action_prior(features: dict[str, float]) -> float:
    if _safe_float(features.get("concrete_plan_prior_selected")) <= 0.0:
        return 0.0
    if (
        _safe_float(features.get("action:place_colorless_mana")) > 0.0
        and _safe_float(features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
    ):
        return 0.0
    if (
        _safe_float(features.get("action:end_turn")) > 0.0
        and _safe_float(features.get("own_no_ready_colored_mana_for_hand")) > 0.0
        and _safe_float(features.get("own_field_to_base_candidate_count")) > 0.0
    ):
        return 0.0
    score = 1.2
    score += min(0.8, _safe_float(features.get("concrete_plan_score_margin")))
    if _safe_float(features.get("concrete_plan_intent:grow_base")) > 0.0:
        score += 0.35
    if _safe_float(features.get("concrete_plan_intent:hold_defense")) > 0.0:
        score += 0.45
    if _safe_float(features.get("concrete_plan_reason:unlock_next_turn_color")) > 0.0:
        score += 0.2
    if _safe_float(features.get("concrete_plan_reason:preserve_life_against_greedy")) > 0.0:
        score += 0.25
    return score


def _public_deep_v2_state_tags(choices: list[tuple[Any, dict[str, float]]]) -> set[str]:
    tags: set[str] = set()
    all_features = [features for _, features in choices]

    if any(
        _safe_float(features.get("enemy_field_dp_pressure")) > 0
        or _safe_float(features.get("enemy_pressure_high_player_risk")) > 0
        or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0
        or _safe_float(features.get("attack_under_observed_aggression_defense_need")) > 0
        or _safe_float(features.get("end_turn_under_observed_aggression_defense_need")) > 0
        for features in all_features
    ):
        tags.add("enemy_dp_pressure")
    if any(
        _safe_float(features.get("opponent_observed_aggressive_pressure")) > 0
        or _safe_float(features.get("attack_under_observed_aggression_defense_need")) > 0
        or _safe_float(features.get("end_turn_under_observed_aggression_defense_need")) > 0
        for features in all_features
    ):
        tags.add("observed_aggressive_pressure")
    if any(0 < _safe_float(features.get("own_player_life")) <= 0.5 for features in all_features):
        tags.add("own_low_life")
    if any(0 < _safe_float(features.get("own_field_count")) <= 0.2 for features in all_features):
        tags.add("last_blocker")
    if any(
        "turn_normalized" in features and _safe_float(features.get("turn_normalized")) <= 0.25
        for features in all_features
    ):
        tags.add("early_game")
    if any(
        _safe_float(features.get("own_deck_tag:resource_sensitive")) > 0
        or _safe_float(features.get("own_deck_archetype:control")) > 0
        or _safe_float(features.get("own_deck_archetype:combo")) > 0
        for features in all_features
    ):
        tags.add("resource_sensitive_deck")
    if any(
        _safe_float(features.get("move_field_to_base")) > 0
        and _safe_float(features.get("move_field_to_base_exposes_lethal_pressure")) <= 0
        for features in all_features
    ):
        tags.add("safe_field_to_base")
    return tags


def _public_deep_v2_deck_plan_tags(choices: list[tuple[Any, dict[str, float]]]) -> set[str]:
    tags: set[str] = set()
    for _, features in choices:
        for key, value in features.items():
            if _safe_float(value) <= 0:
                continue
            if key.startswith("own_deck_archetype:"):
                tags.add(key.split(":", 1)[1])
            elif key.startswith("own_deck_plan:"):
                tags.add(key.split(":", 1)[1])
    return tags


def _public_deep_v2_planner_should_activate(state_tags: set[str]) -> bool:
    return (
        {"enemy_dp_pressure", "own_low_life"}.issubset(state_tags)
        or {"observed_aggressive_pressure", "own_low_life"}.issubset(state_tags)
        or {"early_game", "resource_sensitive_deck", "safe_field_to_base"}.issubset(state_tags)
    )


def _public_deep_v2_action_matches_trace(action: Any, trace_action: dict[str, Any]) -> bool:
    if str(getattr(action, "kind", "")) != str(trace_action.get("kind") or ""):
        return False
    return dict(getattr(action, "payload", {}) or {}) == dict(trace_action.get("payload") or {})


def enable_observed_opponent_features_for_model(engine: Any, model: Any) -> None:
    if model_uses_observed_opponent_features(model):
        setattr(engine, "enable_observed_opponent_features", True)


# ── player correction model (learned from replay data) ──────────────

_player_correction_model: Any = None
_player_correction_model_weight: float = 0.0


def load_player_correction_model(path: str | None = None, *, weight: float = 0.3) -> None:
    """Load a player-trained correction model for runtime use.

    The correction model is a lightweight linear scorer trained on player
    preference pairs. Its score is added to the baseline model's score
    to bias toward human-like decisions.

    Args:
        path: Path to a ``PlayerCorrectionModel`` JSON file.
              Defaults to the latest trained model.
        weight: How much the correction score contributes (0.0 = off).
    """
    global _player_correction_model, _player_correction_model_weight
    if path is None:
        from pathlib import Path as _Path
        default = _Path("local_ai_training/player_correction_model_20260530/correction_model.json")
        if default.exists():
            path = str(default)
        else:
            _player_correction_model = None
            _player_correction_model_weight = 0.0
            return
    from zz.player_correction_model import PlayerCorrectionModel as _PCM
    _player_correction_model = _PCM.load(path)
    _player_correction_model_weight = float(weight)


def player_correction_score(features: dict[str, float]) -> float:
    """Return the correction model's score for these features, or 0.0.

    The true second player gets a stronger correction because the baseline
    model historically struggled from the second-turn role. Seat labels are
    not firstness and must not drive this correction.
    """
    if _player_correction_model is None or _player_correction_model_weight <= 0.0:
        return 0.0
    try:
        base_score = float(_player_correction_model.score(features))
        is_second_player = _safe_float(features.get("learner_is_second_player")) > 0
        weight = _player_correction_model_weight * (3.0 if is_second_player else 1.0)
        return weight * base_score
    except Exception:
        return 0.0


# ── card-aware and opponent-adaptive runtime priors ──────────────────


def card_aware_action_prior(features: dict[str, float]) -> float:
    """Adjust action score based on card properties (CardProfile lookup).

    Uses existing feature keys (``play_card_id:*``, ``attacker_id:*``,
    ``move_card_id:*``) to look up :class:`CardProfile`
    and apply card-specific bonuses or penalties.

    Returns 0.0 when no card identity can be resolved.
    """
    semantic_bonus = _semantic_card_role_action_prior(features)
    card_id = _resolve_card_id_from_features(features)
    if card_id is None:
        return semantic_bonus

    profile = _cached_card_profile(card_id)
    if profile is None:
        return semantic_bonus

    bonus = float(semantic_bonus)

    # ── play_card context ────────────────────────────────────────
    if _safe_float(features.get("action:play_card")) > 0:
        target_enemy = _safe_float(features.get("target_enemy")) > 0
        target_own = _safe_float(features.get("target_own")) > 0

        # Resource development: playing B_MINION to base is almost always good
        if profile.zone_value.good_mana_card and not target_enemy and not target_own:
            bonus += 0.20

        # Removal cards
        if "removal" in profile.roles:
            if target_enemy:
                bonus += 0.60
            if target_own and (
                profile.target_semantics.any_target_unsafe_on_own
                or profile.target_semantics.enemy_preferred
            ):
                bonus -= 0.80

        # Buff cards
        if "buff" in profile.roles or profile.target_semantics.beneficial:
            if target_own:
                bonus += 0.45
            if target_enemy and not profile.target_semantics.harmful:
                bonus -= 0.60

        # Defensive flash: prefer holding until opponent's turn
        if "defensive_flash" in profile.roles:
            if not _safe_float(features.get("is_enemy_turn")) > 0:
                bonus -= 0.40  # prefer waiting for enemy turn

        # Poor mana card (removal/buff magic): don't waste as mana
        if profile.zone_value.poor_mana_card:
            if not target_enemy and not target_own:
                bonus -= 0.35  # using removal as mana is wasteful

        return bonus

    # ── attack context ────────────────────────────────────────────
    if _safe_float(features.get("action:attack")) > 0:
        # Zero-DP attacks
        if profile.tactical_risks.zero_dp_attacker:
            if (
                _safe_float(features.get("attack_has_lethal_player_target"))
                or _attack_has_reliable_force_break(features)
            ):
                return 0.0  # legitimate zero-DP attack
            return -0.70  # no-payoff zero-DP attack

        # Low-BP attacker vs bigger blocker → suicide
        if profile.tactical_risks.low_bp_attacker:
            if _safe_float(features.get("bigger_enemy_blocker")) > 0:
                return -0.40

        # Finisher/combo piece: protect it, don't trade
        if "finisher" in profile.roles or "combo_piece" in profile.roles:
            if not _safe_float(features.get("attack_has_lethal_player_target")) > 0:
                bonus -= 0.25  # penalty for risking finisher

        # Card that should not attack (0 DP but not caught above)
        if profile.zone_value.usually_should_not_attack:
            if (
                not _safe_float(features.get("attack_has_lethal_player_target")) > 0
                and not _attack_has_reliable_force_break(features)
            ):
                bonus -= 0.50

        return bonus

    # ── move_card context ─────────────────────────────────────────
    if _safe_float(features.get("action:move_card")) > 0:
        # Pulling card FROM base TO field
        if _safe_float(features.get("move_base_to_field")) > 0:
            if profile.zone_value.protect_in_base:
                return -0.60  # finisher/combo should stay in base
            if profile.zone_value.stay_field_as_blocker:
                return 0.25  # blocker belongs on field
            if profile.zone_value.good_mana_card and not profile.zone_value.stay_field_as_blocker:
                return -0.15  # mana source is better left in base

        # Moving card FROM field TO base (resource development)
        if _safe_float(features.get("move_field_to_base")) > 0:
            if profile.zone_value.protect_in_base:
                return 0.25  # moving finisher to safety is good
            if profile.zone_value.stay_field_as_blocker:
                return -0.35  # removing a blocker weakens defense
            if profile.zone_value.good_mana_card:
                return 0.15  # generally good to develop mana

        return 0.0

    return 0.0


def _semantic_card_role_action_prior(features: dict[str, float]) -> float:
    bonus = 0.0
    if _safe_float(features.get("action:play_card")) > 0.0:
        if _safe_float(features.get("positive_reanimate_from_trash")) > 0.0:
            bonus += 0.85
        elif (
            _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
            and _safe_float(features.get("play_card_summon_from_trash_own_target_available")) > 0.0
        ):
            bonus += 0.65
        elif _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0:
            bonus += 0.25
        if (
            _safe_float(features.get("play_card_profile_role:death_payoff")) > 0.0
            or _safe_float(features.get("play_card_semantic_role:death_payoff")) > 0.0
        ):
            bonus += 0.45
        if (
            _safe_float(features.get("positive_self_destroy_death_payoff")) > 0.0
            or _safe_float(features.get("target_has_on_destroy_effect")) > 0.0
        ):
            bonus += 0.65
    if _safe_float(features.get("action:move_card")) > 0.0:
        if (
            _safe_float(features.get("move_card_profile_role:death_payoff")) > 0.0
            or _safe_float(features.get("move_card_semantic_role:death_payoff")) > 0.0
        ):
            bonus += 0.25
    return bonus


def opponent_adaptive_action_prior(features: dict[str, float]) -> float:
    """Adjust action score based on opponent pressure and game situation.

    Uses features already in the baseline model's vocabulary — no
    observed-opponent metadata opt-in required.
    """
    bonus = 0.0

    under_pressure = (
        _safe_float(features.get("enemy_field_dp_pressure")) > 0
        or _safe_float(features.get("enemy_pressure_high_player_risk")) > 0
    )
    own_low_life = 0 < _safe_float(features.get("own_player_life")) <= 0.5
    few_blockers = 0 < _safe_float(features.get("own_field_count")) <= 0.25
    early_game = 0 < _safe_float(features.get("turn_normalized")) <= 0.25

    # Under enemy pressure + vulnerable: boost defense
    if under_pressure and (own_low_life or few_blockers):
        if _safe_float(features.get("action:end_turn")) > 0:
            bonus += 0.80
        if _safe_float(features.get("action:attack")) > 0:
            if not _safe_float(features.get("attack_has_lethal_player_target")) > 0:
                bonus -= 0.60
        if _safe_float(features.get("move_base_to_field")) > 0:
            if few_blockers:
                bonus -= 0.50
        if _safe_float(features.get("move_field_to_base")) > 0:
            if few_blockers:
                bonus -= 0.40
            else:
                bonus += 0.15

    # Early game: boost resource development
    if early_game:
        if _safe_float(features.get("move_field_to_base")) > 0:
            if _safe_float(features.get("move_field_to_base_under_curve")) > 0:
                bonus += 0.15

    return bonus


def deck_plan_action_prior(features: dict[str, float]) -> float:
    """Score action alignment with the active deck's deterministic plan tags.

    This is intentionally policy-layer only: old checkpoints do not see these
    profile keys unless they explicitly opt into semantic scoring.
    """
    score = 0.0
    play_card = _safe_float(features.get("action:play_card")) > 0.0
    move_card = _safe_float(features.get("action:move_card")) > 0.0
    attack = _safe_float(features.get("action:attack")) > 0.0
    end_turn = _safe_float(features.get("action:end_turn")) > 0.0
    combo_deck = (
        _safe_float(features.get("own_deck_combo_route:life_exchange")) > 0.0
        or _safe_float(features.get("own_deck_archetype:combo")) > 0.0
    )
    draw_setup = _safe_float(features.get("own_deck_plan:draw_search_setup")) > 0.0
    base_growth = _safe_float(features.get("own_deck_plan:base_growth")) > 0.0
    hold_defense = _safe_float(features.get("own_deck_plan:hold_defense")) > 0.0
    pressure = (
        _safe_float(features.get("own_deck_plan:pressure")) > 0.0
        or _safe_float(features.get("own_deck_plan:lethal_push")) > 0.0
    )

    if play_card and combo_deck:
        if _safe_float(features.get("play_card_force_life_exchange_sets_enemy_low_life")) > 0.0:
            score += 2.4
        if _safe_float(features.get("play_card_force_life_exchange_has_followup_damage")) > 0.0:
            score += 1.4
        if _safe_float(features.get("play_card_force_life_exchange_search_support")) > 0.0:
            score += 1.2
        if _safe_float(features.get("play_card_force_life_exchange_search_for_deck_piece")) > 0.0:
            score += 0.9
        if _safe_float(features.get("play_card_force_life_exchange_search_near_cast")) > 0.0:
            score += 0.9
        if _safe_float(features.get("play_card_profile_role:life_exchange")) > 0.0:
            score += 0.8
        elif _safe_float(features.get("play_card_profile_role:combo_piece")) > 0.0:
            score += 0.35

    if play_card and draw_setup:
        if _safe_float(features.get("play_card_base_search_support")) > 0.0:
            score += 0.9
        if _safe_float(features.get("play_card_profile_role:draw")) > 0.0:
            score += 0.6

    if base_growth:
        if play_card:
            if _safe_float(features.get("play_card_base_development_support")) > 0.0:
                score += 0.9
            if _safe_float(features.get("play_card_place_base_from_hand_support")) > 0.0:
                score += 0.7
            if _safe_float(features.get("play_card_early_base_development_support")) > 0.0:
                score += 0.8
        if move_card and _safe_float(features.get("move_field_to_base")) > 0.0:
            if _safe_float(features.get("move_field_to_base_exposes_lethal_pressure")) <= 0.0:
                score += 0.35
                if _safe_float(features.get("move_field_to_base_under_curve")) > 0.0:
                    score += 0.45
                if _safe_float(features.get("move_field_to_base_future_play")) > 0.0:
                    score += 0.35
                if _safe_float(features.get("move_field_to_base_restores_missing_hand_color")) > 0.0:
                    score += 0.6

    under_pressure = (
        _safe_float(features.get("enemy_field_dp_pressure")) > 0.0
        or _safe_float(features.get("enemy_pressure_high_player_risk")) > 0.0
        or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0.0
    )
    if hold_defense and under_pressure:
        if play_card and _safe_float(features.get("play_card_defensive_reactive_on_enemy_turn")) > 0.0:
            score += 1.0
        if end_turn and _safe_float(features.get("own_player_life")) <= 0.5:
            score += 0.4
        if attack and _safe_float(features.get("attack_has_lethal_player_target")) <= 0.0:
            score -= 0.8

    if pressure and attack:
        if _safe_float(features.get("attack_has_lethal_player_target")) > 0.0:
            score += 1.2
        elif _attack_has_reliable_force_break(features):
            score += 0.5
        elif under_pressure and _safe_float(features.get("own_player_life")) <= 0.4:
            score -= 0.6

    return score


# ── card identity resolution ────────────────────────────────────────


def _resolve_card_id_from_features(features: dict[str, float]) -> str | None:
    """Extract card ID from existing feature keys."""
    for key, value in features.items():
        if _safe_float(value) <= 0:
            continue
        if key.startswith("play_card_id:"):
            return key.split(":", 1)[1]
        if key.startswith("attacker_id:"):
            return key.split(":", 1)[1]
        if key.startswith("move_card_id:"):
            return key.split(":", 1)[1]
    return None


_card_profile_cache: dict[str, Any] = {}


def _cached_card_profile(card_id: str) -> Any | None:
    """Look up CardProfile with simple cache."""
    if card_id in _card_profile_cache:
        return _card_profile_cache[card_id]
    from zz.card_profiles import build_card_profile
    from zz.cards import CARD_REGISTRY

    card = CARD_REGISTRY.get(card_id)
    if card is None:
        _card_profile_cache[card_id] = None
        return None
    profile = build_card_profile(card)
    _card_profile_cache[card_id] = profile
    return profile


class FeatureExtractor:
    def __init__(self) -> None:
        self._card_features_cache: dict[tuple[str, int, str], dict[str, float]] = {}

    def __deepcopy__(self, memo: dict[int, Any]) -> "FeatureExtractor":
        clone = self.__class__.__new__(self.__class__)
        memo[id(self)] = clone
        for key, value in self.__dict__.items():
            if key == "_card_features_cache":
                setattr(clone, key, value)
            else:
                setattr(clone, key, copy.deepcopy(value, memo))
        if not hasattr(clone, "_card_features_cache"):
            clone._card_features_cache = {}
        return clone

    def features_for_action(self, engine: Any, player: Any, action: Action) -> dict[str, float]:
        player = self._player_for_action(engine, player, action)
        state_features = self.state_features(engine, player)
        action_features = self.action_features(engine, player, action)
        features = dict(state_features)
        features.update(action_features)
        features.update(self._state_action_interactions(state_features, action_features))
        return features

    def features_for_actions(
        self,
        engine: Any,
        player: Any,
        actions: list[Action],
    ) -> list[tuple[Action, dict[str, float]]]:
        state_features_by_player_id: dict[int, dict[str, float]] = {}
        rows: list[tuple[Action, dict[str, float]]] = []
        for action in actions:
            action_player = self._player_for_action(engine, player, action)
            player_key = id(action_player)
            state_features = state_features_by_player_id.get(player_key)
            if state_features is None:
                state_features = self.state_features(engine, action_player)
                state_features_by_player_id[player_key] = state_features
            action_features = self.action_features(engine, action_player, action)
            features = dict(state_features)
            features.update(action_features)
            features.update(self._state_action_interactions(state_features, action_features))
            rows.append((action, features))
        return rows

    def features_for_state(self, engine: Any, player: Any) -> dict[str, float]:
        opponent = self._opponent(engine, player)
        features = dict(self.state_features(engine, player))
        features["state_value_context"] = 1.0
        features["life"] = float(getattr(player, "life", 0) or 0)
        features["opponent_life"] = float(getattr(opponent, "life", 0) or 0)
        features["hand_size"] = float(_safe_len(getattr(player, "hand", [])))
        features["field_size"] = float(_safe_len(getattr(player, "field", [])))
        features["base_size"] = float(_safe_len(getattr(player, "base", [])))
        features["force_count"] = float(_safe_len(getattr(player, "forces", [])))
        features["opponent_field_size"] = float(_safe_len(getattr(opponent, "field", [])))
        features["opponent_force_count"] = float(_safe_len(getattr(opponent, "forces", [])))
        return features

    def state_features(self, engine: Any, player: Any) -> dict[str, float]:
        opponent = self._opponent(engine, player)
        own_base = list(getattr(player, "base", []))
        enemy_base = list(getattr(opponent, "base", []))
        own_field = list(getattr(player, "field", []))
        enemy_field = list(getattr(opponent, "field", []))
        own_base_colors = [self._base_mana_color(engine, ci) for ci in own_base]
        ready_mana_counts = self._ready_mana_color_counts(engine, player)
        hand_demand = self._hand_color_demand(player)
        ready_colored_count = sum(count for color, count in ready_mana_counts.items() if color != "colorless")
        hand_colored_demand = sum(amount for color, amount in hand_demand.items() if color != "colorless")
        playable_non_base_hand_count = self._playable_non_base_hand_count(engine, player)
        ready_demand_matches = sum(
            min(float(ready_mana_counts.get(color, 0)), float(amount))
            for color, amount in hand_demand.items()
            if color != "colorless"
        )
        own_life = float(getattr(player, "life", 0) or 0)
        enemy_dp_pressure = self._enemy_field_dp_pressure(engine, player)
        features = {
            "bias": 1.0,
            "turn_normalized": _clamp01(float(getattr(getattr(engine, "state", None), "turn", 0)) / 30.0),
            "own_player_life": _clamp01(float(getattr(player, "life", 0)) / 10.0),
            "enemy_player_life": _clamp01(float(getattr(opponent, "life", 0)) / 10.0),
            "own_force_life_total": _clamp01(self._force_life(player) / 20.0),
            "enemy_force_life_total": _clamp01(self._force_life(opponent) / 20.0),
            "own_forces_alive": _clamp01(self._forces_alive(player) / 2.0),
            "enemy_forces_alive": _clamp01(self._forces_alive(opponent) / 2.0),
            "own_hand_size": _clamp01(_safe_len(getattr(player, "hand", [])) / 10.0),
            "enemy_hand_size": _clamp01(_safe_len(getattr(opponent, "hand", [])) / 10.0),
            "own_deck_size": _clamp01(_safe_len(getattr(player, "deck", [])) / 40.0),
            "enemy_deck_size": _clamp01(_safe_len(getattr(opponent, "deck", [])) / 40.0),
            "own_base_count": _clamp01(len(own_base) / 10.0),
            "enemy_base_count": _clamp01(len(enemy_base) / 10.0),
            "own_colorless_base_count": _clamp01(sum(1 for color in own_base_colors if color is Color.COLORLESS) / 10.0),
            "own_colored_base_count": _clamp01(sum(1 for color in own_base_colors if color is not Color.COLORLESS) / 10.0),
            "own_colorless_only_streak": _clamp01(float(getattr(player, "colorless_only_streak", 0)) / 2.0),
            "can_swap_mana_color": 1.0 if self._can_swap_mana_color(engine, player, own_base_colors) else 0.0,
            "own_field_count": _clamp01(len(own_field) / 6.0),
            "enemy_field_count": _clamp01(len(enemy_field) / 6.0),
            "own_field_bp_total": _clamp01(sum(getattr(ci, "bp", getattr(getattr(ci, "card", None), "bp", 0)) for ci in own_field) / 10000.0),
            "enemy_field_bp_total": _clamp01(sum(getattr(ci, "bp", getattr(getattr(ci, "card", None), "bp", 0)) for ci in enemy_field) / 10000.0),
            "own_field_dp_total": _clamp01(sum(getattr(ci, "dp", getattr(getattr(ci, "card", None), "dp", 0)) for ci in own_field) / 10.0),
            "enemy_field_dp_total": _clamp01(sum(getattr(ci, "dp", getattr(getattr(ci, "card", None), "dp", 0)) for ci in enemy_field) / 10.0),
            "own_ready_field_dp_total": _clamp01(self._ready_field_dp_total(engine, player) / 10.0),
            "enemy_field_dp_pressure": _clamp01(enemy_dp_pressure / 10.0),
            "enemy_pressure_high_player_risk": 1.0 if self._enemy_pressure_high_player_risk(engine, player) else 0.0,
            "enemy_pressure_near_player_lethal": 1.0 if own_life > 0 and enemy_dp_pressure >= own_life else 0.0,
            "own_available_mana": _clamp01(self._available_mana(player) / 10.0),
            "own_movement_right": _clamp01(float(self._movement_right(player)) / 2.0),
            "own_ready_base_count": _clamp01(sum(ready_mana_counts.values()) / 10.0),
            "own_ready_colored_base_count": _clamp01(ready_colored_count / 10.0),
            "own_ready_color_matches_hand_demand": _clamp01(ready_demand_matches / 5.0),
            "own_no_ready_colored_mana_for_hand": (
                1.0 if hand_colored_demand > 0 and ready_colored_count == 0 and playable_non_base_hand_count <= 0 else 0.0
            ),
            "own_playable_non_base_hand_count": _clamp01(playable_non_base_hand_count / 5.0),
            "own_base_growth_available": 1.0 if self._base_growth_available(player) else 0.0,
            "own_field_to_base_candidate_count": _clamp01(self._field_to_base_candidate_count(engine, player) / 6.0),
        }
        features.update(self._turn_end_refresh_force_features(player, prefix="own"))
        features.update(self._turn_end_refresh_force_features(opponent, prefix="enemy"))
        features.update(self._color_count_features("own_ready_base_color", ready_mana_counts, denominator=5.0))
        features.update(self._color_count_features("own_hand_demand_color", hand_demand, denominator=5.0))
        features.update(self._zone_card_features("own_hand", getattr(player, "hand", [])))
        features.update(self._zone_card_features("own_base", own_base))
        features.update(self._zone_card_features("enemy_base", enemy_base))
        features.update(self._zone_card_features("own_field", own_field))
        features.update(self._zone_card_features("enemy_field", enemy_field))
        features.update(self._zone_card_features("own_trash", getattr(player, "trash", [])))
        features.update(self._zone_card_features("enemy_trash", getattr(opponent, "trash", [])))
        features.update(self._force_identity_features("own_force", getattr(player, "forces", [])))
        features.update(self._force_identity_features("enemy_force", getattr(opponent, "forces", [])))
        features.update(self._force_life_exchange_state_features(engine, player, opponent))
        features.update(self._player_context_features(player, opponent))
        features.update(self._observed_opponent_action_features(engine, player))
        features.update(self._deck_profile_features(player, prefix="own_deck"))
        return features

    def action_features(self, engine: Any, player: Any, action: Action) -> dict[str, float]:
        features = {
            _feature_key("action", action.kind): 1.0,
            "is_mana_action": 1.0 if action.kind in {"play_to_base", "place_colorless_mana", "swap_mana_color", "skip_mana"} else 0.0,
            "is_board_action": 1.0 if action.kind in {"play_card", "move_card", "activate_flash_ability"} else 0.0,
            "is_attack": 1.0 if action.kind == "attack" else 0.0,
            "is_end_or_pass": 1.0 if action.kind in {"end_turn", "flash_pass", "skip_mana"} else 0.0,
        }
        features.update(self._choice_context_features(player, "action", action.kind))
        instance = self._action_instance(player, action)
        card = getattr(instance, "card", instance) if instance is not None else None
        if card is not None:
            features.update(self.card_features("play_card", card))
            if self._card_has_on_destroy_effect(card):
                features["play_card_has_on_destroy_effect"] = 1.0
                if self._card_on_destroy_payoff_available(engine, player, card):
                    features["play_card_on_destroy_payoff_available"] = 1.0
            if self._has_effect_template(card, "exchange_player_force_life"):
                features.update(self._force_life_exchange_action_features(engine, player, prefix="play_card"))
            features.update(self._force_life_exchange_search_action_features(engine, player, card, prefix="play_card"))
            features.update(self._base_development_action_features(engine, player, card, prefix="play_card"))
            if action.kind in {"play_card", "activate_flash_ability"}:
                features.update(self._trash_recursion_action_features(engine, player, card, prefix="play_card"))
            if (
                action.kind == "play_card"
                and self._has_effect_template_timing(
                    card,
                    "move_to_base_rested",
                    {EffectTiming.ON_SUMMON, EffectTiming.ON_ENTER_FIELD},
                )
            ):
                features.update(self._play_card_move_to_base_action_features(engine, player, instance))
            if action.kind == "play_card" and getattr(card, "type", None) is CardType.F_MINION:
                features["play_card_develops_field_minion"] = 1.0
                features["play_card_field_minion_bp"] = max(0.0, float(getattr(card, "bp", 0) or 0.0) / 100.0)
                features["play_card_field_minion_dp"] = max(0.0, float(getattr(card, "dp", 0) or 0.0))
                if Keyword.RUSH in getattr(card, "keywords", []):
                    features["play_card_field_minion_rush"] = 1.0
                if Keyword.CANNOT_BLOCK not in getattr(card, "keywords", []):
                    features["play_card_adds_blocker"] = 1.0
                    if (
                        (
                            self._enemy_pressure_high_player_risk(engine, player)
                            or self._enemy_field_dp_pressure(engine, player) > 0.0
                        )
                        and self._play_card_adds_net_blocker(engine, player, card, action)
                    ):
                        features["play_card_adds_blocker_under_pressure"] = 1.0
                        features["positive_add_blocker_under_pressure"] = 1.0
        if action.kind == "play_card" and card is not None and _card_cost(card) > 0:
            if self._has_active_force(player, "force_so2"):
                features["play_card_with_turn_end_mana_refresh"] = 1.0
            if self._play_card_spends_only_ready_color_for_hand(engine, player, instance, card):
                features["play_card_spends_only_ready_color_for_hand"] = 1.0
        if action.kind in {"play_card", "activate_flash_ability"} and card is not None:
            features.update(self._targeted_effect_action_features(engine, player, card, source=instance))
            features.update(self._defensive_reactive_action_features(engine, player, card))
        if action.kind == "play_to_base" and instance is not None:
            features.update(self._play_to_base_action_features(engine, player, instance))
        if action.kind == "place_colorless_mana":
            supports_chimera_fix = self._place_colorless_supports_chimera_color_fix(engine, player)
            ignores_missing_color = self._place_colorless_ignores_missing_hand_color(engine, player)
            graveyard_payoff = self._place_colorless_replacement_has_graveyard_payoff(
                engine,
                player,
                action,
            )
            if supports_chimera_fix:
                features["place_colorless_mana_supports_chimera_color_fix"] = 1.0
            if ignores_missing_color:
                features["place_colorless_mana_ignores_missing_hand_color"] = 1.0
            if graveyard_payoff:
                features["place_colorless_mana_sends_revival_candidate_to_trash"] = 1.0
            full_chimera_fix = bool(supports_chimera_fix and not ignores_missing_color)
            if (
                not full_chimera_fix
                and not graveyard_payoff
                and self._place_colorless_replacement_is_no_effect_or_resource_waste(engine, player, action)
            ):
                if self._place_colorless_spends_ready_color_for_hand(engine, player, action):
                    features["place_colorless_mana_spends_ready_color_for_hand"] = 1.0
                else:
                    features["place_colorless_mana_full_base_no_replacement_payoff"] = 1.0
                features["negative_no_effect_resource_spend"] = 1.0
        if action.kind == "skip_mana" and _safe_len(getattr(player, "base", [])) < BASE_CAP:
            features["skip_mana_under_base_cap"] = 1.0
            features["negative_skip_mana_under_base_cap"] = 1.0
        if action.kind == "attack" and instance is not None:
            features.update(self._attack_action_features(engine, player, instance))
        replaced_base = self._replacement_base_instance(player, action)
        if replaced_base is not None:
            features.update(self._base_replacement_features(engine, player, replaced_base, prefix="replace_base"))
        replaced_field = self._replacement_field_instance(player, action)
        if replaced_field is not None:
            features.update(self._field_replacement_features(engine, player, replaced_field, prefix="replace_field"))
        if action.kind == "move_card":
            direction = action.payload.get("direction")
            features["move_base_to_field"] = 1.0 if direction == "base_to_field" else 0.0
            features["move_field_to_base"] = 1.0 if direction == "field_to_base" else 0.0
            if card is not None:
                features.update(self.card_features("move_card", card))
            if direction == "base_to_field" and instance is not None:
                features.update(self._base_replacement_features(engine, player, instance, prefix="move_base_to_field"))
                card_type = getattr(card, "type", None)
                if card_type is CardType.B_MINION:
                    features["move_base_to_field_b_minion"] = 1.0
                if Keyword.CANNOT_BLOCK in getattr(instance, "keywords", []):
                    features["move_base_to_field_cannot_block"] = 1.0
                elif not getattr(instance, "rested", False):
                    features["move_base_to_field_can_block"] = 1.0
                if not getattr(instance, "rested", False):
                    features["move_base_to_field_spends_ready_mana"] = 1.0
                    if self._playable_non_base_hand_count(engine, player) > 0:
                        features["move_base_to_field_with_playable_hand"] = 1.0
                if self._base_move_can_attack_player(engine, instance):
                    features["move_base_to_field_can_attack_player"] = 1.0
                    if self._base_move_attack_payoff_contested_by_larger_blocker(engine, player, instance):
                        features["move_base_to_field_attack_payoff_contested_by_larger_blocker"] = 1.0
                    elif self._base_move_has_immediate_attack_payoff(engine, player, instance):
                        features["move_base_to_field_immediate_attack_payoff"] = 1.0
                        if self._base_move_has_player_lethal_payoff(engine, player, instance):
                            features["move_base_to_field_immediate_player_lethal_payoff"] = 1.0
                        if self._base_move_has_force_break_payoff(engine, player, instance):
                            features["move_base_to_field_immediate_force_break_payoff"] = 1.0
                if self._base_to_field_delays_force_life_exchange(engine, player, instance):
                    features["move_base_to_field_delays_force_life_exchange"] = 1.0
                if (
                    card_type is CardType.B_MINION
                    and float(features.get("move_base_to_field_cannot_block", 0.0)) > 0.0
                    and float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) <= 0.0
                    and (
                        float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0
                        or float(features.get("move_base_to_field_only_ready_color_for_hand", 0.0)) > 0.0
                        or float(features.get("move_base_to_field_with_playable_hand", 0.0)) > 0.0
                    )
                ):
                    features["move_base_to_field_low_impact_mana_minion"] = 1.0
                if (
                    LookaheadRLPolicy._fragile_base_to_field_no_payoff(features)
                    or LookaheadRLPolicy._unproductive_base_to_field_resource_spend(features)
                ):
                    features["negative_no_effect_resource_spend"] = 1.0
            elif direction == "field_to_base" and instance is not None:
                base_count = _safe_len(getattr(player, "base", []))
                if base_count < BASE_CAP:
                    features["move_field_to_base_builds_mana"] = 1.0
                if base_count < self._target_base_count(engine, player):
                    features["move_field_to_base_under_curve"] = 1.0
                if self._max_non_base_hand_cost(player) > base_count:
                    features["move_field_to_base_future_play"] = 1.0
                enters_base_ready = not self._has_effect_template_timing(
                    card,
                    "move_to_base_rested",
                    {EffectTiming.MOVE_TO_BASE},
                )
                if not enters_base_ready:
                    features["move_field_to_base_enters_rested"] = 1.0
                mover_color_key = self._color_count_key(self._base_mana_color(engine, instance))
                if mover_color_key != self._color_count_key(Color.COLORLESS):
                    hand_demand = self._hand_color_demand(player)
                    if hand_demand.get(mover_color_key, 0.0) > 0.0:
                        features["move_field_to_base_matches_hand_color"] = 1.0
                        ready_counts = self._ready_mana_color_counts(engine, player)
                        if enters_base_ready and ready_counts.get(mover_color_key, 0) <= 0:
                            features["move_field_to_base_restores_missing_hand_color"] = 1.0
                if enters_base_ready and self._field_to_base_enables_playable_hand_card(
                    engine,
                    player,
                    instance,
                    replace_base_iid=action.payload.get("replace_base_iid"),
                ):
                    features["move_field_to_base_enables_playable_hand_card"] = 1.0
                if (
                    self._enemy_pressure_high_player_risk(engine, player)
                    or (
                        self._forces_alive(player) <= 0
                        and self._enemy_field_dp_pressure(engine, player) > 0.0
                    )
                ):
                    features["move_field_to_base_under_enemy_pressure"] = 1.0
                if self._enemy_pressure_near_player_lethal(engine, player):
                    features["move_field_to_base_exposes_lethal_pressure"] = 1.0
                if self._field_to_base_removes_last_blocker_under_pressure(engine, player, instance):
                    features["move_field_to_base_removes_last_blocker_under_enemy_pressure"] = 1.0
                if self._field_to_base_protects_high_value_attacker(engine, player, instance):
                    features["move_field_to_base_protects_high_value_attacker"] = 1.0
                if self._card_can_help_develop_base(card):
                    features["move_field_to_base_resource_engine"] = 1.0
                if self._field_to_base_spends_force_life_exchange_wall(engine, player, instance):
                    features["move_field_to_base_spends_force_life_exchange_wall"] = 1.0
        if action.kind == "swap_mana_color":
            features.update(self._mana_swap_action_features(engine, player, instance, action))
        return features

    def features_for_attack_target(self, engine: Any, player: Any, attacker: Any, target: Any) -> dict[str, float]:
        features = self.state_features(engine, player)
        features["decision:attack_target"] = 1.0
        features.update(self.card_features("attacker", getattr(attacker, "card", attacker)))
        ref = getattr(target, "ref", target)
        target_kind = getattr(target, "kind", None)
        features["target_player"] = 1.0 if target_kind is AttackTargetKind.PLAYER else 0.0
        features["target_force"] = 1.0 if target_kind is AttackTargetKind.FORCE else 0.0
        features["target_minion"] = 1.0 if target_kind is AttackTargetKind.MINION else 0.0
        features["target_lethal_player"] = 0.0
        features["target_lethal_force"] = 0.0
        attacker_dp = self._effective_dp(engine, attacker)
        target_card = getattr(ref, "card", None)
        if target_card is not None:
            features.update(self.card_features("target", target_card))
        if target_kind is AttackTargetKind.PLAYER:
            target_life = float(getattr(ref, "life", 0))
            features["target_lethal_player"] = 1.0 if target_life > 0 and attacker_dp >= target_life else 0.0
            if self._has_low_enemy_life_attack_pressure(engine, player, target_life):
                features["target_low_enemy_life_pressure_player"] = 1.0
            reduction = 1.0 if self._has_active_force(ref, "force_kai") else 0.0
            effective_damage = max(0.0, attacker_dp - reduction)
            features["target_player_effective_dp_damage"] = _clamp01(effective_damage / 5.0)
            if reduction > 0.0:
                features["target_player_damage_reduced_by_force_kai"] = 1.0
            if attacker_dp > 0.0 and effective_damage <= 0.0:
                features["target_player_damage_prevented_by_force_kai"] = 1.0
        elif target_kind is AttackTargetKind.FORCE:
            force_id = getattr(getattr(ref, "force", None), "id", None)
            if force_id:
                features[_feature_key("target_force_id", str(force_id))] = 1.0
            target_life = float(getattr(ref, "life", 0))
            features["target_lethal_force"] = 1.0 if target_life > 0 and attacker_dp >= target_life else 0.0
        features.update(self._target_stats(ref, attacker=attacker))
        return features

    def features_for_blocker(self, engine: Any, player: Any, attacker: Any, blocker: Any) -> dict[str, float]:
        features = self.state_features(engine, player)
        features["decision:blocker"] = 1.0
        features.update(self.card_features("attacker", getattr(attacker, "card", attacker)))
        blocker_card = getattr(blocker, "card", blocker)
        features.update(self.card_features("blocker", blocker_card))
        attacker_bp = self._effective_bp(engine, attacker)
        blocker_bp = self._effective_bp(engine, blocker)
        attacker_dp = self._effective_dp(engine, attacker)
        features["blocker_survives_bp"] = 1.0 if blocker_bp >= attacker_bp else 0.0
        features["blocker_cleanly_beats_attacker"] = 1.0 if blocker_bp > attacker_bp else 0.0
        features["blocker_trades_with_attacker"] = 1.0 if blocker_bp == attacker_bp and blocker_bp > 0 else 0.0
        features["blocker_loses_to_attacker"] = 1.0 if blocker_bp < attacker_bp else 0.0
        if self._card_has_on_destroy_effect(blocker_card):
            features["blocker_has_on_destroy_effect"] = 1.0
            blocker_owner = getattr(blocker, "owner", player)
            if self._card_on_destroy_payoff_available(engine, blocker_owner, blocker_card):
                features["blocker_on_destroy_payoff_available"] = 1.0
        death_payoff_blocker = (
            features.get("blocker_on_destroy_payoff_available", 0.0)
        )
        if death_payoff_blocker and attacker_bp > 0.0 and blocker_bp <= attacker_bp:
            features["blocker_death_payoff_would_trigger"] = 1.0
            features["positive_on_destroy_blocker"] = 1.0
        if attacker_dp <= 0.0 and not self._card_has_attack_payoff(getattr(attacker, "card", attacker)):
            features["blocker_wastes_on_zero_dp_attacker"] = 1.0
        features["blocker_prevents_lethal_player_damage"] = (
            1.0 if self._blocker_attack_targets_player(engine) and attacker_dp >= float(getattr(player, "life", 0)) > 0 else 0.0
        )
        if self._blocker_prevents_turn_lethal_player_damage(engine, player, attacker):
            features["blocker_prevents_turn_lethal_player_damage"] = 1.0
        features.update(self._blocker_context_features(engine, player, attacker, blocker=blocker))
        return features

    def features_for_no_blocker(self, engine: Any, player: Any, attacker: Any) -> dict[str, float]:
        features = self.state_features(engine, player)
        features["block:none"] = 1.0
        attacker_dp = self._effective_dp(engine, attacker)
        if self._blocker_attack_targets_player(engine) and attacker_dp >= float(getattr(player, "life", 0)) > 0:
            features["block_none_allows_lethal_player_damage"] = 1.0
        if self._block_none_allows_turn_lethal_player_damage(engine, player, attacker):
            features["block_none_allows_turn_lethal_player_damage"] = 1.0
        features.update(self._blocker_context_features(engine, player, attacker, blocker=None))
        return features

    def features_for_generic_target(self, engine: Any, player: Any, kind: str, target: Any) -> dict[str, float]:
        features = self.state_features(engine, player)
        features["decision:generic_target"] = 1.0
        features[_feature_key("target_kind", kind)] = 1.0
        features.update(self._generic_target_context_features(engine, player, kind, target))
        features.update(self._target_stats(target))
        return features

    def card_features(self, prefix: str, card: Any) -> dict[str, float]:
        cache = getattr(self, "_card_features_cache", None)
        if cache is None:
            cache = {}
            self._card_features_cache = cache
        cache_key = (str(prefix), id(card), str(getattr(card, "id", "") or ""))
        cached = cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        card_type = getattr(card, "type", None)
        features = {
            f"{prefix}_cost": _clamp01(_card_cost(card) / 10.0),
            f"{prefix}_is_minion": 1.0 if card_type in {CardType.F_MINION, CardType.B_MINION} else 0.0,
            f"{prefix}_is_magic": 1.0 if card_type is CardType.MAGIC else 0.0,
            f"{prefix}_has_effect": 1.0 if self._has_effect_text(card) else 0.0,
            f"{prefix}_has_flash": 1.0 if getattr(card, "flash_timing_ok", False) or getattr(card, "flash_ability", None) else 0.0,
            f"{prefix}_bp": _clamp01(float(getattr(card, "bp", 0)) / 2000.0),
            f"{prefix}_dp": _clamp01(float(getattr(card, "dp", 0)) / 5.0),
        }
        card_id = getattr(card, "id", None)
        if card_id:
            features[_feature_key(f"{prefix}_id", str(card_id))] = 1.0
        for template_id in self._effect_template_ids(card):
            features[_feature_key(f"{prefix}_effect", template_id)] = 1.0
        for effect in getattr(card, "effects", []) or []:
            template_id = str(getattr(effect, "template_id", "") or "")
            if template_id != "draw_cards":
                continue
            params = dict(getattr(effect, "params", {}) or {})
            if str(params.get("scope") or "").lower() == "both":
                features[_feature_key(f"{prefix}_effect", "draw_cards_both_players")] = 1.0
                features[_feature_key(f"{prefix}_risk", "gives_opponent_card")] = 1.0
            else:
                features[_feature_key(f"{prefix}_effect", "draw_cards_self_only")] = 1.0
        for color, amount in getattr(card, "cost", {}).items():
            features[_feature_key(f"{prefix}_cost_color", self._color_label(color))] = _clamp01(float(amount) / 5.0)
        features.update(self._card_profile_features(prefix, card))
        cache[cache_key] = dict(features)
        return dict(features)

    def _deck_profile_features(self, player: Any, *, prefix: str) -> dict[str, float]:
        profile = self._runtime_deck_profile(player)
        if not profile:
            return {}
        features: dict[str, float] = {}
        version = str(profile.get("version") or "")
        deck_id = str(profile.get("deck_id") or profile.get("deckId") or "")
        if version:
            features[_feature_key(f"{prefix}_profile_version", version)] = 1.0
        if deck_id:
            features[_feature_key(f"{prefix}_id", deck_id)] = 1.0
        if profile.get("resource_sensitive") or profile.get("resourceSensitive"):
            features[_feature_key(f"{prefix}_tag", "resource_sensitive")] = 1.0
            features[_feature_key(f"{prefix}_semantic_tag", "resource_sensitive")] = 1.0
        for route in profile.get("combo_routes") or profile.get("comboRoutes") or []:
            features[_feature_key(f"{prefix}_combo_route", str(route))] = 1.0
            features[_feature_key(f"{prefix}_semantic_combo_route", str(route))] = 1.0
        for plan_key in ("preferred_early_plan", "preferred_midgame_plan", "preferred_endgame_plan"):
            for plan in profile.get(plan_key) or profile.get(_camel_case(plan_key)) or []:
                features[_feature_key(f"{prefix}_plan", str(plan))] = 1.0
                features[_feature_key(f"{prefix}_semantic_plan", str(plan))] = 1.0
        archetype_scores = profile.get("archetype_scores") or profile.get("archetypeScores") or {}
        if isinstance(archetype_scores, dict):
            for archetype, raw_score in archetype_scores.items():
                score = _safe_float(raw_score)
                if score > 0.0:
                    features[_feature_key(f"{prefix}_archetype_score", str(archetype))] = _clamp01(score / 20.0)
                if score >= 1.0:
                    features[_feature_key(f"{prefix}_archetype", str(archetype))] = 1.0
                    features[_feature_key(f"{prefix}_semantic_archetype", str(archetype))] = 1.0
        return features

    def _runtime_deck_profile(self, player: Any) -> dict[str, Any]:
        player_profile = getattr(player, "profile", None)
        if not isinstance(player_profile, dict):
            return {}
        deck_profile = player_profile.get("deckProfile") or player_profile.get("deck_profile")
        if isinstance(deck_profile, dict):
            return deck_profile
        if hasattr(deck_profile, "to_dict"):
            return deck_profile.to_dict()
        deck_spec = player_profile.get("deckSpec") or player_profile.get("deck_spec")
        if isinstance(deck_spec, dict):
            try:
                from zz.ai_deck_analysis import DeckSpec
                from zz.deck_profiles import build_deck_profile

                profile = build_deck_profile(DeckSpec(
                    id=str(deck_spec.get("id") or "runtime-deck"),
                    name=str(deck_spec.get("name") or deck_spec.get("id") or "runtime deck"),
                    recipe={str(card_id): int(count) for card_id, count in (deck_spec.get("recipe") or {}).items()},
                    forces=[str(force_id) for force_id in deck_spec.get("forces") or []],
                ))
            except Exception:
                return {}
            return profile.to_dict()
        return {}

    def _card_profile_features(self, prefix: str, card: Any) -> dict[str, float]:
        try:
            from zz.card_profiles import build_card_profile
        except Exception:
            return {}
        try:
            profile = build_card_profile(card)
        except Exception:
            return {}
        features: dict[str, float] = {
            _feature_key(f"{prefix}_profile_version", profile.version): 1.0,
        }
        for role in profile.roles:
            features[_feature_key(f"{prefix}_profile_role", role)] = 1.0
            features[_feature_key(f"{prefix}_semantic_role", role)] = 1.0
        for field_name, enabled in vars(profile.target_semantics).items():
            if enabled:
                features[_feature_key(f"{prefix}_profile_target", field_name)] = 1.0
                features[_feature_key(f"{prefix}_semantic_target", field_name)] = 1.0
        for field_name, enabled in vars(profile.phase_semantics).items():
            if enabled:
                features[_feature_key(f"{prefix}_profile_phase", field_name)] = 1.0
                features[_feature_key(f"{prefix}_semantic_phase", field_name)] = 1.0
        for field_name, enabled in vars(profile.zone_value).items():
            if enabled:
                features[_feature_key(f"{prefix}_profile_zone", field_name)] = 1.0
                features[_feature_key(f"{prefix}_semantic_zone", field_name)] = 1.0
        for field_name, enabled in vars(profile.tactical_risks).items():
            if enabled:
                features[_feature_key(f"{prefix}_profile_risk", field_name)] = 1.0
                features[_feature_key(f"{prefix}_semantic_risk", field_name)] = 1.0
        return features

    def _state_action_interactions(
        self,
        state_features: dict[str, float],
        action_features: dict[str, float],
    ) -> dict[str, float]:
        action_keys = [
            key
            for key, value in action_features.items()
            if value and (key.startswith("action:") or key.startswith("play_card_id:"))
        ]
        visible_card_keys = [
            key
            for key, value in state_features.items()
            if value and "_card_id:" in key
        ]
        interactions = {
            _interaction_feature_key(action_key, state_key): action_features[action_key] * state_features[state_key]
            for action_key in action_keys
            for state_key in visible_card_keys
        }
        observed_aggression_defense_need = (
            float(state_features.get("opponent_observed_aggressive_pressure", 0.0)) > 0.0
            and float(state_features.get("own_player_life", 1.0)) <= 0.5
            and (
                float(state_features.get("own_forces_alive", 1.0)) <= 0.0
                or float(state_features.get("enemy_pressure_high_player_risk", 0.0)) > 0.0
                or float(state_features.get("enemy_pressure_near_player_lethal", 0.0)) > 0.0
            )
        )
        if observed_aggression_defense_need:
            if (
                float(action_features.get("action:attack", 0.0)) > 0.0
                and float(action_features.get("attack_has_lethal_player_target", 0.0)) <= 0.0
                and not _attack_has_reliable_force_break(action_features)
            ):
                interactions["attack_under_observed_aggression_defense_need"] = 1.0
            if (
                float(action_features.get("action:play_card", 0.0)) > 0.0
                and float(action_features.get("play_card_is_minion", 0.0)) > 0.0
            ):
                interactions["play_minion_under_observed_aggression_defense_need"] = 1.0
            if (
                float(action_features.get("move_base_to_field", 0.0)) > 0.0
                and float(action_features.get("move_base_to_field_can_block", 0.0)) > 0.0
            ):
                interactions["move_base_to_field_under_observed_aggression_defense_need"] = 1.0
            elif float(action_features.get("move_base_to_field", 0.0)) > 0.0:
                interactions["move_base_to_field_under_observed_aggression_no_blocker"] = 1.0
            if float(action_features.get("move_field_to_base", 0.0)) > 0.0:
                interactions["move_field_to_base_under_observed_aggression_defense_need"] = 1.0
            if float(action_features.get("action:end_turn", 0.0)) > 0.0:
                interactions["end_turn_under_observed_aggression_defense_need"] = 1.0
        interactions.update(self._semantic_state_action_features(state_features, action_features))
        return interactions

    def _semantic_state_action_features(
        self,
        state_features: dict[str, float],
        action_features: dict[str, float],
    ) -> dict[str, float]:
        features: dict[str, float] = {}
        if float(state_features.get("own_deck_semantic_plan:base_growth", 0.0)) > 0.0:
            field_to_base_develops = (
                float(action_features.get("move_field_to_base", 0.0)) > 0.0
                and float(action_features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
                and (
                    float(action_features.get("move_field_to_base_under_curve", 0.0)) > 0.0
                    or float(action_features.get("move_field_to_base_future_play", 0.0)) > 0.0
                    or float(action_features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0
                    or float(action_features.get("move_field_to_base_resource_engine", 0.0)) > 0.0
                )
            )
            play_to_base_develops = (
                float(action_features.get("action:play_to_base", 0.0)) > 0.0
                and (
                    float(state_features.get("own_base_growth_available", 0.0)) > 0.0
                    or float(action_features.get("play_to_base_matches_hand_color", 0.0)) > 0.0
                    or float(action_features.get("play_to_base_restores_missing_hand_color", 0.0)) > 0.0
                )
            )
            if field_to_base_develops or play_to_base_develops:
                features[_feature_key("semantic_action_plan", "base_growth")] = 1.0
                features[_feature_key("semantic_action_resource", "base_development")] = 1.0
            if (
                float(action_features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0
                or float(action_features.get("play_to_base_restores_missing_hand_color", 0.0)) > 0.0
                or float(action_features.get("play_card_move_to_base_restores_missing_hand_color", 0.0)) > 0.0
            ):
                features[_feature_key("semantic_action_resource", "repair_missing_color")] = 1.0
        if float(state_features.get("own_deck_semantic_plan:hold_defense", 0.0)) > 0.0:
            risky_attack = (
                float(action_features.get("action:attack", 0.0)) > 0.0
                and float(action_features.get("attack_has_lethal_player_target", 0.0)) <= 0.0
                and not _attack_has_reliable_force_break(action_features)
                and (
                    float(action_features.get("attack_without_forces_under_enemy_pressure", 0.0)) > 0.0
                    or float(action_features.get("attack_while_low_life_no_forces", 0.0)) > 0.0
                    or float(action_features.get("attack_exposes_lethal_next_turn", 0.0)) > 0.0
                    or float(action_features.get("attack_loses_to_larger_blocker_without_pressure", 0.0)) > 0.0
                    or float(action_features.get("attack_suicide_into_larger_blocker_without_pressure", 0.0)) > 0.0
                    or float(action_features.get("attack_low_dp_into_larger_blocker", 0.0)) > 0.0
                    or float(action_features.get("attack_removes_last_blocker_under_enemy_pressure", 0.0)) > 0.0
                    or float(action_features.get("attack_spends_high_value_blocker_under_enemy_pressure", 0.0)) > 0.0
                )
            )
            if risky_attack:
                features[_feature_key("semantic_action_risk", "breaks_hold_defense")] = 1.0
            if (
                float(action_features.get("move_base_to_field_can_block", 0.0)) > 0.0
                and (
                    float(action_features.get("move_base_to_field_under_observed_aggression_defense_need", 0.0)) > 0.0
                    or float(state_features.get("enemy_pressure_high_player_risk", 0.0)) > 0.0
                    or float(state_features.get("enemy_pressure_near_player_lethal", 0.0)) > 0.0
                )
            ):
                features[_feature_key("semantic_action_plan", "hold_defense")] = 1.0

        if float(state_features.get("own_deck_semantic_combo_route:life_exchange", 0.0)) > 0.0:
            if (
                float(action_features.get("play_card_exchange_player_force_life", 0.0)) > 0.0
                and float(action_features.get("play_card_force_life_exchange_sets_enemy_low_life", 0.0)) > 0.0
            ):
                features[_feature_key("semantic_action_combo", "life_exchange_execute")] = 1.0
            if (
                float(action_features.get("attack_spends_force_life_exchange_combo_wall", 0.0)) > 0.0
                or float(action_features.get("move_field_to_base_spends_force_life_exchange_wall", 0.0)) > 0.0
            ):
                features[_feature_key("semantic_action_risk", "breaks_life_exchange_plan")] = 1.0
        return features

    def _play_card_move_to_base_action_features(self, engine: Any, player: Any, instance: Any | None) -> dict[str, float]:
        if instance is None:
            return {}
        features: dict[str, float] = {}
        color = self._base_mana_color(engine, instance)
        color_key = self._color_count_key(color)
        if color_key == self._color_count_key(Color.COLORLESS):
            return features
        remaining_demand = self._hand_color_demand_excluding(player, instance)
        if remaining_demand.get(color_key, 0.0) <= 0.0:
            return features
        features["play_card_move_to_base_matches_hand_color"] = 1.0
        ready_counts = self._ready_mana_color_counts(engine, player)
        unfixable_demand = self._hand_color_demand_excluding_chimera_fixable_items(
            engine,
            player,
            ready_counts=ready_counts,
            excluded_instance=instance,
        )
        if unfixable_demand.get(color_key, 0.0) > 0.0:
            features["play_card_move_to_base_matches_unfixable_hand_color"] = 1.0
        else:
            features["play_card_move_to_base_matches_only_chimera_fixable_hand_color"] = 1.0
        return features

    def _zone_card_features(self, prefix: str, zone: Any) -> dict[str, float]:
        features: dict[str, float] = {}
        cost_by_color: dict[str, float] = {}
        for item in zone or []:
            card = getattr(item, "card", item)
            card_id = getattr(card, "id", None)
            if card_id:
                features[_feature_key(f"{prefix}_card_id", str(card_id))] = 1.0
            for color, amount in getattr(card, "cost", {}).items():
                key = _feature_key(f"{prefix}_cost_color", self._color_label(color))
                cost_by_color[key] = cost_by_color.get(key, 0.0) + float(amount)
        for key, amount in cost_by_color.items():
            features[key] = _clamp01(amount / 5.0)
        return features

    def _color_count_features(self, prefix: str, counts: dict[str, float] | dict[str, int], *, denominator: float) -> dict[str, float]:
        return {
            _feature_key(prefix, color): _clamp01(float(amount) / denominator)
            for color, amount in counts.items()
            if amount
        }

    def _force_identity_features(self, prefix: str, forces: Any) -> dict[str, float]:
        ids = sorted(
            str(force_id)
            for force_id in (
                getattr(getattr(force_instance, "force", None), "id", None)
                for force_instance in (forces or [])
            )
            if force_id
        )
        features = {_feature_key(f"{prefix}_id", force_id): 1.0 for force_id in ids}
        if ids:
            features[_feature_key(f"{prefix}_combo", "_".join(ids))] = 1.0
        return features

    def _color_label(self, color: Any) -> str:
        color_label = getattr(color, "name", None)
        if not isinstance(color_label, str):
            color_label = getattr(color, "value", color)
        return str(color_label)

    def _play_to_base_action_features(self, engine: Any, player: Any, instance: Any) -> dict[str, float]:
        features: dict[str, float] = {}
        color = self._base_mana_color(engine, instance)
        color_key = self._color_count_key(color)
        if color_key == self._color_count_key(Color.COLORLESS):
            return features
        hand_demand = self._hand_color_demand(player)
        if hand_demand.get(color_key, 0.0) <= 0.0:
            return features
        features["play_to_base_matches_hand_color"] = 1.0
        ready_counts = self._ready_mana_color_counts(engine, player)
        if ready_counts.get(color_key, 0) <= 0:
            features["play_to_base_restores_missing_hand_color"] = 1.0
        unfixable_demand = self._hand_color_demand_excluding_chimera_fixable_items(
            engine,
            player,
            ready_counts=ready_counts,
            extra_colorless_tokens=1,
        )
        if unfixable_demand.get(color_key, 0.0) > 0.0:
            features["play_to_base_matches_unfixable_hand_color"] = 1.0
            if ready_counts.get(color_key, 0) <= 0:
                features["play_to_base_restores_missing_unfixable_hand_color"] = 1.0
        else:
            features["play_to_base_matches_only_chimera_fixable_hand_color"] = 1.0
        if self._play_to_base_spends_chimera_fixable_field_minion(
            engine,
            player,
            instance,
            ready_counts=ready_counts,
            extra_colorless_tokens=1,
        ):
            features["play_to_base_spends_chimera_fixable_field_minion"] = 1.0
        return features

    def _hand_color_demand_excluding_chimera_fixable_items(
        self,
        engine: Any,
        player: Any,
        *,
        ready_counts: dict[str, int],
        extra_colorless_tokens: int = 0,
        excluded_instance: Any | None = None,
    ) -> dict[str, float]:
        demand: dict[str, float] = {}
        excluded_iid = getattr(excluded_instance, "iid", None)
        for item in getattr(player, "hand", []) or []:
            if item is excluded_instance or (
                excluded_iid is not None and getattr(item, "iid", None) == excluded_iid
            ):
                continue
            if self._colorless_mana_can_fix_colored_cost_for_item(
                engine,
                player,
                item,
                ready_counts=ready_counts,
                extra_colorless_tokens=extra_colorless_tokens,
            ):
                continue
            for color, amount in self._effective_cost(engine, player, item).items():
                if self._color_count_key(color) == self._color_count_key(Color.COLORLESS):
                    continue
                key = self._color_count_key(color)
                demand[key] = demand.get(key, 0.0) + float(amount)
        return demand

    def _play_to_base_spends_chimera_fixable_field_minion(
        self,
        engine: Any,
        player: Any,
        instance: Any,
        *,
        ready_counts: dict[str, int],
        extra_colorless_tokens: int = 0,
    ) -> bool:
        card = getattr(instance, "card", instance)
        if getattr(card, "type", None) is not CardType.F_MINION:
            return False
        return self._colorless_mana_can_fix_colored_cost_for_item(
            engine,
            player,
            instance,
            ready_counts=ready_counts,
            extra_colorless_tokens=extra_colorless_tokens,
        )

    def _place_colorless_ignores_missing_hand_color(self, engine: Any, player: Any) -> bool:
        hand_demand = self._hand_color_demand(player)
        ready_counts = self._ready_mana_color_counts(engine, player)
        for item in getattr(player, "hand", []) or []:
            if self._colorless_mana_can_fix_colored_cost_for_item(
                engine,
                player,
                item,
                ready_counts=ready_counts,
                extra_colorless_tokens=1,
            ):
                continue
            color_key = self._color_count_key(self._base_mana_color(engine, item))
            if color_key == self._color_count_key(Color.COLORLESS):
                continue
            if hand_demand.get(color_key, 0.0) > 0.0 and ready_counts.get(color_key, 0) <= 0:
                return True
        return False

    def _place_colorless_supports_chimera_color_fix(self, engine: Any, player: Any) -> bool:
        ready_counts = self._ready_mana_color_counts(engine, player)
        return any(
            self._colorless_mana_can_fix_colored_cost_for_item(
                engine,
                player,
                item,
                ready_counts=ready_counts,
                extra_colorless_tokens=1,
            )
            for item in getattr(player, "hand", []) or []
        )

    def _place_colorless_spends_ready_color_for_hand(self, engine: Any, player: Any, action: Action) -> bool:
        hand_demand = self._hand_color_demand(player)
        colored_demand = {
            color: float(amount)
            for color, amount in hand_demand.items()
            if color != "colorless" and float(amount) > 0.0
        }
        if not colored_demand:
            return False
        ready_counts = self._ready_mana_color_counts(engine, player)
        replacement = self._replacement_base_instance(player, action)
        if replacement is None:
            return False
        after_counts = dict(ready_counts)
        if not getattr(replacement, "rested", False):
            replaced_color = self._color_count_key(self._base_mana_color(engine, replacement))
            after_counts[replaced_color] = max(0, int(after_counts.get(replaced_color, 0) or 0) - 1)
            after_counts["colorless"] = int(after_counts.get("colorless", 0) or 0) + 1
        return any(
            float(ready_counts.get(color, 0) or 0) >= amount
            and float(after_counts.get(color, 0) or 0) < amount
            for color, amount in colored_demand.items()
        )

    def _place_colorless_replacement_has_graveyard_payoff(
        self,
        engine: Any,
        player: Any,
        action: Action,
    ) -> bool:
        replacement = self._replacement_base_instance(player, action)
        if replacement is None:
            return False
        card = getattr(replacement, "card", replacement)
        return self._own_trash_recursion_can_reuse_card(player, card)

    def _place_colorless_replacement_is_no_effect_or_resource_waste(
        self,
        engine: Any,
        player: Any,
        action: Action,
    ) -> bool:
        replacement = self._replacement_base_instance(player, action)
        if replacement is None:
            return False
        if _safe_len(getattr(player, "base", [])) < BASE_CAP:
            return False
        if self._place_colorless_spends_ready_color_for_hand(engine, player, action):
            return True
        return True

    def _colorless_mana_can_fix_colored_cost_for_item(
        self,
        engine: Any,
        player: Any,
        item: Any,
        *,
        ready_counts: dict[str, int],
        extra_colorless_tokens: int = 0,
    ) -> bool:
        if not self._colorless_counts_as_any_mana(engine, player, item):
            return False
        cost = self._effective_cost(engine, player, item)
        missing_colored = 0
        for color, amount in cost.items():
            color_key = self._color_count_key(color)
            if color_key == "colorless":
                continue
            missing_colored += max(0, int(amount) - int(ready_counts.get(color_key, 0) or 0))
        if missing_colored <= 0:
            return False
        colorless_available = int(ready_counts.get("colorless", 0) or 0) + max(0, int(extra_colorless_tokens))
        return colorless_available >= missing_colored

    def _colorless_counts_as_any_mana(self, engine: Any, player: Any, item: Any) -> bool:
        helper = getattr(engine, "_colorless_counts_as_any_mana", None)
        if callable(helper):
            try:
                return bool(helper(player, item))
            except Exception:
                pass
        card = getattr(item, "card", item)
        return bool(
            self._has_active_force(player, "force_kon")
            and getattr(card, "type", None) is CardType.F_MINION
        )

    def _can_swap_mana_color(self, engine: Any, player: Any, base_colors: list[Color]) -> bool:
        return (
            getattr(player, "is_first_player", None) is False
            and int(getattr(player, "colorless_only_streak", 0)) >= 2
            and any(color is Color.COLORLESS for color in base_colors)
        )

    def _mana_swap_action_features(self, engine: Any, player: Any, instance: Any | None, action: Action) -> dict[str, float]:
        features: dict[str, float] = {}
        if instance is not None:
            features[_feature_key("swap_mana_from", self._color_label(self._base_mana_color(engine, instance)))] = 1.0
        new_color = self._payload_color(action.payload.get("new_color"))
        if new_color is not None:
            features[_feature_key("swap_mana_to", self._color_label(new_color))] = 1.0
            color_key = self._color_count_key(new_color)
            hand_demand = self._hand_color_demand(player)
            base_colors = {
                self._color_count_key(self._base_mana_color(engine, ci))
                for ci in getattr(player, "base", [])
            }
            if hand_demand.get(color_key, 0.0) > 0:
                features["swap_mana_to_hand_demand"] = 1.0
                if color_key not in base_colors:
                    features["swap_mana_to_missing_hand_color"] = 1.0
                if instance is not None and self._swap_enables_playable_hand_card(engine, player, instance, new_color):
                    features["swap_mana_enables_playable_hand_card"] = 1.0
                    if self._base_growth_available(player):
                        features["swap_mana_delays_base_growth"] = 1.0
                    else:
                        features["swap_mana_fallback_unsticks_hand"] = 1.0
        return features

    def _swap_enables_playable_hand_card(self, engine: Any, player: Any, instance: Any, new_color: Any) -> bool:
        before = self._ready_mana_color_counts(engine, player)
        after = self._ready_mana_color_counts(engine, player, replacement=(instance, new_color))
        for item in getattr(player, "hand", []) or []:
            card = getattr(item, "card", item)
            cost = getattr(card, "cost", {})
            if (
                cost
                and not self._can_pay_item_from_color_counts(engine, player, item, before, cost)
                and self._can_pay_item_from_color_counts(engine, player, item, after, cost)
            ):
                return True
        return False

    def _field_to_base_enables_playable_hand_card(
        self,
        engine: Any,
        player: Any,
        instance: Any,
        *,
        replace_base_iid: Any | None = None,
    ) -> bool:
        if getattr(instance, "rested", False):
            return False
        before = self._ready_mana_color_counts(engine, player)
        after = dict(before)
        if replace_base_iid is not None:
            for base in getattr(player, "base", []) or []:
                if getattr(base, "iid", None) != replace_base_iid or getattr(base, "rested", False):
                    continue
                replaced_key = self._color_count_key(self._base_mana_color(engine, base))
                after[replaced_key] = max(0, int(after.get(replaced_key, 0) or 0) - 1)
                break
        mover_key = self._color_count_key(self._base_mana_color(engine, instance))
        after[mover_key] = int(after.get(mover_key, 0) or 0) + 1
        for item in getattr(player, "hand", []) or []:
            card = getattr(item, "card", item)
            if getattr(card, "type", None) is CardType.B_MINION:
                continue
            cost = self._effective_cost(engine, player, item)
            if not cost:
                continue
            before_can = self._engine_can_pay(engine, player, item, cost)
            if before_can is None:
                before_can = self._can_pay_item_from_color_counts(engine, player, item, before, cost)
            if before_can:
                continue
            if self._can_pay_item_from_color_counts(engine, player, item, after, cost):
                return True
        return False

    def _ready_mana_color_counts(
        self,
        engine: Any,
        player: Any,
        *,
        replacement: tuple[Any, Any] | None = None,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        replacement_iid = None
        replacement_color = None
        if replacement is not None:
            replacement_iid = getattr(replacement[0], "iid", None)
            replacement_color = replacement[1]
        for ci in getattr(player, "base", []) or []:
            if getattr(ci, "rested", False):
                continue
            color = replacement_color if getattr(ci, "iid", None) == replacement_iid else self._base_mana_color(engine, ci)
            key = self._color_count_key(color)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _can_pay_from_color_counts(self, counts: dict[str, int], cost: dict[Any, int]) -> bool:
        remaining = dict(counts)
        for color, amount in cost.items():
            key = self._color_count_key(color)
            if key == "colorless":
                continue
            if remaining.get(key, 0) < int(amount):
                return False
            remaining[key] -= int(amount)
        available_for_colorless = sum(remaining.values())
        colorless_cost = int(sum(amount for color, amount in cost.items() if self._color_count_key(color) == "colorless"))
        return available_for_colorless >= colorless_cost

    def _can_pay_item_from_color_counts(
        self,
        engine: Any,
        player: Any,
        item: Any,
        counts: dict[str, int],
        cost: dict[Any, int],
    ) -> bool:
        if self._colorless_counts_as_any_mana(engine, player, item):
            return self._can_pay_from_color_counts_with_colorless_as_any(counts, cost)
        return self._can_pay_from_color_counts(counts, cost)

    def _can_pay_from_color_counts_with_colorless_as_any(
        self,
        counts: dict[str, int],
        cost: dict[Any, int],
    ) -> bool:
        remaining = {str(key): int(value) for key, value in counts.items()}
        colorless_key = self._color_count_key(Color.COLORLESS)
        for color, amount in cost.items():
            key = self._color_count_key(color)
            if key == colorless_key:
                continue
            need = int(amount)
            same_color = min(int(remaining.get(key, 0) or 0), need)
            remaining[key] = int(remaining.get(key, 0) or 0) - same_color
            need -= same_color
            if need > 0:
                colorless = min(int(remaining.get(colorless_key, 0) or 0), need)
                remaining[colorless_key] = int(remaining.get(colorless_key, 0) or 0) - colorless
                need -= colorless
            if need > 0:
                return False
        colorless_cost = int(
            sum(amount for color, amount in cost.items() if self._color_count_key(color) == colorless_key)
        )
        return sum(max(0, int(value)) for value in remaining.values()) >= colorless_cost

    def _playable_non_base_hand_count(self, engine: Any, player: Any) -> int:
        counts = self._ready_mana_color_counts(engine, player)
        total = 0
        for item in getattr(player, "hand", []) or []:
            card = getattr(item, "card", item)
            if getattr(card, "type", None) is CardType.B_MINION:
                continue
            cost = self._effective_cost(engine, player, item)
            if not cost:
                continue
            engine_can_pay = self._engine_can_pay(engine, player, item, cost)
            if engine_can_pay is True:
                total += 1
            elif engine_can_pay is None and self._can_pay_from_color_counts(counts, cost):
                total += 1
        return total

    def _engine_can_pay(self, engine: Any, player: Any, item: Any, cost: dict[Any, int]) -> bool | None:
        can_pay = getattr(engine, "_can_pay", None)
        if not callable(can_pay):
            return None
        try:
            return bool(can_pay(player, cost, item))
        except Exception:
            return None

    def _effective_cost(self, engine: Any, player: Any, item: Any) -> dict[Any, int]:
        effective_cost = getattr(engine, "effective_cost", None)
        if callable(effective_cost):
            try:
                return dict(effective_cost(player, item))
            except Exception:
                pass
        return dict(getattr(getattr(item, "card", item), "cost", {}) or {})

    def _base_move_can_attack_player(self, engine: Any, instance: Any) -> bool:
        if getattr(instance, "rested", False) or getattr(instance, "summoning_sickness", False):
            return False
        present = getattr(getattr(engine, "state", None), "present_at_turn_start", set())
        return getattr(instance, "iid", None) in present

    def _base_move_has_immediate_attack_payoff(self, engine: Any, player: Any, instance: Any) -> bool:
        return (
            self._base_move_has_player_lethal_payoff(engine, player, instance)
            or self._base_move_has_force_break_payoff(engine, player, instance)
        )

    def _base_move_has_player_lethal_payoff(self, engine: Any, player: Any, instance: Any) -> bool:
        if not self._base_move_can_attack_player(engine, instance):
            return False
        attacker_dp = self._effective_dp(engine, instance)
        if attacker_dp <= 0.0:
            return False
        opponent = self._opponent(engine, player)
        return bool(attacker_dp >= float(getattr(opponent, "life", 0) or 0) > 0.0)

    def _base_move_has_force_break_payoff(self, engine: Any, player: Any, instance: Any) -> bool:
        if not self._base_move_can_attack_player(engine, instance):
            return False
        attacker_dp = self._effective_dp(engine, instance)
        if attacker_dp <= 0.0:
            return False
        opponent = self._opponent(engine, player)
        return any(
            attacker_dp >= float(getattr(force, "life", 0) or 0) > 0.0
            for force in getattr(opponent, "forces", []) or []
            if not getattr(force, "destroyed", False)
        )

    def _base_move_attack_payoff_contested_by_larger_blocker(self, engine: Any, player: Any, instance: Any) -> bool:
        if not self._base_move_has_immediate_attack_payoff(engine, player, instance):
            return False
        legal_blockers = getattr(engine, "legal_blockers", None)
        if not callable(legal_blockers):
            return False
        try:
            blockers = list(legal_blockers(instance))
        except Exception:
            return False
        if not blockers:
            return False
        attacker_bp = self._effective_bp(engine, instance)
        return any(self._effective_bp(engine, blocker) > attacker_bp for blocker in blockers)

    def _base_to_field_delays_force_life_exchange(self, engine: Any, player: Any, instance: Any) -> bool:
        exchange_costs = [
            _card_cost(getattr(item, "card", item))
            for item in getattr(player, "hand", []) or []
            if self._has_effect_template(getattr(item, "card", item), "exchange_player_force_life")
        ]
        if not exchange_costs:
            return False
        base_count = _safe_len(getattr(player, "base", []))
        return base_count - 1 < min(exchange_costs)

    def _hand_color_demand(self, player: Any) -> dict[str, float]:
        demand: dict[str, float] = {}
        for item in getattr(player, "hand", []) or []:
            card = getattr(item, "card", item)
            for color, amount in getattr(card, "cost", {}).items():
                if color is Color.COLORLESS:
                    continue
                key = self._color_count_key(color)
                demand[key] = demand.get(key, 0.0) + float(amount)
        return demand

    def _hand_color_demand_excluding(self, player: Any, excluded_instance: Any) -> dict[str, float]:
        demand: dict[str, float] = {}
        excluded_iid = getattr(excluded_instance, "iid", None)
        for item in getattr(player, "hand", []) or []:
            if item is excluded_instance or (
                excluded_iid is not None and getattr(item, "iid", None) == excluded_iid
            ):
                continue
            card = getattr(item, "card", item)
            for color, amount in getattr(card, "cost", {}).items():
                if color is Color.COLORLESS:
                    continue
                key = self._color_count_key(color)
                demand[key] = demand.get(key, 0.0) + float(amount)
        return demand

    def _play_card_spends_only_ready_color_for_hand(
        self,
        engine: Any,
        player: Any,
        instance: Any,
        card: Any,
    ) -> bool:
        if instance is None or _card_cost(card) <= 0:
            return False
        ready_counts = self._ready_mana_color_counts(engine, player)
        ready_total = sum(int(count) for count in ready_counts.values())
        if ready_total <= 0 or ready_total > _card_cost(card):
            return False
        ready_colored = {
            color: int(count)
            for color, count in ready_counts.items()
            if color != self._color_count_key(Color.COLORLESS) and int(count) > 0
        }
        if not ready_colored:
            return False
        remaining_demand = self._hand_color_demand_excluding(player, instance)
        strained_colors = {
            color for color in ready_colored if remaining_demand.get(color, 0.0) > 0.0
        }
        if not strained_colors:
            return False
        card_color = self._color_count_key(self._base_mana_color(engine, instance))
        if (
            getattr(card, "type", None) is CardType.B_MINION
            and card_color in strained_colors
        ):
            return False
        return True

    def _base_growth_available(self, player: Any) -> bool:
        if len(getattr(player, "base", []) or []) >= BASE_CAP:
            return False
        return any(
            getattr(getattr(item, "card", item), "type", None) is CardType.B_MINION
            for item in getattr(player, "hand", []) or []
        )

    def _field_to_base_candidate_count(self, engine: Any, player: Any) -> int:
        total = 0
        movement_locked = getattr(engine, "_movement_locked", None)
        for ci in getattr(player, "field", []) or []:
            card = getattr(ci, "card", ci)
            if getattr(card, "type", None) is CardType.MANA_TOKEN or getattr(card, "is_token", False):
                continue
            if callable(movement_locked):
                try:
                    if movement_locked(ci):
                        continue
                except Exception:
                    pass
            total += 1
        return total

    def _color_count_key(self, color: Any) -> str:
        return _feature_token(self._color_label(color))

    def _payload_color(self, value: Any) -> Any | None:
        if value is None:
            return None
        if isinstance(value, Color):
            return value
        try:
            return Color(value)
        except (ValueError, TypeError):
            pass
        if isinstance(value, str):
            try:
                return Color[value.upper()]
            except KeyError:
                return value
        return value

    def _base_mana_color(self, engine: Any, ci: Any) -> Color:
        mana_color_of = getattr(engine, "_mana_color_of", None)
        if callable(mana_color_of):
            try:
                return mana_color_of(ci)
            except Exception:
                pass
        override = getattr(ci, "mana_color_override", None)
        if override is not None:
            return override
        card = getattr(ci, "card", ci)
        if getattr(card, "type", None) is CardType.MANA_TOKEN:
            return Color.COLORLESS
        mana_color = getattr(card, "mana_color", None)
        if mana_color is not None:
            return mana_color
        for color in getattr(card, "cost", {}):
            if color is not Color.COLORLESS:
                return color
        return Color.COLORLESS

    def _player_for_action(self, engine: Any, player: Any, action: Action) -> Any:
        iid = action.payload.get("iid") or action.payload.get("attacker_iid") or action.payload.get("base_card_iid")
        if iid is None:
            return player
        for candidate in getattr(getattr(engine, "state", None), "players", []):
            if self._find_instance(candidate, iid) is not None:
                return candidate
        return player

    def _opponent(self, engine: Any, player: Any) -> Any:
        players = list(getattr(getattr(engine, "state", None), "players", []))
        for candidate in players:
            if candidate is not player:
                return candidate
        return getattr(getattr(engine, "state", None), "opponent", SimplePlayer())

    def _player_context_features(self, player: Any, opponent: Any) -> dict[str, float]:
        first_marker = getattr(player, "is_first_player", None)
        opponent_first_marker = getattr(opponent, "is_first_player", None)
        return {
            "learner_is_first_player": 1.0 if first_marker is True else 0.0,
            "learner_is_second_player": 1.0 if first_marker is False else 0.0,
            "opponent_is_first_player": 1.0 if opponent_first_marker is True else 0.0,
        }

    def _observed_opponent_action_features(self, engine: Any, player: Any) -> dict[str, float]:
        if not bool(getattr(engine, "enable_observed_opponent_features", False)):
            return {}
        profiles = getattr(engine, "observed_action_profile_by_player_side", {}) or {}
        if not isinstance(profiles, dict):
            return {}
        profile = profiles.get(self._side_label(player), {}) or {}
        if not isinstance(profile, dict):
            return {}
        action_count = int(profile.get("opponent_action_count", 0) or 0)
        if action_count <= 0:
            return {}
        early_action_count = int(profile.get("opponent_early_action_count", 0) or 0)
        attack_count = int(profile.get("opponent_attack_count", 0) or 0)
        early_attack_count = int(profile.get("opponent_early_attack_count", 0) or 0)
        face_attack_count = int(profile.get("opponent_attack_player_count", 0) or 0)
        base_to_field_count = int(profile.get("opponent_move_base_to_field_count", 0) or 0)
        field_to_base_count = int(profile.get("opponent_move_field_to_base_count", 0) or 0)
        play_to_base_count = int(profile.get("opponent_play_to_base_count", 0) or 0)
        aggression_events = early_attack_count + face_attack_count + base_to_field_count
        setup_events = field_to_base_count + play_to_base_count
        features = {
            "opponent_observed_action_count": _clamp01(action_count / 20.0),
            "opponent_observed_attack_rate": _clamp01(attack_count / max(1.0, float(action_count))),
            "opponent_observed_early_attack_rate": _clamp01(early_attack_count / max(1.0, float(early_action_count))),
            "opponent_observed_face_attack_rate": _clamp01(face_attack_count / max(1.0, float(attack_count))),
            "opponent_observed_base_to_field_rate": _clamp01(base_to_field_count / max(1.0, float(action_count))),
            "opponent_observed_field_to_base_rate": _clamp01(field_to_base_count / max(1.0, float(action_count))),
            "opponent_observed_aggression_index": _clamp01(aggression_events / 6.0),
            "opponent_observed_setup_index": _clamp01(setup_events / 6.0),
        }
        if aggression_events >= 2 and aggression_events > setup_events:
            features["opponent_observed_aggressive_pressure"] = 1.0
        return features

    def _choice_context_features(self, player: Any, prefix: str, choice: str) -> dict[str, float]:
        features: dict[str, float] = {}
        choice_key = re.sub(r"[^a-zA-Z0-9_]+", "_", str(choice)).strip("_").lower() or "unknown"
        first_marker = getattr(player, "is_first_player", None)
        if first_marker is True:
            features[f"{prefix}_by_first_player:{choice_key}"] = 1.0
        elif first_marker is False:
                features[f"{prefix}_by_second_player:{choice_key}"] = 1.0
        return features

    def _turn_end_refresh_force_features(self, player: Any, *, prefix: str) -> dict[str, float]:
        return {
            f"{prefix}_turn_end_refreshes_mana": 1.0 if self._has_active_force(player, "force_so2") else 0.0,
            f"{prefix}_turn_end_refreshes_minions": 1.0 if self._has_active_force(player, "force_rin") else 0.0,
        }

    def _has_active_force(self, player: Any, force_id: str) -> bool:
        for force_instance in getattr(player, "forces", []) or []:
            force = getattr(force_instance, "force", None)
            if getattr(force, "id", None) != force_id:
                continue
            if getattr(force_instance, "destroyed", False) or getattr(force_instance, "rested", False):
                continue
            return True
        return False

    def _side_label(self, player: Any) -> str:
        side = getattr(player, "side", "")
        side_name = getattr(side, "name", side)
        return str(side_name).upper()

    def _force_life(self, player: Any) -> float:
        return float(sum(getattr(force, "life", 0) for force in getattr(player, "forces", []) if not getattr(force, "destroyed", False)))

    def _forces_alive(self, player: Any) -> float:
        return float(sum(1 for force in getattr(player, "forces", []) if not getattr(force, "destroyed", False)))

    def _available_mana(self, player: Any) -> int:
        return sum(1 for ci in getattr(player, "base", []) if not getattr(ci, "rested", False))

    def _movement_right(self, player: Any) -> int:
        return int(getattr(player, "movement_right_count", getattr(player, "movement_right", 0)))

    def _action_card(self, player: Any, action: Action) -> Any | None:
        instance = self._action_instance(player, action)
        return getattr(instance, "card", instance) if instance is not None else None

    def _action_instance(self, player: Any, action: Action) -> Any | None:
        iid = action.payload.get("iid") or action.payload.get("attacker_iid") or action.payload.get("base_card_iid")
        if iid is None:
            return None
        return self._find_instance(player, iid)

    def _replacement_base_instance(self, player: Any, action: Action) -> Any | None:
        iid = action.payload.get("replace_base_iid")
        if iid is None:
            return None
        return self._find_instance(player, iid)

    def _replacement_field_instance(self, player: Any, action: Action) -> Any | None:
        iid = action.payload.get("replace_field_iid")
        if iid is None:
            return None
        return self._find_instance(player, iid)

    def _play_card_adds_net_blocker(self, engine: Any, player: Any, card: Any, action: Action) -> bool:
        replacement = self._replacement_field_instance(player, action)
        if replacement is None:
            return True
        return self._blocker_defense_value(engine, card) > self._blocker_defense_value(engine, replacement)

    def _blocker_defense_value(self, engine: Any, card_or_instance: Any) -> float:
        card = getattr(card_or_instance, "card", card_or_instance)
        if getattr(card, "type", None) not in {CardType.F_MINION, CardType.B_MINION}:
            return 0.0
        if Keyword.CANNOT_BLOCK in getattr(card, "keywords", []):
            return 0.0
        bp = (
            self._effective_bp(engine, card_or_instance)
            if hasattr(card_or_instance, "card")
            else float(getattr(card, "bp", 0) or 0.0)
        )
        dp = (
            self._effective_dp(engine, card_or_instance)
            if hasattr(card_or_instance, "card")
            else float(getattr(card, "dp", 0) or 0.0)
        )
        return max(0.0, dp) * 10000.0 + max(0.0, bp)

    def _base_replacement_features(
            self,
            engine: Any,
            player: Any,
            base_instance: Any,
            *,
            prefix: str,
    ) -> dict[str, float]:
        card = getattr(base_instance, "card", base_instance)
        mana_color = self._base_mana_color(engine, base_instance)
        value = self._base_card_value(engine, player, base_instance)
        features = {
            f"{prefix}_value": _clamp01(value / 10.0),
            f"{prefix}_ready": 0.0 if getattr(base_instance, "rested", False) else 1.0,
            f"{prefix}_mana_token": 1.0 if getattr(card, "type", None) is CardType.MANA_TOKEN else 0.0,
            f"{prefix}_colored_mana": 1.0 if mana_color is not Color.COLORLESS else 0.0,
            _feature_key(f"{prefix}_mana_color", self._color_label(mana_color)): 1.0,
        }
        if getattr(card, "type", None) in {CardType.B_MINION, CardType.F_MINION}:
            features[f"{prefix}_protects_minion"] = 1.0
        if self._is_only_ready_color_for_hand(engine, player, base_instance, mana_color):
            features[f"{prefix}_only_ready_color_for_hand"] = 1.0
        if self._own_trash_recursion_can_reuse_card(player, card):
            features[f"{prefix}_own_revival_candidate"] = 1.0
        return features

    def _base_card_value(self, engine: Any, player: Any, base_instance: Any) -> float:
        card = getattr(base_instance, "card", base_instance)
        if getattr(card, "type", None) is CardType.MANA_TOKEN:
            return 0.5
        value = 1.5 + float(_card_cost(card)) * 0.7
        value += float(getattr(card, "bp", 0) or 0) / 1000.0
        value += float(getattr(card, "dp", 0) or 0) * 0.8
        if self._has_effect_text(card):
            value += 1.5
        mana_color = self._base_mana_color(engine, base_instance)
        if mana_color is not Color.COLORLESS:
            value += 1.0
        if self._is_only_ready_color_for_hand(engine, player, base_instance, mana_color):
            value += 3.0
        return value

    def _field_replacement_features(
            self,
            engine: Any,
            player: Any,
            field_instance: Any,
            *,
            prefix: str,
    ) -> dict[str, float]:
        card = getattr(field_instance, "card", field_instance)
        value = self._field_card_value(engine, player, field_instance)
        features = {
            f"{prefix}_value": _clamp01(value / 12.0),
            f"{prefix}_ready": 0.0 if getattr(field_instance, "rested", False) else 1.0,
            f"{prefix}_rested": 1.0 if getattr(field_instance, "rested", False) else 0.0,
            f"{prefix}_token": 1.0 if getattr(card, "is_token", False) else 0.0,
            f"{prefix}_can_block": 1.0 if self._field_minion_can_block(engine, field_instance) else 0.0,
            f"{prefix}_blocker_value": _clamp01(self._blocker_defense_value(engine, field_instance) / 30000.0),
            f"{prefix}_bp": _clamp01(self._effective_bp(engine, field_instance) / 2000.0),
            f"{prefix}_dp": _clamp01(self._effective_dp(engine, field_instance) / 5.0),
        }
        features.update(self.card_features(prefix, card))
        if self._card_has_on_destroy_effect(card):
            features[f"{prefix}_has_on_destroy_effect"] = 1.0
        if self._own_trash_recursion_can_reuse_card(player, card):
            features[f"{prefix}_own_revival_candidate"] = 1.0
        if (
            features[f"{prefix}_can_block"] > 0.0
            and self._enemy_field_dp_pressure(engine, player) > 0.0
        ):
            features[f"{prefix}_blocker_under_pressure"] = 1.0
        return features

    def _field_card_value(self, engine: Any, player: Any, field_instance: Any) -> float:
        card = getattr(field_instance, "card", field_instance)
        if getattr(card, "is_token", False):
            return 0.25
        value = 1.0 + float(_card_cost(card)) * 0.45
        value += self._effective_bp(engine, field_instance) / 1000.0
        value += self._effective_dp(engine, field_instance) * 0.8
        if self._field_minion_can_block(engine, field_instance):
            value += 1.0
        if self._has_effect_text(card):
            value += 1.0
        if self._card_has_on_destroy_effect(card):
            value += 1.0
        if self._own_trash_recursion_can_reuse_card(player, card):
            value -= 0.5
        return max(0.0, value)

    def _field_to_base_protects_high_value_attacker(self, engine: Any, player: Any, instance: Any) -> bool:
        card = getattr(instance, "card", instance)
        if getattr(card, "type", None) not in {CardType.F_MINION, CardType.B_MINION}:
            return False
        if self._effective_dp(engine, instance) <= 0.0:
            return False
        if getattr(card, "is_token", False):
            return False
        high_value = (
            self._effective_bp(engine, instance) >= 1000.0
            or self._effective_dp(engine, instance) >= 3.0
            or self._has_effect_text(card)
        )
        if not high_value:
            return False
        return self._enemy_field_dp_pressure(engine, player) > 0.0

    def _field_to_base_spends_force_life_exchange_wall(self, engine: Any, player: Any, instance: Any) -> bool:
        card = getattr(instance, "card", instance)
        if getattr(card, "type", None) not in {CardType.F_MINION, CardType.B_MINION}:
            return False
        if getattr(card, "is_token", False):
            return False
        if getattr(instance, "rested", False):
            return False
        if self._effective_bp(engine, instance) <= 0.0:
            return False
        if self._enemy_field_dp_pressure(engine, player) <= 0.0:
            return False
        if not self._has_force_life_exchange_plan(player):
            return False
        opponent = self._opponent(engine, player)
        lowest_force_life = self._lowest_own_force_life(player)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        return lowest_force_life is not None and 0.0 < lowest_force_life < enemy_life

    def _is_only_ready_color_for_hand(self, engine: Any, player: Any, base_instance: Any, mana_color: Any) -> bool:
        if mana_color is Color.COLORLESS or getattr(base_instance, "rested", False):
            return False
        color_key = self._color_count_key(mana_color)
        if self._hand_color_demand(player).get(color_key, 0.0) <= 0.0:
            return False
        ready_matches = [
            ci
            for ci in getattr(player, "base", []) or []
            if not getattr(ci, "rested", False)
            and self._color_count_key(self._base_mana_color(engine, ci)) == color_key
        ]
        return len(ready_matches) == 1 and ready_matches[0] is base_instance

    def _force_life_exchange_state_features(self, engine: Any, player: Any, opponent: Any) -> dict[str, float]:
        features: dict[str, float] = {}
        lowest_force_life = self._lowest_own_force_life(player)
        if lowest_force_life is not None:
            features["own_lowest_force_life"] = _clamp01(lowest_force_life / 10.0)
        has_plan = self._has_force_life_exchange_plan(player)
        if has_plan:
            features["own_has_force_life_exchange_plan"] = 1.0
            if self._has_force_life_exchange_in_deck(player):
                features["own_deck_has_force_life_exchange"] = 1.0
            enemy_life = float(getattr(opponent, "life", 0) or 0)
            if lowest_force_life is None:
                features["own_force_life_exchange_resource_lost"] = 1.0
            else:
                features["own_force_life_exchange_resource_alive"] = 1.0
                if 0.0 < lowest_force_life < enemy_life:
                    features["own_force_life_exchange_low_force_resource"] = 1.0
                    features["own_force_life_exchange_plan_delta"] = _clamp01((enemy_life - lowest_force_life) / 10.0)
        if self._has_force_life_exchange_in_hand(player):
            features["own_hand_has_force_life_exchange"] = 1.0
            enemy_life = float(getattr(opponent, "life", 0) or 0)
            if lowest_force_life is not None and 0.0 < lowest_force_life < enemy_life:
                features["own_force_life_exchange_combo_window"] = 1.0
                features["own_force_life_exchange_delta"] = _clamp01((enemy_life - lowest_force_life) / 10.0)
                if self._ready_field_dp_total(engine, player) >= lowest_force_life:
                    features["own_force_life_exchange_followup_damage_available"] = 1.0
        return features

    def _force_life_exchange_action_features(self, engine: Any, player: Any, *, prefix: str) -> dict[str, float]:
        opponent = self._opponent(engine, player)
        lowest_force_life = self._lowest_own_force_life(player)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        features = {f"{prefix}_exchange_player_force_life": 1.0}
        if lowest_force_life is not None:
            features[f"{prefix}_lowest_force_life_target"] = _clamp01(lowest_force_life / 10.0)
        if lowest_force_life is not None and 0.0 < lowest_force_life < enemy_life:
            features[f"{prefix}_force_life_exchange_sets_enemy_low_life"] = 1.0
            features[f"{prefix}_force_life_exchange_delta"] = _clamp01((enemy_life - lowest_force_life) / 10.0)
            if self._ready_field_dp_total(engine, player) >= lowest_force_life:
                features[f"{prefix}_force_life_exchange_has_followup_damage"] = 1.0
        return features

    def _force_life_exchange_search_action_features(
            self,
            engine: Any,
            player: Any,
            card: Any,
            *,
            prefix: str,
    ) -> dict[str, float]:
        if not self._has_force_life_exchange_in_deck(player):
            return {}
        if not self._card_can_help_find_force_life_exchange_piece(card):
            return {}
        opponent = self._opponent(engine, player)
        lowest_force_life = self._lowest_own_force_life(player)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        if lowest_force_life is None or lowest_force_life <= 0.0 or lowest_force_life >= enemy_life:
            return {}
        features = {
            f"{prefix}_force_life_exchange_search_support": 1.0,
            f"{prefix}_force_life_exchange_search_for_deck_piece": 1.0,
            f"{prefix}_force_life_exchange_search_delta": _clamp01((enemy_life - lowest_force_life) / 10.0),
        }
        if len(getattr(player, "base", []) or []) >= 7:
            features[f"{prefix}_force_life_exchange_search_near_cast"] = 1.0
        return features

    def _base_development_action_features(
            self,
            engine: Any,
            player: Any,
            card: Any,
            *,
            prefix: str,
    ) -> dict[str, float]:
        if not self._card_can_help_develop_base(card):
            return {}
        features = {f"{prefix}_base_development_support": 1.0}
        if self._card_can_search_base_minion(card):
            features[f"{prefix}_base_search_support"] = 1.0
        if self._card_can_place_base_from_hand(card):
            features[f"{prefix}_place_base_from_hand_support"] = 1.0
        turn = float(getattr(getattr(engine, "state", None), "turn", 0) or 0)
        if turn <= 5.0 and _safe_len(getattr(player, "base", [])) < self._target_base_count(engine, player):
            features[f"{prefix}_early_base_development_support"] = 1.0
        return features

    def _force_life_exchange_target_features(self, engine: Any, player: Any, target: Any) -> dict[str, float]:
        features: dict[str, float] = {}
        if getattr(target, "owner", None) is not player or not hasattr(target, "force"):
            return features
        opponent = self._opponent(engine, player)
        target_life = float(getattr(target, "life", 0) or 0)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        if target_life <= 0.0:
            return features
        if target_life < enemy_life:
            features["target_force_life_exchange_combo_payoff"] = 1.0
            features["target_force_life_exchange_delta"] = _clamp01((enemy_life - target_life) / 10.0)
            if self._ready_field_dp_total(engine, player) >= target_life:
                features["target_force_life_exchange_followup_damage"] = 1.0
        return features

    def _force_life_exchange_search_target_features(
            self,
            engine: Any,
            player: Any,
            kind: str,
            target: Any,
    ) -> dict[str, float]:
        if not (kind.startswith("deck_") or kind.startswith("top")):
            return {}
        if getattr(target, "owner", None) is not player:
            return {}
        card = getattr(target, "card", target)
        if not self._has_effect_template(card, "exchange_player_force_life"):
            return {}
        opponent = self._opponent(engine, player)
        lowest_force_life = self._lowest_own_force_life(player)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        if lowest_force_life is None or lowest_force_life <= 0.0 or lowest_force_life >= enemy_life:
            return {}
        features = {
            "target_force_life_exchange_search_payoff": 1.0,
            "target_force_life_exchange_search_delta": _clamp01((enemy_life - lowest_force_life) / 10.0),
        }
        if len(getattr(player, "base", []) or []) >= 8:
            features["target_force_life_exchange_search_near_cast"] = 1.0
        return features

    def _blocker_attack_targets_player(self, engine: Any) -> bool:
        context = getattr(engine, "_blocker_selection_context", None)
        if not isinstance(context, dict):
            return True
        target = context.get("target")
        return getattr(target, "kind", None) is AttackTargetKind.PLAYER

    def _block_none_allows_turn_lethal_player_damage(self, engine: Any, player: Any, attacker: Any) -> bool:
        if not self._blocker_attack_targets_player(engine):
            return False
        life = float(getattr(player, "life", 0) or 0)
        if life <= 0.0:
            return False
        attacker_dp = max(0.0, self._effective_dp(engine, attacker))
        if attacker_dp >= life:
            return False
        remaining_pressure = self._remaining_ready_enemy_dp_pressure(engine, player, exclude=attacker)
        return attacker_dp + remaining_pressure >= life and remaining_pressure < life

    def _blocker_prevents_turn_lethal_player_damage(self, engine: Any, player: Any, attacker: Any) -> bool:
        return self._block_none_allows_turn_lethal_player_damage(engine, player, attacker)

    def _blocker_context_features(
            self,
            engine: Any,
            player: Any,
            attacker: Any,
            *,
            blocker: Any | None,
    ) -> dict[str, float]:
        context = getattr(engine, "_blocker_selection_context", None)
        if not isinstance(context, dict):
            return {}
        target = context.get("target")
        target_kind = getattr(target, "kind", None)
        if target_kind is not AttackTargetKind.FORCE:
            return {}
        force_instance = getattr(target, "ref", target)
        if getattr(force_instance, "owner", None) is not player:
            return {}
        if not self._has_force_life_exchange_plan(player):
            return {}
        target_life = float(getattr(force_instance, "life", 0) or 0)
        if target_life <= 0.0:
            return {}
        opponent = self._opponent(engine, player)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        attacker_dp = self._effective_dp(engine, attacker)
        after_damage_life = target_life - attacker_dp
        if attacker_dp > 0.0 and after_damage_life > 0.0 and after_damage_life < enemy_life:
            features = {
                "block_context_force_life_exchange_resource_target": 1.0,
                "block_context_force_life_exchange_setup_damage": 1.0,
                "block_context_force_life_exchange_after_damage_delta": _clamp01(
                    (enemy_life - after_damage_life) / 10.0
                ),
            }
            if blocker is None:
                features["block_none_lowers_force_life_exchange_resource"] = 1.0
            else:
                features["blocker_prevents_force_life_exchange_setup_damage"] = 1.0
            return features
        if target_life >= enemy_life:
            return {}
        if attacker_dp < target_life:
            return {}
        features = {
            "block_context_force_life_exchange_resource_target": 1.0,
            "block_context_force_life_exchange_target_would_break": 1.0,
        }
        if blocker is None:
            features["block_none_loses_force_life_exchange_resource"] = 1.0
        else:
            features["blocker_preserves_force_life_exchange_resource"] = 1.0
        return features

    def _has_force_life_exchange_in_hand(self, player: Any) -> bool:
        return any(
            self._has_effect_template(getattr(item, "card", item), "exchange_player_force_life")
            for item in getattr(player, "hand", []) or []
        )

    def _has_force_life_exchange_in_deck(self, player: Any) -> bool:
        return any(
            self._has_effect_template(getattr(item, "card", item), "exchange_player_force_life")
            for item in getattr(player, "deck", []) or []
        )

    def _has_force_life_exchange_plan(self, player: Any) -> bool:
        return self._has_force_life_exchange_in_hand(player) or self._has_force_life_exchange_in_deck(player)

    def _lowest_own_force_life(self, player: Any) -> float | None:
        lives = [
            float(getattr(force_instance, "life", 0) or 0)
            for force_instance in getattr(player, "forces", []) or []
            if not getattr(force_instance, "destroyed", False) and float(getattr(force_instance, "life", 0) or 0) > 0
        ]
        return min(lives) if lives else None

    def _ready_field_dp_total(self, engine: Any, player: Any) -> float:
        total = 0.0
        for candidate in getattr(player, "field", []) or []:
            if getattr(candidate, "rested", False):
                continue
            total += max(0.0, self._effective_dp(engine, candidate))
        return total

    def _field_minion_can_block(self, engine: Any, instance: Any) -> bool:
        if getattr(instance, "rested", False):
            return False
        card = getattr(instance, "card", instance)
        if getattr(card, "type", None) not in {CardType.F_MINION, CardType.B_MINION}:
            return False
        keywords = set(getattr(instance, "keywords", []) or []) | set(getattr(card, "keywords", []) or [])
        if Keyword.CANNOT_BLOCK in keywords:
            return False
        return self._effective_bp(engine, instance) > 0.0

    def _ready_field_blocker_count(self, engine: Any, player: Any, *, exclude: Any | None = None) -> int:
        return sum(
            1
            for candidate in getattr(player, "field", []) or []
            if candidate is not exclude and self._field_minion_can_block(engine, candidate)
        )

    def _field_to_base_removes_last_blocker_under_pressure(self, engine: Any, player: Any, instance: Any) -> bool:
        if self._enemy_field_dp_pressure(engine, player) <= 0.0:
            return False
        if not self._field_minion_can_block(engine, instance):
            return False
        return self._ready_field_blocker_count(engine, player, exclude=instance) <= 0

    def _remaining_ready_enemy_dp_pressure(self, engine: Any, player: Any, *, exclude: Any | None = None) -> float:
        opponent = self._opponent(engine, player)
        total = 0.0
        for candidate in getattr(opponent, "field", []) or []:
            if candidate is exclude:
                continue
            if getattr(candidate, "rested", False):
                continue
            total += max(0.0, self._effective_dp(engine, candidate))
        return total

    def _attack_action_features(self, engine: Any, player: Any, attacker: Any) -> dict[str, float]:
        features = {
            "attack_has_player_target": 0.0,
            "attack_has_lethal_player_target": 0.0,
            "attack_can_destroy_force": 0.0,
        }
        attacker_dp = self._effective_dp(engine, attacker)
        features["attack_attacker_dp"] = _clamp01(attacker_dp / 5.0)
        if attacker_dp <= 0:
            features["attack_zero_dp"] = 1.0
            if not self._card_has_attack_payoff(getattr(attacker, "card", attacker)):
                features["attack_zero_dp_without_attack_payoff"] = 1.0
        if self._has_active_force(player, "force_rin"):
            features["attack_with_turn_end_minion_refresh"] = 1.0
        card = getattr(attacker, "card", attacker)
        keywords = set(getattr(attacker, "keywords", []) or []) | set(getattr(card, "keywords", []) or [])
        if Keyword.REAWAKEN in keywords:
            features["attack_with_reawaken_self_refresh"] = 1.0
            features["attack_with_turn_end_minion_refresh"] = 1.0
        try:
            targets = list(engine.legal_attack_targets(attacker))
        except Exception:
            return features
        for target in targets:
            target_kind = getattr(target, "kind", None)
            ref = getattr(target, "ref", target)
            if target_kind is AttackTargetKind.PLAYER:
                features["attack_has_player_target"] = 1.0
                target_life = float(getattr(ref, "life", 0))
                damage_reduction = 1.0 if self._has_active_force(ref, "force_kai") else 0.0
                effective_damage = max(0.0, attacker_dp - damage_reduction)
                features["attack_player_effective_dp_damage"] = _clamp01(effective_damage / 5.0)
                if damage_reduction > 0.0:
                    features["attack_player_damage_reduced_by_force_kai"] = 1.0
                if attacker_dp > 0.0 and effective_damage <= 0.0:
                    features["attack_player_damage_prevented_by_force_kai"] = 1.0
                if target_life > 0 and effective_damage > 0.0:
                    features["positive_face_damage"] = 1.0
                if target_life > 0 and effective_damage >= target_life:
                    features["attack_has_lethal_player_target"] = 1.0
                if self._has_low_enemy_life_attack_pressure(engine, player, target_life):
                    features["attack_low_enemy_life_pressure"] = 1.0
            elif target_kind is AttackTargetKind.FORCE:
                target_life = float(getattr(ref, "life", 0))
                if target_life > 0 and attacker_dp >= target_life:
                    features["attack_can_destroy_force"] = 1.0
        features.update(self._attack_blocker_risk_features(engine, player, attacker, attacker_dp, features))
        if not _attack_has_defense_exempt_payoff(features) and not _attack_refreshes_defense_after_attack(features):
            if self._field_to_base_removes_last_blocker_under_pressure(engine, player, attacker):
                features["attack_removes_last_blocker_under_enemy_pressure"] = 1.0
            if self._field_to_base_protects_high_value_attacker(engine, player, attacker):
                features["attack_spends_high_value_blocker_under_enemy_pressure"] = 1.0
        if (
            _safe_len(getattr(player, "base", [])) < self._target_base_count(engine, player)
            and not features["attack_has_lethal_player_target"]
            and not _attack_has_reliable_force_break(features)
        ):
            features["attack_nonlethal_with_low_base"] = 1.0
        own_life = float(getattr(player, "life", 0) or 0)
        own_forces_alive = self._forces_alive(player)
        if own_life > 0 and own_forces_alive <= 0 and not features["attack_has_lethal_player_target"]:
            if self._enemy_field_dp_pressure(engine, player) > 0.0:
                features["attack_without_forces_under_enemy_pressure"] = 1.0
            if own_life <= 3:
                features["attack_while_low_life_no_forces"] = 1.0
            if self._enemy_field_dp_pressure(engine, player) >= own_life:
                features["attack_exposes_lethal_next_turn"] = 1.0
        if self._attack_spends_force_life_exchange_combo_wall(engine, player, attacker, attacker_dp, features):
            features["attack_spends_force_life_exchange_combo_wall"] = 1.0
        return features

    def _attack_spends_force_life_exchange_combo_wall(
            self,
            engine: Any,
            player: Any,
            attacker: Any,
            attacker_dp: float,
            attack_features: dict[str, float],
    ) -> bool:
        if float(attack_features.get("attack_has_lethal_player_target", 0.0)) > 0.0:
            return False
        if not self._has_force_life_exchange_plan(player):
            return False
        opponent = self._opponent(engine, player)
        lowest_force_life = self._lowest_own_force_life(player)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        if lowest_force_life is None or not (0.0 < lowest_force_life < enemy_life):
            return False
        return self._enemy_field_dp_pressure(engine, player) > 0.0

    def _attack_blocker_risk_features(
        self,
        engine: Any,
        player: Any,
        attacker: Any,
        attacker_dp: float,
        attack_features: dict[str, float],
    ) -> dict[str, float]:
        try:
            blockers = list(engine.legal_blockers(attacker))
        except Exception:
            blockers = []
        fallback_blockers = [
            candidate
            for candidate in getattr(self._opponent(engine, player), "field", []) or []
            if self._field_minion_can_block(engine, candidate)
        ]
        if not blockers:
            blockers = fallback_blockers
        attacker_bp = self._effective_bp(engine, attacker)
        larger_blockers = [
            blocker
            for blocker in blockers
            if self._effective_bp(engine, blocker) > attacker_bp
        ]
        if not larger_blockers and fallback_blockers:
            larger_blockers = [
                blocker
                for blocker in fallback_blockers
                if self._effective_bp(engine, blocker) > attacker_bp
            ]
            if larger_blockers:
                blockers = fallback_blockers
        contesting_blockers = list(larger_blockers)
        if not contesting_blockers:
            contesting_blockers = [
                blocker
                for blocker in blockers
                if self._effective_bp(engine, blocker) >= attacker_bp
            ]
        if not contesting_blockers and fallback_blockers:
            contesting_blockers = [
                blocker
                for blocker in fallback_blockers
                if self._effective_bp(engine, blocker) >= attacker_bp
            ]
            if contesting_blockers:
                blockers = fallback_blockers
        if not contesting_blockers:
            return {}
        features: dict[str, float] = {}
        if larger_blockers:
            features["attack_larger_ready_blocker_count"] = _clamp01(len(larger_blockers) / 6.0)
        else:
            features["attack_equal_ready_blocker_count"] = _clamp01(len(contesting_blockers) / 6.0)
        best_bp = max(self._effective_bp(engine, blocker) for blocker in contesting_blockers)
        features["attack_larger_blocker_bp_gap"] = _clamp01(max(0.0, best_bp - attacker_bp) / 2000.0)
        has_attack_payoff = self._card_has_attack_payoff(getattr(attacker, "card", attacker))
        force_break_unreliable = (
            float(attack_features.get("attack_can_destroy_force", 0.0)) > 0.0
            and float(attack_features.get("attack_has_lethal_player_target", 0.0)) <= 0.0
            and float(attack_features.get("attack_low_enemy_life_pressure", 0.0)) <= 0.0
            and not has_attack_payoff
            and not self._has_keyword(attacker, Keyword.PENETRATE)
            and (
                self._enemy_pressure_high_player_risk(engine, player)
                or (
                    float(getattr(player, "life", 0) or 0) > 0.0
                    and self._enemy_field_dp_pressure(engine, player) >= float(getattr(player, "life", 0) or 0)
                )
            )
        )
        if force_break_unreliable:
            features["attack_force_break_unreliable_under_enemy_pressure"] = 1.0
        immediate_payoff = (
            float(attack_features.get("attack_has_lethal_player_target", 0.0)) > 0.0
            or (
                float(attack_features.get("attack_can_destroy_force", 0.0)) > 0.0
                and not force_break_unreliable
            )
            or float(attack_features.get("attack_low_enemy_life_pressure", 0.0)) > 0.0
            or has_attack_payoff
            or self._has_keyword(attacker, Keyword.PENETRATE)
        )
        if attacker_dp <= 1.0 and not immediate_payoff:
            features["attack_low_dp_into_larger_blocker"] = 1.0
        pressure = self._multi_attacker_pressure_outnumbers_blockers(engine, player, blockers)
        if pressure:
            features["attack_multi_attacker_pressure_outnumbers_blockers"] = 1.0
        if (
            not immediate_payoff
            and not pressure
        ):
            features["attack_loses_to_larger_blocker_without_pressure"] = 1.0
            features["attack_suicide_into_larger_blocker_without_pressure"] = 1.0
        return features

    def _has_low_enemy_life_attack_pressure(self, engine: Any, player: Any, target_life: float) -> bool:
        if not (0.0 < target_life <= 3.0):
            return False
        return self._ready_field_dp_total(engine, player) >= target_life

    def _find_instance(self, player: Any, iid: int) -> Any | None:
        for zone_name in ("hand", "base", "field", "trash"):
            for instance in getattr(player, zone_name, []):
                if getattr(instance, "iid", None) == iid:
                    return instance
        return None

    def _has_effect_text(self, card: Any) -> bool:
        return bool(
            getattr(card, "effects", None)
            or getattr(card, "triggers", None)
            or getattr(card, "keywords", None)
            or getattr(card, "aura", None)
            or getattr(card, "ability_jp", "")
            or getattr(card, "ability_en", "")
        )

    def _effect_template_ids(self, card: Any) -> list[str]:
        ids: list[str] = []
        for effect in getattr(card, "effects", []) or []:
            template_id = str(getattr(effect, "template_id", "") or "")
            if template_id:
                ids.append(template_id)
        return ids

    def _has_effect_template(self, card: Any, template_id: str) -> bool:
        return str(template_id) in self._effect_template_ids(card)

    def _has_effect_template_timing(
        self,
        card: Any,
        template_id: str,
        timings: set[EffectTiming],
    ) -> bool:
        for effect in getattr(card, "effects", []) or []:
            if str(getattr(effect, "template_id", "") or "") != str(template_id):
                continue
            if getattr(effect, "timing", None) in timings:
                return True
        return False

    def _card_can_help_find_force_life_exchange_piece(self, card: Any) -> bool:
        for effect in getattr(card, "effects", []) or []:
            template_id = str(getattr(effect, "template_id", "") or "")
            target_kind = str(getattr(effect, "target_kind", "") or "")
            if template_id in {"draw_cards", "look_top_to_hand"}:
                return True
            if target_kind.startswith("top") or target_kind.startswith("deck_"):
                return True
        return False

    def _card_can_help_develop_base(self, card: Any) -> bool:
        return self._card_can_search_base_minion(card) or self._card_can_place_base_from_hand(card)

    def _card_can_search_base_minion(self, card: Any) -> bool:
        for effect in getattr(card, "effects", []) or []:
            template_id = str(getattr(effect, "template_id", "") or "")
            target_kind = str(getattr(effect, "target_kind", "") or "")
            if template_id == "search_deck_to_hand" and "base_minion" in target_kind:
                return True
        return False

    def _card_can_place_base_from_hand(self, card: Any) -> bool:
        return self._has_effect_template(card, "place_base_from_hand")

    def _card_has_attack_payoff(self, card: Any) -> bool:
        for effect in getattr(card, "effects", []) or []:
            if getattr(effect, "timing", None) in {EffectTiming.ON_ATTACK, EffectTiming.ON_BATTLE_WIN}:
                return True
        for trigger in getattr(card, "triggers", []) or []:
            if getattr(trigger, "when", None) is TriggerTiming.ON_ATTACK:
                return True
        return False

    def _has_keyword(self, instance: Any, keyword: Keyword) -> bool:
        keywords = getattr(instance, "keywords", None)
        if keywords is None:
            keywords = getattr(getattr(instance, "card", None), "keywords", [])
        try:
            return keyword in keywords
        except TypeError:
            return False

    def _multi_attacker_pressure_outnumbers_blockers(self, engine: Any, player: Any, blockers: list[Any]) -> bool:
        blocker_count = len(blockers)
        attack_count = 0
        attack_dp_total = 0.0
        for candidate in getattr(player, "field", []) or []:
            if getattr(candidate, "rested", False):
                continue
            try:
                if not list(engine.legal_attack_targets(candidate)):
                    continue
            except Exception:
                continue
            attack_count += 1
            attack_dp_total += self._effective_dp(engine, candidate)
        if attack_count <= blocker_count:
            return False
        opponent = self._opponent(engine, player)
        target_life_values = [
            float(getattr(force, "life", 0) or 0)
            for force in getattr(opponent, "forces", []) or []
            if not getattr(force, "destroyed", False) and float(getattr(force, "life", 0) or 0) > 0
        ]
        player_life = float(getattr(opponent, "life", 0) or 0)
        if player_life > 0:
            target_life_values.append(player_life)
        pressure_threshold = min(target_life_values, default=3.0)
        return attack_dp_total >= max(2.0, pressure_threshold)

    def _targeted_effect_action_features(
            self,
            engine: Any,
            player: Any,
            card: Any,
            *,
            source: Any | None = None,
    ) -> dict[str, float]:
        features: dict[str, float] = {}
        for effect in self._relevant_target_effects(card):
            target_kind = str(getattr(effect, "target_kind", "") or "")
            if not self._can_count_effect_target_sides(target_kind):
                continue
            own_count, enemy_count = self._effect_target_side_counts(engine, player, target_kind, effect, source=source)
            total_count = own_count + enemy_count
            features["play_card_target_effect"] = 1.0
            features[_feature_key("play_card_target_kind", target_kind)] = 1.0
            if total_count == 0:
                features["play_card_target_effect_no_eligible_targets"] = 1.0
            if self._effect_is_harmful(effect):
                features["play_card_harmful_target_effect"] = 1.0
                features[_feature_key("play_card_harmful_target_kind", target_kind)] = 1.0
                if enemy_count > 0:
                    features["play_card_harmful_enemy_target_available"] = 1.0
                    features["play_card_beneficial_remove_threat"] = 1.0
                    template_id = str(getattr(effect, "template_id", "") or "")
                    if template_id == "destroy_targets" and "minion" in target_kind:
                        features["positive_kill_enemy_minion"] = 1.0
                else:
                    features["play_card_harmful_no_enemy_target"] = 1.0
                if target_kind in MIXED_TARGET_KINDS and own_count > 0 and enemy_count == 0:
                    features["play_card_harmful_target_only_own"] = 1.0
            if self._effect_is_beneficial(effect):
                features["play_card_beneficial_target_effect"] = 1.0
                features[_feature_key("play_card_beneficial_target_kind", target_kind)] = 1.0
                if own_count > 0:
                    features["play_card_beneficial_own_target_available"] = 1.0
                else:
                    features["play_card_beneficial_no_own_target"] = 1.0
                if target_kind in MIXED_TARGET_KINDS and enemy_count > 0 and own_count == 0:
                    features["play_card_beneficial_only_enemy_target"] = 1.0
        return features

    def _defensive_reactive_action_features(self, engine: Any, player: Any, card: Any) -> dict[str, float]:
        features: dict[str, float] = {}
        for effect in getattr(card, "effects", []) or []:
            timing = getattr(effect, "timing", None)
            if timing not in {EffectTiming.ON_CAST_MAGIC, EffectTiming.FLASH_ACTIVATED}:
                continue
            if (
                getattr(getattr(engine, "state", None), "active", None) is player
                and self._effect_is_own_turn_rest_lockdown(effect)
            ):
                lockable_targets = self._enemy_rest_lock_target_count(
                    engine,
                    player,
                    str(getattr(effect, "target_kind", "") or ""),
                    effect,
                    source=card,
                )
                ready_targets = self._enemy_ready_minion_target_count(
                    engine,
                    player,
                    str(getattr(effect, "target_kind", "") or ""),
                    effect,
                    source=card,
                )
                if lockable_targets > 0:
                    features["play_card_rest_lockdown_on_own_turn"] = 1.0
                    features["play_card_rest_lockdown_enemy_lockable_targets"] = _clamp01(lockable_targets / 3.0)
                    features["play_card_rest_lockdown_enemy_ready_targets"] = _clamp01(ready_targets / 3.0)
                continue
            if not self._effect_is_defensive_reactive(effect):
                continue
            features["play_card_defensive_reactive_effect"] = 1.0
            if getattr(getattr(engine, "state", None), "active", None) is player:
                if self._defensive_reactive_has_own_turn_attack_payoff(engine, player, effect):
                    features["play_card_defensive_reactive_attack_payoff"] = 1.0
                else:
                    features["play_card_defensive_reactive_on_own_turn"] = 1.0
            else:
                features["play_card_defensive_reactive_on_enemy_turn"] = 1.0
        return features

    def _generic_target_context_features(self, engine: Any, player: Any, kind: str, target: Any) -> dict[str, float]:
        features: dict[str, float] = {}
        owner = getattr(target, "owner", None)
        opponent = self._opponent(engine, player)
        features["target_own"] = 1.0 if owner is player else 0.0
        features["target_enemy"] = 1.0 if owner is opponent else 0.0
        if hasattr(target, "rested"):
            rested = bool(getattr(target, "rested", False))
            features["target_rested"] = 1.0 if rested else 0.0
            features["target_ready"] = 0.0 if rested else 1.0
        card = getattr(target, "card", None)
        if card is not None:
            features["target_is_minion"] = 1.0 if getattr(card, "type", None) in {CardType.F_MINION, CardType.B_MINION} else 0.0
            features["target_is_magic"] = 1.0 if getattr(card, "type", None) is CardType.MAGIC else 0.0
            features["target_cost"] = _clamp01(_card_cost(card) / 10.0)
            card_id = getattr(card, "id", None)
            if card_id:
                features[_feature_key("target_id", str(card_id))] = 1.0
            for template_id in self._effect_template_ids(card):
                features[_feature_key("target_card_effect", template_id)] = 1.0
            features.update(self._card_profile_features("target", card))
            if self._card_has_on_destroy_effect(card):
                features["target_has_on_destroy_effect"] = 1.0
                target_owner = owner if owner is not None else player
                if self._card_on_destroy_payoff_available(engine, target_owner, card):
                    features["target_on_destroy_payoff_available"] = 1.0
            if owner is player and self._own_trash_recursion_can_reuse_card(player, card):
                features["target_own_revival_candidate"] = 1.0
            if getattr(card, "type", None) is CardType.B_MINION:
                features["target_base_minion"] = 1.0
                mana_color = getattr(card, "mana_color", None)
                color_key = self._color_count_key(mana_color)
                if color_key != self._color_count_key(Color.COLORLESS):
                    features[_feature_key("target_mana_color", color_key)] = 1.0
                    if self._hand_color_demand(player).get(color_key, 0.0) > 0.0:
                        features["target_matches_hand_color"] = 1.0
                        if self._ready_mana_color_counts(engine, player).get(color_key, 0) <= 0:
                            features["target_restores_missing_hand_color"] = 1.0
            features.update(self._force_life_exchange_search_target_features(engine, player, kind, target))
            if kind == "ally_base" and hasattr(target, "area"):
                features.update(self._base_replacement_features(engine, player, target, prefix="target_base"))
        elif hasattr(target, "force"):
            features["target_is_force"] = 1.0
        effect = self._target_effect_from_context(engine, kind)
        if effect is not None:
            template_id = str(getattr(effect, "template_id", "") or "")
            if template_id:
                features[_feature_key("target_effect", template_id)] = 1.0
            features["target_effect_harmful"] = 1.0 if self._effect_is_harmful(effect) else 0.0
            features["target_effect_beneficial"] = 1.0 if self._effect_is_beneficial(effect) else 0.0
            features["target_effect_defensive_reactive"] = 1.0 if self._effect_is_defensive_reactive(effect) else 0.0
            features.update(self._search_to_hand_target_value_features(effect, target))
            features.update(self._semantic_target_choice_features(engine, effect, features))
            if template_id == "exchange_player_force_life":
                features.update(self._force_life_exchange_target_features(engine, player, target))
            if (
                template_id == "destroy_targets"
                and float(features.get("target_own", 0.0)) > 0.0
                and (
                    float(features.get("target_on_destroy_payoff_available", 0.0)) > 0.0
                    or float(features.get("target_own_revival_candidate", 0.0)) > 0.0
                )
            ):
                features["positive_self_destroy_death_payoff"] = 1.0
        if (
            float(features.get("target_search_to_hand", 0.0)) <= 0.0
            and kind in {"top_field_minion", "top2_field_minion", "top3_field_minion"}
        ):
            features.update(self._search_target_value_features(target))
        return features

    def _trash_recursion_action_features(
            self,
            engine: Any,
            player: Any,
            card: Any,
            *,
            prefix: str,
    ) -> dict[str, float]:
        features: dict[str, float] = {}
        for effect in getattr(card, "effects", []) or []:
            if str(getattr(effect, "template_id", "") or "") != "summon_from_trash":
                continue
            features[f"{prefix}_summon_from_trash"] = 1.0
            target_count = self._trash_recursion_target_count(player, effect)
            features[f"{prefix}_summon_from_trash_own_target_count"] = _clamp01(target_count / 4.0)
            if target_count > 0:
                features[f"{prefix}_summon_from_trash_own_target_available"] = 1.0
                features["positive_reanimate_from_trash"] = 1.0
            else:
                features[f"{prefix}_summon_from_trash_no_own_target"] = 1.0
        return features

    def _trash_recursion_target_count(self, player: Any, effect: Any) -> int:
        target_kind = str(getattr(effect, "target_kind", "") or "")
        if target_kind != "trash_field_minion":
            return 0
        return sum(
            1
            for candidate in getattr(player, "trash", []) or []
            if self._trash_recursion_effect_can_reuse_card(effect, getattr(candidate, "card", candidate))
        )

    def _own_trash_recursion_can_reuse_card(self, player: Any, card: Any) -> bool:
        for zone_name in ("hand", "field", "base"):
            for candidate in getattr(player, zone_name, []) or []:
                candidate_card = getattr(candidate, "card", candidate)
                for effect in getattr(candidate_card, "effects", []) or []:
                    if self._trash_recursion_effect_can_reuse_card(effect, card):
                        return True
        return False

    def _trash_recursion_effect_can_reuse_card(self, effect: Any, card: Any) -> bool:
        if str(getattr(effect, "template_id", "") or "") != "summon_from_trash":
            return False
        if str(getattr(effect, "target_kind", "") or "") != "trash_field_minion":
            return False
        if getattr(card, "type", None) is not CardType.F_MINION:
            return False
        params = dict(getattr(effect, "params", {}) or {})
        max_cost = params.get("max_cost")
        if max_cost is not None and _card_cost(card) > int(max_cost):
            return False
        exclude_card_id = str(params.get("exclude_card_id") or "")
        if exclude_card_id and str(getattr(card, "id", "") or "") == exclude_card_id:
            return False
        color = params.get("color")
        if color is not None and self._color_label(getattr(card, "mana_color", None)).upper() != str(color).upper():
            return False
        return True

    def _card_has_on_destroy_effect(self, card: Any) -> bool:
        for effect in getattr(card, "effects", []) or []:
            timing = getattr(effect, "timing", None)
            if str(getattr(timing, "value", timing) or "") == "on_destroy":
                return True
        return False

    def _card_on_destroy_payoff_available(self, engine: Any, player: Any, card: Any) -> bool:
        for effect in getattr(card, "effects", []) or []:
            timing = getattr(effect, "timing", None)
            if str(getattr(timing, "value", timing) or "") != "on_destroy":
                continue
            if self._on_destroy_effect_has_payoff(engine, player, effect):
                return True
        return False

    def _on_destroy_effect_has_payoff(self, engine: Any, player: Any, effect: Any) -> bool:
        template_id = str(getattr(effect, "template_id", "") or "")
        if template_id in {"draw_cards", "draw_until_hand_size"}:
            return bool(getattr(player, "deck", []) or [])
        if template_id in {"create_tokens", "place_colorless_mana", "refresh_self"}:
            return True
        if template_id in {
            "destroy_targets",
            "move_to_base_targets",
            "return_to_hand",
            "rest_targets",
            "force_block",
        }:
            return self._effect_has_enemy_target(engine, player, effect)
        if template_id == "damage_targets":
            opponent = self._opponent(engine, player)
            target_kind = str(getattr(effect, "target_kind", "") or "")
            if "force" in target_kind:
                return any(not getattr(force, "destroyed", False) for force in getattr(opponent, "forces", []) or [])
            return float(getattr(opponent, "life", 0) or 0) > 0.0
        if template_id == "summon_from_trash":
            return self._trash_recursion_target_count(player, effect) > 0
        if template_id == "return_from_trash_to_hand":
            return self._trash_return_target_count(player, effect) > 0
        if template_id in {"search_deck_to_hand", "look_top_to_hand", "place_base_from_deck"}:
            return self._deck_effect_target_count(player, effect) > 0
        return False

    def _effect_has_enemy_target(self, engine: Any, player: Any, effect: Any) -> bool:
        opponent = self._opponent(engine, player)
        target_kind = str(getattr(effect, "target_kind", "") or "")
        if target_kind in {"enemy_force", "enemy_minion_or_force", "any_minion_or_force"}:
            if any(not getattr(force, "destroyed", False) for force in getattr(opponent, "forces", []) or []):
                return True
        if target_kind not in {
            "enemy_minion",
            "enemy_minion_cost_at_most_4",
            "enemy_minion_cost_at_least_6",
            "enemy_minion_or_force",
            "any_minion",
            "any_minion_or_force",
        }:
            return False
        implicit_max = 4 if target_kind == "enemy_minion_cost_at_most_4" else None
        implicit_min = 6 if target_kind == "enemy_minion_cost_at_least_6" else None
        return any(
            self._effect_card_matches_filter(
                effect,
                getattr(candidate, "card", candidate),
                implicit_max_cost=implicit_max,
                implicit_min_cost=implicit_min,
                allowed_types={CardType.F_MINION, CardType.B_MINION},
            )
            for candidate in getattr(opponent, "field", []) or []
        )

    def _trash_return_target_count(self, player: Any, effect: Any) -> int:
        target_kind = str(getattr(effect, "target_kind", "") or "")
        implicit_max = 4 if target_kind == "trash_magic_cost_at_most_4" else None
        allowed_types = {CardType.MAGIC} if "magic" in target_kind else {CardType.F_MINION, CardType.B_MINION, CardType.MAGIC}
        return sum(
            1
            for candidate in getattr(player, "trash", []) or []
            if self._effect_card_matches_filter(
                effect,
                getattr(candidate, "card", candidate),
                implicit_max_cost=implicit_max,
                allowed_types=allowed_types,
            )
        )

    def _deck_effect_target_count(self, player: Any, effect: Any) -> int:
        target_kind = str(getattr(effect, "target_kind", "") or "")
        deck = list(getattr(player, "deck", []) or [])
        if target_kind == "top_field_minion":
            deck = deck[:4]
        elif target_kind == "top2_field_minion":
            deck = deck[:2]
        elif target_kind == "top3_field_minion":
            deck = deck[:3]
        if target_kind == "deck_base_minion":
            allowed_types = {CardType.B_MINION}
        elif target_kind in {"deck_minion", "deck_base_or_field_minion", "top_field_minion", "top2_field_minion", "top3_field_minion"}:
            allowed_types = {CardType.F_MINION, CardType.B_MINION}
        else:
            allowed_types = {CardType.F_MINION, CardType.B_MINION, CardType.MAGIC}
        return sum(
            1
            for candidate in deck
            if self._effect_card_matches_filter(
                effect,
                getattr(candidate, "card", candidate),
                allowed_types=allowed_types,
            )
        )

    def _effect_card_matches_filter(
        self,
        effect: Any,
        card: Any,
        *,
        implicit_max_cost: int | None = None,
        implicit_min_cost: int | None = None,
        allowed_types: set[CardType] | None = None,
    ) -> bool:
        if card is None:
            return False
        if allowed_types is not None and getattr(card, "type", None) not in allowed_types:
            return False
        params = dict(getattr(effect, "params", {}) or {})
        max_cost = params.get("max_cost", implicit_max_cost)
        if max_cost is not None and _card_cost(card) > int(max_cost):
            return False
        min_cost = params.get("min_cost", implicit_min_cost)
        if min_cost is not None and _card_cost(card) < int(min_cost):
            return False
        exclude_card_id = str(params.get("exclude_card_id") or "")
        if exclude_card_id and str(getattr(card, "id", "") or "") == exclude_card_id:
            return False
        color = params.get("color")
        if color is not None and self._color_label(getattr(card, "mana_color", None)).upper() != str(color).upper():
            return False
        return True

    def _search_to_hand_target_value_features(self, effect: Any, target: Any) -> dict[str, float]:
        template_id = str(getattr(effect, "template_id", "") or "")
        if template_id not in {"look_top_to_hand", "search_deck_to_hand"}:
            return {}
        return self._search_target_value_features(target)

    def _search_target_value_features(self, target: Any) -> dict[str, float]:
        card = getattr(target, "card", target)
        if card is None:
            return {}
        bp = float(getattr(target, "bp", getattr(card, "bp", 0)) or 0)
        dp = float(getattr(target, "dp", getattr(card, "dp", 0)) or 0)
        cost = float(_card_cost(card))
        search_value = min(1.0, max(0.0, cost / 10.0 + bp / 4000.0 + dp / 10.0))
        features = {
            "target_search_to_hand": 1.0,
            "target_search_value": search_value,
        }
        if dp >= 2:
            features["target_search_high_dp"] = 1.0
        if bp >= 600:
            features["target_search_high_bp"] = 1.0
        if self._has_effect_template(card, "exchange_player_force_life"):
            features["target_search_combo_piece"] = 1.0
        return features

    def _semantic_target_choice_features(
            self,
            engine: Any,
            effect: Any,
            target_features: dict[str, float],
    ) -> dict[str, float]:
        harmful = self._effect_is_harmful(effect)
        beneficial = self._effect_is_beneficial(effect)
        profile = self._target_source_card_profile(engine)
        if profile is not None:
            harmful = harmful or bool(getattr(profile.target_semantics, "harmful", False))
            beneficial = beneficial or bool(getattr(profile.target_semantics, "beneficial", False))
        is_enemy = float(target_features.get("target_enemy", 0.0)) > 0.0
        is_own = float(target_features.get("target_own", 0.0)) > 0.0
        is_ready = float(target_features.get("target_ready", 0.0)) > 0.0
        features: dict[str, float] = {}
        if harmful:
            features[_feature_key("semantic_target_intent", "harmful")] = 1.0
            if is_enemy:
                features[_feature_key("semantic_target_alignment", "harmful_enemy")] = 1.0
                if is_ready:
                    features[_feature_key("semantic_target_priority", "ready_enemy_threat")] = 1.0
            if is_own:
                features[_feature_key("semantic_target_risk", "harmful_own")] = 1.0
        if beneficial:
            features[_feature_key("semantic_target_intent", "beneficial")] = 1.0
            if is_own:
                features[_feature_key("semantic_target_alignment", "beneficial_own")] = 1.0
            if is_enemy:
                features[_feature_key("semantic_target_risk", "beneficial_enemy")] = 1.0
        return features

    def _target_source_card_profile(self, engine: Any) -> Any | None:
        context = getattr(engine, "_target_selection_context", None)
        if not isinstance(context, dict):
            return None
        source = context.get("source")
        source_card = getattr(source, "card", source)
        if source_card is None:
            return None
        try:
            from zz.card_profiles import build_card_profile

            return build_card_profile(source_card)
        except Exception:
            return None

    def _target_effect_from_context(self, engine: Any, kind: str) -> Any | None:
        context = getattr(engine, "_target_selection_context", None)
        if not isinstance(context, dict):
            return None
        effect = context.get("effect")
        if effect is not None and getattr(effect, "target_kind", None) == kind:
            return effect
        source = context.get("source")
        source_card = getattr(source, "card", source)
        for candidate in self._relevant_target_effects(source_card):
            if getattr(candidate, "target_kind", None) == kind:
                return candidate
        return None

    def _relevant_target_effects(self, card: Any) -> list[Any]:
        effects = []
        for effect in getattr(card, "effects", []) or []:
            if not getattr(effect, "target_kind", None):
                continue
            timing = getattr(effect, "timing", None)
            if timing in {EffectTiming.ON_CAST_MAGIC, EffectTiming.ON_SUMMON, EffectTiming.ON_ATTACK, EffectTiming.FLASH_ACTIVATED}:
                effects.append(effect)
        return effects

    def _effect_is_harmful(self, effect: Any) -> bool:
        template_id = str(getattr(effect, "template_id", "") or "")
        params = getattr(effect, "params", {}) or {}
        if str(params.get("target_role") or "").strip().lower() == "harmful":
            return True
        if template_id in HARMFUL_TARGET_EFFECT_TEMPLATES:
            return True
        if template_id in {"stat_modifier", "stat_modifier_all"}:
            return float(params.get("bp_delta", 0) or 0) < 0 or float(params.get("dp_delta", 0) or 0) < 0
        return False

    def _effect_is_beneficial(self, effect: Any) -> bool:
        template_id = str(getattr(effect, "template_id", "") or "")
        params = getattr(effect, "params", {}) or {}
        if str(params.get("target_role") or "").strip().lower() == "beneficial":
            return True
        if template_id in BENEFICIAL_TARGET_EFFECT_TEMPLATES:
            return True
        if template_id in {"stat_modifier", "stat_modifier_all"}:
            return (
                float(params.get("bp_delta", 0) or 0) > 0
                or float(params.get("dp_delta", 0) or 0) > 0
                or bool(params.get("keyword"))
            )
        return False

    def _effect_is_defensive_reactive(self, effect: Any) -> bool:
        template_id = str(getattr(effect, "template_id", "") or "")
        params = getattr(effect, "params", {}) or {}
        if bool(params.get("defensive_reactive", False)):
            return True
        if str(params.get("target_role") or "").strip().lower() == "defensive":
            return True
        return template_id in DEFENSIVE_REACTIVE_EFFECT_TEMPLATES

    def _effect_is_own_turn_rest_lockdown(self, effect: Any) -> bool:
        return (
            str(getattr(effect, "template_id", "") or "") == "rest_targets"
            and bool((getattr(effect, "params", {}) or {}).get("lock_until_next_refresh_on_own_turn"))
        )

    def _enemy_ready_minion_target_count(
            self,
            engine: Any,
            player: Any,
            kind: str,
            effect: Any,
            *,
            source: Any | None = None,
    ) -> int:
        opponent = self._opponent(engine, player)
        _own_targets, enemy_targets = self._targets_by_side_for_kind(player, opponent, kind)
        count = 0
        for target in enemy_targets:
            card = getattr(target, "card", None)
            if card is None or getattr(card, "type", None) not in {CardType.F_MINION, CardType.B_MINION}:
                continue
            if getattr(target, "rested", False):
                continue
            if self._effect_target_filter_allows(engine, target, kind, effect, source=source):
                count += 1
        return count

    def _enemy_rest_lock_target_count(
            self,
            engine: Any,
            player: Any,
            kind: str,
            effect: Any,
            *,
            source: Any | None = None,
    ) -> int:
        opponent = self._opponent(engine, player)
        _own_targets, enemy_targets = self._targets_by_side_for_kind(player, opponent, kind)
        return sum(
            1
            for target in enemy_targets
            if self._effect_target_filter_allows(engine, target, kind, effect, source=source)
        )

    def _defensive_reactive_has_own_turn_attack_payoff(self, engine: Any, player: Any, effect: Any) -> bool:
        template_id = str(getattr(effect, "template_id", "") or "")
        params = getattr(effect, "params", {}) or {}
        bp_delta = float(params.get("bp_delta", 0) or 0)
        if template_id == "refresh_targets":
            return any(
                bool(getattr(candidate, "rested", False))
                and self._effective_dp(engine, candidate) > 0.0
                for candidate in getattr(player, "field", []) or []
            )
        if bp_delta <= 0.0:
            return False
        opponent = self._opponent(engine, player)
        enemy_field = list(getattr(opponent, "field", []) or [])
        if not enemy_field:
            return False
        for own_minion in getattr(player, "field", []) or []:
            if bool(getattr(own_minion, "rested", False)):
                continue
            if self._effective_dp(engine, own_minion) <= 0.0:
                continue
            own_bp = self._effective_bp(engine, own_minion)
            buffed_bp = own_bp + bp_delta
            for enemy_minion in enemy_field:
                enemy_bp = self._effective_bp(engine, enemy_minion)
                if own_bp < enemy_bp <= buffed_bp:
                    return True
        return False

    def _effect_min_targets(self, effect: Any) -> int:
        if bool(getattr(effect, "optional", False)):
            return 0
        return int(getattr(effect, "min_targets", 1) or 0)

    def _effect_target_side_counts(
            self,
            engine: Any,
            player: Any,
            kind: str,
            effect: Any,
            *,
            source: Any | None = None,
    ) -> tuple[int, int]:
        opponent = self._opponent(engine, player)
        own_targets, enemy_targets = self._targets_by_side_for_kind(player, opponent, kind)
        own_count = sum(1 for target in own_targets if self._effect_target_filter_allows(engine, target, kind, effect, source=source))
        enemy_count = sum(1 for target in enemy_targets if self._effect_target_filter_allows(engine, target, kind, effect, source=source))
        return own_count, enemy_count

    def _can_count_effect_target_sides(self, kind: str) -> bool:
        return (
            kind in MIXED_TARGET_KINDS
            or kind in {"ally_base", "ally_force", "enemy_force", "enemy_minion_or_force", "owner_forces"}
            or kind.startswith("ally_minion")
            or kind.startswith("enemy_minion")
            or kind == "other_ally_minion"
        )

    def _targets_by_side_for_kind(self, player: Any, opponent: Any, kind: str) -> tuple[list[Any], list[Any]]:
        if kind == "any_minion":
            return list(getattr(player, "field", []) or []), list(getattr(opponent, "field", []) or [])
        if kind == "any_minion_or_force":
            own_forces = [force for force in getattr(player, "forces", []) or [] if not getattr(force, "destroyed", False)]
            enemy_forces = [force for force in getattr(opponent, "forces", []) or [] if not getattr(force, "destroyed", False)]
            return list(getattr(player, "field", []) or []) + own_forces, list(getattr(opponent, "field", []) or []) + enemy_forces
        if kind == "ally_base":
            return list(getattr(player, "base", []) or []), []
        if kind in {"ally_force", "owner_forces"}:
            return [force for force in getattr(player, "forces", []) or [] if not getattr(force, "destroyed", False)], []
        if kind == "enemy_force":
            return [], [force for force in getattr(opponent, "forces", []) or [] if not getattr(force, "destroyed", False)]
        if kind == "enemy_minion_or_force":
            enemy_forces = [force for force in getattr(opponent, "forces", []) or [] if not getattr(force, "destroyed", False)]
            return [], list(getattr(opponent, "field", []) or []) + enemy_forces
        if kind.startswith("enemy_minion"):
            return [], list(getattr(opponent, "field", []) or [])
        if kind.startswith("ally_minion") or kind == "other_ally_minion":
            return list(getattr(player, "field", []) or []), []
        return [], []

    def _effect_target_filter_allows(
            self,
            engine: Any,
            target: Any,
            kind: str,
            effect: Any,
            *,
            source: Any | None = None,
    ) -> bool:
        card = getattr(target, "card", None)
        if card is None:
            return True
        if not self._effect_selection_allows(engine, source, target, effect):
            return False
        cost = _card_cost(card)
        if kind.endswith("_cost_at_most_3") and cost > 3:
            return False
        if kind.endswith("_cost_at_most_4") and cost > 4:
            return False
        if kind.endswith("_cost_at_least_6") and cost < 6:
            return False
        params = getattr(effect, "params", {}) or {}
        max_cost = params.get("max_cost")
        min_cost = params.get("min_cost")
        if max_cost is not None and cost > int(max_cost):
            return False
        if min_cost is not None and cost < int(min_cost):
            return False
        max_bp = params.get("max_bp")
        max_dp = params.get("max_dp")
        if max_bp is not None and self._effective_bp(engine, target) > float(max_bp):
            return False
        if max_dp is not None and self._effective_dp(engine, target) > float(max_dp):
            return False
        return True

    def _effect_selection_allows(self, engine: Any, source: Any | None, target: Any, effect: Any) -> bool:
        can_effect_select = getattr(engine, "_can_effect_select", None)
        if not callable(can_effect_select) or source is None:
            return True
        source_area = None
        if getattr(effect, "timing", None) is EffectTiming.ON_SUMMON:
            source_area = AreaType.FIELD
        try:
            if source_area is None:
                return bool(can_effect_select(source, target))
            return bool(can_effect_select(source, target, source_area=source_area))
        except TypeError:
            try:
                return bool(can_effect_select(source, target))
            except Exception:
                return True
        except Exception:
            return True

    def _target_stats(self, target: Any, *, attacker: Any | None = None) -> dict[str, float]:
        card = getattr(target, "card", None)
        target_bp = float(getattr(target, "bp", getattr(card, "bp", 0)))
        target_dp = float(getattr(target, "dp", getattr(card, "dp", 0)))
        target_life = float(getattr(target, "life", 0))
        attacker_bp = float(getattr(attacker, "bp", getattr(getattr(attacker, "card", None), "bp", 0))) if attacker is not None else 0.0
        return {
            "target_life": _clamp01(target_life / 10.0),
            "target_can_be_destroyed_by_attacker": 1.0 if attacker_bp and target_bp and attacker_bp >= target_bp else 0.0,
            "target_can_destroy_attacker": 1.0 if attacker_bp and target_bp and target_bp >= attacker_bp else 0.0,
            "target_bp": _clamp01(target_bp / 2000.0),
            "target_dp": _clamp01(target_dp / 5.0),
        }

    def _effective_bp(self, engine: Any, card_instance: Any) -> float:
        effective_bp = getattr(engine, "effective_bp", None)
        if callable(effective_bp):
            try:
                return float(effective_bp(card_instance))
            except Exception:
                pass
        return float(getattr(card_instance, "bp", getattr(getattr(card_instance, "card", None), "bp", 0)))

    def _effective_dp(self, engine: Any, card_instance: Any) -> float:
        effective_dp = getattr(engine, "effective_dp", None)
        if callable(effective_dp):
            try:
                return float(effective_dp(card_instance))
            except Exception:
                pass
        return float(getattr(card_instance, "dp", getattr(getattr(card_instance, "card", None), "dp", 0)))

    def _enemy_field_dp_pressure(self, engine: Any, player: Any) -> float:
        opponent = self._opponent(engine, player)
        return float(
            sum(
                max(0.0, self._effective_dp(engine, enemy))
                for enemy in getattr(opponent, "field", []) or []
            )
        )

    def _enemy_pressure_near_player_lethal(self, engine: Any, player: Any) -> bool:
        own_life = float(getattr(player, "life", 0) or 0)
        return own_life > 0 and self._enemy_field_dp_pressure(engine, player) >= own_life

    def _enemy_pressure_high_player_risk(self, engine: Any, player: Any) -> bool:
        own_life = float(getattr(player, "life", 0) or 0)
        if own_life <= 0:
            return False
        pressure = self._enemy_field_dp_pressure(engine, player)
        return pressure >= max(2.0, own_life - 1.0)

    def _target_base_count(self, engine: Any, player: Any) -> int:
        turn = int(getattr(getattr(engine, "state", None), "turn", 1) or 1)
        return min(6, max(3, turn + 1))

    def _max_non_base_hand_cost(self, player: Any) -> int:
        costs = [
            _card_cost(getattr(item, "card", item))
            for item in getattr(player, "hand", []) or []
            if getattr(getattr(item, "card", item), "type", None) is not CardType.B_MINION
        ]
        return max(costs, default=0)


class SimplePlayer:
    life = 0
    hand: list[Any] = []
    deck: list[Any] = []
    base: list[Any] = []
    field: list[Any] = []
    forces: list[Any] = []
    movement_right_count = 0


@dataclass
class LinearQModel:
    weights: dict[str, float] = field(default_factory=dict)
    episodes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def greedy_prior(cls) -> "LinearQModel":
        return cls(weights=dict(GREEDY_PRIOR_WEIGHTS), metadata={"initialPolicy": "greedy_prior"})

    def seed_missing_greedy_prior_weights(self) -> list[str]:
        added: list[str] = []
        for key, value in GREEDY_PRIOR_WEIGHTS.items():
            if key in self.weights:
                continue
            self.weights[key] = value
            added.append(key)
        if added:
            self.metadata["greedyPriorSeededMissingWeights"] = added
        return added

    def score(self, features: dict[str, float]) -> float:
        return sum(self.weights.get(name, 0.0) * value for name, value in features.items())

    def update(self, features: dict[str, float], *, target: float, alpha: float) -> float:
        prediction = self.score(features)
        error = target - prediction
        for name, value in features.items():
            if value:
                self.weights[name] = self.weights.get(name, 0.0) + alpha * error * value
        return error

    def top_weights(self, limit: int = 10) -> dict[str, list[dict[str, float]]]:
        ordered = sorted(self.weights.items(), key=lambda item: item[1])
        negative = [{"feature": key, "weight": value} for key, value in ordered[:limit]]
        positive = [{"feature": key, "weight": value} for key, value in reversed(ordered[-limit:])]
        return {"positive": positive, "negative": negative}

    def save(self, path: str | Path, *, metadata: dict[str, Any] | None = None) -> None:
        if metadata is not None:
            self.metadata = dict(metadata)
        data = {
            "kind": MODEL_KIND,
            "version": MODEL_VERSION,
            "createdAt": _utc_now(),
            "episodes": self.episodes,
            "weights": dict(sorted(self.weights.items())),
            "metadata": dict(self.metadata),
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "LinearQModel":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("kind") != MODEL_KIND:
            raise ValueError(f"unsupported model kind: {data.get('kind')!r}")
        return cls(
            weights={str(key): float(value) for key, value in data.get("weights", {}).items()},
            episodes=int(data.get("episodes", 0)),
            metadata=dict(data.get("metadata", {})),
        )


class EpisodeRecorder:
    def __init__(
        self,
        *,
        record_choice_audits: bool = False,
        max_choice_audits: int | None = None,
        changed_choice_audits_only: bool = False,
        capture_choice_audit_snapshots: bool = False,
    ) -> None:
        self.decisions: list[dict[str, float]] = []
        self.score_breakdowns: list[dict[str, float]] = []
        self.record_choice_audits = bool(record_choice_audits)
        self.max_choice_audits = (
            None if max_choice_audits is None else max(0, int(max_choice_audits))
        )
        self.changed_choice_audits_only = bool(changed_choice_audits_only)
        self.capture_choice_audit_snapshots = bool(capture_choice_audit_snapshots)
        self.choice_score_audits: list[dict[str, Any]] = []
        self.choice_score_snapshot_audits: list[dict[str, Any]] = []
        self._choice_audit_count = 0
        self._choice_audit_source_counts: dict[str, int] = {}
        self._replay_context: dict[str, Any] = {}
        self._replay_decision_index = 0

    def begin_replay_context(self, context: Mapping[str, Any] | None = None) -> None:
        self._replay_context = _episode_recorder_json_mapping(context or {})
        self._replay_decision_index = 0

    def record(self, features: dict[str, float]) -> None:
        self.decisions.append(dict(features))

    def record_score_breakdown(self, breakdown: dict[str, float]) -> None:
        self.score_breakdowns.append(dict(breakdown))

    def can_record_choice_score_audit(self, *, changed: bool | None = None) -> bool:
        if not bool(self.record_choice_audits):
            return False
        if self.changed_choice_audits_only and not bool(changed):
            return False
        return self.max_choice_audits is None or self._choice_audit_count < self.max_choice_audits

    def record_choice_score_audit(
        self,
        audit: dict[str, Any],
        *,
        engine: Any | None = None,
        player: Any | None = None,
    ) -> None:
        changed = bool(audit.get("runtimeChoiceChanged", False))
        if self.can_record_choice_score_audit(changed=changed):
            item = dict(audit)
            source = str(item.get("source", "scored_choice"))
            item["choiceAuditIndex"] = int(self._choice_audit_count)
            item["sourceChoiceAuditIndex"] = int(self._choice_audit_source_counts.get(source, 0))
            replay_context = self._next_choice_audit_replay_context()
            if replay_context is not None:
                item["sourceContext"] = replay_context
                item["actionSetDecisionIndex"] = int(replay_context["actionSetDecisionIndex"])
                item["replayCursor"] = dict(replay_context.get("replayCursor") or {})
            self._choice_audit_count += 1
            self._choice_audit_source_counts[source] = int(item["sourceChoiceAuditIndex"]) + 1
            self.choice_score_audits.append(item)
            if self.capture_choice_audit_snapshots and engine is not None:
                snapshot = _episode_recorder_snapshot_engine(engine)
                if snapshot is not None:
                    active_player = player if player is not None else getattr(getattr(engine, "state", None), "active", None)
                    self.choice_score_snapshot_audits.append(
                        {
                            "audit": item,
                            "engine": snapshot,
                            "activePlayer": _episode_recorder_player_label(active_player),
                        }
                    )

    def _next_choice_audit_replay_context(self) -> dict[str, Any] | None:
        if not self._replay_context:
            return None
        decision_index = int(self._replay_decision_index)
        self._replay_decision_index += 1
        context = dict(self._replay_context)
        context["actionSetDecisionIndex"] = decision_index
        raw_cursor = context.get("replayCursor")
        cursor = dict(raw_cursor) if isinstance(raw_cursor, Mapping) else {}
        for key in ("episodeIndex", "runSeed", "modelPolicySeed", "opponentPolicySeed"):
            if key in context and key not in cursor:
                cursor[key] = context[key]
        cursor.setdefault("decisionIndex", decision_index)
        cursor.setdefault("actionSetDecisionIndex", decision_index)
        context["replayCursor"] = _episode_recorder_json_mapping(cursor)
        return _episode_recorder_json_mapping(context)

    def apply_final_reward(self, model: LinearQModel, *, reward: float, gamma: float, alpha: float) -> None:
        target = reward
        for features in reversed(self.decisions):
            model.update(features, target=target, alpha=alpha)
            target *= gamma


def _episode_recorder_json_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _episode_recorder_json_value(value) for key, value in mapping.items()}


def _episode_recorder_snapshot_engine(engine: Any) -> Any | None:
    try:
        if hasattr(engine, "_policies") and hasattr(engine, "__dict__"):
            snapshot = _episode_recorder_light_engine_snapshot(engine)
        else:
            clone_for_simulation = getattr(engine, "clone_for_simulation", None)
            snapshot = clone_for_simulation() if callable(clone_for_simulation) else copy.deepcopy(engine)
        if hasattr(snapshot, "state") and hasattr(snapshot.state, "engine"):
            snapshot.state.engine = snapshot
        if hasattr(snapshot, "triggers") and hasattr(snapshot.triggers, "_engine"):
            snapshot.triggers._engine = snapshot
        rebind = getattr(snapshot, "rebind_passive_modifiers", None)
        if callable(rebind):
            rebind()
        return snapshot
    except Exception:
        return None


def _episode_recorder_light_engine_snapshot(engine: Any) -> Any:
    history_event_keys = {
        "public_reveals",
        "visual_events",
        "effect_events",
        "destroy_events",
        "zone_move_events",
    }
    snapshot = engine.__class__.__new__(engine.__class__)
    memo: dict[int, Any] = {id(engine): snapshot}
    for key, value in engine.__dict__.items():
        if key in history_event_keys:
            setattr(snapshot, key, [])
        elif key == "_policies":
            setattr(snapshot, key, [_episode_recorder_light_policy_snapshot(policy) for policy in list(value or [])])
        else:
            setattr(snapshot, key, copy.deepcopy(value, memo))
    return snapshot


def _episode_recorder_light_policy_snapshot(policy: Any) -> Any:
    try:
        clone = copy.copy(policy)
    except Exception:
        return policy
    rng = getattr(policy, "rng", None)
    if rng is not None:
        try:
            clone.rng = copy.deepcopy(rng)
        except Exception:
            pass
    if hasattr(clone, "recorder"):
        clone.recorder = None
    if hasattr(clone, "action_set_recorder"):
        clone.action_set_recorder = None
    delegate = getattr(policy, "delegate", None)
    if delegate is not None and delegate is not policy:
        try:
            clone.delegate = _episode_recorder_light_policy_snapshot(delegate)
        except Exception:
            pass
    return clone


def _episode_recorder_player_label(player: Any) -> str:
    side = getattr(player, "side", None)
    if side is not None:
        return str(getattr(side, "name", side))
    return str(getattr(player, "name", "unknown"))


def _episode_recorder_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _episode_recorder_json_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_episode_recorder_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


class RLPolicy:
    def __init__(
        self,
        *,
        model: LinearQModel | None = None,
        rng: random.Random | None = None,
        epsilon: float = 0.0,
        recorder: EpisodeRecorder | None = None,
        extractor: FeatureExtractor | None = None,
        humanlike_prior_weight: float = 0.0,
        card_aware_prior_weight: float = 1.0,
        opponent_adaptive_prior_weight: float = 1.0,
        deck_plan_prior_weight: float = 0.0,
        concrete_plan_prior_weight: float = 0.0,
        tactical_prior_weight: float = 1.0,
        target_selection_prior_weight: float = 1.0,
        runtime_profiler: Any | None = None,
    ) -> None:
        self.model = model or LinearQModel()
        self.rng = rng or random.Random()
        self.epsilon = epsilon
        self.recorder = recorder
        self.extractor = extractor or FeatureExtractor()
        self.humanlike_prior_weight = float(humanlike_prior_weight)
        self.card_aware_prior_weight = float(card_aware_prior_weight)
        self.opponent_adaptive_prior_weight = float(opponent_adaptive_prior_weight)
        self.deck_plan_prior_weight = float(deck_plan_prior_weight)
        self.concrete_plan_prior_weight = float(concrete_plan_prior_weight)
        self.tactical_prior_weight = float(tactical_prior_weight)
        self.target_selection_prior_weight = float(target_selection_prior_weight)
        self.runtime_profiler = runtime_profiler
        self._queued_targets: list[Any] = []
        self.use_public_deep_v2_planner = model_uses_public_deep_v2_planner(self.model)
        self.use_public_deep_v2_semantic_bridge = model_uses_public_deep_v2_semantic_bridge(self.model)
        self.public_deep_v2_planner_prior_weight = model_public_deep_v2_planner_prior_weight(self.model)
        self.public_deep_v2_plan_head_rerank_weight = model_public_deep_v2_plan_head_rerank_weight(self.model)
        self.public_deep_v2_rerank_head_weight = model_public_deep_v2_rerank_head_weight(self.model)
        self.public_deep_v2_rerank_head_key_decisions_only = (
            model_public_deep_v2_rerank_head_key_decisions_only(self.model)
        )
        self.public_deep_v2_rerank_anti_aggro_guard = model_public_deep_v2_rerank_anti_aggro_guard(self.model)
        self.public_deep_v2_understanding_runtime_weight = (
            model_public_deep_v2_understanding_runtime_weight(self.model)
        )
        self.uses_observed_opponent_features = model_uses_observed_opponent_features(self.model)
        self.scores_observed_opponent_features = model_scores_observed_opponent_features(self.model)

    def __deepcopy__(self, memo: dict[int, Any]) -> "RLPolicy":
        clone = self.__class__.__new__(self.__class__)
        memo[id(self)] = clone
        shared_keys = {
            "model",
            "transition_evaluator",
            "action_set_scorer",
            "action_set_residual_scorer",
        }
        for key, value in self.__dict__.items():
            if key in shared_keys:
                setattr(clone, key, value)
            elif key == "action_set_recorder":
                setattr(clone, key, None)
            else:
                setattr(clone, key, copy.deepcopy(value, memo))
        return clone

    def _profile_span(self, bucket: str):
        profiler = getattr(self, "runtime_profiler", None)
        span = getattr(profiler, "span", None)
        if not callable(span):
            return nullcontext()
        return span(bucket)

    def _profile_legal_actions(self, engine: Any):
        with self._profile_span("legal_actions"):
            return engine.legal_actions()

    def _profile_features_for_actions(
        self,
        engine: Any,
        player: Any,
        actions: list[Action],
    ) -> list[tuple[Action, dict[str, float]]]:
        with self._profile_span("feature"):
            batch_features = getattr(self.extractor, "features_for_actions", None)
            if callable(batch_features):
                extractor_type = type(self.extractor)
                uses_base_batch = (
                    getattr(extractor_type, "features_for_actions", None)
                    is FeatureExtractor.features_for_actions
                )
                overrides_single = (
                    getattr(extractor_type, "features_for_action", None)
                    is not FeatureExtractor.features_for_action
                )
                if not (uses_base_batch and overrides_single):
                    return list(batch_features(engine, player, actions))
            return [
                (action, self.extractor.features_for_action(engine, player, action))
                for action in actions
            ]

    def choose(self, engine: Any) -> Action:
        self._enable_observed_opponent_features(engine)
        legal = self._profile_legal_actions(engine)
        if not legal:
            raise RuntimeError("no legal action")
        return self._choose_action(engine, getattr(engine.state, "active", None), legal, audit_source="action")

    def choose_flash(self, engine: Any, legal: list[Action]) -> Action:
        self._enable_observed_opponent_features(engine)
        if not legal:
            return Action(kind="flash_pass")
        player = getattr(engine, "_current_flash_priority", None)
        if player is None:
            player = getattr(engine.state, "active", None)
        return self._choose_action(engine, player, legal, audit_source="flash")

    def choose_blocker(self, engine: Any, attacker: Any, blockers: list[Any]):
        self._enable_observed_opponent_features(engine)
        if not blockers:
            return None
        player = getattr(blockers[0], "owner", getattr(getattr(engine, "state", None), "active", None))
        with self._profile_span("feature"):
            none_features = self.extractor.features_for_no_blocker(engine, player, attacker)
            choices: list[tuple[Any, dict[str, float]]] = [(None, none_features)]
            for blocker in blockers:
                choices.append((blocker, self.extractor.features_for_blocker(engine, player, attacker, blocker)))
        return self._choose_scored(
            choices,
            audit_source="blocker",
            engine=engine,
            player=player,
            action_kind="choose_blocker",
            payload_extra={"attacker": _action_set_aux_choice_payload(attacker, engine=engine)},
        )

    def choose_attack_target(self, engine: Any, attacker: Any, targets: list[Any]) -> Any:
        self._enable_observed_opponent_features(engine)
        player = getattr(attacker, "owner", getattr(getattr(engine, "state", None), "active", None))
        with self._profile_span("feature"):
            choices = [
                (target, self.extractor.features_for_attack_target(engine, player, attacker, target))
                for target in targets
            ]
        return self._choose_scored(
            choices,
            audit_source="attack_target",
            engine=engine,
            player=player,
            action_kind="choose_attack_target",
            payload_extra={"attacker": _action_set_aux_choice_payload(attacker, engine=engine)},
        )

    def choose_target(self, engine: Any, kind: str, min_n: int, max_n: int, eligible: list[Any]) -> list[Any]:
        self._enable_observed_opponent_features(engine)
        if not eligible or max_n <= 0:
            return []
        if self._queued_targets:
            selected = [target for target in self._queued_targets if target in eligible][:max_n]
            self._queued_targets = [target for target in self._queued_targets if target not in selected]
            if len(selected) >= min_n:
                return selected
        player = target_selection_player_for_context(engine)
        with self._profile_span("feature"):
            choices = [
                (target, self.extractor.features_for_generic_target(engine, player, kind, target))
                for target in eligible
            ]
        choices = target_choices_after_preinference(choices, min_n=min_n)
        if not choices:
            return []
        scored_choices = [
            (breakdown, self.rng.random(), target, features)
            for (target, features), breakdown in zip(
                choices,
                self._score_breakdowns([features for _target, features in choices]),
                strict=True,
            )
        ]
        ordered = sorted(scored_choices, key=lambda item: (item[0]["total"], item[1]), reverse=True)
        count = max(min_n, min(max_n, len(ordered)))
        selected = ordered[:count]
        for breakdown, _tie_breaker, target, features in selected:
            self._record(features, breakdown=breakdown)
            record_choices = [(breakdown, _tie_breaker, target, features)] + [
                item for item in scored_choices if item[2] is not target
            ]
            record_aux = getattr(self, "_record_aux_action_set_teacher_row", None)
            if callable(record_aux):
                record_aux(
                    engine=engine,
                    player=player,
                    scored_choices=record_choices,
                    selected_choice=target,
                    action_kind="choose_target",
                    payload_extra={"target_kind": str(kind)},
                )
        return [target for _breakdown, _tie_breaker, target, _features in selected]

    def queue_targets(self, targets: list[Any]) -> None:
        self._queued_targets = list(targets)

    def choose_mulligan(self, engine: Any, player: Any) -> list[Any]:
        self._enable_observed_opponent_features(engine)
        hand = list(getattr(player, "hand", []))
        bases = [ci for ci in hand if getattr(ci.card, "type", None) is CardType.B_MINION]
        def is_force_life_exchange_payoff(ci: Any) -> bool:
            return self.extractor._has_effect_template(getattr(ci, "card", ci), "exchange_player_force_life")
        def record_and_return(replacements: list[Any], reason: str) -> list[Any]:
            self._record_mulligan_action_set_teacher_rows(
                engine=engine,
                player=player,
                hand=hand,
                replacements=replacements,
                reason=reason,
            )
            return replacements
        if getattr(player, "is_first_player", None) is False:
            if not bases:
                return record_and_return([
                    ci
                    for ci in hand
                    if getattr(ci.card, "type", None) is not CardType.B_MINION
                    and not is_force_life_exchange_payoff(ci)
                ], "second_no_base")
            if len(bases) == 1:
                second_player_redraw = [
                    ci
                    for ci in hand
                    if getattr(ci.card, "type", None) is not CardType.B_MINION
                    and _card_cost(ci.card) >= 3
                    and not is_force_life_exchange_payoff(ci)
                ]
                if second_player_redraw:
                    return record_and_return(second_player_redraw, "second_one_base_high_cost")
        if not bases:
            return record_and_return([
                ci
                for ci in hand
                if getattr(ci.card, "type", None) is not CardType.B_MINION
                and _card_cost(ci.card) >= 3
                and not is_force_life_exchange_payoff(ci)
            ], "first_no_base_high_cost")

        replacements = []
        for card_instance in hand:
            card = getattr(card_instance, "card", card_instance)
            features = self.extractor.state_features(engine, player)
            features.update(self.extractor.card_features("mulligan", card))
            features["mulligan_candidate"] = 1.0
            if self._model_score(features) < -0.05:
                if is_force_life_exchange_payoff(card_instance):
                    continue
                replacements.append(card_instance)
                self._record(features)
        if replacements:
            return record_and_return(replacements, "model_negative_score")

        early = [
            ci
            for ci in hand
            if getattr(ci.card, "type", None) is not CardType.B_MINION and _card_cost(ci.card) <= 2
        ]
        if early and bases:
            return record_and_return([], "has_base_and_early_play")
        if not bases:
            return record_and_return([
                ci
                for ci in hand
                if getattr(ci.card, "type", None) is not CardType.B_MINION
                and _card_cost(ci.card) >= 3
                and not is_force_life_exchange_payoff(ci)
            ], "fallback_no_base_high_cost")
        if not early:
            return record_and_return([
                ci
                for ci in hand
                if getattr(ci.card, "type", None) is not CardType.B_MINION
                and _card_cost(ci.card) >= 4
                and not is_force_life_exchange_payoff(ci)
            ], "no_early_high_cost")
        return record_and_return([
            ci
            for ci in hand
            if getattr(ci.card, "type", None) is not CardType.B_MINION
            and _card_cost(ci.card) >= 5
            and not is_force_life_exchange_payoff(ci)
        ], "default_expensive_only")

    def _record_mulligan_action_set_teacher_rows(
        self,
        *,
        engine: Any,
        player: Any,
        hand: list[Any],
        replacements: list[Any],
        reason: str,
    ) -> None:
        recorder = getattr(self, "action_set_recorder", None)
        record_decision = getattr(recorder, "record_decision", None)
        if not callable(record_decision) or not hand:
            return
        replacement_ids = {id(card_instance) for card_instance in replacements}
        for card_instance in hand:
            replace = id(card_instance) in replacement_ids or any(card_instance == item for item in replacements)
            payload = _action_set_aux_choice_payload(card_instance, engine=engine)
            actions = [
                Action(kind="mulligan_keep", payload=dict(payload)),
                Action(kind="mulligan_replace", payload=dict(payload)),
            ]
            selected_slot = 1 if replace else 0
            teacher_scores = [0.0, 1.0] if replace else [1.0, 0.0]
            record_decision(
                engine,
                player,
                actions,
                teacher_scores=teacher_scores,
                selected_action_slot=selected_slot,
                decision_kind="mulligan",
                raw_scores=teacher_scores,
                metadata={
                    "policyClass": self.__class__.__name__,
                    "teacherScoreMode": "mulligan_heuristic_binary",
                    "mulliganReason": str(reason),
                },
            )

    def _choose_action(
            self,
            engine: Any,
            player: Any,
            legal: list[Action],
            *,
            audit_source: str = "action",
    ) -> Action:
        choices = self._profile_features_for_actions(engine, player, legal)
        if self.use_public_deep_v2_planner:
            choices = action_choices_after_preinference(choices)
            choices = apply_public_deep_v2_planner_to_action_choices(choices)
        if self.concrete_plan_prior_weight > 0.0 and audit_source == "action":
            choices = apply_concrete_plan_prior_to_action_choices(choices)
        return self._choose_scored(
            choices,
            audit_source=audit_source,
            engine=engine,
            player=player,
            action_set_decision_kind="flash" if audit_source == "flash" else None,
        )

    def _choose_scored(
            self,
            choices: list[tuple[Any, dict[str, float]]],
            *,
            audit_source: str = "scored_choice",
            engine: Any | None = None,
            player: Any | None = None,
            action_kind: str | None = None,
            payload_extra: dict[str, Any] | None = None,
            action_set_decision_kind: str | None = None,
    ) -> Any:
        if not choices:
            raise RuntimeError("no legal choices")
        choices = action_choices_after_preinference(choices)
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]] | None = None
        can_record_aux = action_kind is not None and callable(getattr(self, "_record_aux_action_set_teacher_row", None))
        effective_action_set_decision_kind = action_set_decision_kind
        if effective_action_set_decision_kind is None and action_kind is not None:
            effective_action_set_decision_kind = _action_set_aux_decision_kind(action_kind)
        record_action_set = getattr(self, "_record_action_set_teacher_row", None)
        recorder = getattr(self, "action_set_recorder", None)
        can_record_action_set = (
            effective_action_set_decision_kind is not None
            and action_kind is None
            and callable(record_action_set)
            and callable(getattr(recorder, "record_decision", None))
            and engine is not None
            and player is not None
        )
        can_score_action_set = (
            effective_action_set_decision_kind is not None
            and engine is not None
            and player is not None
            and callable(getattr(self, "_apply_action_set_aux_scorer", None))
        )
        if self.rng.random() < self.epsilon:
            choice, features = self.rng.choice(choices)
            selected_breakdown = self._score_breakdown(features)
            if can_record_aux or can_record_action_set:
                score_breakdowns = self._score_breakdowns([features for _choice, features in choices])
                scored_choices = [
                    (score_breakdowns[index], 0.0, choice_item, choice_features)
                    for index, (choice_item, choice_features) in enumerate(choices)
                ]
        else:
            score_breakdowns = self._score_breakdowns([features for _, features in choices])
            scored_choices = [
                (score_breakdowns[index], self.rng.random(), choice, features)
                for index, (choice, features) in enumerate(choices)
            ]
            if can_score_action_set:
                self._apply_action_set_aux_scorer(
                    engine=engine,
                    player=player,
                    scored_choices=scored_choices,
                    decision_kind=str(effective_action_set_decision_kind),
                    action_kind=action_kind,
                    payload_extra=payload_extra or {},
                    metadata_extra={
                        "auditSource": str(audit_source),
                        "teacherScoreMode": "runtime_total",
                    },
                )
                self._apply_action_set_residual_scorer(
                    engine=engine,
                    player=player,
                    scored_choices=scored_choices,
                    decision_kind=str(effective_action_set_decision_kind),
                    action_kind=action_kind,
                    payload_extra=payload_extra or {},
                    metadata_extra={
                        "auditSource": str(audit_source),
                        "teacherScoreMode": "runtime_total",
                    },
                )
            takeover_index = (
                self._action_set_takeover_index(
                    base_breakdowns=[breakdown for breakdown, _tie_breaker, _choice, _features in scored_choices],
                    decision_kind=str(effective_action_set_decision_kind),
                )
                if can_score_action_set
                else None
            )
            if takeover_index is not None:
                for index, (breakdown, _tie_breaker, _choice, _features) in enumerate(scored_choices):
                    breakdown["actionSetTakeoverSelected"] = 1.0 if index == takeover_index else 0.0
                _breakdown, _tie_breaker, choice, features = scored_choices[int(takeover_index)]
            else:
                _, _, choice, features = max(
                    scored_choices,
                    key=lambda item: (item[0]["total"], item[1]),
                )
            selected_breakdown = next(
                breakdown
                for breakdown, _, _, scored_features in scored_choices
                if scored_features is features
            )
            if can_score_action_set:
                self._record_action_set_selection_influence(
                    scored_choices=scored_choices,
                    selected_action=choice,
                )
            self._record_choice_score_audit(
                scored_choices,
                selected_features=features,
                source=audit_source,
                engine=engine,
                player=player,
            )
        self._record(features, breakdown=selected_breakdown)
        record_aux = getattr(self, "_record_aux_action_set_teacher_row", None)
        if can_record_aux and scored_choices is not None and callable(record_aux):
            record_aux(
                engine=engine,
                player=player,
                scored_choices=scored_choices,
                selected_choice=choice,
                action_kind=action_kind,
                payload_extra=payload_extra or {},
            )
        if can_record_action_set and scored_choices is not None and callable(record_action_set):
            raw_scores = [
                float(breakdown.get("model", breakdown.get("total", 0.0)) or 0.0)
                for breakdown, _tie_breaker, _choice, _features in scored_choices
            ]
            record_action_set(
                engine=engine,
                player=player,
                scored_choices=scored_choices,
                selected_action=choice,
                raw_scores=raw_scores,
                decision_kind=str(effective_action_set_decision_kind),
                metadata_extra={
                    "auditSource": str(audit_source),
                    "teacherScoreMode": "runtime_total",
                },
            )
        return choice

    def score_action_for_lookahead(self, engine: Any, player: Any, action: Action) -> float:
        choices = self._profile_features_for_actions(engine, player, [action])
        choices = action_choices_after_preinference(choices)
        if self.use_public_deep_v2_planner:
            choices = apply_public_deep_v2_planner_to_action_choices(choices)
        if self.concrete_plan_prior_weight > 0.0:
            choices = apply_concrete_plan_prior_to_action_choices(choices)
        if not choices:
            return float("-inf")
        return self._score_features(choices[0][1])

    def _record_choice_score_audit(
        self,
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        selected_features: dict[str, float],
        source: str = "scored_choice",
        engine: Any | None = None,
        player: Any | None = None,
    ) -> None:
        if self.recorder is None or not getattr(self.recorder, "record_choice_audits", False):
            return
        can_record = getattr(self.recorder, "can_record_choice_score_audit", None)
        changed_only = bool(getattr(self.recorder, "changed_choice_audits_only", False))
        if callable(can_record) and not changed_only and not can_record():
            return
        ordered = sorted(
            scored_choices,
            key=lambda item: (item[0]["total"], item[1]),
            reverse=True,
        )
        selected_index = next(
            (
                index
                for index, (_, _, _, features) in enumerate(ordered)
                if features is selected_features
            ),
            -1,
        )
        runtime_choice_changed = self._choice_score_audit_runtime_changed(
            ordered,
            selected_index=selected_index,
        )
        if callable(can_record) and changed_only and not can_record(changed=runtime_choice_changed):
            return
        choices = [
            {
                "label": _score_audit_label(features),
                "actionId": _score_audit_action_id(action, features),
                "actionKind": _score_audit_action_kind(action, features),
                "actionPayload": dict(getattr(action, "payload", {}) or {}),
                "actionRecord": _score_audit_action_record(
                    action,
                    features,
                    engine=engine,
                    player=player,
                ),
                "features": {str(key): float(value) for key, value in features.items()},
                "tags": _score_audit_tags(features),
                "score": float(breakdown["total"]),
                "breakdown": dict(breakdown),
            }
            for breakdown, _, action, features in ordered
        ]
        audit = {
            "source": str(source),
            "selectedIndex": selected_index,
            "runtimeChoiceChanged": bool(runtime_choice_changed),
            "choices": choices,
        }
        try:
            is_first = float(selected_features.get("learner_is_first_player", 0.0) or 0.0) > 0.5
            is_second = float(selected_features.get("learner_is_second_player", 0.0) or 0.0) > 0.5
        except (TypeError, ValueError):
            is_first = False
            is_second = False
        if is_first and not is_second:
            audit["learnerFirstness"] = "first"
        elif is_second and not is_first:
            audit["learnerFirstness"] = "second"
        if is_first or is_second:
            audit["beforeStateFeatures"] = {
                "learner_is_first_player": 1.0 if is_first else 0.0,
                "learner_is_second_player": 1.0 if is_second else 0.0,
            }
        if isinstance(self.recorder, EpisodeRecorder):
            self.recorder.record_choice_score_audit(audit, engine=engine, player=player)
        else:
            self.recorder.record_choice_score_audit(audit)

    @staticmethod
    def _choice_score_audit_runtime_changed(
        ordered_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        selected_index: int,
    ) -> bool:
        if selected_index < 0 or selected_index >= len(ordered_choices):
            return False
        transition_evaluated = any(
            _safe_float(breakdown.get("transitionEvaluator")) != 0.0
            or _safe_float(breakdown.get("transitionEvaluatorRaw")) != 0.0
            or _safe_float(breakdown.get("transitionEvaluatorAbstained")) > 0.0
            for breakdown, _random_tie, _choice, _features in ordered_choices
        )
        bounded_mcts_evaluated = any(
            any(
                _safe_float(breakdown.get(key)) != 0.0
                for key in (
                    "boundedMctsPlannerCandidate",
                    "boundedMctsPlannerPrior",
                    "boundedMctsPlannerVisits",
                    "boundedMctsPlannerQ",
                    "boundedMctsPlanner",
                    "boundedMctsPlannerBaselineSelected",
                    "boundedMctsPlannerSelected",
                    "boundedMctsPlannerAbstained",
                )
            )
            for breakdown, _random_tie, _choice, _features in ordered_choices
        )
        if not transition_evaluated and not bounded_mcts_evaluated:
            return False

        def score_without_runtime(breakdown: dict[str, float]) -> float:
            score = _safe_float(breakdown.get("total")) - _safe_float(
                breakdown.get("transitionEvaluator")
            )
            if bounded_mcts_evaluated:
                score -= _safe_float(breakdown.get("boundedMctsPlanner"))
            return float(score)

        baseline_index = max(
            range(len(ordered_choices)),
            key=lambda index: (score_without_runtime(ordered_choices[index][0]), -index),
        )
        return int(baseline_index) != int(selected_index)

    def _score_features(self, features: dict[str, float]) -> float:
        return self._score_breakdown(features)["total"]

    def _score_breakdowns(self, feature_rows: list[dict[str, float]]) -> list[dict[str, float]]:
        if not feature_rows:
            return []
        model_scores = self._model_scores_many(feature_rows)
        return [
            self._score_breakdown_with_model_score(features, model_score)
            for features, model_score in zip(feature_rows, model_scores, strict=True)
        ]

    def _score_breakdown(self, features: dict[str, float]) -> dict[str, float]:
        return self._score_breakdown_with_model_score(features, self._model_score(features))

    def _score_breakdown_with_model_score(
        self,
        features: dict[str, float],
        model_score: float,
    ) -> dict[str, float]:
        breakdown = {
            "model": float(model_score),
            "playerCorrection": player_correction_score(features),
            "humanlikePrior": self.humanlike_prior_weight * humanlike_action_prior(features),
            "cardAwarePrior": self.card_aware_prior_weight * card_aware_action_prior(features),
            "opponentAdaptivePrior": (
                self.opponent_adaptive_prior_weight * opponent_adaptive_action_prior(features)
            ),
            "deckPlanPrior": self.deck_plan_prior_weight * deck_plan_action_prior(features),
            "concretePlanPrior": self.concrete_plan_prior_weight * concrete_plan_action_prior(features),
            "publicDeepV2PlannerPrior": (
                self.public_deep_v2_planner_prior_weight * public_deep_v2_planner_prior(features)
            ),
            "publicDeepV2PlanHeadRerank": (
                self.public_deep_v2_plan_head_rerank_weight * self._public_deep_v2_plan_head_bonus(features)
            ),
            "publicDeepV2RerankHead": (
                self.public_deep_v2_rerank_head_weight * self._public_deep_v2_rerank_head_bonus(features)
            ),
            "publicDeepV2UnderstandingRuntime": (
                self.public_deep_v2_understanding_runtime_weight
                * self._public_deep_v2_understanding_bonus(features)
            ),
            "tacticalPrior": self.tactical_prior_weight * tactical_action_prior(features),
            "targetSelectionPrior": self.target_selection_prior_weight * target_selection_prior(features),
        }
        breakdown["total"] = sum(breakdown.values())
        return breakdown

    def _public_deep_v2_plan_head_bonus(self, features: dict[str, float]) -> float:
        if self.public_deep_v2_plan_head_rerank_weight <= 0.0:
            return 0.0
        if not hasattr(self.model, "plan_logits_many"):
            return 0.0
        try:
            logits = self.model.plan_logits_many([_public_deep_v2_auxiliary_scoring_features(features)])[0]
        except Exception:
            return 0.0
        if not logits:
            return 0.0
        return max(_sigmoid(float(value)) for value in logits) - 0.5

    def _public_deep_v2_rerank_head_bonus(self, features: dict[str, float]) -> float:
        if self.public_deep_v2_rerank_head_weight <= 0.0:
            return 0.0
        if not hasattr(self.model, "rerank_score_many"):
            return 0.0
        if self.public_deep_v2_rerank_head_key_decisions_only and not _public_deep_v2_rerank_key_decision(features):
            return 0.0
        try:
            bonus = float(self.model.rerank_score_many([_public_deep_v2_auxiliary_scoring_features(features)])[0])
        except Exception:
            return 0.0
        if bonus > 0.0 and self.public_deep_v2_rerank_anti_aggro_guard and _public_deep_v2_rerank_anti_aggro_risk(features):
            return 0.0
        return bonus

    def _public_deep_v2_understanding_bonus(self, features: dict[str, float]) -> float:
        if self.public_deep_v2_understanding_runtime_weight <= 0.0:
            return 0.0
        if not hasattr(self.model, "understanding_action_bonus"):
            return 0.0
        try:
            return float(self.model.understanding_action_bonus(_public_deep_v2_auxiliary_scoring_features(features)))
        except Exception:
            return 0.0

    def _model_score(self, features: dict[str, float]) -> float:
        with self._profile_span("model"):
            return float(self.model.score(model_scoring_features(
                features,
                include_observed_opponent_features=self.scores_observed_opponent_features,
                include_public_deep_v2_planner_features=self.use_public_deep_v2_planner,
                include_public_deep_v2_semantic_bridge_features=self.use_public_deep_v2_semantic_bridge,
            )))

    def _model_scores_many(self, feature_rows: list[dict[str, float]]) -> list[float]:
        scoring_rows = [
            model_scoring_features(
                features,
                include_observed_opponent_features=self.scores_observed_opponent_features,
                include_public_deep_v2_planner_features=self.use_public_deep_v2_planner,
                include_public_deep_v2_semantic_bridge_features=self.use_public_deep_v2_semantic_bridge,
            )
            for features in feature_rows
        ]
        score_many = getattr(self.model, "score_many", None)
        with self._profile_span("model"):
            if callable(score_many):
                return [float(score) for score in score_many(scoring_rows)]
            return [float(self.model.score(features)) for features in scoring_rows]

    def _record(self, features: dict[str, float], *, breakdown: dict[str, float] | None = None) -> None:
        if self.recorder is not None:
            self.recorder.record(features)
            self.recorder.record_score_breakdown(breakdown or self._score_breakdown(features))

    def _enable_observed_opponent_features(self, engine: Any) -> None:
        if self.uses_observed_opponent_features:
            setattr(engine, "enable_observed_opponent_features", True)


def _score_audit_action_kind(action: Any, features: dict[str, float]) -> str:
    if _safe_float(features.get("block:none", 0.0)) > 0.0:
        return "block_none"
    if _safe_float(features.get("decision:blocker", 0.0)) > 0.0:
        return "blocker"
    return str(getattr(action, "kind", "unknown"))


def _score_audit_action_id(action: Any, features: dict[str, float]) -> str:
    kind = _score_audit_action_kind(action, features)
    payload = dict(getattr(action, "payload", {}) or {})
    if not payload:
        return kind
    parts = [f"{key}={payload[key]}" for key in sorted(payload)]
    return f"{kind}:{':'.join(parts)}"


def _score_audit_action_record(
    action: Any,
    features: dict[str, float],
    *,
    engine: Any | None,
    player: Any | None,
) -> dict[str, Any]:
    kind = _score_audit_action_kind(action, features)
    payload = dict(getattr(action, "payload", {}) or {})
    record: dict[str, Any] = {"kind": kind, "payload": dict(payload)}
    if engine is not None and player is not None and payload:
        record["signature"] = _score_audit_action_signature(
            engine,
            player,
            kind=kind,
            payload=payload,
        )
    return record


def _score_audit_action_signature(
    engine: Any,
    player: Any,
    *,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    signature_payload: dict[str, Any] = {}
    for key, value in sorted(payload.items()):
        if key == "iid" or str(key).endswith("_iid"):
            try:
                signature_payload[str(key)] = _score_audit_semantic_iid_ref(
                    engine,
                    player,
                    int(value),
                )
            except (TypeError, ValueError):
                signature_payload[str(key)] = _score_audit_json_scalar(value)
        else:
            signature_payload[str(key)] = _score_audit_json_scalar(value)
    return {"kind": str(kind), "payload": signature_payload}


def _score_audit_semantic_iid_ref(engine: Any, preferred_player: Any, iid: int) -> dict[str, Any]:
    state = getattr(engine, "state", None)
    players = [preferred_player] if preferred_player is not None else []
    for candidate in list(getattr(state, "players", []) or []):
        if candidate is not preferred_player:
            players.append(candidate)
    for owner in players:
        for zone_name in ("hand", "base", "field", "trash", "removed"):
            zone = list(getattr(owner, zone_name, []) or [])
            for index, card_instance in enumerate(zone):
                if getattr(card_instance, "iid", None) != iid:
                    continue
                card = getattr(card_instance, "card", card_instance)
                card_id = str(getattr(card, "id", getattr(card, "name_en", "unknown")))
                same_card_index = sum(
                    1
                    for earlier in zone[:index]
                    if str(
                        getattr(
                            getattr(earlier, "card", earlier),
                            "id",
                            getattr(getattr(earlier, "card", earlier), "name_en", "unknown"),
                        )
                    )
                    == card_id
                )
                return {
                    "owner": _score_audit_player_label(owner),
                    "zone": zone_name,
                    "cardId": card_id,
                    "zoneIndex": int(index),
                    "sameCardIndex": int(same_card_index),
                }
    return {"iid": int(iid)}


def _score_audit_player_label(player: Any) -> str:
    side = getattr(player, "side", None)
    if side is not None:
        return str(getattr(side, "name", side))
    return str(getattr(player, "name", "unknown"))


def _score_audit_json_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


def _score_audit_label(features: dict[str, float]) -> str:
    for prefix in ("action:", "block:", "decision:", "target_effect:", "target_kind:"):
        for key, value in sorted(features.items()):
            if key.startswith(prefix) and _safe_float(value) > 0.0:
                return key
    return "unknown"


def _score_audit_tags(features: dict[str, float]) -> list[str]:
    priority_prefixes = (
        "positive_",
        "negative_",
        "enemy_field_dp_pressure",
        "enemy_pressure_",
        "semantic_action_",
        "block:",
        "blocker_",
        "block_none_",
        "block_context_",
        "place_colorless_mana_",
        "play_card_beneficial_",
        "play_card_harmful_",
        "play_card_effect:",
        "play_card_force_life_exchange",
        "play_card_base_search_support",
        "play_card_profile_role:",
        "replace_field_",
        "move_field_to_base",
        "move_base_to_field",
        "attack_",
        "concrete_plan_intent:",
        "concrete_plan_reason:",
        "planner_intent:",
        "planner_reason:",
        "own_deck_combo_route:",
        "own_deck_plan:",
    )
    prefixes = priority_prefixes + (
        "action:",
        "decision:",
        "play_card_id:",
        "move_card_id:",
        "attacker_id:",
        "target_card_id:",
        "target_force_id:",
        "own_deck_archetype:",
    )
    tags: list[str] = []
    seen: set[str] = set()
    for prefix in prefixes:
        for key, value in sorted(features.items()):
            if len(tags) >= 24:
                return tags
            if key in seen:
                continue
            if _safe_float(value) > 0.0 and key.startswith(prefix):
                seen.add(key)
                tags.append(key)
    return tags


class PositionEvaluator:
    def evaluate(self, engine: Any, player: Any) -> float:
        opponent = self._opponent(engine, player)
        return (
            (float(getattr(player, "life", 0)) - float(getattr(opponent, "life", 0))) * 1.0
            + (self._force_life(player) - self._force_life(opponent)) * 0.35
            + (self._forces_alive(player) - self._forces_alive(opponent)) * 2.0
            + (self._field_bp(player) - self._field_bp(opponent)) / 1000.0
            + (self._field_dp(player) - self._field_dp(opponent)) * 0.35
            + (_safe_len(getattr(player, "hand", [])) - _safe_len(getattr(opponent, "hand", []))) * 0.1
            + (self._base_development(player) - self._base_development(opponent))
            + self._force_life_exchange_value(player, opponent)
            - self._force_life_exchange_value(opponent, player)
        )

    def survival_pressure_value(self, engine: Any, player: Any) -> float:
        opponent = self._opponent(engine, player)
        enemy_ready_dp = self._ready_field_dp(opponent)
        if enemy_ready_dp <= 0.0:
            return 0.0
        own_ready_blocker_dp = self._ready_field_dp(player, blockers_only=True)
        force_life = self._force_life(player)
        player_life = float(getattr(player, "life", 0) or 0)

        uncovered_pressure = max(0.0, enemy_ready_dp - own_ready_blocker_dp)
        value = -uncovered_pressure
        if own_ready_blocker_dp <= 0.0:
            value -= 2.0
        if 0.0 < force_life <= enemy_ready_dp:
            value -= 3.0
        elif force_life <= 0.0:
            value -= 1.5
            if player_life <= enemy_ready_dp:
                value -= 8.0
        return value

    def _opponent(self, engine: Any, player: Any) -> Any:
        for candidate in getattr(getattr(engine, "state", None), "players", []):
            if candidate is not player:
                return candidate
        return getattr(getattr(engine, "state", None), "opponent", SimplePlayer())

    def _force_life(self, player: Any) -> float:
        return float(sum(getattr(force, "life", 0) for force in getattr(player, "forces", []) if not getattr(force, "destroyed", False)))

    def _forces_alive(self, player: Any) -> float:
        return float(sum(1 for force in getattr(player, "forces", []) if not getattr(force, "destroyed", False)))

    def _field_bp(self, player: Any) -> float:
        return float(sum(getattr(ci, "bp", getattr(getattr(ci, "card", None), "bp", 0)) for ci in getattr(player, "field", [])))

    def _field_dp(self, player: Any) -> float:
        return float(sum(getattr(ci, "dp", getattr(getattr(ci, "card", None), "dp", 0)) for ci in getattr(player, "field", [])))

    def _ready_field_dp(self, player: Any, *, blockers_only: bool = False) -> float:
        total = 0.0
        for instance in getattr(player, "field", []) or []:
            if getattr(instance, "rested", False):
                continue
            if blockers_only and self._cannot_block(instance):
                continue
            total += max(0.0, self._instance_dp(instance))
        return total

    def _instance_dp(self, instance: Any) -> float:
        return float(getattr(instance, "dp", getattr(getattr(instance, "card", None), "dp", 0)) or 0)

    def _cannot_block(self, instance: Any) -> bool:
        card = getattr(instance, "card", instance)
        keywords = set(getattr(instance, "keywords", []) or []) | set(getattr(card, "keywords", []) or [])
        return Keyword.CANNOT_BLOCK in keywords

    def _base_development(self, player: Any) -> float:
        base_count = _safe_len(getattr(player, "base", []))
        early_curve = min(base_count, 6) * 0.9
        late_curve = max(0, base_count - 6) * 0.2
        return early_curve + late_curve

    def _force_life_exchange_value(self, player: Any, opponent: Any) -> float:
        if not self._has_force_life_exchange_plan(player):
            return 0.0
        lives = [
            float(getattr(force, "life", 0) or 0)
            for force in getattr(player, "forces", []) or []
            if not getattr(force, "destroyed", False) and float(getattr(force, "life", 0) or 0) > 0.0
        ]
        if not lives:
            return -6.0
        lowest = min(lives)
        enemy_life = float(getattr(opponent, "life", 0) or 0)
        if not (0.0 < lowest < enemy_life):
            return 0.0
        hand_bonus = 3.0 if self._has_force_life_exchange_in_hand(player) else 0.0
        mana_bonus = 2.0 if _safe_len(getattr(player, "base", [])) >= 8 else 0.0
        return 6.0 + (enemy_life - lowest) * 1.1 + hand_bonus + mana_bonus

    def _has_force_life_exchange_plan(self, player: Any) -> bool:
        return any(
            self._has_exchange_effect(getattr(item, "card", item))
            for item in list(getattr(player, "hand", []) or []) + list(getattr(player, "deck", []) or [])
        )

    def _has_force_life_exchange_in_hand(self, player: Any) -> bool:
        return any(
            self._has_exchange_effect(getattr(item, "card", item))
            for item in getattr(player, "hand", []) or []
        )

    def _has_exchange_effect(self, card: Any) -> bool:
        for effect in getattr(card, "effects", []) or []:
            if str(getattr(effect, "template_id", "") or "") == "exchange_player_force_life":
                return True
        return False


class LookaheadRLPolicy(RLPolicy):
    def __init__(
        self,
        *,
        lookahead_weight: float = 0.35,
        max_lookahead_actions: int = 8,
        lookahead_depth: int = 1,
        lookahead_branch_width: int = 4,
        lookahead_key_decisions_only: bool = False,
        lookahead_use_active_policy_scores: bool = False,
        lookahead_rollout_actions: int = 0,
        lookahead_rollout_until_self_turn: bool = False,
        survival_pressure_evaluator_weight: float = 0.0,
        evaluator: PositionEvaluator | None = None,
        transition_evaluator: Any | None = None,
        transition_evaluator_path: str | Path | None = None,
        transition_evaluator_weight: float = 0.0,
        transition_evaluator_horizon_turns: int = 2,
        transition_evaluator_max_actions: int = 32,
        transition_evaluator_max_calls: int = 64,
        transition_evaluator_key_decisions_only: bool = True,
        bounded_mcts_planner_enabled: bool = False,
        bounded_mcts_planner_simulations: int = 0,
        bounded_mcts_planner_root_width: int = 4,
        bounded_mcts_planner_depth: int = 2,
        bounded_mcts_planner_cpuct: float = 1.25,
        bounded_mcts_planner_value_weight: float = 0.0,
        bounded_mcts_planner_value_source: str = "hybrid",
        bounded_mcts_planner_key_decisions_only: bool = True,
        bounded_mcts_planner_primary_decision_path: bool = False,
        action_set_recorder: Any | None = None,
        action_set_scorer: Any | None = None,
        action_set_scorer_path: str | Path | None = None,
        action_set_residual_scorer: Any | None = None,
        action_set_residual_scorer_path: str | Path | None = None,
        action_set_residual_score_weight: float = 0.0,
        action_set_residual_decision_kinds: Any | None = None,
        action_set_prune_max_actions: int = 0,
        action_set_prune_include_model_top: int = 1,
        action_set_skip_mcts_margin: float = 0.0,
        action_set_fast_select_margin: float = 0.0,
        action_set_takeover_margin: float = 0.0,
        action_set_aux_score_weight: float = 0.0,
        action_set_influence_decision_kinds: Any | None = None,
        action_set_score_metadata_without_pruning: bool = True,
        action_set_allow_runtime_sidecar_pruning: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.lookahead_weight = lookahead_weight
        self.max_lookahead_actions = max(0, int(max_lookahead_actions))
        self.lookahead_depth = max(1, int(lookahead_depth))
        self.lookahead_branch_width = max(1, int(lookahead_branch_width))
        self.lookahead_key_decisions_only = bool(lookahead_key_decisions_only)
        self.lookahead_use_active_policy_scores = bool(lookahead_use_active_policy_scores)
        self.lookahead_rollout_actions = max(0, int(lookahead_rollout_actions))
        self.lookahead_rollout_until_self_turn = bool(lookahead_rollout_until_self_turn)
        self.survival_pressure_evaluator_weight = float(survival_pressure_evaluator_weight)
        self.position_evaluator = evaluator or PositionEvaluator()
        self.transition_evaluator_weight = float(transition_evaluator_weight)
        self.transition_evaluator_horizon_turns = max(1, int(transition_evaluator_horizon_turns))
        self.transition_evaluator_max_actions = max(1, int(transition_evaluator_max_actions))
        self.transition_evaluator_max_calls = max(0, int(transition_evaluator_max_calls))
        self._transition_evaluator_call_count = 0
        self._transition_evaluator_decision_call_count = 0
        self.transition_evaluator_key_decisions_only = bool(transition_evaluator_key_decisions_only)
        self.bounded_mcts_planner_enabled = bool(bounded_mcts_planner_enabled)
        self.bounded_mcts_planner_simulations = max(0, int(bounded_mcts_planner_simulations))
        self.bounded_mcts_planner_root_width = max(1, int(bounded_mcts_planner_root_width))
        self.bounded_mcts_planner_depth = max(1, int(bounded_mcts_planner_depth))
        self.bounded_mcts_planner_cpuct = max(0.0, float(bounded_mcts_planner_cpuct))
        self.bounded_mcts_planner_value_weight = float(bounded_mcts_planner_value_weight)
        self.bounded_mcts_planner_value_source = self._bounded_mcts_planner_normalise_value_source(
            bounded_mcts_planner_value_source
        )
        self.bounded_mcts_planner_key_decisions_only = bool(bounded_mcts_planner_key_decisions_only)
        self.bounded_mcts_planner_primary_decision_path = bool(bounded_mcts_planner_primary_decision_path)
        self._bounded_mcts_planner_decision_count = 0
        self._bounded_mcts_planner_choice_change_count = 0
        self._bounded_mcts_planner_simulation_count = 0
        self._bounded_mcts_planner_fallback_count = 0
        self.action_set_recorder = action_set_recorder
        self.action_set_scorer_path = str(action_set_scorer_path) if action_set_scorer_path is not None else None
        self.action_set_scorer_load_error: str | None = None
        self.action_set_scorer = action_set_scorer
        if self.action_set_scorer is None and action_set_scorer_path is not None:
            self.action_set_scorer = _load_action_set_scorer(action_set_scorer_path)
        self.action_set_residual_scorer_path = (
            str(action_set_residual_scorer_path)
            if action_set_residual_scorer_path is not None
            else None
        )
        self.action_set_residual_scorer_load_error: str | None = None
        self.action_set_residual_scorer = action_set_residual_scorer
        if self.action_set_residual_scorer is None and action_set_residual_scorer_path is not None:
            self.action_set_residual_scorer = _load_action_set_scorer(action_set_residual_scorer_path)
        self.action_set_residual_score_weight = float(action_set_residual_score_weight)
        self.action_set_residual_decision_kinds = _normalise_action_set_decision_kind_filter(
            action_set_residual_decision_kinds
        )
        self.action_set_prune_max_actions = max(0, int(action_set_prune_max_actions))
        self.action_set_prune_include_model_top = max(0, int(action_set_prune_include_model_top))
        self.action_set_skip_mcts_margin = max(0.0, float(action_set_skip_mcts_margin))
        self.action_set_fast_select_margin = max(0.0, float(action_set_fast_select_margin))
        self.action_set_takeover_margin = max(0.0, float(action_set_takeover_margin))
        self.action_set_aux_score_weight = float(action_set_aux_score_weight)
        self.action_set_influence_decision_kinds = _normalise_action_set_decision_kind_filter(
            action_set_influence_decision_kinds
        )
        self.action_set_score_metadata_without_pruning = bool(action_set_score_metadata_without_pruning)
        self.action_set_allow_runtime_sidecar_pruning = bool(action_set_allow_runtime_sidecar_pruning)
        self._action_set_prune_decision_count = 0
        self._action_set_prune_input_action_count = 0
        self._action_set_prune_kept_action_count = 0
        self._action_set_prune_model_rescue_count = 0
        self._action_set_prune_error_count = 0
        self._action_set_skip_mcts_decision_count = 0
        self._action_set_fast_select_decision_count = 0
        self._action_set_takeover_decision_count = 0
        self._action_set_scorer_decision_count = 0
        self._action_set_scorer_model_top_agreement_count = 0
        self._action_set_scorer_top_margin_sum = 0.0
        self._action_set_scorer_top_margin_max = 0.0
        self._action_set_scorer_top_selection_opportunity_count = 0
        self._action_set_scorer_top_selected_count = 0
        self._action_set_scorer_top_final_score_top_count = 0
        self._action_set_scorer_route_decision_count = 0
        self._action_set_scorer_route_hit_count = 0
        self._action_set_scorer_route_hit_counts: dict[str, int] = {}
        self._action_set_scorer_route_miss_count = 0
        self._action_set_scorer_decision_kind_counts: dict[str, int] = {}
        self._action_set_residual_scorer_decision_count = 0
        self._action_set_residual_scorer_top_margin_sum = 0.0
        self._action_set_residual_scorer_top_margin_max = 0.0
        self._action_set_residual_scorer_decision_kind_counts: dict[str, int] = {}
        self.action_set_runtime_metadata: dict[str, Any] = {}
        self._queued_targets: list[Any] = []
        self.transition_evaluator_load_error: str | None = None
        self.transition_evaluator = transition_evaluator
        self._last_transition_evaluator_delta = 0.0
        self._last_transition_evaluator_novelty_abstained = False
        self._transition_evaluator_decision_count = 0
        self._transition_evaluator_applied_decision_count = 0
        self._transition_evaluator_abstention_count = 0
        self._transition_evaluator_choice_change_count = 0
        self._transition_evaluator_raw_spread_sum = 0.0
        self._transition_evaluator_feature_novelty_abstention_call_count = 0
        self._transition_evaluator_all_novelty_decision_count = 0
        self._transition_evaluator_unknown_feature_counts: dict[str, int] = {}
        self._transition_evaluator_no_change_margin_count = 0
        self._transition_evaluator_no_change_baseline_margin_sum = 0.0
        self._transition_evaluator_no_change_final_margin_sum = 0.0
        if self.transition_evaluator is None and transition_evaluator_path is not None:
            try:
                from zz.counterfactual_transition import TransitionLinearRanker

                self.transition_evaluator = TransitionLinearRanker.load(transition_evaluator_path)
            except Exception as exc:
                self.transition_evaluator = None
                self.transition_evaluator_load_error = str(exc)
        self.use_state_value_head = model_uses_state_value_head(self.model)
        self.state_value_leaf_runtime_focus = model_state_value_leaf_runtime_focus(self.model)

    @staticmethod
    def _bounded_mcts_planner_normalise_value_source(value: str) -> str:
        source = str(value or "hybrid").strip().lower().replace("-", "_")
        aliases = {
            "default": "hybrid",
            "tree": "hybrid",
            "legacy": "hybrid",
            "learned": "transition_evaluator",
            "transition": "transition_evaluator",
            "transition_value": "transition_evaluator",
            "learned_transition": "transition_evaluator",
            "learned_transition_value": "transition_evaluator",
        }
        source = aliases.get(source, source)
        if source not in {"hybrid", "transition_evaluator"}:
            raise ValueError(f"unsupported bounded_mcts_planner_value_source: {value!r}")
        return source

    def choose(self, engine: Any) -> Action:
        self._transition_evaluator_decision_call_count = 0
        self._enable_observed_opponent_features(engine)
        legal = self._profile_legal_actions(engine)
        if not legal:
            raise RuntimeError("no legal action")
        root_decision_kind = _root_action_set_decision_kind(engine, legal)
        player = getattr(engine.state, "active", None)
        choices = self._profile_features_for_actions(engine, player, legal)
        choices = action_choices_after_preinference(choices)
        if self.use_public_deep_v2_planner:
            choices = apply_public_deep_v2_planner_to_action_choices(choices)
        if self.concrete_plan_prior_weight > 0.0:
            choices = apply_concrete_plan_prior_to_action_choices(choices)
        base_breakdowns = self._score_breakdowns([features for _, features in choices])
        model_scores = [breakdown["total"] for breakdown in base_breakdowns]
        choices, base_breakdowns, model_scores = self._apply_action_set_pruning(
            engine=engine,
            player=player,
            choices=choices,
            base_breakdowns=base_breakdowns,
            model_scores=model_scores,
            decision_kind=root_decision_kind,
        )
        lookahead_indexes = {
            index
            for index, _ in sorted(
                enumerate(model_scores),
                key=lambda item: (item[1], -item[0]),
                reverse=True,
            )[: self.max_lookahead_actions]
        }
        if self.rng.random() < self.epsilon:
            choice, features = self.rng.choice(choices)
        else:
            takeover_index = self._action_set_takeover_index(
                base_breakdowns=base_breakdowns,
                decision_kind=root_decision_kind,
            )
            if takeover_index is not None:
                tie_breakers = [self.rng.random() for _choice in choices]
                scored_choices = []
                for index, (action, action_features) in enumerate(choices):
                    breakdown = dict(base_breakdowns[index])
                    breakdown["transitionEvaluatorRaw"] = 0.0
                    breakdown["transitionEvaluator"] = 0.0
                    breakdown["transitionEvaluatorAbstained"] = 0.0
                    breakdown["transitionEvaluatorIneligible"] = 0.0
                    breakdown["lookahead"] = 0.0
                    breakdown["actionSetTakeoverSelected"] = 1.0 if index == takeover_index else 0.0
                    scored_choices.append((breakdown, tie_breakers[index], action, action_features))
                choice, features = choices[takeover_index]
                self._record_choice_score_audit(
                    scored_choices,
                    selected_features=features,
                    source="root_action",
                    engine=engine,
                    player=player,
                )
                self._record_action_set_selection_influence(
                    scored_choices=scored_choices,
                    selected_action=choice,
                )
                self._record_action_set_teacher_row(
                    engine=engine,
                    player=player,
                    scored_choices=scored_choices,
                    selected_action=choice,
                    raw_scores=model_scores,
                    decision_kind=root_decision_kind,
                )
                self._record(features)
                return choice
            fast_select_index = self._action_set_fast_select_index(
                choices=choices,
                base_breakdowns=base_breakdowns,
                model_scores=model_scores,
                decision_kind=root_decision_kind,
            )
            if fast_select_index is not None:
                tie_breakers = [self.rng.random() for _choice in choices]
                scored_choices = []
                for index, (action, action_features) in enumerate(choices):
                    breakdown = dict(base_breakdowns[index])
                    breakdown["transitionEvaluatorRaw"] = 0.0
                    breakdown["transitionEvaluator"] = 0.0
                    breakdown["transitionEvaluatorAbstained"] = 0.0
                    breakdown["transitionEvaluatorIneligible"] = 0.0
                    breakdown["lookahead"] = 0.0
                    breakdown["actionSetFastSelected"] = 1.0 if index == fast_select_index else 0.0
                    scored_choices.append((breakdown, tie_breakers[index], action, action_features))
                choice, features = choices[fast_select_index]
                self._record_choice_score_audit(
                    scored_choices,
                    selected_features=features,
                    source="root_action",
                    engine=engine,
                    player=player,
                )
                self._record_action_set_selection_influence(
                    scored_choices=scored_choices,
                    selected_action=choice,
                )
                self._record_action_set_teacher_row(
                    engine=engine,
                    player=player,
                    scored_choices=scored_choices,
                    selected_action=choice,
                    raw_scores=model_scores,
                    decision_kind=root_decision_kind,
                )
                self._record(features)
                return choice
            use_transition_evaluator = (
                not self.bounded_mcts_planner_primary_decision_path
                and len(lookahead_indexes) >= 2
                and self.transition_evaluator_weight > 0.0
                and self.transition_evaluator is not None
                and (
                    self.transition_evaluator_max_calls - self._transition_evaluator_call_count
                ) >= len(lookahead_indexes)
            )
            if use_transition_evaluator and self.transition_evaluator_key_decisions_only:
                use_transition_evaluator = any(
                    self._transition_evaluator_key_decision(action, features)
                    for index, (action, features) in enumerate(choices)
                    if index in lookahead_indexes
                )
            scored_choice_drafts = []
            for index, (action, features) in enumerate(choices):
                breakdown = dict(base_breakdowns[index])
                transition_eval_raw = 0.0
                lookahead = 0.0
                if index in lookahead_indexes:
                    delta = self._lookahead_delta(
                        engine,
                        player,
                        action,
                        features,
                        include_transition_evaluator=use_transition_evaluator,
                    )
                    transition_eval_raw = (
                        float(getattr(self, "_last_transition_evaluator_delta", 0.0))
                        if use_transition_evaluator
                        else 0.0
                    )
                    transition_novelty_abstained = (
                        bool(getattr(self, "_last_transition_evaluator_novelty_abstained", False))
                        if use_transition_evaluator
                        else False
                    )
                    lookahead = self.lookahead_weight * (float(delta) - transition_eval_raw)
                else:
                    transition_novelty_abstained = False
                scored_choice_drafts.append((
                    breakdown,
                    self.rng.random(),
                    action,
                    features,
                    float(transition_eval_raw),
                    index in lookahead_indexes,
                    float(lookahead),
                    bool(transition_novelty_abstained),
                    index,
                ))
            transition_values = [
                transition_eval_raw
                for _, _, _, _, transition_eval_raw, evaluated, _, _, _ in scored_choice_drafts
                if evaluated and use_transition_evaluator
            ]
            transition_novelty_flags = [
                novelty_abstained
                for _, _, _, _, _, evaluated, _, novelty_abstained, _ in scored_choice_drafts
                if evaluated and use_transition_evaluator
            ]
            transition_center = (
                sum(transition_values) / len(transition_values)
                if len(transition_values) >= 2
                else 0.0
            )
            minimum_transition_spread = self._transition_evaluator_minimum_decision_spread()
            sorted_transition_values = sorted(transition_values, reverse=True)
            transition_spread = (
                sorted_transition_values[0] - sorted_transition_values[1]
                if len(sorted_transition_values) >= 2
                else 0.0
            )
            transition_abstained = bool(
                use_transition_evaluator
                and len(transition_values) >= 2
                and transition_spread < minimum_transition_spread
            )
            all_transition_novelty_abstained = bool(
                use_transition_evaluator
                and len(transition_novelty_flags) >= 2
                and all(transition_novelty_flags)
            )
            transition_abstained = transition_abstained or all_transition_novelty_abstained
            score_without_transition_by_index = {
                int(item[8]): float(item[0]["total"]) + float(item[6])
                for item in scored_choice_drafts
            }
            tie_breaker_by_index = {
                int(item[8]): float(item[1])
                for item in scored_choice_drafts
            }
            selected_index_without_transition = None
            transition_ineligible_indexes: set[int] = set()
            transition_selected_index_with_transition: int | None = None
            transition_decision_ready = bool(use_transition_evaluator and len(transition_values) >= 2)
            if transition_decision_ready and not transition_abstained:
                selected_index_without_transition = max(
                    score_without_transition_by_index,
                    key=lambda index: (
                        score_without_transition_by_index[index],
                        tie_breaker_by_index.get(index, 0.0),
                    ),
                )
                predicted_score_by_index = {
                    int(item[8]): (
                        float(score_without_transition_by_index[int(item[8])])
                        + (
                            float(item[4]) - float(transition_center)
                            if bool(item[5])
                            else 0.0
                        )
                    )
                    for item in scored_choice_drafts
                }
                ranked_transition_indexes = sorted(
                    predicted_score_by_index,
                    key=lambda index: (
                        predicted_score_by_index[index],
                        tie_breaker_by_index.get(index, 0.0),
                    ),
                    reverse=True,
                )
                for candidate_index in ranked_transition_indexes:
                    if self._transition_evaluator_candidate_ineligible(
                        scored_choice_drafts,
                        selected_index_without_transition=selected_index_without_transition,
                        candidate_index=candidate_index,
                        score_without_transition_by_index=score_without_transition_by_index,
                        predicted_score_by_index=predicted_score_by_index,
                    ):
                        transition_ineligible_indexes.add(int(candidate_index))
                        continue
                    transition_selected_index_with_transition = int(candidate_index)
                    break
                raw_transition_top_index = (
                    int(ranked_transition_indexes[0])
                    if ranked_transition_indexes
                    else int(selected_index_without_transition)
                )
                if (
                    transition_selected_index_with_transition is None
                    or (
                        int(transition_selected_index_with_transition) == int(selected_index_without_transition)
                        and raw_transition_top_index in transition_ineligible_indexes
                    )
                ):
                    transition_abstained = True
                    selected_index_without_transition = None
                    transition_selected_index_with_transition = None
            if transition_decision_ready:
                self._transition_evaluator_decision_count += 1
                self._transition_evaluator_raw_spread_sum += float(transition_spread)
                if all_transition_novelty_abstained:
                    self._transition_evaluator_all_novelty_decision_count += 1
                if transition_abstained:
                    self._transition_evaluator_abstention_count += 1
                else:
                    self._transition_evaluator_applied_decision_count += 1
            transition_applied = bool(transition_decision_ready and not transition_abstained)
            scored_choices = []
            final_score_by_index: dict[int, float] = {}
            for (
                breakdown,
                tie_breaker,
                action,
                features,
                transition_eval_raw,
                evaluated,
                lookahead,
                _novelty_abstained,
                index,
            ) in scored_choice_drafts:
                transition_ineligible = (
                    not transition_abstained
                    and int(index) in transition_ineligible_indexes
                )
                transition_eval = (
                    transition_eval_raw - transition_center
                    if (
                        evaluated
                        and use_transition_evaluator
                        and not transition_abstained
                        and not transition_ineligible
                    )
                    else 0.0
                )
                breakdown["transitionEvaluatorRaw"] = float(transition_eval_raw)
                breakdown["transitionEvaluator"] = float(transition_eval)
                breakdown["transitionEvaluatorAbstained"] = 1.0 if evaluated and transition_abstained else 0.0
                breakdown["transitionEvaluatorIneligible"] = 1.0 if transition_ineligible else 0.0
                breakdown["lookahead"] = float(lookahead)
                breakdown["total"] = float(breakdown["total"]) + float(lookahead) + float(transition_eval)
                final_score_by_index[int(index)] = float(breakdown["total"])
                scored_choices.append((breakdown, tie_breaker, action, features))
            self._apply_action_set_aux_scorer(
                engine=engine,
                player=player,
                scored_choices=scored_choices,
                decision_kind=root_decision_kind,
                metadata_extra={
                    "auditSource": "root_action",
                    "teacherScoreMode": "runtime_total",
                },
            )
            self._apply_action_set_residual_scorer(
                engine=engine,
                player=player,
                scored_choices=scored_choices,
                decision_kind=root_decision_kind,
                metadata_extra={
                    "auditSource": "root_action",
                    "teacherScoreMode": "runtime_total",
                },
            )
            final_score_by_index = {
                int(scored_choice_drafts[index][8]): float(
                    scored_choices[index][0].get("total", 0.0) or 0.0
                )
                for index in range(len(scored_choices))
            }
            if not self._should_skip_bounded_mcts_for_action_set(scored_choices, decision_kind=root_decision_kind):
                with self._profile_span("mcts"):
                    self._apply_bounded_mcts_planner(
                        engine=engine,
                        player=player,
                        scored_choices=scored_choices,
                    )
            primary_planner_choice = (
                next(
                    (
                        item
                        for item in scored_choices
                        if _safe_float(item[0].get("boundedMctsPlannerSelected")) > 0.0
                    ),
                    None,
                )
                if self.bounded_mcts_planner_primary_decision_path
                else None
            )
            if primary_planner_choice is not None:
                _, _, choice, features = primary_planner_choice
            else:
                _, _, choice, features = max(
                    [
                        item
                        for item in scored_choices
                        if not (
                            transition_applied
                            and _safe_float(item[0].get("transitionEvaluatorIneligible")) > 0.0
                        )
                    ] or scored_choices,
                    key=lambda item: (item[0]["total"], item[1]),
                )
            if transition_applied and selected_index_without_transition is not None:
                eligible_final_scores = {
                    index: score
                    for index, score in final_score_by_index.items()
                    if index not in transition_ineligible_indexes
                }
                selected_index_with_transition = (
                    transition_selected_index_with_transition
                    if transition_selected_index_with_transition is not None
                    else max(
                        eligible_final_scores or final_score_by_index,
                        key=lambda index: (
                            (eligible_final_scores or final_score_by_index)[index],
                            tie_breaker_by_index.get(index, 0.0),
                        ),
                    )
                )
                if selected_index_with_transition != selected_index_without_transition:
                    self._transition_evaluator_choice_change_count += 1
                else:
                    other_base_scores = [
                        score
                        for index, score in score_without_transition_by_index.items()
                        if index != selected_index_without_transition
                    ]
                    other_final_scores = [
                        score
                        for index, score in final_score_by_index.items()
                        if (
                            index != selected_index_without_transition
                            and index not in transition_ineligible_indexes
                        )
                    ]
                    if other_base_scores and other_final_scores:
                        baseline_margin = max(
                            0.0,
                            score_without_transition_by_index[selected_index_without_transition]
                            - max(other_base_scores),
                        )
                        final_margin = max(
                            0.0,
                            final_score_by_index[selected_index_without_transition]
                            - max(other_final_scores),
                        )
                        self._transition_evaluator_no_change_margin_count += 1
                        self._transition_evaluator_no_change_baseline_margin_sum += baseline_margin
                        self._transition_evaluator_no_change_final_margin_sum += final_margin
            self._record_choice_score_audit(
                scored_choices,
                selected_features=features,
                source="root_action",
                engine=engine,
                player=player,
            )
            self._record_action_set_selection_influence(
                scored_choices=scored_choices,
                selected_action=choice,
            )
            self._record_action_set_teacher_row(
                engine=engine,
                player=player,
                scored_choices=scored_choices,
                selected_action=choice,
                raw_scores=model_scores,
                decision_kind=root_decision_kind,
            )
        self._record(features)
        return choice

    def action_set_pruning_runtime_stats(self) -> dict[str, int]:
        return {
            "actionSetPruneDecisions": int(self._action_set_prune_decision_count),
            "actionSetPruneInputActions": int(self._action_set_prune_input_action_count),
            "actionSetPruneKeptActions": int(self._action_set_prune_kept_action_count),
            "actionSetPruneModelRescues": int(self._action_set_prune_model_rescue_count),
            "actionSetPruneErrors": int(self._action_set_prune_error_count),
            "actionSetSkipMctsDecisions": int(self._action_set_skip_mcts_decision_count),
            "actionSetFastSelectDecisions": int(self._action_set_fast_select_decision_count),
            "actionSetTakeoverDecisions": int(self._action_set_takeover_decision_count),
        }

    def action_set_influence_runtime_stats(self) -> dict[str, int | float | dict[str, int]]:
        decisions = int(self._action_set_scorer_decision_count)
        agreements = int(self._action_set_scorer_model_top_agreement_count)
        opportunities = int(self._action_set_scorer_top_selection_opportunity_count)
        selected = int(self._action_set_scorer_top_selected_count)
        final_score_top = int(self._action_set_scorer_top_final_score_top_count)
        route_decisions = int(self._action_set_scorer_route_decision_count)
        route_hits = int(self._action_set_scorer_route_hit_count)
        route_misses = int(self._action_set_scorer_route_miss_count)
        return {
            "actionSetScorerDecisions": decisions,
            "actionSetScorerModelTopAgreements": agreements,
            "actionSetScorerModelTopDisagreements": max(0, decisions - agreements),
            "actionSetScorerModelTopAgreementRate": round(agreements / decisions, 6) if decisions else 0.0,
            "actionSetScorerTopMarginSum": round(float(self._action_set_scorer_top_margin_sum), 6),
            "actionSetScorerTopMarginAverage": (
                round(float(self._action_set_scorer_top_margin_sum) / decisions, 6)
                if decisions
                else 0.0
            ),
            "actionSetScorerTopMarginMax": round(float(self._action_set_scorer_top_margin_max), 6),
            "actionSetScorerTopSelectionOpportunities": opportunities,
            "actionSetScorerTopSelected": selected,
            "actionSetScorerTopSelectionRate": round(selected / opportunities, 6) if opportunities else 0.0,
            "actionSetScorerTopFinalScoreTop": final_score_top,
            "actionSetScorerTopFinalScoreTopRate": (
                round(final_score_top / opportunities, 6)
                if opportunities
                else 0.0
            ),
            "actionSetScorerRouteDecisions": route_decisions,
            "actionSetScorerRouteHits": route_hits,
            "actionSetScorerRouteMisses": route_misses,
            "actionSetScorerRouteHitRate": round(route_hits / route_decisions, 6) if route_decisions else 0.0,
            "actionSetScorerRouteHitCounts": dict(sorted(self._action_set_scorer_route_hit_counts.items())),
            "actionSetScorerDecisionKindCounts": dict(sorted(self._action_set_scorer_decision_kind_counts.items())),
            "actionSetResidualScorerDecisions": int(self._action_set_residual_scorer_decision_count),
            "actionSetResidualScorerTopMarginSum": round(float(self._action_set_residual_scorer_top_margin_sum), 6),
            "actionSetResidualScorerTopMarginAverage": (
                round(float(self._action_set_residual_scorer_top_margin_sum) / self._action_set_residual_scorer_decision_count, 6)
                if self._action_set_residual_scorer_decision_count
                else 0.0
            ),
            "actionSetResidualScorerTopMarginMax": round(float(self._action_set_residual_scorer_top_margin_max), 6),
            "actionSetResidualScorerDecisionKindCounts": dict(
                sorted(self._action_set_residual_scorer_decision_kind_counts.items())
            ),
            "actionSetTakeoverDecisions": int(self._action_set_takeover_decision_count),
        }

    def _record_action_set_scorer_decision_kind_influence(self, *, decision_kind: str) -> None:
        key = str(decision_kind or "unknown").strip().lower() or "unknown"
        self._action_set_scorer_decision_kind_counts[key] = (
            int(self._action_set_scorer_decision_kind_counts.get(key, 0)) + 1
        )

    def _record_action_set_residual_scorer_influence(
        self,
        *,
        decision_kind: str,
        top_margin: float,
    ) -> None:
        key = str(decision_kind or "unknown").strip().lower() or "unknown"
        self._action_set_residual_scorer_decision_count += 1
        self._action_set_residual_scorer_decision_kind_counts[key] = (
            int(self._action_set_residual_scorer_decision_kind_counts.get(key, 0)) + 1
        )
        margin = max(0.0, float(top_margin))
        self._action_set_residual_scorer_top_margin_sum += margin
        if margin > self._action_set_residual_scorer_top_margin_max:
            self._action_set_residual_scorer_top_margin_max = margin

    def _record_action_set_scorer_route_influence(self, *, route_key: str | None) -> None:
        self._action_set_scorer_route_decision_count += 1
        if route_key:
            key = str(route_key)
            self._action_set_scorer_route_hit_count += 1
            self._action_set_scorer_route_hit_counts[key] = (
                int(self._action_set_scorer_route_hit_counts.get(key, 0)) + 1
            )
        else:
            self._action_set_scorer_route_miss_count += 1

    def _record_action_set_scorer_ranking_influence(
        self,
        *,
        scorer_top_slot: int,
        scorer_top_margin: float,
        model_top_slot: int | None,
    ) -> None:
        self._action_set_scorer_decision_count += 1
        if model_top_slot is not None and int(model_top_slot) == int(scorer_top_slot):
            self._action_set_scorer_model_top_agreement_count += 1
        margin = max(0.0, float(scorer_top_margin))
        self._action_set_scorer_top_margin_sum += margin
        if margin > self._action_set_scorer_top_margin_max:
            self._action_set_scorer_top_margin_max = margin

    def _record_action_set_selection_influence(
        self,
        *,
        scored_choices: list[tuple[dict[str, float], float, Action, dict[str, float]]],
        selected_action: Action,
    ) -> None:
        scorer_top = next(
            (
                item
                for item in scored_choices
                if _safe_float(item[0].get("actionSetScorerTop")) > 0.0
            ),
            None,
        )
        if scorer_top is None:
            return
        self._action_set_scorer_top_selection_opportunity_count += 1
        if scorer_top[2] is selected_action or scorer_top[2] == selected_action:
            self._action_set_scorer_top_selected_count += 1
        final_score_top = max(
            scored_choices,
            key=lambda item: (float(item[0].get("total", 0.0) or 0.0), item[1]),
        )
        if final_score_top is scorer_top:
            self._action_set_scorer_top_final_score_top_count += 1

    def _apply_action_set_aux_scorer(
        self,
        *,
        engine: Any,
        player: Any,
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        decision_kind: str,
        action_kind: str | None = None,
        payload_extra: Mapping[str, Any] | None = None,
        metadata_extra: Mapping[str, Any] | None = None,
    ) -> None:
        weight = float(getattr(self, "action_set_aux_score_weight", 0.0) or 0.0)
        scorer = getattr(self, "action_set_scorer", None)
        score_row = getattr(scorer, "score_row", None)
        needs_scorer_metadata = (
            float(getattr(self, "action_set_fast_select_margin", 0.0) or 0.0) > 0.0
            or float(getattr(self, "action_set_takeover_margin", 0.0) or 0.0) > 0.0
        )
        can_score_metadata = bool(getattr(self, "action_set_score_metadata_without_pruning", True))
        if weight == 0.0 and needs_scorer_metadata and not can_score_metadata:
            return
        if (weight == 0.0 and not needs_scorer_metadata) or not callable(score_row) or len(scored_choices) < 2:
            return
        if not self._action_set_influence_enabled_for_decision(decision_kind):
            return
        try:
            if action_kind is None:
                actions = [action for _breakdown, _tie_breaker, action, _features in scored_choices]
            else:
                actions = [
                    _action_set_aux_choice_action(
                        str(action_kind),
                        choice,
                        payload_extra=dict(payload_extra or {}),
                        engine=engine,
                    )
                    for _breakdown, _tie_breaker, choice, _features in scored_choices
                ]
            row_metadata = dict(getattr(self, "action_set_runtime_metadata", None) or {})
            row_metadata.update(dict(metadata_extra or {}))
            row = _action_set_scorer_row(
                engine,
                player,
                actions,
                decision_kind=str(decision_kind),
                metadata=row_metadata,
            )
            route_key_for_row = getattr(scorer, "route_key_for_row", None)
            route_key = None
            if callable(route_key_for_row):
                route_key = route_key_for_row(row)
                self._record_action_set_scorer_route_influence(route_key=route_key)
            scores = list(score_row(row))
            scored_slots = [
                (slot, float(score))
                for slot, score in enumerate(scores[: len(scored_choices)])
                if score is not None
            ]
            if not scored_slots:
                return
            scorer_ranked = sorted(scored_slots, key=lambda item: (item[1], -item[0]), reverse=True)
            top_slot, top_score = scorer_ranked[0]
            second_score = float(scorer_ranked[1][1]) if len(scorer_ranked) >= 2 else None
            top_margin = float(top_score) - float(second_score) if second_score is not None else 0.0
            rank_by_slot = {
                int(slot): rank
                for rank, (slot, _score) in enumerate(scorer_ranked, start=1)
            }
            model_top_slot = max(
                range(len(scored_choices)),
                key=lambda slot: (float(scored_choices[slot][0].get("total", 0.0) or 0.0), -slot),
            )
            self._record_action_set_scorer_ranking_influence(
                scorer_top_slot=int(top_slot),
                scorer_top_margin=float(top_margin),
                model_top_slot=int(model_top_slot),
            )
            self._record_action_set_scorer_decision_kind_influence(decision_kind=str(decision_kind))
            max_correction = runtime_aux_max_correction_for_scorer(scorer)
            for slot, score in scored_slots:
                if not (0 <= slot < len(scored_choices)):
                    continue
                breakdown = scored_choices[slot][0]
                weighted = clamp_runtime_aux_residual(
                    score,
                    weight=weight,
                    max_correction=max_correction,
                )
                if weighted is None:
                    continue
                breakdown["actionSetAuxScorerScore"] = float(score)
                breakdown["actionSetAuxScorerWeighted"] = float(weighted)
                breakdown["actionSetScorerScore"] = float(score)
                breakdown["actionSetScorerRank"] = float(rank_by_slot.get(slot, 0))
                breakdown["actionSetScorerTop"] = 1.0 if slot == top_slot else 0.0
                breakdown["actionSetScorerTopMargin"] = float(top_margin)
                breakdown["total"] = float(breakdown.get("total", 0.0) or 0.0) + float(weighted)
        except Exception:
            self._action_set_prune_error_count += 1

    def _apply_action_set_residual_scorer(
        self,
        *,
        engine: Any,
        player: Any,
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        decision_kind: str,
        action_kind: str | None = None,
        payload_extra: Mapping[str, Any] | None = None,
        metadata_extra: Mapping[str, Any] | None = None,
    ) -> None:
        weight = float(getattr(self, "action_set_residual_score_weight", 0.0) or 0.0)
        scorer = getattr(self, "action_set_residual_scorer", None)
        score_row = getattr(scorer, "score_row", None)
        if weight == 0.0 or not callable(score_row) or len(scored_choices) < 2:
            return
        if not self._action_set_influence_enabled_for_decision(decision_kind):
            return
        allowed = getattr(self, "action_set_residual_decision_kinds", frozenset())
        if not _action_set_decision_kind_filter_allows(allowed, decision_kind):
            return
        try:
            if action_kind is None:
                actions = [action for _breakdown, _tie_breaker, action, _features in scored_choices]
            else:
                actions = [
                    _action_set_aux_choice_action(
                        str(action_kind),
                        choice,
                        payload_extra=dict(payload_extra or {}),
                        engine=engine,
                    )
                    for _breakdown, _tie_breaker, choice, _features in scored_choices
                ]
            row_metadata = dict(getattr(self, "action_set_runtime_metadata", None) or {})
            row_metadata.update(dict(metadata_extra or {}))
            row = _action_set_scorer_row(
                engine,
                player,
                actions,
                decision_kind=str(decision_kind),
                metadata=row_metadata,
            )
            scores = list(score_row(row))
            scored_slots = [
                (slot, float(score))
                for slot, score in enumerate(scores[: len(scored_choices)])
                if score is not None
            ]
            if not scored_slots:
                return
            ranked = sorted(scored_slots, key=lambda item: (item[1], -item[0]), reverse=True)
            top_slot, top_score = ranked[0]
            second_score = float(ranked[1][1]) if len(ranked) >= 2 else None
            top_margin = float(top_score) - float(second_score) if second_score is not None else 0.0
            rank_by_slot = {int(slot): rank for rank, (slot, _score) in enumerate(ranked, start=1)}
            self._record_action_set_residual_scorer_influence(
                decision_kind=str(decision_kind),
                top_margin=float(top_margin),
            )
            max_correction = runtime_aux_max_correction_for_scorer(scorer)
            for slot, score in scored_slots:
                if not (0 <= slot < len(scored_choices)):
                    continue
                breakdown = scored_choices[slot][0]
                weighted = clamp_runtime_aux_residual(
                    score,
                    weight=weight,
                    max_correction=max_correction,
                )
                if weighted is None:
                    continue
                breakdown["actionSetResidualScorerScore"] = float(score)
                breakdown["actionSetResidualScorerWeighted"] = float(weighted)
                breakdown["actionSetResidualScorerRank"] = float(rank_by_slot.get(slot, 0))
                breakdown["actionSetResidualScorerTop"] = 1.0 if slot == top_slot else 0.0
                breakdown["actionSetResidualScorerTopMargin"] = float(top_margin)
                breakdown["total"] = float(breakdown.get("total", 0.0) or 0.0) + float(weighted)
        except Exception:
            self._action_set_prune_error_count += 1

    def _action_set_fast_select_index(
        self,
        *,
        choices: list[tuple[Action, dict[str, float]]],
        base_breakdowns: list[dict[str, float]],
        model_scores: list[float],
        decision_kind: str,
    ) -> int | None:
        margin_threshold = float(getattr(self, "action_set_fast_select_margin", 0.0) or 0.0)
        if (
            margin_threshold <= 0.0
            or not self._action_set_influence_enabled_for_decision(decision_kind)
            or len(choices) < 2
            or len(choices) != len(base_breakdowns)
            or len(choices) != len(model_scores)
        ):
            return None
        scorer_top_index = next(
            (
                index
                for index, breakdown in enumerate(base_breakdowns)
                if _safe_float(breakdown.get("actionSetScorerTop")) > 0.0
            ),
            None,
        )
        if scorer_top_index is None:
            return None
        margin = _safe_float(base_breakdowns[scorer_top_index].get("actionSetScorerTopMargin"))
        if margin < margin_threshold:
            return None
        model_top_index = max(
            range(len(model_scores)),
            key=lambda index: (float(model_scores[index]), -index),
        )
        if int(model_top_index) != int(scorer_top_index):
            return None
        self._action_set_fast_select_decision_count += 1
        return int(scorer_top_index)

    def _action_set_takeover_index(
        self,
        *,
        base_breakdowns: list[dict[str, float]],
        decision_kind: str,
    ) -> int | None:
        margin_threshold = float(getattr(self, "action_set_takeover_margin", 0.0) or 0.0)
        if (
            margin_threshold <= 0.0
            or not self._action_set_influence_enabled_for_decision(decision_kind)
            or len(base_breakdowns) < 2
        ):
            return None
        scorer_top_index = next(
            (
                index
                for index, breakdown in enumerate(base_breakdowns)
                if _safe_float(breakdown.get("actionSetScorerTop")) > 0.0
            ),
            None,
        )
        if scorer_top_index is None:
            return None
        margin = _safe_float(base_breakdowns[scorer_top_index].get("actionSetScorerTopMargin"))
        if margin < margin_threshold:
            return None
        self._action_set_takeover_decision_count += 1
        return int(scorer_top_index)

    def _should_skip_bounded_mcts_for_action_set(
        self,
        scored_choices: list[tuple[dict[str, float], float, Action, dict[str, float]]],
        *,
        decision_kind: str,
    ) -> bool:
        margin_threshold = float(getattr(self, "action_set_skip_mcts_margin", 0.0) or 0.0)
        if (
            margin_threshold <= 0.0
            or not self._action_set_influence_enabled_for_decision(decision_kind)
            or not self.bounded_mcts_planner_enabled
            or not self.bounded_mcts_planner_primary_decision_path
            or self.bounded_mcts_planner_simulations <= 0
            or self.bounded_mcts_planner_value_weight == 0.0
            or len(scored_choices) < 2
        ):
            return False
        scorer_top = next(
            (
                item
                for item in scored_choices
                if _safe_float(item[0].get("actionSetScorerTop")) > 0.0
            ),
            None,
        )
        if scorer_top is None:
            return False
        margin = _safe_float(scorer_top[0].get("actionSetScorerTopMargin"))
        if margin < margin_threshold:
            return False
        current_top = max(
            scored_choices,
            key=lambda item: (float(item[0].get("total", 0.0) or 0.0), item[1]),
        )
        if current_top is not scorer_top:
            return False
        self._action_set_skip_mcts_decision_count += 1
        for breakdown, _tie_breaker, _action, _features in scored_choices:
            breakdown["boundedMctsPlannerSkippedByActionSet"] = 1.0
        return True

    def _apply_action_set_pruning(
        self,
        *,
        engine: Any,
        player: Any,
        choices: list[tuple[Action, dict[str, float]]],
        base_breakdowns: list[dict[str, float]],
        model_scores: list[float],
        decision_kind: str = "main",
    ) -> tuple[list[tuple[Action, dict[str, float]]], list[dict[str, float]], list[float]]:
        scorer = getattr(self, "action_set_scorer", None)
        score_row = getattr(scorer, "score_row", None)
        max_keep = int(getattr(self, "action_set_prune_max_actions", 0) or 0)
        needs_scorer_metadata = (
            float(getattr(self, "action_set_skip_mcts_margin", 0.0) or 0.0) > 0.0
            or float(getattr(self, "action_set_fast_select_margin", 0.0) or 0.0) > 0.0
            or float(getattr(self, "action_set_takeover_margin", 0.0) or 0.0) > 0.0
        )
        can_prune = max_keep > 0 and len(choices) > max_keep
        if (
            can_prune
            and _action_set_scorer_is_runtime_aux_sidecar(scorer)
            and not bool(getattr(self, "action_set_allow_runtime_sidecar_pruning", False))
        ):
            can_prune = False
        can_score_metadata = bool(getattr(self, "action_set_score_metadata_without_pruning", True))
        if (
            not callable(score_row)
            or not self._action_set_influence_enabled_for_decision(decision_kind)
            or (not can_prune and not (needs_scorer_metadata and can_score_metadata))
            or len(choices) != len(base_breakdowns)
            or len(choices) != len(model_scores)
        ):
            return choices, base_breakdowns, model_scores
        try:
            actions = [action for action, _features in choices]
            row = _action_set_scorer_row(
                engine,
                player,
                actions,
                decision_kind=str(decision_kind),
                metadata=getattr(self, "action_set_runtime_metadata", None),
            )
            route_key_for_row = getattr(scorer, "route_key_for_row", None)
            route_key = None
            if callable(route_key_for_row):
                route_key = route_key_for_row(row)
                self._record_action_set_scorer_route_influence(route_key=route_key)
            scores = list(score_row(row))
            max_correction = runtime_aux_max_correction_for_scorer(scorer)
            weight = float(getattr(self, "action_set_aux_score_weight", 0.0) or 0.0)
            scored_slots = [
                (
                    slot,
                    _action_set_runtime_ranking_score(
                        scorer,
                        score,
                        base_score=model_scores[slot],
                        weight=weight,
                        max_correction=max_correction,
                    ),
                    float(score),
                    clamp_runtime_aux_residual(
                        score,
                        weight=weight,
                        max_correction=max_correction,
                    ),
                )
                for slot, score in enumerate(scores[: len(choices)])
                if score is not None
            ]
            scored_slots = [
                (slot, float(runtime_score), float(raw_score), weighted)
                for slot, runtime_score, raw_score, weighted in scored_slots
                if runtime_score is not None
            ]
            if not scored_slots:
                return choices, base_breakdowns, model_scores
            scorer_ranked = sorted(
                scored_slots,
                key=lambda item: (item[1], -item[0]),
                reverse=True,
            )
            top_slot, top_score, _top_raw_score, _top_weighted = scorer_ranked[0]
            second_score = (
                float(scorer_ranked[1][1])
                if len(scorer_ranked) >= 2
                else None
            )
            top_margin = (
                float(top_score) - float(second_score)
                if second_score is not None
                else 0.0
            )
            rank_by_slot = {
                int(slot): rank
                for rank, (slot, _score, _raw_score, _weighted) in enumerate(scorer_ranked, start=1)
            }
            for slot, score, raw_score, weighted in scored_slots:
                if 0 <= slot < len(base_breakdowns):
                    base_breakdowns[slot]["actionSetScorerScore"] = float(score)
                    base_breakdowns[slot]["actionSetScorerRawScore"] = float(raw_score)
                    if weighted is not None:
                        base_breakdowns[slot]["actionSetAuxScorerWeighted"] = float(weighted)
                    base_breakdowns[slot]["actionSetScorerRank"] = float(rank_by_slot.get(slot, 0))
                    base_breakdowns[slot]["actionSetScorerTop"] = 1.0 if slot == top_slot else 0.0
                    base_breakdowns[slot]["actionSetScorerTopMargin"] = float(top_margin)
            model_top_slot = (
                max(
                    range(len(model_scores)),
                    key=lambda slot: (float(model_scores[slot]), -slot),
                )
                if model_scores
                else None
            )
            self._record_action_set_scorer_ranking_influence(
                scorer_top_slot=int(top_slot),
                scorer_top_margin=float(top_margin),
                model_top_slot=model_top_slot,
            )
            self._record_action_set_scorer_decision_kind_influence(decision_kind=str(decision_kind))
            if max_keep <= 0 or len(choices) <= max_keep:
                return choices, base_breakdowns, model_scores
            scorer_top_slots = {slot for slot, _score, _raw_score, _weighted in scorer_ranked[:max_keep]}
            model_ranked = sorted(
                range(len(model_scores)),
                key=lambda slot: (float(model_scores[slot]), -slot),
                reverse=True,
            )
            kept_slots: list[int] = []

            def add_slot(slot: int) -> None:
                if len(kept_slots) < max_keep and slot not in kept_slots:
                    kept_slots.append(int(slot))

            for slot in model_ranked[: self.action_set_prune_include_model_top]:
                add_slot(slot)
            for slot, _score, _raw_score, _weighted in scorer_ranked:
                add_slot(slot)
                if len(kept_slots) >= max_keep:
                    break
            kept = set(kept_slots)
            if not kept or len(kept) >= len(choices):
                return choices, base_breakdowns, model_scores
            filtered_indexes = [index for index in range(len(choices)) if index in kept]
            model_rescues = sum(1 for slot in kept_slots if slot not in scorer_top_slots)
            self._action_set_prune_decision_count += 1
            self._action_set_prune_input_action_count += len(choices)
            self._action_set_prune_kept_action_count += len(filtered_indexes)
            self._action_set_prune_model_rescue_count += int(model_rescues)
            return (
                [choices[index] for index in filtered_indexes],
                [base_breakdowns[index] for index in filtered_indexes],
                [model_scores[index] for index in filtered_indexes],
            )
        except Exception:
            self._action_set_prune_error_count += 1
            return choices, base_breakdowns, model_scores

    def _action_set_influence_enabled_for_decision(self, decision_kind: str) -> bool:
        allowed = getattr(self, "action_set_influence_decision_kinds", frozenset())
        return _action_set_decision_kind_filter_allows(allowed, decision_kind)

    def _record_action_set_teacher_row(
        self,
        *,
        engine: Any,
        player: Any,
        scored_choices: list[tuple[dict[str, float], float, Action, dict[str, float]]],
        selected_action: Action,
        raw_scores: list[float],
        decision_kind: str = "main",
        metadata_extra: dict[str, Any] | None = None,
    ) -> None:
        recorder = getattr(self, "action_set_recorder", None)
        record_decision = getattr(recorder, "record_decision", None)
        if not callable(record_decision):
            return
        actions = [action for _breakdown, _tie_breaker, action, _features in scored_choices]
        selected_slot = next(
            (index for index, action in enumerate(actions) if action is selected_action),
            None,
        )
        if selected_slot is None:
            selected_slot = next(
                (index for index, action in enumerate(actions) if action == selected_action),
                None,
            )
        if selected_slot is None:
            return
        teacher_scores = [float(breakdown.get("total", 0.0) or 0.0) for breakdown, *_rest in scored_choices]
        lookahead_deltas = [
            float(breakdown.get("lookahead", 0.0) or 0.0)
            for breakdown, *_rest in scored_choices
        ]
        metadata = {
            "policyClass": self.__class__.__name__,
            "boundedMctsPlannerEnabled": bool(self.bounded_mcts_planner_enabled),
            "boundedMctsPlannerPrimaryDecisionPath": bool(self.bounded_mcts_planner_primary_decision_path),
        }
        metadata.update(dict(metadata_extra or {}))
        record_decision(
            engine,
            player,
            actions,
            teacher_scores=teacher_scores,
            selected_action_slot=int(selected_slot),
            decision_kind=str(decision_kind),
            raw_scores=list(raw_scores),
            lookahead_deltas=lookahead_deltas,
            metadata=metadata,
        )

    def _record_aux_action_set_teacher_row(
        self,
        *,
        engine: Any | None,
        player: Any | None,
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        selected_choice: Any,
        action_kind: str,
        payload_extra: dict[str, Any] | None = None,
    ) -> None:
        recorder = getattr(self, "action_set_recorder", None)
        record_decision = getattr(recorder, "record_decision", None)
        if engine is None or player is None or not callable(record_decision):
            return
        actions = [
            _action_set_aux_choice_action(action_kind, choice, payload_extra=payload_extra, engine=engine)
            for _breakdown, _tie_breaker, choice, _features in scored_choices
        ]
        selected_slot = next(
            (index for index, action in enumerate(actions) if scored_choices[index][2] is selected_choice),
            None,
        )
        if selected_slot is None:
            selected_slot = next(
                (index for index, action in enumerate(actions) if scored_choices[index][2] == selected_choice),
                None,
            )
        if selected_slot is None:
            return
        teacher_scores = [float(breakdown.get("total", 0.0) or 0.0) for breakdown, *_rest in scored_choices]
        record_decision(
            engine,
            player,
            actions,
            teacher_scores=teacher_scores,
            selected_action_slot=int(selected_slot),
            decision_kind=_action_set_aux_decision_kind(action_kind),
            raw_scores=list(teacher_scores),
            metadata={
                "policyClass": self.__class__.__name__,
                "teacherScoreMode": "aux_runtime_total",
                "auxActionKind": str(action_kind),
            },
        )

    def _lookahead_delta(
            self,
            engine: Any,
            player: Any,
            action: Action,
            features: dict[str, float] | None = None,
            include_transition_evaluator: bool = True,
    ) -> float:
        self._last_transition_evaluator_delta = 0.0
        if self.lookahead_depth > 1 and (
            not self.lookahead_key_decisions_only
            or self._is_deep_lookahead_key_decision(features or {}, action)
        ):
            return self._multi_step_lookahead_delta(
                engine,
                player,
                action,
                include_transition_evaluator=include_transition_evaluator,
            )
        return self._one_step_lookahead_delta(
            engine,
            player,
            action,
            include_transition_evaluator=include_transition_evaluator,
        )

    def _is_deep_lookahead_key_decision(self, features: dict[str, float], action: Action) -> bool:
        key_flags = (
            "attack_exposes_lethal_next_turn",
            "attack_while_low_life_no_forces",
            "attack_has_lethal_player_target",
            "attack_can_destroy_force",
            "attack_zero_dp_without_attack_payoff",
            "attack_suicide_into_larger_blocker_without_pressure",
            "play_card_target_effect",
            "play_card_defensive_reactive_effect",
            "block_none_allows_lethal_player_damage",
            "decision:blocker",
        )
        if any(float(features.get(key, 0.0)) > 0.0 for key in key_flags):
            return True
        for key, value in features.items():
            if float(value) <= 0.0:
                continue
            if key.startswith("play_card_harmful_") or key.startswith("play_card_beneficial_"):
                return True
        return action.kind in {"activate_flash_ability"}

    def _transition_evaluator_key_decision(self, action: Action, features: dict[str, float]) -> bool:
        if self._is_deep_lookahead_key_decision(features, action):
            return True
        key_flags = (
            "enemy_pressure_high_player_risk",
            "enemy_pressure_near_player_lethal",
            "move_field_to_base_under_enemy_pressure",
            "play_card_defensive_reactive_effect",
            "play_card_rest_lockdown_enemy_ready_targets",
            "block_none_allows_lethal_player_damage",
        )
        return (
            any(float(features.get(key, 0.0) or 0.0) > 0.0 for key in key_flags)
            or (
                action.kind == "play_card"
                and float(features.get("play_card_effect:move_to_base_rested", 0.0) or 0.0) > 0.0
            )
        )

    def transition_evaluator_runtime_stats(self) -> dict[str, int | float]:
        return {
            "transitionEvaluatorCalls": int(self._transition_evaluator_call_count),
            "transitionEvaluatorDecisions": int(self._transition_evaluator_decision_count),
            "transitionEvaluatorAppliedDecisions": int(self._transition_evaluator_applied_decision_count),
            "transitionEvaluatorAbstentions": int(self._transition_evaluator_abstention_count),
            "transitionEvaluatorChoiceChanges": int(self._transition_evaluator_choice_change_count),
            "transitionEvaluatorRawSpreadSum": float(self._transition_evaluator_raw_spread_sum),
            "transitionEvaluatorFeatureNoveltyAbstentionCalls": int(
                self._transition_evaluator_feature_novelty_abstention_call_count
            ),
            "transitionEvaluatorAllNoveltyDecisions": int(
                self._transition_evaluator_all_novelty_decision_count
            ),
            "transitionEvaluatorUnknownFeatureCounts": dict(sorted(
                self._transition_evaluator_unknown_feature_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )),
            "transitionEvaluatorNoChangeMarginCount": int(self._transition_evaluator_no_change_margin_count),
            "transitionEvaluatorNoChangeBaselineMarginSum": float(
                self._transition_evaluator_no_change_baseline_margin_sum
            ),
            "transitionEvaluatorNoChangeFinalMarginSum": float(
                self._transition_evaluator_no_change_final_margin_sum
            ),
        }

    def _position_value(self, engine: Any, player: Any) -> float:
        value: float | None = None
        if self.use_state_value_head and hasattr(self.model, "state_value_many"):
            try:
                state_features = self.extractor.features_for_state(engine, player)
                if not _state_value_leaf_context_allowed(
                    state_features,
                    focus=self.state_value_leaf_runtime_focus,
                ):
                    value = self.position_evaluator.evaluate(engine, player)
                else:
                    value = float(self.model.state_value_many([state_features])[0])
            except Exception:
                pass
        if value is None:
            value = self.position_evaluator.evaluate(engine, player)
        if (
            self.survival_pressure_evaluator_weight > 0.0
            and self._survival_pressure_context(engine, player)
        ):
            try:
                value += (
                    self.survival_pressure_evaluator_weight
                    * self.position_evaluator.survival_pressure_value(engine, player)
                )
            except Exception:
                pass
        return value

    def _survival_pressure_context(self, engine: Any, player: Any) -> bool:
        state = getattr(engine, "state", None)
        phase = getattr(state, "phase", None)
        if phase is None:
            return True
        if getattr(state, "active", None) is not player:
            return True
        phase_value = str(getattr(phase, "value", phase)).lower()
        return phase_value not in {"standby", "mana", "main"}

    def _transition_evaluator_delta(
        self,
        before_engine: Any,
        before_player: Any,
        action: Action,
        after_engine: Any,
        after_player: Any,
        *,
        include_rollout_features: bool | None = None,
    ) -> float:
        self._last_transition_evaluator_novelty_abstained = False
        if self.transition_evaluator_weight <= 0.0 or self.transition_evaluator is None:
            self._last_transition_evaluator_delta = 0.0
            return 0.0
        try:
            from zz.counterfactual_transition import runtime_action_transition_feature_row

            observed_restore = self._temporarily_enable_transition_evaluator_observed_features(
                before_engine,
                after_engine,
            )
            use_rollout_features = (
                self._transition_evaluator_uses_rollout_features()
                if include_rollout_features is None
                else bool(include_rollout_features)
            )
            transition_features = runtime_action_transition_feature_row(
                extractor=self.extractor,
                before_engine=before_engine,
                before_player=before_player,
                action=action,
                after_engine=after_engine,
                after_player=after_player,
                horizon_actions=self.transition_evaluator_max_actions,
                horizon_turns=self.transition_evaluator_horizon_turns,
                clone_after_engine=False,
                include_rollout_features=use_rollout_features,
            )
            novelty_reporter = getattr(self.transition_evaluator, "feature_novelty_report", None)
            if callable(novelty_reporter):
                novelty_report = dict(novelty_reporter(transition_features) or {})
                if bool(novelty_report.get("abstained", False)):
                    self._last_transition_evaluator_novelty_abstained = True
                    self._transition_evaluator_feature_novelty_abstention_call_count += 1
                    for key in novelty_report.get("unknownFeatureKeys") or []:
                        feature_key = str(key)
                        self._transition_evaluator_unknown_feature_counts[feature_key] = (
                            int(self._transition_evaluator_unknown_feature_counts.get(feature_key, 0)) + 1
                        )
            with self._profile_span("transition_evaluator"):
                raw_score = float(self.transition_evaluator.score_transition(transition_features))
            self._transition_evaluator_call_count += 1
            self._transition_evaluator_decision_call_count += 1
            weighted = float(self.transition_evaluator_weight) * raw_score
            self._last_transition_evaluator_delta = weighted
            return weighted
        except Exception:
            self._last_transition_evaluator_delta = 0.0
            self._last_transition_evaluator_novelty_abstained = False
            return 0.0
        finally:
            for target, had_attr, previous in locals().get("observed_restore", []):
                if had_attr:
                    setattr(target, "enable_observed_opponent_features", previous)
                elif hasattr(target, "enable_observed_opponent_features"):
                    delattr(target, "enable_observed_opponent_features")

    def _transition_evaluator_uses_rollout_features(self) -> bool:
        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        if "usesRolloutFeatures" in metadata:
            return bool(metadata.get("usesRolloutFeatures"))
        feature_version = str(metadata.get("featureVersion", ""))
        if "predictive_no_rollout" in feature_version:
            return False
        return True

    def _transition_evaluator_uses_observed_opponent_features(self) -> bool:
        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        return bool(metadata.get("usesObservedOpponentFeatures"))

    def _enable_transition_evaluator_observed_opponent_features(self, engine: Any) -> None:
        if self._transition_evaluator_uses_observed_opponent_features():
            setattr(engine, "enable_observed_opponent_features", True)

    def _temporarily_enable_transition_evaluator_observed_features(self, *engines: Any) -> list[tuple[Any, bool, Any]]:
        if not self._transition_evaluator_uses_observed_opponent_features():
            return []
        restore: list[tuple[Any, bool, Any]] = []
        seen: set[int] = set()
        for engine in engines:
            if engine is None or id(engine) in seen:
                continue
            seen.add(id(engine))
            had_attr = hasattr(engine, "enable_observed_opponent_features")
            previous = getattr(engine, "enable_observed_opponent_features", None)
            setattr(engine, "enable_observed_opponent_features", True)
            restore.append((engine, had_attr, previous))
        return restore

    def _transition_evaluator_minimum_decision_spread(self) -> float:
        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        raw_threshold = float(metadata.get("minimumDecisionRawSpread", 0.0) or 0.0)
        return raw_threshold * max(0.0, float(self.transition_evaluator_weight))

    def _transition_evaluator_candidate_ineligible(
        self,
        scored_choice_drafts: list[tuple[Any, ...]],
        *,
        selected_index_without_transition: int,
        candidate_index: int,
        score_without_transition_by_index: dict[int, float],
        predicted_score_by_index: dict[int, float],
    ) -> bool:
        if int(candidate_index) == int(selected_index_without_transition):
            return False
        draft_by_index = {
            int(item[8]): item
            for item in scored_choice_drafts
        }
        baseline_draft = draft_by_index.get(int(selected_index_without_transition))
        selected_draft = draft_by_index.get(int(candidate_index))
        if baseline_draft is None or selected_draft is None:
            return False

        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        baseline_action = baseline_draft[2]
        baseline_features = baseline_draft[3]
        selected_action = selected_draft[2]
        selected_features = selected_draft[3]
        final_margin = (
            float(predicted_score_by_index.get(int(candidate_index), 0.0))
            - float(predicted_score_by_index.get(int(selected_index_without_transition), 0.0))
        )

        if metadata.get("protectFullChimeraColorFix", True) is not False:
            if self._transition_evaluator_full_chimera_colorless_fix_features(baseline_features):
                other_base_scores = [
                    score
                    for index, score in score_without_transition_by_index.items()
                    if int(index) != int(selected_index_without_transition)
                ]
                baseline_margin = (
                    float(score_without_transition_by_index[int(selected_index_without_transition)])
                    - max(float(score) for score in other_base_scores)
                    if other_base_scores
                    else 0.0
                )
                min_margin = max(
                    0.0,
                    float(metadata.get("protectFullChimeraColorFixMinBaselineMargin", 1.0) or 0.0),
                )
                if (
                    baseline_margin >= min_margin
                    and not self._transition_evaluator_full_chimera_colorless_fix_features(selected_features)
                ):
                    return True

        if (
            metadata.get("protectBaselineConstrainedEligibility", True) is not False
            and self._action_baseline_constrained_regression(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                selected_action=selected_action,
                selected_features=selected_features,
            )
        ):
            return True

        if self._action_safety_negative_conflict(
            baseline_action=baseline_action,
            baseline_features=baseline_features,
            selected_action=selected_action,
            selected_features=selected_features,
        ):
            return True

        raw_margin = (
            float(score_without_transition_by_index.get(int(candidate_index), 0.0))
            - float(score_without_transition_by_index.get(int(selected_index_without_transition), 0.0))
        )
        if metadata.get("protectNegativeRawMarginReversal", True) is not False:
            min_raw_margin = max(
                0.0,
                float(metadata.get("protectNegativeRawMarginMinDelta", 1e-6) or 0.0),
            )
            if (
                raw_margin < -min_raw_margin
                and final_margin > 0.0
                and not self._transition_evaluator_selected_has_immediate_payoff_proof(
                    selected_action,
                    selected_features,
                )
            ):
                strong_passive_raw_margin = max(
                    0.0,
                    float(metadata.get("protectNegativeRawMarginStrongPassiveMinDelta", 2.0) or 0.0),
                )
                if (
                    selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
                    and raw_margin <= -strong_passive_raw_margin
                ):
                    return True
                if self._transition_evaluator_useful_development_or_resource_action(
                    baseline_action,
                    baseline_features,
                ):
                    if selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}:
                        return True
                    if (
                        selected_action.kind == "place_colorless_mana"
                        and _safe_float(selected_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
                    ):
                        return True

        if metadata.get("protectSameKindLowRawQualityOverride", True) is not False:
            min_raw_margin = max(
                0.0,
                float(metadata.get("protectSameKindLowRawQualityMinDelta", 1e-6) or 0.0),
            )
            if (
                selected_action.kind == baseline_action.kind
                and dict(selected_action.payload) != dict(baseline_action.payload)
                and raw_margin < -min_raw_margin
                and final_margin > 0.0
                and not self._transition_evaluator_selected_has_immediate_payoff_proof(
                    selected_action,
                    selected_features,
                )
            ):
                return True

        return False

    def _transition_evaluator_abstains_for_protected_chimera_color_fix(
        self,
        scored_choice_drafts: list[tuple[Any, ...]],
        *,
        selected_index_without_transition: int,
        score_without_transition_by_index: dict[int, float],
        tie_breaker_by_index: dict[int, float],
        transition_center: float,
    ) -> bool:
        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        if metadata.get("protectFullChimeraColorFix", True) is False:
            return False
        draft_by_index = {
            int(item[8]): item
            for item in scored_choice_drafts
        }
        baseline_draft = draft_by_index.get(int(selected_index_without_transition))
        if baseline_draft is None:
            return False
        if not self._transition_evaluator_full_chimera_colorless_fix_features(baseline_draft[3]):
            return False
        other_base_scores = [
            score
            for index, score in score_without_transition_by_index.items()
            if int(index) != int(selected_index_without_transition)
        ]
        if not other_base_scores:
            return False
        baseline_margin = (
            float(score_without_transition_by_index[int(selected_index_without_transition)])
            - max(float(score) for score in other_base_scores)
        )
        min_margin = max(
            0.0,
            float(metadata.get("protectFullChimeraColorFixMinBaselineMargin", 1.0) or 0.0),
        )
        if baseline_margin < min_margin:
            return False
        predicted_score_by_index = {
            int(item[8]): (
                float(score_without_transition_by_index[int(item[8])])
                + (
                    float(item[4]) - float(transition_center)
                    if bool(item[5])
                    else 0.0
                )
            )
            for item in scored_choice_drafts
        }
        selected_index_with_transition = max(
            predicted_score_by_index,
            key=lambda index: (
                predicted_score_by_index[index],
                tie_breaker_by_index.get(index, 0.0),
            ),
        )
        if int(selected_index_with_transition) == int(selected_index_without_transition):
            return False
        selected_draft = draft_by_index.get(int(selected_index_with_transition))
        if selected_draft is None:
            return False
        return not self._transition_evaluator_full_chimera_colorless_fix_features(selected_draft[3])

    def _transition_evaluator_abstains_for_immediate_safety_conflict(
        self,
        scored_choice_drafts: list[tuple[Any, ...]],
        *,
        selected_index_without_transition: int,
        score_without_transition_by_index: dict[int, float],
        tie_breaker_by_index: dict[int, float],
        transition_center: float,
    ) -> bool:
        draft_by_index = {
            int(item[8]): item
            for item in scored_choice_drafts
        }
        baseline_draft = draft_by_index.get(int(selected_index_without_transition))
        if baseline_draft is None:
            return False
        predicted_score_by_index = {
            int(item[8]): (
                float(score_without_transition_by_index[int(item[8])])
                + (
                    float(item[4]) - float(transition_center)
                    if bool(item[5])
                    else 0.0
                )
            )
            for item in scored_choice_drafts
        }
        selected_index_with_transition = max(
            predicted_score_by_index,
            key=lambda index: (
                predicted_score_by_index[index],
                tie_breaker_by_index.get(index, 0.0),
            ),
        )
        if int(selected_index_with_transition) == int(selected_index_without_transition):
            return False
        selected_draft = draft_by_index.get(int(selected_index_with_transition))
        if selected_draft is None:
            return False
        return self._action_safety_negative_conflict(
            baseline_action=baseline_draft[2],
            baseline_features=baseline_draft[3],
            selected_action=selected_draft[2],
            selected_features=selected_draft[3],
        )

    def _transition_evaluator_abstains_for_baseline_constrained_regression(
        self,
        scored_choice_drafts: list[tuple[Any, ...]],
        *,
        selected_index_without_transition: int,
        score_without_transition_by_index: dict[int, float],
        tie_breaker_by_index: dict[int, float],
        transition_center: float,
    ) -> bool:
        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        if metadata.get("protectBaselineConstrainedEligibility", True) is False:
            return False
        draft_by_index = {
            int(item[8]): item
            for item in scored_choice_drafts
        }
        baseline_draft = draft_by_index.get(int(selected_index_without_transition))
        if baseline_draft is None:
            return False
        predicted_score_by_index = {
            int(item[8]): (
                float(score_without_transition_by_index[int(item[8])])
                + (
                    float(item[4]) - float(transition_center)
                    if bool(item[5])
                    else 0.0
                )
            )
            for item in scored_choice_drafts
        }
        selected_index_with_transition = max(
            predicted_score_by_index,
            key=lambda index: (
                predicted_score_by_index[index],
                tie_breaker_by_index.get(index, 0.0),
            ),
        )
        if int(selected_index_with_transition) == int(selected_index_without_transition):
            return False
        selected_draft = draft_by_index.get(int(selected_index_with_transition))
        if selected_draft is None:
            return False
        return self._action_baseline_constrained_regression(
            baseline_action=baseline_draft[2],
            baseline_features=baseline_draft[3],
            selected_action=selected_draft[2],
            selected_features=selected_draft[3],
        )

    def _transition_evaluator_abstains_for_negative_raw_margin_reversal(
        self,
        scored_choice_drafts: list[tuple[Any, ...]],
        *,
        selected_index_without_transition: int,
        score_without_transition_by_index: dict[int, float],
        tie_breaker_by_index: dict[int, float],
        transition_center: float,
    ) -> bool:
        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        if metadata.get("protectNegativeRawMarginReversal", True) is False:
            return False
        draft_by_index = {
            int(item[8]): item
            for item in scored_choice_drafts
        }
        baseline_draft = draft_by_index.get(int(selected_index_without_transition))
        if baseline_draft is None:
            return False
        predicted_score_by_index = {
            int(item[8]): (
                float(score_without_transition_by_index[int(item[8])])
                + (
                    float(item[4]) - float(transition_center)
                    if bool(item[5])
                    else 0.0
                )
            )
            for item in scored_choice_drafts
        }
        selected_index_with_transition = max(
            predicted_score_by_index,
            key=lambda index: (
                predicted_score_by_index[index],
                tie_breaker_by_index.get(index, 0.0),
            ),
        )
        if int(selected_index_with_transition) == int(selected_index_without_transition):
            return False
        selected_draft = draft_by_index.get(int(selected_index_with_transition))
        if selected_draft is None:
            return False

        raw_margin = (
            float(score_without_transition_by_index[int(selected_index_with_transition)])
            - float(score_without_transition_by_index[int(selected_index_without_transition)])
        )
        final_margin = (
            float(predicted_score_by_index[int(selected_index_with_transition)])
            - float(predicted_score_by_index[int(selected_index_without_transition)])
        )
        min_raw_margin = max(
            0.0,
            float(metadata.get("protectNegativeRawMarginMinDelta", 1e-6) or 0.0),
        )
        if raw_margin >= -min_raw_margin or final_margin <= 0.0:
            return False

        baseline_action = baseline_draft[2]
        baseline_features = baseline_draft[3]
        selected_action = selected_draft[2]
        selected_features = selected_draft[3]
        if self._transition_evaluator_selected_has_immediate_payoff_proof(
            selected_action,
            selected_features,
        ):
            return False
        strong_passive_raw_margin = max(
            0.0,
            float(metadata.get("protectNegativeRawMarginStrongPassiveMinDelta", 2.0) or 0.0),
        )
        if (
            selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and raw_margin <= -strong_passive_raw_margin
        ):
            return True
        if not self._transition_evaluator_useful_development_or_resource_action(
            baseline_action,
            baseline_features,
        ):
            return False
        if selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}:
            return True
        return (
            selected_action.kind == "place_colorless_mana"
            and _safe_float(selected_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
        )

    def _transition_evaluator_abstains_for_same_kind_low_raw_quality_override(
        self,
        scored_choice_drafts: list[tuple[Any, ...]],
        *,
        selected_index_without_transition: int,
        score_without_transition_by_index: dict[int, float],
        tie_breaker_by_index: dict[int, float],
        transition_center: float,
    ) -> bool:
        metadata = dict(getattr(self.transition_evaluator, "metadata", {}) or {})
        if metadata.get("protectSameKindLowRawQualityOverride", True) is False:
            return False
        draft_by_index = {
            int(item[8]): item
            for item in scored_choice_drafts
        }
        baseline_draft = draft_by_index.get(int(selected_index_without_transition))
        if baseline_draft is None:
            return False
        predicted_score_by_index = {
            int(item[8]): (
                float(score_without_transition_by_index[int(item[8])])
                + (
                    float(item[4]) - float(transition_center)
                    if bool(item[5])
                    else 0.0
                )
            )
            for item in scored_choice_drafts
        }
        selected_index_with_transition = max(
            predicted_score_by_index,
            key=lambda index: (
                predicted_score_by_index[index],
                tie_breaker_by_index.get(index, 0.0),
            ),
        )
        if int(selected_index_with_transition) == int(selected_index_without_transition):
            return False
        selected_draft = draft_by_index.get(int(selected_index_with_transition))
        if selected_draft is None:
            return False

        baseline_action = baseline_draft[2]
        selected_action = selected_draft[2]
        if selected_action.kind != baseline_action.kind:
            return False
        if dict(selected_action.payload) == dict(baseline_action.payload):
            return False
        raw_margin = (
            float(score_without_transition_by_index[int(selected_index_with_transition)])
            - float(score_without_transition_by_index[int(selected_index_without_transition)])
        )
        final_margin = (
            float(predicted_score_by_index[int(selected_index_with_transition)])
            - float(predicted_score_by_index[int(selected_index_without_transition)])
        )
        min_raw_margin = max(
            0.0,
            float(metadata.get("protectSameKindLowRawQualityMinDelta", 1e-6) or 0.0),
        )
        if raw_margin >= -min_raw_margin or final_margin <= 0.0:
            return False
        return not self._transition_evaluator_selected_has_immediate_payoff_proof(
            selected_action,
            selected_draft[3],
        )

    @staticmethod
    def _transition_evaluator_full_chimera_colorless_fix_features(features: dict[str, float]) -> bool:
        return (
            _safe_float(features.get("place_colorless_mana_supports_chimera_color_fix")) > 0.0
            and _safe_float(features.get("place_colorless_mana_ignores_missing_hand_color")) <= 0.0
        )

    @staticmethod
    def _transition_evaluator_selected_has_immediate_payoff_proof(
        action: Action,
        features: dict[str, float],
    ) -> bool:
        if (
            action.kind == "place_colorless_mana"
            and _safe_float(features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
        ):
            return False
        return LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(features)

    @staticmethod
    def _transition_evaluator_useful_development_or_resource_action(
        action: Action,
        features: dict[str, float],
    ) -> bool:
        if LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(features):
            return True
        if action.kind in {"play_to_base", "place_colorless_mana", "swap_mana_color"}:
            return True
        if action.kind == "play_card":
            useful_play_keys = (
                "play_card_effect:draw_cards",
                "play_card_profile_role:draw",
                "play_card_rest_lockdown_enemy_ready_targets",
                "play_card_force_life_exchange_search_support",
                "play_card_force_life_exchange_search_for_deck_piece",
                "play_card_base_search_support",
            )
            if any(_safe_float(features.get(key)) > 0.0 for key in useful_play_keys):
                return True
            return (
                LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(features, "play_card_beneficial_")
                or LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(features, "play_card_effect:")
            )
        if action.kind == "move_card":
            return (
                _safe_float(features.get("move_field_to_base")) > 0.0
                and (
                    _safe_float(features.get("move_field_to_base_future_play")) > 0.0
                    or _safe_float(features.get("move_field_to_base_builds_mana")) > 0.0
                    or _safe_float(features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
                    or _safe_float(features.get("move_field_to_base_under_enemy_pressure")) > 0.0
                )
            )
        return any(
            _safe_float(value) > 0.0
            for key, value in features.items()
            if str(key).startswith("semantic_action_resource:")
        )

    def bounded_mcts_planner_runtime_stats(self) -> dict[str, int | float]:
        return {
            "boundedMctsPlannerDecisions": int(self._bounded_mcts_planner_decision_count),
            "boundedMctsPlannerChoiceChanges": int(self._bounded_mcts_planner_choice_change_count),
            "boundedMctsPlannerSimulations": int(self._bounded_mcts_planner_simulation_count),
            "boundedMctsPlannerFallbacks": int(self._bounded_mcts_planner_fallback_count),
        }

    def _apply_bounded_mcts_planner(
        self,
        *,
        engine: Any,
        player: Any,
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
    ) -> None:
        if (
            not self.bounded_mcts_planner_enabled
            or self.bounded_mcts_planner_simulations <= 0
            or self.bounded_mcts_planner_value_weight == 0.0
            or len(scored_choices) < 2
            or (self.epsilon > 0.0 and self.rng.random() < self.epsilon)
        ):
            return
        try:
            baseline_index = max(
                range(len(scored_choices)),
                key=lambda index: (scored_choices[index][0]["total"], scored_choices[index][1]),
            )
            candidate_indexes = self._bounded_mcts_planner_candidate_indexes(
                scored_choices,
                baseline_index=baseline_index,
            )
            hard_excluded_indexes: set[int] = set()
            if self.bounded_mcts_planner_primary_decision_path:
                candidate_indexes, hard_excluded_indexes = (
                    self._bounded_mcts_planner_primary_candidate_indexes(
                        scored_choices,
                        baseline_index=baseline_index,
                        candidate_indexes=candidate_indexes,
                    )
                )
            if len(candidate_indexes) < 2:
                return
            if self.bounded_mcts_planner_key_decisions_only and not any(
                self._bounded_mcts_planner_key_decision(scored_choices[index][2], scored_choices[index][3])
                for index in candidate_indexes
            ):
                return

            raw_priors: dict[int, float] = {}
            max_score = max(float(scored_choices[index][0]["total"]) for index in candidate_indexes)
            for index in candidate_indexes:
                breakdown, _, action, features = scored_choices[index]
                score_prior = math.exp(max(-8.0, min(8.0, float(breakdown["total"]) - max_score)))
                concept_prior = max(0.0, self._bounded_mcts_planner_concept_prior(action, features))
                raw_priors[index] = max(0.01, score_prior + concept_prior)
            prior_total = sum(raw_priors.values()) or 1.0
            priors = {index: raw_priors[index] / prior_total for index in candidate_indexes}
            visits = {index: 0 for index in candidate_indexes}
            value_sums = {index: 0.0 for index in candidate_indexes}
            value_cache: dict[int, float] = {}
            simulations = max(
                int(self.bounded_mcts_planner_simulations),
                len(candidate_indexes),
                1,
            )
            for _ in range(simulations):
                total_visits = sum(visits.values())
                unvisited = [index for index in candidate_indexes if visits[index] <= 0]
                if unvisited:
                    selected_index = max(unvisited, key=lambda index: priors[index])
                else:
                    selected_index = max(
                        candidate_indexes,
                        key=lambda index: (
                            (
                                value_sums[index] / visits[index]
                                if visits[index] > 0
                                else 0.0
                            )
                            + self.bounded_mcts_planner_cpuct
                            * priors[index]
                            * math.sqrt(float(total_visits + 1))
                            / float(visits[index] + 1),
                            priors[index],
                        ),
                    )
                if selected_index not in value_cache:
                    _, _, action, features = scored_choices[selected_index]
                    value_cache[selected_index] = self._bounded_mcts_planner_action_value(
                        engine,
                        player,
                        action,
                        features,
                    )
                visits[selected_index] += 1
                value_sums[selected_index] += value_cache[selected_index]

            for index, (breakdown, _tie_breaker, _action, _features) in enumerate(scored_choices):
                baseline_negative = bool(
                    index == baseline_index
                    and self._bounded_mcts_planner_negative_or_no_effect_baseline(_features)
                )
                if index not in candidate_indexes:
                    breakdown["boundedMctsPlannerCandidate"] = 0.0
                    breakdown["boundedMctsPlannerPrior"] = 0.0
                    breakdown["boundedMctsPlannerVisits"] = 0.0
                    breakdown["boundedMctsPlannerQ"] = 0.0
                    breakdown["boundedMctsPlanner"] = 0.0
                    breakdown["boundedMctsPlannerBaselineSelected"] = (
                        1.0 if index == baseline_index else 0.0
                    )
                    breakdown["boundedMctsPlannerSelected"] = 0.0
                    breakdown["boundedMctsPlannerAbstained"] = 0.0
                    breakdown["boundedMctsPlannerIneligible"] = 0.0
                    breakdown["boundedMctsPlannerHardExcluded"] = (
                        1.0 if index in hard_excluded_indexes else 0.0
                    )
                    breakdown["boundedMctsPlannerBaselineNegative"] = 1.0 if baseline_negative else 0.0
                    breakdown["boundedMctsPlannerPrimaryPath"] = (
                        1.0 if self.bounded_mcts_planner_primary_decision_path else 0.0
                    )
                    continue
                q_value = (
                    value_sums[index] / visits[index]
                    if visits[index] > 0
                    else value_cache.get(index, 0.0)
                )
                planner_score = self.bounded_mcts_planner_value_weight * float(q_value)
                breakdown["boundedMctsPlannerCandidate"] = 1.0
                breakdown["boundedMctsPlannerPrior"] = float(priors[index])
                breakdown["boundedMctsPlannerVisits"] = float(visits[index])
                breakdown["boundedMctsPlannerQ"] = float(q_value)
                breakdown["boundedMctsPlanner"] = float(planner_score)
                breakdown["boundedMctsPlannerBaselineSelected"] = 1.0 if index == baseline_index else 0.0
                breakdown["boundedMctsPlannerSelected"] = 0.0
                breakdown["boundedMctsPlannerAbstained"] = 0.0
                breakdown["boundedMctsPlannerIneligible"] = 0.0
                breakdown["boundedMctsPlannerHardExcluded"] = 0.0
                breakdown["boundedMctsPlannerBaselineNegative"] = 1.0 if baseline_negative else 0.0
                breakdown["boundedMctsPlannerPrimaryPath"] = (
                    1.0 if self.bounded_mcts_planner_primary_decision_path else 0.0
                )
                breakdown["total"] = float(breakdown["total"]) + float(planner_score)

            if self.bounded_mcts_planner_primary_decision_path:
                ranked_planner_indexes = sorted(
                    candidate_indexes,
                    key=lambda index: (
                        self._bounded_mcts_planner_primary_reasonable_tie_rank(
                            scored_choices,
                            baseline_index=baseline_index,
                            candidate_index=index,
                        ),
                        float(scored_choices[index][0].get("boundedMctsPlannerQ", 0.0)),
                        float(scored_choices[index][0].get("boundedMctsPlannerVisits", 0.0)),
                        float(scored_choices[index][0].get("boundedMctsPlannerPrior", 0.0)),
                        scored_choices[index][1],
                    ),
                    reverse=True,
                )
            else:
                ranked_planner_indexes = sorted(
                    range(len(scored_choices)),
                    key=lambda index: (scored_choices[index][0]["total"], scored_choices[index][1]),
                    reverse=True,
                )
            ineligible_planner_indexes: set[int] = set()
            selected_index = baseline_index
            baseline_is_negative_or_no_effect = (
                self.bounded_mcts_planner_primary_decision_path
                and self._bounded_mcts_planner_negative_or_no_effect_baseline(
                    scored_choices[baseline_index][3]
                )
            )
            for candidate_index in ranked_planner_indexes:
                if (
                    baseline_is_negative_or_no_effect
                    and int(candidate_index) == int(baseline_index)
                    and len(ranked_planner_indexes) > 1
                ):
                    ineligible_planner_indexes.add(int(candidate_index))
                    scored_choices[candidate_index][0][
                        "boundedMctsPlannerIneligibleReason:negative_baseline_wait_for_escape"
                    ] = 1.0
                    continue
                ineligible_reason = self._bounded_mcts_planner_candidate_ineligible_reason(
                    scored_choices,
                    baseline_index=baseline_index,
                    candidate_index=candidate_index,
                    primary_decision_path=self.bounded_mcts_planner_primary_decision_path,
                    value_source=self.bounded_mcts_planner_value_source,
                )
                if ineligible_reason:
                    ineligible_planner_indexes.add(int(candidate_index))
                    scored_choices[candidate_index][0][
                        f"boundedMctsPlannerIneligibleReason:{ineligible_reason}"
                    ] = 1.0
                    continue
                selected_index = int(candidate_index)
                break

            raw_planner_top_index = int(ranked_planner_indexes[0]) if ranked_planner_indexes else baseline_index
            planner_abstained = bool(
                selected_index == baseline_index
                and raw_planner_top_index in ineligible_planner_indexes
            )
            if planner_abstained:
                for breakdown, _tie_breaker, _action, _features in scored_choices:
                    planner_score = float(breakdown.get("boundedMctsPlanner", 0.0))
                    if planner_score:
                        breakdown["total"] = float(breakdown["total"]) - planner_score
                    breakdown["boundedMctsPlannerAbstained"] = 1.0
                    breakdown["boundedMctsPlanner"] = 0.0
                    breakdown["boundedMctsPlannerIneligible"] = 0.0
                selected_index = baseline_index
            else:
                for index in ineligible_planner_indexes:
                    breakdown = scored_choices[index][0]
                    planner_score = float(breakdown.get("boundedMctsPlanner", 0.0))
                    if planner_score:
                        breakdown["total"] = float(breakdown["total"]) - planner_score
                    breakdown["boundedMctsPlanner"] = 0.0
                    breakdown["boundedMctsPlannerIneligible"] = 1.0
                if not self.bounded_mcts_planner_primary_decision_path:
                    selected_index = max(
                        [
                            index
                            for index in range(len(scored_choices))
                            if index not in ineligible_planner_indexes
                        ] or [baseline_index],
                        key=lambda index: (scored_choices[index][0]["total"], scored_choices[index][1]),
                    )
            if (
                self.bounded_mcts_planner_primary_decision_path
                and selected_index != baseline_index
                and float(scored_choices[selected_index][0].get("total", 0.0))
                < float(scored_choices[baseline_index][0].get("total", 0.0)) - 1.0e-9
                and float(scored_choices[selected_index][0].get("boundedMctsPlannerQ", 0.0))
                <= float(scored_choices[baseline_index][0].get("boundedMctsPlannerQ", 0.0)) + 1.0e-9
                and not (
                    _safe_float(
                        scored_choices[baseline_index][3].get("negative_no_effect_resource_spend")
                    )
                    > 0.0
                    and self._bounded_mcts_planner_selected_has_major_immediate_payoff(
                        scored_choices[selected_index][3]
                    )
                )
                and not (
                    self._bounded_mcts_planner_negative_or_no_effect_baseline(
                        scored_choices[baseline_index][3]
                    )
                    and scored_choices[selected_index][2].kind in {"skip_mana", "end_turn", "flash_pass"}
                    and float(scored_choices[selected_index][0].get("boundedMctsPlannerQ", 0.0))
                    >= -1.0e-9
                )
                and not self._bounded_mcts_planner_primary_semantic_override_allowed(
                    scored_choices,
                    baseline_index=baseline_index,
                    candidate_index=selected_index,
                    comparison_index=baseline_index,
                )
            ):
                breakdown = scored_choices[selected_index][0]
                planner_score = float(breakdown.get("boundedMctsPlanner", 0.0))
                if planner_score:
                    breakdown["total"] = float(breakdown["total"]) - planner_score
                breakdown["boundedMctsPlanner"] = 0.0
                breakdown["boundedMctsPlannerIneligible"] = 1.0
                breakdown["boundedMctsPlannerIneligibleReason:primary_lower_total_nonimproving_q"] = 1.0
                selected_index = baseline_index
            best_total_eligible_indexes = [
                index
                for index, (breakdown, _tie_breaker, action, features) in enumerate(scored_choices)
                if index not in hard_excluded_indexes
                and index not in ineligible_planner_indexes
                and _safe_float(breakdown.get("boundedMctsPlannerHardExcluded")) <= 0.0
                and _safe_float(breakdown.get("boundedMctsPlannerIneligible")) <= 0.0
                and _safe_float(breakdown.get("transitionEvaluatorIneligible")) <= 0.0
                and (
                    index == baseline_index
                    or not self._bounded_mcts_planner_hard_excluded_root_candidate(action, features)
                )
            ] or [baseline_index]
            best_total_index = max(
                best_total_eligible_indexes,
                key=lambda index: (scored_choices[index][0]["total"], scored_choices[index][1]),
            )
            if (
                self.bounded_mcts_planner_primary_decision_path
                and selected_index != best_total_index
                and float(scored_choices[selected_index][0].get("total", 0.0))
                < float(scored_choices[best_total_index][0].get("total", 0.0)) - 1.0e-9
                and float(scored_choices[selected_index][0].get("boundedMctsPlannerQ", 0.0))
                <= float(scored_choices[best_total_index][0].get("boundedMctsPlannerQ", 0.0)) + 1.0e-9
                and not (
                    _safe_float(
                        scored_choices[best_total_index][3].get("negative_no_effect_resource_spend")
                    )
                    > 0.0
                    and self._bounded_mcts_planner_selected_has_major_immediate_payoff(
                        scored_choices[selected_index][3]
                    )
                )
                and not (
                    self._bounded_mcts_planner_negative_or_no_effect_baseline(
                        scored_choices[best_total_index][3]
                    )
                    and scored_choices[selected_index][2].kind in {"skip_mana", "end_turn", "flash_pass"}
                    and float(scored_choices[selected_index][0].get("boundedMctsPlannerQ", 0.0))
                    >= -1.0e-9
                )
                and not self._bounded_mcts_planner_primary_semantic_override_allowed(
                    scored_choices,
                    baseline_index=baseline_index,
                    candidate_index=selected_index,
                    comparison_index=best_total_index,
                )
            ):
                breakdown = scored_choices[selected_index][0]
                planner_score = float(breakdown.get("boundedMctsPlanner", 0.0))
                if planner_score:
                    breakdown["total"] = float(breakdown["total"]) - planner_score
                breakdown["boundedMctsPlanner"] = 0.0
                breakdown["boundedMctsPlannerIneligible"] = 1.0
                breakdown["boundedMctsPlannerIneligibleReason:primary_lower_total_lower_q_than_best_total"] = 1.0
                selected_index = best_total_index
            scored_choices[selected_index][0]["boundedMctsPlannerSelected"] = 1.0
            self._bounded_mcts_planner_decision_count += 1
            self._bounded_mcts_planner_simulation_count += simulations
            if selected_index != baseline_index:
                self._bounded_mcts_planner_choice_change_count += 1
        except Exception:
            self._bounded_mcts_planner_fallback_count += 1

    def _bounded_mcts_planner_candidate_indexes(
        self,
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        baseline_index: int,
    ) -> list[int]:
        root_width = min(len(scored_choices), max(1, int(self.bounded_mcts_planner_root_width)))
        ordered: list[int] = []

        def add(index: int) -> None:
            if index not in ordered and len(ordered) < root_width:
                ordered.append(index)

        def add_essential(index: int) -> None:
            if index not in ordered:
                ordered.append(index)

        add_essential(baseline_index)
        if self._bounded_mcts_planner_negative_or_no_effect_baseline(
            scored_choices[baseline_index][3]
        ):
            for index, (_breakdown, _tie_breaker, action, _features) in enumerate(scored_choices):
                if action.kind in {"end_turn", "skip_mana", "flash_pass"}:
                    add_essential(index)
        concept_order = sorted(
            range(len(scored_choices)),
            key=lambda index: (
                self._bounded_mcts_planner_concept_prior(scored_choices[index][2], scored_choices[index][3]),
                scored_choices[index][0]["total"],
                scored_choices[index][1],
            ),
            reverse=True,
        )
        for index in concept_order:
            if self._bounded_mcts_planner_key_decision(scored_choices[index][2], scored_choices[index][3]):
                add(index)
        score_order = sorted(
            range(len(scored_choices)),
            key=lambda index: (scored_choices[index][0]["total"], scored_choices[index][1]),
            reverse=True,
        )
        for index in score_order:
            add(index)
        return ordered

    def _bounded_mcts_planner_primary_candidate_indexes(
        self,
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        baseline_index: int,
        candidate_indexes: list[int],
    ) -> tuple[list[int], set[int]]:
        hard_excluded = {
            int(index)
            for index in candidate_indexes
            if int(index) != int(baseline_index)
            and self._bounded_mcts_planner_hard_excluded_root_candidate(
                scored_choices[index][2],
                scored_choices[index][3],
            )
        }
        filtered = [index for index in candidate_indexes if index not in hard_excluded]
        return filtered, hard_excluded

    def _bounded_mcts_planner_key_decision(self, action: Action, features: dict[str, float]) -> bool:
        if self._transition_evaluator_key_decision(action, features):
            return True
        if action.kind == "place_colorless_mana":
            return True
        if (
            _safe_float(features.get("play_to_base_restores_missing_hand_color")) > 0.0
            or _safe_float(features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
            or _safe_float(features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
            or any(
                _safe_float(value) > 0.0
                for key, value in features.items()
                if str(key).startswith("semantic_action_resource:")
            )
        ):
            return True
        return self._bounded_mcts_planner_concept_prior(action, features) != 0.0

    def _bounded_mcts_planner_concept_prior(self, action: Action, features: dict[str, float]) -> float:
        score = 0.0
        rested_play_to_base = LookaheadRLPolicy._bounded_mcts_planner_rested_play_to_base_effect(features)
        rested_field_to_base = LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_effect(features)
        rested_play_to_base_no_bonus_keys = {
            "play_card_move_to_base_restores_missing_hand_color",
            "play_card_move_to_base_restores_missing_unfixable_hand_color",
            "play_card_move_to_base_matches_unfixable_hand_color",
            "semantic_action_resource:base_development",
            "semantic_action_resource:repair_missing_color",
        }
        rested_field_to_base_no_bonus_keys = {
            "move_field_to_base_matches_hand_color",
            "move_field_to_base_restores_missing_hand_color",
            "move_field_to_base_enables_playable_hand_card",
            "semantic_action_resource:base_development",
            "semantic_action_resource:repair_missing_color",
        }
        for key, value in features.items():
            if _safe_float(value) <= 0.0:
                continue
            if key.startswith("positive_"):
                score += 1.0
            elif key.startswith("negative_"):
                score -= 1.0
            elif key == "attack_can_destroy_force":
                if _attack_has_reliable_force_break(features):
                    score += 0.75
            elif key == "attack_force_break_unreliable_under_enemy_pressure":
                score -= 0.75
            elif key in {
                "attack_has_lethal_player_target",
                "attack_with_reawaken_self_refresh",
                "attack_with_turn_end_minion_refresh",
            }:
                score += 0.75
            elif key == "place_colorless_mana_supports_chimera_color_fix":
                if LookaheadRLPolicy._transition_evaluator_full_chimera_colorless_fix_features(features):
                    score += 0.75
            elif key in {
                "attack_exposes_lethal_next_turn",
                "block_none_allows_lethal_player_damage",
                "place_colorless_mana_ignores_missing_hand_color",
            }:
                score -= 0.75
            elif key in {
                "play_to_base_restores_missing_hand_color",
                "play_to_base_restores_missing_unfixable_hand_color",
                "play_card_move_to_base_restores_missing_hand_color",
                "play_card_move_to_base_restores_missing_unfixable_hand_color",
                "move_field_to_base_restores_missing_hand_color",
                "move_field_to_base_enables_playable_hand_card",
                "semantic_action_resource:base_development",
                "semantic_action_resource:repair_missing_color",
            }:
                if not (
                    (rested_play_to_base and key in rested_play_to_base_no_bonus_keys)
                    or (rested_field_to_base and key in rested_field_to_base_no_bonus_keys)
                ):
                    score += 0.75
            elif key in {
                "move_field_to_base_matches_hand_color",
                "move_field_to_base_protects_high_value_attacker",
            }:
                if not (rested_field_to_base and key in rested_field_to_base_no_bonus_keys):
                    score += 0.35
            elif (
                key == "play_card_effect:move_to_base_rested"
                and _safe_float(features.get("action:play_card")) > 0.0
            ):
                continue
            elif (
                key == "play_card_effect:summon_from_trash"
                and _safe_float(features.get("action:play_card")) > 0.0
            ):
                score += 0.75
            elif (
                key == "play_card_effect:destroy_targets"
                and (
                    _safe_float(features.get("play_card_profile_role:death_payoff")) > 0.0
                    or _safe_float(features.get("play_card_semantic_role:death_payoff")) > 0.0
                )
            ):
                score += 0.5
            elif key in {
                "play_card_summon_from_trash_own_target_available",
                "positive_reanimate_from_trash",
                "positive_self_destroy_death_payoff",
            }:
                score += 1.0
            elif key in {
                "play_card_profile_role:trash_recursion",
                "play_card_semantic_role:trash_recursion",
                "play_card_profile_role:death_payoff",
                "play_card_semantic_role:death_payoff",
                "move_card_profile_role:death_payoff",
                "move_card_semantic_role:death_payoff",
                "target_has_on_destroy_effect",
                "target_own_revival_candidate",
            }:
                score += 0.5
            elif key in {
                "play_card_base_search_support",
                "play_card_force_life_exchange_search_support",
                "play_card_force_life_exchange_search_for_deck_piece",
            }:
                score += 0.35
            elif key in {
                "play_card_profile_risk:target_value_sensitive",
                "play_card_semantic_risk:target_value_sensitive",
                "play_card_profile_risk:zero_dp_attacker",
                "play_card_semantic_risk:zero_dp_attacker",
                "play_card_profile_zone:usually_should_not_attack",
                "play_card_semantic_zone:usually_should_not_attack",
            }:
                score -= 0.6
            elif key.startswith("play_card_beneficial_"):
                score += 0.35
            elif key.startswith("play_card_harmful_"):
                score -= 0.35
        if action.kind in {"activate_flash_ability"}:
            score += 0.25
        if LookaheadRLPolicy._bounded_mcts_planner_overextended_combo_attack_under_pressure(features):
            score -= 2.0
        return score

    @staticmethod
    def _bounded_mcts_planner_hard_excluded_root_candidate(
        action: Action,
        features: dict[str, float],
    ) -> bool:
        if action.kind == "skip_mana" and (
            _safe_float(features.get("skip_mana_under_base_cap")) > 0.0
            or (
                "own_base_count" in features
                and _safe_float(features.get("own_base_count")) < 1.0 - 1e-9
            )
        ):
            return True
        if LookaheadRLPolicy._bounded_mcts_planner_risky_zero_target_search(features):
            return True
        if (
            action.kind == "attack"
            and _safe_float(features.get("attack_has_lethal_player_target")) <= 0.0
            and LookaheadRLPolicy._action_has_safety_negative(features)
        ):
            return True
        if LookaheadRLPolicy._bounded_mcts_planner_overextended_combo_attack_under_pressure(features):
            return True
        if LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(features):
            return False
        if LookaheadRLPolicy._action_has_safety_negative(features):
            return True
        if (
            LookaheadRLPolicy._fragile_base_to_field_no_payoff(features)
            or LookaheadRLPolicy._unproductive_base_to_field_resource_spend(features)
        ):
            return True
        if _safe_float(features.get("negative_no_effect_resource_spend")) > 0.0:
            return True
        if (
            action.kind == "place_colorless_mana"
            and _safe_float(features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
        ):
            return True
        return False

    @staticmethod
    def _bounded_mcts_planner_candidate_ineligible(
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        baseline_index: int,
        candidate_index: int,
        primary_decision_path: bool = False,
        value_source: str = "hybrid",
    ) -> bool:
        return bool(LookaheadRLPolicy._bounded_mcts_planner_candidate_ineligible_reason(
            scored_choices,
            baseline_index=baseline_index,
            candidate_index=candidate_index,
            primary_decision_path=primary_decision_path,
            value_source=value_source,
        ))

    @staticmethod
    def _bounded_mcts_planner_candidate_ineligible_reason(
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        baseline_index: int,
        candidate_index: int,
        primary_decision_path: bool = False,
        value_source: str = "hybrid",
    ) -> str:
        if int(candidate_index) == int(baseline_index):
            return ""
        baseline_action = scored_choices[baseline_index][2]
        baseline_features = scored_choices[baseline_index][3]
        baseline_breakdown = scored_choices[baseline_index][0]
        selected_action = scored_choices[candidate_index][2]
        selected_features = scored_choices[candidate_index][3]
        selected_breakdown = scored_choices[candidate_index][0]
        selected_q_value = _safe_float(selected_breakdown.get("boundedMctsPlannerQ"))
        baseline_q_value = _safe_float(baseline_breakdown.get("boundedMctsPlannerQ"))
        selected_total = _safe_float(selected_breakdown.get("total"))
        baseline_total = _safe_float(baseline_breakdown.get("total"))
        learned_q_score_leads = (
            str(value_source or "hybrid").strip().lower().replace("-", "_")
            in {"transition_evaluator", "transition", "transition_value", "learned_transition_value"}
            and selected_q_value > baseline_q_value + 1.0e-9
        )
        strong_learned_q_margin = (
            learned_q_score_leads
            and selected_q_value >= baseline_q_value + 2.5
        )
        learned_q_has_semantic_proof = (
            LookaheadRLPolicy._bounded_mcts_planner_learned_q_override_has_semantic_proof(
                selected_action,
                selected_features,
            )
        )
        learned_q_semantic_proof_can_supersede = learned_q_has_semantic_proof
        if (
            learned_q_has_semantic_proof
            and LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(baseline_features)
            and not LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(selected_features)
        ):
            learned_q_semantic_proof_can_supersede = False
        if (
            learned_q_semantic_proof_can_supersede
            and LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(baseline_features)
            and LookaheadRLPolicy._bounded_mcts_planner_combo_setup_without_decisive_removal(
                selected_features
            )
            and not LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_can_supersede(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                candidate_action=selected_action,
                candidate_features=selected_features,
            )
        ):
            learned_q_semantic_proof_can_supersede = False
        learned_q_has_preservation_proof = (
            learned_q_score_leads
            and strong_learned_q_margin
            and LookaheadRLPolicy._bounded_mcts_planner_learned_q_preservation_override_allowed(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                selected_action=selected_action,
                selected_features=selected_features,
            )
        )
        passive_escape_from_negative_baseline = (
            LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(
                baseline_features
            )
            and selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and selected_q_value >= -1.0e-9
        )
        learned_q_override_proven = (
            learned_q_semantic_proof_can_supersede
            or learned_q_has_preservation_proof
        )
        learned_q_improvement = (
            learned_q_score_leads
            and learned_q_override_proven
            and (
                selected_total >= baseline_total - 1.0e-9
                or strong_learned_q_margin
            )
        )
        if (
            primary_decision_path
            and baseline_action.kind == "play_card"
            and selected_action.kind == "move_card"
            and _safe_float(baseline_features.get("play_card_effect:summon_from_trash")) > 0.0
            and _safe_float(baseline_features.get("play_card_summon_from_trash_no_own_target")) > 0.0
            and _safe_float(baseline_features.get("positive_reanimate_from_trash")) <= 0.0
            and _safe_float(selected_features.get("move_base_to_field")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_own_revival_candidate")) > 0.0
            and not LookaheadRLPolicy._action_has_safety_negative(selected_features)
            and selected_q_value >= baseline_q_value + 1.0
        ):
            return ""
        if (
            primary_decision_path
            and LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(baseline_features)
            and LookaheadRLPolicy._bounded_mcts_planner_combo_setup_without_decisive_removal(
                selected_features
            )
        ):
            return "unproven_primary_replacement"
        if (
            primary_decision_path
            and LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_decisive_payoff(
                baseline_features
            )
            and selected_action.kind == "attack"
            and LookaheadRLPolicy._bounded_mcts_planner_immediate_force_break_payoff(
                selected_features
            )
            and _safe_float(selected_features.get("attack_has_lethal_player_target")) <= 0.0
        ):
            return "unproven_primary_replacement"
        if (
            primary_decision_path
            and LookaheadRLPolicy._bounded_mcts_planner_immediate_force_break_payoff(
                baseline_features
            )
            and not LookaheadRLPolicy._bounded_mcts_planner_immediate_force_break_payoff(
                selected_features
            )
            and not LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(
                selected_features
            )
            and not LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_decisive_payoff(
                selected_features
            )
            and _safe_float(selected_features.get("attack_has_lethal_player_target")) <= 0.0
            and _safe_float(selected_features.get("move_base_to_field_immediate_player_lethal_payoff")) <= 0.0
        ):
            return "unproven_primary_replacement"
        if (
            primary_decision_path
            and LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_future_resource_line(
                baseline_features
            )
            and _safe_float(selected_features.get("attack_has_lethal_player_target")) <= 0.0
            and _safe_float(selected_features.get("move_base_to_field_immediate_player_lethal_payoff")) <= 0.0
            and not LookaheadRLPolicy._bounded_mcts_planner_immediate_force_break_payoff(
                selected_features
            )
            and not LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(
                selected_features
            )
        ):
            return "unproven_primary_replacement"
        if (
            primary_decision_path
            and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(
                baseline_features
            )
            and selected_total < baseline_total - 1.0e-9
            and not learned_q_improvement
            and not LookaheadRLPolicy._bounded_mcts_planner_primary_semantic_override_allowed(
                scored_choices,
                baseline_index=baseline_index,
                candidate_index=candidate_index,
                comparison_index=baseline_index,
            )
        ):
            return "primary_lower_total_nonnegative_baseline"
        if (
            primary_decision_path
            and selected_total < baseline_total - 1.0e-9
            and selected_q_value <= baseline_q_value + 1.0e-9
            and not learned_q_improvement
            and not (
                _safe_float(baseline_features.get("negative_no_effect_resource_spend")) > 0.0
                and LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(
                    selected_features
                )
            )
            and not (
                passive_escape_from_negative_baseline
            )
            and not LookaheadRLPolicy._bounded_mcts_planner_primary_semantic_override_allowed(
                scored_choices,
                baseline_index=baseline_index,
                candidate_index=candidate_index,
                comparison_index=baseline_index,
            )
        ):
            return "primary_lower_total_nonimproving_q"
        if (
            primary_decision_path
            and LookaheadRLPolicy._bounded_mcts_planner_abstains_for_no_target_reanimate_over_pressure_blocker(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                selected_action=selected_action,
                selected_features=selected_features,
            )
        ):
            return "no_target_reanimate_over_pressure_blocker"
        if (
            primary_decision_path
            and learned_q_score_leads
            and not learned_q_override_proven
            and not (
                LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(
                    baseline_features
                )
                and selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            )
            and not LookaheadRLPolicy._bounded_mcts_planner_primary_semantic_override_allowed(
                scored_choices,
                baseline_index=baseline_index,
                candidate_index=candidate_index,
                comparison_index=baseline_index,
            )
        ):
            return "unproven_primary_replacement"
        checks = (
            (
                "low_force_nonlethal_attack",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_low_force_nonlethal_attack,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                },
            ),
            (
                "low_plan_resource_shift",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_low_plan_resource_shift,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                },
            ),
            (
                "low_raw_plan_override",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_low_raw_plan_override,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "baseline_breakdown": baseline_breakdown,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                    "selected_breakdown": selected_breakdown,
                },
            ),
            (
                "safety_negative_conflict",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_safety_negative_conflict,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                },
            ),
            (
                "baseline_constrained_regression",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_baseline_constrained_regression,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "baseline_breakdown": baseline_breakdown,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                    "selected_breakdown": selected_breakdown,
                },
            ),
            (
                "no_target_reanimate_over_pressure_blocker",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_no_target_reanimate_over_pressure_blocker,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                },
            ),
            (
                "full_chimera_colorless_replacement",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_full_chimera_colorless_replacement,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                },
            ),
            (
                "immediate_payoff_regression",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_immediate_payoff_regression,
                {
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "baseline_breakdown": baseline_breakdown,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                    "selected_breakdown": selected_breakdown,
                },
            ),
            (
                "unproven_primary_replacement",
                LookaheadRLPolicy._bounded_mcts_planner_abstains_for_unproven_primary_replacement,
                {
                    "primary_decision_path": primary_decision_path,
                    "baseline_action": baseline_action,
                    "baseline_features": baseline_features,
                    "baseline_breakdown": baseline_breakdown,
                    "selected_action": selected_action,
                    "selected_features": selected_features,
                    "selected_breakdown": selected_breakdown,
                    "value_source": value_source,
                },
            ),
        )
        for reason, predicate, kwargs in checks:
            if (
                (learned_q_improvement or passive_escape_from_negative_baseline)
                and reason in {
                    "baseline_constrained_regression",
                    "unproven_primary_replacement",
                    "immediate_payoff_regression",
                }
            ):
                continue
            if predicate(**kwargs):
                return reason
        return ""

    @staticmethod
    def _bounded_mcts_planner_negative_or_no_effect_baseline(features: dict[str, float]) -> bool:
        if LookaheadRLPolicy._bounded_mcts_planner_risky_zero_target_search(features):
            return True
        if LookaheadRLPolicy._bounded_mcts_planner_force_conditioned_resource_line(features):
            return False
        if LookaheadRLPolicy._action_has_safety_negative(features):
            return True
        if LookaheadRLPolicy._bounded_mcts_planner_overextended_combo_attack_under_pressure(features):
            return True
        if LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(features):
            return False
        if LookaheadRLPolicy._bounded_mcts_planner_reactive_removal_timing_delta(features) <= -7.0:
            return True
        return (
            _safe_float(features.get("negative_no_effect_resource_spend")) > 0.0
            or LookaheadRLPolicy._play_card_no_target_reanimate_empty_payoff(features)
            or _safe_float(features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
            or LookaheadRLPolicy._fragile_base_to_field_no_payoff(features)
            or LookaheadRLPolicy._unproductive_base_to_field_resource_spend(features)
        )

    @staticmethod
    def _play_card_no_target_reanimate_empty_payoff(features: dict[str, float]) -> bool:
        no_target_reanimate = (
            _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
            and _safe_float(features.get("play_card_summon_from_trash_no_own_target")) > 0.0
            and _safe_float(features.get("positive_reanimate_from_trash")) <= 0.0
        )
        if not no_target_reanimate:
            return False
        independent_positive = any(
            str(key).startswith("positive_")
            and str(key) != "positive_reanimate_from_trash"
            and _safe_float(value) > 0.0
            for key, value in features.items()
        )
        return not independent_positive

    @staticmethod
    def _bounded_mcts_planner_force_conditioned_resource_line(features: dict[str, float]) -> bool:
        if _safe_float(features.get("move_field_to_base")) <= 0.0:
            return False
        if LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_effect(features):
            return False
        resource_payoff = (
            _safe_float(features.get("semantic_action_resource:repair_missing_color")) > 0.0
            or _safe_float(features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
            or _safe_float(features.get("move_field_to_base_matches_hand_color")) > 0.0
            or _safe_float(features.get("move_field_to_base_enables_playable_hand_card")) > 0.0
            or _safe_float(features.get("move_field_to_base_future_play")) > 0.0
            or _safe_float(features.get("move_field_to_base_builds_mana")) > 0.0
        )
        if not resource_payoff:
            return False
        force_context = (
            _safe_float(features.get("own_forces_alive", 1.0)) <= 0.5
            or _safe_float(features.get("own_force_life_total", 1.0)) <= 0.2
            or _safe_float(features.get("own_lowest_force_life", 1.0)) <= 0.2
            or any(
                _safe_float(value) > 0.0
                for key, value in features.items()
                if str(key).startswith("own_force_combo:")
            )
        )
        resource_pressure = (
            _safe_float(features.get("own_no_ready_colored_mana_for_hand")) > 0.0
            or any(
                _safe_float(value) > 0.0
                for key, value in features.items()
                if str(key).startswith("own_hand_demand_color:")
                and not str(key).endswith(":colorless")
            )
        )
        plan_context = (
            _safe_float(features.get("own_deck_plan:base_growth")) > 0.0
            or _safe_float(features.get("own_deck_semantic_plan:base_growth")) > 0.0
            or _safe_float(features.get("own_deck_plan:stabilize")) > 0.0
            or _safe_float(features.get("own_deck_semantic_plan:stabilize")) > 0.0
        )
        return bool(force_context and resource_pressure and plan_context)

    @staticmethod
    def _bounded_mcts_planner_risky_zero_target_search(features: dict[str, float]) -> bool:
        if _safe_float(features.get("action:play_card")) <= 0.0:
            return False
        if (
            _safe_float(features.get("play_card_effect:place_base_from_hand")) > 0.0
            or _safe_float(features.get("play_card_place_base_from_hand_support")) > 0.0
            or _safe_float(features.get("play_card_base_search_support")) > 0.0
            or _safe_float(features.get("play_card_force_life_exchange_search_support")) > 0.0
            or _safe_float(features.get("play_card_force_life_exchange_search_for_deck_piece")) > 0.0
        ):
            return False
        target_sensitive = (
            _safe_float(features.get("play_card_profile_risk:target_value_sensitive")) > 0.0
            or _safe_float(features.get("play_card_semantic_risk:target_value_sensitive")) > 0.0
        )
        zero_dp_or_bad_zone = (
            _safe_float(features.get("play_card_profile_risk:zero_dp_attacker")) > 0.0
            or _safe_float(features.get("play_card_semantic_risk:zero_dp_attacker")) > 0.0
            or _safe_float(features.get("play_card_profile_zone:usually_should_not_attack")) > 0.0
            or _safe_float(features.get("play_card_semantic_zone:usually_should_not_attack")) > 0.0
        )
        can_choose_zero_targets = (
            _safe_float(features.get("play_card_profile_target:can_choose_zero_targets")) > 0.0
            or _safe_float(features.get("play_card_semantic_target:can_choose_zero_targets")) > 0.0
        )
        return bool(target_sensitive and zero_dp_or_bad_zone and can_choose_zero_targets)

    @staticmethod
    def _bounded_mcts_planner_primary_reasonable_tie_rank(
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        baseline_index: int,
        candidate_index: int,
    ) -> float:
        baseline_features = scored_choices[baseline_index][3]
        baseline_action = scored_choices[baseline_index][2]
        candidate_action = scored_choices[candidate_index][2]
        candidate_features = scored_choices[candidate_index][3]
        if int(candidate_index) != int(baseline_index):
            baseline_q = _safe_float(scored_choices[baseline_index][0].get("boundedMctsPlannerQ"))
            candidate_q = _safe_float(scored_choices[candidate_index][0].get("boundedMctsPlannerQ"))
            baseline_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
                baseline_features
            )
            candidate_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
                candidate_features
            )
            baseline_positive = LookaheadRLPolicy._action_immediate_positive_labels(baseline_features)
            candidate_positive = LookaheadRLPolicy._action_immediate_positive_labels(candidate_features)
            candidate_trash_pressure_blocker = (
                LookaheadRLPolicy._bounded_mcts_planner_trash_recursion_pressure_blocker_score(
                    candidate_features
                )
            )
            if candidate_trash_pressure_blocker >= 2.0:
                return 3.0 + candidate_trash_pressure_blocker
            if (
                baseline_combo_priority > 0.0
                and "positive_kill_enemy_minion" in candidate_positive
                and candidate_q >= baseline_q + 2.5
            ):
                return 1.5 + min(3.0, candidate_q - baseline_q)
            if (
                candidate_combo_priority > baseline_combo_priority + 0.5
                and not (
                    "positive_kill_enemy_minion" in baseline_positive
                    and baseline_q >= candidate_q + 2.5
                )
                and (
                    LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_concrete_payoff(
                        candidate_features
                    )
                    or candidate_q >= baseline_q + 0.5
                )
                and LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_can_supersede(
                    baseline_action=baseline_action,
                    baseline_features=baseline_features,
                    candidate_action=candidate_action,
                    candidate_features=candidate_features,
                )
            ):
                return 2.0 + min(4.0, candidate_combo_priority - baseline_combo_priority)
            if (
                baseline_action.kind == "place_colorless_mana"
                and candidate_action.kind == "play_to_base"
                and _safe_float(baseline_features.get("place_colorless_mana_supports_chimera_color_fix")) > 0.0
                and _safe_float(candidate_features.get("action:play_to_base")) > 0.0
            ):
                if _safe_float(baseline_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0:
                    return 2.0
                if (
                    _safe_float(candidate_features.get("semantic_action_resource:repair_missing_color")) > 0.0
                    or _safe_float(candidate_features.get("play_to_base_restores_missing_hand_color")) > 0.0
                    or _safe_float(candidate_features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
                ):
                    return 1.0
                return 0.0
        baseline_is_negative = LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(
            baseline_features
        )
        if not baseline_is_negative:
            return 0.0
        if int(candidate_index) == int(baseline_index):
            return -1.0
        candidate_q = _safe_float(scored_choices[candidate_index][0].get("boundedMctsPlannerQ"))
        baseline_q = _safe_float(scored_choices[baseline_index][0].get("boundedMctsPlannerQ"))
        if (
            candidate_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and candidate_q >= baseline_q - 0.5
        ):
            return 0.5
        if LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(candidate_features):
            return 1.0 + max(
                0.0,
                LookaheadRLPolicy._bounded_mcts_planner_concept_prior_static(candidate_features),
            )
        return 0.0

    @staticmethod
    def _bounded_mcts_planner_primary_semantic_override_allowed(
        scored_choices: list[tuple[dict[str, float], float, Any, dict[str, float]]],
        *,
        baseline_index: int,
        candidate_index: int,
        comparison_index: int,
    ) -> bool:
        if int(candidate_index) == int(comparison_index):
            return False
        baseline_action = scored_choices[baseline_index][2]
        candidate_action = scored_choices[candidate_index][2]
        candidate_features = scored_choices[candidate_index][3]
        comparison_action = scored_choices[comparison_index][2]
        comparison_features = scored_choices[comparison_index][3]
        candidate_q = _safe_float(scored_choices[candidate_index][0].get("boundedMctsPlannerQ"))
        comparison_q = _safe_float(scored_choices[comparison_index][0].get("boundedMctsPlannerQ"))
        if LookaheadRLPolicy._bounded_mcts_planner_primary_resource_override_allowed(
            baseline_action=baseline_action,
            baseline_features=scored_choices[baseline_index][3],
            comparison_action=comparison_action,
            comparison_features=comparison_features,
            candidate_action=candidate_action,
            candidate_features=candidate_features,
            candidate_q=candidate_q,
            comparison_q=comparison_q,
        ):
            return True
        candidate_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
            candidate_features
        )
        comparison_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
            comparison_features
        )
        candidate_trash_pressure_blocker = (
            LookaheadRLPolicy._bounded_mcts_planner_trash_recursion_pressure_blocker_score(
                candidate_features
            )
        )
        if (
            candidate_trash_pressure_blocker < 2.0
            and candidate_combo_priority <= comparison_combo_priority + 0.5
        ):
            return False
        if not (
            candidate_trash_pressure_blocker >= 2.0
            or LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_concrete_payoff(
                candidate_features
            )
            or candidate_q >= comparison_q + 0.5
        ):
            return False
        if not LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_can_supersede(
            baseline_action=comparison_action,
            baseline_features=comparison_features,
            candidate_action=candidate_action,
            candidate_features=candidate_features,
        ):
            return False
        if (
            baseline_action.kind == "attack"
            and comparison_action.kind == "attack"
            and comparison_index == baseline_index
            and _safe_float(comparison_features.get("attack_has_lethal_player_target")) > 0.0
        ):
            return False
        return True

    @staticmethod
    def _bounded_mcts_planner_primary_resource_override_allowed(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        comparison_action: Action,
        comparison_features: dict[str, float],
        candidate_action: Action,
        candidate_features: dict[str, float],
        candidate_q: float,
        comparison_q: float,
    ) -> bool:
        candidate_is_revival_base_to_field = (
            candidate_action.kind == "move_card"
            and _safe_float(candidate_features.get("move_base_to_field")) > 0.0
            and _safe_float(candidate_features.get("move_base_to_field_own_revival_candidate")) > 0.0
        )
        comparison_is_no_target_reanimate = (
            comparison_action.kind == "play_card"
            and _safe_float(comparison_features.get("play_card_effect:summon_from_trash")) > 0.0
            and _safe_float(comparison_features.get("play_card_summon_from_trash_no_own_target")) > 0.0
            and _safe_float(comparison_features.get("positive_reanimate_from_trash")) <= 0.0
        )
        if (
            candidate_is_revival_base_to_field
            and comparison_is_no_target_reanimate
            and candidate_q >= comparison_q + 1.0
        ):
            return True
        if _safe_float(candidate_features.get("negative_no_effect_resource_spend")) > 0.0:
            return False
        if _safe_float(candidate_features.get("negative_exposes_lethal_or_bad_trade")) > 0.0:
            return False
        comparison_has_decisive_payoff = (
            _safe_float(comparison_features.get("attack_has_lethal_player_target")) > 0.0
            or _safe_float(comparison_features.get("positive_kill_enemy_minion")) > 0.0
            or _safe_float(comparison_features.get("play_card_beneficial_destroy_enemy_minion")) > 0.0
            or _safe_float(comparison_features.get("play_card_beneficial_remove_threat")) > 0.0
        )
        if comparison_has_decisive_payoff:
            return False
        candidate_rested_play_to_base = (
            LookaheadRLPolicy._bounded_mcts_planner_rested_play_to_base_effect(candidate_features)
        )
        candidate_rested_field_to_base = (
            LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_effect(candidate_features)
        )
        candidate_repairs_missing_color = (
            (
                not candidate_rested_play_to_base
                and _safe_float(candidate_features.get("semantic_action_resource:repair_missing_color")) > 0.0
            )
            or _safe_float(candidate_features.get("play_to_base_restores_missing_hand_color")) > 0.0
            or _safe_float(candidate_features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
            or (
                not candidate_rested_play_to_base
                and _safe_float(candidate_features.get("play_card_move_to_base_restores_missing_hand_color")) > 0.0
            )
            or (
                not candidate_rested_play_to_base
                and _safe_float(candidate_features.get("play_card_move_to_base_restores_missing_unfixable_hand_color")) > 0.0
            )
            or (
                not candidate_rested_field_to_base
                and _safe_float(candidate_features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
            )
            or (
                not candidate_rested_field_to_base
                and _safe_float(candidate_features.get("move_field_to_base_enables_playable_hand_card")) > 0.0
            )
        )
        comparison_is_colorless_chimera = (
            comparison_action.kind == "place_colorless_mana"
            and _safe_float(comparison_features.get("place_colorless_mana_supports_chimera_color_fix")) > 0.0
        )
        if candidate_action.kind == "play_to_base" and comparison_is_colorless_chimera:
            if (
                candidate_repairs_missing_color
                and _safe_float(comparison_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
            ):
                return True
            tree_proves_base_growth = (
                _safe_float(candidate_features.get("semantic_action_resource:base_development")) > 0.0
                and _safe_float(candidate_features.get("own_base_count")) <= 0.2
                and (
                    _safe_float(candidate_features.get("semantic_action_plan:base_growth")) > 0.0
                    or _safe_float(candidate_features.get("own_deck_plan:base_growth")) > 0.0
                    or _safe_float(candidate_features.get("own_deck_semantic_plan:base_growth")) > 0.0
                )
                and candidate_q >= comparison_q + 0.05
            )
            if tree_proves_base_growth:
                return True
        if candidate_action.kind == "play_card":
            candidate_is_resource_play = (
                candidate_repairs_missing_color
                or (
                    not candidate_rested_play_to_base
                    and _safe_float(candidate_features.get("semantic_action_resource:base_development")) > 0.0
                )
            )
            comparison_is_setup_play = (
                comparison_action.kind == "play_card"
                and (
                    _safe_float(comparison_features.get("play_card_base_search_support")) > 0.0
                    or _safe_float(comparison_features.get("play_card_force_life_exchange_search_support")) > 0.0
                    or _safe_float(comparison_features.get("play_card_force_life_exchange_search_for_deck_piece")) > 0.0
                    or _safe_float(comparison_features.get("play_card_effect:search_deck_to_hand")) > 0.0
                )
            )
            if candidate_is_resource_play and comparison_is_setup_play and candidate_q >= comparison_q + 1.0:
                return True
        if candidate_action.kind == "move_card":
            candidate_is_field_to_base_repair = (
                _safe_float(candidate_features.get("move_field_to_base")) > 0.0
                and not candidate_rested_field_to_base
                and (
                    candidate_repairs_missing_color
                    or _safe_float(candidate_features.get("move_field_to_base_matches_hand_color")) > 0.0
                    or _safe_float(candidate_features.get("move_field_to_base_builds_mana")) > 0.0
                    or _safe_float(candidate_features.get("move_field_to_base_future_play")) > 0.0
                )
            )
            if candidate_is_field_to_base_repair and candidate_q >= comparison_q + 0.5:
                if baseline_action.kind == "attack" and _safe_float(baseline_features.get("attack_has_lethal_player_target")) > 0.0:
                    return False
                return True
        return False

    @staticmethod
    def _bounded_mcts_planner_combo_asset_priority(features: dict[str, float]) -> float:
        score = 0.0
        play_card = _safe_float(features.get("action:play_card")) > 0.0
        move_card = _safe_float(features.get("action:move_card")) > 0.0
        if play_card:
            trash_pressure_blocker_score = (
                LookaheadRLPolicy._bounded_mcts_planner_trash_recursion_pressure_blocker_score(
                    features
                )
            )
            if _safe_float(features.get("positive_reanimate_from_trash")) > 0.0:
                if (
                    trash_pressure_blocker_score > 0.0
                    and _safe_float(features.get("play_card_field_minion_bp")) < 6.0
                    and _safe_float(features.get("play_card_field_minion_dp")) <= 2.0
                ):
                    score += max(1.0, trash_pressure_blocker_score)
                else:
                    score += 3.0
            elif (
                _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
                and _safe_float(features.get("play_card_summon_from_trash_own_target_available")) > 0.0
            ):
                if (
                    trash_pressure_blocker_score > 0.0
                    and _safe_float(features.get("play_card_field_minion_bp")) < 6.0
                    and _safe_float(features.get("play_card_field_minion_dp")) <= 2.0
                ):
                    score += max(1.0, trash_pressure_blocker_score)
                else:
                    score += 2.0
            elif _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0:
                score += 0.8 + trash_pressure_blocker_score
            play_card_death_payoff = (
                _safe_float(features.get("play_card_profile_role:death_payoff")) > 0.0
                or _safe_float(features.get("play_card_semantic_role:death_payoff")) > 0.0
            )
            if play_card_death_payoff:
                score += 1.5
                if _safe_float(features.get("play_card_effect:destroy_targets")) > 0.0:
                    score += 1.0
            if (
                _safe_float(features.get("positive_self_destroy_death_payoff")) > 0.0
                or _safe_float(features.get("target_has_on_destroy_effect")) > 0.0
                or _safe_float(features.get("target_own_revival_candidate")) > 0.0
            ):
                score += 2.0
        if move_card:
            if (
                _safe_float(features.get("move_card_profile_role:death_payoff")) > 0.0
                or _safe_float(features.get("move_card_semantic_role:death_payoff")) > 0.0
            ):
                score += 1.5
                if _safe_float(features.get("move_field_to_base")) > 0.0:
                    score += 0.5
        if _safe_float(features.get("negative_no_effect_resource_spend")) > 0.0:
            score -= 3.0
        return max(0.0, min(6.0, score))

    @staticmethod
    def _bounded_mcts_planner_trash_recursion_pressure_blocker_score(features: dict[str, float]) -> float:
        if _safe_float(features.get("action:play_card")) <= 0.0:
            return 0.0
        if _safe_float(features.get("play_card_effect:summon_from_trash")) <= 0.0:
            return 0.0
        if (
            _safe_float(features.get("play_card_adds_blocker_under_pressure")) <= 0.0
            and _safe_float(features.get("positive_add_blocker_under_pressure")) <= 0.0
        ):
            return 0.0
        pressure = (
            _safe_float(features.get("enemy_pressure_high_player_risk")) > 0.0
            or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0.0
            or _safe_float(features.get("enemy_field_dp_pressure")) >= 0.5
        )
        low_force_stability = (
            _safe_float(features.get("own_force_life_total", 1.0)) <= 0.25
            or _safe_float(features.get("own_lowest_force_life", 1.0)) <= 0.20
        )
        if not pressure or not low_force_stability:
            return 0.0
        bp = _safe_float(features.get("play_card_field_minion_bp"))
        dp = _safe_float(features.get("play_card_field_minion_dp"))
        score = 0.0
        if bp >= 7.0:
            score += 2.0
        elif bp >= 6.0:
            score += 1.25
        elif bp >= 5.0:
            score += 0.5
        if dp >= 2.0:
            score += 0.5
        return max(0.0, min(2.5, score))

    @staticmethod
    def _bounded_mcts_planner_combo_candidate_has_concrete_payoff(features: dict[str, float]) -> bool:
        if LookaheadRLPolicy._bounded_mcts_planner_reanimate_replaces_combo_asset_without_net_payoff(
            features
        ):
            return False
        if (
            _safe_float(features.get("positive_reanimate_from_trash")) > 0.0
            or _safe_float(features.get("positive_self_destroy_death_payoff")) > 0.0
            or _safe_float(features.get("target_has_on_destroy_effect")) > 0.0
            or _safe_float(features.get("target_own_revival_candidate")) > 0.0
            or _safe_float(features.get("positive_add_blocker_under_pressure")) > 0.0
            or _safe_float(features.get("positive_kill_enemy_minion")) > 0.0
        ):
            return True
        return (
            LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(features, "play_card_beneficial_")
            or LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(features, "move_card_beneficial_")
        )

    @staticmethod
    def _bounded_mcts_planner_reanimate_replaces_combo_asset_without_net_payoff(
        features: dict[str, float],
    ) -> bool:
        reanimate = (
            _safe_float(features.get("positive_reanimate_from_trash")) > 0.0
            or _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
        )
        if not reanimate or _safe_float(features.get("replace_field_is_minion")) <= 0.0:
            return False
        replacing_combo_asset = (
            _safe_float(features.get("replace_field_profile_role:combo_piece")) > 0.0
            or _safe_float(features.get("replace_field_semantic_role:combo_piece")) > 0.0
            or _safe_float(features.get("replace_field_profile_role:trash_recursion")) > 0.0
            or _safe_float(features.get("replace_field_semantic_role:trash_recursion")) > 0.0
        )
        if not replacing_combo_asset or _safe_float(features.get("replace_field_value")) < 0.6:
            return False
        has_net_payoff = (
            _safe_float(features.get("positive_kill_enemy_minion")) > 0.0
            or _safe_float(features.get("play_card_beneficial_destroy_enemy_minion")) > 0.0
            or _safe_float(features.get("play_card_beneficial_remove_threat")) > 0.0
            or _safe_float(features.get("positive_add_blocker_under_pressure")) > 0.0
            or LookaheadRLPolicy._bounded_mcts_planner_trash_recursion_pressure_blocker_score(features) >= 2.0
        )
        return not has_net_payoff

    @staticmethod
    def _bounded_mcts_planner_combo_candidate_has_decisive_payoff(features: dict[str, float]) -> bool:
        if (
            _safe_float(features.get("positive_kill_enemy_minion")) > 0.0
            or _safe_float(features.get("play_card_beneficial_destroy_enemy_minion")) > 0.0
            or _safe_float(features.get("play_card_beneficial_remove_threat")) > 0.0
            or _safe_float(features.get("positive_reanimate_from_trash")) > 0.0
            or _safe_float(features.get("positive_self_destroy_death_payoff")) > 0.0
            or _safe_float(features.get("target_has_on_destroy_effect")) > 0.0
            or _safe_float(features.get("target_own_revival_candidate")) > 0.0
            or LookaheadRLPolicy._bounded_mcts_planner_trash_recursion_pressure_blocker_score(features) >= 2.0
        ):
            return True
        if (
            _safe_float(features.get("move_field_to_base")) > 0.0
            and _safe_float(features.get("move_field_to_base_protects_high_value_attacker")) > 0.0
        ):
            return True
        return bool(
            _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
            and _safe_float(features.get("play_card_summon_from_trash_own_target_available")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_combo_candidate_can_supersede(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        candidate_action: Action,
        candidate_features: dict[str, float],
    ) -> bool:
        if candidate_action.kind not in {"play_card", "move_card"}:
            return False
        if _safe_float(candidate_features.get("negative_no_effect_resource_spend")) > 0.0:
            return False
        if _safe_float(baseline_features.get("attack_has_lethal_player_target")) > 0.0:
            return False
        if baseline_action.kind == "attack":
            if (
                _attack_has_reliable_force_break(baseline_features)
                or _safe_float(baseline_features.get("positive_force_break")) > 0.0
            ):
                return LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_decisive_payoff(
                    candidate_features
                )
            return _safe_float(baseline_features.get("positive_kill_enemy_minion")) <= 0.0
        if baseline_action.kind in {"skip_mana", "end_turn", "flash_pass"}:
            return True
        decisive_baseline_payoff = (
            _safe_float(baseline_features.get("positive_kill_enemy_minion")) > 0.0
            or _safe_float(baseline_features.get("play_card_beneficial_destroy_enemy_minion")) > 0.0
            or _safe_float(baseline_features.get("play_card_beneficial_remove_threat")) > 0.0
        )
        if baseline_action.kind == candidate_action.kind:
            if decisive_baseline_payoff:
                return LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_decisive_payoff(
                    candidate_features
                )
            return True
        if decisive_baseline_payoff:
            if LookaheadRLPolicy._bounded_mcts_planner_combo_setup_without_decisive_removal(
                candidate_features
            ):
                return False
            return LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_decisive_payoff(
                candidate_features
            )
        return True

    @staticmethod
    def _bounded_mcts_planner_decisive_removal_payoff(features: dict[str, float]) -> bool:
        return (
            _safe_float(features.get("positive_kill_enemy_minion")) > 0.0
            or _safe_float(features.get("play_card_beneficial_destroy_enemy_minion")) > 0.0
            or _safe_float(features.get("play_card_beneficial_remove_threat")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_immediate_force_break_payoff(features: dict[str, float]) -> bool:
        return (
            _safe_float(features.get("positive_force_break")) > 0.0
            or _safe_float(features.get("attack_can_destroy_force")) > 0.0
            or _safe_float(features.get("move_base_to_field_immediate_force_break_payoff")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_rested_field_to_base_future_resource_line(features: dict[str, float]) -> bool:
        return (
            _safe_float(features.get("move_field_to_base")) > 0.0
            and _safe_float(features.get("move_field_to_base_enters_rested")) > 0.0
            and _safe_float(features.get("move_field_to_base_builds_mana")) > 0.0
            and (
                _safe_float(features.get("move_field_to_base_under_curve")) > 0.0
                or _safe_float(features.get("move_field_to_base_future_play")) > 0.0
                or _safe_float(features.get("move_field_to_base_resource_engine")) > 0.0
            )
            and _safe_float(features.get("move_field_to_base_exposes_lethal_pressure")) <= 0.0
            and _safe_float(features.get("move_field_to_base_removes_last_blocker_under_enemy_pressure")) <= 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_combo_setup_without_decisive_removal(features: dict[str, float]) -> bool:
        if LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(features):
            return False
        return (
            _safe_float(features.get("positive_reanimate_from_trash")) > 0.0
            or _safe_float(features.get("positive_self_destroy_death_payoff")) > 0.0
            or _safe_float(features.get("target_has_on_destroy_effect")) > 0.0
            or _safe_float(features.get("target_own_revival_candidate")) > 0.0
            or _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_learned_q_preservation_override_allowed(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        if selected_action.kind not in {"end_turn", "flash_pass", "skip_mana"}:
            return False
        if LookaheadRLPolicy._action_has_safety_negative(selected_features):
            return False
        if _safe_float(selected_features.get("negative_no_effect_resource_spend")) > 0.0:
            return False
        low_force_state = (
            _safe_float(selected_features.get("own_force_life_total", 1.0)) <= 0.25
            or _safe_float(selected_features.get("own_lowest_force_life", 1.0)) <= 0.20
            or _safe_float(baseline_features.get("own_force_life_total", 1.0)) <= 0.25
            or _safe_float(baseline_features.get("own_lowest_force_life", 1.0)) <= 0.20
        )
        enemy_force_already_broken = (
            _safe_float(selected_features.get("enemy_forces_alive", 1.0)) <= 0.0
            or _safe_float(selected_features.get("enemy_force_life_total", 1.0)) <= 0.0
            or _safe_float(baseline_features.get("enemy_forces_alive", 1.0)) <= 0.0
            or _safe_float(baseline_features.get("enemy_force_life_total", 1.0)) <= 0.0
        )
        baseline_nonlethal_attack = (
            baseline_action.kind == "attack"
            and _safe_float(baseline_features.get("attack_has_lethal_player_target")) <= 0.0
            and _safe_float(baseline_features.get("attack_can_destroy_force")) <= 0.0
        )
        baseline_unproven_base_to_field = (
            baseline_action.kind == "move_card"
            and _safe_float(baseline_features.get("move_base_to_field")) > 0.0
            and not LookaheadRLPolicy._base_to_field_has_direct_payoff(baseline_features)
        )
        return bool(
            (low_force_state or enemy_force_already_broken)
            and (
                baseline_nonlethal_attack
                or baseline_unproven_base_to_field
            )
        )

    @staticmethod
    def _bounded_mcts_planner_learned_q_override_has_semantic_proof(
        action: Action,
        features: dict[str, float],
    ) -> bool:
        if LookaheadRLPolicy._action_has_safety_negative(features):
            return False
        if _safe_float(features.get("negative_no_effect_resource_spend")) > 0.0:
            return False
        if LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(features):
            return True
        if action.kind in {"end_turn", "flash_pass", "skip_mana"}:
            return False
        if action.kind == "place_colorless_mana":
            return LookaheadRLPolicy._transition_evaluator_full_chimera_colorless_fix_features(features)
        if action.kind == "swap_mana_color":
            return (
                _safe_float(features.get("swap_mana_fallback_unsticks_hand")) > 0.0
                or _safe_float(features.get("swap_mana_enables_playable_hand_card")) > 0.0
                or _safe_float(features.get("swap_mana_to_missing_hand_color")) > 0.0
            )
        if action.kind == "play_to_base":
            return (
                _safe_float(features.get("play_to_base_restores_missing_hand_color")) > 0.0
                or _safe_float(features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
                or _safe_float(features.get("play_to_base_matches_unfixable_hand_color")) > 0.0
                or _safe_float(features.get("semantic_action_resource:repair_missing_color")) > 0.0
                or (
                    _safe_float(features.get("semantic_action_resource:base_development")) > 0.0
                    and _safe_float(features.get("own_base_count")) <= 0.2
                )
            )
        if action.kind == "play_card":
            if LookaheadRLPolicy._bounded_mcts_planner_rested_play_to_base_effect(features):
                return False
            return any(
                _safe_float(features.get(key)) > 0.0
                for key in (
                    "play_card_effect:draw_cards",
                    "play_card_effect:search_deck_to_hand",
                    "play_card_effect:look_top_to_hand",
                    "play_card_effect:place_base_from_hand",
                    "play_card_effect:create_tokens",
                    "play_card_base_development_support",
                    "play_card_base_search_support",
                    "play_card_force_life_exchange_search_support",
                    "play_card_force_life_exchange_search_for_deck_piece",
                    "play_card_rest_lockdown_enemy_ready_targets",
                    "play_card_summon_from_trash_own_target_available",
                )
            )
        if action.kind == "move_card":
            if LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_effect(features):
                return False
            if _safe_float(features.get("move_base_to_field")) > 0.0:
                return LookaheadRLPolicy._base_to_field_has_direct_payoff(features)
            if _safe_float(features.get("move_field_to_base")) > 0.0:
                return (
                    _safe_float(features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
                    or _safe_float(features.get("move_field_to_base_enables_playable_hand_card")) > 0.0
                    or _safe_float(features.get("move_field_to_base_protects_high_value_attacker")) > 0.0
                    or LookaheadRLPolicy._bounded_mcts_planner_force_conditioned_resource_line(features)
                )
        return False

    @staticmethod
    def _bounded_mcts_planner_concept_prior_static(features: dict[str, float]) -> float:
        score = 0.0
        rested_play_to_base = LookaheadRLPolicy._bounded_mcts_planner_rested_play_to_base_effect(features)
        rested_field_to_base = LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_effect(features)
        rested_play_to_base_no_bonus_keys = {
            "play_card_move_to_base_restores_missing_hand_color",
            "play_card_move_to_base_restores_missing_unfixable_hand_color",
            "play_card_move_to_base_matches_unfixable_hand_color",
            "semantic_action_resource:base_development",
            "semantic_action_resource:repair_missing_color",
        }
        rested_field_to_base_no_bonus_keys = {
            "move_field_to_base_matches_hand_color",
            "move_field_to_base_restores_missing_hand_color",
            "move_field_to_base_enables_playable_hand_card",
            "semantic_action_resource:base_development",
            "semantic_action_resource:repair_missing_color",
        }
        for key, value in features.items():
            if _safe_float(value) <= 0.0:
                continue
            if str(key).startswith("positive_"):
                score += 1.0
            elif str(key).startswith("negative_"):
                score -= 1.0
            elif (
                str(key) == "play_card_effect:move_to_base_rested"
                and _safe_float(features.get("action:play_card")) > 0.0
            ):
                continue
            elif (
                str(key) == "play_card_effect:summon_from_trash"
                and _safe_float(features.get("action:play_card")) > 0.0
            ):
                score += 0.75
            elif (
                str(key) == "play_card_effect:destroy_targets"
                and (
                    _safe_float(features.get("play_card_profile_role:death_payoff")) > 0.0
                    or _safe_float(features.get("play_card_semantic_role:death_payoff")) > 0.0
                )
            ):
                score += 0.5
            elif str(key) in {
                "play_card_summon_from_trash_own_target_available",
                "positive_reanimate_from_trash",
                "positive_self_destroy_death_payoff",
            }:
                score += 1.0
            elif str(key) in {
                "play_card_profile_role:trash_recursion",
                "play_card_semantic_role:trash_recursion",
                "play_card_profile_role:death_payoff",
                "play_card_semantic_role:death_payoff",
                "move_card_profile_role:death_payoff",
                "move_card_semantic_role:death_payoff",
                "target_has_on_destroy_effect",
                "target_own_revival_candidate",
            }:
                score += 0.5
            elif str(key) in {
                "play_card_base_search_support",
                "play_card_force_life_exchange_search_support",
                "play_card_force_life_exchange_search_for_deck_piece",
            }:
                score += 0.35
            elif str(key) == "semantic_action_resource:base_development":
                if (
                    (rested_play_to_base and str(key) in rested_play_to_base_no_bonus_keys)
                    or (rested_field_to_base and str(key) in rested_field_to_base_no_bonus_keys)
                ):
                    continue
                score += 0.75
            elif str(key) in {
                "play_to_base_restores_missing_hand_color",
                "play_to_base_restores_missing_unfixable_hand_color",
                "play_to_base_matches_unfixable_hand_color",
                "play_card_move_to_base_restores_missing_hand_color",
                "play_card_move_to_base_restores_missing_unfixable_hand_color",
                "play_card_move_to_base_matches_unfixable_hand_color",
                "move_field_to_base_restores_missing_hand_color",
                "move_field_to_base_enables_playable_hand_card",
                "semantic_action_resource:repair_missing_color",
            }:
                if not (
                    (rested_play_to_base and str(key) in rested_play_to_base_no_bonus_keys)
                    or (rested_field_to_base and str(key) in rested_field_to_base_no_bonus_keys)
                ):
                    score += 0.75
            elif str(key) in {
                "move_field_to_base_matches_hand_color",
                "move_field_to_base_protects_high_value_attacker",
            }:
                if not (rested_field_to_base and str(key) in rested_field_to_base_no_bonus_keys):
                    score += 0.35
            elif str(key) in {
                "play_card_profile_risk:target_value_sensitive",
                "play_card_semantic_risk:target_value_sensitive",
                "play_card_profile_risk:zero_dp_attacker",
                "play_card_semantic_risk:zero_dp_attacker",
                "play_card_profile_zone:usually_should_not_attack",
                "play_card_semantic_zone:usually_should_not_attack",
            }:
                score -= 0.6
        return score

    @staticmethod
    def _bounded_mcts_planner_play_card_immediate_base_resource(features: dict[str, float]) -> bool:
        if _safe_float(features.get("action:play_card")) <= 0.0:
            return False
        if LookaheadRLPolicy._bounded_mcts_planner_rested_play_to_base_effect(features):
            return False
        return (
            _safe_float(features.get("play_card_move_to_base_matches_hand_color")) > 0.0
            or _safe_float(features.get("play_card_move_to_base_restores_missing_hand_color")) > 0.0
            or _safe_float(features.get("play_card_move_to_base_restores_missing_unfixable_hand_color")) > 0.0
            or _safe_float(features.get("play_card_move_to_base_matches_unfixable_hand_color")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_rested_play_to_base_effect(features: dict[str, float]) -> bool:
        return (
            _safe_float(features.get("action:play_card")) > 0.0
            and _safe_float(features.get("play_card_effect:move_to_base_rested")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_rested_field_to_base_effect(features: dict[str, float]) -> bool:
        return (
            _safe_float(features.get("move_field_to_base")) > 0.0
            and _safe_float(features.get("move_field_to_base_enters_rested")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_abstains_for_full_chimera_colorless_replacement(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        if baseline_action.kind != "place_colorless_mana" or selected_action.kind != "play_to_base":
            return False
        if _safe_float(baseline_features.get("place_colorless_mana_supports_chimera_color_fix")) <= 0.0:
            return False
        if _safe_float(baseline_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0:
            return False
        if (
            _safe_float(selected_features.get("semantic_action_plan:base_growth")) > 0.0
            and _safe_float(selected_features.get("own_base_count")) < 0.3
        ):
            return False
        return not (
            _safe_float(selected_features.get("semantic_action_resource:repair_missing_color")) > 0.0
            or _safe_float(selected_features.get("play_to_base_restores_missing_hand_color")) > 0.0
            or _safe_float(selected_features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
        )

    @staticmethod
    def _bounded_mcts_planner_abstains_for_unproven_primary_replacement(
        *,
        primary_decision_path: bool,
        baseline_action: Action,
        baseline_features: dict[str, float],
        baseline_breakdown: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
        selected_breakdown: dict[str, float],
        value_source: str = "hybrid",
        raw_margin_floor: float = 1.0,
    ) -> bool:
        if not primary_decision_path:
            return False
        if baseline_action.kind == selected_action.kind and dict(baseline_action.payload) == dict(selected_action.payload):
            return False
        if (
            baseline_action.kind == "move_card"
            and selected_action.kind == "attack"
            and LookaheadRLPolicy._bounded_mcts_planner_force_conditioned_resource_line(
                baseline_features
            )
            and _safe_float(selected_features.get("attack_has_lethal_player_target")) <= 0.0
            and _safe_float(selected_features.get("positive_kill_enemy_minion")) <= 0.0
        ):
            return True
        baseline_is_resource_engine_field_to_base = (
            baseline_action.kind == "move_card"
            and _safe_float(baseline_features.get("move_field_to_base")) > 0.0
            and (
                _safe_float(baseline_features.get("move_field_to_base_resource_engine")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_enables_playable_hand_card")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_future_play")) > 0.0
                or LookaheadRLPolicy._bounded_mcts_planner_force_conditioned_resource_line(
                    baseline_features
                )
            )
        )
        if (
            LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            and LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(selected_features)
            and not (
                baseline_is_resource_engine_field_to_base
                and selected_action.kind == "play_card"
            )
        ):
            return False
        selected_raw_score = (
            float(selected_breakdown.get("total", 0.0) or 0.0)
            - float(selected_breakdown.get("boundedMctsPlanner", 0.0) or 0.0)
        )
        baseline_raw_score = (
            float(baseline_breakdown.get("total", 0.0) or 0.0)
            - float(baseline_breakdown.get("boundedMctsPlanner", 0.0) or 0.0)
        )
        raw_deficit = baseline_raw_score - selected_raw_score
        selected_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
            selected_features
        )
        baseline_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
            baseline_features
        )
        selected_q_value = _safe_float(selected_breakdown.get("boundedMctsPlannerQ"))
        baseline_q_value = _safe_float(baseline_breakdown.get("boundedMctsPlannerQ"))
        if (
            baseline_action.kind == "play_card"
            and selected_action.kind == "move_card"
            and _safe_float(baseline_features.get("play_card_effect:summon_from_trash")) > 0.0
            and _safe_float(baseline_features.get("play_card_summon_from_trash_no_own_target")) > 0.0
            and _safe_float(baseline_features.get("positive_reanimate_from_trash")) <= 0.0
            and _safe_float(selected_features.get("move_base_to_field")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_own_revival_candidate")) > 0.0
            and selected_q_value >= baseline_q_value + 1.0
        ):
            return False
        if (
            LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(baseline_features)
            and LookaheadRLPolicy._bounded_mcts_planner_combo_setup_without_decisive_removal(
                selected_features
            )
        ):
            return True
        if (
            str(value_source or "hybrid").strip().lower().replace("-", "_")
            in {"transition_evaluator", "transition", "transition_value", "learned_transition_value"}
            and selected_q_value > baseline_q_value + 1.0e-9
            and LookaheadRLPolicy._bounded_mcts_planner_learned_q_override_has_semantic_proof(
                selected_action,
                selected_features,
            )
        ):
            return False
        if (
            LookaheadRLPolicy._bounded_mcts_planner_reactive_removal_timing_delta(
                baseline_features
            )
            <= -7.0
            and selected_action.kind == "play_card"
            and (
                _safe_float(selected_features.get("positive_add_blocker_under_pressure")) > 0.0
                or _safe_float(selected_features.get("play_card_adds_blocker_under_pressure")) > 0.0
            )
            and _safe_float(selected_features.get("negative_no_effect_resource_spend")) <= 0.0
        ):
            return False
        if (
            LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            and selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and selected_q_value >= baseline_q_value - 0.5
        ):
            return False
        if (
            baseline_combo_priority > selected_combo_priority + 0.5
            and "positive_kill_enemy_minion" in LookaheadRLPolicy._action_immediate_positive_labels(selected_features)
            and selected_q_value >= baseline_q_value + 2.5
        ):
            return False
        if (
            selected_combo_priority > baseline_combo_priority + 0.5
            and (
                LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_concrete_payoff(
                    selected_features
                )
                or selected_q_value >= baseline_q_value + 0.5
            )
            and LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_can_supersede(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                candidate_action=selected_action,
                candidate_features=selected_features,
            )
        ):
            return False
        selected_is_stat_blocker_without_hard_payoff = (
            selected_action.kind == "play_card"
            and (
                _safe_float(selected_features.get("positive_add_blocker_under_pressure")) > 0.0
                or _safe_float(selected_features.get("play_card_effect:stat_modifier")) > 0.0
                or _safe_float(selected_features.get("play_card_effect:stat_modifier_all")) > 0.0
                or LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(
                    selected_features,
                    "play_card_beneficial_",
                )
            )
            and _safe_float(selected_features.get("positive_kill_enemy_minion")) <= 0.0
            and _safe_float(selected_features.get("play_card_beneficial_destroy_enemy_minion")) <= 0.0
            and _safe_float(selected_features.get("play_card_beneficial_remove_threat")) <= 0.0
            and _safe_float(selected_features.get("positive_force_break")) <= 0.0
            and _safe_float(selected_features.get("positive_face_damage")) <= 0.0
            and _safe_float(selected_features.get("play_card_rest_lockdown_enemy_ready_targets")) <= 0.0
            and _safe_float(selected_features.get("play_card_base_search_support")) <= 0.0
            and _safe_float(selected_features.get("play_card_base_development_support")) <= 0.0
            and _safe_float(selected_features.get("play_card_effect:move_to_base_rested")) <= 0.0
        )
        if (
            baseline_is_resource_engine_field_to_base
            and selected_is_stat_blocker_without_hard_payoff
            and raw_deficit >= 0.5
        ):
            return True
        if (
            baseline_action.kind == selected_action.kind
            and dict(baseline_action.payload) != dict(selected_action.payload)
        ):
            if (
                baseline_action.kind == "move_card"
                and _safe_float(baseline_features.get("move_field_to_base")) > 0.0
                and _safe_float(selected_features.get("move_field_to_base")) > 0.0
                and (
                    _safe_float(selected_features.get("semantic_action_resource:repair_missing_color")) > 0.0
                    or _safe_float(selected_features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
                    or _safe_float(selected_features.get("move_field_to_base_matches_hand_color")) > 0.0
                )
                and _safe_float(selected_features.get("move_field_to_base_protects_high_value_attacker")) <= 0.0
                and raw_deficit >= float(raw_margin_floor)
                and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            ):
                return True
            baseline_is_force_search_play = (
                baseline_action.kind == "play_card"
                and (
                    _safe_float(baseline_features.get("play_card_effect:draw_cards")) > 0.0
                    or _safe_float(baseline_features.get("play_card_base_search_support")) > 0.0
                    or _safe_float(baseline_features.get("play_card_force_life_exchange_search_support")) > 0.0
                    or _safe_float(baseline_features.get("play_card_force_life_exchange_search_for_deck_piece")) > 0.0
                )
            )
            selected_is_unproven_base_repair_play = (
                selected_action.kind == "play_card"
                and (
                    _safe_float(selected_features.get("semantic_action_resource:base_development")) > 0.0
                    or _safe_float(selected_features.get("semantic_action_resource:repair_missing_color")) > 0.0
                    or _safe_float(selected_features.get("play_card_effect:move_to_base_rested")) > 0.0
                )
                and _safe_float(selected_features.get("positive_kill_enemy_minion")) <= 0.0
                and _safe_float(selected_features.get("play_card_beneficial_destroy_enemy_minion")) <= 0.0
                and _safe_float(selected_features.get("positive_force_break")) <= 0.0
                and _safe_float(selected_features.get("positive_face_damage")) <= 0.0
                and _safe_float(selected_features.get("play_card_rest_lockdown_enemy_ready_targets")) <= 0.0
            )
            selected_has_base_repair_proof = (
                _safe_float(selected_features.get("play_card_move_to_base_restores_missing_hand_color")) > 0.0
                or _safe_float(selected_features.get("play_card_move_to_base_restores_missing_unfixable_hand_color")) > 0.0
                or _safe_float(selected_features.get("play_card_base_search_support")) > 0.0
                or _safe_float(selected_features.get("play_card_force_life_exchange_search_support")) > 0.0
                or _safe_float(selected_features.get("play_card_force_life_exchange_search_for_deck_piece")) > 0.0
                or _safe_float(selected_features.get("play_card_effect:draw_cards")) > 0.0
                or _safe_float(selected_features.get("play_card_effect:search_deck_to_hand")) > 0.0
            )
            selected_has_resource_semantic_without_concrete_proof = (
                (
                    _safe_float(selected_features.get("semantic_action_resource:base_development")) > 0.0
                    or _safe_float(selected_features.get("semantic_action_resource:repair_missing_color")) > 0.0
                )
                and not selected_has_base_repair_proof
            )
            if (
                baseline_is_force_search_play
                and selected_is_unproven_base_repair_play
                and selected_has_resource_semantic_without_concrete_proof
                and raw_deficit >= float(raw_margin_floor)
                and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            ):
                return True
            baseline_is_stronger_field_minion_play = (
                baseline_action.kind == "play_card"
                and selected_action.kind == "play_card"
                and _safe_float(baseline_features.get("play_card_develops_field_minion")) > 0.0
                and _safe_float(selected_features.get("play_card_develops_field_minion")) > 0.0
                and (
                    _safe_float(baseline_features.get("play_card_field_minion_bp"))
                    > _safe_float(selected_features.get("play_card_field_minion_bp")) + 1.0
                    or _safe_float(baseline_features.get("play_card_field_minion_dp"))
                    > _safe_float(selected_features.get("play_card_field_minion_dp")) + 0.5
                    or (
                        _safe_float(baseline_features.get("play_card_field_minion_bp"))
                        > _safe_float(selected_features.get("play_card_field_minion_bp")) + 0.5
                        and _safe_float(baseline_features.get("play_card_field_minion_dp"))
                        > _safe_float(selected_features.get("play_card_field_minion_dp")) + 0.25
                    )
                )
            )
            if (
                baseline_is_stronger_field_minion_play
                and selected_is_unproven_base_repair_play
                and not selected_has_base_repair_proof
                and raw_deficit >= 0.5
                and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            ):
                return True
            baseline_is_stronger_pressure_blocker = (
                baseline_action.kind == "play_card"
                and selected_action.kind == "play_card"
                and _safe_float(baseline_features.get("play_card_adds_blocker_under_pressure")) > 0.0
                and _safe_float(selected_features.get("play_card_adds_blocker_under_pressure")) > 0.0
                and (
                    _safe_float(baseline_features.get("play_card_field_minion_rush"))
                    > _safe_float(selected_features.get("play_card_field_minion_rush"))
                    or _safe_float(baseline_features.get("play_card_field_minion_bp"))
                    > _safe_float(selected_features.get("play_card_field_minion_bp")) + 0.5
                    or _safe_float(baseline_features.get("play_card_field_minion_dp"))
                    > _safe_float(selected_features.get("play_card_field_minion_dp")) + 0.5
                )
            )
            if (
                baseline_is_stronger_pressure_blocker
                and selected_is_unproven_base_repair_play
                and raw_deficit >= -1e-6
                and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            ):
                return True
            baseline_trash_pressure_blocker = (
                LookaheadRLPolicy._bounded_mcts_planner_trash_recursion_pressure_blocker_score(
                    baseline_features
                )
            )
            selected_trash_pressure_blocker = (
                LookaheadRLPolicy._bounded_mcts_planner_trash_recursion_pressure_blocker_score(
                    selected_features
                )
            )
            selected_is_smaller_trash_reanimate = (
                baseline_trash_pressure_blocker > selected_trash_pressure_blocker + 0.75
                and _safe_float(selected_features.get("play_card_effect:summon_from_trash")) > 0.0
                and (
                    _safe_float(selected_features.get("positive_reanimate_from_trash")) > 0.0
                    or _safe_float(selected_features.get("play_card_summon_from_trash_own_target_available")) > 0.0
                )
            )
            if (
                baseline_is_stronger_pressure_blocker
                and selected_is_smaller_trash_reanimate
                and selected_q_value <= baseline_q_value + 1.0
                and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            ):
                return True
            if LookaheadRLPolicy._bounded_mcts_planner_same_kind_play_card_draw_search_replacement_proven(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                baseline_breakdown=baseline_breakdown,
                selected_action=selected_action,
                selected_features=selected_features,
                selected_breakdown=selected_breakdown,
            ):
                return False
            if not LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(selected_features):
                return True
            selected_concept = LookaheadRLPolicy._bounded_mcts_planner_concept_prior_static(selected_features)
            baseline_concept = LookaheadRLPolicy._bounded_mcts_planner_concept_prior_static(baseline_features)
            if selected_concept > baseline_concept + 0.25:
                return False
            if LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(baseline_features):
                if selected_concept <= baseline_concept + 0.25:
                    return True
                return False

        selected_final_score = float(selected_breakdown.get("total", 0.0) or 0.0)
        baseline_final_score = float(baseline_breakdown.get("total", 0.0) or 0.0)
        final_deficit = baseline_final_score - selected_final_score

        baseline_is_high_raw_field_to_base = (
            baseline_action.kind == "move_card"
            and _safe_float(baseline_features.get("move_field_to_base")) > 0.0
            and raw_deficit >= 2.0
            and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
        )
        selected_is_nonlethal_force_or_face_attack = (
            selected_action.kind == "attack"
            and _safe_float(selected_features.get("attack_has_lethal_player_target")) <= 0.0
            and _safe_float(selected_features.get("positive_kill_enemy_minion")) <= 0.0
            and _safe_float(selected_features.get("play_card_beneficial_destroy_enemy_minion")) <= 0.0
            and (
                _safe_float(selected_features.get("positive_face_damage")) > 0.0
                or _safe_float(selected_features.get("attack_can_destroy_force")) > 0.0
                or _attack_has_reliable_force_break(selected_features)
                or LookaheadRLPolicy._bounded_mcts_planner_planned_force_break_attack(selected_features)
            )
        )
        if baseline_is_high_raw_field_to_base and selected_is_nonlethal_force_or_face_attack:
            return True

        baseline_is_pressure_blocker_play = (
            baseline_action.kind == "play_card"
            and (
                _safe_float(baseline_features.get("positive_add_blocker_under_pressure")) > 0.0
                or _safe_float(baseline_features.get("play_card_adds_blocker_under_pressure")) > 0.0
            )
        )
        selected_is_colored_base_to_field_without_attack_payoff = (
            selected_action.kind == "move_card"
            and _safe_float(selected_features.get("move_base_to_field")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_colored_mana")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_immediate_attack_payoff")) <= 0.0
        )
        if (
            baseline_is_pressure_blocker_play
            and selected_is_colored_base_to_field_without_attack_payoff
            and raw_deficit >= 0.25
            and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
        ):
            return True

        selected_has_strong_proof = (
            _safe_float(selected_features.get("attack_has_lethal_player_target")) > 0.0
            or _safe_float(selected_features.get("positive_kill_enemy_minion")) > 0.0
            or _safe_float(selected_features.get("play_card_beneficial_destroy_enemy_minion")) > 0.0
            or LookaheadRLPolicy._bounded_mcts_planner_planned_force_break_attack(selected_features)
        )
        if selected_has_strong_proof:
            return final_deficit >= float(raw_margin_floor)

        selected_is_chip_pressure_attack = (
            selected_action.kind == "attack"
            and (
                _safe_float(selected_features.get("positive_face_damage")) > 0.0
                or _attack_has_reliable_force_break(selected_features)
                or _safe_float(selected_features.get("attack_can_destroy_force")) > 0.0
            )
            and _safe_float(selected_features.get("attack_has_lethal_player_target")) <= 0.0
            and _safe_float(selected_features.get("attack_low_enemy_life_pressure")) <= 0.0
            and _safe_float(selected_features.get("positive_kill_enemy_minion")) <= 0.0
        )
        if (
            selected_is_chip_pressure_attack
            and baseline_action.kind != "attack"
            and raw_deficit >= 0.25
        ):
            return True

        if (
            baseline_action.kind == "place_colorless_mana"
            and selected_action.kind == "play_to_base"
            and _safe_float(baseline_features.get("place_colorless_mana_supports_chimera_color_fix")) > 0.0
            and (
                _safe_float(selected_features.get("semantic_action_resource:base_development")) > 0.0
                or _safe_float(selected_features.get("semantic_action_resource:repair_missing_color")) > 0.0
                or _safe_float(selected_features.get("play_to_base_restores_missing_hand_color")) > 0.0
                or _safe_float(selected_features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
            )
        ):
            selected_q_value = _safe_float(selected_breakdown.get("boundedMctsPlannerQ"))
            baseline_q_value = _safe_float(baseline_breakdown.get("boundedMctsPlannerQ"))
            tree_proves_early_base_development = (
                _safe_float(selected_features.get("semantic_action_resource:base_development")) > 0.0
                and _safe_float(selected_features.get("own_base_count")) <= 0.2
                and selected_q_value > baseline_q_value + 0.05
            )
            if tree_proves_early_base_development:
                return False
            if (
                _safe_float(baseline_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
                or _safe_float(selected_features.get("semantic_action_resource:repair_missing_color")) > 0.0
                or _safe_float(selected_features.get("play_to_base_restores_missing_hand_color")) > 0.0
                or _safe_float(selected_features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
            ):
                return False

        if (
            selected_action.kind != baseline_action.kind
            and final_deficit > 1e-6
            and raw_deficit >= -1e-6
        ):
            return True

        baseline_protects_development = (
            _safe_float(baseline_features.get("move_field_to_base")) > 0.0
            and (
                _safe_float(baseline_features.get("move_field_to_base_builds_mana")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_enables_playable_hand_card")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_future_play")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_matches_hand_color")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_protects_high_value_attacker")) > 0.0
            )
        )
        selected_is_pressure_attack = (
            selected_action.kind == "attack"
            and (
                _safe_float(selected_features.get("positive_face_damage")) > 0.0
                or _safe_float(selected_features.get("attack_can_destroy_force")) > 0.0
                or _safe_float(selected_features.get("attack_larger_ready_blocker_count")) > 0.0
                or _safe_float(selected_features.get("attack_larger_blocker_bp_gap")) > 0.0
                or _safe_float(selected_features.get("enemy_field_dp_pressure")) > 0.0
            )
        )
        selected_is_unproven_attack = (
            selected_action.kind == "attack"
            and not selected_has_strong_proof
            and _safe_float(selected_features.get("positive_face_damage")) <= 0.0
            and _safe_float(selected_features.get("attack_can_destroy_force")) <= 0.0
            and _safe_float(selected_features.get("attack_low_enemy_life_pressure")) <= 0.0
            and _safe_float(selected_features.get("attack_larger_ready_blocker_count")) <= 0.0
            and _safe_float(selected_features.get("attack_larger_blocker_bp_gap")) <= 0.0
        )
        baseline_has_better_attack_target = (
            baseline_action.kind == "attack"
            and selected_action.kind == "attack"
            and _safe_float(baseline_features.get("attack_preserves_better_target_quality")) > 0.0
            and _safe_float(selected_features.get("attack_preserves_better_target_quality")) <= 0.0
        )
        if baseline_has_better_attack_target and selected_is_pressure_attack and raw_deficit >= 0.25:
            return True

        selected_is_resource_pass = selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
        if (
            baseline_action.kind == "play_to_base"
            and selected_is_resource_pass
            and raw_deficit >= 0.25
        ):
            return True
        baseline_is_planned_development = baseline_action.kind in {"play_card", "move_card"} and any(
            _safe_float(baseline_features.get(key)) > 0.0
            for key in (
                "own_deck_plan:base_growth",
                "own_deck_plan:force_life_exchange",
                "semantic_action_plan:base_growth",
                "semantic_action_resource:base_development",
                "semantic_action_resource:repair_missing_color",
                "play_card_base_search_support",
                "play_card_force_life_exchange_search_support",
                "move_field_to_base",
                "move_field_to_base_builds_mana",
                "move_field_to_base_enables_playable_hand_card",
                "move_field_to_base_future_play",
                "move_field_to_base_matches_hand_color",
                "move_field_to_base_restores_missing_hand_color",
            )
        )
        if (
            baseline_is_planned_development
            and selected_is_resource_pass
            and raw_deficit >= 0.25
            and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            and not LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(selected_features)
            and not LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(selected_features)
        ):
            return True

        baseline_is_beneficial_play_card = (
            baseline_action.kind == "play_card"
            and (
                LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(
                    baseline_features,
                    "play_card_beneficial_",
                )
                or _safe_float(baseline_features.get("play_card_effect:stat_modifier")) > 0.0
                or _safe_float(baseline_features.get("play_card_effect:stat_modifier_all")) > 0.0
            )
        )
        if (
            baseline_is_beneficial_play_card
            and selected_is_resource_pass
            and raw_deficit >= -0.25
            and not LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            and not LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(selected_features)
            and not LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(selected_features)
        ):
            return True

        if baseline_protects_development and selected_is_pressure_attack:
            return True
        if baseline_protects_development and selected_is_unproven_attack:
            return True

        return bool(
            raw_deficit >= float(raw_margin_floor)
            and final_deficit >= float(raw_margin_floor)
            and not selected_has_strong_proof
        )

    @staticmethod
    def _bounded_mcts_planner_abstains_for_low_force_nonlethal_attack(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        if baseline_action.kind != "end_turn" or selected_action.kind != "attack":
            return False
        if _safe_float(selected_features.get("attack_can_destroy_force")) <= 0.0:
            return False
        if _safe_float(selected_features.get("attack_has_lethal_player_target")) > 0.0:
            return False
        planned_force_break_attack = LookaheadRLPolicy._bounded_mcts_planner_planned_force_break_attack(
            selected_features
        )
        if planned_force_break_attack:
            return False
        has_force_break_payoff_proof = (
            _safe_float(selected_features.get("positive_force_break")) > 0.0
            or _safe_float(selected_features.get("attack_has_attack_payoff")) > 0.0
        )
        if (
            not has_force_break_payoff_proof
            and _safe_float(selected_features.get("enemy_field_dp_pressure")) > 0.0
        ):
            return True
        own_force_life_total = min(
            _safe_float(selected_features.get("own_force_life_total", 1.0)),
            _safe_float(baseline_features.get("own_force_life_total", 1.0)),
        )
        own_lowest_force_life = min(
            _safe_float(selected_features.get("own_lowest_force_life", 1.0)),
            _safe_float(baseline_features.get("own_lowest_force_life", 1.0)),
        )
        own_forces_alive = min(
            _safe_float(selected_features.get("own_forces_alive", 1.0)),
            _safe_float(baseline_features.get("own_forces_alive", 1.0)),
        )
        low_force_context = (
            own_force_life_total <= 0.10
            or own_lowest_force_life <= 0.10
            or own_forces_alive <= 0.50
        )
        return low_force_context

    @staticmethod
    def _bounded_mcts_planner_planned_force_break_attack(features: dict[str, float]) -> bool:
        return bool(
            _safe_float(features.get("attack_can_destroy_force")) > 0.0
            and (
                _safe_float(features.get("own_deck_archetype:force_break")) > 0.0
                or _safe_float(features.get("own_deck_semantic_archetype:force_break")) > 0.0
            )
            and (
                _safe_float(features.get("own_deck_plan:pressure")) > 0.0
                or _safe_float(features.get("own_deck_semantic_plan:pressure")) > 0.0
            )
            and (
                _safe_float(features.get("positive_force_break")) > 0.0
                or _safe_float(features.get("attack_has_attack_payoff")) > 0.0
            )
            and _safe_float(features.get("attack_attacker_dp")) >= 0.3
            and _safe_float(features.get("enemy_force_life_total", 1.0)) <= 0.25
            and _safe_float(features.get("own_player_life", 1.0)) >= 0.6
            and not LookaheadRLPolicy._action_has_safety_negative(features)
        )

    @staticmethod
    def _bounded_mcts_planner_abstains_for_low_plan_resource_shift(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        if selected_action.kind == "place_colorless_mana":
            return (
                baseline_action.kind == "play_to_base"
                and (
                    _safe_float(selected_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
                    or (
                        LookaheadRLPolicy._bounded_mcts_planner_concept_prior_static(selected_features)
                        <= LookaheadRLPolicy._bounded_mcts_planner_concept_prior_static(baseline_features) + 0.25
                    )
                )
            )

        emergency_pressure = (
            _safe_float(selected_features.get("enemy_pressure_high_player_risk")) > 0.0
            or _safe_float(selected_features.get("enemy_pressure_near_player_lethal")) > 0.0
            or _safe_float(selected_features.get("own_player_life", 1.0)) <= 0.40
            or _safe_float(selected_features.get("own_forces_alive", 1.0)) <= 0.50
        )
        if emergency_pressure:
            return False

        baseline_has_setup_plan = (
            baseline_action.kind in {"play_card", "play_to_base"}
            and (
                _safe_float(baseline_features.get("play_card_base_development_support")) > 0.0
                or _safe_float(baseline_features.get("play_card_base_search_support")) > 0.0
                or _safe_float(baseline_features.get("play_card_profile_zone:good_mana_card")) > 0.0
                or _safe_float(baseline_features.get("play_card_semantic_zone:good_mana_card")) > 0.0
            )
        )
        if not baseline_has_setup_plan:
            return False

        if selected_action.kind == "move_card":
            spends_ready_mana = (
                _safe_float(selected_features.get("move_base_to_field_spends_ready_mana")) > 0.0
                and _safe_float(selected_features.get("move_base_to_field_with_playable_hand")) > 0.0
            )
            has_attack_payoff = _safe_float(selected_features.get("move_base_to_field_immediate_attack_payoff")) > 0.0
            return bool(spends_ready_mana and not has_attack_payoff)

        if selected_action.kind in {"play_card", "activate_flash_ability"}:
            selected_has_setup_plan = (
                _safe_float(selected_features.get("play_card_base_development_support")) > 0.0
                or _safe_float(selected_features.get("play_card_base_search_support")) > 0.0
                or _safe_float(selected_features.get("play_card_force_life_exchange_search_support")) > 0.0
                or _safe_float(selected_features.get("play_card_rest_lockdown_enemy_ready_targets")) > 0.0
                or _safe_float(selected_features.get("play_card_move_to_base_restores_missing_unfixable_hand_color")) > 0.0
            )
            low_plan_risk = (
                _safe_float(selected_features.get("play_card_profile_risk:low_bp_attacker")) > 0.0
                or _safe_float(selected_features.get("play_card_semantic_risk:low_bp_attacker")) > 0.0
            )
            return bool(low_plan_risk and not selected_has_setup_plan)

        return False

    @staticmethod
    def _bounded_mcts_planner_abstains_for_low_raw_plan_override(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        baseline_breakdown: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
        selected_breakdown: dict[str, float],
        raw_margin_floor: float = 1.0,
    ) -> bool:
        if selected_action.kind not in {"attack", "move_card"}:
            return False
        selected_raw_score = (
            float(selected_breakdown.get("total", 0.0) or 0.0)
            - float(selected_breakdown.get("boundedMctsPlanner", 0.0) or 0.0)
        )
        baseline_raw_score = (
            float(baseline_breakdown.get("total", 0.0) or 0.0)
            - float(baseline_breakdown.get("boundedMctsPlanner", 0.0) or 0.0)
        )
        if baseline_raw_score - selected_raw_score < float(raw_margin_floor):
            return False
        selected_q = _safe_float(selected_breakdown.get("boundedMctsPlannerQ"))
        baseline_q = _safe_float(baseline_breakdown.get("boundedMctsPlannerQ"))
        if (
            selected_action.kind == "move_card"
            and baseline_action.kind == "play_card"
            and _safe_float(selected_features.get("move_base_to_field")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_own_revival_candidate")) > 0.0
            and _safe_float(baseline_features.get("play_card_effect:summon_from_trash")) > 0.0
            and _safe_float(baseline_features.get("play_card_summon_from_trash_no_own_target")) > 0.0
            and _safe_float(baseline_features.get("positive_reanimate_from_trash")) <= 0.0
            and selected_q >= baseline_q + 1.0
        ):
            return False

        if selected_action.kind == "attack":
            if baseline_action.kind not in {"play_card", "end_turn"}:
                return False
            has_immediate_payoff = (
                _safe_float(selected_features.get("attack_has_lethal_player_target")) > 0.0
                or _safe_float(selected_features.get("positive_face_damage")) > 0.0
                or LookaheadRLPolicy._bounded_mcts_planner_planned_force_break_attack(selected_features)
                or _safe_float(selected_features.get("positive_kill_enemy_minion")) > 0.0
            )
            return not has_immediate_payoff

        if selected_action.kind == "move_card":
            return (
                baseline_action.kind in {"play_card", "end_turn"}
                and _safe_float(selected_features.get("move_base_to_field_immediate_attack_payoff")) <= 0.0
            )

        return False

    @staticmethod
    def _bounded_mcts_planner_abstains_for_safety_negative_conflict(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        return LookaheadRLPolicy._action_safety_negative_conflict(
            baseline_action=baseline_action,
            baseline_features=baseline_features,
            selected_action=selected_action,
            selected_features=selected_features,
        )

    @staticmethod
    def _bounded_mcts_planner_abstains_for_baseline_constrained_regression(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        baseline_breakdown: dict[str, float] | None = None,
        selected_action: Action,
        selected_features: dict[str, float],
        selected_breakdown: dict[str, float] | None = None,
    ) -> bool:
        if (
            baseline_action.kind == "move_card"
            and selected_action.kind == "attack"
            and LookaheadRLPolicy._bounded_mcts_planner_force_conditioned_resource_line(
                baseline_features
            )
            and _safe_float(selected_features.get("attack_has_lethal_player_target")) <= 0.0
            and _safe_float(selected_features.get("positive_kill_enemy_minion")) <= 0.0
        ):
            return True
        if (
            LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            and LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(selected_features)
        ):
            return False
        if (
            LookaheadRLPolicy._bounded_mcts_planner_negative_or_no_effect_baseline(baseline_features)
            and selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and selected_breakdown is not None
            and baseline_breakdown is not None
            and _safe_float(selected_breakdown.get("boundedMctsPlannerQ"))
            >= _safe_float(baseline_breakdown.get("boundedMctsPlannerQ")) - 0.5
        ):
            return False
        return LookaheadRLPolicy._action_baseline_constrained_regression(
            baseline_action=baseline_action,
            baseline_features=baseline_features,
            selected_action=selected_action,
            selected_features=selected_features,
        )

    @staticmethod
    def _bounded_mcts_planner_abstains_for_immediate_payoff_regression(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        baseline_breakdown: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
        selected_breakdown: dict[str, float],
        raw_margin_floor: float = 1.0,
    ) -> bool:
        if baseline_action.kind == selected_action.kind and dict(baseline_action.payload) != dict(selected_action.payload):
            selected_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
                selected_features
            )
            baseline_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
                baseline_features
            )
            selected_q_value = _safe_float(selected_breakdown.get("boundedMctsPlannerQ"))
            baseline_q_value = _safe_float(baseline_breakdown.get("boundedMctsPlannerQ"))
            if (
                baseline_combo_priority > selected_combo_priority + 0.5
                and "positive_kill_enemy_minion" in LookaheadRLPolicy._action_immediate_positive_labels(selected_features)
                and selected_q_value >= baseline_q_value + 2.5
            ):
                return False
            if (
                selected_combo_priority > baseline_combo_priority + 0.5
                and (
                    LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_has_concrete_payoff(
                        selected_features
                    )
                    or selected_q_value >= baseline_q_value + 0.5
                )
                and LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_can_supersede(
                    baseline_action=baseline_action,
                    baseline_features=baseline_features,
                    candidate_action=selected_action,
                    candidate_features=selected_features,
                )
            ):
                return False
            if LookaheadRLPolicy._bounded_mcts_planner_same_kind_play_card_draw_search_replacement_proven(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                baseline_breakdown=baseline_breakdown,
                selected_action=selected_action,
                selected_features=selected_features,
                selected_breakdown=selected_breakdown,
            ):
                return False
            if LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(selected_features):
                selected_concept = LookaheadRLPolicy._bounded_mcts_planner_concept_prior_static(selected_features)
                baseline_concept = LookaheadRLPolicy._bounded_mcts_planner_concept_prior_static(baseline_features)
                if selected_concept > baseline_concept + 0.25:
                    return False
            selected_raw_score = (
                float(selected_breakdown.get("total", 0.0) or 0.0)
                - float(selected_breakdown.get("boundedMctsPlanner", 0.0) or 0.0)
            )
            baseline_raw_score = (
                float(baseline_breakdown.get("total", 0.0) or 0.0)
                - float(baseline_breakdown.get("boundedMctsPlanner", 0.0) or 0.0)
            )
            return bool(
                baseline_raw_score - selected_raw_score >= float(raw_margin_floor)
                and _safe_float(baseline_features.get("negative_no_effect_resource_spend")) <= 0.0
            )

        if LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(selected_features):
            return False

        if (
            baseline_action.kind == "place_colorless_mana"
            and _safe_float(baseline_features.get("place_colorless_mana_supports_chimera_color_fix")) > 0.0
            and selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
        ):
            return True

        if (
            selected_action.kind == "place_colorless_mana"
            and baseline_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and _safe_float(selected_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
            and _safe_float(selected_features.get("place_colorless_mana_supports_chimera_color_fix")) <= 0.0
        ):
            return True

        if (
            baseline_action.kind == "move_card"
            and selected_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and _safe_float(baseline_features.get("move_field_to_base")) > 0.0
            and (
                _safe_float(baseline_features.get("move_field_to_base_under_enemy_pressure")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_restores_missing_hand_color")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_future_play")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_builds_mana")) > 0.0
                or _safe_float(baseline_features.get("move_field_to_base_protects_high_value_attacker")) > 0.0
            )
        ):
            return True

        if (
            selected_action.kind == "move_card"
            and baseline_action.kind in {"skip_mana", "end_turn", "flash_pass"}
            and _safe_float(selected_features.get("move_base_to_field")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_spends_ready_mana")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_with_playable_hand")) > 0.0
            and _safe_float(selected_features.get("move_base_to_field_immediate_attack_payoff")) <= 0.0
            and (
                _safe_float(selected_features.get("move_card_profile_risk:low_bp_attacker")) > 0.0
                or _safe_float(selected_features.get("move_card_semantic_risk:low_bp_attacker")) > 0.0
                or _safe_float(selected_features.get("move_card_profile_risk:zero_dp_attacker")) > 0.0
                or _safe_float(selected_features.get("move_card_semantic_risk:zero_dp_attacker")) > 0.0
            )
        ):
            return True

        if (
            baseline_action.kind == "swap_mana_color"
            and selected_action.kind == "place_colorless_mana"
            and (
                _safe_float(baseline_features.get("swap_mana_fallback_unsticks_hand")) > 0.0
                or _safe_float(baseline_features.get("swap_mana_enables_playable_hand_card")) > 0.0
                or _safe_float(baseline_features.get("swap_mana_to_missing_hand_color")) > 0.0
            )
            and (
                _safe_float(selected_features.get("negative_no_effect_resource_spend")) > 0.0
                or _safe_float(selected_features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0
                or _safe_float(selected_features.get("place_colorless_mana_supports_chimera_color_fix")) <= 0.0
            )
        ):
            return True

        return False

    @staticmethod
    def _bounded_mcts_planner_abstains_for_no_target_reanimate_over_pressure_blocker(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        if baseline_action.kind != "play_card" or selected_action.kind != "play_card":
            return False
        if dict(baseline_action.payload) == dict(selected_action.payload):
            return False
        selected_no_target_reanimate = (
            LookaheadRLPolicy._play_card_no_target_reanimate_empty_payoff(selected_features)
        )
        if not selected_no_target_reanimate:
            return False
        if _safe_float(baseline_features.get("play_card_summon_from_trash_no_own_target")) > 0.0:
            return False
        return _safe_float(baseline_features.get("positive_add_blocker_under_pressure")) > 0.0

    @staticmethod
    def _bounded_mcts_planner_same_kind_play_card_draw_search_replacement_proven(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        baseline_breakdown: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
        selected_breakdown: dict[str, float],
    ) -> bool:
        if (
            baseline_action.kind != "play_card"
            or selected_action.kind != "play_card"
            or dict(baseline_action.payload) == dict(selected_action.payload)
        ):
            return False
        if (
            _safe_float(selected_features.get("play_card_effect:draw_cards")) <= 0.0
            or (
                _safe_float(selected_features.get("play_card_force_life_exchange_search_support")) <= 0.0
                and _safe_float(selected_features.get("play_card_force_life_exchange_search_for_deck_piece")) <= 0.0
                and _safe_float(selected_features.get("play_card_base_search_support")) <= 0.0
                and _safe_float(selected_features.get("play_card_effect:search_deck_to_hand")) <= 0.0
            )
        ):
            return False
        if _safe_float(baseline_features.get("play_card_effect:draw_cards")) > 0.0:
            return False
        baseline_is_setup_search = (
            _safe_float(baseline_features.get("play_card_effect:move_to_base_rested")) > 0.0
            or _safe_float(baseline_features.get("play_card_effect:search_deck_to_hand")) > 0.0
            or _safe_float(baseline_features.get("play_card_base_search_support")) > 0.0
            or _safe_float(baseline_features.get("play_card_force_life_exchange_search_support")) > 0.0
            or _safe_float(baseline_features.get("play_card_force_life_exchange_search_for_deck_piece")) > 0.0
        )
        if not baseline_is_setup_search:
            return False
        if LookaheadRLPolicy._action_has_safety_negative(selected_features):
            return False
        if _safe_float(selected_features.get("negative_no_effect_resource_spend")) > 0.0:
            return False
        baseline_q = _safe_float(baseline_breakdown.get("boundedMctsPlannerQ"))
        selected_q = _safe_float(selected_breakdown.get("boundedMctsPlannerQ"))
        return selected_q >= baseline_q + 1.0

    @staticmethod
    def _action_baseline_constrained_regression(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        if selected_action.kind == baseline_action.kind and dict(selected_action.payload) == dict(baseline_action.payload):
            return False
        if _safe_float(selected_features.get("attack_has_lethal_player_target")) > 0.0:
            return False
        baseline_negative = LookaheadRLPolicy._action_immediate_negative_labels(baseline_features)
        selected_negative = LookaheadRLPolicy._action_immediate_negative_labels(selected_features)
        if selected_negative and not baseline_negative:
            return True
        baseline_positive = LookaheadRLPolicy._action_immediate_positive_labels(baseline_features)
        selected_positive = LookaheadRLPolicy._action_immediate_positive_labels(selected_features)
        selected_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
            selected_features
        )
        baseline_combo_priority = LookaheadRLPolicy._bounded_mcts_planner_combo_asset_priority(
            baseline_features
        )
        if (
            selected_combo_priority > baseline_combo_priority + 0.5
            and LookaheadRLPolicy._bounded_mcts_planner_combo_candidate_can_supersede(
                baseline_action=baseline_action,
                baseline_features=baseline_features,
                candidate_action=selected_action,
                candidate_features=selected_features,
            )
        ):
            return False
        lost_positive = baseline_positive - selected_positive
        if (
            lost_positive
            and LookaheadRLPolicy._bounded_mcts_planner_decisive_removal_payoff(selected_features)
            and lost_positive <= {
                "positive_reanimate_from_trash",
                "positive_self_destroy_death_payoff",
                "positive_on_destroy_blocker",
                "positive_board_protection",
            }
        ):
            return False
        if (
            lost_positive
            and LookaheadRLPolicy._bounded_mcts_planner_reactive_removal_timing_delta(
                baseline_features
            )
            <= -7.0
            and "positive_board_protection" in selected_positive
        ):
            return False
        return bool(lost_positive)

    @staticmethod
    def _action_immediate_positive_labels(features: dict[str, float]) -> set[str]:
        labels: set[str] = set()
        if (
            _safe_float(features.get("positive_face_damage")) > 0.0
            or _safe_float(features.get("attack_has_lethal_player_target")) > 0.0
        ):
            labels.add("positive_face_damage")
        if (
            _safe_float(features.get("positive_force_break")) > 0.0
            or _attack_has_reliable_force_break(features)
            or _safe_float(features.get("target_lethal_force")) > 0.0
            or _safe_float(features.get("move_base_to_field_immediate_force_break_payoff")) > 0.0
        ):
            labels.add("positive_force_break")
        if _safe_float(features.get("positive_kill_enemy_minion")) > 0.0:
            labels.add("positive_kill_enemy_minion")
        if _safe_float(features.get("positive_on_destroy_blocker")) > 0.0:
            labels.add("positive_on_destroy_blocker")
        if _safe_float(features.get("positive_self_destroy_death_payoff")) > 0.0:
            labels.add("positive_self_destroy_death_payoff")
        if _safe_float(features.get("positive_reanimate_from_trash")) > 0.0:
            labels.add("positive_reanimate_from_trash")
        if (
            LookaheadRLPolicy._productive_base_to_field_protection(features)
            or (
                _safe_float(features.get("action:play_card")) > 0.0
                and _safe_float(features.get("positive_add_blocker_under_pressure")) > 0.0
            )
        ):
            labels.add("positive_board_protection")
        return labels

    @staticmethod
    def _action_immediate_negative_labels(features: dict[str, float]) -> set[str]:
        labels: set[str] = set()
        if LookaheadRLPolicy._action_has_safety_negative(features):
            labels.add("negative_exposes_lethal_or_bad_trade")
        if (
            _safe_float(features.get("negative_no_effect_resource_spend")) > 0.0
            or LookaheadRLPolicy._play_card_no_target_reanimate_empty_payoff(features)
            or LookaheadRLPolicy._fragile_base_to_field_no_payoff(features)
            or LookaheadRLPolicy._unproductive_base_to_field_resource_spend(features)
        ):
            labels.add("negative_no_effect_resource_spend")
        return labels

    @staticmethod
    def _base_to_field_has_direct_payoff(features: dict[str, float]) -> bool:
        if _safe_float(features.get("move_base_to_field_immediate_attack_payoff")) > 0.0:
            return True
        if (
            _safe_float(features.get("move_base_to_field_protects_minion")) > 0.0
            and _safe_float(features.get("move_base_to_field_value")) > 0.0
            and _safe_float(features.get("move_base_to_field_mana_color:colorless")) > 0.0
            and _safe_float(features.get("move_base_to_field_colored_mana")) <= 0.0
            and (
                _safe_float(features.get("own_deck_plan:pressure")) > 0.0
                or _safe_float(features.get("own_deck_archetype:force_break")) > 0.0
                or _safe_float(features.get("enemy_pressure_high_player_risk")) > 0.0
                or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0.0
            )
        ):
            return True
        defense_need = (
            _safe_float(features.get("move_base_to_field_under_observed_aggression_defense_need")) > 0.0
            or _safe_float(features.get("enemy_pressure_high_player_risk")) > 0.0
            or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0.0
            or _safe_float(features.get("enemy_field_dp_pressure")) >= 0.5
        )
        return _safe_float(features.get("move_base_to_field_can_block")) > 0.0 and defense_need

    @staticmethod
    def _productive_base_to_field_protection(features: dict[str, float]) -> bool:
        return (
            _safe_float(features.get("move_base_to_field")) > 0.0
            and _safe_float(features.get("move_base_to_field_protects_minion")) > 0.0
            and _safe_float(features.get("move_base_to_field_value")) > 0.0
            and LookaheadRLPolicy._base_to_field_has_direct_payoff(features)
            and not LookaheadRLPolicy._fragile_base_to_field_no_payoff(features)
        )

    @staticmethod
    def _unproductive_base_to_field_resource_spend(features: dict[str, float]) -> bool:
        if _safe_float(features.get("move_base_to_field")) <= 0.0:
            return False
        if LookaheadRLPolicy._base_to_field_has_direct_payoff(features):
            return False
        return any(
            _safe_float(features.get(key)) > 0.0
            for key in (
                "move_base_to_field_low_impact_mana_minion",
                "move_base_to_field_spends_ready_mana",
                "move_base_to_field_with_playable_hand",
                "move_base_to_field_colored_mana",
                "move_base_to_field_delays_force_life_exchange",
            )
        )

    @staticmethod
    def _fragile_base_to_field_no_payoff(features: dict[str, float]) -> bool:
        if _safe_float(features.get("move_base_to_field")) <= 0.0:
            return False
        fragile = any(
            _safe_float(features.get(key)) > 0.0
            for key in (
                "move_card_profile_zone:usually_should_not_attack",
                "move_card_semantic_zone:usually_should_not_attack",
                "move_card_profile_risk:zero_dp_attacker",
                "move_card_semantic_risk:zero_dp_attacker",
                "move_card_profile_risk:low_bp_attacker",
                "move_card_semantic_risk:low_bp_attacker",
            )
        )
        if not fragile:
            return False
        if LookaheadRLPolicy._base_to_field_has_direct_payoff(features):
            return False
        return True

    @staticmethod
    def _bounded_mcts_planner_overextended_combo_attack_under_pressure(features: dict[str, float]) -> bool:
        if _safe_float(features.get("action:attack")) <= 0.0:
            return False
        if _safe_float(features.get("attack_has_lethal_player_target")) > 0.0:
            return False
        if (
            _safe_float(features.get("positive_force_break")) > 0.0
            or _attack_has_reliable_force_break(features)
            or _safe_float(features.get("attack_low_enemy_life_pressure")) > 0.0
        ):
            return False
        pressure = (
            _safe_float(features.get("enemy_pressure_high_player_risk")) > 0.0
            or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0.0
            or _safe_float(features.get("enemy_field_dp_pressure")) >= 0.5
        )
        chip_attack = (
            _safe_float(features.get("positive_face_damage")) > 0.0
            or _safe_float(features.get("attack_player_effective_dp_damage")) > 0.0
        )
        combo_attacker = (
            _safe_float(features.get("own_deck_combo_route:trash_recursion")) > 0.0
            or _safe_float(features.get("own_deck_semantic_combo_route:trash_recursion")) > 0.0
        ) and (
            _safe_float(features.get("play_card_profile_role:combo_piece")) > 0.0
            or _safe_float(features.get("play_card_semantic_role:combo_piece")) > 0.0
            or _safe_float(features.get("play_card_profile_role:trash_recursion")) > 0.0
            or _safe_float(features.get("play_card_semantic_role:trash_recursion")) > 0.0
            or _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
        )
        defensive_plan = (
            _safe_float(features.get("own_deck_plan:hold_defense")) > 0.0
            or _safe_float(features.get("own_deck_plan:protect_combo_piece")) > 0.0
            or _safe_float(features.get("own_deck_plan:stabilize")) > 0.0
        )
        resource_or_survival_tension = (
            _safe_float(features.get("own_no_ready_colored_mana_for_hand")) > 0.0
            or _safe_float(features.get("own_force_life_total", 1.0)) <= 0.25
            or _safe_float(features.get("own_lowest_force_life", 1.0)) <= 0.20
        )
        return bool(
            pressure
            and chip_attack
            and combo_attacker
            and defensive_plan
            and resource_or_survival_tension
        )

    @staticmethod
    def _bounded_mcts_planner_selected_has_major_immediate_payoff(features: dict[str, float]) -> bool:
        rested_play_to_base = LookaheadRLPolicy._bounded_mcts_planner_rested_play_to_base_effect(features)
        rested_field_to_base = LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_effect(features)
        if (
            _safe_float(features.get("attack_has_lethal_player_target")) <= 0.0
            and (
                LookaheadRLPolicy._action_has_safety_negative(features)
                or LookaheadRLPolicy._bounded_mcts_planner_overextended_combo_attack_under_pressure(features)
            )
        ):
            return False
        if (
            _safe_float(features.get("attack_has_lethal_player_target")) > 0.0
            or _safe_float(features.get("positive_face_damage")) > 0.0
            or LookaheadRLPolicy._bounded_mcts_planner_immediate_force_break_payoff(features)
            or _safe_float(features.get("positive_kill_enemy_minion")) > 0.0
            or _attack_has_reliable_force_break(features)
            or (
                _safe_float(features.get("move_base_to_field")) > 0.0
                and LookaheadRLPolicy._base_to_field_has_direct_payoff(features)
            )
            or LookaheadRLPolicy._productive_base_to_field_protection(features)
            or LookaheadRLPolicy._transition_evaluator_full_chimera_colorless_fix_features(features)
            or _safe_float(features.get("play_to_base_restores_missing_hand_color")) > 0.0
            or _safe_float(features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0
            or (
                not rested_play_to_base
                and not rested_field_to_base
                and _safe_float(features.get("semantic_action_resource:base_development")) > 0.0
            )
            or _safe_float(features.get("swap_mana_fallback_unsticks_hand")) > 0.0
            or _safe_float(features.get("swap_mana_enables_playable_hand_card")) > 0.0
            or _safe_float(features.get("play_card_rest_lockdown_enemy_ready_targets")) > 0.0
            or _safe_float(features.get("positive_reanimate_from_trash")) > 0.0
            or _safe_float(features.get("positive_self_destroy_death_payoff")) > 0.0
            or (
                _safe_float(features.get("play_card_effect:summon_from_trash")) > 0.0
                and _safe_float(features.get("play_card_summon_from_trash_own_target_available")) > 0.0
            )
        ):
            return True
        return (
            LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(features, "play_card_beneficial_")
            or LookaheadRLPolicy._bounded_mcts_planner_features_have_prefix(features, "move_card_beneficial_")
        )

    @staticmethod
    def _action_safety_negative_conflict(
        *,
        baseline_action: Action,
        baseline_features: dict[str, float],
        selected_action: Action,
        selected_features: dict[str, float],
    ) -> bool:
        if _safe_float(selected_features.get("attack_has_lethal_player_target")) > 0.0:
            return False
        if not LookaheadRLPolicy._action_has_safety_negative(selected_features):
            return False
        if LookaheadRLPolicy._action_has_safety_negative(baseline_features):
            return False
        if not LookaheadRLPolicy._action_has_nonnegative_immediate_payoff(baseline_features):
            return False
        if selected_action.kind == baseline_action.kind and dict(selected_action.payload) == dict(baseline_action.payload):
            return False
        return True

    @staticmethod
    def _action_has_safety_negative(features: dict[str, float]) -> bool:
        safety_negative_keys = (
            "negative_exposes_lethal_or_bad_trade",
            "attack_exposes_lethal_next_turn",
            "attack_force_break_unreliable_under_enemy_pressure",
            "attack_while_low_life_no_forces",
            "attack_without_forces_under_enemy_pressure",
            "attack_removes_last_blocker_under_enemy_pressure",
            "attack_spends_high_value_blocker_under_enemy_pressure",
            "attack_spends_force_life_exchange_combo_wall",
            "attack_suicide_into_larger_blocker_without_pressure",
            "attack_loses_to_larger_blocker_without_pressure",
            "semantic_action_risk:breaks_hold_defense",
            "move_field_to_base_exposes_lethal_pressure",
            "move_field_to_base_removes_last_blocker_under_enemy_pressure",
            "block_none_allows_lethal_player_damage",
            "block_none_allows_turn_lethal_player_damage",
        )
        return any(_safe_float(features.get(key)) > 0.0 for key in safety_negative_keys)

    @staticmethod
    def _action_has_nonnegative_immediate_payoff(features: dict[str, float]) -> bool:
        if (
            LookaheadRLPolicy._action_has_safety_negative(features)
            or _safe_float(features.get("negative_no_effect_resource_spend")) > 0.0
        ):
            return False
        if LookaheadRLPolicy._bounded_mcts_planner_selected_has_major_immediate_payoff(features):
            return True
        if _safe_float(features.get("attack_has_attack_payoff")) > 0.0:
            return True
        return any(
            str(key).startswith("positive_") and _safe_float(value) > 0.0
            for key, value in features.items()
        )

    @staticmethod
    def _bounded_mcts_planner_features_have_prefix(features: dict[str, float], prefix: str) -> bool:
        return any(
            str(key).startswith(prefix) and _safe_float(value) > 0.0
            for key, value in features.items()
        )

    def _bounded_mcts_planner_action_value(
        self,
        engine: Any,
        player: Any,
        action: Action,
        features: dict[str, float],
    ) -> float:
        player_index = list(getattr(engine.state, "players", [])).index(player)
        before = self._position_value(engine, player)
        root = self._lookahead_clone(engine)
        root_player = root.state.players[player_index]
        try:
            root.apply(self._copy_action(action))
        except GameOver as game_over:
            return self._game_over_lookahead_value(game_over, root_player)
        after_player = root.state.players[player_index]
        if self.bounded_mcts_planner_value_source == "transition_evaluator":
            return self._transition_evaluator_delta(
                engine,
                player,
                action,
                root,
                after_player,
                include_rollout_features=None,
            )
        if self.bounded_mcts_planner_depth > 1 and (
            not self.bounded_mcts_planner_key_decisions_only
            or self._bounded_mcts_planner_key_decision(action, features)
        ):
            after = self._lookahead_leaf_value(root, player_index, self.bounded_mcts_planner_depth - 1)
        else:
            after = self._position_value(root, after_player)
        transition_delta = 0.0
        transition_call_budget_count = (
            self._transition_evaluator_decision_call_count
            if self.bounded_mcts_planner_primary_decision_path
            else self._transition_evaluator_call_count
        )
        if (
            self.transition_evaluator_weight > 0.0
            and self.transition_evaluator is not None
            and transition_call_budget_count < self.transition_evaluator_max_calls
        ):
            transition_delta = self._transition_evaluator_delta(
                engine,
                player,
                action,
                root,
                after_player,
                include_rollout_features=(
                    False
                    if self.bounded_mcts_planner_primary_decision_path
                    else None
                ),
            )
        stance_delta = self._bounded_mcts_planner_stance_delta(
            before_engine=engine,
            before_player=player,
            after_engine=root,
            after_player=after_player,
            features=features,
        )
        resource_delta = self._bounded_mcts_planner_resource_delta(features)
        resource_delta += self._bounded_mcts_planner_state_resource_delta(
            before_engine=engine,
            before_player=player,
            after_engine=root,
            after_player=after_player,
            features=features,
        )
        board_delta = self._bounded_mcts_planner_state_board_delta(
            before_engine=engine,
            before_player=player,
            after_engine=root,
            after_player=after_player,
            features=features,
        )
        pressure_combo_attack_delta = self._bounded_mcts_planner_pressure_combo_attack_delta(features)
        reactive_removal_timing_delta = self._bounded_mcts_planner_reactive_removal_timing_delta(features)
        tree_delta = (
            float(after)
            - float(before)
            + float(stance_delta)
            + float(resource_delta)
            + float(board_delta)
            + float(pressure_combo_attack_delta)
            + float(reactive_removal_timing_delta)
        )
        bounded_tree_delta = max(-50.0, min(50.0, tree_delta))
        return max(-60.0, min(60.0, bounded_tree_delta + float(transition_delta)))

    @staticmethod
    def _bounded_mcts_planner_pressure_combo_attack_delta(features: dict[str, float]) -> float:
        if LookaheadRLPolicy._bounded_mcts_planner_overextended_combo_attack_under_pressure(features):
            return -3.0
        return 0.0

    @staticmethod
    def _bounded_mcts_planner_reactive_removal_timing_delta(features: dict[str, float]) -> float:
        if _safe_float(features.get("action:play_card")) <= 0.0:
            return 0.0
        pressure = (
            _safe_float(features.get("enemy_pressure_high_player_risk")) > 0.0
            or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0.0
            or _safe_float(features.get("enemy_field_dp_pressure")) >= 0.5
        )
        low_force_stability = (
            _safe_float(features.get("own_force_life_total", 1.0)) <= 0.25
            or _safe_float(features.get("own_lowest_force_life", 1.0)) <= 0.20
        )
        if low_force_stability and _safe_float(features.get("enemy_field_dp_pressure")) >= 0.2:
            pressure = True
        defensive_flash = (
            _safe_float(features.get("play_card_profile_role:defensive_flash")) > 0.0
            or _safe_float(features.get("play_card_semantic_role:defensive_flash")) > 0.0
        )
        enemy_turn_preferred = (
            _safe_float(features.get("play_card_profile_phase:enemy_turn_preferred")) > 0.0
            or _safe_float(features.get("play_card_semantic_phase:enemy_turn_preferred")) > 0.0
        )
        own_turn_lockdown = (
            _safe_float(features.get("play_card_profile_phase:own_turn_lockdown")) > 0.0
            or _safe_float(features.get("play_card_semantic_phase:own_turn_lockdown")) > 0.0
        )
        unsafe_on_own = (
            _safe_float(features.get("play_card_profile_target:any_target_unsafe_on_own")) > 0.0
            or _safe_float(features.get("play_card_semantic_target:any_target_unsafe_on_own")) > 0.0
            or _safe_float(features.get("play_card_profile_zone:poor_mana_card")) > 0.0
            or _safe_float(features.get("play_card_semantic_zone:poor_mana_card")) > 0.0
        )
        adds_blocker = (
            _safe_float(features.get("play_card_adds_blocker_under_pressure")) > 0.0
            or _safe_float(features.get("positive_add_blocker_under_pressure")) > 0.0
        )
        if own_turn_lockdown:
            return 0.0
        if pressure and low_force_stability and defensive_flash and enemy_turn_preferred and unsafe_on_own and not adds_blocker:
            return -8.0
        return 0.0

    @staticmethod
    def _bounded_mcts_planner_resource_delta(features: dict[str, float]) -> float:
        if LookaheadRLPolicy._bounded_mcts_planner_risky_zero_target_search(features):
            return -3.0

        delta = 0.0
        if _safe_float(features.get("action:play_to_base")) > 0.0:
            if _safe_float(features.get("semantic_action_resource:repair_missing_color")) > 0.0:
                delta += 1.1
            if _safe_float(features.get("play_to_base_restores_missing_unfixable_hand_color")) > 0.0:
                delta += 1.0
            elif _safe_float(features.get("play_to_base_restores_missing_hand_color")) > 0.0:
                delta += 0.6
            if _safe_float(features.get("play_to_base_matches_unfixable_hand_color")) > 0.0:
                delta += 0.3
            if (
                _safe_float(features.get("semantic_action_resource:base_development")) > 0.0
                and delta <= 0.0
            ):
                delta += 0.2

        if _safe_float(features.get("action:play_card")) > 0.0:
            if _safe_float(features.get("play_card_effect:draw_cards_self_only")) > 0.0:
                delta += 1.2
                if (
                    _safe_float(features.get("play_card_force_life_exchange_search_support")) > 0.0
                    or _safe_float(features.get("play_card_force_life_exchange_search_for_deck_piece")) > 0.0
                ):
                    delta += 0.4
            if _safe_float(features.get("play_card_risk:gives_opponent_card")) > 0.0:
                delta -= 1.0

        if _safe_float(features.get("action:place_colorless_mana")) > 0.0:
            if LookaheadRLPolicy._transition_evaluator_full_chimera_colorless_fix_features(features):
                delta += 0.8
            elif _safe_float(features.get("place_colorless_mana_ignores_missing_hand_color")) > 0.0:
                delta -= 1.5
            if _safe_float(features.get("place_colorless_mana_spends_ready_color_for_hand")) > 0.0:
                delta -= 2.0

        return max(-4.0, min(4.0, delta))

    def _bounded_mcts_planner_state_resource_delta(
        self,
        *,
        before_engine: Any,
        before_player: Any,
        after_engine: Any,
        after_player: Any,
        features: dict[str, float],
    ) -> float:
        if not (
            _safe_float(features.get("action:play_card")) > 0.0
            or _safe_float(features.get("action:play_to_base")) > 0.0
            or _safe_float(features.get("move_field_to_base")) > 0.0
        ):
            return 0.0
        if LookaheadRLPolicy._bounded_mcts_planner_rested_field_to_base_effect(features):
            return 0.0
        try:
            before = self.extractor.state_features(before_engine, before_player)
            after = self.extractor.state_features(after_engine, after_player)
        except Exception:
            return 0.0

        colored_base_delta = 10.0 * (
            _safe_float(after.get("own_colored_base_count"))
            - _safe_float(before.get("own_colored_base_count"))
        )
        colorless_base_delta = 10.0 * (
            _safe_float(after.get("own_colorless_base_count"))
            - _safe_float(before.get("own_colorless_base_count"))
        )
        ready_match_delta = 5.0 * (
            _safe_float(after.get("own_ready_color_matches_hand_demand"))
            - _safe_float(before.get("own_ready_color_matches_hand_demand"))
        )
        hand_demand_delta = 5.0 * (
            LookaheadRLPolicy._bounded_mcts_planner_colored_hand_demand(after)
            - LookaheadRLPolicy._bounded_mcts_planner_colored_hand_demand(before)
        )
        no_ready_demand_delta = (
            _safe_float(after.get("own_no_ready_colored_mana_for_hand"))
            - _safe_float(before.get("own_no_ready_colored_mana_for_hand"))
        )

        delta = 0.0
        delta += 0.9 * max(0.0, colored_base_delta)
        delta += 0.6 * max(0.0, -hand_demand_delta)
        delta += 0.45 * ready_match_delta
        delta -= 0.3 * max(0.0, colorless_base_delta - max(0.0, colored_base_delta))
        delta -= 0.9 * max(0.0, no_ready_demand_delta)
        return max(-4.0, min(4.0, delta))

    @staticmethod
    def _bounded_mcts_planner_colored_hand_demand(features: dict[str, float]) -> float:
        return sum(
            _safe_float(value)
            for key, value in features.items()
            if str(key).startswith("own_hand_demand_color:")
            and not str(key).endswith(":colorless")
        )

    def _bounded_mcts_planner_state_board_delta(
        self,
        *,
        before_engine: Any,
        before_player: Any,
        after_engine: Any,
        after_player: Any,
        features: dict[str, float],
    ) -> float:
        if not (
            _safe_float(features.get("action:attack")) > 0.0
            or _safe_float(features.get("action:play_card")) > 0.0
            or _safe_float(features.get("action:move_card")) > 0.0
            or _safe_float(features.get("move_base_to_field")) > 0.0
        ):
            return 0.0
        try:
            before = self.extractor.state_features(before_engine, before_player)
            after = self.extractor.state_features(after_engine, after_player)
        except Exception:
            return 0.0

        enemy_field_delta = 6.0 * (
            _safe_float(before.get("enemy_field_count"))
            - _safe_float(after.get("enemy_field_count"))
        )
        enemy_ready_dp_delta = 10.0 * (
            _safe_float(before.get("enemy_field_dp_pressure"))
            - _safe_float(after.get("enemy_field_dp_pressure"))
        )
        enemy_force_life_delta = 20.0 * (
            _safe_float(before.get("enemy_force_life_total"))
            - _safe_float(after.get("enemy_force_life_total"))
        )
        enemy_life_delta = 10.0 * (
            _safe_float(before.get("enemy_player_life"))
            - _safe_float(after.get("enemy_player_life"))
        )
        own_ready_blocker_delta = 0.0
        pressure_blocker_context = (
            _safe_float(features.get("enemy_field_dp_pressure")) > 0.0
            and (
                _safe_float(features.get("positive_add_blocker_under_pressure")) > 0.0
                or _safe_float(features.get("play_card_adds_blocker_under_pressure")) > 0.0
                or _safe_float(features.get("move_base_to_field_protects_minion")) > 0.0
            )
            and (
                _safe_float(features.get("own_force_life_total", 1.0)) <= 0.25
                or _safe_float(features.get("own_lowest_force_life", 1.0)) <= 0.20
                or _safe_float(features.get("own_player_life", 1.0)) <= 0.40
                or _safe_float(features.get("own_forces_alive", 1.0)) <= 0.50
            )
        )
        if pressure_blocker_context:
            try:
                own_ready_blocker_delta = (
                    self.position_evaluator._ready_field_dp(after_player, blockers_only=True)
                    - self.position_evaluator._ready_field_dp(before_player, blockers_only=True)
                )
            except Exception:
                own_ready_blocker_delta = 0.0

        delta = 0.0
        delta += 0.8 * max(0.0, enemy_field_delta)
        delta += 0.35 * max(0.0, enemy_ready_dp_delta)
        delta += 0.45 * max(0.0, enemy_force_life_delta)
        delta += 0.5 * max(0.0, enemy_life_delta)
        delta += 0.75 * max(0.0, own_ready_blocker_delta)
        return max(0.0, min(4.0, delta))

    def _bounded_mcts_planner_stance_delta(
        self,
        *,
        before_engine: Any,
        before_player: Any,
        after_engine: Any,
        after_player: Any,
        features: dict[str, float],
    ) -> float:
        if not self._bounded_mcts_planner_stance_context(features):
            return 0.0
        try:
            before = self.position_evaluator.survival_pressure_value(before_engine, before_player)
            after = self.position_evaluator.survival_pressure_value(after_engine, after_player)
        except Exception:
            return 0.0
        return max(-12.0, min(12.0, float(after) - float(before)))

    @staticmethod
    def _bounded_mcts_planner_stance_context(features: dict[str, float]) -> bool:
        enemy_pressure = (
            _safe_float(features.get("enemy_field_dp_pressure")) > 0.0
            or _safe_float(features.get("enemy_pressure_high_player_risk")) > 0.0
            or _safe_float(features.get("enemy_pressure_near_player_lethal")) > 0.0
        )
        low_stability = (
            _safe_float(features.get("own_force_life_total", 1.0)) <= 0.20
            or _safe_float(features.get("own_lowest_force_life", 1.0)) <= 0.20
            or _safe_float(features.get("own_player_life", 1.0)) <= 0.40
            or _safe_float(features.get("own_forces_alive", 1.0)) <= 0.50
        )
        return bool(enemy_pressure and low_stability)

    def _one_step_lookahead_delta(
        self,
        engine: Any,
        player: Any,
        action: Action,
        *,
        include_transition_evaluator: bool = True,
    ) -> float:
        try:
            player_index = list(getattr(engine.state, "players", [])).index(player)
            before = self._position_value(engine, player)
            clone = self._lookahead_clone(engine)
            clone_player = clone.state.players[player_index]
            try:
                clone.apply(self._copy_action(action))
            except GameOver as game_over:
                return self._game_over_lookahead_value(game_over, clone_player)
            if self.lookahead_rollout_until_self_turn:
                after = self._lookahead_rollout_until_self_turn_value(
                    clone,
                    player_index,
                    self.lookahead_rollout_actions or 32,
                )
                return max(-50.0, min(50.0, after - before))
            if self.lookahead_rollout_actions > 0:
                after = self._lookahead_rollout_value(clone, player_index, self.lookahead_rollout_actions)
                transition_delta = (
                    self._transition_evaluator_delta(engine, player, action, clone, clone.state.players[player_index])
                    if include_transition_evaluator
                    else 0.0
                )
                return max(-50.0, min(50.0, after - before + transition_delta))
            after = self._position_value(clone, clone_player)
            transition_delta = (
                self._transition_evaluator_delta(engine, player, action, clone, clone_player)
                if include_transition_evaluator
                else 0.0
            )
            return max(-50.0, min(50.0, after - before + transition_delta))
        except Exception:
            self._last_transition_evaluator_delta = 0.0
            return 0.0

    def _multi_step_lookahead_delta(
        self,
        engine: Any,
        player: Any,
        action: Action,
        *,
        include_transition_evaluator: bool = True,
    ) -> float:
        try:
            player_index = list(getattr(engine.state, "players", [])).index(player)
            before = self._position_value(engine, player)
            root = self._lookahead_clone(engine)
            root_player = root.state.players[player_index]
            try:
                root.apply(self._copy_action(action))
            except GameOver as game_over:
                return self._game_over_lookahead_value(game_over, root_player)
            leaf = self._lookahead_leaf_value(root, player_index, self.lookahead_depth - 1)
            transition_delta = (
                self._transition_evaluator_delta(engine, player, action, root, root_player)
                if include_transition_evaluator
                else 0.0
            )
            return max(-50.0, min(50.0, leaf - before + transition_delta))
        except Exception:
            return self._one_step_lookahead_delta(
                engine,
                player,
                action,
                include_transition_evaluator=include_transition_evaluator,
            )

    def _lookahead_leaf_value(self, engine: Any, player_index: int, remaining_depth: int) -> float:
        root_player = engine.state.players[player_index]
        if remaining_depth <= 0:
            return self._position_value(engine, root_player)
        try:
            with self._profile_span("legal_actions"):
                legal = list(engine.legal_actions())
        except Exception:
            return self._position_value(engine, root_player)
        if not legal:
            return self._position_value(engine, root_player)
        active = getattr(engine.state, "active", None)
        choices = self._profile_features_for_actions(engine, active, legal)
        choices = action_choices_after_preinference(choices)
        if self.use_public_deep_v2_planner:
            choices = apply_public_deep_v2_planner_to_action_choices(choices)
        if not choices:
            return self._position_value(engine, root_player)
        branch_scores = self._lookahead_branch_scores(engine, active, choices)
        scored = sorted(
            (
                (float(branch_scores[index]), action)
                for index, (action, _features) in enumerate(choices)
            ),
            key=lambda item: item[0],
            reverse=True,
        )[: self.lookahead_branch_width]
        values: list[float] = []
        for _score, next_action in scored:
            clone = self._lookahead_clone(engine)
            clone_player = clone.state.players[player_index]
            try:
                clone.apply(self._copy_action(next_action))
            except GameOver as game_over:
                values.append(self._game_over_lookahead_value(game_over, clone_player))
                continue
            values.append(self._lookahead_leaf_value(clone, player_index, remaining_depth - 1))
        if not values:
            return self._position_value(engine, root_player)
        return max(values) if active is root_player else min(values)

    def _lookahead_branch_score(
        self,
        engine: Any,
        active: Any,
        action: Action,
        features: dict[str, float],
    ) -> float:
        if self.lookahead_use_active_policy_scores:
            try:
                active_policy = engine.policy_for(active)
                scorer = getattr(active_policy, "score_action_for_lookahead", None)
                if callable(scorer):
                    return float(scorer(engine, active, action))
            except Exception:
                pass
        return self._score_features(features)

    def _lookahead_branch_scores(
        self,
        engine: Any,
        active: Any,
        choices: list[tuple[Action, dict[str, float]]],
    ) -> list[float]:
        if (
            self.lookahead_use_active_policy_scores
            or type(self)._score_features is not LookaheadRLPolicy._score_features
        ):
            return [
                self._lookahead_branch_score(engine, active, action, features)
                for action, features in choices
            ]
        return [
            float(breakdown["total"])
            for breakdown in self._score_breakdowns([features for _action, features in choices])
        ]

    def _lookahead_rollout_value(self, engine: Any, player_index: int, action_budget: int) -> float:
        for _ in range(max(0, int(action_budget))):
            root_player = engine.state.players[player_index]
            try:
                with self._profile_span("legal_actions"):
                    legal = list(engine.legal_actions())
            except Exception:
                return self._position_value(engine, root_player)
            if not legal:
                return self._position_value(engine, root_player)
            active = getattr(engine.state, "active", None)
            choices = self._profile_features_for_actions(engine, active, legal)
            choices = action_choices_after_preinference(choices)
            if self.use_public_deep_v2_planner:
                choices = apply_public_deep_v2_planner_to_action_choices(choices)
            if not choices:
                return self._position_value(engine, root_player)
            next_action = max(
                choices,
                key=lambda choice: self._lookahead_branch_score(engine, active, choice[0], choice[1]),
            )[0]
            clone_player = engine.state.players[player_index]
            try:
                engine.apply(self._copy_action(next_action))
            except GameOver as game_over:
                return self._game_over_lookahead_value(game_over, clone_player)
        return self._position_value(engine, engine.state.players[player_index])

    def _lookahead_rollout_until_self_turn_value(
        self,
        engine: Any,
        player_index: int,
        action_budget: int,
    ) -> float:
        max_actions = max(1, int(action_budget))
        saw_non_root_turn = False
        for actions_taken in range(max_actions):
            root_player = engine.state.players[player_index]
            active = getattr(engine.state, "active", None)
            if actions_taken > 0 and saw_non_root_turn and active is root_player:
                return self._position_value(engine, root_player)
            if active is not root_player:
                saw_non_root_turn = True
            try:
                with self._profile_span("legal_actions"):
                    legal = list(engine.legal_actions())
            except Exception:
                return self._position_value(engine, root_player)
            if not legal:
                return self._position_value(engine, root_player)
            choices = self._profile_features_for_actions(engine, active, legal)
            choices = action_choices_after_preinference(choices)
            if self.use_public_deep_v2_planner:
                choices = apply_public_deep_v2_planner_to_action_choices(choices)
            if not choices:
                return self._position_value(engine, root_player)
            next_action = max(
                choices,
                key=lambda choice: self._lookahead_branch_score(engine, active, choice[0], choice[1]),
            )[0]
            clone_player = engine.state.players[player_index]
            try:
                engine.apply(self._copy_action(next_action))
            except GameOver as game_over:
                return self._game_over_lookahead_value(game_over, clone_player)
        return self._position_value(engine, engine.state.players[player_index])

    def _lookahead_clone(self, engine: Any) -> Any:
        profiler = getattr(self, "runtime_profiler", None)
        increment = getattr(profiler, "increment", None)
        if callable(increment):
            increment("engineCloneCalls")
        with self._profile_span("clone_apply"):
            clone_for_simulation = getattr(engine, "clone_for_simulation", None)
            if callable(clone_for_simulation):
                clone = clone_for_simulation()
            else:
                clone = copy.deepcopy(engine)
        if hasattr(clone, "state") and hasattr(clone.state, "engine"):
            clone.state.engine = clone
        if hasattr(clone, "rebind_passive_modifiers"):
            clone.rebind_passive_modifiers()
        return clone

    def _copy_action(self, action: Action) -> Action:
        profiler = getattr(self, "runtime_profiler", None)
        increment = getattr(profiler, "increment", None)
        if callable(increment):
            increment("actionCopyCalls")
        with self._profile_span("clone_apply"):
            payload = getattr(action, "payload", None)
            if type(action) is Action and _action_payload_is_fast_copyable(payload):
                return Action(kind=action.kind, payload=dict(payload or {}))
            return copy.deepcopy(action)

    def _game_over_lookahead_value(self, game_over: GameOver, player: Any) -> float:
        if game_over.winner is player:
            return 100.0
        if game_over.winner is None:
            return -5.0
        return -100.0


class DirectActionSetPolicy(LookaheadRLPolicy):
    """Primary action-set policy: legal actions -> scorer scores -> masked top action."""

    def __init__(
        self,
        *,
        current_policy_base_policy: Any | None = None,
        current_policy_delta_score_weight: float = 1.0,
        current_policy_delta_override_margin: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            lookahead_weight=0.0,
            max_lookahead_actions=0,
            bounded_mcts_planner_enabled=False,
            action_set_aux_score_weight=0.0,
            action_set_prune_max_actions=0,
            action_set_skip_mcts_margin=0.0,
            action_set_fast_select_margin=0.0,
            action_set_takeover_margin=0.0,
            **kwargs,
        )
        self._action_set_direct_decision_count = 0
        self._action_set_direct_fallback_count = 0
        self._action_set_direct_error_count = 0
        self._action_set_direct_history: list[dict[str, Any]] = []
        self.current_policy_base_policy = current_policy_base_policy
        self.current_policy_delta_score_weight = float(current_policy_delta_score_weight)
        self.current_policy_delta_override_margin = float(current_policy_delta_override_margin)

    def choose(self, engine: Any) -> Action:
        self._enable_observed_opponent_features(engine)
        if self._is_zero_delta_base_preserving_current_policy_actor():
            return self._current_policy_base_choose(engine)
        legal = self._profile_legal_actions(engine)
        if not legal:
            raise RuntimeError("no legal action")
        player = getattr(engine.state, "active", None)
        decision_kind = _root_action_set_decision_kind(engine, legal)
        selected = self._direct_action_set_choice(
            engine=engine,
            player=player,
            actions=legal,
            decision_kind=decision_kind,
        )
        if selected is not None:
            return selected
        self._action_set_direct_fallback_count += 1
        if self._is_current_policy_actor_runtime():
            raise RuntimeError("current-policy direct action-set scorer failed to select a root action")
        return super().choose(engine)

    def choose_flash(self, engine: Any, legal: list[Action]) -> Action:
        if self._is_zero_delta_base_preserving_current_policy_actor():
            choose_flash = getattr(getattr(self, "current_policy_base_policy", None), "choose_flash", None)
            if callable(choose_flash):
                return choose_flash(engine, legal)
            raise RuntimeError("current-policy base-preserving actor failed: missing base flash policy")
        return super().choose_flash(engine, legal)

    def choose_blocker(self, engine: Any, attacker: Any, blockers: list[Any]):
        if self._is_zero_delta_base_preserving_current_policy_actor():
            choose_blocker = getattr(getattr(self, "current_policy_base_policy", None), "choose_blocker", None)
            if callable(choose_blocker):
                return choose_blocker(engine, attacker, blockers)
            raise RuntimeError("current-policy base-preserving actor failed: missing base blocker policy")
        if self._is_current_policy_actor_runtime():
            self._enable_observed_opponent_features(engine)
            if not blockers:
                return None
            player = getattr(blockers[0], "owner", getattr(getattr(engine, "state", None), "active", None))
            with self._profile_span("feature"):
                choices: list[tuple[Any, dict[str, float]]] = [
                    (None, self.extractor.features_for_no_blocker(engine, player, attacker))
                ]
                for blocker in blockers:
                    choices.append((blocker, self.extractor.features_for_blocker(engine, player, attacker, blocker)))
            base_slot = (
                self._current_policy_base_slot_for_choices(
                    choices=choices,
                    base_choice=self._current_policy_base_blocker_choice(engine, attacker, blockers),
                )
                if self._is_base_preserving_current_policy_actor()
                else None
            )
            return self._choose_scored(
                choices,
                audit_source="blocker",
                engine=engine,
                player=player,
                action_kind="choose_blocker",
                payload_extra={"attacker": _action_set_aux_choice_payload(attacker, engine=engine)},
                current_policy_base_slot=base_slot,
            )
        return super().choose_blocker(engine, attacker, blockers)

    def choose_attack_target(self, engine: Any, attacker: Any, targets: list[Any]) -> Any:
        if self._is_zero_delta_base_preserving_current_policy_actor():
            choose_attack_target = getattr(
                getattr(self, "current_policy_base_policy", None),
                "choose_attack_target",
                None,
            )
            if callable(choose_attack_target):
                return choose_attack_target(engine, attacker, targets)
            raise RuntimeError("current-policy base-preserving actor failed: missing base attack-target policy")
        if self._is_current_policy_actor_runtime():
            self._enable_observed_opponent_features(engine)
            player = getattr(attacker, "owner", getattr(getattr(engine, "state", None), "active", None))
            with self._profile_span("feature"):
                choices = [
                    (target, self.extractor.features_for_attack_target(engine, player, attacker, target))
                    for target in targets
                ]
            base_slot = (
                self._current_policy_base_slot_for_choices(
                    choices=choices,
                    base_choice=self._current_policy_base_attack_target_choice(engine, attacker, targets),
                )
                if self._is_base_preserving_current_policy_actor()
                else None
            )
            return self._choose_scored(
                choices,
                audit_source="attack_target",
                engine=engine,
                player=player,
                action_kind="choose_attack_target",
                payload_extra={"attacker": _action_set_aux_choice_payload(attacker, engine=engine)},
                current_policy_base_slot=base_slot,
            )
        return super().choose_attack_target(engine, attacker, targets)

    def choose_mulligan(self, engine: Any, player: Any) -> list[Any]:
        if self._is_zero_delta_base_preserving_current_policy_actor():
            choose_mulligan = getattr(getattr(self, "current_policy_base_policy", None), "choose_mulligan", None)
            if callable(choose_mulligan):
                return choose_mulligan(engine, player)
            raise RuntimeError("current-policy base-preserving actor failed: missing base mulligan policy")
        return super().choose_mulligan(engine, player)

    def action_set_direct_runtime_stats(self) -> dict[str, int]:
        return {
            "actionSetDirectDecisions": int(self._action_set_direct_decision_count),
            "actionSetDirectFallbacks": int(self._action_set_direct_fallback_count),
            "actionSetDirectErrors": int(self._action_set_direct_error_count),
        }

    def _direct_action_set_choice(
        self,
        *,
        engine: Any,
        player: Any,
            actions: list[Action],
            decision_kind: str,
            metadata_extra: Mapping[str, Any] | None = None,
    ) -> Action | None:
        top_slot = self._direct_action_set_top_slot(
            engine=engine,
            player=player,
            actions=actions,
            decision_kind=decision_kind,
            metadata_extra=metadata_extra,
        )
        if top_slot is None:
            return None
        return actions[int(top_slot)]

    def _direct_action_set_top_slot(
        self,
        *,
        engine: Any,
        player: Any,
        actions: list[Action],
        decision_kind: str,
        metadata_extra: Mapping[str, Any] | None = None,
    ) -> int | None:
        scorer = getattr(self, "action_set_scorer", None)
        score_row = getattr(scorer, "score_row", None)
        if not callable(score_row) or not actions:
            if self._is_current_policy_actor_runtime():
                raise RuntimeError("current-policy direct action-set scorer failed: scorer unavailable")
            return None
        try:
            metadata = dict(getattr(self, "action_set_runtime_metadata", None) or {})
            metadata.update(dict(metadata_extra or {}))
            row = _action_set_scorer_row(
                engine,
                player,
                actions,
                decision_kind=str(decision_kind),
                metadata=metadata,
                history_context=self._direct_action_set_history_context(metadata),
            )
            if not self._action_set_influence_enabled_for_decision(str(decision_kind)):
                if self._is_base_preserving_current_policy_actor():
                    return self._current_policy_base_slot_for_row(
                        engine=engine,
                        row=row,
                        actions=actions,
                        decision_kind=str(decision_kind),
                        metadata=metadata,
                    )
                if self._is_current_policy_actor_runtime():
                    raise RuntimeError("current-policy direct action-set scorer failed: route disabled")
                return None
            scores = list(score_row(row))
            mask = list(row.get("mask_") or [])
            if self._is_current_policy_actor_runtime():
                base_slot = self._current_policy_base_slot_for_row(
                    engine=engine,
                    row=row,
                    actions=actions,
                    decision_kind=str(decision_kind),
                    metadata=metadata,
                )
                selection = self._current_policy_base_preserving_selection_from_scores(
                    row=row,
                    scores=scores,
                    mask=mask,
                    base_slot=base_slot,
                )
                selected_slot = int(selection["selectedSlot"])
                record_metadata = dict(metadata)
                record_metadata.update(selection["metadata"])
                self._record_direct_action_set_row(
                    engine=engine,
                    player=player,
                    actions=actions,
                    scores=scores,
                    selected_slot=selected_slot,
                    decision_kind=str(decision_kind),
                    metadata_extra=record_metadata,
                )
                self._append_direct_action_history(actions[selected_slot], decision_kind=str(row.get("decisionKind") or decision_kind))
                self._action_set_direct_decision_count += 1
                return selected_slot
            scored_slots = [
                (slot, float(score))
                for slot, score in enumerate(scores[: len(actions)])
                if score is not None and (slot >= len(mask) or bool(mask[slot]))
            ]
            if not scored_slots:
                if self._is_current_policy_actor_runtime():
                    raise RuntimeError("current-policy direct action-set scorer failed: no legal scored slots")
                return None
            top_slot, _top_score = max(scored_slots, key=lambda item: (item[1], -item[0]))
            self._record_direct_action_set_row(
                engine=engine,
                player=player,
                actions=actions,
                scores=scores,
                selected_slot=int(top_slot),
                decision_kind=str(decision_kind),
                metadata_extra=metadata,
            )
            self._append_direct_action_history(actions[int(top_slot)], decision_kind=str(row.get("decisionKind") or decision_kind))
            self._action_set_direct_decision_count += 1
            return int(top_slot)
        except Exception as exc:
            self._action_set_direct_error_count += 1
            if self._is_current_policy_actor_runtime():
                message = str(exc)
                if message.startswith("current-policy direct action-set scorer failed"):
                    raise RuntimeError(message) from exc
                raise RuntimeError("current-policy direct action-set scorer failed") from exc
            return None

    def _is_current_policy_actor_runtime(self) -> bool:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        return isinstance(metadata, Mapping) and bool(metadata.get("currentPolicyActorValue"))

    def _is_base_preserving_current_policy_actor(self) -> bool:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        return (
            isinstance(metadata, Mapping)
            and bool(metadata.get("currentPolicyBasePreservingActor"))
            and self._is_current_policy_actor_runtime()
        )

    def _is_zero_delta_base_preserving_current_policy_actor(self) -> bool:
        return (
            self._is_base_preserving_current_policy_actor()
            and abs(float(getattr(self, "current_policy_delta_score_weight", 1.0))) <= 1.0e-12
        )

    def _current_policy_base_choose(self, engine: Any) -> Action:
        base_policy = getattr(self, "current_policy_base_policy", None)
        choose = getattr(base_policy, "choose", None)
        if not callable(choose):
            raise RuntimeError("current-policy base-preserving actor failed: missing base policy")
        return choose(engine)

    def _current_policy_base_flash_choice(self, engine: Any, actions: list[Action]) -> Action:
        base_policy = getattr(self, "current_policy_base_policy", None)
        choose_flash = getattr(base_policy, "choose_flash", None)
        if callable(choose_flash):
            return choose_flash(engine, actions)
        return self._current_policy_base_choose(engine)

    def _current_policy_base_blocker_choice(self, engine: Any, attacker: Any, blockers: list[Any]) -> Any:
        choose_blocker = getattr(getattr(self, "current_policy_base_policy", None), "choose_blocker", None)
        if not callable(choose_blocker):
            raise RuntimeError("current-policy base-preserving actor failed: missing base blocker policy")
        return choose_blocker(engine, attacker, blockers)

    def _current_policy_base_attack_target_choice(self, engine: Any, attacker: Any, targets: list[Any]) -> Any:
        choose_attack_target = getattr(getattr(self, "current_policy_base_policy", None), "choose_attack_target", None)
        if not callable(choose_attack_target):
            raise RuntimeError("current-policy base-preserving actor failed: missing base attack-target policy")
        return choose_attack_target(engine, attacker, targets)

    def _current_policy_base_target_slot(
        self,
        *,
        engine: Any,
        target_kind: str,
        min_n: int,
        max_n: int,
        eligible: list[Any],
        optional_offset: int,
    ) -> int | None:
        if not self._is_base_preserving_current_policy_actor():
            return None
        choose_target = getattr(getattr(self, "current_policy_base_policy", None), "choose_target", None)
        if not callable(choose_target):
            raise RuntimeError("current-policy base-preserving actor failed: missing base target policy")
        base_targets = list(choose_target(engine, str(target_kind), int(min_n), int(max_n), eligible) or [])
        if not base_targets:
            if optional_offset:
                return 0
            raise RuntimeError("current-policy base-preserving actor failed: base target is not legal")
        if len(base_targets) != 1:
            raise RuntimeError("current-policy base-preserving actor failed: multi-target base choice is unsupported")
        return int(optional_offset) + self._current_policy_base_slot_for_choices(
            choices=[(target, {}) for target in eligible],
            base_choice=base_targets[0],
        )

    def _current_policy_base_slot_for_choices(
        self,
        *,
        choices: list[tuple[Any, dict[str, float]]],
        base_choice: Any,
    ) -> int:
        for index, (choice, _features) in enumerate(choices):
            if choice is base_choice or choice == base_choice:
                return int(index)
        raise RuntimeError("current-policy base-preserving actor failed: base choice is not legal")

    def _current_policy_base_slot_for_row(
        self,
        *,
        engine: Any,
        row: Mapping[str, Any],
        actions: list[Action],
        decision_kind: str,
        metadata: Mapping[str, Any],
    ) -> int | None:
        if not self._is_base_preserving_current_policy_actor():
            return None
        raw_slot = metadata.get("currentPolicyBaseSlot")
        if raw_slot is not None:
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("current-policy base-preserving actor failed: invalid base slot") from exc
            if 0 <= slot < len(actions):
                return slot
            raise RuntimeError("current-policy base-preserving actor failed: base slot is out of range")
        if any(str(getattr(action, "kind", "")).startswith("choose_") for action in actions):
            raise RuntimeError("current-policy base-preserving actor failed: missing aux base slot")
        base_action = (
            self._current_policy_base_flash_choice(engine, actions)
            if str(decision_kind) == "flash"
            else self._current_policy_base_choose(engine)
        )
        base_identity = self._current_policy_action_identity(base_action)
        action_identities = action_identities_from_row(row)
        for index, identity in enumerate(action_identities[: len(actions)]):
            if str(identity) == base_identity:
                return int(index)
        raise RuntimeError("current-policy base-preserving actor failed: base action is not legal")

    def _current_policy_action_identity(self, action: Action) -> str:
        identities = action_identities_from_row({"actions": [_action_set_scorer_action_record(action)]})
        return str(identities[0]) if identities else ""

    def _current_policy_delta_override_margin(self) -> float:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        raw_value = (
            metadata.get("currentPolicyDeltaOverrideMargin")
            if isinstance(metadata, Mapping) and "currentPolicyDeltaOverrideMargin" in metadata
            else getattr(self, "current_policy_delta_override_margin", 0.0)
        )
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("current-policy base-preserving actor failed: invalid delta override margin") from exc
        if not math.isfinite(value) or value < 0.0:
            raise RuntimeError("current-policy base-preserving actor failed: invalid delta override margin")
        return value

    def _current_policy_base_preserving_selection_from_scores(
        self,
        *,
        row: Mapping[str, Any],
        scores: list[Any],
        mask: list[Any],
        base_slot: int | None,
    ) -> dict[str, Any]:
        selection = self._current_policy_direct_selection_from_scores(row=row, scores=scores, mask=mask)
        if not self._is_base_preserving_current_policy_actor():
            return selection
        if base_slot is None:
            raise RuntimeError("current-policy base-preserving actor failed: missing base slot")
        if not (0 <= int(base_slot) < len(mask)) or not bool(mask[int(base_slot)]):
            raise RuntimeError("current-policy base-preserving actor failed: base slot is illegal")
        metadata = dict(selection["metadata"])
        logits = [float(value) for value in metadata.get("actorLogits", [])]
        if int(base_slot) >= len(logits):
            raise RuntimeError("current-policy base-preserving actor failed: missing base slot logit")
        top_slot = int(selection["topSlot"])
        weight = float(getattr(self, "current_policy_delta_score_weight", 0.0))
        if not math.isfinite(weight) or weight < 0.0:
            raise RuntimeError("current-policy base-preserving actor failed: invalid delta score weight")
        margin = self._current_policy_delta_override_margin()
        advantage = (
            (float(logits[top_slot]) - float(logits[int(base_slot)])) * weight
            if 0 <= top_slot < len(logits)
            else float("-inf")
        )
        override = bool(top_slot != int(base_slot) and advantage > margin)
        selected_slot = int(top_slot if override else base_slot)
        identities = action_identities_from_row(row)
        selected_identity = str(identities[selected_slot]) if 0 <= selected_slot < len(identities) else ""
        base_identity = str(identities[int(base_slot)]) if 0 <= int(base_slot) < len(identities) else ""
        top_identity = str(identities[top_slot]) if 0 <= top_slot < len(identities) else ""
        metadata.update(
            {
                "actorActionSlot": selected_slot,
                "actorActionIdentity": selected_identity,
                "currentPolicyBaseSlot": int(base_slot),
                "currentPolicyBaseActionIdentity": base_identity,
                "currentPolicyDeltaTopSlot": top_slot,
                "currentPolicyDeltaTopActionIdentity": top_identity,
                "currentPolicyDeltaScoreWeight": weight,
                "currentPolicyDeltaOverrideMargin": margin,
                "currentPolicyDeltaAdvantage": float(advantage),
                "currentPolicyDeltaOverride": override,
            }
        )
        return {
            "selectedSlot": selected_slot,
            "topSlot": top_slot,
            "metadata": metadata,
        }

    def _current_policy_candidate_policy_id(self) -> str:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        if not isinstance(metadata, Mapping):
            return ""
        return str(metadata.get("currentPolicyCandidatePolicyId") or "").strip()

    def _current_policy_actor_policy_id(self) -> str:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        if not isinstance(metadata, Mapping):
            return ""
        return str(
            metadata.get("currentPolicyActorPolicyId")
            or metadata.get("currentPolicyCandidatePolicyId")
            or ""
        ).strip()

    def _current_policy_source_actor_policy_id(self) -> str:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        if not isinstance(metadata, Mapping):
            return ""
        return str(
            metadata.get("currentPolicySourceActorPolicyId")
            or ""
        ).strip()

    def _current_policy_direct_top_slot_from_scores(
        self,
        *,
        row: Mapping[str, Any],
        scores: list[Any],
        mask: list[Any],
    ) -> int:
        return int(
            self._current_policy_direct_selection_from_scores(
                row=row,
                scores=scores,
                mask=mask,
            )["selectedSlot"]
        )

    def _current_policy_direct_selection_from_scores(
        self,
        *,
        row: Mapping[str, Any],
        scores: list[Any],
        mask: list[Any],
    ) -> dict[str, Any]:
        actor_logits = self._current_policy_actor_logits_from_scores(row=row, scores=scores, mask=mask)
        actor_policy_id = self._current_policy_actor_policy_id()
        if not actor_policy_id:
            raise RuntimeError("current-policy direct action-set scorer failed: missing actor policy id")
        if not self._current_policy_source_actor_policy_id():
            raise RuntimeError("current-policy direct action-set scorer failed: missing source actor policy id")
        selection_row = dict(row)
        selection_row["actorPolicyId"] = actor_policy_id
        selection_row["actorLogits"] = actor_logits
        top_selection = select_current_policy_top(selection_row)
        action_identities = action_identities_from_row(selection_row)
        mode = self._current_policy_rollout_selection_mode()
        selected_slot = int(top_selection.slot)
        selected_log_prob: float | None = None
        temperature: float | None = None
        if mode in {"sampled_from_logits", "stochastic_rollout"}:
            temperature = self._current_policy_rollout_temperature()
            selected_slot, selected_log_prob = self._sample_current_policy_slot_from_logits(
                logits=actor_logits,
                mask=mask,
                temperature=temperature,
            )
        selected_identity = (
            str(action_identities[selected_slot])
            if 0 <= int(selected_slot) < len(action_identities)
            else ""
        )
        metadata: dict[str, Any] = {
            "actorSelectionMode": mode if mode else "argmax",
            "actorActionSlot": int(selected_slot),
            "actorActionIdentity": selected_identity,
            "actorLogits": [float(value) for value in actor_logits],
            "actorTopSlot": int(top_selection.slot),
            "actorTopActionIdentity": str(top_selection.action_identity),
        }
        if temperature is not None:
            metadata["actorSelectionTemperature"] = float(temperature)
        if selected_log_prob is not None:
            metadata["actorActionLogProb"] = float(selected_log_prob)
        return {
            "selectedSlot": int(selected_slot),
            "topSlot": int(top_selection.slot),
            "metadata": metadata,
        }

    def _current_policy_rollout_selection_mode(self) -> str:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        if not isinstance(metadata, Mapping):
            return "argmax"
        mode = str(metadata.get("currentPolicyRolloutSelectionMode") or "").strip()
        if mode in {"sampled_from_logits", "stochastic_rollout"}:
            return mode
        return "argmax"

    def _current_policy_rollout_temperature(self) -> float:
        metadata = getattr(self, "action_set_runtime_metadata", None)
        raw_value = (
            metadata.get("currentPolicyRolloutTemperature")
            if isinstance(metadata, Mapping)
            else None
        )
        try:
            value = float(1.0 if raw_value is None or raw_value == "" else raw_value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("current-policy direct action-set scorer failed: invalid rollout temperature") from exc
        if not math.isfinite(value) or value <= 0.0:
            raise RuntimeError("current-policy direct action-set scorer failed: invalid rollout temperature")
        return value

    def _sample_current_policy_slot_from_logits(
        self,
        *,
        logits: list[float],
        mask: list[Any],
        temperature: float,
    ) -> tuple[int, float]:
        legal_slots = [
            index
            for index, enabled in enumerate(mask[: len(logits)])
            if bool(enabled) and math.isfinite(float(logits[index]))
        ]
        if not legal_slots:
            raise RuntimeError("current-policy direct action-set scorer failed: no legal sampled slots")
        scaled = [float(logits[index]) / float(temperature) for index in legal_slots]
        max_scaled = max(scaled)
        weights = [math.exp(value - max_scaled) for value in scaled]
        total = sum(weights)
        if not math.isfinite(total) or total <= 0.0:
            raise RuntimeError("current-policy direct action-set scorer failed: invalid sampled logits")
        threshold = self.rng.random() * total
        cumulative = 0.0
        selected_slot = legal_slots[-1]
        selected_weight = weights[-1]
        for slot, weight in zip(legal_slots, weights):
            cumulative += float(weight)
            if threshold <= cumulative:
                selected_slot = int(slot)
                selected_weight = float(weight)
                break
        probability = max(1.0e-300, float(selected_weight) / float(total))
        return int(selected_slot), float(math.log(probability))

    def _current_policy_actor_logits_from_scores(
        self,
        *,
        row: Mapping[str, Any],
        scores: list[Any],
        mask: list[Any],
    ) -> list[float]:
        policy_id = self._current_policy_candidate_policy_id()
        if not policy_id:
            raise RuntimeError("current-policy direct action-set scorer failed: missing candidate policy id")
        selection_row = dict(row)
        selection_row["legalMask"] = [bool(value) for value in list(mask)]
        try:
            return actor_logits_from_runtime_scores(selection_row, scores)
        except ValueError as exc:
            raise RuntimeError(f"current-policy direct action-set scorer failed: {exc}") from exc

    def _record_direct_action_set_row(
        self,
        *,
        engine: Any,
        player: Any,
        actions: list[Action],
        scores: list[Any],
        selected_slot: int,
        decision_kind: str,
        metadata_extra: Mapping[str, Any] | None = None,
    ) -> None:
        recorder = getattr(self, "action_set_recorder", None)
        record_decision = getattr(recorder, "record_decision", None)
        if not callable(record_decision):
            return
        finite_scores = [
            float(score) if score is not None else 0.0
            for score in list(scores[: len(actions)])
        ]
        metadata = {
            "policyClass": self.__class__.__name__,
            "teacherScoreMode": "direct_action_set_scorer",
            "directActionSetPolicy": True,
        }
        metadata.update(dict(metadata_extra or {}))
        if self._is_current_policy_actor_runtime():
            actor_policy_id = self._current_policy_actor_policy_id()
            source_actor_policy_id = self._current_policy_source_actor_policy_id()
            candidate_policy_id = self._current_policy_candidate_policy_id()
            actor_side = _current_policy_actor_side(player)
            metadata.pop("currentPolicySourceActorPolicyId", None)
            metadata.update(
                {
                    "actorPolicyId": actor_policy_id,
                    "sourceActorPolicyId": actor_policy_id,
                    "runtimePolicyId": actor_policy_id,
                    "policyId": actor_policy_id,
                    "subjectPolicyId": actor_policy_id,
                    "currentPolicyActorValue": True,
                    "currentPolicyActorPolicyId": actor_policy_id,
                    "currentPolicyTrainingSourceActorPolicyId": source_actor_policy_id,
                    "currentPolicyCandidatePolicyId": candidate_policy_id,
                    "runtimeCandidatePolicyId": candidate_policy_id,
                }
            )
            if actor_side:
                metadata.setdefault("runtimeActorSide", actor_side)
                metadata.setdefault("modelSide", actor_side)
                metadata.setdefault(f"{actor_side.lower()}PolicyId", actor_policy_id)
        recorded_index = record_decision(
            engine,
            player,
            actions,
            teacher_scores=finite_scores,
            selected_action_slot=int(selected_slot),
            decision_kind=str(decision_kind),
            raw_scores=list(finite_scores),
            lookahead_deltas=[0.0 for _action in actions],
            metadata=metadata,
        )
        if self._is_current_policy_actor_runtime():
            self._refresh_recorded_current_policy_action_identities(
                recorder=recorder,
                recorded_index=recorded_index,
            )

    def _direct_action_set_history_context(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        context = _action_set_scorer_json_mapping(dict(metadata or {}))
        context["recentActions"] = [dict(item) for item in self._action_set_direct_history[-8:]]
        return context

    def _refresh_recorded_current_policy_action_identities(
        self,
        *,
        recorder: Any,
        recorded_index: Any,
    ) -> None:
        try:
            index = int(recorded_index)
        except (TypeError, ValueError):
            return
        if index < 0:
            return
        rows = getattr(recorder, "rows", None)
        if not isinstance(rows, list) or index >= len(rows):
            return
        row = rows[index]
        if not isinstance(row, dict):
            return
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            return
        actions = row.get("actions")
        action_count = len(actions) if isinstance(actions, list) else 0
        actor_logits = metadata.get("actorLogits")
        if isinstance(actor_logits, list) and action_count > 0 and len(actor_logits) < action_count:
            metadata["actorLogits"] = [float(value) for value in actor_logits] + [
                -1.0e9 for _index in range(action_count - len(actor_logits))
            ]
        identities = action_identities_from_row(row)
        for slot_key, identity_key in (
            ("actorActionSlot", "actorActionIdentity"),
            ("actorTopSlot", "actorTopActionIdentity"),
        ):
            try:
                slot = int(metadata.get(slot_key))
            except (TypeError, ValueError):
                continue
            if 0 <= slot < len(identities):
                metadata[identity_key] = str(identities[slot])

    def _append_direct_action_history(self, action: Action, *, decision_kind: str) -> None:
        self._action_set_direct_history.append(
            {
                "kind": str(getattr(action, "kind", "unknown") or "unknown"),
                "decisionKind": str(decision_kind or "unknown"),
            }
        )
        if len(self._action_set_direct_history) > 8:
            del self._action_set_direct_history[:-8]

    def choose_target(self, engine: Any, kind: str, min_n: int, max_n: int, eligible: list[Any]) -> list[Any]:
        self._enable_observed_opponent_features(engine)
        if self._is_zero_delta_base_preserving_current_policy_actor():
            choose_target = getattr(getattr(self, "current_policy_base_policy", None), "choose_target", None)
            if callable(choose_target):
                return choose_target(engine, kind, min_n, max_n, eligible)
            raise RuntimeError("current-policy base-preserving actor failed: missing base target policy")
        if self._is_base_preserving_current_policy_actor() and not self._action_set_influence_enabled_for_decision("generic_target"):
            choose_target = getattr(getattr(self, "current_policy_base_policy", None), "choose_target", None)
            if callable(choose_target):
                return choose_target(engine, kind, min_n, max_n, eligible)
            raise RuntimeError("current-policy base-preserving actor failed: missing base target policy")
        if not eligible or max_n <= 0:
            return []
        if self._queued_targets:
            return super().choose_target(engine, kind, min_n, max_n, eligible)
        if int(min_n) == 1 and int(max_n) == 1:
            player = target_selection_player_for_context(engine)
            base_slot = self._current_policy_base_target_slot(
                engine=engine,
                target_kind=str(kind),
                min_n=int(min_n),
                max_n=int(max_n),
                eligible=eligible,
                optional_offset=0,
            )
            metadata_extra = {"auditSource": "generic_target", "targetKind": str(kind)}
            if base_slot is not None:
                metadata_extra["currentPolicyBaseSlot"] = int(base_slot)
            actions = [
                _action_set_aux_choice_action(
                    "choose_target",
                    target,
                    payload_extra={"target_kind": str(kind)},
                    engine=engine,
                )
                for target in eligible
            ]
            top_slot = self._direct_action_set_top_slot(
                engine=engine,
                player=player,
                actions=actions,
                decision_kind="generic_target",
                metadata_extra=metadata_extra,
            )
            if top_slot is not None:
                return [eligible[int(top_slot)]]
        elif self._is_current_policy_actor_runtime():
            selected_slots = self._direct_action_set_target_slots(
                engine=engine,
                targets=eligible,
                target_kind=str(kind),
                min_n=int(min_n),
                max_n=int(max_n),
            )
            if selected_slots is not None:
                return [eligible[int(slot)] for slot in selected_slots]
        self._action_set_direct_fallback_count += 1
        if self._is_current_policy_actor_runtime():
            raise RuntimeError("current-policy direct action-set scorer failed to select a target")
        return super().choose_target(engine, kind, min_n, max_n, eligible)

    def _direct_action_set_target_slots(
        self,
        *,
        engine: Any,
        targets: list[Any],
        target_kind: str,
        min_n: int,
        max_n: int,
    ) -> list[int] | None:
        if not targets or int(max_n) <= 0:
            return []
        scorer = getattr(self, "action_set_scorer", None)
        score_row = getattr(scorer, "score_row", None)
        if not callable(score_row):
            raise RuntimeError("current-policy direct action-set scorer failed: scorer unavailable")
        player = target_selection_player_for_context(engine)
        optional_offset = 1 if int(min_n) <= 0 else 0
        actions: list[Action] = []
        if optional_offset:
            actions.append(
                _action_set_aux_choice_action(
                    "choose_target",
                    None,
                    payload_extra={"target_kind": str(target_kind)},
                    engine=engine,
                )
            )
        actions.extend(
            _action_set_aux_choice_action(
                "choose_target",
                target,
                payload_extra={"target_kind": str(target_kind)},
                engine=engine,
            )
            for target in targets
        )
        try:
            metadata = dict(getattr(self, "action_set_runtime_metadata", None) or {})
            metadata.update({"auditSource": "generic_target", "targetKind": str(target_kind)})
            base_slot = self._current_policy_base_target_slot(
                engine=engine,
                target_kind=str(target_kind),
                min_n=int(min_n),
                max_n=int(max_n),
                eligible=targets,
                optional_offset=optional_offset,
            )
            if base_slot is not None:
                metadata["currentPolicyBaseSlot"] = int(base_slot)
            row = _action_set_scorer_row(
                engine,
                player,
                actions,
                decision_kind="generic_target",
                metadata=metadata,
                history_context=self._direct_action_set_history_context(metadata),
            )
            scores = list(score_row(row))
            mask = list(row.get("mask_") or [])
            selection = self._current_policy_base_preserving_selection_from_scores(
                row=row,
                scores=scores,
                mask=mask,
                base_slot=base_slot,
            )
            selected_slot_for_record = int(selection["selectedSlot"])
            if int(min_n) > 1:
                target_slots = list(range(int(optional_offset), len(actions)))
                ranked_slots = sorted(
                    target_slots,
                    key=lambda slot: float(scores[slot]) if slot < len(scores) and scores[slot] is not None else float("-inf"),
                    reverse=True,
                )
                required = min(int(min_n), len(ranked_slots))
                selected_action_slots = sorted(ranked_slots[:required])
            elif optional_offset and selected_slot_for_record == 0:
                selected_action_slots: list[int] = []
            elif selected_slot_for_record < optional_offset:
                raise RuntimeError("current-policy direct target selection chose an invalid optional slot")
            else:
                selected_action_slots = [selected_slot_for_record]
            self._record_direct_action_set_row(
                engine=engine,
                player=player,
                actions=actions,
                scores=scores,
                selected_slot=selected_slot_for_record,
                decision_kind="generic_target",
                metadata_extra={**metadata, **selection["metadata"]},
            )
            self._append_direct_action_history(
                actions[selected_slot_for_record],
                decision_kind=str(row.get("decisionKind") or "generic_target"),
            )
            self._action_set_direct_decision_count += 1
            return [int(slot) - optional_offset for slot in selected_action_slots]
        except Exception as exc:
            self._action_set_direct_error_count += 1
            message = str(exc)
            if message.startswith("current-policy direct action-set scorer failed"):
                raise RuntimeError(message) from exc
            raise RuntimeError("current-policy direct action-set scorer failed") from exc

    def _choose_scored(
            self,
            choices: list[tuple[Any, dict[str, float]]],
            *,
            audit_source: str = "scored_choice",
            engine: Any | None = None,
            player: Any | None = None,
            action_kind: str | None = None,
            payload_extra: dict[str, Any] | None = None,
            action_set_decision_kind: str | None = None,
            current_policy_base_slot: int | None = None,
    ) -> Any:
        if not choices:
            raise RuntimeError("no legal choices")
        effective_decision = action_set_decision_kind
        if effective_decision is None and action_kind is not None:
            effective_decision = _action_set_aux_decision_kind(action_kind)
        if engine is not None and player is not None and effective_decision is not None:
            metadata_extra = {"auditSource": str(audit_source)}
            if current_policy_base_slot is not None:
                metadata_extra["currentPolicyBaseSlot"] = int(current_policy_base_slot)
            if action_kind is None:
                actions = [choice for choice, _features in choices if isinstance(choice, Action)]
                if len(actions) == len(choices):
                    top_slot = self._direct_action_set_top_slot(
                        engine=engine,
                        player=player,
                        actions=actions,
                        decision_kind=str(effective_decision),
                        metadata_extra=metadata_extra,
                    )
                    if top_slot is not None:
                        return choices[int(top_slot)][0]
            else:
                actions = [
                    _action_set_aux_choice_action(
                        str(action_kind),
                        choice,
                        payload_extra=dict(payload_extra or {}),
                        engine=engine,
                    )
                    for choice, _features in choices
                ]
                top_slot = self._direct_action_set_top_slot(
                    engine=engine,
                    player=player,
                    actions=actions,
                    decision_kind=str(effective_decision),
                    metadata_extra=metadata_extra,
                )
                if top_slot is not None:
                    return choices[int(top_slot)][0]
        self._action_set_direct_fallback_count += 1
        if self._is_current_policy_actor_runtime():
            raise RuntimeError("current-policy direct action-set scorer failed to select a scored choice")
        return super()._choose_scored(
            choices,
            audit_source=audit_source,
            engine=engine,
            player=player,
            action_kind=action_kind,
            payload_extra=payload_extra,
            action_set_decision_kind=action_set_decision_kind,
        )


_FAST_ACTION_PAYLOAD_VALUE_TYPES = (str, int, float, bool, type(None))


def _action_payload_is_fast_copyable(payload: Any) -> bool:
    if payload is None:
        return True
    if not isinstance(payload, dict):
        return False
    return all(
        isinstance(key, str) and isinstance(value, _FAST_ACTION_PAYLOAD_VALUE_TYPES)
        for key, value in payload.items()
    )


def _load_action_set_scorer(path: str | Path) -> Any:
    from zz.action_set_scoring_contracts import validate_action_set_scorer_shape
    from zz.action_set_model import ActionSetLinearScorer
    from zz.action_set_listwise_model import (
        ACTION_SET_LISTWISE_ADDITIVE_VERSION,
        ACTION_SET_LISTWISE_GATED_ADDITIVE_VERSION,
        ACTION_SET_LISTWISE_MODEL_VERSION,
        ACTION_SET_LISTWISE_ROUTED_VERSION,
        ACTION_SET_LISTWISE_TRUE_TURN_ORDER_HYBRID_VERSION,
        ActionSetAdditiveScorer,
        ActionSetGatedAdditiveScorer,
        ActionSetListwiseScorer,
        ActionSetRoutedListwiseScorer,
        ActionSetTrueTurnOrderHybridScorer,
    )
    from zz.action_set_ygo_policy import YGO_STYLE_ACTION_SET_POLICY_VERSION, YgoStyleActionSetPolicyScorer

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("model"), dict):
        data = data["model"]
    model_version = str(data.get("modelVersion") or "")
    if model_version == "action_set_linear_scorer_v1":
        scorer = ActionSetLinearScorer.from_dict(data)
    elif model_version == ACTION_SET_LISTWISE_MODEL_VERSION:
        scorer = ActionSetListwiseScorer.from_dict(data)
    elif model_version == ACTION_SET_LISTWISE_TRUE_TURN_ORDER_HYBRID_VERSION:
        scorer = ActionSetTrueTurnOrderHybridScorer.from_dict(data)
    elif model_version == ACTION_SET_LISTWISE_ROUTED_VERSION:
        scorer = ActionSetRoutedListwiseScorer.from_dict(data)
    elif model_version == ACTION_SET_LISTWISE_ADDITIVE_VERSION:
        scorer = ActionSetAdditiveScorer.from_dict(data)
    elif model_version == ACTION_SET_LISTWISE_GATED_ADDITIVE_VERSION:
        scorer = ActionSetGatedAdditiveScorer.from_dict(data)
    elif model_version == YGO_STYLE_ACTION_SET_POLICY_VERSION:
        scorer = YgoStyleActionSetPolicyScorer.from_dict(data)
    else:
        scorer = ActionSetLinearScorer.from_dict(data)
    validate_action_set_scorer_shape(scorer, context=f"action-set scorer {Path(path)}")
    return scorer


def _action_set_aux_choice_action(
    action_kind: str,
    choice: Any,
    *,
    payload_extra: dict[str, Any] | None = None,
    engine: Any | None = None,
) -> Action:
    payload = dict(payload_extra or {})
    payload.update(_action_set_aux_choice_payload(choice, engine=engine))
    return Action(kind=str(action_kind), payload=payload)


def _action_set_aux_choice_payload(choice: Any, *, engine: Any | None = None) -> dict[str, Any]:
    if choice is None:
        return {"block_none": True}
    ref = getattr(choice, "ref", None)
    if ref is not None:
        target_kind = getattr(getattr(choice, "kind", ""), "name", getattr(choice, "kind", ""))
        payload = {"attack_target_kind": str(target_kind)}
        payload.update(_action_set_aux_choice_payload(ref, engine=engine))
        return payload
    card = getattr(choice, "card", None)
    payload: dict[str, Any] = {}
    iid = getattr(choice, "iid", None)
    if iid is not None:
        payload["iid"] = int(iid)
    if card is not None:
        payload["card_id"] = str(getattr(card, "id", ""))
        payload["bp"] = _action_set_effective_or_instance_stat(
            engine,
            choice,
            "effective_bp",
            "bp",
            getattr(card, "bp", 0),
        )
        payload["dp"] = _action_set_effective_or_instance_stat(
            engine,
            choice,
            "effective_dp",
            "dp",
            getattr(card, "dp", 0),
        )
        payload["rested"] = bool(getattr(choice, "rested", False))
    force = getattr(choice, "force", None)
    if force is not None:
        payload["force_id"] = str(getattr(force, "id", ""))
        payload["force_life"] = int(getattr(choice, "life", 0) or 0)
    owner = getattr(choice, "owner", None)
    if owner is not None:
        payload["owner"] = str(getattr(owner, "name", getattr(owner, "side", "")))
    if not payload and hasattr(choice, "name"):
        payload["name"] = str(getattr(choice, "name"))
    return payload


def _action_set_effective_or_instance_stat(
    engine: Any | None,
    choice: Any,
    method_name: str,
    attr_name: str,
    fallback: Any,
) -> int:
    method = getattr(engine, method_name, None) if engine is not None else None
    if callable(method):
        try:
            return int(method(choice) or 0)
        except Exception:
            pass
    return int(getattr(choice, attr_name, fallback) or 0)


def _normalise_action_set_decision_kind_filter(value: Any | None) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        values = value.split(",")
    else:
        try:
            values = list(value)
        except TypeError:
            values = [value]
    return frozenset(
        str(item).strip().lower()
        for item in values
        if str(item).strip()
    )


def _action_set_decision_kind_filter_allows(allowed: Any, decision_kind: str) -> bool:
    normalised = _normalise_action_set_decision_kind_filter(allowed)
    if not normalised:
        return True
    return str(decision_kind or "unknown").strip().lower() in normalised


def _action_set_aux_decision_kind(action_kind: str) -> str:
    return decision_kind_for_action(Action(str(action_kind or "unknown")))


def _root_action_set_decision_kind(engine: Any, actions: list[Action]) -> str:
    state = getattr(engine, "state", None)
    step = _enum_value_text(getattr(state, "step", None))
    phase = _enum_value_text(getattr(state, "phase", None))
    if step == "mana" or phase == "mana":
        return "mana"
    if step == "flash":
        return "flash"
    if step == "main" or phase == "main":
        return "main"
    decision_kinds = {
        decision_kind_for_action(action)
        for action in actions
        if isinstance(action, Action)
    }
    if not decision_kinds:
        return "unknown"
    if decision_kinds.issubset({"mana", "color_swap"}):
        return "mana"
    non_unknown = {kind for kind in decision_kinds if kind != "unknown"}
    if len(non_unknown) == 1:
        return next(iter(non_unknown))
    if "main" in non_unknown:
        return "main"
    return "unknown"


def _enum_value_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _action_set_runtime_ranking_score(
    scorer: Any,
    raw_score: Any,
    *,
    base_score: Any,
    weight: float,
    max_correction: float | None,
) -> float | None:
    if raw_score is None:
        return None
    if not _action_set_scorer_is_runtime_aux_sidecar(scorer):
        return float(raw_score)
    weighted = clamp_runtime_aux_residual(raw_score, weight=float(weight), max_correction=max_correction)
    if weighted is None:
        return None
    return float(base_score) + float(weighted)


def _action_set_scorer_is_runtime_aux_sidecar(scorer: Any) -> bool:
    if bool(getattr(scorer, "runtimeCalibratedSidecarTraining", False)):
        return True
    diagnostics = getattr(scorer, "runtimeAuxTrainingDiagnostics", None)
    return isinstance(diagnostics, Mapping) and bool(diagnostics.get("requireRowRuntimeTotal"))


def _action_set_scorer_row(
    engine: Any,
    player: Any,
    actions: list[Action],
    *,
    decision_kind: str = "main",
    metadata: Mapping[str, Any] | None = None,
    history_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from zz.rl_tensor_schema import encode_action_set

    encoded = encode_action_set(
        engine,
        player,
        actions,
        max_actions=len(actions),
        decision_kind=decision_kind,
        history_context=history_context if history_context is not None else metadata,
    )
    row_metadata = _action_set_scorer_json_mapping(dict(metadata or {}))
    row = {
        "decisionKind": encoded.decisionKind,
        "actionTensorSchemaVersion": encoded.schemaVersion,
        "actionTensorSchemaFingerprint": encoded.schemaFingerprint,
        "cardIdVocabVersion": encoded.cardIdVocabVersion,
        "cardIdVocabHash": encoded.cardIdVocabHash,
        "trueTurnOrder": "first" if bool(getattr(player, "is_first_player", False)) else "second",
        "globalFeatureNames": list(encoded.globalFeatureNames),
        "actionFeatureNames": list(encoded.actionFeatureNames),
        "cardFeatureNames": list(encoded.cardFeatureNames),
        "historyFeatureNames": list(encoded.historyFeatureNames),
        "cards_": [list(card_row) for card_row in encoded.cards_],
        "history_": list(encoded.history_),
        "global_": list(encoded.global_),
        "actions_": [list(row) for row in encoded.actions_],
        "mask_": list(encoded.mask_),
        "actions": [_action_set_scorer_action_record(action) for action in actions],
        "actionRecords": [_action_set_scorer_action_record(action) for action in actions],
        "metadata": row_metadata,
    }
    for key in (
        "sourceSuiteKind",
        "suiteKind",
        "opponentBaselineLabel",
        "opponentPolicyId",
        "policyId",
        "playerDeckId",
        "opponentDeckId",
        "playerDeckSource",
        "opponentDeckSource",
        "deckSource",
        "modelSide",
        "difficulty",
    ):
        if key in row_metadata:
            row[key] = row_metadata[key]
    return row


def _action_set_scorer_action_record(action: Action) -> dict[str, Any]:
    return {
        "kind": str(getattr(action, "kind", "")),
        "payload": _action_set_scorer_json_mapping(getattr(action, "payload", {}) or {}),
    }


def _current_policy_actor_side(player: Any) -> str:
    side = getattr(player, "side", None)
    for value in (getattr(side, "name", None), getattr(side, "value", None), getattr(player, "name", None)):
        text = str(value or "").strip().upper()
        if text in {"P1", "P2"}:
            return text
    return ""


def _action_set_scorer_json_mapping(mapping: Any) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {
        str(key): _action_set_scorer_json_value(value)
        for key, value in mapping.items()
    }


def _action_set_scorer_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _action_set_scorer_json_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_action_set_scorer_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


def _battle_model_candidate_paths(
        *,
        root: str | Path | None = None,
        model_path: str | Path | None = None,
) -> list[Path]:
    if model_path is not None:
        path = Path(model_path)
        return [path] if path.exists() else []
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    return [
        path
        for candidate in DEFAULT_BATTLE_MODEL_CANDIDATES
        if (path := base / candidate).exists()
    ]


def default_battle_model_path(*, root: str | Path | None = None) -> Path | None:
    paths = _battle_model_candidate_paths(root=root)
    return paths[0] if paths else None


def make_battle_policy(seed: int, *, model_path: str | Path | None = None) -> Any:
    for path in _battle_model_candidate_paths(model_path=model_path):
        try:
            if path.suffix.lower() == ".pt":
                from zz.deep_rl import TorchActionValueModel

                model = TorchActionValueModel.load(path)
                if _is_rejected_public_deep_v2_candidate(model):
                    continue
                return LookaheadRLPolicy(
                    model=model,
                    rng=random.Random(seed),
                    epsilon=0.0,
                    lookahead_weight=DEEP_LOOKAHEAD_WEIGHT,
                    max_lookahead_actions=DEEP_MAX_LOOKAHEAD_ACTIONS,
                    lookahead_depth=DEEP_LOOKAHEAD_DEPTH,
                    lookahead_branch_width=DEEP_LOOKAHEAD_BRANCH_WIDTH,
                    lookahead_key_decisions_only=DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY,
                    humanlike_prior_weight=DEEP_HUMANLIKE_PRIOR_WEIGHT,
                )
            return LookaheadRLPolicy(model=LinearQModel.load(path), rng=random.Random(seed), epsilon=0.0)
        except Exception:
            continue
    return RandomLegalPolicy(random.Random(seed))


def run_training(
    *,
    episodes: int,
    seed: int,
    model_out: str | Path,
    report_out: str | Path | None = None,
    alpha: float = 0.000003,
    gamma: float = 0.97,
    epsilon_start: float = 0.25,
    epsilon_end: float = 0.05,
    opponent: str = "greedy",
    use_greedy_prior: bool = True,
) -> dict[str, Any]:
    model = LinearQModel.greedy_prior() if use_greedy_prior else LinearQModel()
    model.metadata.update({"trainingSeed": seed, "opponent": opponent, "alpha": alpha, "gamma": gamma})
    rows: list[dict[str, Any]] = []
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    turns_total = 0
    for index in range(episodes):
        epsilon = _linear_decay(epsilon_start, epsilon_end, index, episodes)
        recorder = EpisodeRecorder()
        policy = RLPolicy(model=model, rng=random.Random(seed + index * 17), epsilon=epsilon, recorder=recorder)
        opponent_policy = _make_opponent_policy(opponent, seed + index * 31)
        results["played"] += 1
        try:
            winner, turns = play_one_game(seed + index, p1_policy=policy, p2_policy=opponent_policy)
            reward = _reward_for_winner(winner)
            recorder.apply_final_reward(model, reward=reward, gamma=gamma, alpha=alpha)
            results[winner] = results.get(winner, 0) + 1
            turns_total += turns
            rows.append({"episode": index + 1, "winner": winner, "turns": turns, "epsilon": epsilon, "reward": reward})
        except Exception as exc:  # pragma: no cover - report path for long training diagnostics
            recorder.apply_final_reward(model, reward=-1.0, gamma=gamma, alpha=alpha)
            results["errors"] += 1
            rows.append({
                "episode": index + 1,
                "winner": "error",
                "turns": 0,
                "epsilon": epsilon,
                "reward": -1.0,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=4),
            })
    model.episodes = episodes
    metadata = dict(model.metadata)
    metadata.update({
        "trainingSeed": seed,
        "opponent": opponent,
        "alpha": alpha,
        "gamma": gamma,
        "epsilonStart": epsilon_start,
        "epsilonEnd": epsilon_end,
        "greedyPrior": use_greedy_prior,
    })
    model.save(model_out, metadata=metadata)
    report = _training_report(
        seed=seed,
        episodes=episodes,
        model_out=model_out,
        alpha=alpha,
        gamma=gamma,
        epsilon_start=epsilon_start,
        epsilon_end=epsilon_end,
        opponent=opponent,
        use_greedy_prior=use_greedy_prior,
        results=results,
        turns_total=turns_total,
        rows=rows,
        model=model,
    )
    _write_report(report_out, report)
    return report


def run_evaluation(
    *,
    model_path: str | Path,
    episodes: int,
    seed: int = 20260523,
    opponent: str = "greedy",
    report_out: str | Path | None = None,
    learner_side: str = "P1",
    learner_recipe: dict[str, int] | None = None,
    learner_forces: list[str] | None = None,
    opponent_recipe: dict[str, int] | None = None,
    opponent_forces: list[str] | None = None,
) -> dict[str, Any]:
    learner_side = _normalise_learner_side(learner_side)
    model = LinearQModel.load(model_path)
    rows: list[dict[str, Any]] = []
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    turns_total = 0
    for index in range(episodes):
        policy = RLPolicy(model=model, rng=random.Random(seed + index * 19), epsilon=0.0)
        opponent_policy = _make_opponent_policy(opponent, seed + index * 37)
        if learner_side == "P1":
            p1_policy, p2_policy = policy, opponent_policy
            p1_recipe, p2_recipe = learner_recipe, opponent_recipe
            p1_forces, p2_forces = learner_forces, opponent_forces
        else:
            p1_policy, p2_policy = opponent_policy, policy
            p1_recipe, p2_recipe = opponent_recipe, learner_recipe
            p1_forces, p2_forces = opponent_forces, learner_forces
        results["played"] += 1
        try:
            winner, turns = play_one_game(
                seed + index,
                p1_recipe=p1_recipe,
                p2_recipe=p2_recipe,
                p1_forces=p1_forces,
                p2_forces=p2_forces,
                p1_policy=p1_policy,
                p2_policy=p2_policy,
            )
            results[winner] = results.get(winner, 0) + 1
            turns_total += turns
            rows.append({"game": index + 1, "winner": winner, "turns": turns})
        except Exception as exc:  # pragma: no cover - report path for long evaluation diagnostics
            results["errors"] += 1
            rows.append({
                "game": index + 1,
                "winner": "error",
                "turns": 0,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=4),
            })
    completed = max(1, results["P1"] + results["P2"] + results["tie"])
    report = {
        "kind": "rl_linear_evaluation",
        "createdAt": _utc_now(),
        "modelPath": str(model_path),
        "opponent": opponent,
        "learnerSide": learner_side,
        "games": episodes,
        "results": results,
        "winRate": results[learner_side] / completed,
        "averageTurns": turns_total / completed,
        "rowCount": len(rows),
        "rows": _compact_rows(rows),
        "decks": {
            "learner": _evaluation_deck_summary(learner_recipe, learner_forces),
            "opponent": _evaluation_deck_summary(opponent_recipe, opponent_forces),
        },
    }
    _write_report(report_out, report)
    return report


def _evaluation_deck_summary(recipe: dict[str, int] | None, forces: list[str] | None) -> dict[str, Any]:
    return {
        "cards": sum(recipe.values()) if recipe is not None else None,
        "forces": list(forces) if forces is not None else None,
    }


def _linear_decay(start: float, end: float, index: int, total: int) -> float:
    if total <= 1:
        return end
    progress = index / float(total - 1)
    return start + (end - start) * progress


def _make_opponent_policy(name: str, seed: int) -> Any:
    if name == "random":
        return RandomLegalPolicy(random.Random(seed))
    if name == "greedy":
        return GreedyLegalPolicy(random.Random(seed))
    raise ValueError(f"unknown opponent policy: {name}")


def _normalise_learner_side(side: str) -> str:
    cleaned = str(side).upper()
    if cleaned not in {"P1", "P2"}:
        raise ValueError(f"learner_side must be 'P1' or 'P2', got {side!r}")
    return cleaned


def _reward_for_winner(winner: str) -> float:
    if winner == "P1":
        return 1.0
    if winner == "P2":
        return -1.0
    return -0.2


def _training_report(
    *,
    seed: int,
    episodes: int,
    model_out: str | Path,
    alpha: float,
    gamma: float,
    epsilon_start: float,
    epsilon_end: float,
    opponent: str,
    use_greedy_prior: bool,
    results: dict[str, int],
    turns_total: int,
    rows: list[dict[str, Any]],
    model: LinearQModel,
) -> dict[str, Any]:
    completed = max(1, results["P1"] + results["P2"] + results["tie"])
    return {
        "kind": "rl_linear_training",
        "createdAt": _utc_now(),
        "seed": seed,
        "episodes": episodes,
        "modelPath": str(model_out),
        "config": {
            "alpha": alpha,
            "gamma": gamma,
            "epsilonStart": epsilon_start,
            "epsilonEnd": epsilon_end,
            "opponent": opponent,
            "greedyPrior": use_greedy_prior,
        },
        "results": results,
        "winRate": results["P1"] / completed,
        "averageTurns": turns_total / completed,
        "topWeights": model.top_weights(),
        "rowCount": len(rows),
        "rows": _compact_rows(rows),
    }


def _compact_rows(rows: list[dict[str, Any]], max_rows: int = 80) -> list[dict[str, Any]]:
    if len(rows) <= max_rows:
        return rows
    head_count = max_rows // 2
    tail_count = max_rows - head_count
    omitted = len(rows) - head_count - tail_count
    return rows[:head_count] + [{"omittedRows": omitted}] + rows[-tail_count:]


def _write_report(path: str | Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate a linear RL battle AI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser("train")
    train.add_argument("--episodes", type=int, default=200)
    train.add_argument("--seed", type=int, default=20260523)
    train.add_argument("--model-out", default="data/ai_models/rl_linear_latest.json")
    train.add_argument("--report-out", default="data/ai_training/rl_linear_latest.json")
    train.add_argument("--alpha", type=float, default=0.000003)
    train.add_argument("--gamma", type=float, default=0.97)
    train.add_argument("--epsilon-start", type=float, default=0.25)
    train.add_argument("--epsilon-end", type=float, default=0.05)
    train.add_argument("--opponent", choices=["random", "greedy"], default="greedy")
    train.add_argument("--no-greedy-prior", action="store_true")

    evaluate = subparsers.add_parser("eval")
    evaluate.add_argument("--model", required=True)
    evaluate.add_argument("--episodes", type=int, default=100)
    evaluate.add_argument("--seed", type=int, default=20260523)
    evaluate.add_argument("--opponent", choices=["random", "greedy"], default="greedy")
    evaluate.add_argument("--report-out")
    evaluate.add_argument("--learner-side", choices=["P1", "P2"], default="P1")

    args = parser.parse_args(argv)
    if args.command == "train":
        report = run_training(
            episodes=args.episodes,
            seed=args.seed,
            model_out=args.model_out,
            report_out=args.report_out,
            alpha=args.alpha,
            gamma=args.gamma,
            epsilon_start=args.epsilon_start,
            epsilon_end=args.epsilon_end,
            opponent=args.opponent,
            use_greedy_prior=not args.no_greedy_prior,
        )
    else:
        report = run_evaluation(
            model_path=args.model,
            episodes=args.episodes,
            seed=args.seed,
            opponent=args.opponent,
            report_out=args.report_out,
            learner_side=args.learner_side,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
