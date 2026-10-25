"""Experimental paired family bootstrap. Not an approved study analysis.

Equal-probability sampling of independent families, task-weighted estimands.
No sampling weights, finite-population correction, or within-task resampling.
"""

from collections import defaultdict
from dataclasses import dataclass
import math
import random

from .evaluation import paired_task_rows


@dataclass(frozen=True)
class FamilyTotal:
    family_id: str
    tasks: int
    quality_sum: float
    fixed_sum: float
    adaptive_sum: float


def family_totals(fixed, adaptive, *, expected_slots, phase):
    rows = paired_task_rows(fixed, adaptive, expected_slots=expected_slots, phase=phase)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["family_id"]].append(row)
    return tuple(FamilyTotal(f, len(rs), math.fsum(r["quality_difference"] for r in rs),
                             math.fsum(float(r["cost_fixed"]) for r in rs),
                             math.fsum(float(r["cost_adaptive"]) for r in rs))
                 for f, rs in sorted(grouped.items()))


def validate_totals(totals):
    if len(totals) < 2 or len({t.family_id for t in totals}) != len(totals):
        raise ValueError("at least two distinct families required")
    for t in totals:
        if (not isinstance(t.family_id, str) or not t.family_id or type(t.tasks) is not int
                or t.tasks < 1 or any(not math.isfinite(v) for v in
                                     (t.quality_sum, t.fixed_sum, t.adaptive_sum))
                or abs(t.quality_sum) > t.tasks or min(t.fixed_sum, t.adaptive_sum) < 0):
            raise ValueError("invalid family sufficient statistics")
    if math.fsum(t.fixed_sum for t in totals) <= 0:
        raise ValueError("zero reference cost; ratio undefined")


def estimate(totals):
    return (math.fsum(t.quality_sum for t in totals) / sum(t.tasks for t in totals),
            math.fsum(t.adaptive_sum for t in totals) / math.fsum(t.fixed_sum for t in totals))


def resampled_estimates(totals, indices, *, backend="stdlib"):
    """Shared, explicit family-index draws; undefined draws are not dropped."""
    totals = tuple(totals)
    validate_totals(totals)
    g = len(totals)
    if backend == "numpy":
        import numpy as np
        ix = np.asarray(indices)
        if ix.ndim != 2 or ix.shape[1] != g or not len(ix) or ix.dtype.kind not in "iu" or np.any(ix < 0) or np.any(ix >= g):
            raise ValueError("invalid family draws")
        values = np.array([(t.tasks, t.quality_sum, t.fixed_sum, t.adaptive_sum) for t in totals])
        sums = values[ix].sum(axis=1)
        if np.any(sums[:, 2] <= 0):
            raise ValueError("undefined bootstrap cost ratio; no draw deletion")
        return list(zip((sums[:, 1] / sums[:, 0]).tolist(), (sums[:, 3] / sums[:, 2]).tolist()))
    if backend != "stdlib":
        raise ValueError("unknown backend")
    output = []
    for row in indices:
        if len(row) != g or any(type(i) is not int or i < 0 or i >= g for i in row):
            raise ValueError("invalid family draws")
        sampled = [totals[i] for i in row]
        if math.fsum(t.fixed_sum for t in sampled) <= 0:
            raise ValueError("undefined bootstrap cost ratio; no draw deletion")
        output.append(estimate(sampled))
    if not output:
        raise ValueError("empty draws")
    return output


def quantile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def interval_report(totals, samples, *, method):
    validate_totals(totals)
    if method not in {"percentile", "basic"} or len(samples) < 2:
        raise ValueError("supported method and at least two draws required")
    if any(len(s) != 2 or not all(math.isfinite(v) for v in s) for s in samples):
        raise ValueError("invalid resampled estimates")
    point = estimate(totals)
    bounds, degenerate = [], []
    for j in range(2):
        values = [s[j] for s in samples]
        low, high = quantile(values, .025), quantile(values, .975)
        degenerate.append(max(values) - min(values) <= 1e-12)
        if method == "basic":
            low, high = 2 * point[j] - high, 2 * point[j] - low
        bounds.append([low, high])
    return dict(method=method, quality_difference=point[0], cost_ratio=point[1],
                quality_bounds=bounds[0], cost_ratio_bounds=bounds[1],
                quality_degenerate=degenerate[0], cost_degenerate=degenerate[1],
                assessable=not any(degenerate), tasks=sum(t.tasks for t in totals),
                families=len(totals), bootstrap_draws=len(samples),
                status="experimental_not_approved_for_study", one_sided_level=.975)


def hypothetical_decision(report, *, quality_margin, cost_ratio_limit):
    if (not math.isfinite(quality_margin) or not 0 < quality_margin < 1
            or not math.isfinite(cost_ratio_limit) or not 0 < cost_ratio_limit < 1):
        raise ValueError("explicit finite hypothetical thresholds required")
    if not report["assessable"]:
        return None
    return (report["quality_bounds"][0] > -quality_margin
            and report["cost_ratio_bounds"][1] < cost_ratio_limit)


def paired_bootstrap(fixed, adaptive, *, expected_slots, phase, draws, seed, method):
    if type(draws) is not int or draws < 2 or type(seed) is not int:
        raise ValueError("explicit draw count and integer seed required")
    totals = family_totals(fixed, adaptive, expected_slots=expected_slots, phase=phase)
    validate_totals(totals)
    rng = random.Random(seed)
    g = len(totals)
    samples = resampled_estimates(totals, ([rng.randrange(g) for _ in range(g)] for _ in range(draws)))
    return dict(interval_report(totals, samples, method=method), seed=seed, phase=phase)
