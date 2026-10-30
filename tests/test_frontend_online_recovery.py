"""Exercise the real online renderer and handlers across connection loss."""
from __future__ import annotations

import re
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "zz/web/static/app.js").read_text(encoding="utf-8")


def _source(name: str) -> str:
    match = re.search(rf"^(?:async )?function {name}\(", APP_SOURCE, re.MULTILINE)
    assert match, name
    end = re.search(r"^(?:async )?function \w+\(", APP_SOURCE[match.end():], re.MULTILINE)
    return APP_SOURCE[match.start():match.end() + end.start()] if end else APP_SOURCE[match.start():]


HARNESS = r"""
const assert = require('node:assert/strict');
const ONLINE_VIEW = 'online', ONLINE_SERVER_URL = 'wss://example.test/multiplayer', LAN_SERVER_URL = 'ws://example.test';
let appView = 'duel', state = {prompt: null, marker: 'prior-duel'};
let activeMatchPayload = {multiplayer: true}, lastAppliedMultiplayerViewKey = 'match:4:hash';
let pendingChoicePromptId = null, lanPendingCreateRoom = false, lanPendingJoin = null;
let multiplayerUi = {mode:'online', status:'IN_MATCH', url: ONLINE_SERVER_URL, displayName:'Player',
  playerId:'player-1', matchId:'match', room:null, view:state, lan:{state:'STOPPED', discovered:[]}};
let onlineBattleLogHistory = {matchId:null, rows:[], missingEarlier:false};
let logModalOpen = true;
let commands = [], rendered = [];
const window = {zzMultiplayer:{status(){}}};
const app = {querySelector() { return null; }};
function t(key) { return key; }
function esc(value) { return String(value); }
function hydrateMultiplayerViewAssets(view) { return view; }
function isOnlineOpeningChoice() { return false; }
function currentOnlineRoomPlayer() { return null; }
function clearDuelUiState() {}
function stageDuelState(view) { state = view; }
function render(error) { rendered.push({view:appView,error}); }
function renderShellHeader() { return ''; }
function renderLanControls() { return ''; }
function renderOnlinePlayerProfile() { return ''; }
function renderOnlineDeckPicker() { return ''; }
function battleLogText(row) { return String(row.eventIndex); }
function persistOnlineDisplayName() { return 'Player'; }
function onlineInputValue(selector, fallback) { return fallback || ''; }
function normalizeLanUrl(value) { return value; }
async function runMultiplayerCommand(...args) { commands.push(args); return {}; }
"""


