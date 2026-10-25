"""D-055 physical dispatch evidence, finite zero-cost 429 handling and replay.

The caller must hold the study's exclusive lock and verify the source/base guard.
A settled transport envelope is not necessarily a successful model response:
rate_limited is recorded separately and never returned to the executor.
"""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import time

from .contracts import Response, Usage
from .failure_policy import F01, ModelFailure, decode_outcome, strict_json
from .openrouter import RESERVE, decode_billing, encoded, payload, save_new
from .phase_budget import PhaseBudget


class RateStop(RuntimeError):
    pass


def classify(status, raw, output_limit):
    """Accept only the exact authorized zero-token, zero-cost error envelope."""
    if type(output_limit) is not int or output_limit not in (128, 1024):
        raise RateStop('output limit outside D-055')
    data = strict_json(raw)
    usage, generation = decode_billing(raw)
    if status != 200:
        raise RateStop('HTTP status outside D-055')
    choices = data.get('choices')
    if (isinstance(choices, list) and len(choices) == 1
            and choices[0].get('finish_reason') == 'error'):
        choice = choices[0]
        error = choice.get('error', {})
        if (not data.get('error') and type(error.get('code')) is int and error['code'] == 429
                and error.get('metadata', {}).get('error_type') == 'rate_limit_exceeded'
                and usage.cost_usd == 0 and usage.input_tokens == usage.output_tokens == 0
                and data['usage'].get('completion_tokens_details', {}).get('reasoning_tokens', 0) == 0
                and choice.get('message', {}).get('role') == 'assistant'
                and isinstance(choice['message'].get('content'), str)
                and not choice['message'].get('tool_calls') and not choice['message'].get('refusal')):
            return 'rate_limited', None, usage, generation
        raise RateStop('error envelope outside D-055')
    response = decode_outcome(raw, output_limit, F01)
    return ('model_failed' if isinstance(response, ModelFailure) else 'completed'), response, usage, generation


def utc_seconds():
    return datetime.now(timezone.utc).timestamp()


