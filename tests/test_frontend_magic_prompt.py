"""Browser regressions for combat stats on Magic cards during effect prompts."""

import pytest

from test_effect_resolution_order_oct29 import setup
from test_frontend_fx import BROWSER, duel_fx_fixture
from test_frontend_oct29_feedback import PAGE, _run_live_page


def test_magic_effect_prompt_hides_magic_stats_and_keeps_other_prompt_data(
    duel_fx_fixture, tmp_path
):
    if BROWSER is None:
        pytest.skip("Chrome is required for live effect prompt input")

    runner = setup("yellow_011_03_02c_00")
    cast_state = None
    for action in runner.spec["actions"][:3]:
        cast_state = runner._run_action(action)["state"]

    assert cast_state is not None
    assert cast_state["prompt"]["kind"] == "effect_target"
    source = runner.session._pending_effect["source"]
    prompt_options = cast_state["prompt"]["options"]
    candidates = [
        {
            "id": option["id"],
            "iid": option["cardIid"],
            "ownerSide": option["ownerSide"],
            "bp": option.get("effectiveBp", option.get("bp")),
            "dp": option.get("effectiveDp", option.get("dp")),
        }
        for option in prompt_options
        if option.get("cardIid")
    ]
    assert candidates and all(candidate["bp"] and candidate["dp"] for candidate in candidates)

    main = duel_fx_fixture["fixture"]
    browser_fixture = {
        **main,
        "main": cast_state,
        "magicIid": source.iid,
        "sourceSide": source.owner.side.name,
        "candidates": candidates,
        "forceLife": cast_state["players"]["human"]["forces"][0]["life"],
    }
    old_session = duel_fx_fixture["handler"].app.session
    duel_fx_fixture["handler"].app.session = runner.session

    body = r'''
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  const waitFor=async(fn,label)=>{
    const end=performance.now()+10000;
    while(performance.now()<end){
      if(fn())return;
      await delay(25);
    }
    throw new Error(label+JSON.stringify({prompt:activePrompt(),active:activeAnimationEvent?.type,
      pending:!!pendingVisualState,error:state.error}));
  };
  render();
  await waitFor(()=>activePrompt()?.kind==="effect_target"&&!pendingVisualState,
    "the cast opens its real effect target prompt");

  const magicSelector='[data-board-card-anchor="'+fixture.sourceSide+':card:'+fixture.magicIid+'"]';
  const magicCard=app.querySelector(magicSelector);
  assert(magicCard&&magicCard.closest(".hand-cards"),"the pending Magic remains in its public hand zone");
  assert(magicCard.hasAttribute("data-card-iid"),"the pending Magic responds to real card input");
  magicCard.click();
  const detail=app.querySelector(".card-detail-modal .card-detail-panel");
  assert(detail,"clicking the pending Magic opens its real card detail");

  const languages=[
    ["zh","选择效果目标","选择一个效果目标。"],
    ["ja","効果対象を選択","効果対象を1つ選択してください。"],
    ["en","Choose effect target","Choose one effect target."],
  ];
  for(const [language,title,note] of languages){
    settings.uiLanguage=language;
    setAppHtml(renderDuelView());
    const card=app.querySelector(magicSelector);
    const cardText=card.textContent;
    assert(!/\b0\s*\/\s*0\b/.test(cardText),"Magic card board art omits 0/0 in "+language);
    assert(!card.querySelector(".card-stats, .card-field-stats, .card-overlay b"),
      "Magic card board art omits BP/DP elements in "+language);
    const detailPanel=app.querySelector(".card-detail-modal .card-detail-panel");
    assert(detailPanel&&!detailPanel.querySelector(".card-detail-meta").textContent.includes("0/0"),
      "Magic detail omits the combat-stat slot in "+language);

    const modal=app.querySelector(".effect-prompt-modal");
    assert(modal&&modal.querySelector(".payment-title").textContent===title,
      "the effect prompt title is localized in "+language);
    assert(modal.querySelector(".payment-note").textContent===note,
      "the effect prompt note is localized in "+language);
    for(const target of fixture.candidates){
      const fieldCard=app.querySelector('[data-board-card-anchor="'+target.ownerSide+':card:'+target.iid+'"]');
      const fieldStats=fieldCard?.querySelector(".card-field-stats")?.textContent||"";
      assert(fieldStats.includes("BP "+target.bp)&&fieldStats.includes("DP "+target.dp),
        "the Field Minion keeps its board BP/DP in "+language);
      const choice=modal.querySelector('[data-option="'+target.id+'"]');
      assert(choice&&choice.textContent.includes(target.bp+"/"+target.dp),
        "the real Minion choice keeps its BP/DP in "+language);
      assert(choice.querySelector(".force-choice-name").textContent,
        "the real Minion choice keeps its name in "+language);
    }
  }

  const forceLife=[...app.querySelectorAll(".cockpit .force-life")].map(node=>node.textContent.trim());
  assert(forceLife.includes(String(fixture.forceLife)),"Force life remains visible during the effect prompt");
  app.querySelector(".card-detail-modal [data-close-detail]").click();
  assert(!app.querySelector(".card-detail-modal"),"the real card-detail close input restores the prompt");

  settings.uiLanguage="zh";setAppHtml(renderDuelView());
  const first=fixture.candidates[0];
  const firstButton=app.querySelector('.effect-prompt-modal [data-option="'+first.id+'"]');
  assert(firstButton&&!firstButton.disabled,"the first real Minion target is clickable");
  firstButton.click();
  await waitFor(()=>activePrompt()?.kind==="effect_target"&&activePrompt().id!==fixture.main.prompt.id,
    "the HTTP-backed target choice advances the Magic effect");
  await waitFor(()=>!activeAnimationEvent&&!pendingVisualState&&!stagedDuelStateQueue.length,
    "the first target response animations settle");
  const secondMagic=app.querySelector(magicSelector);
  assert(secondMagic&&secondMagic.closest(".resolving-zone")&&!/\b0\s*\/\s*0\b/.test(secondMagic.textContent),
    "the Magic still has no 0/0 while its next clause is prompting");
  assert(!state.error,"the real target choice completes without a frontend error");
  return {ok:true,languages:languages.map(([language])=>language),targetCount:fixture.candidates.length};'''

    try:
        page = PAGE.replace("settings.reducedMotion=false", "settings.reducedMotion=true").replace(
            "await ZZFx.prepare();", ""
        )
        result = _run_live_page(
            {**duel_fx_fixture, "fixture": browser_fixture},
            tmp_path,
            page.replace("BODY", body),
        )
        assert result["languages"] == ["zh", "ja", "en"]
    finally:
        duel_fx_fixture["handler"].app.session = old_session


