"""Meaningful contract checks for the isolated Z33 candidate, no provider use."""
import math
import unittest
import numpy as np
from communication_pruning.paired_iid import intervals, empirical_quantile, _stats


class PairedIIDTests(unittest.TestCase):
    def setUp(self):
        self.atoms = np.array([[-1, .001, .002], [0, .003, .004], [1, .002, .003]])
        self.counts = np.array([50, 100, 50])

    def test_centered_se_hand_calculation(self):
        d, r, sd, sr, mb, sb = (x[0] for x in _stats(self.atoms, self.counts[None, :]))
        self.assertAlmostEqual(d, 0)
        self.assertAlmostEqual(r, .00225 / .00325)
        self.assertAlmostEqual(sd, math.sqrt(.5 / 199))
        residuals = (self.atoms[:, 1] - r * self.atoms[:, 2]) / mb
        expected = math.sqrt(sum(self.counts * residuals ** 2) / (200 * 199))
        self.assertAlmostEqual(sr, expected, places=13)

    def test_quantile_is_inverse_cdf_not_interpolated(self):
        self.assertEqual(empirical_quantile([3, 1, 2, 4], .6), 3)
        self.assertEqual(empirical_quantile(range(1999), .975), 1949)
        self.assertEqual(empirical_quantile(range(1999), .025), 49)

    def test_scale_invariance_and_paired_cost_covariance(self):
        w = np.random.default_rng(122).multinomial(200, self.counts / 200, size=1999)
        a = intervals(self.atoms, self.counts, resample_counts=w)
        scaled = self.atoms.copy(); scaled[:, 1:] *= 1e6
        b = intervals(scaled, self.counts, resample_counts=w)
        for field in ('rho', 'se_rho', 'upper_rho', 'lower_delta'):
            self.assertAlmostEqual(a[field], b[field], places=12)
        unpaired = self.atoms.copy(); unpaired[:, 2] = unpaired[::-1, 2]
        c = intervals(unpaired, self.counts, resample_counts=w)
        self.assertGreater(abs(c['se_rho'] - a['se_rho']), 1e-4)

    def test_constant_quality_is_uninformative(self):
        atoms = self.atoms.copy(); atoms[:, 0] = 0
        result = intervals(atoms, self.counts, rng=np.random.default_rng(1))
        self.assertEqual(result['quality_status'], 'variance_zero')
        self.assertEqual(result['lower_delta'], -1)

    def test_constant_ratio_is_uninformative(self):
        atoms = self.atoms.copy(); atoms[:, 1] = .83 * atoms[:, 2]
        result = intervals(atoms, self.counts, rng=np.random.default_rng(2))
        self.assertEqual(result['cost_status'], 'variance_zero')
        self.assertTrue(math.isinf(result['upper_rho']))

    def test_zero_and_weak_denominators(self):
        zero = self.atoms.copy(); zero[:, 2] = 0
        result = intervals(zero, self.counts, rng=np.random.default_rng(3))
        self.assertEqual(result['cost_status'], 'denominator_zero')
        weak = np.array([[-1, .001, 0], [0, .002, 0], [1, .003, .1]])
        result = intervals(weak, [50, 149, 1], rng=np.random.default_rng(4))
        self.assertEqual(result['cost_status'], 'denominator_weak')
        self.assertTrue(math.isinf(result['upper_rho']))

    def test_no_undefined_bootstrap_draw_is_dropped(self):
        w = np.array([[50, 100, 50], [0, 200, 0]])
        result = intervals(self.atoms, self.counts, resample_counts=w)
        self.assertEqual(result['quality_status'], 'resample_undefined')
        self.assertEqual(result['cost_status'], 'resample_undefined')
        self.assertEqual(result['undefined_quality_resamples'], 1)
        self.assertEqual(result['lower_delta'], -1)
        self.assertTrue(math.isinf(result['upper_rho']))

    def test_lower_upper_quantile_directions(self):
        w = np.array([[70, 100, 30], [60, 100, 40], [40, 100, 60], [30, 100, 70]])
        result = intervals(self.atoms, self.counts, resample_counts=w)
        self.assertLess(result['lower_delta'], result['delta'])
        self.assertGreater(result['upper_rho'], result['rho'])

    def test_invalid_pair_resampling_is_rejected(self):
        with self.assertRaises(ValueError):
            intervals(self.atoms, self.counts, resample_counts=[[50, 100, 49]])


if __name__ == '__main__':
    unittest.main()
