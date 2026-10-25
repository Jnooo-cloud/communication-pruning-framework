"""H2-H4 finite artificial technical failures; no network or real tasks."""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import json
import unittest

from communication_pruning.technical_retry import TechnicalAdapter, TechnicalStop, ref
from communication_pruning.openrouter import encoded, payload
from communication_pruning.failure_policy import ModelFailure
from tests.study_fixture import FakeTransport
from tests.test_rate_limit import Clock, request, seed, RateTransport
from contextlib import contextmanager
from tests.test_final_preflight import trial_directory as original_trial_directory


@contextmanager
def trial_directory():
    with original_trial_directory() as directory:
        yield Path(directory)


class Script(FakeTransport):
    def __init__(self,actions=(),**kwargs):
        super().__init__(**kwargs); self.actions=list(actions); self.physical=0; self.requests=[]
    def __call__(self,endpoint,body=None):
        self.physical+=1; self.requests.append(body)
        action=self.actions[self.physical-1] if self.physical<=len(self.actions) else 'ok'
        if action=='timeout': raise TimeoutError('invented')
        if action=='503': return 503,encoded({'error':{'code':503}})
        if action=='401': return 401,encoded({'error':{'code':401}})
        status,raw=super().__call__(endpoint,body)
        if action=='paid503':
            data=json.loads(raw);data.pop('choices');data['error']={'code':503};return 503,encoded(data)
        if action=='after': return 503,encoded({'error':{'code':503}}),{'Retry-After':'180'}
        return status,raw


