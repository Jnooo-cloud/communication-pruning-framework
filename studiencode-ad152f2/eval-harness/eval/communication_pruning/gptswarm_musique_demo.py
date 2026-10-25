"""Z55 GPTSwarm demonstration on real MuSiQue R blocks (D-082, plan project/dsr/Z55-GPTSWARM-DEMO-PLAN.md).

The unmodified GPTSwarm original (Z31, commit c23a827f) builds one universal
9-node graph: per role a round-1 and a round-2 node plus the aggregator as the
CompositeGraph decision node, initially without edges. Two fixed logit masks
are realized by the original EdgeWiseDistribution.realize(threshold=0.5):
F* = C01 (evidence/linking, 2 rounds, 5 calls) and D (all 20 edges, 9 calls).
The original Graph.run executes the realized graph; each node builds the study
Request (contracts.INSTRUCTIONS, limits 1024/128) from exactly the messages the
framework delivered over realized edges and calls a z53_fast.BlockSender
(unchanged payload bytes and Z53 retry/stop rules). Node.execute swallows
exceptions, so the first failure is held in the arm context and every later
node is blocked before the sender (Z31 pattern).

Evidence for M2 (message rights), M3 (removed edge = no node entry, no call)
and M5 (all billed attempts incl. terminal failures in cost; unclear attempts
stay unknown) is written per arm and recomputed by verify_block.

The original GPTSwarm source and its runtime (torch etc.) must be on sys.path
(runs/Z31-PRUNING-001/original and /runtime). Demonstration only: no study
row, no optimizer, no learned topology.
"""
import asyncio
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path

from .configurations import bank, dense
from .contracts import INSTRUCTIONS, ROLES, Message, Request, TaskInput
from .data import AnswerReference
from .evaluation import score_answer
from .failure_policy import F01, ModelFailure, decode_outcome, strict_json
from .openrouter import RESERVE, ProbeStop, decode_billing, encoded, payload

COMMIT = "c23a827f561c934ce21dd950408f7606aa4a8821"
FRAMEWORK = "GPTSwarm@" + COMMIT
RUNNER = "Z55-GPTSWARM-DEMO-001"
AGG = "aggregator"
AGG_NODE = AGG + "@3"
ARMS = ("F", "D")
EXPECTED_CALLS = {"F": 5, "D": 9}
PRODUCER_LIMIT, AGGREGATOR_LIMIT = 1024, 128
HARD_CAP = Decimal("1.00")          # D-082
LOGIT = math.log(9)                 # sigmoid = 0.9 -> exactly 1 after threshold; -LOGIT -> exactly 0
THRESHOLD = 0.5
SEED = 55


def node_id(role, round_no):
    return f"{role}@{round_no}"


# Sorted by target, then ROLES: Node.execute then delivers messages in execution.py:95-97 order.
POTENTIAL = tuple((node_id(s, 1), node_id(t, 2)) for t in ROLES for s in ROLES) + \
    tuple((node_id(s, 2), AGG_NODE) for s in ROLES)
NODES = tuple(node_id(r, 1) for r in ROLES) + tuple(node_id(r, 2) for r in ROLES) + (AGG_NODE,)


class DemoStop(Exception):
    """Construction or rights violation: stop the whole demonstration (never a model observation)."""


class ArmModelFailure(Exception):
    """F-01 ModelFailure answer: the arm ends as model failure (execution.py _ModelTaskFailed)."""

    def __init__(self, reason, attempt_id):
        super().__init__(reason)
        self.reason, self.attempt_id = reason, attempt_id


def need(condition, message, kind=DemoStop):
    if not condition:
        raise kind(message)


def arm_config(arm):
    if arm == "F":
        configs = {c.config_id: c for c in bank()}
        return configs["C01"]
    need(arm == "D", "unplanned arm")
    return dense()


def realized_edges(config):
    """Edges the study protocol uses for this configuration (execution.py:95-103)."""
    need(tuple(r for r in ROLES if r in config.roles) == config.roles, "roles not in ROLES order")
    rounds = {(node_id(s, 1), node_id(t, 2)) for t in config.roles for s in config.roles
              if s == t or (s, t) in config.edges}
    return rounds | {(node_id(r, 2), AGG_NODE) for r in config.roles}


def expected_sequence(config):
    return [node_id(r, 1) for r in config.roles] + [node_id(r, 2) for r in config.roles] + [AGG_NODE]


def mask_logits(edges):
    return [LOGIT if e in edges else -LOGIT for e in POTENTIAL]


# --------------------------------------------------------------------------- original graph

