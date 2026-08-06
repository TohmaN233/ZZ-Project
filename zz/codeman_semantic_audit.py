from __future__ import annotations

import json
from pathlib import Path
import random
from typing import Any, Mapping

import zz.decks  # noqa: F401 - populate the complete runtime card registry
from zz.cards import CARD_REGISTRY
from zz.engine import Engine
from zz.effects import EffectTiming
from zz.enums import AreaType, Side, Step, TriggerTiming
from zz.forces import F_MINOTAUROS
from zz.model import Action, CardInstance, ForceInstance, GameState, Player
from zz.rl_ai import FeatureExtractor, semantic_ai_action_rejection_reason, semantically_admissible_main_actions


def audit_codeman_trace(
    trace: Mapping[str, Any],
    *,
    source: str = "",
    early_turn_max: int = 3,
) -> dict[str, Any]:
    player_side = str(trace.get("playerSide") or "").strip().upper()
    if player_side not in {"P1", "P2"}:
        raise ValueError(f"Codeman trace has invalid playerSide: {player_side!r}")
    codeman_side = "P2" if player_side == "P1" else "P1"
    events = trace.get("logEvents")
    if not isinstance(events, list):
        raise ValueError("Codeman trace logEvents must be a list")

    violations: list[dict[str, Any]] = []
    suspicious_moves: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping) or str(event.get("actorSide") or "") != codeman_side:
            continue
        if event.get("type") == "attack_target":
            attacker = event.get("attacker")
            if not isinstance(attacker, Mapping):
                raise ValueError("Codeman attack_target event is missing attacker data")
            effective_dp = int(attacker.get("effectiveDp", attacker.get("dp", 0)) or 0)
            card_id = str(attacker.get("cardId") or "")
            if effective_dp <= 0 and not _card_has_attack_payoff(card_id):
                violations.append(_finding(event, attacker, "zero_dp_attack_without_payoff"))
            continue
        if event.get("type") != "action" or event.get("actionKind") != "move_card":
            continue
        action = event.get("action")
        payload = action.get("payload") if isinstance(action, Mapping) else None
        if not isinstance(payload, Mapping) or payload.get("direction") != "base_to_field":
            continue
        turn = int(event.get("turn", 0) or 0)
        if turn <= max(0, int(early_turn_max)):
            card = event.get("card") if isinstance(event.get("card"), Mapping) else {}
            suspicious_moves.append(_finding(event, card, "early_base_to_field"))

    return {
        "source": source,
        "matchId": trace.get("matchId"),
        "codemanId": trace.get("codemanId"),
        "seed": trace.get("seed"),
        "semanticViolations": violations,
        "suspiciousEarlyBaseToField": suspicious_moves,
    }


def audit_codeman_trace_files(
    paths: list[Path],
    *,
    early_turn_max: int = 3,
) -> dict[str, Any]:
    traces = [
        audit_codeman_trace(
            json.loads(path.read_text(encoding="utf-8")),
            source=str(path),
            early_turn_max=early_turn_max,
        )
        for path in paths
    ]
    violations = [finding for trace in traces for finding in trace["semanticViolations"]]
    suspicious_moves = [
        finding
        for trace in traces
        for finding in trace["suspiciousEarlyBaseToField"]
    ]
    return {
        "traceCount": len(traces),
        "semanticViolationCount": len(violations),
        "suspiciousEarlyBaseToFieldCount": len(suspicious_moves),
        "traces": traces,
    }


