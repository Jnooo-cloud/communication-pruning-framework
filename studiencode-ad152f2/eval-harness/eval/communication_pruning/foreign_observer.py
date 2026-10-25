"""Narrow AutoGen 0.7.5 text-client observer, not a provider billing adapter.

Observes calls made to a model client. Internal client retries and server-side
state are outside this boundary. Uses the artifact's existing Usage contract;
foreign messages never claim conformance to its synchronous configuration bank.
"""

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from autogen_core.models import ChatCompletionClient
from .contracts import AdapterError, Usage


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


class BoundaryLedger:
    """Create-only sequential ledger, permanently stopped after write/call failure."""
    def __init__(self, path, run_id, task_id, *, framework='autogen-agentchat==0.7.5'):
        if not all(isinstance(v, str) and v for v in (run_id, task_id, framework)):
            raise ValueError('named run and task required')
        self.path, self.run_id, self.task_id = Path(path), run_id, task_id
        self.active = None; self.poisoned = False; self.counter = 0; self.seq = 0; self.previous = '0' * 64
        with self.path.open('xb'):
            pass
        self.write(dict(kind='header', schema='foreign-model-boundary/v1', framework=framework, run_id=run_id))

    def write(self, event):
        if self.poisoned:
            raise RuntimeError('ledger stopped')
        row = dict(sequence=self.seq, previous_sha256=self.previous,
                   time=datetime.now(timezone.utc).isoformat(), **event)
        digest = sha256(canonical(row)).hexdigest()
        try:
            with self.path.open('ab') as out:
                out.write(canonical(dict(row, sha256=digest)) + b'\n'); out.flush(); os.fsync(out.fileno())
        except BaseException:
            self.poisoned = True
            raise
        self.seq += 1; self.previous = digest

    def bind_task(self, task_id):
        if self.active is not None or self.poisoned or not isinstance(task_id, str) or not task_id:
            raise ValueError('task binding only between completed calls')
        self.task_id = task_id

    def start(self, actor, messages):
        if self.active is not None or self.poisoned:
            raise RuntimeError('only sequential calls on a healthy ledger')
        if not isinstance(actor, str) or not actor:
            raise ValueError('actor ID required')
        request = dict(messages=messages, tools=[], stream=False)
        attempt = f'{self.run_id}:{self.counter + 1:04d}'
        self.write(dict(kind='started', attempt_id=attempt, run_id=self.run_id, task_id=self.task_id,
                        actor=actor, request=request, request_sha256=sha256(canonical(request)).hexdigest()))
        self.counter += 1; self.active = attempt
        return attempt

    def finish(self, attempt, kind, usage, **evidence):
        if attempt != self.active or kind not in ('completed', 'failed') or not isinstance(usage, Usage):
            raise ValueError('invalid terminal event')
        self.write(dict(kind=kind, attempt_id=attempt, usage=usage.to_dict(), **evidence))
        self.active = None
        if kind == 'failed': self.poisoned = True


class ObservedClient(ChatCompletionClient):
    def __init__(self, inner, ledger, actor, billing=None):
        self.inner, self.ledger, self.actor, self.billing = inner, ledger, actor, billing

    async def create(self, messages, *, tools=(), tool_choice='auto', json_output=None,
                     extra_create_args=None, cancellation_token=None):
        if tools or tool_choice not in ('auto', 'none') or json_output not in (None, False) or extra_create_args:
            raise ValueError('observer currently supports plain text without tools or extra options')
        data = [m.model_dump(mode='json') for m in messages]
        if any(not isinstance(m.get('content'), str) for m in data):
            raise ValueError('text messages required')
        attempt = self.ledger.start(self.actor, data); usage = Usage()
        try:
            result = await self.inner.create(messages, tools=[], tool_choice=tool_choice, json_output=json_output,
                                             extra_create_args={}, cancellation_token=cancellation_token)
            usage = (self.billing(result) if self.billing else Usage(input_tokens=result.usage.prompt_tokens,
                                                                     output_tokens=result.usage.completion_tokens))
            if not isinstance(usage, Usage):
                usage = Usage(); raise TypeError('billing resolver must return Usage')
            if not isinstance(result.content, str): raise ValueError('text response required')
            response = result.model_dump(mode='json')
            self.ledger.finish(attempt, 'completed', usage, response=response,
                               response_sha256=sha256(canonical(response)).hexdigest())
            return result
        except BaseException as error:
            if self.ledger.active == attempt and not self.ledger.poisoned:
                if isinstance(error, AdapterError): usage = error.usage
                self.ledger.finish(attempt, 'failed', usage, error_type=type(error).__name__)
            raise

    def create_stream(self, *args, **kwargs):
        raise NotImplementedError('streaming is outside this observer contract')

    async def close(self): await self.inner.close()
    def actual_usage(self): return self.inner.actual_usage()
    def total_usage(self): return self.inner.total_usage()
    def count_tokens(self, messages, *, tools=()): return self.inner.count_tokens(messages, tools=tools)
    def remaining_tokens(self, messages, *, tools=()): return self.inner.remaining_tokens(messages, tools=tools)
    @property
    def capabilities(self): return self.inner.capabilities
    @property
    def model_info(self): return self.inner.model_info
