"""Finite G1-G5/G7 invented recovery checks; never load real study content.

The caller archives exact sources before execution and retains every trial.
The modified fake transport is scoped to this fixture; no provider exists.
"""
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import json
import unittest

from communication_pruning import phase_budget
from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.rate_limit import RateStop, RateAdapter, classify
from communication_pruning.contracts import Request, TaskInput
from communication_pruning.study import file_hash
from study_preparation import final_r125_resume as core, final_r_clean_resume as clean
from study_preparation import final_r_resume as inner, final_preflight as gate, final_execution as native
from tests.test_final_r_clean_resume import CleanFixture
from tests.test_final_preflight import trial_directory
from tests.test_final_rate_resume import FakeClock
from tests.study_fixture import FakeTransport

_ORIGINAL_FAKE=FakeTransport.__call__

def scripted_fake(self,endpoint,body=None):
    status,raw=_ORIGINAL_FAKE(self,endpoint,body)
    action=getattr(self,'actions',{}).get(self.calls) if endpoint=='chat/completions' else None
    if action:
        obj=json.loads(raw)
        obj['choices']=[{'finish_reason':'error','error':{'code':429,'metadata':{'error_type':'rate_limit_exceeded'}},
            'message':{'role':'assistant','content':'INVENTED_FREE429_NOT_AN_ANSWER'}}]
        obj['usage'].update(prompt_tokens=0,completion_tokens=0,total_tokens=0,cost='0')
        if action=='unknown':obj['usage'].pop('cost')
        elif action=='cost':obj['usage']['cost']='0.001'
        elif action=='http':status=429
        elif action=='provider':obj['provider']='Other'
        elif action=='other':obj['choices'][0]['error']['code']=503
        elif action=='tokens':obj['usage'].update(prompt_tokens=1,total_tokens=1)
        elif action!='free':raise AssertionError(action)
        raw=encoded(obj)
    return status,raw


class FixedDateTime(datetime):
    @classmethod
    def now(cls,tz=None):return datetime.fromtimestamp(100,tz or timezone.utc)


