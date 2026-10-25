"""Z02 predeclared criteria: entirely synthetic, including child-process crashes."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from communication_pruning.audit import AuditError
from communication_pruning.configurations import bank, dense, without_peers
from communication_pruning.contracts import AdapterError, Response, Usage
from communication_pruning.execution import execute
from communication_pruning.journal import Journal, JournalError, read_journal
from test_core import TASK, stub


CHILD = r'''
import os, sys
from decimal import Decimal
from pathlib import Path
from communication_pruning.configurations import bank
from communication_pruning.contracts import TaskInput, Response, Usage
from communication_pruning.execution import execute
from communication_pruning.journal import Journal
path, mode = sys.argv[1:]
original = Journal._write
def write(self, payload):
    event = payload.get("event", {})
    if mode == "after_adapter" and event.get("kind") == "completed":
        os._exit(22)
    original(self, payload)
    if mode == "after_start" and event.get("kind") == "started":
        os._exit(21)
Journal._write = write
def adapter(request):
    with open(path + ".calls", "ab") as count:
        count.write(b"1\n")
        count.flush()
        os.fsync(count.fileno())
    return Response(f"{request.role}/{request.round}", Usage(10, 2, Decimal("0.01"), "synthetic"))
execute(TaskInput("artificial", "Which box?", ("The marble is in box A.",)),
        bank()[0], adapter, run_id="child", journal_path=path)
'''


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run.jsonl"
        self.config = bank()[0]

    def run_trace(self, **kwargs):
        return execute(TASK, self.config, kwargs.pop("adapter", stub), run_id="test",
                       journal_path=self.path, **kwargs)

    def read(self):
        return read_journal(self.path, self.config)

    def child(self, mode):
        result = subprocess.run([sys.executable, "-c", CHILD, str(self.path), mode],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.stderr, "")
        return result.returncode

    def call_count(self):
        path = Path(str(self.path) + ".calls")
        return len(path.read_bytes().splitlines()) if path.exists() else 0

    def records(self):
        return [json.loads(line) for line in self.path.read_bytes().splitlines()]

    def replace_records(self, records):
        # Test-only re-signing ensures semantic checks do not rely on checksums.
        previous = None
        for index, record in enumerate(records):
            record.pop("checksum", None)
            record["seq"], record["previous"] = index, previous
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True, allow_nan=False).encode()
            previous = sha256(canonical).hexdigest()
            record["checksum"] = previous
        self.path.write_bytes(b"".join(json.dumps(r).encode() + b"\n" for r in records))

    def test_k1_completed_child_readback(self):
        self.assertEqual(self.child("normal"), 0)
        before = self.path.read_bytes()
        expected = execute(TASK, self.config, stub, run_id="child")
        for _ in range(2):
            saved = self.read()
            self.assertTrue(saved["sealed"])
            self.assertEqual(saved["trace"], expected)
            self.assertEqual(saved["audit"]["calls"], 5)
            self.assertEqual(saved["audit"]["total_cost_usd"], "0.05")
        self.assertEqual(self.call_count(), 5)
        self.assertEqual(self.path.read_bytes(), before)

    def test_k2_abrupt_exit_after_durable_start_before_adapter(self):
        self.assertEqual(self.child("after_start"), 21)
        for _ in range(2):
            saved = self.read()
            self.assertFalse(saved["sealed"])
            self.assertNotIn("answer", saved["trace"])
            self.assertEqual(saved["audit"]["started_attempts"], 1)
            self.assertEqual(saved["audit"]["calls"], 0)
            self.assertEqual(saved["audit"]["unresolved_attempt_ids"], ["child:1:evidence:1"])
            self.assertIsNone(saved["audit"]["total_cost_usd"])
        self.assertEqual(self.call_count(), 0)

    def test_k3_abrupt_exit_after_external_simulation(self):
        self.assertEqual(self.child("after_adapter"), 22)
        before = self.path.read_bytes()
        for _ in range(2):
            saved = self.read()
            self.assertFalse(saved["sealed"])
            self.assertEqual(saved["audit"]["unresolved_attempt_ids"], ["child:1:evidence:1"])
            self.assertIsNone(saved["audit"]["total_cost_usd"])
        self.assertEqual(self.call_count(), 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_k4_semantic_mutations_rejected_even_with_valid_checksums(self):
        self.run_trace()
        original = self.records()
        mutations = {}
        duplicate = deepcopy(original)
        duplicate.insert(2, deepcopy(duplicate[1]))
        mutations["duplicate start"] = duplicate
        conflict = deepcopy(original)
        terminal = deepcopy(conflict[2])
        terminal["payload"]["event"]["text"] = "conflict"
        conflict.insert(3, terminal)
        mutations["second terminal"] = conflict
        wrong_run = deepcopy(original)
        wrong_run[1]["run_id"] = "other"
        mutations["cross-run envelope"] = wrong_run
        wrong_attempt = deepcopy(original)
        wrong_attempt[2]["payload"]["event"]["attempt_id"] = "other:1:evidence:1"
        mutations["cross-run attempt"] = wrong_attempt
        early = deepcopy(original[:2]) + deepcopy(original[-1:])
        mutations["premature closure"] = early
        extra = deepcopy(original) + deepcopy(original[-1:])
        mutations["after closure"] = extra
        leaked = deepcopy(original)
        leaked[1]["payload"]["event"]["messages"] = [{"text": "illegal"}]
        mutations["forbidden message"] = leaked
        for name, records in mutations.items():
            with self.subTest(name=name):
                self.replace_records(records)
                with self.assertRaises(JournalError):
                    self.read()

    def test_k4_corrupt_bytes_and_truncated_line_rejected_without_repair(self):
        self.run_trace()
        original = self.path.read_bytes()
        for malformed in (b"", original[:-1], original[:80],
                          original.replace(b'evidence', b'EVIDENCE', 1),
                          original + b"\xff\n", original.replace(b'"seq":0', b'"seq":0,"seq":0', 1)):
            with self.subTest(size=len(malformed)):
                self.path.write_bytes(malformed)
                with self.assertRaises(JournalError):
                    self.read()
                self.assertEqual(self.path.read_bytes(), malformed)

    def test_k5_known_failed_cost_and_provenance_roundtrip(self):
        from decimal import Decimal
        def fail(request):
            if request.round == 1 and request.role == "evidence":
                raise AdapterError("synthetic fault", Usage(3, 1, Decimal("0.03"), "synthetic"))
            return stub(request)
        trace = self.run_trace(adapter=fail)
        saved = self.read()
        self.assertEqual(saved["trace"], trace)
        self.assertTrue(saved["sealed"])
        self.assertEqual(trace["status"], "incomplete")
        self.assertEqual(saved["audit"]["failed_calls"], 1)
        self.assertEqual(saved["audit"]["total_cost_usd"], "0.07")
        self.assertEqual(saved["audit"]["synthetic_cost_calls"], 5)

    def test_k5_unknown_failed_cost_never_zero(self):
        def fail(request):
            if request.role == "aggregator":
                raise AdapterError("unknown synthetic cost")
            return stub(request)
        self.run_trace(adapter=fail)
        saved = self.read()
        self.assertEqual(saved["audit"]["known_cost_subtotal_usd"], "0.04")
        self.assertIsNone(saved["audit"]["total_cost_usd"])
        self.assertEqual(saved["audit"]["unknown_cost_calls"], 1)
        self.assertEqual(saved["trace"]["events"][-1]["usage"]["cost_source"], "unknown")

    def test_k6_existing_target_rejected_before_any_call(self):
        self.child("after_adapter")
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_trace(adapter=lambda _: self.fail("must not call"))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.call_count(), 1)

    def test_k7_all_configurations_and_separate_factors_roundtrip(self):
        for index, config in enumerate((*bank(), dense(), without_peers(self.config))):
            for rounds, fault in ((2, None), (1, None), (2, config.roles[0])):
                with self.subTest(config=config.config_id, rounds=rounds, fault=fault):
                    target = self.path.with_name(f"{index}-{rounds}-{fault}.jsonl")
                    trace = execute(TASK, config, stub, rounds=rounds, failed_role=fault,
                                    journal_path=target, run_id="matrix")
                    self.assertEqual(read_journal(target, config)["trace"], trace)

    def test_prefix_every_boundary_is_valid_but_never_sealed(self):
        self.run_trace()
        records = self.records()
        for end in range(1, len(records)):
            with self.subTest(end=end):
                self.replace_records(deepcopy(records[:end]))
                saved = self.read()
                self.assertFalse(saved["sealed"])
                self.assertIsNone(saved["audit"]["total_cost_usd"])
                self.assertNotIn("answer", saved["trace"])
        self.assertTrue(saved["audit"]["schedule_complete"])

    def test_writer_rejects_duplicate_start_before_changing_file(self):
        trace = execute(TASK, self.config, stub, run_id="test")
        header = {k: v for k, v in trace.items() if k not in ("answer", "status")}
        header["events"] = []
        with Journal(self.path, header, self.config) as journal:
            journal.append(trace["events"][0])
            before = self.path.read_bytes()
            with self.assertRaises(AuditError):
                journal.append(trace["events"][0])
            self.assertEqual(self.path.read_bytes(), before)

    def test_storage_failure_stops_before_adapter(self):
        original = Journal._write
        def fail_start(writer, payload):
            if payload["kind"] == "event":
                raise OSError("simulated full disk")
            original(writer, payload)
        with patch.object(Journal, "_write", fail_start), self.assertRaises(OSError):
            self.run_trace(adapter=lambda _: self.fail("must not call"))
        saved = self.read()
        self.assertEqual(saved["audit"]["started_attempts"], 0)
        self.assertIsNone(saved["audit"]["total_cost_usd"])

    def test_unexpected_adapter_error_is_preserved_as_unresolved(self):
        def broken(_):
            raise RuntimeError("synthetic programming error")
        with self.assertRaises(RuntimeError):
            self.run_trace(adapter=broken)
        self.assertEqual(self.read()["audit"]["unresolved_attempt_ids"], ["test:1:evidence:1"])

    def test_trusted_configuration_mismatch_rejected(self):
        self.run_trace()
        with self.assertRaises(JournalError):
            read_journal(self.path, bank()[1])

    def test_sync_before_each_adapter(self):
        import os
        original = os.fsync
        synced = []
        calls = []
        def sync(fd):
            original(fd)
            synced.append(fd)
        def adapter(request):
            self.assertEqual(len(synced), 2 + 2 * len(calls))
            calls.append(request.attempt_id)
            return stub(request)
        with patch("communication_pruning.journal.os.fsync", sync):
            self.run_trace(adapter=adapter)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len(synced), 12)  # Header, ten events, closure.

    def test_fsync_error_poison_writer(self):
        trace = execute(TASK, self.config, stub, run_id="test")
        header = {k: v for k, v in trace.items() if k not in ("answer", "status")}
        header["events"] = []
        with Journal(self.path, header, self.config) as journal:
            with patch("communication_pruning.journal.os.fsync", side_effect=OSError("sync failed")):
                with self.assertRaises(OSError):
                    journal.append(trace["events"][0])
            before = self.path.read_bytes()
            with self.assertRaises(JournalError):
                journal.append(trace["events"][0])
            self.assertEqual(self.path.read_bytes(), before)

    def test_terminal_write_error_stops_remaining_calls(self):
        original = Journal._write
        calls = []
        def adapter(request):
            calls.append(request.attempt_id)
            return stub(request)
        def fail_terminal(writer, payload):
            if payload.get("event", {}).get("kind") == "completed":
                raise OSError("simulated terminal write failure")
            original(writer, payload)
        with patch.object(Journal, "_write", fail_terminal), self.assertRaises(OSError):
            self.run_trace(adapter=adapter)
        self.assertEqual(calls, ["test:1:evidence:1"])
        self.assertEqual(self.read()["audit"]["unresolved_attempt_ids"], calls)
        self.assertIsNone(self.read()["audit"]["total_cost_usd"])

    def test_existing_sealed_target_and_symlink_rejected(self):
        self.run_trace()
        original = self.path.read_bytes()
        link = self.path.with_name("alias.jsonl")
        link.symlink_to(self.path)
        for target in (self.path, link):
            with self.subTest(target=target):
                with self.assertRaises(FileExistsError):
                    execute(TASK, self.config, lambda _: self.fail("must not call"), journal_path=target)
        self.assertEqual(self.path.read_bytes(), original)

    def test_sealed_writer_cannot_append_or_close_twice_as_new_run(self):
        trace = execute(TASK, self.config, stub, run_id="test")
        header = {k: v for k, v in trace.items() if k not in ("answer", "status")}
        header["events"] = []
        with Journal(self.path, header, self.config) as journal:
            for event in trace["events"]:
                journal.append(event)
            journal.finish(trace)
            before = self.path.read_bytes()
            with self.assertRaises(JournalError):
                journal.finish(trace)
            self.assertEqual(self.path.read_bytes(), before)
