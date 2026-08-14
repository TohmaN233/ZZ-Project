# Installation Guide

[Chinese overview](README.md) | [日本語 overview](README.ja.md) | [English overview](README.en.md)

This release separates the playable program from the large visual and audio
asset pack. Install or extract the program first, then place the downloaded
`asserts/` directory beside it. English card faces are distributed as a
separate overlay pack.

## 1. Choose a distribution

- **Windows players:** use the installable desktop package. It includes
  Electron, the frozen Python server, the PC02 rules runtime, the current
  runtime models, and the desktop home background `image.png`.
- **Linux players:** use the portable `tar.gz` bundle. It includes the source
  runtime, a Torch-free inference model, `image.png`, and an executable
  `launch-electron.sh`. It is not an AppImage or a native distribution package.
- **macOS players and developers:** use the source ZIP or clone the repository.
- **All players:** download the external asset pack from Google Drive.

## 2. Requirements

- Windows 10 or Windows 11 for the installer.
- A Linux system that can run the portable launcher. The Linux bundle prepares
  Node.js, Electron, and Python in the user cache on first launch.
- Python 3.10+ and Node.js 20+ only for source launches.
- Normal play does not require a dedicated GPU.
- Local AI training requires an NVIDIA GPU, compatible drivers, and CUDA
  PyTorch. Training dependencies are not included in the playable packages.

## 3. Windows installer

Download and run
[`ZZ-Project-v0.2.0-Windows-Setup.exe`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-Windows-Setup.exe).
Python, Node.js, and `npm install` are not required. Start the installed game
from the Start menu or the desktop shortcut.

The large `asserts/` directory is intentionally external. Download the two
main asset volumes described in [Section 5](#5-download-the-asset-pack),
extract them, and place the resulting directory beside
`ZZ-Project.exe`:

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
the player. The installer package explicitly excludes `asserts/`; installing
a newer EXE does not replace the separately downloaded asset directory.

The installer may include the default sample decks as a separate
`resources/data/decks/` folder, never inside `ZZ-Project.exe`. Saved and edited
decks are stored in the per-user `game-data/decks/` directory, outside the
application files, so application updates do not replace them. Private
`data/codeman_ai/`, `ai_challenges/`, training traces, and local Codeman
training actors are not packaged.

English players should then extract
`ZZ-Assets-PC02-English-v1.zip` into the same `asserts/` directory. It writes
`asserts/Eng-cards/` and does not replace the main asset pack.

Installer size: `142391976` bytes.

Installer SHA-256:
`3DFB1EF17F9327E9452C5924FF6A56CDE3FB07FD9ADFE5F883EA8A426BC3FB71`.

## 4. Linux portable bundle

Download
[`ZZ-Project-v0.2.0-Linux.tar.gz`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-Linux.tar.gz),
then extract and run:

```bash
tar -xzf ZZ-Project-v0.2.0-Linux.tar.gz
cd ZZ-Project-v0.2.0
./launch-electron.sh --check
./launch-electron.sh
```

The bundle contains `image.png` at its root, so the desktop home screen does
not depend on the external asset pack. Put the extracted `asserts/` directory
at the bundle root, beside `launch-electron.sh`; add the English ZIP on top if
English card faces are needed.

On first launch the existing launcher downloads or prepares the user-scoped
Node.js, Electron, and Python runtime. A network connection is therefore
needed for the first bootstrap unless those runtime files are already cached.

Bundle size: `21464428` bytes.

Bundle SHA-256:
`156CE7F6C1BFAFB8C5A0D55BA3267AE6FF97CBFEA85B017244A3EEC07B5375BF`.

## 5. Source launch and macOS

Download the explicitly named
[`ZZ-Project-v0.2.0-source.zip`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-source.zip).
Do not use the smaller source archive generated automatically by an old GitHub
tag. The named archive contains the release snapshot, runtime models, tests,
documentation, and `image.png`.

Install the runtime dependencies from the project root:

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

Then put the external `asserts/` directory in the project root and launch with
the platform script:

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

## 6. Download the asset pack

Use the [Google Drive asset folder](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)
to download all required files:

- `ZZ-Assets-PC02-v1.zip.001` - `629145600` bytes.
- `ZZ-Assets-PC02-v1.zip.002` - `576401952` bytes.
- `ZZ-Assets-PC02-English-v1.zip` - `195374917` bytes.

Download both main volumes before extracting. Open `.001`; it will
read `.002` automatically. Extract the result to the program root, not to an
additional nested `asserts/asserts/` directory. The English ZIP is optional
and should be extracted into the same `asserts/` directory after the main pack.

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

The exact sizes, file counts, and hashes are recorded in
[`ASSET_PACK_MANIFEST.json`](ASSET_PACK_MANIFEST.json). On Windows, verify
downloads with:

```powershell
Get-FileHash .\ZZ-Assets-PC02-v1.zip.001 -Algorithm SHA256
Get-FileHash .\ZZ-Assets-PC02-v1.zip.002 -Algorithm SHA256
Get-FileHash .\ZZ-Assets-PC02-English-v1.zip -Algorithm SHA256
```

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
  address shown by the host.
- **Internet:** the default personal server is in Canada. Cross-region
  stability has not been fully verified; users in mainland China may need a
  proxy.

See [docs/ONLINE.md](docs/ONLINE.md) for the full online-play notes.

## 9. AI and local training

Local training is optional and is not required to play. The current computer AI
was trained only with the PC01 card pool. PC01R, EX01, and PC02 are playable
rules content but were not included in the current training data. Do not treat
the AI as a strength guarantee for the newer packs.

Windows and Linux playable packages omit CUDA/PyTorch training dependencies.
Use the source package, install the CUDA-compatible PyTorch build, and use the
tools under `ai_training/` for experiments. Training may require substantial
GPU memory, time, and disk space.

## 10. Troubleshooting

### Missing cards, characters, music, or video

Confirm that both main asset volumes were downloaded and that `.001` was
opened. Confirm that `asserts/` is directly beside `ZZ-Project.exe`
for Windows or directly inside the Linux/source project root.

The Windows client also writes the selected asset root and Python server errors
to `%APPDATA%\ZZ-Project\server.log`. If the directory layout is correct but
the game is still empty, attach that file instead of moving the asset pack.

### Missing English card faces

Extract `ZZ-Assets-PC02-English-v1.zip` into the existing `asserts/` directory
and confirm that `asserts/Eng-cards/` exists.

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
