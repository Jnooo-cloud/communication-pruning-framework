"""Z09 deterministic reference matrix; no provider, benchmark, or credential use."""
import ast
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest

import measurement_reference as reference
from communication_pruning.audit import audit, audit_prefix, AuditError
from communication_pruning.configurations import bank, dense, without_peers
from communication_pruning.contracts import AdapterError, Response, TaskInput, Usage
from communication_pruning.execution import execute
from communication_pruning.journal import read_journal

TASK = TaskInput("z09-synthetic", "An artificial question?", ("Artificial context A.", "Artificial context B."))


def exercise(config, rounds=2, suppressed=None, limit=512, mode="success", journal=None):
    observed = []
    def agent(req):
        if req.task != TASK:
            raise AssertionError("public input changed")
        observed.append({"role": req.role, "round": req.round, "limit": req.max_output_tokens,
                         "messages": [{"role": m.role, "round": m.round, "text": m.text} for m in req.messages]})
        i = len(observed)
        usage = Usage(10*i, i, Decimal(i)/1000, "synthetic")
        if i == 1 and mode != "success":
            raise AdapterError("synthetic fault", Usage(10, 1) if mode == "unknown" else usage)
        return Response(f"output:{req.round}:{req.role}", usage)
    trace = execute(TASK, config, agent, rounds=rounds, failed_role=suppressed,
                    producer_limit=limit, run_id="z09", journal_path=journal)
    return observed, trace


