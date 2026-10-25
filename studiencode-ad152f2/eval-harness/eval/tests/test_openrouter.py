"""Z06 synthetic tests. No real transport or credentials used."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from communication_pruning.configurations import bank
from communication_pruning.contracts import INSTRUCTIONS, Request, Message
from communication_pruning.execution import execute
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import (MODEL, PROVIDER, RESERVE, ProbeAdapter, ProbeStop,
    Transport, NoRedirect, decode_response, encoded, load_key, payload, validate_endpoint)
from communication_pruning.probe import TASK, audit_provider


def reply(n=1):
    return {"id": f"gen-{n}", "model": MODEL, "provider": "Google",
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Linden"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 2, "total_tokens": 102,
                      "cost": 0.0000108, "is_byok": False,
                      "completion_tokens_details": {"reasoning_tokens": 0}}}


def endpoint():
    return {"data": {"id": MODEL, "endpoints": [{"tag": PROVIDER, "model_id": MODEL,
       "status": 0, "context_length": 1048576, "max_completion_tokens": 65535,
       "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
       "supported_parameters": ["reasoning", "temperature", "max_tokens"]}]}}


def request(n=1):
    return Request(f"run:{n}", TASK, "evidence", 1, INSTRUCTIONS["evidence"], (), 512)


class OpenRouterTests(unittest.TestCase):
    def test_k1_exact_payload_and_k2_limits(self):
        req = replace(request(), messages=(Message("prior", "linking", 1, "untrusted text"),))
        p = payload(req)
        content = json.loads(p["messages"][1]["content"])
        self.assertEqual(content["paragraphs"], list(TASK.paragraphs))
        self.assertEqual(content["question"], TASK.question)
        self.assertEqual(content["prior_messages"][0]["text"], "untrusted text")
        self.assertEqual(set(content), {"paragraphs", "question", "prior_messages"})
        self.assertEqual(p["provider"]["only"], [PROVIDER])
        self.assertFalse(p["provider"]["allow_fallbacks"])
        self.assertFalse(p["reasoning"]["enabled"])
        self.assertEqual(p["provider"]["max_price"], {"prompt": .1, "completion": .4, "request": 0})
        self.assertNotIn("tools", p)
        for count in (True, 0, 513):
            with self.assertRaises(ProbeStop): payload(replace(req, max_output_tokens=count))

    def test_z30_administrative_renaming_preserves_model_body(self):
        prior = (Message("run-A:1:linking:1", "linking", 1, "Supported answer."),)
        req = replace(request(), attempt_id="run-A:2:evidence:1", messages=prior)
        renamed = replace(req, attempt_id="run-B:2:evidence:1",
                          task=replace(req.task, task_id="renamed-task"),
                          messages=(replace(prior[0], attempt_id="run-B:1:linking:1"),))
        self.assertEqual(encoded(payload(req)), encoded(payload(renamed)))
        self.assertEqual(req.messages[0].attempt_id, "run-A:1:linking:1")
        self.assertEqual(renamed.messages[0].attempt_id, "run-B:1:linking:1")
        content = json.loads(payload(req)["messages"][1]["content"])
        self.assertNotIn("attempt_id", content["prior_messages"][0])

    def test_z30_message_meaning_and_order_remain_model_inputs(self):
        first = Message("internal", "linking", 1, "Literal internal ID: internal.")
        second = Message("other", "evidence", 1, "Second answer.")
        req = replace(request(), messages=(first, second))
        before = encoded(payload(req))
        content = json.loads(payload(req)["messages"][1]["content"])
        self.assertEqual(content["prior_messages"][0]["text"], first.text)
        variants = ((replace(first, role="checking"), second),
                    (replace(first, round=2), second),
                    (replace(first, text="Different answer."), second),
                    (second, first))
        for messages in variants:
            with self.subTest(messages=messages):
                self.assertNotEqual(before, encoded(payload(replace(req, messages=messages))))

    def test_k2_endpoint_price_version_and_reservation(self):
        validate_endpoint(encoded(endpoint()))
        self.assertLess(Decimal("1048576") * Decimal(".0000001") + Decimal("65535") * Decimal(".0000004"), RESERVE)
        for field, val in (("context_length", 2000000), ("status", 1), ("tag", "other")):
            e = endpoint(); e["data"]["endpoints"][0][field] = val
            with self.assertRaises(ProbeStop): validate_endpoint(encoded(e))
        e = endpoint(); e["data"]["endpoints"][0]["pricing"]["prompt"] = "0.0000002"
        with self.assertRaises(ProbeStop): validate_endpoint(encoded(e))

    def test_k3_reservation_before_send_and_max_five(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); sent = []
            def transport(path, body):
                ledger = [json.loads(s) for s in (folder / "provider-ledger.jsonl").read_text().splitlines()]
                self.assertEqual(ledger[-1]["kind"], "reserved")
                sent.append(body)
                return 200, encoded(reply(len(sent)))
            a = ProbeAdapter(folder, transport)
            for n in range(5): a(request(n))
            with self.assertRaises(ProbeStop): a(request(6))
            self.assertEqual(len(sent), 5)
            self.assertEqual(a.cost, Decimal(".0000540"))
            with self.assertRaises(FileExistsError): ProbeAdapter(folder, transport)

    def test_k3_duplicate_and_failed_save_never_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            a = ProbeAdapter(tmp, lambda *args: (calls.append(1) or 200, encoded(reply())))
            a(request())
            with self.assertRaises(ProbeStop): a(request())
            self.assertEqual(len(calls), 1)
        with tempfile.TemporaryDirectory() as tmp:
            calls = []; a = ProbeAdapter(tmp, lambda *args: calls.append(1))
            with patch("communication_pruning.openrouter.os.fsync", side_effect=OSError("disk")):
                with self.assertRaises(OSError): a(request())
            with self.assertRaises(ProbeStop): a(request(2))
            self.assertEqual(calls, [])

    def test_k3_timeout_stops_execution_and_leaves_open_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def fail(*args):
                calls.append(1)
                raise TimeoutError("sensitive provider detail")
            a = ProbeAdapter(tmp, fail); journal = Path(tmp) / "execution.jsonl"
            with self.assertRaises(ProbeStop): execute(TASK, bank()[0], a, journal_path=journal)
            self.assertEqual(len(calls), 1)
            self.assertFalse(read_journal(journal, expected_config=bank()[0])["sealed"])
            self.assertNotIn("sensitive", (Path(tmp) / "provider-ledger.jsonl").read_text())
            with self.assertRaises(ProbeStop): a(request())
            self.assertEqual(len(calls), 1)

    def test_k4_usage_and_identity_rejections(self):
        self.assertEqual(decode_response(encoded(reply()), 512)[0].usage.cost_usd, Decimal(".0000108"))
        bad = []
        for field, value in (("cost", -1), ("cost", None), ("cost", ".15"), ("cost", "NaN"),
                             ("prompt_tokens", True), ("completion_tokens", 513),
                             ("total_tokens", 1), ("is_byok", True)):
            r = reply(); r["usage"][field] = value; bad.append(r)
        r = reply(); del r["usage"]["cost"]; bad.append(r)
        r = reply(); r["model"] = "other"; bad.append(r)
        r = reply(); r["provider"] = "other"; bad.append(r)
        r = reply(); r["choices"][0]["finish_reason"] = "length"; bad.append(r)
        r = reply(); r["usage"]["completion_tokens_details"]["reasoning_tokens"] = 1; bad.append(r)
        for r in bad:
            with self.subTest(r=r):
                with self.assertRaises((ProbeStop, ValueError, KeyError)):
                    decode_response(encoded(r), 512)

    def test_k4_http_and_invalid_json_poison(self):
        for response in ((429, b'{}'), (200, b'not json'), (200, encoded({}))):
            with tempfile.TemporaryDirectory() as tmp:
                calls = []
                a = ProbeAdapter(tmp, lambda *args: (calls.append(1), response)[1])
                with self.assertRaises(ProbeStop): a(request())
                with self.assertRaises(ProbeStop): a(request(2))
                self.assertEqual(len(calls), 1)
                self.assertTrue((Path(tmp) / "01-response.json").exists())

    def test_k4_transport_no_redirect_or_arbitrary_endpoint(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere"))
        with self.assertRaises(ProbeStop): Transport("synthetic-key")("https://elsewhere")

    def test_k4_transport_header_only_and_secret_response_not_recorded(self):
        from unittest.mock import MagicMock
        t = Transport("synthetic-secret-key")
        response = MagicMock(); response.status = 200; response.read.return_value = b'{}'
        t._opener = MagicMock()
        t._opener.open.return_value.__enter__.return_value = response
        t("key")
        req = t._opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/key")
        self.assertEqual(req.get_header("Authorization"), "Bearer synthetic-secret-key")
        self.assertIsNone(req.data)
        response.read.return_value = b'synthetic-secret-key'
        with self.assertRaises(ProbeStop): t("key")

    def test_k3_response_write_failure_and_duplicate_generation_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def transport(*args):
                calls.append(1)
                return 200, encoded(reply())
            a = ProbeAdapter(tmp, transport)
            a(request())
            with self.assertRaises(ProbeStop): a(request(2))
            with self.assertRaises(ProbeStop): a(request(3))
            self.assertEqual(len(calls), 2)
        with tempfile.TemporaryDirectory() as tmp:
            calls = []; a = ProbeAdapter(tmp, lambda *args: (calls.append(1) or 200, encoded(reply())))
            (Path(tmp) / "01-response.json").touch()
            with self.assertRaises(ProbeStop): a(request())
            with self.assertRaises(ProbeStop): a(request(2))
            self.assertEqual(len(calls), 1)

    def test_k4_key_file_not_executed_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {}, clear=True):
            p = Path(tmp) / "env"
            p.write_text('OTHER=ignored\nOPENROUTER_API_KEY="synthetic-key"\n')
            self.assertEqual(load_key(p), "synthetic-key")
            p.write_text('OPENROUTER_API_KEY=$(bad)\n')
            with self.assertRaises(ProbeStop): load_key(p)
            p.write_text('OPENROUTER_API_KEY=a\nOPENROUTER_API_KEY=b\n')
            with self.assertRaises(ProbeStop): load_key(p)

    def test_k7_explicit_source_no_shadowing_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"OPENROUTER_API_KEY": "environment-key"}):
            p = Path(tmp) / "env"
            p.write_text('OPENROUTER_API_KEY="project-key"\n')
            self.assertEqual(load_key(p, source="file"), "project-key")
            self.assertEqual(load_key(p, source="environment"), "environment-key")
            with self.assertRaises(ProbeStop): load_key(p, source="automatic")
            p.write_text('OTHER=ignored\n')
            with self.assertRaises(ProbeStop): load_key(p, source="file")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ProbeStop): load_key("unused", source="environment")

    def test_k6_synthetic_integration_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def transport(*args):
                calls.append(1)
                return 200, encoded(reply(len(calls)))
            a = ProbeAdapter(tmp, transport)
            trace = execute(TASK, bank()[0], a, run_id="synthetic", journal_path=Path(tmp) / "execution.jsonl")
            self.assertEqual(audit_provider(tmp, trace)["cost_usd"], "0.0000540")
            altered = deepcopy(trace); altered["events"][1]["text"] = "wrong"
            with self.assertRaises(ProbeStop): audit_provider(tmp, altered)
            p = Path(tmp) / "01-request.json"; obj = json.loads(p.read_text()); obj["model"] = "other"
            p.write_bytes(encoded(obj))
            with self.assertRaises(ProbeStop): audit_provider(tmp, trace)
