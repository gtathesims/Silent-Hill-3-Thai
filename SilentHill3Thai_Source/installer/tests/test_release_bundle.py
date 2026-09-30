from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
BASELINE = WORKSPACE / "baseline" / "original"
BUNDLE = WORKSPACE / "installer" / "build" / "windows_bundle" / "SilentHill3ThaiModInstaller"
ENGINE = BUNDLE / "ModPatcher.exe"


class ReleaseBundleTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        game = root / "game"
        (game / "data").mkdir(parents=True)
        shutil.copy2(BASELINE / "sh3.exe", game / "sh3.exe")
        shutil.copy2(BASELINE / "data" / "msg.arc", game / "data" / "msg.arc")
        shutil.copy2(BASELINE / "data" / "pic.arc", game / "data" / "pic.arc")
        return game

    def _run(self, game: Path, command: str, state_dir: Path) -> dict[str, object]:
        completed = subprocess.run(
            [str(ENGINE), "--game-dir", str(game), "--state-dir", str(state_dir), command],
            cwd=BUNDLE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=90,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        return json.loads(completed.stdout)

    def test_standalone_engine_full_install_restore_cycle(self) -> None:
        self.assertTrue(ENGINE.is_file())
        with tempfile.TemporaryDirectory() as temporary:
            game = self._fixture(Path(temporary))
            state_dir = game / ".thai_mod_installer"
            dry_run = self._run(game, "--dry-run", state_dir)
            self.assertEqual(dry_run["overall_status"], "known-supported")
            self.assertFalse((game / ".thai_mod_installer").exists())

            installed = self._run(game, "--patch", state_dir)
            self.assertEqual(installed["overall_status"], "installed")
            self.assertTrue((game / ".thai_mod_installer" / "installed_mod.json").is_file())
            self.assertTrue((game / "data" / "pic.arc").exists())

            repeated = self._run(game, "--patch", state_dir)
            self.assertEqual(repeated["overall_status"], "already-installed-verified")

            restored = self._run(game, "--restore", state_dir)
            self.assertEqual(restored["overall_status"], "restored")
            self.assertFalse((game / ".thai_mod_installer" / "installed_mod.json").exists())
            self.assertFalse(state_dir.exists())
            after = self._run(game, "--dry-run", state_dir)
            self.assertEqual(after["overall_status"], "known-supported")
