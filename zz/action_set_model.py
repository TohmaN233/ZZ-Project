from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from zz.action_set_dataset import summarize_action_set_shadow_rows


ACTION_SET_MODEL_VERSION = "action_set_linear_scorer_v1"


@dataclass
class ActionSetLinearScorer:
    weights: dict[str, float] = field(default_factory=dict)
    modelVersion: str = ACTION_SET_MODEL_VERSION

    def score_row(self, row: Mapping[str, Any]) -> list[float | None]:
        mask = _mask(row)
        scores: list[float | None] = []
        for slot, enabled in enumerate(mask):
            if not enabled:
                scores.append(None)
                continue
            features = _slot_features(row, slot)
            scores.append(sum(self.weights.get(name, 0.0) * value for name, value in features.items()))
        return scores

    def score_rows(self, rows: list[Mapping[str, Any]]) -> list[list[float | None]]:
        return [self.score_row(row) for row in rows]

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.modelVersion,
            "weights": dict(sorted(self.weights.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionSetLinearScorer":
        weights = {
            str(name): float(value)
            for name, value in dict(data.get("weights") or {}).items()
        }
        return cls(
            weights=weights,
            modelVersion=str(data.get("modelVersion") or ACTION_SET_MODEL_VERSION),
        )


def train_action_set_linear_scorer(
    rows: list[Mapping[str, Any]],
    *,
    epochs: int = 5,
    learning_rate: float = 0.1,
    margin: float = 1.0,
) -> ActionSetLinearScorer:
    scorer = ActionSetLinearScorer()
    if epochs <= 0 or learning_rate <= 0.0:
        return scorer

    for _epoch in range(int(epochs)):
        for row in rows:
            selected_slot = _selected_slot(row)
            legal_slots = _legal_slots(row)
            if selected_slot is None or selected_slot not in legal_slots:
                continue
            wrong_slots = [slot for slot in legal_slots if slot != selected_slot]
            if not wrong_slots:
                continue
            scores = scorer.score_row(row)
            best_wrong = max(wrong_slots, key=lambda slot: (scores[slot] or 0.0, -slot))
            selected_score = float(scores[selected_slot] or 0.0)
            wrong_score = float(scores[best_wrong] or 0.0)
            if selected_score >= wrong_score + float(margin):
                continue
            _apply_pairwise_update(
                scorer.weights,
                _slot_features(row, selected_slot),
                _slot_features(row, best_wrong),
                float(learning_rate),
            )
    return scorer


def summarize_action_set_scorer_shadow(
    rows: list[Mapping[str, Any]],
    scorer: ActionSetLinearScorer,
) -> dict[str, Any]:
    scored_rows: list[dict[str, Any]] = []
    for row in rows:
        scored = dict(row)
        scored["shadowScores"] = scorer.score_row(row)
        scored_rows.append(scored)
    return summarize_action_set_shadow_rows(scored_rows)


def _apply_pairwise_update(
    weights: dict[str, float],
    selected_features: Mapping[str, float],
    wrong_features: Mapping[str, float],
    learning_rate: float,
) -> None:
    for name, value in selected_features.items():
        weights[name] = weights.get(name, 0.0) + learning_rate * value
    for name, value in wrong_features.items():
        weights[name] = weights.get(name, 0.0) - learning_rate * value


def _slot_features(row: Mapping[str, Any], slot: int) -> dict[str, float]:
    global_names = [str(name) for name in row.get("globalFeatureNames") or []]
    global_values = _float_list(row.get("global_"))
    action_names = [str(name) for name in row.get("actionFeatureNames") or []]
    actions = row.get("actions_") or []
    action_values = _float_list(actions[slot] if 0 <= slot < len(actions) else [])

    features: dict[str, float] = {}
    nonzero_globals = [
        (name, value)
        for name, value in zip(global_names, global_values)
        if value != 0.0
    ]
    nonzero_actions = [
        (name, value)
        for name, value in zip(action_names, action_values)
        if value != 0.0
    ]
    for action_name, action_value in nonzero_actions:
        features[f"action::{action_name}"] = action_value
    for global_name, global_value in nonzero_globals:
        for action_name, action_value in nonzero_actions:
            features[f"cross::{global_name}::{action_name}"] = global_value * action_value
    return features


def _mask(row: Mapping[str, Any]) -> list[bool]:
    value = row.get("mask_") or []
    if not isinstance(value, (list, tuple)):
        return []
    return [bool(item) for item in value]


def _legal_slots(row: Mapping[str, Any]) -> list[int]:
    return [slot for slot, enabled in enumerate(_mask(row)) if enabled]


def _selected_slot(row: Mapping[str, Any]) -> int | None:
    try:
        return int(row.get("selectedActionSlot"))
    except (TypeError, ValueError):
        return None


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[float] = []
    for item in value:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            out.append(0.0)
    return out
