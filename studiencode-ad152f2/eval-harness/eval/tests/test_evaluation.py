"""Synthetic scoring and aggregation with independently calculated expectations."""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from communication_pruning.configurations import bank
from communication_pruning.contracts import AdapterError, Response, TaskInput, Usage
from communication_pruning.data import AnswerReference
from communication_pruning.evaluation import (PlannedTask, RunResult, development_observations,
                                              normalize_answer, paired_summary, read_result, score_answer)
from communication_pruning.execution import execute
from communication_pruning.selection import CONFIG_IDS, fit_selector


def result(task="A", config="C01", repeat=1, *, q=1., cost="1", run_prefix="run", family="f", phase="spatial"):
    return RunResult(f"{run_prefix}-{task}-{config}-{repeat}", task, family, phase, config, repeat,
                     "completed", q, q, Decimal(cost), Decimal(cost), 1, "0"*64)


class EvaluationTests(unittest.TestCase):
    def test_k1_official_normalization_aliases_and_word_multiplicity(self):
        self.assertEqual(normalize_answer(" The   BLUE-box! "), "bluebox")
        ref = AnswerReference("A", ("red red blue", "other name"))
        score = score_answer("red blue", ref)
        self.assertEqual(score["em"], 0.)
        self.assertAlmostEqual(score["f1"], .8)
        self.assertEqual(score_answer("OTHER, name!", ref), {"em": 1., "f1": 1.})
        self.assertEqual(score_answer(" ", ref), {"em": 0., "f1": 0.})
        self.assertEqual(score_answer("unknown", ref), {"em": 0., "f1": 0.})
        with self.assertRaises(ValueError):
            score_answer(None, ref)

    def test_k2_journal_binding_and_error_status(self):
        task = TaskInput("public", "Synthetic question?", ("Synthetic context",))
        reference = AnswerReference("public", ("blue",))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"complete.jsonl"
            execute(task, bank()[0], lambda _: Response("The blue", Usage(cost_usd=Decimal(".01"), cost_source="synthetic")),
                    journal_path=path)
            options = dict(family_id="family", phase="technical", repeat=1)
            scored = read_result(path, bank()[0], task, reference, **options)
            self.assertEqual(scored.em, 1.)
            self.assertEqual(scored.cost_usd, Decimal(".05"))
            for wrong_task, wrong_reference in ((replace(task, question="changed"), reference),
                                                  (task, AnswerReference("other", ("blue",)))):
                with self.assertRaises(ValueError):
                    read_result(path, bank()[0], wrong_task, wrong_reference, **options)
            failed = Path(directory)/"failed.jsonl"
            def error(_):
                raise AdapterError("synthetic failure")
            execute(task, bank()[0], error, journal_path=failed)
            scored = read_result(failed, bank()[0], task, reference, **options)
            self.assertEqual(scored.status, "incomplete")
            self.assertIsNone(scored.em)
            self.assertIsNone(scored.cost_usd)
            self.assertEqual(scored.known_subtotal_usd, Decimal(0))
            unfinished = Path(directory)/"unfinished.jsonl"
            def broken(_):
                raise RuntimeError("interrupted")
            with self.assertRaises(RuntimeError):
                execute(task, bank()[0], broken, journal_path=unfinished)
            with self.assertRaises(ValueError):
                read_result(unfinished, bank()[0], task, reference, **options)

    def development_case(self):
        plan = [PlannedTask(TaskInput("A", "short", ()), "fa", "spatial", (1, 2)),
                PlannedTask(TaskInput("B", "long question", ()), "fb", "spatial", (1,))]
        rows = [result(p.task.task_id, c, r, q=float(p.task.task_id == "B" or r == 1),
                       cost="2" if p.task.task_id == "A" else "5", family=p.family_id)
                for p in plan for c in CONFIG_IDS for r in p.repeats]
        return rows, plan

    def test_k3_repeats_average_before_tasks_and_costs_not_duplicated(self):
        rows, plan = self.development_case()
        table = development_observations(rows, plan)
        observations = table["observations"]
        self.assertEqual(table["executed_runs"], 42)
        self.assertEqual(table["executed_cost_usd"], Decimal(126))
        self.assertEqual(table["task_count"], 2)
        self.assertEqual(observations[0].quality, (.5,)*14)
        self.assertEqual(observations[1].quality, (1.,)*14)
        self.assertEqual(observations[0].costs, (Decimal(2),)*14)
        self.assertEqual(sum(r.quality[0] for r in observations)/2, .75)
        model = fit_selector(observations, seed="synthetic-only")
        self.assertEqual(model.select(plan[0].task), "C01")

    def test_k4_missing_duplicate_extra_role_family_and_unknown_cost_rejected(self):
        rows, plan = self.development_case()
        broken = [rows[:-1], rows+[rows[0]], rows+[replace(rows[0], repeat=3)],
                  [replace(rows[0], phase="pilot")]+rows[1:],
                  [replace(rows[0], family_id="different")]+rows[1:],
                  [replace(rows[0], cost_usd=None)]+rows[1:],
                  [replace(rows[0], status="incomplete", em=None, f1=None)]+rows[1:]]
        for case in broken:
            with self.subTest(case=broken.index(case)), self.assertRaises(ValueError):
                development_observations(case, plan)

    def test_k5_task_weighted_ratio_of_means_not_mean_ratios(self):
        fixed = [result("A", repeat=1, q=0., cost="1", run_prefix="F"),
                 result("A", repeat=2, q=0., cost="1", run_prefix="F"),
                 result("B", q=1., cost="9", run_prefix="F")]
        adaptive = [result("A", repeat=1, q=1., cost="1", run_prefix="Q"),
                    result("A", repeat=2, q=1., cost="1", run_prefix="Q"),
                    result("B", q=1., cost="1", run_prefix="Q")]
        slots = {("A", 1), ("A", 2), ("B", 1)}
        summary = paired_summary(fixed, adaptive, expected_slots=slots, phase="spatial")
        self.assertEqual(summary["tasks"], 2)
        self.assertEqual(summary["families"], 1)
        self.assertEqual(summary["quality_difference"], .5)
        self.assertEqual(Decimal(summary["cost_ratio"]), Decimal(".2"))
        self.assertEqual(Decimal(summary["mean_cost_fixed_usd"]), Decimal(5))
        with self.assertRaises(ValueError):
            paired_summary(fixed, adaptive[:-1], expected_slots=slots, phase="spatial")
        with self.assertRaises(ValueError):
            paired_summary(fixed, fixed, expected_slots=slots, phase="spatial")

    def test_invalid_pairing_and_zero_denominator(self):
        with self.assertRaises(ValueError):
            paired_summary([result(run_prefix="F")], [result(run_prefix="Q", family="wrong")],
                           expected_slots={("A", 1)}, phase="spatial")
        with self.assertRaises(ValueError):
            paired_summary([result(run_prefix="F", cost="0")], [result(run_prefix="Q")],
                           expected_slots={("A", 1)}, phase="spatial")
        with self.assertRaises(ValueError):
            PlannedTask(TaskInput("A", "q", ()), "f", "spatial", (1, 1))
        with self.assertRaises(ValueError):
            PlannedTask(TaskInput("A", "q", ()), "f", "holdout", (1,))

    def test_k7_mixed_data_phases_must_not_be_pooled(self):
        fixed = [result("A", phase="pilot", run_prefix="F"), result("B", phase="holdout", run_prefix="F")]
        adaptive = [result("A", phase="pilot", run_prefix="Q"), result("B", phase="holdout", run_prefix="Q")]
        with self.assertRaises(ValueError):
            paired_summary(fixed, adaptive, expected_slots={("A", 1), ("B", 1)}, phase="pilot")

    def test_k7_same_missing_task_in_both_arms_rejected(self):
        with self.assertRaises(ValueError):
            paired_summary([result(run_prefix="F")], [result(run_prefix="Q")],
                           expected_slots={("A", 1), ("B", 1)}, phase="spatial")

    def test_k8_complete_synthetic_workflow(self):
        from communication_pruning.demo import demo
        report = demo()
        self.assertEqual(report["development_journals"], 28)
        self.assertEqual(report["development_calls"], 172)
        self.assertEqual(report["comparison_journals"], 2)
        self.assertEqual(report["comparison_calls"], 10)
        self.assertEqual(report["selector_fallback"], "fewer_than_five_families")
        self.assertEqual(report["comparison"]["quality_difference"], 0.)
        self.assertEqual(report["comparison"]["cost_ratio"], "1")
