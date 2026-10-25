"""Hand-derived expected cases and adversarial trace edits, entirely offline."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal
import json
import unittest

from communication_pruning.audit import AuditError, audit
from communication_pruning.configurations import bank, dense, without_peers
from communication_pruning.contracts import (AdapterError, Configuration, Response,
                                              TaskInput, Usage)
from communication_pruning.execution import execute


TASK = TaskInput("artificial", "Which box?", ("The marble is in box A.",))


def stub(request):
    return Response(f"{request.role}/{request.round}", Usage(10, 2, Decimal("0.01"), "synthetic"))


class ConfigurationTests(unittest.TestCase):
    def test_bank_has_fourteen_distinct_configs(self):
        self.assertEqual(len(bank()), 14)
        self.assertEqual(len({(c.roles, c.edges) for c in bank()}), 14)
        self.assertEqual([c.config_id for c in bank()], [f"C{i:02}" for i in range(1, 15)])

    def test_six_pairs_and_eight_triples(self):
        self.assertEqual([len(c.roles) for c in bank()], [2] * 6 + [3] * 8)
        self.assertEqual([len(c.edges) for c in bank()], [2] * 6 + [3, 6] * 4)

    def test_first_ring_has_fixed_direction(self):
        self.assertEqual(bank()[6].edges, (("evidence", "linking"), ("linking", "draft"), ("draft", "evidence")))

    def test_dense_is_outside_bank(self):
        self.assertEqual(len(dense().edges), 12)
        self.assertNotIn(dense().config_id, [c.config_id for c in bank()])

    def test_invalid_config_rejected(self):
        for roles, edges in [((), ()), (("evidence", "evidence"), ()), (("invalid",), ()),
                             (("evidence",), (("evidence", "evidence"),)),
                             (("evidence",), (("evidence", "draft"),))]:
            with self.subTest(roles=roles, edges=edges), self.assertRaises(ValueError):
                Configuration("bad", roles, edges)

    def test_public_task_has_no_gold_field(self):
        with self.assertRaises(TypeError):
            TaskInput("id", "q", (), gold_answer="x")
        with self.assertRaises(FrozenInstanceError):
            TASK.question = "changed"
        with self.assertRaises(ValueError):
            TaskInput("id", "q", ["mutable"])


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.config = bank()[0]

    def run_config(self, config=None, **kwargs):
        return execute(TASK, config or self.config, stub, **kwargs)

    def test_complete_bank_needs_86_calls(self):
        self.assertEqual(sum(audit(self.run_config(c), c)["calls"] for c in bank()), 86)

    def test_pair_triple_dense_counts(self):
        for c, count in [(bank()[0], 5), (bank()[6], 7), (dense(), 9)]:
            with self.subTest(c=c.config_id):
                self.assertEqual(audit(self.run_config(c), c)["calls"], count)

    def test_one_round_is_separate_factor(self):
        self.assertEqual(audit(self.run_config(rounds=1), self.config)["calls"], 3)

    def test_synchronous_rounds_and_own_previous_output(self):
        starts = [e for e in self.run_config()["events"] if e["kind"] == "started"]
        self.assertEqual([e["messages"] for e in starts[:2]], [[], []])
        self.assertEqual([[m["text"] for m in e["messages"]] for e in starts[2:4]],
                         [["evidence/1", "linking/1"], ["evidence/1", "linking/1"]])
        self.assertEqual([m["text"] for m in starts[-1]["messages"]], ["evidence/2", "linking/2"])

    def test_ring_receives_only_incoming_peer_and_self(self):
        starts = [e for e in self.run_config(bank()[6])["events"] if e["kind"] == "started"]
        self.assertEqual([m["role"] for m in starts[3]["messages"]], ["evidence", "draft"])

    def test_without_peers_preserves_roles_rounds_and_calls(self):
        config = without_peers(self.config)
        trace = self.run_config(config)
        starts = [e for e in trace["events"] if e["kind"] == "started"]
        self.assertEqual([m["role"] for m in starts[2]["messages"]], ["evidence"])
        self.assertEqual(audit(trace, config)["calls"], 5)

    def test_suppressed_role_never_called_in_either_round(self):
        trace = self.run_config(failed_role="evidence")
        self.assertEqual(audit(trace, self.config)["calls"], 3)
        self.assertEqual(sum(e["kind"] == "suppressed" for e in trace["events"]), 2)
        self.assertFalse(any(e.get("role") == "evidence" and e["kind"] == "started" for e in trace["events"]))

    def test_adapter_receives_same_raw_context_and_fixed_limits(self):
        requests = []
        def adapter(request):
            requests.append(request)
            return stub(request)
        execute(TASK, self.config, adapter)
        self.assertTrue(all(r.task is TASK for r in requests))
        self.assertEqual([r.max_output_tokens for r in requests], [512] * 4 + [128])

    def test_invalid_controls_rejected(self):
        for kwargs in ({"rounds": 0}, {"rounds": True}, {"rounds": 3}, {"failed_role": "draft"}, {"run_id": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_config(**kwargs)

    def test_json_roundtrip_and_stable_explicit_run_id(self):
        trace = self.run_config(run_id="test-run")
        self.assertEqual(json.loads(json.dumps(trace)), trace)
        self.assertEqual(trace, self.run_config(run_id="test-run"))

    def test_programming_error_is_not_swallowed(self):
        def broken(request):
            raise RuntimeError("bug")
        with self.assertRaises(RuntimeError):
            execute(TASK, self.config, broken)


class AccountingTests(unittest.TestCase):
    def test_invalid_usage_rejected(self):
        for kwargs in ({"input_tokens": -1}, {"input_tokens": True}, {"output_tokens": 1.2},
                       {"cost_usd": Decimal("NaN"), "cost_source": "provider"},
                       {"cost_usd": Decimal("-1"), "cost_source": "provider"},
                       {"cost_usd": Decimal("1")}, {"cost_source": "provider"},
                       {"cost_usd": Decimal("1"), "cost_source": "token_price"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Usage(**kwargs)

    def test_unknown_is_not_zero(self):
        c = bank()[0]
        report = audit(execute(TASK, c, lambda r: Response("x")), c)
        self.assertIsNone(report["total_cost_usd"])
        self.assertEqual(report["unknown_cost_calls"], 5)
        self.assertEqual(report["cost_coverage"], 0)

    def test_known_zero_remains_known(self):
        c = bank()[0]
        report = audit(execute(TASK, c, lambda r: Response("x", Usage(cost_usd=Decimal(0), cost_source="synthetic"))), c)
        self.assertEqual(report["total_cost_usd"], "0")
        self.assertEqual(report["cost_coverage"], 1)
        self.assertEqual(report["synthetic_cost_calls"], 5)

    def test_failed_call_known_cost_is_counted(self):
        def failing(request):
            if request.role == "evidence" and request.round == 1:
                raise AdapterError("synthetic failure", Usage(cost_usd=Decimal("0.03"), cost_source="synthetic"))
            return stub(request)
        c = bank()[0]
        report = audit(execute(TASK, c, failing), c)
        self.assertEqual(report["total_cost_usd"], "0.07")
        self.assertEqual(report["failed_calls"], 1)

    def test_failed_unknown_cost_makes_total_unknown(self):
        def failing(request):
            if request.role == "aggregator":
                raise AdapterError("unknown billing")
            return stub(request)
        c = bank()[0]
        trace = execute(TASK, c, failing)
        report = audit(trace, c)
        self.assertIsNone(trace["answer"])
        self.assertEqual(trace["status"], "incomplete")
        self.assertIsNone(report["total_cost_usd"])
        self.assertEqual(report["known_cost_subtotal_usd"], "0.04")


class AuditMutationTests(unittest.TestCase):
    def setUp(self):
        self.config = bank()[6]
        self.trace = execute(TASK, self.config, stub, run_id="audit-case")

    def rejected(self, mutate):
        trace = deepcopy(self.trace)
        mutate(trace)
        with self.assertRaises(AuditError):
            audit(trace, self.config)

    def test_missing_terminal(self):
        self.rejected(lambda t: t["events"].pop())

    def test_duplicate_attempt(self):
        self.rejected(lambda t: t["events"].extend(t["events"][:2]))

    def test_same_round_leak(self):
        self.rejected(lambda t: t["events"][2]["messages"].append({"attempt_id": "audit-case:1:evidence:1", "role": "evidence", "round": 1, "text": "evidence/1"}))

    def test_forbidden_edge(self):
        self.rejected(lambda t: t["events"][6]["messages"].append({"attempt_id": "audit-case:1:linking:1", "role": "linking", "round": 1, "text": "linking/1"}))

    def test_message_text_substitution(self):
        self.rejected(lambda t: t["events"][6]["messages"][0].update(text="fabricated"))

    def test_cross_run_reference(self):
        self.rejected(lambda t: t["events"][6]["messages"][0].update(attempt_id="another-run:1:evidence:1"))

    def test_changed_graph(self):
        self.rejected(lambda t: t["configuration"]["edges"].clear())

    def test_extra_gold_field(self):
        self.rejected(lambda t: t["task"].update(gold_answer="hidden"))

    def test_changed_answer(self):
        self.rejected(lambda t: t.update(answer="fabricated"))

    def test_nonfinite_cost(self):
        self.rejected(lambda t: t["events"][1]["usage"].update(cost_usd="NaN"))

    def test_unknown_cost_mislabeled(self):
        self.rejected(lambda t: t["events"][1]["usage"].update(cost_usd=None))

    def test_changed_output_limit(self):
        self.rejected(lambda t: t["events"][0].update(max_output_tokens=999))

    def test_trailing_null_event(self):
        self.rejected(lambda t: t["events"].append(None))

    def test_boolean_schema_rejected(self):
        self.rejected(lambda t: t.update(schema=True))


if __name__ == "__main__":
    unittest.main()
