from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from zz.card_slot_refs import decode_card_slot_norm as _shared_decode_card_slot_norm
from zz.enums import CardType


def play_card_target_semantics_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarise whether play_card rows carry enough source/target semantics."""

    try:
        import zz.decks  # noqa: F401 - populate CARD_REGISTRY for card metadata lookup
    except Exception:
        pass
    from zz.cards import CARD_REGISTRY

    totals: Counter[str] = Counter()
    by_decision: dict[str, Counter[str]] = {}
    unsafe_groups: set[tuple[str, str, str, str]] = set()
    target_missing_groups: set[tuple[str, str, str, str]] = set()

    for row in rows:
        decision = str(row.get("decisionKind") or "unknown")
        decision_counts = by_decision.setdefault(decision, Counter())
        row_has_unsafe_play_card_semantics = False
        row_has_missing_target_sensitive_play = False
        for action in _legal_action_records_for_semantic_audit(row):
            action_kind = str(action.get("kind") or "").strip()
            if action_kind == "choose_target":
                totals["genericTargetActions"] += 1
                decision_counts["genericTargetActions"] += 1
                continue
            if action_kind != "play_card":
                continue

            totals["playCardActions"] += 1
            decision_counts["playCardActions"] += 1
            card_id = _source_card_id_from_action(action)
            if card_id:
                totals["playCardSourceCardKnownActions"] += 1
                decision_counts["playCardSourceCardKnownActions"] += 1
            else:
                totals["playCardSourceCardUnknownActions"] += 1
                decision_counts["playCardSourceCardUnknownActions"] += 1
                row_has_unsafe_play_card_semantics = True
                continue

            card = CARD_REGISTRY.get(str(card_id))
            if card is None:
                totals["playCardSourceCardUnregisteredActions"] += 1
                decision_counts["playCardSourceCardUnregisteredActions"] += 1
                row_has_unsafe_play_card_semantics = True
                continue

            if not _card_requires_play_effect_target(card):
                continue

            totals["targetSensitivePlayCardActions"] += 1
            decision_counts["targetSensitivePlayCardActions"] += 1
            if getattr(card, "type", None) is CardType.MAGIC:
                totals["targetSensitiveMagicPlayCardActions"] += 1
                decision_counts["targetSensitiveMagicPlayCardActions"] += 1

            if _action_has_effect_target_payload(action):
                totals["targetSensitivePlayCardWithEffectTargetActions"] += 1
                decision_counts["targetSensitivePlayCardWithEffectTargetActions"] += 1
            else:
                totals["targetSensitivePlayCardMissingEffectTargetActions"] += 1
                decision_counts["targetSensitivePlayCardMissingEffectTargetActions"] += 1
                if getattr(card, "type", None) is CardType.MAGIC:
                    totals["targetSensitiveMagicPlayCardMissingEffectTargetActions"] += 1
                    decision_counts["targetSensitiveMagicPlayCardMissingEffectTargetActions"] += 1
                row_has_unsafe_play_card_semantics = True
                row_has_missing_target_sensitive_play = True

        if row_has_unsafe_play_card_semantics:
            totals["rowsWithUnsafePlayCardSemantics"] += 1
            decision_counts["rowsWithUnsafePlayCardSemantics"] += 1
            unsafe_groups.add(_semantic_state_group_key(row))
        if row_has_missing_target_sensitive_play:
            totals["rowsWithTargetSensitivePlayCardMissingEffectTarget"] += 1
            decision_counts["rowsWithTargetSensitivePlayCardMissingEffectTarget"] += 1
            target_missing_groups.add(_semantic_state_group_key(row))

    missing = int(totals.get("targetSensitivePlayCardMissingEffectTargetActions", 0))
    unknown_or_unregistered = int(totals.get("playCardSourceCardUnknownActions", 0)) + int(
        totals.get("playCardSourceCardUnregisteredActions", 0)
    )
    unsafe_group_count = len(unsafe_groups)
    reasons: list[str] = []
    if unknown_or_unregistered:
        reasons.append("play_card_source_card_unknown_or_unregistered")
    if missing:
        reasons.append("target_sensitive_play_card_missing_effect_target")
    return {
        "kind": "play_card_target_semantics_v1",
        "targetSemanticsGatePassed": missing == 0 and unknown_or_unregistered == 0 and unsafe_group_count == 0,
        "safeForTargetAwarePlayCardTraining": missing == 0 and unknown_or_unregistered == 0 and unsafe_group_count == 0,
        "requiresGenericTargetOrCompositeActionLabels": bool(missing),
        "unsafePlayCardSemanticsStateGroups": int(unsafe_group_count),
        "unsafePlayCardSemanticsRows": int(totals.get("rowsWithUnsafePlayCardSemantics", 0)),
        "unsafeTargetSensitivePlayCardStateGroups": int(len(target_missing_groups)),
        "unsafeTargetSensitivePlayCardRows": int(
            totals.get("rowsWithTargetSensitivePlayCardMissingEffectTarget", 0)
        ),
        "totals": _sorted_counter(totals),
        "byDecisionKind": {
            key: _sorted_counter(counter)
            for key, counter in sorted(by_decision.items())
        },
        "blockingReasons": reasons,
    }


def assert_play_card_target_semantics_safe(
    rows: Iterable[Mapping[str, Any]],
    *,
    allow_missing_target_semantics: bool = False,
) -> dict[str, Any]:
    report = play_card_target_semantics_from_rows(rows)
    if (
        not bool(allow_missing_target_semantics)
        and not bool(report.get("targetSemanticsGatePassed"))
    ):
        raise ValueError(
            "target-sensitive play_card rows are missing effect target semantics; "
            "collect generic_target/composite action-value labels or pass an explicit diagnostic opt-in"
        )
    return report


def target_action_semantics_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarise whether explicit target-choice rows encode target objects as targets."""

    totals: Counter[str] = Counter()
    by_decision: dict[str, Counter[str]] = {}
    unsafe_groups: set[tuple[str, str, str, str]] = set()

    for row in rows:
        decision = str(row.get("decisionKind") or "unknown")
        decision_counts = by_decision.setdefault(decision, Counter())
        row_has_unsafe_target_action = False
        for slot, action in _legal_action_records_with_slots_for_semantic_audit(row):
            action_kind = str(action.get("kind") or "").strip()
            source_fields, target_fields = _target_action_card_ref_fields(action_kind)
            if not source_fields and not target_fields:
                continue
            totals["targetActions"] += 1
            decision_counts["targetActions"] += 1
            has_source_card = _action_has_card_payload_for_fields(action, source_fields)
            has_target_card = _action_has_card_payload_for_fields(action, target_fields)
            if not has_source_card and not has_target_card:
                totals["nonCardTargetActions"] += 1
                decision_counts["nonCardTargetActions"] += 1
                continue
            source_ref = _action_feature_value(row, slot, "action_ref:source_card_slot_norm")
            target_ref = _action_feature_value(row, slot, "action_ref:target_card_slot_norm")

            if has_source_card:
                totals["sourceCardActions"] += 1
                decision_counts["sourceCardActions"] += 1
                if source_ref > 0.0:
                    totals["sourceActionsWithSourceRef"] += 1
                    decision_counts["sourceActionsWithSourceRef"] += 1
                    source_owner_status = _card_ref_owner_semantics_status(
                        row,
                        source_ref,
                        action,
                        source_fields,
                    )
                    if source_owner_status == "known":
                        totals["sourceActionsWithKnownSourceOwner"] += 1
                        decision_counts["sourceActionsWithKnownSourceOwner"] += 1
                    else:
                        _record_target_semantics_owner_failure(
                            totals,
                            decision_counts,
                            prefix="source",
                            status=source_owner_status,
                        )
                        row_has_unsafe_target_action = True
                elif target_ref > 0.0:
                    totals["sourceActionsEncodedAsTargetRef"] += 1
                    decision_counts["sourceActionsEncodedAsTargetRef"] += 1
                    row_has_unsafe_target_action = True
                else:
                    totals["sourceActionsMissingSourceRef"] += 1
                    decision_counts["sourceActionsMissingSourceRef"] += 1
                    row_has_unsafe_target_action = True

            if has_target_card:
                totals["cardTargetActions"] += 1
                decision_counts["cardTargetActions"] += 1
                if target_ref > 0.0:
                    totals["targetActionsWithTargetRef"] += 1
                    decision_counts["targetActionsWithTargetRef"] += 1
                    target_owner_status = _card_ref_owner_semantics_status(
                        row,
                        target_ref,
                        action,
                        target_fields,
                    )
                    if target_owner_status == "known":
                        totals["targetActionsWithKnownTargetOwner"] += 1
                        decision_counts["targetActionsWithKnownTargetOwner"] += 1
                    else:
                        _record_target_semantics_owner_failure(
                            totals,
                            decision_counts,
                            prefix="target",
                            status=target_owner_status,
                        )
                        row_has_unsafe_target_action = True
                    continue
                if source_ref > 0.0 and not has_source_card:
                    totals["targetActionsEncodedAsSourceRef"] += 1
                    decision_counts["targetActionsEncodedAsSourceRef"] += 1
                else:
                    totals["targetActionsMissingTargetRef"] += 1
                    decision_counts["targetActionsMissingTargetRef"] += 1
                row_has_unsafe_target_action = True
        if row_has_unsafe_target_action:
            totals["rowsWithUnsafeTargetActionSemantics"] += 1
            decision_counts["rowsWithUnsafeTargetActionSemantics"] += 1
            unsafe_groups.add(_semantic_state_group_key(row))

    reasons: list[str] = []
    if totals.get("targetActionsEncodedAsSourceRef", 0):
        reasons.append("target_action_encoded_as_source_ref")
    if totals.get("targetActionsMissingTargetRef", 0):
        reasons.append("target_action_missing_target_ref")
    if totals.get("targetActionsMissingTargetOwner", 0):
        reasons.append("target_action_missing_target_owner")
    if totals.get("targetActionsMissingModelSide", 0):
        reasons.append("target_action_missing_model_side")
    if totals.get("targetActionsMismatchedTargetOwner", 0):
        reasons.append("target_action_mismatched_target_owner")
    if totals.get("sourceActionsEncodedAsTargetRef", 0):
        reasons.append("source_action_encoded_as_target_ref")
    if totals.get("sourceActionsMissingSourceRef", 0):
        reasons.append("source_action_missing_source_ref")
    if totals.get("sourceActionsMissingSourceOwner", 0):
        reasons.append("source_action_missing_source_owner")
    if totals.get("sourceActionsMissingModelSide", 0):
        reasons.append("source_action_missing_model_side")
    if totals.get("sourceActionsMismatchedSourceOwner", 0):
        reasons.append("source_action_mismatched_source_owner")
    return {
        "kind": "target_action_semantics_v1",
        "targetActionSemanticsGatePassed": not reasons and len(unsafe_groups) == 0,
        "safeForTargetActionTraining": not reasons and len(unsafe_groups) == 0,
        "unsafeTargetActionStateGroups": int(len(unsafe_groups)),
        "unsafeTargetActionRows": int(totals.get("rowsWithUnsafeTargetActionSemantics", 0)),
        "totals": _sorted_counter(totals),
        "byDecisionKind": {
            key: _sorted_counter(counter)
            for key, counter in sorted(by_decision.items())
        },
        "blockingReasons": reasons,
    }


