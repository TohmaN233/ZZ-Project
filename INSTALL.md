# Installation Guide

[Chinese overview](README.md) | [日本語 overview](README.ja.md) | [English overview](README.en.md)

The v0.4.0 release artifacts are local candidates and have not been published.
They are listed in `dist/releases/v0.4.0/`; public download links and final
package checksums belong in [PUBLIC_RELEASE_MANIFEST.json](PUBLIC_RELEASE_MANIFEST.json).
The large media pack remains separate from the program packages, but the
current desktop client can download and install it on first launch.

### Automatic asset setup in v0.4.0

The v0.4.0 desktop client checks for a complete `asserts/` directory before
starting the game. If it is missing, it asks whether to download `asserts.7z`
from the
[ZZ resource folder](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ).
The current archive is 1,534,680,950 bytes (1.53 GB / 1.43 GiB).
Its files total 1,577,092,255 bytes (1.58 GB) after extraction, including
`Eng-cards/`. Reserve at least 3.2 GB of free space during installation; this
bundle includes the English card faces. Accepting displays download and
extraction progress, checks the archive CRC, and installs `asserts/` beside
the executable (or at the source project root). Cancelling exits without
starting the game. 7-Zip is bundled with the client.

The destination must be writable and have enough space for both the compressed
archive and its extracted files. Installation errors are shown with a retry
option. Existing complete resources skip downloading; an incomplete existing
directory is preserved and reported, so move it aside or complete it manually.
`ZZ_ASSET_ROOT` or `ZENONZARD_ASSET_ROOT` can explicitly select another resource
location. Changing the published archive requires updating
`electron/asset-source.json` in a new client build.

## 1. Choose a distribution

The local v0.4.0 candidate files are:

- `dist/releases/v0.4.0/ZZ-Project-v0.4.0-Windows-Setup.exe`
- `dist/releases/v0.4.0/ZZ-Project-v0.4.0-Linux.tar.gz`
- `dist/releases/v0.4.0/ZZ-Project-v0.4.0-source.zip`
- `dist/releases/v0.4.0/ZZ-Multiplayer-v0.4.0.tar.gz`

These are not public download links. Publication details, sizes, and SHA-256
values will be recorded in `PUBLIC_RELEASE_MANIFEST.json`.

- **Windows players:** use the installable desktop package. It includes
  Electron, the frozen Python server, the PC02R DIVINE rules runtime, the current
  runtime models, and the desktop home background `image.png`.
- **Linux players:** use the portable `tar.gz` bundle. It includes the source
  runtime, a Torch-free inference model, `image.png`, and an executable
  `launch-electron.sh`. It is not an AppImage or a native distribution package.
- **macOS players and developers:** use the source ZIP or clone the repository.
- **All players:** on first launch, consent to the automatic `asserts.7z`
  download when assets are missing. Manually downloading and extracting the
  archive from Google Drive is optional.

## 2. Requirements

- Windows 10 or Windows 11 for the installer.
- A Linux system that can run the portable launcher. The Linux bundle prepares
  Node.js, Electron, and Python in the user cache on first launch.
- Python 3.10+ and Node.js 20+ only for source launches.
- Normal play does not require a dedicated GPU.
- Local AI training requires an NVIDIA GPU, compatible drivers, and CUDA
  PyTorch. Training dependencies are not included in the playable packages.

## 3. Windows installer

Run the v0.4.0 candidate installer when it is available to you. Python,
Node.js, and `npm install` are not required. Start the installed game from the
Start menu or the desktop shortcut.

If the `asserts/` directory is missing, the first launch offers to download
and install it. The destination is beside `ZZ-Project.exe`:

```text
<installation directory>/
|- ZZ-Project.exe
`- asserts/
   |- ZENONZARD_CARDLIST/
   |- images/
   `- ...
```

The installer keeps `image.png` inside the application resources and the
frozen server bundle; it is already included and does not need to be copied by
the player. The installer package excludes the large `asserts/` directory.

The installer may include the default sample decks as a separate
`resources/data/decks/` folder, never inside `ZZ-Project.exe`. Saved and edited
decks are stored in the per-user `game-data/decks/` directory, outside the
application files, so application updates do not replace them. Private
`data/codeman_ai/`, `ai_challenges/`, training traces, and local Codeman
training actors are not packaged.

## 4. Linux portable bundle

Extract the v0.4.0 Linux candidate bundle and run:

```bash
tar -xzf ZZ-Project-v0.4.0-Linux.tar.gz
cd ZZ-Project-v0.4.0
./launch-electron.sh --check
./launch-electron.sh
```

