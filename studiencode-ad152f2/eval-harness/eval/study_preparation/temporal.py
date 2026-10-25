"""Z44 offline temporal preparation; no content loader, Q invocation or transport.

The metadata plan binds the existing spatial selector, never fabricates its outputs.
The two-head adapter copies the fixed R2 selection contract; tests use artificial
public inputs and a fake encoder. This module does not authorize any real fit.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from time import perf_counter_ns
import json
import math

from communication_pruning.contracts import TaskInput
from communication_pruning.data import validate_manifest
from communication_pruning.selection import EPSILON, TOL, family_partition
from communication_pruning.semantic_selection import (
    ALPHAS, DIMENSION, _identity, _matrix, _select_alpha,
)

FOLD_SEED = "Z44-temporal-folds-2026-09-17-v1"
ARM_ORDER_SEED = "Z44-temporal-arm-order-2026-09-17-v1"
ROUNDS = (1, 2)
PARAMETERS = {"alphas": list(ALPHAS), "solver": "svd", "fit_intercept": True,
              "standard_deviation_divisor": "n", "constant_columns": "zero",
              "epsilon": EPSILON, "tie_tolerance": TOL, "score_clipping": False,
              "rounds": list(ROUNDS), "dimension": DIMENSION}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _bindings(bindings):
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("nonempty source hash mapping required")
    for key, value in bindings.items():
        if (not isinstance(key, str) or not key or not isinstance(value, str)
                or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("source hashes must be lowercase SHA256")


def _sealed(value):
    result = deepcopy(value)
    result["sha256"] = digest(result)
    return result


def make_temporal_plan(manifest, allocation, bindings):
    """Preserve the ordered temporal panel; derive folds/order using metadata only."""
    validate_manifest(manifest)
    _bindings(bindings)
    if "raw_q_source" not in bindings:
        raise ValueError("the frozen raw spatial Q source must be bound")
    # source_manifest_sha256 identifies the pre-allocation input. The resulting
    # role-assigned manifest is embedded in the original allocation itself.
    if allocation.get("manifest") != manifest:
        raise ValueError("allocation does not contain this role-assigned manifest")
    unsigned = {k: v for k, v in allocation.items() if k != "sha256"}
    if allocation.get("sha256") != digest(unsigned):
        raise ValueError("allocation content hash mismatch")
    ids = allocation.get("panels", {}).get("temporal")
    if (not isinstance(ids, list) or len(ids) != 100
            or any(not isinstance(t, str) or not t for t in ids) or len(set(ids)) != 100):
        raise ValueError("exactly 100 distinct ordered temporal task IDs required")
    by_id = {r["task_id"]: r for r in manifest["entries"]}
    if any(t not in by_id for t in ids):
        raise ValueError("task missing from manifest")
    rows = [by_id[t] for t in ids]
    if any(r["split"] != "train" or r["phase"] != "temporal" for r in rows):
        raise ValueError("only assigned temporal Train tasks are allowed")
    families = {r["task_id"]: r["family_id"] for r in rows}
    if len(set(families.values())) != 50 or Counter(r["hop"] for r in rows) != {2: 55, 3: 28, 4: 17}:
        raise ValueError("the bound 50-family and 55/28/17-hop panel is required")
    folds_by_family = family_partition(families, seed=FOLD_SEED, folds=5)
    folds = [[t for t in ids if folds_by_family[families[t]] == f] for f in range(5)]
    pairs, slots = [], []
    for number, row in enumerate(rows, 1):
        task_id = row["task_id"]
        # An independent per-task SHA256 permutation, no imposed 50/50 balancing.
        keys = {r: digest([ARM_ORDER_SEED, task_id, r]) for r in ROUNDS}
        order = sorted(ROUNDS, key=lambda r: (keys[r], r))
        pair_id = f"T{number:03d}"
        slot_ids = [f"{pair_id}-R{r}" for r in order]
        pairs.append({"pair_id": pair_id, "task_id": task_id,
                      "family_id": row["family_id"], "hop": row["hop"],
                      "round_order": order, "slot_ids": slot_ids,
                      "arm_rank_hashes": {str(r): keys[r] for r in ROUNDS},
                      "spatial_config_id": None,
                      "spatial_selection": "once_from_bound_raw_Q_then_share_with_both_slots"})
        for position, (rounds, slot_id) in enumerate(zip(order, slot_ids), 1):
            slots.append({"slot_id": slot_id, "pair_id": pair_id, "task_id": task_id,
                          "rounds": rounds, "position": position, "repeat": 1,
                          "fresh_context": True, "reuse_prior_round": False})
    return _sealed({"schema": "z44-temporal-metadata-plan/v1", "phase": "temporal",
                    "status": "offline_preparation_no_execution_release",
                    "send_enabled": False, "real_content_used": False,
                    "source_bindings": dict(bindings), "task_ids": ids,
                    "task_ids_sha256": digest(ids), "family_folds": folds,
                    "family_to_fold": folds_by_family,
                    "seeds": {"folds": FOLD_SEED, "arm_order": ARM_ORDER_SEED},
                    "algorithms": {
                        "folds": "existing size-balanced family_partition; SHA256(seed+NUL+family)",
                        "arm_order": "ascending SHA256(canonical JSON [seed,task_id,rounds]); rounds tie-break",
                        "canonical_json": "UTF-8; sorted keys; separators comma/colon; ensure_ascii=False"},
                    "pairs": pairs, "slots": slots,
                    "counts": {"tasks": 100, "families": 50, "pairs": 100, "slots": 200,
                               "regular_calls_min": 800, "regular_calls_max": 1100},
                    "pending": ["phase_cost_cap", "content_and_external_model_release",
                                "calendar_and_control_holds", "current_provider_and_tariff",
                                "runtime_source_backup_and_separate_start_acceptance"],
                    "cost_projection_usd_not_cap": "0.28"})


def validate_temporal_plan(plan, manifest, allocation, bindings):
    if plan != make_temporal_plan(manifest, allocation, bindings):
        raise ValueError("temporal plan differs from its deterministic metadata sources")


def choose_rounds(scores, costs):
    """Return 1/2: scores within 0.01, lowest training cost, then smaller round ID."""
    if len(scores) != 2 or len(costs) != 2:
        raise ValueError("complete two-head vectors required")
    if any(type(s) not in (int, float) or not math.isfinite(s) for s in scores):
        raise ValueError("finite unbounded scores required")
    if any(not isinstance(c, Decimal) or not c.is_finite() or c < 0 for c in costs):
        raise ValueError("known nonnegative Decimal costs required")
    eligible = [i for i, score in enumerate(scores) if score >= max(scores) - EPSILON - TOL]
    return min(eligible, key=lambda i: (costs[i], ROUNDS[i])) + 1


@dataclass(frozen=True)
class TemporalObservation:
    task: TaskInput
    family_id: str
    phase: str
    spatial_config_id: str
    quality: tuple[float, float]
    costs: tuple[Decimal, Decimal]

    def __post_init__(self):
        if not isinstance(self.task, TaskInput) or not isinstance(self.family_id, str) or not self.family_id:
            raise ValueError("public task and family required")
        if self.phase != "temporal":
            raise ValueError("only temporal development observations allowed")
        if self.spatial_config_id not in tuple(f"C{i:02d}" for i in range(1, 15)):
            raise ValueError("one shared spatial configuration per pair is required")
        if not isinstance(self.quality, tuple) or not isinstance(self.costs, tuple):
            raise ValueError("immutable complete pair vectors required")
        choose_rounds(self.quality, self.costs)
        if any(not 0 <= q <= 1 for q in self.quality):
            raise ValueError("observed quality must be in [0,1]")


def _rows(observations):
    rows = list(observations)
    if not rows or any(not isinstance(r, TemporalObservation) for r in rows):
        raise ValueError("nonempty temporal observations required")
    if len({r.task.task_id for r in rows}) != len(rows):
        raise ValueError("one complete pair per unique task required")
    return rows


def _folds(rows, folds):
    if not isinstance(folds, (list, tuple)) or len(folds) != 5:
        raise ValueError("five prebound family-disjoint folds required")
    if any(not isinstance(f, (list, tuple)) or not f for f in folds):
        raise ValueError("five nonempty folds required")
    ids = {r.task.task_id for r in rows}
    flat = [t for f in folds for t in f]
    if len(flat) != len(ids) or set(flat) != ids:
        raise ValueError("folds must cover each task exactly once")
    assignment = {t: i for i, f in enumerate(folds) for t in f}
    for family in {r.family_id for r in rows}:
        if len({assignment[r.task.task_id] for r in rows if r.family_id == family}) != 1:
            raise ValueError("family crosses validation folds")
    return [sorted(f) for f in folds]


def fit_temporal_ridge(rows, matrix, *, alpha):
    """Only these training rows set scaling, two quality heads and mean costs."""
    import numpy as np
    from sklearn.linear_model import Ridge
    rows = _rows(rows)
    if type(alpha) is not int or alpha not in ALPHAS:
        raise ValueError("alpha must belong to the fixed R2 grid")
    x = np.asarray(matrix, dtype=float)
    if x.shape != (len(rows), DIMENSION) or not np.isfinite(x).all():
        raise ValueError("finite 388-dimensional matrix required")
    mean, scale = x.mean(axis=0), x.std(axis=0, ddof=0)
    constant = np.ptp(x, axis=0) == 0
    scale[constant] = 1.0
    z = (x - mean) / scale
    z[:, constant] = 0.0
    estimator = Ridge(alpha=alpha, fit_intercept=True, solver="svd")
    estimator.fit(z, np.asarray([r.quality for r in rows], dtype=float))
    estimator.coef_[:, constant] = 0.0
    quality = [math.fsum(r.quality[i] for r in rows) / len(rows) for i in range(2)]
    costs = [sum((r.costs[i] for r in rows), Decimal(0)) / len(rows) for i in range(2)]
    return {"alpha": alpha, "mean": mean.tolist(), "scale": scale.tolist(),
            "constant": constant.tolist(), "coefficients": estimator.coef_.tolist(),
            "intercepts": estimator.intercept_.tolist(), "costs": [str(c) for c in costs],
            "training_quality": quality, "fixed_rounds": choose_rounds(quality, costs),
            "training_task_ids": [r.task.task_id for r in rows]}


def _validate_model(model):
    import numpy as np
    if type(model.get("alpha")) is not int or model["alpha"] not in ALPHAS:
        raise ValueError("invalid model alpha")
    for key, shape in (("mean", (DIMENSION,)), ("scale", (DIMENSION,)),
                       ("coefficients", (2, DIMENSION)), ("intercepts", (2,))):
        value = np.asarray(model[key], dtype=float)
        if value.shape != shape or not np.isfinite(value).all():
            raise ValueError("invalid two-head model dimensions or values")
    if any(x <= 0 for x in model["scale"]):
        raise ValueError("positive scaling required")
    constant = model["constant"]
    if len(constant) != DIMENSION or any(type(c) is not bool for c in constant):
        raise ValueError("constant mask required")
    if any(model["scale"][i] != 1 or any(c[i] != 0 for c in model["coefficients"])
           for i, flag in enumerate(constant) if flag):
        raise ValueError("constant columns must be zero")
    q = model["training_quality"]
    if len(q) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in q):
        raise ValueError("invalid training quality")
    fixed = choose_rounds(q, tuple(Decimal(c) for c in model["costs"]))
    if type(model["fixed_rounds"]) is not int or model["fixed_rounds"] != fixed:
        raise ValueError("fixed temporal reference differs from training contract")


def predict_temporal_scores(model, matrix):
    import numpy as np
    _validate_model(model)
    x = np.asarray(matrix, dtype=float)
    if x.ndim != 2 or x.shape[1] != DIMENSION or not np.isfinite(x).all():
        raise ValueError("finite 388-dimensional prediction matrix required")
    z = (x - np.asarray(model["mean"])) / np.asarray(model["scale"])
    z[:, np.asarray(model["constant"])] = 0.0
    return (z @ np.asarray(model["coefficients"]).T + np.asarray(model["intercepts"])).tolist()


def fit_temporal_selector(observations, *, encoder, folds, bindings):
    """Fixed five-fold R2 selection, then one final fit; no spatial selection call."""
    _bindings(bindings)
    if "raw_q_source" not in bindings:
        raise ValueError("frozen spatial Q source required")
    rows = sorted(_rows(observations), key=lambda r: r.task.task_id)
    folds = _folds(rows, folds)
    matrix, encoding = _matrix([r.task for r in rows], encoder)
    reports = []
    for alpha in ALPHAS:
        outcomes, fold_models = [], []
        for number, heldout in enumerate(folds):
            train = [i for i, r in enumerate(rows) if r.task.task_id not in heldout]
            valid = [i for i, r in enumerate(rows) if r.task.task_id in heldout]
            model = fit_temporal_ridge([rows[i] for i in train], matrix[train], alpha=alpha)
            scores = predict_temporal_scores(model, matrix[valid])
            for i, score in zip(valid, scores):
                chosen = choose_rounds(score, tuple(Decimal(c) for c in model["costs"]))
                row = rows[i]
                outcomes.append({"task_id": row.task.task_id, "fold": number,
                                 "rounds": chosen, "scores": score,
                                 "quality": row.quality[chosen - 1],
                                 "cost_usd": str(row.costs[chosen - 1])})
            fold_models.append({"fold": number, "validation_task_ids": heldout, "model": model})
        reports.append({"alpha": alpha,
                        "quality": math.fsum(o["quality"] for o in outcomes) / len(rows),
                        "cost_usd": str(sum((Decimal(o["cost_usd"]) for o in outcomes), Decimal(0)) / len(rows)),
                        "outcomes": sorted(outcomes, key=lambda o: o["task_id"]), "folds": fold_models})
    alpha = _select_alpha(reports)
    final = fit_temporal_ridge(rows, matrix, alpha=alpha)
    choices = [choose_rounds(s, tuple(Decimal(c) for c in final["costs"]))
               for s in predict_temporal_scores(final, matrix)]
    payload = {"schema": "z44-temporal-selector/v1", "parameters": deepcopy(PARAMETERS),
               "bindings": dict(bindings), "encoder": deepcopy(encoder.identity),
               "folds": folds, "task_families": {r.task.task_id: r.family_id for r in rows},
               "spatial_configurations": {r.task.task_id: r.spatial_config_id for r in rows},
               "cross_validation": reports, "chosen_alpha": alpha, "model": final,
               "fixed_rounds": final["fixed_rounds"], "training_selections": choices,
               "encoding": encoding, "independent_effect_evidence": False,
               "study_frozen": False, "send_enabled": False}
    return TemporalSelector(payload, encoder=encoder)


class TemporalSelector:
    """Offline round selector; raw spatial Q remains an externally bound prerequisite."""
    def __init__(self, payload, *, encoder):
        self.payload = deepcopy(payload)
        self.encoder = encoder
        self.selection_timings_ns = []
        self.selection_records = []
        p = self.payload
        if p["schema"] != "z44-temporal-selector/v1" or p["parameters"] != PARAMETERS:
            raise ValueError("changed temporal contract")
        _bindings(p["bindings"])
        if "raw_q_source" not in p["bindings"]:
            raise ValueError("missing spatial Q binding")
        _identity(p["encoder"])
        if p["encoder"] != encoder.identity:
            raise ValueError("encoder binding mismatch")
        _validate_model(p["model"])
        if ([r["alpha"] for r in p["cross_validation"]] != list(ALPHAS)
                or p["chosen_alpha"] != _select_alpha(p["cross_validation"])
                or p["model"]["alpha"] != p["chosen_alpha"]
                or p["fixed_rounds"] != p["model"]["fixed_rounds"]):
            raise ValueError("alpha or fixed-reference contract mismatch")
        families = p["task_families"]
        ids = p["model"]["training_task_ids"]
        if (not isinstance(families, dict) or not ids or len(set(ids)) != len(ids)
                or set(ids) != set(families) or set(p["spatial_configurations"]) != set(ids)
                or any(not isinstance(f, str) or not f for f in families.values())
                or any(c not in tuple(f"C{i:02d}" for i in range(1, 15))
                       for c in p["spatial_configurations"].values())):
            raise ValueError("invalid training identity or spatial configuration map")
        folds = p["folds"]
        if (not isinstance(folds, list) or len(folds) != 5 or any(not f for f in folds)
                or len([t for f in folds for t in f]) != len(ids)
                or {t for f in folds for t in f} != set(ids)):
            raise ValueError("invalid saved folds")
        positions = {t: i for i, fold in enumerate(folds) for t in fold}
        if any(len({positions[t] for t in ids if families[t] == f}) != 1 for f in set(families.values())):
            raise ValueError("saved fold splits a family")
        if (len(p["training_selections"]) != len(ids)
                or any(type(r) is not int or r not in ROUNDS for r in p["training_selections"])):
            raise ValueError("invalid saved round choices")
        for report in p["cross_validation"]:
            if len(report["folds"]) != 5 or [f["fold"] for f in report["folds"]] != list(range(5)):
                raise ValueError("incomplete cross-validation")
            for f in report["folds"]:
                _validate_model(f["model"])
                expected = folds[f["fold"]]
                if (f["validation_task_ids"] != expected
                        or f["model"]["alpha"] != report["alpha"]
                        or set(f["model"]["training_task_ids"]) != set(ids) - set(expected)):
                    raise ValueError("heldout tasks entered the saved training model")
            outputs = report["outcomes"]
            if len(outputs) != len(ids) or {o["task_id"] for o in outputs} != set(ids):
                raise ValueError("incomplete saved validation outcomes")
            for o in outputs:
                if o["fold"] != positions[o["task_id"]]:
                    raise ValueError("validation fold mismatch")
                fm = report["folds"][o["fold"]]["model"]
                if o["rounds"] != choose_rounds(o["scores"], tuple(Decimal(c) for c in fm["costs"])):
                    raise ValueError("validation round choice mismatch")
                if (type(o["quality"]) not in (int, float) or not math.isfinite(o["quality"])
                        or not 0 <= o["quality"] <= 1 or not Decimal(o["cost_usd"]).is_finite()
                        or Decimal(o["cost_usd"]) < 0):
                    raise ValueError("invalid saved validation measurement")
            if (report["quality"] != math.fsum(o["quality"] for o in outputs) / len(ids)
                    or Decimal(report["cost_usd"]) != sum((Decimal(o["cost_usd"]) for o in outputs), Decimal(0)) / len(ids)):
                raise ValueError("validation means mismatch")
        if (p["independent_effect_evidence"] is not False or p["study_frozen"] is not False
                or p["send_enabled"] is not False):
            raise ValueError("offline adapter cannot claim release or effect evidence")

    def select(self, task):
        start = perf_counter_ns()
        matrix, encoding = _matrix([task], self.encoder)
        after_encoding = perf_counter_ns()
        scores = predict_temporal_scores(self.payload["model"], matrix)[0]
        rounds = choose_rounds(scores, tuple(Decimal(c) for c in self.payload["model"]["costs"]))
        end = perf_counter_ns()
        self.selection_timings_ns.append(end - start)
        self.selection_records.append({"selection_index": len(self.selection_records) + 1,
                                       "task_id": task.task_id, "encoding": deepcopy(encoding),
                                       "feature_and_encoder_ns": after_encoding - start,
                                       "score_and_choice_ns": end - after_encoding,
                                       "total_ns": end - start})
        return rounds

    def to_dict(self):
        return _sealed(self.payload)

    @classmethod
    def from_dict(cls, value, *, encoder):
        payload = deepcopy(value)
        checksum = payload.pop("sha256", None)
        if checksum != digest(payload):
            raise ValueError("temporal selector checksum mismatch")
        return cls(payload, encoder=encoder)
