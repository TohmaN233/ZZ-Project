from __future__ import annotations

import argparse
import json
import random
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zz.ai import RandomLegalPolicy
from zz.action_records import (
    action_from_record as _shared_action_from_record,
    action_record_from_action,
    action_signature as _shared_action_signature,
    find_recorded_action,
    json_scalar as _shared_json_scalar,
)
from zz.decks import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
    build_deck,
)
from zz.engine import BASE_CAP, Engine, GameOver
from zz.enums import CardType, Color, Side
from zz.forces import ALL_FORCES
from zz.greedy_ai import GreedyLegalPolicy
from zz.model import Action, ForceInstance, GameState, Player
from zz.rl_ai import (
    FeatureExtractor,
    LinearQModel,
    RLPolicy,
    _compact_rows,
    _normalise_learner_side,
    _utc_now,
    action_choices_after_preinference,
    apply_public_deep_v2_planner_to_action_choices,
    run_evaluation,
    tactical_action_prior,
    target_choices_after_preinference,
    target_selection_player_for_context,
)
from zz.rl_ai import PositionEvaluator


SCHEMA_VERSION = 1
REWARD_VERSION = "resource_combo_v1"
RULE_VERSION = "zz-engine-current"
CARD_POOL_VERSION = "pc01-current"
TRAINING_MAX_TURNS = 30
TRAINING_MAX_ACTIONS = 500
OPPONENT_BEHAVIOR_PREFERENCE_VERSION = "opponent_behavior_preference_v1"
PUBLIC_POLICY_PREFERENCE_VERSION = "public_policy_preference_v1"


@dataclass(frozen=True)
class StateSnapshot:
    own_player_life: int
    enemy_player_life: int
    own_force_life_total: int
    enemy_force_life_total: int
    own_forces_alive: int
    enemy_forces_alive: int
    own_field_count: int
    enemy_field_count: int
    own_field_bp_total: int
    enemy_field_bp_total: int
    own_hand_size: int
    own_base_count: int
    own_trash_size: int
    turn: int
    own_movement_right_count: int = 0
    own_movement_right_total: int = 0
    own_playable_hand_count: int = 0
    own_base_growth_available: int = 0
    own_base_color_counts: tuple[tuple[str, int], ...] = ()
    own_ready_base_color_counts: tuple[tuple[str, int], ...] = ()
    own_hand_cost_color_counts: tuple[tuple[str, int], ...] = ()
    own_field_to_base_candidate_count: int = 0
    enemy_field_dp_total: int = 0

    @classmethod
    def from_engine(cls, engine: Engine, learner: Player) -> "StateSnapshot":
        enemy = next(player for player in engine.state.players if player is not learner)
        base_color_counts = _base_color_counts(engine, learner)
        return cls(
            own_player_life=int(getattr(learner, "life", 0)),
            enemy_player_life=int(getattr(enemy, "life", 0)),
            own_force_life_total=_force_life_total(learner),
            enemy_force_life_total=_force_life_total(enemy),
            own_forces_alive=_forces_alive(learner),
            enemy_forces_alive=_forces_alive(enemy),
            own_field_count=len(learner.field),
            enemy_field_count=len(enemy.field),
            own_field_bp_total=sum(ci.bp for ci in learner.field),
            enemy_field_bp_total=sum(ci.bp for ci in enemy.field),
            enemy_field_dp_total=sum(int(getattr(ci, "dp", getattr(getattr(ci, "card", None), "dp", 0))) for ci in enemy.field),
            own_hand_size=len(learner.hand),
            own_base_count=len(learner.base),
            own_trash_size=len(learner.trash),
            turn=engine.state.turn,
            own_movement_right_count=int(getattr(learner, "movement_right_count", 0)),
            own_movement_right_total=int(getattr(learner, "movement_right_total", 0)),
            own_base_color_counts=base_color_counts,
            own_ready_base_color_counts=_ready_base_color_counts(engine, learner),
            own_hand_cost_color_counts=_hand_cost_color_counts(learner),
            own_playable_hand_count=_playable_hand_count(base_color_counts, learner),
            own_base_growth_available=1 if _base_growth_available(learner) else 0,
            own_field_to_base_candidate_count=_field_to_base_candidate_count(engine, learner),
        )


def calculate_step_reward(before: StateSnapshot, after: StateSnapshot, action: Action) -> float:
    reward = 0.0
    reward += (before.enemy_player_life - after.enemy_player_life) * 0.02
    reward += (before.enemy_force_life_total - after.enemy_force_life_total) * 0.01
    reward += (before.enemy_forces_alive - after.enemy_forces_alive) * 0.08
    reward += (before.enemy_field_count - after.enemy_field_count) * 0.02
    reward += (before.enemy_field_bp_total - after.enemy_field_bp_total) / 50000.0
    reward -= (before.own_player_life - after.own_player_life) * 0.02
    reward -= (before.own_force_life_total - after.own_force_life_total) * 0.01
    reward -= (before.own_forces_alive - after.own_forces_alive) * 0.08
    reward -= (before.own_field_count - after.own_field_count) * 0.02
    if action.kind in {"play_card", "play_to_base", "move_card"}:
        if after.own_field_count > before.own_field_count or after.own_base_count > before.own_base_count:
            reward += 0.005
    if action.kind == "move_card" and _spent_movement_right(before, after):
        direction = str(action.payload.get("direction", ""))
        if direction == "base_to_field" and after.own_field_count > before.own_field_count:
            reward += 0.015
            if _enemy_lethal_player_pressure(before):
                reward += 0.035
            if after.own_playable_hand_count < before.own_playable_hand_count:
                reward -= 0.05
            if before.turn <= 5 and _ready_colored_count(after) == 0 and _colored_hand_demand_count(after) > 0:
                reward -= 0.06
        elif direction == "field_to_base" and after.own_base_count > before.own_base_count:
            reward += 0.035
            if before.own_base_count < 5:
                reward += 0.025
            if before.own_playable_hand_count == 0:
                reward += 0.01
            reward += _field_to_base_color_unlock_reward(before, after)
            if _enemy_lethal_player_pressure(before) and after.own_field_count < before.own_field_count:
                reward -= 0.09
        elif after.own_field_count > before.own_field_count or after.own_base_count > before.own_base_count:
            reward += 0.008
    if action.kind == "swap_mana_color":
        reward += _mana_swap_reward(before, after, action)
    reward += _resource_combo_reward_adjustment(before, after, action)
    if action.kind in {"end_turn", "flash_pass", "skip_mana"}:
        reward -= 0.002
    return max(-0.1, min(0.1, reward))


