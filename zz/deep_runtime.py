from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class NumpyActionValueModel:
    """Inference-only runtime for the exported public deep model."""

    vectorizer_size: int
    hidden_size: int
    input_weight: np.ndarray
    input_bias: np.ndarray
    output_weight: np.ndarray
    output_bias: np.ndarray
    metadata: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "NumpyActionValueModel":
        with np.load(Path(path), allow_pickle=False) as data:
            format_version = int(np.asarray(data["format_version"]).item())
            if format_version != 1:
                raise ValueError(f"unsupported deep runtime model format: {format_version}")
            vectorizer_size = int(np.asarray(data["vectorizer_size"]).item())
            hidden_size = int(np.asarray(data["hidden_size"]).item())
            try:
                metadata = json.loads(str(np.asarray(data["metadata_json"]).item()))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("invalid deep runtime model metadata") from exc
            if not isinstance(metadata, dict):
                raise ValueError("deep runtime model metadata must be an object")
            model = cls(
                vectorizer_size=vectorizer_size,
                hidden_size=hidden_size,
                input_weight=np.asarray(data["input_weight"], dtype=np.float32),
                input_bias=np.asarray(data["input_bias"], dtype=np.float32),
                output_weight=np.asarray(data["output_weight"], dtype=np.float32),
                output_bias=np.asarray(data["output_bias"], dtype=np.float32),
                metadata=metadata,
            )
        model._validate_shapes()
        return model

    @property
    def has_multitask_heads(self) -> bool:
        return False

    @property
    def has_public_deep_v2_architecture(self) -> bool:
        return False

    def score_many(self, feature_rows: list[dict[str, float]]) -> list[float]:
        if not feature_rows:
            return []
        batch = self._vectorize(feature_rows)
        hidden = batch @ self.input_weight.T + self.input_bias
        np.maximum(hidden, 0.0, out=hidden)
        scores = hidden @ self.output_weight.T + self.output_bias
        return [float(value) for value in scores[:, 0].tolist()]

    def score(self, features: dict[str, float]) -> float:
        return self.score_many([features])[0]

    def _vectorize(self, feature_rows: list[dict[str, float]]) -> np.ndarray:
        batch = np.zeros((len(feature_rows), self.vectorizer_size), dtype=np.float32)
        for row_index, features in enumerate(feature_rows):
            for name, value in features.items():
                if not value:
                    continue
                digest = hashlib.blake2b(str(name).encode("utf-8"), digest_size=8).digest()
                feature_index = int.from_bytes(digest, "little") % self.vectorizer_size
                batch[row_index, feature_index] += float(value)
        return batch

    def _validate_shapes(self) -> None:
        expected = {
            "input_weight": (self.hidden_size, self.vectorizer_size),
            "input_bias": (self.hidden_size,),
            "output_weight": (1, self.hidden_size),
            "output_bias": (1,),
        }
        for name, shape in expected.items():
            actual = tuple(getattr(self, name).shape)
            if actual != shape:
                raise ValueError(
                    f"invalid deep runtime model {name} shape: expected {shape}, got {actual}"
                )
