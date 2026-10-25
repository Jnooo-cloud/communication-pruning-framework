"""Create-only Z12 structural evidence. No content loader, model or network call."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys
import zipfile

from .data import families, index_file
from .sampling import expected_families, family_counts, sample_positions

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "eval-harness/eval"
SEED = 20260906012
HASHES = {"train": "83a75b1e11e4e9bb8f8308e72ac40ca617ae4431b3a0d955b61cab259248490a",
          "dev": "15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b"}


def metadata_inventory():
    base = ROOT / "archive/neustart-2026-08-30/legacy-artifact/eval-harness/data/vendor/musique-v1.0/data"
    register = (ROOT / "project/DATENEXPOSITIONSREGISTER.md").read_bytes()
    exposed = set(re.findall(r"`([234]hop\d*__[\d_]+)`", register.decode()))
    rows = tuple(r for split in HASHES for r in index_file(
        base / f"musique_ans_v1.0_{split}.jsonl", split, HASHES[split]))
    mapping = families(rows)
    if exposed - set(mapping):
        raise ValueError("registered exposure missing from structural index")
    blocked = {mapping[t] for t in exposed}
    family_splits = defaultdict(set)
    for r in rows:
        family_splits[mapping[r.task_id]].add(r.split)
    if any(len(s) != 1 for s in family_splits.values()):
        raise ValueError("shared train/dev family")
    result = dict(mode="metadata_only_no_content_exposure", source_hashes=HASHES,
                  exposure_register_sha256=sha256(register).hexdigest(),
                  exposed_ids_count=len(exposed), cross_split_families=0, splits={})
    for split in HASHES:
        eligible = [r for r in rows if r.split == split and mapping[r.task_id] not in blocked]
        sizes = Counter(mapping[r.task_id] for r in eligible)
        result["splits"][split] = dict(tasks=len(eligible), families=len(sizes),
            largest_family=max(sizes.values()), hops=dict(Counter(r.hop for r in eligible)),
            family_size_histogram=dict(sorted(Counter(sizes.values()).items())))
    if [(s["tasks"], s["families"]) for s in result["splits"].values()] != [(17423, 1007), (2277, 535)]:
        raise ValueError("unexpected eligible inventory; investigate before proceeding")
    if result["splits"]["dev"]["largest_family"] != 58:
        raise ValueError("unexpected largest dev family")
    return result


def moments(xs):
    sd = statistics.stdev(xs)
    return dict(mean=statistics.mean(xs), sd=sd, mc_se=sd / math.sqrt(len(xs)), min=min(xs), max=max(xs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run")
    parser.add_argument("--draws", type=int, default=10000)
    args = parser.parse_args()
    if not args.run.isdigit() or args.draws < 2:
        parser.error("numeric run id and at least two draws required")
    folder = ARTIFACT / "runs" / ("Z12-STRUCT-" + args.run)
    folder.mkdir(mode=0o700, exist_ok=False)
    now = lambda: datetime.now(timezone.utc).isoformat()
    files = sorted(set((ARTIFACT / "communication_pruning").glob("*.py")) |
                   set((ARTIFACT / "tests").glob("*.py")) |
                   {ROOT / "project/dsr/Z12-PLAN.md", ROOT / "project/DATENEXPOSITIONSREGISTER.md", ARTIFACT / "README.md"})
    hashes = {}
    with zipfile.ZipFile(folder / "source.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            data = path.read_bytes(); name = str(path.relative_to(ROOT))
            hashes[name] = sha256(data).hexdigest(); archive.writestr(name, data)
    receipt = dict(run_id=folder.name, started_at=now(), status="running", python=sys.version,
                   executable=sys.executable, command=sys.argv, master_seed=SEED, draws=args.draws,
                   model_cost_usd="0", files_sha256=hashes, tests=[], results=[],
                   source_bundle_sha256=sha256((folder / "source.zip").read_bytes()).hexdigest())
    try:
        for command in ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                        [sys.executable, "-m", "communication_pruning"],
                        [sys.executable, "-m", "communication_pruning.demo"]):
            r = subprocess.run(command, cwd=ARTIFACT, capture_output=True, text=True, timeout=180)
            receipt["tests"].append(dict(command=command, returncode=r.returncode, stdout=r.stdout, stderr=r.stderr))
        if any(t["returncode"] for t in receipt["tests"]):
            raise RuntimeError("regression failed; see preserved test outputs")
        inventory = metadata_inventory(); receipt["inventory"] = inventory
        hist = inventory["splits"]["dev"]["family_size_histogram"]
        sizes = tuple(m for m, count in sorted(hist.items()) for _ in range(count))
        with (folder / "trials.jsonl").open("x") as raw:
            for n in (800, 1500, 2277):
                represented, largest = [], []
                for i in range(args.draws):
                    seed = SEED * 10**12 + n * 10**6 + i
                    counts = family_counts(sizes, sample_positions(sizes, n, seed))
                    record = dict(n=n, iteration=i, seed=seed, families=sum(c > 0 for c in counts), largest=max(counts))
                    raw.write(json.dumps(record) + "\n")
                    represented.append(record["families"]); largest.append(record["largest"])
                stats = moments(represented); expected = expected_families(sizes, n)
                result = dict(n=n, draws=args.draws, expected_families=expected, observed_families=stats,
                              largest_observed_family=moments(largest), fraction=n / sum(sizes),
                              fixed_value_variance_factor=1 - n / sum(sizes),
                              within_5_mcse=abs(stats["mean"] - expected) <= max(1e-12, 5 * stats["mc_se"]))
                receipt["results"].append(result); print(json.dumps(result), flush=True)
        if not all(r["within_5_mcse"] for r in receipt["results"]):
            raise RuntimeError("structural expectation check failed")
        receipt["status"] = "completed"
    except BaseException as error:
        # No traceback locals/raw benchmark lines are ever copied into evidence.
        receipt["status"] = "failed_or_interrupted"
        receipt["error_type"] = type(error).__name__
        raise
    finally:
        receipt["ended_at"] = now()
        receipt["source_unchanged_during_run"] = all(sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
        if (folder / "trials.jsonl").exists():
            receipt["trials_sha256"] = sha256((folder / "trials.jsonl").read_bytes()).hexdigest()
        with (folder / "receipt.json").open("x") as output:
            json.dump(receipt, output, indent=2, allow_nan=False); output.write("\n")
        print("Evidence:", folder / "receipt.json", receipt["status"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
