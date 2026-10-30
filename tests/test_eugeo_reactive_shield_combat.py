"""Real debug-board combat against Reactive Shield and a 1200 BP blocker."""

from tests.test_public_base_rules import choose_kind
from test_frontend_fx import BROWSER, duel_fx_fixture
from test_frontend_oct29_feedback import PAGE, _run_live_page
from zz.enums import AreaType
from zz.web.debug_tools import add_debug_card_to_zone, replace_debug_forces, setup_debug_fixed_board
from zz.web.session import GameSession


def setup_battle(*, switch_lock):
    session = GameSession(seed=901, mode="god")
    setup_debug_fixed_board(session, active_side="P1", control_both=True)
    replace_debug_forces(session, "P1", ["force_sho", "force_chi"])
    replace_debug_forces(session, "P2", ["force_sho", "force_chi"])
    engine = session.engine
    owner, opponent = engine.state.players
    source_iid = add_debug_card_to_zone(session, "green_08_02_02c_00", side="P1", zone="field")["added"]["iid"]
    eugeo = next(ci for ci in owner.field if ci.iid == source_iid)
    engine._make_base_space(owner, owner.base[-1].iid)
    sword_iid = add_debug_card_to_zone(session, "green_00_01_02c_01", side="P1", zone="base")["added"]["iid"]
    owner.movement_right_count = 2
    session._clear_prompt()
    session._prompt_main_action()
    assert choose_kind(session, "bless", mana_iid=sword_iid, target_iid=eugeo.iid)["error"] is None
    assert eugeo.card.id == "green_08_02_02c_01"
    blocker = next(ci for ci in opponent.field if ci.card.id == "blue_09_02_02_00")
    engine.rest_target(blocker)
    if switch_lock:
        add_debug_card_to_zone(session, "green_00_01_00_00", side="P1", zone="base")
        kirito_iid = add_debug_card_to_zone(session, "green_04_02_02c_00", side="P1", zone="hand")["added"]["iid"]
        session._clear_prompt()
        session._prompt_main_action()
        assert choose_kind(session, "play_card", iid=kirito_iid)["error"] is None
        assert not engine.refresh_target(blocker)
    shield_iid = add_debug_card_to_zone(session, "white_02_03_00_00", side="P2", zone="hand")["added"]["iid"]
    eugeo.summoning_sickness = False
    engine.state.present_at_turn_start.add(eugeo.iid)
    session._clear_prompt()
    session._prompt_main_action()
    assert choose_kind(session, "attack", attacker_iid=eugeo.iid)["error"] is None
    target = next(o for o in session.prompt["options"] if o.get("kind") == "player")
    assert session.choose(session.prompt["id"], target["id"])["error"] is None
    assert session.prompt["kind"] == "flash_action" and session.prompt["playerSide"] == "P2"
    assert choose_kind(session, "play_card", iid=shield_iid)["error"] is None
    assert session.prompt["kind"] == "effect_target"
    option = next(o for o in session.prompt["options"] if o.get("cardIid") == blocker.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert engine.effective_bp(eugeo) == 1000
    assert engine.effective_bp(blocker) == 1200
    return session, eugeo, blocker


def test_shield_boosts_but_cannot_activate_locked_default_blocker():
    session, eugeo, blocker = setup_battle(switch_lock=True)
    assert blocker.rested
    while session.prompt["kind"] == "flash_action":
        assert choose_kind(session, "flash_pass")["error"] is None
    assert session.prompt["kind"] == "blocker"
    assert blocker.iid not in {o.get("cardIid") for o in session.prompt["options"]}
    assert eugeo.area is AreaType.FIELD


def test_shield_allows_unlocked_default_blocker_to_win_its_real_battle():
    session, eugeo, blocker = setup_battle(switch_lock=False)
    assert not blocker.rested
    while session.prompt["kind"] == "flash_action":
        assert choose_kind(session, "flash_pass")["error"] is None
    assert session.prompt["kind"] == "blocker"
    option = next(o for o in session.prompt["options"] if o.get("cardIid") == blocker.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    assert blocker.area is AreaType.FIELD
    assert eugeo.area is AreaType.TRASH
    battle = next(event for event in reversed(result["logEvents"]) if event.get("type") == "block")["battle"]
    assert battle == {
        "attackerBp": 1000,
        "blockerBp": 1200,
        "outcomeOverride": False,
        "wouldDestroyAttacker": True,
        "wouldDestroyBlocker": False,
        "attackerAreaAfterBattle": "trash",
        "blockerAreaAfterBattle": "field",
    }


def test_battle_log_reports_a_rule_override_instead_of_only_comparing_bp():
    session, eugeo, blocker = setup_battle(switch_lock=False)
    eugeo.flags.add("turn:pc01r_always_wins_battle")
    while session.prompt["kind"] == "flash_action":
        assert choose_kind(session, "flash_pass")["error"] is None
    option = next(o for o in session.prompt["options"] if o.get("cardIid") == blocker.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    battle = next(event for event in reversed(result["logEvents"]) if event.get("type") == "block")["battle"]
    assert battle["outcomeOverride"] is True
    assert battle["attackerBp"] == 1000 and battle["blockerBp"] == 1200
    assert battle["wouldDestroyBlocker"] and not battle["wouldDestroyAttacker"]
    assert battle["attackerAreaAfterBattle"] == "field" and battle["blockerAreaAfterBattle"] == "trash"


def test_battle_log_distinguishes_a_protected_loser_from_a_failed_comparison():
    from tests.test_ex02c_link_activation_combat import block_attack, put
    from tests.test_public_base_rules import lab
    from zz.enums import CardType
    from zz.model import Card

    session, owner = lab("red_06_02_02c_00", zone="field", base_count=1)
    engine = session.engine
    protected = owner.field[0]  # Heathcliff cannot be destroyed on its own turn.
    blocker = put(engine, engine.state.opponent, Card("test-blocker", "blocker", "", CardType.F_MINION, bp=1200))
    protected.summoning_sickness = False
    engine.state.present_at_turn_start.add(protected.iid)
    block_attack(session, protected, blocker)
    battle = next(event for event in reversed(session.state_dto()["logEvents"]) if event.get("type") == "block")["battle"]
    assert battle["attackerBp"] < battle["blockerBp"] and battle["wouldDestroyAttacker"]
    assert battle["attackerAreaAfterBattle"] == battle["blockerAreaAfterBattle"] == "field"


def test_real_block_response_removes_destroyed_eugeo_from_browser(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        import pytest
        pytest.skip("Chrome is required for the actual battle response")
    session, eugeo, blocker = setup_battle(switch_lock=False)
    while session.prompt["kind"] == "flash_action":
        assert choose_kind(session, "flash_pass")["error"] is None
    assert session.prompt["kind"] == "blocker"
    initial = session.state_dto()
    initial["animationEvents"] = []
    blocker_option = next(o["id"] for o in session.prompt["options"] if o.get("cardIid") == blocker.iid)
    fixture = {**duel_fx_fixture, "fixture": {**duel_fx_fixture["fixture"],
        "main": initial, "blockerOption": blocker_option, "eugeoIid": eugeo.iid,
        "blockerIid": blocker.iid}}
    old_session = fixture["handler"].app.session
    fixture["handler"].app.session = session
    body = r'''
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  const waitFor=async(check,label)=>{
    const until=performance.now()+10000;
    while(performance.now()<until){if(check())return;await delay(25);}
    throw new Error(label+JSON.stringify({prompt:rawActivePrompt(),active:activeAnimationEvent?.type,
      pending:!!pendingVisualState,error:state.error}));
  };
  render();
  assert(activePrompt()?.kind==="blocker","actual blocker prompt is available");
  assert(state.players.human.field.some(c=>c.iid===fixture.eugeoIid),"Eugeo starts on the field");
  choose(fixture.blockerOption);
  await waitFor(()=>rawActivePrompt()?.kind!=="blocker","real blocking response arrives");
  await waitFor(()=>!activeAnimationEvent&&!pendingVisualState&&!stagedDuelStateQueue.length,
    "block, destroy and destroy-effect animations settle");
  assert(!state.error,"the blocking action succeeds");
  assert(!state.players.human.field.some(c=>c.iid===fixture.eugeoIid),"destroyed Eugeo leaves the displayed field");
  assert(state.players.human.trash.some(c=>c.iid===fixture.eugeoIid),"destroyed Eugeo appears in Trash");
  assert(state.players.opponent.field.some(c=>c.iid===fixture.blockerIid),"the winning blocker remains on the field");
  assert(!app.querySelector('[data-board-card-anchor="P1:card:'+fixture.eugeoIid+'"]'),
    "the rendered field no longer shows Eugeo");
  app.querySelector("[data-log-toggle]").click();
  const log=app.querySelector(".battle-log-list").textContent;
  assert(log.includes("BP 1000")&&log.includes("BP 1200"),"the battle log shows the actual compared BP");
  return {ok:true};'''
    page = PAGE.replace("settings.reducedMotion=false", "settings.reducedMotion=true").replace("await ZZFx.prepare();", "")
    try:
        _run_live_page(fixture, tmp_path, page.replace("BODY", body))
    finally:
        fixture["handler"].app.session = old_session