def audit_actor_semantic_contract(
    model_path: str | Path,
    *,
    seed: int = 20260731,
) -> dict[str, Any]:
    """Exercise a runtime actor against retained hard semantic regression states."""
    path = Path(model_path)
    scenarios = [
        ("zero_dp_attack_without_payoff", _zero_dp_attack_engine),
        ("no_effect_base_to_field_resource_spend", _no_effect_base_pull_engine),
    ]
    rows: list[dict[str, Any]] = []
    for index, (expected_reason, build_engine) in enumerate(scenarios):
        scenario_seed = int(seed) + index * 1009
        try:
            engine, player = build_engine(scenario_seed)
            legal = list(engine.legal_actions())
            admissible, semantic_report = semantically_admissible_main_actions(
                engine,
                player,
                legal,
                extractor=FeatureExtractor(),
            )
            policy = _load_actor_policy(path, seed=scenario_seed + 1)
            choice = policy.choose(engine)
            selected_violation = semantic_ai_action_rejection_reason(
                engine,
                player,
                choice,
                extractor=FeatureExtractor(),
            )
            runtime_stats = policy.action_set_direct_runtime_stats()
            expected_rejections = int(semantic_report["rejectedByReason"].get(expected_reason, 0))
            passed = bool(
                expected_rejections > 0
                and choice in admissible
                and selected_violation is None
                and int(runtime_stats.get("actionSetDirectFallbacks", 0)) == 0
                and int(runtime_stats.get("actionSetDirectErrors", 0)) == 0
                and int(runtime_stats.get("actionSetSemanticRejections", 0))
                == int(semantic_report["rejectedActionCount"])
            )
            rows.append(
                {
                    "scenario": expected_reason,
                    "passed": passed,
                    "legalActionCount": len(legal),
                    "selectedAction": _action_payload(choice),
                    "selectedViolation": selected_violation,
                    "semanticFilter": semantic_report,
                    "runtimeStats": runtime_stats,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "scenario": expected_reason,
                    "passed": False,
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return {
        "kind": "actor_semantic_contract_v1",
        "modelPath": str(path),
        "seed": int(seed),
        "scenarioCount": len(rows),
        "passedScenarioCount": sum(1 for row in rows if row.get("passed")),
        "errorCount": sum(1 for row in rows if row.get("error")),
        "passed": bool(rows) and all(bool(row.get("passed")) for row in rows),
        "scenarios": rows,
    }


def _load_actor_policy(model_path: Path, *, seed: int) -> Any:
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not bool(payload.get("runtimeLaunchableActor")):
        raise ValueError(f"semantic gate requires a runtime-launchable actor: {model_path}")
    actor_id = str(
        payload.get("actorPolicyId")
        or payload.get("candidatePolicyId")
        or payload.get("modelId")
        or ""
    ).strip()
    if not actor_id:
        raise ValueError(f"semantic gate actor is missing actorPolicyId: {model_path}")
    from zz.policy_factories import create_current_policy_actor_rollout_policy

    return create_current_policy_actor_rollout_policy(
        model_path=model_path,
        seed=seed,
        policy_id=actor_id,
        expected_candidate_policy_ids=[actor_id],
        expected_source_actor_policy_id=str(payload.get("sourceActorPolicyId") or ""),
        min_source_rows=0,
    )


def _semantic_engine(seed: int) -> tuple[Engine, Player, Player]:
    player = Player(name="P1", side=Side.P1, is_first_player=True, life=10)
    opponent = Player(name="P2", side=Side.P2, life=10)
    state = GameState(players=[player, opponent], turn=2)
    state.step = Step.MAIN
    engine = Engine(state, rng=random.Random(seed))
    engine.install_forces(
        opponent,
        [ForceInstance(force=F_MINOTAUROS, owner=opponent, life=F_MINOTAUROS.initial_life)],
    )
    return engine, player, opponent


def _zero_dp_attack_engine(seed: int) -> tuple[Engine, Player]:
    engine, player, _opponent = _semantic_engine(seed)
    attacker = CardInstance(
        CARD_REGISTRY["colorless_01_02_01_01"],
        player,
        area=AreaType.FIELD,
    )
    attacker.summoning_sickness = False
    player.field = [attacker]
    engine.state.present_at_turn_start = {attacker.iid}
    return engine, player


def _no_effect_base_pull_engine(seed: int) -> tuple[Engine, Player]:
    engine, player, _opponent = _semantic_engine(seed)
    mana = CardInstance(
        CARD_REGISTRY["blue_00_01_00_00"],
        player,
        area=AreaType.BASE,
    )
    player.base = [mana]
    player.movement_right_count = 1
    player.movement_right_total = 1
    return engine, player


def _action_payload(action: Action) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "payload": {str(key): value for key, value in action.payload.items()},
    }


def _card_has_attack_payoff(card_id: str) -> bool:
    card = CARD_REGISTRY.get(card_id)
    if card is None:
        raise ValueError(f"Codeman trace references unknown card: {card_id!r}")
    for effect in card.effects:
        if effect.timing in {EffectTiming.ON_ATTACK, EffectTiming.ON_BATTLE_WIN}:
            return True
    for trigger in card.triggers:
        if trigger.when is TriggerTiming.ON_ATTACK:
            return True
    return False


def _finding(
    event: Mapping[str, Any],
    card: Mapping[str, Any],
    kind: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "eventIndex": event.get("eventIndex"),
        "turn": event.get("turn"),
        "cardId": card.get("cardId"),
        "nameJp": card.get("nameJp"),
        "effectiveDp": card.get("effectiveDp", card.get("dp")),
        "text": event.get("rawText") or event.get("label"),
    }
