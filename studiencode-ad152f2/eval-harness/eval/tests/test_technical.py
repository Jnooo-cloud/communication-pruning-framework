"""Z07 technical contracts: synthetic metadata and injected transports only."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from communication_pruning.data import TaskMeta, AnswerReference, canonical
from communication_pruning.openrouter import ProbeStop, encoded, ProbeAdapter
from communication_pruning.technical import select_technical, budget_check, exposed_ids, SOURCE_HASHES
from communication_pruning.probe import TASK, audit_provider
from communication_pruning.configurations import bank
from communication_pruning.execution import execute
from communication_pruning.musique_probe import prepared, release, validate_release, run, PREP, LIVE
from test_openrouter import reply, endpoint


def rows():
    return [TaskMeta("2hop__1_2", "train", 2, ("1", "2")),
            TaskMeta("2hop__2_3", "train", 2, ("2", "3")),
            TaskMeta("2hop__4_5", "train", 2, ("4", "5")),
            TaskMeta("4hop1__6_7_8_9", "train", 4, ("6", "7", "8", "9")),
            TaskMeta("2hop__10_11", "train", 2, ("10", "11")),
            TaskMeta("2hop__11_12", "dev", 2, ("11", "12"))]


def prior():
    return {"run_id": "Z06-OPENROUTER-002", "status": "completed", "calls_reserved": 5,
            "source_unchanged": True, "total_cost_usd": "0.0001213",
            "known_cost_subtotal_usd": "0.0001213", "provider_audit": {"cost_usd": "0.0001213"}}


def prepare_fixture(root):
    from hashlib import sha256
    selected, manifest = select_technical(rows(), [], SOURCE_HASHES)
    folder = root / PREP; folder.mkdir(parents=True)
    raw = canonical(manifest); (folder / "manifest.json").write_bytes(raw)
    (root / "project/dsr").mkdir(parents=True)
    receipt = {"manifest_path": f"{PREP}/manifest.json", "manifest_file_sha256": sha256(raw).hexdigest(),
               "manifest_content_sha256": manifest["sha256"], "selected": selected,
               "source_receipt": "source.json", "source_receipt_sha256": "test-only"}
    (root / "project/dsr/Z07-SELECTION.json").write_bytes(encoded(receipt))
    (root / "project/DATENEXPOSITIONSREGISTER.md").write_text("\n".join(f'`{s["task_id"]}`' for s in selected))
    release(root)
    return receipt


class TechnicalTests(unittest.TestCase):
    def test_k1_deterministic_smallest_pure_families(self):
        chosen, m = select_technical(rows(), [], SOURCE_HASHES)
        other, n = select_technical(reversed(rows()), [], SOURCE_HASHES)
        self.assertEqual((chosen, m), (other, n))
        self.assertEqual([c["task_id"] for c in chosen], ["2hop__4_5", "4hop1__6_7_8_9"])
        self.assertEqual(len({c["family_id"] for c in chosen}), 2)
        self.assertTrue(all(e["phase"] == "unused" for e in m["entries"] if e["split"] == "dev"))

    def test_k1_exposure_transitivity_and_no_replacement_if_unavailable(self):
        chosen, m = select_technical(rows(), ["2hop__4_5"], SOURCE_HASHES)
        self.assertEqual(chosen[0]["members"], ["2hop__1_2", "2hop__2_3"])
        self.assertTrue(all(e["phase"] == "technical" for e in m["entries"] if e["task_id"] in chosen[0]["members"]))
        with self.assertRaises(ValueError): select_technical(rows(), ["4hop1__6_7_8_9"], SOURCE_HASHES)
        with self.assertRaises(ValueError): select_technical(rows(), ["missing"], SOURCE_HASHES)
        with self.assertRaises(ValueError): select_technical(rows() + rows()[:1], [], SOURCE_HASHES)

    def test_k2_new_exposure_excludes_entire_reserved_family(self):
        chosen, _ = select_technical(rows(), ["2hop__4_5"], SOURCE_HASHES)
        exclusions = exposed_ids("`2hop__4_5`\n`" + chosen[0]["task_id"] + "`")
        with self.assertRaises(ValueError): select_technical(rows(), exclusions, SOURCE_HASHES)

    def test_k4_combined_budget_unknowns_and_bounds(self):
        self.assertEqual(budget_check(prior())["maximum_combined_usd"], "1.4001213")
        for change in ({"total_cost_usd": None}, {"status": "stopped"}, {"calls_reserved": 6}, {"source_unchanged": False}):
            with self.assertRaises(ProbeStop): budget_check({**prior(), **change})
        p = prior(); p.update(total_cost_usd=".61", known_cost_subtotal_usd=".61"); p["provider_audit"]["cost_usd"] = ".61"
        with self.assertRaises(ProbeStop): budget_check(p)
        with self.assertRaises(ProbeStop): budget_check(prior(), tasks=3)

    def test_k2_prepared_release_tamper_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepare_fixture(root)
            validate_release(root)
            with self.assertRaises(FileExistsError): release(root)
            p = root / "project/DATENEXPOSITIONSREGISTER.md"; p.write_text("changed")
            with self.assertRaises(ProbeStop): validate_release(root)

    def test_k2_manifest_tamper_fails_before_content_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepare_fixture(root)
            p = root / PREP / "manifest.json"; p.write_text("{}")
            with self.assertRaises(ProbeStop): prepared(root)

    def test_k3_provider_audit_binds_the_specific_public_task(self):
        task = replace(TASK, task_id="another", question="A different public question?")
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def transport(*args):
                calls.append(1); return 200, encoded(reply(len(calls)))
            trace = execute(task, bank()[0], ProbeAdapter(tmp, transport))
            audit_provider(tmp, trace, task=task)
            with self.assertRaises(ProbeStop): audit_provider(tmp, trace)
            changed = deepcopy(trace); changed["task"]["question"] = "tampered"
            with self.assertRaises(ProbeStop): audit_provider(tmp, changed, task=task)

    def integration(self, fail_at=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepare_fixture(root)
            sent, loaded = [], []
            def transport(endpoint_name, body=None):
                if endpoint_name == "key": return 200, encoded({"data": {"is_free_tier": False, "limit_remaining": None}})
                if endpoint_name.startswith("models/"): return 200, encoded(endpoint())
                sent.append(json.loads(body))
                if fail_at == len(sent): raise TimeoutError("private provider string")
                return 200, encoded(reply(len(sent)))
            def loader(path, task_id, manifest, *, phase):
                self.assertEqual(phase, "technical"); loaded.append(task_id)
                task = replace(TASK, task_id=f"synthetic-{len(loaded)}")
                return task, AnswerReference(task.task_id, ("Linden",))
            with patch("communication_pruning.musique_probe.verify_sources", return_value="test-only"), \
                 patch("communication_pruning.musique_probe.verify_prior", return_value=budget_check(prior())), \
                 patch("communication_pruning.musique_probe.load_key", return_value="test-only-key"), \
                 patch("communication_pruning.musique_probe.Transport", return_value=transport), \
                 patch("communication_pruning.musique_probe.load_task", side_effect=loader):
                status = run(root)
                with self.assertRaises(FileExistsError): run(root)
            r = json.loads((root / "project/dsr/Z07-LIVE-001.json").read_text())
            if fail_at:
                self.assertEqual(status, 1); self.assertEqual(len(sent), fail_at)
                self.assertEqual(len(loaded), 1); self.assertIsNone(r["total_cost_usd"])
                self.assertNotIn("private provider string", json.dumps(r))
            else:
                self.assertEqual(status, 0); self.assertEqual(len(sent), 10); self.assertEqual(len(loaded), 2)
                self.assertEqual(r["total_cost_usd"], "0.0001080")
                self.assertEqual(r["combined_technical_cost_usd"], "0.0002293")
                for body in sent:
                    self.assertEqual(set(json.loads(body["messages"][1]["content"])), {"question", "paragraphs", "prior_messages"})

    def test_k6_full_synthetic_two_task_path(self):
        self.integration()

    def test_k4_failed_first_task_prevents_loading_or_calling_second(self):
        self.integration(fail_at=2)
