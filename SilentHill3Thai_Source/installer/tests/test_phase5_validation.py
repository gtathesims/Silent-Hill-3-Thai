from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.validation import ValidationError, validate_targets
from games.silent_hill_3.adapter import analyze_game, installed_validation_targets
from games.silent_hill_3.operations import (
    build_executable_candidate,
    build_msg_arc_candidate,
    validate_payload_integrity,
)


WORKSPACE = Path(__file__).resolve().parents[2]
BASELINE = WORKSPACE / "baseline" / "original"


class Phase5ValidationTests(unittest.TestCase):
    def _installed_fixture(self, root: Path) -> Path:
        game = root / "game"
        (game / "data").mkdir(parents=True)
        build_executable_candidate(BASELINE / "sh3.exe", game / "sh3.exe")
        build_msg_arc_candidate(BASELINE / "data" / "msg.arc", game / "data" / "msg.arc")
        from games.silent_hill_3.pictures import build_pic
        build_pic(BASELINE / 'data/pic.arc', game / 'data/pic.arc')
        return game

    def test_payload_manifest_and_known_installed_targets_validate(self) -> None:
        manifest = validate_payload_integrity()
        self.assertEqual(manifest["mod"]["id"], "silent-hill-3-thai")
        with tempfile.TemporaryDirectory() as temporary:
            game = self._installed_fixture(Path(temporary))
            results = validate_targets(game, installed_validation_targets())
            self.assertEqual([item["status"] for item in results], ["validated"] * 3)
            self.assertEqual(analyze_game(game)["overall_status"], "already-installed")

    def test_modified_installed_file_fails_before_format_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = self._installed_fixture(Path(temporary))
            executable = game / "sh3.exe"
            contents = bytearray(executable.read_bytes())
            contents[-1] ^= 0x01
            executable.write_bytes(contents)
            with self.assertRaises(ValidationError):
                validate_targets(game, installed_validation_targets())
            self.assertEqual(analyze_game(game)["overall_status"], "unsupported-or-mixed-state")
