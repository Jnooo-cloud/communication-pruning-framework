"""Metadata boundary tests for the concrete original-Session integration."""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

from communication_pruning.study import file_hash
from study_preparation import final_secondary as secondary
import unittest

from study_preparation import final_secondary_operator as operator, final_preflight as gate
from study_preparation.final_operator import Session as OriginalSession
from tests.test_final_secondary import SecondaryFixture
from tests.test_final_preflight import trial_directory


class SecondaryOperatorTests(unittest.TestCase):
    def test_native_live_dependencies_are_the_original_functions(self):
        for name in ("loader", "transport", "checkpoint", "initialize", "_save_resource_record"):
            self.assertIs(getattr(operator.Session, name), getattr(OriginalSession, name))
        self.assertIsNot(operator.Session.metadata_gate, OriginalSession.metadata_gate)
        self.assertIsNot(operator.Session.run, OriginalSession.run)

    def test_construction_reads_metadata_only_and_artificial_candidate_cannot_open_live_dependencies(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            candidate = dict(f.candidate, operator={"output_directory": str(f.folder),
                "operation_directory": str(f.root / "operation")})
            candidate = gate.seal(candidate)
            candidate_file = f.file("candidate-operator.json", candidate)
            binding_file = f.file("binding-operator.json", f.binding)
            session = operator.Session(candidate_file["path"], binding_file["path"])
            self.assertIsNone(session.client)
            self.assertIsNone(session.encoder)
            with self.assertRaises(gate.StudyStop):
                session.metadata_gate()
            with self.assertRaises(gate.StudyStop):
                session.create_execution()
            self.assertIsNone(session.client)
            self.assertIsNone(session.encoder)
            self.assertFalse(f.folder.exists())
            self.assertFalse((f.root / "operation").exists())

    def test_extension_backup_requires_bytes_all_members_and_exact_remote_receipt(self):
        # Entirely artificial receipt: exercises the actual live-gate helper,
        # without invoking the real activation path or contacting any remote.
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            paths = sorted(f.binding["source_files"].items())
            expected = {f"extension-{i:04d}": checksum for i, (_, checksum) in enumerate(paths)}
            archive_path = f.root / "artificial-extension-source.zip"
            with ZipFile(archive_path, "x") as archive:
                for i, (path, _) in enumerate(paths):
                    archive.write(path, f"extension-{i:04d}")
            proof = {"path": str(archive_path), "sha256": file_hash(archive_path), "members": expected}
            record = {"artificial_only": True, "source_files": f.binding["source_files"],
                "local_archive": proof, "remote_receipt": {"destination": "Jnooo-cloud/masterarbeit-mas-pruning",
                "archive_sha256": proof["sha256"], "members": expected, "full_remote_reread": True}}
            self.assertEqual(secondary._verify_extension_backup(f.binding, record), expected)
            live_binding = dict(f.binding, mode="authorized_execution")
            with self.assertRaises(gate.StudyStop):
                secondary._verify_extension_backup(live_binding, record)
            for marked in ({"artificial_only": True}, {"origin": "artificial_fixture"},
                           {"nested": {"mode": "synthetic"}}, {"test_authorized": True}):
                with self.subTest(artificial_live_record=marked), self.assertRaises(gate.StudyStop):
                    secondary._require_real_evidence(marked)
            for field in ("source_files", "local_archive", "remote_receipt"):
                broken = deepcopy(record)
                broken.pop(field)
                with self.subTest(missing=field), self.assertRaises(Exception):
                    secondary._verify_extension_backup(f.binding, broken)
            for field, value in (("full_remote_reread", False), ("archive_sha256", "0" * 64),
                                 ("destination", "different-private-target"), ("members", {})):
                broken = deepcopy(record)
                broken["remote_receipt"][field] = value
                with self.subTest(changed=field), self.assertRaises(Exception):
                    secondary._verify_extension_backup(f.binding, broken)
            # A changed local archive with a matching updated container hash
            # still cannot omit a single required recoverable source member.
            missing_path = f.root / "artificial-extension-missing-member.zip"
            with ZipFile(missing_path, "x") as archive:
                for i, (path, _) in enumerate(paths[:-1]):
                    archive.write(path, f"extension-{i:04d}")
            broken = deepcopy(record)
            broken["local_archive"].update(path=str(missing_path), sha256=file_hash(missing_path))
            broken["remote_receipt"]["archive_sha256"] = file_hash(missing_path)
            with self.assertRaises(Exception):
                secondary._verify_extension_backup(f.binding, broken)

    def test_activation_inputs_are_explicit_and_inert(self):
        report = operator.activation_inputs()
        self.assertFalse(report["live_enabled_by_this_function"])
        self.assertEqual(report["schema"], "z52-secondary-activation/v1")
        self.assertGreaterEqual(len(report["required"]), 10)
        self.assertTrue(any("budget.unresolved=true" in value for value in report["required"]))
        self.assertTrue(any("remote reread" in value for value in report["required"]))


if __name__ == "__main__":
    unittest.main()
