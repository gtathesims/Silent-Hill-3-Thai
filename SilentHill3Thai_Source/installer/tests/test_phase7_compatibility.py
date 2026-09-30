from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from games.silent_hill_3.adapter import inspect_messages, load_profile
from games.silent_hill_3.operations import inspect_msg_payload_selectors
from sh3_msg_common import archive_entries, entry_payload, rebuild_archive


WORKSPACE = Path(__file__).resolve().parents[2]
BASELINE_MSG = WORKSPACE / "baseline" / "original" / "data" / "msg.arc"


class Phase7CompatibilityTests(unittest.TestCase):
    def test_payload_targets_are_uniquely_resolved_by_resource_fingerprint(self) -> None:
        result = inspect_msg_payload_selectors(BASELINE_MSG)
        self.assertTrue(result["safe_selector_match"])
        self.assertEqual(result["required_targets"], 135)
        self.assertEqual(result["resolved_targets"], 135)

    def test_unknown_archive_hash_with_unchanged_targets_is_structural_candidate(self) -> None:
        data = BASELINE_MSG.read_bytes()
        entries = archive_entries(data)
        payloads = [entry_payload(data, entry) for entry in entries]
        # Change an untouched message resource only; all payload identities
        # remain intact while the complete archive hash becomes unknown.
        selected = {item["payload_index"] for item in inspect_msg_payload_selectors(BASELINE_MSG)["resolved_indices"]}
        untouched_index = next(index for index in range(len(payloads)) if index not in selected)
        altered = bytearray(payloads[untouched_index])
        altered[-1] ^= 0x01
        payloads[untouched_index] = bytes(altered)
        with tempfile.TemporaryDirectory() as temporary:
            variant = Path(temporary) / "msg.arc"
            variant.write_bytes(rebuild_archive(data, payloads))
            report = inspect_messages(variant, load_profile()["targets"]["messages"])
            self.assertEqual(report["state"], "unknown-structural-candidate")
            self.assertTrue(report["payload_selector_check"]["safe_selector_match"])

    def test_changed_target_resource_is_not_accepted_as_structurally_compatible(self) -> None:
        data = BASELINE_MSG.read_bytes()
        entries = archive_entries(data)
        payloads = [entry_payload(data, entry) for entry in entries]
        selected_index = inspect_msg_payload_selectors(BASELINE_MSG)["resolved_indices"][0]["resolved_index"]
        altered = bytearray(payloads[selected_index])
        altered[-1] ^= 0x01
        payloads[selected_index] = bytes(altered)
        with tempfile.TemporaryDirectory() as temporary:
            variant = Path(temporary) / "msg.arc"
            variant.write_bytes(rebuild_archive(data, payloads))
            selector_report = inspect_msg_payload_selectors(variant)
            self.assertFalse(selector_report["safe_selector_match"])
            self.assertEqual(len(selector_report["missing_payload_indices"]), 1)
