"""V3d: LangGraph replay on the 100 Z55 R blocks (R-02183..R-02282), arms F* (C01) and D.

Answers come from the stored Z53 evidence exactly as in run_z55.py replay (Replay below has the
identical logic of run_z55.Replay; re-implemented because importing run_z55 prepends the
Python-3.12 GPTSwarm runtime to sys.path). Sender shell reused unchanged from the framework's Z55
module: DemoSender (Z53 BlockSender + pre-send round-1 byte guard), BrakedTransport, CostBrake.
Only the graph differs: LangGraph instead of GPTSwarm, LoggingSender/Journal instead of ArmContext.

  run_v3d.py Z55_REPLAY_FOLDER
"""
import common
from common import EVAL, OUT, SMOKE, Decimal, canonical, netguard, write_json, write_jsonl
import binding

import json
from pathlib import Path
import sys
import time

from communication_pruning import gptswarm_musique_demo as g
from communication_pruning.failure_policy import F01
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import ProbeStop, encoded
from study_preparation import z53_fast as z

import lg_adapter as lg

Z53_BLOCKS = EVAL / "runs/Z53-SCHNELLFORTSETZUNG-001/live/blocks"
BLOCKS = [f"R-{i:05d}" for i in range(2183, 2283)][: 3 if SMOKE else None]


class Replay:
    """Same logic as run_z55.Replay (run_z55.py:194-212)."""

    def __init__(self, block):
        self.queue = {}
        for arm in g.ARMS:
            ref = g.z53_arm(block, arm)
            for key, body in ref["requests"].items():
                if key in ref["answers"]:
                    self.queue.setdefault(body, []).append(ref["answers"][key])
        self.misses = 0

    def __call__(self, endpoint, body):
        z.need(endpoint == "chat/completions", "endpoint")
        if not self.queue.get(body):
            self.misses += 1
            raise ProbeStop("replay: request bytes without recorded Z53 answer")
        return 200, self.queue[body].pop(0)


def run_arm(arm, task, reference, run_id, sender, folder):
    folder.mkdir()
    config = g.arm_config(arm)
    evidence, reason = {}, None
    try:
        trace = lg.run(task, config, sender, rounds=2, run_id=run_id, journal_path=folder / "journal.jsonl",
                       producer_limit=1024, failure_policy=F01, evidence=evidence)
        answer = trace["answer"]
        if trace["status"] == "completed":
            status = "ok"
        else:
            status = "model_failure"
            reason = next(e["reason"] for e in trace["events"] if e["kind"] == "model_failed")
    except z.TerminalArmFailure as failure:
        status, answer, reason = "model_failure", None, failure.reason
    scores = g.score_answer(answer, reference) if status == "ok" else {"em": 0.0, "f1": 0.0}
    result = {"arm": arm, "configuration": config.config_id, "run_id": run_id, "framework": "langgraph==1.0.6",
              "status": status, "em": scores["em"], "f1": scores["f1"], "answer": answer, "failure_reason": reason,
              "call_count": sender.calls_for(run_id), "cost_usd": str(sender.cost_for(run_id)),
              "unknown_attempts": sender.unknown_attempts, "executed": evidence["executed"],
              "delivered_sources": evidence["delivered_sources"]}
    (folder / "result.json").write_bytes(encoded(result))
    (folder / "graph.json").write_bytes(encoded({k: evidence[k] for k in (
        "potential_edges", "mask", "realized_edges", "removed_edges", "graph_edges", "graph_waiting_edges", "schedule")}))
    return result, evidence


def run_block(name, directory):
    block = Z53_BLOCKS / name
    directory.mkdir(parents=True)
    task, reference = g.load_task(block)
    transport = Replay(block)
    braked = g.BrakedTransport(transport, g.CostBrake(), z.GlobalStop, directory / "brake.jsonl")
    sender_class = g.make_sender_class()
    results, evidence = {}, {}
    for arm in g.ARMS:
        expected_round1, reconstructed = g.round1_bytes(g.z53_arm(block, arm), task, g.arm_config(arm))
        sender = sender_class(directory / f"provider-{arm}", braked, max_calls=g.EXPECTED_CALLS[arm],
                              deadline=time.time() + 10 ** 6, sleep=lambda _s: None, round1=expected_round1)
        results[arm], evidence[arm] = run_arm(arm, task, reference, f"Z56V3:{name}:{arm}", sender, directory / arm)
        results[arm]["round1_reconstructed"] = reconstructed
    return results, evidence, transport.misses


def keyed(provider, run_id):
    items, unknown, physical = g._provider(provider)
    return {a[len(run_id) + 1:]: v for a, v in items.items()}, unknown, physical


def normalized(trace):
    return json.loads(json.dumps(trace).replace(trace["run_id"], "<RUN>"))


