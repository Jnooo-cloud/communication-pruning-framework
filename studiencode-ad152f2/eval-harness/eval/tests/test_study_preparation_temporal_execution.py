"""Z45 artificial orchestration cases. No network, true gold, Q evaluation or fit."""
from copy import deepcopy
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory as EphemeralDirectory, mkdtemp
from zipfile import ZipFile
import json
import os
import unittest

from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference, digest as data_digest
from communication_pruning.openrouter import encoded
from communication_pruning.study import file_hash
from study_preparation import temporal_execution as te
from study_preparation.temporal import make_temporal_plan
from tests.test_study_preparation_temporal import metadata, BINDINGS
from tests.study_fixture import FakeTransport


@contextmanager
def TemporaryDirectory():
    """Retain all artificial trial evidence in a bound test run, including failures."""
    target = os.environ.get("Z45_TEST_EVIDENCE_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        yield mkdtemp(prefix="artificial-", dir=target)
    else:
        with EphemeralDirectory() as path:
            yield path


class Fixture:
    def __init__(self, root, *, roles=2):
        self.root = Path(root)
        self.folder, self.control = self.root / "output", self.root / "control"
        self.manifest, self.allocation = metadata()
        self.plan = make_temporal_plan(self.manifest, self.allocation, BINDINGS)
        self.provider = self.root / "provider-fixture.json"
        self.provider.write_bytes(FakeTransport()("models/google/gemini-2.5-flash-lite/endpoints")[1])
        self.marker = self.root / "source-marker.txt"
        self.marker.write_text("artificial binding")
        self.candidate = te.prepare_candidate(self.plan, source_files={
            str(p.resolve()): file_hash(p) for p in (Path(te.__file__), self.provider, self.marker)})
        self.candidate.update(mode="artificial_only", test_authorized=True,
            control_directory=str(self.control.resolve()),
            provider_evidence={"path": str(self.provider), "sha256": file_hash(self.provider), "origin": "artificial_fixture"},
            calendar={"start_epoch": 0, "end_epoch": 1000, "origin": "artificial_clock"})
        self.candidate["budget"]["positions_excluding_current_phase"] = [
            {"id": key, "bucket": "overall_only", "known_usd": "0",
             "remaining_commitment_usd": value, "protected": True}
            for key, value in te.PROTECTED.items()]
        self.loads, self.selections, self.backups = [], [], 0
        self.config = next(c for c in bank() if len(c.roles) == roles)
        self.transport = FakeTransport()
        self.clock = lambda: 100
        self.bind()

    def bind(self, *, release=False):
        if release:
            # A fake authorization object solely exercises the same code branch.
            self.candidate.update(mode="authorized_execution", authorized=True, test_authorized=False,
                                  parameters_status="accepted")
            self.candidate["provider_evidence"]["origin"] = "current_preflight"
            self.candidate["calendar"]["origin"] = "author_bound"
            self.candidate["calendar_contract"]["status"] = "accepted"
            approval = self.root / "FAKE-NOT-A-REAL-APPROVAL.json"
            approval.write_bytes(encoded({"author": "Jannik", "authorized": True, "phase": "temporal",
                "approval_reference": "ARTIFICIAL TEST ONLY; NOT AN AUTHOR DECISION",
                "execution_binding_sha256": te.execution_binding(self.candidate)}))
            self.candidate["author_release"] = {"path": str(approval), "sha256": file_hash(approval)}
        path = self.root / f"sources-{self.backups}.zip"
        self.backups += 1
        members = {}
        with ZipFile(path, "x") as z:
            for i, (name, checksum) in enumerate(sorted(self.candidate["source_files"].items())):
                member = f"source-{i:03d}"
                z.write(name, member)
                members[member] = checksum
            if self.candidate["mode"] == "authorized_execution":
                approval = self.candidate["author_release"]
                z.write(approval["path"], "author-release")
                members["author-release"] = approval["sha256"]
        self.candidate["source_backup"] = {"path": str(path), "sha256": file_hash(path), "members": members}
        self.candidate = te.seal(self.candidate)

    def loader(self, task_id):
        self.loads.append(task_id)
        public = "task-" + data_digest([self.manifest["source_hashes"]["train"], task_id])
        return TaskInput(public, "Invented public question?", ("Invented public context.",)), AnswerReference(public, ("PRIVATE_FAKE_GOLD",))

    def selector(self, task):
        assert type(task) is TaskInput
        assert set(vars(task)) == {"task_id", "question", "paragraphs"}
        self.selections.append(task)
        return self.config.config_id

    def checkpoint(self, state):
        path = self.folder / "receipts" / f"backup-{self.backups}.zip"
        self.backups += 1
        with ZipFile(path, "x") as z:
            for name in state["evidence"]:
                z.write(self.folder / name, name)
        return {"path": str(path), "sha256": file_hash(path), "members": state["evidence"]}

    def args(self):
        return dict(folder=self.folder, control=self.control, clock=self.clock)

    def run(self, end=1, **overrides):
        kwargs = dict(**self.args(), section_end=end, loader=self.loader, spatial_selector=self.selector,
                      transport=self.transport, checkpoint=self.checkpoint)
        kwargs.update(overrides)
        return te.run_section(self.candidate, self.plan, self.manifest, self.allocation, **kwargs)

    def inspect(self):
        return te.inspect_temporal(self.candidate, self.plan, self.manifest, self.allocation, **self.args())


class TemporalExecutionTests(unittest.TestCase):
    def test_full_100_pairs_200_fresh_slots_payloads_and_numerical_export(self):
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            for end in (1, 10, 40, 70, 100):
                state = f.run(end)
                self.assertEqual(state["completed_pairs"], end)
                self.assertEqual(state["budget"]["calls"], 8 * end)
            self.assertEqual(len(set(f.loads)), 100)
            self.assertEqual(len(f.selections), 100)
            self.assertEqual(len(list((f.folder / "slots").glob("*.jsonl"))), 200)
            self.assertEqual(len(state["generation_ids"]), 800)
            export = te.collect_temporal_pairs(f.candidate, f.plan, f.manifest, f.allocation, **f.args())
            self.assertEqual(len(export["pairs"]), 100)
            self.assertFalse(export["fit_executed"])
            for pair in export["pairs"]:
                self.assertEqual(pair["rounds"], [1, 2])
                self.assertEqual(pair["em"], [0.0, 0.0])
                self.assertEqual(pair["cost_usd"], ["0.0000324", "0.0000540"])
                self.assertEqual(pair["spatial_config_id"], f.config.config_id)
            bodies = json.dumps(f.transport.bodies)
            for secret in ("PRIVATE_FAKE_GOLD", "synthetic-", "family_id", "hop", "task-"):
                self.assertNotIn(secret, bodies)
            # Exactly 200 starts with empty predecessor messages; no previous-arm carryover.
            journals = [json.loads(p.read_text().splitlines()[0]) for p in (f.folder / "slots").glob("*.jsonl")]
            self.assertEqual(len(journals), 200)
            before = f.transport.calls
            with self.assertRaises(te.TemporalStop):
                f.run(100)
            self.assertEqual(f.transport.calls, before)

    def test_three_roles_and_external_release_branch_only_artificial_transport(self):
        for released in (False, True):
            with self.subTest(released=released), TemporaryDirectory() as tmp:
                f = Fixture(tmp, roles=3)
                if released:
                    f.bind(release=True)
                state = f.run()
                self.assertEqual(state["budget"]["calls"], 11)
                self.assertEqual(len(f.selections), 1)
                self.assertEqual(f.transport.calls, 11)

    def test_missing_and_changed_gates_stop_before_loader_selection_transport(self):
        kinds = ("unauthorized", "plan", "panel", "source", "provider", "calendar", "archive", "live_without_release")
        for kind in kinds:
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                if kind == "unauthorized": f.candidate["test_authorized"] = False
                if kind == "plan": f.plan["phase"] = "pilot"
                if kind == "panel": f.allocation["panels"]["temporal"].pop()
                if kind == "source": f.marker.write_text("changed")
                if kind == "provider": f.candidate["provider_evidence"]["origin"] = "unbound"
                if kind == "calendar": f.clock = lambda: 1001
                if kind == "archive": f.candidate["source_backup"]["sha256"] = "a" * 64
                if kind == "live_without_release":
                    f.candidate.update(mode="authorized_execution", authorized=True, test_authorized=False, parameters_status="accepted")
                f.candidate = te.seal(f.candidate)
                with self.assertRaises(Exception): f.run()
                self.assertEqual((len(f.loads), len(f.selections), f.transport.calls), (0, 0, 0))

    def test_decimal_headroom_all_levels_and_no_double_count(self):
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            c = f.candidate
            view = te.budget_view(c, Decimal("0.46"), require_pair=True)
            self.assertEqual(Decimal(view["available_usd"]["phase"]), Decimal("1.54"))
            self.assertEqual(Decimal(view["overall_other_usd"]), Decimal("20.42"))
            self.assertEqual(Decimal(view["available_usd"]["overall"]), Decimal("99.12"))
            self.assertEqual(Decimal(view["available_usd"]["secondary"]), Decimal("55.42"))
            with self.assertRaises(te.TemporalStop):
                te.budget_view(c, Decimal("0.460000000001"), require_pair=True)
            for bucket, amount in (("overall_only", "98.05"), ("secondary", "54.35")):
                altered = deepcopy(c)
                altered["budget"]["positions_excluding_current_phase"].append({"id": "artificial-other",
                    "bucket": bucket, "known_usd": amount, "remaining_commitment_usd": "0", "protected": False})
                f.candidate = te.seal(altered)
                with self.assertRaises(te.TemporalStop):
                    te.budget_view(f.candidate, Decimal(0), require_pair=True)
                with self.assertRaises(te.TemporalStop): f.run()
                self.assertEqual((len(f.loads), f.transport.calls), (0, 0))
            for change in ("move", "duplicate", "current", "unresolved", "pending"):
                altered = deepcopy(c)
                positions = altered["budget"]["positions_excluding_current_phase"]
                if change == "move": positions[0]["bucket"] = "secondary"
                if change == "duplicate": positions.append(deepcopy(positions[0]))
                if change == "current": positions.append(dict(positions[0], id=te.NAMESPACE, protected=False))
                if change == "unresolved": altered["budget"]["unresolved_other_positions"] = True
                with self.subTest(change=change), self.assertRaises(te.TemporalStop):
                    te.budget_view(altered, Decimal(0), pending=Decimal(".14") if change == "pending" else Decimal(0))

    def test_phase_boundary_stops_before_next_pair_loader(self):
        for price, permitted_pairs in (("0.0575", 2), ("0.057500000000125", 1)):
            with self.subTest(price=price), TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                original = f.transport
                def priced(endpoint, body):
                    status, raw = original(endpoint, body)
                    value = json.loads(raw)
                    value["usage"]["cost"] = price
                    return status, encoded(value)
                f.run(transport=priced)
                with self.assertRaises(te.TemporalStop): f.run(10, transport=priced)
                self.assertEqual(len(f.loads), permitted_pairs)
                self.assertEqual(original.calls, permitted_pairs * 8)

    def test_canonical_namespace_lock_changed_plan_or_folder_no_fresh_budget(self):
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.run()
            before = f.transport.calls
            with self.assertRaises(te.TemporalStop): f.run(10, folder=f.root / "different")
            with self.assertRaises(te.TemporalStop): f.run(10, control=f.root / "different-control")
            with te.temporal_lock(f.control), self.assertRaises(te.TemporalStop): f.run(10)
            f.candidate = te.seal(dict(f.candidate, pending=["changed-binding"]))
            with self.assertRaises(te.TemporalStop): f.run(10)
            self.assertEqual(f.transport.calls, before)

    def test_known_f01_zero_quality_known_cost_other_arm_fresh(self):
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.transport = FakeTransport(fail_at=1, mode="length")
            state = f.run()
            row = state["observations"][0]
            failed_index = f.plan["pairs"][0]["round_order"][0] - 1
            self.assertEqual(row["status"][failed_index], "model_failed")
            self.assertEqual(row["em"][failed_index], 0)
            self.assertEqual(row["f1"][failed_index], 0)
            self.assertEqual(row["cost_usd"][failed_index], "0.0000108")
            self.assertEqual(row["status"][1 - failed_index], "completed")
            self.assertEqual(len(f.selections), 1)
            self.assertEqual(f.transport.calls, 1 + (5 if failed_index == 0 else 3))

    def test_unknown_transport_interruption_overbound_and_partial_pair_never_retry(self):
        for mode in ("unknown", "transport", "interrupt", "http", "over"):
            with self.subTest(mode=mode), TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                f.transport = FakeTransport(fail_at=2, mode=mode)
                with self.assertRaises(BaseException): f.run()
                self.assertEqual(f.transport.calls, 2)
                with self.assertRaises(Exception): f.run()
                with self.assertRaises(Exception):
                    te.checkpoint_temporal(f.candidate, f.plan, f.manifest, f.allocation,
                                          **f.args(), checkpoint=f.checkpoint)
                self.assertEqual(f.transport.calls, 2)
                self.assertFalse(list((f.folder / "pairs").glob("*-complete.json")))
                if mode in ("unknown", "transport", "interrupt"):
                    ledger = [json.loads(s) for s in (f.folder / "budget.jsonl").read_text().splitlines()]
                    self.assertEqual(ledger[-1].get("usage", {}).get("cost_usd"), None)
                    self.assertTrue(any(r.get("reservation_usd") == "0.14" for r in ledger))

    def test_duplicate_generation_after_resume_stops_and_clean_resume_does_not_repeat(self):
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.run()
            f.transport = FakeTransport()  # Reuses fake-gen-1: must be rejected across processes.
            with self.assertRaises(Exception): f.run(10)
            self.assertEqual(f.transport.calls, 1)
            self.assertEqual(len(f.loads), 2)
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.run()
            f.transport = FakeTransport()
            f.transport.calls = 8
            state = f.run(10)
            self.assertEqual(state["completed_pairs"], 10)
            self.assertEqual(len(set(f.loads)), 10)
            self.assertEqual(f.transport.calls, 80)

    def test_missing_backup_requires_additive_checkpoint_and_time_binding_stays_fixed(self):
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            def failure(_): raise OSError("artificial backup failure")
            with self.assertRaises(OSError): f.run(checkpoint=failure)
            self.assertEqual(f.inspect()["completed_pairs"], 1)
            with self.assertRaises(Exception): f.run(10)
            self.assertEqual(f.transport.calls, 8)
            te.checkpoint_temporal(f.candidate, f.plan, f.manifest, f.allocation,
                                  **f.args(), checkpoint=f.checkpoint)
            f.clock = lambda: 1001
            with self.assertRaises(te.TemporalStop): f.run(10)
            self.assertEqual(len(f.loads), 1)
            f.clock = lambda: 100
            self.assertEqual(f.run(10)["completed_pairs"], 10)

    def test_complete_nonhold_prefix_gets_new_receipt_then_resumes_next_hold(self):
        with TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.run()
            def interrupted_clock():
                if f.transport.calls >= 16:
                    raise KeyboardInterrupt("artificial interruption between whole pairs")
                return 100
            with self.assertRaises(KeyboardInterrupt): f.run(10, clock=interrupted_clock)
            self.assertEqual(f.inspect()["completed_pairs"], 2)
            with self.assertRaises(Exception): f.run(10)
            te.checkpoint_temporal(f.candidate, f.plan, f.manifest, f.allocation,
                                  **f.args(), checkpoint=f.checkpoint)
            self.assertEqual(f.run(10)["completed_pairs"], 10)
            self.assertEqual(len(set(f.loads)), 10)
            self.assertEqual(f.transport.calls, 80)

    def test_round_result_backup_and_unclaimed_file_tamper_blocks_resume(self):
        for kind in ("round", "result", "backup", "extra"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                f.run()
                if kind in ("round", "result"):
                    suffix = "-binding.json" if kind == "round" else "-result.json"
                    path = next((f.folder / "slots").glob("*" + suffix))
                    value = json.loads(path.read_text())
                    value["rounds" if kind == "round" else "em"] = 99
                    path.write_bytes(encoded(value))
                elif kind == "backup": next((f.folder / "receipts").glob("*.zip")).write_bytes(b"broken")
                else: (f.folder / "stray.txt").write_text("unclaimed")
                with self.assertRaises(Exception): f.run(10)
                self.assertEqual(f.transport.calls, 8)
                self.assertEqual(len(f.loads), 1)


if __name__ == "__main__":
    unittest.main()
