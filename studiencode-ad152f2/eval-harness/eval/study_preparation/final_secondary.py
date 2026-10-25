"""Z52 additive continuation of the unchanged R/T/F plan.

Offline tests use injected artificial dependencies; live mode requires an exact activation.
No loader, transport, credentials or network fallback is supplied here. The old
P metadata is adopted, never replayed or entered as new PhaseBudget settlements.
All writes and FileWitness transitions hold the ORIGINAL final-study-v1 lock.
A complete-machine rollback or hostile filesystem owner is outside this proof.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import math

from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput, Request, Message
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, decode_outcome
from communication_pruning.openrouter import encoded, payload, decode_billing
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.study import StudyAdapter, FileGuard, file_hash
from project.research_control.recovery import FileWitness
from . import final_execution as native
from . import final_preflight as gate
from .final_plan import ARMS, canonical_hash

StudyStop = gate.StudyStop
PANELS = ("R", "T", "F")
CLAIM = gate.NAMESPACE + ".secondary.claim.json"
ZERO = "0" * 64
HISTORICAL_ACCOUNTING = {
    "prior_known_usd": "14.39894681", "P_known_usd": "26.78059083",
    "protected_reserves_usd": "20.42", "unknown_original_reserve_usd": "0.56",
    "secondary_prior_usd": "0.22511349", "actual_total_cost_usd": None,
    "unknown_originals": ["01073Q", "048002Q", "z51-D072-resume-001:physical:011355F",
                          "z51-D073-resume-001:physical:004164F"],
}


def _need(condition, message):
    if not condition:
        raise StudyStop(message)


def _save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    native._save(path, value)


def _path(path):
    value = Path(path).absolute()
    _need(str(value) == str(value.resolve()) and not value.is_symlink(),
          "canonical paths without symlinks required")
    return value


def _all_files(folder):
    folder = Path(folder)
    result = {}
    for path in sorted(folder.rglob("*")):
        _need(not path.is_symlink(), "symlink in secondary evidence")
        if path.is_file():
            result[str(path.relative_to(folder))] = file_hash(path)
    return result


def additional_sources():
    """Exact new adapter and installed witness dependencies; no installation edit."""
    root = Path(__file__).resolve().parents[3]
    paths = [Path(__file__).resolve(), Path(__file__).with_name("final_secondary_operator.py")]
    paths += sorted((root / "project/research_control").glob("*.py"))
    return {str(p.resolve()): file_hash(p) for p in paths}


def accounting_view(predecessor, new_cost, *, reserve_calls=0, account_available=None):
    """One derived control view; the native new ledger remains the only new book."""
    a = predecessor["accounting"]
    _need(a == HISTORICAL_ACCOUNTING, "historical unknowns, costs or reserves changed")
    _need(isinstance(new_cost, Decimal) and new_cost.is_finite() and new_cost >= 0,
          "finite native new cost required")
    _need(type(reserve_calls) is int and reserve_calls >= 0, "invalid block reservation")
    overall = (Decimal("120") - gate.money(a["prior_known_usd"]) - gate.money(a["P_known_usd"])
               - gate.money(a["protected_reserves_usd"]) - gate.money(a["unknown_original_reserve_usd"]) - new_cost)
    secondary = Decimal("55.88") - gate.money(a["secondary_prior_usd"]) - new_cost
    reserve = Decimal("0.14") * reserve_calls
    _need(min(overall, secondary) >= reserve, "whole block exceeds cumulative study budget")
    if account_available is not None:
        _need(gate.money(account_available) >= reserve, "whole block exceeds current account coverage")
    return {"predecessor": deepcopy(a), "new_known_cost_usd": str(new_cost),
            "known_study_cost_usd": str(gate.money(a["P_known_usd"]) + new_cost),
            "known_project_cost_usd": str(gate.money(a["prior_known_usd"]) + gate.money(a["P_known_usd"]) + new_cost),
            "actual_total_cost_usd": None, "available_usd": {"overall": str(overall), "secondary": str(secondary)},
            "block_reservation_usd": str(reserve), "reservation_is_expense": False,
            "cost_inference": "four original P costs remain unknown; reserve is not an upper bound"}


def prepare_binding(candidate, plan, *, predecessor, folder, control, witness, owner, analysis_contract, activation=None):
    """Build a proposal, never a claim or a live authorization."""
    _need(isinstance(owner, str) and bool(owner.strip()), "one named executor required")
    return gate.seal({"schema": "z52-secondary/v1", "mode": candidate["mode"],
        "candidate_sha256": candidate["sha256"], "scientific_candidate_sha256": predecessor["scientific_candidate_sha256"], "plan_hash": plan["plan_hash"],
        "execution_binding_sha256": gate.execution_binding(candidate),
        "folder": str(_path(folder)), "control": str(_path(control)),
        "witness": str(_path(witness)), "owner": owner, "owner_generation": 1,
        "predecessor": deepcopy(predecessor), "source_files": additional_sources(),
        "analysis_contract": deepcopy(analysis_contract), "activation": deepcopy(activation)})


def _control_snapshot(control):
    return {p.name: file_hash(p) for p in sorted(Path(control).iterdir())
            if p.is_file() and p.name not in (gate.NAMESPACE + ".lock", CLAIM)}


def _check_binding(binding, candidate, plan, *, folder, control, clock, dependencies=None):
    gate._check_seal(binding)
    _need(binding.get("schema") == "z52-secondary/v1" and binding.get("mode") == candidate.get("mode")
          and binding["mode"] in ("artificial_only", "authorized_execution"), "specific secondary mode required")
    _need(binding["folder"] == str(_path(folder)) and binding["control"] == str(_path(control))
          and binding["control"] == candidate["control_directory"], "secondary output/control identity differs")
    _need(binding["candidate_sha256"] == candidate["sha256"] and binding["plan_hash"] == plan["plan_hash"]
          and binding["execution_binding_sha256"] == gate.execution_binding(candidate), "candidate/plan identity changed")
    _need(binding["owner_generation"] == 1 and isinstance(binding["owner"], str) and bool(binding["owner"].strip()),
          "owner transfer has no automatic recovery path")
    _need(binding["source_files"] == additional_sources(), "secondary or installed architecture sources changed")
    _preflight(binding, candidate, plan, control=control, clock=clock, dependencies=dependencies)
    prior = binding["predecessor"]
    _need(prior.get("schema") == "z52-adopted-P/v1" and prior.get("mode") == ("artificial_only" if binding["mode"] == "artificial_only" else "adopted_metadata")
          and prior.get("plan_hash") == plan["plan_hash"]
          and prior.get("scientific_candidate_sha256") == binding["scientific_candidate_sha256"]
          and prior.get("completed_blocks") == plan["counts"]["P"]
          and prior.get("rows") == 2 * plan["counts"]["P"]
          and prior.get("review_complete") is True and prior.get("backup_complete") is True,
          "complete reviewed and backed-up P predecessor required")
    for key in ("state", "analysis", "review", "backup"):
        gate.evidence_file(prior[key])
    _need(prior["control_snapshot"] == _control_snapshot(control), "original claims or STOP evidence changed")
    old_claim = gate.read_json(Path(control) / (gate.NAMESPACE + ".claim.json"))
    _need(old_claim.get("namespace") == gate.NAMESPACE and old_claim.get("plan_hash") == plan["plan_hash"]
          and old_claim.get("execution_binding_sha256") == prior["original_execution_binding_sha256"]
          and old_claim.get("folder") == prior["original_folder"]
          and old_claim["folder"] != binding["folder"], "old canonical claim does not bind adopted predecessor")
    accounting_view(prior, Decimal(0))
    _analysis_contract(binding, candidate, plan)
    _activation_gate(binding, candidate, plan, clock)
    # The original global control marks must include each panel boundary.
    offset = 0
    for panel in ARMS:
        offset += plan["counts"][panel]
        _need(offset in candidate["section_ends"], "original panel boundary missing from holds")


def _claim(binding, control, *, create=False):
    expected = {"namespace": gate.NAMESPACE, "binding_sha256": binding["sha256"],
                "folder": binding["folder"], "control": binding["control"],
                "owner": binding["owner"], "witness": binding["witness"]}
    path = Path(control) / CLAIM
    if path.exists():
        _need(gate.read_json(path) == expected, "secondary study already claimed by another binding/folder/owner")
    else:
        _need(create, "secondary claim missing")
        _save(path, expected)


def _blocks(plan):
    return [b for panel in PANELS for b in plan["panels"][panel]]


def _budget(binding, plan, folder, *, existing):
    levels = accounting_view(binding["predecessor"], Decimal(0))["available_usd"]
    return (PhaseBudget.read_completed if existing else PhaseBudget)(Path(folder) / "budget.jsonl",
        cap=min(gate.money(v) for v in levels.values()), reserve=Decimal("0.14"),
        max_calls=sum(gate.MAX_CALLS[p] * plan["counts"][p] for p in PANELS),
        binding=binding["sha256"], allow_synthetic=binding["mode"] == "artificial_only")


def _admissions(folder):
    result = {}
    files = sorted((Path(folder) / "admissions").glob("*.json"))
    for i, path in enumerate(files):
        _need(path.name == f"{i:08d}.json", "admission evidence gap")
        event = gate.read_json(path)
        token, status = event["action_id"], event["status"]
        _need(token == "request-" + canonical_hash(event["attempt_id"]), "admission identity changed")
        if status == "admitted":
            _need(token not in result, "duplicate secondary attempt")
        else:
            _need(status in ("settled", "unknown") and result.get(token) == "admitted", "invalid admission transition")
        result[token] = status
    return result


def _record_admission(folder, request, status):
    folder = Path(folder)
    index = len(list((folder / "admissions").glob("*.json")))
    _save(folder / "admissions" / f"{index:08d}.json", {"action_id": "request-" + canonical_hash(request.attempt_id),
          "attempt_id": request.attempt_id, "request_sha256": canonical_hash(asdict(request)), "status": status})


def _witness_binding(binding, folder, control):
    folder = Path(folder)
    stop = folder / "STOP.json"
    return {"incarnation": "secondary-" + binding["sha256"][:24],
        "activation_sha256": binding["sha256"], "stop_sha256": file_hash(stop) if stop.exists() else ZERO,
        "stop_active": stop.exists(), "owner_generation": binding["owner_generation"],
        "original_journal_sha256": canonical_hash({"predecessor": binding["predecessor"],
            "new_native_journal": file_hash(folder / "budget.jsonl")}),
        "admission_journal_sha256": canonical_hash({"files": _all_files(folder),
            "claim": file_hash(Path(control) / CLAIM), "original_control": _control_snapshot(control)}),
        "admissions": _section_states(folder)}


def _witness(binding):
    return FileWitness(binding["witness"], binding["folder"])


def _publish(binding, folder, control, generation):
    return _witness(binding).checkpoint(generation, _witness_binding(binding, folder, control))["generation"]


def _assert_current(binding, folder, control):
    record = _witness(binding).assert_current(_witness_binding(binding, folder, control))
    _need(not (Path(folder) / "STOP.json").exists(), "persistent secondary STOP")
    _need(all(s == "settled" for s in _section_states(folder).values()), "unresolved admitted section; no retry")
    return record["generation"]


def _inventory(folder):
    return {name: value for name, value in _all_files(folder).items()
            if name == "budget.jsonl" or name.startswith(("blocks/", "provider/"))}


def _inspect(binding, candidate, plan, folder):
    """Recompute scores, vote decisions, call bodies and billing of a full prefix."""
    folder = Path(folder)
    budget = _budget(binding, plan, folder, existing=True)
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
        if gate.read_json(started[number]) != {"block": block, "plan_hash": plan["plan_hash"]}:
            raise StudyStop("started block identity differs")
        proof = gate.read_json(complete_path)
        if proof["block"] != block or proof["plan_hash"] != plan["plan_hash"]:
            raise StudyStop("complete block identity differs")
        for name, checksum in proof["evidence"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or file_hash(folder / relative) != checksum:
                raise StudyStop("block evidence differs")
        expected_files.update(proof["evidence"])
        expected_files.add(str(complete_path.relative_to(folder)))
        public = gate.read_json(directory / "public.json")
        task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
        private = gate.read_json(directory / "reference.json")
        reference = AnswerReference(private["task_id"], tuple(private["answers"]))
        if task.task_id != native.public_task_id(plan, block["task_id"]) or reference.task_id != task.task_id:
            raise StudyStop("public/reference task identity differs")
        selection = gate.read_json(directory / "selection.json")
        if (set(selection) != {"spatial_q", "temporal_qst"}
                or selection["spatial_q"] not in {c.config_id for c in bank()}
                or block["panel"] == "T" and (type(selection["temporal_qst"]) is not int or selection["temporal_qst"] not in (1, 2))
                or block["panel"] != "T" and selection["temporal_qst"] is not None):
            raise StudyStop("saved Q decision is not a bound bank/round choice")
        for kind, choice in (("spatial", selection["spatial_q"]), ("temporal", selection["temporal_qst"])):
            if choice is not None:
                native._check_selection_measurement(gate.read_json(directory / f"{kind}-measurement.json"),
                                             candidate, plan, block, kind, choice)
        block_rows = []
        for slot in block["slots"]:
            arm = slot["arm"]
            sd = directory / arm
            config, rounds, failed = native._configuration(candidate, block, arm, selection)
            run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
            if config is None:
                maximum, seed = (1, 0) if arm == "S" else (5, block["tie_break_seed"])
                if gate.read_json(sd / "direct-started.json") != {"run_id": run_id, "arm": arm, "maximum_calls": maximum,
                    "tie_break_seed": seed, "instruction": gate.DIRECT_INSTRUCTION}:
                    raise StudyStop("direct slot binding differs")
                samples = sorted(sd.glob("direct-[1-5].json"))
                events = []
                for i, path in enumerate(samples):
                    if path.name != f"direct-{i + 1}.json":
                        raise StudyStop("noncontiguous direct sampling")
                    sample = gate.read_json(path)
                    request = native._direct_request(task, run_id, i)
                    if sample["request"] != native.read_json_bytes(encoded(asdict(request))):
                        raise StudyStop("direct request differs from fixed short-answer contract")
                    event = sample["outcome"]
                    if request.attempt_id in attempts or event["attempt_id"] != request.attempt_id:
                        raise StudyStop("duplicate or foreign direct attempt")
                    attempts[request.attempt_id] = (request, event)
                    events.append(event)
                result = native._direct_summary(events, maximum, seed, reference)
                if result != gate.read_json(sd / "direct-complete.json"):
                    raise StudyStop("plurality, scoring or direct billing differs")
            else:
                result, trace = native._mas_result(sd / "journal.jsonl", config, task, reference, block)
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
            row = native._row(candidate, block, slot, result, config, rounds, failed, run_id)
            if gate.read_json(sd / "result.json") != row:
                raise StudyStop("saved numeric slot differs")
            block_rows.append(row)
            known[block["panel"]] += gate.money(row["cost_usd"])
        if block_rows != proof["rows"]:
            raise StudyStop("complete block lacks its exact fresh slots")
        rows.extend(block_rows)
    if len(attempts) != budget.calls or {k: v[1]["usage"] for k, v in attempts.items()} != dict(budget.settlements):
        raise StudyStop("call evidence does not reconcile with shared ledger")
    generations = set()
    for index, (attempt_id, usage) in enumerate(budget.settlements, 1):
        names = native._provider_files(folder, index)
        request, event = attempts[attempt_id]
        raw = names["response"].read_bytes()
        billed, generation = decode_billing(raw)
        response = decode_outcome(raw, request.max_output_tokens, F01)
        if candidate["mode"] == "artificial_only":
            response = replace(response, usage=replace(response.usage, cost_source="synthetic"))
        if (names["request"].read_bytes() != encoded(payload(request, producer_limit=1024))
                or native._terminal(attempt_id, response) != event or generation in generations
                or gate.read_json(names["binding"]) != {"attempt_id": attempt_id, "request_sha256": file_hash(names["request"]),
                    "mode": "synthetic" if candidate["mode"] == "artificial_only" else "live"}
                or gate.read_json(names["billing"]) != {"generation_id": generation, "usage": usage,
                    "response_sha256": file_hash(names["response"])}
                or gate.read_json(names["received"]) != {"http_status": 200, "response_sha256": file_hash(names["response"])}
                or billed.cost_usd != gate.money(usage["cost_usd"])):
            raise StudyStop("provider request, outcome or generation provenance differs")
        generations.add(generation)
        expected_files.update(str(p.relative_to(folder)) for p in names.values())
    evidence = _inventory(folder)
    if set(evidence) != expected_files or sum(known.values()) != budget.cost:
        raise StudyStop("unclaimed files or unclassified shared costs")
    if set(_admissions(folder)) != {"request-" + canonical_hash(k) for k in attempts} or any(v != "settled" for v in _admissions(folder).values()):
        raise StudyStop("admissions do not reconcile with the only native ledger")
    state = {"execution_binding_sha256": gate.execution_binding(candidate), "plan_hash": plan["plan_hash"],
             "completed_blocks": plan["counts"]["P"] + len(complete), "secondary_completed_blocks": len(complete), "complete": len(complete) == len(blocks), "rows": rows,
             "budget": budget.snapshot(), "levels": accounting_view(binding["predecessor"], budget.cost),
             "generation_ids": sorted(generations), "evidence": evidence}
    state["state_sha256"] = canonical_hash(state)
    return state, budget



def _receipt_path(folder, state):
    return Path(folder) / "receipts" / f"{state['completed_blocks']:06d}-{state['state_sha256']}.json"


def _verify_receipt(folder, state):
    proof = gate.read_json(_receipt_path(folder, state))
    _need(proof["state_sha256"] == state["state_sha256"], "checkpoint state differs")
    gate.verify_archive(proof["backup"], state["evidence"])


def _checkpoint(folder, state, checkpoint):
    proof = checkpoint(deepcopy(state))
    gate.verify_archive(proof, state["evidence"])
    _save(_receipt_path(folder, state), {"state_sha256": state["state_sha256"], "backup": proof})


def _verify_panel_closeout(binding, candidate, plan, folder, panel):
    from .final_analysis import analyze_panel, validate_rows
    closure = gate.read_json(Path(folder) / "panels" / panel / "complete.json")
    _need(closure["binding_sha256"] == binding["sha256"] and closure["panel"] == panel,
          "panel closure binding changed")
    state, _ = _inspect(binding, candidate, plan, folder)
    rows = validate_rows(plan, panel, [r for r in state["rows"] if r["panel"] == panel])
    contract = _analysis_contract(binding, candidate, plan)
    expected = analyze_panel(plan, panel, rows, bootstrap_seed=contract["primary_bootstrap_seed"])
    path = Path(folder) / "panels" / panel / "analysis.json"
    _need(gate.read_json(path) == expected and closure["analysis_sha256"] == file_hash(path),
          "panel analysis differs from unchanged original analysis")
    _need(closure["evidence"] == _panel_evidence(plan, folder, panel),
          "closed panel immutable evidence set changed")
    _verify_ledger_prefix(folder, closure["ledger_prefix"])
    gate.verify_archive(closure["backup"], {**closure["evidence"],
        "budget.jsonl": closure["ledger_prefix"]["sha256"]})
    for name, checksum in closure["evidence"].items():
        _need(file_hash(Path(folder) / name) == checksum, "closed panel evidence changed")
    _verify_panel_remote(binding, panel, closure["analysis_sha256"], closure["backup"], closure["remote_backup"])
    review = gate.read_json(gate.evidence_file(closure["review"]))
    _need(review == {"binding_sha256": binding["sha256"], "panel": panel,
        "analysis_sha256": closure["analysis_sha256"], "reviewer": review.get("reviewer"),
        "not_implementation_author": True, "accepted": True}
        and isinstance(review["reviewer"], str) and bool(review["reviewer"].strip())
        and review["reviewer"] != binding["owner"], "separate panel review missing")
    return closure


def _analysis_contract(binding, candidate, plan):
    evidence = binding["analysis_contract"]
    contract = gate.read_json(gate.evidence_file(evidence))
    _need(contract["study_id"] == plan["study_id"] and contract["seed_base"] == plan["seed_base"]
          and contract["bootstrap_repetitions"] == 19999
          and contract["secondary_costs"] == "descriptive_only", "frozen analysis contract differs")
    if candidate["mode"] != "artificial_only":
        _need(evidence == candidate["operator"]["analysis_binding"]
              and candidate["source_files"].get(evidence["path"]) == evidence["sha256"],
              "original scientific analysis contract required")
    return contract


def _coverage(binding, coverage, *, clock, new_cost, reserve_calls):
    _need(isinstance(coverage, dict) and coverage.get("binding_sha256") == binding["sha256"],
          "current account observation for exact binding missing")
    if binding["mode"] != "artificial_only":
        _require_real_evidence(coverage)
    now = clock()
    _need(all(type(coverage.get(k)) in (int, float) and math.isfinite(coverage[k])
              for k in ("observed_epoch", "valid_until_epoch"))
          and coverage["observed_epoch"] <= now <= coverage["valid_until_epoch"], "account coverage stale")
    _need(coverage.get("origin") == ("artificial_fixture" if binding["mode"] == "artificial_only" else "current_account_read"),
          "wrong account observation origin")
    baseline = gate.money(coverage["native_cost_at_observation_usd"])
    _need(new_cost >= baseline, "account cost baseline is ahead of native ledger")
    available = gate.money(coverage["available_usd"]) - (new_cost - baseline)
    _need(available >= 0, "account coverage exhausted")
    return accounting_view(binding["predecessor"], new_cost, reserve_calls=reserve_calls, account_available=str(available))


def initialize(binding, candidate, plan, *, folder, control, clock):
    """Create one inert-to-live-gates execution. A failed partial init never resets."""
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        folder = Path(folder)
        _need(not folder.exists() or not any(folder.iterdir()), "new secondary folder must be empty")
        _claim(binding, control, create=True)
        for name in ("blocks", "provider", "receipts", "admissions", "panels", "sections"):
            (folder / name).mkdir(parents=True, exist_ok=True)
        _save(folder / "binding.json", binding)
        _budget(binding, plan, folder, existing=False)
        _witness(binding).initialize(_witness_binding(binding, folder, control))
        return {"binding_sha256": binding["sha256"], "next_block": plan["panels"]["R"][0]["block_id"]}


def inspect_study(binding, candidate, plan, *, folder, control, clock):
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        _assert_current(binding, folder, control)
        return _inspect(binding, candidate, plan, folder)[0]


def collect_panel(binding, candidate, plan, panel, *, folder, control, clock):
    from .final_analysis import validate_rows
    _need(panel in PANELS, "P is adopted and cannot be collected or dispatched here")
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        _assert_current(binding, folder, control)
        state, _ = _inspect(binding, candidate, plan, folder)
        _verify_receipt(folder, state)
        return validate_rows(plan, panel, [r for r in state["rows"] if r["panel"] == panel])


def analyze_panel(binding, candidate, plan, panel, *, folder, control, clock):
    """Read original complete rows and run the frozen analysis, under study lock."""
    from .final_analysis import analyze_panel as original_analysis, validate_rows
    _need(panel in PANELS, "secondary panel required")
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        generation = _assert_current(binding, folder, control)
        state, _ = _inspect(binding, candidate, plan, folder)
        _verify_receipt(folder, state)
        rows = validate_rows(plan, panel, [r for r in state["rows"] if r["panel"] == panel])
        contract = _analysis_contract(binding, candidate, plan)
        result = original_analysis(plan, panel, rows, bootstrap_seed=contract["primary_bootstrap_seed"])
        path = Path(folder) / "panels" / panel / "analysis.json"
        _save(path, result)
        _publish(binding, folder, control, generation)
        return {"path": str(path), "sha256": file_hash(path)}


def close_panel(binding, candidate, plan, panel, *, folder, control, clock, review, remote_backup):
    """Separate review and reread backup, required before crossing R/T/F boundary."""
    from .final_analysis import analyze_panel as original_analysis, validate_rows
    _need(panel in PANELS, "secondary panel required")
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        generation = _assert_current(binding, folder, control)
        state, _ = _inspect(binding, candidate, plan, folder)
        _verify_receipt(folder, state)
        rows = validate_rows(plan, panel, [r for r in state["rows"] if r["panel"] == panel])
        contract = _analysis_contract(binding, candidate, plan)
        path = Path(folder) / "panels" / panel / "analysis.json"
        _need(gate.read_json(path) == original_analysis(plan, panel, rows, bootstrap_seed=contract["primary_bootstrap_seed"]),
              "original panel analysis not complete")
        record = gate.read_json(gate.evidence_file(review))
        _need(record == {"binding_sha256": binding["sha256"], "panel": panel,
              "analysis_sha256": file_hash(path), "reviewer": record.get("reviewer"),
              "not_implementation_author": True, "accepted": True}
              and isinstance(record["reviewer"], str) and bool(record["reviewer"].strip())
              and record["reviewer"] != binding["owner"], "separate panel review required")
        prepared = gate.read_json(Path(folder) / "panels" / panel / "backup.json")
        _need(prepared["binding_sha256"] == binding["sha256"] and prepared["panel"] == panel
              and prepared["evidence"] == _panel_evidence(plan, folder, panel), "prepared panel backup differs")
        _verify_ledger_prefix(folder, prepared["ledger_prefix"])
        members = {**prepared["evidence"], "budget.jsonl": prepared["ledger_prefix"]["sha256"]}
        gate.verify_archive(prepared["backup"], members)
        _verify_panel_remote(binding, panel, file_hash(path), prepared["backup"], remote_backup)
        _save(Path(folder) / "panels" / panel / "complete.json", {
            "binding_sha256": binding["sha256"], "panel": panel, "analysis_sha256": file_hash(path),
            "evidence": prepared["evidence"], "ledger_prefix": prepared["ledger_prefix"],
            "backup": prepared["backup"], "remote_backup": remote_backup, "review": review})
        _publish(binding, folder, control, generation)
        return {"panel": panel, "closed": True}


def run_section(binding, candidate, plan, *, folder, control, section_end, coverage,
                loader, spatial_selector, temporal_selector, transport, checkpoint, clock):
    """Exactly the next original global hold; no P dispatch, retries or resumption."""
    dependencies = dict(loader=loader, spatial_selector=spatial_selector, temporal_selector=temporal_selector,
                        transport=transport, checkpoint=checkpoint)
    folder = Path(folder)
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock, dependencies=dependencies)
        _claim(binding, control)
        generation = _assert_current(binding, folder, control)
        state, budget = _inspect(binding, candidate, plan, folder)
        prefix, global_prefix = state["secondary_completed_blocks"], state["completed_blocks"]
        if prefix:
            _verify_receipt(folder, state)
            _verify_confirmation(binding, folder, state)
        later = [n for n in candidate["section_ends"] if n > global_prefix]
        _need(bool(later) and type(section_end) is int and section_end == later[0], "only next original global hold may run")
        blocks = _blocks(plan)
        end = section_end - plan["counts"]["P"]
        _need(prefix < end <= len(blocks) and blocks[prefix]["panel"] == blocks[end - 1]["panel"],
              "section must stay within the next original panel")
        panel = blocks[prefix]["panel"]
        if panel != "R":
            _verify_panel_closeout(binding, candidate, plan, folder, PANELS[PANELS.index(panel) - 1])
        _coverage(binding, coverage, clock=clock, new_cost=budget.cost, reserve_calls=gate.MAX_CALLS[panel])
        _need(gate.money(coverage["native_cost_at_observation_usd"]) == budget.cost,
              "section must start from current native account baseline")
        # Keep the observed coverage evidence immutable, as part of witness state.
        _save(folder / "coverage" / f"{global_prefix:06d}.json", coverage)
        _record_section(folder, section_end, "admitted")
        generation = _publish(binding, folder, control, generation)
        adapter = StudyAdapter(folder / "provider", transport, budget,
                               synthetic=candidate["mode"] == "artificial_only", failure_policy=F01)
        adapter.generations.update(state["generation_ids"])
        try:
            for number in range(prefix, end):
                block = blocks[number]
                _runtime(binding, candidate, clock=clock, panel=panel)
                _coverage(binding, coverage, clock=clock, new_cost=budget.cost, reserve_calls=gate.MAX_CALLS[panel])
                _need(budget.calls + gate.MAX_CALLS[panel] <= budget.max_calls, "whole block exceeds bound call count")
                directory = folder / "blocks" / f"{number:06d}"
                directory.mkdir()
                _save(directory / "started.json", {"block": block, "plan_hash": plan["plan_hash"]})
                first_call = budget.calls + 1
                task, reference = loader(block["task_id"])
                _need(type(task) is TaskInput and type(reference) is AnswerReference
                      and task.task_id == native.public_task_id(plan, block["task_id"])
                      and reference.task_id == task.task_id, "loader returned foreign task/reference")
                _save(directory / "public.json", asdict(task))
                _save(directory / "reference.json", asdict(reference))
                q = native._select_observed(spatial_selector, task, candidate=candidate, plan=plan,
                    block=block, kind="spatial", directory=directory)
                qt = native._select_observed(temporal_selector, task, candidate=candidate, plan=plan,
                    block=block, kind="temporal", directory=directory) if panel == "T" else None
                _need(q in {c.config_id for c in bank()} and (panel != "T" or type(qt) is int and qt in (1, 2)),
                      "selector outside frozen bank")
                selection = {"spatial_q": q, "temporal_qst": qt}
                _save(directory / "selection.json", selection)

                def send(request):
                    _runtime(binding, candidate, clock=clock, panel=panel)
                    _coverage(binding, coverage, clock=clock, new_cost=budget.cost, reserve_calls=1)
                    _need(request.attempt_id not in budget.ids, "duplicate logical request")
                    _record_admission(folder, request, "admitted")
                    try:
                        response = adapter(request)
                    except BaseException:
                        _record_admission(folder, request, "unknown")
                        raise
                    _record_admission(folder, request, "settled")
                    return response

                rows = []
                for slot in block["slots"]:
                    _runtime(binding, candidate, clock=clock, panel=panel)
                    arm = slot["arm"]
                    sd = directory / arm
                    sd.mkdir()
                    run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
                    config, rounds, failed = native._configuration(candidate, block, arm, selection)
                    if config is None:
                        result = native._direct(task, reference, run_id, arm,
                            0 if arm == "S" else block["tie_break_seed"], sd, send)
                    else:
                        execute(task, config, send, rounds=rounds, failed_role=failed, run_id=run_id,
                                journal_path=sd / "journal.jsonl", producer_limit=1024, failure_policy=F01)
                        result, _ = native._mas_result(sd / "journal.jsonl", config, task, reference, block)
                    row = native._row(candidate, block, slot, result, config, rounds, failed, run_id)
                    _save(sd / "result.json", row)
                    rows.append(row)
                files = [p for p in directory.rglob("*") if p.is_file()]
                for index in range(first_call, budget.calls + 1):
                    files.extend(native._provider_files(folder, index).values())
                _save(directory / "complete.json", {"block": block, "plan_hash": plan["plan_hash"], "rows": rows,
                    "evidence": {str(p.relative_to(folder)): file_hash(p) for p in files}})
            state, _ = _inspect(binding, candidate, plan, folder)
            _checkpoint(folder, state, checkpoint)
            _record_section(folder, section_end, "settled")
            _publish(binding, folder, control, generation)
            return state
        except BaseException as error:
            try:
                _save(folder / "STOP.json", {"binding_sha256": binding["sha256"],
                    "error_type": type(error).__name__, "message": str(error), "retry_allowed": False})
                _publish(binding, folder, control, generation)
            except BaseException as recording_error:
                error.add_note("STOP/witness recording failed; existing state remains inert: " + type(recording_error).__name__)
            raise


def _preflight(binding, candidate, plan, *, control, clock, dependencies=None):
    """Complete gate before any content loader/selector/transport is invoked."""
    gate.validate_plan(plan)
    gate._check_seal(candidate)
    artificial = candidate.get("mode") == "artificial_only"
    if (candidate.get("schema") != "z50-execution/v1" or candidate.get("namespace") != gate.NAMESPACE
            or candidate.get("plan_hash") != plan["plan_hash"] or candidate.get("bindings") != plan["bindings"]
            or candidate.get("direct_prompt") != gate.DIRECT_INSTRUCTION
            or candidate.get("control_directory") != str(Path(control).resolve())):
        raise StudyStop("study, prompt, metadata or control binding differs")
    if artificial:
        if (candidate.get("test_authorized") is not True or plan["mode"] != "artificial_only"
                or candidate.get("author_release") is not None
                or any(not r["task_id"].startswith("synthetic-") for r in plan["frame"])):
            raise StudyStop("artificial-only explicit test binding required")
    elif candidate.get("mode") != "authorized_execution" or candidate.get("test_authorized") is not False or plan["mode"] != "live_candidate":
        raise StudyStop("no specific execution authorization")
    files = candidate["source_files"]
    if not isinstance(files, dict) or not gate.required_source_paths() <= set(files) or any(not Path(p).is_absolute() for p in files):
        raise StudyStop("complete recoverable execution/analysis source binding required")
    documents = candidate["documents"]
    if not isinstance(documents, dict) or set(documents) != set(gate.DOCUMENTS):
        raise StudyStop("all rule/design/frame/exposure documents required")
    for key, value in documents.items():
        gate.evidence_file(value)
        if not artificial or key in plan["bindings"]:
            if plan["bindings"].get(key) != value["sha256"]:
                raise StudyStop("external plan/document hash differs")
    if gate.read_json(documents["source_manifest"]["path"]) != {"files": files}:
        raise StudyStop("source manifest does not bind exactly these files")
    if gate.read_json(gate.evidence_file(candidate["plan_evidence"])) != plan:
        raise StudyStop("recoverable saved plan differs")
    if gate.read_json(documents["frame_metadata"]["path"]) != plan["frame"]:
        raise StudyStop("metadata frame differs from the drawn frame")
    exposures = gate.read_json(documents["exposure_metadata"]["path"])
    if (exposures.get("schema") != "z50-exposure-metadata/v1"
            or not isinstance(exposures.get("all_documented_exposed_task_ids"), list)
            or not isinstance(exposures.get("all_documented_exposed_family_ids"), list)
            or exposures.get("holdout_task_overlap") != [] or exposures.get("holdout_family_overlap") != []
            or set(exposures["all_documented_exposed_task_ids"]) & {r["task_id"] for r in plan["frame"]}
            or set(exposures["all_documented_exposed_family_ids"]) & {r["family_id"] for r in plan["frame"]}):
        raise StudyStop("current exposure review does not clear this exact frame")
    inputs = exposures.get("input_sha256")
    if not isinstance(inputs, dict) or not artificial and not inputs:
        raise StudyStop("exposure original bindings missing")
    project = Path(__file__).resolve().parents[3]
    for name, checksum in inputs.items():
        path = str((project / name).resolve())
        if files.get(path) != checksum:
            raise StudyStop("exposure original missing from source/archive binding")
    runtime = gate.read_json(gate.evidence_file(candidate["runtime_manifest"]))
    if runtime != gate.runtime_identity():
        raise StudyStop("runtime differs from frozen manifest")
    gate.validate_endpoint(Path(gate.evidence_file(candidate["provider_evidence"])).read_bytes())
    if candidate["fixed_config_id"] not in {f"C{i:02}" for i in range(1, 15)} or type(candidate["fixed_rounds"]) is not int or candidate["fixed_rounds"] not in (1, 2):
        raise StudyStop("bound fixed spatial/time rules required")
    for key, expected in (("spatial_f", {"config_id": candidate["fixed_config_id"]}),
                          ("temporal_qtf", {"rounds": candidate["fixed_rounds"]})):
        rule = gate.read_json(documents[key]["path"])
        if not all(rule.get(k) == v for k, v in expected.items()):
            raise StudyStop("fixed rule differs from retained rule artifact")
    if not artificial:
        fixed_time = gate.read_json(documents["temporal_qtf"]["path"])
        if (fixed_time.get("raw_q_sha256") != documents["spatial_q"]["sha256"]
                or fixed_time.get("temporal_selector_sha256") != documents["temporal_qst"]["sha256"]):
            raise StudyStop("fixed temporal rule does not bind these exact Q rules")
    cal = candidate["calendar"]
    if (not isinstance(cal, dict) or set(cal) != {"start_epoch", "end_epoch", "maximum_duration_seconds", "origin"}
            or cal["origin"] != ("artificial_clock" if artificial else "author_bound")
            or any(type(cal[k]) not in (int, float) or not math.isfinite(cal[k]) for k in ("start_epoch", "end_epoch", "maximum_duration_seconds"))
            or not 0 < cal["end_epoch"] - cal["start_epoch"] <= cal["maximum_duration_seconds"]):
        raise StudyStop("absolute finite operating interval required")
    observed = candidate["provider_observation"]
    if (not isinstance(observed, dict) or set(observed) != {"origin", "observed_epoch"}
            or observed["origin"] != ("artificial_fixture" if artificial else "current_preflight")
            or type(observed["observed_epoch"]) not in (int, float) or not math.isfinite(observed["observed_epoch"])
            or not cal["start_epoch"] <= observed["observed_epoch"] <= clock() <= cal["end_epoch"]):
        raise StudyStop("current provider/tariff metadata observation missing")
    total = sum(plan["counts"].values())
    ends = candidate["section_ends"]
    if not isinstance(ends, list) or not ends or any(type(v) is not int or not 0 < v <= total for v in ends) or ends != sorted(set(ends)) or ends[-1] != total:
        raise StudyStop("complete prebound section limits required")
    budget = gate.read_json(gate.evidence_file(candidate["budget_evidence"]))
    if candidate["mode"] == "artificial_only":
        if budget != {"complete_nonoverlapping": True, "budget": candidate["budget"], "origin": "artificial_fixture"}:
            raise StudyStop("artificial budget evidence changed")
    else:
        if candidate["budget"].get("unresolved") is not True or budget != {
                "origin": "secondary_activation", "budget": candidate["budget"],
                "predecessor_accounting": binding["predecessor"]["accounting"],
                "actual_total_cost_usd": None}:
            raise StudyStop("current budget must explicitly preserve unresolved historical P costs")
    accounting_view(binding["predecessor"], Decimal(0))
    if dependencies is not None:
        if set(dependencies) != set(gate.DEPENDENCIES) or set(candidate["dependency_bindings"]) != set(gate.DEPENDENCIES):
            raise StudyStop("all explicit dependency bindings required")
        for key, callback in dependencies.items():
            identity = gate.dependency_identity(callback)
            if candidate["dependency_bindings"][key] != identity or {**files, **binding["source_files"]}.get(identity["path"]) != identity["sha256"]:
                raise StudyStop("injected dependency differs from bound source")
        if not artificial:
            # Live Q rules must use the already implemented frozen selectors.
            from communication_pruning.semantic_selection import SemanticSelector
            from .temporal import TemporalSelector
            for key, cls, doc in (("spatial_selector", SemanticSelector, "spatial_q"),
                                 ("temporal_selector", TemporalSelector, "temporal_qst")):
                method = dependencies[key]
                obj = getattr(method, "__self__", None)
                if type(obj) is not cls or method.__func__ is not cls.select or obj.to_dict() != gate.read_json(documents[doc]["path"]):
                    raise StudyStop("live Q must be the unchanged frozen selector")
    gate.runtime_guard(candidate, clock=clock)
    gate.verify_archive(candidate["source_backup"], gate.source_members(candidate))
    return {"mode": candidate["mode"], "execution_binding_sha256": gate.execution_binding(candidate),
            "live_evidence": not artificial, "study_frozen": not artificial}


def connection_hash(binding):
    """Author approval binds the exact proposal without a circular evidence hash."""
    return canonical_hash({k: v for k, v in binding.items() if k not in ("sha256", "activation")})


def _activation_gate(binding, candidate, plan, clock):
    if binding["mode"] == "artificial_only":
        _need(binding["activation"] is None, "artificial tests cannot carry live activation")
        return
    activation = gate.read_json(gate.evidence_file(binding["activation"]))
    _require_real_evidence(activation)
    _require_real_evidence(binding["predecessor"])
    _verify_live_predecessor(binding["predecessor"])
    _require_real_evidence(gate.read_json(gate.evidence_file(candidate["author_release"])))
    _need(activation.get("schema") == "z52-secondary-activation/v1"
          and activation.get("author") == "Jannik" and activation.get("explicit_authorization") is True
          and activation.get("send_enabled") is True and activation.get("study_frozen") is True
          and activation.get("connection_sha256") == connection_hash(binding)
          and activation.get("executor") == binding["owner"]
          and activation.get("panels") == list(PANELS)
          and isinstance(activation.get("approval_reference"), str) and bool(activation["approval_reference"].strip()),
          "specific author activation for exact secondary connection missing")
    # Reuse the original author/phase check as well as the secondary-specific one.
    for panel in PANELS:
        gate._release(candidate, panel)
    scientific = gate.read_json(gate.evidence_file(binding["predecessor"]["scientific_candidate"]))
    _need(binding["predecessor"]["scientific_candidate"]["sha256"] ==
          "05a2c6f3d2b44734c978f396fe9ee19984b5b6883d0b876c127cb3e4ea569d45",
          "only the actual Z50-NACHARBEIT scientific candidate may continue")
    for key in ("bindings", "source_files", "documents", "fixed_config_id", "fixed_rounds", "direct_prompt", "section_ends"):
        _need(candidate[key] == scientific[key], "scientific candidate field changed: " + key)
    expected_budget = deepcopy(scientific["budget"])
    expected_budget["unresolved"] = True
    _need(candidate["budget"] == expected_budget, "historical accounting caps/positions changed")
    _need(plan["plan_hash"] == "50d4c906a74daf4810511ddaec90218d26dd9897ccd9c9fb5f9cf1b532d23539"
          and plan["counts"] == {"P": 9040, "R": 2952, "T": 2952, "F": 2952}, "scientific plan changed")
    _need(candidate["calendar"] == {"start_epoch": 1789937789.191509, "end_epoch": 1791147389.191509,
          "maximum_duration_seconds": 1209600, "origin": "author_bound"}, "original shared calendar changed")
    _need(binding["predecessor"]["state_sha256"] == "960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6"
          and binding["predecessor"]["analysis"]["sha256"] == "fc4be29676749d7611d7c3f0d11e912193e4588609acb5d4734a15c387dcba65",
          "actual adopted P completion identity changed")
    _need(activation.get("data_rights") == {"public_question_context": True, "gold_local_only": True,
          "new_training_or_fit": False, "model": "google/gemini-2.5-flash-lite", "provider": "google-vertex/eu"},
          "explicit unchanged exposure rights required")
    _need(activation.get("account_policy") == "next_whole_block_covered_ongoing_topups_by_Jannik",
          "account coverage and ongoing funding responsibility must be explicit")
    rights = activation.get("backup_rights", {})
    _need(rights.get("private_destination") == "Jnooo-cloud/masterarbeit-mas-pruning"
          and rights.get("secondary_payload_explicitly_authorized") is True
          and rights.get("includes_questions_responses_local_references_costs_reviews") is True
          and isinstance(rights.get("approval_reference"), str) and bool(rights["approval_reference"].strip()),
          "secondary private backup rights not bound")
    for name in ("source_review", "runtime_review", "storage_power_review", "initial_backup", "extension_backup"):
        record = gate.read_json(gate.evidence_file(activation[name]))
        _require_real_evidence(record)
        _need(record.get("connection_sha256") == connection_hash(binding)
              and record.get("accepted") is True and record.get("executor") == binding["owner"]
              and type(record.get("checked_epoch")) in (int, float)
              and type(record.get("valid_until_epoch")) in (int, float)
              and math.isfinite(record["checked_epoch"]) and math.isfinite(record["valid_until_epoch"])
              and candidate["calendar"]["start_epoch"] <= record["checked_epoch"] <= clock() <= record["valid_until_epoch"]
              <= candidate["calendar"]["end_epoch"], "missing or stale actual activation input: " + name)
        if name == "initial_backup":
            _need(record.get("destination") == rights["private_destination"]
                  and record.get("full_remote_reread") is True
                  and record.get("archive_sha256") == candidate["source_backup"]["sha256"]
                  and record.get("members") == candidate["source_backup"]["members"],
                  "exact start archive lacks bound remote reread")
        if name == "extension_backup":
            _verify_extension_backup(binding, record)
        if name == "source_review":
            _need(record.get("reviewer") != binding["owner"] and isinstance(record.get("reviewer"), str)
                  and record.get("not_implementation_author") is True
                  and record.get("additive_sources") == binding["source_files"], "separate exact implementation review missing")
    marker = gate.read_json(gate.evidence_file(activation["architecture_installation"]))
    _need(activation["architecture_installation"]["sha256"] ==
          "0d628ac1b175b0fc5cf630e2511de8a25020c9bc432d31db055c43f51fc158c4", "installed architecture identity changed")
    # Reading the bound marker does not toggle any of its offline installation flags.
    _need(isinstance(marker, dict), "installation metadata unavailable")


def _section_states(folder):
    """Bounded witness admissions: original control sections, not every model call.

    A whole section is admitted before its first mutation/dispatch. Any crash or
    unknown during it prevents reentry: the witness is stale and/or the section
    remains admitted. Native per-request journal and admission files retain the
    finer proof. No continuation from an admitted section is implemented.
    """
    result = {}
    for i, path in enumerate(sorted((Path(folder) / "sections").glob("*.json"))):
        _need(path.name == f"{i:06d}.json", "section admission gap")
        event = gate.read_json(path)
        token = event["section_id"]
        _need(isinstance(token, str) and token.startswith("section-"), "invalid section identity")
        if event["status"] == "admitted":
            _need(token not in result, "duplicate section admission")
        else:
            _need(event["status"] == "settled" and result.get(token) == "admitted", "invalid section completion")
        result[token] = event["status"]
    return result


def _record_section(folder, section_end, status):
    path = Path(folder) / "sections"
    index = len(list(path.glob("*.json")))
    _save(path / f"{index:06d}.json", {"section_id": "section-" + str(section_end), "status": status})


def _verify_confirmation(binding, folder, state):
    proof = gate.read_json(Path(folder) / "confirmations" / f"{state['completed_blocks']:06d}.json")
    for name in ("review", "backup"):
        value = gate.read_json(gate.evidence_file(proof[name]))
        if binding["mode"] != "artificial_only":
            _require_real_evidence(value)
        _need(value.get("binding_sha256") == binding["sha256"] and value.get("state_sha256") == state["state_sha256"]
              and value.get("accepted") is True, "exact hold confirmation missing")
        if name == "review":
            _need(value.get("not_implementation_author") is True and isinstance(value.get("reviewer"), str)
                  and bool(value["reviewer"].strip()) and value["reviewer"] != binding["owner"], "separate hold review required")
        else:
            receipt = gate.read_json(_receipt_path(folder, state))
            _need(value.get("archive_sha256") == receipt["backup"]["sha256"]
                  and value.get("full_reread") is True and value.get("members") == state["evidence"]
                  and value.get("destination") == ("artificial_local" if binding["mode"] == "artificial_only"
                        else "Jnooo-cloud/masterarbeit-mas-pruning"), "exact hold backup confirmation missing")
    return proof


def confirm_hold(binding, candidate, plan, *, folder, control, clock, review, backup):
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        generation = _assert_current(binding, folder, control)
        state, _ = _inspect(binding, candidate, plan, folder)
        _verify_receipt(folder, state)
        path = Path(folder) / "confirmations" / f"{state['completed_blocks']:06d}.json"
        # Validate before publishing; failure remains visible and cannot auto-retry.
        _save(path, {"review": review, "backup": backup})
        _verify_confirmation(binding, folder, state)
        _publish(binding, folder, control, generation)
        return state["state_sha256"]


def _runtime(binding, candidate, *, clock, panel):
    gate.runtime_guard(candidate, clock=clock, panel=panel)
    FileGuard(binding["source_files"])()
    _need(binding["predecessor"]["control_snapshot"] == _control_snapshot(binding["control"]),
          "original control changed during secondary dispatch")
    _need(not (Path(binding["folder"]) / "STOP.json").exists(), "persistent STOP before request")
    _activation_gate(binding, candidate, {"plan_hash": binding["plan_hash"],
        "counts": {"P": 9040, "R": 2952, "T": 2952, "F": 2952}}, clock)


def _verify_extension_backup(binding, record):
    """Reread every additive/installed dependency byte, plus bind remote receipt.

    The remote record is evidence supplied by the sole executor, not a network
    check or an authentication mechanism. The local archive is actually opened
    and every member is hashed here; a hash-only source list cannot pass.
    """
    if binding["mode"] != "artificial_only":
        _require_real_evidence(record)
    expected = {f"extension-{index:04d}": checksum
                for index, (_, checksum) in enumerate(sorted(binding["source_files"].items()))}
    _need(record.get("source_files") == binding["source_files"],
          "extension backup source mapping differs")
    archive = record.get("local_archive")
    gate.verify_archive(archive, expected)
    remote = record.get("remote_receipt", {})
    _need(remote.get("destination") == "Jnooo-cloud/masterarbeit-mas-pruning"
          and remote.get("archive_sha256") == archive["sha256"]
          and remote.get("members") == expected and remote.get("full_remote_reread") is True,
          "extension source archive lacks exact remote reread receipt")
    return expected


def _panel_evidence(plan, folder, panel):
    """Only immutable records belonging to this complete panel, never its live ledger."""
    folder = Path(folder)
    evidence = {}
    for index, block in enumerate(_blocks(plan)):
        if block["panel"] != panel:
            continue
        complete = folder / "blocks" / f"{index:06d}" / "complete.json"
        proof = gate.read_json(complete)
        _need(proof["block"] == block and proof["plan_hash"] == plan["plan_hash"],
              "panel evidence does not match original complete block")
        evidence.update(proof["evidence"])
        evidence[str(complete.relative_to(folder))] = file_hash(complete)
    analysis = folder / "panels" / panel / "analysis.json"
    evidence[str(analysis.relative_to(folder))] = file_hash(analysis)
    _need("budget.jsonl" not in evidence, "panel records must not freeze the growing native ledger")
    return evidence


def _verify_ledger_prefix(folder, prefix):
    """Accept append-only new settlements, reject any change to the closed prefix."""
    _need(isinstance(prefix, dict) and set(prefix) == {"bytes", "sha256"}
          and type(prefix["bytes"]) is int and prefix["bytes"] > 0,
          "exact closed ledger prefix required")
    with (Path(folder) / "budget.jsonl").open("rb") as stream:
        original = stream.read(prefix["bytes"])
    _need(len(original) == prefix["bytes"] and original.endswith(b"\n")
          and sha256(original).hexdigest() == prefix["sha256"],
          "closed panel native ledger prefix changed")
    return prefix


def _require_real_evidence(record):
    """Reject explicit artificial provenance; absence of it is not authorship proof."""
    if isinstance(record, dict):
        for key, value in record.items():
            _need(not (key in ("artificial_only", "synthetic", "test_authorized") and value is True),
                  "artificial evidence cannot activate a real study")
            _need(not (key in ("mode", "origin") and isinstance(value, str)
                      and (value.startswith(("artificial", "synthetic")) or value == "test_fixture")),
                  "artificial evidence cannot activate a real study")
            _require_real_evidence(value)
    elif isinstance(record, list):
        for value in record:
            _require_real_evidence(value)


def _verify_panel_remote(binding, panel, analysis_sha256, backup, remote_evidence):
    record = gate.read_json(gate.evidence_file(remote_evidence))
    if binding["mode"] != "artificial_only":
        _require_real_evidence(record)
    _need(record.get("binding_sha256") == binding["sha256"] and record.get("panel") == panel
          and record.get("analysis_sha256") == analysis_sha256
          and record.get("archive_sha256") == backup["sha256"] and record.get("members") == backup["members"]
          and record.get("full_reread") is True and record.get("accepted") is True
          and record.get("destination") == ("artificial_local" if binding["mode"] == "artificial_only"
              else "Jnooo-cloud/masterarbeit-mas-pruning"), "exact panel analysis backup lacks external reread")
    return record


def prepare_panel_backup(binding, candidate, plan, panel, *, folder, control, clock, checkpoint):
    """Freeze/reread the exact analyzed panel archive before its separate upload."""
    from .final_analysis import analyze_panel as original_analysis, validate_rows
    _need(panel in PANELS, "secondary panel required")
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        generation = _assert_current(binding, folder, control)
        state, _ = _inspect(binding, candidate, plan, folder)
        _verify_receipt(folder, state)
        rows = validate_rows(plan, panel, [r for r in state["rows"] if r["panel"] == panel])
        contract = _analysis_contract(binding, candidate, plan)
        path = Path(folder) / "panels" / panel / "analysis.json"
        _need(gate.read_json(path) == original_analysis(plan, panel, rows, bootstrap_seed=contract["primary_bootstrap_seed"]),
              "original panel analysis not complete")
        evidence = _panel_evidence(plan, folder, panel)
        raw_ledger = (Path(folder) / "budget.jsonl").read_bytes()
        ledger_prefix = {"bytes": len(raw_ledger), "sha256": sha256(raw_ledger).hexdigest()}
        members = {**evidence, "budget.jsonl": ledger_prefix["sha256"]}
        package = {**state, "evidence": members}
        package.pop("state_sha256")
        package["state_sha256"] = canonical_hash(package)
        proof = checkpoint(deepcopy(package))
        gate.verify_archive(proof, members)
        record = {"binding_sha256": binding["sha256"], "panel": panel,
            "analysis_sha256": file_hash(path), "evidence": evidence, "ledger_prefix": ledger_prefix, "backup": proof}
        _save(Path(folder) / "panels" / panel / "backup.json", record)
        _publish(binding, folder, control, generation)
        return record


# These are the existing reviewed metadata bytes, not reconstructed P answers.
# The live wrapper always uses these identities; tests do not replace them.
_LIVE_P_METADATA = {
    "state": ("operation/remote-holds/009040-960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6.json",
              "2bc3f7316167ae5015ea64e76c0c8745251c0aee9c366bd068fc0e7a17e41f3e"),
    "backup": ("operation/remote-holds/009040-960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6.remote.json",
               "6d18de2b404f3ca1967ba95b8b9222c6927fd1b8c9d4dbf83d79ee0f8915d88b"),
    "review": ("root/abschluss-2026-09-23/ROOT-FINAL-ACCEPTANCE.json",
               "4218bcf7c7a37a35314b3dc8d4474fbafc32b2cf5f29d9ca7d87d1f40eb585f7"),
    "original_report": ("root/abschluss-2026-09-23/ROOT-EVIDENCE-CHECK.json",
               "f2517ec58d8614cbd9294a9d6a0dc5bd4dc5a4e913517ef23cc7135b5e45cf4f"),
    "status": ("operation/starter/STATUS.json",
               "f0c5606ee28b98b8e7de545a8128bafbd8a6ecd679e2495e648f7e89aa79b2b3"),
    "analysis": ("operation/P-ANALYSIS.json",
                 "fc4be29676749d7611d7c3f0d11e912193e4588609acb5d4734a15c387dcba65"),
    "analysis_backup": ("operation/P-ANALYSIS-REMOTE.json",
                        "9d49cd1b3edf871a04b7adbf289b5ac21a8ab5950dd91f98c4799d907392c646"),
}


def _verify_live_predecessor(prior):
    """Exact saved metadata identities plus semantic links; no raw P reconstruction."""
    root = Path(__file__).resolve().parent.parent / "runs/Z51-RETRY-EINZELERSATZ-001"
    records = {}
    for key, (relative, checksum) in _LIVE_P_METADATA.items():
        expected = {"path": str(root / relative), "sha256": checksum}
        _need(prior.get(key) == expected, "actual reviewed P metadata identity differs: " + key)
        gate.evidence_file(expected)
        if key != "analysis":
            records[key] = gate.read_json(expected["path"])
            _require_real_evidence(records[key])
    _verify_predecessor_metadata_links(prior, records)


def _verify_predecessor_metadata_links(prior, records):
    """Pure link checker shared with invented fixtures; not a live identity override."""
    state, backup, review, report, status, analysis_backup = (
        records[k] for k in ("state", "backup", "review", "original_report", "status", "analysis_backup"))
    _need(state.get("schema") == "z51-resume-remote-hold/v1"
          and state.get("state_sha256") == prior["state_sha256"]
          and state.get("completed_blocks") == prior["completed_blocks"]
          and prior["rows"] == 2 * state["completed_blocks"]
          and state.get("known_cost_usd") == prior["accounting"]["P_known_usd"]
          and state.get("original_unknown_cost_preserved") is True,
          "adopted P state/count/cost is disconnected from saved metadata")
    unknowns = state.get("unknown_attempts")
    _need(isinstance(unknowns, list) and len(unknowns) == len(prior["accounting"]["unknown_originals"])
          and len({u.get("physical_attempt_id") for u in unknowns}) == len(unknowns)
          and all(isinstance(u.get("physical_attempt_id"), str) and u["physical_attempt_id"]
                  and u.get("provider_cost_usd") is None for u in unknowns)
          and sum((gate.money(u["reservation_usd"]) for u in unknowns), Decimal(0))
              == gate.money(prior["accounting"]["unknown_original_reserve_usd"]),
          "saved P unknown originals or held reserves differ")
    for receipt, evidence in ((backup, prior["state"]), (analysis_backup, prior["analysis"])):
        _need(receipt.get("verified") is True and receipt.get("repository") == "Jnooo-cloud/masterarbeit-mas-pruning"
              and receipt.get("sha256") == evidence["sha256"] and receipt.get("original_path") == evidence["path"],
              "saved P backup does not bind its exact metadata/analysis file")
    _need(review.get("schema") == "offline-P-closeout-adjudication/v1"
          and review.get("original_report_sha256") == prior["original_report"]["sha256"]
          and review.get("original_report_preserved") is True
          and review.get("other_nine_checks_passed") is True
          and review.get("passed_with_documented_audit_scope_correction") is True
          and review.get("actual_live_paths") == {"operation/BACKUP-CLEANUP-BLOCK.json": False, "live/STOP.json": False},
          "saved P adjudication does not accept this exact preserved audit")
    _need(report.get("schema") == "offline-P-closeout-audit/v1" and report.get("passed") is False,
          "preserve the original limited audit rather than inventing a full pass")
    checks = {c["criterion"]: c for c in report["checks"]}
    _need(len(checks) == len(report["checks"])
          and all(c["passed"] is True for key, c in checks.items() if key != "no_current_stop_or_cleanup_block")
          and checks["no_current_stop_or_cleanup_block"]["passed"] is False,
          "P adjudication cannot conceal another failed audit criterion")
    _need(checks["terminal_P9040"]["detail"]["status"] == "complete"
          and checks["terminal_P9040"]["detail"]["completed_blocks"] == state["completed_blocks"]
          and checks["final_hold_identity"]["detail"] == {"state_sha256": state["state_sha256"], "known_cost_usd": state["known_cost_usd"]}
          and checks["saved_analysis_identity"]["detail"]["sha256"] == prior["analysis"]["sha256"]
          and checks["four_unknown_original_costs_retained"]["detail"] == {
              "count": len(unknowns), "actual_total_cost_usd": None, "reserve_is_expense_or_upper_bound": False},
          "P audit does not refer to this state, analysis and conditional accounting")
    _need(status.get("status") == "complete" and status.get("completed_blocks") == state["completed_blocks"]
          and status.get("activation_sha256") == state.get("activation_sha256")
          and isinstance(state.get("activation_sha256"), str) and bool(state["activation_sha256"])
          and status.get("analysis", {}).get("path") == prior["analysis"]["path"]
          and status["analysis"].get("sha256") == prior["analysis"]["sha256"]
          and status["analysis"].get("remote") == analysis_backup
          and status["analysis"].get("cost_inference_is_conditional") is True,
          "P terminal operator/analysis status is disconnected from the adopted hold")
    return {"state_sha256": state["state_sha256"], "completed_blocks": state["completed_blocks"],
            "scope": "adopted reviewed metadata only; no new raw or remote verification"}
