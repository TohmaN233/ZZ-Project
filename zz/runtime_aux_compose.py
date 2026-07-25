from __future__ import annotations

from typing import Any


BOUNDED_RUNTIME_AUX_OBJECTIVES = frozenset(
    {
        "bounded_base_wrong_preserve_correct",
        "trajectory_advantage_runtime_residual",
    }
)
DEFAULT_BOUNDED_RUNTIME_AUX_MAX_CORRECTION = 0.75


def is_bounded_runtime_aux_objective(objective: Any) -> bool:
    return str(objective or "").strip() in BOUNDED_RUNTIME_AUX_OBJECTIVES


def runtime_aux_max_correction_for_objective(objective: Any) -> float | None:
    if is_bounded_runtime_aux_objective(objective):
        return DEFAULT_BOUNDED_RUNTIME_AUX_MAX_CORRECTION
    return None


def runtime_aux_max_correction_for_scorer(scorer: Any) -> float | None:
    return _runtime_aux_max_correction_for_scorer(scorer, seen=set())


def _runtime_aux_max_correction_for_scorer(scorer: Any, *, seen: set[int]) -> float | None:
    if scorer is None:
        return None
    identity = id(scorer)
    if identity in seen:
        return None
    seen.add(identity)
    direct = runtime_aux_max_correction_for_objective(getattr(scorer, "runtimeAuxTrainingObjective", None))
    if direct is not None:
        return direct
    nested_scorers: list[Any] = []
    for attr in ("baseScorer", "deltaScorer", "defaultScorer"):
        nested = getattr(scorer, attr, None)
        if nested is not None:
            nested_scorers.append(nested)
    routes = getattr(scorer, "routes", None)
    if isinstance(routes, dict):
        nested_scorers.extend(routes.values())
    for nested in nested_scorers:
        correction = _runtime_aux_max_correction_for_scorer(nested, seen=seen)
        if correction is not None:
            return correction
    return None


def runtime_aux_pairwise_correction_limit(max_correction: float) -> float:
    return 2.0 * float(max_correction)


def clamp_runtime_aux_residual(
    aux_score: Any,
    *,
    weight: float,
    max_correction: float | None,
) -> float | None:
    if aux_score is None:
        return None
    residual = float(weight) * float(aux_score)
    if max_correction is None:
        return residual
    cap = abs(float(max_correction))
    return max(-cap, min(cap, residual))


def compose_runtime_aux_score(
    base_score: Any,
    aux_score: Any,
    *,
    weight: float,
    max_correction: float | None,
) -> float | None:
    if base_score is None:
        return None
    residual = clamp_runtime_aux_residual(aux_score, weight=weight, max_correction=max_correction)
    if residual is None:
        return None
    return float(base_score) + residual
