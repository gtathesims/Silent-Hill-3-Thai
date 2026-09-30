#!/usr/bin/env python3
"""Universal Mod Installer Patch Engine — analysis and verified restore.

`--analyze` and `--dry-run` never modify the selected game directory.
`--restore` is enabled only when an immutable, verified original backup exists.
Patching remains unavailable until its complete install flow is enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.backup import BackupError
from core.logging_utils import write_run_log
from core.preflight import PreflightError, check_targets_available, ensure_free_space
from core.transaction import TransactionError
from core.validation import ValidationError, validate_targets
from games.silent_hill_3.adapter import (
    analyze_game,
    backup_store_for,
    estimated_install_space,
    installed_validation_targets,
    installer_state_root,
    original_backup_targets,
    prepare_patch_transaction,
    write_installed_metadata,
    restore_backup_targets,
    fallback_executable,
    cleanup_restored_install,
)
from games.silent_hill_3.operations import OperationError, validate_payload_integrity


EXIT_SUCCESS = 0
EXIT_UNSUPPORTED = 10
EXIT_TARGET_MISSING = 11
EXIT_RESTORE_FAILURE = 17
EXIT_PATCH_FAILURE = 15
EXIT_VALIDATION_FAILURE = 16
EXIT_PAYLOAD_FAILURE = 18
EXIT_ARGUMENT_ERROR = 64


def writable_state(game_dir: Path) -> dict[str, object]:
    try:
        usage = shutil.disk_usage(game_dir)
        return {
            "directory_exists": game_dir.is_dir(),
            "directory_writable": os.access(game_dir, os.W_OK),
            "free_bytes": usage.free,
        }
    except OSError as error:
        return {"directory_exists": game_dir.is_dir(), "directory_writable": False, "error": str(error)}


def write_game_log(game_dir: Path, report: dict[str, object], state_dir: Path | None = None) -> None:
    """Logging must not change the result of an otherwise verified command."""
    try:
        report["log_path"] = str(write_run_log(installer_state_root(game_dir, state_dir) / "logs", report))
    except OSError as error:
        report.setdefault("warnings", []).append(f"Could not write installer log: {error}")


def patch_game(game_dir: Path, state_dir: Path | None = None, allow_exe_fallback: bool = False) -> tuple[dict[str, object], int]:
    """Perform the only write-capable install flow after every preflight passes."""
    analysis = analyze_game(game_dir, allow_exe_fallback)
    report: dict[str, object] = {
        "game_dir": str(game_dir),
        "mode": "patch",
        "initial_analysis": analysis,
        "modifies_game_files": True,
    }
    if analysis["overall_status"] == "already-installed":
        try:
            report["validated_targets"] = validate_targets(game_dir, installed_validation_targets())
            report["overall_status"] = "already-installed-verified"
            report["modifies_game_files"] = False
            return report, EXIT_SUCCESS
        except ValidationError as error:
            report.update({"overall_status": "installed-state-invalid", "error": str(error)})
            return report, EXIT_VALIDATION_FAILURE
    if analysis["overall_status"] not in {"known-supported", "supported-with-exe-fallback"}:
        report.update(
            {
                "overall_status": "patch-refused",
                "error": "Game is not the approved original baseline; no file was modified.",
            }
        )
        return report, EXIT_UNSUPPORTED

    try:
        payload_manifest = validate_payload_integrity()
        report['exe_fallback_used'] = analysis['overall_status'] == 'supported-with-exe-fallback'
        if report['exe_fallback_used']:
            fallback_executable()
        profile_targets = analysis["targets"]
        target_paths = [Path(item['path']) for item in profile_targets.values()]
        report["lock_preflight"] = check_targets_available(target_paths)
        requirements = estimated_install_space(game_dir)
        report["space_preflight"] = {
            "game": ensure_free_space(game_dir, requirements["game_commit_and_backup_bytes"], purpose="backup and commit"),
            "temporary": ensure_free_space(
                Path(tempfile.gettempdir()), requirements["temporary_candidate_bytes"], purpose="temporary candidates"
            ),
        }
        report["payload"] = {
            "mod": payload_manifest["mod"],
            "operations": [item["id"] for item in payload_manifest["operations"]],
        }
        with tempfile.TemporaryDirectory(prefix="silent-hill-3-thai-install-") as candidate_directory:
            transaction = prepare_patch_transaction(game_dir, Path(candidate_directory), state_dir, allow_exe_fallback)
            report["committed_targets"] = transaction.commit()
        report["validated_targets"] = validate_targets(game_dir, installed_validation_targets())
        post_install = analyze_game(game_dir)
        if post_install["overall_status"] != "already-installed":
            raise ValidationError("Post-install analysis did not recognize the approved installed state")
        report["installed_metadata"] = str(write_installed_metadata(game_dir, state_dir))
        report["post_install"] = post_install
        report["overall_status"] = "installed"
        return report, EXIT_SUCCESS
    except OperationError as error:
        report.update({"overall_status": "payload-or-operation-failed", "error": str(error)})
        return report, EXIT_PAYLOAD_FAILURE
    except (PreflightError, TransactionError, BackupError, OSError) as error:
        report.update({"overall_status": "patch-failed", "error": str(error)})
        return report, EXIT_PATCH_FAILURE
    except ValidationError as error:
        report.update({"overall_status": "post-install-validation-failed", "error": str(error)})
        return report, EXIT_VALIDATION_FAILURE


def main() -> int:
    parser = argparse.ArgumentParser(description="Silent Hill 3 Thai Mod patch engine.")
    parser.add_argument("--game-dir", type=Path, required=True, help="Silent Hill 3 game directory")
    parser.add_argument("--state-dir", type=Path, help="Directory for backup, metadata, and logs")
    parser.add_argument('--allow-exe-fallback', action='store_true', help='Back up an unrecognized EXE and install using the bundled approved original')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--analyze", action="store_true", help="Inspect compatibility without changing files")
    mode.add_argument("--dry-run", action="store_true", help="Show whether a future patch operation would be allowed")
    mode.add_argument("--patch", action="store_true", help="Install the Thai mod after safety preflight")
    mode.add_argument("--restore", action="store_true", help="Restore verified original files from this mod's backup")
    parser.add_argument("--json", type=Path, help="Write a command report to the specified path")
    args = parser.parse_args()

    game_dir = args.game_dir.resolve()
    state_dir = args.state_dir.resolve() if args.state_dir else None
    if not game_dir.is_dir():
        report = {"overall_status": "game-directory-missing", "safe_to_patch": False, "game_dir": str(game_dir)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return EXIT_TARGET_MISSING

    if args.restore:
        report: dict[str, object] = {"game_dir": str(game_dir), "mode": "restore", "modifies_game_files": True}
        try:
            store = backup_store_for(game_dir, state_dir)
            restored = store.restore(restore_backup_targets(game_dir, state_dir))
            post_restore = analyze_game(game_dir)
            # BackupStore verifies exact pre-install hashes, including an unknown EXE.
            report['removed_installer_files'] = cleanup_restored_install(game_dir, state_dir)
            report.update({"overall_status": "restored", "restored_targets": restored, "post_restore": post_restore})
            exit_code = EXIT_SUCCESS
        except (BackupError, OSError, ValueError) as error:
            report.update({"overall_status": "restore-failed", "error": str(error)})
            exit_code = EXIT_RESTORE_FAILURE
        if exit_code != EXIT_SUCCESS:
            write_game_log(game_dir, report, state_dir)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code

    if args.patch:
        report, exit_code = patch_game(game_dir, state_dir, args.allow_exe_fallback)
        write_game_log(game_dir, report, state_dir)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code

    report = analyze_game(game_dir, args.allow_exe_fallback)
    report["mode"] = "dry-run" if args.dry_run else "analyze"
    report["write_check"] = writable_state(game_dir)
    report["modifies_game_files"] = False
    if args.dry_run and report["overall_status"] in {"known-supported", "supported-with-exe-fallback"}:
        try:
            manifest = validate_payload_integrity()
            if report['overall_status'] == 'supported-with-exe-fallback':
                fallback_executable()
            requirements = estimated_install_space(game_dir)
            report["planned_operations"] = [item["id"] for item in manifest["operations"]]
            report["space_required_bytes"] = requirements
        except (OperationError, OSError, ValueError) as error:
            report["safe_to_patch"] = False
            report["payload_preflight_error"] = str(error)
    report["next_phase_required"] = "installer frontend and expanded compatibility profiles"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["overall_status"] in {"known-supported", "already-installed", "supported-with-exe-fallback"}:
        if report.get('payload_preflight_error'):
            return EXIT_PAYLOAD_FAILURE
        return EXIT_SUCCESS
    if report["overall_status"] in {"target-missing", "game-directory-missing"}:
        return EXIT_TARGET_MISSING
    return EXIT_UNSUPPORTED


if __name__ == "__main__":
    raise SystemExit(main())