class R125Fixture(CleanFixture):
    def __init__(self,root):
        with patch.object(phase_budget,'datetime',FixedDateTime):
            super().__init__(root)
            state=self.initialize_clean();self.confirm_clean(state)
            block=self.plan['panels']['R'][2]
            before=0
            for slot in block['slots']:
                if slot['arm']=='F':break
                config,rounds,_=native._configuration(self.candidate,block,slot['arm'],{'spatial_q':self.q,'temporal_qst':None})
                before+= (1 if slot['arm']=='S' else 5) if config is None else rounds*len(config.roles)+1
            self.transport.actions={self.transport.calls+before+2:'free'}
            try:self.run_clean()
            except BudgetStop:pass
            else:raise AssertionError('retained free429 must stop old adapter')
        self.previous_binding,self.previous_folder=self.binding,self.folder
        self.clock=FakeClock(100)
        ledger=(self.folder/'budget.jsonl').read_bytes()
        raw=[json.loads(line) for line in ledger.splitlines()]
        retained_calls=(len(raw)-1)//2
        retained_cost=sum((Decimal(r['usage']['cost_usd']) for r in raw if r['kind']=='settled'),Decimal(0))
        review=self.file('r125-origin-review.json',dict(inner_binding_sha256=self.binding['sha256'],
            ledger_sha256=file_hash(self.folder/'budget.jsonl'),completed_blocks=self.plan['counts']['P']+2,
            accepted=True,not_implementation_author=True,reviewer='separate-invented-reviewer'))
        backup=self.file('r125-origin-backup.json',dict(artificial_only=True,full_reread=True))
        self.bound=self.file('r125-call-bound.json',dict(schema='z52-r125-call-bound/v1',accepted=True,
            not_implementation_author=True,reviewer='separate-invented-reviewer',original_max_calls=raw[0]['max_calls'],
            retained_calls=retained_calls,lost_calls_upper_bound=0,additional_prior_calls_upper_bound=self.incident['known_calls']+1,
            remaining_calls=raw[0]['max_calls']-retained_calls-self.incident['known_calls']-1,sources=[review]))
        cost=self.file('r125-cost-evidence.json',dict(additional_observed_charge_usd='0.28559945',
            retained_native_cost_usd=str(retained_cost),charge_is_arm_attributed=False,
            account_observation_already_includes_charge=True))
        self.origin=core.prepare_origin(self.binding,self.candidate,self.plan,
            review=review,backup=backup,call_bound=self.bound,cost_evidence=cost)
        self.folder=self.previous_folder.parent/'recovery-R00125/live'
        self.binding=core.prepare_binding(self.candidate,self.plan,inner_binding=self.previous_binding,origin=self.origin,
            folder=self.folder,control=self.control,witness=self.folder.parent/'witness',owner='artificial-executor')
        self.initial_physical=self.transport.calls
        self.initial_loads,self.initial_selections=len(self.loads),len(self.selections)
        self.retained_files=core._all_files(self.previous_folder)

    def initialize_r125(self):
        return core.initialize(self.binding,self.candidate,self.plan,**self.args(),checkpoint=self.checkpoint)

    def coverage_r125(self,amount='100'):
        budget=core._budget(self.binding,self.plan,self.folder,existing=True)
        return dict(binding_sha256=self.binding['sha256'],origin='artificial_fixture',observed_epoch=90,
            valid_until_epoch=999,available_usd=amount,native_cost_at_observation_usd=str(budget.cost))

    def run_r125(self,end=None,coverage=None):
        return core.run_section(self.binding,self.candidate,self.plan,**self.args(),
            section_end=self.binding['first_hold'] if end is None else end,
            coverage=self.coverage_r125() if coverage is None else coverage,
            **self.dependencies(),sleep=self.clock.sleep)

    def confirm_r125(self,state):return self.confirm_for(core,self.binding,state,'r125')

    def finish_r125_panel(self,panel):
        evidence=core.analyze_panel(self.binding,self.candidate,self.plan,panel,**self.args())
        prepared=core.prepare_panel_backup(self.binding,self.candidate,self.plan,panel,**self.args(),checkpoint=self.checkpoint)
        review=self.file('r125-panel-review-'+panel+'.json',dict(binding_sha256=self.binding['sha256'],panel=panel,
            analysis_sha256=evidence['sha256'],reviewer='separate-invented-reviewer',not_implementation_author=True,accepted=True))
        remote=self.file('r125-panel-remote-'+panel+'.json',dict(artificial_only=True,binding_sha256=self.binding['sha256'],
            panel=panel,analysis_sha256=evidence['sha256'],archive_sha256=prepared['backup']['sha256'],
            members=prepared['backup']['members'],full_reread=True,accepted=True,destination='artificial_local'))
        return core.close_panel(self.binding,self.candidate,self.plan,panel,**self.args(),review=review,remote_backup=remote)


