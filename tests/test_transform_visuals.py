import json
from pathlib import Path

import pytest

from tests.test_ex02_cards import ORIGINAL_BY_VARIANT, _original_spec
from tests.test_frontend_atomic_zone_transitions import _run
from tools.run_semantic_scenario import ScenarioRunner
from zz.cards import CARD_REGISTRY
from zz.enums import AreaType
from zz.model import CardInstance
from zz.multiplayer.views import build_player_view
from zz.web.debug_tools import setup_debug_lab
from zz.web.session import GameSession


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "pack,scenario,action_count,before_id,after_id",
    [
        ("pc02r", "red_07_02_02r_00", 3, "red_07_02_02r_00", "red_07_02_02r_01"),
        ("pc02r", "red_04_02_02r_01", 1, "red_04_02_02r_01", "blue_04_02_02r_02"),
        ("ex02c", "green_08_02_02c_00", 3, "green_08_02_02c_00", "green_08_02_02c_01"),
        ("pc03", "purple_04_01_03_00", 2, "purple_04_01_03_00", "purple_04_01_03_01"),
    ],
)
def test_real_bless_transformation_emits_public_before_and_after_faces(
    pack, scenario, action_count, before_id, after_id,
):
    runner = ScenarioRunner(ROOT / f"tests/semantic_scenarios/{pack}/{scenario}-positive.json", ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    for action in runner.spec["actions"][:action_count]:
        result = runner._run_action(action)["state"]

    events = result["animationEvents"]
    transformations = [event for event in events if event["type"] == "transform"]
    assert len(transformations) == 1
    event = transformations[0]
    assert event["side"] == "P1" and len(event["cards"]) == 1
    entry = event["cards"][0]
    assert entry["area"] == "field"
    assert entry["before"]["cardId"] == before_id
    assert entry["after"]["cardId"] == after_id
    assert entry["before"]["iid"] == entry["after"]["iid"]
    assert entry["before"]["area"] == entry["after"]["area"] == "field"
    assert any(card["iid"] == entry["after"]["iid"] and card["cardId"] == after_id
               for card in result["players"]["human"]["field"])

    for player_id in ("player_1", "player_2"):
        view = build_player_view(runner.session, player_id=player_id, revision=1,
                                 state_hash="test", animation_events=events)
        shown = next(item for item in view["animationEvents"] if item["type"] == "transform")
        assert shown["cards"][0]["before"]["cardId"] == before_id
        assert shown["cards"][0]["after"]["cardId"] == after_id

    if scenario == "red_07_02_02r_00":
        transform_index = events.index(event)
        effect_index = next(index for index, item in enumerate(events)
                            if item["type"] == "effect"
                            and item.get("card", {}).get("cardId") == after_id)
        assert transform_index < effect_index


def test_original_ex02_card_uses_its_own_faces_for_the_same_transform_event():
    path = ROOT / "tests/semantic_scenarios/ex02c/green_08_02_02c_00-positive.json"
    runner = ScenarioRunner(path, ROOT)
    runner.spec = _original_spec(runner.spec)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    for action in runner.spec["actions"][:3]:
        result = runner._run_action(action)["state"]
    event = next(event for event in result["animationEvents"] if event["type"] == "transform")
    entry = event["cards"][0]
    assert entry["before"]["cardId"] == ORIGINAL_BY_VARIANT["green_08_02_02c_00"]
    assert entry["after"]["cardId"] == ORIGINAL_BY_VARIANT["green_08_02_02c_01"]


def test_real_transform_packet_keeps_the_old_face_until_its_animation():
    path = ROOT / "tests/semantic_scenarios/pc02r/red_07_02_02r_00-positive.json"
    runner = ScenarioRunner(path, ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    for action in runner.spec["actions"][:2]:
        runner._run_action(action)
    # The historical debug scenario starts with 15 Mana; keep the selected
    # Blessing and a legal ten-Mana board for the frontend capacity checks.
    owner = runner.session.engine.state.players[0]
    blessing_iid = runner.captures["red_bless"]
    selected = next(card for card in owner.base if card.iid == blessing_iid)
    owner.base[:] = [selected, *(card for card in owner.base if card is not selected)][:10]
    runner.state = runner.session.state_dto()
    before = runner.state
    after = runner._run_action(runner.spec["actions"][2])["state"]
    _run("const packet = " + json.dumps([before, after], ensure_ascii=True) + r""";
state = packet[0];
stageDuelState(packet[1]);
let sawTransform = false, sawNewEffect = false;
while (activeAnimationEvent || animationEventQueue.length) {
  if (activeAnimationEvent.type === 'transform') {
    sawTransform = true;
    assert.ok(state.players.human.field.some(card => card.cardId === 'red_07_02_02r_00'));
    assert.ok(isActiveTransformSourceCard(state.players.human.field.find(card => card.cardId === 'red_07_02_02r_00')));
  }
  if (activeAnimationEvent.type === 'effect' && activeAnimationEvent.card?.cardId === 'red_07_02_02r_01') {
    sawNewEffect = true;
    assert.ok(sawTransform);
    assert.ok(state.players.human.field.some(card => card.cardId === 'red_07_02_02r_01'));
  }
  tick();
}
assert.ok(sawTransform && sawNewEffect);
""")


def test_other_in_place_transform_path_emits_the_same_visual_event():
    session = GameSession(seed=12, mode="debug-card-lab")
    setup_debug_lab(session, "red_07_02_02r_00", zone="field", compact_board=True,
                    player_forces=[], opponent_forces=[])
    source = session.engine.state.players[0].field[0]
    session.engine.visual_events.clear()
    session.engine.morph_in_place(source, CARD_REGISTRY["red_07_02_02r_01"])
    events = [event for event in session.engine.visual_events if event["type"] == "transform"]
    assert len(events) == 1
    assert events[0]["cards"][0]["before"].card.id == "red_07_02_02r_00"
    assert events[0]["cards"][0]["after"].card.id == "red_07_02_02r_01"


def test_transform_snapshots_survive_later_card_and_blessing_changes():
    session = GameSession(seed=13, mode="debug-card-lab")
    setup_debug_lab(session, "red_07_02_02r_00", zone="field", compact_board=True,
                    player_forces=[], opponent_forces=[])
    engine = session.engine
    owner = engine.state.players[0]
    source = owner.field[0]
    blessing = CardInstance(CARD_REGISTRY["red_00_01_02_00"], owner,
                            iid=engine.state.allocate_iid(), area=AreaType.BLESSING)
    source.blessings.append(blessing)
    source.flags.add("preserved-flag")
    source.rested = True
    engine.visual_events.clear()
    engine.transform_card(source, CARD_REGISTRY["red_07_02_02r_01"])
    entry = next(event for event in engine.visual_events if event["type"] == "transform")["cards"][0]

    source.flags.clear()
    source.blessings.clear()
    source.rested = False
    blessing.area = AreaType.BASE
    for snapshot in (entry["before"], entry["after"]):
        assert snapshot.flags == {"preserved-flag"}
        assert snapshot.rested
        assert len(snapshot.blessings) == 1 and snapshot.blessings[0].area is AreaType.BLESSING


def test_transform_animation_holds_old_face_then_allows_following_effect():
    _run(r"""
const before = {...card(8, 'field'), cardId: 'before', manaColor: 'RED', rested: true};
const after = {...before, cardId: 'after', manaColor: 'BLUE'};
const event = {type: 'transform', side: 'P1', cards: [{area: 'field', before, after}]};
const effect = {type: 'effect', side: 'P1', card: after};
const prompt = {id: 'target', kind: 'effect_target', options: []};
state = dto(player('P1', [], [], [before]));
stageDuelState(dto(player('P1', [], [], [after]), [event, effect], prompt));
assert.equal(activeAnimationEvent.type, 'transform');
assert.equal(state.players.human.field[0].cardId, 'before');
assert.equal(activePrompt(), null);
assert.equal(isActiveTransformSourceCard(before), true);
assert.equal(isActiveTransformSourceCard({...before, iid: 9}), false);
assert.equal(isActiveTransformSourceCard({...before, ownerSide: 'P2'}), false);
const markup = renderBoardAnchoredFaceChange(event);
assert.match(markup, /board-transformation/);
assert.match(markup, /board-transformation-rays/);
assert.match(markup, /tone-blue/);
assert.match(markup, /--transformation-tilt:8deg/);
assert.doesNotMatch(markup, /EVOLVE/);
tick();
assert.equal(activeAnimationEvent.type, 'effect');
assert.equal(state.players.human.field[0].cardId, 'after');
assert.equal(isActiveTransformSourceCard(after), false);
assert.equal(activePrompt(), null);
drain();
assert.equal(activePrompt().id, 'target');
assert.equal(state.players.human.field[0].cardId, 'after');
""")


def test_consecutive_transformations_show_each_intermediate_face():
    _run(r"""
const before = {...card(8, 'field'), cardId: 'before'};
const middle = {...before, cardId: 'middle'};
const after = {...before, cardId: 'after'};
const first = {type: 'transform', side: 'P1', cards: [{area: 'field', before, after: middle}]};
const second = {type: 'transform', side: 'P1', cards: [{area: 'field', before: middle, after}]};
state = dto(player('P1', [], [], [before]));
stageDuelState(dto(player('P1', [], [], [after]), [first, second]));
assert.equal(state.players.human.field[0].cardId, 'before');
tick();
assert.equal(activeAnimationEvent, second);
assert.equal(state.players.human.field[0].cardId, 'middle');
drain();
assert.equal(state.players.human.field[0].cardId, 'after');
""")


def test_transformed_card_is_shown_before_a_following_field_exit():
    _run(r"""
const before = {...card(8, 'field'), cardId: 'before'};
const after = {...before, cardId: 'after'};
const inTrash = {...after, area: 'trash'};
const transform = {type: 'transform', side: 'P1', cards: [{area: 'field', before, after}]};
const effect = {type: 'effect', side: 'P1', card: after};
state = dto(player('P1', [], [], [before]));
stageDuelState(dto(player('P1', [], [], [], [inTrash]), [transform, effect, move(after, 'field', 'trash')]));
assert.equal(state.players.human.field[0].cardId, 'before');
tick();
assert.equal(activeAnimationEvent.type, 'effect');
assert.equal(state.players.human.field[0].cardId, 'after');
tick();
assert.equal(activeAnimationEvent.type, 'zone_move');
assert.equal(state.players.human.field.length, 0);
drain();
assert.equal(state.players.human.trash[0].cardId, 'after');
""")