def test_cannot_activate_effect_is_localized_in_real_card_details(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("Chrome is required for live card-detail rendering")

    from test_ex02c_link_activation_combat import eugeo_switch_board

    session, _owner, _source, enemy = eugeo_switch_board()
    main = session.state_dto()
    enemy_dto = next(
        card
        for player in main["players"].values()
        for card in player["field"]
        if card["iid"] == enemy.iid
    )
    assert any(effect["kind"] == "cannot_activate" for effect in enemy_dto["activeEffects"])

    browser_fixture = {
        **duel_fx_fixture["fixture"],
        "main": main,
        "enemyIid": enemy.iid,
        "enemySide": enemy.owner.side.name,
    }
    old_session = duel_fx_fixture["handler"].app.session
    duel_fx_fixture["handler"].app.session = session

    body = r'''
  window.ZZDuelRuntime={render:window.ZZApp.renderDuelView};
  render();
  const selector='[data-board-card-anchor="'+fixture.enemySide+':card:'+fixture.enemyIid+'"]';
  const target=app.querySelector(selector);
  assert(target&&target.hasAttribute("data-card-iid"),"the engine-restricted Minion is available for detail input");
  target.click();

  const expected=[
    ["zh","直到下个准备阶段结束都不能激活","现有效果"],
    ["ja","次のスタンバイ終了時までアクティブにならない","適用中の効果"],
    ["en","Cannot become Active until the end of your next Standby Phase","Active effects"],
  ];
  for(const [language,copy,effectsTitle] of expected){
    settings.uiLanguage=language;
    setAppHtml(renderDuelView());
    const panel=app.querySelector(".card-detail-modal .card-detail-panel");
    assert(panel&&panel.getBoundingClientRect().width>0,"card details remain visible in "+language);
    const heading=panel.querySelector(".active-effect-title");
    const rows=panel.querySelectorAll(".active-effect-item");
    assert(heading&&heading.textContent===effectsTitle,"the active-effect heading is localized in "+language);
    assert(rows.length===1&&rows[0].textContent===copy,
      "cannot_activate uses its exact localized copy in "+language);
    assert(panel.querySelector(".card-detail-title"),"the Minion identity remains visible in "+language);
  }
  return {ok:true,languages:expected.map(([language])=>language)};'''

    try:
        page = PAGE.replace("settings.reducedMotion=false", "settings.reducedMotion=true").replace(
            "await ZZFx.prepare();", ""
        )
        result = _run_live_page(
            {**duel_fx_fixture, "fixture": browser_fixture},
            tmp_path,
            page.replace("BODY", body),
        )
        assert result["languages"] == ["zh", "ja", "en"]
    finally:
        duel_fx_fixture["handler"].app.session = old_session
