from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import sys

INSTALLER_ROOT = Path(__file__).resolve().parents[1]
if str(INSTALLER_ROOT) not in sys.path:
    sys.path.insert(0, str(INSTALLER_ROOT))

from core.backup import BackupError, BackupStore, BackupTarget, sha256_file
from core.transaction import PatchTransaction, TransactionError


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


class BackupTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.game.mkdir()
        (self.game / "data").mkdir()
        self.target = self.game / "data" / "target.bin"
        self.original = b"original payload"
        self.patched = b"patched payload"
        self.target.write_bytes(self.original)
        self.backups = BackupStore(
            self.game,
            self.root / "backups",
            game_id="fixture-game",
            mod_id="fixture-mod",
            mod_version="test",
        )
        self.backup_target = BackupTarget("data/target.bin", digest(self.original))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def candidate(self) -> Path:
        path = self.root / "candidate.bin"
        path.write_bytes(self.patched)
        return path

    @staticmethod
    def accepts_expected(path: Path) -> None:
        if path.read_bytes() != b"patched payload":
            raise ValueError("unexpected fixture payload")

    def test_backup_commit_and_restore(self) -> None:
        transaction = PatchTransaction(self.game, self.backups)
        transaction.stage(
            relative_path="data/target.bin",
            expected_original_sha256=digest(self.original),
            candidate=self.candidate(),
            expected_patched_sha256=digest(self.patched),
            validator=self.accepts_expected,
        )
        self.assertEqual(transaction.commit(), ["data/target.bin"])
        self.assertEqual(self.target.read_bytes(), self.patched)
        self.assertEqual(self.backups.restore([self.backup_target]), ["data/target.bin"])
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_validation_failure_leaves_original_untouched(self) -> None:
        transaction = PatchTransaction(self.game, self.backups)
        transaction.stage(
            relative_path="data/target.bin",
            expected_original_sha256=digest(self.original),
            candidate=self.candidate(),
            expected_patched_sha256=digest(self.patched),
            validator=lambda _: (_ for _ in ()).throw(ValueError("intentional failure")),
        )
        with self.assertRaises(TransactionError):
            transaction.commit()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.backups.manifest_path.exists())

    def test_existing_backup_is_not_replaced_by_patched_target(self) -> None:
        self.backups.ensure_originals([self.backup_target])
        self.target.write_bytes(self.patched)
        self.backups.ensure_originals([self.backup_target])
        self.assertEqual(sha256_file(self.backups.files_dir / "data__target.bin"), digest(self.original))


if __name__ == "__main__":
    unittest.main()
