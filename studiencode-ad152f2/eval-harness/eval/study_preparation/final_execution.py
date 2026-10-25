"""Z50 sequential P/R/T/F execution with explicit, injected dependencies only.

One namespace, one PhaseBudget and one exclusive lock span all four panels.
Only an intact, backed-up complete-block prefix can continue at its next bound
control hold. Partial blocks and technical failures have no retry/recovery API.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
import fcntl

import numpy as np

from communication_pruning.configurations import bank, dense
from communication_pruning.contracts import TaskInput, Request, Message, INSTRUCTIONS
from communication_pruning.data import AnswerReference
from communication_pruning.evaluation import normalize_answer, score_answer, read_result
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, ModelFailure, decode_outcome
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import encoded, save_new, payload, decode_billing
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.study import StudyAdapter, file_hash
from .final_plan import ARMS, canonical_hash
from .final_resources import ProcessObservation, validate_observation
from .final_preflight import (NAMESPACE, MAX_CALLS, DIRECT_INSTRUCTION, StudyStop,
                              budget_view, execution_binding, money, preflight,
                              runtime_guard, read_json, verify_archive)


def _save(path, value):
    save_new(Path(path), encoded(value))


def _blocks(plan):
    return [block for panel in ARMS for block in plan["panels"][panel]]


def public_task_id(plan, task_id):
    return "task-" + canonical_hash([plan["bindings"]["frame_metadata"], task_id])


@contextmanager
def study_lock(control):
    control = Path(control)
    control.mkdir(parents=True, exist_ok=True)
    with (control / (NAMESPACE + ".lock")).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StudyStop("another study writer owns the shared namespace") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _claim(candidate, plan, folder, control, *, create=False):
    expected = {"namespace": NAMESPACE, "execution_binding_sha256": execution_binding(candidate),
                "plan_hash": plan["plan_hash"], "folder": str(Path(folder).resolve())}
    path = Path(control) / (NAMESPACE + ".claim.json")
    if path.exists():
        if read_json(path) != expected:
            raise StudyStop("study already claimed with another folder or binding")
    elif create:
        _save(path, expected)
    else:
        raise StudyStop("canonical study claim missing")


def _budget(candidate, plan, folder, *, existing):
    available = budget_view(candidate, {p: Decimal(0) for p in ARMS})["available_usd"]
    cap = min(money(available["overall"]), money(available["main"]) + money(available["secondary"]))
    factory = PhaseBudget.read_completed if existing else PhaseBudget
    return factory(Path(folder) / "budget.jsonl", cap=cap, reserve=Decimal("0.14"),
                   max_calls=sum(MAX_CALLS[p] * plan["counts"][p] for p in ARMS),
                   binding=execution_binding(candidate), allow_synthetic=candidate["mode"] == "artificial_only")


def plurality(answers, seed):
    """Whole-answer official normalization; empty normalized text is a class."""
    if not answers or any(not isinstance(a, str) or not a.strip() for a in answers) or type(seed) is not int or seed < 0:
        raise StudyStop("regular nonempty answers and bound tie seed required")
    normalized = [normalize_answer(a) for a in answers]
    counts = Counter(normalized)
    tied = sorted(key for key, count in counts.items() if count == max(counts.values()))
    rng = np.random.Generator(np.random.PCG64(seed))
    selected = tied[int(rng.integers(len(tied)))]
    index = normalized.index(selected)
    return {"classes": [{"normalized": key, "votes": counts[key],
                         "positions": [i for i, value in enumerate(normalized) if value == key]}
                        for key in sorted(counts)],
            "tie_classes": tied, "tie_break_seed": seed, "tie_algorithm": "PCG64",
            "selected_class": selected, "representative_index": index, "answer": answers[index]}


def _terminal(attempt_id, response):
    if isinstance(response, ModelFailure):
        return {"kind": "model_failed", "attempt_id": attempt_id, "reason": response.reason, "usage": response.usage.to_dict()}
    return {"kind": "completed", "attempt_id": attempt_id, "text": response.text, "usage": response.usage.to_dict()}


def _direct_request(task, run_id, index):
    # The administrative role is not sent by payload(); the immutable short-
    # answer instruction is sent instead of any producer/aggregator instruction.
    return Request(f"{run_id}:S:{index + 1}", task, "single", 1, DIRECT_INSTRUCTION, (), 1024)


def _direct_summary(events, maximum, seed, reference):
    failures = [e for e in events if e["kind"] == "model_failed"]
    if not events or len(events) > maximum or failures and (len(failures) != 1 or events[-1] is not failures[0]):
        raise StudyStop("invalid direct failure prefix")
    if not failures and len(events) != maximum:
        raise StudyStop("direct slot lacks all required fresh calls")
    decision = None if failures else plurality([e["text"] for e in events], seed)
    scores = {"em": 0.0, "f1": 0.0} if failures else score_answer(decision["answer"], reference)
    return {"status": "model_failure" if failures else "ok", **scores,
            "cost_usd": str(sum((money(e["usage"]["cost_usd"]) for e in events), Decimal(0))),
            "call_count": len(events), "vote": decision,
            "failure_reason": failures[0]["reason"] if failures else None}


def _direct(task, reference, run_id, arm, seed, directory, send):
    maximum = 1 if arm == "S" else 5
    _save(directory / "direct-started.json", {"run_id": run_id, "arm": arm,
           "maximum_calls": maximum, "tie_break_seed": seed, "instruction": DIRECT_INSTRUCTION})
    events = []
    for index in range(maximum):
        request = _direct_request(task, run_id, index)
        response = send(request)
        event = _terminal(request.attempt_id, response)
        _save(directory / f"direct-{index + 1}.json", {"request": asdict(request), "outcome": event})
        events.append(event)
        if isinstance(response, ModelFailure):
            break
    summary = _direct_summary(events, maximum, seed, reference)
    _save(directory / "direct-complete.json", summary)
    return summary


def _configuration(candidate, block, arm, selection):
    configs = {c.config_id: c for c in bank()}
    if arm in ("S", "S-k"):
        return None, None, None
    config = dense() if arm == "D" else configs[
        block["z_configuration"] if arm == "Z" else candidate["fixed_config_id"]
        if arm in ("F", "Fc", "Ff") else selection["spatial_q"]]
    rounds = selection["temporal_qst"] if arm == "Q-ST" else candidate["fixed_rounds"] if arm == "Q-TF" else 2
    failed = next(role for role in block["fault_permutation"] if role in config.roles) if arm in ("Qf", "Ff") else None
    return config, rounds, failed


def _row(candidate, block, slot, result, config, rounds, failed, run_id):
    return {key: block[key] for key in ("panel", "block_id", "draw_index", "task_id", "family_id")} | {
        "slot_id": slot["slot_id"], "arm": slot["arm"],
        **{k: result[k] for k in ("em", "f1", "cost_usd", "status", "call_count")},
        "configuration": config.config_id if config is not None else slot["arm"],
        "rounds": rounds, "failed_role": failed, "run_id": run_id,
        "provenance": {"execution_binding_sha256": execution_binding(candidate), "mode": candidate["mode"]}}


def _mas_result(path, config, task, reference, block):
    result = read_result(path, config, task, reference, family_id=block["family_id"], phase="holdout", repeat=block["draw_index"] + 1)
    if result.status not in ("completed", "model_failed") or result.cost_usd is None:
        raise StudyStop("slot is not terminal and completely billed")
    trace = read_journal(path, config)["trace"]
    return {"em": result.em, "f1": result.f1, "cost_usd": str(result.cost_usd),
            "status": "ok" if result.status == "completed" else "model_failure",
            "call_count": sum(e["kind"] == "started" for e in trace["events"])}, trace


def _inventory(folder):
    return {str(path.relative_to(folder)): file_hash(path) for path in sorted(folder.rglob("*"))
            if path.is_file() and path.parts[len(folder.parts)] != "receipts"}


def _provider_files(folder, index):
    """The adapter writes exactly these five files, also above index 99,999."""
    return {part: Path(folder) / "provider" / f"{index:05d}-{part}.json"
            for part in ("request", "response", "binding", "billing", "received")}


def _selection_identity(plan, block, kind):
    return {"plan_hash": plan["plan_hash"], "block_id": block["block_id"],
            "panel": block["panel"], "draw_index": block["draw_index"],
            "task_id": block["task_id"], "public_task_id": public_task_id(plan, block["task_id"]),
            "selector": kind}


def _check_selection_measurement(record, candidate, plan, block, kind, choice):
    if (record.get("schema") != "z50-selection-observation/v1"
            or record.get("identity") != _selection_identity(plan, block, kind)
            or record.get("status") != "completed" or record.get("error_type") is not None
            or record.get("choice") != choice):
        raise StudyStop("selection observation does not bind the exact block decision")
    validate_observation(record["process_observation"])
    detail = record.get("selector_record")
    if detail is None:
        if candidate["mode"] != "artificial_only" or record.get("detail_status") != "callback_without_detail":
            raise StudyStop("live selector observation is missing")
    else:
        fields = ("feature_and_encoder_ns", "score_and_choice_ns", "total_ns")
        if (record.get("detail_status") != "selector_record" or not isinstance(detail, dict)
                or any(type(detail.get(key)) is not int or detail[key] < 0 for key in fields)
                or detail["feature_and_encoder_ns"] + detail["score_and_choice_ns"] != detail["total_ns"]
                or not isinstance(detail.get("encoding"), dict)):
            raise StudyStop("invalid retained selector timing/encoder observation")
        if kind == "temporal" and (detail.get("task_id") != public_task_id(plan, block["task_id"])
                or type(detail.get("selection_index")) is not int or detail["selection_index"] < 1):
            raise StudyStop("temporal selector observation has a foreign task or selection index")


def _select_observed(callback, task, *, candidate, plan, block, kind, directory):
    """Save actual local cost with each fresh block; never change a Q choice."""
    owner = getattr(callback, "__self__", callback)
    records = getattr(owner, "selection_records", None)
    before = len(records) if isinstance(records, list) else None
    observation = ProcessObservation()

    def save(choice, error):
        record = {"schema": "z50-selection-observation/v1",
                  "identity": _selection_identity(plan, block, kind),
                  "status": "completed" if error is None else "failed",
                  "error_type": None if error is None else type(error).__name__,
                  "choice": choice, "process_observation": observation.finish(),
                  "detail_status": "callback_without_detail" if before is None else "selector_record",
                  "selector_record": deepcopy(records[-1]) if before is not None and len(records) == before + 1 else None}
        _save(directory / f"{kind}-measurement.json", record)
        return record

    try:
        choice = callback(task)
    except BaseException as error:
        try:
            save(None, error)
        except Exception as recording_error:
            error.add_note("selection observation recording failed: " + type(recording_error).__name__)
        raise
    record = save(choice, None)
    _check_selection_measurement(record, candidate, plan, block, kind, choice)
    return choice


def _inspect(candidate, plan, folder):
    """Recompute scores, vote decisions, call bodies and billing of a full prefix."""
    folder = Path(folder)
    budget = _budget(candidate, plan, folder, existing=True)
    blocks = _blocks(plan)
    started = sorted((folder / "blocks").glob("*/started.json"))
    complete = sorted((folder / "blocks").glob("*/complete.json"))
    if len(started) != len(complete) or len(complete) > len(blocks):
        raise StudyStop("partial block cannot continue")
    expected_files, attempts, rows = {"budget.jsonl"}, {}, []
    known = {p: Decimal(0) for p in ARMS}
    for number, complete_path in enumerate(complete):
        block = blocks[number]
        directory = folder / "blocks" / f"{number:06d}"
        if complete_path != directory / "complete.json" or started[number] != directory / "started.json":
            raise StudyStop("completed blocks are not a contiguous prefix")
        if read_json(started[number]) != {"block": block, "plan_hash": plan["plan_hash"]}:
            raise StudyStop("started block identity differs")
        proof = read_json(complete_path)
        if proof["block"] != block or proof["plan_hash"] != plan["plan_hash"]:
            raise StudyStop("complete block identity differs")
        for name, checksum in proof["evidence"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or file_hash(folder / relative) != checksum:
                raise StudyStop("block evidence differs")
        expected_files.update(proof["evidence"])
        expected_files.add(str(complete_path.relative_to(folder)))
        public = read_json(directory / "public.json")
        task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
        private = read_json(directory / "reference.json")
        reference = AnswerReference(private["task_id"], tuple(private["answers"]))
        if task.task_id != public_task_id(plan, block["task_id"]) or reference.task_id != task.task_id:
            raise StudyStop("public/reference task identity differs")
        selection = read_json(directory / "selection.json")
        if (set(selection) != {"spatial_q", "temporal_qst"}
                or selection["spatial_q"] not in {c.config_id for c in bank()}
                or block["panel"] == "T" and (type(selection["temporal_qst"]) is not int or selection["temporal_qst"] not in (1, 2))
                or block["panel"] != "T" and selection["temporal_qst"] is not None):
            raise StudyStop("saved Q decision is not a bound bank/round choice")
        for kind, choice in (("spatial", selection["spatial_q"]), ("temporal", selection["temporal_qst"])):
            if choice is not None:
                _check_selection_measurement(read_json(directory / f"{kind}-measurement.json"),
                                             candidate, plan, block, kind, choice)
        block_rows = []
        for slot in block["slots"]:
            arm = slot["arm"]
            sd = directory / arm
            config, rounds, failed = _configuration(candidate, block, arm, selection)
            run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
            if config is None:
                maximum, seed = (1, 0) if arm == "S" else (5, block["tie_break_seed"])
                if read_json(sd / "direct-started.json") != {"run_id": run_id, "arm": arm, "maximum_calls": maximum,
                    "tie_break_seed": seed, "instruction": DIRECT_INSTRUCTION}:
                    raise StudyStop("direct slot binding differs")
                samples = sorted(sd.glob("direct-[1-5].json"))
                events = []
                for i, path in enumerate(samples):
                    if path.name != f"direct-{i + 1}.json":
                        raise StudyStop("noncontiguous direct sampling")
                    sample = read_json(path)
                    request = _direct_request(task, run_id, i)
                    if sample["request"] != read_json_bytes(encoded(asdict(request))):
                        raise StudyStop("direct request differs from fixed short-answer contract")
                    event = sample["outcome"]
                    if request.attempt_id in attempts or event["attempt_id"] != request.attempt_id:
                        raise StudyStop("duplicate or foreign direct attempt")
                    attempts[request.attempt_id] = (request, event)
                    events.append(event)
                result = _direct_summary(events, maximum, seed, reference)
                if result != read_json(sd / "direct-complete.json"):
                    raise StudyStop("plurality, scoring or direct billing differs")
            else:
                result, trace = _mas_result(sd / "journal.jsonl", config, task, reference, block)
                if trace["run_id"] != run_id or trace["rounds"] != rounds or trace["failed_role"] != failed:
                    raise StudyStop("MAS run/round/fault binding differs")
                for event in trace["events"]:
                    if event["kind"] == "started":
                        request = Request(event["attempt_id"], task, event["role"], event["round"], event["instruction"],
                            tuple(Message(**m) for m in event["messages"]), event["max_output_tokens"])
                    elif event["kind"] in ("completed", "model_failed"):
                        if request.attempt_id in attempts or event["attempt_id"] != request.attempt_id:
                            raise StudyStop("duplicate or foreign MAS attempt")
                        attempts[request.attempt_id] = (request, event)
            row = _row(candidate, block, slot, result, config, rounds, failed, run_id)
            if read_json(sd / "result.json") != row:
                raise StudyStop("saved numeric slot differs")
            block_rows.append(row)
            known[block["panel"]] += money(row["cost_usd"])
        if block_rows != proof["rows"]:
            raise StudyStop("complete block lacks its exact fresh slots")
        rows.extend(block_rows)
    if len(attempts) != budget.calls or {k: v[1]["usage"] for k, v in attempts.items()} != dict(budget.settlements):
        raise StudyStop("call evidence does not reconcile with shared ledger")
    generations = set()
    for index, (attempt_id, usage) in enumerate(budget.settlements, 1):
        names = _provider_files(folder, index)
        request, event = attempts[attempt_id]
        raw = names["response"].read_bytes()
        billed, generation = decode_billing(raw)
        response = decode_outcome(raw, request.max_output_tokens, F01)
        if candidate["mode"] == "artificial_only":
            response = replace(response, usage=replace(response.usage, cost_source="synthetic"))
        if (names["request"].read_bytes() != encoded(payload(request, producer_limit=1024))
                or _terminal(attempt_id, response) != event or generation in generations
                or read_json(names["binding"]) != {"attempt_id": attempt_id, "request_sha256": file_hash(names["request"]),
                    "mode": "synthetic" if candidate["mode"] == "artificial_only" else "live"}
                or read_json(names["billing"]) != {"generation_id": generation, "usage": usage,
                    "response_sha256": file_hash(names["response"])}
                or read_json(names["received"]) != {"http_status": 200, "response_sha256": file_hash(names["response"])}
                or billed.cost_usd != money(usage["cost_usd"])):
            raise StudyStop("provider request, outcome or generation provenance differs")
        generations.add(generation)
        expected_files.update(str(p.relative_to(folder)) for p in names.values())
    evidence = _inventory(folder)
    if set(evidence) != expected_files or sum(known.values()) != budget.cost:
        raise StudyStop("unclaimed files or unclassified shared costs")
    state = {"execution_binding_sha256": execution_binding(candidate), "plan_hash": plan["plan_hash"],
             "completed_blocks": len(complete), "complete": len(complete) == len(blocks), "rows": rows,
             "budget": budget.snapshot(), "levels": budget_view(candidate, known),
             "generation_ids": sorted(generations), "evidence": evidence}
    state["state_sha256"] = canonical_hash(state)
    return state, budget


def read_json_bytes(value):
    from communication_pruning.failure_policy import strict_json
    return strict_json(value)


def _receipt_path(folder, state):
    return Path(folder) / "receipts" / f"{state['completed_blocks']:06d}-{state['state_sha256']}.json"


def _verify_receipt(folder, state):
    receipt = read_json(_receipt_path(folder, state))
    if receipt["state_sha256"] != state["state_sha256"]:
        raise StudyStop("checkpoint does not bind this exact full prefix")
    verify_archive(receipt["backup"], state["evidence"])


def inspect_study(candidate, plan, *, folder, control, clock):
    preflight(candidate, plan, control=control, clock=clock)
    with study_lock(control):
        _claim(candidate, plan, folder, control)
        state, _ = _inspect(candidate, plan, folder)
        return state


def checkpoint_study(candidate, plan, *, folder, control, clock, checkpoint):
    """Only audit and back up an already complete prefix; never finish a slot."""
    preflight(candidate, plan, control=control, clock=clock)
    with study_lock(control):
        _claim(candidate, plan, folder, control)
        state, _ = _inspect(candidate, plan, folder)
        path = _receipt_path(folder, state)
        if path.exists():
            _verify_receipt(folder, state)
            return state
        proof = checkpoint(deepcopy(state))
        verify_archive(proof, state["evidence"])
        _save(path, {"state_sha256": state["state_sha256"], "backup": proof})
        return state


def run_section(candidate, plan, *, folder, control, section_end, loader,
                spatial_selector, temporal_selector, transport, checkpoint, clock):
    """Run to exactly the next prebound hold, preserving every failure artifact."""
    dependencies = dict(loader=loader, spatial_selector=spatial_selector, temporal_selector=temporal_selector,
                        transport=transport, checkpoint=checkpoint)
    preflight(candidate, plan, control=control, clock=clock, dependencies=dependencies)
    folder = Path(folder)
    blocks = _blocks(plan)
    with study_lock(control):
        _claim(candidate, plan, folder, control, create=True)
        existing = (folder / "budget.jsonl").exists()
        if existing:
            state, budget = _inspect(candidate, plan, folder)
            prefix = state["completed_blocks"]
            _verify_receipt(folder, state)
            known = {p: money(v) for p, v in state["levels"]["known_by_panel_usd"].items()}
            generations = state["generation_ids"]
        else:
            if folder.exists() and any(folder.iterdir()):
                raise StudyStop("unrecognized existing study folder")
            prefix, generations, known = 0, [], {p: Decimal(0) for p in ARMS}
            budget = None
        later = [end for end in candidate["section_ends"] if end > prefix]
        if not later or type(section_end) is not int or section_end != later[0]:
            raise StudyStop("only the next unchanged control hold may run")
        runtime_guard(candidate, clock=clock, panel=blocks[prefix]["panel"])
        budget_view(candidate, known, panel=blocks[prefix]["panel"], reserve_calls=MAX_CALLS[blocks[prefix]["panel"]])
        if not existing:
            for name in ("blocks", "provider", "receipts"):
                (folder / name).mkdir(parents=True, exist_ok=True)
            budget = _budget(candidate, plan, folder, existing=False)
        adapter = StudyAdapter(folder / "provider", transport, budget,
                               synthetic=candidate["mode"] == "artificial_only", failure_policy=F01)
        adapter.generations.update(generations)
        for number in range(prefix, section_end):
            block = blocks[number]
            panel = block["panel"]
            runtime_guard(candidate, clock=clock, panel=panel)
            budget_view(candidate, known, panel=panel, reserve_calls=MAX_CALLS[panel])
            if budget.calls + MAX_CALLS[panel] > budget.max_calls:
                raise StudyStop("complete block exceeds remaining bound call count")
            directory = folder / "blocks" / f"{number:06d}"
            directory.mkdir()
            _save(directory / "started.json", {"block": block, "plan_hash": plan["plan_hash"]})
            first_call = budget.calls + 1
            task, reference = loader(block["task_id"])
            if (type(task) is not TaskInput or type(reference) is not AnswerReference
                    or task.task_id != public_task_id(plan, block["task_id"]) or reference.task_id != task.task_id):
                raise StudyStop("loader returned a foreign task or reference")
            _save(directory / "public.json", asdict(task))
            _save(directory / "reference.json", asdict(reference))
            q = _select_observed(spatial_selector, task, candidate=candidate, plan=plan,
                                 block=block, kind="spatial", directory=directory)
            qt = _select_observed(temporal_selector, task, candidate=candidate, plan=plan,
                                  block=block, kind="temporal", directory=directory) if panel == "T" else None
            if q not in {c.config_id for c in bank()} or panel == "T" and (type(qt) is not int or qt not in (1, 2)):
                raise StudyStop("selector returned a value outside the frozen bank")
            selection = {"spatial_q": q, "temporal_qst": qt}
            _save(directory / "selection.json", selection)

            def send(request):
                runtime_guard(candidate, clock=clock, panel=panel)
                current = dict(known)
                current[panel] += budget.cost - sum(known.values())
                budget_view(candidate, current, panel=panel, reserve_calls=1)
                return adapter(request)

            rows = []
            for slot in block["slots"]:
                runtime_guard(candidate, clock=clock, panel=panel)
                arm = slot["arm"]
                sd = directory / arm
                sd.mkdir()
                run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
                config, rounds, failed = _configuration(candidate, block, arm, selection)
                if config is None:
                    result = _direct(task, reference, run_id, arm, 0 if arm == "S" else block["tie_break_seed"], sd, send)
                else:
                    execute(task, config, send, rounds=rounds, failed_role=failed, run_id=run_id,
                            journal_path=sd / "journal.jsonl", producer_limit=1024, failure_policy=F01)
                    result, _ = _mas_result(sd / "journal.jsonl", config, task, reference, block)
                row = _row(candidate, block, slot, result, config, rounds, failed, run_id)
                _save(sd / "result.json", row)
                rows.append(row)
            files = [p for p in directory.rglob("*") if p.is_file()]
            for index in range(first_call, budget.calls + 1):
                files.extend(_provider_files(folder, index).values())
            _save(directory / "complete.json", {"block": block, "plan_hash": plan["plan_hash"], "rows": rows,
                  "evidence": {str(p.relative_to(folder)): file_hash(p) for p in files}})
            known[panel] += sum((money(row["cost_usd"]) for row in rows), Decimal(0))
            if sum(known.values()) != budget.cost:
                raise StudyStop("block costs differ from shared ledger")
        state, _ = _inspect(candidate, plan, folder)
        proof = checkpoint(deepcopy(state))
        verify_archive(proof, state["evidence"])
        _save(_receipt_path(folder, state), {"state_sha256": state["state_sha256"], "backup": proof})
        return state


def collect_panel(candidate, plan, panel, *, folder, control, clock):
    state = inspect_study(candidate, plan, folder=folder, control=control, clock=clock)
    _verify_receipt(folder, state)
    from .final_analysis import validate_rows
    rows = [row for row in state["rows"] if row["panel"] == panel]
    return validate_rows(plan, panel, rows)
