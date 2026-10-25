"""Z56 V3: LangGraph attachment of the communication-pruning framework after recipe 7.3 (N3021/N3022).

Foreign system: a LangGraph 1.0.6 StateGraph. It keeps its own graph (universal node set:
every role in every round plus the aggregator; potential edges from every round-k role node to
every round-(k+1) role node and from every last-round node to the aggregator). The configuration
enters only as a fixed 0/1 mask over these potential edges. Messages flow along the LangGraph
edges: a node reads the outputs of exactly its in-edge sources in the graph it was compiled from
(StateGraph.edges / StateGraph.waiting_edges). The adapter deliberately does NOT check message
rights itself; that is left to the framework's unchanged Journal/audit (Pruefroutine).

Every model call goes through LoggingSender, which writes the framework's own event contract
(started -> completed/failed/model_failed with Usage) through the unchanged journal.Journal.
LoggingSender and header() replicate the closure call() and the trace header of
execution.execute (execution.py:31-39, 59-86, 102-107); the framework exposes no separate
logging sender for this contract (finding for V3f).

LangGraph runs all nodes of one superstep concurrently in a thread pool. The framework's journal
and audit require one strict sequential order (round-major, roles in configuration order,
aggregator last). The Gate serializes sender calls into that order without changing which nodes
LangGraph runs or which messages it delivers (precondition, finding for V3f).

Only public LangGraph API is used: StateGraph, add_node, add_edge (single and waiting edges),
START/END, compile, invoke, and the read-only builder attributes edges/waiting_edges.
"""
from contextlib import nullcontext
from dataclasses import asdict
import json
import threading
from typing import Annotated, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from communication_pruning.contracts import (AdapterError, INSTRUCTIONS, ROLES, Message, Request,
                                             Response)
from communication_pruning.failure_policy import F01, ModelFailure, validate_policy
from communication_pruning.journal import Journal

AGG = "aggregator"


class ModelTaskFailed(Exception):
    """F-01 model failure ends the task (execution.py _ModelTaskFailed)."""


class GateClosed(Exception):
    """A node was held before the sender because an earlier call ended the run."""


class GateTimeout(Exception):
    """A node never reached its turn: the foreign graph diverged from the protocol schedule."""


class IncompleteSchedule(Exception):
    """LangGraph finished without executing every scheduled call."""


def node_id(role, round_no):
    return f"{role}@{round_no}"


def split(label):
    role, _, round_no = label.rpartition("@")
    return role, int(round_no)


def potential_edges(rounds):
    """Universal edge set of the foreign graph (sorted by target, then ROLES; 20 edges for 2 rounds)."""
    edges = [(node_id(s, k), node_id(t, k + 1)) for k in range(1, rounds) for t in ROLES for s in ROLES]
    edges += [(node_id(r, rounds), node_id(AGG, rounds + 1)) for r in ROLES]
    return tuple(edges)


def mask(config, rounds):
    """Configuration as fixed 0/1 mask over potential_edges (rule of execution.py:95-103)."""
    active = set(config.roles)
    bits = []
    for source, target in potential_edges(rounds):
        s, t = split(source)[0], split(target)[0]
        if t == AGG:
            bits.append(int(s in active))
        else:
            bits.append(int(s in active and t in active and (s == t or (s, t) in config.edges)))
    return tuple(bits)


def schedule(config, rounds):
    """Protocol order the framework's journal and audit require."""
    return [node_id(r, k) for k in range(1, rounds + 1) for r in config.roles] + [node_id(AGG, rounds + 1)]


