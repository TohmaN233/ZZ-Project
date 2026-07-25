from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import numpy as np
import torch
from torch import nn

from zz.ai import RandomLegalPolicy
from zz.enums import CardType
from zz.greedy_ai import GreedyLegalPolicy
from zz.model import Action
from zz.rl_ai import (
    DEEP_LOOKAHEAD_WEIGHT,
    DEEP_MAX_LOOKAHEAD_ACTIONS,
    FeatureExtractor,
    LinearQModel,
    OBSERVED_OPPONENT_FEATURE_VERSION,
    _card_cost,
    _compact_rows,
    _utc_now,
    action_choices_after_preinference,
    apply_public_deep_v2_planner_to_action_choices,
    card_aware_action_prior,
    opponent_adaptive_action_prior,
    player_correction_score,
    PUBLIC_DEEP_V2_RERANK_RUNTIME_GUARD_VERSION,
    PUBLIC_DEEP_V2_SEMANTIC_BRIDGE_VERSION,
    model_public_deep_v2_planner_prior_weight,
    model_public_deep_v2_understanding_runtime_weight,
    model_scoring_features,
    model_scores_observed_opponent_features,
    model_uses_observed_opponent_features,
    model_uses_public_deep_v2_planner,
    model_uses_public_deep_v2_semantic_bridge,
    public_deep_v2_planner_prior,
    tactical_action_prior,
    target_choices_after_preinference,
    target_selection_player_for_context,
    target_selection_prior,
)


MODEL_KIND = "torch_action_value"
MODEL_VERSION = 1
MULTITASK_HEAD_VERSION = "deep_v2_multitask_heads_v1"
PUBLIC_DEEP_V2_ARCHITECTURE_VERSION = "public_deep_v2_shared_heads_v1"
PUBLIC_DEEP_V2_RERANK_HEAD_VERSION = "public_deep_v2_rerank_head_v1"
PUBLIC_DEEP_V2_UNDERSTANDING_HEAD_VERSION = "public_deep_v2_understanding_head_v1"
PUBLIC_DEEP_V2_UNDERSTANDING_ENCODER_VERSION = "public_deep_v2_understanding_encoder_v1"
PUBLIC_DEEP_V2_UNDERSTANDING_RUNTIME_VERSION = "public_deep_v2_understanding_runtime_v1"
DEFAULT_INTENT_LABELS = (
    "grow_base",
    "preserve_ready_colors",
    "hold_defense",
    "remove_threat",
    "buff_for_combat",
    "break_force",
    "pressure_life",
    "protect_combo_piece",
    "search_draw_setup",
    "execute_combo",
    "prepare_next_turn_lethal",
    "take_lethal_now",
)
DEFAULT_PLAN_LABELS = (
    "preserve_life_against_greedy",
    "preserve_last_blocker",
    "avoid_spends_last_blocker",
    "spends_last_blocker",
    "attack_exposes_lethal_next_turn",
    "suicide_into_bigger_blocker",
    "misses_base_growth",
    "covers_only_ready_color",
    "resource_base_loss",
    "buff_correct_target",
    "buff_before_combat",
)
DEFAULT_UNDERSTANDING_LABELS = (
    "card_role:removal",
    "card_role:buff",
    "card_role:draw",
    "card_role:combo_piece",
    "card_role:life_exchange",
    "card_role:defensive_flash",
    "target_semantics:harmful",
    "target_semantics:beneficial",
    "target_semantics:enemy_preferred",
    "target_semantics:own_preferred",
    "zone_value:good_mana_card",
    "zone_value:poor_mana_card",
    "zone_value:protect_in_base",
    "zone_value:stay_field_as_blocker",
    "zone_value:usually_should_not_attack",
    "tactical_risk:zero_dp_attacker",
    "deck_archetype:aggro",
    "deck_archetype:control",
    "deck_archetype:combo",
    "deck_archetype:ramp",
    "combo_route:life_exchange",
    "deck_trait:resource_sensitive",
)


def _dedupe_labels(labels: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        normalized = str(label).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _normalize_plan_targets(targets: Iterable[Iterable[str] | str]) -> list[tuple[str, ...]]:
    normalized: list[tuple[str, ...]] = []
    for target in targets:
        if isinstance(target, str):
            labels = [target]
        else:
            labels = [str(label) for label in target]
        normalized.append(_dedupe_labels(labels))
    return normalized


def _normalize_understanding_targets(targets: Iterable[Iterable[str] | str]) -> list[tuple[str, ...]]:
    return _normalize_plan_targets(targets)


def _intent_class_weights(
    labels: tuple[str, ...],
    intent_indexes: list[int],
    device: torch.device,
) -> tuple[torch.Tensor | None, dict[str, float]]:
    if not intent_indexes:
        return None, {}
    counts = Counter(intent_indexes)
    total = sum(counts.values())
    class_count = max(1, len(counts))
    weights = torch.ones(len(labels), dtype=torch.float32, device=device)
    report: dict[str, float] = {}
    for index, count in counts.items():
        value = float(total / max(1, class_count * count))
        weights[index] = value
        if 0 <= index < len(labels):
            report[labels[index]] = value
    return weights, report


def _plan_positive_weights(
    labels: tuple[str, ...],
    plan_vectors: list[list[float]],
    observed_plan_labels: set[str],
    device: torch.device,
) -> tuple[torch.Tensor | None, dict[str, float]]:
    if not plan_vectors:
        return None, {}
    samples = len(plan_vectors)
    positive_counts = [0 for _ in labels]
    for vector in plan_vectors:
        for index, value in enumerate(vector[:len(labels)]):
            if float(value) > 0.0:
                positive_counts[index] += 1
    weights = torch.ones(len(labels), dtype=torch.float32, device=device)
    report: dict[str, float] = {}
    for index, count in enumerate(positive_counts):
        if count <= 0:
            continue
        value = float((samples - count) / max(1, count))
        weights[index] = max(1.0, value)
        if labels[index] in observed_plan_labels:
            report[labels[index]] = float(weights[index].detach().cpu().item())
    return weights, report


def _understanding_positive_weights(
    labels: tuple[str, ...],
    target_vectors: list[list[float]],
    observed_labels: set[str],
    device: torch.device,
) -> tuple[torch.Tensor | None, dict[str, float]]:
    if not target_vectors:
        return None, {}
    samples = len(target_vectors)
    positive_counts = [0 for _ in labels]
    for vector in target_vectors:
        for index, value in enumerate(vector[:len(labels)]):
            if float(value) > 0.0:
                positive_counts[index] += 1
    weights = torch.ones(len(labels), dtype=torch.float32, device=device)
    report: dict[str, float] = {}
    for index, count in enumerate(positive_counts):
        if count <= 0:
            continue
        value = float((samples - count) / max(1, count))
        weights[index] = max(1.0, value)
        if labels[index] in observed_labels:
            report[labels[index]] = float(weights[index].detach().cpu().item())
    return weights, report


def _resolve_torch_device(
    device: str | torch.device | None = "auto",
    *,
    require_cuda: bool = False,
) -> torch.device:
    if require_cuda and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this deep training run, but PyTorch reports CUDA unavailable")
    if device is None or str(device).lower() == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    resolved = torch.device(device)
    if resolved.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested, but the installed PyTorch build cannot use CUDA")
    if require_cuda and resolved.type != "cuda":
        raise RuntimeError(f"CUDA is required for this deep training run, but resolved device is {resolved}")
    return resolved


def _torch_environment_metadata(device: str | torch.device | None = None) -> dict[str, Any]:
    cuda_available = bool(torch.cuda.is_available())
    device_count = int(torch.cuda.device_count()) if cuda_available else 0
    device_name = None
    if cuda_available and device_count > 0:
        try:
            resolved = torch.device(device) if device is not None and str(device).lower() != "auto" else torch.device("cuda")
            index = 0 if resolved.index is None else int(resolved.index)
            if resolved.type == "cuda" and index < device_count:
                device_name = torch.cuda.get_device_name(index)
        except Exception:
            device_name = torch.cuda.get_device_name(0)
    return {
        "torchVersion": str(torch.__version__),
        "cudaAvailable": cuda_available,
        "cudaVersion": str(torch.version.cuda) if torch.version.cuda is not None else None,
        "cudaDeviceCount": device_count,
        "cudaDeviceName": device_name,
    }


@dataclass(frozen=True)
class HashedFeatureVectorizer:
    size: int = 512

    def transform(self, features: dict[str, float]) -> np.ndarray:
        vector = np.zeros((self.size,), dtype=np.float32)
        for name, value in features.items():
            if not value:
                continue
            vector[self._index(name)] += float(value)
        return vector

    def transform_many(self, rows: Iterable[dict[str, float]]) -> np.ndarray:
        return np.stack([self.transform(row) for row in rows]).astype(np.float32)

    def _index(self, name: str) -> int:
        digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "little") % self.size


