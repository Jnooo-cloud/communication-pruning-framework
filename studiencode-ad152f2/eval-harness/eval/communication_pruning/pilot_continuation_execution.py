"""R3 additive execution; original pair, run, claim and budget identities remain unchanged.

Local flock/claim persistence prevents concurrent or renamed-output reuse when the
caller binds the canonical control directory. Hashes detect changed evidence, not
a hostile rewrite. No keys, hidden transport, retries, or automatic rescheduling.
"""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter_ns
import fcntl
import json
import re

from .configurations import bank
from .contracts import TaskInput
from .data import AnswerReference, canonical, digest
from .evaluation import read_result
from .execution import execute
from .failure_policy import F01, strict_json
from .openrouter import encoded, save_new
from .phase_budget import PhaseBudget
from .pilot_calendar import PHASE_ID, require_pair_start, utc, validate_calendar, window_interval
from .study import StudyAdapter, file_hash
from .pilot_execution import PilotStop, pilot_lock
from .pilot_continuation_calendar import section_for_pair


def _read(path):
    return strict_json(Path(path).read_bytes())


def _save(path, value):
    save_new(Path(path), encoded(value))


def _claim(plan, folder, synthetic):
    return {"schema": "z42-pilot-claim/v1", "phase_id": PHASE_ID,
            "plan_sha256": plan["sha256"], "output": str(Path(folder).resolve()),
            "synthetic": synthetic, "failure_policy": F01}


def _budget(plan, folder, synthetic, *, existing):
    values = plan["budget"]
    factory = PhaseBudget.read_completed if existing else PhaseBudget
    return factory(Path(folder) / "budget.jsonl", cap=Decimal(values["cap_usd"]),
                   reserve=Decimal(values["reserve_usd"]), max_calls=values["max_calls"],
                   binding=plan["sha256"], allow_synthetic=synthetic)


def _hashes(folder, paths):
    return {str(p.relative_to(folder)): file_hash(p) for p in sorted(paths)}


