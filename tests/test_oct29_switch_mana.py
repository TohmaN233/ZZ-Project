"""Real Session choices for ZZ-03/04/16, including equivalent EX02 faces."""
from copy import deepcopy

import pytest

import zz.ex02  # noqa: F401
from tests.test_public_base_rules import lab, choose_kind
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import Card, CardInstance
from zz.web.debug_tools import setup_debug_fixed_board


TIESE = ("green_02_02_02c_00", "green_02_02_EX02_00")
RONIE = ("green_03_02_02c_00", "green_03_02_EX02_00")


def add(session, owner, card, area=AreaType.HAND, *, rested=False):
    instance = CardInstance(card, owner, iid=session.engine.state.allocate_iid(),
                            area=area, rested=rested)
    getattr(owner, area.value).append(instance)
    return instance


def body(name, race=""):
    return Card(name, name, name, CardType.F_MINION, bp=100, dp=1, race_jp=race)


def prepare(session, active="P1"):
    setup_debug_fixed_board(session, active_side=active, control_both=True,
                            preserve_board=True, step="main")


def target_option(session, instance):
    return next(option for option in session.prompt["options"]
                if option.get("cardIid") == instance.iid)


@pytest.mark.parametrize("card_id", TIESE)
@pytest.mark.parametrize("event", ["native", "ice", "unrelated", "enemy", "moved", "generated"])
def test_tiese_only_native_and_friendly_ice_summon_offer_item_refresh(card_id, event):
    session, owner = lab(card_id, zone="hand" if event == "native" else "field", base_count=4)
    host = next(card for card in owner.hand + owner.field if card.card.id == card_id)
    add(session, owner, body("other-sword", "ソード"), AreaType.FIELD)
    item = owner.base[0]
    item.card = Card("item-mana", "item", "item", CardType.B_MINION, race_jp="アイテム")
    item.rested = True
    owner.base[1].rested = True  # A rested non-Item must never be selectable.
    if event == "generated":
        played = add(session, owner, Card("generate-ice", "generate", "", CardType.MAGIC,
            effects=[EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda source, state, _ctx:
                state.engine.create_field_minions(source.owner, [body("generated-ice", "氷剣")], source=source))]))
    elif event == "native":
        host.card = deepcopy(host.card)
        host.card.cost = {}
        played = host
    else:
        played = add(session, session.engine.state.players[1] if event == "enemy" else owner,
                     body("entering", "獣" if event == "unrelated" else "氷剣"),
                     AreaType.BASE if event == "moved" else AreaType.HAND)
    prepare(session, "P2" if event == "enemy" else "P1")
    if event == "moved":
        dto = choose_kind(session, "move_card", iid=played.iid, direction="base_to_field")
    else:
        dto = choose_kind(session, "play_card", iid=played.iid)
    assert dto["error"] is None
    if event in {"native", "ice"}:
        assert session.prompt["kind"] == "effect_target"
        assert session.prompt["choiceKind"] == "ally_base"
        assert [option["cardIid"] for option in session.prompt["options"]] == [item.iid]
        dto = session.choose(session.prompt["id"], target_option(session, item)["id"])
        assert dto["error"] is None
        assert not item.rested
    else:
        assert session.prompt["kind"] != "effect_target"
        assert item.rested


@pytest.mark.parametrize("card_id", TIESE)
@pytest.mark.parametrize("missing", ["another_sword", "rested_item"])
def test_tiese_requires_another_sword_and_a_rested_item(card_id, missing):
    session, owner = lab(card_id, zone="field", base_count=4)
    owner.base[0].card = Card("item", "item", "", CardType.B_MINION, race_jp="アイテム")
    owner.base[0].rested = missing != "rested_item"
    if missing != "another_sword":
        add(session, owner, body("other-sword", "ソード"), AreaType.FIELD)
    played = add(session, owner, body("ice", "氷剣"))
    prepare(session)
    assert choose_kind(session, "play_card", iid=played.iid)["error"] is None
    assert session.prompt["kind"] != "effect_target"


@pytest.mark.parametrize("card_id", RONIE)
@pytest.mark.parametrize("base_count", [9, 10])
@pytest.mark.parametrize("native", [True, False])
def test_ronie_places_only_item_b_minion_and_owner_replaces_at_ten(card_id, base_count, native):
    session, owner = lab(card_id, zone="hand" if native else "field", base_count=base_count)
    source = next(card for card in owner.hand + owner.field if card.card.id == card_id)
    item = add(session, owner, Card("item", "item", "item", CardType.B_MINION, race_jp="アイテム"))
    non_item = add(session, owner, Card("non-item", "non-item", "", CardType.B_MINION))
    item_field = add(session, owner, body("item-field", "アイテム"))
    if native:
        source.card = deepcopy(source.card)
        source.card.cost = {}
        played = source
    else:
        played = add(session, owner, body("black-swordsman", "黒の剣士"))
    placements = []
    item.card.effects.append(EffectSpec(EffectTiming.ON_PLACE_BASE,
        lambda *_: placements.append("placed")))
    prepare(session)
    assert choose_kind(session, "play_card", iid=played.iid)["error"] is None
    assert session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "hand_base_minion"
    offered = {option.get("cardIid") for option in session.prompt["options"]}
    assert item.iid in offered and non_item.iid not in offered and item_field.iid not in offered
    assert any(option.get("kind") == "effect_target_skip" for option in session.prompt["options"])
    replacement = owner.base[-1]
    result = session.choose(session.prompt["id"], target_option(session, item)["id"])
    assert result["error"] is None
    if base_count == 10:
        assert item in owner.hand  # Replacement must be selected before entry.
        assert session.prompt["kind"] == "effect_target"
        assert session.prompt["choiceKind"] == "ally_base"
        assert session.prompt["playerSide"] == owner.side.name
        assert {option["cardIid"] for option in session.prompt["options"]} == {card.iid for card in owner.base}
        result = session.choose(session.prompt["id"], target_option(session, replacement)["id"])
        assert result["error"] is None
        assert replacement not in owner.base
    else:
        assert replacement in owner.base
    assert item in owner.base and item not in owner.hand and item.rested
    assert len(owner.base) == 10
    assert not placements
    assert non_item in owner.hand and item_field in owner.hand
    moves = [event for event in result["animationEvents"] if event.get("type") == "zone_move"]
    assert any(event.get("fromArea") == "hand" and event.get("toArea") == "base"
               and event.get("card", {}).get("iid") == item.iid for event in moves)