def target_selection_shaped_reward(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> float:
    if float(features.get("decision:generic_target", 0.0)) <= 0.0:
        return 0.0
    if float(features.get("target_effect_harmful", 0.0)) <= 0.0:
        return 0.0
    if float(features.get("target_own", 0.0)) > 0.0:
        reward = -0.08
        if _alt_has(alternatives, lambda alt: float(alt.get("target_enemy", 0.0)) > 0.0):
            reward -= 0.02
        return max(-0.1, reward)
    if float(features.get("target_enemy", 0.0)) <= 0.0:
        return 0.0
    threat = _target_threat_score(features)
    reward = 0.02 + min(0.055, threat * 0.05)
    if float(features.get("target_ready", 0.0)) > 0.0:
        reward += 0.01
    enemy_alternative_threats = [
        _target_threat_score(_alternative_features(alternative))
        for alternative in alternatives
        if float(_alternative_features(alternative).get("target_enemy", 0.0)) > 0.0
    ]
    if not enemy_alternative_threats or threat >= max(enemy_alternative_threats):
        reward += 0.01
    return min(0.1, reward)


def attack_target_shaped_reward(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> float:
    if float(features.get("decision:attack_target", 0.0)) <= 0.0:
        return 0.0
    if float(features.get("target_player_damage_prevented_by_force_kai", 0.0)) > 0.0:
        reward = -0.08
        if _alt_has(
            alternatives,
            lambda alt: float(alt.get("target_force_id:force_kai", 0.0)) > 0.0
            or float(alt.get("target_force", 0.0)) > 0.0,
        ):
            reward -= 0.02
        return max(-0.1, reward)
    if float(features.get("target_force_id:force_kai", 0.0)) > 0.0:
        if _alt_has(
            alternatives,
            lambda alt: float(alt.get("target_player_damage_prevented_by_force_kai", 0.0)) > 0.0,
        ):
            return 0.05
    return 0.0


def _target_threat_score(features: dict[str, Any]) -> float:
    return (
        float(features.get("target_dp", 0.0)) * 1.2
        + float(features.get("target_bp", 0.0)) * 0.8
        + float(features.get("target_cost", 0.0)) * 0.5
    )


def _spent_movement_right(before: StateSnapshot, after: StateSnapshot) -> bool:
    return _movement_right_count(before) > _movement_right_count(after)


def _movement_right_count(snapshot: StateSnapshot) -> int:
    return max(0, int(getattr(snapshot, "own_movement_right_count", 0)))


def _enemy_lethal_player_pressure(snapshot: StateSnapshot) -> bool:
    own_life = int(getattr(snapshot, "own_player_life", 0) or 0)
    if own_life <= 0 or int(getattr(snapshot, "own_forces_alive", 0) or 0) > 0:
        return False
    return int(getattr(snapshot, "enemy_field_dp_total", 0) or 0) >= own_life


def _mana_swap_reward(before: StateSnapshot, after: StateSnapshot, action: Action) -> float:
    new_color = _payload_color_key(action.payload.get("new_color"))
    if not new_color or new_color == "colorless":
        return 0.0
    if getattr(before, "own_base_growth_available", 0):
        return 0.0
    hand_demand = _count_lookup(before.own_hand_cost_color_counts, new_color)
    if hand_demand <= 0:
        return 0.0
    if after.own_playable_hand_count <= before.own_playable_hand_count:
        return 0.0
    before_base = _count_lookup(before.own_base_color_counts, new_color)
    after_base = _count_lookup(after.own_base_color_counts, new_color)
    if before_base <= 0 < after_base:
        return 0.03
    if after_base > before_base:
        return 0.015
    return 0.0


def _resource_combo_reward_adjustment(before: StateSnapshot, after: StateSnapshot, action: Action) -> float:
    reward = 0.0
    if action.kind == "end_turn":
        if _colored_hand_demand_count(after) > 0 and _ready_colored_count(after) == 0:
            reward -= 0.08
        elif _ready_demand_color_count(after) > 0:
            reward += 0.025
        if (
            before.turn <= 5
            and _movement_right_count(before) > 0
            and int(getattr(before, "own_field_to_base_candidate_count", 0)) > 0
            and before.own_base_count < 5
        ):
            reward -= 0.03
    if action.kind in {"play_card", "move_card"}:
        if _ready_colored_count(before) > 0 and _ready_colored_count(after) == 0 and _colored_hand_demand_count(after) > 0:
            reward -= 0.04
    if action.kind == "attack" and before.turn <= 5 and before.own_base_count < 5:
        enemy_damage = before.enemy_player_life - after.enemy_player_life
        force_damage = before.enemy_force_life_total - after.enemy_force_life_total
        removed_minions = before.enemy_field_count - after.enemy_field_count
        if (
            enemy_damage <= 0
            and force_damage <= 0
            and removed_minions <= 0
            and (
                getattr(before, "own_base_growth_available", 0)
                or int(getattr(before, "own_field_to_base_candidate_count", 0)) > 0
            )
        ):
            reward -= 0.035
    return reward


def _field_to_base_color_unlock_reward(before: StateSnapshot, after: StateSnapshot) -> float:
    reward = 0.0
    for color, demand in after.own_hand_cost_color_counts:
        if color == "colorless" or demand <= 0:
            continue
        if _count_lookup(after.own_base_color_counts, color) > _count_lookup(before.own_base_color_counts, color):
            reward += 0.025
        if _count_lookup(after.own_ready_base_color_counts, color) > _count_lookup(before.own_ready_base_color_counts, color):
            reward += 0.015
    return min(0.05, reward)


def _ready_colored_count(snapshot: StateSnapshot) -> int:
    return sum(count for color, count in snapshot.own_ready_base_color_counts if color != "colorless")


def _colored_hand_demand_count(snapshot: StateSnapshot) -> int:
    return sum(count for color, count in snapshot.own_hand_cost_color_counts if color != "colorless")


def _ready_demand_color_count(snapshot: StateSnapshot) -> int:
    return sum(
        min(count, _count_lookup(snapshot.own_hand_cost_color_counts, color))
        for color, count in snapshot.own_ready_base_color_counts
        if color != "colorless"
    )


def _base_color_counts(engine: Engine, player: Player) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for ci in getattr(player, "base", []):
        color = _snapshot_color_key(engine._mana_color_of(ci))
        counts[color] += 1
    return tuple(sorted(counts.items()))


def _ready_base_color_counts(engine: Engine, player: Player) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for ci in getattr(player, "base", []):
        if getattr(ci, "rested", False):
            continue
        color = _snapshot_color_key(engine._mana_color_of(ci))
        counts[color] += 1
    return tuple(sorted(counts.items()))


def _field_to_base_candidate_count(engine: Engine, player: Player) -> int:
    count = 0
    for ci in getattr(player, "field", []):
        if getattr(getattr(ci, "card", None), "is_token", False):
            continue
        if getattr(getattr(ci, "card", None), "type", None) is CardType.MANA_TOKEN:
            continue
        try:
            if engine._movement_locked(ci):
                continue
        except Exception:
            pass
        count += 1
    return count


def _hand_cost_color_counts(player: Player) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for item in getattr(player, "hand", []):
        card = getattr(item, "card", item)
        for color, amount in getattr(card, "cost", {}).items():
            color_key = _snapshot_color_key(color)
            if color_key == "colorless":
                continue
            counts[color_key] += int(amount)
    return tuple(sorted(counts.items()))


def _playable_hand_count(base_counts: tuple[tuple[str, int], ...], player: Player) -> int:
    counts = dict(base_counts)
    total = 0
    for item in getattr(player, "hand", []):
        card = getattr(item, "card", item)
        cost = getattr(card, "cost", {})
        if cost and _can_pay_from_color_counts(counts, cost):
            total += 1
    return total


def _base_growth_available(player: Player) -> bool:
    if len(getattr(player, "base", [])) >= BASE_CAP:
        return False
    return any(
        getattr(getattr(item, "card", item), "type", None) is CardType.B_MINION
        for item in getattr(player, "hand", [])
    )


def _can_pay_from_color_counts(counts: dict[str, int], cost: dict[Any, int]) -> bool:
    remaining = dict(counts)
    for color, amount in cost.items():
        color_key = _snapshot_color_key(color)
        if color_key == "colorless":
            continue
        if remaining.get(color_key, 0) < int(amount):
            return False
        remaining[color_key] -= int(amount)
    colorless_cost = sum(int(amount) for color, amount in cost.items() if _snapshot_color_key(color) == "colorless")
    return sum(remaining.values()) >= colorless_cost


def _count_lookup(counts: tuple[tuple[str, int], ...], key: str) -> int:
    return next((count for color, count in counts if color == key), 0)


def _payload_color_key(value: Any) -> str:
    if isinstance(value, Color):
        return _snapshot_color_key(value)
    try:
        return _snapshot_color_key(Color(value))
    except (TypeError, ValueError):
        return _snapshot_color_key(value)


def _snapshot_color_key(color: Any) -> str:
    label = getattr(color, "name", None)
    if not isinstance(label, str):
        label = getattr(color, "value", color)
    return str(label).lower()


class ActionMaskDiagnostics:
    def __init__(self) -> None:
        self.legal_action_count: Counter[int] = Counter()
        self.selected_rank: Counter[int] = Counter()
        self.action_kind: Counter[str] = Counter()
        self.non_pass_count: Counter[int] = Counter()
        self.invalid_action_attempts = 0

    def record_choice(
        self,
        *,
        legal_actions: list[Action],
        chosen: Action,
        scores: list[float],
        non_pass_count: int,
    ) -> int:
        self.legal_action_count[len(legal_actions)] += 1
        self.non_pass_count[non_pass_count] += 1
        self.action_kind[chosen.kind] += 1
        if chosen not in legal_actions:
            self.invalid_action_attempts += 1
            rank = len(legal_actions) + 1
        else:
            ordered = sorted(
                enumerate(scores),
                key=lambda item: (item[1], -item[0]),
                reverse=True,
            )
            chosen_index = legal_actions.index(chosen)
            rank = next((idx + 1 for idx, (score_index, _) in enumerate(ordered) if score_index == chosen_index), len(legal_actions))
        self.selected_rank[rank] += 1
        return rank

    def merge(self, other: "ActionMaskDiagnostics") -> None:
        self.legal_action_count.update(other.legal_action_count)
        self.selected_rank.update(other.selected_rank)
        self.action_kind.update(other.action_kind)
        self.non_pass_count.update(other.non_pass_count)
        self.invalid_action_attempts += other.invalid_action_attempts

    def summary(self) -> dict[str, Any]:
        return {
            "invalidActionAttempts": self.invalid_action_attempts,
            "legalActionCount": _counter_to_json(self.legal_action_count),
            "selectedRank": _counter_to_json(self.selected_rank),
            "actionKind": dict(sorted(self.action_kind.items())),
            "nonPassLegalActionCount": _counter_to_json(self.non_pass_count),
        }


@dataclass
class TrainingDecision:
    decision_index: int
    features: dict[str, float]
    action: dict[str, Any]
    legal_alternatives: list[dict[str, Any]]
    selected_rank: int
    legal_count: int
    step_reward: float = 0.0
    score: float = 0.0
    lookahead_delta: float = 0.0
    lookahead_score: float = 0.0
    engine_snapshot: Any | None = field(default=None, repr=False, compare=False)


class TrainingEpisodeRecorder:
    def __init__(self) -> None:
        self.decisions: list[TrainingDecision] = []
        self.diagnostics = ActionMaskDiagnostics()

    @property
    def total_shaped_reward(self) -> float:
        return sum(decision.step_reward for decision in self.decisions)

    def record_decision(self, decision: TrainingDecision) -> int:
        self.decisions.append(decision)
        return len(self.decisions) - 1

    def add_step_reward(self, decision_index: int | None, reward: float) -> None:
        if decision_index is None:
            return
        if 0 <= decision_index < len(self.decisions):
            self.decisions[decision_index].step_reward += reward

    def apply_rewards(self, model: LinearQModel, *, final_reward: float, gamma: float, alpha: float) -> None:
        target = final_reward
        for decision in reversed(self.decisions):
            target += decision.step_reward
            model.update(decision.features, target=target, alpha=alpha)
            target *= gamma

    def loss_trace(self) -> list[TrainingDecision]:
        return list(self.decisions)


def summarize_decision_resource_diagnostics(decisions: Iterable[TrainingDecision]) -> dict[str, Any]:
    summary: Counter[str] = Counter()
    for decision in decisions:
        features = getattr(decision, "features", {}) or {}
        action = getattr(decision, "action", {}) or {}
        payload = action.get("payload") or {}
        kind = str(action.get("kind") or "")
        direction = str(payload.get("direction") or "")
        summary["decisionCount"] += 1
        if float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0:
            summary["noReadyColoredManaForHandDecisionCount"] += 1
        if float(features.get("own_field_to_base_candidate_count", 0.0)) > 0.0:
            summary["fieldToBaseOpportunityDecisionCount"] += 1
        if kind == "play_card":
            if float(features.get("play_card_harmful_target_effect", 0.0)) > 0.0:
                summary["harmfulTargetEffectPlayCount"] += 1
            if float(features.get("play_card_harmful_target_only_own", 0.0)) > 0.0:
                summary["harmfulTargetOnlyOwnPlayCount"] += 1
            if float(features.get("play_card_harmful_no_enemy_target", 0.0)) > 0.0:
                summary["harmfulTargetNoEnemyPlayCount"] += 1
            if float(features.get("play_card_harmful_enemy_target_available", 0.0)) > 0.0:
                summary["harmfulTargetEnemyAvailablePlayCount"] += 1
            if float(features.get("play_card_with_turn_end_mana_refresh", 0.0)) > 0.0:
                summary["playCardWithTurnEndManaRefreshCount"] += 1
        if kind == "attack":
            summary["attackCount"] += 1
            if float(features.get("attack_nonlethal_with_low_base", 0.0)) > 0.0:
                summary["nonlethalLowBaseAttackCount"] += 1
            if float(features.get("attack_while_low_life_no_forces", 0.0)) > 0.0:
                summary["attackWhileLowLifeNoForcesCount"] += 1
            if float(features.get("attack_exposes_lethal_next_turn", 0.0)) > 0.0:
                summary["attackExposesLethalNextTurnCount"] += 1
            if float(features.get("attack_spends_force_life_exchange_combo_wall", 0.0)) > 0.0:
                summary["attackSpendsForceLifeExchangeComboWallCount"] += 1
            if float(features.get("attack_zero_dp", 0.0)) > 0.0:
                summary["zeroDpAttackCount"] += 1
            if float(features.get("attack_zero_dp_without_attack_payoff", 0.0)) > 0.0:
                summary["zeroDpAttackWithoutPayoffCount"] += 1
            if float(features.get("attack_low_dp_into_larger_blocker", 0.0)) > 0.0:
                summary["lowDpIntoLargerBlockerAttackCount"] += 1
            if float(features.get("attack_loses_to_larger_blocker_without_pressure", 0.0)) > 0.0:
                summary["largerBlockerSuicideAttackCount"] += 1
            if float(features.get("attack_with_turn_end_minion_refresh", 0.0)) > 0.0:
                summary["attackWithTurnEndMinionRefreshCount"] += 1
            if float(features.get("attack_suicide_into_larger_blocker_without_pressure", 0.0)) > 0.0:
                summary["suicideIntoLargerBlockerAttackCount"] += 1
        elif kind == "choose_attack_target":
            summary["attackTargetDecisionCount"] += 1
            if float(features.get("target_player_damage_prevented_by_force_kai", 0.0)) > 0.0:
                summary["attackPlayerDamagePreventedByForceCount"] += 1
        elif kind == "choose_blocker":
            if float(features.get("block_none_loses_force_life_exchange_resource", 0.0)) > 0.0:
                summary["blockNoneLosesForceLifeExchangeResourceCount"] += 1
            if float(features.get("blocker_preserves_force_life_exchange_resource", 0.0)) > 0.0:
                summary["blockerPreservesForceLifeExchangeResourceCount"] += 1
        elif kind == "move_card":
            if direction == "field_to_base":
                summary["fieldToBaseMoveCount"] += 1
                if float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) > 0.0:
                    summary["fieldToBaseUnderLethalPressureMoveCount"] += 1
                if float(features.get("move_field_to_base_spends_force_life_exchange_wall", 0.0)) > 0.0:
                    summary["fieldToBaseSpendsForceLifeExchangeWallCount"] += 1
            elif direction == "base_to_field":
                summary["baseToFieldMoveCount"] += 1
                if float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0:
                    summary["badBaseToFieldManaPullCount"] += 1
        elif kind == "swap_mana_color":
            summary["swapManaColorCount"] += 1
            if float(features.get("swap_mana_fallback_unsticks_hand", 0.0)) > 0.0:
                summary["swapManaFallbackUnsticksHandCount"] += 1
            if float(features.get("swap_mana_enables_playable_hand_card", 0.0)) > 0.0:
                summary["swapManaEnablesPlayableHandCount"] += 1
            if float(features.get("swap_mana_delays_base_growth", 0.0)) > 0.0:
                summary["swapManaDelaysBaseGrowthCount"] += 1
        elif kind == "end_turn":
            if float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0:
                summary["endTurnNoReadyColoredManaForHandCount"] += 1
            if (
                float(features.get("own_movement_right", 0.0)) > 0.0
                and float(features.get("own_field_to_base_candidate_count", 0.0)) > 0.0
            ):
                summary["endTurnWithUnusedMovementAndBaseCandidateCount"] += 1
    decision_count = max(1, int(summary["decisionCount"]))
    attack_count = max(1, int(summary["attackCount"]))
    field_to_base_opportunities = max(1, int(summary["fieldToBaseOpportunityDecisionCount"]))
    return {
        "decisionCount": int(summary["decisionCount"]),
        "attackCount": int(summary["attackCount"]),
        "nonlethalLowBaseAttackCount": int(summary["nonlethalLowBaseAttackCount"]),
        "nonlethalLowBaseAttackRate": int(summary["nonlethalLowBaseAttackCount"]) / attack_count,
        "attackWhileLowLifeNoForcesCount": int(summary["attackWhileLowLifeNoForcesCount"]),
        "attackExposesLethalNextTurnCount": int(summary["attackExposesLethalNextTurnCount"]),
        "attackSpendsForceLifeExchangeComboWallCount": int(summary["attackSpendsForceLifeExchangeComboWallCount"]),
        "fieldToBaseMoveCount": int(summary["fieldToBaseMoveCount"]),
        "fieldToBaseUnderLethalPressureMoveCount": int(summary["fieldToBaseUnderLethalPressureMoveCount"]),
        "fieldToBaseSpendsForceLifeExchangeWallCount": int(summary["fieldToBaseSpendsForceLifeExchangeWallCount"]),
        "baseToFieldMoveCount": int(summary["baseToFieldMoveCount"]),
        "badBaseToFieldManaPullCount": int(summary["badBaseToFieldManaPullCount"]),
        "fieldToBaseOpportunityDecisionCount": int(summary["fieldToBaseOpportunityDecisionCount"]),
        "fieldToBaseOpportunityUseRate": int(summary["fieldToBaseMoveCount"]) / field_to_base_opportunities,
        "noReadyColoredManaForHandDecisionCount": int(summary["noReadyColoredManaForHandDecisionCount"]),
        "noReadyColoredManaForHandDecisionRate": int(summary["noReadyColoredManaForHandDecisionCount"]) / decision_count,
        "endTurnNoReadyColoredManaForHandCount": int(summary["endTurnNoReadyColoredManaForHandCount"]),
        "endTurnWithUnusedMovementAndBaseCandidateCount": int(summary["endTurnWithUnusedMovementAndBaseCandidateCount"]),
        "harmfulTargetEffectPlayCount": int(summary["harmfulTargetEffectPlayCount"]),
        "harmfulTargetOnlyOwnPlayCount": int(summary["harmfulTargetOnlyOwnPlayCount"]),
        "harmfulTargetNoEnemyPlayCount": int(summary["harmfulTargetNoEnemyPlayCount"]),
        "harmfulTargetEnemyAvailablePlayCount": int(summary["harmfulTargetEnemyAvailablePlayCount"]),
        "zeroDpAttackCount": int(summary["zeroDpAttackCount"]),
        "zeroDpAttackWithoutPayoffCount": int(summary["zeroDpAttackWithoutPayoffCount"]),
        "lowDpIntoLargerBlockerAttackCount": int(summary["lowDpIntoLargerBlockerAttackCount"]),
        "largerBlockerSuicideAttackCount": int(summary["largerBlockerSuicideAttackCount"]),
        "suicideIntoLargerBlockerAttackCount": int(summary["suicideIntoLargerBlockerAttackCount"]),
        "attackTargetDecisionCount": int(summary["attackTargetDecisionCount"]),
        "attackPlayerDamagePreventedByForceCount": int(summary["attackPlayerDamagePreventedByForceCount"]),
        "blockNoneLosesForceLifeExchangeResourceCount": int(summary["blockNoneLosesForceLifeExchangeResourceCount"]),
        "blockerPreservesForceLifeExchangeResourceCount": int(summary["blockerPreservesForceLifeExchangeResourceCount"]),
        "attackWithTurnEndMinionRefreshCount": int(summary["attackWithTurnEndMinionRefreshCount"]),
        "playCardWithTurnEndManaRefreshCount": int(summary["playCardWithTurnEndManaRefreshCount"]),
        "swapManaColorCount": int(summary["swapManaColorCount"]),
        "swapManaFallbackUnsticksHandCount": int(summary["swapManaFallbackUnsticksHandCount"]),
        "swapManaEnablesPlayableHandCount": int(summary["swapManaEnablesPlayableHandCount"]),
        "swapManaDelaysBaseGrowthCount": int(summary["swapManaDelaysBaseGrowthCount"]),
    }


TACTICAL_LABEL_COUNT_KEYS = {
    "missedFieldToBaseSetup": "missedFieldToBaseSetupCount",
    "missedLateBaseToFieldTiming": "missedLateBaseToFieldTimingCount",
    "missedManaSwapFallback": "missedManaSwapFallbackCount",
    "badNonlethalAttackOverSetup": "badNonlethalAttackOverSetupCount",
    "lowLifeNoForceAttack": "lowLifeNoForceAttackCount",
    "attackExposesLethalNextTurn": "attackExposesLethalNextTurnCount",
    "attackSpendsForceLifeExchangeComboWall": "attackSpendsForceLifeExchangeComboWallCount",
    "zeroDpAttackWithoutPayoff": "zeroDpAttackWithoutPayoffCount",
    "lowDpIntoLargerBlockerAttack": "lowDpIntoLargerBlockerAttackCount",
    "suicideIntoLargerBlockerAttack": "suicideIntoLargerBlockerAttackCount",
    "attackPlayerDamagePreventedByForce": "attackPlayerDamagePreventedByForceCount",
    "fieldToBaseUnderLethalPressure": "fieldToBaseUnderLethalPressureCount",
    "fieldToBaseSpendsForceLifeExchangeWall": "fieldToBaseSpendsForceLifeExchangeWallCount",
    "fieldToBaseRemovesLastBlockerUnderPressure": "fieldToBaseRemovesLastBlockerUnderPressureCount",
    "badBaseToFieldManaPull": "badBaseToFieldManaPullCount",
    "attackIgnoresObservedAggressionDefense": "attackIgnoresObservedAggressionDefenseCount",
    "harmfulSelfTargetEffect": "harmfulSelfTargetEffectCount",
    "harmfulNoEnemyTargetEffect": "harmfulNoEnemyTargetEffectCount",
    "harmfulTargetOwnInsteadEnemy": "harmfulTargetOwnInsteadEnemyCount",
    "missedLethalBlock": "missedLethalBlockCount",
    "missedWinningBlock": "missedWinningBlockCount",
    "missedForceLifeExchangeBlock": "missedForceLifeExchangeBlockCount",
    "missedForceLifeExchangeSetupNoBlock": "missedForceLifeExchangeSetupNoBlockCount",
    "missedForceLifeExchangeSearchSupport": "missedForceLifeExchangeSearchSupportCount",
    "missedForceLifeExchangePlay": "missedForceLifeExchangePlayCount",
    "missedRestLockdown": "missedRestLockdownCount",
    "wastedDefensiveReactiveOwnTurn": "wastedDefensiveReactiveOwnTurnCount",
}


def summarize_decision_tactical_labels(decisions: Iterable[TrainingDecision]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    label_rows: list[dict[str, Any]] = []
    decision_count = 0
    for decision in decisions:
        decision_count += 1
        labels = decision_tactical_labels(decision)
        for label in labels:
            counts[label] += 1
        if labels:
            label_rows.append({
                "decisionIndex": int(getattr(decision, "decision_index", -1)),
                "action": getattr(decision, "action", {}),
                "labels": labels,
                "selectedRank": int(getattr(decision, "selected_rank", 0) or 0),
                "legalCount": int(getattr(decision, "legal_count", 0) or 0),
            })
    summary = {
        "decisionCount": decision_count,
        "labelCount": sum(counts.values()),
        "labelRows": _compact_rows(label_rows, max_rows=40),
    }
    for label, key in TACTICAL_LABEL_COUNT_KEYS.items():
        summary[key] = int(counts[label])
    return summary


def decision_tactical_labels(decision: TrainingDecision) -> list[str]:
    features = getattr(decision, "features", {}) or {}
    action = getattr(decision, "action", {}) or {}
    payload = action.get("payload") or {}
    alternatives = list(getattr(decision, "legal_alternatives", []) or [])
    kind = str(action.get("kind") or "")
    direction = str(payload.get("direction") or "")
    labels: list[str] = []
    if _missed_field_to_base_setup(features, alternatives, kind):
        labels.append("missedFieldToBaseSetup")
    if _missed_late_base_to_field_timing(features, alternatives, kind, direction):
        labels.append("missedLateBaseToFieldTiming")
    if _missed_mana_swap_fallback(features, alternatives, kind):
        labels.append("missedManaSwapFallback")
    if kind == "attack":
        if float(features.get("attack_nonlethal_with_low_base", 0.0)) > 0.0:
            labels.append("badNonlethalAttackOverSetup")
        if float(features.get("attack_while_low_life_no_forces", 0.0)) > 0.0:
            labels.append("lowLifeNoForceAttack")
        if float(features.get("attack_exposes_lethal_next_turn", 0.0)) > 0.0:
            labels.append("attackExposesLethalNextTurn")
        if float(features.get("attack_spends_force_life_exchange_combo_wall", 0.0)) > 0.0:
            labels.append("attackSpendsForceLifeExchangeComboWall")
        if float(features.get("attack_zero_dp_without_attack_payoff", 0.0)) > 0.0:
            labels.append("zeroDpAttackWithoutPayoff")
        if _low_dp_attack_into_larger_blocker_without_pressure(features):
            labels.append("lowDpIntoLargerBlockerAttack")
        if float(features.get("attack_suicide_into_larger_blocker_without_pressure", 0.0)) > 0.0:
            labels.append("suicideIntoLargerBlockerAttack")
        if _attack_ignores_observed_aggression_defense(features):
            labels.append("attackIgnoresObservedAggressionDefense")
    if kind == "choose_attack_target":
        if float(features.get("target_player_damage_prevented_by_force_kai", 0.0)) > 0.0:
            labels.append("attackPlayerDamagePreventedByForce")
    if (
        kind == "move_card"
        and direction == "field_to_base"
        and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) > 0.0
    ):
        labels.append("fieldToBaseUnderLethalPressure")
    if (
        kind == "move_card"
        and direction == "field_to_base"
        and float(features.get("move_field_to_base_spends_force_life_exchange_wall", 0.0)) > 0.0
    ):
        labels.append("fieldToBaseSpendsForceLifeExchangeWall")
    if (
        kind == "move_card"
        and direction == "field_to_base"
        and float(features.get("move_field_to_base_removes_last_blocker_under_enemy_pressure", 0.0)) > 0.0
        and not _field_to_base_last_blocker_exempt(features)
    ):
        labels.append("fieldToBaseRemovesLastBlockerUnderPressure")
    if kind == "move_card" and direction == "base_to_field" and _bad_base_to_field_mana_pull(features):
        labels.append("badBaseToFieldManaPull")
    if kind == "play_card":
        if float(features.get("play_card_harmful_target_only_own", 0.0)) > 0.0:
            labels.append("harmfulSelfTargetEffect")
        if float(features.get("play_card_harmful_no_enemy_target", 0.0)) > 0.0:
            labels.append("harmfulNoEnemyTargetEffect")
        if float(features.get("play_card_defensive_reactive_on_own_turn", 0.0)) > 0.0:
            labels.append("wastedDefensiveReactiveOwnTurn")
    if _missed_force_life_exchange_search_support(features, alternatives, kind):
        labels.append("missedForceLifeExchangeSearchSupport")
    if _missed_force_life_exchange_play(features, alternatives):
        labels.append("missedForceLifeExchangePlay")
    if _missed_rest_lockdown(features, alternatives, kind):
        labels.append("missedRestLockdown")
    if kind == "choose_target" and _harmful_target_own_instead_enemy(features, alternatives):
        labels.append("harmfulTargetOwnInsteadEnemy")
    if kind == "choose_blocker":
        if _missed_lethal_block(features, alternatives):
            labels.append("missedLethalBlock")
        if _missed_winning_block(features, alternatives):
            labels.append("missedWinningBlock")
        if _missed_force_life_exchange_block(features, alternatives):
            labels.append("missedForceLifeExchangeBlock")
        if _missed_force_life_exchange_setup_no_block(features, alternatives):
            labels.append("missedForceLifeExchangeSetupNoBlock")
    return labels


def tactical_preference_pairs(decisions: Iterable[TrainingDecision]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for decision in decisions:
        labels = decision_tactical_labels(decision)
        if not labels:
            continue
        alternative = _best_tactical_preference_alternative(decision, labels)
        if alternative is None:
            continue
        pairs.append({
            "decisionIndex": int(getattr(decision, "decision_index", -1)),
            "labels": list(labels),
            "badAction": getattr(decision, "action", {}),
            "goodAction": alternative.get("action", {}),
            "badFeatures": dict(getattr(decision, "features", {}) or {}),
            "goodFeatures": dict(alternative.get("features") or {}),
        })
    return pairs


def lookahead_preference_pairs(
    decisions: Iterable[TrainingDecision],
    *,
    min_adjusted_gap: float = 0.25,
    min_model_overturn_gap: float = 0.05,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for decision in decisions:
        selected_score = float(getattr(decision, "score", 0.0) or 0.0)
        selected_lookahead_score = float(getattr(decision, "lookahead_score", selected_score) or 0.0)
        candidates: list[dict[str, Any]] = []
        for alternative in list(getattr(decision, "legal_alternatives", []) or []):
            if "lookaheadScore" not in alternative:
                continue
            alternative_score = float(alternative.get("score", 0.0) or 0.0)
            alternative_lookahead_score = float(alternative.get("lookaheadScore", alternative_score) or 0.0)
            model_score_gap = alternative_score - selected_score
            lookahead_score_gap = selected_lookahead_score - alternative_lookahead_score
            if model_score_gap < float(min_model_overturn_gap):
                continue
            if lookahead_score_gap < float(min_adjusted_gap):
                continue
            candidates.append({
                "alternative": alternative,
                "modelScoreGap": model_score_gap,
                "lookaheadScoreGap": lookahead_score_gap,
            })
        if not candidates:
            continue
        best = max(candidates, key=lambda item: (item["modelScoreGap"], item["lookaheadScoreGap"]))
        alternative = best["alternative"]
        pairs.append({
            "decisionIndex": int(getattr(decision, "decision_index", -1)),
            "labels": ["lookaheadTeacherPreference"],
            "badAction": alternative.get("action", {}),
            "goodAction": getattr(decision, "action", {}),
            "badFeatures": dict(alternative.get("features") or {}),
            "goodFeatures": dict(getattr(decision, "features", {}) or {}),
            "modelScoreGap": float(best["modelScoreGap"]),
            "lookaheadScoreGap": float(best["lookaheadScoreGap"]),
        })
    return pairs


def public_deep_v2_planner_preference_pairs(decisions: Iterable[TrainingDecision]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for decision in decisions:
        choices = _decision_action_feature_choices(decision)
        if len(choices) < 2:
            continue
        enriched = apply_public_deep_v2_planner_to_action_choices(choices)
        selected_choices = [
            (action, features)
            for action, features in enriched
            if float(features.get("public_deep_v2_planner_selected", 0.0)) > 0.0
        ]
        if not selected_choices:
            continue
        selected_action, selected_features = selected_choices[0]
        selected_signature = _planner_action_signature(_action_to_dict(selected_action))
        current_signature = _planner_action_signature(getattr(decision, "action", {}) or {})
        if current_signature == selected_signature:
            continue
        bad_choices = [
            (action, features)
            for action, features in enriched
            if _planner_action_signature(_action_to_dict(action)) != selected_signature
        ]
        if not bad_choices:
            continue
        current_bad = next(
            (
                (action, features)
                for action, features in bad_choices
                if _planner_action_signature(_action_to_dict(action)) == current_signature
            ),
            None,
        )
        bad_action, bad_features = current_bad or bad_choices[0]
        pairs.append({
            "decisionIndex": int(getattr(decision, "decision_index", -1)),
            "labels": ["publicDeepV2PlannerPreference"],
            "goodAction": _action_to_dict(selected_action),
            "badAction": _action_to_dict(bad_action),
            "goodFeatures": dict(selected_features),
            "badFeatures": dict(bad_features),
        })
    return pairs


def _decision_action_feature_choices(decision: TrainingDecision) -> list[tuple[Action, dict[str, float]]]:
    choices: list[tuple[Action, dict[str, float]]] = []
    action = _action_from_decision_row(getattr(decision, "action", {}) or {})
    features = dict(getattr(decision, "features", {}) or {})
    if action is not None and features:
        choices.append((action, features))
    for alternative in list(getattr(decision, "legal_alternatives", []) or []):
        alt_action = _action_from_decision_row(alternative.get("action", {}) if isinstance(alternative, dict) else {})
        alt_features = dict(alternative.get("features") or {}) if isinstance(alternative, dict) else {}
        if alt_action is not None and alt_features:
            choices.append((alt_action, alt_features))
    return choices


def _action_from_decision_row(row: dict[str, Any]) -> Action | None:
    kind = str(row.get("kind") or "")
    if not kind:
        return None
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return Action(kind=kind, payload=dict(payload))


def _planner_action_signature(row: dict[str, Any]) -> tuple[str, tuple[tuple[str, Any], ...]]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return (
        str(row.get("kind") or ""),
        tuple(sorted((str(key), _json_scalar(value)) for key, value in payload.items())),
    )


def lookahead_value_target_rows(
    decisions: Iterable[TrainingDecision],
    *,
    min_abs_delta: float = 0.01,
    include_alternatives: bool = True,
) -> tuple[list[dict[str, float]], list[float]]:
    rows: list[dict[str, float]] = []
    targets: list[float] = []
    threshold = max(0.0, float(min_abs_delta))
    for decision in decisions:
        selected_delta = float(getattr(decision, "lookahead_delta", 0.0) or 0.0)
        selected_target = float(
            getattr(decision, "lookahead_score", getattr(decision, "score", 0.0)) or 0.0
        )
        if abs(selected_delta) >= threshold:
            rows.append(dict(getattr(decision, "features", {}) or {}))
            targets.append(selected_target)
        if not include_alternatives:
            continue
        for alternative in list(getattr(decision, "legal_alternatives", []) or []):
            if "lookaheadScore" not in alternative:
                continue
            alternative_score = float(alternative.get("score", 0.0) or 0.0)
            alternative_target = float(alternative.get("lookaheadScore", alternative_score) or 0.0)
            alternative_delta = float(
                alternative.get("lookaheadDelta", alternative_target - alternative_score) or 0.0
            )
            if abs(alternative_delta) < threshold:
                continue
            rows.append(dict(alternative.get("features") or {}))
            targets.append(alternative_target)
    return rows, targets


def deep_v2_multitask_rows(
    decisions: Iterable[TrainingDecision],
    *,
    final_reward: float,
    gamma: float = 0.97,
    min_lookahead_delta: float = 0.01,
) -> dict[str, Any]:
    decision_list = list(decisions)
    state_rows: list[dict[str, float]] = []
    state_targets: list[float] = []
    intent_rows: list[dict[str, float]] = []
    intent_targets: list[str] = []
    plan_rows: list[dict[str, float]] = []
    plan_targets: list[list[str]] = []
    discounted: list[float] = []
    target = float(final_reward)
    for decision in reversed(decision_list):
        target += float(getattr(decision, "step_reward", 0.0) or 0.0)
        discounted.append(target)
        target *= float(gamma)
    discounted.reverse()
    for decision, fallback_target in zip(decision_list, discounted, strict=True):
        features = dict(getattr(decision, "features", {}) or {})
        value_target = float(fallback_target)
        lookahead_delta = float(getattr(decision, "lookahead_delta", 0.0) or 0.0)
        if abs(lookahead_delta) >= float(min_lookahead_delta):
            value_target = float(getattr(decision, "lookahead_score", value_target) or value_target)
        state_rows.append(features)
        state_targets.append(value_target)
        intent = _deep_v2_intent_from_features(features)
        if intent:
            intent_rows.append(features)
            intent_targets.append(intent)
        plan_target = _deep_v2_plan_targets_from_features(features)
        if plan_target:
            plan_rows.append(features)
            plan_targets.append(plan_target)
    return {
        "stateRows": state_rows,
        "stateTargets": state_targets,
        "intentRows": intent_rows,
        "intentTargets": intent_targets,
        "planRows": plan_rows,
        "planTargets": plan_targets,
    }


def _deep_v2_intent_from_features(features: dict[str, float]) -> str | None:
    prefix = "planner_intent:"
    for key, value in sorted(features.items()):
        if key.startswith(prefix) and float(value) > 0.0:
            return key[len(prefix):]
    return None


def _deep_v2_plan_targets_from_features(features: dict[str, float]) -> list[str]:
    labels: list[str] = []
    for prefix in ("planner_label:", "planner_reason:", "planner_risk:"):
        for key, value in sorted(features.items()):
            if not key.startswith(prefix) or float(value) <= 0.0:
                continue
            label = key[len(prefix):]
            if label and label not in labels:
                labels.append(label)
    return labels


def policy_distillation_preference_pairs(
    decisions: Iterable[TrainingDecision],
    *,
    min_model_overturn_gap: float = 0.05,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for decision in decisions:
        selected_score = float(getattr(decision, "score", 0.0) or 0.0)
        candidates: list[dict[str, Any]] = []
        for alternative in list(getattr(decision, "legal_alternatives", []) or []):
            alternative_score = float(alternative.get("score", 0.0) or 0.0)
            model_score_gap = alternative_score - selected_score
            if model_score_gap < float(min_model_overturn_gap):
                continue
            candidates.append({
                "alternative": alternative,
                "modelScoreGap": model_score_gap,
            })
        if not candidates:
            continue
        best = max(candidates, key=lambda item: item["modelScoreGap"])
        alternative = best["alternative"]
        pairs.append({
            "decisionIndex": int(getattr(decision, "decision_index", -1)),
            "labels": ["runtimePolicyDistillationPreference"],
            "badAction": alternative.get("action", {}),
            "goodAction": getattr(decision, "action", {}),
            "badFeatures": dict(alternative.get("features") or {}),
            "goodFeatures": dict(getattr(decision, "features", {}) or {}),
            "modelScoreGap": float(best["modelScoreGap"]),
        })
    return pairs


def opponent_behavior_preference_pairs(*, repeats: int = 1) -> list[dict[str, Any]]:
    """Preference rows for reading opponent tempo from observed actions, not labels."""
    repeat_count = max(1, int(repeats))
    scenarios = [
        {
            "labels": ["observedAggressionDefenseScenario", "attackIgnoresObservedAggressionDefense"],
            "badAction": {"kind": "attack", "payload": {"attacker_iid": 1}},
            "goodAction": {"kind": "end_turn", "payload": {}},
            "badFeatures": {
                "action:attack": 1.0,
                "attack_has_lethal_player_target": 0.0,
                "attack_can_destroy_force": 0.0,
                "attack_while_low_life_no_forces": 1.0,
                "opponent_observed_action_count": 1.0,
                "opponent_observed_attack_rate": 0.85,
                "opponent_observed_early_attack_rate": 0.85,
                "opponent_observed_face_attack_rate": 0.8,
                "opponent_observed_base_to_field_rate": 0.5,
                "opponent_observed_aggression_index": 1.0,
                "opponent_observed_aggressive_pressure": 1.0,
                "own_player_life": 0.3,
                "own_forces_alive": 0.0,
                "own_field_count": 1.0,
                "enemy_field_dp_pressure": 0.75,
            },
            "goodFeatures": {
                "action:end_turn": 1.0,
                "opponent_observed_action_count": 1.0,
                "opponent_observed_attack_rate": 0.85,
                "opponent_observed_early_attack_rate": 0.85,
                "opponent_observed_face_attack_rate": 0.8,
                "opponent_observed_base_to_field_rate": 0.5,
                "opponent_observed_aggression_index": 1.0,
                "opponent_observed_aggressive_pressure": 1.0,
                "own_player_life": 0.3,
                "own_forces_alive": 0.0,
                "own_field_count": 1.0,
                "enemy_field_dp_pressure": 0.75,
            },
        },
        {
            "labels": ["observedAggressionDevelopBlockerScenario"],
            "badAction": {"kind": "attack", "payload": {"attacker_iid": 2}},
            "goodAction": {"kind": "play_card", "payload": {"iid": 3}},
            "badFeatures": {
                "action:attack": 1.0,
                "attack_low_dp_into_larger_blocker": 1.0,
                "attack_suicide_into_larger_blocker_without_pressure": 1.0,
                "attack_has_lethal_player_target": 0.0,
                "attack_can_destroy_force": 0.0,
                "opponent_observed_action_count": 1.0,
                "opponent_observed_attack_rate": 0.75,
                "opponent_observed_face_attack_rate": 0.7,
                "opponent_observed_aggression_index": 0.9,
                "opponent_observed_aggressive_pressure": 1.0,
                "own_player_life": 0.35,
                "own_forces_alive": 0.0,
                "own_hand_size": 0.5,
                "enemy_field_dp_pressure": 0.65,
            },
            "goodFeatures": {
                "action:play_card": 1.0,
                "play_card_is_minion": 1.0,
                "opponent_observed_action_count": 1.0,
                "opponent_observed_attack_rate": 0.75,
                "opponent_observed_face_attack_rate": 0.7,
                "opponent_observed_aggression_index": 0.9,
                "opponent_observed_aggressive_pressure": 1.0,
                "own_player_life": 0.35,
                "own_forces_alive": 0.0,
                "own_hand_size": 0.5,
                "enemy_field_dp_pressure": 0.65,
            },
        },
        {
            "labels": ["observedAggressionKeepDefendersScenario", "fieldToBaseUnderLethalPressure"],
            "badAction": {"kind": "move_card", "payload": {"direction": "field_to_base", "iid": 4}},
            "goodAction": {"kind": "move_card", "payload": {"direction": "base_to_field", "iid": 5}},
            "badFeatures": {
                "action:move_card": 1.0,
                "move_field_to_base": 1.0,
                "move_field_to_base_under_enemy_pressure": 1.0,
                "move_field_to_base_exposes_lethal_pressure": 1.0,
                "opponent_observed_action_count": 1.0,
                "opponent_observed_attack_rate": 0.8,
                "opponent_observed_base_to_field_rate": 0.7,
                "opponent_observed_aggression_index": 1.0,
                "opponent_observed_aggressive_pressure": 1.0,
                "own_player_life": 0.25,
                "own_forces_alive": 0.0,
                "own_field_count": 1.0,
                "enemy_field_dp_pressure": 1.0,
            },
            "goodFeatures": {
                "action:move_card": 1.0,
                "move_base_to_field": 1.0,
                "move_base_to_field_can_block": 1.0,
                "opponent_observed_action_count": 1.0,
                "opponent_observed_attack_rate": 0.8,
                "opponent_observed_base_to_field_rate": 0.7,
                "opponent_observed_aggression_index": 1.0,
                "opponent_observed_aggressive_pressure": 1.0,
                "own_player_life": 0.25,
                "own_forces_alive": 0.0,
                "own_field_count": 2.0,
                "enemy_field_dp_pressure": 1.0,
            },
        },
    ]
    pairs: list[dict[str, Any]] = []
    for _ in range(repeat_count):
        for scenario in scenarios:
            pairs.append({
                "decisionIndex": -1,
                "labels": list(scenario["labels"]),
                "badAction": dict(scenario["badAction"]),
                "goodAction": dict(scenario["goodAction"]),
                "badFeatures": dict(scenario["badFeatures"]),
                "goodFeatures": dict(scenario["goodFeatures"]),
                "source": OPPONENT_BEHAVIOR_PREFERENCE_VERSION,
            })
    return pairs


def public_policy_preference_pairs(*, repeats: int = 1) -> list[dict[str, Any]]:
    """Curated public Deep rows for basic tactical habits not sampled often enough."""
    repeat_count = max(1, int(repeats))
    scenarios = [
        {
            "labels": ["optionalMovementRightHoldScenario", "badBaseToFieldManaPull"],
            "badAction": {"kind": "move_card", "payload": {"direction": "base_to_field", "iid": 10}},
            "goodAction": {"kind": "end_turn", "payload": {}},
            "badFeatures": {
                "action:move_card": 1.0,
                "move_base_to_field": 1.0,
                "move_base_to_field_b_minion": 1.0,
                "move_base_to_field_cannot_block": 1.0,
                "move_base_to_field_spends_ready_mana": 1.0,
                "move_base_to_field_colored_mana": 1.0,
                "move_base_to_field_with_playable_hand": 1.0,
                "move_base_to_field_immediate_attack_payoff": 0.0,
                "move_base_to_field_low_impact_mana_minion": 1.0,
                "own_movement_right": 0.5,
            },
            "goodFeatures": {
                "action:end_turn": 1.0,
                "is_end_or_pass": 1.0,
                "own_movement_right": 0.5,
                "own_ready_colored_mana_count": 0.3,
                "own_playable_hand_count": 0.3,
            },
        },
        {
            "labels": ["lateBaseToFieldTimingScenario", "missedLateBaseToFieldTiming"],
            "badAction": {"kind": "end_turn", "payload": {}},
            "goodAction": {"kind": "move_card", "payload": {"direction": "base_to_field", "iid": 16}},
            "badFeatures": {
                "action:end_turn": 1.0,
                "is_end_or_pass": 1.0,
                "own_base_count": 0.8,
                "own_no_ready_colored_mana_for_hand": 0.0,
                "own_movement_right": 0.5,
            },
            "goodFeatures": {
                "action:move_card": 1.0,
                "move_base_to_field": 1.0,
                "move_base_to_field_can_block": 1.0,
                "own_base_count": 0.7,
                "own_movement_right": 0.5,
            },
        },
        {
            "labels": ["forceKaiPreventedFaceScenario", "attackPlayerDamagePreventedByForce"],
            "badAction": {"kind": "choose_attack_target", "payload": {"target": "player"}},
            "goodAction": {"kind": "choose_attack_target", "payload": {"target": "force_kai"}},
            "badFeatures": {
                "decision:attack_target": 1.0,
                "target_player": 1.0,
                "target_player_damage_prevented_by_force_kai": 1.0,
                "attacker_dp": 0.2,
            },
            "goodFeatures": {
                "decision:attack_target": 1.0,
                "target_force": 1.0,
                "target_force_id:force_kai": 1.0,
                "target_can_be_destroyed_by_attacker": 1.0,
            },
        },
        {
            "labels": ["largerReadyBlockerScenario", "suicideIntoLargerBlockerAttack"],
            "badAction": {"kind": "attack", "payload": {"attacker_iid": 11}},
            "goodAction": {"kind": "end_turn", "payload": {}},
            "badFeatures": {
                "action:attack": 1.0,
                "attack_larger_ready_blocker_count": 0.4,
                "attack_larger_blocker_bp_gap": 0.6,
                "attack_has_lethal_player_target": 0.0,
                "attack_can_destroy_force": 0.0,
                "attack_suicide_into_larger_blocker_without_pressure": 1.0,
            },
            "goodFeatures": {
                "action:end_turn": 1.0,
                "is_end_or_pass": 1.0,
                "own_field_count": 0.4,
            },
        },
        {
            "labels": ["defensiveReactiveHoldScenario", "wastedDefensiveReactiveOwnTurn"],
            "badAction": {"kind": "play_card", "payload": {"iid": 12}},
            "goodAction": {"kind": "end_turn", "payload": {}},
            "badFeatures": {
                "action:play_card": 1.0,
                "play_card_target_effect": 1.0,
                "play_card_beneficial_target_effect": 1.0,
                "play_card_defensive_reactive": 1.0,
                "play_card_defensive_reactive_on_own_turn": 1.0,
                "play_card_defensive_reactive_attack_payoff": 0.0,
            },
            "goodFeatures": {
                "action:end_turn": 1.0,
                "is_end_or_pass": 1.0,
                "own_hand_size": 0.4,
            },
        },
        {
            "labels": ["harmfulTargetEnemyScenario", "harmfulTargetOwnInsteadEnemy"],
            "badAction": {"kind": "choose_target", "payload": {"target": "own_minion"}},
            "goodAction": {"kind": "choose_target", "payload": {"target": "enemy_minion"}},
            "badFeatures": {
                "decision:generic_target": 1.0,
                "target_effect_harmful": 1.0,
                "target_own": 1.0,
                "target_enemy": 0.0,
                "target_ready": 0.0,
                "target_dp": 0.2,
                "target_bp": 0.2,
            },
            "goodFeatures": {
                "decision:generic_target": 1.0,
                "target_effect_harmful": 1.0,
                "target_own": 0.0,
                "target_enemy": 1.0,
                "target_ready": 1.0,
                "target_dp": 0.6,
                "target_bp": 0.7,
            },
        },
        {
            "labels": ["mustBlockLethalScenario", "missedLethalBlock"],
            "badAction": {"kind": "choose_blocker", "payload": {"blocker": None}},
            "goodAction": {"kind": "choose_blocker", "payload": {"blocker": "winning_blocker"}},
            "badFeatures": {
                "decision:blocker": 1.0,
                "block:none": 1.0,
                "block_none_allows_lethal_player_damage": 1.0,
                "own_forces_alive": 0.0,
                "own_player_life": 0.2,
            },
            "goodFeatures": {
                "decision:blocker": 1.0,
                "blocker_prevents_lethal_player_damage": 1.0,
                "blocker_cleanly_beats_attacker": 1.0,
                "target_can_be_destroyed_by_attacker": 0.0,
            },
        },
        {
            "labels": ["contestedBaseAttackPayoffScenario", "badBaseToFieldManaPull"],
            "badAction": {"kind": "move_card", "payload": {"direction": "base_to_field", "iid": 13}},
            "goodAction": {"kind": "play_card", "payload": {"iid": 14}},
            "badFeatures": {
                "action:move_card": 1.0,
                "move_base_to_field": 1.0,
                "move_base_to_field_colored_mana": 1.0,
                "move_base_to_field_spends_ready_mana": 1.0,
                "move_base_to_field_with_playable_hand": 1.0,
                "move_base_to_field_can_attack_player": 1.0,
                "move_base_to_field_attack_payoff_contested_by_larger_blocker": 1.0,
                "enemy_ready_larger_blocker_count": 0.4,
            },
            "goodFeatures": {
                "action:play_card": 1.0,
                "play_card_is_minion": 1.0,
                "own_ready_colored_mana_count": 0.3,
                "own_playable_hand_count": 0.3,
            },
        },
        {
            "labels": ["lastBlockerHoldScenario", "fieldToBaseRemovesLastBlockerUnderPressure"],
            "badAction": {"kind": "move_card", "payload": {"direction": "field_to_base", "iid": 15}},
            "goodAction": {"kind": "end_turn", "payload": {}},
            "badFeatures": {
                "action:move_card": 1.0,
                "move_field_to_base": 1.0,
                "move_field_to_base_removes_last_blocker_under_enemy_pressure": 1.0,
                "enemy_field_dp_pressure": 0.7,
                "own_forces_alive": 0.5,
            },
            "goodFeatures": {
                "action:end_turn": 1.0,
                "is_end_or_pass": 1.0,
                "own_field_count": 0.2,
                "own_forces_alive": 0.5,
            },
        },
    ]
    pairs: list[dict[str, Any]] = []
    for _ in range(repeat_count):
        for scenario in scenarios:
            pairs.append({
                "decisionIndex": -1,
                "labels": list(scenario["labels"]),
                "badAction": dict(scenario["badAction"]),
                "goodAction": dict(scenario["goodAction"]),
                "badFeatures": dict(scenario["badFeatures"]),
                "goodFeatures": dict(scenario["goodFeatures"]),
                "source": PUBLIC_POLICY_PREFERENCE_VERSION,
            })
    return pairs


def _best_tactical_preference_alternative(
    decision: TrainingDecision,
    labels: list[str],
) -> dict[str, Any] | None:
    alternatives = list(getattr(decision, "legal_alternatives", []) or [])
    if not alternatives:
        return None
    scored = [
        (_tactical_preference_alternative_score(labels, alternative), alternative)
        for alternative in alternatives
    ]
    scored = [(score, alternative) for score, alternative in scored if score > 0.0]
    if not scored:
        return None
    return max(scored, key=lambda item: (item[0], float(item[1].get("score", 0.0))))[1]


def _tactical_preference_alternative_score(labels: list[str], alternative: dict[str, Any]) -> float:
    features = _alternative_features(alternative)
    action = alternative.get("action") or {}
    kind = str(action.get("kind") or "")
    payload = action.get("payload") or {}
    direction = str(payload.get("direction") or "")
    score = tactical_action_prior(features)
    if "missedFieldToBaseSetup" in labels:
        if float(features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0:
            score += 12.0
        elif float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0:
            score += 10.0
        elif (
            float(features.get("move_field_to_base", 0.0)) > 0.0
            and float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0
        ):
            score += 8.0
    if "missedLateBaseToFieldTiming" in labels:
        if kind == "move_card" and direction == "base_to_field":
            score += 16.0
            score += _late_base_to_field_timing_payoff_score(features)
        elif kind == "move_card" and direction == "field_to_base":
            score -= 12.0
        elif kind == "end_turn":
            score -= 8.0
    if "missedManaSwapFallback" in labels:
        if float(features.get("swap_mana_fallback_unsticks_hand", 0.0)) > 0.0:
            score += 10.0
        if float(features.get("swap_mana_enables_playable_hand_card", 0.0)) > 0.0:
            score += 8.0
    if any(label in labels for label in (
        "badNonlethalAttackOverSetup",
        "lowLifeNoForceAttack",
        "attackExposesLethalNextTurn",
        "attackSpendsForceLifeExchangeComboWall",
        "zeroDpAttackWithoutPayoff",
        "lowDpIntoLargerBlockerAttack",
        "suicideIntoLargerBlockerAttack",
        "attackIgnoresObservedAggressionDefense",
    )):
        if kind != "attack":
            score += 6.0
        if "attackExposesLethalNextTurn" in labels:
            score += 4.0
        if "lowLifeNoForceAttack" in labels:
            score += 2.0
        if "attackSpendsForceLifeExchangeComboWall" in labels:
            score += 3.0
        if float(features.get("move_field_to_base", 0.0)) > 0.0:
            score += 5.0
        if float(features.get("play_card_force_life_exchange_sets_enemy_low_life", 0.0)) > 0.0:
            score += 12.0
        if float(features.get("play_card_force_life_exchange_has_followup_damage", 0.0)) > 0.0:
            score += 8.0
        if float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0:
            score += 5.0
        if float(features.get("attack_zero_dp_without_attack_payoff", 0.0)) > 0.0:
            score -= 30.0
        if float(features.get("attack_low_dp_into_larger_blocker", 0.0)) > 0.0:
            score -= 16.0
        if float(features.get("attack_exposes_lethal_next_turn", 0.0)) > 0.0:
            score -= 30.0
        if float(features.get("attack_suicide_into_larger_blocker_without_pressure", 0.0)) > 0.0:
            score -= 30.0
        if "attackIgnoresObservedAggressionDefense" in labels:
            if float(features.get("play_card_is_minion", 0.0)) > 0.0:
                score += 5.0
            if float(features.get("move_base_to_field", 0.0)) > 0.0:
                score += 5.0
    if "attackPlayerDamagePreventedByForce" in labels:
        if float(features.get("target_force_id:force_kai", 0.0)) > 0.0:
            score += 20.0
        elif float(features.get("target_force", 0.0)) > 0.0:
            score += 12.0
        if float(features.get("target_player_damage_prevented_by_force_kai", 0.0)) > 0.0:
            score -= 30.0
    if "fieldToBaseUnderLethalPressure" in labels:
        if float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) > 0.0:
            score -= 40.0
        elif float(features.get("move_field_to_base", 0.0)) > 0.0:
            score -= 12.0
        if kind in {"end_turn", "play_card"}:
            score += 8.0
        if float(features.get("move_base_to_field", 0.0)) > 0.0:
            score += 8.0
        if float(features.get("play_card_is_minion", 0.0)) > 0.0:
            score += 5.0
    if "fieldToBaseSpendsForceLifeExchangeWall" in labels:
        if float(features.get("move_field_to_base_spends_force_life_exchange_wall", 0.0)) > 0.0:
            score -= 35.0
        if kind in {"end_turn", "play_card"}:
            score += 8.0
        if float(features.get("play_card_is_minion", 0.0)) > 0.0:
            score += 6.0
    if "fieldToBaseRemovesLastBlockerUnderPressure" in labels:
        if float(features.get("move_field_to_base_removes_last_blocker_under_enemy_pressure", 0.0)) > 0.0:
            score -= 35.0
        if kind in {"end_turn", "play_card"}:
            score += 8.0
        if float(features.get("play_card_is_minion", 0.0)) > 0.0:
            score += 6.0
        if float(features.get("move_base_to_field_can_block", 0.0)) > 0.0:
            score += 6.0
    if "badBaseToFieldManaPull" in labels:
        if float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0:
            score -= 40.0
        if float(features.get("move_base_to_field_attack_payoff_contested_by_larger_blocker", 0.0)) > 0.0:
            score -= 40.0
        if kind != "move_card" or direction != "base_to_field":
            score += 8.0
        if float(features.get("move_field_to_base", 0.0)) > 0.0:
            score += 6.0
        if kind in {"end_turn", "play_card", "play_to_base"}:
            score += 4.0
    if any(label in labels for label in (
        "harmfulSelfTargetEffect",
        "harmfulNoEnemyTargetEffect",
        "harmfulTargetOwnInsteadEnemy",
    )):
        if float(features.get("target_enemy", 0.0)) > 0.0:
            score += 12.0
        if float(features.get("target_own", 0.0)) > 0.0:
            score -= 20.0
        if kind not in {"play_card", "activate_flash_ability", "choose_target"}:
            score += 3.0
    if "wastedDefensiveReactiveOwnTurn" in labels:
        if kind not in {"play_card", "activate_flash_ability"}:
            score += 8.0
        if float(features.get("play_card_defensive_reactive_on_enemy_turn", 0.0)) > 0.0:
            score += 4.0
        if float(features.get("play_card_defensive_reactive_attack_payoff", 0.0)) > 0.0:
            score += 4.0
        if float(features.get("play_card_defensive_reactive_on_own_turn", 0.0)) > 0.0:
            score -= 30.0
    if "missedLethalBlock" in labels:
        if float(features.get("blocker_prevents_lethal_player_damage", 0.0)) > 0.0:
            score += 15.0
        if float(features.get("blocker_prevents_turn_lethal_player_damage", 0.0)) > 0.0:
            score += 13.0
        if kind == "choose_blocker" and not features.get("block:none", 0.0):
            score += 3.0
    if "missedWinningBlock" in labels:
        if float(features.get("blocker_cleanly_beats_attacker", 0.0)) > 0.0:
            score += 12.0
        elif float(features.get("blocker_trades_with_attacker", 0.0)) > 0.0:
            score += 8.0
    if "missedForceLifeExchangeBlock" in labels:
        if float(features.get("blocker_preserves_force_life_exchange_resource", 0.0)) > 0.0:
            score += 22.0
        if float(features.get("block_none_loses_force_life_exchange_resource", 0.0)) > 0.0:
            score -= 40.0
    if "missedForceLifeExchangeSetupNoBlock" in labels:
        if float(features.get("block_none_lowers_force_life_exchange_resource", 0.0)) > 0.0:
            score += 26.0
        if float(features.get("blocker_prevents_force_life_exchange_setup_damage", 0.0)) > 0.0:
            score -= 35.0
    if "missedForceLifeExchangeSearchSupport" in labels:
        if float(features.get("play_card_force_life_exchange_search_support", 0.0)) > 0.0:
            score += 24.0
        if float(features.get("play_card_force_life_exchange_search_for_deck_piece", 0.0)) > 0.0:
            score += 8.0
        if kind != "play_card":
            score -= 8.0
    if "missedForceLifeExchangePlay" in labels:
        if float(features.get("play_card_force_life_exchange_sets_enemy_low_life", 0.0)) > 0.0:
            score += 36.0
        if float(features.get("play_card_force_life_exchange_has_followup_damage", 0.0)) > 0.0:
            score += 12.0
        if float(features.get("play_card_exchange_player_force_life", 0.0)) > 0.0:
            score += 8.0
        if kind != "play_card":
            score -= 10.0
    if "missedRestLockdown" in labels:
        if float(features.get("play_card_rest_lockdown_on_own_turn", 0.0)) > 0.0:
            score += 26.0
            score += float(features.get("play_card_rest_lockdown_enemy_ready_targets", 0.0)) * 8.0
        if kind != "play_card":
            score -= 8.0
    return score


def _alternative_features(alternative: dict[str, Any]) -> dict[str, Any]:
    return dict(alternative.get("features") or {})


def _alt_has(alternatives: list[dict[str, Any]], predicate: Any) -> bool:
    return any(predicate(_alternative_features(alternative)) for alternative in alternatives)


def _missed_field_to_base_setup(features: dict[str, Any], alternatives: list[dict[str, Any]], kind: str) -> bool:
    if kind == "move_card" and float(features.get("move_field_to_base", 0.0)) > 0.0:
        return False
    has_setup_need = (
        float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0
        or float(features.get("own_field_to_base_candidate_count", 0.0)) > 0.0
    )
    if not has_setup_need:
        return False
    return _alt_has(
        alternatives,
        _safe_field_to_base_setup_alternative,
    )


def _missed_late_base_to_field_timing(
        features: dict[str, Any],
        alternatives: list[dict[str, Any]],
        kind: str,
        direction: str,
) -> bool:
    if _own_base_count_from_features(features) < 7.0:
        return False
    if float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0:
        return False
    if kind == "move_card" and direction == "base_to_field":
        return False
    if kind == "move_card" and direction == "field_to_base" and _late_field_to_base_timing_exempt(features):
        return False
    return any(_late_base_to_field_timing_alternative(alternative) for alternative in alternatives)


def _own_base_count_from_features(features: dict[str, Any]) -> float:
    value = float(features.get("own_base_count", 0.0) or 0.0)
    if value <= 1.0:
        return value * 10.0
    return value


def _late_field_to_base_timing_exempt(features: dict[str, Any]) -> bool:
    return (
        float(features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0
        or float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0
        or float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) > 0.0
    )


def _late_base_to_field_timing_alternative(alternative: dict[str, Any]) -> bool:
    action = alternative.get("action") or {}
    payload = action.get("payload") or {}
    direction = str(payload.get("direction") or "")
    features = _alternative_features(alternative)
    if str(action.get("kind") or "") != "move_card" or direction != "base_to_field":
        return False
    if float(features.get("move_base_to_field", 0.0)) <= 0.0:
        return False
    if float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0:
        return False
    if _base_to_field_removes_critical_color(features):
        return False
    return _late_base_to_field_timing_payoff_score(features) > 0.0


def _base_to_field_removes_critical_color(features: dict[str, Any]) -> bool:
    if float(features.get("move_base_to_field_only_ready_color_for_hand", 0.0)) > 0.0:
        return True
    return (
        float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0
        and (
            float(features.get("move_base_to_field_spends_ready_mana", 0.0)) > 0.0
            or float(features.get("move_base_to_field_with_playable_hand", 0.0)) > 0.0
        )
        and float(features.get("move_base_to_field_can_block", 0.0)) <= 0.0
        and float(features.get("move_base_to_field_can_attack_player", 0.0)) <= 0.0
        and float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) <= 0.0
    )


def _late_base_to_field_timing_payoff_score(features: dict[str, Any]) -> float:
    score = 0.0
    if float(features.get("move_base_to_field_can_block", 0.0)) > 0.0:
        score += 5.0
    if float(features.get("move_base_to_field_under_observed_aggression_defense_need", 0.0)) > 0.0:
        score += 4.0
    if float(features.get("move_base_to_field_can_attack_player", 0.0)) > 0.0:
        score += 4.0
    if float(features.get("move_base_to_field_immediate_attack_payoff", 0.0)) > 0.0:
        score += 6.0
    if float(features.get("move_base_to_field_attack_payoff_contested_by_larger_blocker", 0.0)) > 0.0:
        score -= 6.0
    if float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0:
        score -= 8.0
    if _base_to_field_removes_critical_color(features):
        score -= 8.0
    return score


def _safe_field_to_base_setup_alternative(features: dict[str, Any]) -> bool:
    if float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) > 0.0:
        return False
    return (
        float(features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0
        or (
            float(features.get("move_field_to_base", 0.0)) > 0.0
            and float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0
        )
    )


def _missed_mana_swap_fallback(features: dict[str, Any], alternatives: list[dict[str, Any]], kind: str) -> bool:
    if kind == "swap_mana_color":
        return False
    if float(features.get("own_no_ready_colored_mana_for_hand", 0.0)) <= 0.0:
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("swap_mana_fallback_unsticks_hand", 0.0)) > 0.0
        or float(alt.get("swap_mana_enables_playable_hand_card", 0.0)) > 0.0,
    )


def _missed_force_life_exchange_search_support(
        features: dict[str, Any],
        alternatives: list[dict[str, Any]],
        kind: str,
) -> bool:
    if kind == "play_card" and float(features.get("play_card_force_life_exchange_search_support", 0.0)) > 0.0:
        return False
    if float(features.get("own_has_force_life_exchange_plan", 0.0)) <= 0.0:
        return False
    if float(features.get("own_deck_has_force_life_exchange", 0.0)) <= 0.0:
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("play_card_force_life_exchange_search_support", 0.0)) > 0.0,
    )


