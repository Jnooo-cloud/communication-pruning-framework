"""Z55 coordinator: GPTSwarm demonstration on 100 R blocks (D-082, plan project/dsr/Z55-GPTSWARM-DEMO-PLAN.md).

  prepare                         zero-call: hash binding of the 100 Z53 source blocks
  replay  --folder SCRATCH        zero-call: full run against recorded Z53 answers (byte parity dry run)
  run --phase smoke               5 blocks, then only after SMOKE-RESULT passed:
  run --phase full                remaining blocks up to 100 (one-shot phases; ABORTED.json blocks reruns)
  verify | analyze | status       [--folder DIR]

Sequential, one process. Cost brake (D-082): before every physical attempt
known cost + 0.14 per unclear attempt + 0.14 for this attempt <= cap <= 1.00.
The OpenRouter key is read from the macOS keychain at run time only.
Old Z31/Z52/Z53/Z54 data are read only (guard_write).
"""
import argparse
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
EVAL = HERE.parents[1]
Z31 = EVAL / "runs/Z31-PRUNING-001"
ORIGINAL = Z31 / "original"
for extra in (str(Z31 / "runtime"), str(ORIGINAL), str(EVAL)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from communication_pruning import gptswarm_musique_demo as g  # noqa: E402
from communication_pruning.openrouter import ProbeStop, Transport, encoded, decode_billing  # noqa: E402
from study_preparation import z53_fast as z  # noqa: E402

Z52 = EVAL / "runs/Z52-NEBENPANEL-ANSCHLUSS-001"
Z53 = EVAL / "runs/Z53-SCHNELLFORTSETZUNG-001"
Z54 = EVAL / "runs/Z54-SK-KORREKTUR-001"
Z53_BLOCKS = Z53 / "live/blocks"
LOCK = EVAL / "runs/final-study-control/final-study-v1.lock"
OLD_HASHES = HERE / "OLD-HASHES.json"
BLOCKS = [f"R-{i:05d}" for i in range(2183, 2283)]   # D-082: R-02183 .. R-02282, plan order
SMOKE_BLOCKS = 5
DEADLINE = 1791147389.191509                         # 04.10.2026 22:56:29 MESZ (D-066 frame, D-082)
MIN_ACCOUNT_USD = Decimal("1.50")
MIN_FREE_BYTES = 2 * 1024 ** 3
MAX_ATTEMPTS = 3


def now():
    return time.time()


def sha(path):
    return z.file_sha(path)


def log(folder, event):
    z.append_jsonl(folder / "events.jsonl", {"t": now(), **event})


def guard_write(path):
    resolved = Path(path).resolve()
    for old in (Z31, Z52, Z53, Z54):
        z.need(resolved != old.resolve() and old.resolve() not in resolved.parents,
               f"write target inside old run tree: {resolved}")
    return Path(path)


def check_original():
    manifest = json.loads((Z31 / "original-manifest.json").read_bytes())
    z.need(manifest["commit"] == g.COMMIT, "original commit")
    for name, meta in manifest["files"].items():
        z.need(sha(ORIGINAL / name) == meta["sha256"], f"GPTSwarm original changed: {name}")
    return sha(Z31 / "original-manifest.json")


def check_native_sources(folder):
    """Every selection.json names native sources inside the pinned original with unchanged bytes."""
    for selection in Path(folder).glob("blocks/*/*/selection.json"):
        data = json.loads(selection.read_bytes())
        for name, entry in data["native_sources"].items():
            source = Path(entry["path"]).resolve()
            z.need(source.is_relative_to(ORIGINAL.resolve()) and sha(source) == entry["sha256"],
                   f"native source outside pinned original or changed: {name}")


def block_hashes():
    out = {}
    for name in BLOCKS:
        d = Z53_BLOCKS / name
        z.need(d.is_dir(), f"Z53 block missing: {name}")
        files = sorted(p for p in d.rglob("*") if p.is_file())
        out[name] = z.sha256(encoded({str(p.relative_to(d)): sha(p) for p in files})).hexdigest()
    return out


def prepare(args):
    if OLD_HASHES.exists():
        raise SystemExit("OLD-HASHES.json exists (create-only)")
    z.write_json(OLD_HASHES, {"blocks": block_hashes(), "z53_root": str(Z53_BLOCKS)})
    print(json.dumps({"blocks": len(BLOCKS), "sha256": sha(OLD_HASHES)}))


def old_hashes_unchanged():
    return json.loads(OLD_HASHES.read_bytes())["blocks"] == block_hashes()


def input_binding(cap):
    return {"module_sha256": sha(g.__file__), "runner_sha256": sha(__file__), "z53_fast_sha256": sha(z.__file__),
            "openrouter_sha256": sha(EVAL / "communication_pruning/openrouter.py"),
            "original_manifest_sha256": check_original(), "old_hashes_sha256": sha(OLD_HASHES),
            "blocks": BLOCKS, "cost_cap_usd": str(cap), "deadline_epoch": DEADLINE, "authority": "D-082"}


# --------------------------------------------------------------------------- credentials and account

def keychain_key():
    raw = subprocess.run(["security", "find-generic-password", "-a", os.environ["USER"], "-s",
                          "OPENROUTER_API_KEY", "-w"], capture_output=True, text=True, check=True).stdout.strip()
    z.need(raw and not any(c.isspace() for c in raw) and "$" not in raw and "`" not in raw,
           "invalid keychain credential")
    return raw


def account(key):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no proxy sees the credential
    out = {}
    for endpoint in ("credits", "key"):
        request = urllib.request.Request("https://openrouter.ai/api/v1/" + endpoint,
                                         headers={"Authorization": "Bearer " + key})
        with opener.open(request, timeout=30) as response:
            out[endpoint] = json.load(response)["data"]
    remaining = Decimal(str(out["credits"]["total_credits"])) - Decimal(str(out["credits"]["total_usage"]))
    return {"account_remaining_usd": str(remaining), "key_usage_usd": str(out["key"]["usage"])}


# --------------------------------------------------------------------------- ledgers

def ledger(directory):
    """Known cost, unclear attempts and generation ids of one attempt directory from its durable
    brake ledger (every physical attempt incl. 429/5xx/error bodies, written before the sender reacts)."""
    known, unknown, generations = Decimal(0), 0, []
    path = Path(directory) / "brake.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            e = json.loads(line)
            if e["billing"] == "provider":
                known += Decimal(e["cost_usd"])
                generations.append(e["generation_id"])
            elif e["billing"] == "unknown":
                unknown += 1
    return known, unknown, generations


def known_generations():
    """Z52 inspect state, every Z53 and Z54 attempt ledger and block summary."""
    seen = set(z.load(z.PRIOR_INSPECT)["state"]["generation_ids"])
    for root in (Z53 / "live", Z54 / "live"):
        for sub in ("blocks", "interrupted", "inflight"):
            for d in (root / sub).glob("*"):
                for path in d.glob("provider*/calls.jsonl"):
                    for line in path.read_text().splitlines():
                        e = json.loads(line)
                        if "generation_id" in e:
                            seen.add(e["generation_id"])
                if (d / "complete.json").exists():
                    summary = z.load(d / "complete.json").get("summary", {})
                    seen.update(summary.get("generations", []))
    return seen


def scan(folder):
    done, interrupted, accounts = {}, {}, {}
    for d in (folder / "blocks").iterdir():
        done[d.name] = d
        accounts[str(d)] = ledger(d)
    for d in (folder / "interrupted").iterdir():
        name, attempt = d.name.rsplit(".a", 1)
        interrupted.setdefault(name, []).append((int(attempt), d))
        accounts[str(d)] = ledger(d)
    return done, interrupted, accounts


def totals(accounts):
    return sum((a[0] for a in accounts.values()), Decimal(0)), sum(a[1] for a in accounts.values())


# --------------------------------------------------------------------------- replay (zero calls)

class Replay:
    """Answers each request with the recorded Z53 answer of the same arm and call (no network)."""

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


def replay(args):
    folder = guard_write(Path(args.folder))
    z.need(folder.resolve() != (HERE / "live").resolve(), "replay never into the canonical folder")
    check_original()
    folder.mkdir(parents=True, exist_ok=False)
    report = []
    for name in BLOCKS[:args.limit or None]:
        block = Z53_BLOCKS / name
        transport = Replay(block)
        brake = g.CostBrake()
        try:
            g.run_block(block, folder / name, transport, deadline=now() + 10 ** 6, brake=brake,
                        sleep=lambda _: None)
            g.verify_block(folder / name, block)
            par = g.parity(folder / name, block)
            report.append({"block": name, "misses": transport.misses,
                           **{arm: {"round1": par[arm]["round1_identical"],
                                    "requests": par[arm]["all_requests_identical"],
                                    "answers": par[arm]["all_answers_identical"],
                                    "em_equal": par[arm]["demo"]["em"] == par[arm]["z53"]["em"],
                                    "f1_equal": par[arm]["demo"]["f1"] == par[arm]["z53"]["f1"],
                                    "cost_equal": Decimal(par[arm]["demo"]["cost_usd"]) == Decimal(par[arm]["z53"]["cost_usd"]),
                                    "status": par[arm]["demo"]["status"]} for arm in g.ARMS}})
        except Exception as error:
            report.append({"block": name, "misses": transport.misses, "error": f"{type(error).__name__}: {error}"})
    ok = [r for r in report if "error" not in r and all(all(r[a][k] for k in ("round1", "requests", "answers", "em_equal",
                                                                               "f1_equal", "cost_equal")) for a in g.ARMS)]
    out = {"blocks": len(report), "fully_identical": len(ok), "errors": [r for r in report if "error" in r],
           "not_identical": [r for r in report if r not in ok and "error" not in r], "network_calls": 0}
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in out.items()}))
    if args.record:
        z.write_json(guard_write(HERE / f"REPLAY-{args.record}.json"), out | {"folder": str(folder)})


