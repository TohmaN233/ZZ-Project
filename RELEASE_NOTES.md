# v0.2.0 - PC02 CONTRACT

[Chinese overview](README.md) | [日本語 overview](README.ja.md) | [English overview](README.en.md)

## Highlights

- Complete Game Lobby, deck building, and local card-battle flow.
- Card pool expanded to Basic, EX01, PC01, PC01R, and PC02 CONTRACT.
- All 100 PC02 cards, Boost effects, target selection, triggers, and boundary
  cases are included in the runtime.
- Human VS AI, omniscient, and AI VS AI offline modes.
- Easy Greedy CPU plus Medium and High experimental reinforcement-learning
  models.
- Codeman recent-match memory, dedicated-model preference, and in-game advice.
- Replay review, local training entrypoints, LAN play, and personal-server
  online play.
- Simplified Chinese, Japanese, and English UI plus a trilingual rulebook.
- Optional battle BGM with a persistent top-bar track selector, Codeman
  profiles, and playmat profiles.
- The desktop home background `image.png` is included in the program packages;
  the large `asserts/` media pack remains a separate download.
- The Windows installer explicitly excludes `asserts/`; updating the EXE does
  not replace the separately downloaded asset directory.
- Default sample decks are installed as `resources/data/decks/`, outside the
  executable. Saved decks live under the per-user `game-data/decks/` folder.
  Private Codeman memory, training traces, challenge data, and local training
  actors are excluded.

## Known limitations

- PC02 is implemented, but a personal project cannot cover every card
  combination. Small rules or interface bugs may remain.
- The computer AI was trained only with the PC01 card pool. PC01R, EX01, and
  PC02 were not included in the current training data. Do not expect the AI to
  understand the newer packs reliably.
- The Windows installer and Linux bundle are for playing. CUDA/PyTorch
  training dependencies are available only through the source setup.
- English card art and English text are distributed as a separate overlay pack.
  Cards not covered locally may still fall back to official URLs.
- The public server is in Canada, and cross-region stability has not been fully
  verified. Mainland China users may need a proxy.
- Story Mode is a future goal and is not included in this release.

## Download contents

1. [`ZZ-Project-v0.2.0-Windows-Setup.exe`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-Windows-Setup.exe):
   directly installable and playable Windows desktop package. It contains
   Electron, the frozen Python server, the PC02 runtime, Torch-free current
   runtime models, the desktop home background, and the top-bar BGM selector.
   Size: `142406863` bytes.
   SHA-256:
   `B5B5D8A99659D80EA79491AD65C7FE9F0BD59F7B5B0D7E58FFA54C8B7FDF2E18`.
2. [`ZZ-Project-v0.2.0-Linux.tar.gz`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-Linux.tar.gz):
   portable Linux source/runtime bundle. Extract it and run
   `./launch-electron.sh`; the first launch prepares user-scoped Node.js,
   Electron, and Python runtime files, including the top-bar BGM selector.
   Size: `21464081` bytes.
   SHA-256:
   `60D32FC4DCCE78BFB4D577F5A726BEFE515BEA55395B7327A2658C4F1896E297`.
3. [`ZZ-Project-v0.2.0-source.zip`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-source.zip):
   source, tests, documentation, runtime models, and `image.png` for macOS
   players and developers.
4. [`ZZ-Assets-PC02-v1.zip.001` and `.002`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing):
   main card art, characters, playmats, video, sound effects, and BGM. Download
   both volumes, open `.001` with 7-Zip, and place the resulting `asserts/`
   beside `ZZ-Project.exe` for Windows or at the bundle/project root for Linux
   and source launches.
5. [`ZZ-Assets-PC02-English-v1.zip`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing):
   English card, Force, and Mana faces. Extract it on top of the main
   `asserts/` directory.

The main asset volumes are intentionally at least about 500 MB each for a more
reliable download. The English pack remains one ZIP. Exact sizes, file counts,
and hashes are recorded in
[`ASSET_PACK_MANIFEST.json`](ASSET_PACK_MANIFEST.json).

## Credits

Special thanks to theFeri for providing 50+ high-resolution playmat images, and
to **Valkyrie** for providing the English text.

See [INSTALL.md](INSTALL.md) for the complete English installation guide.
