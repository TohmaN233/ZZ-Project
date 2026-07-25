from __future__ import annotations
import random
from typing import Protocol

from zz.engine import Engine
from zz.model import Action, AttackTarget, CardInstance


class Policy(Protocol):
    def choose(self, engine: Engine) -> Action: ...
    def choose_flash(self, engine: Engine, legal: list[Action]) -> Action: ...
    def choose_blocker(self, engine: Engine, attacker, blockers: list): ...
    def choose_attack_target(self, engine: Engine, attacker, targets: list[AttackTarget]) -> AttackTarget: ...
    def choose_target(self, engine: Engine, kind: str, min_n: int, max_n: int, eligible: list) -> list: ...
    def choose_mulligan(self, engine: Engine, player) -> list[CardInstance]: ...


class RandomLegalPolicy:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def choose(self, engine: Engine) -> Action:
        legal = engine.legal_actions()
        if not legal:
            raise RuntimeError("no legal action")
        return self.rng.choice(legal)

    def choose_flash(self, engine: Engine, legal: list[Action]) -> Action:
        # 70% chance to just pass to keep games moving
        if self.rng.random() < 0.7:
            return Action(kind="flash_pass")
        return self.rng.choice(legal)

    def choose_blocker(self, engine: Engine, attacker, blockers):
        if not blockers:
            return None
        if self.rng.random() < 0.5:
            return None
        return self.rng.choice(blockers)

    def choose_attack_target(self, engine: Engine, attacker, targets):
        return self.rng.choice(targets)

    def choose_target(self, engine: Engine, kind, min_n, max_n, eligible):
        if not eligible:
            return []
        k = min_n if min_n == max_n else self.rng.randint(min_n, max_n)
        return self.rng.sample(eligible, min(k, len(eligible)))

    def choose_mulligan(self, engine: Engine, player) -> list[CardInstance]:
        return [ci for ci in player.hand if self.rng.random() < 0.3]


class PassOnlyPolicy:
    """Deterministic debug opponent: end main decisions, pass flash, never block."""

    def choose(self, engine: Engine) -> Action:
        legal = engine.legal_actions()
        for kind in ("skip_mana", "end_turn"):
            for action in legal:
                if action.kind == kind:
                    return action
        if not legal:
            raise RuntimeError("no legal action")
        return legal[0]

    def choose_flash(self, engine: Engine, legal: list[Action]) -> Action:
        return Action(kind="flash_pass")

    def choose_blocker(self, engine: Engine, attacker, blockers):
        return None

    def choose_attack_target(self, engine: Engine, attacker, targets: list[AttackTarget]) -> AttackTarget:
        return targets[0]

    def choose_target(self, engine: Engine, kind: str, min_n: int, max_n: int, eligible: list) -> list:
        return eligible[:max_n]

    def choose_mulligan(self, engine: Engine, player) -> list[CardInstance]:
        return []
