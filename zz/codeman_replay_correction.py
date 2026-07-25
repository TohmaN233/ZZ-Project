from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zz.ai_registry import resolve_battle_policy
from zz.cards import CARD_REGISTRY
from zz.codeman_memory import CodemanMemoryStore
from zz.decks import build_deck
from zz.effects import EffectTiming
from zz.engine import FIELD_CAP, BASE_CAP, Engine, GameOver, IllegalActionError
from zz.enums import AreaType, AttackTargetKind, CardType, Color, Phase, Side, Step, TriggerTiming
from zz.forces import ALL_FORCES
from zz.greedy_ai import GreedyLegalPolicy
from zz.model import Action, AttackTarget, Card, CardInstance, ForceInstance, GameState, Player
from zz.rl_training import (
    TRAINING_MAX_ACTIONS,
    TRAINING_MAX_TURNS,
    _action_to_dict,
    _attach_runtime_deck_profile,
    find_replay_action,
)
from zz.web.assets import AssetIndex
from zz.web.serialize import serialize_state
from zz.web.session import GameSession


DEFAULT_DECISION_WINDOW = 10
DEFAULT_ALTERNATIVES_PER_DECISION = 3


class _ReplayRepairPolicy(GreedyLegalPolicy):
    def choose(self, engine: Engine) -> Action:
        legal = list(engine.legal_actions())
        if not legal:
            raise RuntimeError("no legal action")
        player = engine.state.active
        useful = [
            action
            for action in legal
            if not _zero_dp_attack_without_payoff(engine, player, action)
        ]
        return max(useful or legal, key=lambda action: _repair_action_score(engine, player, action))


class _GuardedReplayRepairPolicy:
    def __init__(self, policy: Any, fallback: _ReplayRepairPolicy):
        self.policy = policy
        self.fallback = fallback

    def choose(self, engine: Engine) -> Action:
        legal = list(engine.legal_actions())
        if not legal:
            raise RuntimeError("no legal action")
        player = engine.state.active
        try:
            action = self.policy.choose(engine)
        except Exception:
            return self.fallback.choose(engine)
        if action in legal and not _zero_dp_attack_without_payoff(engine, player, action):
            return action
        return self.fallback.choose(engine)

    def choose_flash(self, engine: Engine, legal: list[Action]) -> Action:
        try:
            return self.policy.choose_flash(engine, legal)
        except Exception:
            return self.fallback.choose_flash(engine, legal)

    def choose_blocker(self, engine: Engine, attacker: CardInstance, blockers: list[CardInstance]):
        try:
            return self.policy.choose_blocker(engine, attacker, blockers)
        except Exception:
            return self.fallback.choose_blocker(engine, attacker, blockers)

    def choose_attack_target(
        self,
        engine: Engine,
        attacker: CardInstance,
        targets: list[AttackTarget],
    ) -> AttackTarget:
        try:
            return self.policy.choose_attack_target(engine, attacker, targets)
        except Exception:
            return self.fallback.choose_attack_target(engine, attacker, targets)

    def choose_target(self, engine: Engine, kind: str, min_n: int, max_n: int, eligible: list) -> list:
        try:
            return self.policy.choose_target(engine, kind, min_n, max_n, eligible)
        except Exception:
            return self.fallback.choose_target(engine, kind, min_n, max_n, eligible)

    def choose_mulligan(self, engine: Engine, player: Player) -> list[CardInstance]:
        try:
            return self.policy.choose_mulligan(engine, player)
        except Exception:
            return self.fallback.choose_mulligan(engine, player)


class _ReplayVisualPolicy:
    """Record combat choices in the same ordered visual stream as engine effects."""

    def __init__(self, policy: Any):
        self.policy = policy

    def choose(self, engine: Engine) -> Action:
        return self.policy.choose(engine)

    def choose_flash(self, engine: Engine, legal: list[Action]) -> Action:
        return self.policy.choose_flash(engine, legal)

    def choose_blocker(self, engine: Engine, attacker: CardInstance, blockers: list[CardInstance]):
        blocker = self.policy.choose_blocker(engine, attacker, blockers)
        if blocker is None and blockers and not engine.can_decline_block(attacker, blockers):
            blocker = engine.forced_blocker(attacker, blockers)
        if blocker is not None:
            engine._record_visual_event({
                "type": "block",
                "attacker": attacker,
                "blocker": blocker,
            })
        return blocker

    def choose_attack_target(
        self,
        engine: Engine,
        attacker: CardInstance,
        targets: list[AttackTarget],
    ) -> AttackTarget:
        target = self.policy.choose_attack_target(engine, attacker, targets)
        engine._record_visual_event({
            "type": "attack",
            "attacker": attacker,
            "target": target,
        })
        return target

    def choose_target(self, engine: Engine, kind: str, min_n: int, max_n: int, eligible: list) -> list:
        return self.policy.choose_target(engine, kind, min_n, max_n, eligible)

    def choose_mulligan(self, engine: Engine, player: Player) -> list[CardInstance]:
        return self.policy.choose_mulligan(engine, player)


