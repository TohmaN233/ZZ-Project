"""Replay the actual browser state/animation functions, with deterministic timers."""
from pathlib import Path
import json
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "zz/web/static/app.js").read_text(encoding="utf-8")


def _source(name):
    # Function boundaries include async functions; do not substitute replay logic.
    match = re.search(rf"^(?:async )?function {name}\(", APP_SOURCE, re.MULTILINE)
    assert match, name
    end = re.search(r"^(?:async )?function \w+\(", APP_SOURCE[match.end():], re.MULTILINE)
    return APP_SOURCE[match.start():match.end() + end.start()] if end else APP_SOURCE[match.start():]


FUNCTIONS = [
    "shouldHoldStateForAnimationEvents", "cloneVisualState", "playerBySideFromState",
    "preservePreSettlementLifeTotals", "pendingVisualEvents", "animationEventNeedsHeldState",
    "animationEventSettlesVisualState", "zoneMoveSourceKey", "rememberZoneMoveSource",
    "promptWaitsForVisualSetup", "animationEventBlocksPrompt", "promptBlockedByAnimation",
    "pendingVisualStateStillNeeded", "commitPendingVisualStateIfSettled", "deckVisualTier",
    "playerAreaCards", "playerAreaCardsFromState", "pendingVisualCard", "refreshPlayerZoneCounts",
    "removeVisualCardFromArea", "addVisualCardToArea", "rememberDestroySource",
    "settleDestroyVisualState", "isRefreshVisualEvent", "settleRefreshVisualState",
    "settleHealVisualState", "settleZoneMoveVisualState", "settleDrawVisualState",
    "settleFinishedAnimationEvent", "stagePendingVisualStateForEffect", "commitPendingVisualState",
    "stageDuelState", "api", "rawActivePrompt", "activePrompt", "players", "cardsFor",
    "findPlayerBySide", "findCardByIid", "enqueueAnimationEvents", "animationEventDuration",
    "showNextAnimationEvent", "isActiveZoneMoveSourceCard", "renderHandFan", "renderBaseLane",
    "boardAnchorKey", "boardAnchorCssName", "boardSideForEventSide", "boardAnchorForZone", "cardAreaAnchorFallback",
    "boardAnchorForCardInState", "boardAnchorForCard", "boardAnchorStyle", "renderBoardAnchoredZoneMove",
]


