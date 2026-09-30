# Build on Windows x64

Recorded toolchain: Python 3.13.14 x64, PyInstaller 6.22.2,
pyinstaller-hooks-contrib 2026.7, Inno Setup 6.7.3.
Install Inno Setup at C:\Program Files (x86)\Inno Setup 6.
Third-party sources: https://github.com/pyinstaller/pyinstaller ,
https://github.com/python/cpython , https://github.com/jrsoftware/issrc .

## Required original game binary (excluded from this archive)

Supply the matching original sh3.exe at installer/payload/original_sh3.exe.
Size: 3,338,240 bytes.
SHA-256: 8FF8F74806F55843B9BC277508B17C8926999F292C65DBE7949325087D460918

The uploaded installer embeds this binary. Its source is not available to this
project. Full fallback behavior cannot be rebuilt without this exact input.
Do not silently omit the binary when comparing with the uploaded version.

## Commands

Open PowerShell in this directory after installing Python and Inno Setup:

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
Get-FileHash -LiteralPath .\installer\payload\original_sh3.exe -Algorithm SHA256
& .\installer\tools\build_windows_bundle.ps1
& .\installer\tools\build_inno_setup.ps1
```

Confirm the input hash before building. Outputs:
- installer/build/windows_bundle/SilentHill3ThaiModInstaller/ModPatcher.exe
- installer/release/SilentHill3ThaiModSetup.exe

The Desktop release was renamed to Silent Hill 3 Thai Localization.exe.
Timestamps and tool environment can change output hashes. Byte-identical
reproducible builds are not claimed.

## Optional integration tests

Supply baseline/original next to installer, containing original sh3.exe,
data/msg.arc and data/pic.arc. Accepted hashes are in
installer/games/silent_hill_3/profile.json. Game fixtures are excluded.
After building the engine:

```powershell
python -m unittest discover -s installer/tests -p test_release_bundle.py -v
$env:TEST_FROZEN_ENGINE = '1'
python -m unittest discover -s installer/tests -p test_exe_fallback.py -v
```

Tests use temporary game copies. Manual --patch and --restore modify their
selected game folder; --analyze is read-only.