def _run(script: str) -> None:
    names = ("multiplayerBridge", "isOnlineDuel", "multiplayerErrorText", "applyMultiplayerSnapshot",
             "connectOnlineServer", "renderOnlineRoom", "renderOnlineGamePage", "battleLogRows", "renderBattleLogModal",
             "onlineBattleLogGapCursor", "mergeOnlineBattleLogPage", "requestOnlineLogHistory")
    program = HARNESS + "\n" + "\n".join(_source(name) for name in names) + "\n" + script
    result = subprocess.run(["node"], input=program, cwd=ROOT, text=True,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_automatic_reconnect_offers_original_room_and_retry():
    _run(r"""
const room = {roomCode:'ABC123',status:'RUNNING',players:[]};
const view = {revision:4,stateHash:'hash',prompt:null,marker:'prior-duel'};
applyMultiplayerSnapshot({status:'RECONNECTING', room, view, matchId:'match', canReconnect:true,
  reconnectFailures:1, reconnectAttemptActive:true, lastError:null});
assert.equal(appView, 'duel', 'automatic reconnect must keep the current duel visible');
assert.equal(state.marker, 'prior-duel');
applyMultiplayerSnapshot({status:'ERROR', room, view, matchId:'match', canReconnect:true,
  canRetryReconnect:true, recoveryRoomCode:'ABC123', reconnectFailures:5,
  lastError:{code:'RECONNECT_EXHAUSTED',message:'reconnect failed repeatedly'}});
assert.equal(appView, 'online', 'exhausted automatic retries return to the room page');
const page = renderOnlineGamePage();
assert.ok(page.includes('ABC123'), 'original room code remains visible');
assert.ok(page.includes('data-online-reconnect'), 'manual recovery of the same match is offered');
""")


def test_recovery_from_persisted_session_shows_room_without_room_snapshot():
    _run(r"""
appView = 'online'; state = null; activeMatchPayload = {};
applyMultiplayerSnapshot({status:'ERROR',room:null,view:null,matchId:'match',canReconnect:true,
  canRetryReconnect:true,recoveryRoomCode:'ABC123',reconnectFailures:5,
  lastError:{code:'RECONNECT_EXHAUSTED',message:'reconnect failed repeatedly'}});
const page = renderOnlineGamePage();
assert.ok(page.includes('ABC123'), 'persisted recovery must expose its room code');
assert.ok(page.includes('data-online-reconnect'), 'persisted recovery must offer a retry');
""")


def test_connect_with_recovery_retries_instead_of_clearing_credentials():
    _run(r"""
multiplayerUi = {...multiplayerUi, status:'ERROR', canReconnect:true, canRetryReconnect:true,
  recoveryRoomCode:'ABC123', reconnectFailures:5};
(async () => {
  await connectOnlineServer();
  assert.deepEqual(commands.map(command => command[0]), ['reconnect'],
    'retry must not call disconnect or connect as a new player');
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
""")


def test_online_log_accumulates_without_duplicates_and_survives_reconnect():
    _run(r"""
function view(indices, hasEarlierEvents) {
  return {logEvents: indices.map(eventIndex => ({type:'action',eventIndex})),
    logHistory:{hasEarlierEvents, firstEventIndex:indices[0] ?? null, lastEventIndex:indices.at(-1) ?? null}};
}
state = view([0,1], false);
assert.deepEqual(battleLogRows().map(row=>row.eventIndex), [0,1]);
state = view([1,2], true);
assert.deepEqual(battleLogRows().map(row=>row.eventIndex), [0,1,2],
  'overlapping server windows must preserve earlier logs exactly once');
state = null;
assert.deepEqual(battleLogRows(), []);
state = view([2,3], true);
assert.deepEqual(battleLogRows().map(row=>row.eventIndex), [0,1,2,3],
  'same-match reconnect must preserve earlier visible entries');
assert.ok(!renderBattleLogModal().includes('onlineEarlierLogUnavailable'),
  'history captured from the start should not claim earlier entries were lost');
multiplayerUi.matchId = 'other-match';
state = view([0], false);
assert.deepEqual(battleLogRows().map(row=>row.eventIndex), [0], 'new matches must not inherit prior logs');
""")


def test_online_log_discloses_when_older_history_was_not_received():
    _run(r"""
state = {logEvents:[{type:'action',eventIndex:120}],
  logHistory:{hasEarlierEvents:true,firstEventIndex:120,lastEventIndex:120}};
assert.deepEqual(battleLogRows().map(row=>row.eventIndex), [120]);
assert.ok(renderBattleLogModal().includes('onlineEarlierLogUnavailable'),
  'a fresh recovery starting mid-history must explicitly say earlier records are unavailable');
""")


def test_online_log_can_fill_a_gap_after_reconnect():
    _run(r"""
function view(indices) {
  return {logEvents:indices.map(eventIndex => ({type:'action',eventIndex})),
    logHistory:{canPage:true,hasEarlierEvents:indices[0]>0,
      firstEventIndex:indices[0] ?? null,lastEventIndex:indices.at(-1) ?? null,
      latestEventIndex:indices.at(-1) ?? null}};
}
state = view([0,1,2]); battleLogRows();
state = view([9,10]); battleLogRows();
assert.equal(onlineBattleLogGapCursor(), 9, 'request backwards from the newer side of a gap');
assert.ok(renderBattleLogModal().includes('data-online-log-earlier'));
(async () => {
  await requestOnlineLogHistory();
  assert.deepEqual(commands.at(-1), ['requestLogHistory',{matchId:'match',beforeEventIndex:9}]);
  mergeOnlineBattleLogPage({matchId:'other-match',beforeEventIndex:9,
    events:[{type:'action',eventIndex:3}],firstEventIndex:3,lastEventIndex:3,hasEarlierEvents:true});
  assert.equal(onlineBattleLogGapCursor(), 9, 'another match cannot modify this history');
  mergeOnlineBattleLogPage({matchId:'match',beforeEventIndex:9,
    events:[3,4,5,6,7,8].map(eventIndex=>({type:'action',eventIndex})),
    firstEventIndex:3,lastEventIndex:8,hasEarlierEvents:true});
  assert.deepEqual(battleLogRows().map(row=>row.eventIndex), [0,1,2,3,4,5,6,7,8,9,10]);
  assert.equal(onlineBattleLogGapCursor(), null);
  assert.ok(!renderBattleLogModal().includes('data-online-log-earlier'));
  assert.ok(!renderBattleLogModal().includes('onlineEarlierLogUnavailable'));
})().catch(error => {console.error(error.stack);process.exitCode=1;});
""")


def test_online_log_can_page_when_the_snapshot_could_not_fit_any_rows():
    _run(r"""
state = {logEvents:[],logHistory:{canPage:true,hasEarlierEvents:true,
  firstEventIndex:null,lastEventIndex:null,latestEventIndex:27}};
battleLogRows();
assert.equal(onlineBattleLogGapCursor(), 28);
assert.ok(renderBattleLogModal().includes('data-online-log-earlier'));
""")


def test_online_log_page_from_desktop_snapshot_is_merged_without_replaying_state():
    _run(r"""
state = {revision:4,stateHash:'hash',logEvents:[{type:'action',eventIndex:3}],
  logHistory:{canPage:true,hasEarlierEvents:true,firstEventIndex:3,lastEventIndex:3,latestEventIndex:3}};
battleLogRows();
const priorState = state;
applyMultiplayerSnapshot({status:'IN_MATCH',room:null,matchId:'match',view:state,
  logHistoryPage:{matchId:'match',beforeEventIndex:3,events:[0,1,2].map(eventIndex=>({type:'action',eventIndex})),
    firstEventIndex:0,lastEventIndex:2,hasEarlierEvents:false}});
assert.equal(state, priorState, 'a history page must not restage or animate the board');
assert.deepEqual(battleLogRows().map(row=>row.eventIndex), [0,1,2,3]);
assert.equal(onlineBattleLogGapCursor(), null);
assert.throws(() => mergeOnlineBattleLogPage({matchId:'match',beforeEventIndex:3,
  events:[{type:'action',eventIndex:1}]}), /did not reach/, 'a non-progressing page cannot silently loop');
state = {logEvents:[null]};
assert.throws(() => battleLogRows(), /valid event index/, 'malformed online rows must not disappear silently');
""")


def test_recovery_button_works_in_the_real_browser(tmp_path):
    browser = next((path for path in (
        shutil.which("google-chrome"), shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ) if path and Path(path).is_file()), None)
    if not browser:
        pytest.skip("headless Chrome/Chromium is required")
    base = (ROOT / "zz/web/static").as_uri() + "/"
    page = tmp_path / "online-recovery.html"
    page.write_text(r'''<!doctype html><html><head><meta charset="utf-8"><base href="BASE">
<link rel="stylesheet" href="styles.css"></head><body><main id="app"></main><script>
window.ZZ_DEFER_BOOT = true;
const snapshot = {status:'ERROR', mode:'online', room:null, view:null, matchId:'match',
  canReconnect:true, canRetryReconnect:true, recoveryRoomCode:'ABC123', reconnectFailures:5,
  lastError:{code:'RECONNECT_EXHAUSTED', message:'reconnect failed repeatedly'}};
window.commands = [];
window.zzMultiplayer = {
  status: async () => snapshot,
  reconnect: async () => { window.commands.push('reconnect'); return {}; },
  requestLogHistory: async (payload) => { window.commands.push({method:'requestLogHistory',payload}); return {}; },
  disconnect: async () => { window.commands.push('disconnect'); return {}; },
  connect: async () => { window.commands.push('connect'); return {}; },
};
</script><script src="multiplayer-card-policy.js"></script><script src="duel-layout.js"></script>
<script src="duel-dom.js"></script><script src="app.js"></script><script>
(async () => {
  appView = ONLINE_VIEW;
  applyMultiplayerSnapshot(snapshot);
  const button = document.querySelector('[data-online-reconnect]');
  const hasCode = document.getElementById('app').innerText.includes('ABC123');
  if (button) button.click();
  await new Promise(resolve => setTimeout(resolve, 100));
  activeMatchPayload = {multiplayer:true}; multiplayerUi.matchId = 'match';
  const logEvent = eventIndex => ({type:'action',eventIndex,actorSide:'P1',actionKind:'end_turn'});
  state = {mode:'multiplayer',humanSide:'P1',logEvents:[logEvent(0)],
    logHistory:{hasEarlierEvents:false,firstEventIndex:0,lastEventIndex:0}};
  battleLogRows();
  state = {mode:'multiplayer',humanSide:'P1',logEvents:[logEvent(1)],
    logHistory:{hasEarlierEvents:true,firstEventIndex:1,lastEventIndex:1}};
  logModalOpen = true;
  app.innerHTML = renderBattleLogModal();
  const logEntries = document.querySelectorAll('.battle-log-entry').length;
  const logReadable = app.innerText.includes('回合结束');
  window.zzMultiplayer.status = async () => null;
  multiplayerUi.status = 'IN_MATCH';
  state = {mode:'multiplayer',humanSide:'P1',logEvents:[logEvent(4)],
    logHistory:{canPage:true,hasEarlierEvents:true,firstEventIndex:4,lastEventIndex:4,latestEventIndex:4}};
  battleLogRows();
  app.innerHTML = renderBattleLogModal();
  const historyButton = document.querySelector('[data-online-log-earlier]');
  if (historyButton) historyButton.click();
  await new Promise(resolve => setTimeout(resolve, 100));
  const result = document.createElement('pre'); result.id = 'recovery-result';
  result.textContent = JSON.stringify({hasCode, hasButton: Boolean(button), commands: window.commands,
    logEntries, logReadable, hasHistoryButton:Boolean(historyButton)});
  document.body.append(result);
})().catch(error => { const result=document.createElement('pre'); result.id='recovery-result';
  result.textContent=JSON.stringify({error:error.stack}); document.body.append(result); });
</script></body></html>'''.replace("BASE", base), encoding="utf-8")
    result = subprocess.run([
        browser, "--headless=new", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
        "--virtual-time-budget=2500", "--dump-dom", page.as_uri(),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stderr
    match = re.search(r'<pre id="recovery-result">([^<]+)</pre>', result.stdout)
    assert match, result.stdout[-2000:] + result.stderr[-1000:]
    actual = json.loads(match[1])
    assert actual == {"hasCode": True, "hasButton": True, "commands": ["reconnect",
                      {"method":"requestLogHistory","payload":{"matchId":"match","beforeEventIndex":4}}],
                      "logEntries": 2, "logReadable": True, "hasHistoryButton": True}
