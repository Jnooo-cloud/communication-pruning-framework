"""Hand-defined selection problems, no empirical controller evaluation."""
from dataclasses import replace
from decimal import Decimal
import json
import math
import unittest

from communication_pruning.contracts import TaskInput
from communication_pruning.selection import (CONFIG_IDS, Observation, choose, family_folds,
                                             features, fit_selector, fit_tree, predict_tree)


def sample(i, family=None):
    group = i % 2
    task = TaskInput(f"opaque-{i:03}", "short" if group == 0 else "long question with many words", ("shared",))
    q = tuple(float(k == group) for k in range(14))
    c = tuple(Decimal(1 if k < 2 else 10) for k in range(14))
    return Observation(task, family or f"family-{i:03}", "spatial", q, c)


class SelectionTests(unittest.TestCase):
    def test_k1_hand_features_empty_context_and_opaque_ids(self):
        task = TaskInput("id", "A b b?", ("a b", "b c"))
        result = features(task)
        self.assertEqual(result[:3], (3., 4., 1.))
        self.assertAlmostEqual(result[3], 2/3)
        self.assertEqual(features(TaskInput("different", task.question, task.paragraphs)), result)
        self.assertEqual(features(TaskInput("id", "", ())), (0., 0., 0., 0.))
        self.assertEqual(features(TaskInput("id", "A", ("a",)))[2:], (1., 1.))

    def test_k2_margin_cost_and_id_order(self):
        q = [0.0]*14
        c = [Decimal(10)]*14
        q[0], q[1], q[2] = 1.0, .99, .989
        c[0], c[1], c[2] = Decimal(3), Decimal(2), Decimal(1)
        self.assertEqual(choose(q, c), 1)
        q[0] = .99
        c[0] = Decimal(2)
        self.assertEqual(choose(q, c), 2)  # All three within .01; cheapest wins.
        c[2] = Decimal(2)
        self.assertEqual(choose(q, c), 0)

    def test_k3_family_folds_invariant_and_disjoint(self):
        rows = [sample(i, f"f-{i//3}") for i in range(30)]
        first = family_folds(rows, seed="predefined")
        second = family_folds(reversed(rows), seed="predefined")
        self.assertEqual(first, second)
        self.assertEqual(sum(map(len, first)), len(rows))
        seen = set()
        for fold in first:
            families = {r.family_id for r in fold}
            self.assertFalse(seen & families)
            seen |= families

    def test_k4_tree_leaf_means_depth_and_minimum(self):
        rows = [sample(i) for i in range(160)]
        tree = fit_tree(rows, depth=2)
        self.assertIn("feature", tree)
        self.assertEqual(tree["feature"], 0)
        self.assertEqual(tree["left"]["n"], 80)
        self.assertEqual(tree["right"]["n"], 80)
        self.assertEqual(predict_tree(tree, rows[0].task), rows[0].quality)
        self.assertEqual(predict_tree(tree, rows[1].task), rows[1].quality)
        small = fit_tree(rows[:60], depth=2)
        self.assertNotIn("feature", small)
        self.assertEqual(small["values"][:2], [.5, .5])

    def test_k5_adaptive_rule_cv_chooses_shallower_equal_candidate(self):
        rows = [sample(i) for i in range(160)]
        model = fit_selector(rows, seed="z04-synthetic-1")
        self.assertEqual(model.report["chosen_depth"], 1)
        self.assertEqual(model.select(rows[0].task), "C01")
        self.assertEqual(model.select(rows[1].task), "C02")
        self.assertEqual(json.loads(json.dumps(model.to_dict()))["config_ids"], list(CONFIG_IDS))
        for fold in model.report["folds"]:
            self.assertFalse(set(fold["training_ids"]) & set(fold["validation_ids"]))
            self.assertEqual(len(fold["training_ids"]) + len(fold["validation_ids"]), 160)

    def test_k5_fold_costs_and_fixed_reference_use_training_only(self):
        rows = [replace(sample(i), costs=tuple(Decimal(i+k+1) for k in range(14))) for i in range(30)]
        model = fit_selector(rows, seed="isolation", min_leaf=2)
        for fold in model.report["folds"]:
            train = [r for r in rows if r.task.task_id in fold["training_ids"]]
            expected_costs = tuple(sum((r.costs[k] for r in train), Decimal(0))/len(train) for k in range(14))
            self.assertEqual(fold["training_costs"], [str(c) for c in expected_costs])
            expected_q = tuple(sum(r.quality[k] for r in train)/len(train) for k in range(14))
            self.assertEqual(fold["fixed"], CONFIG_IDS[choose(expected_q, expected_costs)])

    def test_k5_fallback_is_valid_for_constant_or_insufficient_data(self):
        rows = [sample(i) for i in range(160)]
        constant = [replace(r, task=replace(r.task, question="same")) for r in rows]
        for data in (constant, rows[:4]):
            model = fit_selector(data, seed="fallback")
            self.assertIsNone(model.tree)
            self.assertIn("fallback_reason", model.report)
            self.assertEqual(model.select(rows[0].task), "C01")

    def test_k6_incomplete_invalid_or_wrong_phase_rejected(self):
        row = sample(1)
        for kwargs in ({"phase": "pilot"}, {"phase": "holdout"}, {"quality": row.quality[:-1]},
                       {"quality": (math.nan,) + row.quality[1:]},
                       {"quality": (1.1,) + row.quality[1:]},
                       {"costs": (None,) + row.costs[1:]},
                       {"costs": (Decimal("NaN"),) + row.costs[1:]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(row, **kwargs)
        with self.assertRaises(ValueError):
            fit_selector([row, row], seed="test")

    def test_training_order_and_inference_identity_do_not_change_selection(self):
        rows = [sample(i) for i in range(40)]
        a = fit_selector(rows, seed="order", min_leaf=4)
        b = fit_selector(reversed(rows), seed="order", min_leaf=4)
        self.assertEqual(a.to_dict(), b.to_dict())
        changed_id = replace(rows[0].task, task_id="4hop3__hidden_metadata")
        self.assertEqual(a.select(rows[0].task), a.select(changed_id))

    def test_invalid_training_controls(self):
        rows = [sample(i) for i in range(10)]
        for kwargs in ({"seed": ""}, {"seed": "ok", "min_leaf": True}, {"seed": "ok", "min_leaf": 0}):
            with self.assertRaises(ValueError):
                fit_selector(rows, **kwargs)
        with self.assertRaises(ValueError):
            fit_tree(rows, depth=3)

    def test_k8_split_matches_independent_bruteforce_loss(self):
        rows = []
        for i in range(12):
            task = TaskInput(f"case-{i}", "x "*(i+1), ("y "*(1+(i*7)%11),))
            quality = tuple(((i*(k+3)+k)%7)/6 for k in range(14))
            rows.append(Observation(task, f"f-{i}", "spatial", quality, (Decimal(1),)*14))
        candidates = []
        for feature in range(4):
            values = sorted({features(r.task)[feature] for r in rows})
            for a, b in zip(values, values[1:]):
                threshold = (a+b)/2
                left = [r for r in rows if features(r.task)[feature] <= threshold]
                right = [r for r in rows if features(r.task)[feature] > threshold]
                if min(len(left), len(right)) < 2:
                    continue
                loss = 0
                for group in (left, right):
                    for k in range(14):
                        mean = sum(r.quality[k] for r in group)/len(group)
                        loss += sum((r.quality[k]-mean)**2 for r in group)
                candidates.append((loss, feature, threshold))
        best_loss = min(c[0] for c in candidates)
        _, feature, threshold = min((c for c in candidates if abs(c[0]-best_loss) <= 1e-12),
                                    key=lambda c: (c[1], c[2]))
        actual = fit_tree(rows, depth=1, min_leaf=2)
        self.assertEqual((actual["feature"], actual["threshold"]), (feature, threshold))

    def test_k9_heldout_label_change_does_not_change_own_training_reference(self):
        rows = [sample(i) for i in range(40)]
        first = fit_selector(rows, seed="no-leak", min_leaf=2)
        heldout_ids = set(first.report["folds"][0]["validation_ids"])
        changed = [replace(r, quality=(0.9,)*14, costs=(Decimal(999),)*14)
                   if r.task.task_id in heldout_ids else r for r in rows]
        second = fit_selector(changed, seed="no-leak", min_leaf=2)
        self.assertEqual(first.report["folds"][0], second.report["folds"][0])