class RateAdapter:
    """One persistent physical ledger, with immutable evidence and logical replay.

    seeds bind already paid/settled base responses to their original logical IDs.
    They must be verified against the frozen base by the owning study. Each seed
    has logical_id, request/response/received paths, hashes, output_limit, origin.
    New generations are checked against *all* base generations, including seeds.
    """
    def __init__(self, folder, transport, *, budget_args, base_generations=(), seeds=(),
                 restore=False, clock=utc_seconds, sleep=time.sleep, audit_only=False,
                 initial_retries=0, exception_seed=None):
        if type(initial_retries) is not int or not 0 <= initial_retries <= 20:
            raise RateStop('invalid inherited retry counter')
        self.folder, self.transport = Path(folder), transport
        self.clock, self.sleep, self.audit_only = clock, sleep, audit_only
        self.states, self.generations, self.retries = {}, set(base_generations), initial_retries
        self.origin_contract = (dict(author_decision='D-056', initial_retries=initial_retries,
                               exception_seed=exception_seed) if initial_retries or exception_seed else None)
        self.exception_pending = exception_seed is not None
        self.exception_id = exception_seed['logical_id'] if exception_seed else None
        self.poisoned = False
        self.records = []
        self.replays = []
        self._seed_files = {}
        self._seed_generations = set()
        for seed in seeds:
            self._seed(seed)
        if exception_seed:
            self._exception_seed(exception_seed)
        origin_path = self.folder/'dispatch-origin.json'
        if self.origin_contract is not None:
            if restore:
                if strict_json(origin_path.read_bytes()) != self.origin_contract:
                    raise RateStop('inherited counter or exception changed')
            else:
                save_new(origin_path, encoded(self.origin_contract))
        self.budget = (PhaseBudget.read_completed if restore else PhaseBudget)(
            self.folder/'budget.jsonl', **budget_args)
        if restore:
            self._restore()
        elif set(p.name for p in self.folder.iterdir()) != self._base_files():
            raise RateStop('new provider directory not empty')

    def _base_files(self):
        return {'budget.jsonl'} | ({'dispatch-origin.json'} if self.origin_contract else set())

    def _exception_seed(self, seed):
        """An explicit D-056 input, never a rule classifying new 503 responses."""
        if (seed.get('author_decision') != 'D-056' or seed['logical_id'] in self.states
                or seed.get('held_reserve_usd') != '0.14' or seed.get('output_limit') != 1024):
            raise RateStop('invalid one-time exception binding')
        values = {}
        for kind in ('request', 'response', 'received'):
            raw = Path(seed[kind]['path']).read_bytes()
            if sha256(raw).hexdigest() != seed[kind]['sha256']:
                raise RateStop('exception evidence changed')
            values[kind] = raw
        receipt, data = strict_json(values['received']), strict_json(values['response'])
        if (receipt['http_status'] != 503 or receipt['response_sha256'] != seed['response']['sha256']
                or 'usage' in data or 'id' in data or data['error']['code'] != 503
                or data['error']['metadata']['provider_name'] != 'Google'
                or data['error']['metadata'].get('is_byok') is not False):
            raise RateStop('not the bound unpriced provider 503')
        upstream = strict_json(data['error']['metadata']['raw'])['error']
        if upstream != dict(code=503, message='Authentication backend unavailable.', status='UNAVAILABLE'):
            raise RateStop('different provider error')
        self.states[seed['logical_id']] = dict(body=values['request'], output_limit=1024,
            outcome='authorized_unpriced', response=None, usage=None, generation=None,
            retry=0, received=seed['received_at'], origin=seed['origin'])

    def _retry_increment(self, prior):
        return int(prior is not None and prior['outcome'] == 'rate_limited')

    def _annotate(self, binding, prior):
        if self.origin_contract:
            binding.update(schema='D-056/dispatch-v1', retry_kind=(
                'authorized_503' if prior and prior['outcome']=='authorized_unpriced'
                else '429' if prior else 'initial'))
        return binding

    def _seed(self, seed):
        if seed['logical_id'] in self.states:
            raise RateStop('duplicate seed logical ID')
        values = {}
        for kind in ('request', 'response', 'received'):
            path = Path(seed[kind]['path'])
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != seed[kind]['sha256']:
                raise RateStop('seed evidence changed')
            self._seed_files[str(path)] = seed[kind]['sha256']
            values[kind] = raw
        received = strict_json(values['received'])
        outcome, response, usage, generation = classify(received['http_status'], values['response'], seed['output_limit'])
        if (generation not in self.generations or generation in self._seed_generations
                or received['response_sha256'] != seed['response']['sha256']):
            raise RateStop('seed generation or received evidence differs')
        self._seed_generations.add(generation)
        # Old provider receipts have no timestamp. The base contract supplies
        # the later, preserved stop-report time as a conservative wait anchor.
        stamp = seed['received_at']
        self.states[seed['logical_id']] = dict(body=values['request'], output_limit=seed['output_limit'],
            outcome=outcome, response=response, usage=usage.to_dict(), generation=generation,
            retry=0, received=stamp, origin=seed['origin'])

    def _read(self, number, kind):
        return (self.folder/f'{number:05d}-{kind}.json').read_bytes()

    def _restore(self):
        expected = self._base_files()
        for number, (physical_id, billed) in enumerate(self.budget.settlements, 1):
            expected.update(f'{number:05d}-{kind}.json' for kind in
                            ('request', 'binding', 'response', 'received', 'outcome'))
            body = self._read(number, 'request')
            binding = strict_json(self._read(number, 'binding'))
            raw = self._read(number, 'response')
            received = strict_json(self._read(number, 'received'))
            recorded = strict_json(self._read(number, 'outcome'))
            logical = binding['logical_id']
            if self.exception_pending and logical != self.exception_id:
                raise RateStop('first dispatch must be the authorized exception')
            prior = self.states.get(logical)
            retry = 0 if prior is None else prior['retry'] + 1
            if prior and (prior['outcome'] not in ('rate_limited', 'authorized_unpriced') or prior['body'] != body
                          or prior['output_limit'] != binding['output_limit']):
                raise RateStop('re-dispatched answer or changed retry request')
            global_retry = self.retries + self._retry_increment(prior)
            deadline = None if retry == 0 else prior['received'] + (30 if retry == 1 else 120)
            expected_binding = dict(schema='D-055/dispatch-v1', physical_id=f'dispatch-{number:05d}',
                logical_id=logical, request_sha256=sha256(body).hexdigest(),
                output_limit=binding['output_limit'], retry=retry, global_retry=global_retry,
                not_before=deadline, dispatched_at=binding['dispatched_at'])
            self._annotate(expected_binding, prior)
            if (binding != expected_binding or physical_id != binding['physical_id']
                    or retry > 2 or global_retry > 20
                    or (deadline is not None and binding['dispatched_at'] < deadline)
                    or type(binding['output_limit']) is not int or binding['output_limit'] not in (128, 1024)
                    or received['response_sha256'] != sha256(raw).hexdigest()
                    or received['received_at'] < binding['dispatched_at']):
                raise RateStop('dispatch, limits or wait evidence differs')
            outcome, response, usage, generation = classify(received['http_status'], raw, binding['output_limit'])
            if (generation in self.generations or usage.to_dict() != billed
                    or recorded != dict(outcome=outcome, generation_id=generation, usage=usage.to_dict())):
                raise RateStop('duplicate generation or altered billing/classification')
            self._accept(binding, body, received, outcome, response, usage, generation)
        if set(p.name for p in self.folder.iterdir()) != expected:
            raise RateStop('orphan or missing dispatch evidence; no automatic retry')

    def _accept(self, binding, body, received, outcome, response, usage, generation):
        if binding['logical_id'] == self.exception_id:
            self.exception_pending = False
        self.generations.add(generation)
        self.retries = binding['global_retry']
        state = dict(body=body, output_limit=binding['output_limit'], outcome=outcome,
            response=response, usage=usage.to_dict(), generation=generation,
            retry=binding['retry'], received=received['received_at'], origin=binding['physical_id'])
        self.states[binding['logical_id']] = state
        self.records.append(dict(binding=binding, received=received, outcome=outcome,
                                 usage=usage.to_dict(), generation_id=generation))

    def __call__(self, request):
        if self.poisoned or self.budget.poisoned:
            raise RateStop('adapter stopped')
        body = encoded(payload(request, producer_limit=1024))
        while True:
            prior = self.states.get(request.attempt_id)
            if prior and (prior['body'] != body or prior['output_limit'] != request.max_output_tokens):
                raise RateStop('logical request changed')
            if prior and prior['outcome'] not in ('rate_limited', 'authorized_unpriced'):
                self.replays.append(dict(logical_id=request.attempt_id, origin=prior['origin'],
                    generation_id=prior['generation'], request_sha256=sha256(body).hexdigest()))
                return prior['response']
            if self.audit_only:
                raise RateStop('audit cannot dispatch')
            if self.exception_pending and request.attempt_id != self.exception_id:
                raise RateStop('first dispatch must be the authorized exception')
            retry = 0 if prior is None else prior['retry'] + 1
            if retry > 2 or self.retries + self._retry_increment(prior) > 20:
                raise RateStop('D-055 retry bound exhausted')
            deadline = None if not retry else prior['received'] + (30 if retry == 1 else 120)
            while deadline is not None and self.clock() < deadline:
                self.sleep(min(30, deadline-self.clock()))
            # Poison before filesystem/network operations; only clear after full settlement.
            self.poisoned = True
            number = self.budget.calls + 1
            physical = f'dispatch-{number:05d}'
            binding = dict(schema='D-055/dispatch-v1', physical_id=physical,
                logical_id=request.attempt_id, request_sha256=sha256(body).hexdigest(),
                output_limit=request.max_output_tokens, retry=retry,
                global_retry=self.retries + self._retry_increment(prior), not_before=deadline,
                dispatched_at=self.clock())
            self._annotate(binding, prior)
            save_new(self.folder/f'{number:05d}-request.json', body)
            save_new(self.folder/f'{number:05d}-binding.json', encoded(binding))
            self.budget.start(physical)
            usage = Usage()
            try:
                status, raw = self.transport('chat/completions', body)
                save_new(self.folder/f'{number:05d}-response.json', raw)
                received = dict(http_status=status, received_at=self.clock(), response_sha256=sha256(raw).hexdigest())
                save_new(self.folder/f'{number:05d}-received.json', encoded(received))
                # Retain known billing for other failures; duplicated billing is ambiguous.
                decoded, generation = decode_billing(raw)
                if generation in self.generations:
                    raise RateStop('duplicate generation')
                usage = decoded
                outcome, response, usage, generation = classify(status, raw, request.max_output_tokens)
                save_new(self.folder/f'{number:05d}-outcome.json', encoded(dict(
                    outcome=outcome, generation_id=generation, usage=usage.to_dict())))
            except Exception:
                self.budget.settle(usage, failed=True)
                raise
            self.budget.settle(usage)
            self._accept(binding, body, received, outcome, response, usage, generation)
            self.poisoned = False
            if response is not None:
                return response
