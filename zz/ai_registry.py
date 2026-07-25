from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zz.greedy_ai import GreedyLegalPolicy
from zz.rl_ai import (
    DEEP_HUMANLIKE_PRIOR_WEIGHT,
    DEEP_LOOKAHEAD_BRANCH_WIDTH,
    DEEP_LOOKAHEAD_DEPTH,
    DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY,
    DEEP_LOOKAHEAD_WEIGHT,
    DEEP_MAX_LOOKAHEAD_ACTIONS,
    LinearQModel,
    LookaheadRLPolicy,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = PROJECT_ROOT / "data"
DEFAULT_NORMAL_MODEL_PATH = PROJECT_ROOT / "data" / "ai_training" / "quality_tactical_latest" / "best_league.json"
DEFAULT_DEEP_MODEL_PATH = PROJECT_ROOT / "data" / "ai_training" / "deep_p2_specialist_v1_latest" / "best_greedy.pt"


@dataclass(frozen=True)
class ResolvedBattlePolicy:
    requested_kind: str
    resolved_kind: str
    policy: Any
    checkpoint_path: Path | None = None
    codeman_id: str | None = None
    fallback_used: bool = False


def resolve_battle_policy(
    kind: str,
    *,
    seed: int,
    codeman_id: str | None = None,
    data_root: str | Path | None = None,
    normal_model_path: str | Path | None = None,
    deep_model_path: str | Path | None = None,
    allow_unpromoted_public_deep_v2: bool = False,
    runtime_prior_weights: dict[str, float] | None = None,
) -> ResolvedBattlePolicy:
    requested = _normalise_kind(kind)
    data_root_path = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
    normal_path = Path(normal_model_path) if normal_model_path is not None else DEFAULT_NORMAL_MODEL_PATH
    deep_path = Path(deep_model_path) if deep_model_path is not None else DEFAULT_DEEP_MODEL_PATH

    if requested == "easy":
        return _greedy_resolution(requested, seed, codeman_id=codeman_id)

    if requested in {"normal", "deep"}:
        checkpoint_path = normal_path if requested == "normal" else deep_path
        policy = _load_checkpoint_policy(
            checkpoint_path,
            seed,
            checkpoint_kind=requested,
            allow_unpromoted_public_deep_v2=allow_unpromoted_public_deep_v2,
            runtime_prior_weights=runtime_prior_weights,
        )
        return ResolvedBattlePolicy(
            requested_kind=requested,
            resolved_kind=requested,
            policy=policy,
            checkpoint_path=checkpoint_path,
            codeman_id=codeman_id,
            fallback_used=False,
        )

    load_errors: list[str] = []
    candidates = _candidate_chain(
        requested,
        data_root=data_root_path,
        codeman_id=codeman_id,
        normal_path=normal_path,
        deep_path=deep_path,
    )
    for resolved_kind, checkpoint_path in candidates:
        try:
            policy = _load_checkpoint_policy(
                checkpoint_path,
                seed,
                checkpoint_kind=resolved_kind,
                allow_unpromoted_public_deep_v2=allow_unpromoted_public_deep_v2,
                runtime_prior_weights=runtime_prior_weights,
            )
        except (FileNotFoundError, ValueError) as exc:
            load_errors.append(str(exc))
            continue
        return ResolvedBattlePolicy(
            requested_kind=requested,
            resolved_kind=resolved_kind,
            policy=policy,
            checkpoint_path=checkpoint_path,
            codeman_id=codeman_id,
            fallback_used=resolved_kind != requested,
        )

    tried = "; ".join(load_errors) if load_errors else "no codeman champion or public checkpoint was configured"
    raise FileNotFoundError(f"codeman public checkpoint missing: {tried}")


def write_codeman_champion(
    codeman_id: str,
    *,
    checkpoint_path: str | Path,
    model_kind: str,
    data_root: str | Path | None = None,
) -> Path:
    data_root_path = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
    pointer_path = _codeman_champion_pointer_path(data_root_path, codeman_id)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "codemanId": codeman_id,
        "modelKind": str(model_kind),
        "checkpointPath": str(Path(checkpoint_path)),
    }
    pointer_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return pointer_path


