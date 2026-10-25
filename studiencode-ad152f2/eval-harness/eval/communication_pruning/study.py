"""Sequential spatial executor. No implicit release, retry or key lookup.

File hashes detect changes against external expectations, not hostile rewrites.
Process-crash persistence follows the existing local fsync evidence contract.
"""
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from .configurations import bank
from .contracts import AdapterError, Response, Usage
from .data import digest, load_task
from .evaluation import read_result
from .execution import execute
from .openrouter import (MODEL, PROVIDER, RESERVE, decode_billing, decode_response,
                         encoded, now, payload, save_new, validate_endpoint)
from .phase_budget import PhaseBudget
from .failure_policy import F01, decode_outcome, strict_json, validate_policy
from .spatial_plan import validate_plan, phase_key, iteration_claim


class StudyStop(RuntimeError):
    pass


def file_hash(path):
    h = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class FileGuard:
    def __init__(self, files):
        if not files or any(len(h) != 64 for h in files.values()):
            raise ValueError("external file bindings required")
        self.files = {Path(p): h for p, h in files.items()}

    def __call__(self):
        for path, expected in self.files.items():
            if file_hash(path) != expected:
                raise StudyStop("bound file changed; no execution")


class StudyAdapter:
    """One transport attempt per phase reservation; no task labels accepted."""
    def __init__(self, folder, transport, budget, *, synthetic=False, failure_policy=None):
        validate_policy(failure_policy)
        self.failure_policy = failure_policy
        self.folder, self.transport, self.budget = Path(folder), transport, budget
        self.synthetic = synthetic
        self.generations = set()
        self.poisoned = False

    def __call__(self, request):
        if self.poisoned:
            raise StudyStop("adapter already stopped")
        self.poisoned = True
        # Save only safe names generated locally, never caller-supplied IDs.
        stem = f"{self.budget.calls + 1:05d}"
        body = encoded(payload(request, producer_limit=1024))
        save_new(self.folder / f"{stem}-request.json", body)
        save_new(self.folder / f"{stem}-binding.json", encoded({
            "attempt_id": request.attempt_id, "request_sha256": sha256(body).hexdigest(),
            "mode": "synthetic" if self.synthetic else "live"}))

        def attempt():
            usage = Usage()
            try:
                status, raw = self.transport("chat/completions", body)
                save_new(self.folder / f"{stem}-response.json", raw)
                save_new(self.folder / f"{stem}-received.json", encoded({
                    "http_status": status, "response_sha256": sha256(raw).hexdigest()}))
                # An HTTP error may still carry an identifiable billed generation.
                if self.failure_policy == F01:
                    strict_json(raw)
                billed, generation = decode_billing(raw)
                if generation in self.generations:
                    raise StudyStop("duplicate generation; billing unresolved")
                if self.synthetic:
                    billed = replace(billed, cost_source="synthetic")
                save_new(self.folder / f"{stem}-billing.json", encoded({
                    "generation_id": generation, "usage": billed.to_dict(),
                    "response_sha256": sha256(raw).hexdigest()}))
                # Only durable, distinct billing is allowed to release a reserve.
                self.generations.add(generation)
                usage = billed
                if status != 200:
                    raise StudyStop("HTTP failure; no retry")
                response = decode_outcome(raw, request.max_output_tokens, self.failure_policy)
                return replace(response, usage=usage)
            except Exception:
                # The enclosing budget persists known rejected-answer costs and
                # raises a phase-wide stop, rather than an absorbable call error.
                raise AdapterError("study attempt rejected; inspect evidence", usage) from None

        response = self.budget.run(request.attempt_id, attempt)
        self.poisoned = False
        return response


def run_spatial(plan, manifest, task_ids, repeats, *, bindings, source_path,
                folder, control, transport, guard, synthetic=False, slot_limit=None,
                resume_from=None, failure_policy=None, checkpoint=False, iteration_contract=None):
    from .study_resume import phase_lock
    with phase_lock(control, plan):
        return _run_spatial(plan, manifest, task_ids, repeats, bindings=bindings,
            source_path=source_path, folder=folder, control=control, transport=transport,
            guard=guard, synthetic=synthetic, slot_limit=slot_limit, resume_from=resume_from,
            failure_policy=failure_policy, checkpoint=checkpoint, iteration_contract=iteration_contract)


