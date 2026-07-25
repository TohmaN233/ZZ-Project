from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


CURRENT_POLICY_TRAINING_MAINLINE = "unified_current_policy_actor_value"
DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS = 1000
DEFAULT_CURRENT_POLICY_MIN_EVAL_GROUPS = 32
DEFAULT_CURRENT_POLICY_MIN_EXPECTED_ACTION_VALUE_LIFT = 0.0
CURRENT_POLICY_TARGET_ORIGINAL48_WINS = 38
CURRENT_POLICY_RUNTIME_SELECTION = "masked_argmax_action"
CURRENT_POLICY_SCORE_MODE = "current_policy_actor_logits"
CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE = "current_policy_sampled_trajectory_actor_value"
CURRENT_POLICY_LEGACY_FULL_LEGAL_OBJECTIVE = "current_policy_full_legal_actor_value"
CURRENT_POLICY_RUNTIME_SCORE_DISTILL_OBJECTIVE = "v137_runtime_score_distilled_current_policy_actor"
_CURRENT_POLICY_LEGACY_RUNTIME_KEYS = (
    "action_set_listwise_scorer_path",
    "phase_p_action_value_scorer_path",
    "direct_action_set_scorer_path",
    "action_set_residual_scorer_path",
)


def current_policy_runtime_weights_for_actor_model_path(
    *,
    actor_id: str,
    model_path: str | Path,
    decision_kinds: Iterable[str] | None = None,
    min_source_rows: int = DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS,
    source_policy_id: str = "",
) -> dict[str, Any]:
    resolved_actor_id = str(actor_id or "").strip()
    if not resolved_actor_id:
        raise ValueError("current-policy actor id is missing")
    return {
        "direct_action_set_policy": True,
        "current_policy_actor_value": True,
        "current_policy_actor_model_path": str(Path(model_path)),
        "current_policy_runtime_selection": CURRENT_POLICY_RUNTIME_SELECTION,
        "current_policy_candidate_score_mode": CURRENT_POLICY_SCORE_MODE,
        "action_set_influence_decision_kinds": [
            str(kind).strip()
            for kind in list(decision_kinds or [])
            if str(kind).strip()
        ],
        "current_policy_expected_candidate_policy_ids": [resolved_actor_id],
        "current_policy_min_source_rows": int(min_source_rows),
        "source_policy_id": str(source_policy_id or "").strip(),
    }


def load_current_policy_actor_artifact(
    path: str | Path,
    *,
    expected_candidate_policy_ids: Iterable[str] | None = None,
    context: str = "current policy actor artifact",
) -> dict[str, Any]:
    actor_path = Path(path)
    payload = _load_json_mapping(actor_path)
    assert_current_policy_actor_artifact(
        payload,
        context=f"{context}: {actor_path}",
        expected_candidate_policy_ids=expected_candidate_policy_ids,
    )
    return payload


def assert_current_policy_actor_artifact(
    payload: Mapping[str, Any],
    *,
    context: str,
    expected_candidate_policy_ids: Iterable[str] | None = None,
) -> None:
    if not bool(payload.get("runtimeLaunchableActor")):
        raise ValueError(f"{context} is not a current policy actor artifact")
    if str(payload.get("trainingMainline") or "") != CURRENT_POLICY_TRAINING_MAINLINE:
        raise ValueError(f"{context} is not a current policy actor artifact")
    required_true_fields = (
        "fullLegalActionSetTraining",
        "unifiedMaskedActorValueTraining",
        "directPolicyRuntimeAuthority",
    )
    for key in required_true_fields:
        if not bool(payload.get(key)):
            raise ValueError(f"{context} is not a current policy actor artifact: {key} is not true")
    if str(payload.get("trainingObjective") or "") not in {
        CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE,
        CURRENT_POLICY_LEGACY_FULL_LEGAL_OBJECTIVE,
        CURRENT_POLICY_RUNTIME_SCORE_DISTILL_OBJECTIVE,
    }:
        raise ValueError(f"{context} is not a current policy actor artifact: wrong trainingObjective")
    if str(payload.get("runtimeSelectionInterface") or "") != "zz.current_policy_runtime.masked_argmax_action":
        raise ValueError(f"{context} is not a current policy actor artifact: wrong runtimeSelectionInterface")
    if str(payload.get("runtimeRowContract") or "") != "zz.current_policy_runtime.validate_current_policy_row":
        raise ValueError(f"{context} is not a current policy actor artifact: wrong runtimeRowContract")
    if bool(payload.get("selectedActionImitation")):
        raise ValueError(f"{context} is not a current policy actor artifact: selectedActionImitation is true")
    for key in ("sidecarListwiseTraining", "residualSidecarTraining", "runtimeCalibratedSidecarTraining"):
        if bool(payload.get(key)):
            raise ValueError(f"{context} is not a current policy actor artifact: {key} is true")
    actor_policy_id = str(payload.get("actorPolicyId") or "").strip()
    if not actor_policy_id:
        raise ValueError(f"{context} actorPolicyId is missing")
    if not str(payload.get("sourceActorPolicyId") or "").strip():
        raise ValueError(f"{context} sourceActorPolicyId is missing")
    candidate_policy_id = str(payload.get("candidatePolicyId") or payload.get("modelId") or "").strip()
    if not candidate_policy_id:
        raise ValueError(f"{context} candidatePolicyId is missing")
    if actor_policy_id != candidate_policy_id:
        raise ValueError(
            f"{context} actorPolicyId/candidatePolicyId mismatch: "
            f"actorPolicyId={actor_policy_id}, candidatePolicyId={candidate_policy_id}"
        )
    expected = {str(item).strip() for item in list(expected_candidate_policy_ids or []) if str(item).strip()}
    if expected:
        actual = candidate_policy_id
        if actual not in expected:
            raise ValueError(
                f"{context} candidatePolicyId mismatch: "
                f"expected one of {sorted(expected)}, got {actual or 'missing'}"
            )


