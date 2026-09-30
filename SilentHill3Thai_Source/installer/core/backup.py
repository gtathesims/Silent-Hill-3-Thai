"""Immutable backup manifests for transactional mod installers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class BackupError(RuntimeError):
    """A backup is missing, corrupt, or would overwrite the original state."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


@dataclass(frozen=True)
class BackupTarget:
    relative_path: str
    expected_original_sha256: str


class BackupStore:
    """Stores one verifiable original copy for a mod/game combination.

    An existing manifest is immutable.  This avoids the common failure mode
    where a reinstall backs up an already-patched game file as "original".
    """

    MANIFEST_NAME = "backup_manifest.json"

    def __init__(self, game_dir: Path, root: Path, *, game_id: str, mod_id: str, mod_version: str) -> None:
        self.game_dir = game_dir.resolve()
        self.root = root.resolve()
        self.game_id = game_id
        self.mod_id = mod_id
        self.mod_version = mod_version
        self.files_dir = self.root / "files"
        self.manifest_path = self.root / self.MANIFEST_NAME

    def _read_manifest(self) -> dict[str, object] | None:
        if not self.manifest_path.exists():
            return None
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BackupError(f"Cannot read backup manifest: {error}") from error

    @staticmethod
    def _backup_name(relative_path: str) -> str:
        return relative_path.replace("/", "__").replace("\\", "__")

    def validate(self, targets: Iterable[BackupTarget] | None = None) -> dict[str, object]:
        manifest = self._read_manifest()
        if manifest is None:
            raise BackupError("Backup manifest does not exist")
        if manifest.get("game_id") != self.game_id or manifest.get("mod_id") != self.mod_id:
            raise BackupError("Backup manifest belongs to another game or mod")
        expected = {target.relative_path: target.expected_original_sha256 for target in targets or ()}
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise BackupError("Backup manifest has no files")
        for entry in entries:
            if not isinstance(entry, dict):
                raise BackupError("Backup manifest contains an invalid file entry")
            relative_path = entry.get("relative_path")
            backup_name = entry.get("backup_name")
            original_hash = entry.get("original_sha256")
            if not isinstance(relative_path, str) or not isinstance(backup_name, str) or not isinstance(original_hash, str):
                raise BackupError("Backup manifest entry is incomplete")
            if relative_path in expected and expected[relative_path] != original_hash:
                raise BackupError(f"Backup hash differs from expected original for {relative_path}")
            backup_file = self.files_dir / backup_name
            if not backup_file.is_file():
                raise BackupError(f"Backup file is missing: {relative_path}")
            if sha256_file(backup_file) != original_hash:
                raise BackupError(f"Backup file hash does not match manifest: {relative_path}")
        return manifest

    def ensure_originals(self, targets: Iterable[BackupTarget]) -> dict[str, object]:
        targets = tuple(targets)
        if not targets:
            raise BackupError("No backup targets were supplied")
        existing = self._read_manifest()
        if existing is not None:
            self.validate(targets)
            backed_up = {entry['relative_path'] for entry in existing['files']}
            missing = tuple(target for target in targets if target.relative_path not in backed_up)
            if not missing:
                return self.validate(targets)
            targets = missing

        staged: list[tuple[BackupTarget, Path, str, int]] = []
        for target in targets:
            source = self.game_dir / target.relative_path
            if not source.is_file():
                raise BackupError(f"Cannot back up missing target: {target.relative_path}")
            actual_hash = sha256_file(source)
            if actual_hash != target.expected_original_sha256:
                raise BackupError(
                    f"Refusing to back up non-original file {target.relative_path}: "
                    f"expected {target.expected_original_sha256}, got {actual_hash}"
                )
            staged.append((target, source, actual_hash, source.stat().st_size))

        self.files_dir.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, object]] = list(existing['files']) if existing else []
        created: list[Path] = []
        try:
            for target, source, actual_hash, size in staged:
                backup_name = self._backup_name(target.relative_path)
                destination = self.files_dir / backup_name
                if destination.exists():
                    raise BackupError(f"Backup destination already exists: {destination.name}")
                shutil.copy2(source, destination)
                created.append(destination)
                if sha256_file(destination) != actual_hash:
                    raise BackupError(f"Backup verification failed: {target.relative_path}")
                entries.append(
                    {
                        "relative_path": target.relative_path,
                        "backup_name": backup_name,
                        "original_sha256": actual_hash,
                        "size": size,
                    }
                )
            manifest = {
                "schema_version": 1,
                "game_id": self.game_id,
                "mod_id": self.mod_id,
                "mod_version_created": self.mod_version,
                "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "files": entries,
            }
            temporary_manifest = self.root / (self.MANIFEST_NAME + ".tmp")
            temporary_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary_manifest, self.manifest_path)
            return self.validate(targets)
        except Exception:
            for created_file in created:
                created_file.unlink(missing_ok=True)
            (self.root / (self.MANIFEST_NAME + ".tmp")).unlink(missing_ok=True)
            if not self.manifest_path.exists() and self.files_dir.exists() and not any(self.files_dir.iterdir()):
                self.files_dir.rmdir()
            raise

    def restore(self, targets: Iterable[BackupTarget]) -> list[str]:
        targets = tuple(targets)
        manifest = self.validate(targets)
        by_relative_path = {entry["relative_path"]: entry for entry in manifest["files"]}  # type: ignore[index]
        staging_root = Path(tempfile.mkdtemp(prefix=".mod-installer-restore-", dir=self.game_dir))
        staged: list[tuple[BackupTarget, Path, Path, str]] = []
        restored: list[tuple[BackupTarget, Path, str]] = []
        try:
            # Stage every original and every current target before replacing any
            # game file.  The current copy makes an interrupted restore recoverable.
            for number, target in enumerate(targets):
                entry = by_relative_path.get(target.relative_path)
                if entry is None:
                    raise BackupError(f"Backup does not contain {target.relative_path}")
                source = self.files_dir / str(entry["backup_name"])
                destination = self.game_dir / target.relative_path
                if not destination.is_file():
                    raise BackupError(f"Cannot restore over missing target: {target.relative_path}")
                original_stage = staging_root / f"{number}.original"
                current_stage = staging_root / f"{number}.current"
                shutil.copy2(source, original_stage)
                if sha256_file(original_stage) != target.expected_original_sha256:
                    raise BackupError(f"Restore staging hash failed: {target.relative_path}")
                shutil.copy2(destination, current_stage)
                current_hash = sha256_file(current_stage)
                staged.append((target, original_stage, current_stage, current_hash))

            for target, original_stage, current_stage, current_hash in staged:
                destination = self.game_dir / target.relative_path
                os.replace(original_stage, destination)
                restored.append((target, current_stage, current_hash))
                if sha256_file(destination) != target.expected_original_sha256:
                    raise BackupError(f"Restore verification failed: {target.relative_path}")
            return [target.relative_path for target, _, _ in restored]
        except Exception as error:
            rollback_errors: list[str] = []
            for target, current_stage, current_hash in reversed(restored):
                destination = self.game_dir / target.relative_path
                try:
                    if not current_stage.is_file() or sha256_file(current_stage) != current_hash:
                        raise BackupError("previous target staging copy is unavailable")
                    os.replace(current_stage, destination)
                    if sha256_file(destination) != current_hash:
                        raise BackupError("previous target verification failed")
                except Exception as rollback_error:
                    rollback_errors.append(f"{target.relative_path}: {rollback_error}")
            detail = f"Restore failed: {error}"
            if rollback_errors:
                detail += "; rollback failures: " + "; ".join(rollback_errors)
            raise BackupError(detail) from error
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
