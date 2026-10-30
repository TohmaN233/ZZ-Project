"""Browser regressions for the visible impact, arrival and detail feedback."""

import base64
import html
import json
import subprocess

import pytest

from test_frontend_fx import BROWSER, _run_fx_test_page, duel_fx_fixture


PAGE = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;
window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),16);
window.cancelAnimationFrame=clearTimeout;</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE;
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  catalog=fixture.catalog;state=fixture.main;appView="duel";settings.duelScale=100;settings.reducedMotion=false;
  state.pendingAttack=null;setAppHtml(renderDuelView());await ZZFx.prepare();
  const start=event=>{ZZFx.onEventStart(event,1200);activeAnimationEvent=event;setAppHtml(renderDuelView());};
  const end=event=>{ZZFx.onEventEnd(event);activeAnimationEvent=null;setAppHtml(renderDuelView());};
  BODY
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''


def _run_live_page(fixture, tmp_path, page):
    """Drive actual HTTP choices and queued animations on the browser clock."""
    child = page.replace("ORIGIN", fixture["origin"]).replace("FIXTURE", json.dumps(
        fixture["fixture"], ensure_ascii=False).replace("<", "\\u003c"))
    fixture["handler"].test_document = '''<!doctype html><html><body>
<script>addEventListener("message",({data})=>{if(!data.fxPayload)return;
const node=document.createElement("script");node.id="fx-result";node.type="application/json";
node.textContent=data.fxPayload;document.body.append(node);});</script>
<iframe width="1280" height="900" style="border:0" srcdoc="CHILD"></iframe></body></html>'''.replace(
        "CHILD", html.escape(child, quote=True))
    driver = r'''
const fs=require("node:fs"),path=require("node:path"),{spawn}=require("node:child_process");
const [browser,profile,url]=process.argv.slice(1);
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const chrome=spawn(browser,["--headless=new","--no-sandbox","--no-first-run","--disable-extensions",
  "--disable-breakpad","--disable-crash-reporter","--remote-debugging-port=0","--remote-allow-origins=*",
  "--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader","--window-size=1280,900",
  "--user-data-dir="+profile,"about:blank"],{windowsHide:true,stdio:"ignore"});
(async()=>{
 let ws;
 try{
  const portFile=path.join(profile,"DevToolsActivePort");
  for(let i=0;!fs.existsSync(portFile);i++){if(i>100)throw Error("Chrome debug port did not open");await delay(100);}
  const port=fs.readFileSync(portFile,"utf8").split("\n")[0];
  const targets=await(await fetch("http://127.0.0.1:"+port+"/json/list")).json();
  ws=new WebSocket(targets.find(t=>t.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  let serial=0;const pending=new Map(),exceptions=[];
  ws.onmessage=e=>{const msg=JSON.parse(e.data);if(msg.method==="Runtime.exceptionThrown")exceptions.push(msg.params.exceptionDetails);
    if(msg.id){const p=pending.get(msg.id);pending.delete(msg.id);
    if(msg.error)p.reject(Error(JSON.stringify(msg.error)));else p.resolve(msg.result);}};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  await send("Runtime.enable");await send("Page.navigate",{url});
  for(let i=0;i<150;i++){
   const result=await send("Runtime.evaluate",{expression:'document.querySelector("#fx-result")?.textContent',returnByValue:true});
   if(result.result.value){console.log(result.result.value);return;}
   await delay(200);
  }
  const details=await send("Runtime.evaluate",{expression:'document.querySelector("iframe")?.contentWindow.eval("JSON.stringify({prompt:rawActivePrompt()?.kind,active:activeAnimationEvent?.type,pending:!!pendingVisualState,body:!!document.querySelector(\\\".effect-prompt-modal\\\")})")',returnByValue:true});
  throw Error("Live page did not report a result within 30 seconds: "+JSON.stringify({exceptions,details}));
 }finally{ws?.close();chrome.kill();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});'''
    profile = tmp_path / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["node", "-e", driver, BROWSER, str(profile),
        fixture["origin"] + "/__duel_fx_test__"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=50)
    assert result.returncode == 0, result.stderr
    payload = json.loads(base64.b64decode(result.stdout.strip()).decode("utf-8"))
    assert "error" not in payload, payload.get("error")
    assert payload.get("ok"), payload
    return payload


