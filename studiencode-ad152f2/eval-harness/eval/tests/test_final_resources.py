"""Z50 N3: known clock/RSS values; no provider, encoder or fitted model."""
from contextlib import ExitStack
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from study_preparation import final_resources as resources


def measured(*, platform="linux", rss=(10, 12), wall=(100, 400), cpu=(20, 80),
             utc=(1_000, 2_000), pids=(47, 47)):
    """Controlled readings, not claims about a real operating-system footprint."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(resources.sys, "platform", platform))
        stack.enter_context(patch.object(resources, "_maxrss", side_effect=rss))
        stack.enter_context(patch.object(resources.time, "perf_counter_ns", side_effect=wall))
        stack.enter_context(patch.object(resources.time, "process_time_ns", side_effect=cpu))
        stack.enter_context(patch.object(resources.time, "time_ns", side_effect=utc))
        stack.enter_context(patch.object(resources.os, "getpid", side_effect=pids))
        observation = resources.ProcessObservation()
        record = observation.finish()
        # A later finish must not extend the measurement or consume another read.
        repeated = observation.finish()
    return observation, record, repeated


class ProcessObservationTests(unittest.TestCase):
    def test_linux_known_units_and_exact_clock_ranges(self):
        observation, record, repeated = measured()
        resources.validate_observation(record)
        self.assertEqual(record["observation_status"], "complete")
        self.assertEqual(record["ru_maxrss_native_unit"], "KiB")
        self.assertEqual(record["peak_rss_start_bytes"], 10_240)
        self.assertEqual(record["peak_rss_end_bytes"], 12_288)
        self.assertEqual(record["wall_ns"], 300)
        self.assertEqual(record["process_cpu_ns"], 60)
        self.assertEqual(record["started_at_utc_ns"], 1_000)
        self.assertEqual(record["finished_at_utc_ns"], 2_000)
        self.assertEqual(record["scope"]["peak_rss"],
                         "current_process_peak_since_process_start_not_incremental_arm_memory")
        self.assertNotIn("rss_delta_bytes", record)
        self.assertEqual(record, repeated)
        repeated["scope"]["peak_rss"] = "changed by caller"
        self.assertEqual(observation.finish(), record)
        self.assertEqual(json.loads(json.dumps(record, allow_nan=False)), record)

    def test_macos_bytes_are_not_multiplied_and_equal_peak_is_valid(self):
        _, record, _ = measured(platform="darwin", rss=(4_096.0, 4_096.0))
        resources.validate_observation(record)
        self.assertEqual(record["ru_maxrss_native_unit"], "bytes")
        self.assertEqual(record["peak_rss_start_bytes"], 4_096)
        self.assertEqual(record["peak_rss_end_bytes"], 4_096)

    def test_cpu_can_exceed_wall_and_utc_correction_does_not_change_elapsed_time(self):
        _, record, _ = measured(cpu=(20, 620), utc=(2_000, 1_000))
        resources.validate_observation(record)
        self.assertEqual(record["process_cpu_ns"], 600)
        self.assertEqual(record["wall_ns"], 300)

    def test_rss_read_error_is_preserved_without_zero_or_exception_contents(self):
        _, record, _ = measured(rss=(10, OSError("artificial protected task text")))
        self.assertEqual(record["observation_status"], "incomplete")
        self.assertIsNone(record["ru_maxrss_end_raw"])
        self.assertIsNone(record["peak_rss_end_bytes"])
        self.assertEqual(record["peak_rss_start_bytes"], 10_240)
        self.assertEqual(record["wall_ns"], 300)
        self.assertEqual(record["errors"]["ru_maxrss_end_raw"], "read_failed")
        self.assertNotIn("protected task", json.dumps(record))
        resources.validate_observation(record, require_complete=False)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            resources.validate_observation(record)

    def test_unknown_platform_is_unavailable_without_guessed_unit(self):
        _, record, _ = measured(platform="unrecognized-os")
        self.assertIsNone(record["ru_maxrss_native_unit"])
        self.assertIsNone(record["peak_rss_start_bytes"])
        self.assertIsNone(record["peak_rss_end_bytes"])
        self.assertEqual(record["ru_maxrss_end_raw"], 12)
        resources.validate_observation(record, require_complete=False)
        with self.assertRaises(ValueError):
            resources.validate_observation(record)

    def test_invalid_rss_values_are_missing_not_imputed(self):
        for value in (None, True, 0, -1, 1.5, float("nan"), float("inf"), "12"):
            with self.subTest(value=value):
                _, record, _ = measured(rss=(10, value))
                self.assertIsNone(record["ru_maxrss_end_raw"])
                self.assertIsNone(record["peak_rss_end_bytes"])
                self.assertEqual(record["errors"]["ru_maxrss_end_raw"], "invalid_value")
                resources.validate_observation(record, require_complete=False)
                with self.assertRaises(ValueError):
                    resources.validate_observation(record)

    def test_missing_or_backward_clock_decreasing_peak_and_changed_process_fail_closed(self):
        cases = (
            ({"wall": (100, OSError("clock failed"))}, "wall_ns", "missing_input"),
            ({"cpu": (20, True)}, "process_cpu_ns", "missing_input"),
            ({"wall": (100, 99)}, "wall_ns", "nonmonotonic_counter"),
            ({"cpu": (20, 19)}, "process_cpu_ns", "nonmonotonic_counter"),
            ({"rss": (12, 10)}, "peak_rss_end_bytes", "decreasing_process_peak"),
            ({"pids": (47, 48)}, "process_identity", "process_changed"),
        )
        for kwargs, field, reason in cases:
            with self.subTest(kwargs=kwargs):
                _, record, _ = measured(**kwargs)
                self.assertEqual(record["errors"][field], reason)
                resources.validate_observation(record, require_complete=False)
                with self.assertRaises(ValueError):
                    resources.validate_observation(record)

    def test_saved_record_rejects_absence_unit_changes_tampering_and_invented_zero(self):
        _, valid, _ = measured()
        invalid = [None, {}, {k: v for k, v in valid.items() if k != "wall_ns"}]
        for key, value in (("wall_ns", 301), ("process_cpu_ns", True),
                           ("ru_maxrss_native_unit", "bytes"), ("peak_rss_end_bytes", 12),
                           ("ru_maxrss_end_raw", 0), ("observation_status", "incomplete"),
                           ("errors", {"peak_rss_end_bytes": "read_failed"})):
            candidate = deepcopy(valid)
            candidate[key] = value
            invalid.append(candidate)
        candidate = deepcopy(valid)
        candidate["peak_rss_end_bytes"] = None
        invalid.append(candidate)
        candidate = deepcopy(valid)
        candidate["scope"]["peak_rss"] = "arm_memory_usage"
        invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    resources.validate_observation(candidate, require_complete=False)
        _, missing, _ = measured(rss=(10, OSError("missing")))
        missing["peak_rss_end_bytes"] = 0
        with self.assertRaises(ValueError):
            resources.validate_observation(missing, require_complete=False)


if __name__ == "__main__":
    unittest.main()