class MeasurementTests(unittest.TestCase):
    def test_k1_reference_has_no_measured_import_and_hand_anchors(self):
        tree = ast.parse(Path(reference.__file__).read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertEqual(imports, ["decimal"])
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        for name, calls, peer, own, aggregate in (("C01", 5, 2, 2, 2), ("D", 9, 12, 4, 4), ("D-no-peers", 9, 0, 4, 4)):
            got = reference.expected(name, 2, None, 512, "success")
            self.assertEqual(got["calls"], calls)
            self.assertEqual(got["messages"], {"peer": peer, "own": own, "aggregator": aggregate})
        self.assertEqual(Decimal(reference.expected("C01", 2, None, 512, "success")["total_cost_usd"]), Decimal(".015"))
        self.assertEqual(Decimal(reference.expected("C01", 2, None, 512, "unknown")["known_cost_usd"]), Decimal(".014"))

    def test_k2_k3_full_720_case_matrix(self):
        configs = (*bank(), dense(), without_peers(dense()))
        self.assertEqual({c.config_id for c in configs}, set(reference.MEMBERS))
        evidence = os.environ.get("Z09_MATRIX_EVIDENCE")
        sink = open(evidence, "x") if evidence else None
        count = 0
        try:
            for config in configs:
                roles, edges = reference.policy(config.config_id)
                self.assertEqual(config.roles, roles)
                self.assertEqual(set(config.edges), edges)
                for rounds in (1, 2):
                    for limit in (512, 1024):
                        for suppressed in (None, *roles):
                            for mode in ("success", "known", "unknown"):
                                spec = {"configuration": config.config_id, "rounds": rounds, "limit": limit, "suppressed": suppressed, "mode": mode}
                                expected = reference.expected(config.config_id, rounds, suppressed, limit, mode)
                                observed, trace = exercise(config, rounds, suppressed, limit, mode)
                                report = audit(trace, config)
                                if sink:
                                    sink.write(json.dumps({"case": spec, "expected": expected, "observed_requests": observed, "trace": trace, "audit": report})+"\n")
                                    sink.flush()
                                with self.subTest(**spec):
                                    self.assertEqual(observed, expected["requests"])
                                    for field in ("calls", "failed_calls", "unknown_cost_calls"):
                                        self.assertEqual(report[field], expected[field])
                                    self.assertEqual(Decimal(report["known_cost_subtotal_usd"]), Decimal(expected["known_cost_usd"]))
                                    self.assertEqual(None if report["total_cost_usd"] is None else Decimal(report["total_cost_usd"]),
                                                     None if expected["total_cost_usd"] is None else Decimal(expected["total_cost_usd"]))
                                    self.assertEqual(report["cost_coverage"], (expected["calls"]-expected["unknown_cost_calls"])/expected["calls"])
                                    self.assertEqual(sum(e["kind"] == "suppressed" for e in trace["events"]), expected["suppressed_events"])
                                    ends = [e for e in trace["events"] if e["kind"] in ("completed", "failed")]
                                    self.assertEqual(sum(e["usage"]["input_tokens"] for e in ends), expected["input_tokens"])
                                    self.assertEqual(sum(e["usage"]["output_tokens"] for e in ends), expected["output_tokens"])
                                    for i, event in enumerate(ends, 1):
                                        self.assertEqual(event["usage"]["cost_usd"], None if i == 1 and mode == "unknown" else str(Decimal(i)/1000))
                                count += 1
        finally:
            if sink: sink.close()
        self.assertEqual(count, 720)

    def test_k3_known_zero_is_not_unknown(self):
        trace = execute(TASK, bank()[0], lambda _: Response("zero", Usage(0, 0, Decimal(0), "synthetic")))
        got = audit(trace, bank()[0])
        self.assertEqual(got["total_cost_usd"], "0")
        self.assertEqual((got["unknown_cost_calls"], got["cost_coverage"]), (0, 1))

    def test_k4_all_event_prefixes_stay_partial(self):
        _, trace = exercise(bank()[0])
        for n in range(len(trace["events"])+1):
            prefix = {k: deepcopy(v) for k, v in trace.items() if k not in ("answer", "status")}
            prefix["events"] = prefix["events"][:n]
            got = audit_prefix(prefix, bank()[0])
            self.assertEqual(got["started_attempts"], (n+1)//2)
            self.assertEqual(got["calls"], n//2)
            self.assertIsNone(got["total_cost_usd"])
            self.assertEqual(len(got["unresolved_attempt_ids"]), n % 2)
            self.assertEqual(Decimal(got["known_cost_subtotal_usd"]), Decimal((n//2)*(n//2+1))/2000)
            self.assertEqual(got["schedule_complete"], n == len(trace["events"]))

    def test_k4_actual_local_abort_keeps_open_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"execution.jsonl"
            sent = []
            def agent(req):
                sent.append(req)
                if len(sent) == 2: raise RuntimeError("controlled abort")
                return Response("first", Usage(10, 1, Decimal(".001"), "synthetic"))
            with self.assertRaises(RuntimeError): execute(TASK, bank()[0], agent, journal_path=path)
            got = read_journal(path, bank()[0])
            self.assertFalse(got["sealed"])
            self.assertEqual((got["audit"]["started_attempts"], got["audit"]["calls"]), (2, 1))
            self.assertIsNone(got["audit"]["total_cost_usd"])
            with self.assertRaises(FileExistsError): execute(TASK, bank()[0], agent, journal_path=path)
            self.assertEqual(len(sent), 2)

    def test_k5_invalid_protocol_mutations_are_rejected(self):
        _, trace = exercise(bank()[0])
        bad = []
        t = deepcopy(trace); del t["events"][1]; bad.append(t)
        t = deepcopy(trace); t["events"].insert(2, deepcopy(t["events"][0])); bad.append(t)
        t = deepcopy(trace); t["events"][4]["messages"][0]["text"] = "invented"; bad.append(t)
        t = deepcopy(trace); t["events"][0]["max_output_tokens"] = 1024; bad.append(t)
        t = deepcopy(trace); t["events"] = t["events"][:3]; bad.append(t)
        t = deepcopy(trace); t["events"][1]["usage"]["cost_usd"] = None; bad.append(t)
        for i, candidate in enumerate(bad):
            with self.subTest(mutation=i):
                with self.assertRaises(AuditError): audit(candidate, bank()[0])

    def test_k5_coherent_false_cost_needs_external_expected_value(self):
        _, trace = exercise(bank()[0])
        trace["events"][1]["usage"]["cost_usd"] = "0"
        got = audit(trace, bank()[0])  # Syntactically valid; not a provider invoice audit.
        expected = reference.expected("C01", 2, None, 512, "success")
        self.assertNotEqual(Decimal(got["total_cost_usd"]), Decimal(expected["total_cost_usd"]))
        self.assertEqual(Decimal(got["total_cost_usd"]), Decimal(".014"))
