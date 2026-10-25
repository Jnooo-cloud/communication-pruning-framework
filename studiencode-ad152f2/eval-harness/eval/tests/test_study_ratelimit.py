"""Synthetic raster continuation/reconstruction, independent from live data."""
from pathlib import Path
import tempfile
import unittest

from communication_pruning.data import digest
from communication_pruning.openrouter import encoded
from communication_pruning.study import StudyStop
from communication_pruning.study_ratelimit import run_continuation, inspect_continuation, result_paths
from study_fixture import fixture
from test_rate_limit import Clock, RateTransport, seed


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.context=fixture(self.root/'data');self.clock=Clock()
        plan=self.context['plan']
        c=dict(plan_sha256=plan['sha256'],completed_before=0,old_attempts=0,
            old_known_cost_usd='0',old_reserve_usd='.14',phase_cap_usd='36.12',remaining_cap_usd='35.98',
            remaining_max_calls=30120,base_generations=[],seeds=[],base_results={},run_prefix=plan['sha256'][:16]+'-R1-')
        self.context.update(c=c,folder=self.root/'run',control=self.root/'control',base_guard=lambda:None,
                            adapter_options=dict(clock=self.clock,sleep=self.clock.sleep))
        self.transport=RateTransport([2])
    def tearDown(self):self.tmp.cleanup()
    def run_to(self,n,**kw):return run_continuation(**self.context,transport=self.transport,stop_after_slots=n,**kw)
    def test_checkpoint_inspection_continuation_and_single_claim(self):
        report=self.run_to(1);self.assertEqual(report['completed_slots'],1)
        checked=inspect_continuation(**self.context);self.assertEqual(checked['retry_attempts'],1)
        old={p:p.read_bytes() for p in (self.root/'run'/'slots').iterdir()}
        with self.assertRaises(FileExistsError):self.run_to(2)
        self.run_to(2,resume_from=checked['resume_token'])
        self.assertEqual(inspect_continuation(**self.context)['completed_slots'],2)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in old.items()))
        with self.assertRaises(StudyStop):result_paths(self.context['c'],self.context['plan'],self.root/'run',2)
        with self.assertRaises(StudyStop):self.run_to(3,resume_from=checked['resume_token'])
    def test_partial_journal_preserved_response_replayed_and_no_duplicate_cost(self):
        self.clock.interrupt=True
        with self.assertRaises(KeyboardInterrupt):self.run_to(1)
        self.assertEqual(self.transport.calls,2)
        partial=next((self.root/'run'/'slots').glob('*journal*.jsonl'));old=partial.read_bytes()
        state=inspect_continuation(**self.context);self.assertEqual(state['completed_slots'],0)
        self.clock.interrupt=False
        report=self.run_to(1,resume_from=state['resume_token'])
        self.assertEqual(partial.read_bytes(),old)
        self.assertEqual(report['retry_attempts'],1)
        planned=self.context['plan']['slots'][0]['planned_calls']
        self.assertEqual(self.transport.calls,planned+1)
        checked=inspect_continuation(**self.context);self.assertEqual(checked['completed_slots'],1)
    def test_changed_result_or_new_source_blocks_without_transport(self):
        self.run_to(1);state=inspect_continuation(**self.context);calls=self.transport.calls
        p=next((self.root/'run'/'slots').glob('*result.json'));p.write_bytes(encoded({'invented':True}))
        with self.assertRaises(StudyStop):self.run_to(2,resume_from=state['resume_token'])
        self.assertEqual(self.transport.calls,calls)
    def test_unknown_started_dispatch_cannot_be_reconstructed(self):
        self.transport=RateTransport(fail_at=2,mode='interrupt')
        with self.assertRaises(KeyboardInterrupt):self.run_to(1)
        with self.assertRaises(Exception):inspect_continuation(**self.context)
        self.assertEqual(self.transport.calls,2)

    def test_seeded_partial_slot_keeps_old_answer_and_counts_cost_once(self):
        from decimal import Decimal
        from communication_pruning.configurations import bank
        from communication_pruning.data import load_task
        from communication_pruning.execution import execute
        from communication_pruning.failure_policy import F01
        from communication_pruning.openrouter import payload
        from communication_pruning.rate_limit import classify,RateStop
        from communication_pruning.study_resume import read_json
        c=self.context['c'];slot=self.context['plan']['slots'][0]
        task,_=load_task(self.context['source_path'],slot['task_id'],self.context['manifest'],phase='spatial')
        config=next(x for x in bank() if x.config_id==slot['config_id'])
        seeds=[];old=RateTransport([2])
        def old_adapter(req):
            status,raw=old('chat/completions',encoded(payload(req,producer_limit=1024)))
            seeds.append(seed(self.root/f'old-{old.calls}',req,raw,self.clock,origin=f'old-{old.calls}'))
            outcome,response,_,_=classify(status,raw,req.max_output_tokens)
            if outcome=='rate_limited':raise RateStop('old interruption')
            return response
        with self.assertRaises(RateStop):
            execute(task,config,old_adapter,run_id=c['run_prefix']+slot['slot_id'],producer_limit=1024,failure_policy=F01)
        c.update(seeds=seeds,base_generations=['fake-gen-1','fake-gen-2'],old_attempts=2,
                 old_known_cost_usd='.0000108',remaining_cap_usd='35.9799892')
        self.transport=RateTransport();self.transport.calls=2
        report=self.run_to(1)
        self.assertEqual(report['budget']['calls'],slot['planned_calls']-1)
        self.assertEqual(report['retry_attempts'],1)
        result=read_json(next((self.root/'run'/'slots').glob('*result.json')))
        self.assertEqual(Decimal(result['cost_usd']),Decimal(report['known_phase_usd']))
        self.assertEqual(Decimal(result['cost_usd']),Decimal('.0000108')*slot['planned_calls'])
        provenance=read_json(next((self.root/'run'/'slots').glob('*provenance.json')))
        self.assertEqual(provenance[0]['origin'],'old-1')
        self.assertEqual(inspect_continuation(**self.context)['completed_slots'],1)


if __name__=='__main__':unittest.main()
