"""Z44 studentized complete-block intervals; conditional, unvalidated candidate.

The same bootstrap count matrix applies to every column/endpoint. Centered
weighted sums preserve the Z32 standard errors. No undefined draw is discarded.
This module has no data loader, provider client, or experimental run trigger.
"""
from math import ceil, sqrt, log
from statistics import NormalDist
import numpy as np

ZERO_TOL = 32 * np.finfo(float).eps
Z975 = NormalDist().inv_cdf(.975)


def empirical_quantile(values, probability):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not 0 < probability <= 1 or np.isnan(values).any():
        raise ValueError("nonempty vector without NaN and 0 < p <= 1 required")
    index = ceil(probability * len(values)) - 1
    return float(np.partition(values, index)[index])


def _stats(a, b, weights, n, quality=False):
    """Centered sums; weights are multiplicities of complete original blocks."""
    ma = (weights @ a) / n
    if b is None:
        residual = a[None, :] - ma[:, None]
        se = np.sqrt(np.sum(weights * residual**2, axis=1) / (n*(n-1)))
        if not quality:
            se = np.where(se <= ZERO_TOL * np.max(np.abs(a)) / sqrt(n), 0., se)
        return ma, se, None, None
    mb = (weights @ b) / n
    sb = np.sqrt(np.sum(weights * (b[None, :] - mb[:, None])**2, axis=1) / (n*(n-1)))
    with np.errstate(divide="ignore", invalid="ignore"):
        point = ma / mb
        residual = a[None, :] - point[:, None]*b[None, :]
        se = np.sqrt(np.sum(weights*residual**2, axis=1) / (n*(n-1))) / mb
        scale = np.maximum(np.max(np.abs(a)), np.abs(point)*np.max(np.abs(b))) / mb
        se = np.where(se <= ZERO_TOL * scale / sqrt(n), 0., se)
    return point, se, mb, sb


def _weights_valid(weights, counts, n):
    return (weights.ndim == 2 and weights.shape[1] == len(counts) and len(weights) > 0
            and np.isfinite(weights).all() and (weights >= 0).all()
            and (weights == np.floor(weights)).all() and (weights.sum(axis=1) == n).all()
            and (weights[:, counts == 0] == 0).all())


