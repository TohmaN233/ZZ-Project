from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zz.action_value_group_key import canonical_action_identity
from zz.action_set_runtime_scores import runtime_total_score_provenance


@dataclass(frozen=True)
class CurrentPolicySelection:
    slot: int
    action_identity: str
    policy_id: str
    logit: float


def masked_argmax_action(
    *,
    logits: Sequence[float],
    legal_mask: Sequence[bool],
    action_identities: Sequence[str],
    policy_id: str,
) -> CurrentPolicySelection:
    if not str(policy_id or "").strip():
        raise ValueError("current policy selection requires policy_id")
    if len(logits) != len(legal_mask) or len(logits) != len(action_identities):
        raise ValueError("logits, legal_mask, and action_identities must have the same length")
    legal_slots = [index for index, enabled in enumerate(legal_mask) if bool(enabled)]
    if not legal_slots:
        raise ValueError("current policy selection requires at least one legal action")
    non_finite_slots = [
        index for index in legal_slots if not math.isfinite(float(logits[index]))
    ]
    if non_finite_slots:
        raise ValueError(
            "current policy selection has non-finite legal logits: "
            + ",".join(str(index) for index in non_finite_slots)
        )
    slot = max(legal_slots, key=lambda index: float(logits[index]))
    return CurrentPolicySelection(
        slot=int(slot),
        action_identity=str(action_identities[slot]),
        policy_id=str(policy_id),
        logit=float(logits[slot]),
    )


def select_current_policy_top(row: Mapping[str, Any]) -> CurrentPolicySelection:
    validated = validate_current_policy_row(row)
    return masked_argmax_action(
        logits=validated["actorLogits"],
        legal_mask=validated["legalMask"],
        action_identities=validated["actionIdentities"],
        policy_id=validated["actorPolicyId"],
    )


def actor_logits_from_runtime_scores(
    row: Mapping[str, Any],
    scores: Sequence[Any],
) -> list[float]:
    """Convert model scores to actor logits with the same fail-closed runtime contract."""

    actions = list(row.get("actions") or [])
    mask_source = row.get("legalMask") if "legalMask" in row else row.get("mask_")
    legal_mask = list(mask_source or [])
    if len(legal_mask) != len(actions):
        raise ValueError("legalMask and actions must have the same length")
    if len(scores) != len(actions):
        raise ValueError("score count must exactly match action count")
    actor_logits: list[float] = []
    for slot, score in enumerate(scores):
        legal = bool(legal_mask[slot])
        if score is None:
            if legal:
                raise ValueError("missing legal score")
            actor_logits.append(-1.0e9)
            continue
        try:
            value = float(score)
        except (TypeError, ValueError) as exc:
            raise ValueError("non-numeric score") from exc
        if not math.isfinite(value):
            raise ValueError("non-finite score")
        actor_logits.append(value)
    return actor_logits


def actor_rollout_provenance_rejection_reason(row: Mapping[str, Any]) -> str | None:
    metadata = _mapping(row.get("metadata"))
    actor_action_slot = _optional_int(row.get("actorActionSlot", metadata.get("actorActionSlot")))
    actor_action_identity = str(row.get("actorActionIdentity") or metadata.get("actorActionIdentity") or "").strip()
    actor_top_slot = _optional_int(row.get("actorTopSlot", metadata.get("actorTopSlot")))
    actor_top_identity = str(row.get("actorTopActionIdentity") or metadata.get("actorTopActionIdentity") or "").strip()
    if actor_action_slot is None:
        return "missing_actor_action_slot"
    if not actor_action_identity:
        return "missing_actor_action_identity"
    if actor_top_slot is None:
        return "missing_actor_top_slot"
    if not actor_top_identity:
        return "missing_actor_top_action_identity"
    try:
        validated = validate_current_policy_row(row)
        top_selection = select_current_policy_top(row)
    except ValueError:
        return "invalid_current_policy_row"
    action_identities = list(validated["actionIdentities"])
    legal_mask = list(validated["legalMask"])
    if int(actor_action_slot) < 0 or int(actor_action_slot) >= len(action_identities):
        return "actor_action_slot_out_of_range"
    if not bool(legal_mask[int(actor_action_slot)]):
        return "actor_action_slot_not_legal"
    if actor_action_identity != str(action_identities[int(actor_action_slot)]):
        return "actor_action_identity_mismatch"
    if int(actor_top_slot) != int(top_selection.slot):
        return "actor_top_slot_mismatch"
    if actor_top_identity != str(top_selection.action_identity):
        return "actor_top_action_identity_mismatch"
    if int(actor_action_slot) != int(top_selection.slot):
        if not _actor_selection_mode_allows_non_top(row):
            return "actor_action_slot_not_top"
        temperature = _actor_sampling_temperature(row)
        if temperature is None:
            return "missing_actor_sampling_temperature"
        if temperature <= 0.0:
            return "invalid_actor_sampling_temperature"
        if _actor_sampling_log_prob(row) is None:
            return "missing_actor_action_log_prob"
    return None


