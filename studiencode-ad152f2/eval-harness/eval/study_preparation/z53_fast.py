"""Z53 fast continuation of the R/T/F side panels (design: runs/Z53-SCHNELLFORTSETZUNG-001/DESIGN.md).

Measurement core is imported unchanged from final_execution (selection, arms,
configurations, execute, direct plurality, scoring, row format) and openrouter
(payload bytes, billing decode) / failure_policy (F-01 decode). Only the shell
around it changes: one process per worker, blocks in plan order, arms inside a
block in their bound order, per-block evidence, an append-only call ledger and
these pre-bound error classes (fixed before any Z53 model call):

  Z53-1 over-limit     billed answer reports more output tokens than the bound
                       limit -> arm is a model failure (EM=F1=0, all billed arm
                       costs, in the denominator), built exactly like R2182.
  Z53-3 contract       billed answer with refusal, body error, invalid envelope
                       or unclassified finish reason -> same terminal arm failure.
  Z53-2 technical      no billed answer (429, 5xx/408, transport error):
                       identical bytes resent (429 unbounded, 5xx <= 3,
                       transport error <= 1; unknown billing reserved 0.14).
  systemic             provider/model identity, cost > 0.14, reasoning tokens,
                       duplicate generation, other HTTP -> global stop.
  partial block        arms with a terminal result are never redrawn; an arm
                       interrupted technically is rerun completely; the
                       interrupted part stays as evidence with separate cost.
"""
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from communication_pruning.configurations import bank
from communication_pruning.contracts import Message, Request, TaskInput
from communication_pruning.data import AnswerReference, load_task
from communication_pruning.execution import execute
from communication_pruning import rate_limit as native_rate
from communication_pruning.failure_policy import F01, ModelFailure, decode_outcome, strict_json
from communication_pruning.openrouter import (RESERVE, ProbeStop, decode_billing, encoded,
                                              payload, save_new)
from study_preparation import final_execution as nx
from study_preparation import final_preflight as gate

OVERLIMIT_REASON = "Anbieterantwort überschreitet die gebundene Ausgabegrenze"
CONTRACT_REASON = "Anbieterantwort verletzt den F-01-Antwortvertrag"
PANELS = ("R", "T", "F")
MAX_CALLS = gate.MAX_CALLS
CANDIDATE = EVAL / "runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/activation/CANDIDATE.json"
CANDIDATE_SHA = "135d2a58d7faefde6c7b382e9a23ba5d917a3b1722e1daa7fc7766a6d1cb6a37"
PRIOR = EVAL / ("runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/"
                "recovery-R00125/technical-R00203/coverage-R01462/rate-stop-R01589")
PRIOR_INSPECT = PRIOR / "r2183-overlimit/activation/INSPECT-011223-RESULT-001.json"
RUN = EVAL / "runs/Z53-SCHNELLFORTSETZUNG-001"
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


class TerminalArmFailure(Exception):
    def __init__(self, reason, attempt_id):
        super().__init__(reason)
        self.reason, self.attempt_id = reason, attempt_id


class TechnicalAbort(Exception):
    """No billed answer after the bounded resend rule; block attempt interrupted."""


class GlobalStop(Exception):
    """Systemic deviation, budget, calendar or credential: stop all workers."""


def need(condition, message, kind=GlobalStop):
    if not condition:
        raise kind(message)


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    save_new(Path(path), encoded(value))


def append_jsonl(path, value):
    with open(path, "ab") as out:
        out.write(encoded(value) + b"\n")
        out.flush()
        os.fsync(out.fileno())


def _pick(entries):
    """Fresh provider dir of this attempt wins over inherited copies."""
    names = [name for name, _ in entries]
    return "provider" if "provider" in names else names[-1]


def classify_violation(raw, output_limit):
    """Called only after decode_outcome(F-01) rejected a billed HTTP-200 answer."""
    try:
        data = strict_json(raw)
    except Exception:
        return "systemic", "response not strict JSON"
    usage, _ = decode_billing(raw)  # already passed in the caller
    if usage.cost_usd > RESERVE:
        return "systemic", "cost above per-call reserve"
    details = data.get("usage", {}).get("completion_tokens_details") or {}
    if details.get("reasoning_tokens", 0) != 0:
        return "systemic", "reasoning tokens despite disabled reasoning"
    if type(output_limit) is not int or output_limit not in (128, 1024):
        return "systemic", "unbound output limit"
    if usage.output_tokens > output_limit:
        return "overlimit", OVERLIMIT_REASON
    return "contract", CONTRACT_REASON


