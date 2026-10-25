"""Foreign boundary and current-core context tests; no model or network access."""

import copy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from autogen_core.models import UserMessage
from communication_pruning.foreign_observer import BoundaryLedger, ObservedClient, canonical
from communication_pruning.foreign_audit import audit
from communication_pruning.foreign_demo import ScriptedClient, synthetic_bill
from communication_pruning.contracts import Configuration, Response, TaskInput, Usage
from communication_pruning.execution import execute


class ForeignObserverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'boundary.jsonl'
    def tearDown(self): self.temp.cleanup()
    def client(self, billing=None):
        ledger = BoundaryLedger(self.path, 'unit', 'TASK')
        inner = ScriptedClient(ledger, 'solver')
        return ObservedClient(inner, ledger, 'solver', billing), ledger, inner

    def test_framework_identity_is_explicit_and_default_is_preserved(self):
        BoundaryLedger(self.path, 'unit', 'TASK')
        self.assertEqual(json.loads(self.path.read_text().splitlines()[0])['framework'],
                         'autogen-agentchat==0.7.5')
        other = self.path.with_name('other.jsonl')
        BoundaryLedger(other, 'other', 'TASK', framework='GPTSwarm@pinned-test')
        self.assertEqual(json.loads(other.read_text().splitlines()[0])['framework'],
                         'GPTSwarm@pinned-test')
        for index, value in enumerate(('', None, 1)):
            invalid = self.path.with_name(f'invalid-{index}.jsonl')
            with self.assertRaises(ValueError):
                BoundaryLedger(invalid, 'unit', 'TASK', framework=value)
            self.assertFalse(invalid.exists())

    async def test_unknown_price_and_known_zero(self):
        client, ledger, _ = self.client()
        await client.create([UserMessage(content='public', source='user')])
        r = audit(self.path); self.assertEqual(r['unknown_cost_attempts'], 1); self.assertIsNone(r['total_cost_usd'])
        client.billing = lambda result: Usage(20, 3, Decimal('0'), 'synthetic')
        await client.create([UserMessage(content='second', source='user')])
        r = audit(self.path); self.assertEqual(r['unknown_cost_attempts'], 1); self.assertEqual(r['cost_by_source'], {'synthetic': '0'})

    async def test_unsupported_never_starts_client(self):
        client, ledger, inner = self.client()
        with self.assertRaises(ValueError): await client.create([UserMessage(content='x', source='user')], tools=[{'name': 'x'}])
        with self.assertRaises(NotImplementedError): client.create_stream([])
        self.assertEqual(inner.invocations, 0); self.assertEqual(audit(self.path)['attempts'], 0)

    async def test_task_binding_and_interrupted_start(self):
        _, ledger, _ = self.client()
        ledger.start('solver', [dict(content='x')])
        with self.assertRaises(ValueError): ledger.bind_task('OTHER')
        r = audit(self.path); self.assertEqual(r['unresolved'], 1); self.assertIsNone(r['total_cost_usd'])
        with self.assertRaises(FileExistsError): BoundaryLedger(self.path, 'unit', 'TASK')

    async def test_write_failure_prevents_client_call(self):
        client, ledger, inner = self.client()
        with patch('communication_pruning.foreign_observer.os.fsync', side_effect=OSError('fixture')):
            with self.assertRaises(OSError): await client.create([UserMessage(content='x', source='user')])
        self.assertEqual(inner.invocations, 0); self.assertTrue(ledger.poisoned)
        with self.assertRaises(RuntimeError): await client.create([UserMessage(content='x', source='user')])

    async def test_tampered_duplicate_and_missing_events(self):
        client, _, _ = self.client(synthetic_bill)
        await client.create([UserMessage(content='x', source='user')])
        original = self.path.read_bytes(); rows = [json.loads(line) for line in original.splitlines()]
        variants = [rows + [rows[-1]], [rows[0], rows[-1]]]
        changed = copy.deepcopy(rows); changed[1]['request']['messages'][0]['content'] = 'changed'; variants.append(changed)
        for index, variant in enumerate(variants):
            p = self.path.parent / f'tamper-{index}.jsonl'; p.write_bytes(b'\n'.join(canonical(r) for r in variant)+b'\n')
            with self.assertRaises(ValueError): audit(p)
        self.assertEqual(audit(self.path)['completed'], 1)

    def test_own_core_has_fresh_task_context(self):
        seen = []
        def adapter(request):
            seen.append(request)
            return Response('OUTPUT-' + request.task.task_id, Usage(cost_usd=Decimal('0'), cost_source='synthetic'))
        config = Configuration('context-test', ('evidence', 'linking'), (('evidence','linking'), ('linking','evidence')))
        execute(TaskInput('A', 'public A', ('A context',)), config, adapter, run_id='first')
        execute(TaskInput('B', 'public B', ('B context',)), config, adapter, run_id='second')
        second = [r for r in seen if r.task.task_id == 'B']
        self.assertEqual(len(second), 5)
        self.assertFalse(any('OUTPUT-A' in m.text for r in second for m in r.messages))
        self.assertTrue(all(not r.messages for r in second if r.round == 1))


if __name__ == '__main__': unittest.main()
