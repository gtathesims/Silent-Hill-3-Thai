"""Known-baseline, temp-file patch operations for Silent Hill 3.

The operations never write a game target.  They produce candidates for the
generic transaction core, which is the only layer allowed to commit a result.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

from .adapter import at_va, load_profile, parse_pe, sha256_file, va_to_offset

from .adapter import INSTALLER_ROOT, TOOLS
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sh3_msg_common import archive_entries, entry_payload, rebuild_archive  # noqa: E402


class OperationError(RuntimeError):
    """A known-baseline patch operation cannot produce a validated candidate."""


PAYLOAD_ROOT = INSTALLER_ROOT / "payload"
MSG_PAYLOAD = PAYLOAD_ROOT / "silent_hill_3_msg_arc_phase41.json"
PAYLOAD_MANIFEST = PAYLOAD_ROOT / "manifest.json"


def validate_payload_integrity() -> dict[str, Any]:
    """Validate the bundled payload manifest before any payload is consumed."""
    try:
        manifest = json.loads(PAYLOAD_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OperationError(f"Cannot load payload manifest: {error}") from error
    if manifest.get("format_version") != 1:
        raise OperationError("Unsupported payload manifest version")
    operations = manifest.get("operations")
    if not isinstance(operations, list):
        raise OperationError("Payload manifest has no operations")
    message_operation = next((item for item in operations if item.get("target") == "data/msg.arc"), None)
    if not isinstance(message_operation, dict) or not isinstance(message_operation.get("payload"), dict):
        raise OperationError("Payload manifest has no msg.arc payload declaration")
    declaration = message_operation["payload"]
    if declaration.get("path") != MSG_PAYLOAD.name:
        raise OperationError("Payload manifest points to an unexpected msg.arc payload")
    actual_hash = sha256_file(MSG_PAYLOAD)
    if actual_hash != declaration.get("sha256"):
        raise OperationError("msg.arc payload hash does not match payload manifest")
    from .pictures import payload
    try:
        payload()
    except (ValueError, OSError) as error:
        raise OperationError(str(error)) from error
    return manifest


def _load_msg_payload() -> dict[str, Any]:
    manifest = validate_payload_integrity()
    try:
        payload = json.loads(MSG_PAYLOAD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OperationError(f"Cannot load msg.arc payload: {error}") from error
    if payload.get("schema_version") != 1 or payload.get("method") != "replace-entry-payloads-zlib":
        raise OperationError("Unsupported msg.arc payload schema")
    declared = next(item for item in manifest["operations"] if item.get("target") == "data/msg.arc")
    if payload.get("source_sha256") != declared.get("source_sha256") or payload.get("patched_sha256") != declared.get("result_sha256"):
        raise OperationError("msg.arc payload hashes do not agree with payload manifest")
    return payload


def inspect_msg_payload_selectors(source: Path) -> dict[str, Any]:
    """Resolve translation targets by unique source-resource fingerprint.

    This is deliberately read-only.  It proves whether a structurally similar
    archive contains the exact logical resources required by the payload,
    without treating archive index or total file hash as the resource identity.
    """
    payload = _load_msg_payload()
    data = source.read_bytes()
    entries = archive_entries(data)
    by_hash: dict[str, list[int]] = {}
    for entry in entries:
        digest = hashlib.sha256(entry_payload(data, entry)).hexdigest().upper()
        by_hash.setdefault(digest, []).append(entry.index)

    resolved: list[dict[str, int]] = []
    missing: list[int] = []
    ambiguous: list[dict[str, Any]] = []
    for item in payload["entries"]:
        payload_index = int(item["index"])
        matches = by_hash.get(str(item["source_payload_sha256"]), [])
        if len(matches) == 1:
            resolved.append({"payload_index": payload_index, "resolved_index": matches[0]})
        elif not matches:
            missing.append(payload_index)
        else:
            ambiguous.append({"payload_index": payload_index, "matching_indices": matches})
    return {
        "method": "unique-source-payload-sha256",
        "archive_entry_count": len(entries),
        "required_targets": len(payload["entries"]),
        "resolved_targets": len(resolved),
        "resolved_indices": resolved,
        "missing_payload_indices": missing,
        "ambiguous_payload_indices": ambiguous,
        "safe_selector_match": not missing and not ambiguous and len(resolved) == len(payload["entries"]),
    }


def build_msg_arc_candidate(source: Path, output: Path) -> dict[str, Any]:
    payload = _load_msg_payload()
    source_hash = sha256_file(source)
    if source_hash != payload.get("source_sha256"):
        raise OperationError("msg.arc source is not the approved original baseline")
    data = source.read_bytes()
    entries = archive_entries(data)
    replacements = payload.get("entries")
    if not isinstance(replacements, list) or not replacements:
        raise OperationError("msg.arc payload has no entry replacements")
    entry_payloads = [entry_payload(data, entry) for entry in entries]
    seen: set[int] = set()
    for item in replacements:
        try:
            index = int(item["index"])
            expected_hash = str(item["source_payload_sha256"])
            final_hash = str(item["patched_payload_sha256"])
            encoded = str(item["zlib_base64"])
            final_size = int(item["patched_size"])
        except (KeyError, TypeError, ValueError) as error:
            raise OperationError(f"Invalid msg.arc payload entry: {error}") from error
        if index in seen or not 0 <= index < len(entries):
            raise OperationError(f"Ambiguous or invalid msg.arc entry: {index}")
        seen.add(index)
        original = entry_payloads[index]
        if hashlib.sha256(original).hexdigest().upper() != expected_hash:
            raise OperationError(f"msg.arc target fingerprint mismatch at entry {index}")
        try:
            patched = zlib.decompress(base64.b64decode(encoded, validate=True))
        except (ValueError, zlib.error) as error:
            raise OperationError(f"Corrupt compressed msg.arc payload at entry {index}: {error}") from error
        if len(patched) != final_size or hashlib.sha256(patched).hexdigest().upper() != final_hash:
            raise OperationError(f"msg.arc payload integrity failure at entry {index}")
        entry_payloads[index] = patched
    rebuilt = rebuild_archive(data, entry_payloads)
    actual_hash = hashlib.sha256(rebuilt).hexdigest().upper()
    if actual_hash != payload.get("patched_sha256"):
        raise OperationError("Rebuilt msg.arc does not match the approved final hash")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rebuilt)
    return {
        "target": "data/msg.arc",
        "source_sha256": source_hash,
        "patched_sha256": actual_hash,
        "changed_entries": len(seen),
        "payload_sha256": sha256_file(MSG_PAYLOAD),
    }


def validate_msg_arc_candidate(path: Path) -> None:
    payload = _load_msg_payload()
    if sha256_file(path) != payload.get("patched_sha256"):
        raise OperationError("msg.arc candidate hash does not match payload manifest")
    data = path.read_bytes()
    entries = archive_entries(data)
    if len(entries) != int(payload.get("expected_entry_count", 0)):
        raise OperationError("msg.arc candidate entry count changed")
    # Confirm every message table remains parseable after archive rebuild.
    profile = load_profile()
    from sh3_msg_common import parse_message_table  # local to retain the small operation dependency surface

    for entry in entries:
        if entry.index not in profile["targets"]["messages"]["font_entry_indices"]:
            parse_message_table(entry_payload(data, entry))


def build_executable_candidate(source: Path, output: Path) -> dict[str, Any]:
    profile = load_profile()
    config = profile["targets"]["executable"]
    source_hash = sha256_file(source)
    if source_hash != config["known_original_sha256"]:
        raise OperationError("sh3.exe source is not the approved original baseline")
    data = source.read_bytes()
    pe = parse_pe(data)
    expected_pe = config["pe"]
    if (
        f"{pe['machine']:04X}" != expected_pe["machine"]
        or f"{pe['optional_magic']:04X}" != expected_pe["optional_magic"]
        or f"{pe['image_base']:08X}" != expected_pe["image_base"]
    ):
        raise OperationError("sh3.exe PE structure does not match profile")
    patch = config["patch_signatures"]
    candidate = bytearray(data)
    changed: set[int] = set()
    for key in ("font_metrics", "raster_lookup", "metrics_copy"):
        va = patch[key + "_va"]
        original = bytes.fromhex(patch[key + "_original"])
        replacement = bytes.fromhex(patch[key + "_patched"])
        offset = va_to_offset(pe, int(va, 16))
        if data[offset : offset + len(original)] != original:
            raise OperationError(f"sh3.exe original patch context mismatch: {key}")
        candidate[offset : offset + len(replacement)] = replacement
        changed.update(range(offset, offset + len(replacement)))
    actual_hash = hashlib.sha256(candidate).hexdigest().upper()
    if actual_hash != config["known_patched_sha256"]:
        raise OperationError("sh3.exe candidate hash does not match profile")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(candidate)
    return {
        "target": "sh3.exe",
        "source_sha256": source_hash,
        "patched_sha256": actual_hash,
        "changed_byte_count": len(changed),
        "profile": profile["profile_id"],
    }


def validate_executable_candidate(path: Path) -> None:
    profile = load_profile()
    config = profile["targets"]["executable"]
    if sha256_file(path) != config["known_patched_sha256"]:
        raise OperationError("sh3.exe candidate hash does not match profile")
    data = path.read_bytes()
    pe = parse_pe(data)
    patch = config["patch_signatures"]
    for key in ("font_metrics", "raster_lookup", "metrics_copy"):
        expected = bytes.fromhex(patch[key + "_patched"])
        if at_va(data, pe, patch[key + "_va"], len(expected)) != expected:
            raise OperationError(f"sh3.exe patched context mismatch: {key}")
