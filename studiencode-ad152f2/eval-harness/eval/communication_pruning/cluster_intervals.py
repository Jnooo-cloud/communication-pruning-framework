"""Z14 experimental family-jackknife/t/Fieller candidate, not study approval.

One row per distinct uniformly sampled task: paired EM difference, Q cost,
F* cost. Independent families are an approximation requiring validation under
the actual sampling design. No global finite-population correction is applied.
"""

from functools import lru_cache
import math
import numpy as np
from scipy.stats import t as student_t


def _inputs(outcomes, family_ids):
    x = np.asarray(outcomes)
    labels = np.asarray(family_ids)
    if (x.ndim != 2 or x.shape[1:] != (3,) or len(x) < 2 or x.dtype.kind not in 'iuf'
            or not np.isfinite(x).all()):
        raise ValueError('need finite real n-by-3 outcomes with n >= 2')
    if (labels.ndim != 1 or len(labels) != len(x) or labels.dtype.kind not in 'iuUS'
            or (labels.dtype.kind in 'US' and np.any(labels == ''))):
        raise ValueError('one nonempty string or integer family ID per task required')
    x = x.astype(float)
    if not np.isin(x[:, 0], [-1, 0, 1]).all() or np.any(x[:, 1:] < 0) or x[:, 2].mean() <= 0:
        raise ValueError('EM differences must be -1/0/1, costs nonnegative, mean F* cost positive')
    _, inverse, counts = np.unique(labels, return_inverse=True, return_counts=True)
    return x, inverse, counts


def _moments(x, inverse, counts):
    G, n = len(counts), len(x)
    if G < 2:
        raise ValueError('need at least two families to delete one')
    sums = np.stack([np.bincount(inverse, weights=x[:, k], minlength=G) for k in range(3)], axis=1)
    deleted = (x.sum(axis=0) - sums) / (n - counts[:, None])
    centered = deleted - deleted.mean(axis=0)
    covariance = (G - 1) / G * (centered.T @ centered)
    return x.mean(axis=0), covariance


def cluster_moments(outcomes, family_ids):
    """Task-weighted mean and centered delete-family covariance, no ratio jackknife."""
    x, inverse, counts = _inputs(outcomes, family_ids)
    return _moments(x, inverse, counts)


@lru_cache(maxsize=4096)
def _critical(families):
    return float(student_t.ppf(.975, families - 1))


def fieller_upper(a, b, covariance, critical):
    """Upper one-sided inverted-t bound; None explicitly means no finite bound.

Covariance order is (Q, F*). A weak denominator or unobserved contrast
variation cannot generate a candidate success. Scale before evaluating the
quadratic to keep dollar and micro-dollar units equivalent.
"""
    v = np.asarray(covariance, dtype=float)
    if (v.shape != (2, 2) or not np.isfinite(v).all() or not all(math.isfinite(z) for z in (a, b, critical))
            or a < 0 or b <= 0 or critical <= 0):
        raise ValueError('invalid Fieller moments')
    scale = max(a, b, math.sqrt(float(np.abs(v).max())))
    a, b, v = a / scale, b / scale, v / scale / scale
    if not np.allclose(v, v.T, atol=1e-14, rtol=1e-12) or np.linalg.eigvalsh(v).min() < -1e-12 * max(float(np.abs(v).max()), 1e-300):
        raise ValueError('covariance must be symmetric positive semidefinite')
    ratio = a / b
    terms = (v[0, 0], -2 * ratio * v[0, 1], ratio * ratio * v[1, 1])
    if sum(terms) <= 1e-12 * max(sum(abs(z) for z in terms), 1e-300):
        return None, 'unobserved_cost_contrast_variation'
    t2 = critical * critical
    A = b * b - t2 * v[1, 1]
    if A <= 0:
        return None, 'weak_denominator'
    H = a * b - t2 * v[0, 1]; C = a * a - t2 * v[0, 0]
    discriminant = H * H - A * C
    if discriminant <= 0:
        return None, 'unresolved_quadratic'
    upper = (H + math.sqrt(discriminant)) / A
    if not math.isfinite(upper) or upper < ratio:
        return None, 'unresolved_upper_branch'
    return float(upper), 'finite_candidate'


def candidate_intervals(outcomes, family_ids, population):
    """Experimental nominal 97.5% one-sided bounds and D-050 conjunction.

This API cannot establish cross-family independence or real study approval.
Population is checked for SRS feasibility, never used to erase fresh noise.
"""
    x, inverse, counts = _inputs(outcomes, family_ids)
    if isinstance(population, (bool, np.bool_)) or not isinstance(population, (int, np.integer)) or population < len(x):
        raise ValueError('integer population >= observed task count required')
    mean = x.mean(axis=0); G = len(counts)
    result = dict(mean=mean.tolist(), quality_lower=-1., cost_upper=None,
                  quality_reason='too_few_families', cost_reason='too_few_families',
                  families=G, candidate_joint_pass=False, study_approved=False)
    if G < 30:
        return result
    mean, covariance = _moments(x, inverse, counts)
    critical = _critical(G)
    if covariance[0, 0] > 1e-24:
        result.update(quality_lower=max(-1., float(mean[0] - critical * math.sqrt(covariance[0, 0]))),
                      quality_reason='finite_candidate')
    else:
        result['quality_reason'] = 'unobserved_quality_variation'
    upper, reason = fieller_upper(mean[1], mean[2], covariance[1:, 1:], critical)
    result.update(cost_upper=upper, cost_reason=reason)
    result['candidate_joint_pass'] = bool(result['quality_lower'] > -.03 and upper is not None and upper < .90)
    return result
