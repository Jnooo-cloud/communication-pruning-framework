"""Z13: direct joint-state enumeration, boundary cases, and input contracts."""

from itertools import combinations, product
import unittest
import numpy as np
from communication_pruning.finite_uncertainty import covariance_components, repetition_estimate


class FiniteUncertaintyTests(unittest.TestCase):
    def test_joint_enumeration(self):
        # Reference calculates every outcome probability and centered product;
        # it does not call the analytical covariance decomposition.
        atoms = np.array([[[0, 1], [1, 3], [-1, 2]],
                          [[1, 2], [-1, 1], [0, 4]],
                          [[0, 4], [0, 2], [1, 1]]], dtype=float)
        p = np.array([.25, .5, .25])
        mu = np.einsum('l,lik->ik', p, atoms)
        joint = np.zeros((3, 3, 2, 2))
        for probability, atom in zip(p, atoms):
            for i, j in product(range(3), repeat=2):
                joint[i, j] += probability * np.outer(atom[i] - mu[i], atom[j] - mu[j])
        W = sum(joint[i, i] for i in range(3))
        B = sum(joint[i, j] for i, j in product(range(3), repeat=2) if i != j)
        for n, R in product((2, 3), (1, 2)):
            with self.subTest(n=n, R=R):
                selections = list(combinations(range(3), n))
                expected_mean = np.zeros(2); covariance = np.zeros((2, 2)); estimated = covariance.copy()
                for selected in selections:
                    for states in product(range(3), repeat=R):
                        probability = np.prod(p[list(states)]) / len(selections)
                        x = atoms[list(states)][:, selected, :]
                        mean = x.mean(axis=(0, 1)); delta = mean - mu.mean(axis=0)
                        expected_mean += probability * mean
                        covariance += probability * np.outer(delta, delta)
                        if R >= 2:
                            estimated += probability * repetition_estimate(x, 3)['total']
                oracle = covariance_components(mu, W, B, n, R)
                np.testing.assert_allclose(expected_mean, oracle['mean'], atol=1e-12, rtol=0)
                np.testing.assert_allclose(covariance, oracle['total'], atol=1e-12, rtol=0)
                if R >= 2:
                    np.testing.assert_allclose(estimated, covariance, atol=1e-12, rtol=0)

    def test_census_keeps_fresh_noise(self):
        result = covariance_components([[0], [1]], [[2]], [[0]], 2, 1)
        np.testing.assert_array_equal(result['sampling'], [[0]])
        self.assertEqual(result['total'][0, 0], .5)
        repeated = repetition_estimate([[[0], [1]], [[1], [2]]], 2)
        np.testing.assert_allclose(repeated['total'], repeated['generation'])
        self.assertGreater(repeated['total'][0, 0], 0)

    def test_repetition_reduces_only_generation(self):
        one = covariance_components([[0], [1], [2]], [[3]], [[1]], 2, 1)
        three = covariance_components([[0], [1], [2]], [[3]], [[1]], 2, 3)
        np.testing.assert_array_equal(one['sampling'], three['sampling'])
        for key in ('generation_individual', 'generation_cross'):
            np.testing.assert_allclose(one[key], three[key] * 3)

    def test_negative_estimate_is_preserved(self):
        result = repetition_estimate([[[1], [0]], [[0], [1]]], 4)
        self.assertEqual(result['status'], 'indefinite')
        self.assertLess(result['total'][0, 0], 0)

    def test_observed_invalid_inputs(self):
        valid = np.zeros((3, 2, 3))
        for x, N in [(valid[:1], 3), (valid[:, :1], 3), (valid, 1), (valid, 2.5), (valid, True),
                     (valid[0], 3), ([], 3), (valid.astype(bool), 3),
                     (np.full_like(valid, np.nan), 3), (np.full_like(valid, np.inf), 3),
                     (valid.astype(str), 3), (valid.astype(complex), 3)]:
            with self.subTest(shape=np.shape(x), N=N), self.assertRaises(ValueError):
                repetition_estimate(x, N)

    def test_oracle_invalid_inputs(self):
        valid = ([[0], [1]], [[1]], [[0]], 2, 1)
        for index, value in [(0, [[0]]), (0, [[float('nan')], [1]]), (1, [[1, 2]]),
                             (2, [[float('inf')]]), (3, True), (3, 1), (3, 3), (4, 0), (4, 1.5)]:
            args = list(valid); args[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                covariance_components(*args)
        with self.assertRaises(ValueError):
            covariance_components([[0, 1], [1, 2]], [[1, 2], [0, 1]], np.zeros((2, 2)), 2, 1)


if __name__ == '__main__':
    unittest.main()
