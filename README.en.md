# ZENONZARD Offline Project

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

An unofficial, non-commercial desktop recreation of ZENONZARD and an experimental AI project.

[Project website](https://tohman233.github.io/ZZ-Project/) · [Installation](INSTALL.md) · [Online play](docs/ONLINE.md) · [English rulebook](docs/rules/zz_rulebook_en.md)

## Current Features

- **Game Lobby**: choose both decks, Codemen, playmats, turn order, and AI difficulty.
- **Deck building**: search the card pool, create decks, and save them for battle.
- **Three offline modes**: Human VS AI, omniscient mode with both hands visible and controllable, and AI VS AI.
- **Three AI levels**: Easy uses a Greedy CPU; Medium and High use reinforcement-learning models.
- **Codeman memory**: recent matches and Replays are stored locally. When a Codeman has a dedicated `.pt` model, that model is preferred for the opponent.
- **AI suggestions**: click your Codeman during a match to see the AI's suggestion for the current decision.
- **Replay & Training**: review recent matches and, with a suitable GPU / CUDA environment, run experimental local training.
- **Online Game**: supports LAN play and online rooms through a personal server.
- **Trilingual UI**: Simplified Chinese, Japanese, and English.
- **BGM settings**: the complete asset pack includes ZENONZARD character songs.
- **Update checks**: the desktop client checks GitHub Releases at startup and can open the release page when a newer version is available.
- **Cross-platform launchers**: a Windows installer, a Linux portable `tar.gz` bundle, and `.sh` source launches for macOS and developers. The separate `.command` launcher was removed from this release.

Story Mode has not been implemented. The long-term goal is an Agent-driven game that interacts with each player and generates a GAL-style frontend. The project also intends to learn from the SillyTavern community's work on characters, World Info, and long-term interaction to create a personal ZZ experience shared with the player's own Codeman.

## About the AI

This project does not present its experimental models as strong AI. The author has a statistics degree but has not taken reinforcement-learning courses, and their research is unrelated to reinforcement learning. Training resources are also limited. The current models remain considerably weaker than the AI used during ZENONZARD's official operation, and the in-game suggestions are primarily an entertainment feature.

Important AI note: the computer AI was trained only with the PC01 card pool. PC01R, EX01, and PC02 were not part of that training, so do not expect the computer AI to understand the newer packs reliably. Playable PC02 rules do not mean that the AI has learned those cards.

The AI code was written with assistance from Codex and refers to the public methods and engineering structure of [sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.

## Installation

Windows players should download and run [ZZ-Project-v0.3.0-Windows-Setup.exe](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-Windows-Setup.exe). The installer contains the playable desktop client, frozen Python server, rules code, and default models; Python and Node.js are not required. Large visual/audio assets remain separate: download both main-pack volumes, `ZZ-Assets-PC02-v1.zip.001` and `ZZ-Assets-PC02-v1.zip.002`, from the [Google Drive asset folder](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing). Open `.001` with 7-Zip and place the resulting `asserts/` directory next to the installed `ZZ-Project.exe`. English users should also download the separate `ZZ-Assets-PC02-English-v1.zip` and extract it into the same `asserts/` directory. See [INSTALL.md](INSTALL.md) for the full directory layout and troubleshooting steps.

Linux players should download [ZZ-Project-v0.3.0-Linux.tar.gz](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-Linux.tar.gz), extract it, and run `./launch-electron.sh`; the first launch prepares private runtimes in the user cache. macOS players and developers should use [ZZ-Project-v0.3.0-source.zip](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-source.zip) and follow the source setup below.

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

Place the asset pack's `asserts/` directory in the repository root, then use the launcher for your platform.

```powershell
# Windows
.\launch-electron.cmd
```

```bash
# Linux
./launch-electron.sh

# macOS (source launch)
./launch-electron.sh
```

## Current Limitations

The current card pool contains the basic cards, EX01, PC01, PC01R, and PC02. As a personal project, it has not been tested across every possible card combination, so small rule or interface bugs may remain.

English card images and English text are distributed in a separate asset pack. Cards not covered by the local pack may still fall back to official website URLs, and some image/card mismatches may remain.

## Acknowledgements

Special thanks to theFeri for providing 50+ high-resolution playmat images, and to **Valkyrie** for providing the English text.

## Contributing

Contributors with reinforcement-learning experience are especially welcome to investigate whether a stronger offline ZZ AI can be trained. Card data, English images and translations, rule testing, and bug reports are also valuable. Please use Issues or Discussions.

## Rights Notice

This is an unofficial, non-commercial fan-development and research project. Rights to the ZENONZARD name, characters, card images, music, and related assets belong to their respective owners. This project is not affiliated with or endorsed by BANDAI, STRAIGHT EDGE, or SUNRISE.
