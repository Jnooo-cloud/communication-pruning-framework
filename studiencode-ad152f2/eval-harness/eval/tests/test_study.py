"""Integrated execution fault boundary; every transport is invented."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from communication_pruning.data import canonical, digest
from communication_pruning.openrouter import encoded, save_new
from communication_pruning.study import StudyStop, StudyAdapter, run_spatial, file_hash
from communication_pruning.study_release import run_live
from communication_pruning.phase_budget import PhaseBudget, BudgetStop
from study_fixture import fixture, FakeTransport


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kw = fixture(self.root / "inputs")
        self.transport = FakeTransport()

    def run_study(self, **overrides):
        args = {**self.kw, "folder": self.root / "output", "control": self.root / "control",
                "transport": self.transport, "synthetic": True, "slot_limit": 14, **overrides}
        return run_spatial(**args)

    def report(self):
        return json.loads((self.root / "output/report.json").read_text())

    def test_full_bank_shared_budget_context_and_no_gold(self):
        report = self.run_study()
        self.assertEqual(report["completed_slots"], 14)
        self.assertEqual(self.transport.calls, 86)
        self.assertEqual(Decimal(report["budget"]["known_cost_usd"]), Decimal(".0000108") * 86)
        positions = 0
        for slot in self.kw["plan"]["slots"][:14]:
            bodies = self.transport.bodies[positions:positions + slot["planned_calls"]]
            roles = (slot["planned_calls"] - 1) // 2
            for body in bodies[:roles]:
                self.assertEqual(json.loads(body["messages"][1]["content"])["prior_messages"], [])
            for body in bodies:
                self.assertFalse(body["reasoning"]["enabled"])
                self.assertFalse(body["provider"]["allow_fallbacks"])
                self.assertEqual(body["max_tokens"], 128 if body is bodies[-1] else 1024)
                self.assertNotIn("PRIVATE_", json.dumps(body))
            positions += slot["planned_calls"]
        scores = list((self.root / "output/slots").glob("*-result.json"))
        self.assertEqual(len(scores), 14)
        self.assertTrue(all(json.loads(p.read_text())["synthetic_cost_calls"] in (5, 7) for p in scores))

    def test_known_rejected_answer_stops_phase_and_keeps_cost(self):
        self.transport = FakeTransport(fail_at=8, mode="length")
        with self.assertRaises(BudgetStop): self.run_study()
        self.assertEqual(self.transport.calls, 8)
        self.assertEqual(Decimal(self.report()["budget"]["known_cost_usd"]), Decimal(".0000108") * 8)
        self.assertTrue(self.report()["budget"]["poisoned"])
        self.assertLess(self.report()["completed_slots"], 2)

    def test_unknown_and_duplicate_keep_reserve_and_stop(self):
        for mode in ["unknown", "duplicate", "transport"]:
            with self.subTest(mode=mode):
                t = FakeTransport(fail_at=2, mode=mode)
                output = self.root / mode
                with self.assertRaises(BudgetStop):
                    self.run_study(transport=t, folder=output, control=self.root / f"control-{mode}")
                r = json.loads((output / "report.json").read_text())["budget"]
                self.assertEqual(t.calls, 2)
                self.assertIsNone(r["total_cost_usd"])
                self.assertEqual(r["held_reservation_usd"], "0.14")
                self.assertEqual(Decimal(r["known_cost_usd"]), Decimal(".0000108"))

    def test_http_failure_with_valid_cost_is_preserved(self):
        self.transport = FakeTransport(fail_at=1, mode="http")
        with self.assertRaises(BudgetStop): self.run_study()
        self.assertEqual(self.transport.calls, 1)
        self.assertEqual(Decimal(self.report()["budget"]["known_cost_usd"]), Decimal(".0000108"))

    def test_interruption_retains_claim_and_open_reservation(self):
        self.transport = FakeTransport(fail_at=1, mode="interrupt")
        with self.assertRaises(KeyboardInterrupt): self.run_study()
        self.assertIsNone(self.report()["budget"]["total_cost_usd"])
        with self.assertRaises(FileExistsError): self.run_study(folder=self.root / "another")
        self.assertEqual(self.transport.calls, 1)

    def test_resigned_wrong_panel_and_changed_bound_files_rejected(self):
        changed = deepcopy(self.kw["plan"])
        changed["slots"][0]["task_id"] = "2hop__1000_100300"  # reserved family member, not selected
        changed["sha256"] = digest({k: v for k, v in changed.items() if k != "sha256"})
        with self.assertRaises(ValueError): self.run_study(plan=changed)
        for name in ["plan.json", "manifest.json", "exposure.json"]:
            path = self.root / "inputs" / name
            old = path.read_bytes()
            path.write_bytes(old + b" ")
            with self.assertRaises(StudyStop): self.run_study()
            path.write_bytes(old)
        self.assertEqual(self.transport.calls, 0)

    def test_changed_source_between_slots_stops_before_next_slot(self):
        calls = 0
        original = self.kw["guard"]
        first_count = self.kw["plan"]["slots"][0]["planned_calls"]
        def guard():
            nonlocal calls
            calls += 1
            if calls == 3:
                path = self.root / "inputs/exposure.json"
                path.write_text('["new exposure"]')
            original()
        with self.assertRaises(StudyStop): self.run_study(guard=guard)
        self.assertEqual(self.transport.calls, first_count)

    def test_wrong_public_identity_never_sent(self):
        from communication_pruning.data import load_task
        def wrong(*a, **kw):
            task, ref = load_task(*a, **kw)
            return replace(task, task_id="wrong"), ref
        with patch("communication_pruning.study.load_task", side_effect=wrong):
            with self.assertRaises(StudyStop): self.run_study()
        self.assertEqual(self.transport.calls, 0)

    def test_durable_billing_write_failure_keeps_cost_unknown(self):
        original = save_new
        def fail(path, data):
            if str(path).endswith("-billing.json"):
                raise OSError("invented full disk")
            original(path, data)
        with patch("communication_pruning.study.save_new", side_effect=fail):
            with self.assertRaises(BudgetStop): self.run_study()
        self.assertEqual(self.transport.calls, 1)
        self.assertIsNone(self.report()["budget"]["total_cost_usd"])
        self.assertTrue((self.root / "output/provider/00001-response.json").exists())

    def test_reservation_fsync_failure_prevents_transport(self):
        import communication_pruning.phase_budget as module
        original = module.PhaseBudget._append
        def fail(budget, data):
            if data["kind"] == "reserved":
                budget.poisoned = True
                raise OSError("invented journal error")
            original(budget, data)
        with patch.object(module.PhaseBudget, "_append", fail):
            with self.assertRaises(OSError): self.run_study()
        self.assertEqual(self.transport.calls, 0)

    def test_budget_exhaustion_across_slots_no_next_transport(self):
        # Force cap only in injected test budget; keep the plan unchanged.
        original = PhaseBudget
        first_count = self.kw["plan"]["slots"][0]["planned_calls"]
        def tiny(path, **kw):
            kw.update(cap=Decimal(".14") + Decimal(".0000108") * first_count)
            return original(path, **kw)
        with patch("communication_pruning.study.PhaseBudget", side_effect=tiny):
            with self.assertRaises(BudgetStop): self.run_study()
        self.assertEqual(self.transport.calls, first_count + 1)

    def test_live_gate_precedes_credentials_contents_and_client(self):
        path = self.root / "release.json"
        path.write_text('{"status":"prepared_not_authorized"}')
        with patch("communication_pruning.study_release.load_key") as key, patch("communication_pruning.study_release.Transport") as client:
            with self.assertRaises(StudyStop): run_live(self.root, path, self.root / "live")
            key.assert_not_called()
            client.assert_not_called()

    def test_catalog_change_prevents_model_requests(self):
        def changed(endpoint, body=None):
            status, raw = self.transport(endpoint, body)
            obj = json.loads(raw)
            obj["data"]["endpoints"][0]["pricing"]["prompt"] = "0.1"
            return status, encoded(obj)
        with self.assertRaises(RuntimeError): self.run_study(transport=changed)
        self.assertEqual(self.transport.calls, 0)
