from __future__ import annotations

import pytest

from test_frontend_fx import BROWSER, _run_fx_test_page, duel_fx_fixture


def test_zone_move_arrivals_settle_on_real_field_and_base_slots(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX arrival tests")

    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE;
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const close=(actual,expected,tolerance)=>Math.abs(actual-expected)<=tolerance;
  const angleOf=transform=>{
    if(!transform||transform==="none")return 0;
    const matrix=new DOMMatrixReadOnly(transform);
    return Math.atan2(matrix.b,matrix.a)*180/Math.PI;
  };
  const iidOf=card=>`${fixture.main.humanSide}:card:${card.iid}`;
  const scenarios=[
    {area:"field",existing:0,rested:false,label:"empty field"},
    {area:"field",existing:2,rested:false,label:"field after existing cards"},
    {area:"base",existing:1,rested:false,label:"base mini slot"},
    {area:"field",existing:1,rested:true,label:"rested field card"},
  ];
  const fieldTemplate=fixture.main.players.human.field[0];
  let nextIid=Math.max(...fixture.main.players.human.hand.concat(
    fixture.main.players.human.field,fixture.main.players.human.base).map(card=>Number(card.iid)||0))+50000;
  const measurements=[];
  catalog=fixture.catalog;appView="duel";settings.duelScale=100;settings.reducedMotion=false;

  for(const scenario of scenarios){
    state=JSON.parse(JSON.stringify(fixture.main));
    const human=state.players.human;
    human.field=[];human.base=[];
    const area=human[scenario.area];
    for(let index=0;index<scenario.existing;index++){
      area.push({...fieldTemplate,iid:nextIid++,area:scenario.area,ownerSide:human.side,
        faceDown:false,rested:false});
    }
    const moving={...human.hand[0],area:"hand",faceDown:false,rested:scenario.rested};
    const initialCardAnchor=iidOf(moving);
    setAppHtml(renderDuelView());
    const source=document.querySelector(`[data-board-card-anchor="${initialCardAnchor}"]`);
    assert(source,"zone-move source must be a rendered real hand card: "+scenario.label);
    const sourceSlot=source.closest(".hand-slot");
    const sourceWidth=parseFloat(getComputedStyle(source).width);
    const sourceHeight=parseFloat(getComputedStyle(source).height);
    const sourceOpacity=parseFloat(getComputedStyle(source).opacity);
    const sourceAngle=angleOf(getComputedStyle(source).transform)+
      (sourceSlot?angleOf(getComputedStyle(sourceSlot).transform):0);

    const event={type:"zone_move",side:human.side,fromArea:"hand",toArea:scenario.area,
      card:{...moving},summonFx:""};
    ZZFx.onEventStart(event,1800);activeAnimationEvent=event;
    human.hand=human.hand.filter(card=>String(card.iid)!==String(moving.iid));
    setAppHtml(renderDuelView());
    const flight=app.querySelector(".board-zone-move-card.fx-flight");
    const animation=flight&&flight.getAnimations().find(candidate=>candidate.effect.target===flight);
    assert(flight&&animation,scenario.label+": zone-move must create an actual WAAPI flight");
    const timing=animation.effect.getComputedTiming();
    assert(Number.isFinite(timing.duration)&&timing.duration>100,
      scenario.label+": flight duration must be finite and long enough to inspect");
    const firstFrame=animation.effect.getKeyframes()[0];
    assert(!Object.hasOwn(firstFrame,"width")&&!Object.hasOwn(firstFrame,"height"),
      scenario.label+": flight must resize with transforms instead of animating layout dimensions");
    assert(close(Number(firstFrame.opacity),sourceOpacity,0.01),
      scenario.label+": flight must retain source opacity");
    const firstAngle=Number(firstFrame.transform.match(/rotate\((-?[\d.]+)deg\)/)?.[1]||0);
    assert(close(firstAngle,sourceAngle,0.2),
      scenario.label+": flight must retain the source hand-fan angle");

    animation.pause();
    // Seek the real browser animation, isolating trajectory pacing from RAF
    // scheduling and particle loading. An interior waypoint must not brake to
    // almost zero and immediately restart while the card is still in flight.
    const samples=[];
    for(let index=0;index<=200;index++){
      animation.currentTime=timing.duration*index/200;
      const at=flight.getBoundingClientRect();
      samples.push({x:at.left+at.width/2,y:at.top+at.height/2});
    }
    const speeds=samples.slice(1,-1).map((at,index)=>
      Math.hypot(samples[index+2].x-samples[index].x,samples[index+2].y-samples[index].y));
    const stops=[];
    for(let index=30;index<160;index++){
      const neighbors=Math.min(speeds[index-5],speeds[index+5]);
      if(neighbors>0.1&&speeds[index]<neighbors*.2){
        stops.push({progress:(index+1)/200,speed:speeds[index],neighbors});
      }
    }
    assert(stops.length===0,scenario.label+": card must not pause at an interior waypoint: "+JSON.stringify(stops));
    animation.currentTime=timing.duration-30;
    const flightRect=flight.getBoundingClientRect();
    const flightStyle=getComputedStyle(flight);
    assert(parseFloat(flightStyle.opacity)>0.98,
      scenario.label+": arrival must still be visible 30ms before the queue settles");

    const arrived={...moving,area:scenario.area,rested:scenario.rested};
    human[scenario.area].push(arrived);
    setAppHtml(renderDuelView());
    const realCard=document.querySelector(`[data-board-card-anchor="${iidOf(arrived)}"]`);
    assert(realCard&&flight.isConnected,scenario.label+": same-event patch must preserve the flight and render target card");
    const targetRect=realCard.getBoundingClientRect();
    const targetWidth=parseFloat(getComputedStyle(realCard).width);
    const targetHeight=parseFloat(getComputedStyle(realCard).height);
    const scale=firstFrame.transform.match(/scale\(([-\d.]+),\s*([-\d.]+)\)/);
    assert(scale&&close(parseFloat(getComputedStyle(flight).width),targetWidth,0.5)&&
      close(parseFloat(getComputedStyle(flight).height),targetHeight,0.5)&&
      close(Number(scale[1]),sourceWidth/targetWidth,0.015)&&
      close(Number(scale[2]),sourceHeight/targetHeight,0.015),
      scenario.label+": final inline size and starting transform scale must match source and real target dimensions");
    assert(close(flightRect.width,targetRect.width,1.5)&&
      close(flightRect.height,targetRect.height,1.5),
      scenario.label+": late flight width and height must match the rendered destination card");
    assert(close(flightRect.left+flightRect.width/2,targetRect.left+targetRect.width/2,2)&&
      close(flightRect.top+flightRect.height/2,targetRect.top+targetRect.height/2,2),
      scenario.label+": late flight center must match the rendered destination slot");
    if(scenario.rested){
      assert(close(angleOf(flightStyle.transform),angleOf(getComputedStyle(realCard).transform),0.25),
        "rested arrival must settle at the same 8-degree rotation as renderCard");
    }

    ZZFx.onEventEnd(event);activeAnimationEvent=null;animationEventQueue.length=0;
    setAppHtml(renderDuelView());
    assert(realCard.isConnected&&!flight.isConnected,
      scenario.label+": queue settlement must remove the flight and leave the real card");
    const settledRect=realCard.getBoundingClientRect();
    assert(close(flightRect.left+flightRect.width/2,settledRect.left+settledRect.width/2,2)&&
      close(flightRect.top+flightRect.height/2,settledRect.top+settledRect.height/2,2),
      scenario.label+": pre-settle flight position must meet the settled real card");
    measurements.push({area:scenario.area,existing:scenario.existing,rested:scenario.rested,
      duration:timing.duration,opacity:parseFloat(flightStyle.opacity),
      widthDelta:Math.abs(flightRect.width-targetRect.width),heightDelta:Math.abs(flightRect.height-targetRect.height)});
  }
  return {ok:true,scenarios:measurements};
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''

    result = _run_fx_test_page(duel_fx_fixture, tmp_path, child)
    assert len(result["scenarios"]) == 4, result


def test_control_transfer_arrival_starts_at_old_owner_card(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX arrival tests")

    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE;
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const close=(actual,expected,tolerance)=>Math.abs(actual-expected)<=tolerance;
  catalog=fixture.catalog;appView="duel";settings.duelScale=100;settings.reducedMotion=false;
  state=JSON.parse(JSON.stringify(fixture.main));
  const receiver=state.players.human;
  const oldOwner=state.players.opponent;
  receiver.field=[];receiver.base=[];oldOwner.field=[];oldOwner.base=[];
  const template=fixture.main.players.human.field[0];
  const iid=Math.max(...fixture.main.players.human.hand.concat(
    fixture.main.players.human.field,fixture.main.players.human.base).map(card=>Number(card.iid)||0))+70000;
  const moving={...template,iid,area:"field",ownerSide:oldOwner.side,faceDown:false,rested:false};
  oldOwner.field.push(moving);
  setAppHtml(renderDuelView());

  const source=document.querySelector('[data-board-card-anchor="'+oldOwner.side+':card:'+iid+'"]');
  const receiverZone=document.querySelector('[data-board-anchor="'+receiver.side+':field"]');
  assert(source&&receiverZone,"control-transfer fixture must render source card and receiving zone");
  const sourceRect=source.getBoundingClientRect();
  const sourceCenter={x:sourceRect.left+sourceRect.width/2,y:sourceRect.top+sourceRect.height/2};
  const sourceOpacity=parseFloat(getComputedStyle(source).opacity);
  const receiverRect=receiverZone.getBoundingClientRect();
  const receiverCenter={x:receiverRect.left+receiverRect.width/2,y:receiverRect.top+receiverRect.height/2};
  assert(Math.hypot(sourceCenter.x-receiverCenter.x,sourceCenter.y-receiverCenter.y)>60,
    "the old-owner card and receiving side must have distinct start locations");

  const event={type:"zone_move",side:receiver.side,fromArea:"field",toArea:"field",
    card:{...moving,ownerSide:oldOwner.side},summonFx:""};
  ZZFx.onEventStart(event,1800);activeAnimationEvent=event;
  oldOwner.field=[];
  setAppHtml(renderDuelView());
  const flight=app.querySelector(".board-zone-move-card.fx-flight");
  const animation=flight&&flight.getAnimations().find(candidate=>candidate.effect.target===flight);
  assert(flight&&animation,"cross-owner zone move must create an actual WAAPI flight");
  animation.pause();animation.currentTime=0;
  const firstRect=flight.getBoundingClientRect();
  const firstOpacity=parseFloat(getComputedStyle(flight).opacity);
  assert(close(firstRect.left+firstRect.width/2,sourceCenter.x,2)&&
    close(firstRect.top+firstRect.height/2,sourceCenter.y,2),
    "flight first frame must use the old owner source snapshot, not the receiver side");
  assert(close(firstOpacity,sourceOpacity,0.02),
    "cross-owner arrival must retain the actual source card opacity on its first frame");

  receiver.field.push({...moving,area:"field",ownerSide:receiver.side});
  setAppHtml(renderDuelView());
  const target=document.querySelector('[data-board-card-anchor="'+receiver.side+':card:'+iid+'"]');
  assert(target&&flight.isConnected,"same-event patch must keep flight and render the receiving card");
  animation.currentTime=animation.effect.getComputedTiming().duration-30;
  const lateRect=flight.getBoundingClientRect();
  const targetRect=target.getBoundingClientRect();
  assert(parseFloat(getComputedStyle(flight).opacity)>0.98,
    "cross-owner flight must remain visible until it reaches the receiving card");
  assert(close(lateRect.left+lateRect.width/2,targetRect.left+targetRect.width/2,2)&&
    close(lateRect.top+lateRect.height/2,targetRect.top+targetRect.height/2,2),
    "cross-owner flight must settle at the receiver's real field-card position");

  ZZFx.onEventEnd(event);activeAnimationEvent=null;animationEventQueue.length=0;
  setAppHtml(renderDuelView());
  assert(target.isConnected&&!flight.isConnected,
    "event cleanup must remove the temporary flight and preserve the receiving card");
  return {ok:true,sourceSide:oldOwner.side,receiverSide:receiver.side,
    startCenter:sourceCenter,receiverCenter,arrivalCenter:{x:lateRect.left+lateRect.width/2,
      y:lateRect.top+lateRect.height/2},opacity:firstOpacity};
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''

    result = _run_fx_test_page(duel_fx_fixture, tmp_path, child)
    assert result["sourceSide"] != result["receiverSide"], result
    assert result["opacity"] > 0.98, result
