"""Metadata-only full 14-configuration development plan. Never executes models."""
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from .configurations import bank
from .data import canonical, digest, validate_manifest
from .selection import family_partition


SEED = "Z19-spatial-order-2026-09-07-v1"
CV_SEED = "Z19-spatial-cv-2026-09-07-v1"


def make_plan(manifest, task_ids, repeat_ids, *, bindings, seed=SEED):
    validate_manifest(manifest)
    if (len(task_ids) != 300 or len(set(task_ids)) != 300 or len(repeat_ids) != 50
            or len(set(repeat_ids)) != 50 or not set(repeat_ids) <= set(task_ids)):
        raise ValueError("prebound 300 tasks and 50 unique repeats required")
    if not isinstance(seed, str) or not seed:
        raise ValueError("explicit seed required")
    if (set(bindings) != {"allocation", "repetition", "source"}
            or any(not isinstance(v, str) or len(v) != 64
                   or any(c not in "0123456789abcdef" for c in v) for v in bindings.values())):
        raise ValueError("three external SHA256 bindings required")
    entries = {e["task_id"]: e for e in manifest["entries"]}
    if any(t not in entries or entries[t]["phase"] != "spatial" or entries[t]["split"] != "train" for t in task_ids):
        raise ValueError("only selected spatial training tasks allowed")
    counts = Counter(entries[t]["family_id"] for t in task_ids)
    if len(counts) < 100 or max(counts.values()) > 5:
        raise ValueError("spatial family breadth/cap violated")
    def rank(*parts):
        return digest([seed, *parts])
    configurations = bank()
    slots = []
    for repeat, ids in ((1, task_ids), (2, repeat_ids)):
        ordered = sorted(ids, key=lambda t: (rank("task", repeat, t), t))
        for start in range(0, len(ordered), 14):
            block = start // 14 + 1
            base = sorted(configurations, key=lambda c: (rank("config", repeat, block, c.config_id), c.config_id))
            for offset, task in enumerate(ordered[start:start + 14]):
                order = base[offset:] + base[:offset]
                for position, config in enumerate(order, 1):
                    slots.append({"slot_id": f"S{len(slots) + 1:05d}", "task_id": task,
                                  "family_id": entries[task]["family_id"], "repeat": repeat,
                                  "block": block, "config_id": config.config_id,
                                  "position": position, "rounds": 2, "fresh_context": True,
                                  "planned_calls": 2 * len(config.roles) + 1})
    def fold_ids(ids):
        assignment = family_partition({t: entries[t]["family_id"] for t in ids}, seed=CV_SEED)
        return [sorted(t for t in ids if assignment[entries[t]["family_id"]] == i) for i in range(5)]
    family_order = sorted(counts, key=lambda f: (rank("learning-family", f), f))
    curves = []
    for target in (100, 200, 300):
        chosen = []
        for f in family_order:
            chosen += sorted(t for t in task_ids if entries[t]["family_id"] == f)
            if len(chosen) >= target:
                break
        curves.append({"target": target, "n": len(chosen), "task_ids": sorted(chosen), "folds": fold_ids(chosen)})
    body = {"schema": "spatial-plan/v1", "status": "prepared_not_authorized",
            "manifest_sha256": manifest["sha256"], "bindings": dict(bindings), "seed": seed,
            "cv_seed": CV_SEED, "task_ids": sorted(task_ids), "repeat_ids": sorted(repeat_ids),
            "configurations": [asdict(c) for c in configurations], "slots": slots,
            "folds": fold_ids(task_ids), "learning_curves": curves,
            "proposed_producer_limit": 1024, "proposed_aggregator_limit": 128,
            "proposed_phase_cap_usd": "36.12", "reservation_usd": "0.14",
            "summary": {"tasks": 300, "families": len(counts), "runs": len(slots),
                        "model_calls_without_retry": sum(s["planned_calls"] for s in slots)}}
    # Normalize tuples from Configuration to JSON arrays for exact file replay.
    body = json.loads(canonical(body))
    return dict(body, sha256=digest(body))


def validate_plan(plan, manifest, task_ids, repeat_ids, *, bindings, seed=SEED, iteration_contract=None):
    if iteration_contract is None:
        expected = make_plan(manifest, task_ids, repeat_ids, bindings=bindings, seed=seed)
    else:
        if bindings != iteration_bindings(iteration_contract):
            raise ValueError("iteration bindings differ from external contract")
        legacy = make_plan(manifest, task_ids, repeat_ids,
                           bindings=plan.get("legacy_bindings", {}), seed=seed)
        expected = make_iteration_plan(manifest, task_ids, repeat_ids,
                                       contract=iteration_contract, legacy_plan=legacy)
    if canonical(plan) != canonical(expected):
        raise ValueError("plan differs from externally bound inputs")
    return plan


