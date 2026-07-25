from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.hidden_multiprocessing_spawn import install_hidden_multiprocessing_spawn
from tools.run_ygo_online_training_loop import (
    DEFAULT_FARM_DECISION_KINDS,
    DEFAULT_FIXED_GATE_SEED,
    TRAJECTORY_TRAINING_TABLE,
    _normalise_int_mapping,
    _parse_key_int_args,
    seal_sqlite_training_batch,
)
from tools.run_ygo_style_pairwise_training import (
    CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
    DEFAULT_MAX_CURRENT_POLICY_TRAINING_ROWS,
    DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING,
    YGO_CURRENT_POLICY_ENTROPY_COEF,
    _parse_anchor_kl_decision_weights,
    run_ygo_style_current_policy_training,
)
from zz.ygo_vector_actor_rollout import (
    DEFAULT_ORIGINAL_GAMES_PER_POOL,
    DEFAULT_ORIGINAL_OPPONENT_POLICY_IDS,
    DEFAULT_SELFPLAY_GAMES_PER_POOL,
    DEFAULT_TRAINING_POOL_SCHEDULE,
    DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP,
    EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE,
    PersistentYgoWorkerLocalVectorRolloutPool,
    run_ygo_vector_actor_rollout,
)
from zz.current_policy_actor_contract import (
    CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE,
    assert_current_policy_source_actor_ready,
    current_policy_runtime_weights_for_actor_model_path,
    load_current_policy_actor_artifact,
)


CURRENT_POLICY_LOOP_VERSION = "ygo_current_policy_loop_v1"
DEFAULT_BASE_MODEL_PATH: Path | None = None
_SUPPORTED_RECURRENT_TRAINING_MODES = {"disabled", "gru_domain_v1"}
MOVEMENT_READINESS_ALL_ROW_MIN = 0.55
MOVEMENT_READINESS_ACTOR_UPDATED_MIN = 0.65
MOVEMENT_READINESS_ACTOR_SIGN_MIN = 0.60
MOVEMENT_READINESS_GATE_DOMAIN_MIN = 0.50
YGO_CLEAN_GAE_PPO_ROUTE_PROFILE = "ygo_clean_gae_ppo_v1"
YGO_VTRACE_PPO_ROUTE_PROFILE = "ygo_vtrace_ppo_v1"
ROUTE_PROFILES = (
    "legacy",
    YGO_CLEAN_GAE_PPO_ROUTE_PROFILE,
    YGO_VTRACE_PPO_ROUTE_PROFILE,
)

FarmRunner = Callable[..., Mapping[str, Any]]
SealRunner = Callable[..., Mapping[str, Any]]
TrainingRunner = Callable[..., Mapping[str, Any]]


def _resolve_worker_local_vector_shape(
    *,
    vector_envs: int | None,
    vector_worker_count: int | None,
    vector_total_env_slots: int | None,
    max_workers: int,
    vector_worker_env_slots: int,
) -> dict[str, int | str | bool | None]:
    slots = max(1, int(vector_worker_env_slots))
    explicit_sources = [
        name
        for name, value in (
            ("vector_worker_count", vector_worker_count),
            ("vector_total_env_slots", vector_total_env_slots),
        )
        if value is not None
    ]
    if len(explicit_sources) > 1:
        raise ValueError("--vector-worker-count and --vector-total-env-slots are mutually exclusive")
    if vector_worker_count is not None:
        workers = max(1, int(vector_worker_count))
        total_slots = workers * slots
        source = "vector_worker_count"
    elif vector_total_env_slots is not None:
        total_slots = max(1, int(vector_total_env_slots))
        workers = max(1, int(math.ceil(total_slots / float(slots))))
        source = "vector_total_env_slots"
    else:
        workers = max(1, int(vector_envs if vector_envs is not None else max_workers))
        total_slots = workers * slots
        source = "legacy_vector_envs_as_worker_count"
    process_cap = DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP
    if workers > process_cap:
        raise ValueError(
            "worker-local vector rollout would start "
            f"{workers} worker processes (slots={slots}, totalEnvSlots={total_slots}). "
            "Use --vector-worker-count for process count or --vector-total-env-slots for YGO-style total env slots; "
            f"the current process cap is {process_cap}."
        )
    return {
        "worker_count": int(workers),
        "worker_env_slots": int(slots),
        "total_env_slots": int(workers * slots),
        "requested_total_env_slots": int(total_slots),
        "source": source,
        "legacy_vector_envs": None if vector_envs is None else int(vector_envs),
        "rounded_total_env_slots": bool(workers * slots != total_slots),
    }


