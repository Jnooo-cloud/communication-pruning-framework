"""Content-free, fixed P/R/T/F study planning under the Z50 contract.

Plans identify fresh draws and fresh slots. A plan hash is an identity, never a
data-access, study-freeze or spending permission. This module has no loader.
"""
from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import re

import numpy as np

from communication_pruning.contracts import ROLES


ARMS = {
    "P": ("Q", "F"),
    "R": ("S", "S-k", "D", "Z", "Q", "F"),
    "T": ("Q-ST", "Q-TF"),
    "F": ("Qc", "Qf", "Fc", "Ff"),
}
DEFAULT_COUNTS = {"P": 9040, "R": 2952, "T": 2952, "F": 2952}
REQUIRED_BINDINGS = (
    "design", "analysis_contract", "source_manifest", "frame_metadata",
    "exposure_metadata", "spatial_q", "spatial_f", "temporal_qst", "temporal_qtf",
)
SEED_RULE = "SHA256(canonical JSON [Z50-final-plan-v1, study_id, seed_base, panel, stream]); first 16 bytes little endian"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_STUDY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def canonical_hash(value):
    """Hash strict canonical JSON; reject nonfinite and non-JSON values."""
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("strict JSON value required") from exc
    return hashlib.sha256(payload).hexdigest()


def _identifier(value, name, *, study=False):
    pattern = _STUDY_ID if study else _IDENTIFIER
    if not isinstance(value, str) or not pattern.fullmatch(value) or ".." in value:
        raise ValueError(f"{name} must be a safe nonempty identifier")
    return value


def _inputs(frame, seed_base, bindings, mode, counts, study_id):
    if mode not in ("artificial_only", "live_candidate"):
        raise ValueError("unknown plan mode")
    if type(seed_base) is not int or seed_base < 0:
        raise ValueError("seed_base must be a nonnegative integer")
    _identifier(study_id, "study_id", study=True)
    if type(frame) is not list or not frame:
        raise ValueError("nonempty metadata frame required")
    clean_frame, seen = [], set()
    for item in frame:
        if type(item) is not dict or set(item) != {"task_id", "family_id"}:
            raise ValueError("frame permits only task_id and family_id")
        task = _identifier(item["task_id"], "task_id")
        family = _identifier(item["family_id"], "family_id")
        if task in seen:
            raise ValueError("duplicate task_id in frame")
        seen.add(task)
        clean_frame.append({"task_id": task, "family_id": family})
    if type(bindings) is not dict or not bindings:
        raise ValueError("nonempty SHA256 bindings required")
    for key, value in bindings.items():
        _identifier(key, "binding name")
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError("binding values must be lowercase SHA256")
    if mode == "live_candidate" and not set(REQUIRED_BINDINGS) <= set(bindings):
        raise ValueError("live candidate lacks required external bindings")
    selected = dict(DEFAULT_COUNTS) if counts is None else counts
    if (type(selected) is not dict or set(selected) != set(ARMS)
            or any(type(n) is not int or n < 1 for n in selected.values())):
        raise ValueError("counts must contain one positive integer for each P/R/T/F panel")
    if mode != "artificial_only" and selected != DEFAULT_COUNTS:
        raise ValueError("live counts are fixed at 9040/2952/2952/2952")
    return clean_frame, dict(bindings), {panel: selected[panel] for panel in ARMS}


def _stream_seeds(study_id, seed_base):
    seeds = {}
    for panel in ARMS:
        streams = ["panel", "order"]
        if panel == "R":
            streams += ["z", "tie_break"]
        if panel == "F":
            streams += ["fault"]
        seeds[panel] = {
            stream: int.from_bytes(bytes.fromhex(canonical_hash(
                ["Z50-final-plan-v1", study_id, seed_base, panel, stream]))[:16], "little")
            for stream in streams
        }
    return seeds


