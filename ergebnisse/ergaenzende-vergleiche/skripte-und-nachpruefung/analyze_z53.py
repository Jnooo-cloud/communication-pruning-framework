"""Secondary-panel analysis exactly as final_operator.analyze_saved_panel, on the Z53-collected rows.

Same frozen contract checks, same prebound seed, unchanged final_analysis.analyze_panel.
Rows must equal the zero-call handoff hash (handoff/<panel>-P7.json). Create-only outputs.
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from communication_pruning.openrouter import encoded, save_new  # noqa: E402
from study_preparation import final_preflight as gate  # noqa: E402
from study_preparation import z53_fast as z  # noqa: E402
from study_preparation.final_analysis import analyze_panel  # noqa: E402

ctx = z.Context(with_selectors=False)
binding = ctx.settings["analysis_binding"]
gate.evidence_file(binding)
z.need(ctx.candidate["source_files"].get(binding["path"]) == binding["sha256"], "analysis binding not frozen")
contract = gate.read_json(binding["path"])
z.need(contract["study_id"] == ctx.plan["study_id"] and contract["seed_base"] == ctx.plan["seed_base"]
       and contract["bootstrap_repetitions"] == 19999 and contract["secondary_costs"] == "descriptive_only",
       "analysis differs from frozen contract")
for panel in z.PANELS:
    raw = (HERE / "live/collected" / f"rows-{panel}.json").read_bytes()
    rows = json.loads(raw)
    z.need(z.sha256(encoded(rows)).hexdigest() == z.load(HERE / "live/handoff" / f"{panel}-P7.json")["rows_sha256"],
           f"{panel} rows differ from handoff")
    result = analyze_panel(ctx.plan, panel, rows, bootstrap_seed=contract["primary_bootstrap_seed"])
    out = HERE / f"ANALYSIS-{panel}.json"
    if not out.exists():
        save_new(out, encoded({"analysis_binding_sha256": binding["sha256"], "rows_sha256":
                               z.sha256(encoded(rows)).hexdigest(), "report": result}))
    print(panel, "n", result["n"], "ok")
