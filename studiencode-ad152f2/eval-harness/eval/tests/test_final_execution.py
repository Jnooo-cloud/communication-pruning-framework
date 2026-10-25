"""Small synthetic S2–S4/S7/S8 checks against actual injected call bodies."""
from decimal import Decimal
from pathlib import Path
from copy import deepcopy
import json
import unittest

from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference
from communication_pruning.failure_policy import F01
from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import PhaseBudget, BudgetStop
from communication_pruning.study import StudyAdapter
from study_preparation import final_execution as fe, final_preflight as fp
from tests.study_fixture import FakeTransport
from tests.test_final_preflight import Fixture, trial_directory


class AnswersTransport(FakeTransport):
    def __init__(self, answers, **kwargs):
        super().__init__(**kwargs)
        self.answers = answers

    def __call__(self, endpoint, body=None):
        status, raw = super().__call__(endpoint, body)
        if endpoint == "chat/completions":
            value = json.loads(raw)
            value["choices"][0]["message"]["content"] = self.answers[self.calls - 1]
            raw = encoded(value)
        return status, raw


def direct_fixture(directory, answers, *, mode=None, fail_at=None, arm="S-k", seed=17):
    root = Path(directory)
    (root / "provider").mkdir()
    budget = PhaseBudget(root / "budget.jsonl", cap=Decimal("2"), reserve=Decimal("0.14"),
                         max_calls=5, binding="d" * 64, allow_synthetic=True)
    transport = AnswersTransport(answers, mode=mode, fail_at=fail_at)
    adapter = StudyAdapter(root / "provider", transport, budget, synthetic=True, failure_policy=F01)
    task = TaskInput("synthetic-public", "Invented?", ("Safe invented context.",))
    reference = AnswerReference(task.task_id, ("private-never-sent",))
    result = fe._direct(task, reference, "synthetic-run", arm, seed, root, adapter)
    return result, transport, budget