def analyze(atoms, counts, endpoints, *, rng=None, resample_counts=None,
            bootstrap_reps=19999, batch_size=128):
    """Two-sided marginal limits; explicit weights support independent parity tests.

Endpoint numerator/denominator vectors form per-block linear contrasts. Mean
endpoints bounded by [-1,1] use the original exact quality-zero rule; unbounded
cost changes use the declared floating-point proportionality tolerance.
"""
    atoms = np.asarray(atoms, dtype=float)
    counts = np.asarray(counts)
    if (atoms.ndim != 2 or not len(atoms) or not np.isfinite(atoms).all()
            or counts.shape != (len(atoms),) or not np.isfinite(counts).all()
            or (counts < 0).any() or (counts != np.floor(counts)).any()
            or counts.sum() < 2 or type(batch_size) is not int or batch_size < 1):
        raise ValueError("finite atoms, integer multiplicities, n>=2 and positive batch required")
    counts = counts.astype(np.int64)
    n = int(counts.sum())
    if resample_counts is not None:
        explicit = np.asarray(resample_counts)
        if not _weights_valid(explicit, counts, n):
            raise ValueError("resamples must retain n complete observed blocks")
        reps = len(explicit)
    else:
        explicit = None
        if rng is None or type(bootstrap_reps) is not int or bootstrap_reps < 1:
            raise ValueError("explicit RNG and positive integer bootstrap count required")
        reps = bootstrap_reps
    if not endpoints or len({e['id'] for e in endpoints}) != len(endpoints):
        raise ValueError("nonempty, unique endpoints required")
    prepared = []
    for e in endpoints:
        if e['kind'] not in ('mean', 'ratio'):
            raise ValueError("unknown endpoint kind")
        coeff = np.asarray(e['numerator'], dtype=float)
        if coeff.shape != (atoms.shape[1],) or not np.isfinite(coeff).all():
            raise ValueError("invalid numerator")
        a = atoms @ coeff
        b = None
        if e['kind'] == 'ratio':
            dc = np.asarray(e['denominator'], dtype=float)
            if dc.shape != coeff.shape or not np.isfinite(dc).all():
                raise ValueError("invalid denominator")
            b = atoms @ dc
            if (a < 0).any() or (b < 0).any():
                raise ValueError("cost ratio requires nonnegative block costs")
            bounds = (0., float('inf'))
        else:
            bounds = tuple(e.get('bounds', (-float('inf'), float('inf'))))
            if len(bounds) != 2 or bounds[0] > bounds[1] or np.isnan(bounds).any():
                raise ValueError("invalid parameter bounds")
            if (a < bounds[0]).any() or (a > bounds[1]).any():
                raise ValueError("block contrast exceeds declared bounds")
        quality = e['kind'] == 'mean' and bounds == (-1, 1)
        point, se, mb, sb = _stats(a, b, counts[None, :], n, quality)
        estimate, original_se = float(point[0]), float(se[0])
        status = 'ok'
        if b is not None and mb[0] <= 0:
            status = 'denominator_zero'
        elif b is not None and mb[0] <= Z975*sb[0]:
            status = 'denominator_weak'
        elif original_se == 0 or not np.isfinite(original_se):
            status = 'variance_zero'
        prepared.append(dict(id=e['id'], a=a, b=b, quality=quality,
                             bounds=bounds, estimate=estimate, se=original_se,
                             status=status, pivots=np.empty(reps), bad=0))
    for start in range(0, reps, batch_size):
        stop = min(start+batch_size, reps)
        w = (explicit[start:stop] if explicit is not None else
             rng.multinomial(n, counts/n, size=stop-start))
        for e in prepared:
            point, se, mb, _ = _stats(e['a'], e['b'], w, n, e['quality'])
            with np.errstate(divide='ignore', invalid='ignore'):
                pivots = (point-e['estimate'])/se
            bad = ~np.isfinite(pivots)
            if mb is not None:
                bad |= mb <= 0
            e['bad'] += int(bad.sum())
            e['pivots'][start:stop] = pivots
    result = {}
    for e in prepared:
        status = e['status']
        if status == 'ok' and e['bad']:
            status = 'resample_undefined'
        lo, hi = e['bounds']
        if status == 'ok':
            lo = max(lo, e['estimate']-empirical_quantile(e['pivots'], .975)*e['se'])
            hi = min(hi, e['estimate']-empirical_quantile(e['pivots'], .025)*e['se'])
            # Cost-ratio upper bounds share the original nonnegative constraint.
            if e['b'] is not None:
                hi = max(0., hi)
        result[e['id']] = dict(estimate=e['estimate'], se=e['se'], lower=lo, upper=hi,
                              status=status, undefined_resamples=e['bad'])
    return dict(n=n, bootstrap_reps=reps, endpoints=result,
                status='technical_candidate_not_study_release')


def hoeffding(values, bounds=(-1., 1.)):
    """Declared marginal secondary-quality interval, under independent blocks."""
    values = np.asarray(values, dtype=float)
    a, b = bounds
    if (values.ndim != 1 or not len(values) or not np.isfinite(values).all()
            or not np.isfinite(bounds).all() or a >= b or (values<a).any() or (values>b).any()):
        raise ValueError('finite block values within fixed bounds required')
    mean = float(values.mean())
    radius = (b-a)*sqrt(log(40)/(2*len(values)))
    return dict(estimate=mean, lower=max(a, mean-radius), upper=min(b, mean+radius),
                radius=radius, n=len(values), simultaneous=False)


def secondary_quality(rows, template):
    """All predeclared secondary EM/F1 contrasts, with full block alignment."""
    rows=np.asarray(rows,dtype=float)
    size={'R':6,'T1':2,'T2':2,'F':4}.get(template)
    if rows.ndim!=2 or size is None or rows.shape[1]!=size or not len(rows) or not np.isfinite(rows).all() or (rows<0).any() or (rows>1).any():
        raise ValueError('complete finite quality blocks in [0,1] required')
    if template=='F':
        dq=rows[:,1]-rows[:,0];df=rows[:,3]-rows[:,2]
        return {'d_Q':hoeffding(dq),'d_F':hoeffding(df),
                'd_Q_minus_d_F':hoeffding(dq-df,(-2,2))}
    pairs=([(4,0),(4,1),(4,2),(4,3),(4,5),(5,0),(5,1),(5,2),(5,3)]
           if template=='R' else [(0,1)])
    return {f'{template}/{i:02d}':hoeffding(rows[:,a]-rows[:,b])
            for i,(a,b) in enumerate(pairs,1)}