def _missed_force_life_exchange_play(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> bool:
    if float(features.get("play_card_force_life_exchange_sets_enemy_low_life", 0.0)) > 0.0:
        return False
    if float(features.get("attack_has_lethal_player_target", 0.0)) > 0.0:
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("play_card_force_life_exchange_sets_enemy_low_life", 0.0)) > 0.0,
    )


def _missed_rest_lockdown(features: dict[str, Any], alternatives: list[dict[str, Any]], kind: str) -> bool:
    if kind == "play_card" and float(features.get("play_card_rest_lockdown_on_own_turn", 0.0)) > 0.0:
        return False
    if float(features.get("enemy_field_dp_pressure", 0.0)) <= 0.0:
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("play_card_rest_lockdown_on_own_turn", 0.0)) > 0.0,
    )


def _bad_base_to_field_mana_pull(features: dict[str, Any]) -> bool:
    if float(features.get("move_base_to_field_low_impact_mana_minion", 0.0)) > 0.0:
        return True
    if float(features.get("move_base_to_field", 0.0)) <= 0.0:
        return False
    if (
        float(features.get("move_base_to_field_attack_payoff_contested_by_larger_blocker", 0.0)) > 0.0
        and float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0
        and (
            float(features.get("move_base_to_field_spends_ready_mana", 0.0)) > 0.0
            or float(features.get("move_base_to_field_with_playable_hand", 0.0)) > 0.0
        )
    ):
        return True
    if float(features.get("move_base_to_field_can_attack_player", 0.0)) > 0.0:
        return False
    return (
        float(features.get("move_base_to_field_colored_mana", 0.0)) > 0.0
        and float(features.get("move_base_to_field_only_ready_color_for_hand", 0.0)) > 0.0
        and (
            float(features.get("move_base_to_field_cannot_block", 0.0)) > 0.0
            or float(features.get("move_base_to_field_with_playable_hand", 0.0)) > 0.0
        )
    )