def header(task, config, rounds, run_id, producer_limit, failure_policy):
    """Trace header exactly as execution.execute builds it (execution.py:20-39)."""
    validate_policy(failure_policy)
    if failure_policy is not None and producer_limit != 1024:
        raise ValueError("F-01 requires the explicit 1024/128 contract")
    if type(producer_limit) is not int or producer_limit not in (512, 1024):
        raise ValueError("only the default or explicit technical producer limit supported")
    if type(rounds) is not int or rounds not in (1, 2):
        raise ValueError("only one or two synchronous rounds supported")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise ValueError("nonempty run ID required")
    trace = {"schema": 1, "run_id": run_id or str(uuid4()), "task": asdict(task),
             "configuration": asdict(config), "rounds": rounds, "failed_role": None, "events": []}
    if producer_limit != 512:
        trace.update(schema=2, output_limits={"producer": producer_limit, "aggregator": 128})
    if failure_policy == F01:
        trace.update(schema=3, failure_policy=F01)
    return json.loads(json.dumps(trace))


class LoggingSender:
    """One model call = started event, agent call, terminal event (execution.py:59-86 contract)."""

    def __init__(self, task, trace, journal, agent):
        self.task, self.trace, self.journal, self.agent = task, trace, journal, agent

    def record(self, event):
        if self.journal is not None:
            self.journal.append(event)          # unchanged Journal: online audit_prefix before writing
        self.trace["events"].append(event)

    def call(self, role, round_no, messages):
        trace = self.trace
        attempt_id = f"{trace['run_id']}:{round_no}:{role}:1"
        limit = 128 if role == AGG else trace.get("output_limits", {}).get("producer", 512)
        request = Request(attempt_id, self.task, role, round_no, INSTRUCTIONS[role], messages, limit)
        self.record({"kind": "started", "attempt_id": attempt_id, "role": role, "round": round_no,
                     "instruction": request.instruction, "max_output_tokens": request.max_output_tokens,
                     "messages": [asdict(m) for m in messages]})
        try:
            response = self.agent(request)
            if not isinstance(response, Response):
                raise TypeError("adapter did not return Response")
        except AdapterError as error:
            if trace.get("failure_policy") == F01:
                raise
            self.record({"kind": "failed", "attempt_id": attempt_id, "error": str(error),
                         "usage": error.usage.to_dict()})
            return None
        if isinstance(response, ModelFailure):
            if trace.get("failure_policy") != F01:
                raise TypeError("model failure returned outside the bound policy")
            self.record({"kind": "model_failed", "attempt_id": attempt_id, "reason": response.reason,
                         "usage": response.usage.to_dict()})
            raise ModelTaskFailed()
        self.record({"kind": "completed", "attempt_id": attempt_id, "text": response.text,
                     "usage": response.usage.to_dict()})
        return Message(attempt_id, role, round_no, response.text)


class Gate:
    """Serializes concurrent LangGraph node threads into the protocol schedule."""

    def __init__(self, order, timeout):
        self.order, self.position, self.timeout = list(order), 0, timeout
        self.failure = None
        self.cv = threading.Condition()

    def enter(self, label):
        with self.cv:
            ready = self.cv.wait_for(lambda: self.failure is not None or (
                self.position < len(self.order) and self.order[self.position] == label), timeout=self.timeout)
            if self.failure is not None:
                raise GateClosed(f"{label} held before the sender after {type(self.failure).__name__}")
            if not ready:
                self.failure = GateTimeout(f"{label} never reached its turn")
                self.cv.notify_all()
                raise self.failure

    def leave(self):
        with self.cv:
            self.position += 1
            self.cv.notify_all()

    def fail(self, error):
        with self.cv:
            if self.failure is None:
                self.failure = error
            self.cv.notify_all()


def _merge(left, right):
    out = dict(left or {})
    for key, value in (right or {}).items():
        if key in out:
            raise ValueError(f"node output {key} written twice")
        out[key] = value
    return out


class State(TypedDict):
    task: dict
    outputs: Annotated[dict, _merge]


