"""Bound N2/N4 integration: artificial observations survive real session changes."""
from pathlib import Path
import unittest

from communication_pruning.study import file_hash
from study_preparation import final_execution as execution, final_operator as operator
from study_preparation.final_resources import validate_observation
from tests.test_final_operator import OperatorFixture
from tests.test_final_preflight import trial_directory


class FinalRepairIntegrationTests(unittest.TestCase):
    def test_block_measurements_survive_fresh_sessions_and_checkpoint_early_return(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory, counts={"P": 2, "R": 1, "T": 1, "F": 1})
            first = f.run_session(1)
            initial = f.folder / "blocks/000000/spatial-measurement.json"
            before = (file_hash(initial), initial.stat().st_mtime_ns)
            first_session = f.session._session_id
            f.session = operator.Session(f.candidate_path)
            f.checkpoint = f.session.checkpoint
            for end in (2, 3, 4, 5):
                state = f.run_session(end)
            self.assertNotEqual(first_session, f.session._session_id)
            self.assertEqual((file_hash(initial), initial.stat().st_mtime_ns), before)
            calls = f.transport.calls
            recovered = execution.checkpoint_study(f.candidate, f.plan, **f.args(), checkpoint=f.checkpoint)
            self.assertEqual(recovered, state)
            self.assertEqual(f.transport.calls, calls)
            names = [name for name in state["evidence"] if name.endswith("-measurement.json")]
            self.assertEqual(len(names), 6)  # 5 spatial selections plus T's round selection.
            identities = []
            for name in names:
                record = execution.read_json(f.folder / name)
                validate_observation(record["process_observation"])
                self.assertEqual(record["status"], "completed")
                identities.append((record["identity"]["block_id"], record["identity"]["selector"]))
                self.assertNotIn("Invented question", str(record))
                self.assertNotIn("PRIVATE_FAKE_GOLD", str(record))
            self.assertEqual(len(set(identities)), 6)
            execution._verify_receipt(f.folder, state)
            self.assertTrue(set(first["evidence"]) <= set(state["evidence"]))

    def test_selector_failure_keeps_actual_measurement_and_original_error(self):
        with trial_directory() as directory:
            f = OperatorFixture(directory)
            block = execution._blocks(f.plan)[0]
            task, _ = f.loader(block["task_id"])
            target = Path(directory) / "failed-selection"
            target.mkdir()

            def fail(_task):
                raise ArithmeticError("artificial selector failure")

            with self.assertRaisesRegex(ArithmeticError, "artificial selector failure"):
                execution._select_observed(fail, task, candidate=f.candidate, plan=f.plan,
                    block=block, kind="spatial", directory=target)
            record = execution.read_json(target / "spatial-measurement.json")
            self.assertEqual(record["error_type"], "ArithmeticError")
            self.assertEqual(record["status"], "failed")
            self.assertIsNone(record["choice"])
            validate_observation(record["process_observation"])
            self.assertEqual(f.transport.calls, 0)

    def test_known_provider_paths_cover_six_digit_call_numbers(self):
        for index in (1, 99999, 100000, 271808):
            paths = execution._provider_files(Path("synthetic"), index)
            self.assertEqual(set(paths), {"request", "response", "binding", "billing", "received"})
            self.assertEqual({str(path) for path in paths.values()},
                {f"synthetic/provider/{index:05d}-{part}.json" for part in paths})


if __name__ == "__main__":
    unittest.main()