def assert_current_policy_actor_training_eval_ready(
    payload: Mapping[str, Any],
    *,
    model_path: str | Path,
    context: str,
    require_training_report: bool = True,
    min_training_rows: int | None = DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS,
    min_eval_groups: int = DEFAULT_CURRENT_POLICY_MIN_EVAL_GROUPS,
    required_decision_kinds: Iterable[str] | None = None,
) -> dict[str, Any]:
    actor_path = Path(model_path)
    report_path_value = str(payload.get("trainingReportPath") or "").strip()
    if not report_path_value:
        if require_training_report:
            raise ValueError(f"{context} training report path is missing")
        return {"checked": False, "trainingReportPath": ""}
    report_path = resolve_related_path(report_path_value, base_path=actor_path)
    if report_path is None:
        raise ValueError(f"{context} training report path is missing: {report_path_value}")

    report = _load_json_mapping(report_path)
    if str(report.get("kind") or "") != "ygo_style_current_policy_training_v1":
        raise ValueError(f"{context} training report kind is not current-policy training")
    if str(report.get("trainingMainline") or "") != CURRENT_POLICY_TRAINING_MAINLINE:
        raise ValueError(f"{context} training report mainline is not current-policy actor/value")
    report_bootstrap = bool(report.get("bootstrapInitialization") or payload.get("bootstrapInitialization"))
    behavior_clone = bool(report.get("behaviorCloneTraining") or payload.get("behaviorCloneTraining"))
    actor_n_source_eligible = bool(report.get("actorNSourceEligible")) and bool(payload.get("actorNSourceEligible"))
    bootstrap_source_seed = (
        report_bootstrap
        and not behavior_clone
        and actor_n_source_eligible
        and bool(report.get("currentPolicyBootstrapSourceEligible"))
        and bool(payload.get("currentPolicyBootstrapSourceEligible"))
        and bool(report.get("baseActorEquivalenceGatePassed"))
        and bool(payload.get("baseActorEquivalenceGatePassed"))
    )
    objective = str(report.get("trainingObjective") or "")
    bootstrap_source_objectives = {
        CURRENT_POLICY_LEGACY_FULL_LEGAL_OBJECTIVE,
        CURRENT_POLICY_RUNTIME_SCORE_DISTILL_OBJECTIVE,
    }
    if objective != CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE and not (
        bootstrap_source_seed and objective in bootstrap_source_objectives
    ):
        raise ValueError(f"{context} training report objective is not current-policy sampled trajectory actor/value")
    if not bool(report.get("gateEligible")) and not bootstrap_source_seed:
        raise ValueError(f"{context} training report gateEligible is not true")
    if not bool(report.get("fullDirectPolicyTraining")):
        raise ValueError(f"{context} training report fullDirectPolicyTraining is not true")
    if bool(report.get("scratchTraining")) and not bootstrap_source_seed:
        raise ValueError(f"{context} training report scratchTraining is true")
    expected_candidate_id = str(payload.get("candidatePolicyId") or payload.get("modelId") or "").strip()
    expected_actor_id = str(payload.get("actorPolicyId") or "").strip()
    report_candidate_id = str(report.get("candidatePolicyId") or "").strip()
    if not report_candidate_id:
        raise ValueError(f"{context} training report candidatePolicyId is missing")
    if expected_candidate_id and expected_candidate_id != report_candidate_id:
        raise ValueError(
            f"{context} training report candidatePolicyId mismatch: "
            f"expected {expected_candidate_id}, got {report_candidate_id}"
        )
    report_actor_id = str(report.get("actorPolicyId") or "").strip()
    if not report_actor_id:
        raise ValueError(f"{context} training report actorPolicyId is missing")
    if expected_actor_id and report_actor_id != expected_actor_id:
        raise ValueError(
            f"{context} training report actorPolicyId mismatch: "
            f"expected {expected_actor_id}, got {report_actor_id}"
        )

    if report_bootstrap and not bootstrap_source_seed:
        raise ValueError(f"{context} bootstrapInitialization is not a learned actor_N source")
    if behavior_clone:
        raise ValueError(f"{context} behaviorCloneTraining is not a learned actor_N source")
    row_contract_kind = "current_policy_training_row_contract_report_v1"
    row_contract = report.get("currentPolicyRowContractReport")
    if not isinstance(row_contract, Mapping) and bootstrap_source_seed:
        row_contract = report.get("currentPolicyBootstrapRowContractReport")
    accepted_rows = 0
    rejected_rows = 0
    accepted_rows_by_decision_kind: dict[str, int] = {}
    if isinstance(row_contract, Mapping):
        row_contract_kind = str(row_contract.get("kind") or "").strip()
        allowed_row_contract_kinds = {"current_policy_training_row_contract_report_v1"}
        if bootstrap_source_seed:
            allowed_row_contract_kinds.add("current_policy_bootstrap_row_contract_report_v1")
        if row_contract_kind not in allowed_row_contract_kinds:
            raise ValueError(
                f"{context} training row contract kind is invalid: "
                f"{row_contract_kind or 'missing'}"
            )
        row_actor_id = str(row_contract.get("actorPolicyId") or "").strip()
        if bootstrap_source_seed and row_contract_kind == "current_policy_bootstrap_row_contract_report_v1":
            row_actor_id = row_actor_id or str(row_contract.get("bootstrapSourcePolicyId") or "").strip()
        if not row_actor_id:
            raise ValueError(f"{context} training row contract actorPolicyId is missing")
        expected_row_actor_id = str(report.get("sourceActorPolicyId") or payload.get("sourceActorPolicyId") or "").strip()
        if expected_row_actor_id and row_actor_id != expected_row_actor_id:
            raise ValueError(
                f"{context} training row contract actorPolicyId mismatch: "
                f"expected {expected_row_actor_id}, got {row_actor_id}"
            )
        if "acceptedRows" not in row_contract:
            raise ValueError(f"{context} training row contract acceptedRows is missing")
        if "rejectedRows" not in row_contract:
            raise ValueError(f"{context} training row contract rejectedRows is missing")
        accepted_rows = int(row_contract.get("acceptedRows") or 0)
        rejected_rows = int(row_contract.get("rejectedRows") or 0)
        accepted_rows_by_decision_kind = _row_count_mapping(row_contract.get("acceptedRowsByDecisionKind"))
        if rejected_rows != 0:
            raise ValueError(f"{context} training row contract has rejected rows: {rejected_rows}")
    elif min_training_rows is not None:
        raise ValueError(f"{context} training row contract is missing")

    _assert_required_decision_kind_coverage(
        accepted_rows_by_decision_kind,
        required_decision_kinds=required_decision_kinds,
        context=context,
    )

    usable_rows_field = "usableTrajectoryRows" if "usableTrajectoryRows" in report else "usableFullLegalRows"
    usable_rows_value = report.get(usable_rows_field)
    effective_training_rows = int(accepted_rows)
    if usable_rows_value is not None:
        usable_rows = int(usable_rows_value or 0)
        max_rows_report = (
            report.get("maxTrainingRowsReport")
            if isinstance(report.get("maxTrainingRowsReport"), Mapping)
            else {}
        )
        capped_rows = int(max_rows_report.get("outputRows") or -1)
        # ponytail: row contract is pre-cap; maxTrainingRowsReport is the cap trace.
        if usable_rows != accepted_rows and usable_rows != capped_rows:
            raise ValueError(
                f"{context} training report {usable_rows_field} mismatch: "
                f"contract acceptedRows={accepted_rows}, {usable_rows_field}={usable_rows}"
            )
        effective_training_rows = int(usable_rows)

    if min_training_rows is not None and effective_training_rows < int(min_training_rows):
        raise ValueError(
            f"{context} has insufficient current-policy training rows: "
            f"expected at least {int(min_training_rows)}, got {effective_training_rows}"
        )

    if bootstrap_source_seed:
        eval_report = report.get("candidateCurrentPolicyEval")
        eval_groups = int(eval_report.get("groups") or 0) if isinstance(eval_report, Mapping) else 0
        if eval_groups < int(min_eval_groups):
            raise ValueError(
                f"{context} has insufficient current-policy bootstrap eval groups: "
                f"expected at least {int(min_eval_groups)}, got {eval_groups}"
            )
        return {
            "checked": True,
            "trainingReportPath": str(report_path),
            "candidatePolicyId": expected_candidate_id,
            "acceptedRows": int(accepted_rows),
            "acceptedRowsByDecisionKind": dict(accepted_rows_by_decision_kind),
            "usableTrajectoryRows": int(effective_training_rows),
            "usableFullLegalRows": int(effective_training_rows),
            "rejectedRows": int(rejected_rows),
            "rowContractKind": row_contract_kind,
            "bootstrapInitialization": True,
            "evalGroups": int(eval_groups),
            "sampledAdvantageEvalRows": 0,
            "sampledAdvantageDirectionAccuracy": None,
            "expectedActionValueLiftVsUniform": None,
            "argmaxActionValueLiftVsUniform": None,
            "baseExpectedActionValueLiftVsUniform": None,
            "baseArgmaxActionValueLiftVsUniform": None,
            "expectedActionValueLiftDeltaVsBase": None,
            "argmaxActionValueLiftDeltaVsBase": None,
            "actionValueEvalDiagnosticsOnly": True,
            "trajectoryPolicyEvalOnly": False,
            "currentPolicyBootstrapSourceEligible": True,
            "actorNSourceEligible": bool(actor_n_source_eligible),
            "sourceActorSourceReady": bool(report.get("sourceActorSourceReady")) and bool(payload.get("sourceActorSourceReady")),
        }

    sampled_eval = report.get("candidateCurrentPolicySampledAdvantageEval")
    if not isinstance(sampled_eval, Mapping):
        raise ValueError(f"{context} sampled-advantage eval is missing")
    sampled_total = int(sampled_eval.get("total") or 0)
    if sampled_total <= 0:
        raise ValueError(f"{context} sampled-advantage eval is empty")
    try:
        sampled_direction_accuracy = float(sampled_eval.get("directionAccuracy"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} sampled-advantage directionAccuracy is missing") from exc
    if not math.isfinite(sampled_direction_accuracy):
        raise ValueError(
            f"{context} sampled-advantage directionAccuracy is not finite: {sampled_direction_accuracy!r}"
        )
    return {
        "checked": True,
        "trainingReportPath": str(report_path),
        "candidatePolicyId": expected_candidate_id,
        "acceptedRows": int(accepted_rows),
        "acceptedRowsByDecisionKind": dict(accepted_rows_by_decision_kind),
        "usableTrajectoryRows": int(effective_training_rows),
        "usableFullLegalRows": int(effective_training_rows),
        "rejectedRows": int(rejected_rows),
        "rowContractKind": row_contract_kind,
        "bootstrapInitialization": False,
        "evalGroups": int(sampled_total),
        "sampledAdvantageEvalRows": int(sampled_total),
        "sampledAdvantageDirectionAccuracy": float(sampled_direction_accuracy),
        "expectedActionValueLiftVsUniform": None,
        "argmaxActionValueLiftVsUniform": None,
        "baseExpectedActionValueLiftVsUniform": None,
        "baseArgmaxActionValueLiftVsUniform": None,
        "expectedActionValueLiftDeltaVsBase": None,
        "argmaxActionValueLiftDeltaVsBase": None,
        "actionValueEvalDiagnosticsOnly": True,
        "trajectoryPolicyEvalOnly": True,
        "actorNSourceEligible": bool(actor_n_source_eligible),
        "sourceActorSourceReady": bool(report.get("sourceActorSourceReady")) and bool(payload.get("sourceActorSourceReady")),
    }


def assert_current_policy_source_actor_ready(
    actor_id: str,
    *,
    runtime_weights: Mapping[str, Any],
    explicit_model_path: str | Path | None = None,
    context: str = "current-policy source actor",
) -> dict[str, Any]:
    resolved_actor_id = str(actor_id or "").strip()
    if not resolved_actor_id:
        raise ValueError(f"{context} policy id is missing")
    if not bool(runtime_weights.get("current_policy_actor_value")):
        raise ValueError(f"{context} is not a current-policy actor runtime: {resolved_actor_id!r}")
    _assert_current_policy_runtime_weights_shape(runtime_weights, context=f"{context} {resolved_actor_id!r}")
    raw_registered_path = str(runtime_weights.get("current_policy_actor_model_path") or "").strip()
    if not raw_registered_path:
        raise ValueError(f"{context} model path is missing: {resolved_actor_id!r}")
    registered_path = Path(raw_registered_path)
    if explicit_model_path is not None:
        model_path = Path(explicit_model_path)
        if canonical_path(model_path) != canonical_path(registered_path):
            raise ValueError(
                f"{context} model path must match the registered actor path: "
                f"expected {registered_path}, got {model_path}"
            )
    else:
        model_path = registered_path
    if not model_path.exists():
        raise FileNotFoundError(f"{context} model path does not exist: {model_path}")

    expected_candidate_ids = [
        str(item).strip()
        for item in list(runtime_weights.get("current_policy_expected_candidate_policy_ids") or [])
        if str(item).strip()
    ]
    actor_payload = load_current_policy_actor_artifact(
        model_path,
        expected_candidate_policy_ids=expected_candidate_ids,
        context=f"{context} {resolved_actor_id!r}",
    )
    actor_payload_id = str(actor_payload.get("actorPolicyId") or "").strip()
    expected_source_actor_id = str(runtime_weights.get("source_policy_id") or "").strip()
    actor_source_id = str(actor_payload.get("sourceActorPolicyId") or "").strip()
    if expected_source_actor_id and actor_source_id != expected_source_actor_id:
        raise ValueError(
            f"{context} {resolved_actor_id!r} sourceActorPolicyId mismatch: "
            f"expected {expected_source_actor_id}, got {actor_source_id or 'missing'}"
        )
    base_preserving_actor = bool(
        actor_payload.get("basePreservingActor")
        or runtime_weights.get("current_policy_base_preserving_actor")
    )
    base_policy_id = str(
        actor_payload.get("basePolicyId")
        or runtime_weights.get("current_policy_base_policy_id")
        or ""
    )
    if base_preserving_actor:
        raise ValueError(f"{context} {resolved_actor_id!r} base-preserving actors are not valid actor_N sources")
    min_source_rows = int(
        runtime_weights.get("current_policy_min_source_rows")
        or runtime_weights.get("current_policy_min_gate_rows")
        or DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS
    )
    readiness = assert_current_policy_actor_training_eval_ready(
        actor_payload,
        model_path=model_path,
        context=f"{context} {resolved_actor_id!r}",
        require_training_report=True,
        min_training_rows=min_source_rows,
        min_eval_groups=DEFAULT_CURRENT_POLICY_MIN_EVAL_GROUPS,
        required_decision_kinds=_decision_kind_set(runtime_weights.get("action_set_influence_decision_kinds")),
    )
    if not bool(actor_payload.get("actorNSourceEligible")):
        raise ValueError(f"{context} {resolved_actor_id!r} actorNSourceEligible is not true")
    battle_evidence = _assert_current_policy_source_battle_gate_evidence(
        actor_payload,
        model_path=model_path,
        context=f"{context} {resolved_actor_id!r}",
    )
    return {
        "policyId": resolved_actor_id,
        "actorPolicyId": actor_payload_id,
        "modelPath": str(model_path),
        "sourcePolicyId": expected_source_actor_id,
        "sourceActorPolicyId": actor_source_id,
        "candidatePolicyId": str(actor_payload.get("candidatePolicyId") or actor_payload.get("modelId") or ""),
        "basePreservingActor": False,
        "basePolicyId": base_policy_id,
        "minSourceRows": int(min_source_rows),
        "readiness": readiness,
        "battleGateEvidence": battle_evidence,
    }


def _assert_current_policy_base_preserving_source_report_ready(
    payload: Mapping[str, Any],
    *,
    model_path: str | Path,
    context: str,
) -> dict[str, Any]:
    report_path_value = str(payload.get("trainingReportPath") or "").strip()
    if not report_path_value:
        raise ValueError(f"{context} training report path is missing")
    report_path = resolve_related_path(report_path_value, base_path=model_path)
    if report_path is None:
        raise ValueError(f"{context} training report path is missing: {report_path_value}")
    report = _load_json_mapping(report_path)
    if str(report.get("kind") or "") != "ygo_style_current_policy_training_v1":
        raise ValueError(f"{context} training report kind is not current-policy training")
    if str(report.get("trainingMainline") or "") != CURRENT_POLICY_TRAINING_MAINLINE:
        raise ValueError(f"{context} training report mainline is not current-policy actor/value")
    if str(report.get("trainingObjective") or "") != CURRENT_POLICY_LEGACY_FULL_LEGAL_OBJECTIVE:
        raise ValueError(f"{context} base-preserving source objective is not full-legal actor/value")
    if not bool(report.get("gateEligible")):
        raise ValueError(f"{context} training report gateEligible is not true")
    if not bool(report.get("fullDirectPolicyTraining")):
        raise ValueError(f"{context} training report fullDirectPolicyTraining is not true")
    if bool(report.get("scratchTraining")):
        raise ValueError(f"{context} training report scratchTraining is true")
    for key in ("actorPolicyId", "candidatePolicyId", "sourceActorPolicyId", "basePolicyId"):
        expected = str(payload.get(key) or "").strip()
        actual = str(report.get(key) or "").strip()
        if expected and actual and expected != actual:
            raise ValueError(f"{context} training report {key} mismatch: expected {expected}, got {actual}")
    return {
        "checked": True,
        "trainingReportPath": str(report_path),
        "candidatePolicyId": str(payload.get("candidatePolicyId") or payload.get("modelId") or ""),
        "acceptedRows": 0,
        "acceptedRowsByDecisionKind": {},
        "usableTrajectoryRows": 0,
        "usableFullLegalRows": 0,
        "rejectedRows": 0,
        "rowContractKind": "",
        "bootstrapInitialization": False,
        "basePreservingActor": True,
        "evalGroups": 0,
        "sampledAdvantageEvalRows": 0,
        "sampledAdvantageDirectionAccuracy": None,
        "actionValueEvalDiagnosticsOnly": True,
        "trajectoryPolicyEvalOnly": False,
        "actorNSourceEligible": bool(payload.get("actorNSourceEligible")),
        "sourceActorSourceReady": bool(payload.get("sourceActorSourceReady")),
    }


def _assert_current_policy_runtime_weights_shape(runtime_weights: Mapping[str, Any], *, context: str) -> None:
    if not bool(runtime_weights.get("direct_action_set_policy")):
        raise ValueError(f"{context} must use direct_action_set_policy")
    selection = str(runtime_weights.get("current_policy_runtime_selection") or "").strip()
    if selection != CURRENT_POLICY_RUNTIME_SELECTION:
        raise ValueError(
            f"{context} runtime selection must be {CURRENT_POLICY_RUNTIME_SELECTION}: {selection or 'missing'}"
        )
    score_mode = str(runtime_weights.get("current_policy_candidate_score_mode") or "").strip()
    if score_mode != CURRENT_POLICY_SCORE_MODE:
        raise ValueError(
            f"{context} candidate score mode must be {CURRENT_POLICY_SCORE_MODE}: {score_mode or 'missing'}"
        )
    mixed = [key for key in _CURRENT_POLICY_LEGACY_RUNTIME_KEYS if runtime_weights.get(key)]
    for key in ("action_set_aux_score_weight", "action_set_residual_score_weight"):
        try:
            if abs(float(runtime_weights.get(key) or 0.0)) > 1.0e-12:
                mixed.append(key)
        except (TypeError, ValueError):
            mixed.append(key)
    if mixed:
        raise ValueError(f"{context} cannot mix legacy sidecar runtime keys: {', '.join(sorted(set(mixed)))}")


def _assert_required_decision_kind_coverage(
    accepted_rows_by_decision_kind: Mapping[str, int],
    *,
    required_decision_kinds: Iterable[str] | None,
    context: str,
) -> None:
    required = _decision_kind_set(required_decision_kinds)
    if not required:
        return
    if not accepted_rows_by_decision_kind:
        raise ValueError(f"{context} acceptedRowsByDecisionKind is missing")
    missing = sorted(
        kind
        for kind in required
        if int(accepted_rows_by_decision_kind.get(kind) or 0) <= 0
    )
    if missing:
        raise ValueError(
            f"{context} missing required decision kind coverage: "
            + ", ".join(missing)
        )


def _decision_kind_set(value: Iterable[str] | Any | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {
            token.strip()
            for chunk in value.split(";")
            for token in chunk.split(",")
            if token.strip()
        }
    try:
        return {str(item).strip() for item in value if str(item).strip()}
    except TypeError:
        text = str(value).strip()
        return {text} if text else set()


def _row_count_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        decision = str(key).strip()
        if not decision:
            continue
        try:
            count = int(raw_count or 0)
        except (TypeError, ValueError):
            count = 0
        counts[decision] = count
    return counts


def _assert_current_policy_source_battle_gate_evidence(
    payload: Mapping[str, Any],
    *,
    model_path: str | Path,
    context: str,
) -> dict[str, Any]:
    evidence = payload.get("sourceBattleGateEvidence") or payload.get("baseActorEquivalenceBattleEvidence")
    if not isinstance(evidence, Mapping):
        raise ValueError(f"{context} source battle gate evidence is missing")
    paired_path = resolve_related_path(
        str(evidence.get("pairedGateReportPath") or ""),
        base_path=model_path,
    )
    if paired_path is None:
        raise ValueError(f"{context} paired battle gate report is missing")
    paired_report = _load_json_mapping(paired_path)
    report_kind = str(paired_report.get("kind") or "").strip()
    candidate_policy_id = str(payload.get("candidatePolicyId") or payload.get("modelId") or "").strip()
    if report_kind == "n4_paired_flip_farm_v1":
        if str(paired_report.get("candidatePolicyId") or "").strip() != candidate_policy_id:
            raise ValueError(f"{context} paired battle candidate policyId mismatch")
        paired_totals = _paired_battle_gate_totals(paired_report)
    elif report_kind == "phase_n4_true_winrate_gate":
        if str(paired_report.get("policyId") or "").strip() != candidate_policy_id:
            raise ValueError(f"{context} true-winrate battle policyId mismatch")
        source_actor_id = str(payload.get("sourceActorPolicyId") or "").strip()
        opponent_ids = {str(value).strip() for value in paired_report.get("opponentPolicyIds") or []}
        if source_actor_id and source_actor_id not in opponent_ids:
            raise ValueError(f"{context} true-winrate battle opponent does not include source actor")
        paired_totals = _true_winrate_gate_totals(paired_report)
    elif report_kind == "current_policy_original48_comparison_v1":
        if str(paired_report.get("candidatePolicyId") or "").strip() != candidate_policy_id:
            raise ValueError(f"{context} original48 comparison candidate policyId mismatch")
        source_actor_id = str(payload.get("sourceActorPolicyId") or "").strip()
        reference_policy_id = str(paired_report.get("referencePolicyId") or "").strip()
        if source_actor_id and reference_policy_id != source_actor_id:
            candidate_source_policy_id = str(paired_report.get("candidateSourceActorPolicyId") or "").strip()
            if candidate_source_policy_id != source_actor_id:
                raise ValueError(f"{context} original48 comparison reference policyId mismatch")
        paired_totals = _original48_comparison_totals(paired_report)
    else:
        raise ValueError(
            f"{context} battle evidence must be an n4 paired flip farm, true-winrate gate, "
            "or original48 comparison report"
        )
    candidate_wins = paired_totals["candidateWins"]
    reference_wins = paired_totals["referenceWins"]
    candidate_games = paired_totals["candidateGames"]
    reference_games = paired_totals["referenceGames"]
    min_games = int(evidence.get("minGames") or 48)
    if candidate_games < min_games or reference_games < min_games:
        raise ValueError(f"{context} source battle gate has insufficient games")
    if int(paired_totals["errors"]) != 0:
        raise ValueError(f"{context} source battle gate has errors")
    raw_min_net_wins = evidence.get("minNetWins")
    min_net_wins = int(raw_min_net_wins) if raw_min_net_wins is not None else 1
    net_wins = int(candidate_wins) - int(reference_wins)
    if "netPolicyWins" in paired_report and int(paired_report.get("netPolicyWins") or 0) != net_wins:
        raise ValueError(f"{context} paired battle netPolicyWins mismatch")
    if net_wins < min_net_wins:
        raise ValueError(
            f"{context} source battle gate is below reference: "
            f"candidateWins={candidate_wins}, referenceWins={reference_wins}, minNetWins={min_net_wins}"
        )
    return {
        "reportKind": report_kind,
        "pairedGateReportPath": str(paired_path),
        "candidateWins": int(candidate_wins),
        "referenceWins": int(reference_wins),
        "candidateGames": int(candidate_games),
        "referenceGames": int(reference_games),
        "netWins": int(net_wins),
        "minNetWins": int(min_net_wins),
        "targetOriginal48Wins": int(paired_totals.get("targetOriginal48Wins") or 0),
        "targetReached": bool(paired_totals.get("targetReached", False)),
    }


def _paired_battle_gate_totals(report: Mapping[str, Any]) -> dict[str, int]:
    seed_reports = report.get("seedReports")
    if not isinstance(seed_reports, list) or not seed_reports:
        raise ValueError("paired battle gate seedReports are missing")
    candidate_wins = 0
    reference_wins = 0
    candidate_games = 0
    reference_games = 0
    errors = int(report.get("errors") or 0)
    for seed_report in seed_reports:
        if not isinstance(seed_report, Mapping):
            continue
        candidate_summary = seed_report.get("candidateSummary")
        reference_summary = seed_report.get("referenceSummary")
        if not isinstance(candidate_summary, Mapping) or not isinstance(reference_summary, Mapping):
            continue
        candidate_wins += int(candidate_summary.get("policyWins") or 0)
        reference_wins += int(reference_summary.get("policyWins") or 0)
        candidate_games += int(candidate_summary.get("gamesRun") or candidate_summary.get("taskCount") or 0)
        reference_games += int(reference_summary.get("gamesRun") or reference_summary.get("taskCount") or 0)
        errors += int(candidate_summary.get("errors") or 0)
        errors += int(reference_summary.get("errors") or 0)
    if candidate_games <= 0 or reference_games <= 0:
        raise ValueError("paired battle gate summaries are missing games")
    return {
        "candidateWins": int(candidate_wins),
        "referenceWins": int(reference_wins),
        "candidateGames": int(candidate_games),
        "referenceGames": int(reference_games),
        "errors": int(errors),
    }


def _true_winrate_gate_totals(report: Mapping[str, Any]) -> dict[str, int]:
    overall = report.get("overall")
    if not isinstance(overall, Mapping):
        raise ValueError("true-winrate gate overall summary is missing")
    games = int(overall.get("games") or report.get("successfulGameRows") or report.get("gamesRun") or 0)
    if games <= 0:
        raise ValueError("true-winrate gate summaries are missing games")
    return {
        "candidateWins": int(overall.get("policyWins") or 0),
        "referenceWins": int(overall.get("opponentWins") or 0),
        "candidateGames": games,
        "referenceGames": games,
        "errors": int(report.get("errorRows") or 0),
    }


def _original48_comparison_totals(report: Mapping[str, Any]) -> dict[str, int]:
    candidate_games = int(report.get("candidateGames") or 0)
    reference_games = int(report.get("referenceGames") or 0)
    if candidate_games <= 0 or reference_games <= 0:
        raise ValueError("original48 comparison is missing games")
    if "candidateDirectRuntimeClean" not in report or "referenceDirectRuntimeClean" not in report:
        raise ValueError("original48 comparison direct runtime clean evidence is missing")
    if report.get("candidateDirectRuntimeClean") is not True or report.get("referenceDirectRuntimeClean") is not True:
        raise ValueError("original48 comparison direct runtime is not clean")
    required_combined_gate_fields = (
        "currentModel24Wins",
        "currentModel24Games",
        "currentModel24Errors",
        "currentModel24DirectRuntimeClean",
        "promotionCandidateWins",
        "promotionReferenceWins",
        "promotionCandidateGames",
        "promotionReferenceGames",
    )
    missing_combined_gate_fields = [field for field in required_combined_gate_fields if field not in report]
    if missing_combined_gate_fields:
        raise ValueError(
            "original48 comparison current-model 24 gate evidence is missing: "
            f"{missing_combined_gate_fields[0]}"
        )
    if report.get("currentModel24DirectRuntimeClean") is not True:
        raise ValueError("original48 comparison current-model 24 gate direct runtime is not clean")
    if int(report.get("currentModel24Games") or 0) < 24:
        raise ValueError("original48 comparison current-model 24 gate has insufficient games")
    if int(report.get("currentModel24Errors") or 0) != 0:
        raise ValueError("original48 comparison current-model 24 gate has errors")
    candidate_wins = int(report.get("candidateWins") or 0)
    reference_wins = int(report.get("referenceWins") or 0)
    candidate_games = int(report.get("candidateGames") or 0)
    reference_games = int(report.get("referenceGames") or 0)
    target_original48_wins = max(
        CURRENT_POLICY_TARGET_ORIGINAL48_WINS,
        int(report.get("targetOriginal48Wins") or CURRENT_POLICY_TARGET_ORIGINAL48_WINS),
    )
    target_reached = candidate_wins >= target_original48_wins
    if "targetReached" in report and report.get("targetReached") is not target_reached:
        raise ValueError("original48 comparison targetReached is inconsistent")
    promotion_candidate_wins = int(report.get("promotionCandidateWins") or 0)
    promotion_reference_wins = int(report.get("promotionReferenceWins") or 0)
    promotion_candidate_games = int(report.get("promotionCandidateGames") or 0)
    promotion_reference_games = int(report.get("promotionReferenceGames") or 0)
    if (
        promotion_candidate_wins != candidate_wins
        or promotion_reference_wins != reference_wins
        or promotion_candidate_games != candidate_games
        or promotion_reference_games != reference_games
    ):
        raise ValueError("original48 comparison promotion totals must match fixed original48 totals")
    return {
        "candidateWins": int(candidate_wins),
        "referenceWins": int(reference_wins),
        "candidateGames": int(candidate_games),
        "referenceGames": int(reference_games),
        "errors": int(report.get("errors") or 0),
        "targetOriginal48Wins": int(target_original48_wins),
        "targetReached": int(target_reached),
    }


def resolve_related_path(value: str | Path, *, base_path: str | Path) -> Path | None:
    if not str(value or "").strip():
        return None
    raw_path = Path(value)
    candidates = [raw_path] if raw_path.is_absolute() else [raw_path, Path(base_path).parent / raw_path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def canonical_path(path: str | Path) -> str:
    return str(Path(path).resolve(strict=False)).casefold()


def _load_json_mapping(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data
