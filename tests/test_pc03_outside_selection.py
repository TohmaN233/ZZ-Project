import json
import subprocess
from pathlib import Path

import pytest

from tests.test_public_base_rules import lab, choose_kind
from zz.engine import HAND_CAP
from zz.multiplayer.views import build_player_view
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_fixed_board

REWARDS = {'blue_02_03_00_00', 'blue_03_03_00_01', 'blue_03_03_00_00'}


def setup(side='P1', arcana_side='P1', *, full=False, empty=True):
    session, p1 = lab('blue_04_01_03_00', base_count=6)
    owner = session.engine.state.players[0 if side == 'P1' else 1]
    if side == 'P2':
        add_debug_card_to_zone(session, 'blue_04_01_03_00', side=side, zone='hand')
        for _ in range(6):
            add_debug_card_to_zone(session, 'blue_00_01_02_00', side=side, zone='base')
    if arcana_side:
        add_debug_card_to_zone(session, 'colorless_04_01_03_02', side=arcana_side, zone='field')
    if empty:
        owner.deck.clear()
    else:
        owner.deck.clear()
        for card_id in ('red_02_02_02r_00', 'blue_02_03_00_00', 'green_02_02_02r_00'):
            add_debug_card_to_zone(session, card_id, side=side, zone='deck')
    if full:
        while len(owner.hand) < HAND_CAP + 1:
            add_debug_card_to_zone(session, 'red_02_02_02r_00', side=side, zone='hand')
    setup_debug_fixed_board(session, active_side=side, control_both=True, preserve_board=True, step='main')
    return session, owner


@pytest.mark.parametrize('side', ['P1', 'P2'])
@pytest.mark.parametrize('empty', [True, False])
@pytest.mark.parametrize('reward', sorted(REWARDS))
def test_outside_choice_private_and_deck_untouched(side, empty, reward):
    session, owner = setup(side, side, empty=empty)
    before = [(c.iid, c.card.id) for c in owner.deck]
    source = next(c for c in owner.hand if c.card.id == 'blue_04_01_03_00')
    assert choose_kind(session, 'play_card', iid=source.iid)['error'] is None
    prompt = session.prompt
    assert prompt['choiceKind'] == 'outside_card' and prompt['playerSide'] == side
    assert {x['cardId'] for x in prompt['options']} == REWARDS
    own = 'player_1' if side == 'P1' else 'player_2'
    other = 'player_2' if side == 'P1' else 'player_1'
    view = lambda who: build_player_view(session, player_id=who, revision=0, state_hash='test')
    assert {x['cardId'] for x in view(own)['prompt']['options']} == REWARDS
    assert not view(other).get('prompt') or not view(other)['prompt'].get('options')
    assert session.choose(prompt['id'], 'not-an-option')['error'] is not None
    assert session.prompt['id'] == prompt['id']
    chosen = next(x for x in prompt['options'] if x['cardId'] == reward)
    assert session.choose(prompt['id'], chosen['id'])['error'] is None
    assert [(c.iid, c.card.id) for c in owner.deck] == before
    assert sum(c.card.id == chosen['cardId'] for c in owner.hand) == 1
    assert not session.engine.state.players[1-session.engine.state.players.index(owner)].hand or all(c.card.id != chosen['cardId'] for c in session.engine.state.players[1-session.engine.state.players.index(owner)].hand)
    logs = view(other)['logEvents']
    assert all(t.get('cardId') != chosen['cardId'] for e in logs if e['type'] == 'effect_target' for t in e.get('targets', []))


def test_outside_choice_full_hand_uses_shared_overflow():
    session, owner = setup(full=True)
    source = next(c for c in owner.hand if c.card.id == 'blue_04_01_03_00')
    assert choose_kind(session, 'play_card', iid=source.iid)['error'] is None
    option = session.prompt['options'][0]
    assert session.choose(session.prompt['id'], option['id'])['error'] is None
    assert len(owner.hand) == HAND_CAP
    assert any(c.card.id == option['cardId'] for c in owner.trash)


@pytest.mark.parametrize('arcana_side', [None, 'P2'])
def test_opposing_or_absent_arcana_does_not_trigger(arcana_side):
    session, owner = setup(arcana_side=arcana_side)
    source = next(c for c in owner.hand if c.card.id == 'blue_04_01_03_00')
    assert choose_kind(session, 'play_card', iid=source.iid)['error'] is None
    assert session.prompt['kind'] != 'effect_target'
    assert not any(c.card.id in REWARDS for c in owner.hand)


