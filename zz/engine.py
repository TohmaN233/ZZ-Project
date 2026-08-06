from __future__ import annotations
import random
from typing import Optional, Callable, Iterable, Any

from zz.enums import AreaType, CardType, Color, Keyword, Phase, Side, Step, TriggerTiming
from zz import keyword_rules
from zz.effects import EffectTiming, EffectSpec, effect_once_per_turn_used
from zz.model import (Action, AttackTarget, Card, CardInstance, Context,
                       ForceInstance, GameState, Player)
from zz.triggers import TriggerRegistry


HAND_CAP = 10
BASE_CAP = 10
FIELD_CAP = 5
LIFE_CAP = 10
MAX_TURNS_SAFETY = 100


class IllegalActionError(Exception):
    """Raised when a requested game action is not legal in the current state."""


class GameOver(Exception):
    def __init__(self, winner: Optional[Player], reason: str):
        self.winner = winner
        self.reason = reason
        super().__init__(reason)


class _GrantedForceAbilitySource:
    """Force-passive adapter whose lifetime is tied to one field minion."""

    def __init__(self, source: CardInstance, force: Any):
        self.source = source
        self.force = force
        self.owner = source.owner

    @property
    def destroyed(self) -> bool:
        return self.source.area is not AreaType.FIELD or self.source not in self.owner.field

    @property
    def rested(self) -> bool:
        return False


