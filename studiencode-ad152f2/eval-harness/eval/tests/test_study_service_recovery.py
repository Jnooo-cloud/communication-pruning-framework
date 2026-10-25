"""D-056 artificial exception, inherited counters, exact replay and cost tests."""
from decimal import Decimal
from pathlib import Path
import json
import tempfile
import unittest

from communication_pruning.configurations import bank
from communication_pruning.data import load_task
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01
from communication_pruning.openrouter import encoded,payload
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.rate_limit import RateAdapter,RateStop,classify
from communication_pruning.study import StudyStop
from communication_pruning.study_resume import read_json
from communication_pruning.study_service_recovery import run_continuation,inspect_continuation,result_paths
from study_fixture import fixture
from test_rate_limit import Clock,RateTransport,args,request,seed


def error503():
    return encoded(dict(error=dict(code=503,message='Provider returned error',metadata=dict(
        provider_name='Google',is_byok=False,raw=json.dumps(dict(error=dict(code=503,
        message='Authentication backend unavailable.',status='UNAVAILABLE')))))))


def exception_seed(folder,req,clock):
    value=seed(folder,req,error503(),clock,origin='old-unpriced-503')
    p=Path(value['received']['path']);receipt=json.loads(p.read_bytes());receipt['http_status']=503
    p.write_bytes(encoded(receipt))
    from hashlib import sha256
    value['received']['sha256']=sha256(p.read_bytes()).hexdigest()
    return {**value,'author_decision':'D-056','held_reserve_usd':'0.14'}


class ServiceTransport(RateTransport):
    def __init__(self,*a,service_at=None,**kw):super().__init__(*a,**kw);self.service_at=service_at
    def __call__(self,endpoint,body=None):
        result=super().__call__(endpoint,body)
        if endpoint=='chat/completions' and self.calls==self.service_at:return 503,error503()
        return result


class ServiceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.clock=Clock()
        self.exception=exception_seed(self.root/'old',request(),self.clock)
        self.folder=self.root/'new';self.folder.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def adapter(self,transport,initial=1,**kw):
        return RateAdapter(self.folder,transport,budget_args=args(),initial_retries=initial,
            exception_seed=self.exception,clock=self.clock,sleep=self.clock.sleep,**kw)
    def test_exception_preserves_global_counter_and_is_not_a_zero_cost_bill(self):
        tr=RateTransport();a=self.adapter(tr);response=a(request())
        self.assertEqual(a.retries,1);self.assertEqual(a.budget.calls,1)
        b=read_json(self.folder/'00001-binding.json')
        self.assertEqual((b['retry'],b['global_retry'],b['retry_kind']),(1,1,'authorized_503'))
        self.assertEqual(a.budget.cost,Decimal('.0000108'))
        restored=self.adapter(None,restore=True,audit_only=True)
        self.assertEqual(restored(request()),response);self.assertEqual(restored.retries,1)
        self.assertFalse(restored.exception_pending)
        with self.assertRaises(RateStop):self.adapter(None,initial=0,restore=True)
    def test_exception_uses_first_extra_attempt_only_one_429_retry_remains(self):
        tr=RateTransport([1,2]);a=self.adapter(tr)
        with self.assertRaises(RateStop):a(request())
        self.assertEqual(tr.calls,2);self.assertEqual(a.retries,2)
        self.assertEqual(sum(self.clock.waits),150)
        restored=self.adapter(tr,restore=True)
        with self.assertRaises(RateStop):restored(request())
        self.assertEqual(tr.calls,2)
    def test_inherited_global_bound_survives_exception_and_restart(self):
        tr=RateTransport([2,4]);a=self.adapter(tr,initial=19);a(request());a(request('another'))
        self.assertEqual(a.retries,20)
        restored=self.adapter(tr,initial=19,restore=True)
        with self.assertRaises(RateStop):restored(request('third'))
        self.assertEqual(tr.calls,4)
    def test_only_exact_bound_first_request_may_dispatch(self):
        tr=RateTransport();a=self.adapter(tr)
        with self.assertRaises(RateStop):a(request('different'))
        self.assertEqual(tr.calls,0)
        from dataclasses import replace
        with self.assertRaises(RateStop):a(replace(request(),instruction='changed'))
        self.assertEqual(tr.calls,0)
        Path(self.exception['response']['path']).write_bytes(b'{}')
        with self.assertRaises(RateStop):self.adapter(tr,restore=True)
    def test_new_503_is_unknown_and_blocks_every_restore(self):
        tr=ServiceTransport(service_at=1);a=self.adapter(tr)
        with self.assertRaises(BudgetStop):a(request())
        self.assertEqual(a.budget.snapshot()['held_reservation_usd'],'0.14')
        self.assertIsNone(a.budget.snapshot()['total_cost_usd'])
        with self.assertRaises(BudgetStop):self.adapter(tr,restore=True)
        self.assertEqual(tr.calls,1)
    def test_safe_wait_interruption_retains_exception_and_original_counter(self):
        tr=RateTransport();a=self.adapter(tr);self.clock.interrupt=True
        with self.assertRaises(KeyboardInterrupt):a(request())
        self.assertEqual(tr.calls,0)
        self.clock.interrupt=False;restored=self.adapter(tr,restore=True);restored(request())
        self.assertEqual(restored.retries,1);self.assertEqual(tr.calls,1)


class ServiceStudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.clock=Clock()
        self.context=fixture(self.root/'data');plan=self.context['plan']
        self.prefix=next(i for i,s in enumerate(plan['slots']) if s['planned_calls']>=7)
        self.slot=plan['slots'][self.prefix];slot=self.slot
        task,_=load_task(self.context['source_path'],slot['task_id'],self.context['manifest'],phase='spatial')
        config=next(x for x in bank() if x.config_id==slot['config_id']);old=ServiceTransport(service_at=5)
        seeds=[];exception=[];run_prefix=plan['sha256'][:16]+'-R1-'
        def capture(req):
            status,raw=old('chat/completions',encoded(payload(req,producer_limit=1024)))
            if status==503:
                exception.append(exception_seed(self.root/'old-error',req,self.clock));raise RateStop('old service stop')
            seeds.append(seed(self.root/f'old-{old.calls}',req,raw,self.clock,origin=f'old-{old.calls}'))
            return classify(status,raw,req.max_output_tokens)[1]
        with self.assertRaises(RateStop):execute(task,config,capture,run_id=run_prefix+slot['slot_id'],producer_limit=1024,failure_policy=F01)
        self.assertEqual(len(seeds),4);self.assertEqual(len(exception),1)
        c=dict(plan_sha256=plan['sha256'],completed_before=self.prefix,old_attempts=6,
            old_known_cost_usd='.0000432',old_reserve_usd='.28',phase_cap_usd='36.12',remaining_cap_usd='35.8399568',
            remaining_max_calls=30120,base_generations=[f'fake-gen-{n}' for n in range(1,5)],
            seeds=seeds,exception_seed=exception[0],initial_retries=1,base_results={},run_prefix=run_prefix)
        self.context.update(c=c,folder=self.root/'run',control=self.root/'control',base_guard=lambda:None,
            adapter_options=dict(clock=self.clock,sleep=self.clock.sleep))
        self.tr=ServiceTransport();self.tr.calls=4
    def tearDown(self):self.tmp.cleanup()
    def test_four_old_answers_cost_once_checkpoint_and_continuation(self):
        report=run_continuation(**self.context,transport=self.tr,stop_after_slots=self.prefix+1)
        self.assertEqual(report['budget']['calls'],self.slot['planned_calls']-4)
        self.assertEqual(report['retry_attempts'],1);self.assertTrue(report['service_exception_consumed'])
        r=read_json(self.root/f"run/slots/{self.slot['slot_id']}-result.json")
        self.assertEqual(Decimal(r['cost_usd']),Decimal(report['known_phase_usd']))
        provenance=read_json(self.root/f"run/slots/{self.slot['slot_id']}-provenance.json")
        self.assertEqual([x['origin'] for x in provenance[:4]],[f'old-{n}' for n in range(1,5)])
        state=inspect_continuation(**self.context)
        with self.assertRaises(FileExistsError):run_continuation(**self.context,transport=self.tr,stop_after_slots=self.prefix+2)
        run_continuation(**self.context,transport=self.tr,resume_from=state['resume_token'],stop_after_slots=self.prefix+2)
        self.assertEqual(inspect_continuation(**self.context)['completed_slots'],self.prefix+2)
        with self.assertRaises(StudyStop):result_paths(self.context['c'],self.context['plan'],self.root/'run',self.prefix+2)
    def test_safe_partial_reconstruction_keeps_old_journal(self):
        self.clock.interrupt=True
        with self.assertRaises(KeyboardInterrupt):run_continuation(**self.context,transport=self.tr,stop_after_slots=self.prefix+1)
        journal=next((self.root/'run/slots').glob('*journal*.jsonl'));before=journal.read_bytes()
        state=inspect_continuation(**self.context);self.assertEqual(state['completed_slots'],self.prefix)
        self.clock.interrupt=False
        run_continuation(**self.context,transport=self.tr,resume_from=state['resume_token'],stop_after_slots=self.prefix+1)
        self.assertEqual(journal.read_bytes(),before)
        self.assertEqual(inspect_continuation(**self.context)['completed_slots'],self.prefix+1)
        self.assertEqual(self.tr.calls,self.slot['planned_calls'])


if __name__=='__main__':unittest.main()