@pytest.mark.parametrize(('card_id', 'reward'), [
    ('blue_03_02_02r_00', 'blue_02_03_01_01'),
    ('green_03_02_02r_00', 'green_02_03_01r_00'),
    ('purple_03_02_02r_01', 'purple_01_03_01_00'),
])
def test_older_named_card_generation_records_outside_origin(card_id, reward):
    session, owner = lab(card_id, base_count=8)
    source = next(c for c in owner.hand if c.card.id == card_id)
    owner.deck.clear()
    result = choose_kind(session, 'play_card', iid=source.iid)
    assert result['error'] is None
    assert any(c.card.id == reward for c in owner.hand)
    assert any(e.get('fromArea') == 'outside' and e.get('card', {}).get('cardId') == reward
               for e in result['animationEvents'])
    assert not owner.deck


@pytest.mark.parametrize("side", ["P1", "P2"])
def test_real_frontend_renders_and_selects_outside_card(side):
    session, owner = setup(side, side)
    source = next(c for c in owner.hand if c.card.id == "blue_04_01_03_00")
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    prompt = session.prompt
    js = (Path(__file__).resolve().parents[1] / "zz/web/static/app.js").read_text(encoding="utf-8")
    def function(name):
        start = js.index("function " + name + "(")
        end = js.index("\nfunction ", start + 1)
        return js[start:end]
    code = """
const prompt = JSON.parse(process.argv[1]);
const activePrompt = () => prompt, effectTargetSelectionIds = new Set();
const effectPromptMinimumCount = () => 1, effectPromptMaximumCount = () => 1;
const esc = x => String(x), promptTitle = () => '', effectPromptNote = () => '';
const localizedName = (c, fallback) => fallback, localizedCardAssetUrl = () => '';
const cardCanBeRested = () => false, t = x => x, cardById = () => null;
""" + "\n".join(function(n) for n in ("renderEffectPromptModal", "isRenderableEffectPromptTarget", "effectTargetKey", "renderEffectPromptCard")) + """
const html = renderEffectPromptModal();
console.log(JSON.stringify([...html.matchAll(/data-option="([^"]+)"/g)].map(x => x[1])));
prompt.options = [];
if (renderEffectPromptModal().includes('data-option=')) process.exit(2);
"""
    run = subprocess.run(["node", "-e", code, json.dumps(prompt)], capture_output=True, text=True, check=True)
    ids = json.loads(run.stdout)
    assert ids == [option["id"] for option in prompt["options"]]
    selected = prompt["options"][1]
    assert session.choose(prompt["id"], ids[1])["error"] is None
    assert any(c.card.id == selected["cardId"] for c in owner.hand)


@pytest.mark.parametrize("side", ["P1", "P2"])
@pytest.mark.parametrize("full", [False, True])
def test_pc01r_copy_uses_outside_origin_and_owner(side, full):
    session, owner = lab("red_04_02_01r_00", base_count=8)
    if side == "P2":
        owner = session.engine.state.players[1]
        add_debug_card_to_zone(session, "red_04_02_01r_00", side=side, zone="hand")
        for _ in range(8):
            add_debug_card_to_zone(session, "red_02_02_02r_00", side=side, zone="base")
    add_debug_card_to_zone(session, "red_02_02_02r_00", side="P1" if side == "P2" else "P2", zone="field")
    owner.deck.clear()
    if full:
        while len(owner.hand) < HAND_CAP + 1:
            add_debug_card_to_zone(session, "red_02_02_02r_00", side=side, zone="hand")
    setup_debug_fixed_board(session, active_side=side, control_both=True, preserve_board=True, step="main")
    source = next(c for c in owner.hand if c.card.id == "red_04_02_01r_00")
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    prompt = session.prompt
    target = next(o for o in prompt["options"] if o.get("cardId") == "red_02_02_02r_00")
    result = session.choose(prompt["id"], target["id"])
    assert result["error"] is None
    destination = owner.trash if full else owner.hand
    assert any(c.card.id == "red_02_02_02r_00" and c.owner is owner for c in destination)
    assert not owner.deck
    assert any(e.get("fromArea") == "outside" and e.get("card", {}).get("cardId") == "red_02_02_02r_00" for e in result["animationEvents"])


def test_pc01r_copy_has_no_target_when_no_other_minion_exists():
    session, owner = lab("red_04_02_01r_00", base_count=8)
    for player in session.engine.state.players:
        player.field.clear()
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True, step="main")
    source = next(c for c in owner.hand if c.card.id == "red_04_02_01r_00")
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    assert not session.prompt or session.prompt.get("kind") != "effect_target"
