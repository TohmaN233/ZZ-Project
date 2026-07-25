from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING = 0.03
DEFAULT_COBEST_EPSILON = DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING
HIGH_NOOP_RISK_RAW_SCORE_NEEDED_THRESHOLD = 5.0
DEFAULT_YGO_UPDATE_EPOCHS = 1


def runtime_top_slot(scores: Sequence[Any], slots: Sequence[int]) -> int | None:
    valid_slots = [
        int(slot)
        for slot in slots
        if 0 <= int(slot) < len(scores) and _finite_float(scores[int(slot)]) is not None
    ]
    if not valid_slots:
        return None
    return max(valid_slots, key=lambda slot: (float(scores[slot]), -slot))


def runtime_top_slot_and_margin(scores: Sequence[Any], slots: Sequence[int]) -> tuple[int | None, float | None]:
    valid_slots = [
        int(slot)
        for slot in slots
        if 0 <= int(slot) < len(scores) and _finite_float(scores[int(slot)]) is not None
    ]
    if not valid_slots:
        return None, None
    ranked = sorted(valid_slots, key=lambda slot: (float(scores[slot]), -slot), reverse=True)
    top = int(ranked[0])
    if len(ranked) < 2:
        return top, 0.0
    return top, float(scores[ranked[0]]) - float(scores[ranked[1]])


def value_spread(values: Sequence[Any]) -> float | None:
    finite_values = [_finite_float(value) for value in values]
    finite = [float(value) for value in finite_values if value is not None]
    if not finite:
        return None
    return max(finite) - min(finite)


def value_spread_is_trainable(
    values: Sequence[Any],
    *,
    min_gap: float = DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
) -> bool:
    spread = value_spread(values)
    return spread is not None and float(spread) >= float(min_gap)


def best_value_slots(
    known_values: Mapping[int, float],
    *,
    candidate_slots: Sequence[int],
    epsilon: float = DEFAULT_COBEST_EPSILON,
) -> set[int]:
    values = {
        int(slot): float(known_values[int(slot)])
        for slot in candidate_slots
        if int(slot) in known_values and _finite_float(known_values[int(slot)]) is not None
    }
    if not values:
        return set()
    best = max(values.values())
    return {
        int(slot)
        for slot, value in values.items()
        if abs(float(value) - float(best)) <= float(epsilon)
    }


def resolve_runtime_aux_output_scale(runtime_aux_output_scale: Any, *, runtime_aux_score_weight: Any) -> float:
    if runtime_aux_output_scale is None:
        weight = _finite_float(runtime_aux_score_weight)
        if weight is not None and float(weight) > 0.0:
            return 1.0 / float(weight)
        return 1.0
    scale = _finite_float(runtime_aux_output_scale)
    if scale is None or float(scale) <= 0.0:
        return 1.0
    return float(scale)


def runtime_aux_scale_diagnostics(
    *,
    runtime_aux_score_weight: Any,
    runtime_aux_output_scale: Any,
    max_correction: float | None,
) -> dict[str, float | bool | None]:
    weight = _finite_float(runtime_aux_score_weight)
    scale = _finite_float(runtime_aux_output_scale)
    effective = None if weight is None or scale is None else float(weight) * float(scale)
    raw_needed = None
    if max_correction is not None and effective is not None and abs(float(effective)) > 1.0e-12:
        raw_needed = abs(float(max_correction)) / abs(float(effective))
    high_noop = (
        raw_needed is not None
        and float(raw_needed) > float(HIGH_NOOP_RISK_RAW_SCORE_NEEDED_THRESHOLD)
    )
    return {
        "effectiveResidualWeight": float(effective) if effective is not None else None,
        "rawScoreNeededForMaxCorrection": float(raw_needed) if raw_needed is not None else None,
        "highNoopRiskRawScoreNeededThreshold": float(HIGH_NOOP_RISK_RAW_SCORE_NEEDED_THRESHOLD),
        "highNoopRisk": bool(high_noop),
    }


def validate_action_set_scorer_shape(scorer: Any, *, context: str = "action-set scorer") -> None:
    """Fail fast for malformed launch scorers instead of letting runtime fall back silently."""
    _validate_action_set_scorer_shape(scorer, context=context, seen=set())


def _validate_action_set_scorer_shape(scorer: Any, *, context: str, seen: set[int]) -> None:
    if scorer is None:
        return
    identity = id(scorer)
    if identity in seen:
        return
    seen.add(identity)

    validate_shape = getattr(scorer, "validate_shape", None)
    if callable(validate_shape):
        try:
            validate_shape()
        except Exception as exc:
            raise ValueError(f"{context} shape validation failed: {exc}") from exc
    elif all(hasattr(scorer, name) for name in ("inputDim", "hiddenDim", "w1", "b1", "w2")):
        _validate_mlp_shape(scorer, context=context)

    for attr in ("firstScorer", "secondScorer", "baseScorer", "deltaScorer", "defaultScorer"):
        nested = getattr(scorer, attr, None)
        if nested is not None:
            _validate_action_set_scorer_shape(nested, context=f"{context}.{attr}", seen=seen)
    routes = getattr(scorer, "routes", None)
    if isinstance(routes, Mapping):
        for route, nested in routes.items():
            _validate_action_set_scorer_shape(nested, context=f"{context}.routes[{route!r}]", seen=seen)


def _validate_mlp_shape(scorer: Any, *, context: str) -> None:
    input_dim = int(getattr(scorer, "inputDim"))
    hidden_dim = int(getattr(scorer, "hiddenDim"))
    if input_dim < 0:
        raise ValueError(f"{context} inputDim must be non-negative: {input_dim}")
    if hidden_dim < 0:
        raise ValueError(f"{context} hiddenDim must be non-negative: {hidden_dim}")
    w1 = list(getattr(scorer, "w1") or [])
    b1 = list(getattr(scorer, "b1") or [])
    w2 = list(getattr(scorer, "w2") or [])
    if len(w1) != hidden_dim:
        raise ValueError(f"{context} w1 shape mismatch: expected {hidden_dim} rows, got {len(w1)}")
    for index, row in enumerate(w1):
        if len(list(row)) != input_dim:
            raise ValueError(f"{context} w1 shape mismatch at row {index}: expected {input_dim}, got {len(list(row))}")
    if len(b1) != hidden_dim:
        raise ValueError(f"{context} b1 shape mismatch: expected {hidden_dim}, got {len(b1)}")
    if len(w2) != hidden_dim:
        raise ValueError(f"{context} w2 shape mismatch: expected {hidden_dim}, got {len(w2)}")


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed
