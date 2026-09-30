from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.backup import sha256_file
from core.transaction import PatchTransaction
from games.silent_hill_3.adapter import (
    analyze_game,
    backup_store_for,
    original_backup_targets,
)
from games.silent_hill_3.operations import (
    build_executable_candidate,
    build_msg_arc_candidate,
    validate_executable_candidate,
    validate_msg_arc_candidate,
)


WORKSPACE = Path(__file__).resolve().parents[2]
BASELINE = WORKSPACE / "baseline" / "original"


class Phase6RestoreTests(unittest.TestCase):
    def test_verified_restore_returns_patched_fixture_to_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            (game / "data").mkdir(parents=True)
            shutil.copy2(BASELINE / "sh3.exe", game / "sh3.exe")
            shutil.copy2(BASELINE / "data" / "msg.arc", game / "data" / "msg.arc")
            shutil.copy2(BASELINE / "data" / "pic.arc", game / "data" / "pic.arc")
            candidates = Path(temporary) / "candidates"
            exe_candidate = candidates / "sh3.exe"
            msg_candidate = candidates / "msg.arc"
            build_executable_candidate(game / "sh3.exe", exe_candidate)
            build_msg_arc_candidate(game / "data" / "msg.arc", msg_candidate)

            transaction = PatchTransaction(game, backup_store_for(game))
            from games.silent_hill_3.pictures import build_pic, validate_pic
            pic_candidate = candidates / 'pic.arc'
            build_pic(game / 'data/pic.arc', pic_candidate)
            transaction.stage(relative_path='data/pic.arc',
                              expected_original_sha256=sha256_file(BASELINE / 'data/pic.arc'),
                              candidate=pic_candidate, expected_patched_sha256=sha256_file(pic_candidate),
                              validator=validate_pic)
            transaction.stage(
                relative_path="sh3.exe",
                expected_original_sha256=sha256_file(BASELINE / "sh3.exe"),
                candidate=exe_candidate,
                expected_patched_sha256=sha256_file(exe_candidate),
                validator=validate_executable_candidate,
            )
            transaction.stage(
                relative_path="data/msg.arc",
                expected_original_sha256=sha256_file(BASELINE / "data" / "msg.arc"),
                candidate=msg_candidate,
                expected_patched_sha256=sha256_file(msg_candidate),
                validator=validate_msg_arc_candidate,
            )
            transaction.commit()
            self.assertEqual(analyze_game(game)["overall_status"], "already-installed")

            restored = backup_store_for(game).restore(original_backup_targets())
            self.assertEqual(restored, ["data/pic.arc", "sh3.exe", "data/msg.arc"])
            self.assertEqual(sha256_file(game / "sh3.exe"), sha256_file(BASELINE / "sh3.exe"))
            self.assertEqual(sha256_file(game / "data" / "msg.arc"), sha256_file(BASELINE / "data" / "msg.arc"))
            self.assertEqual(analyze_game(game)["overall_status"], "known-supported")
