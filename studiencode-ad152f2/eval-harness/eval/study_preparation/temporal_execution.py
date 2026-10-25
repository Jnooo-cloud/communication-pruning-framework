"""Z45 dependency-injected temporal execution; no keys, network or CLI.

A candidate is never a release. Actual execution additionally needs an external
author release binding the complete contract, provider/calendar and backup.
All Z45 executions use artificial dependencies only.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile
import fcntl
import json
import math

from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference, digest as data_digest
from communication_pruning.evaluation import read_result
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, strict_json
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import (MODEL, PROVIDER, decode_billing,
                                              encoded, save_new, validate_endpoint)
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.study import FileGuard, StudyAdapter, file_hash
from .temporal import digest, validate_temporal_plan

NAMESPACE = "temporal-development-v1"
PROTECTED = {"planning-reserve": "20.00", "old-reserve-028": "0.28", "old-reserve-014": "0.14"}


class TemporalStop(RuntimeError):
    pass


def seal(value):
    result = deepcopy(value)
    result.pop("sha256", None)
    result["sha256"] = digest(result)
    return result


def _check_seal(value):
    if not isinstance(value, dict) or value.get("sha256") != digest({k: v for k, v in value.items() if k != "sha256"}):
        raise TemporalStop("changed candidate or evidence hash")


def _money(value):
    if not isinstance(value, str):
        raise TemporalStop("explicit decimal string required")
    result = Decimal(value)
    if not result.is_finite() or result < 0:
        raise TemporalStop("finite nonnegative amount required")
    return result


def prepare_candidate(plan, *, source_files, phase_cap="2.00", pair_headroom="1.54"):
    """Metadata-only proposal. Budget baseline, calendar and release remain absent."""
    _check_seal(plan)
    return seal({"schema": "z45-temporal-candidate/v1", "namespace": NAMESPACE,
                 "authorized": False, "test_authorized": False, "mode": "not_authorized",
                 "parameters_status": "unaccepted_proposal", "plan_sha256": plan["sha256"],
                 "metadata_bindings": deepcopy(plan["source_bindings"]),
                 "source_files": dict(source_files), "source_backup": None,
                 "author_release": None, "control_directory": None,
                 "provider_evidence": None, "calendar": None,
                 "calendar_contract": {"status": "unaccepted_proposal", "maximum_duration_seconds": 14400},
                 "budget": {"overall_cap_usd": "120.00", "secondary_cap_usd": "55.88",
                            "phase_cap_proposal_usd": phase_cap, "pair_headroom_proposal_usd": pair_headroom,
                            "per_call_reserve_usd": "0.14", "max_calls": 1100,
                            "positions_excluding_current_phase": None,
                            "unresolved_current_phase": False, "unresolved_other_positions": False},
                 "section_ends_proposal": [1, 10, 40, 70, 100],
                 "pending": ["author_phase_and_content_release", "accepted_phase_cap",
                             "actual_global_and_shared_budget_positions", "active_calendar",
                             "current_provider_evidence", "source_and_runtime_backup",
                             "separate_start_review", "explicit_transport_and_loader_binding"]})


def execution_binding(candidate):
    """Noncircular external approval target; backup and approval are checked separately."""
    return digest({k: v for k, v in candidate.items()
                   if k not in ("sha256", "source_backup", "author_release")})


def budget_view(candidate, phase_known, *, pending=Decimal(0), require_pair=False):
    """Each position once at its own level; commitments mean remaining, not caps."""
    b = candidate["budget"]
    if b["overall_cap_usd"] != "120.00" or b["secondary_cap_usd"] != "55.88":
        raise TemporalStop("D063 global/shared caps changed")
    cap = _money(b["phase_cap_proposal_usd"])
    reserve = _money(b["per_call_reserve_usd"])
    headroom = _money(b["pair_headroom_proposal_usd"])
    if reserve != Decimal("0.14") or headroom < 11 * reserve or b["max_calls"] != 1100:
        raise TemporalStop("call/reservation contract does not cover the complete pair")
    if (not isinstance(phase_known, Decimal) or not phase_known.is_finite() or phase_known < 0
            or not isinstance(pending, Decimal) or not pending.is_finite() or pending < 0
            or b["unresolved_current_phase"] is not False
            or b["unresolved_other_positions"] is not False or pending != 0):
        raise TemporalStop("unresolved phase costs or invalid phase accounting")
    positions = b["positions_excluding_current_phase"]
    if not isinstance(positions, list):
        raise TemporalStop("actual global/shared budget positions still missing")
    ids, protected = set(), {}
    overall_other = secondary_other = Decimal(0)
    for p in positions:
        if set(p) != {"id", "bucket", "known_usd", "remaining_commitment_usd", "protected"}:
            raise TemporalStop("explicit nonoverlapping budget position required")
        if not isinstance(p["id"], str) or not p["id"] or p["id"] in ids or p["id"] == NAMESPACE:
            raise TemporalStop("duplicate or current-phase budget position")
        ids.add(p["id"])
        if p["bucket"] not in ("overall_only", "secondary") or type(p["protected"]) is not bool:
            raise TemporalStop("invalid budget bucket")
        known, remaining = _money(p["known_usd"]), _money(p["remaining_commitment_usd"])
        if p["protected"]:
            protected[p["id"]] = p
        overall_other += known + remaining
        if p["bucket"] == "secondary":
            secondary_other += known + remaining
    if set(protected) != set(PROTECTED):
        raise TemporalStop("all three protected reserves must remain explicit")
    for key, amount in PROTECTED.items():
        p = protected[key]
        if p["bucket"] != "overall_only" or _money(p["known_usd"]) != 0 or _money(p["remaining_commitment_usd"]) != Decimal(amount):
            raise TemporalStop("protected reserve cannot be spent or moved")
    available = {"overall": Decimal("120.00") - overall_other - phase_known,
                 "secondary": Decimal("55.88") - secondary_other - phase_known,
                 "phase": cap - phase_known}
    minimum = headroom if require_pair else Decimal(0)
    if any(value < minimum for value in available.values()):
        raise TemporalStop("insufficient headroom at overall, secondary or phase level")
    return {"phase_known_usd": str(phase_known), "overall_other_usd": str(overall_other),
            "secondary_other_usd": str(secondary_other),
            "available_usd": {k: str(v) for k, v in available.items()},
            "pair_headroom_is_expense": False}


def _archive(evidence, expected):
    if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256", "members"}:
        raise TemporalStop("explicit archive path/hash/member evidence required")
    if evidence["members"] != expected or file_hash(evidence["path"]) != evidence["sha256"]:
        raise TemporalStop("archive binding changed")
    with ZipFile(evidence["path"]) as z:
        if len(z.namelist()) != len(expected) or set(z.namelist()) != set(expected):
            raise TemporalStop("archive member set differs")
        from hashlib import sha256
        if any(sha256(z.read(name)).hexdigest() != checksum for name, checksum in expected.items()):
            raise TemporalStop("archive failed complete reread")


def _runtime(candidate, plan, *, clock, source_archive=False):
    _check_seal(candidate)
    if candidate.get("schema") != "z45-temporal-candidate/v1" or candidate.get("namespace") != NAMESPACE:
        raise TemporalStop("unknown execution contract")
    artificial = candidate.get("mode") == "artificial_only"
    if artificial:
        if candidate.get("authorized") is not False or candidate.get("test_authorized") is not True:
            raise TemporalStop("explicit artificial test binding required")
    elif (candidate.get("mode") != "authorized_execution" or candidate.get("authorized") is not True
          or candidate.get("test_authorized") is not False or candidate.get("parameters_status") != "accepted"):
        raise TemporalStop("no bound execution authorization")
    if candidate.get("plan_sha256") != plan["sha256"] or candidate.get("metadata_bindings") != plan["source_bindings"]:
        raise TemporalStop("plan/phase/source binding differs")
    if artificial and not all(t.startswith("synthetic-") for t in plan["task_ids"]):
        raise TemporalStop("offline runner accepts artificial task IDs only")
    files = candidate["source_files"]
    if not isinstance(files, dict) or not files or str(Path(__file__).resolve()) not in files:
        raise TemporalStop("execution source must be explicitly hash-bound")
    FileGuard(files)()
    provider = candidate["provider_evidence"]
    if (not isinstance(provider, dict) or set(provider) != {"path", "sha256", "origin"}
            or provider["origin"] != ("artificial_fixture" if artificial else "current_preflight")
            or files.get(provider["path"]) != provider["sha256"]):
        raise TemporalStop("bound provider contract required")
    validate_endpoint(Path(provider["path"]).read_bytes())
    cal = candidate["calendar"]
    if (not isinstance(cal, dict) or set(cal) != {"start_epoch", "end_epoch", "origin"}
            or cal["origin"] != ("artificial_clock" if artificial else "author_bound") or any(type(cal[k]) not in (int, float)
            or not math.isfinite(cal[k]) for k in ("start_epoch", "end_epoch"))):
        raise TemporalStop("explicit artificial time binding required")
    duration = candidate["calendar_contract"]
    if (set(duration) != {"status", "maximum_duration_seconds"}
            or duration["status"] != ("unaccepted_proposal" if artificial else "accepted")
            or type(duration["maximum_duration_seconds"]) is not int
            or not 0 < cal["end_epoch"] - cal["start_epoch"] <= duration["maximum_duration_seconds"]):
        raise TemporalStop("invalid bound calendar duration")
    if not artificial:
        approval = candidate["author_release"]
        if not isinstance(approval, dict) or set(approval) != {"path", "sha256"}:
            raise TemporalStop("external author release missing")
        FileGuard({approval["path"]: approval["sha256"]})()
        release = _read(approval["path"])
        if (release.get("author") != "Jannik" or release.get("authorized") is not True
                or release.get("phase") != "temporal" or not release.get("approval_reference")
                or release.get("execution_binding_sha256") != execution_binding(candidate)):
            raise TemporalStop("author release does not bind this execution contract")
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now) or not cal["start_epoch"] <= now <= cal["end_epoch"]:
        raise TemporalStop("outside unchanged bound execution interval")
    if candidate["section_ends_proposal"] != [1, 10, 40, 70, 100]:
        raise TemporalStop("section proposal changed after binding")
    if source_archive:
        members = {f"source-{i:03d}": h for i, (_, h) in enumerate(sorted(files.items()))}
        if not artificial:
            members["author-release"] = candidate["author_release"]["sha256"]
        _archive(candidate["source_backup"], members)


def _save(path, value):
    save_new(Path(path), encoded(value))


def _read(path):
    return strict_json(Path(path).read_bytes())


@contextmanager
def temporal_lock(control):
    control = Path(control)
    control.mkdir(parents=True, exist_ok=True)
    with (control / f"{NAMESPACE}.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise TemporalStop("another temporal writer is active") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _claim(candidate, plan, folder, control, *, create=False):
    if candidate.get("control_directory") != str(Path(control).resolve()):
        raise TemporalStop("canonical control directory differs")
    expected = {"namespace": NAMESPACE, "candidate_sha256": candidate["sha256"],
                "plan_sha256": plan["sha256"], "folder": str(Path(folder).resolve())}
    path = Path(control) / f"{NAMESPACE}.claim.json"
    if path.exists():
        if _read(path) != expected:
            raise TemporalStop("phase already claimed with another folder or binding")
    elif create:
        _save(path, expected)
    else:
        raise TemporalStop("phase claim missing")


def _budget(candidate, folder, *, existing):
    b = candidate["budget"]
    factory = PhaseBudget.read_completed if existing else PhaseBudget
    return factory(Path(folder) / "budget.jsonl", cap=_money(b["phase_cap_proposal_usd"]),
                   reserve=_money(b["per_call_reserve_usd"]), max_calls=b["max_calls"],
                   binding=candidate["sha256"], allow_synthetic=candidate["mode"] == "artificial_only")


def _inventory(folder):
    return {str(p.relative_to(folder)): file_hash(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and p.parts[len(folder.parts)] != "receipts"}


def _result(result):
    value = asdict(result)
    for field in ("cost_usd", "known_subtotal_usd"):
        value[field] = None if value[field] is None else str(value[field])
    return value


def _inspect(candidate, plan, manifest, folder):
    """Validate a whole-pair prefix, scoring locally from its retained artificial references."""
    folder = Path(folder)
    budget = _budget(candidate, folder, existing=True)
    budget_view(candidate, budget.cost)
    configs = {c.config_id: c for c in bank()}
    started = sorted((folder / "pairs").glob("*-started.json"))
    complete = sorted((folder / "pairs").glob("*-complete.json"))
    if len(started) != len(complete) or len(complete) > 100:
        raise TemporalStop("partial or unrecognized pair cannot resume")
    expected_files = {"budget.jsonl"}
    outcomes, attempts, generations = [], {}, set()
    provider_cost = Decimal(0)
    for number, path in enumerate(complete):
        pair = plan["pairs"][number]
        pid = pair["pair_id"]
        if path.name != f"{pid}-complete.json" or started[number].name != f"{pid}-started.json":
            raise TemporalStop("pair prefix is not contiguous")
        proof = _read(path)
        if proof["pair"] != pair or proof["plan_sha256"] != plan["sha256"]:
            raise TemporalStop("pair identity changed")
        if _read(started[number]) != {"pair": pair, "plan_sha256": plan["sha256"]}:
            raise TemporalStop("started pair binding changed")
        for name, checksum in proof["evidence"].items():
            member = Path(name)
            if member.is_absolute() or ".." in member.parts or file_hash(folder / member) != checksum:
                raise TemporalStop("pair evidence changed")
        expected_files.update(proof["evidence"])
        expected_files.add(str(path.relative_to(folder)))
        config = configs[proof["config_id"]]
        if len(config.roles) not in (2, 3):
            raise TemporalStop("invalid spatial group")
        ref_data = _read(folder / "pairs" / f"{pid}-reference.json")
        reference = AnswerReference(ref_data["task_id"], tuple(ref_data["answers"]))
        public_id = "task-" + data_digest([manifest["source_hashes"]["train"], pair["task_id"]])
        arms = {}
        for sid, rounds in zip(pair["slot_ids"], pair["round_order"]):
            journal_path = folder / "slots" / f"{sid}.jsonl"
            saved = read_journal(journal_path, config)
            trace = saved["trace"]
            rid = plan["sha256"][:16] + "-" + sid
            binding = _read(folder / "slots" / f"{sid}-binding.json")
            expected_binding = {"slot_id": sid, "pair_id": pid, "rounds": rounds,
                                "config_id": config.config_id, "public_task_id": public_id,
                                "run_id": rid, "plan_sha256": plan["sha256"]}
            if binding != expected_binding or trace["rounds"] != rounds or trace["run_id"] != rid:
                raise TemporalStop("slot rounds or run identity changed")
            task = TaskInput(trace["task"]["task_id"], trace["task"]["question"], tuple(trace["task"]["paragraphs"]))
            if task.task_id != public_id or reference.task_id != public_id:
                raise TemporalStop("public/reference identity differs")
            result = _result(read_result(journal_path, config, task, reference,
                             family_id=pair["family_id"], phase="temporal", repeat=1))
            if result != _read(folder / "slots" / f"{sid}-result.json") or result["cost_usd"] is None:
                raise TemporalStop("scoring or priced result differs")
            if result["status"] not in ("completed", "model_failed"):
                raise TemporalStop("nonterminal outcome")
            for e in trace["events"]:
                if e["kind"] in ("completed", "model_failed"):
                    if e["attempt_id"] in attempts:
                        raise TemporalStop("duplicate inner attempt")
                    attempts[e["attempt_id"]] = e["usage"]
            arms[rounds] = result
        if set(arms) != {1, 2}:
            raise TemporalStop("complete two-round outcomes required")
        outcomes.append({"task_id": pair["task_id"], "family_id": pair["family_id"], "hop": pair["hop"],
                         "spatial_config_id": config.config_id, "rounds": [1, 2],
                         "em": [arms[r]["em"] for r in (1, 2)], "f1": [arms[r]["f1"] for r in (1, 2)],
                         "cost_usd": [arms[r]["cost_usd"] for r in (1, 2)],
                         "status": [arms[r]["status"] for r in (1, 2)]})
    if len(attempts) != budget.calls or dict(budget.settlements) != attempts:
        raise TemporalStop("journal attempts do not exactly reconcile with phase ledger")
    for index, (attempt_id, usage) in enumerate(budget.settlements, 1):
        stem = f"{index:05d}"
        request = folder / "provider" / f"{stem}-request.json"
        response = folder / "provider" / f"{stem}-response.json"
        link = _read(folder / "provider" / f"{stem}-binding.json")
        billed = _read(folder / "provider" / f"{stem}-billing.json")
        receipt = _read(folder / "provider" / f"{stem}-received.json")
        billing, generation = decode_billing(response.read_bytes())
        if (generation in generations or billed["generation_id"] != generation
                or billed["usage"] != usage or billed["response_sha256"] != file_hash(response)
                or link != {"attempt_id": attempt_id, "request_sha256": file_hash(request),
                            "mode": "synthetic" if candidate["mode"] == "artificial_only" else "live"}
                or receipt != {"http_status": 200, "response_sha256": file_hash(response)}
                or billing.cost_usd != Decimal(usage["cost_usd"])):
            raise TemporalStop("provider provenance or generation identity differs")
        generations.add(generation)
        provider_cost += billing.cost_usd
    evidence = _inventory(folder)
    if set(evidence) != expected_files or provider_cost != budget.cost:
        raise TemporalStop("unclaimed files or unreconciled cost")
    state = {"candidate_sha256": candidate["sha256"], "plan_sha256": plan["sha256"],
             "completed_pairs": len(outcomes), "observations": outcomes,
             "budget": budget.snapshot(), "levels": budget_view(candidate, budget.cost),
             "generation_ids": sorted(generations), "evidence": evidence}
    state["state_sha256"] = digest(state)
    return state, budget


def _receipt_path(folder, state):
    return Path(folder) / "receipts" / f"P{state['completed_pairs']:03d}-{state['state_sha256']}.json"


def _verify_receipt(folder, state):
    receipt = _read(_receipt_path(folder, state))
    if receipt["state_sha256"] != state["state_sha256"]:
        raise TemporalStop("stale prefix receipt")
    _archive(receipt["backup"], state["evidence"])


def inspect_temporal(candidate, plan, manifest, allocation, *, folder, control, clock):
    validate_temporal_plan(plan, manifest, allocation, candidate["metadata_bindings"])
    _runtime(candidate, plan, clock=clock, source_archive=True)
    with temporal_lock(control):
        _claim(candidate, plan, folder, control)
        state, _ = _inspect(candidate, plan, manifest, Path(folder))
        return state


def checkpoint_temporal(candidate, plan, manifest, allocation, *, folder, control, clock, checkpoint):
    """Read-only audit plus additive backup receipt; never completes an open pair."""
    validate_temporal_plan(plan, manifest, allocation, candidate["metadata_bindings"])
    _runtime(candidate, plan, clock=clock, source_archive=True)
    with temporal_lock(control):
        _claim(candidate, plan, folder, control)
        state, _ = _inspect(candidate, plan, manifest, Path(folder))
        proof = checkpoint(deepcopy(state))
        _archive(proof, state["evidence"])
        path = _receipt_path(folder, state)
        if path.exists():
            _verify_receipt(folder, state)
        else:
            _save(path, {"state_sha256": state["state_sha256"], "backup": proof})
        return state


def run_section(candidate, plan, manifest, allocation, *, folder, control, section_end,
                loader, spatial_selector, transport, checkpoint, clock):
    """Dependency-injected artificial run, ending at the next prebound control hold."""
    validate_temporal_plan(plan, manifest, allocation, candidate["metadata_bindings"])
    _runtime(candidate, plan, clock=clock, source_archive=True)
    budget_view(candidate, Decimal(0))
    folder = Path(folder)
    with temporal_lock(control):
        _claim(candidate, plan, folder, control, create=True)
        existing = (folder / "budget.jsonl").exists()
        if existing:
            state, budget = _inspect(candidate, plan, manifest, folder)
            prefix = state["completed_pairs"]
            _verify_receipt(folder, state)
            generations = state["generation_ids"]
        else:
            if folder.exists() and any(folder.iterdir()):
                raise TemporalStop("unrecognized existing output folder")
            for sub in ("provider", "slots", "pairs", "receipts"):
                (folder / sub).mkdir(parents=True, exist_ok=True)
            budget = _budget(candidate, folder, existing=False)
            prefix, generations = 0, []
        later = [x for x in candidate["section_ends_proposal"] if x > prefix]
        if not later or type(section_end) is not int or section_end != later[0]:
            raise TemporalStop("only the next unchanged control hold may run")
        adapter = StudyAdapter(folder / "provider", transport, budget,
                               synthetic=candidate["mode"] == "artificial_only", failure_policy=F01)
        adapter.generations.update(generations)
        configs = {c.config_id: c for c in bank()}

        def send(request):
            _runtime(candidate, plan, clock=clock)
            budget_view(candidate, budget.cost)
            return adapter(request)

        for pair in plan["pairs"][prefix:section_end]:
            _runtime(candidate, plan, clock=clock)
            budget_view(candidate, budget.cost, require_pair=True)
            pid = pair["pair_id"]
            first_call = budget.calls + 1
            start_path = folder / "pairs" / f"{pid}-started.json"
            _save(start_path, {"pair": pair, "plan_sha256": plan["sha256"]})
            task, reference = loader(pair["task_id"])
            public_id = "task-" + data_digest([manifest["source_hashes"]["train"], pair["task_id"]])
            if (not isinstance(task, TaskInput) or not isinstance(reference, AnswerReference)
                    or task.task_id != public_id or reference.task_id != public_id):
                raise TemporalStop("loader public/reference identity mismatch")
            config_id = spatial_selector(task)
            if config_id not in configs or len(configs[config_id].roles) not in (2, 3):
                raise TemporalStop("spatial selector returned an unbound configuration")
            config = configs[config_id]
            reference_path = folder / "pairs" / f"{pid}-reference.json"
            _save(reference_path, asdict(reference))
            files = [start_path, reference_path]
            for sid, rounds in zip(pair["slot_ids"], pair["round_order"]):
                _runtime(candidate, plan, clock=clock)
                run_id = plan["sha256"][:16] + "-" + sid
                binding = folder / "slots" / f"{sid}-binding.json"
                journal = folder / "slots" / f"{sid}.jsonl"
                result_path = folder / "slots" / f"{sid}-result.json"
                _save(binding, {"slot_id": sid, "pair_id": pid, "rounds": rounds,
                                "config_id": config_id, "public_task_id": public_id,
                                "run_id": run_id, "plan_sha256": plan["sha256"]})
                execute(task, config, send, rounds=rounds, run_id=run_id,
                        journal_path=journal, producer_limit=1024, failure_policy=F01)
                result = _result(read_result(journal, config, task, reference,
                                 family_id=pair["family_id"], phase="temporal", repeat=1))
                if result["status"] not in ("completed", "model_failed") or result["cost_usd"] is None:
                    raise TemporalStop("slot not terminal and completely billed")
                _save(result_path, result)
                files.extend((binding, journal, result_path))
            for i in range(first_call, budget.calls + 1):
                files.extend(sorted((folder / "provider").glob(f"{i:05d}-*.json")))
            _save(folder / "pairs" / f"{pid}-complete.json",
                  {"pair": pair, "plan_sha256": plan["sha256"], "config_id": config_id,
                   "evidence": {str(p.relative_to(folder)): file_hash(p) for p in files}})
        state, _ = _inspect(candidate, plan, manifest, folder)
        proof = checkpoint(deepcopy(state))
        _archive(proof, state["evidence"])
        _save(_receipt_path(folder, state), {"state_sha256": state["state_sha256"], "backup": proof})
        return state


def collect_temporal_pairs(candidate, plan, manifest, allocation, *, folder, control, clock):
    state = inspect_temporal(candidate, plan, manifest, allocation, folder=folder, control=control, clock=clock)
    if state["completed_pairs"] != 100:
        raise TemporalStop("only the complete 100-pair matrix is a development export")
    _verify_receipt(folder, state)
    return {"schema": "z45-temporal-numerical-pairs/v1", "plan_sha256": plan["sha256"],
            "state_sha256": state["state_sha256"], "pairs": state["observations"],
            "fit_executed": False, "mode": candidate["mode"]}
