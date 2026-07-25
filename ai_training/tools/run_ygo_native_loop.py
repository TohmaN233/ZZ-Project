from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.hidden_multiprocessing_spawn import install_hidden_multiprocessing_spawn
from zz.action_set_ygo_policy import (
    YGO_STYLE_FEATURE_FAMILY,
    YgoStyleActionSetPolicyScorer,
    build_ygo_outcome_policy_tensor_batch,
    train_ygo_style_outcome_policy_scorer,
)
from zz.action_set_ygo_policy import _merged_feature_names as _ygo_merged_feature_names
from zz.ygo_vector_actor_rollout import (
    DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP,
    PersistentYgoWorkerLocalVectorRolloutPool,
)


YGO_NATIVE_LOOP_VERSION = "ygo_native_loop_v1"
YGO_NATIVE_LOOP_TRAINING_VERSION = "ygo_native_loop_learner_vtrace_v1"
YGO_CURRENT_POLICY_ENTROPY_COEF = 0.01
YGO_STYLE_POLICY_PT_CHECKPOINT_VERSION = "ygo_style_action_set_policy_pt_checkpoint_v1"
CURRENT_POLICY_TRAINING_MAINLINE = "unified_current_policy_actor_value"
CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE = "current_policy_sampled_trajectory_actor_value"
TrainingRunner = Callable[..., Mapping[str, Any]]
PoolFactory = Callable[..., Any]
REWARD_SHAPING_MODES = {"terminal", "local_step", "value_potential"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor_id_from_model(model_path: str | Path, fallback: str) -> str:
    path = Path(model_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    actor_id = str(
        data.get("actorPolicyId")
        or data.get("candidatePolicyId")
        or data.get("modelId")
        or fallback
        or ""
    ).strip()
    if not actor_id:
        raise ValueError(f"could not resolve actor id from {path}")
    return actor_id


def _batch_size_for(rows: int, num_minibatches: int) -> int:
    return max(1, int(math.ceil(max(1, int(rows)) / float(max(1, int(num_minibatches))))))


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return int(parsed)
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _row_text_value(row: Mapping[str, Any], *keys: str) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    label = row.get("trajectoryPolicyLabel") if isinstance(row.get("trajectoryPolicyLabel"), Mapping) else {}
    for source in (row, metadata, label):
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _row_episode_key(row: Mapping[str, Any]) -> str:
    return _row_text_value(row, "runtimeRecurrentKey", "runtimeSequenceId", "episodeId", "taskId", "stateKey") or f"row:{id(row)}"


def _row_order_key(index: int, row: Mapping[str, Any]) -> tuple[int, int, int, int]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    return (
        _int_or_none(row.get("segmentIndex")) or _int_or_none(metadata.get("segmentIndex")) or 0,
        _int_or_none(row.get("episodeStepIndex")) or _int_or_none(metadata.get("episodeStepIndex")) or 0,
        _int_or_none(row.get("actionSetDecisionIndex")) or _int_or_none(metadata.get("actionSetDecisionIndex")) or int(index),
        int(index),
    )


def _potential_shaping_deltas(
    rows: Sequence[Mapping[str, Any]],
    scorer: YgoStyleActionSetPolicyScorer,
    *,
    gamma: float = 1.0,
    clip_value: float = 0.25,
) -> tuple[dict[int, float], dict[str, Any]]:
    scorer.reset_recurrent_state()
    values = scorer.state_values_batched(list(rows))
    scorer.reset_recurrent_state()
    by_episode: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_episode.setdefault(_row_episode_key(row), []).append(index)
    deltas: dict[int, float] = {}
    terminal_rows = 0
    linked_next_rows = 0
    missing_next_rows = 0
    positive_rows = 0
    negative_rows = 0
    total_abs = 0.0
    bound = max(0.0, float(clip_value))
    for indices in by_episode.values():
        ordered = sorted(indices, key=lambda item: _row_order_key(item, rows[item]))
        for offset, index in enumerate(ordered):
            row = rows[index]
            done = bool(
                row.get("trajectoryDone")
                or _mapping(row.get("metadata")).get("trajectoryDone")
                or _mapping(row.get("trajectoryPolicyLabel")).get("done")
            )
            if done:
                next_value = 0.0
                terminal_rows += 1
            elif offset + 1 < len(ordered):
                next_value = float(values[int(ordered[offset + 1])])
                linked_next_rows += 1
            else:
                missing_next_rows += 1
                continue
            raw_delta = float(gamma) * float(next_value) - float(values[index])
            delta = max(-bound, min(bound, raw_delta)) if bound > 0.0 else raw_delta
            deltas[index] = float(delta)
            total_abs += abs(float(delta))
            if delta > 0.0:
                positive_rows += 1
            elif delta < 0.0:
                negative_rows += 1
    return deltas, {
        "kind": "value_potential_reward_shaping_v1",
        "enabled": True,
        "rows": int(len(rows)),
        "episodeGroups": int(len(by_episode)),
        "gamma": float(gamma),
        "clip": float(bound),
        "scoredRows": int(len(values)),
        "appliedRows": int(len(deltas)),
        "linkedNextRows": int(linked_next_rows),
        "terminalRows": int(terminal_rows),
        "missingNextRows": int(missing_next_rows),
        "positiveRows": int(positive_rows),
        "negativeRows": int(negative_rows),
        "meanAbsDelta": float(total_abs) / float(len(deltas)) if deltas else 0.0,
    }


def _load_native_initial_scorer(path: str | Path) -> YgoStyleActionSetPolicyScorer:
    model_path = Path(path)
    if model_path.suffix.lower() in {".pt", ".pth"}:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyTorch is required to load ygo-style .pt checkpoints") from exc
        try:
            payload = torch.load(model_path, map_location="cpu", weights_only=False)
        except TypeError:  # pragma: no cover - older torch
            payload = torch.load(model_path, map_location="cpu")
        if isinstance(payload, Mapping) and isinstance(payload.get("model"), Mapping):
            data = payload["model"]
        elif isinstance(payload, Mapping):
            data = payload
        else:
            raise ValueError(f"ygo native base checkpoint must contain a mapping payload: {model_path}")
    else:
        data = json.loads(model_path.read_text(encoding="utf-8"))
        if isinstance(data, Mapping) and isinstance(data.get("model"), Mapping):
            data = data["model"]
    if not isinstance(data, Mapping):
        raise ValueError(f"ygo native base model must be a mapping: {model_path}")
    scorer = YgoStyleActionSetPolicyScorer.from_dict(data)
    scorer.validate_shape()
    return scorer


def _write_native_model_pt(path: Path, model_dict: Mapping[str, Any]) -> None:
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


def _native_vtrace_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    actor_policy_id: str,
    reward_shaping_mode: str = "local_step",
    local_step_reward_weight: float = 0.0,
    potential_reward_weight: float = 0.0,
    potential_reward_clip: float = 0.25,
    potential_value_model_path: str | Path | None = None,
    potential_value_scorer: YgoStyleActionSetPolicyScorer | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    row_list = list(rows)
    out_rows: list[dict[str, Any]] = []
    mode = str(reward_shaping_mode or "local_step").strip().lower()
    if mode not in REWARD_SHAPING_MODES:
        raise ValueError(f"reward_shaping_mode must be one of {sorted(REWARD_SHAPING_MODES)}")
    weight = max(0.0, float(local_step_reward_weight))
    potential_weight = max(0.0, float(potential_reward_weight))
    potential_deltas: dict[int, float] = {}
    potential_report: dict[str, Any] = {"kind": "value_potential_reward_shaping_v1", "enabled": False}
    if mode == "value_potential" and potential_weight > 0.0:
        if potential_value_scorer is None:
            raise ValueError("value_potential reward shaping requires potential_value_scorer")
        potential_deltas, potential_report = _potential_shaping_deltas(
            row_list,
            potential_value_scorer,
            clip_value=float(potential_reward_clip),
        )
    missing_selected = 0
    finite_old_logprob_rows = 0
    finite_old_value_rows = 0
    done_rows = 0
    truncated_rows = 0
    bootstrap_rows = 0
    step_reward_rows = 0
    local_reward_nonzero_rows = 0
    local_reward_applied_rows = 0
    local_reward_zeroed_rows = 0
    recurrent_initial_hidden_rows = 0
    recurrent_hidden_rows = 0
    potential_reward_applied_rows = 0
    potential_reward_missing_rows = 0
    for row_index, raw in enumerate(row_list):
        row = dict(raw)
        metadata = dict(_mapping(row.get("metadata")))
        label = dict(_mapping(row.get("trajectoryPolicyLabel")) or _mapping(row.get("outcomePolicyLabel")))
        selected = _first_int(
            label.get("selectedSlot"),
            label.get("selectedActionSlot"),
            row.get("selectedActionSlot"),
            row.get("actorActionSlot"),
            metadata.get("actorActionSlot"),
        )
        if selected is None:
            missing_selected += 1
            continue
        step_reward = _finite_float_or_none(
            label.get(
                "stepReward",
                label.get(
                    "trajectoryStepReward",
                    row.get("trajectoryStepReward", metadata.get("trajectoryStepReward")),
                ),
            )
        )
        if step_reward is None:
            step_reward = 0.0
        if abs(float(step_reward)) > 0.0:
            step_reward_rows += 1
        local_reward = _finite_float_or_none(
            label.get("localStepReward", row.get("trajectoryLocalStepReward", metadata.get("trajectoryLocalStepReward")))
        )
        if local_reward is None:
            local_reward = 0.0
        if abs(float(local_reward)) > 0.0:
            local_reward_nonzero_rows += 1
            if weight > 0.0:
                local_reward_applied_rows += 1
            else:
                local_reward_zeroed_rows += 1
        potential_reward = float(potential_deltas.get(row_index, 0.0))
        if mode == "local_step":
            shaped_step_reward = float(step_reward) + float(weight) * float(local_reward)
        elif mode == "value_potential":
            shaped_step_reward = float(step_reward) + float(potential_weight) * float(potential_reward)
            if row_index in potential_deltas:
                potential_reward_applied_rows += 1
            else:
                potential_reward_missing_rows += 1
        else:
            shaped_step_reward = float(step_reward)
        old_logprob = _finite_float_or_none(
            label.get(
                "oldPolicyActionLogProb",
                row.get("actorActionLogProb", metadata.get("actorActionLogProb")),
            )
        )
        if old_logprob is not None:
            finite_old_logprob_rows += 1
        old_value = _finite_float_or_none(
            label.get(
                "oldPolicyStateValue",
                metadata.get("oldPolicyStateValue", metadata.get("actorStateValue", row.get("oldPolicyStateValue"))),
            )
        )
        if old_value is not None:
            finite_old_value_rows += 1
        done = bool(label.get("done", row.get("trajectoryDone", metadata.get("trajectoryDone", False))))
        truncated = bool(label.get("truncated", row.get("trajectoryTruncated", metadata.get("trajectoryTruncated", False))))
        if done:
            done_rows += 1
        if truncated:
            truncated_rows += 1
        bootstrap_value = _finite_float_or_none(
            label.get(
                "bootstrapStateValue",
                label.get(
                    "truncatedBootstrapStateValue",
                    row.get("bootstrapStateValue", metadata.get("bootstrapStateValue", metadata.get("truncatedBootstrapStateValue"))),
                ),
            )
        )
        if bootstrap_value is not None:
            bootstrap_rows += 1
        label.update(
            {
                "selectedSlot": int(selected),
                "returnValue": float(_finite_float_or_none(label.get("returnValue", row.get("trajectoryReturn"))) or 0.0),
                "advantage": float(_finite_float_or_none(label.get("advantage", row.get("trajectoryAdvantage"))) or 0.0),
                "rawStepReward": float(step_reward),
                "stepReward": float(shaped_step_reward),
                "localStepReward": float(local_reward),
                "localStepRewardWeight": float(weight),
                "potentialStepReward": float(potential_reward),
                "potentialRewardWeight": float(potential_weight),
                "rewardShapingMode": str(mode),
                "done": bool(done),
                "truncated": bool(truncated),
                "actorAdvantageMode": "learner_vtrace",
                "advantageMode": "native_learner_vtrace_placeholder",
                "criticAdvantageMode": "learner_vtrace",
                "oldPolicyActionLogProb": float(old_logprob) if old_logprob is not None else float("nan"),
            }
        )
        if old_value is not None:
            label["oldPolicyStateValue"] = float(old_value)
            metadata["oldPolicyStateValue"] = float(old_value)
            metadata["actorStateValue"] = float(old_value)
        if bootstrap_value is not None:
            label["bootstrapStateValue"] = float(bootstrap_value)
            metadata["bootstrapStateValue"] = float(bootstrap_value)
            metadata["truncatedBootstrapStateValue"] = float(bootstrap_value)
        for key in ("runtimeRecurrentInitialHiddenState", "segmentInitialRecurrentHiddenState"):
            if isinstance(row.get(key), list | tuple) or isinstance(metadata.get(key), list | tuple):
                recurrent_initial_hidden_rows += 1
                break
        if isinstance(row.get("runtimeRecurrentHiddenState"), list | tuple) or isinstance(
            metadata.get("runtimeRecurrentHiddenState"),
            list | tuple,
        ):
            recurrent_hidden_rows += 1

        row.update(
            {
                "actorPolicyId": str(actor_policy_id),
                "sourceActorPolicyId": str(actor_policy_id),
                "runtimePolicyId": str(actor_policy_id),
                "currentPolicySourceActorPolicyId": str(actor_policy_id),
                "currentPolicyCandidatePolicyId": str(actor_policy_id),
                "selectedActionSlot": int(selected),
                "actionSlot": int(selected),
                "rawStepReward": float(step_reward),
                "trajectoryStepReward": float(shaped_step_reward),
                "trajectoryLocalStepReward": float(local_reward),
                "trajectoryPotentialStepReward": float(potential_reward),
                "trajectoryPolicyLabel": label,
            }
        )
        metadata.update(
            {
                "actorPolicyId": str(actor_policy_id),
                "sourceActorPolicyId": str(actor_policy_id),
                "runtimePolicyId": str(actor_policy_id),
                "actorActionSlot": int(selected),
                "rawStepReward": float(step_reward),
                "trajectoryStepReward": float(shaped_step_reward),
                "trajectoryLocalStepReward": float(local_reward),
                "trajectoryPotentialStepReward": float(potential_reward),
            }
        )
        row["metadata"] = metadata
        out_rows.append(row)
    report = {
        "kind": "ygo_native_vtrace_row_adapter_v1",
        "inputRows": int(len(row_list)),
        "outputRows": int(len(out_rows)),
        "droppedMissingSelectedRows": int(missing_selected),
        "finiteOldPolicyLogProbRows": int(finite_old_logprob_rows),
        "finiteOldPolicyStateValueRows": int(finite_old_value_rows),
        "doneRows": int(done_rows),
        "truncatedRows": int(truncated_rows),
        "bootstrapRows": int(bootstrap_rows),
        "nonZeroStepRewardRows": int(step_reward_rows),
        "localRewardNonZeroRows": int(local_reward_nonzero_rows),
        "localRewardAppliedRows": int(local_reward_applied_rows),
        "localRewardZeroedRows": int(local_reward_zeroed_rows),
        "actorAdvantageMode": "learner_vtrace",
        "rewardShapingMode": str(mode),
        "localStepRewardWeight": float(weight),
        "potentialRewardWeight": float(potential_weight),
        "potentialRewardAppliedRows": int(potential_reward_applied_rows),
        "potentialRewardMissingRows": int(potential_reward_missing_rows),
        "potentialRewardReport": potential_report,
        "recurrentInitialHiddenRows": int(recurrent_initial_hidden_rows),
        "recurrentHiddenRows": int(recurrent_hidden_rows),
    }
    return out_rows, report


def _train_native_vtrace(
    *,
    out_dir: str | Path,
    actor_policy_id: str,
    candidate_policy_id: str,
    base_model_path: str | Path,
    training_rows: Iterable[Mapping[str, Any]],
    update_epochs: int,
    learning_rate: float,
    hidden_dim: int,
    batch_size: int,
    seed: int,
    ppo_clip_coef: float,
    value_loss_weight: float,
    entropy_coef: float,
    recurrent_training_mode: str,
    device: str,
    reward_shaping_mode: str = "local_step",
    local_step_reward_weight: float = 0.0,
    potential_reward_weight: float = 0.0,
    potential_reward_clip: float = 0.25,
    potential_value_model_path: str | Path | None = None,
) -> dict[str, Any]:
    started_at = perf_counter()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    raw_rows = list(training_rows)
    potential_reference_path = Path(potential_value_model_path) if potential_value_model_path else Path(base_model_path)
    initial_scorer = _load_native_initial_scorer(base_model_path)
    potential_value_scorer = (
        initial_scorer
        if potential_reference_path == Path(base_model_path)
        else _load_native_initial_scorer(potential_reference_path)
    )
    native_rows, row_adapter_report = _native_vtrace_rows(
        raw_rows,
        actor_policy_id=actor_policy_id,
        reward_shaping_mode=str(reward_shaping_mode),
        local_step_reward_weight=float(local_step_reward_weight),
        potential_reward_weight=float(potential_reward_weight),
        potential_reward_clip=float(potential_reward_clip),
        potential_value_scorer=potential_value_scorer,
    )
    if not native_rows:
        raise ValueError("ygo native learner requires at least one native trajectory row")
    if int(row_adapter_report["finiteOldPolicyLogProbRows"]) != len(native_rows):
        raise ValueError("ygo native learner requires finite old selected-action logprobs")

    tensor_shape = YgoStyleActionSetPolicyScorer(
        globalFeatureNames=_ygo_merged_feature_names(native_rows, "globalFeatureNames"),
        historyFeatureNames=_ygo_merged_feature_names(native_rows, "historyFeatureNames"),
        actionFeatureNames=_ygo_merged_feature_names(native_rows, "actionFeatureNames"),
        cardFeatureNames=_ygo_merged_feature_names(native_rows, "cardFeatureNames"),
        inputDim=0,
        hiddenDim=int(hidden_dim),
    )
    tensor_shape.inputDim = (
        len(tensor_shape.globalFeatureNames)
        + len(tensor_shape.historyFeatureNames)
        + len(tensor_shape.actionFeatureNames)
        + 3 * len(tensor_shape.cardFeatureNames)
    )
    recurrent_mode = str(recurrent_training_mode or "disabled").strip().lower()
    tensor_batch = build_ygo_outcome_policy_tensor_batch(
        native_rows,
        scorer=tensor_shape,
        decision_training_weights={},
        normalize_advantages=False,
        layout=("ragged_legal_slots" if recurrent_mode != "disabled" else "dense_padded"),
        preserve_order=True,
    )
    candidate = train_ygo_style_outcome_policy_scorer(
        native_rows,
        epochs=int(update_epochs),
        learning_rate=float(learning_rate),
        hidden_dim=int(hidden_dim),
        batch_size=int(batch_size),
        seed=int(seed),
        initial_scorer=initial_scorer,
        decision_training_weights={},
        anchor_kl_weight=0.0,
        retention_kl_mode="disabled",
        entropy_coef=float(entropy_coef),
        ppo_clip_coef=float(ppo_clip_coef),
        value_loss_weight=float(value_loss_weight),
        normalize_advantages=False,
        advantage_normalization_mode="scale_only",
        value_domain_bias_mode="matchup_bucket",
        recurrent_training_mode=str(recurrent_training_mode),
        decision_residual_policy_mode="disabled",
        state_action_interaction_mode="disabled",
        require_old_policy_log_prob=True,
        actor_update_requires_trusted_value=False,
        actor_loss_sign_balance_mode="disabled",
        actor_loss_advantage_sign_filter="disabled",
        actor_loss_label_consistency_mode="disabled",
        actor_loss_counter_signal_conflict_weight=1.0,
        actor_advantage_source="gae",
        q_backed_actor_residual_transfer_mode="disabled",
        actor_loss_relative_mode="selected_logprob",
        actor_loss_group_mode="disabled",
        actor_legal_margin_weight=0.0,
        actor_signature_drift_penalty_weight=0.0,
        actor_signature_contrastive_weight=0.0,
        actor_gradient_collision_audit_mode="disabled",
        functional_logit_oracle_mode="disabled",
        actor_linearized_representability_mode="disabled",
        learner_diagnostics_mode="minimal",
        critic_warmup_epochs=0,
        critic_warmup_recompute_advantage=True,
        device=str(device),
        tensor_batch=tensor_batch,
    )
    diagnostics = dict(getattr(candidate, "runtimeAuxTrainingDiagnostics", {}) or {})
    learner_vtrace_report = dict(diagnostics.get("learnerVtraceReport") or {})
    if not bool(learner_vtrace_report.get("enabled")):
        raise RuntimeError("native learner did not enable learner-side V-trace")

    model_path = out_path / "self_improvement_current_policy_actor_value_model.json"
    checkpoint_path = out_path / "self_improvement_current_policy_actor_value_model.pt"
    report_path = out_path / "ygo_native_training_report.json"
    model_dict = candidate.to_dict()
    model_dict.update(
        {
            "modelId": str(candidate_policy_id),
            "trainingMode": YGO_NATIVE_LOOP_TRAINING_VERSION,
            "trainingReportPath": str(report_path),
            "checkpointFormat": YGO_STYLE_POLICY_PT_CHECKPOINT_VERSION,
            "checkpointPath": str(checkpoint_path),
            "runtimeJsonExportPath": str(model_path),
            "trainingMainline": CURRENT_POLICY_TRAINING_MAINLINE,
            "routeProfile": YGO_NATIVE_LOOP_VERSION,
            "basePolicyRole": "warmstart_or_reference_only",
            "actorPolicyId": str(candidate_policy_id),
            "sourceActorPolicyId": str(actor_policy_id),
            "candidatePolicyId": str(candidate_policy_id),
            "runtimeLaunchableActor": True,
            "runtimeSelectionInterface": "zz.current_policy_runtime.masked_argmax_action",
            "runtimeRowContract": "zz.current_policy_runtime.validate_current_policy_row",
            "actorNSourceEligible": False,
            "sandboxOnly": False,
            "gateEligible": False,
            "gateEligibilityReasons": ["native_loop_no_gate"],
            "directPolicyRuntimeAuthority": True,
            "unifiedMaskedActorValueTraining": True,
            "fullLegalActionSetTraining": True,
            "activePolicyRequiredForGameplayClaim": True,
            "sidecarListwiseTraining": False,
            "residualSidecarTraining": False,
            "runtimeCalibratedSidecarTraining": False,
            "fullDirectPolicyTraining": True,
            "selectedActionImitation": False,
            "teacherScoreImitation": False,
            "featureFamily": YGO_STYLE_FEATURE_FAMILY,
            "trainingObjective": CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE,
            "policyTarget": "native_sampled_actor_learner_vtrace",
            "policyTargetSource": "rolling_fixed_step_actor_rollout",
            "advantageTarget": "learner_vtrace",
            "actualAdvantageSource": "learner_vtrace",
            "stateValueTarget": "learner_vtrace_target_values",
            "valueTargetMode": "vtrace",
            "sampledAdvantagePolicyGradientTraining": True,
            "currentPolicyActorAdvantageMode": "learner_vtrace",
            "currentPolicyLocalStepRewardWeight": float(local_step_reward_weight),
            "rewardShapingMode": str(reward_shaping_mode),
            "potentialRewardWeight": float(potential_reward_weight),
            "potentialRewardClip": float(potential_reward_clip),
            "potentialValueModelPath": str(potential_reference_path),
            "normalizeAdvantages": False,
            "ppoClipCoef": float(ppo_clip_coef),
            "entropyCoef": float(entropy_coef),
            "valueLossWeight": float(value_loss_weight),
            "updateEpochs": int(update_epochs),
            "batchSize": int(batch_size),
            "baseModelPath": str(base_model_path),
            "trainingLaunched": True,
            "checkpointExported": True,
            "promotionApproved": False,
            "protectedDefaultsChanged": False,
            "defaultRuntimeChanged": False,
            "nativeLoop": True,
            "usesCurrentPolicyLoop": False,
            "nativeRowAdapterReport": row_adapter_report,
        }
    )
    _write_native_model_pt(checkpoint_path, model_dict)
    model_path.write_text(json.dumps(model_dict, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    elapsed_seconds = max(0.000001, perf_counter() - started_at)
    report = {
        "kind": YGO_NATIVE_LOOP_TRAINING_VERSION,
        "createdAt": _utc_now(),
        "nativeLoop": True,
        "usesCurrentPolicyLoop": False,
        "routeProfile": YGO_NATIVE_LOOP_VERSION,
        "trainingMainline": CURRENT_POLICY_TRAINING_MAINLINE,
        "actorPolicyId": str(actor_policy_id),
        "candidatePolicyId": str(candidate_policy_id),
        "baseModelPath": str(base_model_path),
        "candidateModelPath": str(model_path),
        "candidateCheckpointPath": str(checkpoint_path),
        "reportPath": str(report_path),
        "rowCount": int(len(raw_rows)),
        "trainRows": int(len(native_rows)),
        "epochs": int(update_epochs),
        "updateEpochs": int(update_epochs),
        "learningRate": float(learning_rate),
        "hiddenDim": int(candidate.hiddenDim),
        "batchSize": int(batch_size),
        "seed": int(seed),
        "elapsedSeconds": round(float(elapsed_seconds), 6),
        "usableTrajectoryRowsPerSecond": round(float(len(native_rows)) / float(elapsed_seconds), 6),
        "trainingResolvedDevice": str(candidate.trainingResolvedDevice),
        "runtimeLaunchableActor": True,
        "trainingObjective": CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE,
        "actualAdvantageSource": "learner_vtrace",
        "valueTargetMode": "vtrace",
        "currentPolicyActorAdvantageMode": "learner_vtrace",
        "currentPolicyLocalStepRewardWeight": float(local_step_reward_weight),
        "rewardShapingMode": str(reward_shaping_mode),
        "potentialRewardWeight": float(potential_reward_weight),
        "potentialRewardClip": float(potential_reward_clip),
        "potentialValueModelPath": str(potential_reference_path),
        "normalizeAdvantages": False,
        "ppoClipCoef": float(ppo_clip_coef),
        "entropyCoef": float(entropy_coef),
        "learnerVtraceReport": learner_vtrace_report,
        "oldPolicyLogProbAlignmentReport": dict(diagnostics.get("oldPolicyLogProbAlignmentReport") or {}),
        "sequenceBatchReport": dict(diagnostics.get("learnerPrebuiltTensorBatch") or {}),
        "actualLearnerBatchDomainReport": dict(diagnostics.get("actualLearnerBatchDomainReport") or {}),
        "recurrentInitialStateReport": dict(diagnostics.get("recurrentInitialStateReport") or {}),
        "nativeRowAdapterReport": row_adapter_report,
        "gateRun": False,
        "promotionRun": False,
        "offlineMovementGate": False,
        "trainingLaunched": True,
        "checkpointExported": True,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _compact_rollout_report(report: Mapping[str, Any]) -> dict[str, Any]:
    throughput = report.get("throughput") if isinstance(report.get("throughput"), Mapping) else {}
    return {
        "trainableTrajectoryRows": int(report.get("trainableTrajectoryRows") or 0),
        "workerFailures": int(report.get("workerFailures") or 0),
        "executionErrors": list(report.get("executionErrors") or []),
        "rollingContinuedGames": int(report.get("rollingContinuedGames") or 0),
        "rollingCarriedGames": int(report.get("rollingCarriedGames") or 0),
        "rollingActiveSlots": int(report.get("rollingActiveSlots") or 0),
        "decisionRowsPerSecond": throughput.get("decisionRowsPerSecond"),
        "gamesCompleted": throughput.get("gamesCompleted"),
    }


def _write_native_loop_report(
    path: Path,
    *,
    manifest: Mapping[str, Any],
    requested_cycles: int,
    initial_model_path: Path,
    final_actor_policy_id: str,
    final_model_path: Path,
    cycles: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    report = {
        "kind": YGO_NATIVE_LOOP_VERSION,
        "manifest": dict(manifest),
        "trainingCycles": int(requested_cycles),
        "cyclesCompleted": len(cycles),
        "status": status,
        "initialModelPath": str(initial_model_path),
        "finalActorPolicyId": final_actor_policy_id,
        "finalModelPath": str(final_model_path),
        "cycles": cycles,
        "createdAt": _utc_now(),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def run_ygo_native_loop(
    *,
    out_dir: str | Path,
    base_model_path: str | Path,
    current_policy_id: str | None = None,
    candidate_policy_id: str = "ygo_native_loop_v1",
    seed: int = 2026061340,
    cycles: int = 1,
    generation_seeds: Iterable[int] | None = None,
    worker_count: int = 16,
    worker_env_slots: int = 8,
    num_steps: int = 128,
    max_game_actions: int = 500,
    max_games_per_env: int = 8,
    selfplay_games_per_pool: int = 1,
    original_games_per_pool: int = 0,
    update_epochs: int = 2,
    num_minibatches: int = 64,
    learning_rate: float = 0.0003,
    hidden_dim: int = 128,
    ppo_clip_coef: float = 0.2,
    value_loss_weight: float = 0.25,
    entropy_coef: float = YGO_CURRENT_POLICY_ENTROPY_COEF,
    reward_shaping_mode: str = "local_step",
    local_step_reward_weight: float = 0.0,
    potential_reward_weight: float = 0.0,
    potential_reward_clip: float = 0.25,
    potential_value_model_path: str | Path | None = None,
    gate_deck_pool_payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    recurrent_training_mode: str = "gru_domain_v1",
    device: str = "auto",
    rollout_pool_factory: PoolFactory = PersistentYgoWorkerLocalVectorRolloutPool,
    training_runner: TrainingRunner = _train_native_vtrace,
) -> dict[str, Any]:
    """Run the YGO-native boundary: rolling env rollout -> V-trace PPO -> same policy."""

    if int(cycles) <= 0:
        raise ValueError("cycles must be positive")
    if int(worker_count) <= 0 or int(worker_count) > DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP:
        raise ValueError(f"worker_count must be in [1, {DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP}]")
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    current_model = Path(base_model_path)
    if not current_model.exists():
        raise FileNotFoundError(current_model)
    actor_id = _actor_id_from_model(current_model, current_policy_id or "")
    seed_values = [int(value) for value in list(generation_seeds or [])]
    if not seed_values:
        seed_values = [int(seed) + index for index in range(int(cycles))]

    shaping_mode = str(reward_shaping_mode or "local_step").strip().lower()
    if shaping_mode not in REWARD_SHAPING_MODES:
        raise ValueError(f"reward_shaping_mode must be one of {sorted(REWARD_SHAPING_MODES)}")
    reward_label = "terminal_win_loss_only"
    if shaping_mode == "local_step" and float(local_step_reward_weight) > 0.0:
        reward_label = "terminal_win_loss_plus_local_step_shaping"
    if shaping_mode == "value_potential" and float(potential_reward_weight) > 0.0:
        reward_label = "terminal_win_loss_plus_frozen_value_potential_shaping"

    manifest = {
        "kind": "ygo_native_loop_manifest_v1",
        "nativeLoop": True,
        "usesCurrentPolicyLoop": False,
        "routeProfile": "ygo_native_loop_v1",
        "rollout": "rolling_env_time_series",
        "reward": reward_label,
        "rewardShapingMode": str(shaping_mode),
        "advantage": "learner_vtrace",
        "valueTarget": "vtrace",
        "localStepRewardWeight": float(local_step_reward_weight),
        "potentialRewardWeight": float(potential_reward_weight),
        "potentialRewardClip": float(potential_reward_clip),
        "postTrainingDiagnostics": "skip",
        "offlineMovementGate": False,
        "gateRun": False,
        "promotionRun": False,
        "workerCount": int(worker_count),
        "workerEnvSlots": int(worker_env_slots),
        "totalEnvSlots": int(worker_count) * int(worker_env_slots),
        "numSteps": int(num_steps),
        "updateEpochs": int(update_epochs),
        "numMinibatches": int(num_minibatches),
        "ppoClipCoef": float(ppo_clip_coef),
    }
    (root / "native_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    cycle_reports: list[dict[str, Any]] = []
    install_hidden_multiprocessing_spawn()
    report_path = root / "ygo_native_loop_report.json"
    initial_model_path = Path(base_model_path)
    fixed_potential_value_model_path = Path(potential_value_model_path) if potential_value_model_path else initial_model_path
    with rollout_pool_factory(
        worker_count=int(worker_count),
        worker_env_slots=int(worker_env_slots),
        num_steps=int(num_steps),
        action_set_max_actions=128,
        max_game_actions=int(max_game_actions),
        max_games_per_env=int(max_games_per_env),
        selfplay_games_per_pool=int(selfplay_games_per_pool),
        original_games_per_pool=int(original_games_per_pool),
        original_opponent_policy_ids=(),
        training_pool_schedule="default",
        max_bridge_decisions_per_env=0,
        drain_to_terminal=False,
        original_drain_to_terminal=False,
        selfplay_drain_to_terminal=False,
        rolling_env_state=True,
        execution_backend="process",
        compact_action_rows=True,
        current_policy_rollout_selection_mode="sampled_from_logits",
        current_policy_rollout_temperature=1.0,
        sqlite_debug_log=False,
        gate_deck_pool_payloads=gate_deck_pool_payloads,
    ) as pool:
        for cycle_index in range(int(cycles)):
            cycle_id = f"cycle-{cycle_index + 1:04d}"
            cycle_dir = root / cycle_id
            cycle_seed = seed_values[cycle_index % len(seed_values)]
            rollout_report = dict(
                pool.rollout(
                    out_dir=cycle_dir / "rollout",
                    run_id=f"native-{cycle_id}",
                    actor_id=actor_id,
                    current_policy_model_path=current_model,
                    seed=int(seed),
                    generation_seeds=(int(cycle_seed),),
                    fixed_gate_seed=int(seed),
                    training_pool_schedule_cycle_index=int(cycle_index),
                )
            )
            rows = list(rollout_report.get("_trajectoryRows") or [])
            trainable_rows = int(rollout_report.get("trainableTrajectoryRows") or 0)
            if len(rows) != trainable_rows:
                raise ValueError(f"{cycle_id}: rollout rows {len(rows)} != trainable rows {trainable_rows}")
            if trainable_rows <= 0:
                raise ValueError(f"{cycle_id}: no trainable trajectory rows")
            if int(rollout_report.get("workerFailures") or 0):
                raise RuntimeError(f"{cycle_id}: worker failures in native rollout")
            if rollout_report.get("executionErrors"):
                raise RuntimeError(f"{cycle_id}: execution errors in native rollout")

            train_report = dict(
                training_runner(
                    out_dir=cycle_dir / "train",
                    actor_policy_id=actor_id,
                    candidate_policy_id=f"{candidate_policy_id}_{cycle_index + 1:04d}",
                    base_model_path=current_model,
                    training_rows=rows,
                    update_epochs=int(update_epochs),
                    learning_rate=float(learning_rate),
                    hidden_dim=int(hidden_dim),
                    batch_size=_batch_size_for(trainable_rows, int(num_minibatches)),
                    seed=int(seed),
                    ppo_clip_coef=float(ppo_clip_coef),
                    value_loss_weight=float(value_loss_weight),
                    reward_shaping_mode=str(shaping_mode),
                    local_step_reward_weight=float(local_step_reward_weight),
                    potential_reward_weight=float(potential_reward_weight),
                    potential_reward_clip=float(potential_reward_clip),
                    potential_value_model_path=fixed_potential_value_model_path,
                    recurrent_training_mode=str(recurrent_training_mode),
                    entropy_coef=float(entropy_coef),
                    device=str(device),
                )
            )
            if train_report.get("actualAdvantageSource") != "learner_vtrace":
                raise RuntimeError(f"{cycle_id}: learner_vtrace was not used")
            if train_report.get("valueTargetMode") != "vtrace":
                raise RuntimeError(f"{cycle_id}: vtrace value target was not used")
            if abs(float(train_report.get("currentPolicyLocalStepRewardWeight") or 0.0) - float(local_step_reward_weight)) > 1.0e-12:
                raise RuntimeError(f"{cycle_id}: local shaping weight mismatch")
            if str(train_report.get("rewardShapingMode") or "") != str(shaping_mode):
                raise RuntimeError(f"{cycle_id}: reward shaping mode mismatch")
            next_model = Path(str(train_report.get("candidateModelPath") or ""))
            next_actor_id = str(train_report.get("candidatePolicyId") or "").strip()
            if not next_model.exists() or not next_actor_id:
                raise RuntimeError(f"{cycle_id}: training did not export a runtime actor")
            cycle_reports.append(
                {
                    "cycleId": cycle_id,
                    "sourceActorId": actor_id,
                    "sourceModelPath": str(current_model),
                    "candidatePolicyId": next_actor_id,
                    "candidateModelPath": str(next_model),
                    "rollout": _compact_rollout_report(rollout_report),
                    "trainRows": int(trainable_rows),
                    "learnerVtraceRows": int((train_report.get("learnerVtraceReport") or {}).get("rows") or 0),
                    "createdAt": _utc_now(),
                }
            )
            actor_id = next_actor_id
            current_model = next_model
            _write_native_loop_report(
                report_path,
                manifest=manifest,
                requested_cycles=int(cycles),
                initial_model_path=initial_model_path,
                final_actor_policy_id=actor_id,
                final_model_path=current_model,
                cycles=cycle_reports,
                status="running",
            )

    report = _write_native_loop_report(
        report_path,
        manifest=manifest,
        requested_cycles=int(cycles),
        initial_model_path=initial_model_path,
        final_actor_policy_id=actor_id,
        final_model_path=current_model,
        cycles=cycle_reports,
        status="completed",
    )
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the YGO-native rolling selfplay PPO/V-trace loop.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--base-model-path", required=True)
    parser.add_argument("--current-policy-id", default="")
    parser.add_argument("--candidate-policy-id", default="ygo_native_loop_v1")
    parser.add_argument("--seed", type=int, default=2026061340)
    parser.add_argument("--generation-seed", dest="generation_seeds", type=int, action="append", default=[])
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--worker-count", type=int, default=16)
    parser.add_argument("--worker-env-slots", type=int, default=8)
    parser.add_argument("--num-steps", type=int, default=128)
    parser.add_argument("--max-game-actions", type=int, default=500)
    parser.add_argument("--max-games-per-env", type=int, default=8)
    parser.add_argument("--selfplay-games-per-pool", type=int, default=1)
    parser.add_argument("--original-games-per-pool", type=int, default=0)
    parser.add_argument("--update-epochs", type=int, default=2)
    parser.add_argument("--num-minibatches", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--ppo-clip-coef", type=float, default=0.2)
    parser.add_argument("--value-loss-weight", type=float, default=0.25)
    parser.add_argument("--entropy-coef", type=float, default=YGO_CURRENT_POLICY_ENTROPY_COEF)
    parser.add_argument("--reward-shaping-mode", choices=sorted(REWARD_SHAPING_MODES), default="local_step")
    parser.add_argument("--local-step-reward-weight", type=float, default=0.0)
    parser.add_argument("--potential-reward-weight", type=float, default=0.0)
    parser.add_argument("--potential-reward-clip", type=float, default=0.25)
    parser.add_argument("--potential-value-model-path", default="")
    parser.add_argument("--recurrent-training-mode", default="gru_domain_v1")
    parser.add_argument("--device", default="auto")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_ygo_native_loop(
        out_dir=args.out_dir,
        base_model_path=args.base_model_path,
        current_policy_id=args.current_policy_id or None,
        candidate_policy_id=args.candidate_policy_id,
        seed=args.seed,
        cycles=args.cycles,
        generation_seeds=args.generation_seeds,
        worker_count=args.worker_count,
        worker_env_slots=args.worker_env_slots,
        num_steps=args.num_steps,
        max_game_actions=args.max_game_actions,
        max_games_per_env=args.max_games_per_env,
        selfplay_games_per_pool=args.selfplay_games_per_pool,
        original_games_per_pool=args.original_games_per_pool,
        update_epochs=args.update_epochs,
        num_minibatches=args.num_minibatches,
        learning_rate=args.learning_rate,
        hidden_dim=args.hidden_dim,
        ppo_clip_coef=args.ppo_clip_coef,
        value_loss_weight=args.value_loss_weight,
        entropy_coef=args.entropy_coef,
        reward_shaping_mode=args.reward_shaping_mode,
        local_step_reward_weight=args.local_step_reward_weight,
        potential_reward_weight=args.potential_reward_weight,
        potential_reward_clip=args.potential_reward_clip,
        potential_value_model_path=args.potential_value_model_path or None,
        recurrent_training_mode=args.recurrent_training_mode,
        device=args.device,
    )
    print(json.dumps({"trainingCycles": report["trainingCycles"], "finalModelPath": report["finalModelPath"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
