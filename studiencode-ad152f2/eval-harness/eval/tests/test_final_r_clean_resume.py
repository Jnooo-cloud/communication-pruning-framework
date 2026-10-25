"""Finite C1-C7 checks using invented tasks only; no provider, key or real gold.

The outer test runner retains fixtures and archives exact code before execution.
The short fixture stops between completed blocks of a genuinely admitted old
section. It exercises the same inheritance as R87 without loading study tasks.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study import file_hash
from project.research_control.recovery import RecoveryFault
from study_preparation import final_r_resume as old, final_r_clean_resume as clean
from study_preparation import final_secondary as secondary, final_preflight as gate, final_execution as native
from study_preparation import final_r_clean_resume_operator as operator, final_operator
from study_preparation.final_plan import make_plan
from tests.test_final_preflight import trial_directory
from tests.test_final_r_resume import RFixture


class CleanFixture(RFixture):
    def __init__(self, root):
        def expanded(frame, **kwargs):
            counts = kwargs['counts']
            if counts['P'] == 2:
                counts['R'] = 3
            return make_plan(frame, **kwargs)
        with patch('tests.test_final_r_resume.make_plan', side_effect=expanded):
            super().__init__(root)
        self.initialize_recovery()
        state = self.run_recovery()
        self.confirm(state)
        # The fixed, invented account covers one whole block, but no second.
        try:
            self.run_recovery(self.candidate['section_ends'][1], coverage=self.coverage('5.1800001'))
        except gate.StudyStop:
            pass
        else:
            raise AssertionError('invented coverage must stop before third R block')
        self.inner_binding, self.inner_folder = self.binding, self.folder
        state, budget = old._inspect(self.inner_binding, self.candidate, self.plan, self.inner_folder)
        assert state['secondary_completed_blocks'] == 2
        review = self.file('clean-origin-review.json', {
            'inner_binding_sha256': self.inner_binding['sha256'], 'inherited_state_sha256': state['state_sha256'],
            'completed_blocks': state['completed_blocks'], 'ledger_sha256': file_hash(self.inner_folder / 'budget.jsonl'),
            'reviewer': 'artificial-independent-reviewer', 'accepted': True, 'not_implementation_author': True})
        backup = self.file('clean-origin-backup.json', {'artificial_only': True, 'full_reread': True})
        self.origin = clean.prepare_origin(self.inner_binding, self.candidate, self.plan, review=review, backup=backup)
        self.folder = self.inner_folder.parent / 'continuation-R00087/live'
        self.binding = clean.prepare_binding(self.candidate, self.plan, inner_binding=self.inner_binding,
            origin=self.origin, folder=self.folder, control=self.control, witness=self.folder.parent / 'witness',
            owner='artificial-executor')
        self.inherited_calls = self.transport.calls
        self.inherited_loads, self.inherited_selections = len(self.loads), len(self.selections)
        self.inherited_files = secondary._all_files(self.inner_folder)
        self.inherited_ledger = (self.inner_folder / 'budget.jsonl').read_bytes()

    def initialize_clean(self):
        return clean.initialize(self.binding, self.candidate, self.plan, **self.args(), checkpoint=self.checkpoint)

    def clean_coverage(self, amount='100'):
        budget = old._budget(self.inner_binding, self.plan, self.folder, existing=True)
        return {'binding_sha256': self.binding['sha256'], 'origin': 'artificial_fixture',
            'observed_epoch': 90, 'valid_until_epoch': 1000, 'available_usd': amount,
            'native_cost_at_observation_usd': str(budget.cost)}

    def run_clean(self, end=None, *, coverage=None):
        return clean.run_section(self.binding, self.candidate, self.plan, **self.args(),
            section_end=self.binding['first_hold'] if end is None else end,
            coverage=self.clean_coverage() if coverage is None else coverage, **self.dependencies())

    def confirm_clean(self, state):
        return self.confirm_for(clean, self.binding, state, 'clean')

    def finish_clean_panel(self, panel):
        evidence = clean.analyze_panel(self.binding, self.candidate, self.plan, panel, **self.args())
        prepared = clean.prepare_panel_backup(self.binding, self.candidate, self.plan, panel,
            **self.args(), checkpoint=self.checkpoint)
        review = self.file('clean-panel-review-' + panel + '.json', {'binding_sha256': self.binding['sha256'],
            'panel': panel, 'analysis_sha256': evidence['sha256'], 'reviewer': 'artificial-independent-reviewer',
            'not_implementation_author': True, 'accepted': True})
        remote = self.file('clean-panel-remote-' + panel + '.json', {'artificial_only': True,
            'binding_sha256': self.binding['sha256'], 'panel': panel, 'analysis_sha256': evidence['sha256'],
            'archive_sha256': prepared['backup']['sha256'], 'members': prepared['backup']['members'],
            'full_reread': True, 'accepted': True, 'destination': 'artificial_local'})
        clean.close_panel(self.binding, self.candidate, self.plan, panel, **self.args(), review=review, remote_backup=remote)
        return gate.read_json(evidence['path'])


class CleanResumeTests(unittest.TestCase):
    def test_C1_byte_exact_prefix_outer_identity_and_no_new_entries(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            state = f.initialize_clean()
            self.assertEqual((f.folder / 'budget.jsonl').read_bytes(), f.inherited_ledger)
            self.assertEqual(clean._data_files(f.folder), f.origin['data_inventory'])
            self.assertEqual(state['continuation_new_calls'], 0)
            self.assertEqual(Decimal(state['continuation_new_known_cost_usd']), 0)
            self.assertEqual(state['inner_state_sha256'], f.origin['inherited_state_sha256'])
            self.assertNotEqual(state['state_sha256'], state['inner_state_sha256'])
            self.assertEqual((len(f.loads), len(f.selections), f.transport.calls),
                (f.inherited_loads, f.inherited_selections, f.inherited_calls))
            self.assertEqual(secondary._all_files(f.inner_folder), f.inherited_files)
            self.assertFalse((f.folder / 'STOP.json').exists())
            self.assertEqual(secondary._section_states(f.folder), {})

    def test_C1_changed_missing_extra_original_and_partial_prefix_rejected(self):
        for kind in ('changed', 'missing', 'extra', 'partial', 'ledger'):
            with self.subTest(kind=kind), trial_directory() as directory:
                f = CleanFixture(directory)
                path = f.inner_folder / 'provider/00001-response.json'
                if kind == 'missing':
                    path.rename(path.with_suffix('.retained-missing'))
                elif kind == 'partial':
                    path = f.inner_folder / 'blocks/000002/started.json'
                    path.parent.mkdir()
                    path.write_bytes(b'{}')
                else:
                    if kind == 'extra': path = f.inner_folder / 'provider/EXTRA'
                    if kind == 'ledger': path = f.inner_folder / 'budget.jsonl'
                    path.write_bytes((path.read_bytes() if path.exists() else b'') + b' ')
                with self.assertRaises((gate.StudyStop, ValueError, RecoveryFault)):
                    f.initialize_clean()
                self.assertEqual(f.transport.calls, f.inherited_calls)
                self.assertFalse((f.control / clean.CLAIM).exists())

    def test_C1_modified_retained_witness_rejected(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            path = next(Path(f.inner_binding['witness']).rglob('*.json'))
            # This is an invented test file; production originals are never mutated.
            path.chmod(0o600)
            path.write_bytes(path.read_bytes() + b' ')
            with self.assertRaises((gate.StudyStop, ValueError, RecoveryFault)):
                f.initialize_clean()
            self.assertEqual(f.transport.calls, f.inherited_calls)
            self.assertFalse((f.control / clean.CLAIM).exists())

    def test_C2_single_canonical_claim_lock_stale_witness_and_inner_authority_rejected(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            with native.study_lock(f.control):
                with self.assertRaises((gate.StudyStop, RuntimeError)):
                    f.initialize_clean()
            state = f.initialize_clean()
            with self.assertRaises(gate.StudyStop): f.initialize_clean()
            alternate = gate.seal({**f.binding, 'folder': str(f.root / 'alternate')})
            with self.assertRaises(gate.StudyStop):
                clean.initialize(alternate, f.candidate, f.plan, folder=f.root / 'alternate', control=f.control,
                    clock=f.clock, checkpoint=f.checkpoint)
            f.confirm_clean(state)
            bad = f.clean_coverage(); bad['binding_sha256'] = f.inner_binding['sha256']
            with self.assertRaises(gate.StudyStop): f.run_clean(coverage=bad)
            (f.folder / 'unexpected-file').write_bytes(b'preserved witness mutation')
            with self.assertRaises((gate.StudyStop, RuntimeError, RecoveryFault)): f.run_clean()
            self.assertEqual(f.transport.calls, f.inherited_calls)

    def test_C3_next_block_next_provider_preserved_rows_and_no_replay(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            adopted = f.initialize_clean(); f.confirm_clean(adopted)
            state = f.run_clean()
            self.assertEqual(len(f.loads) - f.inherited_loads, 1)
            self.assertEqual(len(f.selections) - f.inherited_selections, 1)
            self.assertEqual(state['rows'][:len(adopted['rows'])], adopted['rows'])
            self.assertEqual(state['budget']['calls'], f.origin['ledger_prefix']['calls'] + state['continuation_new_calls'])
            self.assertGreater(state['continuation_new_calls'], 0)
            self.assertTrue(native._provider_files(f.folder, f.origin['ledger_prefix']['calls'] + 1)['request'].exists())
            self.assertTrue((f.folder / 'budget.jsonl').read_bytes().startswith(f.inherited_ledger))
            self.assertEqual(file_hash(f.folder / 'replacement.json'), file_hash(f.inner_folder / 'replacement.json'))
            self.assertEqual(secondary._all_files(f.inner_folder), f.inherited_files)
            self.assertEqual(len(state['generation_ids']), f.inner_binding['incident']['known_calls'] + state['budget']['calls'])

    def test_C4_adoption_distinct_original_halts_reviews_and_backups_gate_next_section(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            state = f.initialize_clean()
            self.assertEqual(state['checkpoint_kind'], 'technical_clean_prefix_adoption')
            self.assertLess(f.origin['last_regular_hold'], state['completed_blocks'])
            with self.assertRaises((gate.StudyStop, FileNotFoundError)): f.run_clean()
            f.confirm_clean(state)
            with self.assertRaises(gate.StudyStop): f.run_clean(state['completed_blocks'] + 2)
            completed = f.run_clean()
            self.assertEqual(completed['checkpoint_kind'], 'original_planned_hold')
            calls = f.transport.calls
            with self.assertRaises((gate.StudyStop, FileNotFoundError)):
                f.run_clean(f.candidate['section_ends'][2])
            self.assertEqual(f.transport.calls, calls)
            clean._verify_receipt(f.folder, completed)
            with self.assertRaises((gate.StudyStop, FileNotFoundError)):
                clean._verify_receipt(f.folder, {**completed, 'state_sha256': state['inner_state_sha256']})

    def test_C5_cost_basis_reserve_caps_expiry_and_whole_block_gates(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            state = f.initialize_clean(); f.confirm_clean(state)
            old_budget = old._budget(f.inner_binding, f.plan, f.inner_folder, existing=True)
            copied = old._budget(f.inner_binding, f.plan, f.folder, existing=True)
            self.assertEqual((old_budget.cap, old_budget.max_calls, old_budget.cost), (copied.cap, copied.max_calls, copied.cost))
            view = clean.accounting_view(f.binding, copied.cost)
            self.assertEqual(view['original_R_held_reservation_usd'], '0.14')
            self.assertIsNone(view['actual_total_cost_usd'])
            for coverage in (f.clean_coverage('5.04'), {**f.clean_coverage(), 'native_cost_at_observation_usd': '0'},
                {**f.clean_coverage(), 'valid_until_epoch': 99}):
                with self.assertRaises(gate.StudyStop): f.run_clean(coverage=coverage)
            with self.assertRaises(gate.StudyStop):
                clean.run_section(f.binding, f.candidate, f.plan, folder=f.folder, control=f.control,
                    clock=lambda:1001, section_end=f.binding['first_hold'], coverage=f.clean_coverage(), **f.dependencies())
            self.assertEqual(f.transport.calls, f.inherited_calls)

    def test_C6_R_T_F_native_analysis_outer_complete_chain(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            adopted = f.initialize_clean(); f.confirm_clean(adopted)
            for panel, end in zip(('R', 'T', 'F'), f.candidate['section_ends'][1:]):
                state = f.run_clean(end); f.confirm_clean(state)
                result = f.finish_clean_panel(panel)
                if panel == 'R':
                    self.assertEqual(result['affected_cost_endpoints'], ['R03', 'R08'])
                    self.assertFalse(result['zero_cost_imputation'])
                self.assertIsNone(result['actual_total_project_cost_usd'])
                self.assertFalse(result['continuous_interrupted_D_latency_available'])
                closure = gate.read_json(f.folder / 'panels' / panel / 'complete.json')
                self.assertEqual(closure['binding_sha256'], f.binding['sha256'])
                self.assertIn('provenance.json', closure['evidence'])
            self.assertTrue(state['complete'])
            self.assertEqual(secondary._all_files(f.inner_folder), f.inherited_files)

    def test_C7_unknown_http_429_billing_interrupt_no_retry_and_F01(self):
        for mode in ('transport', 'http', '429', 'unknown', 'duplicate', 'interrupt', 'length'):
            with self.subTest(mode=mode), trial_directory() as directory:
                f = CleanFixture(directory)
                state = f.initialize_clean(); f.confirm_clean(state)
                f.transport.mode, f.transport.fail_at = mode, f.transport.calls + 1
                original_call = type(f.transport).__call__
                def status429(obj, endpoint, body=None):
                    status, response = original_call(obj, endpoint, body)
                    if endpoint == 'chat/completions' and obj.calls == obj.fail_at and mode == '429':
                        return 429, encoded({'error': {'code': 429}})
                    return status, response
                with patch.object(type(f.transport), '__call__', status429 if mode == '429' else original_call):
                    if mode == 'length':
                        completed = f.run_clean()
                        self.assertIn('model_failure', {r['status'] for r in completed['rows'][-6:]})
                    else:
                        with self.assertRaises((BudgetStop, KeyboardInterrupt, gate.StudyStop)):
                            f.run_clean()
                        calls = f.transport.calls
                        self.assertTrue((f.folder / 'STOP.json').exists())
                        if mode == '429':
                            received = native._provider_files(f.folder, f.origin['ledger_prefix']['calls'] + 1)['received']
                            self.assertEqual(gate.read_json(received)['http_status'], 429)
                        with self.assertRaises((gate.StudyStop, RuntimeError, RecoveryFault)):
                            f.run_clean()
                        self.assertEqual(f.transport.calls, calls)

    def test_C7_own_session_gate_before_encoder_key_and_immutable_candidate(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            candidate = deepcopy(f.candidate)
            candidate['operator'] = {'output_directory': str(f.inner_folder),
                'operation_directory': str(f.inner_folder.parent / 'operation')}
            cp = f.file('session-candidate.json', candidate)['path']
            bp = f.file('session-binding.json', f.binding)['path']
            with patch.object(final_operator, 'FrozenMiniLM') as encoder, patch.object(final_operator, 'load_key') as key:
                session = operator.Session(cp, bp)
                self.assertEqual(session.candidate['operator']['output_directory'], str(f.inner_folder))
                self.assertEqual(session.settings['output_directory'], str(f.folder))
                self.assertIsNone(session.client)
                with self.assertRaises(gate.StudyStop): session.metadata_gate()
                with self.assertRaises(gate.StudyStop): session.initialize()
                encoder.assert_not_called(); key.assert_not_called()

    def test_C7_session_native_coverage_gate_precedes_encoder_and_key(self):
        with trial_directory() as directory:
            f = CleanFixture(directory)
            state = f.initialize_clean(); f.confirm_clean(state)
            candidate = deepcopy(f.candidate)
            candidate['operator'] = {'output_directory': str(f.inner_folder),
                'operation_directory': str(f.inner_folder.parent / 'operation')}
            cp = f.file('session-candidate.json', candidate)['path']
            bp = f.file('session-binding.json', f.binding)['path']
            session = operator.Session(cp, bp)
            session.candidate = f.candidate
            # The real Session deliberately rejects artificial mode. Only that
            # metadata admission is substituted; the full native artificial
            # claim/witness/receipt/confirmation/coverage gate remains real here.
            with patch.object(session, 'metadata_gate', return_value={}), \
                 patch.object(operator.time, 'time', return_value=100), \
                 patch.object(final_operator, 'FrozenMiniLM') as encoder, \
                 patch.object(final_operator, 'load_key') as key:
                with self.assertRaisesRegex(gate.StudyStop, 'whole block|coverage|account'):
                    session.run(f.binding['first_hold'], coverage=f.clean_coverage('5.04'))
                encoder.assert_not_called(); key.assert_not_called()
            self.assertEqual(f.transport.calls, f.inherited_calls)
            self.assertIsNone(session.encoder)
            self.assertIsNone(session.client)



if __name__ == '__main__':
    unittest.main()
