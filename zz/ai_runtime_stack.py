from __future__ import annotations

from pathlib import Path
from typing import Any

from zz.rl_ai import DEEP_LOOKAHEAD_WEIGHT


CURRENT_TREE_BASELINE_TRANSITION_EVALUATOR_PATH = Path(
    "local_ai_training/baseline_goal_20260602/deep_g5_relative_push_v6_defaultoff/"
    "targeted_tree_transition_conditioned_v1/"
    "candidate_v20_v19_refit_action_tags_no_untrained_state/"
    "transition_action_set_conditioned_v20_refit_action_tags_no_untrained_state_seed202606079.json"
)


def minimal_tree_runtime_weights(
    transition_evaluator_path: str | Path | None,
    *,
    lookahead_weight: float = DEEP_LOOKAHEAD_WEIGHT,
    simulations: int = 8,
    root_width: int = 6,
    depth: int = 2,
    cpuct: float = 1.25,
    value_weight: float = 1.0,
    value_source: str = "hybrid",
    transition_evaluator_weight: float = 0.25,
    transition_evaluator_horizon_turns: int = 2,
    transition_evaluator_max_actions: int = 8,
    transition_evaluator_max_calls: int = 16,
    key_decisions_only: bool = True,
) -> dict[str, Any]:
    """Default-off tree stack with MCTS as root selector and Deep lookahead as value support."""
    weights: dict[str, Any] = {
        "card_aware_prior_weight": 0.0,
        "opponent_adaptive_prior_weight": 0.0,
        "deck_plan_prior_weight": 0.0,
        "concrete_plan_prior_weight": 0.0,
        "tactical_prior_weight": 0.0,
        "target_selection_prior_weight": 0.0,
        "lookahead_weight": float(lookahead_weight),
        "bounded_mcts_planner_enabled": 1,
        "bounded_mcts_planner_simulations": int(simulations),
        "bounded_mcts_planner_root_width": int(root_width),
        "bounded_mcts_planner_depth": int(depth),
        "bounded_mcts_planner_cpuct": float(cpuct),
        "bounded_mcts_planner_value_weight": float(value_weight),
        "bounded_mcts_planner_value_source": str(value_source),
        "bounded_mcts_planner_key_decisions_only": 1 if key_decisions_only else 0,
        "bounded_mcts_planner_primary_decision_path": 1,
        "transition_evaluator_weight": 0.0,
    }
    if transition_evaluator_path is not None:
        weights.update({
            "transition_evaluator_path": str(transition_evaluator_path),
            "transition_evaluator_weight": float(transition_evaluator_weight),
            "transition_evaluator_horizon_turns": int(transition_evaluator_horizon_turns),
            "transition_evaluator_max_actions": int(transition_evaluator_max_actions),
            "transition_evaluator_max_calls": int(transition_evaluator_max_calls),
        })
    return weights


def current_tree_baseline_runtime_weights(
    transition_evaluator_path: str | Path | None = CURRENT_TREE_BASELINE_TRANSITION_EVALUATOR_PATH,
) -> dict[str, Any]:
    """Current promoted comparison baseline: protected Deep plus v20 evaluator-valued MCTS."""
    return minimal_tree_runtime_weights(
        transition_evaluator_path,
        value_source="transition_evaluator",
        transition_evaluator_weight=1.0,
    )
