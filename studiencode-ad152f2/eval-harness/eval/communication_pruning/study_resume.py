"""Offline complete-prefix inspection. No retry or partial-task recovery.

The file lock covers cooperating local writers, not distributed filesystems.
Evidence hashes detect accidental changes; they are not adversarial signatures.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
from decimal import Decimal
import fcntl
import json
from pathlib import Path

from .configurations import bank
from .contracts import TaskInput, Message, Request
from .data import digest, load_task
from .evaluation import read_result
from .journal import read_journal, _object, _constant
from .openrouter import RESERVE, decode_billing, encoded, payload
from .phase_budget import PhaseBudget
from .failure_policy import F01, ModelFailure, decode_outcome, validate_policy
from .spatial_plan import validate_plan, phase_key, iteration_claim
from .study import StudyStop, file_hash


def read_json(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=_object, parse_constant=_constant)


@contextmanager
def phase_lock(control, plan):
    control = Path(control)
    control.mkdir(parents=True, exist_ok=True)
    with (control / f"{phase_key(plan)}.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StudyStop("another phase writer is active") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def execution_binding(plan, manifest, task_ids, repeats, bindings, source_path, failure_policy=None):
    validate_policy(failure_policy)
    sources = Path(__file__).parent
    return {"schema": "spatial-execution/v2", "failure_policy": failure_policy,
            "execution_plan_sha256": digest({"plan_sha256": plan["sha256"], "failure_policy": failure_policy}), "inputs": digest({"plan": plan,
            "manifest": manifest, "task_ids": task_ids, "repeats": repeats,
            "bindings": bindings, "source_path": str(Path(source_path).resolve())}),
            "code": {p.name: file_hash(p) for p in sorted(sources.glob("*.py"))}}


def result_dict(result):
    value = asdict(result)
    for key in ("cost_usd", "known_subtotal_usd"):
        value[key] = str(value[key]) if value[key] is not None else None
    return value


def inspect_spatial(plan, manifest, task_ids, repeats, *, bindings, source_path,
                    folder, control, guard, synthetic=False, failure_policy=None, iteration_contract=None):
    """Inspect without changing evidence; return a token for one explicit resume.

    Only already completed task contents are reread for derived-score checks.
    Unstarted input content, credentials and transports are never opened here.
    """
    with phase_lock(control, plan):
        state = inspect_locked(plan, manifest, task_ids, repeats, bindings=bindings,
                               source_path=source_path, folder=folder, control=control,
                               guard=guard, synthetic=synthetic, failure_policy=failure_policy,
                               iteration_contract=iteration_contract)
    return {k: state[k] for k in ("resume_token", "completed_slots", "classification", "missing_results")}


def inspect_locked(plan, manifest, task_ids, repeats, *, bindings, source_path,
                   folder, control, guard, synthetic=False, failure_policy=None, iteration_contract=None):
    validate_policy(failure_policy)
    guard()
    validate_plan(plan, manifest, task_ids, repeats, bindings=bindings,
                  iteration_contract=iteration_contract)
    if iteration_contract is not None and failure_policy != iteration_contract["failure_policy"]:
        raise StudyStop("iteration failure policy differs from external contract")
    folder, control = Path(folder), Path(control)
    mode = "synthetic" if synthetic else "live"
    if file_hash(source_path) != manifest["source_hashes"]["train"]:
        raise StudyStop("source changed")
    claim_path = control / f"{phase_key(plan)}.claim.json"
    claim = read_json(claim_path)
    expected = {"plan_sha256": plan["sha256"], "output": str(folder.resolve()),
                **iteration_claim(plan),
                "mode": mode, "reserved_task_ids": task_ids, "repeat_ids": repeats, "failure_policy": failure_policy,
                "status": "consumed_even_after_failure_no_resume"}
    if any(claim.get(k) != v for k, v in expected.items()):
        raise StudyStop("claim or output binding mismatch")
    if (read_json(folder / "plan.json") != plan
            or read_json(folder / "execution-bindings.json") != execution_binding(
                plan, manifest, task_ids, repeats, bindings, source_path, failure_policy)):
        raise StudyStop("changed or legacy execution binding")
    budget = PhaseBudget.read_completed(folder / "budget.jsonl",
        cap=Decimal(plan["proposed_phase_cap_usd"]), reserve=RESERVE,
        max_calls=plan["summary"]["model_calls_without_retry"], binding=plan["sha256"],
        allow_synthetic=synthetic)
    checked = inspect_records(plan, manifest, source_path=source_path, folder=folder,
        budget=budget, synthetic=synthetic, failure_policy=failure_policy,
        slots=plan["slots"], run_prefix=plan["sha256"][:16] + "-")
    completed, generations = checked["completed"], checked["generations"]
    missing, results = checked["missing_results"], checked["reconstructed_results"]
    evidence = {str(p.relative_to(folder)): file_hash(p) for p in sorted(folder.rglob("*")) if p.is_file()}
    evidence["@claim"] = file_hash(claim_path)
    guard()
    return {"classification": "complete_prefix" if completed else "unbegun",
            "resume_token": digest(evidence), "completed_slots": len(completed),
            "budget": budget, "generations": generations,
            "missing_results": missing, "reconstructed_results": results,
            "evidence": evidence}



def inspect_records(plan, manifest, *, source_path, folder, budget, synthetic,
                    failure_policy, slots, run_prefix, initial_generations=(),
                    extra_slot_files=(), extra_provider_files=()):
    """Verify terminal records against an already bound ledger and slot range.

    This does not authorize execution or accept a partial ledger. Callers own
    source/plan/claim checks and the exclusive lock. Extra files are only for
    the explicitly frozen old incident, never for a resumed segment.
    """
    folder = Path(folder)
    mode = "synthetic" if synthetic else "live"
    configurations = {c.config_id: c for c in bank()}
    slot_files, provider_files = set(extra_slot_files), set(extra_provider_files)
    generations, settlements = set(initial_generations), []
    completed, traces = [], []
    for slot in slots:
        name = slot["slot_id"]
        journal = folder / "slots" / f"{name}.jsonl"
        binding_path = folder / "slots" / f"{name}-binding.json"
        result_path = folder / "slots" / f"{name}-result.json"
        if not journal.exists() and not binding_path.exists() and not result_path.exists():
            break
        record = read_journal(journal, configurations[slot["config_id"]])
        trace = record["trace"]
        public_id = "task-" + digest([manifest["source_hashes"]["train"], slot["task_id"]])
        run_id = run_prefix + name
        if (not record["sealed"] or trace["status"] not in (("completed", "model_failed") if failure_policy == F01 else ("completed",))
                or trace.get("failure_policy") != failure_policy
                or trace["run_id"] != run_id or trace["task"]["task_id"] != public_id
                or trace["rounds"] != 2
                or trace.get("output_limits") != {"producer": 1024, "aggregator": 128}
                or read_json(binding_path) != {**slot, "run_id": run_id,
                    "public_task_id": public_id, "plan_sha256": plan["sha256"]}):
            raise StudyStop("incomplete or inconsistent slot")
        events = trace["events"]
        expected_calls = slot["planned_calls"]
        if (len(events) % 2 or not 2 <= len(events) <= expected_calls * 2
                or trace["status"] == "completed" and len(events) != expected_calls * 2):
            raise StudyStop("wrong completed call count")
        for started, finished in zip(events[::2], events[1::2]):
            if started["kind"] != "started" or finished["kind"] not in (("completed", "model_failed") if failure_policy == F01 else ("completed",)):
                raise StudyStop("failed or partial attempt")
            stem = f"{len(settlements) + 1:05d}"
            paths = {key: folder / "provider" / f"{stem}-{key}.json"
                     for key in ("request", "binding", "response", "received", "billing")}
            raw = paths["response"].read_bytes()
            usage, generation = decode_billing(raw)
            if synthetic:
                usage = replace(usage, cost_source="synthetic")
            task = TaskInput(**{**trace["task"], "paragraphs": tuple(trace["task"]["paragraphs"])})
            request = Request(attempt_id=started["attempt_id"], task=task,
                role=started["role"], round=started["round"], instruction=started["instruction"],
                messages=tuple(Message(**m) for m in started["messages"]),
                max_output_tokens=started["max_output_tokens"])
            response = decode_outcome(raw, request.max_output_tokens, failure_policy)
            terminal = ({"kind": "model_failed", "attempt_id": request.attempt_id,
                         "reason": response.reason, "usage": usage.to_dict()}
                        if isinstance(response, ModelFailure) else
                        {"kind": "completed", "attempt_id": request.attempt_id,
                         "text": response.text, "usage": usage.to_dict()})
            if (generation in generations or finished != terminal
                    or finished["usage"] != usage.to_dict()
                    or paths["request"].read_bytes() != encoded(payload(request, producer_limit=1024))
                    or read_json(paths["binding"]) != {"attempt_id": request.attempt_id,
                        "request_sha256": file_hash(paths["request"]), "mode": mode}
                    or read_json(paths["received"]) != {"http_status": 200, "response_sha256": file_hash(paths["response"])}
                    or read_json(paths["billing"]) != {"generation_id": generation,
                        "usage": usage.to_dict(), "response_sha256": file_hash(paths["response"])}):
                raise StudyStop("provider and slot evidence disagree")
            generations.add(generation)
            settlements.append((request.attempt_id, usage.to_dict()))
            provider_files.update(paths.values())
        slot_files.update((journal, binding_path))
        if result_path.exists():
            slot_files.add(result_path)
        completed.append(slot)
        traces.append(trace)
    if (set((folder / "slots").iterdir()) != slot_files
            or set((folder / "provider").iterdir()) != provider_files
            or budget.settlements != settlements):
        raise StudyStop("gap, orphan evidence or ledger mismatch")
    # All calls and journals are structurally safe before any original task reload.
    missing, results = [], {}
    for slot in completed:
        name = slot["slot_id"]
        task, reference = load_task(source_path, slot["task_id"], manifest, phase="spatial")
        value = result_dict(read_result(folder / "slots" / f"{name}.jsonl",
            configurations[slot["config_id"]], task, reference, family_id=slot["family_id"],
            phase="spatial", repeat=slot["repeat"]))
        result_path = folder / "slots" / f"{name}-result.json"
        if result_path.exists():
            if read_json(result_path) != value:
                raise StudyStop("derived score changed")
        else:
            missing.append(name)
            results[name] = value
    return {"completed": completed, "generations": generations,
            "missing_results": missing, "reconstructed_results": results}
