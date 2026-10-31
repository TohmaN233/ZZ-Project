import base64
import html
import json
import os
import re
import subprocess

import pytest

from test_frontend_fx import BROWSER, duel_fx_fixture  # noqa: F401


def test_multiplayer_replay_list_opens_player_view_and_steps_in_real_browser(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome is required for the replay UI check")
    origin = duel_fx_fixture["origin"]
    fixture = json.dumps(duel_fx_fixture["fixture"], ensure_ascii=False).replace("<", "\\u003c")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app"></main><script>
window.ZZ_DEFER_BOOT = true;
window.zzDesktop = {
  listMultiplayerReplays: async () => [{id: "replay-id", matchId: "match-1", createdAt: "2026-10-31T00:00:00Z",
    finished: true, complete: false, missingRevisions: 1, missingLogEvents: 2}],
  readMultiplayerReplay: async () => window.testReplay,
};
</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult = value => parent.postMessage({ replayPayload: btoa(unescape(encodeURIComponent(JSON.stringify(value)))) }, "*");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const fixture = FIXTURE;
  const assert = (value, message) => { if (!value) throw new Error(message); };
  catalog = fixture.catalog;
  settings.uiLanguage = "zh";
  const first = structuredClone(fixture.main);
  first.mode = "multiplayer";
  first.humanSide = first.players.human.side;
  first.animationEvents = [{ type: "phase", phase: "main" }];
  const second = structuredClone(first);
  second.turn = first.turn + 1;
  window.testReplay = { metadata: { matchId: "match-1", finished: true, complete: false,
      missingRevisions: 1, missingLogEvents: 2 },
    trace: { logEvents: [{eventIndex: 0, snapshotIndex: 1, type: "optional_effect", used: true}],
      stateSnapshots: [{state: first, animationEvents: []}, {state: second, animationEvents: []}] } };
  appView = AI_TRAINING_VIEW;
  await refreshMultiplayerReplays();
  const entry = app.querySelector('[data-multiplayer-replay="replay-id"]');
  assert(entry && entry.textContent.includes("记录不完整"), "replay list or incomplete status is missing");
  entry.click();
  await delay(100);
  assert(app.querySelector(".replay-duel-board"), "replay must render the actual board, not the fallback");
  assert(codemanReplayFrameAnimationEvents(1).length === 1, "each revision's animation must be replayed even when identical");
  assert(app.querySelectorAll('.cockpit.top .card[data-fx-face="down"]').length === fixture.hiddenHandCount,
    "the opponent hand must remain hidden");
  assert(app.textContent.includes("记录不完整"), "missing recording warning must remain visible");
  app.querySelector('[data-codeman-replay-step="1"]').click();
  await delay(30);
  assert(codemanReplayState.index === 1, "replay step did not advance");
  app.querySelector("[data-codeman-replay-close]").click();
  await delay(30);
  assert(appView === AI_TRAINING_VIEW && app.querySelector('[data-multiplayer-replay="replay-id"]'),
    "closing the replay must return to its list");
  postResult({ ok: true });
})().catch(error => postResult({ error: String(error && error.stack || error) }));
</script></body></html>'''
    child = child.replace("ORIGIN", origin).replace("const fixture = FIXTURE;", f"const fixture = {fixture};")
    outer = '''<!doctype html><html><head><meta charset="utf-8"><script>
addEventListener("message", ({data}) => {
  if (!data.replayPayload) return;
  const result = document.createElement("script"); result.id = "replay-result"; result.type = "application/json";
  result.textContent = data.replayPayload; document.body.append(result);
});
</script></head><body><iframe width="1280" height="900" srcdoc="CHILD"></iframe></body></html>'''
    duel_fx_fixture["handler"].test_document = outer.replace("CHILD", html.escape(child, quote=True))
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    command = [BROWSER, "--headless=new", "--no-first-run", "--disable-extensions", "--no-sandbox",
               "--window-size=1280,900", f"--user-data-dir={profile}", "--virtual-time-budget=12000", "--dump-dom",
               f"{origin}/__duel_fx_test__?run={tmp_path.name}"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stderr[-1500:]
    match = re.search(r'<script id="replay-result" type="application/json">([^<]+)</script>', result.stdout)
    assert match, result.stdout[-2500:] + result.stderr[-1500:]
    payload = json.loads(base64.b64decode(match[1]).decode("utf-8"))
    assert payload.get("ok") is True, payload
