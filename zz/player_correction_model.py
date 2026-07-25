"""Lightweight correction model trained on player preference pairs.

Uses ONLY existing feature vocabulary. Completely separate from the
baseline model — training can't damage the baseline. At inference,
the correction score is added to the baseline score.

Supports both linear (logistic regression) and MLP (2-layer) variants.
The MLP can learn feature interactions that the linear model misses.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


class PlayerCorrectionModel:
    """Linear model that scores actions based on player preferences.

    Weights are learned from preference pairs. At inference, score(features)
    returns a value in roughly [-2, +2] range that can flip small baseline
    margins without dominating strong preferences.
    """

    def __init__(self, seed: int = 42, *, hidden_size: int = 0) -> None:
        self.weights: dict[str, float] = {}
        self.bias: float = 0.0
        self.hidden_size: int = max(0, int(hidden_size))
        # MLP parameters (only when hidden_size > 0)
        self.W1: dict[tuple[int, str], float] = {}  # (neuron, feature) -> weight
        self.b1: list[float] = []  # hidden biases
        self.W2: list[float] = []  # output weights
        self.b2: float = 0.0  # output bias
        self._rng = random.Random(seed)

    @property
    def is_mlp(self) -> bool:
        return self.hidden_size > 0

    # ── scoring ──────────────────────────────────────────────────

    def score(self, features: dict[str, float]) -> float:
        """Return the correction score for this feature dict."""
        if not self.is_mlp:
            total = self.bias
            for key, value in features.items():
                w = self.weights.get(key, 0.0)
                if w != 0.0 and value != 0.0:
                    total += w * float(value)
            return float(total)

        # MLP forward pass
        hidden = [0.0] * self.hidden_size
        for i in range(self.hidden_size):
            s = self.b1[i] if i < len(self.b1) else 0.0
            for key, value in features.items():
                if float(value) == 0.0:
                    continue
                w = self.W1.get((i, key), 0.0)
                if w != 0.0:
                    s += w * float(value)
            hidden[i] = max(0.0, s)  # ReLU
        total = self.b2
        for i, h in enumerate(hidden):
            if i < len(self.W2):
                total += self.W2[i] * h
        return float(total)

    # ── training ─────────────────────────────────────────────────

    def train(
        self,
        pairs: list[dict[str, Any]],
        *,
        epochs: int = 50,
        learning_rate: float = 0.05,
        l2_penalty: float = 0.001,
    ) -> dict[str, Any]:
        """Train on preference pairs using SGD.

        Each pair has ``goodFeatures`` (target +1) and ``badFeatures`` (target -1).
        """
        # Initialize MLP parameters if needed
        if self.is_mlp and not self.b1:
            self.b1 = [self._rng.uniform(-0.01, 0.01) for _ in range(self.hidden_size)]
            self.W2 = [self._rng.uniform(-0.01, 0.01) for _ in range(self.hidden_size)]
            self.b2 = 0.0

        initial_loss = self._pair_loss(pairs)
        updates: list[float] = []

        for epoch in range(epochs):
            shuffled = list(pairs)
            self._rng.shuffle(shuffled)
            total_loss = 0.0
            for pair in shuffled:
                good = dict(pair.get("goodFeatures") or {})
                bad = dict(pair.get("badFeatures") or {})
                # Positive example
                pred_good = self.score(good)
                error_good = 1.0 - pred_good  # want score → +1
                self._sgd_update(good, error_good, learning_rate, l2_penalty)
                # Negative example
                pred_bad = self.score(bad)
                error_bad = -1.0 - pred_bad  # want score → -1
                self._sgd_update(bad, error_bad, learning_rate, l2_penalty)
                total_loss += error_good ** 2 + error_bad ** 2
            avg_loss = total_loss / max(1, 2 * len(shuffled))
            updates.append(avg_loss)
            # Decay learning rate
            learning_rate *= 0.99

        final_loss = self._pair_loss(pairs)
        return {
            "pairCount": len(pairs),
            "epochs": epochs,
            "initialMeanLoss": initial_loss,
            "finalMeanLoss": final_loss,
            "featureCount": len(self.weights),
            "updates": updates,
        }

    def _sgd_update(
        self,
        features: dict[str, float],
        error: float,
        lr: float,
        l2: float,
    ) -> None:
        """Single SGD step for one example, with gradient clipping."""
        # Clip error to prevent explosion
        error = max(-10.0, min(10.0, error))
        n_features = max(1, sum(1 for v in features.values() if float(v) != 0.0))
        effective_lr = lr / n_features  # normalize by active feature count

        if not self.is_mlp:
            for key, value in features.items():
                if float(value) == 0.0:
                    continue
                old_w = self.weights.get(key, 0.0)
                gradient = -2.0 * error * float(value) + 2.0 * l2 * old_w
                gradient = max(-1.0, min(1.0, gradient))
                new_w = old_w - effective_lr * gradient
                if abs(new_w) < 1e-8:
                    if key in self.weights:
                        del self.weights[key]
                else:
                    self.weights[key] = new_w
            bias_grad = max(-1.0, min(1.0, -2.0 * error))
            self.bias = self.bias - effective_lr * bias_grad
            return

        # MLP update
        # Forward pass to get hidden activations
        hidden = [0.0] * self.hidden_size
        hidden_pre_activation = [0.0] * self.hidden_size
        for i in range(self.hidden_size):
            s = self.b1[i] if i < len(self.b1) else 0.0
            for key, value in features.items():
                if float(value) == 0.0:
                    continue
                w = self.W1.get((i, key), 0.0)
                if w != 0.0:
                    s += w * float(value)
            hidden_pre_activation[i] = s
            hidden[i] = max(0.0, s)  # ReLU

        # Output gradient
        output_grad = -2.0 * error
        output_grad = max(-1.0, min(1.0, output_grad))

        # Update W2 and b2
        for i in range(min(self.hidden_size, len(self.W2))):
            self.W2[i] = self.W2[i] - effective_lr * (output_grad * hidden[i] + 2.0 * l2 * self.W2[i])
        self.b2 = self.b2 - effective_lr * output_grad

        # Update W1 and b1 (backprop through ReLU)
        for i in range(self.hidden_size):
            if hidden_pre_activation[i] <= 0.0:
                continue  # ReLU gradient is 0
            neuron_grad = output_grad * (self.W2[i] if i < len(self.W2) else 0.0)
            neuron_grad = max(-1.0, min(1.0, neuron_grad))
            # Update b1
            if i < len(self.b1):
                self.b1[i] = self.b1[i] - effective_lr * neuron_grad
            # Update W1
            for key, value in features.items():
                if float(value) == 0.0:
                    continue
                old_w = self.W1.get((i, key), 0.0)
                grad = neuron_grad * float(value) + 2.0 * l2 * old_w
                new_w = old_w - effective_lr * grad
                if abs(new_w) < 1e-8:
                    self.W1.pop((i, key), None)
                else:
                    self.W1[(i, key)] = new_w

    def _pair_loss(self, pairs: list[dict[str, Any]]) -> float:
        """Mean squared error across all pairs."""
        if not pairs:
            return 0.0
        total = 0.0
        for pair in pairs:
            good = pair.get("goodFeatures") or {}
            bad = pair.get("badFeatures") or {}
            total += (1.0 - self.score(good)) ** 2
            total += (-1.0 - self.score(bad)) ** 2
        return total / (2 * len(pairs))

    # ── serialization ────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Save model weights to a JSON file."""
        data: dict[str, Any] = {
            "weights": self.weights,
            "bias": self.bias,
            "hidden_size": self.hidden_size,
        }
        if self.is_mlp:
            # Convert tuple keys to strings for JSON
            data["W1"] = {f"{i}:{k}": v for (i, k), v in self.W1.items()}
            data["b1"] = self.b1
            data["W2"] = self.W2
            data["b2"] = self.b2
        Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> PlayerCorrectionModel:
        """Load model weights from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        hidden_size = int(data.get("hidden_size") or 0)
        model = cls(hidden_size=hidden_size)
        model.weights = dict(data.get("weights") or {})
        model.bias = float(data.get("bias", 0.0))
        if hidden_size > 0:
            model.W1 = {(int(k.split(":")[0]), k.split(":", 1)[1]): float(v)
                        for k, v in (data.get("W1") or {}).items()}
            model.b1 = [float(v) for v in (data.get("b1") or [])]
            model.W2 = [float(v) for v in (data.get("W2") or [])]
            model.b2 = float(data.get("b2", 0.0))
        return model


def train_player_correction_model(
    model: PlayerCorrectionModel | None = None,
    pairs: list[dict[str, Any]] | None = None,
    *,
    epochs: int = 50,
    learning_rate: float = 0.05,
    l2_penalty: float = 0.001,
    seed: int = 42,
) -> dict[str, Any]:
    """Train a PlayerCorrectionModel on preference pairs.

    Convenience wrapper around ``PlayerCorrectionModel.train()``.
    """
    if model is None:
        model = PlayerCorrectionModel(seed=seed)
    return model.train(
        list(pairs or []),
        epochs=epochs,
        learning_rate=learning_rate,
        l2_penalty=l2_penalty,
    )
