"""V3e: Z37 violation set V1..V8 (+ controls K1, K3, K4) through the LangGraph attachment.

Reused unchanged from runs/Z37-MESSABNAHME-001/private/generate.py (imported, not copied):
SyntheticClient (inner model client with native usage and tariff), manual_journal, reseal,
trace_from_records, independently_priced, ROLES, EDGES, write_jsonl. Case construction follows
generate.build_case; the deliberate defects are placed as the Z56 plan prescribes:
  V1  additional unmasked LangGraph edge draft@1 -> linking@2 (not inside the client)
  V2  additional LangGraph node 'aux' that calls the inner client directly, bypassing the sender
  V3  client mode V3 (adapter reports +0.00037 USD at outer call 3), as in Z37
  V4  client mode V4 (technical stop at outer call 3) plus a false completion claim, as in Z37
  V5-V8  edits of the produced journal records exactly as generate.build_case (lines 300-333)
K2 (suppressed role, one round) is not built: the attachment does not implement failed_role.
Instrument = Z37 instrument/run_instrument.py logic (audit/audit_prefix on the trace, read_journal
on the journal); additionally the online result of the unchanged Journal during the run.
"""
import common
from common import EVAL, OUT, Decimal, canonical, file_sha, netguard, write_json
import binding

from copy import deepcopy
import importlib.util
import shutil
import time
import traceback

from communication_pruning.audit import audit, audit_prefix
from communication_pruning.contracts import INSTRUCTIONS, Configuration, Request, TaskInput
from communication_pruning.failure_policy import F01
from communication_pruning.journal import read_journal

import lg_adapter as lg

GEN_PATH = EVAL / "runs/Z37-MESSABNAHME-001/private/generate.py"
_spec = importlib.util.spec_from_file_location("z37_generate", GEN_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)          # generate.py replaces socket functions with its own refusal ...
netguard.install()                     # ... so the counting V3 lock is installed again on top
assert netguard.installed()

LABELS = ("K1", "K3", "K4", "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8")
CLIENT_MODE = {"K1": "K1", "K3": "K3", "K4": "K4", "V1": "K1", "V2": "K1", "V3": "V3", "V4": "V4",
               "V5": "K1", "V6": "K1", "V7": "K1", "V8": "K1", "V1z": "K1"}
EXPECTED_REJECTED = {"V1", "V5", "V6", "V7", "V8"}          # pre-registered (plan V3e)
EXPECTED_ACCEPTED = {"V2", "V3", "V4", "K1", "K3", "K4"}


def instrument(trace, journal, config):
    """Exactly instrument/run_instrument.py of Z37 (lines 41-58)."""
    record = {}
    partial = not ("answer" in trace and "status" in trace)
    try:
        metrics = (audit_prefix if partial else audit)(trace, config)
        record["trace"] = {"accepted": True, "partial_mode": partial, "metrics": metrics}
    except Exception as error:  # noqa: BLE001
        record["trace"] = {"accepted": False, "partial_mode": partial, "exception": type(error).__name__,
                           "message": str(error)}
    try:
        report = read_journal(journal, config)
        record["journal"] = {"accepted": True, "sealed": report["sealed"], "metrics": report["audit"],
                             "returned_trace_matches_supplied_trace": report["trace"] == trace}
    except Exception as error:  # noqa: BLE001
        record["journal"] = {"accepted": False, "exception": type(error).__name__, "message": str(error)}
    return record


