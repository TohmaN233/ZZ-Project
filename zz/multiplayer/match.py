from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from zz.deckcode0 import (
    DECKCODE0_GREEN_FORCES,
    DECKCODE0_YELLOW_FORCES,
    DEMETE_GREEN_RECIPE,
    KANATANA_YELLOW_RECIPE,
)
from zz.multiplayer.actions import (
    CHOOSE_PROMPT_OPTION,
    PLAYER_IDS,
    SURRENDER,
    ActionRejection,
    ActionResult,
    AppliedActionRecord,
    SubmittedAction,
)
from zz.multiplayer.hashing import canonical_authoritative_state, hash_authoritative_state
from zz.multiplayer.views import build_player_view, player_for_id, player_id_for_side
from zz.web.session import GameSession


RULES_VERSION = "0.0.2"


@dataclass(frozen=True)
class InitialMatchSpec:
    match_id: str
    seed: int
    first_player_id: str
    player_1_deck: Mapping[str, int]
    player_1_forces: tuple[str, str]
    player_2_deck: Mapping[str, int]
    player_2_forces: tuple[str, str]
    player_1_profile: Mapping[str, str | None] | None = None
    player_2_profile: Mapping[str, str | None] | None = None
    rules_version: str = RULES_VERSION

    def __post_init__(self) -> None:
        if not self.match_id or len(self.match_id) > 128:
            raise ValueError("match_id must contain 1-128 characters")
        if self.first_player_id not in PLAYER_IDS:
            raise ValueError(f"invalid first player {self.first_player_id!r}")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        object.__setattr__(self, "player_1_deck", MappingProxyType(dict(self.player_1_deck)))
        object.__setattr__(self, "player_2_deck", MappingProxyType(dict(self.player_2_deck)))
        object.__setattr__(self, "player_1_forces", tuple(self.player_1_forces))
        object.__setattr__(self, "player_2_forces", tuple(self.player_2_forces))

    @classmethod
    def standard(
        cls,
        *,
        match_id: str,
        seed: int,
        first_player_id: str = "player_1",
    ) -> "InitialMatchSpec":
        return cls(
            match_id=match_id,
            seed=seed,
            first_player_id=first_player_id,
            player_1_deck=KANATANA_YELLOW_RECIPE,
            player_1_forces=tuple(DECKCODE0_YELLOW_FORCES),
            player_2_deck=DEMETE_GREEN_RECIPE,
            player_2_forces=tuple(DECKCODE0_GREEN_FORCES),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "matchId": self.match_id,
            "seed": self.seed,
            "firstPlayerId": self.first_player_id,
            "player1Deck": dict(self.player_1_deck),
            "player1Forces": list(self.player_1_forces),
            "player2Deck": dict(self.player_2_deck),
            "player2Forces": list(self.player_2_forces),
            "player1Profile": dict(self.player_1_profile or {}),
            "player2Profile": dict(self.player_2_profile or {}),
            "rulesVersion": self.rules_version,
        }


