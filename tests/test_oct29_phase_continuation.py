"""Interactive phase choices must finish before refresh, draw and lock expiry."""
from copy import deepcopy

import pytest

from tests.test_ex02c_link_activation_combat import eugeo_switch_board, put
from tests.test_public_base_rules import choose_kind
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Step
from zz.model import Card


@pytest.mark.parametrize("use_first", [True, False])
def test_all_start_choices_finish_before_standby_advances_and_mana_unlocks(use_first):
    session, _owner, _source, target = eugeo_switch_board()
    engine = session.engine
    owner = target.owner
    target.card = deepcopy(target.card)
    observations = []
    target.card.effects.extend([
        EffectSpec(EffectTiming.TURN_START,
            lambda _source, state, _ctx: observations.append(state.step),
            condition=lambda source, _state, ctx: ctx.controller is source.owner,
            optional=True, active_areas=(AreaType.FIELD,)),
        build_effect("refresh_targets", EffectTiming.TURN_START,
            target_kind="ally_minion", min_targets=1, max_targets=1,
            condition=lambda source, _state, ctx: ctx.controller is source.owner,
            active_areas=(AreaType.FIELD,)),
    ])
    draw = put(engine, owner, Card("standby-draw", "draw", "", CardType.B_MINION), AreaType.DECK)
    owner.deck.remove(draw)
    owner.deck.insert(0, draw)
    magic = put(engine, owner, Card("mana-refresh", "refresh", "", CardType.MAGIC,
        effects=[build_effect("refresh_targets", EffectTiming.ON_CAST_MAGIC,
            target_kind="ally_minion", min_targets=1, max_targets=1)]), AreaType.HAND)
    assert choose_kind(session, "end_turn")["error"] is None
    assert engine.state.step is Step.START
    assert engine.has_pending_standby and draw in owner.deck
    assert session.prompt["kind"] == "optional_effect"
    assert session.choose(session.prompt["id"], "yes" if use_first else "no")["error"] is None
    assert observations == ([Step.START] if use_first else [])
    assert engine.state.step is Step.START and draw in owner.deck
    assert session.prompt["kind"] == "effect_target"
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert engine.state.step is Step.MANA and not engine.has_pending_standby
    assert draw in owner.hand and target.rested
    assert choose_kind(session, "place_colorless_mana")["error"] is None
    assert choose_kind(session, "play_card", iid=magic.iid)["error"] is None
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert not target.rested
