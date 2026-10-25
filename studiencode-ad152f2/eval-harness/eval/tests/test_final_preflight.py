"""Artificial Z50 gate fixtures; no model, network, real question or real gold.

Z50_TEST_EVIDENCE_DIR retains all trial files, including rejected/partial runs.
The coordinator archives source and tests before invoking this module.
"""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory as EphemeralDirectory, mkdtemp
from zipfile import ZipFile
import json
import os
import unittest

from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference
from communication_pruning.openrouter import encoded
from communication_pruning.study import file_hash
from study_preparation.final_plan import make_plan, ARMS
from study_preparation import final_execution as fe, final_preflight as fp
from tests.study_fixture import FakeTransport


@contextmanager
def trial_directory():
    retained = os.environ.get("Z50_TEST_EVIDENCE_DIR")
    if retained:
        Path(retained).mkdir(parents=True, exist_ok=True)
        yield mkdtemp(prefix="artificial-z50-", dir=retained)
    else:
        with EphemeralDirectory() as temporary:
            yield temporary


class Fixture:
    def __init__(self, root, *, counts=None, q="C01", fixed="C01", temporal=2):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.folder, self.control = self.root / "output", self.root / "control"
        self.q, self.fixed, self.temporal = q, fixed, temporal
        self.loads, self.selections, self.time_selections, self.backups = [], [], [], 0
        self.transport = FakeTransport()
        self.clock = lambda: 100
        self.frame = [{"task_id": "synthetic-one", "family_id": "synthetic-family"}]
        paths = fp.required_source_paths() | {str(Path(__file__).resolve()),
            str(Path(__file__).with_name("test_final_execution.py").resolve()),
            str(Path(__file__).with_name("study_fixture.py").resolve())}
        sources = {name: file_hash(name) for name in sorted(paths)}
        self.documents = {}
        for key, value in {
            "design": {"synthetic": True}, "analysis_contract": {"synthetic": True},
            "source_manifest": {"files": sources}, "frame_metadata": self.frame,
            "exposure_metadata": {"schema": "z50-exposure-metadata/v1", "input_sha256": {},
                "all_documented_exposed_task_ids": [], "all_documented_exposed_family_ids": [],
                "holdout_task_overlap": [], "holdout_family_overlap": []},
            "spatial_q": {"synthetic": True}, "spatial_f": {"config_id": fixed},
            "temporal_qst": {"synthetic": True}, "temporal_qtf": {"rounds": 1},
        }.items():
            self.documents[key] = self.file(key + ".json", value)
        self.plan = make_plan(self.frame, seed_base=71,
            bindings={k: v["sha256"] for k, v in self.documents.items()},
            mode="artificial_only", counts=counts or {p: 1 for p in ARMS})
        self.candidate = fp.prepare_candidate(self.plan, source_files=sources)
        provider = self.root / "provider-fixture.json"
        provider.write_bytes(FakeTransport()("models/google/gemini-2.5-flash-lite/endpoints")[1])
        self.candidate.update(mode="artificial_only", test_authorized=True,
            documents=self.documents, fixed_config_id=fixed, fixed_rounds=1,
            provider_evidence={"path": str(provider), "sha256": file_hash(provider)},
            provider_observation={"origin": "artificial_fixture", "observed_epoch": 1},
            plan_evidence=self.file("plan.json", self.plan),
            runtime_manifest=self.file("runtime.json", fp.runtime_identity()),
            control_directory=str(self.control.resolve()),
            calendar={"start_epoch": 0, "end_epoch": 1000, "maximum_duration_seconds": 1000, "origin": "artificial_clock"},
            section_ends=list(range(1, sum(self.plan["counts"].values()) + 1)))
        self.candidate["budget"].update(unresolved=False,
            positions_excluding_study=[{"id": key, "bucket": "overall_only", "known_usd": "0",
                "remaining_commitment_usd": value, "protected": True} for key, value in fp.PROTECTED.items()])
        self.bind()

    def file(self, name, value):
        path = self.root / name
        path.write_bytes(encoded(value))
        return {"path": str(path.resolve()), "sha256": file_hash(path)}

    def dependencies(self):
        return dict(loader=self.loader, spatial_selector=self.spatial_selector,
                    temporal_selector=self.temporal_selector, transport=self.transport, checkpoint=self.checkpoint)

    def bind(self):
        self.candidate["dependency_bindings"] = {key: fp.dependency_identity(value) for key, value in self.dependencies().items()}
        self.candidate["budget_evidence"] = self.file("budget-evidence.json", {
            "complete_nonoverlapping": True, "budget": self.candidate["budget"], "origin": "artificial_fixture"})
        files = dict(self.candidate["source_files"])
        files.update({v["path"]: v["sha256"] for v in self.candidate["documents"].values()})
        for key in ("provider_evidence", "runtime_manifest", "budget_evidence", "plan_evidence"):
            value = self.candidate[key]
            files[value["path"]] = value["sha256"]
        path = self.root / f"source-backup-{self.backups}.zip"
        self.backups += 1
        members = {}
        with ZipFile(path, "x") as archive:
            for i, (name, checksum) in enumerate(sorted(files.items())):
                member = f"source-{i:04d}"
                archive.write(name, member)
                members[member] = checksum
        self.candidate["source_backup"] = {"path": str(path), "sha256": file_hash(path), "members": members}
        self.candidate = fp.seal(self.candidate)

    def loader(self, task_id):
        self.loads.append(task_id)
        public = fe.public_task_id(self.plan, task_id)
        return TaskInput(public, "Invented question?", ("Invented safe context.",)), AnswerReference(public, ("PRIVATE_FAKE_GOLD",))

    def spatial_selector(self, task):
        assert type(task) is TaskInput
        self.selections.append(task)
        return self.q

    def temporal_selector(self, task):
        assert type(task) is TaskInput
        self.time_selections.append(task)
        return self.temporal

    def checkpoint(self, state):
        path = self.folder / "receipts" / f"backup-{self.backups}.zip"
        self.backups += 1
        with ZipFile(path, "x") as archive:
            for name in state["evidence"]:
                archive.write(self.folder / name, name)
        return {"path": str(path), "sha256": file_hash(path), "members": state["evidence"]}

    def args(self):
        return dict(folder=self.folder, control=self.control, clock=self.clock)

    def check(self):
        return fp.preflight(self.candidate, self.plan, control=self.control, clock=self.clock, dependencies=self.dependencies())

    def run(self, end):
        return fe.run_section(self.candidate, self.plan, **self.args(), section_end=end, **self.dependencies())


