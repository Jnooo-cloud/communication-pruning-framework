"""Z54 S-k correction in panel R (plan: project/dsr/Z54-SK-KORREKTUR-PLAN.md, D-081).

Only the S-k arm is re-collected. Its request bytes are the frozen base payload
(communication_pruning.openrouter.payload, temperature 0) plus exactly
temperature 1.0 and top_p 0.9 (Choi et al. 2025, S166). Everything else is the
unchanged Z53 shell: BlockSender retry/stop rules (inherited), Context/loader,
final_execution._direct (plurality, PCG64 tie seed), _row, F-01 decoding.
No CANDIDATE-bound source is modified; z53_fast.BlockSender only exposes the
request-byte construction as an overridable method whose default is unchanged.
"""
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time
import traceback

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from communication_pruning.contracts import TaskInput  # noqa: E402
from communication_pruning.data import AnswerReference  # noqa: E402
from communication_pruning.failure_policy import F01, decode_outcome, strict_json  # noqa: E402
from communication_pruning.openrouter import ProbeStop, decode_billing, encoded, payload  # noqa: E402
from study_preparation import final_execution as nx  # noqa: E402
from study_preparation import final_preflight as gate  # noqa: E402
from study_preparation import z53_fast as z  # noqa: E402

ARM = "S-k"
SK_SAMPLING = {"temperature": 1.0, "top_p": 0.9}  # Choi et al. 2025, S166 volltext.md:780
MAX_CALLS = 5
RESERVE = Decimal("0.14")
# Worst case of one block attempt: each of 5 logical calls at most 1 billed answer (<= 0.14 by
# max_price/RESERVE) plus 1 unclear transport attempt; a 2nd unclear attempt aborts the block.
# => <= 10 units of 0.14 = 1.40 USD per running block, fixed before dispatch (no in-flight overrun).
BLOCK_RESERVE = 2 * MAX_CALLS * RESERVE  # 1.40 USD per running block
HARD_CAP = Decimal("5.00")               # D-081
RUNNER = "Z54-SK-KORREKTUR-001"
RUN = EVAL / "runs" / RUNNER
need = z.need


# --------------------------------------------------------------------------- payload

def sk_body(request):
    """Frozen base payload + exactly the two sampling fields; only for the S-k direct request."""
    need(request.role == "single" and request.instruction == gate.DIRECT_INSTRUCTION
         and request.messages == () and request.round == 1 and request.max_output_tokens == 1024
         and f":{ARM}:S:" in request.attempt_id, "S-k sampling requested for a non-S-k request")
    base = payload(request, producer_limit=1024)
    need(base.get("temperature") == 0 and "top_p" not in base, "frozen base payload changed")
    return encoded({**base, **SK_SAMPLING})


class SkSender(z.BlockSender):
    """Z53 BlockSender (same retry/stop rules); only the request bytes differ."""

    def _body(self, request):
        return sk_body(request)


def cap_ok(spent, unknown, running, cap=HARD_CAP):
    """Start one more block only if the worst case of all open blocks stays within the cap."""
    cap = Decimal(cap)
    need(Decimal(0) < cap <= HARD_CAP, "cost cap above D-081 limit")
    return Decimal(spent) + unknown * RESERVE + (running + 1) * BLOCK_RESERVE <= cap


def sk_slot(block):
    slots = [s for s in block["slots"] if s["arm"] == ARM]
    need(len(slots) == 1, "block has no unique S-k slot")
    return slots[0]


# --------------------------------------------------------------------------- run

