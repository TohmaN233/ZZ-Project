# v0.4.0 Candidate - PC02R DIVINE and Rule Updates

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

This is a local release candidate. The packages listed below have not been
published or uploaded as release downloads. Final public availability, links,
sizes, and SHA-256 values are tracked in
[PUBLIC_RELEASE_MANIFEST.json](PUBLIC_RELEASE_MANIFEST.json).

## Highlights

- Added the 106-card PC02R DIVINE set.
- Transformation cards support private previews of their transformed faces.
- Reprints of the same card share one combined deck limit of three.
- Updated shared rules for effect-target filtering, damage and Force healing,
  base-owner replacement, and Bless returns.
- Added discard/draw animations and more detail for card buffs.
- On first launch, the desktop client detects missing `asserts/` assets and
  offers to download `asserts.7z`. The bundled 7-Zip validates the archive CRC
  and extracts it at the application root. Cancelling exits without starting
  the game; a failed installation can be retried.
- The `asserts.7z` bundle includes English card faces. It is
  1,534,680,950 bytes (1.53 GB / 1.43 GiB), expands to 1,577,092,255 bytes
  (1.58 GB), and needs at least 3.2 GB of free space during setup.

## AI coverage

The computer AI is still trained only with the PC01 card pool. PC01R, EX01,
PC02, and PC02R DIVINE are not covered by that training, so the new rules and
cards do not imply new AI training or reliable play with those sets.

## Candidate packages

These candidate artifacts are local files under `dist/releases/v0.4.0/`:

1. `ZZ-Project-v0.4.0-Windows-Setup.exe` - Windows desktop installer.
2. `ZZ-Project-v0.4.0-Linux.tar.gz` - portable Linux package.
3. `ZZ-Project-v0.4.0-source.zip` - source, models, tests, and documentation.
4. `ZZ-Multiplayer-v0.4.0.tar.gz` - self-hosted multiplayer server.

These names are not download links. See [INSTALL.md](INSTALL.md) for setup and
[docs/ONLINE.md](docs/ONLINE.md) for self-hosting instructions.

## Credits

Special thanks to theFeri for providing 50+ high-resolution playmat images, and
to **Valkyrie** for providing the English text.
