from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.run_ygo_style_pairwise_training import DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING


ONLINE_LOOP_VERSION = "ygo_online_training_loop_v1"
SEALED_BATCH_VERSION = "ygo_online_sealed_training_batch_v1"
TRAINING_TABLE = "training_action_value_rows"
TRAJECTORY_TRAINING_TABLE = "training_trajectory_rows"
DEFAULT_FIXED_GATE_SEED = 2026061340
TRAINING_MODE_SANDBOX_POLICY_VALUE = "sandbox_policy_value"
TRAINING_MODE_TRAJECTORY_ADVANTAGE_RUNTIME = "trajectory_advantage_runtime"
ONLINE_TRAINING_MODES = {
    TRAINING_MODE_SANDBOX_POLICY_VALUE,
    TRAINING_MODE_TRAJECTORY_ADVANTAGE_RUNTIME,
}
DEFAULT_FARM_DECISION_KINDS = (
    "main",
    "mana",
    "flash",
    "blocker",
    "attack_target",
    "generic_target",
)
DEFAULT_BASE_POLICY_ID = "self_improvement_pilot_ygo_style_policy_phase_v137_anchored_nonmain_wide12_sim16_v1"
DEFAULT_BASE_MODEL_PATH = Path(
    "local_ai_training/baseline_goal_20260602/"
    "deep_g5_relative_push_v6_defaultoff/"
    "phase_v135_ygo_style_anchored_from_v133_seed2026061340_v1/"
    "self_improvement_pilot_listwise_scorer_model.json"
)
DEFAULT_SANDBOX_POLICY_VALUE_ONLINE_BATCH_SIZE = 32
DEFAULT_TRAJECTORY_ADVANTAGE_ONLINE_BATCH_SIZE = 512

FarmRunner = Callable[..., Mapping[str, Any]]
TrainingRunner = Callable[..., Mapping[str, Any]]