def build_original(arm):
    """Universal 9-node graph, realized with the original EdgeWiseDistribution.realize."""
    import inspect
    import random
    import torch
    from swarm.graph.composite_graph import CompositeGraph
    from swarm.graph.graph import Graph
    from swarm.graph.node import Node
    from swarm.memory import GlobalMemory
    from swarm.optimizer.edge_optimizer.parameterization import EdgeWiseDistribution

    class DemoNode(Node):
        def __init__(self, label):
            super().__init__("Z55 study role node " + label, id=label, combine_inputs_as_one=True)
            self.context = None

        async def _execute(self, input, **kwargs):
            if self.context is None:
                raise RuntimeError("context must be attached after original graph realization")
            return self.context.invoke(self.id, input)

    class SingleNodeGraph(Graph):
        def __init__(self, label, is_input):
            self.label, self.is_input = label, is_input
            super().__init__(domain="Z55-MuSiQue")

        def build_graph(self):
            node = self.add_node(DemoNode(self.label))
            self.input_nodes = [node] if self.is_input else []
            self.output_nodes = [node]

    config = arm_config(arm)
    edges = realized_edges(config)
    random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(1)
    GlobalMemory.instance().clear()
    graph = CompositeGraph(DemoNode(AGG_NODE), domain="Z55-MuSiQue")
    for label in NODES[:-1]:
        graph.add_graph(SingleNodeGraph(label, label.endswith("@1")))
    need(graph.num_edges == 0 and list(graph.nodes) == [AGG_NODE, *NODES[:-1]], "initial graph differs")
    distribution = EdgeWiseDistribution(list(POTENTIAL))
    with torch.no_grad():
        distribution.edge_logits.copy_(torch.tensor(mask_logits(edges)))
    realized, log_probability = distribution.realize(graph, temperature=1.0, threshold=THRESHOLD,
                                                     use_learned_order=False)
    selected = sorted((n.id, s.id) for n in realized.nodes.values() for s in n.successors)
    need(set(selected) == edges and len(selected) == len(edges), "original realize differs from mask")
    full = distribution.realize_full(graph)
    full_edges = sorted({(n.id, s.id) for n in full.nodes.values() for s in n.successors})
    if arm == "D":
        need(set(full_edges) == set(selected), "D differs from realize_full")
    for node in realized.nodes.values():
        need([p.id for p in node.predecessors] == [s for s, t in POTENTIAL if t == node.id and (s, t) in edges],
             "predecessor order differs from ROLES order")
    sources = {"Graph.run": Graph.run, "Node.execute": Node.execute,
               "CompositeGraph.add_graph": CompositeGraph.add_graph,
               "EdgeWiseDistribution.realize": EdgeWiseDistribution.realize,
               "EdgeWiseDistribution.realize_full": EdgeWiseDistribution.realize_full}
    evidence = {"framework": FRAMEWORK, "arm": arm, "configuration": config.config_id,
                "selection_method": "EdgeWiseDistribution.realize", "threshold": THRESHOLD,
                "temperature": 1.0, "learned_order": False, "seed": SEED, "torch_version": torch.__version__,
                "potential_connections": [list(e) for e in POTENTIAL],
                "logits": distribution.edge_logits.detach().tolist(),
                "realized_edges": [list(e) for e in selected],
                "realize_full_edges": [list(e) for e in full_edges],
                "log_probability": float(log_probability.detach()),
                "removed_edges": [list(e) for e in POTENTIAL if e not in edges],
                "native_sources": {name: {"path": inspect.getsourcefile(obj),
                                          "sha256": sha256(Path(inspect.getsourcefile(obj)).read_bytes()).hexdigest()}
                                   for name, obj in sources.items()}}
    return realized, edges, evidence


# --------------------------------------------------------------------------- arm context

def append_jsonl(path, value):
    import os
    with open(path, "ab") as out:
        out.write(encoded(value) + b"\n")
        out.flush()
        os.fsync(out.fileno())


