"""Finite-population covariance diagnostics; NOT a confidence-interval method.

See the prospectively secured Z13 plan. Repetition vectors must be iid,
independent of uniform task sampling without replacement. Within-vector task
covariances are allowed. Neither this module nor its estimator trains Q/F*.
"""

import numpy as np


def _integer(value, minimum, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _array(value, ndim, name):
    try:
        a = np.asarray(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be rectangular numeric data") from error
    if a.ndim != ndim or not all(a.shape) or a.dtype.kind not in 'iuf' or not np.isfinite(a).all():
        raise ValueError(f"{name} must be finite real numeric data with {ndim} dimensions")
    return a.astype(float)


def _cov_rows(rows):
    centered = rows - rows.mean(axis=0)
    return centered.T @ centered / (len(rows) - 1)


def covariance_components(means, individual_covariance_sum, ordered_cross_covariance_sum, n, repeats):
    """Oracle covariance from KNOWN finite-population moments, not observed runs.

Cross covariance is summed over ordered distinct task pairs. Individual and
cross sums must come from a valid joint outcome distribution; the summaries
alone do not suffice to check existence of that full distribution.
"""
    mu = _array(means, 2, 'means')
    N, k = mu.shape
    _integer(N, 2, 'population'); _integer(n, 2, 'sample size'); _integer(repeats, 1, 'repeats')
    if n > N:
        raise ValueError('sample exceeds population')
    matrices = []
    for name, values in [('individual sum', individual_covariance_sum), ('ordered cross sum', ordered_cross_covariance_sum)]:
        matrix = _array(values, 2, name)
        if matrix.shape != (k, k) or not np.allclose(matrix, matrix.T, rtol=1e-12, atol=1e-12):
            raise ValueError(f'{name} must be a symmetric {k} by {k} matrix')
        matrices.append(matrix)
    individual, cross = matrices
    sampling = (1 - n / N) * _cov_rows(mu) / n
    generation_individual = individual / (N * n * repeats)
    generation_cross = (n - 1) * cross / (n * N * (N - 1) * repeats)
    return dict(mean=mu.mean(axis=0), sampling=sampling,
                generation_individual=generation_individual,
                generation_cross=generation_cross,
                total=sampling + generation_individual + generation_cross)


def repetition_estimate(outcomes, population):
    """Estimate grand-mean covariance from shape (R, n, k), R>=2 and n>=2.

Same selected tasks in all repetitions. This does not identify a covariance
from a single run. Estimates are not clipped; an indefinite matrix is reported
and must not be treated as an approved interval input.
"""
    x = _array(outcomes, 3, 'outcomes')
    R, n, _ = x.shape
    _integer(population, 2, 'population')
    if R < 2 or n < 2 or n > population:
        raise ValueError('need >=2 repetitions, >=2 tasks, and population >= tasks')
    task_means = x.mean(axis=0)
    residuals = x - task_means
    A = np.einsum('rik,ril->kl', residuals, residuals) / ((R - 1) * R)
    T = _cov_rows(x.mean(axis=1)) / R
    between = _cov_rows(task_means) - (A - n * T) / (n - 1)
    sampling = (1 - n / population) * between / n
    total = sampling + T
    eig = np.linalg.eigvalsh(total)
    tolerance = 1e-12 * max(1., float(np.abs(total).max()))
    return dict(mean=task_means.mean(axis=0), sampling=sampling, generation=T,
                total=total, minimum_eigenvalue=float(eig.min()),
                status='indefinite' if eig.min() < -tolerance else 'moment_estimate_not_interval')
