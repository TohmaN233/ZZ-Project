from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zz.model import Action


PLANNER_VERSION = "turn_planner_v1"


class TurnIntent(Enum):
    GROW_BASE = "grow_base"
    PRESERVE_READY_COLORS = "preserve_ready_colors"
    HOLD_DEFENSE = "hold_defense"
    REMOVE_THREAT = "remove_threat"
    BUFF_FOR_COMBAT = "buff_for_combat"
    BREAK_FORCE = "break_force"
    PRESSURE_LIFE = "pressure_life"
    PROTECT_COMBO_PIECE = "protect_combo_piece"
    SEARCH_DRAW_SETUP = "search_draw_setup"
    EXECUTE_COMBO = "execute_combo"
    PREPARE_NEXT_TURN_LETHAL = "prepare_next_turn_lethal"
    TAKE_LETHAL_NOW = "take_lethal_now"


@dataclass(frozen=True)
class CandidatePlan:
    intent: TurnIntent
    actions: list[dict[str, Any]]
    score: float
    reason_tags: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanTrace:
    version: str
    chosen_intent: TurnIntent
    first_action: dict[str, Any]
    candidate_count: int
    chosen_plan: dict[str, Any]
    rejected_plans: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["chosen_intent"] = self.chosen_intent.value
        row["chosen_plan"]["intent"] = self.chosen_plan["intent"].value
        for rejected in row["rejected_plans"]:
            rejected["intent"] = rejected["intent"].value
        return row


def generate_candidate_plans_from_actions(
    legal_actions: list[Action],
    *,
    state_tags: set[str],
    deck_plan_tags: set[str],
) -> list[CandidatePlan]:
    state_tag_set = set(state_tags)
    deck_plan_tag_set = set(deck_plan_tags)
    actions = list(legal_actions)

    plans = [
        _candidate_plan_from_action(action, state_tag_set, deck_plan_tag_set)
        for action in actions
    ]
    plans.extend(_sequence_candidate_plans_from_actions(actions, state_tag_set, deck_plan_tag_set))
    return plans


def generate_candidate_plans_from_action_choices(
    choices: list[tuple[Action, dict[str, float]]],
    *,
    state_tags: set[str],
    deck_plan_tags: set[str],
) -> list[CandidatePlan]:
    state_tag_set = set(state_tags)
    deck_plan_tag_set = set(deck_plan_tags)
    normalized = [(action, dict(features or {})) for action, features in choices]
    plans = [
        _candidate_plan_from_action_with_features(action, features, state_tag_set, deck_plan_tag_set)
        for action, features in normalized
    ]
    plans.extend(_sequence_candidate_plans_from_action_choices(normalized, state_tag_set, deck_plan_tag_set))
    return plans