class ArmContext:
    """One arm: the node->sender boundary with M2 rights check and failure blocking."""

    def __init__(self, folder, task, run_id, sender, edges, graph_input):
        self.folder, self.task, self.run_id, self.sender = Path(folder), task, run_id, sender
        self.edges, self.graph_input = edges, graph_input
        self.realized_nodes = {n for e in edges for n in e}
        self.trace = self.folder / "trace.jsonl"
        self.failure = None          # first exception; blocks every later node before the sender
        self.entries, self.blocked, self.outputs = [], [], {}

    def _record(self, value):
        append_jsonl(self.trace, value)

    def _fail(self, error):
        if self.failure is None:
            self.failure = error
        return error

    def invoke(self, label, value):
        """Every exception sets the arm failure before anything else (Node.execute swallows it)."""
        try:
            return self._invoke(label, value)
        except BaseException as error:
            if self.failure is None:
                self.failure = error
            raise

    def _invoke(self, label, value):
        self.entries.append(label)
        if label not in self.realized_nodes:
            self._fail(DemoStop(f"node outside realized mask entered: {label}"))
            self._record({"kind": "node_entry", "node": label})
            raise self.failure
        if self.failure is not None:
            self.blocked.append(label)
            self._record({"kind": "node_entry", "node": label})
            self._record({"kind": "blocked", "node": label, "by": type(self.failure).__name__})
            raise RuntimeError("arm stopped after earlier failure; node blocked before sender")
        self._record({"kind": "node_entry", "node": label})
        request, sources = self._request(label, value)
        self._record({"kind": "started", "node": label, "attempt_id": request.attempt_id,
                      "role": request.role, "round": request.round, "instruction": request.instruction,
                      "max_output_tokens": request.max_output_tokens,
                      "messages": [asdict(m) for m in request.messages], "message_sources": sources})
        try:
            response = self.sender(request)
        except BaseException as error:
            self._fail(error)
            self._record({"kind": "failed", "node": label, "attempt_id": request.attempt_id,
                          "error_type": type(error).__name__, "error": str(error)})
            raise
        if isinstance(response, ModelFailure):
            self._fail(ArmModelFailure(response.reason, request.attempt_id))
            self._record({"kind": "model_failed", "node": label, "attempt_id": request.attempt_id,
                          "reason": response.reason, "usage": response.usage.to_dict()})
            raise self.failure
        out = {"node": label, "attempt_id": request.attempt_id, "role": request.role,
               "round": request.round, "text": response.text, "output": response.text}
        self.outputs[label] = encoded(out)          # immutable original; consumers get a separate copy
        self._record({"kind": "completed", "node": label, "attempt_id": request.attempt_id,
                      "text": response.text, "usage": response.usage.to_dict()})
        return json.loads(self.outputs[label])

    def _request(self, label, value):
        role, round_no = label.rsplit("@", 1)
        round_no = int(round_no)
        if round_no == 1:
            need(value == self.graph_input, "round-1 node received something other than the task")
            messages, sources = (), []
        else:
            need(isinstance(value, list), "later node did not receive combined predecessor outputs")
            expected = [s for s, t in POTENTIAL if t == label and (s, t) in self.edges]
            sources = [item.get("node") if isinstance(item, dict) else None for item in value]
            for source in sources:  # M2: only messages over realized edges may be sent
                need((source, label) in self.edges, f"message over unrealized edge {source} -> {label}")
            need(sources == expected, f"messages for {label} differ from its realized in-edges")
            for item in value:  # every field must equal the producer's immutable original
                need(encoded(item) == self.outputs.get(item["node"]), "delivered message differs from producer output")
            messages = tuple(Message(i["attempt_id"], i["role"], i["round"], i["text"]) for i in value)
        limit = AGGREGATOR_LIMIT if role == AGG else PRODUCER_LIMIT
        request = Request(f"{self.run_id}:{round_no}:{role}:1", self.task, role, round_no,
                          INSTRUCTIONS[role], messages, limit)
        return request, sources


def graph_input(task):
    return {"task": asdict(task)}


def run_arm(arm, task, reference, run_id, sender, folder):
    """Execute one arm through the original Graph.run; returns (result, selection evidence)."""
    folder = Path(folder)
    folder.mkdir()
    config = arm_config(arm)
    graph, edges, evidence = build_original(arm)
    (folder / "selection.json").write_bytes(encoded(evidence))
    ctx = ArmContext(folder, task, run_id, sender, edges, graph_input(task))
    for node in graph.nodes.values():
        node.context = ctx
    # Graph.run deep-copies its inputs into every input node; pass the public task only.
    # max_tries=1: no framework retry; large max_time: the synchronous sender is never cut off.
    native = asyncio.run(graph.run(graph_input(task), max_tries=1, max_time=10 ** 6))
    failure = ctx.failure
    record = {"arm": arm, "configuration": config.config_id, "run_id": run_id, "framework": FRAMEWORK,
              "entered_nodes": ctx.entries, "blocked_nodes": ctx.blocked,
              "realized_nodes": sorted(ctx.realized_nodes),
              "not_entered_nodes": [n for n in NODES if n not in ctx.entries]}
    if failure is not None and not isinstance(failure, (ArmModelFailure, TerminalArmFailureType())):
        (folder / "arm-stop.json").write_bytes(encoded(record | {"error_type": type(failure).__name__,
                                                                 "error": str(failure)}))
        raise failure
    need(not set(ctx.entries) - ctx.realized_nodes, "node outside realized mask entered")
    calls = sender.calls_for(run_id)
    cost = sender.cost_for(run_id)
    if failure is None:
        need(ctx.entries == expected_sequence(config), "entered node sequence differs from protocol order")
        need(calls == EXPECTED_CALLS[arm] == sender.calls, "successful arm call count differs from 5/9")
        answer = json.loads(ctx.outputs[AGG_NODE])["text"]
        need(native == [answer], "native graph answer differs from aggregator output")
        status, scores, reason = "ok", score_answer(answer, reference), None
    else:
        need(ctx.entries == expected_sequence(config), "entered node sequence differs from protocol order")
        status, scores, reason, answer = "model_failure", {"em": 0.0, "f1": 0.0}, failure.reason, None
    result = record | {"status": status, "em": scores["em"], "f1": scores["f1"], "answer": answer,
                       "failure_reason": reason, "call_count": calls, "cost_usd": str(cost),
                       "unknown_attempts": sender.unknown_attempts, "native_answer": native}
    (folder / "result.json").write_bytes(encoded(result))
    return result, evidence


