from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

INSTALLER_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = INSTALLER_ROOT.parent
if str(INSTALLER_ROOT) not in sys.path:
    sys.path.insert(0, str(INSTALLER_ROOT))

from games.silent_hill_3.operations import (
    OperationError,
    build_executable_candidate,
    build_msg_arc_candidate,
    validate_executable_candidate,
    validate_msg_arc_candidate,
)


class Phase4OperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name)
        self.baseline = WORKSPACE / "baseline" / "original"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_known_baseline_candidates_match_approved_outputs(self) -> None:
        exe = self.out / "sh3.exe"
        msg = self.out / "msg.arc"
        exe_report = build_executable_candidate(self.baseline / "sh3.exe", exe)
        msg_report = build_msg_arc_candidate(self.baseline / "data" / "msg.arc", msg)
        validate_executable_candidate(exe)
        validate_msg_arc_candidate(msg)
        self.assertEqual(exe_report["patched_sha256"], "45976F814862C13210222656D41BD074EE6EACEC559338530D337A5FB2C4F1F4")
        self.assertEqual(msg_report["patched_sha256"], "3060502498989D0F623C72D813329947DF2459771D3ED134CC9C03493EC68D95")

    def test_modified_source_is_rejected_before_candidate_creation(self) -> None:
        source = self.out / "modified.exe"
        source.write_bytes((self.baseline / "sh3.exe").read_bytes() + b"x")
        with self.assertRaises(OperationError):
            build_executable_candidate(source, self.out / "candidate.exe")
        self.assertFalse((self.out / "candidate.exe").exists())


if __name__ == "__main__":
    unittest.main()
