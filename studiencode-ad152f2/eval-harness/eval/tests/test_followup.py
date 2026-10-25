"""Z08 checks use only synthetic tasks, metadata, and fake provider responses."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from communication_pruning.audit import audit, AuditError
from communication_pruning.configurations import bank
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import ProbeAdapter, ProbeStop, decode_billing, encoded, payload
from communication_pruning.probe import TASK, audit_provider
from communication_pruning.followup import audit_costs, prepare, validate, prior_cost
from communication_pruning.musique_probe import run, sha
from test_openrouter import request, reply, endpoint
from test_technical import prepare_fixture


class FollowupTests(unittest.TestCase):
    def test_k1_rejected_text_keeps_known_cost_and_stops(self):
        for change in ("length", "empty", "error", "over_limit", "over_reservation"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                r = reply()
                if change == "length": r["choices"][0]["finish_reason"] = "length"
                if change == "empty": r["choices"][0]["message"]["content"] = ""
                if change == "error": r["error"] = {"code": 500}
                if change == "over_limit": r["usage"].update(completion_tokens=600, total_tokens=700)
                if change == "over_reservation": r["usage"]["cost"] = ".15"
                sent = []
                a = ProbeAdapter(tmp, lambda *args: (sent.append(1) or 200, encoded(r)))
                with self.assertRaises(ProbeStop): a(request())
                with self.assertRaises(ProbeStop): a(request(2))
                self.assertEqual(len(sent), 1)
                self.assertEqual(a.billed_calls, 1)
                self.assertEqual(a.cost, Decimal(str(r["usage"]["cost"])))
                events = [json.loads(x) for x in (Path(tmp)/"provider-ledger.jsonl").read_text().splitlines()]
                self.assertEqual([e["kind"] for e in events], ["reserved", "received", "billed", "stopped"])
                self.assertEqual(events[-1]["cost_status"], "provider")

    def test_k1_unknown_and_duplicate_do_not_count_as_zero_or_twice(self):
        for change in ("missing", "negative", "identity"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                r = reply()
                if change == "missing": del r["usage"]["cost"]
                if change == "negative": r["usage"]["cost"] = -1
                if change == "identity": r["model"] = "wrong"
                a = ProbeAdapter(tmp, lambda *args: (200, encoded(r)))
                with self.assertRaises(ProbeStop): a(request())
                self.assertEqual((a.calls, a.billed_calls), (1, 0))
        with tempfile.TemporaryDirectory() as tmp:
            a = ProbeAdapter(tmp, lambda *args: (200, encoded(reply())))
            a(request())
            with self.assertRaises(ProbeStop): a(request(2))
            self.assertEqual((a.calls, a.billed_calls), (2, 1))
            self.assertEqual(a.cost, Decimal(".0000108"))

    def test_k2_failed_billing_write_never_reports_durable_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = ProbeAdapter(tmp, lambda *args: (200, encoded(reply())))
            original = a.event
            def event(value):
                if value["kind"] == "billed": raise OSError("disk")
                original(value)
            with patch.object(a, "event", side_effect=event):
                with self.assertRaises(ProbeStop): a(request())
            self.assertEqual((a.billed_calls, a.cost), (0, Decimal(0)))
            with self.assertRaises(ProbeStop): a(request(2))

    def test_k3_limits_are_explicit_and_legacy_stays_512(self):
        for limit in (512, 1024):
            with tempfile.TemporaryDirectory() as tmp:
                sent = []
                def transport(_, body):
                    sent.append(json.loads(body)); return 200, encoded(reply(len(sent)))
                a = ProbeAdapter(tmp, transport, producer_limit=limit)
                trace = execute(TASK, bank()[0], a, producer_limit=limit, journal_path=Path(tmp)/"execution.jsonl")
                self.assertEqual(trace["schema"], 1 if limit == 512 else 2)
                self.assertEqual([p["max_tokens"] for p in sent], [limit]*4+[128])
                self.assertTrue(read_journal(Path(tmp)/"execution.jsonl", expected_config=bank()[0])["sealed"])
                audit_provider(tmp, trace)
                self.assertEqual(audit_costs(tmp, trace)["calls"], 5)
                bad = deepcopy(trace)
                bad["output_limits"] = {"producer": 512, "aggregator": 128}
                with self.assertRaises(AuditError): audit(bad, bank()[0])
                bad = deepcopy(trace); bad["events"][0]["max_output_tokens"] += 1
                with self.assertRaises(AuditError): audit(bad, bank()[0])
        with self.assertRaises(ProbeStop): payload(replace(request(), max_output_tokens=1024))
        self.assertEqual(payload(replace(request(), max_output_tokens=1024), producer_limit=1024)["max_tokens"], 1024)
        for limit in (True, 513, 2048):
            with self.assertRaises(ValueError): execute(TASK, bank()[0], None, producer_limit=limit)

    def test_k2_billing_audit_handles_stopped_trace_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = reply(); r["choices"][0]["finish_reason"] = "length"
            path = Path(tmp)/"execution.jsonl"
            with self.assertRaises(ProbeStop): execute(TASK, bank()[0], ProbeAdapter(tmp, lambda *a: (200, encoded(r))), journal_path=path)
            checked = read_journal(path, expected_config=bank()[0])
            self.assertFalse(checked["sealed"])
            self.assertEqual(audit_costs(tmp, checked["trace"])["total_cost_usd"], "0.0000108")
            ledger = Path(tmp)/"provider-ledger.jsonl"
            events = [json.loads(x) for x in ledger.read_text().splitlines()]
            events[2]["usage"]["cost_usd"] = "0"
            ledger.write_text("\n".join(json.dumps(e) for e in events)+"\n")
            with self.assertRaises(ProbeStop): audit_costs(tmp, checked["trace"])

    def test_k4_release_binds_plan_data_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepare_fixture(root)
            for name in ("Z07-LIVE-001.json", "Z07-RECONCILIATION.json", "Z08-PLAN.md"):
                (root/"project/dsr"/name).write_text("synthetic")
            budget = {"prior_cost_usd": ".001428", "new_reservation_usd": "1.40"}
            with patch("communication_pruning.followup.verify_sources", return_value="synthetic-hash"), patch("communication_pruning.followup.prior_cost", return_value=budget):
                prepare(root, "source.json")
                validate(root)
                with self.assertRaises(FileExistsError): prepare(root, "source.json")
                (root/"project/dsr/Z08-PLAN.md").write_text("changed")
                with self.assertRaises(ProbeStop): validate(root)

    def test_k4_prior_reconciles_legacy_stop_and_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dsr = root/"project/dsr"; dsr.mkdir(parents=True)
            folder = root/"eval-harness/eval/runs/Z07-OPENROUTER-001"; folder.mkdir(parents=True)
            for index in (1, 2):
                local = folder/f"task-{index:02}"; local.mkdir()
                sent = []
                def transport(*args):
                    sent.append(1); r = reply(index*10+len(sent))
                    if index == 2: r["choices"][0]["finish_reason"] = "length"
                    return 200, encoded(r)
                adapter = ProbeAdapter(local, transport)
                if index == 1: execute(TASK, bank()[0], adapter, journal_path=local/"execution.jsonl")
                else:
                    with self.assertRaises(ProbeStop): execute(TASK, bank()[0], adapter, journal_path=local/"execution.jsonl")
                ledger = local/"provider-ledger.jsonl"
                ledger.write_text("\n".join(line for line in ledger.read_text().splitlines() if json.loads(line)["kind"] != "billed")+"\n")
            (dsr/"old-source.zip").write_bytes(b"synthetic archive hash fixture")
            (dsr/"Z07-RUN-002.json").write_bytes(encoded({"source_bundle":"project/dsr/old-source.zip", "source_bundle_sha256":sha(dsr/"old-source.zip")}))
            rec = {"provider_reported_cost_usd":".0000648", "combined_z06_z07_provider_reported_cost_usd":".0001861"}
            (dsr/"Z07-RECONCILIATION.json").write_bytes(encoded(rec))
            live = {"run_id":"Z07-OPENROUTER-001", "evidence_folder":str(folder.relative_to(root)), "source_unchanged":True,
                    "calls_reserved":6, "files_sha256":{str(p.relative_to(folder)):sha(p) for p in folder.rglob("*") if p.is_file()}}
            (folder/"result.json").write_bytes(encoded(live)); (dsr/"Z07-LIVE-001.json").write_bytes(encoded(live))
            with patch("communication_pruning.followup.verify_prior", return_value={"prior_cost_usd":".0001213"}):
                self.assertEqual(prior_cost(root)["maximum_combined_usd"], "1.4001861")
                rec["combined_z06_z07_provider_reported_cost_usd"] = ".7000648"
                (dsr/"Z07-RECONCILIATION.json").write_bytes(encoded(rec))
                with patch("communication_pruning.followup.verify_prior", return_value={"prior_cost_usd":".7"}):
                    with self.assertRaises(ProbeStop): prior_cost(root)
                (folder/"task-02/01-response.json").write_text("changed")
                with self.assertRaises(ProbeStop): prior_cost(root)

    def integration(self, failure=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); selection = prepare_fixture(root)
            (root/"project/dsr/Z08-RELEASE.json").write_text("synthetic")
            selection["budget"] = {"prior_cost_usd": ".0014280", "new_reservation_usd": "1.40"}
            sent, loaded = [], []
            def transport(name, body=None):
                if name == "key": return 200, encoded({"data": {"is_free_tier": False, "limit_remaining": None}})
                if name.startswith("models/"): return 200, encoded(endpoint())
                sent.append(json.loads(body))
                if failure == "timeout": raise TimeoutError("private")
                r = reply(len(sent))
                if failure == "cross_duplicate" and len(sent) == 6: r = reply(1)
                if failure == "length": r["choices"][0]["finish_reason"] = "length"
                if failure == "missing": del r["usage"]["cost"]
                return 200, encoded(r)
            def loader(*args, **kwargs):
                loaded.append(1); return TASK, AnswerReference(TASK.task_id, ("Linden",))
            with patch("communication_pruning.followup.validate", return_value=(selection, {})), \
                 patch("communication_pruning.musique_probe.verify_sources", return_value="test-only"), \
                 patch("communication_pruning.musique_probe.load_key", return_value="synthetic"), \
                 patch("communication_pruning.musique_probe.Transport", return_value=transport), \
                 patch("communication_pruning.musique_probe.load_task", side_effect=loader):
                code = run(root, cycle="Z08")
                with self.assertRaises(FileExistsError): run(root, cycle="Z08")
            receipt = json.loads((root/"project/dsr/Z08-LIVE-001.json").read_text())
            self.assertEqual(code, 1 if failure else 0)
            self.assertEqual(len(sent), 6 if failure == "cross_duplicate" else 1 if failure else 10)
            self.assertEqual(len(loaded), 2 if failure == "cross_duplicate" else 1 if failure else 2)
            self.assertEqual(sent[0]["max_tokens"], 1024)
            if failure in ("timeout", "missing", "cross_duplicate"):
                self.assertIsNone(receipt["total_cost_usd"])
                self.assertEqual(receipt["unknown_cost_calls"], 1)
            else:
                self.assertEqual(receipt["total_cost_usd"], "0.0000108" if failure else "0.0001080")
                self.assertEqual(receipt["cost_coverage"], 1)

    def test_k6_synthetic_complete_batch(self): self.integration()
    def test_k2_rejected_but_fully_billed_batch(self): self.integration("length")
    def test_k2_unknown_timeout_batch(self): self.integration("timeout")
    def test_k2_unknown_missing_usage_batch(self): self.integration("missing")
    def test_k2_cross_task_duplicate_stops_before_next_call(self): self.integration("cross_duplicate")
