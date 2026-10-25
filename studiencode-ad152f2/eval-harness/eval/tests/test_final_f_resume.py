"""D-073 tests use only invented five-segment evidence; no network or real tasks.

The kernel-dev runner binds recoverable source/config copies before the process
and retains every complete, rejected and partial fixture under its own run.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import unittest

from communication_pruning import phase_budget, rate_limit
from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study import file_hash
from study_preparation import final_execution as fe, final_preflight as fp
from study_preparation import final_f_resume as fresh, final_lost_resume as lost
from study_preparation import final_rate_resume as rate, final_resume as previous, final_recovery as fr
from study_preparation.final_plan import canonical_hash, make_plan
from tests import test_final_lost_resume as lost_tests, test_final_rate_resume as rate_tests
from tests.test_final_preflight import Fixture, trial_directory
from tests.test_final_rate_resume import FakeClock, ScriptedTransport, RateFixture, source_backup


class QOriginalRateFixture(RateFixture):
    """The frozen RateFixture setup with its original unknown deliberately in Q.

    This local fixture preserves the old class methods and all source bindings;
    only the invented initial prefix is selected to match D-069's Q arm.
    """
    def __init__(self, directory, *, prefix=1, completed_previous=1, remaining=2, partial_successful=9):
        if prefix < 1 or completed_previous < 1 or remaining < 1 or not 0 <= partial_successful < 14:
            raise ValueError("invalid artificial prefix/partial size")
        self.root = Path(directory).resolve()
        self.clock, self.transport = FakeClock(), ScriptedTransport()
        self.sleep = self.clock.sleep
        total = max(prefix + completed_previous + remaining, 16)
        self.f = f = Fixture(self.root, counts={"P": total, "R": 1, "T": 1, "F": 1}, q="C07", fixed="C07")
        f.clock, f.transport = self.clock, self.transport
        f.candidate["source_files"][str(Path(__file__).resolve())] = file_hash(__file__)
        f.candidate["source_files"][str(Path(rate_tests.__file__).resolve())] = file_hash(rate_tests.__file__)
        f.documents["source_manifest"] = f.file("source_manifest.json", {"files": f.candidate["source_files"]})
        f.plan = make_plan(f.frame, seed_base=71, bindings={k: v["sha256"] for k, v in f.documents.items()},
                           mode="artificial_only", counts={"P": total, "R": 1, "T": 1, "F": 1})
        prefix = next(i for i in range(1, total - 6)
                      if f.plan["panels"]["P"][i]["slots"][0]["arm"] == "Q")
        f.candidate.update(plan_hash=f.plan["plan_hash"], bindings=deepcopy(f.plan["bindings"]),
                           documents=deepcopy(f.documents), plan_evidence=f.file("plan.json", f.plan),
                           section_ends=list(range(prefix, total + 4)))
        f.bind()
        self.prefix, self.preserved = prefix, prefix + completed_previous
        self.partial_successful, self.backups = partial_successful, 0
        owner = self
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(owner.clock(), tz or timezone.utc)
        with patch.object(phase_budget, "datetime", FixedDateTime):
            self.original_checkpoint = f.run(prefix)
            self.transport.fail_at, self.transport.mode = self.transport.calls + 2, "transport"
            try:
                f.run(prefix + 1)
            except BudgetStop:
                pass
            else:
                raise AssertionError("original unknown call was not stopped")
            self.original_inventory = fr.original_inventory(f.folder)
            old_recovery = self.root / "old-recovery"
            old_report = fr.prepare_recovery(f.candidate, f.plan, original_folder=f.folder,
                output=old_recovery, recovery_id="artificial-original", inventory=self.original_inventory,
                expected_inventory_sha256=canonical_hash(self.original_inventory), checkpoint=self.original_checkpoint,
                expected_checkpoint_sha256=self.original_checkpoint["state_sha256"])
            self.prior_folder = self.root / "previous-segment"
            old_paths = [previous.__file__, fr.__file__, Path(__file__).with_name("test_final_resume.py"), __file__]
            old_sources = {str(Path(p).resolve()): file_hash(p) for p in old_paths}
            old_backup = source_backup(self.root / "old-sources.zip", old_sources, previous.source_members(old_sources))
            self.prior_activation = previous.make_activation(f.candidate, f.plan, folder=self.prior_folder,
                control=f.control, recovery_folder=old_recovery, expected_manifest_sha256=old_report["manifest_sha256"],
                resume_id="artificial-previous", source_files=old_sources, source_backup=old_backup,
                checkpoint=self.prior_backup, approval_reference="artificial D-069; no live authorization")
            self.prior_activation_hash = canonical_hash(self.prior_activation)
            old_args = dict(folder=self.prior_folder, control=f.control, expected_activation_sha256=self.prior_activation_hash,
                            clock=self.clock)
            previous.initialize_resume(f.candidate, f.plan, **old_args, recovery_folder=old_recovery,
                expected_manifest_sha256=old_report["manifest_sha256"], activation=self.prior_activation)
            for end in range(prefix + 1, self.preserved + 1):
                self.previous_checkpoint = previous.run_section(f.candidate, f.plan, **old_args, section_end=end,
                    loader=f.loader, spatial_selector=f.spatial_selector, transport=self.transport, checkpoint=self.prior_backup)
            self.transport.actions[self.transport.calls + partial_successful + 1] = "zero429"
            try:
                previous.run_section(f.candidate, f.plan, **old_args, section_end=self.preserved + 1,
                    loader=f.loader, spatial_selector=f.spatial_selector, transport=self.transport, checkpoint=self.prior_backup)
            except BudgetStop:
                pass
            else:
                raise AssertionError("prior structured 429 was not stopped by frozen adapter")
        self.prior_inventory = fr.original_inventory(self.prior_folder)
        self.recovery = self.root / "rate-recovery"
        self.report = rate.prepare_recovery(f.candidate, f.plan, previous_folder=self.prior_folder,
            expected_previous_activation_sha256=self.prior_activation_hash, inventory=self.prior_inventory,
            expected_inventory_sha256=canonical_hash(self.prior_inventory), output=self.recovery,
            recovery_id="artificial-D071", clock=self.clock)
        self.folder = self.root / "rate-segment"
        self.extra_source = self.root / "bound-additional-source.py"
        self.extra_source.write_text("# invented immutable additional source\n")
        paths = [rate.__file__, previous.__file__, fr.__file__, rate_limit.__file__, rate_tests.__file__, __file__, self.extra_source]
        self.sources = {str(Path(p).resolve()): file_hash(p) for p in paths}
        backup = source_backup(self.root / "rate-sources.zip", self.sources, rate.source_members(self.sources))
        self.activation = rate.make_activation(f.candidate, f.plan, folder=self.folder, control=f.control,
            recovery_folder=self.recovery, expected_manifest_sha256=self.report["manifest_sha256"], resume_id="artificial-D071",
            source_files=self.sources, source_backup=backup, checkpoint=self.backup,
            approval_reference="artificial D-071; no live authorization", clock=self.clock)
        self.activation_hash = canonical_hash(self.activation)



class PredecessorFixture(lost_tests.LostFixture):
    """Make a D-072 Q replacement, leaving enough invented pairs for D-073."""
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.r = r = QOriginalRateFixture(directory, remaining=8)
        r.initialize()
        r.checkpoint()
        self.old_checkpoint = r.run(r.preserved + 1)
        self.prefix = self.old_checkpoint["completed_blocks"]
        while r.f.plan["panels"]["P"][self.prefix]["slots"][0]["arm"] != "Q":
            self.old_checkpoint = r.run(self.prefix + 1)
            self.prefix += 1
        r.transport.actions[r.transport.calls + 4] = "transport"
        try:
            r.run(self.prefix + 1)
        except BudgetStop:
            pass
        else:
            raise AssertionError("invented D-072 Q predecessor did not stop")
        self.old_inventory = fr.original_inventory(r.folder)
        self.folder, self.recovery = self.root / "lost-segment", self.root / "lost-recovery"
        self.report = lost.prepare_recovery(r.f.candidate, r.f.plan, previous_folder=r.folder,
            expected_previous_activation_sha256=r.activation_hash, inventory=self.old_inventory,
            expected_inventory_sha256=canonical_hash(self.old_inventory), output=self.recovery,
            recovery_id="invented-048002", clock=r.clock)
        paths = (lost.__file__, rate.__file__, previous.__file__, fr.__file__, lost_tests.__file__, __file__)
        self.sources = {str(Path(p).resolve()): file_hash(p) for p in paths}
        backup = source_backup(self.root / "lost-sources.zip", self.sources, lost.source_members(self.sources))
        self.activation = lost.make_activation(r.f.candidate, r.f.plan, folder=self.folder,
            control=r.f.control, recovery_folder=self.recovery, expected_manifest_sha256=self.report["manifest_sha256"],
            resume_id="invented-D072", source_files=self.sources, source_backup=backup, checkpoint=self.backup,
            approval_reference="invented exact D-072 approval; no live release", clock=r.clock)
        self.activation_hash, self.backups = canonical_hash(self.activation), 0


class FFixture:
    def __init__(self, directory, *, inherited_zero_retries=0):
        self.root = Path(directory).resolve()
        self.prior = p = PredecessorFixture(directory)
        self.r = r = p.r
        p.initialize()
        p.checkpoint()
        self.old_checkpoint = p.run(p.prefix + 1)
        self.prefix = self.old_checkpoint["completed_blocks"]
        while r.f.plan["panels"]["P"][self.prefix]["slots"][0]["arm"] != "F":
            self.old_checkpoint = p.run(self.prefix + 1)
            self.prefix += 1
        first = r.transport.calls + 2
        for offset in range(inherited_zero_retries):
            r.transport.actions[first + offset] = "zero429"
        r.transport.actions[first + inherited_zero_retries] = "transport"
        try:
            p.run(self.prefix + 1)
        except BudgetStop:
            pass
        else:
            raise AssertionError("invented F unknown stop was not produced")
        self.old_inventory = fr.original_inventory(p.folder)
        self.folder, self.recovery = self.root / "f-segment", self.root / "f-recovery"
        self.report = self.prepare(self.recovery, self.old_inventory)
        self.extra_source = self.root / "f-bound-additional.py"
        self.extra_source.write_text("# invented immutable additional source\n")
        paths = (fresh.__file__, lost.__file__, rate.__file__, previous.__file__, fr.__file__, __file__, self.extra_source)
        self.sources = {str(Path(path).resolve()): file_hash(path) for path in paths}
        backup = source_backup(self.root / "f-sources.zip", self.sources, fresh.source_members(self.sources))
        self.activation = fresh.make_activation(r.f.candidate, r.f.plan, folder=self.folder,
            control=r.f.control, recovery_folder=self.recovery, expected_manifest_sha256=self.report["manifest_sha256"],
            resume_id="invented-D073", source_files=self.sources, source_backup=backup, checkpoint=self.backup,
            approval_reference="invented exact D-073 approval; no live release", clock=r.clock)
        self.activation_hash, self.backups = canonical_hash(self.activation), 0

    def prepare(self, output, inventory):
        return fresh.prepare_recovery(self.r.f.candidate, self.r.f.plan, previous_folder=self.prior.folder,
            expected_previous_activation_sha256=self.prior.activation_hash, inventory=inventory,
            expected_inventory_sha256=canonical_hash(inventory), output=output,
            recovery_id="invented-011355", clock=self.r.clock)

    def args(self):
        return dict(folder=self.folder, control=self.r.f.control,
                    expected_activation_sha256=self.activation_hash, clock=self.r.clock)

    def initialize(self):
        return fresh.initialize_resume(self.r.f.candidate, self.r.f.plan, **self.args(),
            recovery_folder=self.recovery, expected_manifest_sha256=self.report["manifest_sha256"], activation=self.activation)

    def backup(self, state):
        path = self.folder / "receipts" / f"invented-f-backup-{self.backups:04d}.zip"
        self.backups += 1
        with ZipFile(path, "x") as archive:
            for name in state["evidence"]:
                archive.write(self.folder / name, name)
        result = {"path": str(path), "sha256": file_hash(path), "members": state["evidence"]}
        fp.verify_archive(result, state["evidence"])
        return result

    def checkpoint(self):
        return fresh.checkpoint_resume(self.r.f.candidate, self.r.f.plan, **self.args(), checkpoint=self.backup)

    def run(self, end):
        return fresh.run_section(self.r.f.candidate, self.r.f.plan, **self.args(), section_end=end,
            loader=self.r.f.loader, spatial_selector=self.r.f.spatial_selector,
            transport=self.r.transport, checkpoint=self.backup, sleep=self.r.sleep)

    def inspect(self):
        return fresh.inspect_resume(self.r.f.candidate, self.r.f.plan, **self.args())

    def sender(self):
        activation, context = fresh._load(self.r.f.candidate, self.r.f.plan, self.folder,
            self.r.f.control, self.activation_hash, self.r.clock)
        return fresh._inspect(self.r.f.candidate, self.r.f.plan, self.folder,
            activation, self.activation_hash, *context)[2], context[2]


class FinalFResumeTests(unittest.TestCase):
    def ready(self, directory, **kwargs):
        fixture = FFixture(directory, **kwargs)
        fixture.initialize()
        fixture.checkpoint()
        return fixture

    def test_five_segments_one_replay_single_F_replacement_all_rows_costs_and_originals(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            initial = f.inspect()
            self.assertEqual(initial["rows"], f.old_checkpoint["rows"])
            self.assertEqual((initial["completed_blocks"], initial["new_budget"]["calls"]), (f.prefix, 0))
            self.assertEqual(f.report["partial_successful_calls"], 1)
            self.assertEqual([u["arm"] for u in initial["unknown_attempts"]], ["Q", "Q", "F"])
            self.assertTrue(all(":Q:" in u["physical_attempt_id"] or ":Q:" in u.get("logical_attempt_id", "")
                                for u in initial["unknown_attempts"][:2]))
            before, loads, selections = f.r.transport.calls, len(f.r.f.loads), len(f.r.f.selections)
            state = f.run(f.prefix + 1)
            self.assertEqual((f.r.transport.calls - before, len(state["rows"])), (13, 2 * (f.prefix + 1)))
            self.assertEqual((len(f.r.f.loads), len(f.r.f.selections)), (loads, selections))
            self.assertEqual(state["rows"][:2 * f.prefix], initial["rows"])
            maps = [fp.read_json(p) for p in sorted((f.folder / "mapping").glob("*.json"))]
            self.assertEqual(len(maps), 14)
            self.assertTrue(maps[0]["response_origin"].startswith("invented-D072:physical:"))
            self.assertEqual(sum(m["replacement_of_unknown"] is not None for m in maps), 1)
            binding = state["physical_attempts"][0]["binding"]
            self.assertEqual(binding["retry"], 1)
            self.assertEqual(binding["replacement_of_unknown"], f.report["lost"]["physical_attempt_id"])
            self.assertIsNone(binding["previous_received_at"])
            self.assertIsNone(binding["not_before"])
            old_number = f.report["lost"]["physical_calls"]
            self.assertEqual((f.folder / "provider/000001-request.json").read_bytes(),
                             (f.prior.folder / "provider" / f"{old_number:06d}-request.json").read_bytes())
            self.assertEqual(state["budget"]["held_reservation_usd"], "0.42")
            self.assertIsNone(state["budget"]["total_cost_usd"])
            self.assertEqual(len(state["budget"]["pending"]), 3)
            self.assertEqual(state["budget"]["pending"], state["cost_assumption"]["additional_charge_assumed_zero_for"])
            self.assertFalse(state["cost_assumption"]["provider_cost_confirmed"])
            self.assertEqual(Decimal(state["levels"]["available_usd"]["main"]),
                             Decimal("40") - Decimal(state["budget"]["known_cost_usd"]) - Decimal(".42"))
            self.assertEqual(fr.original_inventory(f.prior.folder), f.old_inventory)
            self.assertEqual(fr.original_inventory(f.r.folder), f.prior.old_inventory)
            self.assertEqual(fr.original_inventory(f.r.prior_folder), f.r.prior_inventory)
            self.assertEqual(fr.original_inventory(f.r.f.folder), f.r.original_inventory)
            self.assertEqual(f.inspect()["state_sha256"], state["state_sha256"])
            replay, context = f.sender()
            replay.transport = f.r.transport
            before_replay = f.r.transport.calls
            replay(context["partial"][-1].request)
            self.assertEqual(f.r.transport.calls, before_replay)
            with self.assertRaises(fp.StudyStop):
                replay(context["partial"][-1].request)
            for end in range(f.prefix + 2, f.r.f.plan["counts"]["P"] + 1):
                state = f.run(end)
            rows = fresh.collect_panel(f.r.f.candidate, f.r.f.plan, **f.args())
            self.assertEqual(len(rows), 2 * f.r.f.plan["counts"]["P"])
            self.assertTrue(state["complete"])
            self.assertEqual(sum((Decimal(r["cost_usd"]) for r in rows), Decimal(0)),
                             Decimal(state["budget"]["known_cost_usd"]))
            self.assertEqual(state["budget"]["calls"], f.r.transport.calls)

    def test_replacement_then_only_remaining_zero429_ordinals_and_waits(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            before, start = f.r.transport.calls, f.r.clock()
            f.r.transport.actions.update({before + 1: "zero429", before + 2: "zero429"})
            state = f.run(f.prefix + 1)
            records = state["physical_attempts"][:3]
            self.assertEqual([r["binding"]["retry"] for r in records], [1, 2, 3])
            self.assertEqual([r["binding"]["wait_elapsed_seconds"] for r in records], [0, 60, 120])
            self.assertEqual([r["binding"]["not_before"] for r in records], [None, start + 60, start + 180])
            self.assertEqual(state["rate_summary"]["authorized_unknown_replacements"], 1)
            self.assertEqual(state["additional_rate_retries"], 2)
            self.assertEqual(state["rate_summary"]["inherited_zero_cost_429_attempts"],
                             f.report["rate_summary"]["zero_cost_429_attempts"])

    def test_inherited_retry_count_and_new_exhaustion_cannot_reset(self):
        for inherited, allowed in ((2, 1), (0, 3)):
            with self.subTest(inherited=inherited), trial_directory() as directory:
                f = self.ready(directory, inherited_zero_retries=inherited)
                before = f.r.transport.calls
                f.r.transport.actions.update({before + i: "zero429" for i in range(1, 5)})
                with self.assertRaises(fp.StudyStop):
                    f.run(f.prefix + 1)
                self.assertEqual(f.r.transport.calls, before + allowed)
                self.assertFalse(fp.read_json(f.folder / "STOP.json")["retry_allowed"])
                with self.assertRaises(fp.StudyStop):
                    f.run(f.prefix + 1)
                self.assertEqual(f.r.transport.calls, before + allowed)

    def test_unknown_or_noneligible_errors_stop_without_second_unknown_replacement(self):
        for action in ("transport", "unknown_cost", "positive_cost", "positive_tokens", "other_error", "duplicate"):
            with self.subTest(action=action), trial_directory() as directory:
                f = self.ready(directory)
                before = f.r.transport.calls
                f.r.transport.actions[before + 1] = action
                with self.assertRaises(Exception):
                    f.run(f.prefix + 1)
                self.assertEqual(f.r.transport.calls, before + 1)
                with self.assertRaises(Exception):
                    f.run(f.prefix + 1)
                self.assertEqual(f.r.transport.calls, before + 1)

    def test_http401_and_malformed_envelopes_poison_dispatcher(self):
        for status, raw in ((401, b'{"error":{"code":401}}'), (200, b'not json')):
            with self.subTest(status=status), trial_directory() as directory:
                f = self.ready(directory)
                sender, context = f.sender()
                calls = []
                def transport(endpoint, body):
                    calls.append((endpoint, body))
                    return status, raw
                sender.transport = transport
                sender.clock = sender.wait_clock = f.r.clock
                with self.assertRaises(Exception):
                    sender(context["partial"][-1].request)
                self.assertTrue(sender.poisoned)
                with self.assertRaises(Exception):
                    sender(context["partial"][-1].request)
                self.assertEqual(len(calls), 1)

    def test_regular_new_requests_keep_30_60_120_policy_in_both_arms(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            f.run(f.prefix + 1)
            before = f.r.transport.calls
            f.r.transport.actions.update({before + 1: "zero429", before + 2: "zero429", before + 3: "zero429",
                                          before + 11: "zero429"})
            state = f.run(f.prefix + 2)
            records = state["physical_attempts"][13:]
            self.assertEqual([r["binding"]["retry"] for r in records[:4]], [0, 1, 2, 3])
            self.assertEqual([r["binding"]["wait_elapsed_seconds"] for r in records[:4]], [0, 30, 60, 120])
            self.assertEqual({r["binding"]["logical_attempt_id"].split(":")[-4]
                              for r in records if r["binding"]["retry"] > 0}, {"Q", "F"})

    def test_stopped_inventory_request_mapping_old_replacement_and_billing_tampering(self):
        for kind in ("stop", "request", "mapping", "replacement", "billing", "extra", "ledger"):
            with self.subTest(kind=kind), trial_directory() as directory:
                f = self.ready(directory)
                number = f.report["lost"]["physical_calls"]
                path = {"stop": f.prior.folder / "STOP.json", "request": f.prior.folder / "provider" / f"{number:06d}-request.json",
                    "mapping": f.prior.folder / "mapping/000001.json", "replacement": f.prior.folder / "provider/000001-binding.json",
                    "billing": f.prior.folder / "provider/000001-billing.json", "extra": f.prior.folder / "unexpected.json",
                    "ledger": f.prior.folder / "provider/budget.jsonl"}[kind]
                if kind in ("stop", "replacement", "billing"):
                    value = fp.read_json(path)
                    value[{"stop": "block_number", "replacement": "replacement_of_unknown", "billing": "generation_id"}[kind]] = "forged"
                    path.write_bytes(encoded(value))
                else:
                    path.write_bytes(path.read_bytes() + b" " if path.exists() else b"{}")
                with self.assertRaises(Exception):
                    f.prepare(f.root / "bad-preparation", fr.original_inventory(f.prior.folder))

    def test_sources_claim_lock_initial_backup_first_hold_and_four_original_roots(self):
        with trial_directory() as directory:
            f = FFixture(directory)
            before = f.r.transport.calls
            with fe.study_lock(f.r.f.control), self.assertRaises(fp.StudyStop):
                f.initialize()
            f.initialize()
            with self.assertRaises(Exception):
                f.initialize()
            with self.assertRaises(FileNotFoundError):
                f.run(f.prefix + 1)
            f.checkpoint()
            with self.assertRaises(fp.StudyStop):
                f.run(f.prefix + 2)
            for root in (f.prior.folder, f.r.folder, f.r.prior_folder, f.r.f.folder):
                value = deepcopy(f.activation)
                value["folder"] = str(root / "forbidden-output")
                with self.assertRaises(fp.StudyStop):
                    fresh._gate(f.r.f.candidate, f.r.f.plan, value, canonical_hash(value),
                                root / "forbidden-output", f.r.f.control, f.r.clock)
            f.extra_source.write_text("# changed invented source\n")
            with self.assertRaises(Exception):
                f.run(f.prefix + 1)
            self.assertEqual(f.r.transport.calls, before)

    def test_changed_or_duplicate_replay_stops_before_new_physical_work(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), trial_directory() as directory:
                f = self.ready(directory)
                original, seen = fresh.execute, []
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
                with patch.object(fresh, "execute", changed), self.assertRaises(Exception):
                    f.run(f.prefix + 1)
                self.assertEqual(f.r.transport.calls, before)

    def test_three_reservations_boundary_and_calendar_wait_guard(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            with self.assertRaises(fp.StudyStop):
                fresh._levels(f.r.f.candidate, Decimal("39.45"), Decimal(0), reserve_calls=1)
            allowed = fresh._levels(f.r.f.candidate, Decimal("39.44"), Decimal(0), reserve_calls=1)
            self.assertEqual(Decimal(allowed["available_usd"]["main"]), Decimal(".14"))
            self.assertEqual(allowed["held_unknown_reservations_usd"], ["0.14"] * 3)
            f.r.clock.value = f.r.f.candidate["calendar"]["end_epoch"] - 1
            before = f.r.transport.calls
            f.r.transport.actions[before + 1] = "zero429"
            with self.assertRaises(fp.StudyStop):
                f.run(f.prefix + 1)
            self.assertEqual(f.r.transport.calls, before + 1)

    def test_saved_new_replacement_binding_or_billing_tampering_is_rejected(self):
        for part, key in (("binding", "retry"), ("binding", "replacement_of_unknown"), ("billing", "generation_id")):
            with self.subTest(part=part, key=key), trial_directory() as directory:
                f = self.ready(directory)
                f.run(f.prefix + 1)
                path = f.folder / "provider" / f"000001-{part}.json"
                value = fp.read_json(path)
                value[key] = 0 if key == "retry" else "invented-forgery"
                path.write_bytes(encoded(value))
                with self.assertRaises(Exception):
                    f.inspect()

    def test_no_secondary_or_incomplete_panel_and_assumption_requires_three_exact_ids(self):
        with trial_directory() as directory:
            f = self.ready(directory)
            with self.assertRaises(ValueError):
                fresh.collect_panel(f.r.f.candidate, f.r.f.plan, **f.args())
            with self.assertRaises(fp.StudyStop):
                fresh.collect_panel(f.r.f.candidate, f.r.f.plan, "R", **f.args())
            value = deepcopy(f.activation)
            value["author_assumption"]["additional_charge_assumed_zero_for"].pop()
            with self.assertRaises(fp.StudyStop):
                fresh._gate(f.r.f.candidate, f.r.f.plan, value, canonical_hash(value),
                            f.folder, f.r.f.control, f.r.clock)


if __name__ == "__main__":
    unittest.main()
