"""N5 isolated synthetic integration; never imports the live recovery operator."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from decimal import Decimal
import json
import tempfile
import unittest

from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference, digest
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.pilot_calendar import make_calendar, window_interval
from communication_pruning.pilot_execution import run_window as original_run, pilot_lock, PilotStop
from communication_pruning.pilot_recovery_execution import run_window, recovery_status
from communication_pruning.pilot_recovery_guard import (RecoverySession, PACK_REL, OLD_CALL, OLD_STATE,
    OLD_STOP, CLAIM, CHECKPOINT, checksum, read, save, snapshot)
from tests.study_fixture import FakeTransport
from tests.test_pilot_calendar import fixture


class AuditFailure(ValueError):
    def __init__(self, message):
        self.report = {'verified': False, 'findings': [message], 'complete_nested_evidence': {'codes': [1, 2, 3]}}
        super().__init__(message)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.pack = self.root / PACK_REL
        self.base = self.pack / 'repair-r1/recovery'
        self.base.mkdir(parents=True)
        self.live, self.control = self.pack / 'live', self.pack / 'control'
        self.manifest, self.ids, self.bindings = fixture()
        self.plan = make_calendar(self.manifest, self.ids, bindings=self.bindings)
        self.now = window_interval(self.plan['windows'][0])[0] + timedelta(minutes=40)
        self.transport = FakeTransport()
        self.loaded, self.deep_calls, self.audits = [], 0, 0
        save(self.pack / 'calendar-r2/preparation/calendar.json', self.plan)
        save(self.pack / OLD_CALL, {'window': 'W01', 'first_pair': True, 'automatic_retry': False})
        def failed_hold(stage, state):
            save(self.pack / OLD_STATE, state)
            raise AuditFailure('synthetic reproduction of original calendar audit failure')
        with self.assertRaises(AuditFailure):
            original_run(self.plan, self.manifest, self.ids, bindings=self.bindings, window_id='W01',
                folder=self.live, control=self.control, loader=self.loader, selector=lambda _: 'C14',
                transport=self.transport, guard=lambda: None, checkpoint=failed_hold,
                clock=lambda: self.now, synthetic=True, stop_after_first_pair=True)
        save(self.pack / OLD_STOP, {'error_type': 'AuditFailure', 'automatic_retry': False})
        self.original = self.inventory()
        self.prefix = (self.live / 'budget.jsonl').read_bytes()
        last = read_lines(self.prefix)[-1]
        source_names = ['operate.py', 'independent-audit/audit.py', 'calendar-r2/preparation/contract.json',
                        'calendar-r2/START-ACCEPTANCE.json', 'repair-r1/audit/audit.py', 'repair-r1/recovery/operate.py']
        sources = {}
        for name in source_names:
            path = self.pack / name
            save(path, {'synthetic_source_binding': name})
            sources[str(path.relative_to(self.root))] = checksum(path)
        for name in ('pilot_execution', 'pilot_recovery_execution', 'pilot_recovery_guard'):
            path = self.root / 'eval-harness/eval/communication_pruning' / (name + '.py')
            save(path, {'synthetic_source_binding': name})
            sources[str(path.relative_to(self.root))] = checksum(path)
        sources[str(PACK_REL / 'calendar-r2/preparation/calendar.json')] = checksum(self.pack / 'calendar-r2/preparation/calendar.json')
        backup = snapshot(self.root, self.base / 'preactivation-backup',
                          [self.root / name for name in self.original], lambda: self.now)
        sources[str(backup.relative_to(self.root))] = checksum(backup)
        self.contract = {'schema': 'z42-pilot-recovery/v1', 'status': 'ready_for_separate_acceptance',
            'phase_id': 'Z42-PILOT-001', 'work_item': 'Z42-PILOT', 'author_decision': 'D-059',
            'phase_root': str(self.pack), 'synthetic': True, 'source_files': sources,
            'anchors': {name: checksum(self.pack / name) for name in ('live/halted.json', OLD_CALL, OLD_STATE, OLD_STOP, CLAIM)},
            'preserved_files': {str(Path(name).relative_to(PACK_REL)): value for name, value in self.original.items()
                                if not name.endswith('/budget.jsonl') and not name.endswith('.lock')},
            'budget_prefix': {'bytes': len(self.prefix), 'lines': len(self.prefix.splitlines()),
                'sha256': checksum(self.live / 'budget.jsonl'), 'last_sequence': last['sequence'], 'last_chain': last['sha256']},
            'expected_cost_usd': read(self.pack / OLD_STATE)['budget']['known_cost_usd'],
            'preactivation_backup': str(backup.relative_to(self.root))}
        save(self.base / 'contract.json', self.contract)
        evidence = self.base / 'offline-test-review.json'
        save(evidence, {'synthetic_test_fixture_only': True})
        save(self.base / 'START-ACCEPTANCE.json', {'status': 'passed_N1_N5_offline_review',
            'contract_sha256': checksum(self.base / 'contract.json'), 'reviewer': 'fixture-reviewer',
            'implementer': 'fixture-builder', 'criteria': {n: 'passed' for n in ('N1','N2','N3','N4','N5-offline')},
            'evidence': {str(evidence.relative_to(self.root)): checksum(evidence)}})

    def inventory(self):
        return {str(p.relative_to(self.root)): checksum(p) for folder in (self.live, self.control, self.pack / 'window-evidence')
                for p in folder.rglob('*') if p.is_file()}

    def loader(self, task_id):
        self.loaded.append(task_id)
        public = 'task-' + digest([self.manifest['source_hashes']['train'], task_id])
        return TaskInput(public, 'Synthetic question?', ('Synthetic passage.',)), AnswerReference(public, ('synthetic',))

    def deep_guard(self):
        self.deep_calls += 1

    def audit(self, plan, folder, state):
        self.audits += 1
        self.assertEqual(state['completed_pairs'], 1)
        self.assertEqual(state['budget']['calls'], 12)
        self.assertEqual(folder, self.live)
        return {'verified': True, 'plan_sha256': plan['sha256'], 'fixture_only': True}

    def session(self, **changes):
        args = dict(root=self.root, contract_path=self.base / 'contract.json',
            acceptance_path=self.base / 'START-ACCEPTANCE.json', original_guard=lambda: None,
            original_start_guard=self.deep_guard, auditor=self.audit, clock=lambda: self.now, synthetic=True)
        args.update(changes)
        return RecoverySession(**args)

    def checkpoint(self, stage, state):
        save(self.active.current / (stage + '-STATE.json'), state)
        receipt = snapshot(self.root, self.base / 'checkpoints' / stage, self.active.snapshot_paths(), lambda: self.now)
        return {'verified': True, 'sha256': checksum(receipt)}

    def run_remainder(self, **changes):
        self.active = self.session()
        args = dict(bindings=self.bindings, window_id='W01', folder=self.live, control=self.control,
            loader=self.loader, selector=lambda _: 'C14', transport=self.transport, guard=lambda: None,
            checkpoint=self.checkpoint, recovery=self.active, clock=lambda: self.now, synthetic=True)
        args.update(changes)
        return run_window(self.plan, self.manifest, self.ids, **args)

    def mutate(self, path):
        path.write_bytes(path.read_bytes() + b' ')

    def test_full_window_continues_p0002_call13_preserves_every_old_byte_and_budget(self):
        self.session().activate()
        self.assertEqual(self.audits, 1)
        self.loaded.clear()
        result = self.run_remainder()
        self.assertEqual((result['completed_pairs_before'], result['completed_pairs']), (1, 30))
        self.assertEqual(self.loaded[0], self.plan['pairs'][1]['task_id'])
        self.assertEqual(len(self.loaded), 29)
        self.assertEqual(self.transport.calls, 360)
        self.assertTrue((self.live / 'provider/00013-binding.json').is_file())
        self.assertEqual(read(self.live / 'provider/00013-binding.json')['attempt_id'].split(':')[0][-5:], 'S0003')
        self.assertTrue((self.live / 'budget.jsonl').read_bytes().startswith(self.prefix))
        for name, expected in self.original.items():
            if not name.endswith('/budget.jsonl'):
                self.assertEqual(checksum(self.root / name), expected, name)
        self.session().guard(deep=True)
        self.assertFalse((self.pack / OLD_CALL).with_name('RETURN.json').exists())
        self.assertEqual(self.deep_calls, 2)
        waiting = recovery_status(self.plan, self.manifest, self.ids, bindings=self.bindings, recovery=self.session())
        self.assertEqual((waiting['status'], waiting['next_window_id']), ('not_yet_due', 'W02'))
        self.now = window_interval(self.plan['windows'][1])[0]
        second = self.run_remainder(window_id='W02')
        self.assertEqual((second['completed_pairs_before'], second['completed_pairs']), (30, 60))
        self.assertEqual(self.transport.calls, 720)
        self.assertTrue((self.live / 'budget.jsonl').read_bytes().startswith(self.prefix))
        self.session().guard(deep=True)

    def test_mutated_stop_firstpair_claim_calendar_or_source_blocks(self):
        paths = ['live/halted.json', OLD_STOP, OLD_STATE, CLAIM, 'live/pairs/P0001-complete.json',
                 'live/provider/00001-response.json', 'calendar-r2/preparation/calendar.json', 'operate.py']
        for name in paths:
            with self.subTest(name=name):
                path = self.pack / name
                old = path.read_bytes()
                self.mutate(path)
                with self.assertRaises(PilotStop):
                    self.session().activate()
                path.write_bytes(old)
                self.assertFalse((self.base / 'activation').exists())

    def test_shortened_foreign_or_open_ledger_blocks(self):
        path = self.live / 'budget.jsonl'
        for value in (self.prefix[:-1], self.prefix[400:], self.prefix.replace(b'4.00', b'8.00', 1), self.prefix + b'{}\n'):
            with self.subTest(length=len(value)):
                path.write_bytes(value)
                with self.assertRaises((PilotStop, BudgetStop, KeyError)):
                    self.session().activate()
        path.write_bytes(self.prefix)

    def test_wrong_directory_and_symlink_rejected(self):
        with self.assertRaises(PilotStop):
            self.session(root=self.root / 'other')
        path = self.live / 'provider/00001-response.json'
        old = path.read_bytes()
        elsewhere = self.root / 'copy.json'
        elsewhere.write_bytes(old)
        path.unlink()
        path.symlink_to(elsewhere)
        with self.assertRaises(PilotStop):
            self.session().activate()

    def test_new_stop_unknown_call_or_started_pair_blocks(self):
        paths = ['window-evidence/unknown/CALL.json', 'window-evidence/new/STOP.json', 'live/pairs/P0002-started.json']
        for name in paths:
            path = self.pack / name
            save(path, {'unexpected': True})
            with self.assertRaises(PilotStop):
                self.session().activate()
            path.unlink()

    def test_duplicate_activation_is_rejected_without_rewriting_any_file(self):
        self.session().activate()
        before = {str(p): checksum(p) for p in self.pack.rglob('*') if p.is_file()}
        with self.assertRaises(PilotStop):
            self.session().activate()
        after = {str(p): checksum(p) for p in self.pack.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_failed_reaudit_is_additive_and_permanently_blocking(self):
        def fail(*args):
            raise AuditFailure('new audit failure')
        with self.assertRaises(AuditFailure):
            self.session(auditor=fail).activate()
        self.assertTrue(list((self.base / 'errors').glob('*.json')))
        with self.assertRaises(PilotStop):
            self.session().activate()
        self.assertFalse((self.base / 'activation/ACTIVATED.json').exists())
        errors = [read(p) for p in (self.base / 'errors').glob('*.json')]
        self.assertEqual(errors[0]['audit_report']['complete_nested_evidence'], {'codes': [1, 2, 3]})
        self.assertEqual(len(list((self.base / 'stop-snapshots').glob('*/VERIFICATION.json'))), 1)

    def test_partial_activation_missing_hold_and_changed_checkpoint_backup_block(self):
        self.session().activate()
        for path in (self.base / 'activation/CONTROL-HOLD.json', self.pack / CHECKPOINT,
                     self.base / 'activation/activation-snapshot/source.zip'):
            old = path.read_bytes()
            self.mutate(path)
            with self.assertRaises(PilotStop):
                self.session().guard(deep=True)
            path.write_bytes(old)
        (self.base / 'activation/ACTIVATED.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.session().guard()

    def test_existing_lock_blocks_activation_and_execution(self):
        with pilot_lock(self.control):
            with self.assertRaises(PilotStop):
                self.session().activate()
        self.session().activate()
        with pilot_lock(self.control):
            with self.assertRaises(PilotStop):
                self.run_remainder()
        self.assertFalse((self.base / 'attempts').exists())

    def test_early_cutoff_and_end_do_not_activate(self):
        start, cutoff, end = window_interval(self.plan['windows'][0])
        for moment in (start - timedelta(microseconds=1), cutoff, end, end + timedelta(seconds=1)):
            self.now = moment
            with self.assertRaises(ValueError):
                self.session().activate()
        self.now = cutoff - timedelta(microseconds=1)
        self.session().activate()

    def test_expired_after_activation_does_not_start_p0002(self):
        self.session().activate()
        self.now = window_interval(self.plan['windows'][0])[1]
        with self.assertRaises(ValueError):
            self.run_remainder()
        self.assertFalse((self.live / 'pairs/P0002-started.json').exists())

    def test_unknown_provider_result_keeps_reserve_and_new_stop(self):
        self.session().activate()
        self.transport.fail_at, self.transport.mode = 13, 'unknown'
        with self.assertRaises(BudgetStop):
            self.run_remainder()
        self.assertEqual(self.transport.calls, 13)
        self.assertTrue(list((self.base / 'errors').glob('*.json')))
        self.assertTrue((self.live / 'budget.jsonl').read_bytes().startswith(self.prefix))
        self.assertEqual(read_lines((self.live / 'budget.jsonl').read_bytes())[-1]['usage']['cost_usd'], None)
        with self.assertRaises(PilotStop):
            self.run_remainder()
        self.assertEqual(self.transport.calls, 13)

    def test_later_checkpoint_and_archive_are_bound_before_next_window(self):
        self.session().activate()
        self.run_remainder()
        for path in (self.live / 'checkpoints/W01-complete.json',
                     self.base / 'checkpoints/W01-complete/source.zip',
                     self.base / 'attempts/W01/RETURN.json'):
            old = path.read_bytes()
            self.mutate(path)
            with self.assertRaises(PilotStop):
                self.session().guard(deep=True)
            with self.assertRaises(PilotStop):
                self.active.guard(deep=True)
            path.write_bytes(old)

    def test_missing_acceptance_and_wrong_reviewer_block(self):
        path = self.base / 'START-ACCEPTANCE.json'
        value = read(path)
        for changed in ({**value, 'status': 'pending'}, {**value, 'reviewer': 'fixture-builder'}):
            path.write_text(__import__('json').dumps(changed))
            with self.assertRaises(PilotStop):
                self.session().activate()

    def test_later_audit_failure_preserves_full_report_and_final_stop_backup(self):
        self.session().activate()
        def failed_checkpoint(stage, state):
            raise AuditFailure('synthetic later audit failure')
        with self.assertRaises(AuditFailure):
            self.run_remainder(checkpoint=failed_checkpoint)
        error_paths = list((self.base / 'errors').glob('*.json'))
        self.assertEqual(read(error_paths[0])['audit_report']['findings'], ['synthetic later audit failure'])
        receipts = list((self.base / 'stop-snapshots').glob('*/VERIFICATION.json'))
        self.assertEqual(len(receipts), 1)
        entries = read(self.root / read(receipts[0])['manifest'])['members']
        report_path = self.live / 'reports/0002.json'
        self.assertEqual(entries[str(report_path.relative_to(self.root))]['sha256'], checksum(report_path))
        self.assertEqual(entries[str(error_paths[0].relative_to(self.root))]['sha256'], checksum(error_paths[0]))

    def test_stop_backup_failure_does_not_replace_original_audit_error(self):
        self.session().activate()
        save(self.base / 'stop-snapshots', {'fixture_blocks_backup_directory': True})
        def failed_loader(task):
            raise AuditFailure('original failure must survive backup failure')
        with self.assertRaisesRegex(AuditFailure, 'original failure must survive'):
            self.run_remainder(loader=failed_loader)
        errors = [read(p) for p in (self.base / 'errors').glob('*.json')]
        self.assertTrue(any(p['schema'] == 'z42-recovery-stop-backup-failed/v1' for p in errors))
        self.assertTrue(any(p.get('audit_report', {}).get('findings') == ['original failure must survive backup failure']
                            for p in errors if p.get('audit_report')))

    def test_cumulative_cap_reserves_old_cost_before_any_new_dispatch(self):
        self.session().activate()
        def expensive(endpoint, body=None):
            status, raw = self.transport(endpoint, body)
            value = json.loads(raw)
            value['usage']['cost'] = '0.14'
            return status, json.dumps(value).encode()
        with self.assertRaises(BudgetStop):
            self.run_remainder(transport=expensive)
        self.assertEqual(self.transport.calls, 12 + 28)
        report = read(self.live / 'reports/0002.json')
        self.assertEqual(Decimal(report['budget']['known_cost_usd']), Decimal(self.contract['expected_cost_usd']) + Decimal('3.92'))
        self.assertTrue((self.live / 'budget.jsonl').read_bytes().startswith(self.prefix))

    def test_regular_reserved_transport_guard_does_not_demand_completed_ledger(self):
        self.session().activate()
        checked = []
        def reserved_transport(endpoint, body=None):
            if body is not None:
                last = read_lines((self.live / 'budget.jsonl').read_bytes())[-1]
                self.assertEqual(last['kind'], 'reserved')
                self.assertEqual(last['reservation_usd'], '0.14')
                self.active.guard()
                checked.append(last['attempt_id'])
            return self.transport(endpoint, body)
        self.run_remainder(transport=reserved_transport)
        self.assertEqual(len(checked), 348)
        self.assertEqual(self.deep_calls, 2)

    def test_read_only_status_uses_verified_prefix_and_time_without_dispatch(self):
        self.session().activate()
        before = {str(p): checksum(p) for p in self.pack.rglob('*') if p.is_file()}
        def status():
            return recovery_status(self.plan, self.manifest, self.ids, bindings=self.bindings, recovery=self.session())
        self.assertEqual(status()['status'], 'due')
        self.assertEqual(status()['completed_pairs'], 1)
        self.assertEqual(status()['budget']['calls'], 12)
        self.now = window_interval(self.plan['windows'][0])[1]
        self.assertEqual((status()['status'], status()['reason']), ('stopped', 'missed_window'))
        self.assertEqual(self.transport.calls, 12)
        after = {str(p): checksum(p) for p in self.pack.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_unbound_or_incomplete_preactivation_backup_blocks(self):
        empty = snapshot(self.root, self.base / 'empty-backup', [], lambda: self.now)
        self.contract['preactivation_backup'] = str(empty.relative_to(self.root))
        contract_path, acceptance_path = self.base / 'contract.json', self.base / 'START-ACCEPTANCE.json'
        accepted = read(acceptance_path)
        for bound in (False, True):
            if bound:
                self.contract['source_files'][str(empty.relative_to(self.root))] = checksum(empty)
            contract_path.write_text(json.dumps(self.contract))
            accepted['contract_sha256'] = checksum(contract_path)
            acceptance_path.write_text(json.dumps(accepted))
            with self.assertRaises(PilotStop):
                self.session().activate()
        self.assertFalse((self.base / 'activation').exists())


def read_lines(raw):
    from communication_pruning.failure_policy import strict_json
    return [strict_json(line) for line in raw.splitlines()]


if __name__ == '__main__':
    unittest.main()
