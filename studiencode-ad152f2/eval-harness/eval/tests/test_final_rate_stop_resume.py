"""S1-S6 invented nested rate-stop provenance and unchanged native R/T/F flow.

All trials are retained by Z50_TEST_EVIDENCE_DIR; no real study contents or
provider are used. Native model_failed closes its arm, so that terminal case is
placed in a completed inherited S arm, never falsely inside the open F arm.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from types import SimpleNamespace
import unittest

from communication_pruning.study import file_hash
from communication_pruning.openrouter import encoded
from study_preparation import final_rate_stop_resume as core, final_coverage_resume as old
from study_preparation import final_execution as native, final_preflight as gate
from study_preparation.final_plan import make_plan
from tests.test_final_coverage_resume import CoverageFixture
from tests.test_final_technical_resume import technical_fake
from tests.test_final_preflight import trial_directory
from tests.study_fixture import FakeTransport


class RateStopFixture(CoverageFixture):
    def __init__(self, root):
        def expanded(frame, **kwargs):
            if kwargs['counts']['P'] == 2:
                kwargs['counts']['R'] = 30
                trial = make_plan(frame, **kwargs)
                target = next(b['draw_index'] for b in trial['panels']['R'][6:] if b['arm_order'][-1] == 'F')
                kwargs['counts']['R'] = target+2
            return make_plan(frame, **kwargs)
        with patch('tests.test_final_coverage_resume.make_plan', side_effect=expanded):
            super().__init__(Path(root).resolve())
        state = CoverageFixture.init(self); CoverageFixture.accept_adoption(self, state)
        state = CoverageFixture.run(self, coverage=CoverageFixture.current_coverage(self)); CoverageFixture.confirm_coverage(self, state)
        count = state['secondary_completed_blocks']
        target = next(b for b in self.plan['panels']['R'][6:] if b['arm_order'][-1] == 'F')
        ordinary, failed_s = 0, None
        for block in self.plan['panels']['R'][count:target['draw_index']+1]:
            for slot in block['slots']:
                if block == target and slot['arm'] == 'F':
                    ordinary += 2
                    break
                if block == target and slot['arm'] == 'S':
                    failed_s = ordinary+1
                config, rounds, _ = native._configuration(self.candidate, block, slot['arm'],
                    {'spatial_q': self.q, 'temporal_qst': None})
                ordinary += (1 if slot['arm'] == 'S' else 5) if config is None else rounds*len(config.roles)+1
        inherited = old._adapter(self.binding, self.folder, audit_only=True)
        remaining = 20-inherited.rate_retries
        assert remaining > 0 and ordinary > remaining and failed_s > remaining
        before = self.transport.calls
        self.transport.actions = {before+1+2*i: 'free' for i in range(remaining)}
        self.transport.actions[before+ordinary+remaining] = 'free'
        self.transport.fail_at, self.transport.mode = before+failed_s+remaining, 'length'
        try:
            CoverageFixture.run(self, self.candidate['section_ends'][1], coverage=CoverageFixture.current_coverage(self))
        except Exception:
            if not (self.folder/'STOP.json').exists():
                raise
        else:
            raise AssertionError('invented global-rate stop required')
        self.coverage_binding, self.coverage_folder = self.binding, self.folder
        self.origin = core.prepare_origin(self.binding, self.candidate, self.plan)
        assert self.origin['partial_arm'] == 'F' and len(self.origin['done_arms']) == 5
        self.folder = self.coverage_folder.parent/'rate-stop-R01589/live'
        self.binding = core.prepare_binding(self.candidate, self.plan, inner_binding=self.coverage_binding,
            origin=self.origin, folder=self.folder, control=self.control, witness=self.folder.parent/'witness',
            owner='invented-rate-stop-operator')
        self.original_inventory = core._all_files(self.coverage_folder)
        self.original_witness = core._all_files(self.coverage_binding['witness'])
        self.original_claim = file_hash(self.coverage_binding['claim_path'])

    def init(self):
        return core.initialize(self.binding, self.candidate, self.plan, **self.args(), checkpoint=self.checkpoint)

    def current_coverage(self, amount='100'):
        adapter = core._adapter(self.binding, self.folder, audit_only=True)
        return dict(binding_sha256=self.binding['sha256'], origin='artificial_fixture',
            observed_epoch=90, valid_until_epoch=999, available_usd=amount,
            native_cost_at_observation_usd=str(adapter.cost))

    def run(self, end=None, coverage=None):
        return core.run_section(self.binding, self.candidate, self.plan, **self.args(),
            section_end=self.binding['first_hold'] if end is None else end,
            coverage=self.current_coverage() if coverage is None else coverage,
            **self.dependencies(), sleep=self.clock.sleep)

    def accept_adoption(self, state):
        shared = dict(kind='zero-call-rate-stop-adoption', binding_sha256=self.binding['sha256'],
            state_sha256=state['state_sha256'], accepted=True)
        review = self.file('rate-adoption-review.json', dict(shared,
            reviewer='invented-nonauthor', not_implementation_author=True))
        receipt = gate.read_json(core._receipt_path(self.folder, state))
        backup = self.file('rate-adoption-backup.json', dict(shared, archive_sha256=receipt['backup']['sha256'],
            members=state['evidence'], full_reread=True, destination='artificial_local'))
        return core.confirm_adoption(self.binding, self.candidate, self.plan, **self.args(), review=review, backup=backup)

    def confirm_rate(self, state):
        return self.confirm_for(core, self.binding, state, 'rate-stop')

    def close(self, panel):
        evidence = core.analyze_panel(self.binding, self.candidate, self.plan, panel, **self.args())
        prepared = core.prepare_panel_backup(self.binding, self.candidate, self.plan, panel,
            **self.args(), checkpoint=self.checkpoint)
        review = self.file('rate-panel-review-'+panel+'.json', dict(binding_sha256=self.binding['sha256'],
            panel=panel, analysis_sha256=evidence['sha256'], reviewer='invented-nonauthor',
            not_implementation_author=True, accepted=True))
        remote = self.file('rate-panel-backup-'+panel+'.json', dict(artificial_only=True,
            binding_sha256=self.binding['sha256'], panel=panel, analysis_sha256=evidence['sha256'],
            archive_sha256=prepared['backup']['sha256'], members=prepared['backup']['members'],
            full_reread=True, accepted=True, destination='artificial_local'))
        core.close_panel(self.binding, self.candidate, self.plan, panel, **self.args(), review=review, remote_backup=remote)


class RateStopTests(unittest.TestCase):
    def setUp(self):
        fake = patch.object(FakeTransport, '__call__', technical_fake)
        fake.start(); self.addCleanup(fake.stop)

    def test_zero_call_adoption_retry21_special_hold_then_native_panels(self):
        with trial_directory() as directory:
            f = RateStopFixture(directory); before = f.transport.calls
            old_adapter = old._adapter(f.coverage_binding, f.coverage_folder, audit_only=True)
            state = f.init()
            adapter = core._adapter(f.binding, f.folder, audit_only=True)
            self.assertEqual((f.transport.calls, state['continuation_new_calls']), (before, 0))
            self.assertEqual(state['budget'], f.origin['prefix']['snapshot'])
            for attr in ('states', 'records', 'generations', 'cost', 'held', 'calls', 'rate_retries', 'technical_retries'):
                self.assertEqual(getattr(adapter, attr), getattr(old_adapter, attr))
            self.assertTrue(any(v['outcome'] == 'model_failed' for v in old_adapter.states.values()))
            with self.assertRaises(Exception): f.run()
            f.accept_adoption(state)
            with self.assertRaises(Exception): f.run(f.candidate['section_ends'][1])
            loads, selections = len(f.loads), len(f.selections)
            state = f.run()
            self.assertEqual(state['completed_blocks'], f.binding['first_hold'])
            self.assertEqual((len(f.loads), len(f.selections)), (loads, selections))
            number = f.origin['prefix']['snapshot']['calls']+1
            first = gate.read_json(f.folder/'dispatch'/f'{number:06d}-binding.json')
            self.assertEqual(first['logical_id'], f.origin['first_request']['logical_id'])
            self.assertEqual(first['request_sha256'], f.origin['first_request']['request_sha256'])
            self.assertEqual((first['retry_kind'], first['rate_retry'], first['global_rate_retry']), ('rate_limited', 1, 21))
            self.assertEqual(first['technical_retry'], 0)
            self.assertEqual(first['global_technical_retry'], f.origin['prefix']['snapshot']['technical_retries'])
            self.assertEqual(first['not_before'], old_adapter.records[-1]['receipt']['received_at']+30)
            self.assertEqual(len(list((f.folder/'replays').glob('*.json'))), len(f.origin['replays']))
            self.assertFalse(state['continuous_arm_latency_available'])
            count = f.origin['secondary_completed_blocks']
            for arm in f.origin['done_arms']:
                self.assertEqual(core._all_files(f.folder/'blocks'/f'{count:06d}'/arm),
                                 core._all_files(f.coverage_folder/'blocks'/f'{count:06d}'/arm))
            for row in state['rows']:
                if 'known_technical_failure_cost_usd' in row:
                    self.assertEqual(Decimal(row['cost_usd']), Decimal(row['native_terminal_cost_usd'])+
                                     Decimal(row['known_technical_failure_cost_usd']))
            with self.assertRaises(Exception): f.run(f.candidate['section_ends'][1])
            f.confirm_rate(state)
            state = f.run(f.candidate['section_ends'][1]); f.confirm_rate(state); f.close('R')
            for panel, end in zip(('T', 'F'), f.candidate['section_ends'][2:]):
                state = f.run(end); f.confirm_rate(state); f.close(panel)
                analysis = gate.read_json(f.folder/'panels'/panel/'analysis.json')
                self.assertIn('original_analysis', analysis)
            self.assertTrue(state['complete'])
            self.assertEqual(state['budget']['free429_retries'], 21)
            self.assertEqual(core._all_files(f.coverage_folder), f.original_inventory)
            self.assertEqual(core._all_files(f.coverage_binding['witness']), f.original_witness)
            self.assertEqual(file_hash(f.coverage_binding['claim_path']), f.original_claim)
            self.assertFalse((f.folder/'confirmations'/f"{f.origin['completed_blocks']:06d}.json").exists())

    def test_coverage_calendar_exact_hold_and_shared_lock_fail_before_send(self):
        with trial_directory() as directory:
            f = RateStopFixture(directory); state = f.init(); f.accept_adoption(state); before = f.transport.calls
            for coverage in (f.current_coverage('.979862237'), dict(f.current_coverage(), valid_until_epoch=0),
                             dict(f.current_coverage(), native_cost_at_observation_usd='999')):
                with self.assertRaises(Exception): f.run(coverage=coverage)
            with self.assertRaises(Exception): f.run(f.binding['first_hold']+1)
            with native.study_lock(f.control):
                with self.assertRaises(Exception): f.run()
            stamp = f.clock.value
            f.clock.value = f.candidate['calendar']['end_epoch']+1
            with self.assertRaises(Exception): f.run()
            f.clock.value = stamp
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.folder/'STOP.json').exists())

    def test_old_non_tip_mutation_blocks_and_bytes_are_not_repaired(self):
        with trial_directory() as directory:
            f = RateStopFixture(directory); before = f.transport.calls
            path = sorted((f.coverage_folder/'dispatch').glob('*-settled.json'))[0]
            previous_bytes = path.read_bytes(); path.write_bytes(previous_bytes+b' ')
            with self.assertRaises(Exception): f.init()
            self.assertEqual(path.read_bytes(), previous_bytes+b' ')
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.control/core.CLAIM).exists())

    def test_duplicate_initialization_and_successor_witness_rollback_block(self):
        with trial_directory() as directory:
            f = RateStopFixture(directory); state = f.init(); f.accept_adoption(state); before = f.transport.calls
            with self.assertRaises(Exception): f.init()
            (f.folder/'UNEXPECTED.json').write_text('{}')
            with self.assertRaises(Exception): f.run()
            self.assertEqual(f.transport.calls, before)
            self.assertEqual(core._all_files(f.coverage_folder), f.original_inventory)

    def test_adoption_inventory_and_binding_tamper_cannot_start(self):
        with trial_directory() as directory:
            f = RateStopFixture(directory); before = f.transport.calls
            changed = deepcopy(f.binding); changed['origin']['prefix']['snapshot']['calls'] -= 1
            f.binding = gate.seal({k: v for k, v in changed.items() if k != 'sha256'})
            with self.assertRaises(Exception): f.init()
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.control/core.CLAIM).exists())

    def test_new_stop_crash_never_replays_or_automatically_restarts(self):
        with trial_directory() as directory:
            f = RateStopFixture(directory); state = f.init(); f.accept_adoption(state); before = f.transport.calls
            f.transport.fail_at, f.transport.mode = before+1, 'interrupt'
            with self.assertRaises(KeyboardInterrupt): f.run()
            self.assertEqual(f.transport.calls, before+1)
            stop = gate.read_json(f.folder/'STOP.json')
            self.assertFalse(stop['retry_allowed'])
            with self.assertRaises(Exception): f.run()
            self.assertEqual(f.transport.calls, before+1)
            self.assertEqual(core._all_files(f.coverage_folder), f.original_inventory)


class RealAnchorMetadataTests(unittest.TestCase):
    """Exercise the real-only predicate with invented technical objects only.

    The numeric constants describe the authorized anchor, but none of its real
    contents, readers, claims, witnesses or files are opened by these tests.
    """
    def origin(self, mutation=None):
        with trial_directory() as directory:
            folder = Path(directory)/'invented-live'
            (folder/'confirmations').mkdir(parents=True)
            holds = [10540]
            binding = dict(mode='authorized_execution',
                sha256='e3cedf4d9261857deb2cd38176b5af2b8e1370e81801b0132a622029858bb97e',
                folder=str(folder), control=str(Path(directory)/'invented-control'),
                witness=str(Path(directory)/'invented-witness'), claim_path=str(Path(directory)/'invented-claim'))
            adapter = SimpleNamespace(calls=44091, cost=Decimal('10.51520469'), held=Decimal(0),
                technical_retries=1, rate_retries=20, cap=Decimal('53.50242297'), max_calls=195273,
                _path=lambda number, kind: folder/f'{number:06d}-{kind}.json',
                snapshot=lambda: {'artificial_only': True})
            state = dict(adapter=adapter, completed=1589, rows=[{} for _ in range(9534)],
                partial_arm='F', done_arms=['S-k', 'D', 'Z', 'Q', 'S'], pending=object(), replays=[])
            identity = dict(logical_id='50d4c906a74daf48:Z50-STUDY-v1:R:01589:F:1:linking:1',
                request_sha256='bc8fa323a69b693cfbea7d3d71e62b1e975fe637d6be9f2ebc7cde8f2af0ba7e', output_limit=1024)
            hashes = {'STOP.json':'dc3bede993141554b3f703e33da3677aa887b7e9ceb570dc0fae7de0084084f4',
                '044091-settled.json':'44e27ffe9b0dcacaa35cad724c87a7a21599af8b8fe07aae7eaa7c7ee85b3f1c'}
            if mutation:
                mutation(binding, state, adapter, identity, hashes, holds)
            for hold in holds:
                (folder/'confirmations'/f'{hold:06d}.json').write_text('{}')
            witness = SimpleNamespace(assert_current=lambda binding: {'checkpoint': {'stop_active': True}})
            with ExitStack() as stack:
                for owner, name, value in (
                    (core, 'retained_state', lambda *args: state),
                    (old, '_claim', lambda *args: None),
                    (old, '_witness', lambda *args: witness),
                    (old, '_witness_binding', lambda *args: {'artificial_only': True}),
                    (core, 'request_identity', lambda request: dict(identity)),
                    (core, 'file_hash', lambda path: hashes.get(Path(path).name, 'a'*64)),
                    (core, '_all_files', lambda path: {'artificial_only': 'a'*64}),
                    (core, 'ref', lambda path: {'path': str(path), 'sha256': 'b'*64})):
                    stack.enter_context(patch.object(owner, name, value))
                return core.prepare_origin(binding, {}, {'counts': {'P':9040}})

    def test_exact_real_anchor_order_uses_native_plan_order(self):
        origin = self.origin()
        self.assertEqual(origin['done_arms'], ['S-k', 'D', 'Z', 'Q', 'S'])
        self.assertEqual(origin['completed_blocks'], 10629)
        self.assertEqual(origin['last_formal_hold'], 10540)

    def test_each_changed_real_anchor_field_is_rejected(self):
        cases = {
            'binding': lambda o,s,a,i,h,x: o.update(sha256='0'*64),
            'completed': lambda o,s,a,i,h,x: s.update(completed=1588),
            'row_count': lambda o,s,a,i,h,x: s['rows'].pop(),
            'partial_arm': lambda o,s,a,i,h,x: s.update(partial_arm='Q'),
            'old_wrong_inventory_order': lambda o,s,a,i,h,x: s.update(done_arms=['Z','S','S-k','D','Q']),
            'calls': lambda o,s,a,i,h,x: setattr(a,'calls',44090),
            'known_cost': lambda o,s,a,i,h,x: setattr(a,'cost',Decimal('10.51520468')),
            'held_reserve': lambda o,s,a,i,h,x: setattr(a,'held',Decimal('.14')),
            'technical_count': lambda o,s,a,i,h,x: setattr(a,'technical_retries',2),
            'rate_count': lambda o,s,a,i,h,x: setattr(a,'rate_retries',19),
            'cap': lambda o,s,a,i,h,x: setattr(a,'cap',Decimal('53.50242298')),
            'max_calls': lambda o,s,a,i,h,x: setattr(a,'max_calls',195274),
            'last_hold': lambda o,s,a,i,h,x: x.append(10541),
            'logical_id': lambda o,s,a,i,h,x: i.update(logical_id='invented-foreign-logical-id'),
            'body_hash': lambda o,s,a,i,h,x: i.update(request_sha256='0'*64),
            'output_limit': lambda o,s,a,i,h,x: i.update(output_limit=128),
            'STOP_hash': lambda o,s,a,i,h,x: h.update({'STOP.json':'0'*64}),
            'tip_hash': lambda o,s,a,i,h,x: h.update({'044091-settled.json':'0'*64}),
        }
        for name, mutation in cases.items():
            with self.subTest(name=name), self.assertRaises(gate.StudyStop):
                self.origin(mutation)


if __name__ == '__main__':
    unittest.main()
