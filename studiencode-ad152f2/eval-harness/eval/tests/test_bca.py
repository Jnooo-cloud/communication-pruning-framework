import itertools
import math
import random
import unittest

from bca_reference import reference
from communication_pruning.bca import _component, bca_report, family_jackknife, paired_bca
from communication_pruning.inference import FamilyTotal, estimate, hypothetical_decision, resampled_estimates
from test_inference import pair


class BcaTests(unittest.TestCase):
    def setUp(self):
        self.totals = tuple(FamilyTotal(str(i), n, q, f, a) for i, (n,q,f,a) in
                            enumerate([(1,0,2,1), (2,1,12,11), (3,-1,4,3), (4,2,8,7)]))

    def test_direct_family_deletion_matches_fast(self):
        for actual, i in zip(family_jackknife(self.totals), range(4)):
            expected = estimate(self.totals[:i]+self.totals[i+1:])
            for a,b in zip(actual, expected):
                self.assertAlmostEqual(a,b,places=14)

    def test_exhaustive_bca_reference(self):
        indices = list(itertools.product(range(4), repeat=4))
        samples = resampled_estimates(self.totals, indices)
        ref = reference([(t.tasks,t.quality_sum,t.fixed_sum,t.adaptive_sum) for t in self.totals], samples)
        actual = bca_report(self.totals, samples)
        for key, expected in zip(("quality", "cost"), ref):
            component = actual["components"][key]
            for field in ("z0", "acceleration"):
                self.assertAlmostEqual(component[field], expected[field], places=12)
            for a,b in zip(component["bounds"], expected["bounds"]):
                self.assertAlmostEqual(a,b,places=12)

    def test_analytic_acceleration_and_half_ties(self):
        symmetric = _component(0, [-1,0,1]*100, [-.5,0,.5])
        self.assertEqual(symmetric["z0"], 0)
        self.assertEqual(symmetric["acceleration"], 0)
        for actual, expected in zip(symmetric["probabilities"], (.025,.975)):
            self.assertAlmostEqual(actual, expected, places=14)
        asymmetric = _component(1/3, [0,1/3,2/3]*100, [.5,.5,0])
        self.assertAlmostEqual(asymmetric["acceleration"], 1/(6*math.sqrt(6)), places=14)

    def test_degeneracy_and_infinite_correction(self):
        for values, jack, expected in [([1,1], [0,1,2], "degenerate_bootstrap"),
                                       ([1,2], [0,1,2], "infinite_bias_correction"),
                                       ([-1,1], [0,0,0], "degenerate_jackknife")]:
            self.assertEqual(_component(0,values,jack)["reason"], expected)

    def test_tail_warning_blocks_decision(self):
        samples = resampled_estimates(self.totals, list(itertools.product(range(4),repeat=4))[:20])
        report = bca_report(self.totals,samples)
        self.assertFalse(report["assessable"])
        self.assertIsNone(hypothetical_decision(report,quality_margin=.03,cost_ratio_limit=.9))
        # Defined interval with insufficient tail resolution; no fallback.
        c = _component(0, [-1,0,1],[-.5,0,.5])
        self.assertIsNotNone(c["bounds"])
        self.assertTrue(c["tail_resolution_warning"])

    def test_undefined_jackknife_reference_is_explicit(self):
        ts = tuple(FamilyTotal(str(i),1,0,float(i==0),.2) for i in range(3))
        result = bca_report(ts, [(0,.5),(.1,.6)])
        self.assertIsNone(result["cost_ratio_bounds"])
        self.assertIn("reference cost",result["components"]["cost"]["reason"])
        self.assertFalse(result["assessable"])

    def test_invalid_input(self):
        for totals,samples in [(self.totals[:2],[(0,1)]*3),(self.totals,[]),(self.totals,[(math.nan,1)]*3)]:
            with self.assertRaises(ValueError):
                bca_report(totals,samples)

    def test_full_pair_wrapper_reproducible(self):
        ps = [pair(str(i),str(i),1,(i%3)-1,i+1,(i+1)*(.5+.1*i)) for i in range(4)]
        kwargs = dict(expected_slots={(str(i),1) for i in range(4)},phase="analysis",draws=199,seed=42)
        a = paired_bca([x[0] for x in ps],[x[1] for x in ps],**kwargs)
        b = paired_bca([x[0] for x in ps],[x[1] for x in ps],**kwargs)
        self.assertEqual(a,b)

    def test_random_reference_parity(self):
        rng = random.Random(11)
        totals = tuple(FamilyTotal(str(i),i+1,rng.uniform(-1,1),i+1.,rng.uniform(1,9)) for i in range(12))
        samples = resampled_estimates(totals,[[rng.randrange(12) for _ in range(12)] for _ in range(1999)])
        ref = reference([(t.tasks,t.quality_sum,t.fixed_sum,t.adaptive_sum) for t in totals],samples)
        actual = bca_report(totals,samples)
        for key,expected in zip(("quality","cost"),ref):
            for a,b in zip(actual["components"][key]["bounds"],expected["bounds"]):
                self.assertAlmostEqual(a,b,places=11)


if __name__ == "__main__":
    unittest.main()