# --------------------------------------------------------------------------- sender

class BlockSender:
    """Replaces StudyAdapter+PhaseBudget for one block attempt.

    Request bytes are payload(request, producer_limit=1024), identical to the
    native adapter. Every physical attempt is recorded before the next one.
    """

    def __init__(self, directory, transport, *, max_calls, deadline, stop=None,
                 sleep=time.sleep, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.transport, self.max_calls, self.deadline = transport, max_calls, deadline
        self.stop, self.sleep, self.clock = stop, sleep, clock
        self.calls = 0
        self.costs = {}          # attempt_id -> Decimal (billed answers only)
        self.unknown_attempts = 0
        self.rate_retries = 0
        self.technical_retries = 0
        self.generations = []
        self.terminal = {}       # attempt_id -> reason
        self.ledger = self.directory / "calls.jsonl"

    def _event(self, value):
        append_jsonl(self.ledger, {"t": self.clock(), **value})

    def _guard(self):
        if self.stop is not None and self.stop():
            raise GlobalStop("stop requested")
        if self.clock() > self.deadline:
            raise GlobalStop("calendar binding ends")

    def _body(self, request):
        """Request bytes; Z54 overrides this for S-k only (study_preparation/z54_sk.py)."""
        return encoded(payload(request, producer_limit=1024))

    def cost_for(self, run_id):
        return sum((v for k, v in self.costs.items() if k.startswith(run_id + ":")), Decimal(0))

    def calls_for(self, run_id):
        return sum(1 for k in self.costs if k.startswith(run_id + ":"))

    def __call__(self, request):
        self._guard()
        need(self.calls < self.max_calls, "block exceeds its bound call count")
        need(request.attempt_id not in self.costs, "duplicate attempt id in block")
        self.calls += 1
        stem = f"{self.calls:03d}"
        body = self._body(request)
        save_new(self.directory / f"{stem}-request.json", body)
        write_json(self.directory / f"{stem}-binding.json", {
            "attempt_id": request.attempt_id, "request_sha256": sha256(body).hexdigest(),
            "max_output_tokens": request.max_output_tokens})
        transport_errors = server_errors = rate = physical = 0
        base = {"call": stem, "attempt_id": request.attempt_id}
        while True:
            self._guard()
            physical += 1
            base["physical"] = physical
            try:
                status, raw = self.transport("chat/completions", body)
            except ProbeStop:
                transport_errors += 1
                self.unknown_attempts += 1
                self.technical_retries += 1
                self._event(base | {"kind": "transport_error", "billing": "unknown"})
                need(transport_errors <= 1, "transport failed twice", TechnicalAbort)
                self.sleep(10)
                continue
            name = f"{stem}-p{physical:02d}"
            save_new(self.directory / f"{name}-response.json", raw)
            write_json(self.directory / f"{name}-received.json",
                       {"http_status": status, "response_sha256": sha256(raw).hexdigest()})
            if status == 429:
                rate += 1
                self.rate_retries += 1
                self._event(base | {"kind": "rate_limited", "http_status": 429})
                self.sleep(min(60, 5 * 2 ** min(rate, 4)))
                continue
            if status >= 500 or status == 408:
                billed = None
                try:
                    billed = decode_billing(raw)
                except Exception:
                    pass
                need(billed is None, f"billed HTTP {status} answer")
                server_errors += 1
                self.technical_retries += 1
                self._event(base | {"kind": "server_error", "http_status": status})
                need(server_errors <= 3, "server errors repeated", TechnicalAbort)
                self.sleep(min(60, 5 * 2 ** server_errors))
                continue
            need(status == 200, f"unexpected HTTP status {status}")
            try:
                usage, generation = decode_billing(raw)
            except Exception as error:
                self.unknown_attempts += 1
                self._event(base | {"kind": "undecodable_billing", "billing": "unknown"})
                raise GlobalStop(f"HTTP 200 identity/billing mismatch: {error}") from None
            need(generation not in self.generations, "duplicate generation in block")
            self.generations.append(generation)
            # Upstream rate limit inside HTTP 200: exact original D-055 rule (zero cost/tokens) -> free resend.
            try:
                native_kind = native_rate.classify(200, raw, request.max_output_tokens)[0]
            except native_rate.RateStop:
                native_kind = "error_envelope"
            except Exception:
                native_kind = None
            if native_kind == "rate_limited":
                rate += 1
                self.rate_retries += 1
                self._event(base | {"kind": "rate_limited_200", "generation_id": generation})
                self.sleep(min(60, 5 * 2 ** min(rate, 4)))
                continue
            if (native_kind == "error_envelope" and usage.cost_usd == 0
                    and usage.input_tokens == usage.output_tokens == 0):
                server_errors += 1
                self.technical_retries += 1
                self._event(base | {"kind": "zero_cost_error_envelope", "generation_id": generation})
                need(server_errors <= 3, "zero-cost error envelopes repeated", TechnicalAbort)
                self.sleep(min(60, 5 * 2 ** server_errors))
                continue
            self.costs[request.attempt_id] = usage.cost_usd
            event = base | {"kind": "billed", "generation_id": generation, "usage": usage.to_dict()}
            try:
                response = decode_outcome(raw, request.max_output_tokens, F01)
            except ProbeStop:
                kind, reason = classify_violation(raw, request.max_output_tokens)
                self._event(event | {"outcome": kind, "reason": reason})
                need(kind != "systemic", f"systemic F-01 deviation: {reason}")
                self.terminal[request.attempt_id] = reason
                raise TerminalArmFailure(reason, request.attempt_id) from None
            self._event(event | {"outcome": "model_failed" if isinstance(response, ModelFailure) else "completed"})
            return response


# --------------------------------------------------------------------------- context

class Context:
    """Candidate, plan, loader and selectors exactly as final_operator.Session builds them."""

    def __init__(self, *, with_selectors=True):
        need(file_sha(CANDIDATE) == CANDIDATE_SHA, "candidate changed")
        self.candidate = gate.read_json(CANDIDATE)
        self.plan = gate.read_json(gate.evidence_file(self.candidate["plan_evidence"]))
        self.settings = self.candidate["operator"]
        self.manifest = gate.read_json(self.settings["original_manifest"]["path"])
        need(self.settings["dev_source"]["sha256"] == self.manifest["source_hashes"]["dev"], "dev source differs")
        need(file_sha(self.settings["dev_source"]["path"]) == self.settings["dev_source"]["sha256"], "dev bytes differ")
        self.frame = {row["task_id"] for row in self.plan["frame"]}
        self.spatial = self.temporal = None
        if with_selectors:
            self._selectors()

    def _selectors(self):
        from communication_pruning.semantic_selection import FrozenMiniLM, SemanticSelector
        from study_preparation.temporal import TemporalSelector
        provision = gate.read_json(self.settings["provision_manifest"]["path"])
        os.environ.update(OFFLINE_ENV)
        os.environ["TOKENIZERS" + "_PARALLELISM"] = "false"
        model_dir = Path(self.settings["provision_manifest"]["path"]).parent / provision["model_dir_relative"]
        encoder = FrozenMiniLM(model_dir, files=provision["files"], runtime=provision["runtime"])
        docs = self.candidate["documents"]
        self.spatial = SemanticSelector.from_dict(gate.read_json(docs["spatial_q"]["path"]), encoder=encoder)
        self.temporal = TemporalSelector.from_dict(gate.read_json(docs["temporal_qst"]["path"]), encoder=encoder)

    def loader(self, task_id):
        need(task_id in self.frame, "task outside frozen frame")
        task, reference = load_task(self.settings["dev_source"]["path"], task_id, self.manifest, phase="holdout")
        opaque = nx.public_task_id(self.plan, task_id)
        return replace(task, task_id=opaque), replace(reference, task_id=opaque)

    def block(self, panel, index):
        block = self.plan["panels"][panel][index]
        need(block["panel"] == panel and block["draw_index"] == index, "plan block identity")
        return block


def block_name(panel, index):
    return f"{panel}-{index:05d}"


def _failure_row(ctx, block, slot, config, rounds, failed, run_id, sender, reason):
    """R2182 construction: native _row, EM=F1=0, all billed arm costs, started calls."""
    row = nx._row(ctx.candidate, block, slot, dict(em=0, f1=0, cost_usd=str(sender.cost_for(run_id)),
                  status="model_failure", call_count=sender.calls_for(run_id)), config, rounds, failed, run_id)
    row["failure_reason"] = reason
    return row


def run_block(ctx, block, directory, transport, *, deadline, stop=None, sleep=time.sleep,
              clock=time.time, resume=None):
    """Native run_section loop body for one block, unchanged in order and content."""
    candidate, plan = ctx.candidate, ctx.plan
    panel = block["panel"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    resume = Path(resume) if resume else None
    if resume is not None:
        need(load(resume / "started.json") == {"block": block, "plan_hash": plan["plan_hash"]}, "resume foreign block")
        for name in ("started.json", "public.json", "reference.json", "selection.json",
                     "spatial-measurement.json", "temporal-measurement.json"):
            if (resume / name).exists():
                shutil.copy2(resume / name, directory / name)
        for old in sorted(p for p in resume.iterdir() if p.is_dir() and p.name.startswith("provider")):
            shutil.copytree(old, directory / f"{old.name}-{resume.name}")
        write_json(directory / "resumed-from.json", {"path": str(resume)})
        task = TaskInput(**{k: (tuple(v) if k == "paragraphs" else v) for k, v in load(directory / "public.json").items()})
        private = load(directory / "reference.json")
        reference = AnswerReference(private["task_id"], tuple(private["answers"]))
        selection = load(directory / "selection.json")
    else:
        write_json(directory / "started.json", {"block": block, "plan_hash": plan["plan_hash"]})
        task, reference = ctx.loader(block["task_id"])
        need(type(task) is TaskInput and type(reference) is AnswerReference
             and task.task_id == nx.public_task_id(plan, block["task_id"]) == reference.task_id, "loader identity")
        write_json(directory / "public.json", asdict(task))
        write_json(directory / "reference.json", asdict(reference))
        q = nx._select_observed(ctx.spatial.select, task, candidate=candidate, plan=plan,
                                block=block, kind="spatial", directory=directory)
        qt = nx._select_observed(ctx.temporal.select, task, candidate=candidate, plan=plan,
                                 block=block, kind="temporal", directory=directory) if panel == "T" else None
        need(q in {c.config_id for c in bank()} and (panel != "T" or (type(qt) is int and qt in (1, 2))),
             "selector outside frozen bank")
        selection = {"spatial_q": q, "temporal_qst": qt}
        write_json(directory / "selection.json", selection)
    sender = BlockSender(directory / "provider", transport, max_calls=MAX_CALLS[panel],
                         deadline=deadline, stop=stop, sleep=sleep, clock=clock)
    rows, resumed_arms = [], []
    for slot in block["slots"]:
        arm = slot["arm"]
        sd = directory / arm
        if resume is not None and (resume / arm / "result.json").exists():
            shutil.copytree(resume / arm, sd)
            rows.append(load(sd / "result.json"))
            resumed_arms.append(arm)
            continue
        sd.mkdir()
        run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
        config, rounds, failed = nx._configuration(candidate, block, arm, selection)
        try:
            if config is None:
                result = nx._direct(task, reference, run_id, arm, 0 if arm == "S" else block["tie_break_seed"], sd, sender)
            else:
                execute(task, config, sender, rounds=rounds, failed_role=failed, run_id=run_id,
                        journal_path=sd / "journal.jsonl", producer_limit=1024, failure_policy=F01)
                result, _ = nx._mas_result(sd / "journal.jsonl", config, task, reference, block)
            row = nx._row(candidate, block, slot, result, config, rounds, failed, run_id)
            need(row["call_count"] == sender.calls_for(run_id) and Decimal(row["cost_usd"]) == sender.cost_for(run_id),
                 "arm calls/costs differ from billed sender records")
        except TerminalArmFailure as failure:
            need(failure.attempt_id.startswith(run_id + ":"), "terminal failure of a foreign arm")
            row = _failure_row(ctx, block, slot, config, rounds, failed, run_id, sender, failure.reason)
            write_json(sd / "terminal-failure.json", {"attempt_id": failure.attempt_id, "reason": failure.reason,
                       "rule": "Z53-1" if failure.reason == OVERLIMIT_REASON else "Z53-3"})
        write_json(sd / "result.json", row)
        rows.append(row)
    evidence = {str(p.relative_to(directory)): file_sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
    summary = {"calls": sender.calls, "known_cost_usd": str(sum(sender.costs.values(), Decimal(0))),
               "unknown_attempts": sender.unknown_attempts, "rate_retries": sender.rate_retries,
               "technical_retries": sender.technical_retries, "generations": sender.generations,
               "terminal_failures": sender.terminal, "resumed_arms": resumed_arms}
    write_json(directory / "complete.json", {"block": block, "plan_hash": plan["plan_hash"], "rows": rows,
                                             "evidence": evidence, "summary": summary,
                                             "runner": "Z53-SCHNELLFORTSETZUNG-001"})
    return rows, summary


# --------------------------------------------------------------------------- independent check

def verify_block(ctx, directory):
    """Recompute a finished Z53 block from its files with native functions (like final_execution._inspect)."""
    candidate, plan = ctx.candidate, ctx.plan
    directory = Path(directory)
    proof = load(directory / "complete.json")
    block = proof["block"]
    need(load(directory / "started.json") == {"block": block, "plan_hash": plan["plan_hash"]}
         and block == ctx.block(block["panel"], block["draw_index"]), "block identity")
    for name, checksum in proof["evidence"].items():
        need(file_sha(directory / name) == checksum, f"evidence changed: {name}")
    public = load(directory / "public.json")
    task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
    private = load(directory / "reference.json")
    reference = AnswerReference(private["task_id"], tuple(private["answers"]))
    need(task.task_id == nx.public_task_id(plan, block["task_id"]) == reference.task_id, "task identity")
    selection = load(directory / "selection.json")
    for kind, choice in (("spatial", selection["spatial_q"]), ("temporal", selection["temporal_qst"])):
        if choice is not None:
            nx._check_selection_measurement(load(directory / f"{kind}-measurement.json"),
                                            candidate, plan, block, kind, choice)
    # provider evidence of all attempts in this block (fresh and inherited)
    requests, answers = {}, {}
    for pdir in sorted(p for p in directory.iterdir() if p.is_dir() and p.name.startswith("provider")):
        for b in sorted(pdir.glob("*-binding.json")):
            rec = load(b)
            stem = b.name[:3]
            body = (pdir / f"{stem}-request.json").read_bytes()
            need(rec["request_sha256"] == sha256(body).hexdigest(), "request hash")
            finals = []
            for r in sorted(pdir.glob(f"{stem}-p*-received.json")):
                if load(r)["http_status"] == 200:
                    finals.append(pdir / r.name.replace("-received.json", "-response.json"))
            if pdir.name == "provider":
                need(rec["attempt_id"] not in requests, "attempt sent twice in one attempt")
            requests.setdefault(rec["attempt_id"], []).append((pdir.name, body))
            if finals:
                for earlier in finals[:-1]:  # only zero-cost, zero-token error envelopes may precede
                    u, _ = decode_billing(earlier.read_bytes())
                    need(u.cost_usd == 0 and u.input_tokens == u.output_tokens == 0
                         and strict_json(earlier.read_bytes())["choices"][0].get("finish_reason") == "error",
                         "two billed answers for one call")
                answers.setdefault(rec["attempt_id"], []).append((pdir.name, finals[-1].read_bytes()))
    rows = []
    for slot in block["slots"]:
        arm = slot["arm"]
        sd = directory / arm
        run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
        config, rounds, failed = nx._configuration(candidate, block, arm, selection)
        row = load(sd / "result.json")
        source = None  # provider dir that produced this arm
        if (sd / "terminal-failure.json").exists():
            term = load(sd / "terminal-failure.json")
            billed = [a for a in answers if a.startswith(run_id + ":")]
            source = _pick(answers[term["attempt_id"]])
            cost = sum((decode_billing(dict(answers[a])[source])[0].cost_usd for a in billed
                        if source in dict(answers[a])), Decimal(0))
            raw = dict(answers[term["attempt_id"]])[source]
            limit = load(directory / source / next(b.name for b in (directory / source).glob("*-binding.json")
                         if load(b)["attempt_id"] == term["attempt_id"]))["max_output_tokens"]
            try:
                decode_outcome(raw, limit, F01)
                raise GlobalStop("terminal failure on an F-01-valid answer")
            except ProbeStop:
                kind, reason = classify_violation(raw, limit)
            need(kind in ("overlimit", "contract") and reason == term["reason"], "terminal classification")
            expected = nx._row(candidate, block, slot, dict(em=0, f1=0, cost_usd=str(cost), status="model_failure",
                               call_count=sum(1 for a in billed if source in dict(answers[a]))),
                               config, rounds, failed, run_id)
            expected["failure_reason"] = reason
        elif config is None:
            maximum, seed = (1, 0) if arm == "S" else (5, block["tie_break_seed"])
            need(load(sd / "direct-started.json") == {"run_id": run_id, "arm": arm, "maximum_calls": maximum,
                 "tie_break_seed": seed, "instruction": gate.DIRECT_INSTRUCTION}, "direct binding")
            events = []
            for i, path in enumerate(sorted(sd.glob("direct-[1-5].json"))):
                sample = load(path)
                request = nx._direct_request(task, run_id, i)
                need(sample["request"] == nx.read_json_bytes(encoded(asdict(request))), "direct request")
                body = encoded(payload(request, producer_limit=1024))
                source = _pick(requests[request.attempt_id])
                need(dict(requests[request.attempt_id])[source] == body, "direct request bytes")
                raw = dict(answers[request.attempt_id])[source]
                need(nx._terminal(request.attempt_id, decode_outcome(raw, request.max_output_tokens, F01))
                     == sample["outcome"], "direct outcome differs from provider answer")
                events.append(sample["outcome"])
            result = nx._direct_summary(events, maximum, seed, reference)
            need(result == load(sd / "direct-complete.json"), "plurality/scoring differs")
            expected = nx._row(candidate, block, slot, result, config, rounds, failed, run_id)
        else:
            result, trace = nx._mas_result(sd / "journal.jsonl", config, task, reference, block)
            need(trace["run_id"] == run_id and trace["rounds"] == rounds and trace["failed_role"] == failed, "MAS binding")
            current = None
            for event in trace["events"]:
                if event["kind"] == "started":
                    current = Request(event["attempt_id"], task, event["role"], event["round"], event["instruction"],
                                      tuple(Message(**m) for m in event["messages"]), event["max_output_tokens"])
                    body = encoded(payload(current, producer_limit=1024))
                    source = _pick(requests[current.attempt_id])
                    need(dict(requests[current.attempt_id])[source] == body, "MAS request bytes")
                elif event["kind"] in ("completed", "model_failed"):
                    raw = dict(answers[current.attempt_id])[source]
                    need(nx._terminal(current.attempt_id, decode_outcome(raw, current.max_output_tokens, F01))
                         == event, "MAS outcome differs from provider answer")
            expected = nx._row(candidate, block, slot, result, config, rounds, failed, run_id)
        need(row == expected, f"row {arm} differs from recomputation")
        rows.append(row)
    need(rows == proof["rows"], "complete rows differ")
    return rows


# --------------------------------------------------------------------------- worker

def worker_main(worker_id, tasks, results, stop_flag, folder, deadline, transport_factory=None):
    """One process: own encoder/selectors, own transport, blocks strictly one at a time."""
    try:
        ctx = Context()
        if transport_factory is None:
            from communication_pruning.openrouter import Transport, load_key
            transport = Transport(load_key(ctx.settings["credential_file"], source="file"))
        else:  # synthetic test transport only, never in the canonical folder
            sys.path.insert(0, str(RUN))
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
        panel, index, attempt, resume = item
        name = block_name(panel, index)
        tmp = folder / "inflight" / f"{name}.a{attempt}"
        started = time.time()
        try:
            run_block(ctx, ctx.block(panel, index), tmp, transport, deadline=deadline,
                      stop=lambda: stop_flag.value == 1, resume=resume)
            rows = verify_block(ctx, tmp)
            final = folder / "blocks" / name
            os.rename(tmp, final)
            summary = load(final / "complete.json")["summary"]
            results.put({"worker": worker_id, "kind": "complete", "panel": panel, "index": index,
                         "attempt": attempt, "rows": rows, "summary": summary, "seconds": time.time() - started})
        except TechnicalAbort as error:
            dest = folder / "interrupted" / f"{name}.a{attempt}"
            if tmp.exists():
                os.rename(tmp, dest)
            results.put({"worker": worker_id, "kind": "interrupted", "panel": panel, "index": index,
                         "attempt": attempt, "error": str(error), "path": str(dest)})
        except BaseException as error:
            dest = folder / "interrupted" / f"{name}.a{attempt}"
            if tmp.exists():
                os.rename(tmp, dest)
            results.put({"worker": worker_id, "kind": "stop", "panel": panel, "index": index,
                         "attempt": attempt, "error": f"{type(error).__name__}: {error}",
                         "trace": traceback.format_exc()[-3000:], "path": str(dest)})
            return
