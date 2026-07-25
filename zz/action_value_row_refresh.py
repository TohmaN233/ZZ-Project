from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from zz.action_value_group_key import action_value_action_set_identity
from zz.action_set_teacher_rebuild import refresh_action_set_row_semantic_features


ACTION_VALUE_SEMANTIC_REFRESH_VERSION = "action_value_semantic_refresh_v1"


def refresh_action_value_training_row_semantics(
    row: Mapping[str, Any],
    *,
    source_label: str = "",
    record_metadata: bool = True,
    track_changes: bool = True,
    semantic_cache: dict[tuple[Any, ...], tuple[dict[str, Any], dict[str, bool]]] | None = None,
) -> tuple[dict[str, Any], dict[str, bool]]:
    """Refresh tensors for an action-value training row using the current action schema.

    Action-value rows can outlive feature-schema bug fixes. This helper is the single
    path for rebuilding row-local semantic tensors while preserving labels, branch
    outcomes, and training safety fields.
    """

    cache_key = _semantic_cache_key(row) if semantic_cache is not None else None
    if cache_key is not None and semantic_cache is not None and cache_key in semantic_cache:
        fields, changed = semantic_cache[cache_key]
        refreshed = dict(row)
        _apply_semantic_fields(refreshed, fields)
        if record_metadata and (not track_changes or any(changed.values())):
            _annotate_refresh_metadata(
                refreshed,
                source_label=source_label,
                changed=changed,
            )
        return refreshed, dict(changed)

    refreshed = dict(row)
    before = _row_semantic_snapshot(refreshed) if track_changes else {}
    refresh_action_set_row_semantic_features(refreshed, force_action_semantics=True)
    after = _row_semantic_snapshot(refreshed) if track_changes else {}
    changed = {
        "actionFeatures": bool(track_changes and before.get("action") != after.get("action")),
        "globalFeatures": bool(track_changes and before.get("global") != after.get("global")),
        "cardFeatures": bool(track_changes and before.get("card") != after.get("card")),
    }
    if record_metadata and (not track_changes or any(changed.values())):
        _annotate_refresh_metadata(refreshed, source_label=source_label, changed=changed)
    if cache_key is not None and semantic_cache is not None:
        semantic_cache[cache_key] = (_semantic_fields(refreshed), dict(changed))
    return refreshed, changed


def refresh_action_value_training_rows_semantics(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_label: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counters: Counter[str] = Counter()
    by_decision: dict[str, Counter[str]] = {}
    semantic_cache: dict[tuple[Any, ...], tuple[dict[str, Any], dict[str, bool]]] = {}
    refreshed_rows: list[dict[str, Any]] = []
    for row in rows:
        refreshed, changed = refresh_action_value_training_row_semantics(
            row,
            source_label=source_label,
            record_metadata=True,
            track_changes=True,
            semantic_cache=semantic_cache,
        )
        refreshed_rows.append(refreshed)
        decision = str(refreshed.get("decisionKind") or "unknown")
        decision_counts = by_decision.setdefault(decision, Counter())
        any_changed = False
        for report_key, changed_key in (
            ("changedActionFeatureRows", "actionFeatures"),
            ("changedGlobalFeatureRows", "globalFeatures"),
            ("changedCardFeatureRows", "cardFeatures"),
        ):
            if bool(changed.get(changed_key)):
                counters[report_key] += 1
                decision_counts[report_key] += 1
                any_changed = True
        if not any_changed:
            counters["unchangedRows"] += 1
            decision_counts["unchangedRows"] += 1
        decision_counts["rows"] += 1
    report = {
        "kind": ACTION_VALUE_SEMANTIC_REFRESH_VERSION,
        "sourceLabel": str(source_label),
        "inputRows": int(len(refreshed_rows)),
        "outputRows": int(len(refreshed_rows)),
        "changedActionFeatureRows": int(counters.get("changedActionFeatureRows", 0)),
        "changedGlobalFeatureRows": int(counters.get("changedGlobalFeatureRows", 0)),
        "changedCardFeatureRows": int(counters.get("changedCardFeatureRows", 0)),
        "unchangedRows": int(counters.get("unchangedRows", 0)),
        "cacheEntries": int(len(semantic_cache)),
        "byDecisionKind": {
            decision: dict(sorted((key, int(value)) for key, value in values.items()))
            for decision, values in sorted(by_decision.items())
        },
    }
    return refreshed_rows, report


def _row_semantic_snapshot(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "action": _stable_json(
            {
                "actionFeatureNames": row.get("actionFeatureNames"),
                "actions_": row.get("actions_"),
            }
        ),
        "global": _stable_json(
            {
                "globalFeatureNames": row.get("globalFeatureNames"),
                "global_": row.get("global_"),
            }
        ),
        "card": _stable_json(
            {
                "cardFeatureNames": row.get("cardFeatureNames"),
                "cards_": row.get("cards_"),
            }
        ),
    }


def _semantic_cache_key(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    label = row.get("label") if isinstance(row.get("label"), Mapping) else {}
    group_id = (
        metadata.get("fullLegalActionSetGroupId")
        or label.get("fullLegalActionSetGroupId")
        or ""
    )
    state_key = str(row.get("stateKey") or "")
    decision_kind = str(row.get("decisionKind") or "unknown")
    legal_count = int(row.get("legalCount") or 0)
    run_id = str(row.get("runId") or row.get("sourceLabelRunId") or metadata.get("sourceRunId") or "")
    action_identity = action_value_action_set_identity(row)
    if group_id:
        return (
            "full_legal_group",
            str(group_id),
            run_id,
            state_key,
            decision_kind,
            legal_count,
            action_identity,
        )
    if not state_key:
        return None
    return (
        "action_set",
        run_id,
        state_key,
        decision_kind,
        legal_count,
        action_identity,
    )


def _semantic_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in (
        "globalFeatureNames",
        "global_",
        "actionFeatureNames",
        "actions_",
        "cardFeatureNames",
        "cards_",
    ):
        if key in row:
            fields[key] = row.get(key)
    return fields


def _apply_semantic_fields(row: dict[str, Any], fields: Mapping[str, Any]) -> None:
    for key, value in fields.items():
        row[key] = value


def _annotate_refresh_metadata(
    row: dict[str, Any],
    *,
    source_label: str,
    changed: Mapping[str, bool],
) -> None:
    metadata = dict(row.get("metadata") or {})
    metadata["actionValueSemanticRefresh"] = {
        "kind": ACTION_VALUE_SEMANTIC_REFRESH_VERSION,
        "createdAt": _utc_now(),
        "sourceLabel": str(source_label or ""),
        "changedActionFeatures": bool(changed.get("actionFeatures")),
        "changedGlobalFeatures": bool(changed.get("globalFeatures")),
        "changedCardFeatures": bool(changed.get("cardFeatures")),
    }
    row["metadata"] = metadata


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
