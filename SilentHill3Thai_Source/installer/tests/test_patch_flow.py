from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
INSTALLER = WORKSPACE / "installer"
if str(INSTALLER) not in sys.path:
    sys.path.insert(0, str(INSTALLER))

from core.backup import sha256_file
from games.silent_hill_3.adapter import analyze_game
from mod_patcher import EXIT_SUCCESS, EXIT_UNSUPPORTED, patch_game


BASELINE = WORKSPACE / "baseline" / "original"


class PatchFlowTests(unittest.TestCase):
    def _original_fixture(self, root: Path) -> Path:
        game = root / "game"
        (game / "data").mkdir(parents=True)
        shutil.copy2(BASELINE / "sh3.exe", game / "sh3.exe")
        shutil.copy2(BASELINE / "data" / "msg.arc", game / "data" / "msg.arc")
        shutil.copy2(BASELINE / "data" / "pic.arc", game / "data" / "pic.arc")
        return game

    def test_patch_then_repeat_is_verified_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = self._original_fixture(Path(temporary))
            first, first_code = patch_game(game)
            self.assertEqual(first_code, EXIT_SUCCESS)
            self.assertEqual(first["overall_status"], "installed")
            self.assertTrue((game / ".thai_mod_installer" / "installed_mod.json").is_file())
            self.assertTrue(
                (game / ".thai_mod_installer" / "backups" / "silent-hill-3-thai" / "backup_manifest.json").is_file()
            )
            self.assertEqual(analyze_game(game)["overall_status"], "already-installed")

            second, second_code = patch_game(game)
            self.assertEqual(second_code, EXIT_SUCCESS)
            self.assertEqual(second["overall_status"], "already-installed-verified")
            self.assertFalse(second["modifies_game_files"])

    def test_nonbaseline_game_is_refused_without_creating_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = self._original_fixture(Path(temporary))
            executable = game / "sh3.exe"
            data = bytearray(executable.read_bytes())
            data[-1] ^= 0x01
            executable.write_bytes(data)
            original_hash = sha256_file(executable)
            report, code = patch_game(game)
            self.assertEqual(code, EXIT_UNSUPPORTED)
            self.assertEqual(report["overall_status"], "patch-refused")
            self.assertEqual(sha256_file(executable), original_hash)
            self.assertFalse((game / ".thai_mod_installer" / "backups").exists())

    def test_explicit_state_directory_owns_backup_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = self._original_fixture(root)
            state_dir = root / "custom-state"
            report, code = patch_game(game, state_dir)
            self.assertEqual(code, EXIT_SUCCESS)
            self.assertEqual(report["overall_status"], "installed")
            self.assertTrue((state_dir / "installed_mod.json").is_file())
            self.assertTrue(
                (state_dir / "backups" / "silent-hill-3-thai" / "backup_manifest.json").is_file()
            )
            self.assertFalse((game / ".thai_mod_installer").exists())
