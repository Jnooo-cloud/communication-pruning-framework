"""Artificial prefix/suffix boundary tests; all decisive fixtures retained."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import unittest

from communication_pruning.openrouter import encoded
from communication_pruning.technical_retry import TechnicalAdapter, TechnicalStop, ref
from communication_pruning.technical_prefix import PrefixTechnicalAdapter, request_identity
from communication_pruning.study import file_hash
from tests.test_technical_retry import Script, trial_directory
from tests.test_rate_limit import Clock, request


class PrefixFixture:
    def __init__(self, root, *, actions=(), cap='20', max_calls=1000, rate=1, **transport_args):
        self.root, self.clock = Path(root).resolve(), Clock()
        self.transport = Script(actions, **transport_args)
        self.old = TechnicalAdapter(self.root/'prefix', self.transport, binding='a'*64,
            cap=cap, max_calls=max_calls, initial_rate_retries=rate,
            clock=self.clock, sleep=self.clock.sleep)
        self.requests = [request('replay-'+str(i)) for i in range(3)]
        self.answers = [self.old(r) for r in self.requests]
        self.prefix = dict(origin=ref(self.old.folder/'origin.json'),
            last_settlement=ref(self.old._path(self.old.calls, 'settled')), snapshot=self.old.snapshot())
        self.first = request('first-unsent')
        self.inventory = {p.name: file_hash(p) for p in self.old.folder.iterdir()}

    def new(self, **kwargs):
        return PrefixTechnicalAdapter(self.root/'suffix', self.transport, binding='b'*64,
            prefix=self.prefix, replays=[request_identity(r) for r in self.requests],
            first_request=request_identity(self.first), clock=self.clock, sleep=self.clock.sleep, **kwargs)

    def replay(self, adapter):
        before = self.transport.physical
        for req, answer in zip(self.requests, self.answers):
            assert adapter(req) == answer
        assert self.transport.physical == before


class PrefixTests(unittest.TestCase):
    def test_exact_replays_inherited_book_and_first_initial_call(self):
        with trial_directory() as root:
            f = PrefixFixture(root, actions=['paid503', 'ok'])
            a = f.new()
            self.assertEqual(a.snapshot(), f.old.snapshot())
            self.assertEqual(a.generations, f.old.generations)
            self.assertEqual(a.states, f.old.states)
            self.assertEqual(a.records, f.old.records)
            f.replay(a); a(f.first)
            d = a.records[-1]['dispatch']
            self.assertEqual((d['number'], d['retry_kind']), (f.old.calls+1, 'initial'))
            self.assertEqual(d['known_before_usd'], str(f.old.cost))
            self.assertEqual(a.technical_retries, f.old.technical_retries)
            self.assertEqual(a.rate_retries, 1)
            b = f.new(restore=True, audit_only=True)
            self.assertEqual(b.snapshot(), a.snapshot())
            self.assertEqual(b.states, a.states)
            self.assertEqual(b.known_failed_costs(), {'replay-0': Decimal('.0000108')})
            self.assertEqual({p.name: file_hash(p) for p in f.old.folder.iterdir()}, f.inventory)

    def test_out_of_order_extra_and_changed_replays_or_first_request_block(self):
        with trial_directory() as root:
            f = PrefixFixture(root); a = f.new(); before = f.transport.physical
            for wrong in (f.first, f.requests[1], replace(f.requests[0], instruction='changed')):
                with self.assertRaises(TechnicalStop): a(wrong)
            f.replay(a)
            for wrong in (f.requests[0], request('foreign'), replace(f.first, instruction='changed')):
                with self.assertRaises(TechnicalStop): a(wrong)
            self.assertEqual(f.transport.physical, before)
            a(f.first)
            with self.assertRaises(TechnicalStop): a(f.first)
            with self.assertRaises(TechnicalStop): a(f.requests[0])
            self.assertEqual(f.transport.physical, before+1)

    def test_model_failure_is_terminal_and_never_resent(self):
        with trial_directory() as root:
            f = PrefixFixture(root, fail_at=1, mode='length'); a = f.new()
            self.assertEqual(f.old.states['replay-0']['outcome'], 'model_failed')
            f.replay(a)
            self.assertEqual(f.transport.physical, 3)
            with self.assertRaises(TechnicalStop): a(f.requests[0])

    def test_cumulative_call_cap_not_reopened(self):
        with trial_directory() as root:
            f = PrefixFixture(root, max_calls=3); a = f.new(); f.replay(a)
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual(f.transport.physical, 3)

    def test_cumulative_money_and_unknowns_not_reopened(self):
        with trial_directory() as root:
            f = PrefixFixture(root, cap='.28003', actions=['timeout', 'ok'])
            a = f.new(); f.replay(a)
            self.assertEqual(a.held, Decimal('.14'))
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual(a.calls, f.old.calls)

    def test_suffix_failed_charges_and_waits_are_preserved_once(self):
        with trial_directory() as root:
            f = PrefixFixture(root, actions=['paid503', 'ok', 'ok', 'ok', 'paid503', 'ok'])
            a = f.new(); f.replay(a); a(f.first)
            self.assertEqual(sum(f.clock.waits), 60)
            b = f.new(restore=True, audit_only=True)
            self.assertEqual(b.known_failed_costs(),
                {'replay-0': Decimal('.0000108'), 'first-unsent': Decimal('.0000108')})
            self.assertEqual(b.technical_retries, 2)

    def test_unknown_suffix_and_retry_after_remain_bounded(self):
        with trial_directory() as root:
            f = PrefixFixture(root, actions=['ok', 'ok', 'ok', 'after', 'timeout', 'timeout'])
            a = f.new(); f.replay(a)
            with self.assertRaises(TechnicalStop): a(f.first)
            self.assertEqual(a.calls, 6)
            self.assertEqual(a.held, Decimal('.42'))
            self.assertEqual(sum(f.clock.waits), 300)
            b = f.new(restore=True)
            with self.assertRaises(TechnicalStop): b(f.first)
            self.assertEqual(f.transport.physical, 6)

    def test_prefix_tip_change_fails_before_suffix_creation(self):
        with trial_directory() as root:
            f = PrefixFixture(root)
            path = f.old._path(f.old.calls, 'settled')
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaises(TechnicalStop): f.new()
            self.assertFalse((f.root/'suffix').exists())

    def test_snapshot_reset_wrong_tip_or_old_first_identity_block(self):
        with trial_directory() as root:
            f = PrefixFixture(root); original = deepcopy(f.prefix)
            f.prefix['snapshot']['calls'] = 0
            with self.assertRaises(TechnicalStop): f.new()
            f.prefix = original
            f.first = f.requests[0]
            with self.assertRaises(TechnicalStop): f.new()
            self.assertFalse((f.root/'suffix').exists())

    def test_suffix_crash_evidence_and_second_initialization_block(self):
        with trial_directory() as root:
            f = PrefixFixture(root); a = f.new()
            with self.assertRaises(TechnicalStop): f.new()
            # Preserve a simulated crash between request write and settlement.
            a._path(a.calls+1, 'request').write_bytes(encoded({'invented': True}))
            with self.assertRaises(TechnicalStop): f.new(restore=True)
            self.assertEqual(f.transport.physical, 3)

    def test_guard_and_audit_stop_before_transport(self):
        with trial_directory() as root:
            f = PrefixFixture(root)
            def denied(*args): raise TechnicalStop('invented expired gate')
            a = f.new(guard=denied); f.replay(a)
            with self.assertRaises(TechnicalStop): a(f.first)
            b = f.new(restore=True, audit_only=True); f.replay(b)
            with self.assertRaises(TechnicalStop): b(f.first)
            self.assertEqual(f.transport.physical, 3)

    def test_inherited_global_technical_limit_cannot_reset(self):
        with trial_directory() as root:
            root = root.resolve(); clock = Clock(); transport = Script(['timeout', 'ok']*20+['ok']*3+['timeout'])
            old = TechnicalAdapter(root/'prefix', transport, binding='a'*64, cap='20', max_calls=1000,
                                   clock=clock, sleep=clock.sleep)
            for i in range(20): old(request('old-retry-'+str(i)))
            replay = [request('replay-'+str(i)) for i in range(3)]
            for r in replay: old(r)
            prefix = dict(origin=ref(old.folder/'origin.json'), last_settlement=ref(old._path(old.calls, 'settled')),
                          snapshot=old.snapshot())
            first = request('first-unsent')
            new = PrefixTechnicalAdapter(root/'suffix', transport, binding='b'*64, prefix=prefix,
                replays=[request_identity(r) for r in replay], first_request=request_identity(first),
                clock=clock, sleep=clock.sleep)
            for r in replay: new(r)
            with self.assertRaises(TechnicalStop): new(first)
            self.assertEqual(transport.physical, 44)
            self.assertEqual(new.technical_retries, 20)
            self.assertEqual(new.held, Decimal('2.94'))


if __name__ == '__main__':
    unittest.main()
