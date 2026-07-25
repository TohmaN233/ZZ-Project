from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from zz.action_set_scoring_contracts import validate_action_set_scorer_shape


ACTION_SET_LISTWISE_MODEL_VERSION = "action_set_listwise_scorer_v1"
ACTION_SET_LISTWISE_TRUE_TURN_ORDER_HYBRID_VERSION = "action_set_listwise_true_turn_order_hybrid_v1"
ACTION_SET_LISTWISE_ROUTED_VERSION = "action_set_listwise_routed_v1"
ACTION_SET_LISTWISE_ADDITIVE_VERSION = "action_set_listwise_additive_v1"
ACTION_SET_LISTWISE_GATED_ADDITIVE_VERSION = "action_set_listwise_gated_additive_v1"


@dataclass
class ActionSetListwiseScorer:
    inputDim: int
    hiddenDim: int
    w1: list[list[float]] = field(default_factory=list)
    b1: list[float] = field(default_factory=list)
    w2: list[float] = field(default_factory=list)
    b2: float = 0.0
    modelVersion: str = ACTION_SET_LISTWISE_MODEL_VERSION
    featureMode: str = "flat"

    def score_row(self, row: Mapping[str, Any]) -> list[float | None]:
        scores: list[float | None] = []
        mask = _mask(row)
        for slot, enabled in enumerate(mask):
            if not enabled:
                scores.append(None)
                continue
            vector = _slot_vector(row, slot, input_dim=self.inputDim, feature_mode=self.featureMode)
            hidden: list[float] = []
            for weights, bias in zip(self.w1, self.b1, strict=False):
                value = float(bias) + sum(float(w) * x for w, x in zip(weights, vector, strict=False))
                hidden.append(max(0.0, value))
            score = float(self.b2) + sum(float(w) * value for w, value in zip(self.w2, hidden, strict=False))
            scores.append(score)
        return scores

    def score_rows(self, rows: list[Mapping[str, Any]]) -> list[list[float | None]]:
        return [self.score_row(row) for row in rows]

    def score_rows_batched(
        self,
        rows: list[Mapping[str, Any]],
        *,
        batch_size: int = 512,
    ) -> list[list[float | None]]:
        if not rows:
            return []
        try:
            import torch
            import torch.nn.functional as functional
        except ImportError:
            return self.score_rows(rows)
        if not self.w1 or not self.w2:
            return self.score_rows(rows)

        weight_1 = torch.tensor(self.w1, dtype=torch.float32)
        bias_1 = torch.tensor(self.b1, dtype=torch.float32)
        weight_2 = torch.tensor(self.w2, dtype=torch.float32)
        bounded_batch = max(1, int(batch_size))
        out: list[list[float | None]] = []
        for start in range(0, len(rows), bounded_batch):
            batch = rows[start : start + bounded_batch]
            max_slots = max((len(_mask(row)) for row in batch), default=0)
            x_tensor = torch.zeros((len(batch), max_slots, self.inputDim), dtype=torch.float32)
            mask_tensor = torch.zeros((len(batch), max_slots), dtype=torch.bool)
            for row_index, row in enumerate(batch):
                for slot, enabled in enumerate(_mask(row)):
                    if not enabled:
                        continue
                    mask_tensor[row_index, slot] = True
                    x_tensor[row_index, slot, :] = torch.tensor(
                        _slot_vector(row, slot, input_dim=self.inputDim, feature_mode=self.featureMode),
                        dtype=torch.float32,
                    )
            hidden = functional.relu(torch.matmul(x_tensor, weight_1.t()) + bias_1)
            scores = torch.matmul(hidden, weight_2) + float(self.b2)
            for row_index in range(len(batch)):
                row_scores: list[float | None] = []
                for slot in range(len(_mask(batch[row_index]))):
                    row_scores.append(float(scores[row_index, slot].item()) if bool(mask_tensor[row_index, slot]) else None)
                out.append(row_scores)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.modelVersion,
            "inputDim": int(self.inputDim),
            "hiddenDim": int(self.hiddenDim),
            "w1": [[float(value) for value in row] for row in self.w1],
            "b1": [float(value) for value in self.b1],
            "w2": [float(value) for value in self.w2],
            "b2": float(self.b2),
            "featureFamily": "global_action_shared_mlp_v1",
            "featureMode": _normalize_feature_mode(self.featureMode),
            "usesTeacherScores": True,
            "defaultRuntimeChanged": False,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionSetListwiseScorer":
        return cls(
            inputDim=int(data.get("inputDim", 0) or 0),
            hiddenDim=int(data.get("hiddenDim", 0) or 0),
            w1=[
                [float(value) for value in row]
                for row in list(data.get("w1") or [])
            ],
            b1=[float(value) for value in list(data.get("b1") or [])],
            w2=[float(value) for value in list(data.get("w2") or [])],
            b2=float(data.get("b2", 0.0) or 0.0),
            modelVersion=str(data.get("modelVersion") or ACTION_SET_LISTWISE_MODEL_VERSION),
            featureMode=_normalize_feature_mode(data.get("featureMode")),
        )


