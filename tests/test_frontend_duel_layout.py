from __future__ import annotations

import json
import html as html_escape
import os
import re
import shutil
import subprocess
from pathlib import Path
from threading import Thread

import pytest

from zz.web.server import ServerState, make_server
from zz.web.session import GameSession


BROWSER = next((path for path in (
    shutil.which("google-chrome"), shutil.which("chromium"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if path and Path(path).is_file()), None)
pytestmark = pytest.mark.skipif(BROWSER is None, reason="headless Chrome/Chromium is required")


@pytest.fixture(scope="module")
def duel_fixture(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("duel-layout")
    session = GameSession(seed=123, mode="god", opponent_ai_difficulty="easy")
    session.choose(session.prompt["id"], "keep")
    session.choose(session.prompt["id"], "keep")
    mana = session.state_dto()
    session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    main = session.state_dto()
    assert any(option.get("kind") == "end_turn" for option in main["prompt"]["options"])
    app = ServerState(session=session, deck_root=temporary / "decks",
                      settings_root=temporary / "settings", ai_data_root=temporary)
    catalog = app.catalog()
    # Public source archives keep the media pack separate. The icon is still
    # rendered when testing without those assets; its CSS dimensions are real.
    catalog["uiAssets"]["button_turn_end"] = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='110' height='110'/%3E"
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", {"catalog": catalog, "mana": mana, "main": main}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("width,height,scale", [
    (1366, 768, 100), (1280, 800, 80), (1536, 864, 150),
    (1920, 1080, 100), (980, 768, 100), (375, 812, 100),
    (320, 568, 80), (600, 800, 150),
])
def test_end_turn_control_preserves_readable_hands(duel_fixture, tmp_path, width, height, scale):
    origin, fixture = duel_fixture
    html = '''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<base href="ORIGIN/"><link rel="stylesheet" href="static/styles.css"><link rel="stylesheet" href="static/fx.css"></head>
<body><main id="app" class="app duel-app"></main>
<script>window.ZZ_DEFER_BOOT=true;</script>
<script src="static/api-client.js"></script>
<script src="static/multiplayer-card-policy.js"></script>
<script src="static/duel-layout.js"></script><script src="static/duel-dom.js"></script>
<script src="static/fx-core.js"></script><script src="static/app.js"></script>
<script>
(async () => {
  const fixture = FIXTURE;
  const result = {};
  const phase = 'TEST_PHASE';
  catalog = fixture.catalog; state = fixture[phase]; appView = 'duel';
  settings.duelScale = SCALE;
  setAppHtml(renderDuelView());
  await document.fonts.ready;
  await Promise.all([...app.querySelectorAll('img')].map(image => image.complete
    ? Promise.resolve() : new Promise(resolve => { image.onload = image.onerror = resolve; })));
  await new Promise(resolve => setTimeout(resolve, 200));
  const card = document.querySelector('.cockpit.bottom .card.hand-card');
  const button = document.querySelector('.end-turn-action');
  const command = document.querySelector('.cockpit-command-row');
  const buttonRect = button?.getBoundingClientRect();
  const hands = [...document.querySelectorAll('.cockpit.bottom .card.hand-card')];
  result[phase] = {
    viewport: {width: innerWidth, height: innerHeight},
    scaledHandWidth: document.querySelector(".cockpit.bottom .hand-fan").style.getPropertyValue("--hand-w"),
    handWidth: card.offsetWidth, handHeight: card.offsetHeight,
    buttonWidth: button?.offsetWidth, buttonHeight: button?.offsetHeight,
    commandHeight: command.offsetHeight,
    handBottom: document.querySelector('.cockpit.bottom .hand-fan').getBoundingClientRect().bottom,
    commandTop: command.getBoundingClientRect().top,
    cockpitBottom: document.querySelector('.cockpit.bottom').getBoundingClientRect().bottom,
    commandBottom: command.getBoundingClientRect().bottom,
    buttonBottom: buttonRect?.bottom,
    buttonOverlapsHand: buttonRect && hands.some(card => {
      const rect = card.getBoundingClientRect();
      return rect.left < buttonRect.right && rect.right > buttonRect.left
        && rect.top < buttonRect.bottom && rect.bottom > buttonRect.top;
    }),
  };
  return result;
})().then(result => {
  parent.postMessage({layoutResult: result}, '*');
}).catch(error => {
  parent.postMessage({layoutError: error.stack}, '*');
});
</script></body></html>'''
    html = html.replace("ORIGIN", origin).replace("const fixture = FIXTURE;", f"const fixture = {json.dumps(fixture)};")
    html = html.replace("settings.duelScale = SCALE;", f"settings.duelScale = {scale};")
    measured = {}
    for phase in ("mana", "main"):
        page = tmp_path / f"{phase}.html"
        content = html.replace("const phase = 'TEST_PHASE';", f"const phase = '{phase}';")
        # A fixed iframe gives the app the exact viewport on every platform;
        # Chrome's outer window size includes browser decorations on Windows.
        page.write_text('''<!doctype html><meta charset="utf-8"><script>
addEventListener('message', ({data}) => {
  if (data.layoutError) document.body.setAttribute('data-layout-error', data.layoutError);
  if (!data.layoutResult) return;
  const output=document.createElement('script'); output.id='layout-result';
  output.type='application/json'; output.textContent=JSON.stringify(data.layoutResult); document.body.append(output);
});</script>''' + f'<iframe width="{width}" height="{height}" style="border:0" srcdoc="{html_escape.escape(content, quote=True)}"></iframe>', encoding="utf-8")
        result = subprocess.run([
            BROWSER, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={tmp_path / phase}",
            "--force-device-scale-factor=1", f"--window-size={width},{height}",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--virtual-time-budget=3000", "--dump-dom", page.as_uri(),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        assert result.returncode == 0, result.stderr
        match = re.search(r'<script id="layout-result" type="application/json">([^<]+)</script>', result.stdout)
        assert match, result.stdout[-1500:] + result.stderr[-500:]
        measured.update(json.loads(match[1]))
        assert measured[phase]["scaledHandWidth"], json.dumps(measured)
        assert measured[phase]["viewport"] == {"width": width, "height": height}
    main, mana = measured["main"], measured["mana"]
    assert 44 <= main["buttonWidth"] <= 72, json.dumps(measured)
    if width > 600:
        assert main["buttonWidth"] >= 60, json.dumps(measured)
    assert main["buttonWidth"] < main["handWidth"], json.dumps(measured)
    assert main["buttonHeight"] < main["handHeight"], json.dumps(measured)
    assert main["handWidth"] >= mana["handWidth"] - 2, json.dumps(measured)
    assert main["handBottom"] <= main["commandTop"] + 1, json.dumps(measured)
    assert main["commandBottom"] <= main["cockpitBottom"] + 1, json.dumps(measured)
    assert main["buttonBottom"] <= main["cockpitBottom"] + 1, json.dumps(measured)
    assert main["buttonOverlapsHand"] is False, json.dumps(measured)


@pytest.mark.parametrize("online,width,height", [
    (False, 1366, 768),
    (True, 1920, 1080),
])
def test_mulligan_pointer_does_not_leave_a_focused_card_over_its_neighbors(
    duel_fixture, tmp_path, online, width, height,
):
    origin, fixture = duel_fixture
    opening = GameSession(seed=123, mode="human-vs-ai", opponent_ai_difficulty="easy").state_dto()
    assert opening["prompt"]["kind"] == "mulligan"
    data = json.dumps({"catalog": fixture["catalog"], "opening": opening}, ensure_ascii=False).replace("<", "\\u003c")
    html = '''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><base href="ORIGIN/">
<link rel="stylesheet" href="static/styles.css"><link rel="stylesheet" href="static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;</script>
<script src="static/api-client.js"></script><script src="static/multiplayer-card-policy.js"></script>
<script src="static/duel-layout.js"></script><script src="static/duel-dom.js"></script>
<script src="static/fx-core.js"></script><script src="static/app.js"></script><script>
const fixture=FIXTURE;catalog=fixture.catalog;state=fixture.opening;appView="duel";
activeMatchPayload={multiplayer:ONLINE};settings.duelScale=100;
window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};render();window.__mulliganReady=true;
</script></body></html>'''.replace("ORIGIN", origin).replace("FIXTURE", data).replace("ONLINE", "true" if online else "false")
    page = tmp_path / "mulligan.html"
    page.write_text(html, encoding="utf-8")
    driver = r'''
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const {spawn,spawnSync}=require("node:child_process");
const WebSocket=globalThis.WebSocket||require("ws");
const [browser,profile,url,width,height]=process.argv.slice(1),delay=ms=>new Promise(r=>setTimeout(r,ms));
const chrome=spawn(browser,["--headless=new","--no-sandbox","--no-first-run","--disable-extensions",
  "--disable-breakpad","--disable-crash-reporter","--remote-debugging-port=0","--remote-allow-origins=*",
  "--window-size="+width+","+height,"--user-data-dir="+profile,"about:blank"],{stdio:"ignore",windowsHide:true});
(async()=>{let ws;try{
  const portFile=path.join(profile,"DevToolsActivePort");
  for(let i=0;!fs.existsSync(portFile);i++){if(i>100)throw Error("Chrome debug port did not open");await delay(100);}
  const port=fs.readFileSync(portFile,"utf8").split("\n")[0];
  const targets=await(await fetch("http://127.0.0.1:"+port+"/json/list")).json();
  ws=new WebSocket(targets.find(t=>t.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  let serial=0;const pending=new Map();
  ws.onmessage=e=>{const msg=JSON.parse(e.data);if(!msg.id)return;const p=pending.get(msg.id);
    pending.delete(msg.id);msg.error?p.reject(Error(JSON.stringify(msg.error))):p.resolve(msg.result);};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++serial;
    pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const r=await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  await send("Runtime.enable");await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride",{width:Number(width),height:Number(height),deviceScaleFactor:1,mobile:false});
  await send("Page.navigate",{url});
  for(let i=0;i<150;i++){if(await evaluate("Boolean(window.__mulliganReady)"))break;
    if(i===149)throw Error("mulligan page did not load");await delay(100);}
  await delay(300);
  const snapshot=()=>evaluate(`(()=>{
    const slots=[...document.querySelectorAll('.hand-fan.bottom .hand-slot')];
    return {selected:[...mulliganSelectedIids],active:document.activeElement?.dataset?.mulliganIid||null,
      slots:slots.map(slot=>{const card=slot.querySelector('.card'),button=slot.querySelector('.mulligan-toggle');
        const r=card.getBoundingClientRect(),b=button?.getBoundingClientRect();
        return {iid:card.dataset.cardIid,selected:card.classList.contains('mulligan-selected'),
          hover:slot.matches(':hover'),focus:slot.matches(':focus-within'),
          focusVisible:slot.matches(':has(:focus-visible)'),z:Number(getComputedStyle(slot).zIndex),
          rect:{left:r.left,right:r.right,top:r.top,bottom:r.bottom},
          button:b&&{x:b.left+b.width/2,y:b.top+b.height/2}};})};})()`);
  const move=async (x,y)=>{await send("Input.dispatchMouseEvent",{type:"mouseMoved",x,y});await delay(220);};
  const click=async (x,y)=>{await send("Input.dispatchMouseEvent",{type:"mousePressed",x,y,button:"left",clickCount:1});
    await send("Input.dispatchMouseEvent",{type:"mouseReleased",x,y,button:"left",clickCount:1});await delay(220);};
  const key=async (name,code,number)=>{await send("Input.dispatchKeyEvent",{type:"keyDown",key:name,code,windowsVirtualKeyCode:number});
    await send("Input.dispatchKeyEvent",{type:"keyUp",key:name,code,windowsVirtualKeyCode:number});await delay(100);};
  let state=await snapshot();assert.ok(state.slots.length>=5,"opening hand must have selectable cards");
  const right=4,left=3,rightId=state.slots[right].iid,leftId=state.slots[left].iid;
  assert.ok(state.slots[right].button,"mulligan button is present");
  await move(state.slots[right].button.x,state.slots[right].button.y);
  state=await snapshot();await click(state.slots[right].button.x,state.slots[right].button.y);
  state=await snapshot();assert.ok(state.selected.includes(Number(rightId)),"pointer selects the intended card");
  await move(4,4);state=await snapshot();
  assert.ok(state.slots[right].selected&&state.slots[right].focus&&!state.slots[right].hover,
    "selected card keeps its selection and pointer focus after leaving");
  assert.equal(state.slots[right].focusVisible,false,"mouse focus must not appear as keyboard focus");
  assert.ok(state.slots[right].z<100,"mouse-focused card must stop covering its neighbors after pointer leaves: "+JSON.stringify(state));
  let r=state.slots[left].rect;await move(r.left+8,(r.top+r.bottom)/2);state=await snapshot();
  assert.ok(state.slots[left].hover,"neighbor can be hovered");
  const hit=await evaluate(`(()=>{const slots=[...document.querySelectorAll('.hand-fan.bottom .hand-slot')];
    const a=slots[${left}].querySelector('.card').getBoundingClientRect(),b=slots[${right}].querySelector('.card').getBoundingClientRect();
    const x=(Math.max(a.left,b.left)+Math.min(a.right,b.right))/2,y=(Math.max(a.top,b.top)+Math.min(a.bottom,b.bottom))/2;
    return {overlap:Math.min(a.right,b.right)>Math.max(a.left,b.left),owner:document.elementFromPoint(x,y)?.closest('.hand-slot')===slots[${left}]};})()`);
  assert.ok(hit.overlap&&hit.owner,"hovered neighbor must be on top in the overlap: "+JSON.stringify(hit));
  await move(state.slots[left].button.x,state.slots[left].button.y);state=await snapshot();
  await click(state.slots[left].button.x,state.slots[left].button.y);state=await snapshot();
  assert.ok(state.selected.includes(Number(leftId))&&state.selected.includes(Number(rightId)),"adjacent cards can both be selected");
  await move(4,4);
  for(let i=0;i<4;i++){await key("Tab","Tab",9);state=await snapshot();if(state.active)break;}
  assert.ok(state.active,"keyboard can focus a mulligan button");
  const focused=state.slots.find(slot=>slot.iid===state.active);
  assert.ok(focused?.focusVisible&&focused.z>=100,"keyboard focus remains visibly raised");
  const previous=state.selected.includes(Number(state.active));const activeId=Number(state.active);
  await key(" ","Space",32);state=await snapshot();
  assert.notEqual(state.selected.includes(activeId),previous,"keyboard can toggle the focused card");
  const keyboardSlot=state.slots.find(slot=>slot.iid===String(activeId));
  assert.ok(keyboardSlot?.focusVisible&&keyboardSlot.z>=100,"keyboard focus survives the selection redraw");
  const other=keyboardSlot.iid===leftId?right:left;r=state.slots[other].rect;
  await move(r.left+8,(r.top+r.bottom)/2);state=await snapshot();
  assert.ok(state.slots[other].hover&&state.slots[other].z>state.slots.find(slot=>slot.iid===String(activeId)).z,
    "hovered card must appear above a different keyboard-focused card");
  const focusedIndex=state.slots.findIndex(slot=>slot.iid===String(activeId));
  await move(state.slots[focusedIndex].button.x,state.slots[focusedIndex].button.y);state=await snapshot();
  await click(state.slots[focusedIndex].button.x,state.slots[focusedIndex].button.y);await move(4,4);state=await snapshot();
  assert.ok(!state.slots[focusedIndex].focusVisible&&state.slots[focusedIndex].z<100,
    "a mouse click after keyboard focus must not leave the card raised");
  console.log("MULLIGAN_POINTER_AND_KEYBOARD_OK");
}finally{ws?.close();if(process.platform==="win32")spawnSync("taskkill",["/PID",String(chrome.pid),"/T","/F"],{stdio:"ignore",windowsHide:true});else chrome.kill();}})()
 .catch(error=>{console.error(error.stack);process.exitCode=1;});
'''
    result = subprocess.run(
        ["node", "-e", driver, BROWSER, str(tmp_path / "chrome"), page.as_uri(), str(width), str(height)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=55,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MULLIGAN_POINTER_AND_KEYBOARD_OK" in result.stdout
