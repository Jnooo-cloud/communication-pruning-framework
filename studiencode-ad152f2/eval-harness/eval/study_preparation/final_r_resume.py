"""D-076: one additive replacement for the stopped R01223 request.

Original files are immutable. Only new physical requests enter the new native
ledger. Copied original evidence is an explicitly derived backup materialization,
never a second ledger. The original scientific execution and analysis are used
unchanged. Every write is protected by the original study lock.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import math
import shutil

from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput, Request, Message, Usage
from communication_pruning.data import AnswerReference, digest
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, decode_outcome
from communication_pruning.journal import read_journal, _object, _constant
from communication_pruning.openrouter import encoded, payload, decode_billing
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.study import StudyAdapter, FileGuard, file_hash
from project.research_control.recovery import FileWitness
from . import final_secondary as secondary, final_execution as native, final_preflight as gate
from .final_plan import ARMS, canonical_hash

StudyStop = gate.StudyStop
PANELS = secondary.PANELS
ZERO = secondary.ZERO
CLAIM = "r-recovery-01223/claim.json"
UNKNOWN_ID = "50d4c906a74daf48:Z50-STUDY-v1:R:00038:D:2:draft:1"
UNKNOWN_SHA = "67b7878696ff40a25a8a1250508f057954ac11c0e467bbf4cb40590542375d87"
_need, _save, _path, _all_files = secondary._need, secondary._save, secondary._path, secondary._all_files
_blocks, _section_states, _record_section = secondary._blocks, secondary._section_states, secondary._record_section
_receipt_path, _verify_receipt, _checkpoint = secondary._receipt_path, secondary._verify_receipt, secondary._checkpoint
_verify_confirmation, _analysis_contract = secondary._verify_confirmation, secondary._analysis_contract
_require_real_evidence = secondary._require_real_evidence
_verify_ledger_prefix, _verify_panel_remote = secondary._verify_ledger_prefix, secondary._verify_panel_remote
_admissions, _record_admission = secondary._admissions, secondary._record_admission

def _verify_panel_closeout(binding, candidate, plan, folder, panel):
    from .final_analysis import analyze_panel, validate_rows
    closure = gate.read_json(Path(folder) / "panels" / panel / "complete.json")
    _need(closure["binding_sha256"] == binding["sha256"] and closure["panel"] == panel,
          "panel closure binding changed")
    state, _ = _inspect(binding, candidate, plan, folder)
    rows = validate_rows(plan, panel, [r for r in state["rows"] if r["panel"] == panel])
    contract = _analysis_contract(binding, candidate, plan)
    expected = _analysis(binding, plan, panel, rows, contract)
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
        result = _analysis(binding, plan, panel, rows, contract)
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
        _need(gate.read_json(path) == _analysis(binding, plan, panel, rows, contract),
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
        _need(gate.read_json(path) == _analysis(binding, plan, panel, rows, contract),
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


def additional_sources():
    result = secondary.additional_sources()
    for name in ('final_r_resume.py', 'final_r_resume_operator.py'):
        path = Path(__file__).with_name(name).resolve()
        result[str(path)] = file_hash(path)
    return result


def _control_files(control):
    return {str(p.resolve()): file_hash(p) for p in sorted(Path(control).iterdir())
            if p.is_file() and p.name != gate.NAMESPACE + '.lock'}


def _old_ledger(original_binding):
    """Read and validate the poisoned native ledger without changing one byte."""
    path = Path(original_binding['folder']) / 'budget.jsonl'
    raw = path.read_bytes()
    _need(raw.endswith(b'\n'), 'original ledger has a partial line')
    rows, previous = [], ZERO
    for i, line in enumerate(raw.splitlines()):
        row = json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
        checksum = row.pop('sha256')
        _need(row.get('sequence') == i and row.get('previous') == previous and digest(row) == checksum,
              'original ledger chain differs')
        previous = checksum
        rows.append({k: v for k, v in row.items() if k not in ('sequence', 'previous', 'time')})
    cap = min(gate.money(v) for v in secondary.accounting_view(original_binding['predecessor'], Decimal(0))['available_usd'].values())
    _need(rows[0] == {'kind': 'header', 'cap_usd': str(cap), 'reserve_usd': '0.14',
        'max_calls': sum(gate.MAX_CALLS[p] * original_binding['_plan_counts'][p] for p in PANELS),
        'binding': original_binding['sha256'], 'allow_synthetic': original_binding['mode'] == 'artificial_only'},
        'original native budget header changed')
    _need(len(rows) >= 3 and len(rows) % 2 == 1, 'exact settled unknown tail required')
    cost, settlements, ids = Decimal(0), [], set()
    for index, (reserved, settled) in enumerate(zip(rows[1::2], rows[2::2]), 1):
        attempt = reserved.get('attempt_id')
        _need(isinstance(attempt, str) and attempt and attempt not in ids and reserved == {
            'kind': 'reserved', 'attempt_id': attempt, 'reservation_usd': '0.14', 'known_before_usd': str(cost)},
            'original reservation differs')
        ids.add(attempt)
        usage = Usage(**{**settled['usage'], 'cost_usd': Decimal(settled['usage']['cost_usd'])
                         if settled['usage']['cost_usd'] is not None else None})
        last = index == (len(rows) - 1) // 2
        _need(settled == {'kind': 'settled', 'attempt_id': attempt, 'usage': usage.to_dict(),
                         'failed': last, 'over_reservation': False}, 'original settlement differs')
        if last:
            _need(usage.cost_usd is None and usage.cost_source == 'unknown', 'single original unknown required')
            unknown = attempt
        else:
            _need(usage.cost_usd is not None and usage.cost_usd <= Decimal('.14') and
                (usage.cost_source != 'synthetic' or original_binding['mode'] == 'artificial_only'),
                'original successful cost invalid')
            settlements.append((attempt, usage.to_dict()))
            cost += usage.cost_usd
    return settlements, cost, unknown


def prepare_incident(original_candidate, original_binding, plan, *, review, backup):
    """Read metadata only; this proposal neither claims nor authorizes recovery."""
    gate._check_seal(original_candidate)
    gate._check_seal(original_binding)
    original = Path(original_binding['folder'])
    settlements, cost, unknown = _old_ledger({**original_binding, '_plan_counts': plan['counts']})
    complete = sorted((original / 'blocks').glob('*/complete.json'))
    index = len(settlements) + 1
    request = native._provider_files(original, index)['request']
    result = {'schema': 'z52-r01223-incident/v1',
        'original_folder': str(original), 'original_inventory': _all_files(original),
        'witness_folder': original_binding['witness'], 'witness_inventory': _all_files(original_binding['witness']),
        'control_files': _control_files(original_binding['control']),
        'completed_blocks': len(complete), 'known_calls': len(settlements), 'known_cost_usd': str(cost),
        'unknown_provider_index': index, 'unknown_attempt_id': unknown, 'request_sha256': file_hash(request),
        'held_original_reservation_usd': '0.14', 'review': deepcopy(review), 'backup': deepcopy(backup)}
    for record in (review, backup):
        gate.evidence_file(record)
    return result


def prepare_binding(candidate, plan, *, original_candidate, original_binding, incident,
                    folder, control, witness, owner, analysis_contract, activation=None):
    return gate.seal({'schema': 'z52-r01223-resume/v1', 'mode': candidate['mode'],
        'candidate_sha256': candidate['sha256'], 'plan_hash': plan['plan_hash'],
        'execution_binding_sha256': gate.execution_binding(candidate),
        'scientific_candidate_sha256': original_binding['scientific_candidate_sha256'],
        'folder': str(_path(folder)), 'control': str(_path(control)), 'witness': str(_path(witness)),
        'owner': owner, 'owner_generation': 1, 'claim_path': str(_path(control) / CLAIM),
        'original_candidate': deepcopy(original_candidate), 'original_binding': deepcopy(original_binding),
        'incident': deepcopy(incident), 'first_hold': plan['counts']['P'] + incident['completed_blocks'] + 1,
        'predecessor': deepcopy(original_binding['predecessor']), 'source_files': additional_sources(),
        'analysis_contract': deepcopy(analysis_contract), 'activation': deepcopy(activation)})


def connection_hash(binding):
    return secondary.connection_hash(binding)


def _verify_originals(binding):
    incident, original = binding['incident'], binding['original_binding']
    _need(incident['original_folder'] == original['folder'] and incident['witness_folder'] == original['witness'],
          'original path identity changed')
    _need(_all_files(original['folder']) == incident['original_inventory'] and
          _all_files(original['witness']) == incident['witness_inventory'] and
          _control_files(binding['control']) == incident['control_files'], 'immutable original evidence changed')
    for name in ('review', 'backup'):
        gate.evidence_file(incident[name])
    _need(gate.read_json(Path(original['folder']) / 'STOP.json').get('retry_allowed') is False,
          'original STOP must remain active')
    _need(gate.read_json(Path(binding['control']) / secondary.CLAIM)['binding_sha256'] == original['sha256'],
          'original secondary claim differs')


def _check_binding(binding, candidate, plan, *, folder, control, clock, dependencies=None):
    gate._check_seal(binding)
    _need(binding.get('schema') == 'z52-r01223-resume/v1' and binding['mode'] == candidate['mode'],
          'specific R01223 binding required')
    _need(binding['folder'] == str(_path(folder)) and binding['control'] == str(_path(control)) == candidate['control_directory']
          and binding['claim_path'] == str(_path(control) / CLAIM), 'canonical recovery path changed')
    _need(binding['candidate_sha256'] == candidate['sha256'] and binding['plan_hash'] == plan['plan_hash']
          and binding['execution_binding_sha256'] == gate.execution_binding(candidate), 'current candidate identity changed')
    _need(binding['owner_generation'] == 1 and isinstance(binding['owner'], str) and binding['owner'].strip(),
          'one fixed executor required')
    _need(binding['source_files'] == additional_sources(), 'recovery implementation changed')
    old, old_candidate = binding['original_binding'], binding['original_candidate']
    gate._check_seal(old)
    gate._check_seal(old_candidate)
    _need(old['candidate_sha256'] == old_candidate['sha256'] and old['plan_hash'] == plan['plan_hash']
          and old['execution_binding_sha256'] == gate.execution_binding(old_candidate)
          and old['source_files'] == secondary.additional_sources(), 'original binding changed')
    for key in ('bindings', 'source_files', 'documents', 'fixed_config_id', 'fixed_rounds', 'direct_prompt',
                'section_ends', 'calendar', 'plan_evidence', 'budget'):
        _need(candidate[key] == old_candidate[key], 'scientific/original candidate changed: ' + key)
    _need(binding['predecessor'] == old['predecessor'] and binding['analysis_contract'] == old['analysis_contract'],
          'original P or analysis contract changed')
    _verify_originals(binding)
    incident = binding['incident']
    _need(incident['schema'] == 'z52-r01223-incident/v1' and incident['held_original_reservation_usd'] == '0.14'
          and binding['first_hold'] == plan['counts']['P'] + incident['completed_blocks'] + 1,
          'incident identity or first hold changed')
    secondary._preflight(binding, candidate, plan, control=control, clock=clock, dependencies=dependencies)
    _analysis_contract(binding, candidate, plan)
    if binding['mode'] == 'artificial_only':
        _need(binding['activation'] is None, 'artificial tests cannot carry author activation')
    else:
        expected_root = Path(__file__).resolve().parents[1] / 'runs/Z52-NEBENPANEL-ANSCHLUSS-001'
        _need(Path(old['folder']) == expected_root / 'live' and Path(folder) == expected_root / 'recovery-R00038/live'
              and Path(binding['witness']) == expected_root / 'recovery-R00038/witness'
              and Path(control) == expected_root.parent / 'final-study-control', 'live recovery namespace differs')
        _need(incident['completed_blocks'] == 38 and incident['known_calls'] == 1222
              and gate.money(incident['known_cost_usd']) == Decimal('.28654314')
              and incident['unknown_provider_index'] == 1223 and incident['unknown_attempt_id'] == UNKNOWN_ID
              and incident['request_sha256'] == UNKNOWN_SHA and binding['first_hold'] == 9079,
              'only the actual R01223 incident is authorized')
        secondary._activation_gate(binding, candidate, plan, clock)
        activation = gate.read_json(gate.evidence_file(binding['activation']))
        _need(activation.get('author_decision') == 'D-076' and activation.get('single_replacement') is True
              and activation.get('known_costs_only') is True
              and activation.get('incident_sha256') == canonical_hash(incident), 'exact D-076 replacement decision missing')
    accounting_view(binding, Decimal(0))


def accounting_view(binding, new_cost, *, reserve_calls=0, account_available=None):
    incident = binding['incident']
    known = gate.money(incident['known_cost_usd']) + new_cost
    held = Decimal('.14')
    # This same .14 occurs once in each independently binding limit, not twice in any limit.
    adjusted_account = None if account_available is None else str(gate.money(account_available) - held)
    view = secondary.accounting_view(binding['predecessor'], known + held,
                                    reserve_calls=reserve_calls, account_available=adjusted_account)
    view.update(new_known_cost_usd=str(known),
        known_study_cost_usd=str(gate.money(binding['predecessor']['accounting']['P_known_usd']) + known),
        known_project_cost_usd=str(gate.money(binding['predecessor']['accounting']['prior_known_usd'])
                                  + gate.money(binding['predecessor']['accounting']['P_known_usd']) + known),
        cost_inference='four P originals and one R D original remain unknown; known costs only',
        known_secondary_cost_usd=str(known), new_native_cost_usd=str(new_cost),
        old_R_known_cost_usd=incident['known_cost_usd'], original_R_unknown_cost_usd=None,
        original_R_held_reservation_usd='0.14', actual_total_cost_usd=None,
        reservation_is_expense_or_proven_upper_bound=False, cost_scope='known_billed_costs_only')
    return view


def _budget(binding, plan, folder, *, existing):
    limits = accounting_view(binding, Decimal(0))['available_usd']
    return (PhaseBudget.read_completed if existing else PhaseBudget)(Path(folder) / 'budget.jsonl',
        cap=min(gate.money(v) for v in limits.values()), reserve=Decimal('.14'),
        max_calls=sum(gate.MAX_CALLS[p] * plan['counts'][p] for p in PANELS),
        binding=binding['sha256'], allow_synthetic=binding['mode'] == 'artificial_only')


def _claim(binding, control, *, create=False):
    expected = {'namespace': gate.NAMESPACE, 'binding_sha256': binding['sha256'],
        'folder': binding['folder'], 'control': binding['control'], 'owner': binding['owner'],
        'witness': binding['witness'], 'incident_sha256': canonical_hash(binding['incident'])}
    path = Path(control) / CLAIM
    _need(binding['claim_path'] == str(path.resolve()) and not path.is_symlink(), 'canonical claim differs')
    if path.exists():
        _need(gate.read_json(path) == expected, 'R01223 already claimed by another binding')
    else:
        _need(create, 'recovery claim missing')
        _save(path, expected)


def _witness_binding(binding, folder, control):
    stop = Path(folder) / 'STOP.json'
    return {'incarnation': 'r01223-' + binding['sha256'][:24], 'activation_sha256': binding['sha256'],
        'stop_sha256': file_hash(stop) if stop.exists() else ZERO, 'stop_active': stop.exists(), 'owner_generation': 1,
        'original_journal_sha256': canonical_hash(binding['incident']),
        'admission_journal_sha256': canonical_hash({'files': _all_files(folder),
            'claim': file_hash(Path(control) / CLAIM), 'original_control': _control_files(control)}),
        'admissions': _section_states(folder)}


def _witness(binding):
    return FileWitness(binding['witness'], binding['folder'])


def _publish(binding, folder, control, generation):
    return _witness(binding).checkpoint(generation, _witness_binding(binding, folder, control))['generation']


def _assert_current(binding, folder, control):
    record = _witness(binding).assert_current(_witness_binding(binding, folder, control))
    _need(not (Path(folder) / 'STOP.json').exists(), 'permanent recovery STOP')
    _need(all(v == 'settled' for v in _section_states(folder).values()), 'open section; no automatic continuation')
    return record['generation']


def _coverage(binding, coverage, *, clock, new_cost, reserve_calls):
    _need(isinstance(coverage, dict) and coverage.get('binding_sha256') == binding['sha256'], 'exact account observation required')
    if binding['mode'] != 'artificial_only':
        _require_real_evidence(coverage)
    _need(all(type(coverage.get(k)) in (int, float) and math.isfinite(coverage[k]) for k in ('observed_epoch', 'valid_until_epoch'))
          and coverage['observed_epoch'] <= clock() <= coverage['valid_until_epoch'], 'stale account coverage')
    _need(coverage.get('origin') == ('artificial_fixture' if binding['mode'] == 'artificial_only' else 'current_account_read'),
          'wrong account observation origin')
    baseline = gate.money(coverage['native_cost_at_observation_usd'])
    _need(new_cost >= baseline, 'new native cost baseline ahead')
    available = gate.money(coverage['available_usd']) - (new_cost - baseline)
    _need(available >= Decimal('.14'), 'original reservation lacks account coverage')
    return accounting_view(binding, new_cost, reserve_calls=reserve_calls, account_available=str(available))


def _runtime(binding, candidate, *, clock, panel):
    gate.runtime_guard(candidate, clock=clock, panel=panel)
    FileGuard(binding['source_files'])()
    _verify_originals(binding)
    _need(not (Path(binding['folder']) / 'STOP.json').exists(), 'permanent recovery STOP before request')
    if binding['mode'] != 'artificial_only':
        secondary._activation_gate(binding, candidate, {'plan_hash': binding['plan_hash'],
            'counts': {'P': 9040, 'R': 2952, 'T': 2952, 'F': 2952}}, clock)


def _read_block(candidate, plan, folder, number, *, arms=None, row_candidates=None):
    block = _blocks(plan)[number]
    directory = Path(folder) / 'blocks' / f'{number:06d}'
    _need(gate.read_json(directory / 'started.json') == {'block': block, 'plan_hash': plan['plan_hash']},
          'block identity changed')
    slots = block['slots'] if arms is None else [s for s in block['slots'] if s['arm'] in arms]
    attempts = {}
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
    for slot in slots:
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
        row = native._row((row_candidates or {}).get(arm, candidate), block, slot, result, config, rounds, failed, run_id)
        if gate.read_json(sd / "result.json") != row:
            raise StudyStop("saved numeric slot differs")
        block_rows.append(row)
    return block_rows, attempts

def _partial(binding, candidate, plan, root):
    incident = binding['incident']
    number = incident['completed_blocks']
    block = _blocks(plan)[number]
    directory = Path(root) / 'blocks' / f'{number:06d}'
    _need(block['panel'] == 'R', 'only an R incident is supported')
    order = [s['arm'] for s in block['slots']]
    dpos = order.index('D')
    done = order[:dpos]
    if binding['mode'] != 'artificial_only':
        _need(done == ['S-k', 'Z'] and order[dpos:] == ['D', 'S', 'Q', 'F'], 'original partial arm order changed')
    _need({p.name for p in directory.iterdir() if p.is_dir()} == set(done + ['D']), 'unexpected original partial arm')
    rows, attempts = _read_block(candidate, plan, root, number, arms=done)
    selection = gate.read_json(directory / 'selection.json')
    config, rounds, failed = native._configuration(candidate, block, 'D', selection)
    trace_record = read_journal(directory / 'D/journal.jsonl', config)
    trace = trace_record['trace']
    run_id = plan['plan_hash'][:16] + ':' + next(s['slot_id'] for s in block['slots'] if s['arm'] == 'D')
    _need(not trace_record['sealed'] and trace['run_id'] == run_id and trace['rounds'] == rounds
          and trace['failed_role'] == failed, 'original D must be exact unfinished run')
    public = gate.read_json(directory / 'public.json')
    task = TaskInput(public['task_id'], public['question'], tuple(public['paragraphs']))
    d_replays, request = [], None
    for event in trace['events']:
        if event['kind'] == 'started':
            request = Request(event['attempt_id'], task, event['role'], event['round'], event['instruction'],
                tuple(Message(**m) for m in event['messages']), event['max_output_tokens'])
        elif event['kind'] in ('completed', 'model_failed'):
            _need(request is not None and event['attempt_id'] == request.attempt_id and request.attempt_id not in attempts,
                  'duplicate original D attempt')
            attempts[request.attempt_id] = (request, event)
            d_replays.append(request.attempt_id)
    _need(request is not None and trace['events'][-1]['kind'] == 'started'
          and request.attempt_id == incident['unknown_attempt_id'] and len(d_replays) == 6,
          'exactly six D responses and one open original request required')
    names = native._provider_files(root, incident['unknown_provider_index'])
    _need(names['request'].read_bytes() == encoded(payload(request, producer_limit=1024))
          and file_hash(names['request']) == incident['request_sha256']
          and gate.read_json(names['binding']) == {'attempt_id': request.attempt_id,
              'request_sha256': incident['request_sha256'], 'mode': 'synthetic' if binding['mode'] == 'artificial_only' else 'live'}
          and all(not names[k].exists() for k in ('response', 'received', 'billing')),
          'original unknown request bytes or missing-response status changed')
    return rows, attempts, d_replays, request


def _provider_check(binding, root, index, physical, logical, usage, attempt, generations):
    request, event = attempt
    names = native._provider_files(root, index)
    raw = names['response'].read_bytes()
    billed, generation = decode_billing(raw)
    response = decode_outcome(raw, request.max_output_tokens, F01)
    if binding['mode'] == 'artificial_only':
        response = replace(response, usage=replace(response.usage, cost_source='synthetic'))
    _need(names['request'].read_bytes() == encoded(payload(request, producer_limit=1024))
          and native._terminal(logical, response) == event and generation not in generations
          and gate.read_json(names['binding']) == {'attempt_id': physical, 'request_sha256': file_hash(names['request']),
                'mode': 'synthetic' if binding['mode'] == 'artificial_only' else 'live'}
          and gate.read_json(names['billing']) == {'generation_id': generation, 'usage': usage, 'response_sha256': file_hash(names['response'])}
          and gate.read_json(names['received']) == {'http_status': 200, 'response_sha256': file_hash(names['response'])}
          and billed.cost_usd == gate.money(usage['cost_usd']), 'provider billing/request/outcome provenance differs')
    generations.add(generation)
    return response


def _original_state(binding, candidate, plan, root):
    incident = binding['incident']
    candidate = binding['original_candidate']
    _need(_all_files(root) == incident['original_inventory'], 'copied original evidence differs')
    old, cost, unknown = _old_ledger({**binding['original_binding'], '_plan_counts': plan['counts']})
    _need(len(old) == incident['known_calls'] and cost == gate.money(incident['known_cost_usd'])
          and unknown == incident['unknown_attempt_id'] and incident['unknown_provider_index'] == len(old) + 1,
          'original ledger does not match the bound incident')
    rows, attempts, complete = [], {}, incident['completed_blocks']
    _need(len(list((Path(root) / 'blocks').glob('*/complete.json'))) == complete
          and len(list((Path(root) / 'blocks').glob('*/started.json'))) == complete + 1, 'original block prefix changed')
    for number in range(complete):
        block_rows, block_attempts = _read_block(candidate, plan, root, number)
        _verify_block_proof(root, plan, number, block_rows)
        _need(not set(attempts) & set(block_attempts), 'duplicate original logical attempt')
        rows.extend(block_rows)
        attempts.update(block_attempts)
    partial_rows, partial_attempts, replays, unknown_request = _partial(binding, candidate, plan, root)
    _need(not set(attempts) & set(partial_attempts), 'duplicate partial attempt')
    attempts.update(partial_attempts)
    _need({k: v[1]['usage'] for k, v in attempts.items()} == dict(old), 'original known ledger and logical evidence differ')
    generations, responses = set(), {}
    for index, (attempt, usage) in enumerate(old, 1):
        responses[attempt] = _provider_check(binding, root, index, attempt, attempt, usage, attempts[attempt], generations)
    # All original core files must be claimed, including the one open request.
    expected = {'budget.jsonl'}
    for number in range(complete):
        proof_path = Path(root) / 'blocks' / f'{number:06d}/complete.json'
        expected.update(gate.read_json(proof_path)['evidence'])
        expected.add(str(proof_path.relative_to(root)))
    expected.update(str(p.relative_to(root)) for p in (Path(root) / 'blocks' / f'{complete:06d}').rglob('*') if p.is_file())
    for index in range(1, len(old) + 1):
        expected.update(str(p.relative_to(root)) for p in native._provider_files(root, index).values())
    expected.update(str(native._provider_files(root, len(old) + 1)[k].relative_to(root)) for k in ('request', 'binding'))
    _need(set(secondary._inventory(root)) == expected, 'unclaimed original core evidence')
    admissions = secondary._admissions(root)
    _need(admissions == {**{'request-' + canonical_hash(k): 'settled' for k, _ in old},
        'request-' + canonical_hash(unknown): 'unknown'}, 'original request admissions changed')
    return rows, attempts, old, generations, responses, replays, unknown_request


def _verify_block_proof(root, plan, number, rows):
    path = Path(root) / 'blocks' / f'{number:06d}/complete.json'
    proof = gate.read_json(path)
    _need(proof['block'] == _blocks(plan)[number] and proof['plan_hash'] == plan['plan_hash'] and proof['rows'] == rows,
          'complete block rows or binding differ')
    for name, checksum in proof['evidence'].items():
        relative = Path(name)
        _need(not relative.is_absolute() and '..' not in relative.parts and file_hash(Path(root) / relative) == checksum,
              'complete block evidence differs')
    return proof


def _inventory(folder):
    return {name: value for name, value in _all_files(folder).items()
            if name in ('budget.jsonl', 'replacement.json') or name.startswith(('blocks/', 'provider/', 'original/'))}


def _inspect(binding, candidate, plan, folder):
    folder = Path(folder)
    original = folder / 'original'
    old_rows, old_attempts, old_settlements, generations, _, replays, _ = _original_state(binding, candidate, plan, original)
    budget = _budget(binding, plan, folder, existing=True)
    prefix = binding['incident']['completed_blocks']
    started = sorted((folder / 'blocks').glob('*/started.json'))
    complete = sorted((folder / 'blocks').glob('*/complete.json'))
    _need(len(started) == len(complete), 'incomplete recovery block cannot continue')
    rows, attempts = list(old_rows), dict(old_attempts)
    # On completion, the partial block contributes its known calls once through
    # the new logical journal, with exact equality to retained original events.
    expected = {'budget.jsonl'} | {'original/' + k for k in binding['incident']['original_inventory']}
    for offset, path in enumerate(complete):
        number = prefix + offset
        _need(path == folder / 'blocks' / f'{number:06d}/complete.json'
              and started[offset] == folder / 'blocks' / f'{number:06d}/started.json', 'noncontiguous recovery blocks')
        row_candidates = {arm: binding['original_candidate'] for arm in _blocks(plan)[number]['arm_order'][:_blocks(plan)[number]['arm_order'].index('D')]} if number == prefix else {}
        block_rows, block_attempts = _read_block(candidate, plan, folder, number, row_candidates=row_candidates)
        proof = _verify_block_proof(folder, plan, number, block_rows)
        for logical, event in block_attempts.items():
            if logical in attempts:
                _need(number == prefix and attempts[logical] == event, 'changed or repeated retained logical attempt')
            attempts[logical] = event
        expected.update(proof['evidence'])
        expected.add(str(path.relative_to(folder)))
        rows.extend(block_rows)
    replacement = binding['incident']['unknown_attempt_id'] + ':r01223:replacement:1'
    settlement_map = dict(old_settlements)
    for index, (physical, usage) in enumerate(budget.settlements, 1):
        logical = binding['incident']['unknown_attempt_id'] if physical == replacement else physical
        _need(logical not in settlement_map and logical in attempts, 'duplicate physical/logical cost attribution')
        _need(attempts[logical][1]['usage'] == usage, 'new ledger usage differs from logical outcome')
        _provider_check(binding, folder, index, physical, logical, usage, attempts[logical], generations)
        settlement_map[logical] = usage
        expected.update(str(p.relative_to(folder)) for p in native._provider_files(folder, index).values())
    _need({k: v[1]['usage'] for k, v in attempts.items()} == settlement_map, 'mixed ledger reconciliation failed')
    if budget.calls:
        _need(complete and budget.settlements[0][0] == replacement, 'first new call must be the single replacement')
        expected.add('replacement.json')
        _need(gate.read_json(folder / 'replacement.json') == _replacement_record(binding), 'single replacement intent differs')
    else:
        _need(not complete and not (folder / 'replacement.json').exists(), 'unused recovery has unexpected evidence')
    _need(_admissions(folder) == {'request-' + canonical_hash(k): 'settled' for k, _ in budget.settlements},
          'new admissions differ from new native ledger')
    evidence = _inventory(folder)
    _need(set(evidence) == expected, 'unclaimed recovery files')
    known = gate.money(binding['incident']['known_cost_usd']) + budget.cost
    if complete:
        _need(sum((gate.money(r['cost_usd']) for r in rows), Decimal(0)) == known,
              'rows do not contain old and new known costs exactly once')
    state = {'execution_binding_sha256': gate.execution_binding(candidate), 'plan_hash': plan['plan_hash'],
        'completed_blocks': plan['counts']['P'] + prefix + len(complete),
        'secondary_completed_blocks': prefix + len(complete), 'complete': prefix + len(complete) == len(_blocks(plan)),
        'rows': rows, 'budget': budget.snapshot(), 'levels': accounting_view(binding, budget.cost),
        'generation_ids': sorted(generations), 'evidence': evidence,
        'original_unknown': {'attempt_id': binding['incident']['unknown_attempt_id'], 'cost_usd': None,
                             'held_reservation_usd': '0.14'},
        'original_known_calls': binding['incident']['known_calls'], 'local_D_replays': len(replays),
        'cost_scope': 'known_billed_costs_only', 'continuous_arm_latency_available': False}
    state['state_sha256'] = canonical_hash(state)
    return state, budget


def _replacement_record(binding):
    incident = binding['incident']
    return {'author_decision': 'D-076' if binding['mode'] != 'artificial_only' else 'artificial_only',
        'logical_attempt_id': incident['unknown_attempt_id'],
        'physical_attempt_id': incident['unknown_attempt_id'] + ':r01223:replacement:1',
        'original_request_sha256': incident['request_sha256'], 'original_provider_index': incident['unknown_provider_index'],
        'incident_sha256': canonical_hash(incident), 'maximum_replacements': 1}


def initialize(binding, candidate, plan, *, folder, control, clock):
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        folder = Path(folder)
        _need(not folder.exists() or not any(folder.iterdir()), 'new recovery output must be empty')
        # Validate ALL retained evidence and exact original request before claim.
        _original_state(binding, candidate, plan, Path(binding['original_binding']['folder']))
        _claim(binding, control, create=True)
        for name in ('blocks', 'provider', 'receipts', 'admissions', 'panels', 'sections'):
            (folder / name).mkdir(parents=True, exist_ok=True)
        shutil.copytree(binding['original_binding']['folder'], folder / 'original')
        _need(_all_files(folder / 'original') == binding['incident']['original_inventory'], 'original copy failed exact reread')
        _save(folder / 'binding.json', binding)
        _budget(binding, plan, folder, existing=False)
        _witness(binding).initialize(_witness_binding(binding, folder, control))
        return {'binding_sha256': binding['sha256'], 'next_block': _blocks(plan)[binding['incident']['completed_blocks']]['block_id'],
                'first_hold': binding['first_hold']}

def run_section(binding, candidate, plan, *, folder, control, section_end, coverage,
                loader, spatial_selector, temporal_selector, transport, checkpoint, clock):
    dependencies = dict(loader=loader, spatial_selector=spatial_selector, temporal_selector=temporal_selector,
                        transport=transport, checkpoint=checkpoint)
    folder = Path(folder)
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock, dependencies=dependencies)
        _claim(binding, control)
        generation = _assert_current(binding, folder, control)
        state, budget = _inspect(binding, candidate, plan, folder)
        prefix = state['secondary_completed_blocks']
        recovered = prefix > binding['incident']['completed_blocks']
        if recovered:
            _verify_receipt(folder, state)
            _verify_confirmation(binding, folder, state)
        later = [n for n in candidate['section_ends'] if n > state['completed_blocks']]
        expected_end = later[0] if recovered and later else binding['first_hold']
        _need(type(section_end) is int and section_end == expected_end, 'only the bound next recovery/original hold may run')
        blocks, end = _blocks(plan), section_end - plan['counts']['P']
        _need(prefix < end <= len(blocks) and blocks[prefix]['panel'] == blocks[end-1]['panel'], 'section crosses panel boundary')
        panel = blocks[prefix]['panel']
        if panel != 'R':
            _verify_panel_closeout(binding, candidate, plan, folder, PANELS[PANELS.index(panel)-1])
        _coverage(binding, coverage, clock=clock, new_cost=budget.cost, reserve_calls=gate.MAX_CALLS[panel])
        _need(gate.money(coverage['native_cost_at_observation_usd']) == budget.cost, 'section requires current new-native baseline')
        _save(folder / 'coverage' / f"{state['completed_blocks']:06d}.json", coverage)
        _record_section(folder, section_end, 'admitted')
        generation = _publish(binding, folder, control, generation)
        adapter = StudyAdapter(folder / 'provider', transport, budget,
                               synthetic=binding['mode'] == 'artificial_only', failure_policy=F01)
        adapter.generations.update(state['generation_ids'])
        try:
            for number in range(prefix, end):
                block = blocks[number]
                _runtime(binding, candidate, clock=clock, panel=panel)
                _coverage(binding, coverage, clock=clock, new_cost=budget.cost, reserve_calls=gate.MAX_CALLS[panel])
                _need(budget.calls + gate.MAX_CALLS[panel] <= budget.max_calls, 'whole block exceeds call bound')
                directory = folder / 'blocks' / f'{number:06d}'
                directory.mkdir()
                first_call = budget.calls + 1
                recovering = number == binding['incident']['completed_blocks']
                if recovering:
                    original = folder / 'original'
                    old_rows, old_attempts, _, _, responses, replay_ids, unknown_request = _original_state(binding, candidate, plan, original)
                    old_dir = original / 'blocks' / f'{number:06d}'
                    for path in old_dir.iterdir():
                        if path.is_file():
                            shutil.copyfile(path, directory / path.name)
                    public, private = gate.read_json(directory / 'public.json'), gate.read_json(directory / 'reference.json')
                    task = TaskInput(public['task_id'], public['question'], tuple(public['paragraphs']))
                    reference = AnswerReference(private['task_id'], tuple(private['answers']))
                    selection = gate.read_json(directory / 'selection.json')
                    done_arms = block['arm_order'][:block['arm_order'].index('D')]
                    for arm in done_arms:
                        shutil.copytree(old_dir / arm, directory / arm)
                    replay_position = 0
                else:
                    _save(directory / 'started.json', {'block': block, 'plan_hash': plan['plan_hash']})
                    task, reference = loader(block['task_id'])
                    _need(type(task) is TaskInput and type(reference) is AnswerReference
                          and task.task_id == native.public_task_id(plan, block['task_id']) and reference.task_id == task.task_id,
                          'loader returned foreign task/reference')
                    _save(directory / 'public.json', asdict(task))
                    _save(directory / 'reference.json', asdict(reference))
                    q = native._select_observed(spatial_selector, task, candidate=candidate, plan=plan, block=block,
                                               kind='spatial', directory=directory)
                    qt = native._select_observed(temporal_selector, task, candidate=candidate, plan=plan, block=block,
                                                kind='temporal', directory=directory) if panel == 'T' else None
                    _need(q in {c.config_id for c in bank()} and (panel != 'T' or type(qt) is int and qt in (1, 2)),
                          'selection outside frozen bank')
                    selection = {'spatial_q': q, 'temporal_qst': qt}
                    _save(directory / 'selection.json', selection)
                    done_arms, replay_ids, replay_position = [], [], 0

                def send(request):
                    nonlocal replay_position
                    _runtime(binding, candidate, clock=clock, panel=panel)
                    if recovering and replay_position < len(replay_ids):
                        expected_id = replay_ids[replay_position]
                        _need(request.attempt_id == expected_id and request == old_attempts[expected_id][0],
                              'D replay order or complete request body differs')
                        replay_position += 1
                        return responses[expected_id]
                    if recovering and request.attempt_id == binding['incident']['unknown_attempt_id']:
                        _need(replay_position == 6 and request == unknown_request
                              and sha256(encoded(payload(request, producer_limit=1024))).hexdigest() == binding['incident']['request_sha256']
                              and not (folder / 'replacement.json').exists() and budget.calls == 0,
                              'single replacement body or unused right differs')
                        _save(folder / 'replacement.json', _replacement_record(binding))
                        physical = replace(request, attempt_id=_replacement_record(binding)['physical_attempt_id'])
                    else:
                        _need(request.attempt_id not in old_attempts if recovering else True, 'successful original call may never be resent')
                        physical = request
                    _coverage(binding, coverage, clock=clock, new_cost=budget.cost, reserve_calls=1)
                    _need(physical.attempt_id not in budget.ids, 'duplicate new physical request')
                    _record_admission(folder, physical, 'admitted')
                    try:
                        response = adapter(physical)
                    except BaseException:
                        _record_admission(folder, physical, 'unknown')
                        raise
                    _record_admission(folder, physical, 'settled')
                    return response

                rows = []
                for slot in block['slots']:
                    _runtime(binding, candidate, clock=clock, panel=panel)
                    arm, sd = slot['arm'], directory / slot['arm']
                    if arm in done_arms:
                        rows.append(gate.read_json(sd / 'result.json'))
                        continue
                    sd.mkdir()
                    run_id = plan['plan_hash'][:16] + ':' + slot['slot_id']
                    config, rounds, failed = native._configuration(candidate, block, arm, selection)
                    if config is None:
                        result = native._direct(task, reference, run_id, arm, 0 if arm == 'S' else block['tie_break_seed'], sd, send)
                    else:
                        execute(task, config, send, rounds=rounds, failed_role=failed, run_id=run_id,
                                journal_path=sd / 'journal.jsonl', producer_limit=1024, failure_policy=F01)
                        result, _ = native._mas_result(sd / 'journal.jsonl', config, task, reference, block)
                    row = native._row(candidate, block, slot, result, config, rounds, failed, run_id)
                    _save(sd / 'result.json', row)
                    rows.append(row)
                if recovering:
                    _need(replay_position == 6, 'six original D responses not consumed exactly once')
                    _save(directory / 'replay.json', {'logical_attempts': replay_ids, 'replayed_locally': True,
                        'new_physical_calls_for_replays': 0, 'new_native_cost_for_replays_usd': '0',
                        'original_D_journal_sha256': file_hash(old_dir / 'D/journal.jsonl'),
                        'original_selection_measurement_sha256': file_hash(old_dir / 'spatial-measurement.json'),
                        'continuous_arm_latency_available': False})
                files = [p for p in directory.rglob('*') if p.is_file()]
                for index in range(first_call, budget.calls + 1):
                    files.extend(native._provider_files(folder, index).values())
                _save(directory / 'complete.json', {'block': block, 'plan_hash': plan['plan_hash'], 'rows': rows,
                    'evidence': {str(p.relative_to(folder)): file_hash(p) for p in files}})
            state, _ = _inspect(binding, candidate, plan, folder)
            _checkpoint(folder, state, checkpoint)
            _record_section(folder, section_end, 'settled')
            _publish(binding, folder, control, generation)
            return state
        except BaseException as error:
            try:
                _save(folder / 'STOP.json', {'binding_sha256': binding['sha256'], 'error_type': type(error).__name__,
                    'retry_allowed': False, 'diagnostic': safe_exception_chain(error, clock)})
                _publish(binding, folder, control, generation)
            except BaseException as recording_error:
                error.add_note('Recovery STOP/witness recording failed: ' + type(recording_error).__name__)
            raise


def safe_exception_chain(error, clock):
    entries, seen = [], set()
    while error is not None and id(error) not in seen and len(entries) < 8:
        seen.add(id(error))
        item = {'class': type(error).__module__ + '.' + type(error).__name__}
        value = getattr(error, 'errno', None)
        if type(value) is int:
            item['errno'] = value
        entries.append(item)
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return {'observed_epoch': clock(), 'exception_classes': entries, 'messages_or_payloads_saved': False}


def _analysis(binding, plan, panel, rows, contract):
    from .final_analysis import analyze_panel as original_analysis
    result = original_analysis(plan, panel, rows, bootstrap_seed=contract['primary_bootstrap_seed'])
    return {'schema': 'z52-known-cost-panel-analysis/v1', 'original_analysis': result,
        'cost_scope': 'known_billed_costs_only' if panel == 'R' else 'complete_known_panel_costs',
        'original_R_unknown': {'attempt_id': binding['incident']['unknown_attempt_id'], 'cost_usd': None,
                               'reservation_usd': '0.14', 'reservation_is_expense_or_upper_bound': False},
        'affected_arms': ['D'] if panel == 'R' else [], 'affected_cost_endpoints': ['R03', 'R08'] if panel == 'R' else [],
        'D_actual_cost_identity': 'known_D_cost_plus_unknown_nonnegative_u' if panel == 'R' else None,
        'unconditional_actual_cost_ratio_claim': False if panel == 'R' else None,
        'zero_cost_imputation': False, 'actual_total_project_cost_usd': None,
        'continuous_interrupted_D_latency_available': False}


def _panel_evidence(plan, folder, panel):
    folder, evidence = Path(folder), {}
    original_count = len(list((folder / 'original/blocks').glob('*/complete.json')))
    for number, block in enumerate(_blocks(plan)):
        if block['panel'] != panel:
            continue
        root = folder / 'original' if number < original_count else folder
        complete = root / 'blocks' / f'{number:06d}/complete.json'
        proof = gate.read_json(complete)
        _need(proof['block'] == block and proof['plan_hash'] == plan['plan_hash'], 'panel block identity differs')
        prefix = 'original/' if root != folder else ''
        evidence.update({prefix + k: v for k, v in proof['evidence'].items()})
        evidence[str(complete.relative_to(folder))] = file_hash(complete)
    # Includes the original partial D/unknown and poisoned original ledger, all immutable.
    if panel == 'R':
        evidence.update({'original/' + k: v for k, v in _all_files(folder / 'original').items()})
        evidence['replacement.json'] = file_hash(folder / 'replacement.json')
    analysis = folder / 'panels' / panel / 'analysis.json'
    evidence[str(analysis.relative_to(folder))] = file_hash(analysis)
    _need('budget.jsonl' not in evidence, 'growing new ledger cannot be frozen as panel member')
    return evidence
