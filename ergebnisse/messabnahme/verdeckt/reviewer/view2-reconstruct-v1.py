"""Independent, contract-derived S2 reconstruction; standard library only.

This routine checks the outer evidence. It does not infer hidden calls or tariff
truth, import production code, or assign planned case classes.
"""
from pathlib import Path
from decimal import Decimal
from collections import Counter
import hashlib
import json

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / 'reviewer'

def sha(b):
    return hashlib.sha256(b).hexdigest()

def canon(d):
    return json.dumps(d, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()

def lines(p):
    return [json.loads(s) for s in p.read_text().splitlines()]

binding = json.loads((OUT / 'view2-reconstruction-v1-inputs.json').read_text())
for f in binding['files']:
    if sha((BASE / f['path']).read_bytes()) != f['sha256']:
        raise ValueError('Input changed: ' + f['path'])

results = []
for cid in binding['case_ids']:
    c = json.loads((BASE / 'view1' / cid / 'case.json').read_text())
    t = json.loads((BASE / 'view2' / cid / 'trace.json').read_text())
    jp = BASE / 'view2' / cid / 'journal.jsonl'
    j = lines(jp)
    requests = lines(BASE / 'view2' / cid / 'observed_requests.jsonl')
    issues = []
    def issue(code, where, detail):
        issues.append(dict(code=code, where=where, detail=detail))
    for tk, ck in [('configuration', 'expected_config'), ('rounds', 'rounds'),
                   ('failed_role', 'failed_role'), ('output_limits', 'output_limits'),
                   ('failure_policy', 'failure_policy')]:
        if t.get(tk) != c[ck]:
            issue('config_mismatch', tk, {'observed': t.get(tk), 'expected': c[ck]})
    roles = c['expected_config']['roles']
    edges = c['expected_config']['edges']
    active = [r for r in roles if r != c['failed_role']]
    schedule = [(k, r, 'suppressed' if r == c['failed_role'] else 'started')
                for k in range(1, c['rounds'] + 1) for r in roles]
    schedule += [(c['rounds'] + 1, 'aggregator', 'started')]
    pos = 0
    starts = {}
    terminals = {}
    raw_cost = Decimal(0)
    known = Decimal(0)
    unknown = []
    prev_outputs = {}
    outstanding = None
    failure = None
    started_events = []
    completed_events = []
    suppression = []
    message_checks = []
    for ei, e in enumerate(t['events']):
        kind = e.get('kind')
        where = f'trace.events[{ei}]'
        if failure is not None:
            issue('event_after_model_failure', where, kind)
        if kind in ('started', 'suppressed'):
            observed_slot = (e.get('round'), e.get('role'), kind)
            if pos >= len(schedule) or observed_slot != schedule[pos]:
                issue('schedule_mismatch', where, {'observed': observed_slot, 'expected': schedule[pos] if pos < len(schedule) else None})
            pos += 1
            if outstanding is not None:
                issue('next_step_before_terminal', where, outstanding)
            if kind == 'suppressed':
                suppression.append(e)
                continue
            aid = e.get('attempt_id')
            expected_aid = f"{t['run_id']}:{e.get('round')}:{e.get('role')}:1"
            if aid != expected_aid:
                issue('attempt_identity_mismatch', where, {'observed': aid, 'expected': expected_aid})
            if aid in starts:
                issue('duplicate_start', where, aid)
            starts.setdefault(aid, e)
            started_events.append(e)
            outstanding = aid
            lim = c['output_limits']['aggregator' if e.get('role') == 'aggregator' else 'producer']
            if e.get('max_output_tokens') != lim:
                issue('output_limit_mismatch', where, e.get('max_output_tokens'))
            wanted = []
            for r in active:
                prior = c['rounds'] if e.get('role') == 'aggregator' else e.get('round', 0)-1
                allowed = e.get('role') == 'aggregator' or r == e.get('role') or [r, e.get('role')] in edges
                if prior >= 1 and allowed and (prior, r) in prev_outputs:
                    wanted.append(prev_outputs[prior, r])
            if e.get('messages') != wanted:
                issue('message_contract_violation', where, {'observed': e.get('messages'), 'expected': wanted})
            message_checks.append({'attempt_id': aid, 'expected': wanted, 'trace_messages': e.get('messages')})
        elif kind in ('completed', 'model_failed'):
            completed_events.append(e)
            aid = e.get('attempt_id')
            u = e.get('usage', {})
            amount = u.get('cost_usd')
            if amount is not None:
                raw_cost += Decimal(amount)
            if aid not in starts:
                issue('terminal_without_matching_start', where, aid)
                continue
            if aid in terminals:
                issue('duplicate_terminal', where, aid)
                continue
            if aid != outstanding:
                issue('terminal_not_current_attempt', where, {'observed': aid, 'outstanding': outstanding})
            terminals[aid] = e
            if aid == outstanding:
                outstanding = None
            if amount is None:
                unknown.append(aid)
            else:
                known += Decimal(amount)
            if u.get('cost_source') != 'synthetic':
                issue('cost_source_mismatch', where, u.get('cost_source'))
            if kind == 'model_failed':
                failure = aid
                if e.get('reason') not in ('empty', 'length') or amount is None:
                    issue('invalid_f01_terminal', where, e)
            else:
                se = starts[aid]
                prev_outputs[se['round'], se['role']] = dict(attempt_id=aid, role=se['role'], round=se['round'], text=e.get('text'))
        else:
            issue('unknown_event_kind', where, kind)
    open_aids = [a for a in starts if a not in terminals]
    if t.get('status') == 'completed':
        if pos != len(schedule) or open_aids or failure:
            issue('invalid_completed_status', 'trace.status', {'schedule_slots_seen': pos, 'required': len(schedule), 'open': open_aids, 'failure': failure})
        aggregator = prev_outputs.get((c['rounds']+1, 'aggregator'))
        if aggregator is None or t.get('answer') != aggregator['text']:
            issue('answer_not_aggregator_result', 'trace.answer', t.get('answer'))
    elif t.get('status') == 'model_failed':
        if failure is None or t.get('answer') is not None or open_aids:
            issue('invalid_failed_status', 'trace.status', {'failure': failure, 'open': open_aids})
    elif 'status' in t or 'answer' in t:
        issue('unsupported_terminal_status', 'trace', {'status': t.get('status'), 'answer': t.get('answer')})
    elif not open_aids:
        issue('unsealed_without_open_attempt', 'trace', {})
    # Independently validate every journal envelope and replay its payload.
    chain_ok = True
    previous = None
    journal_events = []
    finished = []
    for ji, row in enumerate(j):
        w = f'journal.line[{ji+1}]'
        unsigned = {k:v for k,v in row.items() if k != 'checksum'}
        if row.get('checksum') != sha(canon(unsigned)):
            chain_ok = False
            issue('journal_checksum_mismatch', w, {'stored': row.get('checksum'), 'recomputed': sha(canon(unsigned))})
        if row.get('seq') != ji or row.get('journal_schema') != 1 or row.get('run_id') != t['run_id'] or row.get('previous') != previous:
            chain_ok = False
            issue('journal_envelope_mismatch', w, {'seq': row.get('seq'), 'run_id': row.get('run_id'), 'previous': row.get('previous'), 'expected_previous': previous})
        previous = row.get('checksum')
        p = row['payload']
        if finished:
            issue('journal_after_finished', w, p.get('kind'))
        if ji == 0:
            expected_header = {k:v for k,v in t.items() if k not in ('answer','status')}
            expected_header['events'] = []
            if p != {'kind':'header','trace':expected_header}:
                issue('journal_header_trace_mismatch', w, p)
        elif p.get('kind') == 'event':
            journal_events.append(p['event'])
        elif p.get('kind') == 'finished':
            finished.append(p)
        else:
            issue('journal_payload_kind', w, p.get('kind'))
    if not jp.read_bytes().endswith(b'\n'):
        issue('journal_missing_newline', 'journal', {})
    if journal_events != t['events']:
        differences = [{'event_index': i, 'journal': a, 'trace': b} for i,(a,b) in enumerate(zip(journal_events,t['events'])) if a != b]
        issue('journal_trace_events_mismatch', 'journal', {'journal_count': len(journal_events), 'trace_count': len(t['events']), 'differences': differences})
    expected_finish = [{'kind':'finished','answer':t['answer'],'status':t['status']}] if 'status' in t else []
    if finished != expected_finish:
        issue('journal_finished_mismatch', 'journal', {'observed': finished, 'expected': expected_finish})
    # Match actual outer requests and model messages to the trace and contract.
    req_summaries = []
    if len(requests) != len(started_events):
        issue('request_start_count_mismatch', 'observed_requests', {'requests':len(requests),'starts':len(started_events)})
    for qi, q in enumerate(requests):
        req = q['request']
        body = q['model_body']
        w = f'observed_requests.line[{qi+1}]'
        if q.get('ordinal') != qi+1:
            issue('request_ordinal_mismatch', w, q.get('ordinal'))
        if qi < len(started_events):
            se = started_events[qi]
            expected_request = {k:v for k,v in se.items() if k != 'kind'}
            expected_request['task'] = t['task']
            if req != expected_request:
                issue('request_trace_mismatch', w, {'observed': req, 'expected': expected_request})
        bm = body.get('messages', [])
        try:
            user = json.loads(bm[1]['content'])
            desired_user = {'question':t['task']['question'], 'paragraphs':t['task']['paragraphs'], 'prior_messages':[{k:m[k] for k in ('role','round','text')} for m in req['messages']]}
            if len(bm)!=2 or bm[0] != {'role':'system','content':req['instruction']} or bm[1]['role']!='user' or user!=desired_user or body.get('max_tokens')!=req['max_output_tokens']:
                issue('model_body_request_mismatch', w, {'observed_user':user,'expected_user':desired_user})
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            issue('model_body_not_parseable', w, repr(exc))
            user = None
        req_summaries.append({'ordinal':qi+1,'attempt_id':req['attempt_id'],'role':req['role'],'round':req['round'],'prior_messages':user.get('prior_messages') if user else None,'model_body_sha256':sha(canon(body))})
    established_total = known if not open_aids and not unknown and len(finished)==1 else None
    results.append({'case_id':cid,'issues':issues,'trace_status':t.get('status'),'trace_answer':t.get('answer'),'counts':{'started_events':len(started_events),'distinct_started_attempts':len(starts),'terminal_events':len(completed_events),'matched_unique_terminals':len(terminals),'outer_requests':len(requests)},'open_attempts':open_aids,'suppressed':suppression,'model_failure_attempt':failure,'costs':{'raw_terminal_event_sum_usd':str(raw_cost),'matched_unique_known_subtotal_usd':str(known),'unknown_terminal_amounts':unknown,'outer_record_total_if_complete_usd':str(established_total) if established_total is not None else None,'scope':'Recorded amounts only; no independent tariff truth. Invalid evidence can restrict whether these are trusted totals.'},'journal':{'lines':len(j),'chain_ok':chain_ok,'finished_records':len(finished)},'message_checks':message_checks,'outer_requests':req_summaries,'claimed':c['claimed']})

report = {'schema':1,'scope':'S2 independent outer-evidence reconstruction','source':'view2-reconstruct-v1.py','cases':results}
with (OUT / 'view2-reconstruction-v1-output.json').open('x') as f:
    json.dump(report,f,ensure_ascii=False,indent=2)
    f.write('\n')
print(json.dumps({'cases':[{'case_id':r['case_id'],'issues':r['issues'],'counts':r['counts'],'open_attempts':r['open_attempts'],'costs':r['costs'],'journal':r['journal']} for r in results]},ensure_ascii=False,indent=2))
