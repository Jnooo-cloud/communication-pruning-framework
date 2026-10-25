"""Separate read-only boundary audit. Does not call the writer or AutoGen."""

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from .contracts import Usage


def audit(path):
    rows = []
    for line in Path(path).read_bytes().splitlines():
        def pairs(items):
            result = {}
            for k, v in items:
                if k in result: raise ValueError('duplicate JSON key')
                result[k] = v
            return result
        rows.append(json.loads(line, object_pairs_hook=pairs))
    if not rows or rows[0].get('kind') != 'header' or rows[0].get('schema') != 'foreign-model-boundary/v1':
        raise ValueError('missing boundary header')
    encode = lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    stopped = False
    previous = '0' * 64; pending = {}; ended = set(); known = Decimal(0); sources = {}; calls = []; terminal = []
    for i, original in enumerate(rows):
        row = dict(original); digest = row.pop('sha256')
        if row.get('sequence') != i or row.get('previous_sha256') != previous or sha256(encode(row)).hexdigest() != digest:
            raise ValueError('event chain mismatch')
        previous = digest; kind = row['kind']
        if i == 0: continue
        attempt = row.get('attempt_id')
        if kind == 'started':
            if stopped or not attempt or attempt in pending or attempt in ended or pending:
                raise ValueError('duplicate or concurrent start')
            if row.get('run_id') != rows[0]['run_id'] or not row.get('task_id') or not row.get('actor'):
                raise ValueError('missing or mismatched identity')
            if sha256(encode(row['request'])).hexdigest() != row['request_sha256']:
                raise ValueError('request hash mismatch')
            pending[attempt] = row; calls.append(row)
        elif kind in ('completed', 'failed'):
            if attempt not in pending or attempt in ended: raise ValueError('unmatched terminal event')
            u = dict(row['usage']); raw_cost = u['cost_usd']
            if raw_cost is not None:
                if not isinstance(raw_cost, str): raise ValueError('cost must use decimal string')
                u['cost_usd'] = Decimal(raw_cost)
            usage = Usage(**u)
            if kind == 'completed':
                if sha256(encode(row['response'])).hexdigest() != row['response_sha256']:
                    raise ValueError('response hash mismatch')
                if not isinstance(row['response'].get('content'), str): raise ValueError('missing text response')
            if usage.cost_usd is not None:
                known += usage.cost_usd; sources[usage.cost_source] = sources.get(usage.cost_source, Decimal(0)) + usage.cost_usd
            terminal.append(row); del pending[attempt]; ended.add(attempt)
            if kind == 'failed': stopped = True
        else:
            raise ValueError('unsupported event')
    unknown = sum(r['usage']['cost_usd'] is None for r in terminal) + len(pending)
    return dict(attempts=len(calls), completed=sum(r['kind'] == 'completed' for r in terminal),
                failed=sum(r['kind'] == 'failed' for r in terminal), unresolved=len(pending),
                unknown_cost_attempts=unknown, known_cost_subtotal_usd=str(known),
                total_cost_usd=None if unknown else str(known),
                cost_by_source={k: str(v) for k, v in sources.items()},
                calls=calls, terminal=terminal, last_sha256=previous,
                boundary='model_client_only', synchronous_bank_conformance='not_assessed')