def build(config, rounds, make_node, *, extra_nodes=(), extra_edges=(), extra_waits=None):
    """Universal foreign graph; only masked-in potential edges are added. extra_* = deliberate defects."""
    builder = StateGraph(State)
    for label in [node_id(r, k) for k in range(1, rounds + 1) for r in ROLES] + [node_id(AGG, rounds + 1)]:
        builder.add_node(label, make_node(label))
    for name, function in extra_nodes:
        builder.add_node(name, function)
    realized = [e for e, bit in zip(potential_edges(rounds), mask(config, rounds)) if bit]
    for role in config.roles:
        builder.add_edge(START, node_id(role, 1))
    joins = {}
    for source, target in realized:
        joins.setdefault(target, []).append(source)
    for target, sources in (extra_waits or {}).items():
        joins.setdefault(target, []).extend(sources)
    for target, sources in joins.items():
        builder.add_edge(sources, target)       # waiting edge: target runs once all sources finished
    builder.add_edge(node_id(AGG, rounds + 1), END)
    for source, target in extra_edges:
        builder.add_edge(source, target)
    return builder, realized


def in_sources(builder):
    """Message sources of every node = its in-edge sources in the LangGraph graph itself."""
    sources = {}
    for source, target in builder.edges:
        if source != START:
            sources.setdefault(target, set()).add(source)
    for starts, target in builder.waiting_edges:
        sources.setdefault(target, set()).update(starts)
    return sources


def run(task, config, agent, *, rounds=2, run_id=None, journal_path=None, producer_limit=512,
        failure_policy=None, extra_nodes=(), extra_edges=(), extra_waits=None, evidence=None, timeout=30):
    """LangGraph counterpart of execution.execute (same signature subset, same trace and journal)."""
    trace = header(task, config, rounds, run_id, producer_limit, failure_policy)
    order = schedule(config, rounds)
    rank = {role: i for i, role in enumerate(config.roles)}
    gate = Gate(order, timeout)
    arrived, executed, delivered = [], [], {}
    with Journal(journal_path, trace, config) if journal_path is not None else nullcontext() as journal:
        sender = LoggingSender(task, trace, journal, agent)
        sources = {}

        def make_node(label):
            role, round_no = split(label)

            def node(state):
                outputs = state["outputs"]
                present = [s for s in sources.get(label, ()) if s in outputs]
                present.sort(key=lambda s: (split(s)[1], rank.get(split(s)[0], len(rank) + ROLES.index(split(s)[0]))))
                arrived.append(label)               # LangGraph ran this node (thread order varies)
                delivered[label] = present
                gate.enter(label)
                executed.append(label)              # sender order (protocol order)
                try:
                    message = sender.call(role, round_no, tuple(Message(**outputs[s]) for s in present))
                except BaseException as error:
                    gate.fail(error)
                    raise
                gate.leave()
                return {"outputs": {label: asdict(message)}} if message is not None else {}
            return node

        builder, realized = build(config, rounds, make_node, extra_nodes=extra_nodes,
                                  extra_edges=extra_edges, extra_waits=extra_waits)
        sources.update(in_sources(builder))
        graph = builder.compile()
        if evidence is not None:
            potential = potential_edges(rounds)
            evidence.update(potential_edges=[list(e) for e in potential], mask=list(mask(config, rounds)),
                            realized_edges=[list(e) for e in realized],
                            removed_edges=len(potential) - len(realized),
                            graph_edges=sorted([list(e) for e in builder.edges]),
                            graph_waiting_edges=sorted([[sorted(s), t] for s, t in builder.waiting_edges]),
                            arrived=arrived, executed=executed, delivered_sources=delivered,
                            schedule=order)
        try:
            state = graph.invoke({"task": asdict(task), "outputs": {}})
        except BaseException as error:
            failure = gate.failure if gate.failure is not None else error
            if isinstance(failure, ModelTaskFailed):
                trace.update(status="model_failed", answer=None)
                if journal is not None:
                    journal.finish(trace)
                return trace
            raise failure from None
        if gate.position != len(order):
            raise IncompleteSchedule(f"executed {gate.position} of {len(order)} scheduled calls")
        final = state["outputs"].get(node_id(AGG, rounds + 1))
        trace["answer"] = None if final is None else final["text"]
        trace["status"] = "incomplete" if any(e["kind"] == "failed" for e in trace["events"]) else "completed"
        if journal is not None:
            journal.finish(trace)
        return trace
