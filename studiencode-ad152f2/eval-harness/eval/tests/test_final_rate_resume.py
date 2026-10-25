"""D-071 artificial continuation tests. No network, real tasks, fit or model.

The coordinator archives this module and all sources before each test process.
Z50_TEST_EVIDENCE_DIR keeps the complete invented journals and every failed run.
RateFixture is also an input generator for the separate coordinator review; its
assertions below are not a substitute for that review.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import unittest

from communication_pruning import phase_budget, rate_limit
from communication_pruning.contracts import Request, TaskInput
from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from communication_pruning.study import file_hash
from study_preparation import final_execution as fe, final_preflight as fp, final_recovery as fr, final_resume as previous
from study_preparation import final_rate_resume as rate
from study_preparation.final_plan import canonical_hash, make_plan
from tests.study_fixture import FakeTransport
from tests.test_final_preflight import Fixture, trial_directory


class FakeClock:
    def __init__(self, value=100):
        self.value, self.sleeps = float(value), []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class ScriptedTransport(FakeTransport):
    """One inherited fake physical call per invocation; an explicit response script."""
    def __init__(self):
        super().__init__()
        self.actions = {}

    def __call__(self, endpoint, body=None):
        status, raw = super().__call__(endpoint, body)
        if endpoint != "chat/completions":
            return status, raw
        action = self.actions.get(self.calls)
        if action is None:
            return status, raw
        obj = rate.strict_json(raw)
        if action == "transport":
            raise OSError("invented transport failure")
        if action == "interrupt":
            raise KeyboardInterrupt("invented interruption")
        obj["choices"] = [{"finish_reason": "error", "error": {"code": 429,
            "metadata": {"error_type": "rate_limit_exceeded"}},
            "message": {"role": "assistant", "content": "INVENTED_ERROR_PARTIAL_NEVER_AS_ANSWER"}}]
        obj["usage"].update(prompt_tokens=0, completion_tokens=0, total_tokens=0, cost="0")
        if action == "positive_cost":
            obj["usage"]["cost"] = "0.001"
        elif action == "positive_tokens":
            obj["usage"].update(prompt_tokens=1, total_tokens=1)
        elif action == "unknown_cost":
            obj["usage"].pop("cost")
        elif action == "other_error":
            obj["choices"][0]["error"]["code"] = 503
        elif action == "string_code":
            obj["choices"][0]["error"]["code"] = "429"
        elif action == "wrong_provider":
            obj["provider"] = "InventedOtherProvider"
        elif action == "wrong_model":
            obj["model"] = "invented/other-model"
        elif action == "byok":
            obj["usage"]["is_byok"] = True
        elif action == "duplicate":
            obj["id"] = "fake-gen-1"
        elif action == "reasoning_tokens":
            obj["usage"]["completion_tokens_details"]["reasoning_tokens"] = 1
        elif action == "http":
            status = 429
        elif action != "zero429":
            raise AssertionError("unknown artificial transport action")
        return status, encoded(obj)


def source_backup(path, files, members):
    with ZipFile(path, "x") as archive:
        for member, (name, checksum) in zip(members, sorted(files.items())):
            archive.write(name, member)
    result = {"path": str(path), "sha256": file_hash(path), "members": members}
    fp.verify_archive(result, members)
    return result


class RateFixture:
    """Invented original prefix + one prior segment + a final known-zero 429.

    The clock is 100 throughout inherited execution and ledger timestamps use
    the same artificial epoch. New waits advance that clock. Root's integration
    can reuse f, transport, recovery/report and build a different activation.
    No method accesses a network or real evaluation task.
    """
    def __init__(self, directory, *, prefix=1, completed_previous=1, remaining=2, partial_successful=9):
        if prefix < 1 or completed_previous < 1 or remaining < 1 or not 0 <= partial_successful < 14:
            raise ValueError("invalid artificial prefix/partial size")
        self.root = Path(directory).resolve()
        self.clock, self.transport = FakeClock(), ScriptedTransport()
        self.sleep = self.clock.sleep
        total = prefix + completed_previous + remaining
        self.f = f = Fixture(self.root, counts={"P": total, "R": 1, "T": 1, "F": 1}, q="C07", fixed="C07")
        f.clock, f.transport = self.clock, self.transport
        f.candidate["source_files"][str(Path(__file__).resolve())] = file_hash(__file__)
        f.documents["source_manifest"] = f.file("source_manifest.json", {"files": f.candidate["source_files"]})
        f.plan = make_plan(f.frame, seed_base=71, bindings={k: v["sha256"] for k, v in f.documents.items()},
                           mode="artificial_only", counts={"P": total, "R": 1, "T": 1, "F": 1})
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
        paths = [rate.__file__, previous.__file__, fr.__file__, rate_limit.__file__, __file__, self.extra_source]
        self.sources = {str(Path(p).resolve()): file_hash(p) for p in paths}
        backup = source_backup(self.root / "rate-sources.zip", self.sources, rate.source_members(self.sources))
        self.activation = rate.make_activation(f.candidate, f.plan, folder=self.folder, control=f.control,
            recovery_folder=self.recovery, expected_manifest_sha256=self.report["manifest_sha256"], resume_id="artificial-D071",
            source_files=self.sources, source_backup=backup, checkpoint=self.backup,
            approval_reference="artificial D-071; no live authorization", clock=self.clock)
        self.activation_hash = canonical_hash(self.activation)

    def _backup(self, folder, state):
        path = folder / "receipts" / f"artificial-backup-{self.backups:04d}.zip"
        self.backups += 1
        with ZipFile(path, "x") as archive:
            for name in state["evidence"]:
                archive.write(folder / name, name)
        receipt = {"path": str(path), "sha256": file_hash(path), "members": state["evidence"]}
        fp.verify_archive(receipt, state["evidence"])
        return receipt

    def prior_backup(self, state):
        return self._backup(self.prior_folder, state)

    def backup(self, state):
        return self._backup(self.folder, state)

    def args(self):
        return dict(folder=self.folder, control=self.f.control, expected_activation_sha256=self.activation_hash,
                    clock=self.f.clock)

    def initialize(self):
        return rate.initialize_resume(self.f.candidate, self.f.plan, **self.args(), recovery_folder=self.recovery,
            expected_manifest_sha256=self.report["manifest_sha256"], activation=self.activation)

    def checkpoint(self):
        return rate.checkpoint_resume(self.f.candidate, self.f.plan, **self.args(), checkpoint=self.backup)

    def run(self, end):
        return rate.run_section(self.f.candidate, self.f.plan, **self.args(), section_end=end,
            loader=self.f.loader, spatial_selector=self.f.spatial_selector, transport=self.transport,
            checkpoint=self.backup, sleep=self.sleep)

    def inspect(self):
        return rate.inspect_resume(self.f.candidate, self.f.plan, **self.args())


class FinalRateResumeTests(unittest.TestCase):
    def ready(self, directory, **kwargs):
        r = RateFixture(directory, **kwargs)
        r.initialize()
        r.checkpoint()
        return r

    def test_join_replays_exact_nine_answers_costs_rows_and_original_integrity(self):
        with trial_directory() as directory:
            r = self.ready(directory)
            initial = r.inspect()
            self.assertEqual((initial["completed_blocks"], len(initial["rows"]), initial["new_budget"]["calls"]), (2, 4, 0))
            self.assertEqual(initial["rows"], r.previous_checkpoint["rows"])
            self.assertEqual(Decimal(initial["budget"]["known_cost_usd"]),
                sum((Decimal(row["cost_usd"]) for row in initial["rows"]), Decimal(0)) + Decimal(r.report["partial_known_cost_usd"]))
            before, loads, selections = r.transport.calls, len(r.f.loads), len(r.f.selections)
            state = r.run(3)
            self.assertEqual((len(r.f.loads), len(r.f.selections)), (loads, selections))
            self.assertEqual(r.transport.calls - before, 5)
            self.assertEqual(len(state["rows"]), 6)
            partial_maps = [fp.read_json(p) for p in sorted((r.folder / "mapping").glob("*.json"))]
            self.assertEqual(len(partial_maps), 14)
            self.assertTrue(all(m["final_retry"] == 0 for m in partial_maps[:9]))
            self.assertEqual(partial_maps[9]["final_retry"], 1)
            self.assertEqual((r.folder / "provider/000001-request.json").read_bytes(),
                (r.prior_folder / "provider" / f'{r.previous_checkpoint["new_budget"]["calls"] + 10:05d}-request.json').read_bytes())
            self.assertEqual(state["rate_summary"]["new_wait_elapsed_seconds"], 30)
            self.assertEqual(state["rate_summary"]["total_zero_cost_429_attempts"], 1)
            self.assertEqual(state["rate_summary"]["new_retry_attempts"], 1)
            self.assertEqual(state["budget"]["held_reservation_usd"], "0.14")
            self.assertEqual(Decimal(state["levels"]["available_usd"]["main"]),
                             Decimal("40.00") - Decimal(state["budget"]["known_cost_usd"]) - Decimal("0.14"))
            with self.assertRaises(fp.StudyStop):
                rate._levels(r.f.candidate, Decimal("39.8"), Decimal(0), reserve_calls=1)
            self.assertIsNone(state["budget"]["total_cost_usd"])
            self.assertFalse(state["cost_assumption"]["provider_cost_confirmed"])
            self.assertEqual(state["budget"]["pending"], r.activation["unknown_attempt_id"])
            self.assertEqual(fr.original_inventory(r.f.folder), r.original_inventory)
            self.assertEqual(fr.original_inventory(r.prior_folder), r.prior_inventory)
            state = r.run(4)
            rows = rate.collect_panel(r.f.candidate, r.f.plan, **r.args())
            self.assertEqual(len(rows), 8)
            self.assertTrue(state["complete"])
            self.assertEqual(state["rows"][:4], initial["rows"])
            self.assertEqual(sum((Decimal(row["cost_usd"]) for row in rows), Decimal(0)), Decimal(state["budget"]["known_cost_usd"]))
            self.assertEqual(state["budget"]["calls"], r.transport.calls)
            self.assertEqual(fr.original_inventory(r.prior_folder), r.prior_inventory)

    def test_inherited_attempt_counts_three_retries_waits_and_no_partial_error_answer(self):
        with trial_directory() as directory:
            r = self.ready(directory)
            start = r.transport.calls
            r.transport.actions.update({start + 1: "zero429", start + 2: "zero429"})
            state = r.run(3)
            records = state["physical_attempts"][:3]
            self.assertEqual([a["binding"]["retry"] for a in records], [1, 2, 3])
            self.assertEqual([a["binding"]["not_before"] for a in records], [130, 190, 310])
            self.assertEqual([a["binding"]["wait_elapsed_seconds"] for a in records], [30, 60, 120])
            self.assertEqual([a["outcome"] for a in records], ["rate_limited", "rate_limited", "completed"])
            self.assertEqual(len({a["binding"]["physical_attempt_id"] for a in records}), 3)
            self.assertEqual(len({a["binding"]["logical_attempt_id"] for a in records}), 1)
            self.assertEqual(state["rate_summary"]["new_wait_elapsed_seconds"], 210)
            self.assertEqual(state["rate_summary"]["new_retry_attempts"], 3)
            for journal in (r.folder / "blocks").glob("*/*/journal.jsonl"):
                self.assertNotIn("INVENTED_ERROR_PARTIAL_NEVER_AS_ANSWER", journal.read_text())
            self.assertEqual(r.inspect()["state_sha256"], state["state_sha256"])

    def test_fourth_inherited_physical_failure_stops_and_restart_never_resets_counter(self):
        with trial_directory() as directory:
            r = self.ready(directory)
            before = r.transport.calls
            r.transport.actions.update({before + i: "zero429" for i in (1, 2, 3, 4)})
            with self.assertRaises(fp.StudyStop):
                r.run(3)
            self.assertEqual(r.transport.calls, before + 3)
            self.assertEqual(r.clock(), 310)
            self.assertEqual(len(list((r.folder / "provider").glob("*-outcome.json"))), 3)
            self.assertTrue(all(fp.read_json(p)["outcome"] == "rate_limited" for p in (r.folder / "provider").glob("*-outcome.json")))
            self.assertFalse(fp.read_json(r.folder / "STOP.json")["retry_allowed"])
            with self.assertRaises(fp.StudyStop):
                r.run(3)
            self.assertEqual(r.transport.calls, before + 3)

    def test_new_logical_request_has_four_physical_attempts_and_policy_applies_to_both_arms(self):
        with trial_directory() as directory:
            r = self.ready(directory)
            r.clock.value = 150
            r.run(3)
            # One retry on the first request in each seven-call arm of block 4.
            before = r.transport.calls
            r.transport.actions.update({before + 1: "zero429", before + 2: "zero429", before + 3: "zero429",
                                        before + 11: "zero429"})
            state = r.run(4)
            new = state["physical_attempts"][5:]
            self.assertEqual([a["binding"]["retry"] for a in new[:4]], [0, 1, 2, 3])
            self.assertEqual([a["binding"]["wait_elapsed_seconds"] for a in new[:4]], [0, 30, 60, 120])
            retried = {a["binding"]["logical_attempt_id"] for a in new if a["binding"]["retry"] > 0}
            self.assertEqual(len(retried), 2)
            self.assertEqual(state["rate_summary"]["new_wait_elapsed_seconds"], 240)
            self.assertEqual(state["rate_summary"]["total_zero_cost_429_attempts"], 5)

    def test_already_elapsed_downtime_is_not_active_wait_and_dispatch_deadline_is_bound(self):
        with trial_directory() as directory:
            r = self.ready(directory)
            r.clock.value = 200
            state = r.run(3)
            first = state["physical_attempts"][0]["binding"]
            self.assertEqual((first["not_before"], first["dispatched_at"], first["wait_elapsed_seconds"]), (130, 200, 0))
            self.assertEqual(r.clock.sleeps, [])
            self.assertEqual(state["rate_summary"]["new_wait_elapsed_seconds"], 0)

    def test_only_strict_zero_billing_provider_model_error_envelopes_are_retryable(self):
        for action in ("positive_cost", "positive_tokens", "unknown_cost", "other_error", "string_code",
                       "wrong_provider", "wrong_model", "byok", "duplicate", "reasoning_tokens", "http", "transport"):
            with self.subTest(action=action), trial_directory() as directory:
                r = self.ready(directory)
                before = r.transport.calls
                r.transport.actions[before + 1] = action
                with self.assertRaises(Exception):
                    r.run(3)
                self.assertEqual(r.transport.calls, before + 1)
                self.assertTrue((r.folder / "STOP.json").exists())
                self.assertFalse((r.folder / "provider/000002-request.json").exists())
                if action not in ("transport", "unknown_cost", "wrong_model", "wrong_provider", "byok", "duplicate"):
                    self.assertTrue((r.folder / "provider/000001-billing.json").exists())

    def test_calendar_during_backoff_clock_stall_and_source_change_stop_before_dispatch(self):
        for kind in ("calendar", "stalled", "source"):
            with self.subTest(kind=kind), trial_directory() as directory:
                r = self.ready(directory)
                before = r.transport.calls
                def sleep(seconds):
                    if kind == "calendar":
                        r.clock.value = 1001
                    elif kind == "source":
                        r.clock.sleep(seconds)
                        r.extra_source.write_bytes(r.extra_source.read_bytes() + b"# altered\n")
                r.sleep = sleep
                with self.assertRaises(Exception):
                    r.run(3)
                self.assertEqual(r.transport.calls, before)
                self.assertFalse((r.folder / "provider/000001-request.json").exists())

    def test_initial_backup_original_lock_claim_and_mandatory_next_hold(self):
        with trial_directory() as directory:
            r = RateFixture(directory)
            with fe.study_lock(r.f.control), self.assertRaises(fp.StudyStop):
                r.initialize()
            r.initialize()
            before = r.transport.calls
            with self.assertRaises(FileNotFoundError):
                r.run(3)
            with self.assertRaises(Exception):
                r.initialize()
            r.checkpoint()
            with self.assertRaises(fp.StudyStop):
                r.run(4)
            self.assertEqual(r.transport.calls, before)
            r.run(3)
            receipt = fe._receipt_path(r.folder, r.inspect())
            receipt.unlink()  # artificial damage only, retained in this negative fixture
            with self.assertRaises(FileNotFoundError):
                r.run(4)
            self.assertFalse((r.folder / "blocks/000003").exists())

    def test_changed_original_previous_recovery_activation_and_source_fail_before_load(self):
        for kind in ("original", "previous", "recovery", "activation", "source"):
            with self.subTest(kind=kind), trial_directory() as directory:
                r = self.ready(directory)
                path = {"original": r.f.folder / "provider/00001-response.json",
                        "previous": r.prior_folder / "provider/00001-response.json",
                        "recovery": r.recovery / "ORIGINALS.json", "activation": r.folder / "ACTIVATION.json",
                        "source": r.extra_source}[kind]
                path.write_bytes(path.read_bytes() + b" ")
                before, loads = r.transport.calls, len(r.f.loads)
                with self.assertRaises(Exception):
                    r.run(3)
                self.assertEqual((r.transport.calls, len(r.f.loads)), (before, loads))
                self.assertFalse((r.folder / "blocks/000002").exists())

    def test_changed_retry_identity_time_and_billing_are_rejected_after_saved_hold(self):
        for field in ("retry", "previous_physical_attempt_id", "not_before", "wait_elapsed_seconds", "request_sha256"):
            with self.subTest(field=field), trial_directory() as directory:
                r = self.ready(directory)
                r.run(3)
                path = r.folder / "provider/000001-binding.json"
                binding = fp.read_json(path)
                binding[field] = -1 if field in ("retry", "not_before", "wait_elapsed_seconds") else "forged"
                path.write_bytes(encoded(binding))
                with self.assertRaises(Exception):
                    r.inspect()

    def test_changed_replayed_request_and_repeated_logical_id_stop_without_new_call(self):
        for repeated in (False, True):
            with self.subTest(repeated=repeated), trial_directory() as directory:
                r = self.ready(directory)
                original_execute, first = rate.execute, []
                def changed(task, config, send, **kwargs):
                    def wrapped(request):
                        if repeated:
                            if not first:
                                first.append(request)
                                send(request)
                            return send(first[0])
                        return send(replace(request, instruction=request.instruction + " modified"))
                    return original_execute(task, config, wrapped, **kwargs)
                before = r.transport.calls
                with patch.object(rate, "execute", changed), self.assertRaises(Exception):
                    r.run(3)
                self.assertEqual(r.transport.calls, before)
                self.assertTrue((r.folder / "STOP.json").exists())

    def test_recovery_inventory_hash_and_extra_unclaimed_file_rejected(self):
        with trial_directory() as directory:
            r = RateFixture(directory)
            args = dict(previous_folder=r.prior_folder, expected_previous_activation_sha256=r.prior_activation_hash,
                        inventory=r.prior_inventory, output=r.root / "another-recovery", recovery_id="bad", clock=r.clock)
            with self.assertRaises(Exception):
                rate.prepare_recovery(r.f.candidate, r.f.plan, **args, expected_inventory_sha256="0" * 64)
            (r.prior_folder / "unclaimed.json").write_bytes(b"{}")
            inv = fr.original_inventory(r.prior_folder)
            args["inventory"] = inv
            with self.assertRaises(Exception):
                rate.prepare_recovery(r.f.candidate, r.f.plan, **args, expected_inventory_sha256=canonical_hash(inv))

    def test_partial_sizes_do_not_hardcode_nine_or_allow_incomplete_collection(self):
        for size in (0, 6, 13):
            with self.subTest(partial_successful=size), trial_directory() as directory:
                r = self.ready(directory, partial_successful=size)
                before = r.transport.calls
                state = r.run(3)
                self.assertEqual(r.transport.calls - before, 14 - size)
                self.assertEqual(len(state["rows"]), 6)
                with self.assertRaises(ValueError):
                    rate.collect_panel(r.f.candidate, r.f.plan, **r.args())


if __name__ == "__main__":
    unittest.main()
