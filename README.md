# Silent Hill 3 Thai Localization - source review

Mod: https://www.nexusmods.com/silenthill3/mods/88
Display name: Silent Hill 3 Thai Localization

This package includes the custom Python patch engine, Inno Setup wizard, build
scripts, required archive helper, tests, localization payloads and welcome image.
Generated executables, caches, logs and saves are excluded. Read BUILD.md.

## Local release identification

Silent Hill 3 Thai Localization.exe
SHA-256: 20124CC0A3DD195D212D29B1CDFB91D5139686E99E007B0338E2270A1A82EBD7

Silent Hill 3 Thai Localization.zip
SHA-256: D6C3620F020A7EF9C313265BD2518D2445B77BC03FF09926EF743BD4A795B25C

The local EXE matches the recorded release hash. The remote upload has
not been independently downloaded and hashed.

## Review entry points and behavior

- installer/inno/SilentHill3ThaiModInstaller.iss: wizard and engine invocation.
- installer/mod_patcher.py: analysis, install and restore entry points.
- installer/games/silent_hill_3/: profiles, executable patch, archive rebuilding,
  executable fallback and cleanup after successful restore.
- installer/core/: backup, validation, preflight, transactions and logging.
- tools/sh3_msg_common.py: required archive parser/rebuilder.
- installer/payload/: localization JSON; resource bytes use zlib/base64 as declared.

Inno Setup places ModPatcher.exe in LocalAppData/SilentHill3ThaiMod and invokes it
against the selected game directory. It modifies sh3.exe, data/msg.arc and
data/pic.arc for Thai fonts, text and menu images. Backups and logs are stored in
.thai_mod_installer. Successful restore returns verified pre-install files and
cleans installer-owned state. The helper in LocalAppData remains after restore.

The distributed installer ALSO embeds an original game EXE as a compatibility
fallback. If the user's EXE is unrecognized, it is backed up and a patched EXE
is built from the bundled original. This original game EXE is proprietary
third-party binary material. Its source is NOT available in this project, and
it is NOT included in this source ZIP. BUILD.md specifies its input hash. No
redistribution permission for the original game is asserted. Nexus Support
should advise whether this fallback must be removed for distribution.

The reviewed custom runtime source contains no network client, telemetry or
updater. PyInstaller supplies its bootloader and Python runtime; Inno Setup
supplies the installer runtime. Quarantine is not claimed to be a confirmed
false positive. Byte-identical reproducible builds are not claimed.