class _ReplayAnimationRecorder(GameSession):
    """Reuse the live duel VFX collector for engine-driven corrected replays."""

    def __init__(self, engine: Engine, asset_index: AssetIndex):
        self.engine = engine
        self.asset_index = asset_index
        self._animation_events: list[dict[str, Any]] = []
        self._visual_snapshot = self._visual_state_snapshot()

    def visual_snapshot(self) -> dict[str, Any]:
        return self._visual_state_snapshot()

    def collect(self, before: dict[str, Any]) -> list[dict[str, Any]]:
        self._record_visual_changes(before)
        events = list(self._animation_events)
        self._animation_events.clear()
        return events

    def _animation_event_from_engine_visual_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = event.get("type")
        if event_type == "attack":
            attacker = event["attacker"]
            target = event["target"]
            animation_event = {
                "type": "attack",
                "side": attacker.owner.side.name,
                "attacker": self._card_log_payload(attacker),
                "attackerIid": attacker.iid,
            }
            animation_event.update(self._target_animation_payload(target))
            return animation_event
        if event_type == "block":
            attacker = event["attacker"]
            blocker = event["blocker"]
            return {
                "type": "block",
                "side": attacker.owner.side.name,
                "targetSide": blocker.owner.side.name,
                "attacker": self._card_log_payload(attacker),
                "attackerIid": attacker.iid,
                "blocker": self._card_log_payload(blocker),
                "blockerIid": blocker.iid,
            }
        return super()._animation_event_from_engine_visual_event(event)


def attempt_memory_replay_correction(
    codeman_id: str,
    match_id: str,
    *,
    data_root: str | Path,
    decision_window: int = DEFAULT_DECISION_WINDOW,
    alternatives_per_decision: int = DEFAULT_ALTERNATIVES_PER_DECISION,
    run_id: str | None = None,
    seed: int = 20260526,
) -> dict[str, Any]:
    """Try a bounded single-match repair search for one logged Codeman loss."""

    store = CodemanMemoryStore(data_root)
    row = _memory_row_for_match(store, codeman_id, match_id)
    if row is None:
        raise FileNotFoundError(match_id)
    replay = store.read_replay(codeman_id, match_id)
    trace = replay.get("trace")
    if not isinstance(trace, dict):
        return _empty_result(match_id, "missing_trace")

    player_side = str(row.get("player_side") or trace.get("playerSide") or "")
    winner_side = str(row.get("winner_side") or trace.get("winnerSide") or "")
    if not player_side or winner_side == player_side:
        return _empty_result(match_id, "not_a_player_loss")

    decision_events = _player_operation_events(trace, player_side)
    if not decision_events:
        return _empty_result(match_id, "no_player_decisions")

    run_id = run_id or _default_run_id()
    tried = 0
    for event in reversed(decision_events[-max(1, int(decision_window)):]):
        alternatives = _legal_alternatives_at_event(row, trace, event)
        for action in alternatives[:max(1, int(alternatives_per_decision))]:
            tried += 1
            branch = _play_replay_branch(
                row,
                trace,
                event,
                action,
                data_root=data_root,
                seed=seed + tried,
                codeman_id=codeman_id,
            )
            if str(branch.get("winnerSide") or "") != player_side:
                continue
            payload = _corrected_replay_payload(
                row=row,
                trace=trace,
                event=event,
                action=action,
                branch=branch,
                run_id=run_id,
                tried_branches=tried,
                decision_window=decision_window,
                alternatives_per_decision=alternatives_per_decision,
            )
            corrected_path = store.write_corrected_replay(codeman_id, match_id, payload, run_id=run_id)
            return {
                "ok": True,
                "matchId": match_id,
                "corrected": True,
                "triedBranches": tried,
                "sourceEventIndex": event.get("eventIndex"),
                "actionKind": action.kind,
                "correctedPath": str(corrected_path),
                "branch": branch,
            }

    return {
        "ok": True,
        "matchId": match_id,
        "corrected": False,
        "reason": "no_winning_branch",
        "triedBranches": tried,
    }


def _memory_row_for_match(
    store: CodemanMemoryStore,
    codeman_id: str,
    match_id: str,
) -> dict[str, Any] | None:
    target = str(match_id)
    return next((row for row in store.read_games(codeman_id) if str(row.get("match_id") or "") == target), None)