@pytest.mark.parametrize("card_id", RONIE)
def test_ronie_full_base_can_decline_without_replacement_and_rejects_invalid_card(card_id):
    session, owner = lab(card_id, zone="field", base_count=10)
    item = add(session, owner, Card("item", "item", "", CardType.B_MINION, race_jp="アイテム"))
    played = add(session, owner, body("swordsman", "黒の剣士"))
    prepare(session)
    assert choose_kind(session, "play_card", iid=played.iid)["error"] is None
    before = (tuple(owner.base), tuple(owner.hand))
    prompt_id = session.prompt["id"]
    assert session.choose(prompt_id, "non-item-not-an-option")["error"]["code"] == "illegal_choice"
    assert (tuple(owner.base), tuple(owner.hand)) == before
    skip = next(option for option in session.prompt["options"] if option.get("kind") == "effect_target_skip")
    assert session.choose(prompt_id, skip["id"])["error"] is None
    assert (tuple(owner.base), tuple(owner.hand)) == before
    assert item in owner.hand and session.prompt["kind"] != "effect_target"


@pytest.mark.parametrize("card_id", RONIE)
def test_ronie_without_session_deferral_uses_shared_owner_replacement_selection(card_id):
    session, owner = lab(card_id, zone="field", base_count=10)
    item = add(session, owner, Card("item", "item", "", CardType.B_MINION, race_jp="アイテム"))
    replacement = owner.base[-1]
    played = add(session, owner, body("swordsman", "黒の剣士"))
    prepare(session)
    session.engine.defer_trigger_choice = None
    session.human_policy.queue_targets([item, replacement])
    assert choose_kind(session, "play_card", iid=played.iid)["error"] is None
    assert item in owner.base and replacement not in owner.base and len(owner.base) == 10


def test_ronie_replacement_prompt_belongs_to_its_p2_base_owner():
    session, original = lab(RONIE[0], zone="field", base_count=10)
    owner = session.engine.state.players[1]
    host = next(card for card in original.field if card.card.id == RONIE[0])
    original.field.remove(host)
    host.owner = owner
    owner.field.append(host)
    while len(owner.base) < 10:
        add(session, owner, Card("mana", "mana", "", CardType.B_MINION), AreaType.BASE)
    item = add(session, owner, Card("item", "item", "", CardType.B_MINION, race_jp="アイテム"))
    played = add(session, owner, body("swordsman", "黒の剣士"))
    prepare(session, "P2")
    assert choose_kind(session, "play_card", iid=played.iid)["error"] is None
    assert session.choose(session.prompt["id"], target_option(session, item)["id"])["error"] is None
    assert session.prompt["choiceKind"] == "ally_base" and session.prompt["playerSide"] == "P2"
    assert {option["cardIid"] for option in session.prompt["options"]} == {card.iid for card in owner.base}
    replacement = owner.base[-1]
    assert session.choose(session.prompt["id"], target_option(session, replacement)["id"])["error"] is None
    assert item in owner.base and replacement not in owner.base and len(original.base) == 10


def test_switch_keeps_plain_listeners_multiple_hosts_and_destroy_clauses_separate():
    session, owner = lab(TIESE[0], zone="hand", base_count=4)
    owner.hand.clear()
    owner.field.clear()
    seen = []
    listener = add(session, owner, body("plain-listener"), AreaType.FIELD)
    listener.card.effects = [EffectSpec(EffectTiming.ON_SUMMON,
        lambda _source, _state, ctx: seen.append(("plain", ctx.source.card.id)))]
    hosts = []
    for name, timing in [("summon-host", EffectTiming.ON_SUMMON), ("destroy-host", EffectTiming.ON_DESTROY)]:
        host = add(session, owner, body(name), AreaType.FIELD)
        host.card.effects = [EffectSpec(timing,
            lambda source, _state, ctx: seen.append((source.card.id, ctx.switch_source)),
            params={"ex02c_switch_races": ["氷剣"]})]
        hosts.append(host)
    unrelated = add(session, owner, body("unrelated", "獣"))
    prepare(session)
    assert choose_kind(session, "play_card", iid=unrelated.iid)["error"] is None
    assert seen == [("plain", "unrelated")]
    ice = add(session, owner, body("ice", "氷剣"))
    prepare(session)
    assert choose_kind(session, "play_card", iid=ice.iid)["error"] is None
    assert seen[1:] == [("plain", "ice"), ("summon-host", hosts[0]), ("destroy-host", hosts[1])]
    prepare(session)
    assert choose_kind(session, "move_card", iid=hosts[0].iid, direction="field_to_base")["error"] is None
    # Make room for the next summon without emitting a summon event.
    owner.field.remove(unrelated)
    unrelated.area = AreaType.TRASH
    owner.trash.append(unrelated)
    ice2 = add(session, owner, body("ice2", "氷剣"))
    prepare(session)
    assert choose_kind(session, "play_card", iid=ice2.iid)["error"] is None
    assert seen[-2:] == [("plain", "ice2"), ("destroy-host", hosts[1])]