def TerminalArmFailureType():
    from study_preparation.z53_fast import TerminalArmFailure
    return TerminalArmFailure


# --------------------------------------------------------------------------- sender and cost brake

class CostBrake:
    """Worst case per physical attempt (sequential): known + 0.14 x (unknown + this) <= cap.
    Also holds every generation id seen so far (duplicate -> stop before the next transport)."""

    def __init__(self, cap=HARD_CAP, known=Decimal(0), unknown=0, generations=()):
        cap = Decimal(cap)
        need(Decimal(0) < cap <= HARD_CAP, "cost cap above D-082 limit")
        self.cap, self.known, self.unknown = cap, Decimal(known), int(unknown)
        self.generations = set(generations)

    def admit(self):
        return self.known + RESERVE * (self.unknown + 1) <= self.cap


def _mentions_billing(raw):
    """A non-200 body carrying any usage/cost field (at any depth) has billing we cannot verify."""
    try:
        data = json.loads(raw)
    except Exception:
        return False   # plain-text error page: no billing information

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)
    return any(key in ("usage", "cost") for key in keys(data))


class BrakedTransport:
    """Wraps the transport: every physical attempt is admitted by the brake, then booked in memory
    and in a durable brake ledger before the sender sees the answer (also 429/5xx/error bodies)."""

    def __init__(self, transport, brake, stop_kind, ledger):
        self.transport, self.brake, self.stop_kind, self.ledger = transport, brake, stop_kind, Path(ledger)
        self.n = 0

    def _stop(self, status, raw, reason):
        """Keep the original answer of a systemic stop as evidence before stopping."""
        stem = self.ledger.parent / f"brake-stop-{self.n:04d}"
        Path(str(stem) + "-response.json").write_bytes(raw)
        Path(str(stem) + "-received.json").write_bytes(encoded({"http_status": status, "reason": reason,
                                                                "response_sha256": sha256(raw).hexdigest()}))
        raise self.stop_kind(reason)

    def __call__(self, endpoint, body):
        if not self.brake.admit():
            raise self.stop_kind("cost cap: no further physical attempt within 1.00 USD worst case")
        self.n += 1
        entry = {"n": self.n, "request_sha256": sha256(body).hexdigest()}
        try:
            status, raw = self.transport(endpoint, body)
        except BaseException as error:
            self.brake.unknown += 1
            append_jsonl(self.ledger, entry | {"outcome": "transport_error", "billing": "unknown",
                                               "error_type": type(error).__name__})
            raise
        entry |= {"http_status": status, "response_sha256": sha256(raw).hexdigest()}
        try:
            usage, generation = decode_billing(raw)
        except Exception:
            usage = generation = None
        if usage is not None:
            self.brake.known += usage.cost_usd
            append_jsonl(self.ledger, entry | {"billing": "provider", "cost_usd": str(usage.cost_usd),
                                               "generation_id": generation})
            if generation in self.brake.generations:
                self._stop(status, raw, f"duplicate generation {generation}")
            self.brake.generations.add(generation)
            if usage.cost_usd > RESERVE:
                self._stop(status, raw, "billed attempt above the 0.14 USD per-call reserve")
            if status != 200 and usage.cost_usd > 0:
                self._stop(status, raw, f"billed HTTP {status} answer")
        elif status == 200 or _mentions_billing(raw):
            # billing present but not verifiable (or HTTP 200 without billing): unknown, then systemic stop
            self.brake.unknown += 1
            append_jsonl(self.ledger, entry | {"billing": "unknown"})
            if status != 200:
                self._stop(status, raw, f"HTTP {status} answer with unverifiable billing")
        else:
            append_jsonl(self.ledger, entry | {"billing": "none"})
        return status, raw


