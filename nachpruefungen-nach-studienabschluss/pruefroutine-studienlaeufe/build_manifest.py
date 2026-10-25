#!/usr/bin/env python3
"""Z56 V2a: data manifest of the run logs behind the thesis evaluation (read only).

Derivation (from the evaluation code, not guessed):
  P  rows = final P state analysed by Z51-RETRY-EINZELERSATZ-001/operator/resume_main.py
       (kernel.collect_panel -> analyze_panel), STATE.json bound by the final hold 009040-<sha>.
       Each row carries the provenance key of the segment that produced it; the chain of
       ORIGINALS.json files links FINAL-STUDY-001 -> Z51-FORTSETZUNG -> Z51-RATENLIMIT ->
       Z51-EINZELERSATZ -> Z51-F-EINZELERSATZ -> Z51-RETRY-EINZELERSATZ.
  R  rows = Z54-SK-KORREKTUR-001/live/collected/rows-R-SK.json (ANALYSIS-R-SK.json); its non-S-k
       rows equal Z53 rows-R.json = Z52 inspect state (R 0..2182) + Z53 blocks (R 2183..2951)
       (run_z53.py collect); S-k rows come from Z54 blocks.
  T, F rows = Z53 rows-T.json / rows-F.json (ANALYSIS-T/F.json, run_z53.py collect).
  A row is produced by result.json of its slot (final_execution._row / z53_fast); the slot log
  is the journal.jsonl (MAS arms) or direct-*.json (S, S-k) next to the matching result.json.
Writes only into this v2 folder.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
EVAL = HERE.parents[2]
OUTDIR = Path(os.environ.get("Z56_V2_DIR", str(HERE)))   # scratch only for the pre-run test
RUNS = EVAL / "runs"
sys.path.insert(0, str(EVAL))
from communication_pruning.configurations import bank, dense  # noqa: E402
from study_preparation import final_execution as nx  # noqa: E402  (only for the cross-check of _configuration)

FILES = {}          # relpath (to runs/) -> [sha256, bytes]
CHECKS = []


def rel(path):
    return str(Path(path).resolve().relative_to(RUNS.resolve()))


def sha(path):
    path = Path(path)
    key = rel(path)
    if key not in FILES:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        FILES[key] = [digest, path.stat().st_size]
    return FILES[key][0]


def load(path):
    sha(path)
    return json.loads(Path(path).read_bytes())


def check(name, ok, detail=None):
    CHECKS.append({"check": name, "passed": bool(ok), "detail": detail})
    if not ok:
        print("CHECK FAILED", name, detail, file=sys.stderr)


# ------------------------------------------------------------------ analysis inputs
P_STATE = RUNS / "Z51-RETRY-EINZELERSATZ-001/operation/isolated-backup-D074/8fa92e0363674966964a48fc89d9abc1/STATE.json"
P_HOLD = RUNS / "Z51-RETRY-EINZELERSATZ-001/operation/remote-holds/009040-960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6.json"
P_STATUS = RUNS / "Z51-RETRY-EINZELERSATZ-001/operation/starter/STATUS.json"
P_ANALYSIS = RUNS / "Z51-RETRY-EINZELERSATZ-001/operation/P-ANALYSIS.json"
Z53 = RUNS / "Z53-SCHNELLFORTSETZUNG-001"
Z54 = RUNS / "Z54-SK-KORREKTUR-001"
Z52 = RUNS / "Z52-NEBENPANEL-ANSCHLUSS-001"
PLAN = RUNS / "Z50-NACHARBEIT-001/coordination/final-candidate-001/PLAN.json"
CAND_P = RUNS / "Z51-HAUPTSTUDIE-001/activation/CANDIDATE-AUTHORIZED.json"
CAND_RTF = Z52 / "recovery-R00038/activation/CANDIDATE.json"

plan = load(PLAN)
check("plan_file_sha", sha(PLAN) == "42a55ddd7dc71738d39fbdb546b0bb60ca19a0d6485f47688de32c893f47f61f", sha(PLAN))
cand_p, cand_rtf = load(CAND_P), load(CAND_RTF)
check("candidates_fixed_C01_rounds1", cand_p["fixed_config_id"] == cand_rtf["fixed_config_id"] == "C01"
      and cand_p["fixed_rounds"] == cand_rtf["fixed_rounds"] == 1,
      [cand_p["fixed_config_id"], cand_rtf["fixed_config_id"], cand_p["fixed_rounds"], cand_rtf["fixed_rounds"]])
check("candidate_rtf_sha_as_bound_in_z53_fast", sha(CAND_RTF) == "135d2a58d7faefde6c7b382e9a23ba5d917a3b1722e1daa7fc7766a6d1cb6a37", sha(CAND_RTF))
PLAN_HASH = plan["plan_hash"]
PLAN_BLOCKS = {b["block_id"]: b for panel in ("P", "R", "T", "F") for b in plan["panels"][panel]}

hold = load(P_HOLD)
status = load(P_STATUS)
check("P_state_file_sha_equals_final_hold", sha(P_STATE) == hold["state_sha256"]
      == "960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6", sha(P_STATE))
check("P_analysis_sha_equals_status", sha(P_ANALYSIS) == status["analysis"]["sha256"], sha(P_ANALYSIS))
p_state = json.loads(P_STATE.read_bytes())
check("P_state_complete_9040", p_state["complete"] and p_state["completed_blocks"] == 9040
      and p_state["plan_hash"] == PLAN_HASH and len(p_state["rows"]) == 18080)

rows_r_old = load(Z53 / "live/collected/rows-R.json")
rows_r = load(Z54 / "live/collected/rows-R-SK.json")
rows_t = load(Z53 / "live/collected/rows-T.json")
rows_f = load(Z53 / "live/collected/rows-F.json")
for name, path, rows_path in (("R", Z54 / "ANALYSIS-R-SK.json", Z54 / "live/collected/rows-R-SK.json"),
                              ("R_old", Z53 / "ANALYSIS-R.json", Z53 / "live/collected/rows-R.json"),
                              ("T", Z53 / "ANALYSIS-T.json", Z53 / "live/collected/rows-T.json"),
                              ("F", Z53 / "ANALYSIS-F.json", Z53 / "live/collected/rows-F.json")):
    check(f"{name}_analysis_rows_binding", load(path)["rows_sha256"] == sha(rows_path), sha(rows_path))
key = lambda r: (r["draw_index"], r["arm"])  # noqa: E731
old_non_sk = {key(r): r for r in rows_r_old if r["arm"] != "S-k"}
new_non_sk = {key(r): r for r in rows_r if r["arm"] != "S-k"}
check("R_non_Sk_rows_identical_in_Z53_and_Z54", old_non_sk == new_non_sk, len(new_non_sk))
z52_inspect = Z52 / ("recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/"
                     "rate-stop-R01589/r2183-overlimit/activation/INSPECT-011223-RESULT-001.json")
prior = load(Z53 / "live/PRIOR-BINDING.json")
check("Z53_prior_binding_hash", prior["inspect_sha256"] == sha(z52_inspect) and prior["r_done"] == 2183)
prior_rows = json.loads(z52_inspect.read_bytes())["state"]["rows"]
check("Z52_inspect_rows_equal_rows_R_0_2182",
      {key(r): r for r in prior_rows} == {key(r): r for r in rows_r_old if r["draw_index"] < 2183}, len(prior_rows))

# ------------------------------------------------------------------ expected configuration (own mapping)
CONFIGS = {c.config_id: c for c in bank()}
MAS = {"Q", "F", "D", "Z", "Q-ST", "Q-TF", "Qc", "Qf", "Fc", "Ff"}
DIRECT = {"S", "S-k"}


def expected(arm, block, selection, cand):
    if arm in ("Q", "Qc", "Qf", "Q-ST", "Q-TF"):
        config = CONFIGS[selection["spatial_q"]]
    elif arm in ("F", "Fc", "Ff"):
        config = CONFIGS[cand["fixed_config_id"]]
    elif arm == "D":
        config = dense()
    elif arm == "Z":
        config = CONFIGS[block["z_configuration"]]
    else:
        raise ValueError(arm)
    rounds = selection["temporal_qst"] if arm == "Q-ST" else cand["fixed_rounds"] if arm == "Q-TF" else 2
    failed = next(r for r in block["fault_permutation"] if r in config.roles) if arm in ("Qf", "Ff") else None
    return config, rounds, failed


# ------------------------------------------------------------------ locate slots
P_SEG = {("recovery_provenance", "original_checkpoint"): RUNS / "FINAL-STUDY-001/live",
         ("recovery_provenance", "resumed_segment"): RUNS / "Z51-FORTSETZUNG-001/live",
         "rate_resume_provenance": RUNS / "Z51-RATENLIMIT-001/live",
         "lost_resume_provenance": RUNS / "Z51-EINZELERSATZ-001/live",
         "f_resume_provenance": RUNS / "Z51-F-EINZELERSATZ-001/live",
         "retry_lost_resume_provenance": RUNS / "Z51-RETRY-EINZELERSATZ-001/live"}
P_ALL = list(dict.fromkeys(P_SEG.values()))
# Z52 production chain (direct live roots, in execution order) and carried copies
Z52_CHAIN = ["live", "recovery-R00038/live", "recovery-R00038/continuation-R00087/live",
             "recovery-R00038/continuation-R00087/recovery-R00125/live",
             "recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/live",
             "recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/live",
             "recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/rate-stop-R01589/live",
             "recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/rate-stop-R01589/r2183-overlimit/live"]
Z52_COPIES = ["recovery-R00038/live/original", "recovery-R00038/continuation-R00087/live/original",
              "recovery-R00038/continuation-R00087/recovery-R00125/live/retained",
              "recovery-R00038/continuation-R00087/recovery-R00125/live/retained/original",
              "recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/live/retained",
              "recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/live/retained/retained",
              "recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/live/retained/retained/original"]


def core_equal(row, result):
    """result.json equals the analysed row up to provenance keys added later by resume chains."""
    extra = set(row) - set(result)
    return all(row.get(k) == v for k, v in result.items()) and all(k.endswith("provenance") for k in extra)


z52_index = defaultdict(list)   # (draw, arm) -> [(order, is_copy, slotdir, result)]
for order, root in enumerate(Z52_CHAIN + Z52_COPIES):
    base = Z52 / root / "blocks"
    if not base.is_dir():
        check(f"z52_root_exists:{root}", False)
        continue
    for block_dir in sorted(base.iterdir()):
        if not block_dir.is_dir():
            continue
        for arm_dir in sorted(block_dir.iterdir()):
            result_path = arm_dir / "result.json"
            if arm_dir.is_dir() and result_path.is_file():
                result = load(result_path)   # every indexed result.json is hashed (read)
                if result.get("panel") == "R" and result.get("run_id", "").startswith(PLAN_HASH[:16] + ":"):
                    z52_index[(result["draw_index"], result["arm"])].append(
                        (order, order >= len(Z52_CHAIN), arm_dir, result))

runs, problems = [], []


def slot_files(slot_dir, arm):
    names = (["journal.jsonl", "result.json", "terminal-failure.json", "terminal-overlimit.json"] if arm in MAS
             else ["direct-started.json", "direct-1.json", "direct-2.json", "direct-3.json", "direct-4.json",
                   "direct-5.json", "direct-complete.json", "result.json"])
    found = [slot_dir / n for n in names if (slot_dir / n).is_file()]
    other = sorted(p.name for p in slot_dir.iterdir() if p.is_file() and p.name not in names)
    return found, other


def register(panel, row, slot_dir, source, cand, duplicates=()):
    arm = row["arm"]
    block_dir = slot_dir.parent
    block = PLAN_BLOCKS[row["block_id"]]
    entry = {"panel": panel, "arm": arm, "draw_index": row["draw_index"], "block_id": row["block_id"],
             "slot_id": row["slot_id"], "run_id": row["run_id"], "source": source,
             "slot_dir": rel(slot_dir), "kind": "mas" if arm in MAS else "direct",
             "row": {k: row.get(k) for k in ("status", "call_count", "configuration", "rounds", "failed_role",
                                              "failure_reason")}}
    expected_run_id = PLAN_HASH[:16] + ":" + block["slots"][[s["arm"] for s in block["slots"]].index(arm)]["slot_id"]
    if row["run_id"] != expected_run_id:
        problems.append({"slot": row["slot_id"], "problem": "run_id differs from plan"})
    started = load(block_dir / "started.json")
    if started.get("block") != block or started.get("plan_hash") != PLAN_HASH:
        problems.append({"slot": row["slot_id"], "problem": "started.json block differs from plan"})
    files, other = slot_files(slot_dir, arm)
    for f in files:
        sha(f)
    entry["files"] = [rel(f) for f in files]
    if other:
        entry["other_files_not_read"] = other
    if arm in MAS:
        selection = load(block_dir / "selection.json")
        spatial = load(block_dir / "spatial-measurement.json")
        if spatial.get("choice") != selection["spatial_q"]:
            problems.append({"slot": row["slot_id"], "problem": "spatial measurement choice differs"})
        if panel == "T":
            temporal = load(block_dir / "temporal-measurement.json")
            if temporal.get("choice") != selection["temporal_qst"]:
                problems.append({"slot": row["slot_id"], "problem": "temporal measurement choice differs"})
        config, rounds, failed = expected(arm, block, selection, cand)
        nconfig, nrounds, nfailed = nx._configuration(cand, block, arm, selection)
        if (config, rounds, failed) != (nconfig, nrounds, nfailed):
            problems.append({"slot": row["slot_id"], "problem": "own expectation differs from final_execution._configuration"})
        if (row["configuration"], row["rounds"], row["failed_role"]) != (config.config_id, rounds, failed):
            problems.append({"slot": row["slot_id"], "problem": "analysed row binding differs from expectation"})
        entry["expected"] = {"config_id": config.config_id, "roles": list(config.roles),
                             "edges": [list(e) for e in config.edges], "rounds": rounds, "failed_role": failed,
                             "selection": selection, "selection_file": rel(block_dir / "selection.json")}
        entry["journal"] = rel(slot_dir / "journal.jsonl")
        entry["terminal_failure_file"] = next((rel(f) for f in files if f.name.startswith("terminal-")), None)
        if not (slot_dir / "journal.jsonl").is_file():
            problems.append({"slot": row["slot_id"], "problem": "journal missing"})
    if duplicates:
        entry["duplicates"] = duplicates
    runs.append(entry)


# P
for row in p_state["rows"]:
    pkey = next(k for k in row if k.endswith("provenance") and k != "provenance")
    seg = P_SEG[(pkey, row[pkey]["origin"])] if pkey == "recovery_provenance" else P_SEG[pkey]
    slot = seg / "blocks" / f"{row['draw_index']:06d}" / row["arm"]
    source = rel(seg)
    if not ((slot / "result.json").is_file() and core_equal(row, json.loads((slot / "result.json").read_bytes()))):
        alternatives = [s / "blocks" / f"{row['draw_index']:06d}" / row["arm"] for s in P_ALL]
        alternatives = [a for a in alternatives if (a / "result.json").is_file()
                        and core_equal(row, json.loads((a / "result.json").read_bytes()))]
        problems.append({"slot": row["slot_id"], "problem": "row not found in provenance segment",
                         "alternatives": [rel(a) for a in alternatives]})
        if not alternatives:
            continue
        slot, source = alternatives[0], rel(alternatives[0].parents[2])
    sha(slot / "result.json")
    register("P", row, slot, source, cand_p)

# R, T, F
for panel, rows in (("R", rows_r), ("T", rows_t), ("F", rows_f)):
    for row in rows:
        i, arm = row["draw_index"], row["arm"]
        if panel == "R" and arm == "S-k":
            slot = Z54 / "live/blocks" / f"R-{i:05d}" / "S-k"
            result = load(slot / "result.json")
            if result != row:
                problems.append({"slot": row["slot_id"], "problem": "Z54 S-k result differs from analysed row"})
            register(panel, row, slot, rel(Z54 / "live"), cand_rtf)
        elif panel == "R" and i < 2183:
            matches = [m for m in z52_index.get((i, arm), []) if m[3] == row]
            if not matches:
                problems.append({"slot": row["slot_id"], "problem": "no Z52 result.json equals the analysed row"})
                continue
            matches.sort(key=lambda m: m[0])
            primary = matches[0]
            for m in matches:
                sha(m[2] / "result.json")
            dups = []
            for m in matches[1:]:
                pf, _ = slot_files(primary[2], arm)
                mf, _ = slot_files(m[2], arm)
                same = [f.name for f in pf] == [f.name for f in mf] and all(sha(a) == sha(b) for a, b in zip(pf, mf))
                dups.append({"slot_dir": rel(m[2]), "identical_files": same, "copy_root": m[1]})
                if not same:
                    problems.append({"slot": row["slot_id"], "problem": "matching copies with different bytes",
                                     "copy": rel(m[2])})
            register(panel, row, primary[2], rel(primary[2].parents[2]), cand_rtf, dups)
        else:
            slot = Z53 / "live/blocks" / f"{panel}-{i:05d}" / arm
            result = load(slot / "result.json")
            if result != row:
                problems.append({"slot": row["slot_id"], "problem": "Z53 result differs from analysed row"})
            register(panel, row, slot, rel(Z53 / "live"), cand_rtf)

# ------------------------------------------------------------------ summary and output
count = Counter((r["panel"], r["arm"], r["kind"]) for r in runs)
sources = Counter((r["panel"], r["arm"], r["source"]) for r in runs)
panels = {}
for (panel, arm, kind), n in sorted(count.items()):
    panels.setdefault(panel, {})[arm] = {
        "runs": n, "kind": kind,
        "sources": {s: c for (p, a, s), c in sorted(sources.items()) if p == panel and a == arm},
        "open_with_terminal_file": sum(1 for r in runs if r["panel"] == panel and r["arm"] == arm
                                       and r.get("terminal_failure_file")),
        "with_duplicate_copies": sum(1 for r in runs if r["panel"] == panel and r["arm"] == arm and r.get("duplicates"))}
expected_counts = {"P": {"Q": 9040, "F": 9040}, "R": {a: 2952 for a in ("S", "S-k", "D", "Z", "Q", "F")},
                   "T": {"Q-TF": 2952, "Q-ST": 2952}, "F": {a: 2952 for a in ("Qc", "Qf", "Fc", "Ff")}}
check("run_counts_as_planned", {p: {a: v["runs"] for a, v in arms.items()} for p, arms in panels.items()} == expected_counts,
      {p: {a: v["runs"] for a, v in arms.items()} for p, arms in panels.items()})
check("unique_slots", len({r["slot_id"] for r in runs}) == len(runs) == sum(sum(v.values()) for v in expected_counts.values()))
check("no_location_problems", not problems, len(problems))

runs_path = OUTDIR / "MANIFEST-RUNS.jsonl"
files_path = OUTDIR / "MANIFEST-FILES.jsonl"
with runs_path.open("x") as out:
    for r in runs:
        out.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
with files_path.open("x") as out:
    for k in sorted(FILES):
        out.write(json.dumps({"path": k, "sha256": FILES[k][0], "bytes": FILES[k][1]}) + "\n")


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


manifest = {
    "schema": "z56-v2-data-manifest/v1",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "builder": {"path": rel(Path(__file__)), "sha256": file_sha(__file__)},
    "root": str(RUNS),
    "derivation": __doc__,
    "analysis_inputs": {k: {"path": rel(v), "sha256": sha(v)} for k, v in (
        ("P_state", P_STATE), ("P_final_hold", P_HOLD), ("P_analysis", P_ANALYSIS), ("P_status", P_STATUS),
        ("R_rows_SK", Z54 / "live/collected/rows-R-SK.json"), ("R_rows_Z53", Z53 / "live/collected/rows-R.json"),
        ("T_rows", Z53 / "live/collected/rows-T.json"), ("F_rows", Z53 / "live/collected/rows-F.json"),
        ("R_analysis_SK", Z54 / "ANALYSIS-R-SK.json"), ("T_analysis", Z53 / "ANALYSIS-T.json"),
        ("F_analysis", Z53 / "ANALYSIS-F.json"), ("Z52_inspect", z52_inspect), ("plan", PLAN),
        ("candidate_P", CAND_P), ("candidate_RTF", CAND_RTF))},
    "z52_roots": {"chain": Z52_CHAIN, "copies": Z52_COPIES},
    "p_segments": {f"{k}": rel(v) for k, v in P_SEG.items()},
    "panels": panels,
    "totals": {"runs": len(runs), "mas_runs": sum(r["kind"] == "mas" for r in runs),
               "direct_runs": sum(r["kind"] == "direct" for r in runs), "files_read": len(FILES),
               "bytes_read": sum(v[1] for v in FILES.values())},
    "checks": CHECKS,
    "problems": problems,
    "sidecars": {"runs": {"path": runs_path.name, "sha256": file_sha(runs_path), "lines": len(runs)},
                 "files": {"path": files_path.name, "sha256": file_sha(files_path), "lines": len(FILES)}},
}
with (OUTDIR / "MANIFEST.json").open("x") as out:
    json.dump(manifest, out, indent=1, ensure_ascii=False)
    out.write("\n")
print(json.dumps({"totals": manifest["totals"], "checks_failed": [c["check"] for c in CHECKS if not c["passed"]],
                  "problems": len(problems), "manifest_sha256": file_sha(OUTDIR / "MANIFEST.json")}, indent=1))
