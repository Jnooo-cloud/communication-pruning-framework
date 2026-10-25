"""Z31 native GPTSwarm edge-selection probe with a synthetic observed client.

The original optional GPTSwarm source/runtime must be provided on PYTHONPATH.
This is not a benchmark controller or a provider adapter.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random

from .contracts import AdapterError, Usage
from .foreign_observer import BoundaryLedger, canonical

COMMIT = "c23a827f561c934ce21dd950408f7606aa4a8821"
FRAMEWORK = "GPTSwarm@" + COMMIT
CASES = ("dense", "pruned", "failed_b")
POTENTIAL = (("A", "C"), ("B", "C"))
SYNTHETIC_INPUT = {"question": "Combine the available synthetic markers.", "context": "A supplies ALPHA; B supplies BETA."}


def save_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def append(path, value):
    with Path(path).open("ab") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


@dataclass
class CaseContext:
    folder: Path
    case: str
    ledger: BoundaryLedger
    native_nodes: list = field(default_factory=list)
    blocked_nodes: list = field(default_factory=list)

    def inner_client(self, actor, value):
        # This independently retained client boundary supplies known synthetic truth.
        append(self.folder / "client.jsonl", {"kind": "started", "actor": actor, "input": value})
        failed = self.case == "failed_b" and actor == "B"
        usage = Usage(input_tokens=20, output_tokens=0 if failed else 8,
                      cost_usd=Decimal("0.002" if failed else "0.001"), cost_source="synthetic")
        if failed:
            append(self.folder / "client.jsonl", {"kind": "failed", "actor": actor, "usage": usage.to_dict(),
                                                  "error": "planned synthetic B failure"})
            raise AdapterError("planned synthetic B failure", usage)
        output = {"A": "ALPHA", "B": "BETA"}.get(actor)
        if actor == "C":
            output = "|".join(item["output"] for item in value)
        response = {"actor": actor, "output": output}
        append(self.folder / "client.jsonl", {"kind": "completed", "actor": actor, "usage": usage.to_dict(),
                                              "response": response})
        return response, usage

    def invoke(self, actor, value):
        self.native_nodes.append(actor)
        append(self.folder / "node-entry.jsonl", {"actor": actor, "input": value})
        if self.ledger.poisoned:
            self.blocked_nodes.append(actor)
            raise RuntimeError("observed client is stopped after failure")
        messages = [{"role": "user", "content": canonical(value).decode()}]
        attempt = self.ledger.start(actor, messages)
        try:
            response, usage = self.inner_client(actor, value)
        except AdapterError as error:
            self.ledger.finish(attempt, "failed", error.usage, error=str(error))
            raise
        self.ledger.finish(attempt, "completed", usage, response=response)
        return response


def make_original_graph(case):
    if case not in CASES:
        raise ValueError("only the three planned synthetic cases are supported")
    import torch
    from swarm.graph.graph import Graph
    from swarm.graph.node import Node
    from swarm.graph.composite_graph import CompositeGraph
    from swarm.memory import GlobalMemory
    from swarm.optimizer.edge_optimizer.parameterization import EdgeWiseDistribution

    class ProbeNode(Node):
        def __init__(self, label):
            super().__init__("Z31 synthetic client " + label, id=label, combine_inputs_as_one=True)
            self.context = None

        async def _execute(self, input, **kwargs):
            if self.context is None:
                raise RuntimeError("client must be attached after original graph realization")
            return self.context.invoke(self.id, input)

    class ProducerGraph(Graph):
        def __init__(self, label):
            self.label = label
            super().__init__(domain="Z31-synthetic")

        def build_graph(self):
            node = self.add_node(ProbeNode(self.label))
            self.input_nodes = [node]
            self.output_nodes = [node]

    random.seed(31)
    torch.manual_seed(31)
    torch.set_num_threads(1)
    GlobalMemory.instance().clear()
    graph = CompositeGraph(ProbeNode("C"), domain="Z31-synthetic")
    graph.add_graph(ProducerGraph("A"))
    graph.add_graph(ProducerGraph("B"))
    if graph.num_edges != 0:
        raise RuntimeError("selection requires an initially unconnected candidate graph")
    distribution = EdgeWiseDistribution(list(POTENTIAL))
    with torch.no_grad():
        distribution.edge_logits.copy_(torch.tensor([math.log(9), -math.log(9)]))
    if case == "pruned":
        selected, log_probability = distribution.realize(graph, temperature=1.0, threshold=0.5, use_learned_order=False)
        method = "EdgeWiseDistribution.realize"
    else:
        selected = distribution.realize_full(graph)
        log_probability = None
        method = "EdgeWiseDistribution.realize_full"
    evidence = {"selection_method": method, "potential_connections": list(POTENTIAL),
                "fixture_logits": distribution.edge_logits.detach().tolist(), "threshold": 0.5 if case == "pruned" else None,
                "temperature": 1.0, "learned_order": False, "training": False,
                "initial_edges": graph.num_edges, "seed": 31, "torch_version": torch.__version__,
                "selected_edges": sorted([node.id, successor.id] for node in selected.nodes.values() for successor in node.successors),
                "log_probability": None if log_probability is None else float(log_probability.detach())}
    source_objects = {"Graph.run": Graph.run, "Node.execute": Node.execute,
                      "CompositeGraph.check_cycle": CompositeGraph.check_cycle,
                      "EdgeWiseDistribution.realize": EdgeWiseDistribution.realize,
                      "EdgeWiseDistribution.realize_full": EdgeWiseDistribution.realize_full}
    import inspect
    evidence["native_sources"] = {name: {"path": inspect.getsourcefile(obj),
        "sha256": sha256(Path(inspect.getsourcefile(obj)).read_bytes()).hexdigest()} for name, obj in source_objects.items()}
    return selected, evidence


async def run_case(folder, case):
    if case not in CASES:
        raise ValueError("unplanned case")
    folder = Path(folder)
    folder.mkdir()
    graph, selection = make_original_graph(case)
    save_new(folder / "selection.json", selection)
    ledger = BoundaryLedger(folder / "journal.jsonl", "Z31-" + case, "Z31-SYNTHETIC", framework=FRAMEWORK)
    context = CaseContext(folder, case, ledger)
    # Attach after deepcopy in the unmodified foreign selector; one live ledger.
    for node in graph.nodes.values():
        node.context = context
    native_answer = await graph.run(dict(SYNTHETIC_INPUT), max_tries=1, max_time=10)
    status = "rejected" if ledger.poisoned or ledger.active is not None else "completed"
    result = {"case": case, "framework": FRAMEWORK, "status": status, "native_answer": native_answer,
              "native_node_entries": context.native_nodes, "blocked_before_inner_client": context.blocked_nodes,
              "node_outputs": {key: node.outputs for key, node in graph.nodes.items()},
              "ledger_poisoned": ledger.poisoned, "ledger_active": ledger.active,
              "real_model_calls": 0, "scope": "Synthetic functional integration; no trained adaptive policy or performance claim."}
    save_new(folder / "result.json", result)
    return result