@dataclass
class ActionSetTrueTurnOrderHybridScorer:
    firstScorer: ActionSetListwiseScorer
    secondScorer: ActionSetListwiseScorer
    fallbackTurnOrder: str = "first"
    modelVersion: str = ACTION_SET_LISTWISE_TRUE_TURN_ORDER_HYBRID_VERSION

    def score_row(self, row: Mapping[str, Any]) -> list[float | None]:
        return self._scorer_for_row(row).score_row(row)

    def score_rows(self, rows: list[Mapping[str, Any]]) -> list[list[float | None]]:
        return [self.score_row(row) for row in rows]

    def score_rows_batched(
        self,
        rows: list[Mapping[str, Any]],
        *,
        batch_size: int = 512,
    ) -> list[list[float | None]]:
        if not rows:
            return []
        return [self.score_row(row) for row in rows]

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.modelVersion,
            "firstScorer": self.firstScorer.to_dict(),
            "secondScorer": self.secondScorer.to_dict(),
            "fallbackTurnOrder": str(self.fallbackTurnOrder),
            "featureFamily": "true_turn_order_hybrid_listwise_mlp_v1",
            "usesTeacherScores": True,
            "defaultRuntimeChanged": False,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionSetTrueTurnOrderHybridScorer":
        first = _nested_scorer_dict(data.get("firstScorer"))
        second = _nested_scorer_dict(data.get("secondScorer"))
        return cls(
            firstScorer=ActionSetListwiseScorer.from_dict(first),
            secondScorer=ActionSetListwiseScorer.from_dict(second),
            fallbackTurnOrder=str(data.get("fallbackTurnOrder") or "first"),
        )

    def _scorer_for_row(self, row: Mapping[str, Any]) -> ActionSetListwiseScorer:
        turn_order = _row_true_turn_order(row)
        if turn_order == "second":
            return self.secondScorer
        if turn_order == "first":
            return self.firstScorer
        if str(self.fallbackTurnOrder).lower() == "second":
            return self.secondScorer
        return self.firstScorer


@dataclass
class ActionSetRoutedListwiseScorer:
    defaultScorer: Any
    routes: dict[str, Any]
    modelVersion: str = ACTION_SET_LISTWISE_ROUTED_VERSION

    def score_row(self, row: Mapping[str, Any]) -> list[float | None]:
        return self._scorer_for_row(row).score_row(row)

    def score_rows(self, rows: list[Mapping[str, Any]]) -> list[list[float | None]]:
        return [self.score_row(row) for row in rows]

    def score_rows_batched(
        self,
        rows: list[Mapping[str, Any]],
        *,
        batch_size: int = 512,
    ) -> list[list[float | None]]:
        if not rows:
            return []
        return [self.score_row(row) for row in rows]

    def route_key_for_row(self, row: Mapping[str, Any]) -> str | None:
        for key in _route_keys_for_row(row):
            if key in self.routes:
                return key
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.modelVersion,
            "defaultScorer": self.defaultScorer.to_dict(),
            "routes": {
                str(route): scorer.to_dict()
                for route, scorer in sorted(self.routes.items(), key=lambda item: str(item[0]))
            },
            "routeSyntax": "trueTurnOrder|decisionKind with wildcard * support",
            "featureFamily": "routed_listwise_mlp_v1",
            "usesTeacherScores": True,
            "defaultRuntimeChanged": False,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionSetRoutedListwiseScorer":
        default_data = _nested_scorer_dict(data.get("defaultScorer") or data.get("baseScorer"))
        route_data = data.get("routes")
        if not isinstance(route_data, Mapping):
            raise ValueError("routed listwise scorer requires a routes mapping")
        return cls(
            defaultScorer=_scorer_from_dict(default_data),
            routes={
                _normalize_route_key(str(route)): _scorer_from_dict(_nested_scorer_dict(scorer_data))
                for route, scorer_data in route_data.items()
            },
        )

    def _scorer_for_row(self, row: Mapping[str, Any]) -> Any:
        for key in _route_keys_for_row(row):
            scorer = self.routes.get(key)
            if scorer is not None:
                return scorer
        return self.defaultScorer


@dataclass
class ActionSetAdditiveScorer:
    baseScorer: Any
    deltaScorer: Any
    deltaWeight: float = 0.1
    modelVersion: str = ACTION_SET_LISTWISE_ADDITIVE_VERSION

    def score_row(self, row: Mapping[str, Any]) -> list[float | None]:
        base_scores = list(self.baseScorer.score_row(row))
        delta_scores = list(self.deltaScorer.score_row(row))
        out: list[float | None] = []
        for slot, base_score in enumerate(base_scores):
            if base_score is None:
                out.append(None)
                continue
            delta_score = delta_scores[slot] if 0 <= slot < len(delta_scores) else None
            out.append(float(base_score) + float(self.deltaWeight) * (float(delta_score) if delta_score is not None else 0.0))
        return out

    def score_rows(self, rows: list[Mapping[str, Any]]) -> list[list[float | None]]:
        return [self.score_row(row) for row in rows]

    def score_rows_batched(
        self,
        rows: list[Mapping[str, Any]],
        *,
        batch_size: int = 512,
    ) -> list[list[float | None]]:
        if not rows:
            return []
        base_score_rows = self.baseScorer.score_rows_batched(rows, batch_size=batch_size)
        delta_score_rows = self.deltaScorer.score_rows(rows)
        out: list[list[float | None]] = []
        for base_scores, delta_scores in zip(base_score_rows, delta_score_rows, strict=False):
            row_scores: list[float | None] = []
            for slot, base_score in enumerate(base_scores):
                if base_score is None:
                    row_scores.append(None)
                    continue
                delta_score = delta_scores[slot] if 0 <= slot < len(delta_scores) else None
                row_scores.append(
                    float(base_score) + float(self.deltaWeight) * (float(delta_score) if delta_score is not None else 0.0)
                )
            out.append(row_scores)
        return out

    def route_key_for_row(self, row: Mapping[str, Any]) -> str | None:
        route_key = getattr(self.baseScorer, "route_key_for_row", None)
        if callable(route_key):
            return route_key(row)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.modelVersion,
            "baseScorer": self.baseScorer.to_dict(),
            "deltaScorer": self.deltaScorer.to_dict(),
            "deltaWeight": float(self.deltaWeight),
            "featureFamily": "additive_base_plus_action_value_delta_v1",
            "usesTeacherScores": True,
            "defaultRuntimeChanged": False,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionSetAdditiveScorer":
        return cls(
            baseScorer=_scorer_from_dict(_nested_scorer_dict(data.get("baseScorer"))),
            deltaScorer=_scorer_from_dict(_nested_scorer_dict(data.get("deltaScorer"))),
            deltaWeight=float(data.get("deltaWeight", 0.1) or 0.0),
        )


