"""Additive clean R87 continuation; native D-076 data and accounting stay intact.

The inner binding owns scientific provenance and the single native ledger. The
outer binding owns the new canonical writer, witness, receipts and activation.
No recovery/replay code is dispatched from this clean-prefix connection.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import shutil

from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01
from communication_pruning.study import StudyAdapter, FileGuard, file_hash
from project.research_control.recovery import FileWitness
from . import final_r_resume as inner, final_secondary as secondary
from . import final_execution as native, final_preflight as gate
from .final_plan import canonical_hash

StudyStop = gate.StudyStop
PANELS, ZERO = secondary.PANELS, secondary.ZERO
CLAIM = 'r-recovery-01223/clean-R00087/claim.json'
DATA_NAMES = ('original', 'blocks', 'provider', 'admissions', 'budget.jsonl', 'replacement.json')
_need, _save, _path, _all_files = secondary._need, secondary._save, secondary._path, secondary._all_files
_blocks, _section_states, _record_section = secondary._blocks, secondary._section_states, secondary._record_section
_receipt_path, _verify_receipt, _checkpoint = secondary._receipt_path, secondary._verify_receipt, secondary._checkpoint
_verify_confirmation = secondary._verify_confirmation
_verify_ledger_prefix, _verify_panel_remote = secondary._verify_ledger_prefix, secondary._verify_panel_remote
_record_admission = secondary._record_admission
_require_real_evidence = secondary._require_real_evidence
safe_exception_chain = inner.safe_exception_chain
connection_hash = secondary.connection_hash


def additional_sources():
    result = inner.additional_sources()
    paths = [Path(__file__), Path(__file__).with_name('final_r_clean_resume_operator.py'),
             Path(__file__).parents[1] / 'tests/test_final_r_clean_resume.py']
    result.update({str(p.resolve()): file_hash(p) for p in paths})
    return result


def _data_files(folder):
    return {k: v for k, v in _all_files(folder).items() if k.split('/')[0] in DATA_NAMES}


def prepare_origin(inner_binding, candidate, plan, *, review, backup):
    """Read and inspect the stopped prefix; expose no answers in this record."""
    gate._check_seal(inner_binding)
    folder = Path(inner_binding['folder'])
    stop = gate.read_json(folder / 'STOP.json')
    _need(stop.get('retry_allowed') is False, 'retained permanent STOP required')
    state, budget = inner._inspect(inner_binding, candidate, plan, folder)
    prefix = state['secondary_completed_blocks']
    _need(inner_binding['incident']['completed_blocks'] < prefix < plan['counts']['R'],
          'clean incomplete R panel prefix required')
    raw = (folder / 'budget.jsonl').read_bytes()
    ledger = {'bytes': len(raw), 'sha256': sha256(raw).hexdigest(), 'lines': len(raw.splitlines()),
              'calls': budget.calls, 'known_cost_usd': str(budget.cost)}
    record = gate.read_json(gate.evidence_file(review))
    expected = {'inner_binding_sha256': inner_binding['sha256'],
                'inherited_state_sha256': state['state_sha256'], 'completed_blocks': state['completed_blocks'],
                'ledger_sha256': ledger['sha256']}
    _need(all(record.get(k) == v for k, v in expected.items()) and record.get('accepted') is True
          and record.get('not_implementation_author') is True
          and isinstance(record.get('reviewer'), str) and record['reviewer'].strip()
          and record['reviewer'] != inner_binding['owner'], 'separate exact stopped-prefix review required')
    gate.evidence_file(backup)
    regular = sorted(int(p.stem) for p in (folder / 'confirmations').glob('*.json'))
    _need(bool(regular) and regular[-1] < state['completed_blocks'], 'earlier regular hold required')
    return {'schema': 'z52-clean-R87-origin/v1', 'inner_binding_sha256': inner_binding['sha256'],
        'inherited_state_sha256': state['state_sha256'], 'completed_blocks': state['completed_blocks'],
        'secondary_completed_blocks': prefix, 'last_regular_hold': regular[-1],
        'original_inventory': _all_files(folder), 'data_inventory': _data_files(folder),
        'witness_inventory': _all_files(inner_binding['witness']),
        'claim_sha256': file_hash(Path(inner_binding['control']) / inner.CLAIM),
        'stop_sha256': file_hash(folder / 'STOP.json'), 'ledger_prefix': ledger,
        'review': deepcopy(review), 'backup': deepcopy(backup)}


def prepare_binding(candidate, plan, *, inner_binding, origin, folder, control, witness, owner, activation=None):
    return gate.seal({'schema': 'z52-clean-R87-resume/v1', 'mode': candidate['mode'],
        'candidate_sha256': candidate['sha256'], 'plan_hash': plan['plan_hash'],
        'execution_binding_sha256': gate.execution_binding(candidate),
        'scientific_candidate_sha256': inner_binding['scientific_candidate_sha256'],
        'folder': str(_path(folder)), 'control': str(_path(control)), 'witness': str(_path(witness)),
        'owner': owner, 'owner_generation': 1, 'claim_path': str(_path(control) / CLAIM),
        'inner_binding': deepcopy(inner_binding), 'origin': deepcopy(origin),
        'first_hold': next(n for n in candidate['section_ends'] if n > origin['completed_blocks']),
        'predecessor': deepcopy(inner_binding['predecessor']),
        'analysis_contract': deepcopy(inner_binding['analysis_contract']),
        'source_files': additional_sources(), 'activation': deepcopy(activation)})


def _verify_originals(binding):
    old, origin = binding['inner_binding'], binding['origin']
    inner._verify_originals(old)
    _need(_all_files(old['folder']) == origin['original_inventory']
          and _data_files(old['folder']) == origin['data_inventory']
          and _all_files(old['witness']) == origin['witness_inventory']
          and file_hash(Path(old['control']) / inner.CLAIM) == origin['claim_sha256']
          and file_hash(Path(old['folder']) / 'STOP.json') == origin['stop_sha256'],
          'immutable stopped R87 evidence changed')
    for name in ('review', 'backup'):
        gate.evidence_file(origin[name])


def _activation_gate(binding, candidate, plan, clock):
    secondary._activation_gate(binding, candidate, plan, clock)
    if binding['mode'] != 'artificial_only':
        record = gate.read_json(gate.evidence_file(binding['activation']))
        _need(record.get('author_decision') == 'D-075/D-076' and record.get('clean_resume') is True
              and record.get('origin_sha256') == canonical_hash(binding['origin'])
              and record.get('no_new_unknown_replacement') is True, 'exact clean continuation activation required')


def _check_binding(binding, candidate, plan, *, folder, control, clock, dependencies=None):
    gate._check_seal(binding)
    old, origin = binding['inner_binding'], binding['origin']
    gate._check_seal(old)
    expected = Path(old['folder']).parent / 'continuation-R00087'
    _need(binding.get('schema') == 'z52-clean-R87-resume/v1' and binding['mode'] == candidate['mode'],
          'specific clean R87 connection required')
    _need(binding['folder'] == str(_path(folder)) == str(expected / 'live')
          and binding['witness'] == str(_path(binding['witness'])) == str(expected / 'witness')
          and binding['control'] == str(_path(control)) == old['control'] == candidate['control_directory']
          and binding['claim_path'] == str(_path(control) / CLAIM), 'canonical clean continuation path changed')
    _need(old['candidate_sha256'] == binding['candidate_sha256'] == candidate['sha256']
          and old['plan_hash'] == binding['plan_hash'] == plan['plan_hash']
          and old['execution_binding_sha256'] == binding['execution_binding_sha256'] == gate.execution_binding(candidate)
          and old['source_files'] == inner.additional_sources(), 'inner scientific/native identity changed')
    _need(binding['source_files'] == additional_sources() and binding['owner_generation'] == 1
          and isinstance(binding['owner'], str) and binding['owner'].strip(), 'one exact source-bound owner required')
    _need(binding['analysis_contract'] == old['analysis_contract'] and binding['predecessor'] == old['predecessor']
          and origin['inner_binding_sha256'] == old['sha256'], 'inherited contract/provenance changed')
    _need(binding['first_hold'] == next(n for n in candidate['section_ends'] if n > origin['completed_blocks']),
          'first original hold changed')
    _verify_originals(binding)
    secondary._preflight(binding, candidate, plan, control=control, clock=clock, dependencies=dependencies)
    _analysis_contract(binding, candidate, plan)
    if binding['mode'] != 'artificial_only':
        _need(old['sha256'] == '0636e6862e4ddcb234c6584510818cab2365cb845c54ebfc9809d9a9a80c0afe'
              and origin['completed_blocks'] == 9127 and origin['secondary_completed_blocks'] == 87
              and origin['last_regular_hold'] == 9079 and binding['first_hold'] == 9140
              and origin['stop_sha256'] == 'd1167b47878f8bcc4b6069f05a445f51ab936ab71e3da223bbe649049b298633'
              and origin['backup']['sha256'] == '24dc4c7f27f3a90b6c344ea5a001312247985fd04cb05b78315e7a97f6025255'
              and origin['ledger_prefix'] == {'bytes': 1331995, 'lines': 3131, 'calls': 1565,
                  'known_cost_usd': '0.38259674',
                  'sha256': 'cfe9e9b327bcb62b63ab58a64c08f1dd1e114396a02432c0536d0d46421ed539'},
              'only the exact clean R87 stop is authorized')
    _activation_gate(binding, candidate, plan, clock)


def _claim(binding, control, *, create=False):
    expected = {'namespace': gate.NAMESPACE, 'binding_sha256': binding['sha256'],
        'folder': binding['folder'], 'control': binding['control'], 'witness': binding['witness'],
        'owner': binding['owner'], 'origin_sha256': canonical_hash(binding['origin'])}
    path = Path(control) / CLAIM
    _need(binding['claim_path'] == str(path.resolve()) and not path.is_symlink(), 'canonical clean claim differs')
    if path.exists():
        _need(not create and gate.read_json(path) == expected, 'clean R87 right already claimed')
    else:
        _need(create, 'clean R87 claim missing')
        _save(path, expected)


def _witness_binding(binding, folder, control):
    stop = Path(folder) / 'STOP.json'
    return {'incarnation': 'clean-R87-' + binding['sha256'][:24], 'activation_sha256': binding['sha256'],
        'stop_sha256': file_hash(stop) if stop.exists() else ZERO, 'stop_active': stop.exists(), 'owner_generation': 1,
        'original_journal_sha256': canonical_hash(binding['origin']),
        'admission_journal_sha256': canonical_hash({'files': _all_files(folder),
            'claim': file_hash(Path(control) / CLAIM), 'inner_claim': binding['origin']['claim_sha256']}),
        'admissions': _section_states(folder)}


def _witness(binding):
    return FileWitness(binding['witness'], binding['folder'])


def _publish(binding, folder, control, generation):
    return _witness(binding).checkpoint(generation, _witness_binding(binding, folder, control))['generation']


def _assert_current(binding, folder, control):
    record = _witness(binding).assert_current(_witness_binding(binding, folder, control))
    _need(not (Path(folder) / 'STOP.json').exists(), 'permanent clean continuation STOP')
    _need(all(v == 'settled' for v in _section_states(folder).values()), 'open clean section; no retry')
    return record['generation']


def accounting_view(binding, native_cost, **kwargs):
    return inner.accounting_view(binding['inner_binding'], native_cost, **kwargs)


def _coverage(binding, coverage, *, clock, new_cost, reserve_calls):
    _need(coverage.get('binding_sha256') == binding['sha256'], 'outer coverage authority required')
    return inner._coverage(binding['inner_binding'],
        {**coverage, 'binding_sha256': binding['inner_binding']['sha256']},
        clock=clock, new_cost=new_cost, reserve_calls=reserve_calls)


def _runtime(binding, candidate, *, clock, panel):
    gate.runtime_guard(candidate, clock=clock, panel=panel)
    FileGuard(binding['source_files'])()
    _verify_originals(binding)
    _need(not (Path(binding['folder']) / 'STOP.json').exists(), 'permanent clean STOP before request')
    _activation_gate(binding, candidate, {'plan_hash': binding['plan_hash'],
        'counts': {'P': 9040, 'R': 2952, 'T': 2952, 'F': 2952}}, clock)


def _inspect(binding, candidate, plan, folder):
    old, origin = binding['inner_binding'], binding['origin']
    folder = Path(folder)
    prefix = origin['ledger_prefix']
    _verify_ledger_prefix(folder, {'bytes': prefix['bytes'], 'sha256': prefix['sha256']})
    for name, checksum in origin['data_inventory'].items():
        if name != 'budget.jsonl':
            _need(file_hash(folder / name) == checksum, 'inherited clean-prefix member changed')
    state, budget = inner._inspect(old, candidate, plan, folder)
    _need(state['secondary_completed_blocks'] >= origin['secondary_completed_blocks']
          and budget.calls >= prefix['calls'] and budget.cost >= gate.money(prefix['known_cost_usd']),
          'inherited complete prefix regressed')
    inherited_hash = state['state_sha256']
    if state['completed_blocks'] == origin['completed_blocks']:
        _need(inherited_hash == origin['inherited_state_sha256'], 'initial native adoption differs')
    provenance = {'origin': origin, 'inner_binding_sha256': old['sha256'],
                  'adoption_kind': 'technical_clean_prefix_adoption',
                  'last_regular_hold': origin['last_regular_hold'], 'first_original_hold': binding['first_hold']}
    _need(gate.read_json(folder / 'provenance.json') == provenance
          and gate.read_json(folder / 'binding.json') == binding, 'outer adoption provenance changed')
    state.update(binding_sha256=binding['sha256'], connection_sha256=connection_hash(binding),
        inner_binding_sha256=old['sha256'], inner_state_sha256=inherited_hash,
        origin_sha256=canonical_hash(origin), inherited_native_calls=prefix['calls'],
        continuation_new_calls=budget.calls - prefix['calls'],
        continuation_new_known_cost_usd=str(budget.cost - gate.money(prefix['known_cost_usd'])),
        checkpoint_kind='technical_clean_prefix_adoption' if state['completed_blocks'] == origin['completed_blocks']
                        else 'original_planned_hold')
    state['evidence'].update({name: file_hash(folder / name) for name in ('binding.json', 'provenance.json')})
    state.pop('state_sha256')
    state['state_sha256'] = canonical_hash(state)
    return state, budget


def _analysis_contract(binding, candidate, plan):
    return inner._analysis_contract(binding['inner_binding'], candidate, plan)


def _analysis(binding, plan, panel, rows, contract):
    return inner._analysis(binding['inner_binding'], plan, panel, rows, contract)


def _panel_evidence(plan, folder, panel):
    return {**inner._panel_evidence(plan, folder, panel),
            **{name: file_hash(Path(folder) / name) for name in ('binding.json', 'provenance.json')}}


def initialize(binding, candidate, plan, *, folder, control, clock, checkpoint):
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        folder = Path(folder)
        _need(not folder.exists() or not any(folder.iterdir()), 'clean continuation output must be empty')
        old = binding['inner_binding']
        actual = prepare_origin(old, candidate, plan, review=binding['origin']['review'], backup=binding['origin']['backup'])
        _need(actual == binding['origin'], 'complete origin inspection changed')
        _claim(binding, control, create=True)
        folder.mkdir(parents=True, exist_ok=True)
        for name in DATA_NAMES:
            source, target = Path(old['folder']) / name, folder / name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copyfile(source, target)
        _need(_data_files(folder) == binding['origin']['data_inventory'], 'byte-exact adoption failed')
        for name in ('receipts', 'panels', 'sections'):
            (folder / name).mkdir()
        _save(folder / 'binding.json', binding)
        _save(folder / 'provenance.json', {'origin': binding['origin'], 'inner_binding_sha256': old['sha256'],
            'adoption_kind': 'technical_clean_prefix_adoption',
            'last_regular_hold': binding['origin']['last_regular_hold'], 'first_original_hold': binding['first_hold']})
        state, _ = _inspect(binding, candidate, plan, folder)
        _checkpoint(folder, state, checkpoint)
        _witness(binding).initialize(_witness_binding(binding, folder, control))
        return state

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


def pre_dispatch(binding, candidate, plan, *, folder, control, clock, section_end, coverage):
    """Read-only own-session gate before encoder construction or credential use."""
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        _assert_current(binding, folder, control)
        state, budget = _inspect(binding, candidate, plan, folder)
        _verify_receipt(folder, state)
        _verify_confirmation(binding, folder, state)
        later = [n for n in candidate['section_ends'] if n > state['completed_blocks']]
        _need(bool(later) and type(section_end) is int and section_end == later[0],
              'only the next original hold may dispatch')
        prefix, end = state['secondary_completed_blocks'], section_end - plan['counts']['P']
        blocks = _blocks(plan)
        _need(prefix < end <= len(blocks) and blocks[prefix]['panel'] == blocks[end - 1]['panel'],
              'dispatch crosses panel boundary')
        panel = blocks[prefix]['panel']
        if panel != 'R':
            _verify_panel_closeout(binding, candidate, plan, folder, PANELS[PANELS.index(panel) - 1])
        _coverage(binding, coverage, clock=clock, new_cost=budget.cost, reserve_calls=gate.MAX_CALLS[panel])
        _need(gate.money(coverage['native_cost_at_observation_usd']) == budget.cost,
              'dispatch requires current entire native ledger baseline')
        _need(budget.calls + gate.MAX_CALLS[panel] <= budget.max_calls, 'whole block exceeds call bound')
        return {'state_sha256': state['state_sha256'], 'section_end': section_end}


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
        _verify_receipt(folder, state)
        _verify_confirmation(binding, folder, state)
        later = [n for n in candidate['section_ends'] if n > state['completed_blocks']]
        _need(bool(later), 'no uncompleted original hold')
        expected_end = later[0]
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

                def send(request):
                    _runtime(binding, candidate, clock=clock, panel=panel)
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


