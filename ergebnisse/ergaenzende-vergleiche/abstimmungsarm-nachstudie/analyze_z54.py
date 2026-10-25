"""R-panel re-analysis with the new S-k rows (D-081), exactly as analyze_z53.py for panel R.

Same frozen contract checks, same prebound seed, unchanged final_analysis.analyze_panel.
Input: <folder>/collected/rows-R-SK.json (run_z54.py collect). Output (create-only):
ANALYSIS-R-SK.json and CONTROL-R-SK.json (old vs new: changed endpoints, control endpoints identical).
ANALYSIS-R.json of Z53 is only read.

usage: analyze_z54.py [--folder DIR] [--out DIR]
"""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from communication_pruning.openrouter import encoded, save_new  # noqa: E402
from study_preparation import final_preflight as gate  # noqa: E402
from study_preparation import z53_fast as z  # noqa: E402
from study_preparation.final_analysis import analyze_panel  # noqa: E402

OLD = HERE.parents[0] / "Z53-SCHNELLFORTSETZUNG-001/ANALYSIS-R.json"
AFFECTED = ("R02", "R07")
CONTROL = ("R01", "R03", "R04", "R05", "R06", "R08", "R09")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default=str(HERE / "live"))
    parser.add_argument("--out", default=str(HERE))
    args = parser.parse_args()
    ctx = z.Context(with_selectors=False)
    binding = ctx.settings["analysis_binding"]
    gate.evidence_file(binding)
    z.need(ctx.candidate["source_files"].get(binding["path"]) == binding["sha256"], "analysis binding not frozen")
    contract = gate.read_json(binding["path"])
    z.need(contract["study_id"] == ctx.plan["study_id"] and contract["seed_base"] == ctx.plan["seed_base"]
           and contract["bootstrap_repetitions"] == 19999 and contract["secondary_costs"] == "descriptive_only",
           "analysis differs from frozen contract")
    raw = (Path(args.folder) / "collected/rows-R-SK.json").read_bytes()
    rows = json.loads(raw)
    report = analyze_panel(ctx.plan, "R", rows, bootstrap_seed=contract["primary_bootstrap_seed"])
    old_file = json.loads(OLD.read_bytes())
    z.need(old_file["analysis_binding_sha256"] == binding["sha256"], "old analysis used another binding")
    old = old_file["report"]
    # control: everything except S-k and the S-k endpoints must be identical
    findings = []
    for metric in ("em", "f1"):
        for e in CONTROL:
            if report["secondary_quality"][metric][e] != old["secondary_quality"][metric][e]:
                findings.append(f"secondary_quality.{metric}.{e}")
    for e in CONTROL:
        if report["descriptive_costs"]["endpoints"][e] != old["descriptive_costs"]["endpoints"][e]:
            findings.append(f"descriptive_costs.endpoints.{e}")
    for arm in old["estimates"]:
        if arm != "S-k" and report["estimates"][arm] != old["estimates"][arm]:
            findings.append(f"estimates.{arm}")
        if arm != "S-k" and report["descriptive_costs"]["arms"][arm] != old["descriptive_costs"]["arms"][arm]:
            findings.append(f"descriptive_costs.arms.{arm}")
    for key in ("n", "panel", "plan_hash", "schema", "unit", "mode", "method_status"):
        if report[key] != old[key]:
            findings.append(key)
    control = {
        "control_identical": not findings, "findings": findings,
        "old_analysis_sha256": z.file_sha(OLD), "new_rows_sha256": z.sha256(raw).hexdigest(),
        "S-k": {"old": old["estimates"]["S-k"], "new": report["estimates"]["S-k"],
                "old_cost_arm": old["descriptive_costs"]["arms"]["S-k"],
                "new_cost_arm": report["descriptive_costs"]["arms"]["S-k"]},
        "S": report["estimates"]["S"],
        "affected": {e: {"em": {"old": old["secondary_quality"]["em"][e], "new": report["secondary_quality"]["em"][e]},
                         "f1": {"old": old["secondary_quality"]["f1"][e], "new": report["secondary_quality"]["f1"][e]},
                         "cost": {"old": old["descriptive_costs"]["endpoints"][e],
                                  "new": report["descriptive_costs"]["endpoints"][e]}}
                     for e in AFFECTED},
    }
    out = Path(args.out).resolve()
    for old_tree in (HERE.parents[0] / "Z52-NEBENPANEL-ANSCHLUSS-001", HERE.parents[0] / "Z53-SCHNELLFORTSETZUNG-001"):
        z.need(out != old_tree.resolve() and old_tree.resolve() not in out.parents, "output inside old run tree")
    save_new(out / "ANALYSIS-R-SK.json", encoded({"analysis_binding_sha256": binding["sha256"],
                                                  "rows_sha256": z.sha256(raw).hexdigest(), "report": report}))
    save_new(out / "CONTROL-R-SK.json", encoded(control))
    print(json.dumps({"n": report["n"], "control_identical": not findings, "findings": findings,
                      "S-k_new": report["estimates"]["S-k"]}, indent=1))


if __name__ == "__main__":
    main()
