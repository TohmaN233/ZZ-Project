from __future__ import annotations

from typing import Any, Iterable

from zz.codeman_replay_correction import _engine_from_event_snapshot
from zz.counterfactual_transition import (
    CounterfactualTransitionCollector,
    _action_id,
    transition_value_from_targets,
    validate_transition_row,
)
from zz.rl_ai import FeatureExtractor
from zz.rl_training import find_replay_action


TRACE_COUNTERFACTUAL_SOURCE = "trace-human"
TRACE_PLAYER_FIRSTNESS_VALUES = {"first", "second"}


def collect_trace_derived_transition_rows_from_trace(
    trace: dict[str, Any],
    *,
    row: dict[str, Any] | None = None,
    extractor: Any | None = None,
    seed: int | None = None,
    player_side: str | None = None,
    horizon_actions: int = 16,
    horizon_turns: int = 2,
    max_actions_per_state: int = 16,
    max_events: int | None = None,
    winning_traces_only: bool = False,
    observed_future_target_weight: float = 0.0,
    include_flash_pass: bool = False,
    action_kind_filter: Iterable[str] | None = None,
    source: str = TRACE_COUNTERFACTUAL_SOURCE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build transition rows from actual player trace decisions.

    The older AI-challenge preparation path regenerates states with a model
    policy. This collector instead reconstructs the pre-action snapshot for
    each player log event and records the logged human action as the chosen
    action for the transition row.
    """

    context = dict(row or {})
    side = _player_side(trace, context, player_side)
    winner_side = str(trace.get("winnerSide") or trace.get("winner_side") or context.get("winner_side") or "")
    match_id = str(trace.get("matchId") or trace.get("match_id") or context.get("match_id") or "")
    if winning_traces_only and winner_side and winner_side != side:
        return [], {
            "matchId": match_id,
            "playerSide": side,
            "winnerSide": winner_side,
            "rows": 0,
            "skipped": "non_winning_trace",
            "simulatedPolicyChosenEvents": 0,
        }

    base_seed = int(seed if seed is not None else context.get("seed") or trace.get("seed") or 0)
    extractor = extractor or FeatureExtractor()
    rows: list[dict[str, Any]] = []
    report = {
        "matchId": match_id,
        "playerSide": side,
        "winnerSide": winner_side,
        "actionEvents": 0,
        "playerActionEvents": 0,
        "reconstructedEvents": 0,
        "multiLegalEvents": 0,
        "singleLegalEvents": 0,
        "matchedEvents": 0,
        "unmatchedEvents": 0,
        "chosenActionMissingEvents": 0,
        "rows": 0,
        "simulatedPolicyChosenEvents": 0,
        "observedFutureTargetEvents": 0,
        "observedFutureTargetMissingEvents": 0,
    }
    collector = CounterfactualTransitionCollector(
        extractor=extractor,
        horizon_actions=horizon_actions,
        horizon_turns=horizon_turns,
        max_actions_per_state=max_actions_per_state,
    )
    limit = None if max_events is None else max(0, int(max_events))
    for event_index, event in enumerate(_trace_action_events(
        trace,
        include_flash_pass=include_flash_pass,
        action_kind_filter=action_kind_filter,
    )):
        report["actionEvents"] += 1
        if str(event.get("actorSide") or event.get("actor_side") or "") != side:
            continue
        report["playerActionEvents"] += 1
        if limit is not None and len(rows) >= limit:
            break
        action_record = _recorded_action(event)
        if not action_record:
            report["unmatchedEvents"] += 1
            continue
        engine = _engine_from_event_snapshot(context, trace, event, seed=base_seed + event_index)
        if engine is None:
            report["unmatchedEvents"] += 1
            continue
        actor_player = _player_for_side(engine, side)
        if actor_player is None:
            report["unmatchedEvents"] += 1
            continue
        decision_engine = _engine_for_trace_event(engine, event, action_record, actor_player)
        report["reconstructedEvents"] += 1
        try:
            legal_actions = list(decision_engine.legal_actions())
        except Exception:
            report["unmatchedEvents"] += 1
            continue
        if len(legal_actions) <= 1:
            report["singleLegalEvents"] += 1
            continue
        report["multiLegalEvents"] += 1
        active_player = _decision_actor(decision_engine, actor_player)
        logged_action = find_replay_action(decision_engine, active_player, action_record, legal_actions)
        if logged_action is None:
            report["unmatchedEvents"] += 1
            continue
        report["matchedEvents"] += 1
        chosen_action_id = _action_id(logged_action)
        row_actions_limit = max(int(max_actions_per_state), len(legal_actions))
        state_row = CounterfactualTransitionCollector(
            extractor=extractor,
            horizon_actions=horizon_actions,
            horizon_turns=horizon_turns,
            max_actions_per_state=row_actions_limit,
        ).collect_state_row(
            decision_engine,
            seed=base_seed,
            source=source,
            player_deck_id=_deck_id(context, trace, "player", default="trace-player"),
            opponent_deck_id=_deck_id(context, trace, "opponent", default="trace-opponent"),
            model_side=side,
            state_index=len(rows),
            opponent_kind=_opponent_kind(context, trace),
        )
        action_ids = {str(action.get("actionId")) for action in state_row.get("actions", [])}
        if chosen_action_id not in action_ids:
            report["chosenActionMissingEvents"] += 1
            continue
        _annotate_trace_row(
            state_row,
            trace=trace,
            context=context,
            event=event,
            logged_action=logged_action,
            action_record=action_record,
            chosen_action_id=chosen_action_id,
            side=side,
            winner_side=winner_side,
            match_id=match_id,
        )
        if float(observed_future_target_weight or 0.0) > 0.0:
            if _apply_observed_future_target_to_chosen_action(
                state_row,
                trace=trace,
                event=event,
                side=side,
                winner_side=winner_side,
                horizon_turns=horizon_turns,
                weight=float(observed_future_target_weight),
            ):
                report["observedFutureTargetEvents"] += 1
            else:
                report["observedFutureTargetMissingEvents"] += 1
        validate_transition_row(state_row)
        rows.append(state_row)
    report["rows"] = len(rows)
    return rows, report


class _FlashPriorityTraceEngine:
    def __init__(self, engine: Any, actor_player: Any) -> None:
        self._engine = engine
        self._actor_side = _side_name(actor_player)
        self._actor_index = _player_index_for_side(engine, self._actor_side)
        self._original_active_idx = int(getattr(getattr(engine, "state", None), "active_idx", self._actor_index))
        if self._actor_index is not None:
            engine.state.active_idx = self._actor_index

    def __getattr__(self, name: str) -> Any:
        engine = self.__dict__.get("_engine")
        if engine is None:
            raise AttributeError(name)
        return getattr(engine, name)

    def __getstate__(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)

    def _actor(self) -> Any:
        player = _player_for_side(self._engine, self._actor_side)
        if player is None:
            return getattr(self._engine.state, "active", None)
        return player

    def legal_actions(self) -> list[Any]:
        return list(self._engine.legal_flash_actions(self._actor()))

    def apply(self, action: Any) -> Any:
        result = self._engine.apply_flash_action(self._actor(), action)
        if hasattr(self._engine, "state") and hasattr(self._engine.state, "active_idx"):
            self._engine.state.active_idx = self._original_active_idx
        return result


def _engine_for_trace_event(engine: Any, event: dict[str, Any], action_record: dict[str, Any], actor_player: Any) -> Any:
    if _trace_event_is_flash_priority(event, action_record) and hasattr(engine, "legal_flash_actions"):
        return _FlashPriorityTraceEngine(engine, actor_player)
    return engine


def _decision_actor(decision_engine: Any, actor_player: Any) -> Any:
    if isinstance(decision_engine, _FlashPriorityTraceEngine):
        return decision_engine._actor()
    return getattr(decision_engine.state, "active", actor_player)


def _trace_event_is_flash_priority(event: dict[str, Any], action_record: dict[str, Any]) -> bool:
    if bool(event.get("traceFlashWindow")):
        return True
    kind = str(
        event.get("actionKind")
        or event.get("action_kind")
        or action_record.get("kind")
        or ""
    )
    if kind in {"flash_pass", "activate_flash_ability"}:
        return True
    for key in ("phase", "step", "promptKind", "prompt_kind"):
        value = str(event.get(key) or "").lower()
        if value in {"flash", "flash_action"}:
            return True
    return False


def _player_for_side(engine: Any, side: str) -> Any | None:
    for player in list(getattr(getattr(engine, "state", None), "players", []) or []):
        if _side_name(player) == str(side):
            return player
    return None


def _player_index_for_side(engine: Any, side: str) -> int | None:
    for index, player in enumerate(list(getattr(getattr(engine, "state", None), "players", []) or [])):
        if _side_name(player) == str(side):
            return index
    return None


def _side_name(player: Any) -> str:
    side = getattr(player, "side", "")
    return str(getattr(side, "name", side))


def collect_trace_derived_transition_rows_from_traces(
    traces: Iterable[tuple[dict[str, Any], dict[str, Any]]],
    *,
    extractor: Any | None = None,
    seed: int = 0,
    horizon_actions: int = 16,
    horizon_turns: int = 2,
    max_actions_per_state: int = 16,
    max_events_per_trace: int | None = None,
    winning_traces_only: bool = False,
    observed_future_target_weight: float = 0.0,
    include_flash_pass: bool = False,
    action_kind_filter: Iterable[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    shared_extractor = extractor or FeatureExtractor()
    for index, (trace, row) in enumerate(traces):
        trace_rows, report = collect_trace_derived_transition_rows_from_trace(
            trace,
            row=row,
            extractor=shared_extractor,
            seed=seed + index * 1000,
            horizon_actions=horizon_actions,
            horizon_turns=horizon_turns,
            max_actions_per_state=max_actions_per_state,
            max_events=max_events_per_trace,
            winning_traces_only=winning_traces_only,
            observed_future_target_weight=observed_future_target_weight,
            include_flash_pass=include_flash_pass,
            action_kind_filter=action_kind_filter,
        )
        rows.extend(trace_rows)
        reports.append(report)
    return rows, reports


def _trace_action_events(
    trace: dict[str, Any],
    *,
    include_flash_pass: bool = False,
    action_kind_filter: Iterable[str] | None = None,
) -> Iterable[dict[str, Any]]:
    events = trace.get("logEvents") or trace.get("log_events") or []
    if not isinstance(events, list):
        return []
    wanted = {str(kind).strip() for kind in list(action_kind_filter or []) if str(kind).strip()}
    out: list[dict[str, Any]] = []
    in_attack_window = False
    for raw_event in events:
        if not isinstance(raw_event, dict):
            continue
        event_type = str(raw_event.get("type") or "")
        action_kind = str(raw_event.get("actionKind") or raw_event.get("action_kind") or "")
        if event_type == "attack_target":
            in_attack_window = True
            continue
        if event_type in {"block", "game_over"}:
            in_attack_window = False
            continue
        if event_type != "action":
            continue
        if action_kind == "end_turn":
            in_attack_window = False
        if not include_flash_pass and action_kind == "flash_pass":
            continue
        if wanted and action_kind not in wanted:
            continue
        event = dict(raw_event)
        if in_attack_window and action_kind in {"flash_pass", "play_card", "activate_flash_ability"}:
            event["traceFlashWindow"] = True
        out.append(event)
    return out


def _recorded_action(event: dict[str, Any]) -> dict[str, Any] | None:
    action = event.get("action")
    if isinstance(action, dict):
        return dict(action)
    kind = str(event.get("actionKind") or event.get("action_kind") or "")
    if not kind:
        return None
    return {"kind": kind, "payload": {}}


def _annotate_trace_row(
    state_row: dict[str, Any],
    *,
    trace: dict[str, Any],
    context: dict[str, Any],
    event: dict[str, Any],
    logged_action: Any,
    action_record: dict[str, Any],
    chosen_action_id: str,
    side: str,
    winner_side: str,
    match_id: str,
) -> None:
    tags = {str(tag) for tag in list(state_row.get("stateTags") or [])}
    tags.add("human_observed_choice")
    if winner_side == side:
        tags.add("player_win_trace")
    elif winner_side:
        tags.add("player_loss_trace")
    state_row["stateTags"] = sorted(tags)
    state_row["traceMatchId"] = match_id
    state_row["traceEventIndex"] = event.get("eventIndex")
    state_row["traceSnapshotIndex"] = event.get("snapshotIndex")
    state_row["traceWinnerSide"] = winner_side
    state_row["tracePlayerSide"] = side
    state_row["tracePlayerFirstness"] = _trace_player_firstness_with_context(trace, context, player_side=side)
    state_row["aiChallengeId"] = context.get("challenge_id") or context.get("challengeId") or trace.get("challengeId")
    state_row["humanChosenActionId"] = chosen_action_id
    state_row["humanChosenActionKind"] = str(getattr(logged_action, "kind", action_record.get("kind", "unknown")))
    state_row["humanChosenActionPayload"] = dict(getattr(logged_action, "payload", {}) or {})
    state_row["humanRecordedAction"] = action_record
    state_row["humanChosenActionSignature"] = _chosen_signature(action_record, logged_action)
    state_row["battleChosenActionId"] = chosen_action_id
    state_row["battleChosenActionKind"] = state_row["humanChosenActionKind"]


def _apply_observed_future_target_to_chosen_action(
    state_row: dict[str, Any],
    *,
    trace: dict[str, Any],
    event: dict[str, Any],
    side: str,
    winner_side: str,
    horizon_turns: int,
    weight: float,
) -> bool:
    chosen_action_id = str(state_row.get("humanChosenActionId") or state_row.get("battleChosenActionId") or "")
    chosen_action = next(
        (action for action in list(state_row.get("actions") or []) if str(action.get("actionId")) == chosen_action_id),
        None,
    )
    if chosen_action is None:
        return False
    future = _observed_future_target_delta(
        trace,
        event=event,
        side=side,
        winner_side=winner_side,
        horizon_turns=horizon_turns,
        weight=weight,
    )
    if future is None:
        return False
    targets = dict(chosen_action.get("targets") or {})
    for key in ("terminalValue", "survivalValue", "pressureValue", "planValue", "tempoValue", "resourceValue"):
        targets[key] = float(targets.get(key, 0.0) or 0.0) + float(future.get(key, 0.0) or 0.0)
    targets["observedFutureValue"] = float(targets.get("observedFutureValue", 0.0) or 0.0) + float(
        future["observedFutureValue"]
    )
    targets["observedFutureWeight"] = float(weight)
    targets["observedFutureSnapshotIndex"] = future["observedFutureSnapshotIndex"]
    targets["observedFutureTurnDelta"] = future["observedFutureTurnDelta"]
    targets["transitionValue"] = transition_value_from_targets(targets)
    chosen_action["targets"] = targets
    tags = {str(tag) for tag in list(state_row.get("stateTags") or [])}
    tags.add("observed_trace_future_target")
    state_row["stateTags"] = sorted(tags)
    return True


def _observed_future_target_delta(
    trace: dict[str, Any],
    *,
    event: dict[str, Any],
    side: str,
    winner_side: str,
    horizon_turns: int,
    weight: float,
) -> dict[str, Any] | None:
    current, future = _observed_future_snapshots(trace, event=event, horizon_turns=horizon_turns)
    if current is None or future is None:
        return None
    current_own = _snapshot_player(current, side=side, trace_player_side=_player_side(trace, {}, None))
    future_own = _snapshot_player(future, side=side, trace_player_side=_player_side(trace, {}, None))
    enemy_side = "P2" if side == "P1" else "P1"
    current_enemy = _snapshot_player(current, side=enemy_side, trace_player_side=_player_side(trace, {}, None))
    future_enemy = _snapshot_player(future, side=enemy_side, trace_player_side=_player_side(trace, {}, None))
    if current_own is None or future_own is None or current_enemy is None or future_enemy is None:
        return None

    own_life_delta = _player_life(future_own) - _player_life(current_own)
    own_force_delta = _force_life_total(future_own) - _force_life_total(current_own)
    enemy_life_damage = _player_life(current_enemy) - _player_life(future_enemy)
    enemy_force_damage = _force_life_total(current_enemy) - _force_life_total(future_enemy)
    base_delta = _zone_count(future_own, "base") - _zone_count(current_own, "base")
    field_delta = _zone_count(future_own, "field") - _zone_count(current_own, "field")

    terminal = 0.0
    plan = 0.0
    if winner_side:
        if winner_side == side:
            terminal = 2.0
            plan = 0.5
        else:
            terminal = -2.0
            plan = -0.5
    survival = 0.45 * own_life_delta + 0.25 * own_force_delta
    pressure = 0.55 * enemy_life_damage + 0.25 * enemy_force_damage
    resource = 0.6 * base_delta
    tempo = 0.35 * field_delta
    scale = float(weight)
    values = {
        "terminalValue": terminal * scale,
        "survivalValue": survival * scale,
        "pressureValue": pressure * scale,
        "planValue": plan * scale,
        "tempoValue": tempo * scale,
        "resourceValue": resource * scale,
    }
    values["observedFutureValue"] = sum(float(values[key]) for key in values)
    values["observedFutureSnapshotIndex"] = _snapshot_index(future)
    values["observedFutureTurnDelta"] = _snapshot_turn(future) - _snapshot_turn(current)
    return values


def _observed_future_snapshots(
    trace: dict[str, Any],
    *,
    event: dict[str, Any],
    horizon_turns: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    snapshots = [snapshot for snapshot in list(trace.get("stateSnapshots") or []) if isinstance(snapshot, dict)]
    if not snapshots:
        return None, None
    current_pos = _snapshot_position_for_event(snapshots, event)
    if current_pos is None:
        return None, None
    current = snapshots[current_pos]
    later = snapshots[current_pos + 1 :]
    if not later:
        return current, None
    target_turn = _snapshot_turn(current) + max(1, int(horizon_turns))
    future = next((snapshot for snapshot in later if _snapshot_turn(snapshot) >= target_turn), later[-1])
    return current, future


def _snapshot_position_for_event(snapshots: list[dict[str, Any]], event: dict[str, Any]) -> int | None:
    raw_index = event.get("snapshotIndex")
    if raw_index is None:
        return 0 if snapshots else None
    try:
        snapshot_index = int(raw_index)
    except (TypeError, ValueError):
        return None
    for pos, snapshot in enumerate(snapshots):
        if _snapshot_index(snapshot) == snapshot_index:
            return pos
    if 0 <= snapshot_index < len(snapshots):
        return snapshot_index
    return None


def _snapshot_index(snapshot: dict[str, Any]) -> int:
    try:
        return int(snapshot.get("index", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _snapshot_turn(snapshot: dict[str, Any]) -> int:
    state = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else {}
    value = snapshot.get("turn", state.get("turn", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _snapshot_player(snapshot: dict[str, Any], *, side: str, trace_player_side: str) -> dict[str, Any] | None:
    state = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else snapshot
    players = state.get("players") if isinstance(state, dict) else None
    if isinstance(players, dict):
        direct = players.get(side)
        if isinstance(direct, dict):
            return direct
        for player in players.values():
            if isinstance(player, dict) and str(player.get("side") or "").upper() == side:
                return player
        human = players.get("human")
        opponent = players.get("opponent")
        if side == trace_player_side and isinstance(human, dict):
            return human
        if side != trace_player_side and isinstance(opponent, dict):
            return opponent
    if isinstance(players, list):
        for player in players:
            if isinstance(player, dict) and str(player.get("side") or "").upper() == side:
                return player
    return None


def _player_life(player: dict[str, Any]) -> float:
    try:
        return float(player.get("life", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _zone_count(player: dict[str, Any], zone: str) -> float:
    cards = player.get(zone)
    return float(len(cards)) if isinstance(cards, list) else 0.0


def _force_life_total(player: dict[str, Any]) -> float:
    total = 0.0
    forces = player.get("forces")
    if not isinstance(forces, list):
        return 0.0
    for force in forces:
        if not isinstance(force, dict) or bool(force.get("destroyed", False)):
            continue
        try:
            total += max(0.0, float(force.get("life", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    return total


def _chosen_signature(action_record: dict[str, Any], logged_action: Any) -> dict[str, Any] | None:
    signature = action_record.get("signature")
    if isinstance(signature, dict):
        return dict(signature)
    return {"kind": str(getattr(logged_action, "kind", action_record.get("kind", "unknown"))), "payload": dict(getattr(logged_action, "payload", {}) or {})}


def _player_side(trace: dict[str, Any], row: dict[str, Any], override: str | None) -> str:
    raw = override or row.get("player_side") or row.get("playerSide") or trace.get("playerSide") or trace.get("player_side") or "P1"
    side = str(raw).strip().upper()
    return side if side in {"P1", "P2"} else "P1"


def trace_player_side(trace: dict[str, Any], row: dict[str, Any] | None = None, override: str | None = None) -> str:
    return _player_side(trace, dict(row or {}), override)


def trace_player_firstness(
    trace: dict[str, Any],
    row: dict[str, Any] | None = None,
    *,
    player_side: str | None = None,
) -> str:
    side = _player_side(trace, dict(row or {}), player_side)
    snapshots = trace.get("stateSnapshots") or trace.get("state_snapshots") or []
    if not isinstance(snapshots, list):
        return "unknown"
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        state = snapshot.get("state")
        if not isinstance(state, dict):
            continue
        players = state.get("players")
        if not isinstance(players, dict):
            continue
        for player in players.values():
            if not isinstance(player, dict):
                continue
            if str(player.get("side") or "").strip().upper() != side:
                continue
            if "isFirstPlayer" not in player:
                continue
            return "first" if bool(player.get("isFirstPlayer")) else "second"
    return "unknown"


def _trace_player_firstness_with_context(
    trace: dict[str, Any],
    context: dict[str, Any],
    *,
    player_side: str,
) -> str:
    firstness = trace_player_firstness(trace, context, player_side=player_side)
    if firstness in TRACE_PLAYER_FIRSTNESS_VALUES:
        return firstness
    raw = context.get("player_firstness") or context.get("playerFirstness") or trace.get("playerFirstness")
    fallback = str(raw or "").strip().lower()
    return fallback if fallback in TRACE_PLAYER_FIRSTNESS_VALUES else "unknown"


def _deck_id(row: dict[str, Any], trace: dict[str, Any], prefix: str, *, default: str) -> str:
    snake = f"{prefix}_deck_id"
    camel = f"{prefix}DeckId"
    value = row.get(snake) or row.get(camel) or trace.get(camel) or trace.get(snake)
    return str(value or default)


def _opponent_kind(row: dict[str, Any], trace: dict[str, Any]) -> str:
    value = (
        row.get("opponent_ai_difficulty")
        or row.get("opponentAiDifficulty")
        or trace.get("opponentAiDifficulty")
        or trace.get("opponent_ai_difficulty")
        or "unknown"
    )
    return str(value).strip().lower() or "unknown"
