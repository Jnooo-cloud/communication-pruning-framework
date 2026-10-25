import dataclasses
from decimal import Decimal
import itertools
import math
import random
import unittest

from communication_pruning.evaluation import RunResult, paired_summary
from communication_pruning.inference import (FamilyTotal, estimate, family_totals, hypothetical_decision,
                                            interval_report, paired_bootstrap, quantile,
                                            resampled_estimates, validate_totals)


def pair(task, family, repeat, quality, fixed_cost, adaptive_cost):
    def run(arm, em, cost):
        return RunResult(f"{task}-{repeat}-{arm}", task, family, "analysis", arm, repeat,
                         "completed", em, em, Decimal(str(cost)), Decimal(str(cost)), 0, "synthetic")
    return run("F", int(quality < 0), fixed_cost), run("Q", int(quality > 0), adaptive_cost)


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.pairs = [pair("a", "A", 1, 1, 1, .5), pair("a", "A", 2, -1, 3, 1.5),
                      pair("b", "B", 1, 1, 10, 9), pair("c", "B", 1, 0, 2, 2)]
        self.f = [p[0] for p in self.pairs]
        self.q = [p[1] for p in self.pairs]
        self.slots = {(r.task_id, r.repeat) for r in self.f}
        self.kw = dict(expected_slots=self.slots, phase="analysis")

    def test_hand_weighting_and_point_compatibility(self):
        totals = family_totals(self.f, self.q, **self.kw)
        self.assertEqual(totals, (FamilyTotal("A", 1, 0, 2, 1), FamilyTotal("B", 2, 1, 12, 11)))
        self.assertEqual(estimate(totals), (1/3, 12/14))
        summary = paired_summary(self.f, self.q, **self.kw)
        self.assertEqual(summary["quality_difference"], 1/3)
        self.assertAlmostEqual(float(summary["cost_ratio"]), 12/14)
        # Equal family means (.25) or mean task ratios (.8) would be wrong.
        self.assertNotEqual(estimate(totals), (.25, .8))

    def test_exhaustive_family_draws(self):
        totals = family_totals(self.f, self.q, **self.kw)
        samples = resampled_estimates(totals, list(itertools.product(range(2), repeat=2)))
        self.assertEqual(samples, [(0, .5), (1/3, 12/14), (1/3, 12/14), (.5, 11/12)])

    def test_numpy_matches_reference(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("optional NumPy accelerator; run bundled Python for parity")
        totals = family_totals(self.f, self.q, **self.kw)
        indices = list(itertools.product(range(2), repeat=2))
        left = resampled_estimates(totals, indices)
        right = resampled_estimates(totals, indices, backend="numpy")
        for a, b in zip(left, right):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=14)

    def test_numpy_random_unequal_family_parity(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("optional NumPy accelerator")
        rng = random.Random(20260906)
        totals = tuple(FamilyTotal(str(i), i+1, rng.uniform(-1, 1)*(i+1),
                                   rng.uniform(.01, 100), rng.uniform(.01, 100)) for i in range(20))
        indices = [[rng.randrange(20) for _ in range(20)] for _ in range(500)]
        for left, right in zip(resampled_estimates(totals, indices),
                               resampled_estimates(totals, indices, backend="numpy")):
            for a, b in zip(left, right):
                self.assertTrue(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12))

    def test_quantiles_basic_and_strict_decision(self):
        self.assertEqual(quantile([0, 10], .025), .25)
        totals = family_totals(self.f, self.q, **self.kw)
        samples = [(0, .5), (.5, 1)]
        p = interval_report(totals, samples, method="percentile")
        b = interval_report(totals, samples, method="basic")
        self.assertAlmostEqual(b["quality_bounds"][0], 2/3-p["quality_bounds"][1])
        self.assertAlmostEqual(b["cost_ratio_bounds"][1], 24/14-p["cost_ratio_bounds"][0])
        p["quality_bounds"][0], p["cost_ratio_bounds"][1] = -.03, .8
        self.assertFalse(hypothetical_decision(p, quality_margin=.03, cost_ratio_limit=.9))
        self.assertTrue(hypothetical_decision(p, quality_margin=.05, cost_ratio_limit=.9))
        p["cost_ratio_bounds"][1] = .9
        self.assertFalse(hypothetical_decision(p, quality_margin=.05, cost_ratio_limit=.9))

    def test_reproducibility_and_no_input_mutation(self):
        kwargs = dict(self.kw, draws=99, seed=15, method="percentile")
        before = list(self.f)
        self.assertEqual(paired_bootstrap(self.f, self.q, **kwargs), paired_bootstrap(self.f, self.q, **kwargs))
        self.assertEqual(self.f, before)

    def test_degenerate_is_not_confirmatory(self):
        totals = (FamilyTotal("A", 1, 0, 1, .7), FamilyTotal("B", 1, 0, 1, .7))
        report = interval_report(totals, [(0, .7)] * 10, method="percentile")
        self.assertFalse(report["assessable"])
        self.assertIsNone(hypothetical_decision(report, quality_margin=.03, cost_ratio_limit=.9))

    def test_invalid_totals_and_draws(self):
        base = FamilyTotal("a", 1, 0, 1, .7)
        for totals in [(base,), (base, base), (base, dataclasses.replace(base, family_id="b", fixed_sum=math.nan)),
                       (base, dataclasses.replace(base, family_id="b", quality_sum=2)),
                       (dataclasses.replace(base, fixed_sum=0), FamilyTotal("b", 1, 0, 0, 0))]:
            with self.assertRaises(ValueError):
                validate_totals(totals)
        totals = (base, FamilyTotal("b", 1, 0, 0, 0))
        for ix in [[[1, 1]], [[0]], [[0, 2]], [], [[True, 0]]]:
            with self.assertRaises(ValueError):
                resampled_estimates(totals, ix)

    def test_incomplete_and_mixed_data_rejected(self):
        variants = [self.q[:-1], self.q+[self.q[0]],
                    [dataclasses.replace(self.q[0], cost_usd=None)]+self.q[1:],
                    [dataclasses.replace(self.q[0], phase="holdout")]+self.q[1:],
                    [dataclasses.replace(self.q[0], family_id="other")]+self.q[1:],
                    [dataclasses.replace(self.q[0], run_id=self.f[0].run_id)]+self.q[1:]]
        for q in variants:
            with self.assertRaises(ValueError):
                family_totals(self.f, q, **self.kw)
        with self.assertRaises(ValueError):
            family_totals([dataclasses.replace(r, family_id="") for r in self.f], self.q, **self.kw)


if __name__ == "__main__":
    unittest.main()
