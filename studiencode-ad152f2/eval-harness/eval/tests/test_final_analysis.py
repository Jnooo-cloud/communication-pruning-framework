"""Hand-valued complete blocks and malformed exports, all wholly artificial."""
from copy import deepcopy
import json
import math
import unittest
from unittest.mock import patch

import numpy as np

from study_preparation import final_analysis
from study_preparation.final_analysis import analyze_panel, validate_rows
from study_preparation.final_plan import ARMS, make_plan


def fixture_plan(n=2):
    return make_plan([{"task_id": "same-task", "family_id": "same-family"}],
                     seed_base=77, bindings={"fixture": "a" * 64}, mode="artificial_only",
                     counts={panel: n for panel in ARMS})


def fixture_rows(plan, panel, costs, em=None, f1=None):
    rows = []
    for i, block in enumerate(plan["panels"][panel]):
        values = {arm: j for j, arm in enumerate(ARMS[panel])}
        for slot in block["slots"]:
            j = values[slot["arm"]]
            row = {key: block[key] for key in ("panel", "block_id", "draw_index", "task_id", "family_id")}
            row.update(slot, cost_usd=str(costs[i][j]), em=em[i][j] if em is not None else 0,
                       f1=f1[i][j] if f1 is not None else 0, status="ok",
                       provenance={"fixture": "hand-values", "position": i})
            rows.append(row)
    return list(reversed(rows))  # Deliberately not input, draw or execution order.


def kernel_result(quality=(-0.02, 0.01), cost=(0.7, 0.8), quality_status="ok", cost_status="ok"):
    return {"n": 3, "bootstrap_reps": 19999, "status": "technical_candidate_not_study_release",
            "endpoints": {
                "P-D": {"estimate": 0.0, "se": 0.1, "lower": quality[0], "upper": quality[1],
                        "status": quality_status, "undefined_resamples": 0},
                "P-C": {"estimate": 0.75, "se": 0.1, "lower": cost[0], "upper": cost[1],
                        "status": cost_status, "undefined_resamples": 0}}}


