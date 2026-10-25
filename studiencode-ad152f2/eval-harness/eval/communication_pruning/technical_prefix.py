"""A separately bound suffix of an immutable, fully reconstructed physical book.

The original adapter owns response classification, retry policy and billing.
This adapter adds no retry right: its first new request was never dispatched.
The study caller must hold the original lock and enforce the study gates.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import time

from .contracts import Usage
from .failure_policy import strict_json
from .openrouter import encoded, payload, save_new
from .technical_retry import TechnicalAdapter, checked, need, response_outcome


def request_identity(request):
    return dict(logical_id=request.attempt_id,
                request_sha256=sha256(encoded(payload(request, producer_limit=1024))).hexdigest(),
                output_limit=request.max_output_tokens)


class PrefixTechnicalAdapter(TechnicalAdapter):
    """Inherit every original physical attempt; write only after its final number."""

    def __init__(self, folder, transport, *, binding, prefix, replays, first_request,
                 restore=False, audit_only=False, guard=None,
                 clock=time.time, sleep=time.sleep):
        need(set(prefix) == {'origin', 'last_settlement', 'snapshot'}, 'prefix descriptor differs')
        origin = strict_json(checked(prefix['origin']))
        prefix_folder = Path(prefix['origin']['path']).parent
        need(Path(prefix['origin']['path']).name == 'origin.json', 'foreign prefix origin')
        need(origin['schema'] == 'technical-origin/v1', 'unsupported predecessor book')
        old = TechnicalAdapter(prefix_folder, None, binding=origin['binding'],
            cap=origin['cap_usd'], max_calls=origin['max_calls'], seeds=origin['seeds'],
            pending_seed=origin['pending_seed'], base_generations=origin['base_generations'],
            initial_rate_retries=origin['initial_rate_retries'], restore=True, audit_only=True,
            clock=clock, sleep=sleep)
        need(old.calls > 0 and old.snapshot() == prefix['snapshot'], 'prefix snapshot differs')
        need(Path(prefix['last_settlement']['path']) == old._path(old.calls, 'settled')
             and strict_json(checked(prefix['last_settlement'])) == old.records[-1],
             'prefix tip differs')
        target = Path(folder)
        need(target.is_absolute() and target == target.resolve() and not target.is_symlink()
             and target != prefix_folder and prefix_folder not in target.parents
             and target not in prefix_folder.parents, 'suffix must be separate and canonical')
        need(isinstance(binding, str) and len(binding) == 64
             and all(c in '0123456789abcdef' for c in binding) and binding != origin['binding'],
             'new explicit binding required')
        need(isinstance(replays, list) and len(replays) == 3
             and len({v['logical_id'] for v in replays}) == 3, 'exact three ordered replays required')
        for item in replays:
            need(set(item) == {'logical_id', 'request_sha256', 'output_limit'}, 'replay descriptor differs')
            state = old.states.get(item['logical_id'])
            need(state is not None and state['outcome'] in ('completed', 'model_failed')
                 and sha256(state['body']).hexdigest() == item['request_sha256']
                 and state['limit'] == item['output_limit'], 'replay does not match terminal prefix')
        need(set(first_request) == {'logical_id', 'request_sha256', 'output_limit'}
             and first_request['logical_id'] not in old.states
             and first_request['output_limit'] in (128, 1024)
             and len(first_request['request_sha256']) == 64,
             'first suffix request must be physically unsent')
        # The reconstructed predecessor is private to this instance, never a
        # caller-supplied mutable seed or a reset of cumulative counters.
        self.__dict__.update(old.__dict__)
        self.folder, self.transport, self.binding = target, transport, binding
        self.guard, self.audit_only = guard, audit_only
        self.prefix_folder, self.prefix_calls = prefix_folder, old.calls
        self.allowed_replays, self.first_request = deepcopy(replays), deepcopy(first_request)
        self.origin = dict(schema='technical-prefix-origin/v1', binding=binding,
                           prefix=deepcopy(prefix), replays=deepcopy(replays),
                           first_request=deepcopy(first_request))
        if restore:
            need(strict_json((target/'origin.json').read_bytes()) == self.origin, 'suffix origin changed')
            self._restore_suffix()
        else:
            need(not audit_only, 'audit cannot create a suffix')
            target.mkdir(parents=True, exist_ok=True)
            need(not any(target.iterdir()), 'new suffix must be empty')
            save_new(target/'origin.json', encoded(self.origin))

    def _path(self, number, kind):
        folder = self.prefix_folder if number <= self.prefix_calls else self.folder
        return folder/f'{number:06d}-{kind}.json'

    def _binding(self, logical, body, limit, stamp):
        if self.calls == self.prefix_calls:
            need(dict(logical_id=logical, request_sha256=sha256(body).hexdigest(), output_limit=limit)
                 == self.first_request, 'first unsent request changed')
        return super()._binding(logical, body, limit, stamp)

    def __call__(self, request):
        identity = request_identity(request)
        prior = self.states.get(request.attempt_id)
        if prior and prior['outcome'] in ('completed', 'model_failed'):
            need(self.calls == self.prefix_calls and len(self.replays) < len(self.allowed_replays)
                 and identity == self.allowed_replays[len(self.replays)], 'unapproved terminal replay')
        elif self.calls == self.prefix_calls:
            need(len(self.replays) == len(self.allowed_replays), 'partial block replays incomplete')
        return super().__call__(request)

    def _restore_suffix(self):
        """Same original settlement checks, with the inherited number and chain."""
        paths = sorted(self.folder.glob('*-settled.json'))
        expected = {'origin.json'}
        for number, path in enumerate(paths, self.prefix_calls+1):
            need(path == self._path(number, 'settled'), 'suffix physical attempt gap')
            record = strict_json(path.read_bytes()); d, r = record['dispatch'], record['receipt']
            body = self._path(number, 'request').read_bytes()
            need(strict_json(self._path(number, 'binding').read_bytes()) == d
                 and self._binding(d['logical_id'], body, d['output_limit'], d['dispatched_at']) == d,
                 'suffix dispatch/counter chain changed')
            need(d['not_before'] is None or d['dispatched_at'] >= d['not_before'], 'early persisted retry')
            need(self.cost+self.held+self.RESERVE <= self.cap and self.calls < self.max_calls,
                 'invalid cumulative historical coverage')
            need(r['received_at'] >= d['dispatched_at'], 'nonmonotone receipt')
            expected.update(self._path(number, k).name for k in ('request', 'binding', 'settled'))
            if r.get('http_status') is None:
                need(r.get('exception_classes') and r.get('response_sha256') is None
                     and record['outcome'] == 'technical', 'missing transport evidence')
                outcome, response, usage, generation = 'technical', None, Usage(), None
            else:
                raw = self._path(number, 'response').read_bytes()
                expected.add(self._path(number, 'response').name)
                need(sha256(raw).hexdigest() == r['response_sha256'], 'response changed')
                outcome, response, usage, generation = response_outcome(r['http_status'], raw, d['output_limit'])
            need(self._accept(d, r, outcome, response, usage, generation) == record,
                 'suffix settlement differs from original')
        need({p.name for p in self.folder.iterdir()} == expected, 'unresolved suffix attempt or orphan')
