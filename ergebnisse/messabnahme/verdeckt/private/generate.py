"""Z37 creator. Not blind; never use audit/read_journal as a reference.

The current Journal invokes the production audit internally during execution.
That is instrument behavior, not the source of the independently fixed schedule,
native call record, tariff, expected cost or planted-violation key below.
All manufactured artifacts are create-only. Private attempts remain preserved.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import random
import shutil
import socket
import statistics
import sys
import time
import traceback
import zipfile

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
EVAL = RUN.parents[1]
ROOT = EVAL.parents[1]
sys.path.insert(0, str(EVAL))

from communication_pruning.contracts import Configuration, Message, Response, TaskInput, Usage
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, ModelFailure
from communication_pruning.openrouter import MODEL, decode_billing, payload

SEED = 3709202613
CLASSES = ('K1', 'K2', 'K3', 'K4', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7', 'V8')
ROLES = ('evidence', 'linking', 'draft')
EDGES = (('evidence', 'linking'), ('linking', 'draft'), ('draft', 'evidence'))
PIN = Decimal('0.0000017')
POUT = Decimal('0.0000031')
PRICE = 'Z37-synthetic-20260913'


def network_forbidden(*args, **kwargs):
    raise RuntimeError('Z37 forbids network connections')


socket.create_connection = network_forbidden
socket.socket.connect = network_forbidden
socket.socket.connect_ex = network_forbidden


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def plain(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False, allow_nan=False))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as out:
        json.dump(value, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write('\n')


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False) + '\n')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def independent_schedule(run_id, rounds, failed_role):
    """Contract reconstruction, no executor/auditor call or output used."""
    rows = []
    previous = {}
    for round_no in range(1, rounds + 1):
        current = {}
        for role in ROLES:
            if role == failed_role:
                continue
            identity = f'{run_id}:{round_no}:{role}:1'
            sources = [source for source in ROLES if source in previous
                       and (source == role or (source, role) in EDGES)]
            rows.append({'attempt_id': identity, 'role': role, 'round': round_no,
                         'message_attempt_ids': [previous[source] for source in sources]})
            current[role] = identity
        previous = current
    rows.append({'attempt_id': f'{run_id}:{rounds + 1}:aggregator:1',
                 'role': 'aggregator', 'round': rounds + 1,
                 'message_attempt_ids': [previous[role] for role in ROLES if role in previous]})
    return rows


class SyntheticClient:
    def __init__(self, case_id, mode):
        self.case_id = case_id
        self.mode = mode
        self.observed = []
        self.client = []
        self.usage = []
        self.outputs = {}
        self.outer_count = 0

    def native(self, request, *, technical=False, model_failed=False):
        index = len(self.usage) + 1
        call_id = f'{self.case_id}-n{index:02d}'
        body = payload(request, producer_limit=1024)
        self.client.append({'kind': 'started', 'call_id': call_id,
                            'attempt_id': request.attempt_id, 'role': request.role,
                            'round': request.round, 'request': plain(asdict(request)),
                            'model_body': body})
        if technical:
            self.usage.append({'call_id': call_id, 'attempt_id': request.attempt_id,
                               'input_tokens': None, 'output_tokens': None, 'cost_usd': None,
                               'cost_source': 'unknown', 'price_version': PRICE,
                               'billing_state': 'unresolved'})
            self.client.append({'kind': 'technical_error', 'call_id': call_id,
                                'attempt_id': request.attempt_id,
                                'error': 'synthetic interrupted response before billing receipt'})
            raise RuntimeError('synthetic interrupted response before billing receipt')
        # New declared synthetic quantities; deliberately not tokenized benchmark text.
        input_tokens = 113 + 17 * index + 5 * len(request.messages)
        output_tokens = 19 + 3 * index if request.role != 'aggregator' else 23
        waived = index == 1
        amount = Decimal(0) if waived else input_tokens * PIN + output_tokens * POUT
        usage = {'call_id': call_id, 'attempt_id': request.attempt_id,
                 'input_tokens': input_tokens, 'output_tokens': output_tokens,
                 'cost_usd': str(amount), 'cost_source': 'synthetic',
                 'price_version': PRICE, 'billing_state': 'known'}
        self.usage.append(usage)
        text = '' if model_failed else f'{self.case_id}|{request.role}|{request.round}|amber'
        self.client.append({'kind': 'returned', 'call_id': call_id,
                            'attempt_id': request.attempt_id, 'text': text,
                            'finish_reason': 'empty' if model_failed else 'stop'})
        self.outputs[(request.role, request.round)] = Message(request.attempt_id, request.role, request.round, text)
        reported = Usage(input_tokens, output_tokens, amount, 'synthetic', PRICE)
        return ModelFailure('', reported, 'empty') if model_failed else Response(text, reported)

    def __call__(self, request):
        self.outer_count += 1
        if self.mode == 'V1' and request.role == 'linking' and request.round == 2:
            # draft -> linking is not an allowed edge; really passed to native().
            request = replace(request, messages=request.messages + (self.outputs[('draft', 1)],))
        self.observed.append({'ordinal': self.outer_count, 'request': plain(asdict(request)),
                              'model_body': payload(request, producer_limit=1024)})
        response = self.native(request,
                               technical=self.mode in ('K4', 'V4') and self.outer_count == 3,
                               model_failed=self.mode == 'K3' and self.outer_count == 3)
        if self.mode == 'V2' and self.outer_count == 2:
            # A separate actual inner call not represented at the outer boundary.
            extra = replace(request, attempt_id=request.attempt_id + ':aux')
            self.native(extra)
        if self.mode == 'V3' and self.outer_count == 3:
            # False adapter amount, while independently recorded inner truth is retained.
            old = response.usage
            response = Response(response.text, Usage(old.input_tokens, old.output_tokens,
                                                      old.cost_usd + Decimal('0.00037'),
                                                      'synthetic', PRICE))
        return response

    def tariff(self):
        return {'kind': 'declared_synthetic_tariff', 'version': PRICE,
                'currency': 'USD', 'input_usd_per_token': str(PIN),
                'output_usd_per_token': str(POUT),
                'request_usd': '0', 'waived_call_ids': [f'{self.case_id}-n01'],
                'cache_price': None, 'reasoning_price': None,
                'scope': 'Artificial ledger only. Native usage counts are declared values; no real tokenizer/provider claim.'}


def manual_journal(path):
    """Only deserialize creator evidence; do not validate via production routines."""
    records = [json.loads(line) for line in path.read_text().splitlines()]
    trace = deepcopy(records[0]['payload']['trace'])
    for record in records[1:]:
        item = record['payload']
        if item['kind'] == 'event':
            trace['events'].append(deepcopy(item['event']))
        elif item['kind'] == 'finished':
            trace.update(answer=item['answer'], status=item['status'])
    return records, trace


def reseal(records):
    """Manufacture coherent envelopes for content variants, not an audit."""
    previous = None
    for seq, record in enumerate(records):
        record['seq'] = seq
        record['previous'] = previous
        body = {key: value for key, value in record.items() if key != 'checksum'}
        record['checksum'] = sha256(canonical(body)).hexdigest()
        previous = record['checksum']
    return records


def trace_from_records(records):
    trace = deepcopy(records[0]['payload']['trace'])
    for record in records[1:]:
        item = record['payload']
        if item['kind'] == 'event':
            trace['events'].append(deepcopy(item['event']))
        elif item['kind'] == 'finished':
            trace.update(answer=item['answer'], status=item['status'])
    return trace


def independently_priced(usage, tariff):
    total = Decimal(0)
    unknown = 0
    for item in usage:
        if item['billing_state'] != 'known':
            unknown += 1
            continue
        price = (Decimal(0) if item['call_id'] in tariff['waived_call_ids'] else
                 item['input_tokens'] * Decimal(tariff['input_usd_per_token'])
                 + item['output_tokens'] * Decimal(tariff['output_usd_per_token']))
        if price != Decimal(item['cost_usd']):
            raise AssertionError('native tariff/usage construction disagreement')
        total += price
    return {'started_inner_calls': len(usage), 'known_inner_calls': len(usage) - unknown,
            'unresolved_inner_calls': unknown, 'known_cost_subtotal_usd': str(total),
            'total_cost_usd': None if unknown else str(total)}


def build_case(case_id, mode, destination):
    folder = destination / case_id
    folder.mkdir(parents=True)
    run_id = f'run-{case_id}'
    config = Configuration('bank-' + case_id, ROLES, EDGES)
    rounds = 1 if mode == 'K2' else 2
    failed_role = 'linking' if mode == 'K2' else None
    task = TaskInput('task-' + case_id, 'Welche Markierung trägt der künstliche Behälter?',
                     (f'Im künstlichen Register {case_id} trägt der Behälter die Markierung amber.',
                      'Dieser Text dient ausschließlich einer technischen Fallprüfung.'))
    client = SyntheticClient(case_id, mode)
    journal = folder / 'original-journal.jsonl'
    try:
        original_trace = execute(task, config, client, rounds=rounds, failed_role=failed_role,
                                 run_id=run_id, journal_path=journal,
                                 producer_limit=1024, failure_policy=F01)
    except RuntimeError:
        if mode not in ('K4', 'V4'):
            raise
        (folder / 'expected-technical-stop.log').write_text(traceback.format_exc())
        _, original_trace = manual_journal(journal)
    write_json(folder / 'original-trace.json', original_trace)
    records, parsed = manual_journal(journal)
    if parsed != original_trace:
        raise AssertionError('construction trace/journal mismatch before variants')
    schedule = independent_schedule(run_id, rounds, failed_role)
    actual_outer = [row['request']['attempt_id'] for row in client.observed]
    expected_outer = [row['attempt_id'] for row in schedule]
    if mode in ('K3', 'K4', 'V4'):
        expected_outer = expected_outer[:3]
    if actual_outer != expected_outer:
        raise AssertionError('outer schedule differs from independently constructed plan')
    violations = []
    for index, row in enumerate(client.observed):
        ids = [m['attempt_id'] for m in row['request']['messages']]
        if ids != schedule[index]['message_attempt_ids']:
            violations.append({'attempt_id': row['request']['attempt_id'], 'observed': ids,
                               'allowed': schedule[index]['message_attempt_ids']})
    if bool(violations) != (mode == 'V1'):
        raise AssertionError('unexpected message variant in construction')
    notes = []
    if mode == 'V1':
        actual = next(row['request'] for row in client.observed
                      if row['request']['role'] == 'linking' and row['request']['round'] == 2)
        event = next(record['payload']['event'] for record in records
                     if record['payload']['kind'] == 'event'
                     and record['payload']['event'].get('kind') == 'started'
                     and record['payload']['event'].get('attempt_id') == actual['attempt_id'])
        event['messages'] = actual['messages']
        records = reseal(records)
        notes.append('The outer wrapper actually injected the forbidden prior message. Started messages were then coherently made to describe that real request; all envelope hashes rebuilt. Responses are role/round constants, so no additional downstream text mutation.')
    if mode == 'V5':
        index = next(i for i, record in enumerate(records)
                     if record['payload']['kind'] == 'event'
                     and record['payload']['event'].get('kind') == 'completed'
                     and record['payload']['event'].get('attempt_id', '').endswith(':1:linking:1'))
        records.pop(index)
        records = reseal(records)
        notes.append('One completed event removed; later events/closure retained. Envelope sequence and hashes rebuilt to isolate semantic event completeness.')
    if mode == 'V6':
        index = next(i for i, record in enumerate(records)
                     if record['payload']['kind'] == 'event'
                     and record['payload']['event'].get('kind') == 'completed')
        records.insert(index + 1, deepcopy(records[index]))
        records = reseal(records)
        notes.append('One completed event duplicated; envelope sequence and hashes rebuilt.')
    if mode == 'V7':
        event = next(record['payload']['event'] for record in records
                     if record['payload']['kind'] == 'event'
                     and record['payload']['event'].get('kind') == 'completed')
        event['attempt_id'] = event['attempt_id'].replace(':evidence:', ':checking:')
        records = reseal(records)
        notes.append('One terminal attempt ID assigned to a different role. Envelope hashes rebuilt; native evidence unchanged.')
    if mode == 'V8':
        event = next(record['payload']['event'] for record in records
                     if record['payload']['kind'] == 'event'
                     and record['payload']['event'].get('kind') == 'completed')
        event['usage']['price_version'] += '-r'
        notes.append('One terminal event price-version string changed after binding, without rehashing. Counts, amount, message content and final result unchanged. This tests detectable record integrity, not forged replacement of all anchors.')
    final_trace = trace_from_records(records)
    # Claims are independently declared construction outputs, never auditor totals.
    terminal = [e for e in original_trace['events'] if e['kind'] in ('completed', 'model_failed')]
    declared_subtotal = sum((Decimal(e['usage']['cost_usd']) for e in terminal), Decimal(0))
    complete = 'status' in original_trace
    claimed = {'status': original_trace.get('status', 'technical_stop'),
               'answer': original_trace.get('answer'), 'measurement_complete': complete,
               'started_attempts': len(client.observed), 'calls': len(terminal),
               'known_cost_subtotal_usd': str(declared_subtotal),
               'total_cost_usd': str(declared_subtotal) if complete else None}
    if mode == 'V4':
        claimed.update(status='completed', answer=f'{case_id}|aggregator|3|amber',
                       measurement_complete=True, total_cost_usd=str(declared_subtotal))
        notes.append('Only the report treats unresolved billing as zero and asserts completion. The genuine open journal and trace are retained exactly. This is a false reporting claim, not an invalid F-01 unknown terminal record.')
    if mode == 'V2':
        notes.append('An extra inner call occurs after outer call 2; it is missing at the outer request/journal boundary. No journal forgery is needed. Native counts and native tariff sum retain the extra call.')
    if mode == 'V3':
        notes.append('One adapter-returned cost and the resulting report subtotal/total are consistently increased by 0.00037 USD. Native usage and tariff are unchanged. All journal envelopes are genuinely produced by current execution.')
    expected_native = len(client.observed) + int(mode == 'V2')
    if len(client.usage) != expected_native:
        raise AssertionError('native construction count mismatch')
    native_truth = independently_priced(client.usage, client.tariff())
    current = {'case_id': case_id, 'expected_config': plain(asdict(config)),
               'rounds': rounds, 'failed_role': failed_role,
               'output_limits': {'producer': 1024, 'aggregator': 128},
               'failure_policy': F01, 'claimed': claimed}
    public = destination.parent / 'public-staging'
    write_json(public / 'view1' / case_id / 'case.json', current)
    write_json(public / 'view2' / case_id / 'trace.json', final_trace)
    public_journal = public / 'view2' / case_id / 'journal.jsonl'
    if mode in ('V1', 'V5', 'V6', 'V7', 'V8'):
        write_jsonl(public_journal, records)
    else:
        shutil.copyfile(journal, public_journal)
    write_jsonl(public / 'view2' / case_id / 'observed_requests.jsonl', client.observed)
    write_jsonl(public / 'view3' / case_id / 'client.jsonl', client.client)
    write_jsonl(public / 'view3' / case_id / 'usage.jsonl', client.usage)
    write_json(public / 'view3' / case_id / 'tariff.json', client.tariff())
    expected_instrument = {
        'trace_accepted': mode not in ('V1', 'V5', 'V6', 'V7'),
        'journal_accepted': mode not in ('V1', 'V5', 'V6', 'V7', 'V8'),
        'partial': mode in ('K4', 'V4'),
        'provenance': 'Contract-derived expectation only; not instrument execution.'}
    expected = {'case_id': case_id, 'class': mode, 'rounds': rounds,
                'failed_role': failed_role, 'independent_schedule': schedule,
                'observed_request_count': len(client.observed),
                'actual_transferred_prior_messages': [row['request']['messages'] for row in client.observed],
                'native_truth': native_truth,
                'true_status': original_trace.get('status', 'technical_stop'),
                'true_answer': original_trace.get('answer'),
                'measurement_complete': complete,
                'expected_instrument': expected_instrument,
                'message_violations': violations, 'manufacturing_notes': notes,
                'read_depth': 'Current production execution with injected synthetic client; independent schedule and Decimal tariff reconstruction. No main-auditor result used as truth.'}
    write_json(folder / 'manufacturing.json', expected)
    return expected, task, config


def cost_sheet():
    rows = [
        {'id': 'r01', 'role': 'input_output', 'input_tokens': 80, 'output_tokens': 11, 'price_waived': False},
        {'id': 'r02', 'role': 'paid_model_failure', 'input_tokens': 90, 'output_tokens': 7, 'price_waived': False},
        {'id': 'r03', 'role': 'fresh_repeat', 'input_tokens': 80, 'output_tokens': 11, 'price_waived': False, 'fresh_attempt_of': 'r01'},
        {'id': 'r04', 'role': 'known_zero_price', 'input_tokens': 50, 'output_tokens': 8, 'price_waived': True},
        {'id': 'r05', 'role': 'local_controller', 'model_calls': 0, 'local_cpu_unit': 'nanoseconds', 'local_cpu_value': None},
        {'id': 'r06', 'role': 'cache', 'separate_current_schema_field': False,
         'artificial_provider_body': {'id': 'synthetic-cost-sheet-06', 'model': MODEL, 'provider': 'Google',
                                     'usage': {'prompt_tokens': 90, 'completion_tokens': 7, 'total_tokens': 97,
                                               'is_byok': False, 'cost': '0.00009',
                                               'prompt_tokens_details': {'cached_tokens': 20}}},
         'scope': 'Known total must be retained; cache-specific rate/attribution is not independently established.'},
        {'id': 'r07', 'role': 'automatic_retry', 'allowed_current_execution': False, 'amount': None},
    ]
    truth = []
    production_observations = []
    for row in rows:
        if 'input_tokens' in row:
            value = Decimal(0) if row['price_waived'] else row['input_tokens'] * PIN + row['output_tokens'] * POUT
            truth.append({'id': row['id'], 'status': 'supported_known', 'cost_usd': str(value)})
            stored = Usage(row['input_tokens'], row['output_tokens'], value, 'synthetic', PRICE).to_dict()
            if Decimal(stored['cost_usd']) != value:
                raise AssertionError('Usage did not preserve known amount')
            production_observations.append({'id': row['id'], 'function': 'Usage.to_dict', 'result': stored})
        elif row['role'] == 'local_controller':
            truth.append({'id': row['id'], 'status': 'no_model_call', 'cost_usd': '0',
                          'limit': 'Local CPU time is not monetized as model USD.'})
        elif row['role'] == 'cache':
            stored, identity = decode_billing(json.dumps(row['artificial_provider_body']))
            if stored.cost_usd != Decimal('0.00009'):
                raise AssertionError('decode_billing did not preserve the independently declared total')
            production_observations.append({'id': row['id'], 'function': 'decode_billing',
                                            'generation': identity, 'result': stored.to_dict()})
            truth.append({'id': row['id'], 'status': 'known_aggregate_preserved', 'cost_usd': '0.00009',
                          'limit': 'No separate cache field or independently checked cache tariff. No real provider evidence.'})
        else:
            truth.append({'id': row['id'], 'status': 'not_separately_supported', 'cost_usd': None})
    sheet = {'kind': 'one_deterministic_cost_role_sheet', 'currency': 'USD',
             'input_usd_per_token': str(PIN), 'output_usd_per_token': str(POUT), 'rows': rows,
             'limits': 'Artificial roles only. No real cache/reasoning provider evidence. A fresh repetition is not an automatic retry. Missing special-role support remains a limit.'}
    return sheet, truth, production_observations


def overhead(destination, task, config, case_id):
    """Exactly 20 paired executions, no repeated timing campaign or target."""
    results = []
    folder = destination / 'overhead'
    folder.mkdir()
    for index in range(20):
        order = ('without', 'with') if index % 2 == 0 else ('with', 'without')
        pair = {'pair': index + 1, 'order': list(order), 'measurements': {}}
        for mode in order:
            slot = folder / f'{index + 1:02d}-{mode}'
            slot.mkdir()
            client = SyntheticClient(case_id, 'K1')
            journal = slot / 'journal.jsonl' if mode == 'with' else None
            # Identical input including run_id; different storage destination only.
            start = time.perf_counter_ns()
            trace = execute(task, config, client, rounds=2, run_id=f'overhead-{case_id}',
                            journal_path=journal, producer_limit=1024, failure_policy=F01)
            elapsed = time.perf_counter_ns() - start
            pair['measurements'][mode] = {'wall_ns': elapsed,
                                          'journal_bytes': journal.stat().st_size if journal else 0}
            write_json(slot / 'trace.json', trace)
            write_jsonl(slot / 'client.jsonl', client.client)
            write_jsonl(slot / 'observed_requests.jsonl', client.observed)
        without = json.loads((folder / f'{index + 1:02d}-without' / 'trace.json').read_text())
        with_journal = json.loads((folder / f'{index + 1:02d}-with' / 'trace.json').read_text())
        if without != with_journal:
            raise AssertionError('paired artificial execution outputs differ')
        pair['difference_ns'] = pair['measurements']['with']['wall_ns'] - pair['measurements']['without']['wall_ns']
        results.append(pair)
    differences = [row['difference_ns'] for row in results]
    return {'paired_repetitions': 20, 'results': results,
            'difference_ns': {'median': statistics.median(differences),
                              'minimum': min(differences), 'maximum': max(differences)},
            'interpretation': 'Local synthetic journal/fsync plus repeated contract-check overhead in this runtime only. No provider latency, power claim, target or repeated timing selection.'}


def main():
    binding = json.loads((HERE / 'source-manifest.json').read_text())
    if digest(HERE / binding['archive']) != binding['archive_sha256']:
        raise RuntimeError('source archive changed')
    if digest(HERE / 'runtime-001.zip') != binding['runtime_archive_sha256']:
        raise RuntimeError('runtime archive changed')
    for item in binding['files']:
        if digest(ROOT / item['path']) != item['sha256']:
            raise RuntimeError('prebound input changed: ' + item['path'])
    attempt = HERE / 'generation-001'
    attempt.mkdir()
    write_json(attempt / 'START.json', {'source_manifest_sha256': digest(HERE / 'source-manifest.json'),
                                      'seed': SEED, 'cases': 12, 'overhead_pairs': 20,
                                      'network_disabled_in_process': True,
                                      'role': 'informed creator, not blind reviewer'})
    rng = random.Random(SEED)
    labels = list(CLASSES)
    rng.shuffle(labels)
    ids = ['p-' + ''.join(rng.sample('23456789abcdefghjkmnpqrstuvwxyz', 9)) for _ in labels]
    if len(set(ids)) != 12:
        raise AssertionError('neutral IDs not unique')
    expected = []
    timing_args = None
    for case_id, label in zip(ids, labels):
        truth, task, config = build_case(case_id, label, attempt / 'cases')
        expected.append(truth)
        if label == 'K1':
            timing_args = task, config, case_id
    sheet, sheet_truth, sheet_observations = cost_sheet()
    write_json(attempt / 'public-staging' / 'view3' / 'cost-sheet.json', sheet)
    write_json(attempt / 'cost-sheet-truth.json', sheet_truth)
    write_json(attempt / 'cost-sheet-production.json', sheet_observations)
    timing = overhead(attempt, *timing_args)
    write_json(attempt / 'overhead.json', timing)
    write_json(HERE / 'answer-key.json', {'kind': 'pre-review creator key', 'seed': SEED,
                                        'cases': expected, 'cost_sheet': sheet_truth,
                                        'not_blind': True, 'auditor_used_as_reference': False})
    key_rows = []
    with zipfile.ZipFile(HERE / 'truth-001.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        paths = [HERE / 'answer-key.json'] + sorted(p for p in attempt.rglob('*') if p.is_file())
        for path in paths:
            member = str(path.relative_to(HERE))
            archive.write(path, member)
            key_rows.append({'path': member, 'sha256': digest(path), 'bytes': path.stat().st_size})
    write_json(HERE / 'truth-manifest.json', {'archive': 'truth-001.zip',
                                             'archive_sha256': digest(HERE / 'truth-001.zip'),
                                             'files': key_rows, 'stage': 'Before reviewer starts'})
    for view in ('view1', 'view2', 'view3'):
        if (RUN / view).exists():
            raise RuntimeError('public view already exists: ' + view)
        shutil.copytree(attempt / 'public-staging' / view, RUN / view)
    public_rows = [{'path': str(path.relative_to(RUN)), 'sha256': digest(path), 'bytes': path.stat().st_size}
                   for view in ('view1', 'view2', 'view3') for path in sorted((RUN / view).rglob('*')) if path.is_file()]
    public_rows.append({'path': 'contract.md', 'sha256': digest(RUN / 'contract.md'),
                        'bytes': (RUN / 'contract.md').stat().st_size})
    write_json(RUN / 'PUBLIC-MANIFEST.json', {'files': public_rows, 'case_count': 12,
                                            'source_manifest_sha256': digest(HERE / 'source-manifest.json'),
                                            'answer_key_sha256': digest(HERE / 'answer-key.json'),
                                            'truth_archive_sha256': digest(HERE / 'truth-001.zip'),
                                            'truth_manifest_sha256': digest(HERE / 'truth-manifest.json')})
    write_json(RUN / 'HANDOFF.json', {
        'case_count': 12, 'views': ['view1', 'view2', 'view3'], 'contract': 'contract.md',
        'public_manifest': 'PUBLIC-MANIFEST.json',
        'public_manifest_sha256': digest(RUN / 'PUBLIC-MANIFEST.json'),
        'creator_role': 'informed; no blind claim', 'external_model_calls': 0,
        'completed_paired_overhead_repetitions': 20,
        'private_key': 'private/answer-key.json', 'private_key_sha256': digest(HERE / 'answer-key.json'),
        'private_source_manifest': 'private/source-manifest.json',
        'private_truth_manifest': 'private/truth-manifest.json',
        'restriction': 'Do not inspect private/ or instrument outputs before freezing all three independent reviewer stages.',
        'manufacturing_status': 'completed; intended technical-stop tracebacks are retained privately',
        'deviations': [],
    })
    write_json(attempt / 'COMPLETE.json', {'case_count': 12, 'overhead_pairs': 20,
                                          'public_manifest_sha256': digest(RUN / 'PUBLIC-MANIFEST.json')})
    print(json.dumps({'completed': True, 'case_count': 12, 'overhead_pairs': 20,
                      'handoff': str((RUN / 'HANDOFF.json').relative_to(ROOT)),
                      'public_manifest_sha256': digest(RUN / 'PUBLIC-MANIFEST.json')}))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        failure_path = HERE / 'manufacturing-failure-001.log'
        with failure_path.open('x') as out:
            out.write(traceback.format_exc())
        raise
