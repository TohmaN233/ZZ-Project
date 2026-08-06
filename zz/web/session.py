from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zz.ai import PassOnlyPolicy
from zz.ai_registry import resolve_battle_policy
from zz.ai_runtime_stack import current_tree_baseline_runtime_weights
from zz.codeman_memory import CodemanMemoryStore
from zz.policy_factories import create_current_policy_actor_rollout_policy
from zz.decks import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
    build_deck,
    validate_forces,
)
from zz.engine import BASE_CAP, FIELD_CAP, Engine, GameOver, IllegalActionError, LIFE_CAP
from zz.effects import EffectSpec, EffectTiming, TIMING_LABELS, _target_filter
from zz.enums import AreaType, AttackTargetKind, CardType, Color, Keyword, Side, Step, TriggerTiming
from zz.forces import ALL_FORCES, Force
from zz.model import Action, AttackTarget, CardInstance, Context, ForceInstance, GameState, Player
from zz.web.assets import AssetIndex
from zz.web.profiles import normalize_profile, profile_dto
from zz.web.settings_store import normalize_ai_difficulty
from zz.web.serialize import serialize_card, serialize_force, serialize_state


USER_CONTROLLED_MODES = {"human-vs-ai", "god", "debug-card-lab"}

LOCAL_GAME_DEEP_ACTOR_POLICY_ID = (
    "ygo_cloud_incremental_20260630T171443Z_block0500_0020"
)
LOCAL_GAME_DEEP_ACTOR_SOURCE_POLICY_ID = (
    "ygo_cloud_incremental_20260630T171443Z_block0500_0019"
)
LOCAL_GAME_DEEP_ACTOR_MODEL_PATH = Path(
    "local_ai_training/retained_mainline_20260630/cycle470_actor.json"
)
LOCAL_GAME_MEDIUM_DEEP_ACTOR_MODEL_PATH = Path(
    "local_ai_training/retained_mainline_20260630/source_v3_update30_actor.json"
)


TARGETED_CARD_KINDS = {}

TARGETED_ATTACK_CARD_KINDS = {}

TARGETED_CARD_COUNTS = {}

OPTIONAL_EFFECT_TARGET_KINDS = {"deck_base_minion", "top3_magic"}

LOOK_WINDOW_SIZES = {
    "pc02_fossil_dragon": 3,
    "top3_magic": 3,
}

MANA_COLOR_CHOICES = [
    Color.RED,
    Color.YELLOW,
    Color.WHITE,
    Color.GREEN,
    Color.BLUE,
    Color.PURPLE,
]


def _local_game_deep_policy(seed: int) -> Any:
    if not LOCAL_GAME_DEEP_ACTOR_MODEL_PATH.exists():
        return resolve_battle_policy(
            "deep",
            seed=seed,
            runtime_prior_weights=current_tree_baseline_runtime_weights(),
        ).policy
    return create_current_policy_actor_rollout_policy(
        model_path=LOCAL_GAME_DEEP_ACTOR_MODEL_PATH,
        seed=seed,
        policy_id=LOCAL_GAME_DEEP_ACTOR_POLICY_ID,
        expected_candidate_policy_ids=[LOCAL_GAME_DEEP_ACTOR_POLICY_ID],
        expected_source_actor_policy_id=LOCAL_GAME_DEEP_ACTOR_SOURCE_POLICY_ID,
        min_source_rows=0,
    )

EFFECT_TARGET_FILTER_PARAMS = {
    "card_id",
    "card_ids",
    "exclude_card_id",
    "race",
    "card_type",
    "color",
    "max_cost",
    "min_cost",
    "max_bp",
    "min_bp",
    "max_dp",
    "min_dp",
}


class _QueuedHumanPolicy:
    def __init__(self):
        self._targets: list[Any] = []

    def queue_targets(self, targets: list[Any]) -> None:
        self._targets = list(targets)

    def choose(self, engine: Engine) -> Action:
        legal = engine.legal_actions()
        return legal[-1]

    def choose_flash(self, engine: Engine, legal: list[Action]) -> Action:
        return Action(kind="flash_pass")

    def choose_blocker(self, engine: Engine, attacker, blockers: list):
        return None

    def choose_attack_target(self, engine: Engine, attacker, targets: list[AttackTarget]) -> AttackTarget:
        return targets[0]

    def choose_target(self, engine: Engine, kind: str, min_n: int, max_n: int, eligible: list) -> list:
        if not self._targets:
            return []
        targets = [target for target in self._targets if target in eligible]
        selected = targets[:max_n]
        self._targets = [target for target in self._targets if target not in selected]
        return selected

    def choose_mulligan(self, engine: Engine, player) -> list[CardInstance]:
        return []


@dataclass
class _AttackFlow:
    attacker: CardInstance
    target: AttackTarget
    priority: Player
    passes: int = 0