The bundle contains `image.png` at its root, so the desktop home screen does
not depend on the external asset pack. If `asserts/` is missing, the client
asks to download it and installs it at the bundle root beside
`launch-electron.sh`. English card faces are included in that resource pack.

On first launch the existing launcher downloads or prepares the user-scoped
Node.js, Electron, and Python runtime. A network connection is therefore
needed for the first bootstrap unless those runtime files are already cached.

## 5. Source launch and macOS

Use the v0.4.0 source candidate ZIP or clone the repository. The source
package contains the release snapshot, runtime models, tests, documentation,
and `image.png`.

Install the runtime dependencies from the project root:

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

Then launch with the platform script. On first launch, missing assets trigger
the same download prompt; accepted resources are installed in the project root:

```powershell
# Windows source launch
.\launch-electron.cmd
```

```bash
# Linux or macOS source launch
./launch-electron.sh
```

If Git LFS is used for a clone, run:

```powershell
git lfs install
git lfs pull
```

## 6. Asset pack details

The v0.4.0 resource archive is `asserts.7z` in the [Google Drive asset
folder](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ).
It is 1,534,680,950 bytes (1.53 GB / 1.43 GiB), and expands to 1,577,092,255
bytes (1.58 GB). It includes `Eng-cards/`; there is no separate English faces
archive for this bundle. Reserve at least 3.2 GB of free space while the
archive is downloaded and extracted. The client validates the archive CRC
before extracting it to the application root.

The expected layout is:

```text
ZZ-Project/
|- image.png
|- asserts/
|  |- ZENONZARD_CARDLIST/
|  |- Eng-cards/              # optional English card, Force, and Mana faces
|  |- audio/
|  |- card_back/
|  |- images/
|  `- video/
|- data/
|- electron/
|- zz/
|- launch-electron.cmd
`- launch-electron.sh
```

For a manual installation, extract the archive so the `asserts/` directory is
at the program root, without an extra nested `asserts/asserts/` directory.

## 7. Launch and settings

The Windows installer starts from the Start menu or desktop shortcut. Source
and Linux builds use the launchers above. Once the client is running, the
persistent top bar or Settings can switch between Simplified Chinese, Japanese,
and English, select the battle BGM track, and turn BGM on or off.

The application checks GitHub Releases for newer versions. A failed update
check does not prevent offline play; diagnostics are written to the Electron
log.

## 8. Online play

- **LAN:** create a room in Online Game and let other players join using the
  address shown by the host. No extra server package is required.
- **Internet:** the default personal server is in Canada. Cross-region
  stability has not been fully verified; users in mainland China may need a
  proxy.
- **Self-hosted:** use the local candidate
  `dist/releases/v0.4.0/ZZ-Multiplayer-v0.4.0.tar.gz` when available, then
  follow [docs/ONLINE.md](docs/ONLINE.md). It has not been publicly released.

See [docs/ONLINE.md](docs/ONLINE.md) for the full online-play notes.

## 9. AI and local training

Local training is optional and is not required to play. The current computer AI
was trained only with the PC01 card pool. PC01R, EX01, PC02, and PC02R DIVINE
were not included in the current training data. Do not treat the AI as a
strength guarantee for the newer packs.

Windows and Linux playable packages omit CUDA/PyTorch training dependencies.
Use the source package, install the CUDA-compatible PyTorch build, and use the
tools under `ai_training/` for experiments. Training may require substantial
GPU memory, time, and disk space.

## 10. Troubleshooting

### Missing cards, characters, music, or video

Confirm that `asserts.7z` finished downloading and that the client completed
CRC validation and extraction. Confirm that `asserts/` is directly beside
`ZZ-Project.exe` for Windows or directly inside the Linux/source project root.

The Windows client also writes the selected asset root and Python server errors
to `%APPDATA%\ZZ-Project\server.log`. If the directory layout is correct but
the game is still empty, attach that file instead of moving the asset pack.

### Missing English card faces

The v0.4.0 resource archive includes English card faces. Confirm that
`asserts/Eng-cards/` exists, then retry the asset download or extract the
complete `asserts.7z` archive again.

### High AI reports a model error

For a source clone, run `git lfs pull` and confirm that the model files are not
small LFS pointer files. The playable installers do not include the training
stack.

### Online Game cannot connect

Try LAN mode first to separate local firewall issues from Internet routing.
The public server is in Canada and cross-region connections may be unstable.

## Acknowledgements

Special thanks to theFeri for providing 50+ high-resolution playmat images, and
to **Valkyrie** for providing the English text.
