# v0.3.0 - Online Duel Parity

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
- Starting a new game from the game-over screen keeps the finished match's
  selected player and opponent decks.
- The Windows installer explicitly excludes `asserts/`; updating the EXE does
  not replace the separately downloaded asset directory.
- Online rooms now use the same duel renderer and local cosmetic assets as
  offline play and preserve player display names. Both players secretly choose
  rock, paper, or scissors to decide who goes first; ties repeat and the winner
  starts. Multiplayer compatibility is protocol `2`, rules `0.0.3`.
- When an online match ends, both players return to the same room with their
  seats and selected decks preserved. Either player can change decks, ready up,
  and start another match without entering the room code again.
- The refreshed `0.3.0` packages prevent privacy-redacted opponent hand cards
  from inheriting global actions such as `End Turn`, restrict online mulligan
  selection to the local hand, and load Mana faces through the same local
  `/assets/<assetId>` mapping used by offline play.
- Offline `/duel` now loads the shared multiplayer card-policy script, so
  local matches no longer open as a black screen.
- Online first-player selection happens on the duel view instead of the room
  lobby. After both players choose, the result shows first/second seats and
  keeps a first/second badge on the cockpit.
- The typed online display name is remembered across connect/create/join
  snapshot rerenders instead of snapping back to `Player`.
- Online opening-hand scheduling is simultaneous: both seats get their own
  mulligan prompt and either player may finish first. Local god mode stays
  sequential.
- Reopening the desktop client after a stale room or invalid reconnect token
  returns silently to the home page instead of showing an error or forcing a
  broken duel.
- A mid-match network drop stays on the duel and retries reconnect five times
  before returning to the lobby.
- Gameplay snapshots may exceed the old 64KiB lobby cap; the default wire
  limit is now 256KiB so a mid-game view is not treated as a fatal disconnect.
- Online views no longer carry card, playmat, or portrait URLs. Clients load
  those images from the local `/assets/<id>` catalog. Official website image
  URLs are no longer used as a fallback.
- Online rock-paper-scissors no longer flickers the waiting player when the
  opponent submits. Force and mana target art uses local card/force ids.
  A finished match shows the same win/lose overlay as offline play until the
  player clicks return.
- English and Japanese mana faces share the offline assetUrl/assetUrlEn
  helpers. Online hydration fills those fields the same way as serialize_card.
- Transport/lobby errors no longer stick on the duel prompt after entering a
  match.
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

1. [`ZZ-Project-v0.3.0-Windows-Setup.exe`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-Windows-Setup.exe):
   directly installable and playable Windows desktop package. It contains
   Electron, the frozen Python server, the PC02 runtime, Torch-free current
   runtime models, the desktop home background, and the top-bar BGM selector.
   Size: `142403034` bytes.
   SHA-256:
   `94E74DBEFB42EB237761AA60499D6E8A35E2BB05EEE3CE934B01C010D651EB13`.
2. [`ZZ-Project-v0.3.0-Linux.tar.gz`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-Linux.tar.gz):
   portable Linux source/runtime bundle. Extract it and run
   `./launch-electron.sh`; the first launch prepares user-scoped Node.js,
   Electron, and Python runtime files, including the top-bar BGM selector.
   Size: `21473121` bytes.
   SHA-256:
   `E5982181ECD6DF6AE06CFB390E205A2033593AA53458E9E10A307B1DEA2957AF`.
3. [`ZZ-Project-v0.3.0-source.zip`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-source.zip):
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