def compare_block(name, directory, z55_dir, results):
    block = Z53_BLOCKS / name
    row = {"block": name}
    par = g.parity(directory, block)
    brake_mine = (directory / "brake.jsonl").read_text().splitlines()
    brake_z55 = (z55_dir / "brake.jsonl").read_text().splitlines()
    row["brake_ledger_equal_z55"] = brake_mine == brake_z55
    for arm in g.ARMS:
        config = g.arm_config(arm)
        mine, _, _ = keyed(directory / f"provider-{arm}", f"Z56V3:{name}:{arm}")
        theirs, _, _ = keyed(z55_dir / f"provider-{arm}", f"Z55:{name}:{arm}")
        z55_result = json.loads((z55_dir / arm / "result.json").read_bytes())
        result = results[arm]
        journal = read_journal(directory / arm / "journal.jsonl", config)
        z53_journal = read_journal(block / arm / "journal.jsonl", config)
        started = [e for e in journal["trace"]["events"] if e["kind"] == "started"]
        r = {
            "status": result["status"], "calls": result["call_count"], "cost_usd": result["cost_usd"],
            "calls_equal_z55": sorted(mine) == sorted(theirs),
            "requests_equal_z55": sorted(mine) == sorted(theirs) and all(mine[k]["body"] == theirs[k]["body"] for k in mine),
            "answers_equal_z55": all(mine[k]["answer"] == theirs[k]["answer"] for k in mine if k in theirs),
            "billing_equal_z55": all(mine[k]["billed"] == theirs[k]["billed"] for k in mine if k in theirs),
            "result_equal_z55": all(result[k] == z55_result[k] for k in ("status", "em", "f1", "answer", "failure_reason",
                                                                        "call_count", "cost_usd")),
            "round1_equal_z53": par[arm]["round1_identical"],
            "requests_equal_z53": par[arm]["all_requests_identical"],
            "answers_equal_z53": par[arm]["all_answers_identical"],
            "result_equal_z53": all(par[arm]["demo"][k] == par[arm]["z53"][k] for k in ("status", "em", "f1", "call_count"))
            and Decimal(par[arm]["demo"]["cost_usd"]) == Decimal(par[arm]["z53"]["cost_usd"]),
            "journal_accepted": True, "journal_sealed": journal["sealed"],
            "journal_equal_z53_modulo_run_id": normalized(journal["trace"]) == normalized(z53_journal["trace"]),
            "count_ok": result["status"] != "ok" or result["call_count"] == g.EXPECTED_CALLS[arm],
            "inactive_role_calls": sum(1 for e in started if e["role"] not in config.roles + ("aggregator",)),
            "messages": sum(len(e["messages"]) for e in started),
            "removed_graph_edges": json.loads((directory / arm / "graph.json").read_bytes())["removed_edges"],
            "failure_reason": result["failure_reason"],
        }
        row[arm] = r
    return row


def main():
    z55_root = Path(sys.argv[1]).resolve()
    t0 = time.time()
    folder = OUT / "v3d"
    folder.mkdir(parents=True, exist_ok=True)       # z55-replay may already live here
    sources = binding.bind(folder, "run_v3d.py", "z55_replay_guarded.py", "hash_inputs.py")
    rows, misses, errors = [], 0, []
    for name in BLOCKS:
        directory = folder / "lg" / name
        try:
            results, _, missed = run_block(name, directory)
            misses += missed
            rows.append(compare_block(name, directory, z55_root / name, results))
        except Exception as exc:  # noqa: BLE001 - recorded, counted as failure
            errors.append({"block": name, "error": f"{type(exc).__name__}: {exc}"})
    write_jsonl(folder / "rows.jsonl", rows)
    keys = [k for k, v in rows[0]["F"].items() if isinstance(v, bool) and k != "journal_sealed"] + ["brake_ledger_equal_z55"]
    failures = {}
    for k in keys:
        failures[k] = sum(1 for r in rows for arm in g.ARMS if k in r[arm] and r[arm][k] is False) + \
            sum(1 for r in rows if r.get(k) is False)
    arms = {}
    for arm in g.ARMS:
        part = [r[arm] for r in rows]
        arms[arm] = {"blocks": len(part), "ok": sum(p["status"] == "ok" for p in part),
                     "model_failures": sum(p["status"] != "ok" for p in part),
                     "calls": sum(p["calls"] for p in part),
                     "cost_usd": str(sum((Decimal(p["cost_usd"]) for p in part), Decimal(0))),
                     "messages": sum(p["messages"] for p in part),
                     "inactive_role_calls": sum(p["inactive_role_calls"] for p in part),
                     "removed_graph_edges_per_block": sorted({p["removed_graph_edges"] for p in part}),
                     "unsealed_journals": sum(not p["journal_sealed"] for p in part),
                     "failure_reasons": sorted({p["failure_reason"] for p in part if p["failure_reason"]})}
    summary = {"blocks": len(rows), "errors": errors, "replay_misses": misses, "failures_per_check": failures,
               "all_equal": not errors and misses == 0 and all(v == 0 for v in failures.values()),
               "arms": arms, "z55_replay_folder": str(z55_root), "sources": sources["files"],
               "network": netguard.report(), "seconds": round(time.time() - t0, 1), "smoke": SMOKE}
    write_json(folder / "SUMMARY.json", summary)
    print(canonical({k: v for k, v in summary.items() if k != "sources"}).decode())


if __name__ == "__main__":
    main()
