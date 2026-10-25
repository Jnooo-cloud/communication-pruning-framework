import itertools
import math
import statistics
import unittest

from communication_pruning.sampling import (
    expected_families, family_counts, fixed_mean_sampling_variance,
    inclusion_probability, sample_positions,
)


class SamplingTests(unittest.TestCase):
    def test_k1_positions_reproducible_distinct_complete(self):
        for sizes in ((1,), (1, 2, 4), (7, 3, 1, 1)):
            for n in range(1, sum(sizes) + 1):
                for seed in range(10):
                    positions = sample_positions(sizes, n, seed)
                    self.assertEqual(positions, sample_positions(sizes, n, seed))
                    self.assertEqual(len(set(positions)), n)
                    counts = family_counts(sizes, positions)
                    self.assertEqual(sum(counts), n)
                    self.assertTrue(all(c <= m for c, m in zip(counts, sizes)))
                    if n == sum(sizes):
                        self.assertEqual(counts, sizes)

    def test_k1_invalid_sizes_and_seeds(self):
        for sizes in ((), (0,), (-1, 2), (True,), (1.5,)):
            with self.assertRaises(ValueError):
                expected_families(sizes, 1)
        for n in (0, 4, True, 1.0):
            with self.assertRaises(ValueError):
                sample_positions((1, 2), n, 0)
        for seed in (-1, True, 1.0, "1"):
            with self.assertRaises(ValueError):
                sample_positions((1, 2), 1, seed)
        for positions in ((), (0, 0), (-1,), (3,), (True,), (1.5,)):
            with self.assertRaises(ValueError):
                family_counts((1, 2), positions)

    def test_k2_inclusion_exhaustive(self):
        sizes = (1, 2, 4)
        labels = tuple(g for g, m in enumerate(sizes) for _ in range(m))
        for n in range(1, 8):
            samples = list(itertools.combinations(range(7), n))
            # Direct set membership reference, without family_counts.
            represented = [set(labels[i] for i in s) for s in samples]
            for g, m in enumerate(sizes):
                exact = sum(g in r for r in represented) / len(samples)
                self.assertAlmostEqual(inclusion_probability(7, m, n), exact, places=14)
            self.assertAlmostEqual(expected_families(sizes, n),
                                   statistics.mean(map(len, represented)), places=14)

    def test_k2_probability_exact_combinatorial_and_extreme(self):
        for N in range(1, 20):
            for m in range(1, N + 1):
                for n in range(1, N + 1):
                    p = 1 - math.comb(N - m, n) / math.comb(N, n)
                    self.assertAlmostEqual(inclusion_probability(N, m, n), p, places=14)
        self.assertAlmostEqual(inclusion_probability(10**15, 1, 1) / 1e-15, 1)
        for args in ((0, 1, 1), (5, 0, 1), (5, 6, 1), (5, 1, 0), (5, 1, 6), (5, True, 1)):
            with self.assertRaises(ValueError):
                inclusion_probability(*args)

    def test_k2_fixed_variance_exhaustive(self):
        for values in ((-1, -1, 0, 1), (1, 1, 1), (0.01, 0.1, 2.0, 10.0)):
            for n in range(1, len(values) + 1):
                means = [statistics.mean(s) for s in itertools.combinations(values, n)]
                actual = statistics.pvariance(means)
                self.assertAlmostEqual(fixed_mean_sampling_variance(values, n), actual, places=13)
            self.assertEqual(fixed_mean_sampling_variance(values, len(values)), 0)

    def test_k2_variance_invalid(self):
        for values in ((), (1,), (1, float("nan")), (1, float("inf")), (1, True), (1, "2")):
            with self.assertRaises(ValueError):
                fixed_mean_sampling_variance(values, 1)
        for n in (0, 3, 1.5, True):
            with self.assertRaises(ValueError):
                fixed_mean_sampling_variance((1, 2), n)


if __name__ == "__main__":
    unittest.main()
