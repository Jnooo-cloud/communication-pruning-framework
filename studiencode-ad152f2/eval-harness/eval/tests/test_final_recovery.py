"""Z51 synthetic recovery criteria; never read study tasks or use a network.

Set Z50_TEST_EVIDENCE_DIR to retain every fixture, including failed attempts.
The coordinator must archive this test and its sources before decisive runs.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import json
import unittest

from communication_pruning.contracts import Message, Request, TaskInput
from communication_pruning.data import digest
from communication_pruning.failure_policy import F01, decode_outcome
from communication_pruning.openrouter import encoded
from communication_pruning.phase_budget import BudgetStop
from study_preparation import final_execution as fe, final_preflight as fp
from study_preparation import final_recovery as fr
from study_preparation.final_analysis import validate_rows
from study_preparation.final_plan import canonical_hash
from tests.test_final_preflight import Fixture, trial_directory


def requests_from_original_journals(fixture):
    """Independent fixture extraction from stored journal events, not replay state."""
    result = []
    blocks = [block for panel in ("P", "R", "T", "F") for block in fixture.plan["panels"][panel]]
    for number, block in enumerate(blocks):
        for slot in block["slots"]:
            path = fixture.folder / "blocks" / f"{number:06d}" / slot["arm"] / "journal.jsonl"
            if not path.exists():
                continue
            rows = [json.loads(line) for line in path.read_bytes().splitlines()]
            public = rows[0]["payload"]["trace"]["task"]
            task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
            for row in rows[1:]:
                event = row["payload"].get("event", {})
                if event.get("kind") == "started":
                    result.append(Request(event["attempt_id"], task, event["role"], event["round"],
                                          event["instruction"], tuple(Message(**m) for m in event["messages"]),
                                          event["max_output_tokens"]))
    return result


class FinalRecoveryTests(unittest.TestCase):
    def fixture(self, directory, *, prefix=1, stop=True):
        f = Fixture(Path(directory).resolve(), counts={"P": prefix + 1, "R": 1, "T": 1, "F": 1})
        f.candidate["section_ends"] = list(range(prefix, prefix + 5))
        f.bind()
        checkpoint = f.run(prefix)
        if stop:
            f.transport.fail_at, f.transport.mode = checkpoint["budget"]["calls"] + 2, "transport"
            with self.assertRaises(BudgetStop):
                f.run(prefix + 1)
        return f, checkpoint

    def prepare(self, f, checkpoint, *, name="recovery", inventory=None):
        inventory = fr.original_inventory(f.folder) if inventory is None else inventory
        return fr.prepare_recovery(f.candidate, f.plan, original_folder=f.folder, output=f.root / name,
                                   recovery_id="synthetic-z51-" + name, inventory=inventory,
                                   expected_inventory_sha256=canonical_hash(inventory), checkpoint=checkpoint,
                                   expected_checkpoint_sha256=checkpoint["state_sha256"])

    def replay(self, f, report, *, name="recovery", scope="partial_block"):
        return fr.OfflineReplay(f.candidate, f.plan, recovery_folder=f.root / name,
                                expected_manifest_sha256=report["manifest_sha256"], scope=scope)

    def inspect(self, f, report):
        return fr.inspect_recovery(f.candidate, f.plan, recovery_folder=f.root / "recovery",
                                   expected_manifest_sha256=report["manifest_sha256"])

    def test_intact_prefix_replays_every_original_response_without_new_calls_or_costs(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory, stop=False)
            old = fr.original_inventory(f.folder)
            report = self.prepare(f, checkpoint, inventory=old)
            calls_before = f.transport.calls
            with patch("communication_pruning.openrouter.Transport.__call__", side_effect=AssertionError("network forbidden")):
                replay = self.replay(f, report, scope="all_original_calls")
                for index, request in enumerate(requests_from_original_journals(f), 1):
                    raw = (f.folder / "provider" / f"{index:05d}-response.json").read_bytes()
                    expected = decode_outcome(raw, request.max_output_tokens, F01)
                    expected = replace(expected, usage=replace(expected.usage, cost_source="synthetic"))
                    self.assertEqual(replay(request), expected)
                with self.assertRaisesRegex(fr.RecoveryStop, "no further original call"):
                    replay(request)
            self.assertEqual(fr.original_inventory(f.folder), old)
            self.assertEqual(f.transport.calls, calls_before)
            self.assertFalse(report["live_continuation_allowed"])
            self.assertEqual(report["new_cost_usd"], "0")
            self.assertEqual(report["unresolved_attempts"], [])
            events = list((f.root / "recovery/replay").glob("*-replayed.json"))
            self.assertEqual(len(events), checkpoint["budget"]["calls"])
            self.assertTrue(all(json.loads(p.read_bytes())["reservation_released"] is False for p in events))

    def test_100_complete_pairs_and_known_partial_call_remain_but_unknown_call_stops(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory, prefix=100)
            old = fr.original_inventory(f.folder)
            before_plan, before_candidate = deepcopy(f.plan), deepcopy(f.candidate)
            report = self.prepare(f, checkpoint, inventory=old)
            self.assertEqual(report["completed_blocks_preserved"], 100)
            self.assertEqual(len(checkpoint["rows"]), 200)
            self.assertEqual(len(report["replayable_calls"]), checkpoint["budget"]["calls"] + 1)
            self.assertEqual(report["budget"]["held_reservation_usd"], "0.14")
            self.assertIsNone(report["budget"]["total_cost_usd"])
            self.assertFalse(report["budget"]["reservation_is_expense"])
            self.assertEqual(len(report["unresolved_attempts"]), 1)
            requests = requests_from_original_journals(f)
            replay = self.replay(f, report)
            self.assertEqual(replay(requests[-2]).usage.cost_usd, fp.money("0.0000108"))
            with self.assertRaisesRegex(fr.RecoveryStop, "unresolved"):
                replay(requests[-1])
            with self.assertRaisesRegex(fr.RecoveryStop, "already stopped"):
                replay(requests[-1])
            with self.assertRaises((BudgetStop, fp.StudyStop)):
                f.run(101)
            with self.assertRaisesRegex(ValueError, "complete fixed-size panel"):
                validate_rows(f.plan, "P", checkpoint["rows"])
            self.assertEqual(fr.original_inventory(f.folder), old)
            self.assertEqual((f.plan, f.candidate), (before_plan, before_candidate))
            self.assertEqual(self.inspect(f, report)["budget"], report["budget"])

    def test_changed_request_poison_stops_exact_retry_and_second_consumer(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            report = self.prepare(f, checkpoint)
            replay = self.replay(f, report)
            request = requests_from_original_journals(f)[-2]
            with self.assertRaisesRegex(fr.RecoveryStop, "exact original"):
                replay(replace(request, task=replace(request.task, task_id="synthetic-foreign")))
            with self.assertRaisesRegex(fr.RecoveryStop, "already stopped"):
                replay(request)
            with self.assertRaises(FileExistsError):
                self.replay(f, report)
            self.assertTrue((f.root / "recovery/replay/STOP.json").is_file())

    def test_duplicate_replay_is_never_an_implicit_retry(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            report = self.prepare(f, checkpoint)
            replay = self.replay(f, report)
            request = requests_from_original_journals(f)[-2]
            replay(request)
            with self.assertRaisesRegex(fr.RecoveryStop, "exact original"):
                replay(request)
            self.assertEqual(len(list((f.root / "recovery/replay").glob("*-replayed.json"))), 1)

    def test_every_changed_or_missing_original_provider_part_blocks_against_external_anchor(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            original = fr.original_inventory(f.folder)
            index = checkpoint["budget"]["calls"] + 1
            for part in ("request", "binding", "response", "received", "billing"):
                path = f.folder / "provider" / f"{index:05d}-{part}.json"
                raw = path.read_bytes()
                for operation in ("modified", "missing"):
                    with self.subTest(part=part, operation=operation):
                        if operation == "modified":
                            path.write_bytes(raw + b" ")
                        else:
                            path.unlink()
                        with self.assertRaisesRegex(fr.RecoveryStop, "file set or bytes changed"):
                            self.prepare(f, checkpoint, name=part + operation, inventory=original)
                        path.write_bytes(raw)
            self.assertEqual(fr.original_inventory(f.folder), original)

    def test_attempt_request_response_billing_received_and_generation_cross_bindings(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            index = checkpoint["budget"]["calls"] + 1
            paths = {part: f.folder / "provider" / f"{index:05d}-{part}.json" for part in
                     ("request", "binding", "response", "received", "billing")}
            originals = {part: path.read_bytes() for part, path in paths.items()}
            for case in ("request", "attempt", "answer", "billing", "http", "generation", "missing_cost"):
                with self.subTest(case=case):
                    values = {part: json.loads(raw) for part, raw in originals.items()}
                    if case == "request":
                        values["request"]["messages"][0]["content"] += " changed"
                        values["binding"]["request_sha256"] = fr._hash(encoded(values["request"]))
                    elif case == "attempt":
                        values["binding"]["attempt_id"] = "another-attempt"
                    elif case == "answer":
                        values["response"]["choices"][0]["message"]["content"] = "invented replacement"
                    elif case == "billing":
                        values["billing"]["usage"]["cost_usd"] = "0.01"
                    elif case == "http":
                        values["received"]["http_status"] = 503
                    elif case == "generation":
                        values["response"]["id"] = checkpoint["generation_ids"][0]
                        values["billing"]["generation_id"] = checkpoint["generation_ids"][0]
                    else:
                        del values["response"]["usage"]["cost"]
                    if case in ("answer", "generation", "missing_cost"):
                        response_hash = fr._hash(encoded(values["response"]))
                        values["received"]["response_sha256"] = response_hash
                        values["billing"]["response_sha256"] = response_hash
                    for part, value in values.items():
                        paths[part].write_bytes(encoded(value))
                    # Even a freshly supplied inventory cannot replace cross-file provenance.
                    with self.assertRaises((fr.RecoveryStop, KeyError)):
                        self.prepare(f, checkpoint, name=case)
                    for part, raw in originals.items():
                        paths[part].write_bytes(raw)

    def test_cost_assertion_or_fake_receipt_cannot_resolve_unknown_original(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            index = checkpoint["budget"]["calls"] + 2
            for part in ("response", "received", "billing"):
                old = f.folder / "provider" / f"{index - 1:05d}-{part}.json"
                (f.folder / "provider" / f"{index:05d}-{part}.json").write_bytes(old.read_bytes())
            with self.assertRaisesRegex(fr.RecoveryStop, "no reconstruction import"):
                self.prepare(f, checkpoint)
            rows = [json.loads(line) for line in (f.folder / "budget.jsonl").read_bytes().splitlines()]
            self.assertIsNone(rows[-1]["usage"]["cost_usd"])
            self.assertEqual(rows[-2]["reservation_usd"], "0.14")

    def test_duplicate_or_dispatch_after_unknown_reservation_is_rejected(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            path = f.folder / "budget.jsonl"
            original = path.read_bytes()
            for case in ("duplicate", "after_unknown"):
                with self.subTest(case=case):
                    rows = [json.loads(line) for line in original.splitlines()]
                    if case == "duplicate":
                        rows[-2]["attempt_id"] = rows[1]["attempt_id"]
                        rows[-1]["attempt_id"] = rows[1]["attempt_id"]
                    else:
                        rows.extend(deepcopy(rows[-2:]))
                        rows[-2]["attempt_id"] = rows[-1]["attempt_id"] = "unapproved-second-dispatch"
                    previous = "0" * 64
                    for number, row in enumerate(rows):
                        row.pop("sha256")
                        row.update(sequence=number, previous=previous)
                        row["sha256"] = digest(row)
                        previous = row["sha256"]
                    path.write_bytes(b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows))
                    with self.assertRaisesRegex(fr.RecoveryStop, "reservation|unresolved dispatch"):
                        self.prepare(f, checkpoint, name=case)
                    path.write_bytes(original)

    def test_changed_calendar_budget_or_study_order_cannot_rebind_originals(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            report = self.prepare(f, checkpoint)
            original_candidate, original_plan = deepcopy(f.candidate), deepcopy(f.plan)
            for case in ("calendar", "budget", "order"):
                with self.subTest(case=case):
                    if case == "calendar":
                        f.candidate["calendar"]["end_epoch"] += 1
                    elif case == "budget":
                        f.candidate["budget"]["main_cap_usd"] = "41.00"
                    else:
                        f.plan["panels"]["P"].reverse()
                    f.candidate = fp.seal(f.candidate)
                    with self.assertRaisesRegex(fr.RecoveryStop, "frozen plan changed"):
                        self.inspect(f, report)
                    with self.assertRaises((fr.RecoveryStop, fp.StudyStop, ValueError)):
                        self.prepare(f, checkpoint, name=case)
                    f.candidate, f.plan = deepcopy(original_candidate), deepcopy(original_plan)

    def test_inventory_checkpoint_manifest_and_create_only_output_are_bound(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            old = fr.original_inventory(f.folder)
            corrupt = deepcopy(checkpoint)
            corrupt["completed_blocks"] += 1
            with self.assertRaisesRegex(fr.RecoveryStop, "checkpoint binding"):
                self.prepare(f, corrupt)
            report = self.prepare(f, checkpoint)
            with self.assertRaisesRegex(fr.RecoveryStop, "new recovery directory"):
                self.prepare(f, checkpoint)
            with self.assertRaisesRegex(fr.RecoveryStop, "separate from originals"):
                fr.prepare_recovery(f.candidate, f.plan, original_folder=f.folder,
                                    output=f.folder / "recovery", recovery_id="synthetic-invalid",
                                    inventory=old, expected_inventory_sha256=canonical_hash(old),
                                    checkpoint=checkpoint, expected_checkpoint_sha256=checkpoint["state_sha256"])
            with self.assertRaisesRegex(fr.RecoveryStop, "manifest changed"):
                fr.inspect_recovery(f.candidate, f.plan, recovery_folder=f.root / "recovery",
                                    expected_manifest_sha256="0" * 64)
            path = f.root / "recovery/ORIGINALS.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(fr.RecoveryStop, "manifest changed"):
                self.inspect(f, report)
            self.assertEqual(fr.original_inventory(f.folder), old)

    def test_original_mutation_after_session_creation_blocks_before_returning_response(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            report = self.prepare(f, checkpoint)
            replay = self.replay(f, report)
            request = requests_from_original_journals(f)[-2]
            index = checkpoint["budget"]["calls"] + 1
            path = f.folder / "provider" / f"{index:05d}-response.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(fr.RecoveryStop, "file set or bytes changed"):
                replay(request)
            self.assertEqual(list((f.root / "recovery/replay").glob("*-replayed.json")), [])

    def test_extra_dispatch_file_and_symlink_are_rejected(self):
        with trial_directory() as directory:
            f, checkpoint = self.fixture(directory)
            path = f.folder / "provider/duplicate-request.json"
            path.write_bytes((f.folder / "provider/00001-request.json").read_bytes())
            with self.assertRaisesRegex(fr.RecoveryStop, "unclaimed files"):
                self.prepare(f, checkpoint, name="duplicate")
            path.unlink()
            path.symlink_to(f.folder / "provider/00001-request.json")
            with self.assertRaisesRegex(fr.RecoveryStop, "symlink"):
                self.prepare(f, checkpoint, name="symlink")


if __name__ == "__main__":
    unittest.main()
