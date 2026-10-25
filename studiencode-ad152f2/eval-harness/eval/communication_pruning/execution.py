"""Synchronous offline orchestration with an injected adapter and attempt journal."""

from dataclasses import asdict
from contextlib import nullcontext
import json
from uuid import uuid4
from .contracts import (AdapterError, Agent, Configuration, INSTRUCTIONS, Message,
                        Request, Response, TaskInput)
from .journal import Journal
from .failure_policy import F01, ModelFailure, validate_policy


class _ModelTaskFailed(Exception):
    pass


def execute(task: TaskInput, config: Configuration, agent: Agent, *, rounds: int = 2,
            failed_role: str | None = None, run_id: str | None = None,
            journal_path=None, producer_limit: int = 512, failure_policy=None) -> dict:
    validate_policy(failure_policy)
    if failure_policy is not None and producer_limit != 1024:
        raise ValueError("F-01 requires the explicit 1024/128 contract")
    if type(producer_limit) is not int or producer_limit not in (512, 1024):
        raise ValueError("only the default or explicit technical producer limit supported")
    if type(rounds) is not int or rounds not in (1, 2):
        raise ValueError("only one or two synchronous rounds supported")
    if failed_role is not None and failed_role not in config.roles:
        raise ValueError("fault must suppress an active role")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise ValueError("nonempty run ID required")
    run_id = run_id or str(uuid4())
    trace = {"schema": 1, "run_id": run_id, "task": asdict(task),
             "configuration": asdict(config), "rounds": rounds,
             "failed_role": failed_role, "events": []}
    if producer_limit != 512:
        trace.update(schema=2, output_limits={"producer": producer_limit, "aggregator": 128})
    if failure_policy == F01:
        trace.update(schema=3, failure_policy=F01)
    trace = json.loads(json.dumps(trace))
    with Journal(journal_path, trace, config) if journal_path is not None else nullcontext() as journal:
        try:
            return _execute(task, config, agent, trace, journal)
        except _ModelTaskFailed:
            trace.update(status="model_failed", answer=None)
            if journal is not None:
                journal.finish(trace)
            return trace


def _execute(task, config, agent, trace, journal):
    run_id, rounds, failed_role = trace["run_id"], trace["rounds"], trace["failed_role"]
    events = trace["events"]

    def record(event):
        if journal is not None:
            journal.append(event)
        events.append(event)

    def call(role, round_no, messages):
        attempt_id = f"{run_id}:{round_no}:{role}:1"
        request = Request(attempt_id, task, role, round_no, INSTRUCTIONS[role],
                          messages, 128 if role == "aggregator" else trace.get("output_limits", {}).get("producer", 512))
        record({"kind": "started", "attempt_id": attempt_id, "role": role,
                       "round": round_no, "instruction": request.instruction,
                       "max_output_tokens": request.max_output_tokens,
                       "messages": [asdict(m) for m in messages]})
        try:
            response = agent(request)
            if not isinstance(response, Response):
                raise TypeError("adapter did not return Response")
        except AdapterError as error:
            if trace.get("failure_policy") == F01:
                raise  # an unclassified adapter error is not an F-01 observation
            record({"kind": "failed", "attempt_id": attempt_id,
                           "error": str(error), "usage": error.usage.to_dict()})
            return None
        if isinstance(response, ModelFailure):
            if trace.get("failure_policy") != F01:
                raise TypeError("model failure returned outside the bound policy")
            record({"kind": "model_failed", "attempt_id": attempt_id,
                    "reason": response.reason, "usage": response.usage.to_dict()})
            raise _ModelTaskFailed()
        # Unexpected programming errors propagate: not valid study observations.
        record({"kind": "completed", "attempt_id": attempt_id,
                       "text": response.text, "usage": response.usage.to_dict()})
        return Message(attempt_id, role, round_no, response.text)

    previous = {}
    for round_no in range(1, rounds + 1):
        current = {}
        for role in config.roles:
            if role == failed_role:
                record({"kind": "suppressed", "role": role, "round": round_no})
                continue
            messages = tuple(previous[source] for source in config.roles
                             if source in previous and
                             (source == role or (source, role) in config.edges))
            result = call(role, round_no, messages)
            if result is not None:
                current[role] = result
        previous = current
    final = call("aggregator", rounds + 1,
                 tuple(previous[role] for role in config.roles if role in previous))
    trace["answer"] = None if final is None else final.text
    trace["status"] = "incomplete" if any(e["kind"] == "failed" for e in events) else "completed"
    if journal is not None:
        journal.finish(trace)
    return trace