def _empty_result(match_id: str, reason: str) -> dict[str, Any]:
    return {
        "ok": True,
        "matchId": match_id,
        "corrected": False,
        "reason": reason,
        "triedBranches": 0,
    }


def _default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"manual_replay_repair_{stamp}"


def _player_operation_events(trace: dict[str, Any], player_side: str) -> list[dict[str, Any]]:
    events = trace.get("logEvents")
    if not isinstance(events, list):
        return []
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "action":
            continue
        if str(event.get("actorSide") or "") != player_side:
            continue
        action_kind = str(event.get("actionKind") or "")
        if action_kind in {"flash_pass"}:
            continue
        out.append(event)
    return out


def _legal_alternatives_at_event(
    row: dict[str, Any],
    trace: dict[str, Any],
    event: dict[str, Any],
) -> list[Action]:
    engine = _engine_from_event_snapshot(row, trace, event, seed=int(row.get("seed") or trace.get("seed") or 0))
    if engine is None:
        return []
    legal = list(engine.legal_actions())
    player = engine.state.active
    recorded = event.get("action") if isinstance(event.get("action"), dict) else {}
    original = find_replay_action(engine, player, recorded, legal) if recorded else None
    alternatives = [action for action in legal if action != original]
    alternatives = [
        action
        for action in alternatives
        if not _zero_dp_attack_without_payoff(engine, player, action)
    ]
    alternatives.sort(key=lambda action: _repair_action_score(engine, player, action), reverse=True)
    return alternatives


def _play_replay_branch(
    row: dict[str, Any],
    trace: dict[str, Any],
    event: dict[str, Any],
    action: Action,
    *,
    data_root: str | Path,
    seed: int,
    codeman_id: str | None = None,
) -> dict[str, Any]:
    engine = _engine_from_event_snapshot(row, trace, event, seed=seed)
    if engine is None:
        return {"winnerSide": None, "reason": "snapshot_unavailable", "turns": None, "actions": 0}
    engine.set_policies(
        _ReplayVisualPolicy(_replay_repair_policy(codeman_id, data_root=data_root, seed=seed + 1)),
        _ReplayVisualPolicy(_replay_repair_policy(codeman_id, data_root=data_root, seed=seed + 2)),
    )
    actions = 0
    log_events: list[dict[str, Any]] = []
    state_snapshots: list[dict[str, Any]] = []
    animation_history: list[dict[str, Any]] = []
    asset_index = AssetIndex(None)
    animation_recorder = _ReplayAnimationRecorder(engine, asset_index)
    player_side = str(row.get("player_side") or trace.get("playerSide") or "P1")
    state_snapshots.append(
        _branch_state_snapshot(
            engine,
            row,
            trace,
            asset_index,
            player_side=player_side,
            index=0,
            event_index=None,
            label="AI correction start",
            animation_events=[],
        )
    )

    def apply_branch_action(branch_action: Action) -> None:
        nonlocal actions
        branch_index = len(log_events)
        log_event = _branch_log_event(engine, branch_action, branch_index, event)
        log_events.append(log_event)
        game_over_payload: dict[str, Any] | None = None
        before_visual = animation_recorder.visual_snapshot()
        try:
            engine.apply(branch_action)
            actions += 1
        except GameOver as game_over:
            actions += 1
            game_over_payload = _game_over_payload(game_over)
            animation_history.extend(animation_recorder.collect(before_visual))
            state_snapshots.append(
                _branch_state_snapshot(
                    engine,
                    row,
                    trace,
                    asset_index,
                    player_side=player_side,
                    index=len(state_snapshots),
                    event_index=branch_index,
                    label=_branch_snapshot_label(log_event),
                    game_over=game_over_payload,
                    animation_events=animation_history,
                )
            )
            raise
        animation_history.extend(animation_recorder.collect(before_visual))
        state_snapshots.append(
            _branch_state_snapshot(
                engine,
                row,
                trace,
                asset_index,
                player_side=player_side,
                index=len(state_snapshots),
                event_index=branch_index,
                label=_branch_snapshot_label(log_event),
                animation_events=animation_history,
            )
        )

    try:
        apply_branch_action(action)
        while actions < TRAINING_MAX_ACTIONS and int(getattr(engine.state, "turn", 0)) <= TRAINING_MAX_TURNS:
            policy = engine.policy_for(engine.state.active)
            next_action = policy.choose(engine)
            apply_branch_action(next_action)
    except GameOver as game_over:
        return {
            "winnerSide": _winner_side(game_over.winner),
            "reason": game_over.reason,
            "turns": int(getattr(engine.state, "turn", 0)),
            "actions": actions,
            "logEvents": log_events,
            "stateSnapshots": state_snapshots,
        }
    except (IllegalActionError, RuntimeError, ValueError, KeyError) as exc:
        return {
            "winnerSide": None,
            "reason": f"branch_error:{exc}",
            "turns": int(getattr(engine.state, "turn", 0)),
            "actions": actions,
            "logEvents": log_events,
            "stateSnapshots": state_snapshots,
        }
    return {
        "winnerSide": None,
        "reason": "max_actions",
        "turns": int(getattr(engine.state, "turn", 0)),
        "actions": actions,
        "logEvents": log_events,
        "stateSnapshots": state_snapshots,
    }


