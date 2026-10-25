"""Z26: explicit live checkpoints and author-bound local backup; no network."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from communication_pruning.openrouter import encoded
from communication_pruning.study import run_spatial, StudyStop, file_hash
from communication_pruning.study_release import run_live
from communication_pruning.study_resume import inspect_spatial
from communication_pruning.failure_policy import F01
from study_fixture import fixture, FakeTransport


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.kw = fixture(self.root / 'inputs')
        self.args = dict(**self.kw, folder=self.root / 'out', control=self.root / 'control',
                         synthetic=False, failure_policy=F01)

    def test_explicit_live_checkpoint_resume_keeps_calls_costs_and_bytes(self):
        transport = FakeTransport()
        first = run_spatial(**self.args, transport=transport, slot_limit=14, checkpoint=True)
        self.assertEqual(first['status'], 'paused_at_checkpoint')
        self.assertEqual(first['completed_slots'], 14)
        before = {p: p.read_bytes() for p in self.args['folder'].rglob('*') if p.is_file()}
        state = inspect_spatial(**self.args)
        resumed = run_spatial(**self.args, transport=transport, slot_limit=15, checkpoint=True,
                              resume_from=state['resume_token'])
        baseline = FakeTransport()
        expected = run_spatial(**{**self.args, 'folder': self.root / 'baseline',
                                  'control': self.root / 'other-control'}, transport=baseline,
                               slot_limit=15, checkpoint=True)
        self.assertEqual(resumed['budget'], expected['budget'])
        self.assertEqual(transport.bodies, baseline.bodies)
        self.assertEqual(transport.calls, sum(s['planned_calls'] for s in self.kw['plan']['slots'][:15]))
        for p, data in before.items():
            if p.name == 'budget.jsonl':
                self.assertTrue(p.read_bytes().startswith(data))  # ledger appends, never rewrites
            else:
                self.assertEqual(p.read_bytes(), data)

    def test_unmarked_invalid_or_stale_checkpoint_never_transports(self):
        for overrides in ({'slot_limit': 1}, {'slot_limit': True, 'checkpoint': True},
                          {'slot_limit': 0, 'checkpoint': True}, {'slot_limit': 1, 'checkpoint': 'yes'}):
            transport = FakeTransport()
            with self.assertRaises(StudyStop):
                run_spatial(**self.args, transport=transport, **overrides)
            self.assertEqual(transport.calls, 0)
        transport = FakeTransport()
        run_spatial(**self.args, transport=transport, slot_limit=1, checkpoint=True)
        calls = transport.calls
        with self.assertRaises(StudyStop):
            run_spatial(**self.args, transport=transport, slot_limit=2, checkpoint=True, resume_from='stale')
        self.assertEqual(transport.calls, calls)

    def release(self):
        backup = self.root / 'backup-receipt.json'
        backup.write_text('invented local backup receipt')
        return dict(status='authorized_by_author', author_decision='invented D-local approval',
                    source_zip='unused', source_manifest='unused', files={},
                    backup_evidence=dict(path=str(backup), sha256=file_hash(backup), location_kind='local',
                                         location_description='Invented local fixture',
                                         author_decision='invented D-local approval'), failure_policy=F01)

    def test_author_bound_local_backup_reaches_runner_and_is_guarded(self):
        release = self.release()
        path = self.root / 'release.json'; path.write_bytes(encoded(release))
        metadata = (self.kw['plan'], self.kw['manifest'], self.kw['task_ids'],
                    self.kw['repeats'], self.kw['bindings'], {})
        with patch('communication_pruning.study_release.candidate', return_value=release.copy()), \
             patch('communication_pruning.study_release.bound_metadata', return_value=metadata), \
             patch('communication_pruning.study_release.run_spatial', return_value={'mock': True}) as runner, \
             patch('communication_pruning.study_release.load_key') as key:
            self.assertEqual(run_live(self.root, path, self.root / 'out', stop_after_slots=14), {'mock': True})
            key.assert_not_called()
            args = runner.call_args.kwargs
            self.assertEqual(args['slot_limit'], 14)
            self.assertIs(args['checkpoint'], True)
            args['guard']()
            Path(release['backup_evidence']['path']).write_text('changed')
            with self.assertRaises(StudyStop):
                args['guard']()

    def test_invalid_local_backup_blocks_before_key_or_runner(self):
        release = self.release()
        invalid = [{'author_decision': ''}, {'author_decision': 'different'},
                   {'location_kind': 'cloud'}, {'location_description': ' '}, {'sha256': '0'*64}]
        for update in invalid:
            value = {**release, 'backup_evidence': {**release['backup_evidence'], **update}}
            path = self.root / 'release.json'; path.write_bytes(encoded(value))
            with patch('communication_pruning.study_release.candidate', return_value=value.copy()), \
                 patch('communication_pruning.study_release.run_spatial') as runner, \
                 patch('communication_pruning.study_release.load_key') as key:
                with self.assertRaises(StudyStop):
                    run_live(self.root, path, self.root / 'out')
                key.assert_not_called(); runner.assert_not_called()
