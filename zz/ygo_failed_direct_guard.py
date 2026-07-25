from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


REJECTED_DIRECT_YGO_MODEL_MARKERS = (
    "self_improvement_pilot_ygo_style_direct_phase_v144_v135_action_set_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v145_v135_top1_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v147_v49_anchor_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v149_v49_clone_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v151_v49_history_clone_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v154_large_o2_v130_player_trace_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v159_v154_plus_flashpass_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v176_forceaware_anchor_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v185_v159_plus_v184_failure_value_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v187_v159_v49_anchor_v184_failure_value_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v192_actioncard_signature_v1",
    "self_improvement_pilot_ygo_style_phase_v199_outcome_second_top_ai_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v243_action_value_v238_strongmainanchor_from_v192_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v262_v259_value_distribution_fullanchor_from_v192_v1",
    "self_improvement_pilot_ygo_style_outcome_policy_phase_v276_v273_from_v192_v1",
    "self_improvement_pilot_ygo_style_outcome_policy_phase_v280_v276_plus_v278_second_top_ai_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v283_t49_selected_distill_from_v192_v1",
    "self_improvement_pilot_ygo_style_outcome_policy_phase_v287_t61_centered_from_v192_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v291_v289_t49_selected_fullschema_from_v192_v1",
    "self_improvement_pilot_ygo_style_direct_phase_v293_v289_t49_score_distribution_from_v291_v1",
    "self_improvement_pilot_ygo_style_outcome_policy_phase_v295_v290_fullschema_centered_from_v291_v1",
    "phase_v144_direct_ygo_policy",
    "phase_v145_direct_ygo_policy",
    "phase_v147_direct_ygo_policy",
    "phase_v149_direct_ygo_policy",
    "phase_v151_direct_ygo_policy",
    "phase_v154_direct_ygo_policy",
    "phase_v159_direct_ygo_policy_v154_plus_flashpass",
    "phase_v176_direct_ygo_policy_forceaware_anchor",
    "phase_v185_direct_ygo_policy_v159_plus_v184_failure_value",
    "phase_v187_direct_ygo_policy_v159_plus_v49_anchor_v184_failure_value",
    "phase_v192_direct_ygo_policy_actioncard_signature",
    "phase_v199_ygo_pairwise_outcome_second_top_ai",
    "phase_v243_direct_ygo_policy_action_value",
    "phase_v262_direct_ygo_policy_v259_value_distribution_fullanchor",
    "phase_v276_ygo_outcome_policy_v273_from_v192",
    "phase_v280_ygo_outcome_policy_v276_plus_v278_second_top_ai",
    "phase_v283_direct_ygo_policy_t49_selected_distill_from_v192",
    "phase_v287_ygo_outcome_policy_t61_centered_from_v192",
    "phase_v291_direct_ygo_policy_v289_t49_selected_fullschema",
    "phase_v293_direct_ygo_policy_v289_t49_score_distribution",
    "phase_v295_ygo_outcome_policy_v290_fullschema",
)


def reject_rejected_direct_ygo_model(
    *,
    path: str | Path,
    data: Mapping[str, Any],
    usage_label: str,
) -> None:
    payload = " ".join(
        str(value)
        for value in (
            Path(path).as_posix(),
            data.get("modelId"),
            data.get("baseModelId"),
            data.get("baseModelPath"),
            data.get("sourcePolicyId"),
            data.get("policyId"),
        )
        if value is not None
    )
    for marker in REJECTED_DIRECT_YGO_MODEL_MARKERS:
        if marker in payload:
            raise ValueError(f"rejected direct ygo {usage_label} is not allowed: {marker}")
