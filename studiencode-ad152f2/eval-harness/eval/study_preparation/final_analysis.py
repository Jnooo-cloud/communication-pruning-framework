"""Analysis adapter for complete, fresh Z50 blocks; no content or I/O path.

Primary inference delegates to the unchanged Z44/Z47 kernel. Secondary quality
delegates to its existing Hoeffding function. D-065 secondary costs are strictly
descriptive; a sample standard deviation is not uncertainty of an expectation.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import math
import re

import numpy as np

from . import intervals
from .final_plan import ARMS, canonical_hash, validate_plan


BOOTSTRAP_REPS = 19999
PRIMARY_ENDPOINTS = (
    {"id": "P-D", "kind": "mean", "numerator": [1, 0, 0], "bounds": [-1, 1]},
    {"id": "P-C", "kind": "ratio", "numerator": [0, 1, 0], "denominator": [0, 0, 1]},
)
_ROW_FIELDS = {"panel", "block_id", "draw_index", "slot_id", "arm", "task_id",
               "family_id", "em", "f1", "cost_usd", "status"}
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_REFERENCE_PAIRS = ((4, 0), (4, 1), (4, 2), (4, 3), (4, 5),
                    (5, 0), (5, 1), (5, 2), (5, 3))


def _cost(value):
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("cost_usd must be a finite nonnegative decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid cost_usd decimal") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("cost_usd must be finite and nonnegative")
    return amount


def validate_rows(plan, panel, rows):
    """Return copied rows in draw/canonical-arm order, retaining metadata.

    A task ID is never a grouping key. Incomplete fixed-size panels are rejected
    rather than silently reduced to their successfully observed prefix.
    """
    validate_plan(plan)
    if not isinstance(panel, str) or panel not in ARMS:
        raise ValueError("unknown panel")
    if type(rows) is not list or len(rows) != plan["counts"][panel] * len(ARMS[panel]):
        raise ValueError("complete fixed-size panel rows required")
    expected = {}
    ordered_ids = []
    for block in plan["panels"][panel]:
        by_arm = {slot["arm"]: slot["slot_id"] for slot in block["slots"]}
        for arm in ARMS[panel]:
            slot_id = by_arm[arm]
            expected[slot_id] = {key: block[key] for key in
                                 ("panel", "block_id", "draw_index", "task_id", "family_id")}
            expected[slot_id].update(slot_id=slot_id, arm=arm)
            ordered_ids.append(slot_id)
    actual = {}
    for row in rows:
        if type(row) is not dict or not _ROW_FIELDS <= set(row):
            raise ValueError("numeric row lacks required identity or result fields")
        slot_id = row["slot_id"]
        if not isinstance(slot_id, str) or slot_id not in expected or slot_id in actual:
            raise ValueError("foreign or duplicate result slot")
        if type(row["draw_index"]) is not int or any(row[key] != value for key, value in expected[slot_id].items()):
            raise ValueError("result does not match its planned block/task/family/arm")
        if type(row["em"]) not in (int, float) or row["em"] not in (0, 1):
            raise ValueError("EM must be exactly zero or one")
        if (type(row["f1"]) not in (int, float) or not math.isfinite(row["f1"])
                or not 0 <= row["f1"] <= 1):
            raise ValueError("F1 must be finite and within [0,1]")
        _cost(row["cost_usd"])
        if row["status"] not in ("ok", "model_failure"):
            raise ValueError("technical or unresolved result cannot enter a complete panel")
        if row["status"] == "model_failure" and (row["em"] != 0 or row["f1"] != 0):
            raise ValueError("model failure requires zero EM and F1 with retained cost")
        canonical_hash(row)  # Also validates the retained provenance/execution metadata.
        actual[slot_id] = row
    if set(actual) != set(expected):
        raise ValueError("missing planned result slots")
    return [deepcopy(actual[slot_id]) for slot_id in ordered_ids]


def _decimal_text(value):
    return "0" if value == 0 else str(value)


def _summary(values):
    """Observed distribution only; sample SD uses n-1, and is undefined at n=1."""
    n = len(values)
    total = sum(values, Decimal(0))
    mean = total / n
    sd = (sum(((value - mean) ** 2 for value in values), Decimal(0)) / (n - 1)).sqrt() if n > 1 else None
    return {"n": n, "total": _decimal_text(total), "mean": _decimal_text(mean),
            "sample_sd": _decimal_text(sd) if sd is not None else None,
            "min": _decimal_text(min(values)), "max": _decimal_text(max(values))}


def _descriptive_costs(panel, blocks):
    arms = ARMS[panel]
    columns = {arm: [_cost(block[index]["cost_usd"]) for block in blocks]
               for index, arm in enumerate(arms)}
    with localcontext() as context:
        context.prec = 50
        summaries = {arm: _summary(values) for arm, values in columns.items()}
        endpoints = {}
        pairs = (_REFERENCE_PAIRS if panel == "R" else ((0, 1),) if panel == "T"
                 else ((1, 0), (3, 2)) if panel == "F" else ())
        for index, (a, b) in enumerate(pairs, 1):
            numerator, denominator = arms[a], arms[b]
            ma = sum(columns[numerator], Decimal(0)) / len(blocks)
            mb = sum(columns[denominator], Decimal(0)) / len(blocks)
            difference = [x - y for x, y in zip(columns[numerator], columns[denominator])]
            endpoints[f"{panel}{index:02d}"] = {
                "kind": "ratio_of_means", "numerator_arm": numerator,
                "denominator_arm": denominator,
                "mean_numerator_usd": _decimal_text(ma),
                "mean_denominator_usd": _decimal_text(mb),
                "estimate": _decimal_text(ma / mb) if mb > 0 else None,
                "value_status": "defined" if mb > 0 else "undefined_zero_reference",
                "mean_difference_usd": _decimal_text(ma - mb),
                "paired_difference_usd": _summary(difference),
            }
        if panel == "F":
            hq = [x - y for x, y in zip(columns["Qf"], columns["Qc"])]
            hf = [x - y for x, y in zip(columns["Ff"], columns["Fc"])]
            for identifier, label, values in (("F03", "H_Q", hq), ("F04", "H_F", hf),
                                               ("F05", "H_Q_minus_H_F", [x - y for x, y in zip(hq, hf)])):
                summary = _summary(values)
                endpoints[identifier] = {"kind": "mean_paired_change", "quantity": label,
                                         "estimate": summary["mean"], "value_status": "defined",
                                         "observed_changes_usd": summary}
    return {"method": "descriptive_only", "unit": "USD",
            "spread_definition": "observed sample SD with denominator n-1; undefined at n=1",
            "arms": summaries, "endpoints": endpoints}


def _strict_numbers(value):
    """Keep blocked/unbounded kernel outputs JSON-safe without inventing values."""
    if isinstance(value, float) and not math.isfinite(value):
        return None if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {key: _strict_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict_numbers(item) for item in value]
    return value


def _primary(blocks, bootstrap_seed):
    atoms = []
    for q, f in blocks:
        costs = []
        for row in (q, f):
            exact = _cost(row["cost_usd"])
            value = float(exact)
            if not math.isfinite(value) or (exact != 0 and value == 0):
                raise ValueError("primary kernel cost is outside finite float representation")
            costs.append(value)
        atoms.append([q["em"] - f["em"], *costs])
    # Each row is one fresh draw, including every repeated task identity.
    result = intervals.analyze(np.asarray(atoms, dtype=float), np.ones(len(blocks), dtype=np.int64),
                               deepcopy(PRIMARY_ENDPOINTS),
                               rng=np.random.Generator(np.random.PCG64(bootstrap_seed)),
                               bootstrap_reps=BOOTSTRAP_REPS)
    quality, cost = result["endpoints"]["P-D"], result["endpoints"]["P-C"]

    def statement(endpoint, condition):
        if endpoint["status"] != "ok":
            return "blocked"
        return "established" if condition else "not_established"

    statements = {
        "quality_preserved_3pp": statement(quality, quality["lower"] > -0.03),
        "quality_loss": statement(quality, quality["upper"] < 0),
        "quality_loss_beyond_3pp": statement(quality, quality["upper"] < -0.03),
        "cost_saving_at_least_10pct": statement(cost, cost["upper"] < 0.90),
        "cost_saving_below_10pct": statement(cost, cost["lower"] > 0.90),
        "cost_increase": statement(cost, cost["lower"] > 1),
    }
    positive = (statements["quality_preserved_3pp"] == "established"
                and statements["cost_saving_at_least_10pct"] == "established")
    return {"kernel": _strict_numbers(result), "statements": statements,
            "joint_positive": positive, "joint_finding": "positive" if positive else "not_established",
            "directions_scope": "individual adverse statements; no global negative test",
            "resampling": {"algorithm": "PCG64", "seed": bootstrap_seed, "repetitions": BOOTSTRAP_REPS},
            "nonfinite_encoding": {"undefined": None, "positive_unbounded": "Infinity",
                                   "negative_unbounded": "-Infinity"}}


def _quality(blocks, panel):
    result = {}
    template = "T1" if panel == "T" else panel
    for metric in ("em", "f1"):
        values = np.asarray([[row[metric] for row in block] for block in blocks], dtype=float)
        original = intervals.secondary_quality(values, template)
        if panel == "R":
            result[metric] = {f"R{i:02d}": original[f"R/{i:02d}"] for i in range(1, 10)}
        elif panel == "T":
            # T1/T2 implement the same contrast; this label is the one real panel.
            result[metric] = {"T01": original["T1/01"]}
        else:
            result[metric] = original
    return {"method": "marginal_hoeffding_95pct", "simultaneous": False,
            "scope": "conditional on independent complete blocks", **result}


def analyze_panel(plan, panel, rows, *, bootstrap_seed):
    """Analyze only a complete declared panel, with no method or B override."""
    if type(bootstrap_seed) is not int or bootstrap_seed < 0:
        raise ValueError("bootstrap_seed must be a nonnegative integer")
    ordered = validate_rows(plan, panel, rows)
    size = len(ARMS[panel])
    blocks = [ordered[start:start + size] for start in range(0, len(ordered), size)]
    if panel == "P" and len(blocks) < 2:
        raise ValueError("primary kernel requires at least two complete blocks")
    costs = _descriptive_costs(panel, blocks)
    estimates = {
        arm: {"em": math.fsum(block[index]["em"] for block in blocks) / len(blocks),
              "f1": math.fsum(block[index]["f1"] for block in blocks) / len(blocks),
              "mean_cost_usd": costs["arms"][arm]["mean"],
              "model_failures": sum(block[index]["status"] == "model_failure" for block in blocks)}
        for index, arm in enumerate(ARMS[panel])
    }
    result = {"schema": 1, "panel": panel, "n": len(blocks), "plan_hash": plan["plan_hash"],
              "mode": plan["mode"], "unit": "fresh_complete_draw_block",
              "estimates": estimates, "descriptive_costs": costs,
              "method_status": "conditional_primary_analysis" if panel == "P" else "secondary_quality_and_descriptive_costs"}
    if panel == "P":
        result["primary"] = _primary(blocks, bootstrap_seed)
    else:
        result["secondary_quality"] = _quality(blocks, panel)
    canonical_hash(result)
    return result
