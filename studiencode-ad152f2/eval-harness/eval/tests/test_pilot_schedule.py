"""Synthetic panel only; no real task sampling or trained selection policies."""

from collections import Counter
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from communication_pruning.data import TaskMeta, families, make_manifest, digest
from communication_pruning.pilot_schedule import make_schedule, save_schedule, validate_schedule


def fixture():
    # 40 double and 40 single families. Extra metadata test full-family roles.
    rows = [TaskMeta(f"fake-{i:03d}", "train", 2 + i % 3,
                     (f"shared-{i // 2 if i < 80 else i - 40}",)) for i in range(120)]
    rows += [TaskMeta("unused-member", "train", 2, ("shared-0",)),
             TaskMeta("foreign", "train", 2, ("foreign",)),
             TaskMeta("exposed", "train", 2, ("exposed",)),
             TaskMeta("dev-task", "dev", 2, ("dev-only",))]
    family = families(rows)
    assignments = {family[r.task_id]: "pilot" for r in rows[:120]}
    assignments[family["foreign"]] = "spatial"
    assignments[family["dev-task"]] = "holdout"
    manifest = make_manifest(rows, assignments=assignments, exposed_ids=["exposed"],
                             seed="fake-phase-allocation", source_hashes={"train": "a" * 64, "dev": "b" * 64})
    bindings = {"q_policy": "c" * 64, "fixed_policy": "d" * 64,
                "execution_contract": "e" * 64}
    return manifest, [r.task_id for r in rows[:120]], bindings


class PilotScheduleTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.ids, self.bindings = fixture()

    def make(self, **kwargs):
        return make_schedule(self.manifest, self.ids, bindings=self.bindings, **kwargs)

    def validate(self, plan, **kwargs):
        return validate_schedule(plan, self.manifest, expected_bindings=self.bindings,
                                 expected_task_ids=self.ids, **kwargs)

    def test_complete_pairs_balanced_blocks_and_family_reservation(self):
        plan = self.make()
        slots = plan["slots"]
        self.assertEqual(len(slots), 720)
        self.assertEqual(len({s["slot_id"] for s in slots}), 720)
        self.assertEqual(Counter((s["task_id"], s["arm"]) for s in slots),
                         Counter({(t, arm): 3 for t in self.ids for arm in ("Q", "F*")}))
        self.assertEqual(plan["summary"]["families"], 80)
        self.assertEqual(plan["summary"]["max_model_calls_without_retry"], 120 * 3 * 2 * 7)
        for i in range(0, 720, 2):
            first, second = slots[i:i + 2]
            for field in ("task_id", "family_id", "pair", "repeat", "block"):
                self.assertEqual(first[field], second[field])
            self.assertEqual({first["arm"], second["arm"]}, {"Q", "F*"})
            self.assertEqual((first["position"], second["position"]), (1, 2))
            self.assertTrue(first["fresh_context"] and second["fresh_context"])
        for block in range(1, 19):
            self.assertEqual(Counter(s["arm"] for s in slots if s["block"] == block and s["position"] == 1),
                             Counter({"Q": 10, "F*": 10}))
        self.assertEqual(next(e for e in self.manifest["entries"] if e["task_id"] == "unused-member")["phase"], "pilot")
        self.assertNotIn("unused-member", plan["task_ids"])

    def test_portable_order_and_separate_seed(self):
        self.assertEqual(self.make(), make_schedule(self.manifest, list(reversed(self.ids)), bindings=self.bindings))
        second = self.make(seed="another-prebound-seed")
        self.assertNotEqual(self.make()["slots"], second["slots"])
        self.assertEqual(second["task_ids"], self.ids)
        self.validate(second, expected_seed="another-prebound-seed")
        with self.assertRaises(ValueError):
            self.validate(second)

    def test_wrong_roles_exposure_and_unknown_ids(self):
        for wrong in ("foreign", "exposed", "dev-task", "not-in-manifest"):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                make_schedule(self.manifest, [wrong] + self.ids[1:], bindings=self.bindings)
        tampered = deepcopy(self.manifest)
        tampered["entries"][0]["phase"] = "spatial"
        with self.assertRaises(ValueError):
            make_schedule(tampered, self.ids, bindings=self.bindings)

    def test_size_duplicates_seed_and_binding_types(self):
        for ids in (self.ids[:-1], self.ids + ["extra"], [self.ids[1]] + self.ids[1:], [None] + self.ids[1:]):
            with self.assertRaises(ValueError):
                make_schedule(self.manifest, ids, bindings=self.bindings)
        for seed in ("", " ", None, True, 123):
            with self.assertRaises(ValueError):
                self.make(seed=seed)
        for bindings in ({}, {**self.bindings, "extra": "f" * 64}, {**self.bindings, "q_policy": "unbound"}):
            with self.assertRaises(ValueError):
                make_schedule(self.manifest, self.ids, bindings=bindings)

    def test_family_breadth_and_cap(self):
        # Too few families; then sufficient breadth but one family has six tasks.
        for groups in ([i // 2 for i in range(120)], [0] * 6 + list(range(1, 115))):
            rows = [TaskMeta(f"x{i}", "train", 2, (str(group),)) for i, group in enumerate(groups)]
            mapping = families(rows)
            manifest = make_manifest(rows, exposed_ids=[], assignments={f: "pilot" for f in mapping.values()},
                                     seed="synthetic", source_hashes={"train": "a" * 64})
            with self.assertRaises(ValueError):
                make_schedule(manifest, [r.task_id for r in rows], bindings=self.bindings)

    def test_resigned_tampering_and_changed_external_expectations(self):
        for mutation in ("remove", "repeat", "arm", "fresh", "binding", "type", "panel"):
            plan = self.make()
            if mutation == "remove":
                plan["slots"].pop()
            elif mutation == "repeat":
                plan["slots"][0]["repeat"] = 2
            elif mutation == "arm":
                plan["slots"][0]["arm"] = plan["slots"][1]["arm"]
            elif mutation == "fresh":
                plan["slots"][0]["fresh_context"] = False
            elif mutation == "type":
                plan["slots"][0]["position"] = True
            elif mutation == "panel":
                plan["task_ids"][0] = "unused-member"
            else:
                plan["bindings"]["q_policy"] = "f" * 64
            plan["sha256"] = digest({k: v for k, v in plan.items() if k != "sha256"})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.validate(plan)
        plan = self.make()
        with self.assertRaises(ValueError):
            validate_schedule(plan, self.manifest, expected_task_ids=self.ids,
                              expected_bindings={**self.bindings, "fixed_policy": "f" * 64})

    def test_output_create_only_and_bound_inputs(self):
        plan = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            save_schedule(path, plan, self.manifest, expected_bindings=self.bindings, expected_task_ids=self.ids)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                save_schedule(path, plan, self.manifest, expected_bindings=self.bindings, expected_task_ids=self.ids)
            link = Path(tmp) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(FileExistsError):
                save_schedule(link, plan, self.manifest, expected_bindings=self.bindings, expected_task_ids=self.ids)
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
