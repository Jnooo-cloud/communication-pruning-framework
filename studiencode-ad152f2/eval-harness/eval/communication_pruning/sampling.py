"""Anonymous finite task sampling diagnostics, not a study interval or manifest.

Family sizes alone carry no benchmark content and cannot authorize content access.
The finite-population variance applies to fixed values, not generation noise.
"""

import math
import random
import statistics


def validate_sizes(sizes, n):
    sizes = tuple(sizes)
    if not sizes or any(type(m) is not int or m <= 0 for m in sizes):
        raise ValueError("positive integer family sizes required")
    if type(n) is not int or not 1 <= n <= sum(sizes):
        raise ValueError("sample size outside finite population")
    return sizes


def inclusion_probability(population, family_size, n):
    if any(type(x) is not int for x in (population, family_size, n)):
        raise ValueError("integer sizes required")
    if not 1 <= family_size <= population or not 1 <= n <= population:
        raise ValueError("invalid population, family or sample size")
    if n > population - family_size:
        return 1.0
    # Choose the shorter of equivalent absence products, using log1p/expm1
    # to retain precision when inclusion is rare.
    small, other = min(family_size, n), max(family_size, n)
    return -math.expm1(math.fsum(math.log1p(-other / (population - j))
                                for j in range(small)))


def expected_families(sizes, n):
    sizes = validate_sizes(sizes, n)
    population = sum(sizes)
    return math.fsum(inclusion_probability(population, m, n) for m in sizes)


def sample_positions(sizes, n, seed):
    sizes = validate_sizes(sizes, n)
    if type(seed) is not int or seed < 0:
        raise ValueError("nonnegative integer seed required")
    return tuple(random.Random(seed).sample(range(sum(sizes)), n))


def family_counts(sizes, positions):
    sizes = validate_sizes(sizes, 1)
    positions = tuple(positions)
    population = sum(sizes)
    if (not positions or any(type(i) is not int or not 0 <= i < population for i in positions)
            or len(set(positions)) != len(positions)):
        raise ValueError("distinct valid task positions required")
    labels = tuple(g for g, m in enumerate(sizes) for _ in range(m))
    counts = [0] * len(sizes)
    for i in positions:
        counts[labels[i]] += 1
    return tuple(counts)


def fixed_mean_sampling_variance(values, n):
    values = tuple(values)
    if (len(values) < 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                              or not math.isfinite(v) for v in values)):
        raise ValueError("at least two finite numeric fixed values required")
    if type(n) is not int or not 1 <= n <= len(values):
        raise ValueError("sample size outside finite population")
    return (1 - n / len(values)) * statistics.variance(values) / n
