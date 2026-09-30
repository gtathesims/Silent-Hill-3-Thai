"""Reusable preflight checks that never modify game targets."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable


class PreflightError(RuntimeError):
    """A required install condition is not satisfied."""


def check_targets_available(paths: Iterable[Path]) -> list[str]:
    """Verify targets exist and can be opened read/write before a transaction.

    This is a conservative Windows lock/permission preflight.  A lock may still
    appear after this check, so commit verification remains mandatory.
    """
    checked: list[str] = []
    for path in paths:
        if not path.is_file():
            raise PreflightError(f"Required target is missing: {path}")
        try:
            with path.open("r+b"):
                pass
        except OSError as error:
            raise PreflightError(f"Target is unavailable or locked; close the game and retry: {path}: {error}") from error
        checked.append(str(path))
    return checked


def ensure_free_space(directory: Path, required_bytes: int, *, purpose: str) -> dict[str, int | str]:
    if required_bytes < 0:
        raise ValueError("required_bytes cannot be negative")
    usage = shutil.disk_usage(directory)
    if usage.free < required_bytes:
        raise PreflightError(
            f"Insufficient free space for {purpose}: need {required_bytes} bytes, have {usage.free} bytes"
        )
    return {"directory": str(directory), "required_bytes": required_bytes, "free_bytes": usage.free}
