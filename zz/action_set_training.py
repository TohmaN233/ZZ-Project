from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping

from zz.action_set_model import (
    ACTION_SET_MODEL_VERSION,
    summarize_action_set_scorer_shadow,
    train_action_set_linear_scorer,
)


ACTION_SET_SHADOW_TRAINING_VERSION = "action_set_shadow_training_v1"
PHASE_P_ACTION_VALUE_TRAINING_VERSION = "phase_p_action_value_training_v1"
PHASE_P_ACTION_VALUE_MODEL_VERSION = "phase_p_action_value_linear_v1"


@dataclass
class PhasePActionValueScorer:
    weights: dict[str, float] = field(default_factory=dict)
    modelVersion: str = PHASE_P_ACTION_VALUE_MODEL_VERSION

    def score_row(self, row: Mapping[str, Any]) -> list[float | None]:
        mask = _phase_p_mask(row)
        actions = list(row.get("actions") or [])
        scores: list[float | None] = []
        for slot, enabled in enumerate(mask):
            if not enabled:
                scores.append(None)
                continue
            action = actions[slot] if 0 <= slot < len(actions) and isinstance(actions[slot], Mapping) else {}
            features = _phase_p_features_for_action(row, action)
            scores.append(sum(self.weights.get(name, 0.0) * value for name, value in features.items()))
        return scores

    def score_rows(self, rows: list[Mapping[str, Any]]) -> list[list[float | None]]:
        return [self.score_row(row) for row in rows]

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.modelVersion,
            "weights": {name: float(value) for name, value in sorted(self.weights.items())},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhasePActionValueScorer":
        return cls(
            weights={
                str(name): float(value)
                for name, value in dict(data.get("weights") or {}).items()
            },
            modelVersion=str(data.get("modelVersion") or PHASE_P_ACTION_VALUE_MODEL_VERSION),
        )


def train_action_set_shadow_report(
    rows: list[Mapping[str, Any]],
    *,
    eval_fraction: float = 0.25,
    epochs: int = 5,
    learning_rate: float = 0.1,
    margin: float = 1.0,
) -> dict[str, Any]:
    row_list = list(rows)
    if not row_list:
        raise ValueError("action-set shadow training requires at least one row")

    train_rows, eval_rows = _train_eval_split(row_list, eval_fraction=eval_fraction)
    scorer = train_action_set_linear_scorer(
        train_rows,
        epochs=epochs,
        learning_rate=learning_rate,
        margin=margin,
    )
    shadow_summary = summarize_action_set_scorer_shadow(eval_rows, scorer)
    return {
        "trainingVersion": ACTION_SET_SHADOW_TRAINING_VERSION,
        "modelVersion": ACTION_SET_MODEL_VERSION,
        "rowCount": len(row_list),
        "trainRowCount": len(train_rows),
        "evalRowCount": len(eval_rows),
        "evalFraction": float(eval_fraction),
        "epochs": int(epochs),
        "learningRate": float(learning_rate),
        "margin": float(margin),
        "shadowSummary": shadow_summary,
        "model": scorer.to_dict(),
        "defaultRuntimeChanged": False,
        "candidatePruningEnabled": False,
    }


