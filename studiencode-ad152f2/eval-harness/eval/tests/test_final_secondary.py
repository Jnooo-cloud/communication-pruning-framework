"""Bounded artificial integration cases; preserve all trials via Z50 evidence dir.

No monkeypatch of plan, original execution prefix, arms, analysis or provider.
Fixtures explicitly ADOPT an invented P completion and start actual native R.
The coordinating executor, not the author of these tests, runs this module.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import shutil
import unittest

from communication_pruning.openrouter import encoded
from communication_pruning.study import file_hash
from study_preparation import final_secondary as secondary, final_execution as native, final_preflight as gate
from study_preparation.final_analysis import analyze_panel as original_analysis
from study_preparation.final_plan import canonical_hash
from tests.test_final_preflight import Fixture, trial_directory


class SecondaryFixture(Fixture):
    def __init__(self, root, *, counts=None, fail_mode=None, fail_at=None):
        super().__init__(root, counts=counts or {"P": 2, "R": 1, "T": 1, "F": 1})
        self.original_folder = self.root / "invented-P"
        self.original_folder.mkdir()
        self.folder = self.root / "secondary"
        self.witness = self.root / "secondary-witness"
        self.transport.mode, self.transport.fail_at = fail_mode, fail_at
        self.control.mkdir()
        native._claim(self.candidate, self.plan, self.original_folder, self.control, create=True)
        self.analysis_contract = self.file("analysis-contract.json", {"study_id": self.plan["study_id"],
            "seed_base": self.plan["seed_base"], "bootstrap_repetitions": 19999,
            "secondary_costs": "descriptive_only", "primary_bootstrap_seed": 123})
        self.predecessor = {"schema": "z52-adopted-P/v1", "mode": "artificial_only",
            "plan_hash": self.plan["plan_hash"], "scientific_candidate_sha256": self.candidate["sha256"],
            "original_execution_binding_sha256": gate.execution_binding(self.candidate),
            "completed_blocks": self.plan["counts"]["P"], "rows": self.plan["counts"]["P"] * 2,
            "review_complete": True, "backup_complete": True, "original_folder": str(self.original_folder),
            "control_snapshot": secondary._control_snapshot(self.control),
            "accounting": deepcopy(secondary.HISTORICAL_ACCOUNTING)}
        for key in ("state", "analysis", "review", "backup"):
            self.predecessor[key] = self.file("invented-P-" + key + ".json", {
                "artificial_only": True, "kind": key, "P_blocks": self.plan["counts"]["P"]})
        self.binding = secondary.prepare_binding(self.candidate, self.plan, predecessor=self.predecessor,
            folder=self.folder, control=self.control, witness=self.witness,
            owner="artificial-executor", analysis_contract=self.analysis_contract)
        self.original_plan_hash = canonical_hash(self.plan)

    def initialize(self):
        return secondary.initialize(self.binding, self.candidate, self.plan, **self.args())

    def coverage(self, amount="100"):
        budget = secondary._budget(self.binding, self.plan, self.folder, existing=True)
        return {"binding_sha256": self.binding["sha256"], "origin": "artificial_fixture",
            "observed_epoch": 90, "valid_until_epoch": 1000, "available_usd": amount,
            "native_cost_at_observation_usd": str(budget.cost)}

    def run(self, end, *, coverage=None):
        return secondary.run_section(self.binding, self.candidate, self.plan, **self.args(),
            section_end=end, coverage=self.coverage() if coverage is None else coverage, **self.dependencies())

    def inspect(self):
        return secondary.inspect_study(self.binding, self.candidate, self.plan, **self.args())

    def confirm(self, state):
        review = self.file("hold-review-" + str(state["completed_blocks"]) + ".json", {
            "binding_sha256": self.binding["sha256"], "state_sha256": state["state_sha256"],
            "accepted": True, "reviewer": "artificial-separate-reviewer", "not_implementation_author": True})
        receipt = gate.read_json(secondary._receipt_path(self.folder, state))
        backup = self.file("hold-backup-" + str(state["completed_blocks"]) + ".json", {
            "binding_sha256": self.binding["sha256"], "state_sha256": state["state_sha256"], "accepted": True,
            "archive_sha256": receipt["backup"]["sha256"], "members": state["evidence"],
            "full_reread": True, "destination": "artificial_local"})
        return secondary.confirm_hold(self.binding, self.candidate, self.plan, **self.args(), review=review, backup=backup)

    def analyze(self, panel):
        return secondary.analyze_panel(self.binding, self.candidate, self.plan, panel, **self.args())

    def close(self, panel, evidence):
        review = self.file("panel-review-" + panel + ".json", {"binding_sha256": self.binding["sha256"],
            "panel": panel, "analysis_sha256": evidence["sha256"], "reviewer": "artificial-separate-reviewer",
            "not_implementation_author": True, "accepted": True})
        prepared = secondary.prepare_panel_backup(self.binding, self.candidate, self.plan, panel,
            **self.args(), checkpoint=self.checkpoint)
        remote = self.file("panel-remote-" + panel + ".json", {"artificial_only": True,
            "binding_sha256": self.binding["sha256"], "panel": panel, "analysis_sha256": evidence["sha256"],
            "archive_sha256": prepared["backup"]["sha256"], "members": prepared["backup"]["members"],
            "full_reread": True, "accepted": True, "destination": "artificial_local"})
        return secondary.close_panel(self.binding, self.candidate, self.plan, panel,
            **self.args(), review=review, remote_backup=remote)


class SecondaryTests(unittest.TestCase):
    def test_native_R_T_F_first_block_original_methods_analysis_and_one_cost_book(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            old_claim = (f.control / (gate.NAMESPACE + ".claim.json")).read_bytes()
            self.assertTrue(f.initialize()["next_block"].endswith(":R:00000"))
            for panel, end in zip(secondary.PANELS, (3, 4, 5)):
                state = f.run(end)
                self.assertEqual(state["completed_blocks"], end)
                self.assertEqual(state["secondary_completed_blocks"], end - 2)
                rows = secondary.collect_panel(f.binding, f.candidate, f.plan, panel, **f.args())
                self.assertEqual(len(rows), len(native.ARMS[panel]))
                self.assertEqual({row["arm"] for row in rows}, set(native.ARMS[panel]))
                f.confirm(state)
                evidence = f.analyze(panel)
                self.assertEqual(gate.read_json(evidence["path"]), original_analysis(f.plan, panel, rows, bootstrap_seed=123))
                f.close(panel, evidence)
            self.assertTrue(state["complete"])
            self.assertEqual(canonical_hash(f.plan), f.original_plan_hash)
            self.assertEqual((f.control / (gate.NAMESPACE + ".claim.json")).read_bytes(), old_claim)
            self.assertEqual(len(f.loads), 3)
            self.assertEqual(len(f.time_selections), 1)
            self.assertEqual(f.inspect()["budget"]["calls"], f.transport.calls)
            text = (f.folder / "budget.jsonl").read_text()
            self.assertNotIn(":P:", text)
            self.assertEqual(len(list(f.folder.glob("*budget*"))), 1)
            self.assertIsNone(state["levels"]["actual_total_cost_usd"])
            self.assertEqual(state["levels"]["predecessor"], secondary.HISTORICAL_ACCOUNTING)
            self.assertEqual(len(gate.read_json(f.folder / "blocks/000000/S-k/direct-complete.json")["vote"]["classes"]), 5)
            bodies = json.dumps(f.transport.bodies)
            self.assertNotIn("PRIVATE_FAKE_GOLD", bodies)
            self.assertNotIn("synthetic-family", bodies)
            self.assertEqual({r["rounds"] for r in state["rows"] if r["arm"] == "Q-TF"}, {1})
            self.assertTrue(all(r["failed_role"] is not None for r in state["rows"] if r["arm"] in ("Qf", "Ff")))

    def test_multiple_T_and_F_holds_allow_only_append_only_native_ledger_growth(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory, counts={"P": 2, "R": 1, "T": 2, "F": 2})
            f.initialize()
            closure_prefixes = {}
            for panel, marks in (("R", (3,)), ("T", (4, 5)), ("F", (6, 7))):
                for mark in marks:
                    f.q = f"C{mark - 1:02d}"
                    f.temporal = 1 if mark == 4 else 2
                    state = f.run(mark)
                    self.assertEqual(state["completed_blocks"], mark)
                    f.confirm(state)
                    # Prior panels remain valid even after new requests append
                    # to the sole native ledger at each later control hold.
                    for previous, prefix in closure_prefixes.items():
                        self.assertGreater((f.folder / "budget.jsonl").stat().st_size, prefix["bytes"])
                        secondary._verify_ledger_prefix(f.folder, prefix)
                        with native.study_lock(f.control):
                            secondary._verify_panel_closeout(f.binding, f.candidate, f.plan, f.folder, previous)
                evidence = f.analyze(panel)
                f.close(panel, evidence)
                closure = gate.read_json(f.folder / "panels" / panel / "complete.json")
                self.assertNotIn("budget.jsonl", closure["evidence"])
                self.assertIn("budget.jsonl", closure["backup"]["members"])
                closure_prefixes[panel] = closure["ledger_prefix"]
                for name in closure["evidence"]:
                    parts = Path(name).parts
                    if parts[0] == "blocks":
                        self.assertGreaterEqual(len(parts), 3)
                        block = secondary._blocks(f.plan)[int(parts[1])]
                        self.assertEqual(block["panel"], panel)
                        if len(parts) == 3 and parts[2] == "complete.json":
                            self.assertEqual(gate.read_json(f.folder / name)["block"], block)
            self.assertTrue(state["complete"])
            self.assertEqual(len(f.loads), 5)
            time_rows = [r for r in state["rows"] if r["arm"] == "Q-ST"]
            self.assertEqual([r["rounds"] for r in time_rows], [1, 2])
            self.assertEqual([r["configuration"] for r in time_rows], ["C03", "C04"])
            self.assertEqual({r["configuration"] for r in state["rows"] if r["arm"] in ("F", "Fc", "Ff")}, {"C01"})
            # Preserve both original and changed bytes as artificial evidence.
            tampered = f.root / "tampered-ledger-prefix"
            tampered.mkdir()
            original = (f.folder / "budget.jsonl").read_bytes()
            (tampered / "original-budget.jsonl").write_bytes(original)
            changed = original.replace(b'"time": "', b'"time": "changed-', 1)
            self.assertNotEqual(original, changed)
            (tampered / "budget.jsonl").write_bytes(changed)
            for prefix in closure_prefixes.values():
                with self.assertRaises(gate.StudyStop):
                    secondary._verify_ledger_prefix(tampered, prefix)

    def test_original_global_hold_rejects_wrong_local_prefix_and_duplicate(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            f.initialize()
            for wrong in (0, 1, 2, 4, True):
                with self.assertRaises(Exception):
                    f.run(wrong)
            self.assertEqual(f.transport.calls, 0)
            state = f.run(3)
            calls = f.transport.calls
            with self.assertRaises(Exception):
                f.run(3)
            self.assertEqual(f.transport.calls, calls)
            self.assertEqual(state["rows"][0]["panel"], "R")

    def test_panel_analysis_hold_review_and_backup_are_separate_gates(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            f.initialize()
            with self.assertRaises(Exception):
                f.analyze("R")
            state = f.run(3)
            calls = f.transport.calls
            with self.assertRaises(Exception):
                f.run(4)
            f.confirm(state)
            with self.assertRaises(Exception):
                f.run(4)
            evidence = f.analyze("R")
            with self.assertRaises(Exception):
                f.run(4)
            f.close("R", evidence)
            self.assertEqual(f.transport.calls, calls)
            f.run(4)

    def test_panel_transition_requires_exact_separate_analysis_archive_receipt(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            f.initialize()
            state = f.run(3)
            f.confirm(state)
            analysis = f.analyze("R")
            prepared = secondary.prepare_panel_backup(f.binding, f.candidate, f.plan, "R",
                **f.args(), checkpoint=f.checkpoint)
            review = f.file("R-review.json", {"binding_sha256": f.binding["sha256"], "panel": "R",
                "analysis_sha256": analysis["sha256"], "reviewer": "artificial-separate-reviewer",
                "not_implementation_author": True, "accepted": True})
            # The earlier hold backup omitted analysis.json, so it cannot stand
            # in for this panel-specific analysis archive.
            hold = gate.read_json(secondary._receipt_path(f.folder, state))["backup"]
            wrong = f.file("R-wrong-remote.json", {"artificial_only": True,
                "binding_sha256": f.binding["sha256"], "panel": "R", "analysis_sha256": analysis["sha256"],
                "archive_sha256": hold["sha256"], "members": hold["members"],
                "accepted": True, "full_reread": True, "destination": "artificial_local"})
            with self.assertRaises(gate.StudyStop):
                secondary.close_panel(f.binding, f.candidate, f.plan, "R", **f.args(), review=review, remote_backup=wrong)
            with self.assertRaises(Exception):
                f.run(4)
            good = f.file("R-exact-remote.json", {"artificial_only": True,
                "binding_sha256": f.binding["sha256"], "panel": "R", "analysis_sha256": analysis["sha256"],
                "archive_sha256": prepared["backup"]["sha256"], "members": prepared["backup"]["members"],
                "accepted": True, "full_reread": True, "destination": "artificial_local"})
            secondary.close_panel(f.binding, f.candidate, f.plan, "R", **f.args(), review=review, remote_backup=good)
            f.run(4)

    def test_same_shared_lock_excludes_old_and_new_writer(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            with native.study_lock(f.control):
                with self.assertRaises(gate.StudyStop):
                    f.initialize()
            f.initialize()
            with native.study_lock(f.control):
                with self.assertRaises(gate.StudyStop):
                    f.run(3)
            self.assertEqual(f.transport.calls, 0)

    def test_copied_folder_rebound_claim_and_changed_predecessor_never_dispatch(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            f.initialize()
            original = f.binding
            copied = f.root / "copied"
            shutil.copytree(f.folder, copied)
            f.folder = copied
            with self.assertRaises(Exception):
                f.run(3)
            f.binding = gate.seal({**original, "folder": str(copied)})
            with self.assertRaises(Exception):
                f.run(3)
            f.folder = Path(original["folder"])
            f.binding = deepcopy(original)
            f.binding["predecessor"]["completed_blocks"] = 0
            f.binding = gate.seal(f.binding)
            with self.assertRaises(Exception):
                f.run(3)
            self.assertEqual(f.transport.calls, 0)

    def test_budget_historical_unknowns_secondary_total_whole_blocks_and_account(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            view = secondary.accounting_view(f.predecessor, Decimal(0))
            self.assertEqual(view["available_usd"], {"overall": "57.84046236", "secondary": "55.65488651"})
            for cost in ("55.65488652", "57.84046237"):
                with self.assertRaises(Exception):
                    secondary.accounting_view(f.predecessor, Decimal(cost))
            for panel in secondary.PANELS:
                reserve = Decimal("0.14") * gate.MAX_CALLS[panel]
                secondary.accounting_view(f.predecessor, Decimal(0), reserve_calls=gate.MAX_CALLS[panel], account_available=str(reserve))
                with self.assertRaises(Exception):
                    secondary.accounting_view(f.predecessor, Decimal(0), reserve_calls=gate.MAX_CALLS[panel], account_available=str(reserve - Decimal("0.00000001")))
            altered = deepcopy(f.predecessor)
            altered["accounting"]["actual_total_cost_usd"] = "41.17953764"
            with self.assertRaises(Exception):
                secondary.accounting_view(altered, Decimal(0))
            f.initialize()
            with self.assertRaises(Exception):
                f.run(3, coverage=f.coverage("5.03999999"))
            self.assertEqual(f.transport.calls, 0)
            f.run(3, coverage=f.coverage("5.04"))

    def test_unknown_crash_duplicate_generation_overcost_persist_and_never_retry(self):
        for mode in ("unknown", "interrupt", "duplicate", "over"):
            with self.subTest(mode=mode), trial_directory() as directory:
                f = SecondaryFixture(directory, fail_mode=mode, fail_at=2 if mode == "duplicate" else 1)
                f.initialize()
                with self.assertRaises(BaseException):
                    f.run(3)
                calls = f.transport.calls
                self.assertTrue((f.folder / "STOP.json").is_file())
                self.assertTrue((f.folder / "blocks/000000/started.json").is_file())
                with self.assertRaises(Exception):
                    f.run(3)
                self.assertEqual(f.transport.calls, calls)
                # Deleting local STOP cannot clear the outside monotone witness.
                (f.folder / "STOP.json").unlink()
                with self.assertRaises(Exception):
                    f.run(3)
                self.assertEqual(f.transport.calls, calls)

    def test_regular_F01_failure_has_zero_quality_and_paid_cost_without_block_retry(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory, fail_mode="length", fail_at=1)
            f.initialize()
            state = f.run(3)
            failed = [r for r in state["rows"] if r["status"] == "model_failure"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["em"], 0)
            self.assertGreater(Decimal(failed[0]["cost_usd"]), 0)
            self.assertEqual(len(state["rows"]), 6)

    def test_witness_prevents_execution_tree_rollback(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            f.initialize()
            snapshot = f.root / "before-run"
            shutil.copytree(f.folder, snapshot)
            f.run(3)
            calls = f.transport.calls
            shutil.rmtree(f.folder)
            shutil.copytree(snapshot, f.folder)
            with self.assertRaises(Exception):
                f.run(3)
            self.assertEqual(f.transport.calls, calls)

    def test_numeric_row_complete_block_and_native_ledger_tampering_rejected(self):
        for target in ("row", "complete", "budget", "prefix"):
            with self.subTest(target=target), trial_directory() as directory:
                f = SecondaryFixture(directory)
                f.initialize()
                state = f.run(3)
                if target == "row":
                    path = f.folder / "blocks/000000/S/result.json"
                    value = gate.read_json(path)
                    value["cost_usd"] = "0"
                    path.write_bytes(encoded(value))
                elif target == "complete":
                    path = f.folder / "blocks/000000/complete.json"
                    value = gate.read_json(path)
                    value["rows"].pop()
                    path.write_bytes(encoded(value))
                elif target == "budget":
                    path = f.folder / "budget.jsonl"
                    path.write_bytes(path.read_bytes().replace(b'0.0000108', b'0.0000000'))
                else:
                    (f.folder / "blocks/000000").rename(f.folder / "blocks/000001")
                with self.assertRaises(Exception):
                    f.inspect()
                self.assertEqual(state["budget"]["calls"], f.transport.calls)

    def test_adopted_P_metadata_links_bind_state_review_backup_and_conditional_costs(self):
        # Invented metadata only. The immutable real-source identities are never
        # overridden, and the live wrapper must reject these artificial paths.
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            prior = deepcopy(f.predecessor)
            prior["state_sha256"] = "a" * 64
            prior["accounting"] = {"P_known_usd": "1.25", "unknown_originals": ["invented-1", "invented-2"],
                "unknown_original_reserve_usd": "0.28"}
            prior["original_report"] = f.file("invented-old-report.json", {"artificial_only": True})
            state = {"schema": "z51-resume-remote-hold/v1", "state_sha256": prior["state_sha256"],
                "completed_blocks": 2, "known_cost_usd": "1.25", "original_unknown_cost_preserved": True,
                "activation_sha256": "b" * 64, "unknown_attempts": [
                    {"physical_attempt_id": name, "provider_cost_usd": None, "reservation_usd": "0.14"}
                    for name in ("invented-1", "invented-2")]}
            def receipt(evidence):
                return {"verified": True, "repository": "Jnooo-cloud/masterarbeit-mas-pruning",
                    "sha256": evidence["sha256"], "original_path": evidence["path"]}
            backup, analysis_backup = receipt(prior["state"]), receipt(prior["analysis"])
            review = {"schema": "offline-P-closeout-adjudication/v1",
                "original_report_sha256": prior["original_report"]["sha256"], "original_report_preserved": True,
                "other_nine_checks_passed": True, "passed_with_documented_audit_scope_correction": True,
                "actual_live_paths": {"operation/BACKUP-CLEANUP-BLOCK.json": False, "live/STOP.json": False}}
            report = {"schema": "offline-P-closeout-audit/v1", "passed": False, "checks": [
                {"criterion": "terminal_P9040", "passed": True, "detail": {"status": "complete", "completed_blocks": 2}},
                {"criterion": "final_hold_identity", "passed": True,
                 "detail": {"state_sha256": prior["state_sha256"], "known_cost_usd": "1.25"}},
                {"criterion": "saved_analysis_identity", "passed": True, "detail": {"sha256": prior["analysis"]["sha256"]}},
                {"criterion": "four_unknown_original_costs_retained", "passed": True,
                 "detail": {"count": 2, "actual_total_cost_usd": None, "reserve_is_expense_or_upper_bound": False}},
                {"criterion": "no_current_stop_or_cleanup_block", "passed": False, "detail": ["invented old test marker"]}]}
            status = {"status": "complete", "completed_blocks": 2, "activation_sha256": state["activation_sha256"],
                "analysis": {**prior["analysis"], "remote": analysis_backup, "cost_inference_is_conditional": True}}
            records = {"state": state, "backup": backup, "review": review, "original_report": report,
                "status": status, "analysis_backup": analysis_backup}
            f.file("invented-linked-P-metadata.json", {"artificial_only": True, "prior": prior, "records": records})
            self.assertEqual(secondary._verify_predecessor_metadata_links(prior, records)["completed_blocks"], 2)
            with self.assertRaises(gate.StudyStop):
                secondary._verify_live_predecessor(prior)
            for changed in ("state", "backup", "review", "status", "analysis_backup", "unknown", "audit"):
                broken = deepcopy(records)
                if changed == "state":
                    broken["state"]["state_sha256"] = "c" * 64
                elif changed in ("backup", "analysis_backup"):
                    broken[changed]["sha256"] = "c" * 64
                elif changed == "review":
                    broken["review"]["original_report_sha256"] = "c" * 64
                elif changed == "status":
                    broken["status"]["completed_blocks"] = 1
                elif changed == "unknown":
                    broken["state"]["unknown_attempts"][0]["provider_cost_usd"] = "0"
                else:
                    broken["original_report"]["checks"][0]["passed"] = False
                f.file("invented-broken-P-" + changed + ".json", {"artificial_only": True, "records": broken})
                with self.subTest(disconnected=changed), self.assertRaises(gate.StudyStop):
                    secondary._verify_predecessor_metadata_links(prior, broken)

    def test_missing_actual_activation_rejects_before_any_loader_or_transport(self):
        with trial_directory() as directory:
            f = SecondaryFixture(directory)
            f.binding["mode"] = "authorized_execution"
            f.binding = gate.seal(f.binding)
            with self.assertRaises(Exception):
                f.initialize()
            self.assertEqual(f.loads, [])
            self.assertEqual(f.transport.calls, 0)


if __name__ == "__main__":
    unittest.main()
