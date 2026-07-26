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
- **Cross-platform launchers**: `.cmd` for Windows, `.sh` for Linux, and `.command` for macOS. Linux and macOS currently have experimental source-launch support.

Story Mode has not been implemented. The long-term goal is an Agent-driven game that interacts with each player and generates a GAL-style frontend. The project also intends to learn from the SillyTavern community's work on characters, World Info, and long-term interaction to create a personal ZZ experience shared with the player's own Codeman.

## About the AI

This project does not present its experimental models as strong AI. The author has a statistics degree but has not taken reinforcement-learning courses, and their research is unrelated to reinforcement learning. Training resources are also limited. The current models remain considerably weaker than the AI used during ZENONZARD's official operation, and the in-game suggestions are primarily an entertainment feature.

The AI code was written with assistance from Codex and refers to the public methods and engineering structure of [sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.

## Installation

Source code and large visual/audio assets are distributed separately. Download the [complete asset pack (`ZZ-Assets-v1.zip`)](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing). See [INSTALL.md](INSTALL.md) for the full directory layout and troubleshooting steps.

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

# macOS
./launch-electron.command
```

## Current Limitations

The current card pool contains the basic cards and PC01. It will be expanded gradually with the goal of completing the card pool. As a personal project, it has not been tested across every possible card combination, so small rule or interface bugs may remain.

English card images are loaded directly from official website URLs. Some cards are known to display mismatched images. English-speaking contributors can help resolve this by providing card images and corresponding English text.

## Contributing

Contributors with reinforcement-learning experience are especially welcome to investigate whether a stronger offline ZZ AI can be trained. Card data, English images and translations, rule testing, and bug reports are also valuable. Please use Issues or Discussions.

## Rights Notice

This is an unofficial, non-commercial fan-development and research project. Rights to the ZENONZARD name, characters, card images, music, and related assets belong to their respective owners. This project is not affiliated with or endorsed by BANDAI, STRAIGHT EDGE, or SUNRISE.
