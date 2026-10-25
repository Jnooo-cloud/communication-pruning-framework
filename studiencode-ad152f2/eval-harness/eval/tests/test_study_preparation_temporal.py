"""Z44 V3: artificial offline cases only; not real MiniLM or effect evidence."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import unittest

import numpy as np

from communication_pruning.contracts import TaskInput
from communication_pruning.data import TaskMeta, families, make_manifest
from communication_pruning.semantic_selection import encoder_identity, _matrix, _select_alpha
from study_preparation.temporal import (
    ARM_ORDER_SEED, FOLD_SEED, TemporalObservation, TemporalSelector,
    choose_rounds, digest, fit_temporal_ridge, fit_temporal_selector,
    make_temporal_plan, predict_temporal_scores, validate_temporal_plan,
)

BINDINGS = {"raw_q_source": "1" * 64, "synthetic_sources": "2" * 64}


class ArtificialEncoder:
    def __init__(self):
        self.identity = encoder_identity({f: "3" * 64 for f in (
            "config.json", "tokenizer.json", "tokenizer_config.json",
            "special_tokens_map.json", "vocab.txt", "model.safetensors")},
            {"test_double": True, "not_real_encoder_evidence": True})
        self.questions = []

    def encode_questions(self, questions):
        self.questions.extend(questions)
        result = []
        for q in questions:
            row = [0.] * 384
            row[0 if q == "positive" else 1] = 1.
            result.append(row)
        return result, {"artificial": True, "questions": len(questions)}


def observations(*, constant=False):
    rows, folds = [], []
    for fold in range(5):
        ids = []
        for positive in (False, True):
            tid = f"synthetic-{fold}-{int(positive)}"
            rows.append(TemporalObservation(
                TaskInput(tid, "positive" if positive else "negative", ("visible context",)),
                f"family-{fold}", "temporal", "C01",
                (.5, .5) if constant else (float(positive), float(not positive)),
                (Decimal("1"), Decimal("1"))))
            ids.append(tid)
        folds.append(ids)
    return rows, folds


def metadata():
    hops = [2] * 55 + [3] * 28 + [4] * 17
    rows = [TaskMeta(f"synthetic-{i:03}", "train", hops[i], (f"sub-{i//2}",)) for i in range(100)]
    mapping = families(rows)
    manifest = make_manifest(rows, exposed_ids=[], assignments={f: "temporal" for f in mapping.values()},
                             seed="synthetic-allocation", source_hashes={"train": "a" * 64})
    allocation = {"source_manifest_sha256": "f" * 64, "manifest": manifest,
                  "panels": {"temporal": [r.task_id for r in rows]}}
    allocation["sha256"] = digest(allocation)
    return manifest, allocation


def resign(payload):
    copy = deepcopy(payload)
    copy.pop("sha256", None)
    copy["sha256"] = digest(copy)
    return copy


class TemporalPlanTests(unittest.TestCase):
    def test_exact_complete_metadata_plan_and_independent_order_formula(self):
        manifest, allocation = metadata()
        plan = make_temporal_plan(manifest, allocation, BINDINGS)
        self.assertEqual(plan["task_ids"], allocation["panels"]["temporal"])
        self.assertEqual(len(plan["pairs"]), 100)
        self.assertEqual(len({s["slot_id"] for s in plan["slots"]}), 200)
        self.assertEqual(Counter(s["rounds"] for s in plan["slots"]), {1: 100, 2: 100})
        by_task = {t: f for f, ids in enumerate(plan["family_folds"]) for t in ids}
        self.assertEqual(set(by_task), set(plan["task_ids"]))
        for pair in plan["pairs"]:
            self.assertIsNone(pair["spatial_config_id"])
            self.assertEqual(pair["round_order"], sorted((1, 2), key=lambda r: digest([ARM_ORDER_SEED, pair["task_id"], r])))
        for i in range(0, 100, 2):
            self.assertEqual(by_task[f"synthetic-{i:03}"], by_task[f"synthetic-{i+1:03}"])
        self.assertNotEqual(FOLD_SEED, ARM_ORDER_SEED)
        self.assertFalse(plan["send_enabled"])
        self.assertFalse(plan["real_content_used"])
        validate_temporal_plan(plan, manifest, allocation, BINDINGS)
        plan["send_enabled"] = True
        with self.assertRaises(ValueError):
            validate_temporal_plan(plan, manifest, allocation, BINDINGS)

    def test_changed_missing_or_non_temporal_ids_and_source_binding_rejected(self):
        manifest, original = metadata()
        for kind in ("missing", "duplicate", "wrong_source", "wrong_hash"):
            allocation = deepcopy(original)
            if kind == "missing": allocation["panels"]["temporal"].pop()
            if kind == "duplicate": allocation["panels"]["temporal"][0] = allocation["panels"]["temporal"][1]
            if kind == "wrong_source": allocation["manifest"] = {}
            allocation = resign(allocation)
            if kind == "wrong_hash": allocation["sha256"] = "f" * 64
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                make_temporal_plan(manifest, allocation, BINDINGS)
        with self.assertRaises(ValueError):
            make_temporal_plan(manifest, original, {"other": "3" * 64})


class TemporalSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.folds = observations()
        cls.encoder = ArtificialEncoder()
        cls.fitted = fit_temporal_selector(cls.rows, encoder=cls.encoder, folds=cls.folds, bindings=BINDINGS)

    def test_complete_two_target_and_phase_contract(self):
        row = self.rows[0]
        for change in ({"phase": "spatial"}, {"quality": (.4,)}, {"costs": (Decimal("1"),)},
                       {"quality": (float("nan"), 0.)}, {"quality": (1.1, 0.)},
                       {"spatial_config_id": "C15"}, {"costs": (Decimal("-1"), Decimal("1"))}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(row, **change)

    def test_unclipped_margin_cost_round_and_alpha_ties(self):
        self.assertEqual(choose_rounds((4.0, 4.009), (Decimal("1"), Decimal("2"))), 1)
        self.assertEqual(choose_rounds((-2., -1.98), (Decimal("1"), Decimal("2"))), 2)
        self.assertEqual(choose_rounds((.5, .5), (Decimal("1"), Decimal("1"))), 1)
        reports = [{"alpha": a, "quality": .5, "cost_usd": "1"} for a in (1, 10, 100)]
        self.assertEqual(_select_alpha(reports), 100)
        reports[0]["cost_usd"] = ".9"
        self.assertEqual(_select_alpha(reports), 1)

    def test_ridge_matches_independent_normal_equations_and_constant_zero(self):
        rows = self.rows[:6]
        x = np.ones((6, 388))
        x[:, 0] = [-2, -1, 0, 1, 2, 4]
        x[:, 1] = [0, 1, 0, 2, 1, 3]
        fitted = fit_temporal_ridge(rows, x, alpha=10)
        z = (x[:, :2] - x[:, :2].mean(0)) / x[:, :2].std(0)
        y = np.asarray([r.quality for r in rows])
        coef = np.linalg.solve(z.T @ z + 10 * np.eye(2), z.T @ (y - y.mean(0)))
        np.testing.assert_allclose(np.asarray(fitted["coefficients"])[:, :2], coef.T, rtol=0, atol=2e-15)
        self.assertEqual(np.count_nonzero(np.asarray(fitted["coefficients"])[:, 2:]), 0)
        np.testing.assert_allclose(fitted["intercepts"], y.mean(0), rtol=0, atol=2e-15)
        np.testing.assert_allclose(predict_temporal_scores(fitted, x), z @ coef + y.mean(0), rtol=0, atol=3e-15)

    def test_fivefold_training_scaling_cost_and_labels_exclude_heldout(self):
        changed = list(self.rows)
        for i, row in enumerate(changed):
            if row.task.task_id in self.folds[0]:
                changed[i] = replace(row, quality=(.13, .97), costs=(Decimal("900"), Decimal("800")),
                                     task=TaskInput(row.task.task_id, "changed visible question words", ("new context words",)))
        altered = fit_temporal_selector(changed, encoder=ArtificialEncoder(), folds=self.folds, bindings=BINDINGS)
        for before, after in zip(self.fitted.payload["cross_validation"], altered.payload["cross_validation"]):
            self.assertEqual(before["folds"][0]["model"], after["folds"][0]["model"])
            self.assertTrue(set(self.folds[0]).isdisjoint(before["folds"][0]["model"]["training_task_ids"]))
        self.assertEqual(self.fitted.payload["chosen_alpha"], self.fitted.payload["model"]["alpha"])
        self.assertEqual(len(self.fitted.payload["model"]["coefficients"]), 2)

    def test_family_split_duplicate_and_missing_folds_rejected(self):
        split = deepcopy(self.folds)
        split[0][0], split[1][0] = split[1][0], split[0][0]
        for folds in (split, self.folds[:4], self.folds[:4] + [self.folds[0]]):
            with self.assertRaises(ValueError):
                fit_temporal_selector(self.rows, encoder=ArtificialEncoder(), folds=folds, bindings=BINDINGS)
        with self.assertRaises(ValueError):
            fit_temporal_selector(self.rows + [self.rows[0]], encoder=ArtificialEncoder(), folds=self.folds, bindings=BINDINGS)

    def test_constant_solution_preserved_and_fixed_reference_train_means(self):
        rows, folds = observations(constant=True)
        model = fit_temporal_selector(rows, encoder=ArtificialEncoder(), folds=folds, bindings=BINDINGS)
        self.assertEqual(model.payload["chosen_alpha"], 100)
        self.assertEqual(model.payload["fixed_rounds"], 1)
        self.assertEqual(set(model.payload["training_selections"]), {1})
        self.assertFalse(model.payload["independent_effect_evidence"])

    def test_roundtrip_public_input_only_and_resigned_changes_rejected(self):
        exported = self.fitted.to_dict()
        restored = TemporalSelector.from_dict(exported, encoder=ArtificialEncoder())
        for row in self.rows:
            self.assertEqual(restored.select(row.task), self.fitted.select(row.task))
            renamed = replace(row.task, task_id="different administrative ID")
            self.assertEqual(restored.select(renamed), restored.select(row.task))
        for change in ("parameters", "shape", "release", "family", "training_leak"):
            bad = deepcopy(exported)
            if change == "parameters": bad["parameters"]["epsilon"] = .02
            if change == "shape": bad["model"]["coefficients"].append([0.] * 388)
            if change == "release": bad["send_enabled"] = True
            if change == "family": bad["task_families"][self.rows[0].task.task_id] = self.rows[2].family_id
            if change == "training_leak": bad["cross_validation"][0]["folds"][0]["model"]["training_task_ids"].append(self.folds[0][0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                TemporalSelector.from_dict(resign(bad), encoder=ArtificialEncoder())


if __name__ == "__main__":
    unittest.main()
