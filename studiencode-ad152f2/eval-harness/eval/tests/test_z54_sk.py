"""Z54 S-k correction: payload, sender hook, run/verify, cost brake (offline, synthetic transport)."""
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(EVAL / "runs/Z53-SCHNELLFORTSETZUNG-001"))

from communication_pruning.contracts import Message, Request, TaskInput  # noqa: E402
from communication_pruning.openrouter import encoded, payload  # noqa: E402
from study_preparation import final_execution as nx  # noqa: E402
from study_preparation import final_preflight as gate  # noqa: E402
from study_preparation import z53_fast as z  # noqa: E402
from study_preparation import z54_sk as k  # noqa: E402
import fake_transport  # noqa: E402

TASK = TaskInput("opaque-1", "Who?", ("Para one.", "Para two."))
RUN_ID = "50d4c906a74daf48:Z50-STUDY-v1:R:00007:S-k"
OLD_INDEX = EVAL / "runs/Z54-SK-KORREKTUR-001/OLD-INDEX.json"


class Scripted:
    """Answers in order: str -> billed answer; ('length',) -> F-01 length failure; int -> HTTP status."""

    def __init__(self, script):
        self.script, self.bodies = list(script), []

    def __call__(self, endpoint, body):
        self.bodies.append(body)
        item = self.script.pop(0)
        if isinstance(item, int):
            return item, b'{"error": {"code": %d}}' % item
        gen = f"gen-test-{uuid.uuid4().hex}"
        if item == ("length",):
            return 200, fake_transport.answer(gen, "", finish="length", out=json.loads(body)["max_tokens"])
        if item == ("overlimit",):
            return 200, fake_transport.answer(gen, "x", finish="length", out=json.loads(body)["max_tokens"] + 1)
        return 200, fake_transport.answer(gen, item)


def no_sleep(_):
    pass


class PayloadTests(unittest.TestCase):
    def test_sk_body_is_base_plus_exactly_two_fields(self):
        request = nx._direct_request(TASK, RUN_ID, 0)
        base = payload(request, producer_limit=1024)
        sent = json.loads(k.sk_body(request))
        self.assertEqual(set(sent) - set(base), {"top_p"})
        self.assertEqual(sent, {**base, "temperature": 1.0, "top_p": 0.9})
        self.assertEqual({key for key in base if base[key] != sent[key]}, {"temperature"})
        self.assertEqual(k.sk_body(request), encoded({**base, "temperature": 1.0, "top_p": 0.9}))

    def test_only_sk_requests_accepted(self):
        s_request = nx._direct_request(TASK, RUN_ID[:-4] + ":S", 0)          # arm S
        producer = Request(RUN_ID + ":p:1", TASK, "producer", 1, "Find evidence.", (), 1024)
        aggregator = Request(RUN_ID + ":a:1", TASK, "aggregator", 2, "Aggregate.",
                             (Message("x", "producer", 1, "t"),), 128)
        for request in (s_request, producer, aggregator):
            with self.assertRaises(z.GlobalStop):
                k.sk_body(request)

    def test_default_blocksender_bytes_unchanged(self):
        """Hook default equals the pre-Z54 construction for every request type."""
        requests = [nx._direct_request(TASK, RUN_ID, 0),
                    Request("x:p:1", TASK, "producer", 1, "Find evidence.", (), 1024),
                    Request("x:a:1", TASK, "aggregator", 2, "Aggregate.", (Message("x", "producer", 1, "t"),), 128)]
        with tempfile.TemporaryDirectory() as tmp:
            sender = z.BlockSender(Path(tmp) / "p", Scripted([]), max_calls=5, deadline=9e99)
            for request in requests:
                self.assertEqual(sender._body(request), encoded(payload(request, producer_limit=1024)))
                self.assertNotIn(b"top_p", sender._body(request))

    def test_original_source_construction_preserved(self):
        """The only z53_fast.py change is the hook; the body line was moved verbatim into _body."""
        source = (EVAL / "study_preparation/z53_fast.py").read_text()
        self.assertEqual(source.count("encoded(payload(request, producer_limit=1024))"), 2)  # _body + verify_block
        self.assertIn("body = self._body(request)", source)

    def test_senders_write_expected_bytes_and_hash(self):
        request = nx._direct_request(TASK, RUN_ID, 0)
        with tempfile.TemporaryDirectory() as tmp:
            plain = z.BlockSender(Path(tmp) / "a", Scripted(["Paris"]), max_calls=5, deadline=9e99)
            plain(request)
            sk = k.SkSender(Path(tmp) / "b", Scripted(["Paris"]), max_calls=5, deadline=9e99)
            sk(request)
            for directory, body in ((Path(tmp) / "a", encoded(payload(request, producer_limit=1024))),
                                    (Path(tmp) / "b", k.sk_body(request))):
                self.assertEqual((directory / "001-request.json").read_bytes(), body)
                binding = json.loads((directory / "001-binding.json").read_bytes())
                self.assertEqual(binding["request_sha256"], z.sha256(body).hexdigest())

    def test_parameter_rejection_is_global_stop(self):
        request = nx._direct_request(TASK, RUN_ID, 0)
        with tempfile.TemporaryDirectory() as tmp:
            sender = k.SkSender(Path(tmp) / "p", Scripted([400]), max_calls=5, deadline=9e99)
            with self.assertRaises(z.GlobalStop):
                sender(request)


