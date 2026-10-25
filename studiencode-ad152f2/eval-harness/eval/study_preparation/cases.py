"""Frozen Z44 synthetic cases; no model calls, empirical data or calibration.

Sources: METHODEN-UND-INFORMATION.md sections 2--5 and Z32 section 6.
Each generated row is one complete block. Global controls alone share a state
across rows. Exact means use rational finite-factor expectations, not samples.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import hashlib
import math

import numpy as np


SEED_BASIS = "SV-METHODEN-2026-09-16-v1"
MAIN_N = 9040
SECONDARY_N = 2952
REPETITIONS = 10000
CONTROL_REPETITIONS = 2000
BOOTSTRAPS = 19999
B = Fraction(3, 2500)
METHODS_SHA256 = "c316809305d5eeef11ec9406ed474e6bb0058c47716130737627f8ce8e47623d"
Z32_SHA256 = "927aa7ee09d9c842c61709a923db8f0cd2b0b184ead86f871e2b9345694cf9ce"

_PRIMARY = {
    "R1": ("-0.03", "0.80"),
    "R2": ("0", "0.90"),
    "R3": ("-0.03", "0.90"),
    "R4": ("-0.03", "0.90"),
    "R5": ("-0.03", "0.90"),
    "R6": ("-0.04", "0.80"),
    "R7": ("0", "1"),
    "R8": ("0", "0.80"),
    "P1": ("-0.03", "0.90"),
    "P2": ("-0.06", "1.10"),
    "P3": ("0", "0.90"),
}
_COLUMNS = {
    "P": ["D", "A", "B"],
    "R": ["S", "S-k", "D", "Z", "Q", "F"],
    "T1": ["Q-ST", "Q-TF"],
    "T2": ["Q-ST", "Q-TF"],
    "F": ["Qc", "Qf", "Fc", "Ff"],
}
_REFERENCE_PAIRS = [(4, 0), (4, 1), (4, 2), (4, 3), (4, 5),
                    (5, 0), (5, 1), (5, 2), (5, 3)]


def _f(value) -> Fraction:
    return value if isinstance(value, Fraction) else Fraction(str(value))


def _finite(name, values, probabilities, *, scope="block"):
    return {"name": name, "scope": scope,
            "values": [str(_f(x)) for x in values],
            "probabilities": [str(_f(p)) for p in probabilities]}


def _expect(factor) -> Fraction:
    return sum((_f(v) * _f(p) for v, p in
                zip(factor["values"], factor["probabilities"])), Fraction(0))


def _primary_factors(regime, control=False):
    delta, rho = map(_f, _PRIMARY[regime])
    if control:
        d = _finite("D", [-1, 0], ["0.03", "0.97"], scope="dataset")
    else:
        if regime in ("P1", "P2"):
            q = Fraction(9, 17) + delta * delta
            minus, plus = (q - delta) / 2, (q + delta) / 2
        elif regime == "P3":
            minus = plus = Fraction(1, 2)
        else:
            plus = _f("0.005" if regime == "R4" else "0.10")
            minus = plus - delta
        values = [(-1, minus), (0, 1 - minus - plus), (1, plus)]
        d = _finite("D", [v for v, p in values if p],
                    [p for v, p in values if p])
    z = _finite("Z", ["0.75", 1, "1.25"], ["0.25", "0.5", "0.25"])
    v = (_finite("V", ["0.5", "5.5"], ["0.9", "0.1"])
         if regime in ("R5", "P1", "P2", "P3") else
         _finite("V", ["0.8", 1, "1.2"], ["0.25", "0.5", "0.25"]))
    factors = [d, z, v]
    if regime == "P2":
        factors.append(_finite("Q_first", [0, 1], ["0.5", "0.5"]))
    return delta, rho, factors


def _secondary_k(template):
    if template == "R":
        factors = [_finite("Z_extra", [0, 1], [Fraction(3, 7), Fraction(4, 7)]),
                   _finite("Q_extra", [0, 1], ["0.5", "0.5"])]
        means = list(map(_f, [1, 5, 9, 5 + 2 * _expect(factors[0]),
                            5 + 2 * _expect(factors[1]), 5]))
        formula = "(1,5,9,5+2*Z_extra,5+2*Q_extra,5)"
    else:
        factors = [_finite("k", [2, 3], ["0.5", "0.5"])]
        if template in ("T1", "T2"):
            t = 1 if template == "T1" else 2
            factors.append(_finite("ST_extra_round", [0, 1], ["0.5", "0.5"]))
            means = [_expect(factors[0]) * (1 + _expect(factors[1])) + 1,
                     _expect(factors[0]) * t + 1]
            formula = f"(k*(1+ST_extra_round)+1,k*{t}+1)"
        else:
            means = list(map(_f, [2 * _expect(factors[0]) + 1,
                                 2 * _expect(factors[0]) - 1, 5, 3]))
            formula = "(2*k+1,2*k-1,5,3)"
    return factors, means, formula


def _secondary_factors(template, regime, control=False):
    arms = _COLUMNS[template]
    a = len(arms)
    factors, k_means, k_formula = _secondary_k(template)
    z_values = ["0.1", "1.9"] if regime == "S5" else ["0.75", "1.25"]
    u_values = {"S4": ["0.05", "1.95"], "S5": ["0.99", "1.01"]}.get(
        regime, ["0.8", "1.2"])
    factors.append(_finite("Z", z_values, ["0.5", "0.5"]))
    for arm in arms:
        factors.append(_finite(f"U_{arm}", u_values, ["0.5", "0.5"]))
    if regime in ("S2", "S3"):
        rare, high = ((Fraction(1, 100), 16) if regime == "S2" else
                      (Fraction(1, 1000), 64))
        normalizer = 1 + rare * (high - 1)
        for arm in arms:
            factors.append(_finite(f"T_{arm}",
                                   [1 / normalizer, high / normalizer],
                                   [1 - rare, rare]))
    if regime == "S6":
        for arm in arms:
            factors.append(_finite(f"early_{arm}", [0, 1], ["0.9", "0.1"]))
        k_means = [Fraction(9, 10) * x + Fraction(1, 10) for x in k_means]
    multiplier = Fraction(1)
    if regime == "S7":
        factors.append({"name": "arm_permutation", "scope": "block",
                        "distribution": "uniform_permutation", "size": a,
                        "probability_per_permutation": str(Fraction(1, math.factorial(a)))})
        multiplier = Fraction(a + 1, 2 * a)
    e = list(map(_f, ([1, "1.5", 1, "0.75"] if template == "F" and regime == "S2"
                    else [1, "0.75", 1, "1.5"] if template == "F" and regime == "S3"
                    else [1] * a)))
    if control:
        factors.append(_finite("global_S", [-1, 1], ["0.5", "0.5"], scope="dataset"))
    # E(Z)=E(U_j)=E(T_j)=E(global multiplier)=1 by the exact factors.
    means = [B / 5 * k * multiplier * eff for k, eff in zip(k_means, e)]
    return factors, means, k_formula, e


def _coefficients(size, plus, minus=None):
    result = [0] * size
    result[plus] = 1
    if minus is not None:
        result[minus] = -1
    return result


def _endpoint(identifier, numerator, means, *, denominator=None, h=None,
              bounds=None, information_width_required=True):
    truth = sum((c * m for c, m in zip(numerator, means)), Fraction(0))
    if denominator is not None:
        truth /= sum((c * m for c, m in zip(denominator, means)), Fraction(0))
    result = {"id": identifier, "kind": "ratio" if denominator is not None else "mean",
              "numerator": numerator, "truth": float(truth), "truth_fraction": str(truth),
              "h": float(truth / 10 if h is None else h),
              "information_width_required": information_width_required}
    if denominator is not None:
        result["denominator"] = denominator
    if bounds is not None:
        result["bounds"] = bounds
    return result


def _make_group(identifier, template, regime, *, control=False):
    if template == "P":
        delta, rho, factors = _primary_factors(regime, control)
        d_mean, z_mean, v_mean = [_expect(x) for x in factors[:3]]
        position_mean = Fraction(3, 4) if regime == "P2" else Fraction(1)
        means = [d_mean, rho * B * z_mean * v_mean * (1 + Fraction(3, 10) * d_mean)
                 / (1 + Fraction(3, 10) * delta) * position_mean,
                 B * z_mean * position_mean]
        endpoints = [
            _endpoint("P-D", [1, 0, 0], means, h=Fraction(3, 200), bounds=[-1, 1],
                      information_width_required=regime != "P3"),
            _endpoint("P-C", [0, 1, 0], means, denominator=[0, 0, 1], h=Fraction(1, 20)),
        ]
        distribution = {"factors": factors, "delta": str(delta), "rho": str(rho),
                        "b": str(B), "formula": "D; A=rho*b*Z*V*(1+3*D/10)/(1+3*delta/10); B=b*Z",
                        "position_rule": "Q_first: (M_A,M_B)=(1,1/2), otherwise (1/2,1)"
                        if regime == "P2" else None}
    else:
        factors, means, k_formula, e = _secondary_factors(template, regime, control)
        a = len(means)
        pairs = (_REFERENCE_PAIRS if template == "R" else [(0, 1)]
                 if template in ("T1", "T2") else [(1, 0), (3, 2)])
        prefix = "R" if template == "R" else "T" if template in ("T1", "T2") else "F"
        endpoints = [_endpoint(f"{prefix}{i:02d}", _coefficients(a, num), means,
                               denominator=_coefficients(a, den))
                     for i, (num, den) in enumerate(pairs, 1)]
        if template == "F":
            endpoints.extend([
                _endpoint("F03", [-1, 1, 0, 0], means, h=means[0] / 10),
                _endpoint("F04", [0, 0, -1, 1], means, h=means[2] / 10),
                _endpoint("F05", [-1, 1, 1, -1], means, h=(means[0] + means[2]) / 10),
            ])
        distribution = {"factors": factors, "b": str(B), "k_formula": k_formula,
                        "formula": "C_j=(b/5)*K_j*Z*U_j*T_j*M_j*e_j",
                        "e": [str(x) for x in e],
                        "early_rule": "independently replace K_j by 1" if regime == "S6" else None,
                        "position_rule": "M=1 for first permutation arm, 1/2 otherwise" if regime == "S7" else None,
                        "global_rule": "1+S*(-1)^j/2, j=1,...,arm_count" if control else None,
                        "default_T_M": "1"}
    cardinality = math.prod(math.factorial(f["size"]) if f.get("distribution") == "uniform_permutation"
                            else len(f["values"]) for f in factors)
    return {"id": identifier, "template": template, "regime": regime,
            "n": MAIN_N if template == "P" else SECONDARY_N,
            "repetitions": CONTROL_REPETITIONS if control else REPETITIONS,
            "bootstraps": BOOTSTRAPS, "control": control,
            "iid_rows": not control, "columns": list(_COLUMNS[template]),
            "means_fraction": [str(x) for x in means], "endpoints": endpoints,
            "distribution": distribution, "factor_combinations": cardinality}


@lru_cache(maxsize=1)
def _catalog():
    groups = [_make_group(f"P/{regime}", "P", regime) for regime in _PRIMARY]
    groups.extend(_make_group(f"{template}/S{i}", template, f"S{i}")
                  for template in ("R", "T1", "T2", "F") for i in range(1, 8))
    groups.sort(key=lambda x: x["id"])
    controls = [_make_group("G-Q", "P", "R1", control=True)]
    controls.extend(_make_group(f"G-{template}", template, "S1", control=True)
                    for template in ("R", "T1", "T2", "F"))
    events = []
    for g in groups:
        for endpoint in g["endpoints"]:
            for direction in ("L", "U"):
                events.append({"id": f"{g['id']}/{endpoint['id']}/{direction}",
                               "group_id": g["id"], "endpoint_id": endpoint["id"],
                               "direction": direction, "kind": "marginal"})
        if g["template"] == "P" and g["regime"] != "R8":
            events.append({"id": f"{g['id']}/P-J/Joint", "group_id": g["id"],
                           "endpoint_id": "P-J", "direction": "Joint", "kind": "joint"})
    events.sort(key=lambda x: x["id"])
    return {"schema": 1, "seed_basis": SEED_BASIS, "groups": groups,
            "controls": controls, "events": events,
            "source_sha256": {"METHODEN-UND-INFORMATION.md": METHODS_SHA256,
                              "Z32-HAUPTVERGLEICH-PLAN.md": Z32_SHA256}}


def catalog() -> dict:
    """Return an independent JSON-serializable snapshot of the frozen contract."""
    return deepcopy(_catalog())


def group(identifier: str) -> dict:
    """Return a regular group or one of the five named dependence controls."""
    for item in _catalog()["groups"] + _catalog()["controls"]:
        if item["id"] == identifier:
            return deepcopy(item)
    raise ValueError(f"unknown case: {identifier!r}")


def _positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def seed(group_id: str, n: int, rep: int, stream: str) -> int:
    """SHA256 UTF-8 contract; first 16 bytes interpreted as little endian."""
    g = group(group_id)
    _positive_integer(n, "n")
    if isinstance(rep, bool) or not isinstance(rep, (int, np.integer)) or not 0 <= rep < g["repetitions"]:
        raise ValueError("rep outside the predeclared repetition range")
    if stream not in ("data", "bootstrap"):
        raise ValueError("stream must be data or bootstrap")
    payload = f"{SEED_BASIS}|{group_id}|{n}|{rep}|{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "little")


def _draw(rng, factor, n):
    size = 1 if factor["scope"] == "dataset" else n
    values = np.asarray([float(_f(x)) for x in factor["values"]])
    p = np.asarray([float(_f(x)) for x in factor["probabilities"]])
    return rng.choice(values, size=size, p=p)


def generate(group_id: str, n: int, rng) -> np.ndarray:
    """Draw complete rows; pass Generator(PCG64(seed(..., 'data'))).

    Factor draw order is the catalog order. Each categorical factor draws its
    whole n-vector before the next factor; controls draw their shared state
    once. S7 draws a full independent uniform arm permutation for each row.
    """
    _positive_integer(n, "n")
    g = group(group_id)
    draws = {}
    a = len(g["columns"])
    for factor in g["distribution"]["factors"]:
        name = factor["name"]
        if factor.get("distribution") == "uniform_permutation":
            draws[name] = rng.permuted(np.tile(np.arange(a), (n, 1)), axis=1)
        else:
            draws[name] = _draw(rng, factor, n)
    template, regime = g["template"], g["regime"]
    if template == "P":
        delta = float(_f(g["distribution"]["delta"]))
        rho = float(_f(g["distribution"]["rho"]))
        d = np.broadcast_to(draws["D"], (n,))
        b_cost = float(B) * draws["Z"]
        a_cost = rho * b_cost * draws["V"] * (1 + 0.3 * d) / (1 + 0.3 * delta)
        if regime == "P2":
            q_first = draws["Q_first"]
            a_cost *= 0.5 + 0.5 * q_first
            b_cost *= 1 - 0.5 * q_first
        return np.column_stack((d, a_cost, b_cost))
    if template == "R":
        k = np.tile(np.asarray([1., 5., 9., 5., 5., 5.]), (n, 1))
        k[:, 3] += 2 * draws["Z_extra"]
        k[:, 4] += 2 * draws["Q_extra"]
    elif template in ("T1", "T2"):
        t = 1 if template == "T1" else 2
        k = np.column_stack((draws["k"] * (1 + draws["ST_extra_round"]) + 1,
                             draws["k"] * t + 1))
    else:
        k = np.column_stack((2 * draws["k"] + 1, 2 * draws["k"] - 1,
                             np.full(n, 5.), np.full(n, 3.)))
    u = np.column_stack([draws[f"U_{arm}"] for arm in g["columns"]])
    if regime == "S6":
        early = np.column_stack([draws[f"early_{arm}"] for arm in g["columns"]])
        k = np.where(early == 1, 1., k)
    costs = float(B / 5) * k * draws["Z"][:, None] * u
    if regime in ("S2", "S3"):
        costs *= np.column_stack([draws[f"T_{arm}"] for arm in g["columns"]])
    if regime == "S7":
        multiplier = np.full((n, a), 0.5)
        multiplier[np.arange(n), draws["arm_permutation"][:, 0]] = 1.
        costs *= multiplier
    costs *= np.asarray([float(_f(x)) for x in g["distribution"]["e"]])
    if g["control"]:
        signs = np.asarray([(-1) ** j for j in range(1, a + 1)])
        costs *= 1 + 0.5 * draws["global_S"][0] * signs
    return costs