class GameSession:
    def __init__(self, seed: int = 0, mode: str = "human-vs-ai",
                 asset_root: str | None = None, first_player: str = "human",
                 human_side: str = "P1",
                 player_recipe: dict[str, int] | None = None,
                 player_force_ids: list[str] | None = None,
                 opponent_recipe: dict[str, int] | None = None,
                 opponent_force_ids: list[str] | None = None,
                 player_profile: dict[str, Any] | None = None,
                 opponent_profile: dict[str, Any] | None = None,
                 opponent_ai_difficulty: str = "deep",
                 ai_data_root: str | None = None,
                 challenge_metadata: dict[str, Any] | None = None):
        if mode not in {"human-vs-ai", "ai-vs-ai", "god", "debug-card-lab"}:
            raise ValueError(f"unsupported mode {mode!r}")
        self.seed = seed
        self.mode = mode
        self.asset_index = AssetIndex(asset_root)
        self.rng = random.Random(seed)
        self.human_policy = _QueuedHumanPolicy()
        self.human_side = "P2" if str(human_side or "").upper() == "P2" else "P1"
        self.opponent_ai_difficulty = normalize_ai_difficulty(opponent_ai_difficulty)
        self.codeman_memory_store = CodemanMemoryStore(ai_data_root)
        self._codeman_memory_recorded = False
        self._ai_challenge_recorded = False
        self.challenge_metadata = dict(challenge_metadata or {})
        self._player_profile = normalize_profile(player_profile)
        self._opponent_profile = normalize_profile(opponent_profile)
        self.ai_policies = []
        if mode in {"human-vs-ai", "ai-vs-ai"}:
            opponent_policy = (
                self._policy_for_player_profile(
                    self._opponent_profile,
                    seed=seed + 2,
                    default_kind="deep",
                )
                if mode == "ai-vs-ai"
                else self._policy_for_opponent_profile(
                    self._opponent_profile,
                    seed=seed + 2,
                )
            )
            self.ai_policies = [
                self._policy_for_player_profile(
                    self._player_profile,
                    seed=seed + 1,
                    default_kind="deep",
                ),
                opponent_policy,
            ]
        self.prompt: dict | None = None
        self._options: dict[str, Any] = {}
        self._prompt_counter = 0
        self._log: list[str] = []
        self._log_events: list[dict[str, Any]] = []
        self._codeman_trace_events: list[dict[str, Any]] = []
        self._codeman_trace_snapshots: list[dict[str, Any]] = []
        self._public_reveals: list[dict[str, Any]] = []
        self._animation_events: list[dict[str, Any]] = []
        self._visual_snapshot: dict[str, Any] | None = None
        self._game_over: dict | None = None
        self._attack: _AttackFlow | None = None
        self._pending_effect: dict[str, Any] | None = None
        self._prompted_trigger_resolution: tuple[CardInstance, EffectSpec] | None = None
        self._prompted_source_effect_resolution: tuple[CardInstance, EffectSpec] | None = None
        self.debug_control_both = False
        self._player_recipe = player_recipe
        self._player_force_ids = player_force_ids
        self._opponent_recipe = opponent_recipe
        self._opponent_force_ids = opponent_force_ids
        self._build_game(first_player=first_player)
        self._refresh_visual_snapshot()
        self._codeman_trace_snapshots.append(self._codeman_trace_snapshot(label="initial"))

    @property
    def human(self) -> Player | None:
        if self.mode == "ai-vs-ai":
            return None
        if self.mode == "human-vs-ai" and self.human_side == "P2":
            return self.engine.state.players[1]
        return self.engine.state.players[0]

    def _is_user_controlled(self, player: Player) -> bool:
        if self.debug_control_both:
            return True
        if self.mode == "god":
            return True
        if self.mode == "debug-card-lab":
            return player is self.engine.state.players[0]
        return self.mode == "human-vs-ai" and player is self.human

    def _policy_for_player_profile(self, profile: dict[str, Any], *, seed: int, default_kind: str) -> Any:
        codeman_id = profile.get("codemanId") if isinstance(profile, dict) else None
        if codeman_id:
            return resolve_battle_policy(
                "codeman",
                seed=seed,
                codeman_id=str(codeman_id),
                data_root=self.codeman_memory_store.root,
                deep_model_path=LOCAL_GAME_DEEP_ACTOR_MODEL_PATH,
            ).policy
        return self._policy_for_difficulty(default_kind, seed=seed)

    def _policy_for_opponent_profile(self, profile: dict[str, Any], *, seed: int) -> Any:
        codeman_id = profile.get("codemanId") if isinstance(profile, dict) else None
        if self.opponent_ai_difficulty == "deep" and codeman_id:
            return resolve_battle_policy(
                "codeman",
                seed=seed,
                codeman_id=str(codeman_id),
                data_root=self.codeman_memory_store.root,
                deep_model_path=LOCAL_GAME_DEEP_ACTOR_MODEL_PATH,
            ).policy
        return self._policy_for_difficulty(self.opponent_ai_difficulty, seed=seed)

    def _policy_for_difficulty(self, kind: str, *, seed: int) -> Any:
        resolved = normalize_ai_difficulty(kind)
        if resolved == "deep":
            return _local_game_deep_policy(seed)
        if resolved == "normal":
            return resolve_battle_policy(
                "deep",
                seed=seed,
                deep_model_path=LOCAL_GAME_MEDIUM_DEEP_ACTOR_MODEL_PATH,
            ).policy
        return resolve_battle_policy(
            resolved,
            seed=seed,
            runtime_prior_weights=self._runtime_weights_for_difficulty(resolved),
        ).policy

    @staticmethod
    def _runtime_weights_for_difficulty(kind: str) -> dict[str, Any] | None:
        return current_tree_baseline_runtime_weights() if str(kind or "").lower() == "deep" else None

    def _build_game(self, first_player: str) -> None:
        p1_first, dice_event = self._resolve_first_player(first_player)
        if self.mode == "human-vs-ai":
            p1_name, p2_name = ("AI", "You") if self.human_side == "P2" else ("You", "AI")
        elif self.mode == "debug-card-lab":
            p1_name, p2_name = "Debug", "Pass Bot"
        elif self.mode == "god":
            p1_name, p2_name = "Player 1", "Player 2"
        else:
            p1_name, p2_name = "AI 1", "AI 2"
        p1 = Player(name=p1_name, side=Side.P1, is_first_player=p1_first)
        p2 = Player(name=p2_name, side=Side.P2, is_first_player=not p1_first)
        if self.mode == "human-vs-ai" and self.human_side == "P2":
            p1.profile = profile_dto(self._opponent_profile, self.asset_index)
            p2.profile = profile_dto(self._player_profile, self.asset_index)
        else:
            p1.profile = profile_dto(self._player_profile, self.asset_index)
            p2.profile = profile_dto(self._opponent_profile, self.asset_index)
        state = GameState(players=[p1, p2], active_idx=0 if p1_first else 1)
        self.engine = Engine(state, rng=self.rng)
        state.engine = self.engine
        self.engine.defer_force_base_choice = self._is_user_controlled
        self.engine.defer_blessing_base_choice = self._is_user_controlled
        self.engine.defer_trigger_choice = self._defer_trigger_choice
        self.engine.defer_source_effect_choice = self._defer_source_effect_choice
        self._configure_mode_controls()
        player_specs = (
            (
                p1,
                self._opponent_recipe or DEMETE_GREEN_RECIPE,
                self._opponent_force_ids or DECKCODE0_GREEN_FORCES,
            ),
            (
                p2,
                self._player_recipe or KANATANA_YELLOW_RECIPE,
                self._player_force_ids or DECKCODE0_YELLOW_FORCES,
            ),
        ) if self.mode == "human-vs-ai" and self.human_side == "P2" else (
            (
                p1,
                self._player_recipe or KANATANA_YELLOW_RECIPE,
                self._player_force_ids or DECKCODE0_YELLOW_FORCES,
            ),
            (
                p2,
                self._opponent_recipe or DEMETE_GREEN_RECIPE,
                self._opponent_force_ids or DECKCODE0_GREEN_FORCES,
            ),
        )
        for player, recipe, force_ids in player_specs:
            validate_forces(force_ids)
            player.deck = build_deck(
                recipe,
                owner=player,
                iid_factory=self.engine.state.allocate_iid,
            )
            self.rng.shuffle(player.deck)
            self.engine.deal_opening_hand(player)
            self.engine.install_forces(player, [
                ForceInstance(force=ALL_FORCES[fid], owner=player,
                              life=ALL_FORCES[fid].initial_life)
                for fid in force_ids
            ])
        if dice_event is not None:
            self._queue_animation_event(dice_event)
        if self.mode == "human-vs-ai":
            ai = p1 if self.human_side == "P2" else p2
            self.engine.mulligan(ai, self.engine.policy_for(ai).choose_mulligan(self.engine, ai))
            self._prompt_mulligan(p2 if self.human_side == "P2" else p1)
        elif self.mode == "god":
            self._prompt_mulligan(p1)
        elif self.mode == "debug-card-lab":
            self.engine.mulligan(p2, [])
            self.prompt = None
            self._options = {}
        else:
            for player in (p1, p2):
                self.engine.mulligan(player, self.engine.policy_for(player).choose_mulligan(self.engine, player))
            self._safe_begin_turn()

    def _configure_mode_controls(self) -> None:
        self.engine.ignore_hand_cap = self.mode == "debug-card-lab"
        if self.mode == "human-vs-ai":
            if self.human_side == "P2":
                self.engine.set_policies(self.ai_policies[1], self.human_policy)
            else:
                self.engine.set_policies(self.human_policy, self.ai_policies[1])
        elif self.mode == "god":
            self.engine.set_policies(self.human_policy, self.human_policy)
        elif self.mode == "debug-card-lab":
            self.engine.set_policies(self.human_policy, PassOnlyPolicy())
        else:
            self.engine.set_policies(self.ai_policies[0], self.ai_policies[1])

    def _rename_players_for_mode(self) -> None:
        p1, p2 = self.engine.state.players
        if self.mode == "human-vs-ai":
            p1.name, p2.name = ("AI", "You") if self.human_side == "P2" else ("You", "AI")
        elif self.mode == "god":
            p1.name, p2.name = "Player 1", "Player 2"
        elif self.mode == "debug-card-lab":
            p1.name, p2.name = "Debug", "Pass Bot"
        else:
            p1.name, p2.name = "AI 1", "AI 2"

    def set_mode(self, mode: str) -> None:
        if mode not in {"human-vs-ai", "ai-vs-ai", "god", "debug-card-lab"}:
            raise ValueError(f"unsupported mode {mode!r}")
        self.mode = mode
        if mode != "debug-card-lab":
            self.debug_control_both = False
        self._rename_players_for_mode()
        self._configure_mode_controls()
        if self._game_over is not None:
            return
        self._settle_uncontrolled_mulligans()
        if self.prompt is not None and not self._prompt_is_user_controlled():
            self._clear_prompt()
        if self.prompt is None and self.mode in USER_CONTROLLED_MODES:
            self._advance_after_user_choice(limit=200)

    def _settle_uncontrolled_mulligans(self) -> None:
        for player in self.engine.state.players:
            if player.mulligan_done or self._is_user_controlled(player):
                continue
            self.engine.mulligan(player, self.engine.policy_for(player).choose_mulligan(self.engine, player))
        if all(player.mulligan_done for player in self.engine.state.players) and self.engine.state.step is Step.START:
            self._clear_prompt()
            self._safe_begin_turn()

    def _prompt_controller(self) -> Player | None:
        if self.prompt is None:
            return None
        side_name = self.prompt.get("playerSide")
        if side_name:
            return next((player for player in self.engine.state.players if player.side.name == side_name), None)
        kind = self.prompt.get("kind")
        if kind == "main_action":
            return self.engine.state.active
        if kind == "attack_target" and self._attack is not None:
            return self._attack.attacker.owner
        if kind == "flash_action" and self._attack is not None:
            return self._attack.priority
        if kind == "blocker":
            return self.engine.state.opponent
        return None

    def _prompt_is_user_controlled(self) -> bool:
        if self.prompt is None:
            return False
        if self.prompt.get("kind") == "game_over":
            return True
        player = self._prompt_controller()
        return player is None or self._is_user_controlled(player)

    def _resolve_first_player(self, first_player: str) -> tuple[bool, dict[str, Any] | None]:
        if first_player == "roll":
            value = self.rng.randint(1, 6)
            first_seat = "left" if value % 2 == 1 else "right"
            return first_seat == "left", {
                "type": "dice_roll",
                "value": value,
                "firstSeat": first_seat,
            }
        return first_player != "ai", None

    def _safe_begin_turn(self) -> None:
        before = self._visual_state_snapshot()
        try:
            self.engine.begin_turn()
            self._record_visual_changes(before)
        except GameOver as exc:
            self._record_visual_changes(before)
            self._set_game_over(exc)

    def _set_game_over(self, exc: GameOver) -> None:
        self._record_visual_changes()
        self._queue_animation_event({
            "type": "game_result",
            "winnerSide": None if exc.winner is None else exc.winner.side.name,
        })
        self._game_over = {
            "winner": None if exc.winner is None else exc.winner.name,
            "reason": exc.reason,
        }
        self.prompt = {
            "id": self._next_prompt_id(),
            "kind": "game_over",
            "message": exc.reason,
            "options": [],
        }
        self._options = {}
        self._log_event(f"Game over: {exc.reason}", {
            "type": "game_over",
            "winnerName": None if exc.winner is None else exc.winner.name,
            "winnerSide": None if exc.winner is None else exc.winner.side.name,
            "reason": exc.reason,
        })
        self._record_ai_challenge_memory(exc)
        self._record_codeman_memory(exc)

    def _record_ai_challenge_memory(self, exc: GameOver) -> None:
        if self._ai_challenge_recorded or not self.challenge_metadata:
            return
        self._ai_challenge_recorded = True
        winner_side = None if exc.winner is None else exc.winner.side.name
        players = list(getattr(self.engine.state, "players", []))
        if not players:
            return
        player = self.human or players[0]
        opponent = players[1 - players.index(player)] if len(players) == 2 else None
        challenge_id = str(self.challenge_metadata.get("challengeId") or "ai_challenge")
        opponent_deck_id = str(self.challenge_metadata.get("opponentDeckId") or "opponent")
        match_id = (
            f"challenge-{self._safe_trace_component(challenge_id)}-"
            f"{self._safe_trace_component(opponent_deck_id)}-{self.seed}-{self.engine.state.turn}"
        )
        row = {
            "schema": 1,
            "kind": "ai_challenge_game",
            "challenge_id": challenge_id,
            "match_id": match_id,
            "mode": self.mode,
            "seed": self.seed,
            "player_side": player.side.name,
            "winner_side": winner_side,
            "turns": self.engine.state.turn,
            "reason": exc.reason,
            "opponent_ai_difficulty": self.opponent_ai_difficulty,
            "player_deck_id": self.challenge_metadata.get("playerDeckId"),
            "player_deck_name": self.challenge_metadata.get("playerDeckName"),
            "opponent_deck_id": self.challenge_metadata.get("opponentDeckId"),
            "opponent_deck_name": self.challenge_metadata.get("opponentDeckName"),
            "opponent_index": self.challenge_metadata.get("opponentIndex"),
            "collection_plan_matched": self.challenge_metadata.get("collectionPlanMatched"),
            "collection_plan_reason": self.challenge_metadata.get("collectionPlanReason"),
            "collection_plan_item": self.challenge_metadata.get("collectionPlanItem"),
            "recommended_next_at_start": self.challenge_metadata.get("recommendedNextAtStart"),
            "player_forces": self._force_ids(player),
            "opponent_forces": self._force_ids(opponent),
            "player_deck_recipe": self._deck_recipe_for_player(player),
            "opponent_deck_recipe": self._deck_recipe_for_player(opponent),
            "trace_path": None,
        }
        row["trace_path"] = self._write_ai_challenge_trace(row)
        try:
            path = self.codeman_memory_store.root / "ai_challenges" / "memory.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True))
                handle.write("\n")
            self._prune_ai_challenge_memory(path, keep=20)
        except OSError:
            return

    def _prune_ai_challenge_memory(self, path: Path, *, keep: int) -> None:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        keep_count = max(0, int(keep))
        retained = rows[-keep_count:] if keep_count else []
        for row in rows[: len(rows) - len(retained)]:
            raw = row.get("trace_path") if isinstance(row, dict) else None
            if not isinstance(raw, str) or not raw:
                continue
            trace_path = self.codeman_memory_store.root / raw
            try:
                if trace_path.resolve().is_relative_to(self.codeman_memory_store.root.resolve()):
                    trace_path.unlink(missing_ok=True)
            except OSError:
                continue
        with path.open("w", encoding="utf-8") as handle:
            for row in retained:
                handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True))
                handle.write("\n")

    def _write_ai_challenge_trace(self, row: dict[str, Any]) -> str | None:
        match_id = str(row.get("match_id") or "challenge-match")
        safe_match_id = self._safe_trace_component(match_id)
        if not safe_match_id:
            return None
        trace_rel = Path("ai_challenges") / "traces" / f"{safe_match_id}.json"
        trace_path = self.codeman_memory_store.root / trace_rel
        payload = {
            "schema": 1,
            "kind": "ai_challenge_trace",
            "matchId": match_id,
            "challenge": dict(self.challenge_metadata),
            "mode": row.get("mode"),
            "seed": row.get("seed"),
            "playerSide": row.get("player_side"),
            "winnerSide": row.get("winner_side"),
            "turns": row.get("turns"),
            "reason": row.get("reason"),
            "opponentAiDifficulty": row.get("opponent_ai_difficulty"),
            "collectionPlanMatched": row.get("collection_plan_matched"),
            "collectionPlanReason": row.get("collection_plan_reason"),
            "collectionPlanItem": row.get("collection_plan_item"),
            "recommendedNextAtStart": row.get("recommended_next_at_start"),
            "playerForces": list(row.get("player_forces") or []),
            "opponentForces": list(row.get("opponent_forces") or []),
            "playerDeckRecipe": dict(row.get("player_deck_recipe") or {}),
            "opponentDeckRecipe": dict(row.get("opponent_deck_recipe") or {}),
            "logText": list(self._log),
            "logEvents": list(self._codeman_trace_events),
            "stateSnapshots": list(self._codeman_trace_snapshots),
        }
        try:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(
                json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str),
                encoding="utf-8",
            )
        except OSError:
            return None
        return trace_rel.as_posix()

    def _record_codeman_memory(self, exc: GameOver) -> None:
        if self._codeman_memory_recorded:
            return
        self._codeman_memory_recorded = True
        winner_side = None if exc.winner is None else exc.winner.side.name
        players = list(getattr(self.engine.state, "players", []))
        if not players:
            return
        if self.mode == "human-vs-ai" and self.human in players:
            index = players.index(self.human)
        else:
            index = 0
        player = players[index]
        codeman_id = self._player_codeman_id(player)
        if not codeman_id:
            return
        opponent = players[1 - index] if len(players) == 2 else None
        row = {
            "match_id": f"web-{self.seed}-{self.engine.state.turn}-{index}",
            "mode": self.mode,
            "seed": self.seed,
            "player_seat": index,
            "player_side": player.side.name,
            "winner_side": winner_side,
            "turns": self.engine.state.turn,
            "reason": exc.reason,
            "opponent_ai_difficulty": self.opponent_ai_difficulty,
            "player_forces": self._force_ids(player),
            "opponent_forces": self._force_ids(opponent) if opponent is not None else [],
            "player_deck_recipe": self._deck_recipe_for_player(player),
            "opponent_deck_recipe": self._deck_recipe_for_player(opponent) if opponent is not None else {},
            "trace_path": None,
        }
        row["trace_path"] = self._write_codeman_trace(codeman_id, row)
        try:
            self.codeman_memory_store.append_game(codeman_id, row)
        except Exception:
            return

    def _write_codeman_trace(self, codeman_id: str, row: dict[str, Any]) -> str | None:
        safe_id = self._safe_trace_component(codeman_id)
        match_id = str(row.get("match_id") or "match")
        safe_match_id = self._safe_trace_component(match_id)
        if not safe_id or not safe_match_id:
            return None
        trace_rel = Path("codeman_ai") / safe_id / "traces" / f"{safe_match_id}.json"
        trace_path = self.codeman_memory_store.root / trace_rel
        payload = {
            "schema": 2,
            "kind": "codeman_game_trace",
            "matchId": match_id,
            "codemanId": safe_id,
            "mode": row.get("mode"),
            "seed": row.get("seed"),
            "playerSeat": row.get("player_seat"),
            "playerSide": row.get("player_side"),
            "winnerSide": row.get("winner_side"),
            "turns": row.get("turns"),
            "reason": row.get("reason"),
            "opponentAiDifficulty": row.get("opponent_ai_difficulty"),
            "playerForces": list(row.get("player_forces") or []),
            "opponentForces": list(row.get("opponent_forces") or []),
            "playerDeckRecipe": dict(row.get("player_deck_recipe") or {}),
            "opponentDeckRecipe": dict(row.get("opponent_deck_recipe") or {}),
            "logText": list(self._log),
            "logEvents": list(self._codeman_trace_events),
            "stateSnapshots": list(self._codeman_trace_snapshots),
        }
        try:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(
                json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str),
                encoding="utf-8",
            )
        except OSError:
            return None
        return trace_rel.as_posix()

    def _safe_trace_component(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
        return safe.strip("._")

    def _player_codeman_id(self, player: Player) -> str | None:
        profile = getattr(player, "profile", None)
        if isinstance(profile, dict):
            codeman_id = profile.get("codemanId")
            if codeman_id:
                return str(codeman_id)
        return None

    def _force_ids(self, player: Player | None) -> list[str]:
        if player is None:
            return []
        return [
            str(force.force.id)
            for force in getattr(player, "forces", [])
            if getattr(getattr(force, "force", None), "id", None)
        ]

    def _deck_recipe_for_player(self, player: Player | None) -> dict[str, int]:
        if player is None:
            return {}
        if player is self.engine.state.players[0]:
            return dict(self._player_recipe or KANATANA_YELLOW_RECIPE)
        if player is self.engine.state.players[1]:
            return dict(self._opponent_recipe or DEMETE_GREEN_RECIPE)
        return {}

    def _next_prompt_id(self) -> str:
        self._prompt_counter += 1
        return f"p{self._prompt_counter}"

    def _set_prompt(self, kind: str, message: str, options: list[tuple[str, str, Any, dict | None]] | list[tuple[str, str, Any]]) -> None:
        prompt_id = self._next_prompt_id()
        public_options = []
        self._options = {}
        for raw in options:
            if len(raw) == 3:
                option_id, label, value = raw
                meta = {}
            else:
                option_id, label, value, meta = raw
            self._options[option_id] = value
            public = {"id": option_id, "label": label}
            public.update(meta)
            public_options.append(public)
        self.prompt = {
            "id": prompt_id,
            "kind": kind,
            "message": message,
            "options": public_options,
        }

    def _clear_prompt(self) -> None:
        self.prompt = None
        self._options = {}

    def _log_event(self, text: str, event: dict[str, Any] | None = None) -> None:
        self._log.append(text)
        payload = dict(event or {"type": "raw"})
        event_index = len(self._codeman_trace_events)
        snapshot_index = len(self._codeman_trace_snapshots)
        payload.setdefault("rawText", text)
        payload.setdefault("turn", self.engine.state.turn)
        payload.setdefault("phase", self.engine.state.phase.value)
        payload.setdefault("step", self.engine.state.step.value)
        payload.setdefault("activeSide", self.engine.state.active.side.name)
        payload["eventIndex"] = event_index
        payload["snapshotIndex"] = snapshot_index
        self._log_events.append(payload)
        self._codeman_trace_events.append(dict(payload))
        self._codeman_trace_snapshots.append(
            self._codeman_trace_snapshot(
                label=text,
                event_index=event_index,
            )
        )
        if len(self._log) > 80:
            del self._log[:-80]
        if len(self._log_events) > 80:
            del self._log_events[:-80]

    def _codeman_trace_snapshot(self, *, label: str, event_index: int | None = None) -> dict[str, Any]:
        state = serialize_state(
            self.engine,
            human=None,
            asset_index=self.asset_index,
            prompt=None,
            log=list(self._log),
            log_events=list(self._log_events),
            mode=self.mode,
            game_over=self._game_over,
            reveal_all_hands=True,
            animation_events=[],
        )
        state["seed"] = self.seed
        state["opponentAiDifficulty"] = self.opponent_ai_difficulty
        if self.challenge_metadata:
            state["aiChallenge"] = dict(self.challenge_metadata)
        state["debugControlBoth"] = self.debug_control_both
        state = self._compact_codeman_trace_state(state)
        return {
            "schema": 2,
            "index": len(self._codeman_trace_snapshots),
            "eventIndex": event_index,
            "label": str(label),
            "turn": self.engine.state.turn,
            "phase": self.engine.state.phase.value,
            "step": self.engine.state.step.value,
            "activeSide": self.engine.state.active.side.name,
            "animationEvents": list(self._animation_events),
            "state": state,
        }

    def _compact_codeman_trace_state(self, state: dict[str, Any]) -> dict[str, Any]:
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
                key: self._compact_codeman_trace_player(value)
                for key, value in players.items()
                if isinstance(value, dict)
            }
        return compact

    def _compact_codeman_trace_player(self, player: dict[str, Any]) -> dict[str, Any]:
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
                self._compact_codeman_trace_card(card)
                for card in player.get(key, [])
                if isinstance(card, dict)
            ]
        compact["forces"] = [
            self._compact_codeman_trace_force(force)
            for force in player.get("forces", [])
            if isinstance(force, dict)
        ]
        return compact

    def _compact_codeman_trace_card(self, card: dict[str, Any]) -> dict[str, Any]:
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

    def _compact_codeman_trace_force(self, force: dict[str, Any]) -> dict[str, Any]:
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

    def _card_log_payload(self, ci: CardInstance | None) -> dict[str, Any] | None:
        if ci is None:
            return None
        return serialize_card(self.engine, ci, self.asset_index)

    def _force_log_payload(self, fi: ForceInstance | None) -> dict[str, Any] | None:
        if fi is None:
            return None
        return serialize_force(self.engine, fi, self.asset_index)

    def _player_log_payload(self, player: Player) -> dict[str, str]:
        return {"playerName": player.name, "playerSide": player.side.name}

    def _find_card_for_action(self, actor: Player, action: Action) -> CardInstance | None:
        iid = action.payload.get("iid") or action.payload.get("attacker_iid")
        if iid is None:
            return None
        zones = actor.hand + actor.base + actor.field
        if action.kind == "activate_flash_ability":
            zones = self.engine.state.active.field + self.engine.state.opponent.field
        try:
            return self.engine._find(zones, iid)
        except IllegalActionError:
            return None

    def _replacement_card_for_action(self, actor: Player, action: Action) -> CardInstance | None:
        if "replace_base_iid" in action.payload:
            try:
                return self.engine._find(actor.base, action.payload["replace_base_iid"])
            except IllegalActionError:
                return None
        if "replace_field_iid" in action.payload:
            try:
                return self.engine._find(actor.field, action.payload["replace_field_iid"])
            except IllegalActionError:
                return None
        return None

    def _action_log_event(self, actor: Player, action: Action, label: str) -> dict[str, Any]:
        event: dict[str, Any] = {
            "type": "action",
            "actorName": actor.name,
            "actorSide": actor.side.name,
            "actionKind": action.kind,
            "label": label,
        }
        try:
            from zz.rl_training import _action_to_dict

            event["action"] = _action_to_dict(action, engine=self.engine, player=actor)
        except Exception:
            event["action"] = {"kind": action.kind, "payload": dict(action.payload)}
        card = self._find_card_for_action(actor, action)
        if card is not None:
            event["card"] = self._card_log_payload(card)
        replacement = self._replacement_card_for_action(actor, action)
        if replacement is not None:
            event["replacementCard"] = self._card_log_payload(replacement)
        if action.kind == "swap_mana_color":
            event["newColor"] = Color(action.payload["new_color"]).name
        if action.kind == "move_card":
            event["direction"] = action.payload.get("direction")
        return event

    def _target_log_payload(self, target: AttackTarget) -> dict[str, Any]:
        if target.kind is AttackTargetKind.PLAYER:
            return {
                "type": "player",
                "playerName": target.ref.name,
                "playerSide": target.ref.side.name,
            }
        if target.kind is AttackTargetKind.FORCE:
            return {
                "type": "force",
                "force": self._force_log_payload(target.ref),
            }
        return {
            "type": "minion",
            "card": self._card_log_payload(target.ref),
        }

    def _target_animation_payload(self, target: AttackTarget) -> dict[str, Any]:
        if target.kind is AttackTargetKind.PLAYER:
            return {
                "targetKind": "player",
                "targetSide": target.ref.side.name,
                "targetForceId": None,
                "targetCardIid": None,
            }
        if target.kind is AttackTargetKind.FORCE:
            return {
                "targetKind": "force",
                "targetSide": target.ref.owner.side.name,
                "targetForceId": target.ref.force.id,
                "targetCardIid": None,
            }
        return {
            "targetKind": "card",
            "targetSide": target.ref.owner.side.name,
            "targetForceId": None,
            "targetCardIid": target.ref.iid,
        }

    def _queue_attack_animation_event(self, attacker: CardInstance, target: AttackTarget) -> None:
        event = {
            "type": "attack",
            "side": attacker.owner.side.name,
            "attacker": self._card_log_payload(attacker),
            "attackerIid": attacker.iid,
        }
        event.update(self._target_animation_payload(target))
        self._queue_animation_event(event)

    def _pending_attack_payload(self) -> dict[str, Any] | None:
        if self._attack is None or self._attack.target is None:
            return None
        event = {
            "type": "attack",
            "side": self._attack.attacker.owner.side.name,
            "attacker": self._card_log_payload(self._attack.attacker),
            "attackerIid": self._attack.attacker.iid,
        }
        event.update(self._target_animation_payload(self._attack.target))
        return event

    def _queue_block_animation_event(self, attacker: CardInstance, blocker: CardInstance) -> None:
        self._queue_animation_event({
            "type": "block",
            "side": attacker.owner.side.name,
            "targetSide": blocker.owner.side.name,
            "attacker": self._card_log_payload(attacker),
            "attackerIid": attacker.iid,
            "blocker": self._card_log_payload(blocker),
            "blockerIid": blocker.iid,
        })

    def _visual_state_snapshot(self) -> dict[str, Any]:
        players = {}
        forces = {}
        for player in self.engine.state.players:
            side = player.side.name
            players[side] = player.life
            for index, force in enumerate(player.forces):
                key = f"{side}:{index}:{force.force.id}"
                forces[key] = {
                    "side": side,
                    "forceId": force.force.id,
                    "life": force.life,
                    "destroyed": force.destroyed,
                }
        return {
            "turn": self.engine.state.turn,
            "activeSide": self.engine.state.active.side.name,
            "phase": self.engine.state.phase.value,
            "step": self.engine.state.step.value,
            "players": players,
            "forces": forces,
        }

    def _refresh_visual_snapshot(self) -> None:
        self._visual_snapshot = self._visual_state_snapshot()

    def _queue_animation_event(self, event: dict[str, Any]) -> None:
        self._animation_events.append(event)

    def _zone_move_summon_fx(self, from_area: AreaType, to_area: AreaType) -> str | None:
        if to_area is not AreaType.FIELD:
            return None
        if from_area is AreaType.TRASH:
            return "graveyard"
        if from_area is AreaType.HAND:
            return "hand"
        return None

    def _queue_zone_move_animation_event(
            self,
            ci: CardInstance,
            from_area: AreaType,
            to_area: AreaType,
    ) -> None:
        if from_area is to_area:
            return
        event = {
            "type": "zone_move",
            "side": ci.owner.side.name,
            "fromArea": from_area.value,
            "toArea": to_area.value,
            "card": serialize_card(self.engine, ci, self.asset_index),
        }
        summon_fx = self._zone_move_summon_fx(from_area, to_area)
        if summon_fx is not None:
            event["summonFx"] = summon_fx
        self._queue_animation_event(event)

    def _effect_text_segments(self, text: str) -> list[tuple[tuple[str, ...], str]]:
        lines = (text or "").splitlines()
        segments: list[tuple[tuple[str, ...], list[str]]] = []
        current_markers: tuple[str, ...] = ()
        current_lines: list[str] = []
        marker_pattern = re.compile(r"【([^】]+)】|［([^］]+)］|\[([^\]]+)\]")
        for line in lines:
            stripped = line.strip()
            raw_markers = [
                next(part for part in match.groups() if part)
                for match in marker_pattern.finditer(stripped)
            ]
            marker_parts: list[str] = []
            for marker in raw_markers:
                marker_parts.append(marker)
                marker_parts.extend(part for part in re.split(r"[／/・：:]", marker) if part)
            markers = tuple(dict.fromkeys(marker_parts))
            if markers:
                if current_markers or current_lines:
                    segments.append((current_markers, current_lines))
                current_markers = markers
                current_lines = [stripped]
            else:
                current_lines.append(stripped)
        if current_markers or current_lines:
            segments.append((current_markers, current_lines))
        return [
            (markers, "\n".join(part for part in segment_lines if part).strip())
            for markers, segment_lines in segments
            if any(part.strip() for part in segment_lines)
        ]

    def _effect_marker_candidates(self, timing: EffectTiming | None, timing_label: str | None) -> set[str]:
        candidates = {timing_label} if timing_label else set()
        if timing is EffectTiming.ON_CAST_MAGIC:
            candidates.update({"メイン", "フラッシュ"})
        for label in list(candidates):
            candidates.update(part for part in re.split(r"[／/・：:]", label or "") if part)
        return {candidate for candidate in candidates if candidate}

    def _effect_event_text(self, ci: CardInstance, effect: Any, ctx: Context | None = None) -> str | None:
        timing = getattr(effect, "timing", getattr(effect, "when", None))
        continuous_markers = {"常時", "自分のターン", "相手のターン"}
        timing_label = getattr(effect, "official_timing", None) or TIMING_LABELS.get(timing)
        if timing is EffectTiming.CONTINUOUS or timing_label in continuous_markers:
            return None
        official_effect = getattr(effect, "official_effect", None)
        official_condition = getattr(effect, "official_condition", None)
        ability = getattr(ci.card, "ability_jp", "") or getattr(ci.card, "ability_en", "")
        if ability:
            wanted = self._effect_marker_candidates(timing, timing_label)
            wanted.update(self._effect_marker_candidates(None, official_condition))
            segments = self._effect_text_segments(ability)
            if segments:
                for markers, segment in segments:
                    if wanted.intersection(markers):
                        if continuous_markers.intersection(markers):
                            return None
                        return segment
                return None
            return ability
        prefix = "".join(f"【{part}】" for part in (timing_label, official_condition, official_effect) if part)
        template_id = getattr(effect, "template_id", None)
        return prefix or str(template_id or timing_label or "Effect")

    def _drain_effect_events(self) -> None:
        while self.engine.effect_events:
            ci, effect, ctx = self.engine.effect_events.pop(0)
            text = self._effect_event_text(ci, effect, ctx)
            if not text:
                continue
            self._queue_animation_event({
                "type": "effect",
                "side": ci.owner.side.name,
                "card": serialize_card(self.engine, ci, self.asset_index),
                "effectText": text,
            })

    def _drain_destroy_events(self) -> None:
        while self.engine.destroy_events:
            ci = self.engine.destroy_events.pop(0)
            self._queue_animation_event({
                "type": "destroy",
                "side": ci.owner.side.name,
                "card": serialize_card(self.engine, ci, self.asset_index),
            })

    def _animation_event_from_engine_visual_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = event.get("type")
        if event_type == "effect":
            ci = event["card"]
            text = self._effect_event_text(ci, event.get("effect"), event.get("ctx"))
            if not text:
                return None
            return {
                "type": "effect",
                "side": ci.owner.side.name,
                "card": serialize_card(self.engine, ci, self.asset_index),
                "effectText": text,
            }
        if event_type == "destroy":
            ci = event["card"]
            return {
                "type": "destroy",
                "side": ci.owner.side.name,
                "card": serialize_card(self.engine, ci, self.asset_index),
            }
        if event_type == "zone_move":
            ci = event["card"]
            from_area = event["from"]
            to_area = event["to"]
            if from_area is AreaType.DECK and to_area is AreaType.HAND:
                return {
                    "type": "draw",
                    "side": ci.owner.side.name,
                    "playerKey": self._player_key(ci.owner),
                    "count": 1,
                    "cards": [serialize_card(self.engine, ci, self.asset_index)],
                }
            animation_event = {
                "type": "zone_move",
                "side": ci.owner.side.name,
                "fromArea": from_area.value,
                "toArea": to_area.value,
                "card": serialize_card(self.engine, ci, self.asset_index),
            }
            summon_fx = self._zone_move_summon_fx(from_area, to_area)
            if summon_fx is not None:
                animation_event["summonFx"] = summon_fx
            return animation_event
        if event_type in {"turn_begin", "phase", "damage", "heal"}:
            return dict(event)
        return None

    def _life_event_key(self, event: dict[str, Any]) -> tuple[str, str, str | None] | None:
        if event.get("type") not in {"damage", "heal"}:
            return None
        return (
            str(event.get("targetKind") or ""),
            str(event.get("side") or ""),
            None if event.get("forceId") is None else str(event.get("forceId")),
        )

    def _drain_ordered_engine_visual_events(self) -> set[tuple[str, str, str | None]] | None:
        if not getattr(self.engine, "visual_events", None):
            return None
        covered_life_events: set[tuple[str, str, str | None]] = set()
        while self.engine.visual_events:
            event = self.engine.visual_events.pop(0)
            animation_event = self._animation_event_from_engine_visual_event(event)
            if animation_event is None:
                continue
            life_key = self._life_event_key(animation_event)
            if life_key is not None:
                covered_life_events.add(life_key)
            self._queue_animation_event(animation_event)
        self.engine.zone_move_events.clear()
        self.engine.effect_events.clear()
        self.engine.destroy_events.clear()
        return covered_life_events

    def _drain_zone_move_events(self) -> None:
        while self.engine.zone_move_events:
            event = self.engine.zone_move_events.pop(0)
            ci = event["card"]
            from_area = event["from"]
            to_area = event["to"]
            self._queue_zone_move_animation_event(ci, from_area, to_area)

    def _player_key(self, player: Player) -> str:
        return "human" if player is self.engine.state.players[0] else "opponent"

    def _queue_phase_event(self, snapshot: dict[str, Any]) -> None:
        phase_by_step = {
            "mana": "mana",
            "main": "main",
        }
        phase = phase_by_step.get(snapshot["step"])
        if phase is None:
            return
        self._queue_animation_event({
            "type": "phase",
            "phase": phase,
            "side": snapshot["activeSide"],
        })

    def _record_visual_changes(self, before: dict[str, Any] | None = None) -> None:
        if before is None:
            before = self._visual_snapshot
        current = self._visual_state_snapshot()
        covered_life_events = self._drain_ordered_engine_visual_events()
        if before is None:
            if covered_life_events is None:
                self._drain_zone_move_events()
                self._drain_effect_events()
                self._drain_destroy_events()
            self._visual_snapshot = current
            return

        if covered_life_events is None:
            covered_life_events = set()
            if (
                current["step"] == "mana"
                and (
                    before["turn"] != current["turn"]
                    or before["activeSide"] != current["activeSide"]
                    or before["step"] != current["step"]
                )
            ):
                self._queue_animation_event({
                    "type": "turn_begin",
                    "side": current["activeSide"],
                    "turn": current["turn"],
                })
                self._queue_phase_event(current)
            elif before["step"] != current["step"]:
                self._queue_phase_event(current)

            self._drain_zone_move_events()
            self._drain_effect_events()
            self._drain_destroy_events()

        for side, life in current["players"].items():
            old_life = before["players"].get(side)
            if old_life is None or old_life == life:
                continue
            if ("player", side, None) in covered_life_events:
                continue
            event_type = "damage" if life < old_life else "heal"
            self._queue_animation_event({
                "type": event_type,
                "targetKind": "player",
                "side": side,
                "amount": abs(life - old_life),
            })

        for key, force in current["forces"].items():
            old_force = before["forces"].get(key)
            if old_force is None or old_force["life"] == force["life"]:
                continue
            if ("force", force["side"], force["forceId"]) in covered_life_events:
                continue
            event_type = "damage" if force["life"] < old_force["life"] else "heal"
            self._queue_animation_event({
                "type": event_type,
                "targetKind": "force",
                "side": force["side"],
                "forceId": force["forceId"],
                "amount": abs(force["life"] - old_force["life"]),
            })

        self._visual_snapshot = current

    def _prompt_mulligan(self, player: Player) -> None:
        self._set_prompt("mulligan", f"{player.name}: Opening hand", [
            ("keep", "Keep", {"choice": "keep", "player": player}),
            ("redraw_selected", "Redraw Selected", {"choice": "selected", "player": player}),
        ])
        self.prompt["playerSide"] = player.side.name

    def state_dto(self, error: dict | None = None) -> dict:
        self._record_visual_changes()
        state = serialize_state(
            self.engine,
            human=self.human,
            asset_index=self.asset_index,
            prompt=self.prompt,
            log=self._log,
            log_events=self._log_events,
            mode=self.mode,
            error=error,
            game_over=self._game_over,
            reveal_all_hands=self.mode == "god" or self.debug_control_both,
            animation_events=self._animation_events,
        )
        state["seed"] = self.seed
        state["opponentAiDifficulty"] = self.opponent_ai_difficulty
        if self.challenge_metadata:
            state["aiChallenge"] = dict(self.challenge_metadata)
        state["debugControlBoth"] = self.debug_control_both
        state["seats"] = {"left": "P1", "right": "P2"}
        state["pendingAttack"] = self._pending_attack_payload()
        state["publicReveals"] = list(self._public_reveals)
        self._public_reveals.clear()
        self._animation_events.clear()
        return state

    def advice(self) -> dict[str, Any]:
        if self.prompt is None:
            return {
                "available": False,
                "code": "no_prompt",
                "message": "当前没有需要建议的操作。",
            }
        player = self._prompt_controller()
        if player is None:
            return {
                "available": False,
                "code": "unsupported_prompt",
                "promptId": self.prompt.get("id"),
                "message": "当前选择暂不支持 AI 建议。",
            }
        if not self._player_has_codeman(player):
            return {
                "available": False,
                "code": "no_codeman",
                "promptId": self.prompt.get("id"),
                "message": "选择 Codeman 后才会提供 AI 建议。",
            }
        if not self._prompt_is_user_controlled():
            return {
                "available": False,
                "code": "not_user_turn",
                "promptId": self.prompt.get("id"),
                "message": "当前不是玩家操作时点。",
            }

        policy = self._advice_policy_for_player(player)
        prompt_kind = str(self.prompt.get("kind") or "")
        scored: list[tuple[float, int, dict[str, Any]]] = []
        for index, option in enumerate(self.prompt.get("options", [])):
            option_id = str(option.get("id") or "")
            if option_id not in self._options:
                continue
            score = self._advice_score_option(policy, player, prompt_kind, option_id, self._options[option_id])
            scored.append((
                score,
                -index,
                {
                    "optionId": option_id,
                    "label": str(option.get("label") or option_id),
                    "score": round(score, 6),
                },
            ))
        if not scored:
            return {
                "available": False,
                "code": "no_options",
                "promptId": self.prompt.get("id"),
                "message": "当前没有可建议的选项。",
            }

        ranked = [item for _, _, item in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)]
        best = ranked[0]
        return {
            "available": True,
            "promptId": self.prompt.get("id"),
            "kind": prompt_kind,
            "playerSide": player.side.name,
            "optionId": best["optionId"],
            "label": best["label"],
            "score": best["score"],
            "message": f"建议：{best['label']}",
            "reason": self._advice_reason(ranked),
            "alternatives": ranked[:3],
        }

    def _player_has_codeman(self, player: Player) -> bool:
        profile = getattr(player, "profile", None)
        return bool(isinstance(profile, dict) and profile.get("codeman"))

    def _advice_policy_for_player(self, player: Player) -> Any:
        codeman_id = self._player_codeman_id(player)
        if codeman_id:
            try:
                player_index = self.engine.state.players.index(player)
            except ValueError:
                player_index = 0
            return resolve_battle_policy(
                "codeman",
                seed=self.seed + 7000 + player_index,
                codeman_id=codeman_id,
                data_root=self.codeman_memory_store.root,
            ).policy
        return _local_game_deep_policy(self.seed + 7100)

    def _advice_score_option(
            self,
            policy: Any,
            player: Player,
            prompt_kind: str,
            option_id: str,
            value: Any,
    ) -> float:
        model = getattr(policy, "model", None)
        extractor = getattr(policy, "extractor", None)
        if model is None or extractor is None:
            return 0.0
        try:
            features = self._advice_features_for_option(extractor, player, prompt_kind, option_id, value)
            return float(model.score(features))
        except Exception:
            return 0.0

    def _advice_features_for_option(
            self,
            extractor: Any,
            player: Player,
            prompt_kind: str,
            option_id: str,
            value: Any,
    ) -> dict[str, float]:
        if prompt_kind in {"main_action", "flash_action"} and isinstance(value, Action):
            return extractor.features_for_action(self.engine, player, value)
        if prompt_kind == "attack_target" and self._attack is not None:
            return extractor.features_for_attack_target(self.engine, player, self._attack.attacker, value)
        if prompt_kind == "blocker":
            if value is None:
                features = extractor.state_features(self.engine, player)
                features["block:none"] = 1.0
                return features
            if self._attack is not None:
                return extractor.features_for_blocker(self.engine, player, self._attack.attacker, value)
        if prompt_kind == "effect_target":
            choice_kind = str(self.prompt.get("choiceKind") or "effect_target")
            return extractor.features_for_generic_target(self.engine, player, choice_kind, value)
        if prompt_kind == "force_base_choice" and isinstance(value, dict):
            return extractor.features_for_generic_target(self.engine, player, "force_base_choice", value.get("card"))

        features = extractor.state_features(self.engine, player)
        features[f"decision:{prompt_kind or 'prompt'}"] = 1.0
        features[f"choice:{option_id}"] = 1.0
        if prompt_kind == "optional_effect" and isinstance(value, dict):
            features["optional_effect:use"] = 1.0 if value.get("useEffect") else 0.0
        if prompt_kind == "mulligan" and isinstance(value, dict):
            features[f"mulligan:{value.get('choice') or option_id}"] = 1.0
        return features

    def _advice_reason(self, ranked: list[dict[str, Any]]) -> str:
        if len(ranked) < 2:
            return "这是 AI 当前评分最高的选择。"
        gap = float(ranked[0]["score"]) - float(ranked[1]["score"])
        if gap >= 0.5:
            return "评分明显领先第二选择。"
        if gap >= 0.1:
            return "评分略高于其他选择。"
        return "几个选择评分接近，优先采用当前最高分。"

    def prompt_controller_side(self) -> str | None:
        player = self._prompt_controller()
        return None if player is None else player.side.name

    def validate_choice(
            self,
            prompt_id: str,
            option_id: str,
            payload: dict | None = None,
    ) -> dict[str, str] | None:
        if self.prompt is None or prompt_id != self.prompt["id"]:
            return {"code": "stale_prompt", "message": "Prompt is no longer active."}
        if option_id not in self._options:
            return {"code": "illegal_choice", "message": f"Unknown option {option_id}."}
        if payload is not None and not isinstance(payload, dict):
            return {"code": "invalid_payload", "message": "Choice payload must be an object."}

        body = dict(payload or {})
        kind = self.prompt["kind"]
        value = self._options[option_id]
        allowed_keys = {"promptId", "optionId"}
        if kind == "mulligan":
            allowed_keys.add("selectedCardIids")
        if kind == "effect_target":
            allowed_keys.add("selectedOptionIds")
        if isinstance(value, Action) and value.kind == "play_card":
            allowed_keys.add("paymentBaseIids")
        unknown_keys = sorted(set(body) - allowed_keys)
        if unknown_keys:
            return {
                "code": "invalid_payload",
                "message": f"Unknown choice payload field {unknown_keys[0]}.",
            }

        try:
            if kind == "mulligan" and "selectedCardIids" in body:
                raw_iids = body["selectedCardIids"]
                if not isinstance(raw_iids, list) or any(
                        isinstance(iid, bool) or not isinstance(iid, int)
                        for iid in raw_iids
                ):
                    raise IllegalActionError("selectedCardIids must be an integer list")
                if len(set(raw_iids)) != len(raw_iids):
                    raise IllegalActionError("selectedCardIids contains duplicates")
                player = value.get("player", self.human)
                hand_iids = {card.iid for card in player.hand}
                if any(iid not in hand_iids for iid in raw_iids):
                    raise IllegalActionError("mulligan card is not in hand")

            if kind == "effect_target":
                raw_ids = body.get("selectedOptionIds", [option_id])
                if not isinstance(raw_ids, list) or any(
                        not isinstance(selected_id, str) for selected_id in raw_ids
                ):
                    raise IllegalActionError("selectedOptionIds must be a string list")
                selected_ids = list(dict.fromkeys(raw_ids))
                if len(selected_ids) != len(raw_ids):
                    raise IllegalActionError("selectedOptionIds contains duplicates")
                if any(selected_id not in self._options for selected_id in selected_ids):
                    raise IllegalActionError("selected target is not legal")
                required_count = int(self.prompt.get("requiredTargetCount", 1))
                minimum_count = int(self.prompt.get("minimumTargetCount", required_count))
                maximum_count = int(self.prompt.get("maximumTargetCount", required_count))
                if self.prompt.get("allowVariableTargetCount"):
                    valid_count = minimum_count <= len(selected_ids) <= maximum_count
                else:
                    valid_count = len(selected_ids) == required_count
                if not valid_count:
                    raise IllegalActionError("selected target count is not legal")

            if "paymentBaseIids" in body:
                raw_iids = body["paymentBaseIids"]
                if not isinstance(raw_iids, list) or any(
                        isinstance(iid, bool) or not isinstance(iid, int)
                        for iid in raw_iids
                ):
                    raise IllegalActionError("paymentBaseIids must be an integer list")
                if len(set(raw_iids)) != len(raw_iids):
                    raise IllegalActionError("paymentBaseIids contains duplicates")
                actor = self._prompt_controller()
                if actor is None or not isinstance(value, Action) or value.kind != "play_card":
                    raise IllegalActionError("payment selection is not valid for this choice")
                card = self.engine._find(actor.hand, int(value.payload["iid"]))
                self.engine._validate_payment_selection(
                    actor,
                    self.engine.effective_cost(actor, card),
                    raw_iids,
                    card,
                )
        except (IllegalActionError, KeyError, TypeError, ValueError) as exc:
            return {"code": "illegal_choice", "message": str(exc)}
        return None

    def surrender(self, player_side: str) -> dict:
        if self._game_over is not None:
            return self.state_dto({"code": "match_finished", "message": "Match already ended."})
        loser = next(
            (player for player in self.engine.state.players if player.side.name == player_side),
            None,
        )
        if loser is None:
            return self.state_dto({"code": "invalid_player", "message": "Unknown player side."})
        winner = next(player for player in self.engine.state.players if player is not loser)
        self._set_game_over(GameOver(winner=winner, reason=f"{loser.name} surrendered"))
        return self.state_dto()

    def choose(self, prompt_id: str, option_id: str, payload: dict | None = None) -> dict:
        validation_error = self.validate_choice(prompt_id, option_id, payload)
        if validation_error is not None:
            return self.state_dto(validation_error)
        kind = self.prompt["kind"]
        value = self._options[option_id]
        selected_effect_targets = None
        if kind == "effect_target" and payload and "selectedOptionIds" in payload:
            selected_ids = list(dict.fromkeys(str(option) for option in payload.get("selectedOptionIds", [])))
            required_count = int(self.prompt.get("requiredTargetCount", 1))
            minimum_count = int(self.prompt.get("minimumTargetCount", required_count))
            maximum_count = int(self.prompt.get("maximumTargetCount", required_count))
            if self.prompt.get("allowVariableTargetCount"):
                valid_count = minimum_count <= len(selected_ids) <= maximum_count
                count_message = (
                    f"Choose {minimum_count}-{maximum_count} targets."
                    if minimum_count != maximum_count
                    else f"Choose {maximum_count} targets."
                )
            else:
                valid_count = len(selected_ids) == required_count
                count_message = f"Choose {required_count} targets."
            if not valid_count:
                return self.state_dto({
                    "code": "illegal_choice",
                    "message": count_message,
                })
            unknown = [selected_id for selected_id in selected_ids if selected_id not in self._options]
            if unknown:
                return self.state_dto({
                    "code": "illegal_choice",
                    "message": f"Unknown option {unknown[0]}.",
                })
            selected_effect_targets = [self._options[selected_id] for selected_id in selected_ids]
        value = self._apply_choice_payload(value, payload)
        self._clear_prompt()
        try:
            if kind == "mulligan":
                player = value.get("player", self.human)
                if value["choice"] == "selected":
                    redraw_iids = (payload or {}).get("selectedCardIids", [])
                else:
                    redraw_iids = []
                selected_mulligan_cards = (
                    list(self.engine._mulligan_selection(player, redraw_iids))
                    if redraw_iids else []
                )
                self.engine.mulligan(player, redraw_iids=redraw_iids)
                if selected_mulligan_cards:
                    for ci in selected_mulligan_cards:
                        self._queue_zone_move_animation_event(ci, AreaType.HAND, AreaType.DECK)
                    self._drain_ordered_engine_visual_events()
                    self._queue_animation_event({
                        "type": "shuffle",
                        "side": player.side.name,
                    })
                if self.mode == "god" and player is self.engine.state.players[0]:
                    self._prompt_mulligan(self.engine.state.players[1])
                    return self.state_dto()
                self._safe_begin_turn()
                self._advance_after_user_choice(limit=200)
            elif kind == "main_action":
                self._perform_action(value, actor=self.engine.state.active)
                self._advance_after_user_choice(limit=200)
            elif kind == "attack_target":
                self._declare_attack(self._attack.attacker, value)
                self._advance_after_user_choice(limit=200)
            elif kind == "flash_action":
                self._apply_flash_choice(self._attack.priority, value)
                self._advance_after_user_choice(limit=200)
            elif kind == "blocker":
                self._resolve_blocker(value)
                self._advance_after_user_choice(limit=200)
            elif kind == "effect_target":
                self._finish_pending_effect(selected_effect_targets if selected_effect_targets is not None else value)
                self._advance_after_user_choice(limit=200)
            elif kind == "optional_effect":
                if isinstance(value, dict) and "tokenCount" in value:
                    self._finish_optional_effect(token_count=value["tokenCount"])
                else:
                    self._finish_optional_effect(bool(value.get("useEffect")))
                self._advance_after_user_choice(limit=200)
            elif kind == "force_base_choice":
                self._finish_force_base_choice(value)
                self._advance_after_user_choice(limit=200)
            elif kind == "blessing_base_replacement":
                self._finish_blessing_base_replacement(value)
                self._advance_after_user_choice(limit=200)
        except GameOver as exc:
            self._set_game_over(exc)
        except IllegalActionError as exc:
            return self.state_dto({"code": "illegal_action", "message": str(exc)})
        return self.state_dto()

    def _apply_choice_payload(self, value: Any, payload: dict | None) -> Any:
        if not isinstance(value, Action) or not payload:
            return value
        if "paymentBaseIids" not in payload:
            return value
        return Action(
            kind=value.kind,
            payload={
                **value.payload,
                "payment_base_iids": [int(iid) for iid in payload["paymentBaseIids"]],
            },
        )

    def auto_step(self, limit: int = 1) -> dict:
        if self.mode in USER_CONTROLLED_MODES and self.prompt is not None:
            return self.state_dto()
        try:
            self._advance_until_prompt(limit=limit, visual_step=True)
        except GameOver as exc:
            self._set_game_over(exc)
        return self.state_dto()

    def _advance_after_user_choice(self, limit: int) -> None:
        if self._should_wait_for_uncontrolled_auto_step():
            return
        self._advance_until_prompt(limit=limit)

    def _should_wait_for_uncontrolled_auto_step(self) -> bool:
        if self.mode != "human-vs-ai" or self._game_over is not None or self.prompt is not None:
            return False
        if self._attack is not None:
            flow = self._attack
            if flow.attacker.area is not AreaType.FIELD:
                return False
            if self._is_user_controlled(flow.attacker.owner):
                return False
            if flow.passes < 2:
                legal = self.engine.legal_flash_actions(flow.priority)
                if self._should_prompt_flash_action(flow.priority, legal):
                    return False
                return not self._is_user_controlled(flow.priority)
            defender = self.engine.state.opponent
            if self._is_user_controlled(defender) and self.engine.legal_blockers(flow.attacker):
                return False
            return not self._is_user_controlled(defender)
        return not self._is_user_controlled(self.engine.state.active)

    def _advance_until_prompt(self, limit: int, *, visual_step: bool = False) -> None:
        steps = 0
        while steps < limit and self._game_over is None and self.prompt is None:
            steps += 1
            if self._drain_or_prompt_blessing_returns():
                return
            if self._drain_or_prompt_force_base_choices():
                return
            if self._attack is not None:
                self._continue_attack_flow(single_step=visual_step)
                continue
            active = self.engine.state.active
            if self._is_user_controlled(active):
                self._prompt_main_action()
                return
            action = self.engine.policy_for(active).choose(self.engine)
            self._perform_action(action, actor=active, continue_uncontrolled_attack=not visual_step)
            if (
                self.prompt is None
                and self._game_over is None
                and self._attack is None
                and self._is_user_controlled(self.engine.state.active)
            ):
                self._prompt_main_action()
                return

    def _prompt_main_action(self) -> None:
        options = []
        for index, action in enumerate(self.engine.legal_actions()):
            options.append((f"a{index}", self._action_label(action), action, self._action_meta(action)))
        self._set_prompt("main_action", f"{self.engine.state.active.name}: choose action", options)

    def _perform_action(self, action: Action, actor: Player, *, continue_uncontrolled_attack: bool = True) -> None:
        if action.kind == "move_card" and self._is_user_controlled(actor):
            direction = action.payload.get("direction")
            if direction == "field_to_base":
                moving = self.engine._find(actor.field, action.payload["iid"])
                replacements_needed = max(
                    0,
                    len(actor.base) + 1 + len(moving.blessings) - BASE_CAP,
                )
                action_replacements = 1 if action.payload.get("replace_base_iid") is not None else 0
                additional_replacements = replacements_needed - action_replacements
                if additional_replacements > 0:
                    excluded = []
                    if action.payload.get("replace_base_iid") is not None:
                        excluded.append(
                            self.engine._find(actor.base, action.payload["replace_base_iid"])
                        )
                    self._pending_effect = {
                        "mode": "main",
                        "stage": "blessing_return_replacement",
                        "action": action,
                        "player": actor,
                    }
                    self._prompt_effect_target(
                        actor,
                        "ally_base",
                        action,
                        additional_replacements,
                        source_ci=moving,
                        excluded_targets=excluded,
                    )
                    return
        if action.kind == "attack":
            attacker = self.engine._find(actor.field, action.payload["attacker_iid"])
            if self._is_user_controlled(actor):
                self._prompt_attack_target(attacker)
            else:
                targets = self.engine.legal_attack_targets(attacker)
                target = self.engine.policy_for(actor).choose_attack_target(self.engine, attacker, targets)
                self._declare_attack(attacker, target)
                if continue_uncontrolled_attack:
                    self._continue_attack_flow()
            return
        if action.kind == "play_card" and self._is_user_controlled(actor):
            post_draw_discard_effect = self._post_draw_discard_effect_for_action(action, actor)
            if post_draw_discard_effect is not None:
                self._begin_post_draw_discard_effect(actor, action, post_draw_discard_effect)
                return
            effect = self._targeted_effect_for_action(action, actor)
            source = self._play_action_card(actor, action)
            if (
                isinstance(effect, EffectSpec)
                and effect.pre_target_fn is not None
                and source.card.type is CardType.MAGIC
                and effect.timing is EffectTiming.ON_CAST_MAGIC
            ):
                self._begin_pre_target_effect(actor, action, effect)
                return
            if effect is not None:
                sequence = self._custom_source_effect_sequence(
                    source,
                    effect,
                    Context(controller=actor, source=source),
                )
                if sequence:
                    if source.card.type is CardType.F_MINION:
                        self._begin_deferred_play_effect(actor, action, "main")
                        return
                    self._pending_effect = {
                        "mode": "main",
                        "stage": "source_sequence",
                        "target_sequence": sequence,
                        "target_sequence_index": 0,
                        "first_targets": [],
                        "action": action,
                        "player": actor,
                        "source": source,
                        "effect": effect,
                    }
                    self._prompt_effect_target(
                        actor,
                        sequence[0],
                        action,
                        1,
                        effect=effect,
                        source_ci=source,
                    )
                    return
        if (action.kind == "play_card"
                and self._is_user_controlled(actor)
                and self._action_needs_effect_target(action, actor)):
            effect = self._targeted_effect_for_action(action, actor)
            if self._play_action_card(actor, action).card.type is CardType.F_MINION:
                self._begin_deferred_play_effect(actor, action, "main")
                return
            target_count = self._target_count_for_action(action, actor)
            self._pending_effect = {"mode": "main", "action": action, "player": actor, "effect": effect}
            self._prompt_effect_target(
                actor,
                self._target_kind_for_action(action, actor),
                action,
                target_count,
                effect=effect,
            )
            return
        if action.kind == "play_card" and self._is_user_controlled(actor):
            effect = self._play_resolution_prompt_effect_for_action(action, actor)
            if effect is not None:
                self._begin_deferred_play_resolution_prompt(actor, action, "main", effect)
                return
        label = self._action_label(action)
        event = self._action_log_event(actor, action, label)
        before = self._visual_state_snapshot()
        self.engine.apply(action)
        self._record_visual_changes(before)
        self._log_event(f"{actor.name}: {label}", event)
        self._log_public_reveals()

    def _prompt_attack_target(self, attacker: CardInstance) -> None:
        self._attack = _AttackFlow(attacker=attacker, target=None, priority=self.engine.state.active)
        options = []
        for index, target in enumerate(self.engine.legal_attack_targets(attacker)):
            options.append((f"t{index}", self._target_label(target), target, self._target_meta(target)))
        self._set_prompt("attack_target", f"Choose target for {attacker.card.name_jp}", options)

    def _declare_attack(self, attacker: CardInstance, target: AttackTarget) -> None:
        before = self._visual_state_snapshot()
        effect = self._targeted_effect_for_card(attacker.card, EffectTiming.ON_ATTACK)
        effect_kind = effect.target_kind if effect is not None else TARGETED_ATTACK_CARD_KINDS.get(attacker.card.id)
        defer_attack_effect = (
            self._is_user_controlled(attacker.owner)
            and effect_kind is not None
            and bool(self._eligible_targets(attacker.owner, effect_kind, None, effect, source_ci=attacker))
        )
        self.engine.declare_attack(attacker, target, resolve_triggers=not defer_attack_effect)
        self._queue_attack_animation_event(attacker, target)
        self._record_visual_changes(before)
        self._attack = _AttackFlow(
            attacker=attacker,
            target=target,
            priority=self.engine.state.opponent,
            passes=0,
        )
        self.engine._flash_ctx = ("attack", attacker, target)
        self._log_event(f"{attacker.owner.name}: attack {self._target_label(target)}", {
            "type": "attack_target",
            "actorName": attacker.owner.name,
            "actorSide": attacker.owner.side.name,
            "attacker": self._card_log_payload(attacker),
            "target": self._target_log_payload(target),
        })
        if defer_attack_effect:
            target_count = self._target_count_for_effect(attacker.owner, effect)
            self._pending_effect = {"mode": "attack_deferred", "player": attacker.owner, "effect": effect, "source": attacker}
            self._prompt_effect_target(
                attacker.owner,
                effect_kind,
                None,
                target_count,
                effect=effect,
                source_ci=attacker,
            )

    def _continue_attack_flow(self, *, single_step: bool = False) -> None:
        while self._attack is not None and self.prompt is None:
            if self._drain_or_prompt_blessing_returns():
                return
            flow = self._attack
            if flow.attacker.area is not AreaType.FIELD:
                self.engine._flash_ctx = None
                self._attack = None
                return
            if flow.passes < 2:
                legal = self.engine.legal_flash_actions(flow.priority)
                if self._should_prompt_flash_action(flow.priority, legal):
                    self._prompt_flash_action(legal)
                    return
                had_flash_priority = hasattr(self.engine, "_current_flash_priority")
                previous_flash_priority = getattr(self.engine, "_current_flash_priority", None)
                self.engine._current_flash_priority = flow.priority
                try:
                    action = self.engine.policy_for(flow.priority).choose_flash(self.engine, legal)
                finally:
                    if had_flash_priority:
                        self.engine._current_flash_priority = previous_flash_priority
                    elif hasattr(self.engine, "_current_flash_priority"):
                        delattr(self.engine, "_current_flash_priority")
                self._apply_flash_choice(flow.priority, action)
                if single_step:
                    return
                continue
            blockers = self.engine.legal_blockers(flow.attacker)
            defender = self.engine.state.opponent
            blocker_choices = self.engine.required_blockers(flow.attacker, blockers) or blockers
            must_block = not self.engine.can_decline_block(flow.attacker, blockers)
            if self._is_user_controlled(defender) and blocker_choices:
                self._prompt_blocker(blocker_choices, must_block=must_block)
                return
            blocker = self.engine.policy_for(defender).choose_blocker(self.engine, flow.attacker, blocker_choices)
            if blocker is None and must_block:
                blocker = self.engine.forced_blocker(flow.attacker, blockers)
            self._resolve_blocker(blocker)

    def _should_prompt_flash_action(self, player: Player, legal: list[Action]) -> bool:
        if not self._is_user_controlled(player):
            return False
        return any(action.kind == "flash_pass" for action in legal)

    def _prompt_flash_action(self, legal: list[Action]) -> None:
        self._queue_animation_event({
            "type": "phase",
            "phase": "flash",
            "side": self._attack.priority.side.name,
        })
        options = []
        for index, action in enumerate(legal):
            options.append((f"f{index}", self._action_label(action), action, self._action_meta(action)))
        self._set_prompt("flash_action", f"{self._attack.priority.name}: Flash timing", options)
        self.prompt["playerSide"] = self._attack.priority.side.name

    def _apply_flash_choice(self, player: Player, action: Action) -> None:
        if (action.kind == "play_card"
                and self._is_user_controlled(player)
                and self._action_needs_effect_target(action, player)):
            effect = self._targeted_effect_for_action(action, player)
            if self._play_action_card(player, action).card.type is CardType.F_MINION:
                self._begin_deferred_play_effect(player, action, "flash")
                return
            target_count = self._target_count_for_action(action, player)
            self._pending_effect = {"mode": "flash", "action": action, "player": player, "effect": effect}
            self._prompt_effect_target(
                player,
                self._target_kind_for_action(action, player),
                action,
                target_count,
                effect=effect,
            )
            return
        if action.kind == "play_card" and self._is_user_controlled(player):
            effect = self._play_resolution_prompt_effect_for_action(action, player)
            if effect is not None:
                self._begin_deferred_play_resolution_prompt(player, action, "flash", effect)
                return
        label = self._action_label(action)
        event = self._action_log_event(player, action, label)
        before = self._visual_state_snapshot()
        result = self.engine.apply_flash_action(player, action)
        self._record_visual_changes(before)
        if result == "pass":
            self._attack.passes += 1
        else:
            self._attack.passes = 0
        self._attack.priority = self._other_player(player)
        self._log_event(f"{player.name}: {label}", event)
        self._log_public_reveals()

    def _prompt_blocker(self, blockers: list[CardInstance], *, must_block: bool = False) -> None:
        self._queue_animation_event({
            "type": "phase",
            "phase": "block",
            "side": self.engine.state.opponent.side.name,
        })
        options = [] if must_block else [("none", "No block", None, {"kind": "no_block"})]
        for index, blocker in enumerate(blockers):
            options.append((
                f"b{index}",
                blocker.card.name_jp,
                blocker,
                {"kind": "blocker", "cardIid": blocker.iid},
            ))
        self._set_prompt("blocker", "Choose blocker", options)
        self.prompt["mustBlock"] = bool(must_block)

    def _resolve_blocker(self, blocker: CardInstance | None) -> None:
        flow = self._attack
        blockers = self.engine.legal_blockers(flow.attacker)
        required_blockers = self.engine.required_blockers(flow.attacker, blockers)
        if blocker is None and required_blockers:
            blocker = required_blockers[0]
        if blocker is not None:
            if blocker not in blockers:
                raise IllegalActionError("illegal blocker")
            if required_blockers and blocker not in required_blockers:
                raise IllegalActionError("illegal blocker")
        before = self._visual_state_snapshot()
        if blocker is not None:
            self._queue_block_animation_event(flow.attacker, blocker)
        self.engine.resolve_attack_after_flash(flow.attacker, flow.target, blocker)
        self._record_visual_changes(before)
        self.engine._flash_ctx = None
        self._attack = None
        label = "no block" if blocker is None else blocker.card.name_jp
        self._log_event(f"Block: {label}", {
            "type": "block",
            "blocker": self._card_log_payload(blocker),
            "blocked": blocker is not None,
        })

    def _drain_or_prompt_force_base_choices(self) -> bool:
        while self.engine.pending_force_base_choices and self.prompt is None:
            fi = self.engine.pending_force_base_choices[0]
            if self._is_user_controlled(fi.owner):
                self._prompt_force_base_choice(fi)
                return True
            chosen = self.engine.resolve_force_base_choice(fi, None)
            label = "no B-Minion" if chosen is None else chosen.card.name_jp
            self._log_event(f"{fi.owner.name}: {fi.force.name_jp} placed {label}", {
                "type": "force_base_choice",
                "actorName": fi.owner.name,
                "actorSide": fi.owner.side.name,
                "force": self._force_log_payload(fi),
                "card": self._card_log_payload(chosen),
            })
        return self.prompt is not None

    def _drain_or_prompt_blessing_returns(self) -> bool:
        while self.engine.pending_blessing_returns and self.prompt is None:
            host, mana = self.engine.pending_blessing_returns[0]
            owner = mana.owner
            if self._is_user_controlled(owner):
                options = [
                    (
                        f"br{index}",
                        card.card.name_jp,
                        card,
                        {
                            "kind": "base_replacement",
                            "iid": mana.iid,
                            "replace_base_iid": card.iid,
                        },
                    )
                    for index, card in enumerate(owner.base)
                ]
                self._set_prompt(
                    "blessing_base_replacement",
                    "Choose base card replaced by returning Bless mana",
                    options,
                )
                self.prompt["playerSide"] = owner.side.name
                self.prompt["card"] = serialize_card(self.engine, mana, self.asset_index)
                return True
            selected = self.engine.policy_for(owner).choose_target(
                self.engine,
                "ally_base",
                1,
                1,
                list(owner.base),
            )
            if not selected:
                raise IllegalActionError(
                    "Bless mana returning to a full base requires a replacement"
                )
            self.engine.resolve_blessing_base_choice(host, mana, selected[0])
        return self.prompt is not None

    def _finish_blessing_base_replacement(self, replacement: CardInstance) -> None:
        if not isinstance(replacement, CardInstance):
            raise IllegalActionError("choose a base card to replace")
        host, mana = self.engine.pending_blessing_returns[0]
        before = self._visual_state_snapshot()
        self.engine.resolve_blessing_base_choice(host, mana, replacement)
        self._record_visual_changes(before)
        self._log_event(
            f"{mana.owner.name}: replaced {replacement.card.name_jp} for returning Bless mana",
            {
                "type": "base_replacement",
                "actorName": mana.owner.name,
                "actorSide": mana.owner.side.name,
                "card": self._card_log_payload(mana),
                "replaced": self._card_log_payload(replacement),
            },
        )

    def _prompt_force_base_choice(self, fi: ForceInstance) -> None:
        options = []
        choices = self.engine.eligible_force_base_choices(fi.owner)
        replacements = list(fi.owner.base) if len(fi.owner.base) >= BASE_CAP else [None]
        option_index = 0
        for card in choices:
            for replacement in replacements:
                meta = {
                    "kind": "force_base_choice",
                    "cardIid": card.iid,
                    "cardId": card.card.id,
                    "nameJp": card.card.name_jp,
                    "type": card.card.type.value,
                    "bp": card.card.bp,
                    "dp": card.card.dp,
                    "assetUrl": self.asset_index.asset_url(card.card.id),
                    "ownerSide": fi.owner.side.name,
                }
                label = card.card.name_jp
                value = {"force": fi, "card": card}
                if replacement is not None:
                    label = f"{card.card.name_jp} / replace {replacement.card.name_jp}"
                    value["replaceBaseIid"] = replacement.iid
                    meta["replaceBaseIid"] = replacement.iid
                    meta["replaceBaseCard"] = self._effect_target_meta(replacement)
                options.append((f"fb{option_index}", label, value, meta))
                option_index += 1
        self._set_prompt(
            "force_base_choice",
            f"{fi.owner.name}: choose a Base Minion for {fi.force.name_jp}",
            options,
        )
        self.prompt["playerSide"] = fi.owner.side.name

    def _finish_force_base_choice(self, value: dict[str, Any]) -> None:
        fi = value["force"]
        card = value["card"]
        before = self._visual_state_snapshot()
        chosen = self.engine.resolve_force_base_choice(fi, card.iid, value.get("replaceBaseIid"))
        self._record_visual_changes(before)
        self._log_event(f"{fi.owner.name}: {fi.force.name_jp} placed {chosen.card.name_jp}", {
            "type": "force_base_choice",
            "actorName": fi.owner.name,
            "actorSide": fi.owner.side.name,
            "force": self._force_log_payload(fi),
            "card": self._card_log_payload(chosen),
        })

    def _pending_effect_source(self, pending: dict[str, Any]) -> CardInstance | None:
        source = pending.get("source")
        if isinstance(source, CardInstance):
            return source
        action = pending.get("action")
        player = pending.get("player")
        if isinstance(action, Action) and isinstance(player, Player):
            try:
                return self._play_action_card(player, action)
            except IllegalActionError:
                return None
        return None

    def _optional_followup_target_kind(self, pending: dict[str, Any]) -> str | None:
        effect = pending.get("effect")
        if not isinstance(effect, EffectSpec):
            return None
        kind = effect.params.get("optional_followup_target_kind")
        return str(kind) if kind else None

    def _optional_followup_excluded_targets(self, pending: dict[str, Any]) -> list[Any]:
        effect = pending.get("effect")
        if not isinstance(effect, EffectSpec):
            return []
        if not effect.params.get("optional_followup_exclude_first_targets"):
            return []
        return list(pending.get("first_targets") or [])

    def _effect_needs_mana_color_choice(self, pending: dict[str, Any]) -> bool:
        effect = pending.get("effect")
        return isinstance(effect, EffectSpec) and bool(effect.params.get("choose_mana_color"))

    def _prompt_mana_color_choice(self, player: Player, source: CardInstance | None, effect: EffectSpec | None) -> None:
        options = [
            (
                f"color_{color.name.lower()}",
                color.name.title(),
                color,
                {
                    "kind": "effect_target",
                    "targetKind": "mana_color",
                    "nameJp": color.name.title(),
                    "type": "mana_color",
                    "manaColor": color.name,
                    "ownerSide": player.side.name,
                },
            )
            for color in MANA_COLOR_CHOICES
        ]
        self._set_prompt("effect_target", "Choose mana color", options)
        self.prompt["choiceKind"] = "mana_color"
        self.prompt["playerSide"] = player.side.name
        self.prompt["requiredTargetCount"] = 1
        self.prompt["minimumTargetCount"] = 1
        self.prompt["maximumTargetCount"] = 1
        self.prompt["allowVariableTargetCount"] = False
        if source is not None:
            self.prompt["card"] = serialize_card(self.engine, source, self.asset_index)
            if effect is not None:
                text = self._effect_event_text(source, effect, Context(controller=player, source=source))
                if text:
                    self.prompt["effectText"] = text

    def _defer_trigger_choice(self, pending: Any) -> bool:
        if self.prompt is not None:
            return False
        effect = getattr(pending, "trigger", None)
        source = getattr(pending, "instance", None)
        if not isinstance(effect, EffectSpec) or not isinstance(source, CardInstance):
            return False
        prompted = self._prompted_trigger_resolution
        if prompted is not None and prompted[0] is source and prompted[1] is effect:
            self._prompted_trigger_resolution = None
            return False
        player = source.owner
        if not self._is_user_controlled(player):
            return False
        custom_kind = self._custom_trigger_choice_kind(source, effect, pending.context)
        if custom_kind is not None:
            eligible = self._eligible_targets(player, custom_kind, None, effect, source_ci=source)
            if not eligible:
                return False
            self._pending_effect = {
                "mode": "trigger_deferred",
                "player": player,
                "source": source,
                "effect": effect,
                "context": pending.context,
            }
            self._prompt_effect_target(player, custom_kind, None, 1, effect=effect, source_ci=source)
            return True
        if effect.optional and not self._effect_needs_target_choice(effect):
            self._pending_effect = {
                "mode": "trigger_deferred",
                "player": player,
                "source": source,
                "effect": effect,
                "context": pending.context,
            }
            self._prompt_optional_effect(player, source, effect)
            return True
        if not self._effect_needs_target_choice(effect):
            replacement_count = self._field_replacements_needed_for_effect(player, {"effect": effect}, [])
            replacement_kind = "ally_minion"
            replacement_stage = "field_replacement"
            if replacement_count <= 0 and effect.template_id == "place_colorless_mana" and len(player.base) >= BASE_CAP:
                replacement_count = 1
                replacement_kind = "ally_base"
                replacement_stage = "base_replacement"
            if replacement_count <= 0:
                return False
            self._pending_effect = {
                "mode": "trigger_deferred",
                "stage": replacement_stage,
                "player": player,
                "source": source,
                "effect": effect,
                "context": pending.context,
                "first_targets": [],
                "field_replacement_targets": [],
                "base_replacement_targets": [],
            }
            self._prompt_effect_target(player, replacement_kind, None, replacement_count, effect=effect, source_ci=source)
            return True
        kind = effect.target_kind
        eligible = self._eligible_targets(player, kind, None, effect, source_ci=source)
        if not eligible:
            return False
        target_count = min(self._target_count_for_effect(player, effect), len(eligible))
        self._pending_effect = {
            "mode": "trigger_deferred",
            "player": player,
            "source": source,
            "effect": effect,
            "context": pending.context,
        }
        self._prompt_effect_target(player, kind, None, target_count, effect=effect, source_ci=source)
        return True

    def _custom_trigger_choice_kind(self, source: CardInstance, effect: EffectSpec, ctx: Context) -> str | None:
        if (
            self._catherine_reward_will_resolve(source, effect, ctx)
            and effect.timing is EffectTiming.ON_DAMAGE_FORCE
            and len(source.owner.base) >= BASE_CAP
        ):
            return "ally_base"
        return None

    def _catherine_reward_will_resolve(self, source: CardInstance, effect: EffectSpec, ctx: Context) -> bool:
        damage_source = ctx.source
        target = ctx.target
        return (
            source.card.id == "purple_03_02_01_01"
            and not getattr(ctx, "_catherine_rewarded", False)
            and source.area is AreaType.FIELD
            and source.owner is self.engine.state.active
            and isinstance(damage_source, CardInstance)
            and damage_source is not source
            and damage_source.owner is source.owner
            and damage_source.area is AreaType.FIELD
            and damage_source.card.type in (CardType.F_MINION, CardType.B_MINION)
            and self._card_is_color(damage_source.card, Color.PURPLE)
            and isinstance(target, ForceInstance)
            and target.destroyed
            and getattr(ctx, "damage_kind", None) == "minion_dp"
        )

    def _card_is_color(self, card: Any, color: Color) -> bool:
        if getattr(card, "mana_color", None) is color:
            return True
        return color in getattr(card, "cost", {})

    def _custom_source_effect_sequence(self, source: CardInstance, effect: EffectSpec, ctx: Context) -> list[str]:
        if source.card.id == "purple_07_02_01_00" and effect.timing is EffectTiming.ON_DESTROY:
            return [
                kind for kind in ("enemy_minion", "enemy_force")
                if self._eligible_targets(source.owner, kind, None, effect, source_ci=source)
            ]
        if source.card.id == "red_06_02_02_01" and effect.timing is EffectTiming.ON_SUMMON:
            if not self._eligible_targets(
                source.owner,
                "ally_colorless_mana_token",
                None,
                effect,
                source_ci=source,
            ):
                return []
            sequence = ["ally_colorless_mana_token"]
            if self._eligible_targets(source.owner, "enemy_minion", None, effect, source_ci=source):
                sequence.append("enemy_minion")
            return sequence
        if source.card.id == "red_08_03_02_00" and effect.timing is EffectTiming.ON_CAST_MAGIC:
            if not self._eligible_targets(
                source.owner,
                "ally_colorless_mana_token",
                None,
                effect,
                source_ci=source,
            ):
                return []
            sequence = ["ally_colorless_mana_token"]
            if self._eligible_targets(
                source.owner,
                "pc02_fossil_dragon",
                None,
                effect,
                source_ci=source,
            ):
                sequence.append("pc02_fossil_dragon")
            return sequence
        return []

    def _defer_source_effect_choice(self, source: CardInstance, effect: Any, ctx: Context) -> bool:
        if self.prompt is not None:
            return False
        if not isinstance(effect, EffectSpec):
            return False
        prompted = self._prompted_source_effect_resolution
        if prompted is not None and prompted[0] is source and prompted[1] is effect:
            self._prompted_source_effect_resolution = None
            return False
        player = source.owner
        if not self._is_user_controlled(player):
            return False
        sequence = self._custom_source_effect_sequence(source, effect, ctx)
        if sequence:
            self._pending_effect = {
                "mode": "source_deferred",
                "stage": "source_sequence",
                "target_sequence": sequence,
                "target_sequence_index": 0,
                "first_targets": [],
                "player": player,
                "source": source,
                "effect": effect,
                "context": ctx,
            }
            self._prompt_effect_target(player, sequence[0], None, 1, effect=effect, source_ci=source)
            return True
        if effect.optional and not self._effect_needs_target_choice(effect):
            self._pending_effect = {
                "mode": "source_deferred",
                "player": player,
                "source": source,
                "effect": effect,
                "context": ctx,
            }
            self._prompt_optional_effect(player, source, effect)
            return True
        if not self._effect_needs_target_choice(effect):
            replacement_count = self._field_replacements_needed_for_effect(player, {"effect": effect}, [])
            if replacement_count:
                self._pending_effect = {
                    "mode": "source_deferred",
                    "stage": "field_replacement",
                    "player": player,
                    "source": source,
                    "effect": effect,
                    "context": ctx,
                    "first_targets": [],
                    "field_replacement_targets": [],
                }
                self._prompt_effect_target(
                    player,
                    "ally_minion",
                    None,
                    replacement_count,
                    effect=effect,
                    source_ci=source,
                )
                return True
            if effect.template_id == "place_colorless_mana" and len(player.base) >= BASE_CAP:
                self._pending_effect = {
                    "mode": "source_deferred",
                    "stage": "base_replacement",
                    "player": player,
                    "source": source,
                    "effect": effect,
                    "context": ctx,
                    "first_targets": [],
                    "base_replacement_targets": [],
                }
                self._prompt_effect_target(player, "ally_base", None, 1, effect=effect, source_ci=source)
                return True
            return False
        kind = effect.target_kind
        eligible = self._eligible_targets(player, kind, None, effect, source_ci=source)
        if not eligible:
            return False
        target_count = min(self._target_count_for_effect(player, effect), len(eligible))
        self._pending_effect = {
            "mode": "source_deferred",
            "player": player,
            "source": source,
            "effect": effect,
            "context": ctx,
        }
        self._prompt_effect_target(player, kind, None, target_count, effect=effect, source_ci=source)
        return True

    def _resolve_pre_prompted_trigger(self, pending: dict[str, Any]) -> None:
        source = self._pending_effect_source(pending)
        effect = pending.get("effect")
        if not isinstance(source, CardInstance) or not isinstance(effect, EffectSpec):
            self.engine.triggers.resolve_all()
            return
        marker = (source, effect)
        self._prompted_trigger_resolution = marker
        try:
            self.engine.triggers.resolve_all()
        finally:
            if self._prompted_trigger_resolution is marker:
                self._prompted_trigger_resolution = None

    def _finish_pending_effect(self, target: Any) -> None:
        pending = self._pending_effect
        self._pending_effect = None
        player = pending["player"]
        if isinstance(target, list):
            queued_targets = [item for item in target if item is not None]
        else:
            queued_targets = [] if target is None else [target]
        if pending.get("stage") == "mana_color_choice":
            color_target = queued_targets[0] if queued_targets else None
            if not isinstance(color_target, Color):
                raise IllegalActionError("choose a mana color")
            source = self._pending_effect_source(pending)
            if source is None:
                raise IllegalActionError("effect source missing")
            source.flags = {
                flag for flag in source.flags
                if not flag.startswith("pending_mana_color:")
            }
            source.flags.add(f"pending_mana_color:{color_target.name}")
            queued_targets = list(pending.get("first_targets") or [])
            pending = {
                **pending,
                "stage": "mana_color_choice_done",
            }
        if pending.get("stage") == "source_sequence":
            sequence_targets = list(pending.get("first_targets") or []) + queued_targets
            sequence = list(pending.get("target_sequence") or [])
            next_index = int(pending.get("target_sequence_index", 0)) + 1
            source = self._pending_effect_source(pending)
            while next_index < len(sequence):
                kind = sequence[next_index]
                if source is not None and self._eligible_targets(player, kind, None, pending.get("effect"), source_ci=source):
                    self._pending_effect = {
                        **pending,
                        "target_sequence_index": next_index,
                        "first_targets": sequence_targets,
                    }
                    self._prompt_effect_target(player, kind, None, 1, effect=pending.get("effect"), source_ci=source)
                    return
                next_index += 1
            pending = {
                **pending,
                "stage": "source_sequence_done",
                "first_targets": sequence_targets,
            }
            queued_targets = sequence_targets
        if pending.get("stage") == "base_replacement":
            replacement_targets = list(pending.get("base_replacement_targets") or []) + queued_targets
            groups = list(pending.get("base_replacement_groups") or [])
            next_index = int(pending.get("base_replacement_index", 0)) + 1
            source = self._pending_effect_source(pending)
            while next_index < len(groups):
                owner, count = groups[next_index]
                if self._is_user_controlled(owner):
                    break
                replacement_targets.extend(
                    self._auto_effect_targets(
                        owner,
                        "ally_base",
                        count,
                        count,
                        effect=pending.get("effect"),
                        source_ci=source,
                    )
                )
                next_index += 1
            if next_index < len(groups):
                owner, count = groups[next_index]
                self._pending_effect = {
                    **pending,
                    "base_replacement_index": next_index,
                    "base_replacement_targets": replacement_targets,
                }
                self._prompt_effect_target(owner, "ally_base", None, count, source_ci=source)
                return
            pending = {
                **pending,
                "base_replacement_targets": replacement_targets,
            }
            queued_targets = list(pending.get("first_targets") or [])
        elif pending.get("stage") == "field_replacement":
            pending = {
                **pending,
                "field_replacement_targets": list(pending.get("field_replacement_targets") or []) + queued_targets,
            }
            queued_targets = list(pending.get("first_targets") or [])
        elif self._optional_followup_target_kind(pending) and pending.get("stage") != "followup_target":
            source = self._pending_effect_source(pending)
            if source is not None:
                self._pending_effect = {
                    **pending,
                    "stage": "followup_optional",
                    "first_targets": queued_targets,
                }
                self._prompt_optional_effect(player, source, pending["effect"])
                return
        if pending.get("stage") == "followup_target":
            queued_targets = list(pending.get("first_targets") or []) + queued_targets
        if self._effect_needs_mana_color_choice(pending) and pending.get("stage") != "mana_color_choice_done":
            source = self._pending_effect_source(pending)
            self._pending_effect = {
                **pending,
                "stage": "mana_color_choice",
                "first_targets": queued_targets,
            }
            self._prompt_mana_color_choice(player, source, pending.get("effect"))
            return
        if pending.get("stage") not in {"base_replacement", "field_replacement"}:
            field_replacements_needed = self._field_replacements_needed_for_effect(player, pending, queued_targets)
            if field_replacements_needed:
                source = self._pending_effect_source(pending)
                self._pending_effect = {
                    **pending,
                    "stage": "field_replacement",
                    "first_targets": queued_targets,
                    "field_replacement_targets": [],
                }
                self._prompt_effect_target(
                    player,
                    "ally_minion",
                    None,
                    field_replacements_needed,
                    source_ci=source,
                )
                return
            replacement_groups = self._base_replacement_groups_for_effect(player, pending, queued_targets)
            if replacement_groups:
                source = self._pending_effect_source(pending)
                replacement_targets: list[Any] = []
                replacement_index = 0
                while replacement_index < len(replacement_groups):
                    owner, count = replacement_groups[replacement_index]
                    if self._is_user_controlled(owner):
                        break
                    replacement_targets.extend(
                        self._auto_effect_targets(
                            owner,
                            "ally_base",
                            count,
                            count,
                            effect=pending.get("effect"),
                            source_ci=source,
                        )
                    )
                    replacement_index += 1
                if replacement_index >= len(replacement_groups):
                    pending = {
                        **pending,
                        "stage": "base_replacement",
                        "first_targets": queued_targets,
                        "base_replacement_groups": replacement_groups,
                        "base_replacement_index": replacement_index,
                        "base_replacement_targets": replacement_targets,
                    }
                    queued_targets = list(pending.get("first_targets") or [])
                else:
                    owner, count = replacement_groups[replacement_index]
                    self._pending_effect = {
                        **pending,
                        "stage": "base_replacement",
                        "first_targets": queued_targets,
                        "base_replacement_groups": replacement_groups,
                        "base_replacement_index": replacement_index,
                        "base_replacement_targets": replacement_targets,
                    }
                    self._prompt_effect_target(owner, "ally_base", None, count, source_ci=source)
                    return
        self._resolve_pending_effect_with_targets(pending, queued_targets)

    def _field_replacements_needed_for_effect(
            self,
            player: Player,
            pending: dict[str, Any],
            targets_to_field: list[Any],
    ) -> int:
        effect = pending.get("effect")
        if not isinstance(effect, EffectSpec):
            return 0
        amount = 0
        if effect.template_id == "create_tokens":
            selected_amount = pending.get("token_count")
            amount = int(
                effect.params.get("amount") or 0
                if selected_amount is None
                else selected_amount
            )
        elif effect.template_id == "summon_from_trash" or effect.target_kind == "ally_minion_base":
            amount = sum(1 for target in targets_to_field if isinstance(target, CardInstance))
        elif effect.params.get("puts_targets_on_field"):
            amount = sum(1 for target in targets_to_field if isinstance(target, CardInstance))
        amount += sum(
            1 for target in targets_to_field
            if isinstance(target, CardInstance) and target.card.id == "purple_04_02_01_00"
        )
        if amount <= 0:
            return 0
        return max(0, len(player.field) + amount - FIELD_CAP)

    def _base_replacement_groups_for_effect(
            self,
            player: Player,
            pending: dict[str, Any],
            targets_to_base: list[Any],
    ) -> list[tuple[Player, int]]:
        effect = pending.get("effect")
        if not isinstance(effect, EffectSpec) or not targets_to_base:
            return []
        target_counts: list[tuple[Player, int]] = []
        if (
            effect.template_id in {"place_base_from_hand", "place_base_from_deck"}
            or effect.params.get("puts_targets_on_base")
        ):
            target_counts.append((player, len(targets_to_base)))
        elif effect.template_id == "move_to_base_targets" or effect.params.get("moves_targets_to_base"):
            for target in targets_to_base:
                if not isinstance(target, CardInstance) or target.card.is_token:
                    continue
                owner = target.owner
                entering_count = 1 + len(target.blessings)
                for index, (existing_owner, count) in enumerate(target_counts):
                    if existing_owner is owner:
                        target_counts[index] = (existing_owner, count + entering_count)
                        break
                else:
                    target_counts.append((owner, entering_count))
        groups: list[tuple[Player, int]] = []
        for owner, count in target_counts:
            overflow = max(0, len(owner.base) + count - BASE_CAP)
            replacements_needed = min(count, overflow)
            if replacements_needed:
                groups.append((owner, replacements_needed))
        return groups

    def _queue_policy_targets(self, player: Player, targets: list[Any]) -> None:
        if not targets:
            return
        policy = self.engine.policy_for(player)
        if hasattr(policy, "queue_targets"):
            policy.queue_targets(targets)
        else:
            self.human_policy.queue_targets(targets)

    def _auto_effect_targets(
            self,
            player: Player,
            kind: str,
            min_n: int,
            max_n: int,
            *,
            effect: EffectSpec | None = None,
            source_ci: CardInstance | None = None,
            excluded_targets: list[Any] | None = None,
    ) -> list[Any]:
        eligible = self._eligible_targets(player, kind, None, effect, source_ci=source_ci)
        if excluded_targets:
            eligible = [target for target in eligible if target not in excluded_targets]
        if not eligible or max_n <= 0:
            return []
        policy = self.engine.policy_for(player)
        previous_context = getattr(self.engine, "_target_selection_context", None)
        self.engine._target_selection_context = {"source": source_ci, "effect": effect}
        try:
            selected = list(policy.choose_target(self.engine, kind, min_n, max_n, eligible))[:max_n]
            if len(selected) < min_n:
                for target in eligible:
                    if target in selected:
                        continue
                    selected.append(target)
                    if len(selected) >= min_n:
                        break
            return selected[:max_n]
        finally:
            if previous_context is None:
                try:
                    delattr(self.engine, "_target_selection_context")
                except AttributeError:
                    pass
            else:
                self.engine._target_selection_context = previous_context

    def _run_pending_effect_callback(self, pending: dict[str, Any]) -> None:
        source = pending["source"]
        effect = pending["effect"]
        ctx = pending["context"]
        marker = object()
        previous_count = getattr(ctx, "_create_tokens_count", marker)
        if "token_count" in pending:
            setattr(ctx, "_create_tokens_count", pending["token_count"])
        try:
            self.engine._record_effect_event(source, effect, ctx)
            self.engine._run_effect_callback(effect.fn, source, self.engine.state, ctx)
        finally:
            if previous_count is marker:
                try:
                    delattr(ctx, "_create_tokens_count")
                except AttributeError:
                    pass
            else:
                setattr(ctx, "_create_tokens_count", previous_count)

    def _resolve_pending_effect_with_targets(self, pending: dict[str, Any], queued_targets: list[Any]) -> None:
        player = pending["player"]
        base_replacement_targets = list(pending.get("base_replacement_targets") or [])
        field_replacement_targets = list(pending.get("field_replacement_targets") or [])
        if pending.get("skip_discards_effect") and not queued_targets and not base_replacement_targets and not field_replacement_targets:
            self.engine.triggers.discard_pending(
                instance=pending.get("source"),
                trigger=pending.get("effect"),
            )
        own_replacements = [
            target for target in base_replacement_targets
            if isinstance(target, CardInstance) and target.owner is player
        ]
        policy_batches: list[tuple[Any, list[Any]]] = []

        def add_policy_targets(owner: Player, targets: list[Any]) -> None:
            if not targets:
                return
            policy = self.engine.policy_for(owner)
            if not hasattr(policy, "queue_targets"):
                policy = self.human_policy
            for existing_policy, existing_targets in policy_batches:
                if existing_policy is policy:
                    existing_targets.extend(targets)
                    return
            policy_batches.append((policy, list(targets)))

        add_policy_targets(player, queued_targets + own_replacements + field_replacement_targets)
        for owner in self.engine.state.players:
            if owner is player:
                continue
            owner_replacements = [
                target for target in base_replacement_targets
                if isinstance(target, CardInstance) and target.owner is owner
            ]
            add_policy_targets(owner, owner_replacements)
        for policy, targets in policy_batches:
            policy.queue_targets(targets)
        self._queue_magic_effect_target_animation(pending, queued_targets)
        before = self._visual_state_snapshot()
        if pending["mode"] == "main":
            source = self._pending_effect_source(pending)
            effect = pending.get("effect")
            marker = (source, effect) if isinstance(source, CardInstance) and isinstance(effect, EffectSpec) else None
            if marker is not None:
                self._prompted_source_effect_resolution = marker
            try:
                self.engine.apply(pending["action"])
            finally:
                if marker is not None and self._prompted_source_effect_resolution is marker:
                    self._prompted_source_effect_resolution = None
            self._record_visual_changes(before)
        elif pending["mode"] == "main_deferred":
            self._resolve_pre_prompted_trigger(pending)
            self._record_visual_changes(before)
        elif pending["mode"] == "trigger_deferred":
            self._run_pending_effect_callback(pending)
            self.engine.triggers.resolve_all()
            self._record_visual_changes(before)
        elif pending["mode"] == "source_deferred":
            self._run_pending_effect_callback(pending)
            self.engine.triggers.resolve_all()
            self._record_visual_changes(before)
        elif pending["mode"] == "attack_deferred":
            self._resolve_pre_prompted_trigger(pending)
            self._record_visual_changes(before)
            self._attack.priority = self._other_player(player)
            self._continue_attack_flow()
        elif pending["mode"] == "post_draw_discard":
            if queued_targets:
                target = queued_targets[0]
                if isinstance(target, CardInstance):
                    self.engine.discard_from_hand(player, target)
            self.engine.triggers.resolve_all()
            self._record_visual_changes(before)
        else:
            if pending["mode"] == "flash_deferred":
                self._resolve_pre_prompted_trigger(pending)
                self._record_visual_changes(before)
                if self._attack is not None:
                    self._attack.passes = 0
            else:
                source = self._pending_effect_source(pending)
                effect = pending.get("effect")
                marker = (source, effect) if isinstance(source, CardInstance) and isinstance(effect, EffectSpec) else None
                if marker is not None:
                    self._prompted_source_effect_resolution = marker
                try:
                    result = self.engine.apply_flash_action(player, pending["action"])
                finally:
                    if marker is not None and self._prompted_source_effect_resolution is marker:
                        self._prompted_source_effect_resolution = None
                self._record_visual_changes(before)
                if self._attack is not None:
                    if result == "pass":
                        self._attack.passes += 1
                    else:
                        self._attack.passes = 0
            if self._attack is not None:
                self._attack.priority = self._other_player(player)
                self._continue_attack_flow()
        log_targets = [
            self._effect_target_log_payload(target)
            for target in queued_targets
            if target is not None
        ]
        event_payload = {
            "type": "effect_target",
            "actorName": player.name,
            "actorSide": player.side.name,
        }
        if log_targets:
            event_payload["targets"] = log_targets
        self._log_event(f"{player.name}: target selected", event_payload)
        self._log_public_reveals()

    def _queue_magic_effect_target_animation(self, pending: dict[str, Any], targets: list[Any]) -> None:
        source = self._pending_effect_source(pending)
        if not isinstance(source, CardInstance) or source.card.type is not CardType.MAGIC:
            return
        source_card = serialize_card(self.engine, source, self.asset_index)
        for target in targets:
            if target is None:
                continue
            meta = self._effect_target_log_payload(target)
            target_kind = meta.get("targetKind")
            if target_kind not in {"card", "force", "player"}:
                continue
            if target_kind == "card" and meta.get("area") not in {"field", "base"}:
                continue
            event = {
                "type": "effect_target",
                "side": source.owner.side.name,
                "sourceCard": source_card,
                "target": meta,
                "targetKind": target_kind,
                "targetSide": meta.get("ownerSide"),
                "targetLabel": meta.get("targetLabel") or meta.get("nameJp"),
            }
            if target_kind == "card":
                event["targetCardIid"] = meta.get("cardIid")
                event["targetArea"] = meta.get("area")
            elif target_kind == "force":
                event["targetForceId"] = meta.get("forceId")
            self._queue_animation_event(event)

    def _finish_optional_effect(self, use_effect: bool = False, *, token_count: int | None = None) -> None:
        pending = self._pending_effect
        self._pending_effect = None
        player = pending["player"]
        if token_count is not None:
            effect = pending.get("effect")
            if not isinstance(effect, EffectSpec) or effect.template_id != "create_tokens":
                raise IllegalActionError("token count is only valid for token creation effects")
            amount = int(effect.params.get("amount") or 0)
            if isinstance(token_count, bool) or not isinstance(token_count, int) or not 0 <= token_count <= amount:
                raise IllegalActionError("token count is outside the effect range")
            pending = {
                **pending,
                "token_count": token_count,
            }
            use_effect = token_count > 0
        if pending["mode"] in {"trigger_deferred", "source_deferred"}:
            before = self._visual_state_snapshot()
            if use_effect:
                replacements_needed = self._field_replacements_needed_for_effect(player, pending, [])
                if replacements_needed:
                    source = self._pending_effect_source(pending)
                    self._pending_effect = {
                        **pending,
                        "stage": "field_replacement",
                        "first_targets": [],
                        "field_replacement_targets": [],
                    }
                    self._prompt_effect_target(
                        player,
                        "ally_minion",
                        None,
                        replacements_needed,
                        effect=None,
                        source_ci=source,
                    )
                    self._log_event(f"{player.name}: used optional effect", {
                        "type": "optional_effect",
                        "actorName": player.name,
                        "actorSide": player.side.name,
                        "used": True,
                    })
                    self._log_public_reveals()
                    return
                self._resolve_pending_effect_with_targets(pending, [])
            else:
                self.engine.triggers.resolve_all()
                self._record_visual_changes(before)
            self._log_event(f"{player.name}: {'used' if use_effect else 'skipped'} optional effect", {
                "type": "optional_effect",
                "actorName": player.name,
                "actorSide": player.side.name,
                "used": use_effect,
            })
            self._log_public_reveals()
            return
        if pending.get("stage") == "followup_optional":
            first_targets = list(pending.get("first_targets") or [])
            kind = self._optional_followup_target_kind(pending)
            if use_effect and kind:
                effect = pending["effect"]
                max_targets = int(effect.params.get("optional_followup_max_targets", 1))
                excluded = self._optional_followup_excluded_targets(pending)
                source = self._pending_effect_source(pending)
                eligible = [
                    target
                    for target in self._eligible_targets(player, kind, pending.get("action"), None, source_ci=source)
                    if target not in excluded
                ]
                if eligible:
                    self._pending_effect = {
                        **pending,
                        "stage": "followup_target",
                        "first_targets": first_targets,
                    }
                    self._prompt_effect_target(
                        player,
                        kind,
                        pending.get("action"),
                        max_targets,
                        excluded_targets=excluded,
                        source_ci=source,
                    )
                    return
            self._resolve_pending_effect_with_targets(pending, first_targets)
            return
        if not use_effect:
            self.engine.triggers.discard_pending(
                instance=pending.get("source"),
                trigger=pending.get("effect"),
            )
        else:
            pending = {
                **pending,
                "skip_discards_effect": False,
            }
            if pending["mode"] in {"main_deferred", "flash_deferred"}:
                replacements_needed = self._field_replacements_needed_for_effect(player, pending, [])
                if replacements_needed:
                    source = self._pending_effect_source(pending)
                    self._pending_effect = {
                        **pending,
                        "stage": "field_replacement",
                        "first_targets": [],
                        "field_replacement_targets": [],
                    }
                    self._prompt_effect_target(
                        player,
                        "ally_minion",
                        None,
                        replacements_needed,
                        effect=None,
                        source_ci=source,
                    )
                    self._log_event(f"{player.name}: used optional effect", {
                        "type": "optional_effect",
                        "actorName": player.name,
                        "actorSide": player.side.name,
                        "used": True,
                    })
                    self._log_public_reveals()
                    return
        before = self._visual_state_snapshot()
        if pending["mode"] == "main_deferred":
            self._resolve_pre_prompted_trigger(pending)
            self._record_visual_changes(before)
        elif pending["mode"] == "flash_deferred":
            self._resolve_pre_prompted_trigger(pending)
            self._record_visual_changes(before)
            if self._attack is not None:
                self._attack.passes = 0
                self._attack.priority = self._other_player(player)
                self._continue_attack_flow()
        self._log_event(f"{player.name}: {'used' if use_effect else 'skipped'} optional effect", {
            "type": "optional_effect",
            "actorName": player.name,
            "actorSide": player.side.name,
            "used": use_effect,
        })
        self._log_public_reveals()

    def _begin_deferred_play_resolution_prompt(
            self,
            player: Player,
            action: Action,
            mode: str,
            effect: EffectSpec,
    ) -> None:
        label = self._action_label(action)
        event = self._action_log_event(player, action, label)
        if mode == "main":
            ci = self._play_action_card(player, action)
            replacements_needed = self._token_replacements_needed_before_play(player, ci.card, effect, action)
            if effect.template_id == "create_tokens" and replacements_needed:
                self._log_event(f"{player.name}: {label}", event)
                self._pending_effect = {
                    "mode": "main",
                    "stage": "field_replacement",
                    "action": action,
                    "player": player,
                    "source": ci,
                    "effect": effect,
                    "first_targets": [],
                    "field_replacement_targets": [],
                }
                self._prompt_effect_target(
                    player,
                    "ally_minion",
                    None,
                    replacements_needed,
                    effect=effect,
                    source_ci=ci,
                )
                return
        if mode == "main":
            ci = self._play_action_card(player, action)
            self.engine.play_card(
                ci,
                payment_base_iids=action.payload.get("payment_base_iids"),
                replace_field_iid=action.payload.get("replace_field_iid"),
                resolve_triggers=False,
            )
            pending_mode = "main_deferred"
        else:
            ci = self._play_action_card(player, action)
            self.engine.apply_flash_action(player, action, resolve_triggers=False)
            pending_mode = "flash_deferred"
        self._log_event(f"{player.name}: {label}", event)
        if not self.engine.triggers.has_pending(instance=ci, trigger=effect):
            self._resolve_deferred_play_without_effect(player, mode)
            return
        replacements_needed = self._token_replacements_needed_after_play(player, effect)
        self._pending_effect = {
            "mode": pending_mode,
            "player": player,
            "source": ci,
            "effect": effect,
            "skip_discards_effect": effect.optional,
        }
        if effect.optional:
            self._prompt_optional_effect(player, ci, effect)
            return
        if replacements_needed:
            self._pending_effect = {
                **self._pending_effect,
                "stage": "field_replacement",
                "first_targets": [],
                "field_replacement_targets": [],
            }
            self._prompt_effect_target(player, "ally_minion", None, replacements_needed, effect=effect, source_ci=ci)
            return
        self.engine.triggers.resolve_all()
        self._log_public_reveals()

    def _post_draw_discard_effect_for_action(self, action: Action, player: Player) -> EffectSpec | None:
        if action.kind != "play_card":
            return None
        try:
            card = self._play_action_card(player, action).card
        except IllegalActionError:
            return None
        if card.type is not CardType.MAGIC:
            return None
        return next(
            (
                effect for effect in card.effects
                if effect.timing is EffectTiming.ON_CAST_MAGIC
                and effect.params.get("post_draw_discard_hand")
            ),
            None,
        )

    def _begin_post_draw_discard_effect(self, player: Player, action: Action, effect: EffectSpec) -> None:
        label = self._action_label(action)
        event = self._action_log_event(player, action, label)
        ci = self._play_action_card(player, action)
        before = self._visual_state_snapshot()
        self.engine.play_card(
            ci,
            payment_base_iids=action.payload.get("payment_base_iids"),
            resolve_triggers=False,
            resolve_source_effects=False,
        )
        ctx = Context(controller=player, source=ci)
        self.engine._record_effect_event(ci, effect, ctx)
        self.engine.draw(player, int(effect.params.get("draw_amount", 2)))
        self._record_visual_changes(before)
        self._log_event(f"{player.name}: {label}", event)
        if player.hand:
            self._pending_effect = {"mode": "post_draw_discard", "player": player, "source": ci, "effect": effect}
            self._prompt_effect_target(player, "hand_card", None, 1, effect=effect, source_ci=ci)
            return
        before = self._visual_state_snapshot()
        self.engine.triggers.resolve_all()
        self._record_visual_changes(before)
        self._log_public_reveals()

    def _begin_pre_target_effect(self, player: Player, action: Action, effect: EffectSpec) -> None:
        label = self._action_label(action)
        event = self._action_log_event(player, action, label)
        source = self._play_action_card(player, action)
        before = self._visual_state_snapshot()
        self.engine.play_card(
            source,
            payment_base_iids=action.payload.get("payment_base_iids"),
            replace_field_iid=action.payload.get("replace_field_iid"),
            resolve_triggers=False,
            resolve_source_effects=False,
        )
        ctx = Context(controller=player, source=source)
        self.engine._run_pre_target_effect(effect, source, ctx)
        self._record_visual_changes(before)
        self._log_event(f"{player.name}: {label}", event)

        kind = effect.target_kind
        eligible = (
            self._eligible_targets(player, kind, None, effect, source_ci=source)
            if kind is not None
            else []
        )
        if eligible:
            target_count = min(self._target_count_for_effect(player, effect), len(eligible))
            self._pending_effect = {
                "mode": "source_deferred",
                "player": player,
                "source": source,
                "effect": effect,
                "context": ctx,
            }
            self._prompt_effect_target(
                player,
                kind,
                None,
                target_count,
                effect=effect,
                source_ci=source,
            )
            return

        before = self._visual_state_snapshot()
        self.engine._record_effect_event(source, effect, ctx)
        self.engine._run_effect_callback(effect.fn, source, self.engine.state, ctx)
        self.engine.triggers.resolve_all()
        self._record_visual_changes(before)
        self._log_public_reveals()

    def _prompt_optional_effect(self, player: Player, source: CardInstance, effect: EffectSpec) -> None:
        if effect.template_id == "create_tokens":
            amount = int(effect.params.get("amount") or 0)
            options = [
                (
                    f"count_{count}",
                    f"{count} token" if count == 1 else f"{count} tokens",
                    {"useEffect": count > 0, "tokenCount": count},
                    {"choice": "token_count", "kind": "token_count", "tokenCount": count},
                )
                for count in range(amount + 1)
            ]
            self._set_prompt("optional_effect", f"Choose tokens for {source.card.name_jp}", options)
            self.prompt["choiceKind"] = "token_count"
            self.prompt["minimumTokenCount"] = 0
            self.prompt["maximumTokenCount"] = amount
        else:
            self._set_prompt("optional_effect", f"Use {source.card.name_jp} effect?", [
                ("yes", "Use effect", {"useEffect": True}, {"choice": "yes"}),
                ("no", "Skip", {"useEffect": False}, {"choice": "no"}),
            ])
        self.prompt["playerSide"] = player.side.name
        self.prompt["card"] = serialize_card(self.engine, source, self.asset_index)
        text = self._effect_event_text(source, effect, Context(controller=player, source=source))
        if text:
            self.prompt["effectText"] = text

    def _begin_deferred_play_effect(self, player: Player, action: Action, mode: str) -> None:
        effect = self._targeted_effect_for_action(action, player)
        kind = self._target_kind_for_action(action, player)
        target_count = self._target_count_for_action(action, player)
        label = self._action_label(action)
        event = self._action_log_event(player, action, label)
        ci = self._play_action_card(player, action)
        if mode == "main":
            self.engine.play_card(
                ci,
                payment_base_iids=action.payload.get("payment_base_iids"),
                replace_field_iid=action.payload.get("replace_field_iid"),
                resolve_triggers=False,
            )
            pending_mode = "main_deferred"
        else:
            self.engine.apply_flash_action(player, action, resolve_triggers=False)
            pending_mode = "flash_deferred"
        self._log_event(f"{player.name}: {label}", event)
        if isinstance(effect, EffectSpec) and not self.engine.triggers.has_pending(
            instance=ci,
            trigger=effect,
        ):
            self._resolve_deferred_play_without_effect(player, mode)
            return
        sequence = self._custom_source_effect_sequence(
            ci,
            effect,
            Context(controller=player, source=ci),
        )
        if sequence:
            self._pending_effect = {
                "mode": pending_mode,
                "stage": "source_sequence",
                "target_sequence": sequence,
                "target_sequence_index": 0,
                "first_targets": [],
                "player": player,
                "action": action,
                "source": ci,
                "effect": effect,
            }
            self._prompt_effect_target(
                player,
                sequence[0],
                None,
                1,
                effect=effect,
                source_ci=ci,
            )
            return
        eligible_targets = self._eligible_targets(player, kind, None, effect, source_ci=ci)
        if not eligible_targets:
            if kind == "top3_magic" and player.deck[:3]:
                self._pending_effect = {
                    "mode": pending_mode,
                    "player": player,
                    "action": action,
                    "source": ci,
                    "effect": effect,
                }
                self._prompt_effect_target(
                    player,
                    kind,
                    None,
                    1,
                    effect=effect,
                    source_ci=ci,
                )
                return
            self.engine.triggers.resolve_all()
            self._log_public_reveals()
            return
        target_count = min(target_count, len(eligible_targets))
        self._pending_effect = {
            "mode": pending_mode,
            "player": player,
            "action": action,
            "source": ci,
            "effect": effect,
        }
        self._prompt_effect_target(player, kind, None, target_count, effect=effect, source_ci=ci)

    def _resolve_deferred_play_without_effect(self, player: Player, mode: str) -> None:
        self.engine.triggers.resolve_all()
        self._log_public_reveals()
        if mode == "flash" and self._attack is not None:
            self._attack.passes = 0
            self._attack.priority = self._other_player(player)
            self._continue_attack_flow()

    def _log_public_reveals(self) -> None:
        while self.engine.public_reveals:
            player, card, reason = self.engine.public_reveals.pop(0)
            self._log_event(f"{player.name}: revealed {card.card.name_jp} ({reason})", {
                "type": "reveal",
                "actorName": player.name,
                "actorSide": player.side.name,
                "card": self._card_log_payload(card),
                "reason": reason,
            })
            self._public_reveals.append({
                "playerName": player.name,
                "playerSide": player.side.name,
                "reason": reason,
                "card": serialize_card(self.engine, card, self.asset_index),
            })

    def _action_needs_effect_target(self, action: Action, player: Player) -> bool:
        kind = self._target_kind_for_action(action, player)
        effect = self._targeted_effect_for_action(action, player)
        if kind == "top3_magic":
            return bool(player.deck[:3])
        return kind is not None and bool(self._eligible_targets(player, kind, action, effect))

    def _play_effect_timing_for_card(self, card) -> EffectTiming | None:
        if card.type is CardType.F_MINION:
            return EffectTiming.ON_SUMMON
        if card.type is CardType.MAGIC:
            return EffectTiming.ON_CAST_MAGIC
        return None

    def _effect_needs_target_choice(self, effect: EffectSpec) -> bool:
        return bool(effect.target_kind) and not bool(effect.params.get("all_targets"))

    def _targeted_effect_for_card(self, card, timing: EffectTiming | None) -> EffectSpec | None:
        if timing is None:
            return None
        return next(
            (
                effect for effect in card.effects
                if effect.timing is timing and self._effect_needs_target_choice(effect)
            ),
            None,
        )

    def _targeted_effect_for_action(self, action: Action, player: Player) -> EffectSpec | None:
        if action.kind != "play_card":
            return None
        try:
            card = self._play_action_card(player, action).card
        except IllegalActionError:
            return None
        return self._targeted_effect_for_card(card, self._play_effect_timing_for_card(card))

    def _token_replacements_needed_before_play(
            self,
            player: Player,
            card,
            effect: EffectSpec,
            action: Action | None = None,
    ) -> int:
        if effect.template_id != "create_tokens":
            return 0
        amount = int(effect.params.get("amount") or 0)
        entering = 1 if card.type is CardType.F_MINION else 0
        explicit_field_replacement = bool(
            card.type is CardType.F_MINION
            and action is not None
            and action.payload.get("replace_field_iid") is not None
        )
        return max(
            0,
            len(player.field) + entering + amount - FIELD_CAP - int(explicit_field_replacement),
        )

    def _token_replacements_needed_after_play(self, player: Player, effect: EffectSpec) -> int:
        if effect.template_id != "create_tokens":
            return 0
        amount = int(effect.params.get("amount") or 0)
        return max(0, len(player.field) + amount - FIELD_CAP)

    def _play_resolution_prompt_effect_for_action(self, action: Action, player: Player) -> EffectSpec | None:
        if action.kind != "play_card":
            return None
        try:
            card = self._play_action_card(player, action).card
        except IllegalActionError:
            return None
        if card.type not in (CardType.F_MINION, CardType.MAGIC):
            return None
        timing = self._play_effect_timing_for_card(card)
        if timing is None:
            return None
        for effect in card.effects:
            if effect.timing is not timing or self._effect_needs_target_choice(effect):
                continue
            if card.type is CardType.MAGIC and effect.template_id != "create_tokens":
                continue
            if effect.optional or self._token_replacements_needed_before_play(player, card, effect, action) > 0:
                return effect
        return None

    def _target_kind_for_action(self, action: Action, player: Player) -> str | None:
        if action.kind != "play_card":
            return None
        effect = self._targeted_effect_for_action(action, player)
        if effect is not None:
            return effect.target_kind
        card = self._play_action_card(player, action).card
        return TARGETED_CARD_KINDS.get(card.id)

    def _target_count_for_action(self, action: Action, player: Player) -> int:
        if action.kind != "play_card":
            return 1
        effect = self._targeted_effect_for_action(action, player)
        if effect is not None:
            return self._target_count_for_effect(player, effect)
        card = self._play_action_card(player, action).card
        return TARGETED_CARD_COUNTS.get(card.id, 1)

    def _target_count_for_effect(self, player: Player, effect: EffectSpec | None) -> int:
        if effect is None:
            return 1
        if effect.params.get("exact_target_count_from_own_destroyed_forces"):
            return max(0, self.engine.destroyed_forces_count(player))
        return max(1, effect.max_targets + self._extra_rest_targets(player, effect))

    def _extra_rest_targets(self, player: Player, effect: EffectSpec | None) -> int:
        if effect is None or effect.template_id != "rest_targets":
            return 0
        return 1 if any(
            ci.card.id == "green_04_02_01_01" and ci.area is AreaType.FIELD
            for ci in player.field
        ) else 0

    def _attack_target_kind_for_attacker(self, attacker: CardInstance) -> str | None:
        effect = self._targeted_effect_for_card(attacker.card, EffectTiming.ON_ATTACK)
        if effect is not None:
            return effect.target_kind
        return TARGETED_ATTACK_CARD_KINDS.get(attacker.card.id)

    def _play_action_card(self, player: Player, action: Action) -> CardInstance:
        return self.engine._find(player.hand, action.payload["iid"])

    def _prompt_effect_target(
            self,
            player: Player,
            kind: str,
            action: Action | None = None,
            target_count: int = 1,
            effect: EffectSpec | None = None,
            source_ci: CardInstance | None = None,
            excluded_targets: list[Any] | None = None,
    ) -> None:
        options = []
        eligible_targets = self._eligible_targets(player, kind, action, effect, source_ci=source_ci)
        if excluded_targets:
            eligible_targets = [target for target in eligible_targets if target not in excluded_targets]
        deck_reorder = bool(
            effect
            and effect.params.get("deck_reorder") == "top_or_bottom"
        )
        if deck_reorder:
            if len(eligible_targets) != 1:
                raise IllegalActionError("deck top-or-bottom choice requires exactly one top card")
            top_card = eligible_targets[0]
            top_meta = self._effect_target_meta(top_card)
            top_meta.update({
                "kind": "deck_reorder_option",
                "choiceKind": "deck_top_or_bottom",
                "reorderPosition": "top",
            })
            options.extend([
                ("top", "deck_top", top_card, top_meta),
                (
                    "bottom",
                    "deck_bottom",
                    None,
                    {
                        "kind": "deck_reorder_option",
                        "choiceKind": "deck_top_or_bottom",
                        "reorderPosition": "bottom",
                        "targetKind": "deck_reorder",
                    },
                ),
            ])
        optional_choice = kind in OPTIONAL_EFFECT_TARGET_KINDS or bool(effect and effect.optional)
        exact_dynamic_targets = bool(effect and effect.params.get("exact_target_count_from_own_destroyed_forces"))
        variable_targets = bool(
            effect and (
                effect.params.get("allow_variable_targets")
                or effect.optional
                or effect.min_targets != effect.max_targets
            ) and not exact_dynamic_targets
        )
        min_target_count = (
            target_count
            if exact_dynamic_targets
            else 0 if optional_choice else max(0, effect.min_targets if effect else 1)
        )
        if kind in OPTIONAL_EFFECT_TARGET_KINDS:
            if kind == "top3_magic":
                target_count = min(target_count, len(eligible_targets)) if eligible_targets else max(1, target_count)
            else:
                target_count = max(target_count, effect.max_targets if effect else 1)
        elif eligible_targets:
            target_count = max(1, min(target_count, len(eligible_targets)))
        if variable_targets:
            min_target_count = min(min_target_count, target_count)
        if not deck_reorder:
            for index, target in enumerate(eligible_targets):
                options.append((
                    f"e{index}",
                    self._effect_target_label(target),
                    target,
                    self._effect_target_meta(target),
                ))
        if optional_choice:
            options.append((
                "none",
                "No effect" if effect and effect.optional else "No reveal",
                None,
                {"kind": "effect_target_skip", "choiceKind": kind},
            ))
        message = f"Choose {kind.replace('_', ' ')}"
        if target_count > 1:
            message += f" ({target_count})"
        self._set_prompt("effect_target", message, options)
        self.prompt["choiceKind"] = "deck_top_or_bottom" if deck_reorder else kind
        self.prompt["playerSide"] = player.side.name
        self.prompt["requiredTargetCount"] = target_count
        self.prompt["minimumTargetCount"] = min_target_count if variable_targets else target_count
        self.prompt["maximumTargetCount"] = target_count
        self.prompt["allowVariableTargetCount"] = variable_targets
        if source_ci is not None:
            self.prompt["card"] = serialize_card(self.engine, source_ci, self.asset_index)
            if effect is not None:
                text = self._effect_event_text(source_ci, effect, Context(controller=player, source=source_ci))
                if text:
                    self.prompt["effectText"] = text
        revealed = self._revealed_cards_for_effect(player, kind)
        if revealed:
            self.prompt["revealedCards"] = [
                self._effect_target_meta(target) for target in revealed
            ]

    def _effect_target_label(self, target: CardInstance | ForceInstance | Force | Player) -> str:
        if isinstance(target, Player):
            return target.name
        if isinstance(target, ForceInstance):
            return target.force.name_jp
        if isinstance(target, Force):
            return target.name_jp
        return target.card.name_jp

    def _effect_target_position_label(self, target: CardInstance | ForceInstance | Force | Player) -> str:
        if isinstance(target, Player):
            return f"{target.side.name} PLAYER"
        if isinstance(target, ForceInstance):
            try:
                index = target.owner.forces.index(target) + 1
            except ValueError:
                index = None
            suffix = f" #{index}" if index is not None else ""
            return f"{target.owner.side.name} FORCE{suffix}"
        if isinstance(target, Force):
            return "FORCE CATALOG"
        zone_names = {
            AreaType.FIELD: ("FIELD", target.owner.field),
            AreaType.BASE: ("BASE", target.owner.base),
            AreaType.HAND: ("HAND", target.owner.hand),
            AreaType.DECK: ("DECK", target.owner.deck),
            AreaType.TRASH: ("TRASH", target.owner.trash),
            AreaType.REMOVED: ("REMOVED", target.owner.removed),
        }
        zone_name, zone = zone_names.get(target.area, (target.area.value.upper(), []))
        try:
            index = zone.index(target) + 1
        except ValueError:
            index = None
        suffix = f" #{index}" if index is not None else ""
        return f"{target.owner.side.name} {zone_name}{suffix}"

    def _effect_target_meta(self, target: CardInstance | ForceInstance | Force | Player) -> dict[str, Any]:
        if isinstance(target, Player):
            return {
                "kind": "effect_target",
                "targetKind": "player",
                "nameJp": target.name,
                "type": "player",
                "targetLabel": self._effect_target_position_label(target),
                "life": target.life,
                "maxLife": LIFE_CAP,
                "ownerSide": target.side.name,
            }
        if isinstance(target, ForceInstance):
            return {
                "kind": "effect_target",
                "targetKind": "force",
                "forceId": target.force.id,
                "nameJp": target.force.name_jp,
                "type": "force",
                "targetLabel": self._effect_target_position_label(target),
                "life": target.life,
                "initialLife": target.force.initial_life,
                "maxLife": LIFE_CAP,
                "assetUrl": self.asset_index.asset_url(target.force.id),
                "ownerSide": target.owner.side.name,
                "rested": target.rested,
            }
        if isinstance(target, Force):
            return {
                "kind": "effect_target",
                "targetKind": "force_ability",
                "forceId": target.id,
                "nameJp": target.name_jp,
                "type": "force_ability",
                "targetLabel": "FORCE CATALOG",
                "assetUrl": self.asset_index.asset_url(target.id),
            }
        return {
            "kind": "effect_target",
            "targetKind": "card",
            "cardIid": target.iid,
            "cardId": target.card.id,
            "nameJp": target.card.name_jp,
            "type": target.card.type.value,
            "bp": target.card.bp,
            "dp": target.card.dp,
            "effectiveBp": self.engine.effective_bp(target),
            "effectiveDp": self.engine.effective_dp(target),
            "targetLabel": self._effect_target_position_label(target),
            "assetUrl": self.asset_index.asset_url(target.card.id),
            "ownerSide": target.owner.side.name,
            "area": target.area.value,
            "rested": target.rested,
        }

    def _effect_target_log_payload(self, target: Any) -> dict[str, Any]:
        if isinstance(target, Color):
            return {
                "kind": "effect_target",
                "targetKind": "mana_color",
                "type": "mana_color",
                "manaColor": target.name,
                "nameJp": target.name,
                "targetLabel": target.name,
            }
        if isinstance(target, (CardInstance, ForceInstance, Force, Player)):
            return self._effect_target_meta(target)
        return {
            "kind": "effect_target",
            "targetKind": "unknown",
            "type": "unknown",
            "label": str(target),
            "targetLabel": str(target),
        }

    def _revealed_cards_for_effect(self, player: Player, kind: str) -> list[CardInstance]:
        count = LOOK_WINDOW_SIZES.get(kind)
        if count is None:
            if not kind.startswith("top"):
                return []
            match = re.match(r"top(\d+)_", kind)
            count = int(match.group(1)) if match else 4
        return list(player.deck[:count])

    def _entering_minion_for_action(self, player: Player, action: Action | None) -> CardInstance | None:
        if action is None or action.kind != "play_card":
            return None
        try:
            ci = self.engine._find(player.hand, action.payload["iid"])
        except IllegalActionError:
            return None
        if ci.card.type is CardType.F_MINION:
            return ci
        return None

    def _eligible_targets(
            self,
            player: Player,
            kind: str,
            action: Action | None = None,
            effect: EffectSpec | None = None,
            source_ci: CardInstance | None = None,
    ) -> list[Any]:
        opponent = self._other_player(player)
        if kind == "enemy_minion":
            return self._filter_card_targets_for_effect(player, list(opponent.field), action, effect, source_ci)
        if kind == "any_minion":
            return self._filter_card_targets_for_effect(player, list(player.field) + list(opponent.field), action, effect, source_ci)
        if kind == "enemy_minion_cost_at_most_4":
            return self._filter_card_targets_for_effect(player, [
                target for target in opponent.field
                if sum(target.card.cost.values()) <= 4
            ], action, effect, source_ci)
        if kind == "enemy_minion_cost_at_least_6":
            return self._filter_card_targets_for_effect(player, [
                target for target in opponent.field
                if sum(target.card.cost.values()) >= 6
            ], action, effect, source_ci)
        if kind == "enemy_minion_cost_at_most_3":
            return self._filter_card_targets_for_effect(player, [
                target for target in opponent.field
                if sum(target.card.cost.values()) <= 3
            ], action, effect, source_ci)
        if kind == "enemy_minion_or_force":
            forces = self._filter_effect_targets(
                player,
                [force for force in opponent.forces if not force.destroyed],
                action,
                source_ci=source_ci,
            )
            return (
                self._filter_card_targets_for_effect(player, list(opponent.field), action, effect, source_ci)
                + self._filter_targets_for_effect(forces, effect)
            )
        if kind == "any_minion_or_force":
            forces = self._filter_effect_targets(
                player,
                [
                    force
                    for owner in (player, opponent)
                    for force in owner.forces
                    if not force.destroyed
                ],
                action,
                source_ci=source_ci,
            )
            return (
                self._filter_card_targets_for_effect(player, list(player.field) + list(opponent.field), action, effect, source_ci)
                + self._filter_targets_for_effect(forces, effect)
            )
        if kind == "surprise_attack_targets":
            return self._filter_card_targets_for_effect(player, list(player.field) + list(opponent.field), action, effect, source_ci)
        if kind == "ally_minion":
            targets = list(player.field)
            entering = self._entering_minion_for_action(player, action)
            if entering is not None and entering not in targets:
                targets.append(entering)
            return self._filter_card_targets_for_effect(player, targets, action, effect, source_ci)
        if kind == "other_ally_minion":
            targets = [
                target for target in player.field
                if source_ci is None or target is not source_ci
            ]
            return self._filter_card_targets_for_effect(player, targets, action, effect, source_ci)
        if kind == "ally_minion_cost_at_most_4":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.field
                if sum(target.card.cost.values()) <= 4
            ], action, effect, source_ci)
        if kind == "ally_base":
            return self._filter_card_targets_for_effect(player, list(player.base), action, effect, source_ci)
        if kind == "ally_colorless_mana_token":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.base
                if target.card.type is CardType.MANA_TOKEN and self.engine._mana_color_of(target) is Color.COLORLESS
            ], action, effect, source_ci)
        if kind == "pc02_fossil_dragon":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck[:3]
                if target.card.type is CardType.F_MINION
                and "ドラゴン" in target.card.race_jp
                and (Color.RED in target.card.cost or set(target.card.cost) <= {Color.COLORLESS})
            ], action, effect, source_ci)
        if kind == "ally_minion_base":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.base
                if target.card.type in (CardType.B_MINION, CardType.F_MINION)
            ], action, effect, source_ci)
        if kind == "enemy_force":
            return self._filter_targets_for_effect(self._filter_effect_targets(
                player,
                [force for force in opponent.forces if not force.destroyed],
                action,
                source_ci=source_ci,
            ), effect)
        if kind == "ally_force":
            return self._filter_targets_for_effect(self._filter_effect_targets(
                player,
                [force for force in player.forces if not force.destroyed],
                action,
                source_ci=source_ci,
            ), effect)
        if kind == "owner_player_or_force":
            return [player] + [force for force in player.forces if not force.destroyed]
        if kind == "ally_green_base_hand":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.hand
                if target.card.type is CardType.B_MINION and target.card.mana_color is Color.GREEN
            ], action, effect, source_ci)
        if kind == "hand_base_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.hand
                if target.card.type is CardType.B_MINION
            ], action, effect, source_ci)
        if kind == "hand_card":
            return self._filter_card_targets_for_effect(player, list(player.hand), action, effect, source_ci)
        if kind == "deck_card":
            return self._filter_card_targets_for_effect(player, list(player.deck), action, effect, source_ci)
        if kind == "pc02_celica_dragon":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck
                if target.card.type is CardType.F_MINION
                and "ドラゴン" in target.card.race_jp
                and (
                    self._card_is_color(target.card, Color.YELLOW)
                    or sum(target.card.cost.values()) >= 9
                )
            ], action, effect, source_ci)
        if kind == "hand_field_minion_cost_at_most_2":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.hand
                if target.card.type is CardType.F_MINION and sum(target.card.cost.values()) <= 2
            ], action, effect, source_ci)
        if kind == "trash_magic_cost_at_most_4":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.trash
                if target.card.type is CardType.MAGIC and sum(target.card.cost.values()) <= 4
            ], action, effect, source_ci)
        if kind == "trash_field_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.trash
                if target.card.type is CardType.F_MINION
            ], action, effect, source_ci)
        if kind == "pc02_francesca_dragon":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.trash
                if target.card.type is CardType.F_MINION
                and "ドラゴン" in target.card.race_jp
                and (
                    self._card_is_color(target.card, Color.PURPLE)
                    or self._card_is_color(target.card, Color.COLORLESS)
                )
            ], action, effect, source_ci)
        if kind == "trash_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.trash
                if target.card.type in (CardType.B_MINION, CardType.F_MINION)
            ], action, effect, source_ci)
        if kind == "deck_base_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck
                if target.card.type is CardType.B_MINION
            ], action, effect, source_ci)
        if kind == "deck_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck
                if target.card.type in (CardType.B_MINION, CardType.F_MINION)
            ], action, effect, source_ci)
        if kind == "deck_base_or_field_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck
                if target.card.type in (CardType.B_MINION, CardType.F_MINION)
            ], action, effect, source_ci)
        if kind == "top_field_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck[:4]
                if target.card.type is CardType.F_MINION
            ], action, effect, source_ci)
        if kind == "top2_field_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck[:2]
                if target.card.type is CardType.F_MINION
            ], action, effect, source_ci)
        if kind == "top1_card":
            return self._filter_card_targets_for_effect(
                player, list(player.deck[:1]), action, effect, source_ci
            )
        if kind == "top2_card":
            return self._filter_card_targets_for_effect(
                player, list(player.deck[:2]), action, effect, source_ci
            )
        if kind == "top4_card":
            return self._filter_card_targets_for_effect(
                player, list(player.deck[:4]), action, effect, source_ci
            )
        if kind == "top3_magic":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck[:3]
                if target.card.type is CardType.MAGIC
            ], action, effect, source_ci)
        if kind == "enemy_minion_bp_at_most_500_or_opponent_player":
            cards = [target for target in opponent.field if self.engine.effective_bp(target) <= 500]
            return self._filter_card_targets_for_effect(player, cards, action, effect, source_ci) + [opponent]
        if kind == "force_catalog":
            return list(ALL_FORCES.values())
        if kind == "top3_field_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in player.deck[:3]
                if target.card.type is CardType.F_MINION
            ], action, effect, source_ci)
        if kind == "pc02_destroy_effect_minion":
            return self._filter_card_targets_for_effect(player, [
                target for target in opponent.field
                if any(card_effect.timing is EffectTiming.ON_DESTROY for card_effect in target.card.effects)
                or any(trigger.when is TriggerTiming.ON_DESTROY for trigger in target.card.triggers)
            ], action, effect, source_ci)
        return []

    def _filter_card_targets_for_effect(
            self,
            player: Player,
            targets: list[CardInstance],
            action: Action | None,
            effect: EffectSpec | None,
            source_ci: CardInstance | None = None,
    ) -> list[CardInstance]:
        targets = self._filter_effect_targets(player, targets, action, source_ci=source_ci)
        if effect is not None:
            if effect.params.get("exclude_source") and source_ci is not None:
                targets = [target for target in targets if target is not source_ci]
            if effect.params.get("exclude_tokens"):
                targets = [target for target in targets if not target.card.is_token]
            if effect.params.get("required_keyword"):
                keyword = Keyword[str(effect.params["required_keyword"])]
                targets = [target for target in targets if self.engine.has_keyword(target, keyword)]
        return self._filter_targets_for_effect(targets, effect)

    def _filter_targets_for_effect(self, targets: list[Any], effect: EffectSpec | None) -> list[Any]:
        if effect is None:
            return targets
        if effect.params.get("only_rested"):
            targets = [target for target in targets if bool(getattr(target, "rested", False))]
        if effect.params.get("only_active"):
            targets = [target for target in targets if not bool(getattr(target, "rested", False))]
        params = {
            key: value
            for key, value in effect.params.items()
            if key in EFFECT_TARGET_FILTER_PARAMS and value is not None
        }
        if not params:
            return targets
        matcher = _target_filter(self.engine, **params)
        return [target for target in targets if matcher(target)]

    def _effect_selection_source(
            self,
            player: Player,
            action: Action | None,
            source_ci: CardInstance | None = None,
    ) -> tuple[CardInstance | None, AreaType | None]:
        source = source_ci
        if source is None and action is not None and action.kind == "play_card":
            try:
                source = self._play_action_card(player, action)
            except IllegalActionError:
                source = None
        if source is None:
            return None, None
        source_area = None
        if action is not None and action.kind == "play_card" and source.card.type is CardType.F_MINION:
            source_area = AreaType.FIELD
        return source, source_area

    def _filter_effect_targets(
            self,
            player: Player,
            targets: list[Any],
            action: Action | None,
            source_ci: CardInstance | None = None,
    ) -> list[Any]:
        source, source_area = self._effect_selection_source(player, action, source_ci)
        if source is not None:
            targets = [
                target for target in targets
                if self.engine._can_effect_select(source, target, source_area=source_area)
            ]
        if action is None or action.kind != "play_card":
            return targets
        try:
            action_source = self._play_action_card(player, action)
        except IllegalActionError:
            return targets
        if action_source.card.type is not CardType.MAGIC:
            return targets
        return [
            target for target in targets
            if not (
                isinstance(target, CardInstance)
                and target.owner is not player
                and target.card.id == "white_08_02_01_01"
            )
        ]

    def _other_player(self, player: Player) -> Player:
        players = self.engine.state.players
        return players[1 - players.index(player)]

    def _action_label(self, action: Action) -> str:
        active = self.engine.state.active
        if action.kind == "play_card":
            iid = action.payload["iid"]
            for player in self.engine.state.players:
                for ci in player.hand:
                    if ci.iid == iid:
                        label = f"{action.kind}: {ci.card.name_jp}"
                        if "replace_field_iid" in action.payload:
                            replaced = self.engine._find(player.field, action.payload["replace_field_iid"])
                            label += f" / replace {replaced.card.name_jp}"
                        return label
        if action.kind == "play_to_base":
            iid = action.payload["iid"]
            for ci in active.hand:
                if ci.iid == iid:
                    label = f"{action.kind}: {ci.card.name_jp}"
                    if action.kind == "play_to_base" and "replace_base_iid" in action.payload:
                        replaced = self.engine._find(active.base, action.payload["replace_base_iid"])
                        label += f" / replace {replaced.card.name_jp}"
                    return label
        if action.kind == "place_colorless_mana" and "replace_base_iid" in action.payload:
            replaced = self.engine._find(active.base, action.payload["replace_base_iid"])
            return f"place colorless mana / replace {replaced.card.name_jp}"
        if action.kind == "move_card":
            ci = self.engine._find(active.base + active.field, action.payload["iid"])
            label = f"move: {ci.card.name_jp} {action.payload['direction']}"
            if "replace_field_iid" in action.payload:
                replaced = self.engine._find(active.field, action.payload["replace_field_iid"])
                label += f" / replace {replaced.card.name_jp}"
            if "replace_base_iid" in action.payload:
                replaced = self.engine._find(active.base, action.payload["replace_base_iid"])
                label += f" / replace {replaced.card.name_jp}"
            return label
        if action.kind == "bless":
            mana = self.engine._find(active.base, action.payload["mana_iid"])
            target = self.engine._find(active.field, action.payload["target_iid"])
            return f"bless: {mana.card.name_jp} -> {target.card.name_jp}"
        if action.kind == "attack":
            ci = self.engine._find(active.field, action.payload["attacker_iid"])
            return f"attack: {ci.card.name_jp}"
        if action.kind == "swap_mana_color":
            color = Color(action.payload["new_color"]).name
            return f"swap mana color: {color}"
        if action.kind == "place_colorless_mana":
            return "配置无色 Mana"
        if action.kind == "skip_mana":
            return "不放置 Mana"
        if action.kind == "flash_pass":
            return "Pass"
        if action.kind == "activate_flash_ability":
            for ci in active.field + self.engine.state.opponent.field:
                if ci.iid == action.payload["iid"]:
                    return f"Reactive: {ci.card.name_jp}"
        return action.kind.replace("_", " ")

    def _action_meta(self, action: Action) -> dict[str, Any]:
        meta = {"kind": action.kind}
        meta.update(action.payload)
        if action.kind == "play_card":
            payment = self._payment_meta_for_action(action)
            if payment:
                meta.update(payment)
        return meta

    def _payment_meta_for_action(self, action: Action) -> dict[str, Any]:
        found = self._hand_card_for_action(action)
        if found is None:
            return {}
        player, ci = found
        effective_cost = self.engine.effective_cost(player, ci)
        plan = self.engine.payment_plan(player, effective_cost, ci)
        candidates_by_iid = {
            item["iid"]: item
            for item in plan["candidates"]
        }
        candidates = []
        for base_ci in player.base:
            if base_ci.iid not in candidates_by_iid:
                continue
            candidates.append({
                "iid": base_ci.iid,
                "cardId": base_ci.card.id,
                "nameJp": base_ci.card.name_jp,
                "color": candidates_by_iid[base_ci.iid]["color"],
                "manaValue": candidates_by_iid[base_ci.iid]["manaValue"],
                "card": serialize_card(self.engine, base_ci, self.asset_index),
            })
        return {
            "paymentDefaultIids": plan["default"],
            "paymentCandidates": candidates,
            "paymentColorlessAsAny": plan["colorlessAsAny"],
            "paymentCost": {
                color.name: amount
                for color, amount in effective_cost.items()
            },
        }

    def _hand_card_for_action(self, action: Action) -> tuple[Player, CardInstance] | None:
        iid = action.payload.get("iid")
        if iid is None:
            return None
        for player in self.engine.state.players:
            for ci in player.hand:
                if ci.iid == iid:
                    return player, ci
        return None

    def _target_label(self, target: AttackTarget) -> str:
        if target.kind is AttackTargetKind.PLAYER:
            return f"Player: {target.ref.name}"
        if target.kind is AttackTargetKind.FORCE:
            return f"Force: {target.ref.force.name_jp}"
        return f"Minion: {target.ref.card.name_jp}"

    def _target_meta(self, target: AttackTarget) -> dict[str, Any]:
        if target.kind is AttackTargetKind.PLAYER:
            return {"kind": "player", "side": target.ref.side.name}
        if target.kind is AttackTargetKind.FORCE:
            return {
                "kind": "force",
                "forceId": target.ref.force.id,
                "ownerSide": target.ref.owner.side.name,
            }
        return {"kind": "minion", "cardIid": target.ref.iid}