def build_case(label, root, v1_delivery=None):
    case_id = f"z56-{label.lower()}"
    folder = root / case_id
    folder.mkdir(parents=True)
    run_id = f"run-{case_id}"
    config = Configuration("bank-" + case_id, gen.ROLES, gen.EDGES)
    task = TaskInput("task-" + case_id, "Welche Markierung trägt der künstliche Behälter?",
                     (f"Im künstlichen Register {case_id} trägt der Behälter die Markierung amber.",
                      "Dieser Text dient ausschließlich einer technischen Fallprüfung."))
    client = gen.SyntheticClient(case_id, CLIENT_MODE[label])
    kwargs, aux_calls = {}, []
    if label == "V1":
        kwargs["extra_edges"] = [("draft@1", "linking@2")]
    if label == "V2":
        def aux(_state):
            extra = Request(f"{run_id}:1:linking:1:aux", task, "linking", 1, INSTRUCTIONS["linking"], (), 1024)
            aux_calls.append(extra.attempt_id)
            client.native(extra)            # inner model client, past the logging sender and the journal
            return {}
        kwargs.update(extra_nodes=[("aux", aux)], extra_edges=[("linking@1", "aux")],
                      extra_waits={lg.node_id(r, 2): ["aux"] for r in gen.ROLES})
    journal = folder / "original-journal.jsonl"
    evidence, online = {}, {"raised": None}
    try:
        lg.run(task, config, client, rounds=2, run_id=run_id, journal_path=journal, producer_limit=1024,
               failure_policy=F01, evidence=evidence, **kwargs)
    except Exception as error:  # noqa: BLE001 - K4/V4 technical stop, V1 online rejection
        online["raised"] = {"exception": type(error).__name__, "message": str(error)}
        (folder / "run-exception.log").write_text(traceback.format_exc())
    records, original_trace = gen.manual_journal(journal)
    notes = []
    if label == "V1z":
        # Z37 evidence form of V1: the journal is made to describe the delivery the V1 graph really produced
        event = next(r["payload"]["event"] for r in records if r["payload"]["kind"] == "event"
                     and r["payload"]["event"].get("kind") == "started" and r["payload"]["event"]["attempt_id"].endswith(":2:linking:1"))
        produced = {e["attempt_id"]: e for e in (r["payload"]["event"] for r in records if r["payload"]["kind"] == "event")
                    if e["kind"] == "completed"}
        event["messages"] = [{"attempt_id": f"{run_id}:{rnd}:{role}:1", "role": role, "round": rnd,
                              "text": produced[f"{run_id}:{rnd}:{role}:1"]["text"]} for role, rnd in v1_delivery]
        records = gen.reseal(records)
        notes.append("Supplementary Z37 evidence form of V1: linking@2 started messages set to the sources the V1 LangGraph graph delivered; envelopes resealed.")
    if label == "V5":
        index = next(i for i, record in enumerate(records) if record["payload"]["kind"] == "event"
                     and record["payload"]["event"].get("kind") == "completed"
                     and record["payload"]["event"].get("attempt_id", "").endswith(":1:linking:1"))
        records.pop(index)
        records = gen.reseal(records)
        notes.append("One completed event removed; envelopes resealed (generate.py V5).")
    if label == "V6":
        index = next(i for i, record in enumerate(records) if record["payload"]["kind"] == "event"
                     and record["payload"]["event"].get("kind") == "completed")
        records.insert(index + 1, deepcopy(records[index]))
        records = gen.reseal(records)
        notes.append("One completed event duplicated; envelopes resealed (generate.py V6).")
    if label == "V7":
        event = next(record["payload"]["event"] for record in records if record["payload"]["kind"] == "event"
                     and record["payload"]["event"].get("kind") == "completed")
        event["attempt_id"] = event["attempt_id"].replace(":evidence:", ":checking:")
        records = gen.reseal(records)
        notes.append("First terminal attempt ID moved to checking; envelopes resealed (generate.py V7).")
    if label == "V8":
        event = next(record["payload"]["event"] for record in records if record["payload"]["kind"] == "event"
                     and record["payload"]["event"].get("kind") == "completed")
        event["usage"]["price_version"] += "-r"
        notes.append("First terminal price version changed without rehashing (generate.py V8).")
    final_trace = gen.trace_from_records(records)
    public = folder / "journal.jsonl"
    if label in ("V1z", "V5", "V6", "V7", "V8"):
        gen.write_jsonl(public, records)
    else:
        shutil.copyfile(journal, public)
    write_json(folder / "trace.json", final_trace)
    terminal = [e for e in original_trace["events"] if e["kind"] in ("completed", "model_failed")]
    subtotal = sum((Decimal(e["usage"]["cost_usd"]) for e in terminal), Decimal(0))
    complete = "status" in original_trace
    claimed = {"status": original_trace.get("status", "technical_stop"), "answer": original_trace.get("answer"),
               "measurement_complete": complete, "started_attempts": len(client.observed), "calls": len(terminal),
               "known_cost_subtotal_usd": str(subtotal), "total_cost_usd": str(subtotal) if complete else None}
    if label == "V4":
        claimed.update(status="completed", answer=f"{case_id}|aggregator|3|amber", measurement_complete=True,
                       total_cost_usd=str(subtotal))
        notes.append("Report claims completion although the journal is open (generate.py V4).")
    judged = instrument(final_trace, public, config)
    persisted_original = instrument(original_trace, journal, config) if label == "V1" else None
    inner = gen.independently_priced(client.usage, client.tariff())
    case = {"label": label, "case_id": case_id, "client_mode": CLIENT_MODE[label], "config": common.plain(config.__dict__),
            "online": online, "instrument": judged, "persisted_original_instrument": persisted_original,
            "claimed": claimed, "inner_truth": inner, "outer_requests": len(client.observed),
            "inner_calls": len(client.usage), "aux_calls": aux_calls, "notes": notes,
            "graph": {k: evidence.get(k) for k in ("graph_edges", "graph_waiting_edges", "realized_edges",
                                                    "removed_edges", "delivered_sources", "executed", "schedule")},
            "files": {p.name: file_sha(p) for p in sorted(folder.iterdir()) if p.is_file()}}
    gen.write_jsonl(folder / "client.jsonl", client.client)
    gen.write_jsonl(folder / "usage.jsonl", client.usage)
    gen.write_jsonl(folder / "observed_requests.jsonl", client.observed)
    write_json(folder / "case.json", case)
    return case


