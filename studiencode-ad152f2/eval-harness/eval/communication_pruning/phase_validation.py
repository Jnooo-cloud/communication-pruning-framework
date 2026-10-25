"""Source-bound Z17 regression and real metadata allocation, no content loading."""

from datetime import datetime, timezone
from hashlib import sha256
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from .data import canonical, read_manifest, save_manifest
from .phase_allocation import allocate, repeat_subset, validate_allocation
from .pilot_schedule import make_schedule, save_schedule


SOURCE_SHA = "e18f0882f0ca0d935dd1d5aae1f870f17370cb05c04c4e07d8ccef73ae9e4a89"


def sha(path):
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main(run_id, cycle="Z17"):
    if cycle not in ("Z17", "Z18"):
        raise ValueError("unknown preplanned allocation cycle")
    quota_mode = "closest" if cycle == "Z18" else "exact"
    if not re.fullmatch(r"[0-9]{3}", run_id):
        raise ValueError("three-digit unused run ID required")
    root = Path(__file__).resolve().parents[1]
    project = root.parents[1]
    out = root / "runs" / f"{cycle}-SPLIT-{run_id}"
    out.mkdir(exist_ok=False)
    source_path = root / "runs/Z07-PREPARE/manifest.json"
    register_path = project / "project/DATENEXPOSITIONSREGISTER.md"
    plan_path = project / f"project/dsr/{cycle}-PLAN.md"
    sources = sorted(root.glob("communication_pruning/*.py")) + sorted(root.glob("tests/*.py"))
    sources += [root / "README.md", plan_path, register_path]
    hashes = {str(p.relative_to(project)): sha(p) for p in sources}
    requirements = root / "runs/Z16-PLAN-001/requirements.txt"
    with zipfile.ZipFile(out / "source.zip", "x", zipfile.ZIP_DEFLATED) as z:
        for p in sources:
            z.write(p, str(p.relative_to(project)))
        z.write(requirements, "requirements.txt")
    (out / "source-manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    receipt = {"started_utc": datetime.now(timezone.utc).isoformat(), "status": "started",
               "python": sys.version, "executable": sys.executable,
               "pythonpath": os.environ.get("PYTHONPATH"),
               "versions": {p: importlib.metadata.version(p) for p in ("numpy", "scipy", "autogen-agentchat", "autogen-core")},
               "source_sha256": sha(out / "source.zip"), "plan_sha256": sha(plan_path),
               "exposure_register_sha256": sha(register_path), "commands": [],
               "mode": "metadata_only", "model_calls": 0, "new_model_cost_usd": "0"}
    try:
        for name, args in (("tests", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
                           ("core-demo", ["-m", "communication_pruning"]),
                           ("data-demo", ["-m", "communication_pruning.demo"])):
            command = [sys.executable, *args]
            with (out / f"{name}.log").open("w") as log:
                result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            receipt["commands"].append({"command": command, "exit_code": result.returncode})
            if result.returncode:
                raise RuntimeError(f"{name} failed; log retained")
        if sha(source_path) != SOURCE_SHA:
            raise ValueError("old metadata file differs from prebound Z07 identity")
        source = read_manifest(source_path)
        # Preserve the actual metadata input; raw datasets are hashed as bytes only.
        (out / "source-metadata.json").write_bytes(source_path.read_bytes())
        (out / "exposure-register.md").write_bytes(register_path.read_bytes())
        exposed = sorted(set(re.findall(r"`([234]hop\d*__[\d_]+)`", register_path.read_text())))
        if len(exposed) != 17:
            raise ValueError("exposure register changed from prebound count; review required")
        vendor = project / "archive/neustart-2026-08-30/legacy-artifact/eval-harness/data/vendor/musique-v1.0/data"
        raw_hashes = {split: sha(vendor / f"musique_ans_v1.0_{split}.jsonl") for split in source["source_hashes"]}
        if raw_hashes != source["source_hashes"]:
            raise ValueError("raw dataset bytes changed")
        receipt["inputs"] = {"metadata_file_sha256": SOURCE_SHA, "raw_binary_sha256": raw_hashes,
                             "exposed_ids": exposed, "rows": len(source["entries"])}
        (out / "inputs.json").write_text(json.dumps(receipt["inputs"], indent=2) + "\n")
        # Pin inputs on disk before selecting anything; failures keep these bytes.
        allocation = allocate(source, exposed_ids=exposed, quota_mode=quota_mode)
        (out / "allocation.json").write_bytes(canonical(allocation) + b"\n")
        save_manifest(out / "manifest.json", allocation["manifest"])
        summary = validate_allocation(allocation, source, exposed_ids=exposed, quota_mode=quota_mode)
        repeat = repeat_subset(allocation)
        (out / "spatial-repeat.json").write_text(json.dumps(repeat, indent=2) + "\n")
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        entries = {e["task_id"]: e for e in allocation["manifest"]["entries"]}
        with (out / "selected-tasks.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["phase", "task_id", "family_id", "hop", "second_spatial_repeat"])
            for phase, ids in sorted(allocation["panels"].items()):
                for t in ids:
                    writer.writerow([phase, t, entries[t]["family_id"], entries[t]["hop"], t in repeat["task_ids"]])
        for name in ("fake-q.json", "fake-fixed.json"):
            (out / name).write_bytes((root / "runs/Z16-PLAN-001" / name).read_bytes())
        bindings = {"q_policy": sha(out / "fake-q.json"), "fixed_policy": sha(out / "fake-fixed.json"),
                    "execution_contract": receipt["plan_sha256"]}
        pilot_ids = allocation["panels"]["pilot"]
        preview = make_schedule(allocation["manifest"], pilot_ids, bindings=bindings)
        save_schedule(out / "pilot-preview-NOT-FROZEN.json", preview, allocation["manifest"],
                      expected_bindings=bindings, expected_task_ids=pilot_ids)
        if any(sha(project / p) != h for p, h in hashes.items()):
            raise ValueError("source changed during validation")
        receipt.update(status="passed", solver=allocation["solver"], summary=summary,
                       allocation_content_sha256=allocation["sha256"],
                       manifest_content_sha256=allocation["manifest"]["sha256"],
                       repetition_count=repeat["n"], pilot_preview_runs=len(preview["slots"]))
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        receipt["evidence_sha256"] = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"output": str(out), "status": receipt["status"]}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Z17")
