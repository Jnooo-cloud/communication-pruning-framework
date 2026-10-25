"""Create-only Z16 source-bound offline validation; no benchmark or provider calls."""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import zipfile

from .data import canonical, digest
from .pilot_schedule import make_schedule, save_schedule, validate_schedule


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def main(run_id):
    if not re.fullmatch(r"[0-9]{3}", run_id):
        raise ValueError("three-digit unused run ID required")
    root = Path(__file__).resolve().parents[1]
    project = root.parents[1]
    out = root / "runs" / f"Z16-PLAN-{run_id}"
    out.mkdir(exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    files = sorted(root.glob("communication_pruning/*.py")) + sorted(root.glob("tests/*.py"))
    files += [root / "README.md", project / "project/dsr/Z16-PLAN.md"]
    source_hashes = {str(p.relative_to(project)): sha(p) for p in files}
    with zipfile.ZipFile(root / "runs/Z15-EXT-002/source.zip") as prior:
        names = [n for n in prior.namelist() if n.endswith("Z15-requirements.txt")]
        if len(names) != 1:
            raise ValueError("pinned Z15 requirements not found")
        requirements = prior.read(names[0])
    (out / "requirements.txt").write_bytes(requirements)
    versions = {name: importlib.metadata.version(name) for name in (
        "numpy", "scipy", "autogen-agentchat", "autogen-core", "pydantic")}
    with zipfile.ZipFile(out / "source.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p, str(p.relative_to(project)))
        archive.writestr("requirements.txt", requirements)
    (out / "source-manifest.json").write_text(json.dumps(source_hashes, indent=2) + "\n")
    receipt = {"started_utc": started, "python": sys.version, "executable": sys.executable,
               "platform": platform.platform(), "pythonpath": os.environ.get("PYTHONPATH"),
               "versions": versions, "source_sha256": sha(out / "source.zip"),
               "plan_sha256": sha(project / "project/dsr/Z16-PLAN.md"),
               "model_calls": 0, "new_model_cost_usd": "0", "status": "started",
               "commands": []}
    try:
        # Preserve every decisive output, including a failing regression run.
        for name, args in (("tests", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
                           ("core-demo", ["-m", "communication_pruning"]),
                           ("data-demo", ["-m", "communication_pruning.demo"])):
            command = [sys.executable, *args]
            with (out / f"{name}.log").open("w") as log:
                result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            receipt["commands"].append({"command": command, "exit_code": result.returncode, "log": f"{name}.log"})
            if result.returncode:
                raise RuntimeError(f"{name} failed; retained log")
        sys.path.insert(0, str(root / "tests"))
        from test_pilot_schedule import fixture
        manifest, ids, _ = fixture()
        (out / "synthetic-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        q_file, f_file = out / "fake-q.json", out / "fake-fixed.json"
        q_file.write_text('{"synthetic": true, "role": "Q", "trained": false}\n')
        f_file.write_text('{"synthetic": true, "role": "F*", "trained": false}\n')
        bindings = {"q_policy": sha(q_file), "fixed_policy": sha(f_file),
                    "execution_contract": receipt["plan_sha256"]}
        (out / "expected-inputs.json").write_text(json.dumps({"bindings": bindings, "task_ids": ids}, indent=2) + "\n")
        plan = make_schedule(manifest, ids, bindings=bindings)
        save_schedule(out / "schedule.json", plan, manifest, expected_bindings=bindings, expected_task_ids=ids)
        saved = json.loads((out / "schedule.json").read_text())
        validate_schedule(saved, manifest, expected_bindings=bindings, expected_task_ids=ids)

        # Structural recount does not call make_schedule or validate_schedule.
        rows = saved["slots"]
        checks = []
        def check(label, value):
            checks.append({"check": label, "passed": bool(value)})
            if not value:
                raise AssertionError(label)
        try:
            check("720 unique slots", len(rows) == len({r["slot_id"] for r in rows}) == 720)
            check("external input hashes", saved["bindings"] == bindings and saved["manifest_sha256"] == digest({k: v for k, v in manifest.items() if k != "sha256"}))
            for repeat in range(1, 4):
                counts = Counter((r["task_id"], r["arm"]) for r in rows if r["repeat"] == repeat)
                check(f"repeat {repeat} covers all task arms once", counts == Counter({(t, a): 1 for t in ids for a in ("Q", "F*")}))
            for i in range(0, len(rows), 2):
                a, b = rows[i:i + 2]
                check(f"pair {i // 2 + 1}", all(a[k] == b[k] for k in ("task_id", "family_id", "pair", "repeat", "block"))
                      and {a["arm"], b["arm"]} == {"Q", "F*"} and (a["position"], b["position"]) == (1, 2))
            for block in range(1, 19):
                check(f"block {block} balance", Counter(r["arm"] for r in rows if r["block"] == block and r["position"] == 1) == Counter({"Q": 10, "F*": 10}))
            check("per-task freshness requested", all(r["fresh_context"] is True for r in rows))
            check("source unchanged", all(sha(project / p) == h for p, h in source_hashes.items()))
            with zipfile.ZipFile(out / "source.zip") as archive:
                check("source recoverable", archive.testzip() is None and all(sha256(archive.read(p)).hexdigest() == h for p, h in source_hashes.items()))
        finally:
            (out / "recount.json").write_text(json.dumps(checks, indent=2) + "\n")
        receipt.update(status="passed", recount_checks=len(checks), summary=saved["summary"])
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        receipt["evidence_sha256"] = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"output": str(out), "status": receipt["status"]}))


if __name__ == "__main__":
    main(sys.argv[1])