HARNESS = r"""
const assert = require('node:assert/strict');
let state = null, pendingVisualState = null, visualStateStaged = false;
let animationEventQueue = [], activeAnimationEvent = null, animationOverlayTimer = null;
let activeAnimationSourceAnchor = null;
let stagedDuelStateQueue = [], hiddenZoneMoveSourceKeys = new Set();
let replayReadonlyMode = false, pendingChoicePromptId = null;
const AI_AUTO_VISUAL_POLL_MS = 1;
let snapshots = [], sounds = [], timers = new Map(), nextTimer = 1;
function setTimeout(fn) { const id = nextTimer++; timers.set(id, fn); return id; }
function clearTimeout(id) { timers.delete(id); }
function tick() { const entry = timers.entries().next().value; assert.ok(entry, 'animation timer'); timers.delete(entry[0]); entry[1](); check(); }
function drain() { for (let i = 0; timers.size; i++) { assert.ok(i < 50); tick(); } }
function syncUiStateFromCurrentState() {}
function activatePublicRevealIfIdle() {}
function enqueuePublicReveals() {}
function scheduleAutoStep() {}
function hasBlockingAutoVisuals() { return !!(activeAnimationEvent || animationEventQueue.length || pendingVisualState || stagedDuelStateQueue.length); }
function playBattleSfx(event) { sounds.push(event.type); }
function render() { check(); snapshots.push(structuredClone(state)); }
function t(key, params) { return params ? `${key}:${JSON.stringify(params)}` : key; }
function esc(value) { return String(value); }
let app = {querySelector() {return null;}};
function localizedCardAssetUrl() { return ''; }
function cardTitle(card) { return String(card.iid); }
function optionForCard() { return null; }
function colorPips() { return ''; }
function renderZone(title, meta, cards) { return meta + cards; }
function renderRow(cards) { return cards.map(card => renderCard(card)).join(''); }
function renderCard(card) { return `<i data-iid="${card.iid}" class="${isActiveZoneMoveSourceCard(card) ? 'hidden' : ''}"></i>`; }
function check() {
  if (!state) return;
  const ids = [];
  for (const player of players()) {
    assert.ok(player.hand.length <= 10, `hand overflow ${player.hand.length}`);
    assert.ok(player.base.length <= 10, `base overflow ${player.base.length}`);
    assert.ok(player.field.length <= 5, `field overflow ${player.field.length}`);
    assert.equal(player.handCount, player.hand.length);
    assert.equal(player.baseSummary.total, player.base.length);
    for (const area of ['hand', 'base', 'field', 'trash']) {
      for (const card of player[area]) {
        ids.push(card.iid);
        assert.equal(card.area, area, `card ${card.iid} area`);
      }
    }
    const hand = renderHandFan(player, 'bottom');
    assert.equal((hand.match(/class="hand-slot"/g) || []).length, player.hand.length);
    for (const card of player.hand) {
      if (activeAnimationEvent?.type === 'zone_move' && activeAnimationEvent.fromArea === 'hand' && activeAnimationEvent.card.iid === card.iid) continue;
      assert.ok(!isActiveZoneMoveSourceCard(card), 'no stale hidden source after re-entry');
    }
  }
  assert.equal(new Set(ids).size, ids.length, 'duplicate card instance');
}
function card(iid, area = 'hand', side = 'P1') { return {iid, area, ownerSide: side, manaColor: 'BLUE', rested: false}; }
function player(side, hand = [], base = [], field = [], trash = []) {
  const value = {side, hand, base, field, trash, deckCount: 30, life: 10, forces: []};
  refreshPlayerZoneCounts(value); return value;
}
function dto(human, events = [], prompt = null, opponent = player('P2')) {
  return {players: {human, opponent}, humanSide: 'P1', prompt, animationEvents: events};
}
function move(value, fromArea, toArea, side = 'P1') { return {type: 'zone_move', side, fromArea, toArea, card: {...value, area: toArea}}; }
function draw(cards) { return {type: 'draw', side: 'P1', count: cards.length, cards}; }
"""