# Z38 is one specific second development, not an unrestricted phase factory.
ITERATION_ID = "QSEM-2026-09-13-v1"
ITERATION_SCHEMA = "spatial-plan/v2"
ITERATION_EVIDENCE = frozenset({"design", "source", "source_manifest", "prompt",
    "provider_catalog", "tariff", "data_binding", "manifest", "allocation",
    "repetition", "ordering", "exposure"})


def _sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def make_iteration_contract(evidence, *, legacy_plan_sha256):
    """Bind file identities and fixed Z38 controls; no files or contents loaded."""
    from pathlib import PurePosixPath
    from .failure_policy import F01
    from .openrouter import MODEL, PROVIDER
    if not isinstance(evidence, dict) or set(evidence) != ITERATION_EVIDENCE or not _sha(legacy_plan_sha256):
        raise ValueError("complete iteration evidence and legacy plan identity required")
    for entry in evidence.values():
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("evidence must name a path and SHA256")
        path = entry["path"]
        if (not isinstance(path, str) or not path or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts or "\\" in path or not _sha(entry["sha256"])):
            raise ValueError("evidence paths must remain within the project")
    body = {"schema": "spatial-iteration/v1", "iteration_id": ITERATION_ID,
            "legacy_plan_sha256": legacy_plan_sha256,
            "phase_cap_usd": "12.00", "reservation_usd": "0.14",
            "model": MODEL, "provider": PROVIDER, "producer_limit": 1024,
            "aggregator_limit": 128, "failure_policy": F01, "retry_policy": "none",
            "evidence": json.loads(canonical(evidence))}
    return dict(body, sha256=digest(body))


def validate_iteration_contract(contract):
    if not isinstance(contract, dict):
        raise ValueError("external iteration contract required")
    expected = make_iteration_contract(contract.get("evidence"),
                                      legacy_plan_sha256=contract.get("legacy_plan_sha256"))
    if canonical(contract) != canonical(expected):
        raise ValueError("iteration contract controls or identity changed")
    return contract


def iteration_bindings(contract):
    evidence = validate_iteration_contract(contract)["evidence"]
    return {"source": evidence["source"]["sha256"],
            "allocation": evidence["allocation"]["sha256"],
            "repetition": evidence["repetition"]["sha256"]}


def make_iteration_plan(manifest, task_ids, repeat_ids, *, contract, legacy_plan):
    """Preserve the complete externally bound Z19 ordering, folds and panels."""
    validate_iteration_contract(contract)
    validate_plan(legacy_plan, manifest, task_ids, repeat_ids,
                  bindings=legacy_plan["bindings"])
    if legacy_plan["sha256"] != contract["legacy_plan_sha256"]:
        raise ValueError("legacy ordering differs from external iteration contract")
    body = {k: v for k, v in legacy_plan.items() if k != "sha256"}
    body.update(schema=ITERATION_SCHEMA, iteration_id=ITERATION_ID,
                iteration_contract_sha256=contract["sha256"],
                legacy_plan_sha256=legacy_plan["sha256"],
                legacy_bindings=legacy_plan["bindings"], bindings=iteration_bindings(contract),
                proposed_phase_cap_usd=contract["phase_cap_usd"],
                reservation_usd=contract["reservation_usd"])
    body = json.loads(canonical(body))
    return dict(body, sha256=digest(body))


def phase_key(plan):
    """Claim AND lock key: a new plan hash cannot reset this iteration."""
    if plan.get("schema") == ITERATION_SCHEMA:
        if plan.get("iteration_id") != ITERATION_ID:
            raise ValueError("unexpected iteration namespace")
        return ITERATION_ID
    if "iteration_id" in plan or "iteration_contract_sha256" in plan:
        raise ValueError("iteration cannot be disguised as a legacy plan")
    return plan["sha256"]


def iteration_claim(plan):
    if plan.get("schema") == ITERATION_SCHEMA:
        phase_key(plan)
        return {"iteration_id": ITERATION_ID,
                "iteration_contract_sha256": plan["iteration_contract_sha256"]}
    return {}


def save_plan(path, plan, manifest, task_ids, repeat_ids, *, bindings, seed=SEED):
    validate_plan(plan, manifest, task_ids, repeat_ids, bindings=bindings, seed=seed)
    with Path(path).open("x") as out:
        json.dump(plan, out, indent=2); out.write("\n")