class TechnicalTests(unittest.TestCase):
    def adapter(self,folder,transport,clock,**kwargs):
        return TechnicalAdapter(folder,transport,binding='a'*64,cap='20',max_calls=1000,
            clock=clock,sleep=clock.sleep,**kwargs)

    def test_timeout_success_replay_and_readonly_restore(self):
        with trial_directory() as root:
            folder=root/'calls';clock=Clock();transport=Script(['timeout']);a=self.adapter(folder,transport,clock)
            answer=a(request()); self.assertEqual(a.held,Decimal('.14'));self.assertEqual(a.technical_retries,1)
            self.assertEqual(transport.requests,[transport.requests[0]]*2); self.assertEqual(sum(clock.waits),30)
            b=self.adapter(folder,None,clock,restore=True,audit_only=True)
            self.assertEqual(b(request()),answer);self.assertEqual(b.calls,2);self.assertEqual(b.cost,a.cost)
            self.assertIsNone(b.snapshot()['total_cost_usd'])

    def test_per_logical_bound_persists(self):
        with trial_directory() as root:
            clock=Clock();t=Script(['timeout']*5);a=self.adapter(root/'calls',t,clock)
            with self.assertRaises(TechnicalStop):a(request())
            self.assertEqual(t.physical,3);self.assertEqual(a.held,Decimal('.42'))
            b=self.adapter(root/'calls',t,clock,restore=True)
            with self.assertRaises(TechnicalStop):b(request())
            self.assertEqual(t.physical,3);self.assertEqual(sum(clock.waits),150)

    def test_global_bound_persists(self):
        with trial_directory() as root:
            clock=Clock();t=Script(['timeout','ok']*21);a=self.adapter(root/'calls',t,clock)
            for i in range(20):a(request('logical-'+str(i)))
            b=self.adapter(root/'calls',t,clock,restore=True)
            with self.assertRaises(TechnicalStop):b(request('logical-20'))
            self.assertEqual(t.physical,41);self.assertEqual(b.technical_retries,20)

    def test_paid_error_is_in_arm_cost_and_provider_wait_respected(self):
        with trial_directory() as root:
            clock=Clock();t=Script(['paid503','after','ok']);a=self.adapter(root/'calls',t,clock)
            answer=a(request());self.assertEqual(answer.usage.cost_usd,Decimal('.0000108'))
            self.assertEqual(a.cost,Decimal('.0000216'));self.assertEqual(a.held,Decimal('.14'))
            self.assertEqual(a.known_failed_costs(),{'logical-1':Decimal('.0000108')})
            self.assertEqual(sum(clock.waits),210)
            b=self.adapter(root/'calls',None,clock,restore=True,audit_only=True)
            self.assertEqual(b(request()),answer)

    def test_inherited_unknown_first_replacement_and_success_seed(self):
        with trial_directory() as root:
            clock=Clock();t=Script();req=request('old');status,raw=t('chat/completions',encoded(payload(req,producer_limit=1024)))
            s=seed(root/'seed',req,raw,clock);generation=json.loads(raw)['id']
            pending=request('pending');p=root/'pending.json';p.write_bytes(encoded(payload(pending,producer_limit=1024)))
            ps=dict(logical_id='pending',request=ref(p),output_limit=1024,held_reserve_usd='0.14',
                outcome='technical',observed_epoch=clock(),origin='original')
            a=self.adapter(root/'calls',t,clock,seeds=[s],pending_seed=ps,base_generations=[generation])
            self.assertEqual(a(req).text,'Invented output 1');self.assertEqual(a.calls,0)
            with self.assertRaises(TechnicalStop):a(request('wrong'))
            a(pending);self.assertEqual(a.calls,1);self.assertEqual(a.technical_retries,1)
            self.assertEqual(t.physical,2)

    def test_f01_failure_and_bad_answer_not_retried(self):
        with trial_directory() as root:
            clock=Clock();t=Script(fail_at=1,mode='length');a=self.adapter(root/'calls',t,clock)
            response=a(request());self.assertIsInstance(response,ModelFailure);self.assertEqual(t.physical,1)
            self.assertEqual(a(request()),response);self.assertEqual(t.physical,1)
            with self.assertRaises(TechnicalStop):a(replace(request(),instruction='changed'))

    def test_auth_error_stops_without_retry_and_orphan_blocks_restore(self):
        with trial_directory() as root:
            clock=Clock();t=Script(['401']);a=self.adapter(root/'calls',t,clock)
            with self.assertRaises(TechnicalStop):a(request())
            self.assertEqual(t.physical,1)
            with self.assertRaises(TechnicalStop):self.adapter(root/'calls',t,clock,restore=True)

    def test_unknown_reserve_budget_before_second_dispatch(self):
        with trial_directory() as root:
            clock=Clock();t=Script(['timeout']);a=TechnicalAdapter(root/'calls',t,binding='a'*64,cap='.14',max_calls=9,
                clock=clock,sleep=clock.sleep)
            with self.assertRaises(TechnicalStop):a(request())
            self.assertEqual(t.physical,1);self.assertEqual(a.held,Decimal('.14'))

    def test_free429_counter_remains_separate(self):
        with trial_directory() as root:
            clock=Clock();t=RateTransport([1]);a=self.adapter(root/'calls',t,clock,initial_rate_retries=1)
            a(request());self.assertEqual(a.rate_retries,2);self.assertEqual(a.technical_retries,0)

    def test_guard_can_stop_before_any_physical_call(self):
        with trial_directory() as root:
            clock=Clock();t=Script()
            def denied(*args):raise TechnicalStop('expired calendar or insufficient account')
            a=self.adapter(root/'calls',t,clock,guard=denied)
            with self.assertRaises(TechnicalStop):a(request())
            self.assertEqual(t.physical,0);self.assertEqual(a.calls,0)

    def test_mixed_failures_stop_after_three_and_survive_restart(self):
        with trial_directory() as root:
            clock=Clock();base=RateTransport([1]);calls=[]
            def mixed(endpoint,body):
                calls.append(body)
                if len(calls) in (1,3):raise TimeoutError('invented')
                return base(endpoint,body)
            a=self.adapter(root/'calls',mixed,clock)
            with self.assertRaises(TechnicalStop):a(request())
            self.assertEqual(len(calls),3)
            self.assertEqual(sum(clock.waits),150)
            dispatches=[json.loads(p.read_text()) for p in sorted((root/'calls').glob('*-binding.json'))]
            self.assertEqual(dispatches[1]['dispatched_at']-dispatches[0]['dispatched_at'],30)
            self.assertEqual(dispatches[2]['dispatched_at']-dispatches[1]['dispatched_at'],120)
            b=self.adapter(root/'calls',mixed,clock,restore=True)
            with self.assertRaises(TechnicalStop):b(request())
            self.assertEqual(len(calls),3)


if __name__=='__main__':unittest.main()
