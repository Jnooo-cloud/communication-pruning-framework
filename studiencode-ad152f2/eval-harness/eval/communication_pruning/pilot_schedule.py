"""Offline Z16 pilot ordering, not an executor or a data/budget release.

Requires a complete phase manifest and externally supplied trusted bindings.
Policy digests identify retained files; they do not establish empirical training.
"""

from collections import Counter
import json
from pathlib import Path
import re

from .data import canonical, digest, validate_manifest


BINDINGS = {"q_policy", "fixed_policy", "execution_contract"}
SEED = "Z16-pilot-order-2026-09-07-v1"


def make_schedule(manifest, task_ids, *, bindings, seed=SEED):
    """Build three passes of 120 adjacent Q/F pairs, balanced in blocks of 20.

    Selected IDs are supplied, never sampled here. Only metadata are inspected.
    Rank by domain-separated SHA256, with ID tie breaks, for portable replay.
    """
    validate_manifest(manifest)
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("explicit nonempty ordering seed required")
    if (not isinstance(bindings, dict) or set(bindings) != BINDINGS
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                   for v in bindings.values())):
        raise ValueError("three externally bound SHA256 values required")
    if (not isinstance(task_ids, (list, tuple)) or len(task_ids) != 120
            or any(not isinstance(t, str) or not t for t in task_ids)
            or len(set(task_ids)) != 120):
        raise ValueError("exactly 120 unique task IDs required")
    entries = {e["task_id"]: e for e in manifest["entries"]}
    selected = []
    for task_id in sorted(task_ids):
        e = entries.get(task_id)
        if e is None or e["phase"] != "pilot" or e["split"] != "train":
            raise ValueError("all selected tasks must be eligible train pilot tasks")
        selected.append(e)
    counts = Counter(e["family_id"] for e in selected)
    if len(counts) < 80 or max(counts.values()) > 5:
        raise ValueError("at least 80 families and at most five selected tasks each")

    def rank(domain, repeat, task_id, block=None):
        return digest([seed, domain, repeat, block, task_id]), task_id

    slots = []
    for repeat in range(1, 4):
        ordered = sorted(selected, key=lambda e: rank("task", repeat, e["task_id"]))
        for start in range(0, 120, 20):
            block = (repeat - 1) * 6 + start // 20 + 1
            chunk = ordered[start:start + 20]
            q_first = {e["task_id"] for e in sorted(
                chunk, key=lambda e: rank("arm", repeat, e["task_id"], block))[:10]}
            for e in chunk:
                pair = len(slots) // 2 + 1
                arms = ("Q", "F*") if e["task_id"] in q_first else ("F*", "Q")
                for position, arm in enumerate(arms, 1):
                    slots.append({
                        "slot_id": f"P{pair:03d}-{position}",
                        "pair": pair, "repeat": repeat, "block": block,
                        "task_id": e["task_id"], "family_id": e["family_id"],
                        "arm": arm, "position": position, "fresh_context": True,
                    })
    body = {
        "schema": "pilot-schedule/v1", "status": "prepared_not_authorized",
        "manifest_sha256": manifest["sha256"], "bindings": dict(bindings),
        "seed": seed, "task_ids": sorted(task_ids), "repetitions": 3,
        "block_pairs": 20, "slots": slots,
        "summary": {"tasks": 120, "families": len(counts), "pairs": 360,
                    "runs": 720, "max_model_calls_without_retry": 5040,
                    "hop_counts": dict(sorted(Counter(str(e["hop"]) for e in selected).items()))},
    }
    return dict(body, sha256=digest(body))


def validate_schedule(schedule, manifest, *, expected_bindings, expected_seed=SEED,
                      expected_task_ids):
    """Rebuild from external expectations, not a possibly rewritten plan header."""
    expected = make_schedule(manifest, expected_task_ids, bindings=expected_bindings,
                             seed=expected_seed)
    # Canonical bytes also distinguish JSON true/1 and reject extra fields.
    try:
        if canonical(schedule) != canonical(expected):
            raise ValueError("schedule differs from externally bound plan")
    except (TypeError, OverflowError) as error:
        raise ValueError("malformed schedule") from error
    return schedule


def save_schedule(path, schedule, manifest, *, expected_bindings, expected_seed=SEED,
                  expected_task_ids):
    validate_schedule(schedule, manifest, expected_bindings=expected_bindings,
                      expected_seed=expected_seed, expected_task_ids=expected_task_ids)
    # Exclusive creation: existing files and symlinks are never overwritten.
    with Path(path).open("x", encoding="utf-8") as output:
        output.write(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n")
