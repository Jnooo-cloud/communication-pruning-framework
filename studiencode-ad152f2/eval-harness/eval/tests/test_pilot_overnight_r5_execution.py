"""R5 changed-boundary tests; real synthetic R3 and R4 activation precedes each R5 linkage."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import importlib.util
import json
import unittest

from communication_pruning.data import digest
from communication_pruning.pilot_calendar import window_interval
from communication_pruning.pilot_overnight_r5_calendar import make_schedule, validate_schedule
from communication_pruning.pilot_overnight_r5_execution import run_window, overnight_status
from communication_pruning.pilot_overnight_r5_guard import (OvernightSession, PACK_REL, PRIOR_TREES, PRIOR_FIXED, PRIOR_NIGHT_TREES,
    CONTROL_REL, CONTROL_ORIGINAL, CONTROL_R3, CONTROL_R4, R3_PLAN, R4_PLAN, R5_PLAN, CHECKPOINT, OLD_STATE,
    checksum, read, save, snapshot, check_original_files)
from communication_pruning.pilot_execution import PilotStop
from tests import test_pilot_overnight_execution as prior_tests

AUDIT = Path(__file__).resolve().parents[1] / 'runs/Z42-PILOT-001/calendar-r5/independent-audit/audit.py'


def overwrite(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


class OvernightTests(unittest.TestCase):
    def setUp(self):
        self.prior = prior_tests.OvernightTests('runTest')
        self.prior.setUp()
        self.addCleanup(self.prior.doCleanups)
        self.prior.session().activate()
        self.prior.session().guard(deep=True)
        for name in ('root', 'pack', 'live', 'control', 'manifest', 'ids', 'bindings', 'plan', 'transport', 'prefix'):
            setattr(self, name, getattr(self.prior, name))
        self.base = self.pack / 'calendar-r5/production'
        self.base.mkdir(parents=True)
        (self.root / CONTROL_R4).write_bytes((self.root / CONTROL_REL).read_bytes())
        current = read(self.root / CONTROL_REL)
        current['next'].update(author_decision='D-062', plan=R5_PLAN)
        overwrite(self.root / CONTROL_REL, current)
        save(self.root / R5_PLAN, {'synthetic_plan': True})
        self.schedule = make_schedule(self.plan, acceptance_utc='2026-09-14T20:31:37+00:00',
                                      technical_ready_utc='2026-09-14T20:45:00+00:00')
        self.now = datetime.fromisoformat(self.schedule['anchor']['t_utc'])
        values = {'calendar-r5/schedule.json': self.schedule,
                  'calendar-r5/AUTHOR-APPROVAL.json': {'decision': 'D-062', 'first_observed_utc': self.schedule['anchor']['acceptance_utc']},
                  'calendar-r5/TECHNICAL-READY.json': {'status': 'passed_calendar_independent_checks', 'utc': self.schedule['anchor']['technical_ready_utc']}}
        sources = dict(self.prior.contract['source_files'])
        for name, value in values.items():
            save(self.pack / name, value)
            sources[str(PACK_REL / name)] = checksum(self.pack / name)
        names = ['eval-harness/eval/communication_pruning/pilot_overnight_r5_' + n + '.py'
                 for n in ('calendar', 'execution', 'guard')]
        names += [str(PACK_REL / 'calendar-r5/production/operate.py'), str(PACK_REL / 'calendar-r5/independent-audit/audit.py')]
        for name in names:
            save(self.root / name, {'synthetic_source': name})
            sources[name] = checksum(self.root / name)
        for name in (CONTROL_REL, CONTROL_R4, R5_PLAN):
            sources[name] = checksum(self.root / name)
        self.contract = deepcopy(self.prior.contract)
        self.contract.update(schema='z42-pilot-overnight-r5/v1', author_decision='D-062',
            schedule_sha256=self.schedule['sha256'], source_files=sources,
            prior_night_contract_sha256=checksum(self.prior.base / 'contract.json'),
            prior_night_acceptance_sha256=checksum(self.prior.base / 'START-ACCEPTANCE.json'),
            prior_night_activation_sha256=checksum(self.prior.base / 'activation/ACTIVATED.json'))
        self.contract['prior_night_files'] = {str(p.relative_to(self.pack)): checksum(p) for tree in PRIOR_NIGHT_TREES
            for p in (self.pack / tree).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        self.contract['preserved_files'][CHECKPOINT] = checksum(self.pack / CHECKPOINT)
        self.original = {str(p.relative_to(self.root)): checksum(p) for folder in (self.live, self.control, self.pack / 'window-evidence')
                         for p in folder.rglob('*') if p.is_file()}
        backup = snapshot(self.root, self.base / 'preactivation-backup', [self.root / p for p in self.original], lambda: self.now)
        self.contract['preactivation_backup'] = str(backup.relative_to(self.root))
        self.contract['source_files'][str(backup.relative_to(self.root))] = checksum(backup)
        save(self.base / 'contract.json', self.contract)
        evidence = self.base / 'offline-review.json'
        save(evidence, {'synthetic_only': True})
        save(self.base / 'START-ACCEPTANCE.json', {'status': 'passed_C1_C4_C5_entry',
            'contract_sha256': checksum(self.base / 'contract.json'), 'reviewer': 'separate_fixture',
            'implementer': 'fixture', 'criteria': {n: 'passed' for n in ('C1','C2','C3','C4','C5-entry')},
            'evidence': {str(evidence.relative_to(self.root)): checksum(evidence)}})
        self.loaded = []
        self.audits = 0

    def session(self):
        def original_guard():
            entries = {CONTROL_REL: checksum(self.root / CONTROL_ORIGINAL),
                       str(PACK_REL / 'calendar-r2/preparation/calendar.json'): checksum(self.pack / 'calendar-r2/preparation/calendar.json')}
            check_original_files(self.root, entries, self.contract['source_files'])
        return OvernightSession(root=self.root, contract_path=self.base / 'contract.json',
            acceptance_path=self.base / 'START-ACCEPTANCE.json', original_guard=original_guard,
            original_start_guard=original_guard, auditor=self.audit, clock=lambda: self.now, synthetic=True)

    def audit(self, plan, folder, state, *, schedule):
        spec = importlib.util.spec_from_file_location('actual_r5_audit', AUDIT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.audits += 1
        return module.audit(plan, folder, state, schedule=schedule)

    def loader(self, task_id):
        self.loaded.append(task_id)
        return self.prior.loader(task_id)

    def checkpoint(self, stage, state):
        save(self.active.current / (stage + '-STATE.json'), state)
        report = self.audit(self.plan, self.live, state, schedule=self.schedule)
        save(self.active.current / (stage + '-AUDIT.json'), report)
        receipt = snapshot(self.root, self.base / 'checkpoints' / stage, self.active.snapshot_paths(), lambda: self.now)
        return {'verified': True, 'sha256': checksum(receipt)}

    def run_section(self, window='R5-E01', **changes):
        self.active = self.session()
        args = dict(bindings=self.bindings, window_id=window, folder=self.live, control=self.control,
            loader=self.loader, selector=lambda _: 'C14', transport=self.transport, guard=lambda: None,
            checkpoint=self.checkpoint, recovery=self.active, clock=lambda: self.now, synthetic=True)
        args.update(changes)
        return run_window(self.plan, self.manifest, self.ids, **args)

    def assert_originals(self):
        for name, value in self.original.items():
            if not name.endswith('/budget.jsonl'):
                self.assertEqual(checksum(self.root / name), value, name)
        for name, value in {**self.contract['prior_files'], **self.contract['prior_night_files']}.items():
            self.assertEqual(checksum(self.pack / name), value, name)
        self.assertTrue((self.live / 'budget.jsonl').read_bytes().startswith(self.prefix))

    def test_29_then_30_real_audits_preserve_prior_activation_and_start_call13(self):
        self.session().activate()
        self.assertEqual(self.loaded, [])
        self.assertEqual(self.transport.calls, 12)
        self.assert_originals()
        self.now = window_interval(self.schedule['sections'][0])[0]
        first = self.run_section()
        self.assertEqual((first['completed_pairs_before'], first['completed_pairs']), (1, 30))
        self.assertEqual((len(self.loaded), self.transport.calls), (29, 360))
        self.assertTrue((self.live / 'provider/00013-binding.json').is_file())
        self.session().guard(deep=True)
        waiting = overnight_status(self.plan, self.manifest, self.ids, bindings=self.bindings, recovery=self.session())
        self.assertEqual((waiting['status'], waiting['next_window_id']), ('not_yet_due', 'R5-E02'))
        self.now = window_interval(self.schedule['sections'][1])[0]
        second = self.run_section('R5-E02')
        self.assertEqual((second['completed_pairs_before'], second['completed_pairs']), (30, 60))
        self.assertEqual((len(self.loaded), self.transport.calls, self.audits), (59, 720, 3))
        self.session().guard(deep=True)
        self.assert_originals()

    def test_missing_changed_or_new_prior_evidence_blocks_without_dispatch(self):
        cases = [self.prior.base / 'activation/ACTIVATED.json', self.prior.base / 'activation/LINK.json',
                 self.pack / CHECKPOINT, self.prior.base / 'contract.json', self.root / CONTROL_R3,
                 self.root / CONTROL_R4, self.root / R4_PLAN,
                 self.root / 'eval-harness/eval/communication_pruning/pilot_continuation_execution.py',
                 self.root / 'eval-harness/eval/communication_pruning/pilot_overnight_execution.py']
        for path in cases:
            raw = path.read_bytes()
            path.write_bytes(raw + b' ')
            with self.assertRaises(PilotStop):
                self.session().activate()
            path.write_bytes(raw)
        new = self.prior.base / 'activation/UNKNOWN.json'
        save(new, {'unexpected': True})
        with self.assertRaises(PilotStop):
            self.session().activate()
        new.unlink()
        for folder in ('attempts', 'provider-preflight', 'errors'):
            path = self.prior.base / folder
            path.mkdir()
            with self.assertRaises(PilotStop):
                self.session().activate()
            path.rmdir()
        self.assertEqual(self.transport.calls, 12)
        self.assertFalse((self.base / 'activation').exists())

    def test_r4_control_copy_cannot_change_even_if_current_binding_is_resigned(self):
        path = self.root / CONTROL_R4
        raw = path.read_bytes()
        path.write_bytes(raw + b' ')
        session = self.session()
        session.contract['source_files'][CONTROL_R4] = checksum(path)
        with self.assertRaisesRegex(PilotStop, 'preserved R4 development control differs'):
            session.prior_night(deep=True)
        path.write_bytes(raw)
        self.assertEqual((self.loaded, self.transport.calls), ([], 12))
        self.assertFalse((self.base / 'activation').exists())

    def test_r4_activity_stays_forbidden_after_r5_activation(self):
        self.session().activate()
        for folder in ('attempts', 'provider-preflight', 'errors'):
            path = self.prior.base / folder
            path.mkdir()
            with self.assertRaises(PilotStop):
                self.session().guard(deep=True)
            path.rmdir()
        self.session().guard(deep=True)
        self.assertEqual((self.loaded, self.transport.calls), ([], 12))
        self.assert_originals()

    def test_duplicate_and_partial_linkage_blocks(self):
        self.session().activate()
        original = checksum(self.base / 'activation/ACTIVATED.json')
        with self.assertRaises(PilotStop):
            self.session().activate()
        self.assertEqual(checksum(self.base / 'activation/ACTIVATED.json'), original)
        path = self.base / 'activation/LINK.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(PilotStop):
            self.session().guard(deep=True)
        self.assert_originals()

    def test_hourly_schedule_exact_359_pairs_and_resigned_changes_rejected(self):
        self.assertEqual(self.schedule['anchor']['s_utc'], '2026-09-14T22:00:00+00:00')
        self.assertEqual([len(w['pair_ids']) for w in self.schedule['sections']], [29] + [30] * 11)
        for index, section in enumerate(self.schedule['sections']):
            start, cutoff, end = window_interval(section)
            self.assertEqual(start, datetime.fromisoformat(self.schedule['anchor']['s_utc']) + timedelta(hours=index))
            self.assertEqual((cutoff-start, end-start), (timedelta(minutes=25), timedelta(minutes=55)))
        for key in ('start_utc','pair_start_before_utc','end_utc'):
            bad = deepcopy(self.schedule)
            bad['sections'][0][key] = (datetime.fromisoformat(bad['sections'][0][key]) + timedelta(minutes=1)).isoformat()
            bad['sha256'] = digest({k:v for k,v in bad.items() if k != 'sha256'})
            with self.assertRaises(ValueError):
                validate_schedule(self.plan, bad)
        bad = deepcopy(self.schedule)
        bad['sections'][0]['pair_ids'][0] = 'P0001'
        bad['sha256'] = digest({k:v for k,v in bad.items() if k != 'sha256'})
        with self.assertRaises(ValueError):
            validate_schedule(self.plan, bad)

    def test_early_activation_and_expired_linkage_readonly(self):
        self.now -= timedelta(microseconds=1)
        with self.assertRaises(ValueError):
            self.session().activate()
        self.now = window_interval(self.schedule['sections'][0])[1]
        with self.assertRaises(ValueError):
            self.session().activate()
        self.assertFalse((self.base / 'activation').exists())
        self.assert_originals()

    def test_cutoff_stops_p0002_without_loader_or_send(self):
        self.session().activate()
        self.now = window_interval(self.schedule['sections'][0])[1]
        with self.assertRaises(ValueError):
            self.run_section()
        self.assertEqual((len(self.loaded), self.transport.calls), (0, 12))
        self.assertFalse((self.live / 'pairs/P0002-started.json').exists())
        self.assertTrue(list((self.base / 'errors').glob('*.json')))

    def test_overrun_keeps_actual_pair_and_stops_next(self):
        self.session().activate()
        self.now = window_interval(self.schedule['sections'][0])[0]
        def slow(task_id):
            self.now = window_interval(self.schedule['sections'][0])[2] + timedelta(seconds=1)
            return self.loader(task_id)
        with self.assertRaises(PilotStop):
            self.run_section(loader=slow)
        self.assertTrue((self.live / 'pairs/P0002-complete.json').exists())
        self.assertFalse((self.live / 'pairs/P0003-started.json').exists())
        self.assertEqual(self.transport.calls, 24)
        self.assert_originals()

    def test_unknown_outcome_retains_reserve_and_blocks_reentry(self):
        self.session().activate()
        self.now = window_interval(self.schedule['sections'][0])[0]
        def unknown(*args, **kwargs):
            raise TimeoutError('synthetic unknown result')
        with self.assertRaises(Exception):
            self.run_section(transport=unknown)
        rows = [json.loads(x) for x in (self.live / 'budget.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-2]['kind'], 'reserved')
        self.assertEqual(rows[-1]['kind'], 'settled')
        self.assertIsNone(rows[-1]['usage']['cost_usd'])
        report = read(sorted((self.live / 'reports').glob('*.json'))[-1])
        self.assertEqual(report['budget']['held_reservation_usd'], '0.14')
        self.assertTrue(report['budget']['poisoned'])
        with self.assertRaises(PilotStop):
            self.session().guard()
        self.assert_originals()

    def test_missing_link_and_changed_current_authority_cannot_be_resigned(self):
        for changes in ({'author_decision':'D-061'}, {'id':'Z43'}, {'plan':R3_PLAN}, {'plan':R4_PLAN}):
            path = self.root / CONTROL_REL
            raw = path.read_bytes()
            current = read(path)
            current['next'].update(changes)
            overwrite(path, current)
            sources = dict(self.contract['source_files'])
            sources[CONTROL_REL] = checksum(path)
            with self.assertRaises(PilotStop):
                check_original_files(self.root, {CONTROL_REL: checksum(self.root / CONTROL_ORIGINAL)}, sources)
            path.write_bytes(raw)
        with self.assertRaises(FileNotFoundError):
            self.session().guard()
        self.assertEqual(self.transport.calls, 12)


if __name__ == '__main__':
    unittest.main()
