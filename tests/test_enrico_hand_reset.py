"""ZZ-11/12: both hands leave for Trash before Enrico's first draw."""
from collections import Counter

import pytest

from tests.test_public_base_rules import choose_kind, lab
from zz.cards import CARD_REGISTRY
from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_fixed_board
from zz.web.localization import card_japanese_ability


ENRICO = "colorless_07_02_01_02"


def enrico_session(owner_count, opponent_count, *, deck_count=7):
    """Counts exclude Enrico, which leaves the hand when summoned."""
    session, owner = lab(ENRICO)
    source = owner.hand[0]
    for side, count in (("P1", owner_count), ("P2", opponent_count)):
        for _ in range(count):
            add_debug_card_to_zone(session, "red_02_02_02r_00", side=side, zone="hand")
        for _ in range(deck_count):
            add_debug_card_to_zone(session, "yellow_02_02_02r_00", side=side, zone="deck")
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True, step="main")
    originals = {
        player.side.name: [card.iid for card in player.hand if card is not source]
        for player in session.engine.state.players
    }
    return session, source, originals


def assert_enrico_event_order(after, originals, *, draw_count=5):
    events = after["animationEvents"]
    draws = [index for index, event in enumerate(events) if event["type"] == "draw"]
    discards = [
        (index, event) for index, event in enumerate(events)
        if event["type"] == "zone_move" and event["fromArea"] == "hand" and event["toArea"] == "trash"
    ]
    assert [(event["side"], event["card"]["iid"]) for _, event in discards] == [
        (side, iid) for side, ids in originals.items() for iid in ids
    ]
    assert not discards or not draws or max(index for index, _ in discards) < min(draws)
    assert Counter(event["side"] for event in events if event["type"] == "draw") == Counter({
        "P1": draw_count, "P2": draw_count,
    })
    assert sum(event["type"] == "effect" and event["card"]["cardId"] == ENRICO for event in events) == 1


def test_enrico_complete_japanese_rule():
    assert card_japanese_ability(CARD_REGISTRY[ENRICO]) == (
        "【召喚時】\nお互いは手札を全て破棄する。その後、お互いはカードを5枚引く。"
    )


@pytest.mark.parametrize("counts", [(0, 0), (0, 3), (3, 0), (9, 10)])
def test_real_enrico_session_discards_both_hands_before_any_draw(counts, monkeypatch):
    session, source, originals = enrico_session(*counts)
    session.state_dto()
    real_draw = session.engine.draw
    observed = []

    def observe_draw(player, amount, **kwargs):
        if not observed:
            assert all(not player.hand for player in session.engine.state.players), "both hands must be empty before any draw"
            for owner in session.engine.state.players:
                assert [card.iid for card in owner.trash] == originals[owner.side.name]
        observed.append((player.side.name, amount))
        return real_draw(player, amount, **kwargs)

    monkeypatch.setattr(session.engine, "draw", observe_draw)
    after = choose_kind(session, "play_card", iid=source.iid)
    assert after["error"] is None
    assert observed == [("P1", 5), ("P2", 5)]
    assert_enrico_event_order(after, originals)
    for player in session.engine.state.players:
        assert len(player.hand) == 5
        assert len(player.deck) == 2
        assert [card.iid for card in player.trash] == originals[player.side.name]
        assert all(card.area is AreaType.TRASH for card in player.trash)
    assert source in source.owner.field


@pytest.mark.parametrize("deck_count", [0, 2])
def test_enrico_empty_or_short_decks_still_finish_all_discards(deck_count):
    session, source, originals = enrico_session(3, 4, deck_count=deck_count)
    session.state_dto()
    after = choose_kind(session, "play_card", iid=source.iid)
    assert after["error"] is None
    assert_enrico_event_order(after, originals, draw_count=deck_count)
    for player in session.engine.state.players:
        assert len(player.hand) == deck_count
        assert not player.deck
        assert [card.iid for card in player.trash] == originals[player.side.name]


def test_shared_owner_only_discard_hand_draw_preserves_opponent_and_records_departures():
    session, source, originals = enrico_session(3, 4)
    owner, opponent = session.engine.state.players
    owner.hand.remove(source)
    source.area = AreaType.FIELD
    owner.field.append(source)
    discarded = list(owner.hand)
    discarded[0].bp_mod = 200
    discarded[0].flags.add("turn:temporary")
    session.state_dto()
    effect = build_effect("discard_hand_draw", EffectTiming.ON_SUMMON, amount=2)
    effect.fn(source, session.engine.state, None)
    after = session.state_dto()
    transitions = [event for event in after["animationEvents"] if event["type"] in {"zone_move", "draw"}]
    assert [event["type"] for event in transitions] == ["zone_move"] * 3 + ["draw"] * 2
    assert all(event["side"] == "P1" for event in transitions)
    assert [card.iid for card in owner.trash] == originals["P1"]
    assert len(owner.hand) == 2
    assert [card.iid for card in opponent.hand] == originals["P2"]
    assert len(opponent.deck) == 7 and not opponent.trash
    assert discarded[0].bp_mod == 0 and not discarded[0].flags