class AuthoritativeMatch:
    def __init__(self, spec: InitialMatchSpec, *, asset_root: str | None = None):
        self.spec = spec
        self.session = GameSession(
            seed=spec.seed,
            mode="god",
            asset_root=asset_root,
            first_player="human" if spec.first_player_id == "player_1" else "ai",
            player_recipe=dict(spec.player_1_deck),
            player_force_ids=list(spec.player_1_forces),
            opponent_recipe=dict(spec.player_2_deck),
            opponent_force_ids=list(spec.player_2_forces),
            player_profile=dict(spec.player_1_profile or {}),
            opponent_profile=dict(spec.player_2_profile or {}),
        )
        self.revision = 0
        self._processed: dict[
            tuple[str, str],
            tuple[SubmittedAction, ActionResult],
        ] = {}
        self._action_log: list[AppliedActionRecord] = []

    @property
    def match_id(self) -> str:
        return self.spec.match_id

    @property
    def action_log(self) -> tuple[AppliedActionRecord, ...]:
        return tuple(self._action_log)

    def canonical_state(self) -> dict[str, Any]:
        return canonical_authoritative_state(
            self.session,
            revision=self.revision,
            initial_match=self.spec.to_dict(),
        )

    def state_hash(self) -> str:
        return hash_authoritative_state(
            self.session,
            revision=self.revision,
            initial_match=self.spec.to_dict(),
        )

    def get_view_for(self, player_id: str) -> dict[str, Any]:
        return build_player_view(
            self.session,
            player_id=player_id,
            revision=self.revision,
            state_hash=self.state_hash(),
        )

    def prompt_owner_id(self) -> str | None:
        side = self.session.prompt_controller_side()
        return None if side is None else player_id_for_side(side)

    def submit_controller_action(
        self,
        *,
        player_id: str,
        client_action_id: str,
        chooser: Callable[[dict[str, Any]], Mapping[str, Any]],
    ) -> ActionResult:
        view = self.get_view_for(player_id)
        prompt = view.get("prompt")
        if not isinstance(prompt, dict):
            return self._rejection("NOT_YOUR_TURN", "player has no pending decision")
        action = chooser(deepcopy(prompt))
        return self.submit_action(SubmittedAction(
            match_id=self.match_id,
            player_id=player_id,
            client_action_id=client_action_id,
            expected_revision=self.revision,
            action=deepcopy(dict(action)),
        ))

    def submit_policy_action(
        self,
        *,
        player_id: str,
        client_action_id: str,
        policy: Any,
    ) -> ActionResult:
        from zz.multiplayer.controllers import PolicyPromptController

        controller = PolicyPromptController(policy)
        return self.submit_controller_action(
            player_id=player_id,
            client_action_id=client_action_id,
            chooser=lambda _prompt: controller.choose_action(self, player_id),
        )

    def submit_action(self, submitted: SubmittedAction) -> ActionResult:
        shape_error = self._submission_error(submitted)
        if shape_error is not None:
            return shape_error

        cache_key = (submitted.player_id, submitted.client_action_id)
        cached = self._processed.get(cache_key)
        if cached is not None:
            previous, result = cached
            if previous.to_dict() == submitted.to_dict():
                return result
            return self._rejection(
                "DUPLICATE_ACTION",
                "clientActionId was already used for a different action",
            )

        if submitted.expected_revision != self.revision:
            return self._remember_rejection(
                submitted,
                "STALE_REVISION",
                f"expected revision {self.revision}",
            )
        if self.session._game_over is not None:
            return self._remember_rejection(submitted, "MATCH_FINISHED", "match already ended")

        action_kind = str(submitted.action.get("kind") or "")
        if action_kind == CHOOSE_PROMPT_OPTION:
            result = self._submit_prompt_choice(submitted)
        elif action_kind == SURRENDER:
            result = self._submit_surrender(submitted)
        else:
            result = self._remember_rejection(
                submitted,
                "INVALID_ACTION",
                f"unknown action kind {action_kind!r}",
            )
        return result

    def _submission_error(self, submitted: SubmittedAction) -> ActionResult | None:
        if submitted.match_id != self.match_id:
            return self._rejection("MATCH_NOT_FOUND", "submitted match does not exist")
        if submitted.player_id not in PLAYER_IDS:
            return self._rejection("PLAYER_NOT_IN_MATCH", "unknown player")
        if not submitted.client_action_id or len(submitted.client_action_id) > 128:
            return self._rejection(
                "INVALID_MESSAGE",
                "clientActionId must contain 1-128 characters",
            )
        if (
                isinstance(submitted.expected_revision, bool)
                or not isinstance(submitted.expected_revision, int)
                or submitted.expected_revision < 0
        ):
            return self._rejection("INVALID_MESSAGE", "expectedRevision must be non-negative")
        if not isinstance(submitted.action, Mapping):
            return self._rejection("INVALID_MESSAGE", "action must be an object")
        return None

    def _submit_prompt_choice(self, submitted: SubmittedAction) -> ActionResult:
        allowed_keys = {"kind", "promptId", "optionId", "payload"}
        unknown_keys = sorted(set(submitted.action) - allowed_keys)
        if unknown_keys:
            return self._remember_rejection(
                submitted,
                "INVALID_MESSAGE",
                f"unknown action field {unknown_keys[0]!r}",
            )
        prompt_id = submitted.action.get("promptId")
        option_id = submitted.action.get("optionId")
        payload = submitted.action.get("payload") or {}
        if not isinstance(prompt_id, str) or not isinstance(option_id, str):
            return self._remember_rejection(
                submitted,
                "INVALID_MESSAGE",
                "promptId and optionId must be strings",
            )
        if not isinstance(payload, Mapping):
            return self._remember_rejection(
                submitted,
                "INVALID_MESSAGE",
                "action payload must be an object",
            )
        if self.prompt_owner_id() != submitted.player_id:
            return self._remember_rejection(
                submitted,
                "NOT_YOUR_TURN",
                "pending decision belongs to the other player",
            )
        validation_error = self.session.validate_choice(prompt_id, option_id, dict(payload))
        if validation_error is not None:
            return self._remember_rejection(
                submitted,
                "INVALID_ACTION",
                validation_error["message"],
            )

        before_hash = self.state_hash()
        before_turn = self.session.engine.state.turn
        before_active_side = self.session.engine.state.active.side.name
        before_game_over = self.session._game_over is not None
        before_prompt_kind = None if self.session.prompt is None else self.session.prompt.get("kind")
        state = self.session.choose(prompt_id, option_id, dict(payload))
        error = state.get("error")
        if error is not None:
            after_hash = self.state_hash()
            if after_hash != before_hash:
                raise RuntimeError("rejected authoritative action mutated match state")
            return self._remember_rejection(
                submitted,
                "INVALID_ACTION",
                str(error.get("message") or "action rejected"),
            )
        return self._accept(
            submitted,
            before_turn=before_turn,
            before_active_side=before_active_side,
            before_game_over=before_game_over,
            prompt_kind=before_prompt_kind,
        )

    def _submit_surrender(self, submitted: SubmittedAction) -> ActionResult:
        if set(submitted.action) != {"kind"}:
            return self._remember_rejection(
                submitted,
                "INVALID_MESSAGE",
                "SURRENDER does not accept additional fields",
            )
        before_turn = self.session.engine.state.turn
        before_active_side = self.session.engine.state.active.side.name
        self.session.surrender(player_for_id(self.session, submitted.player_id).side.name)
        return self._accept(
            submitted,
            before_turn=before_turn,
            before_active_side=before_active_side,
            before_game_over=False,
            prompt_kind=None,
        )

    def _accept(
        self,
        submitted: SubmittedAction,
        *,
        before_turn: int,
        before_active_side: str,
        before_game_over: bool,
        prompt_kind: str | None,
    ) -> ActionResult:
        self.revision += 1
        events: list[dict[str, Any]] = [{
            "kind": "ACTION_RESOLVED",
            "playerId": submitted.player_id,
            "actionKind": str(submitted.action.get("kind")),
            "promptKind": prompt_kind,
        }]
        state = self.session.engine.state
        if state.turn != before_turn or state.active.side.name != before_active_side:
            events.append({
                "kind": "TURN_CHANGED",
                "turn": state.turn,
                "activePlayerId": player_id_for_side(state.active.side.name),
            })
        if not before_game_over and self.session._game_over is not None:
            events.append({
                "kind": "MATCH_ENDED",
                "winnerId": self._winner_player_id(),
                "reason": str(self.session._game_over.get("reason") or ""),
            })
        event_tuple = tuple(events)
        state_hash = self.state_hash()
        result = ActionResult(
            accepted=True,
            revision=self.revision,
            events=event_tuple,
            state_hash=state_hash,
        )
        stored_submission = SubmittedAction.from_dict(submitted.to_dict())
        self._processed[(submitted.player_id, submitted.client_action_id)] = (
            stored_submission,
            result,
        )
        self._action_log.append(AppliedActionRecord(
            revision=self.revision,
            submitted=stored_submission,
            events=event_tuple,
            state_hash=state_hash,
        ))
        return result

    def _winner_player_id(self) -> str | None:
        if self.session._game_over is None:
            return None
        winner_name = self.session._game_over.get("winner")
        if winner_name is None:
            return None
        winner = next(
            (player for player in self.session.engine.state.players if player.name == winner_name),
            None,
        )
        return None if winner is None else player_id_for_side(winner.side.name)

    def _remember_rejection(
        self,
        submitted: SubmittedAction,
        code: str,
        message: str,
    ) -> ActionResult:
        result = self._rejection(code, message)
        stored_submission = SubmittedAction.from_dict(submitted.to_dict())
        self._processed[(submitted.player_id, submitted.client_action_id)] = (
            stored_submission,
            result,
        )
        return result

    def _rejection(self, code: str, message: str) -> ActionResult:
        return ActionResult(
            accepted=False,
            revision=self.revision,
            state_hash=self.state_hash(),
            rejection=ActionRejection(code=code, message=message),
        )

    @classmethod
    def replay(
        cls,
        spec: InitialMatchSpec,
        records: Iterable[AppliedActionRecord | Mapping[str, Any]],
        *,
        asset_root: str | None = None,
    ) -> tuple["AuthoritativeMatch", tuple[ActionResult, ...]]:
        match = cls(spec, asset_root=asset_root)
        results = []
        for record in records:
            if isinstance(record, AppliedActionRecord):
                submitted = record.submitted
            else:
                submitted_data = record.get("submitted")
                if not isinstance(submitted_data, Mapping):
                    raise ValueError("action record is missing submitted action")
                submitted = SubmittedAction.from_dict(submitted_data)
            result = match.submit_action(submitted)
            if not result.accepted:
                raise RuntimeError(
                    f"recorded action rejected at revision {match.revision}: "
                    f"{result.rejection}"
                )
            results.append(result)
        return match, tuple(results)
