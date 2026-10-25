"""D-079 suffix: retain the old book, remove only the global free-rate cap.

The old origin and coverage suffix are restored by their unchanged adapters.
Only this new suffix uses the amended rule. The caller still owns the study
lock, immutable activation, native accounting and every per-dispatch gate.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import time

from .failure_policy import strict_json
from .openrouter import encoded, save_new
from .technical_prefix import PrefixTechnicalAdapter
from .technical_retry import TechnicalAdapter, checked, checksum, need


def restore_prefix(prefix, *, clock=time.time, sleep=time.sleep):
    """Read either original book type under its original, capped contract."""
    need(set(prefix) == {'origin', 'last_settlement', 'snapshot'},
         'prefix descriptor differs')
    origin = strict_json(checked(prefix['origin']))
    path = Path(prefix['origin']['path'])
    need(path.name == 'origin.json', 'foreign prefix origin')
    if origin['schema'] == 'technical-origin/v1':
        old = TechnicalAdapter(path.parent, None, binding=origin['binding'],
            cap=origin['cap_usd'], max_calls=origin['max_calls'], seeds=origin['seeds'],
            pending_seed=origin['pending_seed'], base_generations=origin['base_generations'],
            initial_rate_retries=origin['initial_rate_retries'], restore=True,
            audit_only=True, clock=clock, sleep=sleep)
    else:
        need(origin['schema'] == 'technical-prefix-origin/v1',
             'unsupported predecessor book')
        old = PrefixTechnicalAdapter(path.parent, None, binding=origin['binding'],
            prefix=origin['prefix'], replays=origin['replays'],
            first_request=origin['first_request'], restore=True, audit_only=True,
            clock=clock, sleep=sleep)
    need(old.calls > 0 and not old.poisoned and old.snapshot() == prefix['snapshot'],
         'prefix snapshot differs')
    need(Path(prefix['last_settlement']['path']) == old._path(old.calls, 'settled')
         and strict_json(checked(prefix['last_settlement'])) == old.records[-1],
         'prefix tip differs')
    return old


def _identity(value):
    need(isinstance(value, dict)
         and set(value) == {'logical_id', 'request_sha256', 'output_limit'}
         and isinstance(value['logical_id'], str) and bool(value['logical_id'])
         and value['output_limit'] in (128, 1024)
         and isinstance(value['request_sha256'], str)
         and len(value['request_sha256']) == 64
         and all(c in '0123456789abcdef' for c in value['request_sha256']),
         'request identity differs')


class RateStopPrefixAdapter(PrefixTechnicalAdapter):
    """Exactly one bound rate-stop successor; no general recovery permission."""

    def __init__(self, folder, transport, *, binding, prefix, replays, first_request,
                 restore=False, audit_only=False, guard=None,
                 clock=time.time, sleep=time.sleep):
        old = restore_prefix(prefix, clock=clock, sleep=sleep)
        target = Path(folder)
        old_folders = {old.folder}
        if isinstance(old, PrefixTechnicalAdapter):
            old_folders.add(old.prefix_folder)
        need(target.is_absolute() and target == target.resolve() and not target.is_symlink()
             and all(target != p and p not in target.parents and target not in p.parents
                     for p in old_folders), 'suffix must be separate and canonical')
        old_bindings = {old.origin['binding']}
        if isinstance(old, PrefixTechnicalAdapter):
            old_bindings.add(strict_json(checked(old.origin['prefix']['origin']))['binding'])
        need(isinstance(binding, str) and len(binding) == 64
             and all(c in '0123456789abcdef' for c in binding) and binding not in old_bindings,
             'new explicit binding required')
        need(isinstance(replays, list), 'ordered replays required')
        for item in replays:
            _identity(item)
            state = old.states.get(item['logical_id'])
            need(state is not None and state['outcome'] in ('completed', 'model_failed')
                 and sha256(state['body']).hexdigest() == item['request_sha256']
                 and state['limit'] == item['output_limit'], 'replay does not match terminal prefix')
        need(len({v['logical_id'] for v in replays}) == len(replays), 'duplicate replay')
        _identity(first_request)
        first = old.states.get(first_request['logical_id'])
        tip = old.records[-1]
        need(old.rate_retries == 20 and first is not None
             and first['outcome'] == tip['outcome'] == 'rate_limited'
             and tip['dispatch']['logical_id'] == first_request['logical_id']
             and first['technical'] == first['rate'] == 0
             and sha256(first['body']).hexdigest() == first_request['request_sha256']
             and first['limit'] == first_request['output_limit'],
             'first suffix request must be the bound initial free-rate stop')
        need({k for k, v in old.states.items()
              if v['outcome'] not in ('completed', 'model_failed')} == {first_request['logical_id']},
             'another unresolved logical request exists')
        # The predecessor is reconstructed privately, never accepted as a
        # caller-mutated seed. Preserve its path resolver for both old layers.
        self.__dict__.update(old.__dict__)
        self.predecessor = old
        self.folder, self.transport, self.binding = target, transport, binding
        self.guard, self.audit_only = guard, audit_only
        self.prefix_folder, self.prefix_calls = old.folder, old.calls
        self.allowed_replays, self.first_request = deepcopy(replays), deepcopy(first_request)
        self.replays = []
        self.origin = dict(schema='technical-rate-stop-prefix-origin/v1', binding=binding,
            prefix=deepcopy(prefix), replays=deepcopy(replays), first_request=deepcopy(first_request),
            retry_rule='D079-remove-only-global-free-rate-cap')
        if restore:
            need(strict_json((target/'origin.json').read_bytes()) == self.origin, 'suffix origin changed')
            self._restore_suffix()
        else:
            need(not audit_only, 'audit cannot create a suffix')
            target.mkdir(parents=True, exist_ok=True)
            need(not any(target.iterdir()), 'new suffix must be empty')
            save_new(target/'origin.json', encoded(self.origin))

    def _path(self, number, kind):
        if number <= self.prefix_calls:
            return self.predecessor._path(number, kind)
        return self.folder/f'{number:06d}-{kind}.json'

    def _binding(self, logical, body, limit, stamp):
        if self.calls == self.prefix_calls:
            need(dict(logical_id=logical, request_sha256=sha256(body).hexdigest(), output_limit=limit)
                 == self.first_request, 'first rate retry changed')
        prior = self.states.get(logical)
        need(prior is None or prior['body'] == body and prior['limit'] == limit, 'logical request changed')
        need(prior is None or prior['outcome'] in ('technical', 'rate_limited'),
             'successful answer cannot be resent')
        kind = prior['outcome'] if prior else 'initial'
        tech = (prior['technical'] if prior else 0) + int(kind == 'technical')
        rate = (prior['rate'] if prior else 0) + int(kind == 'rate_limited')
        gt = self.technical_retries + int(kind == 'technical')
        gr = self.rate_retries + int(kind == 'rate_limited')
        # Sole policy change from TechnicalAdapter._binding: no gr <= 20.
        need(tech <= 2 and rate <= 2 and tech+rate <= 2 and gt <= 20,
             'persistent retry bound exhausted')
        if self.calls == self.prefix_calls:
            need(kind == 'rate_limited' and rate == 1 and tech == 0 and gr == 21,
                 'first attempt is not the bound rate retry')
        delay = 0 if prior is None else 30 if tech+rate == 1 else 120
        deadline = prior['received'] + max(delay, prior.get('retry_after', 0)) if prior else None
        return dict(schema='technical-dispatch/v1', binding=self.binding, number=self.calls+1,
            physical_id=f'technical-{self.calls+1:06d}', logical_id=logical,
            request_sha256=sha256(body).hexdigest(), output_limit=limit, retry_kind=kind,
            technical_retry=tech, rate_retry=rate, global_technical_retry=gt, global_rate_retry=gr,
            not_before=deadline, dispatched_at=stamp, reservation_usd=str(self.RESERVE),
            known_before_usd=str(self.cost), held_before_usd=str(self.held),
            previous_record=checksum(self.records[-1]))
