#!/usr/bin/env python3
"""Z56 V2b-V2f: apply the unchanged framework reader/audit to every manifest run (read only).

V2b  communication_pruning.journal.read_journal(path, expected_config) -> audit() for sealed
     journals, audit_prefix() for unsealed (open) journals; the expected configuration comes
     from MANIFEST-RUNS.jsonl (plan + saved selection + candidate), never from the journal.
     On a rejection, audit()/audit_prefix() are additionally applied to an own parse of the
     journal records to separate envelope/chain errors from content errors.
V2d  own structural counts from an own parse (separate from the audit routine).
V2e  direct arms (S, S-k) are not applicable; own structure check reported separately.
V2f  every file listed in MANIFEST-FILES.jsonl is hashed again after the audit.
Writes only into this v2 folder (argument: output subfolder name, create-only).
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
EVAL = HERE.parents[2]
RUNS = EVAL / "runs"
sys.path.insert(0, str(EVAL))
from communication_pruning.audit import AuditError, audit, audit_prefix  # noqa: E402
from communication_pruning.contracts import Configuration  # noqa: E402
from communication_pruning.journal import JournalError, read_journal  # noqa: E402

import os
MDIR = Path(os.environ.get("Z56_V2_DIR", str(HERE)))    # scratch only for the pre-run test
OUT = MDIR / sys.argv[1]
OUT.mkdir()
T0 = time.time()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


manifest = json.loads((MDIR / "MANIFEST.json").read_bytes())
for name, side in manifest["sidecars"].items():
    assert file_sha(MDIR / side["path"]) == side["sha256"], f"manifest sidecar changed: {name}"
runs = [json.loads(line) for line in (MDIR / manifest["sidecars"]["runs"]["path"]).read_text().splitlines()]
files = [json.loads(line) for line in (MDIR / manifest["sidecars"]["files"]["path"]).read_text().splitlines()]
assert len(runs) == manifest["sidecars"]["runs"]["lines"] and len(files) == manifest["sidecars"]["files"]["lines"]
SAMPLE = int(os.environ.get("Z56_V2_SAMPLE", "0"))   # pre-run harness test only (scratch); 0 = all runs
if SAMPLE:
    runs = [r for i, r in enumerate(runs) if i % SAMPLE == 0 or r.get("terminal_failure_file")]
    if os.environ.get("Z56_V2_NEGATIVE_CONTROL"):
        # harness self-test: a deliberately wrong expected configuration must be reported as a rejection
        bad = json.loads(json.dumps(next(r for r in runs if r["kind"] == "mas")))
        bad["slot_id"] += ":negative-control"
        bad["expected"].update(config_id="C14", roles=["linking", "draft", "checking"],
                               edges=[["linking", "draft"], ["linking", "checking"], ["draft", "linking"],
                                      ["draft", "checking"], ["checking", "linking"], ["checking", "draft"]])
        runs.append(bad)


def own_parse(path):
    """Independent minimal parse of the journal records (no checksum verification)."""
    trace, sealed, records = None, False, 0
    for line in Path(path).read_bytes().splitlines():
        record = json.loads(line)
        payload = record["payload"]
        records += 1
        if payload["kind"] == "header":
            trace = json.loads(json.dumps(payload["trace"]))
        elif payload["kind"] == "event":
            trace["events"].append(payload["event"])
        elif payload["kind"] == "finished":
            trace.update(answer=payload["answer"], status=payload["status"])
            sealed = True
    return trace, sealed, records


def structure(trace, sealed, run):
    exp = run["expected"]
    roles, edges, failed, rounds = exp["roles"], [list(e) for e in exp["edges"]], exp["failed_role"], exp["rounds"]
    events = trace["events"]
    started = [e for e in events if e.get("kind") == "started"]
    allowed_roles = set(roles) | {"aggregator"}
    inactive = [e["attempt_id"] for e in started if e["role"] not in allowed_roles or e["role"] == failed]
    disallowed, wrong_round, aggregator_foreign = [], 0, 0
    for e in started:
        for m in e["messages"]:
            src = m.get("role")
            ok = src in roles and src != failed and (e["role"] == "aggregator" or src == e["role"] or [src, e["role"]] in edges)
            if not ok:
                disallowed.append((e["attempt_id"], src))
            if m.get("round") != e["round"] - 1:
                wrong_round += 1
    soll = rounds * (len(roles) - (1 if failed is not None else 0)) + 1
    terminal = Counter(e["kind"] for e in events if e.get("kind") in ("completed", "failed", "model_failed"))
    suppressed = sum(1 for e in events if e.get("kind") == "suppressed")
    n = len(started)
    if n == soll:
        calls = "equal"
    elif n > soll:
        calls = "more"
    elif terminal.get("model_failed"):
        calls = "fewer_model_failure"
    elif not sealed and run.get("terminal_failure_file"):
        calls = "fewer_open_terminal_file"
    else:
        calls = "fewer_unexplained"
    binding = {"run_id": trace.get("run_id") == run["run_id"], "rounds": trace.get("rounds") == rounds,
               "failed_role": trace.get("failed_role") == failed,
               "configuration": trace.get("configuration") == {"config_id": exp["config_id"], "roles": roles,
                                                               "edges": edges}}
    return {"started": n, "soll": soll, "calls": calls, "inactive_role_calls": len(inactive),
            "disallowed_messages": len(disallowed), "wrong_round_messages": wrong_round,
            "suppressed_events": suppressed, "suppressed_soll": rounds if failed is not None else 0,
            "terminal": dict(terminal), "sealed": sealed, "status": trace.get("status"),
            "row_call_count_equal": run["row"]["call_count"] == n, "binding": binding,
            "disallowed_examples": disallowed[:3], "inactive_examples": inactive[:3]}


def direct_structure(run):
    slot = RUNS / run["slot_dir"]
    started = json.loads((slot / "direct-started.json").read_bytes())
    samples = sorted(slot.glob("direct-[1-5].json"))
    maximum = 1 if run["arm"] == "S" else 5
    outcomes = [json.loads(p.read_bytes()) for p in samples]
    failures = [o for o in outcomes if o["outcome"]["kind"] == "model_failed"]
    requests_ok = all(o["request"]["role"] == "single" and o["request"]["messages"] == [] and o["request"]["round"] == 1
                      for o in outcomes)
    names_ok = [p.name for p in samples] == [f"direct-{i + 1}.json" for i in range(len(samples))]
    count_ok = len(samples) == maximum or (failures and outcomes[-1] is failures[0] and len(failures) == 1)
    return {"samples": len(samples), "maximum": maximum, "maximum_bound": started.get("maximum_calls") == maximum,
            "run_id_bound": started.get("run_id") == run["run_id"], "single_role_no_messages": requests_ok,
            "contiguous": names_ok, "count_ok": bool(count_ok), "row_call_count_equal": run["row"]["call_count"] == len(samples),
            "model_failures": len(failures)}


results = []
for index, run in enumerate(runs):
    record = {"slot_id": run["slot_id"], "panel": run["panel"], "arm": run["arm"], "kind": run["kind"]}
    if run["kind"] == "direct":
        record["outcome"] = "not_applicable"
        record["reason"] = ("direct single-agent arm (S/S-k): direct-*.json samples, no MAS journal and no "
                            "Configuration; audit/audit_prefix/read_journal are defined only for MAS traces")
        record["own_structure"] = direct_structure(run)
        results.append(record)
        continue
    exp = run["expected"]
    config = Configuration(exp["config_id"], tuple(exp["roles"]), tuple(tuple(e) for e in exp["edges"]))
    path = RUNS / run["journal"]
    try:
        got = read_journal(path, config)
        record["outcome"] = "accepted" if got["sealed"] else "accepted_prefix"
        record["routine"] = "read_journal->audit" if got["sealed"] else "read_journal->audit_prefix"
        record["audit"] = got["audit"]
    except (JournalError, AuditError) as error:
        record["outcome"] = "rejected"
        record["reason"] = f"{type(error).__name__}: {error}"
    except Exception as error:  # noqa: BLE001  any other failure is a rejection with its type
        record["outcome"] = "rejected"
        record["reason"] = f"unexpected {type(error).__name__}: {error}"
    try:
        trace, sealed, nrec = own_parse(path)
        record["own_structure"] = structure(trace, sealed, run)
        record["own_structure"]["records"] = nrec
        if record["outcome"] == "rejected":
            try:
                record["content_audit_on_own_parse"] = (audit if sealed else audit_prefix)(trace, config)
            except AuditError as error:
                record["content_audit_on_own_parse"] = f"AuditError: {error}"
        if record["outcome"] == "accepted_prefix":
            # open run: full audit() is expected to reject (no terminal event); reported for transparency
            try:
                audit(trace, config)
                record["full_audit_on_open_run"] = "accepted"
            except AuditError as error:
                record["full_audit_on_open_run"] = f"AuditError: {error}"
            unresolved = record["audit"].get("unresolved_attempt_ids")
            term = run.get("terminal_failure_file")
            record["open_run_terminal_file"] = term
            if term:
                tf = json.loads((RUNS / term).read_bytes())
                attempt = tf.get("attempt_id") or tf.get("adoption", {}).get("dispatch", {}).get("logical_id")
                record["open_run_terminal_attempt"] = attempt
                record["open_run_terminal_attempt_matches"] = attempt in (unresolved or [])
                record["open_run_terminal_reason"] = tf.get("reason") or tf.get("rule") or Path(term).name
    except Exception as error:  # noqa: BLE001
        record["own_structure_error"] = f"{type(error).__name__}: {error}"
    results.append(record)
    if index % 5000 == 0:
        print(f"{index}/{len(runs)} {time.time() - T0:.0f}s", flush=True)

with (OUT / "RESULTS.jsonl").open("x") as out:
    for r in results:
        out.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")

# ------------------------------------------------------------------ aggregation
table = defaultdict(lambda: defaultdict(int))
reasons = defaultdict(Counter)
for r in results:
    k = (r["panel"], r["arm"])
    table[k]["runs"] += 1
    table[k][r["outcome"]] += 1
    if r["outcome"] == "rejected":
        reasons[k][r["reason"]] += 1
    s = r.get("own_structure")
    if r["kind"] == "mas" and s:
        table[k]["disallowed_messages"] += s["disallowed_messages"]
        table[k]["inactive_role_calls"] += s["inactive_role_calls"]
        table[k]["wrong_round_messages"] += s["wrong_round_messages"]
        table[k]["calls_" + s["calls"]] += 1
        table[k]["started_calls"] += s["started"]
        table[k]["row_call_count_mismatch"] += not s["row_call_count_equal"]
        table[k]["binding_mismatch"] += not all(s["binding"].values())
        table[k]["suppressed_mismatch"] += s["suppressed_events"] != s["suppressed_soll"] and s["status"] == "completed"
        if r["outcome"] == "accepted_prefix":
            table[k]["open_terminal_attempt_matches"] += bool(r.get("open_run_terminal_attempt_matches"))
            table[k]["open_full_audit_rejects"] += str(r.get("full_audit_on_open_run", "")).startswith("AuditError")
        if r["outcome"] == "accepted":
            table[k]["status_" + str(s["status"])] += 1
            table[k]["audit_unknown_cost_calls"] += r["audit"]["unknown_cost_calls"]
            table[k]["audit_total_cost_none"] += r["audit"]["total_cost_usd"] is None
    elif r["kind"] == "direct" and s:
        bad = [name for name in ("maximum_bound", "run_id_bound", "single_role_no_messages", "contiguous", "count_ok",
                                 "row_call_count_equal") if not s[name]]
        table[k]["own_direct_structure_ok"] += not bad
        table[k]["own_direct_structure_bad"] += bool(bad)
        table[k]["direct_samples"] += s["samples"]
    if r.get("own_structure_error"):
        table[k]["own_structure_error"] += 1

print("rehash", flush=True)
changed = []
for f in files:
    p = RUNS / f["path"]
    if not p.is_file() or file_sha(p) != f["sha256"]:
        changed.append(f["path"])
summary = {
    "schema": "z56-v2-audit-result/v1",
    "finished_utc": datetime.now(timezone.utc).isoformat(),
    "seconds": round(time.time() - T0, 1),
    "script": {"path": str(Path(__file__).resolve().relative_to(RUNS)), "sha256": file_sha(__file__)},
    "manifest_sha256": file_sha(MDIR / "MANIFEST.json"),
    "framework_modules_sha256": {name: file_sha(EVAL / "communication_pruning" / name)
                                 for name in ("audit.py", "journal.py", "contracts.py", "failure_policy.py")},
    "python": sys.version,
    "table": {f"{p}/{a}": dict(v) for (p, a), v in sorted(table.items())},
    "rejection_reasons": {f"{p}/{a}": dict(v) for (p, a), v in sorted(reasons.items())},
    "v2f": {"files": len(files), "changed_or_missing": changed},
    "results_sha256": file_sha(OUT / "RESULTS.jsonl"),
}
with (OUT / "SUMMARY.json").open("x") as out:
    json.dump(summary, out, indent=1, ensure_ascii=False)
    out.write("\n")
print(json.dumps({"seconds": summary["seconds"], "rejected": sum(r["outcome"] == "rejected" for r in results),
                  "accepted": sum(r["outcome"] == "accepted" for r in results),
                  "accepted_prefix": sum(r["outcome"] == "accepted_prefix" for r in results),
                  "not_applicable": sum(r["outcome"] == "not_applicable" for r in results),
                  "v2f_changed": len(changed)}, indent=1))