def _run_spatial(plan, manifest, task_ids, repeats, *, bindings, source_path,
                folder, control, transport, guard, synthetic=False, slot_limit=None, resume_from=None,
                failure_policy=None, checkpoint=False, iteration_contract=None):
    """Execute trusted inputs only. Live callers must pass through run_live.

    A callable transport is injected for testing; no automatic network fallback.
    A prefix limit requires a synthetic demonstration or an explicit checkpoint.
    """
    validate_policy(failure_policy)
    guard()
    validate_plan(plan, manifest, task_ids, repeats, bindings=bindings,
                  iteration_contract=iteration_contract)
    if iteration_contract is not None and failure_policy != iteration_contract["failure_policy"]:
        raise StudyStop("iteration failure policy differs from external contract")
    if type(checkpoint) is not bool:
        raise StudyStop("checkpoint must be explicit boolean")
    if slot_limit is not None and (not (synthetic or checkpoint) or type(slot_limit) is not int
                                   or not 1 <= slot_limit <= len(plan["slots"])):
        raise StudyStop("only synthetic prefixes or explicit checkpoints allowed")
    if file_hash(source_path) != manifest["source_hashes"]["train"]:
        raise StudyStop("source mismatch before import")
    folder, control = Path(folder), Path(control)
    control.mkdir(parents=True, exist_ok=True)
    from .study_resume import execution_binding, inspect_locked
    budget, prefix, segment, generations = None, 0, "", set()
    if resume_from is None:
        # A new output directory cannot silently reset this plan's budget.
        save_new(control / f"{phase_key(plan)}.claim.json", encoded({
            "plan_sha256": plan["sha256"], "started_utc": now(),
            **iteration_claim(plan),
            "output": str(folder.resolve()), "mode": "synthetic" if synthetic else "live",
            "reserved_task_ids": task_ids, "repeat_ids": repeats, "failure_policy": failure_policy,
            "status": "consumed_even_after_failure_no_resume"}))
        folder.mkdir(parents=True, exist_ok=False)
        for sub in ("provider", "slots"):
            (folder / sub).mkdir()
        save_new(folder / "plan.json", encoded(plan))
        save_new(folder / "execution-bindings.json", encoded(execution_binding(
            plan, manifest, task_ids, repeats, bindings, source_path, failure_policy)))
    else:
        state = inspect_locked(plan, manifest, task_ids, repeats, bindings=bindings,
            source_path=source_path, folder=folder, control=control, guard=guard,
            synthetic=synthetic, failure_policy=failure_policy, iteration_contract=iteration_contract)
        prefix = state["completed_slots"]
        if (not isinstance(resume_from, str) or resume_from != state["resume_token"]
                or prefix >= (slot_limit or len(plan["slots"]))):
            raise StudyStop("stale resume token or no unstarted slot in requested range")
        budget, generations = state["budget"], state["generations"]
        segment = f"resume-{len(list(folder.glob('resume-*-start.json'))) + 1:05d}-"
        save_new(folder / f"{segment}start.json", encoded({
            "resume_from": resume_from, "completed_slots_before": prefix,
            "evidence_before": state["evidence"], "started_utc": now(),
            "budget_before": budget.snapshot(), "missing_results": state["missing_results"]}))
        for name, value in state["reconstructed_results"].items():
            save_new(folder / "slots" / f"{name}-result.json", encoded(value))
    report = {"status": "started", "mode": "synthetic" if synthetic else "live",
              "plan_sha256": plan["sha256"], "completed_slots": prefix,
              "real_model_calls": 0 if synthetic else None, "failure_policy": failure_policy}
    if resume_from is not None:
        report.update(resume_from=resume_from, completed_slots_before=prefix,
                      start_receipt=f"{segment}start.json")
    try:
        status, catalog = transport("models/google/gemini-2.5-flash-lite/endpoints")
        save_new(folder / f"{segment}endpoint.json", catalog)
        save_new(folder / f"{segment}endpoint-retrieval.json", encoded({"utc": now(), "http_status": status,
                    "source": "synthetic_transport" if synthetic else "live_public_catalog"}))
        if status != 200:
            raise StudyStop("catalog request failed")
        validate_endpoint(catalog)
        budget = budget or PhaseBudget(folder / "budget.jsonl", cap=Decimal(plan["proposed_phase_cap_usd"]),
                             reserve=RESERVE, max_calls=plan["summary"]["model_calls_without_retry"],
                             binding=plan["sha256"], allow_synthetic=synthetic)
        adapter = StudyAdapter(folder / "provider", transport, budget, synthetic=synthetic, failure_policy=failure_policy)
        adapter.generations.update(generations)
        configurations = {c.config_id: c for c in bank()}
        selected = set(task_ids)
        entries = {e["task_id"]: e for e in manifest["entries"]}
        last_id, loaded = None, None
        # Original plan order, with a fresh execute() state for every slot.
        for slot in plan["slots"][prefix:slot_limit]:
            guard()
            task_id = slot["task_id"]
            if task_id not in selected or entries[task_id]["phase"] != "spatial":
                raise StudyStop("not an explicitly selected spatial task")
            if task_id != last_id:
                loaded = load_task(source_path, task_id, manifest, phase="spatial")
                last_id = task_id
            task, reference = loaded
            expected_id = "task-" + digest([manifest["source_hashes"]["train"], task_id])
            if task.task_id != expected_id or reference.task_id != expected_id:
                raise StudyStop("public/reference identity mismatch")
            config = configurations[slot["config_id"]]
            run_id = plan["sha256"][:16] + "-" + slot["slot_id"]
            journal_path = folder / "slots" / f"{slot['slot_id']}.jsonl"
            save_new(folder / "slots" / f"{slot['slot_id']}-binding.json", encoded({
                **slot, "run_id": run_id, "public_task_id": task.task_id,
                "plan_sha256": plan["sha256"]}))
            execute(task, config, adapter, rounds=2, run_id=run_id,
                    journal_path=journal_path, producer_limit=1024, failure_policy=failure_policy)
            scored = read_result(journal_path, config, task, reference, family_id=slot["family_id"],
                                 phase="spatial", repeat=slot["repeat"])
            result = asdict(scored)
            for key in ("cost_usd", "known_subtotal_usd"):
                result[key] = str(result[key]) if result[key] is not None else None
            save_new(folder / "slots" / f"{slot['slot_id']}-result.json", encoded(result))
            report["completed_slots"] += 1
        guard()
        report["status"] = "completed" if report["completed_slots"] == len(plan["slots"]) else ("synthetic_prefix" if synthetic else "paused_at_checkpoint")
    except BaseException as error:
        report.update(status="stopped", error_type=type(error).__name__)
        raise
    finally:
        report["budget"] = None if budget is None else budget.snapshot()
        if failure_policy == F01:
            report["model_failed_slots"] = sum(json.loads(p.read_bytes())["status"] == "model_failed"
                for p in (folder / "slots").glob("*-result.json"))
        report["finished_utc"] = now()
        save_new(folder / f"{segment}report.json", encoded(report))
    return report
