from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


RUNTIME_TOTAL_TEACHER_SCORE_MODES = frozenset({"runtime_total", "aux_runtime_total"})
RUNTIME_TOTAL_SCORE_PROVENANCE_KIND = "runtime_total_score_provenance_v1"


@dataclass(frozen=True)
class RuntimeTotalScoreProvenance:
    scoreMode: str
    runtimePolicyId: str
    runtimeActorSide: str
    actorPolicyId: str
    subjectPolicyId: str


def row_runtime_total_scores(
    row: Mapping[str, Any],
    *,
    require_explicit_mode: bool = False,
    require_policy_provenance: bool = False,
) -> list[float | None] | None:
    """Return recorded runtime-total scores; strict callers can require explicit mode/provenance."""
    if row_runtime_total_rejection_reason(
        row,
        require_explicit_mode=require_explicit_mode,
        require_policy_provenance=require_policy_provenance,
    ) is not None:
        return None
    mode = _teacher_score_mode(row)
    if mode not in RUNTIME_TOTAL_TEACHER_SCORE_MODES:
        return _snapshot_runtime_total_teacher_scores(row)
    for key in ("teacherScores", "rawScores"):
        scores = _score_array(row.get(key))
        if scores is not None:
            return scores
    return None


def runtime_total_score_source(
    row: Mapping[str, Any],
    *,
    require_explicit_mode: bool = False,
    require_policy_provenance: bool = False,
) -> str | None:
    return (
        "row_runtime_total"
        if row_runtime_total_scores(
            row,
            require_explicit_mode=require_explicit_mode,
            require_policy_provenance=require_policy_provenance,
        )
        is not None
        else None
    )


def runtime_total_score_provenance_metadata(row: Mapping[str, Any]) -> dict[str, Any] | None:
    provenance, reason = runtime_total_score_provenance(row, require_policy_provenance=True)
    if reason is not None or provenance is None:
        return None
    return {
        "kind": RUNTIME_TOTAL_SCORE_PROVENANCE_KIND,
        "scoreMode": provenance.scoreMode,
        "runtimePolicyId": provenance.runtimePolicyId,
        "runtimeActorSide": provenance.runtimeActorSide,
        "actorPolicyId": provenance.actorPolicyId,
        "subjectPolicyId": provenance.subjectPolicyId,
    }


def row_runtime_total_rejection_reason(
    row: Mapping[str, Any],
    *,
    require_explicit_mode: bool = False,
    require_policy_provenance: bool = False,
) -> str | None:
    mode = _teacher_score_mode(row)
    if mode not in RUNTIME_TOTAL_TEACHER_SCORE_MODES:
        if require_explicit_mode:
            return "missing_explicit_runtime_total_mode"
        if _snapshot_runtime_total_teacher_scores(row) is None:
            return "missing_row_runtime_total"
    else:
        has_scores = any(_score_array(row.get(key)) is not None for key in ("teacherScores", "rawScores"))
        if not has_scores:
            return "missing_row_runtime_total"
    provenance, reason = runtime_total_score_provenance(
        row,
        require_policy_provenance=require_policy_provenance,
    )
    if reason is not None:
        return reason
    if provenance is not None and provenance.subjectPolicyId:
        if provenance.runtimePolicyId != provenance.subjectPolicyId:
            return "runtime_total_subject_policy_mismatch"
    return None


