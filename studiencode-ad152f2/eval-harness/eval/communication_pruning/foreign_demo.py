"""Real AutoGen orchestration with a deliberately synthetic text model client."""

from decimal import Decimal
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import ChatCompletionClient, CreateResult, RequestUsage
from .contracts import AdapterError, Usage
from .foreign_observer import BoundaryLedger, ObservedClient
from .foreign_audit import audit


class ScriptedClient(ChatCompletionClient):
    """No network, model, random generator, hidden retry, or token estimator."""
    def __init__(self, ledger, actor, mode='normal'):
        self.ledger, self.actor, self.mode = ledger, actor, mode
        self.invocations = 0; self.successes = 0

    async def create(self, messages, **kwargs):
        self.invocations += 1
        if self.ledger.counter == 2 and self.mode in ('failed_known', 'failed_unknown'):
            usage = Usage(20, 1, Decimal('.02'), 'synthetic') if self.mode == 'failed_known' else Usage()
            raise AdapterError('deliberate synthetic failure', usage)
        self.successes += 1
        return CreateResult(content=f'REPLY {self.ledger.run_id}:{self.ledger.counter:04d} by {self.actor}',
                            finish_reason='stop', usage=RequestUsage(prompt_tokens=20, completion_tokens=3), cached=False)

    def create_stream(self, *args, **kwargs): raise NotImplementedError('synthetic non-streaming fixture')
    async def close(self): pass
    def actual_usage(self): return RequestUsage(prompt_tokens=20*self.successes, completion_tokens=3*self.successes)
    def total_usage(self): return self.actual_usage()
    def count_tokens(self, messages, *, tools=()): return 20
    def remaining_tokens(self, messages, *, tools=()): return 1000
    @property
    def capabilities(self): return dict(vision=False, function_calling=False, json_output=False)
    @property
    def model_info(self): return dict(self.capabilities, family='unknown', structured_output=False)


def synthetic_bill(result):
    return Usage(result.usage.prompt_tokens, result.usage.completion_tokens, Decimal('.01'), 'synthetic')


def make_team(path, name, task_id, mode='normal'):
    ledger = BoundaryLedger(path, name, task_id)
    clients = [ObservedClient(ScriptedClient(ledger, actor, mode), ledger, actor,
                              None if mode == 'unknown_prices' else synthetic_bill) for actor in ('solver', 'critic')]
    agents = [AssistantAgent(actor, model_client=client, system_message=f'You are the synthetic {actor}. Respond with a short text.',
                             model_client_stream=False) for actor, client in zip(('solver', 'critic'), clients)]
    team = RoundRobinGroupChat(agents, max_turns=4)
    return team, ledger, clients


async def run_case(folder, name):
    initial = 'HISTORY_ALPHA' if name == 'history_control' else name.upper()
    team, ledger, clients = make_team(folder / f'{name}.jsonl', name, initial, name)
    stages = []; error_type = None
    markers = ('HISTORY_ALPHA', 'HISTORY_BRAVO', 'HISTORY_CHARLIE') if name == 'history_control' else (initial,)
    try:
        for index, marker in enumerate(markers):
            if index == 2: await team.reset()
            ledger.bind_task(marker)
            result = await team.run(task=marker + ': synthetic public task; return a short fixed reply.')
            stages.append(dict(task_id=marker, messages=[m.model_dump(mode='json') for m in result.messages], stop_reason=result.stop_reason))
    except Exception as error:
        if name not in ('failed_known', 'failed_unknown'): raise
        error_type = type(error).__name__
    finally:
        for client in clients: await client.close()
    observed = audit(ledger.path)
    expected = 12 if name == 'history_control' else 2 if name.startswith('failed_') else 4
    if observed['attempts'] != expected: raise ValueError('unexpected external client count')
    if [r['actor'] for r in observed['calls']] != ['solver', 'critic'] * (expected // 2):
        raise ValueError('unexpected external speaker order')
    if name.startswith('failed_'):
        if error_type is None or observed['failed'] != 1: raise ValueError('missing visible external failure')
    elif observed['completed'] != expected: raise ValueError('missing successful external calls')
    content = lambda i: str(observed['calls'][i]['request']['messages'])
    if name == 'history_control':
        if 'HISTORY_ALPHA' not in content(4) or 'HISTORY_BRAVO' not in content(4):
            raise ValueError('expected retained-context control absent')
        if 'HISTORY_ALPHA' in content(8) or 'HISTORY_BRAVO' in content(8) or 'HISTORY_CHARLIE' not in content(8):
            raise ValueError('reset did not isolate the next task')
    if name == 'fresh_b' and 'FRESH_A' in content(0): raise ValueError('fresh team has previous task context')
    expected_total = dict(fresh_a='.04', fresh_b='.04', history_control='.12', unknown_prices=None, failed_known='.03', failed_unknown=None)[name]
    if (None if observed['total_cost_usd'] is None else Decimal(observed['total_cost_usd'])) != (None if expected_total is None else Decimal(expected_total)):
        raise ValueError('unexpected total cost status')
    return dict(case=name, stages=stages, expected_error_type=error_type, audit=observed,
                framework_classes=[type(team).__module__ + '.' + type(team).__name__], passed=True)
