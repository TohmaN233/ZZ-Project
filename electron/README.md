# Zenonzard Electron Shell

This desktop shell opens the existing Python web client and keeps Python as the
rules authority. Electron owns the native window, Python server lifecycle, and a
small IPC surface for desktop-only helpers.

## Dev Start

Install Node dependencies once:

```powershell
npm install
```

Then start the desktop client:

```powershell
npm run electron:dev
```

Platform launchers are also available at the project root:

- Windows: `launch-electron.cmd`
- Linux: `launch-electron.sh`
- macOS: `launch-electron.command`

Useful environment variables:

```powershell
$env:ZZ_WEB_PORT = "8765"
$env:ZZ_ASSET_ROOT = ".\asserts"
npm run electron:dev
```

Without `ZZ_WEB_PORT`, Electron asks Python to bind an available random port and
loads the printed local URL. This avoids trusting a page that happened to occupy
`127.0.0.1:8765`.

## Manual Browser Restart

When you only want the Python web app, run:

```powershell
python -m zz.web.server --port 8765 --asset-root ".\asserts"
```

Then open:

```text
http://127.0.0.1:8765/
```

## IPC Surface

The preload exposes `window.zzDesktop` with narrow helpers only:

- `startServer`, `stopServer`, `serverStatus`
- `openFolder`, `openPath`
- `selectAssetRoot`, `selectDeckRoot`
- `getVersion`, `checkForUpdates`, `openReleasePage`

The main process performs the GitHub Release request through Electron's network
stack, owns the fixed external URLs, installs the native Help menu, and applies
`electron/icon.png` to desktop windows. Renderer code never receives a general
external-URL opener.

Game rules and match state still go through the Python `/api/...` JSON contract.