def read_codeman_champion(codeman_id: str, *, data_root: str | Path | None = None) -> dict[str, Any] | None:
    data_root_path = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
    pointer_path = _codeman_champion_pointer_path(data_root_path, codeman_id)
    if not pointer_path.exists():
        return None
    try:
        data = json.loads(pointer_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    checkpoint_path = data.get("checkpointPath")
    if not checkpoint_path:
        return None
    return {
        "modelKind": data.get("modelKind"),
        "checkpointPath": str(Path(str(checkpoint_path))),
        "pointerPath": str(pointer_path),
    }


def _candidate_chain(
    requested: str,
    *,
    data_root: Path,
    codeman_id: str | None,
    normal_path: Path,
    deep_path: Path,
) -> list[tuple[str, Path]]:
    if requested == "normal":
        return [("normal", normal_path)]
    if requested == "deep":
        return [("deep", deep_path), ("normal", normal_path)]
    if requested == "codeman":
        chain: list[tuple[str, Path]] = []
        champion_path = _read_codeman_champion_path(data_root, codeman_id)
        if champion_path is not None:
            chain.append(("codeman", champion_path))
        chain.extend([("deep", deep_path), ("normal", normal_path)])
        return chain
    raise ValueError(f"unknown battle policy kind: {requested!r}")


def _load_checkpoint_policy(
    path: Path,
    seed: int,
    *,
    checkpoint_kind: str = "model",
    allow_unpromoted_public_deep_v2: bool = False,
    runtime_prior_weights: dict[str, Any] | None = None,
) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"{checkpoint_kind} checkpoint missing: {path}")
    try:
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and bool(payload.get("runtimeLaunchableActor")):
                from zz.policy_factories import create_current_policy_actor_rollout_policy

                actor_id = str(payload.get("actorPolicyId") or payload.get("candidatePolicyId") or payload.get("modelId") or "")
                return create_current_policy_actor_rollout_policy(
                    model_path=path,
                    seed=seed,
                    policy_id=actor_id,
                    expected_candidate_policy_ids=[actor_id],
                    expected_source_actor_policy_id=str(payload.get("sourceActorPolicyId") or ""),
                    min_source_rows=0,
                )
        if path.suffix.lower() == ".pt":
            from zz.deep_rl import TorchActionValueModel

            model = TorchActionValueModel.load(path)
            if not allow_unpromoted_public_deep_v2 and _is_rejected_public_deep_v2_candidate(model):
                raise ValueError(f"{checkpoint_kind} checkpoint not promoted: {path}")
            policy_kwargs = {
                "lookahead_weight": DEEP_LOOKAHEAD_WEIGHT,
                "max_lookahead_actions": DEEP_MAX_LOOKAHEAD_ACTIONS,
                "lookahead_depth": DEEP_LOOKAHEAD_DEPTH,
                "lookahead_branch_width": DEEP_LOOKAHEAD_BRANCH_WIDTH,
                "lookahead_key_decisions_only": DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY,
                "humanlike_prior_weight": DEEP_HUMANLIKE_PRIOR_WEIGHT,
            }
            policy_kwargs.update(_runtime_prior_kwargs(runtime_prior_weights))
            return LookaheadRLPolicy(
                model=model,
                rng=random.Random(seed),
                epsilon=0.0,
                **policy_kwargs,
            )
        return LookaheadRLPolicy(
            model=LinearQModel.load(path),
            rng=random.Random(seed),
            epsilon=0.0,
            **_runtime_prior_kwargs(runtime_prior_weights),
        )
    except (FileNotFoundError, ValueError):
        raise
    except Exception as exc:
        raise ValueError(f"{checkpoint_kind} checkpoint failed to load: {path}") from exc


