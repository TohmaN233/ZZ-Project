from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_closing_the_main_window_quits_and_terminates_server_tree() -> None:
    main = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")

    assert 'mainWindow.on("closed"' in main
    assert "if (!shutdownPrepared) app.quit();" in main
    assert 'spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"]' in main
    assert "terminateProcessTree(processToStop);" in main
    assert 'app.on("before-quit"' in main
