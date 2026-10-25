"""Z25: invented responses only; task failure versus phase integrity stop."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from communication_pruning.failure_policy import F01, ModelFailure, decode_outcome
from communication_pruning.openrouter import encoded, ProbeStop, save_new
from communication_pruning.study import run_spatial, StudyStop
from communication_pruning.study_resume import inspect_spatial, phase_lock
from communication_pruning.phase_budget import BudgetStop, PhaseBudget
from communication_pruning.evaluation import RunResult, PlannedTask, development_observations
from communication_pruning.data import load_task
from communication_pruning.study_release import run_live
from study_fixture import fixture, FakeTransport


class OutcomeTransport(FakeTransport):
    def __init__(self, changes=None, **kw):
        super().__init__(**kw)
        self.changes = changes or {}

    def __call__(self, endpoint, body=None):
        status, raw = super().__call__(endpoint, body)
        if endpoint != 'chat/completions':
            return status, raw
        change = self.changes.get(self.calls)
        if change:
            data = json.loads(raw)
            change(data)
            raw = encoded(data)
        return status, raw


def outcome(reason):
    def change(data):
        data['choices'][0]['finish_reason'] = 'length' if reason == 'length' else 'stop'
        data['choices'][0]['message']['content'] = 'truncated invented text' if reason == 'length' else ' \n '
    return change


class FailurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kw = fixture(self.root / 'inputs')
        self.args = dict(**self.kw, folder=self.root / 'out', control=self.root / 'control',
                         synthetic=True, failure_policy=F01)
        self.transport = OutcomeTransport()

    def run_case(self, **kw):
        return run_spatial(**{**self.args, 'transport':self.transport, 'slot_limit':2, **kw})

    def results(self, folder=None):
        return [json.loads(p.read_bytes()) for p in sorted((folder or self.args['folder']).glob('slots/*-result.json'))]

    def test_early_late_aggregator_length_and_empty_end_task_only(self):
        roles = {1:'linking', 4:'draft', 5:'aggregator'}
        for reason in ('length', 'empty'):
            for position, role in roles.items():
                with self.subTest(reason=reason, position=position):
                    tag = f'{reason}-{position}'
                    t = OutcomeTransport({position:outcome(reason)})
                    folder = self.root / tag
                    report = self.run_case(folder=folder, control=self.root/(tag+'-control'), transport=t)
                    rows = self.results(folder)
                    self.assertEqual(len(rows), 2)
                    first, second = rows
                    self.assertEqual((first['status'], first['em'], first['f1'], first['failure_reason'], first['failure_role']),
                                     ('model_failed', 0, 0, reason, role))
                    self.assertEqual(second['status'], 'completed')
                    expected_calls = position + self.kw['plan']['slots'][1]['planned_calls']
                    self.assertEqual(t.calls, expected_calls)
                    self.assertEqual(report['model_failed_slots'], 1)
                    self.assertEqual(Decimal(report['budget']['known_cost_usd']), Decimal('.0000108')*expected_calls)
                    self.assertEqual(Decimal(first['cost_usd']), Decimal('.0000108')*position)
                    self.assertFalse(report['budget']['poisoned'])
                    self.assertFalse(any('PRIVATE_' in json.dumps(b) for b in t.bodies))
                    self.assertEqual(inspect_spatial(**{**self.args,'folder':folder,'control':self.root/(tag+'-control')})['completed_slots'], 2)

    def test_regular_correct_wrong_and_failure_form_complete_grid(self):
        def correct(data): data['choices'][0]['message']['content'] = 'PRIVATE_REFERENCE_NEVER_SEND'
        self.transport = OutcomeTransport({1:outcome('empty'), 6:correct})
        report = self.run_case(slot_limit=14)
        rows = self.results()
        self.assertEqual([r['em'] for r in rows[:3]], [0, 1, 0])
        self.assertEqual([r['status'] for r in rows[:3]], ['model_failed','completed','completed'])
        results = [RunResult(**{**r,'cost_usd':Decimal(r['cost_usd']), 'known_subtotal_usd':Decimal(r['known_subtotal_usd'])}) for r in rows]
        task, _ = load_task(self.kw['source_path'], self.kw['plan']['slots'][0]['task_id'], self.kw['manifest'], phase='spatial')
        plan = [PlannedTask(task, rows[0]['family_id'], 'spatial', (1,))]
        table = development_observations(results, plan)
        self.assertEqual(table['executed_runs'], 14)
        self.assertEqual(table['executed_cost_usd'], Decimal(report['budget']['known_cost_usd']))
        bad_sets = [results[:-1], results+[results[0]]]
        for changes in ({'cost_usd':None}, {'status':'incomplete'}, {'em':1}, {'failure_policy':None}, {'failure_reason':'http'}):
            bad_sets.append([replace(results[0], **changes), *results[1:]])
        bad_sets.append([results[0], replace(results[1], failure_policy=None), *results[2:]])
        for bad in bad_sets:
            with self.assertRaises(ValueError): development_observations(bad, plan)

    def test_http_unknown_duplicate_transport_and_overreserve_still_stop(self):
        for mode in ('http','unknown','duplicate','transport','over'):
            with self.subTest(mode=mode):
                t = OutcomeTransport({2:outcome('length')}, fail_at=2, mode=mode)
                folder = self.root/mode
                with self.assertRaises(BudgetStop):
                    self.run_case(transport=t, folder=folder, control=self.root/(mode+'-control'))
                self.assertEqual(t.calls, 2)
                self.assertEqual(self.results(folder), [])
                with self.assertRaises((StudyStop, BudgetStop)):
                    inspect_spatial(**{**self.args,'folder':folder,'control':self.root/(mode+'-control')})

    def test_nonallowlisted_envelopes_and_limits_are_phase_stops(self):
        def tokens(d): d['usage'].update(completion_tokens=1025, total_tokens=1125)
        def reasoning(d): d['usage']['completion_tokens_details']['reasoning_tokens'] = 1
        changes = [tokens, reasoning,
                   lambda d:d.update(error=None),
                   lambda d:d['choices'][0].update(finish_reason='content_filter'),
                   lambda d:d['choices'][0]['message'].update(content=None),
                   lambda d:d['choices'][0]['message'].update(role='tool'),
                   lambda d:d['choices'][0]['message'].update(tool_calls=[{}]),
                   lambda d:d['choices'][0]['message'].update(refusal='denied'),
                   lambda d:d['choices'].append(deepcopy(d['choices'][0]))]
        for i, change in enumerate(changes):
            def malformed(d, change=change): outcome('length')(d); change(d)
            t = OutcomeTransport({1:malformed})
            with self.subTest(case=i), self.assertRaises(BudgetStop):
                self.run_case(transport=t, folder=self.root/f'bad{i}', control=self.root/f'bad-control{i}')
            self.assertEqual(t.calls, 1)

    def test_duplicate_json_field_not_known_billing_or_zero_score(self):
        t = OutcomeTransport({1:outcome('length')})
        def duplicate(endpoint, body=None):
            status, raw = t(endpoint, body)
            return status, (raw.replace(b'"cost":', b'"cost":"9","cost":') if body else raw)
        with self.assertRaises(BudgetStop): self.run_case(transport=duplicate)
        report = json.loads((self.args['folder']/'report.json').read_bytes())
        self.assertIsNone(report['budget']['total_cost_usd'])
        self.assertEqual(self.results(), [])

    def test_durable_billing_failure_cannot_become_model_failure(self):
        self.transport = OutcomeTransport({1:outcome('empty')})
        def fail(path, data):
            if str(path).endswith('-billing.json'): raise OSError('invented disk failure')
            save_new(path, data)
        with patch('communication_pruning.study.save_new', side_effect=fail):
            with self.assertRaises(BudgetStop): self.run_case()
        report = json.loads((self.args['folder']/'report.json').read_bytes())
        self.assertIsNone(report['budget']['total_cost_usd'])
        self.assertEqual(self.transport.calls, 1)

    def test_budget_exhaustion_after_failure_blocks_next_call(self):
        self.transport = OutcomeTransport({1:outcome('empty')})
        def tiny(path, **kw): return PhaseBudget(path, **{**kw,'cap':Decimal('.14')})
        with patch('communication_pruning.study.PhaseBudget', side_effect=tiny):
            with self.assertRaises(BudgetStop): self.run_case()
        self.assertEqual(self.transport.calls, 1)
        self.assertEqual(self.results()[0]['status'], 'model_failed')

    def test_resume_after_failure_matches_through_and_preserves_prefix(self):
        self.transport = OutcomeTransport({2:outcome('length'),8:outcome('empty')})
        checks = 0
        def interrupt():
            nonlocal checks
            checks += 1
            self.kw['guard']()
            if checks == 3: raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.run_case(slot_limit=14, guard=interrupt)
        old = {p:p.read_bytes() for p in self.args['folder'].rglob('*') if p.is_file()}
        state = inspect_spatial(**self.args)
        self.assertEqual(state['completed_slots'], 1)
        resumed = self.run_case(slot_limit=14, resume_from=state['resume_token'])
        t = OutcomeTransport({2:outcome('length'),8:outcome('empty')})
        through = self.run_case(slot_limit=14, transport=t, folder=self.root/'through', control=self.root/'through-control')
        self.assertEqual(self.transport.bodies, t.bodies)
        self.assertEqual(resumed['budget'], through['budget'])
        for a,b in zip(self.results(), self.results(self.root/'through')):
            a.pop('journal_sha256'); b.pop('journal_sha256'); self.assertEqual(a,b)
        for p, raw in old.items():
            if p.name == 'budget.jsonl': self.assertTrue(p.read_bytes().startswith(raw))
            else: self.assertEqual(p.read_bytes(),raw)
        self.assertEqual(inspect_spatial(**self.args)['completed_slots'],14)

    def test_policy_change_stale_lock_and_corruption_block_before_transport(self):
        self.transport = OutcomeTransport({1:outcome('empty')})
        self.run_case(slot_limit=1)
        state = inspect_spatial(**self.args)
        t = Mock()
        with self.assertRaises(StudyStop): self.run_case(transport=t, failure_policy=None, resume_from=state['resume_token'])
        with phase_lock(self.args['control'], self.kw['plan']):
            with self.assertRaises(StudyStop): self.run_case(transport=t, resume_from=state['resume_token'])
        result = next(self.args['folder'].glob('slots/*-result.json'))
        raw = result.read_bytes(); obj = json.loads(raw); obj['em']=1; result.write_bytes(encoded(obj))
        with self.assertRaises(StudyStop): self.run_case(transport=t, resume_from=state['resume_token'])
        result.write_bytes(raw)
        self.run_case(resume_from=state['resume_token'])
        with self.assertRaises(StudyStop): self.run_case(slot_limit=3,transport=t,resume_from=state['resume_token'])
        t.assert_not_called()

    def test_missing_failed_result_reconstructed_without_retry(self):
        self.transport = OutcomeTransport({1:outcome('empty')})
        self.run_case(slot_limit=1)
        p = next(self.args['folder'].glob('slots/*-result.json'))
        raw=p.read_bytes(); p.unlink()
        state=inspect_spatial(**self.args)
        self.run_case(resume_from=state['resume_token'])
        self.assertEqual(p.read_bytes(),raw)
        self.assertEqual(self.transport.calls,6)

    def test_policy_switch_in_release_blocked_before_key(self):
        expected = {'status':'prepared_not_authorized','author_decision':None,'backup_evidence':None,
                    'source_zip':'mock','source_manifest':'mock','failure_policy':F01}
        release = {**expected,'status':'authorized_by_author','author_decision':'invented test only',
                   'backup_evidence':{},'failure_policy':None}
        path=self.root/'release.json'; path.write_bytes(encoded(release))
        with patch('communication_pruning.study_release.candidate',return_value=expected), \
             patch('communication_pruning.study_release.load_key') as key, \
             patch('communication_pruning.study_release.Transport') as client:
            with self.assertRaises(StudyStop): run_live(self.root,path,self.root/'live')
            key.assert_not_called(); client.assert_not_called()

    def test_failure_audit_rejects_forged_reason_cost_and_trailing_events(self):
        from communication_pruning.audit import audit, AuditError
        from communication_pruning.configurations import bank
        from communication_pruning.journal import read_journal
        self.transport = OutcomeTransport({2:outcome('length')})
        self.run_case(slot_limit=1)
        config = next(c for c in bank() if c.config_id == self.kw['plan']['slots'][0]['config_id'])
        trace = read_journal(next(self.args['folder'].glob('slots/*.jsonl')), config)['trace']
        self.assertEqual(audit(trace,config)['calls'],2)
        mutations = [lambda t:t['events'][-1].update(reason='http'),
                     lambda t:t['events'][-1]['usage'].update(cost_usd=None,cost_source='unknown'),
                     lambda t:t['events'].extend(t['events'][-2:]),
                     lambda t:t.update(schema=2),
                     lambda t:t.update(status='completed',answer='invented'),
                     lambda t:t['events'][1].update(text='')]
        for mutation in mutations:
            changed=deepcopy(trace); mutation(changed)
            with self.assertRaises(AuditError): audit(changed,config)

    def test_legacy_decoder_does_not_inherit_approved_policy(self):
        for reason in ('length','empty'):
            t=OutcomeTransport({1:outcome(reason)})
            _,raw=t('chat/completions',b'{}')
            self.assertIsInstance(decode_outcome(raw,1024,F01),ModelFailure)
            with self.assertRaises(ProbeStop): decode_outcome(raw,1024,None)