def _runtime_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _runtime_prior_kwargs(runtime_prior_weights: dict[str, Any] | None) -> dict[str, Any]:
    float_keys = {
        "card_aware_prior_weight",
        "opponent_adaptive_prior_weight",
        "deck_plan_prior_weight",
        "concrete_plan_prior_weight",
        "tactical_prior_weight",
        "target_selection_prior_weight",
        "lookahead_weight",
        "survival_pressure_evaluator_weight",
        "transition_evaluator_weight",
        "bounded_mcts_planner_cpuct",
        "bounded_mcts_planner_value_weight",
        "action_set_skip_mcts_margin",
        "action_set_fast_select_margin",
        "action_set_takeover_margin",
        "action_set_aux_score_weight",
        "action_set_residual_score_weight",
    }
    int_keys = {
        "max_lookahead_actions",
        "lookahead_depth",
        "lookahead_branch_width",
        "lookahead_rollout_actions",
        "transition_evaluator_horizon_turns",
        "transition_evaluator_max_actions",
        "transition_evaluator_max_calls",
        "bounded_mcts_planner_simulations",
        "bounded_mcts_planner_root_width",
        "bounded_mcts_planner_depth",
        "action_set_prune_max_actions",
        "action_set_prune_include_model_top",
    }
    if not runtime_prior_weights:
        return {}
    kwargs: dict[str, Any] = {}
    for key, value in runtime_prior_weights.items():
        if key in float_keys:
            kwargs[key] = float(value)
        elif key in int_keys:
            kwargs[key] = int(value)
        elif key == "transition_evaluator_path":
            kwargs[key] = str(value)
        elif key == "action_set_scorer_path":
            kwargs[key] = str(value)
        elif key == "action_set_residual_scorer_path":
            kwargs[key] = str(value)
        elif key == "bounded_mcts_planner_value_source":
            kwargs[key] = str(value)
        elif key == "action_set_influence_decision_kinds":
            if isinstance(value, str):
                kwargs[key] = [part.strip() for part in value.split(",") if part.strip()]
            else:
                kwargs[key] = list(value)
        elif key == "action_set_residual_decision_kinds":
            if isinstance(value, str):
                kwargs[key] = [part.strip() for part in value.split(",") if part.strip()]
            else:
                kwargs[key] = list(value)
        elif key in {
            "lookahead_key_decisions_only",
            "lookahead_use_active_policy_scores",
            "lookahead_rollout_until_self_turn",
            "transition_evaluator_key_decisions_only",
            "bounded_mcts_planner_enabled",
            "bounded_mcts_planner_key_decisions_only",
            "bounded_mcts_planner_primary_decision_path",
            "action_set_score_metadata_without_pruning",
            "action_set_allow_runtime_sidecar_pruning",
        }:
            kwargs[key] = _runtime_bool(value)
    return kwargs


def _is_rejected_public_deep_v2_candidate(model: Any) -> bool:
    metadata = getattr(model, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    if metadata.get("publicDeepV2GatePassed") is True:
        return False
    if metadata.get("publicDeepV2Candidate") is True:
        return True
    if metadata.get("policyArchitecture") == "public_deep_v2_planner":
        return True
    if metadata.get("deepV2ArchitectureVersion") == "public_deep_v2_shared_heads_v1":
        return True
    return False


def _read_codeman_champion_path(data_root: Path, codeman_id: str | None) -> Path | None:
    if not codeman_id:
        return None
    pointer_path = _codeman_champion_pointer_path(data_root, codeman_id)
    if not pointer_path.exists():
        return None
    try:
        data = json.loads(pointer_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw_path = data.get("checkpointPath")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return data_root / path


def _codeman_champion_pointer_path(data_root: Path, codeman_id: str) -> Path:
    return data_root / "codeman_ai" / codeman_id / "champion.json"


def _greedy_resolution(
    requested: str,
    seed: int,
    *,
    codeman_id: str | None,
    fallback_used: bool = False,
) -> ResolvedBattlePolicy:
    return ResolvedBattlePolicy(
        requested_kind=requested,
        resolved_kind="easy",
        policy=GreedyLegalPolicy(random.Random(seed)),
        checkpoint_path=None,
        codeman_id=codeman_id,
        fallback_used=fallback_used,
    )


def _normalise_kind(kind: str) -> str:
    cleaned = str(kind).strip().lower()
    if cleaned not in {"easy", "normal", "deep", "codeman"}:
        raise ValueError(f"unknown battle policy kind: {kind!r}")
    return cleaned
