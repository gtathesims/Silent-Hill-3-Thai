from __future__ import annotations

import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
SETUP = WORKSPACE / "installer" / "release" / "SilentHill3ThaiModSetup_v1.4.1.exe"


class InnoSetupBuildTests(unittest.TestCase):
    def test_direct_game_setup_is_built(self) -> None:
        """The release artifact is a direct setup, not a separately installed UI."""
        self.assertTrue(SETUP.is_file(), SETUP)
        self.assertGreater(SETUP.stat().st_size, 0)