class Engine:
    def __init__(self, state: GameState, rng: random.Random):
        self.state = state
        self.state.engine = self
        self.rng = rng
        self.triggers = TriggerRegistry(self)
        self._policies: list = [None, None]   # filled by set_policies
        # Passive modifiers: list of (kind, fn) registered by Forces
        self._passive_modifiers: list[tuple[str, Callable]] = []
        self.pending_force_base_choices: list[ForceInstance] = []
        self.public_reveals: list[tuple[Player, CardInstance, str]] = []
        self.visual_events: list[dict[str, Any]] = []
        self.effect_events: list[tuple[CardInstance, Any, Context | None]] = []
        self.destroy_events: list[CardInstance] = []
        self.zone_move_events: list[dict[str, Any]] = []
        self.ignore_hand_cap = False
        self.defer_force_base_choice: Callable[[Player], bool] = lambda player: False
        self.defer_blessing_base_choice: Callable[[Player], bool] = lambda player: False
        self.defer_trigger_choice: Callable[[Any], bool] | None = None
        self.defer_source_effect_choice: Callable[[CardInstance, Any, Context], bool] | None = None
        self.pending_blessing_returns: list[tuple[CardInstance, CardInstance]] = []
        self._player_damage_reduction: dict[int, int] = {}
        self._player_damage_reduction_blocked: set[int] = set()
        self._force_damage_reduction: dict[int, int] = {}
        self._force_damage_reduction_blocked: set[int] = set()
        self._player_healing_blocked: set[int] = set()
        self._force_healing_blocked: set[int] = set()
        self._effect_resolution_depth = 0
        self._pending_destroy_events: list[tuple[CardInstance, Context]] = []
        self._flushing_destroy_events = False
        self._resolving_state_based_actions = False
        self._delayed_turn_end_effects: list[tuple[Player, Callable[[], None]]] = []
        self._turn_stat_modifiers: list[dict[str, Any]] = []
        self.observed_action_profile_by_player_side: dict[str, dict[str, int]] = {}

    def __deepcopy__(self, memo: dict[int, Any]) -> "Engine":
        import copy

        clone = self.__class__.__new__(self.__class__)
        memo[id(self)] = clone
        for key, value in self.__dict__.items():
            setattr(clone, key, copy.deepcopy(value, memo))
        if hasattr(clone, "triggers") and hasattr(clone.triggers, "_engine"):
            clone.triggers._engine = clone
        return clone

    def clone_for_simulation(self) -> "Engine":
        import copy

        history_event_keys = {
            "public_reveals",
            "visual_events",
            "effect_events",
            "destroy_events",
            "zone_move_events",
        }
        clone = self.__class__.__new__(self.__class__)
        memo: dict[int, Any] = {id(self): clone}
        for key, value in self.__dict__.items():
            if key in history_event_keys:
                setattr(clone, key, [])
            else:
                setattr(clone, key, copy.deepcopy(value, memo))
        if hasattr(clone, "triggers") and hasattr(clone.triggers, "_engine"):
            clone.triggers._engine = clone
        return clone

    def _enter_effect_resolution(self) -> None:
        self._effect_resolution_depth += 1

    def _leave_effect_resolution(self) -> None:
        self._effect_resolution_depth = max(0, self._effect_resolution_depth - 1)
        if self._effect_resolution_depth == 0:
            if self.pending_blessing_returns:
                return
            self._resolve_state_based_actions()
            self._flush_pending_destroy_events()
            self._resolve_state_based_actions()

    def _resolve_triggers_if_idle(self) -> None:
        if self._effect_resolution_depth == 0:
            self.triggers.resolve_all()

    def _run_effect_callback(self, fn: Callable, *args) -> None:
        self._enter_effect_resolution()
        try:
            fn(*args)
        finally:
            self._leave_effect_resolution()

    def _run_pre_target_effect(self, effect: Any, source: CardInstance, ctx: Context) -> None:
        pre_target_fn = getattr(effect, "pre_target_fn", None)
        if pre_target_fn is None or getattr(ctx, "_pre_target_effect_applied", False):
            return
        pre_target_fn(source, self.state, ctx)
        setattr(ctx, "_pre_target_effect_applied", True)

    def _flush_pending_destroy_events(self) -> None:
        if self._flushing_destroy_events:
            return
        self._flushing_destroy_events = True
        try:
            while self._pending_destroy_events:
                pending = list(self._pending_destroy_events)
                self._pending_destroy_events.clear()
                for ci, ctx in pending:
                    self._resolve_destroy_event(ci, ctx)
        finally:
            self._flushing_destroy_events = False

    def set_policies(self, p1_policy, p2_policy) -> None:
        self._policies = [p1_policy, p2_policy]

    def policy_for(self, player: Player):
        return self._policies[self.state.players.index(player)]

    # ---- basic verbs --------------------------------------------------

    def _record_visual_event(self, event: dict[str, Any]) -> None:
        self.visual_events.append(event)

    def _record_phase_visual_event(self, phase: str, player: Player) -> None:
        self._record_visual_event({
            "type": "phase",
            "phase": phase,
            "side": player.side.name,
        })

    def _record_zone_move(self, ci: CardInstance, from_area: AreaType, to_area: AreaType) -> None:
        if from_area is to_area:
            return
        event = {
            "card": ci,
            "from": from_area,
            "to": to_area,
        }
        self.zone_move_events.append(event)
        self._record_visual_event({"type": "zone_move", **event})

    def add_to_hand(
            self,
            player: Player,
            ci: CardInstance,
            *,
            from_area: AreaType | None = None,
            record_event: bool = True,
    ) -> bool:
        source_area = from_area or ci.area
        if source_area is AreaType.TRASH and ci.card.id == "purple_04_02_01_00" and ci in player.trash:
            replace_iid = None
            if len(player.field) >= FIELD_CAP:
                replacements = self.select_target(player, "ally_minion", 1, 1, source=ci)
                if not replacements:
                    return False
                replace_iid = replacements[0].iid
            self.summon_from_trash(player, ci, replace_field_iid=replace_iid)
            return True
        if source_area is AreaType.TRASH and ci in player.trash:
            player.trash.remove(ci)
        if not self.ignore_hand_cap and len(player.hand) >= HAND_CAP:
            ci.area = AreaType.TRASH
            player.trash.append(ci)
            if record_event:
                self._record_zone_move(ci, source_area, AreaType.TRASH)
            return False
        ci.area = AreaType.HAND
        player.hand.append(ci)
        if record_event:
            self._record_zone_move(ci, source_area, AreaType.HAND)
        return True

    def draw(
            self,
            player: Player,
            n: int = 1,
            *,
            deck_out_loses: bool = False,
            record_event: bool = True,
    ) -> list[CardInstance]:
        drawn = []
        for _ in range(n):
            if not player.deck:
                if deck_out_loses:
                    winner = self.state.players[1 - self.state.players.index(player)]
                    raise GameOver(winner=winner, reason=f"{player.name} decked out")
                break
            ci = player.deck.pop(0)
            self.add_to_hand(player, ci, from_area=AreaType.DECK, record_event=record_event)
            drawn.append(ci)
        return drawn

    def heal(self, target_player: Player, amount: int) -> None:
        if id(target_player) in self._player_healing_blocked:
            return
        before = target_player.life
        target_player.life = min(target_player.life + amount, LIFE_CAP)
        healed = target_player.life - before
        if healed > 0:
            self._record_visual_event({
                "type": "heal",
                "targetKind": "player",
                "side": target_player.side.name,
                "amount": healed,
            })

    def heal_target(self, target, amount: int) -> None:
        if isinstance(target, Player):
            self.heal(target, amount)
        elif isinstance(target, ForceInstance):
            if id(target) in self._force_healing_blocked:
                return
            before = target.life
            target.life = min(target.life + amount, LIFE_CAP)
            healed = target.life - before
            if healed > 0:
                self._record_visual_event({
                    "type": "heal",
                    "targetKind": "force",
                    "side": target.owner.side.name,
                    "forceId": target.force.id,
                    "amount": healed,
                })

    def modify_stat(
            self,
            ci: CardInstance,
            bp_delta: int = 0,
            dp_delta: int = 0,
            *,
            duration: str = "turn",
    ) -> None:
        if duration == "permanent":
            ci.permanent_bp_mod += bp_delta
            ci.permanent_dp_mod += dp_delta
            if self._effect_resolution_depth == 0:
                self._resolve_state_based_actions()
            return
        ci.bp_mod += bp_delta
        ci.dp_mod += dp_delta
        if self._effect_resolution_depth == 0:
            self._resolve_state_based_actions()

    def add_turn_stat_modifier(
            self,
            controller: Player,
            *,
            target_kind: str,
            bp_delta: int = 0,
            dp_delta: int = 0,
            max_cost: int | None = None,
            min_cost: int | None = None,
            max_bp: int | None = None,
            max_dp: int | None = None,
            color: Color | str | None = None,
            source: CardInstance | None = None,
    ) -> None:
        try:
            controller_idx = self.state.players.index(controller)
        except ValueError:
            return
        self._turn_stat_modifiers.append({
            "controller_idx": controller_idx,
            "target_kind": target_kind,
            "bp_delta": bp_delta,
            "dp_delta": dp_delta,
            "max_cost": max_cost,
            "min_cost": min_cost,
            "max_bp": max_bp,
            "max_dp": max_dp,
            "color": self._color_value(color),
            "source_card_id": None if source is None else source.card.id,
            "source_name": "Turn stat modifier" if source is None else source.card.name_jp,
        })
        if self._effect_resolution_depth == 0:
            self._resolve_state_based_actions()

    def _reset_card_modifiers(self, ci: CardInstance) -> None:
        self._remove_granted_force_ability(ci)
        ci.bp_mod = 0
        ci.dp_mod = 0
        ci.permanent_bp_mod = 0
        ci.permanent_dp_mod = 0
        ci.extra_keywords = []
        ci.flags.clear()
        ci.mana_color_override = None

    def _reset_card_zone_state(self, ci: CardInstance) -> None:
        self._reset_card_modifiers(ci)
        ci.rested = False
        ci.summoning_sickness = True

    def add_keyword(self, ci: CardInstance, kw: Keyword) -> None:
        if kw not in ci.extra_keywords:
            ci.extra_keywords.append(kw)

    def effective_keywords(self, ci: CardInstance) -> list[Keyword]:
        keywords = list(ci.keywords)
        if ci.area is AreaType.FIELD and ci.blessings:
            from zz.pc02 import blessing_keywords

            for keyword in blessing_keywords(ci):
                if keyword not in keywords:
                    keywords.append(keyword)
        if ci.area is AreaType.FIELD:
            for player in self.state.players:
                for source in player.field:
                    if source.area is not AreaType.FIELD:
                        continue
                    keyword_aura = source.card.keyword_aura
                    if keyword_aura is None:
                        continue
                    for keyword in keyword_aura(source, ci, self.state):
                        if keyword not in keywords:
                            keywords.append(keyword)
        return keywords

    def has_keyword(self, ci: CardInstance, kw: Keyword) -> bool:
        return kw in self.effective_keywords(ci)

    def _force_for_passive(self, fn: Callable) -> ForceInstance | None:
        force_iid = getattr(fn, "_force_iid", None)
        if force_iid is None:
            return None
        for player in self.state.players:
            for force in player.forces:
                if id(force) == force_iid:
                    return force
        return None

    def card_active_effects(self, ci: CardInstance) -> list[dict[str, Any]]:
        effects: list[dict[str, Any]] = []
        if ci.bp_mod or ci.dp_mod:
            effects.append({
                "kind": "turn_stat_modifier",
                "sourceName": "Turn stat modifier",
                "bpDelta": ci.bp_mod,
                "dpDelta": ci.dp_mod,
            })
        if ci.permanent_bp_mod or ci.permanent_dp_mod:
            effects.append({
                "kind": "permanent_stat_modifier",
                "sourceName": "Permanent stat modifier",
                "bpDelta": ci.permanent_bp_mod,
                "dpDelta": ci.permanent_dp_mod,
            })
        if ci.extra_keywords:
            effects.append({
                "kind": "keyword_modifier",
                "sourceName": "Keyword modifier",
                "keywords": [kw.name for kw in ci.extra_keywords],
            })
        visible_flags = {
            "pc01r:locked_until_owner_turn_end": ("action_lock", "Attack, block, and movement lock"),
            "turn:pc01r_opponent_magic_immune": ("magic_selection_immunity", "Opponent Magic selection immunity"),
            "turn:pc01r_always_wins_battle": ("battle_auto_win", "Wins battle regardless of BP"),
            "turn:pc02_always_wins_battle": ("battle_auto_win", "Wins battle regardless of BP"),
            "turn:pc02_cannot_attack": ("cannot_attack", "Cannot attack this turn"),
            "turn:must_block": ("must_block", "Must block this turn"),
            "must_be_blocked": ("must_be_blocked", "Must be blocked when attacking"),
            "unblockable_by_cost_at_most_3": ("unblockable_by_cost_at_most_3", "Cannot be blocked by cost 3 or less"),
        }
        for flag, (kind, source_name) in visible_flags.items():
            if flag in ci.flags:
                effects.append({"kind": kind, "sourceName": source_name})
        if any(flag.startswith("force_block_iid:") for flag in ci.flags):
            effects.append({"kind": "forced_blocker"})
        if self._skip_refresh_flag(ci.owner.side) in ci.flags:
            effects.append({"kind": "skip_next_refresh"})
        if ci.area is not AreaType.FIELD:
            return effects
        for kind, fn in self._passive_modifiers:
            if kind != "force_passive":
                continue
            bp_delta, dp_delta = fn(ci, self.state)
            if not bp_delta and not dp_delta:
                continue
            force = self._force_for_passive(fn)
            effects.append({
                "kind": "force_passive",
                "sourceType": "force",
                "sourceForceId": None if force is None else force.force.id,
                "sourceName": "Force passive" if force is None else force.force.name_jp,
                "bpDelta": bp_delta,
                "dpDelta": dp_delta,
            })
        for modifier in self._turn_stat_modifiers:
            if not self._turn_stat_modifier_matches(ci, modifier):
                continue
            bp_delta = int(modifier.get("bp_delta") or 0)
            dp_delta = int(modifier.get("dp_delta") or 0)
            if not bp_delta and not dp_delta:
                continue
            effects.append({
                "kind": "turn_stat_aura",
                "sourceType": "card",
                "sourceCardId": modifier.get("source_card_id"),
                "sourceName": modifier.get("source_name") or "Turn stat modifier",
                "bpDelta": bp_delta,
                "dpDelta": dp_delta,
            })
        base_keywords = list(ci.card.keywords)
        for player in self.state.players:
            for source in player.field:
                if source.area is not AreaType.FIELD:
                    continue
                if source.card.aura is not None:
                    bp_delta, dp_delta = source.card.aura(source, ci, self.state)
                    if bp_delta or dp_delta:
                        effects.append({
                            "kind": "card_aura",
                            "sourceType": "card",
                            "sourceCardId": source.card.id,
                            "sourceCardIid": source.iid,
                            "sourceName": source.card.name_jp,
                            "bpDelta": bp_delta,
                            "dpDelta": dp_delta,
                        })
                if source.card.keyword_aura is None:
                    continue
                keywords = [
                    kw
                    for kw in source.card.keyword_aura(source, ci, self.state)
                    if kw not in base_keywords and kw not in ci.extra_keywords
                ]
                if keywords:
                    effects.append({
                        "kind": "keyword_aura",
                        "sourceType": "card",
                        "sourceCardId": source.card.id,
                        "sourceCardIid": source.iid,
                        "sourceName": source.card.name_jp,
                        "keywords": [kw.name for kw in keywords],
                    })
                    base_keywords.extend(keywords)
        return effects

    def reveal_card(self, player: Player, ci: CardInstance, reason: str) -> None:
        self.public_reveals.append((player, ci, reason))

    def reveal_top_cards(
            self,
            player: Player,
            cards: Iterable[CardInstance],
            *,
            reason: str | None = None,
            window_size: int | None = None,
    ) -> None:
        """Publish one complete opponent-visible top-deck open window."""
        window = list(cards)
        if reason is None:
            reason = "top_four" if (window_size or len(window)) == 4 else "top_cards"
        for card in window:
            self.reveal_card(player, card, reason)

    def _record_effect_event(self, ci: CardInstance, effect: Any, ctx: Context | None = None) -> None:
        timing = getattr(effect, "timing", getattr(effect, "when", None))
        if timing is EffectTiming.CONTINUOUS:
            return
        event = (ci, effect, ctx)
        self.effect_events.append(event)
        self._record_visual_event({
            "type": "effect",
            "card": ci,
            "effect": effect,
            "ctx": ctx,
        })

    def prevent_player_damage(self, player: Player, amount: int) -> None:
        key = id(player)
        self._player_damage_reduction[key] = max(self._player_damage_reduction.get(key, 0), amount)

    def prevent_force_damage(self, player: Player, amount: int) -> None:
        for force in player.forces:
            key = id(force)
            self._force_damage_reduction[key] = max(self._force_damage_reduction.get(key, 0), amount)

    def _yakutzork_player_damage_reduction(self, player: Player) -> int:
        if self.state.active is player:
            return 0
        return 1 if any(
            ci.card.id == "green_09_02_01_00" and ci.area is AreaType.FIELD
            for ci in player.field
        ) else 0

    def player_active_effects(self, player: Player) -> list[dict[str, Any]]:
        effects: list[dict[str, Any]] = []
        if id(player) in self._player_damage_reduction_blocked:
            effects.append({
                "kind": "damage_reduction_blocked",
                "target": "player",
                "sourceName": "Damage reduction blocked",
            })
        visible_flags = {
            "turn:pc01r_next_red_summon_rush": "next_red_minion_rush",
            "turn:pc01r_opponent_magic_plus3": "opponent_magic_cost_increase",
            "turn:pc01r_battle_win_damage": "battle_win_damage",
            "hunter_must_be_blocked": "hunter_must_be_blocked",
            "turn:pc02_return_damager": "return_enemy_damager",
            "turn:pc02_next_blue_magic_free": "next_blue_magic_free",
            "turn:pc02_draw_enemy_destroy": "draw_on_enemy_destroy",
        }
        for flag, kind in visible_flags.items():
            if flag in player.flags:
                effects.append({"kind": kind, "target": "player"})
        if id(player) in self._player_damage_reduction_blocked:
            return effects
        temporary = self._player_damage_reduction.get(id(player), 0)
        if temporary:
            effects.append({
                "kind": "prevent_player_damage",
                "target": "player",
                "sourceName": "Player damage prevention",
                "amount": temporary,
            })
        for source in player.field:
            if source.card.id != "green_09_02_01_00" or self.state.active is player:
                continue
            effects.append({
                "kind": "player_damage_reduction",
                "target": "player",
                "sourceType": "card",
                "sourceCardId": source.card.id,
                "sourceCardIid": source.iid,
                "sourceName": source.card.name_jp,
                "amount": 1,
                "scope": "opponent_turn",
            })
        for kind, fn in self._passive_modifiers:
            if kind != "player_dmg_reduce_from_minion":
                continue
            before = 99
            after = fn(before, "minion_dp", player, None)
            amount = max(0, before - after)
            if not amount:
                continue
            force = self._force_for_passive(fn)
            effects.append({
                "kind": "player_damage_reduction",
                "target": "player",
                "sourceType": "force",
                "sourceForceId": None if force is None else force.force.id,
                "sourceName": "Force passive" if force is None else force.force.name_jp,
                "amount": amount,
                "scope": "enemy_minion_dp",
            })
        return effects

    def force_active_effects(self, force: ForceInstance) -> list[dict[str, Any]]:
        effects: list[dict[str, Any]] = []
        if self._skip_refresh_flag(force.owner.side) in getattr(force, "flags", set()):
            effects.append({"kind": "skip_next_refresh", "target": "force"})
        if id(force) in self._force_damage_reduction_blocked:
            effects.append({
                "kind": "damage_reduction_blocked",
                "target": "force",
                "sourceName": "Damage reduction blocked",
            })
            return effects
        amount = self._force_damage_reduction.get(id(force), 0)
        if not amount:
            return effects
        effects.append({
            "kind": "prevent_force_damage",
            "target": "force",
            "sourceName": "Force damage prevention",
            "amount": amount,
        })
        return effects

    def block_life_gain_and_damage_reduction(self, player: Player) -> None:
        self._player_damage_reduction_blocked.add(id(player))
        self._player_healing_blocked.add(id(player))
        for force in player.forces:
            self._force_damage_reduction_blocked.add(id(force))
            self._force_healing_blocked.add(id(force))

    def _resolve_state_based_actions(self) -> None:
        if self._resolving_state_based_actions:
            return
        self._resolving_state_based_actions = True
        try:
            while True:
                doomed = [
                    ci
                    for player in self.state.players
                    for ci in list(player.field)
                    if ci.area is AreaType.FIELD and self.effective_bp(ci) <= 0
                ]
                if not doomed:
                    break
                self._effect_resolution_depth += 1
                try:
                    for ci in doomed:
                        self._destroy(ci, source=None)
                finally:
                    self._effect_resolution_depth = max(0, self._effect_resolution_depth - 1)
                self._flush_pending_destroy_events()
                self.triggers.resolve_all()
        finally:
            self._resolving_state_based_actions = False

    # ---- phase machine ------------------------------------------------

    def _set_step(self, step: Step) -> None:
        self.state.step = step
        if step in (Step.START, Step.REFRESH, Step.DRAW):
            self.state.phase = Phase.STANDBY
        elif step is Step.MANA:
            self.state.phase = Phase.MANA
        elif step is Step.MAIN:
            self.state.phase = Phase.MAIN
        elif step is Step.END:
            self.state.phase = Phase.END
        # FLASH stays in MAIN phase (it's a sub-state)

    def begin_turn(self) -> None:
        """STANDBY (Start→Refresh→Draw) → MANA. Leaves engine at Step.MANA awaiting decision."""
        active = self.state.active
        # START
        self._set_step(Step.START)
        self._record_visual_event({
            "type": "turn_begin",
            "side": active.side.name,
            "turn": self.state.turn,
        })
        self.state.summoned_this_turn.clear()
        active.flags.clear()
        active.movement_right_count = 0
        active.movement_right_total = 0
        # Snapshot present-at-turn-start IIDs (for direct-player-attack gating)
        self.state.present_at_turn_start = set()
        for ci in active.field + active.base:
            self.state.present_at_turn_start.add(ci.iid)
        # Movement right grant (except first-player turn 1)
        if not (self.state.turn == 1 and active.is_first_player):
            self.grant_movement_right(active, 1)
        self._fire_turn_start_hooks()
        self.triggers.emit(EffectTiming.TURN_START, Context(controller=active))
        self.triggers.emit(TriggerTiming.TURN_START, Context(controller=active))
        self.triggers.resolve_all()
        # REFRESH — untap own field/base/forces; clear summoning sickness
        self._set_step(Step.REFRESH)
        for ci in active.field + active.base:
            self._refresh_rest_state(active, ci)
            ci.summoning_sickness = False
        for f in active.forces:
            self._refresh_rest_state(active, f)
        # DRAW — first-player turn 1 skips
        self._set_step(Step.DRAW)
        if not (self.state.turn == 1 and active.is_first_player):
            self.draw(active, 1, deck_out_loses=True)
        # MANA step (await decision)
        self._set_step(Step.MANA)
        self._record_phase_visual_event("mana", active)

    def advance_from_mana(self) -> None:
        """After mana action (or skip), enter MAIN."""
        self._set_step(Step.MAIN)
        self._record_phase_visual_event("main", self.state.active)

    def end_turn(self) -> None:
        active = self.state.active
        self._set_step(Step.END)
        self.triggers.emit(EffectTiming.TURN_END, Context(controller=active))
        self.triggers.emit(TriggerTiming.TURN_END, Context(controller=active))
        self.triggers.resolve_all()
        self._fire_turn_end_hooks()
        from zz.pc01r import clear_owner_turn_end_locks
        from zz.pc02 import clear_turn_state

        clear_owner_turn_end_locks(active)
        clear_turn_state(self.state)
        for ci in active.field:
            if ci.owner is active and ci.area is AreaType.FIELD and self.has_keyword(ci, Keyword.REAWAKEN):
                ci.rested = False
        # Update HR2 streak: did active's base contain ANY colored mana this turn?
        has_colored = any(
            self._mana_color_of(ci) != Color.COLORLESS
            for ci in active.base
        )
        if has_colored:
            active.colorless_only_streak = 0
        else:
            active.colorless_only_streak += 1
        # Drop turn-scoped buffs
        for player in self.state.players:
            for zone in (player.field, player.base, player.hand, player.trash, player.removed):
                for ci in zone:
                    ci.bp_mod = 0
                    ci.dp_mod = 0
                    ci.extra_keywords = []
                    ci.flags = {
                        flag for flag in ci.flags
                        if not flag.startswith("turn:")
                    }
        self._player_damage_reduction.clear()
        self._player_damage_reduction_blocked.clear()
        self._force_damage_reduction.clear()
        self._force_damage_reduction_blocked.clear()
        self._player_healing_blocked.clear()
        self._force_healing_blocked.clear()
        self._turn_stat_modifiers.clear()
        # Unused movement right is lost
        active.movement_right_count = 0
        active.movement_right_total = 0
        # Pass to next player
        self.state.active_idx = 1 - self.state.active_idx
        if self.state.active_idx == 0:
            self.state.turn += 1
        # Safety stop
        if self.state.turn > MAX_TURNS_SAFETY:
            raise GameOver(winner=None, reason=f"reached MAX_TURNS_SAFETY={MAX_TURNS_SAFETY}")
        self.begin_turn()

    def _mana_color_of(self, ci: CardInstance) -> Color:
        """Color this base card produces. Mana-token is colorless. HR2 override consulted."""
        if ci.mana_color_override is not None:
            return ci.mana_color_override
        if ci.card.type is CardType.MANA_TOKEN:
            return Color.COLORLESS
        if ci.card.mana_color is not None:
            return ci.card.mana_color
        # primary color = first non-colorless in cost
        for c in ci.card.cost:
            if c is not Color.COLORLESS:
                return c
        return Color.COLORLESS

    def grant_movement_right(self, player: Player, amount: int = 1) -> None:
        if amount <= 0:
            return
        player.movement_right_count += amount
        player.movement_right_total += amount

    # ---- match setup --------------------------------------------------

    def deal_opening_hand(self, player: Player) -> None:
        """Opening hand is 6 cards for both players."""
        for _ in range(6):
            self.draw(player, 1, record_event=False)

    def _mulligan_selection(self, player: Player, redraw) -> list[CardInstance]:
        if redraw is True:
            return list(player.hand)
        if redraw in (False, None):
            return []
        try:
            requested = {
                item.iid if isinstance(item, CardInstance) else int(item)
                for item in redraw
            }
        except (TypeError, ValueError) as exc:
            raise IllegalActionError("invalid mulligan selection") from exc
        hand_ids = {ci.iid for ci in player.hand}
        missing = requested - hand_ids
        if missing:
            raise IllegalActionError("mulligan selection must be cards in hand")
        return [ci for ci in player.hand if ci.iid in requested]

    def mulligan(self, player: Player, redraw=False, *, do_it: bool | None = None,
                 redraw_iids: Iterable[int] | None = None) -> None:
        """One mulligan: bottom selected hand cards, draw that many, then shuffle."""
        if do_it is not None:
            redraw = do_it
        if redraw_iids is not None:
            redraw = redraw_iids
        if player.mulligan_done:
            raise IllegalActionError("mulligan already done")
        selected = self._mulligan_selection(player, redraw)
        player.mulligan_done = True
        if not selected:
            return
        selected_ids = {ci.iid for ci in selected}
        player.hand = [ci for ci in player.hand if ci.iid not in selected_ids]
        for ci in selected:
            ci.area = AreaType.DECK
            player.deck.append(ci)
        for _ in range(len(selected)):
            self.draw(player, 1)
        self.rng.shuffle(player.deck)

    # ---- mana payment -------------------------------------------------

    def _remove_token_from_game(self, ci: CardInstance) -> None:
        owner = ci.owner
        # Tokens can also be Bless hosts.  Removing one from the field is a
        # leave-field event, regardless of whether the destination is trash,
        # base, or removed, so detach its Bless mana before clearing the zone.
        if ci.area is AreaType.FIELD:
            self._return_blessings_to_base(ci)
        for zone in (owner.field, owner.base, owner.hand, owner.trash):
            if ci in zone:
                zone.remove(ci)
        self._reset_card_zone_state(ci)
        ci.area = AreaType.REMOVED
        if ci not in owner.removed:
            owner.removed.append(ci)

    def _eject_base_card(
            self,
            player: Player,
            ci: CardInstance,
            *,
            reason: str = "destroy",
    ) -> None:
        if ci not in player.base:
            raise IllegalActionError("replacement card not in base")
        player.base.remove(ci)
        if ci.card.type is CardType.MANA_TOKEN or ci.card.is_token:
            ci.area = AreaType.REMOVED
            player.removed.append(ci)
        else:
            self._reset_card_zone_state(ci)
            ci.area = AreaType.TRASH
            player.trash.append(ci)
        from zz.pc02 import on_base_mana_removed

        on_base_mana_removed(self, player, ci, reason=reason)

    def _eject_field_card(self, player: Player, ci: CardInstance) -> None:
        if ci not in player.field:
            raise IllegalActionError("replacement card not in field")
        if ci.card.is_token:
            self._remove_token_from_game(ci)
            return
        player.field.remove(ci)
        self._return_blessings_to_base(ci)
        self._reset_card_zone_state(ci)
        ci.area = AreaType.TRASH
        player.trash.append(ci)

    def _make_base_space(
            self,
            player: Player,
            replace_base_iid: int | None,
            *,
            slots_needed: int = 1,
    ) -> None:
        if slots_needed < 1:
            raise IllegalActionError("base space request must need at least one slot")
        overflow = max(0, len(player.base) + slots_needed - BASE_CAP)
        if overflow == 0:
            if replace_base_iid is not None:
                raise IllegalActionError("base replacement is only legal when base is full")
            return
        if replace_base_iid is None:
            raise IllegalActionError(f"base cap {BASE_CAP} reached; choose a replacement")
        self._eject_base_card(
            player,
            self._find(player.base, replace_base_iid),
            reason="replacement",
        )

    def _field_replacement(self, player: Player, replace_field_iid: int | None) -> CardInstance | None:
        if len(player.field) < FIELD_CAP:
            if replace_field_iid is not None:
                raise IllegalActionError("field replacement is only legal when field is full")
            return None
        if replace_field_iid is None:
            raise IllegalActionError(f"field cap {FIELD_CAP} reached; choose a replacement")
        return self._find(player.field, replace_field_iid)

    def _make_field_space(self, player: Player, replace_field_iid: int | None) -> None:
        replacement = self._field_replacement(player, replace_field_iid)
        if replacement is not None:
            self._eject_field_card(player, replacement)

    def play_to_base(self, ci: CardInstance, replace_base_iid: int | None = None) -> None:
        """B-Minion only. Move from hand to base. Mana phase only."""
        active = self.state.active
        if self.state.step is not Step.MANA:
            raise IllegalActionError("play_to_base only legal in MANA step")
        if ci.card.type is not CardType.B_MINION:
            raise IllegalActionError("only B-Minion can be placed to base")
        if ci not in active.hand:
            raise IllegalActionError("card not in active player's hand")
        self._make_base_space(active, replace_base_iid)
        active.hand.remove(ci)
        ci.area = AreaType.BASE
        ci.rested = False
        active.base.append(ci)
        self._record_zone_move(ci, AreaType.HAND, AreaType.BASE)
        active.flags.add(f"turn:placed_mana:{self._mana_color_of(ci).name}")
        self.triggers.emit(EffectTiming.ON_PLACE_BASE, Context(controller=active, source=ci))
        self.triggers.resolve_all()
        self.advance_from_mana()

    def place_colorless_mana(self, replace_base_iid: int | None = None) -> None:
        """無色マナの配置: place 1 colorless mana token to base."""
        active = self.state.active
        if self.state.step is not Step.MANA:
            raise IllegalActionError("place_colorless_mana only legal in MANA step")
        self._make_base_space(active, replace_base_iid)
        token_card = Card(id="mana_token", name_jp="無色マナ", name_en="Colorless Mana",
                          type=CardType.MANA_TOKEN, cost={})
        token = CardInstance(
            card=token_card,
            owner=active,
            iid=self.state.allocate_iid(),
            area=AreaType.BASE,
        )
        active.base.append(token)
        active.flags.add(f"turn:placed_mana:{Color.COLORLESS.name}")
        self.advance_from_mana()

    def _mana_value(self, ci: CardInstance, ci_being_paid_for: CardInstance | None = None) -> int:
        from zz.pc01r import mana_value
        from zz.pc02 import mana_value as pc02_mana_value

        return pc02_mana_value(ci, ci_being_paid_for, mana_value(ci, ci_being_paid_for))

    def _available_mana(
            self,
            player: Player,
            ci_being_paid_for: CardInstance | None = None,
    ) -> dict[Color, int]:
        """Color counts of unrested base cards."""
        pool: dict[Color, int] = {}
        for ci in player.base:
            if ci.rested:
                continue
            c = self._mana_color_of(ci)
            pool[c] = pool.get(c, 0) + self._mana_value(ci, ci_being_paid_for)
        return pool

    def _is_colorless_mana_token(self, ci: CardInstance) -> bool:
        return ci.card.type is CardType.MANA_TOKEN and self._mana_color_of(ci) is Color.COLORLESS

    def _ready_colorless_mana_token_count(self, player: Player) -> int:
        return sum(1 for ci in self._ready_base_cards(player) if self._is_colorless_mana_token(ci))

    def _colorless_counts_as_any_mana(
            self,
            player: Player,
            ci_being_paid_for: CardInstance | None,
    ) -> bool:
        if ci_being_paid_for is None:
            return False
        return any(
            fn(player, ci_being_paid_for)
            for kind, fn in self._passive_modifiers
            if kind == "chimera_colorless_anycolor"
        )

    def _consume_cost_from_pool(
            self,
            pool: dict[Color, int],
            cost: dict[Color, int],
            *,
            colorless_as_any: bool = False,
            colorless_as_any_available: int = 0,
    ) -> dict[Color, int] | None:
        pool = dict(pool)
        for color, n in cost.items():
            if color is Color.COLORLESS:
                continue
            paid = min(pool.get(color, 0), n)
            pool[color] = pool.get(color, 0) - paid
            missing = n - paid
            if missing:
                if not colorless_as_any:
                    return None
                paid_colorless = min(pool.get(Color.COLORLESS, 0), colorless_as_any_available, missing)
                pool[Color.COLORLESS] = pool.get(Color.COLORLESS, 0) - paid_colorless
                colorless_as_any_available -= paid_colorless
                missing -= paid_colorless
                if missing:
                    return None
        if sum(pool.values()) < cost.get(Color.COLORLESS, 0):
            return None
        return pool

    def _can_pay(
            self,
            player: Player,
            cost: dict[Color, int],
            ci_being_paid_for: CardInstance | None = None,
    ) -> bool:
        return self._consume_cost_from_pool(
            self._available_mana(player, ci_being_paid_for),
            cost,
            colorless_as_any=self._colorless_counts_as_any_mana(player, ci_being_paid_for),
            colorless_as_any_available=self._ready_colorless_mana_token_count(player),
        ) is not None

    def effective_cost(self, player: Player, ci: CardInstance) -> dict[Color, int]:
        cost = dict(ci.card.cost)
        if not cost:
            return {}
        if ci.card.id == "colorless_04_02_01_04" and "cast_cost_4_magic_this_turn" in player.flags:
            return {}
        if (
            ci.card.id == "blue_04_02_01_00"
            and self.state.active is player
            and ci.area is AreaType.HAND
            and "cast_blue_magic_this_turn" in player.flags
        ):
            self._reduce_free_cost(cost, cost.get(Color.COLORLESS, 0))
        if ci.card.id == "colorless_08_02_01_02":
            reduction = sum(len(owner.field) for owner in self.state.players)
            self._reduce_free_cost(cost, reduction)
        if ci.card.id == "colorless_012_02_01_00" and self.state.active is player:
            self._reduce_free_cost(cost, self._destroyed_forces_count() * 3)
        if ci.card.id in {"colorless_05_02_ex01_02", "colorless_08_02_ex01_00"}:
            from zz.ex01 import memoria_free_cost_reduction, twin_free_cost_reduction

            self._reduce_free_cost(cost, twin_free_cost_reduction(player, ci, self.state))
            self._reduce_free_cost(cost, memoria_free_cost_reduction(player, ci, self.state))
        if (
            ci.card.id == "yellow_04_02_01_01"
            and self.state.active is player
            and ci.area is AreaType.HAND
            and "summoned_cost_5_minion_this_turn" in player.flags
        ):
            self._reduce_free_cost(cost, cost.get(Color.COLORLESS, 0))
        for source in self.state.players[1 - self.state.players.index(player)].field:
            if source.card.id == "purple_08_02_01_00" and ci.card.type is CardType.F_MINION:
                cost[Color.COLORLESS] = cost.get(Color.COLORLESS, 0) + 1
            if (
                source.card.id == "colorless_06_02_01_03"
                and ci.area is AreaType.HAND
                and ci.card.type is CardType.F_MINION
                and not self._card_is_colored(ci.card)
            ):
                cost[Color.COLORLESS] = cost.get(Color.COLORLESS, 0) + 1
        for source in player.field:
            if source.card.id == "colorless_06_02_01_03" and self._card_is_colored(ci.card):
                self._reduce_free_cost(cost, self._destroyed_forces_count())
            if source.card.id == "yellow_05_02_00_00" and ci.card.type in (CardType.F_MINION, CardType.B_MINION):
                self._reduce_free_cost(cost, 1)
        for kind, fn in self._passive_modifiers:
            if kind == "magic_cost_reduce":
                cost = fn(ci, cost)
        from zz.pc01r import free_cost_delta
        from zz.pc02 import adjust_effective_cost

        pc01r_delta = free_cost_delta(player, ci, self.state)
        if pc01r_delta < 0:
            self._reduce_free_cost(cost, -pc01r_delta)
        elif pc01r_delta > 0:
            cost[Color.COLORLESS] = cost.get(Color.COLORLESS, 0) + pc01r_delta
        cost = {color: amount for color, amount in cost.items() if amount > 0}
        return adjust_effective_cost(player, ci, self.state, cost)

    def _card_is_colored(self, card: Card) -> bool:
        return any(color is not Color.COLORLESS for color in card.cost) or card.mana_color not in (None, Color.COLORLESS)

    def _destroyed_forces_count(self) -> int:
        return sum(1 for player in self.state.players for force in player.forces if force.destroyed)

    def _reduce_free_cost(self, cost: dict[Color, int], amount: int) -> None:
        if amount <= 0:
            return
        if Color.COLORLESS in cost:
            cost[Color.COLORLESS] = max(0, cost[Color.COLORLESS] - amount)

    def _ready_base_cards(self, player: Player) -> list[CardInstance]:
        return [ci for ci in player.base if not ci.rested]

    def _payment_total(self, cost: dict[Color, int]) -> int:
        return sum(cost.values())

    def _validate_payment_selection(
            self,
            player: Player,
            cost: dict[Color, int],
            payment_base_iids: Iterable[int],
            ci_being_paid_for: CardInstance | None = None,
    ) -> list[CardInstance]:
        try:
            selected_ids = [int(iid) for iid in payment_base_iids]
        except (TypeError, ValueError) as exc:
            raise IllegalActionError("selected mana payment is invalid") from exc
        if len(selected_ids) != len(set(selected_ids)):
            raise IllegalActionError("selected mana payment has duplicates")
        ready_by_iid = {ci.iid: ci for ci in self._ready_base_cards(player)}
        try:
            selected = [ready_by_iid[iid] for iid in selected_ids]
        except KeyError as exc:
            raise IllegalActionError("selected mana must be ready base cards") from exc
        selected_colors: dict[Color, int] = {}
        for ci in selected:
            color = self._mana_color_of(ci)
            selected_colors[color] = selected_colors.get(color, 0) + self._mana_value(ci, ci_being_paid_for)
        selected_colorless_tokens = sum(1 for ci in selected if self._is_colorless_mana_token(ci))
        if self._consume_cost_from_pool(
            selected_colors,
            cost,
            colorless_as_any=self._colorless_counts_as_any_mana(player, ci_being_paid_for),
            colorless_as_any_available=selected_colorless_tokens,
        ) is None:
            raise IllegalActionError("selected mana does not satisfy colored cost")
        return selected

    def _default_payment_iids(
            self,
            player: Player,
            cost: dict[Color, int],
            ci_being_paid_for: CardInstance | None = None,
    ) -> list[int]:
        selected: list[CardInstance] = []
        colorless_as_any = self._colorless_counts_as_any_mana(player, ci_being_paid_for)

        def unused_ready() -> list[CardInstance]:
            selected_iids = {ci.iid for ci in selected}
            return [ci for ci in self._ready_base_cards(player) if ci.iid not in selected_iids]

        colored_surplus = 0
        for color, amount in cost.items():
            if color is Color.COLORLESS:
                continue
            paid = 0
            while paid < amount:
                match = next(
                    (ci for ci in unused_ready() if self._mana_color_of(ci) is color),
                    None,
                )
                if match is None and colorless_as_any:
                    match = next(
                        (ci for ci in unused_ready() if self._is_colorless_mana_token(ci)),
                        None,
                    )
                if match is None:
                    raise IllegalActionError(f"cannot pay cost {cost}")
                selected.append(match)
                paid += self._mana_value(match, ci_being_paid_for)
            colored_surplus += max(0, paid - amount)

        free_paid = 0
        free_needed = max(0, cost.get(Color.COLORLESS, 0) - colored_surplus)
        while free_paid < free_needed:
            match = next(
                (ci for ci in unused_ready() if self._mana_color_of(ci) is Color.COLORLESS),
                None,
            )
            if match is None:
                match = next(iter(unused_ready()), None)
            if match is None:
                raise IllegalActionError(f"cannot pay cost {cost}")
            selected.append(match)
            free_paid += self._mana_value(match, ci_being_paid_for)
        return [ci.iid for ci in selected]

    def _record_summon(self, ci: CardInstance) -> None:
        if ci.card.type is CardType.F_MINION and ci not in self.state.summoned_this_turn:
            self.state.summoned_this_turn.append(ci)
        if ci.owner is self.state.active and ci.card.type in (CardType.F_MINION, CardType.B_MINION):
            if sum(ci.card.cost.values()) >= 5:
                ci.owner.flags.add("summoned_cost_5_minion_this_turn")

    def _emit_enter_field(self, player: Player, ci: CardInstance) -> None:
        if ci.area is AreaType.FIELD and ci.card.type in (CardType.B_MINION, CardType.F_MINION):
            self.triggers.emit(EffectTiming.ON_ENTER_FIELD, Context(controller=player, source=ci))

    def payment_plan(
            self,
            player: Player,
            cost: dict[Color, int],
            ci_being_paid_for: CardInstance | None = None,
    ) -> dict:
        default = self._default_payment_iids(player, cost, ci_being_paid_for)
        colorless_as_any = self._colorless_counts_as_any_mana(player, ci_being_paid_for)
        return {
            "default": default,
            "colorlessAsAny": colorless_as_any,
            "candidates": [
                {
                    "iid": ci.iid,
                    "color": self._mana_color_of(ci).name,
                    "manaValue": self._mana_value(ci, ci_being_paid_for),
                }
                for ci in self._ready_base_cards(player)
            ],
        }

    def _pay(self, player: Player, cost: dict[Color, int],
             payment_base_iids: Iterable[int] | None = None,
             ci_being_paid_for: CardInstance | None = None) -> None:
        if payment_base_iids is not None:
            selected = self._validate_payment_selection(player, cost, payment_base_iids, ci_being_paid_for)
            for ci in selected:
                ci.rested = True
            return
        # Pay colored first (rest matching-color base cards), then free (rest any unrested)
        default_iids = self._default_payment_iids(player, cost, ci_being_paid_for)
        for ci in player.base:
            if ci.iid in default_iids:
                ci.rested = True

    # ---- card play -----------------------------------------------------

    def play_card(self, ci: CardInstance,
                  payment_base_iids: Iterable[int] | None = None,
                  replace_field_iid: int | None = None,
                  resolve_triggers: bool = True,
                  resolve_source_effects: bool = True) -> None:
        """Play F-Minion (summon) or Magic from hand."""
        active = self.state.active
        if self.state.step is not Step.MAIN:
            raise IllegalActionError("play_card only legal in MAIN step")
        if ci not in active.hand:
            raise IllegalActionError("card not in hand")
        if ci.card.type is CardType.B_MINION:
            raise IllegalActionError("B-Minion cannot be summoned directly; use Mana phase")
        if ci.card.type is CardType.MAGIC and not ci.card.main_timing_ok:
            raise IllegalActionError("magic card is flash-only timing")
        from zz.pc02 import can_use_card

        if not can_use_card(active, ci, self.state):
            raise IllegalActionError("card-specific use condition is not met")
        effective_cost = self.effective_cost(active, ci)
        if not self._can_pay(active, effective_cost, ci):
            raise IllegalActionError(f"cannot pay cost {effective_cost}")
        field_replacement = None
        if ci.card.type is CardType.F_MINION:
            field_replacement = self._field_replacement(active, replace_field_iid)
        elif replace_field_iid is not None:
            raise IllegalActionError("field replacement is only legal for field minions")
        original_cost = dict(ci.card.cost)
        self._pay(active, effective_cost, payment_base_iids=payment_base_iids, ci_being_paid_for=ci)
        from zz.pc02 import consume_cost_override

        consume_cost_override(active, ci)
        if field_replacement is not None:
            self._eject_field_card(active, field_replacement)
        active.hand.remove(ci)
        if ci.card.type is CardType.MAGIC:
            ci.area = AreaType.TRASH
            self._record_zone_move(ci, AreaType.HAND, AreaType.TRASH)
            ctx = Context(controller=active, source=ci)
            active.flags.add("cast_magic_this_turn")
            if ci.card.mana_color is Color.BLUE or Color.BLUE in ci.card.cost:
                active.flags.add("cast_blue_magic_this_turn")
            if resolve_source_effects:
                self._resolve_source_effects(ci, EffectTiming.ON_CAST_MAGIC, ctx)
                self._resolve_source_triggers(ci, TriggerTiming.ON_PLAY, ctx)
            self.triggers.emit(EffectTiming.ON_CAST_MAGIC, ctx)
            self.triggers.emit(TriggerTiming.ON_PLAY, ctx)
            self.triggers.emit(EffectTiming.ON_CARD_USED, ctx)
            if resolve_triggers:
                self.triggers.resolve_all()
            if sum(original_cost.values()) >= 4:
                active.flags.add("cast_cost_4_magic_this_turn")
            if ci.area is AreaType.TRASH and ci not in active.trash:
                active.trash.append(ci)
        else:  # F_MINION
            ci.area = AreaType.FIELD
            ci.summoning_sickness = not keyword_rules.enters_without_summoning_sickness(ci)
            active.field.append(ci)
            self._record_zone_move(ci, AreaType.HAND, AreaType.FIELD)
            self._record_summon(ci)
            self.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=active, source=ci))
            self._emit_enter_field(active, ci)
            self.triggers.emit(TriggerTiming.ON_PLAY, Context(controller=active, source=ci))
            self.triggers.emit(EffectTiming.ON_CARD_USED, Context(controller=active, source=ci))
            if resolve_triggers:
                self.triggers.resolve_all()

    # ---- movement right ----------------------------------------------

    def move_card(self, ci: CardInstance, direction: str,
                  replace_base_iid: int | None = None,
                  replace_field_iid: int | None = None) -> None:
        active = self.state.active
        if self.state.step is not Step.MAIN:
            raise IllegalActionError("move_card only legal in MAIN step")
        if active.movement_right_count <= 0:
            raise IllegalActionError("no movement right left this turn")
        if direction == "base_to_field":
            if ci not in active.base:
                raise IllegalActionError("card not in base")
            if self._movement_locked(ci):
                raise IllegalActionError("card cannot move while opponent has a force")
            if ci.card.type is CardType.MANA_TOKEN:
                raise IllegalActionError("mana tokens cannot move to field")
            if self.has_keyword(ci, Keyword.KAGO) or self.has_keyword(ci, Keyword.BLESS):
                raise IllegalActionError("Bless mana cannot move to field")
            if ci.card.is_token:
                raise IllegalActionError("token minions cannot move with movement right")
            field_replacement = self._field_replacement(active, replace_field_iid)
            if field_replacement is not None:
                self._eject_field_card(active, field_replacement)
            active.base.remove(ci)
            from zz.pc02 import on_base_mana_removed

            on_base_mana_removed(self, active, ci, reason="move_to_field")
            ci.area = AreaType.FIELD
            active.field.append(ci)
            self._fire_siren_mana_hooks("minion_mana_moves_to_field", ci)
            self.triggers.emit(EffectTiming.ON_MOVE_TO_FIELD,
                               Context(controller=active, source=ci))
            self.triggers.emit(TriggerTiming.ON_MOVE_TO_FIELD,
                               Context(controller=active, source=ci))
            self.triggers.resolve_all()
        elif direction == "field_to_base":
            if ci not in active.field:
                raise IllegalActionError("card not in field")
            if self._movement_locked(ci):
                raise IllegalActionError("card cannot move while opponent has a force")
            if ci.card.type is CardType.MANA_TOKEN or ci.card.is_token:
                raise IllegalActionError("token minions cannot move with movement right")
            self._make_base_space(active, replace_base_iid)
            active.field.remove(ci)
            self._return_blessings_to_base(ci, reserve_slots=1)
            self._reset_card_modifiers(ci)
            ci.area = AreaType.BASE
            active.base.append(ci)
            self.triggers.emit(EffectTiming.MOVE_TO_BASE,
                               Context(controller=active, source=ci))
            self.triggers.emit(TriggerTiming.MOVE_BACK,
                               Context(controller=active, source=ci))
            self.triggers.resolve_all()
        else:
            raise IllegalActionError(f"unknown direction {direction!r}")
        active.movement_right_count -= 1

    def can_bless(self, mana: CardInstance, target: CardInstance) -> bool:
        active = self.state.active
        if self.state.step is not Step.MAIN or active.movement_right_count <= 0:
            return False
        if mana not in active.base or target not in active.field or target.blessings:
            return False
        if not (self.has_keyword(mana, Keyword.KAGO) or self.has_keyword(mana, Keyword.BLESS)):
            return False
        allow_rested = any(ci.card.id == "colorless_04_02_02_03" for ci in active.field)
        if mana.rested and not allow_rested:
            return False
        from zz.pc02 import bless_condition_matches

        return bless_condition_matches(mana, target)

    def bless(self, mana: CardInstance, target: CardInstance) -> None:
        if not self.can_bless(mana, target):
            raise IllegalActionError("illegal Bless attachment")
        owner = mana.owner
        owner.base.remove(mana)
        mana.area = AreaType.BLESSING
        target.blessings.append(mana)
        owner.movement_right_count -= 1
        self._record_zone_move(mana, AreaType.BASE, AreaType.BLESSING)
        from zz.pc02 import on_base_mana_removed

        on_base_mana_removed(self, owner, mana, reason="bless")
        ctx = Context(controller=owner, source=target, target=mana)
        self.triggers.emit(EffectTiming.ON_BLESS, ctx)
        self.triggers.resolve_all()

    def _finish_blessing_return(
            self,
            host: CardInstance,
            mana: CardInstance,
            *,
            detached: bool = False,
    ) -> None:
        if detached:
            if mana.area is not AreaType.BLESSING:
                raise IllegalActionError("pending Bless mana is no longer attached")
        else:
            if mana not in host.blessings:
                raise IllegalActionError("Bless mana is no longer attached to its host")
            host.blessings.remove(mana)
        mana.area = AreaType.BASE
        mana.rested = True
        mana.summoning_sickness = True
        mana.owner.base.append(mana)
        self._record_zone_move(mana, AreaType.BLESSING, AreaType.BASE)
        from zz.pc02 import on_mana_moved_to_base

        on_mana_moved_to_base(mana.owner, mana)

    def _return_blessings_to_base(self, host: CardInstance, *, reserve_slots: int = 0) -> None:
        if not host.blessings:
            return
        for mana in list(host.blessings):
            owner = mana.owner
            if len(owner.base) >= BASE_CAP - reserve_slots:
                replacements = self.select_target(owner, "ally_base", 1, 1)
                if replacements:
                    self._make_base_space(
                        owner,
                        replacements[0].iid,
                        slots_needed=reserve_slots + 1,
                    )
                elif self.defer_blessing_base_choice(owner):
                    # The host may leave the field before the replacement prompt resolves;
                    # keep the pending mana separate so it cannot serialize with the host.
                    host.blessings.remove(mana)
                    self.pending_blessing_returns.append((host, mana))
                    continue
                else:
                    raise IllegalActionError(
                        "Bless mana returning to a full base requires a replacement"
                    )
            self._finish_blessing_return(host, mana)

    def resolve_blessing_base_choice(
            self,
            host: CardInstance,
            mana: CardInstance,
            replacement: CardInstance,
    ) -> None:
        pending = (host, mana)
        if not self.pending_blessing_returns or self.pending_blessing_returns[0] != pending:
            raise IllegalActionError("Bless return is not awaiting a base replacement")
        if replacement not in mana.owner.base:
            raise IllegalActionError("Bless return replacement is not in the owner's base")
        self.pending_blessing_returns.pop(0)
        self._make_base_space(mana.owner, replacement.iid)
        self._finish_blessing_return(host, mana, detached=True)
        if not self.pending_blessing_returns and self._effect_resolution_depth == 0:
            self._resolve_state_based_actions()
            self._flush_pending_destroy_events()
            self.triggers.resolve_all()
            self._resolve_state_based_actions()

    def create_token(
            self,
            player: Player,
            card: Card,
            *,
            rested: bool = False,
            replace_field_iid: int | None = None,
    ) -> CardInstance:
        self._make_field_space(player, replace_field_iid)
        card.is_token = True
        token = CardInstance(
            card=card,
            owner=player,
            iid=self.state.allocate_iid(),
            area=AreaType.FIELD,
            rested=rested,
            summoning_sickness=True,
        )
        player.field.append(token)
        self._emit_enter_field(player, token)
        return token

    def create_tokens(
            self,
            player: Player,
            cards: Iterable[Card],
            *,
            source: CardInstance | None = None,
            rested: bool = False,
            optional: bool = False,
            count: int | None = None,
    ) -> list[CardInstance]:
        """Create a batch of tokens through the shared full-field replacement path."""
        specs = list(cards)
        if not specs:
            return []
        if count is not None:
            if isinstance(count, bool) or not isinstance(count, int):
                raise IllegalActionError("token count must be an integer")
            if count < 0 or count > len(specs):
                raise IllegalActionError("token count is outside the effect range")
            specs = specs[:count]
        if not specs:
            return []
        replacements_needed = max(0, len(player.field) + len(specs) - FIELD_CAP)
        replacement_iids: list[int] = []
        create_count = len(specs)
        if replacements_needed:
            explicit_count = count is not None
            minimum_replacements = replacements_needed if explicit_count else (0 if optional else replacements_needed)
            replacements = self.select_target(
                player,
                "ally_minion",
                minimum_replacements,
                replacements_needed,
                source=source,
            )
            if len(replacements) < replacements_needed and (not optional or explicit_count):
                return []
            replacement_iids = [target.iid for target in replacements]
            if optional and not explicit_count:
                open_slots = max(0, FIELD_CAP - len(player.field))
                create_count = min(len(specs), open_slots + len(replacement_iids))
        created: list[CardInstance] = []
        for card in specs[:create_count]:
            replace_iid = None
            if len(player.field) >= FIELD_CAP:
                if not replacement_iids:
                    return created
                replace_iid = replacement_iids.pop(0)
            created.append(
                self.create_token(
                    player,
                    card,
                    rested=rested,
                    replace_field_iid=replace_iid,
                )
            )
        return created

    def move_base_minion_to_field(
            self,
            player: Player,
            ci: CardInstance,
            *,
            rested: bool = False,
            replace_field_iid: int | None = None,
    ) -> None:
        if ci not in player.base:
            raise IllegalActionError("card is not in base")
        if ci.card.type is CardType.MANA_TOKEN:
            raise IllegalActionError("mana tokens cannot move to field")
        if ci.card.is_token:
            raise IllegalActionError("token minions cannot move to field")
        if ci.card.type not in (CardType.B_MINION, CardType.F_MINION):
            raise IllegalActionError("only minion mana can move to field")
        self._make_field_space(player, replace_field_iid)
        player.base.remove(ci)
        ci.area = AreaType.FIELD
        ci.rested = rested
        player.field.append(ci)
        self._fire_siren_mana_hooks("minion_mana_moves_to_field", ci)
        self.triggers.emit(EffectTiming.ON_MOVE_TO_FIELD, Context(controller=player, source=ci))
        self.triggers.emit(TriggerTiming.ON_MOVE_TO_FIELD, Context(controller=player, source=ci))
        self.triggers.resolve_all()

    def place_generated_colorless_mana(self, player: Player, replace_base_iid: int | None = None) -> CardInstance:
        self._make_base_space(player, replace_base_iid)
        token_card = Card(id="mana_token", name_jp="無色マナ", name_en="Colorless Mana",
                          type=CardType.MANA_TOKEN, cost={})
        token = CardInstance(
            card=token_card,
            owner=player,
            iid=self.state.allocate_iid(),
            area=AreaType.BASE,
        )
        player.base.append(token)
        return token

    def put_field_minion_from_hand(
            self,
            player: Player,
            ci: CardInstance,
            *,
            rested: bool = False,
            replace_field_iid: int | None = None,
    ) -> None:
        """Put an F-Minion from hand onto the field without paying or summoning it."""
        if ci not in player.hand:
            raise IllegalActionError("card is not in hand")
        if ci.card.type is not CardType.F_MINION:
            raise IllegalActionError("only field minions can be put onto the field")
        self._make_field_space(player, replace_field_iid)
        player.hand.remove(ci)
        ci.area = AreaType.FIELD
        ci.rested = rested
        ci.summoning_sickness = not keyword_rules.enters_without_summoning_sickness(ci)
        player.field.append(ci)
        self._record_zone_move(ci, AreaType.HAND, AreaType.FIELD)
        self._emit_enter_field(player, ci)
        self.triggers.resolve_all()

    def put_base_minion_from_hand(
            self,
            player: Player,
            ci: CardInstance,
            *,
            rested: bool = True,
            replace_base_iid: int | None = None,
    ) -> None:
        """Put an F-Minion from hand into the base without summoning it."""
        if ci not in player.hand:
            raise IllegalActionError("card is not in hand")
        if ci.card.type is not CardType.F_MINION:
            raise IllegalActionError("only field minions can be put into the base")
        self._make_base_space(player, replace_base_iid)
        player.hand.remove(ci)
        ci.area = AreaType.BASE
        ci.rested = rested
        ci.summoning_sickness = True
        player.base.append(ci)
        self._record_zone_move(ci, AreaType.HAND, AreaType.BASE)

    def place_from_deck_to_base(
            self,
            player: Player,
            ci: CardInstance,
            *,
            rested: bool = True,
            replace_base_iid: int | None = None,
    ) -> None:
        if ci not in player.deck:
            raise IllegalActionError("base card is not in deck")
        self._make_base_space(player, replace_base_iid)
        player.deck.remove(ci)
        ci.area = AreaType.BASE
        ci.rested = rested
        player.base.append(ci)

    def summon_from_trash(
            self,
            player: Player,
            ci: CardInstance,
            *,
            rested: bool = False,
            replace_field_iid: int | None = None,
    ) -> None:
        if ci not in player.trash:
            raise IllegalActionError("card is not in trash")
        if ci.card.type is not CardType.F_MINION:
            raise IllegalActionError("only field minions can be summoned from trash")
        self._make_field_space(player, replace_field_iid)
        player.trash.remove(ci)
        ci.area = AreaType.FIELD
        ci.rested = rested
        ci.summoning_sickness = True
        player.field.append(ci)
        self._record_zone_move(ci, AreaType.TRASH, AreaType.FIELD)
        self._emit_enter_field(player, ci)
        self.triggers.resolve_all()

    def move_target_to_base(
            self,
            ci: CardInstance,
            *,
            rested: bool = True,
            replace_base_iid: int | None = None,
    ) -> None:
        if ci.area is not AreaType.FIELD or ci not in ci.owner.field:
            raise IllegalActionError("target is not in field")
        if ci.card.is_token:
            self._remove_token_from_game(ci)
            return
        owner = ci.owner
        self._make_base_space(owner, replace_base_iid)
        owner.field.remove(ci)
        self._return_blessings_to_base(ci, reserve_slots=1)
        self._reset_card_modifiers(ci)
        ci.area = AreaType.BASE
        ci.rested = rested
        owner.base.append(ci)
        self._record_zone_move(ci, AreaType.FIELD, AreaType.BASE)
        self.triggers.emit(EffectTiming.MOVE_TO_BASE, Context(controller=owner, source=ci))
        self.triggers.emit(TriggerTiming.MOVE_BACK, Context(controller=owner, source=ci))
        self.triggers.resolve_all()

    # ---- combat -------------------------------------------------------

    def can_attack(self, attacker: CardInstance) -> bool:
        active = self.state.active
        if self.state.turn == 1 and active.is_first_player:
            return False
        if attacker not in active.field:
            return False
        if attacker.card.type is CardType.MANA_TOKEN:
            return False
        if attacker.card.id == "purple_02_02_01_01" and self._opponent_has_force(attacker.owner):
            return False
        if attacker.card.id == "red_01_02_01_00" and self._own_field_minion_count(attacker.owner) <= 2:
            return False
        from zz.pc01r import can_attack_or_move
        from zz.pc02 import can_attack

        if not can_attack_or_move(attacker) or not can_attack(attacker):
            return False
        if attacker.rested:
            return False
        if self.state.step is not Step.MAIN:
            return False
        return True

    def legal_attack_targets(self, attacker: CardInstance) -> list[AttackTarget]:
        from zz.enums import AttackTargetKind
        if not self.can_attack(attacker):
            return []
        opp = self.state.opponent
        out: list[AttackTarget] = []
        for f in opp.forces:
            if not f.destroyed and not self._force_attack_restricted(attacker, f):
                out.append(AttackTarget(kind=AttackTargetKind.FORCE, ref=f))
        no_forces_left = all(f.destroyed for f in opp.forces)
        was_present_at_turn_start = attacker.iid in self.state.present_at_turn_start
        if (
            no_forces_left
            or self.has_keyword(attacker, Keyword.RUSH)
            or (not attacker.summoning_sickness and was_present_at_turn_start)
        ):
            out.append(AttackTarget(kind=AttackTargetKind.PLAYER, ref=opp))
        return out

    def legal_blockers(self, attacker: CardInstance) -> list[CardInstance]:
        from zz.pc01r import can_block
        from zz.pc02 import can_block as pc02_can_block

        out = []
        for b in self.state.opponent.field:
            if b.card.id == "purple_02_02_01_01" and self._opponent_has_force(b.owner):
                continue
            if not keyword_rules.can_block_attacker(
                    b,
                    attacker,
                    self.state.active,
                    keyword_fn=self.has_keyword,
            ):
                continue
            if not can_block(attacker, b, self.state):
                continue
            if not pc02_can_block(attacker, b, self.state):
                continue
            out.append(b)
        return out

    def _opponent_has_force(self, player: Player) -> bool:
        opponent = self.state.players[1 - self.state.players.index(player)]
        return any(not force.destroyed for force in opponent.forces)

    def _movement_locked(self, ci: CardInstance) -> bool:
        from zz.pc01r import can_attack_or_move

        return (
            ci.card.id == "purple_02_02_01_01" and self._opponent_has_force(ci.owner)
        ) or not can_attack_or_move(ci)

    def _own_field_minion_count(self, player: Player) -> int:
        return sum(
            1
            for ci in player.field
            if ci.card.type is not CardType.MANA_TOKEN
        )

    def _force_attack_restricted(self, attacker: CardInstance, force: ForceInstance) -> bool:
        from zz.pc02 import can_attack_force

        if not can_attack_force(attacker):
            return True
        if sum(attacker.card.cost.values()) > 5:
            return False
        return any(
            source.card.id == "white_04_02_01_01" and source.owner is force.owner
            for source in force.owner.field
        )

    def required_blockers(self, attacker: CardInstance, blockers: list[CardInstance]) -> list[CardInstance]:
        if not blockers:
            return []
        must_blockers = [blocker for blocker in blockers if "turn:must_block" in blocker.flags]
        if must_blockers:
            return must_blockers
        forced_iid = next((flag.split(":", 1)[1] for flag in attacker.flags if flag.startswith("force_block_iid:")), None)
        if forced_iid is not None:
            forced = next((blocker for blocker in blockers if str(blocker.iid) == forced_iid), None)
            return [] if forced is None else [forced]
        if "must_be_blocked" in attacker.flags:
            return list(blockers)
        if any(source.card.id == "white_08_02_01_00" and source.owner is attacker.owner for source in attacker.owner.field):
            return list(blockers)
        if "hunter_must_be_blocked" in attacker.owner.flags and "ハンター" in attacker.card.race_jp:
            return list(blockers)
        return []

    def must_block(self, attacker: CardInstance, blockers: list[CardInstance]) -> bool:
        return bool(self.required_blockers(attacker, blockers))

    def can_decline_block(self, attacker: CardInstance, blockers: list[CardInstance]) -> bool:
        return not self.must_block(attacker, blockers)

    def forced_blocker(self, attacker: CardInstance, blockers: list[CardInstance]) -> CardInstance | None:
        required = self.required_blockers(attacker, blockers)
        if required:
            return required[0]
        return None

    def _damage_player(
            self,
            player: Player,
            amount: int,
            source,
            *,
            damage_kind: str = "effect",
    ) -> None:
        # Damage hits any active Force first... but for direct attacks the target was already chosen.
        # This helper only used for direct player attacks (no Forces left, or attacker bypasses).
        if amount <= 0:
            return
        reduction_blocked = id(player) in self._player_damage_reduction_blocked
        if not reduction_blocked:
            amount = self._force_reduced_player_damage(player, amount, source, damage_kind)
            if damage_kind == "minion_dp":
                from zz.pc01r import adjust_minion_dp_damage

                amount = adjust_minion_dp_damage(self.state, amount, source)
            amount = max(0, amount - self._yakutzork_player_damage_reduction(player))
            amount = max(0, amount - self._player_damage_reduction.get(id(player), 0))
        if amount <= 0:
            return
        player.life = max(0, player.life - amount)
        player.flags.add(self._player_damage_marker())
        self._record_visual_event({
            "type": "damage",
            "targetKind": "player",
            "side": player.side.name,
            "amount": amount,
        })
        self._emit_damage(
            EffectTiming.ON_DAMAGE_PLAYER,
            source,
            player,
            amount=amount,
            damage_kind=damage_kind,
        )
        if player.life <= 0:
            winner = self.state.players[1 - self.state.players.index(player)]
            raise GameOver(winner=winner, reason=f"{player.name} player life <= 0")

    def _damage_force(
            self,
            fi: ForceInstance,
            amount: int,
            source,
            *,
            damage_kind: str = "effect",
    ) -> int:
        """Return spillover (excess damage after Force life is depleted)."""
        if amount <= 0:
            return 0
        if fi.destroyed:
            return amount
        if id(fi) not in self._force_damage_reduction_blocked:
            amount = max(0, amount - self._force_damage_reduction.get(id(fi), 0))
        if amount <= 0:
            return 0
        absorbed = min(fi.life, amount)
        fi.life -= absorbed
        self._record_visual_event({
            "type": "damage",
            "targetKind": "force",
            "side": fi.owner.side.name,
            "forceId": fi.force.id,
            "amount": absorbed,
        })
        spill = amount - absorbed
        if fi.life <= 0:
            self._destroy_force(fi, source=source)
        self._emit_damage(
            EffectTiming.ON_DAMAGE_FORCE,
            source,
            fi,
            amount=absorbed,
            damage_kind=damage_kind,
        )
        return spill

    def _emit_damage(
            self,
            timing: EffectTiming,
            source,
            target,
            *,
            amount: int,
            damage_kind: str = "effect",
    ) -> None:
        controller = source.owner if isinstance(source, CardInstance) else target.owner
        ctx = Context(controller=controller, source=source, target=target)
        setattr(ctx, "damage_kind", damage_kind)
        setattr(ctx, "damage_amount", amount)
        self.triggers.emit(timing, ctx)
        self.triggers.resolve_all()
        from zz.pc02 import on_damage_resolved

        on_damage_resolved(self, source, target, amount)

    def _emit_battle_win(self, winner: CardInstance, loser: CardInstance) -> None:
        if winner.area is not AreaType.FIELD:
            return
        self.triggers.emit(
            EffectTiming.ON_BATTLE_WIN,
            Context(controller=winner.owner, source=winner, target=loser),
        )
        self.triggers.resolve_all()
        from zz.pc01r import battle_win_damage_enabled

        if battle_win_damage_enabled(winner.owner):
            self._damage_player(
                self.state.players[1 - self.state.players.index(winner.owner)],
                1,
                source=winner,
            )

    def _destroy_force(self, fi: ForceInstance, source) -> None:
        fi.destroyed = True
        fi.rested = True
        # Fire on_destroy in rested state (rulebook page 8 footnote)
        if fi.force.on_destroy is not None:
            fi.force.on_destroy(fi, self.state, Context(controller=fi.owner, source=source))
        # Unregister passive
        self._passive_modifiers = [
            (kind, fn) for kind, fn in self._passive_modifiers
            if getattr(fn, "_force_iid", None) != id(fi)
        ]
        self.triggers.emit(
            EffectTiming.ON_FORCE_DESTROYED,
            Context(controller=fi.owner, source=source, target=fi),
        )
        self._resolve_triggers_if_idle()

    def declare_attack(self, attacker: CardInstance, target: AttackTarget,
                       resolve_triggers: bool = True) -> None:
        """Attack Declaration Step: rest attacker and fire ON_ATTACK triggers."""
        from zz.enums import AttackTargetKind
        if not self.can_attack(attacker):
            raise IllegalActionError("attacker cannot attack")
        attacker.rested = True
        self.triggers.emit(EffectTiming.ON_ATTACK,
                           Context(controller=self.state.active,
                                   source=attacker, target=target.ref))
        self.triggers.emit(TriggerTiming.ON_ATTACK,
                           Context(controller=self.state.active,
                                   source=attacker, target=target.ref))
        if resolve_triggers:
            self.triggers.resolve_all()

    def resolve_attack_after_flash(self, attacker: CardInstance, target: AttackTarget,
                                   blocker: Optional[CardInstance] = None) -> None:
        """Block and Battle Resolution steps after Flash has finished."""
        from zz.enums import AttackTargetKind
        target = getattr(self, "_pc02_attack_target_override", target)
        if hasattr(self, "_pc02_attack_target_override"):
            delattr(self, "_pc02_attack_target_override")
        if attacker.area is not AreaType.FIELD:
            return
        blockers = self.legal_blockers(attacker)
        required_blockers = self.required_blockers(attacker, blockers)
        if blocker is None:
            blocker = required_blockers[0] if required_blockers else None
        if blocker is not None:
            if blocker not in blockers:
                raise IllegalActionError("illegal blocker")
            if required_blockers and blocker not in required_blockers:
                raise IllegalActionError("illegal blocker")
            blocker.rested = True
            self.triggers.emit(EffectTiming.ON_BLOCK,
                               Context(controller=self.state.opponent,
                                       source=blocker, target=attacker))
            self.triggers.emit(TriggerTiming.ON_BLOCK,
                               Context(controller=self.state.opponent,
                                       source=blocker, target=attacker))
            self.triggers.resolve_all()
            self._apply_player_blocked_attack_effects(attacker, blocker)
            # 4. Minion battle compares BP against BP.
            from zz.pc01r import battle_outcome_override
            from zz.pc02 import battle_outcome_override as pc02_battle_outcome_override

            override = pc02_battle_outcome_override(attacker, blocker, self.state)
            if override is None:
                override = battle_outcome_override(attacker, blocker)
            if override is None:
                atk_dest = self.effective_bp(attacker) >= self.effective_bp(blocker)
                blk_dest = self.effective_bp(blocker) >= self.effective_bp(attacker)
            else:
                atk_dest, blk_dest = override
            attacker_death_blow = self._should_death_blow_destroy(attacker, blocker, self.state.active)
            blocker_death_blow = self._should_death_blow_destroy(blocker, attacker, self.state.active)
            spill_damage = max(0, self.effective_dp(attacker) - self.effective_dp(blocker))
            if atk_dest and not blk_dest:
                self._emit_battle_win(attacker, blocker)
                if self.has_keyword(attacker, Keyword.PENETRATE) and spill_damage > 0:
                    # Penetrate is won-battle damage, so Minotauros sees it as DP damage.
                    self._apply_penetrate_spill_to_original_target(attacker, target, spill_damage)
            elif blk_dest and not atk_dest:
                self._emit_battle_win(blocker, attacker)
            self._enter_effect_resolution()
            try:
                if atk_dest:
                    self._destroy(blocker, source=attacker)
                if blk_dest:
                    self._destroy(attacker, source=blocker)
            finally:
                self._leave_effect_resolution()
            self.triggers.resolve_all()
            self._apply_death_blow(
                attacker,
                blocker,
                first_active=attacker_death_blow,
                second_active=blocker_death_blow,
            )
            self._destroy_maddoll_after_battle(attacker, blocker)
        else:
            # 4. Unblocked: damage to player/force = attacker.DP per rulebook p20
            if target.kind is AttackTargetKind.MINION:
                # TBD: rulebook may forbid direct minion targeting; keep path using BP
                # since unblocked-to-minion is modeled as a direct combat exchange.
                ref = target.ref
                if self.effective_bp(attacker) >= self.effective_dp(ref):
                    self._destroy(ref, source=attacker)
                if self.effective_bp(ref) >= self.effective_dp(attacker):
                    self._destroy(attacker, source=ref)
                self._apply_death_blow(attacker, ref)
                self._destroy_maddoll_after_battle(attacker, ref)
            elif target.kind is AttackTargetKind.FORCE:
                self._damage_force(
                    target.ref,
                    self.effective_dp(attacker),
                    source=attacker,
                    damage_kind="minion_dp",
                )
                self._destroy_maddoll_after_battle(attacker)
            elif target.kind is AttackTargetKind.PLAYER:
                self._damage_player(
                    self.state.opponent,
                    self.effective_dp(attacker),
                    source=attacker,
                    damage_kind="minion_dp",
                )
                self._destroy_maddoll_after_battle(attacker)

    def attack(self, attacker: CardInstance, target: AttackTarget,
               blocker: Optional[CardInstance] = None) -> None:
        """Full attack sequence for CLI/policy-driven play."""
        self.declare_attack(attacker, target)
        self.run_flash(triggered_by=("attack", attacker, target))
        self.resolve_attack_after_flash(attacker, target, blocker)

    def _spill_to_player_or_force(
            self,
            player: Player,
            amount: int,
            source,
            *,
            damage_kind: str = "effect",
    ) -> None:
        for f in player.forces:
            if not f.destroyed:
                amount = self._damage_force(f, amount, source=source, damage_kind=damage_kind)
                if amount <= 0:
                    return
        if amount > 0:
            self._damage_player(player, amount, source=source, damage_kind=damage_kind)

    def _apply_penetrate_spill_to_original_target(
            self,
            attacker: CardInstance,
            target: AttackTarget,
            amount: int,
    ) -> None:
        from zz.enums import AttackTargetKind

        if target.kind is AttackTargetKind.PLAYER:
            self._damage_player(self.state.opponent, amount, source=attacker, damage_kind="minion_dp")
        elif target.kind is AttackTargetKind.FORCE:
            self._damage_force(target.ref, amount, source=attacker, damage_kind="minion_dp")

    def _apply_player_blocked_attack_effects(self, attacker: CardInstance, blocker: CardInstance) -> None:
        if "turn:arondai_player_attack" in attacker.owner.flags:
            self._damage_player(blocker.owner, 1, source=attacker)

    def _apply_death_blow(
            self,
            first: CardInstance,
            second: CardInstance,
            *,
            first_active: bool | None = None,
            second_active: bool | None = None,
    ) -> None:
        active = self.state.active
        if first_active is None:
            first_active = self._should_death_blow_destroy(first, second, active)
        if second_active is None:
            second_active = self._should_death_blow_destroy(second, first, active)
        if first_active:
            self._destroy(second, source=first)
        if second_active:
            self._destroy(first, source=second)

    def _destroy_maddoll_after_battle(self, *participants: CardInstance) -> None:
        for ci in participants:
            if ci.card.id == "purple_01_02_01_00" and ci.area is AreaType.FIELD:
                self._destroy(ci, source=ci)

    def _should_death_blow_destroy(
            self,
            source: CardInstance,
            opponent: CardInstance,
            active: Player,
    ) -> bool:
        from zz.pc02 import death_blow_active

        return (
            death_blow_active(source, active, self.state)
            and source.card.type in {CardType.F_MINION, CardType.B_MINION}
            and opponent.card.type in {CardType.F_MINION, CardType.B_MINION}
            and self.has_keyword(source, Keyword.DEATH_BLOW)
        )

    def _destroy(self, ci: CardInstance, source) -> None:
        if ci.area is not AreaType.FIELD:
            return
        owner = ci.owner
        self.destroy_events.append(ci)
        self._record_visual_event({
            "type": "destroy",
            "card": ci,
        })
        if ci.card.is_token:
            self._remove_token_from_game(ci)
            return
        if ci in owner.field:
            owner.field.remove(ci)
        had_blessed_return = ci.card.id == "yellow_05_02_02_00" and bool(ci.blessings)
        self._return_blessings_to_base(ci)
        self._reset_card_zone_state(ci)
        ci.area = AreaType.TRASH
        owner.trash.append(ci)
        ctx = Context(controller=owner, source=source, target=ci)
        setattr(ctx, "blessed_return_to_hand", had_blessed_return)
        self._pending_destroy_events.append((ci, ctx))
        if self._effect_resolution_depth == 0 and not self.pending_blessing_returns:
            self._flush_pending_destroy_events()
            self.triggers.resolve_all()
            self._resolve_state_based_actions()

    def _resolve_destroy_event(self, ci: CardInstance, ctx: Context) -> None:
        self._resolve_source_effects(ci, EffectTiming.ON_DESTROY, ctx)
        self._resolve_source_triggers(ci, TriggerTiming.ON_DESTROY, ctx)
        self.triggers.emit(EffectTiming.ON_DESTROY,
                           ctx)
        self.triggers.emit(TriggerTiming.ON_DESTROY,
                           ctx)
        from zz.pc02 import on_minion_destroyed

        on_minion_destroyed(self, ci)

    # ---- top-level action API ----------------------------------------

    def legal_actions(self) -> list[Action]:
        active = self.state.active
        out: list[Action] = []
        if self.state.step is Step.MANA:
            for ci in active.hand:
                if ci.card.type is not CardType.B_MINION:
                    continue
                if len(active.base) < BASE_CAP:
                    out.append(Action(kind="play_to_base", payload={"iid": ci.iid}))
                else:
                    for base_ci in active.base:
                        out.append(Action(
                            kind="play_to_base",
                            payload={
                                "iid": ci.iid,
                                "replace_base_iid": base_ci.iid,
                                "base_card_iid": base_ci.iid,
                            },
                        ))
            if len(active.base) < BASE_CAP:
                out.append(Action(kind="place_colorless_mana"))
            else:
                for base_ci in active.base:
                    out.append(Action(
                        kind="place_colorless_mana",
                        payload={
                            "replace_base_iid": base_ci.iid,
                            "base_card_iid": base_ci.iid,
                        },
                    ))
            if len(active.base) >= BASE_CAP:
                out.append(Action(kind="skip_mana"))
            # HR2: 後攻 player with 2+ consecutive colorless-only turns may swap a base card's color
            if not active.is_first_player and active.colorless_only_streak >= 2:
                for ci in active.base:
                    if self._mana_color_of(ci) is not Color.COLORLESS:
                        continue
                    for color in [Color.RED, Color.YELLOW, Color.WHITE,
                                   Color.GREEN, Color.BLUE, Color.PURPLE]:
                        out.append(Action(kind="swap_mana_color",
                                          payload={"base_card_iid": ci.iid,
                                                   "new_color": color.value}))
            return out
        if self.state.step is Step.MAIN:
            # Summon F-Minion / play Magic (main-timing)
            for ci in active.hand:
                if ci.card.type is CardType.B_MINION:
                    continue
                from zz.pc02 import can_use_card

                if not can_use_card(active, ci, self.state):
                    continue
                cost = self.effective_cost(active, ci)
                if not self._can_pay(active, cost, ci):
                    continue
                if ci.card.type is CardType.F_MINION and len(active.field) >= FIELD_CAP:
                    for field_ci in active.field:
                        out.append(Action(
                            kind="play_card",
                            payload={"iid": ci.iid, "replace_field_iid": field_ci.iid},
                        ))
                    continue
                if ci.card.type is CardType.MAGIC and not ci.card.main_timing_ok:
                    continue
                out.append(Action(kind="play_card", payload={"iid": ci.iid}))
            # Movement Right
            if active.movement_right_count > 0:
                for mana in active.base:
                    for target in active.field:
                        if self.can_bless(mana, target):
                            out.append(Action(
                                kind="bless",
                                payload={"iid": mana.iid, "mana_iid": mana.iid, "target_iid": target.iid},
                            ))
                for ci in active.base:
                    if self._movement_locked(ci):
                        continue
                    if self.has_keyword(ci, Keyword.KAGO) or self.has_keyword(ci, Keyword.BLESS):
                        continue
                    if (ci.card.type is not CardType.MANA_TOKEN
                        and not ci.card.is_token):
                        if len(active.field) < FIELD_CAP:
                            out.append(Action(kind="move_card",
                                              payload={"iid": ci.iid, "direction": "base_to_field"}))
                        else:
                            for field_ci in active.field:
                                out.append(Action(
                                    kind="move_card",
                                    payload={
                                        "iid": ci.iid,
                                        "direction": "base_to_field",
                                        "replace_field_iid": field_ci.iid,
                                    },
                                ))
                for ci in active.field:
                    if self._movement_locked(ci):
                        continue
                    if ci.card.type is CardType.MANA_TOKEN or ci.card.is_token:
                        continue
                    if len(active.base) < BASE_CAP:
                        out.append(Action(kind="move_card",
                                          payload={"iid": ci.iid, "direction": "field_to_base"}))
                    else:
                        for base_ci in active.base:
                            out.append(Action(
                                kind="move_card",
                                payload={
                                    "iid": ci.iid,
                                    "direction": "field_to_base",
                                    "replace_base_iid": base_ci.iid,
                                    "base_card_iid": base_ci.iid,
                                },
                            ))
            # Attack
            for ci in active.field:
                if self.can_attack(ci):
                    if self.legal_attack_targets(ci):
                        out.append(Action(kind="attack",
                                          payload={"attacker_iid": ci.iid}))
            out.append(Action(kind="end_turn"))
            return out
        return []

    def _find(self, region: list[CardInstance], iid: int) -> CardInstance:
        for ci in region:
            if ci.iid == iid:
                return ci
        raise IllegalActionError(f"no card iid={iid} in region")

    def apply(self, action: Action) -> None:
        payload = action.payload
        active = self.state.active
        if action.kind != "attack":
            self._record_observed_action(active, action)
        if action.kind == "play_to_base":
            self.play_to_base(self._find(active.hand, payload["iid"]),
                              payload.get("replace_base_iid"))
        elif action.kind == "place_colorless_mana":
            self.place_colorless_mana(payload.get("replace_base_iid"))
        elif action.kind == "skip_mana":
            if self.state.step is not Step.MANA:
                raise IllegalActionError("skip_mana only legal in MANA step")
            if len(active.base) < BASE_CAP:
                raise IllegalActionError("skip_mana only legal at base cap")
            self.advance_from_mana()
        elif action.kind == "play_card":
            self.play_card(
                self._find(active.hand, payload["iid"]),
                payment_base_iids=payload.get("payment_base_iids"),
                replace_field_iid=payload.get("replace_field_iid"),
            )
        elif action.kind == "move_card":
            ci = self._find(active.base + active.field, payload["iid"])
            self.move_card(
                ci,
                payload["direction"],
                payload.get("replace_base_iid"),
                payload.get("replace_field_iid"),
            )
        elif action.kind == "bless":
            self.bless(
                self._find(active.base, payload["mana_iid"]),
                self._find(active.field, payload["target_iid"]),
            )
        elif action.kind == "attack":
            atk = self._find(active.field, payload["attacker_iid"])
            # Sub-decisions: target now, then Flash, then blocker after Flash changes settle.
            policy = self.policy_for(active)
            targets = self.legal_attack_targets(atk)
            if not targets:
                raise IllegalActionError("no legal attack targets")
            target = policy.choose_attack_target(self, atk, targets)
            self._record_observed_action(active, action, attack_target_kind=getattr(target, "kind", None))
            self.declare_attack(atk, target)
            self.run_flash(triggered_by=("attack", atk, target))
            blocker_policy = self.policy_for(self.state.opponent)
            blockers = self.legal_blockers(atk)
            blocker_choices = self.required_blockers(atk, blockers) or blockers
            previous_blocker_context = getattr(self, "_blocker_selection_context", None)
            self._blocker_selection_context = {"attacker": atk, "target": target}
            try:
                blocker = blocker_policy.choose_blocker(self, atk, blocker_choices)
            finally:
                if previous_blocker_context is None:
                    if hasattr(self, "_blocker_selection_context"):
                        delattr(self, "_blocker_selection_context")
                else:
                    self._blocker_selection_context = previous_blocker_context
            if blocker is None and not self.can_decline_block(atk, blockers):
                blocker = self.forced_blocker(atk, blockers)
            self.resolve_attack_after_flash(atk, target, blocker)
        elif action.kind == "end_turn":
            self.end_turn()
        elif action.kind == "swap_mana_color":   # HR2 — Task 24
            from zz.house_rules import apply_swap_mana_color
            apply_swap_mana_color(self, payload["base_card_iid"], Color(payload["new_color"]))
        else:
            raise IllegalActionError(f"unknown action {action.kind!r}")

    def _record_observed_action(
            self,
            actor: Player,
            action: Action,
            *,
            attack_target_kind: Any | None = None,
    ) -> None:
        actor_side = self._side_name(actor)
        for observer in self.state.players:
            observer_side = self._side_name(observer)
            if observer_side == actor_side:
                continue
            profile = self.observed_action_profile_by_player_side.setdefault(observer_side, {})
            self._increment_observed_profile(profile, "opponent_action_count")
            action_kind = str(action.kind)
            self._increment_observed_profile(profile, f"opponent_{action_kind}_count")
            if self.state.turn <= 5:
                self._increment_observed_profile(profile, "opponent_early_action_count")
            if action.kind == "attack":
                if self.state.turn <= 5:
                    self._increment_observed_profile(profile, "opponent_early_attack_count")
                target_label = getattr(attack_target_kind, "value", attack_target_kind)
                if target_label:
                    self._increment_observed_profile(profile, f"opponent_attack_{target_label}_count")
            elif action.kind == "move_card":
                direction = str(action.payload.get("direction") or "")
                if direction:
                    self._increment_observed_profile(profile, f"opponent_move_{direction}_count")

    def _increment_observed_profile(self, profile: dict[str, int], key: str) -> None:
        profile[key] = int(profile.get(key, 0)) + 1

    def _side_name(self, player: Player) -> str:
        side = getattr(player, "side", "")
        return str(getattr(side, "name", side))

    # ---- Flash sub-state ---------------------------------------------

    def legal_flash_actions(self, player: Player) -> list[Action]:
        out = [Action(kind="flash_pass")]
        from zz.pc02 import can_use_card

        for ci in player.hand:
            if not can_use_card(player, ci, self.state):
                continue
            if ci.card.type is CardType.MAGIC and ci.card.flash_timing_ok and self._can_pay(player, self.effective_cost(player, ci), ci):
                out.append(Action(kind="play_card", payload={"iid": ci.iid}))
            elif (keyword_rules.is_flash_summonable(ci)
                  and self._can_pay(player, self.effective_cost(player, ci), ci)):
                if len(player.field) < FIELD_CAP:
                    out.append(Action(kind="play_card", payload={"iid": ci.iid}))
                else:
                    for field_ci in player.field:
                        out.append(Action(
                            kind="play_card",
                            payload={"iid": ci.iid, "replace_field_iid": field_ci.iid},
                        ))
        for ci in player.field:
            if (Keyword.REACTIVE in ci.keywords
                and not ci.rested
                and ci.card.flash_ability is not None):
                if (ci.card.flash_ability_condition is None
                    or ci.card.flash_ability_condition(ci, self.state)):
                    out.append(Action(kind="activate_flash_ability", payload={"iid": ci.iid}))
        return out

    def apply_flash_action(self, player: Player, action: Action, resolve_triggers: bool = True) -> str:
        """Apply one Flash choice for player. Returns 'pass' or 'action'."""
        if action.kind == "flash_pass":
            return "pass"
        if action.kind == "play_card":
            ci = self._find(player.hand, action.payload["iid"])
            from zz.pc02 import can_use_card

            if not can_use_card(player, ci, self.state):
                raise IllegalActionError("card-specific use condition is not met")
            effective_cost = self.effective_cost(player, ci)
            if not self._can_pay(player, effective_cost, ci):
                raise IllegalActionError("flash play cannot pay")
            if ci.card.type is CardType.F_MINION and not keyword_rules.is_flash_summonable(ci):
                raise IllegalActionError("field minion is not playable at flash timing")
            field_replacement = None
            if ci.card.type is CardType.F_MINION:
                field_replacement = self._field_replacement(player, action.payload.get("replace_field_iid"))
            elif action.payload.get("replace_field_iid") is not None:
                raise IllegalActionError("field replacement is only legal for field minions")
            original_cost = dict(ci.card.cost)
            self._pay(player, effective_cost,
                      payment_base_iids=action.payload.get("payment_base_iids"),
                      ci_being_paid_for=ci)
            from zz.pc02 import consume_cost_override

            consume_cost_override(player, ci)
            if field_replacement is not None:
                self._eject_field_card(player, field_replacement)
            player.hand.remove(ci)
            if ci.card.type is CardType.MAGIC:
                ci.area = AreaType.TRASH
                self._record_zone_move(ci, AreaType.HAND, AreaType.TRASH)
                ctx = Context(controller=player, source=ci)
                player.flags.add("cast_magic_this_turn")
                if ci.card.mana_color is Color.BLUE or Color.BLUE in ci.card.cost:
                    player.flags.add("cast_blue_magic_this_turn")
                self._resolve_source_effects(ci, EffectTiming.ON_CAST_MAGIC, ctx)
                self._resolve_source_triggers(ci, TriggerTiming.ON_PLAY, ctx)
                self.triggers.emit(EffectTiming.ON_CAST_MAGIC, ctx)
                self.triggers.emit(TriggerTiming.ON_PLAY, ctx)
                self.triggers.emit(EffectTiming.ON_CARD_USED, ctx)
                if resolve_triggers:
                    self.triggers.resolve_all()
                if sum(original_cost.values()) >= 4:
                    player.flags.add("cast_cost_4_magic_this_turn")
                if ci.area is AreaType.TRASH and ci not in player.trash:
                    player.trash.append(ci)
            else:
                ci.area = AreaType.FIELD
                ci.summoning_sickness = not keyword_rules.enters_without_summoning_sickness(ci)
                player.field.append(ci)
                self._record_zone_move(ci, AreaType.HAND, AreaType.FIELD)
                self._record_summon(ci)
                self.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=player, source=ci))
                self._emit_enter_field(player, ci)
                self.triggers.emit(TriggerTiming.ON_PLAY, Context(controller=player, source=ci))
                self.triggers.emit(EffectTiming.ON_CARD_USED, Context(controller=player, source=ci))
                if resolve_triggers:
                    self.triggers.resolve_all()
            return "action"
        if action.kind == "activate_flash_ability":
            ci = self._find(player.field, action.payload["iid"])
            ci.rested = True
            ci.card.flash_ability(ci, self.state, Context(controller=player, source=ci))
            return "action"
        raise IllegalActionError(f"unknown flash action {action.kind!r}")

    def run_flash(self, triggered_by) -> None:
        """Drive the Flash priority loop. Exits after two consecutive passes."""
        priority = self._initial_flash_priority(triggered_by)
        passes = 0
        # Snapshot the "triggered_by" so flash abilities can reference attacker etc.
        previous_step = self.state.step
        had_flash_priority = hasattr(self, "_current_flash_priority")
        previous_flash_priority = getattr(self, "_current_flash_priority", None)
        self._flash_ctx = triggered_by
        self._set_step(Step.FLASH)
        try:
            while passes < 2:
                policy = self.policy_for(priority)
                self._current_flash_priority = priority
                action = policy.choose_flash(self, self.legal_flash_actions(priority))
                result = self.apply_flash_action(priority, action)
                if result == "pass":
                    passes += 1
                else:
                    passes = 0
                # Hand priority to the other player
                priority = self.state.opponent if priority is self.state.active else self.state.active
        finally:
            self._set_step(previous_step)
            self._flash_ctx = None
            if had_flash_priority:
                self._current_flash_priority = previous_flash_priority
            elif hasattr(self, "_current_flash_priority"):
                delattr(self, "_current_flash_priority")

    def _initial_flash_priority(self, triggered_by) -> Player:
        if isinstance(triggered_by, tuple) and triggered_by and triggered_by[0] == "attack":
            return self.state.opponent
        return self.state.active

    def select_target(self, player: Player, kind: str, min_n: int = 1, max_n: int = 1,
                       filter_fn: Optional[Callable] = None,
                       source: CardInstance | None = None) -> list:
        """Defer to the player's Policy."""
        if kind == "enemy_minion":
            opp = self.state.opponent if player is self.state.active else self.state.active
            eligible = list(opp.field)
        elif kind == "any_minion":
            eligible = [ci for owner in self.state.players for ci in owner.field]
        elif kind == "enemy_minion_cost_at_most_4":
            opp = self.state.opponent if player is self.state.active else self.state.active
            eligible = [
                ci for ci in opp.field
                if sum(ci.card.cost.values()) <= 4
            ]
        elif kind == "enemy_minion_cost_at_most_3":
            opp = self.state.opponent if player is self.state.active else self.state.active
            eligible = [
                ci for ci in opp.field
                if sum(ci.card.cost.values()) <= 3
            ]
        elif kind == "enemy_minion_cost_at_least_6":
            opp = self.state.opponent if player is self.state.active else self.state.active
            eligible = [
                ci for ci in opp.field
                if sum(ci.card.cost.values()) >= 6
            ]
        elif kind == "ally_minion":
            eligible = list(player.field)
        elif kind == "ally_base":
            eligible = list(player.base)
        elif kind == "ally_colorless_mana_token":
            eligible = [
                ci for ci in player.base
                if ci.card.type is CardType.MANA_TOKEN and self._mana_color_of(ci) is Color.COLORLESS
            ]
        elif kind == "ally_minion_base":
            eligible = [
                ci for ci in player.base
                if ci.card.type in (CardType.B_MINION, CardType.F_MINION)
            ]
        elif kind == "other_ally_minion":
            eligible = list(player.field)
        elif kind == "ally_minion_cost_at_most_4":
            eligible = [
                ci for ci in player.field
                if sum(ci.card.cost.values()) <= 4
            ]
        elif kind == "ally_force":
            eligible = [f for f in player.forces if not f.destroyed]
        elif kind == "owner_player_or_force":
            eligible = [player] + [f for f in player.forces if not f.destroyed]
        elif kind == "enemy_force":
            opp = self.state.opponent if player is self.state.active else self.state.active
            eligible = [f for f in opp.forces if not f.destroyed]
        elif kind == "enemy_minion_or_force":
            opp = self.state.opponent if player is self.state.active else self.state.active
            eligible = list(opp.field) + [f for f in opp.forces if not f.destroyed]
        elif kind == "any_minion_or_force":
            eligible = [
                target
                for owner in self.state.players
                for target in list(owner.field) + [f for f in owner.forces if not f.destroyed]
            ]
        elif kind == "ally_green_base_hand":
            eligible = [
                ci for ci in player.hand
                if ci.card.type is CardType.B_MINION and ci.card.mana_color is Color.GREEN
            ]
        elif kind == "hand_base_minion":
            eligible = [
                ci for ci in player.hand
                if ci.card.type is CardType.B_MINION
            ]
        elif kind == "trash_magic_cost_at_most_4":
            eligible = [
                ci for ci in player.trash
                if ci.card.type is CardType.MAGIC and sum(ci.card.cost.values()) <= 4
            ]
        elif kind == "deck_base_minion":
            eligible = [
                ci for ci in player.deck
                if ci.card.type is CardType.B_MINION
            ]
        elif kind == "deck_minion":
            eligible = [
                ci for ci in player.deck
                if ci.card.type in (CardType.B_MINION, CardType.F_MINION)
            ]
        elif kind == "deck_base_or_field_minion":
            eligible = [
                ci for ci in player.deck
                if ci.card.type in (CardType.B_MINION, CardType.F_MINION)
            ]
        elif kind == "trash_field_minion":
            eligible = [
                ci for ci in player.trash
                if ci.card.type is CardType.F_MINION
            ]
        elif kind == "trash_minion":
            eligible = [
                ci for ci in player.trash
                if ci.card.type in (CardType.B_MINION, CardType.F_MINION)
            ]
        elif kind == "hand_card":
            eligible = list(player.hand)
        elif kind == "hand_field_minion_cost_at_most_2":
            eligible = [
                ci for ci in player.hand
                if ci.card.type is CardType.F_MINION and sum(ci.card.cost.values()) <= 2
            ]
        elif kind == "top_field_minion":
            eligible = [
                ci for ci in player.deck[:4]
                if ci.card.type is CardType.F_MINION
            ]
        elif kind == "top2_field_minion":
            eligible = [
                ci for ci in player.deck[:2]
                if ci.card.type is CardType.F_MINION
            ]
        elif kind == "top1_card":
            eligible = list(player.deck[:1])
        elif kind == "top2_card":
            eligible = list(player.deck[:2])
        elif kind == "top4_card":
            eligible = list(player.deck[:4])
        elif kind == "top3_magic":
            eligible = [
                ci for ci in player.deck[:3]
                if ci.card.type is CardType.MAGIC
            ]
        elif kind == "deck_card":
            eligible = list(player.deck)
        elif kind == "enemy_minion_bp_at_most_500_or_opponent_player":
            opp = self.state.opponent if player is self.state.active else self.state.active
            eligible = [ci for ci in opp.field if self.effective_bp(ci) <= 500] + [opp]
        elif kind == "force_catalog":
            from zz.forces import ALL_FORCES
            eligible = list(ALL_FORCES.values())
        elif kind == "top3_field_minion":
            eligible = [
                ci for ci in player.deck[:3]
                if ci.card.type is CardType.F_MINION
            ]
        else:
            eligible = []
        if filter_fn:
            eligible = [c for c in eligible if filter_fn(c)]
        if source is not None:
            eligible = [c for c in eligible if self._can_effect_select(source, c)]
        policy = self.policy_for(player)
        previous_context = getattr(self, "_target_selection_context", None)
        self._target_selection_context = {"source": source}
        try:
            selected = policy.choose_target(self, kind, min_n, max_n, eligible)
            from zz.pc02 import on_targets_selected

            on_targets_selected(player, source, selected)
            return selected
        finally:
            if previous_context is None:
                if hasattr(self, "_target_selection_context"):
                    delattr(self, "_target_selection_context")
            else:
                self._target_selection_context = previous_context

    def _can_effect_select(
            self,
            source: CardInstance,
            target,
            *,
            source_area: AreaType | None = None,
    ) -> bool:
        if not isinstance(target, CardInstance):
            from zz.pc02 import can_effect_select_non_card

            return can_effect_select_non_card(source, target, self.state)
        from zz.pc01r import can_effect_select

        if not can_effect_select(source, target):
            return False
        from zz.pc02 import can_effect_select as pc02_can_effect_select

        if not pc02_can_effect_select(source, target, self.state):
            return False
        source_effect_area = source_area or source.area
        if (
            target.card.id == "colorless_09_02_01_00"
            and target.owner is not source.owner
            and (
                source.card.type is CardType.MAGIC
                or (
                    source.card.type in (CardType.B_MINION, CardType.F_MINION)
                    and source_effect_area is AreaType.FIELD
                )
            )
        ):
            return False
        if (
            source.card.type is CardType.MAGIC
            and target.owner is not source.owner
            and target.card.id in {"colorless_04_02_00_01", "white_02_02_00_00", "white_08_02_01_01"}
        ):
            return False
        selector_kind = ""
        is_field_minion_effect = source.card.type is CardType.F_MINION and source_effect_area is AreaType.FIELD
        is_base_minion_field_effect = source.card.type is CardType.B_MINION and source_effect_area is AreaType.FIELD
        if (is_field_minion_effect or is_base_minion_field_effect) and source.owner is not target.owner:
            selector_kind = "enemy_minion_effect"
        for kind, fn in self._passive_modifiers:
            if kind == "sphinx_selection_ward" and not fn(target, selector_kind, source):
                return False
        return True

    def should_duplicate_summon_effect(self, source: CardInstance) -> bool:
        if source.owner is not self.state.active:
            return False
        return any(
            ci.card.id == "colorless_05_02_01_05"
            and ci.owner is source.owner
            and ci.area is AreaType.FIELD
            for ci in source.owner.field
        )

    def deal_damage(self, target: CardInstance, amount: int, source) -> None:
        if amount <= 0:
            return
        target.dp_mod -= amount
        if target.dp <= 0:
            self._destroy(target, source=source)

    def discard_from_hand(self, player: Player, ci: CardInstance) -> None:
        if ci not in player.hand:
            return
        player.hand.remove(ci)
        self._reset_card_zone_state(ci)
        ci.area = AreaType.TRASH
        player.trash.append(ci)

    def mill_deck(self, player: Player, amount: int, *, source: CardInstance) -> list[CardInstance]:
        milled = list(player.deck[:max(0, amount)])
        for card in milled:
            player.deck.remove(card)
            card.area = AreaType.TRASH
            player.trash.append(card)
            self._record_zone_move(card, AreaType.DECK, AreaType.TRASH)
        if milled:
            self.triggers.emit(
                EffectTiming.ON_DECK_DISCARD,
                Context(controller=player, source=source, target=milled),
            )
            self.triggers.resolve_all()
        return milled
        self._record_zone_move(ci, AreaType.HAND, AreaType.TRASH)

    def return_to_hand(self, ci: CardInstance) -> None:
        if ci.area is not AreaType.FIELD:
            return
        owner = ci.owner
        if ci in owner.field:
            owner.field.remove(ci)
        self._return_blessings_to_base(ci)
        ci.rested = False
        ci.summoning_sickness = True
        self._reset_card_modifiers(ci)
        self.add_to_hand(owner, ci, from_area=AreaType.FIELD)

    def rest_target(self, target) -> None:
        if hasattr(target, "rested"):
            target.rested = True

    def prevent_next_refresh(self, target) -> None:
        owner = getattr(target, "owner", None)
        side = getattr(owner, "side", None)
        if side is None:
            return
        flags = getattr(target, "flags", None)
        if flags is None:
            flags = set()
            setattr(target, "flags", flags)
        flags.add(self._skip_refresh_flag(side))

    def _refresh_rest_state(self, active: Player, target) -> None:
        flags = getattr(target, "flags", None)
        flag = self._skip_refresh_flag(active.side)
        if isinstance(flags, set) and flag in flags:
            flags.remove(flag)
            return
        target.rested = False

    def _skip_refresh_flag(self, side: Side) -> str:
        return f"skip_refresh:{side.name}"

    def destroy_target(self, target, source) -> None:
        if isinstance(target, CardInstance):
            self._destroy(target, source=source)
        elif isinstance(target, ForceInstance):
            self._destroy_force(target, source=source)

    def _resolve_source_triggers(self, ci: CardInstance, timing: TriggerTiming, ctx: Context) -> None:
        for trig in ci.card.triggers:
            if trig.when is not timing:
                continue
            if trig.condition and not trig.condition(ci, self.state, ctx):
                continue
            self._record_effect_event(ci, trig)
            self._run_effect_callback(trig.fn, ci, self.state, ctx)

    def _resolve_source_effects(self, ci: CardInstance, timing: EffectTiming, ctx: Context) -> None:
        for effect in ci.card.effects:
            if effect.timing is not timing:
                continue
            if isinstance(effect, EffectSpec) and effect_once_per_turn_used(effect, ci):
                continue
            if effect.condition and not effect.condition(ci, self.state, ctx):
                continue
            if self.defer_source_effect_choice is not None and self.defer_source_effect_choice(ci, effect, ctx):
                continue
            self._record_effect_event(ci, effect)
            self._run_pre_target_effect(effect, ci, ctx)
            self._run_effect_callback(effect.fn, ci, self.state, ctx)

    # ---- Force lifecycle ---------------------------------------------

    def eligible_force_base_choices(self, player: Player) -> list[CardInstance]:
        return [ci for ci in player.deck if ci.card.type is CardType.B_MINION]

    def handle_force_destroy_base_search(self, fi: ForceInstance) -> None:
        if self.defer_force_base_choice(fi.owner) and self.eligible_force_base_choices(fi.owner):
            if fi not in self.pending_force_base_choices:
                self.pending_force_base_choices.append(fi)
            return
        self.resolve_force_base_choice(fi, None)

    def resolve_force_base_choice(
            self,
            fi: ForceInstance,
            card_iid: int | None,
            replace_base_iid: int | None = None,
    ) -> CardInstance | None:
        owner = fi.owner
        chosen = None
        if card_iid is None:
            choices = self.eligible_force_base_choices(owner)
            chosen = choices[0] if choices else None
        else:
            for ci in owner.deck:
                if ci.iid == card_iid:
                    chosen = ci
                    break
            if chosen is None:
                raise IllegalActionError("chosen force base card is not in deck")
            if chosen.card.type is not CardType.B_MINION:
                raise IllegalActionError("force base choice must be a B-Minion")
        if chosen is not None:
            if len(owner.base) >= BASE_CAP and replace_base_iid is None:
                replace_base_iid = owner.base[0].iid
            self._make_base_space(owner, replace_base_iid)
            owner.deck.remove(chosen)
            chosen.area = AreaType.BASE
            chosen.rested = False
            owner.base.append(chosen)
        if fi in self.pending_force_base_choices:
            self.pending_force_base_choices.remove(fi)
        self.rng.shuffle(owner.deck)
        self.draw(owner, 1)
        return chosen

    def install_forces(self, player: Player, force_instances: list[ForceInstance]) -> None:
        player.forces = force_instances
        total_force_hp = sum(fi.force.initial_life for fi in force_instances)
        player.life = max(4, 12 - total_force_hp)
        for fi in force_instances:
            if fi.force.passive is not None:
                fi.force.passive(fi, self)

    @staticmethod
    def player_selected_force(player: Player, force_id: str) -> bool:
        return any(fi.force.id == force_id for fi in player.forces)

    @staticmethod
    def destroyed_forces_count(player: Player) -> int:
        return sum(1 for fi in player.forces if fi.destroyed)

    def _player_damage_marker(self) -> str:
        return f"turn:player_damaged:{self.state.turn}:{self.state.active_idx}"

    def player_was_damaged_this_turn(self, player: Player) -> bool:
        return self._player_damage_marker() in player.flags

    def grant_force_ability(self, source: CardInstance, force_id: str) -> None:
        from zz.forces import ALL_FORCES

        if source.area is not AreaType.FIELD or source not in source.owner.field:
            raise IllegalActionError("force ability can only be granted to a field minion")
        if force_id not in ALL_FORCES:
            raise IllegalActionError(f"unknown force ability: {force_id}")
        self._remove_granted_force_ability(source)
        source.flags = {
            flag for flag in source.flags
            if not flag.startswith("granted_force_ability:")
        }
        source.flags.add(f"granted_force_ability:{force_id}")
        self._register_granted_force_ability(source, force_id)

    def _remove_granted_force_ability(self, source: CardInstance) -> None:
        self._passive_modifiers = [
            (kind, fn) for kind, fn in self._passive_modifiers
            if getattr(fn, "_granted_force_source_iid", None) != source.iid
        ]

    def _register_granted_force_ability(self, source: CardInstance, force_id: str) -> None:
        from zz.forces import ALL_FORCES

        force = ALL_FORCES[force_id]
        if force.passive is None:
            raise IllegalActionError(f"force has no unique passive ability: {force_id}")
        proxy = _GrantedForceAbilitySource(source, force)
        start = len(self._passive_modifiers)
        force.passive(proxy, self)
        for _, fn in self._passive_modifiers[start:]:
            fn._granted_force_source_iid = source.iid

    def rebind_passive_modifiers(self) -> None:
        self._passive_modifiers = []
        for player in self.state.players:
            for fi in player.forces:
                if fi.force.passive is not None:
                    fi.force.passive(fi, self)
            for source in player.field:
                for flag in source.flags:
                    if flag.startswith("granted_force_ability:"):
                        self._register_granted_force_ability(source, flag.split(":", 1)[1])

    def _bp_dp_bonus_for(self, ci: CardInstance) -> tuple[int, int]:
        if ci.area is not AreaType.FIELD:
            return 0, 0
        bp = dp = 0
        for kind, fn in self._passive_modifiers:
            if kind == "force_passive":
                b, d = fn(ci, self.state)
                bp += b
                dp += d
        for modifier in self._turn_stat_modifiers:
            if self._turn_stat_modifier_matches(ci, modifier):
                bp += int(modifier.get("bp_delta") or 0)
                dp += int(modifier.get("dp_delta") or 0)
        for player in self.state.players:
            for source in player.field:
                if source.area is not AreaType.FIELD:
                    continue
                if source.card.aura is None:
                    continue
                b, d = source.card.aura(source, ci, self.state)
                bp += b
                dp += d
        return bp, dp

    def _turn_stat_modifier_matches(self, ci: CardInstance, modifier: dict[str, Any]) -> bool:
        if ci.area is not AreaType.FIELD:
            return False
        controller_idx = modifier.get("controller_idx")
        if not isinstance(controller_idx, int) or controller_idx < 0 or controller_idx >= len(self.state.players):
            return False
        controller = self.state.players[controller_idx]
        target_kind = modifier.get("target_kind")
        if target_kind == "enemy_minion" and ci.owner is controller:
            return False
        if target_kind == "ally_minion" and ci.owner is not controller:
            return False
        if target_kind not in {"enemy_minion", "ally_minion", "any_minion"}:
            return False
        card = ci.card
        total_cost = sum(card.cost.values())
        max_cost = modifier.get("max_cost")
        min_cost = modifier.get("min_cost")
        if max_cost is not None and total_cost > int(max_cost):
            return False
        if min_cost is not None and total_cost < int(min_cost):
            return False
        max_bp = modifier.get("max_bp")
        max_dp = modifier.get("max_dp")
        if max_bp is not None:
            raw_bp = card.bp + ci.bp_mod + ci.permanent_bp_mod
            if raw_bp > int(max_bp):
                return False
        if max_dp is not None:
            raw_dp = card.dp + ci.dp_mod + ci.permanent_dp_mod
            if raw_dp > int(max_dp):
                return False
        wanted_color = modifier.get("color")
        if wanted_color is not None and self._card_color(card) is not wanted_color:
            return False
        return True

    def _card_color(self, card: Card) -> Color:
        if card.mana_color is not None:
            return card.mana_color
        for color in card.cost:
            if color is not Color.COLORLESS:
                return color
        return Color.COLORLESS

    def _color_value(self, color: Color | str | None) -> Color | None:
        if color is None or isinstance(color, Color):
            return color
        if color in Color.__members__:
            return Color[color]
        return Color(color)

    def effective_bp(self, ci: CardInstance) -> int:
        bonus_bp, _ = self._bp_dp_bonus_for(ci)
        blessing_bp = sum(mana.card.bp for mana in ci.blessings)
        raw_bp = ci.card.bp + ci.bp_mod + ci.permanent_bp_mod + blessing_bp
        return max(0, raw_bp + bonus_bp)

    def effective_dp(self, ci: CardInstance) -> int:
        _, bonus_dp = self._bp_dp_bonus_for(ci)
        blessing_dp = sum(mana.card.dp for mana in ci.blessings)
        raw_dp = ci.card.dp + ci.dp_mod + ci.permanent_dp_mod + blessing_dp
        return max(0, raw_dp + bonus_dp)

    def _fire_turn_start_hooks(self) -> None:
        for kind, fn in self._passive_modifiers:
            if kind == "turn_start_hook":
                fn()

    def _fire_turn_end_hooks(self) -> None:
        for kind, fn in self._passive_modifiers:
            if kind == "turn_end_hook":
                fn()
        pending = self._delayed_turn_end_effects
        self._delayed_turn_end_effects = []
        active = self.state.active
        for player, fn in pending:
            if player is active:
                fn()
            else:
                self._delayed_turn_end_effects.append((player, fn))

    def schedule_turn_end_effect(self, player: Player, fn: Callable[[], None]) -> None:
        self._delayed_turn_end_effects.append((player, fn))

    def _fire_siren_mana_hooks(self, event_kind: str, ci: CardInstance) -> None:
        for kind, fn in list(self._passive_modifiers):
            if kind == "siren_mana_hook":
                fn(event_kind, ci, self.state)

    def _force_reduced_player_damage(self, player: Player, amount: int, source, damage_kind: str) -> int:
        source_kind = damage_kind if (
            damage_kind == "minion_dp"
            and isinstance(source, CardInstance)
            and source.owner is not player
            and source.card.type in (CardType.F_MINION, CardType.B_MINION)
        ) else ""
        for kind, fn in self._passive_modifiers:
            if kind == "player_dmg_reduce_from_minion":
                amount = fn(amount, source_kind, player, source)
        return amount
