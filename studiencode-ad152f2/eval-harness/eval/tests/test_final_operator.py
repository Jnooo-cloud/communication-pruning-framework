"""Artificial N1/N3/N7 checks for the concrete successor, never live clients.

The coordinator archives this source before running the tests. Fixtures retain
their evidence under Z50_TEST_EVIDENCE_DIR; deliberately changed artificial files
have their unchanged originals saved outside the study inventory first.
"""
from copy import deepcopy
from pathlib import Path
from shutil import copyfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study import file_hash
from study_preparation import final_execution as execution, final_preflight as gate
from study_preparation import final_operator as operator
from study_preparation import final_resources as resources
from study_preparation.final_resources import validate_observation
from tests.test_final_preflight import Fixture, trial_directory


class OperatorFixture(Fixture):
    """Same synthetic execution fixture, with the actual Session checkpoint."""

    def __init__(self, root, **kwargs):
        super().__init__(root, **kwargs)
        self.operation = self.root / "operation"
        self.candidate["operator"] = {"output_directory": str(self.folder),
                                      "operation_directory": str(self.operation)}
        self.candidate_path = self.root / "ARTIFICIAL-OPERATOR.json"
        self.candidate_path.write_bytes(encoded(gate.seal(self.candidate)))
        self.session = operator.Session(self.candidate_path)
        self.checkpoint = self.session.checkpoint
        self.bind()
        self.candidate_path.write_bytes(encoded(self.candidate))
        self.session.candidate = self.candidate

    def run_session(self, end):
        # The real live initialize method rejects artificial rights. Replace
        # only that entry and its dependencies with explicitly synthetic ones.
        self.session.loader = self.loader
        self.session.transport = self.transport
        self.session.spatial = SimpleNamespace(select=self.spatial_selector)
        self.session.temporal = SimpleNamespace(select=self.temporal_selector)
        with patch.object(self.session, "initialize", return_value=None), \
                patch.object(operator.time, "time", self.clock):
            return self.session.run(end)


