"""Read-only compatibility adapter for the Silent Hill 3 Thai mod.

This module intentionally performs no writes.  Patch and restore operations are
implemented only after the analyzer has established their safety contracts.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

if getattr(sys, "frozen", False):
    INSTALLER_ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    TOOLS = INSTALLER_ROOT / "tools"
else:
    INSTALLER_ROOT = Path(__file__).resolve().parents[2]
    TOOLS = INSTALLER_ROOT.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sh3_msg_common import archive_entries, entry_payload, parse_message_table  # noqa: E402


PROFILE_PATH = Path(__file__).with_name("profile.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_profile() -> dict[str, Any]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def parse_pe(data: bytes) -> dict[str, Any]:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("missing DOS MZ header")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("missing PE signature")
    machine, section_count, _, _, _, optional_size, _ = struct.unpack_from(
        "<HHIIIHH", data, pe_offset + 4
    )
    optional_offset = pe_offset + 24
    if optional_offset + optional_size > len(data):
        raise ValueError("optional header extends beyond executable")
    optional_magic = struct.unpack_from("<H", data, optional_offset)[0]
    if optional_magic != 0x10B:
        raise ValueError(f"unsupported PE optional-header magic {optional_magic:04X}")
    image_base = struct.unpack_from("<I", data, optional_offset + 28)[0]
    sections: list[dict[str, int | str]] = []
    section_offset = optional_offset + optional_size
    for number in range(section_count):
        offset = section_offset + number * 40
        if offset + 40 > len(data):
            raise ValueError("section table extends beyond executable")
        name = data[offset : offset + 8].split(b"\0", 1)[0].decode("ascii", "replace")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        if raw_offset + raw_size > len(data):
            raise ValueError(f"section {name!r} extends beyond executable")
        sections.append(
            {
                "name": name,
                "virtual_size": virtual_size,
                "virtual_address": virtual_address,
                "raw_size": raw_size,
                "raw_offset": raw_offset,
            }
        )
    return {
        "machine": machine,
        "optional_magic": optional_magic,
        "image_base": image_base,
        "sections": sections,
    }


def va_to_offset(pe: dict[str, Any], va: int) -> int:
    rva = va - int(pe["image_base"])
    for section in pe["sections"]:
        start = int(section["virtual_address"])
        extent = max(int(section["virtual_size"]), int(section["raw_size"]))
        if start <= rva < start + extent:
            return int(section["raw_offset"]) + rva - start
    raise ValueError(f"VA {va:08X} is not inside a raw PE section")


def at_va(data: bytes, pe: dict[str, Any], va_hex: str, length: int) -> bytes:
    offset = va_to_offset(pe, int(va_hex, 16))
    if offset + length > len(data):
        raise ValueError(f"VA {va_hex} extends beyond executable")
    return data[offset : offset + length]


def inspect_executable(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.is_file():
        result.update({"state": "missing", "compatible": False})
        return result
    data = path.read_bytes()
    digest = sha256_file(path)
    result.update({"size": len(data), "sha256": digest})
    try:
        pe = parse_pe(data)
        result["pe"] = {
            "machine": f"{pe['machine']:04X}",
            "optional_magic": f"{pe['optional_magic']:04X}",
            "image_base": f"{pe['image_base']:08X}",
            "section_count": len(pe["sections"]),
        }
        expected_pe = config["pe"]
        pe_matches = (
            result["pe"]["machine"] == expected_pe["machine"]
            and result["pe"]["optional_magic"] == expected_pe["optional_magic"]
            and result["pe"]["image_base"] == expected_pe["image_base"]
        )
        signatures = config["patch_signatures"]
        original_match = all(
            at_va(data, pe, signatures[key + "_va"], len(bytes.fromhex(signatures[key + "_original"])))
            == bytes.fromhex(signatures[key + "_original"])
            for key in ("font_metrics", "raster_lookup", "metrics_copy")
        )
        patched_match = all(
            at_va(data, pe, signatures[key + "_va"], len(bytes.fromhex(signatures[key + "_patched"])))
            == bytes.fromhex(signatures[key + "_patched"])
            for key in ("font_metrics", "raster_lookup", "metrics_copy")
        )
    except (OSError, ValueError, struct.error) as error:
        result.update({"state": "invalid", "compatible": False, "reason": str(error)})
        return result

    result["signature_checks"] = {
        "profile_pe_matches": pe_matches,
        "original_patch_context_matches": original_match,
        "patched_patch_context_matches": patched_match,
    }
    if digest == config["known_original_sha256"] and original_match:
        result.update({"state": "known-original", "compatible": True})
    elif digest == config["known_patched_sha256"] and patched_match:
        result.update({"state": "known-patched", "compatible": True})
    elif pe_matches and original_match:
        result.update(
            {
                "state": "unknown-structural-candidate",
                "compatible": False,
                "reason": "PE context matches, but this Phase-2 analyzer has no approved unknown-version patch profile.",
            }
        )
    else:
        result.update(
            {
                "state": "unsupported",
                "compatible": False,
                "reason": "Required PE structure or patch context does not match uniquely.",
            }
        )
    return result


def inspect_messages(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.is_file():
        result.update({"state": "missing", "compatible": False})
        return result
    data = path.read_bytes()
    digest = sha256_file(path)
    result.update({"size": len(data), "sha256": digest})
    try:
        entries = archive_entries(data)
        message_entries = 0
        for entry in entries:
            if entry.index in config["font_entry_indices"]:
                continue
            parse_message_table(entry_payload(data, entry))
            message_entries += 1
    except (OSError, ValueError, struct.error) as error:
        result.update({"state": "invalid", "compatible": False, "reason": str(error)})
        return result

    result["structure"] = {
        "entry_count": len(entries),
        "expected_entry_count": config["expected_entry_count"],
        "uncompressed_entries": all(item.packed_size == item.unpacked_size for item in entries),
        "parsed_message_entries": message_entries,
        "translation_path": config["translation_path"],
    }
    if digest == config["known_original_sha256"]:
        result.update({"state": "known-original", "compatible": True})
    elif digest == config["known_patched_sha256"]:
        result.update({"state": "known-patched", "compatible": True})
    elif result["structure"]["uncompressed_entries"]:
        try:
            # Local import prevents the adapter/operation helper relationship
            # from becoming an import cycle while keeping detection read-only.
            from .operations import inspect_msg_payload_selectors

            selectors = inspect_msg_payload_selectors(path)
            result["payload_selector_check"] = selectors
            if selectors["safe_selector_match"]:
                result.update(
                    {
                        "state": "unknown-structural-candidate",
                        "compatible": False,
                        "reason": (
                            "Archive parses and all payload resources resolve uniquely by fingerprint, "
                            "but installation remains disabled until a compatible executable profile exists."
                        ),
                    }
                )
            else:
                result.update(
                    {
                        "state": "unsupported",
                        "compatible": False,
                        "reason": "Archive parses but required payload resources are missing or ambiguous.",
                    }
                )
        except Exception as error:
            result.update(
                {
                    "state": "unsupported",
                    "compatible": False,
                    "reason": f"Archive selector verification failed: {error}",
                }
            )
    else:
        result.update(
            {
                "state": "unsupported",
                "compatible": False,
                "reason": "Message archive structure is incompatible.",
            }
        )
    return result


def analyze_game(game_dir: Path, allow_exe_fallback: bool = False) -> dict[str, Any]:
    profile = load_profile()
    targets = profile["targets"]
    exe = inspect_executable(game_dir / targets["executable"]["path"], targets["executable"])
    msg = inspect_messages(game_dir / targets["messages"]["path"], targets["messages"])
    from .pictures import inspect_pic
    pic = inspect_pic(game_dir / targets['pictures']['path'], targets['pictures'])
    target_results = {"executable": exe, "messages": msg, "pictures": pic}
    states = {item["state"] for item in target_results.values()}
    if states == {"known-patched"}:
        overall = "already-installed"
        safe_to_patch = False
        operations_available = ["restore"]
    elif states <= {"known-original", "known-patched"}:
        overall = "known-supported"
        safe_to_patch = True
        operations_available = ["patch"]
    elif (allow_exe_fallback and exe.get('exists') and exe['state'] != 'missing'
          and all(item['state'] in {'known-original', 'known-patched'} for item in (msg, pic))):
        overall = 'supported-with-exe-fallback'
        safe_to_patch = True
        operations_available = ['patch']
    elif "missing" in states:
        overall = "target-missing"
        safe_to_patch = False
        operations_available = []
    elif "unknown-structural-candidate" in states:
        overall = "unknown-version-needs-profile"
        safe_to_patch = False
        operations_available = []
    else:
        overall = "unsupported-or-mixed-state"
        safe_to_patch = False
        operations_available = []
    return {
        "adapter": profile["game_id"],
        "profile_id": profile["profile_id"],
        "game_dir": str(game_dir),
        "overall_status": overall,
        "safe_to_patch": safe_to_patch,
        "operations_available": operations_available,
        "excluded_components": profile["excluded_components"],
        "targets": target_results,
    }


def installed_validation_targets() -> tuple[object, ...]:
    """Return post-install validators without placing game logic in core."""
    # Imported lazily because operations uses this adapter's PE/profile helpers.
    from core.validation import ExpectedTarget
    from .operations import validate_executable_candidate, validate_msg_arc_candidate

    profile = load_profile()
    targets = profile["targets"]
    from .pictures import validate_pic
    return (
        ExpectedTarget(targets['pictures']['path'], targets['pictures']['known_patched_sha256'], validate_pic),
        ExpectedTarget(
            targets["executable"]["path"],
            targets["executable"]["known_patched_sha256"],
            validate_executable_candidate,
        ),
        ExpectedTarget(
            targets["messages"]["path"],
            targets["messages"]["known_patched_sha256"],
            validate_msg_arc_candidate,
        ),
    )


def original_backup_targets() -> tuple[object, ...]:
    """Describe only the files this adapter owns and may restore."""
    from core.backup import BackupTarget

    profile = load_profile()
    targets = profile["targets"]
    return (
        BackupTarget(targets['pictures']['path'], targets['pictures']['known_original_sha256']),
        BackupTarget(targets["executable"]["path"], targets["executable"]["known_original_sha256"]),
        BackupTarget(targets["messages"]["path"], targets["messages"]["known_original_sha256"]),
    )


def backup_store_for(game_dir: Path, state_dir: Path | None = None) -> object:
    """Return the adapter-owned immutable backup location for this game folder."""
    from core.backup import BackupStore

    profile = load_profile()
    manifest = json.loads((INSTALLER_ROOT / "payload" / "manifest.json").read_text(encoding="utf-8"))
    mod = manifest["mod"]
    root = installer_state_root(game_dir, state_dir) / "backups" / str(mod["id"])
    return BackupStore(
        game_dir,
        root,
        game_id=profile["game_id"],
        mod_id=str(mod["id"]),
        mod_version=str(mod["version"]),
    )


def restore_backup_targets(game_dir: Path, state_dir: Path | None = None) -> tuple[object, ...]:
    """Restore the exact executable present before installation, including fallback installs."""
    from core.backup import BackupTarget
    store = backup_store_for(game_dir, state_dir)
    manifest = store.validate()
    hashes = {entry['relative_path']: entry['original_sha256'] for entry in manifest['files']}
    return tuple(BackupTarget(t.relative_path, hashes.get(t.relative_path, t.expected_original_sha256)
                             if t.relative_path == 'sh3.exe' else t.expected_original_sha256)
                 for t in original_backup_targets())


def fallback_executable() -> Path:
    from .operations import OperationError
    source = INSTALLER_ROOT / 'payload' / 'original_sh3.exe'
    config = load_profile()['targets']['executable']
    if not source.is_file() or sha256_file(source) != config['known_original_sha256']:
        raise OperationError('Bundled original sh3.exe is missing or corrupt')
    return source


def installer_state_root(game_dir: Path, state_dir: Path | None = None) -> Path:
    """Resolve the caller-selected state directory or use the legacy default."""
    if state_dir is not None:
        return state_dir.resolve()
    return game_dir / ".thai_mod_installer"


def prepare_patch_transaction(game_dir: Path, candidate_dir: Path, state_dir: Path | None = None,
                              allow_exe_fallback: bool = False) -> object:
    """Build only validated temporary candidates and stage them for core commit."""
    from core.transaction import PatchTransaction
    from .operations import (
        build_executable_candidate,
        build_msg_arc_candidate,
        validate_executable_candidate,
        validate_msg_arc_candidate,
        validate_payload_integrity,
    )

    profile = load_profile()
    targets = profile["targets"]
    validate_payload_integrity()
    candidate_dir.mkdir(parents=True, exist_ok=True)
    from .pictures import build_pic, validate_pic
    transaction = PatchTransaction(game_dir, backup_store_for(game_dir, state_dir))
    builders = {'executable': (build_executable_candidate, validate_executable_candidate),
                'messages': (build_msg_arc_candidate, validate_msg_arc_candidate),
                'pictures': (build_pic, validate_pic)}
    for key, (builder, validator) in builders.items():
        config = targets[key]
        source = game_dir / config['path']
        source_hash = sha256_file(source)
        if source_hash == config['known_patched_sha256']:
            continue
        candidate = candidate_dir / source.name
        use_fallback = key == 'executable' and allow_exe_fallback and source_hash != config['known_original_sha256']
        builder(fallback_executable() if use_fallback else source, candidate)
        transaction.stage(relative_path=config['path'], expected_original_sha256=source_hash if use_fallback else config['known_original_sha256'],
                          candidate=candidate, expected_patched_sha256=config['known_patched_sha256'], validator=validator)
    return transaction

def estimated_install_space(game_dir: Path) -> dict[str, int]:
    """Calculate required space from actual source/result sizes, not a multiplier."""
    profile = load_profile()
    manifest = json.loads((INSTALLER_ROOT / "payload" / "manifest.json").read_text(encoding="utf-8"))
    operations = {item["target"]: item for item in manifest["operations"]}
    executable = operations[profile["targets"]["executable"]["path"]]
    messages = operations[profile["targets"]["messages"]["path"]]
    original_bytes = sum((game_dir / item['target']).stat().st_size for item in operations.values())
    candidate_bytes = sum(int(item['result_size']) for item in operations.values())
    return {
        "temporary_candidate_bytes": candidate_bytes,
        "game_commit_and_backup_bytes": original_bytes + max(int(item['result_size']) for item in operations.values()),
    }


def write_installed_metadata(game_dir: Path, state_dir: Path | None = None) -> Path:
    """Record only verified installed state after the transaction succeeds."""
    state_root = installer_state_root(game_dir, state_dir)
    state_root.mkdir(parents=True, exist_ok=True)
    profile = load_profile()
    manifest = json.loads((INSTALLER_ROOT / "payload" / "manifest.json").read_text(encoding="utf-8"))
    metadata = {
        "schema_version": 1,
        "game_id": profile["game_id"],
        "profile_id": profile["profile_id"],
        "mod": manifest["mod"],
        "installed_targets": {
            "data/pic.arc": profile['targets']['pictures']['known_patched_sha256'],
            "sh3.exe": profile["targets"]["executable"]["known_patched_sha256"],
            "data/msg.arc": profile["targets"]["messages"]["known_patched_sha256"],
        },
        "excluded_components": profile["excluded_components"],
    }
    destination = state_root / "installed_mod.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def clear_installed_metadata(game_dir: Path, state_dir: Path | None = None) -> None:
    """Remove only state created by this installer after verified restore."""
    metadata = installer_state_root(game_dir, state_dir) / "installed_mod.json"
    metadata.unlink(missing_ok=True)


def cleanup_restored_install(game_dir: Path, state_dir: Path | None = None) -> list[str]:
    """Remove installer-owned state after the original game files were restored."""
    store = backup_store_for(game_dir, state_dir)
    state_root = installer_state_root(game_dir, state_dir)
    removed: list[str] = []
    # These names are derived from fixed game targets, never from manifest paths.
    for target in original_backup_targets():
        backup = store.files_dir / store._backup_name(target.relative_path)
        if backup.is_symlink():
            raise OSError(f"Refusing to clean symlink backup: {backup}")
        if backup.is_file():
            backup.unlink()
            removed.append(str(backup))
    for path in (store.manifest_path, state_root / 'installed_mod.json'):
        if path.is_symlink():
            raise OSError(f"Refusing to clean symlink state file: {path}")
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    logs = state_root / 'logs'
    if logs.is_dir() and not logs.is_symlink():
        for path in logs.iterdir():
            if path.is_file() and not path.is_symlink() and path.name.startswith('mod-installer-') and path.suffix == '.json':
                path.unlink()
                removed.append(str(path))
    for directory in (store.files_dir, store.root, state_root / 'backups', logs, state_root):
        if directory.is_dir() and not directory.is_symlink():
            try:
                directory.rmdir()
            except OSError:
                pass  # Preserve unrelated content in a caller-selected state directory.
    return removed
