from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_preload_exposes_only_narrow_multiplayer_commands() -> None:
    preload = (ROOT / "electron" / "preload.js").read_text(encoding="utf-8")
    required = {
        "status",
        "connect",
        "disconnect",
        "reconnect",
        "createRoom",
        "joinRoom",
        "selectDeck",
        "setReady",
        "selectOpeningChoice",
        "submitAction",
        "surrender",
        "requestSync",
        "leaveRoom",
        "lanStatus",
        "startLanHost",
        "stopLanHost",
        "discoverLan",
        "onEvent",
    }

    assert 'exposeInMainWorld("zzMultiplayer"' in preload
    assert all(f"{name}:" in preload for name in required)
    assert "WebSocket" not in preload
    assert "ipcRenderer.send(" not in preload


def test_main_process_owns_socket_client_and_checks_ipc_sender() -> None:
    main = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    channels = {
        "multiplayer:status",
        "multiplayer:connect",
        "multiplayer:disconnect",
        "multiplayer:reconnect",
        "multiplayer:createRoom",
        "multiplayer:joinRoom",
        "multiplayer:selectDeck",
        "multiplayer:setReady",
        "multiplayer:selectOpeningChoice",
        "multiplayer:submitAction",
        "multiplayer:surrender",
        "multiplayer:requestSync",
        "multiplayer:leaveRoom",
        "multiplayer:lanStatus",
        "multiplayer:startLanHost",
        "multiplayer:stopLanHost",
        "multiplayer:discoverLan",
    }

    assert 'require("./multiplayer-client")' in main
    assert 'require("./adaptive-websocket")' in main
    assert "session.defaultSession.resolveProxy" in main
    assert "WebSocketImpl: AdaptiveWebSocket" in main
    assert "networkRoute:" in main
    assert all(f'ipcMain.handle("{channel}"' in main for channel in channels)
    assert main.count("assertTrustedSender(_event);") >= len(channels)
    assert 'webContents.send("multiplayer:event"' in main
    assert '"multiplayer-recovery.json"' in main
    assert "getRecoverySession()" in main


def test_online_home_entry_and_duel_action_route_are_live() -> None:
    app = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'data-view="online"' in app
    assert 'if (appView === ONLINE_VIEW)' in app
    assert 'runMultiplayerCommand("submitAction"' in app
    assert 'runMultiplayerCommand("surrender")' in app
    assert 'runMultiplayerCommand("selectOpeningChoice", choice)' in app
    assert 'data-online-opening-choice=' in app
    assert 'window.zzMultiplayer' in app
    assert 'data-multiplayer-tab="lan"' in app
    assert 'data-lan-host' in app
    assert 'data-lan-discover' in app
    assert 'data-lan-join' in app
    assert 'data-lan-join data-lan-address=' in app
    assert 'data-lan-join data-lan-host=' not in app
    assert 'const ONLINE_SERVER_URL = "wss://zz.tgy233.top/multiplayer"' in app
    assert 't("onlineNetworkRoute")' in app
    assert 'multiplayerUi.url = multiplayerUi.mode === "lan" ? LAN_SERVER_URL : ONLINE_SERVER_URL' in app
    switch_multiplayer_mode = app.split("async function switchMultiplayerMode", 1)[1].split(
        "async function startLanRoom()", 1
    )[0]
    assert 'multiplayerUi.status !== "OFFLINE"' in switch_multiplayer_mode
    assert 'await runMultiplayerCommand("disconnect")' in switch_multiplayer_mode
    connect_online = app.split("async function connectOnlineServer()", 1)[1].split(
        "function createOnlineRoom()", 1
    )[0]
    assert 'multiplayerUi.status === "ERROR"' in connect_online
    assert 'runMultiplayerCommand("disconnect")' in connect_online
    start_lan_room = app.split("async function startLanRoom()", 1)[1].split(
        "async function stopLanHost()", 1
    )[0]
    assert 'multiplayerUi.displayName = onlineInputValue("[data-online-name]"' in start_lan_room
    discover_lan_rooms = app.split("async function discoverLanRooms()", 1)[1].split(
        "function joinDiscoveredLanRoom", 1
    )[0]
    assert 'multiplayerUi.displayName = onlineInputValue("[data-online-name]"' in discover_lan_rooms


def test_online_duel_uses_local_assets_shared_visual_pipeline_and_inert_card_backs() -> None:
    app = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    apply_snapshot = app.split("function applyMultiplayerSnapshot", 1)[1].split(
        "async function refreshMultiplayerSnapshot", 1
    )[0]
    render_card = app.split("function renderCard(card", 1)[1].split(
        "function renderForce", 1
    )[0]

    assert "hydrateMultiplayerViewAssets" in apply_snapshot
    assert "stageDuelState" in apply_snapshot
    assert "lastAppliedMultiplayerViewKey" in apply_snapshot
    assert "const localManaUrl" in app
    assert '? localAssetUrl("card_back")' in app
    assert "MultiplayerCardPolicy.isCardInteractive" in render_card
    assert "data-card-iid" in render_card and "interactive ?" in render_card
