from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping


PLAYER_IDS = ("player_1", "player_2")
CHOOSE_PROMPT_OPTION = "CHOOSE_PROMPT_OPTION"
SURRENDER = "SURRENDER"


@dataclass(frozen=True)
class SubmittedAction:
    match_id: str
    player_id: str
    client_action_id: str
    expected_revision: int
    action: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmittedAction":
        if not isinstance(value, Mapping):
            raise ValueError("submitted action must be an object")
        action = value.get("action")
        if not isinstance(action, Mapping):
            raise ValueError("action must be an object")
        expected_revision = value.get("expectedRevision")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expectedRevision must be an integer")
        return cls(
            match_id=str(value.get("matchId") or ""),
            player_id=str(value.get("playerId") or ""),
            client_action_id=str(value.get("clientActionId") or ""),
            expected_revision=expected_revision,
            action=deepcopy(dict(action)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "matchId": self.match_id,
            "playerId": self.player_id,
            "clientActionId": self.client_action_id,
            "expectedRevision": self.expected_revision,
            "action": deepcopy(dict(self.action)),
        }


@dataclass(frozen=True)
class ActionRejection:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ActionResult:
    accepted: bool
    revision: int
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    state_hash: str | None = None
    rejection: ActionRejection | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "accepted": self.accepted,
            "revision": self.revision,
            "events": deepcopy(list(self.events)),
        }
        if self.state_hash is not None:
            out["stateHash"] = self.state_hash
        if self.rejection is not None:
            out["rejection"] = self.rejection.to_dict()
        return out


@dataclass(frozen=True)
class AppliedActionRecord:
    revision: int
    submitted: SubmittedAction
    events: tuple[dict[str, Any], ...]
    state_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "submitted": self.submitted.to_dict(),
            "events": deepcopy(list(self.events)),
            "stateHash": self.state_hash,
        }
