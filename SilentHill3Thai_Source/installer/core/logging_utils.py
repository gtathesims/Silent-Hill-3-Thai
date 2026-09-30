"""Small structured run-log helper shared by patch engine commands."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def write_run_log(log_dir: Path, report: dict[str, Any]) -> Path:
    """Write a JSON log atomically after a command has produced its report."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = log_dir / f"mod-installer-{timestamp}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
