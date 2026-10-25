"""Recount Z12 structure evidence and replay via separate counting code."""

import bisect
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import itertools
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "eval-harness/eval"


def main():
    folder = ARTIFACT / "runs/Z12-STRUCT-001"
    output = ARTIFACT / "runs/Z12-VERIFY-001"
    output.mkdir(mode=0o700, exist_ok=False)
    verification = dict(started_at=datetime.now(timezone.utc).isoformat(), status="running",
                        model_cost_usd="0", verifier="same_agent_separate_counting_code", checks=[])
    sources = sorted(set((ARTIFACT / "communication_pruning").glob("*.py")) |
                     set((ARTIFACT / "tests").glob("*.py")) |
                     {ARTIFACT / "README.md", ROOT / "project/dsr/Z12-PLAN.md"})
    hashes = {}
    with zipfile.ZipFile(output / "source.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            data = path.read_bytes(); relative = str(path.relative_to(ROOT))
            hashes[relative] = sha256(data).hexdigest(); archive.writestr(relative, data)
    verification["source_manifest"] = hashes
    verification["source_sha256"] = sha256((output / "source.zip").read_bytes()).hexdigest()
    try:
        receipt_bytes = (folder / "receipt.json").read_bytes()
        receipt = json.loads(receipt_bytes)
        verification["receipt_sha256"] = sha256(receipt_bytes).hexdigest()
        assert receipt["status"] == "completed" and receipt["source_unchanged_during_run"]
        assert sha256((folder / "source.zip").read_bytes()).hexdigest() == receipt["source_bundle_sha256"]
        with zipfile.ZipFile(folder / "source.zip") as archive:
            assert set(archive.namelist()) == set(receipt["files_sha256"])
            for path, expected in receipt["files_sha256"].items():
                assert sha256(archive.read(path)).hexdigest() == expected
                assert sha256((ROOT / path).read_bytes()).hexdigest() == expected
        raw = (folder / "trials.jsonl").read_bytes()
        assert sha256(raw).hexdigest() == receipt["trials_sha256"]
        rows = [json.loads(line) for line in raw.splitlines()]
        assert len(rows) == 30000 and receipt["draws"] == 10000
        assert all(set(row) == {"n", "iteration", "seed", "families", "largest"} for row in rows)
        hist = receipt["inventory"]["splits"]["dev"]["family_size_histogram"]
        sizes = tuple(m for m, count in sorted((int(m), count) for m, count in hist.items()) for _ in range(count))
        ends = tuple(itertools.accumulate(sizes))
        for result in receipt["results"]:
            n = result["n"]
            selected = [r for r in rows if r["n"] == n]
            assert [r["iteration"] for r in selected] == list(range(10000))
            assert all(r["seed"] == 20260906012 * 10**12 + n * 10**6 + r["iteration"] for r in selected)
            for field, report in (("families", "observed_families"), ("largest", "largest_observed_family")):
                values = [r[field] for r in selected]
                assert statistics.mean(values) == result[report]["mean"]
                assert statistics.stdev(values) == result[report]["sd"]
            # Direct cumulative-boundary membership, not the production counter.
            first = selected[0]
            positions = random.Random(first["seed"]).sample(range(sum(sizes)), n)
            counts = Counter(bisect.bisect_right(ends, i) for i in positions)
            assert len(counts) == first["families"] and max(counts.values()) == first["largest"]
            verification["checks"].append(dict(n=n, rows=len(selected), recount=True, first_seed_replay=True))
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
        run = subprocess.run(command, cwd=ARTIFACT, text=True, capture_output=True, timeout=180)
        verification["regression"] = dict(command=command, returncode=run.returncode, stdout=run.stdout, stderr=run.stderr)
        assert run.returncode == 0
        verification["status"] = "completed"
    except BaseException as error:
        verification["status"] = "failed_or_interrupted"; verification["error_type"] = type(error).__name__
        raise
    finally:
        verification["ended_at"] = datetime.now(timezone.utc).isoformat()
        verification["source_unchanged_during_run"] = all(sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
        with (output / "receipt.json").open("x") as stream:
            json.dump(verification, stream, indent=2, allow_nan=False); stream.write("\n")
        print(output / "receipt.json", verification["status"])


if __name__ == "__main__":
    main()
