"""Invented partial-Q coverage stop, retained provenance and native R/T/F flow."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import unittest

from communication_pruning.study import file_hash
from study_preparation import final_coverage_resume as core, final_technical_resume as old
from study_preparation import final_execution as native, final_preflight as gate
from study_preparation.final_plan import make_plan
from tests.test_final_technical_resume import TechnicalFixture, technical_fake
from tests.test_final_preflight import trial_directory
from tests.study_fixture import FakeTransport


class CoverageFixture(TechnicalFixture):
    def __init__(self, root):
        def expanded(frame, **kwargs):
            if kwargs['counts']['P'] == 2:
                kwargs['counts']['R'] = 6
            return make_plan(frame, **kwargs)
        with patch('tests.test_final_technical_resume.make_plan', side_effect=expanded):
            super().__init__(Path(root).resolve())
        TechnicalFixture.init(self)
        # A known technical fee belongs to the immutable inherited prefix.
        self.transport.paid_failure_call = self.transport.calls+1
        state = TechnicalFixture.run(self); self.confirm_technical(state)
        target = self.plan['panels']['R'][4]
        before = 0
        for slot in target['slots']:
            if slot['arm'] == 'Q':
                break
            config, rounds, _ = native._configuration(self.candidate, target, slot['arm'],
                {'spatial_q': self.q, 'temporal_qst': None})
            before += (1 if slot['arm'] == 'S' else 5) if config is None else rounds*len(config.roles)+1
        # Exact fresh fixture coverage falls below .98 after the third Q reply.
        coverage = self.technical_coverage(str(Decimal('.98')+Decimal(before+3)*Decimal('.0000108')-Decimal('.0000054')))
        try:
            TechnicalFixture.run(self, self.candidate['section_ends'][1], coverage=coverage)
        except gate.StudyStop:
            if not (self.folder/'STOP.json').exists():
                raise
        else:
            raise AssertionError('invented cash stop required')
        self.technical_binding, self.technical_folder = self.binding, self.folder
        self.origin = core.prepare_origin(self.binding, self.candidate, self.plan)
        self.folder = self.technical_folder.parent/'coverage-R01462/live'
        self.binding = core.prepare_binding(self.candidate, self.plan, inner_binding=self.technical_binding,
            origin=self.origin, folder=self.folder, control=self.control, witness=self.folder.parent/'witness',
            owner='invented-coverage-operator')
        self.original_inventory = core._all_files(self.technical_folder)
        self.original_witness = core._all_files(self.technical_binding['witness'])
        self.original_claim = file_hash(self.technical_binding['claim_path'])

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
        shared = dict(kind='zero-call-coverage-adoption', binding_sha256=self.binding['sha256'],
                      state_sha256=state['state_sha256'], accepted=True)
        review = self.file('coverage-adoption-review.json', dict(shared,
            reviewer='invented-nonauthor', not_implementation_author=True))
        receipt = gate.read_json(core._receipt_path(self.folder, state))
        backup = self.file('coverage-adoption-backup.json', dict(shared,
            archive_sha256=receipt['backup']['sha256'], members=state['evidence'],
            full_reread=True, destination='artificial_local'))
        return core.confirm_adoption(self.binding, self.candidate, self.plan, **self.args(), review=review, backup=backup)

    def confirm_coverage(self, state):
        return self.confirm_for(core, self.binding, state, 'coverage')

    def close(self, panel):
        evidence = core.analyze_panel(self.binding, self.candidate, self.plan, panel, **self.args())
        prepared = core.prepare_panel_backup(self.binding, self.candidate, self.plan, panel,
            **self.args(), checkpoint=self.checkpoint)
        review = self.file('coverage-panel-review-'+panel+'.json', dict(binding_sha256=self.binding['sha256'],
            panel=panel, analysis_sha256=evidence['sha256'], reviewer='invented-nonauthor',
            not_implementation_author=True, accepted=True))
        remote = self.file('coverage-panel-backup-'+panel+'.json', dict(artificial_only=True,
            binding_sha256=self.binding['sha256'], panel=panel, analysis_sha256=evidence['sha256'],
            archive_sha256=prepared['backup']['sha256'], members=prepared['backup']['members'],
            full_reread=True, accepted=True, destination='artificial_local'))
        core.close_panel(self.binding, self.candidate, self.plan, panel, **self.args(), review=review, remote_backup=remote)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        fake = patch.object(FakeTransport, '__call__', technical_fake)
        fake.start(); self.addCleanup(fake.stop)

    def test_zero_call_adoption_exact_partial_then_all_native_panels(self):
        with trial_directory() as directory:
            f = CoverageFixture(directory); before = f.transport.calls
            state = f.init()
            self.assertEqual((state['secondary_completed_blocks'], state['continuation_new_calls']), (4, 0))
            self.assertEqual(f.transport.calls, before)
            self.assertEqual(state['budget'], f.origin['prefix']['snapshot'])
            with self.assertRaises(Exception): f.run()
            f.accept_adoption(state)
            loads, selections = len(f.loads), len(f.selections)
            f.transport.paid_failure_call = f.transport.calls+1
            state = f.run()
            self.assertEqual(state['secondary_completed_blocks'], 5)
            self.assertEqual((len(f.loads), len(f.selections)), (loads, selections))
            first = gate.read_json(f.folder/'dispatch'/f"{f.origin['prefix']['snapshot']['calls']+1:06d}-binding.json")
            self.assertEqual(first['logical_id'], f.origin['first_request']['logical_id'])
            self.assertEqual(first['retry_kind'], 'initial')
            self.assertEqual(len(list((f.folder/'replays').glob('*.json'))), 3)
            for row in state['rows']:
                if 'known_technical_failure_cost_usd' in row:
                    self.assertEqual(Decimal(row['cost_usd']), Decimal(row['native_terminal_cost_usd'])+Decimal('.0000108'))
            self.assertEqual(sum('known_technical_failure_cost_usd' in r for r in state['rows']), 2)
            with self.assertRaises(Exception): f.run(f.candidate['section_ends'][1])
            f.confirm_coverage(state)
            state = f.run(f.candidate['section_ends'][1]); f.confirm_coverage(state); f.close('R')
            for panel, end in zip(('T', 'F'), f.candidate['section_ends'][2:]):
                state = f.run(end); f.confirm_coverage(state); f.close(panel)
                analysis = gate.read_json(f.folder/'panels'/panel/'analysis.json')
                self.assertIn('original_analysis', analysis)
            self.assertTrue(state['complete'])
            self.assertEqual(core._all_files(f.technical_folder), f.original_inventory)
            self.assertEqual(core._all_files(f.technical_binding['witness']), f.original_witness)
            self.assertEqual(file_hash(f.technical_binding['claim_path']), f.original_claim)
            self.assertFalse((f.folder/'confirmations'/f"{f.origin['completed_blocks']:06d}.json").exists())

    def test_coverage_freshness_exact_hold_and_native_lock_block_before_send(self):
        with trial_directory() as directory:
            f = CoverageFixture(directory); state = f.init(); f.accept_adoption(state); before = f.transport.calls
            for coverage in (f.current_coverage('.979862237'), dict(f.current_coverage(), valid_until_epoch=0),
                             dict(f.current_coverage(), native_cost_at_observation_usd='999')):
                with self.assertRaises(Exception): f.run(coverage=coverage)
            with self.assertRaises(Exception): f.run(f.binding['first_hold']+1)
            with native.study_lock(f.control):
                with self.assertRaises(Exception): f.run()
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.folder/'STOP.json').exists())

    def test_double_initialization_predecessor_mutation_and_successor_rollback_block(self):
        with trial_directory() as directory:
            f = CoverageFixture(directory); state = f.init(); f.accept_adoption(state); before = f.transport.calls
            with self.assertRaises(Exception): f.init()
            # Invented unexpected successor file: witness mismatch, no repair.
            (f.folder/'UNEXPECTED.json').write_text('{}')
            with self.assertRaises(Exception): f.run()
            self.assertEqual(f.transport.calls, before)
            self.assertEqual(core._all_files(f.technical_folder), f.original_inventory)
        with trial_directory() as directory:
            f = CoverageFixture(directory); before = f.transport.calls
            path = f.technical_folder/'STOP.json'
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaises(Exception): f.init()
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.control/core.CLAIM).exists())

    def test_failed_fee_input_rejects_double_enrichment(self):
        class Book:
            def known_failed_costs(self): return {'run:1': Decimal('.01')}
        raw = [{'run_id': 'run', 'cost_usd': '.02'}]
        once = core._raw_rows_with_failed_costs(raw, Book())
        self.assertEqual(once[0]['cost_usd'], '0.03')
        self.assertEqual(raw, [{'run_id': 'run', 'cost_usd': '.02'}])
        with self.assertRaises(gate.StudyStop): core._raw_rows_with_failed_costs(once, Book())


if __name__ == '__main__':
    unittest.main()
