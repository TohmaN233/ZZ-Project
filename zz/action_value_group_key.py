from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def action_value_state_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    cached = _cached_training_group_key(row)
    if cached is not None:
        return cached
    return (
        str(row.get("runId") or row.get("sourceLabelRunId") or "unknown-run"),
        str(row.get("stateKey") or "unknown-state"),
        str(row.get("decisionKind") or "unknown"),
        action_value_action_set_identity(row),
    )


def action_value_group_identity_rejection_reason(row: Mapping[str, Any]) -> str | None:
    group_ids = _full_legal_group_ids(row)
    return "mismatched_full_legal_action_set_group_id" if len(group_ids) > 1 else None


def action_value_action_set_identity(row: Mapping[str, Any]) -> str:
    group_ids = _full_legal_group_ids(row)
    digest = _action_set_digest(row)
    if group_ids:
        return f"full-legal-group:{sorted(group_ids)[0]}|{digest}"
    return digest


def canonical_action_identity(action: Any, *, include_action_key: bool = True) -> str:
    if not isinstance(action, Mapping):
        return _stable_json(action)
    signature = action.get("signature")
    if isinstance(signature, Mapping):
        return _stable_json({"signature": dict(signature)})
    payload = action.get("payload") if isinstance(action.get("payload"), Mapping) else {}
    data: dict[str, Any] = {
        "kind": str(action.get("kind") or ""),
        "payload": dict(payload),
    }
    action_key = action.get("actionKey") or action.get("key")
    if include_action_key and action_key is not None:
        data["actionKey"] = str(action_key)
    return _stable_json(data)


def _action_set_digest(row: Mapping[str, Any]) -> str:
    compact_actions = _compact_actions(row.get("actions"))
    compact_action_records = _compact_actions(row.get("actionRecords"))
    semantic_actions = compact_actions if compact_actions is not None else compact_action_records
    payload = {
        "legalCount": row.get("legalCount"),
        "mask_": row.get("mask_"),
        "actionKeys": None if semantic_actions is not None else row.get("actionKeys") or row.get("action_keys"),
        "actionFeatureNames": row.get("actionFeatureNames"),
        "actions_": row.get("actions_"),
        "actions": compact_actions,
        "actionRecords": compact_action_records,
    }
    encoded = _stable_json(payload)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"action-set:{digest}"


def _full_legal_group_ids(row: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for source in (row, _mapping(row.get("metadata")), _mapping(row.get("label")), _mapping(row.get("sourceContext"))):
        value = source.get("fullLegalActionSetGroupId")
        if value is not None and str(value).strip():
            out.add(str(value).strip())
    return out


def _compact_actions(value: Any) -> Any:
    if not isinstance(value, list | tuple):
        return None
    return [canonical_action_identity(item) for item in value]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _cached_training_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    metadata = _mapping(row.get("metadata"))
    value = metadata.get("_sqliteTrainingGroupKey")
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    parts = tuple(str(part) for part in value)
    if any(not part for part in parts):
        return None
    return parts


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
