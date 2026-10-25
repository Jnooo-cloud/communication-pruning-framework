"""H1-H7 invented end-to-end continuation through native R/T/F boundaries."""
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
import unittest

from communication_pruning.study import file_hash
from study_preparation import final_technical_resume as core, final_r125_resume as old
from study_preparation import final_execution as native, final_preflight as gate
from study_preparation.final_plan import make_plan
from tests.test_final_r125_resume import R125Fixture, scripted_fake
from tests.study_fixture import FakeTransport
from tests.test_final_preflight import trial_directory


def technical_fake(self,endpoint,body=None):
    if endpoint=='chat/completions' and self.calls+1==getattr(self,'technical_failure_call',None):
        self.technical_failure_call=None
        raise TimeoutError('invented preserved timeout')
    if endpoint=='chat/completions' and self.calls+1==getattr(self,'paid_failure_call',None):
        import json
        from communication_pruning.openrouter import encoded
        self.paid_failure_call=None
        status,raw=scripted_fake(self,endpoint,body);data=json.loads(raw);data.pop('choices');data['error']={'code':503}
        return 503,encoded(data)
    return scripted_fake(self,endpoint,body)


class TechnicalFixture(R125Fixture):
    def __init__(self,root):
        def expanded(frame,**kwargs):
            if kwargs['counts']['P']==2:kwargs['counts']['R']=4
            return make_plan(frame,**kwargs)
        with patch('tests.test_final_r_clean_resume.make_plan',side_effect=expanded):
            super().__init__(root)
        self.initialize_r125();state=self.run_r125();self.confirm_r125(state)
        self.transport.actions={}
        target=self.plan['panels']['R'][3]
        target_arm=next(s['arm'] for s in target['slots'] if s['arm'] not in ('S','S-k'))
        original=self.transport
        before=0
        for slot in target['slots']:
            config,rounds,_=native._configuration(self.candidate,target,slot['arm'],{'spatial_q':self.q,'temporal_qst':None})
            count=(1 if slot['arm']=='S' else 5) if config is None else rounds*len(config.roles)+1
            before+=count
            if slot['arm']==target_arm:break
        original.technical_failure_call=original.calls+before
        dependencies=self.dependencies()
        from communication_pruning import phase_budget
        from datetime import datetime,timezone
        clock=self.clock
        class ClockTime(datetime):
            @classmethod
            def now(cls,tz=None):return datetime.fromtimestamp(clock(),tz or timezone.utc)
        try:
            with patch.object(phase_budget,'datetime',ClockTime):
                old.run_section(self.binding,self.candidate,self.plan,**self.args(),section_end=self.candidate['section_ends'][1],
                    coverage=self.coverage_r125(),**dependencies,sleep=self.clock.sleep)
        except Exception as error:
            if not (self.folder/'STOP.json').exists():raise
        else:raise AssertionError('invented technical stop required')
        original.technical_failure_call=None
        self.old_binding,self.old_folder=self.binding,self.folder
        self.origin=core.prepare_origin(self.old_binding,self.candidate,self.plan)
        self.folder=self.old_folder.parent/'technical-R00203/live'
        self.binding=core.prepare_binding(self.candidate,self.plan,inner_binding=self.old_binding,origin=self.origin,
            folder=self.folder,control=self.control,witness=self.folder.parent/'witness',owner='invented-technical-operator')
        self.old_inventory=core._all_files(self.old_folder)

    def init(self):return core.initialize(self.binding,self.candidate,self.plan,**self.args(),checkpoint=self.checkpoint)
    def technical_coverage(self,amount='100'):
        a=core._adapter(self.binding,self.folder,audit_only=True)
        return dict(binding_sha256=self.binding['sha256'],origin='artificial_fixture',observed_epoch=90,
            valid_until_epoch=9999,available_usd=amount,native_cost_at_observation_usd=str(a.cost))
    def run(self,end=None,coverage=None):
        return core.run_section(self.binding,self.candidate,self.plan,**self.args(),
            section_end=self.binding['first_hold'] if end is None else end,
            coverage=self.technical_coverage() if coverage is None else coverage,**self.dependencies(),sleep=self.clock.sleep)
    def confirm_technical(self,state):return self.confirm_for(core,self.binding,state,'technical')
    def close(self,panel):
        evidence=core.analyze_panel(self.binding,self.candidate,self.plan,panel,**self.args())
        prepared=core.prepare_panel_backup(self.binding,self.candidate,self.plan,panel,**self.args(),checkpoint=self.checkpoint)
        review=self.file('technical-review-'+panel+'.json',dict(binding_sha256=self.binding['sha256'],panel=panel,
            analysis_sha256=evidence['sha256'],reviewer='invented-nonauthor',not_implementation_author=True,accepted=True))
        remote=self.file('technical-remote-'+panel+'.json',dict(artificial_only=True,binding_sha256=self.binding['sha256'],panel=panel,
            analysis_sha256=evidence['sha256'],archive_sha256=prepared['backup']['sha256'],members=prepared['backup']['members'],
            full_reread=True,accepted=True,destination='artificial_local'))
        core.close_panel(self.binding,self.candidate,self.plan,panel,**self.args(),review=review,remote_backup=remote)


class TechnicalIntegrationTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(FakeTransport,'__call__',technical_fake);p.start();self.addCleanup(p.stop)

    def test_preserved_prefix_first_replacement_and_panel_boundaries(self):
        with trial_directory() as root:
            f=TechnicalFixture(root);initial=f.transport.calls;state=f.init()
            self.assertEqual(state['secondary_completed_blocks'],3);self.assertEqual(f.transport.calls,initial)
            state=f.run();self.assertEqual(state['secondary_completed_blocks'],4)
            first=gate.read_json(f.folder/'dispatch/000001-binding.json')
            self.assertEqual(first['logical_id'],f.origin['pending_seed']['logical_id'])
            self.assertEqual(first['request_sha256'],f.origin['pending_seed']['request']['sha256'])
            self.assertEqual(core._all_files(f.old_folder),f.old_inventory)
            with self.assertRaises(Exception):f.run(f.candidate['section_ends'][2])
            f.confirm_technical(state)
            with self.assertRaises(Exception):f.run(f.candidate['section_ends'][2])
            f.close('R')
            r_analysis=gate.read_json(f.folder/'panels/R/analysis.json')
            self.assertIn(f.origin['partial_arm'],r_analysis['affected_arms'])
            for panel,end in zip(('T','F'),f.candidate['section_ends'][2:]):
                f.transport.technical_failure_call=f.transport.calls+1
                if panel=='T':f.transport.paid_failure_call=f.transport.calls+1
                state=f.run(end);f.confirm_technical(state);f.close(panel)
                analysis=gate.read_json(f.folder/'panels'/panel/'analysis.json')
                self.assertEqual(analysis['cost_scope'],'known_billed_costs_only')
                self.assertEqual(len(analysis['technical_unknown_attempts']),1)
                self.assertTrue(analysis['affected_arms']);self.assertTrue(analysis['affected_cost_endpoints'])
                if panel=='T':
                    adjusted=[r for r in state['rows'] if r['panel']=='T' and 'known_technical_failure_cost_usd' in r]
                    self.assertEqual(len(adjusted),1)
                    row=adjusted[0]
                    self.assertEqual(Decimal(row['cost_usd']),Decimal(row['native_terminal_cost_usd'])+Decimal('.0000108'))
            adapter=core._adapter(f.binding,f.folder,audit_only=True)
            for row in state['rows']:
                if row['panel']=='F' and row['failed_role']:
                    self.assertFalse(any(r['dispatch']['logical_id'].startswith(row['run_id']+':'+row['failed_role']+':') for r in adapter.records))
            self.assertTrue(state['complete']);self.assertEqual(core._all_files(f.old_folder),f.old_inventory)

    def test_undercoverage_and_wrong_hold_do_not_send(self):
        with trial_directory() as root:
            f=TechnicalFixture(root);f.init();before=f.transport.calls
            with self.assertRaises(Exception):f.run(coverage=f.technical_coverage('.5'))
            with self.assertRaises(Exception):f.run(f.binding['first_hold']+1)
            self.assertEqual(f.transport.calls,before)

    def test_known_fields_exclude_all_new_reserves(self):
        with trial_directory() as root:
            f=TechnicalFixture(root)
            base=old.accounting_view(f.old_binding,Decimal(f.origin['retained_cost_usd'])+Decimal('.02'))
            value=core.accounting_view(f.binding,Decimal('.02'),held=Decimal('.28'))
            for key in ('known_secondary_answer_cost_usd','new_known_cost_usd','known_study_cost_usd',
                        'known_project_cost_usd','known_secondary_cost_usd','native_budget_burden_usd'):
                self.assertEqual(value[key],base[key],key)
            for key in ('overall','secondary'):
                self.assertEqual(Decimal(value['available_usd'][key]),Decimal(base['available_usd'][key])-Decimal('.42'))


if __name__=='__main__':unittest.main()
