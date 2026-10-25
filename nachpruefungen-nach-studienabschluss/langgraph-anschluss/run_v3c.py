"""V3c cost per send attempt under failure scenarios: execution.execute vs LangGraph.

Part A, synthetic contract faults (no provider): AdapterError with known cost (paid failure) and
with unknown usage, F-01 model failure, technical stop, AdapterError under F-01.
Part B, the study sender (study_preparation.z53_fast.BlockSender, unchanged) on the Z53 substitute
transport (runs/Z53-SCHNELLFORTSETZUNG-001/fake_transport.py, unchanged; its uuid4 generation ids
are made deterministic by a per-path shim so both paths can be compared byte for byte).
Scenarios clean, faults (shared transport like one Z53 worker), flaky:N, systemic:N (fresh
transport per run). Every check compares the LangGraph path with the own path; costs are also
recomputed independently from the raw provider files.
"""
import common
from common import EVAL, OUT, SMOKE, Decimal, canonical, file_sha, netguard, tree_hashes, write_json, write_jsonl
import binding

import importlib.util
import shutil
import time
from types import SimpleNamespace
import zipfile

from communication_pruning.contracts import AdapterError
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, ModelFailure
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import decode_billing
from study_preparation import z53_fast as z

import backends
import lg_adapter as lg

FAKE_PATH = EVAL / "runs/Z53-SCHNELLFORTSETZUNG-001/fake_transport.py"
PATHS = (("own", execute), ("lg", lg.run))


class FaultAgent(backends.SyntheticAgent):
    """SyntheticAgent plus the outcome and Usage of every call (also of raised failures)."""

    def __call__(self, request):
        n = len(self.calls)
        try:
            response = super().__call__(request)
        except backends.Technical:
            self.calls[n]["outcome"] = {"kind": "technical", "usage": None}
            raise
        except AdapterError as error:
            self.calls[n]["outcome"] = {"kind": "adapter_error", "usage": error.usage.to_dict()}
            raise
        kind = "model_failed" if isinstance(response, ModelFailure) else "response"
        self.calls[n]["outcome"] = {"kind": kind, "usage": response.usage.to_dict()}
        return response