class FinalPreflightTests(unittest.TestCase):
    def test_complete_artificial_gate_never_claims_live_evidence(self):
        with trial_directory() as directory:
            f = Fixture(directory)
            self.assertEqual(f.check()["mode"], "artificial_only")
            self.assertFalse(f.check()["study_frozen"])
            self.assertFalse(f.check()["live_evidence"])
            self.assertEqual((f.loads, f.selections, f.transport.calls), ([], [], 0))

    def test_missing_rights_freeze_and_binding_changes_stop_before_loader(self):
        mutations = [lambda c: c.update(mode="not_authorized"),
                     lambda c: c.update(mode="authorized_execution", test_authorized=False),
                     lambda c: c.update(source_backup=None),
                     lambda c: c.update(plan_evidence=None),
                     lambda c: c.update(fixed_rounds=2),
                     lambda c: c.update(direct_prompt="changed prompt"),
                     lambda c: c.update(section_ends=[2]),
                     lambda c: c["provider_observation"].update(observed_epoch=-1),
                     lambda c: c["calendar"].update(end_epoch=99)]
        for mutate in mutations:
            with self.subTest(mutate=mutate), trial_directory() as directory:
                f = Fixture(directory)
                mutate(f.candidate)
                f.candidate = fp.seal(f.candidate)
                with self.assertRaises((fp.StudyStop, ValueError, TypeError)):
                    f.run(1)
                self.assertEqual((f.loads, f.selections, f.transport.calls), ([], [], 0))

    def test_original_files_archive_runtime_and_dependency_binding_are_checked(self):
        for field in ("source_backup", "runtime_manifest", "provider_evidence", "budget_evidence", "plan_evidence"):
            with self.subTest(field=field), trial_directory() as directory:
                f = Fixture(directory)
                path = Path(f.candidate[field]["path"])
                path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaises(Exception):
                    f.run(1)
                self.assertEqual(f.loads, [])
                self.assertEqual(f.transport.calls, 0)
        with trial_directory() as directory:
            f = Fixture(directory)
            f.candidate["dependency_bindings"]["loader"]["qualname"] = "foreign"
            f.candidate = fp.seal(f.candidate)
            with self.assertRaises(fp.StudyStop):
                f.run(1)
            self.assertEqual(f.loads, [])

    def test_original_exposure_schema_uses_lists_and_checks_family_overlap(self):
        with trial_directory() as directory:
            f = Fixture(directory)
            exposure = fp.read_json(f.documents["exposure_metadata"]["path"])
            self.assertEqual(exposure["holdout_task_overlap"], [])
            self.assertEqual(exposure["holdout_family_overlap"], [])
            f.check()
            # A changed metadata review cannot be silently substituted after the
            # plan has already bound its exact source-file hash.
            exposure["all_documented_exposed_family_ids"] = ["synthetic-family"]
            Path(f.documents["exposure_metadata"]["path"]).write_bytes(encoded(exposure))
            with self.assertRaises(Exception):
                f.run(1)
            self.assertEqual((f.loads, f.transport.calls), ([], 0))

    def test_budget_three_levels_no_double_count_and_protected_reserves(self):
        with trial_directory() as directory:
            f = Fixture(directory)
            b = f.candidate["budget"]
            b["positions_excluding_study"].append({"id": "time-development", "bucket": "secondary",
                "known_usd": "1.00", "remaining_commitment_usd": "0.25", "protected": False})
            known = {"P": Decimal("2"), "R": Decimal("3"), "T": Decimal("4"), "F": Decimal("5")}
            view = fp.budget_view(f.candidate, known, panel="R", reserve_calls=36)
            self.assertEqual(view["available_usd"], {"overall": "84.33", "main": "38.00", "secondary": "42.63"})
            self.assertEqual(view["block_reservation_usd"], "5.04")
            self.assertFalse(view["reservation_is_expense"])
            b["positions_excluding_study"][0]["remaining_commitment_usd"] = "19.99"
            with self.assertRaises(fp.StudyStop):
                fp.budget_view(f.candidate, known)

    def test_reserve_full_block_before_loader_at_each_budget_level(self):
        for bucket, amount in (("main", "38.05"), ("overall_only", "97.63")):
            with self.subTest(bucket=bucket), trial_directory() as directory:
                f = Fixture(directory)
                f.candidate["budget"]["positions_excluding_study"].append({"id": "other", "bucket": bucket,
                    "known_usd": amount, "remaining_commitment_usd": "0", "protected": False})
                f.bind()
                with self.assertRaises(fp.StudyStop):
                    f.run(1)
                self.assertEqual((f.loads, f.transport.calls), ([], 0))
        with trial_directory() as directory:
            f = Fixture(directory)
            f.candidate["budget"]["positions_excluding_study"].append({"id": "time-development", "bucket": "secondary",
                "known_usd": "50.85", "remaining_commitment_usd": "0", "protected": False})
            f.bind()
            f.run(1)
            before = f.transport.calls
            with self.assertRaises(fp.StudyStop):
                f.run(2)
            self.assertEqual(len(f.loads), 1)
            self.assertEqual(f.transport.calls, before)


if __name__ == "__main__":
    unittest.main()