@dataclass
class ActionSetGatedAdditiveScorer:
    baseScorer: Any
    deltaScorer: Any
    deltaWeight: float = 0.1
    gate: Mapping[str, Any] = field(default_factory=dict)
    modelVersion: str = ACTION_SET_LISTWISE_GATED_ADDITIVE_VERSION

    def score_row(self, row: Mapping[str, Any]) -> list[float | None]:
        base_scores = list(self.baseScorer.score_row(row))
        if not self.gate_matches(row):
            return base_scores
        delta_scores = list(self.deltaScorer.score_row(row))
        return self._merge_scores(base_scores, delta_scores)

    def score_rows(self, rows: list[Mapping[str, Any]]) -> list[list[float | None]]:
        return [self.score_row(row) for row in rows]

    def score_rows_batched(
        self,
        rows: list[Mapping[str, Any]],
        *,
        batch_size: int = 512,
    ) -> list[list[float | None]]:
        if not rows:
            return []
        base_score_rows = self.baseScorer.score_rows_batched(rows, batch_size=batch_size)
        gated_indexes = [index for index, row in enumerate(rows) if self.gate_matches(row)]
        if not gated_indexes:
            return base_score_rows
        gated_rows = [rows[index] for index in gated_indexes]
        gated_delta_rows = self.deltaScorer.score_rows(gated_rows)
        out = [list(scores) for scores in base_score_rows]
        for index, delta_scores in zip(gated_indexes, gated_delta_rows, strict=False):
            out[index] = self._merge_scores(out[index], list(delta_scores))
        return out

    def gate_matches(self, row: Mapping[str, Any]) -> bool:
        true_turn_orders = _gate_values(self.gate, "trueTurnOrders")
        if true_turn_orders and _row_true_turn_order(row) not in true_turn_orders:
            return False
        source_suite_kinds = _gate_values(self.gate, "sourceSuiteKinds", "suiteKinds")
        if source_suite_kinds and _row_source_suite_kind(row) not in source_suite_kinds:
            return False
        decision_kinds = _gate_values(self.gate, "decisionKinds")
        if decision_kinds and _row_decision_kind(row) not in decision_kinds:
            return False
        return True

    def route_key_for_row(self, row: Mapping[str, Any]) -> str | None:
        route_key = getattr(self.baseScorer, "route_key_for_row", None)
        if callable(route_key):
            base_route_key = route_key(row)
            if base_route_key is not None:
                return base_route_key
        if self.gate_matches(row):
            return "|".join(
                (
                    "gated_delta",
                    _row_source_suite_kind(row),
                    _row_true_turn_order(row),
                    _row_decision_kind(row),
                )
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.modelVersion,
            "baseScorer": self.baseScorer.to_dict(),
            "deltaScorer": self.deltaScorer.to_dict(),
            "deltaWeight": float(self.deltaWeight),
            "gate": _normalized_gate_dict(self.gate),
            "gateMode": "conjunctive_non_empty_fields",
            "featureFamily": "gated_additive_base_plus_action_value_delta_v1",
            "usesTeacherScores": True,
            "defaultRuntimeChanged": False,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionSetGatedAdditiveScorer":
        return cls(
            baseScorer=_scorer_from_dict(_nested_scorer_dict(data.get("baseScorer"))),
            deltaScorer=_scorer_from_dict(_nested_scorer_dict(data.get("deltaScorer"))),
            deltaWeight=float(data.get("deltaWeight", 0.1) or 0.0),
            gate=_normalized_gate_dict(data.get("gate") if isinstance(data.get("gate"), Mapping) else {}),
        )

    def _merge_scores(
        self,
        base_scores: list[float | None],
        delta_scores: list[float | None],
    ) -> list[float | None]:
        out: list[float | None] = []
        for slot, base_score in enumerate(base_scores):
            if base_score is None:
                out.append(None)
                continue
            delta_score = delta_scores[slot] if 0 <= slot < len(delta_scores) else None
            out.append(float(base_score) + float(self.deltaWeight) * (float(delta_score) if delta_score is not None else 0.0))
        return out


def train_action_set_listwise_scorer(
    rows: list[Mapping[str, Any]],
    *,
    epochs: int = 24,
    learning_rate: float = 0.01,
    hidden_dim: int = 64,
    batch_size: int = 256,
    teacher_score_weight: float = 0.35,
    teacher_temperature: float = 1.0,
    seed: int = 20260609,
    initial_scorer: ActionSetListwiseScorer | None = None,
    feature_mode: str = "flat",
) -> ActionSetListwiseScorer:
    row_list = [row for row in rows if _selected_slot(row) is not None and _legal_slots(row)]
    if not row_list:
        raise ValueError("listwise scorer training requires at least one usable row")
    try:
        import torch
        import torch.nn.functional as functional
    except ImportError as exc:  # pragma: no cover - exercised only without torch
        raise RuntimeError("PyTorch is required to train action_set_listwise_scorer_v1") from exc

    torch.manual_seed(int(seed))
    normalized_feature_mode = _normalize_feature_mode(feature_mode)
    input_dim = max(_slot_vector_length(row, feature_mode=normalized_feature_mode) for row in row_list)
    max_slots = max(len(_mask(row)) for row in row_list)
    x_tensor, mask_tensor, selected_tensor, soft_targets, soft_weights, row_weights = _training_tensors(
        row_list,
        input_dim=input_dim,
        max_slots=max_slots,
        teacher_temperature=max(1.0e-6, float(teacher_temperature)),
        feature_mode=normalized_feature_mode,
    )
    model = torch.nn.Sequential(
        torch.nn.Linear(input_dim, int(hidden_dim)),
        torch.nn.ReLU(),
        torch.nn.Linear(int(hidden_dim), 1),
    )
    if initial_scorer is not None:
        _copy_initial_scorer_weights(
            model,
            initial_scorer=initial_scorer,
            input_dim=input_dim,
            hidden_dim=int(hidden_dim),
        )
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    count = x_tensor.shape[0]
    bounded_batch = max(1, int(batch_size))
    teacher_mix = max(0.0, min(1.0, float(teacher_score_weight)))

    for _epoch in range(max(0, int(epochs))):
        for start in range(0, count, bounded_batch):
            end = min(count, start + bounded_batch)
            batch_x = x_tensor[start:end]
            batch_mask = mask_tensor[start:end]
            logits = model(batch_x).squeeze(-1)
            logits = logits.masked_fill(~batch_mask, -1.0e9)
            selected_loss = functional.cross_entropy(
                logits,
                selected_tensor[start:end],
                reduction="none",
            )
            log_probs = functional.log_softmax(logits, dim=1)
            teacher_loss = -(soft_targets[start:end] * log_probs).sum(dim=1)
            mix = teacher_mix * soft_weights[start:end]
            loss_by_row = (1.0 - mix) * selected_loss + mix * teacher_loss
            weighted_loss = loss_by_row * row_weights[start:end]
            loss = weighted_loss.mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

    first = model[0]
    second = model[2]
    return ActionSetListwiseScorer(
        inputDim=input_dim,
        hiddenDim=int(hidden_dim),
        w1=first.weight.detach().cpu().tolist(),
        b1=first.bias.detach().cpu().tolist(),
        w2=second.weight.detach().cpu().view(-1).tolist(),
        b2=float(second.bias.detach().cpu().view(-1)[0].item()),
        featureMode=normalized_feature_mode,
    )


def train_action_set_pairwise_margin_scorer(
    rows: list[Mapping[str, Any]],
    *,
    epochs: int = 24,
    learning_rate: float = 0.01,
    hidden_dim: int = 64,
    batch_size: int = 256,
    margin: float = 1.0,
    max_margin: float = 4.0,
    seed: int = 20260611,
    initial_scorer: ActionSetListwiseScorer | None = None,
    teacher_score_pair_fallback: bool = False,
    feature_mode: str = "flat",
) -> ActionSetListwiseScorer:
    row_list = [
        row
        for row in rows
        if _pairwise_preference(row, teacher_score_pair_fallback=teacher_score_pair_fallback) is not None
        and _legal_slots(row)
    ]
    if not row_list:
        raise ValueError("pairwise margin training requires at least one usable preferred/rejected row")
    try:
        import torch
        import torch.nn.functional as functional
    except ImportError as exc:  # pragma: no cover - exercised only without torch
        raise RuntimeError("PyTorch is required to train action_set_pairwise_margin_scorer") from exc

    torch.manual_seed(int(seed))
    normalized_feature_mode = _normalize_feature_mode(feature_mode)
    input_dim = max(_slot_vector_length(row, feature_mode=normalized_feature_mode) for row in row_list)
    preferred_x, rejected_x, margins, row_weights = _pairwise_training_tensors(
        row_list,
        input_dim=input_dim,
        base_margin=max(1.0e-6, float(margin)),
        max_margin=max(1.0e-6, float(max_margin)),
        teacher_score_pair_fallback=teacher_score_pair_fallback,
        feature_mode=normalized_feature_mode,
    )
    model = torch.nn.Sequential(
        torch.nn.Linear(input_dim, int(hidden_dim)),
        torch.nn.ReLU(),
        torch.nn.Linear(int(hidden_dim), 1),
    )
    if initial_scorer is not None:
        _copy_initial_scorer_weights(
            model,
            initial_scorer=initial_scorer,
            input_dim=input_dim,
            hidden_dim=int(hidden_dim),
        )
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    count = preferred_x.shape[0]
    bounded_batch = max(1, int(batch_size))

    for _epoch in range(max(0, int(epochs))):
        for start in range(0, count, bounded_batch):
            end = min(count, start + bounded_batch)
            preferred_scores = model(preferred_x[start:end]).squeeze(-1)
            rejected_scores = model(rejected_x[start:end]).squeeze(-1)
            score_gap = preferred_scores - rejected_scores
            loss_by_row = functional.relu(margins[start:end] - score_gap)
            weighted_loss = loss_by_row * row_weights[start:end]
            loss = weighted_loss.mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

    first = model[0]
    second = model[2]
    return ActionSetListwiseScorer(
        inputDim=input_dim,
        hiddenDim=int(hidden_dim),
        w1=first.weight.detach().cpu().tolist(),
        b1=first.bias.detach().cpu().tolist(),
        w2=second.weight.detach().cpu().view(-1).tolist(),
        b2=float(second.bias.detach().cpu().view(-1)[0].item()),
        featureMode=normalized_feature_mode,
    )


def _copy_initial_scorer_weights(
    model: Any,
    *,
    initial_scorer: ActionSetListwiseScorer,
    input_dim: int,
    hidden_dim: int,
) -> None:
    if int(initial_scorer.inputDim) != int(input_dim):
        raise ValueError(
            "initial listwise scorer inputDim is incompatible with teacher rows: "
            f"{initial_scorer.inputDim} != {input_dim}"
        )
    initial_hidden_dim = int(initial_scorer.hiddenDim)
    requested_hidden_dim = int(hidden_dim)
    if initial_hidden_dim > requested_hidden_dim:
        raise ValueError(
            "initial listwise scorer hiddenDim cannot be larger than requested hidden_dim: "
            f"{initial_scorer.hiddenDim} > {hidden_dim}"
        )
    if len(initial_scorer.w1) != initial_hidden_dim or any(len(row) != int(input_dim) for row in initial_scorer.w1):
        raise ValueError("initial listwise scorer w1 shape is incompatible")
    if len(initial_scorer.b1) != initial_hidden_dim:
        raise ValueError("initial listwise scorer b1 shape is incompatible")
    if len(initial_scorer.w2) != initial_hidden_dim:
        raise ValueError("initial listwise scorer w2 shape is incompatible")

    import torch

    with torch.no_grad():
        model[0].weight[:initial_hidden_dim].copy_(torch.tensor(initial_scorer.w1, dtype=torch.float32))
        model[0].bias[:initial_hidden_dim].copy_(torch.tensor(initial_scorer.b1, dtype=torch.float32))
        model[2].weight[:, :initial_hidden_dim].copy_(torch.tensor([initial_scorer.w2], dtype=torch.float32))
        model[2].bias.copy_(torch.tensor([float(initial_scorer.b2)], dtype=torch.float32))


def _training_tensors(
    rows: list[Mapping[str, Any]],
    *,
    input_dim: int,
    max_slots: int,
    teacher_temperature: float,
    feature_mode: str = "flat",
) -> tuple[Any, Any, Any, Any, Any, Any]:
    import torch

    count = len(rows)
    x_tensor = torch.zeros((count, max_slots, input_dim), dtype=torch.float32)
    mask_tensor = torch.zeros((count, max_slots), dtype=torch.bool)
    selected_tensor = torch.zeros((count,), dtype=torch.long)
    soft_targets = torch.zeros((count, max_slots), dtype=torch.float32)
    soft_weights = torch.zeros((count,), dtype=torch.float32)
    row_weights = torch.ones((count,), dtype=torch.float32)
    decision_counts: dict[str, int] = {}
    for row in rows:
        decision_kind = str(row.get("decisionKind") or "unknown")
        decision_counts[decision_kind] = decision_counts.get(decision_kind, 0) + 1

    for row_index, row in enumerate(rows):
        legal_slots = _legal_slots(row)
        selected_slot = _selected_slot(row)
        if selected_slot is None:
            selected_slot = legal_slots[0]
        selected_tensor[row_index] = int(selected_slot)
        for slot in legal_slots:
            mask_tensor[row_index, slot] = True
            x_tensor[row_index, slot, :] = torch.tensor(
                _slot_vector(row, slot, input_dim=input_dim, feature_mode=feature_mode),
                dtype=torch.float32,
            )
        soft_target, has_teacher_spread = _teacher_distribution(
            row,
            legal_slots=legal_slots,
            selected_slot=selected_slot,
            max_slots=max_slots,
            temperature=teacher_temperature,
        )
        soft_targets[row_index, :] = torch.tensor(soft_target, dtype=torch.float32)
        soft_weights[row_index] = 1.0 if has_teacher_spread else 0.0
        decision_kind = str(row.get("decisionKind") or "unknown")
        decision_weight = len(rows) / max(1.0, len(decision_counts) * decision_counts[decision_kind])
        row_weights[row_index] = decision_weight * _row_training_weight(row)

    mean_weight = float(row_weights.mean().item()) if count else 1.0
    if mean_weight > 0.0:
        row_weights = row_weights / mean_weight

    return x_tensor, mask_tensor, selected_tensor, soft_targets, soft_weights, row_weights


def _pairwise_training_tensors(
    rows: list[Mapping[str, Any]],
    *,
    input_dim: int,
    base_margin: float,
    max_margin: float,
    teacher_score_pair_fallback: bool = False,
    feature_mode: str = "flat",
) -> tuple[Any, Any, Any, Any]:
    import torch

    preferred_vectors: list[list[float]] = []
    rejected_vectors: list[list[float]] = []
    margins: list[float] = []
    weights: list[float] = []
    decision_counts: dict[str, int] = {}
    for row in rows:
        decision_kind = str(row.get("decisionKind") or "unknown")
        decision_counts[decision_kind] = decision_counts.get(decision_kind, 0) + 1

    for row in rows:
        preference = _pairwise_preference(row, teacher_score_pair_fallback=teacher_score_pair_fallback)
        if preference is None:
            continue
        preferred_slot, rejected_slot, value_gap = preference
        legal_slots = set(_legal_slots(row))
        if preferred_slot not in legal_slots or rejected_slot not in legal_slots:
            continue
        preferred_vectors.append(_slot_vector(row, preferred_slot, input_dim=input_dim, feature_mode=feature_mode))
        rejected_vectors.append(_slot_vector(row, rejected_slot, input_dim=input_dim, feature_mode=feature_mode))
        margins.append(_pairwise_margin(base_margin=base_margin, max_margin=max_margin, value_gap=value_gap))
        decision_kind = str(row.get("decisionKind") or "unknown")
        decision_weight = len(rows) / max(1.0, len(decision_counts) * decision_counts[decision_kind])
        weights.append(decision_weight * _row_training_weight(row))

    if not preferred_vectors:
        raise ValueError("pairwise margin training found no rows with legal preferred/rejected slots")

    row_weights = torch.tensor(weights, dtype=torch.float32)
    mean_weight = float(row_weights.mean().item()) if len(weights) else 1.0
    if mean_weight > 0.0:
        row_weights = row_weights / mean_weight

    return (
        torch.tensor(preferred_vectors, dtype=torch.float32),
        torch.tensor(rejected_vectors, dtype=torch.float32),
        torch.tensor(margins, dtype=torch.float32),
        row_weights,
    )


def _pairwise_preference(
    row: Mapping[str, Any],
    *,
    teacher_score_pair_fallback: bool = False,
) -> tuple[int, int, float | None] | None:
    label = row.get("actionValuePreflightLabel")
    if not isinstance(label, Mapping):
        label = row.get("freshLabelTrainingPreference")
    if not isinstance(label, Mapping):
        label = {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}

    preferred = _optional_int(label.get("preferredSlot"))
    rejected = _optional_int(label.get("rejectedSlot"))
    if preferred is None:
        preferred = _optional_int(metadata.get("actionValuePreferredActionSlot"))
    if rejected is None:
        rejected = _optional_int(metadata.get("actionValueRejectedActionSlot"))
    if preferred is None:
        preferred = _optional_int(metadata.get("freshPreferredActionSlot"))
    if rejected is None:
        rejected = _optional_int(metadata.get("freshRejectedActionSlot"))
    if preferred is None or rejected is None or preferred == rejected:
        if not teacher_score_pair_fallback:
            return None
        teacher_pair = _teacher_score_pairwise_preference(row)
        if teacher_pair is None:
            return None
        return teacher_pair
    value_gap = _optional_float(label.get("valueGap"))
    if value_gap is None:
        value_gap = _optional_float(metadata.get("actionValueGap"))
    if value_gap is None:
        value_gap = _optional_float(metadata.get("freshValueGap"))
    return preferred, rejected, value_gap


def _teacher_score_pairwise_preference(row: Mapping[str, Any]) -> tuple[int, int, float | None] | None:
    legal_slots = _legal_slots(row)
    if len(legal_slots) < 2:
        return None
    teacher_scores = _score_slots(row.get("teacherScores"))
    legal_scores = {
        slot: float(teacher_scores[slot])
        for slot in legal_slots
        if slot < len(teacher_scores) and teacher_scores[slot] is not None and math.isfinite(float(teacher_scores[slot]))
    }
    if len(legal_scores) < 2:
        return None
    ranked = sorted(legal_scores, key=lambda slot: (legal_scores[slot], -slot), reverse=True)
    preferred = ranked[0]
    selected = _selected_slot(row)
    if selected is not None and selected in legal_scores and selected != preferred:
        rejected = int(selected)
    else:
        rejected = ranked[-1]
    if preferred == rejected:
        return None
    gap = legal_scores[preferred] - legal_scores[rejected]
    if gap <= 0.0:
        return None
    return int(preferred), int(rejected), float(gap)


def _pairwise_margin(*, base_margin: float, max_margin: float, value_gap: float | None) -> float:
    if value_gap is None or not math.isfinite(value_gap):
        return float(base_margin)
    scaled = max(float(base_margin), min(float(max_margin), abs(float(value_gap))))
    return float(scaled)


def _row_training_weight(row: Mapping[str, Any]) -> float:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    raw = row.get("trainingWeight")
    if raw is None and isinstance(metadata, Mapping):
        raw = metadata.get("trainingWeight")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    return max(0.001, min(1000.0, value))


def _row_true_turn_order(row: Mapping[str, Any]) -> str:
    value = row.get("trueTurnOrder")
    if value is None and isinstance(row.get("metadata"), Mapping):
        value = row["metadata"].get("trueTurnOrder")
    normalized = str(value or "").strip().lower()
    if normalized in {"first", "second"}:
        return normalized
    return ""


def _row_decision_kind(row: Mapping[str, Any]) -> str:
    value = row.get("decisionKind")
    if value is None and isinstance(row.get("metadata"), Mapping):
        value = row["metadata"].get("decisionKind")
    normalized = str(value or "").strip().lower()
    return normalized or "unknown"


def _row_source_suite_kind(row: Mapping[str, Any]) -> str:
    value = row.get("sourceSuiteKind")
    if value is None:
        value = row.get("suiteKind")
    if value is None and isinstance(row.get("metadata"), Mapping):
        metadata = row["metadata"]
        value = metadata.get("sourceSuiteKind") or metadata.get("suiteKind")
    normalized = str(value or "").strip().lower()
    return normalized or ""


def _gate_values(gate: Mapping[str, Any], *keys: str) -> set[str]:
    for key in keys:
        raw = gate.get(key)
        if raw is None:
            continue
        values = raw if isinstance(raw, list | tuple | set) else [raw]
        return {
            str(value).strip().lower()
            for value in values
            if str(value).strip()
        }
    return set()


def _normalized_gate_dict(gate: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        "trueTurnOrders": sorted(_gate_values(gate, "trueTurnOrders")),
        "sourceSuiteKinds": sorted(_gate_values(gate, "sourceSuiteKinds", "suiteKinds")),
        "decisionKinds": sorted(_gate_values(gate, "decisionKinds")),
    }


def _normalize_route_key(value: str) -> str:
    parts = [part.strip().lower() or "*" for part in str(value).split("|")]
    if len(parts) >= 3:
        suite_kind = parts[0] or "*"
        turn_order = parts[1] if parts[1] in {"first", "second", "*"} else "*"
        decision_kind = parts[2] or "*"
        return f"{suite_kind}|{turn_order}|{decision_kind}"
    if len(parts) == 1:
        parts.append("*")
    turn_order = parts[0] if parts[0] in {"first", "second", "*"} else "*"
    decision_kind = parts[1] or "*"
    return f"{turn_order}|{decision_kind}"


def _route_keys_for_row(row: Mapping[str, Any]) -> list[str]:
    turn_order = _row_true_turn_order(row) or "*"
    decision_kind = _row_decision_kind(row)
    suite_kind = _row_source_suite_kind(row)
    keys: list[str] = []
    if suite_kind:
        keys.extend(
            [
                f"{suite_kind}|{turn_order}|{decision_kind}",
                f"{suite_kind}|{turn_order}|*",
                f"{suite_kind}|*|{decision_kind}",
                f"{suite_kind}|*|*",
                f"*|{turn_order}|{decision_kind}",
                f"*|{turn_order}|*",
                f"*|*|{decision_kind}",
                "*|*|*",
            ]
        )
    keys.extend(
        [
        f"{turn_order}|{decision_kind}",
        f"{turn_order}|*",
        f"*|{decision_kind}",
        "*|*",
        ]
    )
    return keys


def _nested_scorer_dict(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("listwise composite scorer requires nested scorer mappings")
    if isinstance(value.get("model"), Mapping):
        return value["model"]
    return value


def _scorer_from_dict(data: Mapping[str, Any]) -> Any:
    model_version = str(data.get("modelVersion") or ACTION_SET_LISTWISE_MODEL_VERSION)
    if model_version == ACTION_SET_LISTWISE_MODEL_VERSION:
        return _validated_scorer(ActionSetListwiseScorer.from_dict(data), context=model_version)
    if model_version == ACTION_SET_LISTWISE_TRUE_TURN_ORDER_HYBRID_VERSION:
        return _validated_scorer(ActionSetTrueTurnOrderHybridScorer.from_dict(data), context=model_version)
    if model_version == ACTION_SET_LISTWISE_ROUTED_VERSION:
        return _validated_scorer(ActionSetRoutedListwiseScorer.from_dict(data), context=model_version)
    if model_version == ACTION_SET_LISTWISE_ADDITIVE_VERSION:
        return _validated_scorer(ActionSetAdditiveScorer.from_dict(data), context=model_version)
    if model_version == ACTION_SET_LISTWISE_GATED_ADDITIVE_VERSION:
        return _validated_scorer(ActionSetGatedAdditiveScorer.from_dict(data), context=model_version)
    try:
        from zz.action_set_training import PHASE_P_ACTION_VALUE_MODEL_VERSION, PhasePActionValueScorer
    except ImportError:  # pragma: no cover
        PHASE_P_ACTION_VALUE_MODEL_VERSION = ""
        PhasePActionValueScorer = None  # type: ignore[assignment]
    if model_version == PHASE_P_ACTION_VALUE_MODEL_VERSION and PhasePActionValueScorer is not None:
        return _validated_scorer(PhasePActionValueScorer.from_dict(data), context=model_version)
    try:
        from zz.action_set_ygo_policy import YGO_STYLE_ACTION_SET_POLICY_VERSION, YgoStyleActionSetPolicyScorer
    except ImportError:  # pragma: no cover
        YGO_STYLE_ACTION_SET_POLICY_VERSION = ""
        YgoStyleActionSetPolicyScorer = None  # type: ignore[assignment]
    if model_version == YGO_STYLE_ACTION_SET_POLICY_VERSION and YgoStyleActionSetPolicyScorer is not None:
        return _validated_scorer(YgoStyleActionSetPolicyScorer.from_dict(data), context=model_version)
    raise ValueError(f"unsupported listwise scorer modelVersion: {model_version!r}")


def _validated_scorer(scorer: Any, *, context: str) -> Any:
    validate_action_set_scorer_shape(scorer, context=context)
    return scorer


def _teacher_distribution(
    row: Mapping[str, Any],
    *,
    legal_slots: list[int],
    selected_slot: int,
    max_slots: int,
    temperature: float,
) -> tuple[list[float], bool]:
    out = [0.0 for _slot in range(max_slots)]
    teacher_scores = _score_slots(row.get("teacherScores"))
    legal_scores = [
        teacher_scores[slot]
        for slot in legal_slots
        if slot < len(teacher_scores) and teacher_scores[slot] is not None
    ]
    if len(legal_scores) >= 2 and max(legal_scores) > min(legal_scores):
        mean = sum(float(value) for value in legal_scores) / len(legal_scores)
        variance = sum((float(value) - mean) ** 2 for value in legal_scores) / len(legal_scores)
        scale = math.sqrt(variance) or 1.0
        logits = {
            slot: (float(teacher_scores[slot]) - mean) / scale / temperature
            for slot in legal_slots
            if slot < len(teacher_scores) and teacher_scores[slot] is not None
        }
        max_logit = max(logits.values())
        exps = {slot: math.exp(max(-60.0, min(60.0, value - max_logit))) for slot, value in logits.items()}
        total = sum(exps.values()) or 1.0
        for slot, value in exps.items():
            out[slot] = float(value / total)
        return out, True
    out[selected_slot] = 1.0
    return out, False


def object_action_slot_vector(row: Mapping[str, Any], slot: int) -> list[float]:
    values = _flat_action_slot_vector(row, slot)
    cards = _card_rows(row)
    if not cards:
        return values
    values.extend(_pooled_card_row(row, cards))
    values.extend(_card_row_for_action_ref(row, slot, cards, "action_ref:source_card_slot_norm"))
    values.extend(_card_row_for_action_ref(row, slot, cards, "action_ref:target_card_slot_norm"))
    return values


def _slot_vector(row: Mapping[str, Any], slot: int, *, input_dim: int, feature_mode: str = "flat") -> list[float]:
    if _normalize_feature_mode(feature_mode) == "object":
        values = object_action_slot_vector(row, slot)
    else:
        values = _flat_action_slot_vector(row, slot)
    if len(values) < input_dim:
        values.extend(0.0 for _index in range(input_dim - len(values)))
    return values[:input_dim]


def _slot_vector_length(row: Mapping[str, Any], *, feature_mode: str = "flat") -> int:
    legal_slots = _legal_slots(row)
    if not legal_slots:
        legal_slots = list(range(len(row.get("actions_") or [])))
    if not legal_slots:
        return len(_flat_action_slot_vector(row, 0))
    return max(
        len(object_action_slot_vector(row, slot))
        if _normalize_feature_mode(feature_mode) == "object"
        else len(_flat_action_slot_vector(row, slot))
        for slot in legal_slots
    )


def _flat_action_slot_vector(row: Mapping[str, Any], slot: int) -> list[float]:
    values = _float_list(row.get("global_"))
    actions = row.get("actions_") or []
    values.extend(_float_list(actions[slot] if 0 <= slot < len(actions) else []))
    return values


def _card_rows(row: Mapping[str, Any]) -> list[list[float]]:
    cards = row.get("cards_")
    if not isinstance(cards, list | tuple):
        return []
    return [_float_list(card_row) for card_row in cards if isinstance(card_row, list | tuple)]


def _pooled_card_row(row: Mapping[str, Any], cards: list[list[float]]) -> list[float]:
    width = max((len(card_row) for card_row in cards), default=0)
    if width <= 0:
        return []
    present_index = _feature_index(row.get("cardFeatureNames"), "card:present")
    present_rows = [
        _padded(card_row, width)
        for card_row in cards
        if present_index is None or (present_index < len(card_row) and float(card_row[present_index]) > 0.0)
    ]
    if not present_rows:
        return [0.0 for _index in range(width)]
    return [
        sum(float(card_row[index]) for card_row in present_rows) / len(present_rows)
        for index in range(width)
    ]


def _card_row_for_action_ref(
    row: Mapping[str, Any],
    slot: int,
    cards: list[list[float]],
    feature_name: str,
) -> list[float]:
    width = max((len(card_row) for card_row in cards), default=0)
    if width <= 0:
        return []
    action_feature_index = _feature_index(row.get("actionFeatureNames"), feature_name)
    if action_feature_index is None:
        return [0.0 for _index in range(width)]
    actions = row.get("actions_") or []
    action_values = _float_list(actions[slot] if 0 <= slot < len(actions) else [])
    if action_feature_index >= len(action_values):
        return [0.0 for _index in range(width)]
    card_slot = _decode_card_slot_norm(action_values[action_feature_index], max_cards=len(cards))
    if card_slot is None or card_slot >= len(cards):
        return [0.0 for _index in range(width)]
    return _padded(cards[card_slot], width)


def _decode_card_slot_norm(value: float, *, max_cards: int) -> int | None:
    if max_cards <= 0 or not math.isfinite(float(value)) or float(value) <= 0.0:
        return None
    slot = int(round(float(value) * max_cards)) - 1
    if slot < 0:
        return None
    return min(slot, max_cards - 1)


def _feature_index(names: Any, name: str) -> int | None:
    if not isinstance(names, list | tuple):
        return None
    try:
        return [str(item) for item in names].index(str(name))
    except ValueError:
        return None


def _padded(values: list[float], width: int) -> list[float]:
    out = list(values[:width])
    if len(out) < width:
        out.extend(0.0 for _index in range(width - len(out)))
    return out


def _normalize_feature_mode(value: Any) -> str:
    normalized = str(value or "flat").strip().lower()
    if normalized in {"object", "object_v1", "card_object", "card"}:
        return "object"
    return "flat"


def _mask(row: Mapping[str, Any]) -> list[bool]:
    value = row.get("mask_") or []
    if not isinstance(value, list | tuple):
        return []
    return [bool(item) for item in value]


def _legal_slots(row: Mapping[str, Any]) -> list[int]:
    return [slot for slot, enabled in enumerate(_mask(row)) if enabled]


def _selected_slot(row: Mapping[str, Any]) -> int | None:
    try:
        return int(row.get("selectedActionSlot"))
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _score_slots(value: Any) -> list[float | None]:
    if not isinstance(value, list | tuple):
        return []
    out: list[float | None] = []
    for item in value:
        if item is None:
            out.append(None)
            continue
        try:
            number = float(item)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(number if math.isfinite(number) else None)
    return out


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list | tuple):
        return []
    out: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            number = 0.0
        out.append(number if math.isfinite(number) else 0.0)
    return out
