from tools.multiplayer_soak import run_soak


def test_small_multiplayer_soak_has_no_desync_duplicate_or_hidden_leak() -> None:
    report = run_soak(matches=1, seed=20_000, max_decisions=250)

    assert report["completeMatches"] == 1
    assert report["desyncs"] == 0
    assert report["uncaughtExceptions"] == 0
    assert report["duplicateAcceptedActions"] == 0
    assert report["hiddenInformationLeaks"] == 0
    assert report["totalActions"] > 0