@dataclass
class TorchActionValueModel:
    vectorizer: HashedFeatureVectorizer = field(default_factory=HashedFeatureVectorizer)
    hidden_size: int = 128
    learning_rate: float = 0.0003
    seed: int = 20260523
    device: str | torch.device | None = "auto"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        torch.manual_seed(self.seed)
        self.device = _resolve_torch_device(self.device)
        self.network = nn.Sequential(
            nn.Linear(self.vectorizer.size, self.hidden_size),
            nn.ReLU(),
            nn.Linear(self.hidden_size, 1),
        )
        self.network.to(self.device)
        self.state_value_head: nn.Module | None = None
        self.intent_head: nn.Module | None = None
        self.intent_labels: tuple[str, ...] = ()
        self.plan_labels: tuple[str, ...] = ()
        self.understanding_labels: tuple[str, ...] = ()
        self.deep_v2_encoder: nn.Module | None = None
        self.deep_v2_action_head: nn.Module | None = None
        self.deep_v2_state_head: nn.Module | None = None
        self.deep_v2_intent_head: nn.Module | None = None
        self.deep_v2_plan_head: nn.Module | None = None
        self.deep_v2_rerank_head: nn.Module | None = None
        self.deep_v2_understanding_encoder: nn.Module | None = None
        self.deep_v2_understanding_head: nn.Module | None = None
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr=self.learning_rate)
        self.loss_fn = nn.MSELoss()

    @property
    def has_multitask_heads(self) -> bool:
        return (
            self.state_value_head is not None and self.intent_head is not None
        ) or (
            self.deep_v2_state_head is not None and self.deep_v2_intent_head is not None
        )

    @property
    def has_public_deep_v2_architecture(self) -> bool:
        return (
            self.deep_v2_encoder is not None
            and self.deep_v2_action_head is not None
            and self.deep_v2_state_head is not None
            and self.deep_v2_intent_head is not None
            and self.deep_v2_plan_head is not None
        )

    def enable_multitask_heads(self, intent_labels: Iterable[str] = DEFAULT_INTENT_LABELS) -> None:
        labels = tuple(str(label) for label in intent_labels)
        if not labels:
            raise ValueError("at least one intent label is required")
        if self.has_multitask_heads and self.intent_labels == labels:
            return
        self.intent_labels = labels
        self.state_value_head = nn.Sequential(
            nn.Linear(self.vectorizer.size, self.hidden_size),
            nn.ReLU(),
            nn.Linear(self.hidden_size, 1),
        ).to(self.device)
        self.intent_head = nn.Sequential(
            nn.Linear(self.vectorizer.size, self.hidden_size),
            nn.ReLU(),
            nn.Linear(self.hidden_size, len(labels)),
        ).to(self.device)
        self.metadata["multitaskHeadVersion"] = MULTITASK_HEAD_VERSION
        self.metadata["intentLabels"] = list(labels)
        self._rebuild_optimizer()

    def enable_public_deep_v2_architecture(
        self,
        *,
        intent_labels: Iterable[str] = DEFAULT_INTENT_LABELS,
        plan_labels: Iterable[str] = DEFAULT_PLAN_LABELS,
    ) -> None:
        intent_label_tuple = _dedupe_labels(intent_labels)
        plan_label_tuple = _dedupe_labels(plan_labels)
        if not intent_label_tuple:
            raise ValueError("at least one intent label is required")
        if not plan_label_tuple:
            raise ValueError("at least one plan label is required")
        if not self.has_public_deep_v2_architecture:
            self.deep_v2_encoder = nn.Sequential(
                copy.deepcopy(self.network[0]),
                nn.ReLU(),
            ).to(self.device)
            self.deep_v2_action_head = copy.deepcopy(self.network[-1]).to(self.device)
            self.deep_v2_state_head = nn.Linear(self.hidden_size, 1).to(self.device)
            self.deep_v2_intent_head = nn.Linear(self.hidden_size, len(intent_label_tuple)).to(self.device)
            self.deep_v2_plan_head = nn.Linear(self.hidden_size, len(plan_label_tuple)).to(self.device)
            self.deep_v2_rerank_head = nn.Linear(self.hidden_size, 1).to(self.device)
        elif self.intent_labels != intent_label_tuple:
            self.deep_v2_intent_head = nn.Linear(self.hidden_size, len(intent_label_tuple)).to(self.device)
        elif self.plan_labels != plan_label_tuple:
            self.deep_v2_plan_head = nn.Linear(self.hidden_size, len(plan_label_tuple)).to(self.device)
        if self.deep_v2_rerank_head is None:
            self.deep_v2_rerank_head = nn.Linear(self.hidden_size, 1).to(self.device)
        self.intent_labels = intent_label_tuple
        self.plan_labels = plan_label_tuple
        self.metadata["deepV2ArchitectureVersion"] = PUBLIC_DEEP_V2_ARCHITECTURE_VERSION
        self.metadata["multitaskHeadVersion"] = MULTITASK_HEAD_VERSION
        self.metadata["intentLabels"] = list(intent_label_tuple)
        self.metadata["planLabels"] = list(plan_label_tuple)
        self._rebuild_optimizer()

    def _ensure_public_deep_v2_plan_labels(self, labels: Iterable[str]) -> None:
        requested = _dedupe_labels((*self.plan_labels, *labels)) if self.plan_labels else _dedupe_labels(labels)
        if not requested:
            requested = DEFAULT_PLAN_LABELS
        if not self.has_public_deep_v2_architecture or requested != self.plan_labels:
            self.enable_public_deep_v2_architecture(
                intent_labels=self.intent_labels or DEFAULT_INTENT_LABELS,
                plan_labels=requested,
            )

    def enable_public_deep_v2_understanding_head(
        self,
        labels: Iterable[str] = DEFAULT_UNDERSTANDING_LABELS,
    ) -> None:
        label_tuple = _dedupe_labels(labels)
        if not label_tuple:
            raise ValueError("at least one understanding label is required")
        if not self.has_public_deep_v2_architecture:
            self.enable_public_deep_v2_architecture()
        if self.deep_v2_understanding_encoder is None:
            self.deep_v2_understanding_encoder = nn.Sequential(
                copy.deepcopy(self.network[0]),
                nn.ReLU(),
            ).to(self.device)
        if self.deep_v2_understanding_head is None or self.understanding_labels != label_tuple:
            self.deep_v2_understanding_head = nn.Linear(self.hidden_size, len(label_tuple)).to(self.device)
        self.understanding_labels = label_tuple
        self.metadata["publicDeepV2UnderstandingEncoderVersion"] = PUBLIC_DEEP_V2_UNDERSTANDING_ENCODER_VERSION
        self.metadata["publicDeepV2UnderstandingHeadVersion"] = PUBLIC_DEEP_V2_UNDERSTANDING_HEAD_VERSION
        self.metadata["understandingLabels"] = list(label_tuple)
        self._rebuild_optimizer()

    def _trainable_parameters(self) -> list[nn.Parameter]:
        if self.has_public_deep_v2_architecture:
            assert self.deep_v2_encoder is not None
            assert self.deep_v2_action_head is not None
            assert self.deep_v2_state_head is not None
            assert self.deep_v2_intent_head is not None
            assert self.deep_v2_plan_head is not None
            modules: list[nn.Module] = [
                self.deep_v2_encoder,
                self.deep_v2_action_head,
                self.deep_v2_state_head,
                self.deep_v2_intent_head,
                self.deep_v2_plan_head,
                self.deep_v2_rerank_head,
                self.deep_v2_understanding_encoder,
                self.deep_v2_understanding_head,
            ]
        else:
            modules = [self.network]
        if self.state_value_head is not None:
            modules.append(self.state_value_head)
        if self.intent_head is not None:
            modules.append(self.intent_head)
        return [
            parameter
            for module in modules
            if module is not None
            for parameter in module.parameters()
            if parameter.requires_grad
        ]

    def _rebuild_optimizer(self) -> None:
        self.optimizer = torch.optim.Adam(self._trainable_parameters(), lr=self.learning_rate)

    def configure_trainable_parameters(self, scope: str = "all") -> None:
        resolved_scope = str(scope or "all").strip().lower()
        if resolved_scope not in {"all", "head"}:
            raise ValueError(f"unknown torch train scope: {scope!r}")
        if self.has_public_deep_v2_architecture:
            assert self.deep_v2_encoder is not None
            for parameter in self.network.parameters():
                parameter.requires_grad = False
            for parameter in self.deep_v2_encoder.parameters():
                parameter.requires_grad = resolved_scope == "all"
            for head in (
                self.deep_v2_action_head,
                self.deep_v2_state_head,
                self.deep_v2_intent_head,
                self.deep_v2_plan_head,
                self.deep_v2_rerank_head,
                self.deep_v2_understanding_head,
            ):
                if head is None:
                    continue
                for parameter in head.parameters():
                    parameter.requires_grad = True
            if self.deep_v2_understanding_encoder is not None:
                for parameter in self.deep_v2_understanding_encoder.parameters():
                    parameter.requires_grad = True
        else:
            for parameter in self.network.parameters():
                parameter.requires_grad = resolved_scope == "all"
            if resolved_scope == "head":
                for parameter in self.network[-1].parameters():
                    parameter.requires_grad = True
        for head in (self.state_value_head, self.intent_head):
            if head is None:
                continue
            for parameter in head.parameters():
                parameter.requires_grad = True
        self._rebuild_optimizer()
        self.metadata["trainScope"] = resolved_scope

    def _encoded_batch(self, batch: torch.Tensor) -> torch.Tensor:
        assert self.deep_v2_encoder is not None
        return self.deep_v2_encoder(batch)

    def _understanding_encoded_batch(self, batch: torch.Tensor) -> torch.Tensor:
        encoder = self.deep_v2_understanding_encoder or self.deep_v2_encoder
        assert encoder is not None
        return encoder(batch)

    def _action_scores_tensor(self, batch: torch.Tensor) -> torch.Tensor:
        if self.has_public_deep_v2_architecture:
            assert self.deep_v2_action_head is not None
            return self.deep_v2_action_head(self._encoded_batch(batch)).squeeze(-1)
        return self.network(batch).squeeze(-1)

    def score_many(self, feature_rows: list[dict[str, float]]) -> list[float]:
        if not feature_rows:
            return []
        self.network.eval()
        for module in (
            self.deep_v2_encoder,
            self.deep_v2_action_head,
        ):
            if module is not None:
                module.eval()
        with torch.no_grad():
            batch = torch.from_numpy(self.vectorizer.transform_many(feature_rows)).to(self.device)
            scores = self._action_scores_tensor(batch)
        return [float(score) for score in scores.detach().cpu().tolist()]

    def score(self, features: dict[str, float]) -> float:
        return self.score_many([features])[0]

    def state_value_many(self, feature_rows: list[dict[str, float]]) -> list[float]:
        if not self.has_multitask_heads:
            raise RuntimeError("multitask heads are not enabled")
        if not feature_rows:
            return []
        if self.has_public_deep_v2_architecture:
            assert self.deep_v2_encoder is not None
            assert self.deep_v2_state_head is not None
            self.deep_v2_encoder.eval()
            self.deep_v2_state_head.eval()
        else:
            assert self.state_value_head is not None
            self.state_value_head.eval()
        with torch.no_grad():
            batch = torch.from_numpy(self.vectorizer.transform_many(feature_rows)).to(self.device)
            if self.has_public_deep_v2_architecture:
                assert self.deep_v2_state_head is not None
                values = self.deep_v2_state_head(self._encoded_batch(batch)).squeeze(-1)
            else:
                assert self.state_value_head is not None
                values = self.state_value_head(batch).squeeze(-1)
        return [float(value) for value in values.detach().cpu().tolist()]

    def intent_logits_many(self, feature_rows: list[dict[str, float]]) -> list[list[float]]:
        if not self.has_multitask_heads:
            raise RuntimeError("multitask heads are not enabled")
        if not feature_rows:
            return []
        if self.has_public_deep_v2_architecture:
            assert self.deep_v2_encoder is not None
            assert self.deep_v2_intent_head is not None
            self.deep_v2_encoder.eval()
            self.deep_v2_intent_head.eval()
        else:
            assert self.intent_head is not None
            self.intent_head.eval()
        with torch.no_grad():
            batch = torch.from_numpy(self.vectorizer.transform_many(feature_rows)).to(self.device)
            if self.has_public_deep_v2_architecture:
                assert self.deep_v2_intent_head is not None
                logits = self.deep_v2_intent_head(self._encoded_batch(batch))
            else:
                assert self.intent_head is not None
                logits = self.intent_head(batch)
        return [[float(value) for value in row] for row in logits.detach().cpu().tolist()]

    def plan_logits_many(self, feature_rows: list[dict[str, float]]) -> list[list[float]]:
        if not self.has_public_deep_v2_architecture:
            raise RuntimeError("public deep v2 architecture is not enabled")
        if not feature_rows:
            return []
        assert self.deep_v2_encoder is not None
        assert self.deep_v2_plan_head is not None
        self.deep_v2_encoder.eval()
        self.deep_v2_plan_head.eval()
        with torch.no_grad():
            batch = torch.from_numpy(self.vectorizer.transform_many(feature_rows)).to(self.device)
            logits = self.deep_v2_plan_head(self._encoded_batch(batch))
        return [[float(value) for value in row] for row in logits.detach().cpu().tolist()]

    def rerank_score_many(self, feature_rows: list[dict[str, float]]) -> list[float]:
        if not self.has_public_deep_v2_architecture or self.deep_v2_rerank_head is None:
            raise RuntimeError("public deep v2 rerank head is not enabled")
        if not feature_rows:
            return []
        assert self.deep_v2_encoder is not None
        self.deep_v2_encoder.eval()
        self.deep_v2_rerank_head.eval()
        with torch.no_grad():
            batch = torch.from_numpy(self.vectorizer.transform_many(feature_rows)).to(self.device)
            scores = self.deep_v2_rerank_head(self._encoded_batch(batch)).squeeze(-1)
        return [float(score) for score in scores.detach().cpu().tolist()]

    def understanding_logits_many(self, feature_rows: list[dict[str, float]]) -> list[list[float]]:
        if not self.has_public_deep_v2_architecture or self.deep_v2_understanding_head is None:
            raise RuntimeError("public deep v2 understanding head is not enabled")
        if not feature_rows:
            return []
        assert self.deep_v2_encoder is not None
        self.deep_v2_encoder.eval()
        if self.deep_v2_understanding_encoder is not None:
            self.deep_v2_understanding_encoder.eval()
        self.deep_v2_understanding_head.eval()
        with torch.no_grad():
            batch = torch.from_numpy(self.vectorizer.transform_many(feature_rows)).to(self.device)
            logits = self.deep_v2_understanding_head(self._understanding_encoded_batch(batch))
        return [[float(value) for value in row] for row in logits.detach().cpu().tolist()]

    def understanding_action_bonus(self, features: dict[str, float]) -> float:
        if not self.has_public_deep_v2_architecture or self.deep_v2_understanding_head is None:
            return 0.0
        probe_features = _understanding_action_probe_features(features)
        if not probe_features:
            return 0.0
        try:
            logits = self.understanding_logits_many([probe_features])[0]
        except Exception:
            return 0.0
        label_scores = {
            label: _sigmoid_float(logits[index])
            for index, label in enumerate(self.understanding_labels)
            if index < len(logits)
        }
        harmful = max(
            label_scores.get("target_semantics:harmful", 0.0),
            label_scores.get("card_role:removal", 0.0),
        )
        beneficial = max(
            label_scores.get("target_semantics:beneficial", 0.0),
            label_scores.get("card_role:buff", 0.0),
        )
        target_enemy = _positive_feature(features.get("target_enemy", 0.0))
        target_own = _positive_feature(features.get("target_own", 0.0))
        bonus = 0.0
        if target_enemy:
            bonus += harmful - beneficial
        if target_own:
            bonus += beneficial - harmful
        return float(bonus)

    def train_batch(
        self,
        feature_rows: list[dict[str, float]],
        targets: list[float],
        *,
        weight: float = 1.0,
    ) -> float:
        if not feature_rows:
            return 0.0
        self.network.train()
        for module in (
            self.deep_v2_encoder,
            self.deep_v2_action_head,
        ):
            if module is not None:
                module.train()
        batch = torch.from_numpy(self.vectorizer.transform_many(feature_rows)).to(self.device)
        target_tensor = torch.tensor(targets, dtype=torch.float32, device=self.device)
        prediction = self._action_scores_tensor(batch)
        loss = self.loss_fn(prediction, target_tensor) * float(weight)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        return float(loss.detach().item())

    def train_multitask_batch(
        self,
        *,
        action_rows: list[dict[str, float]],
        action_targets: list[float],
        state_rows: list[dict[str, float]],
        state_targets: list[float],
        intent_rows: list[dict[str, float]],
        intent_targets: list[str],
        plan_rows: list[dict[str, float]] | None = None,
        plan_targets: list[Iterable[str] | str] | None = None,
        epochs: int = 1,
        weight: float = 1.0,
        preserve_action_path: bool = False,
    ) -> dict[str, Any]:
        plan_rows = list(plan_rows or [])
        normalized_plan_targets = _normalize_plan_targets(plan_targets or [])
        requested_plan_labels = _dedupe_labels(
            (*DEFAULT_PLAN_LABELS, *[label for labels in normalized_plan_targets for label in labels])
        )
        self.enable_public_deep_v2_architecture(plan_labels=requested_plan_labels)
        assert self.deep_v2_state_head is not None
        assert self.deep_v2_intent_head is not None
        assert self.deep_v2_plan_head is not None
        label_index = {label: index for index, label in enumerate(self.intent_labels)}
        filtered_intent_rows: list[dict[str, float]] = []
        intent_indexes: list[int] = []
        for row, label in zip(intent_rows, intent_targets, strict=True):
            index = label_index.get(str(label))
            if index is None:
                continue
            filtered_intent_rows.append(row)
            intent_indexes.append(index)
        plan_label_index = {label: index for index, label in enumerate(self.plan_labels)}
        filtered_plan_rows: list[dict[str, float]] = []
        plan_vectors: list[list[float]] = []
        observed_plan_labels: set[str] = set()
        for row, labels in zip(plan_rows, normalized_plan_targets, strict=False):
            indexes = [plan_label_index[label] for label in labels if label in plan_label_index]
            if not indexes:
                continue
            target_vector = [0.0 for _ in self.plan_labels]
            for index in indexes:
                target_vector[index] = 1.0
                observed_plan_labels.add(self.plan_labels[index])
            filtered_plan_rows.append(row)
            plan_vectors.append(target_vector)
        intent_class_weights, intent_class_weight_map = _intent_class_weights(
            self.intent_labels,
            intent_indexes,
            self.device,
        )
        plan_positive_weights, plan_positive_weight_map = _plan_positive_weights(
            self.plan_labels,
            plan_vectors,
            observed_plan_labels,
            self.device,
        )
        if not action_rows and not state_rows and not filtered_intent_rows and not filtered_plan_rows:
            return {
                "kind": "deep_v2_multitask_batch",
                "headVersion": MULTITASK_HEAD_VERSION,
                "architectureVersion": PUBLIC_DEEP_V2_ARCHITECTURE_VERSION,
                "epochs": 0,
                "loss": 0.0,
                "balancedAuxiliaryTargets": True,
                "intentClassWeights": intent_class_weight_map,
                "planPositiveWeights": plan_positive_weight_map,
                "samples": {"action": 0, "state": 0, "intent": 0, "plan": 0},
            }
        if state_rows:
            self.metadata["stateValueHeadVersion"] = MULTITASK_HEAD_VERSION
        losses: list[float] = []
        previous_requires_grad = _capture_public_deep_v2_action_path_requires_grad(self)
        if preserve_action_path:
            _set_public_deep_v2_action_path_trainable(self, False)
        try:
            for _ in range(max(1, int(epochs))):
                total_loss = torch.tensor(0.0, dtype=torch.float32, device=self.device)
                if action_rows:
                    action_batch = torch.from_numpy(self.vectorizer.transform_many(action_rows)).to(self.device)
                    action_target = torch.tensor(action_targets, dtype=torch.float32, device=self.device)
                    total_loss = total_loss + self.loss_fn(self._action_scores_tensor(action_batch), action_target)
                if state_rows:
                    state_batch = torch.from_numpy(self.vectorizer.transform_many(state_rows)).to(self.device)
                    state_target = torch.tensor(state_targets, dtype=torch.float32, device=self.device)
                    total_loss = total_loss + self.loss_fn(
                        self.deep_v2_state_head(self._encoded_batch(state_batch)).squeeze(-1),
                        state_target,
                    )
                if filtered_intent_rows:
                    intent_batch = torch.from_numpy(self.vectorizer.transform_many(filtered_intent_rows)).to(self.device)
                    intent_target = torch.tensor(intent_indexes, dtype=torch.long, device=self.device)
                    total_loss = total_loss + nn.CrossEntropyLoss(weight=intent_class_weights)(
                        self.deep_v2_intent_head(self._encoded_batch(intent_batch)),
                        intent_target,
                    )
                if filtered_plan_rows:
                    plan_batch = torch.from_numpy(self.vectorizer.transform_many(filtered_plan_rows)).to(self.device)
                    plan_target = torch.tensor(plan_vectors, dtype=torch.float32, device=self.device)
                    total_loss = total_loss + nn.BCEWithLogitsLoss(pos_weight=plan_positive_weights)(
                        self.deep_v2_plan_head(self._encoded_batch(plan_batch)),
                        plan_target,
                    )
                self.optimizer.zero_grad()
                (total_loss * float(weight)).backward()
                self.optimizer.step()
                losses.append(float(total_loss.detach().item()))
        finally:
            if preserve_action_path:
                _restore_public_deep_v2_action_path_requires_grad(self, previous_requires_grad)
        return {
            "kind": "deep_v2_multitask_batch",
            "headVersion": MULTITASK_HEAD_VERSION,
            "architectureVersion": PUBLIC_DEEP_V2_ARCHITECTURE_VERSION,
            "epochs": max(1, int(epochs)),
            "loss": losses[-1] if losses else 0.0,
            "balancedAuxiliaryTargets": True,
            "intentClassWeights": intent_class_weight_map,
            "planPositiveWeights": plan_positive_weight_map,
            "samples": {
                "action": len(action_rows),
                "state": len(state_rows),
                "intent": len(filtered_intent_rows),
                "plan": len(filtered_plan_rows),
            },
        }

    def train_preference_pairs(
        self,
        pairs: list[dict[str, Any]],
        *,
        margin: float = 0.5,
        weight: float = 1.0,
    ) -> float:
        if not pairs or weight <= 0.0:
            return 0.0
        self.network.train()
        for module in (self.deep_v2_encoder, self.deep_v2_action_head):
            if module is not None:
                module.train()
        good_rows = [dict(pair["goodFeatures"]) for pair in pairs]
        bad_rows = [dict(pair["badFeatures"]) for pair in pairs]
        good_batch = torch.from_numpy(self.vectorizer.transform_many(good_rows)).to(self.device)
        bad_batch = torch.from_numpy(self.vectorizer.transform_many(bad_rows)).to(self.device)
        good_scores = self._action_scores_tensor(good_batch)
        bad_scores = self._action_scores_tensor(bad_batch)
        loss = torch.relu(float(margin) - (good_scores - bad_scores)).mean() * float(weight)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        return float(loss.detach().item())

    def train_public_deep_v2_rerank_pairs(
        self,
        pairs: list[dict[str, Any]],
        *,
        epochs: int = 1,
        margin: float = 0.5,
        weight: float = 1.0,
        preserve_action_path: bool = True,
    ) -> dict[str, Any]:
        valid_pairs = [
            {
                "goodFeatures": _public_deep_v2_auxiliary_feature_row(dict(pair["goodFeatures"])),
                "badFeatures": _public_deep_v2_auxiliary_feature_row(dict(pair["badFeatures"])),
            }
            for pair in pairs
            if isinstance(pair, dict) and pair.get("goodFeatures") and pair.get("badFeatures")
        ]
        if not valid_pairs or weight <= 0.0:
            return {
                "kind": "public_deep_v2_rerank_head",
                "headVersion": PUBLIC_DEEP_V2_RERANK_HEAD_VERSION,
                "pairCount": 0,
                "epochs": 0,
                "loss": 0.0,
                "preserveActionPath": bool(preserve_action_path),
            }
        self.enable_public_deep_v2_architecture()
        assert self.deep_v2_rerank_head is not None
        previous_requires_grad = _capture_public_deep_v2_action_path_requires_grad(self)
        if preserve_action_path:
            _set_public_deep_v2_action_path_trainable(self, False)
        losses: list[float] = []
        try:
            for _ in range(max(1, int(epochs))):
                good_rows = [pair["goodFeatures"] for pair in valid_pairs]
                bad_rows = [pair["badFeatures"] for pair in valid_pairs]
                good_batch = torch.from_numpy(self.vectorizer.transform_many(good_rows)).to(self.device)
                bad_batch = torch.from_numpy(self.vectorizer.transform_many(bad_rows)).to(self.device)
                good_scores = self.deep_v2_rerank_head(self._encoded_batch(good_batch)).squeeze(-1)
                bad_scores = self.deep_v2_rerank_head(self._encoded_batch(bad_batch)).squeeze(-1)
                loss = torch.relu(float(margin) - (good_scores - bad_scores)).mean() * float(weight)
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()
                losses.append(float(loss.detach().item()))
        finally:
            if preserve_action_path:
                _restore_public_deep_v2_action_path_requires_grad(self, previous_requires_grad)
        self.metadata["publicDeepV2RerankHeadVersion"] = PUBLIC_DEEP_V2_RERANK_HEAD_VERSION
        return {
            "kind": "public_deep_v2_rerank_head",
            "headVersion": PUBLIC_DEEP_V2_RERANK_HEAD_VERSION,
            "pairCount": len(valid_pairs),
            "epochs": max(1, int(epochs)),
            "margin": float(margin),
            "weight": float(weight),
            "loss": losses[-1] if losses else 0.0,
            "preserveActionPath": bool(preserve_action_path),
        }

    def train_understanding_batch(
        self,
        *,
        feature_rows: list[dict[str, float]],
        targets: list[Iterable[str] | str],
        epochs: int = 1,
        weight: float = 1.0,
        preserve_action_path: bool = True,
    ) -> dict[str, Any]:
        normalized_targets = _normalize_understanding_targets(targets)
        labels = _dedupe_labels((*DEFAULT_UNDERSTANDING_LABELS, *[
            label
            for target_labels in normalized_targets
            for label in target_labels
        ]))
        valid_rows: list[dict[str, float]] = []
        target_vectors: list[list[float]] = []
        self.enable_public_deep_v2_understanding_head(labels)
        label_index = {label: index for index, label in enumerate(self.understanding_labels)}
        for row, target_labels in zip(feature_rows, normalized_targets, strict=False):
            indexes = [label_index[label] for label in target_labels if label in label_index]
            if not indexes:
                continue
            vector = [0.0 for _ in self.understanding_labels]
            for index in indexes:
                vector[index] = 1.0
            valid_rows.append(row)
            target_vectors.append(vector)
        observed_labels = {
            self.understanding_labels[index]
            for vector in target_vectors
            for index, value in enumerate(vector[:len(self.understanding_labels)])
            if float(value) > 0.0
        }
        positive_weights, positive_weight_map = _understanding_positive_weights(
            self.understanding_labels,
            target_vectors,
            observed_labels,
            self.device,
        )
        if not valid_rows or weight <= 0.0:
            return {
                "kind": "public_deep_v2_understanding_head",
                "headVersion": PUBLIC_DEEP_V2_UNDERSTANDING_HEAD_VERSION,
                "samples": 0,
                "epochs": 0,
                "loss": 0.0,
                "preserveActionPath": bool(preserve_action_path),
                "understandingPositiveWeights": positive_weight_map,
            }
        assert self.deep_v2_understanding_head is not None
        previous_requires_grad = _capture_public_deep_v2_action_path_requires_grad(self)
        if preserve_action_path:
            _set_public_deep_v2_action_path_trainable(self, False)
        losses: list[float] = []
        try:
            for _ in range(max(1, int(epochs))):
                batch = torch.from_numpy(self.vectorizer.transform_many(valid_rows)).to(self.device)
                target_tensor = torch.tensor(target_vectors, dtype=torch.float32, device=self.device)
                logits = self.deep_v2_understanding_head(self._understanding_encoded_batch(batch))
                loss = nn.BCEWithLogitsLoss(pos_weight=positive_weights)(logits, target_tensor) * float(weight)
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()
                losses.append(float(loss.detach().item()))
        finally:
            if preserve_action_path:
                _restore_public_deep_v2_action_path_requires_grad(self, previous_requires_grad)
        self.metadata["publicDeepV2UnderstandingHeadVersion"] = PUBLIC_DEEP_V2_UNDERSTANDING_HEAD_VERSION
        self.metadata["publicDeepV2UnderstandingEncoderVersion"] = PUBLIC_DEEP_V2_UNDERSTANDING_ENCODER_VERSION
        self.metadata["understandingLabels"] = list(self.understanding_labels)
        return {
            "kind": "public_deep_v2_understanding_head",
            "headVersion": PUBLIC_DEEP_V2_UNDERSTANDING_HEAD_VERSION,
            "understandingEncoderVersion": PUBLIC_DEEP_V2_UNDERSTANDING_ENCODER_VERSION,
            "samples": len(valid_rows),
            "epochs": max(1, int(epochs)),
            "loss": losses[-1] if losses else 0.0,
            "preserveActionPath": bool(preserve_action_path),
            "understandingPositiveWeights": positive_weight_map,
        }

    def save(self, path: str | Path, *, metadata: dict[str, Any] | None = None) -> None:
        if metadata is not None:
            merged_metadata = dict(self.metadata)
            merged_metadata.update(metadata)
            self.metadata = merged_metadata
        data = {
            "kind": MODEL_KIND,
            "version": MODEL_VERSION,
            "createdAt": _utc_now(),
            "vectorizerSize": self.vectorizer.size,
            "hiddenSize": self.hidden_size,
            "learningRate": self.learning_rate,
            "device": str(self.device),
            "metadata": dict(self.metadata),
            "stateDict": {key: value.detach().cpu() for key, value in self.network.state_dict().items()},
            "multitaskHeads": self._multitask_heads_state_dict(),
            "publicDeepV2Architecture": self._public_deep_v2_architecture_state_dict(),
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(data, path)

    @classmethod
    def load(cls, path: str | Path, *, device: str | torch.device | None = "auto") -> "TorchActionValueModel":
        resolved_device = _resolve_torch_device(device)
        data = torch.load(Path(path), map_location=resolved_device, weights_only=False)
        if data.get("kind") != MODEL_KIND:
            raise ValueError(f"unsupported model kind: {data.get('kind')!r}")
        model = cls(
            vectorizer=HashedFeatureVectorizer(size=int(data["vectorizerSize"])),
            hidden_size=int(data["hiddenSize"]),
            learning_rate=float(data.get("learningRate", 0.0003)),
            device=resolved_device,
            metadata=dict(data.get("metadata", {})),
        )
        model.network.load_state_dict(data["stateDict"])
        heads = data.get("multitaskHeads")
        if isinstance(heads, dict):
            model.enable_multitask_heads(tuple(heads.get("intentLabels") or DEFAULT_INTENT_LABELS))
            assert model.state_value_head is not None
            assert model.intent_head is not None
            model.state_value_head.load_state_dict(heads["stateValueStateDict"])
            model.intent_head.load_state_dict(heads["intentStateDict"])
        architecture = data.get("publicDeepV2Architecture")
        if isinstance(architecture, dict):
            model.enable_public_deep_v2_architecture(
                intent_labels=tuple(architecture.get("intentLabels") or DEFAULT_INTENT_LABELS),
                plan_labels=tuple(architecture.get("planLabels") or DEFAULT_PLAN_LABELS),
            )
            assert model.deep_v2_encoder is not None
            assert model.deep_v2_action_head is not None
            assert model.deep_v2_state_head is not None
            assert model.deep_v2_intent_head is not None
            assert model.deep_v2_plan_head is not None
            assert model.deep_v2_rerank_head is not None
            model.deep_v2_encoder.load_state_dict(architecture["encoderStateDict"])
            model.deep_v2_action_head.load_state_dict(architecture["actionHeadStateDict"])
            model.deep_v2_state_head.load_state_dict(architecture["stateHeadStateDict"])
            model.deep_v2_intent_head.load_state_dict(architecture["intentHeadStateDict"])
            model.deep_v2_plan_head.load_state_dict(architecture["planHeadStateDict"])
            if "rerankHeadStateDict" in architecture:
                model.deep_v2_rerank_head.load_state_dict(architecture["rerankHeadStateDict"])
            if isinstance(architecture.get("understandingHeadStateDict"), dict):
                model.enable_public_deep_v2_understanding_head(
                    tuple(architecture.get("understandingLabels") or DEFAULT_UNDERSTANDING_LABELS)
                )
                assert model.deep_v2_understanding_head is not None
                if isinstance(architecture.get("understandingEncoderStateDict"), dict):
                    assert model.deep_v2_understanding_encoder is not None
                    model.deep_v2_understanding_encoder.load_state_dict(
                        architecture["understandingEncoderStateDict"]
                    )
                else:
                    model.deep_v2_understanding_encoder = None
                model.deep_v2_understanding_head.load_state_dict(architecture["understandingHeadStateDict"])
                model._rebuild_optimizer()
        return model

    def _multitask_heads_state_dict(self) -> dict[str, Any] | None:
        if self.state_value_head is None or self.intent_head is None:
            return None
        return {
            "version": MULTITASK_HEAD_VERSION,
            "intentLabels": list(self.intent_labels),
            "stateValueStateDict": {
                key: value.detach().cpu()
                for key, value in self.state_value_head.state_dict().items()
            },
            "intentStateDict": {
                key: value.detach().cpu()
                for key, value in self.intent_head.state_dict().items()
            },
        }

    def _public_deep_v2_architecture_state_dict(self) -> dict[str, Any] | None:
        if not self.has_public_deep_v2_architecture:
            return None
        assert self.deep_v2_encoder is not None
        assert self.deep_v2_action_head is not None
        assert self.deep_v2_state_head is not None
        assert self.deep_v2_intent_head is not None
        assert self.deep_v2_plan_head is not None
        assert self.deep_v2_rerank_head is not None
        return {
            "version": PUBLIC_DEEP_V2_ARCHITECTURE_VERSION,
            "intentLabels": list(self.intent_labels),
            "planLabels": list(self.plan_labels),
            "understandingLabels": list(self.understanding_labels),
            "encoderStateDict": {
                key: value.detach().cpu()
                for key, value in self.deep_v2_encoder.state_dict().items()
            },
            "actionHeadStateDict": {
                key: value.detach().cpu()
                for key, value in self.deep_v2_action_head.state_dict().items()
            },
            "stateHeadStateDict": {
                key: value.detach().cpu()
                for key, value in self.deep_v2_state_head.state_dict().items()
            },
            "intentHeadStateDict": {
                key: value.detach().cpu()
                for key, value in self.deep_v2_intent_head.state_dict().items()
            },
            "planHeadStateDict": {
                key: value.detach().cpu()
                for key, value in self.deep_v2_plan_head.state_dict().items()
            },
            "rerankHeadStateDict": {
                key: value.detach().cpu()
                for key, value in self.deep_v2_rerank_head.state_dict().items()
            },
            "understandingEncoderVersion": (
                PUBLIC_DEEP_V2_UNDERSTANDING_ENCODER_VERSION
                if self.deep_v2_understanding_encoder is not None
                else None
            ),
            "understandingEncoderStateDict": (
                {
                    key: value.detach().cpu()
                    for key, value in self.deep_v2_understanding_encoder.state_dict().items()
                }
                if self.deep_v2_understanding_encoder is not None
                else None
            ),
            "understandingHeadStateDict": (
                {
                    key: value.detach().cpu()
                    for key, value in self.deep_v2_understanding_head.state_dict().items()
                }
                if self.deep_v2_understanding_head is not None
                else None
            ),
        }


def _understanding_action_probe_features(features: dict[str, float]) -> dict[str, float]:
    probe: dict[str, float] = {}
    for key, value in features.items():
        if not _positive_feature(value):
            continue
        if key in {"action:play_card", "action:activate_flash_ability", "decision:generic_target"}:
            probe["understanding:card"] = 1.0
        elif key == "play_card_is_magic":
            probe["raw_card_type:magic"] = 1.0
        elif key == "play_card_is_minion":
            probe["raw_card_type:minion"] = 1.0
        elif key.startswith("play_card_effect:"):
            probe[f"raw_effect:{key.split(':', 1)[1]}"] = 1.0
            probe["understanding:card"] = 1.0
        elif key.startswith("target_effect:"):
            probe[f"raw_effect:{key.split(':', 1)[1]}"] = 1.0
            probe["understanding:card"] = 1.0
        elif key.startswith("target_kind:"):
            probe[f"raw_target_kind:{key.split(':', 1)[1]}"] = 1.0
            probe["understanding:card"] = 1.0
        elif key.startswith("raw_effect:") or key.startswith("raw_target_kind:") or key.startswith("raw_card_type:"):
            probe[key] = float(value)
            probe["understanding:card"] = 1.0
    return probe if len(probe) > 1 else {}


def _positive_feature(value: Any) -> bool:
    try:
        return float(value) > 0.0
    except (TypeError, ValueError):
        return False


def _sigmoid_float(value: float) -> float:
    if value >= 0.0:
        z = math.exp(-float(value))
        return 1.0 / (1.0 + z)
    z = math.exp(float(value))
    return z / (1.0 + z)


class TorchMaskedPolicy:
    def __init__(
        self,
        *,
        model: Any | None = None,
        rng: random.Random | None = None,
        epsilon: float = 0.0,
        recorder: Any | None = None,
        extractor: FeatureExtractor | None = None,
    ) -> None:
        self.model = model or TorchActionValueModel()
        self.rng = rng or random.Random()
        self.epsilon = epsilon
        self.recorder = recorder
        self.extractor = extractor or FeatureExtractor()
        self.use_public_deep_v2_planner = model_uses_public_deep_v2_planner(self.model)
        self.use_public_deep_v2_semantic_bridge = model_uses_public_deep_v2_semantic_bridge(self.model)
        self.public_deep_v2_planner_prior_weight = model_public_deep_v2_planner_prior_weight(self.model)
        self.public_deep_v2_understanding_runtime_weight = (
            model_public_deep_v2_understanding_runtime_weight(self.model)
        )
        self.uses_observed_opponent_features = model_uses_observed_opponent_features(self.model)
        self.scores_observed_opponent_features = model_scores_observed_opponent_features(self.model)

    def choose(self, engine: Any) -> Action:
        self._enable_observed_opponent_features(engine)
        legal = engine.legal_actions()
        if not legal:
            raise RuntimeError("no legal action")
        return self._choose_action(engine, getattr(engine.state, "active", None), legal)

    def choose_flash(self, engine: Any, legal: list[Action]) -> Action:
        self._enable_observed_opponent_features(engine)
        if not legal:
            return Action(kind="flash_pass")
        return self._choose_action(engine, getattr(engine.state, "active", None), legal)

    def choose_blocker(self, engine: Any, attacker: Any, blockers: list[Any]):
        self._enable_observed_opponent_features(engine)
        if not blockers:
            return None
        player = getattr(blockers[0], "owner", getattr(getattr(engine, "state", None), "active", None))
        none_features = self.extractor.state_features(engine, player) | {"block:none": 1.0}
        attacker_dp = self.extractor._effective_dp(engine, attacker)
        if attacker_dp >= float(getattr(player, "life", 0)) > 0:
            none_features["block_none_allows_lethal_player_damage"] = 1.0
        choices: list[tuple[Any, dict[str, float]]] = [(None, none_features)]
        for blocker in blockers:
            choices.append((blocker, self.extractor.features_for_blocker(engine, player, attacker, blocker)))
        return self._choose_scored(choices)

    def choose_attack_target(self, engine: Any, attacker: Any, targets: list[Any]) -> Any:
        self._enable_observed_opponent_features(engine)
        player = getattr(attacker, "owner", getattr(getattr(engine, "state", None), "active", None))
        choices = [(target, self.extractor.features_for_attack_target(engine, player, attacker, target)) for target in targets]
        return self._choose_scored(choices)

    def choose_target(self, engine: Any, kind: str, min_n: int, max_n: int, eligible: list[Any]) -> list[Any]:
        self._enable_observed_opponent_features(engine)
        if not eligible or max_n <= 0:
            return []
        player = target_selection_player_for_context(engine)
        choices = [(target, self.extractor.features_for_generic_target(engine, player, kind, target)) for target in eligible]
        choices = target_choices_after_preinference(choices, min_n=min_n)
        if not choices:
            return []
        scores = self._score_many([features for _, features in choices])
        ordered = sorted(
            zip(choices, scores, strict=True),
            key=lambda item: (
                float(item[1])
                + target_selection_prior(item[0][1])
                + self.public_deep_v2_understanding_runtime_weight
                * self._public_deep_v2_understanding_bonus(item[0][1]),
                self.rng.random(),
            ),
            reverse=True,
        )
        count = max(min_n, min(max_n, len(ordered)))
        selected = ordered[:count]
        for (_, features), _ in selected:
            self._record(features)
        return [target for (target, _), _ in selected]

    def choose_mulligan(self, engine: Any, player: Any) -> list[Any]:
        self._enable_observed_opponent_features(engine)
        choices: list[tuple[Any, dict[str, float]]] = []
        for card_instance in getattr(player, "hand", []):
            card = getattr(card_instance, "card", card_instance)
            features = self.extractor.state_features(engine, player)
            features.update(self.extractor.card_features("mulligan", card))
            features["mulligan_candidate"] = 1.0
            choices.append((card_instance, features))
        if choices:
            scores = self._score_many([features for _, features in choices])
            replacements = [choice for (choice, _), score in zip(choices, scores, strict=True) if score < -0.05]
            for (choice, features), score in zip(choices, scores, strict=True):
                if choice in replacements:
                    self._record(features)
            if replacements:
                return replacements

        hand = list(getattr(player, "hand", []))
        early = [ci for ci in hand if getattr(ci.card, "type", None) is not CardType.B_MINION and _card_cost(ci.card) <= 2]
        bases = [ci for ci in hand if getattr(ci.card, "type", None) is CardType.B_MINION]
        if early and bases:
            return []
        if not bases:
            return [ci for ci in hand if getattr(ci.card, "type", None) is not CardType.B_MINION and _card_cost(ci.card) >= 3]
        if not early:
            return [ci for ci in hand if getattr(ci.card, "type", None) is not CardType.B_MINION and _card_cost(ci.card) >= 4]
        return [ci for ci in hand if getattr(ci.card, "type", None) is not CardType.B_MINION and _card_cost(ci.card) >= 5]

    def _choose_action(self, engine: Any, player: Any, legal: list[Action]) -> Action:
        choices = [(action, self.extractor.features_for_action(engine, player, action)) for action in legal]
        if self.use_public_deep_v2_planner:
            choices = action_choices_after_preinference(choices)
            choices = apply_public_deep_v2_planner_to_action_choices(choices)
            return self._choose_scored(choices, apply_preinference=False)
        return self._choose_scored(choices)

    def _choose_scored(self, choices: list[tuple[Any, dict[str, float]]], *, apply_preinference: bool = True) -> Any:
        if not choices:
            raise RuntimeError("no legal choices")
        if apply_preinference:
            choices = action_choices_after_preinference(choices)
        if self.rng.random() < self.epsilon:
            choice, features = self.rng.choice(choices)
        else:
            scores = self._score_many([features for _, features in choices])
            index = max(
                range(len(choices)),
                key=lambda item: (
                    float(scores[item])
                    + player_correction_score(choices[item][1])
                    + tactical_action_prior(choices[item][1])
                    + card_aware_action_prior(choices[item][1])
                    + opponent_adaptive_action_prior(choices[item][1])
                    + self.public_deep_v2_planner_prior_weight
                    * public_deep_v2_planner_prior(choices[item][1])
                    + self.public_deep_v2_understanding_runtime_weight
                    * self._public_deep_v2_understanding_bonus(choices[item][1]),
                    self.rng.random(),
                ),
            )
            choice, features = choices[index]
        self._record(features)
        return choice

    def _score_many(self, feature_rows: list[dict[str, float]]) -> list[float]:
        return self.model.score_many([
            model_scoring_features(
                features,
                include_observed_opponent_features=self.scores_observed_opponent_features,
                include_public_deep_v2_planner_features=self.use_public_deep_v2_planner,
                include_public_deep_v2_semantic_bridge_features=self.use_public_deep_v2_semantic_bridge,
            )
            for features in feature_rows
        ])

    def _public_deep_v2_understanding_bonus(self, features: dict[str, float]) -> float:
        if self.public_deep_v2_understanding_runtime_weight <= 0.0:
            return 0.0
        if not hasattr(self.model, "understanding_action_bonus"):
            return 0.0
        try:
            return float(self.model.understanding_action_bonus(features))
        except Exception:
            return 0.0

    def _record(self, features: dict[str, float]) -> None:
        if self.recorder is not None:
            self.recorder.record(features)

    def _enable_observed_opponent_features(self, engine: Any) -> None:
        if self.uses_observed_opponent_features:
            setattr(engine, "enable_observed_opponent_features", True)


def train_from_episode_decisions(
    model: TorchActionValueModel,
    decisions: Iterable[Any],
    *,
    final_reward: float,
    gamma: float = 0.97,
    tactical_preference_weight: float = 0.0,
    tactical_preference_margin: float = 0.5,
    lookahead_preference_weight: float = 0.0,
    lookahead_preference_margin: float = 0.5,
    policy_distillation_preference_weight: float = 0.0,
    policy_distillation_preference_margin: float = 0.5,
    public_deep_v2_planner_preference_weight: float = 0.0,
    public_deep_v2_planner_preference_margin: float = 0.5,
    public_deep_v2_planner_prior_weight: float = 0.0,
    train_value_targets: bool = True,
    lookahead_value_target_weight: float = 0.0,
    lookahead_value_target_min_abs_delta: float = 0.01,
    deep_v2_multitask_weight: float = 0.0,
    deep_v2_multitask_epochs: int = 1,
    preserve_action_path_for_deep_v2_multitask: bool = True,
) -> float:
    decision_list = list(decisions)
    rows: list[dict[str, float]] = []
    targets: list[float] = []
    target = final_reward
    for decision in reversed(decision_list):
        target += float(getattr(decision, "step_reward", 0.0))
        rows.append(dict(decision.features))
        targets.append(target)
        target *= gamma
    rows.reverse()
    targets.reverse()
    loss = model.train_batch(rows, targets) if train_value_targets else 0.0
    if lookahead_value_target_weight > 0.0:
        from zz.rl_training import lookahead_value_target_rows

        lookahead_rows, lookahead_targets = lookahead_value_target_rows(
            decision_list,
            min_abs_delta=lookahead_value_target_min_abs_delta,
        )
        if lookahead_rows:
            loss += model.train_batch(
                lookahead_rows,
                lookahead_targets,
                weight=lookahead_value_target_weight,
            )
    if tactical_preference_weight > 0.0:
        from zz.rl_training import tactical_preference_pairs

        pairs = tactical_preference_pairs(decision_list)
        if pairs:
            loss += model.train_preference_pairs(
                pairs,
                margin=tactical_preference_margin,
                weight=tactical_preference_weight,
            )
    if lookahead_preference_weight > 0.0:
        from zz.rl_training import lookahead_preference_pairs

        pairs = lookahead_preference_pairs(decision_list)
        if pairs:
            loss += model.train_preference_pairs(
                pairs,
                margin=lookahead_preference_margin,
                weight=lookahead_preference_weight,
            )
    if policy_distillation_preference_weight > 0.0:
        from zz.rl_training import policy_distillation_preference_pairs

        pairs = policy_distillation_preference_pairs(decision_list)
        if pairs:
            loss += model.train_preference_pairs(
                pairs,
                margin=policy_distillation_preference_margin,
                weight=policy_distillation_preference_weight,
            )
    if public_deep_v2_planner_preference_weight > 0.0:
        from zz.rl_training import public_deep_v2_planner_preference_pairs

        pairs = public_deep_v2_planner_preference_pairs(decision_list)
        if pairs:
            loss += model.train_preference_pairs(
                pairs,
                margin=public_deep_v2_planner_preference_margin,
                weight=public_deep_v2_planner_preference_weight,
            )
    if deep_v2_multitask_weight > 0.0:
        from zz.rl_training import deep_v2_multitask_rows

        multitask = deep_v2_multitask_rows(decision_list, final_reward=final_reward, gamma=gamma)
        result = model.train_multitask_batch(
            action_rows=[],
            action_targets=[],
            state_rows=multitask["stateRows"],
            state_targets=multitask["stateTargets"],
            intent_rows=multitask["intentRows"],
            intent_targets=multitask["intentTargets"],
            plan_rows=multitask["planRows"],
            plan_targets=multitask["planTargets"],
            epochs=deep_v2_multitask_epochs,
            weight=deep_v2_multitask_weight,
            preserve_action_path=preserve_action_path_for_deep_v2_multitask,
        )
        loss += float(result.get("loss", 0.0))
        model.metadata["deepV2MultitaskTraining"] = {
            "version": "deep_v2_multitask_training_v1",
            "weight": float(deep_v2_multitask_weight),
            "epochs": int(deep_v2_multitask_epochs),
            "preserveActionPath": bool(preserve_action_path_for_deep_v2_multitask),
        }
    return loss


def train_preference_pairs_with_optional_learning_rate(
    model: TorchActionValueModel,
    pairs: list[dict[str, Any]],
    *,
    epochs: int,
    margin: float,
    weight: float,
    learning_rate: float | None = None,
    stage: str = "initial",
) -> list[dict[str, Any]]:
    if not pairs or epochs <= 0 or weight <= 0.0:
        return []
    old_learning_rates = [float(group.get("lr", model.learning_rate)) for group in model.optimizer.param_groups]
    if learning_rate is not None:
        for group in model.optimizer.param_groups:
            group["lr"] = float(learning_rate)
    updates: list[dict[str, Any]] = []
    try:
        for epoch in range(max(0, int(epochs))):
            preference_loss = model.train_preference_pairs(
                pairs,
                margin=margin,
                weight=weight,
            )
            updates.append({
                "stage": stage,
                "epoch": epoch + 1,
                "loss": float(preference_loss),
            })
    finally:
        for group, old_learning_rate in zip(model.optimizer.param_groups, old_learning_rates, strict=True):
            group["lr"] = old_learning_rate
    return updates


class _TorchCounterfactualUpdateAdapter:
    def __init__(self, model: TorchActionValueModel) -> None:
        self.model = model
        self.model_updates = 0
        self.update_loss = 0.0

    def score(self, features: dict[str, float]) -> float:
        return self.model.score(features)

    def update(self, features: dict[str, float], *, target: float, alpha: float) -> float:
        before = self.model.score(features)
        weight = max(0.0, min(1.0, float(alpha)))
        blended_target = before + (float(target) - before) * weight
        loss = self.model.train_batch([dict(features)], [blended_target])
        self.model_updates += 1
        self.update_loss += float(loss)
        return float(target) - before


def _run_linear_counterfactual_loss_replay(**kwargs: Any) -> Any:
    from zz.rl_training import run_counterfactual_loss_replay

    return run_counterfactual_loss_replay(**kwargs)


def run_deep_counterfactual_loss_replay(
    *,
    seed: int,
    model: TorchActionValueModel,
    recorder: Any,
    opponent: str,
    config: Any,
    opponent_model_paths: list[str | Path] | None = None,
    learner_side: str = "P1",
    learner_deck: Any | None = None,
    opponent_deck: Any | None = None,
) -> Any:
    adapter = _TorchCounterfactualUpdateAdapter(model)
    result = _run_linear_counterfactual_loss_replay(
        seed=seed,
        model=adapter,
        recorder=recorder,
        opponent=opponent,
        config=config,
        opponent_model_paths=opponent_model_paths,
        learner_side=learner_side,
        learner_deck=learner_deck,
        opponent_deck=opponent_deck,
    )
    result.model_updates = adapter.model_updates
    result.update_loss = adapter.update_loss
    return result


def distill_linear_model_to_torch_model(
    model: TorchActionValueModel,
    teacher: LinearQModel,
    feature_rows: Iterable[dict[str, float]],
    *,
    epochs: int = 5,
    batch_size: int = 256,
    seed: int = 20260523,
) -> dict[str, Any]:
    rows = [dict(row) for row in feature_rows]
    if not rows:
        return {"kind": "linear_to_deep_distillation", "samples": 0, "epochs": 0, "loss": 0.0}

    targets = [teacher.score(row) for row in rows]
    rng = random.Random(seed)
    batch_size = max(1, int(batch_size))
    epochs = max(1, int(epochs))
    initial_error = _mean_absolute_error(model.score_many(rows), targets)
    loss = 0.0
    indexes = list(range(len(rows)))
    for _ in range(epochs):
        rng.shuffle(indexes)
        for start in range(0, len(indexes), batch_size):
            batch_indexes = indexes[start:start + batch_size]
            loss = model.train_batch(
                [rows[index] for index in batch_indexes],
                [targets[index] for index in batch_indexes],
            )
    final_error = _mean_absolute_error(model.score_many(rows), targets)
    return {
        "kind": "linear_to_deep_distillation",
        "samples": len(rows),
        "epochs": epochs,
        "batchSize": batch_size,
        "loss": loss,
        "initialMeanAbsoluteError": initial_error,
        "finalMeanAbsoluteError": final_error,
    }


def collect_player_imitation_rows_from_trace(
    trace: dict[str, Any],
    *,
    player_side: str | None = None,
) -> list[dict[str, float]]:
    """Extract lightweight supervised rows from a recorded human-side trace."""

    side = str(player_side or trace.get("playerSide") or trace.get("player_side") or "P1")
    player_forces = [str(force_id) for force_id in trace.get("playerForces") or trace.get("player_forces") or []]
    opponent_forces = [str(force_id) for force_id in trace.get("opponentForces") or trace.get("opponent_forces") or []]
    rows: list[dict[str, float]] = []
    for event in trace.get("logEvents") or trace.get("log_events") or []:
        if not isinstance(event, dict):
            continue
        if _imitation_event_is_player_block(event, side):
            features = _imitation_block_features(event)
            _add_imitation_force_features(features, "own_force", player_forces)
            _add_imitation_force_features(features, "enemy_force", opponent_forces)
            rows.append(features)
            continue
        if _imitation_event_is_player_attack_target(event, side):
            features = _imitation_attack_target_features(event, side)
            _add_imitation_force_features(features, "own_force", player_forces)
            _add_imitation_force_features(features, "enemy_force", opponent_forces)
            rows.append(features)
            continue
        if _imitation_event_is_player_effect_target(event, side):
            for features in _imitation_effect_target_rows(event, side):
                _add_imitation_force_features(features, "own_force", player_forces)
                _add_imitation_force_features(features, "enemy_force", opponent_forces)
                rows.append(features)
            continue
        if str(event.get("actorSide") or event.get("actor_side") or "") != side:
            continue
        action = event.get("action") if isinstance(event.get("action"), dict) else {}
        kind = str(action.get("kind") or event.get("actionKind") or event.get("action_kind") or "")
        if not kind:
            continue
        features = _imitation_action_features(kind)
        _add_imitation_force_features(features, "own_force", player_forces)
        _add_imitation_force_features(features, "enemy_force", opponent_forces)
        card_payload = _imitation_event_card(event, action)
        if card_payload:
            features.update(_imitation_card_features("play_card", card_payload))
        if kind == "move_card":
            direction = str((action.get("payload") or {}).get("direction") or "")
            features["move_base_to_field"] = 1.0 if direction == "base_to_field" else 0.0
            features["move_field_to_base"] = 1.0 if direction == "field_to_base" else 0.0
        rows.append(features)
    return rows


def collect_stateful_player_preference_pairs_from_trace(
    trace: dict[str, Any],
    *,
    model: Any,
    player_side: str | None = None,
    row: dict[str, Any] | None = None,
    seed: int = 20260528,
    max_alternatives_per_event: int = 1,
    winning_traces_only: bool = True,
    extractor: FeatureExtractor | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build state-aware good-vs-bad pairs from replay snapshots and human actions."""

    side = str(player_side or trace.get("playerSide") or trace.get("player_side") or "P1")
    match_id = str(trace.get("matchId") or trace.get("match_id") or "")
    winner_side = str(trace.get("winnerSide") or trace.get("winner_side") or "")
    if winning_traces_only and winner_side and winner_side != side:
        return [], {
            "matchId": match_id,
            "playerSide": side,
            "winnerSide": winner_side,
            "pairs": 0,
            "skipped": "non_winning_trace",
        }
    if not isinstance(trace.get("stateSnapshots"), list):
        return [], {
            "matchId": match_id,
            "playerSide": side,
            "winnerSide": winner_side,
            "pairs": 0,
            "skipped": "missing_state_snapshots",
        }

    extractor = extractor or FeatureExtractor()
    max_alternatives_per_event = max(1, int(max_alternatives_per_event))
    pairs: list[dict[str, Any]] = []
    considered = 0
    unmatched = 0
    model_already_agreed = 0
    for event_index, event in enumerate(trace.get("logEvents") or trace.get("log_events") or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("type") or "") != "action":
            continue
        if str(event.get("actorSide") or event.get("actor_side") or "") != side:
            continue
        action = event.get("action") if isinstance(event.get("action"), dict) else {}
        kind = str(action.get("kind") or event.get("actionKind") or event.get("action_kind") or "")
        if not kind or kind == "flash_pass":
            continue
        engine = _engine_from_trace_event(row or {}, trace, event, seed=seed + event_index)
        if engine is None:
            unmatched += 1
            continue
        legal = list(engine.legal_actions())
        if len(legal) <= 1:
            continue
        player = getattr(engine.state, "active", None)
        from zz.rl_training import find_replay_action

        logged_action = find_replay_action(engine, player, action or {"kind": kind, "payload": {}}, legal)
        if logged_action is None:
            unmatched += 1
            continue
        raw_choices = [(candidate, extractor.features_for_action(engine, player, candidate)) for candidate in legal]
        choices = action_choices_after_preinference(raw_choices)
        logged_choice = next(((candidate, features) for candidate, features in choices if candidate == logged_action), None)
        if logged_choice is None:
            unmatched += 1
            continue
        considered += 1
        scored = _score_action_feature_choices(model, choices)
        scored.sort(key=lambda item: item[2], reverse=True)
        alternatives = [item for item in scored if item[0] != logged_action]
        if not alternatives:
            continue
        if scored[0][0] == logged_action:
            model_already_agreed += 1
            continue
        for bad_action, bad_features, bad_score in alternatives[:max_alternatives_per_event]:
            good_action, good_features = logged_choice
            pairs.append({
                "goodFeatures": dict(good_features),
                "badFeatures": dict(bad_features),
                "labels": ["stateful_player_replay_preference", f"human_action:{good_action.kind}", f"model_action:{bad_action.kind}"],
                "matchId": match_id,
                "eventIndex": event.get("eventIndex"),
                "snapshotIndex": event.get("snapshotIndex"),
                "goodAction": _action_report(good_action),
                "badAction": _action_report(bad_action),
                "badScore": float(bad_score),
            })
    return pairs, {
        "matchId": match_id,
        "playerSide": side,
        "winnerSide": winner_side,
        "eventsConsidered": considered,
        "unmatchedEvents": unmatched,
        "modelAlreadyAgreedEvents": model_already_agreed,
        "pairs": len(pairs),
    }


def collect_stateful_player_preference_pairs_from_traces(
    trace_paths: Iterable[str | Path],
    *,
    model: Any,
    seed: int = 20260528,
    max_alternatives_per_event: int = 1,
    winning_traces_only: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    for index, raw_path in enumerate(trace_paths):
        path = Path(raw_path)
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            trace_rows.append({"path": str(path), "pairs": 0, "error": str(exc)})
            continue
        if not isinstance(trace, dict):
            trace_rows.append({"path": str(path), "pairs": 0, "error": "trace root is not an object"})
            continue
        trace_pairs, trace_row = collect_stateful_player_preference_pairs_from_trace(
            trace,
            model=model,
            seed=seed + index * 1000,
            max_alternatives_per_event=max_alternatives_per_event,
            winning_traces_only=winning_traces_only,
        )
        pairs.extend(trace_pairs)
        trace_row["path"] = str(path)
        trace_rows.append(trace_row)
    return pairs, trace_rows


def collect_stateful_lookahead_preference_pairs_from_trace(
    trace: dict[str, Any],
    *,
    model: Any,
    player_side: str | None = None,
    row: dict[str, Any] | None = None,
    seed: int = 20260528,
    max_model_actions: int = 6,
    depth: int = 2,
    branch_width: int = 4,
    min_value_gap: float = 1.0,
    focus: str = "all",
    extractor: FeatureExtractor | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build preference pairs when short search overturns the model's top action."""

    side = str(player_side or trace.get("playerSide") or trace.get("player_side") or "P1")
    match_id = str(trace.get("matchId") or trace.get("match_id") or "")
    if not isinstance(trace.get("stateSnapshots"), list):
        return [], {
            "matchId": match_id,
            "playerSide": side,
            "pairs": 0,
            "skipped": "missing_state_snapshots",
        }
    extractor = extractor or FeatureExtractor()
    max_model_actions = max(2, int(max_model_actions))
    depth = max(1, int(depth))
    branch_width = max(1, int(branch_width))
    pairs: list[dict[str, Any]] = []
    considered = 0
    unmatched = 0
    agreed = 0
    for event_index, event in enumerate(trace.get("logEvents") or trace.get("log_events") or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("type") or "") != "action":
            continue
        if str(event.get("actorSide") or event.get("actor_side") or "") != side:
            continue
        engine = _engine_from_trace_event(row or {}, trace, event, seed=seed + event_index)
        if engine is None:
            unmatched += 1
            continue
        try:
            legal = list(engine.legal_actions())
        except Exception:
            unmatched += 1
            continue
        if len(legal) <= 1:
            continue
        player = getattr(engine.state, "active", None)
        raw_choices = [(candidate, extractor.features_for_action(engine, player, candidate)) for candidate in legal]
        choices = action_choices_after_preinference(raw_choices)
        if len(choices) <= 1:
            continue
        considered += 1
        scored = _score_action_feature_choices(model, choices)
        scored.sort(key=lambda item: item[2], reverse=True)
        candidates = scored[:max_model_actions]
        model_top = candidates[0]
        valued: list[tuple[Action, dict[str, float], float, float]] = []
        for action, features, model_score in candidates:
            value = _stateful_lookahead_action_value(
                engine,
                player,
                action,
                model=model,
                extractor=extractor,
                depth=depth,
                branch_width=branch_width,
            )
            valued.append((action, features, model_score, value))
        model_top_valued = valued[0]
        best = max(valued, key=lambda item: item[3])
        if best[0] == model_top[0]:
            agreed += 1
            continue
        value_gap = float(best[3]) - float(model_top_valued[3])
        if value_gap < float(min_value_gap):
            continue
        pair = {
            "goodFeatures": dict(best[1]),
            "badFeatures": dict(model_top[1]),
            "labels": ["statefulLookaheadTeacherPreference"],
            "matchId": match_id,
            "eventIndex": event.get("eventIndex"),
            "snapshotIndex": event.get("snapshotIndex"),
            "goodAction": _action_report(best[0]),
            "badAction": _action_report(model_top[0]),
            "goodModelScore": float(best[2]),
            "badModelScore": float(model_top[2]),
            "goodLookaheadValue": float(best[3]),
            "badLookaheadValue": float(model_top_valued[3]),
            "lookaheadValueGap": value_gap,
        }
        filtered = _filter_stateful_player_preference_pairs([pair], focus=focus)
        if filtered:
            pairs.append(pair)
    return pairs, {
        "matchId": match_id,
        "playerSide": side,
        "eventsConsidered": considered,
        "unmatchedEvents": unmatched,
        "lookaheadAgreedEvents": agreed,
        "pairs": len(pairs),
    }


def collect_stateful_lookahead_preference_pairs_from_traces(
    trace_paths: Iterable[str | Path],
    *,
    model: Any,
    seed: int = 20260528,
    max_model_actions: int = 6,
    depth: int = 2,
    branch_width: int = 4,
    min_value_gap: float = 1.0,
    focus: str = "all",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    for index, raw_path in enumerate(trace_paths):
        path = Path(raw_path)
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            trace_rows.append({"path": str(path), "pairs": 0, "error": str(exc)})
            continue
        if not isinstance(trace, dict):
            trace_rows.append({"path": str(path), "pairs": 0, "error": "trace root is not an object"})
            continue
        trace_pairs, trace_row = collect_stateful_lookahead_preference_pairs_from_trace(
            trace,
            model=model,
            seed=seed + index * 1000,
            max_model_actions=max_model_actions,
            depth=depth,
            branch_width=branch_width,
            min_value_gap=min_value_gap,
            focus=focus,
        )
        pairs.extend(trace_pairs)
        trace_row["path"] = str(path)
        trace_rows.append(trace_row)
    return pairs, trace_rows


def _engine_from_trace_event(
    row: dict[str, Any],
    trace: dict[str, Any],
    event: dict[str, Any],
    seed: int,
) -> Any | None:
    from zz.codeman_replay_correction import _engine_from_event_snapshot

    return _engine_from_event_snapshot(row, trace, event, seed=seed)


def _score_action_feature_choices(
    model: Any,
    choices: list[tuple[Action, dict[str, float]]],
) -> list[tuple[Action, dict[str, float], float]]:
    rows = [
        model_scoring_features(
            features,
            include_public_deep_v2_planner_features=model_uses_public_deep_v2_planner(model),
        )
        for _action, features in choices
    ]
    if hasattr(model, "score_many"):
        raw_scores = list(model.score_many(rows))
    else:
        raw_scores = [float(model.score(row)) for row in rows]
    return [
        (action, features, float(score) + tactical_action_prior(features))
        for (action, features), score in zip(choices, raw_scores, strict=True)
    ]


def _action_report(action: Action) -> dict[str, Any]:
    return {"kind": action.kind, "payload": dict(action.payload)}


def _stateful_lookahead_action_value(
    engine: Any,
    player: Any,
    action: Action,
    *,
    model: Any,
    extractor: FeatureExtractor,
    depth: int,
    branch_width: int,
) -> float:
    try:
        import copy
        from zz.engine import GameOver
        from zz.rl_ai import PositionEvaluator

        players = list(getattr(engine.state, "players", []))
        player_index = players.index(player)
        clone = _stateful_lookahead_clone(engine)
        clone_player = clone.state.players[player_index]
        try:
            clone.apply(copy.deepcopy(action))
        except GameOver as game_over:
            return _stateful_lookahead_game_over_value(game_over, clone_player)
        evaluator = PositionEvaluator()
        return _stateful_lookahead_leaf_value(
            clone,
            player_index,
            remaining_depth=max(0, int(depth) - 1),
            model=model,
            extractor=extractor,
            branch_width=branch_width,
            evaluator=evaluator,
        )
    except Exception:
        return 0.0


def _stateful_lookahead_leaf_value(
    engine: Any,
    player_index: int,
    *,
    remaining_depth: int,
    model: Any,
    extractor: FeatureExtractor,
    branch_width: int,
    evaluator: Any,
) -> float:
    root_player = engine.state.players[player_index]
    if remaining_depth <= 0:
        return float(evaluator.evaluate(engine, root_player))
    try:
        legal = list(engine.legal_actions())
    except Exception:
        return float(evaluator.evaluate(engine, root_player))
    if not legal:
        return float(evaluator.evaluate(engine, root_player))
    active = getattr(engine.state, "active", None)
    choices = [(action, extractor.features_for_action(engine, active, action)) for action in legal]
    choices = action_choices_after_preinference(choices)
    if not choices:
        return float(evaluator.evaluate(engine, root_player))
    scored = sorted(
        _score_action_feature_choices(model, choices),
        key=lambda item: item[2],
        reverse=True,
    )[: max(1, int(branch_width))]
    values: list[float] = []
    for _action, _features, _score in scored:
        clone = _stateful_lookahead_clone(engine)
        clone_player = clone.state.players[player_index]
        try:
            import copy
            from zz.engine import GameOver

            clone.apply(copy.deepcopy(_action))
        except GameOver as game_over:
            values.append(_stateful_lookahead_game_over_value(game_over, clone_player))
            continue
        values.append(_stateful_lookahead_leaf_value(
            clone,
            player_index,
            remaining_depth=remaining_depth - 1,
            model=model,
            extractor=extractor,
            branch_width=branch_width,
            evaluator=evaluator,
        ))
    if not values:
        return float(evaluator.evaluate(engine, root_player))
    return max(values) if active is root_player else min(values)


def _stateful_lookahead_clone(engine: Any) -> Any:
    import copy

    clone = copy.deepcopy(engine)
    if hasattr(clone, "state") and hasattr(clone.state, "engine"):
        clone.state.engine = clone
    if hasattr(clone, "rebind_passive_modifiers"):
        clone.rebind_passive_modifiers()
    return clone


def _stateful_lookahead_game_over_value(game_over: Any, player: Any) -> float:
    winner = getattr(game_over, "winner", None)
    if winner is player:
        return 100.0
    if winner is None:
        return -5.0
    return -100.0


def _filter_stateful_player_preference_pairs(
    pairs: list[dict[str, Any]],
    *,
    focus: str,
) -> list[dict[str, Any]]:
    resolved = str(focus or "all").strip().lower()
    if resolved in {"", "all"}:
        return list(pairs)
    if resolved != "attack_or_base_to_field":
        raise ValueError(f"unknown stateful player preference focus: {focus!r}")
    return [
        pair
        for pair in pairs
        if _stateful_pair_bad_action_kind(pair) == "attack"
        or float(pair.get("badFeatures", {}).get("move_base_to_field") or 0.0) > 0.0
    ]


def side_mirrored_stateful_preference_pairs(pairs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    mirrored: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        good_features = pair.get("goodFeatures")
        bad_features = pair.get("badFeatures")
        if not isinstance(good_features, dict) or not isinstance(bad_features, dict):
            continue
        labels = list(pair.get("labels") or [])
        if "side_mirrored" not in labels:
            labels.append("side_mirrored")
        mirrored_pair = dict(pair)
        mirrored_pair["goodFeatures"] = _drop_seat_identity_feature_keys(good_features)
        mirrored_pair["badFeatures"] = _drop_seat_identity_feature_keys(bad_features)
        mirrored_pair["labels"] = labels
        mirrored_pair["sideMirrored"] = True
        mirrored.append(mirrored_pair)
    return mirrored


def _drop_seat_identity_feature_keys(features: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in features.items()
        if not _is_seat_identity_feature_key(str(key))
    }


def _drop_seat_identity_from_preference_pairs(pairs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        clean_pair = dict(pair)
        for field in ("goodFeatures", "badFeatures"):
            raw_features = clean_pair.get(field)
            if isinstance(raw_features, dict):
                clean_pair[field] = _drop_seat_identity_feature_keys(raw_features)
        sanitized.append(clean_pair)
    return sanitized


def _is_seat_identity_feature_key(key: str) -> bool:
    return (
        key in {"learner_is_p1", "learner_is_p2"}
        or key.startswith("action_by_p1:")
        or key.startswith("action_by_p2:")
    )


def _stateful_preference_pair_labels(pair: dict[str, Any]) -> list[str]:
    labels = [str(label) for label in pair.get("labels", [])]
    good_kind = _stateful_pair_action_kind(pair.get("goodAction"))
    bad_kind = _stateful_pair_action_kind(pair.get("badAction"))
    if good_kind:
        labels.append(f"human_action:{good_kind}")
    if bad_kind:
        labels.append(f"model_action:{bad_kind}")
    return sorted(set(labels))


def _stateful_pair_bad_action_kind(pair: dict[str, Any]) -> str:
    return _stateful_pair_action_kind(pair.get("badAction"))


def _stateful_pair_action_kind(action: Any) -> str:
    if isinstance(action, dict):
        return str(action.get("kind") or "")
    return str(getattr(action, "kind", "") or "")


def collect_player_imitation_rows_from_traces(
    trace_paths: Iterable[str | Path],
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    rows: list[dict[str, float]] = []
    trace_rows: list[dict[str, Any]] = []
    for raw_path in trace_paths:
        path = Path(raw_path)
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            trace_rows.append({"path": str(path), "samples": 0, "error": str(exc)})
            continue
        if not isinstance(trace, dict):
            trace_rows.append({"path": str(path), "samples": 0, "error": "trace root is not an object"})
            continue
        trace_samples = collect_player_imitation_rows_from_trace(trace)
        rows.extend(trace_samples)
        trace_rows.append({
            "path": str(path),
            "matchId": trace.get("matchId") or trace.get("match_id"),
            "playerSide": trace.get("playerSide") or trace.get("player_side"),
            "winnerSide": trace.get("winnerSide") or trace.get("winner_side"),
            "samples": len(trace_samples),
        })
    return rows, trace_rows


def train_torch_model_on_player_imitation_rows(
    model: TorchActionValueModel,
    rows: Iterable[dict[str, float]],
    *,
    epochs: int,
    batch_size: int,
    target: float = 0.85,
    seed: int = 20260525,
) -> dict[str, Any]:
    samples = [dict(row) for row in rows]
    if not samples:
        return {"kind": "player_trace_imitation", "samples": 0, "epochs": 0, "batchSize": 0, "loss": 0.0}
    epochs = max(1, int(epochs))
    batch_size = max(1, int(batch_size))
    rng = random.Random(seed)
    indexes = list(range(len(samples)))
    targets = [float(target) for _ in samples]
    initial_mean_score = float(sum(model.score(row) for row in samples) / max(1, len(samples)))
    loss = 0.0
    for _ in range(epochs):
        rng.shuffle(indexes)
        for start in range(0, len(indexes), batch_size):
            batch_indexes = indexes[start:start + batch_size]
            loss = model.train_batch(
                [samples[index] for index in batch_indexes],
                [targets[index] for index in batch_indexes],
            )
    final_mean_score = float(sum(model.score(row) for row in samples) / max(1, len(samples)))
    return {
        "kind": "player_trace_imitation",
        "samples": len(samples),
        "epochs": epochs,
        "batchSize": batch_size,
        "target": float(target),
        "initialMeanScore": initial_mean_score,
        "finalMeanScore": final_mean_score,
        "loss": float(loss),
    }


def public_deep_v2_teacher_feature_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, float]]:
    feature_rows: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        chosen_plan = row.get("chosenPlan") if isinstance(row.get("chosenPlan"), dict) else {}
        action = row.get("firstAction") if isinstance(row.get("firstAction"), dict) else {}
        features = _public_deep_v2_plan_features(
            row,
            chosen_plan,
            fallback_action=action,
            fallback_intent=str(row.get("intent") or ""),
        )
        if features:
            feature_rows.append(features)
    return feature_rows


def public_deep_v2_teacher_preference_pairs(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        chosen_plan = row.get("chosenPlan") if isinstance(row.get("chosenPlan"), dict) else {}
        first_action = row.get("firstAction") if isinstance(row.get("firstAction"), dict) else {}
        good_features = _public_deep_v2_plan_features(
            row,
            chosen_plan,
            fallback_action=first_action,
            fallback_intent=str(row.get("intent") or ""),
        )
        if not good_features:
            continue
        for rejected in row.get("rejectedPlans") or []:
            if not isinstance(rejected, dict):
                continue
            bad_features = _public_deep_v2_plan_features(row, rejected, selected=False)
            if not bad_features:
                continue
            pairs.append({
                "goodFeatures": good_features,
                "badFeatures": bad_features,
                "labels": ["plannerTeacherPreference", str(row.get("intent") or "")],
            })
    return pairs


def _public_deep_v2_plan_features(
    row: dict[str, Any],
    plan: dict[str, Any],
    *,
    fallback_action: dict[str, Any] | None = None,
    fallback_intent: str = "",
    selected: bool = True,
) -> dict[str, float]:
    actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    action = actions[0] if actions and isinstance(actions[0], dict) else (fallback_action or {})
    kind = str(action.get("kind") or "")
    if not kind:
        return {}
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    intent = str(plan.get("intent") or fallback_intent or row.get("intent") or "")
    deck_id = str(row.get("deckId") or "")
    features = _imitation_action_features(kind)
    features["planner_teacher_sample"] = 1.0
    features["public_deep_v2_planner"] = 1.0
    if selected:
        features["public_deep_v2_planner_selected"] = 1.0
    if intent:
        features[f"planner_intent:{intent}"] = 1.0
    if deck_id:
        features[f"planner_deck_id:{deck_id}"] = 1.0
    is_second_player = row.get("isSecondPlayer")
    if is_second_player is None and row.get("isFirstPlayer") is not None:
        is_second_player = not bool(row.get("isFirstPlayer"))
    if is_second_player is True:
        features["learner_is_second_player"] = 1.0
        features[_imitation_feature_key("action_by_second_player", kind)] = 1.0
    elif is_second_player is False:
        features["learner_is_first_player"] = 1.0
        features[_imitation_feature_key("action_by_first_player", kind)] = 1.0
    if row.get("opponentIsFirstPlayer") is True:
        features["opponent_is_first_player"] = 1.0
    if kind == "move_card":
        direction = str(payload.get("direction") or "")
        if direction:
            features[f"move_{direction}"] = 1.0
    for label in row.get("labels") or []:
        label_key = str(label)
        if label_key:
            features[f"planner_label:{label_key}"] = 1.0
    for state_tag in row.get("stateTags") or row.get("state_tags") or []:
        state_tag_key = str(state_tag)
        if state_tag_key:
            features[_imitation_feature_key("planner_state", state_tag_key)] = 1.0
    deck_profile = row.get("deckProfile") or row.get("deck_profile")
    if isinstance(deck_profile, dict) or hasattr(deck_profile, "to_dict"):
        features.update(FeatureExtractor()._deck_profile_features(
            SimpleNamespace(profile={"deckProfile": deck_profile}),
            prefix="own_deck",
        ))
    for reason in plan.get("reasonTags") or []:
        reason_key = str(reason)
        if reason_key:
            features[f"planner_reason:{reason_key}"] = 1.0
    for risk in plan.get("riskTags") or []:
        risk_key = str(risk)
        if risk_key:
            features[f"planner_risk:{risk_key}"] = 1.0
    return features


def train_torch_model_on_public_deep_v2_teacher_rows(
    model: TorchActionValueModel,
    rows: Iterable[dict[str, Any]],
    *,
    epochs: int,
    batch_size: int,
    target: float = 0.90,
    weight: float = 1.0,
    action_weight: float = 1.0,
    preference_margin: float = 0.5,
    seed: int = 20260529,
) -> dict[str, Any]:
    rows_list = list(rows)
    samples = public_deep_v2_teacher_feature_rows(rows_list)
    preference_pairs = public_deep_v2_teacher_preference_pairs(rows_list)
    if not samples:
        return {
            "kind": "public_deep_v2_teacher_distillation",
            "samples": 0,
            "epochs": 0,
            "batchSize": 0,
            "target": float(target),
            "weight": float(weight),
            "actionWeight": float(action_weight),
            "preferenceMargin": float(preference_margin),
            "preferencePairCount": 0,
            "initialMeanScore": 0.0,
            "finalMeanScore": 0.0,
            "loss": 0.0,
        }
    intent_rows, intent_targets = _public_deep_v2_teacher_intent_targets(rows_list, samples)
    plan_rows, plan_targets = _public_deep_v2_teacher_plan_targets(rows_list, samples)
    model.enable_public_deep_v2_architecture(
        plan_labels=_dedupe_labels((
            *DEFAULT_PLAN_LABELS,
            *[label for labels in plan_targets for label in labels],
        )),
    )
    epochs = max(1, int(epochs))
    batch_size = max(1, int(batch_size))
    rng = random.Random(seed)
    indexes = list(range(len(samples)))
    targets = [float(target) for _ in samples]
    initial_mean_score = float(sum(model.score(row) for row in samples) / max(1, len(samples)))
    loss = 0.0
    multitask_loss = 0.0
    resolved_action_weight = max(0.0, float(action_weight))
    previous_requires_grad = _capture_public_deep_v2_action_path_requires_grad(model)
    if resolved_action_weight <= 0.0:
        _set_public_deep_v2_action_path_trainable(model, False)
    try:
        for _ in range(epochs):
            rng.shuffle(indexes)
            if resolved_action_weight > 0.0:
                for start in range(0, len(indexes), batch_size):
                    batch_indexes = indexes[start:start + batch_size]
                    loss = model.train_batch(
                        [samples[index] for index in batch_indexes],
                        [targets[index] for index in batch_indexes],
                        weight=float(weight) * resolved_action_weight,
                    )
            if intent_rows or plan_rows:
                multitask = model.train_multitask_batch(
                    action_rows=[],
                    action_targets=[],
                    state_rows=[],
                    state_targets=[],
                    intent_rows=intent_rows,
                    intent_targets=intent_targets,
                    plan_rows=plan_rows,
                    plan_targets=plan_targets,
                    epochs=1,
                    weight=float(weight),
                )
                multitask_loss = float(multitask.get("loss", 0.0))
            if preference_pairs and resolved_action_weight > 0.0:
                loss += model.train_preference_pairs(
                    preference_pairs,
                    margin=float(preference_margin),
                    weight=float(weight) * resolved_action_weight,
                )
    finally:
        _restore_public_deep_v2_action_path_requires_grad(model, previous_requires_grad)
    final_mean_score = float(sum(model.score(row) for row in samples) / max(1, len(samples)))
    intent_head_metrics = _public_deep_v2_intent_head_metrics(model, intent_rows, intent_targets)
    plan_head_metrics = _public_deep_v2_plan_head_metrics(model, plan_rows, plan_targets)
    return {
        "kind": "public_deep_v2_teacher_distillation",
        "samples": len(samples),
        "epochs": epochs,
        "batchSize": batch_size,
        "target": float(target),
        "weight": float(weight),
        "actionWeight": resolved_action_weight,
        "preferenceMargin": float(preference_margin),
        "preferencePairCount": len(preference_pairs),
        "architectureVersion": PUBLIC_DEEP_V2_ARCHITECTURE_VERSION,
        "multitaskSamples": {
            "intent": len(intent_rows),
            "plan": len(plan_rows),
        },
        "intentHeadMetrics": intent_head_metrics,
        "planHeadMetrics": plan_head_metrics,
        "initialMeanScore": initial_mean_score,
        "finalMeanScore": final_mean_score,
        "loss": float(loss),
        "multitaskLoss": float(multitask_loss),
    }


def train_torch_model_on_public_deep_v2_value_rows(
    model: TorchActionValueModel,
    rows: Iterable[dict[str, Any]],
    *,
    epochs: int,
    weight: float = 1.0,
) -> dict[str, Any]:
    rows_list = list(rows)
    state_rows, state_targets = _public_deep_v2_value_training_rows(rows_list)
    source_counts = Counter(str(row.get("source") or "unknown") for row in rows_list if isinstance(row, dict))
    report = {
        "kind": "public_deep_v2_value_head",
        "rows": len(rows_list),
        "samples": len(state_rows),
        "epochs": max(0, int(epochs)),
        "weight": float(weight),
        "preserveActionPath": True,
        "sourceCounts": dict(sorted(source_counts.items())),
        "initialMeanStateValue": 0.0,
        "finalMeanStateValue": 0.0,
        "loss": 0.0,
    }
    if not state_rows or int(epochs) <= 0 or float(weight) <= 0.0:
        return report
    model.enable_public_deep_v2_architecture()
    initial_values = model.state_value_many(state_rows)
    training = model.train_multitask_batch(
        action_rows=[],
        action_targets=[],
        state_rows=state_rows,
        state_targets=state_targets,
        intent_rows=[],
        intent_targets=[],
        plan_rows=[],
        plan_targets=[],
        epochs=max(1, int(epochs)),
        weight=float(weight),
        preserve_action_path=True,
    )
    final_values = model.state_value_many(state_rows)
    model.metadata.update({
        "publicDeepV2ValueHeadVersion": MULTITASK_HEAD_VERSION,
        "publicDeepV2ValueRows": len(rows_list),
        "publicDeepV2ValueSamples": len(state_rows),
    })
    report.update({
        "epochs": max(1, int(epochs)),
        "initialMeanStateValue": float(sum(initial_values) / max(1, len(initial_values))),
        "finalMeanStateValue": float(sum(final_values) / max(1, len(final_values))),
        "loss": float(training.get("loss", 0.0)),
        "architectureVersion": PUBLIC_DEEP_V2_ARCHITECTURE_VERSION,
        "headVersion": MULTITASK_HEAD_VERSION,
    })
    return report


def _public_deep_v2_teacher_intent_targets(
    rows: list[dict[str, Any]],
    samples: list[dict[str, float]],
) -> tuple[list[dict[str, float]], list[str]]:
    intent_rows: list[dict[str, float]] = []
    intent_targets: list[str] = []
    for row, features in zip(rows, samples, strict=True):
        intent = str(row.get("intent") or "")
        if not intent:
            continue
        intent_rows.append(_public_deep_v2_auxiliary_feature_row(features))
        intent_targets.append(intent)
    return intent_rows, intent_targets


def _public_deep_v2_intent_head_metrics(
    model: TorchActionValueModel,
    rows: list[dict[str, float]],
    targets: list[str],
) -> dict[str, Any]:
    if not rows or not targets:
        return {"samples": 0, "top1Accuracy": 0.0}
    labels = list(model.intent_labels)
    logits = model.intent_logits_many(rows)
    correct = 0
    evaluated = 0
    for row_logits, target in zip(logits, targets, strict=False):
        if not row_logits or target not in labels:
            continue
        predicted = labels[max(range(len(row_logits)), key=lambda index: row_logits[index])]
        correct += 1 if predicted == target else 0
        evaluated += 1
    return {
        "samples": evaluated,
        "top1Accuracy": correct / max(1, evaluated),
    }


def _public_deep_v2_plan_head_metrics(
    model: TorchActionValueModel,
    rows: list[dict[str, float]],
    targets: list[Iterable[str] | str],
) -> dict[str, Any]:
    if not rows or not targets:
        return {
            "samples": 0,
            "exactMatchRate": 0.0,
            "microPrecision": 0.0,
            "microRecall": 0.0,
        }
    labels = list(model.plan_labels)
    logits = model.plan_logits_many(rows)
    normalized_targets = _normalize_plan_targets(targets)
    true_positive = 0
    predicted_total = 0
    target_total = 0
    exact_matches = 0
    evaluated = 0
    for row_logits, target_labels in zip(logits, normalized_targets, strict=False):
        if not row_logits:
            continue
        predicted = {
            labels[index]
            for index, value in enumerate(row_logits)
            if index < len(labels) and float(value) >= 0.0
        }
        target = {label for label in target_labels if label in labels}
        true_positive += len(predicted & target)
        predicted_total += len(predicted)
        target_total += len(target)
        exact_matches += 1 if predicted == target else 0
        evaluated += 1
    return {
        "samples": evaluated,
        "exactMatchRate": exact_matches / max(1, evaluated),
        "microPrecision": true_positive / max(1, predicted_total),
        "microRecall": true_positive / max(1, target_total),
    }


def _public_deep_v2_teacher_plan_targets(
    rows: list[dict[str, Any]],
    samples: list[dict[str, float]],
) -> tuple[list[dict[str, float]], list[list[str]]]:
    plan_rows: list[dict[str, float]] = []
    plan_targets: list[list[str]] = []
    for row, features in zip(rows, samples, strict=True):
        labels = _teacher_plan_labels(row)
        if not labels:
            continue
        plan_rows.append(_public_deep_v2_auxiliary_feature_row(features))
        plan_targets.append(labels)
    return plan_rows, plan_targets


def _public_deep_v2_auxiliary_feature_row(features: dict[str, float]) -> dict[str, float]:
    return {
        key: value
        for key, value in features.items()
        if not (
            key.startswith("planner_label:")
            or key.startswith("planner_reason:")
            or key.startswith("planner_risk:")
            or key.startswith("planner_intent:")
            or key == "public_deep_v2_planner_selected"
        )
    }


def _teacher_plan_labels(row: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for label in row.get("labels") or []:
        normalized = str(label).strip()
        if normalized and normalized not in labels:
            labels.append(normalized)
    chosen_plan = row.get("chosenPlan") if isinstance(row.get("chosenPlan"), dict) else {}
    for field_name in ("reasonTags", "riskTags"):
        for label in chosen_plan.get(field_name) or []:
            normalized = str(label).strip()
            if normalized and normalized not in labels:
                labels.append(normalized)
    return labels


def _public_deep_v2_understanding_training_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, float]], list[list[str]]]:
    feature_rows: list[dict[str, float]] = []
    targets: list[list[str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        features = row.get("features")
        labels = row.get("targets")
        if not isinstance(features, dict) or not isinstance(labels, list | tuple):
            continue
        normalized_labels = [
            str(label).strip()
            for label in labels
            if str(label).strip()
        ]
        if not normalized_labels:
            continue
        feature_rows.append({
            str(key): float(value)
            for key, value in features.items()
            if isinstance(value, (int, float)) and float(value) != 0.0
        })
        targets.append(normalized_labels)
    return feature_rows, targets


def _public_deep_v2_value_training_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, float]], list[float]]:
    feature_rows: list[dict[str, float]] = []
    targets: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_target = row.get("stateValueTarget", row.get("valueTarget", row.get("target")))
        if not isinstance(raw_target, (int, float)):
            continue
        features: dict[str, float] = {}
        raw_features = row.get("features")
        if isinstance(raw_features, dict):
            features = {
                str(key): float(value)
                for key, value in raw_features.items()
                if isinstance(value, (int, float)) and float(value) != 0.0
            }
        else:
            generated = public_deep_v2_teacher_feature_rows([row])
            if generated:
                features = generated[0]
        if not features:
            continue
        feature_rows.append(_public_deep_v2_auxiliary_feature_row(features))
        targets.append(float(raw_target))
    return feature_rows, targets


def _public_deep_v2_common_row_value(rows: Iterable[dict[str, Any]], key: str) -> str | list[str] | None:
    values = sorted({
        str(row.get(key))
        for row in rows
        if isinstance(row, dict) and row.get(key) not in {None, ""}
    })
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return values


def _public_deep_v2_report_metadata(
    *,
    model: TorchActionValueModel,
    candidate: bool,
    teacher_rows: Iterable[dict[str, Any]],
    understanding_rows: Iterable[dict[str, Any]],
    value_rows: Iterable[dict[str, Any]] = (),
    rerank_pairs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    teacher_rows_list = list(teacher_rows)
    understanding_rows_list = list(understanding_rows)
    value_rows_list = list(value_rows)
    rerank_pairs_list = list(rerank_pairs)
    version_rows = [*teacher_rows_list, *value_rows_list]
    return {
        "candidate": bool(candidate),
        "gatePassed": bool(model.metadata.get("publicDeepV2GatePassed", False)),
        "architectureVersion": model.metadata.get("deepV2ArchitectureVersion"),
        "cardProfileVersion": _public_deep_v2_common_row_value(version_rows, "cardProfileVersion"),
        "deckProfileVersion": _public_deep_v2_common_row_value(version_rows, "deckProfileVersion"),
        "plannerVersion": _public_deep_v2_common_row_value(version_rows, "plannerVersion"),
        "teacherRowCount": len(teacher_rows_list),
        "understandingRowCount": len(understanding_rows_list),
        "valueRowCount": len(value_rows_list),
        "rerankPairCount": len(rerank_pairs_list),
    }


def _capture_public_deep_v2_action_path_requires_grad(
    model: TorchActionValueModel,
) -> list[tuple[nn.Parameter, bool]]:
    modules = [model.deep_v2_encoder, model.deep_v2_action_head]
    return [
        (parameter, bool(parameter.requires_grad))
        for module in modules
        if module is not None
        for parameter in module.parameters()
    ]


def _set_public_deep_v2_action_path_trainable(model: TorchActionValueModel, trainable: bool) -> None:
    for module in (model.deep_v2_encoder, model.deep_v2_action_head):
        if module is None:
            continue
        for parameter in module.parameters():
            parameter.requires_grad = bool(trainable)
    model._rebuild_optimizer()


def _restore_public_deep_v2_action_path_requires_grad(
    model: TorchActionValueModel,
    states: list[tuple[nn.Parameter, bool]],
) -> None:
    for parameter, requires_grad in states:
        parameter.requires_grad = requires_grad
    if states:
        model._rebuild_optimizer()


def _imitation_action_features(kind: str) -> dict[str, float]:
    return {
        "bias": 1.0,
        _imitation_feature_key("action", kind): 1.0,
        "human_imitation_sample": 1.0,
        "is_mana_action": 1.0 if kind in {"play_to_base", "place_colorless_mana", "swap_mana_color", "skip_mana"} else 0.0,
        "is_board_action": 1.0 if kind in {"play_card", "move_card", "activate_flash_ability"} else 0.0,
        "is_attack": 1.0 if kind == "attack" else 0.0,
        "is_end_or_pass": 1.0 if kind in {"end_turn", "flash_pass", "skip_mana"} else 0.0,
    }


def _imitation_event_is_player_block(event: dict[str, Any], player_side: str) -> bool:
    if str(event.get("type") or "") != "block":
        return False
    active_side = str(event.get("activeSide") or event.get("active_side") or "")
    if active_side:
        return active_side != player_side
    blocker = event.get("blocker") if isinstance(event.get("blocker"), dict) else {}
    owner_side = str(blocker.get("ownerSide") or blocker.get("owner_side") or "")
    return bool(owner_side and owner_side == player_side)


def _imitation_event_is_player_attack_target(event: dict[str, Any], player_side: str) -> bool:
    return (
        str(event.get("type") or "") == "attack_target"
        and str(event.get("actorSide") or event.get("actor_side") or "") == player_side
    )


def _imitation_event_is_player_effect_target(event: dict[str, Any], player_side: str) -> bool:
    return (
        str(event.get("type") or "") == "effect_target"
        and str(event.get("actorSide") or event.get("actor_side") or "") == player_side
    )


def _imitation_block_features(event: dict[str, Any]) -> dict[str, float]:
    features = {
        "bias": 1.0,
        "decision:blocker": 1.0,
        "human_imitation_sample": 1.0,
    }
    blocker = event.get("blocker") if isinstance(event.get("blocker"), dict) else {}
    if event.get("blocked") and blocker:
        features.update(_imitation_card_features("blocker", blocker))
    else:
        features["block:none"] = 1.0
    return features


def _imitation_attack_target_features(event: dict[str, Any], player_side: str) -> dict[str, float]:
    features = {
        "bias": 1.0,
        "decision:attack_target": 1.0,
        "human_imitation_sample": 1.0,
    }
    attacker = event.get("attacker") if isinstance(event.get("attacker"), dict) else {}
    if attacker:
        features.update(_imitation_card_features("attacker", attacker))
    target = event.get("target") if isinstance(event.get("target"), dict) else {}
    features.update(_imitation_target_payload_features(target, player_side))
    return features


def _imitation_effect_target_rows(event: dict[str, Any], player_side: str) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    targets = event.get("targets") if isinstance(event.get("targets"), list) else []
    for target in targets:
        if not isinstance(target, dict):
            continue
        features = {
            "bias": 1.0,
            "decision:generic_target": 1.0,
            "human_imitation_sample": 1.0,
        }
        features.update(_imitation_target_payload_features(target, player_side))
        rows.append(features)
    return rows


def _imitation_target_payload_features(target: dict[str, Any], player_side: str) -> dict[str, float]:
    features: dict[str, float] = {}
    target_type = str(target.get("type") or target.get("targetKind") or target.get("target_kind") or "").lower()
    owner_side = str(target.get("ownerSide") or target.get("owner_side") or "")
    if not owner_side and isinstance(target.get("force"), dict):
        owner_side = str(target["force"].get("ownerSide") or target["force"].get("owner_side") or "")
    if not owner_side and target_type == "player":
        owner_side = str(target.get("playerSide") or target.get("player_side") or "")
    if owner_side:
        features["target_own"] = 1.0 if owner_side == player_side else 0.0
        features["target_enemy"] = 0.0 if owner_side == player_side else 1.0
    if "rested" in target:
        rested = bool(target.get("rested"))
        features["target_rested"] = 1.0 if rested else 0.0
        features["target_ready"] = 0.0 if rested else 1.0
    if target_type == "player":
        features["target_player"] = 1.0
        features["target_force"] = 0.0
        features["target_minion"] = 0.0
        features["target_life"] = _imitation_clamp01(_safe_float(target.get("life")) / 10.0)
        return features
    force_payload = target.get("force") if isinstance(target.get("force"), dict) else {}
    if target_type == "force" or force_payload:
        force = force_payload or target
        force_id = force.get("id") or target.get("forceId") or target.get("force_id")
        features["target_player"] = 0.0
        features["target_force"] = 1.0
        features["target_minion"] = 0.0
        if force_id:
            features[_imitation_feature_key("target_force_id", str(force_id))] = 1.0
        if "rested" in force:
            rested = bool(force.get("rested"))
            features["target_rested"] = 1.0 if rested else 0.0
            features["target_ready"] = 0.0 if rested else 1.0
        features["target_life"] = _imitation_clamp01(_safe_float(force.get("life", target.get("life"))) / 10.0)
        return features
    if target.get("cardId") or target.get("card_id"):
        card = dict(target)
        card["cardId"] = str(target.get("cardId") or target.get("card_id"))
        features["target_player"] = 0.0
        features["target_force"] = 0.0
        features["target_minion"] = 1.0 if str(card.get("type") or "").lower() in {"f_minion", "b_minion"} else 0.0
        features.update(_imitation_card_features("target", card))
        features.update(_imitation_target_stat_features(card))
    return features


def _imitation_target_stat_features(payload: dict[str, Any]) -> dict[str, float]:
    bp = _safe_float(payload.get("effectiveBp", payload.get("bp")))
    dp = _safe_float(payload.get("effectiveDp", payload.get("dp")))
    life = _safe_float(payload.get("life"))
    return {
        "target_bp": _imitation_clamp01(bp / 2000.0),
        "target_dp": _imitation_clamp01(dp / 5.0),
        "target_life": _imitation_clamp01(life / 10.0),
    }


def _imitation_event_card(event: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    card = event.get("card") if isinstance(event.get("card"), dict) else {}
    card_id = card.get("cardId") or card.get("id")
    if not card_id:
        signature = action.get("signature") if isinstance(action.get("signature"), dict) else {}
        payload = signature.get("payload") if isinstance(signature.get("payload"), dict) else {}
        for value in payload.values():
            if isinstance(value, dict) and value.get("cardId"):
                card_id = value.get("cardId")
                break
    if not card_id:
        return {}
    merged = dict(card)
    merged["cardId"] = str(card_id)
    return merged


def _imitation_card_features(prefix: str, card: dict[str, Any]) -> dict[str, float]:
    raw_type = str(card.get("type") or "").lower()
    cost = card.get("cost") if isinstance(card.get("cost"), dict) else {}
    total_cost = sum(_safe_float(value) for value in cost.values())
    features = {
        f"{prefix}_cost": _imitation_clamp01(total_cost / 10.0),
        f"{prefix}_is_minion": 1.0 if raw_type in {"f_minion", "b_minion"} else 0.0,
        f"{prefix}_is_magic": 1.0 if raw_type == "magic" else 0.0,
        f"{prefix}_bp": _imitation_clamp01(_safe_float(card.get("bp")) / 2000.0),
        f"{prefix}_dp": _imitation_clamp01(_safe_float(card.get("dp")) / 5.0),
    }
    features[_imitation_feature_key(f"{prefix}_id", str(card["cardId"]))] = 1.0
    for color, amount in cost.items():
        features[_imitation_feature_key(f"{prefix}_cost_color", str(color))] = _imitation_clamp01(_safe_float(amount) / 5.0)
    return features


def _add_imitation_force_features(features: dict[str, float], prefix: str, force_ids: list[str]) -> None:
    ids = sorted(force_id for force_id in force_ids if force_id)
    for force_id in ids:
        features[_imitation_feature_key(f"{prefix}_id", force_id)] = 1.0
    if ids:
        features[_imitation_feature_key(f"{prefix}_combo", "_".join(ids))] = 1.0


def _imitation_feature_key(prefix: str, value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value)).strip("_").lower() or "unknown"
    return f"{prefix}:{token}"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _features_use_public_deep_v2_semantic_bridge(features: dict[str, Any]) -> bool:
    return any("_semantic_" in str(key) or str(key).startswith("semantic_") for key in features)


def _imitation_clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def distill_torch_model_to_torch_model(
    model: TorchActionValueModel,
    teacher: TorchActionValueModel,
    feature_rows: Iterable[dict[str, float]],
    *,
    epochs: int = 5,
    batch_size: int = 256,
    seed: int = 20260523,
) -> dict[str, Any]:
    rows = [dict(row) for row in feature_rows]
    if not rows:
        return {"kind": "torch_to_torch_distillation", "samples": 0, "epochs": 0, "loss": 0.0}

    targets = teacher.score_many(rows)
    rng = random.Random(seed)
    batch_size = max(1, int(batch_size))
    epochs = max(1, int(epochs))
    initial_error = _mean_absolute_error(model.score_many(rows), targets)
    loss = 0.0
    indexes = list(range(len(rows)))
    for _ in range(epochs):
        rng.shuffle(indexes)
        for start in range(0, len(indexes), batch_size):
            batch_indexes = indexes[start:start + batch_size]
            loss = model.train_batch(
                [rows[index] for index in batch_indexes],
                [targets[index] for index in batch_indexes],
            )
    final_error = _mean_absolute_error(model.score_many(rows), targets)
    return {
        "kind": "torch_to_torch_distillation",
        "samples": len(rows),
        "epochs": epochs,
        "batchSize": batch_size,
        "loss": loss,
        "initialMeanAbsoluteError": initial_error,
        "finalMeanAbsoluteError": final_error,
    }


def _mean_absolute_error(predictions: list[float], targets: list[float]) -> float:
    if not targets:
        return 0.0
    return sum(abs(prediction - target) for prediction, target in zip(predictions, targets, strict=True)) / len(targets)


_RESOURCE_DIAGNOSTIC_COUNT_KEYS = {
    "decisionCount",
    "attackCount",
    "nonlethalLowBaseAttackCount",
    "attackWhileLowLifeNoForcesCount",
    "attackExposesLethalNextTurnCount",
    "fieldToBaseMoveCount",
    "fieldToBaseSpendsForceLifeExchangeWallCount",
    "baseToFieldMoveCount",
    "badBaseToFieldManaPullCount",
    "fieldToBaseOpportunityDecisionCount",
    "noReadyColoredManaForHandDecisionCount",
    "endTurnNoReadyColoredManaForHandCount",
    "endTurnWithUnusedMovementAndBaseCandidateCount",
    "harmfulTargetEffectPlayCount",
    "harmfulTargetOnlyOwnPlayCount",
    "harmfulTargetNoEnemyPlayCount",
    "harmfulTargetEnemyAvailablePlayCount",
    "zeroDpAttackCount",
    "zeroDpAttackWithoutPayoffCount",
    "lowDpIntoLargerBlockerAttackCount",
    "largerBlockerSuicideAttackCount",
    "suicideIntoLargerBlockerAttackCount",
    "attackTargetDecisionCount",
    "attackPlayerDamagePreventedByForceCount",
    "blockNoneLosesForceLifeExchangeResourceCount",
    "blockerPreservesForceLifeExchangeResourceCount",
    "attackWithTurnEndMinionRefreshCount",
    "playCardWithTurnEndManaRefreshCount",
    "swapManaColorCount",
    "swapManaFallbackUnsticksHandCount",
    "swapManaEnablesPlayableHandCount",
    "swapManaDelaysBaseGrowthCount",
}


def _add_resource_diagnostics(totals: Counter[str], summary: dict[str, Any]) -> None:
    for key in _RESOURCE_DIAGNOSTIC_COUNT_KEYS:
        totals[key] += int(summary.get(key, 0))


def _resource_diagnostics_from_totals(totals: Counter[str]) -> dict[str, Any]:
    decision_count = max(1, int(totals["decisionCount"]))
    attack_count = max(1, int(totals["attackCount"]))
    field_to_base_opportunities = max(1, int(totals["fieldToBaseOpportunityDecisionCount"]))
    return {
        "decisionCount": int(totals["decisionCount"]),
        "attackCount": int(totals["attackCount"]),
        "nonlethalLowBaseAttackCount": int(totals["nonlethalLowBaseAttackCount"]),
        "nonlethalLowBaseAttackRate": int(totals["nonlethalLowBaseAttackCount"]) / attack_count,
        "attackWhileLowLifeNoForcesCount": int(totals["attackWhileLowLifeNoForcesCount"]),
        "attackExposesLethalNextTurnCount": int(totals["attackExposesLethalNextTurnCount"]),
        "fieldToBaseMoveCount": int(totals["fieldToBaseMoveCount"]),
        "fieldToBaseSpendsForceLifeExchangeWallCount": int(totals["fieldToBaseSpendsForceLifeExchangeWallCount"]),
        "baseToFieldMoveCount": int(totals["baseToFieldMoveCount"]),
        "badBaseToFieldManaPullCount": int(totals["badBaseToFieldManaPullCount"]),
        "fieldToBaseOpportunityDecisionCount": int(totals["fieldToBaseOpportunityDecisionCount"]),
        "fieldToBaseOpportunityUseRate": int(totals["fieldToBaseMoveCount"]) / field_to_base_opportunities,
        "noReadyColoredManaForHandDecisionCount": int(totals["noReadyColoredManaForHandDecisionCount"]),
        "noReadyColoredManaForHandDecisionRate": int(totals["noReadyColoredManaForHandDecisionCount"]) / decision_count,
        "endTurnNoReadyColoredManaForHandCount": int(totals["endTurnNoReadyColoredManaForHandCount"]),
        "endTurnWithUnusedMovementAndBaseCandidateCount": int(totals["endTurnWithUnusedMovementAndBaseCandidateCount"]),
        "harmfulTargetEffectPlayCount": int(totals["harmfulTargetEffectPlayCount"]),
        "harmfulTargetOnlyOwnPlayCount": int(totals["harmfulTargetOnlyOwnPlayCount"]),
        "harmfulTargetNoEnemyPlayCount": int(totals["harmfulTargetNoEnemyPlayCount"]),
        "harmfulTargetEnemyAvailablePlayCount": int(totals["harmfulTargetEnemyAvailablePlayCount"]),
        "zeroDpAttackCount": int(totals["zeroDpAttackCount"]),
        "zeroDpAttackWithoutPayoffCount": int(totals["zeroDpAttackWithoutPayoffCount"]),
        "lowDpIntoLargerBlockerAttackCount": int(totals["lowDpIntoLargerBlockerAttackCount"]),
        "largerBlockerSuicideAttackCount": int(totals["largerBlockerSuicideAttackCount"]),
        "suicideIntoLargerBlockerAttackCount": int(totals["suicideIntoLargerBlockerAttackCount"]),
        "attackTargetDecisionCount": int(totals["attackTargetDecisionCount"]),
        "attackPlayerDamagePreventedByForceCount": int(totals["attackPlayerDamagePreventedByForceCount"]),
        "blockNoneLosesForceLifeExchangeResourceCount": int(totals["blockNoneLosesForceLifeExchangeResourceCount"]),
        "blockerPreservesForceLifeExchangeResourceCount": int(totals["blockerPreservesForceLifeExchangeResourceCount"]),
        "attackWithTurnEndMinionRefreshCount": int(totals["attackWithTurnEndMinionRefreshCount"]),
        "playCardWithTurnEndManaRefreshCount": int(totals["playCardWithTurnEndManaRefreshCount"]),
        "swapManaColorCount": int(totals["swapManaColorCount"]),
        "swapManaFallbackUnsticksHandCount": int(totals["swapManaFallbackUnsticksHandCount"]),
        "swapManaEnablesPlayableHandCount": int(totals["swapManaEnablesPlayableHandCount"]),
        "swapManaDelaysBaseGrowthCount": int(totals["swapManaDelaysBaseGrowthCount"]),
    }


def _decision_feature_rows(decisions: Iterable[Any]) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for decision in decisions:
        rows.append(dict(decision.features))
        for alternative in getattr(decision, "legal_alternatives", []):
            rows.append(dict(alternative["features"]))
    return rows


def _collect_linear_warm_start_rows(
    *,
    teacher: LinearQModel,
    episodes: int,
    seed: int,
    opponent: str,
    learner_side: str,
    epsilon: float,
    deck_pool: list[Any],
    deck_matchups: list[tuple[Any, Any]],
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    from zz.rl_training import _learner_side_for_episode, _training_deck_pair, run_training_episode

    rows: list[dict[str, float]] = []
    episode_rows: list[dict[str, Any]] = []
    for index in range(max(0, int(episodes))):
        learner_deck, opponent_deck = _training_deck_pair(deck_pool, index, deck_matchups=deck_matchups)
        episode_side = _learner_side_for_episode(learner_side, index)
        episode = run_training_episode(
            seed=seed + index,
            model=teacher,
            epsilon=epsilon,
            opponent=opponent,
            learner_side=episode_side,
            learner_deck=learner_deck,
            opponent_deck=opponent_deck,
        )
        episode_rows.append({
            "episode": index + 1,
            "winner": episode.winner,
            "learnerSide": episode.learner_side,
            "learnerDeckId": episode.learner_deck_id,
            "opponentDeckId": episode.opponent_deck_id,
            "decisions": len(episode.recorder.decisions),
            "featureRows": sum(1 + len(decision.legal_alternatives) for decision in episode.recorder.decisions),
            "error": episode.error,
        })
        rows.extend(_decision_feature_rows(episode.recorder.decisions))
    return rows, episode_rows


def _collect_deep_anchor_rows(
    *,
    teacher: TorchActionValueModel,
    episodes: int,
    seed: int,
    opponent: str,
    opponent_model_paths: list[str | Path],
    learner_side: str,
    epsilon: float,
    deck_pool: list[Any],
    deck_matchups: list[tuple[Any, Any]],
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    from zz.rl_training import _learner_side_for_episode, _training_deck_pair, run_training_episode

    rows: list[dict[str, float]] = []
    episode_rows: list[dict[str, Any]] = []
    for index in range(max(0, int(episodes))):
        learner_deck, opponent_deck = _training_deck_pair(deck_pool, index, deck_matchups=deck_matchups)
        episode_side = _learner_side_for_episode(learner_side, index)
        episode = run_training_episode(
            seed=seed + index,
            model=teacher,
            epsilon=epsilon,
            opponent=opponent,
            opponent_model_paths=opponent_model_paths,
            learner_side=episode_side,
            learner_deck=learner_deck,
            opponent_deck=opponent_deck,
        )
        episode_rows.append({
            "episode": index + 1,
            "winner": episode.winner,
            "learnerSide": episode.learner_side,
            "opponent": episode.opponent,
            "learnerDeckId": episode.learner_deck_id,
            "opponentDeckId": episode.opponent_deck_id,
            "decisions": len(episode.recorder.decisions),
            "featureRows": sum(1 + len(decision.legal_alternatives) for decision in episode.recorder.decisions),
            "error": episode.error,
        })
        rows.extend(_decision_feature_rows(episode.recorder.decisions))
    return rows, episode_rows


def _collect_deep_rollout_batch(jobs: Iterable[dict[str, Any]], *, max_workers: int) -> list[Any]:
    job_list = list(jobs)
    if not job_list:
        return []
    worker_count = max(1, int(max_workers))
    if worker_count <= 1 or len(job_list) <= 1:
        return [_run_deep_rollout_job(job) for job in job_list]
    with ProcessPoolExecutor(max_workers=min(worker_count, len(job_list))) as pool:
        return list(pool.map(_run_deep_rollout_job, job_list))


def _run_deep_rollout_job(job: dict[str, Any]) -> Any:
    from zz.rl_training import run_training_episode

    model = TorchActionValueModel.load(job["model_path"], device=job.get("actor_device", "cpu"))
    return run_training_episode(
        seed=int(job["seed"]),
        model=model,
        epsilon=float(job["epsilon"]),
        opponent=str(job["opponent"]),
        opponent_model_paths=list(job.get("opponent_model_paths") or []),
        learner_side=str(job["learner_side"]),
        learner_deck=job.get("learner_deck"),
        opponent_deck=job.get("opponent_deck"),
        training_lookahead_weight=float(job.get("training_lookahead_weight", 0.0)),
        training_max_lookahead_actions=int(job.get("training_max_lookahead_actions", 0)),
        training_beam_lookahead_width=int(job.get("training_beam_lookahead_width", 0)),
        training_beam_lookahead_depth=int(job.get("training_beam_lookahead_depth", 1)),
        training_beam_lookahead_key_decisions_only=bool(
            job.get("training_beam_lookahead_key_decisions_only", True)
        ),
        capture_decision_snapshots=bool(job.get("capture_decision_snapshots", False)),
    )


def _normalise_opponent_schedule(opponent_schedule: Iterable[str] | None) -> list[str]:
    return [str(item).strip() for item in (opponent_schedule or []) if str(item).strip()]


def _opponent_for_episode(default_opponent: str, opponent_schedule: list[str], index: int) -> str:
    if not opponent_schedule:
        return default_opponent
    return opponent_schedule[index % len(opponent_schedule)]


def _normalise_player_gate_opponent_kinds(
    player_gate_eval_opponent_kind: str,
    player_gate_eval_opponent_kinds: Iterable[str] | None,
) -> list[str]:
    kinds = [str(item).strip() for item in (player_gate_eval_opponent_kinds or []) if str(item).strip()]
    return kinds or [str(player_gate_eval_opponent_kind)]


def _safe_player_gate_opponent_kind(kind: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(kind).strip())
    return safe or "opponent"


def _player_gate_composite_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_count = sum(int(row.get("rowCount", 0)) for row in rows)
    zero_count = sum(int(row.get("zeroRowCount", 0)) for row in rows)
    timeout_count = sum(int(row.get("timeoutCount", 0)) for row in rows)
    error_count = sum(int(row.get("errorCount", 0)) for row in rows)
    average = sum(float(row.get("averageWinRate", 0.0)) for row in rows) / max(1, len(rows))
    floor = min((float(row.get("minimumPlayerDeckWinRate", 0.0)) for row in rows), default=0.0)
    zero_ratio = zero_count / max(1, row_count)
    failure_ratio = (timeout_count + error_count) / max(1, row_count)
    composite_score = (0.45 * average) + (0.45 * floor) - (0.10 * zero_ratio) - (0.25 * failure_ratio)
    return {
        "opponentKinds": [str(row.get("opponentKind", "")) for row in rows],
        "reportPaths": [str(row.get("reportPath", "")) for row in rows],
        "averageWinRate": average,
        "minimumPlayerDeckWinRate": floor,
        "zeroRowCount": zero_count,
        "timeoutCount": timeout_count,
        "errorCount": error_count,
        "rowCount": row_count,
        "zeroRowRatio": zero_ratio,
        "failureRatio": failure_ratio,
        "compositeScore": composite_score,
    }


def run_deep_evaluation(
    *,
    model_path: str | Path,
    episodes: int,
    seed: int = 20260523,
    opponent: str = "greedy",
    learner_side: str = "P1",
    device: str | torch.device | None = "auto",
    learner_recipe: dict[str, int] | None = None,
    learner_forces: list[str] | None = None,
    opponent_recipe: dict[str, int] | None = None,
    opponent_forces: list[str] | None = None,
) -> dict[str, Any]:
    from zz.rl_training import _normalise_learner_side, _play_one_game_with_policy

    learner_side = _normalise_learner_side(learner_side)
    model = TorchActionValueModel.load(model_path, device=device)
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    rows: list[dict[str, Any]] = []
    turns_total = 0
    for index in range(episodes):
        learner_policy = TorchMaskedPolicy(model=model, rng=random.Random(seed + index + 17))
        opponent_policy = RandomLegalPolicy(random.Random(seed + index + 23)) if opponent == "random" else GreedyLegalPolicy(random.Random(seed + index + 23))
        p1_policy = learner_policy if learner_side == "P1" else opponent_policy
        p2_policy = learner_policy if learner_side == "P2" else opponent_policy
        p1_recipe = learner_recipe if learner_side == "P1" else opponent_recipe
        p2_recipe = learner_recipe if learner_side == "P2" else opponent_recipe
        p1_forces = learner_forces if learner_side == "P1" else opponent_forces
        p2_forces = learner_forces if learner_side == "P2" else opponent_forces
        try:
            winner, turns = _play_one_game_with_policy(
                seed + index,
                p1_policy=p1_policy,
                p2_policy=p2_policy,
                p1_recipe=p1_recipe,
                p2_recipe=p2_recipe,
                p1_forces=p1_forces,
                p2_forces=p2_forces,
            )
            results["played"] += 1
            results[winner] = results.get(winner, 0) + 1
            turns_total += turns
            rows.append({"game": index + 1, "winner": winner, "turns": turns})
        except Exception as exc:  # pragma: no cover - long-run diagnostics
            results["errors"] += 1
            rows.append({"game": index + 1, "winner": "error", "error": str(exc)})
    played = max(1, results["played"])
    wins = results[learner_side]
    return {
        "kind": "deep_rl_evaluation",
        "createdAt": _utc_now(),
        "modelPath": str(model_path),
        "device": str(model.device),
        "opponent": opponent,
        "learnerSide": learner_side,
        "games": episodes,
        "results": results,
        "winRate": wins / played,
        "averageTurns": turns_total / played,
        "decks": {
            "learner": {"recipe": dict(learner_recipe or {}), "forces": list(learner_forces or [])},
            "opponent": {"recipe": dict(opponent_recipe or {}), "forces": list(opponent_forces or [])},
        },
        "rowCount": len(rows),
        "rows": _compact_rows(rows),
    }


def run_deep_deck_matrix_evaluation(
    *,
    model_path: str | Path,
    learner_decks: list[Any],
    opponent_decks: list[Any] | None = None,
    episodes: int,
    seed: int = 20260523,
    seed_count: int = 1,
    opponent: str = "greedy",
    learner_sides: tuple[str, ...] | list[str] = ("P1", "P2"),
    device: str | torch.device | None = "auto",
    report_out: str | Path | None = None,
) -> dict[str, Any]:
    from zz.rl_training import _deck_forces, _deck_id, _deck_name, _deck_recipe, _normalise_learner_side, _side_seed_offset

    opponent_decks = learner_decks if opponent_decks is None else opponent_decks
    seed_count = max(1, int(seed_count))
    sides = [_normalise_learner_side(side) for side in learner_sides]
    rows: list[dict[str, Any]] = []
    for learner_index, learner_deck in enumerate(learner_decks):
        for opponent_index, opponent_deck in enumerate(opponent_decks):
            for side in sides:
                seed_runs: list[dict[str, Any]] = []
                results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
                turns_total = 0.0
                completed_total = 0
                for seed_index in range(seed_count):
                    run_seed = seed + learner_index * 10_000 + opponent_index * 1_000 + _side_seed_offset(side) + seed_index * 1009
                    report = run_deep_evaluation(
                        model_path=model_path,
                        episodes=episodes,
                        seed=run_seed,
                        opponent=opponent,
                        learner_side=side,
                        device=device,
                        learner_recipe=_deck_recipe(learner_deck),
                        learner_forces=_deck_forces(learner_deck),
                        opponent_recipe=_deck_recipe(opponent_deck),
                        opponent_forces=_deck_forces(opponent_deck),
                    )
                    row_results = dict(report["results"])
                    completed = max(1, row_results["P1"] + row_results["P2"] + row_results["tie"])
                    completed_total += completed
                    turns_total += report["averageTurns"] * completed
                    for key, value in row_results.items():
                        results[key] = results.get(key, 0) + int(value)
                    seed_runs.append({
                        "seed": run_seed,
                        "winRate": report["winRate"],
                        "results": row_results,
                        "averageTurns": report["averageTurns"],
                    })
                win_rates = [run["winRate"] for run in seed_runs]
                rows.append({
                    "learnerDeckId": _deck_id(learner_deck),
                    "learnerDeckName": _deck_name(learner_deck),
                    "opponentDeckId": _deck_id(opponent_deck),
                    "opponentDeckName": _deck_name(opponent_deck),
                    "opponent": opponent,
                    "learnerSide": side,
                    "episodesPerSeed": episodes,
                    "seed": seed + learner_index * 10_000 + opponent_index * 1_000 + _side_seed_offset(side),
                    "seedCount": seed_count,
                    "winRate": results[side] / max(1, completed_total),
                    "meanWinRate": sum(win_rates) / max(1, len(win_rates)),
                    "minWinRate": min(win_rates, default=0.0),
                    "maxWinRate": max(win_rates, default=0.0),
                    "results": results,
                    "averageTurns": turns_total / max(1, completed_total),
                    "seedRuns": seed_runs,
                })
    report = {
        "schemaVersion": 1,
        "kind": "deep_rl_deck_matrix_evaluation",
        "createdAt": _utc_now(),
        "modelPath": str(model_path),
        "device": str(_resolve_torch_device(device)),
        "opponent": opponent,
        "episodesPerSeed": episodes,
        "seed": seed,
        "seedCount": seed_count,
        "learnerDecks": len(learner_decks),
        "opponentDecks": len(opponent_decks),
        "learnerSides": sides,
        "averageWinRate": sum(row["winRate"] for row in rows) / max(1, len(rows)),
        "minimumSeedWinRate": min((row["minWinRate"] for row in rows), default=0.0),
        "rowCount": len(rows),
        "rows": rows,
    }
    if report_out is not None:
        Path(report_out).write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report


def run_deep_training(
    *,
    episodes: int,
    seed: int,
    out_dir: str | Path,
    eval_interval: int = 50,
    eval_episodes: int = 20,
    opponent: str = "greedy",
    opponent_model_paths: list[str | Path] | None = None,
    opponent_schedule: list[str] | tuple[str, ...] | None = None,
    learner_side: str = "alternate",
    device: str | torch.device | None = "auto",
    require_cuda: bool = False,
    train_scope: str = "all",
    vector_size: int = 512,
    hidden_size: int = 128,
    learning_rate: float = 0.0003,
    gamma: float = 0.97,
    epsilon_start: float = 0.25,
    epsilon_end: float = 0.05,
    training_lookahead_weight: float = DEEP_LOOKAHEAD_WEIGHT,
    training_max_lookahead_actions: int = DEEP_MAX_LOOKAHEAD_ACTIONS,
    training_beam_lookahead_width: int = 0,
    training_beam_lookahead_depth: int = 1,
    training_beam_lookahead_key_decisions_only: bool = True,
    tactical_preference_weight: float = 0.0,
    tactical_preference_margin: float = 0.5,
    lookahead_preference_weight: float = 0.0,
    lookahead_preference_margin: float = 0.5,
    policy_distillation_preference_weight: float = 0.0,
    policy_distillation_preference_margin: float = 0.5,
    public_deep_v2_planner_preference_weight: float = 0.0,
    public_deep_v2_planner_preference_margin: float = 0.5,
    public_deep_v2_planner_prior_weight: float = 0.0,
    train_value_targets: bool = True,
    lookahead_value_target_weight: float = 0.0,
    lookahead_value_target_min_abs_delta: float = 0.01,
    deep_v2_multitask_weight: float = 0.0,
    deep_v2_multitask_epochs: int = 1,
    public_policy_preference_weight: float = 0.0,
    public_policy_preference_margin: float = 0.5,
    public_policy_preference_epochs: int = 0,
    public_policy_preference_learning_rate: float | None = None,
    public_deep_v2_teacher_rows: list[dict[str, Any]] | None = None,
    public_deep_v2_teacher_epochs: int = 0,
    public_deep_v2_teacher_weight: float = 0.0,
    public_deep_v2_teacher_action_weight: float = 1.0,
    public_deep_v2_teacher_preference_margin: float = 0.5,
    public_deep_v2_value_rows: list[dict[str, Any]] | None = None,
    public_deep_v2_value_epochs: int = 0,
    public_deep_v2_value_weight: float = 0.0,
    public_deep_v2_value_runtime_enabled: bool = False,
    public_deep_v2_rerank_pairs: list[dict[str, Any]] | None = None,
    public_deep_v2_rerank_epochs: int = 0,
    public_deep_v2_rerank_weight: float = 0.0,
    public_deep_v2_rerank_margin: float = 0.5,
    public_deep_v2_rerank_runtime_enabled: bool = False,
    public_deep_v2_rerank_runtime_weight: float = 0.1,
    public_deep_v2_understanding_rows: list[dict[str, Any]] | None = None,
    public_deep_v2_understanding_epochs: int = 0,
    public_deep_v2_understanding_weight: float = 0.0,
    public_deep_v2_understanding_preference_weight: float = 0.0,
    public_deep_v2_understanding_preference_margin: float = 0.5,
    public_deep_v2_understanding_preference_epochs: int = 0,
    public_deep_v2_understanding_preference_learning_rate: float | None = None,
    public_deep_v2_understanding_runtime_weight: float = 0.0,
    opponent_behavior_preference_weight: float = 0.0,
    opponent_behavior_preference_margin: float = 0.5,
    opponent_behavior_preference_epochs: int = 0,
    opponent_behavior_preference_learning_rate: float | None = None,
    opponent_behavior_preference_reapply_after_anchor: bool = True,
    update_losing_episodes: bool = True,
    update_winning_episodes: bool = True,
    loss_replay_decisions: int = 0,
    loss_replay_alternatives: int = 0,
    loss_replay_max_branches: int = 0,
    loss_replay_alpha: float = 1.0,
    loss_replay_reward_resource_repairs: bool = True,
    loss_replay_reward_resource_repair_survival_improvements: bool = True,
    loss_replay_winning_update_repeats: int = 1,
    loss_replay_branch_max_turns: int = 30,
    loss_replay_branch_max_actions: int = 160,
    loss_replay_max_runtime_seconds: float = 0.0,
    loss_replay_stop_after_improved_branch: bool = False,
    loss_replay_max_snapshots_per_episode: int = 12,
    initial_model_path: str | Path | None = None,
    linear_warm_start_model_path: str | Path | None = None,
    linear_warm_start_episodes: int = 0,
    linear_warm_start_epochs: int = 5,
    linear_warm_start_batch_size: int = 256,
    linear_warm_start_epsilon: float = 0.0,
    deep_anchor_model_path: str | Path | None = None,
    deep_anchor_episodes: int = 0,
    deep_anchor_epochs: int = 1,
    deep_anchor_batch_size: int = 256,
    deep_anchor_interval: int = 20,
    deep_anchor_epsilon: float = 0.0,
    deep_anchor_opponent: str | None = None,
    imitation_trace_paths: list[str | Path] | None = None,
    imitation_epochs: int = 0,
    imitation_batch_size: int = 256,
    imitation_target: float = 0.85,
    public_deep_v2_teacher_batch_size: int = 256,
    public_deep_v2_teacher_target: float = 0.90,
    stateful_player_preference_weight: float = 0.0,
    stateful_player_preference_margin: float = 0.5,
    stateful_player_preference_epochs: int = 0,
    stateful_player_preference_learning_rate: float | None = None,
    stateful_player_preference_max_alternatives: int = 1,
    stateful_player_preference_winning_traces_only: bool = True,
    stateful_player_preference_focus: str = "all",
    stateful_player_preference_side_mirror: bool = False,
    stateful_lookahead_preference_weight: float = 0.0,
    stateful_lookahead_preference_margin: float = 0.5,
    stateful_lookahead_preference_epochs: int = 0,
    stateful_lookahead_preference_learning_rate: float | None = None,
    stateful_lookahead_preference_max_model_actions: int = 6,
    stateful_lookahead_preference_depth: int = 2,
    stateful_lookahead_preference_branch_width: int = 4,
    stateful_lookahead_preference_min_value_gap: float = 1.0,
    stateful_lookahead_preference_focus: str = "all",
    stateful_lookahead_preference_side_mirror: bool = False,
    deck_pool: list[Any] | None = None,
    deck_matchups: list[Any] | None = None,
    deck_matrix_eval_episodes: int = 0,
    deck_matrix_seed_count: int = 1,
    player_gate_eval_episodes: int = 0,
    player_gate_eval_player_decks: list[Any] | None = None,
    player_gate_eval_old_top10_decks: list[Any] | None = None,
    player_gate_eval_deck_root: str | Path | None = None,
    player_gate_eval_top_suite_path: str | Path = "data/ai_training/top_deck_suite_v2_latest.json",
    player_gate_eval_max_player_decks: int | None = None,
    player_gate_eval_max_old_top10_decks: int | None = None,
    player_gate_eval_model_side: str = "random",
    player_gate_eval_pass_threshold: float = 0.70,
    player_gate_eval_opponent_kind: str = "normal",
    player_gate_eval_opponent_kinds: list[str] | tuple[str, ...] | None = None,
    player_gate_eval_normal_model_path: str | Path | None = None,
    player_gate_eval_deep_model_path: str | Path | None = None,
    player_gate_eval_data_root: str | Path | None = None,
    player_gate_eval_max_turns: int = 30,
    player_gate_eval_max_actions: int = 500,
    rollout_workers: int = 1,
    rollout_batch_size: int | None = None,
    rollout_actor_device: str | torch.device | None = "cpu",
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    from zz.rl_training import (
        CounterfactualReplayConfig,
        _deck_id_or_empty,
        _deck_name_or_empty,
        _fixed_eval_sides_for_mode,
        _learner_side_for_episode,
        _dedupe_existing_paths,
        _linear_decay,
        _memory_correction_from_replay_result,
        _memory_match_id_from_deck_id,
        _normalise_deck_matchups,
        _reward_for_learner,
        _training_deck_pair,
        _validate_learner_side_mode,
        run_training_episode,
        summarize_decision_resource_diagnostics,
        summarize_decision_tactical_labels,
        deep_v2_multitask_rows,
        lookahead_preference_pairs,
        lookahead_value_target_rows,
        policy_distillation_preference_pairs,
        opponent_behavior_preference_pairs,
        OPPONENT_BEHAVIOR_PREFERENCE_VERSION,
        public_policy_preference_pairs,
        PUBLIC_POLICY_PREFERENCE_VERSION,
        public_deep_v2_planner_preference_pairs,
        tactical_preference_pairs,
        TACTICAL_LABEL_COUNT_KEYS,
    )

    _validate_learner_side_mode(learner_side)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    deck_pool = list(deck_pool or [])
    deck_matchups = _normalise_deck_matchups(deck_matchups or [])
    opponent_model_paths = _dedupe_existing_paths(opponent_model_paths or [])
    opponent_schedule = _normalise_opponent_schedule(opponent_schedule)
    player_gate_eval_opponent_kinds = _normalise_player_gate_opponent_kinds(
        player_gate_eval_opponent_kind,
        player_gate_eval_opponent_kinds,
    )
    deck_matrix_eval_episodes = max(0, int(deck_matrix_eval_episodes))
    deck_matrix_seed_count = max(1, int(deck_matrix_seed_count))
    player_gate_eval_episodes = max(0, int(player_gate_eval_episodes))
    rollout_workers = max(1, int(rollout_workers))
    rollout_batch_size = max(1, int(rollout_batch_size or rollout_workers))
    rollout_actor_device = "cpu" if rollout_actor_device is None else rollout_actor_device
    train_scope = str(train_scope or "all").strip().lower()
    if train_scope not in {"all", "head"}:
        raise ValueError(f"unknown torch train scope: {train_scope!r}")
    training_beam_lookahead_width = max(0, int(training_beam_lookahead_width))
    training_beam_lookahead_depth = max(1, int(training_beam_lookahead_depth))
    training_beam_lookahead_key_decisions_only = bool(training_beam_lookahead_key_decisions_only)
    loss_replay_decisions = max(0, int(loss_replay_decisions))
    loss_replay_alternatives = max(0, int(loss_replay_alternatives))
    loss_replay_max_branches = max(0, int(loss_replay_max_branches))
    loss_replay_config = CounterfactualReplayConfig(
        max_decisions=loss_replay_decisions,
        max_alternatives=loss_replay_alternatives,
        max_branches=loss_replay_max_branches,
        alpha=float(loss_replay_alpha),
        reward_resource_repair_branches=bool(loss_replay_reward_resource_repairs),
        reward_resource_repair_survival_improvements=bool(
            loss_replay_reward_resource_repair_survival_improvements
        ),
        winning_update_repeats=max(1, int(loss_replay_winning_update_repeats)),
        branch_max_turns=max(1, int(loss_replay_branch_max_turns)),
        branch_max_actions=max(1, int(loss_replay_branch_max_actions)),
        max_runtime_seconds=max(0.0, float(loss_replay_max_runtime_seconds)),
        stop_after_improved_branch=bool(loss_replay_stop_after_improved_branch),
    )
    resolved_device = _resolve_torch_device(device, require_cuda=require_cuda)
    torch_environment = _torch_environment_metadata(resolved_device)
    public_deep_v2_teacher_rows = list(public_deep_v2_teacher_rows or [])
    public_deep_v2_teacher_epochs = max(0, int(public_deep_v2_teacher_epochs))
    public_deep_v2_value_rows = list(public_deep_v2_value_rows or [])
    public_deep_v2_value_epochs = max(0, int(public_deep_v2_value_epochs))
    public_deep_v2_rerank_pairs = list(public_deep_v2_rerank_pairs or [])
    public_deep_v2_rerank_epochs = max(0, int(public_deep_v2_rerank_epochs))
    public_deep_v2_understanding_rows = list(public_deep_v2_understanding_rows or [])
    public_deep_v2_understanding_epochs = max(0, int(public_deep_v2_understanding_epochs))
    public_deep_v2_understanding_runtime_weight = max(0.0, float(public_deep_v2_understanding_runtime_weight))
    public_deep_v2_understanding_preference_epochs = max(
        0,
        int(public_deep_v2_understanding_preference_epochs),
    )
    if public_deep_v2_understanding_rows:
        from zz.deep_v2_understanding import (
            UNDERSTANDING_PREFERENCE_VERSION,
            understanding_preference_pairs,
        )

        public_deep_v2_understanding_preference_pairs = understanding_preference_pairs(
            public_deep_v2_understanding_rows
        )
    else:
        UNDERSTANDING_PREFERENCE_VERSION = "public_deep_v2_understanding_preference_v1"
        public_deep_v2_understanding_preference_pairs = []
    public_deep_v2_understanding_preference_label_counts: Counter[str] = Counter()
    for pair in public_deep_v2_understanding_preference_pairs:
        for label in pair.get("labels", []):
            public_deep_v2_understanding_preference_label_counts[str(label)] += 1
    public_deep_v2_understanding_preference_uses_semantic_bridge = any(
        _features_use_public_deep_v2_semantic_bridge(pair.get(side) or {})
        for pair in public_deep_v2_understanding_preference_pairs
        for side in ("goodFeatures", "badFeatures")
    )
    public_deep_v2_training = {
        "kind": "public_deep_v2_teacher_distillation",
        "samples": len(public_deep_v2_teacher_rows),
        "epochs": public_deep_v2_teacher_epochs,
        "weight": float(public_deep_v2_teacher_weight),
        "actionWeight": float(public_deep_v2_teacher_action_weight),
        "preferenceMargin": float(public_deep_v2_teacher_preference_margin),
        "enabled": bool(public_deep_v2_teacher_rows) and public_deep_v2_teacher_epochs > 0,
    }
    public_deep_v2_value_training = {
        "kind": "public_deep_v2_value_head",
        "rows": len(public_deep_v2_value_rows),
        "samples": 0,
        "epochs": public_deep_v2_value_epochs,
        "weight": float(public_deep_v2_value_weight),
        "preserveActionPath": True,
        "runtimeEnabled": bool(public_deep_v2_value_runtime_enabled),
        "enabled": (
            bool(public_deep_v2_value_rows)
            and public_deep_v2_value_epochs > 0
            and float(public_deep_v2_value_weight) > 0.0
        ),
    }
    public_deep_v2_rerank_training = {
        "kind": "public_deep_v2_rerank_head",
        "pairCount": len(public_deep_v2_rerank_pairs),
        "epochs": public_deep_v2_rerank_epochs,
        "weight": float(public_deep_v2_rerank_weight),
        "margin": float(public_deep_v2_rerank_margin),
        "runtimeEnabled": bool(public_deep_v2_rerank_runtime_enabled),
        "runtimeWeight": float(public_deep_v2_rerank_runtime_weight),
        "preserveActionPath": True,
        "enabled": (
            bool(public_deep_v2_rerank_pairs)
            and public_deep_v2_rerank_epochs > 0
            and float(public_deep_v2_rerank_weight) > 0.0
        ),
    }
    public_deep_v2_understanding_training = {
        "kind": "public_deep_v2_understanding_head",
        "rows": len(public_deep_v2_understanding_rows),
        "samples": 0,
        "epochs": public_deep_v2_understanding_epochs,
        "weight": float(public_deep_v2_understanding_weight),
        "runtimeWeight": float(public_deep_v2_understanding_runtime_weight),
        "enabled": (
            bool(public_deep_v2_understanding_rows)
            and public_deep_v2_understanding_epochs > 0
            and float(public_deep_v2_understanding_weight) > 0.0
        ),
    }
    public_deep_v2_understanding_preference_training = {
        "kind": UNDERSTANDING_PREFERENCE_VERSION,
        "weight": float(public_deep_v2_understanding_preference_weight),
        "margin": float(public_deep_v2_understanding_preference_margin),
        "epochs": public_deep_v2_understanding_preference_epochs,
        "learningRate": (
            float(public_deep_v2_understanding_preference_learning_rate)
            if public_deep_v2_understanding_preference_learning_rate is not None
            else None
        ),
        "pairCount": len(public_deep_v2_understanding_preference_pairs),
        "labelCounts": dict(sorted(public_deep_v2_understanding_preference_label_counts.items())),
        "semanticBridgeVersion": (
            PUBLIC_DEEP_V2_SEMANTIC_BRIDGE_VERSION
            if public_deep_v2_understanding_preference_uses_semantic_bridge
            else None
        ),
        "enabled": (
            bool(public_deep_v2_understanding_preference_pairs)
            and public_deep_v2_understanding_preference_epochs > 0
            and float(public_deep_v2_understanding_preference_weight) > 0.0
        ),
        "updates": [],
    }
    if initial_model_path is None:
        model = TorchActionValueModel(
            vectorizer=HashedFeatureVectorizer(size=vector_size),
            hidden_size=hidden_size,
            learning_rate=learning_rate,
            seed=seed,
            device=resolved_device,
            metadata={"trainingSeed": seed, "trainingMode": "deep_rl"},
        )
    else:
        model = TorchActionValueModel.load(initial_model_path, device=resolved_device)
        model.learning_rate = learning_rate
        model.optimizer = torch.optim.Adam(model.network.parameters(), lr=learning_rate)
        model.metadata.update({
            "trainingSeed": seed,
            "trainingMode": "deep_rl",
            "initialModelPath": str(initial_model_path),
        })
    model.metadata["observedOpponentFeatureVersion"] = OBSERVED_OPPONENT_FEATURE_VERSION
    public_deep_v2_candidate = (
        bool(public_deep_v2_teacher_rows)
        or bool(public_deep_v2_value_rows)
        or bool(public_deep_v2_rerank_pairs)
        or float(public_deep_v2_planner_preference_weight) > 0.0
        or float(public_deep_v2_planner_prior_weight) > 0.0
        or float(deep_v2_multitask_weight) > 0.0
        or bool(public_deep_v2_understanding_training["enabled"])
        or bool(public_deep_v2_understanding_preference_training["enabled"])
    )
    if public_deep_v2_candidate:
        model.metadata["publicDeepV2Candidate"] = True
        model.metadata["publicDeepV2GatePassed"] = False
    if public_deep_v2_planner_preference_weight > 0.0 or public_deep_v2_planner_prior_weight > 0.0:
        model.metadata["policyArchitecture"] = "public_deep_v2_planner"
    if public_deep_v2_planner_preference_weight > 0.0:
        model.metadata["publicDeepV2PlannerPreferenceWeight"] = float(public_deep_v2_planner_preference_weight)
    if public_deep_v2_planner_prior_weight > 0.0:
        model.metadata["publicDeepV2PlannerPriorWeight"] = float(public_deep_v2_planner_prior_weight)
    if public_deep_v2_teacher_rows:
        model.metadata["publicDeepV2TeacherRows"] = len(public_deep_v2_teacher_rows)
    if public_deep_v2_value_rows:
        model.metadata["publicDeepV2ValueRows"] = len(public_deep_v2_value_rows)
    if public_deep_v2_rerank_pairs:
        model.metadata["publicDeepV2RerankPairRows"] = len(public_deep_v2_rerank_pairs)
    if public_deep_v2_understanding_rows:
        model.metadata["publicDeepV2UnderstandingRows"] = len(public_deep_v2_understanding_rows)
    if (
        public_deep_v2_understanding_training["enabled"]
        and public_deep_v2_understanding_runtime_weight > 0.0
    ):
        model.metadata["publicDeepV2UnderstandingRuntimeVersion"] = PUBLIC_DEEP_V2_UNDERSTANDING_RUNTIME_VERSION
        model.metadata["publicDeepV2UnderstandingRuntimeWeight"] = float(public_deep_v2_understanding_runtime_weight)
    if public_deep_v2_understanding_preference_training["enabled"]:
        model.metadata["publicDeepV2UnderstandingPreferenceWeight"] = float(
            public_deep_v2_understanding_preference_weight
        )
    model.configure_trainable_parameters(train_scope)
    if public_deep_v2_training["enabled"]:
        public_deep_v2_training.update(train_torch_model_on_public_deep_v2_teacher_rows(
            model,
            public_deep_v2_teacher_rows,
            epochs=public_deep_v2_teacher_epochs,
            batch_size=int(public_deep_v2_teacher_batch_size),
                target=float(public_deep_v2_teacher_target),
                weight=float(public_deep_v2_teacher_weight),
                action_weight=float(public_deep_v2_teacher_action_weight),
                preference_margin=float(public_deep_v2_teacher_preference_margin),
                seed=seed + 902000,
            ))
    if public_deep_v2_value_training["enabled"]:
        public_deep_v2_value_training.update(train_torch_model_on_public_deep_v2_value_rows(
            model,
            public_deep_v2_value_rows,
            epochs=public_deep_v2_value_epochs,
            weight=float(public_deep_v2_value_weight),
        ))
        public_deep_v2_value_training["runtimeEnabled"] = bool(public_deep_v2_value_runtime_enabled)
        if public_deep_v2_value_runtime_enabled:
            model.metadata["stateValueLeafRuntimeEnabled"] = True
            model.metadata["stateValueLeafRuntimeFocus"] = "anti_aggro"
            model.metadata["publicDeepV2ValueRuntimeEnabled"] = True
    if public_deep_v2_rerank_training["enabled"]:
        public_deep_v2_rerank_training.update(model.train_public_deep_v2_rerank_pairs(
            public_deep_v2_rerank_pairs,
            epochs=public_deep_v2_rerank_epochs,
            margin=float(public_deep_v2_rerank_margin),
            weight=float(public_deep_v2_rerank_weight),
            preserve_action_path=True,
        ))
        public_deep_v2_rerank_training["runtimeEnabled"] = bool(public_deep_v2_rerank_runtime_enabled)
        public_deep_v2_rerank_training["runtimeWeight"] = float(public_deep_v2_rerank_runtime_weight)
        if public_deep_v2_rerank_runtime_enabled:
            model.metadata.update({
                "publicDeepV2RerankHeadRuntimeEnabled": True,
                "publicDeepV2RerankRuntimeGuardVersion": PUBLIC_DEEP_V2_RERANK_RUNTIME_GUARD_VERSION,
                "publicDeepV2RerankHeadKeyDecisionsOnly": True,
                "publicDeepV2RerankAntiAggroGuard": True,
                "publicDeepV2RerankHeadWeight": float(public_deep_v2_rerank_runtime_weight),
                "publicDeepV2RerankMaxWeight": 0.2,
            })
    if public_deep_v2_understanding_training["enabled"]:
        understanding_feature_rows, understanding_targets = _public_deep_v2_understanding_training_rows(
            public_deep_v2_understanding_rows
        )
        public_deep_v2_understanding_training.update(model.train_understanding_batch(
            feature_rows=understanding_feature_rows,
            targets=understanding_targets,
            epochs=public_deep_v2_understanding_epochs,
            weight=float(public_deep_v2_understanding_weight),
            preserve_action_path=True,
        ))
        public_deep_v2_understanding_training["rows"] = len(public_deep_v2_understanding_rows)
    if public_deep_v2_understanding_preference_training["enabled"]:
        public_deep_v2_understanding_preference_training["updates"].extend(
            train_preference_pairs_with_optional_learning_rate(
                model,
                public_deep_v2_understanding_preference_pairs,
                epochs=public_deep_v2_understanding_preference_epochs,
                margin=public_deep_v2_understanding_preference_margin,
                weight=public_deep_v2_understanding_preference_weight,
                learning_rate=public_deep_v2_understanding_preference_learning_rate,
                stage="initial",
            )
        )
        model.metadata.update({
            "publicDeepV2UnderstandingPreferenceVersion": public_deep_v2_understanding_preference_training["kind"],
            "publicDeepV2UnderstandingPreferenceEpochs": public_deep_v2_understanding_preference_epochs,
            "publicDeepV2UnderstandingPreferencePairCount": len(public_deep_v2_understanding_preference_pairs),
        })
        if public_deep_v2_understanding_preference_uses_semantic_bridge:
            model.metadata["publicDeepV2SemanticBridgeVersion"] = PUBLIC_DEEP_V2_SEMANTIC_BRIDGE_VERSION
    imitation_trace_paths = list(imitation_trace_paths or [])
    imitation_rows, imitation_trace_rows = collect_player_imitation_rows_from_traces(imitation_trace_paths)
    player_imitation = {
        "kind": "player_trace_imitation",
        "samples": len(imitation_rows),
        "epochs": 0,
        "batchSize": 0,
        "traceRows": _compact_rows(imitation_trace_rows, max_rows=20),
    }
    imitation_warm_start_path: Path | None = None
    if imitation_rows and int(imitation_epochs) > 0:
        player_imitation.update(train_torch_model_on_player_imitation_rows(
            model,
            imitation_rows,
            epochs=int(imitation_epochs),
            batch_size=int(imitation_batch_size),
            target=float(imitation_target),
            seed=seed + 880000,
        ))
        player_imitation["traceRows"] = _compact_rows(imitation_trace_rows, max_rows=20)
        model.metadata.update({
            "playerImitationTraceCount": len(imitation_trace_paths),
            "playerImitationSamples": player_imitation["samples"],
            "playerImitationEpochs": player_imitation["epochs"],
        })
        imitation_warm_start_path = out_dir / "imitation_warm_start.pt"
        model.save(imitation_warm_start_path, metadata={
            "trainingSeed": seed,
            "episodes": 0,
            "trainingMode": "deep_rl_player_imitation_warm_start",
            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
            "playerImitationTraceCount": len(imitation_trace_paths),
            "playerImitationSamples": player_imitation["samples"],
            "playerImitationEpochs": player_imitation["epochs"],
        })
    stateful_player_preference_epochs = max(0, int(stateful_player_preference_epochs))
    stateful_player_preference_pairs, stateful_player_preference_trace_rows = (
        collect_stateful_player_preference_pairs_from_traces(
            imitation_trace_paths,
            model=model,
            seed=seed + 885000,
            max_alternatives_per_event=stateful_player_preference_max_alternatives,
            winning_traces_only=stateful_player_preference_winning_traces_only,
        )
        if imitation_trace_paths
        else ([], [])
    )
    stateful_player_preference_source_pair_count = len(stateful_player_preference_pairs)
    stateful_player_preference_focus = str(stateful_player_preference_focus or "all").strip().lower()
    stateful_player_preference_pairs = _filter_stateful_player_preference_pairs(
        stateful_player_preference_pairs,
        focus=stateful_player_preference_focus,
    )
    stateful_player_preference_pairs = _drop_seat_identity_from_preference_pairs(stateful_player_preference_pairs)
    stateful_player_side_mirrored_pairs: list[dict[str, Any]] = []
    if stateful_player_preference_side_mirror:
        stateful_player_side_mirrored_pairs = side_mirrored_stateful_preference_pairs(stateful_player_preference_pairs)
        stateful_player_preference_pairs.extend(stateful_player_side_mirrored_pairs)
    stateful_label_counts: Counter[str] = Counter()
    for pair in stateful_player_preference_pairs:
        for label in _stateful_preference_pair_labels(pair):
            stateful_label_counts[label] += 1
    stateful_player_preference: dict[str, Any] = {
        "kind": "stateful_player_replay_preference_v1",
        "focus": stateful_player_preference_focus,
        "weight": float(stateful_player_preference_weight),
        "margin": float(stateful_player_preference_margin),
        "epochs": stateful_player_preference_epochs,
        "learningRate": (
            float(stateful_player_preference_learning_rate)
            if stateful_player_preference_learning_rate is not None
            else None
        ),
        "maxAlternativesPerEvent": max(1, int(stateful_player_preference_max_alternatives)),
        "winningTracesOnly": bool(stateful_player_preference_winning_traces_only),
        "traceRows": _compact_rows(stateful_player_preference_trace_rows, max_rows=20),
        "sourcePairCount": stateful_player_preference_source_pair_count,
        "sideMirror": bool(stateful_player_preference_side_mirror),
        "sideMirroredPairCount": len(stateful_player_side_mirrored_pairs),
        "pairCount": len(stateful_player_preference_pairs),
        "labelCounts": dict(sorted(stateful_label_counts.items())),
        "updates": [],
    }
    stateful_player_preference_warm_start_path: Path | None = None
    if (
        stateful_player_preference_pairs
        and stateful_player_preference_weight > 0.0
        and stateful_player_preference_epochs > 0
    ):
        stateful_player_preference["updates"].extend(train_preference_pairs_with_optional_learning_rate(
            model,
            stateful_player_preference_pairs,
            epochs=stateful_player_preference_epochs,
            margin=stateful_player_preference_margin,
            weight=stateful_player_preference_weight,
            learning_rate=stateful_player_preference_learning_rate,
            stage="initial",
        ))
        model.metadata.update({
            "statefulPlayerPreferenceVersion": stateful_player_preference["kind"],
            "statefulPlayerPreferenceEpochs": stateful_player_preference_epochs,
            "statefulPlayerPreferencePairCount": len(stateful_player_preference_pairs),
        })
        stateful_player_preference_warm_start_path = out_dir / "stateful_player_preference_warm_start.pt"
        model.save(stateful_player_preference_warm_start_path, metadata={
            "trainingSeed": seed,
            "episodes": 0,
            "trainingMode": "deep_rl_stateful_player_preference_warm_start",
            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
            "statefulPlayerPreferencePairCount": len(stateful_player_preference_pairs),
            "statefulPlayerPreferenceEpochs": stateful_player_preference_epochs,
        })
    stateful_lookahead_preference_epochs = max(0, int(stateful_lookahead_preference_epochs))
    stateful_lookahead_preference_focus = str(stateful_lookahead_preference_focus or "all").strip().lower()
    stateful_lookahead_pairs, stateful_lookahead_trace_rows = (
        collect_stateful_lookahead_preference_pairs_from_traces(
            imitation_trace_paths,
            model=model,
            seed=seed + 887000,
            max_model_actions=stateful_lookahead_preference_max_model_actions,
            depth=stateful_lookahead_preference_depth,
            branch_width=stateful_lookahead_preference_branch_width,
            min_value_gap=stateful_lookahead_preference_min_value_gap,
            focus=stateful_lookahead_preference_focus,
        )
        if imitation_trace_paths
        else ([], [])
    )
    stateful_lookahead_pairs = _drop_seat_identity_from_preference_pairs(stateful_lookahead_pairs)
    stateful_lookahead_label_counts: Counter[str] = Counter()
    stateful_lookahead_side_mirrored_pairs: list[dict[str, Any]] = []
    if stateful_lookahead_preference_side_mirror:
        stateful_lookahead_side_mirrored_pairs = side_mirrored_stateful_preference_pairs(stateful_lookahead_pairs)
        stateful_lookahead_pairs.extend(stateful_lookahead_side_mirrored_pairs)
    for pair in stateful_lookahead_pairs:
        for label in _stateful_preference_pair_labels(pair):
            stateful_lookahead_label_counts[label] += 1
    stateful_lookahead_preference: dict[str, Any] = {
        "kind": "stateful_lookahead_preference_v1",
        "focus": stateful_lookahead_preference_focus,
        "weight": float(stateful_lookahead_preference_weight),
        "margin": float(stateful_lookahead_preference_margin),
        "epochs": stateful_lookahead_preference_epochs,
        "learningRate": (
            float(stateful_lookahead_preference_learning_rate)
            if stateful_lookahead_preference_learning_rate is not None
            else None
        ),
        "maxModelActions": max(2, int(stateful_lookahead_preference_max_model_actions)),
        "depth": max(1, int(stateful_lookahead_preference_depth)),
        "branchWidth": max(1, int(stateful_lookahead_preference_branch_width)),
        "minValueGap": float(stateful_lookahead_preference_min_value_gap),
        "traceRows": _compact_rows(stateful_lookahead_trace_rows, max_rows=20),
        "sideMirror": bool(stateful_lookahead_preference_side_mirror),
        "sideMirroredPairCount": len(stateful_lookahead_side_mirrored_pairs),
        "pairCount": len(stateful_lookahead_pairs),
        "labelCounts": dict(sorted(stateful_lookahead_label_counts.items())),
        "updates": [],
    }
    stateful_lookahead_preference_warm_start_path: Path | None = None
    if (
        stateful_lookahead_pairs
        and stateful_lookahead_preference_weight > 0.0
        and stateful_lookahead_preference_epochs > 0
    ):
        stateful_lookahead_preference["updates"].extend(train_preference_pairs_with_optional_learning_rate(
            model,
            stateful_lookahead_pairs,
            epochs=stateful_lookahead_preference_epochs,
            margin=stateful_lookahead_preference_margin,
            weight=stateful_lookahead_preference_weight,
            learning_rate=stateful_lookahead_preference_learning_rate,
            stage="initial",
        ))
        model.metadata.update({
            "statefulLookaheadPreferenceVersion": stateful_lookahead_preference["kind"],
            "statefulLookaheadPreferenceEpochs": stateful_lookahead_preference_epochs,
            "statefulLookaheadPreferencePairCount": len(stateful_lookahead_pairs),
        })
        stateful_lookahead_preference_warm_start_path = out_dir / "stateful_lookahead_preference_warm_start.pt"
        model.save(stateful_lookahead_preference_warm_start_path, metadata={
            "trainingSeed": seed,
            "episodes": 0,
            "trainingMode": "deep_rl_stateful_lookahead_preference_warm_start",
            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
            "statefulLookaheadPreferencePairCount": len(stateful_lookahead_pairs),
            "statefulLookaheadPreferenceEpochs": stateful_lookahead_preference_epochs,
        })
    linear_warm_start: dict[str, Any] = {
        "kind": "linear_to_deep_distillation",
        "samples": 0,
        "episodes": 0,
        "episodeRows": [],
    }
    if linear_warm_start_model_path is not None and linear_warm_start_episodes > 0:
        teacher = LinearQModel.load(linear_warm_start_model_path)
        teacher.seed_missing_greedy_prior_weights()
        warm_rows, warm_episode_rows = _collect_linear_warm_start_rows(
            teacher=teacher,
            episodes=linear_warm_start_episodes,
            seed=seed + 900000,
            opponent=opponent,
            learner_side=learner_side,
            epsilon=linear_warm_start_epsilon,
            deck_pool=deck_pool,
            deck_matchups=deck_matchups,
        )
        linear_warm_start = distill_linear_model_to_torch_model(
            model,
            teacher,
            warm_rows,
            epochs=linear_warm_start_epochs,
            batch_size=linear_warm_start_batch_size,
            seed=seed + 910000,
        )
        linear_warm_start["modelPath"] = str(linear_warm_start_model_path)
        linear_warm_start["episodes"] = int(linear_warm_start_episodes)
        linear_warm_start["epsilon"] = linear_warm_start_epsilon
        linear_warm_start["episodeRows"] = _compact_rows(warm_episode_rows)
        model.metadata.update({
            "linearWarmStartModelPath": str(linear_warm_start_model_path),
            "linearWarmStartEpisodes": int(linear_warm_start_episodes),
            "linearWarmStartSamples": linear_warm_start["samples"],
        })
    deep_anchor: dict[str, Any] = {
        "kind": "torch_to_torch_anchor_replay",
        "modelPath": str(deep_anchor_model_path) if deep_anchor_model_path is not None else None,
        "samples": 0,
        "episodes": 0,
        "episodeRows": [],
        "updates": [],
    }
    deep_anchor_teacher: TorchActionValueModel | None = None
    deep_anchor_rows: list[dict[str, float]] = []
    deep_anchor_interval = max(1, int(deep_anchor_interval))
    resolved_deep_anchor_opponent = str(deep_anchor_opponent or opponent)
    if deep_anchor_model_path is not None and deep_anchor_episodes > 0:
        deep_anchor_teacher = TorchActionValueModel.load(deep_anchor_model_path, device=resolved_device)
        deep_anchor_rows, deep_anchor_episode_rows = _collect_deep_anchor_rows(
            teacher=deep_anchor_teacher,
            episodes=deep_anchor_episodes,
            seed=seed + 920000,
            opponent=resolved_deep_anchor_opponent,
            opponent_model_paths=opponent_model_paths,
            learner_side=learner_side,
            epsilon=deep_anchor_epsilon,
            deck_pool=deck_pool,
            deck_matchups=deck_matchups,
        )
        deep_anchor.update({
            "samples": len(deep_anchor_rows),
            "episodes": int(deep_anchor_episodes),
            "episodeRows": _compact_rows(deep_anchor_episode_rows),
            "epochs": int(deep_anchor_epochs),
            "batchSize": int(deep_anchor_batch_size),
            "interval": int(deep_anchor_interval),
            "epsilon": deep_anchor_epsilon,
            "opponent": resolved_deep_anchor_opponent,
        })
        model.metadata.update({
            "deepAnchorModelPath": str(deep_anchor_model_path),
            "deepAnchorEpisodes": int(deep_anchor_episodes),
            "deepAnchorSamples": len(deep_anchor_rows),
        })
    opponent_behavior_preference_epochs = max(0, int(opponent_behavior_preference_epochs))
    opponent_behavior_pairs = opponent_behavior_preference_pairs()
    opponent_behavior_label_counts: Counter[str] = Counter()
    for pair in opponent_behavior_pairs:
        for label in pair.get("labels", []):
            opponent_behavior_label_counts[str(label)] += 1
    opponent_behavior_preference: dict[str, Any] = {
        "kind": OPPONENT_BEHAVIOR_PREFERENCE_VERSION,
        "weight": float(opponent_behavior_preference_weight),
        "margin": float(opponent_behavior_preference_margin),
        "epochs": opponent_behavior_preference_epochs,
        "learningRate": (
            float(opponent_behavior_preference_learning_rate)
            if opponent_behavior_preference_learning_rate is not None
            else None
        ),
        "reapplyAfterAnchor": bool(opponent_behavior_preference_reapply_after_anchor),
        "pairCount": len(opponent_behavior_pairs),
        "labelCounts": dict(sorted(opponent_behavior_label_counts.items())),
        "updates": [],
    }
    if opponent_behavior_pairs and opponent_behavior_preference_weight > 0.0 and opponent_behavior_preference_epochs > 0:
        opponent_behavior_preference["updates"].extend(train_preference_pairs_with_optional_learning_rate(
            model,
            opponent_behavior_pairs,
            epochs=opponent_behavior_preference_epochs,
            margin=opponent_behavior_preference_margin,
            weight=opponent_behavior_preference_weight,
            learning_rate=opponent_behavior_preference_learning_rate,
            stage="initial",
        ))
        model.metadata.update({
            "opponentBehaviorPreferenceVersion": OPPONENT_BEHAVIOR_PREFERENCE_VERSION,
            "opponentBehaviorPreferenceEpochs": opponent_behavior_preference_epochs,
            "opponentBehaviorPreferencePairCount": len(opponent_behavior_pairs),
        })
    public_policy_preference_epochs = max(0, int(public_policy_preference_epochs))
    public_policy_pairs = public_policy_preference_pairs()
    public_policy_label_counts: Counter[str] = Counter()
    for pair in public_policy_pairs:
        for label in pair.get("labels", []):
            public_policy_label_counts[str(label)] += 1
    public_policy_preference: dict[str, Any] = {
        "kind": PUBLIC_POLICY_PREFERENCE_VERSION,
        "weight": float(public_policy_preference_weight),
        "margin": float(public_policy_preference_margin),
        "epochs": public_policy_preference_epochs,
        "learningRate": (
            float(public_policy_preference_learning_rate)
            if public_policy_preference_learning_rate is not None
            else None
        ),
        "pairCount": len(public_policy_pairs),
        "labelCounts": dict(sorted(public_policy_label_counts.items())),
        "updates": [],
    }
    if public_policy_pairs and public_policy_preference_weight > 0.0 and public_policy_preference_epochs > 0:
        public_policy_preference["updates"].extend(train_preference_pairs_with_optional_learning_rate(
            model,
            public_policy_pairs,
            epochs=public_policy_preference_epochs,
            margin=public_policy_preference_margin,
            weight=public_policy_preference_weight,
            learning_rate=public_policy_preference_learning_rate,
            stage="initial",
        ))
        model.metadata.update({
            "publicPolicyPreferenceVersion": PUBLIC_POLICY_PREFERENCE_VERSION,
            "publicPolicyPreferenceEpochs": public_policy_preference_epochs,
            "publicPolicyPreferencePairCount": len(public_policy_pairs),
        })
    results = {"played": 0, "P1": 0, "P2": 0, "tie": 0, "errors": 0}
    learner_results = {"wins": 0, "losses": 0, "ties": 0}
    rows: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    deck_matrix_evaluations: list[dict[str, Any]] = []
    player_gate_evaluations: list[dict[str, Any]] = []
    player_gate_composite_evaluations: list[dict[str, Any]] = []
    counterfactual_replays: list[dict[str, Any]] = []
    memory_corrections: list[dict[str, Any]] = []
    resource_diagnostic_totals: Counter[str] = Counter()
    tactical_label_totals: Counter[str] = Counter()
    tactical_label_rows: list[dict[str, Any]] = []
    tactical_preference_totals: Counter[str] = Counter()
    lookahead_preference_totals: Counter[str] = Counter()
    policy_distillation_preference_totals: Counter[str] = Counter()
    public_deep_v2_planner_preference_totals: Counter[str] = Counter()
    lookahead_value_target_totals: Counter[str] = Counter()
    deep_v2_multitask_totals: Counter[str] = Counter()
    counterfactual_totals: Counter[str] = Counter()
    opponent_usage: Counter[str] = Counter()
    best_greedy = -1.0
    best_deck_matrix_average = -1.0
    best_deck_matrix_floor = -1.0
    best_player_gate_average = -1.0
    best_player_gate_floor = -1.0
    best_player_gate_composite = -1.0
    latest_path = out_dir / "latest.pt"
    best_greedy_path = out_dir / "best_greedy.pt"
    best_deck_matrix_average_path = out_dir / "best_deck_matrix_average.pt"
    best_deck_matrix_floor_path = out_dir / "best_deck_matrix_floor.pt"
    best_player_gate_average_path = out_dir / "best_player_vs_oldtop10_average.pt"
    best_player_gate_floor_path = out_dir / "best_player_vs_oldtop10_floor.pt"
    best_player_gate_composite_path = out_dir / "best_player_vs_oldtop10_composite.pt"
    rollout_actor_path = out_dir / "rollout_actor_latest.pt"
    parallel_rollout_cache: dict[int, Any] = {}
    parallel_rollout_batches = 0

    for index in range(episodes):
        episode_no = index + 1
        episode_side = _learner_side_for_episode(learner_side, index)
        epsilon = _linear_decay(epsilon_start, epsilon_end, index, episodes)
        learner_deck, opponent_deck = _training_deck_pair(deck_pool, index, deck_matchups=deck_matchups)
        capture_decision_snapshots = (
            rollout_workers <= 1
            and loss_replay_decisions > 0
            and loss_replay_alternatives > 0
            and loss_replay_max_branches > 0
        )
        if rollout_workers > 1:
            if index not in parallel_rollout_cache:
                batch_indexes = list(range(index, min(episodes, index + rollout_batch_size)))
                model.save(rollout_actor_path, metadata={
                    "trainingSeed": seed,
                    "episodes": episode_no - 1,
                    "trainingMode": "deep_rl_parallel_rollout_actor",
                    "rolloutWorkers": rollout_workers,
                })
                jobs: list[dict[str, Any]] = []
                for job_index in batch_indexes:
                    job_side = _learner_side_for_episode(learner_side, job_index)
                    job_learner_deck, job_opponent_deck = _training_deck_pair(
                        deck_pool,
                        job_index,
                        deck_matchups=deck_matchups,
                    )
                    job_opponent = _opponent_for_episode(opponent, opponent_schedule, job_index)
                    jobs.append({
                        "episode_index": job_index,
                        "seed": seed + job_index,
                        "model_path": str(rollout_actor_path),
                        "actor_device": str(rollout_actor_device),
                        "epsilon": _linear_decay(epsilon_start, epsilon_end, job_index, episodes),
                        "opponent": job_opponent,
                        "opponent_model_paths": [str(path) for path in opponent_model_paths],
                        "learner_side": job_side,
                        "learner_deck": job_learner_deck,
                        "opponent_deck": job_opponent_deck,
                        "training_lookahead_weight": training_lookahead_weight,
                        "training_max_lookahead_actions": training_max_lookahead_actions,
                        "training_beam_lookahead_width": training_beam_lookahead_width,
                        "training_beam_lookahead_depth": training_beam_lookahead_depth,
                        "training_beam_lookahead_key_decisions_only": training_beam_lookahead_key_decisions_only,
                        # Engine snapshots contain callbacks that are not process-pickleable.
                        # Single-match replay repair now handles rich corrected replay search.
                        "capture_decision_snapshots": False,
                    })
                batch_results = _collect_deep_rollout_batch(jobs, max_workers=rollout_workers)
                parallel_rollout_batches += 1
                for job_index, batch_episode in zip(batch_indexes, batch_results):
                    parallel_rollout_cache[job_index] = batch_episode
            episode = parallel_rollout_cache.pop(index)
        else:
            episode_opponent = _opponent_for_episode(opponent, opponent_schedule, index)
            episode = run_training_episode(
                seed=seed + index,
                model=model,
                epsilon=epsilon,
                opponent=episode_opponent,
                opponent_model_paths=opponent_model_paths,
                learner_side=episode_side,
                learner_deck=learner_deck,
                opponent_deck=opponent_deck,
                training_lookahead_weight=training_lookahead_weight,
                training_max_lookahead_actions=training_max_lookahead_actions,
                training_beam_lookahead_width=training_beam_lookahead_width,
                training_beam_lookahead_depth=training_beam_lookahead_depth,
                training_beam_lookahead_key_decisions_only=training_beam_lookahead_key_decisions_only,
                capture_decision_snapshots=capture_decision_snapshots,
                max_decision_snapshots=max(0, int(loss_replay_max_snapshots_per_episode)),
            )
        opponent_usage[episode.opponent] += 1
        results["played"] += 1
        if episode.winner == "error":
            results["errors"] += 1
            final_reward = -1.0
        else:
            results[episode.winner] = results.get(episode.winner, 0) + 1
            final_reward = _reward_for_learner(episode.winner, episode.learner_side)
            if episode.winner == "tie":
                learner_results["ties"] += 1
            elif episode.winner == episode.learner_side:
                learner_results["wins"] += 1
            else:
                learner_results["losses"] += 1
        updated_model = (final_reward < 0.0 and update_losing_episodes) or (
            final_reward >= 0.0 and update_winning_episodes
        )
        loss = 0.0
        episode_tactical_preference_pairs = (
            tactical_preference_pairs(episode.recorder.decisions)
            if tactical_preference_weight > 0.0
            else []
        )
        episode_lookahead_preference_pairs = (
            lookahead_preference_pairs(episode.recorder.decisions)
            if lookahead_preference_weight > 0.0
            else []
        )
        episode_policy_distillation_preference_pairs = (
            policy_distillation_preference_pairs(episode.recorder.decisions)
            if policy_distillation_preference_weight > 0.0
            else []
        )
        episode_public_deep_v2_planner_preference_pairs = (
            public_deep_v2_planner_preference_pairs(episode.recorder.decisions)
            if public_deep_v2_planner_preference_weight > 0.0
            else []
        )
        episode_lookahead_value_rows, _episode_lookahead_value_targets = (
            lookahead_value_target_rows(
                episode.recorder.decisions,
                min_abs_delta=lookahead_value_target_min_abs_delta,
            )
            if lookahead_value_target_weight > 0.0
            else ([], [])
        )
        episode_deep_v2_multitask_rows = (
            deep_v2_multitask_rows(
                episode.recorder.decisions,
                final_reward=final_reward,
                gamma=gamma,
            )
                if deep_v2_multitask_weight > 0.0
                else {"stateRows": [], "intentRows": [], "planRows": []}
            )
        if updated_model:
            loss = train_from_episode_decisions(
                model,
                episode.recorder.decisions,
                final_reward=final_reward,
                gamma=gamma,
                tactical_preference_weight=tactical_preference_weight,
                tactical_preference_margin=tactical_preference_margin,
                lookahead_preference_weight=lookahead_preference_weight,
                lookahead_preference_margin=lookahead_preference_margin,
                policy_distillation_preference_weight=policy_distillation_preference_weight,
                policy_distillation_preference_margin=policy_distillation_preference_margin,
                public_deep_v2_planner_preference_weight=public_deep_v2_planner_preference_weight,
                public_deep_v2_planner_preference_margin=public_deep_v2_planner_preference_margin,
                train_value_targets=train_value_targets,
                lookahead_value_target_weight=lookahead_value_target_weight,
                lookahead_value_target_min_abs_delta=lookahead_value_target_min_abs_delta,
                deep_v2_multitask_weight=deep_v2_multitask_weight,
                deep_v2_multitask_epochs=deep_v2_multitask_epochs,
            )
            if episode_tactical_preference_pairs:
                tactical_preference_totals["episodesWithPairs"] += 1
                tactical_preference_totals["pairCount"] += len(episode_tactical_preference_pairs)
            if episode_lookahead_preference_pairs:
                lookahead_preference_totals["episodesWithPairs"] += 1
                lookahead_preference_totals["pairCount"] += len(episode_lookahead_preference_pairs)
            if episode_policy_distillation_preference_pairs:
                policy_distillation_preference_totals["episodesWithPairs"] += 1
                policy_distillation_preference_totals["pairCount"] += len(episode_policy_distillation_preference_pairs)
            if episode_public_deep_v2_planner_preference_pairs:
                public_deep_v2_planner_preference_totals["episodesWithPairs"] += 1
                public_deep_v2_planner_preference_totals["pairCount"] += len(episode_public_deep_v2_planner_preference_pairs)
            if episode_lookahead_value_rows:
                lookahead_value_target_totals["episodesWithRows"] += 1
                lookahead_value_target_totals["rowCount"] += len(episode_lookahead_value_rows)
            if (
                episode_deep_v2_multitask_rows["stateRows"]
                or episode_deep_v2_multitask_rows["intentRows"]
                or episode_deep_v2_multitask_rows["planRows"]
            ):
                deep_v2_multitask_totals["episodesWithRows"] += 1
                deep_v2_multitask_totals["stateRowCount"] += len(episode_deep_v2_multitask_rows["stateRows"])
                deep_v2_multitask_totals["intentRowCount"] += len(episode_deep_v2_multitask_rows["intentRows"])
                deep_v2_multitask_totals["planRowCount"] += len(episode_deep_v2_multitask_rows["planRows"])
        episode_resource_diagnostics = summarize_decision_resource_diagnostics(episode.recorder.decisions)
        _add_resource_diagnostics(resource_diagnostic_totals, episode_resource_diagnostics)
        episode_tactical_labels = summarize_decision_tactical_labels(episode.recorder.decisions)
        for key in ("decisionCount", "labelCount", *TACTICAL_LABEL_COUNT_KEYS.values()):
            tactical_label_totals[key] += int(episode_tactical_labels.get(key, 0))
        for label_row in episode_tactical_labels.get("labelRows", []):
            tactical_label_rows.append({"episode": episode_no, **label_row})
        episode_counterfactual: dict[str, Any] | None = None
        if (
            final_reward < 0.0
            and rollout_workers <= 1
            and loss_replay_decisions > 0
            and loss_replay_alternatives > 0
            and loss_replay_max_branches > 0
        ):
            replay_result = run_deep_counterfactual_loss_replay(
                seed=seed + 600000 + episode_no,
                model=model,
                recorder=episode.recorder,
                opponent=episode.opponent,
                config=loss_replay_config,
                opponent_model_paths=opponent_model_paths,
                learner_side=episode.learner_side,
                learner_deck=learner_deck,
                opponent_deck=opponent_deck,
            )
            episode_counterfactual = {
                "branchesTried": int(replay_result.branches_tried),
                "skippedBranches": int(replay_result.skipped_branches),
                "improvedBranches": int(replay_result.improved_branches),
                "winningBranches": int(replay_result.winning_branches),
                "resourceRepairBranches": int(getattr(replay_result, "resource_repair_branches", 0)),
                "survivalImprovedBranches": int(getattr(replay_result, "survival_improved_branches", 0)),
                "runtimeBudgetExhausted": bool(getattr(replay_result, "runtime_budget_exhausted", False)),
                "modelUpdates": int(getattr(replay_result, "model_updates", 0)),
                "updateLoss": float(getattr(replay_result, "update_loss", 0.0)),
                "rows": _compact_rows(list(replay_result.rows), max_rows=6),
            }
            counterfactual_replays.append({"episode": episode_no, **episode_counterfactual})
            counterfactual_totals["branchesTried"] += episode_counterfactual["branchesTried"]
            counterfactual_totals["skippedBranches"] += episode_counterfactual["skippedBranches"]
            counterfactual_totals["improvedBranches"] += episode_counterfactual["improvedBranches"]
            counterfactual_totals["winningBranches"] += episode_counterfactual["winningBranches"]
            counterfactual_totals["resourceRepairBranches"] += episode_counterfactual["resourceRepairBranches"]
            counterfactual_totals["survivalImprovedBranches"] += episode_counterfactual["survivalImprovedBranches"]
            counterfactual_totals["runtimeBudgetExhaustedEpisodes"] += int(episode_counterfactual["runtimeBudgetExhausted"])
            counterfactual_totals["modelUpdates"] += episode_counterfactual["modelUpdates"]
            counterfactual_totals["episodesWithReplay"] += 1
            counterfactual_totals["updateLoss"] += episode_counterfactual["updateLoss"]
            match_id = _memory_match_id_from_deck_id(_deck_id_or_empty(learner_deck))
            if match_id:
                correction = _memory_correction_from_replay_result(
                    match_id=match_id,
                    episode_no=episode_no,
                    learner_side=episode.learner_side,
                    opponent=episode.opponent,
                    decisions=episode.recorder.decisions,
                    replay_result=replay_result,
                )
                if correction is not None:
                    memory_corrections.append(correction)
        if deep_anchor_teacher is not None and deep_anchor_rows and episode_no % deep_anchor_interval == 0:
            anchor_update = distill_torch_model_to_torch_model(
                model,
                deep_anchor_teacher,
                deep_anchor_rows,
                epochs=deep_anchor_epochs,
                batch_size=deep_anchor_batch_size,
                seed=seed + 930000 + episode_no,
            )
            deep_anchor["updates"].append({
                "episode": episode_no,
                "samples": anchor_update["samples"],
                "epochs": anchor_update["epochs"],
                "loss": anchor_update["loss"],
                "initialMeanAbsoluteError": anchor_update["initialMeanAbsoluteError"],
                "finalMeanAbsoluteError": anchor_update["finalMeanAbsoluteError"],
            })
            if (
                opponent_behavior_preference_reapply_after_anchor
                and opponent_behavior_pairs
                and opponent_behavior_preference_weight > 0.0
                and opponent_behavior_preference_epochs > 0
            ):
                opponent_behavior_preference["updates"].extend(train_preference_pairs_with_optional_learning_rate(
                    model,
                    opponent_behavior_pairs,
                    epochs=opponent_behavior_preference_epochs,
                    margin=opponent_behavior_preference_margin,
                    weight=opponent_behavior_preference_weight,
                    learning_rate=opponent_behavior_preference_learning_rate,
                    stage=f"afterDeepAnchorEpisode{episode_no}",
                ))
        rows.append({
            "episode": episode_no,
            "winner": episode.winner,
            "learnerSide": episode.learner_side,
            "opponent": episode.opponent,
            "learnerDeckId": _deck_id_or_empty(learner_deck),
            "learnerDeckName": _deck_name_or_empty(learner_deck),
            "opponentDeckId": _deck_id_or_empty(opponent_deck),
            "opponentDeckName": _deck_name_or_empty(opponent_deck),
            "turns": episode.turns,
            "epsilon": epsilon,
            "finalReward": final_reward,
            "loss": loss,
            "updatedModel": updated_model,
            "decisions": len(episode.recorder.decisions),
            "resourceDiagnostics": episode_resource_diagnostics,
            "tacticalDecisionLabels": episode_tactical_labels,
            "counterfactualReplay": episode_counterfactual,
            "error": episode.error,
        })
        if progress_callback is not None:
            progress_callback({
                "state": "running",
                "stage": "training",
                "episode": episode_no,
                "episodes": episodes,
                "learnerSide": episode.learner_side,
                "winner": episode.winner,
                "opponent": episode.opponent,
            })

        if episode_no % max(1, eval_interval) == 0 or episode_no == episodes:
            model.save(latest_path, metadata={
                "trainingSeed": seed,
                "episodes": episode_no,
                "trainingMode": "deep_rl",
                "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
                "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
            })
            eval_reports = [
                run_deep_evaluation(
                    model_path=latest_path,
                    episodes=eval_episodes,
                    seed=seed + 100000 + episode_no + side_index * 50000,
                    opponent="greedy",
                    learner_side=eval_side,
                    device=resolved_device,
                )
                for side_index, eval_side in enumerate(_fixed_eval_sides_for_mode(learner_side))
            ]
            greedy_score = min(float(report["winRate"]) for report in eval_reports)
            greedy_average = sum(float(report["winRate"]) for report in eval_reports) / max(1, len(eval_reports))
            promoted = greedy_score > best_greedy
            if promoted:
                best_greedy = greedy_score
                model.save(best_greedy_path, metadata={
                    "trainingSeed": seed,
                    "episodes": episode_no,
                    "trainingMode": "deep_rl",
                    "bestGreedySeatFloorWinRate": best_greedy,
                    "bestGreedyAverageWinRate": greedy_average,
                    "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
                    "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
                })
            for eval_report in eval_reports:
                evaluations.append({
                    "episode": episode_no,
                    "opponent": "greedy",
                    "learnerSide": eval_report["learnerSide"],
                    "winRate": eval_report["winRate"],
                    "seatFloorWinRate": greedy_score,
                    "averageWinRate": greedy_average,
                    "promoted": promoted,
                    "results": eval_report["results"],
                })
            if progress_callback is not None:
                progress_callback({
                    "state": "running",
                    "stage": "evaluation",
                    "episode": episode_no,
                    "episodes": episodes,
                    "evaluation": {
                        "opponent": "greedy",
                        "seatFloorWinRate": greedy_score,
                        "averageWinRate": greedy_average,
                        "bestGreedySeatFloorWinRate": best_greedy,
                    },
                })
            if player_gate_eval_episodes > 0:
                from zz.ai_league import run_player_vs_oldtop10_gate

                episode_player_gate_rows: list[dict[str, Any]] = []
                multiple_player_gate_kinds = len(player_gate_eval_opponent_kinds) > 1
                for gate_index, gate_opponent_kind in enumerate(player_gate_eval_opponent_kinds):
                    if multiple_player_gate_kinds:
                        safe_kind = _safe_player_gate_opponent_kind(gate_opponent_kind)
                        player_gate_report_path = out_dir / (
                            f"player_vs_oldtop10_gate_{safe_kind}_ep{episode_no:05d}.json"
                        )
                    else:
                        player_gate_report_path = out_dir / f"player_vs_oldtop10_gate_ep{episode_no:05d}.json"
                    player_gate_report = run_player_vs_oldtop10_gate(
                        episodes=player_gate_eval_episodes,
                        seed=seed + 300000 + episode_no + gate_index * 90_001,
                        model_kind="deep",
                        opponent_kind=gate_opponent_kind,
                        player_decks=player_gate_eval_player_decks,
                        old_top10_decks=player_gate_eval_old_top10_decks,
                        deck_root=player_gate_eval_deck_root,
                        top_suite_path=player_gate_eval_top_suite_path,
                        max_player_decks=player_gate_eval_max_player_decks,
                        max_old_top10_decks=player_gate_eval_max_old_top10_decks,
                        model_side=player_gate_eval_model_side,
                        pass_threshold=player_gate_eval_pass_threshold,
                        normal_model_path=player_gate_eval_normal_model_path,
                        deep_model_path=(
                            player_gate_eval_deep_model_path
                            if player_gate_eval_deep_model_path is not None
                            else latest_path
                        ),
                        model_deep_model_path=latest_path,
                        opponent_deep_model_path=player_gate_eval_deep_model_path,
                        allow_model_unpromoted_public_deep_v2=public_deep_v2_candidate,
                        allow_opponent_unpromoted_public_deep_v2=False,
                        data_root=player_gate_eval_data_root,
                        max_turns=player_gate_eval_max_turns,
                        max_actions=player_gate_eval_max_actions,
                        report_out=player_gate_report_path,
                    )
                    player_gate = player_gate_report["gate"]
                    player_gate_average = float(player_gate["averageWinRate"])
                    player_gate_floor = float(player_gate["minimumPlayerDeckWinRate"])
                    player_gate_average_promoted = player_gate_average > best_player_gate_average
                    if player_gate_average_promoted:
                        best_player_gate_average = player_gate_average
                        model.save(best_player_gate_average_path, metadata={
                            "trainingSeed": seed,
                            "episodes": episode_no,
                            "trainingMode": "deep_rl",
                            "bestPlayerVsOldTop10AverageWinRate": best_player_gate_average,
                            "bestPlayerVsOldTop10PlayerDeckFloorWinRate": player_gate_floor,
                            "bestPlayerVsOldTop10OpponentKind": gate_opponent_kind,
                            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
                            "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
                        })
                    player_gate_floor_promoted = player_gate_floor > best_player_gate_floor
                    if player_gate_floor_promoted:
                        best_player_gate_floor = player_gate_floor
                        model.save(best_player_gate_floor_path, metadata={
                            "trainingSeed": seed,
                            "episodes": episode_no,
                            "trainingMode": "deep_rl",
                            "bestPlayerVsOldTop10PlayerDeckFloorWinRate": best_player_gate_floor,
                            "bestPlayerVsOldTop10AverageWinRate": player_gate_average,
                            "bestPlayerVsOldTop10OpponentKind": gate_opponent_kind,
                            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
                            "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
                        })
                    gate_row = {
                        "episode": episode_no,
                        "reportPath": str(player_gate_report_path),
                        "episodesPerRow": int(player_gate_report["episodesPerRow"]),
                        "opponentKind": player_gate_report["opponentKind"],
                        "modelSideMode": player_gate_report["modelSideMode"],
                        "playerDeckCount": int(player_gate_report["playerDeckCount"]),
                        "oldTop10DeckCount": int(player_gate_report["oldTop10DeckCount"]),
                        "rowCount": int(player_gate_report["rowCount"]),
                        "averageWinRate": player_gate_average,
                        "minimumRowWinRate": float(player_gate["minimumRowWinRate"]),
                        "minimumPlayerDeckWinRate": player_gate_floor,
                        "zeroRowCount": int(player_gate["zeroRowCount"]),
                        "timeoutCount": int(player_gate["timeoutCount"]),
                        "errorCount": int(player_gate["errorCount"]),
                        "passed": bool(player_gate["passed"]),
                        "promoted": player_gate_average_promoted or player_gate_floor_promoted,
                        "promotedMetrics": {
                            "player_gate_average": player_gate_average_promoted,
                            "player_gate_floor": player_gate_floor_promoted,
                        },
                    }
                    episode_player_gate_rows.append(gate_row)
                    player_gate_evaluations.append(gate_row)
                if episode_player_gate_rows:
                    composite = {
                        "episode": episode_no,
                        **_player_gate_composite_summary(episode_player_gate_rows),
                    }
                    composite_promoted = float(composite["compositeScore"]) > best_player_gate_composite
                    if composite_promoted:
                        best_player_gate_composite = float(composite["compositeScore"])
                        model.save(best_player_gate_composite_path, metadata={
                            "trainingSeed": seed,
                            "episodes": episode_no,
                            "trainingMode": "deep_rl",
                            "bestPlayerVsOldTop10CompositeScore": best_player_gate_composite,
                            "bestPlayerVsOldTop10AverageWinRate": composite["averageWinRate"],
                            "bestPlayerVsOldTop10PlayerDeckFloorWinRate": composite["minimumPlayerDeckWinRate"],
                            "bestPlayerVsOldTop10ZeroRowCount": composite["zeroRowCount"],
                            "bestPlayerVsOldTop10OpponentKinds": composite["opponentKinds"],
                            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
                            "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
                        })
                    composite["promoted"] = composite_promoted
                    player_gate_composite_evaluations.append(composite)
            if deck_pool and deck_matrix_eval_episodes > 0:
                matrix_report = run_deep_deck_matrix_evaluation(
                    model_path=latest_path,
                    learner_decks=deck_pool,
                    opponent_decks=deck_pool,
                    episodes=deck_matrix_eval_episodes,
                    seed=seed + 400000 + episode_no,
                    seed_count=deck_matrix_seed_count,
                    opponent="greedy",
                    device=resolved_device,
                )
                matrix_average_promoted = matrix_report["averageWinRate"] > best_deck_matrix_average
                if matrix_average_promoted:
                    best_deck_matrix_average = matrix_report["averageWinRate"]
                    model.save(best_deck_matrix_average_path, metadata={
                        "trainingSeed": seed,
                        "episodes": episode_no,
                        "trainingMode": "deep_rl",
                        "bestDeckMatrixAverageWinRate": best_deck_matrix_average,
                        "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
                        "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
                    })
                matrix_floor_promoted = matrix_report["minimumSeedWinRate"] > best_deck_matrix_floor
                if matrix_floor_promoted:
                    best_deck_matrix_floor = matrix_report["minimumSeedWinRate"]
                    model.save(best_deck_matrix_floor_path, metadata={
                        "trainingSeed": seed,
                        "episodes": episode_no,
                        "trainingMode": "deep_rl",
                        "bestDeckMatrixFloorWinRate": best_deck_matrix_floor,
                        "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
                        "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
                    })
                deck_matrix_evaluations.append({
                    "episode": episode_no,
                    "seedCount": matrix_report["seedCount"],
                    "rowCount": matrix_report["rowCount"],
                    "averageWinRate": matrix_report["averageWinRate"],
                    "minimumSeedWinRate": matrix_report["minimumSeedWinRate"],
                    "promoted": matrix_average_promoted or matrix_floor_promoted,
                    "promotedMetrics": {
                        "deck_matrix_average": matrix_average_promoted,
                        "deck_matrix_floor": matrix_floor_promoted,
                    },
                })

    if public_deep_v2_candidate:
        public_deep_v2_versions = _public_deep_v2_report_metadata(
            model=model,
            candidate=public_deep_v2_candidate,
            teacher_rows=public_deep_v2_teacher_rows,
            understanding_rows=public_deep_v2_understanding_rows,
            value_rows=public_deep_v2_value_rows,
            rerank_pairs=public_deep_v2_rerank_pairs,
        )
        if public_deep_v2_versions["cardProfileVersion"] is not None:
            model.metadata["publicDeepV2CardProfileVersion"] = public_deep_v2_versions["cardProfileVersion"]
        if public_deep_v2_versions["deckProfileVersion"] is not None:
            model.metadata["publicDeepV2DeckProfileVersion"] = public_deep_v2_versions["deckProfileVersion"]
        if public_deep_v2_versions["plannerVersion"] is not None:
            model.metadata["publicDeepV2PlannerVersion"] = public_deep_v2_versions["plannerVersion"]

    model.save(latest_path, metadata={
        "trainingSeed": seed,
        "episodes": episodes,
        "trainingMode": "deep_rl",
        "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
        "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
    })
    public_deep_v2_metadata = _public_deep_v2_report_metadata(
        model=model,
        candidate=public_deep_v2_candidate,
        teacher_rows=public_deep_v2_teacher_rows,
        understanding_rows=public_deep_v2_understanding_rows,
        value_rows=public_deep_v2_value_rows,
        rerank_pairs=public_deep_v2_rerank_pairs,
    )
    completed = max(1, results["P1"] + results["P2"] + results["tie"])
    report = {
        "schemaVersion": 1,
        "kind": "deep_rl_training_report",
        "createdAt": _utc_now(),
        "trainingSeed": seed,
        "episodes": episodes,
        "latestModelPath": str(latest_path),
        "imitationWarmStartModelPath": str(imitation_warm_start_path) if imitation_warm_start_path is not None else None,
        "statefulPlayerPreferenceWarmStartModelPath": (
            str(stateful_player_preference_warm_start_path)
            if stateful_player_preference_warm_start_path is not None
            else None
        ),
        "statefulLookaheadPreferenceWarmStartModelPath": (
            str(stateful_lookahead_preference_warm_start_path)
            if stateful_lookahead_preference_warm_start_path is not None
            else None
        ),
        "bestGreedyModelPath": str(best_greedy_path) if best_greedy_path.exists() else None,
        "bestGreedyScore": best_greedy,
        "bestGreedyScoreKind": "seat_floor",
        "bestDeckMatrixAverageModelPath": str(best_deck_matrix_average_path) if best_deck_matrix_average_path.exists() else None,
        "bestDeckMatrixFloorModelPath": str(best_deck_matrix_floor_path) if best_deck_matrix_floor_path.exists() else None,
        "bestPlayerGateAverageModelPath": str(best_player_gate_average_path) if best_player_gate_average_path.exists() else None,
        "bestPlayerGateFloorModelPath": str(best_player_gate_floor_path) if best_player_gate_floor_path.exists() else None,
        "bestPlayerGateCompositeModelPath": (
            str(best_player_gate_composite_path) if best_player_gate_composite_path.exists() else None
        ),
        "bestPlayerGateAverageScore": best_player_gate_average,
        "bestPlayerGateFloorScore": best_player_gate_floor,
        "bestPlayerGateCompositeScore": best_player_gate_composite,
        "modelMetadata": dict(model.metadata),
        "publicDeepV2": public_deep_v2_metadata,
        "config": {
            "vectorSize": model.vectorizer.size,
            "hiddenSize": model.hidden_size,
            "device": str(model.device),
            "requestedDevice": str(device),
            "requireCuda": bool(require_cuda),
            "trainScope": train_scope,
            **torch_environment,
            "learningRate": learning_rate,
            "gamma": gamma,
            "epsilonStart": epsilon_start,
            "epsilonEnd": epsilon_end,
            "trainingLookaheadWeight": float(training_lookahead_weight),
            "trainingMaxLookaheadActions": int(training_max_lookahead_actions),
            "trainingBeamLookaheadWidth": int(training_beam_lookahead_width),
            "trainingBeamLookaheadDepth": int(training_beam_lookahead_depth),
            "trainingBeamLookaheadKeyDecisionsOnly": bool(training_beam_lookahead_key_decisions_only),
            "tacticalPreferenceWeight": float(tactical_preference_weight),
            "tacticalPreferenceMargin": float(tactical_preference_margin),
            "lookaheadPreferenceWeight": float(lookahead_preference_weight),
            "lookaheadPreferenceMargin": float(lookahead_preference_margin),
            "policyDistillationPreferenceWeight": float(policy_distillation_preference_weight),
            "policyDistillationPreferenceMargin": float(policy_distillation_preference_margin),
            "publicDeepV2PlannerPreferenceWeight": float(public_deep_v2_planner_preference_weight),
            "publicDeepV2PlannerPreferenceMargin": float(public_deep_v2_planner_preference_margin),
            "publicDeepV2PlannerPriorWeight": float(public_deep_v2_planner_prior_weight),
            "trainValueTargets": bool(train_value_targets),
            "lookaheadValueTargetWeight": float(lookahead_value_target_weight),
            "lookaheadValueTargetMinAbsDelta": float(lookahead_value_target_min_abs_delta),
            "deepV2MultitaskWeight": float(deep_v2_multitask_weight),
            "deepV2MultitaskEpochs": int(deep_v2_multitask_epochs),
            "publicPolicyPreferenceWeight": float(public_policy_preference_weight),
            "publicPolicyPreferenceMargin": float(public_policy_preference_margin),
            "publicPolicyPreferenceEpochs": int(public_policy_preference_epochs),
            "publicPolicyPreferenceLearningRate": (
                float(public_policy_preference_learning_rate)
                if public_policy_preference_learning_rate is not None
                else None
            ),
            "publicDeepV2TeacherSamples": len(public_deep_v2_teacher_rows),
            "publicDeepV2TeacherEpochs": public_deep_v2_teacher_epochs,
            "publicDeepV2TeacherBatchSize": int(public_deep_v2_teacher_batch_size),
            "publicDeepV2TeacherTarget": float(public_deep_v2_teacher_target),
            "publicDeepV2TeacherWeight": float(public_deep_v2_teacher_weight),
            "publicDeepV2TeacherActionWeight": float(public_deep_v2_teacher_action_weight),
            "publicDeepV2TeacherPreferenceMargin": float(public_deep_v2_teacher_preference_margin),
            "publicDeepV2ValueRows": len(public_deep_v2_value_rows),
            "publicDeepV2ValueEpochs": int(public_deep_v2_value_epochs),
            "publicDeepV2ValueWeight": float(public_deep_v2_value_weight),
            "publicDeepV2ValueRuntimeEnabled": bool(public_deep_v2_value_runtime_enabled),
            "publicDeepV2RerankPairs": len(public_deep_v2_rerank_pairs),
            "publicDeepV2RerankEpochs": int(public_deep_v2_rerank_epochs),
            "publicDeepV2RerankWeight": float(public_deep_v2_rerank_weight),
            "publicDeepV2RerankMargin": float(public_deep_v2_rerank_margin),
            "publicDeepV2RerankRuntimeEnabled": bool(public_deep_v2_rerank_runtime_enabled),
            "publicDeepV2RerankRuntimeWeight": float(public_deep_v2_rerank_runtime_weight),
            "publicDeepV2UnderstandingRows": len(public_deep_v2_understanding_rows),
            "publicDeepV2UnderstandingEpochs": int(public_deep_v2_understanding_epochs),
            "publicDeepV2UnderstandingWeight": float(public_deep_v2_understanding_weight),
            "publicDeepV2UnderstandingRuntimeWeight": float(public_deep_v2_understanding_runtime_weight),
            "publicDeepV2UnderstandingPreferenceWeight": float(public_deep_v2_understanding_preference_weight),
            "publicDeepV2UnderstandingPreferenceMargin": float(public_deep_v2_understanding_preference_margin),
            "publicDeepV2UnderstandingPreferenceEpochs": int(public_deep_v2_understanding_preference_epochs),
            "publicDeepV2UnderstandingPreferenceLearningRate": (
                float(public_deep_v2_understanding_preference_learning_rate)
                if public_deep_v2_understanding_preference_learning_rate is not None
                else None
            ),
            "opponentBehaviorPreferenceWeight": float(opponent_behavior_preference_weight),
            "opponentBehaviorPreferenceMargin": float(opponent_behavior_preference_margin),
            "opponentBehaviorPreferenceEpochs": int(opponent_behavior_preference_epochs),
            "opponentBehaviorPreferenceLearningRate": (
                float(opponent_behavior_preference_learning_rate)
                if opponent_behavior_preference_learning_rate is not None
                else None
            ),
            "opponentBehaviorPreferenceReapplyAfterAnchor": bool(opponent_behavior_preference_reapply_after_anchor),
            "updateLosingEpisodes": update_losing_episodes,
            "updateWinningEpisodes": update_winning_episodes,
            "lossReplayDecisions": int(loss_replay_decisions),
            "lossReplayAlternatives": int(loss_replay_alternatives),
            "lossReplayMaxBranches": int(loss_replay_max_branches),
            "lossReplayAlpha": float(loss_replay_alpha),
            "lossReplayRewardResourceRepairs": bool(loss_replay_reward_resource_repairs),
            "lossReplayRewardResourceRepairSurvivalImprovements": bool(
                loss_replay_reward_resource_repair_survival_improvements
            ),
            "lossReplayWinningUpdateRepeats": max(1, int(loss_replay_winning_update_repeats)),
            "lossReplayBranchMaxTurns": max(1, int(loss_replay_branch_max_turns)),
            "lossReplayBranchMaxActions": max(1, int(loss_replay_branch_max_actions)),
            "lossReplayMaxRuntimeSeconds": max(0.0, float(loss_replay_max_runtime_seconds)),
            "lossReplayStopAfterImprovedBranch": bool(loss_replay_stop_after_improved_branch),
            "lossReplayMaxSnapshotsPerEpisode": max(0, int(loss_replay_max_snapshots_per_episode)),
            "rolloutWorkers": int(rollout_workers),
            "rolloutBatchSize": int(rollout_batch_size),
            "rolloutActorDevice": str(rollout_actor_device),
            "parallelRolloutBatches": int(parallel_rollout_batches),
            "lossReplayDisabledForParallelRollouts": bool(
                rollout_workers > 1
                and loss_replay_decisions > 0
                and loss_replay_alternatives > 0
                and loss_replay_max_branches > 0
            ),
            "opponent": opponent,
            "opponentSchedule": list(opponent_schedule),
            "opponentModelPaths": [str(path) for path in opponent_model_paths],
            "learnerSide": learner_side,
            "evalInterval": eval_interval,
            "evalEpisodes": eval_episodes,
            "initialModelPath": str(initial_model_path) if initial_model_path is not None else None,
            "linearWarmStartModelPath": str(linear_warm_start_model_path) if linear_warm_start_model_path is not None else None,
            "linearWarmStartEpisodes": int(linear_warm_start_episodes),
            "linearWarmStartEpochs": int(linear_warm_start_epochs),
            "linearWarmStartBatchSize": int(linear_warm_start_batch_size),
            "linearWarmStartEpsilon": linear_warm_start_epsilon,
            "deepAnchorModelPath": str(deep_anchor_model_path) if deep_anchor_model_path is not None else None,
            "deepAnchorEpisodes": int(deep_anchor_episodes),
            "deepAnchorEpochs": int(deep_anchor_epochs),
            "deepAnchorBatchSize": int(deep_anchor_batch_size),
            "deepAnchorInterval": int(deep_anchor_interval),
            "deepAnchorEpsilon": deep_anchor_epsilon,
            "deepAnchorOpponent": resolved_deep_anchor_opponent,
            "imitationTraceCount": len(imitation_trace_paths),
            "imitationTracePaths": [str(path) for path in imitation_trace_paths],
            "imitationEpochs": int(imitation_epochs),
            "imitationBatchSize": int(imitation_batch_size),
            "imitationTarget": float(imitation_target),
            "statefulPlayerPreferenceWeight": float(stateful_player_preference_weight),
            "statefulPlayerPreferenceMargin": float(stateful_player_preference_margin),
            "statefulPlayerPreferenceEpochs": int(stateful_player_preference_epochs),
            "statefulPlayerPreferenceLearningRate": (
                float(stateful_player_preference_learning_rate)
                if stateful_player_preference_learning_rate is not None
                else None
            ),
            "statefulPlayerPreferenceMaxAlternatives": max(1, int(stateful_player_preference_max_alternatives)),
            "statefulPlayerPreferenceWinningTracesOnly": bool(stateful_player_preference_winning_traces_only),
            "statefulPlayerPreferenceFocus": stateful_player_preference_focus,
            "statefulPlayerPreferenceSideMirror": bool(stateful_player_preference_side_mirror),
            "statefulLookaheadPreferenceWeight": float(stateful_lookahead_preference_weight),
            "statefulLookaheadPreferenceMargin": float(stateful_lookahead_preference_margin),
            "statefulLookaheadPreferenceEpochs": int(stateful_lookahead_preference_epochs),
            "statefulLookaheadPreferenceLearningRate": (
                float(stateful_lookahead_preference_learning_rate)
                if stateful_lookahead_preference_learning_rate is not None
                else None
            ),
            "statefulLookaheadPreferenceMaxModelActions": max(2, int(stateful_lookahead_preference_max_model_actions)),
            "statefulLookaheadPreferenceDepth": max(1, int(stateful_lookahead_preference_depth)),
            "statefulLookaheadPreferenceBranchWidth": max(1, int(stateful_lookahead_preference_branch_width)),
            "statefulLookaheadPreferenceMinValueGap": float(stateful_lookahead_preference_min_value_gap),
            "statefulLookaheadPreferenceFocus": stateful_lookahead_preference_focus,
            "statefulLookaheadPreferenceSideMirror": bool(stateful_lookahead_preference_side_mirror),
            "deckPoolSize": len(deck_pool),
            "deckMatchupSize": len(deck_matchups),
            "deckMatrixEvalEpisodes": deck_matrix_eval_episodes,
            "deckMatrixSeedCount": deck_matrix_seed_count,
            "playerGateEvalEpisodes": player_gate_eval_episodes,
            "playerGateEvalOpponentKind": player_gate_eval_opponent_kind,
            "playerGateEvalOpponentKinds": list(player_gate_eval_opponent_kinds),
            "playerGateEvalModelSide": player_gate_eval_model_side,
            "playerGateEvalPassThreshold": float(player_gate_eval_pass_threshold),
            "playerGateEvalMaxPlayerDecks": player_gate_eval_max_player_decks,
            "playerGateEvalMaxOldTop10Decks": player_gate_eval_max_old_top10_decks,
            "playerGateEvalMaxTurns": int(player_gate_eval_max_turns),
            "playerGateEvalMaxActions": int(player_gate_eval_max_actions),
            "playerGateEvalDeckRoot": str(player_gate_eval_deck_root) if player_gate_eval_deck_root is not None else None,
            "playerGateEvalTopSuitePath": str(player_gate_eval_top_suite_path),
            "playerGateEvalNormalModelPath": str(player_gate_eval_normal_model_path) if player_gate_eval_normal_model_path is not None else None,
            "playerGateEvalDeepModelPath": str(player_gate_eval_deep_model_path) if player_gate_eval_deep_model_path is not None else None,
            "playerGateEvalDataRoot": str(player_gate_eval_data_root) if player_gate_eval_data_root is not None else None,
        },
        "linearWarmStart": linear_warm_start,
        "deepAnchor": deep_anchor,
        "playerImitation": player_imitation,
        "statefulPlayerPreferenceTraining": stateful_player_preference,
        "statefulLookaheadPreferenceTraining": stateful_lookahead_preference,
        "results": results,
        "learnerResults": learner_results,
        "trainingOpponentUsage": dict(sorted(opponent_usage.items())),
        "winRate": learner_results["wins"] / completed,
        "resourceMovementDiagnostics": _resource_diagnostics_from_totals(resource_diagnostic_totals),
        "tacticalDecisionLabels": {
            "decisionCount": int(tactical_label_totals["decisionCount"]),
            "labelCount": int(tactical_label_totals["labelCount"]),
            **{
                key: int(tactical_label_totals[key])
                for key in TACTICAL_LABEL_COUNT_KEYS.values()
            },
            "labelRows": _compact_rows(tactical_label_rows, max_rows=40),
        },
        "tacticalPreferenceTraining": {
            "weight": float(tactical_preference_weight),
            "margin": float(tactical_preference_margin),
            "episodesWithPairs": int(tactical_preference_totals["episodesWithPairs"]),
            "pairCount": int(tactical_preference_totals["pairCount"]),
        },
        "opponentBehaviorPreferenceTraining": opponent_behavior_preference,
        "publicPolicyPreferenceTraining": public_policy_preference,
        "publicDeepV2TeacherTraining": public_deep_v2_training,
        "publicDeepV2ValueTraining": public_deep_v2_value_training,
        "publicDeepV2RerankTraining": public_deep_v2_rerank_training,
        "publicDeepV2UnderstandingTraining": public_deep_v2_understanding_training,
        "publicDeepV2UnderstandingPreferenceTraining": public_deep_v2_understanding_preference_training,
        "lookaheadPreferenceTraining": {
            "weight": float(lookahead_preference_weight),
            "margin": float(lookahead_preference_margin),
            "episodesWithPairs": int(lookahead_preference_totals["episodesWithPairs"]),
            "pairCount": int(lookahead_preference_totals["pairCount"]),
        },
        "policyDistillationPreferenceTraining": {
            "weight": float(policy_distillation_preference_weight),
            "margin": float(policy_distillation_preference_margin),
            "episodesWithPairs": int(policy_distillation_preference_totals["episodesWithPairs"]),
            "pairCount": int(policy_distillation_preference_totals["pairCount"]),
        },
        "publicDeepV2PlannerPreferenceTraining": {
            "weight": float(public_deep_v2_planner_preference_weight),
            "margin": float(public_deep_v2_planner_preference_margin),
            "episodesWithPairs": int(public_deep_v2_planner_preference_totals["episodesWithPairs"]),
            "pairCount": int(public_deep_v2_planner_preference_totals["pairCount"]),
        },
        "lookaheadValueTargetTraining": {
            "weight": float(lookahead_value_target_weight),
            "minAbsDelta": float(lookahead_value_target_min_abs_delta),
            "episodesWithRows": int(lookahead_value_target_totals["episodesWithRows"]),
            "rowCount": int(lookahead_value_target_totals["rowCount"]),
        },
        "deepV2MultitaskTraining": {
            "weight": float(deep_v2_multitask_weight),
            "epochs": int(deep_v2_multitask_epochs),
            "episodesWithRows": int(deep_v2_multitask_totals["episodesWithRows"]),
            "stateRowCount": int(deep_v2_multitask_totals["stateRowCount"]),
            "intentRowCount": int(deep_v2_multitask_totals["intentRowCount"]),
            "planRowCount": int(deep_v2_multitask_totals["planRowCount"]),
        },
        "counterfactualReplay": {
            "episodesWithReplay": int(counterfactual_totals["episodesWithReplay"]),
            "branchesTried": int(counterfactual_totals["branchesTried"]),
            "skippedBranches": int(counterfactual_totals["skippedBranches"]),
            "improvedBranches": int(counterfactual_totals["improvedBranches"]),
            "winningBranches": int(counterfactual_totals["winningBranches"]),
            "resourceRepairBranches": int(counterfactual_totals["resourceRepairBranches"]),
            "survivalImprovedBranches": int(counterfactual_totals["survivalImprovedBranches"]),
            "runtimeBudgetExhaustedEpisodes": int(counterfactual_totals["runtimeBudgetExhaustedEpisodes"]),
            "modelUpdates": int(counterfactual_totals["modelUpdates"]),
            "updateLoss": float(counterfactual_totals["updateLoss"]),
            "rows": _compact_rows(counterfactual_replays, max_rows=30),
        },
        "memoryCorrections": memory_corrections,
        "evaluations": evaluations,
        "deckMatrixEvaluations": deck_matrix_evaluations,
        "playerGateEvaluations": player_gate_evaluations,
        "playerGateCompositeEvaluations": player_gate_composite_evaluations,
        "rowCount": len(rows),
        "rows": _compact_rows(rows),
    }
    (out_dir / "training_report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report