def _field_to_base_last_blocker_exempt(features: dict[str, Any]) -> bool:
    if float(features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0:
        return True
    return (
        float(features.get("move_field_to_base_early_curve_exempt", 0.0)) > 0.0
        or (
            float(features.get("move_field_to_base_under_curve", 0.0)) > 0.0
            and float(features.get("move_field_to_base_future_play", 0.0)) > 0.0
            and float(features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
            and float(features.get("own_turn", 0.0)) <= 3.0
        )
    )


def _harmful_target_own_instead_enemy(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> bool:
    if float(features.get("target_effect_harmful", 0.0)) <= 0.0:
        return False
    if float(features.get("target_own", 0.0)) <= 0.0:
        return False
    return _alt_has(alternatives, lambda alt: float(alt.get("target_enemy", 0.0)) > 0.0)


def _low_dp_attack_into_larger_blocker_without_pressure(features: dict[str, Any]) -> bool:
    if float(features.get("attack_low_dp_into_larger_blocker", 0.0)) <= 0.0:
        return False
    if float(features.get("attack_multi_attacker_pressure_outnumbers_blockers", 0.0)) > 0.0:
        return False
    if float(features.get("attack_has_lethal_player_target", 0.0)) > 0.0:
        return False
    if float(features.get("attack_can_destroy_force", 0.0)) > 0.0:
        return False
    return True


def _attack_ignores_observed_aggression_defense(features: dict[str, Any]) -> bool:
    if float(features.get("attack_under_observed_aggression_defense_need", 0.0)) > 0.0:
        return True
    return (
        float(features.get("opponent_observed_aggressive_pressure", 0.0)) > 0.0
        and float(features.get("own_player_life", 1.0)) <= 0.4
        and float(features.get("own_forces_alive", 1.0)) <= 0.0
        and float(features.get("attack_has_lethal_player_target", 0.0)) <= 0.0
        and float(features.get("attack_can_destroy_force", 0.0)) <= 0.0
    )


def _missed_lethal_block(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> bool:
    if (
        float(features.get("block_none_allows_lethal_player_damage", 0.0)) <= 0.0
        and float(features.get("block_none_allows_turn_lethal_player_damage", 0.0)) <= 0.0
    ):
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("blocker_prevents_lethal_player_damage", 0.0)) > 0.0
        or float(alt.get("blocker_prevents_turn_lethal_player_damage", 0.0)) > 0.0
        or float(alt.get("blocker_cleanly_beats_attacker", 0.0)) > 0.0
        or float(alt.get("blocker_trades_with_attacker", 0.0)) > 0.0,
    )


def _missed_winning_block(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> bool:
    if float(features.get("blocker_cleanly_beats_attacker", 0.0)) > 0.0:
        return False
    if float(features.get("blocker_trades_with_attacker", 0.0)) > 0.0:
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("blocker_cleanly_beats_attacker", 0.0)) > 0.0
        or float(alt.get("blocker_trades_with_attacker", 0.0)) > 0.0,
    )


def _missed_force_life_exchange_block(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> bool:
    if float(features.get("block_none_loses_force_life_exchange_resource", 0.0)) <= 0.0:
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("blocker_preserves_force_life_exchange_resource", 0.0)) > 0.0,
    )


def _missed_force_life_exchange_setup_no_block(features: dict[str, Any], alternatives: list[dict[str, Any]]) -> bool:
    if float(features.get("blocker_prevents_force_life_exchange_setup_damage", 0.0)) <= 0.0:
        return False
    return _alt_has(
        alternatives,
        lambda alt: float(alt.get("block_none_lowers_force_life_exchange_resource", 0.0)) > 0.0,
    )


def rank_counterfactual_alternatives(decision: TrainingDecision) -> list[dict[str, Any]]:
    alternatives = list(getattr(decision, "legal_alternatives", []) or [])
    return sorted(
        alternatives,
        key=lambda alternative: (
            _counterfactual_resource_priority(decision, alternative),
            float(alternative.get("score", 0.0)),
        ),
        reverse=True,
    )


