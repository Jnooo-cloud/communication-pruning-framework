"""P1/P3 synthetic tests and pinned calendar metadata; no raw task content."""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from communication_pruning.data import TaskMeta, families, make_manifest, digest
from communication_pruning.pilot_calendar import (SEED, make_calendar, save_calendar,
    validate_calendar, require_pair_start, window_interval)


def fixture():
    rows = [TaskMeta(f"invented-{i:03d}", "train", 2 if i < 68 else 3 if i < 102 else 4,
                     (f"family-{i // 2 if i < 80 else i - 40}",)) for i in range(120)]
    mapping = families(rows)
    manifest = make_manifest(rows, assignments={f: "pilot" for f in mapping.values()},
                             exposed_ids=[], seed="invented-panel", source_hashes={"train": "a" * 64})
    ids = [r.task_id for r in rows]
    bindings = {"raw_q": "b" * 64, "fixed": "c" * 64, "source": "a" * 64}
    return manifest, ids, bindings


class PilotCalendarTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.ids, self.bindings = fixture()
        self.plan = make_calendar(self.manifest, self.ids, bindings=self.bindings)

    def test_independent_counts_ranks_and_dates(self):
        p = self.plan
        self.assertEqual((len(p["pairs"]), len(p["slots"]), len(p["windows"])), (360, 720, 12))
        self.assertEqual(len({s["slot_id"] for s in p["slots"]}), 720)
        self.assertEqual(Counter(x["task_id"] for x in p["pairs"]), {t: 3 for t in self.ids})
        for w in p["windows"]:
            pairs = [x for x in p["pairs"] if x["window_id"] == w["window_id"]]
            self.assertEqual(Counter(x["arm_order"][0] for x in pairs), {"Q": 15, "F*": 15})
            start, cutoff, end = window_interval(w)
            self.assertEqual(end - start, timedelta(minutes=105))
            self.assertEqual(end - cutoff, timedelta(minutes=30))
        # Independently spell the rank encoding and four 30-pair partitions.
        def h(t):
            return sha256(json.dumps(t, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        for repeat in (1, 2, 3):
            observed = [x for x in p["pairs"] if x["repeat"] == repeat]
            order = sorted(self.ids, key=lambda t: (h([SEED, "task-order", repeat, t]), t))
            self.assertEqual([x["task_id"] for x in observed], order)
            for block in range(4):
                chunk = observed[block * 30:(block + 1) * 30]
                wid = chunk[0]["window_id"]
                first = sorted(chunk, key=lambda x: (h([SEED, "arm-order", repeat, wid, x["task_id"]]), x["task_id"]))[:15]
                self.assertEqual({x["task_id"] for x in first}, {x["task_id"] for x in chunk if x["arm_order"][0] == "Q"})
        for a, b in zip(p["slots"][::2], p["slots"][1::2]):
            self.assertEqual(a["pair_id"], b["pair_id"])
            self.assertEqual({a["arm"], b["arm"]}, {"Q", "F*"})

    def test_twelve_exact_r2_starts_and_intervals(self):
        # Written independently of the implementation's STARTS and time helpers.
        expected = (
            "2026-09-14T12:00:00+02:00", "2026-09-14T14:00:00+02:00",
            "2026-09-14T16:00:00+02:00", "2026-09-14T18:00:00+02:00",
            "2026-09-14T20:00:00+02:00", "2026-09-14T22:00:00+02:00",
            "2026-09-15T00:00:00+02:00", "2026-09-15T02:00:00+02:00",
            "2026-09-15T04:00:00+02:00", "2026-09-15T06:00:00+02:00",
            "2026-09-15T08:00:00+02:00", "2026-09-15T10:00:00+02:00",
        )
        self.assertEqual(tuple(w["start_local"] for w in self.plan["windows"]), expected)
        starts = []
        for i, (window, local) in enumerate(zip(self.plan["windows"], expected)):
            start = datetime.fromisoformat(local).astimezone(timezone.utc)
            cutoff, end = start + timedelta(minutes=75), start + timedelta(minutes=105)
            self.assertEqual(window["window_id"], f"W{i + 1:02d}")
            self.assertEqual(window["repeat"], i // 4 + 1)
            self.assertEqual(window["start_utc"], start.isoformat())
            self.assertEqual(window["pair_start_before_utc"], cutoff.isoformat())
            self.assertEqual(window["end_utc"], end.isoformat())
            require_pair_start(window, start)
            require_pair_start(window, cutoff - timedelta(microseconds=1))
            for outside in (start - timedelta(microseconds=1), cutoff, end):
                with self.assertRaises(ValueError):
                    require_pair_start(window, outside)
            starts.append(start)
        self.assertEqual([b - a for a, b in zip(starts, starts[1:])], [timedelta(hours=2)] * 11)
        self.assertEqual(end - starts[0], timedelta(hours=23, minutes=45))

    def test_original_pair_slot_and_budget_metadata_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        def pinned(relative, expected_hash):
            raw = (root / relative).read_bytes()
            self.assertEqual(sha256(raw).hexdigest(), expected_hash)
            return json.loads(raw)
        original = pinned("runs/Z42-PILOT-001/preparation/calendar.json",
                          "a55a9850939bf5820033dd3aa084395f2d0a328dcef40899c5455b9fe7a83280")
        manifest = pinned("runs/Z18-SPLIT-001/manifest.json",
                          "2a1f093a32105e3b4495c57b838503ee6a7ca0e48a511d8cd223f7a52183e159")
        bindings = dict(original["bindings"],
                        cycle_plan="9fc0562d889f666f8f3ac29aa0d7e7f6a4c844171d8bec845e488157e6c58e31")
        revised = make_calendar(manifest, original["task_ids"], bindings=bindings)
        self.assertEqual(len(revised["pairs"]), 360)
        self.assertEqual(len(revised["slots"]), 720)
        for key in original.keys() - {"windows", "bindings", "sha256"}:
            self.assertEqual(revised[key], original[key], key)
        self.assertEqual(revised["budget"], {"cap_usd": "4.00", "reserve_usd": "0.14", "max_calls": 4320})
        for old, new in zip(original["windows"], revised["windows"]):
            for key in ("window_id", "repeat", "pairs"):
                self.assertEqual(old[key], new[key])
        # Even with the current bindings and a new checksum, the old times fail.
        original["bindings"] = bindings
        original["sha256"] = digest({k: v for k, v in original.items() if k != "sha256"})
        with self.assertRaisesRegex(ValueError, "differs"):
            validate_calendar(original, manifest, expected_bindings=bindings,
                              expected_task_ids=original["task_ids"])
        with self.assertRaises(ValueError):
            require_pair_start(revised["windows"][0], datetime.fromisoformat("2026-09-14T14:00:00+02:00"))

    def test_bounds_and_schema_cannot_be_resigned(self):
        for field in ("seed", "schema", "phase_id"):
            changed = deepcopy(self.plan)
            changed[field] = "other"
            changed["sha256"] = digest({k: v for k, v in changed.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                validate_calendar(changed, self.manifest, expected_bindings=self.bindings, expected_task_ids=self.ids)
        changed = deepcopy(self.plan)
        changed["pairs"][0]["repeat"] = True
        with self.assertRaises(ValueError):
            validate_calendar(changed, self.manifest, expected_bindings=self.bindings, expected_task_ids=self.ids)
        for ids in (self.ids[:-1], self.ids[:-1] + [self.ids[0]], self.ids[:-1] + ["foreign"]):
            with self.assertRaises(ValueError):
                make_calendar(self.manifest, ids, bindings=self.bindings)

    def test_wrong_role_and_hop_panel(self):
        rows = [TaskMeta(e["task_id"], e["split"], e["hop"], tuple(e["subquestions"])) for e in self.manifest["entries"]]
        fmap = families(rows)
        for phase, exposed in (("spatial", []), ("unused", [self.ids[0]])):
            manifest = make_manifest(rows, assignments={f: phase for f in fmap.values()}, exposed_ids=exposed,
                                     seed="wrong", source_hashes={"train": "a" * 64})
            with self.assertRaises(ValueError):
                make_calendar(manifest, self.ids, bindings=self.bindings)
        rows[0] = TaskMeta(rows[0].task_id, "train", 3, rows[0].subquestions)
        manifest = make_manifest(rows, assignments={f: "pilot" for f in families(rows).values()}, exposed_ids=[],
                                 seed="wrong-hops", source_hashes={"train": "a" * 64})
        with self.assertRaises(ValueError):
            make_calendar(manifest, self.ids, bindings=self.bindings)

    def test_exact_time_boundary_and_create_only(self):
        window = self.plan["windows"][0]
        start, cutoff, end = window_interval(window)
        require_pair_start(window, start)
        require_pair_start(window, cutoff - timedelta(microseconds=1))
        for value in (start - timedelta(microseconds=1), cutoff, end, datetime(2026, 9, 14)):
            with self.assertRaises(ValueError):
                require_pair_start(window, value)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calendar.json"
            save_calendar(path, self.plan, self.manifest, expected_bindings=self.bindings, expected_task_ids=self.ids)
            with self.assertRaises(FileExistsError):
                save_calendar(path, self.plan, self.manifest, expected_bindings=self.bindings, expected_task_ids=self.ids)

    def test_prebound_five_task_family_maximum(self):
        rows = [TaskMeta(e["task_id"], e["split"], e["hop"], tuple(e["subquestions"])) for e in self.manifest["entries"]]
        # Merge three singleton families and split three original two-task families.
        # The panel still contains exactly 80 families and the same 120 task IDs.
        for i in (80, 81, 82):
            rows[i] = TaskMeta(rows[i].task_id, "train", rows[i].hop, rows[0].subquestions)
        for i in (3, 5, 7):
            rows[i] = TaskMeta(rows[i].task_id, "train", rows[i].hop, (f"new-family-{i}",))
        def manifest():
            return make_manifest(rows, assignments={f: "pilot" for f in families(rows).values()},
                                 exposed_ids=[], seed="family-five", source_hashes={"train": "a" * 64})
        make_calendar(manifest(), self.ids, bindings=self.bindings)
        rows[83] = TaskMeta(rows[83].task_id, "train", rows[83].hop, rows[0].subquestions)
        rows[9] = TaskMeta(rows[9].task_id, "train", rows[9].hop, ("new-family-9",))
        with self.assertRaises(ValueError):
            make_calendar(manifest(), self.ids, bindings=self.bindings)


if __name__ == "__main__":
    unittest.main()
