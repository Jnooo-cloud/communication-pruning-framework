"""Pre-outcome schedule and costly/uncertain side-effect boundary tests."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from communication_pruning.contracts import AdapterError, Response, Usage, TaskInput
from communication_pruning.data import TaskMeta, families, make_manifest, digest
from communication_pruning.phase_budget import BudgetStop, PhaseBudget
from communication_pruning.selection import Observation, family_folds, family_partition
from communication_pruning.spatial_plan import make_plan, validate_plan, save_plan, CV_SEED


def fixture():
    rows = [TaskMeta(f"fake-{i:03}", "train", 2 + i % 3, (f"family-{i // 3}",)) for i in range(300)]
    rows += [TaskMeta("unselected-relative", "train", 2, ("family-0",)),
             TaskMeta("foreign-pilot", "train", 2, ("foreign-pilot",))]
    mapping = families(rows)
    manifest = make_manifest(rows, exposed_ids=[], assignments={f: "spatial" if t != "foreign-pilot" else "pilot" for t, f in mapping.items()},
                             seed="fake-meta", source_hashes={"train": "a" * 64})
    ids = [r.task_id for r in rows[:300]]
    return manifest, ids, ids[:50], {"allocation": "b" * 64, "repetition": "c" * 64, "source": "d" * 64}


class SpatialPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.ids, cls.repeats, cls.bindings = fixture()
        cls.plan = make_plan(cls.m, cls.ids, cls.repeats, bindings=cls.bindings)

    def test_complete_configuration_plan_and_position_balance(self):
        slots = self.plan["slots"]
        self.assertEqual(len({s["slot_id"] for s in slots}), 4900)
        self.assertEqual(sum(s["planned_calls"] for s in slots), 30100)
        actual = Counter((s["task_id"], s["config_id"], s["repeat"]) for s in slots)
        expected = Counter({(t, f"C{c:02}", rep): 1 for rep, ids in ((1, self.ids), (2, self.repeats)) for t in ids for c in range(1, 15)})
        self.assertEqual(actual, expected)
        for rep, count in ((1, 300), (2, 50)):
            for block in range(1, count // 14 + 1):
                rows = [s for s in slots if s["repeat"] == rep and s["block"] == block]
                self.assertEqual(Counter((s["config_id"], s["position"]) for s in rows),
                                 Counter({(f"C{c:02}", pos): 1 for c in range(1, 15) for pos in range(1, 15)}))

    def test_folds_and_nested_whole_family_learning_curves(self):
        lookup = {e["task_id"]: e["family_id"] for e in self.m["entries"]}
        previous = set()
        for point in self.plan["learning_curves"]:
            ids = set(point["task_ids"])
            self.assertTrue(previous <= ids <= set(self.ids))
            self.assertTrue(point["target"] <= len(ids) <= min(300, point["target"] + 4))
            selected_families = {lookup[t] for t in ids}
            self.assertTrue(all(t in ids for t in self.ids if lookup[t] in selected_families))
            held_families = []
            self.assertEqual(Counter(t for fold in point["folds"] for t in fold), Counter(ids))
            for fold in point["folds"]:
                fams = {lookup[t] for t in fold}
                self.assertTrue(all(not fams & old for old in held_families))
                held_families.append(fams)
            previous = ids
        self.assertEqual([len(f) for f in self.plan["folds"]], [60] * 5)
        rows = [Observation(TaskInput(t, "", ()), lookup[t], "spatial", (0.,) * 14, (Decimal(0),) * 14) for t in self.ids]
        self.assertEqual([sorted(r.task.task_id for r in f) for f in family_folds(rows, seed=CV_SEED)], self.plan["folds"])

    def test_bound_input_order_and_reject_resigned_changes(self):
        self.assertEqual(self.plan, make_plan(self.m, list(reversed(self.ids)), list(reversed(self.repeats)), bindings=self.bindings))
        for change in ("task", "cost", "slot", "fold"):
            plan = deepcopy(self.plan)
            if change == "task": plan["task_ids"][0] = "unselected-relative"
            elif change == "cost": plan["proposed_phase_cap_usd"] = "100"
            elif change == "slot": plan["slots"].pop()
            else: plan["folds"][0].append(plan["folds"][1][0])
            plan["sha256"] = digest({k: v for k, v in plan.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                validate_plan(plan, self.m, self.ids, self.repeats, bindings=self.bindings)
        for ids, repeats in ((self.ids[:-1], self.repeats), (["foreign-pilot"] + self.ids[1:], self.repeats),
                             (self.ids, self.repeats[:-1]), (self.ids, ["unselected-relative"] + self.repeats[1:])):
            with self.assertRaises(ValueError): make_plan(self.m, ids, repeats, bindings=self.bindings)

    def test_exclusive_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plan.json"
            save_plan(p, self.plan, self.m, self.ids, self.repeats, bindings=self.bindings)
            before = p.read_bytes()
            with self.assertRaises(FileExistsError):
                save_plan(p, self.plan, self.m, self.ids, self.repeats, bindings=self.bindings)
            self.assertEqual(p.read_bytes(), before)


class PhaseBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budget.jsonl"
    def budget(self, cap="0.28", allow=True):
        return PhaseBudget(self.path, cap=Decimal(cap), reserve=Decimal("0.14"), max_calls=10,
                           binding="a" * 64, allow_synthetic=allow)
    def response(self, cost):
        return Response("fake", Usage(cost_usd=Decimal(cost), cost_source="synthetic"))

    def test_real_zero_releases_reservation_and_exact_cap_stops(self):
        b = self.budget()
        b.run("a", lambda: self.response("0"))
        b.run("b", lambda: self.response("0.14"))
        b.run("c", lambda: self.response("0.14"))
        reached = []
        with self.assertRaises(BudgetStop): b.run("d", lambda: reached.append(True))
        self.assertEqual(reached, [])
        self.assertEqual(b.snapshot()["known_cost_usd"], "0.28")

    def test_unknown_and_known_failure_prevent_further_calls(self):
        b = self.budget()
        b.run("a", lambda: self.response("0.01"))
        with self.assertRaises(BudgetStop): b.run("b", lambda: Response("fake", Usage()))
        self.assertIsNone(b.snapshot()["total_cost_usd"])
        self.assertEqual(b.snapshot()["held_reservation_usd"], "0.14")
        with self.assertRaises(BudgetStop): b.start("c")
        second = PhaseBudget(Path(self.tmp.name) / "failure.jsonl", cap=Decimal(1), reserve=Decimal("0.14"),
                             max_calls=3, binding="b" * 64, allow_synthetic=True)
        def failed(): raise AdapterError("fake", Usage(cost_usd=Decimal("0.02"), cost_source="synthetic"))
        with self.assertRaises(BudgetStop): second.run("a", failed)
        self.assertEqual(second.snapshot()["known_cost_usd"], "0.02")
        self.assertTrue(second.poisoned)

    def test_duplicate_open_attempt_and_call_limit(self):
        b = self.budget()
        b.start("a")
        with self.assertRaises(BudgetStop): b.start("b")
        self.assertIsNone(b.snapshot()["total_cost_usd"])
        other = PhaseBudget(Path(self.tmp.name) / "other", cap=Decimal(1), reserve=Decimal("0.14"),
                            max_calls=1, binding="b" * 64, allow_synthetic=True)
        other.run("a", lambda: self.response("0"))
        with self.assertRaises(BudgetStop): other.start("a")
        self.assertEqual(other.calls, 1)

    def test_write_failure_occurs_before_operation(self):
        b = self.budget(); reached = []
        with patch("communication_pruning.phase_budget.os.fsync", side_effect=OSError("fake write failure")):
            with self.assertRaises(OSError): b.run("a", lambda: reached.append(True))
        self.assertEqual(reached, [])
        self.assertTrue(b.poisoned)
        with self.assertRaises(BudgetStop): b.start("b")

    def test_oversize_actual_cost_is_retained_and_never_called_safe(self):
        b = self.budget(cap="0.14")
        with self.assertRaises(BudgetStop): b.run("a", lambda: self.response("0.20"))
        self.assertEqual(b.snapshot()["known_cost_usd"], "0.20")
        self.assertTrue(b.poisoned)
        self.assertIn('"over_reservation": true', self.path.read_text())

    def test_synthetic_prices_not_allowed_in_real_mode_and_existing_file_protected(self):
        b = self.budget(allow=False)
        with self.assertRaises(BudgetStop): b.run("a", lambda: self.response("0"))
        self.assertIsNone(b.snapshot()["total_cost_usd"])
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError): self.budget()
        self.assertEqual(self.path.read_bytes(), before)