def _winner_side(winner: Any) -> str | None:
    side = getattr(winner, "side", None)
    if side is None:
        return None
    return str(getattr(side, "name", side))


def _replay_repair_policy(
    codeman_id: str | None,
    *,
    data_root: str | Path,
    seed: int,
) -> Any:
    fallback = _ReplayRepairPolicy(random.Random(seed + 1009))
    if not codeman_id:
        return fallback
    try:
        resolved = resolve_battle_policy(
            "codeman",
            seed=seed,
            codeman_id=str(codeman_id),
            data_root=data_root,
        )
    except Exception:
        return fallback
    return _GuardedReplayRepairPolicy(resolved.policy, fallback)


def _game_over_payload(game_over: GameOver) -> dict[str, Any]:
    return {
        "winnerSide": _winner_side(game_over.winner),
        "winnerName": getattr(game_over.winner, "name", None),
        "reason": game_over.reason,
    }


def _corrected_replay_payload(
    *,
    row: dict[str, Any],
    trace: dict[str, Any],
    event: dict[str, Any],
    action: Action,
    branch: dict[str, Any],
    run_id: str,
    tried_branches: int,
    decision_window: int,
    alternatives_per_decision: int,
) -> dict[str, Any]:
    action_record = {"kind": action.kind, "payload": dict(action.payload)}
    return {
        "schema": 2,
        "kind": "codeman_corrected_replay",
        "matchId": str(row.get("match_id") or trace.get("matchId") or ""),
        "sourceTraceMatchId": trace.get("matchId"),
        "playerSide": row.get("player_side") or trace.get("playerSide"),
        "originalWinnerSide": row.get("winner_side") or trace.get("winnerSide"),
        "correctedWinnerSide": branch.get("winnerSide"),
        "runId": run_id,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "correctionMode": "bounded_single_match_branch_search",
        "triedBranches": tried_branches,
        "replayControl": {
            "source": "event_snapshot",
            "decisionWindow": int(decision_window),
            "alternativesPerDecision": int(alternatives_per_decision),
            "branchPolicy": "current_codeman_policy_after_divergence",
        },
        "sourceEventIndex": event.get("eventIndex"),
        "sourceSnapshotIndex": _pre_snapshot_index_for_event(event),
        "loggedSnapshotIndex": event.get("snapshotIndex"),
        "sourceEvent": _compact_event(event),
        "branch": dict(branch),
        "logEvents": _corrected_log_events(event, action, branch),
        "stateSnapshots": _corrected_state_snapshots(branch),
        "divergences": [{
            "eventIndex": 0,
            "snapshotIndex": 0,
            "sourceEventIndex": event.get("eventIndex"),
            "sourceSnapshotIndex": _pre_snapshot_index_for_event(event),
            "loggedSnapshotIndex": event.get("snapshotIndex"),
            "playerAction": _action_summary_for_repair(event.get("action") or {"kind": event.get("actionKind")}),
            "aiAction": _action_summary_for_repair(action_record),
            "aiActionRecord": action_record,
            "hint": "AI found a winning branch by changing this decision during single-match replay repair.",
        }],
    }


def _corrected_log_events(event: dict[str, Any], action: Action, branch: dict[str, Any]) -> list[dict[str, Any]]:
    divergence = {
        "type": "correction_divergence",
        "eventIndex": 0,
        "snapshotIndex": 0,
        "sourceEventIndex": event.get("eventIndex"),
        "sourceSnapshotIndex": _pre_snapshot_index_for_event(event),
        "loggedSnapshotIndex": event.get("snapshotIndex"),
        "actorSide": event.get("actorSide"),
        "originalActionKind": event.get("actionKind"),
        "actionKind": action.kind,
        "action": {"kind": action.kind, "payload": dict(action.payload)},
    }
    branch_events = branch.get("logEvents") if isinstance(branch.get("logEvents"), list) else []
    corrected_events = [divergence]
    for index, item in enumerate(branch_events, start=1):
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        copied["eventIndex"] = index
        if "snapshotIndex" not in copied:
            copied["snapshotIndex"] = index
        corrected_events.append(copied)
    return corrected_events