def make_sender_class():
    from study_preparation.z53_fast import BlockSender, GlobalStop

    class DemoSender(BlockSender):
        """Z53 BlockSender (unchanged bytes, retry/stop rules) plus a pre-send round-1 parity guard."""

        def __init__(self, *args, round1=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.round1 = round1 or {}

        def _body(self, request):
            body = super()._body(request)
            if request.round == 1:
                expected = self.round1.get(request.role)
                if expected is None or body != expected:
                    raise GlobalStop(f"round-1 bytes differ from Z53 for {request.role}")
            return body

    return DemoSender


# --------------------------------------------------------------------------- Z53 reference

def z53_arm(block_dir, arm):
    """Requests/answers actually used by the Z53 arm, keyed by (round, role)."""
    from study_preparation.z53_fast import _pick
    block_dir = Path(block_dir)
    result = json.loads((block_dir / arm / "result.json").read_bytes())
    run_id = result["run_id"]
    requests, answers = {}, {}
    for pdir in sorted(p for p in block_dir.iterdir() if p.is_dir() and p.name.startswith("provider")):
        for b in sorted(pdir.glob("*-binding.json")):
            rec = json.loads(b.read_bytes())
            if not rec["attempt_id"].startswith(run_id + ":"):
                continue
            stem = b.name[:3]
            body = (pdir / f"{stem}-request.json").read_bytes()
            need(sha256(body).hexdigest() == rec["request_sha256"], "Z53 request hash")
            requests.setdefault(rec["attempt_id"], []).append((pdir.name, body))
            finals = [pdir / r.name.replace("-received.json", "-response.json")
                      for r in sorted(pdir.glob(f"{stem}-p*-received.json"))
                      if json.loads(r.read_bytes())["http_status"] == 200]
            if finals:
                answers.setdefault(rec["attempt_id"], []).append((pdir.name, finals[-1].read_bytes()))
    out = {"run_id": run_id, "result": result, "requests": {}, "answers": {}}
    for attempt_id, entries in requests.items():
        round_no, role, _ = attempt_id[len(run_id) + 1:].split(":")
        key = f"{round_no}:{role}"
        source = _pick(entries)
        out["requests"][key] = dict(entries)[source]
        if attempt_id in answers and source in dict(answers[attempt_id]):
            out["answers"][key] = dict(answers[attempt_id])[source]
    return out


def round1_bytes(reference, task, config):
    """Pre-send round-1 guard: recorded Z53 bytes; where Z53 never sent the call (arm ended earlier)
    the native study-path reconstruction, which must equal every recorded Z53 round-1 request."""
    out, reconstructed = {}, []
    for role in config.roles:
        native = encoded(payload(Request("round-1", task, role, 1, INSTRUCTIONS[role], (), PRODUCER_LIMIT),
                                 producer_limit=PRODUCER_LIMIT))
        recorded = reference["requests"].get(f"1:{role}")
        if recorded is None:
            out[role] = native
            reconstructed.append(role)
        else:
            need(recorded == native, f"Z53 round-1 bytes differ from native reconstruction for {role}")
            out[role] = recorded
    return out, reconstructed


# --------------------------------------------------------------------------- block

def load_task(block_dir):
    block_dir = Path(block_dir)
    public = json.loads((block_dir / "public.json").read_bytes())
    private = json.loads((block_dir / "reference.json").read_bytes())
    task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
    reference = AnswerReference(private["task_id"], tuple(private["answers"]))
    need(task.task_id == reference.task_id, "task/reference identity")
    return task, reference


def run_block(z53_block, directory, transport, *, deadline, brake, stop=None, sleep=None, clock=None):
    """One demonstration block: arm F*, then arm D, each with its own sender and evidence folder."""
    import time
    from study_preparation.z53_fast import GlobalStop
    z53_block, directory = Path(z53_block), Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    name = z53_block.name
    task, reference = load_task(z53_block)
    (directory / "started.json").write_bytes(encoded({"block": name, "runner": RUNNER, "framework": FRAMEWORK,
                                                      "z53_block": str(z53_block)}))
    (directory / "public.json").write_bytes((z53_block / "public.json").read_bytes())
    sender_class = make_sender_class()
    braked = BrakedTransport(transport, brake, GlobalStop, directory / "brake.jsonl")
    results, summary = {}, {}
    for arm in ARMS:
        ref = z53_arm(z53_block, arm)
        expected_round1, reconstructed = round1_bytes(ref, task, arm_config(arm))
        sender = sender_class(directory / f"provider-{arm}", braked, max_calls=EXPECTED_CALLS[arm],
                              deadline=deadline, stop=stop, sleep=sleep or time.sleep,
                              clock=clock or time.time, round1=expected_round1)
        run_id = f"Z55:{name}:{arm}"
        results[arm], _ = run_arm(arm, task, reference, run_id, sender, directory / arm)
        summary[arm] = {"calls": sender.calls, "known_cost_usd": str(sum(sender.costs.values(), Decimal(0))),
                        "unknown_attempts": sender.unknown_attempts, "rate_retries": sender.rate_retries,
                        "technical_retries": sender.technical_retries, "generations": sender.generations,
                        "terminal_failures": sender.terminal, "round1_without_z53_counterpart": reconstructed}
    evidence = {str(p.relative_to(directory)): sha256(p.read_bytes()).hexdigest()
                for p in sorted(directory.rglob("*")) if p.is_file()}
    (directory / "complete.json").write_bytes(encoded({"block": name, "runner": RUNNER, "results": results,
                                                       "summary": summary, "evidence": evidence}))
    return results, summary


# --------------------------------------------------------------------------- independent verification

def _provider(pdir):
    """attempt_id -> request bytes, final HTTP-200 answer, billed costs, physical attempts.

    Unclear attempts are derived from the raw files (a physical attempt number without a
    received/response pair is a transport error with unknown billing) and must equal the
    sender ledger; nothing is taken from the ledger alone."""
    out, physical, unknown = {}, [], 0
    for b in sorted(pdir.glob("*-binding.json")):
        rec = json.loads(b.read_bytes())
        stem = b.name[:3]
        body = (pdir / f"{stem}-request.json").read_bytes()
        need(rec["request_sha256"] == sha256(body).hexdigest(), "request hash")
        need(rec["attempt_id"] not in out, "attempt sent twice")
        received = {}
        for r in pdir.glob(f"{stem}-p*-received.json"):
            digits = r.name[len(stem) + 2:-len("-received.json")]
            need(digits.isdigit(), "unexpected received file name")
            received[int(digits)] = r
        need(received and max(received) >= 1, "call without any received answer")
        finals, billed = [], []
        for number in range(1, max(received) + 1):
            if number not in received:
                unknown += 1
                physical.append({"request_sha256": rec["request_sha256"], "outcome": "transport_error"})
                continue
            r = received[number]
            meta = json.loads(r.read_bytes())
            raw = (pdir / r.name.replace("-received.json", "-response.json")).read_bytes()
            need(meta["response_sha256"] == sha256(raw).hexdigest(), "response hash")
            physical.append({"request_sha256": rec["request_sha256"], "http_status": meta["http_status"],
                             "response_sha256": meta["response_sha256"]})
            try:
                usage, generation = decode_billing(raw)
                billed.append((usage.cost_usd, generation))
            except Exception:
                pass
            if meta["http_status"] == 200:
                finals.append(raw)
        for earlier in finals[:-1]:  # only zero-cost, zero-token error envelopes may precede
            u, _ = decode_billing(earlier)
            need(u.cost_usd == 0 and u.input_tokens == u.output_tokens == 0
                 and strict_json(earlier)["choices"][0].get("finish_reason") == "error",
                 "two billed answers for one call")
        out[rec["attempt_id"]] = {"body": body, "answer": finals[-1] if finals else None,
                                  "limit": rec["max_output_tokens"], "billed": billed}
    ledger = [json.loads(line) for line in (pdir / "calls.jsonl").read_text().splitlines()] \
        if (pdir / "calls.jsonl").exists() else []
    need(sum(1 for e in ledger if e.get("billing") == "unknown") == unknown,
         "unclear attempts in sender ledger differ from raw files")
    return out, unknown, physical


def verify_block(directory, z53_block):
    """Recompute M2/M3/M5 facts and both arm results from raw files; returns a per-block report."""
    from study_preparation.z53_fast import classify_violation
    directory, z53_block = Path(directory), Path(z53_block)
    proof = json.loads((directory / "complete.json").read_bytes())
    on_disk = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()} - {"complete.json"}
    need(set(proof["evidence"]) == on_disk, "unlisted or missing evidence files")
    for name, checksum in proof["evidence"].items():
        need(sha256((directory / name).read_bytes()).hexdigest() == checksum, f"evidence changed: {name}")
    need((directory / "public.json").read_bytes() == (z53_block / "public.json").read_bytes(), "public task differs")
    task, reference = load_task(z53_block)
    name = proof["block"]
    need(name == z53_block.name and json.loads((directory / "started.json").read_bytes())["block"] == name,
         "block identity")
    report = {"block": name}
    all_physical = []
    for arm in ARMS:
        config = arm_config(arm)
        edges = realized_edges(config)
        ad = directory / arm
        selection = json.loads((ad / "selection.json").read_bytes())
        need({tuple(e) for e in selection["realized_edges"]} == edges, "selection evidence differs from mask")
        result = json.loads((ad / "result.json").read_bytes())
        run_id = f"Z55:{name}:{arm}"
        need(result["run_id"] == run_id, "run id")
        provider, unknown, physical = _provider(directory / f"provider-{arm}")
        all_physical.extend(physical)
        events = [json.loads(line) for line in (ad / "trace.jsonl").read_text().splitlines()]
        entries = [e["node"] for e in events if e["kind"] == "node_entry"]
        started = [e for e in events if e["kind"] == "started"]
        texts = {}
        # M3: only realized nodes are entered, every provider attempt belongs to a started node
        need(set(entries) <= {n for e in edges for n in e}, "node outside realized mask entered")
        need([e["attempt_id"] for e in started] == list(provider), "provider attempts differ from started nodes")
        need(entries == result["entered_nodes"], "entered nodes differ from result")
        for e in events:
            if e["kind"] == "completed":
                texts[e["node"]] = e
        for e in started:
            node = e["node"]
            role, round_no = node.rsplit("@", 1)
            # M2: messages only over realized edges and equal to the producer's completed answer
            expected_sources = [s for s, t in POTENTIAL if t == node and (s, t) in edges] if round_no != "1" else []
            need(e["message_sources"] == expected_sources, "message sources differ from realized in-edges")
            need(len(e["messages"]) == len(e["message_sources"]), "message count differs from realized in-edges")
            for source, message in zip(e["message_sources"], e["messages"]):
                need([message["role"], str(message["round"])] == source.rsplit("@", 1),
                     "message role/round differs from its source node")
                need((source, node) in edges, "message over unrealized edge")
                need(message["text"] == texts[source]["text"] and message["attempt_id"] == texts[source]["attempt_id"],
                     "message text differs from producer answer")
                if arm == "F":
                    need(message["role"] in config.roles, "F* request carries draft/checking content")
            request = Request(e["attempt_id"], task, e["role"], e["round"], e["instruction"],
                              tuple(Message(**m) for m in e["messages"]), e["max_output_tokens"])
            need(e["instruction"] == INSTRUCTIONS[role] and e["max_output_tokens"] ==
                 (AGGREGATOR_LIMIT if role == AGG else PRODUCER_LIMIT), "request contract")
            body = encoded(payload(request, producer_limit=PRODUCER_LIMIT))
            need(provider[e["attempt_id"]]["body"] == body, "request bytes differ from trace")
            sent = json.loads(body)
            prior = json.loads(sent["messages"][1]["content"])["prior_messages"]
            need([(m["role"], m["round"]) for m in prior] == [(m["role"], m["round"]) for m in e["messages"]],
                 "sent prior messages differ")
            raw = provider[e["attempt_id"]]["answer"]
            if node in texts:
                need(raw is not None and decode_outcome(raw, e["max_output_tokens"], F01).text == texts[node]["text"],
                     "completed text differs from provider answer")
        cost = sum((c for a in provider.values() for c, _ in a["billed"]), Decimal(0))
        billed_calls = sum(1 for a in provider.values() if a["billed"])
        need(Decimal(result["cost_usd"]) == cost, "arm cost differs from billed files")
        need(result["call_count"] == billed_calls, "billed call count differs")
        need(result["unknown_attempts"] == unknown, "unknown attempts differ from ledger")
        if result["status"] == "ok":
            need(entries == expected_sequence(config) and len(started) == EXPECTED_CALLS[arm], "successful arm shape")
            answer = texts[AGG_NODE]["text"]
            scores = score_answer(answer, reference)
            need(result["answer"] == answer and result["em"] == scores["em"] and result["f1"] == scores["f1"],
                 "scores differ from recomputation")
        else:
            failed = [e for e in events if e["kind"] in ("model_failed", "failed")]
            need(len(failed) == 1 and result["em"] == result["f1"] == 0.0, "model failure shape")
            raw = provider[failed[0]["attempt_id"]]["answer"]
            if failed[0]["kind"] == "model_failed":
                outcome = decode_outcome(raw, provider[failed[0]["attempt_id"]]["limit"], F01)
                need(isinstance(outcome, ModelFailure) and outcome.reason == result["failure_reason"],
                     "model failure differs from provider answer")
            else:
                limit = provider[failed[0]["attempt_id"]]["limit"]
                try:
                    decode_outcome(raw, limit, F01)
                    raise DemoStop("terminal failure on an F-01-valid answer")
                except ProbeStop:
                    kind, reason = classify_violation(raw, limit)
                need(kind in ("overlimit", "contract") and reason == result["failure_reason"], "terminal classification")
        report[arm] = {"status": result["status"], "em": result["em"], "f1": result["f1"], "cost_usd": str(cost),
                       "calls": len(started), "billed_calls": billed_calls, "unknown_attempts": unknown,
                       "entered": entries, "not_entered": [n for n in NODES if n not in entries],
                       "removed_edges": len(POTENTIAL) - len(edges), "messages_checked": sum(len(e["messages"]) for e in started),
                       "message_rights_checked": True,
                       "generations": [g for a in provider.values() for _, g in a["billed"]]}
    # M5: the durable brake ledger books every physical attempt of both arms in order, incl. errors
    brake = [json.loads(line) for line in (directory / "brake.jsonl").read_text().splitlines()]
    need(len(brake) == len(all_physical), "brake ledger misses physical attempts")
    for booked, seen in zip(brake, all_physical):
        need(booked["request_sha256"] == seen["request_sha256"], "brake ledger order differs")
        if seen.get("outcome") == "transport_error":
            need(booked.get("outcome") == "transport_error" and booked["billing"] == "unknown", "brake transport error")
        else:
            need(booked.get("http_status") == seen["http_status"]
                 and booked.get("response_sha256") == seen["response_sha256"], "brake ledger answer differs")
    brake_cost = sum((Decimal(e["cost_usd"]) for e in brake if e["billing"] == "provider"), Decimal(0))
    need(brake_cost == sum((Decimal(report[a]["cost_usd"]) for a in ARMS), Decimal(0)), "brake ledger cost differs")
    report["brake"] = {"physical_attempts": len(brake), "known_cost_usd": str(brake_cost),
                       "unknown": sum(e["billing"] == "unknown" for e in brake)}
    return report