def run_sk_block(ctx, block, directory, transport, *, deadline, stop=None, sleep=time.sleep, clock=time.time):
    candidate, plan = ctx.candidate, ctx.plan
    need(block["panel"] == "R", "Z54 covers panel R only")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    z.write_json(directory / "started.json", {"block": block, "plan_hash": plan["plan_hash"],
                                              "arm": ARM, "runner": RUNNER, "sampling": SK_SAMPLING})
    task, reference = ctx.loader(block["task_id"])
    need(type(task) is TaskInput and type(reference) is AnswerReference
         and task.task_id == nx.public_task_id(plan, block["task_id"]) == reference.task_id, "loader identity")
    z.write_json(directory / "public.json", asdict(task))
    z.write_json(directory / "reference.json", asdict(reference))
    slot = sk_slot(block)
    sender = SkSender(directory / "provider", transport, max_calls=MAX_CALLS,
                      deadline=deadline, stop=stop, sleep=sleep, clock=clock)
    sd = directory / ARM
    sd.mkdir()
    run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
    config, rounds, failed = nx._configuration(candidate, block, ARM, None)
    need(config is None, "S-k must be a direct arm")
    try:
        result = nx._direct(task, reference, run_id, ARM, block["tie_break_seed"], sd, sender)
        row = nx._row(candidate, block, slot, result, config, rounds, failed, run_id)
        need(row["call_count"] == sender.calls_for(run_id) and Decimal(row["cost_usd"]) == sender.cost_for(run_id),
             "arm calls/costs differ from billed sender records")
    except z.TerminalArmFailure as failure:
        need(failure.attempt_id.startswith(run_id + ":"), "terminal failure of a foreign arm")
        row = z._failure_row(ctx, block, slot, config, rounds, failed, run_id, sender, failure.reason)
        z.write_json(sd / "terminal-failure.json", {"attempt_id": failure.attempt_id, "reason": failure.reason,
                     "rule": "Z53-1" if failure.reason == z.OVERLIMIT_REASON else "Z53-3"})
    z.write_json(sd / "result.json", row)
    evidence = {str(p.relative_to(directory)): z.file_sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
    summary = {"calls": sender.calls, "known_cost_usd": str(sum(sender.costs.values(), Decimal(0))),
               "unknown_attempts": sender.unknown_attempts, "rate_retries": sender.rate_retries,
               "technical_retries": sender.technical_retries, "generations": sender.generations,
               "terminal_failures": sender.terminal}
    z.write_json(directory / "complete.json", {"block": block, "plan_hash": plan["plan_hash"], "rows": [row],
                                               "evidence": evidence, "summary": summary, "runner": RUNNER,
                                               "sampling": SK_SAMPLING})
    return [row], summary


# --------------------------------------------------------------------------- verification

def verify_sk_block(ctx, directory, old=None):
    """Recompute a Z54 block from its files; optionally prove input identity with the old S-k block."""
    candidate, plan = ctx.candidate, ctx.plan
    directory = Path(directory)
    proof = z.load(directory / "complete.json")
    block = proof["block"]
    need(z.load(directory / "started.json") == {"block": block, "plan_hash": plan["plan_hash"], "arm": ARM,
                                                "runner": RUNNER, "sampling": SK_SAMPLING}
         and block == ctx.block("R", block["draw_index"]) and proof["sampling"] == SK_SAMPLING
         and proof["runner"] == RUNNER, "block identity")
    on_disk = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()} - {"complete.json"}
    need(set(proof["evidence"]) == on_disk, "unlisted or missing evidence files")
    for name, checksum in proof["evidence"].items():
        need(z.file_sha(directory / name) == checksum, f"evidence changed: {name}")
    public = z.load(directory / "public.json")
    task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
    private = z.load(directory / "reference.json")
    reference = AnswerReference(private["task_id"], tuple(private["answers"]))
    need(task.task_id == nx.public_task_id(plan, block["task_id"]) == reference.task_id, "task identity")
    pdir = directory / "provider"
    need(sorted(p.name for p in directory.iterdir() if p.is_dir()) == ["S-k", "provider"], "unexpected directories")
    requests, answers, generations = {}, {}, []
    for b in sorted(pdir.glob("*-binding.json")):
        rec = z.load(b)
        stem = b.name[:3]
        body = (pdir / f"{stem}-request.json").read_bytes()
        need(rec["request_sha256"] == z.sha256(body).hexdigest(), "request hash")
        need(rec["attempt_id"] not in requests, "attempt sent twice")
        requests[rec["attempt_id"]] = body
        finals = [pdir / r.name.replace("-received.json", "-response.json")
                  for r in sorted(pdir.glob(f"{stem}-p*-received.json")) if z.load(r)["http_status"] == 200]
        for earlier in finals[:-1]:  # only zero-cost, zero-token error envelopes may precede
            u, _ = decode_billing(earlier.read_bytes())
            need(u.cost_usd == 0 and u.input_tokens == u.output_tokens == 0
                 and strict_json(earlier.read_bytes())["choices"][0].get("finish_reason") == "error",
                 "two billed answers for one call")
        if finals:
            answers[rec["attempt_id"]] = finals[-1].read_bytes()
        for r in sorted(pdir.glob(f"{stem}-p*-received.json")):
            if z.load(r)["http_status"] == 200:
                generations.append(decode_billing((pdir / r.name.replace("-received.json", "-response.json"))
                                                  .read_bytes())[1])
    slot = sk_slot(block)
    sd = directory / ARM
    run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
    seed = block["tie_break_seed"]
    started = {"run_id": run_id, "arm": ARM, "maximum_calls": MAX_CALLS, "tie_break_seed": seed,
               "instruction": gate.DIRECT_INSTRUCTION}
    need(z.load(sd / "direct-started.json") == started, "direct binding")
    row = z.load(sd / "result.json")
    samples = sorted(sd.glob("direct-[1-5].json"))
    for i, path in enumerate(samples):
        request = nx._direct_request(task, run_id, i)
        need(z.load(path)["request"] == nx.read_json_bytes(encoded(asdict(request))), "direct request")
    expected_ids = [nx._direct_request(task, run_id, i).attempt_id for i in range(MAX_CALLS)]
    need(list(requests) == expected_ids[:len(requests)] and len(samples) in (len(requests), len(requests) - 1),
         "provider attempts differ from the direct sample order")
    for i, attempt_id in enumerate(requests):
        request = nx._direct_request(task, run_id, i)
        need(requests[attempt_id] == sk_body(request), "S-k request bytes")
        sent = json.loads(requests[attempt_id])
        need(sent["temperature"] == 1.0 and sent["top_p"] == 0.9, "sampling parameters not sent")
    if (sd / "terminal-failure.json").exists():
        term = z.load(sd / "terminal-failure.json")
        raw = answers[term["attempt_id"]]
        limit = 1024
        try:
            decode_outcome(raw, limit, F01)
            raise z.GlobalStop("terminal failure on an F-01-valid answer")
        except ProbeStop:
            kind, reason = z.classify_violation(raw, limit)
        need(kind in ("overlimit", "contract") and reason == term["reason"], "terminal classification")
        billed = [a for a in answers if a.startswith(run_id + ":")]
        cost = sum((decode_billing(answers[a])[0].cost_usd for a in billed), Decimal(0))
        expected = nx._row(candidate, block, slot, dict(em=0, f1=0, cost_usd=str(cost), status="model_failure",
                           call_count=len(billed)), None, None, None, run_id)
        expected["failure_reason"] = reason
    else:
        events = []
        for i, path in enumerate(samples):
            request = nx._direct_request(task, run_id, i)
            sample = z.load(path)
            need(nx._terminal(request.attempt_id, decode_outcome(answers[request.attempt_id],
                                                                 request.max_output_tokens, F01))
                 == sample["outcome"], "direct outcome differs from provider answer")
            events.append(sample["outcome"])
        result = nx._direct_summary(events, MAX_CALLS, seed, reference)
        need(result == z.load(sd / "direct-complete.json"), "plurality/scoring differs")
        expected = nx._row(candidate, block, slot, result, None, None, None, run_id)
    need(row == expected, "row differs from recomputation")
    need(proof["rows"] == [row], "complete rows differ")
    need(sorted(generations) == sorted(proof["summary"]["generations"]), "generation ids differ")
    if old is not None:
        verify_inputs_against_old(directory, old)
        for i in range(len(requests)):  # also attempts without a saved sample (immediate terminal failure)
            previous = Path(old) / ARM / f"direct-{i + 1}.json"
            need(previous.exists() and z.load(previous)["request"]
                 == nx.read_json_bytes(encoded(asdict(nx._direct_request(task, run_id, i)))),
                 f"provider attempt {i + 1} differs from old request")
    return [row]


