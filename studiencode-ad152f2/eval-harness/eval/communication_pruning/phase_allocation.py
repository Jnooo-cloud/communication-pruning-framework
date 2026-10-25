"""Z17 constrained metadata allocation. No task content, training or API access.

Small families are preferred to preserve unused data; this is not an equal-
probability task sample. The retained allocation, not a future solver rerun,
is the authoritative selection.
"""

from collections import Counter, defaultdict
import math

from .data import TaskMeta, canonical, digest, make_manifest, validate_manifest


SEED = "Z17-joint-phases-2026-09-07-v1"
TARGETS = {"spatial": {"n": 300, "min_families": 100},
           "temporal": {"n": 100, "min_families": 50},
           "pilot": {"n": 120, "min_families": 80},
           "technical": {"n": 40, "min_families": 20}}


def quotas(n, weights):
    """Integer largest remainders; lower hop wins exact ties."""
    if (type(n) is not int or n < 1 or set(weights) != {2, 3, 4}
            or any(type(v) is not int or v < 1 for v in weights.values())):
        raise ValueError("positive sample size and three positive integer hop weights required")
    total = sum(weights.values())
    result = {h: n * weights[h] // total for h in weights}
    order = sorted(weights, key=lambda h: (-(n * weights[h] % total), h))
    for h in order[:n - sum(result.values())]:
        result[h] += 1
    return result


def _input(source, exposed_ids, targets, seed):
    validate_manifest(source)
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("explicit allocation seed required")
    if not isinstance(targets, dict) or set(targets) != set(TARGETS):
        raise ValueError("four explicit training roles required")
    for spec in targets.values():
        if (not isinstance(spec, dict) or set(spec) != {"n", "min_families"}
                or any(type(v) is not int or v < 1 for v in spec.values())
                or spec["min_families"] > spec["n"]):
            raise ValueError("invalid phase sizes or family minimum")
    exposed = sorted(set(exposed_ids))
    by_id = {e["task_id"]: e for e in source["entries"]}
    if set(exposed) - set(by_id) or set(source["exposed_ids"]) - set(exposed):
        raise ValueError("unknown exposure or previously exposed ID removed")
    blocked = {by_id[t]["family_id"] for t in exposed}
    groups = defaultdict(list)
    for e in source["entries"]:
        groups[e["family_id"]].append(e)
        if e["phase"] in TARGETS and e["family_id"] not in blocked:
            raise ValueError("existing unblocked phase reservation cannot be silently reassigned")
    eligible = {f: es for f, es in groups.items()
                if f not in blocked and {e["split"] for e in es} == {"train"}}
    dev = [e for f, es in groups.items() if f not in blocked
           and {e["split"] for e in es} == {"dev"} for e in es]
    weights = dict(Counter(e["hop"] for e in dev))
    quotas(1, weights)  # Require all three target structure classes explicitly.
    return exposed, blocked, groups, eligible, weights


def allocate(source, *, exposed_ids, targets=TARGETS, seed=SEED, time_limit=60,
             quota_mode="exact"):
    """Joint whole-family allocation via a bounded mixed integer problem."""
    if (type(time_limit) not in (int, float) or not math.isfinite(time_limit)
            or not 0 < time_limit <= 60):
        raise ValueError("time limit must be positive and at most 60 seconds")
    exposed, blocked, groups, eligible, weights = _input(source, exposed_ids, targets, seed)
    if quota_mode not in ("exact", "closest"):
        raise ValueError("unknown quota mode")
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    fs, phases = sorted(eligible), sorted(targets)
    if not fs:
        raise ValueError("no eligible training families")
    # For every family/phase: three selected counts followed by a binary role.
    ix = {(f, p): (fi * len(phases) + pi) * 4
          for fi, f in enumerate(fs) for pi, p in enumerate(phases)}
    base_count = len(ix) * 4
    count = base_count + (3 * len(phases) if quota_mode == "closest" else 0)
    objective, upper = np.zeros(count), np.zeros(count)
    for (f, p), i in ix.items():
        available = Counter(e["hop"] for e in eligible[f])
        upper[i:i + 3] = [min(5, available[h]) for h in (2, 3, 4)]
        upper[i + 3] = 1
        tie = int(digest([seed, "family-role", f, p])[:12], 16) / 16**12
        objective[i + 3] = len(eligible[f]) + tie / (len(ix) + 1)
    rr, cc, vv, lower_c, upper_c = [], [], [], [], []
    def constraint(coefficients, low, high):
        row = len(lower_c)
        for col, value in coefficients:
            rr.append(row); cc.append(col); vv.append(value)
        lower_c.append(low); upper_c.append(high)
    for f in fs:
        constraint([(ix[f, p] + 3, 1) for p in phases], 0, 1)
        for p in phases:
            i = ix[f, p]
            constraint([(i + h, 1) for h in range(3)] + [(i + 3, -5)], -np.inf, 0)
            constraint([(i + h, 1) for h in range(3)] + [(i + 3, -1)], 0, np.inf)
    requested = {p: quotas(targets[p]["n"], weights) for p in phases}
    for p in phases:
        constraint([(ix[f, p] + h, 1) for f in fs for h in range(3)], targets[p]["n"], targets[p]["n"])
        for h in (2, 3, 4):
            terms = [(ix[f, p] + h - 2, 1) for f in fs]
            if quota_mode == "exact":
                constraint(terms, requested[p][h], requested[p][h])
            else:
                d = base_count + phases.index(p) * 3 + h - 2
                upper[d] = targets[p]["n"]
                constraint(terms + [(d, -1)], -np.inf, requested[p][h])
                constraint([(col, -value) for col, value in terms] + [(d, -1)], -np.inf, -requested[p][h])
        constraint([(ix[f, p] + 3, 1) for f in fs], targets[p]["min_families"], np.inf)
    quota_proof = None
    if quota_mode == "closest":
        first_matrix = coo_matrix((vv, (rr, cc)), shape=(len(lower_c), count)).tocsc()
        first_objective = np.zeros(count)
        first_objective[base_count:] = 1
        first = milp(first_objective, integrality=np.ones(count), bounds=Bounds(np.zeros(count), upper),
                     constraints=LinearConstraint(first_matrix, lower_c, upper_c),
                     options={"time_limit": float(time_limit), "mip_rel_gap": 0.0})
        if first.x is None or first.status not in (0, 1):
            raise ValueError(f"no admissible quota adjustment; status={first.status}: {first.message}")
        first_x = np.rint(first.x)
        if (not np.all(np.isfinite(first.x)) or np.max(np.abs(first.x - first_x)) > 1e-5
                or np.any(first_x < 0) or np.any(first_x > upper)
                or np.any(first_matrix @ first_x < lower_c) or np.any(first_matrix @ first_x > upper_c)):
            raise ValueError("invalid first-stage integer solution")
        optimum = int(sum(first_x[base_count:]))
        capacity = {h: sum(min(5, sum(e["hop"] == h for e in es)) for es in eligible.values()) for h in (2, 3, 4)}
        lower_bound = 2 * sum(max(0, sum(q[h] for q in requested.values()) - capacity[h]) for h in (2, 3, 4))
        if first.status != 0 and optimum != lower_bound:
            raise ValueError("minimum quota deviation not proved within limit")
        quota_proof = {"l1": optimum, "capacity_lower_bound": lower_bound,
                       "solver_status": int(first.status), "mip_gap": float(first.mip_gap),
                       "nodes": int(first.mip_node_count), "capacity_by_hop": capacity}
        constraint([(i, 1) for i in range(base_count, count)], optimum, optimum)
    matrix = coo_matrix((vv, (rr, cc)), shape=(len(lower_c), count)).tocsc()
    solved = milp(objective, integrality=np.ones(count), bounds=Bounds(np.zeros(count), upper),
                  constraints=LinearConstraint(matrix, lower_c, upper_c),
                  options={"time_limit": float(time_limit), "mip_rel_gap": 0.0})
    if solved.x is None or solved.status not in (0, 1):
        raise ValueError(f"no admissible allocation; solver status={solved.status}: {solved.message}")
    rounded = np.rint(solved.x)
    if not np.all(np.isfinite(solved.x)) or np.max(np.abs(solved.x - rounded)) > 1e-5:
        raise ValueError("solver values are not integral")
    x = rounded.astype(int)
    ax = matrix @ x
    if np.any(x < 0) or np.any(x > upper) or np.any(ax < lower_c) or np.any(ax > upper_c):
        raise ValueError("rounded solver vector violates constraints")
    assignments, panels = {}, {p: [] for p in phases}
    for (f, p), i in ix.items():
        if not x[i + 3]:
            continue
        assignments[f] = p
        for h in (2, 3, 4):
            tasks = sorted((e["task_id"] for e in eligible[f] if e["hop"] == h),
                           key=lambda t: (digest([seed, "task", p, f, h, t]), t))
            panels[p].extend(tasks[:int(x[i + h - 2])])
    for f, es in groups.items():
        if f not in blocked and {e["split"] for e in es} == {"dev"}:
            assignments[f] = "holdout"
    rows = [TaskMeta(e["task_id"], e["split"], e["hop"], tuple(e["subquestions"])) for e in source["entries"]]
    manifest = make_manifest(rows, exposed_ids=exposed, assignments=assignments,
                             seed=seed, source_hashes=source["source_hashes"])
    body = {"schema": "phase-allocation/v1", "seed": seed, "quota_mode": quota_mode,
            "quota_proof": quota_proof,
            "source_manifest_sha256": source["sha256"], "manifest": manifest,
            "targets": targets, "panels": {p: sorted(ts) for p, ts in panels.items()},
            "solver": {"status": int(solved.status), "message": str(solved.message),
                       "mip_gap": float(solved.mip_gap), "objective": float(solved.fun),
                       "nodes": int(solved.mip_node_count), "time_limit_seconds": time_limit}}
    result = dict(body, sha256=digest(body))
    validate_allocation(result, source, exposed_ids=exposed, targets=targets, seed=seed, quota_mode=quota_mode)
    return result


def validate_allocation(result, source, *, exposed_ids, targets=TARGETS, seed=SEED,
                        quota_mode="exact"):
    """Explicit constraint checker, without importing or rerunning the solver.

    Validates feasibility and externally supplied provenance, not optimality.
    """
    exposed, blocked, groups, eligible, weights = _input(source, exposed_ids, targets, seed)
    try:
        if (result["sha256"] != digest({k: v for k, v in result.items() if k != "sha256"})
                or result["schema"] != "phase-allocation/v1" or result["seed"] != seed
                or canonical(result["targets"]) != canonical(targets)
                or result["source_manifest_sha256"] != source["sha256"]
                or quota_mode not in ("exact", "closest") or result["quota_mode"] != quota_mode):
            raise ValueError("allocation binding changed")
        manifest = validate_manifest(result["manifest"])
        if manifest["source_hashes"] != source["source_hashes"] or manifest["exposed_ids"] != exposed:
            raise ValueError("manifest source or exposure binding changed")
        before = {e["task_id"]: {k: v for k, v in e.items() if k != "phase"} for e in source["entries"]}
        after = {e["task_id"]: {k: v for k, v in e.items() if k != "phase"} for e in manifest["entries"]}
        if before != after or manifest["seed"] != seed:
            raise ValueError("metadata or allocation seed changed")
        entries = {e["task_id"]: e for e in manifest["entries"]}
        assigned, summary, l1 = {}, {}, 0
        if set(result["panels"]) != set(targets):
            raise ValueError("missing or extra panel")
        for p, spec in targets.items():
            ids = result["panels"][p]
            if (not isinstance(ids, list) or len(ids) != spec["n"]
                    or any(not isinstance(t, str) for t in ids) or len(set(ids)) != len(ids)):
                raise ValueError("wrong panel size or duplicate task")
            selected = [entries[t] for t in ids]
            if any(e["phase"] != p or e["split"] != "train" or e["family_id"] not in eligible for e in selected):
                raise ValueError("panel violates phase rights")
            counts = Counter(e["family_id"] for e in selected)
            if len(counts) < spec["min_families"] or max(counts.values()) > 5:
                raise ValueError("family breadth or cap violated")
            hops = Counter(e["hop"] for e in selected)
            target_hops = quotas(spec["n"], weights)
            deviations = {h: hops[h] - n for h, n in target_hops.items()}
            l1 += sum(abs(v) for v in deviations.values())
            if quota_mode == "exact" and any(deviations.values()):
                raise ValueError("hop quotas violated")
            for f in counts:
                if f in assigned:
                    raise ValueError("family used in multiple phases")
                assigned[f] = p
            summary[p] = {"selected_tasks": len(ids), "families": len(counts),
                          "selected_hops": dict(sorted(hops.items())), "target_hops": target_hops,
                          "hop_deviations": deviations,
                          "max_selected_per_family": max(counts.values()),
                          "reserved_tasks": sum(len(groups[f]) for f in counts)}
        for e in manifest["entries"]:
            f = e["family_id"]
            splits = {r["split"] for r in groups[f]}
            expected = ("excluded" if f in blocked else "holdout" if splits == {"dev"}
                        else assigned.get(f, "unused"))
            if e["phase"] != expected:
                raise ValueError("unselected family member has wrong role")
        if quota_mode == "closest":
            proof = result["quota_proof"]
            capacity = {h: sum(min(5, sum(e["hop"] == h for e in es)) for es in eligible.values()) for h in (2, 3, 4)}
            lower_bound = 2 * sum(max(0, sum(quotas(s["n"], weights)[h] for s in targets.values()) - capacity[h]) for h in (2, 3, 4))
            if (proof["l1"] != l1 or proof["capacity_lower_bound"] != lower_bound
                    or (proof["solver_status"] != 0 and l1 != lower_bound)):
                raise ValueError("quota minimum proof inconsistent")
        return {"panels": summary, "quota_l1": l1,
                "phase_tasks": dict(sorted(Counter(e["phase"] for e in entries.values()).items())),
                "phase_families": {p: len({e["family_id"] for e in entries.values() if e["phase"] == p})
                                   for p in sorted({e["phase"] for e in entries.values()})},
                "target_hops": weights}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("malformed allocation") from error


def repeat_subset(result, n=50):
    """Pre-outcome spatial repetition panel; no error/quality-based selection."""
    ids = result["panels"]["spatial"]
    if type(n) is not int or not 0 < n <= len(ids):
        raise ValueError("invalid repeat subset size")
    entries = {e["task_id"]: e for e in result["manifest"]["entries"]}
    weights = dict(Counter(entries[t]["hop"] for t in ids))
    requested = quotas(n, weights)
    selected = []
    for h, count in requested.items():
        candidates = sorted((t for t in ids if entries[t]["hop"] == h),
                            key=lambda t: (digest([result["seed"], "spatial-repeat", h, t]), t))
        selected.extend(candidates[:count])
    return {"allocation_sha256": result["sha256"], "task_ids": sorted(selected),
            "hop_counts": requested, "n": n, "reason": "pre-outcome repetition; not extra training weight"}