class CostCapTests(unittest.TestCase):
    def test_cap_boundaries(self):
        self.assertEqual(k.BLOCK_RESERVE, Decimal("1.40"))
        self.assertTrue(k.cap_ok(Decimal("0"), 0, 2))                 # 3 * 1.40 = 4.20
        self.assertFalse(k.cap_ok(Decimal("0"), 0, 3))                # 4 * 1.40 = 5.60
        self.assertTrue(k.cap_ok(Decimal("3.60"), 0, 0))              # 3.60 + 1.40 = 5.00
        self.assertFalse(k.cap_ok(Decimal("3.61"), 0, 0))
        self.assertFalse(k.cap_ok(Decimal("3.50"), 1, 0))             # unknown attempt reserves 0.14
        with self.assertRaises(z.GlobalStop):
            k.cap_ok(Decimal("0"), 0, 0, cap="5.01")

    def test_worst_case_block_stays_within_reserve(self):
        """Max transport errors + max billed answers of one block attempt never exceed BLOCK_RESERVE."""
        script = [z.ProbeStop("t"), "a", z.ProbeStop("t"), "b", z.ProbeStop("t"), "c",
                  z.ProbeStop("t"), "d", z.ProbeStop("t"), z.ProbeStop("t")]

        class Raising(Scripted):
            def __call__(self, endpoint, body):
                if isinstance(self.script[0], Exception):
                    self.bodies.append(body)
                    raise self.script.pop(0)
                return super().__call__(endpoint, body)
        with tempfile.TemporaryDirectory() as tmp:
            sender = k.SkSender(Path(tmp) / "p", Raising(script), max_calls=5, deadline=9e99, sleep=no_sleep)
            with self.assertRaises(z.TechnicalAbort):
                for i in range(5):
                    sender(nx._direct_request(TASK, RUN_ID, i))
            worst = len(sender.costs) * k.RESERVE + sender.unknown_attempts * k.RESERVE
            self.assertEqual((len(sender.costs), sender.unknown_attempts), (4, 6))
            self.assertLessEqual(worst, k.BLOCK_RESERVE)


class GuardTests(unittest.TestCase):
    def test_old_trees_not_writable(self):
        sys.path.insert(0, str(EVAL / "runs/Z54-SK-KORREKTUR-001"))
        import run_z54
        for bad in (run_z54.Z53 / "live", run_z54.Z52 / "live/blocks", run_z54.Z53):
            with self.assertRaises(z.GlobalStop):
                run_z54.guard_write(bad)
        self.assertEqual(run_z54.guard_write(run_z54.HERE / "live"), run_z54.HERE / "live")