def seal_sqlite_training_batch(
    *,
    source_db_path: str | Path,
    sealed_db_path: str | Path,
    batch_id: str,
    source_report: Mapping[str, Any] | None = None,
    training_table: str = TRAINING_TABLE,
) -> dict[str, Any]:
    """Copy a consistent trainable-row snapshot into a sealed SQLite batch."""

    source_path = Path(source_db_path)
    target_path = Path(sealed_db_path)
    if not source_path.exists():
        raise FileNotFoundError(f"source SQLite does not exist: {source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()

    source_uri = f"file:{source_path.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(target_path) as target:
        table = str(training_table or TRAINING_TABLE)
        create_sql = _training_table_create_sql(source, table=table)
        columns = _training_table_columns(source, table=table)
        target.execute(create_sql)
        quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        quoted_table = _quote_identifier(table)
        rows = source.execute(f"select {quoted_columns} from {quoted_table} order by rowid").fetchall()
        target.executemany(
            f"insert into {quoted_table}({quoted_columns}) values ({placeholders})",
            rows,
        )
        target.execute("create table sealed_batch_metadata(key text primary key, value text not null)")
        if "decision_kind" in columns:
            rows_by_decision = dict(
                Counter(
                    str(row[0] or "unknown")
                    for row in target.execute(
                        f"select decision_kind from {quoted_table}"
                        " where decision_kind is not null and decision_kind != ''"
                    )
                )
            )
        else:
            rows_by_decision = {}
        group_column = "case_id" if "case_id" in columns else "state_key" if "state_key" in columns else ""
        group_count = (
            target.execute(
                f"select count(distinct {_quote_identifier(group_column)}) from {quoted_table}"
            ).fetchone()[0]
            if group_column
            else len(rows)
        )
        report = {
            "kind": SEALED_BATCH_VERSION,
            "createdAt": _utc_now(),
            "batchId": str(batch_id),
            "sourceDbPath": str(source_path),
            "sealedDbPath": str(target_path),
            "trainingRowsTable": table,
            "rowCount": int(len(rows)),
            "groupCount": int(group_count or 0),
            "rowsByDecisionKind": dict(sorted(rows_by_decision.items())),
            "sourceReport": dict(source_report or {}),
        }
        metadata = {
            "batchId": str(batch_id),
            "sourceDbPath": str(source_path),
            "rowCount": str(len(rows)),
            "groupCount": str(int(group_count or 0)),
            "rowsByDecisionKind": json.dumps(report["rowsByDecisionKind"], sort_keys=True),
            "sourceReport": json.dumps(report["sourceReport"], sort_keys=True, default=str),
        }
        target.executemany(
            "insert into sealed_batch_metadata(key, value) values (?, ?)",
            sorted(metadata.items()),
        )
        target.commit()

    report_path = target_path.with_name("sealed_training_batch_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report["reportPath"] = str(report_path)
    return report


def run_ygo_online_training_loop(
    *,
    out_dir: str | Path,
    run_id: str,
    generation_seeds: Iterable[int],
    cycles: int,
    max_tasks_per_cycle: int,
    min_trainable_rows_per_cycle: int,
    base_model_path: str | Path = DEFAULT_BASE_MODEL_PATH,
    base_policy_id: str = DEFAULT_BASE_POLICY_ID,
    candidate_model_id_prefix: str,
    fixed_gate_seed: int = DEFAULT_FIXED_GATE_SEED,
    max_workers: int = 8,
    max_elapsed_seconds_per_cycle: float | None = None,
    device: str = "cuda",
    farm_decision_kinds: Iterable[str] | None = None,
    farm_min_action_set_snapshots_per_decision_kind: Mapping[str, int] | None = None,
    farm_min_full_legal_groups_per_decision_kind: Mapping[str, int] | None = None,
    branch_rollout_samples: int = 1,
    max_branch_rows_per_task: int = 16,
    branch_max_actions: int = 30,
    game_prefix_max_actions: int | None = 24,
    game_prefix_hard_max_actions: int | None = 96,
    include_decision_kinds: Iterable[str] | None = None,
    training_mode: str = TRAINING_MODE_SANDBOX_POLICY_VALUE,
    learning_rate: float | None = None,
    hidden_dim: int = 64,
    eval_fraction: float = 0.2,
    runtime_aux_score_weight: float = 0.03,
    ppo_clip_coef: float = 0.2,
    value_loss_weight: float = 0.25,
    full_legal_policy_objective: str = "search_improved_policy_ce",
    policy_improvement_temperature: float = 1.0,
    policy_temperature: float = 0.5,
    high_gap_ranking_weight: float = 0.25,
    high_gap_threshold: float = DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
    base_correct_preserve_weight: float = 4.0,
    anchor_kl_weight: float = 0.5,
    anchor_kl_temperature: float = 1.0,
    target_contract: str = "action_value",
    decision_training_weights: Mapping[str, float] | None = None,
    farm_runner: FarmRunner | None = None,
    training_runner: TrainingRunner | None = None,
) -> dict[str, Any]:
    """Run sealed farm/train cycles without letting training read a live DB."""

    seeds = [int(seed) for seed in generation_seeds]
    if not seeds:
        raise ValueError("generation_seeds must contain at least one seed")
    if int(cycles) <= 0:
        raise ValueError("cycles must be positive")
    if int(max_tasks_per_cycle) <= 0:
        raise ValueError("max_tasks_per_cycle must be positive")
    decision_kinds = [
        str(value).strip()
        for value in (include_decision_kinds or [])
        if str(value).strip()
    ]
    farm_kinds = [
        str(value).strip()
        for value in (farm_decision_kinds or [])
        if str(value).strip()
    ]
    farm_snapshot_minimums = _normalise_int_mapping(farm_min_action_set_snapshots_per_decision_kind)
    farm_full_legal_minimums = _normalise_int_mapping(farm_min_full_legal_groups_per_decision_kind)
    normalized_training_mode = _normalize_training_mode(training_mode)
    if normalized_training_mode == TRAINING_MODE_SANDBOX_POLICY_VALUE and decision_kinds:
        raise ValueError(
            "sandbox_policy_value online training uses one unified full-legal action-set learner; "
            "include_decision_kinds would route-filter the training target"
        )
    if normalized_training_mode == TRAINING_MODE_SANDBOX_POLICY_VALUE and farm_kinds:
        farm_kind_set = set(farm_kinds)
        default_kind_set = set(DEFAULT_FARM_DECISION_KINDS)
        if farm_kind_set != default_kind_set:
            missing = sorted(default_kind_set - farm_kind_set)
            extra = sorted(farm_kind_set - default_kind_set)
            raise ValueError(
                "sandbox_policy_value online training requires full farm_decision_kinds coverage; "
                f"missing={missing}, extra={extra}"
            )
    resolved_farm_runner = _resolve_farm_runner(farm_runner)
    resolved_training_runner = _resolve_training_runner(normalized_training_mode, training_runner)
    resolved_learning_rate = _resolve_learning_rate(normalized_training_mode, learning_rate)

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    cycle_reports: list[dict[str, Any]] = []
    for cycle_index in range(int(cycles)):
        cycle_id = f"cycle-{cycle_index + 1:04d}"
        cycle_seed = seeds[cycle_index % len(seeds)]
        cycle_dir = root / cycle_id
        farm_dir = cycle_dir / "farm"
        train_dir = cycle_dir / "train"
        farm_report = dict(
            resolved_farm_runner(
                out_dir=farm_dir,
                run_id=f"{run_id}-{cycle_id}",
                generation_seeds=(cycle_seed,),
                fixed_gate_seed=int(fixed_gate_seed),
                policy_id=str(base_policy_id),
                max_tasks=int(max_tasks_per_cycle),
                max_workers=int(max_workers),
                max_elapsed_seconds=max_elapsed_seconds_per_cycle,
                max_branch_rows_per_task=int(max_branch_rows_per_task),
                branch_max_actions=int(branch_max_actions),
                branch_rollout_samples=max(1, int(branch_rollout_samples)),
                game_prefix_max_actions=(
                    None if game_prefix_max_actions is None else int(game_prefix_max_actions)
                ),
                game_prefix_hard_max_actions=(
                    None if game_prefix_hard_max_actions is None else int(game_prefix_hard_max_actions)
                ),
                min_action_set_snapshots_per_decision_kind=farm_snapshot_minimums or None,
                decision_kinds=tuple(farm_kinds) if farm_kinds else (
                    DEFAULT_FARM_DECISION_KINDS
                ),
                min_full_legal_groups_per_decision_kind=farm_full_legal_minimums or None,
            )
        )
        _assert_clean_farm_report(farm_report)
        trainable_rows = int(farm_report.get("trainableActionValueRows", 0) or 0)
        cycle_report: dict[str, Any] = {
            "cycleId": cycle_id,
            "generationSeed": int(cycle_seed),
            "farmReport": _compact_farm_report(farm_report),
            "trainingLaunched": False,
        }
        if trainable_rows < int(min_trainable_rows_per_cycle):
            cycle_report["skipReason"] = "insufficient_trainable_rows"
            cycle_reports.append(cycle_report)
            continue

        sealed_db = cycle_dir / "sealed" / "sealed_training_batch.sqlite"
        sealed_report = seal_sqlite_training_batch(
            source_db_path=_farm_training_db_path(farm_report),
            sealed_db_path=sealed_db,
            batch_id=cycle_id,
            source_report=farm_report,
        )
        candidate_id = f"{candidate_model_id_prefix}_{cycle_id}"
        if normalized_training_mode == TRAINING_MODE_SANDBOX_POLICY_VALUE:
            training_report = dict(
                resolved_training_runner(
                    training_rows_path=sealed_db,
                    out_dir=train_dir,
                    candidate_model_id=candidate_id,
                    base_model_path=base_model_path,
                    epochs=1,
                    learning_rate=float(resolved_learning_rate),
                    hidden_dim=int(hidden_dim),
                    batch_size=DEFAULT_SANDBOX_POLICY_VALUE_ONLINE_BATCH_SIZE,
                    eval_fraction=float(eval_fraction),
                    seed=int(fixed_gate_seed),
                    shuffle_rows=True,
                    decision_training_weights=decision_training_weights,
                    policy_temperature=float(policy_temperature),
                    value_loss_weight=float(value_loss_weight),
                    high_gap_ranking_weight=float(high_gap_ranking_weight),
                    high_gap_threshold=float(high_gap_threshold),
                    anchor_kl_weight=float(anchor_kl_weight),
                    anchor_kl_temperature=float(anchor_kl_temperature),
                    device=str(device),
                    allow_unreviewed_restart=True,
                    allow_missing_play_card_target_semantics=False,
                )
            )
        else:
            training_report = dict(
                resolved_training_runner(
                    training_rows_path=sealed_db,
                    out_dir=train_dir,
                    candidate_model_id=candidate_id,
                    base_model_path=base_model_path,
                    expected_runtime_policy_id=str(base_policy_id),
                    epochs=1,
                    learning_rate=float(resolved_learning_rate),
                    hidden_dim=int(hidden_dim),
                    batch_size=DEFAULT_TRAJECTORY_ADVANTAGE_ONLINE_BATCH_SIZE,
                    eval_fraction=float(eval_fraction),
                    seed=int(fixed_gate_seed),
                    shuffle_rows=True,
                    include_decision_kinds=decision_kinds or None,
                    allow_route_limited_launch_training=bool(decision_kinds),
                    runtime_aux_score_weight=float(runtime_aux_score_weight),
                    ppo_clip_coef=float(ppo_clip_coef),
                    value_loss_weight=float(value_loss_weight),
                    device=str(device),
                    allow_unreviewed_restart=True,
                    full_legal_policy_objective=str(full_legal_policy_objective),
                    policy_improvement_temperature=float(policy_improvement_temperature),
                    base_correct_preserve_weight=float(base_correct_preserve_weight),
                    anchor_kl_weight=float(anchor_kl_weight),
                    anchor_kl_temperature=float(anchor_kl_temperature),
                    target_contract=str(target_contract),
                )
            )
        cycle_report.update(
            {
                "sealedBatch": sealed_report,
                "trainingLaunched": True,
                "trainingReport": _compact_training_report(training_report),
            }
        )
        cycle_reports.append(cycle_report)

    report = {
        "kind": ONLINE_LOOP_VERSION,
        "createdAt": _utc_now(),
        "runId": str(run_id),
        "outDir": str(root),
        "cyclesRequested": int(cycles),
        "cyclesCompleted": int(len(cycle_reports)),
        "trainingCycles": int(sum(1 for cycle in cycle_reports if cycle.get("trainingLaunched"))),
        "fixedGateSeed": int(fixed_gate_seed),
        "generationSeeds": seeds,
        "baseModelPath": str(base_model_path),
        "basePolicyId": str(base_policy_id),
        "candidateModelIdPrefix": str(candidate_model_id_prefix),
        "trainingMode": normalized_training_mode,
        "onlineUpdateMode": "sealed_micro_batch_non_promoting",
        "liveDbTrainingAllowed": False,
        "includeDecisionKinds": decision_kinds,
        "farmDecisionKinds": farm_kinds,
        "farmConfig": {
            "branchRolloutSamples": max(1, int(branch_rollout_samples)),
            "maxBranchRowsPerTask": int(max_branch_rows_per_task),
            "branchMaxActions": int(branch_max_actions),
            "gamePrefixMaxActions": (
                None if game_prefix_max_actions is None else int(game_prefix_max_actions)
            ),
            "gamePrefixHardMaxActions": (
                None if game_prefix_hard_max_actions is None else int(game_prefix_hard_max_actions)
            ),
            "minActionSetSnapshotsPerDecisionKind": dict(farm_snapshot_minimums),
            "minFullLegalGroupsPerDecisionKind": dict(farm_full_legal_minimums),
        },
        "trainingConfig": _training_config_report(
            training_mode=normalized_training_mode,
            learning_rate=float(resolved_learning_rate),
            hidden_dim=int(hidden_dim),
            batch_size=(
                DEFAULT_SANDBOX_POLICY_VALUE_ONLINE_BATCH_SIZE
                if normalized_training_mode == TRAINING_MODE_SANDBOX_POLICY_VALUE
                else DEFAULT_TRAJECTORY_ADVANTAGE_ONLINE_BATCH_SIZE
            ),
            eval_fraction=float(eval_fraction),
            policy_temperature=float(policy_temperature),
            high_gap_ranking_weight=float(high_gap_ranking_weight),
            high_gap_threshold=float(high_gap_threshold),
            runtime_aux_score_weight=float(runtime_aux_score_weight),
            ppo_clip_coef=float(ppo_clip_coef),
            value_loss_weight=float(value_loss_weight),
            full_legal_policy_objective=str(full_legal_policy_objective),
            policy_improvement_temperature=float(policy_improvement_temperature),
            base_correct_preserve_weight=float(base_correct_preserve_weight),
            anchor_kl_weight=float(anchor_kl_weight),
            anchor_kl_temperature=float(anchor_kl_temperature),
            target_contract=str(target_contract),
        ),
        "promotionApproved": False,
        "gateLaunched": False,
        "cycles": cycle_reports,
    }
    report_path = root / "ygo_online_training_loop_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report["reportPath"] = str(report_path)
    return report


def _normalize_training_mode(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in ONLINE_TRAINING_MODES:
        allowed = ", ".join(sorted(ONLINE_TRAINING_MODES))
        raise ValueError(f"unknown online training mode {value!r}; expected one of: {allowed}")
    return normalized


def _resolve_training_runner(
    training_mode: str,
    override: TrainingRunner | None,
) -> TrainingRunner:
    if override is not None:
        return override
    if training_mode == TRAINING_MODE_SANDBOX_POLICY_VALUE:
        from tools.run_ygo_style_pairwise_training import run_ygo_style_sandbox_policy_value_training

        return run_ygo_style_sandbox_policy_value_training
    from tools.run_ygo_style_pairwise_training import run_ygo_style_trajectory_advantage_runtime_training

    return run_ygo_style_trajectory_advantage_runtime_training


def _resolve_farm_runner(override: FarmRunner | None) -> FarmRunner:
    if override is not None:
        return override
    from tools.run_ygo_fast_farm import run_ygo_fast_farm

    return run_ygo_fast_farm


def _resolve_learning_rate(training_mode: str, value: float | None) -> float:
    if value is not None:
        return float(value)
    if training_mode == TRAINING_MODE_SANDBOX_POLICY_VALUE:
        return 0.003
    return 0.008


def _training_config_report(
    *,
    training_mode: str,
    learning_rate: float,
    hidden_dim: int,
    batch_size: int,
    eval_fraction: float,
    policy_temperature: float,
    high_gap_ranking_weight: float,
    high_gap_threshold: float,
    runtime_aux_score_weight: float,
    ppo_clip_coef: float,
    value_loss_weight: float,
    full_legal_policy_objective: str,
    policy_improvement_temperature: float,
    base_correct_preserve_weight: float,
    anchor_kl_weight: float,
    anchor_kl_temperature: float,
    target_contract: str,
) -> dict[str, Any]:
    common = {
        "trainingMode": str(training_mode),
        "learningRate": float(learning_rate),
        "hiddenDim": int(hidden_dim),
        "batchSize": int(batch_size),
        "evalFraction": float(eval_fraction),
        "valueLossWeight": float(value_loss_weight),
        "anchorKlWeight": float(anchor_kl_weight),
        "anchorKlTemperature": float(anchor_kl_temperature),
    }
    if training_mode == TRAINING_MODE_SANDBOX_POLICY_VALUE:
        common.update(
            {
                "policyTemperature": float(policy_temperature),
                "highGapRankingWeight": float(high_gap_ranking_weight),
                "highGapThreshold": float(high_gap_threshold),
            }
        )
        return common
    common.update(
        {
            "runtimeAuxScoreWeight": float(runtime_aux_score_weight),
            "ppoClipCoef": float(ppo_clip_coef),
            "fullLegalPolicyObjective": str(full_legal_policy_objective),
            "policyImprovementTemperature": float(policy_improvement_temperature),
            "baseCorrectPreserveWeight": float(base_correct_preserve_weight),
            "targetContract": str(target_contract),
        }
    )
    return common


def _assert_clean_farm_report(report: Mapping[str, Any]) -> None:
    blocking = []
    farm_status = str(report.get("farmStatus") or "").strip()
    if farm_status and farm_status != "completed":
        blocking.append(f"farmStatus={farm_status}")
    if bool(report.get("stoppedByMaxElapsedSeconds")):
        blocking.append("stoppedByMaxElapsedSeconds=True")
    for key in ("identityFailures", "overrideFailures", "dirtyBranchRows", "workerFailures"):
        if int(report.get(key, 0) or 0) != 0:
            blocking.append(f"{key}={report.get(key)}")
    for key in ("timeoutCancelledTasks", "timeoutTerminatedWorkers", "taskFailures"):
        if int(report.get(key, 0) or 0) != 0:
            blocking.append(f"{key}={report.get(key)}")
    execution_errors = report.get("executionErrors")
    if isinstance(execution_errors, list | tuple) and execution_errors:
        blocking.append(f"executionErrors={len(execution_errors)}")
    elif execution_errors:
        blocking.append("executionErrors=present")
    trainable_rows = int(report.get("trainableActionValueRows", 0) or 0)
    runtime_ready_rows = int(report.get("runtimeReadyTrainableActionValueRows", trainable_rows) or 0)
    if runtime_ready_rows != trainable_rows:
        blocking.append(
            f"runtimeReadyTrainableActionValueRows={runtime_ready_rows} "
            f"trainableActionValueRows={trainable_rows}"
        )
    skipped = report.get("skipped") if isinstance(report.get("skipped"), Mapping) else {}
    for key, value in sorted(skipped.items()):
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            count = 1
        if count <= 0:
            continue
        text = str(key)
        if text.startswith("unsafePlayCardTargetSemantics"):
            if _semantic_report_passed(
                report,
                report_key="playCardTargetSemantics",
                passed_key="targetSemanticsGatePassed",
                safe_key="safeForTargetAwarePlayCardTraining",
            ):
                continue
            blocking.append(f"playCardTargetSemantics={count}")
            continue
        if text.startswith("unsafeTargetActionSemantics"):
            if _semantic_report_passed(
                report,
                report_key="targetActionSemantics",
                passed_key="targetActionSemanticsGatePassed",
                safe_key="safeForTargetActionTraining",
            ):
                continue
            blocking.append(f"targetActionSemantics={count}")
            continue
    if blocking:
        raise ValueError("unclean farm report blocks online training: " + ", ".join(blocking))


def _semantic_report_passed(
    report: Mapping[str, Any],
    *,
    report_key: str,
    passed_key: str,
    safe_key: str,
) -> bool:
    semantic_report = report.get(report_key)
    if not isinstance(semantic_report, Mapping):
        return False
    return bool(semantic_report.get(passed_key)) and bool(semantic_report.get(safe_key))


def _farm_training_db_path(report: Mapping[str, Any]) -> Path:
    raw = report.get("trainingRowsDbPath") or report.get("dbPath")
    if not raw:
        raise ValueError("farm report is missing trainingRowsDbPath/dbPath")
    return Path(str(raw))


def _compact_farm_report(report: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "kind",
        "runId",
        "farmStatus",
        "trainingRowsDbPath",
        "trainableActionValueRows",
        "runtimeReadyTrainableActionValueRows",
        "branchRows",
        "actionValueRows",
        "identityFailures",
        "overrideFailures",
        "dirtyBranchRows",
        "workerFailures",
        "throughput",
    )
    return {key: report.get(key) for key in keys if key in report}


def _compact_training_report(report: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "kind",
        "candidateModelId",
        "candidateModelPath",
        "reportPath",
        "trainingRowsPath",
        "trainRows",
        "evalRows",
        "trainingDecisionKindFilter",
        "trainingLaunched",
        "promotionApproved",
        "protectedDefaultsChanged",
        "runtimeBaseScoreSource",
        "candidateTrajectoryAdvantageRuntimeEval",
        "candidateSandboxPolicyValueEval",
        "sandboxOnly",
        "trainingObjective",
    )
    return {key: report.get(key) for key in keys if key in report}


def _training_table_create_sql(conn: sqlite3.Connection, *, table: str = TRAINING_TABLE) -> str:
    row = conn.execute(
        "select sql from sqlite_master where type='table' and name=?",
        (str(table),),
    ).fetchone()
    if not row or not row[0]:
        raise ValueError(f"source SQLite is missing {str(table)}")
    return str(row[0])


def _training_table_columns(conn: sqlite3.Connection, *, table: str = TRAINING_TABLE) -> list[str]:
    columns = [str(row[1]) for row in conn.execute(f"pragma table_info({_quote_identifier(str(table))})")]
    if "row_json" not in columns:
        raise ValueError(f"{str(table)} must contain row_json")
    return columns


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_seeds(values: Iterable[str]) -> list[int]:
    seeds: list[int] = []
    for value in values:
        for part in str(value).split(","):
            text = part.strip()
            if text:
                seeds.append(int(text))
    return seeds


def _parse_string_args(values: Iterable[Any] | None) -> list[str]:
    parsed: list[str] = []
    for value in list(values or []):
        if isinstance(value, list | tuple):
            parsed.extend(_parse_string_args(value))
            continue
        for part in str(value).split(","):
            text = part.strip()
            if text:
                parsed.append(text)
    return parsed


def _parse_decision_training_weights(value: str | None) -> dict[str, float] | None:
    text = str(value or "").strip()
    if not text:
        return None
    weights: dict[str, float] = {}
    for item in text.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"decision training weight must be kind=value, got {item!r}")
        key, raw_weight = item.split("=", 1)
        kind = key.strip()
        if not kind:
            raise ValueError("decision training weight kind must be non-empty")
        weights[kind] = float(raw_weight)
    return weights or None


def _normalise_int_mapping(value: Mapping[str, int] | None) -> dict[str, int]:
    if not value:
        return {}
    out: dict[str, int] = {}
    for key, raw in value.items():
        text = str(key).strip()
        if not text:
            raise ValueError("mapping keys must be non-empty")
        out[text] = int(raw)
    return dict(sorted(out.items()))


def _parse_key_int_args(values: Iterable[str] | None) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for value in list(values or []):
        if isinstance(value, list | tuple):
            parsed.update(_parse_key_int_args(value))
            continue
        for part in str(value).split(","):
            text = part.strip()
            if not text:
                continue
            if "=" not in text:
                raise ValueError(f"expected key=value quota, got {text!r}")
            key, raw = text.split("=", 1)
            key = key.strip()
            if not key:
                raise ValueError(f"empty quota key in {text!r}")
            parsed[key] = int(raw.strip())
    return _normalise_int_mapping(parsed)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a sealed YGO-style online farm/train loop.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generation-seeds", nargs="+", required=True)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--max-tasks-per-cycle", type=int, default=96)
    parser.add_argument("--min-trainable-rows-per-cycle", type=int, default=512)
    parser.add_argument("--base-model-path", type=Path, default=DEFAULT_BASE_MODEL_PATH)
    parser.add_argument("--base-policy-id", default=DEFAULT_BASE_POLICY_ID)
    parser.add_argument("--candidate-model-id-prefix", required=True)
    parser.add_argument("--fixed-gate-seed", type=int, default=DEFAULT_FIXED_GATE_SEED)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--max-elapsed-seconds-per-cycle", type=float, default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--farm-decision-kind",
        "--farm-decision-kinds",
        action="append",
        nargs="+",
        default=None,
    )
    parser.add_argument(
        "--farm-min-action-set-snapshot",
        "--farm-min-action-set-snapshots-per-decision-kind",
        action="append",
        nargs="+",
        default=None,
        help="Farm snapshot minimums by decision kind, e.g. flash=3 blocker=3.",
    )
    parser.add_argument(
        "--farm-min-full-legal-group",
        "--farm-min-full-legal-groups-per-decision-kind",
        action="append",
        nargs="+",
        default=None,
        help="Farm full-legal group quota by decision kind, e.g. flash=8 blocker=8.",
    )
    parser.add_argument("--branch-rollout-samples", type=int, default=1)
    parser.add_argument("--max-branch-rows-per-task", type=int, default=16)
    parser.add_argument("--branch-max-actions", type=int, default=30)
    parser.add_argument("--game-prefix-max-actions", type=int, default=24)
    parser.add_argument("--game-prefix-hard-max-actions", type=int, default=96)
    parser.add_argument("--include-decision-kind", action="append", default=None)
    parser.add_argument(
        "--training-mode",
        choices=sorted(ONLINE_TRAINING_MODES),
        default=TRAINING_MODE_SANDBOX_POLICY_VALUE,
    )
    parser.add_argument("--learning-rate", type=float, default=None)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--eval-fraction", type=float, default=0.2)
    parser.add_argument("--runtime-aux-score-weight", type=float, default=0.03)
    parser.add_argument("--ppo-clip-coef", type=float, default=0.2)
    parser.add_argument("--value-loss-weight", type=float, default=0.25)
    parser.add_argument("--full-legal-policy-objective", default="search_improved_policy_ce")
    parser.add_argument("--policy-improvement-temperature", type=float, default=1.0)
    parser.add_argument("--policy-temperature", type=float, default=0.5)
    parser.add_argument("--high-gap-ranking-weight", type=float, default=0.25)
    parser.add_argument("--high-gap-threshold", type=float, default=DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING)
    parser.add_argument("--base-correct-preserve-weight", type=float, default=4.0)
    parser.add_argument("--anchor-kl-weight", type=float, default=0.5)
    parser.add_argument("--anchor-kl-temperature", type=float, default=1.0)
    parser.add_argument("--target-contract", default="action_value")
    parser.add_argument(
        "--decision-training-weights",
        default="",
        help="Comma-separated sandbox decision multipliers, e.g. main=1,flash=2.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_ygo_online_training_loop(
        out_dir=args.out_dir,
        run_id=args.run_id,
        generation_seeds=_parse_seeds(args.generation_seeds),
        cycles=args.cycles,
        max_tasks_per_cycle=args.max_tasks_per_cycle,
        min_trainable_rows_per_cycle=args.min_trainable_rows_per_cycle,
        base_model_path=args.base_model_path,
        base_policy_id=args.base_policy_id,
        candidate_model_id_prefix=args.candidate_model_id_prefix,
        fixed_gate_seed=args.fixed_gate_seed,
        max_workers=args.max_workers,
        max_elapsed_seconds_per_cycle=args.max_elapsed_seconds_per_cycle,
        device=args.device,
        farm_decision_kinds=_parse_string_args(args.farm_decision_kind),
        farm_min_action_set_snapshots_per_decision_kind=_parse_key_int_args(
            args.farm_min_action_set_snapshot
        ),
        farm_min_full_legal_groups_per_decision_kind=_parse_key_int_args(
            args.farm_min_full_legal_group
        ),
        branch_rollout_samples=args.branch_rollout_samples,
        max_branch_rows_per_task=args.max_branch_rows_per_task,
        branch_max_actions=args.branch_max_actions,
        game_prefix_max_actions=args.game_prefix_max_actions,
        game_prefix_hard_max_actions=args.game_prefix_hard_max_actions,
        include_decision_kinds=args.include_decision_kind,
        training_mode=args.training_mode,
        learning_rate=args.learning_rate,
        hidden_dim=args.hidden_dim,
        eval_fraction=args.eval_fraction,
        runtime_aux_score_weight=args.runtime_aux_score_weight,
        ppo_clip_coef=args.ppo_clip_coef,
        value_loss_weight=args.value_loss_weight,
        full_legal_policy_objective=args.full_legal_policy_objective,
        policy_improvement_temperature=args.policy_improvement_temperature,
        policy_temperature=args.policy_temperature,
        high_gap_ranking_weight=args.high_gap_ranking_weight,
        high_gap_threshold=args.high_gap_threshold,
        base_correct_preserve_weight=args.base_correct_preserve_weight,
        anchor_kl_weight=args.anchor_kl_weight,
        anchor_kl_temperature=args.anchor_kl_temperature,
        target_contract=args.target_contract,
        decision_training_weights=_parse_decision_training_weights(args.decision_training_weights),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