def _validate_receipt(receipt):
    if (not isinstance(receipt, dict) or receipt.get("verified") is not True
            or not isinstance(receipt.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"]) is None):
        raise PilotStop("checkpoint requires a verified external audit/backup receipt")


def _observations(plan, folder):
    """Include all 720 positions; account for unsuccessful inner attempts too."""
    costs, held = {}, {}
    ledger = folder / "budget.jsonl"
    if ledger.exists():
        pending = None
        for line in ledger.read_bytes().splitlines():
            row = strict_json(line)
            attempt = row.get("attempt_id", "")
            sid = attempt.split(":", 1)[0].rsplit("-", 1)[-1]
            if row["kind"] == "reserved":
                pending = sid
                held[sid] = Decimal(row["reservation_usd"])
            elif row["kind"] == "settled":
                value = row["usage"]["cost_usd"]
                if value is not None:
                    costs[sid] = costs.get(sid, Decimal(0)) + Decimal(value)
                    held[sid] = Decimal(0)
                    pending = None
    rows = []
    for slot in plan["slots"]:
        sid = slot["slot_id"]
        result_path = folder / "slots" / f"{sid}-result.json"
        binding_path = folder / "slots" / f"{sid}-binding.json"
        result = _read(result_path) if result_path.exists() else None
        binding = _read(binding_path) if binding_path.exists() else {}
        status = ("F01" if result["status"] == "model_failed" else "complete") if result else (
            "partial" if binding or costs.get(sid) or held.get(sid) else "not_started")
        rows.append({"original_window_id": slot["window_id"],
                     "execution_section_id": binding.get("execution_section_id", "R2-W01" if result and slot["pair_id"] == "P0001" else None),
                     "pair_id": slot["pair_id"], "slot_id": sid, "arm": slot["arm"], "status": status,
                     "em": result["em"] if result else None, "f1": result["f1"] if result else None,
                     "known_cost_usd": str(costs.get(sid, Decimal(0))),
                     "reserved_cost_usd": str(held.get(sid, Decimal(0))),
                     "selection_seconds": binding.get("selection_seconds"),
                     "configuration": binding.get("config_id"),
                     "error": result.get("failure_reason") if result else ("uncompleted_slot" if status == "partial" else None)})
    return rows


def _inspect(plan, folder, control, synthetic, recovery):
    recovery.guard()
    claim_path = control / f"{PHASE_ID}.claim.json"
    if canonical(_read(claim_path)) != canonical(_claim(plan, folder, synthetic)):
        raise PilotStop("pilot claim changed; an output-directory change cannot reset the phase")
    if canonical(_read(folder / "plan.json")) != canonical(plan):
        raise PilotStop("saved pilot calendar changed")
    # ContinuationSession.guard verified exactly the preserved original halted bytes.
    # Every additional failure remains a blocking additive recovery error.
    budget = _budget(plan, folder, synthetic, existing=True)
    completed, evidence, generations, attempts = 0, {}, set(), set()
    for pair in plan["pairs"]:
        pid = pair["pair_id"]
        begin = folder / "pairs" / f"{pid}-started.json"
        done = folder / "pairs" / f"{pid}-complete.json"
        if not done.exists():
            if begin.exists():
                raise PilotStop("begun incomplete pair; no automatic retry")
            break
        receipt = _read(done)
        if (receipt.get("schema") != "z42-pilot-pair/v1" or receipt.get("pair") != pair
                or receipt.get("plan_sha256") != plan["sha256"]):
            raise PilotStop("pair receipt identity differs")
        if pid != "P0001":
            section = section_for_pair(recovery.schedule, pid)
            start_receipt = _read(begin)
            for item in (receipt, start_receipt):
                if item.get("execution_section_id") != section["section_id"] or item.get("schedule_sha256") != recovery.schedule["sha256"]:
                    raise PilotStop("pair execution section binding differs")
            require_pair_start(section, datetime.fromisoformat(start_receipt["started_utc"]))
            if datetime.fromisoformat(receipt["finished_utc"]) > window_interval(section)[2]:
                raise PilotStop("completed pair exceeded execution section")
        for name, checksum in receipt["evidence"].items():
            path = folder / name
            if Path(name).is_absolute() or ".." in Path(name).parts or file_hash(path) != checksum:
                raise PilotStop("pair evidence changed")
            evidence[name] = checksum
            if name.startswith("provider/") and name.endswith("-binding.json"):
                attempt = _read(path)["attempt_id"]
                if attempt in attempts:
                    raise PilotStop("duplicate inner attempt")
                attempts.add(attempt)
            if name.startswith("provider/") and name.endswith("-billing.json"):
                generation = _read(path)["generation_id"]
                if generation in generations:
                    raise PilotStop("generation reused across pairs or windows")
                generations.add(generation)
        required = {str(begin.relative_to(folder))}
        for sid in pair["slot_ids"]:
            required.update(f"slots/{sid}{suffix}" for suffix in (".jsonl", "-binding.json", "-result.json"))
            value = _read(folder / "slots" / f"{sid}-result.json")
            if (value["status"] not in ("completed", "model_failed") or value["cost_usd"] is None
                    or value["run_id"] != plan["sha256"][:16] + "-" + sid):
                raise PilotStop("unscored or mismatched terminal slot")
        if not required <= set(receipt["evidence"]):
            raise PilotStop("missing pair evidence")
        evidence[str(done.relative_to(folder))] = file_hash(done)
        completed += 1
    if attempts != budget.ids or len(generations) != budget.calls:
        raise PilotStop("budget and distinct provider attempts differ")
    expected_starts = {f"{p['pair_id']}-started.json" for p in plan["pairs"][:completed]}
    if {p.name for p in (folder / "pairs").glob("*-started.json")} != expected_starts:
        raise PilotStop("non-prefix or incomplete pair")
    provider_names = {str(p.relative_to(folder)) for p in (folder / "provider").iterdir()}
    if provider_names != {name for name in evidence if name.startswith("provider/")}:
        raise PilotStop("unassigned provider evidence")
    if completed and completed % 30 and completed != 1:
        raise PilotStop("incomplete window; no automatic continuation")
    stages = [f"R3-E{i:02d}-complete" for i in range(1, completed // 30 + 1)]
    if completed:
        stages.insert(0, "W01-first-pair")
    for stage in stages:
        proof = _read(folder / "checkpoints" / f"{stage}.json")
        _validate_receipt(proof["receipt"])
        if proof["stage"] != stage or proof["plan_sha256"] != plan["sha256"]:
            raise PilotStop("checkpoint binding differs")
    return {"completed_pairs": completed, "completed_slots": completed * 2,
            "budget_object": budget, "generations": generations, "evidence": evidence,
            "observations": _observations(plan, folder)}


def inspect_pilot(plan, manifest, task_ids, *, bindings, folder, control, recovery, synthetic=False):
    validate_calendar(plan, manifest, expected_bindings=bindings, expected_task_ids=task_ids)
    if Path(folder) != recovery.live or Path(control) != recovery.control or synthetic is not recovery.synthetic:
        raise PilotStop("recovery canonical inspection mismatch")
    if not (Path(control) / f"{PHASE_ID}.lock").is_file():
        raise PilotStop("existing phase lock missing")
    with pilot_lock(control):
        recovery.original_start_guard()
        recovery.guard(deep=True)
        state = _inspect(plan, Path(folder), Path(control), synthetic, recovery)
        state["budget"] = state.pop("budget_object").snapshot()
        state["generations"] = sorted(state["generations"])
        count = state["completed_pairs"]
        state["next_window_id"] = section_for_pair(recovery.schedule, plan["pairs"][count]["pair_id"])["section_id"] if count < 360 else None
        return state


def continuation_status(plan, manifest, task_ids, *, bindings, recovery):
    """Read-only status using the same inspection, no loader/selector/transport."""
    try:
        state = inspect_pilot(plan, manifest, task_ids, bindings=bindings, folder=recovery.live,
                              control=recovery.control, recovery=recovery, synthetic=recovery.synthetic)
        wid = state['next_window_id']
        result = {'completed_pairs': state['completed_pairs'], 'budget': state['budget'],
                  'next_window_id': wid, 'automatic_dispatch': False}
        if wid is None:
            return {**result, 'status': 'complete_pending_final_diagnosis'}
        window = next(w for w in recovery.schedule['sections'] if w['section_id'] == wid)
        start, cutoff, _ = window_interval(window)
        now = recovery.moment()
        status = 'not_yet_due' if now < start else 'due' if now < cutoff else 'stopped'
        return {**result, 'status': status, 'reason': 'missed_window' if status == 'stopped' else None,
                'next_window': window}
    except Exception as error:
        return {'status': 'stopped', 'automatic_dispatch': False,
                'error_type': type(error).__name__, 'reason': str(error)}


def read_observations(plan, folder):
    """Descriptive partial-state export; this does not approve any continuation."""
    return _observations(plan, Path(folder))


def run_window(plan, manifest, task_ids, *, bindings, window_id, folder, control,
               loader, selector, transport, guard, checkpoint, clock=None,
               recovery, synthetic=False, stop_after_first_pair=False):
    """Execute one calendar window, or its explicit first-pair control hold.

    loader(id)->(TaskInput, AnswerReference); selector(TaskInput)->config ID.
    guard() checks the caller's current release/source/rule/tariff binding.
    checkpoint(stage,state)->{verified: True, sha256: ...} must actually verify
    measurement and an additive backup. The callback runs while the lock is held.
    """
    from .pilot_continuation_guard import ContinuationSession
    if not isinstance(recovery, ContinuationSession):
        raise PilotStop("bound recovery session required")
    if stop_after_first_pair:
        raise PilotStop("P0001 may never be repeated")
    original_guard = guard
    def guard():
        original_guard()
        recovery.guard()
    validate_calendar(plan, manifest, expected_bindings=bindings, expected_task_ids=task_ids)
    if type(synthetic) is not bool or type(stop_after_first_pair) is not bool:
        raise ValueError("explicit boolean execution flags required")
    if not all(callable(c) for c in (loader, selector, transport, guard, checkpoint)):
        raise ValueError("all execution dependencies must be explicitly injected")
    recovery.guard()
    window = next((w for w in recovery.schedule["sections"] if w["section_id"] == window_id), None)
    if window is None or stop_after_first_pair and window_id != "W01":
        raise PilotStop("unknown window or invalid first-pair hold")
    clock = clock or (lambda: datetime.now(timezone.utc))
    folder, control = Path(folder), Path(control)
    if folder != recovery.live or control != recovery.control or synthetic is not recovery.synthetic:
        raise PilotStop("recovery canonical phase mismatch")
    with pilot_lock(control):
        budget, report = None, {"schema": "z42-pilot-report/v1", "window_id": window_id,
                               "plan_sha256": plan["sha256"], "schedule_sha256": recovery.schedule["sha256"], "status": "starting"}
        try:
            recovery.begin_window(window_id)
            guard()
            now = utc(clock())
            require_pair_start(window, now)
            claim_path = control / f"{PHASE_ID}.claim.json"
            if claim_path.exists():
                state = _inspect(plan, folder, control, synthetic, recovery)
                budget, prefix = state["budget_object"], state["completed_pairs"]
                generations = state["generations"]
            else:
                raise PilotStop("existing phase claim required; recovery never creates a budget")
            if prefix >= 360 or plan["pairs"][prefix]["pair_id"] not in window["pair_ids"]:
                raise PilotStop("wrong window or already completed window")
            if stop_after_first_pair and prefix:
                raise PilotStop("first pair has already been consumed")
            adapter = StudyAdapter(folder / "provider", transport, budget,
                                   synthetic=synthetic, failure_policy=F01)
            adapter.generations.update(generations)
            configurations = {c.config_id: c for c in bank()}
            report.update(started_utc=now.isoformat(), completed_pairs_before=prefix)
            latest = now

            def checked_time():
                nonlocal latest
                observed = utc(clock())
                if observed < latest:
                    raise PilotStop("system clock moved backwards")
                latest = observed
                return observed

            def send(request):
                guard()
                checked_time()  # pair may finish beyond the cutoff; never starts a new pair there
                return adapter(request)

            def control_hold(stage):
                snapshot = {"schema": "z42-pilot-checkpoint-state/v1", "stage": stage,
                            "plan_sha256": plan["sha256"], "folder": str(folder.resolve()),
                            "window_id": window_id, "schedule_sha256": recovery.schedule["sha256"], "completed_pairs": prefix,
                            "completed_slots": 2 * prefix, "budget": budget.snapshot(),
                            "observations": _observations(plan, folder),
                            "evidence": _hashes(folder, [p for p in folder.rglob("*") if p.is_file()])}
                receipt = checkpoint(stage, snapshot)
                _validate_receipt(receipt)
                _save(folder / "checkpoints" / f"{stage}.json", {
                    "stage": stage, "plan_sha256": plan["sha256"],
                    "state_sha256": digest(snapshot), "receipt": receipt, "utc": checked_time().isoformat(),
                    "schedule_sha256": recovery.schedule["sha256"]})

            for pair in plan["pairs"][prefix:]:
                if pair["pair_id"] not in window["pair_ids"]:
                    break
                guard()
                started = checked_time()
                require_pair_start(window, started)
                pid, first_call = pair["pair_id"], budget.calls + 1
                pair_start = folder / "pairs" / f"{pid}-started.json"
                _save(pair_start, {"pair": pair, "started_utc": started.isoformat(), "plan_sha256": plan["sha256"],
                                   "execution_section_id": window_id, "schedule_sha256": recovery.schedule["sha256"]})
                task, reference = loader(pair["task_id"])
                expected = "task-" + digest([manifest["source_hashes"]["train"], pair["task_id"]])
                if (not isinstance(task, TaskInput) or not isinstance(reference, AnswerReference)
                        or task.task_id != expected or reference.task_id != expected):
                    raise PilotStop("public/reference input identity mismatch")
                files = [pair_start]
                for sid, arm in zip(pair["slot_ids"], pair["arm_order"]):
                    guard()
                    checked_time()
                    selection_start = perf_counter_ns()
                    config_id = selector(task) if arm == "Q" else "C01"
                    selection_seconds = (perf_counter_ns() - selection_start) / 1_000_000_000
                    if not isinstance(config_id, str) or config_id not in configurations:
                        raise PilotStop("selector returned unknown configuration")
                    config = configurations[config_id]
                    if 2 * len(config.roles) + 1 not in (5, 7):
                        raise PilotStop("configuration exceeds bound 5/7-call contract")
                    run_id = plan["sha256"][:16] + "-" + sid
                    binding_path = folder / "slots" / f"{sid}-binding.json"
                    journal_path = folder / "slots" / f"{sid}.jsonl"
                    result_path = folder / "slots" / f"{sid}-result.json"
                    _save(binding_path, {"slot": plan["slots"][int(sid[1:]) - 1], "run_id": run_id,
                                        "config_id": config_id, "selection_seconds": selection_seconds,
                                        "public_task_id": task.task_id, "started_utc": checked_time().isoformat(),
                                        "execution_section_id": window_id, "schedule_sha256": recovery.schedule["sha256"],
                                        "plan_sha256": plan["sha256"]})
                    execute(task, config, send, rounds=2, run_id=run_id, journal_path=journal_path,
                            producer_limit=1024, failure_policy=F01)
                    execution_finished = checked_time().isoformat()
                    result = asdict(read_result(journal_path, config, task, reference,
                                               family_id=pair["family_id"], phase="pilot", repeat=pair["repeat"]))
                    result.update(execution_finished_utc=execution_finished,
                                  scoring_finished_utc=checked_time().isoformat())
                    for name in ("cost_usd", "known_subtotal_usd"):
                        result[name] = str(result[name]) if result[name] is not None else None
                    if result["status"] not in ("completed", "model_failed") or result["cost_usd"] is None:
                        raise PilotStop("nonterminal or unpriced arm")
                    _save(result_path, result)
                    files.extend((binding_path, journal_path, result_path))
                for call in range(first_call, budget.calls + 1):
                    files.extend((folder / "provider").glob(f"{call:05d}-*.json"))
                finished = checked_time()
                _save(folder / "pairs" / f"{pid}-complete.json", {
                    "schema": "z42-pilot-pair/v1", "pair": pair, "plan_sha256": plan["sha256"],
                    "execution_section_id": window_id, "schedule_sha256": recovery.schedule["sha256"],
                    "started_utc": started.isoformat(), "finished_utc": finished.isoformat(),
                    "evidence": _hashes(folder, files), "budget": budget.snapshot()})
                prefix += 1
                report["completed_pairs"] = prefix
                if finished > window_interval(window)[2]:
                    raise PilotStop("pair exceeded bound window end; retained as a deviation")
                if prefix == 1:
                    control_hold("W01-first-pair")
                    if stop_after_first_pair:
                        report["status"] = "paused_first_pair"
                        break
            else:
                pass
            if report["status"] != "paused_first_pair":
                if prefix % 30 or plan["pairs"][prefix - 1]["pair_id"] != window["pair_ids"][-1]:
                    raise PilotStop("incomplete execution section")
                control_hold(window_id + "-complete")
                report["status"] = "completed_window"
            guard()
            return report
        except BaseException as error:
            report.update(status="stopped", error_type=type(error).__name__, reason=str(error))
            recovery.stop(error)
            if folder.is_dir() and (folder / "plan.json").exists() and not (folder / "halted.json").exists():
                _save(folder / "halted.json", {**report, "budget": budget.snapshot() if budget else None,
                                              "utc": utc(clock()).isoformat()})
            raise
        finally:
            if folder.is_dir() and (folder / "reports").is_dir():
                report.update(budget=budget.snapshot() if budget else None, finished_utc=utc(clock()).isoformat())
                number = len(list((folder / "reports").glob("*.json"))) + 1
                try:
                    _save(folder / "reports" / f"{number:04d}.json", report)
                    if report["status"] == "completed_window":
                        recovery.finish_window(report)
                    elif report["status"] == "stopped":
                        recovery.backup_stop()
                except BaseException as error:
                    recovery.stop(error)
                    recovery.backup_stop()
                    raise
