"""Z55 GPTSwarm demonstration: masks, byte parity, M2/M3/M5, brake, verification (offline, no network)."""
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
import uuid

EVAL = Path(__file__).resolve().parents[1]
Z31 = EVAL / "runs/Z31-PRUNING-001"
for extra in (str(EVAL / "runs/Z53-SCHNELLFORTSETZUNG-001"), str(Z31 / "runtime"), str(Z31 / "original"), str(EVAL)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from communication_pruning import gptswarm_musique_demo as g  # noqa: E402
from communication_pruning.contracts import INSTRUCTIONS, Message, Request, TaskInput  # noqa: E402
from communication_pruning.data import AnswerReference  # noqa: E402
from communication_pruning.evaluation import score_answer  # noqa: E402
from communication_pruning.execution import execute  # noqa: E402
from communication_pruning.failure_policy import F01  # noqa: E402
from communication_pruning.openrouter import ProbeStop, encoded  # noqa: E402
from study_preparation import z53_fast as z  # noqa: E402
import fake_transport  # noqa: E402

TASK = TaskInput("task-demo-1", "Who founded the city?", ("Para one about a city.", "Para two about a founder."))
REFERENCE = AnswerReference("task-demo-1", ("Founder",))
Z53_REAL = EVAL / "runs/Z53-SCHNELLFORTSETZUNG-001/live/blocks/R-02183"


def no_sleep(_):
    pass


class Deterministic:
    """Same request bytes -> same answer; optional per-call faults by (call number -> kind)."""

    def __init__(self, faults=None):
        self.faults, self.n, self.bodies = dict(faults or {}), 0, []

    def __call__(self, endpoint, body):
        assert endpoint == "chat/completions"
        self.n += 1
        self.bodies.append(body)
        fault = self.faults.get(self.n)
        gen = f"gen-test-{uuid.uuid4().hex}"
        limit = json.loads(body)["max_tokens"]
        if fault == "transport":
            raise ProbeStop("transport failed; billing may be unknown")
        if fault == "overlimit":
            return 200, fake_transport.answer(gen, "x", finish="length", out=limit + 1)
        if fault == "length":
            return 200, fake_transport.answer(gen, "", finish="length", out=limit)
        if fault == 429:
            return 429, b'{"error": {"code": 429}}'
        content = ["Founder", "Somebody", "founder", "Nobody"][int(sha256(body).hexdigest(), 16) % 4]
        return 200, fake_transport.answer(gen, content)


def native_block(root, transport, name="R-00001"):
    """A Z53-shaped block produced by the native study path (execution.execute + BlockSender)."""
    block = Path(root) / name
    block.mkdir(parents=True)
    (block / "public.json").write_bytes(encoded(asdict(TASK)))
    (block / "reference.json").write_bytes(encoded(asdict(REFERENCE)))
    sender = z.BlockSender(block / "provider", transport, max_calls=14, deadline=time.time() + 10 ** 6, sleep=no_sleep)
    for arm in g.ARMS:
        (block / arm).mkdir()
        run_id = f"native:{name}:{arm}"
        trace = execute(TASK, g.arm_config(arm), sender, rounds=2, run_id=run_id,
                        journal_path=block / arm / "journal.jsonl", producer_limit=1024, failure_policy=F01)
        ok = trace["status"] == "completed"
        scores = score_answer(trace["answer"], REFERENCE) if ok else {"em": 0.0, "f1": 0.0}
        (block / arm / "result.json").write_bytes(encoded({
            "run_id": run_id, "status": "ok" if ok else "model_failure", **scores,
            "cost_usd": str(sender.cost_for(run_id)), "call_count": sender.calls_for(run_id)}))
    return block


def demo(block, out, transport, brake=None):
    return g.run_block(block, out, transport, deadline=time.time() + 10 ** 6, brake=brake or g.CostBrake(),
                       sleep=no_sleep)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)


