"""Bounded technical replacement, authorized 2026-09-26; no scientific retries.

The caller owns the original study lock and supplies the immutable activation,
budget remainder, old physical-call bound, seeds and a per-dispatch guard.
Every physical attempt is write-once; unknown charges retain their reservation.
"""
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import math
import time

from .contracts import Usage
from .failure_policy import strict_json
from .openrouter import encoded, payload, decode_billing, save_new
from .rate_limit import classify


class TechnicalStop(RuntimeError):
    pass


def need(value, message):
    if not value:
        raise TechnicalStop(message)


def checksum(value):
    return sha256(encoded(value)).hexdigest()


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def checked(item):
    path = Path(item['path'])
    need(path.is_absolute() and path == path.resolve() and not path.is_symlink(), 'noncanonical evidence')
    raw = path.read_bytes()
    need(sha256(raw).hexdigest() == item['sha256'], 'evidence changed')
    return raw


def transport_exception(error):
    """Inspect types only; never persist exception strings with potential keys."""
    chain, seen = [], set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        chain.append(type(error).__module__ + '.' + type(error).__name__)
        if isinstance(error, (TimeoutError, ConnectionError)):
            return chain
        error = error.__cause__ or error.__context__
    return None


def response_outcome(status, raw, limit):
    """F01 model failures remain terminal; only explicit service errors retry."""
    if status == 200:
        return classify(status, raw, limit)
    need(type(status) is int and status in (408, 429, 500, 502, 503, 504), 'nontransient HTTP error')
    try:
        data = strict_json(raw)
    except (ValueError, UnicodeError):
        data = None
    if isinstance(data, dict):
        need(not data.get('choices'), 'HTTP service status with model choices is ambiguous')
        if 'usage' in data or 'id' in data:
            usage, generation = decode_billing(raw)
        else:
            usage, generation = Usage(), None
    else:
        usage, generation = Usage(), None
    return 'technical', None, usage, generation


