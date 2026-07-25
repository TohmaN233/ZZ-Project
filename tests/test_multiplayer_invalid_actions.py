from zz.multiplayer.actions import CHOOSE_PROMPT_OPTION, SURRENDER, SubmittedAction
from zz.multiplayer.match import AuthoritativeMatch, InitialMatchSpec


def _choice(
    match: AuthoritativeMatch,
    *,
    player_id: str,
    client_action_id: str,
    option_id: str,
    expected_revision: int | None = None,
) -> SubmittedAction:
    prompt = match.session.prompt
    assert prompt is not None
    return SubmittedAction(
        match_id=match.match_id,
        player_id=player_id,
        client_action_id=client_action_id,
        expected_revision=match.revision if expected_revision is None else expected_revision,
        action={
            "kind": CHOOSE_PROMPT_OPTION,
            "promptId": prompt["id"],
            "optionId": option_id,
            "payload": {},
        },
    )


def test_invalid_and_out_of_turn_actions_do_not_mutate_state() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="invalid", seed=201))
    initial_hash = match.state_hash()

    out_of_turn = match.submit_action(_choice(
        match,
        player_id="player_2",
        client_action_id="out-of-turn",
        option_id="keep",
    ))
    assert out_of_turn.accepted is False
    assert out_of_turn.rejection.code == "NOT_YOUR_TURN"
    assert match.revision == 0
    assert match.state_hash() == initial_hash

    illegal_card_or_target = match.submit_action(_choice(
        match,
        player_id="player_1",
        client_action_id="illegal-option",
        option_id="play-card-iid-999999",
    ))
    assert illegal_card_or_target.accepted is False
    assert illegal_card_or_target.rejection.code == "INVALID_ACTION"
    assert match.revision == 0
    assert match.state_hash() == initial_hash


def test_revision_and_action_id_are_idempotent() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="dedupe", seed=202))
    submitted = _choice(
        match,
        player_id="player_1",
        client_action_id="keep-p1",
        option_id="keep",
    )

    accepted = match.submit_action(submitted)
    assert accepted.accepted is True
    assert accepted.revision == 1
    accepted_hash = match.state_hash()

    duplicate = match.submit_action(submitted)
    assert duplicate is accepted
    assert match.revision == 1
    assert len(match.action_log) == 1
    assert match.state_hash() == accepted_hash

    changed_duplicate = SubmittedAction(
        match_id=match.match_id,
        player_id="player_1",
        client_action_id="keep-p1",
        expected_revision=1,
        action={"kind": SURRENDER},
    )
    rejected_duplicate = match.submit_action(changed_duplicate)
    assert rejected_duplicate.accepted is False
    assert rejected_duplicate.rejection.code == "DUPLICATE_ACTION"
    assert match.revision == 1

    stale = match.submit_action(_choice(
        match,
        player_id="player_2",
        client_action_id="stale-p2",
        option_id="keep",
        expected_revision=0,
    ))
    assert stale.accepted is False
    assert stale.rejection.code == "STALE_REVISION"
    assert match.revision == 1
    assert match.state_hash() == accepted_hash


def test_invalid_payment_is_rejected_before_prompt_or_state_mutation() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="payment", seed=777))
    for index in range(3):
        prompt = match.session.prompt
        owner = match.prompt_owner_id()
        assert prompt is not None and owner is not None
        result = match.submit_action(SubmittedAction(
            match_id=match.match_id,
            player_id=owner,
            client_action_id=f"setup-{index}",
            expected_revision=match.revision,
            action={
                "kind": CHOOSE_PROMPT_OPTION,
                "promptId": prompt["id"],
                "optionId": prompt["options"][0]["id"],
                "payload": {},
            },
        ))
        assert result.accepted is True

    prompt = match.session.prompt
    owner = match.prompt_owner_id()
    assert prompt is not None and owner is not None
    play_option = next(option for option in prompt["options"] if option.get("kind") == "play_card")
    before_hash = match.state_hash()
    before_revision = match.revision

    rejected = match.submit_action(SubmittedAction(
        match_id=match.match_id,
        player_id=owner,
        client_action_id="invalid-payment",
        expected_revision=before_revision,
        action={
            "kind": CHOOSE_PROMPT_OPTION,
            "promptId": prompt["id"],
            "optionId": play_option["id"],
            "payload": {"paymentBaseIids": [999999]},
        },
    ))

    assert rejected.accepted is False
    assert rejected.rejection.code == "INVALID_ACTION"
    assert match.revision == before_revision
    assert match.state_hash() == before_hash
    assert match.session.prompt["id"] == prompt["id"]

def test_surrender_finishes_match_once() -> None:
    match = AuthoritativeMatch(InitialMatchSpec.standard(match_id="surrender", seed=203))
    result = match.submit_action(SubmittedAction(
        match_id=match.match_id,
        player_id="player_1",
        client_action_id="surrender-p1",
        expected_revision=0,
        action={"kind": SURRENDER},
    ))

    assert result.accepted is True
    assert result.revision == 1
    assert result.events[-1]["kind"] == "MATCH_ENDED"
    assert result.events[-1]["winnerId"] == "player_2"
    assert match.get_view_for("player_1")["gameOver"] is not None

    after_end = match.submit_action(SubmittedAction(
        match_id=match.match_id,
        player_id="player_2",
        client_action_id="too-late",
        expected_revision=1,
        action={"kind": SURRENDER},
    ))
    assert after_end.accepted is False
    assert after_end.rejection.code == "MATCH_FINISHED"
    assert match.revision == 1
