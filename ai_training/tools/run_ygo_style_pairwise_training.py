from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence

try:  # pragma: no cover - optional speed path depends on local environment
    import ujson as _fast_json
except ImportError:  # pragma: no cover
    _fast_json = None

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.summarize_action_set_teacher_rows import _iter_json_array_rows
from tools.ygo_action_value_context import (
    assert_play_card_target_semantics_safe,
    assert_target_action_semantics_safe,
    play_card_target_semantics_from_rows,
    target_action_semantics_from_rows,
)
from zz.action_value_row_refresh import (
    refresh_action_value_training_rows_semantics,
)
from zz.current_policy_runtime import (
    actor_policy_metadata_rejection_reason,
    actor_score_provenance_rejection_reason,
    actor_rollout_provenance_rejection_reason,
    current_policy_id_container_conflict_rejection_reason,
    score_mode_consistency_rejection_reason,
    select_current_policy_top,
    validate_current_policy_row,
)
from zz.current_policy_actor_contract import (
    DEFAULT_CURRENT_POLICY_MIN_EVAL_GROUPS,
    DEFAULT_CURRENT_POLICY_MIN_EXPECTED_ACTION_VALUE_LIFT,
    DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS,
    assert_current_policy_source_actor_ready,
    current_policy_runtime_weights_for_actor_model_path,
    load_current_policy_actor_artifact,
)
from zz.action_set_ygo_policy import (
    ACTION_VALUE_DISTRIBUTION_SIDECAR_TARGET_MODE,
    BOUNDED_RUNTIME_AUX_MAX_CORRECTION,
    DIRECT_POLICY_TARGET_MODE_ACTION_VALUE_DISTRIBUTION,
    DIRECT_POLICY_TARGET_MODE_PREFERRED_SLOT_CE,
    DIRECT_POLICY_TARGET_MODES,
    FULL_LEGAL_POLICY_OBJECTIVE_SEARCH_IMPROVED_CE,
    FULL_LEGAL_POLICY_OBJECTIVE_SEARCH_VALUE_CE,
    FULL_LEGAL_SEARCH_IMPROVED_BASE_CORRECT_PRESERVE_WEIGHT,
    FULL_LEGAL_POLICY_OBJECTIVES,
    POLICY_VALUE_ANCHOR_SOURCE_ROW_RUNTIME_TOTAL,
    POLICY_VALUE_TARGET_SOURCE_ACTION_VALUE,
    POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_ARGMAX,
    POLICY_VALUE_TARGET_SOURCE_SELECTED_ACTION_SLOT,
    POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_TOTAL,
    RUNTIME_AUX_TRAINING_OBJECTIVE_BOUNDED_BASE_WRONG_PRESERVE_CORRECT,
    RUNTIME_AUX_TRAINING_OBJECTIVE_BASE_WRONG_ONLY,
    RUNTIME_AUX_TRAINING_OBJECTIVE_BASE_WRONG_PRESERVE_CORRECT,
    RUNTIME_AUX_TRAINING_OBJECTIVE_TRAJECTORY_ADVANTAGE,
    RUNTIME_AUX_TRAINING_OBJECTIVE_VALUE_DISTRIBUTION,
    RUNTIME_AUX_TRAINING_OBJECTIVES,
    SANDBOX_FULL_LEGAL_POLICY_VALUE_TARGET_MODE,
    TRAJECTORY_ADVANTAGE_RUNTIME_SIDECAR_TARGET_MODE,
    YGO_STYLE_FEATURE_FAMILY,
    YgoStyleActionSetPolicyScorer,
    build_ygo_outcome_policy_tensor_batch,
    evaluate_ygo_style_full_legal_policy_value_scorer,
    train_ygo_style_full_legal_policy_value_scorer,
    train_ygo_style_full_legal_policy_value_scorer_streaming,
    train_ygo_style_action_value_distribution_scorer,
    train_ygo_style_outcome_policy_scorer,
    train_ygo_style_direct_policy_scorer,
    train_ygo_style_pairwise_scorer,
    train_ygo_style_trajectory_advantage_runtime_scorer,
)
from zz.action_set_ygo_policy import _direct_policy_target_slot as _ygo_direct_policy_target_slot
from zz.action_set_ygo_policy import _known_action_value_slots as _ygo_known_action_value_slots
from zz.action_set_ygo_policy import _legal_slots as _ygo_legal_slots
from zz.action_set_ygo_policy import _merged_feature_names as _ygo_merged_feature_names
from zz.action_set_ygo_policy import _pairwise_preference as _ygo_pairwise_preference
from zz.action_set_ygo_policy import _row_has_action_value_distribution_target as _ygo_row_has_action_value_distribution_target
from zz.action_set_ygo_policy import _row_training_weight as _ygo_row_training_weight
from zz.action_set_ygo_policy import _trajectory_policy_label as _ygo_trajectory_policy_label
from zz.action_set_scoring_contracts import (
    DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
    DEFAULT_YGO_UPDATE_EPOCHS,
    best_value_slots,
    resolve_runtime_aux_output_scale,
    runtime_top_slot,
    value_spread_is_trainable,
)
from zz.action_set_runtime_scores import (
    row_runtime_total_rejection_reason,
    row_runtime_total_scores,
    runtime_total_score_provenance,
)
from zz.action_value_group_key import (
    action_value_group_identity_rejection_reason,
    action_value_state_group_key,
    canonical_action_identity,
)
from zz.runtime_aux_compose import compose_runtime_aux_score, is_bounded_runtime_aux_objective
from zz.ygo_failed_direct_guard import reject_rejected_direct_ygo_model


def _loads_training_row_json(text: str) -> Any:
    if _fast_json is not None:
        return _fast_json.loads(text)
    return json.loads(text)


def assert_restart_safety_clear(
    path: str | Path | None,
    *,
    usage_label: str,
    allow_unreviewed_restart: bool = False,
) -> dict[str, Any] | None:
    if path is None:
        if bool(allow_unreviewed_restart):
            return {
                "allowUnreviewedRestart": True,
                "reviewPath": None,
                "requiresReview": False,
                "blockedForRestart": False,
                "blockingReasons": [],
            }
        raise ValueError(f"restart safety review is required for {usage_label}")
    review_path = Path(path)
    report = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"restart safety review must be a JSON object: {review_path}")
    if bool(report.get("requiresReview")) or bool(report.get("blockedForRestart")):
        reasons = [str(reason) for reason in report.get("blockingReasons") or []]
        reason_text = ", ".join(reasons) if reasons else "requires review"
        raise ValueError(f"restart safety review blocks {usage_label}: {reason_text}")
    return dict(report)


def _quote_sql_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


YGO_STYLE_PAIRWISE_TRAINING_VERSION = "ygo_style_pairwise_training_v1"
YGO_STYLE_ACTION_VALUE_LISTWISE_TRAINING_VERSION = "ygo_style_action_value_listwise_training_v1"
YGO_STYLE_DIRECT_POLICY_TRAINING_VERSION = "ygo_style_direct_policy_training_v1"
YGO_STYLE_OUTCOME_POLICY_TRAINING_VERSION = "ygo_style_outcome_policy_training_v1"
YGO_STYLE_TRAJECTORY_ADVANTAGE_RUNTIME_TRAINING_VERSION = "ygo_style_trajectory_advantage_runtime_training_v1"
YGO_STYLE_SANDBOX_POLICY_VALUE_TRAINING_VERSION = "ygo_style_sandbox_policy_value_training_v1"
YGO_STYLE_CURRENT_POLICY_TRAINING_VERSION = "ygo_style_current_policy_training_v1"
CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA = "current_policy_sampled_trajectory_rows_v1"
CURRENT_POLICY_TRAJECTORY_TASK_KIND = "current_policy_sampled_rollout_trajectory"
CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE = "current_policy_sampled_trajectory_actor_value"
CURRENT_POLICY_TRAJECTORY_GAE_LAMBDA = 0.95
CURRENT_POLICY_TRAJECTORY_GAMMA = 1.0
YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION = "ygo_fresh_data_one_epoch_canary_v1"
YGO_SCORING_TOPOLOGY_UNIFIED_FULL_LEGAL = "single_unified_full_legal_action_set_scorer"
YGO_DEFAULT_UPDATE_EPOCHS = DEFAULT_YGO_UPDATE_EPOCHS
YGO_DEFAULT_LEARNING_RATE = 0.001
YGO_RUNTIME_AUX_DEFAULT_LEARNING_RATE = 0.08
YGO_DEFAULT_ENTROPY_COEF = 0.01
YGO_STYLE_POLICY_PT_CHECKPOINT_VERSION = "ygo_style_action_set_policy_pt_checkpoint_v1"
YGO_CURRENT_POLICY_BOOTSTRAP_DEFAULT_ANCHOR_KL_WEIGHT = 2.0
YGO_CURRENT_POLICY_ENTROPY_COEF = 0.01
DEFAULT_MAX_CURRENT_POLICY_TRAINING_ROWS: int | None = None
DEFAULT_CURRENT_POLICY_MIN_CLONE_TOP1_ACCURACY = 0.90
YGO_TRAJECTORY_RUNTIME_DEFAULT_ENTROPY_COEF = 0.0
ACTION_VALUE_TARGET_CONTRACT = "action_value"
EXPLICIT_OR_CAUSAL_TARGET_CONTRACT = "explicit_or_causal"
SELECTED_FALLBACK_TARGET_CONTRACT = "selected_fallback_opt_in"
TARGET_CONTRACT_CHOICES = (
    ACTION_VALUE_TARGET_CONTRACT,
    EXPLICIT_OR_CAUSAL_TARGET_CONTRACT,
    SELECTED_FALLBACK_TARGET_CONTRACT,
)
ACTION_VALUE_LABEL_SOURCES = {
    "causal_forced_action_rollout",
    "fresh_forced_action_rollout",
    "gate_runtime_action_set_scores",
    "snapshot_branch_rollout",
    "paired_outcome_flip_first_divergence",
    "paired_outcome_flip_first_divergence_full_legal",
}
FULL_LEGAL_ACTION_VALUE_TEACHER_IDS = {
    "snapshot_branch_rollout",
    "paired_outcome_flip_first_divergence",
}
FULL_LEGAL_ACTION_VALUE_LABEL_SOURCES = {
    "gate_runtime_action_set_scores",
    "snapshot_branch_rollout",
    "paired_outcome_flip_first_divergence",
    "paired_outcome_flip_first_divergence_full_legal",
}
FULL_DIRECT_TRAINING_SUSPENDED_MESSAGE = (
    "full direct ygo policy training is suspended for the current restart; "
    "use pairwise/action-value rows plus protected additive/route-gated assembly"
)
YGO_TRAIN_EVAL_SHUFFLE_LOCK_REASON = "ygo_group_split_requires_seeded_shuffle"
CURRENT_POLICY_FULL_LEGAL_ROLLOUT_TASK_KIND = "current_policy_full_legal_rollout_value"
BOOTSTRAP_FULL_LEGAL_ROLLOUT_TASK_KIND = "causal_full_legal_action_set_rollout_value"


def _effective_ygo_train_eval_shuffle(_requested_shuffle_rows: bool) -> bool:
    return True


def _shuffle_rows_report_fields(requested_shuffle_rows: bool) -> dict[str, Any]:
    return {
        "requestedShuffleRows": bool(requested_shuffle_rows),
        "shuffleRows": _effective_ygo_train_eval_shuffle(requested_shuffle_rows),
        "shuffleRowsLocked": True,
        "shuffleRowsLockReason": YGO_TRAIN_EVAL_SHUFFLE_LOCK_REASON,
    }


def _reject_full_direct_training_unless_allowed(*, allow_unsafe_full_direct_training: bool) -> None:
    if not bool(allow_unsafe_full_direct_training):
        raise ValueError(FULL_DIRECT_TRAINING_SUSPENDED_MESSAGE)


def run_ygo_style_pairwise_training(
    *,
    training_rows_path: str | Path | list[str | Path],
    out_dir: str | Path,
    candidate_model_id: str,
    base_model_path: str | Path | None = None,
    epochs: int = YGO_DEFAULT_UPDATE_EPOCHS,
    learning_rate: float = 0.001,
    hidden_dim: int = 64,
    batch_size: int = 256,
    margin: float = 1.0,
    max_margin: float = 4.0,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    shuffle_rows: bool = False,
    training_row_file_weights: list[float] | None = None,
    target_contract: str = ACTION_VALUE_TARGET_CONTRACT,
    device: str = "auto",
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
    allow_missing_play_card_target_semantics: bool = False,
) -> dict[str, Any]:
    restart_safety_review = assert_restart_safety_clear(
        restart_safety_review_path,
        usage_label="pairwise training",
        allow_unreviewed_restart=bool(allow_unreviewed_restart),
    )
    training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
    row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
    rows = _load_weighted_training_rows(training_paths, row_file_weights)
    rows, action_value_semantic_refresh = _refresh_action_value_semantics_for_training(
        rows,
        source_label="pairwise_training_load",
    )
    _reject_full_legal_rows_for_pairwise_training(rows)
    candidate_rows = [
        row
        for row in rows
        if _ygo_pairwise_preference(row) is not None and _ygo_legal_slots(row)
    ]
    usable_rows, target_contract_report = _filter_rows_by_target_contract(
        candidate_rows,
        target_contract=target_contract,
        allow_selected_action_fallback=False,
    )
    if not usable_rows:
        _raise_no_usable_rows(
            mode="pairwise",
            candidate_rows=len(candidate_rows),
            target_contract_report=target_contract_report,
        )
    play_card_target_semantics = play_card_target_semantics_from_rows(usable_rows)
    target_action_semantics = assert_target_action_semantics_safe(usable_rows)

    effective_shuffle_rows = _effective_ygo_train_eval_shuffle(shuffle_rows)
    train_rows, eval_rows = _split_rows(
        usable_rows,
        eval_fraction=float(eval_fraction),
        shuffle=effective_shuffle_rows,
        seed=int(seed),
    )
    if not eval_rows:
        eval_rows = train_rows

    initial_scorer = _load_initial_scorer(base_model_path)
    candidate = train_ygo_style_pairwise_scorer(
        train_rows,
        epochs=int(epochs),
        learning_rate=float(learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        margin=float(margin),
        max_margin=float(max_margin),
        seed=int(seed),
        initial_scorer=initial_scorer,
        device=str(device),
    )
    candidate_eval = _pairwise_eval(candidate, eval_rows)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_path = out_path / "self_improvement_pilot_listwise_scorer_model.json"
    report_path = out_path / "ygo_style_pairwise_training_report.json"

    model_dict = candidate.to_dict()
    model_dict.update(
        {
            "modelId": str(candidate_model_id),
            "trainingMode": YGO_STYLE_PAIRWISE_TRAINING_VERSION,
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "baseModelPath": str(base_model_path) if base_model_path is not None else None,
            "scratchTraining": initial_scorer is None,
            "scratchJustification": (
                "architecture changed from flat/object MLP to ygo-style card/action/global masked policy scorer"
                if initial_scorer is None
                else None
            ),
            "defaultRuntimeChanged": False,
            "activePolicyRequiredForGameplayClaim": True,
            "trainingRowFileWeights": list(row_file_weights),
            "targetContract": str(target_contract),
            "restartSafetyReview": restart_safety_review,
            "allowUnreviewedRestart": bool(allow_unreviewed_restart),
            "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
            "playCardTargetSemantics": play_card_target_semantics,
            "targetActionSemantics": target_action_semantics,
            "actionValueSemanticRefresh": action_value_semantic_refresh,
            "trainingObjective": _training_objective_for_contract(target_contract),
            "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
            "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
            "updateEpochs": int(epochs),
            "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        }
    )
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict[str, Any] = {
        "kind": YGO_STYLE_PAIRWISE_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
        "trainingRowsSource": _current_policy_training_rows_source_value(training_paths),
        "trainingRowFileWeights": list(row_file_weights),
        "trainingRowEffectiveWeightSum": _effective_training_weight_sum(
            usable_rows,
            decision_training_weights=None,
        ),
        "trainingRowEffectiveWeightByDecision": _effective_training_weight_by_decision(
            usable_rows,
            decision_training_weights=None,
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "candidateModelId": str(candidate_model_id),
        "candidateModelPath": str(model_path),
        "reportPath": str(report_path),
        "rowCount": len(rows),
        "usablePairwiseRows": len(usable_rows),
        "targetContract": str(target_contract),
        "targetContractReport": target_contract_report,
        "restartSafetyReview": restart_safety_review,
        "allowUnreviewedRestart": bool(allow_unreviewed_restart),
        "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
        "playCardTargetSemantics": play_card_target_semantics,
        "targetActionSemantics": target_action_semantics,
        "actionValueSemanticRefresh": action_value_semantic_refresh,
        "trainingObjective": _training_objective_for_contract(target_contract),
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "trainRows": len(train_rows),
        "evalRows": len(eval_rows),
        "epochs": int(epochs),
        "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
        "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
        "updateEpochs": int(epochs),
        "learningRate": float(learning_rate),
        "hiddenDim": int(candidate.hiddenDim),
        "batchSize": int(batch_size),
        "margin": float(margin),
        "maxMargin": float(max_margin),
        "seed": int(seed),
        **_shuffle_rows_report_fields(shuffle_rows),
        "featureFamily": YGO_STYLE_FEATURE_FAMILY,
        "objectCardFeaturesUsed": any(isinstance(row.get("cards_"), list) and row.get("cards_") for row in usable_rows),
        "sourceTargetCardRefsUsed": any(_row_has_source_or_target_ref(row) for row in usable_rows),
        "globalFeatureCount": len(candidate.globalFeatureNames),
        "actionFeatureCount": len(candidate.actionFeatureNames),
        "cardFeatureCount": len(candidate.cardFeatureNames),
        "inputDim": int(candidate.inputDim),
        "candidatePairwiseEval": candidate_eval,
        "scratchTraining": initial_scorer is None,
        "scratchJustification": (
            "architecture changed from flat/object MLP to ygo-style card/action/global masked policy scorer"
            if initial_scorer is None
            else None
        ),
        "trainingLaunched": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_ygo_style_action_value_listwise_training(
    *,
    training_rows_path: str | Path | list[str | Path],
    out_dir: str | Path,
    candidate_model_id: str,
    training_row_file_weights: list[float] | None = None,
    base_model_path: str | Path | None = None,
    epochs: int = YGO_DEFAULT_UPDATE_EPOCHS,
    learning_rate: float | None = None,
    hidden_dim: int = 64,
    batch_size: int = 256,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    shuffle_rows: bool = False,
    include_decision_kinds: Iterable[str] | None = None,
    allow_route_isolated_diagnostic_training: bool = False,
    allow_route_limited_launch_training: bool = False,
    decision_training_weights: Mapping[str, float] | None = None,
    anchor_kl_weight: float = 0.0,
    anchor_kl_temperature: float = 1.0,
    anchor_kl_decision_weights: Mapping[str, float] | None = None,
    target_contract: str = ACTION_VALUE_TARGET_CONTRACT,
    action_value_temperature: float = 0.25,
    runtime_aux_score_weight: float | None = None,
    runtime_aux_output_scale: float | None = None,
    runtime_aux_training_objective: str = RUNTIME_AUX_TRAINING_OBJECTIVE_VALUE_DISTRIBUTION,
    preserve_correct_residual_l2_weight: float | None = None,
    preserve_correct_margin_hinge_weight: float | None = None,
    preserve_correct_margin_floor: float | None = None,
    device: str = "auto",
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
    allow_missing_play_card_target_semantics: bool = False,
    allow_scorer_runtime_base_fallback: bool = False,
) -> dict[str, Any]:
    normalized_runtime_aux_training_objective = _normalize_runtime_aux_training_objective(runtime_aux_training_objective)
    if (
        runtime_aux_score_weight is None
        and normalized_runtime_aux_training_objective != RUNTIME_AUX_TRAINING_OBJECTIVE_VALUE_DISTRIBUTION
    ):
        raise ValueError("runtime aux training objective requires --runtime-aux-score-weight")
    restart_safety_review = assert_restart_safety_clear(
        restart_safety_review_path,
        usage_label="action-value listwise training",
        allow_unreviewed_restart=bool(allow_unreviewed_restart),
    )
    training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
    row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
    rows = _load_weighted_training_rows(training_paths, row_file_weights)
    rows, action_value_semantic_refresh = _refresh_action_value_semantics_for_training(
        rows,
        source_label="action_value_listwise_training_load",
    )
    _reject_route_filter_unless_diagnostic(
        include_decision_kinds,
        allow_route_isolated_diagnostic_training=bool(allow_route_isolated_diagnostic_training),
        allow_route_limited_launch_training=bool(allow_route_limited_launch_training),
    )
    rows, training_decision_kind_filter = _filter_rows_by_included_decision_kinds(
        rows,
        include_decision_kinds=include_decision_kinds,
    )
    route_isolated_training = bool(training_decision_kind_filter.get("enabled"))
    route_limited_launch_training = bool(route_isolated_training and allow_route_limited_launch_training)
    route_isolated_diagnostic_training = bool(
        route_isolated_training and not route_limited_launch_training
    )
    candidate_rows = [
        row
        for row in rows
        if _row_has_explicit_action_value_row(row)
        or _ygo_row_has_action_value_distribution_target(row)
    ]
    usable_rows, target_contract_report = _filter_rows_by_target_contract(
        candidate_rows,
        target_contract=target_contract,
        allow_selected_action_fallback=False,
    )
    if not usable_rows:
        _raise_no_usable_rows(
            mode="action-value-listwise",
            candidate_rows=len(candidate_rows),
            target_contract_report=target_contract_report,
        )
    runtime_calibrated_sidecar_training = runtime_aux_score_weight is not None
    resolved_learning_rate, learning_rate_source = _resolve_action_value_listwise_learning_rate(
        learning_rate,
        runtime_calibrated_sidecar_training=runtime_calibrated_sidecar_training,
    )
    runtime_row_total_contract_report: dict[str, Any] | None = None
    if runtime_calibrated_sidecar_training:
        if bool(allow_scorer_runtime_base_fallback):
            runtime_row_total_contract_report = _runtime_row_total_contract_report(
                usable_rows,
                contract="row_runtime_total_optional",
            )
        else:
            usable_rows, runtime_row_total_contract_report = _filter_rows_by_runtime_row_total_contract(usable_rows)
            if not usable_rows:
                raise ValueError(
                    "runtime-calibrated action-value listwise training found no rows with row runtime total; "
                    f"contract={runtime_row_total_contract_report}"
                )
    play_card_target_semantics = play_card_target_semantics_from_rows(usable_rows)
    target_action_semantics = assert_target_action_semantics_safe(usable_rows)

    effective_shuffle_rows = _effective_ygo_train_eval_shuffle(shuffle_rows)
    train_rows, eval_rows = _split_rows_by_state_group(
        usable_rows,
        eval_fraction=float(eval_fraction),
        shuffle=effective_shuffle_rows,
        seed=int(seed),
    )
    if not eval_rows:
        eval_rows = train_rows

    initial_scorer = _load_initial_scorer(base_model_path)
    if runtime_calibrated_sidecar_training and initial_scorer is None:
        raise ValueError("runtime-calibrated action-value listwise training requires --base-model-path")
    bounded_runtime_aux_score_weight = (
        float(runtime_aux_score_weight)
        if runtime_aux_score_weight is not None
        else None
    )
    if bounded_runtime_aux_score_weight is not None and bounded_runtime_aux_score_weight <= 0.0:
        raise ValueError("runtime_aux_score_weight must be positive")
    bounded_runtime_aux_output_scale = resolve_runtime_aux_output_scale(
        runtime_aux_output_scale,
        runtime_aux_score_weight=bounded_runtime_aux_score_weight,
    )
    if runtime_aux_output_scale is not None and float(runtime_aux_output_scale) <= 0.0:
        raise ValueError("runtime_aux_output_scale must be positive")
    if not runtime_calibrated_sidecar_training and abs(float(bounded_runtime_aux_output_scale) - 1.0) > 1.0e-12:
        raise ValueError("runtime_aux_output_scale requires runtime_aux_score_weight")
    normalized_decision_training_weights = _normalized_anchor_kl_decision_weights(decision_training_weights)
    bounded_anchor_kl_weight = max(0.0, float(anchor_kl_weight))
    bounded_anchor_kl_temperature = max(1.0e-6, float(anchor_kl_temperature))
    normalized_anchor_kl_decision_weights = _normalized_anchor_kl_decision_weights(anchor_kl_decision_weights)
    if bounded_anchor_kl_weight > 0.0 and initial_scorer is None:
        raise ValueError("action-value listwise anchor KL requires --base-model-path")
    candidate = train_ygo_style_action_value_distribution_scorer(
        train_rows,
        epochs=int(epochs),
        learning_rate=float(resolved_learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        seed=int(seed),
        initial_scorer=initial_scorer,
        decision_training_weights=normalized_decision_training_weights,
        anchor_kl_weight=bounded_anchor_kl_weight,
        anchor_kl_temperature=bounded_anchor_kl_temperature,
        anchor_kl_decision_weights=normalized_anchor_kl_decision_weights,
        action_value_temperature=float(action_value_temperature),
        runtime_base_scorer=initial_scorer if runtime_calibrated_sidecar_training else None,
        runtime_aux_score_weight=bounded_runtime_aux_score_weight,
        runtime_aux_output_scale=bounded_runtime_aux_output_scale,
        runtime_aux_training_objective=normalized_runtime_aux_training_objective,
        preserve_correct_residual_l2_weight=preserve_correct_residual_l2_weight,
        preserve_correct_margin_hinge_weight=preserve_correct_margin_hinge_weight,
        preserve_correct_margin_floor=preserve_correct_margin_floor,
        require_row_runtime_total=not bool(allow_scorer_runtime_base_fallback),
        require_runtime_policy_provenance=(
            bool(runtime_calibrated_sidecar_training)
            and not bool(allow_scorer_runtime_base_fallback)
        ),
        device=str(device),
    )
    candidate_eval = _action_value_listwise_eval(
        candidate,
        eval_rows,
        runtime_base_scorer=initial_scorer if runtime_calibrated_sidecar_training else None,
        runtime_aux_score_weight=bounded_runtime_aux_score_weight,
    )
    base_eval = (
        _runtime_base_action_value_listwise_eval(eval_rows, fallback_base_scorer=initial_scorer)
        if runtime_calibrated_sidecar_training and initial_scorer is not None
        else None
    )
    candidate_eval_delta_vs_base = (
        _action_value_listwise_eval_delta(candidate_eval, base_eval)
        if base_eval is not None
        else None
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_path = out_path / "self_improvement_pilot_listwise_scorer_model.json"
    report_path = out_path / "ygo_style_action_value_listwise_training_report.json"
    training_objective = (
        _runtime_action_value_training_objective(normalized_runtime_aux_training_objective)
        if runtime_calibrated_sidecar_training
        else "full_legal_action_set_value_distribution"
    )
    sidecar_initialization = (
        "zero_residual_output_head"
        if runtime_calibrated_sidecar_training
        else ("warm_start_from_base_policy" if initial_scorer is not None else "scratch_random")
    )
    runtime_aux_training_diagnostics = dict(getattr(candidate, "runtimeAuxTrainingDiagnostics", {}) or {})
    training_runtime_source_groups = dict(runtime_aux_training_diagnostics.get("runtimeBaseScoreSourceGroups") or {})
    actual_preserve_residual_l2_weight = float(
        runtime_aux_training_diagnostics.get("preserveCorrectResidualL2Weight", 0.0) or 0.0
    )
    actual_preserve_margin_hinge_weight = float(
        runtime_aux_training_diagnostics.get("preserveCorrectMarginHingeWeight", 0.0) or 0.0
    )
    actual_preserve_margin_floor = float(
        runtime_aux_training_diagnostics.get("preserveCorrectMarginFloor", 0.0) or 0.0
    )

    model_dict = candidate.to_dict()
    model_dict.update(
        {
            "modelId": str(candidate_model_id),
            "trainingMode": YGO_STYLE_ACTION_VALUE_LISTWISE_TRAINING_VERSION,
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "baseModelPath": str(base_model_path) if base_model_path is not None else None,
            "scratchTraining": initial_scorer is None,
            "scratchJustification": (
                "architecture changed from flat/object MLP to ygo-style card/action/global masked action-value sidecar"
                if initial_scorer is None
                else None
            ),
            "defaultRuntimeChanged": False,
            "activePolicyRequiredForGameplayClaim": True,
            "trainingRowFileWeights": list(row_file_weights),
            "sidecarListwiseTraining": True,
            "fullDirectPolicyTraining": False,
            "directPolicyRuntimeAuthority": False,
            "scoringTopology": YGO_SCORING_TOPOLOGY_UNIFIED_FULL_LEGAL,
            "routeSpecificScoring": False,
            "routeSpecificHeads": False,
            "routeIsolatedTrainingDiagnosticOnly": bool(route_isolated_diagnostic_training),
            "routeLimitedLaunchTraining": bool(route_limited_launch_training),
            "allowRouteIsolatedDiagnosticTraining": bool(allow_route_isolated_diagnostic_training),
            "allowRouteLimitedLaunchTraining": bool(allow_route_limited_launch_training),
            "decisionTrainingWeights": dict(normalized_decision_training_weights),
            "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
            "anchorKlWeight": float(bounded_anchor_kl_weight),
            "anchorKlTemperature": float(bounded_anchor_kl_temperature),
            "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
            "allowSelectedActionFallback": False,
            "directPolicyTargetMode": ACTION_VALUE_DISTRIBUTION_SIDECAR_TARGET_MODE,
            "actionValueTemperature": float(action_value_temperature),
            "fullLegalActionSetTraining": True,
            "runtimeCalibratedSidecarTraining": bool(runtime_calibrated_sidecar_training),
            "runtimeAuxScoreWeight": bounded_runtime_aux_score_weight,
            "runtimeAuxOutputScale": float(bounded_runtime_aux_output_scale),
            "runtimeAuxTrainingObjective": normalized_runtime_aux_training_objective,
            "runtimeAuxPreserveCorrectResidualL2Weight": actual_preserve_residual_l2_weight,
            "runtimeAuxPreserveCorrectMarginHingeWeight": actual_preserve_margin_hinge_weight,
            "runtimeAuxPreserveCorrectMarginFloor": actual_preserve_margin_floor,
            "runtimeAuxTrainingDiagnostics": runtime_aux_training_diagnostics,
            "runtimeTrainingBaseScoreSource": _runtime_base_score_source_summary(
                row_runtime_base_groups=int(training_runtime_source_groups.get("rowRuntimeTotal", 0) or 0),
                scorer_runtime_base_groups=int(training_runtime_source_groups.get("scorerRuntimeBase", 0) or 0),
            ),
            "runtimeTrainingBaseScoreSourceGroups": training_runtime_source_groups,
            "runtimeBaseScoreSource": candidate_eval.get("runtimeBaseScoreSource"),
            "sidecarInitialization": sidecar_initialization,
            "targetContract": str(target_contract),
            "restartSafetyReview": restart_safety_review,
            "allowUnreviewedRestart": bool(allow_unreviewed_restart),
            "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
            "playCardTargetSemantics": play_card_target_semantics,
            "targetActionSemantics": target_action_semantics,
            "actionValueSemanticRefresh": action_value_semantic_refresh,
            "trainingDecisionKindFilter": training_decision_kind_filter,
            "runtimeRowTotalContractReport": runtime_row_total_contract_report,
            "allowScorerRuntimeBaseFallback": bool(allow_scorer_runtime_base_fallback),
            "trainingObjective": training_objective,
            "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
            "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
            "updateEpochs": int(epochs),
            "learningRateSource": learning_rate_source,
            "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        }
    )
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict[str, Any] = {
        "kind": YGO_STYLE_ACTION_VALUE_LISTWISE_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
        "trainingRowsSource": _training_rows_source_value(training_paths),
        "trainingRowFileWeights": list(row_file_weights),
        "trainingRowEffectiveWeightSum": _effective_training_weight_sum(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "trainingRowEffectiveWeightByDecision": _effective_training_weight_by_decision(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "candidateModelId": str(candidate_model_id),
        "candidateModelPath": str(model_path),
        "reportPath": str(report_path),
        "rowCount": len(rows),
        "usableActionValueRows": len(usable_rows),
        "usableActionValueStateGroups": _action_value_listwise_group_count(usable_rows),
        "targetContract": str(target_contract),
        "targetContractReport": target_contract_report,
        "restartSafetyReview": restart_safety_review,
        "allowUnreviewedRestart": bool(allow_unreviewed_restart),
        "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
        "playCardTargetSemantics": play_card_target_semantics,
        "targetActionSemantics": target_action_semantics,
        "actionValueSemanticRefresh": action_value_semantic_refresh,
        "trainingDecisionKindFilter": training_decision_kind_filter,
        "runtimeRowTotalContractReport": runtime_row_total_contract_report,
        "allowScorerRuntimeBaseFallback": bool(allow_scorer_runtime_base_fallback),
        "trainingObjective": training_objective,
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "trainRows": len(train_rows),
        "evalRows": len(eval_rows),
        "trainStateGroups": _action_value_listwise_group_count(train_rows),
        "evalStateGroups": _action_value_listwise_group_count(eval_rows),
        "epochs": int(epochs),
        "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
        "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
        "updateEpochs": int(epochs),
        "learningRate": float(resolved_learning_rate),
        "learningRateSource": learning_rate_source,
        "hiddenDim": int(candidate.hiddenDim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        **_shuffle_rows_report_fields(shuffle_rows),
        "featureFamily": YGO_STYLE_FEATURE_FAMILY,
        "objectCardFeaturesUsed": any(isinstance(row.get("cards_"), list) and row.get("cards_") for row in usable_rows),
        "sourceTargetCardRefsUsed": any(_row_has_source_or_target_ref(row) for row in usable_rows),
        "globalFeatureCount": len(candidate.globalFeatureNames),
        "actionFeatureCount": len(candidate.actionFeatureNames),
        "cardFeatureCount": len(candidate.cardFeatureNames),
        "inputDim": int(candidate.inputDim),
        "candidateActionValueListwiseEval": candidate_eval,
        "baseActionValueListwiseEval": base_eval,
        "candidateActionValueListwiseEvalDeltaVsBase": candidate_eval_delta_vs_base,
        "scratchTraining": initial_scorer is None,
        "scratchJustification": (
            "architecture changed from flat/object MLP to ygo-style card/action/global masked action-value sidecar"
            if initial_scorer is None
            else None
        ),
        "sidecarListwiseTraining": True,
        "fullDirectPolicyTraining": False,
        "directPolicyRuntimeAuthority": False,
        "scoringTopology": YGO_SCORING_TOPOLOGY_UNIFIED_FULL_LEGAL,
        "routeSpecificScoring": False,
        "routeSpecificHeads": False,
        "routeIsolatedTrainingDiagnosticOnly": bool(route_isolated_diagnostic_training),
        "routeLimitedLaunchTraining": bool(route_limited_launch_training),
        "allowRouteIsolatedDiagnosticTraining": bool(allow_route_isolated_diagnostic_training),
        "allowRouteLimitedLaunchTraining": bool(allow_route_limited_launch_training),
        "decisionTrainingWeights": dict(normalized_decision_training_weights),
        "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
        "anchorKlWeight": float(bounded_anchor_kl_weight),
        "anchorKlTemperature": float(bounded_anchor_kl_temperature),
        "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
        "allowSelectedActionFallback": False,
        "directPolicyTargetMode": ACTION_VALUE_DISTRIBUTION_SIDECAR_TARGET_MODE,
        "actionValueTemperature": float(action_value_temperature),
        "fullLegalActionSetTraining": True,
        "runtimeCalibratedSidecarTraining": bool(runtime_calibrated_sidecar_training),
        "runtimeAuxScoreWeight": bounded_runtime_aux_score_weight,
        "runtimeAuxOutputScale": float(bounded_runtime_aux_output_scale),
        "runtimeAuxTrainingObjective": normalized_runtime_aux_training_objective,
        "runtimeAuxPreserveCorrectResidualL2Weight": actual_preserve_residual_l2_weight,
        "runtimeAuxPreserveCorrectMarginHingeWeight": actual_preserve_margin_hinge_weight,
        "runtimeAuxPreserveCorrectMarginFloor": actual_preserve_margin_floor,
        "runtimeAuxTrainingDiagnostics": runtime_aux_training_diagnostics,
        "runtimeTrainingBaseScoreSource": _runtime_base_score_source_summary(
            row_runtime_base_groups=int(training_runtime_source_groups.get("rowRuntimeTotal", 0) or 0),
            scorer_runtime_base_groups=int(training_runtime_source_groups.get("scorerRuntimeBase", 0) or 0),
        ),
        "runtimeTrainingBaseScoreSourceGroups": training_runtime_source_groups,
        "runtimeBaseScoreSource": candidate_eval.get("runtimeBaseScoreSource"),
        "sidecarInitialization": sidecar_initialization,
        "trainingLaunched": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_ygo_style_sandbox_policy_value_training(
    *,
    training_rows_path: str | Path | list[str | Path],
    out_dir: str | Path,
    candidate_model_id: str,
    training_row_file_weights: list[float] | None = None,
    base_model_path: str | Path | None = None,
    epochs: int = YGO_DEFAULT_UPDATE_EPOCHS,
    learning_rate: float = 0.001,
    hidden_dim: int = 64,
    batch_size: int = 256,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    shuffle_rows: bool = False,
    decision_training_weights: Mapping[str, float] | None = None,
    policy_temperature: float = 0.5,
    policy_target_source: str = POLICY_VALUE_TARGET_SOURCE_ACTION_VALUE,
    value_loss_weight: float = 0.25,
    high_gap_ranking_weight: float = 0.25,
    high_gap_threshold: float = DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
    anchor_kl_weight: float = 0.0,
    anchor_kl_temperature: float = 1.0,
    anchor_kl_source: str = "initial_scorer",
    device: str = "auto",
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
    allow_missing_play_card_target_semantics: bool = False,
) -> dict[str, Any]:
    restart_safety_review = assert_restart_safety_clear(
        restart_safety_review_path,
        usage_label="sandbox policy/value training",
        allow_unreviewed_restart=bool(allow_unreviewed_restart),
    )
    training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
    row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
    rows = _load_weighted_training_rows(training_paths, row_file_weights)
    rows, action_value_semantic_refresh = _refresh_action_value_semantics_for_training(
        rows,
        source_label="sandbox_policy_value_training_load",
    )
    candidate_rows = [
        row
        for row in rows
        if _row_is_full_legal_action_value_group(row)
        and str(row.get("schema") or "") == "snapshot_branch_full_legal_action_value_rows_v1"
    ]
    usable_rows, target_contract_report = _filter_rows_by_target_contract(
        candidate_rows,
        target_contract=ACTION_VALUE_TARGET_CONTRACT,
        allow_selected_action_fallback=False,
    )
    if not usable_rows:
        _raise_no_usable_rows(
            mode="sandbox-policy-value",
            candidate_rows=len(candidate_rows),
            target_contract_report=target_contract_report,
        )
    play_card_target_semantics = assert_play_card_target_semantics_safe(
        usable_rows,
        allow_missing_target_semantics=bool(allow_missing_play_card_target_semantics),
    )
    target_action_semantics = assert_target_action_semantics_safe(usable_rows)
    effective_shuffle_rows = _effective_ygo_train_eval_shuffle(shuffle_rows)
    train_rows, eval_rows = _split_rows_by_state_group(
        usable_rows,
        eval_fraction=float(eval_fraction),
        shuffle=effective_shuffle_rows,
        seed=int(seed),
    )
    if not eval_rows:
        eval_rows = train_rows

    initial_scorer = _load_initial_scorer(base_model_path)
    base_model_id = _model_id_from_json(base_model_path)
    candidate = train_ygo_style_full_legal_policy_value_scorer(
        train_rows,
        epochs=int(epochs),
        learning_rate=float(learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        seed=int(seed),
        initial_scorer=initial_scorer,
        policy_temperature=float(policy_temperature),
        policy_target_source=str(policy_target_source),
        value_loss_weight=float(value_loss_weight),
        high_gap_ranking_weight=float(high_gap_ranking_weight),
        high_gap_threshold=float(high_gap_threshold),
        anchor_kl_weight=float(anchor_kl_weight),
        anchor_kl_temperature=float(anchor_kl_temperature),
        anchor_kl_source=str(anchor_kl_source),
        decision_training_weights=decision_training_weights,
        device=str(device),
    )
    candidate_eval = evaluate_ygo_style_full_legal_policy_value_scorer(
        candidate,
        eval_rows,
        policy_temperature=float(policy_temperature),
        policy_target_source=str(policy_target_source),
    )
    candidate_train_eval = evaluate_ygo_style_full_legal_policy_value_scorer(
        candidate,
        train_rows,
        policy_temperature=float(policy_temperature),
        policy_target_source=str(policy_target_source),
    )
    base_train_eval = (
        evaluate_ygo_style_full_legal_policy_value_scorer(
            initial_scorer,
            train_rows,
            policy_temperature=float(policy_temperature),
            policy_target_source=str(policy_target_source),
        )
        if initial_scorer is not None
        else None
    )
    base_eval = (
        evaluate_ygo_style_full_legal_policy_value_scorer(
            initial_scorer,
            eval_rows,
            policy_temperature=float(policy_temperature),
            policy_target_source=str(policy_target_source),
        )
        if initial_scorer is not None
        else None
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_path = out_path / "self_improvement_pilot_sandbox_policy_value_model.json"
    report_path = out_path / "ygo_style_sandbox_policy_value_training_report.json"
    sandbox_diagnostics = dict(getattr(candidate, "runtimeAuxTrainingDiagnostics", {}) or {})
    model_dict = candidate.to_dict()
    for stale_key in (
        "runtimeAuxTrainingObjective",
        "runtimeAuxTrainingDiagnostics",
        "runtimeAuxOutputScale",
        "runtimeCalibratedSidecarTraining",
        "centerLegalSidecarScores",
    ):
        model_dict.pop(stale_key, None)
    model_dict.update(
        {
            "modelId": str(candidate_model_id),
            "trainingMode": YGO_STYLE_SANDBOX_POLICY_VALUE_TRAINING_VERSION,
            "trainingReportPath": str(report_path),
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "baseModelPath": str(base_model_path) if base_model_path is not None else None,
            "baseModelId": base_model_id,
            "scratchTraining": initial_scorer is None,
            "scratchJustification": (
                "sandbox actor/value sanity experiment; not a runtime baseline or gate candidate"
                if initial_scorer is None
                else None
            ),
            "defaultRuntimeChanged": False,
            "activePolicyRequiredForGameplayClaim": False,
            "gateEligible": False,
            "sandboxOnly": True,
            "unifiedMaskedActorValueTraining": True,
            "fullLegalActionSetTraining": True,
            "trainingObjective": "sandbox_full_legal_policy_value",
            "policyTarget": (
                "softmax(row_runtime_total)"
                if str(policy_target_source) == POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_TOTAL
                else "argmax(row_runtime_total)"
                if str(policy_target_source) == POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_ARGMAX
                else "one_hot(selectedActionSlot)"
                if str(policy_target_source) == POLICY_VALUE_TARGET_SOURCE_SELECTED_ACTION_SLOT
                else "softmax(action_value / temperature)"
            ),
            "policyTargetSource": str(policy_target_source),
            "stateValueTarget": "soft_policy_expected_action_value",
            "sidecarListwiseTraining": False,
            "runtimeCalibratedSidecarTraining": False,
            "fullDirectPolicyTraining": False,
            "directPolicyRuntimeAuthority": False,
            "selectedActionImitation": False,
            "directPolicyTargetMode": SANDBOX_FULL_LEGAL_POLICY_VALUE_TARGET_MODE,
            "sandboxTrainingDiagnostics": sandbox_diagnostics,
            "policyTemperature": float(policy_temperature),
            "valueLossWeight": float(value_loss_weight),
            "highGapRankingWeight": float(high_gap_ranking_weight),
            "highGapThreshold": float(high_gap_threshold),
            "policyAnchorKlTraining": bool(
                sandbox_diagnostics.get(
                    "policyAnchorKlTraining",
                    bool(anchor_kl_weight > 0.0 and initial_scorer is not None),
                )
            ),
            "anchorKlWeight": float(anchor_kl_weight),
            "anchorKlTemperature": float(anchor_kl_temperature),
            "anchorKlSource": str(anchor_kl_source),
            "restartSafetyReview": restart_safety_review,
            "allowUnreviewedRestart": bool(allow_unreviewed_restart),
            "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
            "playCardTargetSemantics": play_card_target_semantics,
            "targetActionSemantics": target_action_semantics,
            "actionValueSemanticRefresh": action_value_semantic_refresh,
            "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
            "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
            "updateEpochs": int(epochs),
            "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        }
    )
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict[str, Any] = {
        "kind": YGO_STYLE_SANDBOX_POLICY_VALUE_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
        "trainingRowsSource": _training_rows_source_value(training_paths),
        "trainingRowFileWeights": list(row_file_weights),
        "trainingRowEffectiveWeightSum": _effective_training_weight_sum(
            usable_rows,
            decision_training_weights=decision_training_weights,
        ),
        "trainingRowEffectiveWeightByDecision": _effective_training_weight_by_decision(
            usable_rows,
            decision_training_weights=decision_training_weights,
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "baseModelId": base_model_id,
        "candidateModelId": str(candidate_model_id),
        "candidateModelPath": str(model_path),
        "reportPath": str(report_path),
        "rowCount": len(rows),
        "candidateFullLegalRows": len(candidate_rows),
        "usableFullLegalRows": len(usable_rows),
        "targetContract": ACTION_VALUE_TARGET_CONTRACT,
        "targetContractReport": target_contract_report,
        "restartSafetyReview": restart_safety_review,
        "allowUnreviewedRestart": bool(allow_unreviewed_restart),
        "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
        "playCardTargetSemantics": play_card_target_semantics,
        "targetActionSemantics": target_action_semantics,
        "actionValueSemanticRefresh": action_value_semantic_refresh,
        "trainRows": len(train_rows),
        "evalRows": len(eval_rows),
        "epochs": int(epochs),
        "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
        "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
        "updateEpochs": int(epochs),
        "learningRate": float(learning_rate),
        "hiddenDim": int(candidate.hiddenDim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        **_shuffle_rows_report_fields(shuffle_rows),
        "featureFamily": YGO_STYLE_FEATURE_FAMILY,
        "objectCardFeaturesUsed": any(isinstance(row.get("cards_"), list) and row.get("cards_") for row in usable_rows),
        "sourceTargetCardRefsUsed": any(_row_has_source_or_target_ref(row) for row in usable_rows),
        "globalFeatureCount": len(candidate.globalFeatureNames),
        "actionFeatureCount": len(candidate.actionFeatureNames),
        "cardFeatureCount": len(candidate.cardFeatureNames),
        "inputDim": int(candidate.inputDim),
        "candidateSandboxPolicyValueTrainEval": candidate_train_eval,
        "candidateSandboxPolicyValueEval": candidate_eval,
        "baseSandboxPolicyValueTrainEval": base_train_eval,
        "baseSandboxPolicyValueEval": base_eval,
        "sandboxTrainingDiagnostics": sandbox_diagnostics,
        "sandboxOnly": True,
        "gateEligible": False,
        "unifiedMaskedActorValueTraining": True,
        "fullLegalActionSetTraining": True,
        "trainingObjective": "sandbox_full_legal_policy_value",
        "policyTarget": (
            "softmax(row_runtime_total)"
            if str(policy_target_source) == POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_TOTAL
            else "argmax(row_runtime_total)"
            if str(policy_target_source) == POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_ARGMAX
            else "one_hot(selectedActionSlot)"
            if str(policy_target_source) == POLICY_VALUE_TARGET_SOURCE_SELECTED_ACTION_SLOT
            else "softmax(action_value / temperature)"
        ),
        "policyTargetSource": str(policy_target_source),
        "stateValueTarget": "soft_policy_expected_action_value",
        "sidecarListwiseTraining": False,
        "runtimeCalibratedSidecarTraining": False,
        "fullDirectPolicyTraining": False,
        "directPolicyRuntimeAuthority": False,
        "selectedActionImitation": False,
        "directPolicyTargetMode": SANDBOX_FULL_LEGAL_POLICY_VALUE_TARGET_MODE,
        "policyTemperature": float(policy_temperature),
        "valueLossWeight": float(value_loss_weight),
        "highGapRankingWeight": float(high_gap_ranking_weight),
        "highGapThreshold": float(high_gap_threshold),
        "policyAnchorKlTraining": bool(
            sandbox_diagnostics.get(
                "policyAnchorKlTraining",
                bool(anchor_kl_weight > 0.0 and initial_scorer is not None),
            )
        ),
        "anchorKlWeight": float(anchor_kl_weight),
        "anchorKlTemperature": float(anchor_kl_temperature),
        "anchorKlSource": str(anchor_kl_source),
        "scratchTraining": initial_scorer is None,
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "trainingLaunched": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _current_policy_training_gate_eligibility(
    *,
    row_contract_report: Mapping[str, Any],
    sandbox_report: Mapping[str, Any],
) -> dict[str, Any]:
    blocking_reasons: list[str] = []

    accepted_rows = int(row_contract_report.get("acceptedRows") or 0)
    rejected_rows = int(row_contract_report.get("rejectedRows") or 0)
    if accepted_rows < DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS:
        blocking_reasons.append("insufficient_current_policy_training_rows")
    if rejected_rows != 0:
        blocking_reasons.append("current_policy_row_contract_rejected_rows")
    if bool(sandbox_report.get("scratchTraining")):
        blocking_reasons.append("scratch_training")
    sampled_eval_report = sandbox_report.get("candidateCurrentPolicySampledAdvantageEval")
    if not isinstance(sampled_eval_report, Mapping):
        sampled_eval_report = {}
        blocking_reasons.append("missing_candidate_sampled_advantage_eval")
    sampled_eval_rows = int(sampled_eval_report.get("total") or 0)
    if sampled_eval_rows <= 0:
        blocking_reasons.append("empty_candidate_sampled_advantage_eval")
    sampled_direction_accuracy = _finite_float_or_none(sampled_eval_report.get("directionAccuracy"))
    if sampled_direction_accuracy is None:
        blocking_reasons.append("missing_candidate_sampled_advantage_direction_accuracy")

    eval_groups = int(sampled_eval_rows)
    expected_lift = None
    argmax_lift = None
    base_expected_lift = None
    base_argmax_lift = None
    expected_delta = None
    argmax_delta = None
    route_argmax_deltas: dict[str, float | None] = {}

    return {
        "kind": "current_policy_training_gate_eligibility_v1",
        "gateEligible": not blocking_reasons,
        "fullDirectPolicyTraining": True,
        "blockingReasons": blocking_reasons,
        "acceptedRows": accepted_rows,
        "rejectedRows": rejected_rows,
        "minAcceptedRows": DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS,
        "evalGroups": eval_groups,
        "minEvalGroups": DEFAULT_CURRENT_POLICY_MIN_EVAL_GROUPS,
        "expectedActionValueLiftVsUniform": expected_lift,
        "argmaxActionValueLiftVsUniform": argmax_lift,
        "baseExpectedActionValueLiftVsUniform": base_expected_lift,
        "baseArgmaxActionValueLiftVsUniform": base_argmax_lift,
        "expectedActionValueLiftDeltaVsBase": expected_delta,
        "argmaxActionValueLiftDeltaVsBase": argmax_delta,
        "routeArgmaxActionValueDeltasVsBase": route_argmax_deltas,
        "minActionValueLift": DEFAULT_CURRENT_POLICY_MIN_EXPECTED_ACTION_VALUE_LIFT,
        "actionValueEvalDiagnosticsOnly": True,
        "sampledAdvantageEvalRows": int(sampled_eval_rows),
        "sampledAdvantageDirectionAccuracy": sampled_direction_accuracy,
        "trajectoryPolicyEvalOnly": True,
    }


def _current_policy_clone_gate_eligibility(
    *,
    row_contract_report: Mapping[str, Any],
    sandbox_report: Mapping[str, Any],
) -> dict[str, Any]:
    blocking_reasons: list[str] = []
    accepted_rows = int(row_contract_report.get("acceptedRows") or 0)
    rejected_rows = int(row_contract_report.get("rejectedRows") or 0)
    if accepted_rows < DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS:
        blocking_reasons.append("insufficient_current_policy_training_rows")
    if rejected_rows != 0:
        blocking_reasons.append("current_policy_row_contract_rejected_rows")
    eval_report = sandbox_report.get("candidateSandboxPolicyValueEval")
    if not isinstance(eval_report, Mapping):
        eval_report = {}
        blocking_reasons.append("missing_candidate_runtime_score_distill_eval")
    eval_groups = int(eval_report.get("groups") or 0)
    if eval_groups < DEFAULT_CURRENT_POLICY_MIN_EVAL_GROUPS:
        blocking_reasons.append("insufficient_current_policy_eval_groups")
    distill_top1 = _finite_float_or_none(eval_report.get("top1Accuracy"))
    if distill_top1 is None:
        blocking_reasons.append("missing_runtime_score_distill_top1_accuracy")
    elif distill_top1 < DEFAULT_CURRENT_POLICY_MIN_CLONE_TOP1_ACCURACY:
        blocking_reasons.append("low_runtime_score_distill_top1_accuracy")
    return {
        "kind": "current_policy_runtime_score_distill_gate_eligibility_v1",
        "gateEligible": not blocking_reasons,
        "fullDirectPolicyTraining": True,
        "behaviorCloneTraining": False,
        "runtimeScoreDistillTraining": True,
        "blockingReasons": blocking_reasons,
        "acceptedRows": accepted_rows,
        "rejectedRows": rejected_rows,
        "minAcceptedRows": DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS,
        "evalGroups": eval_groups,
        "minEvalGroups": DEFAULT_CURRENT_POLICY_MIN_EVAL_GROUPS,
        "runtimeScoreDistillTop1Accuracy": distill_top1,
        "minRuntimeScoreDistillTop1Accuracy": DEFAULT_CURRENT_POLICY_MIN_CLONE_TOP1_ACCURACY,
    }


def _finite_float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def run_ygo_style_current_policy_training(
    *,
    training_rows_path: str | Path | list[str | Path] | None = None,
    training_rows: Iterable[Mapping[str, Any]] | None = None,
    out_dir: str | Path,
    actor_policy_id: str,
    candidate_policy_id: str | None = None,
    training_row_file_weights: list[float] | None = None,
    base_model_path: str | Path | None = None,
    update_epochs: int = 1,
    learning_rate: float = 0.001,
    hidden_dim: int = 64,
    batch_size: int = 32,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    decision_training_weights: Mapping[str, float] | None = None,
    policy_temperature: float = 0.5,
    ppo_clip_coef: float = 0.2,
    value_loss_weight: float = 0.25,
    high_gap_ranking_weight: float = 0.25,
    high_gap_threshold: float = DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
    anchor_kl_weight: float = 0.0,
    anchor_kl_temperature: float = 1.0,
    retention_kl_mode: str = "disabled",
    domain_gradient_conflict_mode: str = "disabled",
    multi_domain_objective_mode: str = "disabled",
    recurrent_training_mode: str = "disabled",
    decision_residual_policy_mode: str = "disabled",
    state_action_interaction_mode: str = "disabled",
    state_action_interaction_rank: int = 16,
    state_action_interaction_init_scale: float = 0.01,
    state_action_interaction_lr_multiplier: float = 1.0,
    actor_base_lr_multiplier: float = 1.0,
    actor_update_requires_trusted_value: bool = False,
    actor_trusted_value_ev_threshold: float = 0.0,
    selfplay_actor_loss_cap_fraction: float = 1.0,
    original_terminal_actor_loss_min_fraction: float = 0.0,
    actor_loss_max_rows_per_domain: int = 0,
    actor_loss_sign_balance_mode: str = "disabled",
    actor_loss_sequential_sign_steps: bool = False,
    actor_loss_sequential_sign_order: str = "alternating",
    actor_loss_min_abs_advantage: float = 0.0,
    actor_loss_advantage_sign_filter: str = "disabled",
    actor_loss_label_consistency_mode: str = "disabled",
    actor_loss_label_consistency_min_abs_advantage: float = 0.0,
    actor_loss_counter_signal_conflict_weight: float = 1.0,
    actor_advantage_source: str = "gae",
    q_backed_actor_residual_transfer_mode: str = "disabled",
    action_q_residual_loss_weight: float = 1.0,
    action_q_target_ab_diagnostic_cache_path: str | Path | None = None,
    actor_loss_relative_mode: str = "selected_logprob",
    actor_loss_group_mode: str = "disabled",
    actor_legal_margin_weight: float = 0.0,
    actor_signature_drift_penalty_weight: float = 0.0,
    actor_signature_contrastive_weight: float = 0.0,
    actor_gradient_collision_audit_mode: str = "disabled",
    functional_logit_oracle_mode: str = "disabled",
    actor_linearized_representability_mode: str = "disabled",
    actor_linearized_cg_max_iterations: int = 64,
    actor_linearized_optimizer_diagnostics: str = "full",
    learner_diagnostics_mode: str | None = None,
    terminal_untrusted_actor_loss_max_steps_from_terminal: int = -1,
    entropy_coef: float = YGO_CURRENT_POLICY_ENTROPY_COEF,
    current_policy_actor_advantage_mode: str = "gae",
    current_policy_local_step_reward_weight: float = 0.0,
    detach_value_loss_recurrent_context: bool = False,
    critic_warmup_epochs: int | None = None,
    critic_warmup_recompute_advantage: bool = True,
    require_old_policy_values: bool = False,
    normalize_advantages: bool = False,
    advantage_normalization_mode: str = "scale_only",
    device: str = "auto",
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
    allow_missing_play_card_target_semantics: bool = False,
    max_training_rows: int | None = DEFAULT_MAX_CURRENT_POLICY_TRAINING_ROWS,
    post_training_diagnostics: str = "full",
    row_contract_mode: str = "full",
    allow_multi_epoch_current_policy_update: bool = False,
    allow_unpromoted_source_actor: bool = False,
) -> dict[str, Any]:
    actor_id = str(actor_policy_id or "").strip()
    if not actor_id:
        raise ValueError("current-policy training requires actor_policy_id")
    _assert_not_retired_actor0_policy_id(actor_id, context="current-policy training actor_policy_id")
    normalized_actor_advantage_source = str(actor_advantage_source or "gae").strip().lower()
    normalized_current_policy_actor_advantage_mode = str(
        current_policy_actor_advantage_mode or "gae"
    ).strip().lower()
    zero_epoch_learner_vtrace_dry_run = (
        int(update_epochs) == 0
        and normalized_current_policy_actor_advantage_mode == "learner_vtrace"
    )
    zero_epoch_q_backed_projection_diagnostic = (
        int(update_epochs) == 0
        and normalized_actor_advantage_source
        in {"sampled_action_residual_v1", "sampled_mean_centered_action_residual_v1"}
    )
    normalized_functional_logit_oracle_mode = str(functional_logit_oracle_mode or "disabled").strip().lower()
    if normalized_functional_logit_oracle_mode in {"", "none", "off", "false"}:
        normalized_functional_logit_oracle_mode = "disabled"
    zero_epoch_functional_logit_oracle_diagnostic = (
        int(update_epochs) == 0
        and normalized_functional_logit_oracle_mode in {"centered_delta_scan"}
    )
    if zero_epoch_learner_vtrace_dry_run and abs(float(current_policy_local_step_reward_weight)) > 1.0e-12:
        raise ValueError("learner_vtrace dry-run requires current_policy_local_step_reward_weight=0")
    if int(update_epochs) <= 0 and not (
        zero_epoch_q_backed_projection_diagnostic
        or zero_epoch_functional_logit_oracle_diagnostic
        or zero_epoch_learner_vtrace_dry_run
    ):
        raise ValueError(
            "current-policy update_epochs must be positive unless running "
            "sampled Q-backed projection, functional logit oracle diagnostics, "
            "or learner_vtrace dry-run"
        )
    if int(update_epochs) > 2 and not bool(allow_multi_epoch_current_policy_update):
        raise ValueError(
            "current-policy update_epochs > 2 is diagnostic-only; pass "
            "allow_multi_epoch_current_policy_update for fixed-batch probes"
        )
    normalized_row_contract_mode = str(row_contract_mode or "full").strip().lower()
    if normalized_row_contract_mode not in {"full", "fast_preflight"}:
        raise ValueError("row_contract_mode must be one of: full, fast_preflight")
    started_at = perf_counter()
    phase_timings: dict[str, float] = {}

    if training_rows is not None and training_rows_path is not None:
        raise ValueError("current-policy training accepts either training_rows or training_rows_path, not both")
    if training_rows is None and training_rows_path is None:
        raise ValueError("current-policy training requires training_rows or training_rows_path")
    if training_rows is not None:
        training_paths: list[Path] = []
        row_file_weights: list[float] = []
        rows = list(training_rows)
        training_rows_path_value: str | list[str] | None = None
        training_rows_source_value: dict[str, Any] = {
            "kind": "in_memory_transition_buffer",
            "schema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "rowSchema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "rows": len(rows),
            "sqliteHotPath": False,
            "jsonHotPath": False,
        }
    else:
        assert training_rows_path is not None
        training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
        row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
        rows = _load_weighted_current_policy_trajectory_rows(training_paths, row_file_weights)
        training_rows_path_value = (
            str(training_paths[0])
            if len(training_paths) == 1
            else [str(path) for path in training_paths]
        )
        training_rows_source_value = _current_policy_training_rows_source_value(training_paths)
    row_copy_ready_at = perf_counter()
    phase_timings["rowInputCopySeconds"] = round(max(0.0, row_copy_ready_at - started_at), 6)
    pre_contract_started = perf_counter()
    if normalized_row_contract_mode == "fast_preflight":
        pre_target_semantics_row_contract_report = _current_policy_training_row_contract_report_fast(
            rows,
            actor_policy_id=actor_id,
        )
    else:
        pre_target_semantics_row_contract_report = _current_policy_training_row_contract_report(
            rows,
            actor_policy_id=actor_id,
        )
    phase_timings["preTargetSemanticsContractSeconds"] = round(max(0.0, perf_counter() - pre_contract_started), 6)
    if int(pre_target_semantics_row_contract_report["acceptedRows"]) <= 0 or int(pre_target_semantics_row_contract_report["rejectedRows"]) > 0:
        reasons = ", ".join(pre_target_semantics_row_contract_report["rejectionReasons"].keys()) or "no usable current-policy rows"
        raise ValueError(f"current-policy training row contract failed: {reasons}")
    if base_model_path is None:
        raise ValueError("current-policy actor_N update requires --base-model-path for the current direct actor")
    source_actor_readiness = _assert_current_policy_actor_base_model(
        base_model_path,
        expected_actor_policy_id=actor_id,
        allow_launchable_candidate_base=bool(allow_unpromoted_source_actor),
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    resolved_action_q_target_ab_diagnostic_cache_path = (
        Path(action_q_target_ab_diagnostic_cache_path)
        if action_q_target_ab_diagnostic_cache_path is not None
        else (
            out_path / "action_q_target_ab_diagnostic_cache.pt"
            if normalized_actor_advantage_source
            in {
                "action_q_residual_v1",
                "sampled_action_residual_v1",
                "sampled_mean_centered_action_residual_v1",
            }
            else None
        )
    )
    source_actor_id = actor_id
    candidate_policy_id = str(candidate_policy_id or f"{source_actor_id}_next").strip()
    if not candidate_policy_id:
        raise ValueError("current-policy training requires non-empty candidate_policy_id")
    if candidate_policy_id == source_actor_id:
        raise ValueError("current-policy training candidate_policy_id must differ from actor_policy_id")
    restart_safety_review = assert_restart_safety_clear(
        restart_safety_review_path,
        usage_label="current-policy actor update",
        allow_unreviewed_restart=bool(allow_unreviewed_restart),
    )
    usable_filter_started = perf_counter()
    usable_rows = [
        row
        for row in rows
        if str(row.get("schema") or "") == CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA
        and _ygo_trajectory_policy_label(row) is not None
    ]
    phase_timings["usableRowFilterSeconds"] = round(max(0.0, perf_counter() - usable_filter_started), 6)
    if not usable_rows:
        raise ValueError("current-policy training found no sampled trajectory rows")
    recurrent_mode_enabled = str(recurrent_training_mode or "disabled").strip().lower() not in {
        "",
        "disabled",
        "none",
        "off",
        "false",
    }
    target_filter_started = perf_counter()
    target_safe_rows, target_action_semantics_filter = _filter_current_policy_target_action_safe_rows(usable_rows)
    phase_timings["targetActionFilterSeconds"] = round(max(0.0, perf_counter() - target_filter_started), 6)
    if not target_safe_rows:
        raise ValueError("current-policy training found no target-safe sampled trajectory rows")
    play_filter_started = perf_counter()
    play_safe_rows, play_card_target_semantics_filter = _filter_current_policy_play_card_target_safe_rows(target_safe_rows)
    phase_timings["playCardTargetFilterSeconds"] = round(max(0.0, perf_counter() - play_filter_started), 6)
    if not play_safe_rows:
        raise ValueError("current-policy training found no play-card-target-safe sampled trajectory rows")
    context_only_rows_report: dict[str, Any] = {
        "kind": "current_policy_recurrent_context_only_rows_v1",
        "enabled": False,
        "rows": 0,
    }
    if bool(recurrent_mode_enabled):
        play_safe_ids = {id(row) for row in play_safe_rows}
        target_safe_ids = {id(row) for row in target_safe_rows}
        context_preserved_rows: list[dict[str, Any]] = []
        context_only_rows = 0
        context_only_reasons: Counter[str] = Counter()
        context_only_by_decision: Counter[str] = Counter()
        for row in usable_rows:
            if id(row) in play_safe_ids:
                context_preserved_rows.append(row)
                continue
            runtime_recurrent_key = _current_policy_runtime_recurrent_key(row)
            if runtime_recurrent_key:
                reason = (
                    "play_card_target_semantics_context_only"
                    if id(row) in target_safe_ids
                    else "target_action_semantics_context_only"
                )
                _mark_current_policy_context_only_row(row, reason=reason)
                context_preserved_rows.append(row)
                context_only_rows += 1
                context_only_reasons[reason] += 1
                context_only_by_decision[str(row.get("decisionKind") or "unknown")] += 1
        usable_rows = context_preserved_rows
        context_only_rows_report = {
            "kind": "current_policy_recurrent_context_only_rows_v1",
            "enabled": True,
            "rows": int(context_only_rows),
            "inputRows": int(len(context_preserved_rows)),
            "trainableRows": int(len(play_safe_rows)),
            "reasons": {key: int(value) for key, value in sorted(context_only_reasons.items())},
            "rowsByDecisionKind": {key: int(value) for key, value in sorted(context_only_by_decision.items())},
        }
    else:
        usable_rows = play_safe_rows
    trainable_loss_rows = [
        row
        for row in usable_rows
        if not _current_policy_context_only_row(row)
    ]
    if not trainable_loss_rows:
        raise ValueError("current-policy training found no trainable target-safe sampled trajectory rows")
    play_assert_started = perf_counter()
    play_card_target_semantics = assert_play_card_target_semantics_safe(
        trainable_loss_rows,
        allow_missing_target_semantics=bool(allow_missing_play_card_target_semantics),
    )
    phase_timings["playCardTargetAssertSeconds"] = round(max(0.0, perf_counter() - play_assert_started), 6)
    if bool(require_old_policy_values):
        old_values_started = perf_counter()
        missing_old_values = sum(1 for row in trainable_loss_rows if _current_policy_old_state_value(row) is None)
        phase_timings["oldPolicyValueCheckSeconds"] = round(max(0.0, perf_counter() - old_values_started), 6)
        if missing_old_values:
            raise ValueError(
                "current-policy online actor/value training requires old policy state values: "
                f"missingRows={missing_old_values}"
            )
    trust_old_policy_values = bool(require_old_policy_values) or _current_policy_source_value_head_trusted(base_model_path)
    lambda_started = perf_counter()
    usable_rows, episode_lambda_report = _apply_current_policy_episode_lambda_returns(
        usable_rows,
        actor_advantage_mode=current_policy_actor_advantage_mode,
        local_step_reward_weight=float(current_policy_local_step_reward_weight),
        use_old_policy_values=trust_old_policy_values,
        copy_rows=False,
    )
    phase_timings["episodeLambdaSeconds"] = round(max(0.0, perf_counter() - lambda_started), 6)
    sequence_started = perf_counter()
    usable_rows, sequence_batch_report = _annotate_current_policy_sequence_segments(
        usable_rows,
        chunk_length=16,
        copy_rows=False,
    )
    phase_timings["sequenceAnnotationSeconds"] = round(max(0.0, perf_counter() - sequence_started), 6)
    target_assert_started = perf_counter()
    target_action_semantics = assert_target_action_semantics_safe(trainable_loss_rows)
    phase_timings["targetActionAssertSeconds"] = round(max(0.0, perf_counter() - target_assert_started), 6)
    post_contract_started = perf_counter()
    if normalized_row_contract_mode == "fast_preflight":
        row_contract_report = _current_policy_training_row_contract_report_fast(
            usable_rows,
            actor_policy_id=actor_id,
        )
    else:
        row_contract_report = _current_policy_training_row_contract_report(usable_rows, actor_policy_id=actor_id)
    phase_timings["postTargetSemanticsContractSeconds"] = round(max(0.0, perf_counter() - post_contract_started), 6)
    if int(row_contract_report["acceptedRows"]) <= 0 or int(row_contract_report["rejectedRows"]) > 0:
        reasons = ", ".join(row_contract_report["rejectionReasons"].keys()) or "no usable current-policy rows"
        raise ValueError(f"current-policy training row contract failed after target filtering: {reasons}")
    cap_started = perf_counter()
    usable_rows, max_training_rows_report = _cap_current_policy_training_rows(
        usable_rows,
        max_rows=max_training_rows,
        seed=int(seed),
        preserve_sequence_groups=bool(recurrent_mode_enabled),
        copy_rows=False,
    )
    phase_timings["rowCapSeconds"] = round(max(0.0, perf_counter() - cap_started), 6)
    split_started = perf_counter()
    if bool(recurrent_mode_enabled):
        train_rows, eval_rows = _split_rows_by_sequence_group(
            usable_rows,
            eval_fraction=float(eval_fraction),
            shuffle=True,
            seed=int(seed),
        )
    else:
        train_rows, eval_rows = _split_rows_by_state_group(
            usable_rows,
            eval_fraction=float(eval_fraction),
            shuffle=True,
            seed=int(seed),
        )
    phase_timings["trainEvalSplitSeconds"] = round(max(0.0, perf_counter() - split_started), 6)
    if not eval_rows:
        eval_rows = train_rows
    sampled_train_rows = list(train_rows)
    sampled_eval_rows = list(eval_rows)
    capped_rows_use_gae = bool(usable_rows) and all(
        str(
            _mapping(row.get("trajectoryPolicyLabel")).get(
                "criticAdvantageMode",
                _mapping(row.get("trajectoryPolicyLabel")).get("advantageMode"),
            )
            or ""
        )
        == "episode_gae_old_policy_value"
        for row in usable_rows
    )
    resolved_critic_warmup_epochs = (
        int(critic_warmup_epochs)
        if critic_warmup_epochs is not None
        else (0 if capped_rows_use_gae else 1)
    )
    resolved_actor_advantage_mode = normalized_current_policy_actor_advantage_mode
    advantage_target = (
        "learner_current_value_gae"
        if resolved_actor_advantage_mode == "learner_current_value_gae"
        else "learner_vtrace"
        if resolved_actor_advantage_mode == "learner_vtrace"
        else "gae_from_old_policy_value"
        if capped_rows_use_gae
        else "return_minus_critic_value"
    )
    actual_advantage_source = (
        "learner_vtrace"
        if resolved_actor_advantage_mode == "learner_vtrace"
        else "learner_current_value_gae"
        if resolved_actor_advantage_mode == "learner_current_value_gae"
        else "gae"
    )
    value_target_mode = "vtrace" if resolved_actor_advantage_mode == "learner_vtrace" else "gae"
    sampled_train_conversion = _current_policy_trajectory_passthrough_report(
        train_rows,
        transform_report=episode_lambda_report,
    )
    sampled_eval_conversion = _current_policy_trajectory_passthrough_report(
        eval_rows,
        transform_report=episode_lambda_report,
    )
    phase_timings["rowPreparationSeconds"] = round(max(0.0, perf_counter() - started_at), 6)

    initial_scorer = _load_initial_scorer(base_model_path)
    if initial_scorer is None:
        raise ValueError("current-policy actor_N update requires a direct actor base model")
    normalized_decision_training_weights = _normalized_anchor_kl_decision_weights(decision_training_weights)
    pre_tensor_started = perf_counter()
    tensor_global_names = _ygo_merged_feature_names(sampled_train_rows, "globalFeatureNames")
    tensor_history_names = _ygo_merged_feature_names(sampled_train_rows, "historyFeatureNames")
    tensor_action_names = _ygo_merged_feature_names(sampled_train_rows, "actionFeatureNames")
    tensor_card_names = _ygo_merged_feature_names(sampled_train_rows, "cardFeatureNames")
    tensor_input_dim = (
        len(tensor_global_names)
        + len(tensor_history_names)
        + len(tensor_action_names)
        + 3 * len(tensor_card_names)
    )
    tensor_shape = YgoStyleActionSetPolicyScorer(
        globalFeatureNames=tensor_global_names,
        historyFeatureNames=tensor_history_names,
        actionFeatureNames=tensor_action_names,
        cardFeatureNames=tensor_card_names,
        inputDim=int(tensor_input_dim),
        hiddenDim=int(hidden_dim),
    )
    outcome_tensor_batch = build_ygo_outcome_policy_tensor_batch(
        sampled_train_rows,
        scorer=tensor_shape,
        decision_training_weights=normalized_decision_training_weights,
        normalize_advantages=False,
        layout=("ragged_legal_slots" if bool(recurrent_mode_enabled) else "dense_padded"),
    )
    phase_timings["preTensorBuildSeconds"] = round(max(0.0, perf_counter() - pre_tensor_started), 6)
    model_training_started = perf_counter()
    normalized_learner_diagnostics_mode = (
        str(learner_diagnostics_mode).strip().lower()
        if learner_diagnostics_mode is not None
        else (
            "minimal"
            if str(post_training_diagnostics or "full").strip().lower()
            in {"skip", "skipped", "disabled", "none", "off", "false"}
            else "full"
        )
    )
    candidate = train_ygo_style_outcome_policy_scorer(
        sampled_train_rows,
        epochs=int(update_epochs),
        learning_rate=float(learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        seed=int(seed),
        initial_scorer=initial_scorer,
        decision_training_weights=normalized_decision_training_weights,
        anchor_kl_weight=max(0.0, float(anchor_kl_weight)),
        anchor_kl_temperature=float(anchor_kl_temperature),
        retention_kl_mode=str(retention_kl_mode),
        entropy_coef=float(entropy_coef),
        ppo_clip_coef=float(ppo_clip_coef),
        value_loss_weight=float(value_loss_weight),
        normalize_advantages=bool(normalize_advantages),
        advantage_normalization_mode=str(advantage_normalization_mode),
        value_domain_bias_mode="matchup_bucket",
        domain_gradient_conflict_mode=str(domain_gradient_conflict_mode),
        multi_domain_objective_mode=str(multi_domain_objective_mode),
        recurrent_training_mode=str(recurrent_training_mode),
        decision_residual_policy_mode=str(decision_residual_policy_mode),
        state_action_interaction_mode=str(state_action_interaction_mode),
        state_action_interaction_rank=int(state_action_interaction_rank),
        state_action_interaction_init_scale=float(state_action_interaction_init_scale),
        state_action_interaction_lr_multiplier=float(state_action_interaction_lr_multiplier),
        actor_base_lr_multiplier=float(actor_base_lr_multiplier),
        detach_value_loss_recurrent_context=bool(detach_value_loss_recurrent_context),
        require_old_policy_log_prob=True,
        actor_update_requires_trusted_value=bool(actor_update_requires_trusted_value),
        actor_trusted_value_ev_threshold=float(actor_trusted_value_ev_threshold),
        selfplay_actor_loss_cap_fraction=float(selfplay_actor_loss_cap_fraction),
        original_terminal_actor_loss_min_fraction=float(original_terminal_actor_loss_min_fraction),
        actor_loss_max_rows_per_domain=int(actor_loss_max_rows_per_domain),
        actor_loss_sign_balance_mode=str(actor_loss_sign_balance_mode),
        actor_loss_sequential_sign_steps=bool(actor_loss_sequential_sign_steps),
        actor_loss_sequential_sign_order=str(actor_loss_sequential_sign_order),
        actor_loss_min_abs_advantage=float(actor_loss_min_abs_advantage),
        actor_loss_advantage_sign_filter=str(actor_loss_advantage_sign_filter),
        actor_loss_label_consistency_mode=str(actor_loss_label_consistency_mode),
        actor_loss_label_consistency_min_abs_advantage=float(actor_loss_label_consistency_min_abs_advantage),
        actor_loss_counter_signal_conflict_weight=float(actor_loss_counter_signal_conflict_weight),
        actor_advantage_source=str(actor_advantage_source),
        q_backed_actor_residual_transfer_mode=str(q_backed_actor_residual_transfer_mode),
        action_q_residual_loss_weight=float(action_q_residual_loss_weight),
        action_q_target_ab_diagnostic_cache_path=resolved_action_q_target_ab_diagnostic_cache_path,
        actor_loss_relative_mode=str(actor_loss_relative_mode),
        actor_loss_group_mode=str(actor_loss_group_mode),
        actor_legal_margin_weight=float(actor_legal_margin_weight),
        actor_signature_drift_penalty_weight=float(actor_signature_drift_penalty_weight),
        actor_signature_contrastive_weight=float(actor_signature_contrastive_weight),
        actor_gradient_collision_audit_mode=str(actor_gradient_collision_audit_mode),
        functional_logit_oracle_mode=str(normalized_functional_logit_oracle_mode),
        actor_linearized_representability_mode=str(actor_linearized_representability_mode),
        actor_linearized_cg_max_iterations=int(actor_linearized_cg_max_iterations),
        actor_linearized_optimizer_diagnostics=str(actor_linearized_optimizer_diagnostics),
        learner_diagnostics_mode=str(normalized_learner_diagnostics_mode),
        terminal_untrusted_actor_loss_max_steps_from_terminal=int(terminal_untrusted_actor_loss_max_steps_from_terminal),
        critic_warmup_epochs=int(resolved_critic_warmup_epochs),
        critic_warmup_recompute_advantage=bool(critic_warmup_recompute_advantage),
        device=str(device),
        tensor_batch=outcome_tensor_batch,
    )
    phase_timings["modelTrainingSeconds"] = round(max(0.0, perf_counter() - model_training_started), 6)
    diagnostics_started = perf_counter()
    diagnostics_eval_rows = sampled_eval_rows or sampled_train_rows
    normalized_post_training_diagnostics = str(post_training_diagnostics or "full").strip().lower()
    if normalized_post_training_diagnostics in {"skip", "skipped", "disabled", "none", "off", "false"}:
        outcome_eval = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_eval_v1")
        base_outcome_eval = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_eval_v1")
        outcome_train_eval = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_train_eval_v1")
        base_outcome_train_eval = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_train_eval_v1")
        outcome_eval_movement = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_movement_v1")
        outcome_train_movement = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_movement_v1")
        outcome_eval_group_movement = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_group_movement_v1")
        outcome_train_group_movement = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_group_movement_v1")
        outcome_eval_domain_movement = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_domain_movement_v1")
        outcome_train_domain_movement = _skipped_current_policy_diagnostic_report(kind="current_policy_sampled_advantage_domain_movement_v1")
        outcome_eval_signal_bucket_audit = _skipped_current_policy_diagnostic_report(kind="current_policy_signal_correlation_bucket_audit_v1")
        outcome_train_signal_bucket_audit = _skipped_current_policy_diagnostic_report(kind="current_policy_signal_correlation_bucket_audit_v1")
        post_training_diagnostics_mode = "skipped"
    elif bool(recurrent_mode_enabled):
        _reset_recurrent_state_if_available(candidate)
        candidate_eval_scores = candidate.score_rows_batched(list(diagnostics_eval_rows))
        _reset_recurrent_state_if_available(initial_scorer)
        base_eval_scores = initial_scorer.score_rows_batched(list(diagnostics_eval_rows))
        outcome_eval = _outcome_policy_eval_from_scores(diagnostics_eval_rows, candidate_eval_scores)
        base_outcome_eval = _outcome_policy_eval_from_scores(diagnostics_eval_rows, base_eval_scores)
        outcome_eval_movement = _outcome_policy_movement_eval_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        outcome_eval_group_movement = _outcome_policy_group_movement_eval_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        outcome_eval_domain_movement = _outcome_policy_domain_movement_eval_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        outcome_eval_signal_bucket_audit = _outcome_policy_signal_correlation_bucket_audit_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        outcome_train_eval = _reused_current_policy_diagnostic_report(
            outcome_eval,
            reused_from="candidateCurrentPolicySampledAdvantageEval",
        )
        base_outcome_train_eval = _reused_current_policy_diagnostic_report(
            base_outcome_eval,
            reused_from="baseCurrentPolicySampledAdvantageEval",
        )
        outcome_train_movement = _reused_current_policy_diagnostic_report(
            outcome_eval_movement,
            reused_from="currentPolicySampledAdvantageMovementEval",
        )
        outcome_train_group_movement = _reused_current_policy_diagnostic_report(
            outcome_eval_group_movement,
            reused_from="currentPolicySampledAdvantageGroupMovementEval",
        )
        outcome_train_domain_movement = _reused_current_policy_diagnostic_report(
            outcome_eval_domain_movement,
            reused_from="currentPolicySampledAdvantageDomainMovementEval",
        )
        outcome_train_signal_bucket_audit = _reused_current_policy_diagnostic_report(
            outcome_eval_signal_bucket_audit,
            reused_from="currentPolicySignalBucketAuditEval",
        )
        post_training_diagnostics_mode = "recurrent_eval_only_cached_scores"
    else:
        diagnostics_eval_same_as_train = (
            len(diagnostics_eval_rows) == len(sampled_train_rows)
            and all(left is right for left, right in zip(diagnostics_eval_rows, sampled_train_rows, strict=False))
        )
        _reset_recurrent_state_if_available(candidate)
        candidate_train_scores = candidate.score_rows_batched(list(sampled_train_rows))
        if diagnostics_eval_same_as_train:
            candidate_eval_scores = candidate_train_scores
        else:
            _reset_recurrent_state_if_available(candidate)
            candidate_eval_scores = candidate.score_rows_batched(list(diagnostics_eval_rows))
        _reset_recurrent_state_if_available(initial_scorer)
        base_train_scores = initial_scorer.score_rows_batched(list(sampled_train_rows))
        if diagnostics_eval_same_as_train:
            base_eval_scores = base_train_scores
        else:
            _reset_recurrent_state_if_available(initial_scorer)
            base_eval_scores = initial_scorer.score_rows_batched(list(diagnostics_eval_rows))
        outcome_train_eval = _outcome_policy_eval_from_scores(sampled_train_rows, candidate_train_scores)
        outcome_eval = _outcome_policy_eval_from_scores(diagnostics_eval_rows, candidate_eval_scores)
        base_outcome_train_eval = _outcome_policy_eval_from_scores(sampled_train_rows, base_train_scores)
        base_outcome_eval = _outcome_policy_eval_from_scores(diagnostics_eval_rows, base_eval_scores)
        outcome_train_movement = _outcome_policy_movement_eval_from_scores(
            sampled_train_rows,
            base_train_scores,
            candidate_train_scores,
        )
        outcome_train_group_movement = _outcome_policy_group_movement_eval_from_scores(
            sampled_train_rows,
            base_train_scores,
            candidate_train_scores,
        )
        outcome_eval_movement = _outcome_policy_movement_eval_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        outcome_eval_group_movement = _outcome_policy_group_movement_eval_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        outcome_train_domain_movement = _outcome_policy_domain_movement_eval_from_scores(
            sampled_train_rows,
            base_train_scores,
            candidate_train_scores,
        )
        outcome_eval_domain_movement = _outcome_policy_domain_movement_eval_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        outcome_train_signal_bucket_audit = _outcome_policy_signal_correlation_bucket_audit_from_scores(
            sampled_train_rows,
            base_train_scores,
            candidate_train_scores,
        )
        outcome_eval_signal_bucket_audit = _outcome_policy_signal_correlation_bucket_audit_from_scores(
            diagnostics_eval_rows,
            base_eval_scores,
            candidate_eval_scores,
        )
        post_training_diagnostics_mode = "full_cached_scores"
    domain_gradient_conflict_diagnostics = dict(
        (getattr(candidate, "runtimeAuxTrainingDiagnostics", {}) or {}).get(
            "domainGradientConflictDiagnostics",
            {},
        )
    )
    signal_bucket_audit_paths = _write_current_policy_signal_bucket_audit_files(
        outcome_eval_signal_bucket_audit,
        out_dir=out_path,
    )
    phase_timings["postTrainingDiagnosticsSeconds"] = round(max(0.0, perf_counter() - diagnostics_started), 6)
    sandbox_report = {
        "candidateModelPath": str(out_path / "self_improvement_current_policy_actor_value_model.json"),
        "rowCount": len(rows),
        "usableTrajectoryRows": len(usable_rows),
        "usableFullLegalRows": len(usable_rows),
        "maxTrainingRowsReport": max_training_rows_report,
        "sequenceBatchReport": sequence_batch_report,
        "contextOnlyRowsReport": context_only_rows_report,
        "trainRows": len(train_rows),
        "evalRows": len(eval_rows),
        "candidateSandboxPolicyValueTrainEval": None,
        "candidateSandboxPolicyValueEval": None,
        "baseSandboxPolicyValueTrainEval": None,
        "baseSandboxPolicyValueEval": None,
        "scratchTraining": False,
        "policyAnchorKlTraining": bool(max(0.0, float(anchor_kl_weight)) > 0.0),
        "anchorKlWeight": max(0.0, float(anchor_kl_weight)),
        "anchorKlTemperature": float(anchor_kl_temperature),
        "anchorKlSource": "initial_scorer",
        "retentionKlMode": str(getattr(candidate, "retentionKlMode", retention_kl_mode) or "disabled"),
        "retentionKlReport": dict(getattr(candidate, "retentionKlReport", {}) or {}),
        "domainGradientConflictMode": str(domain_gradient_conflict_mode),
        "multiDomainObjectiveMode": str(multi_domain_objective_mode),
        "recurrentTrainingMode": str(getattr(candidate, "recurrentTrainingMode", recurrent_training_mode) or "disabled"),
        "decisionResidualPolicyMode": str(getattr(candidate, "decisionResidualPolicyMode", decision_residual_policy_mode) or "disabled"),
        "stateActionInteractionMode": str(getattr(candidate, "stateActionInteractionMode", state_action_interaction_mode) or "disabled"),
        "stateActionInteractionRank": int(getattr(candidate, "stateActionInteractionRank", state_action_interaction_rank) or 0),
        "actorUpdateRequiresTrustedValue": bool(actor_update_requires_trusted_value),
        "actorTrustedValueEvThreshold": float(actor_trusted_value_ev_threshold),
        "selfplayActorLossCapFraction": float(selfplay_actor_loss_cap_fraction),
        "originalTerminalActorLossMinFraction": float(original_terminal_actor_loss_min_fraction),
        "actorLossMaxRowsPerDomain": int(actor_loss_max_rows_per_domain),
        "actorLossSignBalanceMode": str(actor_loss_sign_balance_mode),
        "actorLossSequentialSignSteps": bool(actor_loss_sequential_sign_steps),
        "actorLossMinAbsAdvantage": float(actor_loss_min_abs_advantage),
        "actorLossAdvantageSignFilter": str(actor_loss_advantage_sign_filter),
        "actorLossLabelConsistencyMode": str(actor_loss_label_consistency_mode),
        "actorLossLabelConsistencyMinAbsAdvantage": float(actor_loss_label_consistency_min_abs_advantage),
        "actorLossCounterSignalConflictWeight": float(actor_loss_counter_signal_conflict_weight),
        "actorAdvantageSource": str(actor_advantage_source),
        "qBackedActorResidualTransferMode": str(q_backed_actor_residual_transfer_mode),
        "actionQResidualLossWeight": float(action_q_residual_loss_weight),
        "actorLossRelativeMode": str(actor_loss_relative_mode),
        "actorLossGroupMode": str(actor_loss_group_mode),
        "actorLegalMarginWeight": float(actor_legal_margin_weight),
        "actorSignatureDriftPenaltyWeight": float(actor_signature_drift_penalty_weight),
        "actorSignatureContrastiveWeight": float(actor_signature_contrastive_weight),
        "stateActionInteractionMode": str(state_action_interaction_mode),
        "stateActionInteractionRank": int(state_action_interaction_rank),
        "actorBaseLrMultiplier": float(actor_base_lr_multiplier),
        "stateActionInteractionInitScale": float(state_action_interaction_init_scale),
        "stateActionInteractionLrMultiplier": float(state_action_interaction_lr_multiplier),
        "actorGradientCollisionAuditMode": str(actor_gradient_collision_audit_mode),
        "terminalUntrustedActorLossMaxStepsFromTerminal": int(terminal_untrusted_actor_loss_max_steps_from_terminal),
        "policyTemperatureRequested": float(policy_temperature),
        "policyTemperatureUsedInSampledPpo": False,
        "postTrainingDiagnosticsMode": post_training_diagnostics_mode,
        "learnerDiagnosticsMode": str(normalized_learner_diagnostics_mode),
        "entropyCoef": float(entropy_coef),
        "normalizeAdvantages": bool(normalize_advantages),
        "sandboxTrainingDiagnostics": dict(getattr(candidate, "runtimeAuxTrainingDiagnostics", {}) or {}),
        "actorGradientCollisionAudit": dict(
            (getattr(candidate, "runtimeAuxTrainingDiagnostics", {}) or {}).get("actorGradientCollisionAudit", {})
        ),
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "candidateCurrentPolicySampledAdvantageEval": outcome_eval,
        "baseCurrentPolicySampledAdvantageEval": base_outcome_eval,
        "currentPolicySampledAdvantageMovementTrain": outcome_train_movement,
        "currentPolicySampledAdvantageMovementEval": outcome_eval_movement,
        "currentPolicySampledAdvantageGroupMovementTrain": outcome_train_group_movement,
        "currentPolicySampledAdvantageGroupMovementEval": outcome_eval_group_movement,
        "currentPolicySampledAdvantageDomainMovementTrain": outcome_train_domain_movement,
        "currentPolicySampledAdvantageDomainMovementEval": outcome_eval_domain_movement,
        "currentPolicySignalBucketAuditTrain": outcome_train_signal_bucket_audit,
        "currentPolicySignalBucketAuditEval": outcome_eval_signal_bucket_audit,
        "currentPolicySignalBucketAuditPaths": signal_bucket_audit_paths,
        "currentPolicyDomainGradientConflictDiagnostics": domain_gradient_conflict_diagnostics,
        "targetActionSemanticsFilter": target_action_semantics_filter,
        "playCardTargetSemanticsFilter": play_card_target_semantics_filter,
        "episodeLambdaReturnTransform": episode_lambda_report,
        "rowContractMode": normalized_row_contract_mode,
        "trainingPhaseTimings": dict(phase_timings),
        "preTargetSemanticsRowContractReport": pre_target_semantics_row_contract_report,
    }
    gate_eligibility = _current_policy_training_gate_eligibility(
        row_contract_report=row_contract_report,
        sandbox_report=sandbox_report,
    )
    if normalized_row_contract_mode == "fast_preflight":
        gate_eligibility = dict(gate_eligibility)
        blocking = list(gate_eligibility.get("blockingReasons") or [])
        if "full_current_policy_row_contract_deferred" not in blocking:
            blocking.append("full_current_policy_row_contract_deferred")
        gate_eligibility["blockingReasons"] = blocking
        gate_eligibility["gateEligible"] = False

    model_dict = candidate.to_dict()
    model_path = out_path / "self_improvement_current_policy_actor_value_model.json"
    checkpoint_path = out_path / "self_improvement_current_policy_actor_value_model.pt"
    report_path = out_path / "ygo_style_current_policy_training_report.json"
    candidate_model_path_value = None if zero_epoch_learner_vtrace_dry_run else str(model_path)
    candidate_checkpoint_path_value = None if zero_epoch_learner_vtrace_dry_run else str(checkpoint_path)
    model_dict.update(
        {
            "modelId": candidate_policy_id,
            "trainingMode": YGO_STYLE_CURRENT_POLICY_TRAINING_VERSION,
            "trainingReportPath": str(report_path),
            "checkpointFormat": YGO_STYLE_POLICY_PT_CHECKPOINT_VERSION,
            "checkpointPath": candidate_checkpoint_path_value,
            "runtimeJsonExportPath": candidate_model_path_value,
            "trainingMainline": "unified_current_policy_actor_value",
            "basePolicyRole": "warmstart_or_reference_only",
            "actorPolicyId": candidate_policy_id,
            "sourceActorPolicyId": source_actor_id,
            "sourceActorSourceReady": True,
            "sourceActorReadiness": source_actor_readiness,
            "candidatePolicyId": candidate_policy_id,
            "runtimeLaunchableActor": True,
            "actorNSourceEligible": False,
            "runtimeSelectionInterface": "zz.current_policy_runtime.masked_argmax_action",
            "runtimeRowContract": "zz.current_policy_runtime.validate_current_policy_row",
            "currentPolicyRowContractReport": row_contract_report,
            "rowContractMode": normalized_row_contract_mode,
            "requiresFullCurrentPolicyRowContractBeforeGate": normalized_row_contract_mode == "fast_preflight",
            "maxTrainingRowsReport": dict(sandbox_report.get("maxTrainingRowsReport") or {}),
            "sandboxOnly": False,
            "gateEligible": bool(gate_eligibility["gateEligible"]),
            "gateEligibility": gate_eligibility,
            "gateEligibilityReasons": list(gate_eligibility["blockingReasons"]),
            "requiresCurrentPolicyBridgeAuditBeforeGate": True,
            "directPolicyRuntimeAuthority": True,
            "unifiedMaskedActorValueTraining": True,
            "activePolicyRequiredForGameplayClaim": True,
            "sidecarListwiseTraining": False,
            "residualSidecarTraining": False,
            "runtimeCalibratedSidecarTraining": False,
            "fullDirectPolicyTraining": True,
            "selectedActionImitation": False,
            "teacherScoreImitation": False,
            "recurrentTrainingMode": str(sandbox_report.get("recurrentTrainingMode") or "disabled"),
            "decisionResidualPolicyMode": str(sandbox_report.get("decisionResidualPolicyMode") or "disabled"),
            "usesRecurrentState": bool(model_dict.get("usesRecurrentState", False)),
            "postTrainingDiagnosticsMode": str(sandbox_report.get("postTrainingDiagnosticsMode") or ""),
            "fullLegalActionSetTraining": True,
            "trainingObjective": CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE,
            "policyTarget": "sampled_actor_episode_return_advantage",
            "policyTargetSource": "actor_sampled_episode_return",
            "advantageTarget": advantage_target,
            "actualAdvantageSource": actual_advantage_source,
            "valueTargetMode": value_target_mode,
            "sourceSandboxModelPath": None,
            "sourceSandboxTrainingReportPath": None,
            "policyAnchorKlTraining": bool(sandbox_report.get("policyAnchorKlTraining", False)),
            "anchorKlWeight": float(sandbox_report.get("anchorKlWeight", anchor_kl_weight) or 0.0),
            "anchorKlTemperature": float(sandbox_report.get("anchorKlTemperature", anchor_kl_temperature) or 1.0),
            "anchorKlSource": str(sandbox_report.get("anchorKlSource") or "row_actor_logits"),
            "retentionKlMode": str(sandbox_report.get("retentionKlMode") or "disabled"),
            "retentionKlReport": dict(sandbox_report.get("retentionKlReport") or {}),
            "multiDomainObjectiveMode": str(sandbox_report.get("multiDomainObjectiveMode") or "disabled"),
            "actorUpdateRequiresTrustedValue": bool(sandbox_report.get("actorUpdateRequiresTrustedValue", False)),
            "actorTrustedValueEvThreshold": float(
                sandbox_report.get("actorTrustedValueEvThreshold", actor_trusted_value_ev_threshold) or 0.0
            ),
            "entropyCoef": float(sandbox_report.get("entropyCoef", entropy_coef) or 0.0),
            "normalizeAdvantages": bool(normalize_advantages),
            "advantageNormalizationMode": str(
                (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("advantageNormalizationMode")
                or "disabled"
            ),
            "advantageNormalizationReport": dict(
                (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("advantageNormalizationReport")
                or {}
            ),
            "sandboxTrainingDiagnostics": dict(sandbox_report.get("sandboxTrainingDiagnostics") or {}),
            "currentPolicyDomainGradientConflictDiagnostics": domain_gradient_conflict_diagnostics,
            "trainingPhaseTimings": dict(phase_timings),
            "episodeLambdaReturnTransform": dict(sandbox_report.get("episodeLambdaReturnTransform") or {}),
            "sampledAdvantagePolicyGradientTraining": True,
            "dryRun": bool(zero_epoch_learner_vtrace_dry_run),
            "trainingLaunched": not bool(zero_epoch_learner_vtrace_dry_run),
            "checkpointExported": not bool(zero_epoch_learner_vtrace_dry_run),
        }
    )
    model_write_started = perf_counter()
    if not bool(zero_epoch_learner_vtrace_dry_run):
        _write_ygo_style_model_pt(checkpoint_path, model_dict)
        model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    phase_timings["modelWriteSeconds"] = round(max(0.0, perf_counter() - model_write_started), 6)
    model_dict["trainingPhaseTimings"] = dict(phase_timings)

    elapsed_seconds = max(0.000001, perf_counter() - started_at)
    report: dict[str, Any] = {
        "kind": YGO_STYLE_CURRENT_POLICY_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingMainline": "unified_current_policy_actor_value",
        "basePolicyRole": "warmstart_or_reference_only",
        "trainingRowsPath": training_rows_path_value,
        "trainingRowsSource": training_rows_source_value,
        "trainingRowFileWeights": list(row_file_weights),
        "actorPolicyId": candidate_policy_id,
        "sourceActorPolicyId": source_actor_id,
        "sourceActorSourceReady": True,
        "sourceActorReadiness": source_actor_readiness,
        "candidatePolicyId": candidate_policy_id,
        "candidateModelPath": candidate_model_path_value,
        "candidateCheckpointPath": candidate_checkpoint_path_value,
        "candidateRuntimeJsonPath": candidate_model_path_value,
        "reportPath": str(report_path),
        "sourceSandboxModelPath": None,
        "sourceSandboxTrainingReportPath": None,
        "rowCount": int(sandbox_report.get("rowCount", 0) or 0),
        "usableFullLegalRows": int(sandbox_report.get("usableFullLegalRows", 0) or 0),
        "usableTrajectoryRows": int(sandbox_report.get("usableTrajectoryRows", 0) or 0),
        "elapsedSeconds": round(float(elapsed_seconds), 6),
        "usableTrajectoryRowsPerSecond": round(
            float(sandbox_report.get("usableTrajectoryRows", 0) or 0) / float(elapsed_seconds),
            6,
        ),
        "trainingPhaseTimings": dict(phase_timings),
        "trainRows": int(sandbox_report.get("trainRows", 0) or 0),
        "evalRows": int(sandbox_report.get("evalRows", 0) or 0),
        "epochs": int(update_epochs),
        "updateEpochs": int(update_epochs),
        "allowMultiEpochCurrentPolicyUpdate": bool(allow_multi_epoch_current_policy_update),
        "learningRate": float(learning_rate),
        "hiddenDim": int(sandbox_report.get("hiddenDim", hidden_dim) or hidden_dim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        "runtimeLaunchableActor": True,
        "actorNSourceEligible": False,
        "runtimeSelectionInterface": "zz.current_policy_runtime.masked_argmax_action",
        "runtimeRowContract": "zz.current_policy_runtime.validate_current_policy_row",
        "currentPolicyRowContractReport": row_contract_report,
        "rowContractMode": normalized_row_contract_mode,
        "requiresFullCurrentPolicyRowContractBeforeGate": normalized_row_contract_mode == "fast_preflight",
        "maxTrainingRowsReport": dict(sandbox_report.get("maxTrainingRowsReport") or {}),
        "currentPolicySampledAdvantageConversionTrain": sampled_train_conversion,
        "currentPolicySampledAdvantageConversionEval": sampled_eval_conversion,
        "episodeLambdaReturnTransform": dict(sandbox_report.get("episodeLambdaReturnTransform") or {}),
        "currentPolicySampledAdvantageMovementTrain": outcome_train_movement,
        "currentPolicySampledAdvantageMovementEval": outcome_eval_movement,
        "currentPolicySampledAdvantageGroupMovementTrain": outcome_train_group_movement,
        "currentPolicySampledAdvantageGroupMovementEval": outcome_eval_group_movement,
        "currentPolicySampledAdvantageDomainMovementTrain": outcome_train_domain_movement,
        "currentPolicySampledAdvantageDomainMovementEval": outcome_eval_domain_movement,
        "currentPolicySignalBucketAuditTrain": outcome_train_signal_bucket_audit,
        "currentPolicySignalBucketAuditEval": outcome_eval_signal_bucket_audit,
        "currentPolicySignalBucketAuditPaths": signal_bucket_audit_paths,
        "currentPolicyDomainGradientConflictDiagnostics": domain_gradient_conflict_diagnostics,
        "fullLegalActionSetTraining": True,
        "unifiedMaskedActorValueTraining": True,
        "trainingObjective": CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE,
        "policyTarget": "sampled_actor_episode_return_advantage",
        "policyTargetSource": "actor_sampled_episode_return",
        "advantageTarget": advantage_target,
        "actualAdvantageSource": actual_advantage_source,
        "stateValueTarget": "sampled_actor_episode_return",
        "valueTargetMode": value_target_mode,
        "sidecarListwiseTraining": False,
        "residualSidecarTraining": False,
        "runtimeCalibratedSidecarTraining": False,
        "fullDirectPolicyTraining": True,
        "directPolicyRuntimeAuthority": True,
        "selectedActionImitation": False,
        "teacherScoreImitation": False,
        "recurrentTrainingMode": str(sandbox_report.get("recurrentTrainingMode") or "disabled"),
        "decisionResidualPolicyMode": str(sandbox_report.get("decisionResidualPolicyMode") or "disabled"),
        "usesRecurrentState": bool(model_dict.get("usesRecurrentState", False)),
        "postTrainingDiagnosticsMode": str(sandbox_report.get("postTrainingDiagnosticsMode") or ""),
        "learnerDiagnosticsMode": str(sandbox_report.get("learnerDiagnosticsMode") or ""),
        "sandboxOnly": False,
        "gateEligible": bool(gate_eligibility["gateEligible"]),
        "gateEligibility": gate_eligibility,
        "gateEligibilityReasons": list(gate_eligibility["blockingReasons"]),
        "requiresCurrentPolicyBridgeAuditBeforeGate": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
        "defaultRuntimeChanged": False,
        "trainingLaunched": not bool(zero_epoch_learner_vtrace_dry_run),
        "dryRun": bool(zero_epoch_learner_vtrace_dry_run),
        "checkpointExported": not bool(zero_epoch_learner_vtrace_dry_run),
        "scratchTraining": bool(sandbox_report.get("scratchTraining", False)),
        "scratchJustification": (
            "current-policy actor/value smoke only; not a default baseline"
            if bool(sandbox_report.get("scratchTraining", False))
            else None
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "candidateCurrentPolicyTrainEval": sandbox_report.get("candidateSandboxPolicyValueTrainEval"),
        "candidateCurrentPolicyEval": sandbox_report.get("candidateSandboxPolicyValueEval"),
        "baseCurrentPolicyTrainEval": sandbox_report.get("baseSandboxPolicyValueTrainEval"),
        "baseCurrentPolicyEval": sandbox_report.get("baseSandboxPolicyValueEval"),
        "candidateCurrentPolicySampledAdvantageTrainEval": outcome_train_eval,
        "candidateCurrentPolicySampledAdvantageEval": outcome_eval,
        "baseCurrentPolicySampledAdvantageTrainEval": base_outcome_train_eval,
        "baseCurrentPolicySampledAdvantageEval": base_outcome_eval,
        "policyTemperature": float(policy_temperature),
        "policyTemperatureRequested": float(policy_temperature),
        "policyTemperatureUsedInSampledPpo": False,
        "ppoClipCoef": float(ppo_clip_coef),
        "policyTemperatureNote": "current-policy sampled PPO objective uses actor rollout logprobs at rollout temperature; this knob is not applied inside train_ygo_style_outcome_policy_scorer",
        "multiDomainObjectiveMode": str(sandbox_report.get("multiDomainObjectiveMode") or "disabled"),
        "actorUpdateRequiresTrustedValue": bool(sandbox_report.get("actorUpdateRequiresTrustedValue", False)),
        "actorTrustedValueEvThreshold": float(
            sandbox_report.get("actorTrustedValueEvThreshold", actor_trusted_value_ev_threshold) or 0.0
        ),
        "actorLossLabelConsistencyMode": str(actor_loss_label_consistency_mode),
        "actorLossLabelConsistencyMinAbsAdvantage": float(actor_loss_label_consistency_min_abs_advantage),
        "actorLossCounterSignalConflictWeight": float(actor_loss_counter_signal_conflict_weight),
        "actorAdvantageSource": str(actor_advantage_source),
        "qBackedActorResidualTransferMode": str(q_backed_actor_residual_transfer_mode),
        "actionQResidualLossWeight": float(action_q_residual_loss_weight),
        "actorLossRelativeMode": str(actor_loss_relative_mode),
        "actorLossGroupMode": str(actor_loss_group_mode),
        "actorLegalMarginWeight": float(actor_legal_margin_weight),
        "actorSignatureDriftPenaltyWeight": float(actor_signature_drift_penalty_weight),
        "actorSignatureContrastiveWeight": float(actor_signature_contrastive_weight),
        "stateActionInteractionMode": str(state_action_interaction_mode),
        "stateActionInteractionRank": int(state_action_interaction_rank),
        "stateActionInteractionInitScale": float(state_action_interaction_init_scale),
        "stateActionInteractionLrMultiplier": float(state_action_interaction_lr_multiplier),
        "actorBaseLrMultiplier": float(actor_base_lr_multiplier),
        "actorGradientCollisionAuditMode": str(actor_gradient_collision_audit_mode),
        "actorLossSignBalanceMode": str(actor_loss_sign_balance_mode),
        "actorLossSequentialSignSteps": bool(actor_loss_sequential_sign_steps),
        "actorLossSequentialSignOrder": str(actor_loss_sequential_sign_order),
        "actorLossMaxRowsPerDomain": int(actor_loss_max_rows_per_domain),
        "valueLossWeight": float(value_loss_weight),
        "entropyCoef": float(sandbox_report.get("entropyCoef", entropy_coef) or 0.0),
        "currentPolicyActorAdvantageMode": str(current_policy_actor_advantage_mode or "gae"),
        "currentPolicyLocalStepRewardWeight": float(current_policy_local_step_reward_weight),
        "detachValueLossRecurrentContext": bool(detach_value_loss_recurrent_context),
        "criticWarmupEpochs": int(resolved_critic_warmup_epochs),
        "criticWarmupRecomputeAdvantage": bool(critic_warmup_recompute_advantage),
        "requireOldPolicyValues": bool(require_old_policy_values),
        "normalizeAdvantages": bool(normalize_advantages),
        "advantageNormalizationMode": str(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("advantageNormalizationMode")
            or "disabled"
        ),
        "advantageNormalizationReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("advantageNormalizationReport")
            or {}
        ),
        "advantageBaselineMode": str(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("advantageBaselineMode")
            or ""
        ),
        "learnerCurrentValueGaeReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("learnerCurrentValueGaeReport")
            or {}
        ),
        "learnerVtraceReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("learnerVtraceReport")
            or {}
        ),
        "functionalLogitOracleReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("functionalLogitOracleReport")
            or {}
        ),
        "actorLinearizedRepresentabilityReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("actorLinearizedRepresentabilityReport")
            or {}
        ),
        "oldPolicyLogProbAlignmentReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("oldPolicyLogProbAlignmentReport")
            or {}
        ),
        "sequenceBatchReport": dict(sandbox_report.get("sequenceBatchReport") or {}),
        "actualLearnerBatchDomainReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("actualLearnerBatchDomainReport")
            or {}
        ),
        "ppoMovementAuditActorUpdatedRows": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("ppoMovementAuditActorUpdatedRows")
            or {}
        ),
        "actorLegalMarginReport": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("actorLegalMarginReport")
            or {}
        ),
        "finalAllSelectedLogProbMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalAllSelectedLogProbMovementAudit")
            or {}
        ),
        "finalActorUpdatedSelectedLogProbMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalActorUpdatedSelectedLogProbMovementAudit")
            or {}
        ),
        "finalAllSelectedMaxMarginMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalAllSelectedMaxMarginMovementAudit")
            or {}
        ),
        "finalActorUpdatedSelectedMaxMarginMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalActorUpdatedSelectedMaxMarginMovementAudit")
            or {}
        ),
        "finalAllSelectedRawScoreMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalAllSelectedRawScoreMovementAudit")
            or {}
        ),
        "finalActorUpdatedSelectedRawScoreMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalActorUpdatedSelectedRawScoreMovementAudit")
            or {}
        ),
        "finalAllSelectedLogProbDomainMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalAllSelectedLogProbDomainMovementAudit")
            or {}
        ),
        "finalActorUpdatedSelectedLogProbDomainMovementAudit": dict(
            (sandbox_report.get("sandboxTrainingDiagnostics") or {}).get("finalActorUpdatedSelectedLogProbDomainMovementAudit")
            or {}
        ),
        "highGapRankingWeight": float(high_gap_ranking_weight),
        "highGapThreshold": float(high_gap_threshold),
        "policyAnchorKlTraining": bool(sandbox_report.get("policyAnchorKlTraining", False)),
        "anchorKlWeight": float(sandbox_report.get("anchorKlWeight", anchor_kl_weight) or 0.0),
        "anchorKlTemperature": float(sandbox_report.get("anchorKlTemperature", anchor_kl_temperature) or 1.0),
        "anchorKlSource": str(sandbox_report.get("anchorKlSource") or "row_actor_logits"),
        "retentionKlMode": str(sandbox_report.get("retentionKlMode") or "disabled"),
        "retentionKlReport": dict(sandbox_report.get("retentionKlReport") or {}),
        "sandboxTrainingDiagnostics": dict(sandbox_report.get("sandboxTrainingDiagnostics") or {}),
        "actorGradientCollisionAudit": dict(sandbox_report.get("actorGradientCollisionAudit") or {}),
        "trainingResolvedDevice": str(sandbox_report.get("trainingResolvedDevice") or "unknown"),
        "restartSafetyReview": restart_safety_review,
        "playCardTargetSemantics": play_card_target_semantics,
        "playCardTargetSemanticsFilter": play_card_target_semantics_filter,
        "contextOnlyRowsReport": context_only_rows_report,
        "targetActionSemantics": target_action_semantics,
        "targetActionSemanticsFilter": target_action_semantics_filter,
        "preTargetSemanticsRowContractReport": pre_target_semantics_row_contract_report,
        "actionValueSemanticRefresh": {"kind": "not_used_for_current_policy_trajectory_training"},
        "sampledAdvantagePolicyGradientTraining": True,
    }
    report_write_started = perf_counter()
    report["trainingPhaseTimings"]["reportWriteSeconds"] = 0.0
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["trainingPhaseTimings"]["reportWriteSeconds"] = round(max(0.0, perf_counter() - report_write_started), 6)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _cap_current_policy_training_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    max_rows: int | None,
    seed: int,
    preserve_sequence_groups: bool = False,
    copy_rows: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    row_list = [dict(row) for row in rows] if bool(copy_rows) else list(rows)
    enabled = max_rows is not None and int(max_rows) > 0
    if not enabled or len(row_list) <= int(max_rows):
        return row_list, {
            "enabled": bool(enabled),
            "inputRows": int(len(row_list)),
            "maxRows": int(max_rows or 0),
            "outputRows": int(len(row_list)),
            "droppedRows": 0,
            "seed": int(seed),
            "capUnit": (
                "sequence"
                if bool(preserve_sequence_groups) and any(_current_policy_recurrent_sequence_id(row) for row in row_list)
                else ("segment" if any(_current_policy_segment_id(row) for row in row_list) else "row")
            ),
        }
    if bool(preserve_sequence_groups):
        sequence_groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for index, row in enumerate(row_list):
            sequence_id = _current_policy_recurrent_sequence_id(row)
            if not sequence_id:
                sequence_groups = {}
                break
            sequence_groups.setdefault(sequence_id, []).append((index, row))
        if sequence_groups:
            keys = _current_policy_balanced_sequence_cap_order(
                sequence_groups,
                seed=int(seed),
                max_rows=int(max_rows),
            )
            kept: list[tuple[int, dict[str, Any]]] = []
            kept_keys: list[str] = []
            for key in keys:
                sequence = sequence_groups[key]
                if kept and len(kept) + len(sequence) > int(max_rows):
                    continue
                kept.extend(sequence)
                kept_keys.append(key)
                if len(kept) >= int(max_rows):
                    break
            capped = [row for _index, row in sorted(kept, key=lambda item: item[0])]
            report = {
                "enabled": True,
                "inputRows": int(len(row_list)),
                "maxRows": int(max_rows),
                "outputRows": int(len(capped)),
                "droppedRows": int(len(row_list) - len(capped)),
                "seed": int(seed),
                "capUnit": "sequence",
                "inputSequences": int(len(sequence_groups)),
                "outputSequences": int(len({_current_policy_recurrent_sequence_id(row) for row in capped})),
            }
            report.update(_current_policy_balanced_sequence_cap_report(sequence_groups, kept_keys))
            return capped, report
    segment_groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, row in enumerate(row_list):
        segment_id = _current_policy_segment_id(row)
        if not segment_id:
            segment_groups = {}
            break
        segment_groups.setdefault(segment_id, []).append((index, row))
    if segment_groups:
        keys = list(segment_groups)
        random.Random(int(seed)).shuffle(keys)
        kept: list[tuple[int, dict[str, Any]]] = []
        for key in keys:
            segment = segment_groups[key]
            if kept and len(kept) + len(segment) > int(max_rows):
                continue
            kept.extend(segment)
            if len(kept) >= int(max_rows):
                break
        capped = [row for _index, row in sorted(kept, key=lambda item: item[0])]
        return capped, {
            "enabled": True,
            "inputRows": int(len(row_list)),
            "maxRows": int(max_rows),
            "outputRows": int(len(capped)),
            "droppedRows": int(len(row_list) - len(capped)),
            "seed": int(seed),
            "capUnit": "segment",
            "inputSegments": int(len(segment_groups)),
            "outputSegments": int(len({str(row.get('segmentId')) for row in capped})),
        }
    kept_indices = sorted(random.Random(int(seed)).sample(range(len(row_list)), int(max_rows)))
    capped = [row_list[index] for index in kept_indices]
    return capped, {
        "enabled": True,
        "inputRows": int(len(row_list)),
        "maxRows": int(max_rows),
        "outputRows": int(len(capped)),
        "droppedRows": int(len(row_list) - len(capped)),
        "seed": int(seed),
        "capUnit": "row",
    }


def _current_policy_balanced_sequence_cap_order(
    sequence_groups: Mapping[str, list[tuple[int, dict[str, Any]]]],
    *,
    seed: int,
    max_rows: int | None = None,
) -> list[str]:
    rng = random.Random(int(seed))
    terminal_original_buckets: dict[str, list[str]] = {}
    done_original_buckets: dict[str, list[str]] = {}
    other_original_buckets: dict[str, list[str]] = {}
    fallback_keys: list[str] = []
    for key in sequence_groups:
        sequence = sequence_groups[key]
        if _current_policy_sequence_is_current_vs_original(sequence):
            bucket_key = _current_policy_sequence_original48_slice_key(sequence)
            if _current_policy_sequence_is_terminal_backed(sequence):
                terminal_original_buckets.setdefault(bucket_key, []).append(key)
            elif _current_policy_sequence_has_done(sequence):
                done_original_buckets.setdefault(bucket_key, []).append(key)
            else:
                other_original_buckets.setdefault(bucket_key, []).append(key)
        else:
            fallback_keys.append(key)
    for keys in terminal_original_buckets.values():
        rng.shuffle(keys)
    for keys in done_original_buckets.values():
        rng.shuffle(keys)
    for keys in other_original_buckets.values():
        rng.shuffle(keys)
    rng.shuffle(fallback_keys)
    priority_order = (
        _current_policy_round_robin_bucket_keys(terminal_original_buckets)
        + _current_policy_round_robin_bucket_keys(done_original_buckets)
        + _current_policy_round_robin_bucket_keys(other_original_buckets)
        + fallback_keys
    )
    coverage_keys = _current_policy_original_slice_coverage_keys(
        sequence_groups,
        max_rows=max_rows,
    )
    if not coverage_keys:
        return priority_order
    coverage = set(coverage_keys)
    return coverage_keys + [key for key in priority_order if key not in coverage]


def _current_policy_original_slice_coverage_keys(
    sequence_groups: Mapping[str, list[tuple[int, dict[str, Any]]]],
    *,
    max_rows: int | None,
) -> list[str]:
    if max_rows is None or int(max_rows) <= 0:
        return []
    by_slice: dict[str, list[str]] = {}
    for key, sequence in sequence_groups.items():
        if not _current_policy_sequence_is_current_vs_original(sequence):
            continue
        by_slice.setdefault(_current_policy_sequence_original48_slice_key(sequence), []).append(key)
    if len(by_slice) <= 1:
        return []

    def priority(key: str) -> tuple[int, int, str]:
        sequence = sequence_groups[key]
        if _current_policy_sequence_is_terminal_backed(sequence):
            rank = 0
        elif _current_policy_sequence_has_done(sequence):
            rank = 1
        else:
            rank = 2
        return rank, len(sequence), str(key)

    selected = [min(keys, key=priority) for _slice, keys in sorted(by_slice.items()) if keys]
    total_rows = sum(len(sequence_groups[key]) for key in selected)
    if total_rows > int(max_rows):
        return []
    return selected


def _current_policy_round_robin_bucket_keys(buckets: Mapping[str, list[str]]) -> list[str]:
    ordered: list[str] = []
    queues = {bucket: list(keys) for bucket, keys in sorted(buckets.items()) if keys}
    while queues:
        empty: list[str] = []
        for bucket in sorted(queues):
            keys = queues[bucket]
            if keys:
                ordered.append(keys.pop(0))
            if not keys:
                empty.append(bucket)
        for bucket in empty:
            queues.pop(bucket, None)
    return ordered


def _current_policy_balanced_sequence_cap_report(
    sequence_groups: Mapping[str, list[tuple[int, dict[str, Any]]]],
    kept_keys: list[str],
) -> dict[str, Any]:
    kept = set(kept_keys)
    original_input_keys = [
        key
        for key, sequence in sequence_groups.items()
        if _current_policy_sequence_is_current_vs_original(sequence)
    ]
    original_output_keys = [key for key in original_input_keys if key in kept]
    terminal_input_keys = [
        key
        for key, sequence in sequence_groups.items()
        if _current_policy_sequence_is_current_vs_original(sequence)
        and _current_policy_sequence_is_terminal_backed(sequence)
    ]
    terminal_output_keys = [key for key in terminal_input_keys if key in kept]
    done_input_keys = [
        key
        for key, sequence in sequence_groups.items()
        if _current_policy_sequence_is_current_vs_original(sequence)
        and _current_policy_sequence_has_done(sequence)
    ]
    done_output_keys = [key for key in done_input_keys if key in kept]
    return {
        "priorityMode": "original_terminal_done_balanced",
        "inputOriginalSlices": _current_policy_sequence_slice_counts(
            sequence_groups,
            original_input_keys,
        ),
        "outputOriginalSlices": _current_policy_sequence_slice_counts(
            sequence_groups,
            original_output_keys,
        ),
        "terminalOriginalInputSequences": int(len(terminal_input_keys)),
        "terminalOriginalOutputSequences": int(len(terminal_output_keys)),
        "terminalOriginalInputRows": int(
            sum(len(sequence_groups[key]) for key in terminal_input_keys)
        ),
        "terminalOriginalOutputRows": int(
            sum(len(sequence_groups[key]) for key in terminal_output_keys)
        ),
        "outputOriginalTerminalSlices": _current_policy_sequence_slice_counts(
            sequence_groups,
            terminal_output_keys,
        ),
        "doneOriginalInputSequences": int(len(done_input_keys)),
        "doneOriginalOutputSequences": int(len(done_output_keys)),
        "doneOriginalInputRows": int(sum(len(sequence_groups[key]) for key in done_input_keys)),
        "doneOriginalOutputRows": int(sum(len(sequence_groups[key]) for key in done_output_keys)),
        "outputOriginalDoneSlices": _current_policy_sequence_slice_counts(sequence_groups, done_output_keys),
    }


def _current_policy_sequence_slice_counts(
    sequence_groups: Mapping[str, list[tuple[int, dict[str, Any]]]],
    keys: Iterable[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in keys:
        slice_key = _current_policy_sequence_original48_slice_key(sequence_groups[key])
        counts[slice_key] = counts.get(slice_key, 0) + 1
    return dict(sorted(counts.items()))


def _current_policy_sequence_is_current_vs_original(sequence: list[tuple[int, dict[str, Any]]]) -> bool:
    return any(_current_policy_rollout_pool_kind(row) == "current_vs_original" for _index, row in sequence)


def _current_policy_sequence_is_terminal_backed(sequence: list[tuple[int, dict[str, Any]]]) -> bool:
    has_truncated = any(
        _current_policy_row_bool(row, "trajectoryTruncated", "truncated", "fixedStepTruncation")
        for _index, row in sequence
    )
    return bool(_current_policy_sequence_has_done(sequence) and not has_truncated)


def _current_policy_sequence_has_done(sequence: list[tuple[int, dict[str, Any]]]) -> bool:
    return any(_current_policy_row_bool(row, "trajectoryDone", "done", "isTerminal") for _index, row in sequence)


def _current_policy_sequence_original48_slice_key(sequence: list[tuple[int, dict[str, Any]]]) -> str:
    for _index, row in sequence:
        suite = _current_policy_suite_kind(row)
        opponent = _current_policy_runtime_opponent_policy_id(row)
        if suite or opponent:
            return f"{suite or 'unknown'}|{opponent or 'unknown'}"
    return "unknown|unknown"


def _current_policy_rollout_pool_kind(row: Mapping[str, Any]) -> str:
    metadata = _mapping(row.get("metadata"))
    return _first_present_text(
        row.get("rolloutPoolKind"),
        metadata.get("rolloutPoolKind"),
        row.get("poolKind"),
        metadata.get("poolKind"),
    )


def _current_policy_suite_kind(row: Mapping[str, Any]) -> str:
    metadata = _mapping(row.get("metadata"))
    return _first_present_text(row.get("suiteKind"), metadata.get("suiteKind"), row.get("suite"), metadata.get("suite"))


def _current_policy_runtime_opponent_policy_id(row: Mapping[str, Any]) -> str:
    metadata = _mapping(row.get("metadata"))
    return _first_present_text(
        row.get("runtimeOpponentPolicyId"),
        metadata.get("runtimeOpponentPolicyId"),
        row.get("opponentPolicyId"),
        metadata.get("opponentPolicyId"),
        row.get("opponentPolicy"),
        metadata.get("opponentPolicy"),
    )


def _current_policy_row_bool(row: Mapping[str, Any], *keys: str) -> bool:
    metadata = _mapping(row.get("metadata"))
    for key in keys:
        for value in (row.get(key), metadata.get(key)):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"1", "true", "yes", "y", "done"}:
                    return True
                if normalized in {"0", "false", "no", "n", ""}:
                    return False
    return False


def _current_policy_segment_id(row: Mapping[str, Any]) -> str:
    metadata = _mapping(row.get("metadata"))
    return _first_present_text(row.get("segmentId"), metadata.get("segmentId"))


def _current_policy_recurrent_sequence_id(row: Mapping[str, Any]) -> str:
    metadata = _mapping(row.get("metadata"))
    return _first_present_text(
        row.get("sequenceId"),
        metadata.get("sequenceId"),
        row.get("episodeId"),
        metadata.get("episodeId"),
        row.get("taskId"),
        metadata.get("taskId"),
        row.get("segmentId"),
        metadata.get("segmentId"),
    )


def _split_rows_by_sequence_group(
    rows: list[dict[str, Any]],
    *,
    eval_fraction: float,
    shuffle: bool = False,
    seed: int = 2026061340,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bounded = max(0.0, min(0.9, float(eval_fraction)))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        sequence_id = _current_policy_recurrent_sequence_id(row) or f"row:{index}"
        grouped.setdefault(sequence_id, []).append(row)
    groups = [grouped[key] for key in sorted(grouped)]
    if bool(shuffle):
        random.Random(int(seed)).shuffle(groups)
    if bounded <= 0.0 or len(groups) <= 1:
        return [row for group in groups for row in group], []
    eval_count = max(1, int(round(len(groups) * bounded)))
    eval_count = min(eval_count, len(groups) - 1)
    train_groups = groups[:-eval_count]
    eval_groups = groups[-eval_count:]
    return (
        [row for group in train_groups for row in group],
        [row for group in eval_groups for row in group],
    )


def run_ygo_style_current_policy_bootstrap_training(
    *,
    training_rows_path: str | Path | list[str | Path],
    out_dir: str | Path,
    actor_policy_id: str,
    bootstrap_source_policy_id: str,
    training_row_file_weights: list[float] | None = None,
    base_model_path: str | Path | None = None,
    update_epochs: int = 1,
    learning_rate: float = 0.001,
    hidden_dim: int = 64,
    batch_size: int = 32,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    decision_training_weights: Mapping[str, float] | None = None,
    policy_temperature: float = 0.5,
    value_loss_weight: float = 0.25,
    high_gap_ranking_weight: float = 0.25,
    high_gap_threshold: float = DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
    anchor_kl_weight: float = YGO_CURRENT_POLICY_BOOTSTRAP_DEFAULT_ANCHOR_KL_WEIGHT,
    anchor_kl_temperature: float = 1.0,
    bootstrap_target_source: str = "runtime_total",
    base_preserving_base_policy_id: str | None = None,
    base_preserving_delta_score_weight: float = 1.0,
    base_preserving_delta_override_margin: float = 0.0,
    device: str = "auto",
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
    allow_missing_play_card_target_semantics: bool = False,
) -> dict[str, Any]:
    actor_id = str(actor_policy_id or "").strip()
    source_policy_id = str(bootstrap_source_policy_id or "").strip()
    if not actor_id:
        raise ValueError("current-policy bootstrap requires actor_policy_id")
    if not source_policy_id:
        raise ValueError("current-policy bootstrap requires bootstrap_source_policy_id")
    _assert_not_retired_actor0_policy_id(actor_id, context="current-policy bootstrap actor_policy_id")
    _assert_not_retired_actor0_policy_id(source_policy_id, context="current-policy bootstrap source policy id")
    if actor_id == source_policy_id:
        raise ValueError("current-policy bootstrap actor_policy_id must name a new checkpoint")
    resolved_bootstrap_target_source = str(bootstrap_target_source or "runtime_total").strip()
    if resolved_bootstrap_target_source == "selected_action":
        raise ValueError("current-policy bootstrap selected_action target is retired for the YGO actor/value route")
    if resolved_bootstrap_target_source not in {"runtime_total", "runtime_argmax"}:
        raise ValueError("current-policy bootstrap target source must be runtime_total or runtime_argmax")
    if int(update_epochs) < 1:
        raise ValueError("current-policy bootstrap distillation requires at least one epoch")
    base_policy_id = str(base_preserving_base_policy_id or "").strip()
    delta_score_weight = float(base_preserving_delta_score_weight)
    delta_override_margin = float(base_preserving_delta_override_margin)
    if base_policy_id or abs(delta_score_weight - 1.0) > 1.0e-12 or abs(delta_override_margin) > 1.0e-12:
        raise ValueError("current-policy bootstrap emits a direct actor; base-preserving artifacts are diagnostic only")

    training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
    row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
    rows_factory = lambda: _iter_weighted_training_rows(training_paths, row_file_weights)
    sqlite_streaming_bootstrap = _sqlite_training_paths_only(training_paths)
    if sqlite_streaming_bootstrap:
        row_contract_report = _current_policy_bootstrap_row_contract_report_streaming(
            rows_factory,
            bootstrap_source_policy_id=source_policy_id,
        )
    else:
        rows = _load_weighted_training_rows(training_paths, row_file_weights)
        row_contract_report = _current_policy_bootstrap_row_contract_report(
            rows,
            bootstrap_source_policy_id=source_policy_id,
        )
    if int(row_contract_report.get("acceptedRows", 0) or 0) <= 0 or int(
        row_contract_report.get("rejectedRows", 0) or 0
    ):
        raise ValueError(
            "current-policy bootstrap row contract failed: "
            + json.dumps(row_contract_report.get("rejectionReasons") or {}, ensure_ascii=False, sort_keys=True)
        )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    candidate_policy_id = actor_id
    effective_policy_target_source = (
        POLICY_VALUE_TARGET_SOURCE_SELECTED_ACTION_SLOT
        if resolved_bootstrap_target_source == "selected_action"
        else POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_ARGMAX
        if resolved_bootstrap_target_source == "runtime_argmax"
        else POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_TOTAL
    )
    effective_anchor_kl_weight = (
        max(float(YGO_CURRENT_POLICY_BOOTSTRAP_DEFAULT_ANCHOR_KL_WEIGHT), float(anchor_kl_weight))
        if resolved_bootstrap_target_source == "runtime_total"
        else float(anchor_kl_weight)
    )
    effective_value_loss_weight = float(value_loss_weight)
    effective_high_gap_ranking_weight = float(high_gap_ranking_weight)
    streaming_candidate: YgoStyleActionSetPolicyScorer | None = None
    if sqlite_streaming_bootstrap:
        restart_safety_review = assert_restart_safety_clear(
            restart_safety_review_path,
            usage_label="current-policy bootstrap streaming training",
            allow_unreviewed_restart=bool(allow_unreviewed_restart),
        )
        play_card_target_semantics = assert_play_card_target_semantics_safe(
            rows_factory(),
            allow_missing_target_semantics=bool(allow_missing_play_card_target_semantics),
        )
        target_action_semantics = assert_target_action_semantics_safe(rows_factory())
        initial_scorer = _load_initial_scorer(base_model_path)
        base_model_id = _model_id_from_json(base_model_path)
        streaming_candidate = train_ygo_style_full_legal_policy_value_scorer_streaming(
            rows_factory,
            epochs=int(update_epochs),
            learning_rate=float(learning_rate),
            hidden_dim=int(hidden_dim),
            batch_size=int(batch_size),
            seed=int(seed),
            initial_scorer=initial_scorer,
            policy_temperature=float(policy_temperature),
            policy_target_source=effective_policy_target_source,
            value_loss_weight=float(effective_value_loss_weight),
            high_gap_ranking_weight=float(effective_high_gap_ranking_weight),
            high_gap_threshold=float(high_gap_threshold),
            anchor_kl_weight=float(effective_anchor_kl_weight),
            anchor_kl_temperature=float(anchor_kl_temperature),
            anchor_kl_source=POLICY_VALUE_ANCHOR_SOURCE_ROW_RUNTIME_TOTAL,
            decision_training_weights=decision_training_weights,
            device=str(device),
        )
        eval_rows = _collect_streaming_eval_rows(rows_factory, max_rows=512)
        candidate_eval = (
            evaluate_ygo_style_full_legal_policy_value_scorer(
                streaming_candidate,
                eval_rows,
                policy_temperature=float(policy_temperature),
                policy_target_source=effective_policy_target_source,
            )
            if eval_rows
            else None
        )
        base_eval = (
            evaluate_ygo_style_full_legal_policy_value_scorer(
                initial_scorer,
                eval_rows,
                policy_temperature=float(policy_temperature),
                policy_target_source=effective_policy_target_source,
            )
            if initial_scorer is not None and eval_rows
            else None
        )
        sandbox_report = {
            "kind": YGO_STYLE_SANDBOX_POLICY_VALUE_TRAINING_VERSION,
            "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
            "trainingRowsSource": _training_rows_source_value(training_paths),
            "trainingRowFileWeights": list(row_file_weights),
            "trainingRowsLoadMode": "sqlite_streaming_batches",
            "baseModelPath": str(base_model_path) if base_model_path is not None else None,
            "baseModelId": base_model_id,
            "candidateModelId": candidate_policy_id,
            "candidateModelPath": str(out_path / "self_improvement_current_policy_actor_value_model.pt"),
            "candidateCheckpointPath": str(out_path / "self_improvement_current_policy_actor_value_model.pt"),
            "reportPath": str(out_path / "ygo_style_sandbox_policy_value_training_report.json"),
            "rowCount": int(row_contract_report.get("inputRows", 0) or 0),
            "candidateFullLegalRows": int(row_contract_report.get("inputRows", 0) or 0),
            "usableFullLegalRows": int(row_contract_report.get("acceptedRows", 0) or 0),
            "targetContract": ACTION_VALUE_TARGET_CONTRACT,
            "targetContractReport": {"streaming": True, "acceptedRows": int(row_contract_report.get("acceptedRows", 0) or 0)},
            "restartSafetyReview": restart_safety_review,
            "allowUnreviewedRestart": bool(allow_unreviewed_restart),
            "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
            "playCardTargetSemantics": play_card_target_semantics,
            "targetActionSemantics": target_action_semantics,
            "actionValueSemanticRefresh": {"kind": "not_used_for_sqlite_streaming_bootstrap", "streaming": True},
            "trainRows": int(row_contract_report.get("acceptedRows", 0) or 0),
            "evalRows": int(len(eval_rows)),
            "epochs": int(update_epochs),
            "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
            "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
            "updateEpochs": int(update_epochs),
            "learningRate": float(learning_rate),
            "hiddenDim": int(streaming_candidate.hiddenDim),
            "batchSize": int(batch_size),
            "seed": int(seed),
            "shuffleRowsRequested": False,
            "effectiveShuffleRows": False,
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "objectCardFeaturesUsed": None,
            "sourceTargetCardRefsUsed": None,
            "globalFeatureCount": len(streaming_candidate.globalFeatureNames),
            "actionFeatureCount": len(streaming_candidate.actionFeatureNames),
            "cardFeatureCount": len(streaming_candidate.cardFeatureNames),
            "inputDim": int(streaming_candidate.inputDim),
            "candidateSandboxPolicyValueTrainEval": candidate_eval,
            "candidateSandboxPolicyValueEval": candidate_eval,
            "baseSandboxPolicyValueTrainEval": base_eval,
            "baseSandboxPolicyValueEval": base_eval,
            "policyTarget": (
                "softmax(row_runtime_total)"
                if effective_policy_target_source == POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_TOTAL
                else "argmax(row_runtime_total)"
                if effective_policy_target_source == POLICY_VALUE_TARGET_SOURCE_ROW_RUNTIME_ARGMAX
                else "one_hot(selectedActionSlot)"
            ),
            "policyTargetSource": effective_policy_target_source,
            "stateValueTarget": "soft_policy_expected_action_value",
            "sandboxTrainingDiagnostics": dict(streaming_candidate.runtimeAuxTrainingDiagnostics or {}),
            "policyAnchorKlTraining": bool(streaming_candidate.policyAnchorKlTraining),
            "anchorKlWeight": float(streaming_candidate.anchorKlWeight),
            "anchorKlTemperature": float(streaming_candidate.anchorKlTemperature),
            "anchorKlSource": POLICY_VALUE_ANCHOR_SOURCE_ROW_RUNTIME_TOTAL,
            "scratchTraining": initial_scorer is None,
            "trainingResolvedDevice": str(streaming_candidate.trainingResolvedDevice),
        }
    else:
        sandbox_report = run_ygo_style_sandbox_policy_value_training(
            training_rows_path=training_paths,
            out_dir=out_path,
            candidate_model_id=candidate_policy_id,
            training_row_file_weights=row_file_weights,
            base_model_path=base_model_path,
            epochs=int(update_epochs),
            learning_rate=float(learning_rate),
            hidden_dim=int(hidden_dim),
            batch_size=int(batch_size),
            eval_fraction=float(eval_fraction),
            seed=int(seed),
            shuffle_rows=True,
            decision_training_weights=decision_training_weights,
            policy_temperature=float(policy_temperature),
            policy_target_source=effective_policy_target_source,
            value_loss_weight=float(effective_value_loss_weight),
            high_gap_ranking_weight=float(effective_high_gap_ranking_weight),
            high_gap_threshold=float(high_gap_threshold),
            anchor_kl_weight=float(effective_anchor_kl_weight),
            anchor_kl_temperature=float(anchor_kl_temperature),
            anchor_kl_source=POLICY_VALUE_ANCHOR_SOURCE_ROW_RUNTIME_TOTAL,
            device=str(device),
            restart_safety_review_path=restart_safety_review_path,
            allow_unreviewed_restart=bool(allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(allow_missing_play_card_target_semantics),
        )
        _assert_current_policy_usable_rows_match_contract(
            sandbox_report,
            row_contract_report,
            context="current-policy bootstrap training",
        )
    gate_eligibility = _current_policy_clone_gate_eligibility(
        row_contract_report=row_contract_report,
        sandbox_report=sandbox_report,
    )
    bootstrap_source_eligible = False

    source_model_path = Path(str(sandbox_report["candidateModelPath"]))
    if streaming_candidate is not None:
        model_dict = streaming_candidate.to_dict()
    else:
        model_dict = dict(_load_ygo_style_model_payload(source_model_path))
    model_dict.pop("currentPolicyRowContractReport", None)
    model_path = out_path / "self_improvement_current_policy_actor_value_model.json"
    checkpoint_path = out_path / "self_improvement_current_policy_actor_value_model.pt"
    report_path = out_path / "ygo_style_current_policy_training_report.json"
    model_dict.update(
        {
            "modelId": candidate_policy_id,
            "trainingMode": YGO_STYLE_CURRENT_POLICY_TRAINING_VERSION,
            "trainingReportPath": str(report_path),
            "trainingMainline": "unified_current_policy_actor_value",
            "basePolicyRole": "bootstrap_source_reference_only",
            "actorPolicyId": candidate_policy_id,
            "sourceActorPolicyId": source_policy_id,
            "candidatePolicyId": candidate_policy_id,
            "basePreservingActor": False,
            "basePolicyId": None,
            "deltaScoreWeight": 1.0,
            "deltaOverrideMargin": 0.0,
            "bootstrapInitialization": True,
            "behaviorCloneTraining": False,
            "runtimeScoreDistillTraining": True,
            "runtimeSelectedActionDistillTraining": resolved_bootstrap_target_source == "selected_action",
            "bootstrapTargetSource": resolved_bootstrap_target_source,
            "currentPolicyBootstrapSourceEligible": bool(bootstrap_source_eligible),
            "bootstrapCloneEpochs": 0,
            "bootstrapDistillEpochs": int(update_epochs),
            "bootstrapSourcePolicyId": source_policy_id,
            "bootstrapTrainingRowsSource": "strict_runtime_total_full_legal_action_value_rows",
            "runtimeLaunchableActor": True,
            "actorNSourceEligible": bool(bootstrap_source_eligible),
            "runtimeSelectionInterface": "zz.current_policy_runtime.masked_argmax_action",
            "runtimeRowContract": "zz.current_policy_runtime.validate_current_policy_row",
            "currentPolicyBootstrapRowContractReport": row_contract_report,
            "sandboxOnly": False,
            "gateEligible": bool(gate_eligibility["gateEligible"]),
            "gateEligibility": gate_eligibility,
            "gateEligibilityReasons": list(gate_eligibility["blockingReasons"]),
            "requiresCurrentPolicyBridgeAuditBeforeGate": True,
            "directPolicyRuntimeAuthority": True,
            "unifiedMaskedActorValueTraining": True,
            "activePolicyRequiredForGameplayClaim": True,
            "sidecarListwiseTraining": False,
            "residualSidecarTraining": False,
            "runtimeCalibratedSidecarTraining": False,
            "fullDirectPolicyTraining": True,
            "selectedActionImitation": False,
            "fullLegalActionSetTraining": True,
            "trainingObjective": "v137_runtime_score_distilled_current_policy_actor",
            "policyTarget": sandbox_report.get("policyTarget"),
            "policyTargetSource": effective_policy_target_source,
            "sourceSandboxModelPath": str(source_model_path),
            "sourceSandboxTrainingReportPath": str(sandbox_report.get("reportPath") or ""),
            "policyAnchorKlTraining": bool(sandbox_report.get("policyAnchorKlTraining", False)),
            "anchorKlWeight": float(sandbox_report.get("anchorKlWeight", effective_anchor_kl_weight) or 0.0),
            "anchorKlTemperature": float(sandbox_report.get("anchorKlTemperature", anchor_kl_temperature) or 1.0),
            "anchorKlSource": str(
                sandbox_report.get("anchorKlSource") or POLICY_VALUE_ANCHOR_SOURCE_ROW_RUNTIME_TOTAL
            ),
            "sandboxTrainingDiagnostics": dict(sandbox_report.get("sandboxTrainingDiagnostics") or {}),
            "scratchTraining": bool(sandbox_report.get("scratchTraining", False)),
            "scratchJustification": (
                "A0 runtime-score distillation starts from a new actor; direct battle gate decides promotion"
                if bool(sandbox_report.get("scratchTraining", False))
                else None
            ),
        }
    )
    _write_ygo_style_model_pt(checkpoint_path, model_dict)
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict[str, Any] = {
        "kind": YGO_STYLE_CURRENT_POLICY_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingMainline": "unified_current_policy_actor_value",
        "basePolicyRole": "bootstrap_source_reference_only",
        "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
        "trainingRowsSource": _training_rows_source_value(training_paths),
        "trainingRowFileWeights": list(row_file_weights),
        "actorPolicyId": candidate_policy_id,
        "sourceActorPolicyId": source_policy_id,
        "candidatePolicyId": candidate_policy_id,
        "basePreservingActor": False,
        "basePolicyId": None,
        "deltaScoreWeight": 1.0,
        "deltaOverrideMargin": 0.0,
        "bootstrapInitialization": True,
        "behaviorCloneTraining": False,
        "runtimeScoreDistillTraining": True,
        "runtimeSelectedActionDistillTraining": resolved_bootstrap_target_source == "selected_action",
        "bootstrapTargetSource": resolved_bootstrap_target_source,
        "currentPolicyBootstrapSourceEligible": bool(bootstrap_source_eligible),
        "bootstrapSourcePolicyId": source_policy_id,
        "bootstrapTrainingRowsSource": "strict_runtime_total_full_legal_action_value_rows",
        "candidateModelPath": str(model_path),
        "candidateCheckpointPath": str(checkpoint_path),
        "candidateRuntimeJsonPath": str(model_path),
        "trainingRowsLoadMode": (
            "sqlite_streaming_batches"
            if sqlite_streaming_bootstrap
            else "legacy_full_load"
        ),
        "reportPath": str(report_path),
        "sourceSandboxModelPath": str(source_model_path),
        "sourceSandboxTrainingReportPath": str(sandbox_report.get("reportPath") or ""),
        "rowCount": int(sandbox_report.get("rowCount", 0) or 0),
        "usableFullLegalRows": int(sandbox_report.get("usableFullLegalRows", 0) or 0),
        "trainRows": int(sandbox_report.get("trainRows", 0) or 0),
        "evalRows": int(sandbox_report.get("evalRows", 0) or 0),
        "epochs": int(update_epochs),
        "updateEpochs": int(update_epochs),
        "bootstrapCloneEpochs": 0,
        "bootstrapDistillEpochs": int(update_epochs),
        "learningRate": float(learning_rate),
        "hiddenDim": int(sandbox_report.get("hiddenDim", hidden_dim) or hidden_dim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        "runtimeLaunchableActor": True,
        "actorNSourceEligible": bool(bootstrap_source_eligible),
        "runtimeSelectionInterface": "zz.current_policy_runtime.masked_argmax_action",
        "runtimeRowContract": "zz.current_policy_runtime.validate_current_policy_row",
        "currentPolicyBootstrapRowContractReport": row_contract_report,
        "fullLegalActionSetTraining": True,
        "unifiedMaskedActorValueTraining": True,
        "trainingObjective": "v137_runtime_score_distilled_current_policy_actor",
        "policyTarget": sandbox_report.get("policyTarget"),
        "policyTargetSource": effective_policy_target_source,
        "stateValueTarget": "soft_policy_expected_action_value",
        "sidecarListwiseTraining": False,
        "residualSidecarTraining": False,
        "runtimeCalibratedSidecarTraining": False,
        "fullDirectPolicyTraining": True,
        "directPolicyRuntimeAuthority": True,
        "sandboxOnly": False,
        "gateEligible": bool(gate_eligibility["gateEligible"]),
        "gateEligibility": gate_eligibility,
        "gateEligibilityReasons": list(gate_eligibility["blockingReasons"]),
        "requiresCurrentPolicyBridgeAuditBeforeGate": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
        "defaultRuntimeChanged": False,
        "trainingLaunched": True,
        "scratchTraining": bool(sandbox_report.get("scratchTraining", False)),
        "scratchJustification": (
            "A0 runtime-score distillation starts from a new actor; direct battle gate decides promotion"
            if bool(sandbox_report.get("scratchTraining", False))
            else None
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "candidateCurrentPolicyTrainEval": sandbox_report.get("candidateSandboxPolicyValueTrainEval"),
        "candidateCurrentPolicyEval": sandbox_report.get("candidateSandboxPolicyValueEval"),
        "candidateBehaviorCloneTrainEval": (
            None
        ),
        "candidateBehaviorCloneEval": (
            None
        ),
        "candidateRuntimeScoreDistillTrainEval": sandbox_report.get("candidateSandboxPolicyValueTrainEval"),
        "candidateRuntimeScoreDistillEval": sandbox_report.get("candidateSandboxPolicyValueEval"),
        "baseCurrentPolicyTrainEval": sandbox_report.get("baseSandboxPolicyValueTrainEval"),
        "baseCurrentPolicyEval": sandbox_report.get("baseSandboxPolicyValueEval"),
        "policyTemperature": float(policy_temperature),
        "valueLossWeight": float(effective_value_loss_weight),
        "highGapRankingWeight": float(effective_high_gap_ranking_weight),
        "highGapThreshold": float(high_gap_threshold),
        "policyAnchorKlTraining": bool(sandbox_report.get("policyAnchorKlTraining", False)),
        "anchorKlWeight": float(sandbox_report.get("anchorKlWeight", effective_anchor_kl_weight) or 0.0),
        "anchorKlTemperature": float(sandbox_report.get("anchorKlTemperature", anchor_kl_temperature) or 1.0),
        "anchorKlSource": str(sandbox_report.get("anchorKlSource") or POLICY_VALUE_ANCHOR_SOURCE_ROW_RUNTIME_TOTAL),
        "sandboxTrainingDiagnostics": dict(sandbox_report.get("sandboxTrainingDiagnostics") or {}),
        "trainingResolvedDevice": str(sandbox_report.get("trainingResolvedDevice") or "unknown"),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _assert_current_policy_usable_rows_match_contract(
    sandbox_report: Mapping[str, Any],
    row_contract_report: Mapping[str, Any],
    *,
    context: str,
) -> None:
    if "usableFullLegalRows" not in sandbox_report:
        raise ValueError(f"{context} sandbox report missing usableFullLegalRows")
    usable_rows = int(sandbox_report.get("usableFullLegalRows") or 0)
    accepted_rows = int(row_contract_report.get("acceptedRows") or 0)
    if usable_rows != accepted_rows:
        raise ValueError(
            f"{context} usableFullLegalRows mismatch: "
            f"contract acceptedRows={accepted_rows}, usableFullLegalRows={usable_rows}"
        )
    diagnostics = sandbox_report.get("sandboxTrainingDiagnostics")
    if "trainRows" not in sandbox_report or "evalRows" not in sandbox_report:
        raise ValueError(f"{context} sandbox report missing trainRows/evalRows")
    train_rows = int(sandbox_report.get("trainRows") or 0)
    eval_rows = int(sandbox_report.get("evalRows") or 0)
    if train_rows <= 0 or train_rows > accepted_rows:
        raise ValueError(
            f"{context} trainRows mismatch: "
            f"contract acceptedRows={accepted_rows}, trainRows={train_rows}"
        )
    if eval_rows < 0 or eval_rows > accepted_rows:
        raise ValueError(
            f"{context} evalRows mismatch: "
            f"contract acceptedRows={accepted_rows}, evalRows={eval_rows}"
        )
    if isinstance(diagnostics, Mapping) and "trainedRows" in diagnostics:
        trained_rows = int(diagnostics.get("trainedRows") or 0)
        if trained_rows != train_rows:
            raise ValueError(
                f"{context} trainedRows mismatch: "
                f"trainRows={train_rows}, trainedRows={trained_rows}"
            )


def run_ygo_style_trajectory_advantage_runtime_training(
    *,
    training_rows_path: str | Path | list[str | Path],
    out_dir: str | Path,
    candidate_model_id: str,
    training_row_file_weights: list[float] | None = None,
    base_model_path: str | Path | None = None,
    epochs: int = YGO_DEFAULT_UPDATE_EPOCHS,
    learning_rate: float | None = None,
    hidden_dim: int = 64,
    batch_size: int = 256,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    shuffle_rows: bool = False,
    include_decision_kinds: Iterable[str] | None = None,
    allow_route_isolated_diagnostic_training: bool = False,
    allow_route_limited_launch_training: bool = False,
    decision_training_weights: Mapping[str, float] | None = None,
    runtime_aux_score_weight: float = 0.03,
    runtime_aux_output_scale: float | None = None,
    ppo_clip_coef: float = 0.2,
    full_legal_policy_objective: str = FULL_LEGAL_POLICY_OBJECTIVE_SEARCH_IMPROVED_CE,
    policy_improvement_temperature: float = 1.0,
    base_correct_preserve_weight: float = FULL_LEGAL_SEARCH_IMPROVED_BASE_CORRECT_PRESERVE_WEIGHT,
    entropy_coef: float = 0.0,
    value_loss_weight: float = 0.25,
    normalize_advantages: bool = False,
    anchor_kl_weight: float = 0.0,
    anchor_kl_temperature: float = 1.0,
    anchor_kl_decision_weights: Mapping[str, float] | None = None,
    device: str = "auto",
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
    allow_missing_play_card_target_semantics: bool = False,
    expected_runtime_policy_id: str | None = None,
) -> dict[str, Any]:
    restart_safety_review = assert_restart_safety_clear(
        restart_safety_review_path,
        usage_label="trajectory advantage runtime training",
        allow_unreviewed_restart=bool(allow_unreviewed_restart),
    )
    training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
    row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
    sqlite_streaming_rows = all(path.suffix.lower() in SQLITE_TRAINING_ROW_SUFFIXES for path in training_paths)
    if sqlite_streaming_rows:
        (
            rows,
            action_value_semantic_refresh,
            action_value_trajectory_report,
            converted_action_value_trajectory_rows,
            raw_row_count,
        ) = _load_streamed_trajectory_advantage_rows_from_sqlite(
            training_paths,
            row_file_weights,
            source_label="trajectory_advantage_runtime_training_load",
        )
        action_value_trajectory_rows: list[dict[str, Any]] = []
    else:
        rows = _load_weighted_training_rows(training_paths, row_file_weights)
        raw_row_count = len(rows)
        rows, action_value_semantic_refresh = _refresh_action_value_semantics_for_training(
            rows,
            source_label="trajectory_advantage_runtime_training_load",
        )
        action_value_trajectory_rows, action_value_trajectory_report = (
            _trajectory_advantage_rows_from_full_legal_action_values(rows)
        )
        converted_action_value_trajectory_rows = len(action_value_trajectory_rows)
        rows = [*rows, *action_value_trajectory_rows]
    usable_rows = [
        row
        for row in rows
        if _ygo_trajectory_policy_label(row) is not None and _ygo_legal_slots(row)
    ]
    _reject_route_filter_unless_diagnostic(
        include_decision_kinds,
        allow_route_isolated_diagnostic_training=bool(allow_route_isolated_diagnostic_training),
        allow_route_limited_launch_training=bool(allow_route_limited_launch_training),
    )
    usable_rows, training_decision_kind_filter = _filter_rows_by_included_decision_kinds(
        usable_rows,
        include_decision_kinds=include_decision_kinds,
    )
    route_isolated_training = bool(training_decision_kind_filter.get("enabled"))
    route_limited_launch_training = bool(route_isolated_training and allow_route_limited_launch_training)
    route_isolated_diagnostic_training = bool(
        route_isolated_training and not route_limited_launch_training
    )
    _emit_training_progress(
        "trajectory_rows_loaded",
        rawRows=int(raw_row_count),
        usableRows=int(len(usable_rows)),
        convertedActionValueTrajectoryRows=int(converted_action_value_trajectory_rows),
        sqliteStreaming=bool(action_value_semantic_refresh.get("streaming")),
    )
    if not usable_rows:
        raise ValueError("trajectory advantage runtime training requires at least one usable trajectory row")
    if sqlite_streaming_rows:
        usable_rows, runtime_row_total_contract_report = _filter_rows_by_runtime_row_total_contract_fast(
            usable_rows,
            identity_contract="already_checked_during_streaming_conversion",
        )
    else:
        usable_rows, runtime_row_total_contract_report = _filter_rows_by_runtime_row_total_contract(usable_rows)
    _emit_training_progress(
        "trajectory_runtime_contract",
        acceptedRows=int(len(usable_rows)),
        rejectedRows=int(runtime_row_total_contract_report.get("rejectedRows", 0) or 0),
        acceptedStateGroups=int(runtime_row_total_contract_report.get("acceptedStateGroups", 0) or 0),
    )
    if not usable_rows:
        raise ValueError(
            "trajectory advantage runtime training found no rows with row runtime total; "
            f"contract={runtime_row_total_contract_report}"
        )
    play_card_target_semantics = assert_play_card_target_semantics_safe(
        usable_rows,
        allow_missing_target_semantics=bool(allow_missing_play_card_target_semantics),
    )
    target_action_semantics = assert_target_action_semantics_safe(usable_rows)
    effective_shuffle_rows = _effective_ygo_train_eval_shuffle(shuffle_rows)
    train_rows, eval_rows = _split_rows_by_cheap_runtime_group(
        usable_rows,
        eval_fraction=float(eval_fraction),
        shuffle=effective_shuffle_rows,
        seed=int(seed),
    )
    trajectory_split_mode = "decision_stratified_strict_action_set_group"
    if not eval_rows:
        eval_rows = train_rows
    _emit_training_progress(
        "trajectory_split_ready",
        trainRows=int(len(train_rows)),
        evalRows=int(len(eval_rows)),
    )

    initial_scorer = _load_initial_scorer(base_model_path)
    if initial_scorer is None:
        raise ValueError("trajectory advantage runtime training requires --base-model-path")
    base_model_id = _model_id_from_json(base_model_path)
    resolved_expected_runtime_policy_id = str(expected_runtime_policy_id or base_model_id or "").strip()
    runtime_policy_contract_report = _assert_runtime_policy_id_contract(
        usable_rows,
        expected_runtime_policy_id=resolved_expected_runtime_policy_id,
    )
    resolved_learning_rate = float(learning_rate) if learning_rate is not None else YGO_RUNTIME_AUX_DEFAULT_LEARNING_RATE
    learning_rate_source = "explicit" if learning_rate is not None else "runtime_aux_default"
    bounded_runtime_aux_score_weight = float(runtime_aux_score_weight)
    if bounded_runtime_aux_score_weight <= 0.0:
        raise ValueError("runtime_aux_score_weight must be positive")
    bounded_runtime_aux_output_scale = resolve_runtime_aux_output_scale(
        runtime_aux_output_scale,
        runtime_aux_score_weight=bounded_runtime_aux_score_weight,
    )
    if runtime_aux_output_scale is not None and float(runtime_aux_output_scale) <= 0.0:
        raise ValueError("runtime_aux_output_scale must be positive")
    normalized_decision_training_weights = _normalized_anchor_kl_decision_weights(decision_training_weights)
    bounded_anchor_kl_weight = max(0.0, float(anchor_kl_weight))
    bounded_anchor_kl_temperature = max(1.0e-6, float(anchor_kl_temperature))
    normalized_anchor_kl_decision_weights = _normalized_anchor_kl_decision_weights(anchor_kl_decision_weights)
    _emit_training_progress(
        "trajectory_train_start",
        epochs=int(epochs),
        batchSize=int(batch_size),
        device=str(device),
    )
    candidate = train_ygo_style_trajectory_advantage_runtime_scorer(
        train_rows,
        epochs=int(epochs),
        learning_rate=float(resolved_learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        seed=int(seed),
        initial_scorer=initial_scorer,
        runtime_base_scorer=initial_scorer,
        runtime_aux_score_weight=bounded_runtime_aux_score_weight,
        runtime_aux_output_scale=bounded_runtime_aux_output_scale,
        ppo_clip_coef=float(ppo_clip_coef),
        full_legal_policy_objective=str(full_legal_policy_objective),
        policy_improvement_temperature=float(policy_improvement_temperature),
        base_correct_preserve_weight=float(base_correct_preserve_weight),
        entropy_coef=float(entropy_coef),
        value_loss_weight=float(value_loss_weight),
        normalize_advantages=bool(normalize_advantages),
        require_row_runtime_total=True,
        require_runtime_policy_provenance=True,
        decision_training_weights=normalized_decision_training_weights,
        anchor_kl_weight=bounded_anchor_kl_weight,
        anchor_kl_temperature=bounded_anchor_kl_temperature,
        anchor_kl_decision_weights=normalized_anchor_kl_decision_weights,
        device=str(device),
    )
    _emit_training_progress("trajectory_train_done")
    candidate_eval = _trajectory_advantage_runtime_eval(
        candidate,
        eval_rows,
        runtime_base_scorer=initial_scorer,
        runtime_aux_score_weight=bounded_runtime_aux_score_weight,
    )
    _emit_training_progress(
        "trajectory_eval_done",
        total=int(candidate_eval.get("total", 0) or 0),
        directionAccuracy=float(candidate_eval.get("directionAccuracy", 0.0) or 0.0),
        weightedDirectionAccuracy=float(candidate_eval.get("weightedDirectionAccuracy", 0.0) or 0.0),
    )
    runtime_aux_training_diagnostics = dict(getattr(candidate, "runtimeAuxTrainingDiagnostics", {}) or {})
    training_runtime_source_rows = dict(runtime_aux_training_diagnostics.get("runtimeBaseScoreSourceRows") or {})

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_path = out_path / "self_improvement_pilot_listwise_scorer_model.json"
    report_path = out_path / "ygo_style_trajectory_advantage_runtime_training_report.json"
    model_dict = candidate.to_dict()
    model_dict.update(
        {
            "modelId": str(candidate_model_id),
            "trainingMode": YGO_STYLE_TRAJECTORY_ADVANTAGE_RUNTIME_TRAINING_VERSION,
            "trainingReportPath": str(report_path),
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "baseModelPath": str(base_model_path) if base_model_path is not None else None,
            "baseModelId": base_model_id,
            "expectedRuntimePolicyId": resolved_expected_runtime_policy_id or None,
            "runtimePolicyContractReport": runtime_policy_contract_report,
            "scratchTraining": False,
            "scratchJustification": None,
            "defaultRuntimeChanged": False,
            "activePolicyRequiredForGameplayClaim": True,
            "trainingRowFileWeights": list(row_file_weights),
            "sidecarListwiseTraining": False,
            "fullDirectPolicyTraining": False,
            "directPolicyRuntimeAuthority": False,
            "scoringTopology": YGO_SCORING_TOPOLOGY_UNIFIED_FULL_LEGAL,
            "routeSpecificScoring": False,
            "routeSpecificHeads": False,
            "allowSelectedActionFallback": False,
            "selectedActionImitation": False,
            "directPolicyTargetMode": TRAJECTORY_ADVANTAGE_RUNTIME_SIDECAR_TARGET_MODE,
            "fullLegalActionSetTraining": True,
            "trainingObjective": "trajectory_advantage_runtime_residual_policy_gradient",
            "runtimeCalibratedSidecarTraining": True,
            "runtimeAuxScoreWeight": bounded_runtime_aux_score_weight,
            "runtimeAuxOutputScale": float(bounded_runtime_aux_output_scale),
            "runtimeAuxTrainingObjective": RUNTIME_AUX_TRAINING_OBJECTIVE_TRAJECTORY_ADVANTAGE,
            "runtimeAuxTrainingDiagnostics": runtime_aux_training_diagnostics,
            "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
            "anchorKlWeight": float(bounded_anchor_kl_weight),
            "anchorKlTemperature": float(bounded_anchor_kl_temperature),
            "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
            "sidecarInitialization": runtime_aux_training_diagnostics.get("sidecarInitialization"),
            "runtimeTrainingBaseScoreSource": _runtime_base_score_source_summary(
                row_runtime_base_groups=int(training_runtime_source_rows.get("rowRuntimeTotal", 0) or 0),
                scorer_runtime_base_groups=int(training_runtime_source_rows.get("scorerRuntimeBase", 0) or 0),
            ),
            "runtimeTrainingBaseScoreSourceRows": training_runtime_source_rows,
            "runtimeBaseScoreSource": candidate_eval.get("runtimeBaseScoreSource"),
            "outcomePolicyGradientTraining": True,
            "ppoClipCoef": float(ppo_clip_coef),
            "fullLegalPolicyObjective": str(full_legal_policy_objective),
            "policyImprovementTemperature": float(policy_improvement_temperature),
            "baseCorrectPreserveWeight": float(base_correct_preserve_weight),
            "entropyCoef": float(entropy_coef),
            "valueLossWeight": float(value_loss_weight),
            "normalizeAdvantages": bool(normalize_advantages),
            "trajectorySplitMode": trajectory_split_mode,
            "runtimeRowTotalContractReport": runtime_row_total_contract_report,
            "trainingDecisionKindFilter": training_decision_kind_filter,
            "routeIsolatedTrainingDiagnosticOnly": bool(route_isolated_diagnostic_training),
            "routeLimitedLaunchTraining": bool(route_limited_launch_training),
            "allowRouteIsolatedDiagnosticTraining": bool(allow_route_isolated_diagnostic_training),
            "allowRouteLimitedLaunchTraining": bool(allow_route_limited_launch_training),
            "restartSafetyReview": restart_safety_review,
            "allowUnreviewedRestart": bool(allow_unreviewed_restart),
            "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
            "playCardTargetSemantics": play_card_target_semantics,
            "targetActionSemantics": target_action_semantics,
            "actionValueSemanticRefresh": action_value_semantic_refresh,
            "actionValueTrajectoryConversion": action_value_trajectory_report,
            "convertedActionValueTrajectoryRows": int(converted_action_value_trajectory_rows),
            "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
            "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
            "updateEpochs": int(epochs),
            "learningRateSource": learning_rate_source,
            "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        }
    )
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict[str, Any] = {
        "kind": YGO_STYLE_TRAJECTORY_ADVANTAGE_RUNTIME_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
        "trainingRowsSource": _training_rows_source_value(training_paths),
        "trainingRowFileWeights": list(row_file_weights),
        "trainingRowEffectiveWeightSum": _effective_training_weight_sum(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "trainingRowEffectiveWeightByDecision": _effective_training_weight_by_decision(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "baseModelId": base_model_id,
        "expectedRuntimePolicyId": resolved_expected_runtime_policy_id or None,
        "runtimePolicyContractReport": runtime_policy_contract_report,
        "candidateModelId": str(candidate_model_id),
        "candidateModelPath": str(model_path),
        "reportPath": str(report_path),
        "rowCount": int(raw_row_count),
        "usableTrajectoryRows": len(usable_rows),
        "trainingDecisionKindFilter": training_decision_kind_filter,
        "routeIsolatedTrainingDiagnosticOnly": bool(route_isolated_diagnostic_training),
        "routeLimitedLaunchTraining": bool(route_limited_launch_training),
        "allowRouteIsolatedDiagnosticTraining": bool(allow_route_isolated_diagnostic_training),
        "allowRouteLimitedLaunchTraining": bool(allow_route_limited_launch_training),
        "trainingObjective": "trajectory_advantage_runtime_residual_policy_gradient",
        "restartSafetyReview": restart_safety_review,
        "allowUnreviewedRestart": bool(allow_unreviewed_restart),
        "allowMissingPlayCardTargetSemantics": bool(allow_missing_play_card_target_semantics),
        "playCardTargetSemantics": play_card_target_semantics,
        "targetActionSemantics": target_action_semantics,
        "actionValueSemanticRefresh": action_value_semantic_refresh,
        "actionValueTrajectoryConversion": action_value_trajectory_report,
        "convertedActionValueTrajectoryRows": int(converted_action_value_trajectory_rows),
        "runtimeRowTotalContractReport": runtime_row_total_contract_report,
        "trainRows": len(train_rows),
        "evalRows": len(eval_rows),
        "epochs": int(epochs),
        "freshDataCanaryWorkflow": YGO_FRESH_DATA_CANARY_WORKFLOW_VERSION,
        "defaultUpdateEpochs": YGO_DEFAULT_UPDATE_EPOCHS,
        "updateEpochs": int(epochs),
        "learningRate": float(resolved_learning_rate),
        "learningRateSource": learning_rate_source,
        "hiddenDim": int(candidate.hiddenDim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        **_shuffle_rows_report_fields(shuffle_rows),
        "trajectorySplitMode": trajectory_split_mode,
        "featureFamily": YGO_STYLE_FEATURE_FAMILY,
        "objectCardFeaturesUsed": any(isinstance(row.get("cards_"), list) and row.get("cards_") for row in usable_rows),
        "sourceTargetCardRefsUsed": any(_row_has_source_or_target_ref(row) for row in usable_rows),
        "globalFeatureCount": len(candidate.globalFeatureNames),
        "actionFeatureCount": len(candidate.actionFeatureNames),
        "cardFeatureCount": len(candidate.cardFeatureNames),
        "inputDim": int(candidate.inputDim),
        "candidateTrajectoryAdvantageRuntimeEval": candidate_eval,
        "runtimeBaseScoreSource": candidate_eval.get("runtimeBaseScoreSource"),
        "runtimeCalibratedSidecarTraining": True,
        "runtimeAuxScoreWeight": bounded_runtime_aux_score_weight,
        "runtimeAuxOutputScale": float(bounded_runtime_aux_output_scale),
        "runtimeAuxTrainingObjective": RUNTIME_AUX_TRAINING_OBJECTIVE_TRAJECTORY_ADVANTAGE,
        "runtimeAuxTrainingDiagnostics": runtime_aux_training_diagnostics,
        "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
        "anchorKlWeight": float(bounded_anchor_kl_weight),
        "anchorKlTemperature": float(bounded_anchor_kl_temperature),
        "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
        "sidecarInitialization": runtime_aux_training_diagnostics.get("sidecarInitialization"),
        "runtimeTrainingBaseScoreSource": _runtime_base_score_source_summary(
            row_runtime_base_groups=int(training_runtime_source_rows.get("rowRuntimeTotal", 0) or 0),
            scorer_runtime_base_groups=int(training_runtime_source_rows.get("scorerRuntimeBase", 0) or 0),
        ),
        "runtimeTrainingBaseScoreSourceRows": training_runtime_source_rows,
        "outcomePolicyGradientTraining": True,
        "fullDirectPolicyTraining": False,
        "directPolicyRuntimeAuthority": False,
        "selectedActionImitation": False,
        "directPolicyTargetMode": TRAJECTORY_ADVANTAGE_RUNTIME_SIDECAR_TARGET_MODE,
        "fullLegalActionSetTraining": True,
        "ppoClipCoef": float(ppo_clip_coef),
        "fullLegalPolicyObjective": str(full_legal_policy_objective),
        "policyImprovementTemperature": float(policy_improvement_temperature),
        "baseCorrectPreserveWeight": float(base_correct_preserve_weight),
        "entropyCoef": float(entropy_coef),
        "valueLossWeight": float(value_loss_weight),
        "normalizeAdvantages": bool(normalize_advantages),
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "trainingLaunched": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_ygo_style_direct_policy_training(
    *,
    training_rows_path: str | Path | list[str | Path],
    out_dir: str | Path,
    candidate_model_id: str,
    training_row_file_weights: list[float] | None = None,
    base_model_path: str | Path | None = None,
    epochs: int = YGO_DEFAULT_UPDATE_EPOCHS,
    learning_rate: float = 0.001,
    hidden_dim: int = 64,
    batch_size: int = 256,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    shuffle_rows: bool = False,
    decision_training_weights: Mapping[str, float] | None = None,
    anchor_kl_weight: float = 0.0,
    anchor_kl_temperature: float = 1.0,
    anchor_kl_decision_weights: Mapping[str, float] | None = None,
    allow_selected_action_fallback: bool = False,
    target_contract: str = ACTION_VALUE_TARGET_CONTRACT,
    direct_policy_target_mode: str = DIRECT_POLICY_TARGET_MODE_PREFERRED_SLOT_CE,
    action_value_temperature: float = 0.25,
    device: str = "auto",
    allow_unsafe_full_direct_training: bool = False,
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
) -> dict[str, Any]:
    _reject_full_direct_training_unless_allowed(
        allow_unsafe_full_direct_training=allow_unsafe_full_direct_training
    )
    restart_safety_review = assert_restart_safety_clear(
        restart_safety_review_path,
        usage_label="direct policy training",
        allow_unreviewed_restart=bool(allow_unreviewed_restart),
    )
    training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
    row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
    rows = _load_weighted_training_rows(training_paths, row_file_weights)
    rows, action_value_semantic_refresh = _refresh_action_value_semantics_for_training(
        rows,
        source_label="direct_policy_training_load",
    )
    if str(direct_policy_target_mode) == DIRECT_POLICY_TARGET_MODE_ACTION_VALUE_DISTRIBUTION:
        candidate_rows = [
            row
            for row in rows
            if _ygo_legal_slots(row) and _ygo_row_has_action_value_distribution_target(row)
        ]
    else:
        candidate_rows = [
            row
            for row in rows
            if _ygo_direct_policy_target_slot(
                row,
                allow_selected_action_fallback=allow_selected_action_fallback,
            )
            is not None
            and _ygo_legal_slots(row)
        ]
    usable_rows, target_contract_report = _filter_rows_by_target_contract(
        candidate_rows,
        target_contract=target_contract,
        allow_selected_action_fallback=allow_selected_action_fallback,
    )
    if not usable_rows:
        _raise_no_usable_rows(
            mode="direct-policy",
            candidate_rows=len(candidate_rows),
            target_contract_report=target_contract_report,
        )
    play_card_target_semantics = assert_play_card_target_semantics_safe(usable_rows)
    target_action_semantics = assert_target_action_semantics_safe(usable_rows)

    effective_shuffle_rows = _effective_ygo_train_eval_shuffle(shuffle_rows)
    train_rows, eval_rows = _split_rows(
        usable_rows,
        eval_fraction=float(eval_fraction),
        shuffle=effective_shuffle_rows,
        seed=int(seed),
    )
    if not eval_rows:
        eval_rows = train_rows

    initial_scorer = _load_initial_scorer(base_model_path)
    normalized_decision_training_weights = _normalized_anchor_kl_decision_weights(decision_training_weights)
    bounded_anchor_kl_weight = max(0.0, float(anchor_kl_weight))
    bounded_anchor_kl_temperature = max(1.0e-6, float(anchor_kl_temperature))
    normalized_anchor_kl_decision_weights = _normalized_anchor_kl_decision_weights(anchor_kl_decision_weights)
    if bounded_anchor_kl_weight > 0.0 and initial_scorer is None:
        raise ValueError("direct policy anchor KL requires --base-model-path")
    candidate = train_ygo_style_direct_policy_scorer(
        train_rows,
        epochs=int(epochs),
        learning_rate=float(learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        seed=int(seed),
        initial_scorer=initial_scorer,
        decision_training_weights=normalized_decision_training_weights,
        anchor_kl_weight=bounded_anchor_kl_weight,
        anchor_kl_temperature=bounded_anchor_kl_temperature,
        anchor_kl_decision_weights=normalized_anchor_kl_decision_weights,
        allow_selected_action_fallback=bool(allow_selected_action_fallback),
        direct_policy_target_mode=str(direct_policy_target_mode),
        action_value_temperature=float(action_value_temperature),
        device=str(device),
    )
    candidate_eval = _direct_policy_eval(
        candidate,
        eval_rows,
        allow_selected_action_fallback=bool(allow_selected_action_fallback),
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_path = out_path / "self_improvement_pilot_listwise_scorer_model.json"
    report_path = out_path / "ygo_style_direct_policy_training_report.json"

    model_dict = candidate.to_dict()
    model_dict.update(
        {
            "modelId": str(candidate_model_id),
            "trainingMode": YGO_STYLE_DIRECT_POLICY_TRAINING_VERSION,
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "baseModelPath": str(base_model_path) if base_model_path is not None else None,
            "scratchTraining": initial_scorer is None,
            "scratchJustification": (
                "architecture changed from flat/object MLP to ygo-style card/action/global masked direct policy scorer"
                if initial_scorer is None
                else None
            ),
            "defaultRuntimeChanged": False,
            "activePolicyRequiredForGameplayClaim": True,
            "trainingRowFileWeights": list(row_file_weights),
            "directMaskedTop1Training": True,
            "decisionTrainingWeights": dict(normalized_decision_training_weights),
            "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
            "anchorKlWeight": float(bounded_anchor_kl_weight),
            "anchorKlTemperature": float(bounded_anchor_kl_temperature),
            "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
            "allowSelectedActionFallback": bool(allow_selected_action_fallback),
            "directPolicyTargetMode": str(candidate.directPolicyTargetMode),
            "actionValueTemperature": float(action_value_temperature),
            "targetContract": str(target_contract),
            "restartSafetyReview": restart_safety_review,
            "allowUnreviewedRestart": bool(allow_unreviewed_restart),
            "playCardTargetSemantics": play_card_target_semantics,
            "targetActionSemantics": target_action_semantics,
            "actionValueSemanticRefresh": action_value_semantic_refresh,
            "trainingObjective": _training_objective_for_contract(target_contract),
            "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        }
    )
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict[str, Any] = {
        "kind": YGO_STYLE_DIRECT_POLICY_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
        "trainingRowsSource": _training_rows_source_value(training_paths),
        "trainingRowFileWeights": list(row_file_weights),
        "trainingRowEffectiveWeightSum": _effective_training_weight_sum(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "trainingRowEffectiveWeightByDecision": _effective_training_weight_by_decision(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "candidateModelId": str(candidate_model_id),
        "candidateModelPath": str(model_path),
        "reportPath": str(report_path),
        "rowCount": len(rows),
        "usableDirectPolicyRows": len(usable_rows),
        "targetContract": str(target_contract),
        "targetContractReport": target_contract_report,
        "restartSafetyReview": restart_safety_review,
        "allowUnreviewedRestart": bool(allow_unreviewed_restart),
        "playCardTargetSemantics": play_card_target_semantics,
        "targetActionSemantics": target_action_semantics,
        "actionValueSemanticRefresh": action_value_semantic_refresh,
        "trainingObjective": _training_objective_for_contract(target_contract),
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "trainRows": len(train_rows),
        "evalRows": len(eval_rows),
        "epochs": int(epochs),
        "learningRate": float(learning_rate),
        "hiddenDim": int(candidate.hiddenDim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        **_shuffle_rows_report_fields(shuffle_rows),
        "featureFamily": YGO_STYLE_FEATURE_FAMILY,
        "objectCardFeaturesUsed": any(isinstance(row.get("cards_"), list) and row.get("cards_") for row in usable_rows),
        "sourceTargetCardRefsUsed": any(_row_has_source_or_target_ref(row) for row in usable_rows),
        "globalFeatureCount": len(candidate.globalFeatureNames),
        "actionFeatureCount": len(candidate.actionFeatureNames),
        "cardFeatureCount": len(candidate.cardFeatureNames),
        "inputDim": int(candidate.inputDim),
        "candidateDirectPolicyEval": candidate_eval,
        "scratchTraining": initial_scorer is None,
        "scratchJustification": (
            "architecture changed from flat/object MLP to ygo-style card/action/global masked direct policy scorer"
            if initial_scorer is None
            else None
        ),
        "directMaskedTop1Training": True,
        "decisionTrainingWeights": dict(normalized_decision_training_weights),
        "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
        "anchorKlWeight": float(bounded_anchor_kl_weight),
        "anchorKlTemperature": float(bounded_anchor_kl_temperature),
        "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
        "allowSelectedActionFallback": bool(allow_selected_action_fallback),
        "directPolicyTargetMode": str(candidate.directPolicyTargetMode),
        "actionValueTemperature": float(action_value_temperature),
        "trainingLaunched": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_ygo_style_outcome_policy_training(
    *,
    training_rows_path: str | Path | list[str | Path],
    out_dir: str | Path,
    candidate_model_id: str,
    training_row_file_weights: list[float] | None = None,
    base_model_path: str | Path | None = None,
    epochs: int = YGO_DEFAULT_UPDATE_EPOCHS,
    learning_rate: float = 0.001,
    hidden_dim: int = 64,
    batch_size: int = 256,
    eval_fraction: float = 0.2,
    seed: int = 2026061340,
    shuffle_rows: bool = False,
    decision_training_weights: Mapping[str, float] | None = None,
    anchor_kl_weight: float = 0.0,
    anchor_kl_temperature: float = 1.0,
    anchor_kl_decision_weights: Mapping[str, float] | None = None,
    entropy_coef: float = 0.01,
    value_loss_weight: float = 0.25,
    normalize_advantages: bool = False,
    device: str = "auto",
    allow_unsafe_full_direct_training: bool = False,
    restart_safety_review_path: str | Path | None = None,
    allow_unreviewed_restart: bool = False,
) -> dict[str, Any]:
    _reject_full_direct_training_unless_allowed(
        allow_unsafe_full_direct_training=allow_unsafe_full_direct_training
    )
    restart_safety_review = assert_restart_safety_clear(
        restart_safety_review_path,
        usage_label="outcome policy training",
        allow_unreviewed_restart=bool(allow_unreviewed_restart),
    )
    training_paths = [Path(path) for path in training_rows_path] if isinstance(training_rows_path, list) else [Path(training_rows_path)]
    row_file_weights = _normalized_row_file_weights(training_paths, training_row_file_weights)
    rows = _load_weighted_training_rows(training_paths, row_file_weights)
    rows, action_value_semantic_refresh = _refresh_action_value_semantics_for_training(
        rows,
        source_label="outcome_policy_training_load",
    )
    usable_rows = [
        row
        for row in rows
        if _ygo_trajectory_policy_label(row) is not None and _ygo_legal_slots(row)
    ]
    if not usable_rows:
        raise ValueError("ygo-style outcome policy training requires at least one usable trajectory row")
    play_card_target_semantics = assert_play_card_target_semantics_safe(usable_rows)
    target_action_semantics = assert_target_action_semantics_safe(usable_rows)

    effective_shuffle_rows = _effective_ygo_train_eval_shuffle(shuffle_rows)
    train_rows, eval_rows = _split_rows(
        usable_rows,
        eval_fraction=float(eval_fraction),
        shuffle=effective_shuffle_rows,
        seed=int(seed),
    )
    if not eval_rows:
        eval_rows = train_rows

    initial_scorer = _load_initial_scorer(base_model_path)
    normalized_decision_training_weights = _normalized_anchor_kl_decision_weights(decision_training_weights)
    bounded_anchor_kl_weight = max(0.0, float(anchor_kl_weight))
    bounded_anchor_kl_temperature = max(1.0e-6, float(anchor_kl_temperature))
    normalized_anchor_kl_decision_weights = _normalized_anchor_kl_decision_weights(anchor_kl_decision_weights)
    if bounded_anchor_kl_weight > 0.0 and initial_scorer is None:
        raise ValueError("outcome policy anchor KL requires --base-model-path")
    candidate = train_ygo_style_outcome_policy_scorer(
        train_rows,
        epochs=int(epochs),
        learning_rate=float(learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        seed=int(seed),
        initial_scorer=initial_scorer,
        decision_training_weights=normalized_decision_training_weights,
        anchor_kl_weight=bounded_anchor_kl_weight,
        anchor_kl_temperature=bounded_anchor_kl_temperature,
        anchor_kl_decision_weights=normalized_anchor_kl_decision_weights,
        entropy_coef=float(entropy_coef),
        value_loss_weight=float(value_loss_weight),
        normalize_advantages=bool(normalize_advantages),
        device=str(device),
    )
    candidate_eval = _outcome_policy_eval(candidate, eval_rows)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_path = out_path / "self_improvement_pilot_listwise_scorer_model.json"
    report_path = out_path / "ygo_style_outcome_policy_training_report.json"

    model_dict = candidate.to_dict()
    model_dict.update(
        {
            "modelId": str(candidate_model_id),
            "trainingMode": YGO_STYLE_OUTCOME_POLICY_TRAINING_VERSION,
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "baseModelPath": str(base_model_path) if base_model_path is not None else None,
            "scratchTraining": initial_scorer is None,
            "scratchJustification": (
                "architecture changed from offline pair labels to ygo-style trajectory outcome policy/value update"
                if initial_scorer is None
                else None
            ),
            "defaultRuntimeChanged": False,
            "activePolicyRequiredForGameplayClaim": True,
            "trainingRowFileWeights": list(row_file_weights),
            "trainingObjective": "trajectory_outcome_policy_gradient",
            "restartSafetyReview": restart_safety_review,
            "allowUnreviewedRestart": bool(allow_unreviewed_restart),
            "playCardTargetSemantics": play_card_target_semantics,
            "targetActionSemantics": target_action_semantics,
            "actionValueSemanticRefresh": action_value_semantic_refresh,
            "outcomePolicyGradientTraining": True,
            "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
            "anchorKlWeight": float(bounded_anchor_kl_weight),
            "anchorKlTemperature": float(bounded_anchor_kl_temperature),
            "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
            "decisionTrainingWeights": dict(normalized_decision_training_weights),
            "entropyCoef": float(entropy_coef),
            "valueLossWeight": float(value_loss_weight),
            "normalizeAdvantages": bool(normalize_advantages),
            "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        }
    )
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    report: dict[str, Any] = {
        "kind": YGO_STYLE_OUTCOME_POLICY_TRAINING_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trainingRowsPath": str(training_paths[0]) if len(training_paths) == 1 else [str(path) for path in training_paths],
        "trainingRowsSource": _training_rows_source_value(training_paths),
        "trainingRowFileWeights": list(row_file_weights),
        "trainingRowEffectiveWeightSum": _effective_training_weight_sum(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "trainingRowEffectiveWeightByDecision": _effective_training_weight_by_decision(
            usable_rows,
            decision_training_weights=normalized_decision_training_weights,
        ),
        "baseModelPath": str(base_model_path) if base_model_path is not None else None,
        "candidateModelId": str(candidate_model_id),
        "candidateModelPath": str(model_path),
        "reportPath": str(report_path),
        "rowCount": len(rows),
        "usableOutcomePolicyRows": len(usable_rows),
        "trainingObjective": "trajectory_outcome_policy_gradient",
        "restartSafetyReview": restart_safety_review,
        "allowUnreviewedRestart": bool(allow_unreviewed_restart),
        "playCardTargetSemantics": play_card_target_semantics,
        "targetActionSemantics": target_action_semantics,
        "actionValueSemanticRefresh": action_value_semantic_refresh,
        "trainRows": len(train_rows),
        "evalRows": len(eval_rows),
        "epochs": int(epochs),
        "learningRate": float(learning_rate),
        "hiddenDim": int(candidate.hiddenDim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        **_shuffle_rows_report_fields(shuffle_rows),
        "featureFamily": YGO_STYLE_FEATURE_FAMILY,
        "objectCardFeaturesUsed": any(isinstance(row.get("cards_"), list) and row.get("cards_") for row in usable_rows),
        "sourceTargetCardRefsUsed": any(_row_has_source_or_target_ref(row) for row in usable_rows),
        "globalFeatureCount": len(candidate.globalFeatureNames),
        "actionFeatureCount": len(candidate.actionFeatureNames),
        "cardFeatureCount": len(candidate.cardFeatureNames),
        "inputDim": int(candidate.inputDim),
        "candidateOutcomePolicyEval": candidate_eval,
        "scratchTraining": initial_scorer is None,
        "scratchJustification": (
            "architecture changed from offline pair labels to ygo-style trajectory outcome policy/value update"
            if initial_scorer is None
            else None
        ),
        "policyAnchorKlTraining": bool(bounded_anchor_kl_weight > 0.0),
        "anchorKlWeight": float(bounded_anchor_kl_weight),
        "anchorKlTemperature": float(bounded_anchor_kl_temperature),
        "anchorKlDecisionWeights": dict(normalized_anchor_kl_decision_weights),
        "decisionTrainingWeights": dict(normalized_decision_training_weights),
        "entropyCoef": float(entropy_coef),
        "valueLossWeight": float(value_loss_weight),
        "normalizeAdvantages": bool(normalize_advantages),
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "trainingLaunched": True,
        "promotionApproved": False,
        "protectedDefaultsChanged": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _pairwise_eval(model: Any, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    _reset_recurrent_state_if_available(model)
    scores_by_row = model.score_rows_batched(list(rows))
    total = 0
    correct = 0
    margin_sum = 0.0
    by_decision: dict[str, dict[str, int]] = {}
    for row, scores in zip(rows, scores_by_row, strict=False):
        preference = _ygo_pairwise_preference(row)
        if preference is None:
            continue
        preferred, rejected, _value_gap = preference
        if preferred >= len(scores) or rejected >= len(scores):
            continue
        preferred_score = scores[preferred]
        rejected_score = scores[rejected]
        if preferred_score is None or rejected_score is None:
            continue
        total += 1
        if float(preferred_score) > float(rejected_score):
            correct += 1
        margin_sum += float(preferred_score) - float(rejected_score)
        decision = str(row.get("decisionKind") or "unknown")
        bucket = by_decision.setdefault(decision, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if float(preferred_score) > float(rejected_score):
            bucket["correct"] += 1
    return {
        "total": total,
        "correct": correct,
        "accuracy": float(correct / total) if total else 0.0,
        "meanMargin": float(margin_sum / total) if total else 0.0,
        "byDecisionKind": {
            decision: {
                "total": values["total"],
                "correct": values["correct"],
                "accuracy": float(values["correct"] / values["total"]) if values["total"] else 0.0,
            }
            for decision, values in sorted(by_decision.items())
        },
    }


def _reset_recurrent_state_if_available(model: Any) -> None:
    reset = getattr(model, "reset_recurrent_state", None)
    if callable(reset):
        reset()


def _direct_policy_eval(
    model: Any,
    rows: list[Mapping[str, Any]],
    *,
    allow_selected_action_fallback: bool = False,
) -> dict[str, Any]:
    _reset_recurrent_state_if_available(model)
    scores_by_row = model.score_rows_batched(list(rows))
    total = 0
    correct = 0
    by_decision: dict[str, dict[str, int]] = {}
    for row, scores in zip(rows, scores_by_row, strict=False):
        target = _ygo_direct_policy_target_slot(
            row,
            allow_selected_action_fallback=allow_selected_action_fallback,
        )
        legal_slots = [
            slot
            for slot, score in enumerate(scores)
            if score is not None and slot in set(_ygo_legal_slots(row))
        ]
        if target is None or target not in legal_slots:
            continue
        selected = runtime_top_slot(scores, legal_slots)
        if selected is None:
            continue
        total += 1
        if selected == target:
            correct += 1
        decision = str(row.get("decisionKind") or "unknown")
        bucket = by_decision.setdefault(decision, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if selected == target:
            bucket["correct"] += 1
    known_slot_eval = _direct_policy_known_action_value_eval(model, rows)
    return {
        "total": total,
        "correct": correct,
        "top1Accuracy": float(correct / total) if total else 0.0,
        "knownSlotTotal": known_slot_eval["total"],
        "knownSlotCorrect": known_slot_eval["correct"],
        "knownSlotTop1Accuracy": known_slot_eval["top1Accuracy"],
        "knownSlotByDecisionKind": known_slot_eval["byDecisionKind"],
        "byDecisionKind": {
            decision: {
                "total": values["total"],
                "correct": values["correct"],
                "top1Accuracy": float(values["correct"] / values["total"]) if values["total"] else 0.0,
            }
            for decision, values in sorted(by_decision.items())
        },
    }


def _outcome_policy_eval(model: Any, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    _reset_recurrent_state_if_available(model)
    scores_by_row = model.score_rows_batched(list(rows))
    return _outcome_policy_eval_from_scores(rows, scores_by_row)


def _reused_current_policy_diagnostic_report(report: Mapping[str, Any], *, reused_from: str) -> dict[str, Any]:
    out = dict(report)
    out["reusedFrom"] = str(reused_from)
    out["reuseReason"] = "recurrent_eval_only_post_training_diagnostics"
    return out


def _skipped_current_policy_diagnostic_report(*, kind: str) -> dict[str, Any]:
    return {
        "kind": str(kind),
        "skipped": True,
        "skipReason": "post_training_diagnostics_disabled",
        "total": 0,
        "directionAccuracy": None,
    }


def _outcome_policy_eval_from_scores(
    rows: list[Mapping[str, Any]],
    scores_by_row: list[list[float | None]],
) -> dict[str, Any]:
    total = 0
    direction_correct = 0
    positive_rows = 0
    negative_rows = 0
    no_choice_rows_skipped = 0
    by_decision: dict[str, dict[str, int]] = {}
    for row, scores in zip(rows, scores_by_row, strict=False):
        label = _ygo_trajectory_policy_label(row)
        if label is None:
            continue
        selected_slot, _return_value, advantage = label
        legal_slots = [
            slot
            for slot, score in enumerate(scores)
            if score is not None and slot in set(_ygo_legal_slots(row))
        ]
        if len(legal_slots) <= 1:
            no_choice_rows_skipped += 1
            continue
        if selected_slot not in legal_slots:
            continue
        top_slot = max(legal_slots, key=lambda slot: float(scores[slot]))
        selected_is_top = top_slot == selected_slot
        if advantage > 0.0:
            positive_rows += 1
            correct = selected_is_top
        elif advantage < 0.0:
            negative_rows += 1
            correct = not selected_is_top if len(legal_slots) > 1 else True
        else:
            continue
        total += 1
        if correct:
            direction_correct += 1
        decision = str(row.get("decisionKind") or "unknown")
        bucket = by_decision.setdefault(decision, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if correct:
            bucket["correct"] += 1
    return {
        "total": int(total),
        "directionCorrect": int(direction_correct),
        "directionAccuracy": float(direction_correct / total) if total else 0.0,
        "positiveAdvantageRows": int(positive_rows),
        "negativeAdvantageRows": int(negative_rows),
        "noChoiceRowsSkipped": int(no_choice_rows_skipped),
        "byDecisionKind": {
            decision: {
                "total": values["total"],
                "correct": values["correct"],
                "directionAccuracy": float(values["correct"] / values["total"]) if values["total"] else 0.0,
            }
            for decision, values in sorted(by_decision.items())
        },
    }


def _outcome_policy_movement_eval(
    base_model: Any,
    candidate_model: Any,
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    _reset_recurrent_state_if_available(base_model)
    base_scores_by_row = base_model.score_rows_batched(list(rows))
    _reset_recurrent_state_if_available(candidate_model)
    candidate_scores_by_row = candidate_model.score_rows_batched(list(rows))
    return _outcome_policy_movement_eval_from_scores(rows, base_scores_by_row, candidate_scores_by_row)


def _outcome_policy_movement_eval_from_scores(
    rows: list[Mapping[str, Any]],
    base_scores_by_row: list[list[float | None]],
    candidate_scores_by_row: list[list[float | None]],
) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    sums: Counter[str] = Counter()
    by_decision: dict[str, Counter[str]] = {}
    tiny_delta_thresholds: tuple[tuple[str, float], ...] = (
        ("1e-06", 1.0e-6),
        ("1e-05", 1.0e-5),
        ("1e-04", 1.0e-4),
        ("1e-03", 1.0e-3),
    )
    threshold_totals: dict[str, Counter[str]] = {
        label: Counter() for label, _threshold in tiny_delta_thresholds
    }
    threshold_by_decision: dict[str, dict[str, Counter[str]]] = {}
    no_choice_rows_skipped = 0
    for row, base_scores, candidate_scores in zip(rows, base_scores_by_row, candidate_scores_by_row, strict=False):
        label = _ygo_trajectory_policy_label(row)
        if label is None:
            continue
        selected_slot, _return_value, advantage = label
        if advantage == 0.0:
            continue
        base_log_probs = _masked_log_probs_for_scores(base_scores, row)
        candidate_log_probs = _masked_log_probs_for_scores(candidate_scores, row)
        shared_legal_slots = [
            slot for slot in base_log_probs.keys() if slot in candidate_log_probs
        ]
        if len(shared_legal_slots) <= 1:
            no_choice_rows_skipped += 1
            continue
        if selected_slot not in base_log_probs or selected_slot not in candidate_log_probs:
            continue
        decision = str(row.get("decisionKind") or "unknown")
        bucket = by_decision.setdefault(decision, Counter())
        key = "positive" if advantage > 0.0 else "negative"
        delta = float(candidate_log_probs[selected_slot]) - float(base_log_probs[selected_slot])
        totals["total"] += 1
        totals[f"{key}Rows"] += 1
        sums[f"{key}SelectedLogProbDelta"] += delta
        bucket["total"] += 1
        bucket[f"{key}Rows"] += 1
        bucket[f"{key}SelectedLogProbDelta"] += delta
        direction_correct = (advantage > 0.0 and delta > 0.0) or (advantage < 0.0 and delta < 0.0)
        if direction_correct:
            totals[f"{key}CorrectDirection"] += 1
            bucket[f"{key}CorrectDirection"] += 1
        elif delta != 0.0:
            totals[f"{key}WrongDirection"] += 1
            bucket[f"{key}WrongDirection"] += 1
        if delta != 0.0:
            for threshold_label, threshold in tiny_delta_thresholds:
                if abs(delta) < threshold:
                    continue
                for threshold_bucket in (
                    threshold_totals[threshold_label],
                    threshold_by_decision.setdefault(decision, {}).setdefault(
                        threshold_label,
                        Counter(),
                    ),
                ):
                    threshold_bucket["changedRows"] += 1
                    threshold_bucket[f"{key}Rows"] += 1
                    threshold_bucket[f"{key}SelectedLogProbDelta"] += delta
                    if direction_correct:
                        threshold_bucket["correctDirection"] += 1
                        threshold_bucket[f"{key}CorrectDirection"] += 1
                    else:
                        threshold_bucket["wrongDirection"] += 1
                        threshold_bucket[f"{key}WrongDirection"] += 1
    positive_rows = int(totals.get("positiveRows", 0))
    negative_rows = int(totals.get("negativeRows", 0))
    correct_direction = int(totals.get("positiveCorrectDirection", 0) + totals.get("negativeCorrectDirection", 0))
    wrong_direction = int(totals.get("positiveWrongDirection", 0) + totals.get("negativeWrongDirection", 0))
    changed_direction = correct_direction + wrong_direction
    return {
        "kind": "sampled_advantage_probability_movement_v1",
        "total": int(totals.get("total", 0)),
        "positiveAdvantageRows": positive_rows,
        "negativeAdvantageRows": negative_rows,
        "noChoiceRowsSkipped": int(no_choice_rows_skipped),
        "changedDirectionRows": int(changed_direction),
        "changedDirectionRate": float(changed_direction / totals["total"]) if totals.get("total") else 0.0,
        "correctDirectionRows": correct_direction,
        "wrongDirectionRows": int(wrong_direction),
        "correctDirectionRate": float(correct_direction / totals["total"]) if totals.get("total") else 0.0,
        "positiveCorrectDirectionRate": (
            float(totals.get("positiveCorrectDirection", 0) / positive_rows) if positive_rows else 0.0
        ),
        "negativeCorrectDirectionRate": (
            float(totals.get("negativeCorrectDirection", 0) / negative_rows) if negative_rows else 0.0
        ),
        "avgPositiveSelectedLogProbDelta": (
            float(sums.get("positiveSelectedLogProbDelta", 0.0) / positive_rows) if positive_rows else 0.0
        ),
        "avgNegativeSelectedLogProbDelta": (
            float(sums.get("negativeSelectedLogProbDelta", 0.0) / negative_rows) if negative_rows else 0.0
        ),
        "tinyDeltaExclusion": _outcome_policy_movement_threshold_report(
            threshold_totals,
            tiny_delta_thresholds=tiny_delta_thresholds,
        ),
        "byDecisionKind": {
            decision: {
                **_outcome_policy_movement_bucket(values),
                "tinyDeltaExclusion": _outcome_policy_movement_threshold_report(
                    threshold_by_decision.get(decision, {}),
                    tiny_delta_thresholds=tiny_delta_thresholds,
                ),
            }
            for decision, values in sorted(by_decision.items())
        },
        "mainActionSignatureMovement": _outcome_policy_action_signature_movement_eval_from_scores(
            rows,
            base_scores_by_row,
            candidate_scores_by_row,
            decision_kind="main",
        ),
    }


def _selected_action_signature(row: Mapping[str, Any], selected_slot: int) -> str:
    identities = row.get("actionIdentities")
    if isinstance(identities, list | tuple) and 0 <= selected_slot < len(identities):
        identity = str(identities[selected_slot] or "").strip()
        if identity:
            return f"identity:{identity[:160]}"
    actions = row.get("actions")
    if isinstance(actions, list | tuple) and 0 <= selected_slot < len(actions):
        action = actions[selected_slot]
        if isinstance(action, Mapping):
            identity = str(action.get("actionIdentity") or "").strip()
            if identity:
                return f"identity:{identity[:160]}"
            kind = str(action.get("kind") or "").strip()
            if kind:
                return f"kind:{kind[:160]}"
    names = list(row.get("actionFeatureNames") or [])
    actions_ = row.get("actions_")
    values: Any = None
    if isinstance(actions_, list | tuple) and 0 <= selected_slot < len(actions_):
        values = actions_[selected_slot]
    if isinstance(values, list | tuple):
        prefixes = (
            "action_kind:",
            "resource_action:",
            "board_action:",
            "spell_action:",
            "combat_action:",
            "target_action:",
            "terminal_action:",
            "action:",
            "card_profile_identity:",
            "card_profile_role:",
        )
        parts: list[str] = []
        for name, value in zip(names, values, strict=False):
            try:
                active = abs(float(value)) > 0.5
            except (TypeError, ValueError):
                active = False
            text = str(name)
            if active and any(text.startswith(prefix) for prefix in prefixes):
                parts.append(text[:96])
            if len(parts) >= 8:
                break
        if parts:
            return "|".join(parts)
    decision = str(row.get("decisionKind") or "unknown")
    return f"decision:{decision}|slot:{int(selected_slot)}"


def _outcome_policy_action_signature_movement_eval_from_scores(
    rows: list[Mapping[str, Any]],
    base_scores_by_row: list[list[float | None]],
    candidate_scores_by_row: list[list[float | None]],
    *,
    decision_kind: str,
    max_groups: int = 40,
) -> dict[str, Any]:
    target_decision = str(decision_kind or "").strip()
    totals: Counter[str] = Counter()
    by_signature: dict[str, Counter[str]] = {}
    no_choice_rows_skipped = 0
    for row, base_scores, candidate_scores in zip(rows, base_scores_by_row, candidate_scores_by_row, strict=False):
        decision = str(row.get("decisionKind") or "unknown")
        if target_decision and decision != target_decision:
            continue
        label = _ygo_trajectory_policy_label(row)
        if label is None:
            continue
        selected_slot, _return_value, advantage = label
        if advantage == 0.0:
            continue
        base_log_probs = _masked_log_probs_for_scores(base_scores, row)
        candidate_log_probs = _masked_log_probs_for_scores(candidate_scores, row)
        shared_legal_slots = [slot for slot in base_log_probs.keys() if slot in candidate_log_probs]
        if len(shared_legal_slots) <= 1:
            no_choice_rows_skipped += 1
            continue
        if selected_slot not in base_log_probs or selected_slot not in candidate_log_probs:
            continue
        signature = _selected_action_signature(row, int(selected_slot))
        bucket = by_signature.setdefault(signature, Counter())
        key = "positive" if advantage > 0.0 else "negative"
        delta = float(candidate_log_probs[selected_slot]) - float(base_log_probs[selected_slot])
        for counter in (totals, bucket):
            counter["total"] += 1
            counter[f"{key}Rows"] += 1
            counter[f"{key}SelectedLogProbDelta"] += delta
        direction_correct = (advantage > 0.0 and delta > 0.0) or (advantage < 0.0 and delta < 0.0)
        if direction_correct:
            totals[f"{key}CorrectDirection"] += 1
            bucket[f"{key}CorrectDirection"] += 1
        elif delta != 0.0:
            totals[f"{key}WrongDirection"] += 1
            bucket[f"{key}WrongDirection"] += 1
    groups: list[dict[str, Any]] = []
    for signature, values in by_signature.items():
        positive_rows = int(values.get("positiveRows", 0))
        negative_rows = int(values.get("negativeRows", 0))
        total = int(values.get("total", 0))
        minority_rows = min(positive_rows, negative_rows)
        groups.append(
            {
                "signature": signature,
                **_outcome_policy_movement_bucket(values),
                "signConflictRows": int(minority_rows),
                "signConflictRate": float(minority_rows / total) if total else 0.0,
            }
        )
    groups.sort(
        key=lambda item: (
            int(item.get("wrongDirectionRows", 0)),
            int(item.get("signConflictRows", 0)),
            int(item.get("total", 0)),
        ),
        reverse=True,
    )
    positive_rows = int(totals.get("positiveRows", 0))
    negative_rows = int(totals.get("negativeRows", 0))
    correct_direction = int(totals.get("positiveCorrectDirection", 0) + totals.get("negativeCorrectDirection", 0))
    wrong_direction = int(totals.get("positiveWrongDirection", 0) + totals.get("negativeWrongDirection", 0))
    return {
        "kind": "sampled_advantage_selected_action_signature_movement_v1",
        "decisionKind": target_decision or "all",
        "total": int(totals.get("total", 0)),
        "positiveAdvantageRows": positive_rows,
        "negativeAdvantageRows": negative_rows,
        "noChoiceRowsSkipped": int(no_choice_rows_skipped),
        "correctDirectionRows": correct_direction,
        "wrongDirectionRows": wrong_direction,
        "correctDirectionRate": float(correct_direction / totals["total"]) if totals.get("total") else 0.0,
        "positiveCorrectDirectionRate": (
            float(totals.get("positiveCorrectDirection", 0) / positive_rows) if positive_rows else 0.0
        ),
        "negativeCorrectDirectionRate": (
            float(totals.get("negativeCorrectDirection", 0) / negative_rows) if negative_rows else 0.0
        ),
        "groupsReturned": int(min(max_groups, len(groups))),
        "groupsTotal": int(len(groups)),
        "groups": groups[: max(0, int(max_groups))],
    }


def _current_policy_group_movement_key(row: Mapping[str, Any], row_index: int, *, window_size: int = 3) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    label = row.get("trajectoryPolicyLabel") if isinstance(row.get("trajectoryPolicyLabel"), Mapping) else {}
    sequence = str(
        row.get("sequenceId")
        or metadata.get("sequenceId")
        or label.get("sequenceId")
        or row.get("episodeId")
        or metadata.get("episodeId")
        or row.get("taskId")
        or metadata.get("taskId")
        or f"row-{row_index}"
    )
    side = str(
        metadata.get("runtimeActorSide")
        or metadata.get("trajectoryActorSide")
        or row.get("modelSide")
        or "unknown"
    )
    explicit_window = str(row.get("turnPhaseWindow") or metadata.get("turnPhaseWindow") or "").strip()
    if explicit_window:
        return f"{sequence}|{side}|turnPhase:{explicit_window}"
    turn_value = row.get("turnIndex", row.get("gameTurn", metadata.get("turnIndex", metadata.get("gameTurn"))))
    phase_value = row.get("gamePhase", metadata.get("gamePhase", row.get("phase", metadata.get("phase"))))
    active_side = row.get("activeSide", metadata.get("activeSide", metadata.get("runtimeActiveSide")))
    if turn_value is not None or phase_value is not None:
        return (
            f"{sequence}|{side}|turn:{turn_value if turn_value is not None else 'unknown'}"
            f"|phase:{phase_value if phase_value is not None else 'unknown'}"
            f"|active:{active_side if active_side is not None else 'unknown'}"
        )
    step_value = (
        row.get("episodeStepIndex")
        or metadata.get("episodeStepIndex")
        or row.get("actionSetDecisionIndex")
        or metadata.get("actionSetDecisionIndex")
        or row_index
    )
    try:
        step = int(step_value)
    except (TypeError, ValueError):
        step = int(row_index)
    bounded_window = max(1, int(window_size))
    return f"{sequence}|{side}|window:{step // bounded_window}"


def _current_policy_group_sequence_side_key(row: Mapping[str, Any], row_index: int) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    label = row.get("trajectoryPolicyLabel") if isinstance(row.get("trajectoryPolicyLabel"), Mapping) else {}
    sequence = str(
        row.get("sequenceId")
        or metadata.get("sequenceId")
        or label.get("sequenceId")
        or row.get("episodeId")
        or metadata.get("episodeId")
        or row.get("taskId")
        or metadata.get("taskId")
        or f"row-{row_index}"
    )
    side = str(
        metadata.get("runtimeActorSide")
        or metadata.get("trajectoryActorSide")
        or row.get("modelSide")
        or "unknown"
    )
    return f"{sequence}|{side}"


def _current_policy_group_order_index(row: Mapping[str, Any], row_index: int) -> int:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    value = (
        row.get("episodeStepIndex")
        or metadata.get("episodeStepIndex")
        or row.get("actionSetDecisionIndex")
        or metadata.get("actionSetDecisionIndex")
        or row_index
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(row_index)


def _current_policy_row_mc_return(row: Mapping[str, Any]) -> float | None:
    label = row.get("trajectoryPolicyLabel") if isinstance(row.get("trajectoryPolicyLabel"), Mapping) else {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    for source in (label, row, metadata):
        for key in (
            "mcReturnValue",
            "terminalMcReturnValue",
            "rawEpisodeReturnValue",
            "terminalReturnValue",
            "monteCarloReturnValue",
        ):
            value = _float_or_none(source.get(key))
            if value is not None and math.isfinite(float(value)):
                return float(value)
    return None


def _outcome_policy_group_movement_eval_from_scores(
    rows: list[Mapping[str, Any]],
    base_scores_by_row: list[list[float | None]],
    candidate_scores_by_row: list[list[float | None]],
    *,
    window_size: int = 3,
) -> dict[str, Any]:
    groups: dict[str, Counter[str]] = {}
    group_meta: dict[str, dict[str, Any]] = {}
    no_choice_rows_skipped = 0
    for row_index, (row, base_scores, candidate_scores) in enumerate(
        zip(rows, base_scores_by_row, candidate_scores_by_row, strict=False)
    ):
        label = _ygo_trajectory_policy_label(row)
        if label is None:
            continue
        selected_slot, _return_value, advantage = label
        if advantage == 0.0:
            continue
        base_log_probs = _masked_log_probs_for_scores(base_scores, row)
        candidate_log_probs = _masked_log_probs_for_scores(candidate_scores, row)
        shared_legal_slots = [slot for slot in base_log_probs.keys() if slot in candidate_log_probs]
        if len(shared_legal_slots) <= 1:
            no_choice_rows_skipped += 1
            continue
        if selected_slot not in base_log_probs or selected_slot not in candidate_log_probs:
            continue
        delta = float(candidate_log_probs[selected_slot]) - float(base_log_probs[selected_slot])
        group_key = _current_policy_group_movement_key(row, row_index, window_size=window_size)
        group = groups.setdefault(group_key, Counter())
        step_index = _current_policy_group_order_index(row, row_index)
        meta = group_meta.setdefault(
            group_key,
            {
                "episode": _current_policy_group_sequence_side_key(row, row_index),
                "step": int(step_index),
                "oldValue": _current_policy_old_state_value(row),
            },
        )
        if int(step_index) < int(meta.get("step", step_index)):
            meta["step"] = int(step_index)
            meta["oldValue"] = _current_policy_old_state_value(row)
        group["rows"] += 1
        group["advantageSum"] += float(advantage)
        group["selectedLogProbDeltaSum"] += float(delta)
        mc_return = _current_policy_row_mc_return(row)
        if mc_return is not None:
            group["mcReturnSum"] += float(mc_return)
            group["mcReturnRows"] += 1
        if advantage > 0.0:
            group["positiveActionRows"] += 1
        elif advantage < 0.0:
            group["negativeActionRows"] += 1
        group[str(row.get("decisionKind") or "unknown")] += 1

    totals: Counter[str] = Counter()
    mc_totals: Counter[str] = Counter()
    group_records: list[dict[str, Any]] = []
    for group_key, values in sorted(groups.items()):
        advantage_sum = float(values.get("advantageSum", 0.0))
        delta_sum = float(values.get("selectedLogProbDeltaSum", 0.0))
        mc_rows = int(values.get("mcReturnRows", 0))
        mc_mean = float(values.get("mcReturnSum", 0.0)) / float(mc_rows) if mc_rows else None
        if advantage_sum == 0.0:
            totals["zeroAdvantageGroupsSkipped"] += 1
            direction_correct = False
        else:
            key = "positive" if advantage_sum > 0.0 else "negative"
            totals["total"] += 1
            totals[f"{key}Rows"] += 1
            totals[f"{key}SelectedLogProbDelta"] += delta_sum
            direction_correct = (advantage_sum > 0.0 and delta_sum > 0.0) or (
                advantage_sum < 0.0 and delta_sum < 0.0
            )
            if direction_correct:
                totals[f"{key}CorrectDirection"] += 1
            elif delta_sum != 0.0:
                totals[f"{key}WrongDirection"] += 1
        if mc_mean is None or mc_mean == 0.0:
            mc_totals["zeroAdvantageGroupsSkipped"] += 1
        else:
            mc_key = "positive" if mc_mean > 0.0 else "negative"
            mc_totals["total"] += 1
            mc_totals[f"{mc_key}Rows"] += 1
            mc_totals[f"{mc_key}SelectedLogProbDelta"] += delta_sum
            mc_correct = (mc_mean > 0.0 and delta_sum > 0.0) or (mc_mean < 0.0 and delta_sum < 0.0)
            if mc_correct:
                mc_totals[f"{mc_key}CorrectDirection"] += 1
            elif delta_sum != 0.0:
                mc_totals[f"{mc_key}WrongDirection"] += 1
        group_records.append(
            {
                "group": group_key,
                "rows": int(values.get("rows", 0)),
                "advantageSum": float(advantage_sum),
                "mcReturnMean": mc_mean,
                "selectedLogProbDeltaSum": float(delta_sum),
                "correctDirection": bool(direction_correct),
                "positiveActionRows": int(values.get("positiveActionRows", 0)),
                "negativeActionRows": int(values.get("negativeActionRows", 0)),
                "episode": str(group_meta.get(group_key, {}).get("episode", "")),
                "step": int(group_meta.get(group_key, {}).get("step", 0)),
                "oldPolicyStateValue": group_meta.get(group_key, {}).get("oldValue"),
            }
        )

    local_value_report = _current_policy_local_value_delta_group_movement_report(group_records)
    result = _outcome_policy_movement_bucket(totals)
    result.update(
        {
            "kind": "sampled_advantage_group_probability_movement_v1",
            "groupKey": [
                "sequenceId",
                "runtimeActorSide",
                "turnPhaseWindow_or_turn_phase_step_active",
                f"fallback_episodeStepIndex//{max(1, int(window_size))}",
            ],
            "advantageAggregation": "sum_row_advantage",
            "logProbAggregation": "sum_selected_action_logprob_delta",
            "windowSize": int(max(1, int(window_size))),
            "groups": int(len(group_records)),
            "noChoiceRowsSkipped": int(no_choice_rows_skipped),
            "zeroAdvantageGroupsSkipped": int(totals.get("zeroAdvantageGroupsSkipped", 0)),
            "terminalReturnMovement": {
                **_outcome_policy_movement_bucket(mc_totals),
                "kind": "sampled_terminal_return_group_probability_movement_v1",
                "advantageAggregation": "mean_mc_return",
                "zeroAdvantageGroupsSkipped": int(mc_totals.get("zeroAdvantageGroupsSkipped", 0)),
            },
            "localValueDeltaMovement": local_value_report,
            "worstGroups": sorted(
                group_records,
                key=lambda item: (bool(item.get("correctDirection")), -abs(float(item.get("advantageSum", 0.0)))),
            )[:10],
        }
    )
    return result


def _current_policy_local_value_delta_group_movement_report(group_records: list[dict[str, Any]]) -> dict[str, Any]:
    by_episode: dict[str, list[dict[str, Any]]] = {}
    for record in group_records:
        old_value = _float_or_none(record.get("oldPolicyStateValue"))
        if old_value is None:
            continue
        by_episode.setdefault(str(record.get("episode") or "unknown"), []).append(record)
    totals: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for episode, episode_records in sorted(by_episode.items()):
        ordered = sorted(episode_records, key=lambda item: int(item.get("step", 0)))
        for current, nxt in zip(ordered, ordered[1:], strict=False):
            current_value = _float_or_none(current.get("oldPolicyStateValue"))
            next_value = _float_or_none(nxt.get("oldPolicyStateValue"))
            if current_value is None or next_value is None:
                continue
            local_delta = float(next_value) - float(current_value)
            logprob_delta = float(current.get("selectedLogProbDeltaSum", 0.0))
            if local_delta == 0.0:
                totals["zeroAdvantageGroupsSkipped"] += 1
                continue
            key = "positive" if local_delta > 0.0 else "negative"
            totals["total"] += 1
            totals[f"{key}Rows"] += 1
            totals[f"{key}SelectedLogProbDelta"] += logprob_delta
            correct = (local_delta > 0.0 and logprob_delta > 0.0) or (
                local_delta < 0.0 and logprob_delta < 0.0
            )
            if correct:
                totals[f"{key}CorrectDirection"] += 1
            elif logprob_delta != 0.0:
                totals[f"{key}WrongDirection"] += 1
            records.append(
                {
                    "episode": episode,
                    "group": current.get("group"),
                    "step": int(current.get("step", 0)),
                    "rows": int(current.get("rows", 0)),
                    "oldPolicyStateValue": float(current_value),
                    "nextOldPolicyStateValue": float(next_value),
                    "localValueDelta": float(local_delta),
                    "selectedLogProbDeltaSum": float(logprob_delta),
                    "correctDirection": bool(correct),
                }
            )
    return {
        **_outcome_policy_movement_bucket(totals),
        "kind": "sampled_local_value_delta_group_probability_movement_v1",
        "advantageAggregation": "next_window_old_policy_value_delta",
        "episodes": int(len(by_episode)),
        "groupsWithOldValue": int(sum(len(values) for values in by_episode.values())),
        "zeroAdvantageGroupsSkipped": int(totals.get("zeroAdvantageGroupsSkipped", 0)),
        "worstGroups": sorted(
            records,
            key=lambda item: (bool(item.get("correctDirection")), -abs(float(item.get("localValueDelta", 0.0)))),
        )[:10],
    }


def _outcome_policy_domain_movement_eval(
    base_model: Any,
    candidate_model: Any,
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    _reset_recurrent_state_if_available(base_model)
    base_scores_by_row = base_model.score_rows_batched(list(rows))
    _reset_recurrent_state_if_available(candidate_model)
    candidate_scores_by_row = candidate_model.score_rows_batched(list(rows))
    return _outcome_policy_domain_movement_eval_from_scores(rows, base_scores_by_row, candidate_scores_by_row)


def _outcome_policy_domain_movement_eval_from_scores(
    rows: list[Mapping[str, Any]],
    base_scores_by_row: list[list[float | None]],
    candidate_scores_by_row: list[list[float | None]],
) -> dict[str, Any]:
    by_domain: dict[str, list[Mapping[str, Any]]] = {}
    indices_by_domain: dict[str, list[int]] = {}
    domain_parts: dict[str, tuple[str, str, str, str, str, str]] = {}
    for index, row in enumerate(rows):
        key = _current_policy_domain_key(row)
        label = "|".join(key)
        by_domain.setdefault(label, []).append(row)
        indices_by_domain.setdefault(label, []).append(index)
        domain_parts[label] = key
    domains: list[dict[str, Any]] = []
    for label in sorted(by_domain):
        pool, suite, opponent, side, player_deck, opponent_deck = domain_parts[label]
        indices = indices_by_domain[label]
        movement = _outcome_policy_movement_eval_from_scores(
            list(by_domain[label]),
            [base_scores_by_row[index] for index in indices],
            [candidate_scores_by_row[index] for index in indices],
        )
        movement.update(
            {
                "domain": label,
                "rolloutPoolKind": pool,
                "suiteKind": suite,
                "runtimeOpponentPolicyId": opponent,
                "runtimeActorSide": side,
                "playerDeckId": player_deck,
                "opponentDeckId": opponent_deck,
            }
        )
        domains.append(movement)
    worst = sorted(
        domains,
        key=lambda item: (float(item.get("correctDirectionRate", 0.0)), -int(item.get("total", 0))),
    )[:10]
    return {
        "kind": "sampled_advantage_domain_probability_movement_v1",
        "domainKey": [
            "rolloutPoolKind",
            "suiteKind",
            "runtimeOpponentPolicyId",
            "runtimeActorSide",
            "playerDeckId",
            "opponentDeckId",
        ],
        "domainCount": int(len(domains)),
        "domains": domains,
        "worstDomains": worst,
    }


def _current_policy_domain_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    pool = str(metadata.get("rolloutPoolKind") or row.get("rolloutPoolKind") or "unknown")
    suite = str(metadata.get("suiteKind") or row.get("suiteKind") or metadata.get("sourceSuiteKind") or "unknown")
    opponent = str(
        metadata.get("runtimeOpponentPolicyId")
        or metadata.get("subjectOpponentPolicyId")
        or row.get("runtimeOpponentPolicyId")
        or "unknown"
    )
    if pool == "current_selfplay":
        opponent = "selfplay_current_actor"
    side = str(metadata.get("runtimeActorSide") or metadata.get("modelSide") or row.get("modelSide") or "unknown")
    player_deck = str(
        metadata.get("playerDeckId")
        or metadata.get("modelDeckId")
        or row.get("playerDeckId")
        or row.get("modelDeckId")
        or "unknown"
    )
    opponent_deck = str(
        metadata.get("opponentDeckId")
        or metadata.get("oldTop10DeckId")
        or row.get("opponentDeckId")
        or row.get("oldTop10DeckId")
        or "unknown"
    )
    return pool, suite, opponent, side, player_deck, opponent_deck


def _current_policy_sign(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number) or number == 0.0:
        return 0
    return 1 if number > 0.0 else -1


def _current_policy_local_step_reward(row: Mapping[str, Any]) -> float | None:
    label = row.get("trajectoryPolicyLabel") if isinstance(row.get("trajectoryPolicyLabel"), Mapping) else {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    for source in (label, row, metadata):
        value = _float_or_none(source.get("localStepReward"))
        if value is not None and math.isfinite(float(value)):
            return float(value)
    return None


def _current_policy_phase_bucket(row: Mapping[str, Any], row_index: int) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    explicit_window = str(row.get("turnPhaseWindow") or metadata.get("turnPhaseWindow") or "").strip()
    if explicit_window:
        return f"turnPhase:{explicit_window}"
    turn_value = row.get("turnIndex", row.get("gameTurn", metadata.get("turnIndex", metadata.get("gameTurn"))))
    phase_value = row.get("gamePhase", metadata.get("gamePhase", row.get("phase", metadata.get("phase"))))
    if turn_value is not None or phase_value is not None:
        return (
            f"turn:{turn_value if turn_value is not None else 'unknown'}"
            f"|phase:{phase_value if phase_value is not None else 'unknown'}"
        )
    step_value = (
        row.get("episodeStepIndex")
        or metadata.get("episodeStepIndex")
        or row.get("actionSetDecisionIndex")
        or metadata.get("actionSetDecisionIndex")
        or row_index
    )
    try:
        step = int(step_value)
    except (TypeError, ValueError):
        step = int(row_index)
    return f"stepWindow:{step // 8}"


def _current_policy_signal_counter_record(values: Counter[str], *, bucket_type: str, bucket: str) -> dict[str, Any]:
    rows = int(values.get("rows", 0))
    positive_rows = int(values.get("positiveRows", 0))
    negative_rows = int(values.get("negativeRows", 0))
    movement_changed = int(values.get("movementChangedRows", 0))
    movement_correct = int(values.get("movementCorrectRows", 0))
    local_comparable = int(values.get("localComparableRows", 0))
    local_agree = int(values.get("localAgreeRows", 0))
    mc_comparable = int(values.get("mcComparableRows", 0))
    mc_agree = int(values.get("mcAgreeRows", 0))
    value_comparable = int(values.get("valueDeltaComparableRows", 0))
    value_agree = int(values.get("valueDeltaAgreeRows", 0))

    def rate(num: int, den: int) -> float | None:
        return float(num) / float(den) if den else None

    def mean(key: str, den: int) -> float | None:
        return float(values.get(key, 0.0)) / float(den) if den else None

    return {
        "bucketType": str(bucket_type),
        "bucket": str(bucket),
        "rows": int(rows),
        "positiveRows": int(positive_rows),
        "negativeRows": int(negative_rows),
        "gaeLocalComparableRows": int(local_comparable),
        "gaeLocalAgreeRows": int(local_agree),
        "gaeLocalAgreeRate": rate(local_agree, local_comparable),
        "gaeMcComparableRows": int(mc_comparable),
        "gaeMcAgreeRows": int(mc_agree),
        "gaeMcAgreeRate": rate(mc_agree, mc_comparable),
        "gaeValueDeltaComparableRows": int(value_comparable),
        "gaeValueDeltaAgreeRows": int(value_agree),
        "gaeValueDeltaAgreeRate": rate(value_agree, value_comparable),
        "movementChangedRows": int(movement_changed),
        "movementCorrectRows": int(movement_correct),
        "movementCorrectRate": rate(movement_correct, movement_changed),
        "positiveMovementRows": int(values.get("positiveMovementRows", 0)),
        "positiveMovementCorrectRows": int(values.get("positiveMovementCorrectRows", 0)),
        "positiveMovementCorrectRate": rate(
            int(values.get("positiveMovementCorrectRows", 0)),
            int(values.get("positiveMovementRows", 0)),
        ),
        "negativeMovementRows": int(values.get("negativeMovementRows", 0)),
        "negativeMovementCorrectRows": int(values.get("negativeMovementCorrectRows", 0)),
        "negativeMovementCorrectRate": rate(
            int(values.get("negativeMovementCorrectRows", 0)),
            int(values.get("negativeMovementRows", 0)),
        ),
        "avgPositiveSelectedLogProbDelta": rate(
            float(values.get("positiveSelectedLogProbDelta", 0.0)),
            positive_rows,
        ),
        "avgNegativeSelectedLogProbDelta": rate(
            float(values.get("negativeSelectedLogProbDelta", 0.0)),
            negative_rows,
        ),
        "avgSelectedRankBefore": mean("selectedRankBeforeSum", rows),
        "avgSelectedRankAfter": mean("selectedRankAfterSum", rows),
        "selectedRankImprovedRate": rate(int(values.get("selectedRankImprovedRows", 0)), rows),
        "selectedRankWorsenedRate": rate(int(values.get("selectedRankWorsenedRows", 0)), rows),
        "avgHeadKl": mean("headKlSum", rows),
        "topAlternativeChangedRate": rate(int(values.get("topAlternativeChangedRows", 0)), rows),
    }


def _current_policy_signature_prior_null_model(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_signature: dict[str, dict[str, float]] = {}
    for item in rows:
        signature = str(item.get("signature") or "unknown")
        bucket = by_signature.setdefault(
            signature,
            {
                "rows": 0.0,
                "deltaSum": 0.0,
                "positiveRows": 0.0,
                "negativeRows": 0.0,
                "positiveDeltaSum": 0.0,
                "negativeDeltaSum": 0.0,
            },
        )
        delta = float(item.get("delta", 0.0) or 0.0)
        gae_sign = int(item.get("gaeSign", 0) or 0)
        bucket["rows"] += 1.0
        bucket["deltaSum"] += delta
        if gae_sign > 0:
            bucket["positiveRows"] += 1.0
            bucket["positiveDeltaSum"] += delta
        elif gae_sign < 0:
            bucket["negativeRows"] += 1.0
            bucket["negativeDeltaSum"] += delta

    predicted_rows = 0
    predicted_actual_correct = 0
    predicted_gae_correct = 0
    predicted_positive_correct = 0
    predicted_positive_rows = 0
    predicted_negative_correct = 0
    predicted_negative_rows = 0
    signature_records: list[dict[str, Any]] = []
    for item in rows:
        signature = str(item.get("signature") or "unknown")
        bucket = by_signature.get(signature)
        if not bucket or bucket["rows"] <= 1.0:
            continue
        leave_one_out_delta = (bucket["deltaSum"] - float(item.get("delta", 0.0) or 0.0)) / (
            bucket["rows"] - 1.0
        )
        predicted_sign = _current_policy_sign(leave_one_out_delta)
        movement_sign = int(item.get("movementSign", 0) or 0)
        gae_sign = int(item.get("gaeSign", 0) or 0)
        if predicted_sign == 0 or movement_sign == 0 or gae_sign == 0:
            continue
        predicted_rows += 1
        if predicted_sign == movement_sign:
            predicted_actual_correct += 1
        if predicted_sign == gae_sign:
            predicted_gae_correct += 1
        if gae_sign > 0:
            predicted_positive_rows += 1
            if predicted_sign > 0:
                predicted_positive_correct += 1
        elif gae_sign < 0:
            predicted_negative_rows += 1
            if predicted_sign < 0:
                predicted_negative_correct += 1

    for signature, bucket in by_signature.items():
        rows_for_signature = int(bucket["rows"])
        if rows_for_signature <= 1:
            continue
        positive_rows = int(bucket["positiveRows"])
        negative_rows = int(bucket["negativeRows"])
        mean_delta = bucket["deltaSum"] / float(rows_for_signature)
        positive_mean = (
            bucket["positiveDeltaSum"] / float(positive_rows)
            if positive_rows
            else None
        )
        negative_mean = (
            bucket["negativeDeltaSum"] / float(negative_rows)
            if negative_rows
            else None
        )
        same_direction_mixed_sign = (
            positive_mean is not None
            and negative_mean is not None
            and _current_policy_sign(float(positive_mean)) == _current_policy_sign(float(negative_mean))
            and _current_policy_sign(float(positive_mean)) != 0
        )
        signature_records.append(
            {
                "signature": str(signature),
                "rows": int(rows_for_signature),
                "positiveRows": int(positive_rows),
                "negativeRows": int(negative_rows),
                "meanDelta": float(mean_delta),
                "positiveMeanDelta": positive_mean,
                "negativeMeanDelta": negative_mean,
                "sameDirectionMixedSign": bool(same_direction_mixed_sign),
            }
        )

    signature_records.sort(
        key=lambda item: (
            not bool(item.get("sameDirectionMixedSign")),
            -int(item.get("rows", 0) or 0),
            str(item.get("signature") or ""),
        )
    )

    def rate(num: int, den: int) -> float | None:
        return float(num) / float(den) if den else None

    return {
        "kind": "signature_prior_null_model_v1",
        "description": "Predicts selected-logprob movement using only the leave-one-out mean delta for the selected action signature.",
        "rows": int(predicted_rows),
        "signatureGroups": int(len(signature_records)),
        "predictsObservedMovementRate": rate(predicted_actual_correct, predicted_rows),
        "predictsGaeDirectionRate": rate(predicted_gae_correct, predicted_rows),
        "positiveGaeDirectionRate": rate(predicted_positive_correct, predicted_positive_rows),
        "negativeGaeDirectionRate": rate(predicted_negative_correct, predicted_negative_rows),
        "sameDirectionMixedSignGroups": int(
            sum(1 for item in signature_records if bool(item.get("sameDirectionMixedSign")))
        ),
        "topSameDirectionMixedSignGroups": signature_records[:20],
    }


def _current_policy_same_signature_sign_separation_audit(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_rows_per_sign: int = 1,
    max_groups: int = 20,
) -> dict[str, Any]:
    by_signature: dict[str, dict[str, float]] = {}
    for item in rows:
        signature = str(item.get("signature") or "unknown")
        gae_sign = int(item.get("gaeSign", 0) or 0)
        if gae_sign == 0:
            continue
        delta = float(item.get("delta", 0.0) or 0.0)
        bucket = by_signature.setdefault(
            signature,
            {
                "positiveRows": 0.0,
                "negativeRows": 0.0,
                "positiveDeltaSum": 0.0,
                "negativeDeltaSum": 0.0,
            },
        )
        if gae_sign > 0:
            bucket["positiveRows"] += 1.0
            bucket["positiveDeltaSum"] += delta
        elif gae_sign < 0:
            bucket["negativeRows"] += 1.0
            bucket["negativeDeltaSum"] += delta

    groups: list[dict[str, Any]] = []
    separated_groups = 0
    both_aligned_groups = 0
    weighted_rows = 0
    weighted_separated_rows = 0
    weighted_both_aligned_rows = 0
    separation_sum = 0.0
    for signature, bucket in by_signature.items():
        positive_rows = int(bucket["positiveRows"])
        negative_rows = int(bucket["negativeRows"])
        if positive_rows < int(min_rows_per_sign) or negative_rows < int(min_rows_per_sign):
            continue
        rows_for_group = positive_rows + negative_rows
        positive_mean = bucket["positiveDeltaSum"] / float(positive_rows)
        negative_mean = bucket["negativeDeltaSum"] / float(negative_rows)
        separation = float(positive_mean - negative_mean)
        separated = separation > 0.0
        both_aligned = positive_mean > 0.0 and negative_mean < 0.0
        weighted_rows += rows_for_group
        weighted_separated_rows += rows_for_group if separated else 0
        weighted_both_aligned_rows += rows_for_group if both_aligned else 0
        separated_groups += 1 if separated else 0
        both_aligned_groups += 1 if both_aligned else 0
        separation_sum += separation
        groups.append(
            {
                "signature": str(signature),
                "rows": int(rows_for_group),
                "positiveRows": int(positive_rows),
                "negativeRows": int(negative_rows),
                "positiveMeanDelta": float(positive_mean),
                "negativeMeanDelta": float(negative_mean),
                "separationDelta": float(separation),
                "positiveAboveNegative": bool(separated),
                "bothSignsAligned": bool(both_aligned),
            }
        )

    groups.sort(
        key=lambda item: (
            bool(item.get("bothSignsAligned")),
            bool(item.get("positiveAboveNegative")),
            -int(item.get("rows", 0) or 0),
            float(item.get("separationDelta", 0.0) or 0.0),
            str(item.get("signature") or ""),
        )
    )

    def rate(num: int, den: int) -> float | None:
        return float(num) / float(den) if den else None

    return {
        "kind": "same_signature_sign_separation_audit_v1",
        "description": "For signatures with both positive and negative GAE rows, checks whether positive rows get a higher selected-logprob delta than negative rows.",
        "minRowsPerSign": int(min_rows_per_sign),
        "groups": int(len(groups)),
        "weightedRows": int(weighted_rows),
        "positiveAboveNegativeGroups": int(separated_groups),
        "positiveAboveNegativeRate": rate(separated_groups, len(groups)),
        "weightedPositiveAboveNegativeRate": rate(weighted_separated_rows, weighted_rows),
        "bothSignsAlignedGroups": int(both_aligned_groups),
        "bothSignsAlignedRate": rate(both_aligned_groups, len(groups)),
        "weightedBothSignsAlignedRate": rate(weighted_both_aligned_rows, weighted_rows),
        "avgSeparationDelta": rate(separation_sum, len(groups)),
        "worstGroups": groups[: max(0, int(max_groups))],
    }


def _current_policy_state_sign_separability_audit(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_rows: int = 20,
    max_groups: int = 20,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    def state_vector(row: Mapping[str, Any]) -> list[float] | None:
        values: list[float] = []
        for key in ("global_", "history_"):
            raw_values = row.get(key)
            if not isinstance(raw_values, list | tuple):
                continue
            for raw in raw_values:
                value = _float_or_none(raw)
                if value is None or not math.isfinite(float(value)):
                    return None
                values.append(float(value))
        return values if values else None

    for row in rows:
        label = _ygo_trajectory_policy_label(row)
        if label is None:
            continue
        selected_slot, _return_value, advantage = label
        gae_sign = _current_policy_sign(advantage)
        if gae_sign == 0:
            continue
        vector = state_vector(row)
        if vector is None:
            continue
        decision = str(row.get("decisionKind") or "unknown")
        signature = _selected_action_signature(row, int(selected_slot))
        grouped.setdefault(f"{decision}|{signature}", []).append(
            {"sign": int(gae_sign), "vector": vector}
        )

    def centroid(vectors: list[list[float]]) -> list[float]:
        width = len(vectors[0])
        return [sum(vector[index] for vector in vectors) / float(len(vectors)) for index in range(width)]

    def distance_sq(left: list[float], right: list[float]) -> float:
        return sum((float(a) - float(b)) ** 2 for a, b in zip(left, right, strict=True))

    records: list[dict[str, Any]] = []
    total_rows = 0
    total_comparable = 0
    total_correct = 0
    for signature, items in grouped.items():
        if len(items) < int(min_rows):
            continue
        dimensions = {len(item["vector"]) for item in items}
        if len(dimensions) != 1:
            continue
        positive = [item for item in items if int(item["sign"]) > 0]
        negative = [item for item in items if int(item["sign"]) < 0]
        if not positive or not negative:
            continue
        comparable = 0
        correct = 0
        positive_comparable = 0
        positive_correct = 0
        negative_comparable = 0
        negative_correct = 0
        for index, item in enumerate(items):
            pos_vectors = [
                other["vector"]
                for other_index, other in enumerate(items)
                if other_index != index and int(other["sign"]) > 0
            ]
            neg_vectors = [
                other["vector"]
                for other_index, other in enumerate(items)
                if other_index != index and int(other["sign"]) < 0
            ]
            if not pos_vectors or not neg_vectors:
                continue
            pos_distance = distance_sq(item["vector"], centroid(pos_vectors))
            neg_distance = distance_sq(item["vector"], centroid(neg_vectors))
            if abs(float(pos_distance) - float(neg_distance)) <= 1.0e-12:
                continue
            predicted_sign = 1 if pos_distance < neg_distance else -1
            actual_sign = int(item["sign"])
            comparable += 1
            is_correct = predicted_sign == actual_sign
            if is_correct:
                correct += 1
            if actual_sign > 0:
                positive_comparable += 1
                if is_correct:
                    positive_correct += 1
            else:
                negative_comparable += 1
                if is_correct:
                    negative_correct += 1
        if comparable <= 0:
            continue
        total_rows += len(items)
        total_comparable += comparable
        total_correct += correct
        records.append(
            {
                "signature": str(signature),
                "rows": int(len(items)),
                "positiveRows": int(len(positive)),
                "negativeRows": int(len(negative)),
                "stateFeatureDim": int(next(iter(dimensions))),
                "comparableRows": int(comparable),
                "nearestCentroidAgreeRate": float(correct) / float(comparable),
                "positiveAgreeRate": (
                    float(positive_correct) / float(positive_comparable)
                    if positive_comparable
                    else None
                ),
                "negativeAgreeRate": (
                    float(negative_correct) / float(negative_comparable)
                    if negative_comparable
                    else None
                ),
            }
        )

    records.sort(
        key=lambda item: (
            float(item.get("nearestCentroidAgreeRate") or 0.0),
            -int(item.get("rows", 0) or 0),
            str(item.get("signature") or ""),
        )
    )
    return {
        "kind": "state_sign_separability_audit_v1",
        "featureSource": "global_+history_",
        "minRows": int(min_rows),
        "groups": int(len(records)),
        "rows": int(total_rows),
        "comparableRows": int(total_comparable),
        "nearestCentroidAgreeRate": (
            float(total_correct) / float(total_comparable)
            if total_comparable
            else None
        ),
        "worstGroups": records[: max(0, int(max_groups))],
    }


def _outcome_policy_signal_correlation_bucket_audit_from_scores(
    rows: list[Mapping[str, Any]],
    base_scores_by_row: list[list[float | None]],
    candidate_scores_by_row: list[list[float | None]],
    *,
    max_buckets: int = 300,
    min_rows: int = 8,
) -> dict[str, Any]:
    by_bucket: dict[tuple[str, str], Counter[str]] = {}
    totals: Counter[str] = Counter()
    prior_rows: list[dict[str, Any]] = []
    no_choice_rows_skipped = 0

    def bump(bucket_type: str, bucket: str, row_stats: Mapping[str, Any]) -> None:
        stats = by_bucket.setdefault((str(bucket_type), str(bucket)), Counter())
        for key, value in row_stats.items():
            stats[str(key)] += value

    for row_index, (row, base_scores, candidate_scores) in enumerate(
        zip(rows, base_scores_by_row, candidate_scores_by_row, strict=False)
    ):
        label = _ygo_trajectory_policy_label(row)
        if label is None:
            continue
        selected_slot, _return_value, advantage = label
        gae_sign = _current_policy_sign(advantage)
        if gae_sign == 0:
            continue
        base_log_probs = _masked_log_probs_for_scores(base_scores, row)
        candidate_log_probs = _masked_log_probs_for_scores(candidate_scores, row)
        shared_legal_slots = [slot for slot in base_log_probs.keys() if slot in candidate_log_probs]
        if len(shared_legal_slots) <= 1:
            no_choice_rows_skipped += 1
            continue
        if selected_slot not in base_log_probs or selected_slot not in candidate_log_probs:
            continue

        delta = float(candidate_log_probs[selected_slot]) - float(base_log_probs[selected_slot])
        movement_sign = _current_policy_sign(delta)
        selected_rank_before = 1 + sum(
            1 for slot in shared_legal_slots if float(base_log_probs[slot]) > float(base_log_probs[selected_slot])
        )
        selected_rank_after = 1 + sum(
            1
            for slot in shared_legal_slots
            if float(candidate_log_probs[slot]) > float(candidate_log_probs[selected_slot])
        )
        head_kl = sum(
            math.exp(float(base_log_probs[slot]))
            * (float(base_log_probs[slot]) - float(candidate_log_probs[slot]))
            for slot in shared_legal_slots
        )
        alternative_slots = [slot for slot in shared_legal_slots if int(slot) != int(selected_slot)]
        top_alternative_before = (
            max(alternative_slots, key=lambda slot: float(base_log_probs[slot]))
            if alternative_slots
            else None
        )
        top_alternative_after = (
            max(alternative_slots, key=lambda slot: float(candidate_log_probs[slot]))
            if alternative_slots
            else None
        )
        mc_return = _current_policy_row_mc_return(row)
        mc_sign = _current_policy_sign(mc_return)
        local_sign = _current_policy_sign(_current_policy_local_step_reward(row))
        old_value = _current_policy_old_state_value(row)
        value_delta_sign = 0
        if mc_return is not None and old_value is not None:
            value_delta_sign = _current_policy_sign(float(mc_return) - float(old_value))

        row_stats: dict[str, float | int] = {"rows": 1}
        row_stats["selectedRankBeforeSum"] = float(selected_rank_before)
        row_stats["selectedRankAfterSum"] = float(selected_rank_after)
        if int(selected_rank_after) < int(selected_rank_before):
            row_stats["selectedRankImprovedRows"] = 1
        elif int(selected_rank_after) > int(selected_rank_before):
            row_stats["selectedRankWorsenedRows"] = 1
        row_stats["headKlSum"] = float(head_kl)
        if top_alternative_before is not None and top_alternative_after is not None:
            row_stats["topAlternativeChangedRows"] = (
                1 if int(top_alternative_before) != int(top_alternative_after) else 0
            )
        if gae_sign > 0:
            row_stats["positiveRows"] = 1
            row_stats["positiveSelectedLogProbDelta"] = float(delta)
        else:
            row_stats["negativeRows"] = 1
            row_stats["negativeSelectedLogProbDelta"] = float(delta)
        if local_sign:
            row_stats["localComparableRows"] = 1
            row_stats["localAgreeRows"] = 1 if local_sign == gae_sign else 0
        if mc_sign:
            row_stats["mcComparableRows"] = 1
            row_stats["mcAgreeRows"] = 1 if mc_sign == gae_sign else 0
        if value_delta_sign:
            row_stats["valueDeltaComparableRows"] = 1
            row_stats["valueDeltaAgreeRows"] = 1 if value_delta_sign == gae_sign else 0
        if movement_sign:
            row_stats["movementChangedRows"] = 1
            row_stats["movementCorrectRows"] = 1 if movement_sign == gae_sign else 0
            if gae_sign > 0:
                row_stats["positiveMovementRows"] = 1
                row_stats["positiveMovementCorrectRows"] = 1 if movement_sign > 0 else 0
            else:
                row_stats["negativeMovementRows"] = 1
                row_stats["negativeMovementCorrectRows"] = 1 if movement_sign < 0 else 0

        decision = str(row.get("decisionKind") or "unknown")
        signature = _selected_action_signature(row, int(selected_slot))
        prior_rows.append(
            {
                "signature": f"{decision}|{signature}",
                "gaeSign": int(gae_sign),
                "movementSign": int(movement_sign),
                "delta": float(delta),
            }
        )
        domain = "|".join(_current_policy_domain_key(row))
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        side = str(metadata.get("runtimeActorSide") or metadata.get("modelSide") or row.get("modelSide") or "unknown")
        phase = _current_policy_phase_bucket(row, row_index)
        buckets = (
            ("decisionKind", decision),
            ("actionSignature", f"{decision}|{signature}"),
            ("domain", domain),
            ("side", side),
            ("phase", phase),
            ("decisionSide", f"{decision}|{side}"),
            ("decisionPhase", f"{decision}|{phase}"),
            ("domainDecision", f"{domain}|{decision}"),
            ("domainDecisionSignature", f"{domain}|{decision}|{signature}"),
        )
        for key, value in row_stats.items():
            totals[str(key)] += value
        for bucket_type, bucket in buckets:
            bump(bucket_type, bucket, row_stats)

    all_records = [
        _current_policy_signal_counter_record(values, bucket_type=bucket_type, bucket=bucket)
        for (bucket_type, bucket), values in by_bucket.items()
        if int(values.get("rows", 0)) >= int(min_rows)
    ]

    def low_rate(record: Mapping[str, Any], key: str) -> tuple[float, int]:
        value = record.get(key)
        return (float(value) if value is not None else 2.0, -int(record.get("rows", 0) or 0))

    records_by_rows = sorted(all_records, key=lambda item: (-int(item.get("rows", 0)), item["bucketType"], item["bucket"]))
    bounded_records = records_by_rows[: max(0, int(max_buckets))]
    return {
        "kind": "current_policy_signal_correlation_bucket_audit_v1",
        "bucketFields": [
            "decisionKind",
            "actionSignature",
            "domain",
            "side",
            "phase",
            "decisionSide",
            "decisionPhase",
            "domainDecision",
            "domainDecisionSignature",
        ],
        "minRows": int(min_rows),
        "maxBuckets": int(max_buckets),
        "inputRows": int(len(rows)),
        "total": _current_policy_signal_counter_record(totals, bucket_type="all", bucket="all"),
        "signaturePriorNullModel": _current_policy_signature_prior_null_model(prior_rows),
        "sameSignatureSignSeparation": _current_policy_same_signature_sign_separation_audit(
            prior_rows,
        ),
        "stateSignSeparability": _current_policy_state_sign_separability_audit(
            rows,
            min_rows=max(int(min_rows), 20),
        ),
        "noChoiceRowsSkipped": int(no_choice_rows_skipped),
        "bucketsReturned": int(len(bounded_records)),
        "bucketsTotal": int(len(all_records)),
        "buckets": bounded_records,
        "worstLocalGaeBuckets": sorted(
            [row for row in all_records if row.get("gaeLocalAgreeRate") is not None],
            key=lambda item: low_rate(item, "gaeLocalAgreeRate"),
        )[:20],
        "worstMcGaeBuckets": sorted(
            [row for row in all_records if row.get("gaeMcAgreeRate") is not None],
            key=lambda item: low_rate(item, "gaeMcAgreeRate"),
        )[:20],
        "worstValueDeltaGaeBuckets": sorted(
            [row for row in all_records if row.get("gaeValueDeltaAgreeRate") is not None],
            key=lambda item: low_rate(item, "gaeValueDeltaAgreeRate"),
        )[:20],
        "worstMovementBuckets": sorted(
            [row for row in all_records if row.get("movementCorrectRate") is not None],
            key=lambda item: low_rate(item, "movementCorrectRate"),
        )[:20],
        "worstPositiveMovementBuckets": sorted(
            [row for row in all_records if row.get("positiveMovementCorrectRate") is not None],
            key=lambda item: low_rate(item, "positiveMovementCorrectRate"),
        )[:20],
        "worstNegativeMovementBuckets": sorted(
            [row for row in all_records if row.get("negativeMovementCorrectRate") is not None],
            key=lambda item: low_rate(item, "negativeMovementCorrectRate"),
        )[:20],
    }


def _write_current_policy_signal_bucket_audit_files(
    audit: Mapping[str, Any],
    *,
    out_dir: Path,
) -> dict[str, str]:
    json_path = out_dir / "current_policy_signal_bucket_audit.json"
    csv_path = out_dir / "current_policy_signal_bucket_audit.csv"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    buckets = list(audit.get("buckets") or [])
    fieldnames = [
        "bucketType",
        "bucket",
        "rows",
        "positiveRows",
        "negativeRows",
        "gaeLocalAgreeRate",
        "gaeMcAgreeRate",
        "gaeValueDeltaAgreeRate",
        "movementCorrectRate",
        "positiveMovementCorrectRate",
        "negativeMovementCorrectRate",
        "avgPositiveSelectedLogProbDelta",
        "avgNegativeSelectedLogProbDelta",
        "avgSelectedRankBefore",
        "avgSelectedRankAfter",
        "selectedRankImprovedRate",
        "selectedRankWorsenedRate",
        "avgHeadKl",
        "topAlternativeChangedRate",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in buckets:
            writer.writerow({key: row.get(key) for key in fieldnames})
    return {"json": str(json_path), "csv": str(csv_path)}


def _masked_log_probs_for_scores(scores: list[float | None], row: Mapping[str, Any]) -> dict[int, float]:
    legal_slots = [
        slot
        for slot, score in enumerate(scores)
        if score is not None and slot in set(_ygo_legal_slots(row))
    ]
    if not legal_slots:
        return {}
    max_score = max(float(scores[slot]) for slot in legal_slots)
    normalizer = sum(math.exp(float(scores[slot]) - max_score) for slot in legal_slots)
    if normalizer <= 0.0 or not math.isfinite(normalizer):
        return {}
    log_normalizer = math.log(normalizer)
    return {
        int(slot): float(scores[slot]) - max_score - log_normalizer
        for slot in legal_slots
    }


def _outcome_policy_movement_bucket(values: Counter[str]) -> dict[str, Any]:
    positive_rows = int(values.get("positiveRows", 0))
    negative_rows = int(values.get("negativeRows", 0))
    total = int(values.get("total", 0))
    correct = int(values.get("positiveCorrectDirection", 0) + values.get("negativeCorrectDirection", 0))
    wrong = int(values.get("positiveWrongDirection", 0) + values.get("negativeWrongDirection", 0))
    changed = correct + wrong
    return {
        "total": total,
        "positiveAdvantageRows": positive_rows,
        "negativeAdvantageRows": negative_rows,
        "changedDirectionRows": int(changed),
        "changedDirectionRate": float(changed / total) if total else 0.0,
        "correctDirectionRows": correct,
        "wrongDirectionRows": int(wrong),
        "correctDirectionRate": float(correct / total) if total else 0.0,
        "positiveCorrectDirectionRate": (
            float(values.get("positiveCorrectDirection", 0) / positive_rows) if positive_rows else 0.0
        ),
        "negativeCorrectDirectionRate": (
            float(values.get("negativeCorrectDirection", 0) / negative_rows) if negative_rows else 0.0
        ),
        "avgPositiveSelectedLogProbDelta": (
            float(values.get("positiveSelectedLogProbDelta", 0.0) / positive_rows) if positive_rows else 0.0
        ),
        "avgNegativeSelectedLogProbDelta": (
            float(values.get("negativeSelectedLogProbDelta", 0.0) / negative_rows) if negative_rows else 0.0
        ),
    }


def _outcome_policy_movement_threshold_report(
    values_by_threshold: Mapping[str, Counter[str]],
    *,
    tiny_delta_thresholds: Sequence[tuple[str, float]],
) -> dict[str, Any]:
    thresholds: list[dict[str, Any]] = []
    for label, threshold in tiny_delta_thresholds:
        values = values_by_threshold.get(label, Counter())
        changed_rows = int(values.get("changedRows", 0))
        positive_rows = int(values.get("positiveRows", 0))
        negative_rows = int(values.get("negativeRows", 0))
        correct_rows = int(values.get("correctDirection", 0))
        wrong_rows = int(values.get("wrongDirection", 0))
        thresholds.append(
            {
                "minAbsLogProbDelta": float(threshold),
                "changedDirectionRows": int(changed_rows),
                "correctDirectionRows": int(correct_rows),
                "wrongDirectionRows": int(wrong_rows),
                "changedDirectionPrecision": (
                    float(correct_rows) / float(changed_rows) if changed_rows else None
                ),
                "positiveAdvantageRows": int(positive_rows),
                "negativeAdvantageRows": int(negative_rows),
                "positiveCorrectDirectionRate": (
                    float(values.get("positiveCorrectDirection", 0) / positive_rows)
                    if positive_rows
                    else None
                ),
                "negativeCorrectDirectionRate": (
                    float(values.get("negativeCorrectDirection", 0) / negative_rows)
                    if negative_rows
                    else None
                ),
                "avgPositiveSelectedLogProbDelta": (
                    float(values.get("positiveSelectedLogProbDelta", 0.0) / positive_rows)
                    if positive_rows
                    else None
                ),
                "avgNegativeSelectedLogProbDelta": (
                    float(values.get("negativeSelectedLogProbDelta", 0.0) / negative_rows)
                    if negative_rows
                    else None
                ),
            }
        )
    return {
        "kind": "movement_tiny_delta_exclusion_v1",
        "thresholds": thresholds,
    }


def _filter_current_policy_target_action_safe_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    skipped_reasons: Counter[str] = Counter()
    skipped_by_decision: Counter[str] = Counter()
    for row in rows:
        report = target_action_semantics_from_rows([row])
        if bool(report.get("targetActionSemanticsGatePassed")):
            accepted.append(row)
            continue
        decision = str(row.get("decisionKind") or "unknown")
        skipped_by_decision[decision] += 1
        reasons = list(report.get("blockingReasons") or [])
        if not reasons:
            reasons = ["target_action_semantics_gate_failed"]
        for reason in reasons:
            skipped_reasons[str(reason)] += 1
    return accepted, {
        "kind": "current_policy_target_action_semantics_filter_v1",
        "inputRows": int(len(rows)),
        "acceptedRows": int(len(accepted)),
        "skippedRows": int(len(rows) - len(accepted)),
        "skippedRowsByDecisionKind": {
            key: int(value)
            for key, value in sorted(skipped_by_decision.items())
        },
        "skippedReasons": {
            key: int(value)
            for key, value in sorted(skipped_reasons.items())
        },
    }


def _filter_current_policy_play_card_target_safe_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    skipped_reasons: Counter[str] = Counter()
    skipped_by_decision: Counter[str] = Counter()
    for row in rows:
        report = play_card_target_semantics_from_rows([row])
        if bool(report.get("targetSemanticsGatePassed")):
            accepted.append(row)
            continue
        decision = str(row.get("decisionKind") or "unknown")
        skipped_by_decision[decision] += 1
        reasons = list(report.get("blockingReasons") or [])
        if not reasons:
            reasons = ["play_card_target_semantics_gate_failed"]
        for reason in reasons:
            skipped_reasons[str(reason)] += 1
    return accepted, {
        "kind": "current_policy_play_card_target_semantics_filter_v1",
        "inputRows": int(len(rows)),
        "acceptedRows": int(len(accepted)),
        "skippedRows": int(len(rows) - len(accepted)),
        "skippedRowsByDecisionKind": {
            key: int(value)
            for key, value in sorted(skipped_by_decision.items())
        },
        "skippedReasons": {
            key: int(value)
            for key, value in sorted(skipped_reasons.items())
        },
    }


def _current_policy_runtime_recurrent_key(row: Mapping[str, Any]) -> str:
    metadata = _mapping(row.get("metadata"))
    return _first_present_text(
        row.get("runtimeRecurrentKey"),
        metadata.get("runtimeRecurrentKey"),
        row.get("runtimeSequenceId"),
        metadata.get("runtimeSequenceId"),
    )


def _mark_current_policy_context_only_row(row: dict[str, Any], *, reason: str) -> None:
    metadata = dict(_mapping(row.get("metadata")))
    row["lossMask"] = False
    row["trainingWeight"] = 0.0
    row["currentPolicyContextOnly"] = True
    row["currentPolicyContextOnlyReason"] = str(reason)
    metadata["lossMask"] = False
    metadata["trainingWeight"] = 0.0
    metadata["currentPolicyContextOnly"] = True
    metadata["currentPolicyContextOnlyReason"] = str(reason)
    row["metadata"] = metadata


def _current_policy_context_only_row(row: Mapping[str, Any]) -> bool:
    metadata = _mapping(row.get("metadata"))
    return bool(row.get("currentPolicyContextOnly") or metadata.get("currentPolicyContextOnly"))


def _trajectory_advantage_runtime_eval(
    model: Any,
    rows: list[Mapping[str, Any]],
    *,
    runtime_base_scorer: Any,
    runtime_aux_score_weight: float,
) -> dict[str, Any]:
    scores_by_row = model.score_rows_batched(list(rows))
    aux_scores_by_row_id = {
        id(row): aux_scores
        for row, aux_scores in zip(rows, scores_by_row, strict=False)
    }
    total = 0
    direction_correct = 0
    positive_rows = 0
    negative_rows = 0
    selected_prob_delta_sum = 0.0
    selected_prob_delta_abs_sum = 0.0
    positive_selected_prob_delta_sum = 0.0
    negative_selected_prob_delta_sum = 0.0
    weight_sum = 0.0
    weighted_direction_correct_sum = 0.0
    weighted_selected_prob_delta_sum = 0.0
    weighted_selected_prob_delta_abs_sum = 0.0
    weighted_positive_sum = 0.0
    weighted_negative_sum = 0.0
    weighted_positive_selected_prob_delta_sum = 0.0
    weighted_negative_selected_prob_delta_sum = 0.0
    row_runtime_base_rows = 0
    scorer_runtime_base_rows = 0
    by_decision: dict[str, dict[str, Any]] = {}
    for row, aux_scores in zip(rows, scores_by_row, strict=False):
        label = _ygo_trajectory_policy_label(row)
        if label is None:
            continue
        selected_slot, _return_value, advantage = label
        legal_slots = _ygo_legal_slots(row)
        if selected_slot not in set(legal_slots):
            continue
        runtime_row_scores = row_runtime_total_scores(
            row,
            require_explicit_mode=True,
            require_policy_provenance=True,
        )
        runtime_base_source = "row_runtime_total"
        base_scores = runtime_row_scores
        if base_scores is None:
            base_scores = runtime_base_scorer.score_row(row)
            runtime_base_source = "scorer_runtime_base"
        if base_scores is None:
            continue
        max_correction = (
            BOUNDED_RUNTIME_AUX_MAX_CORRECTION
            if is_bounded_runtime_aux_objective(getattr(model, "runtimeAuxTrainingObjective", None))
            else None
        )
        runtime_scores = [
            compose_runtime_aux_score(
                base_scores[slot] if 0 <= slot < len(base_scores) else None,
                aux_scores[slot] if 0 <= slot < len(aux_scores) else None,
                weight=float(runtime_aux_score_weight),
                max_correction=max_correction,
            )
            for slot in range(max(len(base_scores), len(aux_scores)))
        ]
        old_prob = _softmax_slot_probability(base_scores, selected_slot, legal_slots)
        new_prob = _softmax_slot_probability(runtime_scores, selected_slot, legal_slots)
        if old_prob is None or new_prob is None:
            continue
        selected_prob_delta = float(new_prob) - float(old_prob)
        if advantage > 0.0:
            positive_rows += 1
            positive_selected_prob_delta_sum += selected_prob_delta
            correct = selected_prob_delta > 0.0
        elif advantage < 0.0:
            negative_rows += 1
            negative_selected_prob_delta_sum += selected_prob_delta
            correct = selected_prob_delta < 0.0
        else:
            continue
        if runtime_base_source == "row_runtime_total":
            row_runtime_base_rows += 1
        else:
            scorer_runtime_base_rows += 1
        row_weight = max(0.0, float(_ygo_row_training_weight(row)))
        total += 1
        weight_sum += row_weight
        selected_prob_delta_sum += selected_prob_delta
        selected_prob_delta_abs_sum += abs(selected_prob_delta)
        weighted_selected_prob_delta_sum += row_weight * selected_prob_delta
        weighted_selected_prob_delta_abs_sum += row_weight * abs(selected_prob_delta)
        if correct:
            direction_correct += 1
            weighted_direction_correct_sum += row_weight
        decision = str(row.get("decisionKind") or "unknown")
        bucket = by_decision.setdefault(
            decision,
            {
                "total": 0,
                "correct": 0,
                "weightSum": 0.0,
                "weightedCorrectSum": 0.0,
                "selectedProbDeltaSum": 0.0,
                "selectedProbDeltaAbsSum": 0.0,
                "weightedSelectedProbDeltaSum": 0.0,
                "weightedSelectedProbDeltaAbsSum": 0.0,
                "positiveRows": 0,
                "negativeRows": 0,
                "positiveWeightSum": 0.0,
                "negativeWeightSum": 0.0,
                "positiveSelectedProbDeltaSum": 0.0,
                "negativeSelectedProbDeltaSum": 0.0,
                "weightedPositiveSelectedProbDeltaSum": 0.0,
                "weightedNegativeSelectedProbDeltaSum": 0.0,
            },
        )
        bucket["total"] += 1
        bucket["weightSum"] += row_weight
        bucket["selectedProbDeltaSum"] += selected_prob_delta
        bucket["selectedProbDeltaAbsSum"] += abs(selected_prob_delta)
        bucket["weightedSelectedProbDeltaSum"] += row_weight * selected_prob_delta
        bucket["weightedSelectedProbDeltaAbsSum"] += row_weight * abs(selected_prob_delta)
        if advantage > 0.0:
            bucket["positiveRows"] += 1
            bucket["positiveWeightSum"] += row_weight
            bucket["positiveSelectedProbDeltaSum"] += selected_prob_delta
            bucket["weightedPositiveSelectedProbDeltaSum"] += row_weight * selected_prob_delta
            weighted_positive_sum += row_weight
            weighted_positive_selected_prob_delta_sum += row_weight * selected_prob_delta
        elif advantage < 0.0:
            bucket["negativeRows"] += 1
            bucket["negativeWeightSum"] += row_weight
            bucket["negativeSelectedProbDeltaSum"] += selected_prob_delta
            bucket["weightedNegativeSelectedProbDeltaSum"] += row_weight * selected_prob_delta
            weighted_negative_sum += row_weight
            weighted_negative_selected_prob_delta_sum += row_weight * selected_prob_delta
        if correct:
            bucket["correct"] += 1
            bucket["weightedCorrectSum"] += row_weight
    group_expected_value_eval = _trajectory_group_expected_action_value_eval(
        rows,
        aux_scores_by_row_id=aux_scores_by_row_id,
        runtime_base_scorer=runtime_base_scorer,
        runtime_aux_score_weight=runtime_aux_score_weight,
        model=model,
    )
    return {
        "total": int(total),
        "directionCorrect": int(direction_correct),
        "directionAccuracy": float(direction_correct / total) if total else 0.0,
        "weightSum": float(weight_sum),
        "weightedDirectionCorrect": float(weighted_direction_correct_sum),
        "weightedDirectionAccuracy": (
            float(weighted_direction_correct_sum / weight_sum) if weight_sum else 0.0
        ),
        "positiveAdvantageRows": int(positive_rows),
        "negativeAdvantageRows": int(negative_rows),
        "selectedProbDeltaMean": float(selected_prob_delta_sum / total) if total else 0.0,
        "selectedProbDeltaAbsMean": float(selected_prob_delta_abs_sum / total) if total else 0.0,
        "weightedSelectedProbDeltaMean": (
            float(weighted_selected_prob_delta_sum / weight_sum) if weight_sum else 0.0
        ),
        "weightedSelectedProbDeltaAbsMean": (
            float(weighted_selected_prob_delta_abs_sum / weight_sum) if weight_sum else 0.0
        ),
        "positiveAdvantageSelectedProbDeltaMean": (
            float(positive_selected_prob_delta_sum / positive_rows) if positive_rows else 0.0
        ),
        "negativeAdvantageSelectedProbDeltaMean": (
            float(negative_selected_prob_delta_sum / negative_rows) if negative_rows else 0.0
        ),
        "weightedPositiveAdvantageSelectedProbDeltaMean": (
            float(weighted_positive_selected_prob_delta_sum / weighted_positive_sum)
            if weighted_positive_sum
            else 0.0
        ),
        "weightedNegativeAdvantageSelectedProbDeltaMean": (
            float(weighted_negative_selected_prob_delta_sum / weighted_negative_sum)
            if weighted_negative_sum
            else 0.0
        ),
        "runtimeBaseScoreSource": _runtime_base_score_source_summary(
            row_runtime_base_groups=row_runtime_base_rows,
            scorer_runtime_base_groups=scorer_runtime_base_rows,
        ),
        "runtimeBaseScoreSourceRows": {
            "rowRuntimeTotal": int(row_runtime_base_rows),
            "scorerRuntimeBase": int(scorer_runtime_base_rows),
        },
        "byDecisionKind": {
            decision: {
                "total": int(values["total"]),
                "correct": int(values["correct"]),
                "directionAccuracy": (
                    float(values["correct"] / values["total"])
                    if values["total"]
                    else 0.0
                ),
                "weightSum": float(values["weightSum"]),
                "weightedDirectionCorrect": float(values["weightedCorrectSum"]),
                "weightedDirectionAccuracy": (
                    float(values["weightedCorrectSum"] / values["weightSum"])
                    if values["weightSum"]
                    else 0.0
                ),
                "selectedProbDeltaMean": (
                    float(values["selectedProbDeltaSum"] / values["total"])
                    if values["total"]
                    else 0.0
                ),
                "selectedProbDeltaAbsMean": (
                    float(values["selectedProbDeltaAbsSum"] / values["total"])
                    if values["total"]
                    else 0.0
                ),
                "weightedSelectedProbDeltaMean": (
                    float(values["weightedSelectedProbDeltaSum"] / values["weightSum"])
                    if values["weightSum"]
                    else 0.0
                ),
                "weightedSelectedProbDeltaAbsMean": (
                    float(values["weightedSelectedProbDeltaAbsSum"] / values["weightSum"])
                    if values["weightSum"]
                    else 0.0
                ),
                "positiveAdvantageRows": int(values["positiveRows"]),
                "negativeAdvantageRows": int(values["negativeRows"]),
                "positiveAdvantageSelectedProbDeltaMean": (
                    float(values["positiveSelectedProbDeltaSum"] / values["positiveRows"])
                    if values["positiveRows"]
                    else 0.0
                ),
                "negativeAdvantageSelectedProbDeltaMean": (
                    float(values["negativeSelectedProbDeltaSum"] / values["negativeRows"])
                    if values["negativeRows"]
                    else 0.0
                ),
                "weightedPositiveAdvantageSelectedProbDeltaMean": (
                    float(values["weightedPositiveSelectedProbDeltaSum"] / values["positiveWeightSum"])
                    if values["positiveWeightSum"]
                    else 0.0
                ),
                "weightedNegativeAdvantageSelectedProbDeltaMean": (
                    float(values["weightedNegativeSelectedProbDeltaSum"] / values["negativeWeightSum"])
                    if values["negativeWeightSum"]
                    else 0.0
                ),
            }
            for decision, values in sorted(by_decision.items())
        },
        "groupExpectedActionValueEval": group_expected_value_eval,
    }


def _first_present_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _current_policy_episode_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    label = _mapping(row.get("trajectoryPolicyLabel"))
    metadata = _mapping(row.get("metadata"))
    actor_side = _first_present_text(
        row.get("trajectoryActorSide"),
        metadata.get("trajectoryActorSide"),
        row.get("modelSide"),
        metadata.get("modelSide"),
    )
    sequence_id = _first_present_text(row.get("sequenceId"), metadata.get("sequenceId"), label.get("sequenceId"))
    if sequence_id:
        return ("sequence", sequence_id, "", actor_side)
    episode_id = _first_present_text(row.get("episodeId"), metadata.get("episodeId"), label.get("episodeId"))
    if episode_id:
        return ("episode", episode_id, "", actor_side)
    run_id = _first_present_text(row.get("runId"), metadata.get("runId"))
    task_id = _first_present_text(row.get("taskId"), metadata.get("taskId"))
    episode_index = _first_present_text(row.get("episodeIndex"), metadata.get("episodeIndex"))
    state_key = _first_present_text(row.get("stateKey"), metadata.get("stateKey"), id(row))
    if not run_id or not task_id or not episode_index:
        return ("single_row", state_key, "", actor_side)
    return (run_id, task_id, episode_index, actor_side)


def _current_policy_decision_index(row: Mapping[str, Any]) -> int:
    metadata = _mapping(row.get("metadata"))
    value = row.get("actionSetDecisionIndex", metadata.get("actionSetDecisionIndex"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _current_policy_label_return(row: Mapping[str, Any]) -> float:
    label = _mapping(row.get("trajectoryPolicyLabel"))
    value = _finite_float_or_none(label.get("returnValue", row.get("trajectoryReturn")))
    return 0.0 if value is None else float(value)


def _current_policy_step_reward(row: Mapping[str, Any]) -> float | None:
    label = _mapping(row.get("trajectoryPolicyLabel"))
    metadata = _mapping(row.get("metadata"))
    return _finite_float_or_none(
        label.get(
            "stepReward",
            row.get(
                "trajectoryStepReward",
                metadata.get("trajectoryStepReward"),
            ),
        )
    )


def _current_policy_local_step_reward(row: Mapping[str, Any]) -> float | None:
    label = _mapping(row.get("trajectoryPolicyLabel"))
    metadata = _mapping(row.get("metadata"))
    return _finite_float_or_none(
        label.get(
            "localStepReward",
            row.get(
                "trajectoryLocalStepReward",
                metadata.get("trajectoryLocalStepReward"),
            ),
        )
    )


def _current_policy_bool(row: Mapping[str, Any], *keys: str) -> bool:
    label = _mapping(row.get("trajectoryPolicyLabel"))
    metadata = _mapping(row.get("metadata"))
    for source in (label, row, metadata):
        for key in keys:
            if key not in source:
                continue
            value = source.get(key)
            if isinstance(value, bool):
                return bool(value)
            text = str(value).strip().lower()
            if text in {"1", "true", "yes"}:
                return True
            if text in {"0", "false", "no"}:
                return False
    return False


def _current_policy_float_vector(row: Mapping[str, Any], *keys: str) -> list[float]:
    metadata = _mapping(row.get("metadata"))
    for source in (row, metadata):
        for key in keys:
            value = source.get(key)
            if not isinstance(value, list | tuple):
                continue
            out: list[float] = []
            for item in value:
                parsed = _finite_float_or_none(item)
                if parsed is not None:
                    out.append(float(parsed))
            if out:
                return out
    return []


def _current_policy_done(row: Mapping[str, Any]) -> bool:
    return _current_policy_bool(row, "trajectoryDone", "done")


def _current_policy_truncated(row: Mapping[str, Any]) -> bool:
    return _current_policy_bool(row, "trajectoryTruncated", "truncated")


def _annotate_current_policy_sequence_segments(
    rows: list[dict[str, Any]],
    *,
    chunk_length: int = 16,
    copy_rows: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bounded_chunk = max(1, int(chunk_length))
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row_index, row in enumerate(rows):
        metadata = dict(_mapping(row.get("metadata")))
        runtime_recurrent_key = _first_present_text(
            row.get("runtimeRecurrentKey"),
            metadata.get("runtimeRecurrentKey"),
            row.get("runtimeSequenceId"),
            metadata.get("runtimeSequenceId"),
        )
        if runtime_recurrent_key:
            row["runtimeRecurrentOrderIndex"] = int(row_index)
            metadata["runtimeRecurrentOrderIndex"] = int(row_index)
            row["metadata"] = metadata
        groups.setdefault(_current_policy_episode_key(row), []).append(row)

    annotated: list[dict[str, Any]] = []
    segments_by_length: Counter[str] = Counter()
    segment_count = 0
    reset_rows = 0
    done_rows = 0
    truncated_rows = 0
    continued_episode_rows = 0
    continued_episode_first_rows = 0
    continued_episode_first_rows_reset_hidden_false = 0
    continued_episode_batch_reset_rows = 0
    continued_episode_missing_initial_hidden_state_rows = 0
    segment_boundary_reset_rows = 0
    continued_episode_initial_hidden_state_rows = 0
    segment_initial_hidden_state_rows = 0
    batch_boundary_reset_ids: set[int] = set()

    def flush_segment(
        *,
        sequence_id: str,
        segment_index: int,
        chunk: list[dict[str, Any]],
    ) -> None:
        nonlocal segment_count, reset_rows, done_rows, truncated_rows
        nonlocal continued_episode_batch_reset_rows, segment_boundary_reset_rows, segment_initial_hidden_state_rows
        if not chunk:
            return
        segment_id = f"{sequence_id}:seg-{segment_index}"
        segment_count += 1
        segments_by_length[str(len(chunk))] += 1
        for position, raw_row in enumerate(chunk):
            out = dict(raw_row) if bool(copy_rows) else raw_row
            metadata = dict(_mapping(out.get("metadata")))
            episode_step = _current_policy_decision_index(out)
            runtime_recurrent_key = _first_present_text(
                out.get("runtimeRecurrentKey"),
                metadata.get("runtimeRecurrentKey"),
                out.get("runtimeSequenceId"),
                metadata.get("runtimeSequenceId"),
            )
            reset_hidden = (
                bool(out.get("resetHiddenState")) or bool(metadata.get("resetHiddenState"))
                if runtime_recurrent_key
                else position == 0
            )
            initial_hidden = (
                _current_policy_float_vector(
                    out,
                    "segmentInitialRecurrentHiddenState",
                    "runtimeRecurrentInitialHiddenState",
                )
                if runtime_recurrent_key and position == 0 and not reset_hidden
                else []
            )
            if initial_hidden:
                out["segmentInitialRecurrentHiddenState"] = initial_hidden
                metadata["segmentInitialRecurrentHiddenState"] = initial_hidden
                out["segmentInitialHiddenStateSource"] = "runtimeRecurrentInitialHiddenState"
                metadata["segmentInitialHiddenStateSource"] = "runtimeRecurrentInitialHiddenState"
                segment_initial_hidden_state_rows += 1
            forced_segment_reset = bool(runtime_recurrent_key and position == 0 and not reset_hidden and not initial_hidden)
            if forced_segment_reset:
                reset_hidden = True
                out["segmentBoundaryResetApplied"] = True
                metadata["segmentBoundaryResetApplied"] = True
                segment_boundary_reset_rows += 1
                if id(raw_row) in batch_boundary_reset_ids:
                    out["batchBoundaryResetApplied"] = True
                    metadata["batchBoundaryResetApplied"] = True
                    continued_episode_batch_reset_rows += 1
            updates = {
                "sequenceId": sequence_id,
                "episodeId": _first_present_text(out.get("episodeId"), metadata.get("episodeId"), out.get("taskId"), metadata.get("taskId")),
                "episodeStepIndex": int(episode_step),
                "segmentId": segment_id,
                "segmentIndex": int(segment_index),
                "positionInSegment": int(position),
                "segmentStart": position == 0,
                "segmentEnd": position == len(chunk) - 1,
                "resetHiddenState": bool(reset_hidden),
                "lossMask": bool(out.get("lossMask", metadata.get("lossMask", True))),
            }
            out.update(updates)
            metadata.update(updates)
            out["metadata"] = metadata
            annotated.append(out)
            reset_rows += int(bool(reset_hidden))
            done_rows += int(_current_policy_done(out))
            truncated_rows += int(_current_policy_truncated(out))

    for episode_key, group_rows in sorted(groups.items(), key=lambda item: item[0]):
        ordered = sorted(group_rows, key=_current_policy_decision_index)
        sequence_id = _current_policy_sequence_id(ordered[0], episode_key) if ordered else ""
        if ordered:
            first_row = ordered[0]
            first_metadata = _mapping(first_row.get("metadata"))
            first_runtime_key = _first_present_text(
                first_row.get("runtimeRecurrentKey"),
                first_metadata.get("runtimeRecurrentKey"),
                first_row.get("runtimeSequenceId"),
                first_metadata.get("runtimeSequenceId"),
            )
            first_step = _current_policy_decision_index(first_row)
            first_reset = bool(first_row.get("resetHiddenState")) or bool(first_metadata.get("resetHiddenState"))
            continued_group = bool(first_runtime_key and first_step > 0)
            if continued_group:
                continued_episode_first_rows += 1
                continued_episode_rows += len(ordered)
                if not first_reset:
                    continued_episode_first_rows_reset_hidden_false += 1
                    first_initial_hidden = _current_policy_float_vector(
                        first_row,
                        "segmentInitialRecurrentHiddenState",
                        "runtimeRecurrentInitialHiddenState",
                    )
                    if first_initial_hidden:
                        continued_episode_initial_hidden_state_rows += 1
                    else:
                        continued_episode_missing_initial_hidden_state_rows += 1
                        batch_boundary_reset_ids.add(id(first_row))
        chunk: list[dict[str, Any]] = []
        segment_index = 0
        for row in ordered:
            chunk.append(row)
            if len(chunk) >= bounded_chunk or _current_policy_done(row) or _current_policy_truncated(row):
                flush_segment(sequence_id=sequence_id, segment_index=segment_index, chunk=chunk)
                segment_index += 1
                chunk = []
        flush_segment(sequence_id=sequence_id, segment_index=segment_index, chunk=chunk)

    return annotated, {
        "kind": "current_policy_sequence_batch_v1",
        "chunkLength": int(bounded_chunk),
        "rows": int(len(annotated)),
        "episodes": int(len(groups)),
        "segments": int(segment_count),
        "segmentsByLength": dict(sorted(segments_by_length.items())),
        "resetRows": int(reset_rows),
        "doneRows": int(done_rows),
        "truncatedRows": int(truncated_rows),
        "continuedEpisodeRows": int(continued_episode_rows),
        "continuedEpisodeFirstRows": int(continued_episode_first_rows),
        "continuedEpisodeFirstRowsResetHiddenFalse": int(continued_episode_first_rows_reset_hidden_false),
        "continuedEpisodeInitialHiddenStateRows": int(continued_episode_initial_hidden_state_rows),
        "continuedEpisodeBatchResetRows": int(continued_episode_batch_reset_rows),
        "continuedEpisodeMissingInitialHiddenStateRows": int(
            max(0, continued_episode_missing_initial_hidden_state_rows - continued_episode_batch_reset_rows)
        ),
        "segmentBoundaryResetRows": int(segment_boundary_reset_rows),
        "segmentInitialHiddenStateRows": int(segment_initial_hidden_state_rows),
        "shuffleUnit": "segment",
        "singleStepShuffle": False,
    }


def _current_policy_sequence_id(row: Mapping[str, Any], episode_key: tuple[str, str, str, str]) -> str:
    metadata = _mapping(row.get("metadata"))
    explicit = _first_present_text(row.get("sequenceId"), metadata.get("sequenceId"))
    if explicit:
        return explicit
    run_id, task_id, episode_index, actor_side = episode_key
    parts = [part for part in (run_id, task_id, episode_index, actor_side) if part]
    return ":".join(parts)


def _current_policy_bootstrap_state_value(row: Mapping[str, Any]) -> float | None:
    label = _mapping(row.get("trajectoryPolicyLabel"))
    metadata = _mapping(row.get("metadata"))
    return _finite_float_or_none(
        label.get(
            "bootstrapStateValue",
            label.get(
                "truncatedBootstrapStateValue",
                row.get(
                    "bootstrapStateValue",
                    metadata.get(
                        "bootstrapStateValue",
                        metadata.get("truncatedBootstrapStateValue"),
                    ),
                ),
            ),
        )
    )


def _current_policy_old_state_value(row: Mapping[str, Any]) -> float | None:
    label = _mapping(row.get("trajectoryPolicyLabel"))
    metadata = _mapping(row.get("metadata"))
    return _finite_float_or_none(
        label.get(
            "oldPolicyStateValue",
            metadata.get("oldPolicyStateValue", metadata.get("actorStateValue")),
        )
    )


def _apply_current_policy_episode_lambda_returns(
    rows: list[dict[str, Any]],
    *,
    gae_lambda: float = CURRENT_POLICY_TRAJECTORY_GAE_LAMBDA,
    actor_advantage_mode: str = "gae",
    local_step_reward_weight: float = 0.0,
    use_old_policy_values: bool = True,
    copy_rows: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bounded_lambda = min(1.0, max(0.0, float(gae_lambda)))
    gamma = float(CURRENT_POLICY_TRAJECTORY_GAMMA)
    bounded_local_step_reward_weight = max(0.0, float(local_step_reward_weight))
    resolved_actor_advantage_mode = str(actor_advantage_mode or "gae").strip().lower()
    if resolved_actor_advantage_mode not in {
        "gae",
        "gae_upgo",
        "mc_return",
        "mc_return_decay",
        "mc_sign_preserving_gae",
        "local_step_reward",
        "learner_current_value_gae",
        "learner_vtrace",
    }:
        raise ValueError(f"unknown current-policy actor_advantage_mode: {actor_advantage_mode!r}")
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_current_policy_episode_key(row), []).append(row)
    adjusted_rows: list[dict[str, Any]] = []
    adjusted = 0
    gae_rows = 0
    fallback_rows = 0
    max_steps_from_terminal = 0
    explicit_step_reward_rows = 0
    raw_step_reward_nonzero_rows = 0
    terminal_step_reward_rows = 0
    nonterminal_step_reward_rows = 0
    nonterminal_nonzero_step_reward_rows = 0
    local_step_reward_rows = 0
    local_step_reward_nonzero_rows = 0
    local_step_reward_applied_rows = 0
    truncated_groups = 0
    truncated_bootstrap_groups = 0
    missing_truncated_bootstrap_groups = 0
    mc_advantage_sign_comparable_rows = 0
    mc_advantage_sign_aligned_rows = 0
    mc_advantage_sign_mismatched_rows = 0
    positive_mc_return_negative_advantage_rows = 0
    negative_mc_return_positive_advantage_rows = 0
    local_step_reward_gae_sign_comparable_rows = 0
    local_step_reward_gae_sign_aligned_rows = 0
    local_step_reward_gae_sign_mismatched_rows = 0
    positive_local_step_reward_negative_gae_rows = 0
    negative_local_step_reward_positive_gae_rows = 0
    local_step_reward_gae_by_decision_kind: dict[str, dict[str, int]] = {}
    local_step_reward_gae_by_selected_action_kind: dict[str, dict[str, int]] = {}
    local_step_reward_unshaped_gae_sign_comparable_rows = 0
    local_step_reward_unshaped_gae_sign_aligned_rows = 0
    local_step_reward_unshaped_gae_sign_mismatched_rows = 0
    positive_local_step_reward_negative_unshaped_gae_rows = 0
    negative_local_step_reward_positive_unshaped_gae_rows = 0
    local_step_reward_unshaped_gae_by_decision_kind: dict[str, dict[str, int]] = {}
    local_step_reward_unshaped_gae_by_selected_action_kind: dict[str, dict[str, int]] = {}
    actor_advantage_mc_sign_comparable_rows = 0
    actor_advantage_mc_sign_aligned_rows = 0
    actor_advantage_mc_sign_mismatched_rows = 0
    old_policy_value_rows = 0
    old_policy_value_sum = 0.0
    mc_return_for_old_value_sum = 0.0
    old_policy_value_minus_mc_return_sum = 0.0
    old_policy_value_abs_error_sum = 0.0
    old_policy_value_mc_sign_comparable_rows = 0
    old_policy_value_mc_sign_aligned_rows = 0
    old_policy_value_mc_sign_mismatched_rows = 0
    positive_mc_return_negative_old_value_rows = 0
    negative_mc_return_positive_old_value_rows = 0

    def sign(value: float) -> int:
        if float(value) > 0.0:
            return 1
        if float(value) < 0.0:
            return -1
        return 0

    def bump_local_gae_bucket(
        target: dict[str, dict[str, int]],
        key: str,
        *,
        aligned: bool,
        local_sign: int,
        gae_sign: int,
    ) -> None:
        entry = target.setdefault(
            str(key or "unknown"),
            {
                "comparableRows": 0,
                "alignedRows": 0,
                "mismatchedRows": 0,
                "positiveLocalNegativeGaeRows": 0,
                "negativeLocalPositiveGaeRows": 0,
            },
        )
        entry["comparableRows"] += 1
        if bool(aligned):
            entry["alignedRows"] += 1
        else:
            entry["mismatchedRows"] += 1
            if int(local_sign) > 0 and int(gae_sign) < 0:
                entry["positiveLocalNegativeGaeRows"] += 1
            if int(local_sign) < 0 and int(gae_sign) > 0:
                entry["negativeLocalPositiveGaeRows"] += 1

    def selected_action_kind(row: Mapping[str, Any]) -> str:
        label = _mapping(row.get("trajectoryPolicyLabel"))
        selected_slot = row.get(
            "actorActionSlot",
            row.get("selectedActionSlot", label.get("selectedSlot", 0)),
        )
        try:
            slot = int(selected_slot or 0)
        except (TypeError, ValueError):
            slot = 0
        actions = row.get("actions")
        if isinstance(actions, list | tuple) and 0 <= slot < len(actions):
            action = actions[slot]
            if isinstance(action, Mapping):
                kind = str(action.get("kind") or "").strip()
                if kind:
                    return kind
        signature = _selected_action_signature(row, slot)
        return signature.split(":", 1)[-1] if ":" in signature else signature

    def finalize_local_gae_buckets(source: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for key, raw in sorted(
            source.items(),
            key=lambda item: (-int(item[1].get("comparableRows", 0)), str(item[0])),
        ):
            comparable = int(raw.get("comparableRows", 0))
            aligned = int(raw.get("alignedRows", 0))
            rows.append(
                {
                    "key": str(key),
                    "comparableRows": comparable,
                    "alignedRows": aligned,
                    "mismatchedRows": int(raw.get("mismatchedRows", 0)),
                    "agreementRate": (float(aligned) / float(comparable) if comparable else None),
                    "positiveLocalNegativeGaeRows": int(raw.get("positiveLocalNegativeGaeRows", 0)),
                    "negativeLocalPositiveGaeRows": int(raw.get("negativeLocalPositiveGaeRows", 0)),
                }
            )
        return {
            "rows": rows,
            "worstRows": sorted(
                rows,
                key=lambda row: (float(row.get("agreementRate") or 0.0), -int(row.get("comparableRows") or 0)),
            )[:10],
        }

    for group_rows in groups.values():
        ordered = sorted(group_rows, key=_current_policy_decision_index)
        last_index = len(ordered) - 1
        old_values = (
            [_current_policy_old_state_value(row) for row in ordered]
            if bool(use_old_policy_values)
            else [None for _row in ordered]
        )
        use_gae = all(value is not None for value in old_values)
        gae_advantages = [0.0 for _row in ordered]
        unshaped_gae_advantages = [0.0 for _row in ordered]
        gae_targets = [0.0 for _row in ordered]
        upgo_returns = [0.0 for _row in ordered]
        explicit_step_rewards = [_current_policy_step_reward(row) for row in ordered]
        local_step_rewards = [_current_policy_local_step_reward(row) for row in ordered]
        has_explicit_step_rewards = any(value is not None for value in explicit_step_rewards)
        explicit_step_reward_rows += sum(1 for value in explicit_step_rewards if value is not None)
        local_step_reward_rows += sum(1 for value in local_step_rewards if value is not None)
        local_step_reward_nonzero_rows += sum(
            1 for value in local_step_rewards if value is not None and abs(float(value)) > 1.0e-12
        )
        final_return = _current_policy_label_return(ordered[-1]) if ordered else 0.0
        raw_step_rewards = [
            float(value)
            if value is not None
            else float(final_return)
            if index == last_index
            else 0.0
            for index, value in enumerate(explicit_step_rewards)
        ]
        raw_step_reward_nonzero_rows += sum(1 for value in raw_step_rewards if abs(float(value)) > 1.0e-12)
        step_rewards = []
        for index, value in enumerate(raw_step_rewards):
            shaped_value = float(value)
            local_value = local_step_rewards[index]
            if local_value is not None and bounded_local_step_reward_weight > 0.0:
                shaped_value += bounded_local_step_reward_weight * float(local_value)
                if abs(float(local_value)) > 1.0e-12:
                    local_step_reward_applied_rows += 1
            step_rewards.append(float(shaped_value))
            if not _current_policy_done(ordered[index]):
                nonterminal_step_reward_rows += 1
                if abs(float(value)) > 1.0e-12:
                    nonterminal_nonzero_step_reward_rows += 1
            elif abs(float(value)) > 1.0e-12:
                terminal_step_reward_rows += 1
        last_row = ordered[-1] if ordered else {}
        last_truncated = bool(_current_policy_truncated(last_row) and not _current_policy_done(last_row))
        bootstrap_value = _current_policy_bootstrap_state_value(last_row) if last_truncated else None
        if last_truncated:
            truncated_groups += 1
            if bootstrap_value is None:
                missing_truncated_bootstrap_groups += 1
            else:
                truncated_bootstrap_groups += 1
        if use_gae:
            running_gae = 0.0
            running_unshaped_gae = 0.0
            running_upgo_return = float(bootstrap_value or 0.0) if last_truncated else 0.0
            next_q = float(bootstrap_value or 0.0) if last_truncated else 0.0
            for index in range(last_index, -1, -1):
                value = float(old_values[index] or 0.0)
                if index == last_index:
                    next_value = float(bootstrap_value or 0.0) if last_truncated else 0.0
                else:
                    next_value = float(old_values[index + 1] or 0.0)
                step_reward = float(step_rewards[index])
                delta = step_reward + gamma * next_value - value
                running_gae = delta + gamma * bounded_lambda * running_gae
                gae_advantages[index] = float(running_gae)
                gae_targets[index] = float(running_gae + value)
                raw_step_reward = float(raw_step_rewards[index])
                unshaped_delta = raw_step_reward + gamma * next_value - value
                running_unshaped_gae = unshaped_delta + gamma * bounded_lambda * running_unshaped_gae
                unshaped_gae_advantages[index] = float(running_unshaped_gae)
                running_upgo_return = step_reward + gamma * (
                    running_upgo_return if next_q >= next_value else next_value
                )
                next_q = step_reward + gamma * next_value
                upgo_returns[index] = float(running_upgo_return)
        fallback_returns = [0.0 for _row in ordered]
        if has_explicit_step_rewards:
            running_return = float(bootstrap_value or 0.0) if last_truncated else 0.0
            for index in range(last_index, -1, -1):
                running_return = float(step_rewards[index]) + gamma * running_return
                fallback_returns[index] = float(running_return)
        for index, row in enumerate(ordered):
            steps_from_terminal = max(0, last_index - index)
            max_steps_from_terminal = max(max_steps_from_terminal, steps_from_terminal)
            raw_return = _current_policy_label_return(row)
            lambda_return = (
                fallback_returns[index]
                if has_explicit_step_rewards
                else raw_return * (bounded_lambda ** steps_from_terminal)
            )
            return_value = gae_targets[index] if use_gae else lambda_return
            critic_advantage_value = gae_advantages[index] if use_gae else lambda_return
            unshaped_critic_advantage_value = unshaped_gae_advantages[index] if use_gae else lambda_return
            mc_return_value = fallback_returns[index] if has_explicit_step_rewards else lambda_return
            mc_sign = sign(float(mc_return_value))
            critic_advantage_sign = sign(float(critic_advantage_value))
            unshaped_critic_advantage_sign = sign(float(unshaped_critic_advantage_value))
            local_step_reward_sign = (
                sign(float(local_step_rewards[index]))
                if local_step_rewards[index] is not None
                else 0
            )
            old_value = old_values[index] if index < len(old_values) else None
            if old_value is not None:
                old_value_float = float(old_value)
                old_policy_value_rows += 1
                old_policy_value_sum += old_value_float
                mc_return_for_old_value_sum += float(mc_return_value)
                old_policy_value_minus_mc_return_sum += old_value_float - float(mc_return_value)
                old_policy_value_abs_error_sum += abs(old_value_float - float(mc_return_value))
                old_value_sign = sign(old_value_float)
                if mc_sign and old_value_sign:
                    old_policy_value_mc_sign_comparable_rows += 1
                    if mc_sign == old_value_sign:
                        old_policy_value_mc_sign_aligned_rows += 1
                    else:
                        old_policy_value_mc_sign_mismatched_rows += 1
                        if mc_sign > 0 and old_value_sign < 0:
                            positive_mc_return_negative_old_value_rows += 1
                        if mc_sign < 0 and old_value_sign > 0:
                            negative_mc_return_positive_old_value_rows += 1
            if resolved_actor_advantage_mode == "gae_upgo" and use_gae and old_value is not None:
                advantage_value = float(critic_advantage_value) + (
                    float(upgo_returns[index]) - float(old_value)
                )
            elif resolved_actor_advantage_mode == "mc_return":
                advantage_value = float(mc_return_value)
            elif resolved_actor_advantage_mode == "mc_return_decay":
                advantage_value = float(mc_return_value) * float(bounded_lambda ** steps_from_terminal)
            elif resolved_actor_advantage_mode == "mc_sign_preserving_gae" and mc_sign:
                advantage_value = float(abs(float(critic_advantage_value)) * float(mc_sign))
            elif resolved_actor_advantage_mode == "local_step_reward":
                advantage_value = float(local_step_rewards[index] or 0.0)
            else:
                advantage_value = float(critic_advantage_value)
            actor_advantage_sign = sign(float(advantage_value))
            if mc_sign and critic_advantage_sign:
                mc_advantage_sign_comparable_rows += 1
                if mc_sign == critic_advantage_sign:
                    mc_advantage_sign_aligned_rows += 1
                else:
                    mc_advantage_sign_mismatched_rows += 1
                    if mc_sign > 0 and critic_advantage_sign < 0:
                        positive_mc_return_negative_advantage_rows += 1
                    if mc_sign < 0 and critic_advantage_sign > 0:
                        negative_mc_return_positive_advantage_rows += 1
            if use_gae and local_step_reward_sign and critic_advantage_sign:
                local_step_reward_gae_sign_comparable_rows += 1
                local_gae_aligned = local_step_reward_sign == critic_advantage_sign
                if local_gae_aligned:
                    local_step_reward_gae_sign_aligned_rows += 1
                else:
                    local_step_reward_gae_sign_mismatched_rows += 1
                    if local_step_reward_sign > 0 and critic_advantage_sign < 0:
                        positive_local_step_reward_negative_gae_rows += 1
                    if local_step_reward_sign < 0 and critic_advantage_sign > 0:
                        negative_local_step_reward_positive_gae_rows += 1
                bump_local_gae_bucket(
                    local_step_reward_gae_by_decision_kind,
                    str(row.get("decisionKind") or "unknown"),
                    aligned=bool(local_gae_aligned),
                    local_sign=int(local_step_reward_sign),
                    gae_sign=int(critic_advantage_sign),
                )
                bump_local_gae_bucket(
                    local_step_reward_gae_by_selected_action_kind,
                    selected_action_kind(row),
                    aligned=bool(local_gae_aligned),
                    local_sign=int(local_step_reward_sign),
                    gae_sign=int(critic_advantage_sign),
                )
            if use_gae and local_step_reward_sign and unshaped_critic_advantage_sign:
                local_step_reward_unshaped_gae_sign_comparable_rows += 1
                local_unshaped_gae_aligned = local_step_reward_sign == unshaped_critic_advantage_sign
                if local_unshaped_gae_aligned:
                    local_step_reward_unshaped_gae_sign_aligned_rows += 1
                else:
                    local_step_reward_unshaped_gae_sign_mismatched_rows += 1
                    if local_step_reward_sign > 0 and unshaped_critic_advantage_sign < 0:
                        positive_local_step_reward_negative_unshaped_gae_rows += 1
                    if local_step_reward_sign < 0 and unshaped_critic_advantage_sign > 0:
                        negative_local_step_reward_positive_unshaped_gae_rows += 1
                bump_local_gae_bucket(
                    local_step_reward_unshaped_gae_by_decision_kind,
                    str(row.get("decisionKind") or "unknown"),
                    aligned=bool(local_unshaped_gae_aligned),
                    local_sign=int(local_step_reward_sign),
                    gae_sign=int(unshaped_critic_advantage_sign),
                )
                bump_local_gae_bucket(
                    local_step_reward_unshaped_gae_by_selected_action_kind,
                    selected_action_kind(row),
                    aligned=bool(local_unshaped_gae_aligned),
                    local_sign=int(local_step_reward_sign),
                    gae_sign=int(unshaped_critic_advantage_sign),
                )
            if mc_sign and actor_advantage_sign:
                actor_advantage_mc_sign_comparable_rows += 1
                if mc_sign == actor_advantage_sign:
                    actor_advantage_mc_sign_aligned_rows += 1
                else:
                    actor_advantage_mc_sign_mismatched_rows += 1
            out = dict(row) if bool(copy_rows) else row
            label = dict(_mapping(out.get("trajectoryPolicyLabel")))
            critic_advantage_mode = (
                "episode_gae_old_policy_value"
                if use_gae
                else "episode_lambda_return_no_baseline"
            )
            label["rawEpisodeReturnValue"] = float(raw_return)
            label["rawStepReward"] = float(raw_step_rewards[index])
            label["stepReward"] = float(step_rewards[index])
            if local_step_rewards[index] is not None:
                label["localStepReward"] = float(local_step_rewards[index] or 0.0)
            label["localStepRewardWeight"] = float(bounded_local_step_reward_weight)
            label["mcReturnValue"] = float(mc_return_value)
            label["returnValue"] = float(return_value)
            label["advantage"] = float(advantage_value)
            label["criticAdvantage"] = float(critic_advantage_value)
            label["unshapedCriticAdvantage"] = float(unshaped_critic_advantage_value)
            label["criticAdvantageMode"] = critic_advantage_mode
            label["actorAdvantageMode"] = str(resolved_actor_advantage_mode)
            label["advantageMode"] = (
                critic_advantage_mode
                if resolved_actor_advantage_mode == "gae"
                else f"episode_{resolved_actor_advantage_mode}_actor_advantage"
            )
            label["gaeLambda"] = float(bounded_lambda)
            label["gamma"] = float(gamma)
            label["stepsFromTerminalDecision"] = int(steps_from_terminal)
            label["done"] = bool(_current_policy_done(row))
            label["truncated"] = bool(_current_policy_truncated(row))
            if index == last_index and bootstrap_value is not None:
                label["bootstrapStateValue"] = float(bootstrap_value)
            out["trajectoryPolicyLabel"] = label
            out["trajectoryReturn"] = float(return_value)
            out["trajectoryAdvantage"] = float(advantage_value)
            adjusted_rows.append(out)
            adjusted += 1
            if use_gae:
                gae_rows += 1
            else:
                fallback_rows += 1
    advantage_mode = (
        "episode_gae_old_policy_value"
        if gae_rows and not fallback_rows
        else "episode_lambda_return_no_baseline"
        if fallback_rows and not gae_rows
        else "mixed_episode_gae_or_lambda_return"
    )
    if local_step_reward_applied_rows > 0:
        actor_gae_reward_source = "explicit_step_reward_plus_local_shaping"
    elif explicit_step_reward_rows > 0 and nonterminal_nonzero_step_reward_rows > 0:
        actor_gae_reward_source = "explicit_mixed_step_reward"
    elif explicit_step_reward_rows > 0:
        actor_gae_reward_source = "explicit_terminal_sparse_step_reward"
    else:
        actor_gae_reward_source = "fallback_terminal_return"
    return adjusted_rows, {
        "kind": "current_policy_episode_lambda_return_v1",
        "inputRows": int(len(rows)),
        "adjustedRows": int(adjusted),
        "episodeGroups": int(len(groups)),
        "gaeLambda": float(bounded_lambda),
        "gamma": float(gamma),
        "localStepRewardWeight": float(bounded_local_step_reward_weight),
        "oldPolicyValueTrusted": bool(use_old_policy_values),
        "advantageMode": advantage_mode,
        "criticAdvantageMode": advantage_mode,
        "actorAdvantageMode": str(resolved_actor_advantage_mode),
        "gaeRows": int(gae_rows),
        "fallbackLambdaRows": int(fallback_rows),
        "maxStepsFromTerminalDecision": int(max_steps_from_terminal),
        "explicitStepRewardRows": int(explicit_step_reward_rows),
        "rawStepRewardNonZeroRows": int(raw_step_reward_nonzero_rows),
        "terminalStepRewardRows": int(terminal_step_reward_rows),
        "nonTerminalStepRewardRows": int(nonterminal_step_reward_rows),
        "nonTerminalNonZeroStepRewardRows": int(nonterminal_nonzero_step_reward_rows),
        "localStepRewardRows": int(local_step_reward_rows),
        "localStepRewardNonZeroRows": int(local_step_reward_nonzero_rows),
        "localStepRewardAppliedRows": int(local_step_reward_applied_rows),
        "actorGaeRewardSource": str(actor_gae_reward_source),
        "truncatedGroups": int(truncated_groups),
        "truncatedBootstrapGroups": int(truncated_bootstrap_groups),
        "missingTruncatedBootstrapGroups": int(missing_truncated_bootstrap_groups),
        "mcAdvantageSignComparableRows": int(mc_advantage_sign_comparable_rows),
        "mcAdvantageSignAlignedRows": int(mc_advantage_sign_aligned_rows),
        "mcAdvantageSignMismatchedRows": int(mc_advantage_sign_mismatched_rows),
        "mcAdvantageSignAgreementRate": (
            float(mc_advantage_sign_aligned_rows) / float(mc_advantage_sign_comparable_rows)
            if mc_advantage_sign_comparable_rows
            else None
        ),
        "positiveMcReturnNegativeAdvantageRows": int(positive_mc_return_negative_advantage_rows),
        "negativeMcReturnPositiveAdvantageRows": int(negative_mc_return_positive_advantage_rows),
        "localStepRewardGaeSignComparableRows": int(local_step_reward_gae_sign_comparable_rows),
        "localStepRewardGaeSignAlignedRows": int(local_step_reward_gae_sign_aligned_rows),
        "localStepRewardGaeSignMismatchedRows": int(local_step_reward_gae_sign_mismatched_rows),
        "localStepRewardGaeSignAgreementRate": (
            float(local_step_reward_gae_sign_aligned_rows) / float(local_step_reward_gae_sign_comparable_rows)
            if local_step_reward_gae_sign_comparable_rows
            else None
        ),
        "positiveLocalStepRewardNegativeGaeRows": int(positive_local_step_reward_negative_gae_rows),
        "negativeLocalStepRewardPositiveGaeRows": int(negative_local_step_reward_positive_gae_rows),
        "localStepRewardGaeSignReference": "criticAdvantageAfterLocalStepRewardWeight",
        "localStepRewardGaeSignByDecisionKind": finalize_local_gae_buckets(local_step_reward_gae_by_decision_kind),
        "localStepRewardGaeSignBySelectedActionKind": finalize_local_gae_buckets(
            local_step_reward_gae_by_selected_action_kind
        ),
        "localStepRewardUnshapedGaeSignComparableRows": int(local_step_reward_unshaped_gae_sign_comparable_rows),
        "localStepRewardUnshapedGaeSignAlignedRows": int(local_step_reward_unshaped_gae_sign_aligned_rows),
        "localStepRewardUnshapedGaeSignMismatchedRows": int(local_step_reward_unshaped_gae_sign_mismatched_rows),
        "localStepRewardUnshapedGaeSignAgreementRate": (
            float(local_step_reward_unshaped_gae_sign_aligned_rows)
            / float(local_step_reward_unshaped_gae_sign_comparable_rows)
            if local_step_reward_unshaped_gae_sign_comparable_rows
            else None
        ),
        "positiveLocalStepRewardNegativeUnshapedGaeRows": int(
            positive_local_step_reward_negative_unshaped_gae_rows
        ),
        "negativeLocalStepRewardPositiveUnshapedGaeRows": int(
            negative_local_step_reward_positive_unshaped_gae_rows
        ),
        "localStepRewardUnshapedGaeSignReference": "criticAdvantageBeforeLocalStepRewardWeight",
        "localStepRewardUnshapedGaeSignByDecisionKind": finalize_local_gae_buckets(
            local_step_reward_unshaped_gae_by_decision_kind
        ),
        "localStepRewardUnshapedGaeSignBySelectedActionKind": finalize_local_gae_buckets(
            local_step_reward_unshaped_gae_by_selected_action_kind
        ),
        "oldPolicyValueRows": int(old_policy_value_rows),
        "oldPolicyValueMean": (
            float(old_policy_value_sum) / float(old_policy_value_rows)
            if old_policy_value_rows
            else None
        ),
        "mcReturnForOldValueMean": (
            float(mc_return_for_old_value_sum) / float(old_policy_value_rows)
            if old_policy_value_rows
            else None
        ),
        "oldPolicyValueMinusMcReturnMean": (
            float(old_policy_value_minus_mc_return_sum) / float(old_policy_value_rows)
            if old_policy_value_rows
            else None
        ),
        "oldPolicyValueAbsErrorMean": (
            float(old_policy_value_abs_error_sum) / float(old_policy_value_rows)
            if old_policy_value_rows
            else None
        ),
        "oldPolicyValueMcSignComparableRows": int(old_policy_value_mc_sign_comparable_rows),
        "oldPolicyValueMcSignAlignedRows": int(old_policy_value_mc_sign_aligned_rows),
        "oldPolicyValueMcSignMismatchedRows": int(old_policy_value_mc_sign_mismatched_rows),
        "oldPolicyValueMcSignAgreementRate": (
            float(old_policy_value_mc_sign_aligned_rows) / float(old_policy_value_mc_sign_comparable_rows)
            if old_policy_value_mc_sign_comparable_rows
            else None
        ),
        "positiveMcReturnNegativeOldValueRows": int(positive_mc_return_negative_old_value_rows),
        "negativeMcReturnPositiveOldValueRows": int(negative_mc_return_positive_old_value_rows),
        "actorAdvantageMcSignComparableRows": int(actor_advantage_mc_sign_comparable_rows),
        "actorAdvantageMcSignAlignedRows": int(actor_advantage_mc_sign_aligned_rows),
        "actorAdvantageMcSignMismatchedRows": int(actor_advantage_mc_sign_mismatched_rows),
        "actorAdvantageMcSignAgreementRate": (
            float(actor_advantage_mc_sign_aligned_rows) / float(actor_advantage_mc_sign_comparable_rows)
            if actor_advantage_mc_sign_comparable_rows
            else None
        ),
    }


def _current_policy_trajectory_passthrough_report(
    rows: list[dict[str, Any]],
    *,
    transform_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    transform = dict(transform_report or {})
    return {
        "kind": "current_policy_sampled_trajectory_passthrough_v1",
        "inputRows": int(len(rows)),
        "convertedRows": int(len(rows)),
        "source": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
        "advantageMode": str(transform.get("advantageMode") or "recorded_sampled_actor_trajectory"),
        "trajectoryTransform": transform or None,
    }


def _actor_selection_mode_from_row(row: Mapping[str, Any]) -> str:
    metadata = _mapping(row.get("metadata"))
    return str(row.get("actorSelectionMode") or metadata.get("actorSelectionMode") or "").strip()


def _actor_sampling_log_prob_from_row(row: Mapping[str, Any]) -> float | None:
    metadata = _mapping(row.get("metadata"))
    return _finite_float_or_none(
        row.get(
            "actorActionLogProb",
            row.get(
                "actorLogProb",
                metadata.get("actorActionLogProb", metadata.get("actorLogProb")),
            ),
        )
    )


def _trajectory_group_expected_action_value_eval(
    rows: list[Mapping[str, Any]],
    *,
    aux_scores_by_row_id: Mapping[int, list[Any]],
    runtime_base_scorer: Any,
    runtime_aux_score_weight: float,
    model: Any,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_cheap_runtime_contract_group_key(row), []).append(row)
    total = 0
    improved = 0
    delta_sum = 0.0
    delta_abs_sum = 0.0
    old_value_sum = 0.0
    new_value_sum = 0.0
    by_decision: dict[str, dict[str, Any]] = {}
    for group_key, group in grouped.items():
        representative = group[0]
        known_values = _trajectory_group_known_action_values(group)
        if len(known_values) < 2:
            continue
        legal_slots = _ygo_legal_slots(representative)
        candidate_slots = [slot for slot in legal_slots if slot in known_values]
        if len(candidate_slots) < 2:
            continue
        base_scores = row_runtime_total_scores(
            representative,
            require_explicit_mode=True,
            require_policy_provenance=True,
        ) or runtime_base_scorer.score_row(representative)
        if base_scores is None:
            continue
        aux_scores = aux_scores_by_row_id.get(id(representative))
        if aux_scores is None:
            aux_scores = model.score_row(representative)
        max_correction = (
            BOUNDED_RUNTIME_AUX_MAX_CORRECTION
            if is_bounded_runtime_aux_objective(getattr(model, "runtimeAuxTrainingObjective", None))
            else None
        )
        runtime_scores = [
            compose_runtime_aux_score(
                base_scores[slot] if 0 <= slot < len(base_scores) else None,
                aux_scores[slot] if 0 <= slot < len(aux_scores) else None,
                weight=float(runtime_aux_score_weight),
                max_correction=max_correction,
            )
            for slot in range(max(len(base_scores), len(aux_scores)))
        ]
        old_probs = _softmax_slot_probabilities(base_scores, candidate_slots)
        new_probs = _softmax_slot_probabilities(runtime_scores, candidate_slots)
        if set(old_probs) != set(candidate_slots) or set(new_probs) != set(candidate_slots):
            continue
        old_value = sum(float(old_probs[slot]) * float(known_values[slot]) for slot in candidate_slots)
        new_value = sum(float(new_probs[slot]) * float(known_values[slot]) for slot in candidate_slots)
        delta = float(new_value) - float(old_value)
        total += 1
        old_value_sum += float(old_value)
        new_value_sum += float(new_value)
        delta_sum += delta
        delta_abs_sum += abs(delta)
        if delta > 0.0:
            improved += 1
        decision = str(group_key[2] or representative.get("decisionKind") or "unknown")
        bucket = by_decision.setdefault(
            decision,
            {"groups": 0, "improved": 0, "deltaSum": 0.0, "deltaAbsSum": 0.0},
        )
        bucket["groups"] += 1
        bucket["deltaSum"] += delta
        bucket["deltaAbsSum"] += abs(delta)
        if delta > 0.0:
            bucket["improved"] += 1
    return {
        "groups": int(total),
        "improvedGroups": int(improved),
        "improvedRate": float(improved / total) if total else 0.0,
        "expectedActionValueDeltaMean": float(delta_sum / total) if total else 0.0,
        "expectedActionValueDeltaAbsMean": float(delta_abs_sum / total) if total else 0.0,
        "oldExpectedActionValueMean": float(old_value_sum / total) if total else 0.0,
        "newExpectedActionValueMean": float(new_value_sum / total) if total else 0.0,
        "byDecisionKind": {
            decision: {
                "groups": int(values["groups"]),
                "improvedGroups": int(values["improved"]),
                "improvedRate": (
                    float(values["improved"] / values["groups"])
                    if values["groups"]
                    else 0.0
                ),
                "expectedActionValueDeltaMean": (
                    float(values["deltaSum"] / values["groups"])
                    if values["groups"]
                    else 0.0
                ),
                "expectedActionValueDeltaAbsMean": (
                    float(values["deltaAbsSum"] / values["groups"])
                    if values["groups"]
                    else 0.0
                ),
            }
            for decision, values in sorted(by_decision.items())
        },
    }


def _trajectory_group_known_action_values(group: list[Mapping[str, Any]]) -> dict[int, float]:
    known_values: dict[int, float] = {}
    for row in group:
        label = _mapping(row.get("trajectoryPolicyLabel"))
        known = label.get("knownActionValuesBySlot")
        if isinstance(known, Mapping):
            for key, value in known.items():
                slot = _int_or_none(key)
                parsed = _float_or_none(value)
                if slot is not None and parsed is not None:
                    known_values[int(slot)] = float(parsed)
        elif isinstance(known, list | tuple):
            for slot, value in enumerate(known):
                parsed = _float_or_none(value)
                if parsed is not None:
                    known_values[int(slot)] = float(parsed)
        selected = _int_or_none(label.get("selectedSlot"))
        if selected is None:
            selected = _int_or_none(row.get("selectedActionSlot"))
        value = _float_or_none(label.get("sourceActionValue"))
        if value is None:
            value = _float_or_none(label.get("returnValue"))
        if value is None:
            value = _float_or_none(row.get("trajectoryReturn"))
        if selected is not None and value is not None:
            known_values[int(selected)] = float(value)
    return known_values


def _softmax_slot_probability(scores: list[Any], selected_slot: int, legal_slots: list[int]) -> float | None:
    finite_scores = []
    for slot in legal_slots:
        if slot < 0 or slot >= len(scores):
            continue
        value = _float_or_none(scores[slot])
        if value is None:
            continue
        finite_scores.append((int(slot), float(value)))
    if selected_slot not in {slot for slot, _score in finite_scores}:
        return None
    max_score = max(score for _slot, score in finite_scores)
    exp_scores = [(slot, math.exp(score - max_score)) for slot, score in finite_scores]
    denominator = sum(score for _slot, score in exp_scores)
    if denominator <= 0.0:
        return None
    selected_exp = next(score for slot, score in exp_scores if slot == selected_slot)
    return float(selected_exp / denominator)


def _softmax_slot_probabilities(scores: list[Any], legal_slots: list[int]) -> dict[int, float]:
    finite_scores: list[tuple[int, float]] = []
    for slot in legal_slots:
        if slot < 0 or slot >= len(scores):
            continue
        value = _float_or_none(scores[slot])
        if value is None:
            continue
        finite_scores.append((int(slot), float(value)))
    if not finite_scores:
        return {}
    max_score = max(score for _slot, score in finite_scores)
    exp_scores = [(slot, math.exp(score - max_score)) for slot, score in finite_scores]
    denominator = sum(score for _slot, score in exp_scores)
    if denominator <= 0.0:
        return {}
    return {slot: float(score / denominator) for slot, score in exp_scores}


def _trajectory_advantage_rows_from_full_legal_action_values(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    skipped: Counter[str] = Counter()
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if _ygo_trajectory_policy_label(row) is not None:
            continue
        contract_reason = _trajectory_action_value_conversion_rejection_reason(row)
        if contract_reason is not None:
            skipped[f"rowContract.{contract_reason}"] += 1
            continue
        grouped.setdefault(_state_group_key(row), []).append(row)

    converted: list[dict[str, Any]] = []
    converted_by_decision: Counter[str] = Counter()
    groups_converted = 0
    for group in grouped.values():
        representative = group[0]
        decision_kind = str(representative.get("decisionKind") or "unknown")
        legal_slots = sorted(set(_ygo_legal_slots(representative)))
        if len(legal_slots) < 2:
            skipped["belowMinLegalActions"] += 1
            continue
        identity_reasons = {
            str(reason)
            for row in group
            for reason in (action_value_group_identity_rejection_reason(row),)
            if reason is not None
        }
        if identity_reasons:
            skipped[f"identity.{sorted(identity_reasons)[0]}"] += 1
            continue
        known_values = _known_action_value_slots(group, legal_slots=set(legal_slots))
        if len(known_values) < 2:
            skipped["insufficientKnownActionValues"] += 1
            continue
        if not set(legal_slots).issubset(set(known_values)):
            skipped["partialFullLegalCoverage"] += 1
            continue
        if not value_spread_is_trainable(list(known_values.values())):
            skipped["flatActionValues"] += 1
            continue
        runtime_scores = row_runtime_total_scores(
            representative,
            require_explicit_mode=True,
            require_policy_provenance=True,
        )
        if runtime_scores is None:
            reason = row_runtime_total_rejection_reason(
                representative,
                require_explicit_mode=True,
                require_policy_provenance=True,
            )
            skipped[f"runtimeTotal.{reason or 'missing'}"] += 1
            continue
        trainable_slots = [
            slot
            for slot in legal_slots
            if slot in known_values and slot < len(runtime_scores) and _float_or_none(runtime_scores[slot]) is not None
        ]
        if set(trainable_slots) != set(legal_slots):
            skipped["partialRuntimeScoreCoverage"] += 1
            continue
        old_policy_probs = _softmax_slot_probabilities(runtime_scores, trainable_slots)
        if set(old_policy_probs) != set(trainable_slots):
            skipped["missingOldPolicyProbabilities"] += 1
            continue
        expected_action_value = sum(
            float(old_policy_probs[slot]) * float(known_values[slot])
            for slot in trainable_slots
        )
        row_by_slot = {
            slot: row
            for row in group
            for slot in [_row_action_slot(row)]
            if slot is not None
        }
        group_weight = sum(_ygo_row_training_weight(row) for row in group) / max(1, len(group))
        emitted_for_group = 0
        for slot in trainable_slots:
            action_value = float(known_values[slot])
            advantage = action_value - float(expected_action_value)
            source = row_by_slot.get(slot, representative)
            out = dict(representative)
            source_label = dict(source.get("label") if isinstance(source.get("label"), Mapping) else {})
            source_label.update({"actionSlot": int(slot), "actionValue": action_value})
            label = {
                "labelVersion": YGO_STYLE_TRAJECTORY_ADVANTAGE_RUNTIME_TRAINING_VERSION,
                "labelSource": "full_legal_action_value_expected_old_policy_advantage",
                "selectedSlot": int(slot),
                "returnValue": action_value,
                "advantage": float(advantage),
                "advantageMode": "action_value_minus_old_policy_expected_value",
                "oldPolicyActionProbability": float(old_policy_probs[slot]),
                "basePolicyActionProbability": float(old_policy_probs[slot]),
                "oldPolicyExpectedActionValue": float(expected_action_value),
                "basePolicyExpectedActionValue": float(expected_action_value),
                "sourceActionValue": action_value,
                "knownActionValuesBySlot": {
                    str(known_slot): float(known_value)
                    for known_slot, known_value in sorted(known_values.items())
                },
                "branchRolloutLabel": True,
            }
            metadata = dict(out.get("metadata") if isinstance(out.get("metadata"), Mapping) else {})
            metadata.update(
                {
                    "labelSource": "full_legal_action_value_expected_old_policy_advantage",
                    "trajectoryRowsFromActionValue": True,
                    "oldPolicyActionProbability": float(old_policy_probs[slot]),
                    "basePolicyActionProbability": float(old_policy_probs[slot]),
                    "oldPolicyExpectedActionValue": float(expected_action_value),
                    "basePolicyExpectedActionValue": float(expected_action_value),
                    "sourceActionValue": action_value,
                    "trainingWeight": float(group_weight) * float(old_policy_probs[slot]),
                    "trajectoryActionValueSourceSlot": int(slot),
                }
            )
            out.update(
                {
                    "trajectoryPolicyLabel": label,
                    "trajectoryReturn": action_value,
                    "trajectoryAdvantage": float(advantage),
                    "selectedActionSlot": int(slot),
                    "actionSlot": int(slot),
                    "label": source_label,
                    "metadata": metadata,
                    "trainingWeight": float(group_weight) * float(old_policy_probs[slot]),
                }
            )
            converted.append(out)
            converted_by_decision[decision_kind] += 1
            emitted_for_group += 1
        if emitted_for_group:
            groups_converted += 1

    return converted, {
        "kind": "full_legal_action_value_to_trajectory_advantage_v1",
        "inputRows": int(len(rows)),
        "candidateGroups": int(len(grouped)),
        "convertedGroups": int(groups_converted),
        "convertedRows": int(len(converted)),
        "convertedRowsByDecisionKind": {key: int(value) for key, value in sorted(converted_by_decision.items())},
        "skipped": {key: int(value) for key, value in sorted(skipped.items())},
        "advantageMode": "action_value_minus_old_policy_expected_value",
        "oldPolicyWeighting": "softmax(row_runtime_total)",
        "basePolicyPriorSource": "softmax(row_runtime_total)",
        "oldPolicyProbabilitySemantics": "base_runtime_score_prior_not_behavior_logprob",
    }


def _trajectory_action_value_conversion_rejection_reason(row: Mapping[str, Any]) -> str | None:
    if str(row.get("schema") or "") != "snapshot_branch_full_legal_action_value_rows_v1":
        return "not_snapshot_branch_full_legal_schema"
    if str(row.get("taskKind") or "") != "causal_full_legal_action_set_rollout_value":
        return "not_causal_full_legal_action_set_rollout_value"
    if str(row.get("labelKind") or "") != "action_value":
        return "not_action_value_label_kind"
    if str(row.get("teacherId") or "") not in FULL_LEGAL_ACTION_VALUE_TEACHER_IDS:
        return "unsupported_full_legal_action_value_teacher"
    if not bool(row.get("nonTie")):
        return "not_outcome_non_tie"
    metadata = _mapping(row.get("metadata"))
    if not bool(metadata.get("fullLegalActionSetGroup")):
        return "missing_full_legal_group_marker"
    label = _mapping(row.get("label"))
    if str(label.get("labelSource") or metadata.get("labelSource") or "") not in FULL_LEGAL_ACTION_VALUE_LABEL_SOURCES:
        return "unsupported_full_legal_action_value_label_source"
    if _row_action_slot(row) is None:
        return "missing_action_slot"
    if _row_action_value(row) is None:
        return "missing_action_value"
    if _row_is_tiebreak_only_action_value(row):
        return "tiebreak_only"
    if not _row_has_action_value_target_contract(row):
        return "missing_action_value_contract"
    return None


def _direct_policy_known_action_value_eval(
    model: Any,
    rows: list[Mapping[str, Any]],
    *,
    runtime_base_scorer: Any | None = None,
    runtime_aux_score_weight: float | None = None,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_state_group_key(row), []).append(row)
    total = 0
    correct = 0
    row_runtime_base_groups = 0
    scorer_runtime_base_groups = 0
    by_decision: dict[str, dict[str, int]] = {}
    for (_run_id, _state_key, decision, _action_set_identity), group in grouped.items():
        representative = group[0]
        known_values = _known_action_value_slots(group, legal_slots=set(_ygo_legal_slots(representative)))
        if len(known_values) < 2:
            continue
        scores, runtime_base_source = _eval_scores(
            model,
            representative,
            runtime_base_scorer=runtime_base_scorer,
            runtime_aux_score_weight=runtime_aux_score_weight,
        )
        candidate_slots = [slot for slot in known_values if slot < len(scores) and scores[slot] is not None]
        best_slots = _best_action_value_slots(known_values, candidate_slots=candidate_slots)
        if not best_slots:
            continue
        if runtime_base_source == "row_runtime_total":
            row_runtime_base_groups += 1
        elif runtime_base_source == "scorer_runtime_base":
            scorer_runtime_base_groups += 1
        selected = runtime_top_slot(scores, candidate_slots)
        if selected is None:
            continue
        total += 1
        if selected in best_slots:
            correct += 1
        bucket = by_decision.setdefault(str(decision), {"total": 0, "correct": 0})
        bucket["total"] += 1
        if selected in best_slots:
            bucket["correct"] += 1
    return {
        "total": int(total),
        "correct": int(correct),
        "top1Accuracy": float(correct / total) if total else 0.0,
        "runtimeBaseScoreSource": _runtime_base_score_source_summary(
            row_runtime_base_groups=row_runtime_base_groups,
            scorer_runtime_base_groups=scorer_runtime_base_groups,
        ),
        "runtimeBaseScoreSourceGroups": {
            "rowRuntimeTotal": int(row_runtime_base_groups),
            "scorerRuntimeBase": int(scorer_runtime_base_groups),
        },
        "byDecisionKind": {
            decision: {
                "total": values["total"],
                "correct": values["correct"],
                "top1Accuracy": float(values["correct"] / values["total"]) if values["total"] else 0.0,
            }
            for decision, values in sorted(by_decision.items())
        },
    }


def _best_action_value_slots(
    known_values: Mapping[int, float],
    *,
    candidate_slots: list[int],
    epsilon: float = DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
) -> set[int]:
    return best_value_slots(known_values, candidate_slots=candidate_slots, epsilon=epsilon)


def _action_value_listwise_eval(
    model: Any,
    rows: list[Mapping[str, Any]],
    *,
    runtime_base_scorer: Any | None = None,
    runtime_aux_score_weight: float | None = None,
) -> dict[str, Any]:
    known_slot_eval = _direct_policy_known_action_value_eval(
        model,
        rows,
        runtime_base_scorer=runtime_base_scorer,
        runtime_aux_score_weight=runtime_aux_score_weight,
    )
    return {
        "total": known_slot_eval["total"],
        "correct": known_slot_eval["correct"],
        "top1Accuracy": known_slot_eval["top1Accuracy"],
        "knownSlotTotal": known_slot_eval["total"],
        "knownSlotCorrect": known_slot_eval["correct"],
        "knownSlotTop1Accuracy": known_slot_eval["top1Accuracy"],
        "coBestActionValueTop1": True,
        "tiebreakOnlyNeutral": True,
        "runtimeBaseScoreSource": known_slot_eval.get("runtimeBaseScoreSource"),
        "runtimeBaseScoreSourceGroups": known_slot_eval.get("runtimeBaseScoreSourceGroups"),
        "knownSlotByDecisionKind": known_slot_eval["byDecisionKind"],
        "runtimeCalibratedEval": runtime_base_scorer is not None and runtime_aux_score_weight is not None,
        "runtimeAuxScoreWeight": float(runtime_aux_score_weight) if runtime_aux_score_weight is not None else None,
    }


def _runtime_base_action_value_listwise_eval(
    rows: list[Mapping[str, Any]],
    *,
    fallback_base_scorer: Any | None = None,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_state_group_key(row), []).append(row)
    total = 0
    correct = 0
    row_runtime_base_groups = 0
    scorer_runtime_base_groups = 0
    by_decision: dict[str, dict[str, int]] = {}
    for (_run_id, _state_key, decision, _action_set_identity), group in grouped.items():
        representative = group[0]
        known_values = _known_action_value_slots(group, legal_slots=set(_ygo_legal_slots(representative)))
        if len(known_values) < 2:
            continue
        runtime_scores = row_runtime_total_scores(
            representative,
            require_explicit_mode=True,
            require_policy_provenance=True,
        )
        source = "row_runtime_total"
        if runtime_scores is None and fallback_base_scorer is not None:
            runtime_scores = fallback_base_scorer.score_row(representative)
            source = "scorer_runtime_base"
        if runtime_scores is None:
            continue
        candidate_slots = [
            slot
            for slot in known_values
            if slot < len(runtime_scores) and runtime_scores[slot] is not None
        ]
        best_slots = _best_action_value_slots(known_values, candidate_slots=candidate_slots)
        if not best_slots:
            continue
        if source == "row_runtime_total":
            row_runtime_base_groups += 1
        else:
            scorer_runtime_base_groups += 1
        selected = runtime_top_slot(runtime_scores, candidate_slots)
        if selected is None:
            continue
        total += 1
        if selected in best_slots:
            correct += 1
        bucket = by_decision.setdefault(str(decision), {"total": 0, "correct": 0})
        bucket["total"] += 1
        if selected in best_slots:
            bucket["correct"] += 1
    return {
        "total": int(total),
        "correct": int(correct),
        "top1Accuracy": float(correct / total) if total else 0.0,
        "knownSlotTotal": int(total),
        "knownSlotCorrect": int(correct),
        "knownSlotTop1Accuracy": float(correct / total) if total else 0.0,
        "coBestActionValueTop1": True,
        "tiebreakOnlyNeutral": True,
        "runtimeBaseScoreSource": _runtime_base_score_source_summary(
            row_runtime_base_groups=row_runtime_base_groups,
            scorer_runtime_base_groups=scorer_runtime_base_groups,
        ),
        "runtimeBaseScoreSourceGroups": {
            "rowRuntimeTotal": int(row_runtime_base_groups),
            "scorerRuntimeBase": int(scorer_runtime_base_groups),
        },
        "knownSlotByDecisionKind": {
            decision: {
                "total": values["total"],
                "correct": values["correct"],
                "top1Accuracy": float(values["correct"] / values["total"]) if values["total"] else 0.0,
            }
            for decision, values in sorted(by_decision.items())
        },
        "runtimeCalibratedEval": True,
        "runtimeAuxScoreWeight": 0.0,
    }


def _action_value_listwise_eval_delta(
    candidate_eval: Mapping[str, Any],
    base_eval: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(base_eval, Mapping):
        return None
    candidate_top1 = _float_or_none(candidate_eval.get("knownSlotTop1Accuracy"))
    base_top1 = _float_or_none(base_eval.get("knownSlotTop1Accuracy"))
    by_decision: dict[str, dict[str, Any]] = {}
    candidate_by_decision = candidate_eval.get("knownSlotByDecisionKind")
    base_by_decision = base_eval.get("knownSlotByDecisionKind")
    if isinstance(candidate_by_decision, Mapping) and isinstance(base_by_decision, Mapping):
        for decision, candidate_summary in candidate_by_decision.items():
            base_summary = base_by_decision.get(decision)
            if not isinstance(candidate_summary, Mapping) or not isinstance(base_summary, Mapping):
                continue
            candidate_route_top1 = _float_or_none(candidate_summary.get("top1Accuracy"))
            base_route_top1 = _float_or_none(base_summary.get("top1Accuracy"))
            by_decision[str(decision)] = {
                "candidateTop1Accuracy": candidate_route_top1,
                "baseTop1Accuracy": base_route_top1,
                "top1AccuracyDelta": (
                    float(candidate_route_top1) - float(base_route_top1)
                    if candidate_route_top1 is not None and base_route_top1 is not None
                    else None
                ),
                "candidateTotal": int(candidate_summary.get("total", 0) or 0),
                "baseTotal": int(base_summary.get("total", 0) or 0),
            }
    return {
        "candidateTop1Accuracy": candidate_top1,
        "baseTop1Accuracy": base_top1,
        "top1AccuracyDelta": (
            float(candidate_top1) - float(base_top1)
            if candidate_top1 is not None and base_top1 is not None
            else None
        ),
        "byDecisionKind": by_decision,
    }


def _eval_scores(
    model: Any,
    row: Mapping[str, Any],
    *,
    runtime_base_scorer: Any | None,
    runtime_aux_score_weight: float | None,
) -> tuple[list[float | None], str | None]:
    scores = model.score_row(row)
    if runtime_base_scorer is None or runtime_aux_score_weight is None:
        return scores, None
    runtime_row_scores = row_runtime_total_scores(
        row,
        require_explicit_mode=True,
        require_policy_provenance=True,
    )
    runtime_base_source = "row_runtime_total" if runtime_row_scores is not None else "scorer_runtime_base"
    base_scores = runtime_row_scores or runtime_base_scorer.score_row(row)
    max_correction = (
        BOUNDED_RUNTIME_AUX_MAX_CORRECTION
        if is_bounded_runtime_aux_objective(getattr(model, "runtimeAuxTrainingObjective", None))
        else None
    )
    out: list[float | None] = []
    for slot, score in enumerate(scores):
        if score is None:
            out.append(None)
            continue
        base_score = base_scores[slot] if 0 <= slot < len(base_scores) else None
        out.append(
            compose_runtime_aux_score(
                base_score,
                score,
                weight=float(runtime_aux_score_weight),
                max_correction=max_correction,
            )
        )
    return out, runtime_base_source


def _runtime_base_score_source_summary(
    *,
    row_runtime_base_groups: int,
    scorer_runtime_base_groups: int,
) -> str | None:
    if row_runtime_base_groups and not scorer_runtime_base_groups:
        return "row_runtime_total"
    if scorer_runtime_base_groups and not row_runtime_base_groups:
        return "scorer_runtime_base"
    if row_runtime_base_groups or scorer_runtime_base_groups:
        return "mixed"
    return None


def _action_value_listwise_group_count(rows: list[Mapping[str, Any]]) -> int:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_state_group_key(row), []).append(row)
    count = 0
    for group in grouped.values():
        representative = group[0]
        legal_slots = set(_ygo_legal_slots(representative))
        known_values = _known_action_value_slots(group, legal_slots=legal_slots)
        if len(known_values) < 2:
            continue
        if not legal_slots or not legal_slots.issubset(set(known_values)):
            continue
        values = list(known_values.values())
        if not value_spread_is_trainable(values):
            continue
        count += 1
    return count


def _row_has_explicit_action_value_row(row: Mapping[str, Any]) -> bool:
    legal_slots = set(_ygo_legal_slots(row))
    if not legal_slots:
        return False
    slot = _row_action_slot(row)
    return slot is not None and slot in legal_slots and _row_action_value(row) is not None


def _load_initial_scorer(path: str | Path | None) -> YgoStyleActionSetPolicyScorer | None:
    if path is None:
        return None
    data = _load_ygo_style_model_payload(Path(path))
    if not isinstance(data, Mapping):
        raise ValueError(f"base ygo-style model must be a JSON object or pt checkpoint: {path}")
    reject_rejected_direct_ygo_model(path=path, data=data, usage_label="warm-start base")
    scorer = YgoStyleActionSetPolicyScorer.from_dict(data)
    try:
        scorer.validate_shape()
    except ValueError as exc:
        raise ValueError(f"base ygo-style model shape is invalid: {path}") from exc
    return scorer


def _load_ygo_style_model_payload(path: Path) -> Mapping[str, Any]:
    if path.suffix.lower() in {".pt", ".pth"}:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyTorch is required to load ygo-style .pt checkpoints") from exc
        try:
            payload = torch.load(path, map_location="cpu", weights_only=False)
        except TypeError:  # pragma: no cover - older torch
            payload = torch.load(path, map_location="cpu")
        if isinstance(payload, Mapping) and isinstance(payload.get("model"), Mapping):
            return payload["model"]
        if isinstance(payload, Mapping):
            return payload
        raise ValueError(f"ygo-style .pt checkpoint must contain a mapping payload: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, Mapping) and isinstance(data.get("model"), Mapping):
        return data["model"]
    return data


def _write_ygo_style_model_pt(path: Path, model_dict: Mapping[str, Any]) -> None:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyTorch is required to write ygo-style .pt checkpoints") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "checkpointVersion": YGO_STYLE_POLICY_PT_CHECKPOINT_VERSION,
            "model": dict(model_dict),
        },
        path,
    )


def _assert_current_policy_actor_base_model(
    path: str | Path,
    *,
    expected_actor_policy_id: str,
    allow_launchable_candidate_base: bool = False,
) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"current-policy actor_N base model must be a JSON object: {path}")
    if bool(data.get("basePreservingActor")):
        expected = str(expected_actor_policy_id or "").strip()
        runtime_weights = current_policy_runtime_weights_for_actor_model_path(
            actor_id=expected,
            model_path=path,
            source_policy_id=str(data.get("sourceActorPolicyId") or ""),
            min_source_rows=0,
        )
        return assert_current_policy_source_actor_ready(
            expected,
            runtime_weights=runtime_weights,
            explicit_model_path=path,
            context="current-policy actor_N base model",
        )
    for key in ("sidecarListwiseTraining", "residualSidecarTraining", "runtimeCalibratedSidecarTraining"):
        if bool(data.get(key)):
            raise ValueError(f"current-policy actor_N base model must not be a sidecar artifact: {key} is true")
    expected = str(expected_actor_policy_id or "").strip()
    ids = {
        key: str(data.get(key) or "").strip()
        for key in ("actorPolicyId", "candidatePolicyId", "modelId", "policyId", "candidateModelId")
    }
    present = {key: value for key, value in ids.items() if value}
    if not present:
        raise ValueError("current-policy actor_N base model is missing actor identity")
    mismatched = {key: value for key, value in present.items() if value != expected}
    if mismatched:
        details = ", ".join(f"{key}={value}" for key, value in sorted(mismatched.items()))
        raise ValueError(
            f"current-policy actor_N base model id mismatch: expected {expected}, got {details}"
        )
    if bool(allow_launchable_candidate_base) or not bool(data.get("actorNSourceEligible")):
        actor_payload = load_current_policy_actor_artifact(
            path,
            expected_candidate_policy_ids=[expected],
            context="current-policy launchable base model",
        )
        return {
            "checked": True,
            "modelPath": str(path),
            "actorPolicyId": str(actor_payload.get("actorPolicyId") or ""),
            "candidatePolicyId": str(actor_payload.get("candidatePolicyId") or actor_payload.get("modelId") or ""),
            "sourceActorPolicyId": str(actor_payload.get("sourceActorPolicyId") or ""),
            "actorNSourceEligible": bool(actor_payload.get("actorNSourceEligible")),
            "promotedSource": False,
            "launchableCandidateBase": True,
            "bootstrapInitialization": bool(actor_payload.get("bootstrapInitialization")),
            "behaviorCloneTraining": bool(actor_payload.get("behaviorCloneTraining")),
        }
    bootstrap_source_seed = (
        bool(data.get("bootstrapInitialization"))
        and bool(data.get("currentPolicyBootstrapSourceEligible"))
        and bool(data.get("baseActorEquivalenceGatePassed"))
        and not bool(data.get("behaviorCloneTraining"))
    )
    if bool(data.get("bootstrapInitialization")) and not bootstrap_source_seed:
        raise ValueError("current-policy actor_N base model is not a learned actor_N source: bootstrapInitialization is true")
    if bool(data.get("behaviorCloneTraining")):
        raise ValueError("current-policy actor_N base model is not a learned actor_N source: behaviorCloneTraining is true")
    runtime_weights = current_policy_runtime_weights_for_actor_model_path(
        actor_id=expected,
        model_path=path,
        source_policy_id=str(data.get("sourceActorPolicyId") or ""),
        min_source_rows=DEFAULT_CURRENT_POLICY_MIN_SOURCE_ROWS,
    )
    return assert_current_policy_source_actor_ready(
        expected,
        runtime_weights=runtime_weights,
        explicit_model_path=path,
        context="current-policy actor_N base model",
    )


def _current_policy_source_value_head_trusted(path: str | Path) -> bool:
    data = load_current_policy_actor_artifact(Path(path))
    return (
        str(data.get("trainingObjective") or "") == CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE
        and bool(data.get("sampledAdvantagePolicyGradientTraining"))
        # ponytail: actor promotion proves policy can battle, not that its critic is a good GAE baseline.
        and bool(data.get("valueHeadTrustedForGae"))
    )


def _assert_not_retired_actor0_policy_id(value: str, *, context: str) -> None:
    if str(value or "").strip() in {"actor0", "actor0_next"}:
        raise ValueError(f"{context} must not use retired actor0/actor0_next policy ids")


def _model_id_from_json(path: str | Path | None) -> str:
    if path is None:
        return ""
    data = _load_ygo_style_model_payload(Path(path))
    if not isinstance(data, Mapping):
        return ""
    return str(data.get("modelId") or data.get("policyId") or data.get("candidateModelId") or "").strip()


def _assert_runtime_policy_id_contract(
    rows: list[Mapping[str, Any]],
    *,
    expected_runtime_policy_id: str,
) -> dict[str, Any]:
    expected = str(expected_runtime_policy_id or "").strip()
    if not expected:
        return {
            "checked": False,
            "expectedRuntimePolicyId": None,
            "reason": "no_expected_runtime_policy_id",
        }
    observed: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    for row in rows:
        provenance, reason = runtime_total_score_provenance(row, require_policy_provenance=True)
        if reason is not None:
            rejected[str(reason)] += 1
            continue
        runtime_policy_id = str(provenance.runtimePolicyId if provenance is not None else "").strip()
        observed[runtime_policy_id] += 1
    mismatched = {
        policy_id: count
        for policy_id, count in observed.items()
        if policy_id != expected
    }
    if rejected or mismatched:
        raise ValueError(
            "row runtime policy id mismatch: "
            f"expected {expected!r}; observed {dict(sorted(observed.items()))}; "
            f"rejected {dict(sorted(rejected.items()))}"
        )
    return {
        "checked": True,
        "expectedRuntimePolicyId": expected,
        "observedRuntimePolicyIds": dict(sorted(observed.items())),
        "rows": int(sum(observed.values())),
    }


def _state_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return _cached_sqlite_training_group_key(row) or action_value_state_group_key(row)


def _known_action_value_slots(
    rows: list[Mapping[str, Any]],
    *,
    legal_slots: set[int],
) -> dict[int, float]:
    return _ygo_known_action_value_slots(rows, legal_slots=legal_slots)


def _row_action_slot(row: Mapping[str, Any]) -> int | None:
    for key in ("actionSlot", "actionIndex"):
        value = _int_or_none(row.get(key))
        if value is not None:
            return value
    label = _mapping(row.get("label"))
    return _int_or_none(label.get("actionSlot"))


def _row_action_value(row: Mapping[str, Any]) -> float | None:
    label = _mapping(row.get("label"))
    for key in ("actionValue", "relativeValue", "branchValue", "rolloutWinValue"):
        value = _float_or_none(label.get(key))
        if value is not None:
            return value
    role = str(label.get("actionRole") or "").strip().lower()
    if role == "selected":
        value = _float_or_none(label.get("selectedValue"))
        if value is not None:
            return value
    if role == "alternative":
        value = _float_or_none(label.get("alternativeValue"))
        if value is not None:
            return value
    for key in ("actionValue", "relativeValue", "branchValue", "rolloutWinValue"):
        value = _float_or_none(row.get(key))
        if value is not None:
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_has_source_or_target_ref(row: Mapping[str, Any]) -> bool:
    names = [str(name) for name in list(row.get("actionFeatureNames") or [])]
    return "action_ref:source_card_slot_norm" in names or "action_ref:target_card_slot_norm" in names


def _normalized_row_file_weights(paths: list[Path], weights: list[float] | None) -> list[float]:
    if weights is None:
        return [1.0 for _path in paths]
    if len(weights) != len(paths):
        raise ValueError("training row file weights must match the number of --training-rows paths")
    return [max(0.0, float(value)) for value in weights]


def _normalize_runtime_aux_training_objective(value: Any) -> str:
    objective = str(value or RUNTIME_AUX_TRAINING_OBJECTIVE_VALUE_DISTRIBUTION).strip()
    if objective not in RUNTIME_AUX_TRAINING_OBJECTIVES:
        raise ValueError(
            "runtime_aux_training_objective must be one of "
            f"{', '.join(RUNTIME_AUX_TRAINING_OBJECTIVES)}"
        )
    return objective


def _runtime_action_value_training_objective(runtime_aux_training_objective: str) -> str:
    if runtime_aux_training_objective == RUNTIME_AUX_TRAINING_OBJECTIVE_BOUNDED_BASE_WRONG_PRESERVE_CORRECT:
        return "runtime_calibrated_bounded_base_wrong_preserve_correct_full_legal_action_set_ranking"
    if runtime_aux_training_objective == RUNTIME_AUX_TRAINING_OBJECTIVE_BASE_WRONG_PRESERVE_CORRECT:
        return "runtime_calibrated_base_wrong_preserve_correct_full_legal_action_set_value_distribution"
    if runtime_aux_training_objective == RUNTIME_AUX_TRAINING_OBJECTIVE_BASE_WRONG_ONLY:
        return "runtime_calibrated_base_wrong_only_full_legal_action_set_value_distribution"
    return "runtime_calibrated_full_legal_action_set_value_distribution"


def _emit_training_progress(phase: str, **fields: Any) -> None:
    payload = {
        "kind": "ygo_style_training_progress_v1",
        "phase": str(phase),
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _resolve_action_value_listwise_learning_rate(
    learning_rate: float | None,
    *,
    runtime_calibrated_sidecar_training: bool,
) -> tuple[float, str]:
    if learning_rate is not None:
        return float(learning_rate), "explicit"
    if bool(runtime_calibrated_sidecar_training):
        return YGO_RUNTIME_AUX_DEFAULT_LEARNING_RATE, "runtime_aux_default"
    return YGO_DEFAULT_LEARNING_RATE, "default"


SQLITE_TRAINING_ROW_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
SQLITE_TRAINING_ROW_TABLE = "training_action_value_rows"
SQLITE_TRAJECTORY_ROW_TABLE = "training_trajectory_rows"
SQLITE_TRAINING_GROUP_KEY_METADATA = "_sqliteTrainingGroupKey"


def _refresh_action_value_semantics_for_training(
    rows: list[dict[str, Any]],
    *,
    source_label: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if rows and all(bool(_mapping(row.get("metadata")).get("semanticRefreshNotRequired")) for row in rows):
        return rows, {
            "kind": "action_value_semantic_refresh_v1",
            "sourceLabel": str(source_label),
            "inputRows": int(len(rows)),
            "outputRows": int(len(rows)),
            "changedActionFeatureRows": 0,
            "changedGlobalFeatureRows": 0,
            "changedCardFeatureRows": 0,
            "unchangedRows": int(len(rows)),
            "cacheEntries": 0,
            "skipped": True,
            "skipReason": "engine_fresh_gate_action_set_rows",
            "byDecisionKind": {
                decision: {"rows": int(count), "unchangedRows": int(count)}
                for decision, count in _row_counts_by_decision_kind(rows).items()
            },
        }
    return refresh_action_value_training_rows_semantics(rows, source_label=source_label)


def _filter_rows_by_included_decision_kinds(
    rows: list[dict[str, Any]],
    *,
    include_decision_kinds: Iterable[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    include = sorted({str(value).strip() for value in (include_decision_kinds or []) if str(value).strip()})
    if not include:
        return (
            list(rows),
            {
                "enabled": False,
                "includeDecisionKinds": [],
                "inputRows": int(len(rows)),
                "acceptedRows": int(len(rows)),
                "rejectedRows": 0,
                "acceptedRowsByDecisionKind": _row_counts_by_decision_kind(rows),
                "rejectedRowsByDecisionKind": {},
            },
        )
    include_set = set(include)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        decision = str(row.get("decisionKind") or "unknown")
        if decision in include_set:
            accepted.append(row)
        else:
            rejected.append(row)
    return (
        accepted,
        {
            "enabled": True,
            "includeDecisionKinds": include,
            "inputRows": int(len(rows)),
            "acceptedRows": int(len(accepted)),
            "rejectedRows": int(len(rejected)),
            "acceptedRowsByDecisionKind": _row_counts_by_decision_kind(accepted),
            "rejectedRowsByDecisionKind": _row_counts_by_decision_kind(rejected),
        },
    )


def _current_policy_training_row_contract_report(
    rows: list[Mapping[str, Any]],
    *,
    actor_policy_id: str,
) -> dict[str, Any]:
    actor_id = str(actor_policy_id or "").strip()
    row_reasons: list[str | None] = []
    for row_index, row in enumerate(rows):
        decision = str(row.get("decisionKind") or "unknown")
        reason: str | None = None
        if str(row.get("schema") or "") != CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA:
            reason = "nonTrajectorySchema"
        elif not str(row.get("stateKey") or "").strip():
            reason = "missingStateKey"
        elif str(row.get("taskKind") or "") != CURRENT_POLICY_TRAJECTORY_TASK_KIND:
            reason = "nonCurrentPolicyTaskKind"
        elif _ygo_trajectory_policy_label(row) is None:
            reason = "missingTrajectoryPolicyLabel"
        elif (legacy_reason := _legacy_sidecar_row_field_rejection_reason(row)) is not None:
            reason = legacy_reason
        elif (actor_id_conflict := current_policy_id_container_conflict_rejection_reason(row)) is not None:
            reason = actor_id_conflict
        elif (score_mode_reason := _current_policy_score_mode_rejection_reason(row)) is not None:
            reason = score_mode_reason
        else:
            try:
                validated = validate_current_policy_row(row)
                top_selection = select_current_policy_top(row)
            except ValueError as exc:
                reason = f"invalidCurrentPolicyRow:{_compact_rejection_reason(str(exc))}"
            else:
                if str(validated["actorPolicyId"]) != actor_id:
                    reason = "actorPolicyId mismatch"
                else:
                    policy_metadata_reason = actor_policy_metadata_rejection_reason(
                        row,
                        expected_actor_policy_id=actor_id,
                    )
                    if policy_metadata_reason is not None:
                        reason = f"actorPolicyMetadata:{policy_metadata_reason}"
                        row_reasons.append(reason)
                        continue
                    score_provenance_reason = actor_score_provenance_rejection_reason(
                        row,
                        expected_actor_policy_id=actor_id,
                    )
                    if score_provenance_reason is not None:
                        reason = f"actorScoreProvenance:{score_provenance_reason}"
                        row_reasons.append(reason)
                        continue
                    selection_mode = _actor_selection_mode_from_row(row)
                    if selection_mode not in {"sampled_from_logits", "stochastic_rollout"}:
                        reason = "nonSampledActorSelection"
                        row_reasons.append(reason)
                        continue
                    if _actor_sampling_log_prob_from_row(row) is None:
                        reason = "missingActorActionLogProb"
                        row_reasons.append(reason)
                        continue
                    provenance_reason = actor_rollout_provenance_rejection_reason(row)
                    if provenance_reason is not None:
                        reason = str(provenance_reason)
        row_reasons.append(reason)

    accepted = 0
    rejected: Counter[str] = Counter()
    accepted_by_decision: Counter[str] = Counter()
    rejected_by_decision: Counter[str] = Counter()
    for row, reason in zip(rows, row_reasons, strict=True):
        decision = str(row.get("decisionKind") or "unknown")
        if reason is None:
            accepted += 1
            accepted_by_decision[decision] += 1
        else:
            rejected[reason] += 1
            rejected_by_decision[decision] += 1
    return {
        "kind": "current_policy_training_row_contract_report_v1",
        "actorPolicyId": actor_id,
        "inputRows": int(len(rows)),
        "acceptedRows": int(accepted),
        "rejectedRows": int(sum(rejected.values())),
        "rejectionReasons": {str(key): int(value) for key, value in sorted(rejected.items())},
        "acceptedRowsByDecisionKind": {str(key): int(value) for key, value in sorted(accepted_by_decision.items())},
        "rejectedRowsByDecisionKind": {str(key): int(value) for key, value in sorted(rejected_by_decision.items())},
    }


def _current_policy_training_row_contract_report_fast(
    rows: list[Mapping[str, Any]],
    *,
    actor_policy_id: str,
) -> dict[str, Any]:
    actor_id = str(actor_policy_id or "").strip()
    row_reasons: list[str | None] = []
    for row in rows:
        metadata = _mapping(row.get("metadata"))
        reason: str | None = None
        if str(row.get("schema") or "") != CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA:
            reason = "nonTrajectorySchema"
        elif not str(row.get("stateKey") or "").strip():
            reason = "missingStateKey"
        elif str(row.get("taskKind") or "") != CURRENT_POLICY_TRAJECTORY_TASK_KIND:
            reason = "nonCurrentPolicyTaskKind"
        elif _ygo_trajectory_policy_label(row) is None:
            reason = "missingTrajectoryPolicyLabel"
        elif (legacy_reason := _legacy_sidecar_row_field_rejection_reason(row)) is not None:
            reason = legacy_reason
        elif (actor_id_conflict := current_policy_id_container_conflict_rejection_reason(row)) is not None:
            reason = actor_id_conflict
        elif (score_mode_reason := _current_policy_score_mode_rejection_reason(row)) is not None:
            reason = score_mode_reason
        else:
            row_actor_id = str(row.get("actorPolicyId") or metadata.get("actorPolicyId") or "").strip()
            if row_actor_id != actor_id:
                reason = "actorPolicyId mismatch"
            elif (policy_metadata_reason := actor_policy_metadata_rejection_reason(
                row,
                expected_actor_policy_id=actor_id,
            )) is not None:
                reason = f"actorPolicyMetadata:{policy_metadata_reason}"
            else:
                selection_mode = _actor_selection_mode_from_row(row)
                if selection_mode not in {"sampled_from_logits", "stochastic_rollout"}:
                    reason = "nonSampledActorSelection"
                elif _actor_sampling_log_prob_from_row(row) is None:
                    reason = "missingActorActionLogProb"
        row_reasons.append(reason)

    accepted = 0
    rejected: Counter[str] = Counter()
    accepted_by_decision: Counter[str] = Counter()
    rejected_by_decision: Counter[str] = Counter()
    for row, reason in zip(rows, row_reasons, strict=True):
        decision = str(row.get("decisionKind") or "unknown")
        if reason is None:
            accepted += 1
            accepted_by_decision[decision] += 1
        else:
            rejected[reason] += 1
            rejected_by_decision[decision] += 1
    return {
        "kind": "current_policy_training_row_contract_report_v1",
        "contractMode": "fast_preflight",
        "fastPreflight": True,
        "fullValidationDeferred": True,
        "actorPolicyId": actor_id,
        "inputRows": int(len(rows)),
        "acceptedRows": int(accepted),
        "rejectedRows": int(sum(rejected.values())),
        "rejectionReasons": {str(key): int(value) for key, value in sorted(rejected.items())},
        "acceptedRowsByDecisionKind": {str(key): int(value) for key, value in sorted(accepted_by_decision.items())},
        "rejectedRowsByDecisionKind": {str(key): int(value) for key, value in sorted(rejected_by_decision.items())},
    }


def _current_policy_bootstrap_row_contract_report(
    rows: list[Mapping[str, Any]],
    *,
    bootstrap_source_policy_id: str,
) -> dict[str, Any]:
    source_policy_id = str(bootstrap_source_policy_id or "").strip()
    row_reasons: list[str | None] = []
    grouped_row_indexes: dict[tuple[str, str, str, str], list[int]] = {}
    for row_index, row in enumerate(rows):
        decision = str(row.get("decisionKind") or "unknown")
        reason: str | None = None
        if str(row.get("schema") or "") != "snapshot_branch_full_legal_action_value_rows_v1":
            reason = "nonFullLegalSchema"
        elif not str(row.get("stateKey") or "").strip():
            reason = "missingStateKey"
        elif not _row_is_full_legal_action_value_group(row):
            reason = "nonFullLegalActionValueGroup"
        elif str(row.get("taskKind") or "") != BOOTSTRAP_FULL_LEGAL_ROLLOUT_TASK_KIND:
            reason = "nonBootstrapTaskKind"
        elif str(row.get("labelKind") or "") != "action_value":
            reason = "nonActionValueLabelKind"
        elif str(row.get("teacherId") or "") != "snapshot_branch_rollout":
            reason = "nonSnapshotBranchRolloutTeacher"
        elif not bool(row.get("nonTie")):
            reason = "notOutcomeNonTie"
        elif (legacy_reason := _legacy_sidecar_row_field_rejection_reason(row)) is not None:
            reason = legacy_reason
        else:
            score_mode_reason = _bootstrap_teacher_score_mode_rejection_reason(row)
            if score_mode_reason is not None:
                reason = score_mode_reason
            else:
                runtime_reason = row_runtime_total_rejection_reason(
                    row,
                    require_explicit_mode=True,
                    require_policy_provenance=True,
                )
                if runtime_reason is not None:
                    reason = f"runtimeTotal:{runtime_reason}"
                else:
                    provenance, provenance_reason = runtime_total_score_provenance(
                        row,
                        require_policy_provenance=True,
                    )
                    if provenance_reason is not None or provenance is None:
                        reason = f"runtimeTotal:{provenance_reason or 'missing_provenance'}"
                    elif provenance.runtimePolicyId != source_policy_id:
                        reason = "bootstrapRuntimePolicyIdMismatch"
                    elif provenance.actorPolicyId != source_policy_id:
                        reason = "bootstrapActorPolicyIdMismatch"
                    elif provenance.subjectPolicyId and provenance.subjectPolicyId != source_policy_id:
                        reason = "bootstrapSubjectPolicyIdMismatch"
                    else:
                        actor_field_reason = _bootstrap_current_policy_actor_field_rejection_reason(row)
                        if actor_field_reason is not None:
                            reason = actor_field_reason
                        else:
                            action_record_reason = _bootstrap_action_records_rejection_reason(row)
                            if action_record_reason is not None:
                                reason = action_record_reason
                            else:
                                identity_reason = action_value_group_identity_rejection_reason(row)
                                if identity_reason is not None:
                                    reason = f"invalidFullLegalActionSetIdentity:{identity_reason}"
        if reason is None:
            grouped_row_indexes.setdefault(action_value_state_group_key(row), []).append(row_index)
        row_reasons.append(reason)

    for group_indexes in grouped_row_indexes.values():
        if not group_indexes:
            continue
        representative = rows[group_indexes[0]]
        legal_slots = _current_policy_contract_legal_slots(representative)
        present_slots = [
            int(slot)
            for index in group_indexes
            for slot in (_row_action_slot(rows[index]),)
            if slot is not None
        ]
        if len(group_indexes) == 1 and _bootstrap_row_has_action_value_distribution(rows[group_indexes[0]]):
            continue
        present_slot_set = set(present_slots)
        if len(present_slots) != len(present_slot_set):
            for index in group_indexes:
                row_reasons[index] = "duplicateFullLegalActionSetSlot"
        elif legal_slots and present_slot_set != legal_slots:
            for index in group_indexes:
                row_reasons[index] = "incompleteFullLegalActionSetGroup"

    accepted = 0
    rejected: Counter[str] = Counter()
    accepted_by_decision: Counter[str] = Counter()
    rejected_by_decision: Counter[str] = Counter()
    for row, reason in zip(rows, row_reasons, strict=True):
        decision = str(row.get("decisionKind") or "unknown")
        if reason is None:
            accepted += 1
            accepted_by_decision[decision] += 1
        else:
            rejected[reason] += 1
            rejected_by_decision[decision] += 1
    return {
        "kind": "current_policy_bootstrap_row_contract_report_v1",
        "bootstrapSourcePolicyId": source_policy_id,
        "actorPolicyId": source_policy_id,
        "requiredTaskKind": BOOTSTRAP_FULL_LEGAL_ROLLOUT_TASK_KIND,
        "requiredScoreMode": "runtime_total_or_aux_runtime_total",
        "inputRows": int(len(rows)),
        "acceptedRows": int(accepted),
        "rejectedRows": int(sum(rejected.values())),
        "rejectionReasons": {str(key): int(value) for key, value in sorted(rejected.items())},
        "acceptedRowsByDecisionKind": {str(key): int(value) for key, value in sorted(accepted_by_decision.items())},
        "rejectedRowsByDecisionKind": {str(key): int(value) for key, value in sorted(rejected_by_decision.items())},
    }


def _current_policy_stale_teacher_score_mode(row: Mapping[str, Any]) -> bool:
    return _current_policy_score_mode_rejection_reason(row) is not None


def _current_policy_score_mode_rejection_reason(row: Mapping[str, Any]) -> str | None:
    reason = score_mode_consistency_rejection_reason(row)
    if reason is None:
        return None
    if reason == "score_mode_conflict":
        return "scoreModeConflict"
    return "staleTeacherScoreMode"


def _bootstrap_teacher_score_mode(row: Mapping[str, Any]) -> str:
    for source in (_mapping(row.get("metadata")), row):
        provenance = source.get("scoreProvenance")
        if isinstance(provenance, Mapping):
            value = provenance.get("scoreMode")
            if value:
                return str(value).strip()
    metadata = _mapping(row.get("metadata"))
    value = metadata.get("teacherScoreMode") or row.get("teacherScoreMode")
    return str(value).strip() if value else ""


def _bootstrap_teacher_score_mode_rejection_reason(row: Mapping[str, Any]) -> str | None:
    reason = score_mode_consistency_rejection_reason(
        row,
        allowed_modes=("runtime_total", "aux_runtime_total"),
    )
    if reason is None:
        return None
    if reason == "missing_score_mode":
        return "bootstrapTeacherScoreMode"
    if reason == "score_mode_conflict":
        return "bootstrapTeacherScoreModeMismatch"
    return "bootstrapTeacherScoreMode"


def _legacy_sidecar_row_field_rejection_reason(row: Mapping[str, Any]) -> str | None:
    stale_keys = {
        "action_set_aux_score_weight",
        "action_set_listwise_scorer_path",
        "action_set_residual_scorer_path",
        "action_set_residual_score_weight",
        "actionSetAuxScoreWeight",
        "actionSetListwiseScorerPath",
        "actionSetResidualScorerPath",
        "actionSetResidualScoreWeight",
        "direct_action_set_scorer_path",
        "phase_p_action_value_scorer_path",
        "residualSidecarTraining",
        "runtimeAuxScoreWeight",
        "runtimeCalibratedSidecarTraining",
        "sidecarListwiseTraining",
    }
    for source_name, source in (
        ("row", row),
        ("metadata", _mapping(row.get("metadata"))),
        ("sourceContext", _mapping(row.get("sourceContext"))),
    ):
        for key in sorted(stale_keys):
            if key in source:
                return f"containsLegacySidecarField:{source_name}.{key}"
    return None


def _bootstrap_current_policy_actor_field_rejection_reason(row: Mapping[str, Any]) -> str | None:
    stale_keys = {
        "actorPolicyId",
        "actorLogits",
        "actorActionSlot",
        "actorActionIdentity",
        "actorTopSlot",
        "actorTopActionIdentity",
        "sourceActorPolicyId",
        "currentPolicySourceActorPolicyId",
        "runtimeCandidatePolicyId",
        "currentPolicyCandidatePolicyId",
    }
    for source_name, source in (
        ("row", row),
        ("metadata", _mapping(row.get("metadata"))),
        ("sourceContext", _mapping(row.get("sourceContext"))),
    ):
        for key in sorted(stale_keys):
            if key in source:
                return f"containsCurrentPolicyActorField:{source_name}.{key}"
    return None


def _bootstrap_action_records_rejection_reason(row: Mapping[str, Any]) -> str | None:
    actions = row.get("actions")
    action_records = row.get("actionRecords")
    if not isinstance(actions, list | tuple) or not actions:
        return "missingActions"
    if not isinstance(action_records, list | tuple):
        return "missingActionRecords"
    if len(actions) != len(action_records):
        return "actionRecordsLengthMismatch"
    if "legalMask" in row and "mask_" in row:
        legal_mask = [bool(value) for value in list(row.get("legalMask") or [])]
        tensor_mask = [bool(value) for value in list(row.get("mask_") or [])]
        if legal_mask != tensor_mask:
            return "legalMaskMismatch"
    mask = row.get("mask_") if "mask_" in row else row.get("legalMask")
    if not isinstance(mask, list | tuple) or len(mask) != len(actions):
        return "legalMaskActionLengthMismatch"
    action_features = row.get("actions_")
    if not isinstance(action_features, list | tuple) or len(action_features) != len(actions):
        return "actionFeaturesLengthMismatch"
    runtime_scores = row_runtime_total_scores(
        row,
        require_explicit_mode=True,
        require_policy_provenance=True,
    )
    if runtime_scores is None or len(runtime_scores) != len(actions):
        return "runtimeTotalScoreLengthMismatch"
    for index, enabled in enumerate(mask):
        if bool(enabled):
            try:
                score = float(runtime_scores[index])
            except (TypeError, ValueError):
                return f"runtimeTotalScoreMissing:{index}"
            if not math.isfinite(score):
                return f"runtimeTotalScoreMissing:{index}"
    legal_slots = _current_policy_contract_legal_slots(row)
    if not _bootstrap_row_has_action_value_distribution(row):
        action_slot = _row_action_slot(row)
        if action_slot is None or int(action_slot) not in legal_slots:
            return "actionSlotNotLegal"
    for index, (action, action_record) in enumerate(zip(actions, action_records, strict=True)):
        if canonical_action_identity(action, include_action_key=False) != canonical_action_identity(
            action_record,
            include_action_key=False,
        ):
            return f"actionRecordIdentityMismatch:{index}"
    explicit_action_identities = row.get("actionIdentities")
    if isinstance(explicit_action_identities, list | tuple):
        if len(explicit_action_identities) != len(actions):
            return "actionIdentitiesLengthMismatch"
        for index, (explicit_identity, action) in enumerate(zip(explicit_action_identities, actions, strict=True)):
            if str(explicit_identity) != _bootstrap_action_identity(action):
                return f"actionIdentitiesMismatch:{index}"
    return None


def _bootstrap_row_has_action_value_distribution(row: Mapping[str, Any]) -> bool:
    legal_slots = _current_policy_contract_legal_slots(row)
    if len(legal_slots) < 2:
        return False
    scores = row_runtime_total_scores(
        row,
        require_explicit_mode=True,
        require_policy_provenance=True,
    )
    if scores is None:
        return False
    values: list[float] = []
    for slot in sorted(legal_slots):
        if slot < 0 or slot >= len(scores):
            return False
        try:
            value = float(scores[slot])
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
        values.append(value)
    return bool(values) and max(values) - min(values) > 1.0e-9


def _bootstrap_action_identity(action: Any) -> str:
    if isinstance(action, Mapping) and str(action.get("actionIdentity") or "").strip():
        return str(action["actionIdentity"])
    return canonical_action_identity(action, include_action_key=False)


def _current_policy_contract_legal_slots(row: Mapping[str, Any]) -> set[int]:
    mask = row.get("legalMask") if "legalMask" in row else row.get("mask_")
    if not isinstance(mask, list | tuple):
        return set()
    return {int(index) for index, enabled in enumerate(mask) if bool(enabled)}


def _compact_rejection_reason(message: str) -> str:
    return "_".join(str(message or "unknown").strip().split())[:96] or "unknown"


def _reject_route_filter_unless_diagnostic(
    include_decision_kinds: Iterable[str] | None,
    *,
    allow_route_isolated_diagnostic_training: bool,
    allow_route_limited_launch_training: bool,
) -> None:
    include = {
        str(value).strip()
        for value in (include_decision_kinds or [])
        if str(value).strip()
    }
    diagnostic = bool(allow_route_isolated_diagnostic_training)
    launch_limited = bool(allow_route_limited_launch_training)
    if diagnostic and launch_limited:
        raise ValueError(
            "route-filtered training must be either diagnostic-only or route-limited launch training, not both"
        )
    if include and not (diagnostic or launch_limited):
        raise ValueError(
            "route-isolated action-value training is diagnostic-only unless explicitly launch-limited; "
            "route-filtered action-value training requires an explicit contract; "
            "pass allow_route_isolated_diagnostic_training for non-launch diagnostics "
            "or allow_route_limited_launch_training when the protected runtime route set "
            "will be a subset of the included decision kinds."
        )


def _row_counts_by_decision_kind(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter(str(row.get("decisionKind") or "unknown") for row in rows)
    return {key: int(value) for key, value in sorted(counts.items())}


def _load_weighted_training_rows(paths: list[Path], weights: list[float]) -> list[dict[str, Any]]:
    return list(_iter_weighted_training_rows(paths, weights))


def _iter_weighted_training_rows(paths: list[Path], weights: list[float]) -> Iterable[dict[str, Any]]:
    for path, weight in zip(paths, weights, strict=True):
        for row in _iter_training_rows(path):
            weighted = dict(row)
            weighted["trainingWeight"] = float(_ygo_row_training_weight(weighted)) * float(weight)
            if weight != 1.0:
                metadata = dict(weighted.get("metadata") or {})
                metadata["trainingRowFileWeight"] = float(weight)
                metadata["trainingRowsPath"] = str(path)
                weighted["metadata"] = metadata
            yield weighted


def _sqlite_training_paths_only(paths: list[Path]) -> bool:
    return bool(paths) and all(path.suffix.lower() in SQLITE_TRAINING_ROW_SUFFIXES for path in paths)


def _iter_contiguous_training_row_groups(rows: Iterable[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
    current_key: tuple[str, str, str, str] | None = None
    current_group: list[dict[str, Any]] = []
    for row in rows:
        key = action_value_state_group_key(row)
        if current_key is None:
            current_key = key
        if key != current_key:
            if current_group:
                yield current_group
            current_key = key
            current_group = []
        current_group.append(row)
    if current_group:
        yield current_group


def _current_policy_bootstrap_row_contract_report_streaming(
    rows_factory: Callable[[], Iterable[dict[str, Any]]],
    *,
    bootstrap_source_policy_id: str,
) -> dict[str, Any]:
    source_policy_id = str(bootstrap_source_policy_id or "").strip()
    merged: dict[str, Any] = {
        "kind": "current_policy_bootstrap_row_contract_report_v1",
        "bootstrapSourcePolicyId": source_policy_id,
        "actorPolicyId": source_policy_id,
        "requiredTaskKind": BOOTSTRAP_FULL_LEGAL_ROLLOUT_TASK_KIND,
        "requiredScoreMode": "runtime_total_or_aux_runtime_total",
        "inputRows": 0,
        "acceptedRows": 0,
        "rejectedRows": 0,
        "rejectionReasons": {},
        "acceptedRowsByDecisionKind": {},
        "rejectedRowsByDecisionKind": {},
        "streaming": True,
        "streamingMode": "sqlite_contiguous_state_group_batches",
    }
    for group in _iter_contiguous_training_row_groups(rows_factory()):
        report = _current_policy_bootstrap_row_contract_report(
            group,
            bootstrap_source_policy_id=source_policy_id,
        )
        merged["inputRows"] += int(report.get("inputRows", 0) or 0)
        merged["acceptedRows"] += int(report.get("acceptedRows", 0) or 0)
        merged["rejectedRows"] += int(report.get("rejectedRows", 0) or 0)
        _merge_counter_mapping(merged["rejectionReasons"], report.get("rejectionReasons"))
        _merge_counter_mapping(merged["acceptedRowsByDecisionKind"], report.get("acceptedRowsByDecisionKind"))
        _merge_counter_mapping(merged["rejectedRowsByDecisionKind"], report.get("rejectedRowsByDecisionKind"))
    return merged


def _merge_counter_mapping(target: dict[str, int], values: Any) -> None:
    if not isinstance(values, Mapping):
        return
    for key, value in values.items():
        target[str(key)] = int(target.get(str(key), 0)) + int(value or 0)


def _collect_streaming_eval_rows(
    rows_factory: Callable[[], Iterable[dict[str, Any]]],
    *,
    max_rows: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    limit = max(0, int(max_rows))
    if limit <= 0:
        return rows
    for row in rows_factory():
        if str(row.get("schema") or "") != "snapshot_branch_full_legal_action_value_rows_v1":
            continue
        if not _ygo_legal_slots(row) or not _ygo_row_has_action_value_distribution_target(row):
            continue
        rows.append(dict(row))
        if len(rows) >= limit:
            break
    return rows


def _load_weighted_current_policy_trajectory_rows(paths: list[Path], weights: list[float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, weight in zip(paths, weights, strict=True):
        for row in _iter_current_policy_trajectory_rows(path):
            weighted = dict(row)
            weighted["trainingWeight"] = float(_ygo_row_training_weight(weighted)) * float(weight)
            if weight != 1.0:
                metadata = dict(weighted.get("metadata") or {})
                metadata["trainingRowFileWeight"] = float(weight)
                metadata["trainingRowsPath"] = str(path)
                weighted["metadata"] = metadata
            rows.append(weighted)
    return rows


def _iter_current_policy_trajectory_rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in SQLITE_TRAINING_ROW_SUFFIXES:
        yield from _iter_sqlite_table_rows(path, table=SQLITE_TRAJECTORY_ROW_TABLE)
        return
    yield from _iter_json_array_rows(path)


def _iter_training_rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in SQLITE_TRAINING_ROW_SUFFIXES:
        yield from _iter_sqlite_training_rows(path)
        return
    yield from _iter_json_array_rows(path)


def _iter_sqlite_training_rows(path: Path) -> Iterable[dict[str, Any]]:
    yield from _iter_sqlite_table_rows(path, table=SQLITE_TRAINING_ROW_TABLE)


def _iter_sqlite_table_rows(path: Path, *, table: str) -> Iterable[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as conn:
        table_exists = conn.execute(
            "select 1 from sqlite_master where type='table' and name=?",
            (str(table),),
        ).fetchone()
        if table_exists is None:
            raise ValueError(
                f"SQLite training DB {path} does not contain table "
                f"{str(table)!r}; fast-farm trainable rows must be stored there"
            )
        for (row_json,) in conn.execute(
            f"select row_json from {_quote_sql_identifier(str(table))} order by row_id"
        ):
            row = _loads_training_row_json(row_json)
            if not isinstance(row, dict):
                raise ValueError(f"SQLite training row in {path} must be a JSON object")
            yield row


def _iter_sqlite_training_rows_with_ids(path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as conn:
        table_exists = conn.execute(
            "select 1 from sqlite_master where type='table' and name=?",
            (SQLITE_TRAINING_ROW_TABLE,),
        ).fetchone()
        if table_exists is None:
            raise ValueError(
                f"SQLite training DB {path} does not contain table "
                f"{SQLITE_TRAINING_ROW_TABLE!r}; fast-farm trainable rows must be stored there"
            )
        columns = {
            str(row[1])
            for row in conn.execute(f"pragma table_info({SQLITE_TRAINING_ROW_TABLE})")
        }
        row_id_expr = "row_id" if "row_id" in columns else "rowid"
        fast_group_columns = {"case_id", "state_key", "decision_kind"}.issubset(columns)
        if fast_group_columns:
            query = (
                f"select {row_id_expr}, case_id, state_key, decision_kind, row_json "
                f"from {SQLITE_TRAINING_ROW_TABLE} order by {row_id_expr}"
            )
            for row_id, case_id, state_key, decision_kind, row_json in conn.execute(query):
                row = _loads_training_row_json(row_json)
                if not isinstance(row, dict):
                    raise ValueError(f"SQLite training row in {path} must be a JSON object")
                group_key = _sqlite_training_row_group_key_from_columns(
                    row_id,
                    row,
                    case_id=case_id,
                    state_key=state_key,
                    decision_kind=decision_kind,
                )
                yield str(row_id), _with_sqlite_training_group_key(row, group_key)
            return
        for row_id, row_json in conn.execute(
            f"select {row_id_expr}, row_json from {SQLITE_TRAINING_ROW_TABLE} order by {row_id_expr}"
        ):
            row = _loads_training_row_json(row_json)
            if not isinstance(row, dict):
                raise ValueError(f"SQLite training row in {path} must be a JSON object")
            yield str(row_id), row


def _load_streamed_trajectory_advantage_rows_from_sqlite(
    paths: list[Path],
    weights: list[float],
    *,
    source_label: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], int, int]:
    usable_rows: list[dict[str, Any]] = []
    refresh_summary = _empty_semantic_refresh_summary(source_label=source_label)
    conversion_summary = _empty_action_value_trajectory_conversion_summary()
    raw_rows = 0
    converted_rows = 0
    groups_seen: set[Any] = set()
    non_contiguous_groups = 0
    streamed_groups = 0

    def flush_group(group: list[dict[str, Any]]) -> None:
        nonlocal converted_rows
        nonlocal streamed_groups
        if not group:
            return
        streamed_groups += 1
        if all(_streaming_row_can_trust_existing_semantics(row) for row in group):
            refreshed_group = group
            refresh_report = _trusted_existing_semantics_report(group, source_label=source_label)
        else:
            refreshed_group, refresh_report = _refresh_action_value_semantics_for_training(
                group,
                source_label=source_label,
            )
        _merge_semantic_refresh_summary(refresh_summary, refresh_report)
        converted_group, conversion_report = _trajectory_advantage_rows_from_full_legal_action_values(refreshed_group)
        _merge_action_value_trajectory_conversion_summary(conversion_summary, conversion_report)
        converted_rows += len(converted_group)
        usable_rows.extend(
            row
            for row in refreshed_group
            if _ygo_trajectory_policy_label(row) is not None and _ygo_legal_slots(row)
        )
        usable_rows.extend(converted_group)

    for path, file_weight in zip(paths, weights, strict=True):
        current_key: Any | None = None
        current_group: list[dict[str, Any]] = []
        for row_id, row in _iter_sqlite_training_rows_with_ids(path):
            raw_rows += 1
            weighted = dict(row)
            weighted["trainingWeight"] = float(_ygo_row_training_weight(weighted)) * float(file_weight)
            if file_weight != 1.0:
                metadata = dict(weighted.get("metadata") or {})
                metadata["trainingRowFileWeight"] = float(file_weight)
                metadata["trainingRowsPath"] = str(path)
                weighted["metadata"] = metadata
            group_key = _cached_sqlite_training_group_key(weighted) or _sqlite_training_row_id_group_key(row_id) or _state_group_key(weighted)
            if current_key is None:
                current_key = group_key
            if group_key != current_key:
                groups_seen.add(current_key)
                flush_group(current_group)
                if group_key in groups_seen:
                    non_contiguous_groups += 1
                current_key = group_key
                current_group = []
            current_group.append(weighted)
        if current_key is not None:
            groups_seen.add(current_key)
            flush_group(current_group)

    refresh_summary.update(
        {
            "streaming": True,
            "streamingMode": "sqlite_grouped_by_state_action_set",
            "inputRows": int(raw_rows),
            "outputRows": int(raw_rows),
            "streamedGroups": int(streamed_groups),
            "nonContiguousGroups": int(non_contiguous_groups),
        }
    )
    conversion_summary.update(
        {
            "streaming": True,
            "streamingMode": "sqlite_grouped_by_state_action_set",
            "inputRows": int(raw_rows),
            "convertedRows": int(converted_rows),
            "nonContiguousGroups": int(non_contiguous_groups),
        }
    )
    return usable_rows, refresh_summary, conversion_summary, int(converted_rows), int(raw_rows)


def _sqlite_training_row_id_group_key(row_id: Any) -> str | None:
    text = str(row_id or "")
    marker = "|action-set:"
    if marker not in text:
        return None
    prefix, action_part = text.split(marker, 1)
    action_set_identity = action_part.split(":", 1)[0]
    if not prefix or not action_set_identity:
        return text
    return f"{prefix}{marker}{action_set_identity}"


def _sqlite_training_row_group_key_from_columns(
    row_id: Any,
    row: Mapping[str, Any],
    *,
    case_id: Any,
    state_key: Any,
    decision_kind: Any,
) -> tuple[str, str, str, str]:
    action_set_identity = _sqlite_training_row_id_group_key(row_id) or str(case_id or "")
    return (
        str(row.get("runId") or row.get("sourceLabelRunId") or "unknown-run"),
        str(state_key or row.get("stateKey") or "unknown-state"),
        str(decision_kind or row.get("decisionKind") or "unknown"),
        str(action_set_identity or "unknown-action-set"),
    )


def _with_sqlite_training_group_key(row: dict[str, Any], group_key: tuple[str, str, str, str]) -> dict[str, Any]:
    metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
    metadata[SQLITE_TRAINING_GROUP_KEY_METADATA] = [str(part) for part in group_key]
    row["metadata"] = metadata
    return row


def _cached_sqlite_training_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    value = metadata.get(SQLITE_TRAINING_GROUP_KEY_METADATA)
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    return (str(value[0]), str(value[1]), str(value[2]), str(value[3]))


def _streaming_row_can_trust_existing_semantics(row: Mapping[str, Any]) -> bool:
    if _trajectory_action_value_conversion_rejection_reason(row) is not None:
        return False
    if not isinstance(row.get("globalFeatureNames"), list) or not isinstance(row.get("global_"), list):
        return False
    if not isinstance(row.get("actionFeatureNames"), list) or not isinstance(row.get("actions_"), list):
        return False
    if not isinstance(row.get("cardFeatureNames"), list) or not isinstance(row.get("cards_"), list):
        return False
    if row_runtime_total_rejection_reason(
        row,
        require_explicit_mode=True,
        require_policy_provenance=True,
    ) is not None:
        return False
    return True


def _trusted_existing_semantics_report(rows: list[Mapping[str, Any]], *, source_label: str) -> dict[str, Any]:
    by_decision: dict[str, dict[str, int]] = {}
    for row in rows:
        decision = str(row.get("decisionKind") or "unknown")
        bucket = by_decision.setdefault(decision, {})
        bucket["rows"] = int(bucket.get("rows", 0)) + 1
        bucket["trustedExistingSemanticRows"] = int(bucket.get("trustedExistingSemanticRows", 0)) + 1
    return {
        "kind": "action_value_semantic_refresh_v1",
        "sourceLabel": str(source_label),
        "inputRows": int(len(rows)),
        "outputRows": int(len(rows)),
        "changedActionFeatureRows": 0,
        "changedGlobalFeatureRows": 0,
        "changedCardFeatureRows": 0,
        "unchangedRows": int(len(rows)),
        "trustedExistingSemanticRows": int(len(rows)),
        "cacheEntries": 0,
        "refreshSkippedReason": "strict_runtime_ready_row_semantics_trusted",
        "byDecisionKind": by_decision,
    }


def _empty_semantic_refresh_summary(*, source_label: str) -> dict[str, Any]:
    return {
        "kind": "action_value_semantic_refresh_v1",
        "sourceLabel": str(source_label),
        "inputRows": 0,
        "outputRows": 0,
        "changedActionFeatureRows": 0,
        "changedGlobalFeatureRows": 0,
        "changedCardFeatureRows": 0,
        "unchangedRows": 0,
        "trustedExistingSemanticRows": 0,
        "cacheEntries": 0,
        "byDecisionKind": {},
    }


def _merge_semantic_refresh_summary(summary: dict[str, Any], report: Mapping[str, Any]) -> None:
    for key in (
        "inputRows",
        "outputRows",
        "changedActionFeatureRows",
        "changedGlobalFeatureRows",
        "changedCardFeatureRows",
        "unchangedRows",
        "trustedExistingSemanticRows",
        "cacheEntries",
    ):
        summary[key] = int(summary.get(key, 0)) + int(report.get(key, 0) or 0)
    by_decision = summary.setdefault("byDecisionKind", {})
    for decision, values in _mapping(report.get("byDecisionKind")).items():
        bucket = by_decision.setdefault(str(decision), {})
        if not isinstance(values, Mapping):
            continue
        for key, value in values.items():
            bucket[str(key)] = int(bucket.get(str(key), 0)) + int(value or 0)


def _empty_action_value_trajectory_conversion_summary() -> dict[str, Any]:
    return {
        "kind": "full_legal_action_value_to_trajectory_advantage_v1",
        "inputRows": 0,
        "candidateGroups": 0,
        "convertedGroups": 0,
        "convertedRows": 0,
        "convertedRowsByDecisionKind": {},
        "skipped": {},
        "advantageMode": "action_value_minus_old_policy_expected_value",
        "oldPolicyWeighting": "softmax(row_runtime_total)",
    }


def _merge_action_value_trajectory_conversion_summary(summary: dict[str, Any], report: Mapping[str, Any]) -> None:
    for key in ("inputRows", "candidateGroups", "convertedGroups", "convertedRows"):
        summary[key] = int(summary.get(key, 0)) + int(report.get(key, 0) or 0)
    for key, value in _mapping(report.get("convertedRowsByDecisionKind")).items():
        converted_by_decision = summary.setdefault("convertedRowsByDecisionKind", {})
        converted_by_decision[str(key)] = int(converted_by_decision.get(str(key), 0)) + int(value or 0)
    for key, value in _mapping(report.get("skipped")).items():
        skipped = summary.setdefault("skipped", {})
        skipped[str(key)] = int(skipped.get(str(key), 0)) + int(value or 0)


def _training_rows_source_value(paths: list[Path]) -> dict[str, Any] | list[dict[str, Any]]:
    sources = [_training_rows_source(path) for path in paths]
    return sources[0] if len(sources) == 1 else sources


def _current_policy_training_rows_source_value(paths: list[Path]) -> dict[str, Any] | list[dict[str, Any]]:
    sources = [_current_policy_training_rows_source(path) for path in paths]
    return sources[0] if len(sources) == 1 else sources


def _training_rows_source(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in SQLITE_TRAINING_ROW_SUFFIXES:
        return {
            "kind": "sqlite_table",
            "dbPath": str(path),
            "table": SQLITE_TRAINING_ROW_TABLE,
            "rowJsonColumn": "row_json",
            "schema": "snapshot_branch_full_legal_action_value_rows_v1",
            "rowSchema": "snapshot_branch_full_legal_action_value_rows_v1",
            "tableSchema": "training_action_value_rows",
        }
    return {
        "kind": "json_array_file",
        "path": str(path),
        "compression": "gzip" if path.suffix.lower() == ".gz" else None,
        "schema": "action_value_training_rows",
    }


def _current_policy_training_rows_source(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in SQLITE_TRAINING_ROW_SUFFIXES:
        return {
            "kind": "sqlite_table",
            "dbPath": str(path),
            "table": SQLITE_TRAJECTORY_ROW_TABLE,
            "rowJsonColumn": "row_json",
            "schema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "rowSchema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "tableSchema": SQLITE_TRAJECTORY_ROW_TABLE,
        }
    return {
        "kind": "json_array_file",
        "path": str(path),
        "compression": "gzip" if path.suffix.lower() == ".gz" else None,
        "schema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
    }


def _effective_training_weight_sum(
    rows: list[Mapping[str, Any]],
    *,
    decision_training_weights: Mapping[str, float] | None = None,
) -> float:
    return float(
        sum(
            _ygo_row_training_weight(row) * _decision_training_weight(row, decision_training_weights)
            for row in rows
        )
    )


def _effective_training_weight_by_decision(
    rows: list[Mapping[str, Any]],
    *,
    decision_training_weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        decision = str(row.get("decisionKind") or "unknown")
        out[decision] = out.get(decision, 0.0) + (
            _ygo_row_training_weight(row) * _decision_training_weight(row, decision_training_weights)
        )
    return {key: float(value) for key, value in sorted(out.items())}


def _decision_training_weight(
    row: Mapping[str, Any],
    decision_training_weights: Mapping[str, float] | None,
) -> float:
    if not decision_training_weights:
        return 1.0
    decision = str(row.get("decisionKind") or "unknown")
    try:
        return float(decision_training_weights.get(decision, 1.0))
    except (TypeError, ValueError):
        return 1.0


def _filter_rows_by_target_contract(
    rows: list[dict[str, Any]],
    *,
    target_contract: str,
    allow_selected_action_fallback: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    contract = _normalize_target_contract(target_contract)
    accepted: list[dict[str, Any]] = []
    rejected_reasons: dict[str, int] = {}
    for row in rows:
        reason = _target_contract_rejection_reason(
            row,
            target_contract=contract,
            allow_selected_action_fallback=allow_selected_action_fallback,
        )
        if reason is None:
            accepted.append(row)
        else:
            rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
    return accepted, {
        "contract": contract,
        "candidateRowsBeforeContract": len(rows),
        "acceptedRows": len(accepted),
        "rejectedRows": len(rows) - len(accepted),
        "rejectedReasons": dict(sorted(rejected_reasons.items())),
    }


def _filter_rows_by_runtime_row_total_contract(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_state_group_key(row), []).append(row)
    accepted: list[dict[str, Any]] = []
    rejected_reasons: dict[str, int] = {}
    for group in grouped.values():
        reasons = [
            action_value_group_identity_rejection_reason(row)
            or row_runtime_total_rejection_reason(
                row,
                require_explicit_mode=True,
                require_policy_provenance=True,
            )
            for row in group
        ]
        reasons = [str(reason) for reason in reasons if reason is not None]
        if not reasons:
            accepted.extend(group)
            continue
        reason = sorted(set(reasons))[0]
        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
    report = _runtime_row_total_contract_report(
        rows,
        contract="row_runtime_total_required",
        accepted_rows=accepted,
        rejected_reasons=rejected_reasons,
    )
    return accepted, report


def _filter_rows_by_runtime_row_total_contract_fast(
    rows: list[dict[str, Any]],
    *,
    identity_contract: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    rejected_reasons: dict[str, int] = {}
    groups: set[tuple[str, str, str, str]] = set()
    accepted_groups: set[tuple[str, str, str, str]] = set()
    for row in rows:
        group_key = _cheap_runtime_contract_group_key(row)
        groups.add(group_key)
        reason = row_runtime_total_rejection_reason(
            row,
            require_explicit_mode=True,
            require_policy_provenance=True,
        )
        if reason is None:
            accepted.append(row)
            accepted_groups.add(group_key)
            continue
        rejected_reasons[str(reason)] = int(rejected_reasons.get(str(reason), 0)) + 1
    return accepted, {
        "contract": "row_runtime_total_required",
        "identityContract": str(identity_contract),
        "candidateRowsBeforeContract": int(len(rows)),
        "candidateStateGroupsBeforeContract": int(len(groups)),
        "acceptedRows": int(len(accepted)),
        "acceptedStateGroups": int(len(accepted_groups)),
        "rejectedRows": int(len(rows) - len(accepted)),
        "rejectedStateGroups": int(len(groups) - len(accepted_groups)),
        "rejectedReasons": dict(sorted(rejected_reasons.items())),
        "fastPath": True,
    }


def _cheap_runtime_contract_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return _state_group_key(row)


def _runtime_row_total_contract_report(
    rows: list[dict[str, Any]],
    *,
    contract: str,
    accepted_rows: list[dict[str, Any]] | None = None,
    rejected_reasons: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_state_group_key(row), []).append(row)
    if accepted_rows is None:
        accepted_rows = list(rows)
    accepted_group_keys = {_state_group_key(row) for row in accepted_rows}
    accepted_groups = len(accepted_group_keys)
    return {
        "contract": str(contract),
        "candidateRowsBeforeContract": int(len(rows)),
        "candidateStateGroupsBeforeContract": int(len(grouped)),
        "acceptedRows": int(len(accepted_rows)),
        "acceptedStateGroups": int(accepted_groups),
        "rejectedRows": int(len(rows) - len(accepted_rows)),
        "rejectedStateGroups": int(len(grouped) - accepted_groups),
        "rejectedReasons": dict(sorted((str(key), int(value)) for key, value in (rejected_reasons or {}).items())),
    }


def _target_contract_rejection_reason(
    row: Mapping[str, Any],
    *,
    target_contract: str,
    allow_selected_action_fallback: bool,
) -> str | None:
    contract = _normalize_target_contract(target_contract)
    if contract == EXPLICIT_OR_CAUSAL_TARGET_CONTRACT:
        return None
    if contract == SELECTED_FALLBACK_TARGET_CONTRACT:
        if allow_selected_action_fallback and row.get("selectedActionSlot") is not None:
            return None
        if _row_has_action_value_target_contract(row):
            return None
        return "not_selected_fallback_or_action_value"
    if _row_is_tiebreak_only_action_value(row):
        return "tiebreak_only_not_outcome_action_value"
    if _row_has_action_value_target_contract(row):
        return None
    return "not_action_value_target"


def _row_has_action_value_target_contract(row: Mapping[str, Any]) -> bool:
    if _ygo_row_has_action_value_distribution_target(row):
        return True
    if _ygo_pairwise_preference(row) is None:
        return False
    metadata = _mapping(row.get("metadata"))
    label = _mapping(row.get("freshCounterfactualLabel"))
    if bool(metadata.get("causalActionValueTrainingRow")):
        return True
    if (
        str(row.get("taskKind") or "") == "causal_alternative_rollout_value"
        and str(row.get("labelKind") or "") == "relative_value"
        and str(row.get("teacherId") or "") == "causal_forced_action_rollout"
    ):
        return True
    label_source = str(
        metadata.get("labelSource")
        or metadata.get("directFailureLabelSource")
        or row.get("labelSource")
        or label.get("labelSource")
        or ""
    )
    return label_source in ACTION_VALUE_LABEL_SOURCES


def _row_is_tiebreak_only_action_value(row: Mapping[str, Any]) -> bool:
    label = _mapping(row.get("label"))
    outcome_gap = _float_or_none(label.get("outcomeValueGap"))
    if outcome_gap is None:
        return False
    if abs(float(outcome_gap)) >= DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING:
        return False
    if _row_is_full_legal_action_value_group(row):
        value_spread = _full_legal_value_spread(row)
        if value_spread is not None and abs(float(value_spread)) >= DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING:
            return False
    tiebreak_gap = _float_or_none(label.get("tiebreakValueGap"))
    value_gap = _float_or_none(label.get("valueGap"))
    fresh_label = _mapping(row.get("freshCounterfactualLabel"))
    fresh_gap = _float_or_none(fresh_label.get("freshValueGap") or fresh_label.get("valueGap"))
    return any(
        gap is not None and abs(float(gap)) >= DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING
        for gap in (tiebreak_gap, value_gap, fresh_gap)
    )


def _row_is_full_legal_action_value_group(row: Mapping[str, Any]) -> bool:
    metadata = _mapping(row.get("metadata"))
    label = _mapping(row.get("label"))
    return (
        str(row.get("schema") or "") == "snapshot_branch_full_legal_action_value_rows_v1"
        or bool(metadata.get("fullLegalActionSetGroup"))
        or bool(label.get("fullLegalActionSetGroupId"))
    )


def _full_legal_value_spread(row: Mapping[str, Any]) -> float | None:
    label = _mapping(row.get("label"))
    value = _float_or_none(label.get("valueSpread"))
    if value is not None:
        return value
    fresh_label = _mapping(row.get("freshCounterfactualLabel"))
    for key in ("outcomeValueGap", "freshValueGap", "valueGap"):
        value = _float_or_none(fresh_label.get(key))
        if value is not None:
            return value
    return None


def _reject_full_legal_rows_for_pairwise_training(rows: list[Mapping[str, Any]]) -> None:
    if any(_row_is_full_legal_action_value_group(row) for row in rows):
        raise ValueError(
            "full-legal action-set rows require action_value_listwise training; "
            "legacy pairwise training is not a full legal action-set objective"
        )


def _normalize_target_contract(target_contract: str) -> str:
    contract = str(target_contract or ACTION_VALUE_TARGET_CONTRACT).strip()
    if contract not in TARGET_CONTRACT_CHOICES:
        raise ValueError(
            f"unknown target contract {contract!r}; expected one of {', '.join(TARGET_CONTRACT_CHOICES)}"
        )
    return contract


def _training_objective_for_contract(target_contract: str) -> str:
    contract = _normalize_target_contract(target_contract)
    if contract == ACTION_VALUE_TARGET_CONTRACT:
        return "same_state_action_value"
    if contract == SELECTED_FALLBACK_TARGET_CONTRACT:
        return "selected_action_teacher_clone_opt_in"
    return "explicit_or_causal_diagnostic"


def _raise_no_usable_rows(
    *,
    mode: str,
    candidate_rows: int,
    target_contract_report: Mapping[str, Any],
) -> None:
    if candidate_rows and int(target_contract_report.get("acceptedRows", 0) or 0) == 0:
        raise ValueError(
            f"ygo-style {mode} training requires at least one row passing the "
            f"{target_contract_report.get('contract')} action-value target contract; "
            f"rejected={target_contract_report.get('rejectedReasons')}"
        )
    raise ValueError(f"ygo-style {mode} training requires at least one usable {mode} row")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalized_anchor_kl_decision_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    if not weights:
        return {}
    out: dict[str, float] = {}
    for key, value in weights.items():
        name = str(key).strip()
        if not name:
            continue
        out[name] = max(0.0, float(value))
    return dict(sorted(out.items()))


def _parse_anchor_kl_decision_weights(text: str | None) -> dict[str, float]:
    if not text:
        return {}
    out: dict[str, float] = {}
    for part in str(text).split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"invalid anchor decision weight {item!r}; expected decision=value")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError("invalid anchor decision weight with empty decision name")
        out[name] = max(0.0, float(value))
    return dict(sorted(out.items()))


def _parse_row_file_weights(text: str | None) -> list[float] | None:
    if not text:
        return None
    return [max(0.0, float(part.strip())) for part in str(text).split(",") if part.strip()]


def _parse_training_rows_args(values: Iterable[str | Path] | str | Path | None) -> list[str]:
    if values is None:
        return []
    raw_values = [values] if isinstance(values, (str, Path)) else list(values)
    out: list[str] = []
    for value in raw_values:
        for part in str(value).replace(";", ",").split(","):
            item = part.strip()
            if item:
                out.append(item)
    return out


def _cli_flag_present(argv: Iterable[str], flag: str) -> bool:
    return any(str(item) == flag or str(item).startswith(f"{flag}=") for item in argv)


def _split_rows(
    rows: list[dict[str, Any]],
    *,
    eval_fraction: float,
    shuffle: bool = False,
    seed: int = 2026061340,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bounded = max(0.0, min(0.9, float(eval_fraction)))
    eval_count = int(round(len(rows) * bounded))
    ordered = list(rows)
    if bool(shuffle):
        rng = random.Random(int(seed))
        rng.shuffle(ordered)
    if eval_count <= 0:
        return ordered, []
    return ordered[:-eval_count], ordered[-eval_count:]


def _split_rows_by_state_group(
    rows: list[dict[str, Any]],
    *,
    eval_fraction: float,
    shuffle: bool = False,
    seed: int = 2026061340,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bounded = max(0.0, min(0.9, float(eval_fraction)))
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_state_group_key(row), []).append(row)
    groups_by_decision: dict[str, list[list[dict[str, Any]]]] = {}
    for key in sorted(grouped):
        groups_by_decision.setdefault(str(key[2]), []).append(grouped[key])
    if bool(shuffle):
        rng = random.Random(int(seed))
        for groups in groups_by_decision.values():
            rng.shuffle(groups)
    train_groups: list[list[dict[str, Any]]] = []
    eval_groups: list[list[dict[str, Any]]] = []
    for _decision, groups in sorted(groups_by_decision.items()):
        if bounded <= 0.0 or len(groups) <= 1:
            train_groups.extend(groups)
            continue
        eval_count = max(1, int(round(len(groups) * bounded)))
        eval_count = min(eval_count, len(groups) - 1)
        train_groups.extend(groups[:-eval_count])
        eval_groups.extend(groups[-eval_count:])
    return (
        [row for group in train_groups for row in group],
        [row for group in eval_groups for row in group],
    )


def _split_rows_by_cheap_runtime_group(
    rows: list[dict[str, Any]],
    *,
    eval_fraction: float,
    shuffle: bool = False,
    seed: int = 2026061340,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bounded = max(0.0, min(0.9, float(eval_fraction)))
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_cheap_runtime_contract_group_key(row), []).append(row)
    groups_by_decision: dict[str, list[list[dict[str, Any]]]] = {}
    for key in sorted(grouped):
        groups_by_decision.setdefault(str(key[2] or "unknown"), []).append(grouped[key])
    if bool(shuffle):
        rng = random.Random(int(seed))
        for groups in groups_by_decision.values():
            rng.shuffle(groups)
    train_groups: list[list[dict[str, Any]]] = []
    eval_groups: list[list[dict[str, Any]]] = []
    for _decision, groups in sorted(groups_by_decision.items()):
        if bounded <= 0.0 or len(groups) <= 1:
            train_groups.extend(groups)
            continue
        eval_count = max(1, int(round(len(groups) * bounded)))
        eval_count = min(eval_count, len(groups) - 1)
        train_groups.extend(groups[:-eval_count])
        eval_groups.extend(groups[-eval_count:])
    return (
        [row for group in train_groups for row in group],
        [row for group in eval_groups for row in group],
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a ygo-style masked card/action policy scorer from causal action rows.")
    parser.add_argument(
        "--training-rows",
        required=True,
        action="append",
        help=(
            "Training row file or SQLite DB. Repeat for multiple sources, or pass a comma/semicolon "
            "separated list; weights must match the flattened source count."
        ),
    )
    parser.add_argument(
        "--training-row-file-weights",
        default="",
        help="Comma-separated weights matching --training-rows order, e.g. 0.1,3,2.",
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--candidate-model-id")
    parser.add_argument(
        "--actor-policy-id",
        help="For current-policy modes: actor_N policy id recorded in current-policy rows, or actor_0 id for bootstrap.",
    )
    parser.add_argument(
        "--bootstrap-source-policy-id",
        help="For --training-mode current_policy_bootstrap: verified runtime policy id that produced the strict rows.",
    )
    parser.add_argument(
        "--bootstrap-clone-epochs",
        type=int,
        default=1,
        help="For --training-mode current_policy_bootstrap: V137 row_runtime_total distillation epochs.",
    )
    parser.add_argument(
        "--bootstrap-target-source",
        choices=("runtime_total", "runtime_argmax"),
        default="runtime_total",
        help="For current_policy_bootstrap: distill V137 runtime scores or runtime argmax.",
    )
    parser.add_argument(
        "--base-preserving-base-policy-id",
        default="",
        help="Deprecated diagnostic flag; current_policy/current_policy_bootstrap reject base-preserving exports.",
    )
    parser.add_argument(
        "--base-preserving-delta-score-weight",
        type=float,
        default=1.0,
        help="Deprecated diagnostic flag; current_policy/current_policy_bootstrap reject base-preserving exports.",
    )
    parser.add_argument(
        "--base-preserving-delta-override-margin",
        type=float,
        default=0.0,
        help="Deprecated diagnostic flag; current_policy/current_policy_bootstrap reject base-preserving exports.",
    )
    parser.add_argument(
        "--training-mode",
        choices=[
            "pairwise",
            "action_value_listwise",
            "trajectory_advantage_runtime",
            "sandbox_policy_value",
            "current_policy_bootstrap",
            "current_policy",
            "direct_policy",
            "outcome_policy",
        ],
        required=True,
    )
    parser.add_argument("--base-model-path")
    parser.add_argument("--epochs", type=int, default=YGO_DEFAULT_UPDATE_EPOCHS)
    parser.add_argument("--learning-rate", type=float, default=None)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--margin", type=float, default=1.0)
    parser.add_argument("--max-margin", type=float, default=4.0)
    parser.add_argument("--eval-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=2026061340)
    parser.add_argument("--shuffle-rows", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--include-decision-kind",
        action="append",
        default=[],
        help=(
            "For action_value_listwise or trajectory_advantage_runtime, train/evaluate only rows "
            "with this decisionKind. Requires either --allow-route-isolated-diagnostic-training "
            "or --allow-route-limited-launch-training."
        ),
    )
    parser.add_argument(
        "--allow-route-isolated-diagnostic-training",
        action="store_true",
        help=(
            "Diagnostic opt-in only: allow --include-decision-kind route isolation. "
            "Default rejects route-isolated training so candidates stay aligned with a single YGO-style scorer."
        ),
    )
    parser.add_argument(
        "--allow-route-limited-launch-training",
        action="store_true",
        help=(
            "Allow --include-decision-kind for a launch candidate only when protected runtime "
            "decision kinds are a subset of the included decision kinds. Preflight enforces the subset."
        ),
    )
    parser.add_argument(
        "--decision-training-weights",
        default="",
        help="Comma-separated direct-policy CE decision multipliers, e.g. main=3,mana=2.",
    )
    parser.add_argument("--anchor-kl-weight", type=float, default=0.0)
    parser.add_argument("--anchor-kl-temperature", type=float, default=1.0)
    parser.add_argument(
        "--retention-kl-mode",
        choices=(
            "disabled",
            "selective_original_nonpositive_advantage",
            "selective_original_nonpositive_advantage_nonupweighted",
        ),
        default="disabled",
        help=(
            "Current-policy PPO only: restrict source-actor KL retention to selected row domains "
            "instead of applying a global anchor."
        ),
    )
    parser.add_argument(
        "--anchor-kl-decision-weights",
        default="",
        help="Comma-separated decision multipliers for direct-policy anchor KL, e.g. main=30,mana=15,flash=0.",
    )
    parser.add_argument(
        "--allow-selected-action-fallback",
        action="store_true",
        help="Opt in to treating selectedActionSlot-only teacher rows as direct-policy targets.",
    )
    parser.add_argument(
        "--direct-policy-target-mode",
        choices=DIRECT_POLICY_TARGET_MODES,
        default=DIRECT_POLICY_TARGET_MODE_PREFERRED_SLOT_CE,
        help=(
            "Direct-policy loss target. preferred_slot_ce is the historical hard target; "
            "action_value_distribution trains from same-state known action values."
        ),
    )
    parser.add_argument("--action-value-temperature", type=float, default=0.25)
    parser.add_argument(
        "--runtime-aux-score-weight",
        type=float,
        default=None,
        help="For action_value_listwise, train the sidecar against base + weight * sidecar runtime logits.",
    )
    parser.add_argument(
        "--runtime-aux-output-scale",
        type=float,
        default=None,
        help=(
            "For runtime action_value_listwise, serialize a fixed sidecar output scale. "
            "Defaults to 1/runtimeAuxScoreWeight so one raw sidecar unit is one residual unit."
        ),
    )
    parser.add_argument(
        "--runtime-aux-training-objective",
        choices=RUNTIME_AUX_TRAINING_OBJECTIVES,
        default=RUNTIME_AUX_TRAINING_OBJECTIVE_VALUE_DISTRIBUTION,
        help="For runtime action_value_listwise, choose whether to train all groups or only base-wrong groups.",
    )
    parser.add_argument(
        "--preserve-correct-residual-l2-weight",
        type=float,
        default=None,
        help=(
            "For runtime preserve-correct objectives, explicit residual L2 weight on base-correct rows. "
            "Omit to use the objective default."
        ),
    )
    parser.add_argument(
        "--preserve-correct-margin-hinge-weight",
        type=float,
        default=None,
        help=(
            "For runtime preserve-correct objectives, explicit margin-preservation hinge weight on base-correct rows. "
            "Omit to use the objective default."
        ),
    )
    parser.add_argument(
        "--preserve-correct-margin-floor",
        type=float,
        default=None,
        help=(
            "For runtime preserve-correct objectives, required base-correct safety margin after capping by the "
            "original base margin. Omit to use the objective default."
        ),
    )
    parser.add_argument(
        "--allow-scorer-runtime-base-fallback",
        action="store_true",
        help=(
            "Diagnostic opt-in only: allow runtime action_value_listwise rows without recorded row runtime total "
            "to fall back to the base scorer. Default filters them out so training, eval, and gate preflight use "
            "the same recorded runtime totals."
        ),
    )
    parser.add_argument(
        "--entropy-coef",
        type=float,
        default=None,
        help=(
            "Entropy coefficient. trajectory_advantage_runtime defaults to 0.0 because it is an "
            "offline protected residual sidecar; legacy outcome/direct policy modes default to 0.01."
        ),
    )
    parser.add_argument("--value-loss-weight", type=float, default=0.25)
    parser.add_argument(
        "--policy-temperature",
        type=float,
        default=0.5,
        help="For sandbox_policy_value, softmax temperature for action-value policy-improvement targets.",
    )
    parser.add_argument(
        "--high-gap-ranking-weight",
        type=float,
        default=0.25,
        help="For sandbox_policy_value, extra ranking loss weight for high-gap action pairs.",
    )
    parser.add_argument(
        "--high-gap-threshold",
        type=float,
        default=DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
        help="For sandbox_policy_value, minimum action-value gap for the extra ranking loss.",
    )
    parser.add_argument("--ppo-clip-coef", type=float, default=0.2)
    parser.add_argument(
        "--full-legal-policy-objective",
        choices=sorted(FULL_LEGAL_POLICY_OBJECTIVES),
        default=FULL_LEGAL_POLICY_OBJECTIVE_SEARCH_IMPROVED_CE,
        help=(
            "For trajectory_advantage_runtime rows converted from full-legal action values. "
            "Default uses a base-prior search-improved full-legal CE target. "
            "The pure search-value CE remains an explicit diagnostic; PPO is only valid for true sampled trajectories."
        ),
    )
    parser.add_argument("--policy-improvement-temperature", type=float, default=1.0)
    parser.add_argument(
        "--base-correct-preserve-weight",
        type=float,
        default=FULL_LEGAL_SEARCH_IMPROVED_BASE_CORRECT_PRESERVE_WEIGHT,
        help=(
            "For search_improved_policy_ce on converted full-legal groups, penalize lowering the old "
            "runtime top probability when that old top is also an outcome-best slot."
        ),
    )
    parser.add_argument("--normalize-advantages", action="store_true")
    parser.add_argument(
        "--advantage-normalization-mode",
        choices=("scale_only", "global", "matchup_bucket"),
        default="scale_only",
    )
    parser.add_argument(
        "--domain-gradient-conflict-mode",
        choices=(
            "disabled",
            "pcgrad_coarse_policy_only",
            "pcgrad_action_signature_sign_policy_only",
            "pcgrad_action_family_sign_policy_only",
            "pcgrad_advantage_sign_policy_only",
        ),
        default="disabled",
        help=(
            "Current-policy PPO diagnostic/experiment: optionally project conflicting "
            "coarse-domain or action-signature/sign actor gradients."
        ),
    )
    parser.add_argument(
        "--functional-logit-oracle-mode",
        choices=("disabled", "centered_delta_scan"),
        default="disabled",
        help=(
            "Diagnostic-only current-policy audit: scan legal-set-centered per-row logit deltas "
            "without exporting or relying on a production actor update."
        ),
    )
    parser.add_argument(
        "--actor-linearized-representability-mode",
        choices=(
            "disabled",
            "actor_linearized_last_layer",
            "actor_linearized_full",
            "last_layer_and_full_scan",
            "actor_linearized_full_jacobian_cg",
            "last_layer_and_full_jacobian_scan",
            "projected_legal_logit_cg_update",
        ),
        default="disabled",
        help=(
            "Diagnostic-only current-policy audit: temporarily project the functional legal-logit "
            "target through actor parameters, report movement, then restore parameters unless the "
            "explicit projected_legal_logit_cg_update repair-proof mode is selected."
        ),
    )
    parser.add_argument(
        "--actor-linearized-cg-max-iterations",
        type=int,
        default=64,
        help="Maximum strict actor-Jacobian CG iterations for actor-linearized modes.",
    )
    parser.add_argument(
        "--actor-linearized-optimizer-diagnostics",
        choices=("full", "projected_update_only"),
        default="full",
        help=(
            "full keeps PPO-gradient decomposition diagnostics; projected_update_only skips "
            "optimizer-realization replay after the CG line-search and is intended for speed probes."
        ),
    )
    parser.add_argument(
        "--multi-domain-objective-mode",
        choices=("disabled", "original48_cvar"),
        default="disabled",
        help="Current-policy PPO experiment: optimize original48 domains as constrained worst-domain slices.",
    )
    parser.add_argument(
        "--recurrent-training-mode",
        choices=("disabled", "gru_domain_v1"),
        default="disabled",
        help="Enable the minimal domain-conditioned GRU actor/value V2 training path for current-policy PPO.",
    )
    parser.add_argument(
        "--current-policy-actor-advantage-mode",
        choices=(
            "gae",
            "gae_upgo",
            "mc_return",
            "mc_return_decay",
            "mc_sign_preserving_gae",
            "local_step_reward",
            "learner_current_value_gae",
            "learner_vtrace",
        ),
        default="gae",
        help=(
            "Actor-loss advantage source for sampled current-policy PPO. "
            "gae keeps old behavior; mc_return/sign_preserving modes diagnose critic-sign drift; "
            "local_step_reward uses rollout local reward for actor loss only; "
            "learner_current_value_gae recomputes actor advantage from the learner's current value head; "
            "learner_vtrace computes a learner-side V-trace advantage for fixed-batch diagnostics."
        ),
    )
    parser.add_argument(
        "--current-policy-local-step-reward-weight",
        type=float,
        default=0.0,
        help="Optional shaping weight that adds rollout localStepReward into the GAE step reward; default 0 keeps terminal-only GAE.",
    )
    parser.add_argument(
        "--detach-value-loss-recurrent-context",
        action="store_true",
        help=(
            "For recurrent current-policy PPO, stop value loss from updating the shared recurrent context. "
            "This keeps actor/value heads in one checkpoint while matching YGO's separated actor/critic recurrent state."
        ),
    )
    parser.add_argument(
        "--critic-warmup-epochs",
        type=int,
        default=None,
        help="Override current-policy critic warmup epochs; default keeps the existing GAE-aware auto rule.",
    )
    parser.add_argument(
        "--no-critic-warmup-recompute-advantage",
        action="store_true",
        help="Warm the critic/value head but keep the rollout actor advantage tensor unchanged.",
    )
    parser.add_argument(
        "--decision-residual-policy-mode",
        choices=("disabled", "linear_v1"),
        default="disabled",
        help="Enable a same-checkpoint per-decision linear actor residual head for current-policy PPO.",
    )
    parser.add_argument("--actor-update-requires-trusted-value", action="store_true")
    parser.add_argument("--actor-trusted-value-ev-threshold", type=float, default=0.0)
    parser.add_argument("--selfplay-actor-loss-cap-fraction", type=float, default=1.0)
    parser.add_argument("--original-terminal-actor-loss-min-fraction", type=float, default=0.0)
    parser.add_argument("--actor-loss-max-rows-per-domain", type=int, default=0)
    parser.add_argument("--actor-loss-min-abs-advantage", type=float, default=0.0)
    parser.add_argument(
        "--actor-loss-advantage-sign-filter",
        choices=("disabled", "positive", "negative"),
        default="disabled",
        help="Diagnostic current-policy PPO option: update actor only from one advantage sign.",
    )
    parser.add_argument(
        "--actor-loss-label-consistency-mode",
        choices=(
            "disabled",
            "gae_mc_agree",
            "gae_mc_local_agree",
            "gae_mc_excluded",
            "gae_local_agree",
            "gae_local_excluded",
            "unshaped_gae_local_agree",
            "drop_positive_local_negative_advantage",
            "drop_positive_local_negative_unshaped_gae",
            "drop_counter_signal_advantage",
        ),
        default="disabled",
        help="Diagnostic current-policy PPO option: filter actor rows by GAE/MC/local reward sign consistency.",
    )
    parser.add_argument("--actor-loss-label-consistency-min-abs-advantage", type=float, default=0.0)
    parser.add_argument(
        "--actor-loss-counter-signal-conflict-weight",
        type=float,
        default=1.0,
        help="Default-off actor loss multiplier for rows where GAE conflicts with MC/local signs; 0 makes them critic-only.",
    )
    parser.add_argument(
        "--actor-advantage-source",
        choices=(
            "gae",
            "action_q_residual_v1",
            "sampled_action_residual_v1",
            "sampled_mean_centered_action_residual_v1",
        ),
        default="gae",
        help=(
            "Learner actor advantage source. action_q_residual_v1 keeps selected-logprob PPO ratio "
            "and uses centered action-Q residual advantages; sampled_action_residual_v1 uses selectedRaw "
            "with Q-fit readiness gates; sampled_mean_centered_action_residual_v1 trains "
            "selectedRaw - mean_legal(raw) for fixed-batch D0 diagnostics."
        ),
    )
    parser.add_argument("--action-q-residual-loss-weight", type=float, default=1.0)
    parser.add_argument(
        "--q-backed-actor-residual-transfer-mode",
        choices=(
            "disabled",
            "frozen_no_step_v1",
            "correction_step_v1",
            "oracle_functional_correction_v1",
            "anchor_preserving_oracle_functional_correction_v1",
            "anchor_preserving_correction_step_v1",
            "functional_temporal_delta_q_backed_single_residual_v1",
        ),
        default="disabled",
        help=(
            "Fixed-batch D2 diagnostic: after sampled mean-centered Q readiness, feed "
            "mean_legal-centered all-legal Q residuals through the actor residual scoring path "
            "without running PPO, run an E0 diagnostic-only functional logit correction, "
            "run an E1-P D2-anchor-preserving parametric residual correction, or run the "
            "q-backed single-carrier continuation contract."
        ),
    )
    parser.add_argument(
        "--actor-loss-relative-mode",
        choices=("selected_logprob",),
        default="selected_logprob",
        help="Actor PPO objective basis. selected-vs-top margin is audit-only, not a PPO ratio.",
    )
    parser.add_argument(
        "--actor-loss-group-mode",
        choices=("disabled", "turn_phase_window_sum"),
        default="disabled",
        help="Diagnostic current-policy PPO option: group selected-action logprobs by turn/phase window.",
    )
    parser.add_argument(
        "--actor-legal-margin-weight",
        type=float,
        default=0.0,
        help=(
            "Default-off PPO auxiliary: move sampled action raw score relative to the other legal "
            "actions according to the sampled row advantage."
        ),
    )
    parser.add_argument(
        "--state-action-interaction-mode",
        choices=(
            "disabled",
            "low_rank_v1",
            "low_rank_v2",
            "low_rank_v3",
            "full_cross_v1",
            "full_cross_recurrent_v1",
            "mlp_refdelta_v1",
            "mlp_recurrent_refdelta_v1",
            "prior_free_legal_ranker_v1",
            "prior_free_recurrent_legal_ranker_v1",
            "legal_set_context_ranker_v1",
            "legal_set_recurrent_context_ranker_v1",
            "legal_set_delta_ranker_v1",
            "signature_state_linear_v1",
            "signature_mlp_delta_v1",
            "signature_low_rank_delta_v1",
            "signature_full_cross_delta_v1",
        ),
        default="disabled",
        help="Default-off actor head: add a state-action interaction residual/delta to masked logits.",
    )
    parser.add_argument("--state-action-interaction-rank", type=int, default=16)
    parser.add_argument("--state-action-interaction-init-scale", type=float, default=0.01)
    parser.add_argument("--state-action-interaction-lr-multiplier", type=float, default=1.0)
    parser.add_argument("--actor-base-lr-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--actor-signature-drift-penalty-weight",
        type=float,
        default=0.0,
        help=(
            "Default-off PPO regularizer: penalize mean selected-logprob drift inside mixed-sign "
            "action signatures so action-family priors do not dominate state-conditioned credit."
        ),
    )
    parser.add_argument(
        "--actor-signature-contrastive-weight",
        type=float,
        default=0.0,
        help=(
            "Default-off PPO auxiliary: within each mixed-sign action signature, encourage "
            "positive-GAE selected-logprob deltas to exceed negative-GAE deltas."
        ),
    )
    parser.add_argument(
        "--actor-loss-sign-balance-mode",
        choices=("disabled", "global", "decision_kind", "action_signature", "action_family"),
        default="disabled",
        help="Diagnostic current-policy PPO option: preserve advantage signs but balance positive/negative actor loss weight.",
    )
    parser.add_argument(
        "--actor-loss-sequential-sign-steps",
        action="store_true",
        help="Diagnostic current-policy PPO option: run positive-advantage and negative-advantage actor steps separately inside each minibatch.",
    )
    parser.add_argument(
        "--actor-gradient-collision-audit-mode",
        choices=("disabled", "action_signature", "parameter_isolation"),
        default="disabled",
        help="Diagnostic-only dry-run audit: compare positive/negative actor gradients inside one action signature.",
    )
    parser.add_argument("--terminal-untrusted-actor-loss-max-steps-from-terminal", type=int, default=-1)
    parser.add_argument("--device", default="auto", help="PyTorch device for training: auto, cpu, cuda, cuda:0, ...")
    parser.add_argument("--restart-safety-review", type=Path, default=None)
    parser.add_argument("--allow-unreviewed-restart", action="store_true")
    parser.add_argument(
        "--allow-missing-play-card-target-semantics",
        action="store_true",
        help=(
            "Diagnostic opt-in only: allow target-sensitive play_card rows that lack explicit effect targets. "
            "Default rejects them because cast card and target choice are different decisions."
        ),
    )
    parser.add_argument(
        "--expected-runtime-policy-id",
        default=None,
        help=(
            "For trajectory_advantage_runtime, require row runtime-total provenance to match this active "
            "runtime policy id. Defaults to --base-model-path modelId when available."
        ),
    )
    parser.add_argument(
        "--target-contract",
        choices=TARGET_CONTRACT_CHOICES,
        default=ACTION_VALUE_TARGET_CONTRACT,
        help=(
            "Training target contract. Default action_value accepts only outcome-grounded "
            "same-state/action-value rows; use explicit_or_causal or selected_fallback_opt_in "
            "only for diagnostics."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(raw_argv)
    if args.training_mode in {"direct_policy", "outcome_policy"}:
        raise ValueError(FULL_DIRECT_TRAINING_SUSPENDED_MESSAGE)
    if args.training_mode not in {"current_policy", "current_policy_bootstrap"} and not str(
        args.candidate_model_id or ""
    ).strip():
        raise ValueError("--candidate-model-id is required unless --training-mode current_policy/current_policy_bootstrap")
    if args.training_mode in {"current_policy", "current_policy_bootstrap"}:
        if _cli_flag_present(raw_argv, "--candidate-model-id"):
            raise ValueError("--candidate-model-id is derived for current-policy modes and must not be provided")
        if _cli_flag_present(raw_argv, "--epochs"):
            raise ValueError("--epochs is locked to 1 for current-policy modes and must not be provided")
        for flag in (
            "--base-preserving-base-policy-id",
            "--base-preserving-delta-score-weight",
            "--base-preserving-delta-override-margin",
        ):
            if _cli_flag_present(raw_argv, flag):
                raise ValueError(f"{flag} is diagnostic-only and not allowed for ygo-style direct actor training")
    training_rows_path = _parse_training_rows_args(args.training_rows)
    training_row_file_weights = _parse_row_file_weights(args.training_row_file_weights)
    decision_training_weights = _parse_anchor_kl_decision_weights(args.decision_training_weights)
    anchor_kl_decision_weights = _parse_anchor_kl_decision_weights(args.anchor_kl_decision_weights)
    legacy_learning_rate = (
        YGO_DEFAULT_LEARNING_RATE
        if args.learning_rate is None
        else float(args.learning_rate)
    )
    if args.training_mode == "current_policy":
        actor_policy_id = str(args.actor_policy_id or "").strip()
        if not actor_policy_id:
            raise ValueError("--actor-policy-id is required for --training-mode current_policy")
        report = run_ygo_style_current_policy_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            actor_policy_id=actor_policy_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            update_epochs=1,
            learning_rate=legacy_learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            decision_training_weights=decision_training_weights,
            policy_temperature=float(args.policy_temperature),
            ppo_clip_coef=float(args.ppo_clip_coef),
            value_loss_weight=float(args.value_loss_weight),
            high_gap_ranking_weight=float(args.high_gap_ranking_weight),
            high_gap_threshold=float(args.high_gap_threshold),
            anchor_kl_weight=float(args.anchor_kl_weight),
            anchor_kl_temperature=float(args.anchor_kl_temperature),
            retention_kl_mode=str(args.retention_kl_mode),
            domain_gradient_conflict_mode=str(args.domain_gradient_conflict_mode),
            multi_domain_objective_mode=str(args.multi_domain_objective_mode),
            recurrent_training_mode=str(args.recurrent_training_mode),
            decision_residual_policy_mode=str(args.decision_residual_policy_mode),
            state_action_interaction_mode=str(args.state_action_interaction_mode),
            state_action_interaction_rank=int(args.state_action_interaction_rank),
            state_action_interaction_init_scale=float(args.state_action_interaction_init_scale),
            state_action_interaction_lr_multiplier=float(args.state_action_interaction_lr_multiplier),
            actor_base_lr_multiplier=float(args.actor_base_lr_multiplier),
            current_policy_actor_advantage_mode=str(args.current_policy_actor_advantage_mode),
            current_policy_local_step_reward_weight=float(args.current_policy_local_step_reward_weight),
            detach_value_loss_recurrent_context=bool(args.detach_value_loss_recurrent_context),
            critic_warmup_epochs=args.critic_warmup_epochs,
            critic_warmup_recompute_advantage=not bool(args.no_critic_warmup_recompute_advantage),
            actor_update_requires_trusted_value=bool(args.actor_update_requires_trusted_value),
            actor_trusted_value_ev_threshold=float(args.actor_trusted_value_ev_threshold),
            selfplay_actor_loss_cap_fraction=float(args.selfplay_actor_loss_cap_fraction),
            original_terminal_actor_loss_min_fraction=float(args.original_terminal_actor_loss_min_fraction),
            actor_loss_max_rows_per_domain=int(args.actor_loss_max_rows_per_domain),
            actor_loss_sign_balance_mode=str(args.actor_loss_sign_balance_mode),
            actor_loss_sequential_sign_steps=bool(args.actor_loss_sequential_sign_steps),
            actor_loss_min_abs_advantage=float(args.actor_loss_min_abs_advantage),
            actor_loss_advantage_sign_filter=str(args.actor_loss_advantage_sign_filter),
            actor_loss_label_consistency_mode=str(args.actor_loss_label_consistency_mode),
            actor_loss_label_consistency_min_abs_advantage=float(args.actor_loss_label_consistency_min_abs_advantage),
            actor_loss_counter_signal_conflict_weight=float(args.actor_loss_counter_signal_conflict_weight),
            actor_advantage_source=str(args.actor_advantage_source),
            q_backed_actor_residual_transfer_mode=str(args.q_backed_actor_residual_transfer_mode),
            action_q_residual_loss_weight=float(args.action_q_residual_loss_weight),
            actor_loss_relative_mode=str(args.actor_loss_relative_mode),
            actor_loss_group_mode=str(args.actor_loss_group_mode),
            actor_legal_margin_weight=float(args.actor_legal_margin_weight),
            actor_signature_drift_penalty_weight=float(args.actor_signature_drift_penalty_weight),
            actor_signature_contrastive_weight=float(args.actor_signature_contrastive_weight),
            actor_gradient_collision_audit_mode=str(args.actor_gradient_collision_audit_mode),
            functional_logit_oracle_mode=str(args.functional_logit_oracle_mode),
            actor_linearized_representability_mode=str(args.actor_linearized_representability_mode),
            actor_linearized_cg_max_iterations=int(args.actor_linearized_cg_max_iterations),
            actor_linearized_optimizer_diagnostics=str(args.actor_linearized_optimizer_diagnostics),
            terminal_untrusted_actor_loss_max_steps_from_terminal=int(args.terminal_untrusted_actor_loss_max_steps_from_terminal),
            normalize_advantages=bool(args.normalize_advantages),
            advantage_normalization_mode=str(args.advantage_normalization_mode),
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(args.allow_missing_play_card_target_semantics),
        )
    elif args.training_mode == "current_policy_bootstrap":
        actor_policy_id = str(args.actor_policy_id or "").strip()
        source_policy_id = str(args.bootstrap_source_policy_id or "").strip()
        if not actor_policy_id:
            raise ValueError("--actor-policy-id is required for --training-mode current_policy_bootstrap")
        if not source_policy_id:
            raise ValueError("--bootstrap-source-policy-id is required for --training-mode current_policy_bootstrap")
        report = run_ygo_style_current_policy_bootstrap_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            actor_policy_id=actor_policy_id,
            bootstrap_source_policy_id=source_policy_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            update_epochs=int(args.bootstrap_clone_epochs),
            learning_rate=legacy_learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            decision_training_weights=decision_training_weights,
            policy_temperature=float(args.policy_temperature),
            value_loss_weight=float(args.value_loss_weight),
            high_gap_ranking_weight=float(args.high_gap_ranking_weight),
            high_gap_threshold=float(args.high_gap_threshold),
            anchor_kl_weight=float(args.anchor_kl_weight),
            anchor_kl_temperature=float(args.anchor_kl_temperature),
            bootstrap_target_source=str(args.bootstrap_target_source),
            base_preserving_base_policy_id=str(args.base_preserving_base_policy_id or ""),
            base_preserving_delta_score_weight=float(args.base_preserving_delta_score_weight),
            base_preserving_delta_override_margin=float(args.base_preserving_delta_override_margin),
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(args.allow_missing_play_card_target_semantics),
        )
    elif args.training_mode == "action_value_listwise":
        report = run_ygo_style_action_value_listwise_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            candidate_model_id=args.candidate_model_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            shuffle_rows=bool(args.shuffle_rows),
            include_decision_kinds=args.include_decision_kind,
            allow_route_isolated_diagnostic_training=bool(args.allow_route_isolated_diagnostic_training),
            allow_route_limited_launch_training=bool(args.allow_route_limited_launch_training),
            decision_training_weights=decision_training_weights,
            anchor_kl_weight=float(args.anchor_kl_weight),
            anchor_kl_temperature=float(args.anchor_kl_temperature),
            anchor_kl_decision_weights=anchor_kl_decision_weights,
            target_contract=str(args.target_contract),
            action_value_temperature=float(args.action_value_temperature),
            runtime_aux_score_weight=args.runtime_aux_score_weight,
            runtime_aux_output_scale=(
                None if args.runtime_aux_output_scale is None else float(args.runtime_aux_output_scale)
            ),
            runtime_aux_training_objective=str(args.runtime_aux_training_objective),
            preserve_correct_residual_l2_weight=args.preserve_correct_residual_l2_weight,
            preserve_correct_margin_hinge_weight=args.preserve_correct_margin_hinge_weight,
            preserve_correct_margin_floor=args.preserve_correct_margin_floor,
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(args.allow_missing_play_card_target_semantics),
            allow_scorer_runtime_base_fallback=bool(args.allow_scorer_runtime_base_fallback),
        )
    elif args.training_mode == "trajectory_advantage_runtime":
        trajectory_entropy_coef = (
            YGO_TRAJECTORY_RUNTIME_DEFAULT_ENTROPY_COEF
            if args.entropy_coef is None
            else float(args.entropy_coef)
        )
        report = run_ygo_style_trajectory_advantage_runtime_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            candidate_model_id=args.candidate_model_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            shuffle_rows=bool(args.shuffle_rows),
            include_decision_kinds=args.include_decision_kind,
            allow_route_isolated_diagnostic_training=bool(args.allow_route_isolated_diagnostic_training),
            allow_route_limited_launch_training=bool(args.allow_route_limited_launch_training),
            decision_training_weights=decision_training_weights,
            runtime_aux_score_weight=(
                0.03 if args.runtime_aux_score_weight is None else float(args.runtime_aux_score_weight)
            ),
            runtime_aux_output_scale=(
                None if args.runtime_aux_output_scale is None else float(args.runtime_aux_output_scale)
            ),
            ppo_clip_coef=float(args.ppo_clip_coef),
            full_legal_policy_objective=str(args.full_legal_policy_objective),
            policy_improvement_temperature=float(args.policy_improvement_temperature),
            base_correct_preserve_weight=float(args.base_correct_preserve_weight),
            entropy_coef=float(trajectory_entropy_coef),
            value_loss_weight=float(args.value_loss_weight),
            normalize_advantages=bool(args.normalize_advantages),
            anchor_kl_weight=float(args.anchor_kl_weight),
            anchor_kl_temperature=float(args.anchor_kl_temperature),
            anchor_kl_decision_weights=anchor_kl_decision_weights,
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(args.allow_missing_play_card_target_semantics),
            expected_runtime_policy_id=args.expected_runtime_policy_id,
        )
    elif args.training_mode == "sandbox_policy_value":
        report = run_ygo_style_sandbox_policy_value_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            candidate_model_id=args.candidate_model_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            epochs=args.epochs,
            learning_rate=legacy_learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            shuffle_rows=bool(args.shuffle_rows),
            decision_training_weights=decision_training_weights,
            policy_temperature=float(args.policy_temperature),
            value_loss_weight=float(args.value_loss_weight),
            high_gap_ranking_weight=float(args.high_gap_ranking_weight),
            high_gap_threshold=float(args.high_gap_threshold),
            anchor_kl_weight=float(args.anchor_kl_weight),
            anchor_kl_temperature=float(args.anchor_kl_temperature),
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(args.allow_missing_play_card_target_semantics),
        )
    elif args.training_mode == "outcome_policy":
        policy_entropy_coef = (
            YGO_DEFAULT_ENTROPY_COEF
            if args.entropy_coef is None
            else float(args.entropy_coef)
        )
        report = run_ygo_style_outcome_policy_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            candidate_model_id=args.candidate_model_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            epochs=args.epochs,
            learning_rate=legacy_learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            shuffle_rows=bool(args.shuffle_rows),
            decision_training_weights=decision_training_weights,
            anchor_kl_weight=float(args.anchor_kl_weight),
            anchor_kl_temperature=float(args.anchor_kl_temperature),
            anchor_kl_decision_weights=anchor_kl_decision_weights,
            entropy_coef=float(policy_entropy_coef),
            value_loss_weight=float(args.value_loss_weight),
            normalize_advantages=bool(args.normalize_advantages),
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(args.allow_missing_play_card_target_semantics),
        )
    elif args.training_mode == "direct_policy":
        report = run_ygo_style_direct_policy_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            candidate_model_id=args.candidate_model_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            epochs=args.epochs,
            learning_rate=legacy_learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            shuffle_rows=bool(args.shuffle_rows),
            decision_training_weights=decision_training_weights,
            anchor_kl_weight=float(args.anchor_kl_weight),
            anchor_kl_temperature=float(args.anchor_kl_temperature),
            anchor_kl_decision_weights=anchor_kl_decision_weights,
            allow_selected_action_fallback=bool(args.allow_selected_action_fallback),
            target_contract=str(args.target_contract),
            direct_policy_target_mode=str(args.direct_policy_target_mode),
            action_value_temperature=float(args.action_value_temperature),
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
        )
    else:
        report = run_ygo_style_pairwise_training(
            training_rows_path=training_rows_path,
            out_dir=args.out_dir,
            candidate_model_id=args.candidate_model_id,
            training_row_file_weights=training_row_file_weights,
            base_model_path=args.base_model_path,
            epochs=args.epochs,
            learning_rate=legacy_learning_rate,
            hidden_dim=args.hidden_dim,
            batch_size=args.batch_size,
            margin=args.margin,
            max_margin=args.max_margin,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
            shuffle_rows=bool(args.shuffle_rows),
            target_contract=str(args.target_contract),
            device=str(args.device),
            restart_safety_review_path=args.restart_safety_review,
            allow_unreviewed_restart=bool(args.allow_unreviewed_restart),
            allow_missing_play_card_target_semantics=bool(args.allow_missing_play_card_target_semantics),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