# --------------------------------------------------------------------------- parity

def parity(directory, z53_block):
    """Compare demo arms with the Z53 arms of the same block (bytes, texts, EM/F1, cost)."""
    directory, z53_block = Path(directory), Path(z53_block)
    out = {}
    for arm in ARMS:
        ref = z53_arm(z53_block, arm)
        provider, _, _ = _provider(directory / f"provider-{arm}")
        result = json.loads((directory / arm / "result.json").read_bytes())
        demo = {}
        for attempt_id, item in provider.items():
            round_no, role, _ = attempt_id.rsplit(":", 3)[1:]
            demo[f"{round_no}:{role}"] = item
        keys = sorted(set(demo) | set(ref["requests"]), key=lambda k: (int(k.split(":")[0]), ROLES.index(k.split(":")[1])
                                                                          if k.split(":")[1] in ROLES else 9))
        rows = []
        first_divergence = None
        for key in keys:
            d, z = demo.get(key), ref["requests"].get(key)
            same_request = d is not None and z is not None and d["body"] == z
            dt = zt = None
            if d is not None and d["answer"] is not None:
                try:
                    dt = decode_outcome(d["answer"], d["limit"], F01).text
                except Exception:
                    dt = None
            if key in ref["answers"]:
                try:
                    zt = decode_outcome(ref["answers"][key], json.loads(z)["max_tokens"], F01).text
                except Exception:
                    zt = None
            same_answer = dt is not None and dt == zt
            if first_divergence is None and same_request and not same_answer:
                first_divergence = {"call": key, "demo_text": dt, "z53_text": zt}
            rows.append({"call": key, "demo_sent": d is not None, "z53_sent": z is not None,
                         "request_identical": same_request, "answer_identical": same_answer})
        zr = ref["result"]
        out[arm] = {"calls": rows,
                    "round1_identical": all(r["request_identical"] for r in rows
                                            if r["call"].startswith("1:") and r["demo_sent"] and r["z53_sent"]),
                    "all_requests_identical": all(r["request_identical"] for r in rows),
                    "all_answers_identical": all(r["answer_identical"] for r in rows),
                    "first_divergence": first_divergence,
                    "demo": {k: result[k] for k in ("status", "em", "f1", "cost_usd", "call_count")},
                    "z53": {k: zr[k] for k in ("status", "em", "f1", "cost_usd", "call_count")}}
    return out