def _corrected_state_snapshots(branch: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = branch.get("stateSnapshots")
    if not isinstance(snapshots, list):
        return []
    return [dict(item) for item in snapshots if isinstance(item, dict)]


def _branch_log_event(
    engine: Engine,
    action: Action,
    branch_index: int,
    source_event: dict[str, Any],
) -> dict[str, Any]:
    player = engine.state.active
    payload: dict[str, Any] = {
        "type": "action",
        "eventIndex": branch_index + 1,
        "branchEventIndex": branch_index,
        "sourceEventIndex": source_event.get("eventIndex"),
        "sourceSnapshotIndex": _pre_snapshot_index_for_event(source_event),
        "snapshotIndex": branch_index + 1,
        "actorName": player.name,
        "actorSide": player.side.name,
        "turn": engine.state.turn,
        "phase": engine.state.phase.value,
        "step": engine.state.step.value,
        "activeSide": engine.state.active.side.name,
        "actionKind": action.kind,
    }
    try:
        payload["action"] = _action_to_dict(action, engine=engine, player=player)
    except Exception:
        payload["action"] = {"kind": action.kind, "payload": dict(action.payload)}
    return payload


def _branch_state_snapshot(
    engine: Engine,
    row: dict[str, Any],
    trace: dict[str, Any],
    asset_index: AssetIndex,
    *,
    player_side: str,
    index: int,
    event_index: int | None,
    label: str,
    game_over: dict[str, Any] | None = None,
    animation_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    human = _player_for_side(engine, player_side)
    state = serialize_state(
        engine,
        human=human,
        asset_index=asset_index,
        prompt=None,
        log=[],
        log_events=[],
        mode=str(trace.get("mode") or row.get("mode") or "codeman-replay-correction"),
        game_over=game_over,
        reveal_all_hands=True,
        animation_events=[],
    )
    if row.get("seed") is not None or trace.get("seed") is not None:
        state["seed"] = row.get("seed") if row.get("seed") is not None else trace.get("seed")
    if row.get("opponent_ai_difficulty") is not None or trace.get("opponentAiDifficulty") is not None:
        state["opponentAiDifficulty"] = (
            row.get("opponent_ai_difficulty")
            if row.get("opponent_ai_difficulty") is not None
            else trace.get("opponentAiDifficulty")
        )
    if row.get("debug_control_both") is not None or trace.get("debugControlBoth") is not None:
        state["debugControlBoth"] = bool(row.get("debug_control_both") or trace.get("debugControlBoth"))
    compact_state = _compact_branch_state(state)
    return {
        "schema": 2,
        "index": index,
        "eventIndex": event_index,
        "label": str(label),
        "turn": getattr(engine.state, "turn", None),
        "phase": getattr(getattr(engine.state, "phase", None), "value", getattr(engine.state, "phase", None)),
        "step": getattr(getattr(engine.state, "step", None), "value", getattr(engine.state, "step", None)),
        "activeSide": getattr(getattr(engine.state, "active", None), "side", None).name,
        "animationEvents": list(animation_events or []),
        "state": compact_state,
    }


def _player_for_side(engine: Engine, side_name: str) -> Player | None:
    for player in getattr(engine.state, "players", []):
        if getattr(getattr(player, "side", None), "name", None) == side_name:
            return player
    players = list(getattr(engine.state, "players", []) or [])
    return players[0] if players else None


def _branch_snapshot_label(log_event: dict[str, Any]) -> str:
    return str(
        log_event.get("label")
        or log_event.get("rawText")
        or log_event.get("actionKind")
        or "AI branch action"
    )


def _compact_branch_state(state: dict[str, Any]) -> dict[str, Any]:
    allowed_state_keys = {
        "mode",
        "turn",
        "phase",
        "step",
        "activeSide",
        "humanSide",
        "gameOver",
        "players",
        "seed",
        "opponentAiDifficulty",
        "debugControlBoth",
    }
    compact = {key: state[key] for key in allowed_state_keys if key in state}
    players = state.get("players")
    if isinstance(players, dict):
        compact["players"] = {
            key: _compact_branch_player(value)
            for key, value in players.items()
            if isinstance(value, dict)
        }
    return compact


def _compact_branch_player(player: dict[str, Any]) -> dict[str, Any]:
    allowed_player_keys = {
        "name",
        "side",
        "isFirstPlayer",
        "profile",
        "life",
        "maxLife",
        "deckCount",
        "deckVisualTier",
        "handCount",
        "trashCount",
        "movementRightCount",
        "movementRightTotal",
        "baseSummary",
    }
    compact = {key: player[key] for key in allowed_player_keys if key in player}
    for key in ("hand", "field", "base", "trash"):
        compact[key] = [
            _compact_branch_card(card)
            for card in player.get(key, [])
            if isinstance(card, dict)
        ]
    compact["forces"] = [
        _compact_branch_force(force)
        for force in player.get("forces", [])
        if isinstance(force, dict)
    ]
    return compact


def _compact_branch_card(card: dict[str, Any]) -> dict[str, Any]:
    allowed_card_keys = {
        "iid",
        "cardId",
        "ownerSide",
        "nameJp",
        "nameEn",
        "nameZh",
        "type",
        "cost",
        "manaColor",
        "bp",
        "dp",
        "effectiveBp",
        "effectiveDp",
        "rested",
        "area",
        "keywords",
        "faceDown",
        "assetId",
        "assetUrl",
        "assetUrlEn",
    }
    return {key: card[key] for key in allowed_card_keys if key in card}


def _compact_branch_force(force: dict[str, Any]) -> dict[str, Any]:
    allowed_force_keys = {
        "id",
        "ownerSide",
        "nameJp",
        "nameZh",
        "life",
        "initialLife",
        "maxLife",
        "destroyed",
        "rested",
        "assetId",
        "assetUrl",
    }
    return {key: force[key] for key in allowed_force_keys if key in force}


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event.get(key)
        for key in (
            "eventIndex",
            "snapshotIndex",
            "type",
            "actorSide",
            "actionKind",
            "label",
            "rawText",
            "turn",
            "phase",
            "step",
            "activeSide",
        )
        if key in event
    }


def _action_summary_for_repair(action: Any) -> str:
    if isinstance(action, Action):
        return action.kind
    if isinstance(action, dict):
        return str(action.get("kind") or action.get("actionKind") or "")
    return str(action or "")


def _engine_from_event_snapshot(
    row: dict[str, Any],
    trace: dict[str, Any],
    event: dict[str, Any],
    *,
    seed: int,
) -> Engine | None:
    snapshot = _snapshot_for_event(trace, event)
    if snapshot is None:
        return None
    state_data = snapshot.get("state")
    if not isinstance(state_data, dict):
        return None
    players_data = state_data.get("players")
    if not isinstance(players_data, dict):
        return None

    p1 = Player(name="P1", side=Side.P1)
    p2 = Player(name="P2", side=Side.P2)
    player_by_side = {Side.P1.name: p1, Side.P2.name: p2}
    trace_player_side = str(row.get("player_side") or trace.get("playerSide") or "P1").strip().upper()
    if trace_player_side not in {"P1", "P2"}:
        trace_player_side = "P1"
    player_recipe = dict(row.get("player_deck_recipe") or trace.get("playerDeckRecipe") or {})
    opponent_recipe = dict(row.get("opponent_deck_recipe") or trace.get("opponentDeckRecipe") or {})
    player_forces = list(row.get("player_forces") or trace.get("playerForces") or [])
    opponent_forces = list(row.get("opponent_forces") or trace.get("opponentForces") or [])
    p1_recipe = player_recipe if trace_player_side == "P1" else opponent_recipe
    p2_recipe = player_recipe if trace_player_side == "P2" else opponent_recipe
    p1_forces = player_forces if trace_player_side == "P1" else opponent_forces
    p2_forces = player_forces if trace_player_side == "P2" else opponent_forces

    for public_player in players_data.values():
        if not isinstance(public_player, dict):
            continue
        side_name = str(public_player.get("side") or "")
        player = player_by_side.get(side_name)
        if player is None:
            continue
        player.name = str(public_player.get("name") or side_name)
        player.is_first_player = bool(public_player.get("isFirstPlayer"))
        player.life = int(public_player.get("life") or 0)
        player.movement_right_count = int(public_player.get("movementRightCount") or 0)
        player.movement_right_total = int(public_player.get("movementRightTotal") or 0)
        player.hand = _cards_from_public_zone(public_player.get("hand"), player, AreaType.HAND)
        player.field = _cards_from_public_zone(public_player.get("field"), player, AreaType.FIELD)
        player.base = _cards_from_public_zone(public_player.get("base"), player, AreaType.BASE)
        player.trash = _cards_from_public_zone(public_player.get("trash"), player, AreaType.TRASH)
        public_profile = public_player.get("profile")
        if isinstance(public_profile, dict):
            player.profile = dict(public_profile)
        for card in player.field + player.base:
            card.summoning_sickness = False
        force_ids = p1_forces if player.side is Side.P1 else p2_forces
        player.forces = _forces_from_public(public_player.get("forces"), player, force_ids)
        recipe = p1_recipe if player.side is Side.P1 else p2_recipe
        is_trace_player = player.side.name == trace_player_side
        _attach_runtime_deck_profile(
            player,
            deck_id="trace-player" if is_trace_player else "trace-opponent",
            name=f"{'player' if is_trace_player else 'opponent'} trace deck",
            recipe=recipe,
            forces=force_ids,
        )
        player.deck = _remaining_deck(recipe, player)
        _remove_visible_cards_from_deck(player)

    active_side = str(state_data.get("activeSide") or snapshot.get("activeSide") or event.get("activeSide") or "P1")
    active_idx = 0 if active_side == Side.P1.name else 1
    game_state = GameState(
        players=[p1, p2],
        turn=int(state_data.get("turn") or snapshot.get("turn") or event.get("turn") or 1),
        active_idx=active_idx,
    )
    game_state.phase = _enum_or_default(Phase, state_data.get("phase") or snapshot.get("phase"), Phase.MAIN)
    game_state.step = _enum_or_default(Step, state_data.get("step") or snapshot.get("step"), Step.MAIN)
    game_state.present_at_turn_start = {
        card.iid
        for card in (game_state.active.field + game_state.active.base)
    }
    engine = Engine(game_state, rng=random.Random(seed))
    game_state.engine = engine
    engine.set_policies(GreedyLegalPolicy(random.Random(seed + 1)), GreedyLegalPolicy(random.Random(seed + 2)))
    engine.rebind_passive_modifiers()
    return engine


def _snapshot_for_event(trace: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = trace.get("stateSnapshots")
    if not isinstance(snapshots, list):
        return None
    raw_index = event.get("snapshotIndex")
    try:
        snapshot_index = int(raw_index)
    except (TypeError, ValueError):
        snapshot_index = -1
    pre_snapshot_index = _pre_snapshot_index_for_event(event)
    if 0 <= pre_snapshot_index < len(snapshots) and isinstance(snapshots[pre_snapshot_index], dict):
        return snapshots[pre_snapshot_index]
    if 0 <= snapshot_index < len(snapshots) and isinstance(snapshots[snapshot_index], dict):
        return snapshots[snapshot_index]
    event_index = event.get("eventIndex")
    for snapshot in snapshots:
        if isinstance(snapshot, dict) and snapshot.get("eventIndex") == event_index:
            return snapshot
    return None


def _pre_snapshot_index_for_event(event: dict[str, Any]) -> int:
    try:
        snapshot_index = int(event.get("snapshotIndex"))
    except (TypeError, ValueError):
        return -1
    return snapshot_index - 1 if snapshot_index > 0 else snapshot_index


def _cards_from_public_zone(raw_zone: Any, owner: Player, area: AreaType) -> list[CardInstance]:
    if not isinstance(raw_zone, list):
        return []
    out: list[CardInstance] = []
    for raw_card in raw_zone:
        if not isinstance(raw_card, dict):
            continue
        card_id = str(raw_card.get("cardId") or "")
        card = _card_from_public_snapshot(raw_card)
        if card is None:
            continue
        instance = CardInstance(card=card, owner=owner)
        try:
            instance.iid = int(raw_card.get("iid"))
        except (TypeError, ValueError):
            pass
        instance.area = area
        instance.rested = bool(raw_card.get("rested"))
        instance.summoning_sickness = False
        raw_mana_color = raw_card.get("manaColor")
        if raw_mana_color:
            try:
                color = Color[str(raw_mana_color)]
                if card.mana_color is not color:
                    instance.mana_color_override = color
            except KeyError:
                pass
        out.append(instance)
    return out


def _card_from_public_snapshot(raw_card: dict[str, Any]) -> Card | None:
    card_id = str(raw_card.get("cardId") or "")
    if card_id == "mana_token" or str(raw_card.get("type") or "") == "mana_token":
        return Card(
            id="mana_token",
            name_jp=str(raw_card.get("nameJp") or "無色マナ"),
            name_en=str(raw_card.get("nameEn") or "Colorless Mana"),
            type=CardType.MANA_TOKEN,
            cost={},
        )
    return CARD_REGISTRY.get(card_id)


def _forces_from_public(raw_forces: Any, owner: Player, fallback_force_ids: list[str]) -> list[ForceInstance]:
    public_forces = raw_forces if isinstance(raw_forces, list) else []
    out: list[ForceInstance] = []
    for index, force_id in enumerate(fallback_force_ids):
        force = ALL_FORCES.get(str(force_id))
        if force is None:
            continue
        public = public_forces[index] if index < len(public_forces) and isinstance(public_forces[index], dict) else {}
        instance = ForceInstance(
            force=force,
            owner=owner,
            life=int(public.get("life") if public.get("life") is not None else force.initial_life),
            destroyed=bool(public.get("destroyed")),
            rested=bool(public.get("rested")),
        )
        out.append(instance)
    return out


def _remaining_deck(recipe: dict[str, int], owner: Player) -> list[CardInstance]:
    if not recipe:
        return []
    try:
        return build_deck(recipe, owner=owner)
    except ValueError:
        return []


def _remove_visible_cards_from_deck(player: Player) -> None:
    visible_counts: dict[str, int] = {}
    for card in player.hand + player.field + player.base + player.trash + player.removed:
        visible_counts[card.card.id] = visible_counts.get(card.card.id, 0) + 1
    deck = list(player.deck)
    for card_id, count in visible_counts.items():
        removed = 0
        retained: list[CardInstance] = []
        for candidate in deck:
            if candidate.card.id == card_id and removed < count:
                removed += 1
            else:
                retained.append(candidate)
        deck = retained
    player.deck = deck


def _enum_or_default(enum_cls: Any, raw: Any, default: Any) -> Any:
    try:
        return enum_cls(str(raw))
    except Exception:
        return default


def _repair_action_score(engine: Engine, player: Player, action: Action) -> tuple[float, float, str]:
    if action.kind == "attack":
        if _zero_dp_attack_without_payoff(engine, player, action):
            return -1000, random.random(), action.kind
        attacker = _find_card_by_iid(player.field, action.payload.get("attacker_iid"))
        return 1000 + _card_threat(attacker), random.random(), action.kind
    if action.kind == "move_card":
        card = _find_card_by_iid(player.base + player.field, action.payload.get("iid"))
        direction = str(action.payload.get("direction") or "")
        if direction == "base_to_field":
            field_space_bonus = 80 if len(player.field) < FIELD_CAP or action.payload.get("replace_field_iid") else 0
            return 900 + field_space_bonus + _card_threat(card), random.random(), action.kind
        if direction == "field_to_base":
            base_space_bonus = 20 if len(player.base) < BASE_CAP or action.payload.get("replace_base_iid") else 0
            return 500 + base_space_bonus + _card_threat(card), random.random(), action.kind
    if action.kind == "play_card":
        card = _find_card_by_iid(player.hand, action.payload.get("iid"))
        return 700 + _card_threat(card), random.random(), action.kind
    if action.kind == "play_to_base":
        card = _find_card_by_iid(player.hand, action.payload.get("iid"))
        return 650 + _card_threat(card), random.random(), action.kind
    if action.kind == "swap_mana_color":
        return 300, random.random(), action.kind
    if action.kind == "place_colorless_mana":
        return 250, random.random(), action.kind
    if action.kind == "skip_mana":
        return 50, random.random(), action.kind
    if action.kind == "end_turn":
        return -100, random.random(), action.kind
    return 100, random.random(), action.kind


def _find_card_by_iid(cards: list[CardInstance], raw_iid: Any) -> CardInstance | None:
    try:
        iid = int(raw_iid)
    except (TypeError, ValueError):
        return None
    return next((card for card in cards if card.iid == iid), None)


def _card_threat(card: CardInstance | None) -> float:
    if card is None:
        return 0.0
    card_type = getattr(card.card, "type", None)
    type_bonus = 50 if card_type is CardType.F_MINION else 20
    return type_bonus + float(card.dp * 30) + float(card.bp) / 20.0 + float(sum(card.card.cost.values()) * 5)


def _zero_dp_attack_without_payoff(engine: Engine, player: Player, action: Action) -> bool:
    if action.kind != "attack":
        return False
    attacker = _find_card_by_iid(player.field, action.payload.get("attacker_iid"))
    if attacker is None:
        return False
    if _effective_dp(engine, attacker) > 0:
        return False
    return not _card_has_attack_payoff(attacker)


def _effective_dp(engine: Engine, card: CardInstance) -> int:
    try:
        return int(engine.effective_dp(card))
    except Exception:
        return int(card.dp)


def _card_has_attack_payoff(card: CardInstance) -> bool:
    source = card.card
    for effect in getattr(source, "effects", []) or []:
        if getattr(effect, "timing", None) in {EffectTiming.ON_ATTACK, EffectTiming.ON_BATTLE_WIN}:
            return True
    for trigger in getattr(source, "triggers", []) or []:
        if getattr(trigger, "when", None) is TriggerTiming.ON_ATTACK:
            return True
    return False