class GraphTests(Base):
    def test_original_realize_gives_exact_masks(self):
        for arm, count in (("F", 6), ("D", 20)):
            graph, edges, evidence = g.build_original(arm)
            self.assertEqual(len(evidence["realized_edges"]), count)
            self.assertEqual({tuple(e) for e in evidence["realized_edges"]}, edges)
            self.assertEqual(len(evidence["removed_edges"]), 20 - count)
            self.assertEqual(evidence["log_probability"], 0.0)
        _, _, d = g.build_original("D")
        self.assertEqual(d["realized_edges"], d["realize_full_edges"])

    def test_f_star_has_no_draft_or_checking_edge(self):
        _, edges, _ = g.build_original("F")
        self.assertFalse({n for e in edges for n in e} & {"draft@1", "draft@2", "checking@1", "checking@2"})

    def test_realized_edges_match_execution_semantics(self):
        config = g.arm_config("F")
        expected = set()
        for target in config.roles:
            for source in config.roles:
                if source == target or (source, target) in config.edges:
                    expected.add((source + "@1", target + "@2"))
        expected |= {(r + "@2", g.AGG_NODE) for r in config.roles}
        self.assertEqual(g.realized_edges(config), expected)


class ParityTests(Base):
    def test_all_request_bytes_identical_to_native_study_path(self):
        block = native_block(self.tmp / "z53", Deterministic())
        results, _ = demo(block, self.tmp / "demo" / block.name, Deterministic())
        report = g.verify_block(self.tmp / "demo" / block.name, block)
        par = g.parity(self.tmp / "demo" / block.name, block)
        for arm in g.ARMS:
            self.assertTrue(par[arm]["all_requests_identical"], arm)
            self.assertTrue(par[arm]["all_answers_identical"], arm)
            self.assertEqual(par[arm]["demo"]["em"], par[arm]["z53"]["em"])
            self.assertEqual(report[arm]["calls"], g.EXPECTED_CALLS[arm])
        self.assertEqual(results["F"]["not_entered_nodes"], ["draft@1", "checking@1", "draft@2", "checking@2"])
        self.assertEqual(results["D"]["not_entered_nodes"], [])

    def test_round1_guard_stops_before_any_send(self):
        Sender = g.make_sender_class()
        transport = Deterministic()
        sender = Sender(self.tmp / "p", transport, max_calls=5, deadline=time.time() + 100, sleep=no_sleep,
                        round1={"evidence": b"different bytes"})
        request = Request("x:1:evidence:1", TASK, "evidence", 1, INSTRUCTIONS["evidence"], (), 1024)
        with self.assertRaises(z.GlobalStop):
            sender(request)
        self.assertEqual(transport.n, 0)

    def test_block_with_deviating_round1_bytes_stops(self):
        block = native_block(self.tmp / "z53", Deterministic())
        public = json.loads((block / "public.json").read_bytes())
        public["question"] = "Another question?"
        reference_block = self.tmp / "z53b" / block.name
        shutil.copytree(block, reference_block)
        # demo reads the task from public.json; the recorded Z53 round-1 bytes belong to the old question
        (reference_block / "public.json").write_bytes(encoded(public))
        transport = Deterministic()
        with self.assertRaises(g.DemoStop):   # recorded Z53 bytes no longer match the task: stop before sending
            demo(reference_block, self.tmp / "demo" / block.name, transport)
        self.assertEqual(transport.n, 0)

    def test_round1_reconstructed_where_z53_arm_ended_early(self):
        block = native_block(self.tmp / "z53", Deterministic({1: "length"}))   # Z53 F stops after evidence@1
        self.assertEqual(json.loads((block / "F" / "result.json").read_bytes())["call_count"], 1)
        results, summary = demo(block, self.tmp / "demo" / block.name, Deterministic())
        self.assertEqual(results["F"]["status"], "ok")
        self.assertEqual(summary["F"]["round1_without_z53_counterpart"], ["linking"])
        par = g.parity(self.tmp / "demo" / block.name, block)
        self.assertTrue(par["F"]["round1_identical"])
        self.assertEqual(sum(r["demo_sent"] and not r["z53_sent"] for r in par["F"]["calls"]), 4)

    def test_z53_round1_bytes_must_equal_native_reconstruction(self):
        block = native_block(self.tmp / "z53", Deterministic())
        ref = g.z53_arm(block, "F")
        ref["requests"]["1:evidence"] = ref["requests"]["1:evidence"].replace(b"Para one", b"Para 1")
        with self.assertRaises(g.DemoStop):
            g.round1_bytes(ref, TASK, g.arm_config("F"))

    @unittest.skipUnless(Z53_REAL.exists(), "real Z53 block not available")
    def test_replay_of_real_z53_block_is_identical(self):
        spec = importlib.util.spec_from_file_location("run_z55", EVAL / "runs/Z55-GPTSWARM-DEMO-001/run_z55.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        replay = runner.Replay(Z53_REAL)
        demo(Z53_REAL, self.tmp / "demo" / Z53_REAL.name, replay)
        par = g.parity(self.tmp / "demo" / Z53_REAL.name, Z53_REAL)
        self.assertEqual(replay.misses, 0)
        for arm in g.ARMS:
            self.assertTrue(par[arm]["all_requests_identical"] and par[arm]["all_answers_identical"])
            self.assertEqual(Decimal(par[arm]["demo"]["cost_usd"]), Decimal(par[arm]["z53"]["cost_usd"]))


class RightsTests(Base):
    """M2/M3 negative cases at the node->sender boundary: rejected before any provider call."""

    def context(self, arm="F"):
        transport = Deterministic()
        sender = z.BlockSender(self.tmp / f"p-{uuid.uuid4().hex}", transport, max_calls=9, deadline=time.time() + 100, sleep=no_sleep)
        config = g.arm_config(arm)
        ctx = g.ArmContext(self.tmp, TASK, "t:" + arm, sender, g.realized_edges(config), g.graph_input(TASK))
        return ctx, transport

    def test_message_over_unrealized_edge_rejected(self):
        ctx, transport = self.context()
        forged = {"node": "draft@1", "attempt_id": "t:F:1:draft:1", "role": "draft", "round": 1,
                  "text": "draft text", "output": "draft text"}
        with self.assertRaises(g.DemoStop):
            ctx.invoke("evidence@2", [forged])
        self.assertEqual(transport.n, 0)
        self.assertIsInstance(ctx.failure, g.DemoStop)

    def test_node_outside_mask_rejected(self):
        ctx, transport = self.context()
        with self.assertRaises(g.DemoStop):
            ctx.invoke("draft@1", g.graph_input(TASK))
        self.assertEqual(transport.n, 0)

    def test_tampered_message_rejected(self):
        ctx, transport = self.context()
        first = ctx.invoke("evidence@1", g.graph_input(TASK))
        second = ctx.invoke("linking@1", g.graph_input(TASK))
        with self.assertRaises(g.DemoStop):
            ctx.invoke("evidence@2", [dict(first, text="forged"), second])
        self.assertEqual(transport.n, 2)

    def test_missing_message_rejected(self):
        ctx, transport = self.context()
        first = ctx.invoke("evidence@1", g.graph_input(TASK))
        ctx.invoke("linking@1", g.graph_input(TASK))
        with self.assertRaises(g.DemoStop):
            ctx.invoke("evidence@2", [first])
        self.assertEqual(transport.n, 2)

    def test_mutated_original_output_object_rejected(self):
        ctx, transport = self.context()
        first = ctx.invoke("evidence@1", g.graph_input(TASK))
        second = ctx.invoke("linking@1", g.graph_input(TASK))
        first["text"] = "FORGED"                      # mutate the very object the framework delivers
        with self.assertRaises(g.DemoStop):
            ctx.invoke("evidence@2", [first, second])
        ctx2, transport2 = self.context()
        a = ctx2.invoke("evidence@1", g.graph_input(TASK))
        b = ctx2.invoke("linking@1", g.graph_input(TASK))
        b["role"] = "draft"
        with self.assertRaises(g.DemoStop):
            ctx2.invoke("evidence@2", [a, b])
        self.assertEqual((transport.n, transport2.n), (2, 2))

    def test_logging_error_after_stop_still_blocks_later_nodes(self):
        calls = []

        def sender(request):
            calls.append(request.attempt_id)
            raise z.GlobalStop("stop")

        class Broken(g.ArmContext):
            def _record(self, value):
                if value["kind"] == "failed":
                    raise OSError("disk full")
                super()._record(value)
        ctx = Broken(self.tmp, TASK, "t:F", sender, g.realized_edges(g.arm_config("F")), g.graph_input(TASK))
        with self.assertRaises(OSError):
            ctx.invoke("evidence@1", g.graph_input(TASK))
        self.assertIsInstance(ctx.failure, z.GlobalStop)
        with self.assertRaises(RuntimeError):
            ctx.invoke("linking@1", g.graph_input(TASK))
        self.assertEqual(len(calls), 1)

    def test_round1_node_needs_task_input(self):
        ctx, transport = self.context()
        with self.assertRaises(g.DemoStop):
            ctx.invoke("evidence@1", {"task": {"question": "other"}})
        self.assertEqual(transport.n, 0)

    def test_failure_blocks_all_later_nodes(self):
        ctx, transport = self.context()
        ctx.failure = RuntimeError("earlier")
        with self.assertRaises(RuntimeError):
            ctx.invoke("evidence@1", g.graph_input(TASK))
        self.assertEqual(ctx.blocked, ["evidence@1"])
        self.assertEqual(transport.n, 0)


class FailureAndCostTests(Base):
    def run_with(self, faults):
        block = native_block(self.tmp / "z53", Deterministic())
        transport = Deterministic(faults)
        brake = g.CostBrake()
        results, summary = demo(block, self.tmp / "demo" / block.name, transport, brake)
        report = g.verify_block(self.tmp / "demo" / block.name, block)
        return results, summary, report, brake

    def test_terminal_failure_counts_cost_and_blocks_successors(self):
        results, summary, report, _ = self.run_with({1: "overlimit"})
        f = results["F"]
        self.assertEqual((f["status"], f["em"], f["f1"]), ("model_failure", 0.0, 0.0))
        self.assertEqual(f["call_count"], 1)
        self.assertEqual(f["blocked_nodes"], ["linking@1", "evidence@2", "linking@2", g.AGG_NODE])
        self.assertEqual(Decimal(f["cost_usd"]), Decimal(summary["F"]["known_cost_usd"]))
        self.assertGreater(Decimal(f["cost_usd"]), 0)
        self.assertEqual(results["D"]["status"], "ok")
        self.assertEqual(report["F"]["calls"], 1)

    def test_model_failure_length_ends_arm_with_all_costs(self):
        results, summary, report, _ = self.run_with({4: "length"})
        f = results["F"]
        self.assertEqual(f["status"], "model_failure")
        self.assertEqual(f["failure_reason"], "length")
        self.assertEqual(f["call_count"], 4)
        self.assertEqual(f["blocked_nodes"], [g.AGG_NODE])
        self.assertEqual(Decimal(f["cost_usd"]), Decimal(summary["F"]["known_cost_usd"]))

    def test_unclear_attempt_stays_unknown(self):
        results, summary, report, brake = self.run_with({2: "transport", 5: 429})
        f = results["F"]
        self.assertEqual(f["status"], "ok")
        self.assertEqual(f["unknown_attempts"], 1)
        self.assertEqual(report["F"]["unknown_attempts"], 1)
        self.assertEqual(brake.unknown, 1)
        self.assertEqual(f["call_count"], 5)

    def test_brake_refuses_before_transport(self):
        transport = Deterministic()
        brake = g.CostBrake(Decimal("0.30"), Decimal("0.10"), 1)
        self.assertFalse(brake.admit())
        with self.assertRaises(z.GlobalStop):
            g.BrakedTransport(transport, brake, z.GlobalStop, self.tmp / "b.jsonl")("chat/completions", b"{}")
        self.assertEqual(transport.n, 0)
        self.assertTrue(g.CostBrake(Decimal("1.00"), Decimal("0.85"), 0).admit())
        self.assertFalse(g.CostBrake(Decimal("1.00"), Decimal("0.87"), 0).admit())
        with self.assertRaises(g.DemoStop):
            g.CostBrake(Decimal("1.01"))

    def test_billed_error_answers_are_booked_and_stop(self):
        def billed(status, cost):
            def transport(endpoint, body):
                raw = json.loads(fake_transport.answer(f"gen-{uuid.uuid4().hex}", "x"))
                raw["usage"]["cost"] = cost
                return status, json.dumps(raw).encode()
            return transport
        for status, cost in ((500, "0.10"), (429, "0.15"), (200, "0.15")):
            brake = g.CostBrake()
            ledger = self.tmp / f"b-{status}.jsonl"
            with self.assertRaises(z.GlobalStop):
                g.BrakedTransport(billed(status, cost), brake, z.GlobalStop, ledger)("chat/completions", b"{}")
            self.assertEqual(brake.known, Decimal(cost))
            self.assertEqual(json.loads(ledger.read_text().splitlines()[0])["cost_usd"], cost)

    def test_unverifiable_billing_on_429_stops_and_keeps_answer(self):
        def transport(endpoint, body):
            raw = json.loads(fake_transport.answer(f"gen-{uuid.uuid4().hex}", "x", provider="OtherProvider"))
            raw["usage"]["cost"] = "0.10"
            return 429, json.dumps(raw).encode()
        brake = g.CostBrake()
        ledger = self.tmp / "b.jsonl"
        with self.assertRaises(z.GlobalStop):
            g.BrakedTransport(transport, brake, z.GlobalStop, ledger)("chat/completions", b"{}")
        self.assertEqual(brake.unknown, 1)
        self.assertEqual(len(list(self.tmp.glob("brake-stop-0001-*.json"))), 2)

    def test_plain_429_is_free_and_retried(self):
        brake = g.CostBrake()
        braked = g.BrakedTransport(lambda e, b: (429, b'{"error": {"code": 429, "message": "rate limited"}}'),
                                   brake, z.GlobalStop, self.tmp / "b.jsonl")
        self.assertEqual(braked("chat/completions", b"{}")[0], 429)
        self.assertEqual((brake.known, brake.unknown), (Decimal(0), 0))

    def test_more_than_99_physical_attempts_verify(self):
        block = native_block(self.tmp / "z53", Deterministic())
        out = self.tmp / "demo" / block.name
        demo(block, out, Deterministic({i: 429 for i in range(1, 101)}))
        self.assertTrue((out / "provider-F" / "001-p101-received.json").exists())
        report = g.verify_block(out, block)
        self.assertEqual(report["brake"]["physical_attempts"], 101 + 4 + 9)

    def test_duplicate_generation_stops_before_next_transport(self):
        fixed = fake_transport.answer("gen-same", "x")
        n = []

        def transport(endpoint, body):
            n.append(1)
            return 200, fixed
        braked = g.BrakedTransport(transport, g.CostBrake(), z.GlobalStop, self.tmp / "b.jsonl")
        braked("chat/completions", b"{}")
        with self.assertRaises(z.GlobalStop):
            braked("chat/completions", b"{}")
        self.assertEqual(len(n), 2)

    def test_brake_stops_block_midway(self):
        block = native_block(self.tmp / "z53", Deterministic())
        brake = g.CostBrake(Decimal("0.28"), Decimal("0"), 1)   # admits exactly one more attempt
        transport = Deterministic()
        with self.assertRaises(z.GlobalStop):
            demo(block, self.tmp / "demo" / block.name, transport, brake)
        self.assertEqual(transport.n, 1)

    def test_extra_call_beyond_mask_is_impossible(self):
        Sender = g.make_sender_class()
        transport = Deterministic()
        sender = Sender(self.tmp / "p", transport, max_calls=1, deadline=time.time() + 100, sleep=no_sleep)
        request = Request("x:2:evidence:1", TASK, "evidence", 2, INSTRUCTIONS["evidence"], (), 1024)
        sender(request)
        with self.assertRaises(z.GlobalStop):
            sender(Request("x:2:linking:1", TASK, "linking", 2, INSTRUCTIONS["linking"], (), 1024))
        self.assertEqual(transport.n, 1)


class VerificationTests(Base):
    def good(self):
        block = native_block(self.tmp / "z53", Deterministic())
        out = self.tmp / "demo" / block.name
        demo(block, out, Deterministic())
        return block, out

    def rehash(self, out):
        proof = json.loads((out / "complete.json").read_bytes())
        proof["evidence"] = {str(p.relative_to(out)): sha256(p.read_bytes()).hexdigest()
                             for p in sorted(out.rglob("*")) if p.is_file() and p.name != "complete.json"}
        (out / "complete.json").write_bytes(encoded(proof))

    def test_changed_request_file_detected(self):
        block, out = self.good()
        path = next((out / "provider-F").glob("003-request.json"))
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(g.DemoStop):
            g.verify_block(out, block)

    def test_forged_message_in_trace_detected_even_with_fresh_hashes(self):
        block, out = self.good()
        trace = out / "F" / "trace.jsonl"
        lines = [json.loads(line) for line in trace.read_text().splitlines()]
        for e in lines:
            if e["kind"] == "started" and e["node"] == "evidence@2":
                e["message_sources"][1] = "draft@1"
        trace.write_bytes(b"".join(encoded(e) + b"\n" for e in lines))
        self.rehash(out)
        with self.assertRaises(g.DemoStop):
            g.verify_block(out, block)

    def test_extra_forbidden_message_detected(self):
        block, out = self.good()
        trace = out / "F" / "trace.jsonl"
        lines = [json.loads(line) for line in trace.read_text().splitlines()]
        for e in lines:
            if e["kind"] == "started" and e["node"] == "evidence@2":
                e["messages"].append({"attempt_id": "x", "role": "draft", "round": 1, "text": "draft"})
        trace.write_bytes(b"".join(encoded(e) + b"\n" for e in lines))
        self.rehash(out)
        with self.assertRaises(g.DemoStop):
            g.verify_block(out, block)

    def test_removed_unknown_ledger_entry_detected(self):
        block = native_block(self.tmp / "z53", Deterministic())
        out = self.tmp / "demo" / block.name
        demo(block, out, Deterministic({2: "transport"}))
        ledger = out / "provider-F" / "calls.jsonl"
        ledger.write_text("".join(line + "\n" for line in ledger.read_text().splitlines()
                                  if '"unknown"' not in line))
        self.rehash(out)
        with self.assertRaises(g.DemoStop):
            g.verify_block(out, block)

    def test_unlisted_extra_attempt_detected(self):
        block, out = self.good()
        (out / "provider-F" / "099-request.json").write_bytes(b"{}")
        with self.assertRaises(g.DemoStop):
            g.verify_block(out, block)

    def test_runner_never_writes_into_old_trees(self):
        spec = importlib.util.spec_from_file_location("run_z55", EVAL / "runs/Z55-GPTSWARM-DEMO-001/run_z55.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        for old in (runner.Z53 / "live/x", runner.Z54 / "y", runner.Z31 / "original/z", runner.Z52 / "q"):
            with self.assertRaises(z.GlobalStop):
                runner.guard_write(old)
        runner.guard_write(self.tmp / "ok")


if __name__ == "__main__":
    unittest.main()