def attempt(runner, *args, **kwargs):
    try:
        return runner(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001 - recorded and compared
        return None, [type(exc).__name__, str(exc)]


def instrument(journal, config):
    try:
        report = read_journal(journal, config)
        return {"accepted": True, "sealed": report["sealed"], "metrics": report["audit"]}, report["trace"]
    except Exception as exc:  # noqa: BLE001
        return {"accepted": False, "error": [type(exc).__name__, str(exc)]}, None


def terminal_ids(trace):
    return {e["attempt_id"] for e in trace["events"] if e["kind"] in ("completed", "failed", "model_failed")}


# --------------------------------------------------------------------------- part A

def patterns(expected_calls, f01):
    mid, last = (expected_calls + 1) // 2, expected_calls
    if not f01:
        return {"paid_first": {1: "paid_fail"}, "unknown_first": {1: "unknown_fail"},
                "paid_mid_unknown_aggregator": {mid: "paid_fail", last: "unknown_fail"},
                "technical_2": {2: "technical"}}
    return {"model_failed_first": {1: "model_failed"}, "model_failed_mid": {mid: "model_failed"},
            "model_failed_aggregator": {last: "model_failed"}, "technical_2": {2: "technical"},
            "adapter_error_2": {2: "adapter_error"}}


def part_a(raw):
    rows = []
    contracts = (("schema1", False, 512), ("schema2", False, 1024), ("schema3-F01", True, 1024))
    for name, f01, limit in contracts:
        for config in common.configurations(with_dense=True):
            for rounds in (1, 2):
                expected = len(config.roles) * rounds + 1
                for pattern, faults in patterns(expected, f01).items():
                    for task in common.synthetic_tasks(12)[:2]:
                        run_id = f"z56v3c-a:{name}:{pattern}:{config.config_id}:{rounds}:{task.task_id}"
                        out = {}
                        for path_name, runner in PATHS:
                            agent = FaultAgent(f01=f01, producer_limit=limit, faults=faults)
                            journal = raw / "a" / path_name / name / pattern / f"{config.config_id}-r{rounds}-{task.task_id}.jsonl"
                            journal.parent.mkdir(parents=True, exist_ok=True)
                            trace, error = attempt(runner, task, config, agent, rounds=rounds, run_id=run_id,
                                                   journal_path=journal, producer_limit=limit,
                                                   failure_policy=F01 if f01 else None)
                            judged, read_trace = instrument(journal, config)
                            out[path_name] = {"trace": trace, "error": error, "calls": agent.calls,
                                              "journal": journal.read_bytes(), "instrument": judged,
                                              "read_trace": read_trace}
                        o, g = out["own"], out["lg"]
                        journaled = terminal_ids(g["read_trace"]) if g["read_trace"] else set()
                        known = sum((Decimal(c["outcome"]["usage"]["cost_usd"]) for c in g["calls"]
                                     if c["attempt_id"] in journaled and c["outcome"]["usage"]["cost_usd"] is not None), Decimal(0))
                        unknown = sum(1 for c in g["calls"] if c["attempt_id"] in journaled
                                      and c["outcome"]["usage"]["cost_usd"] is None)
                        paid_fail = [c for c in g["calls"] if c["outcome"]["kind"] in ("adapter_error", "model_failed")
                                     and c["outcome"]["usage"]["cost_usd"] is not None]
                        billed_not_journaled = [c["attempt_id"] for c in paid_fail if c["attempt_id"] not in journaled]
                        metrics = g["instrument"].get("metrics", {})
                        rows.append({
                            "contract": name, "pattern": pattern, "configuration": config.config_id, "rounds": rounds,
                            "task": task.task_id,
                            "error_equal": o["error"] == g["error"], "error": g["error"],
                            "trace_equal": o["trace"] == g["trace"],
                            "calls_equal": o["calls"] == g["calls"],
                            "journal_bytes_equal": o["journal"] == g["journal"],
                            "instrument_equal": o["instrument"] == g["instrument"],
                            "journal_accepted": g["instrument"]["accepted"], "sealed": g["instrument"].get("sealed"),
                            "status": None if g["trace"] is None else g["trace"]["status"],
                            "calls": len(g["calls"]), "known_cost_subtotal_usd": metrics.get("known_cost_subtotal_usd"),
                            "total_cost_usd": metrics.get("total_cost_usd"),
                            "unknown_cost_calls": metrics.get("unknown_cost_calls"),
                            "unresolved": metrics.get("unresolved_attempt_ids", []),
                            "known_matches_backend": metrics.get("known_cost_subtotal_usd") is not None
                            and Decimal(metrics["known_cost_subtotal_usd"]) == known,
                            "unknown_matches_backend": metrics.get("unknown_cost_calls") == unknown,
                            "unknown_stays_unknown": (metrics.get("total_cost_usd") is None) == (unknown > 0 or not g["instrument"].get("sealed")),
                            "paid_failures": len(paid_fail),
                            "paid_failures_in_cost": all(c["attempt_id"] in journaled for c in paid_fail if c["attempt_id"] not in billed_not_journaled),
                            "billed_not_journaled": billed_not_journaled,
                        })
    return rows


# --------------------------------------------------------------------------- part B

class UuidShim:
    """Deterministic stand-in for fake_transport's uuid4 (generation ids); one per path."""

    def __init__(self):
        self.n = 0

    def uuid4(self):
        self.n += 1
        return SimpleNamespace(hex=f"{self.n:032x}")


def load_fake():
    spec = importlib.util.spec_from_file_location("z56_fake_transport", FAKE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_costs(provider):
    """Independent recomputation from raw files: billed cost per attempt, unclear physical attempts.

    A physical attempt without received/response pair is a transport error (unknown billing);
    transport errors after the last answer leave no file and are taken from the call list."""
    costs, unknown, physical = {}, 0, 0
    events = ledger(provider)
    for b in sorted(provider.glob("*-binding.json")):
        rec = load(b)
        stem = b.name[:3]
        received = {int(r.name[len(stem) + 2:-len("-received.json")]): r for r in provider.glob(f"{stem}-p*-received.json")}
        top = max(received, default=0)
        missing = top - len(received)
        transport = sum(1 for e in events if e.get("call") == stem and e["kind"] == "transport_error")
        trailing = transport - missing
        assert missing >= 0 and trailing >= 0, "transport errors inconsistent with raw files"
        physical += top + trailing
        unknown += missing + trailing
        for number in sorted(received):
            meta = load(received[number])
            raw = (provider / received[number].name.replace("-received.json", "-response.json")).read_bytes()
            if meta["http_status"] != 200:
                continue
            try:
                usage, _ = decode_billing(raw)
            except Exception:  # noqa: BLE001 - undecodable billing stays unknown
                unknown += 1
                continue
            costs[rec["attempt_id"]] = costs.get(rec["attempt_id"], Decimal(0)) + usage.cost_usd
    return costs, unknown, physical


def load(path):
    import json
    return json.loads(path.read_bytes())


def ledger(provider):
    import json
    path = provider / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


SCENARIOS = (("clean", "shared"), ("faults", "shared"), ("flaky:1", "per-run"), ("flaky:3", "per-run"),
             ("systemic:2", "per-run"), ("systemic:5", "per-run"))


def part_b(raw):
    fake = load_fake()
    rows = []
    for spec, scope in SCENARIOS:
        shared = {p: (fake.make(spec, 0), UuidShim()) for p, _ in PATHS} if scope == "shared" else None
        for config in common.configurations(with_dense=True):
            for rounds in (1, 2):
                for task in common.synthetic_tasks(12)[:2]:
                    run_id = f"z56v3c-b:{spec}:{config.config_id}:{rounds}:{task.task_id}"
                    out = {}
                    for path_name, runner in PATHS:
                        transport, shim = shared[path_name] if shared else (fake.make(spec, 0), UuidShim())
                        fake.uuid = shim
                        folder = raw / "b" / path_name / spec.replace(":", "-") / f"{config.config_id}-r{rounds}-{task.task_id}"
                        sender = z.BlockSender(folder / "provider", transport, max_calls=len(config.roles) * rounds + 1,
                                               deadline=10 ** 12, sleep=lambda _s: None, clock=lambda: 0.0)
                        trace, error = attempt(runner, task, config, sender, rounds=rounds, run_id=run_id,
                                               journal_path=folder / "journal.jsonl", producer_limit=1024,
                                               failure_policy=F01)
                        judged, read_trace = instrument(folder / "journal.jsonl", config)
                        state = {"calls": sender.calls, "costs": {k: str(v) for k, v in sender.costs.items()},
                                 "unknown_attempts": sender.unknown_attempts, "rate_retries": sender.rate_retries,
                                 "technical_retries": sender.technical_retries, "generations": sender.generations,
                                 "terminal": sender.terminal}
                        out[path_name] = {"trace": trace, "error": error, "state": state, "folder": folder,
                                          "tree": tree_hashes(folder / "provider"),
                                          "journal": (folder / "journal.jsonl").read_bytes(),
                                          "instrument": judged, "read_trace": read_trace, "sender": sender}
                    o, g = out["own"], out["lg"]
                    costs, unknown, physical = raw_costs(g["folder"] / "provider")
                    sender = g["sender"]
                    journal_costs = {}
                    if g["read_trace"]:
                        for e in g["read_trace"]["events"]:
                            if e["kind"] in ("completed", "model_failed") and e["usage"]["cost_usd"] is not None:
                                journal_costs[e["attempt_id"]] = Decimal(e["usage"]["cost_usd"])
                    outcome = (g["error"][0] if g["error"] else g["trace"]["status"])
                    rows.append({
                        "scenario": spec, "transport_scope": scope, "configuration": config.config_id,
                        "rounds": rounds, "task": task.task_id, "outcome": outcome, "error": g["error"],
                        "error_equal": o["error"] == g["error"], "trace_equal": o["trace"] == g["trace"],
                        "sender_state_equal": o["state"] == g["state"],
                        "provider_files_equal": o["tree"] == g["tree"],
                        "journal_bytes_equal": o["journal"] == g["journal"],
                        "instrument_equal": o["instrument"] == g["instrument"],
                        "journal_accepted": g["instrument"]["accepted"], "sealed": g["instrument"].get("sealed"),
                        "calls": sender.calls, "physical_attempts": physical,
                        "known_cost_usd": str(sender.cost_for(run_id)), "unknown_attempts": sender.unknown_attempts,
                        "raw_costs_match_sender": {k: str(v) for k, v in costs.items()} == g["state"]["costs"],
                        "raw_unknown_match_sender": unknown == sender.unknown_attempts,
                        "journal_costs_match_raw": all(costs.get(k) == v for k, v in journal_costs.items()),
                        "paid_failures": {"terminal_arm": {k: str(sender.costs[k]) for k in sender.terminal},
                                          "model_failed": {k: str(v) for k, v in journal_costs.items()
                                                           if any(e["kind"] == "model_failed" and e["attempt_id"] == k
                                                                  for e in g["read_trace"]["events"])} if g["read_trace"] else {}},
                        "paid_failures_in_sender_cost": all(k in sender.costs for k in sender.terminal),
                        "rate_retries": sender.rate_retries, "technical_retries": sender.technical_retries,
                    })
    return rows


def zip_tree(root, target):
    names = sorted(p for p in root.rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in names:
            info = zipfile.ZipInfo(str(path.relative_to(root)), date_time=(2026, 10, 20, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return len(names)


def summarize(rows, keys):
    return {k: sum(1 for r in rows if r.get(k) is False) for k in keys}


def main():
    t0 = time.time()
    folder = OUT / "v3c"
    folder.mkdir(parents=True, exist_ok=False)
    sources = binding.bind(folder, "run_v3c.py")
    raw = folder / "raw"
    rows_a = part_a(raw)
    rows_b = part_b(raw)
    write_jsonl(folder / "rows-a.jsonl", rows_a)
    write_jsonl(folder / "rows-b.jsonl", rows_b)
    manifest = tree_hashes(raw)
    write_json(folder / "raw-manifest.json", manifest)
    files = zip_tree(raw, folder / "raw.zip")
    with zipfile.ZipFile(folder / "raw.zip") as archive:
        same = all(common.sha(archive.read(n)) == manifest[n] for n in archive.namelist()) and len(archive.namelist()) == len(manifest)
    if same:
        shutil.rmtree(raw)
    keys_a = ["error_equal", "trace_equal", "calls_equal", "journal_bytes_equal", "instrument_equal", "journal_accepted",
              "known_matches_backend", "unknown_matches_backend", "unknown_stays_unknown", "paid_failures_in_cost"]
    keys_b = ["error_equal", "trace_equal", "sender_state_equal", "provider_files_equal", "journal_bytes_equal",
              "instrument_equal", "journal_accepted", "raw_costs_match_sender", "raw_unknown_match_sender",
              "journal_costs_match_raw", "paid_failures_in_sender_cost"]
    outcomes_b = {}
    for r in rows_b:
        outcomes_b.setdefault(r["scenario"], {}).setdefault(r["outcome"], 0)
        outcomes_b[r["scenario"]][r["outcome"]] += 1
    summary = {
        "part_a": {"runs_per_path": len(rows_a), "failures_per_check": summarize(rows_a, keys_a),
                   "paid_failure_attempts": sum(r["paid_failures"] for r in rows_a),
                   "billed_but_not_journaled": sum(len(r["billed_not_journaled"]) for r in rows_a),
                   "runs_with_unknown_total": sum(1 for r in rows_a if r["total_cost_usd"] is None),
                   "outcomes": {o: sum(1 for r in rows_a if (r["error"][0] if r["error"] else r["status"]) == o)
                                for o in sorted({(r["error"][0] if r["error"] else r["status"]) for r in rows_a})}},
        "part_b": {"runs_per_path": len(rows_b), "failures_per_check": summarize(rows_b, keys_b),
                   "outcomes_by_scenario": outcomes_b,
                   "physical_attempts": sum(r["physical_attempts"] for r in rows_b),
                   "unknown_attempts": sum(r["unknown_attempts"] for r in rows_b),
                   "rate_retries": sum(r["rate_retries"] for r in rows_b),
                   "technical_retries": sum(r["technical_retries"] for r in rows_b),
                   "paid_terminal_arm_failures": sum(len(r["paid_failures"]["terminal_arm"]) for r in rows_b),
                   "paid_model_failures": sum(len(r["paid_failures"]["model_failed"]) for r in rows_b),
                   "known_cost_usd": str(sum((Decimal(r["known_cost_usd"]) for r in rows_b), Decimal(0)))},
        "raw_files": files, "raw_zip_sha256": file_sha(folder / "raw.zip"), "raw_zip_verified": same,
        "sources": sources["files"], "network": netguard.report(), "seconds": round(time.time() - t0, 1),
        "smoke": SMOKE,
    }
    summary["all_equal"] = (all(v == 0 for v in summary["part_a"]["failures_per_check"].values())
                            and all(v == 0 for v in summary["part_b"]["failures_per_check"].values()))
    write_json(folder / "SUMMARY.json", summary)
    print(canonical({k: v for k, v in summary.items() if k != "sources"}).decode())


if __name__ == "__main__":
    main()
