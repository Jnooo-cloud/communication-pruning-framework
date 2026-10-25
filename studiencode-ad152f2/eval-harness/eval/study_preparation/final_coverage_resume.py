"""Bounded successor of the preserved R1462 coverage stop.

Original scientific readers, arm execution and analyses remain source-bound.
No predecessor file is mutated, no new P execution and no automatic STOP reset.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import math
import shutil
import time

from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01
from communication_pruning.openrouter import encoded, payload
from communication_pruning.study import FileGuard, file_hash
from communication_pruning.technical_retry import ref
from communication_pruning.technical_prefix import PrefixTechnicalAdapter, request_identity
from project.research_control.recovery import FileWitness
from . import final_technical_resume as base
from . import final_operating_renewal as operating
from . import final_r125_resume as previous, final_r_resume as inner
from . import final_secondary as secondary, final_execution as native, final_preflight as gate
from .final_plan import canonical_hash

StudyStop = gate.StudyStop
PANELS, ZERO = secondary.PANELS, secondary.ZERO
CLAIM = 'coverage-R01462/claim.json'
_need, _save, _path, _all_files = secondary._need, secondary._save, secondary._path, secondary._all_files
_blocks, _section_states, _record_section = secondary._blocks, secondary._section_states, secondary._record_section
_receipt_path, _verify_receipt, _checkpoint = secondary._receipt_path, secondary._verify_receipt, secondary._checkpoint
_verify_confirmation, _verify_panel_remote = secondary._verify_confirmation, secondary._verify_panel_remote
_require_real_evidence = secondary._require_real_evidence
safe_exception_chain, connection_hash = base.safe_exception_chain, secondary.connection_hash


def additional_sources():
    files = base.additional_sources()
    root = Path(__file__).parents[1]
    for name in ('communication_pruning/technical_prefix.py', 'study_preparation/final_coverage_resume.py',
                 'study_preparation/final_coverage_resume_operator.py', 'tests/test_technical_prefix.py',
                 'tests/test_final_coverage_resume.py', 'tests/test_final_coverage_resume_operator.py',
                 'study_preparation/final_operating_renewal.py', 'study_preparation/final_operating_renewal_operator.py'):
        p = root/name
        files[str(p.resolve())] = file_hash(p)
    activation = root/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/activation'
    for name in ('coverage_operation.py', 'coverage_metadata.py', 'coverage_backup.py'):
        path = activation/name
        files[str(path.resolve())] = file_hash(path)
    return files


def _verify_guards(folder, records, start=1):
    paths = sorted((Path(folder)/'physical').glob('*.json'))
    _need(len(paths) == len(records), 'physical guard count differs')
    for number, (path, record) in enumerate(zip(paths, records), start):
        proof = gate.read_json(path); d = record['dispatch']
        _need(path.name == f'{number:06d}.json' and proof['dispatch'] == d and proof['guard_passed'] is True
              and proof['logical_wait_started_at'] <= d['dispatched_at'] <= proof['guard_checked_at']
              <= record['receipt']['received_at'], 'physical runtime/wait proof differs')
        for wait in proof['sleep_intervals']:
            _need(0 < wait['requested_seconds'] <= 30
                  and proof['logical_wait_started_at'] <= wait['started_at'] < wait['finished_at'] <= d['dispatched_at'],
                  'observed retry wait differs')


def _verify_terminals(old, retained, attempts, adapter):
    terminal = {k: v for k, v in adapter.states.items() if v['outcome'] in ('completed', 'model_failed')}
    seeds = {s['logical_id'] for s in old['origin']['seeds']}
    _need(set(terminal) == (set(attempts)-set(retained['attempts'])) | seeds, 'physical/logical result sets differ')
    for logical, state in terminal.items():
        request, event = attempts[logical]
        _need(state['body'] == encoded(payload(request, producer_limit=1024))
              and native._terminal(logical, previous._normal_response(state['response'], old['mode'])) == event,
              'physical/logical content differs')


def retained_state(old, candidate, plan):
    """Read raw native rows, including exactly one physically unsent tail."""
    root = Path(old['folder'])
    base._verify_originals(old); FileGuard(old['source_files'])()
    retained = base.retained_state(old['inner_binding'], candidate, plan)
    _need(_all_files(root/'retained') == old['origin']['original_inventory'], 'retained copy changed')
    rows, attempts = list(retained['rows']), dict(retained['attempts'])
    complete = sorted((root/'blocks').glob('*/complete.json'))
    count = retained['completed']+len(complete)
    _need(sorted((root/'blocks').glob('*/started.json')) ==
          [root/'blocks'/f'{i:06d}/started.json' for i in range(retained['completed'], count+1)],
          'stopped block prefix differs')
    for number, path in enumerate(complete, retained['completed']):
        _need(path == root/'blocks'/f'{number:06d}/complete.json', 'predecessor complete gap')
        current, events = inner._read_block(candidate, plan, root, number)
        inner._verify_block_proof(root, plan, number, current)
        for logical, event in events.items():
            _need(logical not in attempts or attempts[logical] == event, 'retained replay differs')
            attempts[logical] = event
        rows.extend(current)
    partial, events, replay, pending, done, arm = base._partial(candidate, plan, root, count)
    _need(not set(events) & set(attempts), 'partial duplicate response')
    attempts.update(events)
    adapter = base._adapter(old, root, audit_only=True)
    _verify_terminals(old, retained, attempts, adapter)
    _verify_guards(root, adapter.records)
    seedids = {s['logical_id'] for s in old['origin']['seeds']}
    paths = sorted((root/'replays').glob('*.json'))
    _need(len(paths) == len(seedids) and {gate.read_json(p)['logical_id'] for p in paths} == seedids,
          'old replay evidence differs')
    _need(len(replay) == 3 and pending.attempt_id not in adapter.states,
          'coverage tail must have three responses and an unsent request')
    _need(gate.read_json(root/'STOP.json')['retry_allowed'] is False, 'preserved persistent stop required')
    return dict(rows=rows, attempts=attempts, completed=count, partial_rows=partial,
                replays=[request_identity(attempts[k][0]) for k in replay], pending=pending,
                done_arms=done, partial_arm=arm, adapter=adapter, base_retained=retained)


def prepare_origin(old, candidate, plan):
    state = retained_state(old, candidate, plan); adapter = state['adapter']
    base._claim(old, old['control'])
    witness = base._witness(old).assert_current(base._witness_binding(old, old['folder'], old['control']))
    _need(witness['checkpoint']['stop_active'] is True, 'old witness must retain its stop')
    if old['mode'] != 'artificial_only':
        _need(state['completed'] == 1462 and len(state['rows']) == 8772
              and state['partial_arm'] == 'Q' and state['done_arms'] == ['Z', 'F', 'D', 'S', 'S-k']
              and adapter.calls == 40066 and str(adapter.cost) == '9.56561729'
              and adapter.held == 0 and adapter.technical_retries == 1 and adapter.rate_retries == 6
              and adapter.cap == Decimal('53.50242297') and adapter.max_calls == 195273
              and state['pending'].attempt_id == '50d4c906a74daf48:Z50-STUDY-v1:R:01462:Q:2:checking:1'
              and file_hash(Path(old['folder'])/'STOP.json') ==
              '3f7c3e2879257718aa5f5ecccde78ea1731ba20cb5af70e4eacfe6bad1670310',
              'only the bound R1462 coverage stop may continue')
    return dict(schema='coverage-R1462-origin/v1', predecessor_sha256=old['sha256'],
        original_inventory=_all_files(old['folder']), witness_inventory=_all_files(old['witness']),
        claim_sha256=file_hash(old['claim_path']), old_witness=deepcopy(witness),
        completed_blocks=plan['counts']['P']+state['completed'], secondary_completed_blocks=state['completed'],
        done_arms=state['done_arms'], partial_arm=state['partial_arm'], replays=state['replays'],
        first_request=request_identity(state['pending']),
        prefix=dict(origin=ref(Path(old['folder'])/'dispatch/origin.json'),
            last_settlement=ref(adapter._path(adapter.calls, 'settled')), snapshot=adapter.snapshot()),
        historical_gaps_repaired=False, continuous_interrupted_arm_latency_available=False)


def prepare_binding(candidate, plan, *, inner_binding, origin, folder, control, witness, owner,
                    operating_context=None, operating_tip=None, activation=None):
    return gate.seal(dict(schema='z52-coverage-resume/v1', mode=candidate['mode'],
        candidate_sha256=candidate['sha256'], plan_hash=plan['plan_hash'],
        execution_binding_sha256=gate.execution_binding(candidate),
        scientific_candidate_sha256=inner_binding['scientific_candidate_sha256'],
        folder=str(_path(folder)), control=str(_path(control)), witness=str(_path(witness)),
        owner=owner, owner_generation=1, claim_path=str(_path(control)/CLAIM),
        inner_binding=deepcopy(inner_binding), origin=deepcopy(origin), first_hold=origin['completed_blocks']+1,
        predecessor=deepcopy(inner_binding['predecessor']), analysis_contract=deepcopy(inner_binding['analysis_contract']),
        source_files=additional_sources(), operating_context=operating_context,
        operating_tip=operating_tip, activation=activation))


def _verify_originals(binding):
    old, origin = binding['inner_binding'], binding['origin']
    base._verify_originals(old)
    _need(_all_files(old['folder']) == origin['original_inventory']
          and _all_files(old['witness']) == origin['witness_inventory']
          and file_hash(old['claim_path']) == origin['claim_sha256'], 'stopped predecessor changed')
    current = base._witness(old).assert_current(base._witness_binding(old, old['folder'], old['control']))
    _need(current == origin['old_witness'], 'stopped predecessor witness changed')


def _predecessor_activation(binding, candidate, plan, clock):
    old = binding['inner_binding']
    if binding['mode'] == 'artificial_only':
        _need(binding['operating_context'] is None and binding['operating_tip'] is None,
              'artificial coverage connection cannot carry live operating evidence')
        return base._activation_gate(old, candidate, plan, clock)
    context = operating.OperatingContext(binding['operating_context'], expected_tip=binding['operating_tip'])
    return context._activation_gate(old, candidate, plan, clock)


def _activation_gate(binding, candidate, plan, clock):
    _predecessor_activation(binding, candidate, plan, clock)
    if binding['mode'] == 'artificial_only':
        _need(binding['activation'] is None, 'artificial connection cannot carry live activation')
        return
    value = gate.read_json(gate.evidence_file(binding['activation']))
    _require_real_evidence(value)
    _need(value.get('schema') == 'z52-coverage-activation/v1'
          and value.get('connection_sha256') == connection_hash(binding)
          and value.get('executor') == binding['owner'] and value.get('send_enabled') is True
          and value.get('continuation_authority') == 'existing-Jannik-2026-09-26-continuation'
          and value.get('plan_sha256') == '204f3fa88a0a1ba241af7bd7ceccf5006108dff4a776b25ba1a1164c45566e90',
          'exact authorized coverage connection missing')
    manifest = gate.read_json(gate.evidence_file(value['source_manifest']))
    _need(manifest['files'] == binding['source_files'], 'coverage source manifest differs')
    _need(manifest['members'] == {f'source-{i:04d}': h for i, (_, h) in enumerate(sorted(manifest['files'].items()))},
          'coverage source archive members differ')
    gate.verify_archive(manifest['archive'], manifest['members'])
    review = gate.read_json(gate.evidence_file(value['source_review']))
    backup = gate.read_json(gate.evidence_file(value['source_backup']))
    for record in (review, backup):
        _require_real_evidence(record)
        _need(record.get('accepted') is True and record.get('connection_sha256') == connection_hash(binding)
              and record.get('source_manifest') == value['source_manifest'], 'coverage source acceptance differs')
    _need(review.get('not_implementation_author') is True and isinstance(review.get('reviewer'), str)
          and review['reviewer'].strip() and review['reviewer'] != binding['owner'], 'separate coverage review required')
    _need(backup.get('destination') == 'Jnooo-cloud/masterarbeit-mas-pruning'
          and backup.get('full_remote_reread') is True and backup.get('members') == manifest['members']
          and backup.get('archive_sha256') == manifest['archive']['sha256'], 'coverage source full reread required')
    for key, expected in (('stop_review', 'd1fa6ffc4f92703eb00d374768be73f12f10415e253f2a9d70e71c0d672c2851'),
                          ('stop_backup', 'b8ab1dc5c298abd18b5303cf7deca8eccd77a0ace5bb04f85a8975aa0e7b3ad7'),
                          ('supplement_backup', '42fb5cd61cf000df4970fd195a1035f8790a4b3ff073de50597295949b5a951d')):
        _need(value[key]['sha256'] == expected, 'wrong stopped-state acceptance')
        gate.evidence_file(value[key])


def _check_binding(binding, candidate, plan, *, folder, control, clock, dependencies=None):
    gate._check_seal(binding); gate._check_seal(binding['inner_binding'])
    old, origin = binding['inner_binding'], binding['origin']
    expected = Path(old['folder']).parent/'coverage-R01462'
    _need(binding['schema'] == 'z52-coverage-resume/v1' and binding['mode'] == candidate['mode']
          and binding['folder'] == str(_path(folder)) == str(expected/'live')
          and binding['witness'] == str(expected/'witness')
          and binding['control'] == str(_path(control)) == old['control'] == candidate['control_directory']
          and binding['claim_path'] == str(_path(control)/CLAIM), 'canonical coverage identity differs')
    _need(binding['candidate_sha256'] == old['candidate_sha256'] == candidate['sha256']
          and binding['plan_hash'] == old['plan_hash'] == plan['plan_hash']
          and binding['execution_binding_sha256'] == gate.execution_binding(candidate)
          and binding['scientific_candidate_sha256'] == old['scientific_candidate_sha256']
          and binding['source_files'] == additional_sources() and binding['analysis_contract'] == old['analysis_contract']
          and origin['predecessor_sha256'] == old['sha256']
          and binding['first_hold'] == origin['completed_blocks']+1, 'scientific/source identity differs')
    FileGuard(old['source_files'])(); _verify_originals(binding)
    secondary._preflight(binding, candidate, plan, control=control, clock=clock, dependencies=dependencies)
    _analysis_contract(binding, candidate, plan); _activation_gate(binding, candidate, plan, clock)


def _adapter(binding, folder, *, transport=None, clock=time.time, sleep=time.sleep,
             guard=None, restore=True, audit_only=False):
    origin = binding['origin']
    return PrefixTechnicalAdapter(_path(folder)/'dispatch', transport, binding=binding['sha256'],
        prefix=origin['prefix'], replays=origin['replays'], first_request=origin['first_request'],
        clock=clock, sleep=sleep, guard=guard, restore=restore, audit_only=audit_only)


def accounting_view(binding, cost, *, held=Decimal(0), reserve_calls=0, account_available=None):
    return base.accounting_view(binding['inner_binding'], cost, held=held,
                                reserve_calls=reserve_calls, account_available=account_available)


def _analysis_contract(binding, candidate, plan):
    return base._analysis_contract(binding['inner_binding'], candidate, plan)


def _raw_rows_with_failed_costs(rows, adapter):
    """Never accept already enriched rows as native input."""
    result = deepcopy(rows); failed = adapter.known_failed_costs()
    for row in result:
        _need(not {'native_terminal_cost_usd', 'known_technical_failure_cost_usd'} & set(row),
              'analysis input already includes failed-attempt charges')
        extra = sum((cost for logical, cost in failed.items() if logical.startswith(row['run_id']+':')), Decimal(0))
        if extra:
            row['native_terminal_cost_usd'] = row['cost_usd']
            row['known_technical_failure_cost_usd'] = str(extra)
            row['cost_usd'] = str(gate.money(row['cost_usd'])+extra)
            row['cost_provenance'] = 'native terminal response costs plus known physical failure charges; Unknowns separate'
    return result


def _inspect(binding, candidate, plan, folder):
    folder = Path(folder); old = binding['inner_binding']
    retained = retained_state(old, candidate, plan)
    adapter = _adapter(binding, folder, audit_only=True)
    rows, attempts = list(retained['rows']), dict(retained['attempts'])
    complete = sorted((folder/'blocks').glob('*/complete.json'))
    _need(len(list((folder/'blocks').glob('*/started.json'))) == len(complete), 'incomplete successor block')
    for number, path in enumerate(complete, retained['completed']):
        _need(path == folder/'blocks'/f'{number:06d}/complete.json', 'successor complete gap')
        current, events = inner._read_block(candidate, plan, folder, number)
        inner._verify_block_proof(folder, plan, number, current)
        for logical, event in events.items():
            _need(logical not in attempts or attempts[logical] == event, 'successor logical replay differs')
            attempts[logical] = event
        rows.extend(current)
    _verify_terminals(old, retained['base_retained'], attempts, adapter)
    inherited = binding['origin']['prefix']['snapshot']['calls']
    _verify_guards(folder, adapter.records[inherited:], inherited+1)
    replay_paths = sorted((folder/'replays').glob('*.json'))
    expected = binding['origin']['replays'] if complete else []
    _need(len(replay_paths) == len(expected), 'successor replay count differs')
    for index, (path, identity) in enumerate(zip(replay_paths, expected), 1):
        replay = gate.read_json(path)
        _need(path.name == f'{index:06d}.json' and replay == dict(logical_id=identity['logical_id'],
              request_sha256=identity['request_sha256'], new_physical_calls=0,
              origin=adapter.states[identity['logical_id']]['origin']), 'successor replay differs')
    count = retained['completed']+len(complete)
    value = dict(binding_sha256=binding['sha256'], connection_sha256=connection_hash(binding),
        execution_binding_sha256=gate.execution_binding(candidate), plan_hash=plan['plan_hash'],
        completed_blocks=plan['counts']['P']+count, secondary_completed_blocks=count,
        complete=count == len(_blocks(plan)), rows=_raw_rows_with_failed_costs(rows, adapter),
        budget=adapter.snapshot(), levels=accounting_view(binding, adapter.cost, held=adapter.held),
        generation_ids=sorted(adapter.generations), evidence=_evidence(folder),
        origin_sha256=canonical_hash(binding['origin']), continuation_new_calls=adapter.calls-inherited,
        continuation_new_known_cost_usd=str(adapter.cost-Decimal(binding['origin']['prefix']['snapshot']['known_cost_usd'])),
        historical_witness_continuity=False, historical_deleted_attempts_reconstructed=False,
        continuous_arm_latency_available=False)
    value['state_sha256'] = canonical_hash(value)
    return value, adapter


def initialize(binding, candidate, plan, *, folder, control, clock, checkpoint):
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        folder = Path(folder)
        _need(not folder.exists() or not any(folder.iterdir()), 'new coverage output must be empty')
        _need(prepare_origin(binding['inner_binding'], candidate, plan) == binding['origin'], 'coverage origin changed')
        _claim(binding, control, create=True)
        for name in ('blocks', 'dispatch', 'physical', 'replays', 'receipts', 'panels', 'sections'):
            (folder/name).mkdir(parents=True)
        _save(folder/'binding.json', binding); _save(folder/'provenance.json', binding['origin'])
        _adapter(binding, folder, restore=False, clock=clock)
        state, _ = _inspect(binding, candidate, plan, folder)
        _checkpoint(folder, state, checkpoint)
        _witness(binding).initialize(_witness_binding(binding, folder, control))
        return state


def _verify_adoption(binding, folder, state):
    """Separate zero-call acceptance, deliberately not a regular R1462 hold."""
    _need(state['completed_blocks'] == binding['origin']['completed_blocks']
          and state['continuation_new_calls'] == 0, 'adoption must precede all new calls')
    proof = gate.read_json(Path(folder)/'adoption/confirmation.json')
    for name in ('review', 'backup'):
        value = gate.read_json(gate.evidence_file(proof[name]))
        if binding['mode'] != 'artificial_only':
            _require_real_evidence(value)
        _need(value.get('kind') == 'zero-call-coverage-adoption'
              and value.get('binding_sha256') == binding['sha256']
              and value.get('state_sha256') == state['state_sha256'] and value.get('accepted') is True,
              'exact zero-call adoption acceptance missing')
        if name == 'review':
            _need(value.get('not_implementation_author') is True and isinstance(value.get('reviewer'), str)
                  and value['reviewer'].strip() and value['reviewer'] != binding['owner'], 'separate adoption review required')
        else:
            receipt = gate.read_json(_receipt_path(folder, state))
            _need(value.get('archive_sha256') == receipt['backup']['sha256']
                  and value.get('full_reread') is True and value.get('members') == state['evidence']
                  and value.get('destination') == ('artificial_local' if binding['mode'] == 'artificial_only'
                       else 'Jnooo-cloud/masterarbeit-mas-pruning'), 'exact adoption backup missing')
    return proof


def confirm_adoption(binding, candidate, plan, *, folder, control, clock, review, backup):
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control); generation = _assert_current(binding, folder, control)
        state, _ = _inspect(binding, candidate, plan, folder); _verify_receipt(folder, state)
        _save(Path(folder)/'adoption/confirmation.json', {'review': review, 'backup': backup})
        _verify_adoption(binding, folder, state)
        _publish(binding, folder, control, generation)
        return state['state_sha256']


# Static source-bound adaptation of the predecessor; no runtime patch.
def _claim(binding,control,*,create=False):
    path=Path(control)/CLAIM
    expected=dict(namespace=gate.NAMESPACE,binding_sha256=binding['sha256'],folder=binding['folder'],control=binding['control'],
        witness=binding['witness'],owner=binding['owner'],origin_sha256=canonical_hash(binding['origin']))
    _need(binding['claim_path']==str(path.resolve()) and not path.is_symlink(),'noncanonical claim')
    if path.exists(): _need(not create and gate.read_json(path)==expected,'claim changed or already exists')
    else: _need(create,'missing claim'); _save(path,expected)


# Static source-bound adaptation of the predecessor; no runtime patch.
def _witness_binding(binding,folder,control):
    stop=Path(folder)/'STOP.json'
    return dict(incarnation='coverage-'+binding['sha256'][:24],activation_sha256=binding['sha256'],
        stop_sha256=file_hash(stop) if stop.exists() else ZERO,stop_active=stop.exists(),owner_generation=1,
        original_journal_sha256=canonical_hash(binding['origin']),admission_journal_sha256=canonical_hash(
        {'files':_all_files(folder),'claim':file_hash(Path(control)/CLAIM)}),admissions=_section_states(folder))


# Static source-bound adaptation of the predecessor; no runtime patch.
def _witness(binding): return FileWitness(binding['witness'],binding['folder'])


# Static source-bound adaptation of the predecessor; no runtime patch.
def _publish(binding,folder,control,generation):
    return _witness(binding).checkpoint(generation,_witness_binding(binding,folder,control))['generation']


# Static source-bound adaptation of the predecessor; no runtime patch.
def _assert_current(binding,folder,control):
    record=_witness(binding).assert_current(_witness_binding(binding,folder,control))
    _need(not (Path(folder)/'STOP.json').exists() and all(v=='settled' for v in _section_states(folder).values()),
          'permanent technical stop or unresolved section')
    return record['generation']


# Static source-bound adaptation of the predecessor; no runtime patch.
def _coverage(binding,coverage,clock,adapter,panel):
    _need(coverage.get('binding_sha256')==binding['sha256'] and coverage.get('origin')==
        ('artificial_fixture' if binding['mode']=='artificial_only' else 'current_account_read'),'coverage binding differs')
    if binding['mode']!='artificial_only': _require_real_evidence(coverage)
    _need(all(type(coverage[k]) in (int,float) and math.isfinite(coverage[k]) for k in ('observed_epoch','valid_until_epoch'))
        and coverage['observed_epoch']<=clock()<=coverage['valid_until_epoch'],'stale coverage')
    baseline=gate.money(coverage['native_cost_at_observation_usd'])
    _need(adapter.cost>=baseline,'coverage baseline ahead')
    available=gate.money(coverage['available_usd'])-(adapter.cost-baseline)
    _need(adapter.calls+gate.MAX_CALLS[panel]<=adapter.max_calls,'whole block call bound exhausted')
    return accounting_view(binding,adapter.cost,held=adapter.held,reserve_calls=gate.MAX_CALLS[panel],account_available=available)


# Static source-bound adaptation of the predecessor; no runtime patch.
def _runtime(binding,candidate,plan,clock,panel):
    gate.runtime_guard(candidate,clock=clock,panel=panel); FileGuard(binding['source_files'])(); _claim(binding,binding['control'])
    _need(not (Path(binding['folder'])/'STOP.json').exists(),'persistent stop')
    _activation_gate(binding,candidate,plan,clock)


# Static source-bound adaptation of the predecessor; no runtime patch.
def _analysis(binding,plan,panel,rows,contract):
    value=previous._analysis(binding['inner_binding']['inner_binding'],plan,panel,rows,contract)
    adapter=_adapter(binding,binding['folder'],audit_only=True)
    unknown=[]
    if panel=='R':
        unknown.append(dict(logical_id=binding['inner_binding']['origin']['pending_seed']['logical_id'],arm=binding['inner_binding']['origin']['partial_arm'],
            physical_id=binding['inner_binding']['origin']['pending_seed']['origin'],cost_usd=None,reserve_usd='0.14'))
    for record in adapter.records:
        if record['usage']['cost_usd'] is not None:continue
        logical=record['dispatch']['logical_id']
        matched=[r for r in rows if logical.startswith(r['run_id']+':')]
        if matched:
            _need(len(matched)==1,'Unknown arm attribution ambiguous')
            unknown.append(dict(logical_id=logical,arm=matched[0]['arm'],physical_id=record['dispatch']['physical_id'],
                cost_usd=None,reserve_usd='0.14'))
    arms=sorted(set(value.get('affected_arms',[]))|{v['arm'] for v in unknown})
    affected=[]
    for identifier,endpoint in value['original_analysis']['descriptive_costs']['endpoints'].items():
        involved={endpoint.get('numerator_arm'),endpoint.get('denominator_arm')}
        if endpoint.get('quantity')=='H_Q':involved={'Qf','Qc'}
        elif endpoint.get('quantity')=='H_F':involved={'Ff','Fc'}
        elif endpoint.get('quantity')=='H_Q_minus_H_F':involved={'Qf','Qc','Ff','Fc'}
        if involved&set(arms):affected.append(identifier)
    value.update(technical_retry_cost_scope='Known failed-attempt charges assigned to logical arm; Unknowns excluded and separately reserved',
        additional_R204_unknown=panel=='R',technical_unknown_attempts=unknown,affected_arms=arms,
        affected_cost_endpoints=affected,
        cost_scope='known_billed_costs_only' if unknown or panel=='R' else 'complete_known_panel_costs',
        unconditional_actual_cost_ratio_claim=False if unknown or panel=='R' else None,
        uninterrupted_historical_arm_latency_available=False)
    return value


# Static source-bound adaptation of the predecessor; no runtime patch.
def _evidence(folder):
    return {k:v for k,v in _all_files(folder).items() if k.split('/')[0] in ('retained','blocks','dispatch','physical','replays')
        or k in ('binding.json','provenance.json')}


# Static source-bound adaptation of the predecessor; no runtime patch.
def _next_end(binding,candidate,state):
    if state['completed_blocks']==binding['origin']['completed_blocks']: return binding['first_hold']
    later=[v for v in candidate['section_ends'] if v>state['completed_blocks']]
    _need(later,'no remaining planned hold'); return later[0]


# Static source-bound adaptation of the predecessor; no runtime patch.
def _dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock):
    state,adapter=_inspect(binding,candidate,plan,folder); _verify_receipt(folder,state)
    if state['completed_blocks']==binding['origin']['completed_blocks']: _verify_adoption(binding,folder,state)
    else: _verify_confirmation(binding,folder,state)
    _need(type(section_end) is int and section_end==_next_end(binding,candidate,state),'only next exact hold permitted')
    prefix,end=state['secondary_completed_blocks'],section_end-plan['counts']['P']; blocks=_blocks(plan)
    _need(prefix<end<=len(blocks) and blocks[prefix]['panel']==blocks[end-1]['panel'],'cross-panel section')
    panel=blocks[prefix]['panel']
    if panel!='R': _verify_panel_closeout(binding,candidate,plan,folder,PANELS[PANELS.index(panel)-1])
    _coverage(binding,coverage,clock,adapter,panel)
    _need(gate.money(coverage['native_cost_at_observation_usd'])==adapter.cost,'fresh exact ledger coverage required')
    return state,adapter,prefix,end,panel


# Static source-bound adaptation of the predecessor; no runtime patch.
def pre_dispatch(binding,candidate,plan,*,folder,control,clock,section_end,coverage):
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock)
        _claim(binding,control); _assert_current(binding,folder,control)
        state,*_=_dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock)
        return {'state_sha256':state['state_sha256'],'section_end':section_end}


# Static source-bound adaptation of the predecessor; no runtime patch.
def run_section(binding,candidate,plan,*,folder,control,section_end,coverage,loader,spatial_selector,
                temporal_selector,transport,checkpoint,clock,sleep=time.sleep):
    dependencies=dict(loader=loader,spatial_selector=spatial_selector,temporal_selector=temporal_selector,
        transport=transport,checkpoint=checkpoint)
    folder=Path(folder)
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock,dependencies=dependencies)
        _claim(binding,control); generation=_assert_current(binding,folder,control)
        state,_,prefix,end,panel=_dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock)
        _save(folder/'coverage'/f"{state['completed_blocks']:06d}.json",coverage)
        _record_section(folder,section_end,'admitted'); generation=_publish(binding,folder,control,generation)
        active={'started':None,'waits':[]}; adapter=None
        def measured_sleep(seconds):
            before=clock(); sleep(seconds); after=clock()
            _need(0<seconds<=30 and after>before,'invalid retry sleep')
            active['waits'].append(dict(started_at=before,finished_at=after,requested_seconds=seconds))
        def guard(dispatch,snapshot):
            _runtime(binding,candidate,plan,clock,panel); _coverage(binding,coverage,clock,adapter,panel)
            _save(folder/'physical'/f"{dispatch['number']:06d}.json",dict(dispatch=dispatch,guard_passed=True,
                logical_wait_started_at=active['started'],guard_checked_at=clock(),sleep_intervals=deepcopy(active['waits'])))
            active['waits']=[]
        try:
            adapter=_adapter(binding,folder,transport=transport,clock=clock,sleep=measured_sleep,guard=guard)
            for number in range(prefix,end):
                block=_blocks(plan)[number]; _runtime(binding,candidate,plan,clock,panel)
                _coverage(binding,coverage,clock,adapter,panel)
                directory=folder/'blocks'/f'{number:06d}'; directory.mkdir()
                recovering=number==binding['origin']['secondary_completed_blocks']; first_call=adapter.calls+1
                if recovering:
                    old_dir=Path(binding['inner_binding']['folder'])/'blocks'/f'{number:06d}'
                    for path in old_dir.iterdir():
                        if path.is_file(): shutil.copyfile(path,directory/path.name)
                    public,private=gate.read_json(directory/'public.json'),gate.read_json(directory/'reference.json')
                    task=TaskInput(public['task_id'],public['question'],tuple(public['paragraphs']))
                    reference=AnswerReference(private['task_id'],tuple(private['answers']))
                    selection=gate.read_json(directory/'selection.json'); done=binding['origin']['done_arms']
                    for arm in done: shutil.copytree(old_dir/arm,directory/arm)
                else:
                    done=[]; _save(directory/'started.json',{'block':block,'plan_hash':plan['plan_hash']})
                    task,reference=loader(block['task_id'])
                    _need(type(task) is TaskInput and type(reference) is AnswerReference
                        and task.task_id==native.public_task_id(plan,block['task_id']) and reference.task_id==task.task_id,'foreign task')
                    _save(directory/'public.json',asdict(task)); _save(directory/'reference.json',asdict(reference))
                    q=native._select_observed(spatial_selector,task,candidate=candidate,plan=plan,block=block,kind='spatial',directory=directory)
                    qt=native._select_observed(temporal_selector,task,candidate=candidate,plan=plan,block=block,kind='temporal',directory=directory) if panel=='T' else None
                    selection={'spatial_q':q,'temporal_qst':qt}; _save(directory/'selection.json',selection)
                def send(request):
                    active.update(started=clock(),waits=[])
                    before=adapter.calls
                    response=adapter(request)
                    if adapter.calls==before:
                        _need(recovering and request.attempt_id in {s['logical_id'] for s in binding['origin']['replays']},'unapproved answer replay')
                        _save(folder/'replays'/f'{len(list((folder/"replays").glob("*.json")))+1:06d}.json',
                            dict(logical_id=request.attempt_id,request_sha256=sha256(encoded(payload(request,producer_limit=1024))).hexdigest(),
                                new_physical_calls=0,origin=adapter.states[request.attempt_id]['origin']))
                    return previous._normal_response(response,binding['mode'])
                rows=[]
                for slot in block['slots']:
                    arm=slot['arm']; sd=directory/arm
                    if arm in done: rows.append(gate.read_json(sd/'result.json')); continue
                    sd.mkdir(); run_id=plan['plan_hash'][:16]+':'+slot['slot_id']
                    config,rounds,failed=native._configuration(candidate,block,arm,selection)
                    if config is None:
                        result=native._direct(task,reference,run_id,arm,0 if arm=='S' else block['tie_break_seed'],sd,send)
                    else:
                        execute(task,config,send,rounds=rounds,failed_role=failed,run_id=run_id,
                            journal_path=sd/'journal.jsonl',producer_limit=1024,failure_policy=F01)
                        result,_=native._mas_result(sd/'journal.jsonl',config,task,reference,block)
                    row=native._row(candidate,block,slot,result,config,rounds,failed,run_id)
                    _save(sd/'result.json',row); rows.append(row)
                if recovering:
                    _save(directory/'replay.json',dict(original_partial_journal_sha256=file_hash(old_dir/binding['origin']['partial_arm']/'journal.jsonl'),
                        original_selection_measurement_sha256=file_hash(old_dir/'spatial-measurement.json'),continuous_arm_latency_available=False))
                files=[p for p in directory.rglob('*') if p.is_file()]
                for index in range(first_call,adapter.calls+1):
                    files.extend((folder/'dispatch').glob(f'{index:06d}-*.json')); files.append(folder/'physical'/f'{index:06d}.json')
                if recovering: files.extend((folder/'replays').glob('*.json'))
                _save(directory/'complete.json',dict(block=block,plan_hash=plan['plan_hash'],rows=rows,
                    evidence={str(p.relative_to(folder)):file_hash(p) for p in files}))
            state,_=_inspect(binding,candidate,plan,folder); _checkpoint(folder,state,checkpoint)
            _record_section(folder,section_end,'settled'); _publish(binding,folder,control,generation)
            return state
        except BaseException as error:
            try:
                _save(folder/'STOP.json',dict(binding_sha256=binding['sha256'],error_type=type(error).__name__,
                    retry_allowed=False,diagnostic=safe_exception_chain(error,clock)))
                _publish(binding,folder,control,generation)
            except BaseException as recording_error:
                error.add_note('technical STOP/witness evidence failed: '+type(recording_error).__name__)
            raise


# Static source-bound adaptation of the predecessor; no runtime patch.
def _panel_evidence(plan,folder,panel):
    folder=Path(folder)
    result={k:v for k,v in _evidence(folder).items() if k.split('/')[0] in ('retained','dispatch','physical','replays')
        or k in ('binding.json','provenance.json')}
    for number,block in enumerate(_blocks(plan)):
        directory=folder/'blocks'/f'{number:06d}'
        if block['panel']==panel and directory.exists():
            proof=gate.read_json(directory/'complete.json'); result.update(proof['evidence'])
            result[str((directory/'complete.json').relative_to(folder))]=file_hash(directory/'complete.json')
    path=folder/'panels'/panel/'analysis.json'; result[str(path.relative_to(folder))]=file_hash(path)
    return result


# Static source-bound adaptation of the predecessor; no runtime patch.
def prepare_panel_backup(binding,candidate,plan,panel,*,folder,control,clock,checkpoint):
    from .final_analysis import validate_rows
    _need(panel in PANELS,'secondary panel required')
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock); _claim(binding,control)
        generation=_assert_current(binding,folder,control); state,_=_inspect(binding,candidate,plan,folder); _verify_receipt(folder,state)
        rows=validate_rows(plan,panel,[r for r in state['rows'] if r['panel']==panel]); path=Path(folder)/'panels'/panel/'analysis.json'
        _need(gate.read_json(path)==_analysis(binding,plan,panel,rows,_analysis_contract(binding,candidate,plan)),'panel analysis differs')
        evidence=_panel_evidence(plan,folder,panel); package={**state,'evidence':evidence}; package.pop('state_sha256')
        package['state_sha256']=canonical_hash(package); proof=checkpoint(package); gate.verify_archive(proof,evidence)
        value=dict(binding_sha256=binding['sha256'],panel=panel,analysis_sha256=file_hash(path),evidence=evidence,backup=proof)
        _save(Path(folder)/'panels'/panel/'backup.json',value); _publish(binding,folder,control,generation)
        return value


# Static source-bound adaptation of the predecessor; no runtime patch.
def _panel_review(binding,panel,path,review):
    record=gate.read_json(gate.evidence_file(review))
    _need(record==dict(binding_sha256=binding['sha256'],panel=panel,analysis_sha256=file_hash(path),
        reviewer=record.get('reviewer'),not_implementation_author=True,accepted=True)
        and isinstance(record['reviewer'],str) and record['reviewer'].strip() and record['reviewer']!=binding['owner'],'separate panel review missing')


# Static source-bound adaptation of the predecessor; no runtime patch.
def close_panel(binding,candidate,plan,panel,*,folder,control,clock,review,remote_backup):
    _need(panel in PANELS,'secondary panel required')
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock); _claim(binding,control)
        generation=_assert_current(binding,folder,control); state,_=_inspect(binding,candidate,plan,folder); _verify_receipt(folder,state)
        path=Path(folder)/'panels'/panel/'analysis.json'; _panel_review(binding,panel,path,review)
        prepared=gate.read_json(Path(folder)/'panels'/panel/'backup.json')
        _need(prepared['binding_sha256']==binding['sha256'] and prepared['panel']==panel
            and prepared['analysis_sha256']==file_hash(path) and prepared['evidence']==_panel_evidence(plan,folder,panel),'panel backup differs')
        gate.verify_archive(prepared['backup'],prepared['evidence'])
        _verify_panel_remote(binding,panel,file_hash(path),prepared['backup'],remote_backup)
        _save(Path(folder)/'panels'/panel/'complete.json',{**prepared,'review':review,'remote_backup':remote_backup})
        _publish(binding,folder,control,generation); return {'panel':panel,'closed':True}


# Static source-bound adaptation of the predecessor; no runtime patch.
def _verify_panel_closeout(binding,candidate,plan,folder,panel):
    from .final_analysis import validate_rows
    value=gate.read_json(Path(folder)/'panels'/panel/'complete.json'); path=Path(folder)/'panels'/panel/'analysis.json'
    _need(value['binding_sha256']==binding['sha256'] and value['panel']==panel,'panel closure identity differs')
    state,_=_inspect(binding,candidate,plan,folder)
    rows=validate_rows(plan,panel,[r for r in state['rows'] if r['panel']==panel])
    _need(gate.read_json(path)==_analysis(binding,plan,panel,rows,_analysis_contract(binding,candidate,plan))
        and file_hash(path)==value['analysis_sha256'],'closed panel analysis changed')
    for rel,checksum in value['evidence'].items(): _need(file_hash(Path(folder)/rel)==checksum,'closed panel evidence changed')
    gate.verify_archive(value['backup'],value['evidence']); _panel_review(binding,panel,path,value['review'])
    _verify_panel_remote(binding,panel,file_hash(path),value['backup'],value['remote_backup'])
    return value


# Static source-bound adaptation of the predecessor; no runtime patch.
def inspect_study(binding, candidate, plan, *, folder, control, clock):
    with native.study_lock(control):
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        _claim(binding, control)
        _assert_current(binding, folder, control)
        return _inspect(binding, candidate, plan, folder)[0]


# Static source-bound adaptation of the predecessor; no runtime patch.
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


# Static source-bound adaptation of the predecessor; no runtime patch.
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


# Static source-bound adaptation of the predecessor; no runtime patch.
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
