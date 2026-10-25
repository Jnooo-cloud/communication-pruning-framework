"""Synthetic family graphs and sentinel labels; never loads real benchmark data."""

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from communication_pruning.data import (TaskMeta, canonical, digest, families, index_file,
                                       load_task, make_manifest, read_manifest, save_manifest,
                                       structure, validate_manifest)
from communication_pruning.configurations import bank
from communication_pruning.execution import execute
from test_core import stub


def raw(task_id="2hop__1_2"):
    return {"id": task_id, "question": "Which container?", "answerable": True,
            "answer": "HIDDEN_ANSWER", "answer_aliases": ["HIDDEN_ALIAS"],
            "question_decomposition": [{"id": 1, "question": "HIDDEN_SUBQUESTION"}, {"id": 2}],
            "paragraphs": [{"idx": 0, "title": "Container", "paragraph_text": "Public evidence.",
                            "is_supporting": True},
                           {"idx": 1, "title": "Second", "paragraph_text": "Another public text.",
                            "is_supporting": False}]}


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"synthetic.jsonl"
        self.path.write_bytes(canonical(raw()) + b"\n")
        self.source_hash = sha256(self.path.read_bytes()).hexdigest()
        self.rows = index_file(self.path, "train", self.source_hash)
        self.family = families(self.rows)[self.rows[0].task_id]

    def manifest(self, **kwargs):
        options = dict(exposed_ids=[], assignments={self.family: "technical"}, seed="test-only",
                       source_hashes={"train": self.source_hash})
        options.update(kwargs)
        return make_manifest(self.rows, **options)

    def test_k1_transitive_family_cross_split_order_invariance(self):
        rows = (TaskMeta("A", "train", 2, ("1", "2")),
                TaskMeta("B", "train", 2, ("2", "3")),
                TaskMeta("C", "dev", 2, ("3", "4")),
                TaskMeta("D", "dev", 2, ("5", "6")))
        result = families(rows)
        self.assertEqual(result, families(reversed(rows)))
        self.assertEqual(result["A"], result["C"])
        self.assertNotEqual(result["A"], result["D"])

    def test_k2_exposure_excludes_whole_family(self):
        rows = (*self.rows, TaskMeta("B", "train", 2, ("2", "3")))
        manifest = make_manifest(rows, exposed_ids=[self.rows[0].task_id], assignments={}, seed="test",
                                 source_hashes={"train": self.source_hash})
        self.assertEqual([e["phase"] for e in manifest["entries"]], ["excluded", "excluded"])
        validate_manifest(manifest)

    def test_k2_unmatched_exposure_and_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(exposed_ids=["missing"])
        with self.assertRaises(ValueError):
            families((*self.rows, *self.rows))
        with self.assertRaises(ValueError):
            self.manifest(exposed_ids=[self.rows[0].task_id])

    def test_k3_train_dev_roles_and_cross_split_family(self):
        with self.assertRaises(ValueError):
            self.manifest(assignments={self.family: "holdout"})
        for split, phase in (("dev", "technical"), ("train", "holdout")):
            rows = [TaskMeta("A", split, 2, ("1", "2"))]
            with self.assertRaises(ValueError):
                make_manifest(rows, exposed_ids=[], assignments={families(rows)["A"]: phase},
                              seed="test", source_hashes={split: self.source_hash})
        rows = [TaskMeta("A", "train", 2, ("1", "2")), TaskMeta("B", "dev", 2, ("2", "3"))]
        with self.assertRaises(ValueError):
            make_manifest(rows, exposed_ids=[], assignments={families(rows)["A"]: "technical"},
                          seed="test", source_hashes={"train": self.source_hash, "dev": self.source_hash})

    def test_k3_mixed_family_tamper_rejected_after_resigning(self):
        rows = (*self.rows, TaskMeta("B", "train", 2, ("2", "3")))
        family = families(rows)["B"]
        result = make_manifest(rows, exposed_ids=[], assignments={family: "spatial"}, seed="test",
                               source_hashes={"train": self.source_hash})
        result["entries"][0]["phase"] = "pilot"
        result["sha256"] = digest({k: v for k, v in result.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            validate_manifest(result)

    def test_k4_manifest_roundtrip_and_change_detection(self):
        manifest = self.manifest()
        target = self.path.with_name("manifest.json")
        save_manifest(target, manifest)
        self.assertEqual(read_manifest(target), manifest)
        self.assertEqual(self.manifest(), manifest)
        with self.assertRaises(FileExistsError):
            save_manifest(target, manifest)
        for key, value in (("seed", "changed"), ("sha256", "0"*64), ("schema", True)):
            changed = deepcopy(manifest)
            changed[key] = value
            with self.assertRaises(ValueError):
                validate_manifest(changed)

    def test_k4_index_hash_and_explicit_sources_required(self):
        with self.assertRaises(ValueError):
            index_file(self.path, "train", "0"*64)
        with self.assertRaises(ValueError):
            self.manifest(source_hashes={})
        with self.assertRaises(ValueError):
            self.manifest(assignments={"missing": "technical"})

    def test_k5_public_input_opaque_id_and_no_annotation_leak(self):
        public, reference = load_task(self.path, self.rows[0].task_id, self.manifest(), phase="technical")
        self.assertEqual(set(asdict(public)), {"task_id", "question", "paragraphs"})
        self.assertEqual(public.paragraphs, ("Container\nPublic evidence.", "Second\nAnother public text."))
        self.assertEqual(reference.answers, ("HIDDEN_ANSWER", "HIDDEN_ALIAS"))
        self.assertEqual(reference.task_id, public.task_id)
        self.assertNotIn("2hop", public.task_id)
        trace = execute(public, bank()[0], stub)
        text = json.dumps(trace)
        for sentinel in ("HIDDEN_ANSWER", "HIDDEN_ALIAS", "HIDDEN_SUBQUESTION", "is_supporting", "question_decomposition"):
            self.assertNotIn(sentinel, text)

    def test_k6_wrong_role_exposure_unused_and_source_rejected(self):
        task_id = self.rows[0].task_id
        for manifest, phase in ((self.manifest(), "pilot"),
                                (self.manifest(assignments={}), "technical"),
                                (self.manifest(assignments={}, exposed_ids=[task_id]), "technical")):
            with self.assertRaises(ValueError):
                load_task(self.path, task_id, manifest, phase=phase)
        manifest = self.manifest()
        self.path.write_bytes(self.path.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            load_task(self.path, task_id, manifest, phase="technical")

    def test_malformed_raw_records_rejected_without_content_errors(self):
        for field, value in (("answerable", False), ("answer_aliases", "HIDDEN_ALIAS"),
                             ("paragraphs", []), ("answer", "")):
            record = raw()
            record[field] = value
            self.path.write_bytes(canonical(record) + b"\n")
            self.source_hash = sha256(self.path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError) as error:
                load_task(self.path, self.rows[0].task_id, self.manifest(), phase="technical")
            self.assertNotIn("HIDDEN", str(error.exception))

    def test_unknown_and_duplicate_subquestions_rejected(self):
        for parts in ((), ("same", "same"), (None,)):
            with self.assertRaises(ValueError):
                TaskMeta("A", "train", 2, parts)
        record = raw()
        record["question_decomposition"][0]["id"] = True
        with self.assertRaises(ValueError):
            structure(record, "train")