def assert_target_action_semantics_safe(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    report = target_action_semantics_from_rows(rows)
    if not bool(report.get("targetActionSemanticsGatePassed")):
        raise ValueError(
            "target-choice rows encode card targets without target-ref/owner semantics; "
            "regenerate with action_ref target semantics before training"
        )
    return report


def force_or_combo_context_from_row(row: Mapping[str, Any]) -> dict[str, bool]:
    """Return compact context flags for force/combo-sensitive action-value rows."""

    global_names = [str(name).lower() for name in list(row.get("globalFeatureNames") or [])]
    action_names = [str(name).lower() for name in list(row.get("actionFeatureNames") or [])]
    global_values = _float_list(row.get("global_"))
    action_rows = row.get("actions_")

    force_feature = False
    force_pressure_feature = False
    combo_feature = False
    force_action_feature = False

    for index, name in enumerate(global_names):
        if not _nonzero_at(global_values, index):
            continue
        if "combo" in name:
            combo_feature = True
        if "force" not in name:
            continue
        force_feature = True
        if "force_broken" in name or "force_low_life" in name:
            force_pressure_feature = True

    if isinstance(action_rows, list):
        for action_row in action_rows:
            values = _float_list(action_row)
            for index, name in enumerate(action_names):
                if not _nonzero_at(values, index):
                    continue
                if "combo" in name:
                    combo_feature = True
                if "force" not in name:
                    continue
                force_feature = True
                if _is_force_action_context_name(name):
                    force_action_feature = True

    return {
        "forceFeature": bool(force_feature),
        "forcePressureFeature": bool(force_pressure_feature),
        "forceActionFeature": bool(force_action_feature),
        "comboFeature": bool(combo_feature),
        "forceOrComboContext": bool(force_pressure_feature or force_action_feature or combo_feature),
    }


def row_has_force_or_combo_context(row: Mapping[str, Any]) -> bool:
    context = force_or_combo_context_from_row(row)
    return bool(context.get("forceOrComboContext"))


def row_has_force_features(row: Mapping[str, Any]) -> bool:
    context = force_or_combo_context_from_row(row)
    return bool(context.get("forceFeature") or context.get("comboFeature"))


def label_has_force_or_combo_context(label: Mapping[str, Any]) -> bool:
    combo_tags = label.get("comboTags")
    if label.get("forceStateBefore") or label.get("forceStateAfter"):
        return True
    if isinstance(combo_tags, list) and combo_tags:
        return True
    context = label.get("forceOrComboContext")
    if isinstance(context, bool):
        return bool(context)
    if isinstance(context, Mapping):
        return bool(
            context.get("forceOrComboContext")
            or context.get("forcePressureFeature")
            or context.get("forceActionFeature")
            or context.get("comboFeature")
        )
    return False


def attach_force_or_combo_context_label(label: dict[str, Any], row: Mapping[str, Any]) -> None:
    context = force_or_combo_context_from_row(row)
    if context.get("forceOrComboContext"):
        label["forceOrComboContext"] = context


def _is_force_action_context_name(name: str) -> bool:
    return (
        "target_force" in name
        or "target_kind_force" in name
        or "force_target" in name
        or "block_preserves_life_or_force" in name
        or "no_block_force_exposed" in name
    )


def _legal_action_records_for_semantic_audit(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [action for _slot, action in _legal_action_records_with_slots_for_semantic_audit(row)]


def _legal_action_records_with_slots_for_semantic_audit(row: Mapping[str, Any]) -> list[tuple[int, Mapping[str, Any]]]:
    actions = row.get("actions")
    if isinstance(actions, list | tuple):
        mask = row.get("mask_")
        legal_count = _optional_int(row.get("legalCount"))
        out: list[tuple[int, Mapping[str, Any]]] = []
        for index, action in enumerate(actions):
            if legal_count is not None and index >= legal_count:
                break
            if isinstance(mask, list | tuple) and index < len(mask) and not bool(mask[index]):
                continue
            if isinstance(action, Mapping):
                out.append((index, action))
        return out
    action = row.get("action")
    if isinstance(action, Mapping):
        slot = _optional_int(row.get("actionSlot"))
        return [(0 if slot is None else int(slot), action)]
    return []


def _source_card_id_from_action(action: Mapping[str, Any]) -> str | None:
    for payload in _payload_mappings_for_action(action):
        for key in ("card_id", "cardId", "source_card_id", "sourceCardId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("iid", "source_iid", "source_card_iid"):
            card_id = _nested_card_id(payload.get(key))
            if card_id:
                return card_id
    return None


def _action_has_effect_target_payload(action: Mapping[str, Any]) -> bool:
    target_fields = (
        "effect_target",
        "effect_target_iid",
        "effect_target_card_iid",
        "effect_targets",
        "effect_target_iids",
        "target",
        "target_iid",
        "target_card_iid",
        "targets",
        "target_iids",
        "target_card_iids",
    )
    for payload in _payload_mappings_for_action(action):
        for key in target_fields:
            value = payload.get(key)
            if _payload_has_value(value):
                return True
    return False


def _payload_mappings_for_action(action: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    payload = action.get("payload")
    if isinstance(payload, Mapping):
        out.append(payload)
    signature = action.get("signature")
    if isinstance(signature, Mapping):
        signature_payload = signature.get("payload")
        if isinstance(signature_payload, Mapping):
            out.append(signature_payload)
    return out


def _nested_card_id(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("cardId", "card_id", "sourceCardId", "source_card_id", "targetCardId", "target_card_id"):
        card_id = value.get(key)
        if isinstance(card_id, str) and card_id.strip():
            return card_id.strip()
    return None


def _payload_has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, list | tuple | set):
        return bool(value)
    return True


def _target_action_card_ref_fields(action_kind: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if action_kind == "choose_target":
        return (
            ("source_iid", "source_card_iid", "source"),
            ("target_iid", "target_card_iid", "target", "iid"),
        )
    if action_kind == "choose_attack_target":
        return (
            ("attacker_iid", "attacker", "source_iid", "source_card_iid", "source"),
            ("target_iid", "target_card_iid", "target", "iid"),
        )
    if action_kind in {"choose_blocker", "block"}:
        return (
            ("blocker_iid", "blocker", "iid", "source_iid", "source_card_iid"),
            ("attacker_iid", "attacker", "target_iid", "target_card_iid", "target"),
        )
    if action_kind == "no_block":
        return (
            (),
            ("attacker_iid", "attacker", "target_iid", "target_card_iid", "target"),
        )
    return (), ()


def _action_has_card_payload_for_fields(action: Mapping[str, Any], fields: tuple[str, ...]) -> bool:
    if not fields:
        return False
    for payload in _payload_mappings_for_action(action):
        for key in fields:
            value = payload.get(key)
            if _payload_has_value(value):
                return True
    return False


def _action_payload_owner_for_fields(action: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for payload in _payload_mappings_for_action(action):
        for key in fields:
            value = payload.get(key)
            if isinstance(value, Mapping) and str(value.get("owner") or "").strip():
                return str(value.get("owner") or "").strip()
    return ""


def _card_ref_owner_semantics_status(
    row: Mapping[str, Any],
    ref_value: float,
    action: Mapping[str, Any],
    fields: tuple[str, ...],
) -> str:
    owner_flags = _card_ref_owner_flags(row, ref_value)
    payload_owner = _normalise_player_side(_action_payload_owner_for_fields(action, fields))
    model_side = _normalise_player_side(_row_model_side(row))
    if payload_owner and not model_side:
        return "missing_model_side"
    if payload_owner and model_side and owner_flags is not None:
        expected_self = payload_owner == model_side
        if bool(owner_flags["self"]) != bool(expected_self):
            return "mismatched_owner"
        return "known"
    if owner_flags is not None and model_side:
        return "known"
    if owner_flags is not None and not model_side:
        return "missing_model_side"
    return "missing_owner"


def _record_target_semantics_owner_failure(
    totals: Counter[str],
    decision_counts: Counter[str],
    *,
    prefix: str,
    status: str,
) -> None:
    label = "Target" if prefix == "target" else "Source"
    if status == "missing_model_side":
        key = f"{prefix}ActionsMissingModelSide"
    elif status == "mismatched_owner":
        key = f"{prefix}ActionsMismatched{label}Owner"
    else:
        key = f"{prefix}ActionsMissing{label}Owner"
    totals[key] += 1
    decision_counts[key] += 1


def _card_ref_owner_flags(row: Mapping[str, Any], ref_value: float) -> dict[str, bool] | None:
    cards = row.get("cards_")
    if not isinstance(cards, list | tuple) or not cards:
        return None
    slot = _decode_card_slot_norm(ref_value, max_cards=len(cards))
    if slot is None or slot < 0 or slot >= len(cards):
        return None
    names = [str(name) for name in list(row.get("cardFeatureNames") or [])]
    try:
        self_index = names.index("card:owner_self")
        opponent_index = names.index("card:owner_opponent")
    except ValueError:
        return None
    values = _float_list(cards[slot])
    owner_self = self_index < len(values) and values[self_index] > 0.0
    owner_opponent = opponent_index < len(values) and values[opponent_index] > 0.0
    if owner_self == owner_opponent:
        return None
    return {"self": bool(owner_self), "opponent": bool(owner_opponent)}


def _row_model_side(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    return str(row.get("modelSide") or metadata.get("modelSide") or "")


def _normalise_player_side(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"P1", "SIDE.P1"}:
        return "P1"
    if text in {"P2", "SIDE.P2"}:
        return "P2"
    return ""


def _action_feature_value(row: Mapping[str, Any], slot: int, feature_name: str) -> float:
    names = [str(name) for name in list(row.get("actionFeatureNames") or [])]
    try:
        index = names.index(str(feature_name))
    except ValueError:
        return 0.0
    action_rows = row.get("actions_")
    if not isinstance(action_rows, list | tuple) or slot < 0 or slot >= len(action_rows):
        return 0.0
    values = _float_list(action_rows[slot])
    if index >= len(values):
        return 0.0
    return float(values[index])


def _decode_card_slot_norm(value: float, *, max_cards: int) -> int | None:
    return _shared_decode_card_slot_norm(value, max_cards=max_cards)


def _card_requires_play_effect_target(card: Any) -> bool:
    for effect in getattr(card, "effects", []) or []:
        if getattr(effect, "target_kind", None):
            return True
    return False


def _semantic_state_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    metadata = row.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}
    return (
        str(row.get("runId") or metadata_map.get("runId") or "unknown-run"),
        str(row.get("stateKey") or "unknown-state"),
        str(row.get("decisionKind") or "unknown"),
        str(metadata_map.get("fullLegalActionSetGroupId") or ""),
    )


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return {key: int(counter[key]) for key in sorted(counter)}


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def _nonzero_at(values: list[float], index: int) -> bool:
    return index < len(values) and abs(float(values[index])) > 1.0e-9
