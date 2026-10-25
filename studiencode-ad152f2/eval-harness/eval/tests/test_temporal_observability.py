"""Z50 N2: hand-constructed temporal model; no fit and no actual encoder."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from communication_pruning.contracts import TaskInput
from communication_pruning.semantic_selection import ALPHAS, DIMENSION, encoder_identity
from study_preparation import temporal


class ArtificialEncoder:
    def __init__(self):
        self.identity = encoder_identity({name: "3" * 64 for name in (
            "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
            "vocab.txt", "model.safetensors")},
            {"test_double": True, "not_real_encoder_evidence": True})
        self.last_metadata = None

    def encode_questions(self, questions):
        rows = []
        for question in questions:
            row = [0.0] * 384
            row[0 if question == "positive" else 1] = 1.0
            rows.append(row)
        self.last_metadata = {"artificial": True, "encoder_ns": 12, "questions": len(questions),
                              "token_lengths_before_truncation": [3] * len(questions),
                              "truncated_questions": 0}
        return rows, self.last_metadata


def artificial_selector():
    """A validated five-fold export assembled from constants, never trained."""
    encoder = ArtificialEncoder()
    ids = ["artificial-train-" + str(i) for i in range(5)]

    def model(alpha, training_ids):
        coefficients = [[0.0] * DIMENSION for _ in range(2)]
        coefficients[0][0] = 1.0
        coefficients[1][1] = 1.0
        return {"alpha": alpha, "mean": [0.0] * DIMENSION, "scale": [1.0] * DIMENSION,
                "coefficients": coefficients, "intercepts": [0.0, 0.0],
                "constant": [False, False] + [True] * (DIMENSION - 2),
                "training_task_ids": list(training_ids), "training_quality": [0.5, 0.5],
                "costs": ["1", "1"], "fixed_rounds": 1}

    reports = []
    for alpha in ALPHAS:
        reports.append({"alpha": alpha, "quality": 0.5, "cost_usd": "1",
                        "folds": [{"fold": i, "validation_task_ids": [task_id],
                                   "model": model(alpha, [t for t in ids if t != task_id])}
                                  for i, task_id in enumerate(ids)],
                        "outcomes": [{"task_id": task_id, "fold": i, "rounds": 1,
                                      "scores": [1.0, 0.0], "quality": 0.5, "cost_usd": "1"}
                                     for i, task_id in enumerate(ids)]})
    payload = {"schema": "z44-temporal-selector/v1", "parameters": deepcopy(temporal.PARAMETERS),
               "bindings": {"raw_q_source": "a" * 64}, "encoder": deepcopy(encoder.identity),
               "folds": [[t] for t in ids], "task_families": {t: "family-" + t for t in ids},
               "spatial_configurations": {t: "C01" for t in ids},
               "cross_validation": reports, "chosen_alpha": 100, "model": model(100, ids),
               "fixed_rounds": 1, "training_selections": [1] * len(ids),
               "encoding": {"artificial": True, "no_fit_performed": True},
               "independent_effect_evidence": False, "study_frozen": False, "send_enabled": False}
    return temporal.TemporalSelector(payload, encoder=encoder)


class TemporalObservabilityTests(unittest.TestCase):
    def test_known_choice_exact_timing_and_encoding_metadata_are_retained(self):
        selector = artificial_selector()
        before = temporal.canonical(selector.to_dict())
        task = TaskInput("opaque-repeat", "positive", ("artificial context excluded from records",))
        with patch.object(temporal, "perf_counter_ns", side_effect=(100, 170, 190)):
            self.assertEqual(selector.select(task), 1)
        self.assertEqual(selector.selection_timings_ns, [90])
        record = selector.selection_records[0]
        self.assertEqual(record, {"selection_index": 1, "task_id": "opaque-repeat",
                                 "encoding": {"artificial": True, "encoder_ns": 12, "questions": 1,
                                              "token_lengths_before_truncation": [3], "truncated_questions": 0},
                                 "feature_and_encoder_ns": 70, "score_and_choice_ns": 20, "total_ns": 90})
        self.assertEqual(temporal.canonical(selector.to_dict()), before)
        selector.encoder.last_metadata["token_lengths_before_truncation"][0] = 99
        self.assertEqual(record["encoding"]["token_lengths_before_truncation"], [3])
        self.assertNotIn(task.question, json.dumps(record))
        self.assertNotIn(task.paragraphs[0], json.dumps(record))

    def test_repeated_task_ids_keep_distinct_selections_and_fixed_expected_decisions(self):
        selector = artificial_selector()
        before = selector.to_dict()
        with patch.object(temporal, "perf_counter_ns", side_effect=(10, 20, 30, 100, 140, 200)), \
                patch.object(temporal, "fit_temporal_ridge", side_effect=AssertionError("fit forbidden")), \
                patch.object(temporal, "fit_temporal_selector", side_effect=AssertionError("fit forbidden")):
            choices = [selector.select(TaskInput("opaque-repeat", text, ("artificial context",)))
                       for text in ("positive", "negative")]
        self.assertEqual(choices, [1, 2])
        self.assertEqual([r["selection_index"] for r in selector.selection_records], [1, 2])
        self.assertEqual([r["task_id"] for r in selector.selection_records], ["opaque-repeat", "opaque-repeat"])
        self.assertEqual(selector.selection_timings_ns, [20, 100])
        self.assertEqual(selector.to_dict(), before)

    def test_roundtrip_does_not_insert_runtime_records_into_frozen_model(self):
        selector = artificial_selector()
        before = selector.to_dict()
        selector.select(TaskInput("opaque", "negative", ("artificial context",)))
        restored = temporal.TemporalSelector.from_dict(selector.to_dict(), encoder=ArtificialEncoder())
        self.assertEqual(restored.selection_records, [])
        self.assertEqual(restored.selection_timings_ns, [])
        self.assertEqual(restored.to_dict(), before)
        self.assertEqual(restored.select(TaskInput("opaque", "negative", ("artificial context",))), 2)
        self.assertEqual(restored.selection_records[0]["selection_index"], 1)
        self.assertEqual(restored.to_dict(), before)

    def test_failed_selection_does_not_fabricate_a_success_record(self):
        selector = artificial_selector()
        before = selector.to_dict()
        with self.assertRaises(ValueError):
            selector.select({"task_id": "not-a-public-input"})
        self.assertEqual(selector.selection_records, [])
        self.assertEqual(selector.selection_timings_ns, [])
        self.assertEqual(selector.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
