"""Own tests of the LangGraph attachment (run before every V3 part)."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402  (installs network lock first)

import json  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import unittest  # noqa: E402

from communication_pruning.audit import AuditError, audit  # noqa: E402
from communication_pruning.configurations import bank, dense  # noqa: E402
from communication_pruning.execution import execute  # noqa: E402
from communication_pruning.failure_policy import F01  # noqa: E402
from communication_pruning.journal import read_journal  # noqa: E402

import backends  # noqa: E402
import lg_adapter as lg  # noqa: E402

CONFIGS = {c.config_id: c for c in bank()}
TASK = common.synthetic_tasks(1)[0]


def both(config, rounds, *, f01=False, limit=512, faults=None, folder):
    out = {}
    for name, runner in (("own", execute), ("lg", lg.run)):
        agent = backends.SyntheticAgent(f01=f01, producer_limit=limit, faults=faults)
        journal = Path(folder) / f"{name}.jsonl"
        try:
            trace = runner(TASK, config, agent, rounds=rounds, run_id="t-run", journal_path=journal,
                           producer_limit=limit, failure_policy=F01 if f01 else None)
            error = None
        except Exception as exc:  # noqa: BLE001
            trace, error = None, (type(exc).__name__, str(exc))
        out[name] = {"trace": trace, "error": error, "calls": agent.calls, "journal": journal.read_bytes()}
    return out


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="z56-v3-test-")

    def tearDown(self):
        self.tmp.cleanup()

    def folder(self, name):
        path = Path(self.tmp.name) / name
        path.mkdir()
        return path

    def test_mask_counts(self):
        self.assertEqual(len(lg.potential_edges(2)), 20)
        self.assertEqual(len(lg.potential_edges(1)), 4)
        self.assertEqual(20 - sum(lg.mask(CONFIGS["C01"], 2)), 14)
        self.assertEqual(sum(lg.mask(dense(), 2)), 20)
        self.assertEqual(lg.schedule(CONFIGS["C01"], 2),
                         ["evidence@1", "linking@1", "evidence@2", "linking@2", "aggregator@3"])

    def test_equal_to_execute(self):
        for cid, rounds, f01, limit in (("C01", 2, False, 512), ("C14", 1, False, 1024), ("C10", 2, True, 1024)):
            r = both(CONFIGS[cid], rounds, f01=f01, limit=limit, folder=self.folder(f"{cid}-{rounds}"))
            self.assertIsNone(r["own"]["error"])
            self.assertEqual(r["own"]["trace"], r["lg"]["trace"])
            self.assertEqual(r["own"]["calls"], r["lg"]["calls"])
            self.assertEqual(r["own"]["journal"], r["lg"]["journal"])
        r = both(dense(), 2, folder=self.folder("dense"))
        self.assertEqual(r["own"]["journal"], r["lg"]["journal"])
        self.assertEqual(len(r["lg"]["calls"]), 9)

    def test_failed_call_returns_no_output(self):
        r = both(CONFIGS["C05"], 2, faults={1: "paid_fail", 7: "unknown_fail"}, folder=self.folder("f"))
        self.assertEqual(r["own"]["trace"], r["lg"]["trace"])
        self.assertEqual(r["lg"]["trace"]["status"], "incomplete")
        self.assertIsNone(audit(r["lg"]["trace"], CONFIGS["C05"])["total_cost_usd"])

    def test_model_failure_and_technical(self):
        r = both(CONFIGS["C02"], 2, f01=True, limit=1024, faults={2: "model_failed"}, folder=self.folder("m"))
        self.assertEqual(r["lg"]["trace"]["status"], "model_failed")
        self.assertEqual(r["own"]["journal"], r["lg"]["journal"])
        self.assertEqual(len(r["lg"]["calls"]), 2)
        r = both(CONFIGS["C11"], 2, faults={4: "technical"}, folder=self.folder("t"))
        self.assertEqual(r["own"]["error"], r["lg"]["error"])
        self.assertEqual(r["own"]["error"][0], "Technical")
        self.assertEqual(r["own"]["journal"], r["lg"]["journal"])
        self.assertEqual(len(r["lg"]["calls"]), 4)

    def test_extra_edge_rejected_before_call(self):
        agent = backends.SyntheticAgent(f01=False, producer_limit=512)
        path = self.folder("v1") / "j.jsonl"
        evidence = {}
        config = CONFIGS["C07"]          # ring evidence->linking->draft->evidence: no draft->linking edge
        self.assertNotIn(("draft", "linking"), config.edges)
        with self.assertRaises(AuditError):
            lg.run(TASK, config, agent, rounds=2, run_id="v1", journal_path=path,
                   extra_edges=[("draft@1", "linking@2")], evidence=evidence)
        self.assertIn("draft@1", evidence["delivered_sources"]["linking@2"])
        self.assertNotIn(("linking", 2), [(c["role"], c["round"]) for c in agent.calls])
        self.assertFalse(read_journal(path, config)["sealed"])

    def test_concurrency_is_serialized(self):
        agent = backends.SyntheticAgent(f01=False, producer_limit=512)
        threads = set()
        inner = agent.__call__

        def spy(request):
            threads.add(threading.current_thread().name)
            return inner(request)
        evidence = {}
        lg.run(TASK, dense(), spy, rounds=2, run_id="conc", evidence=evidence)
        self.assertGreater(len(threads), 1)
        self.assertEqual(evidence["executed"], evidence["schedule"])

    def test_missing_node_detected(self):
        agent = backends.SyntheticAgent(f01=False, producer_limit=512)
        with self.assertRaises((lg.IncompleteSchedule, lg.GateTimeout)):
            lg.run(TASK, CONFIGS["C01"], agent, rounds=2, run_id="miss",
                   extra_waits={"aggregator@3": ["draft@2"]}, timeout=2)

    def test_network_lock(self):
        self.assertTrue(common.netguard.installed())
        self.assertTrue(common.netguard.selftest())


if __name__ == "__main__":
    unittest.main()
