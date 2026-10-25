"""Metadata-only technical sample selection and settled-prior budget checks."""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

from .data import families, make_manifest
from .openrouter import LIMIT, MAX_CALLS, RESERVE, ProbeStop, number

SEED = "Z07-technical-2026-09-06-v1"
SOURCE_HASHES = {"train": "83a75b1e11e4e9bb8f8308e72ac40ca617ae4431b3a0d955b61cab259248490a",
                 "dev": "15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b"}
DATA_PATH = "archive/neustart-2026-08-30/legacy-artifact/eval-harness/data/vendor/musique-v1.0/data"


def exposed_ids(register):
    return set(re.findall(r"`([234]hop\d*__[\d_]+)`", register))


def select_technical(metadata, excluded, source_hashes, *, seed=SEED):
    rows = tuple(metadata)
    mapping = families(rows)
    if set(excluded) - set(mapping):
        raise ValueError("unknown exposure identity")
    blocked = {mapping[t] for t in excluded}
    groups = defaultdict(list)
    for row in rows:
        groups[mapping[row.task_id]].append(row)
    def tie(kind, identity, hop):
        return sha256(json.dumps([seed, kind, identity, hop]).encode()).hexdigest()
    selected, used = [], set()
    for hop in (2, 4):
        eligible = [f for f, members in groups.items() if f not in blocked | used
                    and all(r.split == "train" for r in members) and any(r.hop == hop for r in members)]
        if not eligible:
            raise ValueError("technical hop has no eligible independent family")
        family = min(eligible, key=lambda f: (len(groups[f]), tie("family", f, hop), f))
        task = min((r for r in groups[family] if r.hop == hop),
                   key=lambda r: (tie("task", r.task_id, hop), r.task_id))
        selected.append({"task_id": task.task_id, "hop": hop, "family_id": family,
                         "members": sorted(r.task_id for r in groups[family])})
        used.add(family)
    manifest = make_manifest(rows, exposed_ids=excluded, assignments={f: "technical" for f in used},
                             seed=seed, source_hashes=source_hashes)
    return selected, manifest


def budget_check(prior, *, tasks=2):
    if type(tasks) is not int or tasks != 2:
        raise ProbeStop("exactly two technical tasks authorized by Z07 plan")
    if (prior.get("status") != "completed" or prior.get("calls_reserved") != 5
            or prior.get("total_cost_usd") is None or not prior.get("source_unchanged")
            or prior.get("run_id") != "Z06-OPENROUTER-002"):
        raise ProbeStop("prior technical spending is not settled")
    cost = number(prior["total_cost_usd"])
    if cost != number(prior["known_cost_subtotal_usd"]) or cost != number(prior["provider_audit"]["cost_usd"]):
        raise ProbeStop("prior cost evidence disagrees")
    maximum = cost + tasks * MAX_CALLS * RESERVE
    if maximum > LIMIT:
        raise ProbeStop("combined technical spending would exceed authorization")
    return {"prior_cost_usd": str(cost), "new_reservation_usd": str(tasks * MAX_CALLS * RESERVE),
            "maximum_combined_usd": str(maximum), "authorization_limit_usd": str(LIMIT)}


def verify_prior(root):
    """Check preserved Z06 receipts, without comparing old code to current code."""
    root = Path(root)
    prior = json.loads((root / "project/dsr/Z06-LIVE-002.json").read_bytes())
    for run in ("001", "002"):
        receipt = json.loads((root / f"project/dsr/Z06-LIVE-{run}.json").read_bytes())
        if receipt["run_id"] != f"Z06-OPENROUTER-{run}":
            raise ProbeStop("prior run identity mismatch")
        if run == "001" and (receipt["calls_reserved"] != 0 or number(receipt["total_cost_usd"]) != 0):
            raise ProbeStop("unaccounted prior preflight spending")
        folder = root / receipt["evidence_folder"]
        for name, digest in receipt["files_sha256"].items():
            if sha256((folder / name).read_bytes()).hexdigest() != digest:
                raise ProbeStop("prior evidence file changed")
    return budget_check(prior)