class FinalOperatorTests(unittest.TestCase):
    def assert_resource_backup(self, session):
        evidence = session.last_resource_evidence
        self.assertIsNotNone(evidence)
        self.assertEqual(file_hash(evidence["path"]), evidence["sha256"])
        backup = gate.read_json(evidence["path"])["backup"]
        self.assertEqual(backup, evidence["backup"])
        gate.verify_archive(backup, backup["members"])
        self.assertEqual(set(backup["members"]), {"RESOURCE.json", "MANIFEST.json"})
        with ZipFile(backup["path"]) as archive:
            record = execution.read_json_bytes(archive.read("RESOURCE.json"))
            manifest = execution.read_json_bytes(archive.read("MANIFEST.json"))
        self.assertEqual(manifest["archive_path"], backup["path"])
        self.assertEqual(manifest["files"], {"RESOURCE.json": backup["members"]["RESOURCE.json"]})
        self.assertEqual(manifest["run_id"], record["run_id"])
        self.assertEqual(manifest["session_id"], record["session_id"])
        validate_observation(record["process_observation"], require_complete=False)
        self.assertNotIn("PRIVATE_FAKE_GOLD", str(record))
        self.assertNotIn("Invented question", str(record))
        return record

    def test_real_callback_recovers_orphan_zip_after_receipt_write_failure(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory, counts={"P": 2, "R": 1, "T": 1, "F": 1})
            original_save = execution._save

            def fail_receipt(path, value):
                if Path(path).parent.name == "receipts":
                    raise OSError("invented interruption after archive verification")
                return original_save(path, value)

            with patch.object(execution, "_save", side_effect=fail_receipt):
                with self.assertRaisesRegex(OSError, "invented interruption"):
                    f.run(1)
            state = execution.inspect_study(f.candidate, f.plan, **f.args())
            archive = f.folder / "receipts" / (state["state_sha256"] + ".zip")
            before_hash, before_mtime = file_hash(archive), archive.stat().st_mtime_ns
            before_calls = f.transport.calls
            self.assertFalse(execution._receipt_path(f.folder, state).exists())
            repaired = execution.checkpoint_study(f.candidate, f.plan, **f.args(), checkpoint=f.checkpoint)
            self.assertEqual(repaired, state)
            self.assertEqual(f.transport.calls, before_calls)
            self.assertEqual((file_hash(archive), archive.stat().st_mtime_ns), (before_hash, before_mtime))
            execution._verify_receipt(f.folder, state)
            next_state = f.run(2)
            self.assertEqual(next_state["completed_blocks"], 2)
            self.assertTrue(set(state["generation_ids"]) < set(next_state["generation_ids"]))

    def test_lost_receipt_and_repeated_checkpoint_preserve_zip_and_call_count(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            state = f.run(1)
            receipt = execution._receipt_path(f.folder, state)
            backup = gate.read_json(receipt)["backup"]
            archive = Path(backup["path"])
            stable = (file_hash(archive), archive.stat().st_mtime_ns, f.transport.calls)
            copyfile(receipt, f.root / "preserved-lost-receipt.json")
            receipt.unlink()  # Deliberate artificial loss; original is preserved.
            for _ in range(2):
                current = execution.checkpoint_study(f.candidate, f.plan, **f.args(), checkpoint=f.checkpoint)
                self.assertEqual(current, state)
                self.assertEqual((file_hash(archive), archive.stat().st_mtime_ns, f.transport.calls), stable)
                execution._verify_receipt(f.folder, state)
            # Exercise repeated direct invocation as well as the core's valid
            # receipt early return: the callback itself must be idempotent.
            self.assertEqual(f.session.checkpoint(deepcopy(state)), backup)
            self.assertEqual(f.session.checkpoint(deepcopy(state)), backup)
            self.assertEqual((file_hash(archive), archive.stat().st_mtime_ns, f.transport.calls), stable)

    def test_damaged_or_wrong_member_zip_stops_without_replacing_it(self):
        for kind in ("damaged", "wrong_members"):
            with self.subTest(kind=kind), trial_directory() as directory:
                f = OperatorFixture(directory)
                state = f.run(1)
                archive = f.folder / "receipts" / (state["state_sha256"] + ".zip")
                copyfile(archive, f.root / "preserved-valid-checkpoint.zip")
                if kind == "damaged":
                    archive.write_bytes(b"deliberately broken artificial archive")
                else:
                    with ZipFile(archive, "w") as changed:
                        changed.writestr("foreign.txt", "unrelated artificial evidence")
                changed_hash, calls = file_hash(archive), f.transport.calls
                with self.assertRaises(gate.StudyStop):
                    f.session.checkpoint(deepcopy(state))
                self.assertEqual(file_hash(archive), changed_hash)
                self.assertEqual(f.transport.calls, calls)

    def test_invalid_receipt_stops_before_callback_and_does_not_replace_archive(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            state = f.run(1)
            receipt = execution._receipt_path(f.folder, state)
            saved = gate.read_json(receipt)
            archive = Path(saved["backup"]["path"])
            copyfile(receipt, f.root / "preserved-valid-receipt.json")
            saved["backup"]["sha256"] = "0" * 64
            receipt.write_bytes(encoded(saved))
            checksum, calls = file_hash(archive), f.transport.calls
            with patch.object(f.session, "checkpoint", side_effect=AssertionError("bad receipt must not invoke callback")):
                with self.assertRaises(gate.StudyStop):
                    execution.checkpoint_study(f.candidate, f.plan, **f.args(), checkpoint=f.session.checkpoint)
            self.assertEqual(file_hash(archive), checksum)
            self.assertEqual(f.transport.calls, calls)
            self.assertEqual(gate.read_json(receipt), saved)

    def test_changed_evidence_or_state_identity_cannot_reuse_checkpoint(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            state = f.run(1)
            changed = deepcopy(state)
            changed["completed_blocks"] += 1
            with self.assertRaisesRegex(gate.StudyStop, "state identity"):
                f.session.checkpoint(changed)
            selection = f.folder / "blocks" / "000000" / "selection.json"
            copyfile(selection, f.root / "preserved-selection.json")
            selection.write_bytes(selection.read_bytes() + b" ")
            calls = f.transport.calls
            with self.assertRaisesRegex(gate.StudyStop, "evidence changed"):
                f.session.checkpoint(deepcopy(state))
            with self.assertRaises(gate.StudyStop):
                execution.checkpoint_study(f.candidate, f.plan, **f.args(), checkpoint=f.checkpoint)
            self.assertEqual(f.transport.calls, calls)

    def test_partial_block_has_no_checkpoint_or_hidden_retry(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            f.transport.fail_at, f.transport.mode = 2, "transport"
            with self.assertRaises(BudgetStop):
                f.run(1)
            calls = f.transport.calls
            # Ledger replay rejects the prior failed settlement before block
            # inspection; this established BudgetStop is the intended guard.
            with self.assertRaisesRegex(BudgetStop, "^failed or unresolved prior settlement$"):
                execution.checkpoint_study(f.candidate, f.plan, **f.args(), checkpoint=f.checkpoint)
            self.assertEqual(f.transport.calls, calls)
            self.assertEqual(list((f.folder / "receipts").glob("*.zip")), [])

    def test_session_process_evidence_is_saved_across_fresh_sessions(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory, counts={"P": 2, "R": 1, "T": 1, "F": 1})
            first = f.run_session(1)
            record = self.assert_resource_backup(f.session)
            proof = deepcopy(f.session.last_resource_evidence)
            validate_observation(record["process_observation"])
            self.assertEqual(record["outcome"], "returned")
            self.assertEqual(record["state_sha256"], first["state_sha256"])
            self.assertEqual(record["checkpoint"]["state_sha256"], first["state_sha256"])
            self.assertEqual(record["encoder_initialization_status"], "not_initialized")
            self.assertIsNone(record["encoder_initialization_ns"])
            f.session = operator.Session(f.candidate_path)
            f.checkpoint = f.session.checkpoint
            second = f.run_session(2)
            later = self.assert_resource_backup(f.session)
            self.assertNotEqual(later["session_id"], record["session_id"])
            self.assertNotEqual(later["run_id"], record["run_id"])
            self.assertEqual(later["state_sha256"], second["state_sha256"])
            self.assertEqual(file_hash(proof["path"]), proof["sha256"])
            gate.verify_archive(proof["backup"], proof["backup"]["members"])

    def test_session_process_evidence_survives_real_artificial_execution_failure(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            f.transport.fail_at, f.transport.mode = 2, "transport"
            with self.assertRaises(BudgetStop):
                f.run_session(1)
            record = self.assert_resource_backup(f.session)
            validate_observation(record["process_observation"])
            self.assertEqual(record["outcome"], "raised")
            self.assertEqual(record["error_type"], "BudgetStop")
            self.assertIsNone(record["state_sha256"])
            self.assertIsNone(record["checkpoint"])
            self.assertEqual(f.transport.calls, 2)
            with self.assertRaisesRegex(BudgetStop, "^failed or unresolved prior settlement$"):
                f.run_session(1)
            self.assertEqual(f.transport.calls, 2)

    def test_unauthorized_session_cannot_initialize_live_clients_but_records_failure(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            session = f.session
            with patch.object(operator, "FrozenMiniLM", side_effect=AssertionError("real encoder")), \
                    patch.object(operator, "load_key", side_effect=AssertionError("real key")), \
                    patch.object(operator, "Transport", side_effect=AssertionError("real transport")), \
                    patch.object(operator, "load_task", side_effect=AssertionError("real data")):
                with self.assertRaisesRegex(gate.StudyStop, "actual author release"):
                    session.run(1)
                for call in (lambda: session.transport("chat/completions", b"{}"),
                             lambda: session.loader("synthetic-one")):
                    with self.assertRaises(gate.StudyStop):
                        call()
            record = self.assert_resource_backup(session)
            self.assertEqual(record["outcome"], "raised")
            self.assertEqual(record["error_type"], "StudyStop")
            self.assertEqual(record["encoder_initialization_status"], "not_initialized")
            self.assertIsNone(record["encoder_initialization_ns"])
            self.assertEqual(f.transport.calls, 0)
            self.assertFalse(session._ready)

    def test_encoder_initialization_is_counted_once_across_two_session_runs(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            f.session.settings["provision_manifest"] = f.file("fake-provision.json", {
                "model_dir_relative": "no-model", "files": {}, "runtime": {}})
            fake_encoder = SimpleNamespace(initialization_ns=731)
            with patch.object(f.session, "metadata_gate", return_value={}), \
                    patch.object(operator, "FrozenMiniLM", return_value=fake_encoder) as constructor, \
                    patch.object(operator.SemanticSelector, "from_dict", return_value=SimpleNamespace(select=f.spatial_selector)), \
                    patch.object(operator.TemporalSelector, "from_dict", return_value=SimpleNamespace(select=f.temporal_selector)), \
                    patch.object(execution, "run_section", return_value={"state_sha256": "a" * 64}), \
                    patch.object(operator, "load_key", side_effect=AssertionError("no credentials")):
                f.session.run(1)
                first = self.assert_resource_backup(f.session)
                f.session.run(2)
                second = self.assert_resource_backup(f.session)
            constructor.assert_called_once()
            self.assertEqual(first["encoder_initialization_status"], "initialized_this_run")
            self.assertEqual(first["encoder_initialization_ns"], 731)
            self.assertEqual(second["encoder_initialization_status"], "reused")
            self.assertIsNone(second["encoder_initialization_ns"])
            self.assertEqual(first["session_id"], second["session_id"])
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertEqual(f.transport.calls, 0)

    def test_completed_fake_encoder_initialization_survives_later_selector_failure(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            f.session.settings["provision_manifest"] = f.file("fake-provision.json", {
                "model_dir_relative": "no-model", "files": {}, "runtime": {}})
            with patch.object(f.session, "metadata_gate", return_value={}), \
                    patch.object(operator, "FrozenMiniLM", return_value=SimpleNamespace(initialization_ns=947)), \
                    patch.object(operator.SemanticSelector, "from_dict", side_effect=ValueError("invented selector failure")), \
                    patch.object(operator, "load_key", side_effect=AssertionError("no credentials")):
                with self.assertRaisesRegex(ValueError, "invented selector failure"):
                    f.session.run(1)
            record = self.assert_resource_backup(f.session)
            self.assertEqual(record["outcome"], "raised")
            self.assertEqual(record["encoder_initialization_status"], "initialized_this_run")
            self.assertEqual(record["encoder_initialization_ns"], 947)
            self.assertIsNone(f.session.encoder)
            self.assertFalse(f.session._ready)
            self.assertEqual(f.transport.calls, 0)

    def test_resource_backup_failure_does_not_replace_original_exception(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            original = RuntimeError("invented initialization failure")
            with patch.object(f.session, "initialize", side_effect=original), \
                    patch.object(f.session, "_save_resource_record", side_effect=OSError("invented disk failure")):
                with self.assertRaises(RuntimeError) as caught:
                    f.session.run(1)
            self.assertIs(caught.exception, original)
            self.assertTrue(any("OSError" in note for note in caught.exception.__notes__))
            self.assertEqual(f.transport.calls, 0)
            self.assertIsNone(f.session.last_resource_evidence)

    def test_incomplete_process_measurement_is_saved_and_stops_successful_return(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            with patch.object(resources, "_maxrss", side_effect=OSError("invented unavailable RSS")):
                unavailable = resources.ProcessObservation().finish()
            observation = SimpleNamespace(finish=lambda: deepcopy(unavailable))
            f.session.spatial = SimpleNamespace(select=f.spatial_selector)
            f.session.temporal = SimpleNamespace(select=f.temporal_selector)
            with patch.object(operator, "ProcessObservation", return_value=observation), \
                    patch.object(f.session, "initialize", return_value=None), \
                    patch.object(execution, "run_section", return_value={"state_sha256": "a" * 64}):
                with self.assertRaisesRegex(gate.StudyStop, "measurement is incomplete"):
                    f.session.run(1)
            record = self.assert_resource_backup(f.session)
            measured = record["process_observation"]
            self.assertEqual(measured["observation_status"], "incomplete")
            self.assertIsNone(measured["peak_rss_end_bytes"])
            self.assertNotEqual(measured["errors"], {})
            with self.assertRaises(ValueError):
                validate_observation(measured)
            self.assertEqual(f.transport.calls, 0)


if __name__ == "__main__":
    unittest.main()
