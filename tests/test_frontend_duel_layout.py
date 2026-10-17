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
<base href="ORIGIN/"><link rel="stylesheet" href="static/styles.css"></head>
<body><main id="app" class="app duel-app"></main>
<script>window.ZZ_DEFER_BOOT=true;</script>
<script src="static/api-client.js"></script>
<script src="static/multiplayer-card-policy.js"></script>
<script src="static/duel-layout.js"></script><script src="static/app.js"></script>
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
