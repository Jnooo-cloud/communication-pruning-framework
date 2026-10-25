"""Retained Z20 integrated test: fake data and fake transport only."""
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from .openrouter import encoded, save_new
from .study import FileGuard, file_hash, run_spatial
from .study_release import candidate


def main(run_id):
    if not run_id.isdigit() or len(run_id) != 3:
        raise ValueError("three-digit create-only run ID required")
    artifact = Path(__file__).resolve().parents[1]
    root = artifact.parents[1]
    out = artifact / "runs" / f"Z20-INTEGRATION-{run_id}"
    out.mkdir(exist_ok=False)
    paths = sorted([*artifact.glob("communication_pruning/*.py"), *artifact.glob("tests/*.py"),
                    artifact / "README.md", root / "project/dsr/Z20-PLAN.md",
                    root / "project/dsr/Z18-DATENBINDUNG.json"])
    hashes = {str(p.relative_to(root)): file_hash(p) for p in paths}
    with zipfile.ZipFile(out / "source.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, str(path.relative_to(root)))
        with zipfile.ZipFile(artifact / "runs/Z19-PREPARE-001/source.zip") as previous:
            archive.writestr("requirements.txt", previous.read("requirements.txt"))
    save_new(out / "source-manifest.json", encoded(hashes))
    receipt = {"status": "started", "started_utc": datetime.now(timezone.utc).isoformat(),
               "source_sha256": file_hash(out / "source.zip"), "python": sys.version,
               "executable": sys.executable, "pythonpath": os.environ.get("PYTHONPATH"),
               "versions": {p: importlib.metadata.version(p) for p in ("numpy", "scipy", "autogen-agentchat", "autogen-core")},
               "commands": [], "real_model_calls": 0, "new_model_cost_usd": "0"}
    try:
        for name, command in [("tests", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
                              ("core-demo", ["-m", "communication_pruning"]),
                              ("data-demo", ["-m", "communication_pruning.demo"])]:
            with (out / f"{name}.log").open("xb") as log:
                proc = subprocess.run([sys.executable, *command], cwd=artifact, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            receipt["commands"].append({"command": command, "exit_code": proc.returncode})
            if proc.returncode:
                raise RuntimeError(f"{name} failed")
        sys.path.insert(0, str(artifact / "tests"))
        from study_fixture import FakeTransport, fixture
        inputs = fixture(out / "fake-inputs")
        source_guard = FileGuard({root / p: h for p, h in hashes.items()})
        input_guard = inputs["guard"]
        def guard():
            source_guard()
            input_guard()
        inputs["guard"] = guard
        transport = FakeTransport()
        print("Full synthetic schedule started", flush=True)
        full = run_spatial(**inputs, folder=out / "full", control=out / "full-control", transport=transport, synthetic=True)
        receipt["full"] = full
        receipt["synthetic_transport_calls"] = transport.calls
        if full["completed_slots"] != 4900 or transport.calls != 30100:
            raise AssertionError("full schedule incomplete")
        del transport
        print("Full synthetic schedule complete; retaining failure cases", flush=True)
        faults = {}
        for mode in ("length", "unknown", "duplicate", "transport", "http", "interrupt", "over"):
            client = FakeTransport(fail_at=2, mode=mode)
            try:
                run_spatial(**inputs, folder=out / f"fault-{mode}", control=out / f"control-{mode}",
                            transport=client, synthetic=True, slot_limit=14)
            except BaseException as error:
                faults[mode] = {"error_type": type(error).__name__, "synthetic_transport_calls": client.calls,
                               "report_sha256": file_hash(out / f"fault-{mode}/report.json")}
            else:
                raise AssertionError("fault did not stop")
        receipt["faults"] = faults
        prepared = candidate(root, out / "source.zip", out / "source-manifest.json")
        save_new(out / "prepared-live-candidate.json", encoded(prepared))
        source_guard()
        receipt["status"] = "passed"
    except BaseException as error:
        receipt.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        # Bind every retained provider, journal and failure artifact, not just summaries.
        evidence = {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}
        save_new(out / "evidence-manifest.json", encoded(evidence))
        receipt["evidence_manifest_sha256"] = file_hash(out / "evidence-manifest.json")
        save_new(out / "receipt.json", encoded(receipt))
        print(json.dumps({"output": str(out), "status": receipt["status"]}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
