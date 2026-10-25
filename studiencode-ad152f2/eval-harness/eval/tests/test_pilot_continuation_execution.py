"""R3 isolated synthetic integration with actual independent auditor; never imports the live recovery operator."""
from pathlib import Path
from copy import deepcopy
from communication_pruning.pilot_continuation_calendar import make_schedule
import importlib.util

_AUDIT_PATH = Path(__file__).resolve().parents[1] / 'runs/Z42-PILOT-001/calendar-r3/independent-audit/audit.py'

def actual_auditor():
    spec = importlib.util.spec_from_file_location('z42_r3_actual_auditor', _AUDIT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
from datetime import datetime, timedelta
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
from communication_pruning.pilot_continuation_execution import run_window, continuation_status
from communication_pruning.pilot_continuation_guard import (ContinuationSession, PACK_REL, OLD_CALL, OLD_STATE,
    OLD_STOP, CLAIM, CHECKPOINT, checksum, read, save, snapshot)
from tests.study_fixture import FakeTransport
from tests.test_pilot_calendar import fixture


class AuditFailure(ValueError):
    def __init__(self, message):
        self.report = {'verified': False, 'findings': [message], 'complete_nested_evidence': {'codes': [1, 2, 3]}}
        super().__init__(message)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.pack = self.root / PACK_REL
        self.base = self.pack / 'calendar-r3/production'
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
                        'calendar-r2/START-ACCEPTANCE.json', 'repair-r1/audit/audit.py', 'calendar-r3/production/operate.py', 'calendar-r3/independent-audit/audit.py']
        sources = {}
        for name in source_names:
            path = self.pack / name
            save(path, {'synthetic_source_binding': name})
            sources[str(path.relative_to(self.root))] = checksum(path)
        for name in ('pilot_execution', 'pilot_continuation_execution', 'pilot_continuation_guard', 'pilot_continuation_calendar'):
            path = self.root / 'eval-harness/eval/communication_pruning' / (name + '.py')
            save(path, {'synthetic_source_binding': name})
            sources[str(path.relative_to(self.root))] = checksum(path)
        sources[str(PACK_REL / 'calendar-r2/preparation/calendar.json')] = checksum(self.pack / 'calendar-r2/preparation/calendar.json')
        self.schedule = make_schedule(self.plan, acceptance_utc='2026-09-14T11:30:00+00:00',
                                      technical_ready_utc='2026-09-14T11:40:00+00:00')
        self.now = window_interval(self.schedule['sections'][0])[0]
        values = {'calendar-r3/schedule.json': self.schedule,
                  'calendar-r3/AUTHOR-APPROVAL.json': {'author_decision': 'D-061', 'utc': self.schedule['anchor']['acceptance_utc']},
                  'calendar-r3/TECHNICAL-READY.json': {'status': 'passed_calendar_independent_checks', 'utc': self.schedule['anchor']['technical_ready_utc']}}
        for name, value in values.items():
            path = self.pack / name
            save(path, value)
            sources[str(path.relative_to(self.root))] = checksum(path)
        for name in ('project/ENTWICKLUNGSSTEUERUNG.json', 'project/dsr/Z42-FORTSETZUNGSPLAN-R3.md',
                     str(PACK_REL / 'calendar-r3/production/original-development-control.json')):
            path = self.root / name
            save(path, {'synthetic_control_binding': name})
            sources[name] = checksum(path)
        backup = snapshot(self.root, self.base / 'preactivation-backup',
                          [self.root / name for name in self.original], lambda: self.now)
        sources[str(backup.relative_to(self.root))] = checksum(backup)
        self.contract = {'schema': 'z42-pilot-continuation/v1', 'schedule_sha256': self.schedule['sha256'], 'status': 'ready_for_separate_acceptance',
            'phase_id': 'Z42-PILOT-001', 'work_item': 'Z42-PILOT', 'author_decision': 'D-061',
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
        save(self.base / 'START-ACCEPTANCE.json', {'status': 'passed_C1_C4_C5_entry',
            'contract_sha256': checksum(self.base / 'contract.json'), 'reviewer': 'fixture-reviewer',
            'implementer': 'fixture-builder', 'criteria': {n: 'passed' for n in ('C1','C2','C3','C4','C5-entry')},
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

    def audit(self, plan, folder, state, *, schedule):
        self.audits += 1
        result = actual_auditor().audit(plan, folder, state, schedule=schedule)
        self.assertTrue(result['verified'])
        return result

    def session(self, **changes):
        args = dict(root=self.root, contract_path=self.base / 'contract.json',
            acceptance_path=self.base / 'START-ACCEPTANCE.json', original_guard=lambda: None,
            original_start_guard=self.deep_guard, auditor=self.audit, clock=lambda: self.now, synthetic=True)
        args.update(changes)
        return ContinuationSession(**args)

    def checkpoint(self, stage, state):
        save(self.active.current / (stage + '-STATE.json'), state)
        audited = self.audit(self.plan, self.live, state, schedule=self.schedule)
        save(self.active.current / (stage + '-AUDIT.json'), audited)
        receipt = snapshot(self.root, self.base / 'checkpoints' / stage, self.active.snapshot_paths(), lambda: self.now)
        return {'verified': True, 'sha256': checksum(receipt)}

    def run_remainder(self, **changes):
        self.active = self.session()
        args = dict(bindings=self.bindings, window_id='R3-E01', folder=self.live, control=self.control,
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
        waiting = continuation_status(self.plan, self.manifest, self.ids, bindings=self.bindings, recovery=self.session())
        self.assertEqual((waiting['status'], waiting['next_window_id']), ('not_yet_due', 'R3-E02'))
        self.now = window_interval(self.schedule['sections'][1])[0]
        second = self.run_remainder(window_id='R3-E02')
        self.assertEqual((second['completed_pairs_before'], second['completed_pairs']), (30, 60))
        self.assertEqual(self.transport.calls, 720)
        self.assertEqual(self.audits, 3)
        for pid in ('P0002', 'P0031'):
            receipt = read(self.live / 'pairs' / (pid + '-complete.json'))
            self.assertEqual(receipt['schedule_sha256'], self.schedule['sha256'])
            self.assertEqual(receipt['pair'], self.plan['pairs'][int(pid[1:])-1])
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
        def fail(*args, **kwargs):
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
        start, cutoff, end = window_interval(self.schedule['sections'][0])
        for moment in (datetime.fromisoformat(self.schedule['anchor']['t_utc']) - timedelta(microseconds=1), cutoff, end, end + timedelta(seconds=1)):
            self.now = moment
            with self.assertRaises(ValueError):
                self.session().activate()
        self.now = cutoff - timedelta(microseconds=1)
        self.session().activate()

    def test_expired_after_activation_does_not_start_p0002(self):
        self.session().activate()
        self.now = window_interval(self.schedule['sections'][0])[1]
        with self.assertRaises(ValueError):
            self.run_remainder()
        self.assertFalse((self.live / 'pairs/P0002-started.json').exists())

    def test_preactivation_before_S_is_local_and_early_pair_start_blocks(self):
        self.now = datetime.fromisoformat(self.schedule['anchor']['t_utc'])
        self.session().activate()
        self.assertEqual(self.transport.calls, 12)
        self.assertEqual(self.audits, 1)
        with self.assertRaises(ValueError):
            self.run_remainder()
        self.assertFalse((self.live / 'pairs/P0002-started.json').exists())
        self.assertEqual(self.transport.calls, 12)

    def test_pair_overrun_retains_new_pair_and_blocks_next(self):
        self.session().activate()
        def slow_loader(task_id):
            loaded = self.loader(task_id)
            self.now = window_interval(self.schedule['sections'][0])[2] + timedelta(seconds=1)
            return loaded
        with self.assertRaisesRegex(PilotStop, 'exceeded'):
            self.run_remainder(loader=slow_loader)
        self.assertTrue((self.live / 'pairs/P0002-complete.json').exists())
        self.assertFalse((self.live / 'pairs/P0003-started.json').exists())
        self.assertEqual(self.transport.calls, 24)
        with self.assertRaises(PilotStop):
            self.session().guard()

    def test_schedule_or_anchor_change_blocks_even_with_new_session(self):
        for name in ('calendar-r3/schedule.json', 'calendar-r3/TECHNICAL-READY.json',
                     'calendar-r3/AUTHOR-APPROVAL.json'):
            path = self.pack / name
            original = path.read_bytes()
            self.mutate(path)
            with self.assertRaises(PilotStop):
                self.session().activate()
            path.write_bytes(original)

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
        for path in (self.live / 'checkpoints/R3-E01-complete.json',
                     self.base / 'checkpoints/R3-E01-complete/source.zip',
                     self.base / 'attempts/R3-E01/RETURN.json'):
            old = path.read_bytes()
            self.mutate(path)
            with self.assertRaises(PilotStop):
                self.session().guard(deep=True)
            with self.assertRaises(PilotStop):
                self.active.guard(deep=True)
            path.write_bytes(old)
        archive = self.base / 'checkpoints/R3-E01-complete/source.zip'
        old = archive.read_bytes()
        archive.unlink()
        with self.assertRaises((PilotStop, FileNotFoundError)):
            self.session().guard(deep=True)
        with self.assertRaises((PilotStop, FileNotFoundError)):
            self.session().snapshot_paths()
        archive.write_bytes(old)

    def test_three_checkpoint_snapshots_keep_linear_membership_and_prior_proofs(self):
        self.session().activate()
        active = self.session()
        required = [self.base / 'snapshot-fixture/AUDIT.json', self.base / 'snapshot-fixture/ERROR.json',
                    self.live / 'provider/00001-response.json', self.live / 'budget.jsonl']
        save(required[0], {'synthetic_audit': True})
        save(required[1], {'synthetic_preserved_error': True})
        baseline = {str(p.relative_to(self.root)) for p in active.snapshot_paths()}
        expected = set(baseline)
        proofs, counts = [], []
        for index in range(1, 4):
            directory = self.base / 'checkpoints' / f'R3-E{index:02d}-complete'
            receipt_path = snapshot(self.root, directory, active.snapshot_paths(), lambda: self.now)
            members = set(read(directory / 'MANIFEST.json')['members'])
            self.assertEqual(members, expected)
            self.assertTrue({str(p.relative_to(self.root)) for p in required} <= members)
            self.assertFalse(any(name.endswith('/source.zip') for name in members))
            counts.append(len(members))
            proofs.append({'archive': str((directory / 'source.zip').relative_to(self.root)),
                           'archive_sha256': checksum(directory / 'source.zip'),
                           'members': sorted(members)})
            expected.update(str((directory / name).relative_to(self.root))
                            for name in ('MANIFEST.json', 'VERIFICATION.json'))
        self.assertEqual(counts, [len(baseline), len(baseline) + 2, len(baseline) + 4])
        archive = self.root / proofs[0]['archive']
        original = archive.read_bytes()
        self.mutate(archive)
        with self.assertRaises(PilotStop):
            active.snapshot_paths()
        archive.write_bytes(original)
        archive.unlink()
        with self.assertRaises((PilotStop, FileNotFoundError)):
            active.snapshot_paths()
        archive.write_bytes(original)
        for proof in proofs:
            self.assertEqual(checksum(self.root / proof['archive']), proof['archive_sha256'])
        import os
        output = os.environ.get('Z42_R3_CHECKPOINT_EVIDENCE')
        evidence = {'synthetic': True, 'snapshots': 3, 'member_counts': counts,
                    'increment_per_snapshot': 2, 'nested_checkpoint_archives': 0,
                    'required_raw_audit_error_evidence_retained': True,
                    'changed_and_missing_previous_archives_rejected': True, 'proofs': proofs}
        if output:
            with Path(output).open('x') as stream:
                stream.write(json.dumps(evidence, sort_keys=True, indent=2) + '\n')
        print('Checkpoint member counts:', counts, '; no nested checkpoint archives; old proofs remain required.')

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
        self.assertTrue(any(p['schema'] == 'z42-continuation-stop-backup-failed/v1' for p in errors))
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
            return continuation_status(self.plan, self.manifest, self.ids, bindings=self.bindings, recovery=self.session())
        self.assertEqual(status()['status'], 'due')
        self.assertEqual(status()['completed_pairs'], 1)
        self.assertEqual(status()['budget']['calls'], 12)
        self.now = window_interval(self.schedule['sections'][0])[1]
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
