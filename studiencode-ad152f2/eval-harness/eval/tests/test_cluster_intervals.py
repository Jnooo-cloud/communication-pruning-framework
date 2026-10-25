"""Direct deletion and numerical test inversion, separate from candidate algebra."""

import unittest
import numpy as np
from scipy.optimize import brentq
from scipy.stats import t
from communication_pruning.cluster_intervals import candidate_intervals, cluster_moments, fieller_upper


class ClusterIntervalTests(unittest.TestCase):
    def fixture(self):
        labels = np.repeat(np.arange(40), np.arange(40) % 5 + 1)
        i = np.arange(len(labels))
        return np.stack((i % 3 - 1, .2 + i % 7, 1. + i % 11), axis=1), labels

    def test_direct_deletion_reference(self):
        x, labels = self.fixture(); mean, cov = cluster_moments(x, labels)
        unique = sorted(set(labels)); deleted = []
        for family in unique:
            remaining = [row for row, label in zip(x, labels) if label != family]
            deleted.append([sum(row[k] for row in remaining) / len(remaining) for k in range(3)])
        center = [sum(row[k] for row in deleted) / len(unique) for k in range(3)]
        reference = [[(len(unique) - 1) / len(unique) * sum((r[k] - center[k]) * (r[l] - center[l]) for r in deleted)
                      for l in range(3)] for k in range(3)]
        np.testing.assert_allclose(cov, reference, rtol=0, atol=1e-12)
        np.testing.assert_allclose(mean, x.mean(axis=0), atol=1e-12)
        self.assertFalse(np.allclose(mean, np.mean([x[labels == g].mean(axis=0) for g in unique], axis=0)))
        self.assertGreaterEqual(np.linalg.eigvalsh(cov).min(), -1e-12)

    def test_fieller_direct_inversion(self):
        for df in (29, 99, 534):
            critical = t.ppf(.975, df)
            for cov in (np.diag([.02, .03]), np.array([[.03, .012], [.012, .01]]), np.array([[.03, 0], [0, 0]])):
                a, b = .8, 1.2
                bound, status = fieller_upper(a, b, cov, critical)
                def equation(r):
                    return a - r * b + critical * np.sqrt(np.array([1, -r]) @ cov @ np.array([1, -r]))
                root = brentq(equation, a / b, 100., xtol=1e-13)
                self.assertEqual(status, 'finite_candidate')
                self.assertAlmostEqual(bound / root, 1., places=10)

    def test_invariance_and_census(self):
        x, labels = self.fixture(); n = len(x)
        a = candidate_intervals(x, labels, n)
        b = candidate_intervals(x[::-1], [f'family-{g}' for g in labels[::-1]], n * 2)
        for key in ('quality_lower', 'cost_upper'):
            self.assertAlmostEqual(a[key], b[key], places=11)
        for scale in (1e-8, 1e8):
            scaled = x.copy(); scaled[:, 1:] *= scale
            c = candidate_intervals(scaled, labels, n)
            self.assertAlmostEqual(a['cost_upper'], c['cost_upper'], places=10)
        self.assertLess(a['quality_lower'], a['mean'][0])
        self.assertGreater(a['cost_upper'], a['mean'][1] / a['mean'][2])

    def test_safety_boundaries(self):
        upper, reason = fieller_upper(.8, 1., np.diag([.1, 1.]), 2.)
        self.assertIsNone(upper); self.assertEqual(reason, 'weak_denominator')
        x = np.array([[0, 1, 2]] * 40, dtype=float)
        r = candidate_intervals(x, np.arange(40), 50)
        self.assertEqual(r['quality_lower'], -1); self.assertIsNone(r['cost_upper']); self.assertFalse(r['candidate_joint_pass'])
        x, labels = self.fixture()
        r = candidate_intervals(x, labels % 12, len(x))
        self.assertEqual(r['cost_reason'], 'too_few_families'); self.assertFalse(r['candidate_joint_pass'])
        r = candidate_intervals(x, np.zeros(len(x), dtype=int), len(x))
        self.assertFalse(r['candidate_joint_pass'])

    def test_invalid_inputs(self):
        x, labels = self.fixture()
        for bad, ids, N in [(x[:1], labels[:1], 2), (x[:, :2], labels, 200), (x, labels[:-1], 200),
                            (x, labels, len(x)-1), (x, labels, True), (x, labels, 200.5),
                            (x, labels.astype(bool), 200), (x.astype(str), labels, 200),
                            (np.full_like(x, np.nan), labels, 200)]:
            with self.assertRaises(ValueError): candidate_intervals(bad, ids, N)
        for column, value in [(0, .5), (1, -1), (2, -1)]:
            bad = x.copy(); bad[0, column] = value
            with self.assertRaises(ValueError): candidate_intervals(bad, labels, 200)
        with self.assertRaises(ValueError): fieller_upper(.8, 1., [[1, 2], [2, 1]], 2.)
        with self.assertRaises(ValueError): fieller_upper(.8, 1., [[1, 0], [2, 1]], 2.)

    def test_strict_joint_rule(self):
        # A comfortably positive-quality, cheap case only verifies the rule;
        # it is not evidence about real Q performance.
        x = np.array([[1 if i % 2 else 0, 1 + (i % 3) * .1, 3 + (i % 5) * .1] for i in range(300)])
        result = candidate_intervals(x, np.arange(300), 400)
        self.assertEqual(result['candidate_joint_pass'], result['quality_lower'] > -.03 and result['cost_upper'] < .9)
        self.assertTrue(result['candidate_joint_pass']); self.assertFalse(result['study_approved'])


if __name__ == '__main__':
    unittest.main()