def actor_score_provenance_rejection_reason(
    row: Mapping[str, Any],
    *,
    expected_actor_policy_id: str | None = None,
) -> str | None:
    """Require current-policy actor logits/scores to be traceable to the same actor."""

    expected = str(expected_actor_policy_id or _row_actor_policy_id(row) or "").strip()
    if not expected:
        return "missing_expected_actor_policy_id"
    score_mode_reason = score_mode_consistency_rejection_reason(row)
    if score_mode_reason is not None:
        return score_mode_reason
    mode = _teacher_score_mode(row)
    if mode == "runtime_total":
        provenance, reason = runtime_total_score_provenance(row, require_policy_provenance=True)
        if reason is not None:
            return f"runtime_total_score_provenance_{reason}"
        if provenance is None:
            return "runtime_total_score_provenance_missing"
        if provenance.runtimePolicyId != expected or provenance.actorPolicyId != expected:
            return "runtime_total_actor_policy_mismatch"
        if provenance.subjectPolicyId and provenance.subjectPolicyId != expected:
            return "runtime_total_subject_policy_mismatch"
        return None
    if mode == "direct_action_set_scorer":
        return _direct_action_set_actor_score_provenance_rejection_reason(row, expected_actor_policy_id=expected)
    return "stale_teacher_score_mode"


def actor_policy_metadata_rejection_reason(
    row: Mapping[str, Any],
    *,
    expected_actor_policy_id: str | None = None,
    expected_candidate_policy_id: str | None = None,
) -> str | None:
    expected = str(expected_actor_policy_id or _row_actor_policy_id(row) or "").strip()
    if not expected:
        return "missing_expected_actor_policy_id"
    source_actor, source_conflict = _consistent_source_value(
        row,
        "sourceActorPolicyId",
        "currentPolicySourceActorPolicyId",
    )
    if source_conflict:
        return "source_actor_policy_id_conflict"
    if not source_actor:
        return "missing_source_actor_policy_id"
    if source_actor != expected:
        return "source_actor_policy_id_mismatch"
    candidate_id, candidate_conflict = _consistent_source_value(
        row,
        "runtimeCandidatePolicyId",
        "currentPolicyCandidatePolicyId",
    )
    if candidate_conflict:
        return "runtime_candidate_policy_id_conflict"
    if not candidate_id:
        return "missing_runtime_candidate_policy_id"
    expected_candidate = str(
        expected_candidate_policy_id if expected_candidate_policy_id is not None else expected
    ).strip()
    if expected_candidate and candidate_id != expected_candidate:
        return "runtime_candidate_policy_id_mismatch"
    return None