class R125Tests(unittest.TestCase):
    def setUp(self):
        self.fake_patch=patch.object(FakeTransport,'__call__',scripted_fake)
        self.fake_patch.start();self.addCleanup(self.fake_patch.stop)

    def test_G1_G2_exact_adoption_separate_charge_and_no_cost_for_seed(self):
        with trial_directory() as directory:
            f=R125Fixture(directory);state=f.initialize_r125()
            self.assertEqual(state['secondary_completed_blocks'],2)
            self.assertEqual(len(state['rows']),12)
            self.assertEqual(state['budget']['calls'],0)
            self.assertEqual(core._all_files(f.previous_folder),f.retained_files)
            self.assertEqual(f.transport.calls,f.initial_physical)
            self.assertFalse(state['historical_witness_continuity'])
            budget=core._budget(f.binding,f.plan,f.folder,existing=True)
            self.assertEqual(budget.cap,Decimal(f.origin['ledger_prefix']['original_cap_usd'])-Decimal(f.origin['ledger_prefix']['known_cost_usd'])-core.CHARGE)
            self.assertEqual(budget.max_calls,f.origin['call_limits']['remaining_calls'])
            self.assertEqual(state['levels']['additional_observed_charge_usd'],'0.28559945')
            with self.assertRaises(Exception):f.initialize_r125()

    def test_G3_G4_first_request_exact_seed_replay_wait_and_native_rows(self):
        with trial_directory() as directory:
            f=R125Fixture(directory);f.initialize_r125();state=f.run_r125()
            self.assertEqual(state['secondary_completed_blocks'],3)
            self.assertEqual(len(state['rows']),18)
            first=gate.read_json(f.folder/'dispatch/00001-binding.json')
            self.assertEqual(first['logical_id'],f.origin['first_logical_id'])
            self.assertEqual(first['request_sha256'],f.origin['first_request_sha256'])
            self.assertEqual(first['retry'],1);self.assertEqual(first['global_retry'],1)
            self.assertEqual(f.clock.sleeps,[30])
            waited=gate.read_json(f.folder/'physical/00001.json')
            self.assertEqual(waited['observed_sleep_seconds'],30)
            self.assertEqual(waited['requested_sleep_seconds'],30)
            self.assertEqual(len(list((f.folder/'replays').glob('*.json'))),1)
            self.assertEqual(len(f.loads),f.initial_loads);self.assertEqual(len(f.selections),f.initial_selections)
            self.assertEqual(core._all_files(f.previous_folder),f.retained_files)
            self.assertEqual(state['continuation_new_calls'],f.transport.calls-f.initial_physical)
            self.assertEqual(core.inspect_study(f.binding,f.candidate,f.plan,**f.args()),state)

    def test_G3_second_free_retry_and_third_stops(self):
        for actions,success,expected_calls in [(['free'],True,None),(['free','free'],False,2)]:
            with self.subTest(actions=actions),trial_directory() as directory:
                f=R125Fixture(directory);f.initialize_r125()
                f.transport.actions.update({f.transport.calls+i+1:a for i,a in enumerate(actions)})
                if success:
                    state=f.run_r125();self.assertEqual(state['free429_retries'],2)
                    self.assertEqual(sum(f.clock.sleeps),150)
                    self.assertEqual(core._adapter(f.binding,f.plan,f.folder,audit_only=True).retries,2)
                else:
                    with self.assertRaises(RateStop):f.run_r125()
                    self.assertEqual(f.transport.calls-f.initial_physical,expected_calls)
                    self.assertTrue((f.folder/'STOP.json').exists())

    def test_G3_global_twenty_persists_with_seed_inherited_retry(self):
        # This focused D055 mechanism test uses exact known-free seed evidence;
        # kernel integration above proves the outer physical dispatch guard.
        with trial_directory() as directory:
            f=R125Fixture(directory);f.initialize_r125()
            adapter=core._adapter(f.binding,f.plan,f.folder,transport=f.transport,clock=f.clock,sleep=f.clock.sleep)
            retained=core._retained(f.previous_binding,f.candidate,f.plan,f.folder/'retained')
            request=retained['pending']
            adapter(request)
            self.assertEqual(adapter.retries,1)
            task=request.task
            for index in range(9):
                f.transport.actions.update({f.transport.calls+1:'free',f.transport.calls+2:'free'})
                adapter(Request('invented-bound-'+str(index),task,'evidence',1,'Invented instruction',(),1024))
            self.assertEqual(adapter.retries,19)
            final=Request('invented-bound-last',task,'evidence',1,'Invented instruction',(),1024)
            f.transport.actions.update({f.transport.calls+1:'free'})
            adapter(final)
            self.assertEqual(adapter.retries,20)
            adapter=core._adapter(f.binding,f.plan,f.folder,transport=f.transport,clock=f.clock,sleep=f.clock.sleep)
            self.assertEqual(adapter.retries,20)
            last=Request('invented-bound-reject',task,'evidence',1,'Invented instruction',(),1024)
            f.transport.actions.update({f.transport.calls+1:'free'})
            before=f.transport.calls
            with self.assertRaises(RateStop):adapter(last)
            self.assertEqual(f.transport.calls,before+1)
            with self.assertRaises(RateStop):core._adapter(f.binding,f.plan,f.folder,transport=f.transport,clock=f.clock,sleep=f.clock.sleep)(last)
            self.assertEqual(f.transport.calls,before+1)

    def test_G3_nonfree_or_foreign_error_never_retries(self):
        for action in ('unknown','cost','http','provider','other','tokens'):
            with self.subTest(action=action),trial_directory() as directory:
                f=R125Fixture(directory);f.initialize_r125()
                f.transport.actions[f.transport.calls+1]=action
                with self.assertRaises(Exception):f.run_r125()
                self.assertEqual(f.transport.calls-f.initial_physical,1)
                self.assertTrue((f.folder/'STOP.json').exists())
                with self.assertRaises(Exception):f.run_r125()
                self.assertEqual(f.transport.calls-f.initial_physical,1)

    def test_G1_original_mutation_and_missing_call_bound_stop(self):
        with trial_directory() as directory:
            f=R125Fixture(directory);f.initialize_r125()
            target=f.previous_folder/'provider/00001-binding.json'
            target.write_bytes(target.read_bytes()+b' ')
            with self.assertRaises(Exception):f.run_r125()
            self.assertEqual(f.transport.calls,f.initial_physical)
        with trial_directory() as directory:
            f=R125Fixture(directory)
            value=gate.read_json(f.bound['path']);value['remaining_calls']+=1
            Path(f.bound['path']).write_bytes(encoded(value))
            with self.assertRaises(Exception):f.initialize_r125()

    def test_G2_account_baseline_calendar_budget_and_claim_gates(self):
        with trial_directory() as directory:
            f=R125Fixture(directory);f.initialize_r125()
            for coverage in (f.coverage_r125('.279999'),{**f.coverage_r125(),'native_cost_at_observation_usd':'.28559945'}):
                with self.assertRaises(Exception):core.pre_dispatch(f.binding,f.candidate,f.plan,**f.args(),section_end=f.binding['first_hold'],coverage=coverage)
            core.pre_dispatch(f.binding,f.candidate,f.plan,**f.args(),section_end=f.binding['first_hold'],coverage=f.coverage_r125('.28'))
            with self.assertRaises(Exception):core.accounting_view(f.binding,Decimal(f.origin['ledger_prefix']['original_cap_usd']),reserve_calls=37)
            f.clock.value=1001
            with self.assertRaises(Exception):f.run_r125()
            self.assertEqual(f.transport.calls,f.initial_physical)

    def test_G5_G7_native_R_T_F_closures_and_mandatory_recovery_confirmation(self):
        with trial_directory() as directory:
            f=R125Fixture(directory);f.initialize_r125();state=f.run_r125()
            with self.assertRaises(Exception):f.run_r125(f.candidate['section_ends'][-2])
            f.confirm_r125(state)
            with self.assertRaises(Exception):f.run_r125(f.candidate['section_ends'][-2])
            f.finish_r125_panel('R')
            for panel,end in [('T',f.candidate['section_ends'][-2]),('F',f.candidate['section_ends'][-1])]:
                state=f.run_r125(end);f.confirm_r125(state);f.finish_r125_panel(panel)
            self.assertTrue(state['complete'])
            self.assertEqual(state['secondary_completed_blocks'],5)
            report=gate.read_json(f.folder/'panels/R/analysis.json')
            self.assertFalse(report['historical_witness_continuity'])
            self.assertFalse(report['additional_charge_attributed_to_arms'])
            self.assertIn('original_analysis',report)

if __name__=='__main__':unittest.main()
