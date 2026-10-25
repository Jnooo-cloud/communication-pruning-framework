"""The three Z31 synthetic cases; optional pinned foreign runtime, no providers."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from communication_pruning.gptswarm_probe import run_case

AVAILABLE = importlib.util.find_spec("torch") is not None and importlib.util.find_spec("swarm") is not None


@unittest.skipUnless(AVAILABLE, "requires the isolated Z31 GPTSwarm source/runtime")
class GPTSwarmProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_pruning_changes_actual_receivers_and_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            for case, actors, answer in (("dense", ["A", "B", "C"], ["ALPHA|BETA"]),
                                         ("pruned", ["A", "C"], ["ALPHA"])):
                folder = Path(tmp) / case
                result = await run_case(folder, case)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["native_answer"], answer)
                inner = [json.loads(line) for line in (folder / "client.jsonl").read_text().splitlines()]
                self.assertEqual([row["actor"] for row in inner if row["kind"] == "started"], actors)
                self.assertEqual(result["native_node_entries"], actors)

    async def test_native_swallowed_failure_does_not_become_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "failed_b"
            result = await run_case(folder, "failed_b")
            self.assertEqual(result["status"], "rejected")
            self.assertTrue(result["ledger_poisoned"])
            self.assertIsNone(result["ledger_active"])
            self.assertEqual(result["native_node_entries"], ["A", "B", "C"])
            self.assertEqual(result["blocked_before_inner_client"], ["C"])
            inner = [json.loads(line) for line in (folder / "client.jsonl").read_text().splitlines()]
            self.assertEqual([row["actor"] for row in inner if row["kind"] == "started"], ["A", "B"])
            self.assertEqual(inner[-1]["kind"], "failed")
            self.assertEqual(inner[-1]["usage"]["cost_usd"], "0.002")
