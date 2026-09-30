"""Generic, read-only validation primitives for installed mod targets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .backup import sha256_file


class ValidationError(RuntimeError):
    """A staged or installed target failed a required validation."""


Validator = Callable[[Path], None]


@dataclass(frozen=True)
class ExpectedTarget:
    """A target expected to exist at a relative game path after installation."""

    relative_path: str
    expected_sha256: str
    validator: Validator


def validate_targets(game_dir: Path, targets: Iterable[ExpectedTarget]) -> list[dict[str, str]]:
    """Validate installed targets without changing any file.

    A hash check is deliberately performed before the format-specific validator:
    this prevents a parser from treating an unexpected binary as a known-good
    installed output merely because it happens to be structurally readable.
    """

    results: list[dict[str, str]] = []
    for target in targets:
        path = game_dir / target.relative_path
        if not path.is_file():
            raise ValidationError(f"Installed target is missing: {target.relative_path}")
        actual_hash = sha256_file(path)
        if actual_hash != target.expected_sha256:
            raise ValidationError(
                f"Installed target hash mismatch: {target.relative_path}; "
                f"expected {target.expected_sha256}, got {actual_hash}"
            )
        try:
            target.validator(path)
        except Exception as error:
            raise ValidationError(f"Installed target format validation failed: {target.relative_path}: {error}") from error
        results.append({"relative_path": target.relative_path, "sha256": actual_hash, "status": "validated"})
    return results