class FinalAnalysisTests(unittest.TestCase):
    def test_primary_passes_each_draw_and_bound_atom_contract_to_existing_kernel(self):
        plan = fixture_plan(3)
        rows = fixture_rows(plan, "P", [[2, 4], [3, 5], [7, 8]],
                            em=[[1, 0], [0, 1], [1, 1]], f1=[[1, 0], [0, 1], [0.5, 0.5]])
        before = deepcopy(rows)
        with patch.object(final_analysis.intervals, "analyze", return_value=kernel_result()) as kernel:
            report = analyze_panel(plan, "P", rows, bootstrap_seed=123)
        atoms, counts, endpoints = kernel.call_args.args
        np.testing.assert_array_equal(atoms, [[1, 2, 4], [-1, 3, 5], [0, 7, 8]])
        np.testing.assert_array_equal(counts, [1, 1, 1])
        self.assertEqual([endpoint["id"] for endpoint in endpoints], ["P-D", "P-C"])
        self.assertEqual(endpoints[0], {"id": "P-D", "kind": "mean", "numerator": [1, 0, 0], "bounds": [-1, 1]})
        self.assertEqual(endpoints[1], {"id": "P-C", "kind": "ratio", "numerator": [0, 1, 0], "denominator": [0, 0, 1]})
        self.assertEqual(kernel.call_args.kwargs["bootstrap_reps"], 19999)
        self.assertNotIn("resample_counts", kernel.call_args.kwargs)
        self.assertEqual(kernel.call_args.kwargs["rng"].bit_generator.state,
                         np.random.PCG64(123).state)
        self.assertEqual(report["n"], 3)
        self.assertEqual(report["estimates"]["Q"]["em"], 2 / 3)
        self.assertEqual(report["estimates"]["Q"]["mean_cost_usd"], "4")
        self.assertTrue(report["primary"]["joint_positive"])
        self.assertEqual(rows, before)

    def test_primary_strict_boundaries_and_endpoint_blocks(self):
        plan = fixture_plan(3)
        rows = fixture_rows(plan, "P", [[1, 2]] * 3)
        cases = [
            (kernel_result(quality=(-0.03, 0), cost=(0.90, 0.90)),
             {"quality_preserved_3pp": "not_established", "quality_loss": "not_established",
              "cost_saving_at_least_10pct": "not_established", "cost_saving_below_10pct": "not_established"}),
            (kernel_result(quality=(-0.08, -0.04), cost=(1.01, 1.2)),
             {"quality_loss": "established", "quality_loss_beyond_3pp": "established",
              "cost_saving_below_10pct": "established", "cost_increase": "established"}),
            (kernel_result(quality_status="resample_undefined", cost_status="denominator_weak"),
             {"quality_preserved_3pp": "blocked", "cost_saving_at_least_10pct": "blocked"}),
        ]
        for result, statements in cases:
            with self.subTest(result=result), patch.object(final_analysis.intervals, "analyze", return_value=result):
                primary = analyze_panel(plan, "P", rows, bootstrap_seed=1)["primary"]
            self.assertFalse(primary["joint_positive"])
            for name, expected in statements.items():
                self.assertEqual(primary["statements"][name], expected)

    def test_actual_kernel_zero_denominator_is_json_safe_and_retains_failure_costs(self):
        plan = fixture_plan(2)
        rows = fixture_rows(plan, "P", [[0.1, 0], [0.3, 0]])
        rows[0]["status"] = "model_failure"
        report = analyze_panel(plan, "P", rows, bootstrap_seed=8)
        self.assertEqual(report["primary"]["kernel"]["bootstrap_reps"], 19999)
        cost = report["primary"]["kernel"]["endpoints"]["P-C"]
        self.assertEqual(cost["status"], "denominator_zero")
        self.assertEqual(cost["upper"], "Infinity")
        self.assertFalse(report["primary"]["joint_positive"])
        self.assertEqual(report["descriptive_costs"]["arms"]["Q"]["total"], "0.4")
        json.dumps(report, allow_nan=False)

    def test_reference_ratios_use_means_and_have_nine_complete_endpoints(self):
        plan = fixture_plan()
        rows = fixture_rows(plan, "R", [[1, 2, 4, 0, 2, 4], [3, 2, 2, 2, 4, 8]],
                            em=[[0, 1, 0, 1, 1, 0], [1, 0, 1, 0, 0, 1]])
        with patch.object(final_analysis.intervals, "analyze", side_effect=AssertionError("no secondary cost bootstrap")):
            report = analyze_panel(plan, "R", rows, bootstrap_seed=1)
        endpoints = report["descriptive_costs"]["endpoints"]
        expected = [1.5, 1.5, 1, 3, 0.5, 3, 3, 2, 6]
        self.assertEqual(list(endpoints), [f"R{i:02d}" for i in range(1, 10)])
        for endpoint, hand_value in zip(endpoints.values(), expected):
            self.assertEqual(float(endpoint["estimate"]), hand_value)
        self.assertNotEqual(float(endpoints["R01"]["estimate"]), (2 / 1 + 4 / 3) / 2)
        self.assertEqual(endpoints["R01"]["mean_difference_usd"], "1")
        self.assertEqual(endpoints["R01"]["paired_difference_usd"]["sample_sd"], "0")
        q = report["descriptive_costs"]["arms"]["Q"]
        self.assertEqual((q["mean"], q["min"], q["max"]), ("3", "2", "4"))
        self.assertAlmostEqual(float(q["sample_sd"]), math.sqrt(2))
        self.assertEqual(len(report["secondary_quality"]["em"]), 9)

    def test_temporal_quality_and_descriptive_paired_changes(self):
        plan = fixture_plan()
        rows = fixture_rows(plan, "T", [[1, 2], [3, 2]], em=[[1, 0], [0, 1]],
                            f1=[[0.8, 0.2], [0.4, 0.4]])
        report = analyze_panel(plan, "T", rows, bootstrap_seed=1)
        costs = report["descriptive_costs"]["endpoints"]["T01"]
        self.assertEqual(costs["estimate"], "1")
        self.assertEqual(costs["mean_difference_usd"], "0")
        quality = report["secondary_quality"]
        self.assertEqual(quality["em"]["T01"]["estimate"], 0)
        self.assertAlmostEqual(quality["f1"]["T01"]["estimate"], 0.3)
        self.assertAlmostEqual(quality["em"]["T01"]["radius"], 2 * math.sqrt(math.log(40) / 4))
        self.assertFalse(quality["simultaneous"])

    def test_fault_hand_values_and_double_quality_range(self):
        plan = fixture_plan()
        rows = fixture_rows(plan, "F", [[4, 2, 8, 12], [2, 4, 4, 2]],
                            em=[[1, 0, 0, 1], [0, 1, 1, 0]],
                            f1=[[0.8, 0.2, 0.4, 0.5], [0.1, 0.9, 0.6, 0.2]])
        report = analyze_panel(plan, "F", rows, bootstrap_seed=1)
        costs = report["descriptive_costs"]["endpoints"]
        self.assertEqual(list(costs), ["F01", "F02", "F03", "F04", "F05"])
        for name, expected in {"F01": 1, "F02": 7 / 6, "F03": 0, "F04": 1, "F05": -1}.items():
            self.assertAlmostEqual(float(costs[name]["estimate"]), expected)
        self.assertEqual(costs["F05"]["observed_changes_usd"]["min"], "-6")
        self.assertEqual(costs["F05"]["observed_changes_usd"]["max"], "4")
        quality = report["secondary_quality"]
        self.assertEqual(len(quality["em"]), 3)
        self.assertEqual(quality["em"]["d_Q_minus_d_F"]["estimate"], 0)
        self.assertAlmostEqual(quality["f1"]["d_Q_minus_d_F"]["estimate"], 0.25)
        self.assertAlmostEqual(quality["em"]["d_Q_minus_d_F"]["radius"],
                               2 * quality["em"]["d_Q"]["radius"])
        self.assertEqual((quality["em"]["d_Q_minus_d_F"]["lower"],
                          quality["em"]["d_Q_minus_d_F"]["upper"]), (-2, 2))

    def test_all_secondary_cost_fields_remain_descriptive_and_zero_reference_undefined(self):
        plan = fixture_plan(1)
        quality_count, cost_count = 0, 0
        forbidden = {"lower", "upper", "ci", "p", "p_value", "winner", "direction", "significant"}

        def check_keys(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for nested in value.values():
                    check_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    check_keys(nested)

        for panel in ("R", "T", "F"):
            costs = [[0] * len(ARMS[panel])]
            report = analyze_panel(plan, panel, fixture_rows(plan, panel, costs), bootstrap_seed=1)
            quality_count += len(report["secondary_quality"]["em"])
            cost_count += len(report["descriptive_costs"]["endpoints"])
            check_keys(report["descriptive_costs"])
            for endpoint in report["descriptive_costs"]["endpoints"].values():
                if endpoint["kind"] == "ratio_of_means":
                    self.assertIsNone(endpoint["estimate"])
                    self.assertEqual(endpoint["value_status"], "undefined_zero_reference")
            for summary in report["descriptive_costs"]["arms"].values():
                self.assertIsNone(summary["sample_sd"])
            json.dumps(report, allow_nan=False)
        self.assertEqual(quality_count, 13)
        self.assertEqual(cost_count, 15)

    def test_invalid_rows_stop_before_any_analysis(self):
        plan = fixture_plan()
        source = fixture_rows(plan, "P", [[1, 2], [3, 4]])
        mutations = [lambda rows: rows.pop(), lambda rows: rows.append(deepcopy(rows[0])),
                     lambda rows: rows.__setitem__(1, deepcopy(rows[0])),
                     lambda rows: rows[0].pop("family_id"),
                     lambda rows: rows[0].update(panel="R"),
                     lambda rows: rows[0].update(task_id="foreign"),
                     lambda rows: rows[0].update(family_id="foreign"),
                     lambda rows: rows[0].update(arm="S"),
                     lambda rows: rows[0].update(block_id="foreign"),
                     lambda rows: rows[0].update(draw_index=True),
                     lambda rows: rows[0].update(slot_id="foreign"),
                     lambda rows: rows[0].update(status="unresolved"),
                     lambda rows: rows[0].update(status="model_failure", em=1),
                     lambda rows: rows[0].update(provenance={"bad": float("nan")})]
        with patch.object(final_analysis.intervals, "analyze") as kernel:
            for mutate in mutations:
                changed = deepcopy(source)
                mutate(changed)
                with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                    analyze_panel(plan, "P", changed, bootstrap_seed=1)
            kernel.assert_not_called()

    def test_invalid_numeric_values_and_costs_are_not_imputed(self):
        plan = fixture_plan()
        source = fixture_rows(plan, "T", [[1, 2], [3, 4]])
        bad = {"cost_usd": [1, True, None, "NaN", "Infinity", "-0.01", "1_0", " 0.1", ""],
               "em": [True, 0.5, float("nan"), "1"],
               "f1": [True, -0.1, 1.1, float("inf"), float("nan"), "0.5"]}
        for field, values in bad.items():
            for value in values:
                rows = deepcopy(source)
                rows[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_rows(plan, "T", rows)

    def test_rows_preserve_provenance_and_return_independent_copies(self):
        plan = fixture_plan()
        rows = fixture_rows(plan, "R", [[1] * 6, [2] * 6])
        ordered = validate_rows(plan, "R", rows)
        self.assertEqual([row["arm"] for row in ordered], list(ARMS["R"]) * 2)
        self.assertEqual([row["draw_index"] for row in ordered], [0] * 6 + [1] * 6)
        self.assertEqual(ordered[0]["provenance"], {"fixture": "hand-values", "position": 0})
        ordered[0]["provenance"]["fixture"] = "changed-copy"
        self.assertTrue(all(row["provenance"]["fixture"] == "hand-values" for row in rows))


if __name__ == "__main__":
    unittest.main()