def verdict(case):
    online_rejected = case["online"]["raised"] is not None and case["online"]["raised"]["exception"] == "AuditError"
    trace_rejected = not case["instrument"]["trace"]["accepted"]
    journal_rejected = not case["instrument"]["journal"]["accepted"]
    rejected = online_rejected or trace_rejected or journal_rejected
    return {"online_rejected": online_rejected, "trace_rejected": trace_rejected, "journal_rejected": journal_rejected,
            "rejected_by_pruefroutine": rejected,
            "journal_sealed": case["instrument"]["journal"].get("sealed")}


def main():
    t0 = time.time()
    root = OUT / "v3e"
    root.mkdir(parents=True, exist_ok=False)
    sources = binding.bind(root, "run_v3e.py")
    cases = {label: build_case(label, root) for label in LABELS}
    v1_delivery = [lg.split(s) for s in cases["V1"]["graph"]["delivered_sources"]["linking@2"]]
    cases["V1z"] = build_case("V1z", root, v1_delivery)
    rows = {}
    for label, case in cases.items():
        v = verdict(case)
        expected = "rejected" if label in EXPECTED_REJECTED else "accepted" if label in EXPECTED_ACCEPTED else "supplementary"
        observed = "rejected" if v["rejected_by_pruefroutine"] else "accepted"
        rows[label] = {**v, "expected": expected, "observed": observed,
                       "matches": expected == "supplementary" or expected == observed,
                       "online": case["online"]["raised"],
                       "trace_exception": case["instrument"]["trace"].get("message"),
                       "journal_exception": case["instrument"]["journal"].get("message"),
                       "journal_metrics": case["instrument"]["journal"].get("metrics"),
                       "persisted_original_journal": None if case["persisted_original_instrument"] is None else {
                           "accepted": case["persisted_original_instrument"]["journal"]["accepted"],
                           "sealed": case["persisted_original_instrument"]["journal"].get("sealed"),
                           "metrics": case["persisted_original_instrument"]["journal"].get("metrics")},
                       "claimed": case["claimed"], "outer_requests": case["outer_requests"],
                       "inner_calls": case["inner_calls"], "inner_truth": case["inner_truth"]}
    pattern = {"rejected": sorted(l for l in ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8") if rows[l]["observed"] == "rejected"),
               "accepted": sorted(l for l in ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8") if rows[l]["observed"] == "accepted")}
    summary = {"expected_pattern": {"rejected": sorted(EXPECTED_REJECTED), "accepted": ["V2", "V3", "V4"]},
               "observed_pattern": pattern,
               "pattern_matches": pattern == {"rejected": sorted(EXPECTED_REJECTED), "accepted": ["V2", "V3", "V4"]},
               "controls_accepted": all(rows[k]["observed"] == "accepted" for k in ("K1", "K3", "K4")),
               "cases": rows, "z37_generate_sha256": file_sha(GEN_PATH), "sources": sources["files"],
               "network": netguard.report(), "seconds": round(time.time() - t0, 1)}
    write_json(root / "SUMMARY.json", summary)
    print(canonical({k: summary[k] for k in ("expected_pattern", "observed_pattern", "pattern_matches",
                                             "controls_accepted", "network")}).decode())
    for label, row in rows.items():
        print(label, row["observed"], "online" if row["online_rejected"] else "", row["online"] and row["online"]["exception"],
              "trace:", row["trace_exception"], "| journal:", row["journal_exception"], "| sealed:", row["journal_sealed"],
              "| outer/inner:", row["outer_requests"], row["inner_calls"])


if __name__ == "__main__":
    main()
