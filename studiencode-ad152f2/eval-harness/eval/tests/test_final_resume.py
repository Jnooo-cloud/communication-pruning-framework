"""Bounded Z51 synthetic continuation tests; no live tasks or network.

Z50_TEST_EVIDENCE_DIR retains every fixture and failed attempt. Archive this
module and its implementation/dependencies before every decisive test process.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import unittest

from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study import file_hash
from study_preparation import final_execution as fe, final_preflight as fp, final_recovery as fr, final_resume as resume
from study_preparation.final_plan import canonical_hash
from tests.test_final_preflight import Fixture, trial_directory


class ResumeFixture:
    def __init__(self, directory, *, prefix=1, remaining=2, old_extra_commitment=None):
        self.root = Path(directory).resolve()
        self.f = Fixture(self.root, counts={"P": prefix + remaining, "R": 1, "T": 1, "F": 1})
        self.prefix = prefix
        self.f.candidate["section_ends"] = list(range(prefix, prefix + remaining + 4))
        if old_extra_commitment is not None:
            self.f.candidate["budget"]["positions_excluding_study"].append({
                "id": "invented-prior-main", "bucket": "main", "known_usd": old_extra_commitment,
                "remaining_commitment_usd": "0", "protected": False})
        self.f.bind()
        self.checkpoint = self.f.run(prefix)
        self.f.transport.fail_at, self.f.transport.mode = self.checkpoint["budget"]["calls"] + 2, "transport"
        try:
            self.f.run(prefix + 1)
        except BudgetStop:
            pass
        else:
            raise AssertionError("fixture did not preserve an unknown original call")
        self.old = fr.original_inventory(self.f.folder)
        self.recovery = self.root / "original-recovery"
        self.report = fr.prepare_recovery(self.f.candidate, self.f.plan, original_folder=self.f.folder,
            output=self.recovery, recovery_id="synthetic-resume-original", inventory=self.old,
            expected_inventory_sha256=canonical_hash(self.old), checkpoint=self.checkpoint,
            expected_checkpoint_sha256=self.checkpoint["state_sha256"])
        self.folder = self.root / "new-segment"
        self.extra_source = self.root / "additional-bound-source.py"
        self.extra_source.write_text("# synthetic immutable source evidence\n")
        paths = [Path(resume.__file__).resolve(), Path(fr.__file__).resolve(), Path(__file__).resolve(), self.extra_source]
        self.sources = {str(path): file_hash(path) for path in paths}
        self.source_zip = self.root / "additional-sources.zip"
        with ZipFile(self.source_zip, "x") as archive:
            for i, (name, checksum) in enumerate(sorted(self.sources.items())):
                archive.write(name, f"resume-source-{i:04d}")
        self.activation = resume.make_activation(self.f.candidate, self.f.plan, folder=self.folder,
            control=self.f.control, recovery_folder=self.recovery, expected_manifest_sha256=self.report["manifest_sha256"],
            resume_id="synthetic-once", source_files=self.sources,
            source_backup={"path": str(self.source_zip), "sha256": file_hash(self.source_zip),
                           "members": resume.source_members(self.sources)},
            checkpoint=self.backup, approval_reference="synthetic D-069 fixture; no live authorization")
        self.activation_hash = canonical_hash(self.activation)
        self.backups = 0

    def backup(self, state):
        path = self.folder / "receipts" / f"synthetic-backup-{self.backups:03d}.zip"
        self.backups += 1
        with ZipFile(path, "x") as archive:
            for name in state["evidence"]:
                archive.write(self.folder / name, name)
        return {"path": str(path), "sha256": file_hash(path), "members": state["evidence"]}

    def args(self):
        return dict(folder=self.folder, control=self.f.control,
                    expected_activation_sha256=self.activation_hash, clock=self.f.clock)

    def initialize(self):
        return resume.initialize_resume(self.f.candidate, self.f.plan, **self.args(), recovery_folder=self.recovery,
            expected_manifest_sha256=self.report["manifest_sha256"], activation=self.activation)

    def run(self, end):
        return resume.run_section(self.f.candidate, self.f.plan, **self.args(), section_end=end,
            loader=self.f.loader, spatial_selector=self.f.spatial_selector, transport=self.f.transport,
            checkpoint=self.backup)

    def inspect(self):
        return resume.inspect_resume(self.f.candidate, self.f.plan, **self.args())


class FinalResumeTests(unittest.TestCase):
    def test_exact_partial_replay_once_and_complete_join_without_duplicate_costs(self):
        with trial_directory() as directory:
            r = ResumeFixture(directory)
            initial = r.initialize()
            self.assertEqual(initial["completed_blocks"], 1)
            self.assertEqual(initial["new_budget"]["calls"], 0)
            loads, selections, old_calls = len(r.f.loads), len(r.f.selections), r.f.transport.calls
            saved_unknown = (r.f.folder / "provider" / f"{old_calls:05d}-request.json").read_bytes()
            state = r.run(2)
            self.assertEqual((len(r.f.loads), len(r.f.selections)), (loads, selections))
            self.assertEqual((r.folder / "provider" / "00001-request.json").read_bytes(), saved_unknown)
            self.assertEqual(state["new_budget"]["calls"], r.f.transport.calls - old_calls)
            self.assertEqual(Decimal(state["budget"]["known_cost_usd"]),
                Decimal(r.report["budget"]["known_cost_usd"]) + Decimal(state["new_budget"]["known_cost_usd"]))
            self.assertIsNone(state["budget"]["total_cost_usd"])
            self.assertEqual(state["budget"]["held_reservation_usd"], "0.14")
            self.assertFalse(state["budget"]["reservation_is_expense"])
            self.assertEqual(state["budget"]["pending"], r.activation["unknown_attempt_id"])
            self.assertFalse(state["cost_assumption"]["provider_cost_confirmed"])
            self.assertEqual(Decimal(state["levels"]["available_usd"]["main"]),
                             Decimal("40.00") - Decimal(state["budget"]["known_cost_usd"]) - Decimal("0.14"))
            self.assertEqual(fr.original_inventory(r.f.folder), r.old)
            for actual, original in zip(state["rows"], r.checkpoint["rows"]):
                self.assertEqual({k: v for k, v in actual.items() if k != "recovery_provenance"}, original)
                self.assertEqual(actual["recovery_provenance"]["original_row_sha256"], canonical_hash(original))
            first = fp.read_json(r.folder / "mapping" / "000001.json")
            replacement = fp.read_json(r.folder / "mapping" / "000002.json")
            self.assertEqual(first["origin"], "preserved_original")
            self.assertEqual(replacement["origin"], "replacement")
            self.assertNotEqual(replacement["logical_attempt_id"], replacement["physical_attempt_id"])
            self.assertEqual(replacement["logical_attempt_id"], r.activation["unknown_attempt_id"])
            state = r.run(3)
            self.assertTrue(state["complete"])
            rows = resume.collect_panel(r.f.candidate, r.f.plan, **r.args())
            self.assertEqual(len(rows), 6)
            self.assertEqual(sum((Decimal(row["cost_usd"]) for row in rows), Decimal(0)),
                             Decimal(state["budget"]["known_cost_usd"]))
            self.assertEqual((len(r.f.loads), len(r.f.selections)), (loads + 1, selections + 1))
            self.assertEqual(fr.original_inventory(r.f.folder), r.old)

    def test_hundred_pair_prefix_remains_and_101_is_a_real_additional_hold(self):
        with trial_directory() as directory:
            r = ResumeFixture(directory, prefix=100, remaining=2)
            r.initialize()
            old_calls = r.f.transport.calls
            with self.assertRaises(fp.StudyStop):
                r.run(102)
            self.assertEqual(r.f.transport.calls, old_calls)
            state = r.run(101)
            self.assertEqual(state["completed_blocks"], 101)
            self.assertFalse((r.folder / "blocks" / "000101").exists())
            self.assertEqual(fr.original_inventory(r.f.folder), r.old)
            self.assertEqual(len([row for row in state["rows"] if row["recovery_provenance"]["origin"] == "original_checkpoint"]), 200)
            with self.assertRaises(ValueError):
                resume.collect_panel(r.f.candidate, r.f.plan, **r.args())

    def test_create_only_activation_and_original_lock_reject_double_start(self):
        with trial_directory() as directory:
            r = ResumeFixture(directory)
            with fe.study_lock(r.f.control):
                with self.assertRaises(fp.StudyStop):
                    r.initialize()
            r.initialize()
            with self.assertRaises(fp.StudyStop):
                r.initialize()
            other = r.root / "other-segment"
            changed = deepcopy(r.activation)
            changed["folder"] = str(other)
            with self.assertRaises(FileExistsError):
                resume.initialize_resume(r.f.candidate, r.f.plan, folder=other, control=r.f.control,
                    recovery_folder=r.recovery, expected_manifest_sha256=r.report["manifest_sha256"],
                    activation=changed, expected_activation_sha256=canonical_hash(changed), clock=r.f.clock)
            self.assertFalse(other.exists())
            with fe.study_lock(r.f.control):
                with self.assertRaises(fp.StudyStop):
                    r.run(2)

    def test_changed_replay_or_replacement_request_stops_before_transport(self):
        original_execute = resume.execute
        for target_call in (1, 2):
            with self.subTest(target_call=target_call), trial_directory() as directory:
                r = ResumeFixture(directory)
                r.initialize()
                old_calls = r.f.transport.calls
                count = 0
                def corrupt(task, config, send, **kwargs):
                    def wrapped(request):
                        nonlocal count
                        count += 1
                        if count == target_call:
                            request = replace(request, instruction=request.instruction + " changed")
                        return send(request)
                    return original_execute(task, config, wrapped, **kwargs)
                with patch.object(resume, "execute", corrupt), self.assertRaises(Exception):
                    r.run(2)
                self.assertEqual(r.f.transport.calls, old_calls)
                stop = fp.read_json(r.folder / "STOP.json")
                self.assertFalse(stop["retry_allowed"])
                self.assertNotIn("message", stop)
                with self.assertRaises(fp.StudyStop):
                    r.run(2)

    def test_changed_original_inventory_source_activation_and_recovery_stop(self):
        for kind in ("original", "source", "activation", "manifest"):
            with self.subTest(kind=kind), trial_directory() as directory:
                r = ResumeFixture(directory)
                r.initialize()
                old_calls = r.f.transport.calls
                paths = {"original": r.f.folder / "provider" / "00001-response.json",
                         "source": r.extra_source, "activation": r.folder / "ACTIVATION.json",
                         "manifest": r.recovery / "ORIGINALS.json"}
                path = paths[kind]
                if kind == "activation":
                    obj = fp.read_json(path)
                    obj["unknown_request_sha256"] = "0" * 64
                    path.write_bytes(encoded(obj))
                else:
                    path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaises(Exception):
                    r.run(2)
                self.assertEqual(r.f.transport.calls, old_calls)
                self.assertFalse((r.folder / "blocks" / "000001").exists())

    def test_new_unknown_outcome_persists_and_cannot_be_retried(self):
        with trial_directory() as directory:
            r = ResumeFixture(directory)
            r.initialize()
            r.f.transport.fail_at = r.f.transport.calls + 1
            old_calls = r.f.transport.calls
            with self.assertRaises(BudgetStop):
                r.run(2)
            self.assertEqual(r.f.transport.calls, old_calls + 1)
            self.assertTrue((r.folder / "provider" / "00001-request.json").exists())
            self.assertTrue((r.folder / "STOP.json").exists())
            self.assertEqual(fr.original_inventory(r.f.folder), r.old)
            with self.assertRaises(fp.StudyStop):
                r.run(2)
            with self.assertRaises(fp.StudyStop):
                r.inspect()
            self.assertEqual(r.f.transport.calls, old_calls + 1)

    def test_calendar_expiry_and_budget_headroom_stop_without_new_call(self):
        with trial_directory() as directory:
            r = ResumeFixture(directory)
            r.initialize()
            old_calls = r.f.transport.calls
            r.f.clock = lambda: 1001
            with self.assertRaises(fp.StudyStop):
                r.run(2)
            self.assertEqual(r.f.transport.calls, old_calls)
        with trial_directory() as directory:
            r = ResumeFixture(directory)
            old_calls = r.f.transport.calls
            # Frozen caps are exercised independently with actual old/new amounts.
            with self.assertRaises(fp.StudyStop):
                resume._levels(r.f.candidate, Decimal("39.75"), Decimal("0.00"), reserve_calls=1)
            with self.assertRaises(fp.StudyStop):
                resume._levels(r.f.candidate, Decimal("39.90"), Decimal("0.00"))
            self.assertEqual(r.f.transport.calls, old_calls)

    def test_complete_evidence_tampering_and_extra_dispatch_files_are_rejected(self):
        for name in ("mapping/000002.json", "provider/00001-binding.json", "provider/00001-billing.json", "provider/99999-request.json"):
            with self.subTest(name=name), trial_directory() as directory:
                r = ResumeFixture(directory)
                r.initialize()
                r.run(2)
                path = r.folder / name
                path.write_bytes(path.read_bytes() + b" " if path.exists() else b"{}")
                with self.assertRaises(Exception):
                    r.inspect()

    def test_provider_duplicate_generation_and_over_reservation_stop(self):
        for mode in ("duplicate", "over", "unknown"):
            with self.subTest(mode=mode), trial_directory() as directory:
                r = ResumeFixture(directory)
                r.initialize()
                r.f.transport.fail_at, r.f.transport.mode = r.f.transport.calls + 1, mode
                old_calls = r.f.transport.calls
                with self.assertRaises(BudgetStop):
                    r.run(2)
                self.assertEqual(r.f.transport.calls, old_calls + 1)
                with self.assertRaises(fp.StudyStop):
                    r.run(2)

    def test_backup_receipt_required_before_next_block(self):
        with trial_directory() as directory:
            r = ResumeFixture(directory)
            r.initialize()
            real_backup = r.backup
            with patch.object(resume, "_checkpoint", side_effect=OSError("synthetic backup loss")), self.assertRaises(OSError):
                r.run(2)
            self.assertFalse((r.folder / "STOP.json").exists())
            old_calls = r.f.transport.calls
            with self.assertRaises(FileNotFoundError):
                r.run(3)
            self.assertEqual(r.f.transport.calls, old_calls)
            resume.checkpoint_resume(r.f.candidate, r.f.plan, **r.args(), checkpoint=real_backup)
            state = r.run(3)
            self.assertTrue(state["complete"])

    def test_fake_provider_zero_or_rebound_science_cannot_authorize(self):
        for mutation in ("provider_zero", "unknown_id", "source_backup", "calendar", "candidate"):
            with self.subTest(mutation=mutation), trial_directory() as directory:
                r = ResumeFixture(directory)
                changed = deepcopy(r.activation)
                if mutation == "provider_zero":
                    changed["author_assumption"]["provider_cost_confirmed"] = True
                elif mutation == "unknown_id":
                    changed["unknown_attempt_id"] += "-other"
                elif mutation == "source_backup":
                    changed["source_backup"]["members"].clear()
                elif mutation == "calendar":
                    r.f.candidate["calendar"]["end_epoch"] = 2000
                    r.f.candidate = fp.seal(r.f.candidate)
                else:
                    changed["candidate_sha256"] = "f" * 64
                r.activation, r.activation_hash = changed, canonical_hash(changed)
                with self.assertRaises(Exception):
                    r.initialize()
                self.assertFalse(r.folder.exists())

    def test_secondary_panels_and_full_panel_on_prefix_are_rejected(self):
        with trial_directory() as directory:
            r = ResumeFixture(directory)
            r.initialize()
            r.run(2)
            with self.assertRaises(ValueError):
                resume.collect_panel(r.f.candidate, r.f.plan, **r.args())
            with self.assertRaises(fp.StudyStop):
                resume.collect_panel(r.f.candidate, r.f.plan, "R", **r.args())
            old_calls = r.f.transport.calls
            with self.assertRaises(fp.StudyStop):
                r.run(4)
            self.assertEqual(r.f.transport.calls, old_calls)


if __name__ == "__main__":
    unittest.main()