@unittest.skipUnless(OLD_INDEX.exists(), "needs local study context and old-block index")
class BlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = z.Context(with_selectors=False)
        cls.index = json.loads(OLD_INDEX.read_bytes())["index"]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_block(self, script, index=7):
        block = self.ctx.block("R", index)
        transport = Scripted(script)
        directory = self.tmp / f"R-{index}"
        k.run_sk_block(self.ctx, block, directory, transport, deadline=9e99, sleep=no_sleep)
        return block, directory, transport

    def test_five_samples_plurality_and_verify(self):
        block, directory, transport = self.run_block(["Paris", "London", "paris", "Berlin", "London"])
        rows = k.verify_sk_block(self.ctx, directory, Path(self.index["7"]))
        (row,) = rows
        self.assertEqual((row["arm"], row["call_count"], row["status"]), ("S-k", 5, "ok"))
        summary = json.loads((directory / "S-k/direct-complete.json").read_bytes())
        # plurality: 'paris' and 'london' tie with 2 votes each -> PCG64 with the bound tie seed
        expected = nx.plurality(["Paris", "London", "paris", "Berlin", "London"], block["tie_break_seed"])
        self.assertEqual(summary["vote"], expected)
        self.assertEqual(sorted(expected["tie_classes"]), ["london", "paris"])
        for body in transport.bodies:
            sent = json.loads(body)
            self.assertEqual((sent["temperature"], sent["top_p"]), (1.0, 0.9))
        self.assertEqual(k.sample_texts(directory), ["Paris", "London", "paris", "Berlin", "London"])

    def test_f01_failure_on_third_sample(self):
        _, directory, _ = self.run_block(["Paris", "Paris", ("length",)])
        (row,) = k.verify_sk_block(self.ctx, directory, Path(self.index["7"]))
        self.assertEqual((row["status"], row["call_count"], row["em"]), ("model_failure", 3, 0.0))

    def test_overlimit_is_terminal_arm_failure(self):
        _, directory, _ = self.run_block(["Paris", ("overlimit",)])
        (row,) = k.verify_sk_block(self.ctx, directory, Path(self.index["7"]))
        self.assertEqual((row["status"], row["call_count"], row["failure_reason"]),
                         ("model_failure", 2, z.OVERLIMIT_REASON))

    def test_immediate_terminal_failure_checks_old_request(self):
        _, directory, _ = self.run_block([("overlimit",)])
        (row,) = k.verify_sk_block(self.ctx, directory, Path(self.index["7"]))
        self.assertEqual((row["status"], row["call_count"]), ("model_failure", 1))
        self.assertEqual(list((directory / "S-k").glob("direct-[1-5].json")), [])
        with self.assertRaises(z.GlobalStop):
            k.verify_sk_block(self.ctx, directory, Path(self.index["8"]))

    def test_rate_limit_resend_identical_bytes(self):
        _, directory, transport = self.run_block([429, "Paris", "Paris", "Paris", "Paris", "Paris"])
        k.verify_sk_block(self.ctx, directory, Path(self.index["7"]))
        self.assertEqual(transport.bodies[0], transport.bodies[1])

    def test_base_payload_block_fails_verification(self):
        """A block sent without the sampling fields (plain BlockSender) must not verify."""
        original = k.SkSender
        k.SkSender = z.BlockSender
        try:
            _, directory, _ = self.run_block(["Paris"] * 5)
        finally:
            k.SkSender = original
        with self.assertRaises(z.GlobalStop):
            k.verify_sk_block(self.ctx, directory)

    def test_tampered_request_fails(self):
        _, directory, _ = self.run_block(["Paris"] * 5)
        path = directory / "provider/001-request.json"
        path.chmod(0o600)
        data = json.loads(path.read_bytes())
        del data["top_p"]
        path.write_bytes(encoded(data))
        with self.assertRaises(z.GlobalStop):
            k.verify_sk_block(self.ctx, directory)

    def test_input_mismatch_with_old_block_fails(self):
        _, directory, _ = self.run_block(["Paris"] * 5)
        with self.assertRaises(z.GlobalStop):
            k.verify_sk_block(self.ctx, directory, Path(self.index["8"]))   # other task

    def test_collect_gate_rechecks_current_raw_evidence(self):
        """verify_all (used by collect) fails on raw evidence changed after an earlier passed verification."""
        sys.path.insert(0, str(EVAL / "runs/Z54-SK-KORREKTUR-001"))
        import run_z54
        folder = self.tmp / "live"
        (folder / "blocks").mkdir(parents=True)
        k.run_sk_block(self.ctx, self.ctx.block("R", 7), folder / "blocks/R-00007", Scripted(["Paris"] * 5),
                       deadline=9e99, sleep=no_sleep)
        self.assertEqual(run_z54.verify_all(folder, workers=1), (1, []))
        response = folder / "blocks/R-00007/provider/003-p01-response.json"
        response.chmod(0o600)
        response.write_bytes(response.read_bytes().replace(b"Paris", b"Lyon!"))
        verified, failures = run_z54.verify_all(folder, workers=1)
        self.assertEqual(verified, 0)
        self.assertIn("evidence changed", failures[0]["error"])
        extra = folder / "blocks/R-00007/S-k/extra.json"
        response.write_bytes(response.read_bytes().replace(b"Lyon!", b"Paris"))
        extra.write_bytes(b"{}")
        self.assertIn("unlisted", run_z54.verify_all(folder, workers=1)[1][0]["error"])

    def test_old_z53_blocks_still_verify(self):
        """Hook default unchanged: Z53 blocks recompute byte-identically with the edited z53_fast."""
        for index in (2183, 2500, 2951):
            rows = z.verify_block(self.ctx, Path(self.index[str(index)]).parent / z.block_name("R", index))
            self.assertEqual(len(rows), 6)


if __name__ == "__main__":
    unittest.main()
