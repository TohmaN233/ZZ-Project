from __future__ import annotations

import random
from typing import Any

from zz.engine import Engine
from zz.enums import AttackTargetKind, CardType
from zz.model import Action, AttackTarget, CardInstance


class GreedyLegalPolicy:
    ACTION_BASE_SCORES = {
        "play_to_base": 90,
        "play_card": 80,
        "attack": 70,
        "move_card_base_to_field": 60,
        "move_card_field_to_base": 45,
        "place_colorless_mana": 40,
        "swap_mana_color": 35,
        "skip_mana": 5,
        "end_turn": 0,
        "flash_pass": -10,
        "activate_flash_ability": 65,
    }

    def __init__(self, rng: random.Random):
        self.rng = rng

    def choose(self, engine: Engine) -> Action:
        legal = engine.legal_actions()
        if not legal:
            raise RuntimeError("no legal action")
        return max(legal, key=self._action_score)

    def choose_flash(self, engine: Engine, legal: list[Action]) -> Action:
        non_pass = [action for action in legal if action.kind != "flash_pass"]
        if non_pass and self.rng.random() < 0.25:
            return max(non_pass, key=self._action_score)
        return Action(kind="flash_pass")

    def choose_blocker(self, engine: Engine, attacker: CardInstance, blockers: list[CardInstance]):
        if not blockers:
            return None
        attacker_threat = attacker.dp + attacker.bp / 100
        best = max(blockers, key=lambda card: (card.dp, card.bp))
        if attacker_threat >= 2 or best.bp >= attacker.dp:
            return best
        return None

    def choose_attack_target(
        self,
        engine: Engine,
        attacker: CardInstance,
        targets: list[AttackTarget],
    ) -> AttackTarget:
        return max(targets, key=lambda target: self._attack_target_score(attacker, target))

    def choose_target(self, engine: Engine, kind: str, min_n: int, max_n: int, eligible: list) -> list:
        if not eligible or max_n <= 0:
            return []
        ordered = sorted(eligible, key=self._generic_target_score, reverse=True)
        count = max(min_n, min(max_n, len(ordered)))
        return ordered[:count]

    def choose_mulligan(self, engine: Engine, player) -> list[CardInstance]:
        early = [ci for ci in player.hand if self._card_total_cost(ci) <= 2 and ci.card.type is not CardType.B_MINION]
        bases = [ci for ci in player.hand if ci.card.type is CardType.B_MINION]
        if early and bases:
            return []
        return [
            ci
            for ci in player.hand
            if ci.card.type is not CardType.B_MINION and self._card_total_cost(ci) >= 5
        ]

    def _action_score(self, action: Action) -> tuple[float, float]:
        return self.score_action_for_lookahead(None, None, action), self.rng.random()

    def score_action_for_lookahead(self, _engine: Any, _player: Any, action: Action) -> float:
        if action.kind == "move_card":
            suffix = "base_to_field" if action.payload.get("direction") == "base_to_field" else "field_to_base"
            return float(self.ACTION_BASE_SCORES[f"move_card_{suffix}"])
        return float(self.ACTION_BASE_SCORES.get(action.kind, 10))

    def _attack_target_score(self, attacker: CardInstance, target: AttackTarget) -> tuple[float, float]:
        if target.kind is AttackTargetKind.PLAYER:
            return 100 + attacker.dp, self.rng.random()
        if target.kind is AttackTargetKind.FORCE:
            life = getattr(target.ref, "life", 99)
            lethal_bonus = 30 if attacker.bp >= life else 0
            return 80 + lethal_bonus - life, self.rng.random()
        return 40 + self._generic_target_score(target.ref), self.rng.random()

    def _generic_target_score(self, target: Any) -> float:
        card = getattr(target, "card", None)
        if card is None:
            return float(getattr(target, "life", 0))
        return (getattr(card, "dp", 0) * 10) + (getattr(card, "bp", 0) / 100) + self._card_total_cost(target)

    def _card_total_cost(self, ci: CardInstance) -> int:
        return sum(ci.card.cost.values())
