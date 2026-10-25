"""Experimental BCa on paired family totals; see Z11-PLAN, not study approval.

Formula checked against SciPy 1.16.2 _bca_interval and _percentile_of_score.
Independent implementation of the single-sample (whole-family) equations.
"""

import math
import random
from statistics import NormalDist

from .inference import estimate, family_totals, quantile, resampled_estimates, validate_totals


def family_jackknife(totals):
    totals = tuple(totals)
    validate_totals(totals)
    if len(totals) < 3:
        raise ValueError("BCa requires at least three families")
    n = sum(t.tasks for t in totals)
    q = math.fsum(t.quality_sum for t in totals)
    f = math.fsum(t.fixed_sum for t in totals)
    a = math.fsum(t.adaptive_sum for t in totals)
    if not all(math.isfinite(v) for v in (q, f, a)):
        raise ValueError("nonfinite aggregate")
    output = []
    for t in totals:
        denominator = f-t.fixed_sum
        if denominator <= 0:
            raise ValueError("undefined leave-one-family-out reference cost")
        row = ((q-t.quality_sum)/(n-t.tasks), (a-t.adaptive_sum)/denominator)
        if not all(math.isfinite(v) for v in row):
            raise ValueError("nonfinite jackknife estimate")
        output.append(row)
    return tuple(output)


def _component(point, values, jackknife):
    result = dict(bounds=None, reason=None, z0=None, acceleration=None,
                  probabilities=None, tail_resolution_warning=False)
    if max(values)-min(values) <= 1e-12:
        return dict(result, reason="degenerate_bootstrap")
    b = (sum(v < point for v in values)+.5*sum(v == point for v in values))/len(values)
    if not 0 < b < 1:
        return dict(result, reason="infinite_bias_correction")
    mean = math.fsum(jackknife)/len(jackknife)
    u = [mean-x for x in jackknife]
    scale = max(abs(x) for x in u)
    if scale == 0:
        return dict(result, reason="degenerate_jackknife")
    # Scale cancels analytically; this avoids cubing tiny or huge deviations.
    u = [x/scale for x in u]
    acceleration = math.fsum(x**3 for x in u)/(6*math.fsum(x*x for x in u)**1.5)
    normal = NormalDist()
    z0 = normal.inv_cdf(b)
    result.update(z0=z0, acceleration=acceleration)
    probabilities = []
    for p in (.025, .975):
        z = z0+normal.inv_cdf(p)
        denominator = 1-acceleration*z
        if denominator <= 0 or not math.isfinite(denominator):
            return dict(result, reason="invalid_bca_transform")
        probabilities.append(normal.cdf(z0+z/denominator))
    if not 0 <= probabilities[0] < probabilities[1] <= 1:
        return dict(result, reason="invalid_bca_quantiles", probabilities=probabilities)
    resolution = 1/(len(values)+1)
    warning = probabilities[0] < resolution or probabilities[1] > 1-resolution
    return dict(result, bounds=[quantile(values, p) for p in probabilities],
                probabilities=probabilities, tail_resolution_warning=warning,
                reason="tail_resolution_warning" if warning else None)


def bca_report(totals, samples):
    totals = tuple(totals)
    validate_totals(totals)
    if len(totals) < 3 or len(samples) < 2:
        raise ValueError("at least three families and two draws required")
    if any(len(s) != 2 or not all(math.isfinite(v) for v in s) for s in samples):
        raise ValueError("invalid resampled estimates")
    point = estimate(totals)
    try:
        jack = family_jackknife(totals)
    except ValueError as error:
        components = [dict(bounds=None, reason=str(error), z0=None, acceleration=None,
                           probabilities=None, tail_resolution_warning=False) for _ in range(2)]
    else:
        components = [_component(point[j], [s[j] for s in samples], [r[j] for r in jack]) for j in range(2)]
    return dict(method="bca", quality_difference=point[0], cost_ratio=point[1],
                quality_bounds=components[0]["bounds"], cost_ratio_bounds=components[1]["bounds"],
                assessable=all(c["reason"] is None for c in components),
                components=dict(quality=components[0], cost=components[1]),
                tasks=sum(t.tasks for t in totals), families=len(totals), bootstrap_draws=len(samples),
                one_sided_level=.975, status="experimental_not_approved_for_study")


def paired_bca(fixed, adaptive, *, expected_slots, phase, draws, seed):
    if type(draws) is not int or draws < 2 or type(seed) is not int:
        raise ValueError("explicit integer draw count and seed required")
    totals = family_totals(fixed, adaptive, expected_slots=expected_slots, phase=phase)
    validate_totals(totals)
    if len(totals) < 3:
        raise ValueError("BCa requires at least three families")
    rng = random.Random(seed)
    g = len(totals)
    samples = resampled_estimates(totals, ([rng.randrange(g) for _ in range(g)] for _ in range(draws)))
    return dict(bca_report(totals, samples), seed=seed, phase=phase)