def _run(script):
    functions = "\n".join(_source(name) for name in FUNCTIONS)
    # New common helpers are included when present, keeping the original test red-capable.
    for name in ("startAnimationEventVisualState", "stageNextDuelState", "captureBoardAnimationSourceAnchor"):
        if re.search(rf"^function {name}\(", APP_SOURCE, re.MULTILINE):
            functions += "\n" + _source(name)
    result = subprocess.run(["node"], input=HARNESS + functions + script, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_source_leaves_area_and_count_when_its_flight_starts():
    _run(r"""
const old = card(1), next = card(1, 'base');
const originalDto = dto(player('P1', [old]));
state = originalDto;
const before = structuredClone(state);
stageDuelState(dto(player('P1', [], [next]), [move(old, 'hand', 'base')]));
check();
assert.equal(state.players.human.handCount, 0, 'departed card still counted during flight');
assert.equal(state.players.human.baseSummary.total, 0);
assert.deepEqual(originalDto, before, 'server snapshot must stay immutable');
drain();
assert.deepEqual(state.players.human.base.map(c => c.iid), [1]);
""")


def test_new_response_waits_for_prior_animation_snapshot_boundary():
    _run(r"""
const old = card(1), mana = card(1, 'base'), incoming = card(2);
state = dto(player('P1', [old]));
stageDuelState(dto(player('P1', [], [mana]), [move(old, 'hand', 'base')]));
stageDuelState(dto(player('P1', [incoming], [mana]), [draw([incoming])]));
check();
assert.equal(activeAnimationEvent.type, 'zone_move');
tick();
assert.equal(activeAnimationEvent.type, 'draw');
check();
assert.deepEqual(state.players.human.base.map(c => c.iid), [1]);
assert.deepEqual(state.players.human.hand, [], 'future response published before draw');
drain();
assert.deepEqual(state.players.human.hand.map(c => c.iid), [2]);
assert.deepEqual(sounds, ['zone_move', 'draw']);
""")


def test_api_does_not_commit_final_snapshot_while_old_events_are_live():
    _run(r"""
(async () => {
  const old = card(1), mana = card(1, 'base'), incoming = card(2);
  state = dto(player('P1', [old]));
  stageDuelState(dto(player('P1', [], [mana]), [move(old, 'hand', 'base')]));
  const ZZApiResponse = dto(player('P1', [incoming], [mana]), [draw([incoming])]);
  globalThis.ZZApi = {request: async () => ({state: ZZApiResponse})};
  await api('/api/state');
  assert.equal(state.players.human.base.length, 0, 'api published old final state during flight');
  drain(); check();
})().catch(error => { console.error(error); process.exitCode = 1; });
""")


def test_draw_two_finishes_before_discard_prompt_opens():
    _run(r"""
const source = card(1), first = card(2), second = card(3);
state = dto(player('P1', [source]), [], {id: 1, kind: 'main_action'});
const prompt = {id: 2, kind: 'effect_target', choiceKind: 'hand_card', minTargets: 2, maxTargets: 2};
stageDuelState(dto(player('P1', [first, second], [], [card(1, 'field')]), [
  move(source, 'hand', 'field'), {type:'effect', side:'P1', card: card(1, 'field')}, draw([first, second])
], prompt));
assert.equal(activePrompt(), null, 'stale main action cannot be usable during transition');
tick(); assert.equal(activeAnimationEvent.type, 'effect'); assert.equal(activePrompt(), null);
tick(); assert.equal(activeAnimationEvent.type, 'draw'); assert.equal(activePrompt(), null);
assert.equal(state.players.human.hand.length, 0);
tick(); assert.equal(activePrompt().id, 2);
assert.deepEqual(state.players.human.hand.map(c => c.iid), [2, 3]);
""")


@pytest.mark.parametrize("area", ["base", "field"])
def test_full_area_replacement_never_renders_extra_card(area):
    cap = 10 if area == "base" else 5
    _run(f"""
const area = {area!r}, originals = Array.from({{length: {cap}}}, (_, index) => card(index + 1, area));
const incoming = card(100), outgoing = originals[0];
const current = player('P1', [incoming]); current[area] = originals; refreshPlayerZoneCounts(current);
state = dto(current);
const next = player('P1', [], [], [], [card(outgoing.iid, 'trash')]);
next[area] = [...originals.slice(1), card(100, area)]; refreshPlayerZoneCounts(next);
stageDuelState(dto(next, [move(outgoing, area, 'trash'), move(incoming, 'hand', area)]));
check(); drain(); check();
assert.equal(state.players.human[area].length, {cap});
assert.equal(state.players.human.trash[0].iid, outgoing.iid);
""")


def test_full_hand_mulligan_draw_and_remove_keep_counts_and_reentered_card_visible():
    _run(r"""
const originals = Array.from({length: 10}, (_, index) => card(index + 1));
state = dto(player('P1', originals));
// The same instance can be drawn again after it returns to the shuffled deck.
const next = player('P1', [...originals.slice(2), card(1), card(11)]);
const events = [move(originals[0], 'hand', 'deck'), move(originals[1], 'hand', 'deck'), draw([card(1), card(11)])];
stageDuelState(dto(next, events)); check(); drain(); check();
assert.equal(state.players.human.handCount, 10);
const after = player('P1', next.hand.filter(c => c.iid !== 1), [], [], [card(1, 'trash')]);
stageDuelState(dto(after, [move(card(1), 'hand', 'trash')]));
assert.equal(state.players.human.handCount, 9); drain(); check();
""")


def test_control_transfer_removes_card_from_actual_source_player():
    _run(r"""
const source = card(1, 'field', 'P2'), target = card(1, 'field', 'P1');
state = dto(player('P1'), [], null, player('P2', [], [], [source]));
stageDuelState(dto(player('P1', [], [], [target]), [move(target, 'field', 'field')], null, player('P2')));
check(); drain(); check();
assert.equal(state.players.opponent.field.length, 0);
assert.equal(state.players.human.field[0].ownerSide, 'P1');
""")


def test_three_fast_api_responses_cannot_replay_draws_onto_a_future_full_hand():
    _run(r"""
(async () => {
  const originals = Array.from({length: 8}, (_, index) => card(index + 1));
  state = dto(player('P1', originals));
  const first = [card(9), card(10)], second = [card(11), card(12)];
  const afterFirst = player('P1', [...originals, ...first]); afterFirst.deckCount = 28;
  stageDuelState(dto(afterFirst, [draw(first)]));
  const afterDiscard = player('P1', originals, [], [], first.map(c => card(c.iid, 'trash')));
  afterDiscard.deckCount = 28;
  globalThis.ZZApi = {request: async () => ({state: dto(afterDiscard, first.map(c => move(c, 'hand', 'trash')))})};
  await api('/api/choose');
  const afterSecond = player('P1', [...originals, ...second], [], [], afterDiscard.trash);
  afterSecond.deckCount = 26;
  ZZApi.request = async () => ({state: dto(afterSecond, [draw(second)])});
  await api('/api/state');
  ZZApi.request = async () => ({state: dto(afterSecond, [{type: 'effect', side: 'P1', card: second[0]}])});
  await api('/api/state');
  // Old implementation replays draw(9,10) against the full future hand(1..8,11,12).
  drain(); check();
  assert.deepEqual(state.players.human.hand.map(c => c.iid), [...originals, ...second].map(c => c.iid));
  assert.equal(state.players.human.deckCount, 26);
  assert.deepEqual(sounds, ['draw', 'zone_move', 'zone_move', 'draw', 'effect']);
})().catch(error => { console.error(error); process.exitCode = 1; });
""")


def test_three_fast_api_responses_cannot_replay_mana_entry_onto_a_future_full_base():
    _run(r"""
(async () => {
  const originals = Array.from({length: 10}, (_, index) => card(index + 1, 'base'));
  const first = card(11), second = card(12);
  state = dto(player('P1', [first, second], originals));
  const afterFirst = player('P1', [second], [...originals.slice(1), card(11, 'base')], [], [card(1, 'trash')]);
  stageDuelState(dto(afterFirst, [move(originals[0], 'base', 'trash'), move(first, 'hand', 'base')]));
  const afterReturn = player('P1', [second, first], originals.slice(1), [], afterFirst.trash);
  globalThis.ZZApi = {request: async () => ({state: dto(afterReturn, [move(card(11, 'base'), 'base', 'hand')])})};
  await api('/api/choose');
  const afterSecond = player('P1', [first], [...originals.slice(1), card(12, 'base')], [], afterFirst.trash);
  ZZApi.request = async () => ({state: dto(afterSecond, [move(second, 'hand', 'base')])});
  await api('/api/state');
  ZZApi.request = async () => ({state: dto(afterSecond, [{type: 'effect', side: 'P1', card: second}])});
  await api('/api/state');
  drain(); check();
  assert.equal(state.players.human.baseSummary.total, 10);
  assert.deepEqual(state.players.human.hand.map(c => c.iid), [11]);
})().catch(error => { console.error(error); process.exitCode = 1; });
""")


def test_same_instance_can_leave_and_reenter_hand_before_later_effect_animation():
    _run(r"""
const original = card(1), incoming = card(2);
state = dto(player('P1', [original]));
stageDuelState(dto(player('P1', [original, incoming]), [
  move(original, 'hand', 'deck'), draw([original, incoming]), {type: 'effect', side: 'P1', card: original}
]));
tick(); tick();
assert.equal(activeAnimationEvent.type, 'effect');
check();
assert.ok(!isActiveZoneMoveSourceCard(state.players.human.hand[0]));
drain();
""")


def test_response_without_events_is_also_delivered_after_active_batch():
    _run(r"""
state = dto(player('P1'));
const incoming = card(1);
stageDuelState(dto(player('P1', [incoming]), [draw([incoming])]));
const noEvents = dto(player('P1', [incoming]), [], {id: 3, kind: 'main_action'});
noEvents.players.human.life = 7;
stageDuelState(noEvents);
assert.equal(state.players.human.life, 10);
assert.equal(activePrompt(), null);
drain(); assert.equal(state.players.human.life, 7); assert.equal(activePrompt().id, 3);
""")


def test_real_griphone_session_draws_then_opens_discard_and_replays_discards():
    from tools.run_semantic_scenario import ScenarioRunner

    runner = ScenarioRunner(ROOT / "tests/semantic_scenarios/pc02r/white_07_02_02r_00-positive.json", ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    before = runner.state
    summon = runner._run_action(runner.spec["actions"][0])["state"]
    discard = runner._run_action(runner.spec["actions"][1])["state"]
    assert summon["prompt"]["kind"] == "effect_target"
    assert sum(event.get("count", 0) for event in summon["animationEvents"] if event["type"] == "draw") == 2
    _run("const packet = " + json.dumps([before, summon, discard], ensure_ascii=True) + r""";
state = packet[0];
stageDuelState(packet[1]);
assert.equal(activePrompt(), null);
while (activeAnimationEvent || animationEventQueue.length) {
  assert.equal(activePrompt(), null, 'discard must wait for the actual draw animations');
  tick();
}
assert.equal(activePrompt().id, packet[1].prompt.id);
assert.ok(sounds.includes('draw'));
assert.deepEqual(state.players.human.hand, packet[1].players.human.hand);
stageDuelState(packet[2]);
check(); drain(); check();
assert.deepEqual(state.players.human.hand, packet[2].players.human.hand);
assert.deepEqual(state.players.human.trash, packet[2].players.human.trash);
""")


def test_new_public_restriction_kinds_have_all_three_language_labels():
    start = APP_SOURCE.index("const ACTIVE_EFFECT_COPY = {")
    end = APP_SOURCE.index("\nconst KEYWORD_COPY", start)
    copy = APP_SOURCE[start:end]
    script = "const assert = require('node:assert/strict');\n" + copy + _source("activeEffectKindLabel") + r"""
let language = 'zh';
function currentLanguage() { return language; }
for (const lang of ['zh', 'ja', 'en']) {
  language = lang;
  for (const kind of ['cannot_attack_player', 'cannot_move']) {
    assert.ok(ACTIVE_EFFECT_COPY[lang][kind]);
    assert.equal(activeEffectKindLabel(kind), ACTIVE_EFFECT_COPY[lang][kind]);
  }
}
"""
    result = subprocess.run(["node"], input=script, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_platoona_full_hand_discards_before_draw_and_never_overflows():
    from tests.test_public_base_rules import lab, choose_kind
    from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_fixed_board

    session, owner = lab("colorless_03_02_02r_03")
    source = owner.hand[0]
    for _ in range(9):
        add_debug_card_to_zone(session, "red_02_02_02r_00", side="P1", zone="hand")
        add_debug_card_to_zone(session, "yellow_02_02_02r_00", side="P1", zone="deck")
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True, step="main")
    before = session.state_dto()
    selection = choose_kind(session, "play_card", iid=source.iid)
    choices = [o["id"] for o in session.prompt["options"] if "cardIid" in o]
    assert len(choices) == 9
    after = session.choose(session.prompt["id"], choices[0], {"selectedOptionIds": choices})
    assert after["error"] is None
    transitions = [event for event in after["animationEvents"] if event["type"] in {"draw", "zone_move"}]
    first_draw = next(i for i, event in enumerate(transitions) if event["type"] == "draw")
    assert first_draw == 9
    assert all(e["fromArea"] == "hand" and e["toArea"] == "trash" for e in transitions[:first_draw])
    _run("const packet = " + json.dumps([before, selection, after], ensure_ascii=True) + r""";
state = packet[0];
stageDuelState(packet[1]); drain(); check();
assert.equal(state.players.human.hand.length, 9);
stageDuelState(packet[2]); check(); drain(); check();
assert.deepEqual(state.players.human.hand, packet[2].players.human.hand);
assert.deepEqual(state.players.human.trash, packet[2].players.human.trash);
assert.equal(state.players.human.hand.length, 9);
""")


def test_departure_animation_keeps_measured_source_position_after_zone_removal():
    _run(r"""
const old = card(1), next = card(1, 'base');
state = dto(player('P1', [old]));
app.querySelector = selector => {
  if (selector === '[data-board-card-anchor="P1:card:1"]') {
    return {getBoundingClientRect: () => ({left: 400, top: 150, width: 100, height: 140})};
  }
  if (selector === '.board-animation-layer.live') {
    return {getBoundingClientRect: () => ({left: 100, top: 50, width: 1000, height: 500})};
  }
  return null;
};
stageDuelState(dto(player('P1', [], [next]), [move(old, 'hand', 'base')]));
assert.equal(state.players.human.hand.length, 0);
assert.equal(activeAnimationSourceAnchor.cssX, '35%');
assert.equal(activeAnimationSourceAnchor.cssY, '34%');
app.querySelector = () => null; // The next DOM render has removed the card.
const html = renderBoardAnchoredZoneMove(activeAnimationEvent);
assert.ok(html.includes('--from-x:35%; --from-y:34%;'));
drain(); assert.equal(activeAnimationSourceAnchor, null);
""")


def test_duplicate_replay_card_raises_an_error_with_instance_and_destination():
    _run(r"""
state = dto(player('P1', [card(1)]));
assert.throws(() => addVisualCardToArea(state.players.human, 'base', card(1, 'base')),
  /duplicated card 1 entering P1:base/);
assert.equal(state.players.human.base.length, 0);
""")


def test_real_full_hand_mulligan_response_keeps_every_render_within_capacity():
    from zz.web.session import GameSession

    session = GameSession(seed=712, mode="god")
    owner = session.engine.state.players[0]
    session.engine.draw(owner, 10 - len(owner.hand), record_event=False)
    before = session.state_dto()
    selected = [card.iid for card in owner.hand[:2]]
    after = session.choose(session.prompt["id"], "redraw_selected", {"selectedCardIids": selected})
    assert after["error"] is None
    _run("const packet = " + json.dumps([before, after], ensure_ascii=True) + r""";
state = packet[0]; stageDuelState(packet[1]); check(); drain(); check();
assert.equal(state.players.human.handCount, 10);
assert.deepEqual(state.players.human.hand, packet[1].players.human.hand);
assert.equal(state.players.human.deckCount, packet[1].players.human.deckCount);
""")


def test_real_full_base_force_search_replacement_response_keeps_every_render_within_capacity():
    from zz.cards import CARD_REGISTRY
    from zz.enums import AreaType, CardType
    from zz.forces import F_OUROBOROS
    from zz.model import Card, CardInstance, ForceInstance
    from zz.web.session import GameSession

    session = GameSession(seed=713, mode="god")
    owner = session.engine.state.players[0]
    token = Card(id="mana_token", name_jp="無色マナ", name_en="Mana", type=CardType.MANA_TOKEN)
    owner.base = [CardInstance(card=token, owner=owner,
                               iid=session.engine.state.allocate_iid(), area=AreaType.BASE) for _ in range(10)]
    chosen = CardInstance(card=CARD_REGISTRY["white_00_01_02_00"], owner=owner,
                          iid=session.engine.state.allocate_iid(), area=AreaType.DECK)
    owner.deck = [chosen]
    force = ForceInstance(force=F_OUROBOROS, owner=owner, life=F_OUROBOROS.initial_life)
    owner.forces = [force]
    session._clear_prompt()
    session.engine.handle_force_destroy_base_search(force)
    assert session._drain_or_prompt_force_base_choices()
    before = session.state_dto()
    choose_card = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    victim = next(option for option in session.prompt["options"] if option.get("cardIid") == owner.base[2].iid)
    replace = session.choose(session.prompt["id"], victim["id"])
    assert replace["error"] is None
    _run("const packet = " + json.dumps([before, choose_card, replace], ensure_ascii=True) + r""";
state = packet[0]; stageDuelState(packet[1]); check(); drain(); check();
stageDuelState(packet[2]); check(); drain(); check();
assert.equal(state.players.human.baseSummary.total, 10);
assert.deepEqual(state.players.human.base, packet[2].players.human.base);
assert.equal(state.players.human.deckCount, packet[2].players.human.deckCount);
""")
