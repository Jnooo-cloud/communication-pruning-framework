"""Artificial D-079 book/replay/retry tests; preserve fixtures via Z50_TEST_EVIDENCE_DIR."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import unittest

from communication_pruning.openrouter import encoded
from communication_pruning.rate_stop_prefix import RateStopPrefixAdapter, restore_prefix
from communication_pruning.technical_prefix import PrefixTechnicalAdapter, request_identity
from communication_pruning.technical_retry import TechnicalAdapter, TechnicalStop, ref
from tests.study_fixture import FakeTransport
from tests.test_rate_limit import Clock, request
from tests.test_technical_retry import trial_directory


class Transport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.actions, self.physical, self.requests = [], 0, []

    def __call__(self, endpoint, body=None):
        self.physical += 1
        self.requests.append(body)
        action = self.actions.pop(0) if self.actions else 'ok'
        if action == 'timeout':
            raise TimeoutError('artificial retained timeout')
        if action == 'crash':
            raise KeyboardInterrupt('artificial retained crash')
        status, raw = super().__call__(endpoint, body)
        value = json.loads(raw)
        if action in ('rate', 'rate-after'):
            value['usage'].update(prompt_tokens=0, completion_tokens=0, total_tokens=0, cost='0')
            value['choices'][0].update(finish_reason='error', error={
                'code': 429, 'metadata': {'error_type': 'rate_limit_exceeded'}})
            value['choices'][0]['message']['content'] = '{"answer'
        elif action == 'paid503':
            value.pop('choices')
            value['error'] = {'code': 503}
            status = 503
        elif action == 'model_failed':
            value['choices'][0]['finish_reason'] = 'length'
        elif action == '401':
            status, value = 401, {'error': {'code': 401}}
        elif action == 'bad-rate':
            value['choices'][0].update(finish_reason='error', error={
                'code': 429, 'metadata': {'error_type': 'rate_limit_exceeded'}})
        elif action == 'over':
            value['usage']['cost'] = '0.15'
        result = status, encoded(value)
        return result + ({'Retry-After': '180'},) if action == 'rate-after' else result


def descriptor(adapter):
    return dict(origin=ref(adapter.folder/'origin.json'),
                last_settlement=ref(adapter._path(adapter.calls, 'settled')),
                snapshot=adapter.snapshot())


def inventory(folder):
    return {str(p.relative_to(folder)): sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


class Fixture:
    def __init__(self, root, *, cap='20', max_calls=1000, rate=20,
                 base_action='paid503', extra_technical=0, rate_after=False):
        self.root, self.clock = Path(root).resolve(), Clock()
        self.transport = Transport()
        self.base = TechnicalAdapter(self.root/'base', self.transport, binding='a'*64,
            cap=cap, max_calls=max_calls, initial_rate_retries=rate,
            clock=self.clock, sleep=self.clock.sleep)
        for i in range(extra_technical):
            self.transport.actions.extend(['paid503', 'ok'])
            self.base(request('old-technical-'+str(i)))
        self.base_requests = [request('base-'+str(i)) for i in range(3)]
        self.transport.actions.extend([base_action, 'ok'] if base_action != 'ok' else ['ok'])
        for r in self.base_requests:
            self.base(r)
        self.coverage_first = request('coverage-first')
        self.old = PrefixTechnicalAdapter(self.root/'coverage', self.transport, binding='b'*64,
            prefix=descriptor(self.base), replays=[request_identity(r) for r in self.base_requests],
            first_request=request_identity(self.coverage_first), clock=self.clock, sleep=self.clock.sleep)
        for r in self.base_requests:
            self.old(r)
        self.old(self.coverage_first)
        # Five terminal replay identities, spread across both original layers;
        # model_failed is deliberately included and must remain terminal.
        self.failed = request('retained-model-failure')
        self.transport.actions.append('model_failed')
        self.old(self.failed)
        self.replay_requests = [self.base_requests[1], self.base_requests[2],
                                self.coverage_first, self.failed]
        self.extra = request('retained-final')
        self.old(self.extra)
        self.replay_requests.append(self.extra)
        self.first = request('open-rate-request')
        self.transport.actions.append('rate-after' if rate_after else 'rate')
        if rate == 20:
            with unittest.TestCase().assertRaises(TechnicalStop):
                self.old(self.first)
        else:
            # Below20 the old adapter is allowed to continue; isolate the
            # persisted rate result using its normal per-dispatch guard.
            def stop_retry(d, snapshot):
                if d['retry_kind'] != 'initial':
                    raise TechnicalStop('artificial stop before old allowed retry')
            self.old.guard = stop_retry
            with unittest.TestCase().assertRaises(TechnicalStop):
                self.old(self.first)
        self.prefix = descriptor(self.old)
        self.answers = [self.old.states[r.attempt_id]['response'] for r in self.replay_requests]
        self.old_inventory = {name: inventory(self.root/name) for name in ('base', 'coverage')}
        self.clock.waits = []

    def new(self, **kw):
        values = dict(binding='c'*64, prefix=self.prefix,
            replays=[request_identity(r) for r in self.replay_requests],
            first_request=request_identity(self.first), clock=self.clock, sleep=self.clock.sleep)
        values.update(kw)
        return RateStopPrefixAdapter(self.root/'successor', self.transport, **values)

    def replay(self, adapter):
        before = self.transport.physical
        for r, answer in zip(self.replay_requests, self.answers):
            assert adapter(r) == answer
        assert self.transport.physical == before


class RateStopPrefixTests(unittest.TestCase):
    def test_nested_zero_call_takeover_and_first_exact_retry(self):
        with trial_directory() as root:
            f = Fixture(root)
            before = f.transport.physical
            a = f.new()
            for key in ('states', 'records', 'generations'):
                self.assertEqual(getattr(a, key), getattr(f.old, key))
            self.assertEqual(a.snapshot(), f.old.snapshot())
            self.assertEqual(a.replays, [])
            self.assertEqual(f.transport.physical, before)
            for number in range(1, f.old.calls+1):
                self.assertEqual(a._path(number, 'settled'), f.old._path(number, 'settled'))
            f.replay(a)
            a(f.first)
            d = a.records[-1]['dispatch']
            self.assertEqual((d['number'], d['retry_kind'], d['rate_retry'], d['global_rate_retry'],
                              d['technical_retry'], d['global_technical_retry']),
                             (before+1, 'rate_limited', 1, 21, 0, 1))
            self.assertEqual(d['request_sha256'], request_identity(f.first)['request_sha256'])
            self.assertEqual(d['previous_record'], f.prefix['last_settlement']['sha256'])
            self.assertEqual(d['known_before_usd'], str(f.old.cost))
            self.assertEqual(d['held_before_usd'], '0')
            self.assertEqual(d['not_before'], f.old.records[-1]['receipt']['received_at']+30)
            self.assertEqual(f.transport.requests[-1], f.transport.requests[-2])
            self.assertEqual(sum(f.clock.waits), 30)
            self.assertEqual({n: inventory(f.root/n) for n in ('base', 'coverage')}, f.old_inventory)

    def test_restore_above20_preserves_every_cost_generation_and_retry_once(self):
        with trial_directory() as root:
            f = Fixture(root)
            a = f.new(); f.replay(a); a(f.first)
            f.transport.actions.extend(['rate', 'ok'])
            a(request('later-rate'))
            self.assertEqual(a.rate_retries, 22)
            before = f.transport.physical
            b = f.new(restore=True, audit_only=True)
            self.assertEqual(b.snapshot(), a.snapshot())
            self.assertEqual(b.states, a.states)
            self.assertEqual(b.records, a.records)
            self.assertEqual(b.generations, a.generations)
            self.assertEqual(b.known_failed_costs(), a.known_failed_costs())
            self.assertEqual(b.known_failed_costs()['base-0'], Decimal('.0000108'))
            self.assertEqual(b.replays, [])
            self.assertEqual(f.transport.physical, before)

    def test_replay_order_changed_body_missing_extra_and_terminal_resend_block(self):
        with trial_directory() as root:
            f = Fixture(root); a = f.new(); before = f.transport.physical
            for wrong in (f.first, f.replay_requests[1], replace(f.replay_requests[0], instruction='wrong')):
                with self.assertRaises(TechnicalStop): a(wrong)
            f.replay(a)
            self.assertEqual(a.states[f.failed.attempt_id]['outcome'], 'model_failed')
            for wrong in (f.replay_requests[0], request('unplanned'), replace(f.first, instruction='wrong')):
                with self.assertRaises(TechnicalStop): a(wrong)
            self.assertEqual(f.transport.physical, before)
            a(f.first)
            for wrong in (f.first, f.failed):
                with self.assertRaises(TechnicalStop): a(wrong)
            self.assertEqual(f.transport.physical, before+1)

    def test_first_request_cannot_be_unsent_or_terminal_or_changed(self):
        with trial_directory() as root:
            f = Fixture(root)
            for wrong in (request('unsent'), f.failed, replace(f.first, instruction='wrong')):
                with self.assertRaises(TechnicalStop): f.new(first_request=request_identity(wrong))
            self.assertFalse((f.root/'successor').exists())

    def test_rate_counter_below20_is_not_this_authorized_stop(self):
        with trial_directory() as root:
            f = Fixture(root, rate=19)
            with self.assertRaises(TechnicalStop): f.new()
            self.assertFalse((f.root/'successor').exists())

    def test_mixed_retries_stop_after_shared_two_and_unknowns_survive_restore(self):
        with trial_directory() as root:
            f = Fixture(root, base_action='timeout'); a = f.new(); f.replay(a)
            inherited = a.held
            f.transport.actions.extend(['timeout', 'timeout'])
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual(a.calls, f.old.calls+2)
            self.assertEqual(a.held, inherited+Decimal('.28'))
            self.assertEqual(sum(f.clock.waits), 150)
            state = a.states[f.first.attempt_id]
            self.assertEqual((state['technical'], state['rate']), (1, 1))
            self.assertEqual(state['costs'], [Decimal('0'), None, None])
            self.assertEqual(state['origin'], f'technical-{a.calls:06d}')
            b = f.new(restore=True)
            self.assertEqual(b.snapshot(), a.snapshot())
            self.assertEqual(b.states, a.states)
            with self.assertRaises(TechnicalStop): b(f.first)
            self.assertEqual(f.transport.physical, a.calls)

    def test_two_rate_retries_allowed_third_blocked(self):
        with trial_directory() as root:
            f = Fixture(root); a = f.new(); f.replay(a)
            f.transport.actions.extend(['rate', 'rate'])
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual((a.calls, a.rate_retries), (f.old.calls+2, 22))
            self.assertEqual(a.held, 0)
            self.assertEqual(sum(f.clock.waits), 150)
            self.assertEqual(f.new(restore=True).snapshot(), a.snapshot())

    def test_global_technical20_still_blocks21(self):
        with trial_directory() as root:
            f = Fixture(root, extra_technical=19); a = f.new(); f.replay(a)
            self.assertEqual(a.technical_retries, 20)
            f.transport.actions.append('timeout')
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual(a.calls, f.old.calls+1)
            self.assertEqual((a.technical_retries, a.rate_retries), (20, 21))
            self.assertEqual(f.new(restore=True).snapshot(), a.snapshot())

    def test_retry_after_uses_original_receipt_not_takeover_time(self):
        with trial_directory() as root:
            f = Fixture(root, rate_after=True)
            received = f.old.records[-1]['receipt']['received_at']
            f.clock.value += 60
            a = f.new(); f.replay(a); a(f.first)
            self.assertEqual(sum(f.clock.waits), 120)
            self.assertEqual(a.records[-1]['dispatch']['not_before'], received+180)

    def test_interrupted_wait_retains_old_floor_without_dispatch(self):
        with trial_directory() as root:
            f = Fixture(root); a = f.new(); f.replay(a); f.clock.interrupt = True
            with self.assertRaises(KeyboardInterrupt): a(f.first)
            self.assertEqual(a.calls, f.old.calls)
            f.clock.interrupt = False
            b = f.new(restore=True); f.replay(b); b(f.first)
            self.assertEqual(b.records[-1]['dispatch']['not_before'],
                             f.old.records[-1]['receipt']['received_at']+30)

    def test_inherited_physical_cap_counts_free_attempt(self):
        with trial_directory() as root:
            f = Fixture(root, max_calls=8)
            self.assertEqual(f.old.calls, 8)
            self.assertEqual(f.old.records[-1]['usage']['cost_usd'], '0')
            a = f.new(); f.replay(a)
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual(f.transport.physical, 8)

    def test_free_new_attempt_consumes_last_physical_slot(self):
        with trial_directory() as root:
            f = Fixture(root, max_calls=9); a = f.new(); f.replay(a)
            f.transport.actions.append('rate')
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual((a.calls, a.rate_retries, a.held), (9, 21, 0))
            self.assertEqual(f.new(restore=True).snapshot(), a.snapshot())

    def test_inherited_money_cap_and_unknown_reserve_cannot_reopen(self):
        with trial_directory() as root:
            f = Fixture(root, base_action='timeout', cap='.28007')
            a = f.new(); f.replay(a)
            self.assertEqual(a.held, Decimal('.14'))
            # Remaining cap admits the pending request; its new unknown charge
            # must consume another .14 before any second physical dispatch.
            f.transport.actions.append('timeout')
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual(a.calls, f.old.calls+1)
            self.assertEqual(a.held, Decimal('.28'))
            self.assertEqual(f.new(restore=True).snapshot(), a.snapshot())

    def test_guard_and_audit_only_reject_before_transport(self):
        with trial_directory() as root:
            f = Fixture(root)
            def denied(d, snapshot):
                raise TechnicalStop('artificial source/price/auth/calendar/coverage gate')
            a = f.new(guard=denied); f.replay(a)
            with self.assertRaises(TechnicalStop): a(f.first)
            b = f.new(restore=True, audit_only=True); f.replay(b)
            with self.assertRaises(TechnicalStop): b(f.first)
            self.assertEqual(f.transport.physical, f.old.calls)

    def test_prefix_snapshot_tip_reset_and_duplicate_replay_rejected(self):
        with trial_directory() as root:
            f = Fixture(root)
            bad = deepcopy(f.prefix); bad['snapshot']['free429_retries'] = 0
            with self.assertRaises(TechnicalStop): f.new(prefix=bad)
            bad = deepcopy(f.prefix); bad['last_settlement'] = ref(f.base._path(1, 'settled'))
            with self.assertRaises(TechnicalStop): f.new(prefix=bad)
            bad = [request_identity(f.replay_requests[0])]*2
            with self.assertRaises(TechnicalStop): f.new(replays=bad)
            self.assertFalse((f.root/'successor').exists())

    def test_changed_old_edge_and_missing_receipt_block_before_creation(self):
        for mutation in ('edge', 'missing'):
            with self.subTest(mutation=mutation), trial_directory() as root:
                f = Fixture(root)
                p = f.base._path(f.base.calls, 'settled')
                if mutation == 'edge': p.write_bytes(p.read_bytes()+b' ')
                else: f.old._path(f.old.calls, 'response').rename(f.root/'retained-missing-response')
                with self.assertRaises((TechnicalStop, FileNotFoundError)): f.new()
                self.assertFalse((f.root/'successor').exists())

    def test_missing_zero_cost_proof_in_old_final_response_blocks_takeover(self):
        with trial_directory() as root:
            f = Fixture(root)
            response_path = f.old._path(f.old.calls, 'response')
            value = json.loads(response_path.read_bytes())
            value['usage'].pop('cost')
            response_path.write_bytes(encoded(value))
            settled_path = f.old._path(f.old.calls, 'settled')
            settled = json.loads(settled_path.read_bytes())
            settled['receipt']['response_sha256'] = sha256(response_path.read_bytes()).hexdigest()
            settled_path.write_bytes(encoded(settled))
            rebound = deepcopy(f.prefix)
            rebound['last_settlement'] = ref(settled_path)
            with self.assertRaises(Exception): f.new(prefix=rebound)
            self.assertFalse((f.root/'successor').exists())

    def test_old_rule_is_not_reinterpreted_by_new_adapter(self):
        with trial_directory() as root:
            f = Fixture(root)
            p = f.base.folder/'origin.json'; origin = json.loads(p.read_bytes())
            origin['initial_rate_retries'] = 21
            p.write_bytes(encoded(origin))
            # Even rebound artificial metadata cannot turn old history into
            # new-policy history: original TechnicalAdapter rejects >20.
            with self.assertRaises(TechnicalStop): restore_prefix(descriptor(f.base))

    def test_no_general_successor_schema_or_old_binding_or_nested_write_target(self):
        with trial_directory() as root:
            f = Fixture(root)
            for binding in ('a'*64, 'b'*64):
                with self.assertRaises(TechnicalStop): f.new(binding=binding)
            with self.assertRaises(TechnicalStop):
                RateStopPrefixAdapter(f.base.folder/'nested', f.transport, binding='c'*64,
                    prefix=f.prefix, replays=[], first_request=request_identity(f.first))
            a = f.new(); f.replay(a); a(f.first)
            with self.assertRaises(TechnicalStop): restore_prefix(descriptor(a))

    def test_duplicate_initialization_and_request_crash_remain_fail_closed(self):
        with trial_directory() as root:
            f = Fixture(root); a = f.new()
            with self.assertRaises(TechnicalStop): f.new()
            f.replay(a); f.transport.actions.append('crash')
            with self.assertRaises(KeyboardInterrupt): a(f.first)
            self.assertTrue(a.poisoned)
            with self.assertRaises(TechnicalStop): f.new(restore=True)
            self.assertTrue(a._path(a.calls+1, 'request').is_file())
            self.assertTrue(a._path(a.calls+1, 'binding').is_file())

    def test_new_counter_reservation_and_previous_hash_tampering_block_restore(self):
        for field, value in (('global_rate_retry', 1), ('retry_kind', 'initial'),
                             ('reservation_usd', '0'), ('previous_record', '0'*64)):
            with self.subTest(field=field), trial_directory() as root:
                f = Fixture(root); a = f.new(); f.replay(a); a(f.first)
                p = a._path(a.calls, 'settled'); record = json.loads(p.read_bytes())
                record['dispatch'][field] = value
                p.write_bytes(encoded(record))
                a._path(a.calls, 'binding').write_bytes(encoded(record['dispatch']))
                with self.assertRaises(TechnicalStop): f.new(restore=True)

    def test_invalid_free_proof_or_overcharge_never_gains_rate_retry(self):
        for action in ('bad-rate', '401', 'over'):
            with self.subTest(action=action), trial_directory() as root:
                f = Fixture(root); a = f.new(); f.replay(a)
                f.transport.actions.append(action)
                with self.assertRaises(Exception): a(f.first)
                self.assertEqual(f.transport.physical, f.old.calls+1)
                self.assertTrue(a.poisoned)
                with self.assertRaises(TechnicalStop): f.new(restore=True)


if __name__ == '__main__':
    unittest.main()
