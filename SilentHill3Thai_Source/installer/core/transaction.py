"""Temp-file transaction coordinator shared by game-specific patch adapters."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .backup import BackupStore, BackupTarget, sha256_file


class TransactionError(RuntimeError):
    """A patch transaction could not be safely staged or committed."""


Validator = Callable[[Path], None]


@dataclass(frozen=True)
class StagedOperation:
    relative_path: str
    expected_original_sha256: str
    candidate: Path
    expected_patched_sha256: str
    validator: Validator


class PatchTransaction:
    """Validates every candidate before replacing any game file.

    The transaction owns a temporary directory outside the game data files.
    It never creates a backup from a target whose hash is not the approved
    original hash.  If a commit fails after a replacement, already-replaced
    files are restored from the immutable backup manifest.
    """

    def __init__(self, game_dir: Path, backup_store: BackupStore) -> None:
        self.game_dir = game_dir.resolve()
        self.backup_store = backup_store
        self.operations: list[StagedOperation] = []

    def stage(
        self,
        *,
        relative_path: str,
        expected_original_sha256: str,
        candidate: Path,
        expected_patched_sha256: str,
        validator: Validator,
    ) -> None:
        if not candidate.is_file():
            raise TransactionError(f"Candidate does not exist: {candidate}")
        if any(item.relative_path == relative_path for item in self.operations):
            raise TransactionError(f"Target staged twice: {relative_path}")
        self.operations.append(
            StagedOperation(relative_path, expected_original_sha256, candidate, expected_patched_sha256, validator)
        )

    def _preflight(self) -> tuple[BackupTarget, ...]:
        if not self.operations:
            raise TransactionError("No operations are staged")
        backups: list[BackupTarget] = []
        for operation in self.operations:
            target = self.game_dir / operation.relative_path
            if not target.is_file():
                raise TransactionError(f"Target does not exist: {operation.relative_path}")
            if sha256_file(target) != operation.expected_original_sha256:
                raise TransactionError(f"Target is not the approved original: {operation.relative_path}")
            if sha256_file(operation.candidate) != operation.expected_patched_sha256:
                raise TransactionError(f"Candidate hash mismatch: {operation.relative_path}")
            try:
                operation.validator(operation.candidate)
            except Exception as error:
                raise TransactionError(f"Candidate validation failed for {operation.relative_path}: {error}") from error
            backups.append(BackupTarget(operation.relative_path, operation.expected_original_sha256))
        return tuple(backups)

    def commit(self) -> list[str]:
        backups = self._preflight()
        self.backup_store.ensure_originals(backups)
        committed: list[StagedOperation] = []
        try:
            for operation in self.operations:
                target = self.game_dir / operation.relative_path
                temporary = target.with_name(target.name + ".mod-install-tmp")
                shutil.copy2(operation.candidate, temporary)
                if sha256_file(temporary) != operation.expected_patched_sha256:
                    temporary.unlink(missing_ok=True)
                    raise TransactionError(f"Commit staging hash mismatch: {operation.relative_path}")
                os.replace(temporary, target)
                committed.append(operation)
                if sha256_file(target) != operation.expected_patched_sha256:
                    raise TransactionError(f"Commit verification failed: {operation.relative_path}")
            return [operation.relative_path for operation in committed]
        except Exception as error:
            if committed:
                self.backup_store.restore(
                    BackupTarget(item.relative_path, item.expected_original_sha256) for item in committed
                )
            raise TransactionError(f"Transaction rolled back: {error}") from error


def temporary_workspace() -> tempfile.TemporaryDirectory[str]:
    """Create a workspace-only temporary area for unit and integration tests."""
    return tempfile.TemporaryDirectory(prefix="universal-mod-installer-")
