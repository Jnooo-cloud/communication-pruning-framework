"""Bounded tests of the real Z42 entry boundary; no provider or benchmark use."""
import importlib.util
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch


ENTRY = Path(__file__).resolve().parents[1] / "runs/Z42-PILOT-001/operate.py"


def module():
    spec = importlib.util.spec_from_file_location("z42_entry_test", ENTRY)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class PilotLiveBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.op = module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        pack = root / "eval-harness/eval/runs/Z42-PILOT-001"
        self.patches = patch.multiple(self.op, ROOT=root, EXPECTED_ROOT=root, PACK=pack,
            PREP=pack / "calendar-r2/preparation", LIVE=pack / "live", CONTROL=pack / "control")
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.op.PREP.mkdir(parents=True)

    def test_missing_acceptance_stops_before_any_bound_source(self):
        with patch.object(self.op, "checked_files", side_effect=AssertionError("too late")) as guard:
            with self.assertRaises(FileNotFoundError):
                self.op.guard_start()
            guard.assert_not_called()

    def test_calendar_revision_cannot_prepare_after_any_live_start(self):
        markers = (self.op.LIVE / "marker", self.op.CONTROL / "marker",
                   self.op.PACK / "window-evidence/W01-first-pair/CALL.json")
        for marker in markers:
            with self.subTest(marker=marker):
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("preserved live evidence")
                with patch.object(self.op, "fixed_inputs", side_effect=AssertionError("too late")) as inputs:
                    with self.assertRaisesRegex(RuntimeError, "unexposed, unstarted"):
                        self.op.prepare()
                    inputs.assert_not_called()
                marker.unlink()
                marker.parent.rmdir()

    def test_approval_word_without_actual_P4_is_not_accepted(self):
        self.op.save(self.op.PACK / "calendar-r2/START-ACCEPTANCE.json", {"status": "authorized_by_author", "author_decision": "D-059"})
        with self.assertRaisesRegex(RuntimeError, "P1-P4"):
            self.op.guard_start()

    def test_changed_phase_cap_stops_before_source_or_runtime_reads(self):
        contract = {"schema": "z42-live-contract/v1", "phase_id": "Z42-PILOT-001", "author_decision": "D-059",
            "plan_sha256": self.op.PLAN_SHA, "folder": self.op.rel(self.op.LIVE),
            "control": self.op.rel(self.op.CONTROL), "cap_usd": "40.00", "reserve_usd": "0.14",
            "max_calls": 4320, "retry_policy": "none"}
        self.op.save(self.op.PREP / "contract.json", contract)
        self.op.save(self.op.PACK / "calendar-r2/START-ACCEPTANCE.json", {"status": "passed_P1_P4", "author_decision": "D-059",
            "contract_sha256": self.op.file_hash(self.op.PREP / "contract.json"), "evidence": []})
        with patch.object(self.op, "checked_files", side_effect=AssertionError("too late")) as guard:
            with self.assertRaisesRegex(RuntimeError, "fixed phase"):
                self.op.guard_start()
            guard.assert_not_called()

    def test_directory_copy_cannot_create_a_new_budget_phase(self):
        with patch.object(self.op, "PACK", self.op.PACK.with_name("Z42-copy")):
            with self.assertRaisesRegex(RuntimeError, "fixed pilot directory"):
                self.op.guard_start()

    def test_structurally_identical_project_copy_cannot_reset_budget(self):
        other = self.op.ROOT / "another-project"
        with patch.multiple(self.op, ROOT=other, PACK=other / "eval-harness/eval/runs/Z42-PILOT-001"):
            with self.assertRaisesRegex(RuntimeError, "fixed pilot directory"):
                self.op.guard_start()

    def test_missing_external_checkpoint_is_not_resume_approval(self):
        p = self.op.LIVE / "checkpoints"
        p.mkdir(parents=True)
        self.op.save(p / "W01-first-pair.json", {"stage": "W01-first-pair", "receipt": {"sha256": "0" * 64}})
        with self.assertRaises(FileNotFoundError):
            self.op.verify_completed_holds()

    def test_stopped_phase_is_not_resumed(self):
        self.op.LIVE.mkdir()
        self.op.save(self.op.LIVE / "halted.json", {"reason": "unknown cost"})
        with self.assertRaisesRegex(RuntimeError, "hard stop"):
                self.op.verify_completed_holds()

    def test_unresolved_outer_call_cannot_be_bypassed_before_live_folder_exists(self):
        self.op.save(self.op.PACK / "window-evidence/W01-first-pair/CALL.json", {"window": "W01"})
        self.assertFalse(self.op.LIVE.exists())
        with self.assertRaisesRegex(RuntimeError, "unresolved outer"):
            self.op.verify_completed_holds()

    def test_not_due_run_stops_before_runtime_keys_or_content(self):
        from datetime import datetime, timezone
        future = {"window_id": "W01", "start_utc": "2099-01-01T00:00:00+00:00",
                  "pair_start_before_utc": "2099-01-01T03:15:00+00:00", "end_utc": "2099-01-01T03:45:00+00:00"}
        plan = {"windows": [future], "task_ids": ["synthetic"]}
        def read(path):
            return plan if path.name == "calendar.json" else {}
        with patch.object(self.op, "guard_start", return_value=({"bindings": {}}, {})), \
             patch.object(self.op, "verify_completed_holds"), patch.object(self.op, "read", side_effect=read), \
             patch.object(self.op, "validate_calendar"), patch.object(self.op, "catalog", side_effect=AssertionError("network")), \
             patch("communication_pruning.openrouter.load_key", side_effect=AssertionError("credential")), \
             patch("communication_pruning.data.load_task", side_effect=AssertionError("content")), \
             patch("communication_pruning.semantic_selection.FrozenMiniLM", side_effect=AssertionError("encoder")):
            with self.assertRaisesRegex(ValueError, "pair-start"):
                self.op.run("W01")
        self.assertFalse((self.op.PACK / "window-evidence").exists())


if __name__ == "__main__":
    unittest.main()
