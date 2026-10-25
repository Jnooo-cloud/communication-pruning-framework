"""D078 additive R125 recovery; retained bytes and scientific kernels stay fixed.

Retained admissions are a bounded provenance inventory, never a reconstructed
historical witness. One new D055 ledger distinguishes physical requests from
logical journal results. The observed account discrepancy is not an arm cost.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import math
import shutil
import time

from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput, Request, Message
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import encoded, payload, decode_billing
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.rate_limit import RateAdapter, classify
from communication_pruning.study import FileGuard, file_hash
from project.research_control.recovery import FileWitness
from . import final_r_resume as inner, final_secondary as secondary
from . import final_execution as native, final_preflight as gate, final_rate_resume as rate
from .final_plan import canonical_hash

StudyStop = gate.StudyStop
PANELS, ZERO = secondary.PANELS, secondary.ZERO
CLAIM = 'r-recovery-02795/claim.json'
CHARGE = Decimal('0.28559945')
DATA_NAMES = ('original', 'blocks', 'provider', 'admissions', 'budget.jsonl', 'replacement.json')
_need, _save, _path, _all_files = secondary._need, secondary._save, secondary._path, secondary._all_files
_blocks, _section_states, _record_section = secondary._blocks, secondary._section_states, secondary._record_section
_receipt_path, _verify_receipt, _checkpoint = secondary._receipt_path, secondary._verify_receipt, secondary._checkpoint
_verify_confirmation, _verify_panel_remote = secondary._verify_confirmation, secondary._verify_panel_remote
_require_real_evidence = secondary._require_real_evidence
safe_exception_chain = inner.safe_exception_chain
connection_hash = secondary.connection_hash


def additional_sources():
    result = inner.additional_sources()
    for name in ('final_r125_resume.py', 'final_r125_resume_operator.py', 'final_rate_resume.py'):
        path = Path(__file__).with_name(name).resolve()
        result[str(path)] = file_hash(path)
    for name in ('test_final_r125_resume.py','test_final_r125_resume_operator.py'):
        path = Path(__file__).parents[1] / 'tests' / name
        result[str(path.resolve())] = file_hash(path)
    path = Path(__file__).parents[1] / 'communication_pruning/rate_limit.py'
    result[str(path.resolve())] = file_hash(path)
    return result


def _data_files(folder):
    return {k: v for k, v in _all_files(folder).items() if k.split('/')[0] in DATA_NAMES}


def _scientific(binding):
    return binding['inner_binding']['inner_binding']


def _normal_response(response, mode):
    if response is not None and mode == 'artificial_only':
        return replace(response, usage=replace(response.usage, cost_source='synthetic'))
    return response


def _logical_usage(usage, mode):
    return {**usage, 'cost_source': 'synthetic'} if mode == 'artificial_only' else usage


def _partial(candidate, plan, root, number):
    """Read saved F selection and unsealed trace; do not resume/write its journal."""
    block = _blocks(plan)[number]
    directory = Path(root) / 'blocks' / f'{number:06d}'
    order = block['arm_order']
    done = order[:order.index('F')]
    _need({p.name for p in directory.iterdir() if p.is_dir()} == set(done + ['F']),
          'unexpected retained partial arm set')
    rows, attempts = inner._read_block(candidate, plan, root, number, arms=done)
    public = gate.read_json(directory / 'public.json')
    task = TaskInput(public['task_id'], public['question'], tuple(public['paragraphs']))
    selection = gate.read_json(directory / 'selection.json')
    config, rounds, failed = native._configuration(candidate, block, 'F', selection)
    saved = read_journal(directory / 'F/journal.jsonl', config)
    trace = saved['trace']
    run_id = plan['plan_hash'][:16] + ':' + next(s['slot_id'] for s in block['slots'] if s['arm'] == 'F')
    _need(not saved['sealed'] and trace['run_id'] == run_id and trace['rounds'] == rounds
          and trace['failed_role'] == failed, 'retained F trace identity changed')
    replay, request = [], None
    for event in trace['events']:
        if event['kind'] == 'started':
            request = Request(event['attempt_id'], task, event['role'], event['round'], event['instruction'],
                tuple(Message(**m) for m in event['messages']), event['max_output_tokens'])
        elif event['kind'] in ('completed', 'model_failed'):
            _need(request is not None and request.attempt_id == event['attempt_id'] and request.attempt_id not in attempts,
                  'invalid partial F response identity')
            attempts[request.attempt_id] = (request, event)
            replay.append(request.attempt_id)
    _need(request is not None and trace['events'][-1]['kind'] == 'started' and len(replay) == 1
          and request.role == 'linking' and attempts[replay[0]][0].role == 'evidence',
          'exact one F evidence success and open linking request required')
    return rows, attempts, replay, request, done


def _retained(inner_binding, candidate, plan, root):
    """Check native logical and physical evidence without old R87 inspectors."""
    old = inner_binding['inner_binding']
    root = Path(root)
    rows, attempts, original_settlements, generations, _, _, _ = inner._original_state(old, candidate, plan, root / 'original')
    attempts = dict(attempts)
    first = old['incident']['completed_blocks']
    completed = sorted((root / 'blocks').glob('*/complete.json'))
    prefix = first + len(completed)
    _need(first < prefix < plan['counts']['R'], 'retained complete R prefix outside plan')
    _need(sorted((root / 'blocks').glob('*/started.json')) ==
          [root / 'blocks' / f'{i:06d}/started.json' for i in range(first, prefix + 1)],
          'retained blocks are not contiguous with exactly one partial')
    for number, proof_path in enumerate(completed, first):
        _need(proof_path == root / 'blocks' / f'{number:06d}/complete.json', 'retained complete gap')
        row_candidates = {a: old['original_candidate'] for a in _blocks(plan)[number]['arm_order'][:_blocks(plan)[number]['arm_order'].index('D')]} if number == first else {}
        current, events = inner._read_block(candidate, plan, root, number, row_candidates=row_candidates)
        inner._verify_block_proof(root, plan, number, current)
        for logical, event in events.items():
            _need(logical not in attempts or number == first and attempts[logical] == event,
                  'retained logical attempt duplicated or changed')
            attempts[logical] = event
        rows.extend(current)
    partial_rows, partial_attempts, replay, pending, done = _partial(candidate, plan, root, prefix)
    _need(not set(attempts) & set(partial_attempts), 'partial request duplicated')
    attempts.update(partial_attempts)
    cap = min(gate.money(v) for v in inner.accounting_view(old, Decimal(0))['available_usd'].values())
    header = dict(kind='header', cap_usd=str(cap), reserve_usd='0.14',
        max_calls=sum(gate.MAX_CALLS[p] * plan['counts'][p] for p in PANELS), binding=old['sha256'],
        allow_synthetic=old['mode'] == 'artificial_only')
    ledger_raw = (root / 'budget.jsonl').read_bytes()
    calls, cost = rate._old_ledger(ledger_raw, header)
    replacement = old['incident']['unknown_attempt_id'] + ':r01223:replacement:1'
    _need(calls[0]['attempt_id'] == replacement, 'retained D076 first replacement changed')
    settled = dict(original_settlements)
    seeds, links = [], []
    for index, call in enumerate(calls, 1):
        physical = call['attempt_id']
        logical = old['incident']['unknown_attempt_id'] if physical == replacement else physical
        usage = call['usage']
        paths = native._provider_files(root, index)
        if index == len(calls):
            _need(logical == pending.attempt_id, 'retained free failure is not the open linking request')
            raw = paths['response'].read_bytes()
            outcome, response, billed, generation = classify(200, raw, pending.max_output_tokens)
            _need(outcome == 'rate_limited' and response is None and generation not in generations
                  and _logical_usage(billed.to_dict(), old['mode']) == usage
                  and paths['request'].read_bytes() == encoded(payload(pending, producer_limit=1024))
                  and gate.read_json(paths['binding']) == dict(attempt_id=physical,
                      request_sha256=file_hash(paths['request']), mode='synthetic' if old['mode'] == 'artificial_only' else 'live')
                  and gate.read_json(paths['billing']) == dict(generation_id=generation, usage=usage, response_sha256=file_hash(paths['response']))
                  and gate.read_json(paths['received']) == dict(http_status=200, response_sha256=file_hash(paths['response'])),
                  'retained free429 provider/request/billing differs')
            generations.add(generation)
        else:
            _need(logical in attempts and logical not in settled and attempts[logical][1]['usage'] == usage,
                  'retained settlement has no unique logical response')
            inner._provider_check(old, root, index, physical, logical, usage, attempts[logical], generations)
            settled[logical] = usage
        links.append(dict(index=index, physical_id=physical, logical_id=logical,
            request_sha256=file_hash(paths['request']), binding_sha256=file_hash(paths['binding']),
            billing_sha256=file_hash(paths['billing']), received_sha256=file_hash(paths['received'])))
        if logical in replay or logical == pending.attempt_id:
            seeds.append(dict(logical_id=logical, provider_index=index,
                output_limit=pending.max_output_tokens if logical == pending.attempt_id else attempts[logical][0].max_output_tokens,
                outcome='rate_limited' if logical == pending.attempt_id else 'completed',
                received_at=call['settled_epoch'], time_basis='preserved_ledger_settlement_not_original_received_time',
                origin=f'retained-provider-{index:05d}',
                **{k: {'path': str(paths[k].resolve()), 'sha256': file_hash(paths[k])} for k in ('request','response','received')}))
    _need({k: v[1]['usage'] for k, v in attempts.items()} == settled, 'retained logical and native billing sets differ')
    _need(len(seeds) == 2 and [s['logical_id'] for s in seeds] == replay + [pending.attempt_id], 'F seed sequence changed')
    expected_provider = {str(p.relative_to(root)) for i in range(1,len(calls)+1) for p in native._provider_files(root,i).values()}
    _need({str(p.relative_to(root)) for p in (root/'provider').iterdir()} == expected_provider, 'orphan retained provider evidence')
    admissions = secondary._admissions(root)
    _need(admissions == {'request-' + canonical_hash(c['attempt_id']): 'unknown' if i == len(calls)-1 else 'settled'
                        for i,c in enumerate(calls)}, 'retained admission identity/status differs')
    # Placeholder hashes are retained as limitations. New links derive from original bytes above.
    admission_inventory = _all_files(root/'admissions')
    return dict(rows=rows, attempts=attempts, partial_rows=partial_rows, pending=pending, done_arms=done,
        completed=prefix, calls=calls, cost=cost, cap=cap, generations=sorted(generations), seeds=seeds,
        physical_links=links, admission_inventory=admission_inventory,
        ledger=dict(bytes=len(ledger_raw), sha256=sha256(ledger_raw).hexdigest(), calls=len(calls), known_cost_usd=str(cost),
                    original_cap_usd=str(cap), original_max_calls=header['max_calls']))


def _call_bound(evidence, retained, owner):
    value = gate.read_json(gate.evidence_file(evidence))
    _need(value.get('schema') == 'z52-r125-call-bound/v1' and value.get('accepted') is True
          and value.get('not_implementation_author') is True and isinstance(value.get('reviewer'),str)
          and value['reviewer'].strip() and value['reviewer'] != owner,
          'separate conservative physical-call bound required')
    for key in ('retained_calls','lost_calls_upper_bound','additional_prior_calls_upper_bound','remaining_calls','original_max_calls'):
        _need(type(value.get(key)) is int and value[key] >= 0, 'finite integer call bound required')
    _need(value['retained_calls'] == retained['calls'] and value['original_max_calls'] == retained['original_max_calls']
          and value['remaining_calls'] == value['original_max_calls'] - value['retained_calls']
              - value['lost_calls_upper_bound'] - value['additional_prior_calls_upper_bound']
          and value['remaining_calls'] > 0, 'call cap was reset or widened')
    sources = value.get('sources')
    if sources is None and isinstance(value.get('evidence'),dict):
        sources = list(value['evidence'].values())
    _need(isinstance(sources,list) and sources, 'call bound original evidence missing')
    for source in sources:
        _need(isinstance(source,dict) and 'path' in source and 'sha256' in source, 'call bound evidence identity missing')
        gate.evidence_file({k:source[k] for k in ('path','sha256')})
    return value


def prepare_origin(inner_binding, candidate, plan, *, review, backup, call_bound, cost_evidence):
    gate._check_seal(inner_binding)
    gate._check_seal(inner_binding['inner_binding'])
    root = Path(inner_binding['folder'])
    _need(gate.read_json(root/'binding.json')==inner_binding, 'retained binding file differs from input')
    FileGuard(inner_binding['source_files'])()
    _need(gate.read_json(root/'STOP.json').get('retry_allowed') is False, 'retained permanent stop required')
    retained = _retained(inner_binding,candidate,plan,root)
    record = gate.read_json(gate.evidence_file(review))
    _need(record.get('accepted') is True and record.get('not_implementation_author') is True
          and record.get('inner_binding_sha256') == inner_binding['sha256']
          and record.get('ledger_sha256') == retained['ledger']['sha256']
          and record.get('completed_blocks') == plan['counts']['P'] + retained['completed']
          and isinstance(record.get('reviewer'),str) and record['reviewer'].strip()
          and record['reviewer'] != inner_binding['owner'], 'separate retained prefix review required')
    gate.evidence_file(backup)
    cost_record = gate.read_json(gate.evidence_file(cost_evidence))
    _need(cost_record.get('additional_observed_charge_usd') == str(CHARGE)
          and cost_record.get('retained_native_cost_usd') == str(retained['cost'])
          and cost_record.get('charge_is_arm_attributed') is False
          and cost_record.get('account_observation_already_includes_charge') is True,
          'explicit separate account discrepancy evidence required')
    bounds = _call_bound(call_bound, retained['ledger'], inner_binding['owner'])
    _need(bounds['additional_prior_calls_upper_bound'] >= inner_binding['inner_binding']['incident']['known_calls']+1,
          'original pre-native physical calls were not reserved')
    regular = sorted(int(p.stem) for p in (root/'confirmations').glob('*.json'))
    _need(regular and regular[-1] <= plan['counts']['P']+retained['completed'], 'retained regular review absent')
    return dict(schema='z52-r125-origin/v1', inner_binding_sha256=inner_binding['sha256'],
        completed_blocks=plan['counts']['P']+retained['completed'], secondary_completed_blocks=retained['completed'],
        last_regular_hold=regular[-1], original_inventory=_all_files(root), data_inventory=_data_files(root),
        witness_inventory=_all_files(inner_binding['witness']), claim_sha256=file_hash(inner_binding['claim_path']),
        stop_sha256=file_hash(root/'STOP.json'), ledger_prefix=retained['ledger'],
        generation_ids=retained['generations'], successful_logical_ids=sorted(retained['attempts']), seeds=retained['seeds'], physical_links=retained['physical_links'],
        historical_admission_inventory=retained['admission_inventory'], historical_witness_continuity=False,
        historical_deleted_attempts_reconstructed=False, additional_observed_charge_usd=str(CHARGE),
        first_logical_id=retained['pending'].attempt_id, first_request_sha256=retained['seeds'][-1]['request']['sha256'],
        done_arms=retained['done_arms'], call_limits=bounds,
        **{k:deepcopy(v) for k,v in dict(review=review,backup=backup,call_bound=call_bound,cost_evidence=cost_evidence).items()})


def prepare_binding(candidate, plan, *, inner_binding, origin, folder, control, witness, owner, activation=None):
    return gate.seal(dict(schema='z52-r125-resume/v1', mode=candidate['mode'], candidate_sha256=candidate['sha256'],
        plan_hash=plan['plan_hash'], execution_binding_sha256=gate.execution_binding(candidate),
        scientific_candidate_sha256=inner_binding['scientific_candidate_sha256'],
        folder=str(_path(folder)), control=str(_path(control)), witness=str(_path(witness)),
        owner=owner, owner_generation=1, claim_path=str(_path(control)/CLAIM), inner_binding=deepcopy(inner_binding),
        origin=deepcopy(origin), first_hold=origin['completed_blocks']+1,
        predecessor=deepcopy(inner_binding['predecessor']), analysis_contract=deepcopy(inner_binding['analysis_contract']),
        source_files=additional_sources(), activation=deepcopy(activation)))


def _verify_originals(binding):
    previous, origin = binding['inner_binding'], binding['origin']
    inner._verify_originals(_scientific(binding))
    _need(_all_files(previous['folder']) == origin['original_inventory']
          and _all_files(previous['witness']) == origin['witness_inventory']
          and file_hash(previous['claim_path']) == origin['claim_sha256'], 'retained original or historic witness changed')
    for key in ('review','backup','cost_evidence','call_bound'):
        gate.evidence_file(origin[key])
    _need(_call_bound(origin['call_bound'],origin['ledger_prefix'],previous['owner']) == origin['call_limits'],
          'conservative call bound changed')


def _activation_gate(binding,candidate,plan,clock):
    secondary._activation_gate(binding,candidate,plan,clock)
    if binding['mode'] != 'artificial_only':
        record=gate.read_json(gate.evidence_file(binding['activation']))
        _need(record.get('author_decision') == 'D-078' and record.get('r125_recovery') is True
            and record.get('recovery_account_policy') == 'next_request_plus_original_R_reserve'
            and record.get('origin_sha256') == canonical_hash(binding['origin'])
            and record.get('free_429') == {'per_logical':2,'global':20,'wait_seconds':[30,120]}
            and record.get('separate_observed_charge_usd') == str(CHARGE), 'exact D078 activation missing')


def _check_binding(binding,candidate,plan,*,folder,control,clock,dependencies=None):
    gate._check_seal(binding)
    previous,origin=binding['inner_binding'],binding['origin']
    gate._check_seal(previous)
    old=_scientific(binding)
    gate._check_seal(old)
    FileGuard(previous['source_files'])()
    _need(origin['call_limits']['additional_prior_calls_upper_bound'] >= old['incident']['known_calls']+1,
          'original pre-native call bound omitted')
    expected=Path(previous['folder']).parent/'recovery-R00125'
    _need(binding.get('schema') == 'z52-r125-resume/v1' and binding['mode']==candidate['mode']
          and binding['folder']==str(_path(folder))==str(expected/'live')
          and binding['witness']==str(expected/'witness')
          and binding['control']==str(_path(control))==previous['control']==candidate['control_directory']
          and binding['claim_path']==str(_path(control)/CLAIM), 'canonical R125 identity differs')
    _need(binding['candidate_sha256']==previous['candidate_sha256']==candidate['sha256']
          and binding['plan_hash']==previous['plan_hash']==plan['plan_hash']
          and binding['execution_binding_sha256']==gate.execution_binding(candidate)
          and old['source_files']==inner.additional_sources()
          and binding['source_files']==additional_sources(), 'fixed scientific/native/source identity changed')
    _need(binding['owner_generation']==1 and isinstance(binding['owner'],str) and binding['owner'].strip()
          and binding['analysis_contract']==previous['analysis_contract'] and binding['predecessor']==previous['predecessor']
          and origin['inner_binding_sha256']==previous['sha256'] and binding['first_hold']==origin['completed_blocks']+1
          and origin['additional_observed_charge_usd']==str(CHARGE), 'origin, owner or contract changed')
    _verify_originals(binding)
    secondary._preflight(binding,candidate,plan,control=control,clock=clock,dependencies=dependencies)
    _analysis_contract(binding,candidate,plan)
    if binding['mode'] != 'artificial_only':
        _need(origin['secondary_completed_blocks']==125 and origin['completed_blocks']==9165
          and origin['last_regular_hold']==9140 and binding['first_hold']==9166
          and origin['stop_sha256']=='b2872bbb682d3c57d17758ef0ec15e7570b4da15c4cd8cf676c2798d8986ec6c'
          and origin['ledger_prefix']['sha256']=='a52ab22e691645fb95bd3b0d5d489b12efa2e51a63a57e3a2efe36c09240643c'
          and origin['ledger_prefix']['known_cost_usd']=='0.67498386' and origin['ledger_prefix']['calls']==2795
          and origin['first_request_sha256']=='4655cc986c337e55f0b8bd47c05ef0f566bafcccf4e636d77b968f3697872ce0'
          and origin['first_logical_id']=='50d4c906a74daf48:Z50-STUDY-v1:R:00125:F:1:linking:1',
          'only exact accepted R125 incident is authorized')
    _activation_gate(binding,candidate,plan,clock)


def _claim(binding, control, *, create=False):
    expected = {'namespace': gate.NAMESPACE, 'binding_sha256': binding['sha256'],
        'folder': binding['folder'], 'control': binding['control'], 'witness': binding['witness'],
        'owner': binding['owner'], 'origin_sha256': canonical_hash(binding['origin'])}
    path = Path(control) / CLAIM
    _need(binding['claim_path'] == str(path.resolve()) and not path.is_symlink(), 'canonical clean claim differs')
    if path.exists():
        _need(not create and gate.read_json(path) == expected, 'R125 right already claimed')
    else:
        _need(create, 'R125 claim missing')
        _save(path, expected)


def _witness_binding(binding, folder, control):
    stop = Path(folder) / 'STOP.json'
    return {'incarnation': 'r125-' + binding['sha256'][:24], 'activation_sha256': binding['sha256'],
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
    _need(not (Path(folder) / 'STOP.json').exists(), 'permanent R125 continuation STOP')
    _need(all(v == 'settled' for v in _section_states(folder).values()), 'open clean section; no retry')
    return record['generation']



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
        "dispatch/budget.jsonl": closure["ledger_prefix"]["sha256"]})
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
        members = {**prepared["evidence"], "dispatch/budget.jsonl": prepared["ledger_prefix"]["sha256"]}
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
        raw_ledger = (Path(folder) / "dispatch/budget.jsonl").read_bytes()
        ledger_prefix = {"bytes": len(raw_ledger), "sha256": sha256(raw_ledger).hexdigest()}
        members = {**evidence, "dispatch/budget.jsonl": ledger_prefix["sha256"]}
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




def accounting_view(binding, native_cost, *, reserve_calls=0, account_available=None):
    retained = gate.money(binding['origin']['ledger_prefix']['known_cost_usd'])
    view = inner.accounting_view(_scientific(binding),retained+CHARGE+native_cost,reserve_calls=reserve_calls)
    if account_available is not None:
        _need(gate.money(account_available) >= Decimal('.28'), 'next request plus original R reserve lacks account coverage')
    # Separate unattributed charge; do not silently place it in a result arm.
    view.update(new_native_cost_usd=str(native_cost), retained_native_cost_usd=str(retained),
        additional_observed_charge_usd=str(CHARGE), charge_is_arm_attributed=False,
        native_budget_burden_usd=str(retained+CHARGE+native_cost),
        known_secondary_answer_cost_usd=str(gate.money(_scientific(binding)['incident']['known_cost_usd'])+retained+native_cost),
        historical_deleted_attempts_cost_scope='separate account discrepancy; logical attribution incomplete',
        continuous_interrupted_F_latency_available=False)
    return view


def _budget_args(binding,plan):
    prefix=binding['origin']['ledger_prefix']
    return dict(cap=gate.money(prefix['original_cap_usd'])-gate.money(prefix['known_cost_usd'])-CHARGE,
        reserve=Decimal('.14'),max_calls=binding['origin']['call_limits']['remaining_calls'],
        binding=binding['sha256'],allow_synthetic=binding['mode']=='artificial_only')


def _budget(binding,plan,folder,*,existing):
    return (PhaseBudget.read_completed if existing else PhaseBudget)(Path(folder)/'dispatch/budget.jsonl',
        **_budget_args(binding,plan))


def _coverage(binding,coverage,*,clock,new_cost,reserve_calls):
    _need(isinstance(coverage,dict) and coverage.get('binding_sha256')==binding['sha256'], 'exact outer account observation required')
    if binding['mode'] != 'artificial_only':
        _require_real_evidence(coverage)
    _need(all(type(coverage.get(k)) in (float,int) and math.isfinite(coverage[k]) for k in ('observed_epoch','valid_until_epoch'))
        and coverage['observed_epoch']<=clock()<=coverage['valid_until_epoch'], 'stale account coverage')
    _need(coverage.get('origin')==('artificial_fixture' if binding['mode']=='artificial_only' else 'current_account_read'), 'wrong account observation origin')
    baseline=gate.money(coverage['native_cost_at_observation_usd'])
    _need(new_cost>=baseline, 'new ledger account baseline ahead')
    available=gate.money(coverage['available_usd'])-(new_cost-baseline)
    return accounting_view(binding,new_cost,reserve_calls=reserve_calls,account_available=str(available))


def _runtime(binding,candidate,*,clock,panel):
    gate.runtime_guard(candidate,clock=clock,panel=panel)
    FileGuard(binding['source_files'])()
    _claim(binding,binding['control'])
    _need(not (Path(binding['folder'])/'STOP.json').exists(), 'persistent R125 stop')
    previous=binding['inner_binding']
    _need(file_hash(previous['claim_path'])==binding['origin']['claim_sha256']
          and file_hash(Path(previous['folder'])/'STOP.json')==binding['origin']['stop_sha256'], 'retained authority changed')
    # Full originals are verified under the study lock before each section.
    # Every physical transport also rechecks immutable source/authority, runtime,
    # activation, account and whole-block budget, after any retry waiting.
    _activation_gate(binding,candidate,{'plan_hash':binding['plan_hash'],'counts':{'P':9040,'R':2952,'T':2952,'F':2952}},clock)


def _seeds(binding,folder):
    result=[]
    for seed in binding['origin']['seeds']:
        copied=deepcopy(seed)
        for kind in ('request','response'):
            copied[kind]['path']=str(Path(folder)/'retained/provider'/f"{seed['provider_index']:05d}-{kind}.json")
        received=Path(folder)/'seeds'/f"{seed['provider_index']:05d}-received.json"
        copied['received']={'path':str(received),'sha256':file_hash(received)}
        original=gate.read_json(gate.evidence_file(seed['received']))
        _need(gate.read_json(received)=={**original,'received_at':seed['received_at'],
            'time_basis':seed['time_basis'],'original_received_sha256':seed['received']['sha256']},
            'derived seed time or original receipt binding changed')
        result.append(copied)
    return result


def _adapter(binding,plan,folder,*,transport=None,clock=time.time,sleep=time.sleep,restore=True,audit_only=False):
    return RateAdapter(Path(folder)/'dispatch',transport,budget_args=_budget_args(binding,plan),
        base_generations=binding['origin']['generation_ids'],seeds=_seeds(binding,folder),
        restore=restore,clock=clock,sleep=sleep,audit_only=audit_only,initial_retries=0)


def _evidence(folder):
    return {k:v for k,v in _all_files(folder).items()
        if k.split('/')[0] in ('retained','blocks','dispatch','seeds','physical','replays')
        or k in ('binding.json','provenance.json')}


def _inspect(binding,candidate,plan,folder):
    folder=Path(folder)
    origin=binding['origin']
    _need(_data_files(folder/'retained')==origin['data_inventory'], 'copied retained bytes changed')
    retained=_retained(binding['inner_binding'],candidate,plan,folder/'retained')
    _need(retained['ledger']==origin['ledger_prefix'] and retained['completed']==origin['secondary_completed_blocks']
        and retained['generations']==origin['generation_ids'], 'retained scientific state changed')
    adapter=_adapter(binding,plan,folder,audit_only=True)
    rows=list(retained['rows'])
    attempts=dict(retained['attempts'])
    complete=sorted((folder/'blocks').glob('*/complete.json'))
    started=sorted((folder/'blocks').glob('*/started.json'))
    _need(len(started)==len(complete), 'incomplete new section cannot continue')
    for number,proofpath in enumerate(complete,retained['completed']):
        _need(proofpath==folder/'blocks'/f'{number:06d}/complete.json'
              and started[number-retained['completed']]==folder/'blocks'/f'{number:06d}/started.json', 'new block gap')
        blockrows,events=inner._read_block(candidate,plan,folder,number)
        inner._verify_block_proof(folder,plan,number,blockrows)
        for logical,event in events.items():
            _need(logical not in attempts or number==retained['completed'] and attempts[logical]==event,
                'new block repeated or changed a retained response')
            attempts[logical]=event
        rows.extend(blockrows)
    logical_states={k:v for k,v in adapter.states.items() if v['outcome']!='rate_limited'}
    seed_ids={s['logical_id'] for s in origin['seeds'] if s['outcome']!='rate_limited'}
    new_ids=set(attempts)-set(retained['attempts'])
    _need(set(logical_states)==new_ids|seed_ids, 'new physical success lacks exact logical result or vice versa')
    for logical,value in logical_states.items():
        request,event=attempts[logical]
        _need(value['body']==encoded(payload(request,producer_limit=1024))
            and native._terminal(logical,_normal_response(value['response'],binding['mode']))==event,
            'new physical response/request differs from logical journal')
    if adapter.records:
        _need(adapter.records[0]['binding']['logical_id']==origin['first_logical_id']
              and adapter.records[0]['binding']['request_sha256']==origin['first_request_sha256']
              and adapter.records[0]['binding']['retry']==1, 'first new physical dispatch changed')
    elif complete:
        raise StudyStop('completed recovery without physical replacement')
    physical=sorted((folder/'physical').glob('*.json'))
    _need(len(physical)==len(adapter.records), 'physical guard evidence count differs')
    for index,(path,record) in enumerate(zip(physical,adapter.records),1):
        bound=record['binding']
        value=gate.read_json(path)
        _need(path.name==f'{index:05d}.json' and value['binding']==bound
            and value['transport_started_at']>=bound['dispatched_at']
            and value['logical_wait_started_at']<=value['transport_started_at']
            and value['elapsed_since_logical_invocation_seconds']==value['transport_started_at']-value['logical_wait_started_at']
            and value['guard_passed'] is True, 'physical/wait evidence differs')
        waits=value['sleep_intervals']
        _need(isinstance(waits,list) and value['requested_sleep_seconds']==sum(w['requested_seconds'] for w in waits)
            and value['observed_sleep_seconds']==sum(w['finished_at']-w['started_at'] for w in waits), 'sleep totals differ')
        previous_time=value['logical_wait_started_at']
        for wait in waits:
            _need(all(type(wait[k]) in (int,float) and math.isfinite(wait[k]) for k in ('started_at','finished_at','requested_seconds'))
                and previous_time<=wait['started_at']<wait['finished_at']<=value['transport_started_at']
                and 0<wait['requested_seconds']<=30, 'nonmonotone or invalid sleep interval')
            previous_time=wait['finished_at']
    replay_paths=sorted((folder/'replays').glob('*.json'))
    expected_replays=1 if complete else 0
    _need(len(replay_paths)==expected_replays, 'retained successful seed replay count differs')
    if replay_paths:
        value=gate.read_json(replay_paths[0])
        _need(value['logical_id']==origin['seeds'][0]['logical_id'] and value['new_physical_calls']==0
            and value['request_sha256']==origin['seeds'][0]['request']['sha256'], 'successful seed replay changed')
    _need(gate.read_json(folder/'binding.json')==binding and gate.read_json(folder/'provenance.json')==origin,
        'saved outer binding/provenance differs')
    if complete:
        known=gate.money(_scientific(binding)['incident']['known_cost_usd'])+retained['cost']+adapter.budget.cost
        _need(sum((gate.money(r['cost_usd']) for r in rows),Decimal(0))==known,
            'successful answer costs not attributed exactly once')
    count=retained['completed']+len(complete)
    state=dict(binding_sha256=binding['sha256'],connection_sha256=connection_hash(binding),
        execution_binding_sha256=gate.execution_binding(candidate),plan_hash=plan['plan_hash'],
        completed_blocks=plan['counts']['P']+count,secondary_completed_blocks=count,
        complete=count==len(_blocks(plan)),rows=rows,budget=adapter.budget.snapshot(),
        levels=accounting_view(binding,adapter.budget.cost),generation_ids=sorted(adapter.generations),
        evidence=_evidence(folder),origin_sha256=canonical_hash(origin),
        inherited_native_calls=origin['ledger_prefix']['calls'],continuation_new_calls=adapter.budget.calls,
        continuation_new_known_cost_usd=str(adapter.budget.cost),free429_retries=adapter.retries,
        physical_attempts=[dict(logical_id=r['binding']['logical_id'],physical_id=r['binding']['physical_id'],
            retry=r['binding']['retry'],outcome=r['outcome']) for r in adapter.records],
        call_count_scope='logical scientific results; separate physical dispatch records',
        historical_witness_continuity=False,historical_deleted_attempts_reconstructed=False,
        continuous_arm_latency_available=False,continuous_interrupted_F_latency_available=False,
        cost_scope='retained known response costs; separate unattributed account discrepancy',
        original_unknown={'attempt_id':_scientific(binding)['incident']['unknown_attempt_id'],'cost_usd':None,'held_reservation_usd':'0.14'},
        checkpoint_kind='r126_recovery_hold' if count==origin['secondary_completed_blocks']+1 else 'original_planned_hold')
    state['state_sha256']=canonical_hash(state)
    return state,adapter.budget


def _analysis_contract(binding,candidate,plan):
    return inner._analysis_contract(_scientific(binding),candidate,plan)


def _analysis(binding,plan,panel,rows,contract):
    result=inner._analysis(_scientific(binding),plan,panel,rows,contract)
    result.update(historical_deleted_R_attempts_reconstructed=False,historical_witness_continuity=False,
        additional_observed_charge_usd=str(CHARGE),additional_charge_attributed_to_arms=False,
        R_cost_attribution_complete=False,continuous_interrupted_F_latency_available=False,
        physical_retries_excluded_from_logical_call_count=True,
        historical_cost_limit='Deleted R attempts prevent complete historical arm attribution; account discrepancy is separate.')
    return result


def _panel_evidence(plan,folder,panel):
    folder=Path(folder)
    result={k:v for k,v in _evidence(folder).items() if k.split('/')[0] in ('retained','seeds')
            or k in ('binding.json','provenance.json')}
    for number,block in enumerate(_blocks(plan)):
        directory=folder/'blocks'/f'{number:06d}'
        if block['panel']==panel and directory.exists():
            proof=gate.read_json(directory/'complete.json')
            result.update(proof['evidence'])
            result[str((directory/'complete.json').relative_to(folder))]=file_hash(directory/'complete.json')
    path=folder/'panels'/panel/'analysis.json'
    result[str(path.relative_to(folder))]=file_hash(path)
    return result


def _verify_ledger_prefix(folder,prefix):
    raw=(Path(folder)/'dispatch/budget.jsonl').read_bytes()
    _need(len(raw)>=prefix['bytes'] and sha256(raw[:prefix['bytes']]).hexdigest()==prefix['sha256'],
        'new physical ledger prefix changed')


def initialize(binding,candidate,plan,*,folder,control,clock,checkpoint):
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock)
        folder=Path(folder)
        _need(not folder.exists() or not any(folder.iterdir()), 'new R125 output must be empty')
        actual=prepare_origin(binding['inner_binding'],candidate,plan,
            **{k:binding['origin'][k] for k in ('review','backup','call_bound','cost_evidence')})
        _need(actual==binding['origin'], 'complete origin inspection changed')
        _claim(binding,control,create=True)
        for name in ('retained','blocks','dispatch','seeds','physical','replays','receipts','panels','sections'):
            (folder/name).mkdir(parents=True)
        for name in DATA_NAMES:
            source,target=Path(binding['inner_binding']['folder'])/name,folder/'retained'/name
            if source.is_dir():shutil.copytree(source,target)
            else:shutil.copyfile(source,target)
        for seed in binding['origin']['seeds']:
            received=gate.read_json(gate.evidence_file(seed['received']))
            _save(folder/'seeds'/f"{seed['provider_index']:05d}-received.json",{**received,
                'received_at':seed['received_at'],'time_basis':seed['time_basis'],
                'original_received_sha256':seed['received']['sha256']})
        _save(folder/'binding.json',binding)
        _save(folder/'provenance.json',binding['origin'])
        _adapter(binding,plan,folder,restore=False,clock=clock)
        state,_=_inspect(binding,candidate,plan,folder)
        _checkpoint(folder,state,checkpoint)
        _witness(binding).initialize(_witness_binding(binding,folder,control))
        return state


def _next_end(binding,candidate,state):
    if state['completed_blocks']==binding['origin']['completed_blocks']:
        return binding['first_hold']
    later=[n for n in candidate['section_ends'] if n>state['completed_blocks']]
    _need(later, 'no uncompleted original hold')
    return later[0]


def _dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock):
    state,budget=_inspect(binding,candidate,plan,folder)
    _verify_receipt(folder,state)
    if state['completed_blocks']>binding['origin']['completed_blocks']:
        _verify_confirmation(binding,folder,state)
    _need(type(section_end) is int and section_end==_next_end(binding,candidate,state), 'only next recovery/original hold allowed')
    prefix,end=state['secondary_completed_blocks'],section_end-plan['counts']['P']
    blocks=_blocks(plan)
    _need(prefix<end<=len(blocks) and blocks[prefix]['panel']==blocks[end-1]['panel'], 'section crosses panel boundary')
    panel=blocks[prefix]['panel']
    if panel!='R':_verify_panel_closeout(binding,candidate,plan,folder,PANELS[PANELS.index(panel)-1])
    _coverage(binding,coverage,clock=clock,new_cost=budget.cost,reserve_calls=gate.MAX_CALLS[panel])
    _need(gate.money(coverage['native_cost_at_observation_usd'])==budget.cost,'current new-ledger account baseline required')
    _need(budget.calls+gate.MAX_CALLS[panel]<=budget.max_calls, 'whole block exceeds remaining original physical call bound')
    return state,budget,prefix,end,panel


def pre_dispatch(binding,candidate,plan,*,folder,control,clock,section_end,coverage):
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock)
        _claim(binding,control)
        _assert_current(binding,folder,control)
        state,*_=_dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock)
        return {'state_sha256':state['state_sha256'],'section_end':section_end}


def run_section(binding,candidate,plan,*,folder,control,section_end,coverage,loader,spatial_selector,
                temporal_selector,transport,checkpoint,clock,sleep=time.sleep):
    dependencies=dict(loader=loader,spatial_selector=spatial_selector,temporal_selector=temporal_selector,
        transport=transport,checkpoint=checkpoint)
    folder=Path(folder)
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock,dependencies=dependencies)
        _claim(binding,control)
        generation=_assert_current(binding,folder,control)
        state,budget,prefix,end,panel=_dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock)
        _save(folder/'coverage'/f"{state['completed_blocks']:06d}.json",coverage)
        _record_section(folder,section_end,'admitted')
        generation=_publish(binding,folder,control,generation)
        active={'request':None,'wait_started':None,'waits':[]}
        adapter=None
        def measured_sleep(seconds):
            _need(type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=30, 'invalid requested sleep')
            before=clock()
            sleep(seconds)
            after=clock()
            _need(all(type(v) in (int,float) and math.isfinite(v) for v in (before,after)) and after>before,
                  'sleep did not advance a finite clock')
            active['waits'].append(dict(requested_seconds=seconds,started_at=before,finished_at=after))
        def physical_transport(endpoint,body):
            _runtime(binding,candidate,clock=clock,panel=panel)
            _coverage(binding,coverage,clock=clock,new_cost=adapter.budget.cost,reserve_calls=gate.MAX_CALLS[panel])
            # start() reserved the current attempt already; keep a complete block covered conservatively.
            _need(adapter.budget.calls+gate.MAX_CALLS[panel]-1<=adapter.budget.max_calls,
                'physical retry would exceed whole-block call bound')
            number=adapter.budget.calls
            dispatch=gate.read_json(folder/'dispatch'/f'{number:05d}-binding.json')
            request=active['request']
            _need(endpoint=='chat/completions' and request is not None
                  and dispatch['logical_id']==request.attempt_id
                  and body==encoded(payload(request,producer_limit=1024)), 'physical request/body drift')
            if number==1:
                _need(request.attempt_id==binding['origin']['first_logical_id']
                    and sha256(body).hexdigest()==binding['origin']['first_request_sha256'], 'first dispatch must replace02795')
            now=clock()
            _need(type(now) in (int,float) and math.isfinite(now) and now>=active['wait_started'], 'nonmonotone physical clock')
            _save(folder/'physical'/f'{number:05d}.json',dict(binding=dispatch,guard_passed=True,
                logical_wait_started_at=active['wait_started'],transport_started_at=now,
                elapsed_since_logical_invocation_seconds=now-active['wait_started'],
                sleep_intervals=deepcopy(active['waits']),
                requested_sleep_seconds=sum(w['requested_seconds'] for w in active['waits']),
                observed_sleep_seconds=sum(w['finished_at']-w['started_at'] for w in active['waits'])))
            active['waits']=[]
            return transport(endpoint,body)
        try:
            adapter=_adapter(binding,plan,folder,transport=physical_transport,clock=clock,sleep=measured_sleep)
            for number in range(prefix,end):
                block=_blocks(plan)[number]
                _runtime(binding,candidate,clock=clock,panel=panel)
                _coverage(binding,coverage,clock=clock,new_cost=adapter.budget.cost,reserve_calls=gate.MAX_CALLS[panel])
                _need(adapter.budget.calls+gate.MAX_CALLS[panel]<=adapter.budget.max_calls,'whole block call bound exhausted')
                directory=folder/'blocks'/f'{number:06d}'
                directory.mkdir()
                first_call=adapter.budget.calls+1
                recovering=number==binding['origin']['secondary_completed_blocks']
                if recovering:
                    old_dir=folder/'retained/blocks'/f'{number:06d}'
                    for path in old_dir.iterdir():
                        if path.is_file():shutil.copyfile(path,directory/path.name)
                    public,private=gate.read_json(directory/'public.json'),gate.read_json(directory/'reference.json')
                    task=TaskInput(public['task_id'],public['question'],tuple(public['paragraphs']))
                    reference=AnswerReference(private['task_id'],tuple(private['answers']))
                    selection=gate.read_json(directory/'selection.json')
                    done=binding['origin']['done_arms']
                    for arm in done:shutil.copytree(old_dir/arm,directory/arm)
                else:
                    done=[]
                    _save(directory/'started.json',{'block':block,'plan_hash':plan['plan_hash']})
                    task,reference=loader(block['task_id'])
                    _need(type(task) is TaskInput and type(reference) is AnswerReference
                        and task.task_id==native.public_task_id(plan,block['task_id']) and reference.task_id==task.task_id,'foreign task/reference')
                    _save(directory/'public.json',asdict(task));_save(directory/'reference.json',asdict(reference))
                    q=native._select_observed(spatial_selector,task,candidate=candidate,plan=plan,block=block,kind='spatial',directory=directory)
                    qt=native._select_observed(temporal_selector,task,candidate=candidate,plan=plan,block=block,kind='temporal',directory=directory) if panel=='T' else None
                    _need(q in {c.config_id for c in bank()} and (panel!='T' or type(qt) is int and qt in (1,2)), 'frozen bank selection differs')
                    selection={'spatial_q':q,'temporal_qst':qt};_save(directory/'selection.json',selection)
                def send(request):
                    active.update(request=request,wait_started=clock(),waits=[])
                    prior=adapter.states.get(request.attempt_id)
                    _need(request.attempt_id not in set(binding['origin']['successful_logical_ids'])
                        or request.attempt_id in {s['logical_id'] for s in binding['origin']['seeds']}, 'historical successful request cannot be resent')
                    if prior and prior['outcome']!='rate_limited':
                        _need(recovering and request.attempt_id==binding['origin']['seeds'][0]['logical_id'], 'unapproved logical replay')
                    before=adapter.budget.calls
                    response=adapter(request)
                    if adapter.budget.calls==before:
                        _save(folder/'replays'/'00001.json',dict(logical_id=request.attempt_id,new_physical_calls=0,
                            request_sha256=sha256(encoded(payload(request,producer_limit=1024))).hexdigest(),
                            generation_id=adapter.states[request.attempt_id]['generation']))
                    return _normal_response(response,binding['mode'])
                rows=[]
                for slot in block['slots']:
                    arm,sd=slot['arm'],directory/slot['arm']
                    if arm in done:
                        rows.append(gate.read_json(sd/'result.json'));continue
                    sd.mkdir()
                    run_id=plan['plan_hash'][:16]+':'+slot['slot_id']
                    config,rounds,failed=native._configuration(candidate,block,arm,selection)
                    if config is None:
                        result=native._direct(task,reference,run_id,arm,0 if arm=='S' else block['tie_break_seed'],sd,send)
                    else:
                        execute(task,config,send,rounds=rounds,failed_role=failed,run_id=run_id,
                            journal_path=sd/'journal.jsonl',producer_limit=1024,failure_policy=F01)
                        result,_=native._mas_result(sd/'journal.jsonl',config,task,reference,block)
                    row=native._row(candidate,block,slot,result,config,rounds,failed,run_id)
                    _save(sd/'result.json',row);rows.append(row)
                if recovering:
                    _save(directory/'replay.json',dict(original_F_journal_sha256=file_hash(old_dir/'F/journal.jsonl'),
                        original_selection_measurement_sha256=file_hash(old_dir/'spatial-measurement.json'),
                        continuous_arm_latency_available=False,continuous_interrupted_F_latency_available=False))
                files=[p for p in directory.rglob('*') if p.is_file()]
                for index in range(first_call,adapter.budget.calls+1):
                    files.extend(folder/'dispatch'/f'{index:05d}-{k}.json' for k in ('request','binding','response','received','outcome'))
                    files.append(folder/'physical'/f'{index:05d}.json')
                if recovering:files.extend((folder/'replays').glob('*.json'))
                _save(directory/'complete.json',dict(block=block,plan_hash=plan['plan_hash'],rows=rows,
                    evidence={str(p.relative_to(folder)):file_hash(p) for p in files}))
            state,_=_inspect(binding,candidate,plan,folder)
            _checkpoint(folder,state,checkpoint)
            _record_section(folder,section_end,'settled')
            _publish(binding,folder,control,generation)
            return state
        except BaseException as error:
            try:
                _save(folder/'STOP.json',dict(binding_sha256=binding['sha256'],error_type=type(error).__name__,
                    retry_allowed=False,diagnostic=safe_exception_chain(error,clock)))
                _publish(binding,folder,control,generation)
            except BaseException as recording_error:
                error.add_note('R125 STOP/witness recording failed: '+type(recording_error).__name__)
            raise