def run_ygo_current_policy_loop(
    *,
    out_dir: str | Path,
    current_policy_id: str,
    seed: int = DEFAULT_FIXED_GATE_SEED,
    cycles: int = 1,
    tasks_per_cycle: int = 16,
    generation_seeds: Iterable[int] | None = None,
    min_trainable_rows_per_cycle: int = 1,
    max_workers: int = 8,
    max_elapsed_seconds_per_cycle: float | None = None,
    rollouts_per_update: int = 1,
    base_model_path: str | Path | None = DEFAULT_BASE_MODEL_PATH,
    device: str = "auto",
    farm_decision_kinds: Iterable[str] | None = None,
    farm_min_action_set_snapshots_per_decision_kind: Mapping[str, int] | None = None,
    farm_min_full_legal_groups_per_decision_kind: Mapping[str, int] | None = None,
    branch_rollout_samples: int = 1,
    max_branch_rows_per_task: int = 16,
    branch_max_actions: int = 80,
    game_prefix_max_actions: int | None = None,
    game_prefix_hard_max_actions: int | None = None,
    current_policy_rollout_selection_mode: str | None = "sampled_from_logits",
    current_policy_rollout_temperature: float = 1.0,
    candidate_policy_id: str | None = None,
    decision_training_weights: Mapping[str, float] | None = None,
    learning_rate: float = 0.0003,
    hidden_dim: int = 64,
    batch_size: int | None = None,
    num_minibatches: int | None = None,
    update_epochs: int = 1,
    allow_multi_epoch_current_policy_update: bool = False,
    eval_fraction: float = 0.0,
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
    actor_loss_min_abs_advantage: float = 0.0,
    actor_loss_advantage_sign_filter: str = "disabled",
    actor_loss_label_consistency_mode: str = "disabled",
    actor_loss_label_consistency_min_abs_advantage: float = 0.0,
    actor_loss_label_consistency_probe_modes: Iterable[str] | None = None,
    actor_loss_label_consistency_probe_max_training_rows: int | None = None,
    actor_loss_counter_signal_conflict_weight: float = 1.0,
    actor_advantage_source: str = "gae",
    q_backed_actor_residual_transfer_mode: str = "disabled",
    action_q_residual_loss_weight: float = 1.0,
    actor_loss_relative_mode: str = "selected_logprob",
    actor_loss_group_mode: str = "disabled",
    actor_legal_margin_weight: float = 0.0,
    actor_signature_drift_penalty_weight: float = 0.0,
    actor_signature_contrastive_weight: float = 0.0,
    actor_gradient_collision_audit_mode: str = "disabled",
    actor_linearized_representability_mode: str = "disabled",
    actor_linearized_cg_max_iterations: int = 64,
    actor_linearized_optimizer_diagnostics: str = "full",
    require_movement_readiness: bool = False,
    terminal_untrusted_actor_loss_max_steps_from_terminal: int = -1,
    post_training_diagnostics: str = "full",
    row_contract_mode: str = "full",
    entropy_coef: float = YGO_CURRENT_POLICY_ENTROPY_COEF,
    current_policy_actor_advantage_mode: str = "gae",
    current_policy_local_step_reward_weight: float = 0.0,
    current_policy_local_step_reward_probe_weights: Iterable[float] | None = None,
    detach_value_loss_recurrent_context: bool = False,
    critic_warmup_epochs: int | None = None,
    critic_warmup_recompute_advantage: bool = True,
    normalize_advantages: bool = False,
    advantage_normalization_mode: str = "scale_only",
    max_current_policy_training_rows: int | None = DEFAULT_MAX_CURRENT_POLICY_TRAINING_ROWS,
    domain_balance_training_weights: bool = False,
    gate_domain_weight_plan: Mapping[str, Any] | None = None,
    gate_domain_weight_plan_path: str | Path | None = None,
    no_learning_domain_audit: bool = False,
    online_transition_buffer: bool = False,
    persist_online_transition_rows: bool = False,
    persistent_worker_pool: bool = True,
    executor_factory: Callable[..., Any] = ProcessPoolExecutor,
    rollout_backend: str = "fast_farm",
    vector_envs: int | None = None,
    vector_worker_count: int | None = None,
    vector_total_env_slots: int | None = None,
    vector_worker_env_slots: int = 1,
    vector_worker_local_inference: bool = False,
    vector_steps: int = 128,
    vector_max_game_actions: int | None = None,
    vector_selfplay_games_per_pool: int = DEFAULT_SELFPLAY_GAMES_PER_POOL,
    vector_original_games_per_pool: int = DEFAULT_ORIGINAL_GAMES_PER_POOL,
    vector_original_opponent_policy_ids: Iterable[str] = DEFAULT_ORIGINAL_OPPONENT_POLICY_IDS,
    vector_training_pool_schedule: str = DEFAULT_TRAINING_POOL_SCHEDULE,
    vector_gate_task_specs: Sequence[Mapping[str, Any]] | None = None,
    vector_gate_deck_pool_payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    vector_inference_batch_size: int = 512,
    vector_inference_timeout_ms: int = 2,
    vector_worker_idle_timeout_seconds: float = 60.0,
    vector_bridge_decisions_per_env: int = 0,
    vector_drain_to_terminal: bool = False,
    vector_original_drain_to_terminal: bool = False,
    vector_selfplay_drain_to_terminal: bool = False,
    vector_rolling_env_state: bool = False,
    vector_execution_backend: str = "process",
    vector_compact_action_rows: bool = True,
    allow_unpromoted_launch_actor: bool = False,
    route_profile: str = "legacy",
) -> dict[str, Any]:
    """Run actor_N -> farm -> sealed batch -> one-epoch actor_N+1 cycles."""

    actor_id = str(current_policy_id or "").strip()
    if not actor_id:
        raise ValueError("current_policy_id must be non-empty")
    if int(cycles) <= 0:
        raise ValueError("cycles must be positive")
    if int(tasks_per_cycle) <= 0:
        raise ValueError("tasks_per_cycle must be positive")
    if int(min_trainable_rows_per_cycle) <= 0:
        raise ValueError("min_trainable_rows_per_cycle must be positive")
    if int(rollouts_per_update) <= 0:
        raise ValueError("rollouts_per_update must be positive")
    if batch_size is not None and int(batch_size) <= 0:
        raise ValueError("batch_size must be positive")
    if num_minibatches is not None and int(num_minibatches) <= 0:
        raise ValueError("num_minibatches must be positive")
    if batch_size is not None and num_minibatches is not None:
        raise ValueError("set batch_size or num_minibatches, not both")
    if vector_max_game_actions is not None and int(vector_max_game_actions) <= 0:
        raise ValueError("vector_max_game_actions must be positive")
    route_profile_name = str(route_profile or "legacy").strip().lower()
    if route_profile_name not in ROUTE_PROFILES:
        raise ValueError(f"unknown route_profile={route_profile!r}")
    rollout_backend_name = _normalise_rollout_backend(rollout_backend)
    if rollout_backend_name == "persistent_vector_batched" and not bool(online_transition_buffer):
        raise ValueError("persistent_vector_batched rollout requires online_transition_buffer=True")
    if int(rollouts_per_update) > 1 and not bool(online_transition_buffer):
        raise ValueError("rollouts_per_update > 1 requires online_transition_buffer=True")
    if bool(persist_online_transition_rows) and not bool(online_transition_buffer):
        raise ValueError("persist_online_transition_rows requires online_transition_buffer=True")
    if bool(no_learning_domain_audit) and not bool(online_transition_buffer):
        raise ValueError("no_learning_domain_audit requires online_transition_buffer=True")
    label_consistency_probe_modes = _normalise_label_consistency_modes(actor_loss_label_consistency_probe_modes)
    if label_consistency_probe_modes and not bool(online_transition_buffer):
        raise ValueError("actor_loss_label_consistency_probe_modes requires online_transition_buffer=True")
    local_step_reward_probe_weights = _normalise_local_step_reward_probe_weights(
        current_policy_local_step_reward_probe_weights
    )
    if local_step_reward_probe_weights and not bool(online_transition_buffer):
        raise ValueError("current_policy_local_step_reward_probe_weights requires online_transition_buffer=True")
    if (
        str(current_policy_rollout_selection_mode or "").strip().lower() == "sampled_from_logits"
        and abs(float(current_policy_rollout_temperature) - 1.0) > 1.0e-9
    ):
        raise ValueError(
            "sampled PPO currently requires current_policy_rollout_temperature=1.0; "
            "otherwise stored old logprobs and learner logprobs use different policy distributions"
        )
    _assert_ygo_vtrace_ppo_route_profile(
        route_profile=route_profile_name,
        rollout_backend_name=rollout_backend_name,
        online_transition_buffer=bool(online_transition_buffer),
        vector_drain_to_terminal=bool(vector_drain_to_terminal),
        vector_original_drain_to_terminal=bool(vector_original_drain_to_terminal),
        vector_selfplay_drain_to_terminal=bool(vector_selfplay_drain_to_terminal),
        vector_rolling_env_state=bool(vector_rolling_env_state),
        actor_advantage_source=str(actor_advantage_source),
        current_policy_actor_advantage_mode=str(current_policy_actor_advantage_mode or "gae"),
        q_backed_actor_residual_transfer_mode=str(q_backed_actor_residual_transfer_mode),
        state_action_interaction_mode=str(state_action_interaction_mode),
        actor_loss_relative_mode=str(actor_loss_relative_mode),
        actor_loss_sign_balance_mode=str(actor_loss_sign_balance_mode),
        actor_loss_advantage_sign_filter=str(actor_loss_advantage_sign_filter),
        actor_loss_label_consistency_mode=str(actor_loss_label_consistency_mode),
        actor_loss_counter_signal_conflict_weight=float(actor_loss_counter_signal_conflict_weight),
        actor_loss_group_mode=str(actor_loss_group_mode),
        actor_legal_margin_weight=float(actor_legal_margin_weight),
        actor_signature_drift_penalty_weight=float(actor_signature_drift_penalty_weight),
        actor_signature_contrastive_weight=float(actor_signature_contrastive_weight),
        current_policy_local_step_reward_weight=float(current_policy_local_step_reward_weight),
        normalize_advantages=bool(normalize_advantages),
        advantage_normalization_mode=str(advantage_normalization_mode),
        actor_linearized_representability_mode=str(actor_linearized_representability_mode),
        domain_gradient_conflict_mode=str(domain_gradient_conflict_mode),
        actor_loss_sequential_sign_steps=bool(actor_loss_sequential_sign_steps),
        actor_gradient_collision_audit_mode=str(actor_gradient_collision_audit_mode),
        decision_residual_policy_mode=str(decision_residual_policy_mode),
        multi_domain_objective_mode=str(multi_domain_objective_mode),
        retention_kl_mode=str(retention_kl_mode),
        anchor_kl_weight=float(anchor_kl_weight),
        actor_base_lr_multiplier=float(actor_base_lr_multiplier),
        state_action_interaction_lr_multiplier=float(state_action_interaction_lr_multiplier),
    )
    active_route_manifest = _build_active_route_manifest(
        route_profile_name=route_profile_name,
        rollout_backend_name=rollout_backend_name,
        online_transition_buffer=bool(online_transition_buffer),
        vector_drain_to_terminal=bool(vector_drain_to_terminal),
        vector_original_drain_to_terminal=bool(vector_original_drain_to_terminal),
        vector_selfplay_drain_to_terminal=bool(vector_selfplay_drain_to_terminal),
        vector_rolling_env_state=bool(vector_rolling_env_state),
        actor_advantage_source=str(actor_advantage_source),
        current_policy_actor_advantage_mode=str(current_policy_actor_advantage_mode or "gae"),
        current_policy_local_step_reward_weight=float(current_policy_local_step_reward_weight),
        normalize_advantages=bool(normalize_advantages),
        advantage_normalization_mode=str(advantage_normalization_mode),
        actor_loss_relative_mode=str(actor_loss_relative_mode),
        q_backed_actor_residual_transfer_mode=str(q_backed_actor_residual_transfer_mode),
        state_action_interaction_mode=str(state_action_interaction_mode),
        actor_loss_sign_balance_mode=str(actor_loss_sign_balance_mode),
        actor_loss_advantage_sign_filter=str(actor_loss_advantage_sign_filter),
        actor_loss_label_consistency_mode=str(actor_loss_label_consistency_mode),
        actor_loss_counter_signal_conflict_weight=float(actor_loss_counter_signal_conflict_weight),
        actor_loss_group_mode=str(actor_loss_group_mode),
        actor_legal_margin_weight=float(actor_legal_margin_weight),
        actor_signature_drift_penalty_weight=float(actor_signature_drift_penalty_weight),
        actor_signature_contrastive_weight=float(actor_signature_contrastive_weight),
        update_epochs=int(update_epochs),
        entropy_coef=float(entropy_coef),
        ppo_clip_coef=float(ppo_clip_coef),
        value_loss_weight=float(value_loss_weight),
        actor_linearized_representability_mode=str(actor_linearized_representability_mode),
        actor_linearized_optimizer_diagnostics=str(actor_linearized_optimizer_diagnostics),
        domain_gradient_conflict_mode=str(domain_gradient_conflict_mode),
        actor_loss_sequential_sign_steps=bool(actor_loss_sequential_sign_steps),
        actor_gradient_collision_audit_mode=str(actor_gradient_collision_audit_mode),
        decision_residual_policy_mode=str(decision_residual_policy_mode),
        multi_domain_objective_mode=str(multi_domain_objective_mode),
        retention_kl_mode=str(retention_kl_mode),
        anchor_kl_weight=float(anchor_kl_weight),
        actor_base_lr_multiplier=float(actor_base_lr_multiplier),
        state_action_interaction_lr_multiplier=float(state_action_interaction_lr_multiplier),
    )
    _assert_current_policy_loop_update_config(
        cycles=int(cycles),
        update_epochs=int(update_epochs),
        allow_multi_epoch_current_policy_update=bool(allow_multi_epoch_current_policy_update),
        actor_gradient_collision_audit_mode=str(actor_gradient_collision_audit_mode),
    )
    resolved_gate_domain_weight_plan = _resolve_gate_domain_weight_plan(
        gate_domain_weight_plan=gate_domain_weight_plan,
        gate_domain_weight_plan_path=gate_domain_weight_plan_path,
    )

    fixed_seed = int(seed)
    resolved_vector_max_game_actions = (
        int(vector_max_game_actions)
        if vector_max_game_actions is not None
        else (
            int(game_prefix_hard_max_actions)
            if game_prefix_hard_max_actions is not None
            else int(branch_max_actions)
        )
    )
    vector_original_opponent_ids = tuple(str(value) for value in vector_original_opponent_policy_ids)
    vector_schedule_name = str(vector_training_pool_schedule or DEFAULT_TRAINING_POOL_SCHEDULE).strip()
    if vector_schedule_name == "easy_top10_matrix_v1":
        vector_schedule_name = EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE
    if vector_schedule_name not in {DEFAULT_TRAINING_POOL_SCHEDULE, EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE}:
        raise ValueError(f"unknown vector_training_pool_schedule={vector_training_pool_schedule!r}")
    if rollout_backend_name == "persistent_vector_batched":
        vector_shape = _resolve_worker_local_vector_shape(
            vector_envs=vector_envs,
            vector_worker_count=vector_worker_count,
            vector_total_env_slots=vector_total_env_slots,
            max_workers=max_workers,
            vector_worker_env_slots=vector_worker_env_slots,
        )
    else:
        vector_shape = {
            "worker_count": max(1, int(vector_envs if vector_envs is not None else max_workers)),
            "worker_env_slots": max(1, int(vector_worker_env_slots)),
            "total_env_slots": max(1, int(vector_envs if vector_envs is not None else max_workers))
            * max(1, int(vector_worker_env_slots)),
            "requested_total_env_slots": max(1, int(vector_envs if vector_envs is not None else max_workers))
            * max(1, int(vector_worker_env_slots)),
            "source": "unused_fast_farm",
            "legacy_vector_envs": None if vector_envs is None else int(vector_envs),
            "rounded_total_env_slots": False,
        }
    rollouts_per_update_count = max(1, int(rollouts_per_update))
    cycle_generation_seed_batches = _cycle_generation_seed_batches(
        generation_seeds=generation_seeds,
        cycles=int(cycles) * int(rollouts_per_update_count),
        fixed_gate_seed=fixed_seed,
    )
    decision_kinds = tuple(_normalise_decision_kinds(farm_decision_kinds))
    _assert_current_policy_farm_full_coverage(decision_kinds)
    farm_snapshot_minimums = _normalise_int_mapping(farm_min_action_set_snapshots_per_decision_kind)
    farm_full_legal_minimums = _normalise_int_mapping(farm_min_full_legal_groups_per_decision_kind)
    if not farm_full_legal_minimums:
        farm_full_legal_minimums = {kind: 1 for kind in decision_kinds}
    source_actor_contract = _resolve_current_policy_source_actor(
        actor_id,
        explicit_base_model_path=base_model_path,
        decision_kinds=decision_kinds,
        allow_unpromoted_launch_actor=bool(allow_unpromoted_launch_actor),
    )
    resolved_base_model_path = Path(str(source_actor_contract["modelPath"]))
    initial_model_path = Path(resolved_base_model_path)
    source_actor_id = str(source_actor_contract.get("actorPolicyId") or actor_id).strip()
    resolved_recurrent_training_mode = _resolve_recurrent_training_mode(
        requested_mode=recurrent_training_mode,
        source_model_path=resolved_base_model_path,
    )
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    initial_policy_id = actor_id
    requested_candidate_policy_id = str(candidate_policy_id or "").strip()
    cycle_reports: list[dict[str, Any]] = []
    shared_executor: Any | None = None
    shared_vector_pool: PersistentYgoWorkerLocalVectorRolloutPool | None = None
    shared_worker_pool_enabled = (
        rollout_backend_name == "fast_farm"
        and bool(online_transition_buffer)
        and bool(persistent_worker_pool)
        and int(max_workers) > 1
    )
    shared_vector_pool_enabled = (
        rollout_backend_name == "persistent_vector_batched"
        and bool(online_transition_buffer)
        and bool(persistent_worker_pool)
        and bool(vector_rolling_env_state)
    )
    def _new_shared_vector_pool() -> PersistentYgoWorkerLocalVectorRolloutPool:
        return PersistentYgoWorkerLocalVectorRolloutPool(
            worker_count=int(vector_shape["worker_count"]),
            worker_env_slots=int(vector_shape["worker_env_slots"]),
            num_steps=int(vector_steps),
            inference_batch_size=int(vector_inference_batch_size),
            inference_timeout_ms=int(vector_inference_timeout_ms),
            worker_idle_timeout_seconds=float(vector_worker_idle_timeout_seconds),
            action_set_max_actions=128,
            max_game_actions=int(resolved_vector_max_game_actions),
            max_games_per_env=int(tasks_per_cycle),
            selfplay_games_per_pool=int(vector_selfplay_games_per_pool),
            original_games_per_pool=int(vector_original_games_per_pool),
            original_opponent_policy_ids=vector_original_opponent_ids,
            training_pool_schedule=vector_schedule_name,
            max_bridge_decisions_per_env=int(vector_bridge_decisions_per_env),
            drain_to_terminal=bool(vector_drain_to_terminal),
            original_drain_to_terminal=bool(vector_original_drain_to_terminal),
            selfplay_drain_to_terminal=bool(vector_selfplay_drain_to_terminal),
            rolling_env_state=bool(vector_rolling_env_state),
            execution_backend=str(vector_execution_backend),
            compact_action_rows=bool(vector_compact_action_rows),
            current_policy_rollout_selection_mode=current_policy_rollout_selection_mode,
            current_policy_rollout_temperature=float(current_policy_rollout_temperature),
            sqlite_debug_log=False,
            gate_task_specs=vector_gate_task_specs,
            gate_deck_pool_payloads=vector_gate_deck_pool_payloads,
        )

    if shared_worker_pool_enabled:
        install_hidden_multiprocessing_spawn()
        shared_executor = executor_factory(max_workers=max(1, int(max_workers)))
    if shared_vector_pool_enabled:
        if str(vector_execution_backend).strip().lower() == "process":
            install_hidden_multiprocessing_spawn()
        shared_vector_pool = _new_shared_vector_pool()

    def _run_rollout_shard(
        *,
        cycle_id: str,
        cycle_index: int,
        cycle_dir: Path,
        shard_index: int,
        shard_count: int,
        shard_seeds: tuple[int, ...],
        source_actor_id: str,
        source_model_path: Path,
    ) -> dict[str, Any]:
        nonlocal shared_vector_pool
        shard_suffix = f"rollout-{int(shard_index) + 1:04d}"
        farm_dir = cycle_dir / "farm" if int(shard_count) == 1 else cycle_dir / "farm" / shard_suffix
        run_id = f"current-policy-{cycle_id}" if int(shard_count) == 1 else f"current-policy-{cycle_id}-{shard_suffix}"
        if rollout_backend_name == "persistent_vector_batched":
            if shared_vector_pool is not None:
                rollout_kwargs = {
                    "out_dir": farm_dir,
                    "run_id": run_id,
                    "generation_seeds": shard_seeds,
                    "fixed_gate_seed": fixed_seed,
                    "seed": fixed_seed,
                    "actor_id": source_actor_id,
                    "current_policy_model_path": source_model_path,
                    "training_pool_schedule_cycle_index": int(cycle_index),
                }
                try:
                    return dict(shared_vector_pool.rollout(**rollout_kwargs))
                except TimeoutError as first_timeout:
                    try:
                        shared_vector_pool.close()
                    finally:
                        shared_vector_pool = _new_shared_vector_pool()
                    farm_report = dict(shared_vector_pool.rollout(**rollout_kwargs))
                    farm_report["persistentWorkerPoolRetry"] = {
                        "retriedAfterTimeout": True,
                        "attempts": 2,
                        "firstError": str(first_timeout),
                    }
                    return farm_report
            return dict(
                run_ygo_vector_actor_rollout(
                    out_dir=farm_dir,
                    run_id=run_id,
                    generation_seeds=shard_seeds,
                    fixed_gate_seed=fixed_seed,
                    seed=fixed_seed,
                    current_policy_id=source_actor_id,
                    current_policy_model_path=source_model_path,
                    env_count=int(vector_shape["total_env_slots"]),
                    worker_env_slots=int(vector_shape["worker_env_slots"]),
                    worker_local_inference=bool(vector_worker_local_inference),
                    num_steps=int(vector_steps),
                    selfplay_games_per_pool=int(vector_selfplay_games_per_pool),
                    original_games_per_pool=int(vector_original_games_per_pool),
                    original_opponent_policy_ids=vector_original_opponent_ids,
                    training_pool_schedule=vector_schedule_name,
                    training_pool_schedule_cycle_index=int(cycle_index),
                    gate_task_specs=vector_gate_task_specs,
                    gate_deck_pool_payloads=vector_gate_deck_pool_payloads,
                    inference_batch_size=int(vector_inference_batch_size),
                    inference_timeout_ms=int(vector_inference_timeout_ms),
                    worker_idle_timeout_seconds=float(vector_worker_idle_timeout_seconds),
                    max_bridge_decisions_per_env=int(vector_bridge_decisions_per_env),
                    drain_to_terminal=bool(vector_drain_to_terminal),
                    original_drain_to_terminal=bool(vector_original_drain_to_terminal),
                    selfplay_drain_to_terminal=bool(vector_selfplay_drain_to_terminal),
                    rolling_env_state=False,
                    execution_backend=str(vector_execution_backend),
                    compact_action_rows=bool(vector_compact_action_rows),
                    current_policy_rollout_selection_mode=current_policy_rollout_selection_mode,
                    current_policy_rollout_temperature=float(current_policy_rollout_temperature),
                    max_game_actions=int(resolved_vector_max_game_actions),
                    sqlite_debug_log=False,
                )
            )
        return dict(
            _run_ygo_fast_farm(
                out_dir=farm_dir,
                run_id=run_id,
                generation_seeds=shard_seeds,
                fixed_gate_seed=fixed_seed,
                policy_id=actor_id,
                current_policy_id=actor_id,
                current_policy_model_path=source_model_path,
                max_ai_decks=0,
                max_tasks=int(tasks_per_cycle),
                max_workers=int(max_workers),
                max_elapsed_seconds=max_elapsed_seconds_per_cycle,
                max_branch_rows_per_task=int(max_branch_rows_per_task),
                branch_max_actions=int(branch_max_actions),
                branch_rollout_samples=max(1, int(branch_rollout_samples)),
                current_policy_rollout_selection_mode=current_policy_rollout_selection_mode,
                current_policy_rollout_temperature=float(current_policy_rollout_temperature),
                record_all_action_set_sides=False,
                game_prefix_max_actions=(
                    None if game_prefix_max_actions is None else int(game_prefix_max_actions)
                ),
                game_prefix_hard_max_actions=(
                    None
                    if game_prefix_hard_max_actions is None
                    else int(game_prefix_hard_max_actions)
                ),
                decision_kinds=decision_kinds,
                min_action_set_snapshots_per_decision_kind=farm_snapshot_minimums or None,
                min_full_legal_groups_per_decision_kind=farm_full_legal_minimums or None,
                return_trajectory_rows=bool(online_transition_buffer),
                return_bridge_rows=bridge_rows_requested,
                task_builder=farm_task_builder,
                evaluator=farm_evaluator,
                executor=shared_executor,
                executor_factory=executor_factory,
            )
        )

    def _run_ygo_fast_farm(**kwargs: Any) -> Mapping[str, Any]:
        from tools.run_ygo_fast_farm import run_ygo_fast_farm

        return run_ygo_fast_farm(**kwargs)

    def _run_current_policy_bridge_audit(
        rows: Iterable[Mapping[str, Any]],
        *,
        candidate_model_path: str,
        candidate_policy_id: str,
    ) -> Mapping[str, Any]:
        from tools.audit_ygo_current_policy_bridge import audit_current_policy_bridge_rows

        return audit_current_policy_bridge_rows(
            rows,
            candidate_model_path=candidate_model_path,
            candidate_policy_id=candidate_policy_id,
            min_gate_rows=0,
        )

    def _load_current_policy_bridge_rows(path: str | Path) -> list[dict[str, Any]]:
        from tools.audit_ygo_current_policy_bridge import load_current_policy_bridge_rows

        return load_current_policy_bridge_rows(path)
    try:
        for cycle_index in range(int(cycles)):
            if cycle_index:
                source_actor_contract = _resolve_current_policy_source_actor(
                    actor_id,
                    explicit_base_model_path=resolved_base_model_path,
                    decision_kinds=decision_kinds,
                    allow_unpromoted_launch_actor=True,
                )
                source_actor_id = str(source_actor_contract.get("actorPolicyId") or actor_id).strip()
            cycle_id = f"cycle-{cycle_index + 1:04d}"
            cycle_dir = root / cycle_id
            train_dir = cycle_dir / "train"

            in_memory_trajectory_rows: list[dict[str, Any]] = []
            in_memory_bridge_rows: list[dict[str, Any]] = []
            trainable_rows = 0
            cycle_seed_values: list[int] = []
            rollout_shards: list[dict[str, Any]] = []
            farm_report: dict[str, Any] = {}
            for shard_index in range(int(rollouts_per_update_count)):
                seed_batch_index = int(cycle_index) * int(rollouts_per_update_count) + int(shard_index)
                cycle_seeds = tuple(int(value) for value in cycle_generation_seed_batches[seed_batch_index])
                cycle_seed_values.extend(int(value) for value in cycle_seeds)
                shard_report = _run_rollout_shard(
                    cycle_id=cycle_id,
                    cycle_index=cycle_index,
                    cycle_dir=cycle_dir,
                    shard_index=shard_index,
                    shard_count=int(rollouts_per_update_count),
                    shard_seeds=cycle_seeds,
                    source_actor_id=source_actor_id,
                    source_model_path=resolved_base_model_path,
                )
                _assert_clean_farm_report(shard_report)
                shard_trainable_rows = int(shard_report.get("trainableTrajectoryRows", 0) or 0)
                shard_trajectory_rows = _mapping_row_list(shard_report.get("_trajectoryRows"))
                if bool(online_transition_buffer) and len(shard_trajectory_rows) != shard_trainable_rows:
                    raise ValueError(
                        "online transition buffer row count mismatch: "
                        f"farm trainableTrajectoryRows={shard_trainable_rows}, bufferRows={len(shard_trajectory_rows)}"
                    )
                shard_bridge_rows = _mapping_row_list(shard_report.get("_bridgeRows"))
                trainable_rows += int(shard_trainable_rows)
                in_memory_trajectory_rows.extend(shard_trajectory_rows)
                in_memory_bridge_rows.extend(shard_bridge_rows)
                shard_report.pop("_trajectoryRows", None)
                shard_report.pop("_bridgeRows", None)
                shard_report.pop("_gameRows", None)
                compact_shard = _compact_farm_report(shard_report)
                compact_shard["shardIndex"] = int(shard_index + 1)
                compact_shard["generationSeeds"] = [int(value) for value in cycle_seeds]
                rollout_shards.append(compact_shard)
                farm_report = shard_report
            if int(rollouts_per_update_count) > 1:
                farm_report = _merged_rollout_farm_report(rollout_shards)
            bridge_rows_requested = bool(online_transition_buffer) and int(vector_bridge_decisions_per_env) > 0
            if bridge_rows_requested and not in_memory_bridge_rows:
                raise ValueError("online transition buffer did not return bridge audit rows")
            domain_balance_report: dict[str, Any] = {"enabled": False}
            if bool(domain_balance_training_weights) and bool(online_transition_buffer):
                in_memory_trajectory_rows, domain_balance_report = _apply_domain_balance_training_weights(
                    in_memory_trajectory_rows,
                    gate_domain_weight_plan=resolved_gate_domain_weight_plan,
                )
            persisted_transition_rows: dict[str, Any] | None = None
            persisted_transition_rows_path: Path | None = None
            if bool(persist_online_transition_rows):
                persisted_transition_rows_path = cycle_dir / "fixed_batch" / "current_policy_trajectory_rows.json"
                persisted_transition_rows = _persist_online_transition_rows(
                    in_memory_trajectory_rows,
                    persisted_transition_rows_path,
                )
            cycle_report: dict[str, Any] = {
                "cycleId": cycle_id,
                "registeredPolicyId": actor_id,
                "actorPolicyId": source_actor_id,
                "sourceActorContract": source_actor_contract,
                "generationSeeds": [int(value) for value in cycle_seed_values],
                "rolloutsPerUpdate": int(rollouts_per_update_count),
                "rolloutShards": rollout_shards,
                "farmReport": _compact_farm_report(farm_report),
                "transitionBuffer": {
                    "mode": "in_memory" if bool(online_transition_buffer) else "sealed_sqlite",
                    "rows": int(len(in_memory_trajectory_rows)) if bool(online_transition_buffer) else 0,
                    "bridgeRows": int(len(in_memory_bridge_rows)) if bool(online_transition_buffer) else 0,
                    "sqliteHotPath": not bool(online_transition_buffer),
                    "jsonHotPath": bool(persisted_transition_rows),
                },
                "transitionDomainReport": _transition_domain_report(in_memory_trajectory_rows),
                "domainBalanceTrainingWeights": domain_balance_report,
                "noLearningDomainAuditRequested": bool(no_learning_domain_audit),
                "trainingLaunched": False,
            }
            if persisted_transition_rows is not None:
                cycle_report["transitionBuffer"].update(persisted_transition_rows)
            training_batching = _training_batching_report(
                transition_rows=(
                    min(trainable_rows, int(max_current_policy_training_rows))
                    if max_current_policy_training_rows is not None and int(max_current_policy_training_rows) > 0
                    else trainable_rows
                ),
                batch_size=batch_size,
                num_minibatches=num_minibatches,
            )
            cycle_report["trainingBatching"] = training_batching
            if bool(no_learning_domain_audit):
                cycle_report["skipReason"] = "no_learning_domain_audit"
                cycle_report["noLearningDomainAudit"] = _no_learning_domain_audit_report(
                    rows=in_memory_trajectory_rows,
                    domain_report=cycle_report["transitionDomainReport"],
                    domain_balance_report=domain_balance_report,
                    training_batching=training_batching,
                    expected_original_opponent_policy_ids=vector_original_opponent_ids,
                )
                cycle_reports.append(cycle_report)
                in_memory_trajectory_rows.clear()
                in_memory_bridge_rows.clear()
                continue
            if trainable_rows < int(min_trainable_rows_per_cycle):
                cycle_report["skipReason"] = "insufficient_trainable_rows"
                cycle_reports.append(cycle_report)
                in_memory_trajectory_rows.clear()
                in_memory_bridge_rows.clear()
                continue

            sealed_report: dict[str, Any] | None = None
            sealed_db_path: Path | None = None
            if not bool(online_transition_buffer):
                sealed_report = dict(
                    seal_sqlite_training_batch(
                        source_db_path=_farm_training_db_path(farm_report),
                        sealed_db_path=cycle_dir / "sealed" / "sealed_training_batch.sqlite",
                        batch_id=cycle_id,
                        source_report=farm_report,
                        training_table=TRAJECTORY_TRAINING_TABLE,
                    )
                )
                sealed_db_path = _sealed_training_db_path(
                    sealed_report,
                    default_path=cycle_dir / "sealed" / "sealed_training_batch.sqlite",
                )
                _assert_clean_sealed_batch_report(
                    sealed_report,
                    farm_report=farm_report,
                    expected_sealed_db_path=sealed_db_path,
                )

            final_review_update = cycle_index + 1 >= int(cycles)
            effective_post_training_diagnostics = (
                str(post_training_diagnostics)
                if final_review_update or str(post_training_diagnostics) != "full"
                else "skip"
            )
            effective_row_contract_mode = (
                str(row_contract_mode)
                if final_review_update or str(row_contract_mode) != "full"
                else "fast_preflight"
            )
            training_kwargs: dict[str, Any] = {
                "out_dir": train_dir,
                "actor_policy_id": source_actor_id,
                "candidate_policy_id": _cycle_candidate_policy_id(
                    requested_candidate_policy_id=requested_candidate_policy_id,
                    initial_policy_id=initial_policy_id,
                    fixed_seed=fixed_seed,
                    cycle_index=cycle_index,
                    cycles=int(cycles),
                ),
                "base_model_path": resolved_base_model_path,
                "update_epochs": int(update_epochs),
                "learning_rate": float(learning_rate),
                "hidden_dim": int(hidden_dim),
                "batch_size": int(training_batching["effectiveBatchSize"]),
                "eval_fraction": float(eval_fraction),
                "seed": fixed_seed,
                "decision_training_weights": dict(decision_training_weights or {}),
                "policy_temperature": float(policy_temperature),
                "ppo_clip_coef": float(ppo_clip_coef),
                "value_loss_weight": float(value_loss_weight),
                "high_gap_ranking_weight": float(high_gap_ranking_weight),
                "high_gap_threshold": float(high_gap_threshold),
                "anchor_kl_weight": float(anchor_kl_weight),
                "anchor_kl_temperature": float(anchor_kl_temperature),
                "retention_kl_mode": str(retention_kl_mode),
                "domain_gradient_conflict_mode": str(domain_gradient_conflict_mode),
                "multi_domain_objective_mode": str(multi_domain_objective_mode),
                "recurrent_training_mode": str(resolved_recurrent_training_mode),
                "decision_residual_policy_mode": str(decision_residual_policy_mode),
                "state_action_interaction_mode": str(state_action_interaction_mode),
                "state_action_interaction_rank": int(state_action_interaction_rank),
                "state_action_interaction_init_scale": float(state_action_interaction_init_scale),
                "state_action_interaction_lr_multiplier": float(state_action_interaction_lr_multiplier),
                "actor_base_lr_multiplier": float(actor_base_lr_multiplier),
                "actor_update_requires_trusted_value": bool(actor_update_requires_trusted_value),
                "actor_trusted_value_ev_threshold": float(actor_trusted_value_ev_threshold),
                "selfplay_actor_loss_cap_fraction": float(selfplay_actor_loss_cap_fraction),
                "original_terminal_actor_loss_min_fraction": float(original_terminal_actor_loss_min_fraction),
                "actor_loss_max_rows_per_domain": int(actor_loss_max_rows_per_domain),
                "actor_loss_sign_balance_mode": str(actor_loss_sign_balance_mode),
                "actor_loss_sequential_sign_steps": bool(actor_loss_sequential_sign_steps),
                "actor_loss_min_abs_advantage": float(actor_loss_min_abs_advantage),
                "actor_loss_advantage_sign_filter": str(actor_loss_advantage_sign_filter),
                "actor_loss_label_consistency_mode": str(actor_loss_label_consistency_mode),
                "actor_loss_label_consistency_min_abs_advantage": float(actor_loss_label_consistency_min_abs_advantage),
                "actor_loss_counter_signal_conflict_weight": float(actor_loss_counter_signal_conflict_weight),
                "actor_advantage_source": str(actor_advantage_source),
                "q_backed_actor_residual_transfer_mode": str(q_backed_actor_residual_transfer_mode),
                "action_q_residual_loss_weight": float(action_q_residual_loss_weight),
                "actor_loss_relative_mode": str(actor_loss_relative_mode),
                "actor_loss_group_mode": str(actor_loss_group_mode),
                "actor_legal_margin_weight": float(actor_legal_margin_weight),
                "actor_signature_drift_penalty_weight": float(actor_signature_drift_penalty_weight),
                "actor_signature_contrastive_weight": float(actor_signature_contrastive_weight),
                "actor_gradient_collision_audit_mode": str(actor_gradient_collision_audit_mode),
                "actor_linearized_representability_mode": str(actor_linearized_representability_mode),
                "actor_linearized_cg_max_iterations": int(actor_linearized_cg_max_iterations),
                "actor_linearized_optimizer_diagnostics": str(actor_linearized_optimizer_diagnostics),
                "terminal_untrusted_actor_loss_max_steps_from_terminal": int(terminal_untrusted_actor_loss_max_steps_from_terminal),
                "post_training_diagnostics": effective_post_training_diagnostics,
                "row_contract_mode": effective_row_contract_mode,
                "allow_multi_epoch_current_policy_update": bool(allow_multi_epoch_current_policy_update),
                "entropy_coef": float(entropy_coef),
                "current_policy_actor_advantage_mode": str(current_policy_actor_advantage_mode or "gae"),
                "current_policy_local_step_reward_weight": float(current_policy_local_step_reward_weight),
                "detach_value_loss_recurrent_context": bool(detach_value_loss_recurrent_context),
                "critic_warmup_epochs": critic_warmup_epochs,
                "critic_warmup_recompute_advantage": bool(critic_warmup_recompute_advantage),
                "normalize_advantages": bool(normalize_advantages),
                "advantage_normalization_mode": str(advantage_normalization_mode),
                "max_training_rows": max_current_policy_training_rows,
                "require_old_policy_values": bool(online_transition_buffer),
                "device": str(device),
                "allow_unreviewed_restart": True,
                "allow_unpromoted_source_actor": bool(allow_unpromoted_launch_actor),
                "allow_missing_play_card_target_semantics": False,
            }
            if bool(online_transition_buffer):
                if persisted_transition_rows_path is not None:
                    training_kwargs["training_rows_path"] = persisted_transition_rows_path
                else:
                    training_kwargs["training_rows"] = list(in_memory_trajectory_rows)
            else:
                training_kwargs["training_rows_path"] = sealed_db_path
            if label_consistency_probe_modes or local_step_reward_probe_weights:
                probe_modes = label_consistency_probe_modes or (str(actor_loss_label_consistency_mode),)
                probe_weights = local_step_reward_probe_weights or (float(current_policy_local_step_reward_weight),)
                probe_reports: list[dict[str, Any]] = []
                for mode in probe_modes:
                    for local_weight in probe_weights:
                        probe_kwargs = dict(training_kwargs)
                        weight_tag = _local_step_reward_weight_tag(float(local_weight))
                        probe_kwargs["out_dir"] = (
                            train_dir
                            / "label_consistency_probe"
                            / str(mode)
                            / f"local_step_reward_weight_{weight_tag}"
                        )
                        probe_kwargs["candidate_policy_id"] = (
                            f"{_cycle_candidate_policy_id(requested_candidate_policy_id=requested_candidate_policy_id, initial_policy_id=initial_policy_id, fixed_seed=fixed_seed, cycle_index=cycle_index, cycles=int(cycles)) or source_actor_id}_probe_{str(mode)}_localw_{weight_tag}"
                        )
                        probe_kwargs["actor_loss_label_consistency_mode"] = str(mode)
                        probe_kwargs["actor_loss_label_consistency_min_abs_advantage"] = float(
                            actor_loss_label_consistency_min_abs_advantage
                        )
                        probe_kwargs["current_policy_local_step_reward_weight"] = float(local_weight)
                        if (
                            actor_loss_label_consistency_probe_max_training_rows is not None
                            and int(actor_loss_label_consistency_probe_max_training_rows) > 0
                        ):
                            probe_kwargs["max_training_rows"] = int(
                                actor_loss_label_consistency_probe_max_training_rows
                            )
                        if bool(online_transition_buffer) and persisted_transition_rows_path is None:
                            probe_kwargs["training_rows"] = _copy_probe_training_rows(in_memory_trajectory_rows)
                        probe_report = dict(run_ygo_style_current_policy_training(**probe_kwargs))
                        compact_probe_report = _compact_label_consistency_probe_training_report(
                            mode=str(mode),
                            local_step_reward_weight=float(local_weight),
                            report=probe_report,
                        )
                        probe_reports.append(compact_probe_report)
                        probe_report_path = Path(probe_kwargs["out_dir"]) / "label_consistency_probe_report.json"
                        probe_report_path.parent.mkdir(parents=True, exist_ok=True)
                        probe_report_path.write_text(
                            json.dumps(compact_probe_report, ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8",
                        )
                        probe_kwargs.pop("training_rows", None)
                        probe_report.clear()
                probe_weights_payload: list[float] | None = (
                    [float(value) for value in probe_weights]
                    if local_step_reward_probe_weights
                    else None
                )
                probe_modes_payload: list[str] | None = (
                    [str(value) for value in probe_modes]
                    if label_consistency_probe_modes
                    else None
                )
                cycle_report.update(
                    {
                        "trainingLaunched": False,
                        "skipReason": "label_consistency_probe_only",
                        "labelConsistencyProbeLaunched": True,
                        "labelConsistencyProbe": {
                            "kind": "actor_loss_label_consistency_probe_v1",
                            "sameBatchRows": int(len(in_memory_trajectory_rows)),
                            "valueLossWeight": float(value_loss_weight),
                            "normalizeAdvantages": bool(normalize_advantages),
                            "maxCurrentPolicyTrainingRows": (
                                None
                                if max_current_policy_training_rows is None
                                else int(max_current_policy_training_rows)
                            ),
                            "probeMaxTrainingRows": (
                                None
                                if actor_loss_label_consistency_probe_max_training_rows is None
                                else int(actor_loss_label_consistency_probe_max_training_rows)
                            ),
                            "modes": probe_reports,
                            "requestedModes": probe_modes_payload,
                            "localStepRewardProbeWeights": probe_weights_payload,
                        },
                    }
                )
                cycle_reports.append(cycle_report)
                in_memory_trajectory_rows.clear()
                in_memory_bridge_rows.clear()
                farm_report.clear()
                continue
            training_report = dict(run_ygo_style_current_policy_training(**training_kwargs))
            training_kwargs.pop("training_rows", None)
            movement_readiness = _current_policy_movement_readiness_report(training_report)
            training_report["currentPolicyMovementReadiness"] = movement_readiness
            _assert_current_policy_training_report_invariants(
                training_report,
                expected_update_epochs=int(update_epochs),
                expected_allow_multi_epoch=bool(allow_multi_epoch_current_policy_update),
                expected_value_loss_weight=float(value_loss_weight),
                expected_normalize_advantages=bool(normalize_advantages),
                expected_advantage_normalization_mode=str(advantage_normalization_mode),
                expected_actor_loss_sign_balance_mode=str(actor_loss_sign_balance_mode),
                expected_actor_loss_label_consistency_mode=str(actor_loss_label_consistency_mode),
                expected_actor_loss_counter_signal_conflict_weight=float(actor_loss_counter_signal_conflict_weight),
                expected_actor_loss_relative_mode=str(actor_loss_relative_mode),
                expected_actor_advantage_source=str(actor_advantage_source),
                expected_q_backed_actor_residual_transfer_mode=str(q_backed_actor_residual_transfer_mode),
                expected_recurrent_training_mode=str(resolved_recurrent_training_mode),
                expected_candidate_policy_id=str(training_kwargs.get("candidate_policy_id") or ""),
            )
            if bool(require_movement_readiness) and movement_readiness.get("passed") is not True:
                blockers = ", ".join(str(item) for item in movement_readiness.get("blockers", []))
                raise ValueError(f"current-policy movement readiness failed: {blockers}")
            produced_candidate_policy_id = str(training_report.get("candidatePolicyId") or "").strip()
            if not produced_candidate_policy_id:
                raise ValueError("current-policy training report is missing candidatePolicyId")
            if not bool(training_report.get("runtimeLaunchableActor")):
                raise ValueError("current-policy training report is not runtimeLaunchableActor")
            candidate_model_path_value = str(training_report.get("candidateModelPath") or "").strip()
            if not candidate_model_path_value:
                raise ValueError("current-policy training report is missing candidateModelPath")
            bridge_report: dict[str, Any] | None = None
            bridge_report_path: Path | None = None
            if in_memory_bridge_rows or not bool(online_transition_buffer):
                bridge_report = dict(
                    _run_current_policy_bridge_audit(
                        in_memory_bridge_rows
                        if bool(online_transition_buffer)
                        else _load_current_policy_bridge_rows(_farm_training_db_path(farm_report)),
                        candidate_model_path=candidate_model_path_value,
                        candidate_policy_id=produced_candidate_policy_id,
                    )
                )
                bridge_report_path = train_dir / "current_policy_bridge_audit.json"
                bridge_report_path.parent.mkdir(parents=True, exist_ok=True)
                bridge_report_path.write_text(
                    json.dumps(bridge_report, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                _assert_clean_bridge_report(bridge_report)

            cycle_update: dict[str, Any] = {
                "sealedBatch": sealed_report,
                "trainingLaunched": True,
                "trainingReport": _compact_training_report(training_report),
                "candidatePolicyId": produced_candidate_policy_id,
                "candidateModelPath": training_report.get("candidateModelPath"),
            }
            if bridge_report is not None and bridge_report_path is not None:
                cycle_update["bridgeAudit"] = _compact_bridge_report(bridge_report)
                cycle_update["bridgeAuditPath"] = str(bridge_report_path)
            else:
                cycle_update["bridgeAuditSkipped"] = "vector_bridge_decisions_per_env=0"
            cycle_report.update(cycle_update)
            cycle_reports.append(cycle_report)
            actor_id = produced_candidate_policy_id
            source_actor_id = produced_candidate_policy_id
            resolved_base_model_path = Path(candidate_model_path_value)
            in_memory_trajectory_rows.clear()
            in_memory_bridge_rows.clear()
            training_report.clear()
            farm_report.clear()
    finally:
        if shared_executor is not None:
            shutdown = getattr(shared_executor, "shutdown", None)
            if callable(shutdown):
                shutdown(wait=True, cancel_futures=False)
        if shared_vector_pool is not None:
            shared_vector_pool.close()

    report = {
        "kind": CURRENT_POLICY_LOOP_VERSION,
        "createdAt": _utc_now(),
        "outDir": str(root),
        "initialPolicyId": initial_policy_id,
        "finalPolicyId": actor_id,
        "cyclesRequested": int(cycles),
        "cyclesCompleted": len(cycle_reports),
        "trainingCycles": int(sum(1 for cycle in cycle_reports if cycle.get("trainingLaunched"))),
        "fixedGateSeed": fixed_seed,
        "generationSeeds": [
            int(value)
            for batch in cycle_generation_seed_batches
            for value in batch
        ],
        "rolloutsPerUpdate": int(rollouts_per_update_count),
        "currentPolicyMainline": "unified_current_policy_actor_value",
        "routeProfile": route_profile_name,
        "activeRouteManifest": active_route_manifest,
        "policyFlow": "actor_N_generates_rows_then_one_epoch_actor_N_plus_1",
        "rolloutBackend": (
            "persistent_vector_batched_inference"
            if rollout_backend_name == "persistent_vector_batched"
            else "fast_farm_cycle"
        ),
        "sourceActorContract": source_actor_contract,
        "initialModelPath": str(initial_model_path),
        "finalModelPath": str(resolved_base_model_path),
        "liveDbTrainingAllowed": False,
        "onlineTransitionBuffer": bool(online_transition_buffer),
        "persistOnlineTransitionRows": bool(persist_online_transition_rows),
        "transitionStorageHotPath": "in_memory" if bool(online_transition_buffer) else "sealed_sqlite",
        "workerPersistence": (
            "persistent_worker_local_vector_env_pool_across_updates"
            if shared_vector_pool_enabled
            else "per_cycle_vector_env_workers"
            if rollout_backend_name == "persistent_vector_batched"
            else
            "persistent_process_pool_across_training_updates"
            if shared_worker_pool_enabled
            else "single_process"
            if int(max_workers) <= 1
            else "per_cycle_process_pool"
        ),
        "persistentWorkerPool": bool(shared_worker_pool_enabled or shared_vector_pool_enabled),
        "vectorPoolLifetime": (
            "per_cycle_or_per_shard"
            if rollout_backend_name == "persistent_vector_batched" and not shared_vector_pool_enabled
            else "shared_across_cycles"
            if shared_vector_pool_enabled
            else "not_vector"
        ),
        "crossCycleVectorPoolReuse": bool(shared_vector_pool_enabled),
        "allowUnpromotedLaunchActor": bool(allow_unpromoted_launch_actor),
        "gateLaunched": False,
        "promotionApproved": False,
        "farmDecisionKinds": list(decision_kinds),
        "farmConfig": {
            "tasksPerCycle": int(tasks_per_cycle),
            "rolloutsPerUpdate": int(rollouts_per_update_count),
            "maxWorkers": int(max_workers),
            "branchRolloutSamples": max(1, int(branch_rollout_samples)),
            "maxBranchRowsPerTask": int(max_branch_rows_per_task),
            "branchMaxActions": int(branch_max_actions),
            "currentPolicyRolloutSelectionMode": str(current_policy_rollout_selection_mode or "argmax"),
            "currentPolicyRolloutTemperature": float(current_policy_rollout_temperature),
            "gamePrefixMaxActions": (
                None if game_prefix_max_actions is None else int(game_prefix_max_actions)
            ),
            "gamePrefixHardMaxActions": (
                None if game_prefix_hard_max_actions is None else int(game_prefix_hard_max_actions)
            ),
            "minActionSetSnapshotsPerDecisionKind": farm_snapshot_minimums,
            "minFullLegalGroupsPerDecisionKind": farm_full_legal_minimums,
            "rolloutBackend": rollout_backend_name,
            "vectorEnvCount": None if vector_envs is None else int(vector_envs),
            "vectorEnvCountSemantic": "legacy_worker_count",
            "vectorWorkerCount": int(vector_shape["worker_count"]),
            "vectorTotalEnvSlots": int(vector_shape["total_env_slots"]),
            "vectorRequestedTotalEnvSlots": int(vector_shape["requested_total_env_slots"]),
            "vectorWorkerEnvSlots": int(vector_shape["worker_env_slots"]),
            "vectorShapeSource": str(vector_shape["source"]),
            "vectorRoundedTotalEnvSlots": bool(vector_shape["rounded_total_env_slots"]),
            "vectorWorkerLocalInference": bool(vector_worker_local_inference),
            "vectorSteps": int(vector_steps),
            "vectorMaxGameActions": int(resolved_vector_max_game_actions),
            "vectorSelfplayGamesPerPool": int(vector_selfplay_games_per_pool),
            "vectorOriginalGamesPerPool": int(vector_original_games_per_pool),
            "vectorOriginalOpponentPolicyIds": [str(value) for value in vector_original_opponent_ids],
            "vectorTrainingPoolSchedule": vector_schedule_name,
            "vectorGateTaskSpecs": int(len(list(vector_gate_task_specs or []))),
            "vectorInferenceBatchSize": int(vector_inference_batch_size),
            "vectorInferenceTimeoutMs": int(vector_inference_timeout_ms),
            "vectorWorkerIdleTimeoutSeconds": float(vector_worker_idle_timeout_seconds),
            "vectorBridgeDecisionsPerEnv": int(vector_bridge_decisions_per_env),
            "vectorDrainToTerminal": bool(vector_drain_to_terminal),
            "vectorOriginalDrainToTerminal": bool(vector_original_drain_to_terminal),
            "vectorSelfplayDrainToTerminal": bool(vector_selfplay_drain_to_terminal),
            "vectorRollingEnvState": bool(vector_rolling_env_state),
            "vectorExecutionBackend": str(vector_execution_backend),
            "vectorCompactActionRows": bool(vector_compact_action_rows),
            "normalizeAdvantages": bool(normalize_advantages),
            "advantageNormalizationMode": str(advantage_normalization_mode),
            "domainBalanceTrainingWeights": bool(domain_balance_training_weights),
            "gateDomainWeightPlanEnabled": bool(resolved_gate_domain_weight_plan.get("enabled")),
            "gateDomainWeightPlanPath": str(gate_domain_weight_plan_path or ""),
            "noLearningDomainAudit": bool(no_learning_domain_audit),
        },
        "trainingConfig": {
            "routeProfile": route_profile_name,
            "initialBaseModelPath": str(initial_model_path),
            "finalBaseModelPath": str(resolved_base_model_path),
            "updateEpochs": int(update_epochs),
            "allowMultiEpochCurrentPolicyUpdate": bool(allow_multi_epoch_current_policy_update),
            "learningRate": float(learning_rate),
            "hiddenDim": int(hidden_dim),
            "batchSize": int(batch_size) if batch_size is not None else None,
            "numMinibatches": int(num_minibatches) if num_minibatches is not None else None,
            "evalFraction": float(eval_fraction),
            "policyTemperature": float(policy_temperature),
            "ppoClipCoef": float(ppo_clip_coef),
            "policyTemperatureRequested": float(policy_temperature),
            "policyTemperatureUsedInSampledPpo": False,
            "decisionTrainingWeights": dict(decision_training_weights or {}),
            "valueLossWeight": float(value_loss_weight),
            "highGapRankingWeight": float(high_gap_ranking_weight),
            "highGapThreshold": float(high_gap_threshold),
            "anchorKlWeight": float(anchor_kl_weight),
            "anchorKlTemperature": float(anchor_kl_temperature),
            "retentionKlMode": str(retention_kl_mode),
            "domainGradientConflictMode": str(domain_gradient_conflict_mode),
        "multiDomainObjectiveMode": str(multi_domain_objective_mode),
        "recurrentTrainingMode": str(resolved_recurrent_training_mode),
        "decisionResidualPolicyMode": str(decision_residual_policy_mode),
        "stateActionInteractionMode": str(state_action_interaction_mode),
        "stateActionInteractionRank": int(state_action_interaction_rank),
        "stateActionInteractionInitScale": float(state_action_interaction_init_scale),
        "stateActionInteractionLrMultiplier": float(state_action_interaction_lr_multiplier),
        "actorBaseLrMultiplier": float(actor_base_lr_multiplier),
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
            "actorLossLabelConsistencyProbeModes": list(label_consistency_probe_modes),
            "actorLossLabelConsistencyProbeMaxTrainingRows": (
                None
                if actor_loss_label_consistency_probe_max_training_rows is None
                else int(actor_loss_label_consistency_probe_max_training_rows)
            ),
            "actorLossRelativeMode": str(actor_loss_relative_mode),
            "actorLossGroupMode": str(actor_loss_group_mode),
            "actorLegalMarginWeight": float(actor_legal_margin_weight),
            "actorSignatureDriftPenaltyWeight": float(actor_signature_drift_penalty_weight),
            "actorSignatureContrastiveWeight": float(actor_signature_contrastive_weight),
            "actorGradientCollisionAuditMode": str(actor_gradient_collision_audit_mode),
            "actorLinearizedRepresentabilityMode": str(actor_linearized_representability_mode),
            "actorLinearizedCgMaxIterations": int(actor_linearized_cg_max_iterations),
            "actorLinearizedOptimizerDiagnostics": str(actor_linearized_optimizer_diagnostics),
            "terminalUntrustedActorLossMaxStepsFromTerminal": int(terminal_untrusted_actor_loss_max_steps_from_terminal),
            "postTrainingDiagnostics": str(post_training_diagnostics),
            "rowContractMode": str(row_contract_mode),
            "entropyCoef": float(entropy_coef),
            "currentPolicyActorAdvantageMode": str(current_policy_actor_advantage_mode or "gae"),
            "currentPolicyLocalStepRewardWeight": float(current_policy_local_step_reward_weight),
            "detachValueLossRecurrentContext": bool(detach_value_loss_recurrent_context),
            "criticWarmupEpochs": None if critic_warmup_epochs is None else int(critic_warmup_epochs),
            "criticWarmupRecomputeAdvantage": bool(critic_warmup_recompute_advantage),
            "normalizeAdvantages": bool(normalize_advantages),
            "advantageNormalizationMode": str(advantage_normalization_mode),
            "maxCurrentPolicyTrainingRows": (
                None
                if max_current_policy_training_rows is None
                else int(max_current_policy_training_rows)
            ),
            "device": str(device),
            "onlineTransitionBuffer": bool(online_transition_buffer),
            "requireOldPolicyValues": bool(online_transition_buffer),
            "persistOnlineTransitionRows": bool(persist_online_transition_rows),
            "domainBalanceTrainingWeights": bool(domain_balance_training_weights),
            "gateDomainWeightPlanEnabled": bool(resolved_gate_domain_weight_plan.get("enabled")),
            "gateDomainWeightPlanPath": str(gate_domain_weight_plan_path or ""),
            "noLearningDomainAudit": bool(no_learning_domain_audit),
        },
        "cycles": cycle_reports,
    }
    report_path = root / "ygo_current_policy_loop_report.json"
    report["reportPath"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _training_batching_report(
    *,
    transition_rows: int,
    batch_size: int | None,
    num_minibatches: int | None,
) -> dict[str, Any]:
    rows = max(1, int(transition_rows))
    if num_minibatches is not None:
        minibatches = max(1, int(num_minibatches))
        effective_batch = max(1, (rows + minibatches - 1) // minibatches)
        return {
            "mode": "num_minibatches",
            "numMinibatches": int(minibatches),
            "effectiveBatchSize": int(effective_batch),
            "transitionRows": int(transition_rows),
        }
    effective_batch = max(1, int(batch_size if batch_size is not None else 32))
    return {
        "mode": "batch_size",
        "numMinibatches": None,
        "effectiveBatchSize": int(effective_batch),
        "transitionRows": int(transition_rows),
    }


def _mapping_row_list(rows: Any) -> list[dict[str, Any]]:
    if not rows:
        return []
    if isinstance(rows, list):
        return rows
    if isinstance(rows, Mapping):
        return [rows if isinstance(rows, dict) else dict(rows)]
    return [
        row if isinstance(row, dict) else dict(row)
        for row in rows
        if isinstance(row, Mapping)
    ]


def _persist_online_transition_rows(
    rows: Sequence[Mapping[str, Any]],
    path: Path,
) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(materialized, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return {
        "kind": "online_transition_rows_json_snapshot_v1",
        "path": str(path),
        "persistedRows": int(len(materialized)),
        "rowSchema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
        "bytes": int(path.stat().st_size),
    }


def _apply_domain_balance_training_weights(
    rows: list[Mapping[str, Any]],
    *,
    gate_domain_weight_plan: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    row_list = [row if isinstance(row, dict) else dict(row) for row in rows]
    if not row_list:
        return [], {"enabled": True, "rows": 0, "bucketCount": 0}
    gate_plan = _normalise_gate_domain_weight_plan(gate_domain_weight_plan)
    buckets: dict[tuple[str, str, str, str], list[int]] = {}
    for index, row in enumerate(row_list):
        buckets.setdefault(_transition_domain_key(row), []).append(index)
    pools = sorted({key[0] for key in buckets})
    pool_targets = _domain_balance_pool_targets(pools)
    bucket_targets: dict[tuple[str, str, str, str], float] = {}
    for pool in pools:
        pool_keys = [key for key in sorted(buckets) if key[0] == pool]
        if not pool_keys:
            continue
        target_share = float(pool_targets.get(pool, 0.0)) / float(len(pool_keys))
        for key in pool_keys:
            bucket_targets[key] = target_share
    weighted_rows: list[dict[str, Any] | None] = [None for _row in row_list]
    total_rows = len(row_list)
    bucket_reports: list[dict[str, Any]] = []
    for key in sorted(buckets):
        indices = buckets[key]
        target_share = float(bucket_targets.get(key, 0.0))
        balance_weight = target_share * float(total_rows) / float(max(1, len(indices)))
        episode_counts: dict[str, int] = {}
        for index in indices:
            episode_id = _transition_episode_id(row_list[index])
            episode_counts[episode_id] = int(episode_counts.get(episode_id, 0)) + 1
        episode_count = max(1, len(episode_counts))
        max_episode_rows = max(episode_counts.values(), default=0)
        pool, suite, opponent, side = key
        bucket_reports.append(
            {
                "rolloutPoolKind": pool,
                "suiteKind": suite,
                "opponentPolicyId": opponent,
                "runtimeActorSide": side,
                "rows": int(len(indices)),
                "episodes": int(episode_count),
                "maxEpisodeRows": int(max_episode_rows),
                "targetShare": float(target_share),
                "domainBalanceTrainingWeight": float(balance_weight),
                "episodeBalanceTrainingWeights": True,
            }
        )
        for index in indices:
            row = row_list[index]
            metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
            base_weight = _existing_training_weight(row, metadata)
            episode_id = _transition_episode_id(row)
            episode_rows = max(1, int(episode_counts.get(episode_id, 1)))
            episode_balance_weight = float(len(indices)) / float(episode_count * episode_rows)
            gate_weight = _gate_domain_weight_for_row(row, gate_plan)
            weighted_value = (
                float(base_weight)
                * float(balance_weight)
                * float(episode_balance_weight)
                * float(gate_weight)
            )
            metadata["domainBalanceTrainingWeight"] = float(balance_weight)
            metadata["episodeBalanceTrainingWeight"] = float(episode_balance_weight)
            if gate_weight != 1.0:
                metadata["gateDomainTrainingWeight"] = float(gate_weight)
            metadata["trainingWeight"] = float(weighted_value)
            row["metadata"] = metadata
            row["trainingWeight"] = float(weighted_value)
            weighted_rows[index] = row
    return [row for row in weighted_rows if row is not None], {
        "enabled": True,
        "rows": int(total_rows),
        "bucketCount": int(len(buckets)),
        "poolTargets": pool_targets,
        "buckets": bucket_reports,
        "gateDomainWeightPlan": gate_plan,
    }


def _resolve_gate_domain_weight_plan(
    *,
    gate_domain_weight_plan: Mapping[str, Any] | None,
    gate_domain_weight_plan_path: str | Path | None,
) -> dict[str, Any]:
    if gate_domain_weight_plan is not None:
        return _normalise_gate_domain_weight_plan(gate_domain_weight_plan)
    if gate_domain_weight_plan_path:
        return load_gate_domain_weight_plan_from_path(gate_domain_weight_plan_path)
    return {"enabled": False, "opponents": {}}


def load_gate_domain_weight_plan_from_path(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"gate-domain weight plan must be a JSON object: {path}")
    if "original48SliceDeltas" in payload:
        return build_gate_domain_weight_plan_from_original48_comparison(payload)
    return _normalise_gate_domain_weight_plan(payload)


def build_gate_domain_weight_plan_from_original48_comparison(
    comparison_report: Mapping[str, Any],
    *,
    alpha: float = 0.35,
    surplus_alpha: float = 0.15,
    floor: float = 0.50,
    cap: float = 2.00,
) -> dict[str, Any]:
    stats: dict[str, dict[str, Any]] = {}
    domain_stats: dict[str, dict[str, Any]] = {}
    for item in list(comparison_report.get("original48SliceDeltas") or []):
        if not isinstance(item, Mapping):
            continue
        suite, opponent = _parse_original48_slice_key(str(item.get("slice") or ""))
        if not opponent:
            continue
        candidate_wins = _optional_int(item.get("candidateWins"))
        reference_wins = _optional_int(item.get("referenceWins"))
        delta_wins = _optional_int(item.get("deltaWins"))
        if delta_wins is None and candidate_wins is not None and reference_wins is not None:
            delta_wins = int(candidate_wins) - int(reference_wins)
        if delta_wins is None:
            continue
        bucket = stats.setdefault(
            opponent,
            {
                "opponentPolicyId": opponent,
                "deficitWins": 0,
                "surplusWins": 0,
                "slices": [],
            },
        )
        if int(delta_wins) < 0:
            bucket["deficitWins"] = int(bucket["deficitWins"]) + abs(int(delta_wins))
        elif int(delta_wins) > 0:
            bucket["surplusWins"] = int(bucket["surplusWins"]) + int(delta_wins)
        bucket["slices"].append(
            {
                "slice": str(item.get("slice") or ""),
                "suiteKind": suite,
                "deltaWins": int(delta_wins),
                "candidateWins": candidate_wins,
                "referenceWins": reference_wins,
            }
        )
        if suite:
            domain_key = _gate_suite_opponent_key(suite, opponent)
            domain_bucket = domain_stats.setdefault(
                domain_key,
                {
                    "suiteKind": suite,
                    "opponentPolicyId": opponent,
                    "deficitWins": 0,
                    "surplusWins": 0,
                    "slices": [],
                },
            )
            if int(delta_wins) < 0:
                domain_bucket["deficitWins"] = int(domain_bucket["deficitWins"]) + abs(int(delta_wins))
            elif int(delta_wins) > 0:
                domain_bucket["surplusWins"] = int(domain_bucket["surplusWins"]) + int(delta_wins)
            domain_bucket["slices"].append(
                {
                    "slice": str(item.get("slice") or ""),
                    "suiteKind": suite,
                    "deltaWins": int(delta_wins),
                    "candidateWins": candidate_wins,
                    "referenceWins": reference_wins,
                }
            )
    if not stats:
        return {"enabled": False, "opponents": {}, "reason": "no_original48_slice_deltas"}

    raw: dict[str, float] = {}
    for opponent, bucket in stats.items():
        score = float(alpha) * float(bucket["deficitWins"]) - float(surplus_alpha) * float(bucket["surplusWins"])
        raw[opponent] = min(float(cap), max(float(floor), math.exp(score)))
    normalizer = sum(raw.values()) / float(len(raw)) if len(raw) > 1 else 1.0
    opponents: dict[str, dict[str, Any]] = {}
    for opponent in sorted(stats):
        multiplier = min(float(cap), max(float(floor), raw[opponent] / float(max(normalizer, 1e-9))))
        bucket = dict(stats[opponent])
        bucket["weightMultiplier"] = float(multiplier)
        opponents[opponent] = bucket
    domain_raw: dict[str, float] = {}
    for domain_key, bucket in domain_stats.items():
        score = float(alpha) * float(bucket["deficitWins"]) - float(surplus_alpha) * float(bucket["surplusWins"])
        domain_raw[domain_key] = min(float(cap), max(float(floor), math.exp(score)))
    domain_normalizer = sum(domain_raw.values()) / float(len(domain_raw)) if len(domain_raw) > 1 else 1.0
    domains: dict[str, dict[str, Any]] = {}
    for domain_key in sorted(domain_stats):
        multiplier = min(float(cap), max(float(floor), domain_raw[domain_key] / float(max(domain_normalizer, 1e-9))))
        bucket = dict(domain_stats[domain_key])
        bucket["domainKey"] = domain_key
        bucket["weightMultiplier"] = float(multiplier)
        domains[domain_key] = bucket
    return {
        "enabled": True,
        "kind": "gate_domain_weight_plan_v1",
        "source": "original48SliceDeltas",
        "alpha": float(alpha),
        "surplusAlpha": float(surplus_alpha),
        "floor": float(floor),
        "cap": float(cap),
        "normalization": "suite_opponent_domain_mean_when_available_else_opponent_mean",
        "domains": domains,
        "opponents": opponents,
    }


def _normalise_gate_domain_weight_plan(plan: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or not bool(plan.get("enabled")):
        return {"enabled": False, "domains": {}, "opponents": {}}
    domains: dict[str, dict[str, Any]] = {}
    raw_domains = plan.get("domains") if isinstance(plan.get("domains"), Mapping) else {}
    for domain_key, payload in raw_domains.items():
        if not isinstance(payload, Mapping):
            continue
        suite = str(payload.get("suiteKind") or "").strip()
        opponent = str(payload.get("opponentPolicyId") or "").strip()
        if not suite or not opponent:
            parsed_suite, parsed_opponent = _parse_original48_slice_key(str(domain_key or ""))
            suite = suite or parsed_suite
            opponent = opponent or parsed_opponent
        if not suite or not opponent:
            continue
        key = _gate_suite_opponent_key(suite, opponent)
        multiplier = _float_or_default(payload.get("weightMultiplier"), 1.0)
        domains[key] = {
            **dict(payload),
            "domainKey": key,
            "suiteKind": suite,
            "opponentPolicyId": opponent,
            "weightMultiplier": float(max(0.0, multiplier)),
        }
    opponents: dict[str, dict[str, Any]] = {}
    raw_opponents = plan.get("opponents") if isinstance(plan.get("opponents"), Mapping) else {}
    for opponent, payload in raw_opponents.items():
        if not isinstance(payload, Mapping):
            continue
        text = str(opponent or payload.get("opponentPolicyId") or "").strip()
        if not text:
            continue
        multiplier = _float_or_default(payload.get("weightMultiplier"), 1.0)
        opponents[text] = {
            **dict(payload),
            "opponentPolicyId": text,
            "weightMultiplier": float(max(0.0, multiplier)),
        }
    return {**dict(plan), "enabled": bool(domains or opponents), "domains": domains, "opponents": opponents}


def _gate_domain_weight_for_row(row: Mapping[str, Any], plan: Mapping[str, Any]) -> float:
    if not bool(plan.get("enabled")):
        return 1.0
    pool, suite, opponent, _side = _transition_domain_key(row)
    if pool != "current_vs_original":
        return 1.0
    domains = plan.get("domains") if isinstance(plan.get("domains"), Mapping) else {}
    domain_entry = domains.get(_gate_suite_opponent_key(suite, opponent)) if isinstance(domains, Mapping) else None
    if isinstance(domain_entry, Mapping):
        return max(0.0, _float_or_default(domain_entry.get("weightMultiplier"), 1.0))
    opponents = plan.get("opponents") if isinstance(plan.get("opponents"), Mapping) else {}
    entry = opponents.get(opponent) if isinstance(opponents, Mapping) else None
    if not isinstance(entry, Mapping):
        return 1.0
    return max(0.0, _float_or_default(entry.get("weightMultiplier"), 1.0))


def _gate_suite_opponent_key(suite: str, opponent: str) -> str:
    return f"{str(suite or '').strip()}|{str(opponent or '').strip()}"


def _parse_original48_slice_key(value: str) -> tuple[str, str]:
    parts = str(value or "").split("|", 1)
    if len(parts) != 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def _transition_domain_report(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    buckets: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    episodes_by_bucket: dict[tuple[str, str, str, str], set[str]] = {}
    rich_buckets: dict[tuple[str, str, str, str, str, str, str, str], dict[str, Any]] = {}
    rich_episodes_by_bucket: dict[tuple[str, str, str, str, str, str, str, str], set[str]] = {}
    deck_domain_source_counts: dict[str, int] = {}
    missing_player_deck_rows = 0
    missing_opponent_deck_rows = 0
    for row in rows:
        key = _transition_domain_key(row)
        pool, suite, opponent, side = key
        bucket = buckets.setdefault(
            key,
            {
                "rolloutPoolKind": pool,
                "suiteKind": suite,
                "opponentPolicyId": opponent,
                "runtimeActorSide": side,
                "rows": 0,
            },
        )
        bucket["rows"] = int(bucket["rows"]) + 1
        episodes_by_bucket.setdefault(key, set()).add(_transition_episode_id(row))
        rich_key = _transition_rich_domain_key(row)
        (
            rich_pool,
            rich_suite,
            rich_opponent,
            rich_side,
            player_deck_id,
            opponent_deck_id,
            player_deck_source,
            opponent_deck_source,
        ) = rich_key
        rich_bucket = rich_buckets.setdefault(
            rich_key,
            {
                "rolloutPoolKind": rich_pool,
                "suiteKind": rich_suite,
                "opponentPolicyId": rich_opponent,
                "runtimeActorSide": rich_side,
                "playerDeckId": player_deck_id,
                "opponentDeckId": opponent_deck_id,
                "playerDeckSource": player_deck_source,
                "opponentDeckSource": opponent_deck_source,
                "rows": 0,
            },
        )
        rich_bucket["rows"] = int(rich_bucket["rows"]) + 1
        rich_episodes_by_bucket.setdefault(rich_key, set()).add(_transition_episode_id(row))
        deck_source = _transition_text(row, "deckDomainSource")
        if deck_source == "unknown":
            deck_source = f"{player_deck_source}|{opponent_deck_source}"
        deck_domain_source_counts[deck_source] = int(deck_domain_source_counts.get(deck_source, 0)) + 1
        if player_deck_id == "unknown":
            missing_player_deck_rows += 1
        if opponent_deck_id == "unknown":
            missing_opponent_deck_rows += 1
    out = []
    total_rows = len(rows)
    for key in sorted(buckets):
        bucket = dict(buckets[key])
        bucket["episodes"] = int(len(episodes_by_bucket.get(key, set())))
        out.append(bucket)
    rich_out = []
    for key in sorted(rich_buckets):
        bucket = dict(rich_buckets[key])
        bucket["episodes"] = int(len(rich_episodes_by_bucket.get(key, set())))
        rich_out.append(bucket)
    max_fraction = (
        max((int(bucket["rows"]) / float(total_rows) for bucket in out), default=0.0)
        if total_rows
        else 0.0
    )
    rich_max_fraction = (
        max((int(bucket["rows"]) / float(total_rows) for bucket in rich_out), default=0.0)
        if total_rows
        else 0.0
    )
    return {
        "rows": int(total_rows),
        "bucketCount": int(len(out)),
        "maxBucketRowFraction": float(max_fraction),
        "buckets": out,
        "richDomainKey": [
            "rolloutPoolKind",
            "suiteKind",
            "opponentPolicyId",
            "runtimeActorSide",
            "playerDeckId",
            "opponentDeckId",
            "playerDeckSource",
            "opponentDeckSource",
        ],
        "richBucketCount": int(len(rich_out)),
        "richMaxBucketRowFraction": float(rich_max_fraction),
        "richBuckets": rich_out,
        "missingPlayerDeckIdRows": int(missing_player_deck_rows),
        "missingOpponentDeckIdRows": int(missing_opponent_deck_rows),
        "deckDomainSourceCounts": {
            key: int(value) for key, value in sorted(deck_domain_source_counts.items())
        },
    }


def _no_learning_domain_audit_report(
    *,
    rows: list[Mapping[str, Any]],
    domain_report: Mapping[str, Any],
    domain_balance_report: Mapping[str, Any],
    training_batching: Mapping[str, Any],
    expected_original_opponent_policy_ids: Iterable[str],
) -> dict[str, Any]:
    pool_rows: dict[str, int] = {}
    pool_weights: dict[str, float] = {}
    original_opponents: set[str] = set()
    original_sides: set[str] = set()
    sides: set[str] = set()
    player_decks: set[str] = set()
    opponent_decks: set[str] = set()
    deck_domain_source_counts: dict[str, int] = {}
    missing_player_deck_rows = 0
    missing_opponent_deck_rows = 0
    decision_rows: dict[str, int] = {}
    forced_one_action_rows: dict[str, int] = {}
    rows_by_domain_decision: dict[str, dict[str, int]] = {}
    weight_by_domain: dict[str, float] = {}
    for row in rows:
        pool, suite, opponent, side = _transition_domain_key(row)
        key = "|".join((pool, suite, opponent, side))
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        weight = _existing_training_weight(row, metadata)
        pool_rows[pool] = int(pool_rows.get(pool, 0)) + 1
        pool_weights[pool] = float(pool_weights.get(pool, 0.0)) + float(weight)
        weight_by_domain[key] = float(weight_by_domain.get(key, 0.0)) + float(weight)
        if side:
            sides.add(side)
        if pool == "current_vs_original":
            if opponent:
                original_opponents.add(opponent)
            if side:
                original_sides.add(side)
        player_deck_id = _transition_text(row, "playerDeckId", "modelDeckId")
        opponent_deck_id = _transition_text(row, "opponentDeckId", "oldTop10DeckId")
        if player_deck_id == "unknown":
            missing_player_deck_rows += 1
        else:
            player_decks.add(player_deck_id)
        if opponent_deck_id == "unknown":
            missing_opponent_deck_rows += 1
        else:
            opponent_decks.add(opponent_deck_id)
        deck_source = _transition_text(row, "deckDomainSource")
        if deck_source == "unknown":
            deck_source = f"{_transition_text(row, 'playerDeckSource')}|{_transition_text(row, 'opponentDeckSource')}"
        deck_domain_source_counts[deck_source] = int(deck_domain_source_counts.get(deck_source, 0)) + 1
        decision = str(metadata.get("decisionKind") or row.get("decisionKind") or "unknown")
        decision_rows[decision] = int(decision_rows.get(decision, 0)) + 1
        rows_by_domain_decision.setdefault(key, {})
        rows_by_domain_decision[key][decision] = int(rows_by_domain_decision[key].get(decision, 0)) + 1
        legal_mask = row.get("legalMask") if "legalMask" in row else row.get("mask_")
        if isinstance(legal_mask, list | tuple):
            legal_count = sum(1 for value in legal_mask if bool(value))
            if legal_count <= 1:
                forced_one_action_rows[decision] = int(forced_one_action_rows.get(decision, 0)) + 1

    expected_opponents = [
        str(value)
        for value in expected_original_opponent_policy_ids
        if str(value or "").strip()
    ]
    missing_opponents = sorted(set(expected_opponents) - original_opponents)
    max_bucket_fraction = float(domain_report.get("maxBucketRowFraction", 0.0) or 0.0)
    pass_criteria = {
        "hasCurrentVsOriginalRows": int(pool_rows.get("current_vs_original", 0)) > 0,
        "hasCurrentSelfplayRows": int(pool_rows.get("current_selfplay", 0)) > 0,
        "hasBothOriginalActorSides": {"P1", "P2"}.issubset(original_sides),
        "hasExpectedOriginalOpponents": not missing_opponents,
        "maxBucketRowFractionAtMost25Percent": max_bucket_fraction <= 0.25,
        "hasDeckDomainLabels": missing_player_deck_rows == 0 and missing_opponent_deck_rows == 0,
    }
    warnings: list[str] = []
    if not pass_criteria["hasCurrentVsOriginalRows"]:
        warnings.append("missing_current_vs_original_rows")
    if not pass_criteria["hasCurrentSelfplayRows"]:
        warnings.append("missing_current_selfplay_rows")
    if not pass_criteria["hasBothOriginalActorSides"]:
        warnings.append("missing_original_actor_side")
    if missing_opponents:
        warnings.append("missing_expected_original_opponent")
    if not pass_criteria["maxBucketRowFractionAtMost25Percent"]:
        warnings.append("dominant_domain_bucket_over_25_percent")
    if not pass_criteria["hasDeckDomainLabels"]:
        warnings.append("missing_deck_domain_labels")
    return {
        "kind": "current_policy_no_learning_domain_audit_v1",
        "rows": int(len(rows)),
        "noCandidateTraining": True,
        "trainingLaunched": False,
        "domainKey": ["rolloutPoolKind", "suiteKind", "opponentPolicyId", "runtimeActorSide"],
        "richDomainKey": [
            "rolloutPoolKind",
            "suiteKind",
            "opponentPolicyId",
            "runtimeActorSide",
            "playerDeckId",
            "opponentDeckId",
            "playerDeckSource",
            "opponentDeckSource",
        ],
        "expectedOriginalOpponentPolicyIds": expected_opponents,
        "presentOriginalOpponentPolicyIds": sorted(original_opponents),
        "missingOriginalOpponentPolicyIds": missing_opponents,
        "presentActorSides": sorted(sides),
        "presentOriginalActorSides": sorted(original_sides),
        "presentPlayerDeckIds": sorted(player_decks),
        "presentOpponentDeckIds": sorted(opponent_decks),
        "missingPlayerDeckIdRows": int(missing_player_deck_rows),
        "missingOpponentDeckIdRows": int(missing_opponent_deck_rows),
        "deckDomainSourceCounts": {
            key: int(value) for key, value in sorted(deck_domain_source_counts.items())
        },
        "poolRows": {key: int(value) for key, value in sorted(pool_rows.items())},
        "poolTrainingWeights": {key: float(value) for key, value in sorted(pool_weights.items())},
        "domainTrainingWeights": {key: float(value) for key, value in sorted(weight_by_domain.items())},
        "decisionRows": {key: int(value) for key, value in sorted(decision_rows.items())},
        "forcedOneActionRowsByDecisionKind": {
            key: int(value) for key, value in sorted(forced_one_action_rows.items())
        },
        "rowsByDomainDecisionKind": {
            key: {inner_key: int(inner_value) for inner_key, inner_value in sorted(value.items())}
            for key, value in sorted(rows_by_domain_decision.items())
        },
        "transitionDomainReport": dict(domain_report),
        "domainBalanceTrainingWeights": dict(domain_balance_report),
        "trainingBatching": dict(training_batching),
        "passCriteria": pass_criteria,
        "readyForLearningProbe": all(bool(value) for value in pass_criteria.values()),
        "warnings": warnings,
    }


def _domain_balance_pool_targets(pools: list[str]) -> dict[str, float]:
    configured = {
        "current_vs_original": 0.60,
        "current_selfplay": 0.40,
    }
    present = [pool for pool in pools if pool in configured]
    if not present:
        share = 1.0 / float(max(1, len(pools)))
        return {pool: share for pool in pools}
    configured_total = sum(float(configured[pool]) for pool in present)
    out = {pool: float(configured[pool]) / configured_total for pool in present}
    remaining = [pool for pool in pools if pool not in out]
    if remaining:
        spare = max(0.0, 1.0 - sum(out.values()))
        share = spare / float(len(remaining))
        for pool in remaining:
            out[pool] = share
    return out


def _transition_domain_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    pool = str(metadata.get("rolloutPoolKind") or row.get("rolloutPoolKind") or "unknown")
    suite = str(
        metadata.get("suiteKind")
        or metadata.get("sourceSuiteKind")
        or row.get("suiteKind")
        or row.get("sourceSuiteKind")
        or "unknown"
    )
    opponent = str(
        metadata.get("opponentPolicyId")
        or metadata.get("runtimeOpponentPolicyId")
        or row.get("opponentPolicyId")
        or row.get("runtimeOpponentPolicyId")
        or "unknown"
    )
    if pool == "current_selfplay":
        opponent = "selfplay_current_actor"
    side = str(
        metadata.get("runtimeActorSide")
        or metadata.get("modelSide")
        or row.get("runtimeActorSide")
        or row.get("modelSide")
        or "unknown"
    )
    return pool, suite, opponent, side


def _transition_rich_domain_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, str, str, str]:
    pool, suite, opponent, side = _transition_domain_key(row)
    return (
        pool,
        suite,
        opponent,
        side,
        _transition_text(row, "playerDeckId", "modelDeckId"),
        _transition_text(row, "opponentDeckId", "oldTop10DeckId"),
        _transition_text(row, "playerDeckSource", "deckSource"),
        _transition_text(row, "opponentDeckSource"),
    )


def _transition_text(row: Mapping[str, Any], *keys: str) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    for key in keys:
        value = metadata.get(key)
        if value is None:
            value = row.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return "unknown"


def _transition_episode_id(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    return str(
        metadata.get("episodeId")
        or metadata.get("gameId")
        or row.get("episodeId")
        or row.get("taskId")
        or row.get("rowId")
        or id(row)
    )


def _existing_training_weight(row: Mapping[str, Any], metadata: Mapping[str, Any]) -> float:
    for value in (row.get("trainingWeight"), metadata.get("trainingWeight")):
        try:
            if value is not None:
                return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    return 1.0


def _float_or_default(value: Any, default: float) -> float:
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        pass
    return float(default)


def _optional_int(value: Any) -> int | None:
    try:
        if value is not None:
            return int(value)
    except (TypeError, ValueError):
        pass
    return None


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
    if "trainableTrajectoryRows" not in report:
        blocking.append("missingTrainableTrajectoryRows")
    trainable_rows = int(report.get("trainableTrajectoryRows", 0) or 0)
    if trainable_rows <= 0:
        blocking.append(f"trainableTrajectoryRows={trainable_rows}")
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
        if text.startswith("currentPolicyProvenance.") or text.startswith("nonStrictCurrentPolicyTraining"):
            blocking.append(f"{text}={count}")
    if blocking:
        raise ValueError("unclean current-policy farm report: " + ", ".join(blocking))


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


def _assert_clean_sealed_batch_report(
    report: Mapping[str, Any],
    *,
    farm_report: Mapping[str, Any],
    expected_sealed_db_path: Path,
) -> None:
    if str(report.get("kind") or "") != "ygo_online_sealed_training_batch_v1":
        raise ValueError("current-policy sealed batch has wrong kind")
    trainable_rows = int(farm_report.get("trainableTrajectoryRows", 0) or 0)
    row_count = int(report.get("rowCount", 0) or 0)
    group_count = int(report.get("groupCount", 0) or 0)
    if row_count <= 0:
        raise ValueError("current-policy sealed batch rowCount is zero")
    if group_count <= 0:
        raise ValueError("current-policy sealed batch has no groups")
    if row_count != trainable_rows:
        raise ValueError(
            "current-policy sealed batch rowCount mismatch: "
            f"farm trainableTrajectoryRows={trainable_rows}, sealed rowCount={row_count}"
        )
    actual_path = _sealed_training_db_path(report, default_path=expected_sealed_db_path)
    if _canonical_path(actual_path) != _canonical_path(expected_sealed_db_path):
        raise ValueError(
            "current-policy sealed batch target path mismatch: "
            f"expected {expected_sealed_db_path}, got {actual_path}"
        )


def _farm_training_db_path(report: Mapping[str, Any]) -> Path:
    raw = report.get("trainingRowsDbPath") or report.get("dbPath")
    if not raw:
        storage = report.get("storage") if isinstance(report.get("storage"), Mapping) else {}
        raw = storage.get("dbPath")
    if not raw:
        raise ValueError("farm report is missing trainingRowsDbPath/dbPath")
    return Path(str(raw))


def _sealed_training_db_path(report: Mapping[str, Any], *, default_path: Path) -> Path:
    raw = report.get("sealedDbPath") or report.get("targetPath") or report.get("dbPath")
    return Path(str(raw)) if raw else Path(default_path)


def _assert_clean_bridge_report(report: Mapping[str, Any]) -> None:
    blocking = []
    for key in ("invalidRows", "mismatchedRows", "rowContractRejectedRows"):
        if int(report.get(key, 0) or 0) != 0:
            blocking.append(f"{key}={report.get(key)}")
    if report.get("currentPolicyRuntimeSelectionMatch") is not True:
        blocking.append("currentPolicyRuntimeSelectionMatch!=true")
    if int(report.get("candidateScoredRows", 0) or 0) <= 0:
        blocking.append("candidateScoredRows=0")
    if blocking:
        raise ValueError("unclean current-policy bridge audit: " + ", ".join(blocking))


def _assert_current_policy_loop_update_config(
    *,
    cycles: int,
    update_epochs: int,
    allow_multi_epoch_current_policy_update: bool,
    actor_gradient_collision_audit_mode: str = "disabled",
) -> None:
    if int(update_epochs) <= 0:
        raise ValueError("update_epochs must be positive; use update_epochs=1 for movement/readiness probes")
    if int(update_epochs) > 2 and not bool(allow_multi_epoch_current_policy_update):
        raise ValueError(
            "current-policy update_epochs > 2 is diagnostic-only; pass "
            "allow_multi_epoch_current_policy_update for fixed-batch probes"
        )
    if int(cycles) > 2 and bool(allow_multi_epoch_current_policy_update):
        raise ValueError(
            "allow_multi_epoch_current_policy_update is diagnostic-only and cannot be used "
            "for multi-cycle online/formal training"
        )


def _assert_ygo_vtrace_ppo_route_profile(
    *,
    route_profile: str,
    rollout_backend_name: str,
    online_transition_buffer: bool,
    vector_drain_to_terminal: bool,
    vector_original_drain_to_terminal: bool,
    vector_selfplay_drain_to_terminal: bool,
    vector_rolling_env_state: bool,
    actor_advantage_source: str,
    current_policy_actor_advantage_mode: str,
    q_backed_actor_residual_transfer_mode: str,
    state_action_interaction_mode: str,
    actor_loss_relative_mode: str,
    actor_loss_sign_balance_mode: str,
    actor_loss_advantage_sign_filter: str,
    actor_loss_label_consistency_mode: str,
    actor_loss_counter_signal_conflict_weight: float,
    actor_loss_group_mode: str,
    actor_legal_margin_weight: float,
    actor_signature_drift_penalty_weight: float,
    actor_signature_contrastive_weight: float,
    current_policy_local_step_reward_weight: float,
    normalize_advantages: bool,
    advantage_normalization_mode: str,
    actor_linearized_representability_mode: str = "disabled",
    domain_gradient_conflict_mode: str = "disabled",
    actor_loss_sequential_sign_steps: bool = False,
    actor_gradient_collision_audit_mode: str = "disabled",
    decision_residual_policy_mode: str = "disabled",
    multi_domain_objective_mode: str = "disabled",
    retention_kl_mode: str = "disabled",
    anchor_kl_weight: float = 0.0,
    actor_base_lr_multiplier: float = 1.0,
    state_action_interaction_lr_multiplier: float = 1.0,
) -> None:
    route_name = str(route_profile)
    if route_name not in {
        YGO_CLEAN_GAE_PPO_ROUTE_PROFILE,
        YGO_VTRACE_PPO_ROUTE_PROFILE,
    }:
        return
    blockers: list[str] = []
    if str(rollout_backend_name) != "persistent_vector_batched":
        blockers.append("rollout_backend must be persistent_vector_batched")
    if not bool(online_transition_buffer):
        blockers.append("online_transition_buffer must be true")
    if bool(vector_drain_to_terminal) or bool(vector_original_drain_to_terminal) or bool(vector_selfplay_drain_to_terminal):
        blockers.append("vector rollout must be fixed-step, not drain-to-terminal")
    if route_name == YGO_VTRACE_PPO_ROUTE_PROFILE and not bool(vector_rolling_env_state):
        blockers.append("vector_rolling_env_state must be true for ygo_vtrace_ppo_v1")
    if str(actor_advantage_source) != "gae":
        blockers.append("actor_advantage_source must be gae")
    if route_name == YGO_VTRACE_PPO_ROUTE_PROFILE:
        if str(current_policy_actor_advantage_mode) != "learner_vtrace":
            blockers.append("current_policy_actor_advantage_mode must be learner_vtrace")
        if abs(float(current_policy_local_step_reward_weight)) > 1.0e-12:
            blockers.append("current_policy_local_step_reward_weight must be 0 for learner_vtrace")
    elif str(current_policy_actor_advantage_mode) not in {"gae", "learner_current_value_gae"}:
        blockers.append("current_policy_actor_advantage_mode must be gae or learner_current_value_gae")
    if str(q_backed_actor_residual_transfer_mode) != "disabled":
        blockers.append("q_backed_actor_residual_transfer_mode must be disabled")
    if str(state_action_interaction_mode) != "disabled":
        blockers.append("state_action_interaction_mode must be disabled")
    if str(actor_loss_relative_mode) != "selected_logprob":
        blockers.append("actor_loss_relative_mode must be selected_logprob")
    if str(actor_loss_sign_balance_mode) != "disabled":
        blockers.append("actor_loss_sign_balance_mode must be disabled")
    if str(actor_loss_advantage_sign_filter) != "disabled":
        blockers.append("actor_loss_advantage_sign_filter must be disabled")
    if str(actor_loss_label_consistency_mode) != "disabled":
        blockers.append("actor_loss_label_consistency_mode must be disabled")
    if abs(float(actor_loss_counter_signal_conflict_weight) - 1.0) > 1.0e-9:
        blockers.append("actor_loss_counter_signal_conflict_weight must be 1.0")
    if str(actor_loss_group_mode) != "disabled":
        blockers.append("actor_loss_group_mode must be disabled")
    if str(actor_linearized_representability_mode) != "disabled":
        blockers.append("actor_linearized_representability_mode must be disabled")
    if str(domain_gradient_conflict_mode) != "disabled":
        blockers.append("domain_gradient_conflict_mode must be disabled")
    if bool(actor_loss_sequential_sign_steps):
        blockers.append("actor_loss_sequential_sign_steps must be false")
    if str(actor_gradient_collision_audit_mode) != "disabled":
        blockers.append("actor_gradient_collision_audit_mode must be disabled")
    if str(decision_residual_policy_mode) != "disabled":
        blockers.append("decision_residual_policy_mode must be disabled")
    if str(multi_domain_objective_mode) != "disabled":
        blockers.append("multi_domain_objective_mode must be disabled")
    if str(retention_kl_mode) != "disabled":
        blockers.append("retention_kl_mode must be disabled")
    if abs(float(anchor_kl_weight)) > 1.0e-12:
        blockers.append("anchor_kl_weight must be 0")
    if abs(float(actor_base_lr_multiplier) - 1.0) > 1.0e-9:
        blockers.append("actor_base_lr_multiplier must be 1")
    if abs(float(state_action_interaction_lr_multiplier) - 1.0) > 1.0e-9:
        blockers.append("state_action_interaction_lr_multiplier must be 1")
    if abs(float(actor_legal_margin_weight)) > 1.0e-12:
        blockers.append("actor_legal_margin_weight must be 0")
    if abs(float(actor_signature_drift_penalty_weight)) > 1.0e-12:
        blockers.append("actor_signature_drift_penalty_weight must be 0")
    if abs(float(actor_signature_contrastive_weight)) > 1.0e-12:
        blockers.append("actor_signature_contrastive_weight must be 0")
    if route_name == YGO_CLEAN_GAE_PPO_ROUTE_PROFILE and (
        float(current_policy_local_step_reward_weight) < -1.0e-12
        or float(current_policy_local_step_reward_weight) > 0.25
    ):
        blockers.append("current_policy_local_step_reward_weight must be in [0, 0.25]")
    if bool(normalize_advantages):
        blockers.append("normalize_advantages must be false")
    if str(advantage_normalization_mode) == "matchup_bucket":
        blockers.append("advantage_normalization_mode must not be matchup_bucket")
    if blockers:
        raise ValueError(f"{route_name} route profile rejects: {', '.join(blockers)}")


def _build_active_route_manifest(
    *,
    route_profile_name: str,
    rollout_backend_name: str,
    online_transition_buffer: bool,
    vector_drain_to_terminal: bool,
    vector_original_drain_to_terminal: bool,
    vector_selfplay_drain_to_terminal: bool,
    vector_rolling_env_state: bool,
    actor_advantage_source: str,
    current_policy_actor_advantage_mode: str,
    current_policy_local_step_reward_weight: float,
    normalize_advantages: bool,
    advantage_normalization_mode: str,
    actor_loss_relative_mode: str,
    q_backed_actor_residual_transfer_mode: str,
    state_action_interaction_mode: str,
    actor_loss_sign_balance_mode: str,
    actor_loss_advantage_sign_filter: str,
    actor_loss_label_consistency_mode: str,
    actor_loss_counter_signal_conflict_weight: float,
    actor_loss_group_mode: str,
    actor_legal_margin_weight: float,
    actor_signature_drift_penalty_weight: float,
    actor_signature_contrastive_weight: float,
    update_epochs: int,
    entropy_coef: float,
    ppo_clip_coef: float,
    value_loss_weight: float,
    actor_linearized_representability_mode: str = "disabled",
    actor_linearized_optimizer_diagnostics: str = "full",
    domain_gradient_conflict_mode: str = "disabled",
    actor_loss_sequential_sign_steps: bool = False,
    actor_gradient_collision_audit_mode: str = "disabled",
    decision_residual_policy_mode: str = "disabled",
    multi_domain_objective_mode: str = "disabled",
    retention_kl_mode: str = "disabled",
    anchor_kl_weight: float = 0.0,
    actor_base_lr_multiplier: float = 1.0,
    state_action_interaction_lr_multiplier: float = 1.0,
) -> dict[str, Any]:
    mode = str(current_policy_actor_advantage_mode or "gae")
    actual_value_mode = "vtrace" if mode == "learner_vtrace" else "gae"
    actor_relative_mode = str(actor_loss_relative_mode)
    margin_weight = float(actor_legal_margin_weight)
    return {
        "kind": "ygo_active_route_manifest_v1",
        "routeName": str(route_profile_name),
        "actualActorAdvantageMode": mode,
        "actualAdvantageSource": "learner_vtrace" if mode == "learner_vtrace" else str(actor_advantage_source),
        "actualValueMode": actual_value_mode,
        "advantageComputationMode": mode,
        "valueTargetMode": actual_value_mode,
        "localStepRewardWeight": float(current_policy_local_step_reward_weight),
        "normalizeAdvantages": bool(normalize_advantages),
        "advantageNormalizationMode": str(advantage_normalization_mode),
        "actorLossRelativeMode": actor_relative_mode,
        "qBackedEnabled": str(q_backed_actor_residual_transfer_mode) != "disabled",
        "qBackedActorResidualTransferMode": str(q_backed_actor_residual_transfer_mode),
        "stateActionInteractionMode": str(state_action_interaction_mode),
        "signBalanceMode": str(actor_loss_sign_balance_mode),
        "labelFilterMode": str(actor_loss_advantage_sign_filter),
        "labelConsistencyMode": str(actor_loss_label_consistency_mode),
        "counterSignalWeight": float(actor_loss_counter_signal_conflict_weight),
        "actorLossGroupMode": str(actor_loss_group_mode),
        "actorLegalMarginWeight": margin_weight,
        "selectedMarginPpoEnabled": actor_relative_mode != "selected_logprob",
        "actorLegalMarginAuxEnabled": abs(margin_weight) > 1.0e-12,
        "actorSignatureDriftPenaltyWeight": float(actor_signature_drift_penalty_weight),
        "actorSignatureContrastiveWeight": float(actor_signature_contrastive_weight),
        "actorLinearizedRepresentabilityMode": str(actor_linearized_representability_mode),
        "actorLinearizedOptimizerDiagnostics": str(actor_linearized_optimizer_diagnostics),
        "domainGradientConflictMode": str(domain_gradient_conflict_mode),
        "actorLossSequentialSignSteps": bool(actor_loss_sequential_sign_steps),
        "actorGradientCollisionAuditMode": str(actor_gradient_collision_audit_mode),
        "decisionResidualPolicyMode": str(decision_residual_policy_mode),
        "multiDomainObjectiveMode": str(multi_domain_objective_mode),
        "retentionKlMode": str(retention_kl_mode),
        "anchorKlWeight": float(anchor_kl_weight),
        "actorBaseLrMultiplier": float(actor_base_lr_multiplier),
        "stateActionInteractionLrMultiplier": float(state_action_interaction_lr_multiplier),
        "rolloutBackend": str(rollout_backend_name),
        "onlineTransitionBuffer": bool(online_transition_buffer),
        "drainToTerminal": bool(vector_drain_to_terminal)
        or bool(vector_original_drain_to_terminal)
        or bool(vector_selfplay_drain_to_terminal),
        "rollingEnvState": bool(vector_rolling_env_state),
        "updateEpochs": int(update_epochs),
        "entropyCoef": float(entropy_coef),
        "ppoClipCoef": float(ppo_clip_coef),
        "valueLossWeight": float(value_loss_weight),
        "offlineMovementBlocksTraining": False,
        "gateLaunchedDuringTraining": False,
        "promotionApprovedDuringTraining": False,
    }


def _assert_current_policy_training_report_invariants(
    report: Mapping[str, Any],
    *,
    expected_update_epochs: int,
    expected_allow_multi_epoch: bool,
    expected_value_loss_weight: float,
    expected_normalize_advantages: bool,
    expected_advantage_normalization_mode: str,
    expected_actor_loss_sign_balance_mode: str,
    expected_actor_loss_label_consistency_mode: str,
    expected_recurrent_training_mode: str,
    expected_candidate_policy_id: str,
    expected_actor_loss_relative_mode: str = "selected_logprob",
    expected_actor_advantage_source: str = "gae",
    expected_q_backed_actor_residual_transfer_mode: str = "disabled",
    expected_actor_loss_counter_signal_conflict_weight: float = 1.0,
) -> None:
    errors: list[str] = []
    expected_norm_mode = str(expected_advantage_normalization_mode or "disabled").strip().lower()
    expected_sign_mode = str(expected_actor_loss_sign_balance_mode or "disabled").strip().lower()
    expected_label_mode = str(expected_actor_loss_label_consistency_mode or "disabled").strip().lower()
    expected_relative_mode = str(expected_actor_loss_relative_mode or "selected_logprob").strip().lower()
    expected_advantage_source = str(expected_actor_advantage_source or "gae").strip().lower()
    expected_q_transfer_mode = str(expected_q_backed_actor_residual_transfer_mode or "disabled").strip().lower()
    expected_recurrent_mode = str(expected_recurrent_training_mode or "disabled").strip().lower()
    if expected_sign_mode in {"", "none", "off", "false"}:
        expected_sign_mode = "disabled"
    if expected_label_mode in {"", "none", "off", "false"}:
        expected_label_mode = "disabled"
    if expected_relative_mode in {"", "none", "off", "false", "disabled", "logprob"}:
        expected_relative_mode = "selected_logprob"
    if expected_advantage_source in {"", "none", "off", "false", "disabled", "row", "row_advantage"}:
        expected_advantage_source = "gae"
    if expected_q_transfer_mode in {"", "none", "off", "false"}:
        expected_q_transfer_mode = "disabled"
    if expected_recurrent_mode in {"", "none", "off", "false"}:
        expected_recurrent_mode = "disabled"

    if "updateEpochs" in report:
        actual_epochs = int(report.get("updateEpochs", 0) or 0)
        if actual_epochs != int(expected_update_epochs):
            errors.append(f"updateEpochs={actual_epochs} expected {int(expected_update_epochs)}")
    if "allowMultiEpochCurrentPolicyUpdate" in report:
        actual_allow = bool(report.get("allowMultiEpochCurrentPolicyUpdate"))
        if actual_allow != bool(expected_allow_multi_epoch):
            errors.append(
                "allowMultiEpochCurrentPolicyUpdate="
                f"{actual_allow} expected {bool(expected_allow_multi_epoch)}"
            )
    if "valueLossWeight" in report:
        actual_value_loss = float(report.get("valueLossWeight", 0.0) or 0.0)
        if abs(actual_value_loss - float(expected_value_loss_weight)) > 1.0e-12:
            errors.append(
                f"valueLossWeight={actual_value_loss:.12g} expected {float(expected_value_loss_weight):.12g}"
            )
    if "normalizeAdvantages" in report:
        actual_normalize = bool(report.get("normalizeAdvantages"))
        if actual_normalize != bool(expected_normalize_advantages):
            errors.append(
                f"normalizeAdvantages={actual_normalize} expected {bool(expected_normalize_advantages)}"
            )
    if bool(report.get("normalizeAdvantages")) and "advantageNormalizationMode" in report:
        actual_norm_mode = str(report.get("advantageNormalizationMode") or "disabled").strip().lower()
        if actual_norm_mode != expected_norm_mode:
            errors.append(f"advantageNormalizationMode={actual_norm_mode} expected {expected_norm_mode}")
    if "actorLossSignBalanceMode" in report:
        actual_sign_mode = str(report.get("actorLossSignBalanceMode") or "disabled").strip().lower()
        if actual_sign_mode in {"", "none", "off", "false"}:
            actual_sign_mode = "disabled"
        if actual_sign_mode != expected_sign_mode:
            errors.append(f"actorLossSignBalanceMode={actual_sign_mode} expected {expected_sign_mode}")
    if "actorLossLabelConsistencyMode" in report:
        actual_label_mode = str(report.get("actorLossLabelConsistencyMode") or "disabled").strip().lower()
        if actual_label_mode in {"", "none", "off", "false"}:
            actual_label_mode = "disabled"
        if actual_label_mode != expected_label_mode:
            errors.append(
                f"actorLossLabelConsistencyMode={actual_label_mode} expected {expected_label_mode}"
            )
    if "actorLossCounterSignalConflictWeight" in report:
        actual_conflict_weight = float(report.get("actorLossCounterSignalConflictWeight", 1.0) or 1.0)
        if abs(actual_conflict_weight - float(expected_actor_loss_counter_signal_conflict_weight)) > 1.0e-12:
            errors.append(
                "actorLossCounterSignalConflictWeight="
                f"{actual_conflict_weight:.12g} expected {float(expected_actor_loss_counter_signal_conflict_weight):.12g}"
            )
        if "actorLossRelativeMode" in report:
            actual_relative_mode = str(report.get("actorLossRelativeMode") or "selected_logprob").strip().lower()
            if actual_relative_mode in {"", "none", "off", "false", "disabled", "logprob"}:
                actual_relative_mode = "selected_logprob"
            if actual_relative_mode != expected_relative_mode:
                errors.append(f"actorLossRelativeMode={actual_relative_mode} expected {expected_relative_mode}")
        if "actorAdvantageSource" in report:
            actual_advantage_source = str(report.get("actorAdvantageSource") or "gae").strip().lower()
            if actual_advantage_source in {"", "none", "off", "false", "disabled", "row", "row_advantage"}:
                actual_advantage_source = "gae"
            if actual_advantage_source != expected_advantage_source:
                errors.append(f"actorAdvantageSource={actual_advantage_source} expected {expected_advantage_source}")
    if "qBackedActorResidualTransferMode" in report or expected_q_transfer_mode != "disabled":
        actual_q_transfer_mode = str(
            report.get("qBackedActorResidualTransferMode") or "disabled"
        ).strip().lower()
        if actual_q_transfer_mode in {"", "none", "off", "false"}:
            actual_q_transfer_mode = "disabled"
        if actual_q_transfer_mode != expected_q_transfer_mode:
            errors.append(
                "qBackedActorResidualTransferMode="
                f"{actual_q_transfer_mode} expected {expected_q_transfer_mode}"
            )
    if "recurrentTrainingMode" in report:
        actual_recurrent_mode = str(report.get("recurrentTrainingMode") or "disabled").strip().lower()
        if actual_recurrent_mode in {"", "none", "off", "false"}:
            actual_recurrent_mode = "disabled"
        if actual_recurrent_mode != expected_recurrent_mode:
            errors.append(f"recurrentTrainingMode={actual_recurrent_mode} expected {expected_recurrent_mode}")

    diagnostics = report.get("sandboxTrainingDiagnostics")
    if isinstance(diagnostics, Mapping):
        actual_actor_advantage_mode = str(report.get("currentPolicyActorAdvantageMode") or "").strip().lower()
        if actual_actor_advantage_mode == "learner_current_value_gae":
            learner_gae = diagnostics.get("learnerCurrentValueGaeReport")
            if not isinstance(learner_gae, Mapping):
                learner_gae = report.get("learnerCurrentValueGaeReport")
            if not isinstance(learner_gae, Mapping):
                errors.append("missing learnerCurrentValueGaeReport")
            elif learner_gae.get("enabled") is not True:
                errors.append("learnerCurrentValueGaeReport.enabled!=true")
            if str(report.get("advantageTarget") or "").strip() != "learner_current_value_gae":
                errors.append("advantageTarget!=learner_current_value_gae")
            if str(diagnostics.get("advantageBaselineMode") or "").strip() != "learner_current_value_gae":
                errors.append("advantageBaselineMode!=learner_current_value_gae")
        if actual_actor_advantage_mode == "learner_vtrace":
            learner_vtrace = diagnostics.get("learnerVtraceReport")
            if not isinstance(learner_vtrace, Mapping):
                learner_vtrace = report.get("learnerVtraceReport")
            if not isinstance(learner_vtrace, Mapping):
                errors.append("missing learnerVtraceReport")
            elif learner_vtrace.get("enabled") is not True:
                errors.append("learnerVtraceReport.enabled!=true")
            if str(report.get("advantageTarget") or "").strip() != "learner_vtrace":
                errors.append("advantageTarget!=learner_vtrace")
            if str(report.get("actualAdvantageSource") or "").strip() != "learner_vtrace":
                errors.append("actualAdvantageSource!=learner_vtrace")
            if str(report.get("valueTargetMode") or "").strip() != "vtrace":
                errors.append("valueTargetMode!=vtrace")
            if str(diagnostics.get("advantageBaselineMode") or "").strip() != "learner_vtrace":
                errors.append("advantageBaselineMode!=learner_vtrace")
        diagnostics_recurrent_mode = str(diagnostics.get("recurrentTrainingMode") or "disabled").strip().lower()
        if diagnostics_recurrent_mode in {"", "none", "off", "false"}:
            diagnostics_recurrent_mode = "disabled"
        if diagnostics_recurrent_mode != expected_recurrent_mode:
            errors.append(
                "sandboxTrainingDiagnostics.recurrentTrainingMode="
                f"{diagnostics_recurrent_mode} expected {expected_recurrent_mode}"
            )
        diagnostics_relative_mode = str(
            diagnostics.get("actorLossRelativeMode") or report.get("actorLossRelativeMode") or "selected_logprob"
        ).strip().lower()
        if diagnostics_relative_mode in {"", "none", "off", "false", "disabled", "logprob"}:
            diagnostics_relative_mode = "selected_logprob"
        if diagnostics_relative_mode != expected_relative_mode:
            errors.append(
                "sandboxTrainingDiagnostics.actorLossRelativeMode="
                f"{diagnostics_relative_mode} expected {expected_relative_mode}"
            )
        diagnostics_advantage_source = str(
            diagnostics.get("actorAdvantageSource") or report.get("actorAdvantageSource") or "gae"
        ).strip().lower()
        if diagnostics_advantage_source in {"", "none", "off", "false", "disabled", "row", "row_advantage"}:
            diagnostics_advantage_source = "gae"
        if diagnostics_advantage_source != expected_advantage_source:
            errors.append(
                "sandboxTrainingDiagnostics.actorAdvantageSource="
                f"{diagnostics_advantage_source} expected {expected_advantage_source}"
            )
        if (
            "qBackedActorResidualTransferMode" in diagnostics
            or "qBackedActorResidualTransferMode" in report
            or expected_q_transfer_mode != "disabled"
        ):
            diagnostics_q_transfer_mode = str(
                diagnostics.get("qBackedActorResidualTransferMode")
                or report.get("qBackedActorResidualTransferMode")
                or "disabled"
            ).strip().lower()
            if diagnostics_q_transfer_mode in {"", "none", "off", "false"}:
                diagnostics_q_transfer_mode = "disabled"
            if diagnostics_q_transfer_mode != expected_q_transfer_mode:
                errors.append(
                    "sandboxTrainingDiagnostics.qBackedActorResidualTransferMode="
                    f"{diagnostics_q_transfer_mode} expected {expected_q_transfer_mode}"
                )
        conflict_weight_report = diagnostics.get("actorLossCounterSignalConflictWeightReport")
        if isinstance(conflict_weight_report, Mapping):
            actual_conflict_weight = float(conflict_weight_report.get("weight", 1.0) or 1.0)
            if abs(actual_conflict_weight - float(expected_actor_loss_counter_signal_conflict_weight)) > 1.0e-12:
                errors.append(
                    "actorLossCounterSignalConflictWeightReport.weight="
                    f"{actual_conflict_weight:.12g} expected "
                    f"{float(expected_actor_loss_counter_signal_conflict_weight):.12g}"
                )
        norm_report = diagnostics.get("advantageNormalizationReport")
        if not isinstance(norm_report, Mapping):
            norm_report = report.get("advantageNormalizationReport")
        if isinstance(norm_report, Mapping):
            sign_flip_rows = int(norm_report.get("signFlipRows", 0) or 0)
            if sign_flip_rows != 0:
                errors.append(f"advantageNormalizationReport.signFlipRows={sign_flip_rows}")
        sign_balance_report = diagnostics.get("actorLossSignBalanceReport")
        if isinstance(sign_balance_report, Mapping):
            actual_sign_mode = str(sign_balance_report.get("mode") or "disabled").strip().lower()
            if actual_sign_mode in {"", "none", "off", "false"}:
                actual_sign_mode = "disabled"
            if actual_sign_mode != expected_sign_mode:
                errors.append(f"actorLossSignBalanceReport.mode={actual_sign_mode} expected {expected_sign_mode}")
            raw_sign_flips = int(sign_balance_report.get("rawNormalizedSignFlipRows", 0) or 0)
            if raw_sign_flips != 0:
                errors.append(f"actorLossSignBalanceReport.rawNormalizedSignFlipRows={raw_sign_flips}")
        alignment = diagnostics.get("oldPolicyLogProbAlignmentReport")
        if isinstance(alignment, Mapping) and bool(alignment.get("computed")):
            rows = int(alignment.get("rows", 0) or 0)
            close_rate = float(alignment.get("closeRateAt1e-4", 1.0) or 0.0)
            if rows > 0 and close_rate < 0.999:
                non_close_movement = diagnostics.get(
                    "finalActorUpdatedSelectedLogProbMovementOldPolicyNonCloseAudit"
                )
                non_close_actor_rows = (
                    int(non_close_movement.get("rows", 0) or 0)
                    if isinstance(non_close_movement, Mapping)
                    else -1
                )
                if non_close_actor_rows != 0:
                    errors.append(
                        "oldPolicyLogProbAlignment "
                        f"closeRateAt1e-4={close_rate:.6f} "
                        f"nonCloseActorUpdatedRows={non_close_actor_rows}"
                    )
        if str(report.get("postTrainingDiagnosticsMode") or "").strip().lower() == "full":
            final_all = diagnostics.get("finalAllSelectedLogProbMovementAudit")
            if not isinstance(final_all, Mapping):
                errors.append("missing finalAllSelectedLogProbMovementAudit")
        candidate_id = str(expected_candidate_policy_id or "").strip()
        if candidate_id and _selfplay_domain_contains_policy_id(diagnostics, candidate_id):
            errors.append("selfplay domain/bucket key contains transient candidate policy id")
    candidate_id = str(expected_candidate_policy_id or "").strip()
    if candidate_id:
        for field in (
            "currentPolicySampledAdvantageDomainMovementTrain",
            "currentPolicySampledAdvantageDomainMovementEval",
        ):
            if _selfplay_domain_contains_policy_id(report.get(field), candidate_id):
                errors.append(f"{field} selfplay domain key contains transient candidate policy id")

    if errors:
        raise ValueError("current-policy training invariant failed: " + "; ".join(errors))


def _movement_rate(report: Mapping[str, Any] | None, key: str) -> float | None:
    if not isinstance(report, Mapping):
        return None
    try:
        value = float(report.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _movement_rows(report: Mapping[str, Any] | None, key: str = "rows") -> int:
    if not isinstance(report, Mapping):
        return 0
    try:
        return int(report.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _current_policy_movement_readiness_report(report: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = report.get("sandboxTrainingDiagnostics")
    if not isinstance(diagnostics, Mapping):
        diagnostics = {}
    all_rows = diagnostics.get("finalAllSelectedLogProbMovementAudit")
    actor_rows = diagnostics.get("finalActorUpdatedSelectedLogProbMovementAudit")
    domain_report = diagnostics.get("finalActorUpdatedSelectedLogProbDomainMovementAudit")
    gate_domain_source = "final_actor_updated"
    if not isinstance(domain_report, Mapping):
        domain_report = report.get("currentPolicySampledAdvantageDomainMovementTrain")
        gate_domain_source = "top_level_train"
    domains = domain_report.get("domains") if isinstance(domain_report, Mapping) else []
    gate_domains = [
        domain
        for domain in (domains if isinstance(domains, Sequence) and not isinstance(domains, (str, bytes)) else [])
        if isinstance(domain, Mapping)
        and str(domain.get("rolloutPoolKind") or "").strip() == "current_vs_original"
        and (_movement_rows(domain, "total") or _movement_rows(domain, "rows")) > 0
    ]
    gate_rows = sum((_movement_rows(domain, "total") or _movement_rows(domain, "rows")) for domain in gate_domains)
    gate_worst = min(
        (
            _movement_rate(domain, "correctDirectionRate")
            for domain in gate_domains
            if _movement_rate(domain, "correctDirectionRate") is not None
        ),
        default=None,
    )

    checks = {
        "allRowMovement": _movement_rate(all_rows, "correctDirectionRate"),
        "allRowRows": _movement_rows(all_rows),
        "actorUpdatedMovement": _movement_rate(actor_rows, "correctDirectionRate"),
        "actorUpdatedRows": _movement_rows(actor_rows),
        "actorUpdatedPositiveMovement": _movement_rate(actor_rows, "positiveCorrectDirectionRate"),
        "actorUpdatedPositiveRows": _movement_rows(actor_rows, "positiveAdvantageRows"),
        "actorUpdatedNegativeMovement": _movement_rate(actor_rows, "negativeCorrectDirectionRate"),
        "actorUpdatedNegativeRows": _movement_rows(actor_rows, "negativeAdvantageRows"),
        "gateDomainRows": int(gate_rows),
        "gateDomainWorstMovement": gate_worst,
        "gateDomainCount": int(len(gate_domains)),
        "gateDomainSource": gate_domain_source,
    }
    blockers: list[str] = []
    if checks["allRowRows"] <= 0 or checks["allRowMovement"] is None:
        blockers.append("missing_all_row_movement")
    elif float(checks["allRowMovement"]) < MOVEMENT_READINESS_ALL_ROW_MIN:
        blockers.append(f"all_row_movement={float(checks['allRowMovement']):.4f}<0.55")
    if checks["actorUpdatedRows"] <= 0 or checks["actorUpdatedMovement"] is None:
        blockers.append("missing_actor_updated_movement")
    elif float(checks["actorUpdatedMovement"]) < MOVEMENT_READINESS_ACTOR_UPDATED_MIN:
        blockers.append(f"actor_updated_movement={float(checks['actorUpdatedMovement']):.4f}<0.65")
    if checks["actorUpdatedPositiveRows"] <= 0 or checks["actorUpdatedPositiveMovement"] is None:
        blockers.append("missing_positive_actor_updated_rows")
    elif float(checks["actorUpdatedPositiveMovement"]) < MOVEMENT_READINESS_ACTOR_SIGN_MIN:
        blockers.append(f"positive_actor_movement={float(checks['actorUpdatedPositiveMovement']):.4f}<0.60")
    if checks["actorUpdatedNegativeRows"] <= 0 or checks["actorUpdatedNegativeMovement"] is None:
        blockers.append("missing_negative_actor_updated_rows")
    elif float(checks["actorUpdatedNegativeMovement"]) < MOVEMENT_READINESS_ACTOR_SIGN_MIN:
        blockers.append(f"negative_actor_movement={float(checks['actorUpdatedNegativeMovement']):.4f}<0.60")
    if gate_rows <= 0:
        blockers.append("missing_current_vs_original_domain_rows")
    elif gate_worst is not None and float(gate_worst) < MOVEMENT_READINESS_GATE_DOMAIN_MIN:
        blockers.append(f"gate_domain_worst_movement={float(gate_worst):.4f}<0.50")
    return {
        "kind": "current_policy_movement_readiness_v1",
        "passed": not blockers,
        "blockers": blockers,
        "thresholds": {
            "allRowMovementMin": MOVEMENT_READINESS_ALL_ROW_MIN,
            "actorUpdatedMovementMin": MOVEMENT_READINESS_ACTOR_UPDATED_MIN,
            "actorUpdatedPositiveNegativeMovementMin": MOVEMENT_READINESS_ACTOR_SIGN_MIN,
            "gateDomainWorstMovementMin": MOVEMENT_READINESS_GATE_DOMAIN_MIN,
        },
        **checks,
    }


def _selfplay_domain_contains_policy_id(value: Any, policy_id: str) -> bool:
    if isinstance(value, str):
        return "current_selfplay" in value and policy_id in value
    if isinstance(value, Mapping):
        return any(_selfplay_domain_contains_policy_id(item, policy_id) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_selfplay_domain_contains_policy_id(item, policy_id) for item in value)
    return False


def _canonical_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _compact_farm_report(report: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "kind",
        "runId",
        "farmStatus",
        "trainingRowsDbPath",
        "dbPath",
        "currentPolicyId",
        "trainableActionValueRows",
        "trainableTrajectoryRows",
        "runtimeReadyTrainableActionValueRows",
        "branchRows",
        "actionValueRows",
        "identityFailures",
        "overrideFailures",
        "dirtyBranchRows",
        "workerFailures",
        "throughput",
        "rolloutBackend",
        "persistentWorkerPool",
        "persistentWorkerPoolRetry",
        "centralBatchedInference",
        "workerLocalBatchedInference",
        "inference",
        "modelLoadCount",
        "modelReloadCount",
        "modelBroadcastCount",
        "workerCount",
        "envSlotsPerWorker",
        "fixedStepTargetRows",
        "rolloutPool",
        "terminalSignal",
        "gateTaskSpecs",
        "onlineTransitionBuffer",
        "minFullLegalGroupsPerDecisionKind",
        "finalTrainableDecisionKindQuota",
    )
    return {key: report.get(key) for key in keys if key in report}


def _merged_rollout_farm_report(shards: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    shard_list = [dict(shard) for shard in shards]
    throughput_values = [
        float(
            (
                shard.get("throughput")
                if isinstance(shard.get("throughput"), Mapping)
                else {}
            ).get("decisionRowsPerSecond", 0.0)
            or 0.0
        )
        for shard in shard_list
    ]
    return {
        "kind": "merged_current_policy_rollout_shards_v1",
        "farmStatus": "completed",
        "rolloutShards": int(len(shard_list)),
        "trainableTrajectoryRows": int(
            sum(int(shard.get("trainableTrajectoryRows", 0) or 0) for shard in shard_list)
        ),
        "trainableActionValueRows": int(
            sum(int(shard.get("trainableActionValueRows", 0) or 0) for shard in shard_list)
        ),
        "runtimeReadyTrainableActionValueRows": int(
            sum(int(shard.get("runtimeReadyTrainableActionValueRows", 0) or 0) for shard in shard_list)
        ),
        "identityFailures": int(sum(int(shard.get("identityFailures", 0) or 0) for shard in shard_list)),
        "overrideFailures": int(sum(int(shard.get("overrideFailures", 0) or 0) for shard in shard_list)),
        "dirtyBranchRows": int(sum(int(shard.get("dirtyBranchRows", 0) or 0) for shard in shard_list)),
        "workerFailures": int(sum(int(shard.get("workerFailures", 0) or 0) for shard in shard_list)),
        "rolloutBackend": (
            str(shard_list[0].get("rolloutBackend") or "")
            if shard_list
            else ""
        ),
        "persistentWorkerPool": any(bool(shard.get("persistentWorkerPool")) for shard in shard_list),
        "modelReloadCount": int(sum(int(shard.get("modelReloadCount", 0) or 0) for shard in shard_list)),
        "modelBroadcastCount": int(sum(int(shard.get("modelBroadcastCount", 0) or 0) for shard in shard_list)),
        "throughput": {
            "decisionRowsPerSecondMean": (
                sum(throughput_values) / float(len(throughput_values)) if throughput_values else None
            )
        },
    }


def _compact_training_report(report: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "kind",
        "actorPolicyId",
        "candidatePolicyId",
        "candidateModelPath",
        "reportPath",
        "trainingRowsPath",
        "trainingRowsSource",
        "rowCount",
        "usableTrajectoryRows",
        "usableFullLegalRows",
        "sequenceBatchReport",
        "elapsedSeconds",
        "usableTrajectoryRowsPerSecond",
        "trainRows",
        "evalRows",
        "epochs",
        "updateEpochs",
        "trainingObjective",
        "policyTarget",
        "requireOldPolicyValues",
        "advantageNormalizationMode",
        "advantageNormalizationReport",
        "retentionKlMode",
        "retentionKlReport",
        "recurrentTrainingMode",
        "usesRecurrentState",
        "postTrainingDiagnosticsMode",
        "rowContractMode",
        "runtimeLaunchableActor",
        "runtimeSelectionInterface",
        "currentPolicyRowContractReport",
        "candidateCurrentPolicyEval",
        "candidateCurrentPolicySampledAdvantageEval",
        "currentPolicySampledAdvantageMovementTrain",
        "currentPolicySampledAdvantageMovementEval",
        "currentPolicySampledAdvantageGroupMovementTrain",
        "currentPolicySampledAdvantageGroupMovementEval",
        "currentPolicySampledAdvantageDomainMovementTrain",
        "currentPolicySampledAdvantageDomainMovementEval",
        "currentPolicyMovementReadiness",
        "currentPolicySignalBucketAuditTrain",
        "currentPolicySignalBucketAuditEval",
        "currentPolicySignalBucketAuditPaths",
        "currentPolicyDomainGradientConflictDiagnostics",
        "currentPolicyLocalStepRewardWeight",
        "actorLossRelativeMode",
        "episodeLambdaReturnTransform",
        "advantageBaselineMode",
        "learnerCurrentValueGaeReport",
        "oldPolicyLogProbAlignmentReport",
        "actualLearnerBatchDomainReport",
        "ppoMovementAuditActorUpdatedRows",
        "actorGradientCollisionAudit",
        "actorLegalMarginReport",
        "finalAllSelectedLogProbMovementAudit",
        "finalActorUpdatedSelectedLogProbMovementAudit",
        "finalAllSelectedRawScoreMovementAudit",
        "finalActorUpdatedSelectedRawScoreMovementAudit",
        "finalAllSelectedLogProbDomainMovementAudit",
        "finalActorUpdatedSelectedLogProbDomainMovementAudit",
        "finalAllLegalSetComponentMovementAudit",
        "finalActorUpdatedLegalSetComponentMovementAudit",
        "trainingResolvedDevice",
    )
    compact = {key: report.get(key) for key in keys if key in report}
    diagnostics = report.get("sandboxTrainingDiagnostics")
    if isinstance(diagnostics, Mapping):
        for key in (
            "advantageBaselineMode",
            "learnerCurrentValueGaeReport",
            "oldPolicyLogProbAlignmentReport",
            "actualLearnerBatchDomainReport",
            "ppoMovementAuditActorUpdatedRows",
            "actorGradientCollisionAudit",
            "actorLegalMarginReport",
            "actorLossRelativeMode",
            "finalAllSelectedLogProbMovementAudit",
            "finalActorUpdatedSelectedLogProbMovementAudit",
            "finalAllSelectedRawScoreMovementAudit",
            "finalActorUpdatedSelectedRawScoreMovementAudit",
            "finalAllSelectedLogProbDomainMovementAudit",
            "finalActorUpdatedSelectedLogProbDomainMovementAudit",
            "finalAllLegalSetComponentMovementAudit",
            "finalActorUpdatedLegalSetComponentMovementAudit",
        ):
            if key not in compact and key in diagnostics:
                compact[key] = diagnostics.get(key)
    return compact


_ACTOR_LOSS_LABEL_CONSISTENCY_MODES = {
    "disabled",
    "gae_mc_agree",
    "gae_mc_local_agree",
    "gae_mc_excluded",
    "gae_local_agree",
    "gae_local_excluded",
    "unshaped_gae_local_agree",
    "counter_signal_conflict",
    "drop_positive_local_negative_advantage",
    "drop_positive_local_negative_unshaped_gae",
    "drop_counter_signal_advantage",
}


def _normalise_label_consistency_modes(values: Iterable[str] | None) -> tuple[str, ...]:
    modes: list[str] = []
    for value in list(values or []):
        for part in str(value).split(","):
            mode = part.strip().lower()
            if not mode:
                continue
            if mode not in _ACTOR_LOSS_LABEL_CONSISTENCY_MODES:
                raise ValueError(f"unknown actor_loss_label_consistency_mode: {part!r}")
            modes.append(mode)
    return tuple(modes)


def _normalise_local_step_reward_probe_weights(values: Iterable[float] | None) -> tuple[float, ...]:
    weights: list[float] = []
    for value in list(values or []):
        for part in str(value).split(","):
            text = part.strip()
            if not text:
                continue
            weight = float(text)
            if weight < 0.0:
                raise ValueError("current_policy_local_step_reward_probe_weights must be non-negative")
            weights.append(weight)
    return tuple(weights)


def _local_step_reward_weight_tag(weight: float) -> str:
    text = f"{float(weight):.6g}".replace("-", "neg").replace(".", "p")
    return text or "0"


def _copy_probe_training_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        metadata = item.get("metadata")
        if isinstance(metadata, Mapping):
            item["metadata"] = dict(metadata)
        label = item.get("trajectoryPolicyLabel")
        if isinstance(label, Mapping):
            item["trajectoryPolicyLabel"] = dict(label)
        copied.append(item)
    return copied


def _compact_label_consistency_probe_training_report(
    *,
    mode: str,
    local_step_reward_weight: float,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    compact = _compact_training_report(report)
    diagnostics = report.get("sandboxTrainingDiagnostics")
    if isinstance(diagnostics, Mapping):
        compact["ppoMovementAuditActorUpdatedRows"] = diagnostics.get("ppoMovementAuditActorUpdatedRows")
        compact["actorLossLabelConsistencyReport"] = diagnostics.get("actorLossLabelConsistencyReport")
        compact["finalActorSignalConflictMatrixAudit"] = diagnostics.get("finalActorSignalConflictMatrixAudit")
        compact["actualLearnerBatchDomainReport"] = diagnostics.get("actualLearnerBatchDomainReport")
    return {
        "mode": str(mode),
        "localStepRewardWeight": float(local_step_reward_weight),
        **compact,
    }


def _compact_bridge_report(report: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "kind",
        "rows",
        "groups",
        "candidatePolicyId",
        "candidateModelPath",
        "currentPolicyRuntimeSelectionMatch",
        "invalidRows",
        "mismatchedRows",
        "rowContractRejectedRows",
        "candidateScoredRows",
        "candidateScoredGroups",
        "changedGroups",
        "changedTargetImprovedGroups",
        "changedTargetRegressedGroups",
        "candidateTrainingEvalReady",
        "candidateTrainingEvalError",
    )
    return {key: report.get(key) for key in keys if key in report}


def _normalise_decision_kinds(values: Iterable[str] | None) -> list[str]:
    raw_values = list(values or DEFAULT_FARM_DECISION_KINDS)
    out: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    if not out:
        raise ValueError("farm_decision_kinds must contain at least one route")
    return out


def _normalise_rollout_backend(value: str | None) -> str:
    text = str(value or "fast_farm").strip().lower().replace("-", "_")
    aliases = {
        "fast": "fast_farm",
        "fast_farm_cycle": "fast_farm",
        "legacy_fast_farm": "fast_farm",
        "vector": "persistent_vector_batched",
        "vector_batched": "persistent_vector_batched",
        "persistent_vector": "persistent_vector_batched",
        "persistent_vector_batched_inference": "persistent_vector_batched",
    }
    normalized = aliases.get(text, text)
    if normalized not in {"fast_farm", "persistent_vector_batched"}:
        raise ValueError(f"unknown rollout_backend: {value!r}")
    return normalized


def _assert_current_policy_farm_full_coverage(decision_kinds: Iterable[str]) -> None:
    actual = {str(value).strip() for value in decision_kinds if str(value).strip()}
    required = {str(value).strip() for value in DEFAULT_FARM_DECISION_KINDS if str(value).strip()}
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        raise ValueError(
            "current-policy loop requires full farm_decision_kinds coverage; "
            f"missing={missing}, extra={extra}"
        )


def _resolve_current_policy_source_actor(
    actor_id: str,
    *,
    explicit_base_model_path: str | Path | None,
    decision_kinds: Iterable[str] | None = None,
    allow_unpromoted_launch_actor: bool = False,
) -> dict[str, Any]:
    if allow_unpromoted_launch_actor and explicit_base_model_path is not None:
        return _resolve_unpromoted_current_policy_launch_actor(
            actor_id,
            model_path=explicit_base_model_path,
            decision_kinds=decision_kinds,
        )
    try:
        from zz.policy_factories import runtime_weights_for_policy_id

        weights = runtime_weights_for_policy_id(str(actor_id))
    except Exception as exc:  # pragma: no cover - exact registry errors are policy-factory owned.
        if explicit_base_model_path is None:
            raise ValueError(f"current-policy loop requires a registered current-policy actor: {actor_id!r}") from exc
        weights = current_policy_runtime_weights_for_actor_model_path(
            actor_id=str(actor_id),
            model_path=explicit_base_model_path,
            decision_kinds=decision_kinds or DEFAULT_FARM_DECISION_KINDS,
        )
    return assert_current_policy_source_actor_ready(
        str(actor_id),
        runtime_weights=weights,
        explicit_model_path=explicit_base_model_path,
        context="current-policy loop source actor",
    )


def _source_recurrent_training_mode(model_path: str | Path | None) -> str:
    if model_path is None:
        return "disabled"
    try:
        payload = json.loads(Path(model_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "disabled"
    if not isinstance(payload, Mapping):
        return "disabled"
    for key in ("recurrentTrainingMode", "recurrent_training_mode", "recurrentMode"):
        mode = str(payload.get(key) or "").strip()
        if mode:
            return mode
    aux = payload.get("runtimeAuxTrainingDiagnostics")
    if isinstance(aux, Mapping):
        mode = str(aux.get("recurrentTrainingMode") or "").strip()
        if mode:
            return mode
    return "disabled"


def _resolve_recurrent_training_mode(
    *,
    requested_mode: str | None,
    source_model_path: str | Path | None,
) -> str:
    requested = str(requested_mode or "disabled").strip().lower() or "disabled"
    if requested not in _SUPPORTED_RECURRENT_TRAINING_MODES:
        raise ValueError(f"unsupported recurrent_training_mode: {requested_mode!r}")
    if requested != "disabled":
        return requested
    inherited = _source_recurrent_training_mode(source_model_path).strip().lower() or "disabled"
    if inherited not in _SUPPORTED_RECURRENT_TRAINING_MODES:
        raise ValueError(
            f"source checkpoint uses unsupported recurrentTrainingMode {inherited!r}: {source_model_path}"
        )
    return inherited


def _resolve_unpromoted_current_policy_launch_actor(
    actor_id: str,
    *,
    model_path: str | Path,
    decision_kinds: Iterable[str] | None = None,
) -> dict[str, Any]:
    actor_payload = load_current_policy_actor_artifact(
        model_path,
        expected_candidate_policy_ids=[str(actor_id)],
        context=f"current-policy loop in-run actor {actor_id!r}",
    )
    if bool(actor_payload.get("basePreservingActor")):
        raise ValueError("current-policy loop in-run actor cannot be base-preserving")
    if str(actor_payload.get("trainingObjective") or "") != CURRENT_POLICY_TRAJECTORY_TRAINING_OBJECTIVE:
        raise ValueError("current-policy loop in-run actor must be sampled trajectory actor/value")
    actor_payload_id = str(actor_payload.get("actorPolicyId") or "").strip()
    return {
        "policyId": str(actor_id),
        "actorPolicyId": actor_payload_id,
        "modelPath": str(model_path),
        "sourcePolicyId": str(actor_payload.get("sourceActorPolicyId") or ""),
        "sourceActorPolicyId": str(actor_payload.get("sourceActorPolicyId") or ""),
        "candidatePolicyId": str(actor_payload.get("candidatePolicyId") or actor_payload.get("modelId") or ""),
        "basePreservingActor": False,
        "basePolicyId": "",
        "minSourceRows": 0,
        "inRunUnpromotedActor": True,
        "readiness": {
            "checked": True,
            "launchableCandidateSource": True,
            "actorNSourceEligible": bool(actor_payload.get("actorNSourceEligible")),
            "decisionKinds": [str(kind) for kind in list(decision_kinds or [])],
        },
    }


def _cycle_candidate_policy_id(
    *,
    requested_candidate_policy_id: str,
    initial_policy_id: str,
    fixed_seed: int,
    cycle_index: int,
    cycles: int,
) -> str | None:
    requested = str(requested_candidate_policy_id or "").strip()
    if int(cycles) <= 1:
        return requested or None
    if requested:
        return f"{requested}_{int(cycle_index) + 1:04d}"
    return f"{initial_policy_id}_loop_{int(fixed_seed)}_{int(cycle_index) + 1:04d}"


def _cycle_generation_seed_batches(
    *,
    generation_seeds: Iterable[int] | None,
    cycles: int,
    fixed_gate_seed: int,
) -> list[list[int]]:
    provided = [int(value) for value in list(generation_seeds or [])]
    if provided:
        if int(cycles) == 1:
            return [provided]
        if len(provided) < int(cycles):
            provided.extend(provided[index % len(provided)] for index in range(int(cycles) - len(provided)))
        return [[seed] for seed in provided[: int(cycles)]]
    return [[int(fixed_gate_seed) + 1000 + index] for index in range(int(cycles))]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_int_args(values: Iterable[str] | None) -> list[int]:
    parsed: list[int] = []
    for value in list(values or []):
        for part in str(value).split(","):
            text = part.strip()
            if text:
                parsed.append(int(text))
    return parsed


def _parse_string_args(values: Iterable[str] | None) -> list[str]:
    parsed: list[str] = []
    for value in list(values or []):
        for part in str(value).split(","):
            text = part.strip()
            if text:
                parsed.append(text)
    return parsed


def _load_vector_gate_deck_pool_payloads(
    path: str | Path | None,
) -> dict[str, list[dict[str, Any]]] | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("gateDeckPoolPayloads"), Mapping):
        payload = payload["gateDeckPoolPayloads"]
    if not isinstance(payload, Mapping):
        raise ValueError("vector gate deck pool JSON must be an object")
    out: dict[str, list[dict[str, Any]]] = {}
    for key in ("player", "top10"):
        rows = payload.get(key)
        if rows is None:
            continue
        if not isinstance(rows, list):
            raise ValueError(f"vector gate deck pool {key!r} must be a list")
        out[key] = [dict(item) for item in rows if isinstance(item, Mapping)]
    if not any(out.values()):
        raise ValueError("vector gate deck pool JSON must contain player or top10 deck payloads")
    return out


def _load_vector_gate_task_specs(path: str | Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("gateTaskSpecs"), list):
        payload = payload["gateTaskSpecs"]
    if not isinstance(payload, list):
        raise ValueError("vector gate task specs JSON must be a list or contain gateTaskSpecs")
    tasks = [dict(item) for item in payload if isinstance(item, Mapping)]
    if not tasks:
        raise ValueError("vector gate task specs JSON must contain at least one task")
    return tasks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run YGO-style current-policy farm/seal/one-epoch training cycles."
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--current-policy-id", required=True)
    parser.add_argument(
        "--route-profile",
        choices=ROUTE_PROFILES,
        default="legacy",
        help=(
            "Use ygo_clean_gae_ppo_v1 for the current clean GAE PPO route. "
            "Use ygo_vtrace_ppo_v1 only for learner_vtrace; it rejects GAE."
        ),
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_FIXED_GATE_SEED)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--tasks-per-cycle", type=int, default=16)
    parser.add_argument(
        "--rollouts-per-update",
        type=int,
        default=1,
        help="Collect N rollout shards with the same actor_N and merge them into one PPO update.",
    )
    parser.add_argument("--generation-seed", "--generation-seeds", action="append", default=[])
    parser.add_argument("--min-trainable-rows-per-cycle", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--max-elapsed-seconds-per-cycle", type=float, default=None)
    parser.add_argument("--base-model-path", type=Path, default=DEFAULT_BASE_MODEL_PATH)
    parser.add_argument("--candidate-policy-id", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--farm-decision-kind", "--farm-decision-kinds", action="append", default=[])
    parser.add_argument(
        "--farm-min-action-set-snapshot",
        "--farm-min-action-set-snapshots",
        action="append",
        default=[],
        help="Keep each game prefix past the soft action cap until route snapshots are seen, e.g. flash=3 blocker=3.",
    )
    parser.add_argument(
        "--farm-min-full-legal-group",
        "--farm-min-full-legal-groups",
        action="append",
        default=[],
        help="Require route full-legal groups before priority fill, e.g. flash=8 blocker=8.",
    )
    parser.add_argument("--branch-rollout-samples", type=int, default=1)
    parser.add_argument("--max-branch-rows-per-task", type=int, default=16)
    parser.add_argument("--branch-max-actions", type=int, default=80)
    parser.add_argument("--game-prefix-max-actions", type=int, default=None)
    parser.add_argument("--game-prefix-hard-max-actions", type=int, default=None)
    parser.add_argument("--current-policy-rollout-selection-mode", default="sampled_from_logits")
    parser.add_argument("--current-policy-rollout-temperature", type=float, default=1.0)
    parser.add_argument(
        "--decision-training-weights",
        default="",
        help="Comma-separated sampled PPO actor/value row weights by decision kind, e.g. main=1,mana=2,flash=0.",
    )
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--num-minibatches", type=int, default=None)
    parser.add_argument("--update-epochs", type=int, default=1)
    parser.add_argument(
        "--allow-multi-epoch-current-policy-update",
        action="store_true",
        help="Diagnostic-only: allow update_epochs > 1 for fixed-batch overfit/capacity probes.",
    )
    parser.add_argument("--eval-fraction", type=float, default=0.0)
    parser.add_argument("--policy-temperature", type=float, default=0.5)
    parser.add_argument("--ppo-clip-coef", type=float, default=0.2)
    parser.add_argument("--value-loss-weight", type=float, default=0.25)
    parser.add_argument("--high-gap-ranking-weight", type=float, default=0.25)
    parser.add_argument("--high-gap-threshold", type=float, default=DEFAULT_MIN_OUTCOME_VALUE_GAP_FOR_TRAINING)
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
        help="Restrict source-actor KL retention to selected current-policy PPO rows.",
    )
    parser.add_argument(
        "--domain-gradient-conflict-mode",
        choices=(
            "disabled",
            "pcgrad_coarse_policy_only",
            "pcgrad_action_signature_sign_policy_only",
            "pcgrad_action_family_sign_policy_only",
        ),
        default="disabled",
        help=(
            "Current-policy PPO experiment: optionally project conflicting "
            "coarse-domain or action-signature/sign actor gradients."
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
        help="Enable the minimal domain-conditioned GRU actor/value V2 training path.",
    )
    parser.add_argument(
        "--decision-residual-policy-mode",
        choices=("disabled", "linear_v1"),
        default="disabled",
        help="Enable a same-checkpoint per-decision linear actor residual head.",
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
            "counter_signal_conflict",
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
        "--actor-loss-label-consistency-probe-modes",
        action="append",
        default=[],
        help="Comma-separated modes to run on one shared online batch without advancing actor_N.",
    )
    parser.add_argument(
        "--actor-loss-label-consistency-probe-max-training-rows",
        type=int,
        default=None,
        help="Optional learner row cap for each label-consistency probe mode; default uses --max-current-policy-training-rows.",
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
            "Q-backed sampled mean-centered residual transfer mode passed to the current-policy "
            "learner; functional_temporal_delta_q_backed_single_residual_v1 is the q-backed "
            "single-carrier continuation candidate."
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
            "Default-off PPO regularizer: penalize mixed-sign action signature mean selected-logprob drift "
            "so broad action-family priors do not dominate state-conditioned credit."
        ),
    )
    parser.add_argument(
        "--actor-signature-contrastive-weight",
        type=float,
        default=0.0,
        help=(
            "Default-off PPO auxiliary: within mixed-sign action signatures, push positive-GAE "
            "selected-logprob deltas above negative-GAE deltas."
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
            "Explicit fixed-batch actor-Jacobian diagnostic/repair-proof mode passed to the learner. "
            "projected_legal_logit_cg_update is opt-in and does not change the default PPO route."
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
            "optimizer-realization replay after the CG line-search for speed probes."
        ),
    )
    parser.add_argument("--terminal-untrusted-actor-loss-max-steps-from-terminal", type=int, default=-1)
    parser.add_argument(
        "--post-training-diagnostics",
        choices=("full", "skip"),
        default="full",
        help="Skip post-update base/candidate row rescoring on learner-throughput probes.",
    )
    parser.add_argument(
        "--row-contract-mode",
        choices=("full", "fast_preflight"),
        default="full",
        help="Use full row contract for gate/review, or fast preflight for intermediate online learner updates.",
    )
    parser.add_argument("--entropy-coef", type=float, default=YGO_CURRENT_POLICY_ENTROPY_COEF)
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
            "learner_vtrace is required by ygo_vtrace_ppo_v1."
        ),
    )
    parser.add_argument(
        "--current-policy-local-step-reward-weight",
        type=float,
        default=0.0,
        help="Optional shaping weight that adds rollout localStepReward into the GAE step reward; default 0 keeps terminal-only GAE.",
    )
    parser.add_argument(
        "--current-policy-local-step-reward-probe-weight",
        action="append",
        default=[],
        help=(
            "Diagnostic-only comma-separated localStepReward weights. "
            "When set, the loop reuses one online rollout batch for probe training reports and does not advance actor_N."
        ),
    )
    parser.add_argument(
        "--detach-value-loss-recurrent-context",
        action="store_true",
        help=(
            "For recurrent current-policy PPO, stop value loss from updating the shared recurrent context. "
            "Actor and value remain in the same checkpoint."
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
        "--max-current-policy-training-rows",
        type=int,
        default=DEFAULT_MAX_CURRENT_POLICY_TRAINING_ROWS,
        help="Optional cap for sampled current-policy learner rows; omit for no cap.",
    )
    parser.add_argument(
        "--normalize-advantages",
        action="store_true",
        help=(
            "Explicit diagnostic/experiment: normalize sampled current-policy advantages. "
            "Default follows the YGO-style route and leaves sparse win/loss advantages uncentered."
        ),
    )
    parser.add_argument(
        "--disable-normalize-advantages",
        action="store_true",
        help="Compatibility alias: force sampled current-policy advantages to stay raw.",
    )
    parser.add_argument(
        "--advantage-normalization-mode",
        choices=("scale_only", "global", "matchup_bucket"),
        default="scale_only",
        help="Only used with --normalize-advantages; default scales without changing advantage signs.",
    )
    parser.add_argument("--domain-balance-training-weights", action="store_true")
    parser.add_argument(
        "--gate-domain-weight-plan-path",
        type=Path,
        default=None,
        help="JSON gate-domain plan or original48 comparison whose slice deficits weight current-vs-original rows.",
    )
    parser.add_argument(
        "--no-learning-domain-audit",
        action="store_true",
        help="Collect online transition rows and domain/batching reports, then skip actor training.",
    )
    parser.add_argument(
        "--require-movement-readiness",
        action="store_true",
        help="Fail the loop if all-row, actor-updated, or current-vs-original movement readiness is below the current safety floor.",
    )
    parser.add_argument(
        "--online-transition-buffer",
        action="store_true",
        help="Train actor_next directly from in-process sampled trajectory rows instead of sealed SQLite.",
    )
    parser.add_argument(
        "--persist-online-transition-rows",
        action="store_true",
        help=(
            "Diagnostic fixed-batch mode: write online transition rows to JSON and train from that path "
            "so follow-up probes can reuse the exact same batch."
        ),
    )
    parser.add_argument(
        "--rollout-backend",
        default="fast_farm",
        choices=("fast_farm", "persistent_vector_batched", "vector"),
        help="Use legacy fast farm or persistent vector env workers with centralized batched inference.",
    )
    parser.add_argument("--vector-envs", type=int, default=None, help="Legacy alias for vector worker process count.")
    parser.add_argument("--vector-worker-count", type=int, default=None, help="Explicit worker process count for worker-local vector rollout.")
    parser.add_argument("--vector-total-env-slots", type=int, default=None, help="YGO-style total env slots; worker count is ceil(total / worker slots).")
    parser.add_argument("--vector-worker-env-slots", type=int, default=1)
    parser.add_argument("--vector-worker-local-inference", action="store_true")
    parser.add_argument("--vector-steps", type=int, default=128)
    parser.add_argument("--vector-max-game-actions", type=int, default=None)
    parser.add_argument("--vector-selfplay-games-per-pool", type=int, default=DEFAULT_SELFPLAY_GAMES_PER_POOL)
    parser.add_argument("--vector-original-games-per-pool", type=int, default=DEFAULT_ORIGINAL_GAMES_PER_POOL)
    parser.add_argument("--vector-original-opponent-policy-id", action="append", default=[])
    parser.add_argument(
        "--vector-training-pool-schedule",
        default=DEFAULT_TRAINING_POOL_SCHEDULE,
        choices=(DEFAULT_TRAINING_POOL_SCHEDULE, "easy_top10_matrix_v1", EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE),
    )
    parser.add_argument("--vector-gate-task-specs-path", type=Path, default=None)
    parser.add_argument("--vector-gate-deck-pool-path", type=Path, default=None)
    parser.add_argument("--vector-inference-batch-size", type=int, default=512)
    parser.add_argument("--vector-inference-timeout-ms", type=int, default=2)
    parser.add_argument("--vector-worker-idle-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--vector-bridge-decisions-per-env", type=int, default=0)
    parser.add_argument("--vector-drain-to-terminal", action="store_true")
    parser.add_argument("--vector-original-drain-to-terminal", action="store_true")
    parser.add_argument("--vector-selfplay-drain-to-terminal", action="store_true")
    parser.add_argument(
        "--vector-rolling-env-state",
        action="store_true",
        help="Reuse persistent vector worker env/game state across learner updates; fixed-step slices carry unfinished games forward.",
    )
    parser.add_argument("--vector-execution-backend", choices=("process", "thread"), default="process")
    parser.add_argument("--disable-vector-compact-action-rows", action="store_true")
    parser.add_argument("--allow-unpromoted-launch-actor", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_ygo_current_policy_loop(
        out_dir=args.out_dir,
        current_policy_id=args.current_policy_id,
        route_profile=args.route_profile,
        seed=args.seed,
        cycles=args.cycles,
        tasks_per_cycle=args.tasks_per_cycle,
        rollouts_per_update=args.rollouts_per_update,
        generation_seeds=_parse_int_args(args.generation_seed),
        min_trainable_rows_per_cycle=args.min_trainable_rows_per_cycle,
        max_workers=args.max_workers,
        max_elapsed_seconds_per_cycle=args.max_elapsed_seconds_per_cycle,
        base_model_path=args.base_model_path,
        candidate_policy_id=args.candidate_policy_id,
        device=args.device,
        farm_decision_kinds=(
            _parse_string_args(args.farm_decision_kind)
            if args.farm_decision_kind
            else DEFAULT_FARM_DECISION_KINDS
        ),
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
        current_policy_rollout_selection_mode=args.current_policy_rollout_selection_mode,
        current_policy_rollout_temperature=args.current_policy_rollout_temperature,
        decision_training_weights=_parse_anchor_kl_decision_weights(args.decision_training_weights),
        learning_rate=args.learning_rate,
        hidden_dim=args.hidden_dim,
        batch_size=args.batch_size,
        num_minibatches=args.num_minibatches,
        update_epochs=int(args.update_epochs),
        allow_multi_epoch_current_policy_update=bool(args.allow_multi_epoch_current_policy_update),
        eval_fraction=args.eval_fraction,
        policy_temperature=args.policy_temperature,
        ppo_clip_coef=args.ppo_clip_coef,
        value_loss_weight=args.value_loss_weight,
        high_gap_ranking_weight=args.high_gap_ranking_weight,
        high_gap_threshold=args.high_gap_threshold,
        anchor_kl_weight=args.anchor_kl_weight,
        anchor_kl_temperature=args.anchor_kl_temperature,
        retention_kl_mode=args.retention_kl_mode,
        domain_gradient_conflict_mode=args.domain_gradient_conflict_mode,
        multi_domain_objective_mode=args.multi_domain_objective_mode,
        recurrent_training_mode=args.recurrent_training_mode,
        decision_residual_policy_mode=args.decision_residual_policy_mode,
        state_action_interaction_mode=args.state_action_interaction_mode,
        state_action_interaction_rank=int(args.state_action_interaction_rank),
        state_action_interaction_init_scale=float(args.state_action_interaction_init_scale),
        state_action_interaction_lr_multiplier=float(args.state_action_interaction_lr_multiplier),
        actor_base_lr_multiplier=float(args.actor_base_lr_multiplier),
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
        actor_loss_label_consistency_probe_modes=_parse_string_args(args.actor_loss_label_consistency_probe_modes),
        actor_loss_label_consistency_probe_max_training_rows=args.actor_loss_label_consistency_probe_max_training_rows,
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
        actor_linearized_representability_mode=str(args.actor_linearized_representability_mode),
        actor_linearized_cg_max_iterations=int(args.actor_linearized_cg_max_iterations),
        actor_linearized_optimizer_diagnostics=str(args.actor_linearized_optimizer_diagnostics),
        terminal_untrusted_actor_loss_max_steps_from_terminal=int(args.terminal_untrusted_actor_loss_max_steps_from_terminal),
        post_training_diagnostics=args.post_training_diagnostics,
        row_contract_mode=args.row_contract_mode,
        entropy_coef=args.entropy_coef,
        current_policy_actor_advantage_mode=args.current_policy_actor_advantage_mode,
        current_policy_local_step_reward_weight=float(args.current_policy_local_step_reward_weight),
        current_policy_local_step_reward_probe_weights=_parse_string_args(
            args.current_policy_local_step_reward_probe_weight
        ),
        detach_value_loss_recurrent_context=bool(args.detach_value_loss_recurrent_context),
        critic_warmup_epochs=args.critic_warmup_epochs,
        critic_warmup_recompute_advantage=not bool(args.no_critic_warmup_recompute_advantage),
        normalize_advantages=bool(args.normalize_advantages) and not bool(args.disable_normalize_advantages),
        advantage_normalization_mode=str(args.advantage_normalization_mode),
        max_current_policy_training_rows=args.max_current_policy_training_rows,
        domain_balance_training_weights=bool(args.domain_balance_training_weights),
        gate_domain_weight_plan_path=args.gate_domain_weight_plan_path,
        no_learning_domain_audit=bool(args.no_learning_domain_audit),
        require_movement_readiness=bool(args.require_movement_readiness),
        online_transition_buffer=bool(args.online_transition_buffer),
        persist_online_transition_rows=bool(args.persist_online_transition_rows),
        rollout_backend=args.rollout_backend,
        vector_envs=args.vector_envs,
        vector_worker_count=args.vector_worker_count,
        vector_total_env_slots=args.vector_total_env_slots,
        vector_worker_env_slots=args.vector_worker_env_slots,
        vector_worker_local_inference=bool(args.vector_worker_local_inference),
        vector_steps=args.vector_steps,
        vector_max_game_actions=args.vector_max_game_actions,
        vector_selfplay_games_per_pool=args.vector_selfplay_games_per_pool,
        vector_original_games_per_pool=args.vector_original_games_per_pool,
        vector_original_opponent_policy_ids=(
            _parse_string_args(args.vector_original_opponent_policy_id)
            or DEFAULT_ORIGINAL_OPPONENT_POLICY_IDS
        ),
        vector_training_pool_schedule=args.vector_training_pool_schedule,
        vector_gate_task_specs=_load_vector_gate_task_specs(args.vector_gate_task_specs_path),
        vector_gate_deck_pool_payloads=_load_vector_gate_deck_pool_payloads(
            args.vector_gate_deck_pool_path
        ),
        vector_inference_batch_size=args.vector_inference_batch_size,
        vector_inference_timeout_ms=args.vector_inference_timeout_ms,
        vector_worker_idle_timeout_seconds=args.vector_worker_idle_timeout_seconds,
        vector_bridge_decisions_per_env=args.vector_bridge_decisions_per_env,
        vector_drain_to_terminal=bool(args.vector_drain_to_terminal),
        vector_original_drain_to_terminal=bool(args.vector_original_drain_to_terminal),
        vector_selfplay_drain_to_terminal=bool(args.vector_selfplay_drain_to_terminal),
        vector_rolling_env_state=bool(args.vector_rolling_env_state),
        vector_execution_backend=args.vector_execution_backend,
        vector_compact_action_rows=not bool(args.disable_vector_compact_action_rows),
        allow_unpromoted_launch_actor=bool(args.allow_unpromoted_launch_actor),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