def test_sakuya_live_choices_keep_second_prompt_clickable(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("Chrome is required for live choice responses")
    from test_effect_resolution_order_oct29 import setup
    runner = setup("yellow_06_02_02c_00")
    session = runner.session
    initial = session.state_dto()
    dp_by_iid = {card.iid: session.engine.effective_dp(card) for card in session.engine.state.players[1].field}
    for action in runner.spec["actions"][:2]:
        opened = runner._run_action(action)["state"]
    fixture = {**duel_fx_fixture, "fixture": {**duel_fx_fixture["fixture"],
        "main": initial, "liveFirst": opened, "dpByIid": dp_by_iid}}
    old_session = fixture["handler"].app.session
    fixture["handler"].app.session = session
    body = r'''
  // The production /duel entry installs this renderer in duel.js. The fixture
  // defers boot, so wire that same renderer before using full render().
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  const waitFor=async(check,label)=>{
    const until=performance.now()+10000;
    while(performance.now()<until){if(check())return;await delay(25);}
    throw new Error(label+JSON.stringify({prompt:activePrompt(),active:activeAnimationEvent?.type,pending:!!pendingVisualState,error:state.error}));
  };
  stageDuelState(fixture.liveFirst);render();
  const seen=[];
  for(const dp of [0,1]){
    await waitFor(()=>activePrompt()?.kind==="effect_target","DP"+dp+" prompt appears");
    const prompt=activePrompt(),options=prompt.options.filter(o=>o.cardIid);
    assert(options.length>0&&options.every(o=>fixture.dpByIid[o.cardIid]===dp),"only correct DP"+dp+" targets are selectable");
    const button=app.querySelector('.effect-prompt-modal [data-option="'+options[0].id+'"]');
    assert(button&&!button.disabled,"DP"+dp+" has a real clickable choice");
    seen.push({dp,promptId:prompt.id,target:options[0].cardIid});button.click();
    await waitFor(()=>!!pendingVisualState||rawActivePrompt()?.id!==prompt.id,"real choose response arrives");
    await waitFor(()=>!activeAnimationEvent&&!pendingVisualState&&!stagedDuelStateQueue.length,"choose animations settle");
  }
  assert(!state.error&&activePrompt()?.kind!=="effect_target","both actual HTTP choices complete");
  assert(seen.every(({target})=>!state.players.opponent.field.some(c=>c.iid===target)),"both selected targets leave the field");
  return {ok:true,seen,finalPrompt:activePrompt()?.kind};'''
    page = PAGE.replace("settings.reducedMotion=false", "settings.reducedMotion=true").replace("await ZZFx.prepare();", "")
    try:
        result = _run_live_page(fixture, tmp_path, page.replace("BODY", body))
        assert [item["dp"] for item in result["seen"]] == [0, 1], result
    finally:
        fixture["handler"].app.session = old_session


@pytest.mark.parametrize("viewer", ["controller", "opponent"])
def test_rosario_real_dtos_animate_through_public_resolving_area(duel_fx_fixture, tmp_path, viewer):
    if BROWSER is None:
        pytest.skip("Chrome is required for resolving-zone playback")
    from test_effect_resolution_order_oct29 import setup
    from zz.multiplayer.views import build_player_view
    runner = setup("yellow_011_03_02c_00")
    for action in runner.spec["actions"][:3]:
        initial = runner._run_action(action)["state"]
    if viewer == "opponent":
        initial = build_player_view(runner.session, player_id="player_2", revision=1,
            state_hash="test", animation_events=initial["animationEvents"])
    first = runner._run_action(runner.spec["actions"][3])["state"]
    magic, = first["players"]["human"]["resolving"]
    if viewer == "opponent":
        first = build_player_view(runner.session, player_id="player_2", revision=2,
            state_hash="test", animation_events=first["animationEvents"])
    final = runner._run_action(runner.spec["actions"][4])["state"]
    if viewer == "opponent":
        final = build_player_view(runner.session, player_id="player_2", revision=3,
            state_hash="test", animation_events=final["animationEvents"])
    fixture = {**duel_fx_fixture, "fixture": {**duel_fx_fixture["fixture"],
        "main": initial, "firstClause": first, "finalClause": final, "magicIid": magic["iid"],
        "sourceSide": magic["ownerSide"], "viewer": viewer}}
    body = r'''
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  const iid=fixture.magicIid;
  const source=()=>findPlayerBySide(fixture.sourceSide);
  const count=area=>(source()[area]||[]).filter(c=>c.iid===iid).length;
  const expectedHand=Object.values(fixture.firstClause.players).find(p=>p.side===fixture.sourceSide).hand.length;
  stageDuelState(fixture.firstClause);render();
  let steps=0,entered=false;
  while(activeAnimationEvent){
    let landingRect=null;
    assert(++steps<20,"first response settles");
    assert(count("trash")===0,"source Magic cannot reach Trash during either clause");
    if(activeAnimationEvent.type==="zone_move"&&activeAnimationEvent.card.iid===iid){
      assert(activeAnimationEvent.toArea==="resolving","paid source first moves to resolving");
      const flight=app.querySelector(".board-zone-move-card.fx-flight");
      assert(flight,"entering resolving keeps its real card flight");
      const animation=flight.getAnimations().find(a=>a.effect.target===flight);
      animation.pause();animation.currentTime=animation.effect.getComputedTiming().duration;
      landingRect=flight.getBoundingClientRect();
      assert(!ZZFx.inspect().activeHandles,"casting adds no particle emitter");
    }
    if(count("resolving")){
      entered=true;
      assert(findCardByIid(iid)?.area==="resolving","public resolving card is discoverable for details");
      const card=app.querySelector('.resolving-zone [data-board-card-anchor="'+fixture.sourceSide+':card:'+iid+'"]');
      assert(card&&card.querySelector("img")?.alt!=="CARD","resolving source is publicly displayed");
      assert(count("hand")===0,"source does not duplicate its former hand card");
    }
    showNextAnimationEvent(true);
    if(landingRect){
      const settled=app.querySelector('.resolving-zone [data-board-card-anchor="'+fixture.sourceSide+':card:'+iid+'"]')?.getBoundingClientRect();
      assert(settled&&Math.abs(settled.left-landingRect.left)<2&&Math.abs(settled.top-landingRect.top)<2&&
        Math.abs(settled.width-landingRect.width)<2&&Math.abs(settled.height-landingRect.height)<2,
        "the flight lands exactly on the public resolving card slot");
    }
  }
  assert(entered&&count("resolving")===1&&count("trash")===0,"second choice keeps source publicly resolving");
  assert(source().hand.length===expectedHand,"casting removes exactly one source hand card");
  if(fixture.viewer==="controller")assert(activePrompt()?.kind==="effect_target","second clause choice remains selectable");
  else assert(source().hand.every(c=>c.faceDown&&!c.cardId&&c.iid==null),"other opponent hand cards remain anonymous");
  stageDuelState(fixture.finalClause);render();
  let exits=0;steps=0;
  while(activeAnimationEvent){
    assert(++steps<20,"final response settles");
    const event=activeAnimationEvent;
    if(event.type==="zone_move"&&event.card.iid===iid){
      exits++;assert(event.fromArea==="resolving"&&event.toArea==="trash","source exits resolving only after both clauses");
      assert(app.querySelector(".board-zone-move-card.fx-flight"),"resolving source has a real exit flight");
    }
    showNextAnimationEvent(true);
  }
  assert(exits===1&&count("resolving")===0&&count("trash")===1&&count("hand")===0,"source arrives once without loss or duplication");
  assert(source().hand.length===expectedHand,"leaving resolving never removes another hidden hand card");
  assert(!ZZFx.inspect().errors.length,"resolving playback stays error-free: "+JSON.stringify(ZZFx.inspect().errors));
  return {ok:true,exits};'''
    _run_fx_test_page(fixture, tmp_path, PAGE.replace("BODY", body))


def test_siune_real_switch_disclosure_finishes_before_private_top_two_window(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("Chrome is required for disclosure/choice timing")
    from test_effect_resolution_order_oct29 import setup
    runner = setup("yellow_02_02_02c_00")
    initial = runner.session.state_dto()
    opened = runner._run_action(runner.spec["actions"][0])["state"]
    assert len(opened["prompt"]["revealedCards"]) == 2
    fixture = {**duel_fx_fixture, "fixture": {**duel_fx_fixture["fixture"],
        "main": initial, "switchResponse": opened}}
    body = r'''
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  stageDuelState(fixture.switchResponse);render();
  let disclosed=false,steps=0;
  while(activeAnimationEvent){
    assert(++steps<20,"Switch disclosure batch settles");
    assert(!activePrompt(),"private choice cannot open while its setup animations run");
    assert(!app.querySelector(".effect-prompt-modal"),"no top-two card window is mounted before disclosure ends");
    if(activeAnimationEvent.type==="effect"&&activeAnimationEvent.card?.cardId==="yellow_02_02_02c_00"){
      disclosed=true;
      const explanation=app.querySelector(".effect-trigger-overlay");
      assert(explanation&&explanation.getBoundingClientRect().width>0,"Switch uses its real visible source disclosure overlay");
      assert(!app.querySelector(".effect-prompt-grid .effect-choice-card"),"private revealed cards stay behind the disclosure boundary");
    }
    showNextAnimationEvent(true);
  }
  assert(disclosed,"the real source Switch disclosure must play");
  assert(activePrompt()?.kind==="effect_target"&&activePrompt().revealedCards.length===2,"two private cards become available after disclosure");
  assert(app.querySelectorAll(".effect-prompt-grid .effect-choice-card").length===2,"exactly the two inspected cards now render in the choice window");
  assert(!app.querySelector(".effect-trigger-overlay"),"source disclosure has finished before the private choice appears");
  return {ok:true,disclosed};'''
    _run_fx_test_page(fixture, tmp_path, PAGE.replace("BODY", body))


def _force_search_session(*, full=False, empty=False, viewer_id=None):
    from zz.cards import CARD_REGISTRY
    from zz.enums import AreaType, CardType
    from zz.forces import F_OUROBOROS
    from zz.model import CardInstance, ForceInstance
    from zz.web.session import GameSession
    from test_force_base_replacement import _token
    from zz.multiplayer.views import build_player_view
    session = GameSession(seed=11, mode="god")
    owner = session.engine.state.players[1]
    cards = [card for card in CARD_REGISTRY.values() if card.type is CardType.B_MINION][:2]
    if empty:
        cards = [next(card for card in CARD_REGISTRY.values() if card.type is CardType.F_MINION)]
    owner.deck = [CardInstance(card=card, owner=owner, iid=session.engine.state.allocate_iid(), area=AreaType.DECK) for card in cards]
    if full:
        owner.base = [_token(owner, session.engine.state.allocate_iid()) for _ in range(10)]
    owner.forces = [ForceInstance(force=F_OUROBOROS, owner=owner, life=1)]
    session._clear_prompt()
    initial = session.state_dto()
    if viewer_id:
        initial = build_player_view(session, player_id=viewer_id, revision=1, state_hash="test")
    session.engine._damage_force(owner.forces[0], 1, source=None)
    session._drain_or_prompt_force_base_choices()
    choice = session.state_dto()
    if viewer_id:
        choice = build_player_view(session, player_id=viewer_id, revision=2, state_hash="test",
            animation_events=choice["animationEvents"])
    return session, initial, choice


@pytest.mark.parametrize("full", [False, True])
def test_force_search_uses_large_shared_deck_picker_and_real_choices(duel_fx_fixture, tmp_path, full):
    if BROWSER is None:
        pytest.skip("Chrome is required for Force deck search")
    session, initial, choice = _force_search_session(full=full)
    fixture = {**duel_fx_fixture, "fixture": {**duel_fx_fixture["fixture"],
        "main": initial, "forceChoice": choice, "full": full}}
    old_session = fixture["handler"].app.session
    fixture["handler"].app.session = session
    body = r'''
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  const waitFor=async(fn,label)=>{const end=performance.now()+10000;while(performance.now()<end){if(fn())return;await delay(25);}throw Error(label+JSON.stringify({prompt:activePrompt(),pending:!!pendingVisualState,error:state.error}));};
  stageDuelState(fixture.forceChoice);render();
  await waitFor(()=>activePrompt()?.kind==="force_base_choice","Force owner's deck choice opens after damage");
  const prompt=activePrompt(),chosen=prompt.options[1];
  assert(prompt.playerSide==="P2"&&prompt.options.length===2,"the Force owner receives exactly its legal Base Minions");
  const modal=app.querySelector(".effect-prompt-modal"),cards=app.querySelectorAll(".effect-prompt-grid .effect-choice-card");
  assert(modal&&cards.length===2,"Force search reuses the large common deck-search picker");
  assert(!app.querySelector(".cockpit .force-choice-card"),"the special small cockpit picker is removed");
  assert(modal.querySelector(".effect-prompt-panel").getBoundingClientRect().width>600&&cards[0].getBoundingClientRect().height>=200,"candidate cards use the existing large search dimensions");
  for(const [language,note] of [["zh","选择 1 张"],["ja","1枚を選んで"],["en","Choose 1 Base Minion"]]){
    settings.uiLanguage=language;setAppHtml(renderDuelView());
    assert(app.querySelector(".effect-prompt-modal .payment-note").textContent.includes(note),"Force choice explicitly requires exactly one card in "+language);
  }
  settings.uiLanguage="zh";setAppHtml(renderDuelView());
  app.querySelector('.effect-prompt-modal [data-option="'+chosen.id+'"]').click();
  const owner=()=>findPlayerBySide("P2");
  if(fixture.full){
    await waitFor(()=>activePrompt()?.kind==="effect_target"&&activePrompt().choiceKind==="ally_base","full Mana continues to its replacement choice");
    assert(owner().base.length===10&&!owner().base.some(c=>c.iid===chosen.cardIid),"choosing the deck card cannot silently eject existing Mana");
    const replacement=activePrompt().options[2];
    assert(app.querySelectorAll(".effect-prompt-grid .effect-choice-card").length===10,"replacement shares the same large picker");
    app.querySelector('.effect-prompt-modal [data-option="'+replacement.id+'"]').click();
  }
  await waitFor(()=>!pendingChoicePromptId&&!pendingVisualState&&!activeAnimationEvent&&owner().base.some(c=>c.iid===chosen.cardIid),"the selected second Base Minion arrives through real choose responses");
  assert(owner().base.length===(fixture.full?10:1)&&!state.error,"Force search preserves capacity and selected identity");
  return {ok:true,full:fixture.full};'''
    page = PAGE.replace("settings.reducedMotion=false", "settings.reducedMotion=true").replace("await ZZFx.prepare();", "")
    try:
        _run_live_page(fixture, tmp_path, page.replace("BODY", body))
    finally:
        fixture["handler"].app.session = old_session


@pytest.mark.parametrize("case", ["empty", "private"])
def test_force_search_empty_deck_or_other_viewer_has_no_picker(duel_fx_fixture, tmp_path, case):
    if BROWSER is None:
        pytest.skip("Chrome is required for Force search visibility")
    session, initial, response = _force_search_session(empty=case == "empty",
        viewer_id="player_1" if case == "private" else None)
    assert response["prompt"] is None
    fixture = {**duel_fx_fixture, "fixture": {**duel_fx_fixture["fixture"],
        "main": initial, "forceResponse": response, "case": case}}
    body = r'''
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  stageDuelState(fixture.forceResponse);render();
  let steps=0;
  while(activeAnimationEvent){assert(++steps<12,"Force response settles");showNextAnimationEvent(true);}
  assert(!app.querySelector(".effect-prompt-modal, .force-choice-card"),"no choice window appears for an empty search or another viewer");
  assert(!activePrompt(),"the UI cannot invent a Force selection from the catalog");
  if(fixture.case==="private")
    assert(state.players.opponent.hand.every(c=>c.faceDown&&!c.cardId&&c.iid==null),"opponent hand identities remain hidden");
  else
    assert(findPlayerBySide("P2").hand.length===fixture.main.players.opponent.hand.length+1,"an empty search still performs its rule draw without requiring a fake choice");
  return {ok:true};'''
    page = PAGE.replace("settings.reducedMotion=false", "settings.reducedMotion=true").replace("await ZZFx.prepare();", "")
    _run_fx_test_page(fixture, tmp_path, page.replace("BODY", body))


def test_damage_native_frames_have_one_visible_impact(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("Chrome is required for actual WebGL frame checks")
    body = r'''
  const canvas=app.querySelector(".fx-canvas"),gl=canvas.getContext("webgl");
  const draw=gl.drawArrays.bind(gl);let samples=[],began=0;
  gl.drawArrays=(...args)=>{
    draw(...args);
    if(gl.getParameter(gl.FRAMEBUFFER_BINDING)||!began)return;
    const pixels=new Uint8Array(canvas.width*canvas.height*4);
    gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
    let light=0;
    for(let i=0;i<pixels.length;i+=4)light+=Math.max(pixels[i],pixels[i+1],pixels[i+2]);
    samples.push([Math.round(performance.now()-began),light]);
  };
  const waveforms={},preflashes={};
  for(const targetKind of ["force","player","force","player"]){
    const event={type:"damage",side:state.humanSide,targetKind,forceId:state.players.human.forces[0].id,amount:1};
    const before=ZZFx.inspect().renderedEvents;
    samples=[];began=performance.now();start(event);
    const target=app.querySelector(targetKind==="force"
      ? `[data-board-force-anchor="${event.side}:force:${event.forceId}"]`
      : `[data-board-anchor="${event.side}:player"]`);
    assert(target,"real life target is mounted");
    // Scrub actual browser-created WAAPI to its peak. Virtual-time Chrome does
    // not advance the compositor clock at the same rate as JS timers.
    const pulses=app.getAnimations({subtree:true}).filter(a=>a.effect?.getKeyframes().some(f=>/brightness\(2\)/.test(f.filter||"")));
    for(const a of pulses){a.pause();a.currentTime=61.2;}
    await delay(64);
    preflashes[targetKind]={filter:getComputedStyle(target).filter,
      pulses:pulses.map(a=>({filter:getComputedStyle(a.effect.target).filter,tag:a.effect.target.outerHTML.slice(0,220)})),
      nativeLight:Math.max(...samples.map(p=>p[1]))};
    await delay(36);
    const layer=app.querySelector(".board-animation-layer");
    setAppHtml(renderDuelView());
    assert(app.querySelector(".board-animation-layer")===layer,"same-event rerender retains its existing visual layer");
    await delay(500);began=0;waveforms[targetKind+before]=samples;
    assert(ZZFx.inspect().renderedEvents===before+1,"each distinct damage event draws once, including after rerender");
    assert(!ZZFx.inspect().activeHandles,"the completed short strike leaves no native tail");
    assert(app.querySelectorAll(".board-life-float.damage").length===1,"one exact damage number remains");
    end(event);
  }
  // A second substantial rising lobe after the first has faded is a second
  // visible strike, even if one native handle owns both emitter bursts.
  for(const [kind,wave] of Object.entries(waveforms)){
    const max=Math.max(...wave.map(p=>p[1]));
    let peak=0,low=Infinity,second=false;
    for(const [,light] of wave){
      if(peak>max*.25&&low<peak*.48&&light>Math.max(peak*.7,max*.3))second=true;
      if(light>peak){peak=light;low=light;}
      else low=Math.min(low,light);
    }
    assert(max>10000,kind+" must draw a real visible impact");
    assert(!second,kind+" native pixels contain a second impact: "+JSON.stringify(waveforms));
  }
  for(const [kind,flash] of Object.entries(preflashes))
    assert(!flash.pulses.length,
      kind+" flashes the entire life target before the later native strike: "+JSON.stringify({preflashes,waveforms}));
  return {ok:true,waveforms,preflashes};'''
    _run_fx_test_page(duel_fx_fixture, tmp_path, PAGE.replace("BODY", body))


def test_summon_and_base_placement_fly_without_landing_particles(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("Chrome is required for actual arrival feedback")
    body = r'''
  let nextIid=800000;
  for(const [fromArea,toArea,summonFx] of [
    ["hand","field","hand"],["trash","field","graveyard"],["deck","field","deck"],
    ["hand","base",""],["deck","base",""],["trash","base",""]]){
    state=JSON.parse(JSON.stringify(fixture.main));state.pendingAttack=null;
    const human=state.players.human;
    const moving={...human.hand[0],iid:nextIid++,ownerSide:human.side,area:fromArea};
    if(fromArea!=="deck")human[fromArea].push(moving);
    setAppHtml(renderDuelView());
    const event={type:"zone_move",side:human.side,fromArea,toArea,card:moving,summonFx};
    const before=ZZFx.inspect().renderedEvents;
    start(event);
    const flight=app.querySelector(".board-zone-move-card.fx-flight");
    assert(flight&&flight.getAnimations().length,fromArea+" → "+toArea+": card flight must remain");
    await delay(600);
    assert(!ZZFx.inspect().activeHandles&&ZZFx.inspect().renderedEvents===before,
      fromArea+" → "+toArea+": no small landing particle emitter");
    assert(!app.querySelector(".board-graveyard-summon"),"no legacy resurrection landing glow");
    end(event);
  }
  assert(!ZZFx.inspect().errors.length,"arrival paths must remain error-free: "+JSON.stringify(ZZFx.inspect().errors));
  return {ok:true};'''
    _run_fx_test_page(duel_fx_fixture, tmp_path, PAGE.replace("BODY", body))


def test_card_detail_long_title_stays_inside_panel_and_clear_of_close(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("Chrome is required for layout checks")
    body = r'''
  const card={...state.players.human.field[0],activeEffects:Array.from({length:6},()=>({textZh:"能力修正 / BP +100"})),
    nameZh:"「狂战治疗师」亚丝娜 —— 连续发动与能力修正的超长卡牌详情标题",
    abilityZh:"飞来\n【常时】\n这个回合，当对方的随从返回手牌时，处理对应效果。\n".repeat(22)};
  const sizes=[[1295,1150],[1280,720],[390,844]];
  for(const [width,height] of sizes){
    const iframe=parent.document.querySelector("iframe");iframe.width=width;iframe.height=height;
    await delay(40);
    setAppHtml(renderCardDetail(card));
    const panel=app.querySelector(".card-detail-panel"),title=panel.querySelector(".card-detail-title");
    const button=panel.querySelector(".detail-close");
    title.scrollIntoView({block:"center"});
    const bounds=panel.getBoundingClientRect(),close=button.getBoundingClientRect();
    const heading=title.getBoundingClientRect();
    assert(heading.right<=close.left||heading.left>=close.right||heading.bottom<=close.top||heading.top>=close.bottom,
      width+": title layout must reserve the close button's complete width");
    assert(bounds.left>=0&&bounds.right<=innerWidth+1&&bounds.top>=0&&bounds.bottom<=innerHeight+1,
      width+": panel must fit the viewport: "+JSON.stringify(bounds.toJSON()));
    const range=document.createRange();range.selectNodeContents(title);
    for(const line of range.getClientRects()){
      assert(line.left>=bounds.left&&line.right<=bounds.right&&line.top>=bounds.top&&line.bottom<=bounds.bottom,
        width+": every title line must be fully visible within the panel");
      assert(line.right<=close.left||line.left>=close.right||line.bottom<=close.top||line.top>=close.bottom,
        width+": title text overlaps the close button");
    }
  }
  return {ok:true};'''
    _run_fx_test_page(duel_fx_fixture, tmp_path, PAGE.replace("BODY", body))
