# ZENONZARD Offline Project

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

An unofficial, non-commercial desktop recreation of ZENONZARD and an AI experimentation project for players who want to play locally, study the rules, or contribute.

[Project website](https://tohman233.github.io/ZZ-Project/) · [Installation guide](INSTALL.md) · [Online play](docs/ONLINE.md) · [English rulebook](docs/rules/zz_rulebook_en.md)

## System Requirements

- The Windows 10 or 11 installer runs on Windows; Linux players can use the portable package; macOS players and developers can launch from source.
- Launching from source requires Python 3.10+ and Node.js 20+.
- Regular matches do not require a dedicated GPU. Local AI training requires an NVIDIA GPU, compatible drivers, and a CUDA-enabled build of PyTorch.

## Installation

v0.5.0 adds all 70 EX02C/SAO cards, including two CAMPAIGN cards, and their corresponding EX02 original faces. It also improves card search, rule resolution, Force search, and visual feedback during battles. The online handshake requires the client and server `applicationVersion` values to match exactly; both players and the server, including self-hosted servers, must use v0.5.0.

[Windows installer](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.0/ZZ-Project-v0.5.0-Windows-Setup.exe) · [Linux portable bundle](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.0/ZZ-Project-v0.5.0-Linux.tar.gz) · [Source package](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.0/ZZ-Project-v0.5.0-source.zip) · [Self-hosted multiplayer server](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.0/ZZ-Multiplayer-v0.5.0.tar.gz) · [SHA256 checksums](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.0/SHA256SUMS-PC02.txt)

Windows players should use the installer, Linux players the portable package, and macOS players and developers the source package. See the [installation guide](INSTALL.md) for complete steps.

On first launch, if the complete `asserts/` directory is missing, the client asks whether to download `asserts.7z` from the [Google Drive resource folder](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ), then verifies and extracts it automatically. The resource archive is 1.53 GB and expands to 1.58 GB; reserve at least 3.2 GB of free space. Cancelling the download exits the game. If installed under Program Files, run as administrator for the first resource installation, or choose a writable installation directory.

Before launching from source, install the dependencies from the project root:

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

## Configuration

The default interface language is Simplified Chinese, and the opponent AI defaults to High difficulty. You can change the difficulty in the game lobby. Use the top bar or Settings page to switch between Chinese, Japanese, and English, and to select or turn off the background music. Easy uses the Greedy strategy; Medium and High use the runtime models provided by the project.

## Quick Start

Launch the Windows installer build from the Start menu or its desktop shortcut. The Linux portable package prepares its runtime in the user's cache directory on first launch. To launch from source, use the command for your platform:

```powershell
# Windows source launch
.\launch-electron.cmd
```

```bash
# Linux or macOS source launch
./launch-electron.sh
```

## Current Features

- **Matches and decks**: play Human vs AI, in omniscient view, or AI vs AI; search the card pool, edit decks, and save them.
- **Codeman and local training**: recent match memories are stored locally; the source build supports experimental training with a GPU / CUDA environment.
- **Replay and AI suggestions**: review recent matches and see Codeman's suggestion for the current action during a match.
- **Online play**: supports LAN and public rooms. The client connects by default to `wss://zz.tgy233.top/multiplayer`; see the [online play guide](docs/ONLINE.md) to host your own server.
- **Card pool and interface**: includes the basic cards, EX01, PC01, PC01R, PC02, and 106 PC02R DIVINE cards, plus 70 EX02C/SAO cards and their corresponding EX02 original faces; the interface supports Simplified Chinese, Japanese, and English.
- **Card display**: preview a transformed form in card details. Reprints with the same name count toward a shared deck limit of three copies.

Story Mode has not been implemented. The long-term goal is to design a game where an Agent automatically interacts with players and to build a GAL-style frontend. The project also plans to learn from the SillyTavern community's experience with characters, World Info, and long-term interaction, creating a ZZ experience for players to share with their own Codeman.

## About AI Strength

This project does not present its experimental models as strong AI. The author has a statistics degree but has not taken reinforcement-learning courses, and their research is unrelated to reinforcement learning. Training resources are also limited. The current models remain considerably weaker than the AI used during ZENONZARD's official operation, and the in-game suggestions are primarily an entertainment feature.

The computer AI's training card pool currently covers PC01 only. PC01R, EX01, PC02, PC02R DIVINE, EX02, and EX02C/SAO were not included in the current training process, so do not expect the computer AI to understand these newer packs correctly. Implementing playable rules does not mean the AI has learned those cards.

Codex assisted with the AI-related code, which also draws on the public methods and engineering structure of [sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.

## Contributing

Contributions are welcome through the [contribution guide](CONTRIBUTING.md). Before starting, please describe the work you plan to do in an Issue or Discussion to avoid duplication.

## Acknowledgements

Thanks to theFeri for providing more than 50 high-resolution playmat images, and to **Valkyrie** for providing the English text.

## Rights Notice

This is an unofficial, non-commercial fan development and research project. The rights to the ZENONZARD name, characters, card images, music, and related assets belong to their respective rights holders. This project is not affiliated with or authorized by BANDAI, STRAIGHT EDGE, or SUNRISE.

The repository does not include an official open-source license for the project code. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for notes on referenced projects and third-party dependencies; that file does not replace their individual licenses.
