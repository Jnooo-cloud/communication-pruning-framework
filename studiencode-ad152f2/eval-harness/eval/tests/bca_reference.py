"""Slow BCa equation reference, stdlib only, no production imports.

Same agent as production, not independent authorship. Uses direct family deletion
and a bisection inverse normal rather than the production NormalDist inverse.
"""

import math


def normal_cdf(x):
    return math.erfc(-x/math.sqrt(2))/2


def inverse_normal(p):
    low, high = -12., 12.
    for _ in range(100):
        mid = (low+high)/2
        if normal_cdf(mid) < p:
            low = mid
        else:
            high = mid
    return (low+high)/2


def reference(rows, samples):
    def statistic(rs):
        return sum(r[1] for r in rs)/sum(r[0] for r in rs), sum(r[3] for r in rs)/sum(r[2] for r in rs)
    point = statistic(rows)
    deleted = [statistic(rows[:i]+rows[i+1:]) for i in range(len(rows))]
    results = []
    for j in range(2):
        means = [v[j] for v in deleted]
        deviations = [sum(means)/len(means)-v for v in means]
        acc = sum(v**3 for v in deviations)/(6*sum(v*v for v in deviations)**1.5)
        values = sorted(s[j] for s in samples)
        z0 = inverse_normal(sum(1 if x < point[j] else .5 if x == point[j] else 0 for x in values)/len(values))
        bounds = []
        for p in (.025, .975):
            z = z0+inverse_normal(p)
            prob = normal_cdf(z0+z/(1-acc*z))
            index = prob*(len(values)-1)
            k = int(index)
            bounds.append(values[k] if k == len(values)-1 else values[k]*(1-(index-k))+values[k+1]*(index-k))
        results.append(dict(bounds=bounds, acceleration=acc, z0=z0))
    return results
