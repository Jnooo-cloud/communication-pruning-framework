"""Additive R203 continuation: immutable originals, frozen scientific functions.

Only the technical adapter and operating continuity differ from D078.
Old provenance gaps and missing uninterrupted arm timing remain explicit.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import math
import json
import shutil
import time

from communication_pruning.contracts import TaskInput, Request, Message
from communication_pruning.data import AnswerReference, digest
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import encoded, payload
from communication_pruning.rate_limit import classify
from communication_pruning.study import FileGuard, file_hash
from communication_pruning.technical_retry import TechnicalAdapter, ref
from project.research_control.recovery import FileWitness
from . import final_r125_resume as previous, final_r_resume as inner
from . import final_secondary as secondary, final_execution as native, final_preflight as gate
from .final_plan import canonical_hash

StudyStop = gate.StudyStop
PANELS, ZERO = secondary.PANELS, secondary.ZERO
CLAIM = 'technical-R00203/claim.json'
_need, _save, _path, _all_files = secondary._need, secondary._save, secondary._path, secondary._all_files
_blocks, _section_states, _record_section = secondary._blocks, secondary._section_states, secondary._record_section
_receipt_path, _verify_receipt, _checkpoint = secondary._receipt_path, secondary._verify_receipt, secondary._checkpoint
_verify_confirmation, _verify_panel_remote = secondary._verify_confirmation, secondary._verify_panel_remote
_require_real_evidence = secondary._require_real_evidence
safe_exception_chain, connection_hash = inner.safe_exception_chain, secondary.connection_hash


def additional_sources():
    files = previous.additional_sources()
    root = Path(__file__).parents[1]
    for name in ('communication_pruning/technical_retry.py','study_preparation/final_technical_resume.py',
                 'study_preparation/final_technical_resume_operator.py','tests/test_technical_retry.py',
                 'tests/test_final_technical_resume.py','tests/test_final_technical_resume_operator.py'):
        p = root/name
        files[str(p.resolve())] = file_hash(p)
    return files


def _scientific(binding):
    return previous._scientific(binding['inner_binding'])


def _ledger(path):
    """Verify the preserved PhaseBudget chain; never repair its failed tail."""
    raw = Path(path).read_bytes()
    _need(raw.endswith(b'\n'), 'partial old ledger')
    rows, last = [], ZERO
    for sequence, line in enumerate(raw.splitlines()):
        row = json.loads(line)
        check = row.pop('sha256')
        _need(row['sequence'] == sequence and row['previous'] == last and digest(row) == check, 'old ledger chain changed')
        last = check; rows.append(row)
    _need(len(rows)%2 == 1 and rows[0]['kind'] == 'header', 'open inherited ledger reservation')
    pairs = list(zip(rows[1::2],rows[2::2]))
    known, unknown = Decimal(0), []
    for i,(r,s) in enumerate(pairs,1):
        _need(r['kind']=='reserved' and s['kind']=='settled' and r['attempt_id']==s['attempt_id']==f'dispatch-{i:05d}'
              and r['reservation_usd']=='0.14' and Decimal(r['known_before_usd'])==known, 'invalid inherited reservation')
        if s['usage']['cost_usd'] is None:
            _need(s['failed'] is True and i==len(pairs), 'unexpected inherited Unknown')
            unknown.append(s['attempt_id'])
        else:
            amount=gate.money(s['usage']['cost_usd'])
            _need(not s['failed'] and not s['over_reservation'] and amount<=Decimal('.14'), 'inherited failed known settlement')
            known += amount
    _need(len(unknown)==1, 'exactly one inherited technical Unknown required')
    return rows[0],pairs,known,unknown


def _partial(candidate,plan,root,number):
    directory=Path(root)/'blocks'/f'{number:06d}'; block=_blocks(plan)[number]
    order=block['arm_order']; done=[a for a in order if (directory/a/'result.json').exists()]
    _need(done==order[:len(done)] and len(done)<len(order), 'partial arm prefix differs')
    arm=order[len(done)]
    _need({p.name for p in directory.iterdir() if p.is_dir()}==set(done+[arm]), 'partial arm directories differ')
    rows,attempts=inner._read_block(candidate,plan,root,number,arms=done)
    public=gate.read_json(directory/'public.json'); task=TaskInput(public['task_id'],public['question'],tuple(public['paragraphs']))
    selection=gate.read_json(directory/'selection.json')
    config,rounds,failed=native._configuration(candidate,block,arm,selection)
    _need(config is not None,'initial retained partial must be a MAS arm')
    saved=read_journal(directory/arm/'journal.jsonl',config); trace=saved['trace']
    run_id=plan['plan_hash'][:16]+':'+next(s['slot_id'] for s in block['slots'] if s['arm']==arm)
    _need(not saved['sealed'] and trace['run_id']==run_id and trace['rounds']==rounds and trace['failed_role']==failed,
          'partial native trace identity differs')
    replay=[]; request=None
    for event in trace['events']:
        if event['kind']=='started':
            request=Request(event['attempt_id'],task,event['role'],event['round'],event['instruction'],
                tuple(Message(**m) for m in event['messages']),event['max_output_tokens'])
        elif event['kind'] in ('completed','model_failed'):
            _need(request is not None and request.attempt_id==event['attempt_id'] and request.attempt_id not in attempts,
                  'partial response identity conflict')
            attempts[request.attempt_id]=(request,event); replay.append(request.attempt_id)
    _need(request is not None and trace['events'][-1]['kind']=='started','no exact unresolved native request')
    return rows,attempts,replay,request,done,arm


def retained_state(old,candidate,plan):
    """Original 125er reader plus exact R125 dispatch/journal verification."""
    root=Path(old['folder']); previous._verify_originals(old); FileGuard(old['source_files'])()
    base=previous._retained(old['inner_binding'],candidate,plan,root/'retained')
    rows=list(base['rows']); attempts=dict(base['attempts'])
    complete=sorted((root/'blocks').glob('*/complete.json')); count=base['completed']+len(complete)
    _need(sorted((root/'blocks').glob('*/started.json')) ==
        [root/'blocks'/f'{i:06d}/started.json' for i in range(base['completed'],count+1)], 'noncontiguous retained blocks')
    for number,path in enumerate(complete,base['completed']):
        _need(path==root/'blocks'/f'{number:06d}/complete.json','retained complete gap')
        current,events=inner._read_block(candidate,plan,root,number)
        inner._verify_block_proof(root,plan,number,current)
        for logical,event in events.items():
            _need(logical not in attempts or attempts[logical]==event,'retained replay changed')
            attempts[logical]=event
        rows.extend(current)
    partial,events,replay,pending,done,arm=_partial(candidate,plan,root,count)
    _need(not set(events)&set(attempts),'partial duplicated result'); attempts.update(events)
    header,pairs,cost,unknown=_ledger(root/'dispatch/budget.jsonl')
    args=previous._budget_args(old,plan)
    _need(all(header[k]==v for k,v in dict(cap_usd=str(args['cap']),reserve_usd=str(args['reserve']),
        max_calls=args['max_calls'],binding=old['sha256'],allow_synthetic=args['allow_synthetic']).items()),'old budget header changed')
    generations=set(base['generations']); states={s['logical_id']:dict(body=Path(s['request']['path']).read_bytes(),
        limit=s['output_limit'],outcome=s['outcome'],retry=0,received=s['received_at']) for s in old['origin']['seeds']}
    retries=0; linked=set(); seeds=[]
    from datetime import datetime
    for index,(reserved,settled) in enumerate(pairs,1):
        droot=root/'dispatch'; stem=f'{index:05d}'
        d=gate.read_json(droot/f'{stem}-binding.json'); body=(droot/f'{stem}-request.json').read_bytes()
        logical=d['logical_id']; prior=states.get(logical); retry=0 if prior is None else prior['retry']+1
        deadline=None if prior is None else prior['received']+(30 if retry==1 else 120)
        retries += int(prior is not None and prior['outcome']=='rate_limited')
        expected=dict(schema='D-055/dispatch-v1',physical_id=f'dispatch-{index:05d}',logical_id=logical,
            request_sha256=sha256(body).hexdigest(),output_limit=d['output_limit'],retry=retry,
            global_retry=retries,not_before=deadline,dispatched_at=d['dispatched_at'])
        _need(d==expected and retry<=2 and retries<=20 and (deadline is None or d['dispatched_at']>=deadline),
              'old physical retry binding differs')
        if prior:
            _need(prior['outcome']=='rate_limited' and prior['body']==body,'old successful response resent')
        guard=gate.read_json(root/'physical'/f'{stem}.json')
        _need(guard['binding']==d and guard['guard_passed'] is True and guard['transport_started_at']>=d['dispatched_at'],
              'old physical guard differs')
        if index==len(pairs):
            _need(logical==pending.attempt_id and body==encoded(payload(pending,producer_limit=1024))
                  and not (droot/f'{stem}-response.json').exists() and not (droot/f'{stem}-received.json').exists()
                  and not (droot/f'{stem}-outcome.json').exists(),'Unknown is not exact unanswered pending request')
            pending_seed=dict(logical_id=logical,request=ref(droot/f'{stem}-request.json'),output_limit=pending.max_output_tokens,
                held_reserve_usd='0.14',outcome='technical',observed_epoch=datetime.fromisoformat(settled['time']).timestamp(),
                origin='r125:'+d['physical_id'])
            continue
        raw=(droot/f'{stem}-response.json').read_bytes(); received=gate.read_json(droot/f'{stem}-received.json')
        outcome,response,usage,generation=classify(received['http_status'],raw,d['output_limit'])
        _need(generation not in generations and usage.to_dict()==settled['usage']
              and received['response_sha256']==sha256(raw).hexdigest() and received['received_at']>=d['dispatched_at']
              and gate.read_json(droot/f'{stem}-outcome.json')==dict(outcome=outcome,generation_id=generation,usage=usage.to_dict()),
              'old received response or billing differs')
        generations.add(generation)
        states[logical]=dict(body=body,limit=d['output_limit'],outcome=outcome,retry=retry,received=received['received_at'])
        if response is not None:
            _need(logical in attempts and body==encoded(payload(attempts[logical][0],producer_limit=1024))
                  and native._terminal(logical,previous._normal_response(response,old['mode']))==attempts[logical][1],
                  'old physical/logical result mismatch')
            linked.add(logical)
        if logical in replay:
            seeds.append(dict(logical_id=logical,output_limit=d['output_limit'],received_at=received['received_at'],
                origin='r125:'+d['physical_id'],**{k:ref(droot/f'{stem}-{k}.json') for k in ('request','response','received')}))
    _need(set(attempts)-set(base['attempts'])==linked-set(base['attempts']) and {s['logical_id'] for s in seeds}==set(replay),
          'old successes not completely mapped')
    stop=gate.read_json(root/'STOP.json')
    _need(stop['retry_allowed'] is False and any(x['class']=='builtins.TimeoutError'
        for x in stop['diagnostic']['exception_classes']), 'initial STOP is not the bound timeout')
    return dict(rows=rows,attempts=attempts,completed=count,partial_rows=partial,seeds=seeds,pending_seed=pending_seed,
        done_arms=done,partial_arm=arm,generations=sorted(generations),known_cost_usd=str(cost),calls=len(pairs),
        rate_retries=retries,old_budget_cap_usd=str(args['cap']),old_max_calls=args['max_calls'])


def prepare_origin(old,candidate,plan):
    state=retained_state(old,candidate,plan)
    if old['mode']!='artificial_only':
        _need(state['completed']==203 and state['calls']==2483 and state['known_cost_usd']=='0.62533709'
              and state['partial_arm']=='Z' and state['done_arms']==['Q','F'],'only bound R203 incident supported')
    return dict(schema='technical-R203-origin/v1',inner_binding_sha256=old['sha256'],
        completed_blocks=plan['counts']['P']+state['completed'],secondary_completed_blocks=state['completed'],
        last_formal_hold=max(int(p.stem) for p in (Path(old['folder'])/'confirmations').glob('*.json')),
        original_inventory=_all_files(old['folder']),witness_inventory=_all_files(old['witness']),
        claim_sha256=file_hash(old['claim_path']),seeds=state['seeds'],pending_seed=state['pending_seed'],
        done_arms=state['done_arms'],partial_arm=state['partial_arm'],generation_ids=state['generations'],
        retained_cost_usd=state['known_cost_usd'],retained_calls=state['calls'],rate_retries=state['rate_retries'],
        remaining_cap_usd=str(Decimal(state['old_budget_cap_usd'])-Decimal(state['known_cost_usd'])-Decimal('.14')),
        remaining_calls=state['old_max_calls']-state['calls'],historical_gaps_repaired=False)


def prepare_binding(candidate,plan,*,inner_binding,origin,folder,control,witness,owner,activation=None):
    return gate.seal(dict(schema='z52-technical-resume/v1',mode=candidate['mode'],candidate_sha256=candidate['sha256'],
        plan_hash=plan['plan_hash'],execution_binding_sha256=gate.execution_binding(candidate),
        scientific_candidate_sha256=inner_binding['scientific_candidate_sha256'],folder=str(_path(folder)),
        control=str(_path(control)),witness=str(_path(witness)),owner=owner,owner_generation=1,
        claim_path=str(_path(control)/CLAIM),inner_binding=deepcopy(inner_binding),origin=deepcopy(origin),
        first_hold=origin['completed_blocks']+1,predecessor=deepcopy(inner_binding['predecessor']),
        analysis_contract=deepcopy(inner_binding['analysis_contract']),source_files=additional_sources(),activation=activation))


def _verify_originals(binding):
    old,origin=binding['inner_binding'],binding['origin']
    previous._verify_originals(old)
    _need(_all_files(old['folder'])==origin['original_inventory'] and _all_files(old['witness'])==origin['witness_inventory']
        and file_hash(old['claim_path'])==origin['claim_sha256'],'original state changed')


def _activation_gate(binding,candidate,plan,clock):
    secondary._activation_gate(binding,candidate,plan,clock)
    if binding['mode']!='artificial_only':
        value=gate.read_json(gate.evidence_file(binding['activation']))
        _need(value.get('technical_completion_authorization')=='Jannik-2026-09-26'
              and value.get('technical_retries')=={'per_logical':2,'global':20,'wait_seconds':[30,120]}
              and value.get('origin_sha256')==canonical_hash(binding['origin']), 'specific technical activation missing')


def _check_binding(binding,candidate,plan,*,folder,control,clock,dependencies=None):
    gate._check_seal(binding); gate._check_seal(binding['inner_binding'])
    old=binding['inner_binding']; origin=binding['origin']; expected=Path(old['folder']).parent/'technical-R00203'
    _need(binding['schema']=='z52-technical-resume/v1' and binding['mode']==candidate['mode']
        and binding['folder']==str(_path(folder))==str(expected/'live') and binding['witness']==str(expected/'witness')
        and binding['control']==str(_path(control))==old['control']==candidate['control_directory']
        and binding['claim_path']==str(_path(control)/CLAIM),'canonical technical identity differs')
    _need(binding['candidate_sha256']==old['candidate_sha256']==candidate['sha256']
        and binding['plan_hash']==old['plan_hash']==plan['plan_hash']
        and binding['execution_binding_sha256']==gate.execution_binding(candidate)
        and binding['source_files']==additional_sources() and binding['analysis_contract']==old['analysis_contract']
        and origin['inner_binding_sha256']==old['sha256'] and binding['first_hold']==origin['completed_blocks']+1,
        'scientific/source identity changed')
    FileGuard(old['source_files'])(); _verify_originals(binding)
    secondary._preflight(binding,candidate,plan,control=control,clock=clock,dependencies=dependencies)
    _analysis_contract(binding,candidate,plan); _activation_gate(binding,candidate,plan,clock)


def _claim(binding,control,*,create=False):
    path=Path(control)/CLAIM
    expected=dict(namespace=gate.NAMESPACE,binding_sha256=binding['sha256'],folder=binding['folder'],control=binding['control'],
        witness=binding['witness'],owner=binding['owner'],origin_sha256=canonical_hash(binding['origin']))
    _need(binding['claim_path']==str(path.resolve()) and not path.is_symlink(),'noncanonical claim')
    if path.exists(): _need(not create and gate.read_json(path)==expected,'claim changed or already exists')
    else: _need(create,'missing claim'); _save(path,expected)


def _witness_binding(binding,folder,control):
    stop=Path(folder)/'STOP.json'
    return dict(incarnation='technical-'+binding['sha256'][:24],activation_sha256=binding['sha256'],
        stop_sha256=file_hash(stop) if stop.exists() else ZERO,stop_active=stop.exists(),owner_generation=1,
        original_journal_sha256=canonical_hash(binding['origin']),admission_journal_sha256=canonical_hash(
        {'files':_all_files(folder),'claim':file_hash(Path(control)/CLAIM)}),admissions=_section_states(folder))


def _witness(binding): return FileWitness(binding['witness'],binding['folder'])
def _publish(binding,folder,control,generation):
    return _witness(binding).checkpoint(generation,_witness_binding(binding,folder,control))['generation']
def _assert_current(binding,folder,control):
    record=_witness(binding).assert_current(_witness_binding(binding,folder,control))
    _need(not (Path(folder)/'STOP.json').exists() and all(v=='settled' for v in _section_states(folder).values()),
          'permanent technical stop or unresolved section')
    return record['generation']


def _adapter(binding,folder,*,transport=None,clock=time.time,sleep=time.sleep,guard=None,restore=True,audit_only=False):
    origin=binding['origin']
    return TechnicalAdapter(Path(folder)/'dispatch',transport,binding=binding['sha256'],cap=origin['remaining_cap_usd'],
        max_calls=origin['remaining_calls'],seeds=origin['seeds'],pending_seed=origin['pending_seed'],
        base_generations=origin['generation_ids'],initial_rate_retries=origin['rate_retries'],
        clock=clock,sleep=sleep,guard=guard,restore=restore,audit_only=audit_only)


def accounting_view(binding,cost,*,held=Decimal(0),reserve_calls=0,account_available=None):
    old=binding['inner_binding']; original_new=Decimal(binding['origin']['retained_cost_usd'])
    view=previous.accounting_view(old,original_new+cost)
    reserved=previous.accounting_view(old,original_new+cost+held+Decimal('.14'),reserve_calls=reserve_calls)
    view['available_usd']=reserved['available_usd']
    view['block_reservation_usd']=reserved['block_reservation_usd']
    if account_available is not None:
        _need(gate.money(str(account_available))>=Decimal('.98')+held,'next request plus all historical/new Unknownreserves uncovered')
    view.update(technical_known_cost_usd=str(cost),technical_unknown_reserve_usd=str(held),
        retained_R204_unknown_cost_usd=None,retained_R204_unknown_reserve_usd='0.14',
        technical_budget_burden_usd=str(cost+held+Decimal('.14')),
        native_budget_burden_includes_reservations=False,actual_total_cost_usd=None,cost_scope='known costs; Unknowns separate')
    return view


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


def _runtime(binding,candidate,plan,clock,panel):
    gate.runtime_guard(candidate,clock=clock,panel=panel); FileGuard(binding['source_files'])(); _claim(binding,binding['control'])
    _need(not (Path(binding['folder'])/'STOP.json').exists(),'persistent stop')
    _activation_gate(binding,candidate,plan,clock)


def _analysis_contract(binding,candidate,plan): return previous._analysis_contract(binding['inner_binding'],candidate,plan)
def _analysis(binding,plan,panel,rows,contract):
    value=previous._analysis(binding['inner_binding'],plan,panel,rows,contract)
    adapter=_adapter(binding,binding['folder'],audit_only=True)
    unknown=[]
    if panel=='R':
        unknown.append(dict(logical_id=binding['origin']['pending_seed']['logical_id'],arm=binding['origin']['partial_arm'],
            physical_id=binding['origin']['pending_seed']['origin'],cost_usd=None,reserve_usd='0.14'))
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


def _evidence(folder):
    return {k:v for k,v in _all_files(folder).items() if k.split('/')[0] in ('retained','blocks','dispatch','physical','replays')
        or k in ('binding.json','provenance.json')}


def _inspect(binding,candidate,plan,folder):
    folder=Path(folder); retained=retained_state(binding['inner_binding'],candidate,plan)
    _need(_all_files(folder/'retained')==binding['origin']['original_inventory'],'copied retained original changed')
    adapter=_adapter(binding,folder,audit_only=True); rows=list(retained['rows']); attempts=dict(retained['attempts'])
    complete=sorted((folder/'blocks').glob('*/complete.json'))
    _need(len(list((folder/'blocks').glob('*/started.json')))==len(complete),'incomplete new block')
    for number,path in enumerate(complete,retained['completed']):
        _need(path==folder/'blocks'/f'{number:06d}/complete.json','new complete gap')
        current,events=inner._read_block(candidate,plan,folder,number); inner._verify_block_proof(folder,plan,number,current)
        for logical,event in events.items():
            _need(logical not in attempts or attempts[logical]==event,'logical response changed')
            attempts[logical]=event
        rows.extend(current)
    terminal={k:v for k,v in adapter.states.items() if v['outcome'] in ('completed','model_failed')}
    seedids={s['logical_id'] for s in binding['origin']['seeds']}
    _need(set(terminal)==(set(attempts)-set(retained['attempts']))|seedids,'physical/logical result sets differ')
    for logical,state in terminal.items():
        request,event=attempts[logical]
        _need(state['body']==encoded(payload(request,producer_limit=1024))
            and native._terminal(logical,previous._normal_response(state['response'],binding['mode']))==event,'physical/logical content differs')
    physical=sorted((folder/'physical').glob('*.json'))
    _need(len(physical)==len(adapter.records),'physical guard count mismatch')
    for index,(path,record) in enumerate(zip(physical,adapter.records),1):
        proof=gate.read_json(path); d=record['dispatch']
        _need(path.name==f'{index:06d}.json' and proof['dispatch']==d and proof['guard_passed'] is True
            and proof['logical_wait_started_at']<=d['dispatched_at']<=proof['guard_checked_at']<=record['receipt']['received_at'],
            'physical runtime/wait proof differs')
        for wait in proof['sleep_intervals']:
            _need(0<wait['requested_seconds']<=30 and proof['logical_wait_started_at']<=wait['started_at']<wait['finished_at']<=d['dispatched_at'],
                'invalid observed wait')
    replay_paths=sorted((folder/'replays').glob('*.json'))
    _need(len(replay_paths)==(len(seedids) if complete else 0),'replay count differs')
    _need({gate.read_json(p)['logical_id'] for p in replay_paths}==(seedids if complete else set()),'replay identity differs')
    # Frozen native journals/rows describe terminal logical responses. Known
    # physical failure fees are added exactly once in explicit analysis rows.
    failed_costs=adapter.known_failed_costs()
    for row in rows:
        extra=sum((cost for logical,cost in failed_costs.items() if logical.startswith(row['run_id']+':')),Decimal(0))
        if extra:
            row['native_terminal_cost_usd']=row['cost_usd']
            row['known_technical_failure_cost_usd']=str(extra)
            row['cost_usd']=str(gate.money(row['cost_usd'])+extra)
            row['cost_provenance']='native terminal response costs plus known physical failure charges; Unknowns separate'
    count=retained['completed']+len(complete)
    value=dict(binding_sha256=binding['sha256'],connection_sha256=connection_hash(binding),
        execution_binding_sha256=gate.execution_binding(candidate),plan_hash=plan['plan_hash'],
        completed_blocks=plan['counts']['P']+count,secondary_completed_blocks=count,complete=count==len(_blocks(plan)),
        rows=rows,budget=adapter.snapshot(),levels=accounting_view(binding,adapter.cost,held=adapter.held),
        generation_ids=sorted(adapter.generations),evidence=_evidence(folder),origin_sha256=canonical_hash(binding['origin']),
        continuation_new_calls=adapter.calls,continuation_new_known_cost_usd=str(adapter.cost),
        historical_witness_continuity=False,historical_deleted_attempts_reconstructed=False,continuous_arm_latency_available=False)
    value['state_sha256']=canonical_hash(value)
    return value,adapter


def initialize(binding,candidate,plan,*,folder,control,clock,checkpoint):
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock)
        folder=Path(folder); _need(not folder.exists() or not any(folder.iterdir()),'new output must be empty')
        _need(prepare_origin(binding['inner_binding'],candidate,plan)==binding['origin'],'origin changed')
        _claim(binding,control,create=True)
        for name in ('blocks','dispatch','physical','replays','receipts','panels','sections'): (folder/name).mkdir(parents=True)
        shutil.copytree(binding['inner_binding']['folder'],folder/'retained')
        _save(folder/'binding.json',binding); _save(folder/'provenance.json',binding['origin'])
        _adapter(binding,folder,restore=False,clock=clock)
        state,_=_inspect(binding,candidate,plan,folder); _checkpoint(folder,state,checkpoint)
        _witness(binding).initialize(_witness_binding(binding,folder,control))
        return state


def _next_end(binding,candidate,state):
    if state['completed_blocks']==binding['origin']['completed_blocks']: return binding['first_hold']
    later=[v for v in candidate['section_ends'] if v>state['completed_blocks']]
    _need(later,'no remaining planned hold'); return later[0]


def _dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock):
    state,adapter=_inspect(binding,candidate,plan,folder); _verify_receipt(folder,state)
    if state['completed_blocks']>binding['origin']['completed_blocks']: _verify_confirmation(binding,folder,state)
    _need(type(section_end) is int and section_end==_next_end(binding,candidate,state),'only next exact hold permitted')
    prefix,end=state['secondary_completed_blocks'],section_end-plan['counts']['P']; blocks=_blocks(plan)
    _need(prefix<end<=len(blocks) and blocks[prefix]['panel']==blocks[end-1]['panel'],'cross-panel section')
    panel=blocks[prefix]['panel']
    if panel!='R': _verify_panel_closeout(binding,candidate,plan,folder,PANELS[PANELS.index(panel)-1])
    _coverage(binding,coverage,clock,adapter,panel)
    _need(gate.money(coverage['native_cost_at_observation_usd'])==adapter.cost,'fresh exact ledger coverage required')
    return state,adapter,prefix,end,panel


def pre_dispatch(binding,candidate,plan,*,folder,control,clock,section_end,coverage):
    with native.study_lock(control):
        _check_binding(binding,candidate,plan,folder=folder,control=control,clock=clock)
        _claim(binding,control); _assert_current(binding,folder,control)
        state,*_=_dispatch_gate(binding,candidate,plan,folder,coverage,section_end,clock)
        return {'state_sha256':state['state_sha256'],'section_end':section_end}


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
                        _need(recovering and request.attempt_id in {s['logical_id'] for s in binding['origin']['seeds']},'unapproved answer replay')
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


def _panel_review(binding,panel,path,review):
    record=gate.read_json(gate.evidence_file(review))
    _need(record==dict(binding_sha256=binding['sha256'],panel=panel,analysis_sha256=file_hash(path),
        reviewer=record.get('reviewer'),not_implementation_author=True,accepted=True)
        and isinstance(record['reviewer'],str) and record['reviewer'].strip() and record['reviewer']!=binding['owner'],'separate panel review missing')


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


# Exact unchanged native hold/read/analysis entrypoint bodies from D078.

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
