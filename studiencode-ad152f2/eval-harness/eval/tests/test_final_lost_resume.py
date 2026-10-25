"""D-072 invented multi-segment evidence only; no network, model or real tasks.

The kernel-dev runner snapshots the exact sources before each process and sets
Z50_TEST_EVIDENCE_DIR so every artificial success, failure and partial survives.
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
from study_preparation import final_lost_resume as lost, final_rate_resume as rate
from study_preparation import final_recovery as fr, final_resume as previous
from study_preparation import final_execution as fe, final_preflight as fp
from study_preparation.final_plan import canonical_hash
from tests.test_final_preflight import trial_directory
from tests.test_final_rate_resume import RateFixture, source_backup


class LostFixture:
    def __init__(self, directory, *, inherited_zero_retries=0, partial_successful=3):
        self.root = Path(directory).resolve()
        self.r = r = RateFixture(directory, remaining=4)
        r.initialize()
        r.checkpoint()
        self.old_checkpoint = r.run(r.preserved + 1)
        self.prefix = self.old_checkpoint["completed_blocks"]
        first = r.transport.calls + partial_successful + 1
        for offset in range(inherited_zero_retries):
            r.transport.actions[first + offset] = "zero429"
        r.transport.actions[first + inherited_zero_retries] = "transport"
        try:
            r.run(self.prefix + 1)
        except BudgetStop:
            pass
        else:
            raise AssertionError("invented D-071 unknown stop was not produced")
        self.old_inventory = fr.original_inventory(r.folder)
        self.folder = self.root / "lost-segment"
        self.recovery = self.root / "lost-recovery"
        self.report = lost.prepare_recovery(r.f.candidate, r.f.plan, previous_folder=r.folder,
            expected_previous_activation_sha256=r.activation_hash, inventory=self.old_inventory,
            expected_inventory_sha256=canonical_hash(self.old_inventory), output=self.recovery,
            recovery_id="invented-048002", clock=r.clock)
        self.extra_source = self.root / "lost-bound-additional.py"
        self.extra_source.write_text("# invented immutable source\n")
        paths = (lost.__file__, rate.__file__, previous.__file__, fr.__file__, __file__, self.extra_source)
        self.sources = {str(Path(path).resolve()): file_hash(path) for path in paths}
        backup = source_backup(self.root / "lost-sources.zip", self.sources, lost.source_members(self.sources))
        self.activation = lost.make_activation(r.f.candidate, r.f.plan, folder=self.folder,
            control=r.f.control, recovery_folder=self.recovery,
            expected_manifest_sha256=self.report["manifest_sha256"], resume_id="invented-D072",
            source_files=self.sources, source_backup=backup, checkpoint=self.backup,
            approval_reference="invented exact D-072 authorization, no live release", clock=r.clock)
        self.activation_hash, self.backups = canonical_hash(self.activation), 0

    def args(self):
        return dict(folder=self.folder, control=self.r.f.control,
                    expected_activation_sha256=self.activation_hash, clock=self.r.clock)

    def initialize(self):
        return lost.initialize_resume(self.r.f.candidate, self.r.f.plan, **self.args(),
            recovery_folder=self.recovery, expected_manifest_sha256=self.report["manifest_sha256"], activation=self.activation)

    def backup(self, state):
        path = self.folder / "receipts" / f"invented-lost-backup-{self.backups:04d}.zip"
        self.backups += 1
        with ZipFile(path, "x") as archive:
            for name in state["evidence"]:
                archive.write(self.folder / name, name)
        result = {"path": str(path), "sha256": file_hash(path), "members": state["evidence"]}
        fp.verify_archive(result, state["evidence"])
        return result

    def checkpoint(self):
        return lost.checkpoint_resume(self.r.f.candidate, self.r.f.plan, **self.args(), checkpoint=self.backup)

    def run(self, end):
        return lost.run_section(self.r.f.candidate, self.r.f.plan, **self.args(), section_end=end,
            loader=self.r.f.loader, spatial_selector=self.r.f.spatial_selector,
            transport=self.r.transport, checkpoint=self.backup, sleep=self.r.sleep)

    def inspect(self):
        return lost.inspect_resume(self.r.f.candidate, self.r.f.plan, **self.args())


class FinalLostResumeTests(unittest.TestCase):
    def ready(self, directory, **kwargs):
        fixture = LostFixture(directory, **kwargs)
        fixture.initialize()
        fixture.checkpoint()
        return fixture

    def test_exact_three_replays_single_replacement_full_rows_costs_and_original_preservation(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            initial = f.inspect()
            self.assertEqual(initial["rows"], f.old_checkpoint["rows"])
            self.assertEqual((initial["completed_blocks"], initial["new_budget"]["calls"]), (3, 0))
            self.assertEqual(f.report["partial_successful_calls"], 3)
            before, loads, selections = f.r.transport.calls, len(f.r.f.loads), len(f.r.f.selections)
            state = f.run(4)
            self.assertEqual((f.r.transport.calls - before, len(state["rows"])), (11, 8))
            self.assertEqual((len(f.r.f.loads), len(f.r.f.selections)), (loads, selections))
            self.assertEqual(state["rows"][:6], initial["rows"])
            maps = [fp.read_json(p) for p in sorted((f.folder / "mapping").glob("*.json"))]
            self.assertEqual(len(maps), 14)
            self.assertTrue(all(m["response_origin"].startswith("artificial-D071:physical:") for m in maps[:3]))
            self.assertEqual(sum(m["replacement_of_unknown"] is not None for m in maps), 1)
            binding = state["physical_attempts"][0]["binding"]
            self.assertEqual(binding["retry"], 1)
            self.assertEqual(binding["replacement_of_unknown"], f.report["lost"]["physical_attempt_id"])
            self.assertIsNone(binding["previous_received_at"])
            self.assertIsNone(binding["not_before"])
            old_number = f.report["lost"]["physical_calls"]
            self.assertEqual((f.folder / "provider/000001-request.json").read_bytes(),
                             (f.r.folder / "provider" / f"{old_number:06d}-request.json").read_bytes())
            self.assertEqual(state["budget"]["held_reservation_usd"], "0.28")
            self.assertIsNone(state["budget"]["total_cost_usd"])
            self.assertEqual(len(state["budget"]["pending"]), 2)
            self.assertEqual(state["budget"]["pending"], state["cost_assumption"]["additional_charge_assumed_zero_for"])
            self.assertFalse(state["cost_assumption"]["provider_cost_confirmed"])
            self.assertEqual(Decimal(state["levels"]["available_usd"]["main"]),
                             Decimal("40") - Decimal(state["budget"]["known_cost_usd"]) - Decimal(".28"))
            self.assertEqual(fr.original_inventory(f.r.folder), f.old_inventory)
            self.assertEqual(fr.original_inventory(f.r.prior_folder), f.r.prior_inventory)
            self.assertEqual(fr.original_inventory(f.r.f.folder), f.r.original_inventory)
            self.assertEqual(f.inspect()["state_sha256"], state["state_sha256"])
            activation, context = lost._load(f.r.f.candidate, f.r.f.plan, f.folder,
                f.r.f.control, f.activation_hash, f.r.clock)
            _, _, replay = lost._inspect(f.r.f.candidate, f.r.f.plan, f.folder,
                activation, f.activation_hash, *context)
            replay.transport = f.r.transport
            before_replay = f.r.transport.calls
            replay(context[2]["partial"][-1].request)
            self.assertEqual(f.r.transport.calls, before_replay)
            with self.assertRaises(fp.StudyStop):
                replay(context[2]["partial"][-1].request)
            self.assertEqual(f.r.transport.calls, before_replay)
            f.run(5)
            final = f.run(6)
            rows = lost.collect_panel(f.r.f.candidate, f.r.f.plan, **f.args())
            self.assertEqual(len(rows), 12)
            self.assertTrue(final["complete"])
            self.assertEqual(sum((Decimal(r["cost_usd"]) for r in rows), Decimal(0)),
                             Decimal(final["budget"]["known_cost_usd"]))
            self.assertEqual(final["budget"]["calls"], f.r.transport.calls)
            self.assertEqual(final["rate_summary"]["authorized_unknown_replacements"], 1)

    def test_replacement_ordinal_continues_then_only_remaining_zero429_retries(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            before, start = f.r.transport.calls, f.r.clock()
            f.r.transport.actions.update({before + 1: "zero429", before + 2: "zero429"})
            state = f.run(4)
            records = state["physical_attempts"][:3]
            self.assertEqual([r["binding"]["retry"] for r in records], [1, 2, 3])
            self.assertEqual([r["binding"]["wait_elapsed_seconds"] for r in records], [0, 60, 120])
            self.assertEqual([r["binding"]["not_before"] for r in records], [None, start + 60, start + 180])
            self.assertEqual([r["outcome"] for r in records], ["rate_limited", "rate_limited", "completed"])
            self.assertEqual(state["rate_summary"]["authorized_unknown_replacements"], 1)
            self.assertEqual(state["additional_rate_retries"], 2)
            for journal in (f.folder / "blocks").glob("*/*/journal.jsonl"):
                self.assertNotIn("INVENTED_ERROR_PARTIAL_NEVER_AS_ANSWER", journal.read_text())

    def test_inherited_zero429_before_unknown_cannot_reset_count(self):
        with trial_directory() as directory:
            f = self.ready(directory, inherited_zero_retries=2)
            self.assertEqual(f.report["lost"]["retry"], 2)
            before = f.r.transport.calls
            f.r.transport.actions[before + 1] = "zero429"
            with self.assertRaises(fp.StudyStop):
                f.run(4)
            self.assertEqual(f.r.transport.calls, before + 1)
            binding = fp.read_json(f.folder / "provider/000001-binding.json")
            self.assertEqual(binding["retry"], 3)
            with self.assertRaises(fp.StudyStop):
                f.run(4)
            self.assertEqual(f.r.transport.calls, before + 1)

    def test_three_new_zero429s_stop_permanently_before_fourth_physical_dispatch(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            before = f.r.transport.calls
            f.r.transport.actions.update({before + i: "zero429" for i in (1, 2, 3, 4)})
            with self.assertRaises(fp.StudyStop):
                f.run(4)
            self.assertEqual(f.r.transport.calls, before + 3)
            self.assertFalse(fp.read_json(f.folder / "STOP.json")["retry_allowed"])
            with self.assertRaises(fp.StudyStop):
                f.inspect()
            with self.assertRaises(Exception):
                f.initialize()

    def test_any_new_unknown_or_noneligible_error_stops_without_second_unknown_replacement(self):
        for action in ("transport", "unknown_cost", "positive_cost", "positive_tokens", "other_error", "duplicate"):
            with self.subTest(action=action), trial_directory() as directory:
                f = self.ready(directory)
                before = f.r.transport.calls
                f.r.transport.actions[before + 1] = action
                with self.assertRaises(Exception):
                    f.run(4)
                self.assertEqual(f.r.transport.calls, before + 1)
                self.assertTrue((f.folder / "STOP.json").exists())
                with self.assertRaises(Exception):
                    f.run(4)
                self.assertEqual(f.r.transport.calls, before + 1)

    def test_new_regular_requests_retain_original_30_60_120_policy_in_both_arms(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            f.run(4)
            before = f.r.transport.calls
            f.r.transport.actions.update({before + 1: "zero429", before + 2: "zero429", before + 3: "zero429",
                                          before + 11: "zero429"})
            state = f.run(5)
            records = state["physical_attempts"][11:]
            self.assertEqual([r["binding"]["retry"] for r in records[:4]], [0, 1, 2, 3])
            self.assertEqual([r["binding"]["wait_elapsed_seconds"] for r in records[:4]], [0, 30, 60, 120])
            self.assertEqual(len({r["binding"]["logical_attempt_id"] for r in records if r["binding"]["retry"] > 0}), 2)

    def test_inventory_stop_request_and_logical_mapping_damage_rejected_before_preparation(self):
        for kind in ("stop", "request", "mapping", "extra", "ledger"):
            with self.subTest(kind=kind), trial_directory() as directory:
                f = self.ready(directory)
                number = f.report["lost"]["physical_calls"]
                path = {"stop": f.r.folder / "STOP.json", "request": f.r.folder / "provider" / f"{number:06d}-request.json",
                        "mapping": f.r.folder / "mapping/000001.json", "extra": f.r.folder / "unexpected.json",
                        "ledger": f.r.folder / "provider/budget.jsonl"}[kind]
                if kind == "stop":
                    value = fp.read_json(path)
                    value["block_number"] += 1
                    path.write_bytes(encoded(value))
                else:
                    path.write_bytes(path.read_bytes() + b" " if path.exists() else b"{}")
                inventory = fr.original_inventory(f.r.folder)
                with self.assertRaises(Exception):
                    lost.prepare_recovery(f.r.f.candidate, f.r.f.plan, previous_folder=f.r.folder,
                        expected_previous_activation_sha256=f.r.activation_hash, inventory=inventory,
                        expected_inventory_sha256=canonical_hash(inventory), output=f.root / "bad-preparation",
                        recovery_id="invented-tampering", clock=f.r.clock)

    def test_sources_claim_lock_initial_backup_and_first_hold_remain_gates(self):
        with trial_directory() as directory:
            f = LostFixture(directory)
            before = f.r.transport.calls
            with fe.study_lock(f.r.f.control), self.assertRaises(fp.StudyStop):
                f.initialize()
            f.initialize()
            with self.assertRaises(Exception):
                f.initialize()
            with self.assertRaises(FileNotFoundError):
                f.run(4)
            f.checkpoint()
            with self.assertRaises(fp.StudyStop):
                f.run(5)
            self.assertEqual(f.r.transport.calls, before)
            f.extra_source.write_text("# changed artificial source\n")
            with self.assertRaises(Exception):
                f.run(4)
            self.assertEqual(f.r.transport.calls, before)

    def test_changed_or_duplicate_replay_request_stops_before_model_work(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), trial_directory() as directory:
                f = self.ready(directory)
                original, seen = lost.execute, []
                def changed(task, config, send, **kwargs):
                    def wrapped(request):
                        if duplicate:
                            if not seen:
                                seen.append(request)
                                send(request)
                            return send(seen[0])
                        return send(replace(request, instruction=request.instruction + " changed"))
                    return original(task, config, wrapped, **kwargs)
                before = f.r.transport.calls
                with patch.object(lost, "execute", changed), self.assertRaises(Exception):
                    f.run(4)
                self.assertEqual(f.r.transport.calls, before)

    def test_both_reserves_boundary_and_calendar_wait_guard(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            with self.assertRaises(fp.StudyStop):
                lost._levels(f.r.f.candidate, Decimal("39.59"), Decimal(0), reserve_calls=1)
            allowed = lost._levels(f.r.f.candidate, Decimal("39.58"), Decimal(0), reserve_calls=1)
            self.assertEqual(Decimal(allowed["available_usd"]["main"]), Decimal(".14"))
            f.r.clock.value = f.r.f.candidate["calendar"]["end_epoch"] - 1
            before = f.r.transport.calls
            f.r.transport.actions[before + 1] = "zero429"
            with self.assertRaises(fp.StudyStop):
                f.run(4)
            self.assertEqual(f.r.transport.calls, before + 1)

    def test_saved_replacement_binding_or_billing_tampering_is_rejected(self):
        for part, key in (("binding", "retry"), ("binding", "replacement_of_unknown"), ("billing", "generation_id")):
            with self.subTest(part=part, key=key), trial_directory() as directory:
                f = self.ready(directory)
                f.run(4)
                path = f.folder / "provider" / f"000001-{part}.json"
                value = fp.read_json(path)
                value[key] = 0 if key == "retry" else "invented-forgery"
                path.write_bytes(encoded(value))
                with self.assertRaises(Exception):
                    f.inspect()

    def test_no_secondary_or_incomplete_panel_and_assumption_covers_both(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            with self.assertRaises(ValueError):
                lost.collect_panel(f.r.f.candidate, f.r.f.plan, **f.args())
            with self.assertRaises(fp.StudyStop):
                lost.collect_panel(f.r.f.candidate, f.r.f.plan, "R", **f.args())
            value = deepcopy(f.activation)
            value["author_assumption"]["additional_charge_assumed_zero_for"].pop()
            with self.assertRaises(fp.StudyStop):
                lost._gate(f.r.f.candidate, f.r.f.plan, value, canonical_hash(value),
                           f.folder, f.r.f.control, f.r.clock)


if __name__ == "__main__":
    unittest.main()