def validate_current_policy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(row.get("metadata"))
    actor_policy_id_conflict = current_policy_id_container_conflict_rejection_reason(row)
    if actor_policy_id_conflict is not None:
        raise ValueError(actor_policy_id_conflict)
    actor_policy_id, _ = _consistent_source_value(row, "actorPolicyId")
    if not actor_policy_id:
        raise ValueError("current policy row is missing actorPolicyId")
    missing = [key for key in ("decisionKind", "actions", "actionRecords") if key not in row]
    if "actorLogits" not in row and "actorLogits" not in metadata:
        missing.append("actorLogits")
    if "legalMask" not in row and "mask_" not in row:
        missing.append("legalMask")
    if missing:
        raise ValueError("current policy row is missing fields: " + ", ".join(missing))

    if "legalMask" in row and "mask_" in row:
        explicit_mask = [bool(value) for value in list(row.get("legalMask") or [])]
        tensor_mask = [bool(value) for value in list(row.get("mask_") or [])]
        if explicit_mask != tensor_mask:
            raise ValueError("legalMask and mask_ disagree")
    legal_mask = [bool(value) for value in list(row.get("legalMask") if "legalMask" in row else row.get("mask_") or [])]
    actions = list(row.get("actions") or [])
    actor_logits = [float(value) for value in list(row.get("actorLogits") if "actorLogits" in row else metadata.get("actorLogits") or [])]
    if len(legal_mask) != len(actions) or len(legal_mask) != len(actor_logits):
        raise ValueError("legalMask, actions, and actorLogits must have the same length")
    non_finite_logits = [
        index for index, value in enumerate(actor_logits) if not math.isfinite(float(value))
    ]
    if non_finite_logits:
        raise ValueError(
            "current policy row has non-finite actorLogits: "
            + ",".join(str(index) for index in non_finite_logits)
        )
    action_features = row.get("actions_")
    if isinstance(action_features, Sequence) and not isinstance(action_features, str | bytes):
        if len(action_features) != len(actions):
            raise ValueError("actions_ and actions must have the same length")
    action_records = row.get("actionRecords")
    if not isinstance(action_records, Sequence) or isinstance(action_records, str | bytes):
        raise ValueError("actionRecords must be a sequence")
    if len(action_records) != len(actions):
        raise ValueError("actionRecords and actions must have the same length")
    for index, (action, record) in enumerate(zip(actions, action_records)):
        legal = bool(legal_mask[index])
        if not isinstance(action, Mapping):
            if legal:
                raise ValueError(f"actions must contain mapping records at legal slot {index}")
            continue
        if not isinstance(record, Mapping):
            if legal:
                raise ValueError(f"actionRecords must contain mapping records at legal slot {index}")
            continue
        action_identity = canonical_action_identity(action, include_action_key=False)
        record_identity = canonical_action_identity(record, include_action_key=False)
        if action_identity != record_identity:
            raise ValueError(f"actionRecords and actions disagree at slot {index}")
    explicit_action_identities = row.get("actionIdentities")
    if isinstance(explicit_action_identities, Sequence) and not isinstance(explicit_action_identities, str | bytes):
        explicit_identities = [str(value) for value in explicit_action_identities]
        if len(explicit_identities) != len(actions):
            raise ValueError("actionIdentities and actions must have the same length")
        derived_identities = [_action_identity_from_action(action) for action in actions]
        for index, (explicit_identity, derived_identity) in enumerate(zip(explicit_identities, derived_identities)):
            if bool(legal_mask[index]) and explicit_identity != derived_identity:
                raise ValueError(f"actionIdentities and actions disagree at slot {index}")
    if not any(bool(value) for value in legal_mask):
        raise ValueError("current policy row requires at least one legal action")

    action_identities = action_identities_from_row(row)
    if len(action_identities) != len(actions):
        raise ValueError("action identities and actions must have the same length")
    missing_identity_slots = [
        index
        for index, value in enumerate(action_identities)
        if bool(legal_mask[index]) and not str(value).strip()
    ]
    if missing_identity_slots:
        raise ValueError("current policy row has empty action identity slots: " + ",".join(map(str, missing_identity_slots)))

    return {
        "actorPolicyId": actor_policy_id,
        "stateKey": str(row.get("stateKey") or ""),
        "decisionKind": str(row.get("decisionKind") or ""),
        "legalMask": list(legal_mask),
        "actorLogits": actor_logits,
        "actionIdentities": action_identities,
    }


def action_identities_from_row(row: Mapping[str, Any]) -> list[str]:
    explicit = row.get("actionIdentities")
    if isinstance(explicit, Sequence) and not isinstance(explicit, str | bytes):
        return [str(value) for value in explicit]

    actions = row.get("actions")
    if not isinstance(actions, Sequence) or isinstance(actions, str | bytes):
        return []
    identities: list[str] = []
    for action in actions:
        identities.append(_action_identity_from_action(action))
    return identities


def _action_identity_from_action(action: Any) -> str:
    if isinstance(action, Mapping) and str(action.get("actionIdentity") or "").strip():
        return str(action["actionIdentity"])
    if not isinstance(action, Mapping):
        return ""
    return canonical_action_identity(action, include_action_key=False)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _actor_selection_mode_allows_non_top(row: Mapping[str, Any]) -> bool:
    metadata = _mapping(row.get("metadata"))
    mode = str(row.get("actorSelectionMode") or metadata.get("actorSelectionMode") or "").strip()
    return mode in {"sampled_from_logits", "stochastic_rollout"}


def _actor_sampling_temperature(row: Mapping[str, Any]) -> float | None:
    metadata = _mapping(row.get("metadata"))
    return _finite_float(
        row.get(
            "actorSelectionTemperature",
            row.get(
                "actorTemperature",
                metadata.get("actorSelectionTemperature", metadata.get("actorTemperature")),
            ),
        )
    )


def _actor_sampling_log_prob(row: Mapping[str, Any]) -> float | None:
    metadata = _mapping(row.get("metadata"))
    return _finite_float(
        row.get(
            "actorActionLogProb",
            row.get(
                "actorLogProb",
                metadata.get("actorActionLogProb", metadata.get("actorLogProb")),
            ),
        )
    )


def _finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _row_actor_policy_id(row: Mapping[str, Any]) -> str:
    value, conflict = _consistent_source_value(row, "actorPolicyId")
    return "" if conflict else value