def choose_plan_from_candidates(candidates: list[CandidatePlan], *, state_tags: set[str]) -> PlanTrace:
    if not candidates:
        raise ValueError("at least one candidate plan is required")

    scored = [
        (_adjusted_plan_score(candidate, state_tags), candidate)
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    chosen_score, chosen = scored[0]

    return PlanTrace(
        version=PLANNER_VERSION,
        chosen_intent=chosen.intent,
        first_action=chosen.actions[0],
        candidate_count=len(candidates),
        chosen_plan=_trace_plan(chosen, chosen_score),
        rejected_plans=[
            _trace_plan(candidate, score)
            for score, candidate in scored[1:]
        ],
    )


def _adjusted_plan_score(candidate: CandidatePlan, state_tags: set[str]) -> float:
    score = float(candidate.score)
    risks = set(candidate.risk_tags)
    reasons = set(candidate.reason_tags)

    if {"enemy_dp_pressure", "own_low_life", "last_blocker"}.issubset(state_tags):
        if candidate.intent is TurnIntent.HOLD_DEFENSE:
            score += 0.45
        if "spends_last_blocker" in risks:
            score -= 0.55

    if {"observed_aggressive_pressure", "own_low_life"}.issubset(state_tags):
        if candidate.intent is TurnIntent.HOLD_DEFENSE:
            score += 0.55
        if candidate.intent is TurnIntent.PRESSURE_LIFE:
            score -= 0.45
        if "spends_last_blocker" in risks:
            score -= 0.35

    if {"early_game", "resource_sensitive_deck", "safe_field_to_base"}.issubset(state_tags):
        if candidate.intent is TurnIntent.GROW_BASE:
            score += 0.35
        if "misses_base_growth" in risks:
            score -= 0.25

    if "unlock_next_turn_color" in reasons:
        score += 0.10

    return score


def _candidate_plan_from_action(
    action: Action,
    state_tags: set[str],
    deck_plan_tags: set[str],
) -> CandidatePlan:
    action_trace = _trace_action(action)
    kind = action.kind
    payload = dict(action.payload)

    if kind == "end_turn":
        if (
            {"enemy_dp_pressure", "own_low_life"}.issubset(state_tags)
            or {"observed_aggressive_pressure", "own_low_life"}.issubset(state_tags)
        ):
            reason_tags = ("enemy_dp_pressure", "own_low_life")
            if "observed_aggressive_pressure" in state_tags:
                reason_tags += ("preserve_life_against_greedy",)
            if "control" in deck_plan_tags:
                reason_tags += ("control",)
            return CandidatePlan(
                intent=TurnIntent.HOLD_DEFENSE,
                actions=[action_trace],
                score=0.5,
                reason_tags=reason_tags,
            )
        return CandidatePlan(
            intent=TurnIntent.PRESERVE_READY_COLORS,
            actions=[action_trace],
            score=0.5,
            reason_tags=("end_turn",),
        )

    if kind == "move_card":
        direction = payload.get("direction")
        if direction == "field_to_base":
            return CandidatePlan(
                intent=TurnIntent.GROW_BASE,
                actions=[action_trace],
                score=0.5,
                reason_tags=("field_to_base",),
            )
        if direction == "base_to_field":
            return CandidatePlan(
                intent=TurnIntent.PRESSURE_LIFE,
                actions=[action_trace],
                score=0.5,
                reason_tags=("base_to_field",),
            )

    if kind == "attack":
        return CandidatePlan(
            intent=TurnIntent.PRESSURE_LIFE,
            actions=[action_trace],
            score=0.5,
            reason_tags=("attack",),
        )

    if kind == "play_card":
        if "enemy_must_answer_threat" in state_tags:
            return CandidatePlan(
                intent=TurnIntent.REMOVE_THREAT,
                actions=[action_trace],
                score=0.5,
                reason_tags=("enemy_must_answer_threat",),
            )
        return CandidatePlan(
            intent=TurnIntent.SEARCH_DRAW_SETUP,
            actions=[action_trace],
            score=0.5,
            reason_tags=("play_card",),
        )

    return CandidatePlan(
        intent=TurnIntent.PRESERVE_READY_COLORS,
        actions=[action_trace],
        score=0.5,
        reason_tags=("fallback",),
    )


def _candidate_plan_from_action_with_features(
    action: Action,
    features: dict[str, float],
    state_tags: set[str],
    deck_plan_tags: set[str],
) -> CandidatePlan:
    if (
        action.kind == "move_card"
        and action.payload.get("direction") == "base_to_field"
        and {"enemy_dp_pressure", "own_low_life"}.issubset(state_tags)
        and _positive(features, "move_base_to_field_can_block")
        and not _positive(features, "move_base_to_field_low_impact_mana_minion")
    ):
        reason_tags = ("base_to_field_blocker", "enemy_dp_pressure", "own_low_life")
        if "observed_aggressive_pressure" in state_tags:
            reason_tags += ("preserve_life_against_greedy",)
        if "control" in deck_plan_tags:
            reason_tags += ("control",)
        return CandidatePlan(
            intent=TurnIntent.HOLD_DEFENSE,
            actions=[_trace_action(action)],
            score=0.62,
            reason_tags=reason_tags,
        )
    return _candidate_plan_from_action(action, state_tags, deck_plan_tags)


def _sequence_candidate_plans_from_actions(
    actions: list[Action],
    state_tags: set[str],
    deck_plan_tags: set[str],
) -> list[CandidatePlan]:
    end_turn = next((action for action in actions if action.kind == "end_turn"), None)
    if end_turn is None:
        return []

    plans: list[CandidatePlan] = []
    for action in actions:
        if action.kind != "move_card" or action.payload.get("direction") != "field_to_base":
            continue
        reason_tags = ("field_to_base", "setup_then_hold")
        score = 0.55
        if {"early_game", "safe_field_to_base", "resource_sensitive_deck"}.issubset(state_tags):
            reason_tags += ("unlock_next_turn_color",)
            score += 0.08
        if "control" in deck_plan_tags:
            reason_tags += ("control",)
        plans.append(CandidatePlan(
            intent=TurnIntent.GROW_BASE,
            actions=[_trace_action(action), _trace_action(end_turn)],
            score=score,
            reason_tags=reason_tags,
        ))
    return plans


def _sequence_candidate_plans_from_action_choices(
    choices: list[tuple[Action, dict[str, float]]],
    state_tags: set[str],
    deck_plan_tags: set[str],
) -> list[CandidatePlan]:
    end_turn = next((action for action, _ in choices if action.kind == "end_turn"), None)
    if end_turn is None:
        return []

    plans: list[CandidatePlan] = []
    for action, features in choices:
        if (
            action.kind != "move_card"
            or action.payload.get("direction") != "base_to_field"
            or not {"enemy_dp_pressure", "own_low_life"}.issubset(state_tags)
            or not _positive(features, "move_base_to_field_can_block")
            or _positive(features, "move_base_to_field_low_impact_mana_minion")
        ):
            continue
        reason_tags = ("base_to_field_blocker", "setup_then_hold", "enemy_dp_pressure", "own_low_life")
        if "observed_aggressive_pressure" in state_tags:
            reason_tags += ("preserve_life_against_greedy",)
        if "control" in deck_plan_tags:
            reason_tags += ("control",)
        plans.append(CandidatePlan(
            intent=TurnIntent.HOLD_DEFENSE,
            actions=[_trace_action(action), _trace_action(end_turn)],
            score=0.72,
            reason_tags=reason_tags,
        ))
    return plans


def _positive(features: dict[str, float], key: str) -> bool:
    try:
        return float(features.get(key, 0.0) or 0.0) > 0.0
    except (TypeError, ValueError):
        return False


def _trace_action(action: Action) -> dict[str, Any]:
    return {"kind": action.kind, "payload": dict(action.payload)}


def _trace_plan(candidate: CandidatePlan, score: float) -> dict[str, Any]:
    return {
        "intent": candidate.intent,
        "actions": candidate.actions,
        "score": score,
        "reasonTags": list(candidate.reason_tags),
        "riskTags": list(candidate.risk_tags),
    }