def runtime_total_score_provenance(
    row: Mapping[str, Any],
    *,
    require_policy_provenance: bool = False,
) -> tuple[RuntimeTotalScoreProvenance | None, str | None]:
    runtime_policy_id = _runtime_policy_id(row)
    actor_side = _actor_side(row)
    actor_policy_id = _actor_policy_id(row, actor_side)
    subject_policy_id = _subject_policy_id(row)
    if require_policy_provenance:
        if not runtime_policy_id:
            return None, "missing_runtime_policy_id"
        if actor_side not in {"P1", "P2"}:
            return None, "missing_runtime_model_side"
        if not actor_policy_id:
            return None, "missing_runtime_actor_policy_id"
    if runtime_policy_id and actor_policy_id and actor_policy_id != runtime_policy_id:
        return None, "runtime_total_policy_mismatch"
    return (
        RuntimeTotalScoreProvenance(
            scoreMode=_teacher_score_mode(row),
            runtimePolicyId=runtime_policy_id,
            runtimeActorSide=actor_side,
            actorPolicyId=actor_policy_id,
            subjectPolicyId=subject_policy_id,
        ),
        None,
    )


def _teacher_score_mode(row: Mapping[str, Any]) -> str:
    for provenance in _score_provenance_sources(row):
        value = provenance.get("scoreMode")
        if value:
            return str(value).strip()
    metadata = row.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("teacherScoreMode")
        if value:
            return str(value).strip()
    value = row.get("teacherScoreMode")
    return str(value).strip() if value else ""


def _runtime_total_policy_mismatch(row: Mapping[str, Any]) -> bool:
    expected_policy_id = _runtime_policy_id(row)
    actor_side = _actor_side(row)
    actor_policy_id = _actor_policy_id(row, actor_side)
    return bool(expected_policy_id and actor_policy_id and actor_policy_id != expected_policy_id)


def _runtime_policy_id(row: Mapping[str, Any]) -> str:
    for provenance in _score_provenance_sources(row):
        value = provenance.get("runtimePolicyId")
        if value:
            return str(value)
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        value = source.get("runtimePolicyId") or source.get("policyId")
        if value:
            return str(value)
    return ""


def _subject_policy_id(row: Mapping[str, Any]) -> str:
    for provenance in _score_provenance_sources(row):
        value = provenance.get("subjectPolicyId")
        if value:
            return str(value)
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        value = source.get("subjectPolicyId")
        if value:
            return str(value)
    return ""


def _actor_side(row: Mapping[str, Any]) -> str:
    for provenance in _score_provenance_sources(row):
        value = str(provenance.get("runtimeActorSide") or "").strip().upper()
        if value in {"P1", "P2"}:
            return value
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        value = str(source.get("runtimeActorSide") or "").strip().upper()
        if value in {"P1", "P2"}:
            return value
    for source in (row, _mapping(row.get("metadata")), _mapping(row.get("sourceContext"))):
        value = str(source.get("modelSide") or "").strip().upper()
        if value in {"P1", "P2"}:
            return value
    return ""


def _actor_policy_id(row: Mapping[str, Any], actor_side: str) -> str:
    for provenance in _score_provenance_sources(row):
        value = provenance.get("actorPolicyId")
        if value:
            return str(value)
    if actor_side not in {"P1", "P2"}:
        return ""
    key = f"{actor_side.lower()}PolicyId"
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        value = source.get(key)
        if value:
            return str(value)
    return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _score_provenance_sources(row: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    out: list[Mapping[str, Any]] = []
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        for key in ("scoreProvenance", "runtimeTotalScoreProvenance"):
            provenance = source.get(key)
            if isinstance(provenance, Mapping):
                out.append(provenance)
    return tuple(out)


def _snapshot_runtime_total_teacher_scores(row: Mapping[str, Any]) -> list[float | None] | None:
    if str(row.get("teacherId") or "") != "snapshot_branch_rollout":
        return None
    scores = _score_array(row.get("teacherScores"))
    if scores is None:
        return None
    return scores


def _score_array(value: Any) -> list[float | None] | None:
    if not isinstance(value, list | tuple) or not value:
        return None
    out: list[float | None] = []
    finite_count = 0
    for item in value:
        if item is None:
            out.append(None)
            continue
        try:
            score = float(item)
        except (TypeError, ValueError):
            out.append(None)
            continue
        if not math.isfinite(score):
            out.append(None)
            continue
        finite_count += 1
        out.append(float(score))
    return out if finite_count else None