def current_policy_id_container_conflict_rejection_reason(row: Mapping[str, Any]) -> str | None:
    _, conflict = _consistent_source_value(row, "actorPolicyId")
    if conflict:
        return "actor_policy_id_conflict"
    actor_policy_id, alias_conflict = _consistent_source_value(
        row,
        "actorPolicyId",
        "currentPolicyActorPolicyId",
    )
    if alias_conflict:
        return "actor_policy_id_conflict"
    if actor_policy_id:
        return None
    return None


def teacher_score_mode_from_row(row: Mapping[str, Any]) -> str:
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        for key in ("scoreProvenance", "runtimeTotalScoreProvenance"):
            provenance = source.get(key)
            if isinstance(provenance, Mapping):
                value = provenance.get("scoreMode")
                if value:
                    return str(value).strip()
    metadata = _mapping(row.get("metadata"))
    return str(metadata.get("teacherScoreMode") or row.get("teacherScoreMode") or "").strip()


def _teacher_score_mode(row: Mapping[str, Any]) -> str:
    return teacher_score_mode_from_row(row)


def score_mode_consistency_rejection_reason(
    row: Mapping[str, Any],
    *,
    allowed_modes: Sequence[str] = ("runtime_total", "direct_action_set_scorer"),
) -> str | None:
    modes: list[str] = []
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        for key in ("scoreProvenance", "runtimeTotalScoreProvenance"):
            provenance = source.get(key)
            if isinstance(provenance, Mapping):
                value = str(provenance.get("scoreMode") or "").strip()
                if value:
                    modes.append(value)
        value = str(source.get("teacherScoreMode") or "").strip()
        if value:
            modes.append(value)
    unique_modes = {mode for mode in modes if mode}
    if not unique_modes:
        return "missing_score_mode"
    if len(unique_modes) > 1:
        return "score_mode_conflict"
    mode = next(iter(unique_modes))
    if mode not in set(allowed_modes):
        return "stale_teacher_score_mode"
    return None


def _direct_action_set_actor_score_provenance_rejection_reason(
    row: Mapping[str, Any],
    *,
    expected_actor_policy_id: str,
) -> str | None:
    metadata = _mapping(row.get("metadata"))
    if not bool(metadata.get("directActionSetPolicy")):
        return "direct_action_set_policy_missing"
    source_actor, source_conflict = _consistent_source_value(
        row,
        "sourceActorPolicyId",
        "currentPolicySourceActorPolicyId",
    )
    if source_conflict:
        return "direct_action_set_source_actor_policy_conflict"
    if not source_actor:
        return "direct_action_set_source_actor_policy_missing"
    if source_actor != expected_actor_policy_id:
        return "direct_action_set_source_actor_policy_mismatch"
    runtime_policy_id, runtime_conflict = _consistent_source_value(row, "runtimePolicyId", "policyId")
    if runtime_conflict:
        return "direct_action_set_runtime_policy_conflict"
    if not runtime_policy_id:
        return "direct_action_set_runtime_policy_missing"
    if runtime_policy_id != expected_actor_policy_id:
        return "direct_action_set_runtime_policy_mismatch"
    actor_side_value, actor_side_conflict = _consistent_source_value(row, "runtimeActorSide", "modelSide")
    if actor_side_conflict:
        return "direct_action_set_actor_side_conflict"
    actor_side = actor_side_value.upper()
    if actor_side not in {"P1", "P2"}:
        return "direct_action_set_actor_side_missing"
    actor_policy_id, actor_policy_conflict = _consistent_source_value(row, f"{actor_side.lower()}PolicyId")
    if actor_policy_conflict:
        return "direct_action_set_actor_policy_conflict"
    if not actor_policy_id:
        return "direct_action_set_actor_policy_missing"
    if actor_policy_id != expected_actor_policy_id:
        return "direct_action_set_actor_policy_mismatch"
    subject_policy_id, subject_conflict = _consistent_source_value(row, "subjectPolicyId")
    if subject_conflict:
        return "direct_action_set_subject_policy_conflict"
    if subject_policy_id and subject_policy_id != expected_actor_policy_id:
        return "direct_action_set_subject_policy_mismatch"
    return None


def _first_source_value(row: Mapping[str, Any], *keys: str) -> str:
    value, _ = _consistent_source_value(row, *keys)
    return value


def _consistent_source_value(row: Mapping[str, Any], *keys: str) -> tuple[str, bool]:
    values: list[str] = []
    for source in (_mapping(row.get("metadata")), _mapping(row.get("sourceContext")), row):
        for key in keys:
            value = source.get(key)
            if value:
                text = str(value).strip()
                if text:
                    values.append(text)
    if not values:
        return "", False
    if len(set(values)) > 1:
        return values[0], True
    return values[0], False


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
