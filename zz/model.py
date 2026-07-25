from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import Callable, Optional, TYPE_CHECKING, Any

from zz.enums import CardType, Color, Keyword, TriggerTiming, AttackTargetKind
from zz.effects import EffectSpec

if TYPE_CHECKING:
    from zz.model import CardInstance, Player, GameState  # noqa: F401


@dataclass
class Trigger:
    """A timed callback owned by a Card (template) or applied dynamically."""
    when: TriggerTiming
    fn: Callable[["CardInstance", "GameState", "Context"], None]
    condition: Optional[Callable[["CardInstance", "GameState", "Context"], bool]] = None


@dataclass
class Card:
    """Static card template. Same object shared by every copy of the card."""
    id: str
    name_jp: str
    name_en: str
    type: CardType
    is_token: bool = False
    cost: dict[Color, int] = field(default_factory=dict)
    bp: int = 0
    dp: int = 0
    mana_color: Optional[Color] = None
    race_jp: str = ""
    keywords: list[Keyword] = field(default_factory=list)
    ability_jp: str = ""
    ability_en: str = ""
    effects: list[EffectSpec] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    aura: Optional[Callable[["CardInstance", "CardInstance", "GameState"], tuple[int, int]]] = None
    keyword_aura: Optional[Callable[["CardInstance", "CardInstance", "GameState"], list[Keyword]]] = None
    # Magic-specific timing flags
    main_timing_ok: bool = True
    flash_timing_ok: bool = False
    # Reactive-keyword flash ability
    flash_ability: Optional[Callable[["CardInstance", "GameState", "Context"], None]] = None
    flash_ability_condition: Optional[Callable[["CardInstance", "GameState"], bool]] = None


@dataclass
class Context:
    """Carried alongside trigger callbacks; holds 'why' info."""
    controller: "Player"
    source: Optional[Any] = None    # may be CardInstance or ForceInstance
    target: Optional[Any] = None


@dataclass
class Action:
    """A move chosen by a policy and applied by the engine."""
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass
class AttackTarget:
    """An attack's chosen target."""
    kind: AttackTargetKind
    ref: Any   # Player | ForceInstance | CardInstance


import itertools
from zz.enums import AreaType, Phase, Step, Side


_id_counter = itertools.count(1)


@dataclass
class CardInstance:
    """A specific in-game copy of a Card."""
    card: Card
    owner: "Player"
    iid: int = field(default_factory=lambda: next(_id_counter))
    area: AreaType = AreaType.DECK
    bp_mod: int = 0
    dp_mod: int = 0
    permanent_bp_mod: int = 0
    permanent_dp_mod: int = 0
    extra_keywords: list[Keyword] = field(default_factory=list)
    rested: bool = False
    summoning_sickness: bool = True
    flags: set[str] = field(default_factory=set)
    # House-rule HR2 support
    mana_color_override: Optional[Color] = None

    def __deepcopy__(self, memo: dict[int, Any]) -> "CardInstance":
        import copy

        clone = self.__class__.__new__(self.__class__)
        memo[id(self)] = clone
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "card":
                setattr(clone, item.name, value)
            else:
                setattr(clone, item.name, copy.deepcopy(value, memo))
        return clone

    @property
    def bp(self) -> int:
        return max(0, self.card.bp + self.bp_mod + self.permanent_bp_mod)

    @property
    def dp(self) -> int:
        return max(0, self.card.dp + self.dp_mod + self.permanent_dp_mod)

    @property
    def keywords(self) -> list[Keyword]:
        return list(self.card.keywords) + list(self.extra_keywords)


@dataclass
class ForceInstance:
    """A specific in-game Force assigned to a player."""
    force: Any    # type: forces.Force (forward; defined in Task 19)
    owner: "Player"
    life: int
    destroyed: bool = False
    rested: bool = False

    def __deepcopy__(self, memo: dict[int, Any]) -> "ForceInstance":
        import copy

        clone = self.__class__.__new__(self.__class__)
        memo[id(self)] = clone
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "force":
                setattr(clone, item.name, value)
            else:
                setattr(clone, item.name, copy.deepcopy(value, memo))
        return clone


@dataclass
class Player:
    name: str
    side: Side                                 # which slot (P1 or P2)
    is_first_player: bool = False              # 先攻 = True
    life: int = 0                              # bare player life (when all forces are gone, taken from this)
    deck: list[CardInstance] = field(default_factory=list)
    hand: list[CardInstance] = field(default_factory=list)
    base: list[CardInstance] = field(default_factory=list)
    trash: list[CardInstance] = field(default_factory=list)
    removed: list[CardInstance] = field(default_factory=list)
    forces: list[ForceInstance] = field(default_factory=list)
    movement_right_count: int = 0
    movement_right_total: int = 0
    mulligan_done: bool = False
    profile: dict[str, Any] = field(default_factory=dict)
    # House-rule HR2 tracker
    colorless_only_streak: int = 0
    flags: set[str] = field(default_factory=set)
    # NOTE: `field` attr declared LAST to avoid shadowing dataclasses.field within the class body.
    field: list[CardInstance] = field(default_factory=list)


@dataclass
class GameState:
    players: list[Player]
    turn: int = 1
    active_idx: int = 0           # index into players
    phase: Phase = Phase.STANDBY
    step: Step = Step.START
    # Snapshot of card IIDs that were on field/base at turn START (for direct-player attack gating)
    present_at_turn_start: set[int] = field(default_factory=set)
    # F-Minion instances summoned during the current turn.
    summoned_this_turn: list[CardInstance] = field(default_factory=list)
    _next_iid: int = field(default=1, repr=False)

    @property
    def active(self) -> Player:
        return self.players[self.active_idx]

    @property
    def opponent(self) -> Player:
        return self.players[1 - self.active_idx]

    def allocate_iid(self) -> int:
        iid = self._next_iid
        self._next_iid += 1
        return iid

    @property
    def next_instance_id(self) -> int:
        return self._next_iid

    def clone(self) -> "GameState":
        import copy
        return copy.deepcopy(self)
