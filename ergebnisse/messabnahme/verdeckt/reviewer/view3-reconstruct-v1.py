"""Independent inner-ledger reconstruction from the released synthetic contract.
No production imports, private key, network, tokenizer, or inferred class labels.
"""
from pathlib import Path
from decimal import Decimal
from collections import Counter
import hashlib
import json

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / 'reviewer'
def sha(data):
    return hashlib.sha256(data).hexdigest()
def canon(d):
    return json.dumps(d, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
def readlines(p):
    return [json.loads(x) for x in p.read_text().splitlines()]

manifest = json.loads((OUT/'view3-reconstruction-v1-inputs.json').read_text())
for rec in manifest['files']:
    if sha((BASE/rec['path']).read_bytes()) != rec['sha256']:
        raise ValueError('Input changed: '+rec['path'])

results=[]
for cid in manifest['case_ids']:
    c=json.loads((BASE/'view1'/cid/'case.json').read_text())
    t=json.loads((BASE/'view2'/cid/'trace.json').read_text())
    outer=readlines(BASE/'view2'/cid/'observed_requests.jsonl')
    client=readlines(BASE/'view3'/cid/'client.jsonl')
    usages=readlines(BASE/'view3'/cid/'usage.jsonl')
    tariff=json.loads((BASE/'view3'/cid/'tariff.json').read_text())
    issues=[]
    def issue(code, where, detail):
        issues.append({'code':code,'where':where,'detail':detail})
    starts={}
    outcomes={}
    usage_by_id={}
    order=[]
    successful_outputs={}
    active=[r for r in c['expected_config']['roles'] if r != c['failed_role']]
    allowed_pairs={(a,b) for a,b in c['expected_config']['edges']}
    scheduled=[(rd,r) for rd in range(1,c['rounds']+1) for r in active]+[(c['rounds']+1,'aggregator')]
    stopped=None
    body_checks=[]
    for i,rec in enumerate(client):
        call=rec['call_id']
        kind=rec['kind']
        where=f'client.line[{i+1}]'
        if kind=='started':
            if stopped is not None:
                issue('inner_call_after_stop',where,stopped)
            if call in starts:
                issue('duplicate_inner_call_id',where,call)
            starts[call]=rec
            order.append(call)
            req=rec['request']
            for k in ('attempt_id','round','role'):
                if rec[k]!=req[k]:
                    issue('inner_request_identity_mismatch',where,k)
            expected_id=f"{t['run_id']}:{rec['round']}:{rec['role']}:1"
            if rec['attempt_id']!=expected_id:
                issue('inner_attempt_contract_mismatch',where,{'actual':rec['attempt_id'],'expected':expected_id})
            actual_slot=(rec['round'],rec['role'])
            index=len(order)-1
            if index>=len(scheduled) or actual_slot!=scheduled[index]:
                issue('inner_schedule_mismatch',where,{'observed':actual_slot,'expected':scheduled[index] if index<len(scheduled) else None})
            if req['task']!=t['task']:
                issue('inner_task_mismatch',where,req['task'])
            prior=c['rounds'] if rec['role']=='aggregator' else rec['round']-1
            expected_messages=[]
            for role in active:
                allowed=rec['role']=='aggregator' or rec['role']==role or (role,rec['role']) in allowed_pairs
                if prior>=1 and allowed and (prior,role) in successful_outputs:
                    expected_messages.append(successful_outputs[prior,role])
            if req['messages']!=expected_messages:
                issue('inner_message_contract_violation',where,{'actual':req['messages'],'expected':expected_messages})
            body=rec['model_body']
            bm=body['messages']
            user=json.loads(bm[1]['content'])
            projection=[{k:m[k] for k in ('role','round','text')} for m in req['messages']]
            expected_user={'question':req['task']['question'],'paragraphs':req['task']['paragraphs'],'prior_messages':projection}
            if len(bm)!=2 or bm[0]!={'role':'system','content':req['instruction']} or bm[1]['role']!='user' or user!=expected_user or body['max_tokens']!=req['max_output_tokens']:
                issue('inner_model_projection_mismatch',where,{'observed_user':user,'expected_user':expected_user})
            max_expected=c['output_limits']['aggregator' if rec['role']=='aggregator' else 'producer']
            if req['max_output_tokens']!=max_expected:
                issue('inner_output_limit_mismatch',where,req['max_output_tokens'])
            body_checks.append({'call_id':call,'attempt_id':rec['attempt_id'],'actual_prior_messages':user['prior_messages'],'model_body_sha256':sha(canon(body))})
        elif kind in ('returned','technical_error'):
            if call not in starts or call in outcomes:
                issue('inner_outcome_pairing_violation',where,call)
            outcomes[call]=rec
            if call in starts and rec['attempt_id']!=starts[call]['attempt_id']:
                issue('inner_outcome_identity_mismatch',where,call)
            if kind=='technical_error' or rec.get('finish_reason') in ('empty','length'):
                stopped=call
            elif kind=='returned' and call in starts:
                sr=starts[call]
                successful_outputs[sr['round'],sr['role']]={'attempt_id':sr['attempt_id'],'role':sr['role'],'round':sr['round'],'text':rec['text']}
        else:
            issue('unknown_inner_kind',where,kind)
    for i,u in enumerate(usages):
        call=u['call_id']
        if call in usage_by_id or call not in starts:
            issue('usage_call_pairing_violation',f'usage.line[{i+1}]',call)
        usage_by_id[call]=u
        if call in starts and u['attempt_id']!=starts[call]['attempt_id']:
            issue('usage_attempt_mismatch',f'usage.line[{i+1}]',call)
    if set(starts)!=set(outcomes) or set(starts)!=set(usage_by_id):
        issue('incomplete_inner_evidence','client/usage',{'starts':list(starts),'outcomes':list(outcomes),'usage':list(usage_by_id)})
    # Match each inner request against the next outer request, preserving order.
    outer_cursor=0
    hidden=[]
    cross_matches=[]
    for call in order:
        sr=starts[call]
        candidate=outer[outer_cursor] if outer_cursor<len(outer) else None
        if candidate is not None and candidate['request']==sr['request'] and candidate['model_body']==sr['model_body']:
            cross_matches.append({'call_id':call,'outer_ordinal':outer_cursor+1,'request_and_entire_model_body_equal':True})
            outer_cursor+=1
        else:
            hidden.append(call)
            issue('inner_call_without_matching_outer_record',call,{'attempt_id':sr['attempt_id'],'role':sr['role'],'round':sr['round'],'request':sr['request'],'model_body':sr['model_body']})
    if outer_cursor!=len(outer):
        issue('unmatched_outer_requests','outer',{'next_unmatched_index':outer_cursor,'outer_count':len(outer)})
    known=Decimal(0)
    reported_inner=Decimal(0)
    unknown=[]
    call_details=[]
    known_input_tokens=0
    known_output_tokens=0
    for call in order:
        sr=starts[call]
        u=usage_by_id[call]
        outcome=outcomes[call]
        unresolved=u.get('billing_state')=='unresolved' or u.get('cost_usd') is None or u.get('input_tokens') is None or u.get('output_tokens') is None
        if unresolved:
            truth=None
            unknown.append(call)
            if u.get('cost_usd') is not None:
                issue('unknown_usage_has_known_amount',call,u)
        else:
            known_input_tokens+=u['input_tokens']
            known_output_tokens+=u['output_tokens']
            truth=Decimal(0) if call in tariff['waived_call_ids'] else Decimal(u['input_tokens'])*Decimal(tariff['input_usd_per_token'])+Decimal(u['output_tokens'])*Decimal(tariff['output_usd_per_token'])
            known+=truth
            reported_inner+=Decimal(u['cost_usd'])
            if Decimal(u['cost_usd'])!=truth or u['cost_source']!='synthetic' or u['price_version']!=tariff['version']:
                issue('inner_usage_tariff_mismatch',call,{'usage':u,'recomputed_cost_usd':str(truth)})
        terms=[e for e in t['events'] if e.get('kind') in ('completed','model_failed') and e.get('attempt_id')==sr['attempt_id']]
        if outcome['kind']=='returned':
            if len(terms)!=1:
                issue('trace_terminal_count_against_inner',call,{'attempt_id':sr['attempt_id'],'terminals':len(terms)})
            for term in terms:
                expected_kind='model_failed' if outcome.get('finish_reason') in ('empty','length') else 'completed'
                if term['kind']!=expected_kind or (expected_kind=='completed' and term.get('text')!=outcome.get('text')) or (expected_kind=='model_failed' and term.get('reason')!=outcome.get('finish_reason')):
                    issue('trace_inner_outcome_mismatch',call,{'trace':term,'inner':outcome})
                expected_usage={k:u.get(k) for k in ('input_tokens','output_tokens','cost_usd','cost_source','price_version')}
                if term.get('usage')!=expected_usage:
                    issue('trace_inner_usage_mismatch',call,{'trace':term.get('usage'),'inner':expected_usage})
        elif terms:
            issue('technical_error_falsely_closed_in_trace',call,terms)
        call_details.append({'call_id':call,'attempt_id':sr['attempt_id'],'role':sr['role'],'round':sr['round'],'outcome':outcome['kind'],'finish_reason':outcome.get('finish_reason'),'known_input_tokens':u.get('input_tokens'),'known_output_tokens':u.get('output_tokens'),'waived':call in tariff['waived_call_ids'],'reconstructed_cost_usd':str(truth) if truth is not None else None,'recorded_inner_cost_usd':u.get('cost_usd'),'outer_terminal_records':len(terms)})
    inner_attempts=Counter(sr['attempt_id'] for sr in starts.values())
    trace_starts=Counter(e.get('attempt_id') for e in t['events'] if e.get('kind')=='started')
    orphan_trace_terms=[e for e in t['events'] if e.get('kind') in ('completed','model_failed') and e.get('attempt_id') not in inner_attempts]
    if orphan_trace_terms:
        issue('trace_terminal_without_inner_attempt','trace',orphan_trace_terms)
    total=None if unknown else known
    inner_returns=sum(rec['kind']=='returned' for rec in outcomes.values())
    technical=sum(rec['kind']=='technical_error' for rec in outcomes.values())
    model_failed=sum(rec.get('finish_reason') in ('empty','length') for rec in outcomes.values())
    status='technical_stop' if technical else 'model_failed' if model_failed else 'completed'
    aggregator=successful_outputs.get((c['rounds']+1,'aggregator'))
    answer=aggregator['text'] if status=='completed' and aggregator else None
    if status=='completed' and aggregator is None:
        issue('no_inner_aggregator_after_nonfailed_calls','client',{})
    delta_subtotal=Decimal(c['claimed']['known_cost_subtotal_usd'])-known
    delta_total=Decimal(c['claimed']['total_cost_usd'])-total if c['claimed']['total_cost_usd'] is not None and total is not None else None
    results.append({'case_id':cid,'issues':issues,'counts':{'inner_started':len(order),'inner_returned_including_model_failure':inner_returns,'inner_technical_errors':technical,'model_failed_returns':model_failed,'outer_requests':len(outer),'trace_started':sum(trace_starts.values()),'trace_terminal_events':sum(e.get('kind') in ('completed','model_failed') for e in t['events'])},'reconstructed_status':status,'reconstructed_answer':answer,'known_subtotal_usd':str(known),'total_usd':str(total) if total is not None else None,'unknown_call_ids':unknown,'known_input_tokens':known_input_tokens,'known_output_tokens':known_output_tokens,'claimed_minus_reconstructed_subtotal_usd':str(delta_subtotal),'claimed_minus_reconstructed_total_usd':str(delta_total) if delta_total is not None else None,'inner_calls_missing_outer':hidden,'full_request_model_body_matches':cross_matches,'calls':call_details,'actual_messages':body_checks})

sheet=json.loads((BASE/'view3'/'cost-sheet.json').read_text())
sheet_results=[]
sheet_known=Decimal(0)
for row in sheet['rows']:
    role=row['role']
    amount=None
    status='unsupported'
    if role in ('input_output','paid_model_failure','fresh_repeat','known_zero_price'):
        amount=Decimal(0) if row['price_waived'] else Decimal(row['input_tokens'])*Decimal(sheet['input_usd_per_token'])+Decimal(row['output_tokens'])*Decimal(sheet['output_usd_per_token'])
        status='supported_individual_model_call_amount'
    elif role=='local_controller':
        if row['model_calls']!=0:
            raise ValueError('Unexpected controller model calls')
        amount=Decimal(0)
        status='zero_model_usd_only_local_cpu_measurement_unavailable'
    elif role=='cache':
        amount=Decimal(row['artificial_provider_body']['usage']['cost'])
        status='known_provider_total_only_separate_cache_attribution_unsupported'
    elif role=='automatic_retry':
        status='forbidden_no_executed_call_or_price_inferred'
    if amount is not None:
        sheet_known+=amount
    sheet_results.append({'id':row['id'],'role':role,'amount_usd':str(amount) if amount is not None else None,'support':status})
report={'schema':1,'source':'view3-reconstruct-v1.py','cases':results,'cost_sheet':{'rows':sheet_results,'sum_of_supported_known_amounts_usd':str(sheet_known),'scope':'Synthetic amounts; forbidden automatic retry omitted as not executed, not zero-priced. No separate cache/reasoning rate or measured controller time inferred.'}}
with (OUT/'view3-reconstruction-v1-output.json').open('x') as f:
    json.dump(report,f,ensure_ascii=False,indent=2)
    f.write('\n')
print(json.dumps({'cases':[{k:r[k] for k in ('case_id','issues','counts','reconstructed_status','known_subtotal_usd','total_usd','claimed_minus_reconstructed_subtotal_usd','claimed_minus_reconstructed_total_usd','unknown_call_ids','inner_calls_missing_outer')} for r in results],'cost_sheet':report['cost_sheet']},ensure_ascii=False,indent=2))
