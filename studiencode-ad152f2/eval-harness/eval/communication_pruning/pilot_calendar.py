"""The single predeclared Z42 calendar. Metadata only; no sampling or release."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
from zoneinfo import ZoneInfo

from .data import canonical, digest, validate_manifest


PHASE_ID = "Z42-PILOT-001"
SEED = "Z42-pilot-calendar-2026-09-14-v1"
SCHEMA = "z42-pilot-calendar/v1"
STARTS = (
    "2026-09-14T12:00:00", "2026-09-14T14:00:00", "2026-09-14T16:00:00",
    "2026-09-14T18:00:00", "2026-09-14T20:00:00", "2026-09-14T22:00:00",
    "2026-09-15T00:00:00", "2026-09-15T02:00:00", "2026-09-15T04:00:00",
    "2026-09-15T06:00:00", "2026-09-15T08:00:00", "2026-09-15T10:00:00",
)


def validate_bindings(bindings):
    if (not isinstance(bindings, dict) or not bindings
            or any(not isinstance(k, str) or not k or not isinstance(v, str)
                   or not re.fullmatch(r"[0-9a-f]{64}", v) for k, v in bindings.items())):
        raise ValueError("nonempty external SHA256 bindings required")


def utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware system time required")
    return value.astimezone(timezone.utc)


def window_interval(window):
    return tuple(datetime.fromisoformat(window[k]) for k in ("start_utc", "pair_start_before_utc", "end_utc"))


def require_pair_start(window, now):
    start, cutoff, _ = window_interval(window)
    if not start <= utc(now) < cutoff:
        raise ValueError("outside the bound pair-start interval")


def make_calendar(manifest, task_ids, *, bindings):
    validate_manifest(manifest)
    validate_bindings(bindings)
    if (not isinstance(task_ids, (list, tuple)) or len(task_ids) != 120
            or any(not isinstance(t, str) or not t for t in task_ids) or len(set(task_ids)) != 120):
        raise ValueError("exactly 120 unique externally selected IDs required")
    entries = {e["task_id"]: e for e in manifest["entries"]}
    selected = []
    for task_id in task_ids:
        e = entries.get(task_id)
        if e is None or e["phase"] != "pilot" or e["split"] != "train":
            raise ValueError("only selected eligible pilot train tasks allowed")
        selected.append(e)
    families = Counter(e["family_id"] for e in selected)
    if len(families) != 80 or max(families.values()) > 5:
        raise ValueError("bound 80-family panel with at most five tasks per family required")
    if Counter(e["hop"] for e in selected) != {2: 68, 3: 34, 4: 18}:
        raise ValueError("bound 68/34/18 hop composition required")
    windows, pairs, slots = [], [], []
    for i, value in enumerate(STARTS):
        start = datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Europe/Berlin"))
        end = start + timedelta(hours=1, minutes=45)
        windows.append({"window_id": f"W{i + 1:02d}", "repeat": i // 4 + 1,
                        "start_local": start.isoformat(), "start_utc": utc(start).isoformat(),
                        "end_utc": utc(end).isoformat(),
                        "pair_start_before_utc": utc(end - timedelta(minutes=30)).isoformat(),
                        "pairs": 30})
    for repeat in range(1, 4):
        def task_rank(task_id):
            return digest([SEED, "task-order", repeat, task_id]), task_id
        order = sorted(task_ids, key=task_rank)
        for block in range(4):
            window = windows[(repeat - 1) * 4 + block]
            wid = window["window_id"]
            members = order[block * 30:(block + 1) * 30]
            def arm_rank(task_id):
                return digest([SEED, "arm-order", repeat, wid, task_id]), task_id
            q_first = set(sorted(members, key=arm_rank)[:15])
            for task_id in members:
                entry = entries[task_id]
                pid = f"P{len(pairs) + 1:04d}"
                arms = ["Q", "F*"] if task_id in q_first else ["F*", "Q"]
                pair = {"pair_id": pid, "task_id": task_id, "family_id": entry["family_id"],
                        "hop": entry["hop"], "repeat": repeat, "window_id": wid,
                        "pair_index": len(pairs) + 1, "arm_order": arms,
                        "task_rank_tuple": [SEED, "task-order", repeat, task_id],
                        "task_rank_sha256": task_rank(task_id)[0],
                        "arm_rank_tuple": [SEED, "arm-order", repeat, wid, task_id],
                        "arm_rank_sha256": arm_rank(task_id)[0], "slot_ids": []}
                for position, arm in enumerate(arms, 1):
                    sid = f"S{len(slots) + 1:04d}"
                    pair["slot_ids"].append(sid)
                    slots.append({k: pair[k] for k in ("pair_id", "task_id", "family_id", "hop", "repeat", "window_id")}
                                 | {"slot_id": sid, "arm": arm, "position": position})
                pairs.append(pair)
    body = {"schema": SCHEMA, "phase_id": PHASE_ID, "seed": SEED,
            "timezone": "Europe/Berlin", "rank_encoding": "UTF-8 JSON arrays; ensure_ascii=True; separators=(',', ':'); SHA256; lexical task-ID tie break",
            "manifest_sha256": manifest["sha256"], "task_ids": list(task_ids),
            "task_ids_sha256": digest(list(task_ids)), "bindings": dict(bindings),
            "budget": {"cap_usd": "4.00", "reserve_usd": "0.14", "max_calls": 4320},
            "summary": {"tasks": 120, "families": 80, "hops": {"2": 68, "3": 34, "4": 18},
                        "pairs": 360, "slots": 720, "windows": 12, "repeats": 3},
            "windows": windows, "pairs": pairs, "slots": slots}
    return dict(body, sha256=digest(body))


def validate_calendar(plan, manifest, *, expected_bindings, expected_task_ids):
    expected = make_calendar(manifest, expected_task_ids, bindings=expected_bindings)
    # Canonical bytes also distinguish true from 1 and 1.0 from 1.
    if canonical(plan) != canonical(expected):
        raise ValueError("calendar differs from externally bound Z42 specification")
    return plan


def save_calendar(path, plan, manifest, *, expected_bindings, expected_task_ids):
    validate_calendar(plan, manifest, expected_bindings=expected_bindings, expected_task_ids=expected_task_ids)
    from .openrouter import save_new
    save_new(Path(path), canonical(plan) + b"\n")
