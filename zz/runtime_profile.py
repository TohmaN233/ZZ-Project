from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable, Iterator


RUNTIME_PROFILE_BUCKET_FIELDS: dict[str, str] = {
    "total": "totalSeconds",
    "env": "envSeconds",
    "legal_actions": "legalActionsSeconds",
    "feature": "featureSeconds",
    "model": "modelSeconds",
    "mcts": "mctsSeconds",
    "transition_evaluator": "transitionEvaluatorSeconds",
    "clone_apply": "cloneApplySeconds",
}

RUNTIME_PROFILE_COUNTER_FIELDS = (
    "actions",
    "boundedMctsDecisions",
    "transitionEvaluatorCalls",
    "engineCloneCalls",
    "actionCopyCalls",
)

_COST_BUCKET_FIELDS = tuple(
    field_name
    for bucket, field_name in RUNTIME_PROFILE_BUCKET_FIELDS.items()
    if bucket != "total"
)


@dataclass
class RuntimeProfile:
    enabled: bool = True
    clock: Callable[[], float] = perf_counter
    _seconds: dict[str, float] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def span(self, bucket: str):
        if not self.enabled:
            return nullcontext()
        return _RuntimeProfileSpan(self, _normalise_bucket(bucket))

    def add_seconds(self, bucket: str, seconds: float) -> None:
        if not self.enabled:
            return
        bucket = _normalise_bucket(bucket)
        self._seconds[bucket] = float(self._seconds.get(bucket, 0.0) or 0.0) + max(0.0, float(seconds))

    def increment(self, counter: str, amount: int = 1) -> None:
        if not self.enabled:
            return
        key = str(counter)
        self._counters[key] = int(self._counters.get(key, 0) or 0) + int(amount)

    def merge(self, other: "RuntimeProfile | dict[str, object]") -> None:
        if not self.enabled:
            return
        report = other.to_report() if isinstance(other, RuntimeProfile) else dict(other)
        for bucket, field_name in RUNTIME_PROFILE_BUCKET_FIELDS.items():
            self.add_seconds(bucket, _float(report.get(field_name)))
        for counter in RUNTIME_PROFILE_COUNTER_FIELDS:
            self.increment(counter, int(_float(report.get(counter))))

    def to_report(self, *, timeouts: int = 0, errors: int = 0) -> dict[str, object]:
        report: dict[str, object] = {"enabled": bool(self.enabled)}
        if not self.enabled:
            for field_name in RUNTIME_PROFILE_BUCKET_FIELDS.values():
                report[field_name] = 0.0
            for counter in RUNTIME_PROFILE_COUNTER_FIELDS:
                report[counter] = 0
            report.update({
                "sps": 0.0,
                "timeouts": 0,
                "errors": 0,
                "highestCostBucket": None,
            })
            return report

        for bucket, field_name in RUNTIME_PROFILE_BUCKET_FIELDS.items():
            report[field_name] = round(float(self._seconds.get(bucket, 0.0) or 0.0), 6)
        if not report["totalSeconds"]:
            report["totalSeconds"] = round(
                sum(float(self._seconds.get(bucket, 0.0) or 0.0) for bucket in self._seconds),
                6,
            )
        for counter in RUNTIME_PROFILE_COUNTER_FIELDS:
            report[counter] = int(self._counters.get(counter, 0) or 0)
        report["timeouts"] = int(timeouts)
        report["errors"] = int(errors)
        total_seconds = float(report["totalSeconds"] or 0.0)
        actions = int(report["actions"] or 0)
        report["sps"] = round(actions / total_seconds, 6) if total_seconds > 0.0 else 0.0
        report["highestCostBucket"] = _highest_cost_bucket(report)
        return report


class _RuntimeProfileSpan:
    def __init__(self, profile: RuntimeProfile, bucket: str) -> None:
        self.profile = profile
        self.bucket = bucket
        self.started_at = 0.0

    def __enter__(self) -> "_RuntimeProfileSpan":
        self.started_at = float(self.profile.clock())
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        ended_at = float(self.profile.clock())
        self.profile.add_seconds(self.bucket, ended_at - self.started_at)


def _normalise_bucket(bucket: str) -> str:
    key = str(bucket).strip().lower().replace("-", "_")
    aliases = {
        "legal": "legal_actions",
        "legalactions": "legal_actions",
        "features": "feature",
        "mcts_planner": "mcts",
        "bounded_mcts": "mcts",
        "transition": "transition_evaluator",
        "transitionevaluator": "transition_evaluator",
        "clone": "clone_apply",
        "apply": "clone_apply",
    }
    return aliases.get(key, key)


def _highest_cost_bucket(report: dict[str, object]) -> str | None:
    best_field = None
    best_value = 0.0
    for field_name in _COST_BUCKET_FIELDS:
        value = _float(report.get(field_name))
        if best_field is None or value > best_value:
            best_field = field_name
            best_value = value
    return best_field if best_value > 0.0 else None


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
