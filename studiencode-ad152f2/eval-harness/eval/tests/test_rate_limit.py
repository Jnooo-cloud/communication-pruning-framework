"""Artificial dispatch outcomes only; no provider/network access."""
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from communication_pruning.contracts import Request, TaskInput
from communication_pruning.failure_policy import ModelFailure
from communication_pruning.openrouter import encoded, payload
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.rate_limit import RateAdapter, RateStop, classify
from study_fixture import FakeTransport


class Clock:
    def __init__(self):self.value=1000.;self.waits=[];self.interrupt=False
    def __call__(self):return self.value
    def sleep(self,seconds):
        if self.interrupt:raise KeyboardInterrupt()
        self.waits.append(seconds);self.value+=seconds


class RateTransport(FakeTransport):
    def __init__(self,rate_calls=(),**kw):super().__init__(**kw);self.rate_calls=set(rate_calls)
    def __call__(self,endpoint,body=None):
        status,raw=super().__call__(endpoint,body)
        if endpoint=='chat/completions' and self.calls in self.rate_calls:
            value=json.loads(raw)
            value['usage'].update(prompt_tokens=0,completion_tokens=0,total_tokens=0,cost='0')
            value['choices'][0].update(finish_reason='error',error=dict(code=429,metadata=dict(error_type='rate_limit_exceeded')))
            value['choices'][0]['message']['content']='{"answer'
            raw=encoded(value)
        return status,raw


def request(name='logical-1'):
    return Request(name,TaskInput('task','Question?',('Context.',)), 'linking',1,'Instruction',(),1024)


def args():return dict(cap=Decimal('2'),reserve=Decimal('.14'),max_calls=100,binding='a'*64)


def seed(folder,req,raw,clock,origin='old'):
    folder=Path(folder);folder.mkdir(exist_ok=True)
    received=encoded(dict(http_status=200,response_sha256=sha256(raw).hexdigest()))
    value=dict(logical_id=req.attempt_id,output_limit=req.max_output_tokens,origin=origin,received_at=clock())
    for kind,data in dict(request=encoded(payload(req,producer_limit=1024)),response=raw,received=received).items():
        p=folder/f'{kind}.json';p.write_bytes(data);value[kind]=dict(path=str(p),sha256=sha256(data).hexdigest())
    return value


class RateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)/'provider';self.folder.mkdir();self.clock=Clock()
    def tearDown(self):self.tmp.cleanup()
    def adapter(self,transport,**kw):
        return RateAdapter(self.folder,transport,budget_args=args(),clock=self.clock,sleep=self.clock.sleep,**kw)

    def test_exact_429_never_returns_fragment_and_retries_identical_bytes(self):
        transport=RateTransport([1,2]);adapter=self.adapter(transport)
        result=adapter(request())
        self.assertEqual(result.text,'Invented output 3');self.assertEqual(transport.calls,3)
        self.assertEqual(sum(self.clock.waits),150);self.assertEqual(adapter.retries,2)
        self.assertEqual(transport.bodies,[transport.bodies[0]]*3)
        self.assertEqual(adapter.budget.cost,Decimal('.0000108'))
        restored=self.adapter(None,restore=True,audit_only=True)
        self.assertEqual(restored(request()),result);self.assertEqual(restored.retries,2)

    def test_per_call_bound_survives_restart(self):
        transport=RateTransport([1,2,3]);adapter=self.adapter(transport)
        with self.assertRaises(RateStop):adapter(request())
        self.assertEqual(transport.calls,3)
        restored=self.adapter(transport,restore=True)
        with self.assertRaises(RateStop):restored(request())
        self.assertEqual(transport.calls,3)

    def test_global_bound_does_not_reset_per_call_or_restart(self):
        transport=RateTransport(range(1,44,2));adapter=self.adapter(transport)
        for n in range(20):adapter(request(f'logical-{n}'))
        self.assertEqual(adapter.retries,20)
        restored=self.adapter(transport,restore=True)
        with self.assertRaises(RateStop):restored(request('logical-20'))
        self.assertEqual(transport.calls,41)
        again=self.adapter(transport,restore=True)
        with self.assertRaises(RateStop):again(request('logical-20'))
        self.assertEqual(transport.calls,41)

    def test_wait_interruption_preserves_deadline_and_no_dispatch(self):
        transport=RateTransport([1]);adapter=self.adapter(transport);self.clock.interrupt=True
        with self.assertRaises(KeyboardInterrupt):adapter(request())
        self.assertEqual(transport.calls,1)
        self.clock.interrupt=False;self.clock.value+=10
        restored=self.adapter(transport,restore=True);restored(request())
        self.assertEqual(sum(self.clock.waits),20);self.assertEqual(restored.retries,1)

    def test_success_and_f01_replay_never_send_again(self):
        transport=RateTransport(fail_at=1,mode='length');adapter=self.adapter(transport)
        response=adapter(request());self.assertIsInstance(response,ModelFailure)
        self.assertEqual(adapter(request()),response)
        self.assertEqual(self.adapter(None,restore=True,audit_only=True)(request()),response)
        self.assertEqual(transport.calls,1)
        with self.assertRaises(RateStop):adapter(replace(request(),instruction='Changed'))

    def test_unpriced_transport_and_duplicate_generation_block_restore(self):
        for mode in ('transport','unknown','over','http','duplicate','interrupt'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                transport=RateTransport(fail_at=1,mode=mode)
                adapter=RateAdapter(tmp,transport,budget_args=args(),base_generations=['fake-gen-1'] if mode=='duplicate' else [])
                with self.assertRaises((BudgetStop,KeyboardInterrupt)):adapter(request())
                with self.assertRaises(BudgetStop):RateAdapter(tmp,None,budget_args=args(),restore=True)

    def test_seed_answer_cost_not_recharged_and_seed_429_counts_as_retry(self):
        old=RateTransport([2]);_,valid=old('chat/completions',b'{}');_,rate=old('chat/completions',b'{}')
        req1=request('old-link');req2=request('old-check')
        seeds=[seed(Path(self.tmp.name)/'one',req1,valid,self.clock),seed(Path(self.tmp.name)/'two',req2,rate,self.clock)]
        new=RateTransport();new.calls=2
        adapter=self.adapter(new,seeds=seeds,base_generations=['fake-gen-1','fake-gen-2'])
        self.assertEqual(adapter(req1).text,'Invented output 1');self.assertEqual(adapter.budget.calls,0)
        adapter(req2);self.assertEqual(new.calls,3);self.assertEqual(adapter.retries,1)
        self.assertEqual(adapter.budget.cost,Decimal('.0000108'))
        restored=self.adapter(None,seeds=seeds,base_generations=['fake-gen-1','fake-gen-2'],restore=True,audit_only=True)
        self.assertEqual(restored(req1).text,'Invented output 1')
        duplicate={**seeds[0],'logical_id':'second-assignment'}
        with self.assertRaises(RateStop):self.adapter(None,seeds=[seeds[0],duplicate],base_generations=['fake-gen-1'],restore=True)
        Path(seeds[0]['response']['path']).write_text('{}')
        with self.assertRaises(RateStop):self.adapter(None,seeds=seeds,base_generations=['fake-gen-1','fake-gen-2'],restore=True)

    def test_orphan_evidence_and_altered_billing_stop(self):
        adapter=self.adapter(RateTransport());adapter(request())
        (self.folder/'00002-request.json').write_bytes(b'{}')
        with self.assertRaises(RateStop):self.adapter(None,restore=True)

    def test_cost_cap_reserves_before_transport(self):
        budget=args();budget['cap']=Decimal('.14')
        transport=RateTransport();adapter=RateAdapter(self.folder,transport,budget_args=budget)
        adapter(request())
        with self.assertRaises(BudgetStop):adapter(request('second'))
        self.assertEqual(transport.calls,1)

    def test_only_exact_zero_cost_429_envelope_is_eligible(self):
        _,raw=RateTransport([1])('chat/completions',b'{}');base=json.loads(raw)
        self.assertEqual(classify(200,raw,1024)[0],'rate_limited')
        mutations=[lambda d:d['usage'].update(cost='.0001'),lambda d:d['usage'].pop('cost'),
            lambda d:d['usage'].update(prompt_tokens=1,total_tokens=1),lambda d:d.pop('id'),
            lambda d:d['choices'][0]['error'].update(code=503),lambda d:d['choices'][0]['error'].update(code='429'),
            lambda d:d['choices'][0]['error']['metadata'].update(error_type='other'),
            lambda d:d['choices'].append(d['choices'][0]),lambda d:d.update(error={'code':429}),
            lambda d:d['choices'][0].update(finish_reason='stop')]
        for mutate in mutations:
            value=json.loads(raw);mutate(value)
            with self.subTest(value=value),self.assertRaises(Exception):classify(200,encoded(value),1024)
        with self.assertRaises(RateStop):classify(429,raw,1024)
        with self.assertRaises(Exception):classify(200,raw[:-1]+b',"id":"duplicate-key"}',1024)


if __name__=='__main__':unittest.main()
