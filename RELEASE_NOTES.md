# v0.4.0 - PC02R DIVINE and Rule Updates

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

[Download v0.4.0](https://github.com/TohmaN233/ZZ-Project/releases/tag/v0.4.0). Package sizes and SHA-256 values are recorded in
[PUBLIC_RELEASE_MANIFEST.json](PUBLIC_RELEASE_MANIFEST.json). The public
multiplayer server runs v0.4.0; update both clients before connecting.

## v0.4.0 resource installation hotfix

The Windows, Linux, and source downloads have been replaced with corrected
packages. This fixes `Redirect was cancelled` during first-launch resource
installation: Electron's Chromium transport now exposes manual redirects for
validation instead of rejecting them. Download, CRC validation, extraction, and
installation were verified using the complete public 1.53 GB resource archive.

If you downloaded v0.4.0 before this fix, download the current package again and
reinstall it. The version remains 0.4.0, so the version checker will not offer
this replacement automatically. The multiplayer version and server runtime are
unchanged. Use the updated checksum list for the replacement files.

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

## Downloads

- [ZZ-Project-v0.4.0-Windows-Setup.exe](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.0/ZZ-Project-v0.4.0-Windows-Setup.exe)
- [ZZ-Project-v0.4.0-Linux.tar.gz](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.0/ZZ-Project-v0.4.0-Linux.tar.gz)
- [ZZ-Project-v0.4.0-source.zip](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.0/ZZ-Project-v0.4.0-source.zip)
- [ZZ-Multiplayer-v0.4.0.tar.gz](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.0/ZZ-Multiplayer-v0.4.0.tar.gz)
- [SHA256SUMS-PC02.txt](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.0/SHA256SUMS-PC02.txt)

See [INSTALL.md](INSTALL.md) for setup and [docs/ONLINE.md](docs/ONLINE.md)
for self-hosting instructions.

## Credits

Special thanks to theFeri for providing 50+ high-resolution playmat images, and
to **Valkyrie** for providing the English text.
