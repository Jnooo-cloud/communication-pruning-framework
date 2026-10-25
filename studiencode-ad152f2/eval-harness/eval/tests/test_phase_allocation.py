"""Known feasible/infeasible structural problems; no real answers or task text."""

from copy import deepcopy
import unittest

from communication_pruning.data import TaskMeta, make_manifest, digest
from communication_pruning.phase_allocation import allocate, quotas, repeat_subset, validate_allocation


SMALL = {p: {"n": 6, "min_families": 2} for p in ("spatial", "pilot", "temporal", "technical")}


def fixture(family_count=12, reverse=False):
    rows = [TaskMeta(f"fake-{f}-{h}", "train", h, (f"shared-{f}",))
            for f in range(family_count) for h in (2, 3, 4)]
    rows += [TaskMeta(f"dev-{h}", "dev", h, (f"dev-shared-{h}",)) for h in (2, 3, 4)]
    rows += [TaskMeta("exposed-train", "train", 2, ("old-exposure",)),
             TaskMeta("exposed-relative", "train", 3, ("old-exposure",)),
             TaskMeta("cross-train", "train", 4, ("cross-split",)),
             TaskMeta("cross-dev", "dev", 4, ("cross-split",))]
    if reverse:
        rows.reverse()
    return make_manifest(rows, exposed_ids=["exposed-train"], assignments={},
                         seed="old-synthetic-index", source_hashes={"train": "a" * 64, "dev": "b" * 64})


class PhaseAllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = fixture()
        cls.plan = allocate(cls.source, exposed_ids=["exposed-train"], targets=SMALL)

    def check(self, plan):
        return validate_allocation(plan, self.source, exposed_ids=["exposed-train"], targets=SMALL)

    def test_known_quota_apportionment_and_invalid_controls(self):
        self.assertEqual(quotas(300, {2: 1247, 3: 648, 4: 382}), {2: 164, 3: 86, 4: 50})
        self.assertEqual(quotas(120, {2: 1247, 3: 648, 4: 382}), {2: 66, 3: 34, 4: 20})
        self.assertEqual(quotas(50, {2: 164, 3: 86, 4: 50}), {2: 28, 3: 14, 4: 8})
        for n, weights in ((True, {2: 1, 3: 1, 4: 1}), (0, {2: 1, 3: 1, 4: 1}),
                           (5, {2: 1, 3: 1}), (5, {2: 0, 3: 1, 4: 1})):
            with self.assertRaises(ValueError):
                quotas(n, weights)
        for limit in (0, -1, 61, float("nan"), True):
            with self.assertRaises(ValueError):
                allocate(self.source, exposed_ids=["exposed-train"], targets=SMALL, time_limit=limit)

    def test_feasible_solution_and_known_optimal_reserved_count(self):
        summary = self.check(self.plan)
        self.assertEqual(self.plan["solver"]["status"], 0)
        self.assertEqual(sum(s["reserved_tasks"] for s in summary["panels"].values()), 24)
        # 24 selected tasks is a lower bound on 24 reserved tasks, attained here.
        for panel in summary["panels"].values():
            self.assertEqual(panel["selected_tasks"], 6)
            self.assertEqual(panel["families"], 2)
            self.assertEqual(panel["selected_hops"], {2: 2, 3: 2, 4: 2})
            self.assertEqual(panel["max_selected_per_family"], 3)

    def test_exposed_family_and_cross_split_never_selected(self):
        by_id = {e["task_id"]: e for e in self.plan["manifest"]["entries"]}
        self.assertEqual(by_id["exposed-relative"]["phase"], "excluded")
        self.assertEqual(by_id["cross-train"]["phase"], "unused")
        self.assertEqual(by_id["cross-dev"]["phase"], "unused")
        self.assertTrue(all(by_id[f"dev-{h}"]["phase"] == "holdout" for h in (2, 3, 4)))

    def test_input_order_invariance_same_solver(self):
        source = fixture(reverse=True)
        other = allocate(source, exposed_ids=["exposed-train"], targets=dict(reversed(list(SMALL.items()))))
        self.assertEqual(other["panels"], self.plan["panels"])
        self.assertEqual(other["manifest"], self.plan["manifest"])

    def test_impossible_joint_problem_stops_without_relaxation(self):
        with self.assertRaisesRegex(ValueError, "no admissible allocation"):
            allocate(fixture(family_count=4), exposed_ids=["exposed-train"], targets=SMALL)

    def test_provenance_and_existing_reservations(self):
        for exposure in ([], ["missing"], ["exposed-train", "missing"]):
            with self.assertRaises(ValueError):
                allocate(self.source, exposed_ids=exposure, targets=SMALL)
        with self.assertRaisesRegex(ValueError, "reservation"):
            allocate(self.plan["manifest"], exposed_ids=["exposed-train"], targets=SMALL)
        bad = deepcopy(self.source)
        bad["entries"].append(bad["entries"][0])
        bad["sha256"] = digest({k: v for k, v in bad.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            allocate(bad, exposed_ids=["exposed-train"], targets=SMALL)

    def test_resigned_panel_and_role_tampering_rejected(self):
        for mutation in ("duplicate", "foreign", "role", "metadata", "seed"):
            plan = deepcopy(self.plan)
            if mutation == "duplicate":
                plan["panels"]["pilot"][0] = plan["panels"]["pilot"][1]
            elif mutation == "foreign":
                plan["panels"]["pilot"][0] = plan["panels"]["spatial"][0]
            elif mutation == "role":
                plan["manifest"]["entries"][0]["phase"] = "pilot"
            elif mutation == "metadata":
                plan["manifest"]["entries"][0]["hop"] = 2
            else:
                plan["seed"] = "post-outcome-change"
            plan["manifest"]["sha256"] = digest({k: v for k, v in plan["manifest"].items() if k != "sha256"})
            plan["sha256"] = digest({k: v for k, v in plan.items() if k != "sha256"})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.check(plan)

    def test_repeat_subset_is_prebound_unique_and_stratified(self):
        sub = repeat_subset(self.plan, 3)
        self.assertEqual(sub, repeat_subset(self.plan, 3))
        self.assertEqual(len(set(sub["task_ids"])), 3)
        self.assertTrue(set(sub["task_ids"]) <= set(self.plan["panels"]["spatial"]))
        self.assertEqual(sub["hop_counts"], {2: 1, 3: 1, 4: 1})
        for n in (0, 7, True):
            with self.assertRaises(ValueError):
                repeat_subset(self.plan, n)

    def test_closest_mode_has_known_minimum_without_relaxing_total_or_families(self):
        source = fixture()
        # Four available four-hop tasks for eight requested; at least four
        # substitutions and L1>=8. Remaining task supply can cover all 24 slots.
        source["entries"] = [e for e in source["entries"]
                             if not (e["task_id"].startswith("fake-") and e["hop"] == 4
                                     and int(e["task_id"].split("-")[1]) >= 4)]
        rows = [TaskMeta(e["task_id"], e["split"], e["hop"], tuple(e["subquestions"])) for e in source["entries"]]
        source = make_manifest(rows, exposed_ids=["exposed-train"], assignments={},
                               seed="scarce-synthetic", source_hashes=source["source_hashes"])
        result = allocate(source, exposed_ids=["exposed-train"], targets=SMALL, quota_mode="closest")
        summary = validate_allocation(result, source, exposed_ids=["exposed-train"], targets=SMALL, quota_mode="closest")
        self.assertEqual(result["quota_proof"]["l1"], 8)
        self.assertEqual(result["quota_proof"]["capacity_lower_bound"], 8)
        self.assertEqual(summary["quota_l1"], 8)
        self.assertEqual(sum(p["selected_tasks"] for p in summary["panels"].values()), 24)
        with self.assertRaises(ValueError):
            validate_allocation(result, source, exposed_ids=["exposed-train"], targets=SMALL)
        tampered = deepcopy(result)
        tampered["quota_proof"]["l1"] = 0
        tampered["sha256"] = digest({k: v for k, v in tampered.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_allocation(tampered, source, exposed_ids=["exposed-train"], targets=SMALL, quota_mode="closest")

    def test_closest_mode_does_not_relax_impossible_total(self):
        with self.assertRaisesRegex(ValueError, "no admissible quota adjustment"):
            allocate(fixture(family_count=4), exposed_ids=["exposed-train"], targets=SMALL, quota_mode="closest")

    def test_closest_mode_preserves_feasible_exact_quotas(self):
        result = allocate(self.source, exposed_ids=["exposed-train"], targets=SMALL, quota_mode="closest")
        self.assertEqual(result["quota_proof"]["l1"], 0)
        summary = validate_allocation(result, self.source, exposed_ids=["exposed-train"], targets=SMALL, quota_mode="closest")
        self.assertEqual(summary["quota_l1"], 0)