def _train_eval_split(
    rows: list[Mapping[str, Any]],
    *,
    eval_fraction: float,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    if len(rows) == 1:
        return list(rows), list(rows)
    bounded_fraction = max(0.0, min(0.9, float(eval_fraction)))
    eval_count = max(1, int(round(len(rows) * bounded_fraction))) if bounded_fraction > 0.0 else 1
    eval_count = min(len(rows) - 1, eval_count)
    stride = max(1, int(round(len(rows) / eval_count)))
    eval_indexes: set[int] = set()
    for index in range(stride - 1, len(rows), stride):
        eval_indexes.add(index)
        if len(eval_indexes) >= eval_count:
            break
    index = len(rows) - 1
    while len(eval_indexes) < eval_count and index >= 0:
        eval_indexes.add(index)
        index -= 1
    train_rows = [row for index, row in enumerate(rows) if index not in eval_indexes]
    eval_rows = [row for index, row in enumerate(rows) if index in eval_indexes]
    if not train_rows:
        return list(rows), list(rows)
    return train_rows, eval_rows


def train_phase_p_action_value_report(
    rows: list[Mapping[str, Any]],
    *,
    eval_fraction: float = 0.25,
    epochs: int = 10,
    learning_rate: float = 0.05,
    initial_weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    row_list = list(rows)
    if not row_list:
        raise ValueError("Phase P action-value training requires at least one row")
    if _phase_p_has_counterfactual_pair_rows(row_list):
        raise ValueError(
            "Phase P single-action regression must not train from freshCounterfactualLabel "
            "same-state pair rows; use the YGO action-value/pairwise training path instead"
        )
    if epochs <= 0:
        raise ValueError("epochs must be positive")
    if learning_rate <= 0.0:
        raise ValueError("learning_rate must be positive")

    train_rows, eval_rows = _train_eval_split(row_list, eval_fraction=eval_fraction)
    feature_names = _phase_p_feature_names(row_list)
    initial = {str(name): float(value) for name, value in dict(initial_weights or {}).items()}
    weights = {name: float(initial.get(name, 0.0)) for name in feature_names}
    for _epoch in range(int(epochs)):
        for row in train_rows:
            features = _phase_p_features(row)
            target = _phase_p_target(row)
            prediction = sum(weights.get(name, 0.0) * value for name, value in features.items())
            error = prediction - target
            training_weight = _phase_p_training_weight(row)
            for name, value in features.items():
                weights[name] = weights.get(name, 0.0) - float(learning_rate) * training_weight * error * value

    train_eval = _phase_p_value_eval(train_rows, weights)
    holdout_eval = _phase_p_value_eval(eval_rows, weights)
    train_action_set_eval = _phase_p_action_set_eval(train_rows, weights)
    holdout_action_set_eval = _phase_p_action_set_eval(eval_rows, weights)
    coverage = _phase_p_coverage(row_list)
    retained_initial_weights = sum(1 for name in feature_names if name in initial)
    return {
        "trainingVersion": PHASE_P_ACTION_VALUE_TRAINING_VERSION,
        "modelVersion": PHASE_P_ACTION_VALUE_MODEL_VERSION,
        "rowCount": len(row_list),
        "trainRowCount": len(train_rows),
        "evalRowCount": len(eval_rows),
        "evalFraction": float(eval_fraction),
        "epochs": int(epochs),
        "learningRate": float(learning_rate),
        "initialWeightsLoaded": len(initial),
        "initialWeightsRetained": int(retained_initial_weights),
        "weightedTraining": any(not math.isclose(_phase_p_training_weight(row), 1.0) for row in row_list),
        "coverage": coverage,
        "train": train_eval,
        "eval": holdout_eval,
        "trainActionSet": train_action_set_eval,
        "evalActionSet": holdout_action_set_eval,
        "model": {
            "modelVersion": PHASE_P_ACTION_VALUE_MODEL_VERSION,
            "featureNames": feature_names,
            "weights": {name: weights[name] for name in feature_names},
        },
        "defaultRuntimeChanged": False,
        "candidatePruningEnabled": False,
        "promotionApproved": False,
    }


def _phase_p_feature_names(rows: list[Mapping[str, Any]]) -> list[str]:
    names: set[str] = {"bias"}
    for row in rows:
        names.update(_phase_p_features(row).keys())
    return sorted(names)


def _phase_p_features(row: Mapping[str, Any]) -> dict[str, float]:
    action = _phase_p_row_action(row)
    return _phase_p_features_for_action(row, action)


def _phase_p_row_action(row: Mapping[str, Any]) -> Mapping[str, Any]:
    action = row.get("action")
    if isinstance(action, Mapping):
        return action
    actions = row.get("actions")
    if not isinstance(actions, list | tuple):
        return {}
    slot = _phase_p_row_action_slot(row)
    if slot is None or slot < 0 or slot >= len(actions):
        return {}
    selected = actions[slot]
    return selected if isinstance(selected, Mapping) else {}


def _phase_p_row_action_slot(row: Mapping[str, Any]) -> int | None:
    for key in ("actionSlot", "selectedActionSlot", "teacherTopSlot"):
        value = row.get(key)
        try:
            if value is not None and not isinstance(value, bool):
                return int(value)
        except (TypeError, ValueError):
            continue
    label = row.get("freshCounterfactualLabel")
    if isinstance(label, Mapping):
        value = label.get("preferredSlot")
        try:
            if value is not None and not isinstance(value, bool):
                return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _phase_p_features_for_action(row: Mapping[str, Any], action: Mapping[str, Any]) -> dict[str, float]:
    decision_kind = _phase_p_context_value(row, "decisionKind", default="unknown")
    deck_source = _phase_p_context_value(row, "deckSource", "sourceDeckSource", "playerDeckSource", default="unknown")
    opponent_suite = _phase_p_context_value(row, "opponentSuite", "sourceSuiteKind", "suiteKind", default="unknown")
    source_suite = _phase_p_context_value(row, "sourceSuiteKind", "suiteKind", "opponentSuite", default="unknown")
    difficulty = _phase_p_context_value(row, "difficulty", default="unknown")
    true_turn_order = _phase_p_context_value(row, "trueTurnOrder", default="unknown")
    opponent_baseline = _phase_p_context_value(
        row,
        "opponentBaselineLabel",
        "sourceOpponentBaselineLabel",
        default="unknown",
    )
    action_kind = _phase_p_safe_value(action.get("kind"), default="unknown")
    features = {
        "bias": 1.0,
        f"decisionKind={decision_kind}": 1.0,
        f"deckSource={deck_source}": 1.0,
        f"opponentSuite={opponent_suite}": 1.0,
        f"sourceSuiteKind={source_suite}": 1.0,
        f"difficulty={difficulty}": 1.0,
        f"trueTurnOrder={true_turn_order}": 1.0,
        f"opponentBaselineLabel={opponent_baseline}": 1.0,
        f"actionKind={action_kind}": 1.0,
        f"decisionKind={decision_kind}|actionKind={action_kind}": 1.0,
        f"deckSource={deck_source}|decisionKind={decision_kind}|actionKind={action_kind}": 1.0,
        f"sourceSuiteKind={source_suite}|trueTurnOrder={true_turn_order}|decisionKind={decision_kind}": 1.0,
        f"trueTurnOrder={true_turn_order}|decisionKind={decision_kind}|actionKind={action_kind}": 1.0,
        f"opponentBaselineLabel={opponent_baseline}|decisionKind={decision_kind}|actionKind={action_kind}": 1.0,
    }
    for name, value in _phase_p_action_payload_features(action).items():
        features[name] = value
        features[f"decisionKind={decision_kind}|{name}"] = value
    return features


def _phase_p_context_value(row: Mapping[str, Any], *names: str, default: str) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    nested_metadata = [
        metadata,
        metadata.get("label") if isinstance(metadata.get("label"), Mapping) else {},
        metadata.get("decision") if isinstance(metadata.get("decision"), Mapping) else {},
        metadata.get("action") if isinstance(metadata.get("action"), Mapping) else {},
    ]
    for name in names:
        value = _phase_p_safe_value(row.get(name), default="")
        if value:
            return value
        for source in nested_metadata:
            value = _phase_p_safe_value(source.get(name), default="")
            if value:
                return value
    return default


def _phase_p_action_payload_features(action: Mapping[str, Any]) -> dict[str, float]:
    payload = action.get("payload") if isinstance(action.get("payload"), Mapping) else {}
    signature = action.get("signature") if isinstance(action.get("signature"), Mapping) else {}
    signature_payload = signature.get("payload") if isinstance(signature.get("payload"), Mapping) else {}
    features: dict[str, float] = {}
    for key in (
        "direction",
        "choice",
        "phase",
        "target_kind",
        "targetKind",
        "replacement_zone",
        "replacementZone",
        "color",
        "from_color",
        "to_color",
    ):
        value = _phase_p_safe_value(payload.get(key), default="")
        if value:
            features[f"actionPayload.{key}={value}"] = 1.0
    card_id = (
        _phase_p_safe_value(payload.get("card_id"), default="")
        or _phase_p_safe_value(payload.get("cardId"), default="")
        or _phase_p_card_id_from_signature_payload(signature_payload)
    )
    if card_id:
        features[f"actionCardId={card_id}"] = 1.0
    if _phase_p_has_replacement_payload(payload):
        features["focusedAction=replacement"] = 1.0
    if _phase_p_safe_value(action.get("kind"), default="") == "swap_mana_color":
        features["focusedAction=color_swap"] = 1.0
    return features


def _phase_p_card_id_from_signature_payload(payload: Mapping[str, Any]) -> str:
    for key in ("iid", "card", "source", "target"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            card_id = _phase_p_safe_value(value.get("cardId") or value.get("card_id"), default="")
            if card_id:
                return card_id
    return ""


def _phase_p_has_replacement_payload(payload: Mapping[str, Any]) -> bool:
    return any(
        payload.get(key) is not None
        for key in ("replace_base_iid", "replaceBaseIid", "replace_field_iid", "replaceFieldIid")
    )


def _phase_p_safe_value(value: Any, *, default: str) -> str:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return str(value)
    if not isinstance(value, str):
        return default
    stripped = value.strip()
    if not stripped:
        return default
    return stripped.replace("\n", " ").replace("\r", " ")


def _phase_p_mask(row: Mapping[str, Any]) -> list[bool]:
    raw = row.get("mask_")
    if raw is None:
        actions = row.get("actions")
        return [True for _ in list(actions or [])]
    return [bool(value) for value in list(raw)]


def _phase_p_target(row: Mapping[str, Any]) -> float:
    snapshot_target = _phase_p_snapshot_target(row)
    if snapshot_target is not None:
        return snapshot_target
    label = row.get("label") if isinstance(row.get("label"), Mapping) else {}
    for key in ("winDelta", "freshValueGap", "teacherScoreMargin", "valueGap", "relativeValue"):
        value = label.get(key)
        if value is not None:
            return float(value)
    preference = row.get("alternativePreferred")
    if preference is True:
        return 1.0
    if preference is False:
        return -1.0
    return 0.0


def _phase_p_snapshot_target(row: Mapping[str, Any]) -> float | None:
    label = row.get("freshCounterfactualLabel")
    if not isinstance(label, Mapping):
        return None
    value = label.get("freshValueGap")
    if value is None:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        value = metadata.get("freshValueGap")
    if value is None:
        return None
    try:
        gap = abs(float(value))
    except (TypeError, ValueError):
        return None
    preferred_slot = _optional_int(label.get("preferredSlot"))
    rejected_slot = _optional_int(label.get("rejectedSlot"))
    action_slot = _phase_p_row_action_slot(row)
    if action_slot is not None and rejected_slot is not None and int(action_slot) == int(rejected_slot):
        return -gap
    if action_slot is not None and preferred_slot is not None and int(action_slot) == int(preferred_slot):
        return gap
    return gap


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _phase_p_training_weight(row: Mapping[str, Any]) -> float:
    value = row.get("trainingWeight")
    if value is None or isinstance(value, bool):
        return 1.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(number) or number <= 0.0:
        return 1.0
    return number


def _phase_p_value_eval(rows: list[Mapping[str, Any]], weights: Mapping[str, float]) -> dict[str, Any]:
    if not rows:
        return {"rowCount": 0, "mse": None, "mae": None, "signAccuracy": None}
    squared = 0.0
    absolute = 0.0
    sign_total = 0
    sign_correct = 0
    for row in rows:
        target = _phase_p_target(row)
        prediction = sum(weights.get(name, 0.0) * value for name, value in _phase_p_features(row).items())
        error = prediction - target
        squared += error * error
        absolute += abs(error)
        if not math.isclose(target, 0.0, abs_tol=1e-9):
            sign_total += 1
            if (prediction >= 0.0 and target > 0.0) or (prediction < 0.0 and target < 0.0):
                sign_correct += 1
    return {
        "rowCount": len(rows),
        "mse": squared / len(rows),
        "mae": absolute / len(rows),
        "signAccuracy": (sign_correct / sign_total) if sign_total else None,
    }


def _phase_p_action_set_eval(rows: list[Mapping[str, Any]], weights: Mapping[str, float]) -> dict[str, Any]:
    scorer = PhasePActionValueScorer(weights={str(name): float(value) for name, value in weights.items()})
    pair_count = 0
    preferred_beats_rejected = 0
    preferred_top = 0
    rejected_top = 0
    other_top = 0
    preferred_at_k = {2: 0, 3: 0, 6: 0}
    margin_sum = 0.0
    skipped = Counter()
    for row in rows:
        label = row.get("freshCounterfactualLabel")
        if not isinstance(label, Mapping):
            skipped["missingFreshCounterfactualLabel"] += 1
            continue
        preferred_slot = _optional_int(label.get("preferredSlot"))
        rejected_slot = _optional_int(label.get("rejectedSlot"))
        if preferred_slot is None or rejected_slot is None or preferred_slot == rejected_slot:
            skipped["missingPairSlots"] += 1
            continue
        scores = scorer.score_row(row)
        if (
            preferred_slot < 0
            or rejected_slot < 0
            or preferred_slot >= len(scores)
            or rejected_slot >= len(scores)
            or scores[preferred_slot] is None
            or scores[rejected_slot] is None
        ):
            skipped["pairSlotNotScored"] += 1
            continue
        legal_scores = [(slot, score) for slot, score in enumerate(scores) if score is not None]
        if not legal_scores:
            skipped["noLegalScores"] += 1
            continue
        ranked_slots = [
            slot
            for slot, _score in sorted(
                legal_scores,
                key=lambda item: float(item[1]),
                reverse=True,
            )
        ]
        top_slot = ranked_slots[0]
        preferred_score = float(scores[preferred_slot] or 0.0)
        rejected_score = float(scores[rejected_slot] or 0.0)
        margin = preferred_score - rejected_score
        pair_count += 1
        margin_sum += margin
        for k in preferred_at_k:
            if preferred_slot in ranked_slots[: min(k, len(ranked_slots))]:
                preferred_at_k[k] += 1
        if margin > 0.0:
            preferred_beats_rejected += 1
        if top_slot == preferred_slot:
            preferred_top += 1
        elif top_slot == rejected_slot:
            rejected_top += 1
        else:
            other_top += 1
    return {
        "rowCount": len(rows),
        "pairCount": int(pair_count),
        "preferredBeatsRejected": int(preferred_beats_rejected),
        "preferredBeatsRejectedRate": _safe_ratio(preferred_beats_rejected, pair_count),
        "preferredTop": int(preferred_top),
        "preferredTopRate": _safe_ratio(preferred_top, pair_count),
        "rejectedTop": int(rejected_top),
        "rejectedTopRate": _safe_ratio(rejected_top, pair_count),
        "otherTop": int(other_top),
        "otherTopRate": _safe_ratio(other_top, pair_count),
        "preferredAt2": int(preferred_at_k[2]),
        "preferredAt2Rate": _safe_ratio(preferred_at_k[2], pair_count),
        "preferredAt3": int(preferred_at_k[3]),
        "preferredAt3Rate": _safe_ratio(preferred_at_k[3], pair_count),
        "preferredAt6": int(preferred_at_k[6]),
        "preferredAt6Rate": _safe_ratio(preferred_at_k[6], pair_count),
        "averagePreferredMinusRejected": _safe_ratio(margin_sum, pair_count),
        "skipped": {name: int(skipped[name]) for name in sorted(skipped)},
    }


def _phase_p_has_counterfactual_pair_rows(rows: list[Mapping[str, Any]]) -> bool:
    for row in rows:
        label = row.get("freshCounterfactualLabel")
        if not isinstance(label, Mapping):
            continue
        if _optional_int(label.get("preferredSlot")) is not None and _optional_int(label.get("rejectedSlot")) is not None:
            return True
    return False


def _phase_p_coverage(rows: list[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    counters = {
        "byDecisionKind": Counter(),
        "byDeckSource": Counter(),
        "byOpponentSuite": Counter(),
        "byDifficulty": Counter(),
        "byTrueTurnOrder": Counter(),
        "byTaskKind": Counter(),
    }
    for row in rows:
        counters["byDecisionKind"][str(row.get("decisionKind") or "unknown")] += 1
        counters["byDeckSource"][str(row.get("deckSource") or "unknown")] += 1
        counters["byOpponentSuite"][str(row.get("opponentSuite") or "unknown")] += 1
        counters["byDifficulty"][str(row.get("difficulty") or "unknown")] += 1
        counters["byTrueTurnOrder"][str(row.get("trueTurnOrder") or "unknown")] += 1
        counters["byTaskKind"][str(row.get("taskKind") or "unknown")] += 1
    return {
        key: {name: int(counter[name]) for name in sorted(counter)}
        for key, counter in counters.items()
    }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)
