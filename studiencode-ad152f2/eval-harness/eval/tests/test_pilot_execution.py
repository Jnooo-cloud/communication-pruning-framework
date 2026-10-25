"""P2/P3: no real inputs, encoders, keys, or provider calls."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import json
import tempfile
import unittest

from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference, digest
from communication_pruning.pilot_calendar import make_calendar, window_interval
from communication_pruning.pilot_execution import (PilotStop, run_window, inspect_pilot,
    pilot_lock, read_observations)
from communication_pruning.phase_budget import BudgetStop
from tests.test_pilot_calendar import fixture
from tests.study_fixture import FakeTransport


class PilotExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest, self.ids, self.bindings = fixture()
        self.plan = make_calendar(self.manifest, self.ids, bindings=self.bindings)
        self.now = window_interval(self.plan["windows"][0])[0]
        self.transport = FakeTransport()
        self.guards, self.loaded, self.selected, self.checkpoints = 0, [], [], []
        self.q = "C01"

    def loader(self, task_id):
        self.loaded.append(task_id)
        public_id = "task-" + digest([self.manifest["source_hashes"]["train"], task_id])
        return TaskInput(public_id, "Invented public question?", ("Invented public passage.",)), AnswerReference(public_id, ("PRIVATE_GOLD",))

    def selector(self, task):
        self.assertIsInstance(task, TaskInput)
        self.assertFalse(hasattr(task, "family_id"))
        self.assertFalse(hasattr(task, "hop"))
        self.selected.append(task)
        return self.q

    def guard(self):
        self.guards += 1

    def checkpoint(self, stage, state):
        self.checkpoints.append((stage, state))
        self.assertEqual(len(state["observations"]), 720)
        self.assertFalse(state["budget"]["poisoned"])
        return {"verified": True, "sha256": digest(state)}

    def run_case(self, **changes):
        args = dict(bindings=self.bindings, window_id="W01", folder=self.root / "output", control=self.root / "control",
                    loader=self.loader, selector=self.selector, transport=self.transport, guard=self.guard,
                    checkpoint=self.checkpoint, clock=lambda: self.now, synthetic=True, stop_after_first_pair=True)
        args.update(changes)
        return run_window(self.plan, self.manifest, self.ids, **args)

    def inspect(self):
        return inspect_pilot(self.plan, self.manifest, self.ids, bindings=self.bindings,
                             folder=self.root / "output", control=self.root / "control", synthetic=True)

    def test_equal_configurations_are_two_fresh_paid_arms(self):
        report = self.run_case()
        self.assertEqual(report["status"], "paused_first_pair")
        self.assertEqual((self.transport.calls, len(self.loaded), len(self.selected)), (10, 1, 1))
        self.assertGreaterEqual(self.guards, 14)
        state = self.inspect()
        self.assertEqual((state["completed_pairs"], state["budget"]["calls"]), (1, 10))
        self.assertEqual(len(state["generations"]), 10)
        self.assertEqual([x[0] for x in self.checkpoints], ["W01-first-pair"])
        for sid in self.plan["pairs"][0]["slot_ids"]:
            header = json.loads((self.root / "output" / "slots" / f"{sid}.jsonl").read_text().splitlines()[0])
            self.assertNotIn("PRIVATE_GOLD", json.dumps(header))
            result = json.loads((self.root / "output" / "slots" / f"{sid}-result.json").read_text())
            self.assertEqual(result["execution_finished_utc"], self.now.isoformat())
            self.assertEqual(result["scoring_finished_utc"], self.now.isoformat())
        first_a, first_b = self.transport.bodies[0], self.transport.bodies[5]
        self.assertEqual(first_a, first_b)
        self.assertNotIn("PRIVATE_GOLD", json.dumps(self.transport.bodies))
        rows = read_observations(self.plan, self.root / "output")
        self.assertEqual([r["status"] for r in rows[:3]], ["complete", "complete", "not_started"])
        self.assertTrue(all(r["selection_seconds"] >= 0 for r in rows[:2]))

    def test_raw_selection_has_no_fixed_fallback_and_seven_call_limit(self):
        self.q = "C14"
        self.run_case()
        self.assertEqual(self.transport.calls, 12)
        rows = read_observations(self.plan, self.root / "output")[:2]
        self.assertEqual({r["arm"]: r["configuration"] for r in rows}, {"Q": "C14", "F*": "C01"})

    def test_first_pair_resume_and_next_window_preserve_budget_and_generations(self):
        self.run_case()
        self.run_case(stop_after_first_pair=False)
        self.assertEqual((self.inspect()["completed_pairs"], self.transport.calls), (30, 300))
        self.now = window_interval(self.plan["windows"][1])[0]
        self.run_case(window_id="W02", stop_after_first_pair=False)
        state = self.inspect()
        self.assertEqual((state["completed_pairs"], state["budget"]["calls"]), (60, 600))
        self.assertEqual(Decimal(state["budget"]["known_cost_usd"]), Decimal("0.0000108") * 600)

    def test_unknown_cost_stops_one_attempt_and_keeps_reserve_without_retry(self):
        self.transport = FakeTransport(fail_at=2, mode="unknown")
        with self.assertRaises(BudgetStop):
            self.run_case()
        self.assertEqual(self.transport.calls, 2)
        halted = json.loads((self.root / "output" / "halted.json").read_text())
        self.assertEqual(halted["budget"]["held_reservation_usd"], "0.14")
        rows = read_observations(self.plan, self.root / "output")
        self.assertEqual(rows[0]["status"], "partial")
        self.assertIsNone(rows[0]["em"])
        self.assertEqual(rows[0]["reserved_cost_usd"], "0.14")
        with self.assertRaises(PilotStop):
            self.run_case(stop_after_first_pair=False)
        self.assertEqual(self.transport.calls, 2)

    def test_f01_is_terminal_zero_and_known_failed_costs_are_included(self):
        self.transport = FakeTransport(fail_at=1, mode="length")
        self.run_case()
        rows = read_observations(self.plan, self.root / "output")
        self.assertEqual((rows[0]["status"], rows[0]["em"], rows[0]["f1"]), ("F01", 0, 0))
        self.assertEqual(rows[0]["known_cost_usd"], "0.0000108")
        self.assertEqual(self.inspect()["budget"]["calls"], 6)

    def test_guard_change_between_calls_stops_before_next_transport(self):
        def changed():
            if self.transport.calls >= 1:
                raise PilotStop("changed rule/source/tariff binding")
        with self.assertRaises(PilotStop):
            self.run_case(guard=changed)
        self.assertEqual(self.transport.calls, 1)

    def test_early_late_wrong_window_and_duplicate_claim(self):
        start, cutoff, _ = window_interval(self.plan["windows"][0])
        for value in (start - timedelta(seconds=1), cutoff):
            self.now = value
            with self.assertRaises(ValueError):
                self.run_case()
        self.now = start
        with self.assertRaises(ValueError):
            self.run_case(window_id="W02", stop_after_first_pair=False)
        self.assertEqual(self.transport.calls, 0)
        self.run_case()
        with self.assertRaises(PilotStop):
            self.run_case(folder=self.root / "renamed", stop_after_first_pair=False)
        self.assertEqual(self.transport.calls, 10)

    def test_lock_and_changed_saved_evidence_block(self):
        with pilot_lock(self.root / "control"):
            with self.assertRaises(PilotStop):
                self.run_case()
        self.run_case()
        path = self.root / "output" / "provider" / "00001-response.json"
        path.write_bytes(b"{}")
        with self.assertRaises(PilotStop):
            self.run_case(stop_after_first_pair=False)
        self.assertEqual(self.transport.calls, 10)

    def test_cutoff_keeps_begun_pair_but_never_starts_a_second(self):
        start, cutoff, end = window_interval(self.plan["windows"][0])
        self.now = cutoff - timedelta(seconds=1)
        def selected(task):
            self.now = cutoff + timedelta(seconds=1)
            return "C01"
        with self.assertRaises(ValueError):
            self.run_case(selector=selected, stop_after_first_pair=False)
        self.assertEqual(self.transport.calls, 10)
        self.assertTrue((self.root / "output" / "pairs" / "P0001-complete.json").exists())
        self.assertFalse((self.root / "output" / "pairs" / "P0002-started.json").exists())

    def test_overrun_stops_after_preserving_complete_pair(self):
        _, _, end = window_interval(self.plan["windows"][0])
        def selected(task):
            self.now = end + timedelta(seconds=1)
            return "C01"
        with self.assertRaisesRegex(PilotStop, "exceeded"):
            self.run_case(selector=selected)
        self.assertEqual(self.transport.calls, 10)

    def test_budget_includes_costs_and_reserve_cumulatively(self):
        base = FakeTransport()
        def expensive(endpoint, body=None):
            status, raw = base(endpoint, body)
            value = json.loads(raw)
            value["usage"]["cost"] = "0.14"
            return status, json.dumps(value).encode()
        with self.assertRaises(BudgetStop):
            self.run_case(transport=expensive, stop_after_first_pair=False)
        self.assertEqual(base.calls, 28)
        halted = json.loads((self.root / "output" / "halted.json").read_text())
        self.assertEqual(Decimal(halted["budget"]["known_cost_usd"]), Decimal("3.92"))

    def test_incorrect_loader_identity_stops_before_sending(self):
        def wrong(_):
            return TaskInput("foreign", "invented", ()), AnswerReference("foreign", ("secret",))
        with self.assertRaises(PilotStop):
            self.run_case(loader=wrong)
        self.assertEqual(self.transport.calls, 0)


if __name__ == "__main__":
    unittest.main()