def verify_inputs_against_old(directory, old):
    """Same task text, same direct binding (run_id, seed, instruction), same request objects as the old S-k arm."""
    directory, old = Path(directory), Path(old)
    need(z.load(directory / "public.json") == z.load(old / "public.json"), "public task differs from old block")
    need(z.load(directory / ARM / "direct-started.json") == z.load(old / ARM / "direct-started.json"),
         "direct binding differs from old block")
    for path in sorted((directory / ARM).glob("direct-[1-5].json")):
        previous = old / ARM / path.name
        need(previous.exists() and z.load(previous)["request"] == z.load(path)["request"],
             f"request object differs from old block: {path.name}")


def sample_texts(directory):
    """Raw and normalized answer texts of completed S-k samples (for the diversity check)."""
    texts = []
    for path in sorted((Path(directory) / ARM).glob("direct-[1-5].json")):
        outcome = z.load(path)["outcome"]
        if outcome["kind"] == "completed":
            texts.append(outcome["text"])
    return texts


# --------------------------------------------------------------------------- worker

def worker_main(worker_id, tasks, results, stop_flag, folder, deadline, old_index, transport_factory=None):
    """One process, one block at a time; the old-block input check is part of acceptance."""
    try:
        ctx = z.Context(with_selectors=False)
        if transport_factory is None:
            from communication_pruning.openrouter import Transport, load_key
            transport = Transport(load_key(ctx.settings["credential_file"], source="file"))
        else:  # synthetic test transport only, never in the canonical folder
            sys.path.insert(0, str(z.RUN))
            import fake_transport
            transport = fake_transport.make(transport_factory, worker_id)
    except BaseException as error:
        results.put({"worker": worker_id, "kind": "init_failed", "error": repr(error)})
        return
    folder = Path(folder)
    results.put({"worker": worker_id, "kind": "ready"})
    while True:
        item = tasks.get()
        if item is None:
            return
        index, attempt = item
        name = z.block_name("R", index)
        tmp = folder / "inflight" / f"{name}.a{attempt}"
        started = time.time()
        try:
            run_sk_block(ctx, ctx.block("R", index), tmp, transport, deadline=deadline,
                         stop=lambda: stop_flag.value == 1)
            old = old_index.get(str(index))
            rows = verify_sk_block(ctx, tmp, Path(old) if old else None)
            final = folder / "blocks" / name
            os.rename(tmp, final)
            summary = z.load(final / "complete.json")["summary"]
            results.put({"worker": worker_id, "kind": "complete", "index": index, "attempt": attempt,
                         "rows": rows, "summary": summary, "seconds": time.time() - started,
                         "texts": sample_texts(final)})
        except z.TechnicalAbort as error:
            dest = folder / "interrupted" / f"{name}.a{attempt}"
            if tmp.exists():
                os.rename(tmp, dest)
            results.put({"worker": worker_id, "kind": "interrupted", "index": index, "attempt": attempt,
                         "error": str(error), "path": str(dest)})
        except BaseException as error:
            dest = folder / "interrupted" / f"{name}.a{attempt}"
            if tmp.exists():
                os.rename(tmp, dest)
            results.put({"worker": worker_id, "kind": "stop", "index": index, "attempt": attempt,
                         "error": f"{type(error).__name__}: {error}",
                         "trace": traceback.format_exc()[-3000:], "path": str(dest)})
            return
