from __future__ import annotations

from typing import Any, Mapping

from zz.multiplayer.actions import CHOOSE_PROMPT_OPTION
from zz.multiplayer.views import player_for_id


class PolicyPromptController:
    """Adapts an existing Engine policy to the authoritative prompt action API."""

    def __init__(self, policy: Any):
        self.policy = policy

    def choose_action(self, match: Any, player_id: str) -> Mapping[str, Any]:
        session = match.session
        prompt = session.prompt
        if prompt is None or match.prompt_owner_id() != player_id:
            raise RuntimeError("policy has no pending decision")
        player = player_for_id(session, player_id)
        kind = prompt["kind"]
        option_id: str
        payload: dict[str, Any] = {}

        if kind == "mulligan":
            selected = list(self.policy.choose_mulligan(session.engine, player))
            option_id = "redraw_selected" if selected else "keep"
            if selected:
                payload["selectedCardIids"] = [card.iid for card in selected]
        elif kind == "main_action":
            option_id = self._option_id(session, self.policy.choose(session.engine))
        elif kind == "attack_target":
            targets = list(session._options.values())
            target = self.policy.choose_attack_target(session.engine, session._attack.attacker, targets)
            option_id = self._option_id(session, target)
        elif kind == "flash_action":
            legal = list(session._options.values())
            action = self.policy.choose_flash(session.engine, legal)
            option_id = self._option_id(session, action)
        elif kind == "blocker":
            blockers = [value for value in session._options.values() if value is not None]
            blocker = self.policy.choose_blocker(session.engine, session._attack.attacker, blockers)
            option_id = self._option_id(session, blocker)
        elif kind == "effect_target":
            eligible = [value for value in session._options.values() if value is not None]
            minimum = int(prompt.get("minimumTargetCount", prompt.get("requiredTargetCount", 1)))
            maximum = int(prompt.get("maximumTargetCount", prompt.get("requiredTargetCount", 1)))
            selected = list(self.policy.choose_target(
                session.engine,
                str(prompt.get("choiceKind") or "effect_target"),
                minimum,
                maximum,
                eligible,
            ))
            if selected:
                selected_ids = [self._option_id(session, target) for target in selected]
                option_id = selected_ids[0]
                payload["selectedOptionIds"] = selected_ids
            else:
                option_id = "none" if "none" in session._options else next(iter(session._options))
                payload["selectedOptionIds"] = []
        else:
            option_id = next(iter(session._options))

        return {
            "kind": CHOOSE_PROMPT_OPTION,
            "promptId": prompt["id"],
            "optionId": option_id,
            "payload": payload,
        }

    @staticmethod
    def _option_id(session: Any, selected: Any) -> str:
        for option_id, value in session._options.items():
            if value is selected or value == selected:
                return option_id
        raise RuntimeError(f"policy selected value outside current prompt: {selected!r}")