def _counterfactual_resource_priority(decision: TrainingDecision, alternative: dict[str, Any]) -> float:
    decision_features = getattr(decision, "features", {}) or {}
    alt_features = alternative.get("features") or {}
    action = alternative.get("action") or {}
    payload = action.get("payload") or {}
    kind = str(action.get("kind") or "")
    direction = str(payload.get("direction") or "")
    priority = 0.0
    stuck_for_color = float(decision_features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0
    base_candidate = float(decision_features.get("own_field_to_base_candidate_count", 0.0)) > 0.0
    if kind == "move_card" and direction == "field_to_base":
        priority += 6.0
        if float(alt_features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) > 0.0:
            priority -= 14.0
        if (
            float(alt_features.get("move_field_to_base_protects_high_value_attacker", 0.0)) > 0.0
            and float(alt_features.get("move_field_to_base_exposes_lethal_pressure", 0.0)) <= 0.0
        ):
            priority += 4.0
        if base_candidate:
            priority += 2.0
        if float(alt_features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0:
            priority += 5.0
        elif float(alt_features.get("move_field_to_base_matches_hand_color", 0.0)) > 0.0:
            priority += 2.5
    elif kind in {"play_to_base", "place_colorless_mana"}:
        priority += 3.0
    elif kind == "swap_mana_color":
        priority += 2.0
        if stuck_for_color and float(alt_features.get("swap_mana_to_missing_hand_color", 0.0)) > 0.0:
            priority += 4.0
        if float(alt_features.get("swap_mana_enables_playable_hand_card", 0.0)) > 0.0:
            priority += 2.0
    elif kind == "attack":
        priority -= 1.0
        if stuck_for_color or base_candidate:
            priority -= 2.0
    elif kind in {"end_turn", "flash_pass", "skip_mana"}:
        priority -= 3.0
    if stuck_for_color and kind not in {"end_turn", "flash_pass", "skip_mana"}:
        priority += 0.5
    return priority


_BEAM_KEY_ACTION_KINDS = {
    "attack",
    "move_card",
    "play_card",
    "activate_flash_ability",
    "swap_mana_color",
}

_BEAM_KEY_FEATURES = (
    "decision:blocker",
    "decision:attack_target",
    "decision:generic_target",
    "play_card_harmful_enemy_target_available",
    "play_card_harmful_target_only_own",
    "play_card_harmful_no_enemy_target",
    "play_card_target_effect_no_eligible_targets",
    "move_field_to_base",
    "move_field_to_base_spends_force_life_exchange_wall",
    "move_field_to_base_protects_high_value_attacker",
    "move_base_to_field",
    "move_base_to_field_low_impact_mana_minion",
    "move_base_to_field_only_ready_color_for_hand",
    "attack_nonlethal_with_low_base",
    "attack_spends_force_life_exchange_combo_wall",
    "attack_zero_dp_without_attack_payoff",
    "block_none_allows_lethal_player_damage",
    "block_none_allows_turn_lethal_player_damage",
    "blocker_prevents_turn_lethal_player_damage",
    "block_none_loses_force_life_exchange_resource",
    "blocker_preserves_force_life_exchange_resource",
)


def _is_beam_key_action_kind(kind: str) -> bool:
    return kind in _BEAM_KEY_ACTION_KINDS


def _counterfactual_snapshot_candidate(
    selected_features: dict[str, float],
    alternatives: list[dict[str, Any]],
    selected_rank: int,
) -> bool:
    if not alternatives:
        return False
    if int(selected_rank) > 1:
        return True
    key_features = (
        "own_no_ready_colored_mana_for_hand",
        "own_field_to_base_candidate_count",
        "enemy_pressure_high_player_risk",
        "enemy_pressure_near_player_lethal",
        "attack_exposes_lethal_next_turn",
        "attack_zero_dp_without_attack_payoff",
        "attack_loses_to_larger_blocker_without_pressure",
        "play_card_harmful_target_only_own",
        "play_card_harmful_no_enemy_target",
        "play_card_harmful_enemy_target_available",
        "play_card_target_effect",
        "play_card_defensive_reactive_effect",
    )
    if any(float(selected_features.get(key, 0.0) or 0.0) > 0.0 for key in key_features):
        return True
    if float(selected_features.get("action:end_turn", 0.0) or 0.0) > 0.0:
        if float(selected_features.get("own_field_to_base_candidate_count", 0.0) or 0.0) > 0.0:
            return True
        if float(selected_features.get("own_no_ready_colored_mana_for_hand", 0.0) or 0.0) > 0.0:
            return True
    for alternative in alternatives[:4]:
        action = alternative.get("action") if isinstance(alternative.get("action"), dict) else {}
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        alt_features = alternative.get("features") if isinstance(alternative.get("features"), dict) else {}
        if action.get("kind") == "move_card" and payload.get("direction") == "field_to_base":
            if float(alt_features.get("move_field_to_base_restores_missing_hand_color", 0.0) or 0.0) > 0.0:
                return True
            if float(selected_features.get("own_no_ready_colored_mana_for_hand", 0.0) or 0.0) > 0.0:
                return True
        if action.get("kind") == "swap_mana_color":
            if float(alt_features.get("swap_mana_to_missing_hand_color", 0.0) or 0.0) > 0.0:
                return True
        if float(alt_features.get("play_card_beneficial_remove_threat", 0.0) or 0.0) > 0.0:
            return True
    return False


def _aux_action_decision_kind(action_kind: str) -> str:
    if action_kind == "choose_attack_target":
        return "attack_target"
    if action_kind == "choose_blocker":
        return "blocker"
    if action_kind == "choose_target":
        return "generic_target"
    if action_kind == "choose_replacement":
        return "replacement"
    if action_kind == "swap_mana_color":
        return "color_swap"
    return "unknown"


class InstrumentedRLPolicy(RLPolicy):
    def __init__(
        self,
        *,
        recorder: TrainingEpisodeRecorder,
        lookahead_weight: float = 0.0,
        max_lookahead_actions: int = 0,
        evaluator: PositionEvaluator | None = None,
        capture_decision_snapshots: bool = False,
        max_decision_snapshots: int = 12,
        beam_lookahead_width: int = 0,
        beam_lookahead_depth: int = 1,
        beam_key_decisions_only: bool = True,
        action_set_recorder: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(recorder=None, **kwargs)
        self.training_recorder = recorder
        self.last_main_decision_index: int | None = None
        self.lookahead_weight = float(lookahead_weight)
        self.max_lookahead_actions = max(0, int(max_lookahead_actions))
        self.position_evaluator = evaluator or PositionEvaluator()
        self.capture_decision_snapshots = bool(capture_decision_snapshots)
        self.max_decision_snapshots = max(0, int(max_decision_snapshots))
        self._decision_snapshot_count = 0
        self.beam_lookahead_width = max(0, int(beam_lookahead_width))
        self.beam_lookahead_depth = max(1, int(beam_lookahead_depth))
        self.beam_key_decisions_only = bool(beam_key_decisions_only)
        self.action_set_recorder = action_set_recorder

    def choose(self, engine: Engine) -> Action:
        self._enable_observed_opponent_features(engine)
        legal = engine.legal_actions()
        if not legal:
            raise RuntimeError("no legal action")
        player = getattr(engine.state, "active", None)
        choices = [(action, self.extractor.features_for_action(engine, player, action)) for action in legal]
        choices = action_choices_after_preinference(choices)
        if self.use_public_deep_v2_planner:
            choices = apply_public_deep_v2_planner_to_action_choices(choices)
        legal = [action for action, _features in choices]
        scores = [self._score_features(features) for _, features in choices]
        lookahead_indexes = self._lookahead_indexes(scores)
        lookahead_deltas = [0.0 for _ in choices]
        adjusted_scores = list(scores)
        for index in lookahead_indexes:
            lookahead_deltas[index] = self._lookahead_delta(
                engine,
                player,
                choices[index][0],
                choices[index][1],
            )
            adjusted_scores[index] = scores[index] + self.lookahead_weight * lookahead_deltas[index]
        if self.rng.random() < self.epsilon:
            chosen_index = self.rng.randrange(len(choices))
        else:
            chosen_index = max(
                range(len(choices)),
                key=lambda index: (adjusted_scores[index], self.rng.random()),
            )
        chosen, features = choices[chosen_index]
        non_pass_count = sum(1 for action in legal if action.kind not in {"end_turn", "flash_pass", "skip_mana"})
        selected_rank = self.training_recorder.diagnostics.record_choice(
            legal_actions=legal,
            chosen=chosen,
            scores=scores,
            non_pass_count=non_pass_count,
        )
        alternatives = [
            {
                "action": _action_to_dict(action, engine=engine, player=player),
                "features": dict(action_features),
                "score": scores[index],
                "lookaheadDelta": lookahead_deltas[index],
                "lookaheadScore": adjusted_scores[index],
            }
            for index, (action, action_features) in enumerate(choices)
            if index != chosen_index
        ]
        alternatives.sort(key=lambda item: item["score"], reverse=True)
        engine_snapshot = None
        if (
            self.capture_decision_snapshots
            and self._decision_snapshot_count < self.max_decision_snapshots
            and _counterfactual_snapshot_candidate(features, alternatives, selected_rank)
        ):
            engine_snapshot = _copy_engine_for_replay(engine)
            if engine_snapshot is not None:
                self._decision_snapshot_count += 1
        decision_index = len(self.training_recorder.decisions)
        decision = TrainingDecision(
            decision_index=decision_index,
            features=dict(features),
            action=_action_to_dict(chosen, engine=engine, player=player),
            legal_alternatives=alternatives,
            selected_rank=selected_rank,
            legal_count=len(legal),
            score=scores[chosen_index],
            lookahead_delta=lookahead_deltas[chosen_index],
            lookahead_score=adjusted_scores[chosen_index],
            engine_snapshot=engine_snapshot,
        )
        self.last_main_decision_index = self.training_recorder.record_decision(decision)
        if self.action_set_recorder is not None:
            self.action_set_recorder.record_decision(
                engine,
                player,
                legal,
                teacher_scores=adjusted_scores,
                selected_action_slot=chosen_index,
                decision_kind="main",
                raw_scores=scores,
                lookahead_deltas=lookahead_deltas,
                metadata={"decisionIndex": decision_index},
            )
        return chosen

    def choose_blocker(self, engine: Any, attacker: Any, blockers: list[Any]):
        if not blockers:
            return None
        player = getattr(blockers[0], "owner", getattr(getattr(engine, "state", None), "active", None))
        none_features = self.extractor.features_for_no_blocker(engine, player, attacker)
        choices: list[tuple[Any, dict[str, float]]] = [(None, none_features)]
        for blocker in blockers:
            choices.append((blocker, self.extractor.features_for_blocker(engine, player, attacker, blocker)))
        return self._choose_aux_scored(
            "choose_blocker",
            choices,
            payload_extra={"attacker": self._choice_payload(attacker)},
            engine=engine,
            player=player,
        )

    def choose_attack_target(self, engine: Any, attacker: Any, targets: list[Any]) -> Any:
        player = getattr(attacker, "owner", getattr(getattr(engine, "state", None), "active", None))
        choices = [
            (target, self.extractor.features_for_attack_target(engine, player, attacker, target))
            for target in targets
        ]
        return self._choose_aux_scored(
            "choose_attack_target",
            choices,
            payload_extra={"attacker": self._choice_payload(attacker)},
            engine=engine,
            player=player,
        )

    def choose_target(self, engine: Any, kind: str, min_n: int, max_n: int, eligible: list[Any]) -> list[Any]:
        if not eligible or max_n <= 0:
            return []
        player = target_selection_player_for_context(engine)
        raw_choices = [
            (target, self.extractor.features_for_generic_target(engine, player, kind, target))
            for target in eligible
        ]
        choices = target_choices_after_preinference(raw_choices, min_n=min_n)
        if not choices:
            return []
        scored = self._scored_choices(choices)
        all_scored = self._scored_choices(raw_choices)
        ordered = sorted(range(len(scored)), key=lambda index: (scored[index][2], self.rng.random()), reverse=True)
        count = max(min_n, min(max_n, len(ordered)))
        selected_indexes = ordered[:count]
        for selected_index in selected_indexes:
            chosen_choice = scored[selected_index][0]
            record_scored = [scored[selected_index]] + [
                row for row in all_scored if row[0] is not chosen_choice
            ]
            self._record_aux_decision(
                action_kind="choose_target",
                scored_choices=record_scored,
                chosen_index=0,
                payload_extra={"target_kind": str(kind)},
                engine=engine,
                player=player,
            )
        return [scored[index][0] for index in selected_indexes]

    def _choose_aux_scored(
        self,
        action_kind: str,
        choices: list[tuple[Any, dict[str, float]]],
        *,
        payload_extra: dict[str, Any] | None = None,
        engine: Any | None = None,
        player: Any | None = None,
    ) -> Any:
        if not choices:
            raise RuntimeError("no legal choices")
        choices = action_choices_after_preinference(choices)
        scored = self._scored_choices(choices)
        if self.rng.random() < self.epsilon:
            chosen_index = self.rng.randrange(len(scored))
        else:
            chosen_index = max(range(len(scored)), key=lambda index: (scored[index][2], self.rng.random()))
        self._record_aux_decision(
            action_kind=action_kind,
            scored_choices=scored,
            chosen_index=chosen_index,
            payload_extra=payload_extra or {},
            engine=engine,
            player=player,
        )
        return scored[chosen_index][0]

    def _scored_choices(self, choices: list[tuple[Any, dict[str, float]]]) -> list[tuple[Any, dict[str, float], float]]:
        return [(choice, features, self._score_features(features)) for choice, features in choices]

    def _record_aux_decision(
        self,
        *,
        action_kind: str,
        scored_choices: list[tuple[Any, dict[str, float], float]],
        chosen_index: int,
        payload_extra: dict[str, Any],
        engine: Any | None = None,
        player: Any | None = None,
    ) -> None:
        choice, features, _score = scored_choices[chosen_index]
        ordered_indexes = sorted(range(len(scored_choices)), key=lambda index: scored_choices[index][2], reverse=True)
        selected_rank = ordered_indexes.index(chosen_index) + 1 if chosen_index in ordered_indexes else len(scored_choices)
        alternatives = [
            {
                "action": self._choice_action_record(action_kind, alt_choice, payload_extra=payload_extra),
                "features": dict(alt_features),
                "score": alt_score,
            }
            for index, (alt_choice, alt_features, alt_score) in enumerate(scored_choices)
            if index != chosen_index
        ]
        alternatives.sort(key=lambda item: item["score"], reverse=True)
        if action_kind == "choose_target":
            step_reward = target_selection_shaped_reward(features, alternatives)
        elif action_kind == "choose_attack_target":
            step_reward = attack_target_shaped_reward(features, alternatives)
        else:
            step_reward = 0.0
        decision_index = len(self.training_recorder.decisions)
        decision = TrainingDecision(
            decision_index=decision_index,
            features=dict(features),
            action=self._choice_action_record(action_kind, choice, payload_extra=payload_extra),
            legal_alternatives=alternatives,
            selected_rank=selected_rank,
            legal_count=len(scored_choices),
            step_reward=step_reward,
        )
        self.training_recorder.record_decision(decision)
        self._record_aux_action_set_decision(
            engine=engine,
            player=player,
            action_kind=action_kind,
            scored_choices=scored_choices,
            chosen_index=chosen_index,
            payload_extra=payload_extra,
            decision_index=decision_index,
        )

    def _record_aux_action_set_decision(
        self,
        *,
        engine: Any | None,
        player: Any | None,
        action_kind: str,
        scored_choices: list[tuple[Any, dict[str, float], float]],
        chosen_index: int,
        payload_extra: dict[str, Any],
        decision_index: int,
    ) -> None:
        if self.action_set_recorder is None or engine is None or player is None:
            return
        actions = [
            _action_from_dict(self._choice_action_record(action_kind, choice, payload_extra=payload_extra))
            for choice, _features, _score in scored_choices
        ]
        scores = [float(score) for _choice, _features, score in scored_choices]
        self.action_set_recorder.record_decision(
            engine,
            player,
            actions,
            teacher_scores=scores,
            selected_action_slot=chosen_index,
            decision_kind=_aux_action_decision_kind(action_kind),
            raw_scores=scores,
            metadata={
                "decisionIndex": decision_index,
                "teacherScoreMode": "aux_model_score",
            },
        )

    def _choice_action_record(
        self,
        action_kind: str,
        choice: Any,
        *,
        payload_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(payload_extra or {})
        payload.update(self._choice_payload(choice))
        return {"kind": action_kind, "payload": payload}

    def _choice_payload(self, choice: Any) -> dict[str, Any]:
        if choice is None:
            return {"block_none": True}
        ref = getattr(choice, "ref", None)
        if ref is not None:
            payload = {"attack_target_kind": str(getattr(getattr(choice, "kind", ""), "name", getattr(choice, "kind", "")))}
            payload.update(self._choice_payload(ref))
            return payload
        card = getattr(choice, "card", None)
        payload: dict[str, Any] = {}
        iid = getattr(choice, "iid", None)
        if iid is not None:
            payload["iid"] = int(iid)
        if card is not None:
            payload["card_id"] = str(getattr(card, "id", ""))
            payload["bp"] = int(getattr(choice, "bp", getattr(card, "bp", 0)) or 0)
            payload["dp"] = int(getattr(choice, "dp", getattr(card, "dp", 0)) or 0)
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

    def _lookahead_indexes(self, scores: list[float]) -> set[int]:
        if self.lookahead_weight == 0.0 or self.max_lookahead_actions <= 0:
            return set()
        return {
            index
            for index, _ in sorted(
                enumerate(scores),
                key=lambda item: (item[1], -item[0]),
                reverse=True,
            )[: self.max_lookahead_actions]
        }

    def _lookahead_delta(
        self,
        engine: Engine,
        player: Player,
        action: Action,
        features: dict[str, float] | None = None,
    ) -> float:
        if (
            self.beam_lookahead_width > 0
            and self.beam_lookahead_depth > 1
            and self._beam_enabled_for_action(action, features or {})
        ):
            return self._beam_lookahead_delta(engine, player, action)
        return self._one_step_lookahead_delta(engine, player, action)

    def _one_step_lookahead_delta(self, engine: Engine, player: Player, action: Action) -> float:
        try:
            import copy

            player_index = list(getattr(engine.state, "players", [])).index(player)
            before = self.position_evaluator.evaluate(engine, player)
            clone = copy.deepcopy(engine)
            if hasattr(clone, "state") and hasattr(clone.state, "engine"):
                clone.state.engine = clone
            if hasattr(clone, "rebind_passive_modifiers"):
                clone.rebind_passive_modifiers()
            clone_player = clone.state.players[player_index]
            try:
                clone.apply(copy.deepcopy(action))
            except GameOver as game_over:
                if game_over.winner is clone_player:
                    return 100.0
                if game_over.winner is None:
                    return -5.0
                return -100.0
            after = self.position_evaluator.evaluate(clone, clone_player)
            return max(-50.0, min(50.0, after - before))
        except Exception:
            return 0.0

    def _beam_enabled_for_action(self, action: Action, features: dict[str, float]) -> bool:
        if not self.beam_key_decisions_only:
            return True
        if _is_beam_key_action_kind(str(getattr(action, "kind", ""))):
            return True
        return any(float(features.get(key, 0.0)) > 0.0 for key in _BEAM_KEY_FEATURES)

    def _beam_lookahead_delta(self, engine: Engine, player: Player, action: Action) -> float:
        try:
            player_index = list(getattr(engine.state, "players", [])).index(player)
            before = self.position_evaluator.evaluate(engine, player)
            root = self._lookahead_clone(engine)
            root_player = root.state.players[player_index]
            try:
                root.apply(self._copy_action(action))
            except GameOver as game_over:
                return self._game_over_lookahead_value(game_over, root_player)
            leaf = self._beam_leaf_value(root, player_index, self.beam_lookahead_depth - 1)
            return max(-50.0, min(50.0, leaf - before))
        except Exception:
            return self._one_step_lookahead_delta(engine, player, action)

    def _beam_leaf_value(self, engine: Engine, player_index: int, remaining_depth: int) -> float:
        root_player = engine.state.players[player_index]
        if remaining_depth <= 0:
            return self.position_evaluator.evaluate(engine, root_player)
        try:
            legal = list(engine.legal_actions())
        except Exception:
            return self.position_evaluator.evaluate(engine, root_player)
        if not legal:
            return self.position_evaluator.evaluate(engine, root_player)
        active = getattr(engine.state, "active", None)
        choices = [(action, self.extractor.features_for_action(engine, active, action)) for action in legal]
        choices = action_choices_after_preinference(choices)
        if self.use_public_deep_v2_planner:
            choices = apply_public_deep_v2_planner_to_action_choices(choices)
        if self.beam_key_decisions_only and not any(
            self._beam_enabled_for_action(action, features) for action, features in choices
        ):
            return self.position_evaluator.evaluate(engine, root_player)
        scored = sorted(
            ((self._score_features(features), action) for action, features in choices),
            key=lambda item: item[0],
            reverse=True,
        )[: max(1, self.beam_lookahead_width)]
        values: list[float] = []
        for _score, next_action in scored:
            clone = self._lookahead_clone(engine)
            clone_player = clone.state.players[player_index]
            try:
                clone.apply(self._copy_action(next_action))
            except GameOver as game_over:
                values.append(self._game_over_lookahead_value(game_over, clone_player))
                continue
            values.append(self._beam_leaf_value(clone, player_index, remaining_depth - 1))
        if not values:
            return self.position_evaluator.evaluate(engine, root_player)
        return max(values) if active is root_player else min(values)

    def _lookahead_clone(self, engine: Engine) -> Engine:
        import copy

        clone = copy.deepcopy(engine)
        if hasattr(clone, "state") and hasattr(clone.state, "engine"):
            clone.state.engine = clone
        if hasattr(clone, "rebind_passive_modifiers"):
            clone.rebind_passive_modifiers()
        return clone

    def _copy_action(self, action: Action) -> Action:
        import copy

        return copy.deepcopy(action)

    def _game_over_lookahead_value(self, game_over: GameOver, player: Player) -> float:
        if game_over.winner is player:
            return 100.0
        if game_over.winner is None:
            return -5.0
        return -100.0


@dataclass
class EpisodeTrainingResult:
    winner: str
    turns: int
    recorder: TrainingEpisodeRecorder
    learner_side: str = "P1"
    opponent: str = ""
    learner_deck_id: str = ""
    learner_deck_name: str = ""
    opponent_deck_id: str = ""
    opponent_deck_name: str = ""
    error: str | None = None
    timeout_side: str | None = None


@dataclass(frozen=True)
class CounterfactualReplayConfig:
    max_decisions: int = 3
    max_alternatives: int = 2
    max_branches: int = 6
    alpha: float = 0.000001
    reward_resource_repair_branches: bool = True
    reward_resource_repair_survival_improvements: bool = True
    winning_update_repeats: int = 1
    branch_max_turns: int = TRAINING_MAX_TURNS
    branch_max_actions: int = TRAINING_MAX_ACTIONS
    max_runtime_seconds: float = 0.0
    stop_after_improved_branch: bool = False


@dataclass
class CounterfactualReplayResult:
    branches_tried: int = 0
    skipped_branches: int = 0
    improved_branches: int = 0
    winning_branches: int = 0
    resource_repair_branches: int = 0
    survival_improved_branches: int = 0
    model_updates: int = 0
    update_loss: float = 0.0
    runtime_budget_exhausted: bool = False
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class LeagueOpponent:
    name: str
    kind: str
    model_path: str | None = None


@dataclass(frozen=True)
class TrainingOpponentChoice:
    name: str
    policy: Any


class ScriptedReplayPolicy(RLPolicy):
    def __init__(
        self,
        *,
        trace: list[TrainingDecision],
        override_index: int,
        override_action: Action,
        override_record: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.trace = trace
        self.override_index = override_index
        self.override_action = override_action
        self.override_record = override_record or _action_to_dict(override_action)
        self.main_index = 0
        self.override_applied = False
        self.skipped_override = False

    def choose(self, engine: Engine) -> Action:
        legal = engine.legal_actions()
        if not legal:
            raise RuntimeError("no legal action")
        desired_record: dict[str, Any] | None = None
        is_override = self.main_index == self.override_index
        if is_override:
            desired_record = self.override_record
        elif self.main_index < len(self.trace):
            desired_record = self.trace[self.main_index].action
        self.main_index += 1
        if desired_record is not None:
            matched = find_replay_action(engine, engine.state.active, desired_record, legal)
            if matched is not None:
                if is_override:
                    self.override_applied = True
                return matched
            if is_override:
                self.skipped_override = True
        desired = _action_from_dict(desired_record) if desired_record is not None else None
        if desired is not None and desired in legal:
            if is_override:
                self.override_applied = True
            return desired
        return super().choose(engine)


def _copy_engine_for_replay(engine: Any) -> Any | None:
    import copy

    original_policies = getattr(engine, "_policies", None)
    try:
        if original_policies is not None:
            engine._policies = [None, None]
        clone = copy.deepcopy(engine)
    except Exception:
        return None
    finally:
        if original_policies is not None:
            engine._policies = original_policies
    if hasattr(clone, "state") and hasattr(clone.state, "engine"):
        clone.state.engine = clone
    if hasattr(clone, "rebind_passive_modifiers"):
        clone.rebind_passive_modifiers()
    return clone


def _winner_label(winner: Any) -> str:
    if winner is None:
        return "tie"
    side = getattr(winner, "side", None)
    if side is not None:
        side_name = getattr(side, "name", side)
        if str(side_name) in {"P1", "P2"}:
            return str(side_name)
    return str(getattr(winner, "name", "tie"))


def _play_counterfactual_branch_from_snapshot(
    *,
    snapshot: Any,
    override_record: dict[str, Any],
    model: Any,
    opponent_policy: Any,
    learner_side: str,
    seed: int,
    max_turns: int = TRAINING_MAX_TURNS,
    max_actions: int = TRAINING_MAX_ACTIONS,
) -> tuple[str, int, bool]:
    engine = _copy_engine_for_replay(snapshot)
    if engine is None:
        return "tie", 0, False
    learner_policy = _policy_for_current_model(model, seed)
    if learner_side == "P1":
        p1_policy, p2_policy = learner_policy, opponent_policy
    else:
        p1_policy, p2_policy = opponent_policy, learner_policy
    if hasattr(engine, "set_policies"):
        engine.set_policies(p1_policy, p2_policy)
    legal = engine.legal_actions()
    override_action = find_replay_action(engine, engine.state.active, override_record, legal)
    if override_action is None:
        return "tie", int(getattr(engine.state, "turn", 0)), False
    try:
        engine.apply(override_action)
    except GameOver as game_over:
        return _winner_label(game_over.winner), int(getattr(engine.state, "turn", 0)), True
    actions = 0
    try:
        while actions < max(1, int(max_actions)) and int(getattr(engine.state, "turn", 0)) <= max(1, int(max_turns)):
            action = engine.policy_for(engine.state.active).choose(engine)
            engine.apply(action)
            actions += 1
    except GameOver as game_over:
        return _winner_label(game_over.winner), int(getattr(engine.state, "turn", 0)), True
    return "tie", int(getattr(engine.state, "turn", 0)), True


class CheckpointManager:
    def __init__(self, out_dir: str | Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "createdAt": _utc_now(),
            "rewardVersion": REWARD_VERSION,
            "ruleVersion": RULE_VERSION,
            "cardPoolVersion": CARD_POOL_VERSION,
            "best": {},
            "evaluations": [],
        }

    def save_latest(self, model: LinearQModel, *, episode: int | None = None) -> Path:
        path = self.out_dir / "latest.json"
        metadata = dict(model.metadata)
        if episode is not None:
            metadata["episode"] = episode
        metadata["rewardVersion"] = REWARD_VERSION
        model.save(path, metadata=metadata)
        self.manifest["latest"] = str(path)
        return path

    def promote_if_best(self, metric: str, score: float, model: LinearQModel) -> bool:
        current = self.manifest["best"].get(metric)
        if current is not None and score <= current["score"]:
            return False
        path = self.out_dir / f"best_{metric}.json"
        metadata = dict(model.metadata)
        metadata["promotedMetric"] = metric
        metadata["promotedScore"] = score
        metadata["rewardVersion"] = REWARD_VERSION
        model.save(path, metadata=metadata)
        self.manifest["best"][metric] = {"score": score, "path": str(path), "createdAt": _utc_now()}
        return True

    def record_evaluation(self, *, episode: int, opponent: str, score: float, report: dict[str, Any], promoted: bool) -> None:
        self.manifest["evaluations"].append({
            "episode": episode,
            "opponent": opponent,
            "learnerSide": report.get("learnerSide"),
            "score": score,
            "seedCount": report.get("seedCount", 1),
            "reportKind": report.get("kind"),
            "meanWinRate": report.get("meanWinRate"),
            "minWinRate": report.get("minWinRate"),
            "promoted": promoted,
            "results": report.get("results", {}),
        })

    def record_league_evaluation(self, *, episode: int, report: dict[str, Any], promoted: bool) -> None:
        self.manifest.setdefault("leagueEvaluations", []).append({
            "episode": episode,
            "seedCount": report.get("seedCount", 1),
            "averageWinRate": report["averageWinRate"],
            "fixedOpponentMinimumWinRate": report.get("fixedOpponentMinimumWinRate"),
            "greedyP2WinRate": report.get("greedyP2WinRate"),
            "greedyP2MinimumWinRate": report.get("greedyP2MinimumWinRate"),
            "minimumOpponentSeedWinRate": report.get("minimumOpponentSeedWinRate"),
            "opponents": report["opponents"],
            "promoted": promoted,
            "rows": report["rows"],
        })

    def write_manifest(self) -> Path:
        path = self.out_dir / "manifest.json"
        _write_json(path, self.manifest)
        return path


def run_counterfactual_loss_replay(
    *,
    seed: int,
    model: LinearQModel,
    recorder: TrainingEpisodeRecorder,
    opponent: str,
    config: CounterfactualReplayConfig,
    opponent_model_paths: list[str | Path] | None = None,
    learner_side: str = "P1",
    learner_deck: Any | None = None,
    opponent_deck: Any | None = None,
) -> CounterfactualReplayResult:
    learner_side = _normalise_learner_side(learner_side)
    result = CounterfactualReplayResult()
    trace = recorder.loss_trace()
    snapshot_trace = [decision for decision in trace if getattr(decision, "engine_snapshot", None) is not None]
    replay_trace = snapshot_trace if snapshot_trace else trace
    branch_budget = config.max_branches
    branch_max_turns = max(1, int(getattr(config, "branch_max_turns", TRAINING_MAX_TURNS) or TRAINING_MAX_TURNS))
    branch_max_actions = max(1, int(getattr(config, "branch_max_actions", TRAINING_MAX_ACTIONS) or TRAINING_MAX_ACTIONS))
    max_runtime_seconds = max(0.0, float(getattr(config, "max_runtime_seconds", 0.0) or 0.0))
    deadline = time.perf_counter() + max_runtime_seconds if max_runtime_seconds > 0.0 else None
    baseline_outcomes: dict[int, tuple[str, int, bool]] = {}
    opponent_model_cache: dict[str, Any] = {}
    opponent_candidates = (
        training_opponent_candidates(
            opponent_model_paths or [],
            include_fixed=opponent == "checkpoint_pool",
        )
        if opponent in {"checkpoint_pool", "checkpoint_only"}
        else None
    )

    def runtime_budget_exhausted() -> bool:
        return deadline is not None and time.perf_counter() >= deadline

    def opponent_policy_for(branch_seed: int) -> Any:
        if opponent == "self":
            return _policy_for_current_model(model, branch_seed)
        if opponent in {"checkpoint_pool", "checkpoint_only"}:
            candidates = opponent_candidates or []
            if not candidates:
                raise ValueError("checkpoint_only opponent requires at least one existing checkpoint")
            selected = random.Random(branch_seed).choice(candidates)
            if selected.kind == "model":
                assert selected.model_path is not None
                return _policy_for_cached_training_checkpoint(
                    selected.model_path,
                    branch_seed + 17,
                    cache=opponent_model_cache,
                )
            return _make_opponent_policy(selected.name, branch_seed + 17)
        if str(opponent).startswith("model:"):
            candidates = training_opponent_candidates(opponent_model_paths or [], include_fixed=False)
            selected = next((candidate for candidate in candidates if candidate.name == opponent), None)
            if selected is None or selected.model_path is None:
                raise ValueError(f"unknown checkpoint opponent: {opponent}")
            return _policy_for_cached_training_checkpoint(
                selected.model_path,
                branch_seed + 17,
                cache=opponent_model_cache,
            )
        return choose_training_opponent(
            opponent,
            seed=branch_seed,
            checkpoint_paths=opponent_model_paths or [],
        ).policy

    for decision in reversed(replay_trace[-config.max_decisions:]):
        for alternative in rank_counterfactual_alternatives(decision)[:config.max_alternatives]:
            if runtime_budget_exhausted():
                result.runtime_budget_exhausted = True
                result.rows.append({
                    "decisionIndex": decision.decision_index,
                    "skipped": True,
                    "reason": "runtime_budget_exhausted",
                })
                return result
            if result.branches_tried >= branch_budget:
                return result
            override = _action_from_dict(alternative["action"])
            policy = ScriptedReplayPolicy(
                trace=trace,
                override_index=decision.decision_index,
                override_action=override,
                override_record=alternative["action"],
                model=model,
                rng=random.Random(seed + 7001 + result.branches_tried),
                epsilon=0.0,
            )
            try:
                opponent_policy = opponent_policy_for(seed + 7101 + result.branches_tried)
                snapshot = getattr(decision, "engine_snapshot", None)
                if snapshot is not None:
                    winner, turns, override_applied = _play_counterfactual_branch_from_snapshot(
                        snapshot=snapshot,
                        override_record=alternative["action"],
                        model=model,
                        opponent_policy=opponent_policy,
                        learner_side=learner_side,
                        seed=seed + 7201 + result.branches_tried,
                        max_turns=branch_max_turns,
                        max_actions=branch_max_actions,
                    )
                    policy.override_applied = override_applied
                else:
                    if learner_side == "P1":
                        p1_policy, p2_policy = policy, opponent_policy
                        p1_deck, p2_deck = learner_deck, opponent_deck
                    else:
                        p1_policy, p2_policy = opponent_policy, policy
                        p1_deck, p2_deck = opponent_deck, learner_deck
                    winner, turns = _play_one_game_with_policy(
                        seed,
                        p1_policy=p1_policy,
                        p2_policy=p2_policy,
                        p1_recipe=_deck_recipe_or_none(p1_deck),
                        p2_recipe=_deck_recipe_or_none(p2_deck),
                        p1_forces=_deck_forces_or_none(p1_deck),
                        p2_forces=_deck_forces_or_none(p2_deck),
                        max_turns=branch_max_turns,
                        max_actions=branch_max_actions,
                    )
            except Exception as exc:  # pragma: no cover - diagnostics path
                result.skipped_branches += 1
                result.rows.append({"decisionIndex": decision.decision_index, "skipped": True, "error": str(exc)})
                continue
            if not policy.override_applied:
                result.skipped_branches += 1
                result.rows.append({"decisionIndex": decision.decision_index, "skipped": True, "reason": "override_not_legal"})
                continue
            result.branches_tried += 1
            won = winner == learner_side
            if won:
                result.winning_branches += 1
                result.improved_branches += 1
                for _ in range(max(1, int(config.winning_update_repeats))):
                    result.update_loss += abs(float(model.update(alternative["features"], target=1.0, alpha=config.alpha)))
                    result.update_loss += abs(float(model.update(decision.features, target=-1.0, alpha=config.alpha)))
                    result.model_updates += 2
            is_resource_repair = _is_resource_repair_counterfactual(decision, alternative)
            if not won and is_resource_repair:
                result.resource_repair_branches += 1
                if (
                    snapshot is not None
                    and decision.decision_index not in baseline_outcomes
                    and (
                        not config.reward_resource_repair_branches
                        or config.reward_resource_repair_survival_improvements
                    )
                    and not runtime_budget_exhausted()
                ):
                    baseline_opponent_policy = opponent_policy_for(seed + 9101 + result.branches_tried)
                    baseline_outcomes[decision.decision_index] = _play_counterfactual_branch_from_snapshot(
                        snapshot=snapshot,
                        override_record=decision.action,
                        model=model,
                        opponent_policy=baseline_opponent_policy,
                        learner_side=learner_side,
                        seed=seed + 9201 + result.branches_tried,
                        max_turns=branch_max_turns,
                        max_actions=branch_max_actions,
                    )
                survival_improved = _is_survival_improved_counterfactual(
                    baseline_outcomes.get(decision.decision_index),
                    winner=winner,
                    turns=turns,
                    learner_side=learner_side,
                )
                if survival_improved:
                    result.survival_improved_branches += 1
                if config.reward_resource_repair_branches:
                    result.improved_branches += 1
                    result.update_loss += abs(float(model.update(alternative["features"], target=0.35, alpha=config.alpha)))
                    result.update_loss += abs(float(model.update(decision.features, target=-0.25, alpha=config.alpha)))
                    result.model_updates += 2
                elif config.reward_resource_repair_survival_improvements and survival_improved:
                    result.improved_branches += 1
                    result.update_loss += abs(float(model.update(alternative["features"], target=0.2, alpha=config.alpha)))
                    result.update_loss += abs(float(model.update(decision.features, target=-0.1, alpha=config.alpha)))
                    result.model_updates += 2
            result.rows.append({
                "decisionIndex": decision.decision_index,
                "override": alternative["action"],
                "winner": winner,
                "turns": turns,
                "won": won,
                "resourceRepair": is_resource_repair,
                "survivalImproved": _is_survival_improved_counterfactual(
                    baseline_outcomes.get(decision.decision_index),
                    winner=winner,
                    turns=turns,
                    learner_side=learner_side,
                ),
            })
            if config.stop_after_improved_branch and result.improved_branches > 0:
                return result
    return result


def _is_survival_improved_counterfactual(
    baseline: tuple[str, int, bool] | None,
    *,
    winner: str,
    turns: int,
    learner_side: str,
) -> bool:
    if baseline is None:
        return False
    baseline_winner, baseline_turns, baseline_applied = baseline
    if not baseline_applied:
        return False
    if baseline_winner == learner_side:
        return False
    if winner == learner_side:
        return False
    if winner == "tie" and baseline_winner != "tie":
        return True
    return int(turns) > int(baseline_turns)


def _is_resource_repair_counterfactual(decision: TrainingDecision, alternative: dict[str, Any]) -> bool:
    decision_features = getattr(decision, "features", {}) or {}
    alt_features = alternative.get("features") or {}
    action = alternative.get("action") or {}
    payload = action.get("payload") or {}
    if action.get("kind") == "move_card" and payload.get("direction") == "field_to_base":
        if float(alt_features.get("move_field_to_base_restores_missing_hand_color", 0.0)) > 0.0:
            return True
        if (
            float(decision_features.get("own_no_ready_colored_mana_for_hand", 0.0)) > 0.0
            and float(alt_features.get("move_field_to_base", 0.0)) > 0.0
        ):
            return True
    if action.get("kind") == "swap_mana_color":
        return float(alt_features.get("swap_mana_to_missing_hand_color", 0.0)) > 0.0
    return False


def run_training_episode(
    *,
    seed: int,
    model: LinearQModel,
    epsilon: float,
    opponent: str,
    opponent_model_paths: list[str | Path] | None = None,
    learner_side: str = "P1",
    learner_deck: Any | None = None,
    opponent_deck: Any | None = None,
    max_turns: int = TRAINING_MAX_TURNS,
    max_actions: int = TRAINING_MAX_ACTIONS,
    training_lookahead_weight: float = 0.0,
    training_max_lookahead_actions: int = 0,
    training_beam_lookahead_width: int = 0,
    training_beam_lookahead_depth: int = 1,
    training_beam_lookahead_key_decisions_only: bool = True,
    capture_decision_snapshots: bool = False,
    max_decision_snapshots: int = 12,
) -> EpisodeTrainingResult:
    learner_side = _normalise_learner_side(learner_side)
    recorder = TrainingEpisodeRecorder()
    policy = InstrumentedRLPolicy(
        model=model,
        rng=random.Random(seed + 17),
        epsilon=epsilon,
        recorder=recorder,
        lookahead_weight=training_lookahead_weight,
        max_lookahead_actions=training_max_lookahead_actions,
        beam_lookahead_width=training_beam_lookahead_width,
        beam_lookahead_depth=training_beam_lookahead_depth,
        beam_key_decisions_only=training_beam_lookahead_key_decisions_only,
        capture_decision_snapshots=capture_decision_snapshots,
        max_decision_snapshots=max_decision_snapshots,
    )
    if opponent == "self":
        opponent_choice = TrainingOpponentChoice(
            name="self",
            policy=_policy_for_current_model(model, seed + 31),
        )
    else:
        opponent_choice = choose_training_opponent(opponent, seed=seed + 31, checkpoint_paths=opponent_model_paths or [])
    if learner_side == "P1":
        engine, _ = _setup_game(
            seed,
            policy,
            opponent_choice.policy,
            p1_recipe=_deck_recipe_or_none(learner_deck),
            p2_recipe=_deck_recipe_or_none(opponent_deck),
            p1_forces=_deck_forces_or_none(learner_deck),
            p2_forces=_deck_forces_or_none(opponent_deck),
        )
    else:
        engine, _ = _setup_game(
            seed,
            opponent_choice.policy,
            policy,
            p1_recipe=_deck_recipe_or_none(opponent_deck),
            p2_recipe=_deck_recipe_or_none(learner_deck),
            p1_forces=_deck_forces_or_none(opponent_deck),
            p2_forces=_deck_forces_or_none(learner_deck),
        )
    learner = engine.state.players[0 if learner_side == "P1" else 1]
    actions = 0
    try:
        engine.begin_turn()
        while True:
            if engine.state.turn > max_turns or actions >= max_actions:
                timeout_side = engine.state.active.name
                winner = "P2" if timeout_side == "P1" else "P1"
                return EpisodeTrainingResult(
                    winner=winner,
                    turns=engine.state.turn,
                    recorder=recorder,
                    learner_side=learner_side,
                    opponent=opponent_choice.name,
                    learner_deck_id=_deck_id_or_empty(learner_deck),
                    learner_deck_name=_deck_name_or_empty(learner_deck),
                    opponent_deck_id=_deck_id_or_empty(opponent_deck),
                    opponent_deck_name=_deck_name_or_empty(opponent_deck),
                    timeout_side=timeout_side,
                )
            active = engine.state.active
            action = engine.policy_for(active).choose(engine)
            actions += 1
            decision_index = policy.last_main_decision_index if active is learner else None
            before = StateSnapshot.from_engine(engine, learner) if active is learner else None
            try:
                engine.apply(action)
            except GameOver as game_over:
                if active is learner and before is not None:
                    after = StateSnapshot.from_engine(engine, learner)
                    recorder.add_step_reward(decision_index, calculate_step_reward(before, after, action))
                return EpisodeTrainingResult(
                    winner=game_over.winner.name if game_over.winner else "tie",
                    turns=engine.state.turn,
                    recorder=recorder,
                    learner_side=learner_side,
                    opponent=opponent_choice.name,
                    learner_deck_id=_deck_id_or_empty(learner_deck),
                    learner_deck_name=_deck_name_or_empty(learner_deck),
                    opponent_deck_id=_deck_id_or_empty(opponent_deck),
                    opponent_deck_name=_deck_name_or_empty(opponent_deck),
                )
            if active is learner and before is not None:
                after = StateSnapshot.from_engine(engine, learner)
                recorder.add_step_reward(decision_index, calculate_step_reward(before, after, action))
    except Exception as exc:  # pragma: no cover - report path for long runs
        return EpisodeTrainingResult(
            winner="error",
            turns=getattr(engine.state, "turn", 0),
            recorder=recorder,
            learner_side=learner_side,
            opponent=opponent_choice.name,
            learner_deck_id=_deck_id_or_empty(learner_deck),
            learner_deck_name=_deck_name_or_empty(learner_deck),
            opponent_deck_id=_deck_id_or_empty(opponent_deck),
            opponent_deck_name=_deck_name_or_empty(opponent_deck),
            error=f"{exc}\n{traceback.format_exc(limit=4)}",
        )


def run_quality_training(
    *,
    episodes: int,
    seed: int,
    out_dir: str | Path,
    eval_interval: int = 50,
    eval_episodes: int = 20,
    alpha: float = 0.000003,
    gamma: float = 0.97,
    epsilon_start: float = 0.25,
    epsilon_end: float = 0.05,
    opponent: str = "greedy",
    loss_replay_decisions: int = 3,
    loss_replay_alternatives: int = 2,
    loss_replay_max_branches: int = 6,
    league_eval_episodes: int | None = None,
    learner_side: str = "alternate",
    initial_model_path: str | Path | None = None,
    opponent_model_paths: list[str | Path] | None = None,
    multi_seed_eval_count: int = 1,
    multi_seed_eval_episodes: int | None = None,
    deck_pool: list[Any] | None = None,
    deck_pool_source: str | None = None,
    deck_matchups: list[Any] | None = None,
    deck_matrix_eval_episodes: int = 0,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    _validate_learner_side_mode(learner_side)
    out_dir = Path(out_dir)
    league_eval_episodes = eval_episodes if league_eval_episodes is None else league_eval_episodes
    multi_seed_eval_count = max(1, int(multi_seed_eval_count))
    multi_seed_eval_episodes = eval_episodes if multi_seed_eval_episodes is None else multi_seed_eval_episodes
    deck_pool = list(deck_pool or [])
    resolved_deck_pool_source = str(deck_pool_source or ("explicit" if deck_pool else "none"))
    deck_matchups = _normalise_deck_matchups(deck_matchups or [])
    opponent_model_paths = _dedupe_existing_paths(opponent_model_paths or [])
    deck_matrix_eval_episodes = max(0, int(deck_matrix_eval_episodes))
    manager = CheckpointManager(out_dir)
    model = LinearQModel.load(initial_model_path) if initial_model_path is not None else LinearQModel.greedy_prior()
    if initial_model_path is not None:
        model.seed_missing_greedy_prior_weights()
    model.metadata.update({
        "trainingSeed": seed,
        "rewardVersion": REWARD_VERSION,
        "trainingMode": "quality",
        "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
    })
    aggregate_diagnostics = ActionMaskDiagnostics()
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    learner_results = {"wins": 0, "losses": 0, "ties": 0}
    episode_rows: list[dict[str, Any]] = []
    replay_totals = Counter()
    checkpoints_evaluated = 0
    league_evaluations: list[dict[str, Any]] = []
    deck_matrix_evaluations: list[dict[str, Any]] = []
    memory_corrections: list[dict[str, Any]] = []
    opponent_usage: Counter[str] = Counter()
    latest_path = manager.save_latest(model, episode=0)
    replay_config = CounterfactualReplayConfig(
        max_decisions=loss_replay_decisions,
        max_alternatives=loss_replay_alternatives,
        max_branches=loss_replay_max_branches,
    )

    for index in range(episodes):
        episode_no = index + 1
        epsilon = _linear_decay(epsilon_start, epsilon_end, index, episodes)
        episode_learner_side = _learner_side_for_episode(learner_side, index)
        learner_deck, opponent_deck = _training_deck_pair(deck_pool, index, deck_matchups=deck_matchups)
        current_checkpoint_paths = _dedupe_existing_paths([*_best_checkpoint_paths(manager), *opponent_model_paths])
        episode = run_training_episode(
            seed=seed + index,
            model=model,
            epsilon=epsilon,
            opponent=opponent,
            opponent_model_paths=current_checkpoint_paths,
            learner_side=episode_learner_side,
            learner_deck=learner_deck,
            opponent_deck=opponent_deck,
            capture_decision_snapshots=loss_replay_decisions > 0
            and loss_replay_alternatives > 0
            and loss_replay_max_branches > 0,
        )
        opponent_usage[episode.opponent] += 1
        aggregate_diagnostics.merge(episode.recorder.diagnostics)
        results["played"] += 1
        if episode.winner == "error":
            results["errors"] += 1
            final_reward = -1.0
        else:
            results[episode.winner] = results.get(episode.winner, 0) + 1
            final_reward = _reward_for_learner(episode.winner, episode.learner_side)
            if episode.winner == "tie":
                learner_results["ties"] += 1
            elif episode.winner == episode.learner_side:
                learner_results["wins"] += 1
            else:
                learner_results["losses"] += 1
        episode.recorder.apply_rewards(model, final_reward=final_reward, gamma=gamma, alpha=alpha)

        replay_result = CounterfactualReplayResult()
        if episode.winner not in {episode.learner_side, "error", "tie"}:
            replay_result = run_counterfactual_loss_replay(
                seed=seed + index,
                model=model,
                recorder=episode.recorder,
                opponent=opponent,
                config=replay_config,
                opponent_model_paths=current_checkpoint_paths,
                learner_side=episode.learner_side,
                learner_deck=learner_deck,
                opponent_deck=opponent_deck,
            )
            replay_totals["branchesTried"] += replay_result.branches_tried
            replay_totals["skippedBranches"] += replay_result.skipped_branches
            replay_totals["improvedBranches"] += replay_result.improved_branches
            replay_totals["winningBranches"] += replay_result.winning_branches
            replay_totals["resourceRepairBranches"] += replay_result.resource_repair_branches
            replay_totals["survivalImprovedBranches"] += replay_result.survival_improved_branches
            match_id = _memory_match_id_from_deck_id(episode.learner_deck_id)
            if match_id:
                correction = _memory_correction_from_replay_result(
                    match_id=match_id,
                    episode_no=episode_no,
                    learner_side=episode.learner_side,
                    opponent=opponent,
                    decisions=episode.recorder.decisions,
                    replay_result=replay_result,
                )
                if correction is not None:
                    memory_corrections.append(correction)

        episode_rows.append({
            "episode": episode_no,
            "winner": episode.winner,
            "learnerSide": episode.learner_side,
            "opponent": episode.opponent,
            "learnerDeckId": episode.learner_deck_id,
            "learnerDeckName": episode.learner_deck_name,
            "opponentDeckId": episode.opponent_deck_id,
            "opponentDeckName": episode.opponent_deck_name,
            "turns": episode.turns,
            "epsilon": epsilon,
            "finalReward": final_reward,
            "shapedReward": episode.recorder.total_shaped_reward,
            "decisions": len(episode.recorder.decisions),
            "lossReplay": {
                "branchesTried": replay_result.branches_tried,
                "skippedBranches": replay_result.skipped_branches,
                "improvedBranches": replay_result.improved_branches,
                "winningBranches": replay_result.winning_branches,
                "resourceRepairBranches": replay_result.resource_repair_branches,
                "survivalImprovedBranches": replay_result.survival_improved_branches,
            },
        })
        if progress_callback is not None:
            progress_callback({
                "state": "running",
                "stage": "training",
                "episode": episode_no,
                "episodes": episodes,
                "learnerSide": episode.learner_side,
                "winner": episode.winner,
                "opponent": episode.opponent,
            })

        if episode_no % max(1, eval_interval) == 0 or episode_no == episodes:
            model.episodes = episode_no
            latest_path = manager.save_latest(model, episode=episode_no)
            for eval_opponent in ("random", "greedy"):
                for eval_side in _fixed_eval_sides_for_mode(learner_side):
                    metric = _fixed_eval_metric(eval_opponent, eval_side)
                    eval_report = run_evaluation(
                        model_path=latest_path,
                        episodes=eval_episodes,
                        seed=seed + 100000 + episode_no + _side_seed_offset(eval_side),
                        opponent=eval_opponent,
                        learner_side=eval_side,
                    )
                    promoted = manager.promote_if_best(metric, eval_report["winRate"], model)
                    manager.record_evaluation(
                        episode=episode_no,
                        opponent=metric,
                        score=eval_report["winRate"],
                        report=eval_report,
                        promoted=promoted,
                    )
                    checkpoints_evaluated += 1
                    if multi_seed_eval_count > 1:
                        stable_metric = f"{metric}_stable"
                        stable_report = run_multi_seed_evaluation(
                            model_path=latest_path,
                            episodes=multi_seed_eval_episodes,
                            seed=seed + 300000 + episode_no + _side_seed_offset(eval_side),
                            seed_count=multi_seed_eval_count,
                            opponent=eval_opponent,
                            learner_side=eval_side,
                        )
                        stable_promoted = manager.promote_if_best(stable_metric, stable_report["minWinRate"], model)
                        manager.record_evaluation(
                            episode=episode_no,
                            opponent=stable_metric,
                            score=stable_report["minWinRate"],
                            report=stable_report,
                            promoted=stable_promoted,
                        )
                        checkpoints_evaluated += multi_seed_eval_count
            league_report = run_league_evaluation(
                model_path=latest_path,
                episodes=league_eval_episodes,
                seed=seed + 200000 + episode_no,
                fixed_model_paths=current_checkpoint_paths,
                seed_count=multi_seed_eval_count,
            )
            league_promoted = manager.promote_if_best("league", league_report["averageWinRate"], model)
            fixed_floor_promoted = manager.promote_if_best(
                "fixed_floor",
                league_report["fixedOpponentMinimumWinRate"],
                model,
            )
            greedy_p2_promoted = manager.promote_if_best("greedy_p2", league_report["greedyP2WinRate"], model)
            league_stable_promoted = False
            greedy_p2_stable_promoted = False
            if multi_seed_eval_count > 1:
                league_stable_promoted = manager.promote_if_best(
                    "league_stable",
                    league_report["minimumOpponentSeedWinRate"],
                    model,
                )
                greedy_p2_stable_promoted = manager.promote_if_best(
                    "greedy_p2_stable_league",
                    league_report["greedyP2MinimumWinRate"],
                    model,
                )
            manager.record_league_evaluation(
                episode=episode_no,
                report=league_report,
                promoted=(
                    league_promoted
                    or fixed_floor_promoted
                    or greedy_p2_promoted
                    or league_stable_promoted
                    or greedy_p2_stable_promoted
                ),
            )
            league_evaluations.append({
                "episode": episode_no,
                "seedCount": league_report.get("seedCount", 1),
                "averageWinRate": league_report["averageWinRate"],
                "fixedOpponentMinimumWinRate": league_report["fixedOpponentMinimumWinRate"],
                "greedyP2WinRate": league_report["greedyP2WinRate"],
                "greedyP2MinimumWinRate": league_report.get("greedyP2MinimumWinRate"),
                "minimumOpponentSeedWinRate": league_report.get("minimumOpponentSeedWinRate"),
                "opponents": league_report["opponents"],
                "promoted": (
                    league_promoted
                    or fixed_floor_promoted
                    or greedy_p2_promoted
                    or league_stable_promoted
                    or greedy_p2_stable_promoted
                ),
                "promotedMetrics": {
                    "league": league_promoted,
                    "fixed_floor": fixed_floor_promoted,
                    "greedy_p2": greedy_p2_promoted,
                    "league_stable": league_stable_promoted,
                    "greedy_p2_stable_league": greedy_p2_stable_promoted,
                },
                "rows": league_report["rows"],
            })
            if progress_callback is not None:
                progress_callback({
                    "state": "running",
                    "stage": "evaluation",
                    "episode": episode_no,
                    "episodes": episodes,
                    "evaluation": {
                        "averageWinRate": league_report["averageWinRate"],
                        "fixedOpponentMinimumWinRate": league_report["fixedOpponentMinimumWinRate"],
                        "greedyP2WinRate": league_report["greedyP2WinRate"],
                    },
                })
            if deck_pool and deck_matrix_eval_episodes > 0:
                matrix_report = run_deck_matrix_evaluation(
                    model_path=latest_path,
                    learner_decks=deck_pool,
                    opponent_decks=deck_pool,
                    episodes=deck_matrix_eval_episodes,
                    seed=seed + 400000 + episode_no,
                    seed_count=multi_seed_eval_count,
                    opponent="greedy",
                )
                matrix_average_promoted = manager.promote_if_best(
                    "deck_matrix_average",
                    matrix_report["averageWinRate"],
                    model,
                )
                manager.record_evaluation(
                    episode=episode_no,
                    opponent="deck_matrix_average",
                    score=matrix_report["averageWinRate"],
                    report=matrix_report,
                    promoted=matrix_average_promoted,
                )
                matrix_promoted = manager.promote_if_best(
                    "deck_matrix_floor",
                    matrix_report["minimumSeedWinRate"],
                    model,
                )
                manager.record_evaluation(
                    episode=episode_no,
                    opponent="deck_matrix_floor",
                    score=matrix_report["minimumSeedWinRate"],
                    report=matrix_report,
                    promoted=matrix_promoted,
                )
                checkpoints_evaluated += matrix_report["rowCount"] * multi_seed_eval_count
                deck_matrix_evaluations.append({
                    "episode": episode_no,
                    "seedCount": matrix_report["seedCount"],
                    "rowCount": matrix_report["rowCount"],
                    "averageWinRate": matrix_report["averageWinRate"],
                    "minimumSeedWinRate": matrix_report["minimumSeedWinRate"],
                    "promoted": matrix_average_promoted or matrix_promoted,
                    "promotedMetrics": {
                        "deck_matrix_average": matrix_average_promoted,
                        "deck_matrix_floor": matrix_promoted,
                    },
                })

    mask_summary = aggregate_diagnostics.summary()
    _write_json(out_dir / "mask_diagnostics.json", mask_summary)
    manifest_path = manager.write_manifest()
    completed = max(1, results["P1"] + results["P2"] + results["tie"])
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rl_training_quality_report",
        "createdAt": _utc_now(),
        "rewardVersion": REWARD_VERSION,
        "ruleVersion": RULE_VERSION,
        "cardPoolVersion": CARD_POOL_VERSION,
        "trainingSeed": seed,
        "evaluationSeedBase": seed + 100000,
        "episodes": episodes,
        "latestModelPath": str(latest_path),
        "manifestPath": str(manifest_path),
        "opponentPool": ["random", "greedy", "self", "checkpoint_pool", "checkpoint_only"],
        "config": {
            "alpha": alpha,
            "gamma": gamma,
            "epsilonStart": epsilon_start,
            "epsilonEnd": epsilon_end,
            "opponent": opponent,
            "evalInterval": eval_interval,
            "evalEpisodes": eval_episodes,
            "lossReplayDecisions": loss_replay_decisions,
            "lossReplayAlternatives": loss_replay_alternatives,
            "lossReplayMaxBranches": loss_replay_max_branches,
            "lossReplayRewardResourceRepairSurvivalImprovements": replay_config.reward_resource_repair_survival_improvements,
            "leagueEvalEpisodes": league_eval_episodes,
            "learnerSide": learner_side,
            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
            "opponentModelPaths": [str(path) for path in opponent_model_paths],
            "multiSeedEvalCount": multi_seed_eval_count,
            "multiSeedEvalEpisodes": multi_seed_eval_episodes,
            "deckPoolSize": len(deck_pool),
            "deckPoolSource": resolved_deck_pool_source,
            "deckMatchupSize": len(deck_matchups),
            "deckMatrixEvalEpisodes": deck_matrix_eval_episodes,
        },
        "results": results,
        "learnerResults": learner_results,
        "winRate": learner_results["wins"] / completed,
        "maskDiagnostics": mask_summary,
        "lossReplay": dict(replay_totals),
        "memoryCorrections": memory_corrections,
        "checkpointsEvaluated": checkpoints_evaluated,
        "leagueEvaluations": league_evaluations,
        "deckMatrixEvaluations": deck_matrix_evaluations,
        "trainingOpponentUsage": dict(sorted(opponent_usage.items())),
        "manifest": manager.manifest,
        "rowCount": len(episode_rows),
        "rows": _compact_rows(episode_rows),
    }
    _write_json(out_dir / "quality_report.json", report)
    return report


def run_league_evaluation(
    *,
    model_path: str | Path,
    episodes: int,
    seed: int = 20260523,
    seed_count: int = 1,
    fixed_model_paths: list[str | Path] | None = None,
    include_default_previous: bool = True,
    learner_sides: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    model_path = Path(model_path)
    learner_model = LinearQModel.load(model_path)
    seed_count = max(1, int(seed_count))
    sides = [_normalise_learner_side(side) for side in (learner_sides or ("P1", "P2"))]
    opponents = _league_opponents(
        learner_model_path=model_path,
        fixed_model_paths=fixed_model_paths or [],
        include_default_previous=include_default_previous,
    )
    rows = [
        _evaluate_league_opponent_multi_seed(
            learner_model=learner_model,
            learner_model_path=model_path,
            opponent=opponent,
            episodes=episodes,
            seed=seed + (opponent_index * max(1, len(sides)) + side_index) * 1009,
            seed_count=seed_count,
            learner_side=side,
        )
        for opponent_index, opponent in enumerate(opponents)
        for side_index, side in enumerate(sides)
    ]
    average = sum(row["winRate"] for row in rows) / max(1, len(rows))
    fixed_rows = [row for row in rows if row["kind"] == "fixed_policy"]
    fixed_average = sum(row["winRate"] for row in fixed_rows) / max(1, len(fixed_rows))
    fixed_minimum = min((row.get("minWinRate", row["winRate"]) for row in fixed_rows), default=0.0)
    minimum_opponent_seed = min((row.get("minWinRate", row["winRate"]) for row in rows), default=0.0)
    greedy_p2_row = next(
        (
            row
            for row in fixed_rows
            if row["opponent"] == "greedy" and row.get("learnerSide") == "P2"
        ),
        None,
    )
    greedy_p2 = greedy_p2_row["winRate"] if greedy_p2_row is not None else 0.0
    greedy_p2_minimum = greedy_p2_row.get("minWinRate", greedy_p2) if greedy_p2_row is not None else 0.0
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rl_training_league_evaluation",
        "createdAt": _utc_now(),
        "modelPath": str(model_path),
        "episodesPerOpponent": episodes,
        "seed": seed,
        "seedCount": seed_count,
        "opponents": len(opponents),
        "learnerSides": sides,
        "averageWinRate": average,
        "fixedOpponentAverageWinRate": fixed_average,
        "fixedOpponentMinimumWinRate": fixed_minimum,
        "greedyP2WinRate": greedy_p2,
        "greedyP2MinimumWinRate": greedy_p2_minimum,
        "minimumOpponentSeedWinRate": minimum_opponent_seed,
        "rows": rows,
    }


def run_multi_seed_evaluation(
    *,
    model_path: str | Path,
    episodes: int,
    seed: int = 20260523,
    seed_count: int = 1,
    opponent: str = "greedy",
    learner_side: str = "P1",
    report_out: str | Path | None = None,
    learner_recipe: dict[str, int] | None = None,
    learner_forces: list[str] | None = None,
    opponent_recipe: dict[str, int] | None = None,
    opponent_forces: list[str] | None = None,
) -> dict[str, Any]:
    seed_count = max(1, int(seed_count))
    learner_side = _normalise_learner_side(learner_side)
    rows = []
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    turns_total = 0.0
    completed_total = 0
    for seed_index in range(seed_count):
        run_seed = seed + seed_index * 1009
        report = run_evaluation(
            model_path=model_path,
            episodes=episodes,
            seed=run_seed,
            opponent=opponent,
            learner_side=learner_side,
            learner_recipe=learner_recipe,
            learner_forces=learner_forces,
            opponent_recipe=opponent_recipe,
            opponent_forces=opponent_forces,
        )
        row_results = dict(report["results"])
        completed = max(1, row_results["P1"] + row_results["P2"] + row_results["tie"])
        completed_total += completed
        turns_total += report["averageTurns"] * completed
        for key, value in row_results.items():
            results[key] = results.get(key, 0) + int(value)
        rows.append({
            "seed": run_seed,
            "winRate": report["winRate"],
            "results": row_results,
            "averageTurns": report["averageTurns"],
            "decks": report.get("decks"),
        })
    mean = sum(row["winRate"] for row in rows) / max(1, len(rows))
    minimum = min((row["winRate"] for row in rows), default=0.0)
    maximum = max((row["winRate"] for row in rows), default=0.0)
    aggregate_win_rate = results[learner_side] / max(1, completed_total)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rl_multi_seed_evaluation",
        "createdAt": _utc_now(),
        "modelPath": str(model_path),
        "opponent": opponent,
        "learnerSide": learner_side,
        "episodesPerSeed": episodes,
        "seed": seed,
        "seedCount": seed_count,
        "results": results,
        "winRate": aggregate_win_rate,
        "meanWinRate": mean,
        "minWinRate": minimum,
        "maxWinRate": maximum,
        "averageTurns": turns_total / max(1, completed_total),
        "decks": rows[0].get("decks") if rows else None,
        "rows": rows,
    }
    if report_out is not None:
        _write_json(report_out, report)
    return report


def run_deck_matrix_evaluation(
    *,
    model_path: str | Path,
    learner_decks: list[Any],
    opponent_decks: list[Any] | None = None,
    episodes: int,
    seed: int = 20260523,
    seed_count: int = 1,
    opponent: str = "greedy",
    learner_sides: tuple[str, ...] | list[str] = ("P1", "P2"),
    report_out: str | Path | None = None,
) -> dict[str, Any]:
    opponent_decks = learner_decks if opponent_decks is None else opponent_decks
    sides = [_normalise_learner_side(side) for side in learner_sides]
    rows: list[dict[str, Any]] = []
    for learner_index, learner_deck in enumerate(learner_decks):
        for opponent_index, opponent_deck in enumerate(opponent_decks):
            for side in sides:
                run_seed = seed + learner_index * 10_000 + opponent_index * 1_000 + _side_seed_offset(side)
                report = run_multi_seed_evaluation(
                    model_path=model_path,
                    episodes=episodes,
                    seed=run_seed,
                    seed_count=seed_count,
                    opponent=opponent,
                    learner_side=side,
                    learner_recipe=_deck_recipe(learner_deck),
                    learner_forces=_deck_forces(learner_deck),
                    opponent_recipe=_deck_recipe(opponent_deck),
                    opponent_forces=_deck_forces(opponent_deck),
                )
                rows.append({
                    "learnerDeckId": _deck_id(learner_deck),
                    "learnerDeckName": _deck_name(learner_deck),
                    "opponentDeckId": _deck_id(opponent_deck),
                    "opponentDeckName": _deck_name(opponent_deck),
                    "opponent": opponent,
                    "learnerSide": side,
                    "episodesPerSeed": episodes,
                    "seed": run_seed,
                    "seedCount": seed_count,
                    "winRate": report["winRate"],
                    "meanWinRate": report["meanWinRate"],
                    "minWinRate": report["minWinRate"],
                    "maxWinRate": report["maxWinRate"],
                    "results": report["results"],
                    "averageTurns": report["averageTurns"],
                    "seedRuns": report["rows"],
                })
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rl_deck_matrix_evaluation",
        "createdAt": _utc_now(),
        "modelPath": str(model_path),
        "opponent": opponent,
        "episodesPerSeed": episodes,
        "seed": seed,
        "seedCount": seed_count,
        "learnerDecks": len(learner_decks),
        "opponentDecks": len(opponent_decks),
        "learnerSides": sides,
        "averageWinRate": sum(row["winRate"] for row in rows) / max(1, len(rows)),
        "minimumSeedWinRate": min((row["minWinRate"] for row in rows), default=0.0),
        "rowCount": len(rows),
        "rows": rows,
    }
    if report_out is not None:
        _write_json(report_out, report)
    return report


def _deck_id(deck: Any) -> str:
    if isinstance(deck, dict):
        return str(deck.get("id", "deck"))
    return str(getattr(deck, "id", "deck"))


def _deck_id_or_empty(deck: Any | None) -> str:
    return "" if deck is None else _deck_id(deck)


def _deck_name(deck: Any) -> str:
    if isinstance(deck, dict):
        return str(deck.get("name", _deck_id(deck)))
    return str(getattr(deck, "name", _deck_id(deck)))


def _deck_name_or_empty(deck: Any | None) -> str:
    return "" if deck is None else _deck_name(deck)


def _deck_recipe(deck: Any) -> dict[str, int]:
    recipe = deck.get("recipe") if isinstance(deck, dict) else getattr(deck, "recipe")
    return {str(card_id): int(count) for card_id, count in recipe.items()}


def _deck_recipe_or_none(deck: Any | None) -> dict[str, int] | None:
    return None if deck is None else _deck_recipe(deck)


def _deck_forces(deck: Any) -> list[str]:
    forces = deck.get("forces") if isinstance(deck, dict) else getattr(deck, "forces")
    return [str(force_id) for force_id in forces]


def _deck_forces_or_none(deck: Any | None) -> list[str] | None:
    return None if deck is None else _deck_forces(deck)


def _training_deck_pair(
    deck_pool: list[Any],
    index: int,
    *,
    deck_matchups: list[tuple[Any, Any]] | None = None,
) -> tuple[Any | None, Any | None]:
    if deck_matchups:
        return deck_matchups[index % len(deck_matchups)]
    if not deck_pool:
        return None, None
    pool_size = len(deck_pool)
    learner = deck_pool[index % pool_size]
    opponent = deck_pool[(index // pool_size) % pool_size]
    return learner, opponent


def _normalise_deck_matchups(raw_matchups: list[Any]) -> list[tuple[Any, Any]]:
    matchups: list[tuple[Any, Any]] = []
    for raw in raw_matchups:
        learner = None
        opponent = None
        if isinstance(raw, dict):
            learner = raw.get("learner") or raw.get("player")
            opponent = raw.get("opponent")
        else:
            try:
                learner, opponent = raw
            except (TypeError, ValueError):
                continue
        if learner is None or opponent is None:
            continue
        matchups.append((learner, opponent))
    return matchups


def _memory_match_id_from_deck_id(deck_id: str) -> str | None:
    prefix = "memory-match-"
    suffix = "-player"
    if not deck_id.startswith(prefix) or not deck_id.endswith(suffix):
        return None
    raw = deck_id[len(prefix):-len(suffix)]
    return raw or None


def _memory_correction_from_replay_result(
    *,
    match_id: str,
    episode_no: int,
    learner_side: str,
    opponent: str,
    decisions: list[TrainingDecision],
    replay_result: CounterfactualReplayResult,
) -> dict[str, Any] | None:
    if replay_result.winning_branches <= 0:
        return None
    winning_row = next((row for row in replay_result.rows if row.get("won")), None)
    if not winning_row:
        return None
    decision_index = int(winning_row.get("decisionIndex", -1))
    decision = next((item for item in decisions if item.decision_index == decision_index), None)
    player_action = _action_summary(decision.action) if decision is not None else "recorded action"
    ai_action = _action_summary(winning_row.get("override"))
    replay_control = "codeman_self_vs_self" if opponent == "self" else str(opponent)
    return {
        "schema": 1,
        "kind": "codeman_corrected_replay",
        "matchId": str(match_id),
        "sourceEpisode": int(episode_no),
        "learnerSide": learner_side,
        "playerController": "codeman_self" if opponent == "self" else "codeman",
        "opponentController": "codeman_self" if opponent == "self" else str(opponent),
        "replayControl": replay_control,
        "divergences": [{
            "eventIndex": 0,
            "decisionIndex": decision_index,
            "playerAction": player_action,
            "aiAction": ai_action,
            "hint": f"Codeman chose {ai_action} instead of {player_action} and found a winning branch.",
        }],
        "logEvents": [{
            "type": "codeman_correction",
            "actionKind": "ai_correction",
            "label": f"AI correction: {ai_action}",
            "decisionIndex": decision_index,
            "winner": winning_row.get("winner"),
        }],
    }


def _action_summary(action: Any) -> str:
    if not isinstance(action, dict):
        return str(action or "")
    kind = str(action.get("kind") or "")
    payload = action.get("payload")
    if isinstance(payload, dict) and payload:
        return kind
    return kind


def _setup_game(
    seed: int,
    p1_policy: Any,
    p2_policy: Any,
    *,
    p1_recipe: dict[str, int] | None = None,
    p2_recipe: dict[str, int] | None = None,
    p1_forces: list[str] | None = None,
    p2_forces: list[str] | None = None,
) -> tuple[Engine, Player]:
    rng = random.Random(seed)
    p1 = Player(name="P1", side=Side.P1, is_first_player=True)
    p2 = Player(name="P2", side=Side.P2, is_first_player=False)
    state = GameState(players=[p1, p2])
    engine = Engine(state, rng=rng)
    state.engine = engine
    engine.set_policies(p1_policy, p2_policy)
    p1_recipe = p1_recipe or KANATANA_YELLOW_RECIPE
    p2_recipe = p2_recipe or DEMETE_GREEN_RECIPE
    p1_forces = p1_forces or DECKCODE0_YELLOW_FORCES
    p2_forces = p2_forces or DECKCODE0_GREEN_FORCES
    _attach_runtime_deck_profile(p1, deck_id="runtime-p1", name="P1 runtime deck", recipe=p1_recipe, forces=p1_forces)
    _attach_runtime_deck_profile(p2, deck_id="runtime-p2", name="P2 runtime deck", recipe=p2_recipe, forces=p2_forces)
    p1.deck = build_deck(p1_recipe, owner=p1, iid_factory=state.allocate_iid)
    p2.deck = build_deck(p2_recipe, owner=p2, iid_factory=state.allocate_iid)
    rng.shuffle(p1.deck)
    rng.shuffle(p2.deck)
    for player in (p1, p2):
        engine.deal_opening_hand(player)
        force_ids = p1_forces if player is p1 else p2_forces
        engine.install_forces(player, [
            ForceInstance(force=ALL_FORCES[force_id], owner=player, life=ALL_FORCES[force_id].initial_life)
            for force_id in force_ids
        ])
    for player in (p1, p2):
        engine.mulligan(player, redraw=engine.policy_for(player).choose_mulligan(engine, player))
    return engine, p1


def _attach_runtime_deck_profile(
    player: Player,
    *,
    deck_id: str,
    name: str,
    recipe: dict[str, int],
    forces: list[str],
) -> None:
    try:
        from zz.ai_deck_analysis import DeckSpec
        from zz.deck_profiles import build_deck_profile

        deck_spec = DeckSpec(
            id=deck_id,
            name=name,
            recipe={str(card_id): int(count) for card_id, count in recipe.items()},
            forces=[str(force_id) for force_id in forces],
        )
        deck_profile = build_deck_profile(deck_spec).to_dict()
    except Exception:
        return
    player.profile = dict(getattr(player, "profile", {}) or {})
    player.profile.setdefault("deckSpec", {
        "id": deck_id,
        "name": name,
        "recipe": dict(recipe),
        "forces": list(forces),
    })
    player.profile["deckProfile"] = deck_profile


def _play_one_game_with_policy(
    seed: int,
    *,
    p1_policy: Any,
    p2_policy: Any,
    p1_recipe: dict[str, int] | None = None,
    p2_recipe: dict[str, int] | None = None,
    p1_forces: list[str] | None = None,
    p2_forces: list[str] | None = None,
    max_turns: int = TRAINING_MAX_TURNS,
    max_actions: int = TRAINING_MAX_ACTIONS,
) -> tuple[str, int]:
    engine, _ = _setup_game(
        seed,
        p1_policy,
        p2_policy,
        p1_recipe=p1_recipe,
        p2_recipe=p2_recipe,
        p1_forces=p1_forces,
        p2_forces=p2_forces,
    )
    actions = 0
    try:
        engine.begin_turn()
        while actions < max(1, int(max_actions)) and int(getattr(engine.state, "turn", 0)) <= max(1, int(max_turns)):
            action = engine.policy_for(engine.state.active).choose(engine)
            engine.apply(action)
            actions += 1
    except GameOver as game_over:
        return game_over.winner.name if game_over.winner else "tie", engine.state.turn
    return "tie", int(getattr(engine.state, "turn", 0))


def _make_opponent_policy(name: str, seed: int) -> Any:
    if name == "random":
        return RandomLegalPolicy(random.Random(seed))
    if name == "greedy":
        return GreedyLegalPolicy(random.Random(seed))
    if name == "checkpoint_pool":
        return RLPolicy(model=LinearQModel.greedy_prior(), rng=random.Random(seed), epsilon=0.0)
    raise ValueError(f"unknown opponent policy: {name}")


def _policy_for_current_model(model: Any, seed: int) -> Any:
    if model.__class__.__name__ == "TorchActionValueModel":
        from zz.deep_rl import TorchMaskedPolicy

        return TorchMaskedPolicy(model=model, rng=random.Random(seed), epsilon=0.0)
    return RLPolicy(model=model, rng=random.Random(seed), epsilon=0.0)


def training_opponent_candidates(
    checkpoint_paths: list[str | Path],
    *,
    include_fixed: bool = True,
) -> list[LeagueOpponent]:
    candidates = []
    if include_fixed:
        candidates.extend([
            LeagueOpponent(name="random", kind="fixed_policy"),
            LeagueOpponent(name="greedy", kind="fixed_policy"),
        ])
    seen_paths: set[str] = set()
    for path_like in checkpoint_paths:
        path = Path(path_like)
        if not path.exists():
            continue
        key = _path_key(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        candidates.append(LeagueOpponent(name=_model_opponent_name(path), kind="model", model_path=str(path)))
    return candidates


def choose_training_opponent(
    opponent: str,
    *,
    seed: int,
    checkpoint_paths: list[str | Path] | None = None,
) -> TrainingOpponentChoice:
    if opponent in {"random", "greedy"}:
        return TrainingOpponentChoice(name=opponent, policy=_make_opponent_policy(opponent, seed))
    if str(opponent).startswith("model:"):
        candidates = training_opponent_candidates(checkpoint_paths or [], include_fixed=False)
        selected = next((candidate for candidate in candidates if candidate.name == opponent), None)
        if selected is None or selected.model_path is None:
            raise ValueError(f"unknown checkpoint opponent: {opponent}")
        return TrainingOpponentChoice(
            name=selected.name,
            policy=_policy_for_training_checkpoint(selected.model_path, seed + 17),
        )
    if opponent not in {"checkpoint_pool", "checkpoint_only"}:
        raise ValueError(f"unknown opponent policy: {opponent}")
    candidates = training_opponent_candidates(
        checkpoint_paths or [],
        include_fixed=opponent == "checkpoint_pool",
    )
    if not candidates:
        raise ValueError("checkpoint_only opponent requires at least one existing checkpoint")
    selected = random.Random(seed).choice(candidates)
    if selected.kind == "model":
        return TrainingOpponentChoice(
            name=selected.name,
            policy=_policy_for_training_checkpoint(selected.model_path, seed + 17),
        )
    return TrainingOpponentChoice(name=selected.name, policy=_make_opponent_policy(selected.name, seed + 17))


def _policy_for_training_checkpoint(path: str | Path, seed: int) -> Any:
    checkpoint = Path(path)
    if checkpoint.suffix.lower() == ".pt":
        from zz.deep_rl import TorchActionValueModel, TorchMaskedPolicy

        return TorchMaskedPolicy(
            model=TorchActionValueModel.load(checkpoint),
            rng=random.Random(seed),
            epsilon=0.0,
        )
    return RLPolicy(model=LinearQModel.load(checkpoint), rng=random.Random(seed), epsilon=0.0)


def _policy_for_cached_training_checkpoint(path: str | Path, seed: int, *, cache: dict[str, Any]) -> Any:
    checkpoint = Path(path)
    key = _path_key(checkpoint)
    if key not in cache:
        if checkpoint.suffix.lower() == ".pt":
            from zz.deep_rl import TorchActionValueModel

            cache[key] = TorchActionValueModel.load(checkpoint)
        else:
            cache[key] = LinearQModel.load(checkpoint)
    model = cache[key]
    if checkpoint.suffix.lower() == ".pt":
        from zz.deep_rl import TorchMaskedPolicy

        return TorchMaskedPolicy(model=model, rng=random.Random(seed), epsilon=0.0)
    return RLPolicy(model=model, rng=random.Random(seed), epsilon=0.0)


def _league_opponents(
    *,
    learner_model_path: Path,
    fixed_model_paths: list[str | Path],
    include_default_previous: bool,
) -> list[LeagueOpponent]:
    opponents = [
        LeagueOpponent(name="random", kind="fixed_policy"),
        LeagueOpponent(name="greedy", kind="fixed_policy"),
    ]
    seen_model_paths: set[str] = set()
    learner_key = _path_key(learner_model_path)
    if include_default_previous:
        default_previous = Path("data/ai_models/rl_linear_latest.json")
        if default_previous.exists() and _path_key(default_previous) != learner_key:
            opponents.append(LeagueOpponent(
                name="model:previous_rl_linear_latest",
                kind="model",
                model_path=str(default_previous),
            ))
            seen_model_paths.add(_path_key(default_previous))
    for path_like in fixed_model_paths:
        path = Path(path_like)
        if not path.exists():
            continue
        key = _path_key(path)
        if key == learner_key or key in seen_model_paths:
            continue
        seen_model_paths.add(key)
        opponents.append(LeagueOpponent(name=_model_opponent_name(path), kind="model", model_path=str(path)))
    return opponents


def _evaluate_league_opponent(
    *,
    learner_model: LinearQModel,
    learner_model_path: Path,
    opponent: LeagueOpponent,
    episodes: int,
    seed: int,
    learner_side: str,
) -> dict[str, Any]:
    learner_side = _normalise_learner_side(learner_side)
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    turns_total = 0
    for index in range(episodes):
        learner_policy = RLPolicy(model=learner_model, rng=random.Random(seed + index * 19), epsilon=0.0)
        if opponent.kind == "model":
            opponent_policy = _policy_for_training_checkpoint(opponent.model_path, seed + index * 37)
        else:
            opponent_policy = _make_opponent_policy(opponent.name, seed + index * 37)
        if learner_side == "P1":
            p1_policy, p2_policy = learner_policy, opponent_policy
        else:
            p1_policy, p2_policy = opponent_policy, learner_policy
        results["played"] += 1
        try:
            winner, turns = _play_one_game_with_policy(seed + index, p1_policy=p1_policy, p2_policy=p2_policy)
            results[winner] = results.get(winner, 0) + 1
            turns_total += turns
        except Exception:
            results["errors"] += 1
    completed = max(1, results["P1"] + results["P2"] + results["tie"])
    row = {
        "opponent": opponent.name,
        "kind": opponent.kind,
        "modelPath": opponent.model_path,
        "learnerSide": learner_side,
        "results": results,
        "winRate": results[learner_side] / completed,
        "averageTurns": turns_total / completed,
    }
    if opponent.kind == "model":
        row["learnerModelPath"] = str(learner_model_path)
    return row


def _evaluate_league_opponent_multi_seed(
    *,
    learner_model: LinearQModel,
    learner_model_path: Path,
    opponent: LeagueOpponent,
    episodes: int,
    seed: int,
    seed_count: int,
    learner_side: str,
) -> dict[str, Any]:
    rows = [
        _evaluate_league_opponent(
            learner_model=learner_model,
            learner_model_path=learner_model_path,
            opponent=opponent,
            episodes=episodes,
            seed=seed + seed_index * 1009,
            learner_side=learner_side,
        )
        for seed_index in range(max(1, int(seed_count)))
    ]
    if len(rows) == 1:
        row = dict(rows[0])
        row["seedCount"] = 1
        row["minWinRate"] = row["winRate"]
        row["meanWinRate"] = row["winRate"]
        row["seedRuns"] = rows
        return row
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    turns_total = 0.0
    completed_total = 0
    for row in rows:
        row_results = row["results"]
        completed = max(1, row_results["P1"] + row_results["P2"] + row_results["tie"])
        completed_total += completed
        turns_total += row["averageTurns"] * completed
        for key, value in row_results.items():
            results[key] = results.get(key, 0) + int(value)
    learner_side = _normalise_learner_side(learner_side)
    merged = {
        "opponent": rows[0]["opponent"],
        "kind": rows[0]["kind"],
        "modelPath": rows[0].get("modelPath"),
        "learnerSide": learner_side,
        "results": results,
        "winRate": results[learner_side] / max(1, completed_total),
        "meanWinRate": sum(row["winRate"] for row in rows) / len(rows),
        "minWinRate": min(row["winRate"] for row in rows),
        "maxWinRate": max(row["winRate"] for row in rows),
        "averageTurns": turns_total / max(1, completed_total),
        "seedCount": len(rows),
        "seedRuns": rows,
    }
    if rows[0].get("learnerModelPath") is not None:
        merged["learnerModelPath"] = rows[0]["learnerModelPath"]
    return merged


def _best_checkpoint_paths(manager: CheckpointManager) -> list[Path]:
    paths: list[Path] = []
    for entry in manager.manifest.get("best", {}).values():
        path = Path(str(entry.get("path", "")))
        if path.exists():
            paths.append(path)
    return paths


def _dedupe_existing_paths(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path_like in paths:
        path = Path(path_like)
        if not path.exists():
            continue
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _path_key(path: str | Path) -> str:
    return str(Path(path).resolve()).lower()


def _model_opponent_name(path: str | Path) -> str:
    path = Path(path)
    if path.stem in {"latest", "best"}:
        return f"model:{path.parent.name}_{path.stem}"
    return f"model:{path.stem}"


def action_signature(engine: Engine, player: Player, action: Action) -> dict[str, Any]:
    return _shared_action_signature(engine, player, action)


def find_replay_action(
    engine: Engine,
    player: Player,
    recorded: dict[str, Any],
    legal_actions: list[Action],
) -> Action | None:
    return find_recorded_action(engine, player, recorded, legal_actions)


def _action_to_dict(action: Action, *, engine: Engine | None = None, player: Player | None = None) -> dict[str, Any]:
    return action_record_from_action(action, engine=engine, player=player)


def _action_from_dict(data: dict[str, Any]) -> Action:
    return _shared_action_from_record(data)


def _json_scalar(value: Any) -> Any:
    return _shared_json_scalar(value)


def _force_life_total(player: Player) -> int:
    return int(sum(force.life for force in player.forces if not force.destroyed))


def _forces_alive(player: Player) -> int:
    return sum(1 for force in player.forces if not force.destroyed)


def _counter_to_json(counter: Counter[int]) -> dict[str, int]:
    return {str(key): value for key, value in sorted(counter.items())}


def _linear_decay(start: float, end: float, index: int, total: int) -> float:
    if total <= 1:
        return end
    return start + (end - start) * (index / float(total - 1))


def _validate_learner_side_mode(mode: str) -> None:
    if mode == "alternate":
        return
    _normalise_learner_side(mode)


def _learner_side_for_episode(mode: str, index: int) -> str:
    if mode == "alternate":
        return "P1" if index % 2 == 0 else "P2"
    return _normalise_learner_side(mode)


def _fixed_eval_sides_for_mode(mode: str) -> tuple[str, ...]:
    if mode == "alternate":
        return ("P1", "P2")
    return (_normalise_learner_side(mode),)


def _fixed_eval_metric(opponent: str, learner_side: str) -> str:
    return opponent if learner_side == "P1" else f"{opponent}_p2"


def _side_seed_offset(learner_side: str) -> int:
    return 0 if learner_side == "P1" else 50000


def _reward_for_learner(winner: str, learner_side: str) -> float:
    if winner == learner_side:
        return 1.0
    if winner == "tie":
        return -0.2
    return -1.0


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run RL training-quality experiments.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    train = subparsers.add_parser("train-quality")
    train.add_argument("--episodes", type=int, default=200)
    train.add_argument("--seed", type=int, default=20260523)
    train.add_argument("--out-dir", default="data/ai_training/quality_latest")
    train.add_argument("--eval-interval", type=int, default=50)
    train.add_argument("--eval-episodes", type=int, default=20)
    train.add_argument("--opponent", choices=["random", "greedy", "self", "checkpoint_pool", "checkpoint_only"], default="greedy")
    train.add_argument("--loss-replay-decisions", type=int, default=3)
    train.add_argument("--loss-replay-alternatives", type=int, default=2)
    train.add_argument("--loss-replay-max-branches", type=int, default=6)
    train.add_argument("--league-eval-episodes", type=int)
    train.add_argument("--learner-side", choices=["P1", "P2", "alternate"], default="alternate")
    train.add_argument("--initial-model")
    train.add_argument("--multi-seed-eval-count", type=int, default=1)
    train.add_argument("--multi-seed-eval-episodes", type=int)
    train.add_argument("--use-benchmark-deck-pool", action="store_true")
    train.add_argument("--deck-root", type=Path)
    train.add_argument("--deck-matrix-eval-episodes", type=int, default=0)
    args = parser.parse_args(argv)
    deck_pool = []
    deck_pool_source = "none"
    if args.use_benchmark_deck_pool:
        from zz.deck_ai import load_benchmark_decks

        deck_pool = load_benchmark_decks(args.deck_root)
        deck_pool_source = "benchmark"
    report = run_quality_training(
        episodes=args.episodes,
        seed=args.seed,
        out_dir=args.out_dir,
        eval_interval=args.eval_interval,
        eval_episodes=args.eval_episodes,
        opponent=args.opponent,
        loss_replay_decisions=args.loss_replay_decisions,
        loss_replay_alternatives=args.loss_replay_alternatives,
        loss_replay_max_branches=args.loss_replay_max_branches,
        league_eval_episodes=args.league_eval_episodes,
        learner_side=args.learner_side,
        initial_model_path=args.initial_model,
        multi_seed_eval_count=args.multi_seed_eval_count,
        multi_seed_eval_episodes=args.multi_seed_eval_episodes,
        deck_pool=deck_pool,
        deck_pool_source=deck_pool_source,
        deck_matrix_eval_episodes=args.deck_matrix_eval_episodes,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
