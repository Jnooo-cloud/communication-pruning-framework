"""Artificial D-054 partial failure/recovery, including rejected deviations."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from study_fixture import FakeTransport, fixture
from communication_pruning.failure_policy import F01
from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study import StudyStop, run_spatial
from communication_pruning.study_resume import phase_lock
from communication_pruning.study_recovery import (contract, inventory, inspect_recovery,
    run_recovery, result_paths, run_live_recovery, live_context, budget_args)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.args=fixture(self.root/'inputs')
        self.old=self.root/'old';self.control=self.root/'control';self.new=self.root/'recovery'
        # Stop at the first request of slot 46, exactly the approved incident shape.
        self.completed=45
        calls=sum(x['planned_calls'] for x in self.args['plan']['slots'][:self.completed])
        self.transport=FakeTransport(fail_at=calls+1,mode='transport')
        with self.assertRaises(BudgetStop):
            run_spatial(**self.args,folder=self.old,control=self.control,transport=self.transport,
                synthetic=True,slot_limit=46,failure_policy=F01)
        self.before=inventory(self.old)
        self.manifest=self.root/'old-manifest.json';self.manifest.write_bytes(encoded(self.before))
        self.c=contract(self.args['plan'],self.old,self.manifest,self.control,synthetic=True)
        self.rargs=dict(**self.args,c=self.c,folder=self.new,control=self.control,synthetic=True)

    def run_to(self,n,**kw):
        return run_recovery(**self.rargs,transport=self.transport,stop_after_slots=n,**kw)

    def inspect(self):
        return inspect_recovery(**self.rargs)

    def test_recovery_checkpoint_preserves_prefix_and_common_budget(self):
        old_count=self.transport.calls
        report=self.run_to(46)
        self.assertEqual(report['completed_slots'],46)
        first=self.new/'provider/00001-request.json'
        self.assertEqual(first.read_bytes(),(self.old/'provider'/f'{old_count:05d}-request.json').read_bytes())
        old_binding=json.loads((self.old/'provider'/f'{old_count:05d}-binding.json').read_bytes())
        new_binding=json.loads((self.new/'provider/00001-binding.json').read_bytes())
        self.assertNotEqual(old_binding['attempt_id'],new_binding['attempt_id'])
        self.assertIn('-R1-S00046:',new_binding['attempt_id'])
        saved=inventory(self.new);saved_budget=(self.new/'budget.jsonl').read_bytes();state=self.inspect()
        self.run_to(48,resume_from=state['resume_token'])
        state=self.inspect();self.assertEqual(state['completed_slots'],48)
        self.assertEqual(self.before,inventory(self.old))
        after=inventory(self.new)
        for n,h in saved.items():
            if n != 'budget.jsonl':self.assertEqual(h,after[n])
        self.assertTrue((self.new/'budget.jsonl').read_bytes().startswith(saved_budget))
        common=report['common_budget'];known=Decimal(self.c['old_known_cost_usd'])
        self.assertEqual(Decimal(common['known_plus_held_usd']),known+Decimal('0.14')+Decimal(report['budget']['known_cost_usd']))
        self.assertIsNone(common['total_cost_usd'])
        self.assertEqual(common['dispatch_attempts'],old_count+report['budget']['calls'])
        paths=result_paths(self.c,self.args['plan'],self.new,48,require_complete=False)
        self.assertEqual(len(paths),48);self.assertEqual(len(set(paths)),48)
        self.assertEqual(paths[44].parent.parent.resolve(),self.old.resolve());self.assertEqual(paths[45].parent.parent.resolve(),self.new.resolve())
        with self.assertRaises(StudyStop):result_paths(self.c,self.args['plan'],self.new,48)

    def test_changed_target_reserve_cap_or_source_rejected_before_transport(self):
        count=self.transport.calls
        for key,value in [('completed_before',44),('old_reserve_usd','0'),('segment_cap_usd','36.12'),
                          ('segment_max_calls',40000),('first_slot',self.args['plan']['slots'][46])]:
            with self.subTest(key=key):
                bad=copy.deepcopy(self.c);bad[key]=value
                with self.assertRaises(StudyStop):run_recovery(**{**self.rargs,'c':bad},transport=self.transport)
        p=self.args['source_path'];p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaises(StudyStop):self.run_to(46)
        self.assertEqual(self.transport.calls,count)

    def test_old_bytes_changed_or_new_files_rejected(self):
        p=self.old/'extra.json';p.write_text('{}')
        with self.assertRaises(StudyStop):self.run_to(46)
        p.unlink();p=self.old/'slots/S00001-result.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(StudyStop):self.run_to(46)

    def test_second_recovery_stale_token_and_lock_rejected(self):
        self.run_to(46);state=self.inspect();count=self.transport.calls
        with self.assertRaises(FileExistsError):self.run_to(47)
        with self.assertRaises(FileExistsError):
            run_recovery(**{**self.rargs,'folder':self.root/'another'},transport=self.transport)
        with self.assertRaises(StudyStop):self.run_to(47,resume_from='stale')
        with phase_lock(self.control,self.args['plan']):
            with self.assertRaises(StudyStop):self.run_to(47,resume_from=state['resume_token'])
        self.assertEqual(self.transport.calls,count)

    def test_second_technical_partial_cannot_resume_or_restart(self):
        self.transport.fail_at=self.transport.calls+2;self.transport.mode='transport'
        with self.assertRaises(BudgetStop):self.run_to(46)
        count=self.transport.calls
        with self.assertRaises(BudgetStop):self.inspect()
        with self.assertRaises(BudgetStop):self.run_to(46,resume_from='anything')
        with self.assertRaises(FileExistsError):self.run_to(46)
        self.assertEqual(count,self.transport.calls)
        self.assertEqual(inventory(self.old),self.before)

    def test_duplicate_generation_from_old_phase_stops(self):
        self.transport.fail_at=self.transport.calls+1;self.transport.mode='duplicate'
        with self.assertRaises(BudgetStop):self.run_to(46)
        report=json.loads((self.new/'report.json').read_bytes())
        self.assertEqual(report['completed_slots'],45)
        self.assertTrue(report['budget']['poisoned'])

    def test_budget_reservation_honors_old_cost_and_unknown_reserve(self):
        from communication_pruning.phase_budget import PhaseBudget
        b=PhaseBudget(self.root/'budget.jsonl',**budget_args(self.c,True))
        b.cost=b.cap-b.reserve+Decimal('0.00000001')
        with self.assertRaises(BudgetStop):b.start('over-common-cap')
        self.assertEqual(b.calls,0)
        self.assertEqual(b.cap+Decimal(self.c['old_known_cost_usd'])+Decimal('0.14'),Decimal('36.12'))
        self.assertEqual(b.max_calls,sum(x['planned_calls'] for x in self.args['plan']['slots'][45:]))

    def test_unapproved_live_case_fails_before_key_or_client(self):
        p=self.root/'release.json';p.write_text('{}')
        with patch('communication_pruning.openrouter.load_key') as key, patch('communication_pruning.openrouter.Transport') as client:
            with self.assertRaises(StudyStop):run_live_recovery(self.root,p,self.new)
            key.assert_not_called();client.assert_not_called()
        with self.assertRaises(StudyStop):contract(self.args['plan'],self.old,self.manifest,self.control)

    def test_changed_segment_source_binding_rejected(self):
        self.run_to(46)
        p=self.new/'recovery-binding.json';v=json.loads(p.read_bytes());v['execution']['changed']=True;p.write_bytes(encoded(v))
        with self.assertRaises(StudyStop):self.inspect()

    def test_f01_terminal_failure_in_recovered_slot_can_continue(self):
        self.transport.fail_at=self.transport.calls+1;self.transport.mode='length'
        self.run_to(46)
        result=json.loads((self.new/'slots/S00046-result.json').read_bytes())
        self.assertEqual((result['status'],result['em'],result['f1']),('model_failed',0,0))
        self.assertGreater(Decimal(result['cost_usd']),0)
        state=self.inspect();self.run_to(47,resume_from=state['resume_token'])
        self.assertEqual(self.inspect()['completed_slots'],47)

    def test_authorized_live_gate_rejects_changed_release_and_backup(self):
        release=dict(status='authorized_by_author',author_decision='D-054',source_zip='source.zip',
            source_manifest='source.json',files={},recovery=self.c,
            backup_evidence=dict(path=str(self.manifest),sha256=__import__('hashlib').sha256(self.manifest.read_bytes()).hexdigest(),
                location_kind='local',location_description='Artificial local receipt',author_decision='D-054'))
        p=self.root/'release.json';p.write_bytes(encoded(release))
        candidate={**release,'status':'prepared_not_authorized','author_decision':None,'backup_evidence':None}
        metadata=(self.args['plan'],self.args['manifest'],self.args['task_ids'],self.args['repeats'],self.args['bindings'],{})
        with patch('communication_pruning.study_recovery.recovery_candidate',return_value=candidate), patch('communication_pruning.study_release.bound_metadata',return_value=metadata):
            context=live_context(self.root,p)
            self.assertFalse(context['synthetic'])
            changed=copy.deepcopy(release);changed['segment_cap_usd']='36.12';p.write_bytes(encoded(changed))
            with self.assertRaises(StudyStop):live_context(self.root,p)
            changed=copy.deepcopy(release);changed['backup_evidence']['author_decision']='D-053';p.write_bytes(encoded(changed))
            with self.assertRaises(StudyStop):live_context(self.root,p)
            p.write_bytes(encoded(release));self.manifest.write_bytes(b'changed')
            with self.assertRaises(StudyStop):live_context(self.root,p)
