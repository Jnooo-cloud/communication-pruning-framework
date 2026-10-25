"""Create-only Z19 plan/budget validation. No benchmark contents or model calls."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from .contracts import AdapterError, Response, Usage
from .data import read_manifest
from .openrouter import validate_endpoint
from .phase_budget import PhaseBudget, BudgetStop
from .spatial_plan import make_plan, save_plan


def sha(path): return sha256(path.read_bytes()).hexdigest()


def main(run_id):
    if not re.fullmatch(r"[0-9]{3}", run_id): raise ValueError("unused three-digit ID required")
    root = Path(__file__).resolve().parents[1]; project = root.parents[1]
    out = root / "runs" / f"Z19-PREPARE-{run_id}"
    out.mkdir(exist_ok=False)
    files = sorted(root.glob("communication_pruning/*.py")) + sorted(root.glob("tests/*.py"))
    files += [root / "README.md", project / "project/dsr/Z19-PLAN.md", project / "project/dsr/Z18-DATENBINDUNG.json"]
    hashes = {str(p.relative_to(project)): sha(p) for p in files}
    with zipfile.ZipFile(out / "source.zip", "x", zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p, str(p.relative_to(project)))
        z.write(root / "runs/Z16-PLAN-001/requirements.txt", "requirements.txt")
    (out / "source-manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    receipt = {"started_utc": datetime.now(timezone.utc).isoformat(), "status": "started",
               "python": sys.version, "executable": sys.executable, "pythonpath": os.environ.get("PYTHONPATH"),
               "versions": {p: importlib.metadata.version(p) for p in ("numpy", "scipy", "autogen-agentchat", "autogen-core")},
               "source_sha256": sha(out / "source.zip"), "commands": [], "real_model_calls": 0, "new_model_cost_usd": "0"}
    try:
        for name, args in (("tests", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
                           ("core-demo", ["-m", "communication_pruning"]), ("data-demo", ["-m", "communication_pruning.demo"])):
            command = [sys.executable, *args]
            with (out / f"{name}.log").open("w") as log:
                r = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            receipt["commands"].append({"command": command, "exit_code": r.returncode})
            if r.returncode: raise RuntimeError(f"{name} failed; retained")
        binding = json.loads((project / "project/dsr/Z18-DATENBINDUNG.json").read_text())
        for obj in list(binding["files"].values()) + [binding["verification"]]:
            if sha(project / obj["path"]) != obj["sha256"]: raise ValueError("Z18 file changed")
        if sha(project / "project/DATENEXPOSITIONSREGISTER.md") != binding["exposure_register_sha256"]:
            raise ValueError("exposure register changed")
        m = read_manifest(project / binding["files"]["manifest.json"]["path"])
        allocation = json.loads((project / binding["files"]["allocation.json"]["path"]).read_text())
        repeats = json.loads((project / binding["files"]["spatial-repeat.json"]["path"]).read_text())
        bindings = {"allocation": binding["files"]["allocation.json"]["sha256"],
                    "repetition": binding["files"]["spatial-repeat.json"]["sha256"], "source": receipt["source_sha256"]}
        plan = make_plan(m, allocation["panels"]["spatial"], repeats["task_ids"], bindings=bindings)
        save_plan(out / "spatial-plan.json", plan, m, allocation["panels"]["spatial"], repeats["task_ids"], bindings=bindings)
        for name in ("z19-endpoints.json", "z19-endpoints-retrieval.json"):
            (out / name).write_bytes((project / ".firecrawl" / name).read_bytes())
        endpoint = validate_endpoint((out / "z19-endpoints.json").read_bytes())
        price_in, price_out = Decimal(endpoint["pricing"]["prompt"]), Decimal(endpoint["pricing"]["completion"])
        catalog_max = endpoint["context_length"] * price_in + endpoint["max_completion_tokens"] * price_out
        budget = {"proposed_phase_cap_usd": "36.12", "authorized": False, "call_reservation_usd": "0.14",
                  "catalog_limit_cost_usd": str(catalog_max), "reserve_covers_catalog": catalog_max <= Decimal("0.14"),
                  "expected_calls_without_retry": 30100, "scenarios_are_unmeasured_assumptions": True,
                  "scenarios": [{"input_per_call": i, "output_per_call": o, "total_usd": str(30100 * (i * price_in + o * price_out))}
                                for i, o in ((2000, 300), (4000, 600), (8000, 1000))]}
        (out / "budget-proposal.json").write_text(json.dumps(budget, indent=2) + "\n")
        cases = {}
        for case in ("normal", "cap", "unknown", "failed_known", "open", "over"):
            ledger = PhaseBudget(out / f"budget-{case}.jsonl", cap=Decimal("0.28"), reserve=Decimal("0.14"),
                                 max_calls=10, binding=plan["sha256"], allow_synthetic=True)
            reached = []
            def operation(value):
                reached.append(value)
                if value == "failed": raise AdapterError("synthetic failure", Usage(cost_usd=Decimal("0.02"), cost_source="synthetic"))
                return Response("synthetic", Usage() if value is None else Usage(cost_usd=Decimal(value), cost_source="synthetic"))
            try:
                if case == "open": ledger.start("open-a")
                else:
                    values = {"normal": ["0", "0.01", "0.14"], "cap": ["0.14", "0.14", "0"],
                              "unknown": ["0.01", None], "failed_known": ["failed"], "over": ["0.30"]}[case]
                    for i, value in enumerate(values): ledger.run(f"{case}-{i}", lambda value=value: operation(value))
            except BudgetStop:
                pass
            cases[case] = {"snapshot": ledger.snapshot(), "reached_operations": reached}
        expected_known = {"normal": "0.15", "cap": "0.28", "unknown": "0.01", "failed_known": "0.02", "open": "0", "over": "0.30"}
        for case, value in expected_known.items():
            if Decimal(cases[case]["snapshot"]["known_cost_usd"]) != Decimal(value): raise AssertionError(case)
        if len(cases["cap"]["reached_operations"]) != 2: raise AssertionError("cap leaked call")
        (out / "budget-cases.json").write_text(json.dumps(cases, indent=2) + "\n")
        if any(sha(project / p) != h for p, h in hashes.items()): raise ValueError("source changed")
        receipt.update(status="passed", summary=plan["summary"], folds=[len(f) for f in plan["folds"]],
                       learning_curve_sizes=[p["n"] for p in plan["learning_curves"]],
                       budget_proposal=budget, synthetic_budget_operations=sum(len(c["reached_operations"]) for c in cases.values()))
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__, error=str(error)); raise
    finally:
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        receipt["evidence_sha256"] = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"output": str(out), "status": receipt["status"]}))


if __name__ == "__main__": main(sys.argv[1])
