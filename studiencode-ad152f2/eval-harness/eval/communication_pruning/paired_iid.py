"""Isolated Z33 candidate, conditional on iid paired draws; not a study release.

Protocol: project/dsr/Z32-HAUPTVERGLEICH-PLAN.md, sections 5--6.
Zero SE tolerance is 32 machine eps times the largest residual operand,
divided by sqrt(n). This only handles roundoff in exact proportionality.
No bootstrap draw is discarded. A single undefined pivot blocks its endpoint.
"""
from math import ceil, sqrt
from statistics import NormalDist

import numpy as np

BOOTSTRAP_REPS = 1999
ZERO_TOL = 32 * np.finfo(float).eps
Z975 = NormalDist().inv_cdf(0.975)


def _stats(atoms, weights):
    """Centered weighted sums; each row of weights describes n complete pairs."""
    n = weights.sum(axis=1)
    d, a, b = atoms.T
    md = (weights @ d) / n
    ma = (weights @ a) / n
    mb = (weights @ b) / n
    sd = np.sqrt((weights * (d - md[:, None]) ** 2).sum(axis=1) / (n * (n - 1)))
    sb = np.sqrt((weights * (b - mb[:, None]) ** 2).sum(axis=1) / (n * (n - 1)))
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.divide(ma, mb, out=np.full_like(ma, np.nan), where=mb > 0)
        residual = a - ratio[:, None] * b
        sr = np.sqrt((weights * residual ** 2).sum(axis=1) / (n * (n - 1))) / mb
        scale = np.maximum(np.abs(a).max(), np.abs(ratio) * np.abs(b).max()) / mb
        sr = np.where(sr <= ZERO_TOL * scale / np.sqrt(n), 0.0, sr)
    return md, ratio, sd, sr, mb, sb


def empirical_quantile(values, probability):
    """Inverse empirical CDF, one-based rank ceil(p * number of draws)."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not 0 < probability <= 1:
        raise ValueError("nonempty vector and 0 < probability <= 1 required")
    return float(np.partition(values, ceil(probability * len(values)) - 1)[ceil(probability * len(values)) - 1])


def intervals(atoms, counts, *, rng=None, resample_counts=None, bootstrap_reps=BOOTSTRAP_REPS):
    """Return one-sided 97.5% candidate limits for mean D and mean A / mean B.

    atoms has columns D, A, B. Integer counts are multiplicities of whole pairs.
    Explicit resample counts permit independent row/reference parity tests.
    """
    atoms = np.asarray(atoms, dtype=float)
    counts = np.asarray(counts)
    if (atoms.ndim != 2 or atoms.shape[1] != 3 or counts.shape != (len(atoms),)
            or not np.isfinite(atoms).all() or not np.isfinite(counts).all()
            or (counts < 0).any() or (counts != np.floor(counts)).any()
            or counts.sum() < 2 or (np.abs(atoms[:, 0]) > 1).any()
            or (atoms[:, 1:] < 0).any()):
        raise ValueError("finite paired atoms, nonnegative costs, integer counts and n >= 2 required")
    counts = counts.astype(np.int64)
    n = int(counts.sum())
    if resample_counts is None:
        if rng is None:
            raise ValueError("explicit RNG required")
        if bootstrap_reps < 1:
            raise ValueError("positive bootstrap count required")
        weights = rng.multinomial(n, counts / n, size=bootstrap_reps)
    else:
        weights = np.asarray(resample_counts)
        if (weights.ndim != 2 or weights.shape[1] != len(atoms) or not len(weights)
                or not np.isfinite(weights).all() or (weights < 0).any()
                or (weights != np.floor(weights)).any() or (weights.sum(axis=1) != n).any()
                or (weights[:, counts == 0] != 0).any()):
            raise ValueError("each resample must contain n whole original pairs")
    original = _stats(atoms, counts[None, :])
    delta, rho, se_delta, se_rho, mean_b, se_b = (float(v[0]) for v in original)
    bd, br, bsd, bsr, bmb, _ = _stats(atoms, weights)
    with np.errstate(divide="ignore", invalid="ignore"):
        td = (bd - delta) / bsd
        tr = (br - rho) / bsr
    bad_d = int((~np.isfinite(td)).sum())
    bad_r = int((~np.isfinite(tr) | (bmb <= 0)).sum())
    quality_status = "ok"
    if se_delta == 0 or not np.isfinite(se_delta):
        quality_status = "variance_zero"
    elif bad_d:
        quality_status = "resample_undefined"
    cost_status = "ok"
    if mean_b <= 0:
        cost_status = "denominator_zero"
    elif mean_b <= Z975 * se_b:
        cost_status = "denominator_weak"
    elif se_rho == 0 or not np.isfinite(se_rho):
        cost_status = "variance_zero"
    elif bad_r:
        cost_status = "resample_undefined"
    lower = -1.0 if quality_status != "ok" else max(-1.0, delta - empirical_quantile(td, .975) * se_delta)
    upper = float("inf") if cost_status != "ok" else max(0.0, rho - empirical_quantile(tr, .025) * se_rho)
    return dict(n=n, delta=delta, rho=rho, se_delta=se_delta, se_rho=se_rho,
                lower_delta=lower, upper_rho=upper, quality_status=quality_status,
                cost_status=cost_status, undefined_quality_resamples=bad_d,
                undefined_cost_resamples=bad_r, bootstrap_reps=len(weights),
                success=bool(lower > -.03 and upper < .90))