class TechnicalAdapter:
    RESERVE = Decimal('0.14')

    def __init__(self, folder, transport, *, binding, cap, max_calls,
                 seeds=(), pending_seed=None, base_generations=(), initial_rate_retries=0,
                 restore=False, audit_only=False, guard=None, clock=time.time, sleep=time.sleep):
        self.folder, self.transport = Path(folder), transport
        self.binding, self.cap, self.max_calls = binding, Decimal(cap), max_calls
        need(self.cap.is_finite() and self.cap > 0 and type(max_calls) is int and max_calls > 0,
             'invalid remaining budget/call bound')
        need(type(initial_rate_retries) is int and 0 <= initial_rate_retries <= 20, 'invalid inherited429 count')
        self.clock, self.sleep, self.guard, self.audit_only = clock, sleep, guard, audit_only
        self.states, self.records, self.replays = {}, [], []
        self.generations = set(base_generations)
        self.cost, self.held = Decimal(0), Decimal(0)
        self.calls, self.technical_retries, self.rate_retries = 0, 0, initial_rate_retries
        self.poisoned = False
        self.initial_pending = pending_seed['logical_id'] if pending_seed else None
        self.origin = dict(schema='technical-origin/v1', binding=binding, cap_usd=str(self.cap),
            max_calls=max_calls, reserve_usd=str(self.RESERVE), initial_rate_retries=initial_rate_retries,
            seeds=list(seeds), pending_seed=pending_seed, base_generations=sorted(self.generations))
        for seed in seeds:
            body, raw, receipt = checked(seed['request']), checked(seed['response']), strict_json(checked(seed['received']))
            outcome, response, usage, generation = classify(receipt['http_status'], raw, seed['output_limit'])
            need(outcome in ('completed', 'model_failed') and seed['logical_id'] not in self.states
                 and generation in self.generations and receipt['response_sha256'] == seed['response']['sha256'],
                 'invalid successful replay seed')
            self.states[seed['logical_id']] = dict(body=body, limit=seed['output_limit'], outcome=outcome,
                response=response, costs=[], usages=[], received=seed['received_at'], technical=0, rate=0,
                generation=generation, origin=seed['origin'])
        if pending_seed:
            body = checked(pending_seed['request'])
            need(pending_seed['logical_id'] not in self.states and pending_seed['held_reserve_usd'] == '0.14'
                 and pending_seed['outcome'] == 'technical' and pending_seed['output_limit'] in (128, 1024),
                 'invalid inherited unknown attempt')
            self.states[pending_seed['logical_id']] = dict(body=body, limit=pending_seed['output_limit'],
                outcome='technical', response=None, costs=[], usages=[], received=pending_seed['observed_epoch'],
                technical=0, rate=0, generation=None, origin=pending_seed['origin'])
        if restore:
            need(strict_json((self.folder/'origin.json').read_bytes()) == self.origin, 'adapter origin changed')
            self._restore()
        else:
            self.folder.mkdir(parents=True, exist_ok=True)
            need(not any(self.folder.iterdir()), 'new dispatch directory must be empty')
            save_new(self.folder/'origin.json', encoded(self.origin))

    def snapshot(self):
        return dict(calls=self.calls, known_cost_usd=str(self.cost), held_reservation_usd=str(self.held),
            total_cost_usd=None if self.held else str(self.cost), technical_retries=self.technical_retries,
            free429_retries=self.rate_retries, poisoned=self.poisoned)

    def _path(self, number, kind):
        return self.folder/f'{number:06d}-{kind}.json'

    def _binding(self, logical, body, limit, stamp):
        prior = self.states.get(logical)
        need(prior is None or prior['body'] == body and prior['limit'] == limit, 'logical request changed')
        need(prior is None or prior['outcome'] in ('technical', 'rate_limited'), 'successful answer cannot be resent')
        kind = prior['outcome'] if prior else 'initial'
        tech = (prior['technical'] if prior else 0) + int(kind == 'technical')
        rate = (prior['rate'] if prior else 0) + int(kind == 'rate_limited')
        gt, gr = self.technical_retries + int(kind == 'technical'), self.rate_retries + int(kind == 'rate_limited')
        need(tech <= 2 and rate <= 2 and tech+rate <= 2 and gt <= 20 and gr <= 20, 'persistent retry bound exhausted')
        delay = 0 if prior is None else 30 if tech+rate == 1 else 120
        deadline = prior['received'] + max(delay, prior.get('retry_after', 0)) if prior else None
        return dict(schema='technical-dispatch/v1', binding=self.binding, number=self.calls+1,
            physical_id=f'technical-{self.calls+1:06d}', logical_id=logical, request_sha256=sha256(body).hexdigest(),
            output_limit=limit, retry_kind=kind, technical_retry=tech, rate_retry=rate,
            global_technical_retry=gt, global_rate_retry=gr, not_before=deadline, dispatched_at=stamp,
            reservation_usd=str(self.RESERVE),known_before_usd=str(self.cost),held_before_usd=str(self.held),
            previous_record=checksum(self.records[-1]) if self.records else checksum(self.origin))

    def _accept(self, dispatch, receipt, outcome, response, usage, generation):
        logical = dispatch['logical_id']
        prior = self.states.get(logical)
        need(generation is None or generation not in self.generations, 'duplicate provider generation')
        need(usage.cost_usd is None or usage.cost_usd <= self.RESERVE, 'physical charge exceeds reservation')
        if generation is not None:
            self.generations.add(generation)
        self.calls += 1
        self.technical_retries, self.rate_retries = dispatch['global_technical_retry'], dispatch['global_rate_retry']
        if usage.cost_usd is None:
            self.held += self.RESERVE
        else:
            self.cost += usage.cost_usd
        costs = (prior['costs'] if prior else []) + [usage.cost_usd]
        usages = (prior['usages'] if prior else []) + [usage]
        # Keep the received terminal response/usage byte-semantically native.
        # Failed physical attempts are a separate book; the study adds their
        # known charges to analysis rows, never fabricates response token counts.
        self.states[logical] = dict(body=self._path(self.calls, 'request').read_bytes(), limit=dispatch['output_limit'],
            outcome=outcome, response=response, costs=costs, usages=usages, received=receipt['received_at'],
            technical=dispatch['technical_retry'], rate=dispatch['rate_retry'], generation=generation,
            origin=dispatch['physical_id'], retry_after=receipt.get('retry_after_seconds', 0))
        record = dict(dispatch=dispatch, receipt=receipt, outcome=outcome, usage=usage.to_dict(), generation=generation)
        self.records.append(record)
        return record

    def known_failed_costs(self):
        result={}
        for record in self.records:
            if record['outcome'] in ('technical','rate_limited') and record['usage']['cost_usd'] is not None:
                logical=record['dispatch']['logical_id']
                result[logical]=result.get(logical,Decimal(0))+Decimal(record['usage']['cost_usd'])
        return result

    def _restore(self):
        paths = sorted(self.folder.glob('*-settled.json'))
        expected = {'origin.json'}
        for number, path in enumerate(paths, 1):
            need(path == self._path(number, 'settled'), 'physical attempt gap')
            record = strict_json(path.read_bytes()); d, r = record['dispatch'], record['receipt']
            body = self._path(number, 'request').read_bytes()
            need(strict_json(self._path(number, 'binding').read_bytes()) == d
                 and self._binding(d['logical_id'], body, d['output_limit'], d['dispatched_at']) == d,
                 'physical dispatch/counter chain changed')
            need(d['not_before'] is None or d['dispatched_at'] >= d['not_before'], 'early persisted retry')
            need(self.cost+self.held+self.RESERVE <= self.cap and self.calls < self.max_calls, 'invalid historical coverage')
            need(r['received_at'] >= d['dispatched_at'], 'nonmonotone receipt')
            expected.update(self._path(number,k).name for k in ('request','binding','settled'))
            if r.get('http_status') is None:
                need(r.get('exception_classes') and r.get('response_sha256') is None
                     and record['outcome'] == 'technical', 'missing exact transport error evidence')
                outcome, response, usage, generation = 'technical', None, Usage(), None
            else:
                raw = self._path(number, 'response').read_bytes()
                expected.add(self._path(number, 'response').name)
                need(sha256(raw).hexdigest() == r['response_sha256'], 'response changed')
                outcome, response, usage, generation = response_outcome(r['http_status'], raw, d['output_limit'])
            need(self._accept(d,r,outcome,response,usage,generation) == record, 'settlement differs from original')
        need({p.name for p in self.folder.iterdir()} == expected, 'unresolved physical attempt or orphan evidence')

    def __call__(self, request):
        body = encoded(payload(request, producer_limit=1024))
        logical, limit = request.attempt_id, request.max_output_tokens
        while True:
            need(not self.poisoned, 'adapter poisoned')
            prior = self.states.get(logical)
            need(prior is None or prior['body'] == body and prior['limit'] == limit, 'logical replay changed')
            if prior and prior['outcome'] in ('completed', 'model_failed'):
                self.replays.append(dict(logical_id=logical, origin=prior['origin'], request_sha256=sha256(body).hexdigest()))
                return prior['response']
            need(not self.audit_only, 'audit cannot dispatch')
            need(self.calls != 0 or self.initial_pending is None or logical == self.initial_pending, 'first replacement identity differs')
            d = self._binding(logical, body, limit, self.clock())
            while d['not_before'] is not None and self.clock() < d['not_before']:
                before = self.clock(); self.sleep(min(30,d['not_before']-before))
                need(self.clock() > before, 'retry clock did not advance')
            d = self._binding(logical, body, limit, self.clock())
            need(self.cost+self.held+self.RESERVE <= self.cap and self.calls < self.max_calls, 'remaining budget/calls exhausted')
            if self.guard:
                self.guard(d, self.snapshot())
            self.poisoned = True
            number = self.calls+1
            save_new(self._path(number,'request'),body)
            save_new(self._path(number,'binding'),encoded(d))
            try:
                result = self.transport('chat/completions',body)
            except Exception as error:
                chain = transport_exception(error)
                if chain is None:
                    raise
                receipt = dict(http_status=None, response_sha256=None, received_at=self.clock(), exception_classes=chain)
                outcome,response,usage,generation = 'technical',None,Usage(),None
            else:
                status, raw = result[:2]
                headers = result[2] if len(result) == 3 else {}
                save_new(self._path(number,'response'),raw)
                outcome,response,usage,generation = response_outcome(status,raw,limit)
                receipt = dict(http_status=status,response_sha256=sha256(raw).hexdigest(),received_at=self.clock())
                if headers:
                    value = headers.get('Retry-After',headers.get('retry-after'))
                    if value is not None:
                        try:
                            delay = float(value)
                        except (ValueError,TypeError):
                            from email.utils import parsedate_to_datetime
                            delay = parsedate_to_datetime(str(value)).timestamp()-receipt['received_at']
                        need(math.isfinite(delay), 'invalid Retry-After')
                        receipt['retry_after_seconds'] = max(0,delay)
            need(receipt['received_at'] >= d['dispatched_at'], 'receipt clock regressed')
            record = self._accept(d,receipt,outcome,response,usage,generation)
            save_new(self._path(number,'settled'),encoded(record))
            self.poisoned = False
            if response is not None:
                return self.states[logical]['response']
