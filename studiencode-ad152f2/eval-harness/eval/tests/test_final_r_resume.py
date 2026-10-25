"""Eight finite D-076 synthetic criteria. No actual study inputs or network.

Run only after Root has archived this source version. Every trial is retained
through Z50_TEST_EVIDENCE_DIR, including expected failures and stopped journals.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import unittest

from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study import file_hash
from project.research_control.recovery import RecoveryFault
from study_preparation import final_secondary as secondary, final_r_resume as resume
from study_preparation import final_execution as native, final_preflight as gate
from study_preparation.final_plan import make_plan, canonical_hash
from tests.test_final_preflight import Fixture, trial_directory


class RFixture(Fixture):
    def __init__(self, root, *, prefix=0, real_global=False):
        counts = {'P': 9040 if real_global else 2, 'R': prefix + 2, 'T': 1, 'F': 1}
        super().__init__(root, counts=counts)
        # Select an INVENTED planning seed solely to exercise the actual arm
        # order of the incident; no response/score is observed in this search.
        for seed in range(10000):
            trial = make_plan(self.frame, seed_base=seed,
                bindings={k: v['sha256'] for k, v in self.documents.items()}, mode='artificial_only',
                counts={'P': 1, 'R': prefix + 1, 'T': 1, 'F': 1})
            if trial['panels']['R'][prefix]['arm_order'] == ['S-k', 'Z', 'D', 'S', 'Q', 'F']:
                break
        else:
            raise AssertionError('finite artificial seed search did not find required order')
        self.plan = make_plan(self.frame, seed_base=seed, bindings=trial['bindings'], mode='artificial_only', counts=counts)
        self.candidate['plan_hash'] = self.plan['plan_hash']
        self.candidate['plan_evidence'] = self.file('plan.json', self.plan)
        self.candidate['section_ends'] = [counts['P']] + ([counts['P'] + prefix] if prefix else []) + [counts['P'] + counts['R'], sum(counts.values()) - 1, sum(counts.values())]
        self.bind()
        self.control.mkdir()
        original_P = self.root / 'invented-P'
        original_P.mkdir()
        native._claim(self.candidate, self.plan, original_P, self.control, create=True)
        self.folder = self.root / 'secondary'
        self.analysis_contract = self.file('analysis-contract.json', {'study_id': self.plan['study_id'],
            'seed_base': seed, 'bootstrap_repetitions': 19999, 'secondary_costs': 'descriptive_only', 'primary_bootstrap_seed': 123})
        prior = {'schema': 'z52-adopted-P/v1', 'mode': 'artificial_only', 'plan_hash': self.plan['plan_hash'],
            'scientific_candidate_sha256': self.candidate['sha256'],
            'original_execution_binding_sha256': gate.execution_binding(self.candidate),
            'completed_blocks': counts['P'], 'rows': counts['P'] * 2, 'review_complete': True, 'backup_complete': True,
            'original_folder': str(original_P), 'control_snapshot': secondary._control_snapshot(self.control),
            'accounting': deepcopy(secondary.HISTORICAL_ACCOUNTING)}
        for name in ('state', 'analysis', 'review', 'backup'):
            prior[name] = self.file('old-P-' + name + '.json', {'artificial_only': True, 'kind': name})
        self.original_binding = secondary.prepare_binding(self.candidate, self.plan, predecessor=prior,
            folder=self.folder, control=self.control, witness=self.root / 'old-witness', owner='artificial-executor',
            analysis_contract=self.analysis_contract)
        secondary.initialize(self.original_binding, self.candidate, self.plan, **self.args())
        if prefix:
            state = secondary.run_section(self.original_binding, self.candidate, self.plan, **self.args(),
                section_end=counts['P'] + prefix, coverage=self.old_coverage(), **self.dependencies())
            self.confirm_for(secondary, self.original_binding, state, 'old')
        block = self.plan['panels']['R'][prefix]
        config, rounds, _ = native._configuration(self.candidate, block, 'Z', {'spatial_q': self.q, 'temporal_qst': None})
        self.transport.fail_at = self.transport.calls + 5 + rounds * len(config.roles) + 1 + 6 + 1
        self.transport.mode = 'transport'
        try:
            secondary.run_section(self.original_binding, self.candidate, self.plan, **self.args(),
                section_end=counts['P'] + counts['R'], coverage=self.old_coverage(), **self.dependencies())
        except BudgetStop:
            pass
        else:
            raise AssertionError('fixture must preserve its original unknown')
        self.original_candidate = deepcopy(self.candidate)
        self.original_folder = self.folder
        review = self.file('incident-review.json', {'artificial_only': True, 'accepted': True})
        backup = self.file('incident-backup.json', {'artificial_only': True, 'full_reread': True})
        self.incident = resume.prepare_incident(self.original_candidate, self.original_binding, self.plan, review=review, backup=backup)
        self.folder = self.root / 'recovery-R00038/live'
        self.candidate['operating_proposal'] = {'artificial_only': True, 'recovery': 'R01223'}
        self.candidate = gate.seal(self.candidate)
        self.binding = resume.prepare_binding(self.candidate, self.plan, original_candidate=self.original_candidate,
            original_binding=self.original_binding, incident=self.incident, folder=self.folder, control=self.control,
            witness=self.root / 'recovery-R00038/witness', owner='artificial-executor', analysis_contract=self.analysis_contract)
        self.old_files = secondary._all_files(self.original_folder)
        self.initial_calls = self.transport.calls
        self.old_loads, self.old_selections = len(self.loads), len(self.selections)
        self.transport.fail_at, self.transport.mode = None, None

    def old_coverage(self):
        budget = secondary._budget(self.original_binding, self.plan, self.folder, existing=True)
        return {'binding_sha256': self.original_binding['sha256'], 'origin': 'artificial_fixture',
            'observed_epoch': 90, 'valid_until_epoch': 1000, 'available_usd': '100',
            'native_cost_at_observation_usd': str(budget.cost)}

    def initialize_recovery(self):
        return resume.initialize(self.binding, self.candidate, self.plan, **self.args())

    def coverage(self, amount='100'):
        budget = resume._budget(self.binding, self.plan, self.folder, existing=True)
        return {'binding_sha256': self.binding['sha256'], 'origin': 'artificial_fixture',
            'observed_epoch': 90, 'valid_until_epoch': 1000, 'available_usd': amount,
            'native_cost_at_observation_usd': str(budget.cost)}

    def run_recovery(self, end=None, *, coverage=None):
        return resume.run_section(self.binding, self.candidate, self.plan, **self.args(),
            section_end=self.binding['first_hold'] if end is None else end,
            coverage=self.coverage() if coverage is None else coverage, **self.dependencies())

    def inspect(self):
        return resume.inspect_study(self.binding, self.candidate, self.plan, **self.args())

    def confirm_for(self, module, binding, state, label):
        review = self.file(label + '-review-' + str(state['completed_blocks']) + '.json', {
            'binding_sha256': binding['sha256'], 'state_sha256': state['state_sha256'], 'accepted': True,
            'reviewer': 'artificial-independent-reviewer', 'not_implementation_author': True})
        receipt = gate.read_json(module._receipt_path(self.folder, state))
        backup = self.file(label + '-backup-' + str(state['completed_blocks']) + '.json', {
            'binding_sha256': binding['sha256'], 'state_sha256': state['state_sha256'], 'accepted': True,
            'archive_sha256': receipt['backup']['sha256'], 'members': state['evidence'],
            'full_reread': True, 'destination': 'artificial_local'})
        return module.confirm_hold(binding, self.candidate, self.plan, **self.args(), review=review, backup=backup)

    def confirm(self, state):
        return self.confirm_for(resume, self.binding, state, 'recovery')

    def finish_panel(self, panel):
        evidence = resume.analyze_panel(self.binding, self.candidate, self.plan, panel, **self.args())
        prepared = resume.prepare_panel_backup(self.binding, self.candidate, self.plan, panel,
            **self.args(), checkpoint=self.checkpoint)
        review = self.file('panel-review-' + panel + '.json', {'binding_sha256': self.binding['sha256'], 'panel': panel,
            'analysis_sha256': evidence['sha256'], 'reviewer': 'artificial-independent-reviewer',
            'not_implementation_author': True, 'accepted': True})
        remote = self.file('panel-remote-' + panel + '.json', {'artificial_only': True,
            'binding_sha256': self.binding['sha256'], 'panel': panel, 'analysis_sha256': evidence['sha256'],
            'archive_sha256': prepared['backup']['sha256'], 'members': prepared['backup']['members'],
            'full_reread': True, 'accepted': True, 'destination': 'artificial_local'})
        resume.close_panel(self.binding, self.candidate, self.plan, panel, **self.args(), review=review, remote_backup=remote)
        return gate.read_json(evidence['path'])


class RResumeTests(unittest.TestCase):
    def test_E1_complete_38_prefix_six_arms_exact_once_and_global9079(self):
        with trial_directory() as directory:
            f = RFixture(directory, prefix=38, real_global=True)
            f.initialize_recovery()
            state = f.run_recovery()
            self.assertEqual(state['completed_blocks'], 9079)
            self.assertEqual(len(state['rows']), 234)
            self.assertEqual(state['local_D_replays'], 6)
            self.assertEqual((len(f.loads), len(f.selections)), (f.old_loads, f.old_selections))
            self.assertEqual(secondary._all_files(f.original_folder), f.old_files)
            self.assertEqual(state['budget']['calls'], f.transport.calls - f.initial_calls)
            self.assertEqual((f.folder / 'provider/00001-request.json').read_bytes(),
                native._provider_files(f.original_folder, f.incident['unknown_provider_index'])['request'].read_bytes())
            self.assertEqual(len(state['generation_ids']), f.incident['known_calls'] + state['budget']['calls'])
            self.assertEqual(sum((Decimal(r['cost_usd']) for r in state['rows']), Decimal(0)),
                Decimal(f.incident['known_cost_usd']) + Decimal(state['budget']['known_cost_usd']))
            self.assertEqual(f.inspect(), state)

    def test_E2_changed_body_messages_order_plan_seed_selection_stop_before_send(self):
        for mutation in ('body', 'D-journal', 'selection', 'plan'):
            with self.subTest(mutation=mutation), trial_directory() as directory:
                f = RFixture(directory)
                if mutation == 'body':
                    path = native._provider_files(f.original_folder, f.incident['unknown_provider_index'])['request']
                    path.write_bytes(path.read_bytes() + b' ')
                elif mutation == 'D-journal':
                    path = f.original_folder / 'blocks/000000/D/journal.jsonl'
                    lines = path.read_bytes().splitlines(keepends=True)
                    path.write_bytes(b''.join([lines[0], lines[2], lines[1], *lines[3:]]))
                elif mutation == 'selection':
                    path = f.original_folder / 'blocks/000000/selection.json'
                    value = gate.read_json(path)
                    value['spatial_q'] = 'C14'
                    path.write_bytes(encoded(value))
                else:
                    f.plan['panels']['R'][0]['tie_break_seed'] += 1
                with self.assertRaises((gate.StudyStop, ValueError)):
                    f.initialize_recovery()
                self.assertEqual(f.transport.calls, f.initial_calls)
                self.assertFalse((f.control / resume.CLAIM).exists())

    def test_E3_original_ledger_provider_STOP_claim_witness_and_extra_evidence(self):
        for kind in ('ledger', 'billing', 'missing', 'extra', 'STOP', 'claim', 'witness'):
            with self.subTest(kind=kind), trial_directory() as directory:
                f = RFixture(directory)
                if kind == 'ledger': path = f.original_folder / 'budget.jsonl'
                elif kind == 'billing': path = f.original_folder / 'provider/00001-billing.json'
                elif kind == 'STOP': path = f.original_folder / 'STOP.json'
                elif kind == 'claim': path = f.control / secondary.CLAIM
                elif kind == 'witness': path = next(p for p in Path(f.original_binding['witness']).rglob('*') if p.is_file())
                elif kind == 'extra': path = f.original_folder / 'provider/EXTRA.json'
                else: path = f.original_folder / 'provider/00001-response.json'
                if kind == 'missing':
                    path.rename(path.with_suffix('.preserved-missing'))
                else:
                    path.write_bytes((path.read_bytes() if path.exists() else b'') + b' ')
                with self.assertRaises((gate.StudyStop, ValueError)):
                    f.initialize_recovery()
                self.assertEqual(f.transport.calls, f.initial_calls)

    def test_E4_one_replacement_unknown_http_billing_crash_and_F01(self):
        for mode in ('transport', 'http', 'unknown', 'duplicate', 'interrupt', 'length'):
            with self.subTest(mode=mode), trial_directory() as directory:
                f = RFixture(directory)
                f.initialize_recovery()
                f.transport.mode, f.transport.fail_at = mode, f.transport.calls + 1
                if mode == 'length':
                    state = f.run_recovery()
                    self.assertEqual(next(r for r in state['rows'] if r['arm'] == 'D')['status'], 'model_failure')
                    self.assertEqual(gate.read_json(f.folder / 'replacement.json')['maximum_replacements'], 1)
                else:
                    with self.assertRaises((BudgetStop, KeyboardInterrupt, gate.StudyStop)):
                        f.run_recovery()
                    calls = f.transport.calls
                    self.assertTrue((f.folder / 'STOP.json').exists())
                    with self.assertRaises((gate.StudyStop, RuntimeError)):
                        f.run_recovery()
                    self.assertEqual(f.transport.calls, calls)
                self.assertEqual(secondary._all_files(f.original_folder), f.old_files)

    def test_E5_same_lock_canonical_claim_single_writer_stale_witness(self):
        with trial_directory() as directory:
            f = RFixture(directory)
            with native.study_lock(f.control):
                with self.assertRaises((gate.StudyStop, RuntimeError)):
                    f.initialize_recovery()
            f.initialize_recovery()
            with self.assertRaises(gate.StudyStop):
                f.initialize_recovery()
            alternate = deepcopy(f.binding)
            alternate['folder'] = str(f.root / 'alternate')
            alternate = gate.seal(alternate)
            with self.assertRaises((gate.StudyStop, RuntimeError)):
                resume.initialize(alternate, f.candidate, f.plan, folder=f.root / 'alternate', control=f.control, clock=f.clock)
            (f.folder / 'sections/000000.json').write_bytes(encoded({'section_id': 'section-3', 'status': 'admitted'}))
            with self.assertRaises((gate.StudyStop, RuntimeError, RecoveryFault)):
                f.run_recovery()
            self.assertEqual(f.transport.calls, f.initial_calls)

    def test_E6_cost_reserve_once_account_source_tariff_and_calendar_gates(self):
        with trial_directory() as directory:
            f = RFixture(directory)
            f.initialize_recovery()
            before = resume.accounting_view(f.binding, Decimal(0))
            original = secondary.accounting_view(f.binding['predecessor'], Decimal(0))
            self.assertEqual(Decimal(original['available_usd']['secondary']) - Decimal(before['available_usd']['secondary']),
                Decimal(f.incident['known_cost_usd']) + Decimal('.14'))
            self.assertEqual(before['original_R_held_reservation_usd'], '0.14')
            self.assertEqual(Decimal(before['new_known_cost_usd']), Decimal(f.incident['known_cost_usd']))
            self.assertEqual(Decimal(before['known_study_cost_usd']),
                Decimal(secondary.HISTORICAL_ACCOUNTING['P_known_usd']) + Decimal(f.incident['known_cost_usd']))
            self.assertIsNone(before['actual_total_cost_usd'])
            with self.assertRaises(gate.StudyStop):
                f.run_recovery(coverage=f.coverage('5.04'))
            with self.assertRaises(gate.StudyStop):
                f.run_recovery(coverage={**f.coverage(), 'valid_until_epoch': 99})
            f.clock = lambda: 1001
            with self.assertRaises(gate.StudyStop):
                f.run_recovery()
            self.assertEqual(f.transport.calls, f.initial_calls)

    def test_E7_first_hold_review_remote_then_original_R_T_F_closures(self):
        with trial_directory() as directory:
            f = RFixture(directory)
            f.initialize_recovery()
            state = f.run_recovery()
            endR = f.plan['counts']['P'] + f.plan['counts']['R']
            with self.assertRaises((gate.StudyStop, FileNotFoundError)):
                f.run_recovery(endR)
            with self.assertRaises((gate.StudyStop, ValueError)):
                resume.collect_panel(f.binding, f.candidate, f.plan, 'R', **f.args())
            f.confirm(state)
            state = f.run_recovery(endR)
            f.confirm(state)
            analysis = f.finish_panel('R')
            self.assertEqual(analysis['affected_cost_endpoints'], ['R03', 'R08'])
            for panel, end in (('T', endR + 1), ('F', endR + 2)):
                state = f.run_recovery(end)
                f.confirm(state)
                f.finish_panel(panel)
            self.assertTrue(state['complete'])
            self.assertEqual(secondary._all_files(f.original_folder), f.old_files)

    def test_E8_known_cost_envelope_and_safe_exception_chain_no_payload(self):
        from study_preparation.final_analysis import analyze_panel
        with trial_directory() as directory:
            f = RFixture(directory)
            f.initialize_recovery()
            first = f.run_recovery()
            f.confirm(first)
            state = f.run_recovery(f.plan['counts']['P'] + f.plan['counts']['R'])
            f.confirm(state)
            record = f.finish_panel('R')
            self.assertEqual(record['original_analysis'], analyze_panel(f.plan, 'R', state['rows'], bootstrap_seed=123))
            self.assertIsNone(record['original_R_unknown']['cost_usd'])
            self.assertFalse(record['zero_cost_imputation'])
            self.assertFalse(record['continuous_interrupted_D_latency_available'])
            for name in ('selection.json', 'spatial-measurement.json'):
                self.assertEqual((f.folder / 'blocks/000000' / name).read_bytes(), (f.original_folder / 'blocks/000000' / name).read_bytes())
            error = OSError(5, 'SECRET_PAYLOAD_MUST_NOT_APPEAR')
            chain = resume.safe_exception_chain(error, f.clock)
            self.assertEqual(chain['exception_classes'][0]['errno'], 5)
            self.assertNotIn('SECRET', json.dumps(chain))


if __name__ == '__main__':
    unittest.main()
