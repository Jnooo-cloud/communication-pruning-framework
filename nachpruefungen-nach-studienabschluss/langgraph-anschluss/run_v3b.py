"""V3b differential test: execution.execute vs LangGraph, same deterministic backend.

14 bank configurations (+ dense D as extra) x rounds 1/2 x 12 synthetic tasks x three
contracts (schema 1: 512 default; schema 2: 1024; schema 3: F-01 1024/128).
Compared per run: calls (role, round) in order, request bytes (dataclass and OpenRouter payload),
delivered messages, full trace, journal bytes, audit metrics (known/unknown cost).
"""
import common
from common import OUT, Decimal, canonical, file_sha, netguard, write_json, write_jsonl

import time

from communication_pruning.audit import audit
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01
from communication_pruning.journal import read_journal

import backends
import lg_adapter as lg

CONTRACTS = (("schema1", False, 512), ("schema2", False, 1024), ("schema3-F01", True, 1024))


def one(path_name, runner, task, config, rounds, contract, folder):
    name, f01, limit = contract
    agent = backends.SyntheticAgent(f01=f01, producer_limit=limit)
    run_id = f"z56v3b:{name}:{config.config_id}:{rounds}:{task.task_id}"
    journal = folder / path_name / name / f"{config.config_id}-r{rounds}-{task.task_id}.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    evidence = {} if runner is lg.run else None
    kwargs = dict(rounds=rounds, run_id=run_id, journal_path=journal, producer_limit=limit,
                  failure_policy=F01 if f01 else None)
    if evidence is not None:
        kwargs["evidence"] = evidence
    trace = runner(task, config, agent, **kwargs)
    return {"trace": trace, "calls": agent.calls, "billed": agent.billed, "journal": journal,
            "evidence": evidence}


def main():
    t0 = time.time()
    folder = OUT / "v3b"
    folder.mkdir(parents=True, exist_ok=False)
    tasks = common.synthetic_tasks(12)
    rows, calls_own, calls_lg = [], [], []
    for contract in CONTRACTS:
        for config in common.configurations(with_dense=True):
            for rounds in (1, 2):
                for task in tasks:
                    own = one("own", execute, task, config, rounds, contract, folder)
                    lgr = one("lg", lg.run, task, config, rounds, contract, folder)
                    seq_own = [(c["role"], c["round"]) for c in own["calls"]]
                    seq_lg = [(c["role"], c["round"]) for c in lgr["calls"]]
                    a_own, a_lg = audit(own["trace"], config), audit(lgr["trace"], config)
                    journal_report = read_journal(lgr["journal"], config)
                    known = sum((u.cost_usd for u in lgr["billed"] if u.cost_usd is not None), Decimal(0))
                    unknown = sum(u.cost_usd is None for u in lgr["billed"])
                    ev = lgr["evidence"]
                    expected_calls = len(config.roles) * rounds + 1
                    row = {
                        "contract": contract[0], "configuration": config.config_id, "rounds": rounds,
                        "task": task.task_id,
                        "calls_equal": seq_own == seq_lg,
                        "request_bytes_equal": [c["request_sha256"] for c in own["calls"]] == [c["request_sha256"] for c in lgr["calls"]]
                        and [c["request"] for c in own["calls"]] == [c["request"] for c in lgr["calls"]],
                        "payload_bytes_equal": [c["payload_sha256"] for c in own["calls"]] == [c["payload_sha256"] for c in lgr["calls"]],
                        "messages_equal": [c["messages"] for c in own["calls"]] == [c["messages"] for c in lgr["calls"]],
                        "trace_equal": own["trace"] == lgr["trace"],
                        "events_equal": own["trace"]["events"] == lgr["trace"]["events"],
                        "journal_bytes_equal": own["journal"].read_bytes() == lgr["journal"].read_bytes(),
                        "journal_sha256": file_sha(lgr["journal"]),
                        "audit_equal": a_own == a_lg,
                        "journal_accepted_sealed": journal_report["sealed"] and journal_report["trace"] == lgr["trace"],
                        "known_cost_equal": a_own["known_cost_subtotal_usd"] == a_lg["known_cost_subtotal_usd"],
                        "total_cost_equal": a_own["total_cost_usd"] == a_lg["total_cost_usd"],
                        "unknown_equal": a_own["unknown_cost_calls"] == a_lg["unknown_cost_calls"],
                        "backend_known_matches_audit": Decimal(a_lg["known_cost_subtotal_usd"]) == known,
                        "backend_unknown_matches_audit": a_lg["unknown_cost_calls"] == unknown,
                        "unknown_total_is_none": (a_lg["total_cost_usd"] is None) == (unknown > 0),
                        "call_count": a_lg["calls"], "expected_calls": expected_calls,
                        "count_rule_ok": a_lg["calls"] == expected_calls == len(seq_lg),
                        "inactive_role_calls": sum(1 for r, _ in seq_lg if r != "aggregator" and r not in config.roles),
                        "removed_graph_edges": ev["removed_edges"], "realized_graph_edges": len(ev["realized_edges"]),
                        "executed_equals_schedule": ev["executed"] == ev["schedule"],
                        "threads_note": "arrived order may differ (concurrent superstep)" if ev["arrived"] != ev["schedule"] else "",
                        "known_cost_usd": a_lg["known_cost_subtotal_usd"], "total_cost_usd": a_lg["total_cost_usd"],
                        "unknown_cost_calls": a_lg["unknown_cost_calls"],
                    }
                    rows.append(row)
                    tag = {"contract": contract[0], "configuration": config.config_id, "rounds": rounds,
                           "task": task.task_id}
                    calls_own.extend({**tag, **{k: v for k, v in c.items() if k != "request"}} for c in own["calls"])
                    calls_lg.extend({**tag, **{k: v for k, v in c.items() if k != "request"}} for c in lgr["calls"])
    checks = [k for k, v in rows[0].items() if isinstance(v, bool)]
    failures = {k: sum(1 for r in rows if not r[k]) for k in checks}
    bank_rows = [r for r in rows if r["configuration"] != "D"]
    summary = {
        "runs_per_path": len(rows), "bank_runs_per_path": len(bank_rows),
        "configurations": sorted({r["configuration"] for r in rows}), "rounds": [1, 2], "tasks": len(tasks),
        "contracts": [c[0] for c in CONTRACTS], "checks": checks, "failures_per_check": failures,
        "all_equal": all(v == 0 for v in failures.values()),
        "calls_per_path": sum(r["call_count"] for r in rows),
        "runs_with_unknown_cost": sum(1 for r in rows if r["unknown_cost_calls"]),
        "runs_with_concurrent_arrival_order": sum(1 for r in rows if r["threads_note"]),
        "removed_edges_by_configuration_rounds2": {r["configuration"]: r["removed_graph_edges"] for r in rows if r["rounds"] == 2},
        "network": netguard.report(), "seconds": round(time.time() - t0, 1),
    }
    write_jsonl(folder / "rows.jsonl", rows)
    write_jsonl(folder / "calls-own.jsonl", calls_own)
    write_jsonl(folder / "calls-lg.jsonl", calls_lg)
    write_json(folder / "SUMMARY.json", summary)
    print(canonical({k: summary[k] for k in ("runs_per_path", "all_equal", "failures_per_check", "calls_per_path",
                                              "runs_with_unknown_cost", "runs_with_concurrent_arrival_order",
                                              "network", "seconds")}).decode())


if __name__ == "__main__":
    main()
