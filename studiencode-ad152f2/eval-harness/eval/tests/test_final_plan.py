"""Artificial metadata and prescribed draws; no empirical or calibration data."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

import numpy as np

from study_preparation import final_plan
from study_preparation.final_plan import ARMS, DEFAULT_COUNTS, canonical_hash, make_plan, validate_plan


FRAME = [{"task_id": "one", "family_id": "small"},
         {"task_id": "two", "family_id": "large"},
         {"task_id": "three", "family_id": "large"},
         {"task_id": "four", "family_id": "large"}]
BINDINGS = {"fixture": "a" * 64}


def plan(counts=None, frame=None, **kwargs):
    return make_plan(FRAME if frame is None else frame, seed_base=20260920,
                     bindings=BINDINGS, mode="artificial_only",
                     counts={key: 3 for key in ARMS} if counts is None else counts, **kwargs)


def reseal(value):
    value["plan_hash"] = canonical_hash({key: item for key, item in value.items() if key != "plan_hash"})
    return value


class PrescribedRng:
    def __init__(self, numbers=()):
        self.numbers = iter(numbers)
        self.bounds = []

    def integers(self, low, high=None):
        low, high = (0, low) if high is None else (low, high)
        self.bounds.append((low, high))
        value = next(self.numbers, low)
        if not low <= value < high:
            raise AssertionError("prescribed value is outside requested bounds")
        return value

    def permutation(self, size):
        return np.arange(size)


class FinalPlanTests(unittest.TestCase):
    def test_repeated_task_has_fresh_complete_blocks_and_slots(self):
        actual = plan(frame=FRAME[:1])
        all_slots, all_blocks = [], []
        for panel, arms in ARMS.items():
            for index, block in enumerate(actual["panels"][panel]):
                self.assertEqual(block["draw_index"], index)
                self.assertEqual(block["task_id"], "one")
                self.assertEqual(set(block["arm_order"]), set(arms))
                self.assertEqual([slot["arm"] for slot in block["slots"]], block["arm_order"])
                self.assertEqual(len(block["slots"]), len(arms))
                self.assertEqual(block["block_id"], f"Z50-STUDY-v1:{panel}:{index:05d}")
                all_blocks.append(block["block_id"])
                all_slots.extend(slot["slot_id"] for slot in block["slots"])
        self.assertEqual(len(all_blocks), 12)
        self.assertEqual(len(set(all_blocks)), 12)
        self.assertEqual(len(all_slots), 42)
        self.assertEqual(len(set(all_slots)), 42)
        self.assertIs(validate_plan(actual), actual)

    def test_fault_draw_uses_size_weighted_family_then_uniform_member(self):
        # Four equally likely family tickets: one for small, three for large.
        streams = [PrescribedRng() for _ in range(11)]
        fault_draw = streams[8] = PrescribedRng([0, 0, 1, 0, 2, 1, 3, 2])
        with patch.object(final_plan.np.random, "Generator", side_effect=streams):
            actual = plan(counts={"P": 1, "R": 1, "T": 1, "F": 4})
        self.assertEqual([block["task_id"] for block in actual["panels"]["F"]],
                         ["one", "two", "three", "four"])
        self.assertEqual(fault_draw.bounds,
                         [(0, 4), (0, 1), (0, 4), (0, 3), (0, 4), (0, 3), (0, 4), (0, 3)])

    def test_stream_seed_contract_and_panel_independence(self):
        first = plan()
        longer = plan(counts={"P": 5, "R": 3, "T": 3, "F": 3})
        self.assertEqual(first, plan())
        for panel in ("R", "T", "F"):
            self.assertEqual(first["panels"][panel], longer["panels"][panel])
        self.assertEqual(first["panels"]["P"], longer["panels"]["P"][:3])
        seeds = first["randomization"]["streams"]
        values = [seed for streams in seeds.values() for seed in streams.values()]
        self.assertEqual(len(values), len(set(values)))
        payload = json.dumps(["Z50-final-plan-v1", "Z50-STUDY-v1", 20260920, "R", "z"],
                             sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        expected_seed = int.from_bytes(hashlib.sha256(payload).digest()[:16], "little")
        self.assertEqual(seeds["R"]["z"], expected_seed)
        z_rng = np.random.Generator(np.random.PCG64(expected_seed))
        self.assertEqual([block["z_configuration"] for block in first["panels"]["R"]],
                         [f"C{int(z_rng.integers(1, 15)):02d}" for _ in range(3)])
        for block in first["panels"]["F"]:
            self.assertEqual(set(block["fault_permutation"]), {"evidence", "linking", "draft", "checking"})

    def test_full_live_counts_are_fixed_and_bindings_required(self):
        self.assertEqual(DEFAULT_COUNTS, {"P": 9040, "R": 2952, "T": 2952, "F": 2952})
        complete = {name: "b" * 64 for name in final_plan.REQUIRED_BINDINGS}
        with self.assertRaisesRegex(ValueError, "live counts"):
            make_plan(FRAME, seed_base=1, bindings=complete, counts={key: 2 for key in ARMS})
        with self.assertRaisesRegex(ValueError, "required external bindings"):
            make_plan(FRAME, seed_base=1, bindings=BINDINGS)

    def test_resealed_incomplete_or_foreign_plan_is_rejected(self):
        source = plan()
        mutations = [
            lambda p: p["panels"]["P"].pop(),
            lambda p: p["panels"]["R"][0]["slots"].pop(),
            lambda p: p["panels"]["F"][0]["slots"].append(p["panels"]["F"][0]["slots"][0]),
            lambda p: p["panels"]["P"][0].update(task_id="foreign"),
            lambda p: p["panels"]["P"][0].update(family_id="foreign"),
            lambda p: p["panels"]["P"][0].update(draw_index=False),
            lambda p: p["panels"]["R"][0].update(z_configuration="C15"),
            lambda p: p["panels"]["F"][0].update(fault_permutation=["evidence"] * 4),
            lambda p: p["panels"]["T"][0]["slots"][0].update(arm="Q"),
            lambda p: p["panels"]["P"][0]["slots"][0].update(slot_id="elsewhere"),
            lambda p: p["panels"]["P"].append(p["panels"]["P"][0]),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = deepcopy(source)
                mutate(changed)
                with self.assertRaises(ValueError):
                    validate_plan(reseal(changed))

    def test_input_schema_and_safe_ids(self):
        bad_frames = [[], [FRAME[0], FRAME[0]], [{"task_id": "one"}],
                      [{**FRAME[0], "question": "forbidden content field"}],
                      [{"task_id": "../one", "family_id": "family"}],
                      [{"task_id": "one", "family_id": "family\n"}],
                      [{"task_id": "one", "family_id": float("nan")}]]
        for frame in bad_frames:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                plan(frame=frame)
        for counts in ({"P": 1}, {**DEFAULT_COUNTS, "X": 1}, {**DEFAULT_COUNTS, "R": 0},
                       {**DEFAULT_COUNTS, "P": True}, {**DEFAULT_COUNTS, "T": 2.0}):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                plan(counts=counts)
        for study_id in ("../study", "study/child", "study\\child", "study\n", ""):
            with self.subTest(study_id=study_id), self.assertRaises(ValueError):
                plan(study_id=study_id)
        for seed in (-1, True, 1.0):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                make_plan(FRAME, seed_base=seed, bindings=BINDINGS, mode="artificial_only")
        for bindings in ({}, {"fixture": "NaN"}, {"fixture": "A" * 64}, {"../x": "a" * 64}):
            with self.subTest(bindings=bindings), self.assertRaises(ValueError):
                make_plan(FRAME, seed_base=1, bindings=bindings, mode="artificial_only")

    def test_hash_is_canonical_and_rejects_nonfinite_json(self):
        self.assertEqual(canonical_hash({"b": 1, "a": 2}), canonical_hash({"a": 2, "b": 1}))
        self.assertNotEqual(canonical_hash({"a": True}), canonical_hash({"a": 1}))
        for value in (float("nan"), float("inf"), {1, 2}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_hash(value)


if __name__ == "__main__":
    unittest.main()
