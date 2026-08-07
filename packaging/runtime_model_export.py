from __future__ import annotations

import json
from pathlib import Path


def export_deep_runtime_model(source: Path, destination: Path) -> None:
    """Export the public deep checkpoint to a Torch-free inference artifact."""
    import numpy as np
    import torch

    payload = torch.load(source, map_location="cpu", weights_only=False)
    if payload.get("kind") != "torch_action_value":
        raise ValueError(f"unsupported deep model kind: {payload.get('kind')!r}")
    if payload.get("multitaskHeads") is not None or payload.get("publicDeepV2Architecture") is not None:
        raise ValueError("the current inference-only exporter does not support auxiliary deep heads")
    state_dict = payload.get("stateDict")
    required_keys = {"0.weight", "0.bias", "2.weight", "2.bias"}
    if not isinstance(state_dict, dict) or set(state_dict) != required_keys:
        raise ValueError("deep model state dictionary does not match the supported runtime architecture")
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        format_version=np.asarray(1, dtype=np.int64),
        vectorizer_size=np.asarray(int(payload["vectorizerSize"]), dtype=np.int64),
        hidden_size=np.asarray(int(payload["hiddenSize"]), dtype=np.int64),
        input_weight=state_dict["0.weight"].detach().cpu().numpy().astype(np.float32),
        input_bias=state_dict["0.bias"].detach().cpu().numpy().astype(np.float32),
        output_weight=state_dict["2.weight"].detach().cpu().numpy().astype(np.float32),
        output_bias=state_dict["2.bias"].detach().cpu().numpy().astype(np.float32),
        metadata_json=np.asarray(json.dumps(payload.get("metadata") or {}, ensure_ascii=True)),
    )
