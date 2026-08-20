# v0.3.2 - Duel Timing And Desktop Update

[Chinese overview](README.md) | [日本語 overview](README.ja.md) | [English overview](README.en.md)

## Highlights

- Complete Game Lobby, deck building, and local card-battle flow.
- Card pool expanded to Basic, EX01, PC01, PC01R, and PC02 CONTRACT.
- Human VS AI, omniscient, and AI VS AI offline modes.
- Easy Greedy CPU plus Medium and High experimental reinforcement-learning
  models.
- Codeman recent-match memory, dedicated-model preference, and in-game advice.
- Replay review, local training entrypoints, LAN play, and personal-server
  online play.
- Simplified Chinese, Japanese, and English UI plus a trilingual rulebook.
- The duel top bar opens the rulebook as a rendered in-game panel.
- Optional battle BGM, Codeman profiles, and playmat profiles.
- The large `asserts/` media pack stays a separate download; updating the
  installer does not replace it.
- Online play uses the same duel screen and local assets as offline. Players
  choose rock, paper, or scissors for first turn, then can rematch in the same
  room. Protocol `2`, rules `0.0.3`.
- End-of-turn heals and exhausted cards resolve before the opponent draws.
  Triggered card text follows the selected UI language.
- The desktop client can download and launch the latest Windows or Linux package
  from GitHub Releases after checksum verification.

## Known limitations

- PC02 is implemented, but a personal project cannot cover every card
  combination. Small rules or interface bugs may remain.
- The computer AI was trained only with the PC01 card pool. PC01R, EX01, and
  PC02 were not included in the current training data. Do not expect the AI to
  understand the newer packs reliably.
- The Windows installer and Linux bundle are for playing. CUDA/PyTorch
  training dependencies are available only through the source setup.
- English card art and English text are distributed as a separate overlay pack.
- The public server is in Canada, and cross-region stability has not been fully
  verified. Mainland China users may need a proxy.
- Story Mode is a future goal and is not included in this release.

## Download contents

1. [`ZZ-Project-v0.3.2-Windows-Setup.exe`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.2/ZZ-Project-v0.3.2-Windows-Setup.exe):
   directly installable and playable Windows desktop package. It contains
   Electron, the frozen Python server, the PC02 runtime, Torch-free current
   runtime models, the desktop home background, and the top-bar BGM selector.
   Size: `142837370` bytes.
   SHA-256:
   `E5703C4976E3A52692550066571E17DE42B5312363370745ACD61D922257BB7A`.
2. [`ZZ-Project-v0.3.2-Linux.tar.gz`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.2/ZZ-Project-v0.3.2-Linux.tar.gz):
   portable Linux source/runtime bundle. Extract it and run
   `./launch-electron.sh`; the first launch prepares user-scoped Node.js,
   Electron, and Python runtime files, including the top-bar BGM selector.
   Size: `21480331` bytes.
   SHA-256:
   `A9FF73C2088B0FC512C755318176289F76EA4ED3309536996E02D6F2D90FF7A2`.
3. [`ZZ-Project-v0.3.2-source.zip`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.2/ZZ-Project-v0.3.2-source.zip):
   source, tests, documentation, runtime models, and `image.png` for macOS
   players and developers.
4. [`ZZ-Multiplayer-v0.3.2-f7a50d6.tar.gz`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.2/ZZ-Multiplayer-v0.3.2-f7a50d6.tar.gz):
   latest authoritative server snapshot for people who want to host their own
   room service. Older server archives are not kept. Size: `21786306` bytes.
   SHA-256:
   `04139BDC15FC9CD65A2F2B0D4F07B008161A8C94493B9F9B1DCB908145EED9CD`.
   Setup: [docs/ONLINE.md](docs/ONLINE.md).
5. [`ZZ-Assets-PC02-v1.zip.001` and `.002`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing):
   main card art, characters, playmats, video, sound effects, and BGM. Download
   both volumes, open `.001` with 7-Zip, and place the resulting `asserts/`
   beside `ZZ-Project.exe` for Windows or at the bundle/project root for Linux
   and source launches.
6. [`ZZ-Assets-PC02-English-v1.zip`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing):
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
