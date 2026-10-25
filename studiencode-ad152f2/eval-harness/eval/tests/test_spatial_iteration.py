"""Z38: invented inputs and transports only; retain cases when requested."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from communication_pruning.data import digest
from communication_pruning.failure_policy import F01
from communication_pruning.openrouter import MODEL, PROVIDER, encoded
from communication_pruning.spatial_plan import (ITERATION_ID, ITERATION_EVIDENCE,
    make_iteration_contract, make_iteration_plan, iteration_bindings, validate_plan,
    validate_iteration_contract)
from communication_pruning.study import run_spatial, file_hash, FileGuard, StudyStop
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study_resume import inspect_spatial, phase_lock
from communication_pruning.study_release import iteration_candidate, run_iteration_live
from study_fixture import fixture, FakeTransport


def resign(value):
    value = deepcopy(value)
    value.pop("sha256", None)
    return dict(value, sha256=digest(value))


class SpatialIterationTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get("Z38_ITERATION_TEST_ROOT")
        if retained:
            self.root = Path(retained) / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=False)
        else:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.root = Path(tmp.name)
        self.kw = fixture(self.root / "inputs")
        self.legacy = self.kw["plan"]
        evidence = {name: {"path": f"metadata/{name}.json", "sha256": "1" * 64}
                    for name in ITERATION_EVIDENCE}
        self.contract = make_iteration_contract(evidence, legacy_plan_sha256=self.legacy["sha256"])
        self.plan = make_iteration_plan(self.kw["manifest"], self.kw["task_ids"], self.kw["repeats"],
                                        contract=self.contract, legacy_plan=self.legacy)
        self.args = {**self.kw, "plan": self.plan, "bindings": iteration_bindings(self.contract),
                     "iteration_contract": self.contract, "failure_policy": F01,
                     "folder": self.root / "out", "control": self.root / "control", "synthetic": True}

    def inspect(self, **updates):
        args = {**self.args, **updates}
        return inspect_spatial(**args)

    def changed(self):
        evidence = deepcopy(self.contract["evidence"])
        evidence["prompt"]["sha256"] = "2" * 64
        contract = make_iteration_contract(evidence, legacy_plan_sha256=self.legacy["sha256"])
        plan = make_iteration_plan(self.kw["manifest"], self.kw["task_ids"], self.kw["repeats"],
                                    contract=contract, legacy_plan=self.legacy)
        return {"plan": plan, "iteration_contract": contract, "bindings": iteration_bindings(contract)}

    def test_preserves_entire_z19_order_folds_curves_and_new_fixed_cap(self):
        for key in ("slots", "configurations", "task_ids", "repeat_ids", "folds", "learning_curves",
                    "seed", "cv_seed", "summary", "manifest_sha256"):
            self.assertEqual(self.plan[key], self.legacy[key], key)
        self.assertEqual(self.plan["summary"]["runs"], 4900)
        self.assertEqual(self.plan["summary"]["model_calls_without_retry"], 30100)
        self.assertEqual(self.legacy["proposed_phase_cap_usd"], "36.12")
        self.assertEqual(self.plan["proposed_phase_cap_usd"], "12.00")
        self.assertEqual(self.contract["retry_policy"], "none")
        validate_plan(self.plan, self.kw["manifest"], self.kw["task_ids"], self.kw["repeats"],
                      bindings=self.args["bindings"], iteration_contract=self.contract)
        for field, value in (("phase_cap_usd", "36.12"), ("reservation_usd", "0.01"),
                             ("retry_policy", "Z26-resume"), ("iteration_id", "other")):
            modified = deepcopy(self.contract)
            modified[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_iteration_contract(resign(modified))
        modified = deepcopy(self.plan)
        modified["proposed_phase_cap_usd"] = "36.12"
        with self.assertRaises(ValueError):
            run_spatial(**{**self.args, "plan": resign(modified)}, transport=FakeTransport(), slot_limit=1)
        with self.assertRaises(ValueError):
            run_spatial(**{**self.args, "iteration_contract": None}, transport=FakeTransport(), slot_limit=1)
        with self.assertRaises(StudyStop):
            run_spatial(**{**self.args, "failure_policy": None}, transport=FakeTransport(), slot_limit=1)

    def test_same_iteration_changed_plan_cannot_restart_resume_or_bypass_lock(self):
        first = run_spatial(**self.args, transport=FakeTransport(), slot_limit=1)
        state = self.inspect()
        claim_path = self.args["control"] / f"{ITERATION_ID}.claim.json"
        claim_bytes = claim_path.read_bytes()
        claim = json.loads(claim_bytes)
        self.assertEqual(claim["iteration_contract_sha256"], self.contract["sha256"])
        changed = self.changed()
        self.assertNotEqual(changed["plan"]["sha256"], self.plan["sha256"])
        for update in ({}, changed):
            transport = FakeTransport()
            with self.subTest(change=bool(update)), self.assertRaises(FileExistsError):
                run_spatial(**{**self.args, **update, "folder": self.root / "other"},
                            transport=transport, slot_limit=2)
            self.assertEqual(transport.calls, 0)
        for folder in (self.args["folder"], self.root / "other"):
            with self.subTest(folder=str(folder)), self.assertRaises(StudyStop):
                self.inspect(**changed, folder=folder)
            with self.subTest(resume_folder=str(folder)), self.assertRaises(StudyStop):
                run_spatial(**{**self.args, **changed, "folder": folder},
                            transport=FakeTransport(), slot_limit=2, resume_from=state["resume_token"])
        with phase_lock(self.args["control"], self.plan):
            with self.assertRaises(StudyStop):
                run_spatial(**{**self.args, **changed}, transport=FakeTransport(), slot_limit=2,
                            resume_from=state["resume_token"])
        self.assertEqual(claim_path.read_bytes(), claim_bytes)
        self.assertEqual(json.loads((self.args["folder"] / "report.json").read_bytes())["budget"], first["budget"])
        self.assertFalse((self.root / "other").exists())

    def test_complete_prefix_resume_preserves_costs_and_legacy_claim(self):
        self.args["control"].mkdir()
        legacy_claim = self.args["control"] / f"{self.legacy['sha256']}.claim.json"
        legacy_claim.write_bytes(b"preserved historical claim\n")
        first = run_spatial(**self.args, transport=FakeTransport(), slot_limit=1)
        state = self.inspect()
        before = {p: p.read_bytes() for p in self.args["folder"].rglob("*") if p.is_file()}
        transport = FakeTransport()
        transport.calls = first["budget"]["calls"]
        second = run_spatial(**self.args, transport=transport, slot_limit=2, resume_from=state["resume_token"])
        total_calls = sum(s["planned_calls"] for s in self.plan["slots"][:2])
        self.assertEqual(second["budget"]["calls"], total_calls)
        self.assertEqual(Decimal(second["budget"]["known_cost_usd"]), total_calls * Decimal("0.0000108"))
        header = json.loads((self.args["folder"] / "budget.jsonl").read_bytes().splitlines()[0])
        self.assertEqual(header["cap_usd"], "12.00")
        self.assertEqual(legacy_claim.read_bytes(), b"preserved historical claim\n")
        for path, value in before.items():
            if path.name == "budget.jsonl":
                self.assertTrue(path.read_bytes().startswith(value))
            else:
                self.assertEqual(path.read_bytes(), value)
        with self.assertRaises(StudyStop):
            run_spatial(**self.args, transport=FakeTransport(), slot_limit=3, resume_from=state["resume_token"])

    def test_budget_stops_before_uncovered_transport_and_never_resets(self):
        class AtReservation(FakeTransport):
            def __call__(self, endpoint, body=None):
                status, raw = super().__call__(endpoint, body)
                if endpoint == "chat/completions":
                    reply = json.loads(raw)
                    reply["usage"]["cost"] = "0.14"  # deliberately maximal artificial reservation cost
                    raw = encoded(reply)
                return status, raw
        transport = AtReservation()
        with self.assertRaises(BudgetStop):
            run_spatial(**self.args, transport=transport, slot_limit=20)
        report = json.loads((self.args["folder"] / "report.json").read_bytes())
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(transport.calls, 85)
        self.assertEqual(Decimal(report["budget"]["known_cost_usd"]), Decimal("11.90"))
        header = json.loads((self.args["folder"] / "budget.jsonl").read_bytes().splitlines()[0])
        self.assertEqual(header["cap_usd"], "12.00")
        self.assertLessEqual(Decimal(report["budget"]["known_cost_usd"]), Decimal("12"))
        with self.assertRaises(FileExistsError):
            run_spatial(**{**self.args, "folder": self.root / "again"}, transport=FakeTransport(), slot_limit=1)
        with self.assertRaises(StudyStop):
            self.inspect()

    def test_http_failure_is_one_attempt_no_inherited_retry(self):
        transport = FakeTransport(fail_at=1, mode="http")
        with self.assertRaises(BudgetStop):
            run_spatial(**self.args, transport=transport, slot_limit=1)
        self.assertEqual(transport.calls, 1)
        with self.assertRaises(BudgetStop):
            self.inspect()

    def test_complete_artificial_14_configuration_block_reaches_aggregation(self):
        from communication_pruning.configurations import bank
        from communication_pruning.data import load_task
        from communication_pruning.evaluation import PlannedTask, read_result, development_observations
        transport = FakeTransport()
        report = run_spatial(**self.args, transport=transport, slot_limit=14)
        self.assertEqual(report["completed_slots"], 14)
        self.assertEqual(self.inspect()["completed_slots"], 14)
        slots = self.plan["slots"][:14]
        task, reference = load_task(self.kw["source_path"], slots[0]["task_id"], self.kw["manifest"], phase="spatial")
        configs = {c.config_id: c for c in bank()}
        results = [read_result(self.args["folder"] / "slots" / f"{s['slot_id']}.jsonl",
                              configs[s["config_id"]], task, reference,
                              family_id=s["family_id"], phase="spatial", repeat=1) for s in slots]
        aggregated = development_observations(results, [PlannedTask(task, slots[0]["family_id"], "spatial", (1,))])
        self.assertEqual(aggregated["task_count"], 1)
        self.assertEqual(aggregated["executed_runs"], 14)
        self.assertEqual(len(aggregated["observations"][0].quality), 14)
        self.assertEqual(aggregated["executed_cost_usd"], Decimal(report["budget"]["known_cost_usd"]))
        self.assertEqual(transport.calls, 86)
        for body in transport.bodies:
            text = json.dumps(body)
            self.assertNotIn("PRIVATE_REFERENCE_NEVER_SEND", text)
            self.assertNotIn("PRIVATE_ALIAS_NEVER_SEND", text)
        (self.root / "integration-summary.json").write_bytes(encoded({
            "synthetic_only": True, "terminal_slots": 14, "configurations": 14,
            "calls": transport.calls, "executed_cost_usd": str(aggregated["executed_cost_usd"]),
            "no_semantic_fit_claim": True}))

    def candidate_fixture(self):
        root = self.root / "candidate"
        root.mkdir()
        evidence_dir = root / "metadata"
        evidence_dir.mkdir()
        files = {}
        def put(role, value, filename=None):
            path = evidence_dir / (filename or f"{role}.json")
            path.write_bytes(encoded(value))
            files[role] = {"path": str(path.relative_to(root)), "sha256": file_hash(path)}
            return path
        put("manifest", self.kw["manifest"])
        put("allocation", {"panels": {"spatial": self.kw["task_ids"]}})
        put("repetition", {"task_ids": self.kw["repeats"]})
        # Bind actual metadata file hashes in a newly reproducible synthetic legacy plan.
        from communication_pruning.spatial_plan import make_plan
        legacy = make_plan(self.kw["manifest"], self.kw["task_ids"], self.kw["repeats"], bindings={
            "source": "a" * 64, "allocation": files["allocation"]["sha256"],
            "repetition": files["repetition"]["sha256"]})
        put("ordering", legacy)
        put("data_binding", {"files": {name: files[role] for role, name in (
            ("manifest", "manifest.json"), ("allocation", "allocation.json"),
            ("repetition", "spatial-repeat.json"))}, "exposure_register_sha256": "0" * 64})
        put("design", {"fixture": "invented design identity"})
        register = put("register", {"fixture": "current synthetic exposure register"})
        prior = put("prior", {"fixture": "synthetic prior exposure"})
        put("exposure", {"schema": "spatial-exposure-clearance/v1", "iteration_id": ITERATION_ID,
            "stage": "pre_execution", "task_ids": self.kw["task_ids"], "repeat_ids": self.kw["repeats"],
            "register": files.pop("register"), "prior_exposure": [files.pop("prior")],
            "allowed_fields": ["question", "paragraphs"], "references": "scoring_only", "no_other_panels": True})
        catalog = json.loads(FakeTransport()("models/google/gemini-2.5-flash-lite/endpoints")[1])
        put("provider_catalog", catalog)
        put("tariff", {"schema": "spatial-tariff/v1", "model": MODEL, "provider": PROVIDER, "currency": "USD",
            "catalog_sha256": files["provider_catalog"]["sha256"], "pricing": catalog["data"]["endpoints"][0]["pricing"],
            "retrieved_utc": "2026-09-13T00:00:00Z"})
        original = Path(__file__).resolve().parents[1]
        copied = root / "eval-harness/eval"
        for folder in ("communication_pruning", "tests"):
            (copied / folder).mkdir(parents=True)
            for path in (original / folder).glob("*.py"):
                shutil.copyfile(path, copied / folder / path.name)
        # This test checks source binding, never initializes the semantic model.
        semantic = copied / "communication_pruning/semantic_selection.py"
        if not semantic.exists():
            semantic.write_text('"""Synthetic source-manifest placeholder; not executed."""\n')
        source_map = {str(p.relative_to(root)): file_hash(p) for folder in ("communication_pruning", "tests")
                      for p in (copied / folder).glob("*.py")}
        put("source_manifest", source_map)
        source_zip = evidence_dir / "source.zip"
        with ZipFile(source_zip, "x") as archive:
            for name in sorted(source_map):
                archive.write(root / name, name)
        files["source"] = {"path": str(source_zip.relative_to(root)), "sha256": file_hash(source_zip)}
        put("prompt", {"schema": "spatial-prompt/v1", "correction": "Z30", "administrative_message_ids_in_model_input": False,
            "files": {"eval-harness/eval/communication_pruning/" + name: source_map["eval-harness/eval/communication_pruning/" + name]
                      for name in ("openrouter.py", "execution.py", "configurations.py", "contracts.py")}})
        contract = make_iteration_contract(files, legacy_plan_sha256=legacy["sha256"])
        contract_path = root / "contract.json"
        contract_path.write_bytes(encoded(contract))
        return root, contract_path

    def test_current_candidate_is_metadata_only_and_never_authorizes(self):
        root, contract_path = self.candidate_fixture()
        with patch("communication_pruning.study.load_task", side_effect=AssertionError("data")), \
             patch("communication_pruning.study_release.load_key", side_effect=AssertionError("key")), \
             patch("communication_pruning.study_release.Transport", side_effect=AssertionError("client")):
            candidate = iteration_candidate(root, contract_path)
            self.assertEqual(candidate["status"], "prepared_not_authorized")
            self.assertEqual(candidate["phase_cap_usd"], "12.00")
            self.assertEqual(candidate["iteration_id"], ITERATION_ID)
            release_path = root / "release.json"
            release_path.write_bytes(encoded(candidate))
            with self.assertRaises(StudyStop):
                run_iteration_live(root, contract_path, release_path, root / "out")
        exposure = json.loads((root / "metadata/exposure.json").read_bytes())
        changed_file = root / exposure["register"]["path"]
        changed_file.write_text("changed current register\n")
        with self.assertRaises(StudyStop):
            iteration_candidate(root, contract_path)

    def test_release_checks_before_even_contract_and_old_authorization_rejected(self):
        release_path = self.root / "unreleased.json"
        for release in ({"status": "prepared_not_authorized"},
                        {"schema": "spatial-release/v1", "status": "authorized_by_author",
                         "author_decision": "D-053", "backup_evidence": {}}):
            release_path.write_bytes(encoded(release))
            with patch("communication_pruning.study_release._iteration_metadata", side_effect=AssertionError("metadata")), \
                 patch("communication_pruning.study_release.load_key", side_effect=AssertionError("key")), \
                 patch("communication_pruning.study_release.Transport", side_effect=AssertionError("client")):
                with self.assertRaises(StudyStop):
                    run_iteration_live(self.root, self.root / "missing-contract.json", release_path, self.root / "out")

    def test_altered_new_release_cap_and_backup_block_before_runner(self):
        root, contract_path = self.candidate_fixture()
        candidate = iteration_candidate(root, contract_path)
        backup_path = root / "backup-receipt.json"
        backup_path.write_bytes(b"invented local receipt\n")
        backup = {"path": str(backup_path), "sha256": file_hash(backup_path), "location_kind": "local",
                  "location_description": "synthetic local copy", "author_decision": "SYNTHETIC-Z38-ONLY"}
        release = {**candidate, "status": "authorized_by_author", "author_decision": "SYNTHETIC-Z38-ONLY", "backup_evidence": backup}
        release_path = root / "release.json"
        for variant in ({**release, "phase_cap_usd": "36.12"},
                        {**release, "backup_evidence": {**backup, "author_decision": "D-053"}}):
            release_path.write_bytes(encoded(variant))
            with patch("communication_pruning.study_release.load_key", side_effect=AssertionError("key")), \
                 patch("communication_pruning.study_release.Transport", side_effect=AssertionError("client")), \
                 patch("communication_pruning.study_release.run_spatial", side_effect=AssertionError("runner")):
                with self.assertRaises(StudyStop):
                    run_iteration_live(root, contract_path, release_path, root / "out")
        release_path.write_bytes(encoded(release))
        with patch("communication_pruning.study_release.load_key", side_effect=AssertionError("key")), \
             patch("communication_pruning.study_release.Transport", side_effect=AssertionError("client")), \
             patch("communication_pruning.study_release.run_spatial", return_value={"fake": True}) as runner:
            run_iteration_live(root, contract_path, release_path, root / "out")
            self.assertEqual(runner.call_args.kwargs["iteration_contract"]["phase_cap_usd"], "12.00")
            self.assertEqual(runner.call_args.kwargs["failure_policy"], F01)
            self.assertFalse(runner.call_args.kwargs["synthetic"])


if __name__ == "__main__":
    unittest.main()