def _panels(frame, counts, study_id, seeds):
    # Preserve frame order. Family PPS is an integer ticket draw followed by
    # an independent uniform member draw, both with replacement.
    families = {}
    for item in frame:
        families.setdefault(item["family_id"], []).append(item)
    members = list(families.values())
    cumulative, total = [], 0
    for family in members:
        total += len(family)
        cumulative.append(total)
    panels = {}
    for panel, arms in ARMS.items():
        rng = {name: np.random.Generator(np.random.PCG64(value))
               for name, value in seeds[panel].items()}
        blocks = []
        for index in range(counts[panel]):
            if panel == "F":
                family = members[bisect_right(cumulative, int(rng["panel"].integers(total)))]
                item = family[int(rng["panel"].integers(len(family)))]
            else:
                item = frame[int(rng["panel"].integers(len(frame)))]
            block_id = f"{study_id}:{panel}:{index:05d}"
            order = [arms[int(i)] for i in rng["order"].permutation(len(arms))]
            block = {
                "panel": panel, "block_id": block_id, "draw_index": index,
                "task_id": item["task_id"], "family_id": item["family_id"],
                "arm_order": order,
                "slots": [{"slot_id": f"{block_id}:{arm}", "arm": arm} for arm in order],
            }
            if panel == "R":
                block["z_configuration"] = f"C{int(rng['z'].integers(1, 15)):02d}"
                block["tie_break_seed"] = int(rng["tie_break"].integers(0, 2**63 - 1))
            if panel == "F":
                block["fault_permutation"] = [ROLES[int(i)] for i in rng["fault"].permutation(len(ROLES))]
            blocks.append(block)
        panels[panel] = blocks
    return panels


def make_plan(frame, *, seed_base, bindings, mode="live_candidate", counts=None,
              study_id="Z50-STUDY-v1"):
    """Draw only metadata; a repeated task always gets a new block and slots."""
    frame, bindings, counts = _inputs(frame, seed_base, bindings, mode, counts, study_id)
    seeds = _stream_seeds(study_id, seed_base)
    plan = {
        "schema": 1, "mode": mode, "study_id": study_id, "seed_base": seed_base,
        "bindings": bindings, "frame": frame, "frame_hash": canonical_hash(frame),
        "counts": counts,
        "randomization": {"algorithm": "PCG64", "seed_rule": SEED_RULE,
                          "streams": seeds, "replacement": True,
                          "fault_sampling": "family_PPS_Nf_then_uniform_member"},
        "panels": _panels(frame, counts, study_id, seeds),
    }
    plan["plan_hash"] = canonical_hash(plan)
    return plan


def validate_plan(plan):
    """Reject changed identities, incomplete slots and nonreproducible draws.

    Validation replays content-free randomization. Even a caller that recomputes
    a hash cannot silently alter a slot or the frozen draw procedure.
    """
    keys = {"schema", "mode", "study_id", "seed_base", "bindings", "frame",
            "frame_hash", "counts", "randomization", "panels", "plan_hash"}
    if type(plan) is not dict or set(plan) != keys or type(plan["schema"]) is not int or plan["schema"] != 1:
        raise ValueError("invalid final plan schema")
    if not isinstance(plan["plan_hash"], str) or not _SHA256.fullmatch(plan["plan_hash"]):
        raise ValueError("invalid plan hash")
    unhashed = {key: value for key, value in plan.items() if key != "plan_hash"}
    if canonical_hash(unhashed) != plan["plan_hash"]:
        raise ValueError("plan hash mismatch")
    expected = make_plan(plan["frame"], seed_base=plan["seed_base"], bindings=plan["bindings"],
                         mode=plan["mode"], counts=plan["counts"], study_id=plan["study_id"])
    # Canonical hashes distinguish e.g. bool from int where Python equality does not.
    if canonical_hash(expected) != canonical_hash(plan):
        raise ValueError("plan identities, complete blocks or randomization do not match the bound seed")
    return plan