# --------------------------------------------------------------------------- run

def run(args):
    folder = guard_write(Path(args.folder))
    live = folder.resolve() == (HERE / "live").resolve()
    z.need(live or args.fake is not None, "real runs only into the canonical folder")
    z.need(not live or args.fake is None, "synthetic runs never into the canonical folder")
    cap = Decimal(args.cost_cap)
    z.need(Decimal(0) < cap <= g.HARD_CAP, "cost cap above D-082 limit")
    for sub in ("blocks", "inflight", "interrupted"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    lock_handle = open(LOCK if live else folder / "fake.lock", "a")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another study writer holds the study lock")
    if (folder / "ABORTED.json").exists():
        raise SystemExit("run was aborted earlier; a new run needs a new author decision")
    blocks = BLOCKS[:args.blocks] if args.blocks else BLOCKS
    if args.phase == "smoke":
        z.need(not any((folder / "blocks").iterdir()) and not any((folder / "interrupted").iterdir()),
               "smoke needs an empty folder")
        queue = blocks[:SMOKE_BLOCKS]
    else:
        smoke = folder / "SMOKE-RESULT.json"
        z.need(smoke.exists() and z.load(smoke)["passed"] is True, "full run only after a passed smoke")
        z.need(not (folder / "FULL-STARTED.json").exists(), "full phase already started once")
        queue = blocks[SMOKE_BLOCKS:]
    binding = input_binding(cap)
    path = folder / "INPUT-BINDING.json"
    if path.exists():
        z.need(z.load(path) == binding, "inputs changed since first start")
    else:
        z.write_json(path, binding)
    z.need(old_hashes_unchanged(), "Z53 source blocks changed")
    deadline = DEADLINE if live else now() + 10 ** 6
    z.need(now() <= deadline - 600, "calendar: less than 10 min to the bound end")
    acct_before = None
    if live:
        key = keychain_key()
        acct_before = account(key)
        z.need(Decimal(acct_before["account_remaining_usd"]) >= MIN_ACCOUNT_USD,
               f"account below {MIN_ACCOUNT_USD} USD")
        transport = Transport(key)
        del key
    else:
        sys.path.insert(0, str(Z53))
        import fake_transport
        transport = fake_transport.make(args.fake, 0)
    z.write_json(folder / f"{args.phase.upper()}-STARTED.json", {"t": now(), "queue": queue, "cap": str(cap),
                                                                 "account_before": acct_before})
    for d in list((folder / "inflight").iterdir()):
        os.rename(d, folder / "interrupted" / d.name)
    done, interrupted, accounts = scan(folder)
    spent, unknown = totals(accounts)
    generations = known_generations() if live else set()
    for _, _, gens in accounts.values():
        z.need(not set(gens) & generations and len(gens) == len(set(gens)), "duplicate generation on disk")
        generations.update(gens)
    # the brake books every new attempt and stops on a duplicate generation before the next transport
    brake = g.CostBrake(cap, spent, unknown, generations)
    queue = [n for n in queue if n not in done]
    log(folder, {"kind": "start", "phase": args.phase, "queue": len(queue), "spent": str(spent),
                 "unknown": unknown, "cap": str(cap), "fake": args.fake, "account": acct_before})
    stop = {"flag": False}

    def on_signal(*_):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    stop_reason, completed, t_start = None, 0, now()
    while queue:
        if (folder / "STOP").exists():
            stop_reason = "STOP file"
            break
        if stop["flag"]:
            stop_reason = "signal"
            break
        if now() > deadline - 600:
            stop_reason = "calendar: no new block within 10 min of end"
            break
        if shutil.disk_usage(folder).free < MIN_FREE_BYTES:
            stop_reason = "disk below 2 GB"
            break
        if not brake.admit():
            stop_reason = "cost cap reached"
            break
        name = queue[0]
        attempts = sorted(interrupted.get(name, []))
        if len(attempts) >= MAX_ATTEMPTS:
            stop_reason = f"{name}: {MAX_ATTEMPTS} interrupted attempts"
            break
        attempt = len(attempts) + 1
        tmp = folder / "inflight" / f"{name}.a{attempt}"
        started = now()
        try:
            g.run_block(Z53_BLOCKS / name, tmp, transport, deadline=deadline, brake=brake,
                        stop=lambda: stop["flag"], sleep=time.sleep if live else (lambda _: None))
            g.verify_block(tmp, Z53_BLOCKS / name)
            final = folder / "blocks" / name
            os.rename(tmp, final)
            queue.pop(0)
            completed += 1
            proof = z.load(final / "complete.json")
            log(folder, {"kind": "complete", "block": name, "attempt": attempt, "seconds": round(now() - started, 1),
                         **{arm: {k: proof["results"][arm][k] for k in ("status", "em", "f1", "cost_usd", "call_count")}
                            for arm in g.ARMS}, "brake_known": str(brake.known), "brake_unknown": brake.unknown})
        except z.TechnicalAbort as error:
            dest = folder / "interrupted" / f"{name}.a{attempt}"
            if tmp.exists():
                os.rename(tmp, dest)
                interrupted.setdefault(name, []).append((attempt, dest))
            log(folder, {"kind": "interrupted", "block": name, "attempt": attempt, "error": str(error)})
        except BaseException as error:
            dest = folder / "interrupted" / f"{name}.a{attempt}"
            if tmp.exists():
                os.rename(tmp, dest)
            stop_reason = f"{type(error).__name__}: {error}"
            import traceback
            log(folder, {"kind": "stop", "block": name, "attempt": attempt, "error": stop_reason,
                         "trace": traceback.format_exc()[-3000:]})
            break
        z.need(brake.known <= cap, "cost above cap")
        z.need(totals({k: ledger(Path(k)) for k in [str(d) for d in (folder / "blocks").iterdir()]
                       + [str(d) for d in (folder / "interrupted").iterdir()]}) == (brake.known, brake.unknown),
               "durable brake ledgers differ from the in-memory brake")
        progress = {"updated": now(), "phase": args.phase, "complete_this_run": completed, "queue_left": len(queue),
                    "brake_known_usd": str(brake.known), "brake_unknown": brake.unknown, "cap_usd": str(cap),
                    "hours_to_deadline": round((deadline - now()) / 3600, 2), "minutes_running": round((now() - t_start) / 60, 1)}
        tmpfile = folder / "progress.json.tmp"
        tmpfile.write_bytes(encoded(progress))
        os.replace(tmpfile, folder / "progress.json")
    done, _, accounts = scan(folder)
    spent, unknown = totals(accounts)
    acct_after = account(keychain_key()) if live else None
    end = {"kind": "end", "phase": args.phase, "stop_reason": stop_reason, "complete_this_run": completed,
           "blocks_done": len(done), "spent": str(spent), "unknown": unknown, "account_after": acct_after}
    log(folder, end)
    if stop_reason is not None:
        z.write_json(folder / "ABORTED.json", end)
    elif args.phase == "smoke":
        z.write_json(folder / "SMOKE-RESULT.json", smoke_result(folder, done) | {"spent_usd": str(spent),
                     "unknown_attempts": unknown})
    print(json.dumps(end))


def smoke_result(folder, done):
    """K4: five blocks, round-1 bytes identical to Z53 for both arms, successful arms with 5/9 calls."""
    rows = []
    for name in sorted(done):
        report = g.verify_block(folder / "blocks" / name, Z53_BLOCKS / name)
        par = g.parity(folder / "blocks" / name, Z53_BLOCKS / name)
        rows.append({"block": name, "round1": all(par[a]["round1_identical"] for a in g.ARMS),
                     "calls": {a: report[a]["calls"] for a in g.ARMS},
                     "shape_ok": all(report[a]["status"] != "ok" or report[a]["calls"] == g.EXPECTED_CALLS[a]
                                     for a in g.ARMS)})
    return {"blocks": len(rows), "rows": rows,
            "passed": len(rows) == SMOKE_BLOCKS and all(r["round1"] and r["shape_ok"] for r in rows)}


# --------------------------------------------------------------------------- after the run

def verify(args):
    folder = guard_write(Path(args.folder))
    check_original()
    check_native_sources(folder)
    failures, verified = [], 0
    for d in sorted((folder / "blocks").iterdir()):
        try:
            g.verify_block(d, Z53_BLOCKS / d.name)
            verified += 1
        except Exception as error:
            failures.append({"block": d.name, "error": f"{type(error).__name__}: {error}"})
    digest = z.sha256(encoded([(d.name, sha(d / "complete.json")) for d in sorted((folder / "blocks").iterdir())])).hexdigest()
    out = {"verified": verified, "failures": failures, "blocks_digest": digest, "old_hashes_unchanged": old_hashes_unchanged(),
           "epoch": now()}
    print(json.dumps(out, indent=1))
    n = len(list(folder.glob("VERIFY-*.json"))) + 1
    z.write_json(folder / f"VERIFY-{n:03d}.json", out)
    if failures or not out["old_hashes_unchanged"]:
        raise SystemExit(1)


def analyze(args):
    folder = guard_write(Path(args.folder))
    blocks = sorted((folder / "blocks").iterdir())
    per = []
    for d in blocks:
        report = g.verify_block(d, Z53_BLOCKS / d.name)
        par = g.parity(d, Z53_BLOCKS / d.name)
        per.append({"block": d.name, "verify": report, "parity": par})

    def mean(values):
        values = list(values)
        return sum(values) / len(values) if values else None
    arms = {}
    for arm in g.ARMS:
        rows = [p["parity"][arm] for p in per]
        calls = [c for r in rows for c in r["calls"]]
        r1 = [c for c in calls if c["call"].startswith("1:") and c["demo_sent"] and c["z53_sent"]]
        both = [c for c in calls if c["demo_sent"] and c["z53_sent"]]
        arms[arm] = {
            "blocks": len(rows),
            "demo_em": mean(r["demo"]["em"] for r in rows), "z53_em": mean(r["z53"]["em"] for r in rows),
            "demo_f1": mean(r["demo"]["f1"] for r in rows), "z53_f1": mean(r["z53"]["f1"] for r in rows),
            "demo_cost_usd": str(sum((Decimal(r["demo"]["cost_usd"]) for r in rows), Decimal(0))),
            "z53_cost_usd": str(sum((Decimal(r["z53"]["cost_usd"]) for r in rows), Decimal(0))),
            "demo_model_failures": sum(r["demo"]["status"] != "ok" for r in rows),
            "z53_model_failures": sum(r["z53"]["status"] != "ok" for r in rows),
            "em_equal_blocks": sum(r["demo"]["em"] == r["z53"]["em"] for r in rows),
            "f1_equal_blocks": sum(r["demo"]["f1"] == r["z53"]["f1"] for r in rows),
            "round1_requests": len(r1), "round1_identical": sum(c["request_identical"] for c in r1),
            "requests_compared": len(both), "requests_identical": sum(c["request_identical"] for c in both),
            "answers_identical": sum(c["answer_identical"] for c in both),
            "demo_only_calls": sum(c["demo_sent"] and not c["z53_sent"] for c in calls),
            "z53_only_calls": sum(c["z53_sent"] and not c["demo_sent"] for c in calls),
            "blocks_all_requests_identical": sum(r["all_requests_identical"] for r in rows),
            "blocks_all_answers_identical": sum(r["all_answers_identical"] for r in rows),
            "first_divergence_by_call": {},
            "calls_executed": sum(p["verify"][arm]["calls"] for p in per),
            "billed_calls": sum(p["verify"][arm]["billed_calls"] for p in per),
            "unknown_attempts": sum(p["verify"][arm]["unknown_attempts"] for p in per),
            "messages_checked": sum(p["verify"][arm]["messages_checked"] for p in per),
            "not_entered_node_sets": sorted({tuple(p["verify"][arm]["not_entered"]) for p in per}),
            "removed_edges_per_block": sorted({p["verify"][arm]["removed_edges"] for p in per})}
        for r in rows:
            if r["first_divergence"]:
                key = r["first_divergence"]["call"]
                arms[arm]["first_divergence_by_call"][key] = arms[arm]["first_divergence_by_call"].get(key, 0) + 1
    interrupted = []
    for d in sorted((folder / "interrupted").iterdir()):
        known, unclear, _ = ledger(d)
        interrupted.append({"attempt": d.name, "known_cost_usd": str(known), "unknown_attempts": unclear})
    block_known, block_unknown = totals({str(d): ledger(d) for d in blocks})
    costs = {"completed_blocks_known_usd": str(block_known), "completed_blocks_unknown_attempts": block_unknown,
             "interrupted_attempts": interrupted,
             "interrupted_known_usd": str(sum((Decimal(i["known_cost_usd"]) for i in interrupted), Decimal(0))),
             "interrupted_unknown_attempts": sum(i["unknown_attempts"] for i in interrupted)}
    costs["total_known_usd"] = str(block_known + Decimal(costs["interrupted_known_usd"]))
    costs["total_unknown_attempts"] = block_unknown + costs["interrupted_unknown_attempts"]
    costs["note"] = "unknown attempts are reported, never valued at 0 or at the reserve"
    out = {"blocks": len(per), "arms": arms, "costs": costs, "old_hashes_unchanged": old_hashes_unchanged(),
           "per_block": [{"block": p["block"], **{arm: {"demo": p["parity"][arm]["demo"], "z53": p["parity"][arm]["z53"],
                                                       "round1": p["parity"][arm]["round1_identical"],
                                                       "requests": p["parity"][arm]["all_requests_identical"],
                                                       "answers": p["parity"][arm]["all_answers_identical"],
                                                       "first_divergence": p["parity"][arm]["first_divergence"]}
                                                  for arm in g.ARMS}} for p in per]}
    target = guard_write(HERE / f"ANALYSIS-{args.record}.json") if args.record else None
    if target:
        z.write_json(target, out)
    print(json.dumps({"blocks": out["blocks"], "costs": costs, "arms": {a: {k: v for k, v in arms[a].items() if k != "not_entered_node_sets"}
                                                         for a in arms}, "old_hashes_unchanged": out["old_hashes_unchanged"]},
                     indent=1, default=str))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "replay", "run", "verify", "analyze", "status"))
    parser.add_argument("--folder", default=str(HERE / "live"))
    parser.add_argument("--phase", choices=("smoke", "full"), default=None)
    parser.add_argument("--cost-cap", default="1.00")
    parser.add_argument("--fake", default=None)
    parser.add_argument("--blocks", type=int, default=0, help="synthetic tests only: fewer blocks")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--record", default=None)
    args = parser.parse_args()
    if args.blocks and args.fake is None:
        raise SystemExit("--blocks only for synthetic runs")
    if args.command == "status":
        p = Path(args.folder) / "progress.json"
        print(p.read_text() if p.exists() else "no progress")
        return
    if args.command == "run":
        z.need(args.phase is not None, "run needs --phase smoke|full")
    {"prepare": prepare, "replay": replay, "run": run, "verify": verify, "analyze": analyze}[args.command](args)


if __name__ == "__main__":
    main()
