"""Z23: deterministic complete-prefix continuation and fail-closed boundaries."""
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from communication_pruning.contracts import Response, Usage
from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import PhaseBudget, BudgetStop
from communication_pruning.study import run_spatial, StudyStop, file_hash
from communication_pruning.study_resume import inspect_spatial, phase_lock
from communication_pruning.study_release import run_live
from study_fixture import fixture, FakeTransport


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kw = fixture(self.root / "inputs")
        self.args = dict(**self.kw, folder=self.root / "out", control=self.root / "control", synthetic=True)
        self.transport = FakeTransport()

    def run_prefix(self, limit=1, **kw):
        return run_spatial(**{**self.args, "transport": self.transport, "slot_limit": limit, **kw})

    def inspect(self):
        return inspect_spatial(**self.args)

    def test_interrupted_resume_matches_uninterrupted_preserves_bytes(self):
        checks = 0
        def interrupt():
            nonlocal checks
            checks += 1
            self.kw["guard"]()
            if checks == 3:
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_prefix(3, guard=interrupt)
        before = {p: p.read_bytes() for p in self.args["folder"].rglob("*") if p.is_file()}
        claim = next(self.args["control"].glob("*.claim.json"))
        claim_before = claim.read_bytes()
        state = self.inspect()
        self.assertEqual(state["classification"], "complete_prefix")
        self.assertEqual(state["completed_slots"], 1)
        report = self.run_prefix(3, resume_from=state["resume_token"])
        baseline_transport = FakeTransport()
        baseline = self.run_prefix(3, folder=self.root / "baseline", control=self.root / "other-control", transport=baseline_transport)
        self.assertEqual(self.transport.bodies, baseline_transport.bodies)
        self.assertEqual(report["budget"], baseline["budget"])
        self.assertEqual(self.transport.calls, sum(s["planned_calls"] for s in self.kw["plan"]["slots"][:3]))
        for path, raw in before.items():
            if path.name == "budget.jsonl":
                self.assertTrue(path.read_bytes().startswith(raw))
            else:
                self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(claim.read_bytes(), claim_before)
        for path in (self.root / "baseline/slots").glob("*-result.json"):
            left, right = json.loads(path.read_bytes()), json.loads((self.args["folder"] / "slots" / path.name).read_bytes())
            left.pop("journal_sha256"); right.pop("journal_sha256")
            self.assertEqual(left, right)
        self.assertEqual(self.inspect()["completed_slots"], 3)

    def test_unbegun_after_budget_header_can_continue(self):
        checks = 0
        def stop():
            nonlocal checks
            checks += 1
            if checks == 2: raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.run_prefix(guard=stop)
        state = self.inspect()
        self.assertEqual(state["classification"], "unbegun")
        self.assertEqual(self.transport.calls, 0)
        self.run_prefix(resume_from=state["resume_token"])
        self.assertGreater(self.transport.calls, 0)

    def test_missing_result_rebuilt_without_answer_redraw(self):
        self.run_prefix()
        path = next((self.args["folder"] / "slots").glob("*-result.json"))
        old = path.read_bytes(); path.unlink()
        state = self.inspect()
        self.assertEqual(len(state["missing_results"]), 1)
        self.run_prefix(2, resume_from=state["resume_token"])
        self.assertEqual(path.read_bytes(), old)
        receipt = json.loads(next(self.args["folder"].glob("resume-*-start.json")).read_bytes())
        self.assertEqual(receipt["missing_results"], state["missing_results"])
        self.assertEqual(self.transport.calls, sum(s["planned_calls"] for s in self.kw["plan"]["slots"][:2]))

    def test_partial_unknown_failed_and_open_calls_stop_before_input_or_transport(self):
        for mode in ("interrupt", "unknown", "length", "http", "transport"):
            with self.subTest(mode=mode):
                args = {**self.args, "folder": self.root / mode, "control": self.root / (mode + "-control")}
                with self.assertRaises((KeyboardInterrupt, BudgetStop)):
                    run_spatial(**args, transport=FakeTransport(fail_at=1, mode=mode), slot_limit=1)
                transport = Mock()
                with patch("communication_pruning.study_resume.load_task") as contents:
                    with self.assertRaises((BudgetStop, StudyStop, ValueError)):
                        run_spatial(**args, transport=transport, slot_limit=2, resume_from="bad")
                    contents.assert_not_called()
                transport.assert_not_called()

    def test_corrupt_bindings_provider_results_and_gaps_rejected(self):
        self.run_prefix()
        folder = self.args["folder"]
        changes = [folder / "execution-bindings.json", folder / "provider/00001-response.json",
                   next((folder / "slots").glob("*-binding.json")), next((folder / "slots").glob("*-result.json")),
                   folder / "budget.jsonl"]
        for path in changes:
            with self.subTest(path=path.name):
                raw = path.read_bytes(); path.write_text('{}\n')
                t = Mock()
                try:
                    with self.assertRaises((StudyStop, BudgetStop, ValueError, KeyError, TypeError)):
                        self.run_prefix(2, transport=t, resume_from="bad")
                    t.assert_not_called()
                finally: path.write_bytes(raw)
        orphan = folder / "slots/foreign-binding.json"; orphan.write_text('{}')
        with self.assertRaises(StudyStop): self.inspect()

    def test_unsealed_journal_stops_before_reload(self):
        self.run_prefix()
        path = next((self.args["folder"] / "slots").glob("*.jsonl"))
        lines = path.read_bytes().splitlines(keepends=True)
        path.write_bytes(b''.join(lines[:-1]))
        with patch("communication_pruning.study_resume.load_task") as contents:
            with self.assertRaises(StudyStop): self.inspect()
            contents.assert_not_called()

    def test_well_formed_but_inconsistent_evidence_rejected(self):
        self.run_prefix()
        folder = self.args['folder']
        result = next((folder / 'slots').glob('*-result.json'))
        binding = next((folder / 'slots').glob('*-binding.json'))
        edits = [(result, lambda v: v.update(em=1)),
                 (binding, lambda v: v.update(repeat=99)),
                 (folder / 'provider/00001-received.json', lambda v: v.update(http_status=503)),
                 (folder / 'provider/00001-billing.json', lambda v: v.update(generation_id='different')),
                 (folder / 'execution-bindings.json', lambda v: v.update(inputs='a'*64))]
        for path, edit in edits:
            raw = path.read_bytes(); value = json.loads(raw); edit(value)
            path.write_bytes(encoded(value))
            try:
                with self.assertRaises(StudyStop): self.inspect()
            finally: path.write_bytes(raw)
        # A valid hash chain is insufficient when a stored sum is contradictory.
        from communication_pruning.data import digest
        path = folder / 'budget.jsonl'; raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.splitlines()]
        rows[1]['known_before_usd'] = '9'
        previous = '0'*64
        for row in rows:
            row.pop('sha256'); row['previous'] = previous
            row['sha256'] = digest(row); previous = row['sha256']
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaises(BudgetStop): self.inspect()

    def test_stale_duplicate_and_other_output_blocked(self):
        self.run_prefix()
        token = self.inspect()["resume_token"]
        self.run_prefix(2, resume_from=token)
        t = Mock()
        with self.assertRaises(StudyStop): self.run_prefix(3, transport=t, resume_from=token)
        with self.assertRaises(StudyStop): self.run_prefix(3, folder=self.root / "reset", transport=t, resume_from=token)
        with self.assertRaises(FileExistsError): self.run_prefix(3, folder=self.root / "reset", transport=t)
        t.assert_not_called()

    def test_lock_blocks_resume_and_fresh_start(self):
        self.run_prefix()
        token = self.inspect()["resume_token"]
        t = Mock()
        with phase_lock(self.args["control"], self.kw["plan"]):
            with self.assertRaises(StudyStop): self.run_prefix(2, transport=t, resume_from=token)
            with self.assertRaises(StudyStop): self.run_prefix(2, transport=t)
        t.assert_not_called()

    def test_generation_ids_remain_unique_across_segments(self):
        self.run_prefix()
        token = self.inspect()["resume_token"]
        t = FakeTransport()  # restarts at fake-gen-1, must be rejected
        with self.assertRaises(BudgetStop): self.run_prefix(2, transport=t, resume_from=token)
        self.assertEqual(t.calls, 1)
        with self.assertRaises(BudgetStop): self.inspect()

    def test_budget_replay_preserves_cap_calls_and_duplicate_ids(self):
        for limit, cap in [(1, Decimal('1')), (3, Decimal('.20'))]:
            path = self.root / f'budget-{limit}.jsonl'
            args = dict(cap=cap, reserve=Decimal('.14'), max_calls=limit, binding='a'*64, allow_synthetic=True)
            budget = PhaseBudget(path, **args)
            budget.run('old', lambda: Response('text', Usage(cost_usd=Decimal('.07'), cost_source='synthetic')))
            raw = path.read_bytes()
            restored = PhaseBudget.read_completed(path, **args)
            self.assertEqual(restored.snapshot(), budget.snapshot())
            self.assertEqual(path.read_bytes(), raw)
            called = Mock()
            with self.assertRaises(BudgetStop): restored.run('new', called)
            called.assert_not_called()
            with self.assertRaises(BudgetStop): PhaseBudget.read_completed(path, **args).start('old')
            with self.assertRaises(BudgetStop): PhaseBudget.read_completed(path, **{**args, 'cap': Decimal('2')})

    def test_live_release_missing_backup_and_changed_sources_never_load_key(self):
        path = self.root / 'release.json'
        for value in ({'status':'prepared_not_authorized'},
                      {'status':'authorized_by_author', 'author_decision':'invented test', 'backup_evidence':None},
                      {'status':'authorized_by_author', 'author_decision':'invented test', 'backup_evidence':{}, 'source_zip':'absent', 'source_manifest':'absent'}):
            path.write_bytes(encoded(value))
            with patch('communication_pruning.study_release.load_key') as key, patch('communication_pruning.study_release.Transport') as client:
                with self.assertRaises((StudyStop, FileNotFoundError)): run_live(self.root, path, self.root / 'live', resume_from='x')
                key.assert_not_called(); client.assert_not_called()

    def test_live_unsafe_prefix_rejected_before_credentials(self):
        # All release/backup metadata are explicitly invented; no actual release.
        source = self.root / 'inputs/musique_ans_v1.0_train.jsonl'
        source.write_bytes(Path(self.kw['source_path']).read_bytes())
        control = self.root / 'eval-harness/eval/study-control/spatial'
        args = {**self.args, 'source_path':source, 'control':control, 'synthetic':False}
        with self.assertRaises(KeyboardInterrupt):
            run_spatial(**args, transport=FakeTransport(fail_at=1, mode='interrupt'))
        backup = self.root / 'fake-backup'; backup.write_text('invented backup evidence')
        release = {'status':'authorized_by_author', 'author_decision':'invented test only',
            'backup_evidence':{'path':str(backup), 'sha256':file_hash(backup), 'external_location_description':'invented test'},
            'source_zip':'mock', 'source_manifest':'mock', 'files':{str(source):file_hash(source)}}
        path = self.root / 'release.json'; path.write_bytes(encoded(release))
        metadata = (self.kw['plan'], self.kw['manifest'], self.kw['task_ids'], self.kw['repeats'], self.kw['bindings'], {})
        with patch('communication_pruning.study_release.candidate', return_value=dict(release)), \
             patch('communication_pruning.study_release.bound_metadata', return_value=metadata), \
             patch('communication_pruning.study_release.DATA_PATH', 'inputs'), \
             patch('communication_pruning.study_release.load_key') as key, \
             patch('communication_pruning.study_release.Transport') as client, \
             patch('communication_pruning.study_resume.load_task') as contents:
            with self.assertRaises(BudgetStop): run_live(self.root, path, self.args['folder'], resume_from='x')
            key.assert_not_called(); client.assert_not_called(); contents.assert_not_called()