class FinalExecutionTests(unittest.TestCase):
    def test_all_panels_fresh_slots_repeated_task_and_actual_model_bodies(self):
        with trial_directory() as directory:
            f = Fixture(directory, counts={"P": 2, "R": 1, "T": 1, "F": 1})
            for end in range(1, 6):
                state = f.run(end)
            self.assertTrue(state["complete"])
            self.assertEqual(len(state["rows"]), 16)
            self.assertEqual(len(set(row["slot_id"] for row in state["rows"])), 16)
            self.assertEqual(len(set(row["task_id"] for row in state["rows"])), 1)
            self.assertEqual(len(f.loads), 5)
            self.assertEqual(len(f.selections), 5)
            self.assertEqual(len(f.time_selections), 1)
            self.assertEqual(state["budget"]["calls"], sum(row["call_count"] for row in state["rows"]))
            self.assertEqual(len(state["generation_ids"]), f.transport.calls)
            self.assertEqual(len(fe.collect_panel(f.candidate, f.plan, "P", **f.args())), 4)
            singles = [b for b in f.transport.bodies if b["messages"][0]["content"] == fp.DIRECT_INSTRUCTION]
            self.assertEqual(len(singles), 6)
            for body in singles:
                self.assertEqual(body["max_tokens"], 1024)
                self.assertEqual(json.loads(body["messages"][1]["content"])["prior_messages"], [])
            bodies = json.dumps(f.transport.bodies)
            for forbidden in ("PRIVATE_FAKE_GOLD", "synthetic-", "family_id", "block_id", "task-"):
                self.assertNotIn(forbidden, bodies)
            before = f.transport.calls
            with self.assertRaises(fp.StudyStop):
                f.run(5)
            self.assertEqual(f.transport.calls, before)

    def test_direct_single_five_calls_empty_normalized_class_and_original_winner(self):
        with trial_directory() as directory:
            result, transport, _ = direct_fixture(directory, ["The.", "a", "THE", "Paris", "Paris!"])
            self.assertEqual(transport.calls, 5)
            self.assertEqual(result["vote"]["selected_class"], "")
            self.assertEqual(result["vote"]["answer"], "The.")
            self.assertEqual(result["vote"]["representative_index"], 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["cost_usd"], "0.0000540")
            self.assertTrue(all(b["messages"][0]["content"] == fp.DIRECT_INSTRUCTION for b in transport.bodies))
        with trial_directory() as directory:
            result, transport, _ = direct_fixture(directory, ["One original answer."], arm="S", seed=0)
            self.assertEqual(transport.calls, 1)
            self.assertEqual(result["vote"]["answer"], "One original answer.")

    def test_ties_are_sorted_seeded_and_never_shortcut_five_votes(self):
        answers = ["Zulu", "beta", "BETA!", "Zulu.", "third"]
        result = fe.plurality(answers, 97)
        self.assertEqual(result["tie_classes"], ["beta", "zulu"])
        self.assertEqual(result, fe.plurality(answers, 97))
        self.assertEqual(result["answer"], answers[result["representative_index"]])
        with trial_directory() as directory:
            _, transport, _ = direct_fixture(directory, ["same"] * 5)
            self.assertEqual(transport.calls, 5)

    def test_direct_f01_stops_whole_slot_and_keeps_paid_prefix(self):
        for mode, answers in (("length", ["ok"] * 5), (None, ["ok", "ok", "   ", "later", "later"])):
            with self.subTest(mode=mode), trial_directory() as directory:
                result, transport, budget = direct_fixture(directory, answers, fail_at=3, mode=mode)
                self.assertEqual(transport.calls, 3)
                self.assertEqual((result["status"], result["em"], result["f1"]), ("model_failure", 0, 0))
                self.assertIsNone(result["vote"])
                self.assertEqual(result["cost_usd"], str(budget.cost))
                self.assertFalse((Path(directory) / "direct-4.json").exists())

    def test_temporal_and_fault_calls_use_existing_graph_without_rerouting(self):
        triple = next(c for c in bank() if len(c.roles) == 3 and len(c.edges) == 3)
        with trial_directory() as directory:
            f = Fixture(directory, q=triple.config_id, fixed="C01", temporal=2)
            for end in (1, 2, 3, 4):
                state = f.run(end)
            temporal = {row["arm"]: row for row in state["rows"] if row["panel"] == "T"}
            self.assertEqual((temporal["Q-ST"]["call_count"], temporal["Q-TF"]["call_count"]), (7, 4))
            self.assertEqual(temporal["Q-ST"]["configuration"], temporal["Q-TF"]["configuration"])
            block = f.plan["panels"]["F"][0]
            for arm, config in (("Qf", triple), ("Ff", bank()[0])):
                failed = next(r for r in block["fault_permutation"] if r in config.roles)
                journal = f.folder / "blocks" / "000003" / arm / "journal.jsonl"
                trace = fe.read_journal(journal, config)["trace"]
                self.assertEqual(trace["failed_role"], failed)
                self.assertEqual(sum(e["kind"] == "suppressed" for e in trace["events"]), 2)
                starts = [e for e in trace["events"] if e["kind"] == "started"]
                self.assertTrue(all(e["role"] != failed for e in starts))
                for event in starts:
                    if event["round"] == 2:
                        expected = [r for r in config.roles if r != failed and (r == event["role"] or (r, event["role"]) in config.edges)]
                        self.assertEqual([m["role"] for m in event["messages"]], expected)
                self.assertEqual([m["role"] for m in starts[-1]["messages"]], [r for r in config.roles if r != failed])

    def test_model_failure_allows_other_fresh_arm_but_technical_failure_never_resumes(self):
        with trial_directory() as directory:
            f = Fixture(directory)
            f.transport.fail_at, f.transport.mode = 1, "length"
            state = f.run(1)
            self.assertEqual([row["status"] for row in state["rows"]], ["model_failure", "ok"])
            self.assertEqual(f.transport.calls, 6)
        for mode in ("unknown", "http", "over", "transport", "duplicate", "interrupt"):
            with self.subTest(mode=mode), trial_directory() as directory:
                f = Fixture(directory)
                f.transport.fail_at, f.transport.mode = 2, mode
                with self.assertRaises((BudgetStop, KeyboardInterrupt)):
                    f.run(1)
                before = f.transport.calls
                with self.assertRaises(Exception):
                    f.run(1)
                self.assertEqual(f.transport.calls, before)
                self.assertTrue((f.folder / "budget.jsonl").exists())
                self.assertFalse((f.folder / "blocks" / "000000" / "complete.json").exists())

    def test_claim_lock_checkpoint_and_tampering_cannot_repeat_slots(self):
        with trial_directory() as directory:
            f = Fixture(directory)
            with fe.study_lock(f.control):
                with self.assertRaises(fp.StudyStop):
                    f.run(1)
            self.assertEqual(f.transport.calls, 0)
            first = f.run(1)
            before = f.transport.calls
            old_folder = f.folder
            f.folder = f.root / "other-output"
            with self.assertRaises(fp.StudyStop):
                f.run(2)
            f.folder = old_folder
            self.assertEqual(f.transport.calls, before)
            receipt = fe._receipt_path(f.folder, first)
            receipt.unlink()
            with self.assertRaises(FileNotFoundError):
                f.run(2)
            self.assertEqual(f.transport.calls, before)
            fe.checkpoint_study(f.candidate, f.plan, **f.args(), checkpoint=f.checkpoint)
            f.run(2)
            before = f.transport.calls
            path = f.folder / "blocks" / "000000" / "selection.json"
            path.write_text(path.read_text() + " ")
            with self.assertRaises(fp.StudyStop):
                f.run(3)
            self.assertEqual(f.transport.calls, before)

    def test_duplicate_generation_after_completed_prefix_is_retained_and_stops(self):
        with trial_directory() as directory:
            f = Fixture(directory)
            f.run(1)
            before = f.transport.calls
            f.transport.fail_at, f.transport.mode = before + 1, "duplicate"
            with self.assertRaises(BudgetStop):
                f.run(2)
            self.assertEqual(f.transport.calls, before + 1)
            self.assertTrue((f.folder / "provider" / f"{before + 1:05d}-response.json").exists())


if __name__ == "__main__":
    unittest.main()
